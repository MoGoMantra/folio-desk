"""Optional paid providers. Each is used only when its API key is set and it is listed in
[data] price_providers. Endpoints follow each vendor's public documentation; responses are mapped onto the
same bars / universe / estimates shapes as the free source.
"""
from __future__ import annotations

import datetime as dt
import logging

import httpx
import pandas as pd

from .base import DataError, Estimates, UniverseMember, frame

log = logging.getLogger(__name__)


class _Http:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.c = httpx.Client(timeout=30, transport=transport)

    def json(self, url: str, params: dict):
        r = self.c.get(url, params=params)
        if r.status_code == 401 or r.status_code == 403:
            raise DataError(f"{url}: API key rejected ({r.status_code})")
        r.raise_for_status()
        return r.json()


class PolygonProvider(_Http):
    """Polygon.io aggregates: GET /v2/aggs/ticker/{t}/range/1/day/{from}/{to}"""
    name = "polygon"

    def __init__(self, api_key: str, transport=None):
        super().__init__(transport)
        self.key = api_key

    def daily_bars(self, symbols: list[str], period_days: int = 760) -> dict[str, pd.DataFrame]:
        to = dt.date.today()
        frm = to - dt.timedelta(days=period_days)
        out = {}
        for s in symbols:
            try:
                j = self.json(f"https://api.polygon.io/v2/aggs/ticker/{s}/range/1/day/{frm}/{to}",
                              {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": self.key})
                rows = [(pd.to_datetime(b["t"], unit="ms"), b["o"], b["h"], b["l"], b["c"], b.get("v", 0)) for b in j.get("results") or []]
                if rows:
                    out[s] = frame(rows)
            except DataError:
                raise
            except Exception as e:
                log.warning("polygon %s: %s", s, e)
        return out


class TiingoProvider(_Http):
    """Tiingo end-of-day: GET /tiingo/daily/{t}/prices"""
    name = "tiingo"

    def __init__(self, api_key: str, transport=None):
        super().__init__(transport)
        self.key = api_key

    def daily_bars(self, symbols: list[str], period_days: int = 760) -> dict[str, pd.DataFrame]:
        frm = (dt.date.today() - dt.timedelta(days=period_days)).isoformat()
        out = {}
        for s in symbols:
            try:
                j = self.json(f"https://api.tiingo.com/tiingo/daily/{s.replace('.', '-')}/prices",
                              {"startDate": frm, "token": self.key})
                rows = [(b["date"][:10], b["adjOpen"], b["adjHigh"], b["adjLow"], b["adjClose"], b.get("adjVolume", 0)) for b in j]
                if rows:
                    out[s] = frame(rows)
            except DataError:
                raise
            except Exception as e:
                log.warning("tiingo %s: %s", s, e)
        return out


class FmpProvider(_Http):
    """Financial Modeling Prep: daily prices, a stock screener universe, and analyst estimates."""
    name = "fmp"
    base = "https://financialmodelingprep.com/api/v3"

    def __init__(self, api_key: str, transport=None):
        super().__init__(transport)
        self.key = api_key

    def daily_bars(self, symbols: list[str], period_days: int = 760) -> dict[str, pd.DataFrame]:
        frm = (dt.date.today() - dt.timedelta(days=period_days)).isoformat()
        out = {}
        for s in symbols:
            try:
                j = self.json(f"{self.base}/historical-price-full/{s}", {"from": frm, "apikey": self.key})
                rows = [(b["date"], b["open"], b["high"], b["low"], b.get("adjClose", b["close"]), b.get("volume", 0))
                        for b in j.get("historical") or []]
                if rows:
                    out[s] = frame(rows)
            except DataError:
                raise
            except Exception as e:
                log.warning("fmp %s: %s", s, e)
        return out

    def universe(self, min_cap: float = 2e9) -> list[UniverseMember]:
        j = self.json(f"{self.base}/stock-screener", {"marketCapMoreThan": int(min_cap), "country": "US",
                                                      "isEtf": "false", "isActivelyTrading": "true", "limit": 10000, "apikey": self.key})
        return [UniverseMember(symbol=r["symbol"], name=r.get("companyName", ""), sector=r.get("sector") or "",
                               industry=r.get("industry") or "", market_cap=r.get("marketCap")) for r in j]

    def estimates(self, ticker: str) -> Estimates:
        j = self.json(f"{self.base}/analyst-estimates/{ticker}", {"period": "annual", "limit": 4, "apikey": self.key})
        today = dt.date.today().isoformat()
        fut = sorted([r for r in j if r.get("date", "") >= today], key=lambda r: r["date"])
        est = Estimates(source="fmp", raw={"rows": fut[:2]})
        if fut:
            est.eps_fy1, est.rev_fy1 = fut[0].get("estimatedEpsAvg"), fut[0].get("estimatedRevenueAvg")
            est.n_analysts = fut[0].get("numberAnalystsEstimatedEps")
        if len(fut) > 1:
            est.eps_fy2, est.rev_fy2 = fut[1].get("estimatedEpsAvg"), fut[1].get("estimatedRevenueAvg")
        return est
