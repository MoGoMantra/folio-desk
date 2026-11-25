# Data sources

Analytics code never calls a website directly. It asks the data layer (`folio_desk/data`) for bars, a
universe, estimates or an option chain, and the registry picks a provider from `folio-desk.toml`.

| Need | Order tried |
|---|---|
| Daily prices | `[data] price_providers` in order (paid ones only when their key is set); symbols a provider misses fall through to the next |
| Universe | FMP screener (keyed) → Nasdaq website screener (only if `allow_unofficial = true`) → S&P 500 constituents (open dataset, GICS sectors) |
| Estimates | FMP (keyed) → yfinance → Nasdaq analyst forecast (only if `allow_unofficial = true`; EPS only) |
| Option chains | yfinance |
| Fundamentals, filings, Form 4 | SEC EDGAR only |

## Notes per source

- **SEC EDGAR** is the primary source. Its fair-access policy requires a User-Agent with your name and email
  and at most 10 requests per second; folio-desk refuses to call EDGAR without `[sec] user_agent` and stays
  under 7 per second.
- **yfinance** is a community library over Yahoo Finance's public web endpoints, not an official API. It can
  lag, change or rate-limit. Estimates and option chains need a Yahoo session cookie; on some networks that
  fails, and equity runs then fall back to trailing growth and EDGAR-based peer P/Es (the report says so).
- **Nasdaq's website screener** is undocumented and can block automated requests. It is off by default.
  folio-desk does not impersonate a browser.
- **Paid providers** (Polygon, Tiingo, FMP) follow each vendor's public docs. Their terms of use apply to you.

## Why consensus matters

The equity desk's exit multiple is anchored on peers' forward P/E (price ÷ consensus EPS). Without consensus
it falls back to trailing GAAP P/Es from EDGAR, which one-off gains and losses distort (a peer with a large
investment gain looks cheap, dragging the median down). Reports built on that fallback are marked
PROVISIONAL: fair value and levels are shown for reference, but there is no BUY / TRIM call and the
Decisions page shows NO VIEW. Even forward consensus can carry one-offs (a year whose EPS includes a gain),
so check the peer table in a review.

## Adding a provider

Implement `daily_bars(symbols, period_days) -> {symbol: DataFrame[open, high, low, close, volume]}` (and
optionally `universe` / `estimates`), then register it in `folio_desk/data/__init__.py`.
