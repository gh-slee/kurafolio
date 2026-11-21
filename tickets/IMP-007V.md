---
id: IMP-007V
title: Add the import worker's prepare step that brings a normalized set to a preview
priority: P0
status: backlog
type: feature
parent: IMP-007
depends_on: [IMP-007F, IMP-007P]
resources: [v2-import-worker]
risk: critical
size: M
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

# IMP-007V: Add the import worker's prepare step that brings a normalized set to a preview

## Goal

After every file of an import set is normalized, and again after the user answers the review's questions, the import worker must build the set's preview without a human step. Add the worker's prepare step: it claims the set's prepare lease, reads the basis, builds the `ReviewBundle` with IMP-007P's builder and passes it to `prepare_preview_v1`. A worker whose lease has lapsed must not publish a preview. With this ticket, an uploaded file reaches a preview that the user can confirm.

## Context

- Filed on 2026-11-20 in plan pull request #86 from the owner's decision Q16, which moved the prepare step, the former AC-IMP-007F-04 and the prepare case of AC-IMP-007F-05 out of IMP-007F, so that IMP-007F (worker and launcher) can finish without waiting for IMP-007P.
- Builds on IMP-007F's worker (`src/kurafolio/ingestion/worker.py`, `worker_sql.py`). Under IMP-007F's plan, `WorkerSQL.CALLS` holds six names without `read_plan_basis_v1` and `prepare_preview_v1`, `WorkerSQL.call` refuses a `claim_plan_v1` request whose `work_kind` is not `"cleanup"`, and the worker does no prepare work: a normalized set waits in `NORMALIZING` until the user cancels it or it expires. Both tickets hold the `v2-import-worker` resource. The Build plan is written from IMP-007F's merged code.
- Builder: IMP-007P's `src/kurafolio/ingestion/review_bundle.py`. This ticket imports it and does not change it.
- Merged SQL (`main` at `d902717`, `src/kurafolio/persistence/ingestion_schema.py`, IMP-007L):
  - `claim_plan_v1{work_kind: "prepare"}` (`_PREPARE_CLAIM_SQL`) picks, oldest first, a set in `NORMALIZING` or `RECONCILING` that has not expired, has a stored prepare session, has every member `admitted` with its stage, and has no live prepare lease. The lease lasts until `LEAST(now + 60 s, set expiry, the user's session expiry, the session's last activity + 1800 s)`, cut to whole seconds, and cannot be renewed. A candidate whose user session changed or ended is skipped. A replay with the same `claim_request_id` and token returns `already_claimed`.
  - `read_plan_basis_v1` serves six resources (`inputs`, `entities`, `mappings`, `revisions`, `heads`, `authorities`) in pages of at most 50 rows and 4,210,688 bytes, each carrying the set revision and the accepted, mapping and control generations. It keeps no replay cache: a retry regenerates the page under the same live lease and pins, or returns `import_stale` (`wire-contracts.json#/basis_read_policy`).
  - `prepare_preview_v1` takes `p_bytes` = the encoded `ReviewBundle` (at most 16,777,216 bytes) and a `PreparePreviewRequest` with `bundle_digest`, `payload_bytes`, `expected_set_revision` and the three generations. It returns a `PreviewAck` with state `NEEDS_MAPPING`, `CONFLICT` or `READY`. A stale fence, token or pin is refused.
  - `decide_set_v1` moves a reviewed set to `RECONCILING` with revision + 1, cancels any live prepare lease of the set and bumps the control generation, so the worker prepares the new revision.
  - No worker function reports that a set cannot be prepared. A bundle the worker cannot build leaves the set where it is (Decision 1).
