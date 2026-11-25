# Market signals: method

Built from the lessons of one market episode (a tech/AI sell-off in autumn 2026). **Thresholds are
unvalidated beyond that episode.** Review them against outcomes before relying on them.

## Principles

1. **Leads vs confirms.** Each signal is tagged `lead` (historically moves before stocks) or `coincident`
   (moves with or after). In the reference episode breadth narrowing, small caps and speculative assets led
   by 3–8 weeks; rate-adjusted credit did not lead.
2. **Alert on state changes, not levels.** A run reports which signals changed colour since the last run.
3. **No single signal calls a top or bottom.** Scores aggregate; the bottom checklist wants several greens together.
4. **Free data only.** ETF ratios stand in for credit spreads; a fixed ~100-stock basket stands in for index breadth.

## Signals

| ID | Layer | Signal | Kind | Rule |
|---|---|---|---|---|
| BR1 | Breadth | RSP/SPY 30-session change | lead | Red ≤ −2% while SPY within 3% of its 52-week high; amber below 50-day avg |
| BR2 | Breadth | IWM/SPY 30-session change | lead | Red ≤ −3%; amber below 50-day avg |
| BR3 | Breadth | % of basket above 50-day avg | coincident | Green > 60, amber 40–60, red < 40 |
| BR4 | Breadth | % of basket above 200-day avg | coincident | Green > 60, amber 45–60, red < 45 |
| BR5 | Breadth | Net new 52-week highs, 10-day avg | coincident | Green > +2, amber −2..+2, red < −2 |
| LC1 | Leadership | SMH distance from 200-day avg | lead | Red ≥ +25% or < 0; amber +15..25 or 0..+3 |
| LC2 | Leadership | SMH/SPY 20-session change | coincident | Amber ≤ −3%, red ≤ −8% |
| LC3 | Leadership | Theme basket median drawdown (configurable) | coincident | Amber ≤ −10%, red ≤ −20% |
| CR1 | Credit | HYG/IEF 20-session change | lead | Red ≤ −1%; amber below 50-day avg |
| CR2 | Credit | LQD/IEF 20-session change | coincident | Red ≤ −0.75%; amber below 50-day avg |
| CR3 | Credit | Theme bellwether 20-session change (optional) | lead | Amber ≤ −10%, red ≤ −20% |
| VO1 | Volatility | VIX | coincident | Green < 16, amber 16–22, red > 22 |
| VO2 | Volatility | VIX / VIX3M | coincident | Green < 0.90, amber 0.90–1.0, red > 1.0 |
| VO3 | Volatility | VVIX | coincident | Green < 95, amber 95–115, red > 115 |
| MA1 | Macro | 10-year yield | lead | Red +25bp in 20 sessions; amber ≥ 5.25% or +10bp |
| MA2 | Macro | WTI crude | lead | Red ≥ $100 or +10% in 20 sessions; amber ≥ $90 |
| MA3 | Macro | Dollar index 20-session change | coincident | Amber \|move\| ≥ 2%, red ≥ 4% |
| RA1 | Risk appetite | Bitcoin drawdown from 90-day high | lead | Amber ≤ −7%, red ≤ −15% |
| RA2 | Risk appetite | ARKK/SPY 20-session change | lead | Amber ≤ −3%, red ≤ −7% |
| RA3 | Risk appetite | Defensives (XLU, XLP) vs SPY, 20 sessions | coincident | Amber ≥ +2%, red ≥ +4% |

## Scores and regime

- Top-risk score = 100 × (reds + ½ × ambers) ÷ scored signals. Low < 25, Elevated 25–45, High ≥ 45.
- Regime: Washout if VIX/VIX3M ≥ 1.0 or < 20% of the basket is above its 50-day; else Risk-off (≥ 45),
  Caution (≥ 25), Risk-on.

## Bottom checklist

B1 VIX term structure spike and reversal · B2 VVIX spike and fade · B3 credit stops deteriorating ·
B4 semis reclaim the 200-day · B5 breadth washout then thrust · B6 bad news bought (manual) · B7 leaders'
capex / guidance holds (manual) · B8 10-year yield falling · B9 positioning flush ends (manual) · B10 oil
below $95. ≥ 6 green: "Bottom signals strong"; 4–5: "Bottom forming".

## Posture playbook (first draft)

Regime sets posture, not picks. Risk-on: normal buying. Caution: hold, stagger buys, favour quality.
Risk-off: no averaging down into breaking leaders; sell puts only at strikes you'd gladly own. Washout:
build the buy list; size re-entry by the bottom checklist (0–3 wait, 4–5 a first third, 6+ the next).
