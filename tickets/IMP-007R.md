---
id: IMP-007R
title: Sweep a lapsed normalize attempt into reupload_required
priority: P0
status: ready
type: feature
parent: IMP-007
depends_on: []
resources: [ingestion-schema-sql]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-23, Gate A on the amended text (hash 5eebf8c6…): Approve Gate A"
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:5eebf8c637dd7d798e6d72bda1280f64e4cab3507c733fa4ae3fcc441bedc724
updated: 2026-11-23
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
- Checked again on `main` at `cd122a2` (2026-11-23, for the Build plan):
  - IMP-007O and IMP-007W are `done`. IMP-007F, IMP-007Q, IMP-007T and IMP-007V are `ready` and not built, so no worker process calls `claim_plan_v1` yet, `release_member_slot_v1` does not exist, and the "cancel or expiry is the recovery" text from IMP-007F's plan is not in `docs/web-v2-imports.md`. IMP-007X (`backlog`) also lists `ingestion-schema-sql`.
  - `src/kurafolio/persistence/migrations/versions/` stops at `0004_ingestion.py`. IMP-007T plans a later revision, and APP-011I and APP-011E plan `0005` and `0006`.
  - `_structure_digest` (`ingestion_migration.py:221`) reads relations, columns, constraints, indexes, policies, types and triggers, never `pg_proc`; `pg_get_triggerdef` renders only the `CREATE TRIGGER` line. The `sql-inventory` key of `tests/fixtures/ingestion/oracle.json` holds names, arguments and grants, not bodies. So a change to the text of `claim_plan_v1` or `_transition_v1` leaves `EXPECTED_STRUCTURE_SHA256`, `EXPECTED_RESTORED_STRUCTURE_SHA256` and `oracle.json` as they are. `verify_functions` compares each installed body with the code. The Requirements say the oracle vectors and both digests "change with the function text"; IMP-007O met the same wording (its Decisions item 1). See Decisions needed item 5.
  - The whole body of `claim_plan_v1` sits in one block whose `EXCEPTION WHEN SQLSTATE '22023'`, `unique_violation` and `data_exception` handlers roll back everything the call did. A sweep in that block would be undone by every refusal.
  - Lock order in the merged functions: the worker guard takes `wl_pg.instance_state`, `wl_ingestion.instance_state` and the `workers` row `FOR SHARE`. Every user call's guard then takes `wl_identity.instance_auth_state FOR UPDATE`, user and session rows, source rows, then (reserve) `instance_budgets` 'raw' and the user's `quotas` 'raw' row inside `_quota_v1`, then the root, set, members and leases. `finish_member_v1` and `cleanup_set_v1` take the raw quota rows before the root too. The prepare path of `claim_plan_v1` takes `instance_auth_state` first (`_PREPARE_AUTH_STATE_LOCK`) and its user and session locks later. The cleanup path takes no identity lock and takes roots with `FOR UPDATE SKIP LOCKED`.
  - Raw quota: one concurrent raw slot per user and four per instance (`QUOTA_LIMITS['raw']['leases'] == (1, 4)`). A swept bound attempt that keeps its slot therefore blocks every reserve by that user, in any set, with `import_busy`.
  - Reserve sets `raw_deadline` to the reserve clock plus 120 seconds and the offer's `created_at` to the same clock, so a passed raw deadline means 120 seconds since reserve. The lease trigger tests `n>=created_at+interval '120 seconds'` without truncation; the lease functions compare against `date_trunc('second', raw_deadline)`.
  - Lease state `expired` is written today only for `prepare` and `cleanup` leases (`claim_plan_v1`). No code path sets a `normalize` lease to `expired`, so after this ticket an expired normalize lease is always one the sweep closed. The partial unique index `live_member_lease_uq` allows one `offered` or `active` normalize lease per member, and `lease_expiry_idx` covers `(expires_at, state)`.
  - The members trigger raises `import_expired` for any change to a member of a set whose `expires_at` has passed, even before the set is marked `EXPIRED`. Closing an `offered` or `active` lease as `expired` needs `n>=OLD.expires_at` and an unchanged `expires_at`.
  - `IngestionStorageDDLTests.test_cleanup_lease_functions_match_their_worker_declarations` asserts that `'DELETE '` does not occur in `CLAIM_PLAN_DDL`. `test_cleanup_claim_backoff_is_one_shared_rule` counts fragments of the cleanup candidate query, including `ORDER BY x.created_at,x.id::text COLLATE "C" LIMIT 8` once.
  - Planning-time hashes (any `PYTHONHASHSEED`): `CLAIM_PLAN_DDL` `0416dccbd8ac6bd8a83eda4873d1ca9c581f9fbab5ba89a7a90cb66677bdef1d`, `TRANSITION_DDL` `884071b8ab5f0af3e35fc9d3b573eda1ff03a26886b0832b77ec3486b3449d13`, `function_ddl()` `038c60e351f28f0372842e71d90c9c2dbd11a73e4ca84aaf8488eab767391b7c`, and `function_ddl()` with both constants removed `6066ad4131933d7ccb7da183c483d0b22920b104ae82943ffa4ed1aa460e88c8`.

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
- No DTO in `wire-contracts.json` or `codec-schema.json` changes. No function, argument, return type, grant, table, column, index or inventory row is added, and `ingestion_schema.WORKER` is unchanged. Only the text of `claim_plan_v1` changes, plus one narrow exception in the stage rule of the `_transition_v1` trigger function: in a live set, the sweep may delete the stage of the attempt it closes, and every other stage deletion in a live set stays refused. The frozen r7 inventory, `tests/fixtures/ingestion/oracle.json`, `EXPECTED_STRUCTURE_SHA256` and `EXPECTED_RESTORED_STRUCTURE_SHA256` stay as they are, because neither the structure digests nor the oracle cover function bodies; `verify_functions` checks each installed body against the code.
- The change is made in place at revision `0004_ingestion`; the `0001` to `0003` providers stay byte-identical. Before building, confirm that no database outside disposable tests has run `operator migrate-ingestion` at `0004`. If that cannot be confirmed, stop and ask the owner whether a new revision is needed instead.
- No error, notice or log line carries raw bytes, context, a token or a handle.

## Acceptance criteria

