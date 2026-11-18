---
id: ANL-012D
title: Build the V2 Total page and Home
priority: P0
status: ready
type: feature
parent: ANL-012
depends_on: [ANL-012C]
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

# ANL-012D: Build the V2 Total page and Home

## Goal

A V2 user lands on Home to see what they track and what to do next, and opens Total for the combined picture. The shipped Overview is the screen the approved direction calls overwhelming; Home replaces it with the value, the split and one next action.

## Context

### Current behaviour

- No V2 page exists. The shipped UI talks only to `/api/v1` (`frontend/src/lib/api.ts`).
- Nearest shipped page: Overview (`frontend/src/components/analysis.tsx:60-176`). Observed 2026-11-10: the value is followed by "Evidence for this saved edition", "Next steps (4)" and "Saved evidence and checks"; a "Report edition" selector sits in the header. APP-011 bans these concepts from Home.
- Data: `GET /api/v2/analysis/total` from ANL-012A.

## Requirements

### Expected behaviour

- Home (`/app`): tracked value in the reporting currency, securities and crypto split, last source and price update, one primary next action (enable a source, import, or refresh), and one line for estimate or partial status with detail on demand.
- Total (`/app/total`): known-valued subtotal, complete total only when determinable, allocation by asset class, account and currency, source coverage, value history with observation and revaluation distinguished.
- First use: Home shows no fabricated zero; it leads to enabling a source.
- Loading keeps the page structure and never shows 0 before a response. Empty, partial, stale and error states each state what is missing and offer one next action.

### Scope

- In scope: the two pages, locale keys, tests.
- Out of scope: contract changes (return them to ANL-012A), exports (RPT-013B), drill-downs (ANL-107), performance or contribution figures (ANL-102).

### Implementation notes

- Reuse `frontend/src/components/data-table.tsx`, `chart.tsx`, `ui/button.tsx`, `lib/format.ts`, `lib/i18n.tsx`, `lib/theme.tsx` and the tokens in `frontend/src/styles.css`. Read [DESIGN.md](../DESIGN.md), [PRODUCT.md](../PRODUCT.md) and [web-frontend.md](../docs/web-frontend.md).
- Browser tests intercept `/api/v2` with Playwright `page.route`, as `frontend/tests/browser/onboarding.spec.ts` does for `/api/v1`, until a synthetic V2 fixture exists.
- Add locale keys to all three catalogs in one block named for this ticket; rebase before the PR.
- Use the shared toolbar from ANL-012B on Total. Home has no toolbar.
- Currencies are alternative equivalents; never add CAD, USD and TWD figures.
- Value growth is not a return; the history caption says so, as the shipped History page does.

### Visual direction

- Owner-confirmed direction (2026-11-10): a consumer-clear top with analyst depth below. The owner finds a minimal tracker layout too simple and prefers the clarity of a retail brokerage portfolio page.
- Order on Stock/Bond, Crypto and Total, same skeleton on all three: (1) one large value with its change in amount and percent; (2) a full-width value chart with range buttons (1 week, 1 month, 3 months, 1 year, all); (3) a row of key figures (cost, unrealized gain, cash, last updated); (4) allocation by account, asset class and currency; (5) holdings table with quantity, price, market value, cost, gain and weight, sortable and searchable; (6) deeper analysis below.
- Until MKT-009 delivers daily prices, the headline shows value and unrealized gain, and the chart plots import dates; "change today" and the daily line appear when daily prices exist. Never show a fabricated change.
- Layout patterns only. Do not copy another product's colours, icons, assets or wording; keep the tokens in [DESIGN.md](../DESIGN.md).

## Acceptance criteria

- [ ] AC-ANL-012D-01: Given a new user with no source enabled, then Home shows no amount and one action leading to Sources.
- [ ] AC-ANL-012D-02: Given securities only, then Home and Total show the securities value and Crypto as "not tracked yet".
- [ ] AC-ANL-012D-03: Given both, then Total counts Bitcoin once and equals the mocked oracle in each currency.
- [ ] AC-ANL-012D-04: Home contains none of: "Evidence for this saved edition", "Partial source scope", "Carried forward", "Provided", "Next steps", "Saved evidence and checks", "Report edition", in any locale.
- [ ] AC-ANL-012D-05: Given a partial total, then the known subtotal and a single partial marker are shown; detail opens on demand.
- [ ] AC-ANL-012D-06: Keyboard reachable with visible focus, one `h1`, labelled controls, chart data available as a table, no colour-only meaning; en-CA, zh-TW, zh-CN; light and dark; 375 px and 1024 px.

### Tests

- Browser specs `frontend/tests/browser/v2-home.spec.ts` and `v2-total.spec.ts`, including the banned-text assertion per locale.

## Plan

- [ ] Home.
- [ ] Total.
- [ ] Tests and screenshots.

## Decisions needed

None open. The owner recorded Gate A on this ticket itself on 2026-11-10.

## Handoff

- State: Not started. Owner approved Gate A and released it on 2026-11-10. Waits only on ANL-012C.
- Next step: After ANL-012C merges, replace the V2 shell's Home placeholder using a mocked `/api/v2/analysis/total`.
- Verify: `npm --prefix frontend run build`; `npm --prefix frontend test`; `npm --prefix frontend run check:source`; `npm --prefix frontend run test:e2e`
- Gotchas: The browser suite needs local port binding and a headless browser. If your sandbox has neither (see ENG-102), say so here and leave browser criteria unchecked.
- Open questions: None.

## Log

- 2026-11-10 planner: created from the UI/UX feature inventory (tickets/UX_FEATURE_INVENTORY.md).
- 2026-11-10 planner: added the owner-confirmed visual direction for the investment pages.
- 2026-11-10 planner: owner approved Gate A for the V2 MVP scope of this ticket on 2026-11-10 and released it (status ready).
- 2026-11-13 planner: removed the answered gate question and the stale handoff wording.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved "Expected behaviour", "Scope", "Implementation notes" and "Visual direction" from Context into Requirements and numbered the acceptance criteria AC-ANL-012D-01 to 06. Spec hash sha256:9ec8c0bf66ad2592e749a91dc7b86a4d526ba0a2d8dc537c8561ec29f9c517fc, awaiting the owner's confirmation.
