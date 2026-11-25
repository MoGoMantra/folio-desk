"""Multi-week drawdown screen: every stock in the universe whose close sits >= 10% below the highest close of
the last 16 sessions (that session plus the 15 before, about three weeks).

Per row: dd (vs the window high), peak and its date, d1, r5 / r10 / r15, the worst close-to-close day in the
window and its date, the 16 closes for a sparkline, and flags: "ca?" (a one-day move <= -35% or >= +50%:
likely split / spin-off, not a real drawdown) and "new" (< 22 sessions of history).
`research` lists names at <= -15% without a "ca?" flag: candidates to explain before acting.
"""
from __future__ import annotations

import pandas as pd

from ..config import Settings, get_settings
from .. import data as datasrc
from ..data.base import UniverseMember

WIN = 16


def rnd(x, n=2):
    return None if x is None or x != x else round(float(x), n)


def compute(bars: dict[str, pd.DataFrame], members: list[UniverseMember], keep: float = 10.0, research: float = 15.0) -> dict:
    mem = {m.symbol: m for m in members}
    rows, stats, asof = [], {"universe": 0, "dd10": 0, "dd15": 0, "dd20": 0}, None
    for sym, df in bars.items():
        m = mem.get(sym)
        if m is None or len(df) < WIN:
            continue
        c = df["close"].dropna()
        if len(c) < WIN:
            continue
        w = c.iloc[-WIN:]
        vals = w.to_list()
        d = [x.date().isoformat() for x in w.index]
        asof = max(asof or d[-1], d[-1])
        last, pk = vals[-1], max(vals)
        pi = vals.index(pk)
        dd = (last / pk - 1) * 100
        stats["universe"] += 1
        for k in (10, 15, 20):
            stats[f"dd{k}"] += dd <= -k
        if dd > -keep:
            continue
        rets = [(d[j], (vals[j] / vals[j - 1] - 1) * 100) for j in range(1, WIN)]
        wd = min(rets, key=lambda x: x[1])
        flags = []
        if any(r <= -35 or r >= 50 for _, r in rets):
            flags.append("ca?")
        if len(c) < 22:
            flags.append("new")
        rows.append({"sym": sym, "name": m.name[:40], "sector": m.sector, "price": rnd(last), "peak": rnd(pk), "peakDate": d[pi],
                     "dd": rnd(dd), "d1": rnd((vals[-1] / vals[-2] - 1) * 100), "r5": rnd((last / vals[-6] - 1) * 100),
                     "r10": rnd((last / vals[-11] - 1) * 100), "r15": rnd((last / vals[0] - 1) * 100),
                     "w1": rnd(wd[1]), "w1Date": wd[0], "closes": [rnd(x) for x in vals], "flag": " ".join(flags)})
    rows.sort(key=lambda r: r["dd"])
    todo = [r["sym"] for r in rows if r["dd"] <= -research and "ca?" not in r["flag"]]
    return {"id": asof, "asOf": asof, "window": WIN, "keepPct": keep, "stats": stats, "rows": rows, "research": todo}


def run(s: Settings | None = None) -> dict:
    s = s or get_settings()
    members, source = datasrc.universe(2e9, s)
    bars = datasrc.daily_bars([m.symbol for m in members], period_days=60, s=s)
    import datetime as dt
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    if (now.hour, now.minute) < (16, 10):  # today's session is not closed yet
        today = pd.Timestamp(now.date())
        bars = {k: v[v.index < today] for k, v in bars.items()}
    doc = compute(bars, members)
    doc["universeSource"] = source
    return doc