- Tests to reuse: `tests/test_postgres_migration.py` (`prepare_preview_call`, the `basis_call` helpers, `test_renew_refuses_a_lapsed_or_foreign_lease` for forcing expiry with `session_replication_role=replica`) and IMP-007F's `tests/test_postgres_worker.py` and `tests/test_ingestion_worker.py`. Expected values for the two example files: oracle `builtin-inputs.json` (`wealthsimple_expected`, `bull_expected`). The IMP-007F plan had these AC-01 cases, which the Build plan here should keep (the oracle wins if it disagrees):
  - `examples/data/wealthsimple-holdings.csv`, set created and reserved through `create_set_v1` and `reserve_member_v1` (`reserve`, then `bind`) or the IMP-007U route, a fake launcher running the child logic in-process, and a test API peer that posts the handoff: the set reaches a preview with no test step between upload and preview; after the decisions the review requires (if any) through `decide_set_v1`, the preview is READY and `accept_preview_v1` books 3 accounts and 6 positions, CAD native sum 565, USD native sum 150, `as_of` 2024-02-01T10:00:00-05:00, coverage `partial`, membership `unknown`.
  - `examples/data/bull-orders.csv`, the same way: 2 accounts, 3 completed orders, 2 completed buys, BTC 0.00400000, LBTC 0.00300000, purchase cost CAD 700.00, funding CAD 1000.00, contribution boundary `unclassified`, no wallet truth; no contribution and no wallet balance booked.
  - A Docker variant of both through the real launcher and child, with the same values.
- The upload route that hands files to the worker is IMP-007U's (filed in plan pull request #87). AC-01 allows the SQL functions while it is not merged.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance. Use the claim's `isolation_id` and `port_base`.
- Scope: the prepare step of IMP-007F's worker. Add `read_plan_basis_v1` and `prepare_preview_v1` to the worker's fixed list of SQL functions and allow `claim_plan_v1` with `work_kind: "prepare"`. Every other rule of IMP-007F's worker stays as it is.
- The prepare loop: claim with `claim_plan_v1{work_kind: "prepare"}` using a fresh 256-bit token and a fresh `claim_request_id` for each claim, and never reuse either. Under the claimed lease, read every basis resource with `read_plan_basis_v1`, following each cursor to the end. Build the bundle with IMP-007P's builder, check it with `approval.validate_review_bundle`, and call `prepare_preview_v1` with the encoded bundle and the pins from the lease and the basis pages. Every call carries the lease's fence and token.
- One lease covers the whole step and is never renewed (IMP-007F decision D6). If less than 5 seconds remain before the lease's `expires_at`, the worker gives up the step: it sends no further call with that fence, and a later claim after expiry starts again from the basis.
- A worker whose lease has lapsed, or whose set changed revision or generation, must not publish: the database refuses a stale fence, token or pin, and the worker treats the refusal as the end of the step.
- The worker sends only a bundle that the builder returned and the check accepted, built from basis pages read under one lease with one set of pins. A refusal by the builder or the check sends nothing; the set stays as it was (Decision 1). The worker never edits, completes or guesses a bundle.
- Basis pages and the bundle live only in memory for the step and are dropped when the step ends. Nothing from them is written to the journal, a file or a log. Logs carry only the function name, `request_id`, set ID and a fixed code.
- Not in scope: the builder's content (IMP-007P), any SQL, grant or DTO change, the upload route (IMP-007U), the launcher, and renewal of prepare leases. The frozen r7 bundle and `oracle.json` stay as they are.

## Acceptance criteria

