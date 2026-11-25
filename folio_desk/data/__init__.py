"""Provider registry: picks a source from the settings so analytics code stays source-agnostic.

Prices      : [data] price_providers in order; a paid provider is skipped when its key is blank. Symbols a
              provider returns nothing for fall through to the next one.
Universe    : FMP screener (if keyed) > Nasdaq screener (if allow_unofficial) > S&P 500 constituents
              (open dataset, GICS sectors, no market caps).
Estimates   : FMP (if keyed) > yfinance.
Options     : yfinance.
"""
from __future__ import annotations

import csv
import io
import logging

import httpx
import pandas as pd

from ..config import Settings, get_settings
from .base import DataError, Estimates, OptionRow, PriceProvider, UniverseMember
from .paid import FmpProvider, PolygonProvider, TiingoProvider
from .yahoo import YahooProvider

log = logging.getLogger(__name__)

SP500_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"

__all__ = ["DataError", "Estimates", "OptionRow", "UniverseMember", "price_providers", "daily_bars", "universe",
           "estimates", "option_chain"]


def price_providers(s: Settings | None = None) -> list[PriceProvider]:
    s = s or get_settings()
    d = s.data
    out: list[PriceProvider] = []
    for name in d.price_providers:
        if name == "yahoo":
            out.append(YahooProvider())
        elif name == "polygon" and d.polygon_api_key:
            out.append(PolygonProvider(d.polygon_api_key))
        elif name == "tiingo" and d.tiingo_api_key:
            out.append(TiingoProvider(d.tiingo_api_key))
        elif name == "fmp" and d.fmp_api_key:
            out.append(FmpProvider(d.fmp_api_key))
    if not out:
        out.append(YahooProvider())
    return out


def daily_bars(symbols: list[str], period_days: int = 760, s: Settings | None = None,
               providers: list[PriceProvider] | None = None) -> dict[str, pd.DataFrame]:
    left = list(dict.fromkeys(symbols))
    got: dict[str, pd.DataFrame] = {}
    for p in providers or price_providers(s):
        if not left:
            break
        try:
            res = p.daily_bars(left, period_days)
        except DataError as e:
            log.warning("%s: %s", p.name, e)
            continue
        got.update(res)
        left = [x for x in left if x not in got]
    return got


def sp500_members(transport: httpx.BaseTransport | None = None) -> list[UniverseMember]:
    with httpx.Client(timeout=30, transport=transport) as c:
        r = c.get(SP500_CSV)
        r.raise_for_status()
    rows = csv.DictReader(io.StringIO(r.text))
    return [UniverseMember(symbol=x["Symbol"].strip(), name=x.get("Security", "").strip(),
                           sector=x.get("GICS Sector", "").strip(), industry=x.get("GICS Sub-Industry", "").strip())
            for x in rows]


def universe(min_cap: float = 2e9, s: Settings | None = None) -> tuple[list[UniverseMember], str]:
    """Returns (members, source label)."""
    s = s or get_settings()
    if s.data.fmp_api_key:
        try:
            return FmpProvider(s.data.fmp_api_key).universe(min_cap), "FMP screener"
        except Exception as e:
            log.warning("FMP universe failed: %s", e)
    if s.data.allow_unofficial:
        try:
            from .unofficial import nasdaq_universe
            return nasdaq_universe(min_cap), "Nasdaq screener (unofficial)"
        except Exception as e:
            log.warning("Nasdaq universe failed: %s", e)
    return sp500_members(), "S&P 500 constituents (open dataset)"


def estimates(ticker: str, s: Settings | None = None) -> Estimates:
    s = s or get_settings()
    if s.data.fmp_api_key:
        try:
            return FmpProvider(s.data.fmp_api_key).estimates(ticker)
        except Exception as e:
            log.warning("FMP estimates failed for %s: %s", ticker, e)
    return YahooProvider().estimates(ticker)


def option_chain(ticker: str, kind: str = "put", min_dte: int = 30, max_dte: int = 130) -> list[OptionRow]:
    return YahooProvider().option_chain(ticker, kind, min_dte, max_dte)