- [ ] AC-IMP-007R-01: A lapsed attempt in a live set, for a member in `receiving` and one in `normalizing`, is swept: the lease is `expired`, the member is `reupload_required` with `import_reupload_required`, and the set's state and revision are unchanged.
- [ ] AC-IMP-007R-02: The sweep leaves untouched an attempt whose lease is still live, one whose raw deadline has not passed, one closed by `finish_member_v1`, and one whose set is terminal; a test covers each.
- [ ] AC-IMP-007R-03: After the sweep, `renew_member_v1`, `admit_stage_v1` and `finish_member_v1` with the old fence and token return `import_stale` and change nothing, and the next `reserve_member_v1` for the member issues fence + 1.
- [ ] AC-IMP-007R-04: A swept attempt that was never bound releases its raw slot once, 120 seconds after reserve. A swept bound attempt keeps `raw_slot = held` with no proof and no quota change, and the same user's next reserve returns `import_busy`; after the set is cancelled, `cleanup_set_v1` with an all-`absent` proof releases the slot exactly once.
- [ ] AC-IMP-007R-05: Two concurrent sweeps, and a sweep racing a late `finish_member_v1`, `cancel_set_v1` or set expiry, give exactly one effect, and the raw quota is returned at most once.
- [ ] AC-IMP-007R-06: An attempt that stored a stage before it lapsed is swept to `reupload_required` and its stage row is deleted; no accepted fact, mapping, decision, preview or stage of another attempt changes; a later upload of the same file in that member reaches `admitted`; and deleting a stage of a live set in any other way is still refused.
- [ ] AC-IMP-007R-07: The frozen r7 inventory, the oracle inventory, both expected structure digests and every DTO are unchanged; no function, grant or inventory row is added and `ingestion_schema.WORKER` is unchanged; only the text of `claim_plan_v1` and `_transition_v1` changes, and `tests/test_postgres_migration.py` passes against a real `0004` install.
- [ ] AC-IMP-007R-08: The pull request records the evidence that no database outside disposable tests ran `operator migrate-ingestion` at `0004`, or the owner's decision to use a new revision.
- [ ] AC-IMP-007R-09: Opt-in real-PostgreSQL tests cover AC-01 to AC-06 and AC-11.
- [ ] AC-IMP-007R-10: `docs/web-v2-imports.md` describes the sweep, that it runs inside `claim_plan_v1` and so needs a running worker, and that a slot without proof stays held until cleanup unless the worker process that holds the attempt's token gets a late proof (IMP-007Q), replacing the "cancel or expiry is the recovery" text where it becomes untrue.
- [ ] AC-IMP-007R-11: A `claim_plan_v1` call with `work_kind: "cleanup"` sweeps lapsed attempts, as a `prepare` call does; one call sweeps no more than the fixed bound and later calls sweep the rest; a call refused by `_guard_worker_v1`, or run outside READ COMMITTED, sweeps nothing; and the sweep's changes stand when the call answers `no_work`, `already_claimed` or a refusal code.

## Build plan

