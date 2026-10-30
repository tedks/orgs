"""Turn usage + catalog into ranked dispatch recommendations.

Every insight is computed from data; none is written by hand, so re-running
after a model ships re-derives all of them. Each carries the evidence it
rests on and a confidence:

  strong      the cheaper model wins at least one same-source comparison
              and loses none
  mixed       it wins some same-source comparisons and loses others; both
              are listed, because one favourable benchmark is not the story
  indicative  its only wins come from comparing scores across sources.
              Harnesses differ: one model's SWE-bench Verified score was
              measured 12 points apart by two sources
  fact        a statement about your own usage, not a capability claim

`weight` ranks insights within one kind only; kinds weigh different things
(turns, list dollars), so the report groups by kind rather than merging.

Dollar figures are list-price equivalents from the catalog, never a bill.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field

from .aggregate import Usage
from .catalog import Catalog, Price

STRONG, MIXED, INDICATIVE, FACT = "strong", "mixed", "indicative", "fact"
# Anthropic bills a 5-minute cache write at 1.25x input. Logs do not say
# which TTL was used, so the cheaper, more common one is assumed.
CLAUDE_CACHE_WRITE_MULTIPLIER = 1.25


@dataclass
class Params:
    recent_days: int = 30
    min_vendor_recent_turns: int = 500  # below this a vendor's mix is noise
    heavy_share: float = 0.10  # a model you lean on
    ignore_share: float = 0.05  # a model you are not really using
    min_age_days: int = 21  # give a new model three weeks before nagging
    tier_down_min_turns: int = 2000  # enough use to have formed an opinion
    drop_in_min_recent_turns: int = 50
    cached_share_threshold: float = 0.90
    min_list_cost: float = 100.0  # ignore context-shape findings below this
    min_terminal_coverage: float = 0.95  # Claude output tokens trusted above this
    tier_mix_min_turns: int = 500


@dataclass
class Insight:
    kind: str
    title: str
    detail: str
    confidence: str
    weight: float
    models: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _money(x: float) -> str:
    return f"${x:,.0f}"


def _price(p: Price | None) -> str:
    return f"${p.input:g}/${p.output:g}" if p else "price unknown"


# ---------------------------------------------------------------- costing


def codex_cost(tok: collections.Counter, p: Price) -> float | None:
    """List-price cost of Codex usage. input includes cached; reasoning is
    already inside output."""
    if p.cache_read is None:
        return None
    fresh = max(0, tok["input"] - tok["cached"])
    return (fresh * p.input + tok["cached"] * p.cache_read + tok["output"] * p.output) / 1e6


def claude_cost(tok: collections.Counter, p: Price) -> float | None:
    if p.cache_read is None:
        return None
    return (
        tok["input"] * p.input
        + tok["cache_write"] * p.input * CLAUDE_CACHE_WRITE_MULTIPLIER
        + tok["cache_read"] * p.cache_read
        + tok["output"] * p.output
    ) / 1e6


# ------------------------------------------------------------------ roll-up


def by_catalog_id(usage: Usage, cat: Catalog, months: set[str] | None = None) -> dict:
    """Usage summed per CATALOG model. Logs name one model several ways
    (Antigravity reports "Gemini 3.1 Pro (High)", the CLI
    "gemini-3.1-pro-preview"), so every rule must roll up by catalog id
    before comparing, or an aliased model is counted as several."""
    out: dict[str, dict] = {}
    for name, mu in usage.models.items():
        m = cat.resolve(name)
        if not m:
            continue
        agg = out.setdefault(m.id, {"turns": 0, "first_use": None})
        agg["turns"] += usage.model_turns(name, months)
        if mu.first_use and (agg["first_use"] is None or mu.first_use < agg["first_use"]):
            agg["first_use"] = mu.first_use
    return out


def tokens_by_catalog_id(table: dict, cat: Catalog) -> dict[str, collections.Counter]:
    out: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for name, tok in table.items():
        m = cat.resolve(name)
        if m:
            out[m.id].update(tok)
    return out


# ------------------------------------------------------------------- rules


def unknown_models(usage: Usage, cat: Catalog, prm: Params) -> list[Insight]:
    out = []
    for mid, mu in usage.models.items():
        if cat.resolve(mid) is None:
            out.append(
                Insight(
                    "unknown-model",
                    f"{mid} is not in the catalog",
                    f"You ran it {mu.turns:,} times ({mu.vendor}), first on {mu.first_use}. "
                    "Add it to catalog/models.toml so it can be tiered, priced and compared.",
                    FACT,
                    float(mu.turns),
                    [mid],
                    {"turns": mu.turns, "first_use": str(mu.first_use)},
                )
            )
    return out


def ignored_cheaper(usage: Usage, cat: Catalog, prm: Params) -> list[Insight]:
    recent = usage.recent_months(prm.recent_days)
    rolled = by_catalog_id(usage, cat, recent)
    ever = by_catalog_id(usage, cat)
    out = []
    for vendor in sorted({m.vendor for m in cat.models.values()}):
        vt = usage.vendor_turns(vendor, recent)
        if vt < prm.min_vendor_recent_turns:
            continue
        shares = {i: r["turns"] / vt for i, r in rolled.items() if cat.models[i].vendor == vendor}
        heavy = [cat.models[i] for i, s in shares.items() if s >= prm.heavy_share]
        for c in cat.models.values():
            if c.vendor != vendor or not c.dispatchable or not c.price or not c.released:
                continue
            if c.successor:
                continue  # a newer drop-in exists; suggest that instead, never go back
            if (usage.as_of - c.released).days < prm.min_age_days:
                continue
            if shares.get(c.id, 0.0) >= prm.ignore_share:
                continue
            over = [
                h for h in heavy if h.price and h.tier > c.tier and c.price.input < h.price.input
            ]
            if not over:
                continue
            h = max(over, key=lambda x: shares[x.id])
            first_use = ever.get(c.id, {}).get("first_use")
            lag = (first_use - c.released).days if first_use else None
            first = f"first used {lag} days after release" if lag is not None else "never used"
            out.append(
                Insight(
                    "ignored-cheaper",
                    f"{c.id} is {h.price.input / c.price.input:.0f}x cheaper than {h.id} "
                    f"and gets {_pct(shares.get(c.id, 0.0))} of your recent {vendor} turns",
                    f"{c.id} ({c.tier_name}, {_price(c.price)}) shipped {c.released}, "
                    f"{(usage.as_of - c.released).days} days ago, {first}. Over the same "
                    f"months {h.id} ({h.tier_name}, {_price(h.price)}) took "
                    f"{_pct(shares[h.id])}. Try it on the work {h.id} handles that does "
                    "not need the tier above.",
                    FACT,
                    shares[h.id] * vt,
                    [c.id, h.id],
                    {
                        "vendor": vendor,
                        "recent_vendor_turns": vt,
                        "share": shares.get(c.id, 0.0),
                        "heavy_share": shares[h.id],
                        "lag_days": lag,
                    },
                )
            )
    return out


def compare(m, c) -> dict:
    """Every benchmark comparison between m and a candidate c.

    Returns same-source wins and losses (the only ones that are evidence of
    a real difference) and cross-source wins (suggestive at best)."""
    wins, losses, cross = [], [], []
    for sm in m.scores:
        for sc in c.score(sm.bench):
            row = (sm.bench, sm.score, sc.score, sm.source, sc.source)
            if sc.source == sm.source:
                (wins if sc.score >= sm.score else losses).append(row)
            elif sc.score >= sm.score:
                cross.append(row)
    return {"wins": wins, "losses": losses, "cross": cross}


def _fmt_cmp(cat: Catalog, rows) -> str:
    return ", ".join(
        f"{cat.benchmarks[b]['name']} {to:g} vs {frm:g} ({to - frm:+g})" for b, frm, to, *_ in rows
    )


def tier_down(usage: Usage, cat: Catalog, prm: Params) -> list[Insight]:
    """For each model you relied on, the cheaper dispatchable model with the
    best evidence of matching it, with the evidence against it shown too."""
    out = []
    totals = {i: r["turns"] for i, r in by_catalog_id(usage, cat).items()}
    for mid, turns in totals.items():
        m = cat.models[mid]
        if turns < prm.tier_down_min_turns or not m.price or not m.scores:
            continue
        cands = []
        for c in cat.models.values():
            if c.id == m.id or not c.dispatchable or not c.price or c.successor:
                continue
            if c.price.input >= m.price.input:
                continue
            cmp = compare(m, c)
            if cmp["wins"] and not cmp["losses"]:
                conf = STRONG
            elif cmp["wins"]:
                conf = MIXED
            elif cmp["cross"]:
                conf = INDICATIVE
            else:
                continue
            cands.append((conf, c, cmp))
        if not cands:
            continue
        rank = {STRONG: 0, INDICATIVE: 1, MIXED: 2}
        cands.sort(key=lambda x: (rank[x[0]], x[1].price.input))
        conf, c, cmp = cands[0]
        cross_vendor = c.vendor != m.vendor
        evidence = cmp["wins"] or cmp["cross"]
        parts = [f"You ran {m.id} {turns:,} times."]
        label = "Same source" if cmp["wins"] else "Across sources"
        parts.append(f"{label}, {c.id} matches or beats it on {_fmt_cmp(cat, evidence)}.")
        if cmp["losses"]:
            parts.append(f"It loses on {_fmt_cmp(cat, cmp['losses'])}.")
        parts.append(f"{_price(c.price)} against {_price(m.price)}.")
        if cross_vendor:
            parts.append(
                f"This is a switch from {m.vendor} to {c.vendor}, so the harness changes too."
            )
        others = sorted({x[1].id for x in cands} - {c.id})
        if others:
            parts.append(f"Other candidates: {', '.join(others)}.")
        verb = "partly matches" if conf == MIXED else "matches"
        out.append(
            Insight(
                "tier-down",
                f"{c.id} {verb} what you trusted {m.id} for, at "
                f"{_pct(c.price.input / m.price.input)} of the input price"
                + (" (other vendor)" if cross_vendor else ""),
                " ".join(parts),
                conf,
                float(turns) * (1 - c.price.input / m.price.input),
                [m.id, c.id],
                {
                    "turns": turns,
                    "wins": cmp["wins"],
                    "losses": cmp["losses"],
                    "cross_source_wins": cmp["cross"],
                    "cross_vendor": cross_vendor,
                    "others": others,
                },
            )
        )
    return out


def drop_in(usage: Usage, cat: Catalog, prm: Params) -> list[Insight]:
    recent = usage.recent_months(prm.recent_days)
    out = []
    for mid, rolled in by_catalog_id(usage, cat, recent).items():
        m = cat.models[mid]
        if not m.successor:
            continue
        s = cat.models[m.successor]
        n = rolled["turns"]
        if n < prm.drop_in_min_recent_turns or not s.dispatchable:
            continue
        out.append(
            Insight(
                "drop-in",
                f"{m.id} → {s.id}: a drop-in upgrade you have not finished making",
                f"{n:,} of your recent turns still went to {m.id}. {s.id} is its "
                f"same-vendor successor at {_price(s.price)} against {_price(m.price)}.",
                FACT,
                float(n),
                [m.id, s.id],
                {"recent_turns": n},
            )
        )
    return out


def context_shape(usage: Usage, cat: Catalog, prm: Params) -> list[Insight]:
    """Cache-heavy workloads on an expensive tier. When most tokens are cached
    re-reads, the cached-input rate is the bill, not the headline price."""
    out = []
    sources = [
        ("codex", tokens_by_catalog_id(usage.codex_tokens, cat), codex_cost),
        ("claude", tokens_by_catalog_id(usage.claude_tokens, cat), claude_cost),
    ]
    for kind, table, cost_fn in sources:
        for mid, tok in table.items():
            m = cat.models[mid]
            if not m.price or m.price.cache_read is None or m.tier < 3:
                continue
            if kind == "codex":
                cached, total_in = tok["cached"], tok["input"]
            else:
                cached = tok["cache_read"]
                total_in = tok["input"] + tok["cache_read"] + tok["cache_write"]
                cov = tok["terminal_responses"] / tok["responses"] if tok["responses"] else 0
                if cov < prm.min_terminal_coverage:
                    continue  # output tokens under-recorded; a cost would be wrong
            if not total_in or cached / total_in < prm.cached_share_threshold:
                continue
            base = cost_fn(tok, m.price)
            if base is None or base < prm.min_list_cost:
                continue
            alts = []
            for c in cat.models.values():
                if c.vendor != m.vendor or c.tier >= m.tier or not c.dispatchable:
                    continue
                if not c.price or c.price.cache_read is None:
                    continue
                alts.append((cost_fn(tok, c.price), c))
            if not alts:
                continue
            alts.sort(key=lambda x: x[0])
            mid_alt = next((a for a in alts if a[1].tier == 2), alts[0])
            priced = [m] + [a[1] for a in alts]
            assumed = [x.id for x in priced if x.price.cache_read_basis != "published"]
            out.append(
                Insight(
                    "context-shape",
                    f"{m.id}: {_pct(cached / total_in)} of input was cached re-reading — "
                    f"{_money(base)} at list, {_money(mid_alt[0])} on {mid_alt[1].id}",
                    f"When a workload is mostly cached context, the model's cached-input rate "
                    f"dominates the bill. The same tokens on {mid_alt[1].id} "
                    f"({mid_alt[1].tier_name}) cost {base / mid_alt[0]:.1f}x less; "
                    f"on {alts[0][1].id} {base / alts[0][0]:.0f}x less.",
                    FACT,
                    base - mid_alt[0],
                    [m.id] + [a[1].id for a in alts],
                    {
                        "cached_share": cached / total_in,
                        "list_cost": base,
                        "alternatives": {a[1].id: a[0] for a in alts},
                        "assumed_cache_rates": assumed,
                        "tokens": dict(tok),
                    },
                )
            )
    return out


def tier_mix(usage: Usage, cat: Catalog, prm: Params) -> list[Insight]:
    """Share of each vendor's automated turns that run on a cheap or mid tier.
    Delegated work is where a cheaper tier is easiest to adopt."""
    auto: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in usage.rows:
        if r["channel"] != "automated":
            continue
        m = cat.resolve(r["model"])
        if m:
            auto[m.vendor]["low" if m.tier <= 2 else "high"] += r["turns"]
    shares = {
        v: c["low"] / (c["low"] + c["high"])
        for v, c in auto.items()
        if c["low"] + c["high"] >= prm.tier_mix_min_turns
    }
    if len(shares) < 2:
        return []
    lo = min(shares, key=shares.get)
    hi = max(shares, key=shares.get)
    if shares[hi] - shares[lo] < 0.25:
        return []
    return [
        Insight(
            "tier-mix",
            f"You delegate to cheap tiers on {hi} ({_pct(shares[hi])}) but not on {lo} "
            f"({_pct(shares[lo])})",
            f"Of your automated {lo} turns, {_pct(shares[lo])} ran on a cheap or mid tier, "
            f"against {_pct(shares[hi])} on {hi}. The habit that works on {hi} has not "
            f"carried over to {lo}.",
            FACT,
            float(sum(auto[lo].values())),
            [],
            {"automated_low_tier_share": shares},
        )
    ]


RULES = (unknown_models, tier_down, context_shape, ignored_cheaper, drop_in, tier_mix)


def compute(usage: Usage, cat: Catalog, prm: Params | None = None) -> list[Insight]:
    prm = prm or Params()
    found = [i for rule in RULES for i in rule(usage, cat, prm)]
    return sorted(found, key=lambda i: -i.weight)


def adoption(usage: Usage, cat: Catalog) -> list[dict]:
    """Days from public release to your first turn, per model."""
    rows = []
    for mid, r in by_catalog_id(usage, cat).items():
        m = cat.models[mid]
        if m.released and r["first_use"]:
            rows.append(
                {
                    "model": m.id,
                    "vendor": m.vendor,
                    "released": m.released.isoformat(),
                    "first_use": r["first_use"].isoformat(),
                    "lag_days": (r["first_use"] - m.released).days,
                    "turns": r["turns"],
                }
            )
    return sorted(rows, key=lambda r: r["released"])


def drift(usage: Usage, cat: Catalog) -> dict[str, dict[str, dict[int, int]]]:
    """Turns per vendor per month per tier: how your tier mix moved."""
    out: dict = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in usage.rows:
        m = cat.resolve(r["model"])
        tier = m.tier if m else 0  # 0 = not in catalog
        out[r["vendor"]][r["month"]][tier] += r["turns"]
    return {v: {mo: dict(t) for mo, t in ms.items()} for v, ms in out.items()}
