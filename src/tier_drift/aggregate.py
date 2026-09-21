"""Merge per-host collector documents into one view of usage.

Collector output is bucketed by calendar month (UTC) for turns and tokens,
and by day only for first/last use. "Recent" therefore means whole months:
every month from the one containing (as_of - recent_days) onward.
"""

from __future__ import annotations

import collections
import datetime as dt
from dataclasses import dataclass, field

from . import collector

CHANNELS = ("direct", "automated", "unattributed")


class UsageError(ValueError):
    pass


@dataclass
class ModelUsage:
    model: str
    vendor: str
    turns: int = 0
    by_channel: collections.Counter = field(default_factory=collections.Counter)
    by_month: collections.Counter = field(default_factory=collections.Counter)
    first_use: dt.date | None = None
    last_use: dt.date | None = None


@dataclass
class Usage:
    hosts: list[dict]
    rows: list[dict]  # merged turn rows: vendor, model, month, channel, sub, turns
    claude_tokens: dict[str, collections.Counter]  # model -> summed fields
    codex_tokens: dict[str, collections.Counter]
    models: dict[str, ModelUsage]
    months: list[str]
    as_of: dt.date
    diagnostics: dict

    @property
    def total(self) -> int:
        return sum(r["turns"] for r in self.rows)

    def recent_months(self, days: int = 30) -> set[str]:
        start = (self.as_of - dt.timedelta(days=days)).strftime("%Y-%m")
        return {m for m in self.months if m >= start}

    def vendor_turns(self, vendor: str, months: set[str] | None = None) -> int:
        return sum(
            r["turns"]
            for r in self.rows
            if r["vendor"] == vendor and (months is None or r["month"] in months)
        )

    def model_turns(self, model: str, months: set[str] | None = None) -> int:
        mu = self.models.get(model)
        if mu is None:
            return 0
        if months is None:
            return mu.turns
        return sum(n for m, n in mu.by_month.items() if m in months)


def _day(value):
    return dt.date.fromisoformat(value) if value else None


def merge(docs: list[dict], as_of: dt.date | None = None) -> Usage:
    if not docs:
        raise UsageError("no collector documents to merge")
    seen_hosts = set()
    rows = collections.Counter()
    claude = collections.defaultdict(collections.Counter)
    codex = collections.defaultdict(collections.Counter)
    first: dict[str, str] = {}
    last: dict[str, str] = {}
    diag = {"errors": collections.Counter(), "deduplicated": collections.Counter()}
    gemini_projects = collections.Counter()
    hosts = []
    for doc in docs:
        if doc.get("schema") != collector.SCHEMA:
            raise UsageError(
                f"host {doc.get('host')!r} sent schema {doc.get('schema')!r}; "
                f"this tier-drift reads schema {collector.SCHEMA}. "
                "Re-run with a matching collector."
            )
        host = doc["host"]
        if host in seen_hosts:
            # The same machine collected twice would double every number.
            raise UsageError(f"host {host!r} appears twice")
        seen_hosts.add(host)
        host_turns = collections.Counter()
        for r in doc["turns"]:
            rows[(r["vendor"], r["model"], r["month"], r["channel"], r["sub"])] += r["turns"]
            host_turns[r["vendor"]] += r["turns"]
        for r in doc["claude_tokens"]:
            claude[r["model"]].update({k: v for k, v in r.items() if isinstance(v, int)})
        for r in doc["codex_tokens"]:
            codex[r["model"]].update({k: v for k, v in r.items() if isinstance(v, int)})
        for m, d in doc["first_use"].items():
            first[m] = min(first.get(m, d), d)
        for m, d in doc["last_use"].items():
            last[m] = max(last.get(m, d), d)
        dg = doc.get("diagnostics", {})
        diag["errors"].update(dg.get("errors", {}))
        diag["deduplicated"].update(dg.get("deduplicated", {}))
        gemini_projects.update(dict(dg.get("gemini_cli_projects", [])))
        hosts.append(
            {
                "host": host,
                "python": doc.get("python"),
                "seconds": doc.get("seconds"),
                "collected_at": doc.get("collected_at"),
                "turns": dict(host_turns),
                "sources": doc.get("sources", {}),
            }
        )

    merged = [
        {"vendor": k[0], "model": k[1], "month": k[2], "channel": k[3], "sub": k[4], "turns": n}
        for k, n in sorted(rows.items())
    ]
    models: dict[str, ModelUsage] = {}
    for r in merged:
        mu = models.setdefault(r["model"], ModelUsage(r["model"], r["vendor"]))
        mu.turns += r["turns"]
        mu.by_channel[r["channel"]] += r["turns"]
        mu.by_month[r["month"]] += r["turns"]
    for m, mu in models.items():
        mu.first_use = _day(first.get(m))
        mu.last_use = _day(last.get(m))
    months = sorted({r["month"] for r in merged})
    if as_of is None:
        seen = [mu.last_use for mu in models.values() if mu.last_use]
        as_of = max(seen) if seen else dt.date.today()
    diag["gemini_cli_projects"] = gemini_projects.most_common(10)
    return Usage(
        hosts=sorted(hosts, key=lambda h: -sum(h["turns"].values())),
        rows=merged,
        claude_tokens=dict(claude),
        codex_tokens=dict(codex),
        models=models,
        months=months,
        as_of=as_of,
        diagnostics={
            k: dict(v) if isinstance(v, collections.Counter) else v for k, v in diag.items()
        },
    )
