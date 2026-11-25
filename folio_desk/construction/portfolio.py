"""Portfolio construction: backtests of a weight mix (monthly points, configurable rebalancing and
contributions), risk/return statistics, factor sensitivities, stress windows, and tax-aware account
placement checks. Ported from the Portfolio Lab page; prices are daily adjusted closes.

Accounts: T = taxable, I = traditional IRA / 401(k), R = Roth.
"""
from __future__ import annotations

import json
import math
from importlib import resources

import numpy as np
import pandas as pd

CATEGORY_CLASS = {
    "US Total Market": "us", "US Large Cap": "us", "US Value": "us", "US Mid/Small": "us", "US Growth": "us",
    "Sector/Satellite": "sat", "Leveraged": "sat", "International": "intl", "Stacked": "stack",
    "US Aggregate Bonds": "bond", "Short Treasuries": "bond", "Intermediate Treasuries": "bond", "Long Treasuries": "bond",
    "Municipal Bonds": "bond", "TIPS": "tips", "Gold": "gold", "Commodities": "real", "Real Estate": "real", "Cash/T-Bills": "cash",
}
STRESS = [("2008 financial crisis", "2007-10-09", "2009-03-09"), ("2011 debt-ceiling scare", "2011-04-29", "2011-10-03"),
          ("2013 taper tantrum", "2013-05-02", "2013-06-24"), ("2018 Q4 sell-off", "2018-09-20", "2018-12-24"),
          ("2020 COVID crash", "2020-02-19", "2020-03-23"), ("2022 rate shock (calendar year)", "2021-12-31", "2022-12-30"),
          ("2025 tariff shock", "2025-02-19", "2025-04-08")]
ACCT = {"T": "Taxable", "I": "Traditional IRA", "R": "Roth IRA"}


def load_preset(name: str):
    return json.loads(resources.files("folio_desk.presets").joinpath(name).read_text())


def default_funds() -> list[dict]:
    return load_preset("funds.json")


def presets() -> dict:
    return {k: v for k, v in load_preset("portfolios.json").items() if not k.startswith("_")}


def weights_by_ticker(rows: list[dict]) -> dict[str, float]:
    w: dict[str, float] = {}
    for r in rows:
        w[r["t"]] = w.get(r["t"], 0) + float(r["w"] or 0)
    return w


def backtest(weights: dict[str, float], prices: pd.DataFrame, rebal: str = "A", init: float = 1.0,
             contrib_monthly: float = 0.0, start: str | None = None) -> dict | None:
    """prices: daily adjusted closes, columns = tickers. Month-end points; rebal M/Q/A/N."""
    tks = [t for t, w in weights.items() if w > 0]
    tot = sum(weights[t] for t in tks)
    if not tks or not tot:
        return None
    missing = [t for t in tks if t not in prices]
    if missing:
        return {"missing": missing}
    px = prices[tks].dropna(how="any")
    if start:
        px = px[px.index >= pd.Timestamp(start)]
    if len(px) < 40:
        return None
    me = px.groupby([px.index.year, px.index.month]).tail(1)
    if me.index[0] != px.index[0]:
        me = pd.concat([px.iloc[[0]], me])
    if me.index[-1] != px.index[-1]:
        me = pd.concat([me, px.iloc[[-1]]])
    me = me[~me.index.duplicated()]
    w = np.array([weights[t] / tot for t in tks])
    hold = w * init
    val, nav, contrib = init, 1.0, init
    out = {"dates": [me.index[0].date().isoformat()], "nav": [1.0], "val": [val], "contrib": [contrib], "rets": []}
    vals = me.to_numpy()
    for k in range(1, len(me)):
        before = val
        hold = hold * vals[k] / vals[k - 1]
        val = float(hold.sum())
        r = val / before - 1
        nav *= 1 + r
        out["rets"].append(r)
        mo = me.index[k].month
        if contrib_monthly and k < len(me) - 1:
            hold = hold + contrib_monthly * w
            val += contrib_monthly
            contrib += contrib_monthly
        if rebal == "M" or (rebal == "Q" and mo % 3 == 0) or (rebal == "A" and mo == 12):
            hold = w * val
        out["dates"].append(me.index[k].date().isoformat())
        out["nav"].append(nav)
        out["val"].append(val)
        out["contrib"].append(contrib)
    return out


