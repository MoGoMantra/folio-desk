# Equity research: method

An equity run collects primary-source data, sets valuation levers by written rules, values the stock under
bear / base / bull scenarios, and turns the result into priced levels.

## Pipeline

1. **Collect** (`folio_desk/equity/collect.py`)
   - SEC EDGAR: CIK, filings list, 12 discrete XBRL quarters (year-to-date facts de-cumulated; Q4 = FY − 9M),
     the latest 10-K / 10-Q and the last 8 earnings releases as text, Form 4 open-market buys and sells.
   - Data layer: 5 years of daily prices (returns, volatility, 5-year monthly beta vs SPY, big-move days),
     consensus estimates, a put chain 30–130 days out, and peer statistics (forward P/E where consensus is
     available, trailing GAAP P/E from EDGAR otherwise).
2. **Automatic levers** (`autolevers.py`): rules below. Every lever records the rule that set it.
3. **Engine** (`engine.py`): scenario value, DCF cross-check, margin of safety, levels. The web page recomputes
   the same maths when you edit a lever.
4. **Review** (optional): edit levers on the page, or add a forces ledger (`forces.py`) and risk-factor changes
   (`riskdiff.py`). Every override needs a reason; the validator applies the same guard rails.

## Lever rules (automatic mode)

| Lever | Rule |
|---|---|
| Base sales | Current fiscal-year consensus revenue; else trailing-4Q revenue |
| Base growth g | Consensus FY+1 revenue growth; else median of the last 4 quarterly YoY rates |
| Decay d | 0 when \|g\| < 5% (mature); else 0.25, floor 0.15 when g > 10%. Nothing compounds at its opening rate |
| Bull / bear g | Base ± 1 standard deviation of the last 8 quarterly YoY rates; bear floor −10%. Bull decay 0.8 × base, bear min(0.8, 2.4 × base) |
| Margins (GAAP net) | m0 = trailing 4Q; m1 = m0 + half the YoY change; m2 = m1 + the same step, capped at the best of the last 8 quarters + 2pp |
| Bull / bear margins | Bull m2 = base m2 + max(1.5pp, 1σ of 8Q margins); bear m1 = base m1 − 2pp; bear m2 = lowest of the last 8 quarters |
| Shares | Latest diluted count; growth = trailing-4Q net change; bear +1pp for unannounced dilution |
| Exit P/E (value year FY+2) | Peer median P/E × clamp(company EPS CAGR ÷ peer EPS growth, 0.8, 1.3). Bull = min(base × 1.3, max(base × 1.2, peer 75th pct)); bear = min(base × 0.65, peer 25th pct × 0.85). Peers with negative or > 80x P/E are dropped |
| Exit P/E caps (lower wins) | Growth cap = max(15x, 150 × base EPS growth in the year after the value year), i.e. PEG 1.5 with a 15x floor; the stock's own median trailing GAAP P/E when 8+ profitable quarters exist |
| Cost of equity | 4.2% + β × 5.5%, rounded to 0.5%, floor 9%, cap 11% (15% when β ≥ 2) |
| DCF | Capex grows with sales; D&A and working capital as % of sales from the trailing 4Q; WACC = CoE − 1pp when leverage is low; terminal growth 3 / 3.5 / 4% (2.5 / 3 / 3% mature) |
| Weights | 25 / 50 / 25 |

## Levels

- Margin of safety = clamp(0.5 × (base PV − bear PV) ÷ base PV, 15%, 40%). Only downside dispersion counts.
- BUY below FV × (1 − MoS); ACCUMULATE below FV × (1 − MoS/2); TRIM above FV × (1 + MoS/2); HOLD between.

## Reliability flags

The report flags when the scenario value and the DCF differ by more than 2x, when terminal value is more
than 70% of the DCF, and when fair value is not positive. An ACCUMULATE that rests on the exit multiple alone
is weaker than one the DCF supports.

## Known limits of automatic mode

- One revenue driver: segment XBRL is not standardised enough to split automatically.
- GAAP net margin basis. Peer forward P/Es usually rest on non-GAAP consensus, so automatic values lean
  conservative for companies with large stock comp or amortisation.
- Trailing GAAP P/Es (the fallback when consensus is unavailable) include one-off gains and losses.
- Without FY+2 consensus the decay cannot be solved, so the default 0.25 applies and growth after the value
  year is understated. The growth cap was loosened from PEG 1.0 / 12x to PEG 1.5 / 15x for this reason
  (a live test valued a large, durable compounder at 12x earnings). Review the exit multiple before acting.

## Options overlay

Puts whose strike sits at or below the ACCUMULATE level, 30–130 days out, ranked by annualised yield
(bid ÷ strike × 365 ÷ days). Assignment would mean buying at a price the model already likes. Size every
put against cash and your risk limits: one contract obliges you to buy 100 shares.
