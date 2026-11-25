"""Decision layer: one research call per name, combining the desks.

Inputs per name: the equity desk's priced levels (BUY / ACCUMULATE / TRIM) and reliability flags, the market
regime and its playbook, the 200-day trend, what you already hold, and the pre-trade risk check.

Output per name:
- action      BUY | ADD | HOLD | TRIM | SELL | AVOID | NO VIEW
- confidence  High | Medium | Low (each reliability issue lowers it one step)
- size        a suggested dollar amount for BUY / ADD, scaled by regime and confidence, inside your limits
- put idea    the best cash-secured put at or below ACCUMULATE, with its own risk check
- risk        the PASS / WARN / BLOCK verdict for the suggested trade
- reasons     every input that moved the call, in plain words

The rules are deliberately simple and written down (docs/decisions.md), so you can disagree with a specific
one. It is a research call for you to review, not an instruction: folio-desk never places orders.
"""
from __future__ import annotations

import datetime as dt

CONF_FACTOR = {"High": 1.0, "Medium": 0.6, "Low": 0.3}
STALE_DAYS = 120
AGING_DAYS = 60
STARTER = 1 / 3          # an ACCUMULATE starter is a third of the full size


def _age_days(as_of: str | None, today: dt.date) -> int | None:
    if not as_of:
        return None
    try:
        return (today - dt.date.fromisoformat(as_of[:10])).days
    except ValueError:
        return None


