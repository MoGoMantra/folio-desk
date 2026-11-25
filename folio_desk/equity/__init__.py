"""Equity desk: collect -> automatic levers -> valuation engine -> signal and options overlay."""
from __future__ import annotations

from ..config import Settings, get_settings
from .autolevers import auto_report
from .collect import collect


def run(ticker: str, peers: list[str] | None = None, outdir=None, s: Settings | None = None) -> dict:
    s = s or get_settings()
    c = collect(ticker, peers, outdir, s)
    return auto_report(c)


__all__ = ["run", "collect", "auto_report"]
