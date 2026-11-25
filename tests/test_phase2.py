import datetime as dt

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from folio_desk import db
from folio_desk.optimization import optimize as opt
from folio_desk.performance import returns as perf
from folio_desk.register import ledger
from folio_desk.risk import check as risk


def T(date, ticker, side, qty, price, **kw):
    base = {"id": ledger.new_id(), "date": date, "account": "T", "ticker": ticker, "asset": "stock", "side": side, "qty": qty,
            "price": price, "fees": 0.0, "opt_kind": "", "strike": None, "expiry": "", "multiplier": 1.0, "strategy": "",
            "idea_source": "", "event": "trade"}
    if kw.get("asset") == "option":
        base["multiplier"] = 100.0
    return base | kw


# ---------------------------------------------------------------- ledger

def test_fifo_realized_pnl_and_cash():
    trades = [T("2026-01-02", "AAA", "buy", 10, 100), T("2026-02-02", "AAA", "buy", 10, 120), T("2026-03-02", "AAA", "sell", 15, 130)]
    b = ledger.build_book(trades, [{"date": "2026-01-01", "account": "T", "amount": 5000}])
    assert sum(r["pnl"] for r in b.realized) == pytest.approx(10 * 30 + 5 * 10)
    pos = ledger.positions(b, {"AAA": 140})
    assert pos[0]["qty"] == 5 and pos[0]["avgPrice"] == pytest.approx(120)
    assert b.cash["T"] == pytest.approx(5000 - 1000 - 1200 + 1950)


def test_short_put_expiry_keeps_premium():
    put = T("2026-01-05", "BBB", "sell", 2, 3.0, asset="option", opt_kind="put", strike=50, expiry="2026-02-20", strategy="cash-secured put")
    b = ledger.build_book([put])
    key = ledger.instrument_key(put)
    assert ledger.positions(b)[0]["assignmentNotional"] == 2 * 100 * 50
    rows = ledger.expire(b, "T", key, "2026-02-20")
    b2 = ledger.build_book([put, *rows])
    assert b2.lots == []
    assert b2.realized[0]["pnl"] == pytest.approx(600)


def test_short_put_assignment_creates_shares_at_strike():
    put = T("2026-01-05", "BBB", "sell", 1, 2.5, asset="option", opt_kind="put", strike=40, expiry="2026-02-20")
    b = ledger.build_book([put])
    rows = ledger.assign(b, "T", ledger.instrument_key(put), "2026-02-20")
    assert {r["asset"] for r in rows} == {"option", "stock"}
    stock = next(r for r in rows if r["asset"] == "stock")
    assert stock["side"] == "buy" and stock["qty"] == 100 and stock["price"] == 40
    assert rows[0]["link_id"] == rows[1]["link_id"]
    b2 = ledger.build_book([put, *rows])
    assert ledger.positions(b2)[0]["key"] == "BBB" and b2.realized[0]["pnl"] == pytest.approx(250)


def test_roll_closes_and_reopens():
    call = T("2026-01-05", "CCC", "sell", 1, 1.5, asset="option", opt_kind="call", strike=60, expiry="2026-02-20", strategy="covered call")
    b = ledger.build_book([call])
    rows = ledger.roll(b, "T", ledger.instrument_key(call), "2026-02-10", 2.0, "2026-03-20", 62, 2.4)
    b2 = ledger.build_book([call, *rows])
    assert b2.realized[0]["pnl"] == pytest.approx(-50)
    p = ledger.positions(b2)[0]
    assert p["strike"] == 62 and p["expiry"] == "2026-03-20" and p["qty"] == -1


# ---------------------------------------------------------------- performance

@pytest.fixture
def closes():
    idx = pd.bdate_range("2025-01-02", "2025-12-31")
    t = np.asarray((idx - idx[0]).days) / 365.25
    return pd.DataFrame({"AAA": 100 * 1.20 ** t, "SPY": 100 * 1.10 ** t}, index=idx)


def test_twr_matches_the_stock_with_no_cash_drag(closes):
    trades = [T("2025-01-02", "AAA", "buy", 100, 100)]
    rep = perf.report(trades, [], closes, ["SPY"])
    assert rep["mode"] == "positions"
    assert rep["twrTotal"] == pytest.approx(closes["AAA"].iloc[-1] / 100 - 1, rel=1e-3)
    assert rep["benchmarks"]["SPY"]["total"] == pytest.approx(closes["SPY"].iloc[-1] / 100 - 1, rel=1e-3)