def stats(bt: dict, rf_annual: float = 0.0) -> dict:
    r = np.array(bt["rets"])
    n = len(r)
    d0, d1 = pd.Timestamp(bt["dates"][0]), pd.Timestamp(bt["dates"][-1])
    y = (d1 - d0).days / 365.25
    nav = np.array(bt["nav"])
    cagr = nav[-1] ** (1 / y) - 1 if y > 0 else float("nan")
    vol = float(r.std(ddof=1) * math.sqrt(12)) if n > 1 else float("nan")
    sharpe = (r.mean() * 12 - rf_annual) / vol if vol and vol == vol else None
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1
    tr = int(dd.argmin())
    pk = int(nav[:tr + 1].argmax())
    rec = next((i - pk for i in range(tr, len(nav)) if nav[i] >= nav[pk]), None)
    w12 = [nav[i] / nav[i - 12] - 1 for i in range(12, len(nav))]
    years: dict[str, float] = {}
    for i in range(1, len(bt["dates"])):
        yy = bt["dates"][i][:4]
        years[yy] = years.get(yy, 1.0) * (1 + r[i - 1])
    return {"cagr": cagr, "vol": vol, "sharpe": sharpe, "mdd": float(dd.min()), "recoveryMonths": rec,
            "worst12": min(w12) if w12 else None, "best12": max(w12) if w12 else None,
            "drawdown": dd.tolist(), "years": {k: v - 1 for k, v in years.items()},
            "endValue": bt["val"][-1], "contributed": bt["contrib"][-1], "years_": y}


def stress(weights: dict[str, float], prices: pd.DataFrame) -> list[dict]:
    tot = sum(weights.values()) or 1
    out = []
    for label, a, b in STRESS:
        v, ok = 0.0, True
        for t, w in weights.items():
            if t not in prices:
                ok = False
                break
            s = prices[t].dropna()
            sa, sb = s[s.index >= pd.Timestamp(a)], s[s.index >= pd.Timestamp(b)]
            if sa.empty or sb.empty or s.index[0] > pd.Timestamp(a):
                ok = False
                break
            v += w / tot * (sb.iloc[0] / sa.iloc[0] - 1)
        spy = None
        if "SPY" in prices:
            s = prices["SPY"].dropna()
            sa, sb = s[s.index >= pd.Timestamp(a)], s[s.index >= pd.Timestamp(b)]
            spy = float(sb.iloc[0] / sa.iloc[0] - 1) if not sa.empty and not sb.empty else None
        out.append({"window": label, "from": a, "to": b, "portfolio": v if ok else None, "spy": spy})
    return out


def placement_checks(rows: list[dict], funds: dict[str, dict], accounts: dict[str, float]) -> list[dict]:
    """Tax-placement warnings. Rules are US-federal generalisations; state tax treatment varies."""
    W = []
    tot = sum(accounts.values())
    for a in ("T", "I", "R"):
        w = sum(float(r["w"] or 0) for r in rows if r["a"] == a)
        if rows and (w > 0 or accounts.get(a, 0) > 0) and abs(tot * w / 100 - accounts.get(a, 0)) > max(1000, 0.01 * tot):
            W.append({"level": "warn", "text": f"{ACCT[a]} holdings come to ${tot * w / 100:,.0f} but the account holds ${accounts.get(a, 0):,.0f}."})
    ineff = {"bond", "tips", "gold", "real", "stack"}
    low = {"bond", "tips", "gold", "cash"}
    for r in rows:
        if not float(r["w"] or 0):
            continue
        f = funds.get(r["t"])
        if not f:
            continue
        k = CATEGORY_CLASS.get(f["category"], "us")
        if r["a"] == "T" and k in ineff and f["category"] not in ("Municipal Bonds", "Short Treasuries"):
            why = ("gold gains are taxed as collectibles (up to 28%)" if k == "gold" else
                   "its distributions have been ordinary income" if k == "stack" else "its income is taxed at ordinary rates")
            W.append({"level": "warn", "text": f"{r['t']} in Taxable: {why}. It usually belongs in a tax-deferred account."})
        if r["a"] == "T" and f["category"] == "Leveraged":
            W.append({"level": "warn", "text": f"{r['t']} in Taxable: leveraged funds trade heavily inside the fund. Hold it in an IRA."})
        if r["a"] != "T" and f["category"] == "Municipal Bonds":
            W.append({"level": "warn", "text": f"{r['t']} in the {ACCT[r['a']]}: muni interest is already tax-free, so it wastes the shelter."})
        if r["a"] == "R" and k in low and f["category"] != "Municipal Bonds":
            W.append({"level": "warn", "text": f"{r['t']} in the Roth: a low-growth asset uses up tax-free space."})
        if r["a"] != "T" and k == "intl":
            W.append({"level": "info", "text": f"{r['t']} in the {ACCT[r['a']]}: the foreign tax credit is only usable in Taxable."})
    idx: dict[str, dict[str, list[str]]] = {"T": {}, "I": {}, "R": {}}
    for r in rows:
        f = funds.get(r["t"])
        if not float(r["w"] or 0) or not f or not f.get("index") or f["index"].startswith("Active"):
            continue
        idx[r["a"]].setdefault(f["index"], []).append(r["t"])
    for ix, tks in idx["T"].items():
        for a in ("I", "R"):
            if ix in idx[a]:
                W.append({"level": "bad", "text": f"Same index in Taxable and the {ACCT[a]} ({ix}: {', '.join(tks)} vs {', '.join(idx[a][ix])}). "
                                                  "A buy there within 30 days of a taxable loss sale is a wash sale, and the loss is lost for good."})
    return W or [{"level": "good", "text": "No placement issues found." if rows else "Add holdings to run the checks."}]
