"""Sector rotation screen: where money is moving between the 11 GICS sectors, early (leading) and confirmed,
plus candidate stock lists inside sectors that have confirmed.

Status: UNVALIDATED. The first backtests (2025-26 member data, 27 years of sector ETFs) found that the
flags describe rotation but do not yet forecast it; the leading flags showed no edge. Every run re-scores
the flags over the stored history so the page always shows the current evidence. Method: docs/sectors.md.

Views    : cap-weighted  = sector SPDR ETF vs SPY
           equal-weight  = daily-rebalanced average of member returns (each capped at +/-30%) vs the
                           equal-weight universe. Ranks, flags and stages use the equal-weight view.
Confirm  : Gaining  rank up >= 3 over 20 sessions, ratio above its 50-day avg, breadth up >= 10 pts
           Losing   mirror image
           Thinning ETF in the top 3 by 20-session RS while breadth falls >= 15 pts
Leading  : L1 breadth thaw, L2 early leaders, L4 accumulation (L3, bad news absorbed, needs the
           extended-hours movers lists and is not in this version)
Stage    : Confirmed > Losing > Early (2+ leading) > Watch (1) > Neutral; a watch older than 30 sessions
           without confirmation becomes "Stale watch".
Lists    : Confirmed sectors only: top 10 members by 20-session return vs the sector, >= $25M/day traded,
           <= 40% above the 50-day, no one-day move <= -35% or >= +50% in 60 sessions (likely corporate action).
"""
from __future__ import annotations

import datetime as dt
import warnings

import numpy as np
import pandas as pd

from ..config import Settings, get_settings
from .. import data as datasrc
from ..data.base import UniverseMember

SECTORS = [  # key, GICS sector, SPDR ETF
    ("tech", "Information Technology", "XLK"),
    ("fin", "Financials", "XLF"),
    ("hlth", "Health Care", "XLV"),
    ("disc", "Consumer Discretionary", "XLY"),
    ("ind", "Industrials", "XLI"),
    ("comm", "Communication Services", "XLC"),
    ("stap", "Consumer Staples", "XLP"),
    ("ener", "Energy", "XLE"),
    ("util", "Utilities", "XLU"),
    ("re", "Real Estate", "XLRE"),
    ("mat", "Materials", "XLB"),
]
TH = {"rankMove": 3, "breadthUp": 10, "breadthDown": -10, "thinBreadth": -15, "flatRS": 1.0, "l1MinRank": 6,
      "l2HiShare": 15, "l4UpVol": 58, "l4VolRatio": 1.10, "staleWatch": 30, "episodeGap": 10, "fwd": 20,
      "listMinDvolM": 25, "listMaxExt50": 40, "ratesBp": 25}
HIST = 60


def rnd(x, n=2):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def roll_mean(a, w):
    out = np.full(a.shape, np.nan)
    c = np.nancumsum(np.nan_to_num(a), axis=-1)
    n = np.cumsum(~np.isnan(a), axis=-1)
    cs = np.concatenate([np.zeros(a.shape[:-1] + (1,)), c], axis=-1)
    ns = np.concatenate([np.zeros(a.shape[:-1] + (1,)), n], axis=-1)
    s = cs[..., w:] - cs[..., :-w]
    k = ns[..., w:] - ns[..., :-w]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[..., w - 1:] = np.where(k == w, s / w, np.nan)
    return out


def roll_max(a, w):
    out = np.full(a.shape, np.nan)
    for i in range(w - 1, a.shape[-1]):
        out[..., i] = np.max(a[..., i - w + 1:i + 1], axis=-1)
    return out


def shift(a, n):
    out = np.full(a.shape, np.nan)
    out[..., n:] = a[..., :-n]
    return out


def episodes(on, gap):
    st, last = [], -10**9
    for i, v in enumerate(on):
        if v:
            if i - last > gap:
                st.append(i)
            last = i
    return st


