import datetime as dt

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from folio_desk import db
from folio_desk.decision.engine import decide, put_idea
from folio_desk.risk.check import DEFAULT_LIMITS

TODAY = dt.date(2026, 11, 20)


def report(price=100.0, fv=150.0, buy=110.0, acc=130.0, trim=170.0, flags=(), age_days=5, cands=None):
    return {"asOf": (TODAY - dt.timedelta(days=age_days)).isoformat(), "price": price, "problems": [],
            "signal": {"label": "BUY", "fv": fv, "buy": buy, "acc": acc, "trim": trim, "flags": list(flags)},
            "options": {"candidates": cands or []}}


def call(rep, price, **kw):
    args = dict(report=rep, price=price, regime="Risk-on", below200=False, held_value=0.0, held_qty=0.0,
                portfolio_value=100000, limits=DEFAULT_LIMITS, today=TODAY) | kw
    return decide("TEST", **args)


def test_buy_sized_by_limit_and_confidence():
    d = call(report(), 100)
    assert d["action"] == "BUY" and d["confidence"] == "High"
    assert d["size"] == pytest.approx(10000) and d["shares"] == 100


def test_accumulate_is_a_starter_and_flags_cut_confidence():
    d = call(report(flags=["DCF disagrees"]), 120)
    assert d["action"] == "BUY" and d["label"] == "ACCUMULATE" and d["confidence"] == "Medium"
    assert d["size"] == pytest.approx(10000 * 0.6 / 3, rel=1e-3)


def test_relabels_at_todays_price():
    assert call(report(), 175)["action"] == "AVOID"
    assert call(report(), 175, held_qty=10, held_value=1750)["action"] == "TRIM"
    assert call(report(), 230, held_qty=10, held_value=2300)["action"] == "SELL"


def test_risk_off_no_averaging_down_and_wait_above_buy():
    held = dict(held_qty=10, held_value=1000)
    assert call(report(), 100, regime="Risk-off", below200=True, **held)["action"] == "HOLD"
    assert call(report(), 120, regime="Risk-off")["action"] == "AVOID"    # ACCUMULATE zone: wait in Risk-off
    d = call(report(), 100, regime="Risk-off")                            # BUY zone: reduced size
    assert d["action"] == "BUY" and d["size"] == pytest.approx(5000)


def test_stale_or_missing_report_means_no_view():
    assert call(None, 100)["action"] == "NO VIEW"
    assert call(report(age_days=200), 100)["action"] == "NO VIEW"
    assert call(report(age_days=200), 100, held_qty=5, held_value=500)["action"] == "HOLD"


def test_already_full_size_holds():
    assert call(report(), 100, held_qty=100, held_value=10000)["action"] == "HOLD"


def test_put_idea_prefers_below_buy_and_skips_sells():
    c = [{"expiry": "2027-01-15", "strike": 125, "bid": 3, "annYield": 0.25, "dte": 56, "belowBuy": False},
         {"expiry": "2027-01-15", "strike": 105, "bid": 1.5, "annYield": 0.12, "dte": 56, "belowBuy": True}]
    idea = put_idea(report(cands=c), "BUY", "Risk-on", DEFAULT_LIMITS)
    assert idea["strike"] == 105
    assert put_idea(report(cands=c), "TRIM", "Risk-on", DEFAULT_LIMITS) is None


@pytest.fixture
def client(mem_db, monkeypatch):
    from folio_desk.api.app import app
    from folio_desk.config import Settings, set_settings
    s = Settings()
    s.watchlist.symbols = ["WWW"]
    set_settings(s)
    idx = pd.bdate_range("2025-06-02", "2026-11-20")
    monkeypatch.setattr("folio_desk.api.prices.closes",
                        lambda tickers, years=22: pd.DataFrame({t: np.linspace(90, 100, len(idx)) for t in tickers}, index=idx))
    monkeypatch.setattr("folio_desk.api.phase2.option_quotes", lambda lots: {})
    with TestClient(app) as c:
        yield c


def test_decisions_api_end_to_end(client):
    client.post("/api/register/cashflows", json={"date": "2025-06-02", "amount": 100000})
    rep = report(price=100)
    rep["asOf"] = dt.date.today().isoformat()
    db.put_doc("equity", "AAA", rep)
    from folio_desk.decision.run import run
    doc = run()
    by = {r["ticker"]: r for r in doc["rows"]}
    assert by["AAA"]["action"] == "BUY" and by["AAA"]["risk"]["verdict"] in ("PASS", "WARN")
    assert by["WWW"]["action"] == "NO VIEW"
    assert any("regime unknown" in i for i in by["AAA"]["issues"])
    assert doc["rows"][0]["ticker"] == "AAA"


def test_funds_are_judged_by_allocation():
    d = call(None, 100, held_qty=10, held_value=1000, is_fund=True)
    assert d["action"] == "HOLD" and d["fund"] and "allocation" in d["reasons"][0]


def test_review_requires_reasons_and_guards(client):
    from tests.test_equity import make_collect
    from folio_desk.equity import autolevers
    rep = autolevers.auto_report(make_collect(), today=dt.date(2026, 11, 20))
    db.put_doc("equity", "TEST", rep)
    m = rep["model"] | {"mult": [rep["model"]["mult"][0] - 1, rep["model"]["mult"][1] - 1, rep["model"]["mult"][2] - 1]}
    assert client.post("/api/equity/TEST/review", json={"model": m, "overrides": []}).status_code == 422
    over_cap = m | {"mult": [m["mult"][0], m["mult"][1] + 3, m["mult"][2] + 3]}  # base above the growth cap
    assert client.post("/api/equity/TEST/review", json={"model": over_cap, "overrides": [{"lever": "Exit P/E", "why": "x"}]}).status_code == 422
    bad = m | {"mult": [m["mult"][0], m["mult"][1], m["mult"][1] * 2]}
    assert client.post("/api/equity/TEST/review", json={"model": bad, "overrides": [{"lever": "Exit P/E", "why": "x"}]}).status_code == 422
    ok = client.post("/api/equity/TEST/review", json={"model": m, "overrides": [{"lever": "Exit P/E", "why": "peer set de-rated after earnings"}]})
    assert ok.status_code == 200 and db.get_doc("equity", "TEST")["mode"] == "reviewed"


def test_provisional_report_gives_no_call_and_no_put():
    rep = report(cands=[{"expiry": "2027-01-15", "strike": 105, "bid": 1.5, "annYield": 0.12, "dte": 56, "belowBuy": True}])
    rep["provisional"] = True
    assert call(rep, 100)["action"] == "NO VIEW"
    assert call(rep, 100, held_qty=5, held_value=500)["action"] == "HOLD"
    assert put_idea(rep, "HOLD", "Risk-on", DEFAULT_LIMITS) is None
