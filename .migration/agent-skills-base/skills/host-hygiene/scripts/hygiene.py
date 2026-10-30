#!/usr/bin/env python3
"""Read-only remote inventory, followed by separately reviewed exact deletions."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import stat
import subprocess
import sys
import time

DAY = 86400
FULL_ID = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
STORE_PATH = re.compile(r"/nix/store/[0-9a-z]{32}-[^/\s]+\Z")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{shlex.join(args)}: {result.stderr.strip() or 'failed'}")
    return result.stdout


def timestamp(value):
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})", value)
    if not match:
        raise ValueError("invalid timezone-qualified Docker timestamp")
    base, fraction, zone = match.groups()
    fraction = "." + fraction[:6].ljust(6, "0") if fraction else ""
    zone = "+00:00" if zone == "Z" else zone
    return dt.datetime.fromisoformat(base + fraction + zone).timestamp()


def size(path):
    # du never follows symlinks; failure keeps the entry ineligible.
    return int(run("du", "-s", "-B1", "--", path).split()[0])


def directory_sizes(paths):
    """Bounded GNU du batches; no partial or unrecognized sizes are trusted."""
    if not paths:
        return {}, {}
    sizes, errors = {}, {}
    deadline = time.monotonic() + 60
    def mounts():
        # -x alone does not exclude bind mounts or mounted root operands.
        result = set()
        for line in Path("/proc/self/mountinfo").read_bytes().splitlines():
            fields = line.split()
            if len(fields) < 7 or b" - " not in line:
                raise RuntimeError("unsupported mountinfo record")
            name = re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m[1], 8)]), fields[4])
            if not name.startswith(b"/"):
                raise RuntimeError("unsupported mountinfo path")
            result.add(name)
        return result
    def identity(path):
        st = path.lstat()
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError("directory replaced with nondirectory")
        return st.st_dev, st.st_ino, st.st_mode, st.st_mtime_ns, st.st_ctime_ns, st.st_uid
    try:
        original_mounts = mounts()
    except (OSError, RuntimeError) as exc:
        return {}, {str(p): "directory measurement unavailable: " + str(exc) for p in paths}
    for offset in range(0, len(paths), 256):
        batch, before = [], {}
        for path in paths[offset:offset + 256]:
            name = os.fsencode(path)
            try:
                # Kernel mount paths and operands must use the same namespace.
                if not path.is_absolute() or path.resolve(strict=True) != path:
                    raise RuntimeError("directory path alias; no traversal")
                if any(m == name or m.startswith(name + b"/") for m in original_mounts):
                    raise RuntimeError("directory is or contains a mount; no traversal")
                before[name] = identity(path)
                batch.append(name)
            except (OSError, RuntimeError) as exc:
                errors[str(path)] = "directory measurement unavailable: " + str(exc)
        if not batch:
            continue
        try:
            if mounts() != original_mounts:
                raise RuntimeError("mount inventory changed before directory measurement")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("directory measurement exceeded 60s budget")
            result = subprocess.run(
                ["du", "--summarize", "--block-size=1", "--null", "--no-dereference",
                 "--one-file-system", "--count-links", "--files0-from=-"],
                input=b"".join(name + b"\0" for name in batch), capture_output=True,
                timeout=remaining)
            if result.returncode or result.stderr:
                raise RuntimeError("GNU du batch failed (exit " + str(result.returncode) +
                                   "); partial sizes discarded; stderr_bytes=" + str(len(result.stderr)) +
                                   "; stderr (first 512 bytes)=" + repr(os.fsdecode(result.stderr[:512])) +
                                   "; partial stdout_bytes=" + str(len(result.stdout)) +
                                   "; partial stdout (first 512 bytes)=" + repr(result.stdout[:512]))
            if not result.stdout.endswith(b"\0"):
                raise RuntimeError("unsupported GNU du output: missing NUL terminator")
            measured = {}
            for record in result.stdout[:-1].split(b"\0"):
                amount, separator, name = record.partition(b"\t")
                if (not separator or not re.fullmatch(rb"[0-9]+", amount)
                        or name not in before or name in measured):
                    raise RuntimeError("unsupported GNU du output: invalid/duplicate/unrequested record")
                measured[name] = int(amount)
            if set(measured) != set(batch):
                raise RuntimeError("incomplete GNU du output: missing requested directory")
            if mounts() != original_mounts:
                raise RuntimeError("mount inventory changed during directory measurement")
            for name in batch:
                if identity(Path(os.fsdecode(name))) != before[name]:
                    raise RuntimeError("directory identity changed during measurement")
            sizes.update({os.fsdecode(name): amount for name, amount in measured.items()})
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            for name in batch:
                errors[os.fsdecode(name)] = "directory measurement unavailable: " + str(exc)
    return sizes, errors

def cache_size(value):
    # Older Buildx versions JSON-format human sizes rather than byte counts.
    text = str(value)
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(B|kB|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?", text)
    if not match:
        raise RuntimeError(f"unknown cache size: {text!r}")
    units = {None: 1, "B": 1, "kB": 1000, "KB": 1000, "MB": 1000**2,
             "GB": 1000**3, "TB": 1000**4, "KiB": 1024, "MiB": 1024**2,
             "GiB": 1024**3, "TiB": 1024**4}
    return int(float(match[1]) * units[match[2]]), match[2] in (None, "B")


def protections(policy):
    texts, errors = [], []
    paths = policy.get("records")
    if not isinstance(paths, list) or not paths:
        return "", ["policy records must name the required current owner/lane protection documents"]
    for name in paths:
        path = Path(name).expanduser()
        try:
            texts.append(path.read_text())
        except (OSError, UnicodeError) as exc:
            errors.append(f"protection record {path}: {exc}")
    return "\n".join(texts), errors


def policy_root(policy):
    root = policy.get("projects_root") if isinstance(policy, dict) else None
    if (not isinstance(root, str) or not Path(root).is_absolute()
            or any(ord(c) < 32 or ord(c) == 127 for c in root)):
        raise ValueError("policy requires an absolute remote projects_root; local configuration is not a remote path")
    return Path(root)


def worktrees(policy):
    """Conservatively protect every compose file under the declared project root."""
    root = policy_root(policy)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"project root unreadable: {root}")
    texts = []
    deadline = time.monotonic() + 60
    def failed(exc):
        raise exc
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        if time.monotonic() > deadline:
            raise RuntimeError("project reference scan exceeded 60s; retain Docker/cache; choose a complete narrower project root")
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise RuntimeError(f"symlink directory leaves project reference coverage incomplete: {Path(directory) / name}; review external references explicitly and declare a complete root")
        if ".git" in files or ".git" in dirs:
            texts.append(str(Path(directory)))
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", ".bare", ".venv")]
        for name in files:
            if (("compose" in name.lower() and name.endswith((".yaml", ".yml")))
                    or name in ("docker-compose.yml", "docker-compose.yaml")):
                path = Path(directory) / name
                if path.is_symlink():
                    raise RuntimeError(f"compose symlink needs manual reference review: {path}")
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise RuntimeError(f"nonregular compose file needs manual reference review: {path}")
                texts.append(str(path) + "\n" + path.read_text())
    return "\n".join(texts)


def inventory(policy, record_text, record_errors):
    now = time.time()
    entries, diagnostics = [], list(record_errors)
    refs = record_text + "\n" + "\n".join(policy.get("protected", []))
    reference_ok = not record_errors
    try:
        refs += "\n" + worktrees(policy)
    except (OSError, UnicodeError, RuntimeError) as exc:
        diagnostics.append(str(exc))
        reference_ok = False
    # A separate text token is intentionally conservative: any mention retains it.
    def mentioned(tokens):
        return any(token and token in refs for token in tokens)
    claims = policy.get("claims", [])
    def owner(kind, ident):
        matches = [c for c in claims if c.get("kind") == kind and c.get("id") == ident]
        # Conflicting claims, including a peer's non-idle claim, never confer ownership.
        return matches[0]["owner"] if len(matches) == 1 and matches[0].get("idle") is True and matches[0].get("owner") else None
    def add(kind, ident, name, bytes_, identity, eligible, reason, tokens):
        valid_size = type(bytes_) is int and bytes_ >= 0
        if not valid_size:
            bytes_ = None
            reason = "retain: unknown/invalid byte size; " + reason
        entries.append(dict(kind=kind, id=ident, name=name, bytes=bytes_,
                            identity=digest(identity), eligible=bool(eligible and valid_size and (not record_errors if kind == "nix" else reference_ok)
                                                                      and not mentioned(tokens)),
                            owner=owner(kind, ident), reason=reason))
    try:
        container_ids = run("docker", "container", "ls", "-aq", "--no-trunc").split()
        containers = [json.loads(run("docker", "container", "inspect", "--size", ident))[0]
                      for ident in container_ids]
        image_ids = sorted(set(run("docker", "image", "ls", "-aq", "--no-trunc").split()))
        images = [json.loads(run("docker", "image", "inspect", ident))[0] for ident in image_ids]
        volumes = run("docker", "volume", "ls", "-q").split()
        # Complete inventory before marking Docker entries eligible; any failure disables all.
        volume_data = [json.loads(run("docker", "volume", "inspect", name))[0] for name in volumes]
        used_images = {c["Image"] for c in containers}
        used_volumes = {m["Name"] for c in containers for m in c.get("Mounts", [])
                        if m.get("Type") == "volume"}
        for c in containers:
            ident, name = c["Id"], c["Name"].lstrip("/")
            labels = c.get("Config", {}).get("Labels") or {}
            tokens = [ident, name, c["Image"], c.get("Config", {}).get("Image", "")]
            tokens += list(labels.values())
            exited = c["State"]["Status"] == "exited"
            old = exited and now - timestamp(c["State"]["FinishedAt"]) > DAY
            add("container", ident, name, c["SizeRw"], c, old and owner("container", ident),
                "exited >24h; exact owner-confirmed idle required", tokens)
        for img in images:
            ident = img["Id"]
            tags = img.get("RepoTags") or []
            tags = [t for t in tags if t != "<none>:<none>"]
            old = now - timestamp(img["Created"]) > 14 * DAY
            tokens = [ident] + tags + list((img.get("Config", {}).get("Labels") or {}).values())
            # Tagged deletion additionally needs an explicit release of every current tag.
            release = any(c.get("kind") == "image" and c.get("id") == ident
                          and sorted(c.get("released_tags", [])) == sorted(tags)
                          for c in claims)
            eligible = (not tags or (old and release)) and ident not in used_images and owner("image", ident)
            add("image", ident, ", ".join(tags) or "<untagged>", img["Size"], img, eligible,
                "untagged/unreferenced; owner required" if not tags else
                ("old >14d tagged; explicit released_tags and idle owner required" if old else
                 "tagged image younger than 14d; retain"), tokens)
        for v in volume_data:
            name = v["Name"]
            labels = v.get("Labels") or {}
            project = labels.get("com.docker.compose.project", "")
            mount = v["Mountpoint"]
            try:
                bytes_ = size(mount)
                st = os.stat(mount, follow_symlinks=False)
                identity = [v, st.st_dev, st.st_ino, st.st_mtime_ns, bytes_]
                eligible = bool(project and name not in used_volumes and owner("volume", name))
                reason = "unreferenced compose volume; exact owner-confirmed idle required"
            except (OSError, ValueError, RuntimeError) as exc:
                bytes_, identity, eligible = None, v, False
                reason = f"retain: volume size/identity inaccessible: {exc}; root-needed: sudo du -s -B1 -- {shlex.quote(mount)}"
            add("volume", name, name, bytes_, identity, eligible, reason,
                [name, project] + list(labels.values()))
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        diagnostics.append(f"Docker inventory incomplete; retain all Docker entries: {exc}")
        for entry in entries:
            entry["eligible"] = False
    try:
        roots = run("nix-store", "--gc", "--print-roots")
        dead = run("nix-store", "--gc", "--print-dead").splitlines()
        diagnostics.append("Nix roots (read-only):\n" + roots)
        for path in dead:
            if not STORE_PATH.fullmatch(path):
                raise RuntimeError(f"invalid dead store path: {path!r}")
            st = os.stat(path, follow_symlinks=False)
            bytes_ = int(run("nix-store", "--query", "--size", path).strip())
            add("nix", path, path, bytes_, [st.st_dev, st.st_ino, st.st_mtime_ns, bytes_],
                True, "dead graph member; daemon rechecks liveness (store mtime is not installation age)",
                [path])
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        diagnostics.append(f"Nix inventory incomplete; retain all Nix entries: {exc}")
        for entry in entries:
            if entry["kind"] == "nix":
                entry["eligible"] = False
    try:
        builder = policy.get("builder")
        if not builder or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", builder):
            raise RuntimeError("policy must name a fixed builder to inventory/apply cache")
        backend = run("docker", "buildx", "inspect", builder)
        records = run("docker", "buildx", "du", "--builder", builder, "--format=json", "--filter", "until=72h")
        for line in records.splitlines():
            cache = json.loads(line)
            ident = cache["ID"]
            # until=72h is the backend age check; LastUsedAt can be human text.
            old = True
            bytes_, exact = cache_size(cache["Size"])
            private = cache["Shared"] is False and cache["Mutable"] is False and cache["Reclaimable"] is True
            add("cache", ident, cache["Description"], bytes_, [builder, backend, cache],
                old and private and owner("cache", ident),
                "unused >72h; immutable/private/reclaimable; exact idle owner required",
                [ident, cache["Description"]])
            entries[-1]["size_display"] = cache["Size"]
            entries[-1]["size_exact"] = exact
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        diagnostics.append(f"Build cache >72h inventory incomplete; retain all cache: {exc}")
        for entry in entries:
            if entry["kind"] == "cache":
                entry["eligible"] = False
    try:
        candidates = []
        for path in Path("/tmp").iterdir():
            try:
                st = path.lstat()
                if now - st.st_mtime > 2 * DAY:
                    candidates.append((path, st))
            except OSError as exc:
                diagnostics.append(f"/tmp entry {path}: retain: {exc}")
        sizes, errors = directory_sizes([p for p, st in candidates if stat.S_ISDIR(st.st_mode)])
        for path, st in candidates:
            directory = stat.S_ISDIR(st.st_mode)
            bytes_ = sizes.get(str(path)) if directory else st.st_blocks * 512
            if directory:
                try:
                    current = path.lstat()
                    if (current.st_dev, current.st_ino, current.st_mode, current.st_mtime_ns,
                        current.st_ctime_ns, current.st_uid) != (st.st_dev, st.st_ino, st.st_mode,
                        st.st_mtime_ns, st.st_ctime_ns, st.st_uid):
                        raise RuntimeError("directory changed since enumeration")
                except (OSError, RuntimeError) as exc:
                    bytes_ = None
                    errors[str(path)] = "directory measurement unavailable: " + str(exc)
            reason = "retain: unprivileged inventory cannot prove complete peer proc/mount/socket references; "
            if str(path) in errors:
                reason += errors[str(path)] + "; "
                diagnostics.append(f"/tmp entry {path}: retain: {errors[str(path)]}")
            if directory:
                reason += "directory allocated-byte estimate counts every hardlink; not freed bytes; "
            reason += ("root-needed diagnostics: sudo lsof +D " + shlex.quote(str(path)) +
                       "; sudo findmnt --target " + shlex.quote(str(path)))
            add("tmp", str(path), str(path), bytes_,
                [st.st_dev, st.st_ino, st.st_mtime_ns, st.st_uid, bytes_], False, reason, [str(path)])
            entries[-1]["size_exact"] = not directory
    except OSError as exc:
        diagnostics.append(f"/tmp inventory inaccessible; retain: {exc}")
    return dict(version=1, machine=socket.gethostname(), uid=os.getuid(), created=now,
                entries=entries, diagnostics=diagnostics, reference_ok=reference_ok,
                tmp_owner=policy.get("tmp_owner", "unknown"))


def apply(plan, policy, record_text, record_errors, owner):
    # One complete inventory, then targeted identity checks; never O(paths * inventory).
    fresh = inventory(policy, record_text, record_errors)
    if plan["machine"] != fresh["machine"] or plan["uid"] != fresh["uid"]:
        raise RuntimeError("plan host/user identity mismatch")
    current = {(e["kind"], e["id"]): e for e in fresh["entries"]}
    results, nix = [], []
    response = dict(results=results, diagnostics=fresh["diagnostics"], status="ok")
    for entry in plan["entries"]:
        key = entry["kind"], entry["id"]
        new = current.get(key)
        reason = "not eligible or fresh identity/reference/age/ownership changed"
        if key[0] == "tmp":
            reason = "retain /tmp: current owner=" + str(fresh["tmp_owner"]) + "; complete references unavailable"
        elif (entry.get("eligible") is True and new and new["eligible"]
              and new["identity"] == entry["identity"]
              and (key[0] == "nix" or entry.get("owner") == new["owner"] == owner)):
            kind, ident = key
            try:
                if kind in ("container", "image") and not FULL_ID.fullmatch(ident):
                    raise RuntimeError("invalid full Docker ID")
                if kind == "nix" and not STORE_PATH.fullmatch(ident):
                    raise RuntimeError("invalid exact store path")
                if kind == "volume" and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", ident):
                    raise RuntimeError("invalid volume name")
                if kind == "nix":
                    nix.append(entry)
                    continue
                if kind == "cache":
                    if not re.fullmatch(r"[a-z0-9]{25,64}", ident):
                        raise RuntimeError("invalid exact cache ID")
                    builder = policy["builder"]
                    backend = run("docker", "buildx", "inspect", builder)
                    raw = run("docker", "buildx", "du", "--builder", builder, "--format=json",
                              "--filter", "id=" + ident, "--filter", "until=72h")
                    records = [json.loads(line) for line in raw.splitlines()]
                    if len(records) != 1 or records[0]["ID"] != ident or digest([builder, backend, records[0]]) != new["identity"]:
                        results.append(dict(kind=kind, id=ident, action="retained", reason="cache/backend changed before prune"))
                        continue
                    run("docker", "buildx", "prune", "--builder", builder, "--force",
                        "--filter", "id=" + ident, "--filter", "until=72h",
                        "--filter", "private=true", "--filter", "inuse=false", "--filter", "immutable=true")
                    remains = run("docker", "buildx", "du", "--builder", builder,
                                  "--format=json", "--filter", "id=" + ident)
                    results.append(dict(kind=kind, id=ident, action="retained" if remains.strip() else "deleted",
                                        reason="exact-ID prune; backend absence verified" if not remains.strip() else "backend retained cache"))
                    continue
                args = ["docker", kind, "inspect"] + (["--size"] if kind == "container" else [])
                inspected = json.loads(run(*args, ident))[0]
                identity = inspected
                if kind == "volume":
                    mount = inspected["Mountpoint"]
                    st = os.stat(mount, follow_symlinks=False)
                    identity = [inspected, st.st_dev, st.st_ino, st.st_mtime_ns, size(mount)]
                if digest(identity) != new["identity"]:
                    results.append(dict(kind=kind, id=ident, action="retained", reason="changed before delete"))
                    continue
                run("docker", kind, "rm", "--", ident)
                listing = ["docker", kind, "ls"] + (["-q"] if kind == "volume" else ["-aq", "--no-trunc"])
                remaining = run(*listing).split()
                if ident in remaining:
                    raise RuntimeError("delete returned success but exact Docker entry remains")
                results.append(dict(kind=kind, id=ident, action="deleted"))
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
                results.append(dict(kind=kind, id=ident, action="failed", reason=str(exc)))
                response["status"] = "failed"
                return response
            continue
        results.append(dict(kind=key[0], id=key[1], action="retained", reason=reason))
    if nix:
        try:
            # Batch preserves referrer ordering: the daemon can collect the exact reviewed graph.
            dead = set(run("nix-store", "--gc", "--print-dead").splitlines())
            selected = []
            for entry in nix:
                path = entry["id"]
                if path not in dead:
                    results.append(dict(kind="nix", id=path, action="retained", reason="newly rooted/live"))
                    continue
                st = os.stat(path, follow_symlinks=False)
                bytes_ = int(run("nix-store", "--query", "--size", path).strip())
                if digest([st.st_dev, st.st_ino, st.st_mtime_ns, bytes_]) != entry["identity"]:
                    results.append(dict(kind="nix", id=path, action="retained", reason="identity changed"))
                    continue
                selected.append(path)
            if selected:
                run("nix-store", "--delete", *selected)
                for path in selected:
                    try:
                        os.stat(path, follow_symlinks=False)
                    except FileNotFoundError:
                        results.append(dict(kind="nix", id=path, action="deleted"))
                    else:
                        raise RuntimeError("Nix delete returned success but exact store path remains: " + path)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            # Nix may partially delete before an error: do not claim atomicity or successful receipt.
            results.append(dict(kind="nix", ids=[e["id"] for e in nix], action="failed",
                                reason=str(exc), partial_deletion_possible=True))
            response["status"] = "failed"
    return response


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--remote":
        request = json.load(sys.stdin)
        policy = request["policy"]
        policy_root(policy)
        if request["mode"] == "plan":
            result = inventory(policy, request["record_text"], request["record_errors"])
        else:
            result = apply(request["plan"], policy, request["record_text"],
                           request["record_errors"], request["owner"])
        print(json.dumps(result, indent=2), flush=True)
        if result.get("status") == "failed":
            sys.exit(1)
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("host", help="SSH host, e.g. build.local (no SSH options)")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--reviewed-sha256")
    parser.add_argument("--owner")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9@._-]*", args.host):
        parser.error("invalid SSH host")
    policy = json.loads(args.policy.read_text())
    policy_root(policy)
    record_text, record_errors = protections(policy)
    request = dict(mode=args.mode, policy=policy, record_text=record_text, record_errors=record_errors)
    if args.mode == "apply":
        raw = args.plan.read_bytes()
        if not args.owner or not args.reviewed_sha256 or hashlib.sha256(raw).hexdigest() != args.reviewed_sha256:
            parser.error("apply requires owner and exact reviewed SHA256 of saved plan")
        plan = json.loads(raw)
        if plan.get("version") != 1 or plan.get("host") != args.host:
            parser.error("plan version/SSH host mismatch")
        request.update(plan=plan, owner=args.owner)
    source = Path(__file__).read_text()
    command = "python3 -c " + shlex.quote(source) + " --remote"
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", args.host, command],
                            input=json.dumps(request), text=True, capture_output=True, timeout=900)
    if result.returncode:
        if result.stdout:
            print(result.stdout, end="", flush=True)
        raise RuntimeError("remote failed (no automatic retry; retain partial receipts): " + result.stderr.strip())
    data = json.loads(result.stdout)
    if args.mode == "plan":
        data["host"] = args.host
        # Do not overwrite the previously reviewed list; 0600 excludes other users.
        fd = os.open(args.plan, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, indent=2)
            output.write("\n")
        print(f"Plan: {args.plan}; reviewed digest: {hashlib.sha256(args.plan.read_bytes()).hexdigest()}")
        print(f"{len(data['entries'])} enumerated entries; {sum(e['eligible'] for e in data['entries'])} eligible")
        for diagnostic in data["diagnostics"]:
            print(diagnostic, file=sys.stderr)
    else:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"host-hygiene: {exc}", file=sys.stderr)
        sys.exit(1)
