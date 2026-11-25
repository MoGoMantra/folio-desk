# Register, performance, optimization and risk: method

## Trading register

Every position change is one row: trades you log, and option life-cycle events (expired, assigned /
exercised, rolled) recorded from the positions table. Assignments create the share trade at the strike and
link both rows; a roll closes one contract and opens the next, linked.

- Lots are matched first-in, first-out, long and short. Realized P&L = (close − open) × quantity × multiplier.
- Cash per account = deposits − withdrawals − purchases + sales − fees (option premium included).
- Short puts show their assignment obligation (strike × 100 × contracts).
- Each trade can carry its idea source, strategy, thesis, invalidation trigger and a review date. Review dates
  that have passed are listed on the register page.
- Trades logged without a risk check are counted and marked "unchecked".
- **Marks:** shares at the last close. Options at intrinsic value from the underlying's last close. This
  understates what an open short option would cost to close (time value is ignored), so unrealized P&L on
  short options reads high until expiry.
- Export the whole register as CSV from the register page.

## Performance

- **Account view** (when you log deposits and withdrawals): only those are external flows; idle cash counts.
- **Positions view** (no deposits logged): every buy is treated as money in and every sale as money out.
- **Time-weighted return** chains daily returns with flows at the end of the day, so it is not affected by
  when you added money; use it to compare with a benchmark.
- **Money-weighted return (XIRR)** includes your timing.
- **Attribution**: realized P&L, count and win rate by idea source and by strategy.
- Past option values use intrinsic value; free data has no option price history.

## Optimization

| Method | Needs a return forecast? | Notes |
|---|---|---|
| Risk parity | No | Each holding contributes the same share of volatility |
| Minimum variance | No | Lowest volatility within the weight caps |
| Max Sharpe | Yes (historical) | Mean returns shrunk 50% toward their average; treat as a what-if |

Covariances use daily log returns over the lookback window (default 5 years). Rebalancing bands use the
"5/25" rule: trade a holding back to target when it drifts more than 5 percentage points or more than 25%
of its target, whichever is tighter.

## Risk management

A proposed trade is checked rule by rule and comes back PASS, WARN or BLOCK. Every check is stored with a
fingerprint (a hash of the proposal, the limits and the context) and can be attached to the trade you log.
folio-desk never places orders, and a BLOCK can be overridden with a deliberate second click.

| Rule | Checks |
|---|---|
| R0 | A market-signals run exists, so limits can be scaled by regime |
| R1 | Single-name exposure (shares + short-put obligations) ≤ max % × regime multiplier |
| R2 | Each cluster of correlated names ≤ max % × regime multiplier |
| R3 | All short-put obligations ≤ max % × regime multiplier |
| R4 | Short-put delta ≤ the regime's limit (needs implied volatility) |
| R5 | Short-put strike ≤ the equity desk's ACCUMULATE level; warns when buying above TRIM |
| R6 | No short put across earnings unless the strike is ≤ ACCUMULATE |
| R7 | Short puts fully cash-secured; purchases within available cash and the cash floor |
| R8 | No adding to a name below its 200-day average in Risk-off |

Default limits (all editable): 10% single name, 25% per cluster, 50% short-put obligations, regime
multipliers 1.0 / 0.75 / 0.5 / 0.75 and put-delta limits 0.30 / 0.25 / 0.20 / 0.30 for Risk-on / Caution /
Risk-off / Washout. They are starting points, not advice.
