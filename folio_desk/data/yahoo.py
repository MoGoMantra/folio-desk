"""Free default source: the yfinance library.

yfinance is community-maintained and reads Yahoo Finance's public web endpoints; it is not an official
Yahoo API, so it can lag, change or rate-limit. Check anything important against your broker.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

import pandas as pd

from .base import BAR_COLUMNS, Estimates, OptionRow

log = logging.getLogger(__name__)
_SHARE_CLASS = re.compile(r"^[A-Z]{1,5}\.[A-Z]$")


def ysym(symbol: str) -> str:
    """Yahoo writes share classes with a dash (BRK.B -> BRK-B); indexes and futures keep their dots (DX-Y.NYB)."""
    return symbol.replace(".", "-") if _SHARE_CLASS.match(symbol) else symbol


class YahooProvider:
    name = "yahoo"

    def __init__(self, chunk: int = 100):
        self.chunk = chunk

    def daily_bars(self, symbols: list[str], period_days: int = 760) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        out: dict[str, pd.DataFrame] = {}
        start = (dt.date.today() - dt.timedelta(days=period_days)).isoformat()
        ysyms = [ysym(s) for s in symbols]
        back = dict(zip(ysyms, symbols))
        for i in range(0, len(ysyms), self.chunk):
            part = ysyms[i:i + self.chunk]
            try:
                raw = yf.download(part, start=start, auto_adjust=True, progress=False, threads=True, group_by="ticker")
            except Exception as e:  # network, rate limit
                log.warning("yfinance download failed for %d symbols: %s", len(part), e)
                continue
            for ys in part:
                try:
                    df = raw[ys] if isinstance(raw.columns, pd.MultiIndex) else raw
                except KeyError:
                    continue
                df = df.rename(columns=str.lower)
                if "close" not in df:
                    continue
                df = df[[c for c in BAR_COLUMNS if c in df]].dropna(subset=["close"])
                if df.empty:
                    continue
                df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                out[back[ys]] = df.astype(float)
        return out

    def estimates(self, ticker: str) -> Estimates:
        import yfinance as yf

        t = yf.Ticker(ysym(ticker))
        est = Estimates(source="yahoo")
        try:
            e = t.earnings_estimate  # rows "0q","+1q","0y","+1y"; column "avg", "numberOfAnalysts"
            if e is not None and not e.empty:
                est.eps_fy1 = _num(e.loc["0y", "avg"]) if "0y" in e.index else None
                est.eps_fy2 = _num(e.loc["+1y", "avg"]) if "+1y" in e.index else None
                est.n_analysts = int(e.loc["0y", "numberOfAnalysts"]) if "0y" in e.index else None
            r = t.revenue_estimate
            if r is not None and not r.empty:
                est.rev_fy1 = _num(r.loc["0y", "avg"]) if "0y" in r.index else None
                est.rev_fy2 = _num(r.loc["+1y", "avg"]) if "+1y" in r.index else None
        except Exception as ex:
            log.warning("yfinance estimates unavailable for %s: %s", ticker, ex)
        return est

    def option_chain(self, ticker: str, kind: str = "put", min_dte: int = 30, max_dte: int = 130) -> list[OptionRow]:
        import yfinance as yf

        t = yf.Ticker(ysym(ticker))
        today = dt.date.today()
        rows: list[OptionRow] = []
        for exp in t.options or []:
            d = dt.date.fromisoformat(exp)
            dte = (d - today).days
            if not (min_dte <= dte <= max_dte):
                continue
            try:
                ch = t.option_chain(exp)
            except Exception as ex:
                log.warning("option chain %s %s: %s", ticker, exp, ex)
                continue
            tbl = ch.puts if kind == "put" else ch.calls
            for _, r in tbl.iterrows():
                rows.append(OptionRow(expiry=exp, dte=dte, strike=float(r["strike"]), kind=kind, bid=_num(r.get("bid")),
                                      ask=_num(r.get("ask")), iv=_num(r.get("impliedVolatility")),
                                      open_interest=_num(r.get("openInterest")), volume=_num(r.get("volume"))))
        return rows


def _num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None
