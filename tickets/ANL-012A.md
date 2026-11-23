---
id: ANL-012A
title: Define the V2 analysis read contract for securities, crypto and total
priority: P0
status: ready
type: feature
parent: ANL-012
depends_on: [ANL-008]
resources: [calculation-contract]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-10, V2 MVP scope as written in this ticket"
review: independent
branch:
pr:
spec:
spec_approved: sha256:53db5ddc3a935a30bdbdefb6bc5d90d43426429e417c2ebb3db32784d205d4ee
updated: 2026-11-18
---

# ANL-012A: Define the V2 analysis read contract for securities, crypto and total

## Goal

The three V2 analysis pages need one versioned read contract so they can be built in parallel with confidence and tested against fixed numbers. Today ANL-012 bundles this contract with all three pages. This child delivers only the endpoints and DTOs.

## Context

### Current behaviour

- No `/api/v2/analysis` route exists (`src/kurafolio/web_v2/api.py:26-37` lists all V2 routes).
- The shipped pages read a frozen report (`GET /api/v1/portfolios/{id}/reports/{report_id}`, `src/kurafolio/web/reports.py:293`); its DTO is edition-based and cannot refresh.
- Positions come from ANL-008 and quotes and FX from MKT-009.

## Requirements

### Expected behaviour

- `GET /api/v2/analysis/securities`, `/crypto` and `/total`, each taking `currency`.
- Every response carries: a calculation identifier, fact generation, valuation time, report currency, exact decimal strings in native and converted currency, `known_subtotal`, a nullable `complete_total`, source, quote and FX dates, and typed coverage or assumption codes.
- A KPI that cannot be computed is a typed "unavailable" status with a reason, never zero.
- Responses are tenant-scoped and cache keys include user, currency and generation.

### Scope

- In scope: the three endpoints, DTOs, OpenAPI, fixed-oracle tests.
- Out of scope: exposures (ETF-010), exports (RPT-013A), refresh scheduling (MKT-009), any page.

### Implementation notes

- DTO and error conventions: `src/kurafolio/web_v2/schemas.py`. Decimal rules: [canonical-domain.md](../docs/canonical-domain.md).
- Unknown is never zero and CAD, USD and TWD are alternative equivalents, never additive (AGENTS.md).
- The frontend types are generated: see `docs/web-frontend.md` lines 130-140 for `scripts/export_web_schema.py` and `openapi-typescript`. Decide whether V2 gets its own generated file.
- Acceptance numbers come from the golden cases referenced by ANL-008 and the original ANL-012 criteria, in [docs/golden-cases.md](../docs/golden-cases.md) (sha256:f7adca063ff68fe0502066608fc6fad6b1f818244679190b3e7cdcf3020e5594).

### Owner decisions recorded 2026-11-10

- Each analysis response includes a daily value series revalued with fetched prices, not only import dates. Days without a price carry the last known price and are marked.
- Securities responses expose book cost and unrealized gain where the source provided cost, as a typed "unavailable" otherwise. Cash is a separate class and a separate line in Total.
- Crypto quantity is purchases minus sales reported by the same exchange file; the response says when sales were counted.
- Assets are classified by asset class, not institution. A Bitcoin ETF is in securities.
- MVP order (owner: a usable V2 as soon as possible): the first version may value securities from the import's own market values and Bitcoin from the existing live price, before MKT-009 delivers stock quotes. The decision below is answered yes. This ticket may therefore start after ANL-008 for that first version; stored live quotes follow in MKT-009B, more currencies in MKT-009C and the daily series in MKT-009D, each of which extends this contract.

## Acceptance criteria

- [ ] AC-ANL-012A-01: Given only a securities import, then `/securities` and `/total` match the fixed oracle right after the commit generation and `/crypto` reports "no eligible acquisitions" without a zero value.
- [ ] AC-ANL-012A-02: Given securities and Bitcoin acquisitions, then `/total` counts Bitcoin once and equals the oracle in each supported currency.
- [ ] AC-ANL-012A-03: Given a missing quote or FX rate, then `known_subtotal` is returned, `complete_total` is null and the affected rows carry a reason code.
- [ ] AC-ANL-012A-04: Given user A, then no parameter returns user B's data.
- [ ] AC-ANL-012A-05: OpenAPI lists the routes and every field; decimal values are strings.

### Tests

- Opt-in PostgreSQL tests with independently derived oracles.
- HTTP contract tests in the style of `tests/test_web_v2_api.py`.

## Plan

- [x] Owner Gate A on the contract (2026-11-10).
- [ ] DTOs and OpenAPI.
- [ ] Service wiring to positions and references.
- [ ] Oracle tests; independent review.

## Decisions needed

None open. Answered by the owner on 2026-11-10: yes, the first version may value securities from the import's own market values, marked "as of the source file", or from a live quote where the MKT-009A adapter is enabled.

## Handoff

- State: Not started. Gate A recorded 2026-11-10. ANL-008 is done. The Build plan and the owner's answers of 2026-11-22 are in the plan pull request #106; the owner chose to wait on IMP-007E for the ingestion runtime profile.
- Next step: After #106 merges and IMP-007E is done, claim the ticket and follow the Build plan on `main`.
- Verify: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_web_v2_api -v` with the opt-in identity environment from [web-v2-identity.md](../docs/web-v2-identity.md)
- Gotchas: Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.
- Open questions: None.

## Log

- 2026-11-10 planner: created from the UI/UX feature inventory (tickets/UX_FEATURE_INVENTORY.md).
- 2026-11-10 planner: recorded owner decisions on the daily series, cost and gain, cash, sales and the MVP-first order.
- 2026-11-10 planner: owner approved Gate A for the V2 MVP scope of this ticket on 2026-11-10 and released it (status ready).
- 2026-11-10 planner: dependency on MKT-009 removed for the first version by the owner's MVP decision; live stock quotes and the daily series are added when MKT-009 and MKT-009A land.
- 2026-11-11 planner: named the MKT-009 children that extend this contract after the MVP.
- 2026-11-13 planner: removed the answered decision and the stale gate wording; the ticket waits only on ANL-008.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved "Expected behaviour", "Scope", "Implementation notes" and "Owner decisions recorded 2026-11-10" from Context into Requirements and numbered the acceptance criteria AC-ANL-012A-01 to 05. Spec hash sha256:53db5ddc3a935a30bdbdefb6bc5d90d43426429e417c2ebb3db32784d205d4ee, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:53db5ddc3a935a30bdbdefb6bc5d90d43426429e417c2ebb3db32784d205d4ee.
- 2026-11-22 claude-code/opus-5.5: at the owner's request ("Yes, separate PR"), refreshed the stale Handoff and moved this ticket to step 3 of the roadmap's Step 1, after IMP-007E. No gated section changed.
