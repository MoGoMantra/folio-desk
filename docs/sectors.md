# Sector research: method

## Sector rotation (status: UNVALIDATED)

Where money is moving between the 11 GICS sectors, and candidate stocks inside sectors that have confirmed.

- **Views.** Cap-weighted: sector SPDR ETF vs SPY. Equal-weight: daily-rebalanced mean of member returns
  (each capped at ±30%) vs the equal-weight universe. Ranks, flags and stages use the equal-weight view.
- **Confirmation flags.** Gaining: rank up ≥ 3 in 20 sessions, ratio above its 50-day avg, breadth +10 pts.
  Losing: the mirror image. Thinning: ETF in the top 3 by 20-session RS while breadth falls 15 pts.
- **Leading flags.** L1 breadth thaw; L2 early leaders (≥ 15% of members at a 63-session high within 5
  sessions while the ratio is below its 50-day); L4 accumulation (≥ 58% of dollar volume on up days, dollar-
  volume share ≥ 1.10× its 60-session norm, RS ≤ +1%).
- **Stage.** Confirmed > Losing > Early (2+ leading) > Watch (1) > Neutral; a watch older than 30 sessions
  without confirmation becomes "Stale watch".
- **Candidate lists.** Confirmed sectors only: top 10 members by 20-session return vs the sector, ≥ $25M/day,
  ≤ 40% above the 50-day, no one-day move ≤ −35% or ≥ +50% in 60 sessions.
- **Evidence.** Every run re-scores every flag over the stored history: hit rate over the next 20 sessions
  vs the base rate. Base rates use only sector-days whose outcome is known (counting the last 20 sessions as
  "neither" once overstated every edge by about 4.6 points). Differences under ~5 points are noise.
- **What earlier research found.** A price-only version over 27 years of sector ETFs showed no edge; classic
  sector momentum rankings showed no spread; the leading flags showed no edge. The screen describes rotation;
  it does not yet forecast it.

## Multi-week drawdowns

Every stock whose close is ≥ 10% below the highest close of the last 16 sessions, with the worst day, a
sparkline and flags for likely corporate actions (a one-day move ≤ −35% or ≥ +50%) and recent listings.
A drawdown is a question, not a signal: explain it from the filings and news before acting on it.
