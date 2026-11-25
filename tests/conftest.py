"""Deterministic synthetic market data so the suite runs offline and repeatably (fixed seeds)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from folio_desk import db
from folio_desk.config import Settings, set_settings


def walk(n: int, seed: int, drift: float = 0.0003, vol: float = 0.012, start: float = 100.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return start * np.exp(np.cumsum(rng.normal(drift, vol, n)))


@pytest.fixture
def dates():
    return pd.bdate_range("2024-01-02", periods=420)


def bars_from(close: np.ndarray, idx, vol0: float = 1e6, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 7)
    hi = close * (1 + np.abs(rng.normal(0, 0.005, len(close))))
    lo = close * (1 - np.abs(rng.normal(0, 0.005, len(close))))
    return pd.DataFrame({"open": close, "high": hi, "low": lo, "close": close,
                         "volume": vol0 * (1 + rng.random(len(close)))}, index=idx)


@pytest.fixture
def market_bars(dates):
    from folio_desk.signals.market import BASKET, MARKET
    syms = sorted(set(MARKET + BASKET + ["NVDA", "AVGO", "AMD", "TSM", "MSFT", "META", "AAPL", "JNJ"]))
    out = {}
    for k, s in enumerate(syms):
        start = {"^VIX": 15, "^VIX3M": 17, "^VVIX": 90, "^TNX": 4.2, "CL=F": 75, "DX-Y.NYB": 100}.get(s, 100)
        vol = 0.003 if s.startswith("^") or s in ("DX-Y.NYB",) else 0.012
        out[s] = bars_from(walk(len(dates), 100 + k, 0.0002, vol, start), dates, seed=k)
    return out


@pytest.fixture
def mem_db():
    db.init_db(":memory:")
    set_settings(Settings())
    yield
    db._Session = None
