---
id: IMP-007R
title: Sweep a lapsed normalize attempt into reupload_required
priority: P0
status: backlog
type: feature
parent: IMP-007
depends_on: []
resources: [ingestion-schema-sql]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: 
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: 
updated: 2026-11-21
---

# IMP-007R: Sweep a lapsed normalize attempt into reupload_required

## Goal

If the import worker dies while it normalizes a file, its lease lapses and nothing can finish the attempt. The member stays `receiving` or `normalizing` until the user cancels the set or it expires after 24 hours, and the user cannot upload that file again. Add a fenced SQL sweep that closes such a lapsed attempt and moves its member to `reupload_required`, so the user can upload again. The sweep releases the attempt's raw slot only under the existing proof rule; without proof the slot stays held.

## Context

- Filed on 2026-11-20 from the IMP-007F plan (PR #86), its Decision D7, option (b), which the owner chose. Until this ticket lands, IMP-007F's docs say that cancel or expiry is the recovery.
- Findings from `main` at `d902717` (`src/kurafolio/persistence/ingestion_schema.py`):
  - Only `finish_member_v1`, under a live normalize lease, moves a member to `reupload_required`. Its `reupload_required` branch closes the lease as `finished`, sets the member's state and error code, leaves the set's state and revision unchanged, and releases the raw slot only when its proofs show no live child.
  - The member trigger allows `receiving` to `reupload_required` and `normalizing` to `reupload_required`. `reserve_member_v1` accepts a member in `waiting` or `reupload_required` and, for `reupload_required`, issues fence + 1.
  - Lease states are `offered`, `active`, `finished`, `expired` and `cancelled`. A closed lease may change only its raw-slot and cleanup-proof record.
  - The raw-slot rule in the lease trigger: a slot is released once, only for an attempt that was never bound (no `token_digest`) once 120 seconds have passed since reserve, or whose recorded proofs for that fence are all `absent` or `not_created`. `cleanup_set_v1` applies the rule to terminal sets only. Releasing a slot returns one unit of the user's `raw` quota through `_quota_v1`.
  - `cancel_set_v1`, the expiry step of accept, cancel and `claim_plan_v1`, and a `rejected` finish set every `offered` or `active` lease of the set to `cancelled`.
  - `admit_stage_v1` stores at most one stage per attempt, and returns the existing stage when an identical stage of that member exists. `finish_member_v1` with `stage_admitted` requires exactly one stage stored since the attempt's offer. A swept attempt that had already stored a stage therefore needs a rule (Decision 2): otherwise a re-upload of the same file stores no new stage and its `stage_admitted` finish fails.
  - The stage rule of the `_transition_v1` trigger refuses to delete a stage row unless its set is terminal or the row's `purge_at` (the set's `expires_at`) has passed. Deleting a swept attempt's stage in a live set (Decision 2) therefore needs a narrow change to that rule.
  - `claim_plan_v1` turns some `22023` exceptions into refusal codes and ends a replay with `import_stale` raised as an exception. Work the sweep does in the same call must not be undone when the call then answers with a refusal.
