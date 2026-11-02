"""Golden reproduction: the engine must reproduce independently computed
results on a frozen collector snapshot.

The snapshot is real usage, so it never lives in this repo. Point
TIER_DRIFT_GOLDEN_DIR at a directory holding

    snapshot/<host>.json   collector documents
    expected.json          values computed WITHOUT tier_drift (so a match is
                           a real check, not the engine agreeing with itself)

and this test runs; otherwise it is skipped.
"""

import datetime as dt
import glob
import json
import os
from pathlib import Path

import pytest

from tier_drift import aggregate, catalog, insights

GOLDEN = os.environ.get("TIER_DRIFT_GOLDEN_DIR")
pytestmark = pytest.mark.skipif(not GOLDEN, reason="set TIER_DRIFT_GOLDEN_DIR to run")


@pytest.fixture(scope="module")
def golden():
    root = Path(GOLDEN)
    docs = [
        json.loads(Path(p).read_text())
        for p in sorted(glob.glob(str(root / "snapshot" / "*.json")))
    ]
    # Bazel gives tests a private /tmp, so a snapshot under /tmp is invisible there.
    assert docs, f"no snapshot documents under {root} (under Bazel, keep it outside /tmp)"
    expected = json.loads((root / "expected.json").read_text())
    usage = aggregate.merge(docs)
    return usage, catalog.load(), expected


def test_turn_totals(golden):
    usage, _, exp = golden
    assert usage.total == exp["total"]
    for vendor, n in exp["vendors"].items():
        assert usage.vendor_turns(vendor) == n, vendor
    by_channel = {}
    for r in usage.rows:
        by_channel[r["channel"]] = by_channel.get(r["channel"], 0) + r["turns"]
    assert by_channel == exp["channels"]


def test_astra_tokens_and_list_costs(golden):
    usage, cat, exp = golden
    shape = [
        i
        for i in insights.context_shape(usage, cat, insights.Params())
        if i.models[0] == "gpt-6-astra"
    ]
    assert len(shape) == 1
    ev = shape[0].evidence
    tok = ev["tokens"]
    assert (tok["input"], tok["cached"], tok["output"]) == (
        exp["astra"]["input"],
        exp["astra"]["cached"],
        exp["astra"]["output"],
    )
    assert round(ev["cached_share"], 4) == exp["astra"]["cached_share"]
    costs = {"gpt-6-astra": ev["list_cost"], **ev["alternatives"]}
    assert {m: round(c) for m, c in costs.items()} == exp["astra"]["list_cost"]


def test_delegation_asymmetry(golden):
    usage, cat, exp = golden
    (mix,) = insights.tier_mix(usage, cat, insights.Params())
    shares = {v: round(s, 4) for v, s in mix.evidence["automated_low_tier_share"].items()}
    assert shares == exp["automated_low_tier_share"]


def test_adoption_lag(golden):
    usage, cat, exp = golden
    lags = {r["model"]: r["lag_days"] for r in insights.adoption(usage, cat)}
    for model, days in exp["adoption_lag_days"].items():
        assert lags[model] == days, model


def test_as_of_is_the_latest_use(golden):
    usage, _, _ = golden
    assert isinstance(usage.as_of, dt.date)
