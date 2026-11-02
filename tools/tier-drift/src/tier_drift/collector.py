#!/usr/bin/env python3
"""tier-drift host collector.

Reads this machine's agent session logs and prints ONE JSON document of
aggregates to stdout. It never emits prompt text, file paths or session ids.

This file is piped over ssh to other hosts and run by whatever `python3`
they have, so it must stay self-contained and run on Python 3.6:
stdlib only, no walrus, no removeprefix, no datetime.fromisoformat, no
built-in generic annotations. tests/test_collector_floor.py enforces both.

    python3 collector.py [BASE64_JSON_CONFIG]
    ssh host python3 - BASE64_JSON_CONFIG < collector.py

Counting rules. Each one exists because the naive version was measured to be
wrong on real logs; do not simplify one away without re-measuring.

 1. Claude writes several assistant records per API request (a thinking
    block, then text or tool use), each carrying a CUMULATIVE usage
    snapshot. One request = one turn; its usage is the MAX of each field.
 2. Resumed and forked Claude sessions copy their parent's history into a
    NEW file, so a requestId can appear in several files (8.6% of responses
    on one host). Requests are deduplicated across the whole host; the
    earliest file claims each one.
 3. Output tokens are only trustworthy where the terminal record (the one
    with a stop_reason) was written. Older Claude Code builds wrote only
    streaming partials, so per-model terminal coverage is emitted and the
    report decides whether to show output tokens at all.
 4. Codex logs a cumulative total_token_usage per session. Summing the
    per-turn last_token_usage overcounts (it is re-emitted), and summing
    per-session maxima double-counts forks, which inherit the parent's
    events. So: walk events in time order across the host, skip events
    already seen in another file, count only growth of the counter, and
    treat a decrease as a reset that starts a new segment from zero.
 5. Forked Codex sessions also copy assistant messages; turns are
    deduplicated across files on (timestamp, content digest).
 6. Gemini CLI rewrites the whole message array on each `$set`, so the same
    message appears in many snapshots (2.49x overcount). Turns are
    deduplicated by message id.
 7. Antigravity keeps transcripts under a hidden `.system_generated/` dir,
    which glob() will not descend into even with `**`. Every source is
    therefore walked with os.walk.
 8. How a session was launched is read from signals a tool writes, never
    inferred from context. That means harness fields (Claude `entrypoint`,
    `isSidechain`, `agentName`; Codex `originator` and `source`), a
    launcher's own session registry, and exact prompt text a tool emits,
    which is configurable. A launch with no positive signal is
    unattributed: `claude -p` and `codex exec` are used alike by chat bots,
    review tooling and cron jobs. Two tempting shortcuts are wrong. The cwd
    names the project worked on, not the launcher. And a prose search for
    "council" matches nearly every session, because instruction files
    mention it.
 9. Claude sessions from builds that predate `entrypoint` are classified by
    shape: more than one human turn is interactive (direct, inferred);
    exactly one is scripted (automated, inferred). The `-inferred` suffix is
    kept so the report can show or discount the guess.
"""
import base64
import collections
import hashlib
import json
import os
import platform
import socket
import sys
import time

SCHEMA = 1

DEFAULT_CONFIG = {
    # Launchers that record the session ids they start. Sessions listed are
    # direct use through that tool. discord-agents
    # (github.com/tedks/discord-agents) keeps its live sessions here.
    "launch_registries": {"discord-agents": "~/.config/discord-agents/sessions.json"},
    # Codex `originator` values that identify a tool you drive directly.
    # swarm-ide (github.com/tedks/swarm-ide) names itself this way.
    "direct_originators": {"swarm_ide": "swarm-ide"},
    # Operator-specific markers; empty unless configured. Exact prompt text a
    # review tool sends each seat:
    "council_markers": [],
    # substrings of a sidechain agentName that mark a review seat:
    "council_agent_markers": [],
    # a path an ask-agent style wrapper stages an Antigravity prompt at:
    "ask_agent_markers": [],
    "home": None,  # override for tests; defaults to ~
}


MODEL_SELECTION = "Model Selection` from "


def load_config(argv):
    cfg = dict(DEFAULT_CONFIG)
    if len(argv) > 1 and argv[1]:
        cfg.update(json.loads(base64.b64decode(argv[1]).decode("utf-8")))
    return cfg