- Related tickets:
  - IMP-007F's worker keeps a private journal of its attempts and launcher handles, so after a restart it can still ask the launcher for proofs. It calls `claim_plan_v1` with `work_kind: "cleanup"` on its pull loop and refuses any other `work_kind` until IMP-007V adds `prepare`. With the sweep inside `claim_plan_v1` (Decision 1), the worker needs no change, as long as the sweep runs for every `work_kind`.
  - IMP-007Q (filed in PR #85) adds a worker-fenced release of a held raw slot after a late launcher proof. The owner decided on 2026-11-21 (Q22, IMP-007Q option (b)) that it also covers attempts this sweep closed, but only from the worker process that still holds the attempt's handoff token (Decision 3).
  - IMP-007O, IMP-007Q, IMP-007T and IMP-007W share the `ingestion-schema-sql` lock with this ticket, so they build one at a time. IMP-007N is `done`; its `claim_plan_v1` change is on `main`.
- Changing the `0004` function text in place is safe only if no database outside disposable tests ran `operator migrate-ingestion` at `0004`. IMP-007O has the same check; Requirements make it a stop point here too.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md). The r7 inventory is the frozen baseline [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json). The inventory the code is tested against is the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`, checked by `tests/test_postgres_migration.py`; it is the r7 baseline plus later approved additions.
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.
- A normalize attempt is lapsed when its lease is `offered` or `active`, its `expires_at` and its member's `raw_deadline` have both passed on the database clock, no `finish_member_v1` has closed it, and its set is not terminal.
- The sweep runs with no user or operator step, inside `claim_plan_v1` (owner answer Q23). It runs on every call, whatever the request's `work_kind`, after `_guard_worker_v1` has accepted the caller and the READ COMMITTED check has passed, and before the function picks work. One call sweeps at most a fixed number of lapsed attempts, a bound set in code (the Build plan names it); later calls sweep the rest. For each lapsed attempt, in one transaction under the set lock, it:
  1. closes the lease as `expired`;
  2. moves the member to `reupload_required` with error code `import_reupload_required`, whether or not the attempt stored a stage (owner answer Q24);
  3. if the attempt stored a stage, deletes that attempt's transient stage row, so that a re-upload of the same file can store it again;
  4. leaves the set's state and revision, the other members, the stages of other attempts and all accepted data unchanged. No accepted fact, mapping, decision or preview is deleted or changed.
- The sweep's changes stand whatever the call then answers, including `no_work` and any refusal code; they are undone only when the transaction itself fails (a serialization failure, deadlock, lock timeout or cancel).
- Fencing: after the sweep, every call with the old fence or handoff token (`renew_member_v1`, `admit_stage_v1`, `finish_member_v1`) is refused with `import_stale` and changes nothing. The next `reserve_member_v1` for the member issues fence + 1. The one exception is IMP-007Q's `release_member_slot_v1`, which may still release the swept attempt's held raw slot under its own proof rule, and only when the caller is the worker process that still holds the attempt's handoff token (owner answer Q22).
- Raw slot. Never release a slot without proof that the attempt has no live child or raw buffer. The existing rule (never bound and 120 seconds past reserve, or recorded proofs for that fence all `absent` or `not_created`) stays the only release condition. A swept attempt that was never bound releases its slot once, under that rule. Every other swept attempt has no proof, so the sweep keeps `raw_slot = held`, records no proof and changes no quota. The member is then `reupload_required`, but a new reserve by that user returns `import_busy` until the slot is released: by `cleanup_set_v1` with an all-`absent` proof after the set ends, or by IMP-007Q's late-proof release, which accepts a swept attempt only from the worker process that still holds its handoff token. A restarted worker has no token, so after a restart the slot returns only at set cleanup after cancel or expiry.
- The sweep is idempotent and safe under concurrency: two sweeps, or a sweep racing a late `finish_member_v1`, `cancel_set_v1` or expiry, have exactly one effect, and a slot is released at most once. Serialization failures, deadlocks, lock timeouts and cancels are re-raised as the merged functions do, not mapped.
- No DTO in `wire-contracts.json` or `codec-schema.json` changes. No function, argument, return type, grant, table, column, index or inventory row is added, and `ingestion_schema.WORKER` is unchanged. Only the text of `claim_plan_v1` changes, plus one narrow exception in the stage rule of the `_transition_v1` trigger function: in a live set, the sweep may delete the stage of the attempt it closes, and every other stage deletion in a live set stays refused. The frozen r7 inventory stays as it is; the oracle vectors and both expected structure digests change with the function text.
- The change is made in place at revision `0004_ingestion`; the `0001` to `0003` providers stay byte-identical. Before building, confirm that no database outside disposable tests has run `operator migrate-ingestion` at `0004`. If that cannot be confirmed, stop and ask the owner whether a new revision is needed instead.
- No error, notice or log line carries raw bytes, context, a token or a handle.

## Acceptance criteria

- [ ] AC-IMP-007R-01: A lapsed attempt in a live set, for a member in `receiving` and one in `normalizing`, is swept: the lease is `expired`, the member is `reupload_required` with `import_reupload_required`, and the set's state and revision are unchanged.
- [ ] AC-IMP-007R-02: The sweep leaves untouched an attempt whose lease is still live, one whose raw deadline has not passed, one closed by `finish_member_v1`, and one whose set is terminal; a test covers each.
- [ ] AC-IMP-007R-03: After the sweep, `renew_member_v1`, `admit_stage_v1` and `finish_member_v1` with the old fence and token return `import_stale` and change nothing, and the next `reserve_member_v1` for the member issues fence + 1.
- [ ] AC-IMP-007R-04: A swept attempt that was never bound releases its raw slot once, 120 seconds after reserve. A swept bound attempt keeps `raw_slot = held` with no proof and no quota change, and the same user's next reserve returns `import_busy`; after the set is cancelled, `cleanup_set_v1` with an all-`absent` proof releases the slot exactly once.
- [ ] AC-IMP-007R-05: Two concurrent sweeps, and a sweep racing a late `finish_member_v1`, `cancel_set_v1` or set expiry, give exactly one effect, and the raw quota is returned at most once.
- [ ] AC-IMP-007R-06: An attempt that stored a stage before it lapsed is swept to `reupload_required` and its stage row is deleted; no accepted fact, mapping, decision, preview or stage of another attempt changes; a later upload of the same file in that member reaches `admitted`; and deleting a stage of a live set in any other way is still refused.
- [ ] AC-IMP-007R-07: The frozen r7 inventory and every DTO are unchanged; no function, grant or inventory row is added and `ingestion_schema.WORKER` is unchanged; only the text of `claim_plan_v1` and `_transition_v1` changes, with the oracle vectors and both expected structure digests, and `tests/test_postgres_migration.py` passes against them.
- [ ] AC-IMP-007R-08: The pull request records the evidence that no database outside disposable tests ran `operator migrate-ingestion` at `0004`, or the owner's decision to use a new revision.
- [ ] AC-IMP-007R-09: Opt-in real-PostgreSQL tests cover AC-01 to AC-06 and AC-11.
- [ ] AC-IMP-007R-10: `docs/web-v2-imports.md` describes the sweep, that it runs inside `claim_plan_v1` and so needs a running worker, and that a slot without proof stays held until cleanup unless the worker process that holds the attempt's token gets a late proof (IMP-007Q), replacing the "cancel or expiry is the recovery" text where it becomes untrue.
- [ ] AC-IMP-007R-11: A `claim_plan_v1` call with `work_kind: "cleanup"` sweeps lapsed attempts, as a `prepare` call does; one call sweeps no more than the fixed bound and later calls sweep the rest; a call refused by `_guard_worker_v1`, or run outside READ COMMITTED, sweeps nothing; and the sweep's changes stand when the call answers `no_work`, `already_claimed` or a refusal code.

## Plan

- [x] Owner answers Decisions 1 to 3 (2026-11-21: 1 = (a), 2 = (a), 3 = yes for the running worker only).
- [ ] Owner gives Gate A; planner writes the Build plan from the merged SQL and whichever of IMP-007O, IMP-007Q and IMP-007W have merged.
- [ ] Sweep in `claim_plan_v1`, the stage-delete exception in `_transition_v1`, oracle vectors and structure digests.
- [ ] Real-PostgreSQL tests for each acceptance ID; `0004` evidence; docs.

## Decisions needed

Only the owner answers. The planner recommends an option for each.

1. Where the sweep runs. (a) Inside `claim_plan_v1`, before it picks work, for a bounded number of attempts per call. It needs no new function or grant, and the worker already calls it every 1 to 2 seconds; IMP-007N also changes `claim_plan_v1`, and the shared lock keeps the two apart. (b) A new worker function that IMP-007F's worker calls on its pull loop. It needs a new function, a grant and a worker change in IMP-007F's files. (c) Inside `reserve_member_v1` and `cancel_set_v1`, so that it runs when the user acts. It needs no worker, but a set stays stuck until the user does something, and a client may not offer a retry for a member shown as `normalizing`. The planner recommends (a).
   **Resolved 2026-11-21: (a).** Asked "IMP-007R: where does the sweep that turns a lapsed normalize attempt into reupload_required run?", the owner chose "Inside claim_plan_v1 (Recommended)". Requirements state it; the sweep runs for every `work_kind`, so it works with IMP-007F's cleanup-only worker.
2. A lapsed attempt that stored a stage before it lapsed. (a) The sweep makes it `reupload_required`, as the owner's words for this ticket say ("turns a lapsed normalize attempt into reupload_required"), and deletes that attempt's transient stage row, so that a re-upload of the same file can store it again. Stages are transient, and no accepted evidence is deleted. (b) The sweep finishes it as `stage_admitted` would: r7 makes a member `reupload_required` only when the bytes are lost before the parser result is admitted, and an admitted stage is not lost. The member becomes `admitted`, and the set moves on when all members are admitted. This departs from the owner's wording and makes the sweep do a finish's work. The planner recommends (a), which keeps the owner's wording and one simple outcome for every swept attempt.
   **Resolved 2026-11-21: (a).** Asked "IMP-007R: an attempt that had already stored its parsed stage before the worker died. What does the sweep do with it?", the owner chose "reupload_required (Recommended)": the sweep deletes that attempt's transient stage row, and no accepted evidence is deleted. The stage trigger refuses that delete in a live set today, so Requirements allow one narrow exception for it.
3. Whether IMP-007Q's late-proof release also covers an attempt this sweep closed, so that IMP-007F's restarted worker can use its journal to free the slot before the set ends. (a) Yes; the IMP-007Q plan says so and its tests include a swept attempt. (b) No; a swept bound attempt's slot returns only at set cleanup. The planner recommends (a), recorded in IMP-007Q's plan, not in this ticket's code.
   **Resolved 2026-11-21: yes, narrower than (a).** The owner was asked who may later release a held raw slot with a launcher proof when an upload attempt was closed by the sweep or the worker restarted, given that the release is fenced on the attempt's one-use handoff token, which only the running worker process holds. The owner chose "Running worker only (Recommended)": "IMP-007Q (b): the release also accepts a sweep-closed attempt, but only from the worker process that still holds the token (e.g. it survived a long DB outage). A restarted worker can't; that slot returns at set cleanup after cancel/expiry. Keeps finish's fencing." A restarted worker therefore cannot use its journal to free the slot, unlike option (a) as first written. IMP-007Q's code carries the rule; this ticket's Requirements name the exception to its fencing.
4. Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, with the answers to items 1 to 3 written into them, or asks for changes.

## Handoff

- State: Filed on 2026-11-20; backlog. Decisions 1 to 3 were resolved on 2026-11-21; waiting for Gate A and a Build plan. Builds before, after or between IMP-007O, IMP-007Q, IMP-007T and IMP-007W, one at a time on the `ingestion-schema-sql` lock.
- Next step: The owner gives Gate A; the planner then writes the Build plan from the merged SQL.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: Never release a slot without proof that the attempt has no live child or raw buffer. A lapsed lease can expire before its raw deadline; the sweep waits for both. A refusal raised as an exception inside `claim_plan_v1` must not roll back the sweep.
- Open questions: Gate A (Decisions needed item 4).

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #86 from the owner's decision of 2026-11-20 on "IMP-007F D7: if the worker process dies mid-normalize ... What should happen?": the owner chose "SQL sweep ticket (Recommended)": "file a SQL ticket (IMP-007M family) for a fenced sweep that turns a lapsed normalize attempt into reupload_required; until it lands, docs say cancel or expiry is the recovery." Shares `ingestion-schema-sql` with IMP-007N, IMP-007O and IMP-007Q. Status backlog; no Gate A yet.
- 2026-11-21 claude-code/opus-5.5: recorded the owner's answers of 2026-11-21 in plan pull request #95. Decision 1: asked "IMP-007R: where does the sweep that turns a lapsed normalize attempt into reupload_required run?", the owner chose "Inside claim_plan_v1 (Recommended)". Decision 2: asked "IMP-007R: an attempt that had already stored its parsed stage before the worker died. What does the sweep do with it?", the owner chose "reupload_required (Recommended)": the sweep deletes that attempt's transient stage row; no accepted evidence is deleted. Decision 3: asked "IMP-007Q (late-proof slot release) and IMP-007R (crash sweep) disagree. When an upload attempt was closed by the sweep, or the worker restarted, who may later release its held raw slot with a launcher proof? The release call is fenced on the attempt's one-use handoff token, which only the running worker process holds (the journal never stores it)." (Q22), the owner chose "Running worker only (Recommended)": "IMP-007Q (b): the release also accepts a sweep-closed attempt, but only from the worker process that still holds the token (e.g. it survived a long DB outage). A restarted worker can't; that slot returns at set cleanup after cancel/expiry. Keeps finish's fencing." Gated changes: the sweep runs inside `claim_plan_v1` on every call whatever its `work_kind`, after the guard, with a fixed per-call bound named in the Build plan; a swept attempt that stored a stage becomes `reupload_required` and its stage row is deleted; the sweep runs after the guard and the READ COMMITTED check; a new bullet keeps the sweep's changes when the call answers a refusal (the merged exception block would roll them back); the fencing bullet names IMP-007Q's release as the one exception; the raw-slot bullet states the running-worker rule; the inventory bullet says only `claim_plan_v1` and a narrow stage-delete exception in `_transition_v1` change, since the merged stage trigger refuses that delete in a live set; AC-06, AC-07, AC-09 and AC-10 rewritten; new AC-11 for the `cleanup` call, the bound and refusal answers. Spec hash sha256:3d4a9432b9dc9d88dc6408dad9d9007a22c09c2e0bc2bf0d9043d4ac29ec8202 becomes sha256:8b2ab2f1293f7e513e1415f7c6531ae33fe4d3503a03a8aa3018a748e7af2952; still backlog, no Gate A.
