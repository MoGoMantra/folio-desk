"""Market signal monitor: ~20 signals in six layers (breadth, leadership, credit, volatility, macro, risk
appetite), each green / amber / red, plus a top-risk score, a regime, a 10-item bottom checklist,
watchlist trend status and state changes against the previous run.

Method: docs/signals.md. Thresholds were first calibrated on a single episode (Aug-Oct 2026) and are
UNVALIDATED beyond it; review them against outcomes before relying on them.

`compute()` is pure (series in, document out) so it is testable offline; `run()` fetches and computes.
"""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from ..config import Settings, get_settings
from .. import data as datasrc

HIST = 120  # sparkline length stored per signal

MARKET = ["SPY", "QQQ", "RSP", "IWM", "SMH", "SOXX", "XLU", "XLP", "ARKK", "HYG", "IEF", "LQD",
          "^VIX", "^VIX3M", "^VVIX", "^TNX", "CL=F", "DX-Y.NYB", "BTC-USD"]
BASKET = """AAPL MSFT NVDA AMZN GOOGL META AVGO TSLA BRK-B JPM LLY V UNH XOM MA COST HD PG JNJ WMT
ABBV NFLX BAC CRM ORCL CVX MRK KO AMD PEP TMO ADBE LIN ACN MCD CSCO WFC ABT PM GE IBM DHR INTU TXN
QCOM CAT VZ AMGN NOW ISRG DIS CMCSA NEE PFE SPGI RTX UNP GS LOW HON AMAT BKNG T UBER PGR COP BLK
SYK ELV LMT MS SCHW TJX C ADP VRTX PLD MDT DE BSX CB ADI REGN PANW LRCX MU SBUX KLAC GILD BMY SO
DUK MO CI ETN ZTS ICE SHW CME FCX NKE UPS""".split()

MANUAL_ITEMS = {  # bottom-checklist items that need judgment; carried forward from the previous run
    "B6": "Bad news gets bought (a miss/downgrade and the stock closes up)",
    "B7": "Capex / guidance of the market's leaders holds or rises",
    "B9": "Positioning flush ends (de-grossing over, blow-up rumours resolved)",
}

PLAYBOOK = {
    "Risk-on": "Normal buying; add on pullbacks.",
    "Caution": "Hold; stagger new buys; favour quality.",
    "Risk-off": "No averaging down into breaking leaders; trim to target weights; sell puts only at strikes you'd gladly own.",
    "Washout": "Contrarian zone: build the buy list; size re-entry by the bottom checklist.",
}


# ---------------------------------------------------------------- helpers (unchanged maths)

def series_on(dates, s):
    out, last = [], None
    for d in dates:
        if d in s:
            last = s[d]
        out.append(last)
    return out


