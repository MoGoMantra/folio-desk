---
name: folio-desk
description: Operate a local folio-desk install for an individual investor - run the market signals, sector, equity and decision jobs, read their results, log trades in the register, and run pre-trade risk checks. Use when the user asks what the desk says about the market or a ticker, wants a trade checked or logged, or wants performance or a rebalance.
---

# Operating folio-desk

folio-desk runs on the user's machine: a FastAPI server (default http://127.0.0.1:8765, started with
`folio-desk serve`) over a SQLite file, plus a CLI. Everything below works through either.

## Ground rules

- It is research software. Never phrase output as an instruction to trade, and never place, or offer to
  place, orders. folio-desk has no broker connection by design.
- Say which inputs a call rests on and how old they are (`asOf` on every document).
- Signals and sector rotation are **unvalidated**; the automatic equity levers are a first draft. Say so when
  a result leans on them.
- Never type the user's SEC contact into config files you create; ask them to set `[sec] user_agent`.

## Jobs

| Need | CLI | API |
|---|---|---|
| Market regime and signals | `folio-desk run signals` | `POST /api/signals/run`, `GET /api/signals/latest` |
| Sector rotation | `folio-desk run rotation` | `POST /api/sectors/rotation/run`, `GET .../latest` |
| Drawdown screen | `folio-desk run drawdowns` | `POST /api/sectors/drawdowns/run`, `GET .../latest` |
| Equity report | `folio-desk run equity TICK --peers A,B,C` | `POST /api/equity/TICK/run` `{"peers": [...]}`, `GET /api/equity/TICK` |
| Decisions | `folio-desk run decisions` | `POST /api/decisions/run`, `GET /api/decisions/latest` |

API runs return a job; poll `GET /api/jobs/{id}` until `done` or `error`.

## Order of work for "should I buy X?"

1. `GET /api/signals/latest`: regime and playbook line (run it if missing or older than a session).
2. `GET /api/equity/X`: levels and flags (run it if missing or older than 60 days; pick 8-12 peers from the
   10-K's competition section and keep the same set afterwards).
3. `POST /api/decisions/run`, then read X's row: action, confidence, size, reasons, issues, put idea.
4. If the user wants to act: `POST /api/risk/check` with the exact trade; report every non-PASS rule.
5. After the user places the trade with their broker: `POST /api/register/trades`, including `check_id`,
   `thesis`, `invalidation` and `review_date`.

## Register

- Trades: `POST /api/register/trades` (stock: qty = shares; option: qty = contracts, price = premium per
  share, plus `opt_kind`, `strike`, `expiry`). Deposits: `POST /api/register/cashflows`.
- Option events: `POST /api/register/options/action` with `action` = expire | assign | roll and the
  position `key` from `GET /api/register/positions` (e.g. `"MSFT 2027-01-15 P 440"`).
- Performance: `POST /api/performance` `{"benchmarks": ["SPY"]}`. Optimization: `POST /api/optimize`.

## When results look wrong

- An equity report flagged "provisional" used trailing P/Es because consensus was unavailable: say so before
  quoting its label, and suggest the equity-review skill.
- `missing` lists in signal docs mean a data source failed for those symbols.
- Risk check WARN on R0 means no signals run: limits were not regime-scaled.
