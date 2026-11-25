"""Automatic levers: build a valuation model from collected data using the written lever rules
(docs/equity.md), so an equity run needs no human or AI judgment to produce a first signal.

Every lever records the rule that set it (model.rules). A reviewer (a person, or the Claude skill in
skills/equity-review) can override any lever; overrides must carry a reason (model.overrides) and the
validator checks the guard rails either way.

Auto mode simplifications, all stated in model.rules:
- One "Revenue" driver (segment XBRL is not standardised enough to split automatically).
- GAAP net margin basis, so no non-GAAP haircut. Peer forward P/Es are usually on non-GAAP consensus EPS,
  which makes the auto value conservative for companies with large stock comp or amortisation.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics as stats

from . import engine


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def _half(x):
    return round(x * 2) / 2


def _sum(rows, k):
    v = [r.get(k) for r in rows]
    return sum(v) if v and all(x is not None for x in v) else None


def fiscal_timing(fye: str | None, today: dt.date) -> tuple[dt.date, float]:
    """Next fiscal-year end on/after today (FY0) and years from today to the end of FY+1."""
    mm, dd = (int(fye[:2]), int(fye[2:])) if fye and len(fye) == 4 else (12, 31)
    dd = min(dd, 28) if mm == 2 else dd
    end = dt.date(today.year, mm, dd)
    if end < today:
        end = dt.date(today.year + 1, mm, dd)
    fy1_end = dt.date(end.year + 1, mm, dd)
    return end, max(0.25, (fy1_end - today).days / 365.25)


def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = math.floor(k)
    return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)


def build(c: dict, today: dt.date | None = None) -> tuple[dict, list[str]]:
    """Return (model, warnings) from a collect() document."""
    today = today or dt.date.today()
    rules: list[dict] = []
    warns: list[str] = []
    rule = lambda lever, why, value: rules.append({"lever": lever, "rule": why, "value": value})
    q = [r for r in c["sec"]["quarters"] if r.get("revenue")]
    if len(q) < 8:
        raise ValueError(f"need at least 8 quarters of XBRL revenue, found {len(q)}")
    last4, prior4 = q[-4:], q[-8:-4]
    ttm_rev = _sum(last4, "revenue") / 1e6
    ttm_ni = _sum(last4, "netIncome")
    if ttm_ni is None:
        raise ValueError("net income missing in the last 4 quarters")
    ttm_ni /= 1e6
    est = c.get("estimates") or {}

    # ---- fiscal timing and years
    fy0_end, yrs = fiscal_timing(c["sec"].get("fiscalYearEnd"), today)
    years = [f"FY{fy0_end.year + k}E" for k in range(5)]

    # ---- base sales and growth
    if est.get("revFY1"):
        base = est["revFY1"] / 1e6
        rule("Base sales", "current fiscal-year consensus revenue", f"${base:,.0f}mm")
    else:
        base = ttm_rev
        rule("Base sales", "trailing-4Q revenue (no consensus available)", f"${base:,.0f}mm")
    yoy = [q[i]["revenue"] / q[i - 4]["revenue"] - 1 for i in range(max(4, len(q) - 8), len(q)) if q[i - 4].get("revenue")]
    if est.get("revFY1") and est.get("revFY2"):
        g = est["revFY2"] / est["revFY1"] - 1
        rule("Base growth g", "consensus FY+1 revenue growth", f"{g:.1%}")
    elif yoy:
        g = stats.median(yoy[-4:])
        rule("Base growth g", "median of the last 4 quarterly YoY growth rates (no consensus)", f"{g:.1%}")
    else:
        g = 0.05
        rule("Base growth g", "default 5% (no consensus, too little history)", "5.0%")
    sd_g = stats.stdev(yoy) if len(yoy) >= 3 else abs(g) * 0.5
    mature = abs(g) < 0.05
    d = 0.0 if mature else max(0.25, 0.15 if g > 0.10 else 0.0)
    rule("Base decay d", "0 for mature (|g| < 5%); else 0.25 (FY+2 consensus not available to solve for it); floor 0.15 when g > 10%", d)
    g_bull, g_bear = g + sd_g, max(g - sd_g, -0.10)
    d_bull, d_bear = (0.0, 0.0) if mature else (0.8 * d, min(0.8, 2.4 * d))
    rule("Bull/bear g", "base +/- 1 standard deviation of the last 8 quarterly YoY rates, bear floor -10%", f"{g_bull:.1%} / {g_bear:.1%}")

    # ---- margins (GAAP net margin)
    qm = [r["netIncome"] / r["revenue"] for r in q[-8:] if r.get("netIncome") is not None]
    m_t4 = ttm_ni / ttm_rev
    p_ni = _sum(prior4, "netIncome")
    m_p4 = (p_ni / 1e6) / (_sum(prior4, "revenue") / 1e6) if p_ni is not None else m_t4
    step = (m_t4 - m_p4) / 2
    best = max(qm) if qm else m_t4
    m0 = m_t4
    m1 = m_t4 + step
    m2 = min(m1 + step, best + 0.02)
    sd_m = stats.stdev(qm) if len(qm) >= 3 else 0.015
    rule("Margins", "GAAP net margin: m0 = trailing 4Q; m1 = m0 + half the YoY change; m2 = m1 + the same step, capped at the best of the last 8 quarters + 2pp",
         f"{m0:.1%} / {m1:.1%} / {m2:.1%}")
    bull_m2 = m2 + max(0.015, sd_m)
    bear_m1, bear_m2 = m1 - 0.02, min(qm) if qm else m1 - 0.03
    rule("Bull/bear margins", "bull m2 = base m2 + max(1.5pp, 1 sd of 8Q margins); bear m1 = base m1 - 2pp; bear m2 = lowest of the last 8 quarters",
         f"bull m2 {bull_m2:.1%}; bear {bear_m1:.1%} / {bear_m2:.1%}")

    # ---- shares
    sh = [r.get("dilutedShares") for r in q if r.get("dilutedShares")]
    if not sh:
        raise ValueError("diluted share count missing")
    sh_base = sh[-1] / 1e6
    sh_g = max(-0.05, min(0.10, sh[-1] / sh[-5] - 1)) if len(sh) >= 5 else 0.0
    rule("Shares", "latest diluted count; growth = trailing-4Q net change (bear +1pp for unannounced dilution)", f"{sh_base:,.1f}mm, {sh_g:+.1%}/yr")

    # ---- cost of equity
    beta = c.get("price", {}).get("beta5yMonthly")
    if beta is None:
        beta = 1.0
        warns.append("beta unavailable: used 1.0")
    coe = _half(4.2 + beta * 5.5) / 100
    coe = min(0.11 if beta < 2 else 0.15, max(0.09, coe))
    rule("Cost of equity", "4.2% + beta x 5.5%, rounded to 0.5%, floor 9%, cap 11% (15% when beta >= 2)", f"{coe:.1%} (beta {beta})")

    # ---- DCF inputs
    capex0 = (_sum(last4, "capex") or 0) / 1e6
    da = (_sum(last4, "da") or 0) / 1e6 / ttm_rev if _sum(last4, "da") else 0.04
    nwc = lambda r: (r.get("receivables") or 0) + (r.get("inventory") or 0) - (r.get("payables") or 0)
    d_rev = (_sum(last4, "revenue") - _sum(prior4, "revenue")) / 1e6
    wc = (nwc(q[-1]) - nwc(q[-5])) / 1e6 / d_rev if d_rev > 0 else 0.05
    wc = max(0.0, min(0.25, wc))
    L = q[-1]
    debt = ((L.get("debtCurrent") or 0) + (L.get("debtLT") or 0)) / 1e6
    cash = ((L.get("cash") or 0) + (L.get("stInvest") or 0)) / 1e6
    net_debt = debt - cash
    ebitda = ((_sum(last4, "opIncome") or 0) + (_sum(last4, "da") or 0)) / 1e6
    wacc = coe - 0.01 if debt > 0 and ebitda > 0 and net_debt / ebitda < 2 else coe
    tg = [0.025, 0.03, 0.03] if mature else [0.03, 0.035, 0.04]
    rule("DCF", "capex grows with sales; D&A and working capital as % of sales from the trailing 4Q; WACC = CoE - 1pp when leverage is low; terminal growth 3/3.5/4% (2.5/3/3% mature)",
         f"D&A {da:.1%}, WC {wc:.1%}, WACC {wacc:.1%}")

    def path(gg, dd_):
        s, out = base, []
        for t in range(1, 5):
            s *= 1 + gg * (1 - dd_) ** (t - 1)
            out.append(s)
        return out
    capex = [[capex0 * x / base for x in path(gg, dd_)] for gg, dd_ in ((g_bear, d_bear), (g, d), (g_bull, d_bull))]
    capex[0] = [x * 0.9 for x in capex[0]]

    m = {
        "years": years, "valueYear": 2, "valueLabel": years[2], "basis": "GAAP net income",
        "drivers": [{"name": "Revenue", "base": base, "m0": m0, "sc": [
            {"g": g_bear, "d": d_bear, "m1": bear_m1, "m2": bear_m2},
            {"g": g, "d": d, "m1": m1, "m2": m2},
            {"g": g_bull, "d": d_bull, "m1": m1, "m2": bull_m2}]}],
        "corp": {"label": "none (company-level basis)", "base": 0.0, "g": [0, 0, 0]},
        "shares": {"base": sh_base, "g": [sh_g + 0.01, sh_g, sh_g]},
        "haircut": {"label": "none (GAAP basis)", "perShare": [0, 0, 0], "phase": 2},
        "mult": [10, 15, 18], "coe": coe, "beta": beta, "yrs": round(yrs, 2), "wt": [25, 50, 25],
        "dcf": {"capex0": capex0, "capex": capex, "da": [da] * 3, "wc": [wc] * 3, "wacc": [max(w_, t_ + 0.02) for w_, t_ in zip([wacc] * 3, tg)],
                "tg": tg, "netDebt": net_debt, "salesPrior": ttm_rev},
        "peers": c.get("peerSet") or [], "rules": rules, "overrides": [], "calibration": [],
    }

    # ---- exit multiple
    rb = engine.run(m, 1)
    eps = [y["econ"] for y in rb["Y"]]
    cagr = (eps[2] / eps[0]) ** 0.5 - 1 if eps[0] > 0 and eps[2] > 0 else None
    peers = c.get("peers") or []
    pes = [p["fwdPE"] for p in peers if p.get("fwdPE") and 0 < p["fwdPE"] <= 80]
    kind = "forward"
    if len(pes) < 3:  # consensus unavailable: fall back to trailing GAAP P/E computed from EDGAR
        pes = [p["trailingPE"] for p in peers if p.get("trailingPE") and 0 < p["trailingPE"] <= 80]
        kind = "trailing GAAP (from EDGAR; consensus unavailable)"
    pgs = [p["epsGrowthFY2"] for p in peers if p.get("epsGrowthFY2") is not None]
    own = c.get("ownPE") or {}
    if len(pes) >= 3:
        med = stats.median(pes)
        pg = stats.median(pgs) if pgs else None
        f = max(0.8, min(1.3, cagr / pg)) if cagr is not None and pg and pg > 0 else 1.0
        base_pe = med * f
        why = (f"peer median {kind} P/E {med:.1f}x x growth factor {f:.2f} (company EPS CAGR vs peer median EPS growth, clamped 0.8-1.3)"
               if pg else f"peer median {kind} P/E {med:.1f}x (no peer growth data, factor 1.0)")
        p75, p25 = _pct(pes, 0.75), _pct(pes, 0.25)
    elif own.get("usable"):
        base_pe, why, p75, p25 = own["medianPE"], "own median trailing GAAP P/E (fewer than 3 usable peers)", None, None
    else:
        base_pe, why, p75, p25 = 16.0, "default 16x (no usable peers and no usable own P/E history)", None, None
    g_after = eps[3] / eps[2] - 1 if eps[2] > 0 else 0
    caps = [("growth cap (PEG 1.0 on EPS growth after the value year)", max(12.0, 100 * g_after))]
    if own.get("usable"):
        caps.append(("own median trailing P/E", own["medianPE"]))
    bound = None
    for name, cv in caps:
        if base_pe > cv:
            base_pe, bound = cv, name
    base_pe = _half(base_pe)
    bull_pe = _half(min(base_pe * 1.3, max(base_pe * 1.2, p75 or 0)))
    bear_pe = _half(max(1.0, min(base_pe * 0.65, (p25 * 0.85) if p25 else base_pe * 0.65)))
    m["mult"] = [bear_pe, base_pe, bull_pe]
    rule("Exit P/E", why + (f"; capped by the {bound}" if bound else ""), f"{bear_pe}x / {base_pe}x / {bull_pe}x")

    # ---- calibration against consensus
    if est.get("epsFY1"):
        m["calibration"].append({"label": f"{years[0]} EPS", "model": _r(eps[0], 2), "ref": f"consensus {est['epsFY1']:.2f} (often non-GAAP)"})
    if est.get("epsFY2"):
        m["calibration"].append({"label": f"{years[1]} EPS", "model": _r(eps[1], 2), "ref": f"consensus {est['epsFY2']:.2f} (often non-GAAP)"})
        if est["epsFY2"] > 0 and abs(eps[1] / est["epsFY2"] - 1) > 0.10:
            warns.append(f"base {years[1]} EPS {eps[1]:.2f} is more than 10% from consensus {est['epsFY2']:.2f}; check GAAP vs non-GAAP before relying on it")
    return m, warns


def options_overlay(rows: list[dict], price: float, acc: float, buy: float, top: int = 5) -> dict:
    """Puts whose strike sits at or below the ACCUMULATE level: being assigned means buying at a price the
    model already likes. Annualised yield = bid / strike x 365 / days."""
    cands = []
    for r in rows:
        if r.get("kind", "put") != "put" or not r.get("bid") or r["strike"] > acc:
            continue
        y = r["bid"] / r["strike"] * 365 / max(r["dte"], 1)
        cands.append({**r, "annYield": round(y, 4), "belowBuy": r["strike"] <= buy, "otmPct": round(r["strike"] / price - 1, 4)})
    cands.sort(key=lambda x: -x["annYield"])
    verdict = ("No put strike at or below the ACCUMULATE level in the 30-130 day window." if not cands else
               f"{len(cands)} put strikes sit at or below ACCUMULATE (${acc:.2f}); best annualised yield {cands[0]['annYield']:.1%} "
               f"at ${cands[0]['strike']:.0f}, {cands[0]['expiry']}.")
    return {"candidates": cands[:top], "verdict": verdict}


def auto_report(c: dict, today: dt.date | None = None) -> dict:
    m, warns = build(c, today)
    price = c["price"]["price"]
    problems = engine.validate({"ticker": c["ticker"], "asOf": c["collectedAt"], "price": price, "model": m}, "auto", collect=c)
    sig = engine.signal(m, price)
    q = c["sec"]["quarters"]
    return {
        "schema": 2, "mode": "auto", "ticker": c["ticker"], "company": c["sec"].get("name"), "asOf": c["collectedAt"],
        "price": price, "priceDate": c["price"]["date"], "model": m,
        "signal": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in sig.items()},
        "headline": f"{sig['label']}: fair value ${sig['fv']:.2f} vs ${price:.2f} (auto levers; review before acting).",
        "options": options_overlay((c.get("options") or {}).get("rows", []), price, sig["acc"], sig["buy"]),
        "history": {"quarters": [r["end"] for r in q], "revenue": [r.get("revenue") for r in q],
                    "netMargin": [(r["netIncome"] / r["revenue"]) if r.get("netIncome") is not None and r.get("revenue") else None for r in q]},
        "insiders": c["sec"].get("insiders"), "bigDays": c["price"].get("bigDays"), "ownPE": c.get("ownPE"),
        "warnings": (c.get("warnings") or []) + warns, "problems": problems,
        "disclaimer": "Research output from automatic rules, not investment advice.",
    }
