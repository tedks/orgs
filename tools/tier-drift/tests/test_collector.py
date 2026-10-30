"""Collector counting rules, each exercised on synthetic logs shaped like the
real bug it guards against. Rule numbers match the collector's docstring."""

import base64
import json
import sys
from pathlib import Path

import pytest

from tier_drift import collector

SECRET = "PRIVATE-PROMPT-TEXT-must-never-leave-the-host"


# Real harness logs are compact JSON. Fixtures default to the same, and
# test_prefilters_do_not_depend_on_json_spacing proves spaced output counts
# identically, so a harness changing its serializer cannot silently zero a
# source.
SEPARATORS = (",", ":")


def write_jsonl(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=SEPARATORS) + "\n" for r in records))


# Neutral stand-ins for operator-specific markers (the real ones live in the
# operator's own config, never in this repo).
REVIEW = "REVIEW-SEAT-TEMPLATE: review the following change"
STAGE = "/tmp/wrapper-stage-agy"
MARKERS = {
    "council_markers": [REVIEW],
    "council_agent_markers": ["reviewer"],
    "ask_agent_markers": [STAGE],
}


def run(home: Path, **overrides):
    cfg = dict(collector.DEFAULT_CONFIG, home=str(home), **overrides)
    return collector.collect(cfg)


def turns(result, **match):
    return sum(r["turns"] for r in result["turns"] if all(r.get(k) == v for k, v in match.items()))


# ------------------------------------------------------------------ Claude


def human(text, ts="2026-03-01T10:00:00Z", **extra):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}, **extra}


def asst(rid, model="claude-opus-4-6", ts="2026-03-01T10:00:01Z", usage=None, stop=None, **extra):
    return {
        "type": "assistant",
        "requestId": rid,
        "timestamp": ts,
        "message": {"model": model, "usage": usage or {}, "stop_reason": stop},
        **extra,
    }


def claude_file(home, name, records):
    write_jsonl(home / ".claude" / "projects" / "-proj" / f"{name}.jsonl", records)


def test_claude_one_request_is_one_turn_with_max_usage(tmp_path):
    # rule 1: a thinking record then a text record, cumulative snapshots
    claude_file(
        tmp_path,
        "s",
        [
            human(SECRET, entrypoint="cli"),
            asst(
                "req1",
                usage={"input_tokens": 9, "cache_read_input_tokens": 500, "output_tokens": 3},
            ),
            asst(
                "req1",
                usage={"input_tokens": 9, "cache_read_input_tokens": 500, "output_tokens": 152},
                stop="end_turn",
            ),
        ],
    )
    out = run(tmp_path)
    assert turns(out, vendor="Anthropic") == 1
    (tok,) = out["claude_tokens"]
    assert tok["output"] == 152  # max, not 3 and not 155
    assert tok["cache_read"] == 500  # max, not summed to 1000
    assert tok["responses"] == 1


def test_claude_request_copied_into_a_fork_is_counted_once(tmp_path):
    # rule 2: resume/fork copies parent history into a new file
    parent = [human("a", entrypoint="cli"), asst("req1", ts="2026-03-01T10:00:01Z")]
    fork = [
        human("a", ts="2026-03-01T10:00:00Z", entrypoint="cli"),
        asst("req1", ts="2026-03-01T10:00:01Z"),
        human("b", ts="2026-03-02T09:00:00Z"),
        asst("req2", ts="2026-03-02T09:00:01Z"),
    ]
    claude_file(tmp_path, "parent", parent)
    claude_file(tmp_path, "zfork", fork)
    out = run(tmp_path)
    assert turns(out, vendor="Anthropic") == 2
    assert out["diagnostics"]["deduplicated"]["claude_cross_file_request"] == 1


def test_claude_terminal_coverage_is_reported_not_assumed(tmp_path):
    # rule 3: a request with only streaming partials has no terminal record
    claude_file(
        tmp_path,
        "s",
        [
            human("x", entrypoint="cli"),
            asst("r1", usage={"output_tokens": 5}),
            asst("r2", usage={"output_tokens": 7}, stop="end_turn"),
        ],
    )
    (tok,) = run(tmp_path)["claude_tokens"]
    assert tok["responses"] == 2
    assert tok["terminal_responses"] == 1