def test_twr_ignores_deposit_timing_but_mwr_does_not(closes):
    cfs = [{"date": "2025-01-02", "account": "T", "amount": 10000}, {"date": "2025-07-01", "account": "T", "amount": 10000}]
    trades = [T("2025-01-02", "AAA", "buy", 100, 100)]
    second = closes.index[closes.index >= "2025-07-01"][0]
    trades.append(T(second.date().isoformat(), "AAA", "buy", 10000 / closes.loc[second, "AAA"], float(closes.loc[second, "AAA"])))
    rep = perf.report(trades, cfs, closes, [])
    assert rep["mode"] == "account"
    assert rep["twrTotal"] == pytest.approx(closes["AAA"].iloc[-1] / 100 - 1, rel=2e-3)
    assert rep["mwrAnnual"] is not None and 0.15 < rep["mwrAnnual"] < 0.25


def test_xirr_simple():
    r = perf.xirr([(dt.date(2025, 1, 1), -100), (dt.date(2026, 1, 1), 110)])
    assert r == pytest.approx(0.10, abs=1e-3)


# ---------------------------------------------------------------- optimization

@pytest.fixture
def three_assets():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2020-01-01", periods=1000)
    vols = np.array([0.30, 0.15, 0.05]) / np.sqrt(252)
    r = rng.normal(0.0003, vols, (1000, 3))
    return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=["HIGH", "MID", "LOW"])


def test_risk_parity_equalises_risk(three_assets):
    res = opt.optimize(three_assets, "risk_parity")
    assert sum(res["weights"].values()) == pytest.approx(1)
    assert max(res["riskShare"].values()) - min(res["riskShare"].values()) < 0.02
    assert res["weights"]["LOW"] > res["weights"]["MID"] > res["weights"]["HIGH"]


def test_caps_are_respected(three_assets):
    res = opt.optimize(three_assets, "min_variance", max_w=0.5)
    assert max(res["weights"].values()) <= 0.5 + 1e-6
    with pytest.raises(ValueError, match="impossible"):
        opt.optimize(three_assets, "min_variance", max_w=0.2)


def test_rebalance_bands():
    r = opt.rebalance({"A": 0.66, "B": 0.30, "C": 0.04}, {"A": 0.60, "B": 0.30, "C": 0.10}, 100000)
    out = {x["ticker"] for x in r["rows"] if x["outside"]}
    assert out == {"A", "C"}  # A drifts 6pts (>5); C drifts 6pts on a 10% target (>2.5)
    assert next(t for t in r["trades"] if t["ticker"] == "C")["side"] == "buy"


# ---------------------------------------------------------------- risk

CTX = {"portfolioValue": 100000, "cash": {"T": 60000}, "exposure": {"MU": 5000}, "shortPutNotional": 10000,
       "accountShortPutNotional": 10000, "regime": "Risk-on", "spot": 100, "below200": False,
       "report": {"acc": 90, "buy": 80, "trim": 130, "label": "HOLD"}, "earningsDate": None}
PUT = {"account": "T", "ticker": "MU", "asset": "option", "side": "sell", "qty": 1, "price": 2.0, "opt_kind": "put",
       "strike": 85, "expiry": (dt.date.today() + dt.timedelta(days=45)).isoformat(), "iv": 0.45}


def test_put_passes_in_risk_on_and_blocks_in_risk_off():
    ok = risk.check(PUT, CTX | {"exposure": {"MU": 1000}})  # 1,000 + 8,500 notional = 9.5% < 10%
    assert ok["verdict"] == "WARN"  # earnings date unknown
    assert all(r["status"] != "BLOCK" for r in ok["rules"])
    off = risk.check(PUT, CTX | {"regime": "Risk-off", "exposure": {"MU": 1000}})  # limit halves to 5%
    assert off["verdict"] == "BLOCK"
    assert any(r["id"] == "R1" and r["status"] == "BLOCK" for r in off["rules"])


def test_strike_above_accumulate_blocks_and_earnings_rule():
    high = PUT | {"strike": 95}
    res = risk.check(high, CTX | {"earningsDate": (dt.date.today() + dt.timedelta(days=10)).isoformat()})
    ids = {r["id"]: r["status"] for r in res["rules"]}
    assert ids["R5"] == "BLOCK" and ids["R6"] == "BLOCK"


