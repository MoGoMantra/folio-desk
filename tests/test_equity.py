import copy
import datetime as dt
import json

import httpx
import pytest

from folio_desk.data.base import DataError
from folio_desk.data.edgar import EdgarClient
from folio_desk.equity import autolevers, engine, facts, forces


def quarter_ends(n=12, last=dt.date(2026, 9, 30)):
    out, y, m = [], last.year, last.month
    for _ in range(n):
        out.append(dt.date(y, m, 30 if m in (6, 9) else 31).isoformat())
        m -= 3
        if m <= 0:
            m += 12
            y -= 1
    return out[::-1]


def make_collect():
    qs = []
    for i, e in enumerate(quarter_ends()):
        rev = 1000e6 * 1.03 ** i
        qs.append({"end": e, "revenue": rev, "netIncome": rev * (0.14 + 0.002 * i), "epsDiluted": rev * 0.15 / 100e6,
                   "dilutedShares": 100e6 * (1 - 0.002 * i), "ocf": rev * 0.2, "capex": rev * 0.05, "da": rev * 0.04,
                   "opIncome": rev * 0.2, "receivables": rev * 0.5, "inventory": rev * 0.3, "payables": rev * 0.2,
                   "cash": 2000e6, "stInvest": 500e6, "debtCurrent": 100e6, "debtLT": 1500e6})
    return {"ticker": "TEST", "collectedAt": "2026-11-20T00:00:00+00:00",
            "sec": {"name": "Test Corp", "fiscalYearEnd": "1231", "quarters": qs, "insiders": {}},
            "price": {"price": 60.0, "date": "2026-11-19", "beta5yMonthly": 1.1, "bigDays": []},
            "estimates": {"epsFY1": 7.2, "epsFY2": 8.1, "revFY1": 4.9e9, "revFY2": 5.5e9},
            "options": {"rows": [{"kind": "put", "expiry": "2027-01-15", "dte": 56, "strike": s, "bid": b}
                                 for s, b in ((40, 0.3), (45, 0.6), (50, 1.1), (55, 2.0), (60, 3.5))]},
            "ownPE": {"usable": True, "medianPE": 22.0},
            "peerSet": ["AAA", "BBB", "CCC", "DDD"],
            "peers": [{"ticker": t, "fwdPE": pe, "epsGrowthFY2": g} for t, pe, g in
                      (("AAA", 18, 0.10), ("BBB", 22, 0.12), ("CCC", 25, 0.15), ("DDD", 95, 0.2))]}


@pytest.fixture
def collect_doc():
    return make_collect()


def test_auto_levers_build_a_valid_model(collect_doc):
    rep = autolevers.auto_report(collect_doc, today=dt.date(2026, 11, 20))
    assert rep["problems"] == [], rep["problems"]
    m = rep["model"]
    assert m["years"][0] == "FY2026E" and m["valueYear"] == 2
    assert m["mult"][0] < m["mult"][1] <= m["mult"][2] <= m["mult"][1] * 1.3 + 0.5
    assert 0.09 <= m["coe"] <= 0.11
    levers = {r["lever"] for r in m["rules"]}
    assert {"Base sales", "Base growth g", "Margins", "Exit P/E", "Cost of equity", "DCF"} <= levers
    assert m["mult"][1] <= 22.0  # own median P/E cap
    assert rep["signal"]["label"] in ("BUY", "ACCUMULATE", "HOLD", "TRIM")
    assert rep["signal"]["fv"] > 0


def test_options_overlay_only_below_accumulate(collect_doc):
    rep = autolevers.auto_report(collect_doc, today=dt.date(2026, 11, 20))
    acc = rep["signal"]["acc"]
    assert all(c["strike"] <= acc for c in rep["options"]["candidates"])


def test_needs_history():
    bad = {"sec": {"quarters": [{"end": "2026-09-30", "revenue": 1.0, "netIncome": 0.1}]}}
    with pytest.raises(ValueError, match="8 quarters"):
        autolevers.build(bad)


