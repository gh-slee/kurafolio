---
id: IMP-007P
title: Build the ReviewBundle that the worker's prepare step passes to prepare_preview_v1
priority: P0
status: backlog
type: feature
parent: IMP-007
depends_on: []
resources: [ingestion-review-bundle]
risk: critical
size: L
agent_tier: frontier
gate: owner
gate_approval: 
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: 
updated: 2026-11-20
---

# IMP-007P: Build the ReviewBundle that the worker's prepare step passes to prepare_preview_v1

## Goal

After every member of an import set is normalized, the import worker must turn the set's stages, decisions and current references into a `ReviewBundle` (a review document and, when r7 requires one, a complete Plan) and pass it to `prepare_preview_v1`. No merged code builds one, so no set can reach a preview without a human step. Build a deterministic builder that follows the r7 reconciliation rules and reproduces the oracle review and plan vectors exactly.

## Context

- Filed on 2026-11-20 from the IMP-007F plan (PR #86), its Decision D2, option (a), which the owner chose.
- Caller: IMP-007F's PR 3 prepare step (`src/kurafolio/ingestion/worker.py`, Worker loop step 2). Under one prepare lease it reads every basis resource with `read_plan_basis_v1` (cursor paging, `limit` 50), calls this builder, checks the result with `approval.validate_review_bundle`, and passes `codec.encode(bundle)` as `p_bytes` to `prepare_preview_v1`. A prepare lease lasts at most 60 s and is never renewed (IMP-007F D6), so the builder must finish well inside one lease. IMP-007F imports this module and does not change it; this ticket does not change the worker.
- Contracts, all in the r7 bundle: [reconciliation.md](../docs/specs/imp-007-r7/reconciliation.md) (identity keys, the source revision and activity table, the snapshot and coverage table), [normalized-evidence.md](../docs/specs/imp-007-r7/normalized-evidence.md) and [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md). DTOs: `ReviewBundle` (`{version: 1, review: ReviewDocument, plan: Plan | null}` in `src/kurafolio/ingestion/contracts.py`), `ReviewDocument`, `BasisPage`, `PreparePreviewRequest` (`payload_bytes` at most 16,777,216) in [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json), `Plan` in [codec-schema.json](../docs/specs/imp-007-r7/codec-schema.json).
- Merged code to build on (`main` at `d902717`):
  - `approval.py`: `validate_review_bundle(data, *, stages)`, `verify_staged_material`, `verify_proposals`.
  - `mapping.py`: `MappingIndex`, `proposed_body`, `compatible`, `verify_target_version`.
  - `reconciliation.py`: `source_revision_key`, `project_record`, `financial_projection`, `reconcile_revision` (`RevisionDecision`), `snapshot_order`.
  - `codec.py` (`encode`, `validate`, `digest`, `sha256`) and `cursors.py`.
  - The checks in `prepare_preview_v1` (`ingestion_schema.py`, IMP-007L, with the r7-A1 to r7-A4 amendments recorded in IMP-007L), which accept or refuse a bundle against the stored stages, decisions and generation pins.
- Expected values: the oracle vectors in `tests/fixtures/ingestion/oracle.json`. Cases with review or plan vectors: `authority-only`, the four `branch-*` cases, `metadata-native` (plan only), `mixed-set`, `snapshot-historical-t1` and `snapshot-seed-t2`, plus `plan-first-use.json` and `plan-native-first-use.json`. Their inputs are the matching `*-minimal.json`, `*-decisions.json`, `*-context.json`, `*-prestate.json` and `*-discovery.json` entries. `builtin-inputs.json` holds the expected facts for the two example files (`wealthsimple_expected`, `bull_expected`) that IMP-007F's AC-04 checks, and the `large-basis-*` entries the largest basis.
- `tests/test_postgres_migration.py` drives `prepare_preview_v1` with oracle bundles (`prepare_preview_call`, the `basis_call` helpers). Those helpers show how the basis pages look for each case.
- `resources` holds a new `ingestion-review-bundle` lock. It does not overlap IMP-007F's `v2-import-worker` files or the `ingestion-schema-sql` lock.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.
- The builder lives in its own new module, `src/kurafolio/ingestion/review_bundle.py`. It takes the decoded basis pages of one prepare lease (every resource `read_plan_basis_v1` serves, with their generation pins) and returns one `ReviewBundle` value that passes `codec.validate(value, 'ReviewBundle')`.
- It follows `reconciliation.md`, `normalized-evidence.md` and `contract-appendix.md`. Where the merged helpers in `approval.py`, `mapping.py` and `reconciliation.py` implement a rule, the builder calls them; it does not change their behaviour or their tests.
- It is deterministic: the same basis gives byte-identical `codec.encode` output whatever the page size or page order of delivery. It reads no clock, randomness, environment, file, database or network. Values that do not come from the basis come from the r7 rules or from explicit arguments the caller passes.
- Finance rules: amounts stay `Decimal` strings exactly as staged; unknown values stay unknown and are never zero; no contribution is inferred from holdings or purchase spend; no wallet total or opening balance is inferred; coverage and membership stay as staged (for example `partial` and `unknown`). Every fact in the review and Plan traces to a stage, a decision or a current reference in the basis.
- It never builds a partial or guessed bundle. A basis it cannot reconcile, or a bundle over 16,777,216 encoded bytes, raises a fixed error code and returns nothing.
- It builds the largest oracle basis (`large-basis-*`) in well under one prepare lease; the acceptance bound is 10 seconds on the CI runner.
- Not in scope: the worker's prepare loop and lease handling (IMP-007F PR 3), any SQL, grant or DTO change, and the frozen r7 bundle and `oracle.json`, which stay as they are. If an oracle vector seems wrong, or a case cannot be expressed as basis pages, stop and ask.

## Acceptance criteria

- [ ] AC-IMP-007P-01: For every oracle case with a `*-review.json` or `*-plan.json` vector, a test builds the basis pages from that case's oracle inputs, and the builder's review and Plan equal the vectors byte for byte after `codec.encode`.
- [ ] AC-IMP-007P-02: Every bundle the builder produces passes `approval.validate_review_bundle`, and an opt-in real-PostgreSQL test shows that `prepare_preview_v1` accepts it for the first-use, native first-use, `branch-*`, `snapshot-*`, `authority-only` and `mixed-set` cases.
- [ ] AC-IMP-007P-03: For the stages of `examples/data/wealthsimple-holdings.csv` and `examples/data/bull-orders.csv`, the review's facts equal `wealthsimple_expected` and `bull_expected` in oracle `builtin-inputs.json`, and no contribution or wallet balance appears.
- [ ] AC-IMP-007P-04: Building twice from the same basis, and from the same basis delivered with page sizes 1, 7 and 50, gives identical bytes.
- [ ] AC-IMP-007P-05: A missing basis resource, a stage whose digest does not match its row, a decision for an unknown member or entity, pages with different generation pins, and an encoded bundle over 16,777,216 bytes are each refused with a fixed error code, and no bundle is returned.
- [ ] AC-IMP-007P-06: A static test and a test that patches the clock, randomness, environment, file and socket APIs to raise show that the module reads none of them.
- [ ] AC-IMP-007P-07: The `large-basis` oracle case builds in under 10 seconds on the CI runner.
- [ ] AC-IMP-007P-08: [review] Every fact in each produced review and Plan traces to the basis; no value is invented, rounded or defaulted to zero; a reviewer checks this against `reconciliation.md`.
- [ ] AC-IMP-007P-09: `docs/web-v2-imports.md` says what the builder decides, which review states it produces and its limits.

## Plan

- [ ] Map each oracle case to basis pages; record any case that cannot be mapped and stop.
- [ ] Builder for revisions and activities, then snapshots and coverage, then mappings and authorities, then the Plan.
- [ ] Determinism, refusal and performance tests; real-PostgreSQL acceptance through `prepare_preview_v1`.
- [ ] Docs; full suite; pull request with the independent review.

## Decisions needed

- Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes.

## Handoff

- State: Filed on 2026-11-20; backlog, waiting for the owner's Gate A and a Build plan.
- Next step: The planner reads `reconciliation.md`, the merged `approval.py`, `mapping.py`, `reconciliation.py` and `prepare_preview_v1`, maps each oracle case to basis pages, and writes the Build plan, including the builder's exact signature for IMP-007F's PR 3.
- Verify: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_ingestion_*.py' -v` and `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: IMP-007F's PR 3 waits for this ticket, and IMP-007S waits for IMP-007F, so this ticket gates activation.
- Open questions: Gate A.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #86 from the owner's decision of 2026-11-20 on "No merged code builds the ReviewBundle ... Who builds it?": the owner chose "New ticket (Recommended)": "risk critical, tier frontier, own review." (IMP-007F D2 = (a).) On the wait, the owner chose "Build now, prepare last (Recommended)": "No depends_on. Builders do PR 1 and PR 2 now; prepare and AC-04 land in a third PR once IMP-007P merges." Status backlog; no Gate A yet.