def decide(ticker: str, *, report: dict | None, price: float | None, regime: str | None, below200: bool | None,
           held_value: float, held_qty: float, portfolio_value: float, limits: dict, today: dt.date | None = None,
           is_fund: bool = False) -> dict:
    today = today or dt.date.today()
    if is_fund:  # index funds are judged by allocation, not by a single-company valuation
        return {"ticker": ticker, "held": held_qty > 0, "heldValue": held_value, "price": price, "regime": regime or "Risk-on",
                "levels": None, "reportAge": None, "action": "HOLD" if held_qty > 0 else "NO VIEW", "confidence": "n/a", "size": 0.0,
                "shares": 0, "fund": True, "issues": [],
                "reasons": ["A fund: size it by allocation, not valuation. Use Portfolio construction and the rebalancing bands on the Optimization page."]}
    reasons: list[str] = []
    issues: list[str] = []
    regime_ = regime or "Risk-on"
    if not regime:
        issues.append("no market-signals run: regime unknown")
    held = held_qty > 0
    sig = (report or {}).get("signal") or {}
    age = _age_days((report or {}).get("asOf"), today)
    px = price if price is not None else (report or {}).get("price")

    base = {"ticker": ticker, "held": held, "heldValue": held_value, "price": px, "regime": regime_,
            "levels": {k: sig.get(k) for k in ("fv", "buy", "acc", "trim")} if sig else None, "reportAge": age}
    if not report or not sig or age is None or age > STALE_DAYS:
        why = "no equity report on file" if not report else f"equity report is {age} days old (over {STALE_DAYS})"
        return base | {"action": "HOLD" if held else "NO VIEW", "confidence": "Low", "size": 0.0,
                       "reasons": [f"{why}: run the equity desk before acting."], "issues": [why]}

    label, fv, buy, acc, trim = sig["label"], sig["fv"], sig["buy"], sig["acc"], sig["trim"]
    if px is not None and px != report.get("price"):  # re-label at today's price with the stored levels
        label = "BUY" if px < buy else "ACCUMULATE" if px < acc else "TRIM" if px > trim else "HOLD"
    reasons.append(f"Equity desk: fair value ${fv:,.2f}; BUY < ${buy:,.2f}, ACCUMULATE < ${acc:,.2f}, TRIM > ${trim:,.2f}; "
                   f"price ${px:,.2f} reads {label}.")
    for f in sig.get("flags") or []:
        issues.append(f)
    if age > AGING_DAYS:
        issues.append(f"report is {age} days old")
    for p in (report.get("problems") or []):
        issues.append(f"validation: {p}")

    # ---- action
    if fv <= 0:
        action = "SELL" if held else "AVOID"
        reasons.append("The model gives no positive fair value.")
    elif label == "BUY":
        action = "ADD" if held else "BUY"
    elif label == "ACCUMULATE":
        action = "ADD" if held else "BUY"
        reasons.append("Between BUY and ACCUMULATE: a starter (a third of full size) at most.")
    elif label == "TRIM":
        if held and px > trim * 1.25:
            action = "SELL"
            reasons.append("Price is more than 25% above the TRIM level.")
        else:
            action = "TRIM" if held else "AVOID"
    else:
        action = "HOLD" if held else "AVOID"
        if not held:
            reasons.append("Fairly valued: no margin of safety to buy into.")

    # ---- regime overlay (posture, not picks)
    if action in ("BUY", "ADD"):
        if regime_ == "Risk-off":
            if held and below200:
                action = "HOLD"
                reasons.append("Risk-off and the stock is below its 200-day average: the playbook says don't average down.")
            else:
                reasons.append("Risk-off: new buys at reduced size, only at BUY-level prices.")
                if label != "BUY":
                    action = "HOLD" if held else "AVOID"
                    reasons.append("Price is above the BUY level, so wait in Risk-off.")
        elif regime_ == "Caution":
            reasons.append("Caution: stagger the buy in tranches.")
        elif regime_ == "Washout":
            reasons.append("Washout: contrarian zone; size re-entry by the bottom checklist.")
        if below200 and regime_ != "Risk-off":
            issues.append("below its 200-day average (trend against you)")

    confidence = ["High", "Medium", "Low"][min(2, len(issues))]

    # ---- size
    size = 0.0
    if action in ("BUY", "ADD") and portfolio_value > 0:
        mult = (limits.get("regimeMultiplier") or {}).get(regime_, 1.0)
        full = limits.get("maxPositionPct", 10.0) / 100 * portfolio_value * mult
        target = full * CONF_FACTOR[confidence] * (STARTER if label == "ACCUMULATE" else 1.0)
        size = max(0.0, target - held_value)
        reasons.append(f"Size: limit {limits.get('maxPositionPct', 10.0):g}% x regime {mult:g} x confidence {CONF_FACTOR[confidence]:g}"
                       + (" x starter 1/3" if label == "ACCUMULATE" else "") + f" = ${target:,.0f} target; ${held_value:,.0f} already held.")
        if size < 0.005 * portfolio_value:
            action = "HOLD"
            size = 0.0
            reasons.append("Already at or above the suggested size.")
    if action == "TRIM" and held:
        size = held_value * 0.25
        reasons.append("Trim: a quarter of the position as a starting point; the rest depends on your tax lots.")
    if action == "SELL" and held:
        size = held_value

    return base | {"action": action, "label": label, "confidence": confidence, "size": round(size, 2),
                   "shares": int(size // px) if px and action in ("BUY", "ADD", "TRIM", "SELL") else 0,
                   "reasons": reasons, "issues": issues}


def put_idea(report: dict | None, action: str, regime: str | None, limits: dict) -> dict | None:
    """The best cash-secured put at or below ACCUMULATE, when owning the stock there is consistent with the call."""
    if not report or action in ("TRIM", "SELL", "AVOID", "NO VIEW"):
        return None
    cands = ((report.get("options") or {}).get("candidates")) or []
    if not cands:
        return None
    prefer = [c for c in cands if c.get("belowBuy")] or cands
    c = max(prefer, key=lambda x: x["annYield"])
    return {"expiry": c["expiry"], "strike": c["strike"], "bid": c["bid"], "annYield": c["annYield"], "dte": c["dte"],
            "iv": c.get("iv"), "belowBuy": c.get("belowBuy", False),
            "why": ("Assignment would be at or below the BUY level." if c.get("belowBuy") else
                    "Assignment would be below ACCUMULATE but above BUY.") + " One contract obliges 100 shares."}
