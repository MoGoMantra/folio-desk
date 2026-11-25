"""The data-source interface. Analytics code never calls a website directly: it asks for bars, a universe,
estimates or an option chain, and the registry (data/__init__.py) picks a provider from the settings.

Bars come back as {symbol: DataFrame[date index; open, high, low, close, volume]}, dates as tz-naive
pandas Timestamps (session dates), closes adjusted for splits and dividends where the source supports it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]


class DataError(RuntimeError):
    pass


class PriceProvider(Protocol):
    name: str

    def daily_bars(self, symbols: list[str], period_days: int = 760) -> dict[str, pd.DataFrame]:
        """Daily OHLCV for each symbol over roughly the last `period_days` calendar days. Missing symbols are omitted."""
        ...


@dataclass
class UniverseMember:
    symbol: str
    name: str
    sector: str            # GICS-style sector name (see SECTORS in sectors/rotation.py)
    industry: str = ""
    market_cap: float | None = None


@dataclass
class Estimates:
    """Consensus estimates for the next fiscal years. Any field may be None when the source lacks it."""
    eps_fy1: float | None = None
    eps_fy2: float | None = None
    rev_fy1: float | None = None
    rev_fy2: float | None = None
    n_analysts: int | None = None
    source: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class OptionRow:
    expiry: str            # YYYY-MM-DD
    dte: int
    strike: float
    kind: str              # "put" | "call"
    bid: float | None
    ask: float | None
    iv: float | None = None
    open_interest: float | None = None
    volume: float | None = None


def frame(rows: list[tuple], dates_first: bool = True) -> pd.DataFrame:
    """Build a bars frame from (date, open, high, low, close, volume) tuples."""
    df = pd.DataFrame(rows, columns=["date", *BAR_COLUMNS])
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.dropna(subset=["close"]).drop_duplicates("date", keep="last").set_index("date").sort_index()
    return df.astype(float)
