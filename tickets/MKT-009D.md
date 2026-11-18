---
id: MKT-009D
title: Build the daily value curve from historical prices and carried-forward quantities
priority: P0
status: ready
type: feature
parent: MKT-009
depends_on: [MKT-009B, MKT-009C]
resources: [calculation-contract, market-contract, frontend-charts, frontend-i18n]
risk: high
size: L
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-11, post-MVP scope as written in this ticket"
review: independent
branch:
pr:
spec:
updated: 2026-11-18
---

# MKT-009D: Build the daily value curve from historical prices and carried-forward quantities

## Goal

The owner wants the value chart to be a daily line, not a few points on import dates. That needs the closing price and FX rate of every day since the first import, and a rule for the days between two imports. The owner chose the rule on 2026-11-11: use the quantities of the previous import until the next one, and say that those days are estimates.

## Context

### Spec material

- Golden cases G18 and G19: [docs/golden-cases.md](../docs/golden-cases.md) (sha256:f7adca063ff68fe0502066608fc6fad6b1f818244679190b3e7cdcf3020e5594).

### Current behaviour

- After the MVP the value series has one point per import date (ANL-012A, first version).
- MKT-009A defines daily history on the adapter interface. MKT-009B stores latest prices and MKT-009C daily FX; neither backfills earlier days.
- The wide chart with range buttons on Stock/Bond, Crypto and Total (ANL-012B, 012C, 012D) draws whatever series the contract returns.

### Owner decision recorded 2026-11-11

Between two imports, each day is valued as the previous import's quantities times that day's closing price. Those points are marked "estimated from the import of <date>". If the user bought or sold in between, that stretch is wrong until the next import; the chart says so in one line.

This replaces, for the value curve only, the earlier planning rule that no value is shown for days without an observation (golden case G18). It does not allow anything else to be inferred: no return, contribution, gain for a period, or transaction is derived from an estimated day.

### Expected behaviour

- For each listing and currency pair a user has held, daily closes are fetched once from the first import date to today and stored in the market reference store; later days are appended by the daily refresh.
- Each analysis response returns a `value_series` of daily points. Each point has the date, the value as a decimal string in the display currency, and a basis: `observed` (an import date, or a day whose quantities come from dated transactions), `estimated` (carried-forward quantities) with the date of the import they come from, or `unavailable` with a reason.
- Securities: quantities change only at holdings imports. Bitcoin: quantities come from dated purchase and sale rows, so every day is `observed`.
- A day with no close (weekend, holiday) uses the latest earlier close and keeps its basis. A day before a listing has any price is `unavailable`; the chart shows a gap, not zero.
- The value on an import date equals the value shown for that import: the curve passes through every observed point exactly.
- A position that the next import shows as sold is carried until the day before that import.
- When a split falls between an older quantity and a later price, the affected days are `unavailable` for that holding until a newer import confirms the quantity (golden case G19).
- Range buttons (1M, 3M, 6M, YTD, 1Y, All) are served by one `range` parameter; the response never returns more than one point per day.
- The page shows one line of text under the chart when any visible point is estimated. The wording is in the three locale catalogs.

### Scope

- In scope: historical backfill for prices and FX, the series calculation, the contract change, the one-line notice and the point styling on the three pages, tests.
- Out of scope: performance or return figures (ANL-104), contributions (ANL-103), intraday points, benchmarks.

### Implementation notes

- Backfill runs in the refresh process from MKT-009B, in bounded batches that respect the provider budget, and can resume after a stop. It is triggered when a holding appears for the first time.
- If the provider has no history for a listing, the series for that holding is `unavailable` before the first fetched price; totals for those days are `known_subtotal` only.
- Compute the series in the service and cache it by user, currency, fact generation and the latest stored close date. Do not store per-user daily values as facts.
- Estimated points are drawn in the same line with a lighter or dashed style and are named in the chart's data table; meaning must not rely on colour alone ([DESIGN.md](../DESIGN.md)).
- This changes the response of ANL-012A. Add the fields in a backward-compatible way and regenerate the frontend types ([web-frontend.md](../docs/web-frontend.md)).

## Acceptance criteria

- [ ] Given holdings imports on 15 January and 15 March and fixed daily closes, then every day of February has a point equal to the January quantities times that day's close, with basis `estimated` and source date 15 January.
- [ ] Given the same data, then the points of 15 January and 15 March equal the values the imports show and have basis `observed`.
- [ ] Given a position present in January and absent in March, then it contributes through 14 March and not from 15 March.
- [ ] Given Bitcoin purchases on three dates, then each day's quantity is the sum of purchases minus sales up to that day and every point is `observed`.
- [ ] Given a Sunday, then Friday's close is used.
- [ ] Given a listing with no price before 1 February, then its January points are `unavailable`, the total for those days is a known subtotal, and nothing is zero.
- [ ] Given a split between the import and a later close, then that holding's later days are `unavailable` with the reason.
- [ ] Given `currency=TWD`, then each day is converted with that day's rate or the latest earlier one.
- [ ] Given any estimated point in the visible range, then the page shows the notice; with none, it does not.
- [ ] No response field or page text derives a return, gain for a period or contribution from estimated points.
- [ ] Backfill stopped halfway resumes without refetching completed days.

### Tests

- Unit tests for the series rules with independently derived oracles.
- Opt-in PostgreSQL tests for backfill and resume with the fake provider.
- Browser tests for the notice, the dashed segment and the data table on one page at 375 px and 1024 px.

## Plan

- [x] Owner Gate A.
- [ ] Backfill job.
- [ ] Series calculation and contract fields.
- [ ] Chart styling and notice on the three pages.
- [ ] Documentation of the estimate rule in the user manual.

## Handoff

- State: Not started. Owner approved Gate A on 2026-11-11. Waits on MKT-009B and MKT-009C.
- Next step: Read the ANL-012A series code and the MKT-009B refresh process, then write the series rules as pure functions with their oracles before any fetching code.
- Verify: the new unit test module, then the opt-in PostgreSQL tests.
- Gotchas: [AGENTS.md](../AGENTS.md) says not to revalue history or invent observations. That rule protects stored facts and frozen report editions. This ticket stores no estimated value as a fact and marks every estimated point; keep it that way. Fetch unadjusted closing prices. A dividend-adjusted close understates every past value, and many providers also back-adjust the whole history for splits, which makes the days before a split wrong for a quantity imported before it. Check what the adapter returns, store which kind it is, and apply the split rule in Expected behaviour to back-adjusted history as well.
- Open questions: None.

## Log

- 2026-11-11 planner: split out of MKT-009. Owner chose on 2026-11-11 to carry the previous import's quantities forward between imports and mark those days as estimates.
- 2026-11-11 planner: owner approved Gate A for this ticket on 2026-11-11 and released it (status ready).
- 2026-11-13 planner: added a gotcha about dividend-adjusted and split-back-adjusted price history. No change to scope or acceptance criteria.
