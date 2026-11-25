"""Collect everything an equity run needs for one ticker.

EDGAR (primary): CIK, filings list, 12 discrete XBRL quarters, the latest 10-K/10-Q and the last 8
earnings releases as text (saved under <outdir>/docs for review), Form 4 open-market activity.
Data layer: 5 years of daily prices (returns, volatility, beta vs SPY, big-move days), consensus
estimates, a put chain 30-130 days out, and peer stats.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .. import data as datasrc
from ..config import Settings, get_settings
from ..data.edgar import EdgarClient, filings_list
from .facts import DUR_TAGS, REV_TAGS, quarterly, quarters_table


def price_block(df: pd.DataFrame, spy: pd.DataFrame | None) -> dict:
    c = df["close"].dropna()
    if len(c) < 60:
        raise ValueError("fewer than 60 daily bars")
    last_1y = df.iloc[-252:]

    def rv(n):
        x = np.log(c.iloc[-n - 1:]).diff().dropna()
        return float(x.std() * math.sqrt(252))

    hi = last_1y["high"].idxmax()
    lo = last_1y["low"].idxmin()
    r = c.pct_change()
    d90 = r.iloc[-90:]
    sd = float(np.sqrt((d90 ** 2).mean()))
    thr = max(0.04, 2 * sd)
    big = [{"d": d.date().isoformat(), "r": round(float(v), 4), "sigma": round(float(v / sd), 1)} for d, v in d90.items() if abs(v) >= thr]
    beta = None
    if spy is not None:
        m = pd.concat([c.resample("ME").last().pct_change(), spy["close"].resample("ME").last().pct_change()], axis=1).dropna().iloc[-60:]
        if len(m) >= 24:
            beta = round(float(np.cov(m.iloc[:, 0], m.iloc[:, 1])[0, 1] / np.var(m.iloc[:, 1], ddof=1)), 2)
    ret = lambda n: float(c.iloc[-1] / c.iloc[-n - 1] - 1) if len(c) > n else None
    return {"price": float(c.iloc[-1]), "date": c.index[-1].date().isoformat(),
            "high52": float(last_1y.loc[hi, "high"]), "high52Date": hi.date().isoformat(),
            "low52": float(last_1y.loc[lo, "low"]), "low52Date": lo.date().isoformat(),
            "ret1m": ret(21), "ret3m": ret(63), "ret6m": ret(126), "ret12m": ret(252),
            "rv20": rv(20), "rv60": rv(60), "rv250": rv(min(250, len(c) - 2)), "beta5yMonthly": beta,
            "daily90": [{"d": d.date().isoformat(), "c": round(float(v), 2)} for d, v in c.iloc[-90:].items()],
            "bigDays": big, "_closes": c}


def own_pe_history(closes: pd.Series, quarters: list[dict]) -> dict:
    out = []
    for i in range(3, len(quarters)):
        eps4 = [quarters[k].get("epsDiluted") for k in range(i - 3, i + 1)]
        if any(e is None for e in eps4):
            continue
        ttm = sum(eps4)
        p = closes[closes.index <= pd.Timestamp(quarters[i]["end"])]
        if p.empty:
            continue
        out.append({"end": quarters[i]["end"], "price": round(float(p.iloc[-1]), 2), "ttmEps": round(ttm, 3),
                    "pe": round(float(p.iloc[-1]) / ttm, 1) if ttm > 0 else None})
    pos = sorted(x["pe"] for x in out if x["pe"] and x["pe"] > 0)
    med = pos[len(pos) // 2] if pos else None
    return {"points": out, "positiveQuarters": len(pos), "medianPE": med, "usable": len(pos) >= 8 and med is not None and med < 150}


def sec_block(ec: EdgarClient, ticker: str, outdir: Path | None, warns: list[str]) -> dict:
    cik, title = ec.cik_for(ticker)
    if not cik:
        raise ValueError(f"{ticker} not found in SEC company_tickers.json (not an SEC filer or wrong symbol)")
    sub = ec.submissions(cik)
    fl = filings_list(sub)
    cut12 = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    periodic = [f for f in fl if f["form"] in ("10-Q", "10-K", "20-F", "40-F")]
    eightk = [f for f in fl if f["form"] in ("8-K", "6-K") and f["date"] >= (dt.date.today() - dt.timedelta(days=760)).isoformat()]
    form4 = [f for f in fl if f["form"] == "4" and f["date"] >= cut12]
    cf = ec.company_facts(cik)
    quarters, used, w = quarters_table(cf)
    warns += w
    saved = []
    if outdir:
        docs = outdir / "docs"
        docs.mkdir(parents=True, exist_ok=True)

        def save(f, name, exhibit=None):
            try:
                doc = f["doc"]
                if exhibit:
                    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{f['acc'].replace('-', '')}/"
                    names = [x["name"] for x in ec.json(base + "index.json")["directory"]["item"]]
                    ex = [n for n in names if re.search(exhibit, n, re.I) and n.lower().endswith((".htm", ".html", ".txt"))]
                    if not ex:
                        return
                    doc = ex[0]
                txt = ec.filing_text(cik, f["acc"], doc)
                (docs / name).write_text(txt)
                saved.append({"file": name, "form": f["form"], "date": f["date"], "acc": f["acc"], "chars": len(txt)})
            except Exception as e:
                warns.append(f"could not fetch {f['form']} {f['acc']}: {e}")
        lq = next((f for f in periodic if f["form"] == "10-Q"), None)
        lk = next((f for f in periodic if f["form"] in ("10-K", "20-F", "40-F")), None)
        if lq:
            save(lq, f"10Q_{lq['report'] or lq['date']}.txt")
        if lk:
            save(lk, f"{lk['form'].replace('-', '')}_{lk['report'] or lk['date']}.txt")
        for f in [x for x in eightk if "2.02" in (x["items"] or "")][:8]:
            save(f, f"EX99_{f['date']}.txt", exhibit=r"ex[-_]?99|ex991|x99|exhibit99")
    insiders = []
    for f in form4[:150]:
        try:
            doc = re.sub(r"^xslF345X\d+/", "", f["doc"])
            x = ec.get(ec.filing_url(cik, f["acc"], doc)).decode("utf-8", "ignore")
            plan = bool(re.search(r"10b5-1", x, re.I))
            for t in re.findall(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", x, re.S):
                g = lambda p: (re.search(p, t, re.S) or [None, None])[1]
                sh, px = g(r"<transactionShares>\s*<value>(.*?)</value>"), g(r"<transactionPricePerShare>\s*<value>(.*?)</value>")
                insiders.append({"date": f["date"], "code": g(r"<transactionCode>(.*?)</transactionCode>"),
                                 "shares": float(sh) if sh else None, "price": float(px) if px else None, "plan10b51": plan})
        except Exception as e:
            warns.append(f"form4 {f['acc']}: {e}")
    buys = [t for t in insiders if t["code"] == "P"]
    sells = [t for t in insiders if t["code"] == "S"]
    val = lambda ts: round(sum((t["shares"] or 0) * (t["price"] or 0) for t in ts))
    return {"cik": cik, "name": title, "sic": sub.get("sicDescription"), "fiscalYearEnd": sub.get("fiscalYearEnd"),
            "lastEarnings": next((f["date"] for f in eightk if "2.02" in (f["items"] or "")), None),
            "tagsUsed": used, "quarters": quarters, "docs": saved,
            "filings": {"periodic": periodic[:8], "eightK": eightk[:20], "form4Count": len(form4)},
            "insiders": {"openMarketBuys": len(buys), "buyValue": val(buys), "openMarketSells": len(sells), "sellValue": val(sells),
                         "sells10b51Share": round(sum(1 for t in sells if t["plan10b51"]) / len(sells), 2) if sells else None}}


def peer_block(ec: EdgarClient, peers: list[str], s: Settings, warns: list[str]) -> list[dict]:
    out = []
    bars = datasrc.daily_bars(peers, period_days=10, s=s)
    for p in peers:
        row = {"ticker": p}
        if p in bars:
            row["price"] = float(bars[p]["close"].iloc[-1])
        try:
            e = datasrc.estimates(p, s)
            row["epsFY1"], row["epsFY2"] = e.eps_fy1, e.eps_fy2
            if row.get("price") and e.eps_fy1:
                row["fwdPE"] = round(row["price"] / e.eps_fy1, 1)
            if e.eps_fy1 and e.eps_fy2 and e.eps_fy1 > 0:
                row["epsGrowthFY2"] = round(e.eps_fy2 / e.eps_fy1 - 1, 3)
        except Exception as ex:
            warns.append(f"peer {p} estimates: {ex}")
        try:
            cik, _ = ec.cik_for(p)
            if cik:
                cf = ec.company_facts(cik)
                rev, _ = quarterly(cf, REV_TAGS)
                ends = sorted(rev)[-8:]
                if len(ends) >= 8:
                    t4, p4 = sum(rev[e] for e in ends[-4:]), sum(rev[e] for e in ends[:4])
                    row["revGrowthTTM"] = round(t4 / p4 - 1, 3) if p4 else None
                eps, _ = quarterly(cf, DUR_TAGS["epsDiluted"])
                ee = sorted(eps)[-4:]
                if len(ee) == 4 and row.get("price"):
                    ttm = sum(eps[e] for e in ee)
                    row["ttmEps"] = round(ttm, 3)
                    row["trailingPE"] = round(row["price"] / ttm, 1) if ttm > 0 else None
        except Exception as ex:
            warns.append(f"peer {p} xbrl: {ex}")
        out.append(row)
    return out


def collect(ticker: str, peers: list[str] | None = None, outdir: str | Path | None = None, s: Settings | None = None,
            edgar: EdgarClient | None = None) -> dict:
    s = s or get_settings()
    T = ticker.upper()
    warns: list[str] = []
    ec = edgar or EdgarClient(s.sec.user_agent)
    out = Path(outdir) if outdir else None
    res: dict = {"ticker": T, "collectedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    res["sec"] = sec_block(ec, T, out, warns)
    bars = datasrc.daily_bars([T, "SPY"], period_days=1900, s=s)
    if T not in bars:
        raise ValueError(f"no price history for {T}")
    pb = price_block(bars[T], bars.get("SPY"))
    closes = pb.pop("_closes")
    res["price"] = pb
    e = datasrc.estimates(T, s)
    res["estimates"] = {"epsFY1": e.eps_fy1, "epsFY2": e.eps_fy2, "revFY1": e.rev_fy1, "revFY2": e.rev_fy2,
                        "nAnalysts": e.n_analysts, "source": e.source}
    if not (e.eps_fy1 or e.rev_fy1):
        warns.append("no consensus estimates: growth anchors fall back to trailing growth")
    try:
        rows = datasrc.option_chain(T, "put", 30, 130)
        lo, hi = 0.6 * pb["price"], 1.02 * pb["price"]
        res["options"] = {"rows": [r.__dict__ for r in rows if lo <= r.strike <= hi]}
    except Exception as ex:
        res["options"] = {"rows": []}
        warns.append(f"option chain unavailable: {ex}")
    res["ownPE"] = own_pe_history(closes, res["sec"]["quarters"])
    res["peerSet"] = peers or []
    res["peers"] = peer_block(ec, peers, s, warns) if peers else []
    res["warnings"] = warns
    if out:
        import json
        out.mkdir(parents=True, exist_ok=True)
        (out / "collect.json").write_text(json.dumps(res, indent=1, default=str))
    return res