def walk_files(root, want):
    """Yield paths under root whose basename satisfies want(dirpath, name)."""
    if not os.path.isdir(root):
        return
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if want(dirpath, name):
                yield os.path.join(dirpath, name)


def read_lines(path, errors):
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                yield line
    except (IOError, OSError):
        errors["unreadable_file"] += 1


def parse(line, errors, key):
    try:
        return json.loads(line)
    except ValueError:
        errors[key] += 1
        return None


def load_registries(home, cfg, out):
    """Session ids each launcher recorded, as {session_id: label}. Missing
    or malformed registries are skipped and counted, never fatal."""
    ids = {}
    for label, path in sorted(cfg["launch_registries"].items()):
        path = path.replace("~", home, 1) if path.startswith("~") else path
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            records = data if isinstance(data, list) else list(data.values())
            for r in records:
                sid = r.get("session_id") if isinstance(r, dict) else None
                if sid:
                    ids[sid] = label
            out.sources["registry:" + label]["sessions"] += len(records)
        except (IOError, OSError, ValueError, AttributeError):
            out.errors["registry_unreadable:" + label] += 1
    return ids


class Out(object):
    def __init__(self):
        self.turns = collections.Counter()  # (vendor, model, month, channel, sub)
        self.claude_tok = collections.defaultdict(collections.Counter)  # (model, month, channel)
        self.codex_tok = collections.defaultdict(collections.Counter)  # (model, month, channel)
        self.first = {}
        self.last = {}
        self.errors = collections.Counter()
        self.dedup = collections.Counter()
        self.seen_values = collections.defaultdict(collections.Counter)
        self.sources = collections.defaultdict(collections.Counter)
        self.gemini_projects = collections.Counter()

    def turn(self, vendor, model, ts, channel, sub):
        if not model or not ts or len(ts) < 10:
            self.errors["turn_without_model_or_time"] += 1
            return
        self.turns[(vendor, model, ts[:7], channel, sub)] += 1
        day = ts[:10]
        if model not in self.first or day < self.first[model]:
            self.first[model] = day
        if model not in self.last or day > self.last[model]:
            self.last[model] = day


def contains_any(text, markers):
    for m in markers:
        if m and m in text:
            return True
    return False


# ---------------------------------------------------------------- Claude


def claude_human_text(record):
    """Text of a genuine human turn, or None for tool results and meta."""
    if record.get("isSidechain") or record.get("isMeta"):
        return None
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                return None
            if block.get("type") == "text":
                parts.append(block.get("text") or "")
        content = " ".join(parts)
    if isinstance(content, str) and content.strip():
        return content
    return None


