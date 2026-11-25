"""API routes for the trading register, performance, optimization and risk management."""
from __future__ import annotations

import csv
import datetime as dt
import io

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from .. import db
from ..optimization import optimize as opt
from ..performance import returns as perf
from ..register import ledger
from ..risk import check as risk
from . import prices

router = APIRouter(prefix="/api")

TRADE_FIELDS = ["id", "date", "account", "ticker", "asset", "side", "qty", "price", "fees", "opt_kind", "strike", "expiry",
                "multiplier", "strategy", "idea_source", "thesis", "invalidation", "review_date", "note", "event", "link_id", "check_id"]


class TradeIn(BaseModel):
    date: str
    account: str = "T"
    ticker: str
    asset: str = "stock"
    side: str
    qty: float = Field(gt=0)
    price: float = Field(ge=0)
    fees: float = 0.0
    opt_kind: str = ""
    strike: float | None = None
    expiry: str = ""
    multiplier: float = 100.0
    strategy: str = ""
    idea_source: str = ""
    thesis: str = ""
    invalidation: str = ""
    review_date: str = ""
    note: str = ""
    check_id: str = ""

    @field_validator("ticker")
    @classmethod
    def up(cls, v):
        return v.strip().upper()

    def validated(self) -> dict:
        d = self.model_dump()
        dt.date.fromisoformat(d["date"])
        if d["side"] not in ("buy", "sell"):
            raise HTTPException(422, "side must be buy or sell")
        if d["asset"] not in ("stock", "option"):
            raise HTTPException(422, "asset must be stock or option")
        if d["asset"] == "option":
            if d["opt_kind"] not in ("put", "call") or not d["strike"] or not d["expiry"]:
                raise HTTPException(422, "options need opt_kind (put/call), strike and expiry")
            dt.date.fromisoformat(d["expiry"])
        else:
            d.update(opt_kind="", strike=None, expiry="", multiplier=1.0)
        return d


def _trades() -> list[dict]:
    with db.session() as s:
        return [{f: getattr(t, f) for f in TRADE_FIELDS} | {"created_at": t.created_at.isoformat() if t.created_at else ""}
                for t in s.scalars(select(db.Trade)).all()]


def _cashflows() -> list[dict]:
    with db.session() as s:
        return [{"id": c.id, "date": c.date, "account": c.account, "amount": c.amount, "note": c.note} for c in s.scalars(select(db.CashFlow)).all()]


def _save_trades(rows: list[dict]):
    with db.session() as s:
        for r in rows:
            s.add(db.Trade(**{k: r.get(k) for k in TRADE_FIELDS if k in r} | {"id": r.get("id") or ledger.new_id()}))


def option_quotes(lots: list[ledger.Lot]) -> dict[str, float]:
    """Live mid quotes for open option lots (free source; empty when unavailable)."""
    from ..data.yahoo import option_mids
    by_t: dict[str, list] = {}
    for lot in lots:
        if lot.asset == "option" and lot.expiry >= dt.date.today().isoformat():
            by_t.setdefault(lot.ticker, []).append((lot.expiry, lot.opt_kind, float(lot.strike)))
    out = {}
    for t, wanted in by_t.items():
        try:
            mids = option_mids(t, wanted)
        except Exception:
            continue
        for (e, k, s), v in mids.items():
            out[f"{t} {e} {'P' if k == 'put' else 'C'} {s:g}"] = v
    return out


def _marks(book: ledger.Book, live_options: bool = True) -> tuple[dict[str, float], pd.DataFrame, dict[str, str]]:
    """Latest closes for stocks; options at the live chain's mid when available, else intrinsic value.
    Returns (marks, closes, mark source per instrument key)."""
    tickers = sorted({lot.ticker for lot in book.lots})
    px = prices.closes(tickers) if tickers else pd.DataFrame()
    quotes = option_quotes(book.lots) if live_options else {}
    marks, source = {}, {}
    for lot in book.lots:
        if lot.asset == "option" and lot.key in quotes:
            marks[lot.key], source[lot.key] = quotes[lot.key], "chain mid"
            continue
        if lot.ticker not in px or px[lot.ticker].dropna().empty:
            continue
        spot = float(px[lot.ticker].dropna().iloc[-1])
        if lot.asset == "option":
            marks[lot.key], source[lot.key] = perf._intrinsic(lot.opt_kind, float(lot.strike), spot), "intrinsic"
        else:
            marks[lot.key], source[lot.key] = spot, "close"
    return marks, px, source


# ---------------------------------------------------------------- register

@router.get("/register/trades")
def list_trades():
    return sorted(_trades(), key=lambda t: (t["date"], t["created_at"]), reverse=True)


