"""Compute the decision table for every name you hold, have researched, or watch."""
from __future__ import annotations

import datetime as dt

from .. import db
from ..config import get_settings
from ..register import ledger
from ..risk import check as risk
from .engine import decide, put_idea


def run() -> dict:
    from ..api import phase2, prices  # late import: the API module owns the register queries

    trades, cfs = phase2._trades(), phase2._cashflows()
    book = ledger.build_book(trades, cfs)
    marks, _, _ = phase2._marks(book)
    pos = ledger.positions(book, marks)
    summ = ledger.summary(book)
    pv = sum(summ["cash"].values()) + sum(p["value"] or 0 for p in pos)
    held: dict[str, dict] = {}
    for p in pos:
        if p["asset"] == "stock":
            h = held.setdefault(p["ticker"], {"qty": 0.0, "value": 0.0})
            h["qty"] += p["qty"]
            h["value"] += p["value"] or 0
    reports = {d["id"]: d for d in db.list_docs("equity")}
    from sqlalchemy import select
    with db.session() as s_:
        funds = {f.ticker for f in s_.scalars(select(db.Fund)).all()}
    names = sorted(set(held) | set(reports) | set(get_settings().watchlist.symbols))
    limits = risk.merged_limits(db.get_doc("risk", "limits"))
    sig = db.latest_doc("signals") or {}
    regime = sig.get("regime")
    closes = prices.closes(names) if names else None
    base_ctx = phase2.book_context() if pv > 0 else None
    rows = []
    for t in names:
        px, below200 = None, None
        if closes is not None and t in closes and not closes[t].dropna().empty:
            h = closes[t].dropna()
            px = float(h.iloc[-1])
            below200 = bool(h.iloc[-1] < h.iloc[-200:].mean()) if len(h) >= 200 else None
        rep = reports.get(t)
        h = held.get(t, {"qty": 0.0, "value": 0.0})
        d = decide(t, report=rep, price=px, regime=regime, below200=below200, held_value=h["value"], held_qty=h["qty"],
                   portfolio_value=pv, limits=limits, is_fund=t in funds and t not in reports)
        ctx = phase2.risk_context({"ticker": t, "account": "T"}, base_ctx) if base_ctx else None
        if ctx and d["action"] in ("BUY", "ADD") and d.get("shares"):
            r = risk.check({"account": "T", "ticker": t, "asset": "stock", "side": "buy", "qty": d["shares"], "price": px}, ctx, limits)
            d["risk"] = {"verdict": r["verdict"], "rules": [x for x in r["rules"] if x["status"] != "PASS"]}
        idea = put_idea(rep, d["action"], regime, limits)
        if idea and ctx:
            r = risk.check({"account": "T", "ticker": t, "asset": "option", "side": "sell", "qty": 1, "price": idea["bid"],
                            "opt_kind": "put", "strike": idea["strike"], "expiry": idea["expiry"], "iv": idea.get("iv")}, ctx, limits)
            idea["risk"] = {"verdict": r["verdict"], "rules": [x for x in r["rules"] if x["status"] != "PASS"]}
        d["putIdea"] = idea
        rows.append(d)
    order = {"BUY": 0, "ADD": 1, "SELL": 2, "TRIM": 3, "HOLD": 4, "AVOID": 5, "NO VIEW": 6}
    rows.sort(key=lambda r: (order.get(r["action"], 9), r["ticker"]))
    today = dt.date.today().isoformat()
    return {"id": today, "asOf": today, "regime": regime, "playbook": sig.get("playbook"), "signalsAsOf": sig.get("asOf"),
            "portfolioValue": pv, "rows": rows,
            "note": "Research calls from written rules, for you to review. folio-desk never places orders."}