def collect_claude(home, cfg, out, registry):
    files = []
    root = os.path.join(home, ".claude", "projects")
    for path in walk_files(root, lambda d, n: n.endswith(".jsonl")):
        out.sources["claude"]["files"] += 1
        sess = {
            "path": path,
            "sid": os.path.basename(path)[: -len(".jsonl")],
            "entrypoint": None,
            "human": 0,
            "council": False,
            "first": None,
            "reqs": {},
        }
        order = 0
        for line in read_lines(path, out.errors):
            # Prefilters are a speed optimisation only, so they must not depend
            # on how the JSON is spaced: match bare tokens, and let the parsed
            # record decide.
            is_user = '"user"' in line
            if '"assistant"' not in line and '"entrypoint"' not in line and not is_user:
                continue
            rec = parse(line, out.errors, "claude_bad_line")
            if rec is None:
                continue
            if rec.get("entrypoint") and not sess["entrypoint"]:
                sess["entrypoint"] = rec["entrypoint"]
            ts = rec.get("timestamp") or ""
            if ts and (sess["first"] is None or ts < sess["first"]):
                sess["first"] = ts
            if rec.get("type") == "user":
                text = claude_human_text(rec)
                if text is not None:
                    sess["human"] += 1
                    if contains_any(text, cfg["council_markers"]):
                        sess["council"] = True
                continue
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message") or {}
            model = msg.get("model")
            if not model or model.startswith("<"):
                continue  # <synthetic> and local records never reached a model
            usage = msg.get("usage") or {}
            vec = [
                usage.get("input_tokens") or 0,
                usage.get("cache_creation_input_tokens") or 0,
                usage.get("cache_read_input_tokens") or 0,
                usage.get("output_tokens") or 0,
            ]
            key = rec.get("requestId") or ("uuid", rec.get("uuid"), order)
            order += 1
            agent = rec.get("agentName") or ""
            r = sess["reqs"].get(key)
            if r is None:
                sess["reqs"][key] = {
                    "model": model,
                    "ts": ts,
                    "side": bool(rec.get("isSidechain")),
                    "council": contains_any(agent, cfg["council_agent_markers"]),
                    "vec": vec,
                    "terminal": msg.get("stop_reason") is not None,
                }
            else:  # rule 1: cumulative snapshots -> max per field
                r["vec"] = [max(a, b) for a, b in zip(r["vec"], vec)]
                r["terminal"] = r["terminal"] or msg.get("stop_reason") is not None
                if agent and contains_any(agent, cfg["council_agent_markers"]):
                    r["council"] = True
        if sess["reqs"]:
            files.append(sess)

    # A fork ties with its parent on first timestamp; the path breaks the tie
    # so attribution is deterministic. Totals do not depend on the order,
    # since each unique request is claimed exactly once either way.
    files.sort(key=lambda s: (s["first"] or "", s["path"]))
    claimed = set()
    for sess in files:
        ep = sess["entrypoint"]
        out.seen_values["claude_entrypoint"][ep or "(absent)"] += 1
        if sess["sid"] in registry:
            out.dedup["claude_registry_match"] += 1
            base = ("direct", registry[sess["sid"]])
        else:
            base = claude_session_channel(ep, sess["human"], sess["council"])
        out.sources["claude"]["sessions"] += 1
        for key, r in sess["reqs"].items():
            if key in claimed and key[0] != "uuid":
                out.dedup["claude_cross_file_request"] += 1  # rule 2
                continue
            claimed.add(key)
            if r["side"]:
                channel, sub = "automated", ("council-review" if r["council"] else "internal-subagent")
            else:
                channel, sub = base
            out.turn("Anthropic", r["model"], r["ts"], channel, sub)
            if len(r["ts"]) >= 7:
                t = out.claude_tok[(r["model"], r["ts"][:7], channel)]
                t["responses"] += 1
                t["input"] += r["vec"][0]
                t["cache_write"] += r["vec"][1]
                t["cache_read"] += r["vec"][2]
                t["output"] += r["vec"][3]
                if r["terminal"]:
                    t["terminal_responses"] += 1  # rule 3


def claude_session_channel(entrypoint, human_turns, council):
    if entrypoint in ("cli", "claude-desktop"):
        return ("direct", "terminal")
    if entrypoint == "sdk-cli":
        # claude -p: a chat bot, a review tool or a cron job alike.
        if council:
            return ("automated", "council-review")
        return ("unattributed", "sdk-cli")
    if entrypoint:
        return ("unattributed", "entrypoint:" + entrypoint)
    # rule 9: builds without entrypoint -> classify by session shape
    if human_turns > 1:
        return ("direct", "terminal-inferred")
    if human_turns == 1:
        return ("automated", "oneshot-inferred")
    return ("unattributed", "no-human-turn")


# ---------------------------------------------------------------- Codex

CODEX_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def codex_channel(originator, source, council, registered, cfg):
    # Codex marks threads it spawned itself: {"subagent": {"thread_spawn":
    # ...}} for delegated work, {"subagent": "review"} for its reviewer.
    if isinstance(source, dict) and "subagent" in source:
        kind = source["subagent"]
        return ("automated", "codex-review" if kind == "review" else "internal-subagent")
    if registered:
        return ("direct", registered)
    if originator in cfg["direct_originators"]:
        return ("direct", cfg["direct_originators"][originator])
    if originator == "codex_exec" or source == "exec":
        # codex exec: a chat bot, a review tool or a script alike.
        return ("automated", "council-review") if council else ("unattributed", "codex-exec")
    if source == "vscode":
        return ("direct", "ide")
    if source == "cli":
        return ("direct", "terminal")
    return ("unattributed", "originator:" + str(originator))