@router.post("/register/trades")
def add_trade(t: TradeIn):
    d = t.validated()
    d["id"] = ledger.new_id()
    d["event"] = "trade"
    if d["side"] == "sell":  # selling more than held opens a short: allowed for options, refused for shares
        b = ledger.build_book(_trades(), _cashflows())
        held = ledger.open_qty(b, d["account"], ledger.instrument_key(d))
        if d["asset"] == "stock" and held < d["qty"] - 1e-9:
            raise HTTPException(422, f"selling {d['qty']:g} {d['ticker']} but only {held:g} held in {d['account']} (short stock is not supported)")
    _save_trades([d])
    return {"id": d["id"]}


@router.delete("/register/trades/{tid}")
def delete_trade(tid: str):
    with db.session() as s:
        t = s.get(db.Trade, tid)
        if not t:
            raise HTTPException(404, "no such trade")
        linked = [x for x in s.scalars(select(db.Trade).where(db.Trade.link_id == t.link_id)).all()] if t.link_id else [t]
        for x in linked:
            s.delete(x)
    return {"deleted": len(linked)}


class OptionAction(BaseModel):
    action: str
    account: str
    key: str
    date: str
    close_price: float = 0.0
    new_expiry: str = ""
    new_strike: float | None = None
    open_price: float = 0.0


@router.post("/register/options/action")
def option_action(a: OptionAction):
    b = ledger.build_book(_trades(), _cashflows())
    try:
        if a.action == "expire":
            rows = ledger.expire(b, a.account, a.key, a.date)
        elif a.action == "assign":
            rows = ledger.assign(b, a.account, a.key, a.date)
        elif a.action == "roll":
            if not a.new_expiry or not a.new_strike:
                raise ValueError("a roll needs the new expiry and strike")
            rows = ledger.roll(b, a.account, a.key, a.date, a.close_price, a.new_expiry, a.new_strike, a.open_price)
        else:
            raise ValueError("action must be expire, assign or roll")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    _save_trades(rows)
    return {"added": len(rows)}


@router.get("/register/positions")
def register_positions():
    b = ledger.build_book(_trades(), _cashflows())
    marks, _, src = _marks(b)
    pos = ledger.positions(b, marks)
    for x in pos:
        x["markSource"] = src.get(x["key"])
    s = ledger.summary(b)
    value = sum(s["cash"].values()) + sum(p["value"] or 0 for p in pos)
    today = dt.date.today().isoformat()
    unchecked = [t["id"] for t in _trades() if t["event"] == "trade" and not t["check_id"]]
    reviews = [t for t in _trades() if t["review_date"] and t["review_date"] <= today and t["event"] == "trade"]
    return {"positions": pos, "summary": s, "portfolioValue": value, "shortPutNotional": sum(p.get("assignmentNotional", 0) for p in pos),
            "uncheckedTrades": len(unchecked), "reviewsDue": [{"id": t["id"], "ticker": t["ticker"], "review": t["review_date"], "thesis": t["thesis"]} for t in reviews],
            "note": "Shares at the last close. Options at the live chain's mid quote where available, otherwise intrinsic value (which ignores time value)."}


class CashFlowIn(BaseModel):
    date: str
    account: str = "T"
    amount: float
    note: str = ""


@router.get("/register/cashflows")
def cashflows():
    return sorted(_cashflows(), key=lambda c: c["date"], reverse=True)


@router.post("/register/cashflows")
def add_cashflow(c: CashFlowIn):
    dt.date.fromisoformat(c.date)
    with db.session() as s:
        cid = ledger.new_id()
        s.add(db.CashFlow(id=cid, **c.model_dump()))
    return {"id": cid}


@router.delete("/register/cashflows/{cid}")
def delete_cashflow(cid: str):
    with db.session() as s:
        c = s.get(db.CashFlow, cid)
        if c:
            s.delete(c)
    return {"ok": True}


@router.get("/register/export.csv")
def export_csv():
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=TRADE_FIELDS, extrasaction="ignore")
    w.writeheader()
    for t in sorted(_trades(), key=lambda x: x["date"]):
        w.writerow(t)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=folio-desk-trades.csv"})


# ---------------------------------------------------------------- performance

class PerfIn(BaseModel):
    benchmarks: list[str] = ["SPY", "QQQ"]


@router.post("/performance")
def performance(p: PerfIn):
    trades, cfs = _trades(), _cashflows()
    if not trades:
        raise HTTPException(404, "no trades in the register yet")
    tickers = sorted({t["ticker"] for t in trades} | set(p.benchmarks))
    px = prices.closes(tickers)
    b = ledger.build_book(trades, cfs)
    today_marks = option_quotes(b.lots)  # today's options at the chain mid; past days stay at intrinsic
    return perf.report(trades, cfs, px, p.benchmarks, today_marks)


