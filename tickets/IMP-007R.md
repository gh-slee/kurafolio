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
updated: 2026-11-20
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
- Related tickets:
  - IMP-007F's worker keeps a private journal of its attempts and launcher handles, so after a restart it can still ask the launcher for proofs. It does not call any sweep.
  - IMP-007Q (filed in PR #85) adds a worker-fenced release of a held raw slot after a late launcher proof. Whether that release also covers attempts this sweep closed is Decision 3.
  - IMP-007N, IMP-007O and IMP-007Q share the `ingestion-schema-sql` lock with this ticket, so they build one at a time.
- Changing the `0004` function text in place is safe only if no database outside disposable tests ran `operator migrate-ingestion` at `0004`. IMP-007O has the same check; Requirements make it a stop point here too.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md). The r7 inventory is the frozen baseline [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json). The inventory the code is tested against is the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`, checked by `tests/test_postgres_migration.py`; it is the r7 baseline plus later approved additions.
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.
- A normalize attempt is lapsed when its lease is `offered` or `active`, its `expires_at` and its member's `raw_deadline` have both passed on the database clock, no `finish_member_v1` has closed it, and its set is not terminal.
- The sweep runs with no user or operator step, from the place Decision 1 chooses. For each lapsed attempt, in one transaction under the set lock, it:
  1. closes the lease as `expired`;
  2. moves the member to `reupload_required` with error code `import_reupload_required`, except as Decision 2 decides for an attempt that stored a stage;
  3. leaves the set's state and revision, the other members, the stages of other attempts and all accepted data unchanged, apart from what Decision 2 needs for an attempt that stored a stage.
- Fencing: after the sweep, every call with the old fence or handoff token (`renew_member_v1`, `admit_stage_v1`, `finish_member_v1`) is refused with `import_stale` and changes nothing. The next `reserve_member_v1` for the member issues fence + 1.
- Raw slot. Never release a slot without proof that the attempt has no live child or raw buffer. The existing rule (never bound and 120 seconds past reserve, or recorded proofs for that fence all `absent` or `not_created`) stays the only release condition. A swept attempt that was never bound releases its slot once, under that rule. Every other swept attempt has no proof, so the sweep keeps `raw_slot = held`, records no proof and changes no quota. The member is then `reupload_required`, but a new reserve by that user returns `import_busy` until the slot is released: by `cleanup_set_v1` with an all-`absent` proof after the set ends, or by IMP-007Q's late-proof release if Decision 3 extends it to swept attempts.
- The sweep is idempotent and safe under concurrency: two sweeps, or a sweep racing a late `finish_member_v1`, `cancel_set_v1` or expiry, have exactly one effect, and a slot is released at most once. Serialization failures, deadlocks, lock timeouts and cancels are re-raised as the merged functions do, not mapped.
- No DTO in `wire-contracts.json` or `codec-schema.json` changes. Only the functions, grants and inventory entries Decision 1 needs change; the frozen r7 inventory stays as it is, and the oracle inventory and the expected structure digests change with them.
- The change is made in place at revision `0004_ingestion`; the `0001` to `0003` providers stay byte-identical. Before building, confirm that no database outside disposable tests has run `operator migrate-ingestion` at `0004`. If that cannot be confirmed, stop and ask the owner whether a new revision is needed instead.
- No error, notice or log line carries raw bytes, context, a token or a handle.

## Acceptance criteria

- [ ] AC-IMP-007R-01: A lapsed attempt in a live set, for a member in `receiving` and one in `normalizing`, is swept: the lease is `expired`, the member is `reupload_required` with `import_reupload_required`, and the set's state and revision are unchanged.
- [ ] AC-IMP-007R-02: The sweep leaves untouched an attempt whose lease is still live, one whose raw deadline has not passed, one closed by `finish_member_v1`, and one whose set is terminal; a test covers each.
- [ ] AC-IMP-007R-03: After the sweep, `renew_member_v1`, `admit_stage_v1` and `finish_member_v1` with the old fence and token return `import_stale` and change nothing, and the next `reserve_member_v1` for the member issues fence + 1.
- [ ] AC-IMP-007R-04: A swept attempt that was never bound releases its raw slot once, 120 seconds after reserve. A swept bound attempt keeps `raw_slot = held` with no proof and no quota change, and the same user's next reserve returns `import_busy`; after the set is cancelled, `cleanup_set_v1` with an all-`absent` proof releases the slot exactly once.
- [ ] AC-IMP-007R-05: Two concurrent sweeps, and a sweep racing a late `finish_member_v1`, `cancel_set_v1` or set expiry, give exactly one effect, and the raw quota is returned at most once.
- [ ] AC-IMP-007R-06: An attempt that stored a stage before it lapsed ends as Decision 2 decides, and a later upload of the same file in that member can reach `admitted`.
- [ ] AC-IMP-007R-07: The frozen r7 inventory and every DTO are unchanged; the oracle inventory and expected structure digests change only as Decision 1 needs, and `tests/test_postgres_migration.py` passes against them.
- [ ] AC-IMP-007R-08: The pull request records the evidence that no database outside disposable tests ran `operator migrate-ingestion` at `0004`, or the owner's decision to use a new revision.
- [ ] AC-IMP-007R-09: Opt-in real-PostgreSQL tests cover AC-01 to AC-06.
- [ ] AC-IMP-007R-10: `docs/web-v2-imports.md` describes the sweep, when it runs, and that a slot without proof stays held until cleanup, replacing the "cancel or expiry is the recovery" text where it becomes untrue.

## Plan

- [ ] Answer Decisions 1 to 3 with the owner; planner writes the Build plan from the merged SQL and the merged IMP-007N, IMP-007O and IMP-007Q changes.
- [ ] Sweep SQL, trigger checks, inventory and structure digests.
- [ ] Real-PostgreSQL tests for each acceptance ID; `0004` evidence; docs.

## Decisions needed

Only the owner answers. The planner recommends an option for each.

1. Where the sweep runs. (a) Inside `claim_plan_v1`, before it picks work, for a bounded number of attempts per call. It needs no new function or grant, and the worker already calls it every 1 to 2 seconds; IMP-007N also changes `claim_plan_v1`, and the shared lock keeps the two apart. (b) A new worker function that IMP-007F's worker calls on its pull loop. It needs a new function, a grant and a worker change in IMP-007F's files. (c) Inside `reserve_member_v1` and `cancel_set_v1`, so that it runs when the user acts. It needs no worker, but a set stays stuck until the user does something, and a client may not offer a retry for a member shown as `normalizing`. The planner recommends (a).
2. A lapsed attempt that stored a stage before it lapsed. (a) The sweep finishes it as `stage_admitted` would, because r7 makes a member `reupload_required` only when the bytes are lost before the parser result is admitted, and an admitted stage is not lost. The member becomes `admitted`, and the set moves on when all members are admitted. (b) The sweep makes it `reupload_required` and deletes that attempt's transient stage row, so that a re-upload of the same file can store it again. The planner recommends (a).
3. Whether IMP-007Q's late-proof release also covers an attempt this sweep closed, so that IMP-007F's restarted worker can use its journal to free the slot before the set ends. (a) Yes; the IMP-007Q plan says so and its tests include a swept attempt. (b) No; a swept bound attempt's slot returns only at set cleanup. The planner recommends (a), recorded in IMP-007Q's plan, not in this ticket's code.
4. Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, with the answers to items 1 to 3, or asks for changes.

## Handoff

- State: Filed on 2026-11-20; backlog, waiting for the owner's answers, Gate A and a Build plan. Builds after IMP-007N, IMP-007O and IMP-007Q, or between them, one at a time on the `ingestion-schema-sql` lock.
- Next step: The owner answers Decisions 1 to 3 and gives Gate A; the planner then writes the Build plan from the merged SQL.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: Never release a slot without proof that the attempt has no live child or raw buffer. A lapsed lease can expire before its raw deadline; the sweep waits for both.
- Open questions: Decisions needed items 1 to 4.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #86 from the owner's decision of 2026-11-20 on "IMP-007F D7: if the worker process dies mid-normalize ... What should happen?": the owner chose "SQL sweep ticket (Recommended)": "file a SQL ticket (IMP-007M family) for a fenced sweep that turns a lapsed normalize attempt into reupload_required; until it lands, docs say cancel or expiry is the recovery." Shares `ingestion-schema-sql` with IMP-007N, IMP-007O and IMP-007Q. Status backlog; no Gate A yet.