def test_cluster_limit_and_fingerprint_stability():
    lim = {"clusters": {"AI capex": ["MU", "AMD"]}, "maxClusterPct": 10}
    a = risk.check(PUT, CTX | {"exposure": {"MU": 5000, "AMD": 4000}}, lim)
    assert any(r["id"] == "R2" and r["status"] == "BLOCK" for r in a["rules"])
    b = risk.check(PUT, CTX | {"exposure": {"MU": 5000, "AMD": 4000}}, lim)
    assert a["fingerprint"] == b["fingerprint"]


def test_cash_secured_rule():
    res = risk.check(PUT | {"qty": 6}, CTX)
    assert any(r["id"] == "R7" and r["status"] == "BLOCK" for r in res["rules"])


def test_put_delta_reasonable():
    assert 0.2 < risk.put_delta(100, 95, 45, 0.40) < 0.4
    assert risk.put_delta(100, 70, 45, 0.30) < 0.05


# ---------------------------------------------------------------- API

@pytest.fixture
def client(mem_db, monkeypatch):
    from folio_desk.api.app import app
    idx = pd.bdate_range("2025-06-02", "2026-11-20")

    def fake_closes(tickers, years=22):
        return pd.DataFrame({t: np.linspace(90, 110, len(idx)) for t in tickers}, index=idx)
    monkeypatch.setattr("folio_desk.api.prices.closes", fake_closes)
    monkeypatch.setattr("folio_desk.api.phase2.option_quotes", lambda lots: {})  # keep tests offline
    with TestClient(app) as c:
        yield c


def test_register_api_flow(client):
    client.post("/api/register/cashflows", json={"date": "2025-06-02", "amount": 50000})
    r = client.post("/api/register/trades", json={"date": "2025-06-02", "ticker": "aaa", "side": "buy", "qty": 100, "price": 90,
                                                  "idea_source": "equity", "thesis": "cheap vs FV", "review_date": "2025-09-01"})
    assert r.status_code == 200
    assert client.post("/api/register/trades", json={"date": "2025-06-03", "ticker": "AAA", "side": "sell", "qty": 500, "price": 91}).status_code == 422
    client.post("/api/register/trades", json={"date": "2025-06-03", "ticker": "AAA", "asset": "option", "side": "sell", "qty": 1, "price": 2,
                                              "opt_kind": "call", "strike": 100, "expiry": "2025-07-18", "strategy": "covered call"})
    pos = client.get("/api/register/positions").json()
    assert {p["key"] for p in pos["positions"]} == {"AAA", "AAA 2025-07-18 C 100"}
    assert pos["uncheckedTrades"] == 2 and pos["reviewsDue"][0]["ticker"] == "AAA"
    act = client.post("/api/register/options/action", json={"action": "expire", "account": "T", "key": "AAA 2025-07-18 C 100", "date": "2025-07-18"})
    assert act.json()["added"] == 1
    pos = client.get("/api/register/positions").json()
    assert pos["summary"]["byStrategy"]["covered call"]["pnl"] == pytest.approx(200)
    assert "AAA" in client.get("/api/register/export.csv").text
    perf_ = client.post("/api/performance", json={"benchmarks": ["SPY"]}).json()
    assert perf_["mode"] == "account" and "SPY" in perf_["benchmarks"]


def test_risk_api_records_checks(client):
    client.post("/api/register/cashflows", json={"date": "2025-06-02", "amount": 100000})
    client.put("/api/risk/limits", json={"maxPositionPct": 5})
    assert client.put("/api/risk/limits", json={"nonsense": 1}).status_code == 422
    r = client.post("/api/risk/check", json={"ticker": "ZZZ", "side": "buy", "qty": 100, "price": 100}).json()
    assert r["verdict"] == "BLOCK" and any(x["id"] == "R1" for x in r["rules"])  # $10k = 10% > 5%
    assert client.get("/api/risk/checks").json()[0]["id"] == r["id"]
    assert db.latest_doc("risk") is not None


def test_optimize_api(client):
    r = client.post("/api/optimize", json={"tickers": ["AAA", "BBB"], "method": "min_variance", "max_weight": 0.8,
                                           "current": {"AAA": 70, "BBB": 30}}).json()
    assert "weights" in r and "rebalance" in r


def test_missing_regime_is_flagged_not_assumed_silently():
    res = risk.check(PUT, CTX | {"regime": None, "exposure": {"MU": 1000}})
    assert any(r["id"] == "R0" and r["status"] == "WARN" for r in res["rules"])
