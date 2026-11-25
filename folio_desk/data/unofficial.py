"""Opt-in, unofficial sources. Off unless [data] allow_unofficial = true.

- Nasdaq's website screener (all US listings with market cap and sector). Undocumented; it can change or
  block automated requests at any time, and its terms of use apply to you. No browser impersonation is done:
  requests identify as folio-desk.
"""
from __future__ import annotations

import httpx

from .base import DataError, Estimates, UniverseMember

# Nasdaq's sector names -> the GICS-style names used across folio-desk
NASDAQ_TO_GICS = {
    "Technology": "Information Technology",
    "Finance": "Financials",
    "Health Care": "Health Care",
    "Consumer Discretionary": "Consumer Discretionary",
    "Industrials": "Industrials",
    "Telecommunications": "Communication Services",
    "Consumer Staples": "Consumer Staples",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Basic Materials": "Materials",
}


def _num(x):
    try:
        return float(str(x).replace("$", "").replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def nasdaq_universe(min_cap: float = 2e9, min_price: float = 2.0, transport: httpx.BaseTransport | None = None) -> list[UniverseMember]:
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true"
    with httpx.Client(timeout=90, transport=transport, headers={"User-Agent": "folio-desk (open-source research tool)",
                                                                "Accept": "application/json"}) as c:
        r = c.get(url)
        if r.status_code != 200:
            raise DataError(f"Nasdaq screener returned {r.status_code}; it blocks some automated clients. "
                            "Use the default S&P 500 universe or a paid provider instead.")
        rows = r.json()["data"]["rows"]
    out = []
    for row in rows:
        sym = (row.get("symbol") or "").strip()
        if not sym or "^" in sym or " " in sym:
            continue
        mc, px = _num(row.get("marketCap")), _num(row.get("lastsale"))
        if not mc or not px or mc < min_cap or px < min_price:
            continue
        sec = NASDAQ_TO_GICS.get(row.get("sector") or "")
        if not sec:
            continue
        out.append(UniverseMember(symbol=sym.replace("/", "."), name=row.get("name", "").strip(), sector=sec,
                                  industry=row.get("industry") or "", market_cap=mc))
    return out


def nasdaq_estimates(ticker: str, transport: httpx.BaseTransport | None = None) -> Estimates:
    """Annual EPS consensus (current and next fiscal year) from Nasdaq's analyst-forecast page data.
    EPS only: Nasdaq does not publish revenue consensus there."""
    url = f"https://api.nasdaq.com/api/analyst/{ticker.upper()}/earnings-forecast"
    with httpx.Client(timeout=30, transport=transport, headers={"User-Agent": "folio-desk (open-source research tool)",
                                                                "Accept": "application/json"}) as c:
        r = c.get(url)
        if r.status_code != 200:
            raise DataError(f"Nasdaq earnings forecast returned {r.status_code}")
        data = (r.json() or {}).get("data") or {}
    rows = ((data.get("yearlyForecast") or {}).get("rows")) or []
    eps = [_num(x.get("consensusEPSForecast")) for x in rows]
    n = [_num(x.get("noOfEstimates")) for x in rows]
    est = Estimates(source="nasdaq (unofficial)", raw={"rows": rows[:2]})
    if eps:
        est.eps_fy1 = eps[0]
        est.n_analysts = int(n[0]) if n and n[0] else None
    if len(eps) > 1:
        est.eps_fy2 = eps[1]
    return est
