---
id: ANL-012C
title: Build the V2 Crypto page
priority: P0
status: ready
type: feature
parent: ANL-012
depends_on: [ANL-012B]
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
spec_approved: sha256:55d2377916623369929ca3799242d0b00b39db2b573d474a9c02cec11e11984f
updated: 2026-11-18
---

# ANL-012C: Build the V2 Crypto page

## Goal

A V2 user who imported Bitcoin purchase records wants to see how much they acquired and what it is worth, under the approved assumption that acquired coins are still held. The shipped Bitcoin page mixes this with funding, cash flows and source-specific wording.

## Context

### Current behaviour

- No V2 page exists. The shipped UI talks only to `/api/v1` (`frontend/src/lib/api.ts`).
- Nearest shipped page: Bitcoin & flows (`frontend/src/components/analysis.tsx:480-590`). Observed 2026-11-10: it shows "Bull purchases (BTC equivalent)", a monthly "Funding, unclassified" column and a "Recorded cash flows" section; labels name one provider.
- Data: `GET /api/v2/analysis/crypto` from ANL-012A; positions from ANL-008.

## Requirements

### Expected behaviour

- Route `/app/crypto`. Label: "Tracked BTC acquisitions, assumed held".
- KPIs: tracked BTC-equivalent quantity, estimated value, known acquisition spending with cost coverage, weighted purchase rate.
- Sections: cumulative acquisitions chart, monthly table of quantity, spend and rate, breakdown by source and network.
- No opening balance, wallet verification, funding, cash-flow or period-return wording. Quote time and source time are shown separately.
- Loading keeps the page structure and never shows 0 before a response. Empty, partial, stale and error states each state what is missing and offer one next action.

### Scope

- In scope: the page, locale keys, tests.
- Out of scope: contract changes (return them to ANL-012A), exports (RPT-013B), drill-downs (ANL-107), performance or contribution figures (ANL-102).

### Implementation notes

- Reuse `frontend/src/components/data-table.tsx`, `chart.tsx`, `ui/button.tsx`, `lib/format.ts`, `lib/i18n.tsx`, `lib/theme.tsx` and the tokens in `frontend/src/styles.css`. Read [DESIGN.md](../DESIGN.md), [PRODUCT.md](../PRODUCT.md) and [web-frontend.md](../docs/web-frontend.md).
- Browser tests intercept `/api/v2` with Playwright `page.route`, as `frontend/tests/browser/onboarding.spec.ts` does for `/api/v1`, until a synthetic V2 fixture exists.
- Add locale keys to all three catalogs in one block named for this ticket; rebase before the PR.
- Use the shared toolbar from ANL-012B unchanged.
- Quantities use eight decimals (`lib/format.ts` `quantity`). LBTC is presented as BTC-equivalent with its network shown in the breakdown.
- No generic label may contain a provider name; provider names appear only as data in the source breakdown.

### Visual direction

- Owner-confirmed direction (2026-11-10): a consumer-clear top with analyst depth below. The owner finds a minimal tracker layout too simple and prefers the clarity of a retail brokerage portfolio page.
- Order on Stock/Bond, Crypto and Total, same skeleton on all three: (1) one large value with its change in amount and percent; (2) a full-width value chart with range buttons (1 week, 1 month, 3 months, 1 year, all); (3) a row of key figures (cost, unrealized gain, cash, last updated); (4) allocation by account, asset class and currency; (5) holdings table with quantity, price, market value, cost, gain and weight, sortable and searchable; (6) deeper analysis below.
- Until MKT-009 delivers daily prices, the headline shows value and unrealized gain, and the chart plots import dates; "change today" and the daily line appear when daily prices exist. Never show a fabricated change.
- Layout patterns only. Do not copy another product's colours, icons, assets or wording; keep the tokens in [DESIGN.md](../DESIGN.md).

## Acceptance criteria

- [ ] AC-ANL-012C-01: Given purchases of 0.010 and 0.020 BTC, then the page shows 0.03000000 BTC and the oracle value from the mocked contract.
- [ ] AC-ANL-012C-02: Given transfers or balance snapshots in the data, then they add nothing to acquisitions.
- [ ] AC-ANL-012C-03: Given unknown cost for some purchases, then spending shows the known part with its coverage and no unrealized difference is computed for the unknown part.
- [ ] AC-ANL-012C-04: Given no crypto source is enabled and no data, then the page offers "Enable a source"; given a disabled source with data, the data stays visible.
- [ ] AC-ANL-012C-05: No element contains the words "opening", "self-custodied" or a provider name outside the source breakdown, in any locale.
- [ ] AC-ANL-012C-06: Keyboard reachable with visible focus, one `h1`, labelled controls, chart data available as a table, no colour-only meaning; en-CA, zh-TW, zh-CN; light and dark; 375 px and 1024 px.

### Tests

- Browser spec `frontend/tests/browser/v2-crypto.spec.ts`.

## Plan

- [ ] KPIs.
- [ ] Chart and monthly table.
- [ ] Breakdown; tests and screenshots.

## Decisions needed

None open. The owner recorded Gate A on this ticket itself on 2026-11-10.

## Handoff

- State: Not started. Owner approved Gate A and released it on 2026-11-10. Waits only on ANL-012B.
- Next step: After ANL-012B merges, add `/app/crypto` using its toolbar and a mocked `/api/v2/analysis/crypto`.
- Verify: `npm --prefix frontend run build`; `npm --prefix frontend test`; `npm --prefix frontend run check:source`; `npm --prefix frontend run test:e2e`
- Gotchas: The browser suite needs local port binding and a headless browser. If your sandbox has neither (see ENG-102), say so here and leave browser criteria unchecked.
- Open questions: None.

## Log

- 2026-11-10 planner: created from the UI/UX feature inventory (tickets/UX_FEATURE_INVENTORY.md).
- 2026-11-10 planner: added the owner-confirmed visual direction for the investment pages.
- 2026-11-10 planner: owner approved Gate A for the V2 MVP scope of this ticket on 2026-11-10 and released it (status ready).
- 2026-11-13 planner: removed the answered gate question and the stale handoff wording.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved "Expected behaviour", "Scope", "Implementation notes" and "Visual direction" from Context into Requirements and numbered the acceptance criteria AC-ANL-012C-01 to 06. Spec hash sha256:55d2377916623369929ca3799242d0b00b39db2b573d474a9c02cec11e11984f, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:55d2377916623369929ca3799242d0b00b39db2b573d474a9c02cec11e11984f.