@pytest.mark.parametrize(
    "entrypoint,channel,sub",
    [
        ("cli", "direct", "terminal"),
        ("claude-desktop", "direct", "terminal"),
        # claude -p is used by chat bots, review tools and cron jobs alike
        ("sdk-cli", "unattributed", "sdk-cli"),
        ("some-future-entrypoint", "unattributed", "entrypoint:some-future-entrypoint"),
    ],
)
def test_claude_channel_comes_from_entrypoint(tmp_path, entrypoint, channel, sub):
    claude_file(tmp_path, "s", [human("x", entrypoint=entrypoint), asst("r1")])
    assert turns(run(tmp_path), channel=channel, sub=sub) == 1


def test_cwd_never_decides_the_launcher(tmp_path):
    # the cwd names the project worked on, not what launched the session
    claude_file(
        tmp_path,
        "s",
        [human("x", entrypoint="sdk-cli", cwd="/home/u/Projects/some-bot/master"), asst("r1")],
    )
    assert turns(run(tmp_path), channel="unattributed", sub="sdk-cli") == 1


def test_sdk_session_carrying_a_review_prompt_is_automated(tmp_path):
    claude_file(tmp_path, "s", [human(REVIEW + " diff...", entrypoint="sdk-cli"), asst("r1")])
    assert turns(run(tmp_path, **MARKERS), channel="automated", sub="council-review") == 1


def registry(home, records):
    path = home / ".config" / "discord-agents" / "sessions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records))


def test_sessions_a_launcher_registered_are_direct(tmp_path):
    registry(tmp_path, [{"session_id": "abc", "agent_kind": "claude"}, {"session_id": "cx1"}])
    claude_file(tmp_path, "abc", [human("x", entrypoint="sdk-cli"), asst("r1")])
    claude_file(tmp_path, "other", [human("x", entrypoint="sdk-cli"), asst("r2")])
    codex_file(
        tmp_path,
        "c",
        "codex_exec",
        "exec",
        [
            ("ctx", "2026-09-05T10:00:00Z", "gpt-6-astra"),
            ("msg", "2026-09-05T10:00:01Z", [{"type": "output_text", "text": "x"}]),
        ],
        session_id="cx1",
    )
    out = run(tmp_path)
    assert turns(out, vendor="Anthropic", channel="direct", sub="discord-agents") == 1
    assert turns(out, vendor="Anthropic", channel="unattributed", sub="sdk-cli") == 1
    assert turns(out, vendor="OpenAI", channel="direct", sub="discord-agents") == 1
    assert json.dumps(out).count("abc") == 0  # registry ids never leave the host


def test_unreadable_registry_is_counted_not_fatal(tmp_path):
    path = tmp_path / ".config" / "discord-agents" / "sessions.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    claude_file(tmp_path, "s", [human("x", entrypoint="cli"), asst("r1")])
    out = run(tmp_path)
    assert turns(out, sub="terminal") == 1
    assert out["diagnostics"]["errors"]["registry_unreadable:discord-agents"] == 1


def test_claude_subagents_are_automated_and_council_seats_are_named(tmp_path):
    claude_file(
        tmp_path,
        "s",
        [
            human("x", entrypoint="cli"),
            asst("r1"),
            asst("r2", isSidechain=True, agentName="explore-worker"),
            asst("r3", isSidechain=True, agentName="reviewer-claude-r1"),
        ],
    )
    out = run(tmp_path, **MARKERS)
    assert turns(out, channel="direct", sub="terminal") == 1
    assert turns(out, channel="automated", sub="internal-subagent") == 1
    assert turns(out, channel="automated", sub="council-review") == 1


def test_prose_mentioning_review_does_not_make_a_session_automated(tmp_path):
    # rule 8: instruction files mention review tooling in every session
    claude_file(
        tmp_path,
        "s",
        [human("Run the review tool before merging.", entrypoint="cli"), asst("r1")],
    )
    assert turns(run(tmp_path, **MARKERS), channel="direct", sub="terminal") == 1


@pytest.mark.parametrize(
    "humans,channel,sub",
    [
        (2, "direct", "terminal-inferred"),
        (1, "automated", "oneshot-inferred"),
        (0, "unattributed", "no-human-turn"),
    ],
)
def test_claude_without_entrypoint_is_classified_by_shape(tmp_path, humans, channel, sub):
    # rule 9
    recs = [human(f"turn {i}", ts=f"2026-01-0{i + 1}T00:00:00Z") for i in range(humans)]
    recs.append(asst("r1", ts="2026-01-05T00:00:00Z"))
    claude_file(tmp_path, "s", recs)
    assert turns(run(tmp_path), channel=channel, sub=sub) == 1


