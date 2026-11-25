"""Portfolio optimization from daily closes, with honest defaults.

Methods
- "risk_parity": each holding contributes the same share of portfolio volatility (needs no return forecast).
- "min_variance": lowest volatility mix within the weight caps (needs no return forecast).
- "max_sharpe": highest historical Sharpe ratio, with each asset's mean return shrunk 50% toward the cross-
  sectional average. Historical means are noisy, so this is the least reliable method; treat it as a what-if.
All methods respect per-asset minimum and maximum weights and sum to 100%.

Rebalancing bands: trade a holding back to target when it drifts more than `abs_band` percentage points or
more than `rel_band` of its target (the "5/25" rule by default).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def estimates(closes: pd.DataFrame, lookback_years: float = 5.0) -> tuple[np.ndarray, np.ndarray, list[str], dict]:
    px = closes.dropna(how="any")
    px = px[px.index >= px.index[-1] - pd.Timedelta(days=int(lookback_years * 365.25))]
    r = np.log(px).diff().dropna()
    if len(r) < 120:
        raise ValueError("need at least ~6 months of overlapping daily prices for every holding")
    mu = r.mean().to_numpy() * 252
    cov = r.cov().to_numpy() * 252
    return mu, cov, list(px.columns), {"from": px.index[0].date().isoformat(), "to": px.index[-1].date().isoformat(), "days": len(r)}


def _risk_contrib(w, cov):
    pv = math.sqrt(w @ cov @ w)
    return w * (cov @ w) / pv if pv else np.zeros_like(w)


def optimize(closes: pd.DataFrame, method: str = "risk_parity", min_w: float = 0.0, max_w: float = 1.0,
             lookback_years: float = 5.0, rf: float = 0.0, shrink: float = 0.5) -> dict:
    mu, cov, names, window = estimates(closes, lookback_years)
    n = len(names)
    if n * max_w < 1 - 1e-9 or n * min_w > 1 + 1e-9:
        raise ValueError("weight caps make 100% impossible: widen min/max weight")
    bounds = [(min_w, max_w)] * n
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    x0 = np.full(n, 1 / n)
    if method == "risk_parity":
        obj = lambda w: float(np.sum((_risk_contrib(w, cov) / max(math.sqrt(w @ cov @ w), 1e-12) - 1 / n) ** 2))
    elif method == "min_variance":
        obj = lambda w: float(w @ cov @ w)
    elif method == "max_sharpe":
        mu_s = (1 - shrink) * mu + shrink * mu.mean()
        obj = lambda w: -float((w @ mu_s - rf) / max(math.sqrt(w @ cov @ w), 1e-12))
    else:
        raise ValueError(f"unknown method {method}")
    res = minimize(obj, x0, method="SLSQP", bounds=bounds, constraints=cons, options={"maxiter": 500, "ftol": 1e-12})
    w = np.clip(res.x, min_w, max_w)
    w = w / w.sum()
    vol = math.sqrt(w @ cov @ w)
    rc = _risk_contrib(w, cov) / vol if vol else np.zeros(n)
    return {"method": method, "weights": dict(zip(names, map(float, w))), "riskShare": dict(zip(names, map(float, rc))),
            "vol": vol, "histReturn": float(w @ mu), "window": window, "converged": bool(res.success),
            "assetVol": dict(zip(names, map(float, np.sqrt(np.diag(cov))))),
            "corr": {"names": names, "matrix": np.round(cov / np.outer(np.sqrt(np.diag(cov)), np.sqrt(np.diag(cov))), 3).tolist()},
            "caveat": "Optimised on past prices. Correlations and volatility shift, and past returns are a weak guide to future returns."}


def rebalance(current: dict[str, float], target: dict[str, float], total_value: float, abs_band: float = 0.05,
              rel_band: float = 0.25) -> dict:
    """current / target: weights (fractions). Returns the holdings outside their band and the trades to fix them."""
    rows, trades = [], []
    for t in sorted(set(current) | set(target)):
        c, g = current.get(t, 0.0), target.get(t, 0.0)
        band = min(abs_band, rel_band * g) if g > 0 else abs_band
        out = abs(c - g) > band
        rows.append({"ticker": t, "current": c, "target": g, "drift": c - g, "band": band, "outside": out})
        if out:
            trades.append({"ticker": t, "side": "sell" if c > g else "buy", "amount": abs(c - g) * total_value})
    return {"rows": rows, "trades": trades, "rule": f"trade when drift exceeds {abs_band:.0%} points or {rel_band:.0%} of target, whichever is tighter"}
