"""The model catalog: the one hand-edited input.

Loading validates the whole file and raises CatalogError listing every
problem at once. A catalog that loads with a silently dropped score or a
typo'd successor would make an insight quietly vanish, which is worse than
refusing to run.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

VENDORS = ("Anthropic", "OpenAI", "Google")
STATUSES = ("active", "legacy", "superseded", "deprecated", "retired")
CACHE_BASES = ("published", "assumed-0.1x")
TIER_NAMES = {1: "cheap", 2: "mid", 3: "flagship", 4: "frontier"}
# Statuses a recommendation may point AT: you can still send work there.
DISPATCHABLE = ("active", "legacy")

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "catalog" / "models.toml"


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float | None = None
    cache_read_basis: str | None = None


@dataclass(frozen=True)
class Score:
    bench: str
    score: float
    source: str


@dataclass(frozen=True)
class Model:
    id: str
    vendor: str
    family: str
    tier: int
    status: str
    aliases: tuple[str, ...] = ()
    released: dt.date | None = None
    context: int | None = None
    price: Price | None = None
    successor: str | None = None
    scores: tuple[Score, ...] = ()

    @property
    def tier_name(self) -> str:
        return TIER_NAMES[self.tier]

    @property
    def dispatchable(self) -> bool:
        return self.status in DISPATCHABLE

    def score(self, bench: str) -> list[Score]:
        return [s for s in self.scores if s.bench == bench]


@dataclass
class Catalog:
    as_of: dt.date
    models: dict[str, Model]
    sources: dict[str, dict]
    benchmarks: dict[str, dict]
    _alias: dict[str, str] = field(default_factory=dict, repr=False)

    def resolve(self, name: str) -> Model | None:
        """Catalog entry for a model id or alias as it appears in logs."""
        mid = name if name in self.models else self._alias.get(name)
        return self.models.get(mid) if mid else None

    def source_kind(self, source: str) -> str:
        return self.sources[source]["kind"]


def _date(value, where, errors):
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"{where}: {value!r} is not a YYYY-MM-DD date")
        return None


def load(path: Path | str = DEFAULT_PATH) -> Catalog:
    raw = tomllib.loads(Path(path).read_text())
    errors: list[str] = []
    if raw.get("catalog_version") != 1:
        errors.append(f"catalog_version must be 1, got {raw.get('catalog_version')!r}")
    as_of = _date(raw.get("as_of"), "as_of", errors)
    sources = raw.get("sources", {})
    benchmarks = raw.get("benchmarks", {})
    for name, src in sources.items():
        if src.get("kind") not in ("vendor", "third-party"):
            errors.append(f"source {name}: kind must be vendor or third-party")

    models: dict[str, Model] = {}
    alias: dict[str, str] = {}
    for i, m in enumerate(raw.get("models", [])):
        where = f"models[{i}] {m.get('id', '?')}"
        mid = m.get("id")
        if not mid:
            errors.append(f"{where}: missing id")
            continue
        if mid in models or mid in alias:
            errors.append(f"{where}: duplicate id")
        if m.get("vendor") not in VENDORS:
            errors.append(f"{where}: vendor must be one of {VENDORS}")
        if m.get("tier") not in TIER_NAMES:
            errors.append(f"{where}: tier must be 1-4")
        if m.get("status") not in STATUSES:
            errors.append(f"{where}: status must be one of {STATUSES}")
        price = None
        if "price" in m:
            p = m["price"]
            numeric = all(isinstance(p.get(k), (int, float)) for k in ("in", "out"))
            if not numeric:
                errors.append(f"{where}: price needs numeric in and out")
            elif p["in"] < 0 or p["out"] < 0:
                errors.append(f"{where}: negative price")
            else:
                cr = p.get("cache_read")
                basis = p.get("cache_read_basis")
                if (cr is None) != (basis is None):
                    errors.append(f"{where}: cache_read and cache_read_basis go together")
                elif basis is not None and basis not in CACHE_BASES:
                    errors.append(f"{where}: cache_read_basis must be one of {CACHE_BASES}")
                price = Price(float(p["in"]), float(p["out"]), cr, basis)
        scores = []
        for s in m.get("scores", []):
            if s.get("bench") not in benchmarks:
                errors.append(f"{where}: unknown benchmark {s.get('bench')!r}")
            elif s.get("source") not in sources:
                errors.append(f"{where}: unknown source {s.get('source')!r}")
            elif not isinstance(s.get("score"), (int, float)):
                errors.append(f"{where}: score for {s['bench']} is not a number")
            else:
                scores.append(Score(s["bench"], float(s["score"]), s["source"]))
        for a in m.get("aliases", []):
            if a in alias or a in models:
                errors.append(f"{where}: alias {a!r} collides")
            alias[a] = mid
        models[mid] = Model(
            id=mid,
            vendor=m.get("vendor", ""),
            family=m.get("family", ""),
            tier=m.get("tier", 0),
            status=m.get("status", ""),
            aliases=tuple(m.get("aliases", [])),
            released=_date(m.get("released"), f"{where} released", errors),
            context=m.get("context"),
            price=price,
            successor=m.get("successor"),
            scores=tuple(scores),
        )

    for mid, m in models.items():
        if m.successor is None:
            continue
        succ = models.get(m.successor)
        if succ is None:
            errors.append(f"{mid}: successor {m.successor!r} is not in the catalog")
        elif succ.vendor != m.vendor:
            errors.append(f"{mid}: successor must be the same vendor")
        elif (
            m.price
            and succ.price
            and (succ.price.input > m.price.input or succ.price.output > m.price.output)
        ):
            errors.append(f"{mid}: successor {succ.id} costs more, so it is not a drop-in")
    for a in alias:
        if a in models:
            errors.append(f"alias {a!r} is also a model id")

    if errors:
        raise CatalogError("invalid catalog:\n  " + "\n  ".join(errors))
    return Catalog(as_of=as_of, models=models, sources=sources, benchmarks=benchmarks, _alias=alias)