- [ ] AC-IMP-007V-01: Given the example Wealthsimple holdings file and the example exchange orders file uploaded through the IMP-007U upload route (or its SQL functions if IMP-007U is not merged), the worker brings each set to a preview without a human step, and a confirmation then books the facts.
- [ ] AC-IMP-007V-02: A worker that stalls while it holds a prepare lease cannot publish after the lease expires: a second worker claims the set with a new fence, the first worker's late `prepare_preview_v1` is refused, and exactly one preview exists.
- [ ] AC-IMP-007V-03: Each prepare step runs under one lease that is never renewed; when less than 5 seconds of the lease remain, the worker sends no further call with that fence, and a later claim builds the preview from a fresh basis.
- [ ] AC-IMP-007V-04: After the user's decisions move a set to `RECONCILING`, the worker prepares the new revision without a human step, and a call with the earlier lease's fence is refused.
- [ ] AC-IMP-007V-05: A bundle that IMP-007P's builder or `approval.validate_review_bundle` refuses is never sent; no preview is created and the set's state, revision and generations are unchanged.
- [ ] AC-IMP-007V-06: The worker's fixed list of SQL functions gains exactly `read_plan_basis_v1` and `prepare_preview_v1`, `claim_plan_v1` accepts `work_kind: "prepare"`, and every other rule checked by AC-IMP-007F-01 still holds.
- [ ] AC-IMP-007V-07: No basis page, bundle byte or financial value appears in the worker journal, a file or a log after a prepare step, whether it succeeded, was refused or gave up.
- [ ] AC-IMP-007V-08: `docs/web-v2-imports.md` and `docs/web-v2-import-worker.md` say that sets now reach a preview without a human step, and no longer say that sets stop after normalization.

## Plan

- [ ] Planner writes the Build plan from the merged IMP-007F and IMP-007P code, after Gate A and Decision 1.
- [ ] Prepare loop, the two new `CALLS` names and the `prepare` claim kind.
- [ ] Unit and real-PostgreSQL tests per acceptance ID, including the Docker variant of AC-01 through the real launcher.
- [ ] Docs; full suite; pull request with the independent review.

## Decisions needed

Only the owner answers. The planner recommends an option.

1. What happens when the builder or the check refuses a set's basis. No worker function reports that a set cannot be prepared, and `claim_plan_v1` hands out the oldest eligible set first, so the same set is claimed again each time its lease lapses (about once a minute) until the user cancels it or it expires. Other sets are still served while its lease is live. (a) Accept that for the MVP: the worker logs a fixed code on each attempt, and the docs say that a set that cannot be prepared waits until it is cancelled or expires. (b) File a SQL ticket for a worker function that rejects the set with a fixed code under the prepare lease, so the user sees the failure at once; it shares the `ingestion-schema-sql` lock with IMP-007N, IMP-007O, IMP-007Q and IMP-007R. The planner recommends (a) now and (b) as a follow-up if refusals show up in practice.
2. Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes.

## Handoff

- State: Filed on 2026-11-20; backlog, waiting for the owner's Gate A, the answer to Decision 1 and a Build plan. Depends on IMP-007F and IMP-007P; neither is merged.
- Next step: After IMP-007F and IMP-007P merge, the planner reads their merged code and writes the Build plan, including the exact builder call, the paging order of the six basis resources and the test table per acceptance ID.
- Verify: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_ingestion_*.py' -v` and `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_postgres_*.py' -v`
- Gotchas: A prepare lease ends at the user's session expiry or 1800 s after the session's last activity if that is sooner than 60 s, so a set whose user signed out is not claimed. Do not add renewal for prepare leases (D6).
- Open questions: Decisions needed items 1 and 2.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #86 from the owner's decision of 2026-11-20 on "IMP-007F problem: the repo's pr-check fails any PR from the ticket's branch unless the ticket is done ... How should this work?": the owner chose "Split prepare out (Recommended)": "Move the prepare step and AC-04 to a new ticket (IMP-007V) that depends on IMP-007F and IMP-007P. IMP-007F (worker + launcher) finishes after PR 2, unblocking IMP-007S. Same pattern as the IMP-007E upload split." AC-IMP-007V-01 is the former AC-IMP-007F-04, with "the IMP-007E routes (or their SQL functions if 007E is not merged)" changed to the IMP-007U upload route, which now owns upload; AC-IMP-007V-02 is the prepare case of AC-IMP-007F-05. Status backlog; no Gate A yet.