def sma(xs, n, i=None):
    i = len(xs) - 1 if i is None else i
    w = [x for x in xs[max(0, i - n + 1): i + 1] if x is not None]
    return sum(w) / len(w) if len(w) >= max(5, n // 2) else None


def pct(a, b):
    return None if (a is None or b in (None, 0)) else 100.0 * (a / b - 1)


def ratio(a, b):
    return [None if (x is None or y in (None, 0)) else x / y for x, y in zip(a, b)]


def chg(xs, n):
    return pct(xs[-1], xs[-1 - n]) if len(xs) > n else None


def rnd(x, k=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, k)


def spark(xs, k=4):
    return [rnd(x, k) for x in xs[-HIST:]]


def status_hi(v, amber, red):
    if v is None:
        return "na"
    return "red" if v >= red else "amber" if v >= amber else "green"


def status_lo(v, amber, red):
    if v is None:
        return "na"
    return "red" if v <= red else "amber" if v <= amber else "green"


def closes_from_bars(bars: dict[str, pd.DataFrame]) -> dict[str, dict[str, float]]:
    return {s: {d.date().isoformat(): float(c) for d, c in df["close"].items() if c == c} for s, df in bars.items()}


# ---------------------------------------------------------------- compute

def compute(S: dict[str, dict[str, float]], *, watchlist: list[str], theme: list[str], theme_name: str = "Theme",
            bellwether: str = "", prev: dict | None = None, manual: dict | None = None) -> dict:
    """S = {symbol: {"YYYY-MM-DD": close}}. Returns the signals document."""
    for need in ["SPY", "RSP", "SMH", "HYG", "IEF", "^VIX"]:
        if need not in S:
            raise ValueError(f"critical series missing: {need}")
    dates = sorted(S["SPY"])
    asof = dates[-1]
    col = {s: series_on(dates, v) for s, v in S.items()}
    g = col.get
    sig = []

    def add(id_, layer, name, value, unit, status, rule, kind, hist=None, extra=None):
        d = {"id": id_, "layer": layer, "name": name, "value": rnd(value, 3), "unit": unit,
             "status": status, "rule": rule, "kind": kind}
        if hist is not None:
            d["hist"] = spark(hist)
        if extra:
            d.update(extra)
        sig.append(d)

    spy = g("SPY")
    spy_hi52 = max(x for x in spy[-252:] if x)
    spy_off = pct(spy[-1], spy_hi52)
    n = len(dates)

    # ---------- Breadth ----------
    rsp_spy = ratio(g("RSP"), spy)
    r30 = chg(rsp_spy, 30)
    below50 = rsp_spy[-1] < (sma(rsp_spy, 50) or 0)
    st = "red" if (r30 is not None and r30 <= -2 and spy_off is not None and spy_off > -3) else "amber" if below50 else "green"
    add("BR1", "Breadth", "Equal-weight vs S&P (RSP/SPY), 30-day change", r30, "%", st,
        "Red: RSP/SPY down >=2% over 30 sessions while SPY within 3% of its 52-wk high (narrowing). Amber: ratio below its 50-day avg.",
        "lead", rsp_spy, {"spyOffHigh": rnd(spy_off)})

    if "IWM" in col:
        iwm_spy = ratio(g("IWM"), spy)
        i30 = chg(iwm_spy, 30)
        st = "red" if (i30 is not None and i30 <= -3) else "amber" if iwm_spy[-1] < (sma(iwm_spy, 50) or 0) else "green"
        add("BR2", "Breadth", "Small caps vs S&P (IWM/SPY), 30-day change", i30, "%", st,
            "Red: down >=3% over 30 sessions. Amber: below its 50-day avg.", "lead", iwm_spy)

    bsyms = [s for s in BASKET if s in col]
    p50, p200, nnh = [], [], []
    for i in range(max(0, n - HIST - 25), n):
        a50 = a200 = cnt = hi = lo = 0
        for s in bsyms:
            xs = col[s]
            x = xs[i]
            if x is None:
                continue
            m50, m200 = sma(xs, 50, i), sma(xs, 200, i)
            if m50 is None:
                continue
            cnt += 1
            a50 += x > m50
            if m200 is not None:
                a200 += x > m200
            w = [y for y in xs[max(0, i - 251): i + 1] if y is not None]
            if len(w) > 120:
                hi += x >= max(w)
                lo += x <= min(w)
        p50.append(100.0 * a50 / cnt if cnt else None)
        p200.append(100.0 * a200 / cnt if cnt else None)
        nnh.append(hi - lo)
    if bsyms:
        add("BR3", "Breadth", f"% of {len(bsyms)} large caps above 50-day avg", p50[-1], "%",
            status_lo(p50[-1], 60, 40), "Green >60%, amber 40-60%, red <40%. <20% = washout (bottom checklist).", "coincident", p50)
        add("BR4", "Breadth", f"% of {len(bsyms)} large caps above 200-day avg", p200[-1], "%",
            status_lo(p200[-1], 60, 45), "Green >60%, amber 45-60%, red <45%.", "coincident", p200)
        nn10 = sum(nnh[-10:]) / 10
        add("BR5", "Breadth", "Net new 52-wk highs in basket (10-day avg)", nn10, "names",
            "green" if nn10 > 2 else "amber" if nn10 >= -2 else "red",
            "Green > +2, amber -2..+2, red < -2 (more new lows than highs).", "coincident", nnh)

    # ---------- Leadership ----------
    smh = g("SMH")
    smh200 = pct(smh[-1], sma(smh, 200))
    smh200_hist = [pct(smh[i], sma(smh, 200, i)) for i in range(max(0, n - HIST), n)]
    if smh200 is None:
        st = "na"
    elif smh200 >= 25 or smh200 < 0:
        st = "red"
    elif smh200 >= 15 or smh200 < 3:
        st = "amber"
    else:
        st = "green"
    add("LC1", "Leadership", "Semis (SMH) distance from 200-day avg", smh200, "%", st,
        "Red: >= +25% (blow-off / crowding) or below the 200-day (breakdown). Amber: +15..25% or 0..+3%. Green: +3..15%.",
        "lead", smh200_hist)
    smh_spy = ratio(smh, spy)
    s20 = chg(smh_spy, 20)
    add("LC2", "Leadership", "Semis vs S&P (SMH/SPY), 20-day change", s20, "%",
        status_lo(s20, -3, -8), "Amber <= -3%, red <= -8% (leadership breaking).", "coincident", smh_spy)
    dds, detail = [], {}
    for s in theme:
        if s in col:
            xs = [x for x in col[s][-252:] if x]
            if xs:
                d_ = pct(xs[-1], max(xs))
                dds.append(d_)
                detail[s] = rnd(d_, 1)
    dds.sort()
    med = dds[len(dds) // 2] if dds else None
    if dds:
        add("LC3", "Leadership", f"{theme_name}: median drawdown from 52-wk high ({len(dds)} names)", med, "%",
            status_lo(med, -10, -20), "Amber <= -10%, red <= -20%.", "coincident", None, {"detail": detail})

    # ---------- Credit ----------
    hyg_ief = ratio(g("HYG"), g("IEF"))
    h20 = chg(hyg_ief, 20)
    st = "red" if (h20 is not None and h20 <= -1.0) else "amber" if hyg_ief[-1] < (sma(hyg_ief, 50) or 0) else "green"
    add("CR1", "Credit", "High yield vs Treasuries (HYG/IEF), 20-day change", h20, "%", st,
        "Rate-adjusted junk-credit proxy. Red: down >=1% in 20 sessions. Amber: below 50-day avg.", "lead", hyg_ief)
    if "LQD" in col:
        lqd_ief = ratio(g("LQD"), g("IEF"))
        l20 = chg(lqd_ief, 20)
        st = "red" if (l20 is not None and l20 <= -0.75) else "amber" if lqd_ief[-1] < (sma(lqd_ief, 50) or 0) else "green"
        add("CR2", "Credit", "Investment grade vs Treasuries (LQD/IEF), 20-day change", l20, "%", st,
            "Red: down >=0.75% in 20 sessions. Amber: below 50-day avg.", "coincident", lqd_ief)
    if bellwether and bellwether in col:
        cw = col[bellwether]
        c20 = chg(cw, 20)
        add("CR3", "Credit", f"Theme credit bellwether: {bellwether} 20-day change", c20, "%",
            status_lo(c20, -10, -20), "Stock as a proxy for theme credit stress (bonds are not in free data). Amber <= -10%, red <= -20%.",
            "lead", cw)

    # ---------- Volatility ----------
    vix = g("^VIX")
    add("VO1", "Volatility", "VIX", vix[-1], "", status_hi(vix[-1], 16, 22), "Green <16, amber 16-22, red >22.", "coincident", vix)
    vts = ratio(vix, g("^VIX3M")) if "^VIX3M" in col else None
    if vts:
        add("VO2", "Volatility", "VIX / 3-month VIX (term structure)", vts[-1], "x", status_hi(vts[-1], 0.90, 1.0),
            "Green <0.90 (calm contango), amber 0.90-1.0, red >1.0 (backwardation = panic). A spike >1 then a fall back is a bottom signal.",
            "coincident", vts)
    vv = g("^VVIX")
    if vv:
        add("VO3", "Volatility", "VVIX (volatility of VIX)", vv[-1], "", status_hi(vv[-1], 95, 115),
            "Green <95, amber 95-115, red >115.", "coincident", vv)

    # ---------- Macro ----------
    tnx = g("^TNX")
    t20 = None
    if tnx:
        t20 = (tnx[-1] - tnx[-21]) * 100 if len(tnx) > 21 and tnx[-21] else None
        st = "red" if (t20 is not None and t20 >= 25) else "amber" if (tnx[-1] >= 5.25 or (t20 or 0) >= 10) else "green"
        add("MA1", "Macro", "10-year Treasury yield", tnx[-1], "%", st,
            "Red: up >=25bp in 20 sessions. Amber: >=5.25% or up >=10bp. Green otherwise.", "lead", tnx, {"chg20bp": rnd(t20, 0)})
    oil = g("CL=F")
    if oil:
        o20 = chg(oil, 20)
        st = "red" if ((o20 or 0) >= 10 or oil[-1] >= 100) else "amber" if oil[-1] >= 90 else "green"
        add("MA2", "Macro", "WTI crude oil", oil[-1], "$", st, "Red: >= $100 or up >=10% in 20 sessions. Amber: >= $90.",
            "lead", oil, {"chg20": rnd(o20, 1)})
    dxy = g("DX-Y.NYB")
    if dxy:
        d20 = chg(dxy, 20)
        add("MA3", "Macro", "US dollar index, 20-day change", d20, "%", status_hi(abs(d20) if d20 is not None else None, 2, 4),
            "Amber: |move| >=2% in 20 sessions, red >=4% (dollar shocks tighten conditions).", "coincident", dxy)

    # ---------- Risk appetite ----------
    btc = g("BTC-USD")
    if btc:
        w = [x for x in btc[-90:] if x]
        bdd = pct(btc[-1], max(w))
        add("RA1", "Risk appetite", "Bitcoin drawdown from 90-day high", bdd, "%", status_lo(bdd, -7, -15),
            "Amber <= -7%, red <= -15%. Speculative appetite tends to roll over before equities.", "lead", btc)
    ark = g("ARKK")
    if ark:
        a20 = chg(ratio(ark, spy), 20)
        add("RA2", "Risk appetite", "Speculative growth vs S&P (ARKK/SPY), 20-day change", a20, "%",
            status_lo(a20, -3, -7), "Amber <= -3%, red <= -7%.", "lead", ratio(ark, spy))
    if "XLU" in col and "XLP" in col:
        dfn = [((u or 0) + (p or 0)) / 2 if u and p else None for u, p in zip(ratio(g("XLU"), spy), ratio(g("XLP"), spy))]
        dd20 = chg(dfn, 20)
        add("RA3", "Risk appetite", "Defensives vs S&P (avg XLU/SPY, XLP/SPY), 20-day change", dd20, "%",
            status_hi(dd20, 2, 4), "Amber: defensives outperform by >=2% in 20 sessions, red >=4% (flight to safety).",
            "coincident", dfn)

    # ---------- Scores ----------
    scored = [s for s in sig if s["status"] in ("green", "amber", "red")]
    pts = {"green": 0, "amber": 0.5, "red": 1}
    risk = 100.0 * sum(pts[s["status"]] for s in scored) / len(scored)
    leads = [s for s in scored if s["kind"] == "lead"]
    lead_score = 100.0 * sum(pts[s["status"]] for s in leads) / len(leads) if leads else None

    # ---------- Bottom checklist ----------
    chk = []

    def item(id_, name, status, now, rule):
        chk.append({"id": id_, "name": name, "status": status, "now": now, "rule": rule})

    if vts:
        w = [x for x in vts[-15:] if x]
        spiked = max(w) > 1.0
        st = "green" if spiked and vts[-1] < 1.0 else "amber" if vts[-1] >= 1.0 else "red"
        item("B1", "VIX term structure spikes above 1.0 then falls back", st, f"{vts[-1]:.3f} (15-day max {max(w):.3f})",
             "Green: >1.0 within 15 sessions and now <1.0. Amber: >1.0 now (panic underway). Red: no spike yet.")
    if vv:
        w = [x for x in vv[-15:] if x]
        pk = max(w)
        st = "green" if pk >= 120 and vv[-1] <= pk * 0.9 else "amber" if pk >= 120 else "red"
        item("B2", "VVIX spikes above 120 then fades", st, f"{vv[-1]:.1f} (15-day max {pk:.1f})",
             "Green: peak >=120 in 15 sessions and now >=10% below it. Amber: spiked, not fading. Red: no spike.")
    h5 = chg(hyg_ief, 5)
    lo10 = min(x for x in hyg_ief[-10:] if x)
    st = "green" if (h5 or 0) >= 0 and hyg_ief[-1] > lo10 * 1.002 else "red"
    item("B3", "Credit stops deteriorating (HYG/IEF)", st, f"5-day {h5:+.2f}%" if h5 is not None else "n/a",
         "Green: 5-day change >= 0 and above its 10-day low.")
    rec_below = any(x is not None and x < 0 for x in smh200_hist[-20:])
    st = "green" if smh200 is not None and smh200 > 0 and rec_below else "amber" if smh200 is not None and smh200 > 0 else "red"
    item("B4", "Semis hold or reclaim the 200-day average", st, f"SMH {smh200:+.1f}% vs 200-day" if smh200 is not None else "n/a",
         "Green: above after being below within 20 sessions (reclaim). Amber: still above, untested. Red: below.")
    if bsyms:
        wash = min(x for x in p50[-20:] if x is not None)
        st = "green" if wash < 20 and p50[-1] > 40 else "amber" if p50[-1] < 20 else "red"
        item("B5", "Breadth washout then thrust (% above 50-day)", st, f"{p50[-1]:.0f}% (20-day min {wash:.0f}%)",
             "Green: <20% within 20 sessions and now >40%. Amber: <20% now (washout). Red: no washout yet.")
    if tnx:
        st = "green" if (t20 is not None and t20 < 0) else "red"
        item("B8", "10-year yield falling", st, f"{tnx[-1]:.2f}% ({t20:+.0f}bp / 20d)" if t20 is not None else f"{tnx[-1]:.2f}%",
             "Green: 20-session change < 0.")
    if oil:
        st = "green" if oil[-1] < 95 else "amber" if oil[-1] < 100 else "red"
        item("B10", "Oil eases below $95", st, f"${oil[-1]:.2f}", "Green < $95, amber $95-100, red > $100.")
    manual = manual or {}
    prev_chk = {c["id"]: c for c in (prev or {}).get("bottom", [])}
    for mid, name in MANUAL_ITEMS.items():
        if mid in manual:
            st, note = manual[mid].get("status", "pending"), manual[mid].get("note", "")
        elif mid in prev_chk:
            st, note = prev_chk[mid]["status"], prev_chk[mid].get("now", "")
        else:
            st, note = "pending", "Judgment item: set it on the Signals page"
        item(mid, name, st, note, "Manual / news-based.")
    chk.sort(key=lambda c: int(c["id"][1:]))
    greens = sum(c["status"] == "green" for c in chk)

    # ---------- Regime ----------
    p50now = (p50[-1] if p50 else None) or 100
    if (vts and vts[-1] >= 1.0) or p50now < 20:
        regime = "Washout"
    elif risk >= 45:
        regime = "Risk-off"
    elif risk >= 25:
        regime = "Caution"
    else:
        regime = "Risk-on"
    risk_level = "High" if risk >= 45 else "Elevated" if risk >= 25 else "Low"
    bottom_level = "Bottom signals strong" if greens >= 6 else "Bottom forming" if greens >= 4 else "No bottom yet"

    # ---------- Watchlist trend ----------
    cov = []
    for s in watchlist:
        if s not in col:
            continue
        xs = col[s]
        w = [x for x in xs[-252:] if x]
        if not w:
            continue
        cov.append({"sym": s, "px": rnd(xs[-1]), "d1": rnd(chg(xs, 1), 1), "d20": rnd(chg(xs, 20), 1),
                    "vs50": rnd(pct(xs[-1], sma(xs, 50)), 1), "vs200": rnd(pct(xs[-1], sma(xs, 200)), 1),
                    "dd": rnd(pct(xs[-1], max(w)), 1)})

    # ---------- State changes vs prev ----------
    changes = []
    now_levels = {"regime": regime, "riskLevel": risk_level, "bottomLevel": bottom_level}
    if prev:
        pmap = {s["id"]: s for s in prev.get("signals", [])}
        for s in sig:
            p = pmap.get(s["id"])
            if p and p["status"] != s["status"]:
                changes.append({"id": s["id"], "name": s["name"], "from": p["status"], "to": s["status"]})
        for k, v in now_levels.items():
            if prev.get(k) != v:
                changes.append({"id": k, "name": k, "from": prev.get(k), "to": v})
        pc = {c["id"]: c["status"] for c in prev.get("bottom", [])}
        for c in chk:
            if c["id"] in pc and pc[c["id"]] != c["status"]:
                changes.append({"id": c["id"], "name": "Bottom: " + c["name"], "from": pc[c["id"]], "to": c["status"]})

    return {
        "asOf": asof, "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "regime": regime, "playbook": PLAYBOOK[regime], "riskScore": rnd(risk, 1), "leadScore": rnd(lead_score, 1),
        "riskLevel": risk_level, "bottomGreens": greens, "bottomTotal": len(chk), "bottomLevel": bottom_level,
        "signals": sig, "bottom": chk, "watchlist": cov, "changes": changes,
        "headlineChange": prev is not None and any(c["id"] in now_levels for c in changes),
        "dates": dates[-HIST:], "spy": spark(spy, 2), "basketSize": len(bsyms),
        "status": "unvalidated", "caveat": "Thresholds calibrated on one episode (Aug-Oct 2026). Inputs, not trades.",
    }


def run(s: Settings | None = None, prev: dict | None = None, manual: dict | None = None, bars=None) -> dict:
    s = s or get_settings()
    syms = sorted(set(MARKET + BASKET + s.theme.symbols + s.watchlist.symbols + ([s.theme.bellwether] if s.theme.bellwether else [])))
    bars = bars if bars is not None else datasrc.daily_bars(syms, period_days=760, s=s)
    S = closes_from_bars(bars)
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    if (now.hour, now.minute) < (16, 10):  # today's session is not closed yet: score the last close
        today = now.date().isoformat()
        S = {k: {d: c for d, c in v.items() if d != today} for k, v in S.items()}
    doc = compute(S, watchlist=s.watchlist.symbols, theme=s.theme.symbols, theme_name=s.theme.name,
                  bellwether=s.theme.bellwether, prev=prev, manual=manual)
    doc["missing"] = [x for x in syms if x not in S]
    return doc
