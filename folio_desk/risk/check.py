"""Pre-trade risk check: a proposed trade is checked against your written limits and comes back PASS, WARN or
BLOCK, rule by rule. Every check is stored with a fingerprint of exactly what was checked, and register
entries can point at the check that cleared them.

The limits are yours to set (Risk page or PUT /api/risk/limits). The defaults are starting points taken from a
regime-scaled risk budget: the market regime from the signals desk scales size limits and the maximum put
delta, so the same trade can PASS in Risk-on and BLOCK in Risk-off.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math

DEFAULT_LIMITS = {
    "maxPositionPct": 10.0,              # one name, % of portfolio value (shares + short-put assignment notional)
    "maxClusterPct": 25.0,               # one cluster of correlated names, % of portfolio value
    "clusters": {},                      # {"AI capex": ["MU", "AMD", ...]}
    "maxShortPutNotionalPct": 50.0,      # all short puts' assignment notional, % of portfolio value
    "regimeMultiplier": {"Risk-on": 1.0, "Caution": 0.75, "Risk-off": 0.5, "Washout": 0.75},
    "putDeltaMax": {"Risk-on": 0.30, "Caution": 0.25, "Risk-off": 0.20, "Washout": 0.30},
    "requireStrikeAtOrBelowAccumulate": True,
    "blockPutsSpanningEarningsAboveAccumulate": True,
    "noAveragingDownInRiskOff": True,
    "cashSecuredPuts": True,
    "minCashPct": 0.0,
}

PASS, WARN, BLOCK, SKIP = "PASS", "WARN", "BLOCK", "SKIP"


def merged_limits(user: dict | None) -> dict:
    out = json.loads(json.dumps(DEFAULT_LIMITS))
    for k, v in (user or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "clusters":
            out[k].update(v)
        else:
            out[k] = v
    return out


def put_delta(spot: float, strike: float, dte: int, iv: float, r: float = 0.042) -> float:
    """Absolute Black-Scholes put delta."""
    T = max(dte, 1) / 365
    d1 = (math.log(spot / strike) + (r + iv * iv / 2) * T) / (iv * math.sqrt(T))
    return abs(0.5 * (1 + math.erf(d1 / math.sqrt(2))) - 1)


def fingerprint(proposal: dict, limits: dict, ctx_summary: dict) -> str:
    blob = json.dumps({"p": proposal, "l": limits, "c": ctx_summary}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def check(p: dict, ctx: dict, limits: dict | None = None, today: dt.date | None = None) -> dict:
    """p: {account, ticker, asset, side, qty, price, opt_kind, strike, expiry, iv?}
    ctx: {portfolioValue, cash{account: $}, exposure{ticker: $ of shares + short-put notional},
          shortPutNotional, regime, spot, below200 (bool|None), report{acc, buy, label}|None, earningsDate|None}"""
    L = merged_limits(limits)
    today = today or dt.date.today()
    regime = ctx.get("regime") or "Risk-on"
    no_regime = not ctx.get("regime")
    mult = L["regimeMultiplier"].get(regime, 1.0)
    pv = float(ctx.get("portfolioValue") or 0)
    t = p["ticker"].upper()
    is_opt = p.get("asset") == "option"
    short_put = is_opt and p.get("opt_kind") == "put" and p["side"] == "sell"
    adds_risk = (p["side"] == "buy" and not is_opt) or short_put
    qty = float(p["qty"])
    m = 100.0 if is_opt else 1.0
    new_exposure = qty * m * (float(p["strike"]) if short_put else float(p["price"])) if adds_risk else 0.0
    rules = []
    rule = lambda id_, name, status, detail: rules.append({"id": id_, "name": name, "status": status, "detail": detail})
    if no_regime and adds_risk:
        rule("R0", "Market regime", WARN, "No market-signals run on file: limits are not regime-scaled (Risk-on values used). Run the signals desk.")

    # R1 single-name size
    if adds_risk and pv > 0:
        cap = L["maxPositionPct"] * mult
        after = (ctx.get("exposure", {}).get(t, 0.0) + new_exposure) / pv * 100
        rule("R1", "Single-name size", BLOCK if after > cap else PASS,
             f"{t} would be {after:.1f}% of the portfolio (shares + short-put notional); limit {cap:.1f}% ({L['maxPositionPct']}% x {mult} for {regime}).")
    elif adds_risk:
        rule("R1", "Single-name size", WARN, "Portfolio value unknown: log deposits or positions so size can be checked.")
    # R2 cluster
    clusters = [c for c, names in (L.get("clusters") or {}).items() if t in [x.upper() for x in names]]
    for c in clusters:
        if adds_risk and pv > 0:
            names = [x.upper() for x in L["clusters"][c]]
            cur = sum(v for k, v in ctx.get("exposure", {}).items() if k in names)
            after = (cur + new_exposure) / pv * 100
            cap = L["maxClusterPct"] * mult
            rule("R2", f"Cluster: {c}", BLOCK if after > cap else PASS, f"{c} would be {after:.1f}% of the portfolio; limit {cap:.1f}%.")
    # R3 total short-put assignment exposure
    if short_put and pv > 0:
        cap = L["maxShortPutNotionalPct"] * mult
        after = (float(ctx.get("shortPutNotional") or 0) + new_exposure) / pv * 100
        rule("R3", "Total short-put assignment exposure", BLOCK if after > cap else PASS,
             f"All short puts would oblige ${float(ctx.get('shortPutNotional') or 0) + new_exposure:,.0f} of purchases = {after:.1f}% of the portfolio; limit {cap:.1f}%.")
    # R4 put delta by regime
    if short_put:
        dmax = L["putDeltaMax"].get(regime, 0.30)
        iv, spot = p.get("iv"), ctx.get("spot")
        if iv and spot and p.get("expiry"):
            dte = (dt.date.fromisoformat(p["expiry"]) - today).days
            d = put_delta(float(spot), float(p["strike"]), dte, float(iv))
            rule("R4", "Put delta", BLOCK if d > dmax else PASS, f"Delta {d:.2f} at IV {float(iv):.0%}, {dte} days; limit {dmax:.2f} in {regime}.")
        else:
            rule("R4", "Put delta", WARN, "Need the option's implied volatility and the stock price to compute delta.")
    # R5 strike vs ACCUMULATE level
    rep = ctx.get("report")
    if short_put and L["requireStrikeAtOrBelowAccumulate"]:
        if rep and rep.get("acc"):
            ok = float(p["strike"]) <= float(rep["acc"])
            rule("R5", "Strike at or below ACCUMULATE", PASS if ok else BLOCK,
                 f"Strike ${float(p['strike']):.2f} vs ACCUMULATE ${float(rep['acc']):.2f} from the equity desk ({rep.get('label', '')}).")
        else:
            rule("R5", "Strike at or below ACCUMULATE", WARN, f"No equity report on file for {t}: run one so the strike can be checked against a fair value.")
    if p["side"] == "buy" and not is_opt and rep and rep.get("trim") and float(p["price"]) > float(rep["trim"]):
        rule("R5b", "Buying above TRIM", WARN, f"Price ${float(p['price']):.2f} is above the TRIM level ${float(rep['trim']):.2f}.")
    # R6 earnings inside the option's life
    if short_put and L["blockPutsSpanningEarningsAboveAccumulate"]:
        e = ctx.get("earningsDate")
        if not e:
            rule("R6", "Earnings before expiry", WARN, "Next earnings date unknown: check it before selling a put across it.")
        elif today.isoformat() <= e <= p["expiry"]:
            below = rep and rep.get("acc") and float(p["strike"]) <= float(rep["acc"])
            rule("R6", "Earnings before expiry", PASS if below else BLOCK,
                 f"Earnings on {e} fall before expiry {p['expiry']}" + ("; strike is at or below ACCUMULATE, allowed." if below else "; only allowed with the strike at or below ACCUMULATE."))
        else:
            rule("R6", "Earnings before expiry", PASS, f"Next earnings {e} are after expiry.")
    # R7 cash
    cash = float((ctx.get("cash") or {}).get(p.get("account", "T"), 0))
    if short_put and L["cashSecuredPuts"]:
        need = float(ctx.get("accountShortPutNotional") or 0) + new_exposure
        rule("R7", "Cash secured", PASS if cash >= need else BLOCK, f"Account cash ${cash:,.0f} vs ${need:,.0f} of short-put obligations including this one.")
    elif p["side"] == "buy":
        cost = qty * m * float(p["price"])
        floor = L["minCashPct"] / 100 * pv
        rule("R7", "Cash available", PASS if cash - cost >= floor else BLOCK if cash - cost < 0 else WARN,
             f"Account cash ${cash:,.0f}; this costs ${cost:,.0f}" + (f"; floor ${floor:,.0f}" if floor else "") + ".")
    # R8 averaging down into a broken trend in Risk-off
    if adds_risk and L["noAveragingDownInRiskOff"] and regime == "Risk-off" and ctx.get("below200") and ctx.get("exposure", {}).get(t, 0) > 0:
        rule("R8", "No averaging down in Risk-off", BLOCK, f"{t} is below its 200-day average and already held; the Risk-off playbook says don't add.")
    elif adds_risk and regime == "Risk-off" and ctx.get("below200") is None:
        rule("R8", "No averaging down in Risk-off", WARN, "200-day trend unknown.")

    statuses = {r["status"] for r in rules}
    verdict = BLOCK if BLOCK in statuses else WARN if WARN in statuses else PASS
    summary = {"regime": regime, "multiplier": mult, "portfolioValue": pv, "newExposure": new_exposure}
    return {"verdict": verdict, "rules": rules, "context": summary, "limits": L,
            "fingerprint": fingerprint(p, L, summary), "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "note": "Risk check against your own limits. It does not place orders; you decide."}
