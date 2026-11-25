import numpy as np

from folio_desk.signals import market


def test_compute_shape_and_bounds(market_bars):
    S = market.closes_from_bars(market_bars)
    doc = market.compute(S, watchlist=["AAPL", "JNJ"], theme=["NVDA", "AMD"], theme_name="AI")
    assert doc["regime"] in ("Risk-on", "Caution", "Risk-off", "Washout")
    assert 0 <= doc["riskScore"] <= 100
    assert doc["playbook"] == market.PLAYBOOK[doc["regime"]]
    ids = {s["id"] for s in doc["signals"]}
    assert {"BR1", "BR3", "LC1", "CR1", "VO1", "MA1"} <= ids
    assert "CR3" not in ids  # no bellwether configured
    assert [w["sym"] for w in doc["watchlist"]] == ["AAPL", "JNJ"]
    assert doc["bottomTotal"] == 10
    assert doc["status"] == "unvalidated"


def test_bellwether_and_theme_from_config(market_bars):
    S = market.closes_from_bars(market_bars)
    doc = market.compute(S, watchlist=[], theme=["NVDA"], theme_name="Chips", bellwether="AMD")
    cr3 = next(s for s in doc["signals"] if s["id"] == "CR3")
    assert "AMD" in cr3["name"]
    lc3 = next(s for s in doc["signals"] if s["id"] == "LC3")
    assert lc3["name"].startswith("Chips")


def test_crash_turns_regime_defensive(market_bars):
    crash = {k: v.copy() for k, v in market_bars.items()}
    n = len(crash["SPY"])
    fall = np.linspace(1, 0.70, 40)
    for s, df in crash.items():
        if s.startswith("^") or s in ("IEF", "XLU", "XLP", "DX-Y.NYB"):
            continue
        c = df["close"].to_numpy().copy()
        c[-40:] = c[-41] * fall
        crash[s] = df.assign(close=c)
    for s, f in (("^VIX", 2.8), ("^VIX3M", 1.6), ("^VVIX", 1.6)):
        c = crash[s]["close"].to_numpy().copy()
        c[-10:] *= f
        crash[s] = crash[s].assign(close=c)
    doc = market.compute(market.closes_from_bars(crash), watchlist=[], theme=[])
    assert doc["regime"] in ("Risk-off", "Washout")
    assert n > 0


def test_state_changes_and_manual_carry_forward(market_bars):
    S = market.closes_from_bars(market_bars)
    first = market.compute(S, watchlist=[], theme=[], manual={"B7": {"status": "green", "note": "guides held"}})
    assert next(c for c in first["bottom"] if c["id"] == "B7")["status"] == "green"
    prev = dict(first, regime="Washout")
    second = market.compute(S, watchlist=[], theme=[], prev=prev)
    assert next(c for c in second["bottom"] if c["id"] == "B7")["status"] == "green"  # carried forward
    assert any(c["id"] == "regime" for c in second["changes"])
    assert second["headlineChange"] is True


def test_yahoo_symbol_mapping():
    from folio_desk.data.yahoo import ysym
    assert ysym("BRK.B") == "BRK-B"
    assert ysym("DX-Y.NYB") == "DX-Y.NYB"
    assert ysym("^VIX") == "^VIX" and ysym("CL=F") == "CL=F"
