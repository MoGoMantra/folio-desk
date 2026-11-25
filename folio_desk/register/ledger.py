"""Trading register maths: FIFO lots (long and short), realized P&L, open positions, cash per account,
short-put assignment exposure, and the option life-cycle (expire, assign / exercise, roll).

Pure functions over plain dicts (one dict per trade / cash flow) so they are testable without a database.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from dataclasses import dataclass, field


def instrument_key(t: dict) -> str:
    if t.get("asset") == "option":
        return f"{t['ticker']} {t['expiry']} {'P' if t['opt_kind'] == 'put' else 'C'} {float(t['strike']):g}"
    return t["ticker"]


def mult(t: dict) -> float:
    return float(t.get("multiplier") or 100.0) if t.get("asset") == "option" else 1.0


def signed_qty(t: dict) -> float:
    return float(t["qty"]) if t["side"] == "buy" else -float(t["qty"])


def new_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class Lot:
    trade_id: str
    account: str
    key: str
    ticker: str
    asset: str
    open_date: str
    qty: float           # signed: + long, - short
    price: float
    mult: float
    strategy: str = ""
    idea_source: str = ""
    opt_kind: str = ""
    strike: float | None = None
    expiry: str = ""


@dataclass
class Book:
    lots: list[Lot] = field(default_factory=list)
    realized: list[dict] = field(default_factory=list)
    cash: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    fees: float = 0.0
    warnings: list[str] = field(default_factory=list)


def build_book(trades: list[dict], cashflows: list[dict] | None = None, until: str | None = None) -> Book:
    """Replay trades and cash flows in date order (up to and including `until`)."""
    b = Book()
    for cf in sorted(cashflows or [], key=lambda c: c["date"]):
        if until and cf["date"] > until:
            continue
        b.cash[cf["account"]] += float(cf["amount"])
    order = sorted(trades, key=lambda t: (t["date"], str(t.get("created_at") or ""), t["id"]))
    for t in order:
        if until and t["date"] > until:
            continue
        key, m, q, px = instrument_key(t), mult(t), signed_qty(t), float(t["price"])
        fee = float(t.get("fees") or 0)
        b.cash[t["account"]] += -q * px * m - fee
        b.fees += fee
        remaining = q
        for lot in [x for x in b.lots if x.key == key and x.account == t["account"]]:
            if remaining == 0 or (lot.qty > 0) == (remaining > 0):
                continue
            close = min(abs(lot.qty), abs(remaining))
            sign = 1 if lot.qty > 0 else -1          # long lots profit when the close price is higher
            pnl = (px - lot.price) * close * sign * m
            b.realized.append({"key": key, "ticker": lot.ticker, "asset": lot.asset, "account": lot.account,
                               "openDate": lot.open_date, "closeDate": t["date"], "qty": close * sign,
                               "openPrice": lot.price, "closePrice": px, "pnl": pnl,
                               "days": (dt.date.fromisoformat(t["date"]) - dt.date.fromisoformat(lot.open_date)).days,
                               "strategy": lot.strategy, "ideaSource": lot.idea_source, "event": t.get("event", "trade")})
            lot.qty -= close * sign
            remaining += close * sign
        b.lots = [x for x in b.lots if abs(x.qty) > 1e-9]
        if abs(remaining) > 1e-9:
            if t.get("event") in ("expire", "assign", "exercise"):
                b.warnings.append(f"{t['date']} {key}: {t['event']} for more contracts than were open")
            b.lots.append(Lot(trade_id=t["id"], account=t["account"], key=key, ticker=t["ticker"], asset=t.get("asset", "stock"),
                              open_date=t["date"], qty=remaining, price=px, mult=m, strategy=t.get("strategy", ""),
                              idea_source=t.get("idea_source", ""), opt_kind=t.get("opt_kind", ""),
                              strike=t.get("strike"), expiry=t.get("expiry", "")))
    return b


def positions(b: Book, marks: dict[str, float] | None = None) -> list[dict]:
    """Aggregate open lots per account + instrument. marks: {instrument key: price per share/contract-share}."""
    marks = marks or {}
    agg: dict[tuple, dict] = {}
    for lot in b.lots:
        k = (lot.account, lot.key)
        p = agg.setdefault(k, {"account": lot.account, "key": lot.key, "ticker": lot.ticker, "asset": lot.asset, "qty": 0.0,
                               "cost": 0.0, "mult": lot.mult, "optKind": lot.opt_kind, "strike": lot.strike, "expiry": lot.expiry,
                               "strategy": lot.strategy, "ideaSource": lot.idea_source, "opened": lot.open_date})
        p["qty"] += lot.qty
        p["cost"] += lot.qty * lot.price * lot.mult
        p["opened"] = min(p["opened"], lot.open_date)
    out = []
    for p in agg.values():
        p["avgPrice"] = p["cost"] / (p["qty"] * p["mult"]) if p["qty"] else None
        mk = marks.get(p["key"])
        p["mark"] = mk
        p["value"] = p["qty"] * p["mult"] * mk if mk is not None else None
        p["unrealized"] = p["value"] - p["cost"] if mk is not None else None
        if p["asset"] == "option" and p["optKind"] == "put" and p["qty"] < 0:
            p["assignmentNotional"] = -p["qty"] * p["mult"] * float(p["strike"])
        out.append(p)
    return sorted(out, key=lambda x: (x["account"], x["ticker"], x["key"]))


def summary(b: Book) -> dict:
    by = lambda field_: _group(b.realized, field_)
    return {"realizedTotal": sum(r["pnl"] for r in b.realized), "fees": b.fees,
            "byStrategy": by("strategy"), "byIdeaSource": by("ideaSource"), "byTicker": by("ticker"),
            "cash": dict(b.cash), "warnings": b.warnings}


def _group(rows, k):
    g: dict[str, dict] = {}
    for r in rows:
        x = g.setdefault(r.get(k) or "untagged", {"pnl": 0.0, "n": 0, "wins": 0})
        x["pnl"] += r["pnl"]
        x["n"] += 1
        x["wins"] += r["pnl"] > 0
    return g


# ---------------------------------------------------------------- option life-cycle

def _option_from_key(b: Book, account: str, key: str) -> Lot:
    lots = [x for x in b.lots if x.key == key and x.account == account]
    if not lots:
        raise ValueError(f"no open position {key} in account {account}")
    return lots[0]


def open_qty(b: Book, account: str, key: str) -> float:
    return sum(x.qty for x in b.lots if x.key == key and x.account == account)


def expire(b: Book, account: str, key: str, date: str) -> list[dict]:
    lot = _option_from_key(b, account, key)
    q = open_qty(b, account, key)
    return [_opt_trade(lot, account, date, "sell" if q > 0 else "buy", abs(q), 0.0, "expire", "Expired worthless")]


def assign(b: Book, account: str, key: str, date: str) -> list[dict]:
    """Short option assigned, or long option exercised: close the option at 0 and trade the shares at the strike."""
    lot = _option_from_key(b, account, key)
    q = open_qty(b, account, key)
    if lot.asset != "option" or lot.strike is None:
        raise ValueError("not an option position")
    link = new_id()
    event = "assign" if q < 0 else "exercise"
    close = _opt_trade(lot, account, date, "sell" if q > 0 else "buy", abs(q), 0.0, event, f"{event.title()}ed at {lot.strike:g}", link)
    shares = abs(q) * lot.mult
    # short put / long call -> buy shares; short call / long put -> sell shares
    buy = (lot.opt_kind == "put" and q < 0) or (lot.opt_kind == "call" and q > 0)
    stock = {"id": new_id(), "date": date, "account": account, "ticker": lot.ticker, "asset": "stock",
             "side": "buy" if buy else "sell", "qty": shares, "price": float(lot.strike), "fees": 0.0, "opt_kind": "",
             "strike": None, "expiry": "", "multiplier": 1.0, "strategy": "assigned stock" if q < 0 else "exercised stock",
             "idea_source": lot.idea_source, "event": event, "link_id": link, "note": f"From {key}"}
    return [close, stock]


def roll(b: Book, account: str, key: str, date: str, close_price: float, new_expiry: str, new_strike: float,
         open_price: float, qty: float | None = None) -> list[dict]:
    lot = _option_from_key(b, account, key)
    q = open_qty(b, account, key)
    n = abs(qty) if qty else abs(q)
    link = new_id()
    close = _opt_trade(lot, account, date, "sell" if q > 0 else "buy", n, close_price, "roll", "Rolled out", link)
    opened = _opt_trade(lot, account, date, "buy" if q > 0 else "sell", n, open_price, "roll", f"Rolled from {key}", link)
    opened.update(expiry=new_expiry, strike=float(new_strike), id=new_id())
    return [close, opened]


def _opt_trade(lot: Lot, account, date, side, qty, price, event, note, link=""):
    return {"id": new_id(), "date": date, "account": account, "ticker": lot.ticker, "asset": "option", "side": side,
            "qty": qty, "price": price, "fees": 0.0, "opt_kind": lot.opt_kind, "strike": lot.strike, "expiry": lot.expiry,
            "multiplier": lot.mult, "strategy": lot.strategy, "idea_source": lot.idea_source, "event": event,
            "link_id": link, "note": note}
