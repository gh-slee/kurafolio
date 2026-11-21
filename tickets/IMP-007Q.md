---
id: IMP-007Q
title: Release a held raw slot after a late launcher proof
priority: P0
status: backlog
type: feature
parent: IMP-007
depends_on: [IMP-007M, IMP-007F]
resources: [ingestion-schema-sql, v2-import-worker]
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

# IMP-007Q: Release a held raw slot after a late launcher proof

## Goal

When `finish_member_v1` ends a normalize attempt without proof that its parser child and raw buffer are gone, the attempt keeps the user's only raw slot. Every further upload by that user then returns `import_busy` until the set ends and its cleanup proves the slot free, which takes 24 hours or more unless the user cancels. Add a worker-fenced SQL function that takes a later launcher proof for that exact attempt in a live set and releases the slot under the same proof rule as finish, and have the import worker call it when the proof arrives. A slot is never released without proof.

## Context

- Filed on 2026-11-20 from IMP-007M (plan PR #85). The owner chose "B with F" for IMP-007M decision 1. This ticket is option B. Option F, the worker waiting for its proof before `finish`, is IMP-007F PR 1 (plan PR #86, normalize step 6). The owner also decided that the release covers a slot held after a `stage_admitted` finish (IMP-007M decision 2), and that the worker's call to the new function belongs here, not in IMP-007F (IMP-007F D8).
- Merged behaviour this builds on (`main` at `d902717`, `src/kurafolio/persistence/ingestion_schema.py`):
  - Slot scope. `QUOTA_LIMITS['raw']['leases']` is `(1, 4)`: one held raw slot per user and portfolio, four per instance. `reserve_member_v1` (action `reserve`) calls `_quota_v1(tenant,portfolio,'raw',1,0)`, which raises `import_busy` while the slot is held.
  - Finish. In `_lease_ddl(..., 'finish')`, `cleaned` is true only when at least one proof was sent and every proof says `absent` or `not_created`. Only then does finish set `raw_slot='released'` and call `_quota_v1(...,'raw',-1,0)`; otherwise the lease is `finished` with `raw_slot='held'`, for all three outcomes. Proofs must repeat the finish request's job and fence (`_proofs_shape_sql(3, same_job=True)`). The acknowledgement is a `FinishAck` with `cleanup_complete` equal to `cleaned`.
  - Once a normalize lease is `finished`, finish answers only the same request (stored acknowledgement) and returns `import_stale` for any other. No function accepts a later proof for a finished attempt in a live set.
  - Finish requires the set to be `RECEIVING`. The last member's `stage_admitted` finish moves the set to `NORMALIZING`, so a slot held after that finish sits in a set that is no longer `RECEIVING`.
  - The lease trigger (`_transition_v1`, `UPDATE` branch) already allows a closed normalize lease (`finished`, `expired` or `cancelled`) to move `held` to `released` when its stored `cleanup_proof_bytes` are a non-empty array whose proofs all say `absent` or `not_created` and all name the lease's own fence. It does not look at the set state. A closed lease may replace its proofs while the slot is held, but may not change `state`, `expires_at`, the token or claim fields, or `last_request_id`, `last_request_digest` and `last_result_bytes`. A repeat call therefore cannot be answered from a stored result.
  - `cleanup_set_v1` releases held slots of terminal sets only, with proofs matched by job and fence. It locks the raw `instance_budgets` row, the user's raw `quotas` row, the storage pair, then the root, set, members (`ORDER BY id`) and leases (`ORDER BY id`), and it refuses to run outside READ COMMITTED. Set expiry raises each member's fence by one and cancels live leases.
  - No path on `main` closes a normalize lease as `expired` in a live set. IMP-007R (below) would add one.
  - Function inventory: `_FUNCTIONS` holds one JSON row per function. `ingestion_schema.WORKER` is every row with `execute: ingestion_worker_only`, and `ingestion_migration.grants` grants EXECUTE on each name in `WORKER` to the worker role. `ingestion_migration.EXPECTED_STRUCTURE_SHA256` and `EXPECTED_RESTORED_STRUCTURE_SHA256` cover each function's text. The `sql-inventory` key of `tests/fixtures/ingestion/oracle.json` is the tested inventory.
- Frozen DTOs that fit without change ([wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json)): `CleanupSetRequest` has exactly the keys `cleanup_proofs` (at most 12), `credential_epoch`, `fence`, `job_id`, `member_id` (UUID or null), `realm_digest`, `request_id`, `set_id`, `version` and `work_kind` (`normalize`, `prepare` or `cleanup`). `FinishAck` has `version`, `job_id`, `fence`, `member_id`, `state` and `cleanup_complete`. The frozen `worker_sql_contracts` list does not name the new function; this ticket records which DTOs it uses.
- IMP-007F (plan PR #86), whose worker files this ticket changes:
  - `src/kurafolio/ingestion/worker_sql.py` keeps a fixed tuple `CALLS` of the eight functions the worker calls and checks at import that each is in `ingestion_schema.WORKER`, without requiring equality. Its AC-01 static test expects "8 names exactly".
  - Normalize step 6 waits for the proof until `raw_deadline` minus 5 seconds. With an `absent` or `not_created` proof, `finish` releases the slot and the journal record is removed. With a `pending` or `failed` proof, the record stays and the launcher's record is not forgotten, so a later cleanup can ask for the proof by handle.
  - The worker journal holds only set, job, member, fence and handle (IMP-007F D4). The handoff token is never written there. After a restart the worker does not finish old attempts, because their tokens died with the old process; their records wait for the cleanup of their sets.
  - IMP-007F stays open until its PR 3, which waits for IMP-007P. `depends_on: IMP-007F` therefore holds this ticket until then (Decisions needed 2).
- IMP-007R (plan PR #86, backlog) would add a sweep that closes a lapsed normalize lease as `expired` and moves its member to `reupload_required`, keeping the slot held when there is no proof. Its Decision 3, not yet answered, asks whether this ticket's release also covers swept attempts. That is Decisions needed 1 here.
- Shares `ingestion-schema-sql` with IMP-007N (being built), IMP-007O and IMP-007R, so these build one at a time. Shares `v2-import-worker` with IMP-007F.
- Changing the `0004` function text in place is safe only if no database outside disposable tests ran `operator migrate-ingestion` at `0004`. IMP-007O and IMP-007R have the same check; Requirements make it a stop point here too.
- Gated PostgreSQL tests: the `postgres-foundation` CI job runs `scripts/run_gated_tests.py --expect-skipped 118` today; IMP-007N plans to raise it. New gated methods raise it from the value on `main` when this ticket is built.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md). The r7 inventory is the frozen baseline [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json). The inventory the code is tested against is the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`, checked by `tests/test_postgres_migration.py`; it is the r7 baseline plus later approved additions.
- Owner decisions of 2026-11-20: IMP-007M decision 1 is "B with F" and decision 2 is yes (the release also covers a slot held after a `stage_admitted` finish); IMP-007F D8 puts the worker's call to the new function in this ticket.
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.

### The function

- One new worker function, `wl_ingestion.release_member_slot_v1(p_worker uuid,p_token text,p_request jsonb,p_bytes bytea) RETURNS jsonb`: PL/pgSQL, `SECURITY DEFINER`, `search_path=pg_catalog,pg_temp`, `REVOKE ALL ... FROM PUBLIC`, executable by the worker role only, like `finish_member_v1`. It returns `{"ok": true, "value": <FinishAck>}` or `{"ok": false, "code": <code>}`.
- Request: exactly the keys `cleanup_proofs`, `credential_epoch`, `fence`, `job_id`, `member_id`, `realm_digest`, `request_id`, `set_id`, `version` (1) and `work_kind` (`normalize`), with `member_id` a UUID and `p_bytes` NULL. `cleanup_proofs` holds 1 to 3 proofs, each naming the request's `job_id` and `fence`, with the same shape check as finish's proofs. An empty list, an extra or missing key, or any other shape returns `import_invalid`. Every valid request is a valid `CleanupSetRequest`, and every success value is a valid `FinishAck` whose `state` is the member's current state and whose `cleanup_complete` says whether the slot is now released. No DTO in `wire-contracts.json` or `codec-schema.json` changes.
- Fencing, all required, each refusal changing nothing:
  - `_guard_worker_v1` runs first; the call runs only under READ COMMITTED.
  - Scope comes only from the stored set, never from the worker.
  - The target is the newest normalize lease of that member at the requested fence. It must be closed as `finished`; a lease closed as `expired` is accepted only as Decisions needed 1 decides.
  - The lease's `worker_id` equals `p_worker`, and its `token_digest` is not NULL and equals the digest of `p_token`, the attempt's handoff token. A mismatch, or an attempt that was never bound, returns `authentication_required`.
  - The member's stored context `job_id` equals the request's `job_id`, the member's `fence` still equals the lease's fence, and the lease's `incarnation` and `restore_epoch` equal the guard's.
  - The set is live: not `COMMITTED`, `REJECTED`, `CANCELLED` or `EXPIRED`, and before its `expires_at` on the database clock. Every live state is accepted, including `NORMALIZING` and later states reached after the last member's `stage_admitted` finish. A set that is `EXPIRED` or past `expires_at` returns `import_expired`; any other terminal set returns `import_stale`. Terminal sets stay with `cleanup_set_v1`.
  - No matching lease, a lease still `offered` or `active`, or a wrong job, fence or member returns `import_stale`.
- Release rule, the same as finish's `cleaned` rule and the lease trigger's: if every proof in the request says `absent` or `not_created`, set `raw_slot='released'`, store the proofs and call `_quota_v1(tenant,portfolio,'raw',-1,0)` exactly once. Otherwise store the proofs in place of any stored earlier, keep the slot held and change no quota. No timer, set state or member state ever releases a slot.
- Repeats: the function writes no `last_request_*` field (the trigger forbids it on a closed lease). A repeated or later call on a lease whose slot is already `released` returns `cleanup_complete: true` and changes nothing: no quota change and no proof change. A slot is released at most once across `finish_member_v1`, this function and `cleanup_set_v1`.
- Locks: always take the raw `instance_budgets` row, then the user's raw `quotas` row, before the root; then the root, the set, its members `ORDER BY id` and its leases `ORDER BY id`, the same order as `cleanup_set_v1`. No storage rows. Serialization failures, deadlocks, lock timeouts and cancels are re-raised, as in the merged functions.
- No trigger, table, column, index, `claim_plan_v1`, `cleanup_set_v1` or `finish_member_v1` change.
- Inventory amendment, approved with this ticket's Gate A: one `ingestion_worker_only` row in `_FUNCTIONS` and the same entry in the oracle `sql-inventory`, so the name joins `ingestion_schema.WORKER` and the worker grant. `EXPECTED_STRUCTURE_SHA256`, `EXPECTED_RESTORED_STRUCTURE_SHA256` and the oracle vectors change with it. The frozen r7 [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json) does not change.
- The change is made in place at revision `0004_ingestion`; the `0001` to `0003` providers stay byte-identical. Before building, confirm that no database outside disposable tests has run `operator migrate-ingestion` at `0004`. If that cannot be confirmed, stop and ask the owner whether a new revision is needed instead.

### The worker call (IMP-007F's files)

- `CALLS` in `worker_sql.py` gains `release_member_slot_v1` (nine names), and the AC-01 static test of IMP-007F changes to match. The request is validated as `CleanupSetRequest` and the value as `FinishAck`.
- After a `finish_member_v1` that returned `cleanup_complete: false`, the worker process that finished the attempt keeps that attempt's handoff token in memory and keeps asking the launcher for the attempt's status by its journal handle, with a bounded backoff, until one of these happens: the launcher reports `absent` or `not_created`; the set's `expires_at` passes; the function refuses the call; or the worker stops. On `absent` or `not_created` it calls the function once with that proof, retrying the same request only as `WorkerSQL` retries any call. When the value says `cleanup_complete: true`, it removes the journal record and sends the launcher `forget`. Otherwise the record stays for the set's cleanup.
- The handoff token stays in process memory only: never in the journal, a log, an error or the database. It is dropped when the release succeeds, the attempt is given up, or the worker stops.
- A worker restart before the proof makes no call: the restarted worker has no token, and the attempt waits for cancel or expiry and the set's cleanup, as today. This holds unless Decisions needed 1 chooses option (c).
- No error, notice or log line carries raw bytes, context, a token or a handle.

### Docs

- `docs/web-v2-imports.md` describes the new function, its fencing and release rule, and when the worker calls it. It replaces IMP-007F's interim text that a slot without a launcher proof stays held until the set ends, where that text becomes untrue, and still says that a restart before the proof falls back to cancel or cleanup.

## Acceptance criteria

- [ ] AC-IMP-007Q-01: `wl_ingestion.release_member_slot_v1(uuid,text,jsonb,bytea) RETURNS jsonb` exists as `SECURITY DEFINER` with `search_path=pg_catalog,pg_temp`, is not executable by `PUBLIC`, the gateway or the runtime role, and is executable by the worker role; it is in `_FUNCTIONS` as `ingestion_worker_only` and in the oracle `sql-inventory`, the frozen r7 inventory is unchanged, both expected structure digests are updated, and `tests/test_postgres_migration.py` passes against them.
- [ ] AC-IMP-007Q-02: After a `reupload_required` finish with a `pending` proof in a live set, a call with an `absent` proof for that job and fence releases the slot once: the lease shows `raw_slot='released'` and the stored proof, the user's raw lease count drops by exactly one, the value is a `FinishAck` with `state` `reupload_required` and `cleanup_complete: true`, and the member's next reserve succeeds with fence + 1. The same holds for a `not_created` proof and for a finish that sent no proof.
- [ ] AC-IMP-007Q-03: After a `stage_admitted` finish without proof, a proven call releases the slot once and the set's second member can then reserve. When that finish was the last member's and the set has moved to `NORMALIZING`, a proven call also releases the slot once, and the same user can then reserve a member of another set.
- [ ] AC-IMP-007Q-04: A call with a `pending` or `failed` proof, or with one `absent` and one `pending` proof, stores the proofs, keeps the slot held, changes no quota and returns `cleanup_complete: false`; an empty proof list returns `import_invalid` and changes nothing.
- [ ] AC-IMP-007Q-05: Fencing: a wrong fence, job, member or set, another worker, a wrong handoff token, an attempt that was never bound, a lease still `offered` or `active`, a restored instance (`incarnation` or `restore_epoch` changed), a changed credential epoch, a `COMMITTED`, `REJECTED` or `CANCELLED` set (`import_stale`), an `EXPIRED` set or one past `expires_at` (`import_expired`), and a call outside READ COMMITTED each return their refusal code and leave the lease, the member, the set and every quota unchanged.
- [ ] AC-IMP-007Q-06: A second call after a release returns `cleanup_complete: true` with no further change. Two concurrent calls, a call racing `cancel_set_v1`, and a call followed by `cancel_set_v1` and `cleanup_set_v1` release the slot exactly once in total, and the raw lease count never drops below its value before the reserve.
- [ ] AC-IMP-007Q-07: A normalize lease closed as `expired` in a live set is handled as Decisions needed 1 decides: under (b) or (c) it is released under the same rule and the fencing that option names; under (a) the call returns `import_stale` and changes nothing.
- [ ] AC-IMP-007Q-08: The worker, with a fake launcher that reports `cleanup_pending` until after the finish and then `finished` with `cleanup_complete: true`, calls `release_member_slot_v1` once with the `absent` proof, then removes the journal record and sends `forget`; with a launcher that never finishes removal it stops asking by the set's `expires_at` and keeps the record; after a restart it makes no release call and the attempt is released only by the set's cleanup after cancel; and a scan of the journal directory and captured logs finds no handoff token.
- [ ] AC-IMP-007Q-09: No DTO in `wire-contracts.json` or `codec-schema.json` changes; every request the worker sends validates as `CleanupSetRequest` and every success value as `FinishAck`.
- [ ] AC-IMP-007Q-10: The pull request records the evidence that no database outside disposable tests ran `operator migrate-ingestion` at `0004`, or the owner's decision to use a new revision.
- [ ] AC-IMP-007Q-11: Opt-in real-PostgreSQL tests cover AC-02 to AC-07, and the `postgres-foundation` job's `--expect-skipped` rises by exactly the number of new gated test methods.
- [ ] AC-IMP-007Q-12: `docs/web-v2-imports.md` describes the function, its fencing, its release rule and when the worker calls it, and says that a worker restart before the proof falls back to cancel or cleanup.

## Plan

- [ ] Owner answers Decisions needed 1 and 2 and gives Gate A; a planner writes the Build plan from the merged SQL and the merged IMP-007F worker, IMP-007N and (if merged) IMP-007O and IMP-007R.
- [ ] SQL function, inventory row, oracle inventory and structure digests; `0004` evidence.
- [ ] Real-PostgreSQL tests for each acceptance ID; CI skip count.
- [ ] Worker call in IMP-007F's files and its unit and PostgreSQL tests; docs.

## Decisions needed

Only the owner answers. The planner recommends an option for each.

1. **Swept attempts (IMP-007R Decision 3).** Should the release also cover a normalize lease that IMP-007R's sweep closed as `expired` in a live set? The function above is fenced on the attempt's handoff token, as finish is, and IMP-007F's journal never holds that token (IMP-007F D4). A worker that crashed and restarted therefore cannot make the call under that fencing, whatever is decided here. The sweep mostly follows such a crash.
   - (a) No. Only `finished` leases. A swept attempt's slot returns only at set cleanup after cancel or expiry.
   - (b) Yes, with the same token fencing. The function also accepts a lease closed as `expired` in a live set from the worker process that still holds the attempt's handoff token. That covers a worker that lost its lease but kept running, for example through a database outage longer than the lease, and then gets the proof. It does not cover a restarted worker. If IMP-007R is not merged when this ticket is built, the test seeds an `expired` lease through the operator role, and the worker's late-proof loop also starts after a lost lease.
   - (c) Yes, for a restarted worker too. For a closed lease, the call is accepted without the handoff token from the lease's own registered worker (`worker_id`, login role, enabled, credential epoch and realm, as `_guard_worker_v1` checks), using the job, fence and handle from the journal. This also lets a restarted worker release `finished` attempts. It weakens the fencing compared with finish, and it changes this ticket's worker Requirements and AC-08. It is the case IMP-007R's Decision 3 recommendation describes ("so that IMP-007F's restarted worker can use its journal").
   - Recommendation: (b). It keeps the token rule finish uses, adds no new trust in the worker identity alone, and costs one more accepted lease state. IMP-007R's recommendation (a) assumes a restarted worker can make the call, which needs (c) here. Answer this together with IMP-007R Decision 3 and before this ticket's Gate A, because AC-07 and the worker Requirements depend on it.
2. **When this ticket can start.** `depends_on: [IMP-007M, IMP-007F]` holds it until IMP-007F is `done`, which happens only in IMP-007F PR 3, after IMP-007P merges.
   - (a) Keep it. The worker files are stable by then, and `v2-import-worker` is free.
   - (b) Split this ticket. The SQL function and its tests depend on IMP-007M only and can be built after IMP-007N. The worker call goes in a second ticket that depends on this one and on IMP-007F. This changes where the owner put the worker call (IMP-007F D8) and needs a gated change here.
   - Recommendation: (a). Until this ticket lands, IMP-007F's proof wait (option F) already avoids most held slots, and cancel stays the way out.
3. **Gate A.** The owner approves the Goal, Requirements and Acceptance criteria above, with the answers to items 1 and 2, including the function name `release_member_slot_v1` and the inventory amendment, or asks for changes.

## Handoff

- State: Filed on 2026-11-20 in plan PR #85; `backlog`, waiting for the owner's answers to Decisions needed 1 and 2, Gate A and a Build plan. It starts after IMP-007M and IMP-007F are `done`, and takes the `ingestion-schema-sql` lock in turn with IMP-007N, IMP-007O and IMP-007R.
- Next step: The owner answers Decisions needed 1 (with IMP-007R Decision 3) and 2 and gives Gate A; a planner then writes the Build plan from the merged SQL and the merged IMP-007F worker.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: Never release a slot without proof that the attempt has no live child or raw buffer. The trigger forbids writing `last_request_*` on a closed lease, so repeats are answered from the lease's state; do not change the trigger. Finish requires a `RECEIVING` set, but this function must accept every live state.
- Open questions: Decisions needed 1 to 3.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #85 from the owner's decisions of 2026-11-20. On "IMP-007M: ... Which fix?" the owner chose "B with F (Recommended)": "B = a new worker function takes late launcher proofs and releases the slot (one SQL inventory amendment, a follow-up ticket); F = the worker waits for proof before finishing, within the 120 s raw deadline." On "IMP-007M #2 the new release also covers a slot held after a stage_admitted finish; #3 drop IMP-007M's resources: [ingestion-schema-sql] ..." the owner chose "Accept all (Recommended)". On IMP-007F's "D8 the F wait-for-proof goes in IMP-007F now, and calling B's new release function goes in B's follow-up ticket" the owner chose "Accept all (Recommended)". Shares `ingestion-schema-sql` with IMP-007N, IMP-007O and IMP-007R and `v2-import-worker` with IMP-007F. Spec hash at filing sha256:f89be6ef37d18fe7f2893cfcde9f0bcd8f5370ce3f142ca14ca071c104940dca, awaiting the owner's answers and Gate A. Status backlog; no Gate A yet.
