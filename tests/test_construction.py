import numpy as np
import pandas as pd
import pytest

from folio_desk.construction import portfolio as pf


@pytest.fixture
def prices():
    idx = pd.bdate_range("2015-01-01", "2024-12-31")
    t = np.asarray((idx - idx[0]).days) / 365.25
    return pd.DataFrame({"AAA": 100 * 1.10 ** t, "BBB": 100 * 1.02 ** t, "SPY": 100 * 1.08 ** t}, index=idx)


def test_backtest_matches_closed_form(prices):
    bt = pf.backtest({"AAA": 100}, prices, rebal="N")
    st = pf.stats(bt)
    assert st["cagr"] == pytest.approx(0.10, abs=0.002)
    assert st["mdd"] == pytest.approx(0, abs=1e-9)


def test_rebalanced_mix_between_parts(prices):
    st = pf.stats(pf.backtest({"AAA": 50, "BBB": 50}, prices, rebal="A"))
    assert 0.02 < st["cagr"] < 0.10


def test_missing_ticker_reported(prices):
    assert pf.backtest({"ZZZ": 100}, prices) == {"missing": ["ZZZ"]}


def test_contributions_counted(prices):
    bt = pf.backtest({"BBB": 100}, prices, init=1000, contrib_monthly=100)
    assert bt["contrib"][-1] == pytest.approx(1000 + 100 * (len(bt["dates"]) - 2))


def test_placement_flags_wash_sale_pairs_and_tax_drag():
    funds = {f["ticker"]: f for f in pf.default_funds()}
    rows = [{"t": "VOO", "a": "T", "w": 50}, {"t": "IVV", "a": "I", "w": 30}, {"t": "BND", "a": "T", "w": 20}]
    checks = pf.placement_checks(rows, funds, {"T": 70000, "I": 30000, "R": 0})
    text = " ".join(c["text"] for c in checks)
    assert "wash sale" in text and "BND in Taxable" in text


def test_presets_reference_known_funds():
    known = {f["ticker"] for f in pf.default_funds()}
    for name, rows in pf.presets().items():
        assert sum(r[2] for r in rows) == pytest.approx(100), name
        assert {r[0] for r in rows} <= known, name
