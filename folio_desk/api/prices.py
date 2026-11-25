"""Daily price cache for portfolio work: one document per ticker in collection "prices", refreshed when the last
stored session is older than the last weekday. Proxy codes splice older history before a fund's inception:
a ticker (use that fund's returns), CASH (BIL returns), SYN_NTSX (0.9 x IVV + 0.6 x (IEF - cash) - fee)."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from .. import data as datasrc
from .. import db


def _stale(doc: dict | None) -> bool:
    if not doc or not doc.get("dates"):
        return True
    last = dt.date.fromisoformat(doc["dates"][-1])
    today = dt.date.today()
    target = today - dt.timedelta(days={0: 3, 6: 2}.get(today.weekday(), 1))
    return last < target


def closes(tickers: list[str], years: int = 22) -> pd.DataFrame:
    need, frames = [], {}
    for t in dict.fromkeys(tickers):
        d = db.get_doc("prices", t)
        if _stale(d):
            need.append(t)
        else:
            frames[t] = pd.Series(d["close"], index=pd.to_datetime(d["dates"]))
    if need:
        bars = datasrc.daily_bars(need, period_days=int(years * 365.25))
        for t, df in bars.items():
            s = df["close"].dropna()
            db.put_doc("prices", t, {"dates": [x.date().isoformat() for x in s.index], "close": [round(float(v), 6) for v in s]})
            frames[t] = s
    return pd.DataFrame(frames).sort_index()


def extended(funds: dict[str, dict], tickers: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Closes with proxy history spliced in before each fund's own start. Returns (prices, notes)."""
    extra = set()
    for t in tickers:
        p = (funds.get(t) or {}).get("proxy") or ""
        if p == "CASH":
            extra.add("BIL")
        elif p.startswith("SYN"):
            extra |= {"IVV", "IEF", "BIL"}
        elif p:
            extra.add(p)
    px = closes(list(tickers) + sorted(extra))
    R = px.pct_change(fill_method=None)
    out, notes = {}, []
    for t in tickers:
        if t not in px:
            continue
        own = px[t]
        first = own.first_valid_index()
        if first is None:
            continue
        f = funds.get(t) or {}
        p = f.get("proxy") or ""
        pr = None
        if p == "CASH" and "BIL" in R:
            pr = R["BIL"]
        elif p.startswith("SYN") and {"IVV", "IEF", "BIL"} <= set(R):
            pr = 0.9 * R["IVV"] + 0.6 * (R["IEF"] - R["BIL"].fillna(0)) - (f.get("fee", 0) / 100 / 252)
        elif p and p in R:
            pr = R[p]
        r = own.pct_change(fill_method=None)
        if pr is not None:
            pre = pr[pr.index <= first].dropna()
            if len(pre) > 1:
                r = r.copy()
                r.loc[pre.index[1:]] = pre.iloc[1:]
                notes.append(f"{t} before {first.date()} uses {p} history")
                first = pre.index[0]
        r = r[r.index >= first].fillna(0)
        r.iloc[0] = 0
        out[t] = (1 + r).cumprod() * 100
    return pd.DataFrame(out).sort_index(), notes
