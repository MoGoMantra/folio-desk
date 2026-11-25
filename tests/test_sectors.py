import numpy as np
import pandas as pd
import pytest

from folio_desk.data.base import UniverseMember
from folio_desk.sectors import drawdown, rotation
from tests.conftest import bars_from, walk


@pytest.fixture
def sector_world(dates):
    bars, members = {}, []
    for k, (key, gics, etf) in enumerate(rotation.SECTORS):
        bars[etf] = bars_from(walk(len(dates), 500 + k), dates, seed=k)
        for j in range(8):
            sym = f"{key.upper()}{j}"
            drift = 0.0015 if key == "ener" else 0.0002  # energy rallies through the window
            c = walk(len(dates), 1000 + 10 * k + j, drift, 0.015, 50)
            bars[sym] = bars_from(c, dates, vol0=2e6, seed=k * 10 + j)
            members.append(UniverseMember(symbol=sym, name=f"{gics} {j}", sector=gics))
    bars["SPY"] = bars_from(walk(len(dates), 7), dates)
    return bars, members


def test_rotation_document(sector_world):
    bars, members = sector_world
    doc = rotation.compute(bars, members)
    assert doc["status"] == "unvalidated"
    assert len(doc["sectors"]) == 11
    for s in doc["sectors"]:
        assert s["stage"] in ("Confirmed", "Losing", "Early", "Watch", "Neutral", "Stale watch")
    ener = next(s for s in doc["sectors"] if s["key"] == "ener")
    assert ener["rsEW"]["w12"] > 0


def test_base_rates_use_known_outcomes_only(sector_world):
    """Regression: base rates once counted the last 20 sessions (outcome unknown) as 'neither', so up + down
    summed to ~95% and every edge was overstated. They must sum to ~100%."""
    bars, members = sector_world
    bt = rotation.compute(bars, members)["backtest"]
    assert bt["baseUpPct"] + bt["baseDownPct"] == pytest.approx(100, abs=0.5)


def test_rotation_needs_all_etfs(sector_world):
    bars, members = sector_world
    bars = {k: v for k, v in bars.items() if k != "XLE"}
    with pytest.raises(ValueError, match="XLE"):
        rotation.compute(bars, members)


def test_drawdown_rows_and_flags(dates):
    idx = dates[-60:]
    flat = np.full(60, 100.0)
    falling = flat.copy()
    falling[-10:] = np.linspace(100, 78, 10)
    split = flat.copy()
    split[-5:] = 50.0  # one-day -50%: a split, not a drawdown
    bars = {"FLAT": bars_from(flat, idx), "FALL": bars_from(falling, idx), "SPLT": bars_from(split, idx)}
    mem = [UniverseMember(s, s, "Industrials") for s in bars]
    doc = drawdown.compute(bars, mem)
    syms = [r["sym"] for r in doc["rows"]]
    assert "FLAT" not in syms and "FALL" in syms
    fall = next(r for r in doc["rows"] if r["sym"] == "FALL")
    assert fall["dd"] == pytest.approx(-22, abs=0.01)
    assert "ca?" in next(r for r in doc["rows"] if r["sym"] == "SPLT")["flag"]
    assert doc["research"] == ["FALL"]
    assert isinstance(pd.Timestamp(doc["asOf"]), pd.Timestamp)