# ---------------------------------------------------------------- optimization

class OptIn(BaseModel):
    tickers: list[str]
    method: str = "risk_parity"
    min_weight: float = 0.0
    max_weight: float = 0.4
    lookback_years: float = 5.0
    current: dict[str, float] | None = None
    total_value: float = 100000
    abs_band: float = 0.05
    rel_band: float = 0.25


@router.post("/optimize")
def optimize(o: OptIn):
    tks = [t.strip().upper() for t in o.tickers if t.strip()]
    if len(tks) < 2:
        raise HTTPException(422, "give at least two tickers")
    px = prices.closes(tks)
    missing = [t for t in tks if t not in px]
    if missing:
        raise HTTPException(422, f"no price history for {missing}")
    try:
        res = opt.optimize(px[tks], o.method, o.min_weight, o.max_weight, o.lookback_years)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if o.current:
        tot = sum(o.current.values()) or 1
        res["rebalance"] = opt.rebalance({k.upper(): v / tot for k, v in o.current.items()}, res["weights"], o.total_value, o.abs_band, o.rel_band)
    return res


# ---------------------------------------------------------------- risk

class Proposal(BaseModel):
    account: str = "T"
    ticker: str
    asset: str = "stock"
    side: str
    qty: float = Field(gt=0)
    price: float = Field(ge=0)
    opt_kind: str = ""
    strike: float | None = None
    expiry: str = ""
    iv: float | None = None
    earnings_date: str | None = None


@router.get("/risk/limits")
def get_limits():
    return risk.merged_limits(db.get_doc("risk", "limits"))


@router.put("/risk/limits")
def put_limits(limits: dict):
    unknown = set(limits) - set(risk.DEFAULT_LIMITS)
    if unknown:
        raise HTTPException(422, f"unknown limit keys: {sorted(unknown)}")
    db.put_doc("risk", "limits", limits)
    return risk.merged_limits(limits)


def book_context() -> dict:
    """The part of the risk context that does not depend on the proposed trade (computed once per run)."""
    b = ledger.build_book(_trades(), _cashflows())
    marks, _, _ = _marks(b)
    pos = ledger.positions(b, marks)
    s = ledger.summary(b)
    exposure: dict[str, float] = {}
    for x in pos:
        exposure[x["ticker"]] = exposure.get(x["ticker"], 0.0) + (x.get("assignmentNotional") or max(x["value"] or 0, 0))
    return {"portfolioValue": sum(s["cash"].values()) + sum(x["value"] or 0 for x in pos), "cash": s["cash"], "exposure": exposure,
            "positions": pos, "shortPutNotional": sum(x.get("assignmentNotional", 0) for x in pos)}


def risk_context(p: dict, base: dict | None = None) -> dict:
    base = base or book_context()
    t = p["ticker"]
    sig = db.latest_doc("signals") or {}
    rep = db.get_doc("equity", t)
    spot, below200 = None, None
    try:
        h = prices.closes([t])[t].dropna()
        spot = float(h.iloc[-1])
        below200 = bool(h.iloc[-1] < h.iloc[-200:].mean()) if len(h) >= 200 else None
    except Exception:
        pass
    report = None
    if rep and rep.get("signal"):
        report = {k: rep["signal"].get(k) for k in ("acc", "buy", "trim", "fv", "label")}
    return {k: v for k, v in base.items() if k != "positions"} | {
        "accountShortPutNotional": sum(x.get("assignmentNotional", 0) for x in base["positions"] if x["account"] == p.get("account", "T")),
        "regime": sig.get("regime"), "spot": spot, "below200": below200, "report": report, "earningsDate": p.get("earnings_date")}


@router.post("/risk/check")
def risk_check(p: Proposal):
    d = p.model_dump()
    d["ticker"] = d["ticker"].upper()
    if d["asset"] == "option" and (not d["strike"] or not d["expiry"] or d["opt_kind"] not in ("put", "call")):
        raise HTTPException(422, "options need opt_kind, strike and expiry")
    res = risk.check(d, risk_context(d), db.get_doc("risk", "limits"))
    cid = ledger.new_id()
    with db.session() as s:
        s.add(db.RiskCheck(id=cid, verdict=res["verdict"], fingerprint=res["fingerprint"], proposal=d, result=res))
    return {"id": cid, **res}


@router.get("/risk/checks")
def risk_checks(limit: int = 50):
    with db.session() as s:
        rows = s.scalars(select(db.RiskCheck).order_by(db.RiskCheck.created_at.desc()).limit(limit)).all()
        return [{"id": r.id, "createdAt": r.created_at.isoformat(), "verdict": r.verdict, "fingerprint": r.fingerprint[:12],
                 "proposal": r.proposal} for r in rows]
