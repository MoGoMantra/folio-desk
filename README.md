# folio-desk

An open-source research and portfolio desk for individual investors. It runs on your own machine and turns
public data (SEC EDGAR filings and market prices) into market signals, equity and sector research, and
portfolio analysis, with a web interface on top.

> **Research software, not investment advice.** folio-desk reads public data and does arithmetic. It does not
> know your situation, it cannot see the future, and its signals have limited or no validated track record
> (each module says which). It never places orders. Check anything important against your broker and the
> filings, and talk to a licensed professional if you need advice.

## What it does

| Desk | What you get | Status |
|---|---|---|
| **Market signals** | ~20 signals in six layers (breadth, leadership, credit, volatility, macro, risk appetite), a top-risk score, a regime with a posture playbook, a 10-item bottom checklist, watchlist trends | Ported; thresholds **unvalidated** beyond one episode |
| **Sector research** | Sector rotation (equal-weight and ETF views, confirmation and leading flags, candidate lists, a backtest re-scored every run) and a multi-week drawdown screen | Ported; rotation **unvalidated** (describes rotation, does not yet forecast it) |
| **Equity research** | EDGAR-first collection (12 XBRL quarters, filings text, Form 4s), automatic valuation levers from written rules, bear/base/bull fair value, BUY / ACCUMULATE / HOLD / TRIM levels, DCF cross-check, a cash-secured-put overlay | Ported; automatic levers are new and need review |
| **Portfolio construction** | Multi-account (taxable / traditional / Roth) model builder, backtests with rebalancing and contributions, stress windows, tax-placement checks | Ported |
| **Trading register** | Stock and option legs, rolls, assignments, thesis and invalidation triggers | Phase 2 |
| **Performance** | Time- and money-weighted returns, attribution by idea source | Phase 2 |
| **Optimization** | Risk parity, constrained mean-variance, rebalancing bands | Phase 2 |
| **Risk management** | A PASS / BLOCK check on every proposed trade against your limits | Phase 2 |

## Quick start

```bash
git clone https://github.com/MoGoMantra/folio-desk.git
cd folio-desk
pip install -e .            # Python 3.11+
folio-desk init             # writes folio-desk.toml; set [sec] user_agent to your name and email
folio-desk serve            # http://127.0.0.1:8765
```

The web app ships prebuilt in releases. From a source checkout, build it once (needs Node 20+):

```bash
cd web && npm install && npm run build
```

Run jobs from the command line as well:

```bash
folio-desk run signals
folio-desk run rotation
folio-desk run drawdowns
folio-desk run equity MSFT --peers ORCL,GOOGL,AMZN,ADBE
```

Set `[schedule] enabled = true` in `folio-desk.toml` to run signals, rotation and drawdowns every weekday after the close.

## Data sources

| Data | Default (free) | Optional |
|---|---|---|
| Daily prices | [yfinance](https://github.com/ranaroussi/yfinance) (community library over Yahoo Finance's public web endpoints; not an official API) | Polygon, Tiingo, FMP (set the key, list the provider first) |
| Fundamentals, filings, insider trades | SEC EDGAR (official; needs your name and email as the User-Agent) | — |
| Stock universe | S&P 500 constituents ([open dataset](https://github.com/datasets/s-and-p-500-companies)) | FMP screener; Nasdaq's website screener (opt-in, unofficial) |
| Consensus estimates | yfinance | FMP |
| Option chains | yfinance | — |

Free sources can lag, change or rate-limit. See [docs/data-sources.md](docs/data-sources.md).

## Repository layout

```
folio_desk/          Python package: data layer, analytics, FastAPI app, CLI
  data/              provider interface, yfinance, EDGAR, paid providers, opt-in unofficial sources
  signals/           market signal monitor
  sectors/           rotation and drawdown screens
  equity/            collector, automatic levers, valuation engine, forces ledger, risk-factor diff
  construction/      backtests, stats, stress windows, tax placement
  api/               REST API, background jobs, price cache
web/                 React + TypeScript frontend (Vite, TanStack Query, Recharts, Tailwind)
docs/                methods for each desk
tests/               offline test suite (synthetic, deterministic data)
```

## Development

```bash
pip install -e ".[dev]" && pytest          # backend
cd web && npm install && npm test          # frontend
npm run dev                                # UI on :5173, proxied to the API on :8765
```

The test suite runs offline. It includes a privacy guard that fails if personal identifiers (emails, local
paths, private links) are committed.

## License

MIT. See [LICENSE](LICENSE).