def test_tool_results_are_not_counted_as_human_turns(tmp_path):
    tool_result = {
        "type": "user",
        "timestamp": "2026-01-01T00:00:02Z",
        "message": {"content": [{"type": "tool_result", "content": "ok"}]},
    }
    claude_file(tmp_path, "s", [human("go"), tool_result, tool_result, asst("r1")])
    # one real human turn -> one-shot, not interactive
    assert turns(run(tmp_path), sub="oneshot-inferred") == 1


def test_synthetic_records_never_count(tmp_path):
    claude_file(
        tmp_path, "s", [human("x", entrypoint="cli"), asst("r1", model="<synthetic>"), asst("r2")]
    )
    assert turns(run(tmp_path), vendor="Anthropic") == 1


# ------------------------------------------------------------------- Codex


def codex_file(home, name, originator, source, events, session_id=None):
    meta = {"originator": originator, "source": source, "id": session_id or name}
    recs = [{"timestamp": events[0][1], "type": "session_meta", "payload": meta}]
    for ev in events:
        kind, ts = ev[0], ev[1]
        if kind == "ctx":
            recs.append({"timestamp": ts, "type": "turn_context", "payload": {"model": ev[2]}})
        elif kind == "msg":
            recs.append(
                {
                    "timestamp": ts,
                    "type": "response_item",
                    "payload": {"type": "message", "role": "assistant", "content": ev[2]},
                }
            )
        elif kind == "tok":
            inp, cached, out_ = ev[2]
            usage = {
                "input_tokens": inp,
                "cached_input_tokens": cached,
                "output_tokens": out_,
                "reasoning_output_tokens": 0,
                "total_tokens": inp + out_,
            }
            recs.append(
                {
                    "timestamp": ts,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {"total_token_usage": usage, "last_token_usage": usage},
                    },
                }
            )
    write_jsonl(home / ".codex" / "sessions" / "2026" / "09" / f"{name}.jsonl", recs)


def codex_totals(out, model):
    rows = [r for r in out["codex_tokens"] if r["model"] == model]
    return {k: sum(r[k] for r in rows) for k in ("input", "cached", "output")}


def test_codex_fork_counts_only_its_own_growth(tmp_path):
    # rule 4: the fork inherits the parent's cumulative events, then continues
    parent = [
        ("ctx", "2026-09-05T10:00:00Z", "gpt-6-astra"),
        ("tok", "2026-09-05T10:00:01Z", (100, 80, 10)),
        ("tok", "2026-09-05T10:00:02Z", (200, 170, 20)),
    ]
    fork = parent + [("tok", "2026-09-06T10:00:00Z", (260, 220, 26))]
    codex_file(tmp_path, "a-parent", "codex-tui", "cli", parent)
    codex_file(tmp_path, "b-fork", "codex-tui", "cli", fork)
    totals = codex_totals(run(tmp_path), "gpt-6-astra")
    # parent contributes 200/170/20, the fork only 60/50/6 on top
    assert totals == {"input": 260, "cached": 220, "output": 26}


def test_codex_counter_reset_starts_a_new_segment(tmp_path):
    events = [
        ("ctx", "2026-09-05T10:00:00Z", "gpt-6-astra"),
        ("tok", "2026-09-05T10:00:01Z", (100, 0, 10)),
        ("tok", "2026-09-05T10:00:02Z", (30, 0, 3)),  # reset
        ("tok", "2026-09-05T10:00:03Z", (50, 0, 5)),
    ]
    codex_file(tmp_path, "s", "codex-tui", "cli", events)
    out = run(tmp_path)
    assert codex_totals(out, "gpt-6-astra")["input"] == 150  # 100 + 50, not max()=100
    assert out["diagnostics"]["deduplicated"]["codex_counter_reset"] == 1


def test_codex_reemitted_total_is_not_double_counted(tmp_path):
    events = [
        ("ctx", "2026-09-05T10:00:00Z", "gpt-5.6-sol"),
        ("tok", "2026-09-05T10:00:01Z", (100, 90, 10)),
        ("tok", "2026-09-05T10:00:02Z", (100, 90, 10)),  # same counter, re-emitted
    ]
    codex_file(tmp_path, "s", "codex-tui", "cli", events)
    assert codex_totals(run(tmp_path), "gpt-5.6-sol")["input"] == 100


