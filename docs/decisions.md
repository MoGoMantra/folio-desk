# Decisions: how the call is made

The Decisions page (the home page) gives one research call per name you hold, have researched, or watch.
The rules are written down so you can disagree with a specific one. It is a call for you to review, not an
instruction; folio-desk never places orders.

## Inputs

| Input | From |
|---|---|
| Fair value and BUY / ACCUMULATE / TRIM levels, reliability flags | Equity desk report (auto or reviewed) |
| Market regime and posture | Signals desk (latest run) |
| 200-day trend | Price history |
| What you hold | Trading register |
| Limits | Risk page |

## Rules, in order

1. **Funds** (anything in the fund list without an equity report): judged by allocation, not valuation.
   HOLD if held; use construction and rebalancing.
2. **No report, or a report older than 120 days:** NO VIEW (HOLD if held). Run the equity desk first.
3. **Re-label at today's price** using the stored levels: below BUY → BUY zone; below ACCUMULATE → ACCUMULATE
   zone; above TRIM → TRIM zone; otherwise HOLD zone.
4. **Base call:** BUY zone → BUY (ADD if held). ACCUMULATE zone → BUY / ADD at starter size (a third).
   HOLD zone → HOLD if held, AVOID if not. TRIM zone → TRIM if held (SELL if more than 25% above TRIM),
   AVOID if not. A non-positive fair value → SELL if held, AVOID if not.
5. **Regime overlay (buys only):** Risk-off: no adding to a held name below its 200-day; outside the BUY
   zone, wait; inside it, size is halved by the regime multiplier. Caution: stagger. Washout: size re-entry
   by the bottom checklist.
6. **Confidence:** starts High; each reliability issue lowers it one step (Medium, then Low). Issues: every
   flag on the equity report (DCF disagreement, terminal value over 70%, provisional exit multiple), a report
   older than 60 days, validation problems, no market-signals run, a buy below the 200-day.
7. **Size (BUY / ADD):** max single-name % × regime multiplier × confidence factor (High 1.0, Medium 0.6,
   Low 0.3) × starter (1/3 in the ACCUMULATE zone), minus what you already hold. Under 0.5% of the portfolio
   becomes HOLD. **TRIM:** a quarter of the position as a starting point.
8. **Risk check:** the suggested share trade and the put idea are each run through the pre-trade check
   (docs/portfolio.md) and show PASS / WARN / BLOCK.
9. **Put idea:** for BUY / ADD / HOLD calls, the cash-secured put with the best annualised yield whose strike
   is at or below ACCUMULATE, preferring strikes at or below BUY.

## Known weakness

The call is only as good as the equity desk's levels. In automatic mode without consensus estimates, the exit
multiple falls back to trailing GAAP P/Es, which reads bearish on durable compounders. Those reports carry a
"provisional" flag and the call's confidence drops. Review the levers (or run with a consensus source) before
acting on a TRIM or AVOID.
