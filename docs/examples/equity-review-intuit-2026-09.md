# Worked example: a reviewed equity report (Intuit, September 2026)

This example shows what a fully *reviewed* equity report looks like, which is what the automatic levers are a
first draft of. It follows the desk's method on a real company using its filings. Figures are as of
25 September 2026 and are not updated. **Research for illustration, not a recommendation.**

**Sources.** 10-K FY2026 (accession 0000896878-26-000037: income statement, balance sheet, cash flow,
restructuring, income taxes, segments, notes receivable); 8-K earnings release (0000896878-26-000029: non-GAAP
reconciliation and FY27 guidance); quarterly XBRL facts from the 10-Qs, de-cumulated (Q4 = FY − 9M); Form 4s.
Peer multiples, price and investor-day figures come from screeners and press coverage and are labelled.

## 1. The call

| | |
|---|---|
| Probability-weighted fair value | **$349** |
| DCF cross-check | $463 (terminal value 77% of it: weak cross-check) |
| Margin of safety | 29.6% |
| BUY below / ACCUMULATE below / TRIM above | **$246 / $297 / $401** |
| Price | $275.94 |
| **Signal** | **ACCUMULATE**: a starter now; full size only below $246 |

Both methods sat above the price, and the DCF sat *higher* than the scenario value, so the scenario multiples
were the conservative anchor. At $276 the base-case cash earnings capitalised at a 9% WACC imply only ~0.7%
perpetual growth: the market was pricing a business that stops growing, while it guided 9–10% growth. The
argument was about terminal value (AI agents), not next year.

## 2. Why the stock had fallen 61%

1. **An accounting change made the FY27 guide look like a miss.** From FY27, non-GAAP EPS includes stock
   comp. The $22.88–23.12 guide vs $27.30 consensus becomes ~$28.81 on the old basis, above consensus.
2. **Real deceleration underneath:** revenue growth 14% → 9–10%; long-term targets cut (small-business
   15–20% → 10–15%, consumer 8–12% → 4–8%).
3. **Tax-software growth came from price, not users:** units −2%, revenue +7%, and management now cutting
   price on purpose.
4. **AI-agent fear** and two overhangs (a class action and a 17% workforce cut).

## 3. Quality of earnings: the checks that mattered

| Test | Value | Read |
|---|---|---|
| Old non-GAAP premium over GAAP EPS | 47% | Above the 40% warning line; the new basis (stock comp in) cuts it to 13.6% |
| Operating cash flow ÷ net income | 1.94× (1.66× excluding the deferred-tax add-back) | Strong after normalising |
| Deferred taxes in operating cash flow | +$1.28B (prior year −$0.44B) | A one-off: R&D expensing returned, so ~$1.3B of FY26 cash flow was a cash-tax windfall that ends in FY27 |
| Stock-comp-adjusted normalised FCF | $5.28B, a 7.2% yield | Cheap on cash |
| Goodwill + intangibles ÷ assets | 50.6% | Flag: a separately reported acquired unit with flat revenue is open to impairment |
| Purchased loans | $1.8B → $6.2B in two years; provision +77% | Flag: a hidden cyclical that hurts revenue and credit losses in the same downturn |

**A screen trap in reverse:** the company's screened forward P/E included stock comp while peers' excluded it;
like-for-like it traded at 9.6× vs a peer median of ~16×. The screen made it look *more* expensive.

## 4. Operating leverage

The FY27 guide implied stock-comp-inclusive operating income +17.8% on revenue +9.5%: costs up only 5%
after the headcount cut. With costs already cut, a revenue shortfall flows through hard: −5% revenue ≈ −12%
operating income.

## 5. Scenarios (five revenue drivers)

| | FY28 EPS | Exit P/E | Value today | Weight |
|---|---|---|---|---|
| Bull | $27.76 | 20× | $507 | 25% |
| Base | $26.22 | 15× | $359 | 45% |
| Bear | $22.20 | 10× | $203 | 30% |

The base case reproduced guidance (FY27 revenue $23.41B vs $23.40B midpoint) rather than quietly disagreeing
with it. Even the bear DCF ($302) sat above the price: you needed flat revenue *and* near-zero terminal growth
to justify $276.

## 6. Options overlay

Estimated (Black–Scholes, to be checked against the live chain): the Nov $250 put (~22% annualised, effective
basis $241.61) and the Jan $260 put (~22%, basis $242.59) both put the entry below the $246 BUY level: paid to
wait for the price the model wants. A poor-man's covered call failed the single-cycle reward test (0.29× vs a
0.5× floor).

**Correlation note (generic):** a software incumbent hurt by "AI makes software cheap" sits on the opposite
side of the AI trade from AI-hardware names; it diversifies that cluster on factor exposure but still shares
market beta. Count it with any other "incumbent survives AI" positions when sizing.

## 7. Steelman of the bear case

1. Tax-software units are already ex-growth and the price lever is spent.
2. Small-business growth is revenue per customer, not customers: exposed to the same squeeze.
3. FY27 EPS growth is partly one-off (restructuring savings, a cash-tax windfall that ends).
4. The lending book is a hidden cyclical.
5. "Cheap vs history" fails in a sector-wide de-rating (peers already at 7–9×).

**What survived:** 1, 2 and 5 (hence a 30% bear weight at 10× and ACCUMULATE, not BUY); 3 partly; 4 was not
modelled, so it became a trigger. **What did not:** "value trap on cash" (7.2% FCF yield, 3–4% annual share
shrink, bear DCF above the price).

## 8. Invalidation triggers (numeric, filing-tied)

Thesis fails if: Q1 FY27 revenue < $4.294B (guide low); any FY27 revenue-guide cut; small-business online
accounting growth < 15%; tax-software revenue declines in the FY27 season or units fall > 3%; the notes
allowance rises above 12% of gross notes; a goodwill impairment on the acquired unit.

Thesis strengthens if: Q1 revenue ≥ $4.313B with online accounting growth ≥ 20%; stock comp < 9% of revenue
with diluted shares −3%; tax-software units grow; an open-market insider buying cluster.

## How this maps to folio-desk

| Section | Where in folio-desk |
|---|---|
| Levels, fair value, DCF cross-check | Equity report (auto levers, then reviewed via `POST /api/equity/{ticker}/review`) |
| Quality-of-earnings checks | XBRL quarters in the collector; written up in a review |
| Scenario drivers | `model.drivers` (auto mode uses one revenue driver; a review can split segments) |
| Forces and triggers | `forces` ledger (sized in $/share) and `triggers` in a review |
| Put overlay | Options overlay on the report; the Decisions page's put idea and risk check |