def collect_codex(home, cfg, out, registry):
    files = []
    root = os.path.join(home, ".codex", "sessions")
    for path in walk_files(root, lambda d, n: n.endswith(".jsonl")):
        out.sources["codex"]["files"] += 1
        f = {
            "path": path,
            "sid": None,
            "orig": None,
            "src": None,
            "first": None,
            "events": [],
            "council": False,
        }
        model = None
        for line in read_lines(path, out.errors):
            if not f["council"] and contains_any(line, cfg["council_markers"]):
                f["council"] = True
            is_meta = '"session_meta"' in line
            is_ctx = '"turn_context"' in line
            is_msg = '"message"' in line
            is_tok = '"total_token_usage"' in line
            if not (is_meta or is_ctx or is_msg or is_tok):
                continue
            rec = parse(line, out.errors, "codex_bad_line")
            if rec is None:
                continue
            ts = rec.get("timestamp") or ""
            if ts and (f["first"] is None or ts < f["first"]):
                f["first"] = ts
            payload = rec.get("payload") or {}
            kind = rec.get("type")
            if kind == "session_meta":
                f["orig"] = payload.get("originator")
                f["src"] = payload.get("source")
                f["sid"] = payload.get("id") or payload.get("session_id")
            elif kind == "turn_context":
                model = payload.get("model") or model
            elif payload.get("type") == "message" and payload.get("role") == "assistant":
                digest = hashlib.md5(
                    json.dumps(payload.get("content"), sort_keys=True).encode("utf-8")
                ).hexdigest()
                f["events"].append(("msg", ts, model, digest))
            elif is_tok:
                info = payload.get("info") or {}
                total = info.get("total_token_usage") if isinstance(info, dict) else None
                if isinstance(total, dict) and total.get("total_tokens"):
                    vec = [total.get(k) or 0 for k in CODEX_FIELDS]
                    f["events"].append(("tok", ts, model, total["total_tokens"], vec))
        if f["events"]:
            files.append(f)

    files.sort(key=lambda f: (f["first"] or "", f["path"]))
    seen_msg = set()
    seen_tok = set()
    for f in files:
        out.sources["codex"]["sessions"] += 1
        out.seen_values["codex_originator"][str(f["orig"])] += 1
        registered = registry.get(f["sid"])
        if registered:
            out.dedup["codex_registry_match"] += 1
        channel, sub = codex_channel(f["orig"], f["src"], f["council"], registered, cfg)
        prev_total = None
        prev_vec = None
        for ev in f["events"]:
            if ev[0] == "msg":
                _, ts, model, digest = ev
                key = (ts, digest)
                if key in seen_msg:
                    out.dedup["codex_copied_message"] += 1  # rule 5
                    continue
                seen_msg.add(key)
                if model:
                    out.turn("OpenAI", model, ts, channel, sub)
                else:
                    out.errors["codex_message_before_model"] += 1
                continue
            _, ts, model, total, vec = ev
            if (ts, total) in seen_tok:
                # rule 4: an event inherited from the parent session. The fork's
                # counter continues from here, so it becomes the baseline.
                out.dedup["codex_inherited_token_event"] += 1
                prev_total, prev_vec = total, vec
                continue
            seen_tok.add((ts, total))
            if prev_total is None or total < prev_total:
                if prev_total is not None:
                    out.dedup["codex_counter_reset"] += 1
                grew = vec  # a fresh counter (or a reset) counts from zero
            elif total == prev_total:
                grew = None  # re-emitted with no new usage
            else:
                grew = [max(0, a - b) for a, b in zip(vec, prev_vec)]
            prev_total, prev_vec = total, vec
            if grew and model and len(ts) >= 7:
                t = out.codex_tok[(model, ts[:7], channel)]
                t["input"] += grew[0]
                t["cached"] += grew[1]
                t["output"] += grew[2]
                t["reasoning"] += grew[3]


# ---------------------------------------------------------------- Google


def agy_model_after(text, current):
    """Apply every `Model Selection` change in text, in order."""
    start = 0
    while True:
        i = text.find(MODEL_SELECTION, start)
        if i < 0:
            return current
        j = text.find(" to ", i)
        k = text.find(". No need", j)
        if j < 0 or k < 0:
            return current
        current = text[j + 4 : k].strip() or current
        start = k


