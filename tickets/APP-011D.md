---
id: APP-011D
title: Add V2 import upload, review and history UI
priority: P0
status: ready
type: feature
parent: APP-011
depends_on: [APP-011A, IMP-007E]
resources: [frontend-imports-ui]
risk: medium
size: M
agent_tier: standard
gate: owner
gate_approval: "owner 2026-11-10, V2 MVP scope as written in this ticket"
review: independent
branch: 
pr: 
spec: docs/specs/v2-drafts/WL-P0-011.md
updated: 2026-11-18
---

# APP-011D: Add V2 import upload, review and history UI

## Goal

Upload, reconciled preview, decisions, confirmation and import history on the V2 import routes. A user picks an enabled source, uploads a file, reviews what will change, confirms, and lands on their analysis, without choosing a snapshot kind, typing timestamps or creating a portfolio.

## Context

### Current behaviour

- No V2 page exists. The shipped UI talks only to `/api/v1` (`frontend/src/lib/api.ts`).
- Routes come from IMP-007E (not built). Backend status and the meaning of preview, decision and confirmation: [web-v2-imports.md](../docs/web-v2-imports.md).
- The shipped import page is `frontend/src/components/imports.tsx` (1,071 lines). Observed on the synthetic fixture on 2026-11-10: step 3 is marked current on arrival (`:170-176`), two near-identical introductions (`:393-394`), timestamps typed with a UTC offset (`:507,521`), "Snapshot kind" and "reference JSON" fields, and history rows that show only a job type and time (`:1040-1060`).
- Its confirmation dialog (`:996-1030`) and its rule that unsent input survives errors are worth keeping.

### Expected behaviour

- Import Data `/app/import`, three steps: 1 choose an enabled source and file; 2 review; 3 confirm.
- Step 1 lists only sources the user enabled (APP-011C) with each one's format help, and accepts one file up to the server limit.
- Step 2 names any account that earlier imports had and this file lacks, and asks whether to keep it unchanged or mark it closed (owner decision 2026-11-10; a position missing inside a covered account is sold without asking). Step 2 also shows detected accounts, counts of new, duplicate and conflicting records, and each conflict with old and proposed values and the allowed choices. Nothing is booked yet.
- Step 3 confirms the exact preview. On success the user goes to the matching analysis page, which shows "updating" until the new calculation is current.
- A stale or expired preview says why and offers "Upload again"; raw files are not kept, and the page says so.
- History lists past imports with source, file name, date, outcome and counts; a running import can be cancelled.

### Scope

- In scope: the three steps, history, their states, locale keys, tests.
- Out of scope: API sync runs (PLG-102), scheduled imports (IMP-102), changes to the shipped import page (IMP-105, IMP-106).

### Implementation notes

- Reuse `frontend/src/components/data-table.tsx`, `chart.tsx`, `ui/button.tsx`, `lib/format.ts`, `lib/i18n.tsx`, `lib/theme.tsx` and the tokens in `frontend/src/styles.css`. Read [DESIGN.md](../DESIGN.md), [PRODUCT.md](../PRODUCT.md) and [web-frontend.md](../docs/web-frontend.md).
- Browser tests intercept `/api/v2` with Playwright `page.route`, as `frontend/tests/browser/onboarding.spec.ts` does for `/api/v1`.
- Add locale keys in a block named for this ticket to reduce merge conflicts; rebase before the PR.
- Split the page into small components; do not copy `imports.tsx` wholesale.
- Confirmation sends the preview digest and an idempotency token; a retry after an uncertain network result must reuse both.
- Polling must not move focus; announce completion once with `role="status"`.
- The longer draft spec is published as background: [docs/specs/v2-drafts/WL-P0-011.md](../docs/specs/v2-drafts/WL-P0-011.md) (sha256:c1e6032acd9488898f8a71cb0fd8edc2b8867ae4816d33a43bf4c5b9e26b8636). This ticket is written to be sufficient without it.

## Acceptance criteria

- [ ] Given a new user with one enabled source, when they upload a valid file and confirm, then they reach the analysis page without creating a portfolio, choosing a snapshot kind or entering a timestamp.
- [ ] Given the page is opened with earlier imports in history, then step 1 is current.
- [ ] Given a source the user has not enabled, then it is not offered and a link leads to the Parser Plugin Store.
- [ ] Given a preview with conflicts, then each shows old and proposed values and confirmation is disabled until every conflict has a decision.
- [ ] Given a stale or expired preview at confirmation, then the reason and "Upload again" are shown and nothing is booked.
- [ ] Given an uncertain network result on confirmation, then retry reuses the same digest and token and the import is booked once.
- [ ] Given two past imports, then their history rows differ in visible text (source, file name, date, outcome).
- [ ] Given a wrong format or an oversized file, then the message names the problem and the accepted format.
- [ ] Keyboard reachable with visible focus, one `h1` per page, labelled controls, no colour-only meaning; en-CA, zh-TW, zh-CN; light and dark; 375 px and 1024 px.

### Tests

- Browser spec `frontend/tests/browser/v2-import.spec.ts` against mocked import routes, including stale preview and retry.
- Unit tests for step derivation and conflict completeness.

## Plan

- [ ] Source and file step.
- [ ] Review with conflicts and decisions.
- [ ] Confirm, stale handling and navigation.
- [ ] History and cancel.
- [ ] Browser tests and screenshots.

## Handoff

- State: Not started. Waits on APP-011A, IMP-007E and Gate A on APP-011.
- Next step: After IMP-007E publishes the route DTOs, mock them and build step 1; until then only the layout can be prepared.
- Verify: `npm --prefix frontend run build`; `npm --prefix frontend test`; `npm --prefix frontend run check:source`; `npm --prefix frontend run test:e2e`
- Gotchas: The browser suite needs local port binding and a headless browser. If your sandbox has neither (see ENG-102), say so here and leave browser criteria unchecked.
- Open questions: None.

## Log

- 2026-11-05 planner: created in the initial backlog plan.
- 2026-11-10 planner: described the target flow per step, added criteria drawn from defects observed in the shipped import page; scope unchanged.
- 2026-11-10 planner: destination name updated to "Parser Plugin Store".
- 2026-11-10 planner: added the absent-account question to the review step by owner decision.
- 2026-11-10 planner: owner approved Gate A for the V2 MVP scope of this ticket on 2026-11-10 and released it (status ready).