def test_engine_label_thresholds(collect_doc):
    m, _ = autolevers.build(collect_doc, today=dt.date(2026, 11, 20))
    s = engine.signal(m, 1.0)
    assert s["label"] == "BUY"
    assert engine.signal(m, s["fv"])["label"] == "HOLD"
    assert engine.signal(m, s["trim"] * 1.01)["label"] == "TRIM"
    assert 0.15 <= s["mos"] <= 0.40


def test_validator_guards(collect_doc):
    m, _ = autolevers.build(collect_doc, today=dt.date(2026, 11, 20))
    bad = copy.deepcopy(m)
    bad["mult"][2] = bad["mult"][1] * 2
    bad["coe"] = 0.05
    probs = engine.validate({"ticker": "T", "asOf": "x", "price": 60, "model": bad})
    assert any("bull exit" in p for p in probs) and any("cost of equity" in p for p in probs)
    assert engine.validate({"ticker": "T", "asOf": "x", "price": 60, "model": m}, locked_peers=["ZZZ"])  # peer change w/o override


def test_forces_sizing(collect_doc):
    m, _ = autolevers.build(collect_doc, today=dt.date(2026, 11, 20))
    rep = {"model": m, "price": 60.0, "triggers": {"up": ["x"], "down": ["y"]}, "forces": {"items": [
        {"force": f"f{i}", "direction": d, "type": "demand", "evidence": "filed", "inBase": "none", "horizon": "6-18m",
         "source": "10-Q", "watch": {"metric": "rev", "where": "10-Q"}, "lever": {"lever": "growth", "delta": 0.02 if d == "tailwind" else -0.02}}
        for i, d in enumerate(["tailwind", "headwind", "tailwind", "headwind"])]}}
    calc, probs = forces.size(rep)
    assert probs == []
    assert calc["tailwindUsd"] > 0 > calc["headwindUsd"]


def test_xbrl_decumulates_ytd_into_q4():
    f = lambda s, e, v, form, filed: {"start": s, "end": e, "val": v, "form": form, "filed": filed}
    cf = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        f("2025-01-01", "2025-03-31", 100, "10-Q", "2025-05-01"),
        f("2025-01-01", "2025-06-30", 210, "10-Q", "2025-08-01"),
        f("2025-01-01", "2025-09-30", 330, "10-Q", "2025-11-01"),
        f("2025-01-01", "2025-12-31", 460, "10-K", "2026-02-15")]}}}}}
    q, used = facts.quarterly(cf, ["Revenues"])
    assert q == {"2025-03-31": 100, "2025-06-30": 110, "2025-09-30": 120, "2025-12-31": 130}
    assert used == ["Revenues"]


def test_edgar_requires_user_agent():
    with pytest.raises(DataError, match="name and email"):
        EdgarClient(user_agent="")


def test_edgar_sends_user_agent():
    seen = {}

    def handler(req):
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, content=json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}))
    ec = EdgarClient(user_agent="Jane Doe jane@example.com", transport=httpx.MockTransport(handler))
    assert ec.cik_for("aapl") == (320193, "Apple Inc.")
    assert seen["ua"] == "Jane Doe jane@example.com"


def test_growth_cap_is_peg_1_5_with_15x_floor():
    assert engine.growth_cap(0.04) == 15.0           # floor
    assert engine.growth_cap(0.20) == pytest.approx(30.0)


def test_compounder_without_peers_or_consensus_keeps_15x_floor():
    c = make_collect()
    c["estimates"] = {}
    c["peers"], c["peerSet"] = [], []
    c["ownPE"] = {"usable": False}
    m, _ = autolevers.build(c, today=dt.date(2026, 11, 20))
    assert m["mult"][1] >= 15.0
    assert engine.validate({"ticker": "T", "asOf": "x", "price": 60, "model": m}) == []


def test_fallback_multiple_raises_a_visible_flag():
    c = make_collect()
    c["estimates"] = {}
    for p in c["peers"]:
        p.pop("fwdPE")
        p["trailingPE"] = 20.0
    rep = autolevers.auto_report(c, today=dt.date(2026, 11, 20))
    assert any("provisional" in f for f in rep["signal"]["flags"])
