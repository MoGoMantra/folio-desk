# Worked example: a cash-secured put from idea to register

A fictional $200,000 taxable account with one stock idea, followed through every desk. Prices and levels are
illustrative. **Not a recommendation.**

## 1. The market (Signals)

The signals run reads **Caution**: risk score 34, breadth amber, credit green. The playbook line says: hold,
stagger new buys, favour quality. Caution scales the risk limits by 0.75 and caps short-put delta at 0.25.

## 2. The idea (Sectors → Equity)

Rotation shows Health Care at *Confirmed* with a candidate list; one name, **EXMP** (fictional), is also on
the drawdown screen at −14% from its three-week high after an earnings-day drop. The drawdown is a question,
so the equity desk runs: EDGAR quarters, consensus, peers, options.

The report: fair value **$92**, BUY < **$74**, ACCUMULATE < **$83**, TRIM > **$101**. Price **$80** → the
ACCUMULATE zone. One flag: terminal value is 74% of the DCF. The options overlay finds the 49-day **$72 put**
at $1.40 bid (14.5% annualised), strike below BUY.

## 3. The call (Decisions)

| | |
|---|---|
| Call | **BUY** (ACCUMULATE zone, starter size) |
| Confidence | **Medium** (one reliability flag) |
| Size | 10% limit × 0.75 (Caution) × 0.6 (Medium) × ⅓ (starter) = **$3,000** → 37 shares |
| Put idea | 49-day $72 put, 14.5%/yr, assignment below BUY |
| Reasons | ACCUMULATE zone; Caution → stagger; TV flag lowers confidence |

## 4. The check (Risk)

Running the put through the pre-trade check (one contract = $7,200 obligation):

| Rule | Result |
|---|---|
| R1 single name | PASS: $7,200 = 3.6% vs 7.5% (10% × 0.75) |
| R3 short-put exposure | PASS: $7,200 = 3.6% vs 37.5% |
| R4 delta | PASS: 0.19 at 38% IV vs 0.25 in Caution |
| R5 strike vs ACCUMULATE | PASS: $72 ≤ $83 |
| R6 earnings | WARN: next earnings date not entered |
| R7 cash secured | PASS |
| **Verdict** | **WARN** (look up the earnings date) |

You find the next report falls after expiry, enter it, re-run: **PASS**.

## 5. The record (Register)

"Log the put" pre-fills the register: sell 1 EXMP 49-day $72 put at $1.40, strategy *cash-secured put*,
idea source *equity*, with the risk check attached. You add the thesis ("cash-generative compounder sold off
on a one-quarter margin miss") and the invalidation trigger ("gross margin below 58% for a second quarter"),
and a review date one week before expiry.

## 6. What happens next

- **Expires worthless:** click *Expired*; $140 is realized under *cash-secured put / equity*.
- **Assigned:** click *Assigned*; the option closes and 100 shares are booked at $72, effective basis $70.60,
  below the BUY level the model wanted.
- **Rolled:** enter the close and open prices; both legs are linked.

Every month, Performance shows time- and money-weighted return against SPY, and attribution shows whether
ideas from the equity desk, rotation or the drawdown screen are paying for themselves.
