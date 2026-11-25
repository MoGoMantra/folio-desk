"""Portfolio performance from the register: daily valuation, time-weighted return (TWR), money-weighted
return (XIRR), drawdown, benchmark comparison and attribution by idea source and strategy.

Valuation per day = cash + shares x close + options x multiplier x mark. Free data has no option price
history, so past option marks use intrinsic value (a lower bound; it understates short-option liabilities
before expiry and long-option value). Today's marks can come from the live chain.

Modes
- "account": cash flows you logged (deposits / withdrawals) are the only external flows. Use this when you
  record deposits; it measures the whole account including idle cash.
- "positions": no cash flows logged. Every buy is treated as money in and every sale as money out, so the
  return measures the positions only.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from ..register.ledger import build_book, instrument_key, mult, signed_qty


def _intrinsic(kind: str, strike: float, spot: float) -> float:
    return max(0.0, strike - spot) if kind == "put" else max(0.0, spot - strike)


def daily_values(trades: list[dict], cashflows: list[dict], closes: pd.DataFrame, today_marks: dict[str, float] | None = None,
                 mode: str = "account") -> pd.DataFrame:
    """Return a frame indexed by session date with columns value, flow (external, + = money in)."""
    if not trades:
        return pd.DataFrame(columns=["value", "flow"])
    start = min([t["date"] for t in trades] + [c["date"] for c in cashflows])
    idx = closes.index[closes.index >= pd.Timestamp(start)]
    if len(idx) == 0:
        return pd.DataFrame(columns=["value", "flow"])
    closes = closes.ffill()
    t_by_date: dict[str, list[dict]] = {}
    for t in sorted(trades, key=lambda x: x["date"]):
        t_by_date.setdefault(t["date"], []).append(t)
    cf_by_date: dict[str, float] = {}
    for c in cashflows:
        cf_by_date[c["date"]] = cf_by_date.get(c["date"], 0.0) + float(c["amount"])
    pos: dict[str, dict] = {}
    cash = 0.0
    rows = []
    pending = sorted({*t_by_date, *cf_by_date})
    pi = 0
    for d in idx:
        ds = d.date().isoformat()
        flow = 0.0
        while pi < len(pending) and pending[pi] <= ds:  # apply everything dated on or before this session
            day = pending[pi]
            pi += 1
            if mode == "account":
                cash += cf_by_date.get(day, 0.0)
                flow += cf_by_date.get(day, 0.0)
            for t in t_by_date.get(day, []):
                k, m, q = instrument_key(t), mult(t), signed_qty(t)
                amt = -q * float(t["price"]) * m - float(t.get("fees") or 0)
                if mode == "account":
                    cash += amt
                else:
                    flow += -amt  # buys bring money in, sales take it out
                p = pos.setdefault(k, {"qty": 0.0, "t": t})
                p["qty"] += q
                if abs(p["qty"]) < 1e-9:
                    pos.pop(k)
        val = cash
        for k, p in pos.items():
            t = p["t"]
            if t.get("asset") == "option":
                last = d == idx[-1]
                spot = closes[t["ticker"]].get(d) if t["ticker"] in closes else None
                if last and today_marks and k in today_marks:
                    mk = today_marks[k]
                elif spot is not None and not math.isnan(spot):
                    mk = _intrinsic(t["opt_kind"], float(t["strike"]), float(spot))
                else:
                    mk = 0.0
                if t.get("expiry") and ds > t["expiry"]:
                    mk = 0.0
                val += p["qty"] * mult(t) * mk
            else:
                px = closes[t["ticker"]].get(d) if t["ticker"] in closes else None
                val += p["qty"] * (float(px) if px is not None and not math.isnan(px) else float(t["price"]))
        rows.append((d, val, flow))
    return pd.DataFrame(rows, columns=["date", "value", "flow"]).set_index("date")


def twr(v: pd.DataFrame) -> pd.Series:
    """Daily chained returns with flows at the end of the day: r = (V_t - F_t) / V_{t-1} - 1."""
    vals, flows = v["value"].to_numpy(), v["flow"].to_numpy()
    r = np.zeros(len(vals))
    for i in range(1, len(vals)):
        prev = vals[i - 1]
        r[i] = (vals[i] - flows[i]) / prev - 1 if prev > 0 else 0.0
    return pd.Series(np.cumprod(1 + r), index=v.index)


def xirr(flows: list[tuple[dt.date, float]]) -> float | None:
    """flows from the investor's view: deposits negative, withdrawals and the ending value positive."""
    if len(flows) < 2 or all(f >= 0 for _, f in flows) or all(f <= 0 for _, f in flows):
        return None
    t0 = flows[0][0]
    yrs = [((d - t0).days) / 365.25 for d, _ in flows]
    amt = [f for _, f in flows]
    f = lambda r: sum(a / (1 + r) ** y for a, y in zip(amt, yrs))
    lo, hi = -0.99, 10.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def report(trades: list[dict], cashflows: list[dict], closes: pd.DataFrame, benchmarks: list[str],
           today_marks: dict[str, float] | None = None) -> dict:
    mode = "account" if cashflows else "positions"
    v = daily_values(trades, cashflows, closes, today_marks, mode)
    if len(v) < 2:
        return {"mode": mode, "error": "not enough history yet: log trades (and deposits) first"}
    nav = twr(v)
    years = max((v.index[-1] - v.index[0]).days / 365.25, 1 / 365.25)
    total = float(nav.iloc[-1] - 1)
    ann = (1 + total) ** (1 / years) - 1 if years >= 1 else None
    dd = nav / nav.cummax() - 1
    daily = nav.pct_change().dropna()
    flows = [(d.date(), -float(f)) for d, f in v["flow"].items() if f]
    if mode == "positions":
        first = v.index[0]
        flows = [(first.date(), -float(v["value"].iloc[0]))] + [(d.date(), -float(f)) for d, f in v["flow"].iloc[1:].items() if f]
    elif v["value"].iloc[0] and not v["flow"].iloc[0]:
        flows = [(v.index[0].date(), -float(v["value"].iloc[0]))] + flows
    flows.append((v.index[-1].date(), float(v["value"].iloc[-1])))
    mwr = xirr(sorted(flows))
    bench = {}
    for b in benchmarks:
        if b in closes:
            s = closes[b].reindex(v.index).ffill().dropna()
            if len(s) > 1:
                bn = s / s.iloc[0]
                bench[b] = {"total": float(bn.iloc[-1] - 1), "series": [round(float(x), 5) for x in bn.reindex(v.index).ffill()]}
    b = build_book(trades, cashflows)
    from ..register.ledger import summary
    return {
        "mode": mode, "from": v.index[0].date().isoformat(), "to": v.index[-1].date().isoformat(),
        "value": float(v["value"].iloc[-1]), "twrTotal": total, "twrAnnual": ann, "mwrAnnual": mwr,
        "vol": float(daily.std() * math.sqrt(252)) if len(daily) > 20 else None, "maxDrawdown": float(dd.min()),
        "dates": [d.date().isoformat() for d in v.index], "nav": [round(float(x), 5) for x in nav],
        "values": [round(float(x), 2) for x in v["value"]], "benchmarks": bench,
        "attribution": {"byIdeaSource": summary(b)["byIdeaSource"], "byStrategy": summary(b)["byStrategy"]},
        "notes": ["Past option marks use intrinsic value (free data has no option price history)."] +
                 (["No deposits logged: returns measure the positions only (every buy counted as money in)."] if mode == "positions" else
                  ["Account view: idle cash counts, so returns lag a fully invested benchmark while cash sits uninvested."]),
    }