def test_codex_tokens_follow_a_mid_session_model_switch(tmp_path):
    events = [
        ("ctx", "2026-09-05T10:00:00Z", "gpt-5.6-sol"),
        ("tok", "2026-09-05T10:00:01Z", (100, 0, 10)),
        ("ctx", "2026-09-05T10:00:02Z", "gpt-6-astra"),
        ("tok", "2026-09-05T10:00:03Z", (160, 0, 16)),
    ]
    codex_file(tmp_path, "s", "codex-tui", "cli", events)
    out = run(tmp_path)
    assert codex_totals(out, "gpt-5.6-sol")["input"] == 100
    assert codex_totals(out, "gpt-6-astra")["input"] == 60


def test_codex_messages_copied_into_a_fork_are_counted_once(tmp_path):
    # rule 5
    parent = [
        ("ctx", "2026-09-05T10:00:00Z", "gpt-6-astra"),
        ("msg", "2026-09-05T10:00:01Z", [{"type": "output_text", "text": "hi"}]),
    ]
    fork = parent + [("msg", "2026-09-06T10:00:00Z", [{"type": "output_text", "text": "more"}])]
    codex_file(tmp_path, "a", "codex-tui", "cli", parent)
    codex_file(tmp_path, "b", "codex-tui", "cli", fork)
    out = run(tmp_path)
    assert turns(out, vendor="OpenAI") == 2
    assert out["diagnostics"]["deduplicated"]["codex_copied_message"] == 1


@pytest.mark.parametrize(
    "originator,source,body,channel,sub",
    [
        ("codex_exec", "exec", "hello", "unattributed", "codex-exec"),
        ("codex_exec", "exec", REVIEW, "automated", "council-review"),
        ("swarm_ide", "vscode", "hello", "direct", "swarm-ide"),
        ("Codex Desktop", "vscode", "hello", "direct", "ide"),
        ("codex-tui", "cli", "hello", "direct", "terminal"),
        (
            "codex-tui",
            {"subagent": {"thread_spawn": {"parent_thread_id": "p"}}},
            "hello",
            "automated",
            "internal-subagent",
        ),
        ("codex_cli_rs", {"subagent": "review"}, "hello", "automated", "codex-review"),
    ],
)
def test_codex_channel_comes_from_originator(tmp_path, originator, source, body, channel, sub):
    events = [
        ("ctx", "2026-09-05T10:00:00Z", "gpt-6-astra"),
        ("msg", "2026-09-05T10:00:01Z", [{"type": "output_text", "text": body}]),
    ]
    codex_file(tmp_path, "s", originator, source, events)
    assert turns(run(tmp_path, **MARKERS), channel=channel, sub=sub) == 1


# ------------------------------------------------------------------ Google


def agy_transcript(home, uuid, steps):
    path = home / ".gemini" / "antigravity-cli" / "brain" / uuid / ".system_generated" / "logs"
    write_jsonl(path / "transcript.jsonl", steps)


def settings(model):
    return (
        "<USER_SETTINGS_CHANGE>\nThe user changed setting `Model Selection` from None to "
        f"{model}. No need to comment on this change.\n</USER_SETTINGS_CHANGE>"
    )


def test_agy_transcripts_under_hidden_dirs_are_found(tmp_path):
    # rule 7: glob('**') would return nothing here
    agy_transcript(
        tmp_path,
        "u1",
        [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": "hi " + settings("Gemini 3.1 Pro (High)"),
            },
            {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": "2026-09-05T22:04:05Z"},
        ],
    )
    out = run(tmp_path)
    assert turns(out, vendor="Google", model="Gemini 3.1 Pro (High)", sub="antigravity") == 1


def test_agy_ask_agent_council_and_model_switch(tmp_path):
    marker = f"Read the file {STAGE}.x1/prompt/prompt.txt"
    council = REVIEW
    agy_transcript(
        tmp_path,
        "u2",
        [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": marker + settings("Gemini 3.1 Pro (High)"),
            },
            {"step_index": 1, "type": "VIEW_FILE", "content": council},
            {"step_index": 2, "type": "PLANNER_RESPONSE", "created_at": "2026-09-05T22:04:05Z"},
            {"step_index": 3, "type": "USER_INPUT", "content": settings("Gemini 3.1 Flash (Low)")},
            {"step_index": 4, "type": "PLANNER_RESPONSE", "created_at": "2026-09-05T22:05:05Z"},
            {"step_index": 4, "type": "PLANNER_RESPONSE", "created_at": "2026-09-05T22:05:05Z"},
        ],
    )
    out = run(tmp_path, **MARKERS)
    assert turns(out, model="Gemini 3.1 Pro (High)", sub="council-review") == 1
    assert turns(out, model="Gemini 3.1 Flash (Low)", sub="council-review") == 1
    assert out["diagnostics"]["deduplicated"]["agy_repeated_step"] == 1


