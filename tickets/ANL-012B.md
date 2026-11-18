---
id: ANL-012B
title: Build the V2 Stock/Bond page and the shared analysis toolbar
priority: P0
status: ready
type: feature
parent: ANL-012
depends_on: [ANL-012A, APP-011A]
resources: [frontend-analysis, frontend-i18n]
risk: medium
size: M
agent_tier: standard
gate: owner
gate_approval: "owner 2026-11-10, V2 MVP scope as written in this ticket"
review: independent
branch:
pr:
spec:
updated: 2026-11-18
---

# ANL-012B: Build the V2 Stock/Bond page and the shared analysis toolbar

## Goal

A V2 user who imported a holdings file wants to see their securities at current value without learning about report editions. Build the Stock/Bond page and the toolbar every analysis page shares: reporting currency, refresh with freshness, and the entry point for downloads.

## Context

### Current behaviour

- No V2 page exists. The shipped UI talks only to `/api/v1` (`frontend/src/lib/api.ts`).
- Data: `GET /api/v2/analysis/securities` from ANL-012A.

## Requirements

- Nearest shipped page: Holdings (`frontend/src/components/analysis.tsx:178-290`). Defects seen there on 2026-11-10 that this page must not repeat: cash listed as securities with an average cost, native and display currency mixed in one row without labels, a date rail filling the top half of the screen, an edition selector.

### Expected behaviour

- Route `/app/investments`. Three to five KPIs: known value in the reporting currency, book cost and unrealized difference only where cost scope matches, number of accounts, last source date.
- Sections: allocation by account and type, holdings table with search, sort and account or currency filters, cash by account as its own table, value history from actual observations.
- Toolbar: currency selector (persisted through preferences), Refresh button showing "as of" and "last checked" times, a Download button that opens the panel from RPT-013B when present.
- Estimate, partial or stale status sits next to the value it qualifies, with detail on demand. No warning wall.
- Loading keeps the page structure and never shows 0 before a response. Empty, partial, stale and error states each state what is missing and offer one next action.

### Scope

- In scope: the page, the shared toolbar component, locale keys, tests.
- Out of scope: contract changes (return them to ANL-012A), exports (RPT-013B), drill-downs (ANL-107), performance or contribution figures (ANL-102).

### Implementation notes

- Reuse `frontend/src/components/data-table.tsx`, `chart.tsx`, `ui/button.tsx`, `lib/format.ts`, `lib/i18n.tsx`, `lib/theme.tsx` and the tokens in `frontend/src/styles.css`. Read [DESIGN.md](../DESIGN.md), [PRODUCT.md](../PRODUCT.md) and [web-frontend.md](../docs/web-frontend.md).
- Browser tests intercept `/api/v2` with Playwright `page.route`, as `frontend/tests/browser/onboarding.spec.ts` does for `/api/v1`, until a synthetic V2 fixture exists.
- Add locale keys to all three catalogs in one block named for this ticket; rebase before the PR.
- Each money column header states its currency once. Decimal strings are formatted with `lib/format.ts`; never parse to float for arithmetic.
- The currency follows the user preference from APP-011E; fall back to CAD until it loads.
- Refresh calls the market refresh route from MKT-009 and never imports data.

### Visual direction

- Owner-confirmed direction (2026-11-10): a consumer-clear top with analyst depth below. The owner finds a minimal tracker layout too simple and prefers the clarity of a retail brokerage portfolio page.
- Order on Stock/Bond, Crypto and Total, same skeleton on all three: (1) one large value with its change in amount and percent; (2) a full-width value chart with range buttons (1 week, 1 month, 3 months, 1 year, all); (3) a row of key figures (cost, unrealized gain, cash, last updated); (4) allocation by account, asset class and currency; (5) holdings table with quantity, price, market value, cost, gain and weight, sortable and searchable; (6) deeper analysis below.
- Until MKT-009 delivers daily prices, the headline shows value and unrealized gain, and the chart plots import dates; "change today" and the daily line appear when daily prices exist. Never show a fabricated change.
- Layout patterns only. Do not copy another product's colours, icons, assets or wording; keep the tokens in [DESIGN.md](../DESIGN.md).

## Acceptance criteria

- [ ] AC-ANL-012B-01: Given only a Wealthsimple import, when the page loads, then the known securities value and holdings match the mocked contract and no Bitcoin or edition wording appears.
- [ ] AC-ANL-012B-02: Given cash in two accounts, then cash is listed separately without cost or profit columns.
- [ ] AC-ANL-012B-03: Given the user selects USD, then every amount, chart axis and table header follows it and the choice survives a reload.
- [ ] AC-ANL-012B-04: Given a partial response (`complete_total` null), then the known subtotal is shown with a "partial" marker and a reason; no total is fabricated.
- [ ] AC-ANL-012B-05: Given a refresh in progress, then previous values stay visible with "updating"; on failure they stay with an error and retry.
- [ ] AC-ANL-012B-06: Given no securities source is enabled, then the page offers "Enable a source" instead of zero values.
- [ ] AC-ANL-012B-07: Given a value history with one, two or many points, then each axis label appears once and in order (the shipped chart repeats labels with one point; see ANL-111).
- [ ] AC-ANL-012B-08: No internal identifier or error code is shown as the only explanation of a status, and no heading is immediately repeated as a table caption (see APP-107, RPT-103).
- [ ] AC-ANL-012B-09: Keyboard reachable with visible focus, one `h1`, labelled controls, chart data available as a table, no colour-only meaning; en-CA, zh-TW, zh-CN; light and dark; 375 px and 1024 px.

### Tests

- Browser spec `frontend/tests/browser/v2-investments.spec.ts` covering each criterion against mocked responses.
- Unit tests for toolbar state.

## Plan

- [ ] Shared toolbar.
- [ ] KPIs and holdings table.
- [ ] Allocation and history.
- [ ] Tests and screenshots.

## Decisions needed

None open. The owner recorded Gate A on this ticket itself on 2026-11-10.

## Handoff

- State: Not started. Owner approved Gate A and released it on 2026-11-10. Waits only on ANL-012A, APP-011A (merged).
- Next step: After ANL-012A and APP-011A merge, add the route to the V2 shell and build the toolbar against a mocked `/api/v2/analysis/securities`.
- Verify: `npm --prefix frontend run build`; `npm --prefix frontend test`; `npm --prefix frontend run check:source`; `npm --prefix frontend run test:e2e`
- Gotchas: The browser suite needs local port binding and a headless browser. If your sandbox has neither (see ENG-102), say so here and leave browser criteria unchecked.
- Open questions: None.

## Log

- 2026-11-10 planner: created from the UI/UX feature inventory (tickets/UX_FEATURE_INVENTORY.md).
- 2026-11-10 planner: added history-axis, internal-code and repeated-heading criteria carried from superseded ANL-111, APP-107 and RPT-103.
- 2026-11-10 planner: added the owner-confirmed visual direction for the investment pages.
- 2026-11-10 planner: owner approved Gate A for the V2 MVP scope of this ticket on 2026-11-10 and released it (status ready).
- 2026-11-13 planner: removed the answered gate question and the stale handoff wording.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the "Nearest shipped page" bullet of Current behaviour, "Expected behaviour", "Scope", "Implementation notes" and "Visual direction" from Context into Requirements and numbered the acceptance criteria AC-ANL-012B-01 to 09. Spec hash sha256:2137e3a3e730ec66d9d0d535270c97df145f96206587aa559cfe02dcf56c53b4, awaiting the owner's confirmation.