def collect_agy(home, cfg, out):
    root = os.path.join(home, ".gemini")
    for path in walk_files(root, lambda d, n: n == "transcript.jsonl"):  # rule 7
        out.sources["agy"]["transcripts"] += 1
        lines = list(read_lines(path, out.errors))
        raw = "".join(lines)
        if contains_any(raw, cfg["ask_agent_markers"]):
            channel = "automated"
            sub = "council-review" if contains_any(raw, cfg["council_markers"]) else "ask-agent"
        else:
            channel, sub = "direct", "antigravity"
        model = "agy:unknown-model"
        steps = set()
        for line in lines:
            if MODEL_SELECTION in line:
                model = agy_model_after(line.replace("\\n", "\n"), model)
            if '"PLANNER_RESPONSE"' not in line:
                continue
            rec = parse(line, out.errors, "agy_bad_line")
            if rec is None or rec.get("type") != "PLANNER_RESPONSE":
                continue
            step = rec.get("step_index")
            if step in steps:
                out.dedup["agy_repeated_step"] += 1
                continue
            steps.add(step)
            out.turn("Google", model, rec.get("created_at") or "", channel, sub)


def collect_gemini_cli(home, cfg, out, registry):
    root = os.path.join(home, ".gemini")
    want = lambda d, n: os.path.basename(d) == "chats" and n.endswith(".jsonl")  # noqa: E731
    for path in walk_files(root, want):
        out.sources["gemini_cli"]["sessions"] += 1
        out.gemini_projects[os.path.basename(os.path.dirname(os.path.dirname(path)))] += 1
        lines = list(read_lines(path, out.errors))
        raw = "".join(lines)
        sid = None
        try:
            sid = json.loads(lines[0]).get("sessionId") if lines else None
        except ValueError:
            pass
        if sid in registry:
            out.dedup["gemini_registry_match"] += 1
            channel, sub = "direct", registry[sid]
        elif contains_any(raw, cfg["council_markers"]):
            channel, sub = "automated", "council-review"
        else:
            # Gemini CLI records no launch source, so "direct" cannot be asserted.
            channel, sub = "unattributed", "gemini-cli"
        default_model = None
        messages = {}
        for line in lines:
            rec = parse(line, out.errors, "gemini_bad_line")
            if rec is None:
                continue
            stack = [rec]
            while stack:
                x = stack.pop()
                if isinstance(x, dict):
                    m = x.get("model")
                    if default_model is None and isinstance(m, str) and m.startswith("gemini"):
                        default_model = m
                    if x.get("type") == "gemini" and x.get("timestamp"):
                        mid = x.get("id") or ("ts", x.get("timestamp"))
                        if mid in messages:
                            out.dedup["gemini_snapshot_repeat"] += 1  # rule 6
                        else:
                            messages[mid] = (x.get("timestamp"), m if isinstance(m, str) else None)
                    stack.extend(v for v in x.values() if isinstance(v, (dict, list)))
                elif isinstance(x, list):
                    stack.extend(x)
        for ts, model in messages.values():
            out.turn("Google", model or default_model or "gemini:unknown-model", ts, channel, sub)


# ---------------------------------------------------------------- main


def rows(counter, names):
    return [dict(zip(names, k), **dict(v)) for k, v in sorted(counter.items())]


def collect(cfg):
    home = cfg.get("home") or os.path.expanduser("~")
    out = Out()
    started = time.time()
    registry = load_registries(home, cfg, out)
    collect_claude(home, cfg, out, registry)
    collect_codex(home, cfg, out, registry)
    collect_agy(home, cfg, out)
    collect_gemini_cli(home, cfg, out, registry)
    return {
        "schema": SCHEMA,
        "host": socket.gethostname(),
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(),
        "seconds": round(time.time() - started, 1),
        "turns": [
            {"vendor": k[0], "model": k[1], "month": k[2], "channel": k[3], "sub": k[4], "turns": n}
            for k, n in sorted(out.turns.items())
        ],
        "claude_tokens": rows(out.claude_tok, ("model", "month", "channel")),
        "codex_tokens": rows(out.codex_tok, ("model", "month", "channel")),
        "first_use": out.first,
        "last_use": out.last,
        "sources": {k: dict(v) for k, v in out.sources.items()},
        "diagnostics": {
            "errors": dict(out.errors),
            "deduplicated": dict(out.dedup),
            "seen_values": {k: dict(v) for k, v in out.seen_values.items()},
            "gemini_cli_projects": out.gemini_projects.most_common(10),
        },
    }


def main(argv):
    json.dump(collect(load_config(argv)), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv)