- Based on: `main` at `cd122a2` (after IMP-007O, #103, and the IMP-007T planning record, #109).
- Tier: `frontier`, `risk: high`, `review: independent`. The reviewer model's fresh-context QA review and a second Architect review are required before the owner's review (tickets/README.md, "Reviews").

### Before you claim

1. Decisions needed items 5 and 6 must be resolved on `main`. If item 5 was resolved by amending the gated wording, `spec_approved` must hold the hash of the amended text; if `python3 scripts/tickets.py spec IMP-007R` reports `CHANGED`, do not build. If either item is open, do not claim; report that the ticket waits on the owner.
2. `git fetch origin`, then `python3 scripts/tickets.py cleanup`. If `claim` refuses the `ingestion-schema-sql` lock, run `python3 scripts/tickets.py list` and stop while a live claim holds it. Never release another agent's live claim.
3. `ls src/kurafolio/persistence/migrations/versions/` on the build base must end at `0004_ingestion.py`. If any later revision has merged (IMP-007T, APP-011I or APP-011E plan one), stop and ask: a later revision changes what an in-place `0004` edit means.
4. Run `git log cd122a2..origin/main -- src/kurafolio/persistence/ingestion_schema.py src/kurafolio/persistence/ingestion_migration.py tests/test_postgres_migration.py`. If IMP-007Q or another ticket changed `claim_plan_v1`, `_transition_v1`, a lease function, `_quota_v1` or the lease trigger, recompute every value in "Baseline" from the new base, and the `WORKER` tuple, the function count (68 at `cd122a2`) and the stripped `function_ddl()` hash in the static test (IMP-007Q adds `release_member_slot_v1` to all three), and check that the design below still holds. If `claim_plan_v1` no longer has a single top-level exception block, or a function now sets a `normalize` lease to `expired`, stop and ask.

### Baseline (record before editing)

On the unchanged tree, save the output under ignored `work/imp-007r/` and quote it in the PR:

- `PYTHONPATH=src .venv/bin/python -c "import hashlib; from kurafolio.persistence import ingestion_schema as s, ingestion_migration as m; h=lambda t: hashlib.sha256(t.encode()).hexdigest(); f=m.function_ddl(); print(h(s.CLAIM_PLAN_DDL), h(s.TRANSITION_DDL), h(f), h(f.replace(s.CLAIM_PLAN_DDL,'').replace(s.TRANSITION_DDL,'')), h(s.tables_ddl()), h(s.triggers_ddl()), h(m.inherited_guard_replacements()), sep='\n')"`. At `cd122a2` this prints `0416dccbd8ac6bd8a83eda4873d1ca9c581f9fbab5ba89a7a90cb66677bdef1d`, `884071b8ab5f0af3e35fc9d3b573eda1ff03a26886b0832b77ec3486b3449d13`, `038c60e351f28f0372842e71d90c9c2dbd11a73e4ca84aaf8488eab767391b7c`, `6066ad4131933d7ccb7da183c483d0b22920b104ae82943ffa4ed1aa460e88c8`, `64b4b1b52df00c6c3f8efb59f7917ed176a7f2b455573bb935052e5a737ca7e9`, `585b16d1c69965a595ea43e35fef6b1bc03dd7bd98500057c50281c848575f56` and `09b6dbb7eceea20cbfb8becc711bfc5a5dafd5a2b841023938214aeb6de62475`.
- The existing claim and cleanup tests, unchanged: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_postgres_migration -k claim -k cleanup -k finish -k renew`. All must pass with no skip.

### Files

- `src/kurafolio/persistence/ingestion_schema.py`: a constant `NORMALIZE_SWEEP_LIMIT = 8`, three new module strings for the `claim_plan_v1` insertions and two for the `_transition_v1` insertion (below), their placeholders in `CLAIM_PLAN_DDL` and `TRANSITION_DDL`, and the matching `.replace(...)` calls. Every change to the two function bodies is an insertion: removing each inserted string once gives back the baseline text byte for byte. The strings the static test strips must be the rendered ones (`CODES`, `TERMINAL`, `SWEEP_LIMIT` and `REJECT;` already replaced); either keep rendered module constants or render them in the test through the same replacements before stripping. Nothing else in the module changes.
- `tests/test_postgres_migration.py`: one narrowed assertion in an existing static test, one new static test, seven new gated tests in `IngestionAppendOnlyPostgresTests`, one in `IngestionRuntimeInventoryPostgresTests`, and small helpers (below).
- `.github/workflows/ci.yml`: in job `postgres-foundation`, `--expect-skipped 132` rises by one per new gated method (eight here, so 140) and its comment says "the 139 ingestion tests". Job `postgres-ingestion` keeps `--expect-skipped 0`.
- `docs/web-v2-imports.md`: the sweep (AC-10, below).
- `tickets/IMP-007R.md`: status, Handoff, Log and the AC-08 evidence.

### Design: `claim_plan_v1`

The sweep runs after the guard and the READ COMMITTED check and before any work is picked, in the function's outer block. Everything from the authority lock to the final `no_work` moves into a new inner block with its own refusal handlers. A refusal then rolls back only the inner block; the sweep stays. Errors the inner block does not catch (serialization failure, deadlock, lock timeout, cancel, anything else) reach the unchanged outer handler, which re-raises them or raises `internal_error`, so the transaction fails and the sweep is undone with it.

Insertions, in order:

1. Declarations, on a new line before `BEGIN`: `sweep_hints wl_ingestion.leases[];sweep_hint wl_ingestion.leases%ROWTYPE;sweep_lease wl_ingestion.leases%ROWTYPE;sweep_member wl_ingestion.members%ROWTYPE;sweep_set wl_ingestion.sets%ROWTYPE;sweep_now timestamptz;sweep_release boolean;sweep_changed integer;`. Do not reuse `held`, `selected`, `candidate`, `mem` or `n`.
2. The sweep prelude, right after `request_digest:=...;` and before the comment `-- Take the existing authority lock before looking up a prepare request so`:
   - On a `prepare` call only: `PERFORM 1 FROM wl_identity.instance_auth_state WHERE id=1 FOR UPDATE;` with no condition and no refusal. This keeps the declared order (identity singleton before quota rows and roots) for the identity locks the prepare path takes later. The unchanged `PREPARE_AUTH_STATE_LOCK` block below it, now inside the inner block, still refuses `instance_not_ready` when bootstrap is open; it re-locks a row this transaction already holds. So the sweep runs on every call that passed the guard and the isolation check, as the Requirements say.
   - The sweep (below).
   - `BEGIN` opening the inner block.
3. The inner block's end, right after the final `RETURN ... 'outcome','no_work' ...;` and before the outer `EXCEPTION`:

   ```sql
    -- IMP-007R: a refusal rolls back only this block; the sweep above stands.
    EXCEPTION WHEN SQLSTATE '22023' THEN
     code:=SQLERRM;
     IF code NOT IN CODES THEN code:='import_invalid'; END IF;
     RETURN pg_catalog.jsonb_build_object('ok',false,'code',code);
    WHEN unique_violation THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_conflict');
    WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
    END;
   ```

   These three answers are exactly the outer handler's, so every refusal keeps its current code. `CODES` is replaced by the existing chain.

The sweep, as SQL (`TERMINAL` and `SWEEP_LIMIT` are placeholders the `.replace` chain fills; put the sweep's own `.replace` before `TERMINAL` in the chain):

```sql
 -- IMP-007R (owner answers Q23, Q24): close normalize attempts whose lease and raw deadline
 -- have both lapsed, oldest lease deadline first, at most SWEEP_LIMIT per call. The list is a
 -- hint; every condition is rechecked under the set lock.
 sweep_now:=wl_identity._clock_timestamp_v1();
 sweep_hints:=ARRAY(SELECT l FROM wl_ingestion.leases l
  JOIN wl_ingestion.members m ON m.tenant_id=l.tenant_id AND m.portfolio_id=l.portfolio_id AND m.set_id=l.set_id AND m.id=l.member_id
  JOIN wl_ingestion.sets x ON x.tenant_id=l.tenant_id AND x.portfolio_id=l.portfolio_id AND x.id=l.set_id
  WHERE l.work_kind='normalize' AND l.state IN ('offered','active') AND l.expires_at<=sweep_now
   AND m.state IN ('receiving','normalizing') AND m.fence=l.fence AND m.raw_deadline<=sweep_now
   AND x.state NOT IN TERMINAL AND sweep_now<x.expires_at
  ORDER BY l.expires_at,l.id::text COLLATE "C" LIMIT SWEEP_LIMIT);
 -- Raw quota rows precede the roots, as in reserve, finish and cleanup_set_v1.
 IF EXISTS(SELECT 1 FROM pg_catalog.unnest(sweep_hints) h WHERE h.token_digest IS NULL) THEN
  PERFORM 1 FROM wl_ingestion.instance_budgets WHERE bucket='raw' FOR UPDATE;
  PERFORM 1 FROM wl_ingestion.quotas q WHERE q.bucket='raw' AND (q.tenant_id,q.portfolio_id) IN (
   SELECT h.tenant_id,h.portfolio_id FROM pg_catalog.unnest(sweep_hints) h WHERE h.token_digest IS NULL)
   ORDER BY q.tenant_id,q.portfolio_id FOR UPDATE;
 END IF;
 FOREACH sweep_hint IN ARRAY sweep_hints LOOP
  BEGIN
   -- A root another call holds is skipped, never waited for; a later call retries.
   PERFORM 1 FROM wl_ingestion.roots WHERE tenant_id=sweep_hint.tenant_id AND portfolio_id=sweep_hint.portfolio_id
    FOR UPDATE SKIP LOCKED;
   IF FOUND THEN
    SELECT * INTO sweep_set FROM wl_ingestion.sets WHERE tenant_id=sweep_hint.tenant_id AND
     portfolio_id=sweep_hint.portfolio_id AND id=sweep_hint.set_id FOR UPDATE;
    PERFORM 1 FROM wl_ingestion.members WHERE tenant_id=sweep_set.tenant_id AND portfolio_id=sweep_set.portfolio_id
     AND set_id=sweep_set.id ORDER BY id FOR UPDATE;
    PERFORM 1 FROM wl_ingestion.leases WHERE tenant_id=sweep_set.tenant_id AND portfolio_id=sweep_set.portfolio_id
     AND set_id=sweep_set.id ORDER BY id FOR UPDATE;
    sweep_now:=wl_identity._clock_timestamp_v1();
    SELECT * INTO sweep_lease FROM wl_ingestion.leases WHERE tenant_id=sweep_hint.tenant_id AND
     portfolio_id=sweep_hint.portfolio_id AND id=sweep_hint.id;
    SELECT * INTO sweep_member FROM wl_ingestion.members WHERE tenant_id=sweep_lease.tenant_id AND
     portfolio_id=sweep_lease.portfolio_id AND set_id=sweep_lease.set_id AND id=sweep_lease.member_id;
    -- A set at or past its expiry belongs to the expiry step, which cancels the lease.
    IF sweep_set.state NOT IN TERMINAL AND sweep_now<sweep_set.expires_at AND sweep_lease.work_kind='normalize' AND
     sweep_lease.state IN ('offered','active') AND sweep_now>=sweep_lease.expires_at AND
     sweep_member.state IN ('receiving','normalizing') AND sweep_member.fence=sweep_lease.fence AND
     sweep_now>=sweep_member.raw_deadline THEN
     -- The trigger's own release rule: never bound and 120 s past reserve. Any other
     -- swept attempt has no proof, so its slot stays held.
     sweep_release:=sweep_hint.token_digest IS NULL AND sweep_lease.token_digest IS NULL AND
      sweep_now>=sweep_lease.created_at+interval '120 seconds';
     UPDATE wl_ingestion.leases SET state='expired',
      raw_slot=CASE WHEN sweep_release THEN 'released' ELSE raw_slot END
      WHERE tenant_id=sweep_lease.tenant_id AND portfolio_id=sweep_lease.portfolio_id AND id=sweep_lease.id
       AND state IN ('offered','active') AND raw_slot='held';
     GET DIAGNOSTICS sweep_changed=ROW_COUNT;
     IF sweep_changed<>1 THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error'; END IF;
     UPDATE wl_ingestion.members SET state='reupload_required',error_code='import_reupload_required'
      WHERE tenant_id=sweep_member.tenant_id AND portfolio_id=sweep_member.portfolio_id AND
       set_id=sweep_member.set_id AND id=sweep_member.id;
     -- This attempt's transient stage, so a re-upload of the same file can store it again.
     DELETE FROM wl_ingestion.stages WHERE tenant_id=sweep_member.tenant_id AND portfolio_id=sweep_member.portfolio_id
      AND set_id=sweep_member.set_id AND member_id=sweep_member.id AND created_at>=sweep_lease.created_at;
     IF sweep_release THEN
      PERFORM wl_ingestion._quota_v1(sweep_lease.tenant_id,sweep_lease.portfolio_id,'raw',-1,0);
     END IF;
    END IF;
   END IF;
  -- An attempt a trigger or _quota_v1 refuses (its set reached expiry between the checks,
  -- for example) is left as it was, and the loop goes on to the next one.
  EXCEPTION WHEN data_exception THEN NULL;
  END;
 END LOOP;
```

Rules the builder keeps:

- Order inside one attempt: lease, then member, then stage, then quota. The stage guard below reads the expired lease and the `reupload_required` member, so the lease and member must change first.
- The lease stays `expired` with `expires_at` unchanged (the trigger requires both). Only the release rule above may set `raw_slot = 'released'`; never derive it from `raw_deadline` or a truncated deadline.
- `_quota_v1` raises `import_invalid` rather than release below zero. Inside the per-attempt block that rolls the attempt back, so a slot can never be returned twice.
- Only `data_exception` (SQLSTATE class 22, which includes every `22023` refusal from the triggers and `_quota_v1`) is swallowed per attempt. Serialization failure, deadlock, lock timeout, cancel and `internal_error` propagate.
- The `sweep_changed<>1` check raises `internal_error` on purpose, as `finish_member_v1` does for the same lease update. Under the locks and rechecks it can only fire if a live normalize lease no longer holds its raw slot, which the triggers forbid; failing the whole call then is safer than closing the attempt without knowing its slot. It does stop every `claim_plan_v1` call, cleanup included, until the row is repaired. A refused attempt, by contrast, stays in the candidate list, so eight attempts that keep being refused would fill the bound ahead of later ones; today only a set reaching expiry causes a refusal, and the hint excludes such a set on the next call.
- The sweep writes no notice, log line or message. It changes no set row, no revision, no other member and no other attempt's stage.
- `NORMALIZE_SWEEP_LIMIT = 8`, rendered into `LIMIT 8`. Ordering by `(l.expires_at, l.id)` is deterministic and can use `lease_expiry_idx`. Do not add an index.
- Lock order: worker guard rows (`FOR SHARE`), then on `prepare` the identity singleton, then `instance_budgets` 'raw' and the users' raw `quotas` rows in `(tenant_id, portfolio_id)` order (only when the list holds a never-bound attempt), then each root with `SKIP LOCKED`, then set, members and leases. Reserve, finish, cancel and `cleanup_set_v1` take the same rows in the same relative order, and the cleanup path that follows already takes roots with `SKIP LOCKED`.
- Do not change `_PREPARE_AUTH_STATE_LOCK`; `_PREPARE_LEASE_LOCKS` shares it.

### Design: the stage guard in `_transition_v1`

In the `stages`/`decisions`/`previews` branch, the line

```text
   IF NOT (parent.state=ANY(terminal) OR n>=OLD.purge_at) THEN REJECT; END IF;
```

becomes, by two insertions (after `THEN`, and after `REJECT; END IF;`):

```text
   IF NOT (parent.state=ANY(terminal) OR n>=OLD.purge_at) THEN
    -- IMP-007R (owner answer Q24): in a live set, only the stage of the attempt the
    -- claim_plan_v1 sweep closed. Its member is reupload_required at that attempt's fence,
    -- the attempt's normalize lease is expired (only the sweep expires one) and the stage
    -- is no older than the attempt.
    IF TG_TABLE_NAME<>'stages' THEN REJECT; END IF;
    IF NOT EXISTS(SELECT 1 FROM wl_ingestion.members m JOIN wl_ingestion.leases l ON l.tenant_id=m.tenant_id AND
      l.portfolio_id=m.portfolio_id AND l.set_id=m.set_id AND l.member_id=m.id
     WHERE m.tenant_id=OLD.tenant_id AND m.portfolio_id=OLD.portfolio_id AND m.set_id=OLD.set_id AND
      m.id=OLD.member_id AND m.state='reupload_required' AND m.stage_digest IS NULL AND
      l.work_kind='normalize' AND l.fence=m.fence AND l.state='expired' AND l.created_at<=OLD.created_at) THEN
     REJECT; END IF;
   END IF;
```

Keep `OLD.member_id` in its own statement after the table-name test: `decisions` and `previews` rows have no `member_id`. The rule excludes finish's `reupload_required` (its lease is `finished`), other members, earlier attempts' stages, a member re-reserved at a new fence, decisions and previews.

### Interfaces

- `claim_plan_v1(uuid,text,jsonb,bytea) RETURNS jsonb`: arguments, return shapes, refusal codes, grants and `search_path` unchanged. `_transition_v1() RETURNS trigger` unchanged apart from the guard above.
- Unchanged: `_FUNCTIONS`, `GATEWAY`, `WORKER`, `READ_TABLES`, `REVISION`, `PREDECESSOR`, `function_ddl()` order, `ingestion_migration.py` (`EXPECTED_STRUCTURE_SHA256` `bfa65a66…`, `EXPECTED_RESTORED_STRUCTURE_SHA256` `7008e006…`), `ingestion_restore.py` (`"functions": "68"`), `migrations/versions/0004_ingestion.py`, `tests/fixtures/ingestion/oracle.json`, `src/kurafolio/ingestion/contracts.py` and every file under `docs/specs/imp-007-r7/`.
- Error code written by the sweep: `import_reupload_required`, which is in the `MemberResult.error_code` enum.

### Expected values (independent of the code)

- A swept attempt: lease `state` `expired`, `expires_at` and `created_at` unchanged; member `state` `reupload_required`, `error_code` `import_reupload_required`, same `fence`, `raw_digest`, `raw_bytes`, `raw_deadline` and `stage_digest` (NULL); set `state`, `revision` and `cleanup_state` unchanged (for a fresh set `['RECEIVING', 1, 'not_needed']`).
- Never bound (reserve only), aged so that `created_at` is 3 minutes back: `raw_slot` `released`, raw quota `[used_count, lease_count]` from `[1, 1]` to `[1, 0]`, instance raw `lease_count` from 1 to 0, `cleanup_proof_bytes` NULL.
- Bound (bind, with or without claim): `raw_slot` `held`, no proof, raw quota stays `[1, 1]`.
- After the sweep: `renew_member_v1`, `admit_stage_v1`, `claim_member_v1` and `finish_member_v1` (both `stage_admitted` and `reupload_required`) at fence `'1'` answer exactly `{'ok': False, 'code': 'import_stale'}`; a reserve for the swept never-bound member answers `ok` with `fence` `'2'`, the member becomes `['receiving', 2]` with `error_code`, `raw_digest` and `raw_bytes` NULL, and the leases read `['expired', 'offered']`. A reserve by the user of a swept bound attempt answers `{'ok': False, 'code': 'import_busy'}` and changes nothing.
- Bound swept attempt, then `cancel_set_v1`, a cleanup claim and `cleanup_set_v1` with one `absent` proof for job and fence `'1'`: ack `outcome` `purged`, `quota_released` true; attempts `[['expired', 'released', ['absent']]]`; raw `[1, 0]`; instance raw `lease_count` 0; storage `[0, 0]`; transient 0. A replay returns the same ack.
- Bound: `NORMALIZE_SWEEP_LIMIT == 8`. With nine lapsed attempts, the first call sweeps the eight with the earliest lease `expires_at`, the second sweeps the ninth, the third sweeps nothing.

### Tests

Name the acceptance IDs in each docstring. Use synthetic rows only. Age rows in replica mode as the existing tests do (`SET LOCAL session_replication_role=replica; … origin;`): move a normalize lease's `created_at` and `expires_at`, and its member's `raw_deadline`, back by the same interval (3 minutes) so `raw_deadline` stays `created_at + 120 s`. Call the sweep through the existing `plan_claim(...)` (cleanup by default; `work_kind="'prepare'"` for prepare). Reuse `claim_seed`, `cleanup_seed`, `finish_seed`, `lease_call`, `admit_call`, `finish_call`, `reserve_call`, `cancel_call`, `cleanup_call`, `proofs`, `rejects`, `FINISH_STATE`, `CLEANUP_STATE`, `LEASE_STATE` and `NO_WORK`. Add a helper `lapse(seconds=180, where="l.work_kind='normalize'")` for the aging, and let `run_labelled` take an optional `begin='BEGIN;'` argument (default unchanged) for the isolation case.

Static, in `IngestionStorageDDLTests`:

| AC | Case | Expected |
|---|---|---|
| 07 | New `test_sweep_changes_only_claim_plan_and_the_stage_guard`: remove each `claim_plan_v1` insertion once from `schema.CLAIM_PLAN_DDL` and each `_transition_v1` insertion once from `schema.TRANSITION_DDL`, then hash | `0416dccb…` and `884071b8…` (full values in Baseline) |
| 07 | Same test: `function_ddl()` with both constants removed | `6066ad41…`; every other function body is unchanged |
| 07 | Same test: `schema.WORKER`, the `_FUNCTIONS` names and the inventory function count | `('claim_member_v1', 'renew_member_v1', 'admit_stage_v1', 'prepare_preview_v1', 'finish_member_v1', 'cleanup_set_v1', 'claim_plan_v1', 'read_plan_basis_v1')`; unchanged; 68 with the inherited functions as today |
| 07, 11 | Same test: in `CLAIM_PLAN_DDL`, positions of the guard call, the READ COMMITTED check, the sweep's first line, the inner `BEGIN`, `-- Take the existing authority lock`, the final `no_work` `RETURN`, the inner `EXCEPTION`, the outer `EXCEPTION` | Strictly increasing; `LIMIT 8` occurs inside the sweep; `schema.NORMALIZE_SWEEP_LIMIT == 8` |
| 01, 07 | Same test: `re.search(r'RAISE\s+(NOTICE\|LOG\|WARNING\|INFO\|DEBUG)', ddl)` for both constants | `None` |
| 07 | Existing `test_cleanup_lease_functions_match_their_worker_declarations`: replace only the `'DELETE '` check for `claim_plan_v1`. Assert `CLAIM_PLAN_DDL.count('DELETE ') == 1` and that the one occurrence is `DELETE FROM wl_ingestion.stages`; keep `'DELETE '` absent from `CLEANUP_SET_DDL` and `_purge_v1` absent from `CLAIM_PLAN_DDL` | Passes; every other assertion of that test unchanged |

`test_cleanup_claim_backoff_is_one_shared_rule` must pass unchanged; the sweep's `ORDER BY l.expires_at,…` does not repeat the cleanup candidate text.

Gated, in `IngestionAppendOnlyPostgresTests` (`KURAFOLIO_INGESTION_TEST=1`):

| AC | Test and case | Expected |
|---|---|---|
| 01, 09 | `test_sweep_closes_lapsed_receiving_and_normalizing_attempts`. Subtest `receiving`: `claim_seed(count=2)` (bound offer), `lapse()`, `plan_claim('sweep')`, `FINISH_STATE`. Subtest `normalizing`: the same after `lease_call('claim_member_v1', 'claim')` | `SWEEP` is `NO_WORK`. `FSTATE` set `['RECEIVING', 1, 'not_needed']`; members `[['reupload_required', 'import_reupload_required', False, 1], ['waiting', None, False, 1]]`; leases `['expired']`; raw `[1, 1]` |
| 02 | `test_sweep_leaves_live_unlapsed_finished_and_terminal_attempts`, one subtest each; take a row snapshot (normalize leases, members, stages, raw quotas, sets) before and after `plan_claim` | Snapshot equal in each case: (a) live lease: bound offer, member `raw_deadline` 1 s in the past, lease `expires_at` 20 s ahead; (b) unbound offer whose 30 s lease has lapsed but whose raw deadline is 80 s ahead (lapse 40 s only); (c) `finish_member_v1` with `reupload_required` then `lapse()`; (d) a replica-built `CANCELLED` set (`cleanup_state` `complete`) with an `active` lapsed lease and a `normalizing` member; (e) a bound attempt after `lapse()`, with its live `RECEIVING` set then aged 2 days past `expires_at`, called with `work_kind="'prepare'"`. Then case (e) again with a cleanup call: the set is expired as today (members `[['expired', 2]]`, attempts `[['cancelled', 'held', None]]`), not swept |
| 03 | `test_sweep_fences_the_old_attempt_and_reserve_starts_the_next_fence`. Bound: `finish_seed()`, `lapse()`, sweep, then `renew_member_v1`, `admit_call`, `claim_member_v1`, `finish_call` (both outcomes), all at fence `'1'` with the original token, then `LEASE_STATE`/`FINISH_STATE`. Never bound: `cleanup_seed(bind=False)`, `lapse()`, sweep, `reserve_call('again', catalog)`, then a `renew_member_v1` and a `finish_call` at fence `'1'` | Every old-fence call `{'ok': False, 'code': 'import_stale'}` and state unchanged by them. `AGAIN` ok with fence `'2'`; member `['receiving', 2]`; leases `['expired', 'offered']`; old-fence calls after the reserve still `import_stale` |
| 04 | `test_sweep_releases_only_a_never_bound_slot_and_cleanup_proves_the_rest`. Never bound: `cleanup_seed(bind=False)`, `lapse()`, sweep twice (`request` IDs differ), `CLEANUP_STATE`. Defensive: the same with `raw_deadline` aged but `created_at` only 60 s back. Bound: `cleanup_seed()`, claim, `lapse()`, sweep, `reserve_call('busy', catalog)`, `CLEANUP_STATE`, `cancel_call`, cleanup claim, `cleanup_call('clean', proofs=('absent',))`, `CLEANUP_STATE`, replay | Never bound: attempts `[['expired', 'released', None]]`, raw `[1, 0]`, instance 0, after both sweeps. Defensive: `[['expired', 'held', None]]`, raw `[1, 1]`. Bound: `BUSY` `import_busy`; attempts `[['expired', 'held', None]]`, raw `[1, 1]`; after cleanup the values under "Expected values"; replay equal |
| 05 | `test_concurrent_sweeps_and_late_calls_have_one_effect`. Use the two-session pattern of `test_concurrent_exact_prepare_claims_replay_the_same_lease` (separate database from `TEMPLATE postgres`, committed setup, `pg_stat_activity` wait detection); you may factor it into a helper without changing that test's assertions. Races: (a) two sweeps of a never-bound attempt (the second waits on the raw budget row); (b) two sweeps of a bound attempt (the second skips the locked root and returns at once); (c) sweep holds, `finish_member_v1` waits; (d) `finish_member_v1` (`stage_admitted`) holds a lease that lapses during the transaction (`expires_at` and `raw_deadline` 3 s ahead; sleep past them), then a sweep; (e) sweep holds, `cancel_set_v1` waits; (f) `cancel_set_v1` holds, then a sweep; (g) in one script, sweep then age the set past expiry and run a cleanup claim | (a), (b): second call `NO_WORK`; lease `expired` once; never bound raw `[1, 0]` and instance 0, bound raw `[1, 1]`. (c): finish `import_stale`; member `reupload_required`. (d): sweep `NO_WORK` without waiting; after commit lease `finished`, member `admitted`, and a later sweep changes nothing. (e): cancel ok; lease stays `expired`; member `cancelled` at fence 2; raw `[1, 1]`. (f): lease `cancelled`, member `cancelled`; no `expired` lease. (g): set `EXPIRED`, member `expired` at fence 2, lease stays `expired` |
| 06 | `test_sweep_deletes_only_the_swept_attempts_stage`. `finish_seed(count=2)` gives member 0 a stored stage (claimed and admitted, not finished) in a live set; `accept_seed`, under it, adds a live READY set in the same scope with admitted members, their stages, a decision and a preview. Before: digest every row of `accepted_inputs`, `accepted_plans`, `source_revisions`, `mappings`, `authority_links`, `lineage`, `receipts`, `audit`, `outbox`, `decisions`, `previews`, `roots` and of every stage except the swept one (`md5` of each row's text, ordered by primary key). `lapse()`, sweep, digests again | Member 0 `['reupload_required', 'import_reupload_required', False, 1]`; its stage count 0; every digest equal |
| 06 | Same test, re-upload: stand in for IMP-007Q's release by recording one `absent` proof for fence `'1'` on the expired lease (`UPDATE … SET raw_slot='released',cleanup_proof_bytes=wl_ingestion._canonical_v1(<proofs('absent')>)`, origin mode, so the lease trigger checks it) and `SELECT wl_ingestion._quota_v1(<tenant>,<portfolio>,'raw',-1,0)`. Then reserve, bind, `claim_member_v1`, `admit_call` with the same fixture and `finish_call` with `stage_admitted`, all at fence `'2'` (proof fence `'2'`), new request IDs | Reserve fence `'2'`; admit `outcome` `admitted` (not `already_admitted`); finish ok, `state` `admitted` |
| 06 | Same test, refusals with `rejects(...)`: delete a stage of the live `accept_seed` set (admitted members, no expired lease); in a separate `finish_seed()` script, delete the stage left after a `finish_call` with `reupload_required` (lease `finished`); after the sweep, delete a stage of the swept member inserted in replica mode with another digest and `created_at` 1 s before the expired lease's `created_at`; delete the decision and the preview of the `accept_seed` set | Each raises `import_invalid` and deletes nothing |
| 11 | `test_sweep_runs_on_every_claim_within_its_bound`. Seed lapsed bound attempts as replica rows (`set_row`, `member_row`, `lease_row` with a token digest, member `raw_deadline` in the past, a `roots` row for the scope, staggered lease `expires_at`). Cases: cleanup call; prepare call; nine attempts in three sets of three members with three calls; refusals: unknown worker (`authentication_required`), `credential_epoch` `'2'` (`credentials_changed`), `run_labelled(..., begin='BEGIN ISOLATION LEVEL REPEATABLE READ;')` (`import_invalid`); answers after a sweep: `no_work`, `already_claimed` (repeat of a cleanup claim on a cancelled set), `import_conflict` (a prepare call reusing a cleanup claim request ID), `authentication_required` (that repeat with another token), `import_stale` (that repeat after aging the cleanup lease past expiry) | Cleanup and prepare calls both sweep. Bound: 8, then 1, then 0, the first eight by lease `expires_at`. Guard and isolation refusals: nothing swept. Every other answer: the attempt is swept in the state read after the call in the same transaction |

Gated, in `IngestionRuntimeInventoryPostgresTests`, `test_imp_007r_installed_bodies_with_unchanged_digests`:

| AC | Case | Expected |
|---|---|---|
| 07 | `self._assert_clean()`; read `prosrc` of `claim_plan_v1` and `_transition_v1` | Clean with 68 functions and the unchanged `EXPECTED_STRUCTURE_SHA256`; each body holds its insertion once |
| 07, rollback | In `try`/`finally`, commit the pre-change bodies (insertions removed, `CREATE OR REPLACE FUNCTION`) as the operator with `exec_driver_sql(..., execution_options={'no_parameters': True})`, run `self._check()` and the operator's `verify_inventory`; in `finally` reinstall the current bodies and call `self._assert_clean()` | Both checks raise `PersistenceError('migration_target_invalid')`; clean again after the reinstall |

Do not raise a tolerance or weaken an existing assertion beyond the one narrowing above. Every other existing test must pass unchanged; none seeds a lapsed normalize attempt in a live, unexpired set before calling `claim_plan_v1` at `cd122a2`.

### Docs (AC-10)

In `docs/web-v2-imports.md`, after the paragraph on `claim_plan_v1` and `cleanup_set_v1`, add a paragraph that says:

- Every `claim_plan_v1` call that passes the worker guard and the isolation check first closes up to eight normalize attempts whose lease and 120-second raw deadline have both passed, in a set that is neither terminal nor past expiry. Each becomes `reupload_required` with `import_reupload_required`; its lease is `expired`; a stage it stored is deleted so the same file can be uploaded again. The set, its revision, other members and accepted data do not change. The sweep stands whatever the call answers.
- It runs inside `claim_plan_v1`, so it needs a running worker. No worker process calls `claim_plan_v1` yet (IMP-007F).
- A never-bound attempt's raw slot returns at once. A bound attempt has no proof, so its slot stays held and the user's next reserve answers `import_busy` until `cleanup_set_v1` proves the slot after the set is cancelled or expires. A planned late-proof release (IMP-007Q) will free it sooner, but only from the worker process that still holds the attempt's handoff token; after a restart the slot returns only at cleanup.
- Opt-in PostgreSQL tests cover the sweep, its bound, its fencing, slot handling, races and the stage rule.
- If a sentence saying that cancel or expiry is the only recovery from a crashed worker exists on the build base (IMP-007F's docs), replace it with a pointer to this paragraph.

### AC-08 evidence

Put it in the PR under "Behavior & Compatibility" and in one ticket Log line: the owner's answer to Decisions needed item 6, quoted from the ticket Log on `main`; `git tag --list` empty and `gh release list --repo gh-slee/kurafolio` empty; `src/kurafolio/persistence/context.py` still mapping no runtime profile to `0004_ingestion`; `docs/web-v2-imports.md` still saying there is no operational `0004` profile; the migrations directory ending at `0004`.

### Verify

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_postgres_migration.IngestionStorageDDLTests`
- `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python scripts/run_gated_tests.py --expect-skipped 0 -- discover -s tests -p 'test_postgres_migration.py'`. It needs Docker, the pinned image in `IngestionAppendOnlyPostgresTests.IMAGE` pulled beforehand, and `scripts/postgres.py test-identity-environment` for the runtime-inventory class. If your sandbox blocks Docker or local ports, run it in the owner's terminal or rely on the `postgres-ingestion` CI job, and say which. A skipped test is not acceptance.
- Without the variable, `PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration` reports 139 opt-in ingestion skips, matching the new `postgres-foundation` count of 140 with the runtime-image test.
- The baseline hash command again: `CLAIM_PLAN_DDL`, `TRANSITION_DDL` and `function_ddl()` differ; the stripped values match the baseline; the other three hashes are unchanged.
- `git diff --exit-code origin/main -- src/kurafolio/persistence/ingestion_migration.py src/kurafolio/persistence/ingestion_restore.py src/kurafolio/persistence/migrations/ src/kurafolio/persistence/schema.py src/kurafolio/persistence/identity_schema.py src/kurafolio/persistence/source_schema.py src/kurafolio/ingestion/ docs/specs/imp-007-r7/ tests/fixtures/ingestion/oracle.json` exits 0 (AC-07).
- The full suite, `scripts/check_language.py`, `scripts/check_publication.py --worktree` and `--staged`, and `python scripts/check_pr_image.py` from a clean tree.

### Rollback

Revert the commit. There is no data migration and no table, column, index, grant or inventory change. Rows the sweep wrote stay valid under the old code: an `expired` normalize lease is closed, so the old `cleanup_set_v1` still proves and releases its slot; a `reupload_required` member can be reserved again; a deleted stage was transient. The old stage rule would again refuse such a delete. A database installed with one body fails `verify_functions` against the other source with `migration_target_invalid`, and so does a `restore-ingestion` of a backup taken under the other body; that is safe only because no `0004` database or backup exists outside disposable tests (Decisions needed item 6). Recreate synthetic test databases rather than editing them.

### Negative cases the review should check

- A refusal from the inner block leaves the sweep in place; a guard refusal or a non-READ COMMITTED call sweeps nothing.
- No slot is released without the trigger's rule, and none twice (two sweeps; sweep then cleanup; sweep then a stand-in late proof).
- No attempt is swept while its lease or raw deadline is live, after a finish, in a terminal set or in a set past expiry.
- The stage rule admits only the swept attempt's stage; every other live-set deletion of a stage, decision or preview is refused.
- No lock is waited for in an order that differs from reserve, finish, cancel or `cleanup_set_v1`; a busy root is skipped.
- No notice or message carries raw bytes, context, a token or a handle.
- The fail-closed `internal_error` when the lease update does not change exactly one row, and the possibility that repeatedly refused attempts fill the per-call bound (Design, "Rules the builder keeps"), are deliberate; judge them as decisions.

### Do not touch

- `ingestion_migration.py`, `ingestion_restore.py`, `src/kurafolio/persistence/migrations/`, `schema.py`, `identity_schema.py`, `source_schema.py`, `src/kurafolio/ingestion/` and `src/kurafolio/web_v2/`.
- `tests/fixtures/ingestion/oracle.json` and everything under `docs/specs/imp-007-r7/`.
- Every other DDL constant and function in `ingestion_schema.py`, including `_PREPARE_AUTH_STATE_LOCK`, `_PREPARE_CLAIM_SQL`, the lease functions, `_quota_v1`, `CLEANUP_SET_DDL` and the lease and member branches of `_transition_v1`.
- `tickets/ROADMAP.md` and other tickets.

### Stop and ask if

- Decisions needed item 5 or 6 is open, `spec_approved` does not match, or you learn of a `0004` database or backup outside disposable tests.
- A revision after `0004_ingestion` exists on the build base.
- The live `_structure_digest` or the restored digest differs from its expected value, or any inventory, oracle, DTO or r7 file would have to change.
- A test needs a new refusal code, a changed acknowledgement, a second `DELETE`, a notice, or a weakened existing assertion beyond the one narrowing above.
- PostgreSQL rejects a construct above (`FOREACH` over `wl_ingestion.leases[]`, `ARRAY(SELECT l …)`, or `OLD.member_id` in the trigger), and the fix would change behaviour rather than syntax.
- A race test shows a deadlock or a second effect, or an existing test's expected values move.
- The opt-in PostgreSQL suite cannot run anywhere you can reach. Report it and do not open the PR as passing.

## Plan

- [x] Owner answers Decisions 1 to 3 (2026-11-21: 1 = (a), 2 = (a), 3 = yes for the running worker only).
- [x] Owner gives Gate A (2026-11-21, Q32).
- [x] Planner writes the Build plan from `main` at `cd122a2`, after IMP-007O and IMP-007W merged (plan pull request recorded in the Log).
- [x] Owner answers Decisions needed item 5 (2026-11-23: (a), amend); amended wording applied.
- [x] Owner gives Gate A on the amended text (2026-11-23, sha256:5eebf8c637dd7d798e6d72bda1280f64e4cab3507c733fa4ae3fcc441bedc724).
- [ ] Owner answers Decisions needed item 6.
- [ ] Sweep in `claim_plan_v1` and the stage-delete exception in `_transition_v1`, as insertions; both structure digests and `oracle.json` unchanged (Build plan).
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
   **Resolved 2026-11-21.** Asked "Gate A, tickets rewritten with your decisions. Which do you approve exactly as written?" with this ticket listed at sha256:8b2ab2f1293f7e513e1415f7c6531ae33fe4d3503a03a8aa3018a748e7af2952, the owner selected "IMP-007Q,IMP-007R,IMP-007V" (Q32). `gate_approval` and `spec_approved` record it.
5. **Proposed change to gated sections, for the owner.** The approved text says a function-text change moves the oracle vectors and both expected structure digests, and it cannot. The Requirements bullet ends "The frozen r7 inventory stays as it is; the oracle vectors and both expected structure digests change with the function text." AC-07 says "only the text of `claim_plan_v1` and `_transition_v1` changes, with the oracle vectors and both expected structure digests". But `_structure_digest` never reads `pg_proc`, and the `sql-inventory` vectors in `oracle.json` hold names, arguments and grants, not bodies (Context). So the build leaves `EXPECTED_STRUCTURE_SHA256`, `EXPECTED_RESTORED_STRUCTURE_SHA256` and `oracle.json` unchanged, and `verify_functions` is what catches a stale body. IMP-007O had the same wording (its Decisions item 1).
   (a) Amend the gated text and give Gate A on the new hash. Proposed wording: in the Requirements bullet, replace that last sentence with "The frozen r7 inventory, `tests/fixtures/ingestion/oracle.json`, `EXPECTED_STRUCTURE_SHA256` and `EXPECTED_RESTORED_STRUCTURE_SHA256` stay as they are, because neither the structure digests nor the oracle cover function bodies; `verify_functions` checks each installed body against the code." Replace AC-07 with "AC-IMP-007R-07: The frozen r7 inventory, the oracle inventory, both expected structure digests and every DTO are unchanged; no function, grant or inventory row is added and `ingestion_schema.WORKER` is unchanged; only the text of `claim_plan_v1` and `_transition_v1` changes, and `tests/test_postgres_migration.py` passes against a real `0004` install."
   (b) Keep the approved text and accept the Build plan's reading: the digests and the oracle "change with the function text" only as far as the function text reaches them, which is not at all. The reviewer then judges AC-07 by that reading.
   The planner recommends (a): the text a builder and reviewer check against should state what the code does. Either answer blocks the build until it is on `main`; (a) also needs the new `spec_approved`.
   **Option chosen 2026-11-23: (a); Gate A on the amended text still open.** Asked "For item 5, should the spec wording be amended with a new Gate A (a)?", with (a) described as "Amend the text and give a new Gate A. The exact replacement wording is in the ticket.", the owner replied "Yes, amend (a)" (relayed to this planning session by the coordinating session). The Requirements bullet and AC-07 now carry the proposed wording, and the gated text hashes to sha256:5eebf8c637dd7d798e6d72bda1280f64e4cab3507c733fa4ae3fcc441bedc724. The owner has not yet approved that exact text and hash, so `gate_approval` and `spec_approved` still record the 2026-11-21 Gate A and `tickets.py spec` reports `CHANGED`. Next: the owner gives Gate A on sha256:5eebf8c6…edc724, or asks for changes.
   **Resolved 2026-11-23: Gate A given on the amended text.** Asked "Do you give Gate A on IMP-007R at this hash, or do you want the wording changed first?" after being shown the amended Requirements sentence, the amended AC-IMP-007R-07 and sha256:5eebf8c637dd7d798e6d72bda1280f64e4cab3507c733fa4ae3fcc441bedc724, the owner replied "Approve Gate A" (relayed to this planning session by the coordinating session). `gate_approval` and `spec_approved` record it.
6. **Has any database outside disposable tests run `operator migrate-ingestion` at `0004`, or been backed up with `backup-ingestion`?** The Requirements make this a stop point, and only the owner can answer it. The owner answered "No, none has" for IMP-007O on 2026-11-22; that answer was for IMP-007O's change. Repository evidence at `cd122a2` is unchanged: no runtime profile serves `0004`, there are no tags or releases, and the migrations stop at `0004`. (a) No: the in-place change goes ahead, and the PR cites the answer as AC-08 evidence. (b) Yes or unsure: the ticket returns to the planner and the owner to choose a new revision, which changes the Requirements. The planner recommends asking the owner and recording the answer before the build is claimed.

## Handoff

- State: Filed on 2026-11-20; backlog. Decisions 1 to 3 were resolved on 2026-11-21; waiting for Gate A and a Build plan. Builds before, after or between IMP-007O, IMP-007Q, IMP-007T and IMP-007W, one at a time on the `ingestion-schema-sql` lock.
- Next step: The owner gives Gate A; the planner then writes the Build plan from the merged SQL.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: Never release a slot without proof that the attempt has no live child or raw buffer. A lapsed lease can expire before its raw deadline; the sweep waits for both. A refusal raised as an exception inside `claim_plan_v1` must not roll back the sweep.
- Open questions: Gate A (Decisions needed item 4).

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #86 from the owner's decision of 2026-11-20 on "IMP-007F D7: if the worker process dies mid-normalize ... What should happen?": the owner chose "SQL sweep ticket (Recommended)": "file a SQL ticket (IMP-007M family) for a fenced sweep that turns a lapsed normalize attempt into reupload_required; until it lands, docs say cancel or expiry is the recovery." Shares `ingestion-schema-sql` with IMP-007N, IMP-007O and IMP-007Q. Status backlog; no Gate A yet.
- 2026-11-21 claude-code/opus-5.5: recorded the owner's answers of 2026-11-21 in plan pull request #95. Decision 1: asked "IMP-007R: where does the sweep that turns a lapsed normalize attempt into reupload_required run?", the owner chose "Inside claim_plan_v1 (Recommended)". Decision 2: asked "IMP-007R: an attempt that had already stored its parsed stage before the worker died. What does the sweep do with it?", the owner chose "reupload_required (Recommended)": the sweep deletes that attempt's transient stage row; no accepted evidence is deleted. Decision 3: asked "IMP-007Q (late-proof slot release) and IMP-007R (crash sweep) disagree. When an upload attempt was closed by the sweep, or the worker restarted, who may later release its held raw slot with a launcher proof? The release call is fenced on the attempt's one-use handoff token, which only the running worker process holds (the journal never stores it)." (Q22), the owner chose "Running worker only (Recommended)": "IMP-007Q (b): the release also accepts a sweep-closed attempt, but only from the worker process that still holds the token (e.g. it survived a long DB outage). A restarted worker can't; that slot returns at set cleanup after cancel/expiry. Keeps finish's fencing." Gated changes: the sweep runs inside `claim_plan_v1` on every call whatever its `work_kind`, after the guard, with a fixed per-call bound named in the Build plan; a swept attempt that stored a stage becomes `reupload_required` and its stage row is deleted; the sweep runs after the guard and the READ COMMITTED check; a new bullet keeps the sweep's changes when the call answers a refusal (the merged exception block would roll them back); the fencing bullet names IMP-007Q's release as the one exception; the raw-slot bullet states the running-worker rule; the inventory bullet says only `claim_plan_v1` and a narrow stage-delete exception in `_transition_v1` change, since the merged stage trigger refuses that delete in a live set; AC-06, AC-07, AC-09 and AC-10 rewritten; new AC-11 for the `cleanup` call, the bound and refusal answers. Spec hash sha256:3d4a9432b9dc9d88dc6408dad9d9007a22c09c2e0bc2bf0d9043d4ac29ec8202 becomes sha256:8b2ab2f1293f7e513e1415f7c6531ae33fe4d3503a03a8aa3018a748e7af2952; still backlog, no Gate A.
- 2026-11-21 claude-code/opus-5.5: recorded Gate A in plan pull request #95. Asked "Gate A, tickets rewritten with your decisions. Which do you approve exactly as written?" (Q32) with this ticket listed at sha256:8b2ab2f1293f7e513e1415f7c6531ae33fe4d3503a03a8aa3018a748e7af2952, the owner selected "IMP-007Q,IMP-007R,IMP-007V". `gate_approval` set to "owner 2026-11-21, Gate A on the text as written on PR #95's branch (Q32)"; `spec_approved` set to sha256:8b2ab2f1293f7e513e1415f7c6531ae33fe4d3503a03a8aa3018a748e7af2952, which `tickets.py spec` reports as the current hash; status backlog becomes ready. Decisions needed item 4 resolved. No Build plan yet; the planner writes it in a later pull request.
- 2026-11-23 claude-code/opus-5.5: wrote the frontier Build plan from `main` at `cd122a2` in plan pull request https://github.com/gh-slee/kurafolio/pull/112 and refreshed the Context. Added Decisions needed items 5 (proposed change to gated sections for the owner: the Requirements and AC-07 say the oracle vectors and both structure digests change with the function text, but neither covers function bodies; proposed wording needs a new Gate A) and 6 (the owner's `0004` install and backup confirmation for this ticket). Both block the build, not this plan. Goal, Requirements and Acceptance criteria unchanged (sha256:8b2ab2f1293f7e513e1415f7c6531ae33fe4d3503a03a8aa3018a748e7af2952).
- 2026-11-23 claude-code/opus-5.5: recorded the owner's choice on Decisions needed item 5 in plan pull request https://github.com/gh-slee/kurafolio/pull/112. Asked "For item 5, should the spec wording be amended with a new Gate A (a)?", with (a) described as "Amend the text and give a new Gate A. The exact replacement wording is in the ticket.", the owner replied "Yes, amend (a)". Gated change: the last sentence of the Requirements bullet on DTOs and inventory now says the frozen r7 inventory, `oracle.json` and both expected structure digests stay as they are because neither covers function bodies, and AC-07 says the same and passes against a real `0004` install. Spec hash sha256:8b2ab2f1293f7e513e1415f7c6531ae33fe4d3503a03a8aa3018a748e7af2952 becomes sha256:5eebf8c637dd7d798e6d72bda1280f64e4cab3507c733fa4ae3fcc441bedc724. Gate A on the amended text not recorded: the owner chose to amend but has not approved this exact text and hash. `gate_approval` and `spec_approved` unchanged; item 6 still open.
- 2026-11-23 claude-code/opus-5.5: recorded Gate A on the amended text in plan pull request https://github.com/gh-slee/kurafolio/pull/112. Asked "Do you give Gate A on IMP-007R at this hash, or do you want the wording changed first?" after being shown the amended Requirements sentence, the amended AC-IMP-007R-07 and sha256:5eebf8c637dd7d798e6d72bda1280f64e4cab3507c733fa4ae3fcc441bedc724, the owner replied "Approve Gate A". `tickets.py spec` computed exactly that hash before recording. `gate_approval` set to "owner 2026-11-23, Gate A on the amended text (hash 5eebf8c6…): Approve Gate A"; `spec_approved` set to sha256:5eebf8c637dd7d798e6d72bda1280f64e4cab3507c733fa4ae3fcc441bedc724; status stays ready. Decisions needed item 6 (the `0004` confirmation) is still open and blocks the build.