def compute(bars: dict[str, pd.DataFrame], members: list[UniverseMember], *, rates: dict | None = None,
            drop_today: bool = False, today: str | None = None) -> dict:
    """bars must contain SPY and the 11 sector ETFs plus member symbols. Returns the rotation document."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN windows early in the history are expected
        return _compute(bars, members, rates, drop_today, today)


def _compute(bars, members, rates, drop_today, today):
    gics2key = {s[1]: s[0] for s in SECTORS}
    mem = {m.symbol: m for m in members if m.sector in gics2key and m.symbol in bars}
    etfs = ["SPY"] + [s[2] for s in SECTORS]
    missing_etf = [e for e in etfs if e not in bars]
    if missing_etf:
        raise ValueError(f"no data for {missing_etf}")
    dates = sorted(bars["SPY"].index)
    if drop_today and today:
        dates = [d for d in dates if d.date().isoformat() != today]
    T = len(dates)
    idx = pd.DatetimeIndex(dates)
    syms = list(mem)
    S = len(syms)
    C = np.vstack([bars[s]["close"].reindex(idx).to_numpy(dtype=float) for s in syms]) if S else np.zeros((0, T))
    V = np.vstack([bars[s]["volume"].reindex(idx).fillna(0).to_numpy(dtype=float) for s in syms]) if S else np.zeros((0, T))
    E = {e: bars[e]["close"].reindex(idx).ffill().to_numpy(dtype=float) for e in etfs}

    sec_of = np.array([gics2key[mem[s].sector] for s in syms])
    keys = [s[0] for s in SECTORS]
    K = len(keys)
    with np.errstate(invalid="ignore", divide="ignore"):
        RAW = C / shift(C, 1) - 1
    R = np.clip(RAW, -0.30, 0.30)

    def ew_index(mask):
        if not mask.any():
            return np.ones(T)
        with np.errstate(invalid="ignore"):
            r = np.nanmean(np.where(mask[:, None], R, np.nan), axis=0)
        return np.cumprod(1 + np.nan_to_num(r))

    EWU = ew_index(np.ones(S, bool))
    EWS = np.array([ew_index(sec_of == k) for k in keys])
    RATIO = EWS / EWU
    CW = np.array([E[s[2]] / E["SPY"] for s in SECTORS])

    def rs(x, n):
        return (x / shift(x, n) - 1) * 100
    RSE = {n: rs(RATIO, n) for n in (5, 20, 60)}
    RSC = {n: rs(CW, n) for n in (5, 20, 60)}
    R50 = (RATIO / roll_mean(RATIO, 50) - 1) * 100

    with np.errstate(invalid="ignore"):
        m50 = roll_mean(C, 50)
        above = np.where(np.isnan(C) | np.isnan(m50), np.nan, (C > m50).astype(float))
        hi63 = roll_max(C, 63)
        newhi = np.where(np.isnan(hi63), np.nan, (C >= hi63).astype(float))
    hi5 = np.full(newhi.shape, np.nan)
    for i in range(4, T):
        w = newhi[:, i - 4:i + 1]
        hi5[:, i] = np.where(np.all(np.isnan(w), axis=1), np.nan, np.nanmax(np.nan_to_num(w, nan=0), axis=1))
    DV = C * V
    up = R > 0
    BR = np.zeros((K, T)); HI = np.zeros((K, T)); SH = np.zeros((K, T)); UPV = np.zeros((K, T))
    totdv = np.nansum(DV, axis=0)
    totdv[totdv == 0] = np.nan
    for k, key in enumerate(keys):
        m = sec_of == key
        with np.errstate(invalid="ignore", divide="ignore"):
            BR[k] = np.nanmean(above[m], axis=0) * 100 if m.any() else np.nan
            HI[k] = np.nanmean(hi5[m], axis=0) * 100 if m.any() else np.nan
            sdv = np.nansum(DV[m], axis=0)
            SH[k] = sdv / totdv
            updv = np.nansum(np.where(up[m], DV[m], 0), axis=0)
            UPV[k] = roll_mean(updv[None], 20)[0] / roll_mean(sdv[None], 20)[0] * 100
    with np.errstate(invalid="ignore", divide="ignore"):
        VR = roll_mean(SH, 5) / roll_mean(SH, 60)
    BRC = BR - shift(BR, 20)

    def ranks(x):
        o = np.full(x.shape, np.nan)
        for i in range(x.shape[1]):
            c = x[:, i]
            if np.isnan(c).any():
                continue
            o[np.argsort(-c), i] = np.arange(1, x.shape[0] + 1)
        return o
    RK = ranks(RSE[20]); RKC = RK - shift(RK, 20)
    CWRK = ranks(RSC[20])

    with np.errstate(invalid="ignore"):
        G = (-RKC >= TH["rankMove"]) & (R50 > 0) & (BRC >= TH["breadthUp"])
        X = (RKC >= TH["rankMove"]) & (R50 < 0) & (BRC <= TH["breadthDown"])
        TT = (CWRK <= 3) & (BRC <= TH["thinBreadth"])
        L1 = (BRC >= TH["breadthUp"]) & (RSE[20] <= TH["flatRS"]) & (RK >= TH["l1MinRank"])
        L2 = (HI >= TH["l2HiShare"]) & (R50 < 0)
        L4 = (UPV >= TH["l4UpVol"]) & (VR >= TH["l4VolRatio"]) & (RSE[20] <= TH["flatRS"])
    valid = ~np.isnan(RKC) & ~np.isnan(BRC) & ~np.isnan(R50) & ~np.isnan(VR) & ~np.isnan(UPV)
    for F in (G, X, TT, L1, L2, L4):
        F &= valid
    allv = valid.all(axis=0)
    if not allv.any():
        raise ValueError("not enough history to compute the flags (need ~90 sessions)")
    first = int(np.argmax(allv))
    anyL = L1 | L2 | L4

    def stage_at(k, i):
        nl = int(L1[k, i]) + int(L2[k, i]) + int(L4[k, i])
        if G[k, i]:
            return "Confirmed"
        if X[k, i]:
            return "Losing"
        if nl >= 2:
            return "Early"
        if nl == 1:
            return "Watch"
        return "Neutral"

    def watch_age(k, i):
        if not anyL[k, i]:
            return None
        j = i
        while j > 0:
            lo = max(0, j - 5)
            w = np.where(anyL[k, lo:j])[0]
            if not len(w):
                break
            j = lo + w[0]
        return i - j

    ma50 = roll_mean(C, 50)

    def pick(k_key, i):
        m = np.where(sec_of == k_key)[0]
        if i < 60:
            return []
        kk_ = keys.index(k_key)
        ew20 = EWS[kk_, i] / EWS[kk_, i - 20] - 1
        rows = []
        for k in m:
            c0, c20 = C[k, i], C[k, i - 20]
            if np.isnan(c0) or np.isnan(c20) or np.isnan(ma50[k, i]):
                continue
            dv = np.nanmean(DV[k, i - 19:i + 1]) / 1e6
            ext = (c0 / ma50[k, i] - 1) * 100
            r60 = RAW[k, i - 59:i + 1]
            if dv < TH["listMinDvolM"] or ext > TH["listMaxExt50"] or np.nanmin(r60) <= -0.35 or np.nanmax(r60) >= 0.50:
                continue
            rows.append((((c0 / c20) / (1 + ew20) - 1) * 100, k, dv, ext))
        rows.sort(key=lambda x: -x[0])
        return rows[:10]

    # ---- backtest over history (base rates over sector-days with a known outcome only)
    F = TH["fwd"]; gap = TH["episodeGap"]
    FW = np.full((K, T), np.nan)
    FW[:, :T - F] = (RATIO[:, F:] / RATIO[:, :T - F] - 1) * 100
    fw_known = FW[:, first:][~np.isnan(FW[:, first:])]
    base_pos = float(np.mean(fw_known > 0) * 100) if fw_known.size else float("nan")
    base_neg = float(np.mean(fw_known < 0) * 100) if fw_known.size else float("nan")
    early = (L1.astype(int) + L2.astype(int) + L4.astype(int)) >= 2
    bt = {"from": dates[first].date().isoformat(), "fwd": F, "baseUpPct": rnd(base_pos, 1), "baseDownPct": rnd(base_neg, 1), "flags": {}}
    log_eps = []
    for name, M, want in (("Gaining", G, 1), ("Losing", X, -1), ("Thinning", TT, -1), ("L1 breadth thaw", L1, 1),
                          ("L2 early leaders", L2, 1), ("L4 accumulation", L4, 1), ("Early (2+ leading)", early, 1)):
        vals = []
        for k in range(K):
            for i in episodes(M[k, first:], gap):
                i += first
                f = FW[k, i]
                log_eps.append({"sector": keys[k], "flag": name, "date": dates[i].date().isoformat(), "fwd20": rnd(f, 2)})
                if not np.isnan(f):
                    vals.append(f * want)
        v = np.array(vals)
        basep = base_pos if want > 0 else base_neg
        bt["flags"][name] = {"n": int(len(v)), "hitPct": rnd(np.mean(v > 0) * 100, 1) if len(v) else None,
                             "edgePts": rnd(np.mean(v > 0) * 100 - basep, 1) if len(v) else None,
                             "meanFwd": rnd(np.mean(v) * want, 2) if len(v) else None, "dir": "up" if want > 0 else "down"}
    lv = []
    for k in range(K):
        for i in episodes(G[k, first:], gap):
            i += first
            if i + F >= T:
                continue
            sec_f = EWS[k, i + F] / EWS[k, i] - 1
            for _, kk, _, _ in pick(keys[k], i):
                if not np.isnan(C[kk, i + F]):
                    lv.append((C[kk, i + F] / C[kk, i] - 1 - sec_f) * 100)
    lv = np.array(lv)
    bt["lists"] = {"n": int(len(lv)), "beatSectorPct": rnd(np.mean(lv > 0) * 100, 1) if len(lv) else None,
                   "meanVsSector": rnd(np.mean(lv), 2) if len(lv) else None}
    bt["caveat"] = ("Current universe only (delisted names missing), one market period, thresholds set before testing "
                    "and not tuned. Treat differences under ~5 points as noise.")

    # ---- today's document
    i = T - 1
    h0 = max(first, T - HIST)
    out_secs, lists = [], {}
    for k, (key, label, etf) in enumerate(SECTORS):
        stg = stage_at(k, i)
        wa = watch_age(k, i)
        if stg in ("Watch", "Early") and wa is not None and wa > TH["staleWatch"]:
            stg = "Stale watch"
        notes = []
        if rates and rates.get("big") and key in ("tech", "re", "util", "fin") and stg != "Neutral":
            notes.append(f"Rates: 10-yr {rates['chg20bp']:+}bp in 20 sessions; may explain part of this.")
        if TT[k, i]:
            notes.append("Thinning: ETF top 3, breadth falling.")
        out_secs.append({
            "key": key, "label": label, "etf": etf, "members": int((sec_of == key).sum()),
            "rsEW": {"w1": rnd(RSE[5][k, i]), "w4": rnd(RSE[20][k, i]), "w12": rnd(RSE[60][k, i])},
            "rsCW": {"w1": rnd(RSC[5][k, i]), "w4": rnd(RSC[20][k, i]), "w12": rnd(RSC[60][k, i])},
            "rank": rnd(RK[k, i], 0), "rankChg": rnd(-RKC[k, i], 0), "cwRank": rnd(CWRK[k, i], 0),
            "vs50": rnd(R50[k, i]), "breadth": rnd(BR[k, i], 1), "breadthChg": rnd(BRC[k, i], 1),
            "hiShare": rnd(HI[k, i], 1), "upVol": rnd(UPV[k, i], 1), "volRatio": rnd(VR[k, i]),
            "lead": {"L1": bool(L1[k, i]), "L2": bool(L2[k, i]), "L4": bool(L4[k, i])},
            "confirm": {"G": bool(G[k, i]), "X": bool(X[k, i]), "T": bool(TT[k, i])},
            "stage": stg, "watchAge": wa, "notes": notes,
            "hist": {"rank": [rnd(x, 0) for x in RK[k, h0:]], "vs50": [rnd(x, 1) for x in R50[k, h0:]],
                     "breadth": [rnd(x, 1) for x in BR[k, h0:]]},
        })
        if stg == "Confirmed":
            rows = []
            spy20 = E["SPY"][i] / E["SPY"][i - 20] - 1
            for rel, kk, dv, ext in pick(key, i):
                s = syms[kk]
                c0 = C[kk, i]
                hi252 = np.nanmax(C[kk, max(0, i - 251):i + 1])
                rows.append({"sym": s, "name": mem[s].name[:40], "industry": mem[s].industry[:40],
                             "rsSector": rnd(rel, 1), "ret20": rnd((c0 / C[kk, i - 20] - 1) * 100, 1),
                             "rsSPY": rnd(((c0 / C[kk, i - 20]) / (1 + spy20) - 1) * 100, 1),
                             "from52": rnd((c0 / hi252 - 1) * 100, 1), "ext50": rnd(ext, 1), "dvolM": rnd(dv, 0)})
            lists[key] = rows
    asof = dates[i].date().isoformat()
    return {"id": asof, "asOf": asof, "status": "unvalidated", "universe": {"members": S, "sessions": T},
            "thresholds": TH, "rates": rates, "dates": [d.date().isoformat() for d in dates[h0:]],
            "sectors": out_secs, "lists": lists, "backtest": bt,
            "episodes": [e for e in log_eps if e["date"] >= dates[max(first, T - 252)].date().isoformat()][-400:]}


def run(s: Settings | None = None, signals_doc: dict | None = None) -> dict:
    s = s or get_settings()
    members, source = datasrc.universe(2e9, s)
    etfs = ["SPY"] + [x[2] for x in SECTORS]
    bars = datasrc.daily_bars(etfs + [m.symbol for m in members], period_days=760, s=s)
    rates = None
    if signals_doc:
        m = next((x for x in signals_doc.get("signals", []) if x.get("id") == "MA1"), None)
        if m:
            rates = {"asOf": signals_doc.get("asOf"), "chg20bp": m.get("chg20bp"),
                     "big": m.get("chg20bp") is not None and abs(m["chg20bp"]) >= TH["ratesBp"]}
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    doc = compute(bars, members, rates=rates, drop_today=(now.hour, now.minute) < (16, 10), today=now.date().isoformat())
    doc["universe"]["source"] = source
    doc["universe"]["failed"] = len([m for m in members if m.symbol not in bars])
    return doc