def test_gemini_cli_snapshots_are_deduplicated_by_message_id(tmp_path):
    # rule 6: every $set rewrites the whole array
    m1 = {
        "id": "a",
        "type": "gemini",
        "timestamp": "2026-06-05T00:00:01Z",
        "model": "gemini-3-flash-preview",
    }
    m2 = {
        "id": "b",
        "type": "gemini",
        "timestamp": "2026-06-05T00:00:02Z",
        "model": "gemini-3-flash-preview",
    }
    user = {
        "id": "u",
        "type": "user",
        "timestamp": "2026-06-05T00:00:00Z",
        "content": [{"text": SECRET}],
    }
    recs = [
        {"sessionId": "s", "kind": "main", "startTime": "2026-06-05T00:00:00Z"},
        {"$set": {"messages": [user, m1]}},
        {"$set": {"messages": [user, m1, m2]}},
        {"$set": {"messages": [user, m1, m2]}},
    ]
    write_jsonl(tmp_path / ".gemini" / "tmp" / "proj" / "chats" / "session-1.jsonl", recs)
    out = run(tmp_path)
    assert turns(out, vendor="Google") == 2  # not 5
    assert turns(out, channel="unattributed", sub="gemini-cli") == 2


# --------------------------------------------------------- whole collector


def test_public_defaults_carry_no_operator_markers():
    for key in ("council_markers", "council_agent_markers", "ask_agent_markers"):
        assert collector.DEFAULT_CONFIG[key] == []


def test_output_contains_no_prompt_text_or_paths(tmp_path):
    claude_file(
        tmp_path, "s", [human(SECRET, entrypoint="cli", cwd=f"/home/u/{SECRET}"), asst("r1")]
    )
    codex_file(
        tmp_path,
        "c",
        "codex_exec",
        "exec",
        [
            ("ctx", "2026-09-05T10:00:00Z", "gpt-6-astra"),
            ("msg", "2026-09-05T10:00:01Z", [{"type": "output_text", "text": SECRET}]),
        ],
    )
    blob = json.dumps(run(tmp_path))
    assert SECRET not in blob
    assert str(tmp_path) not in blob


def test_missing_sources_produce_an_empty_but_valid_document(tmp_path):
    out = run(tmp_path)
    assert out["schema"] == collector.SCHEMA
    assert out["turns"] == [] and out["claude_tokens"] == [] and out["codex_tokens"] == []


def test_config_arrives_as_base64_json_argument():
    cfg = {"council_markers": ["X"], "home": "/nonexistent"}
    arg = base64.b64encode(json.dumps(cfg).encode()).decode()
    loaded = collector.load_config(["-", arg])
    assert loaded["council_markers"] == ["X"]
    assert loaded["ask_agent_markers"] == collector.DEFAULT_CONFIG["ask_agent_markers"]


@pytest.mark.parametrize("separators", [(",", ":"), (", ", ": ")], ids=["compact", "spaced"])
def test_prefilters_do_not_depend_on_json_spacing(tmp_path, monkeypatch, separators):
    monkeypatch.setattr(sys.modules[__name__], "SEPARATORS", separators)
    claude_file(tmp_path, "s", [human("a"), human("b"), asst("r1", ts="2026-01-05T00:00:00Z")])
    # positive control: the fixture really was written with these separators
    written = next((tmp_path / ".claude").rglob("*.jsonl")).read_text()
    assert ('"type": "user"' in written) == (separators[1] == ": ")
    codex_file(
        tmp_path,
        "c",
        "codex-tui",
        "cli",
        [
            ("ctx", "2026-09-05T10:00:00Z", "gpt-6-astra"),
            ("msg", "2026-09-05T10:00:01Z", [{"type": "output_text", "text": "x"}]),
            ("tok", "2026-09-05T10:00:02Z", (10, 5, 1)),
        ],
    )
    out = run(tmp_path)
    assert turns(out, sub="terminal-inferred") == 1
    assert turns(out, vendor="OpenAI", sub="terminal") == 1
    assert codex_totals(out, "gpt-6-astra")["input"] == 10
