---
id: IMP-007N
title: Back off cleanup claims for sets whose cleanup keeps failing
priority: P0
status: in_progress
type: feature
parent: IMP-007
depends_on: [IMP-007C]
resources: [ingestion-schema-sql]
risk: high
size: S
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-12, exponential backoff 30s x 2^(n-1) capped at 15 minutes, oldest-first among eligible sets, no new columns"
review: independent
branch: ticket/imp-007n-back-off-cleanup-claims-for-sets-whose-c
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:c3e06c751ef4816ad200095284163430738b7a0e1783e78999605dd5035e92eb
updated: 2026-11-20
---

# IMP-007N: Back off cleanup claims for sets whose cleanup keeps failing

## Goal

`claim_plan_v1(work_kind=cleanup)` always hands out the oldest terminal set whose cleanup is `pending` or `failed`. A set whose launcher proofs keep coming back `pending` or `failed` is therefore picked first on every claim. A single worker loop can retry it forever while newer sets keep their storage reservations and raw slots. Add the owner's backoff so that a failing set waits longer between attempts and newer sets get cleaned in the meantime.

## Context

- Background only: the revision 1 planning draft [docs/specs/v2-drafts/WL-P0-007.md](../docs/specs/v2-drafts/WL-P0-007.md) (sha256:fa0971a0da787cb327484c92144e4a5ecd916db4ad0328e03b408d647190acd5), which the r7 bundle supersedes.
- Origin: IMP-007C (PR #42) added `claim_plan_v1` and `cleanup_set_v1`. Its owner decisions of 2026-11-10 still hold: decision 3 makes a cleanup lease's fence 1 plus the set's earlier cleanup leases, decision 5 keeps `cleanup_state=failed` and the storage reservation until a proof succeeds, and decision 6 selects the oldest terminal set with cleanup `pending` or `failed` and no live cleanup lease. This ticket refines decision 6 only.
- Current behaviour on `main`. The cleanup branch of `CLAIM_PLAN_DDL` in `src/kurafolio/persistence/ingestion_schema.py` sets `n` from `wl_identity._clock_timestamp_v1()`, which is `pg_catalog.clock_timestamp()`. It then reads at most 8 candidate IDs, ordered by `created_at, id::text COLLATE "C"` (`LIMIT 8`): sets that are terminal with `cleanup_state` `pending` or `failed`, or non-terminal and past `expires_at`, and that have no live cleanup lease. For each candidate it takes the root lock with `FOR UPDATE SKIP LOCKED`, locks the set, its members and its leases, re-reads `n` and expires an overdue set. It then skips a set that is not terminal with cleanup `pending` or `failed`, closes lapsed cleanup leases as `expired`, skips a set that still has a live cleanup lease, and inserts a 30-second lease with fence `count(*)+1`. A set whose cleanup keeps returning `cleanup_pending` is therefore handed out again by the very next claim.
- Why the rule must sit in the candidate query as well as under the locks. `LIMIT 8` is applied before the locked checks. If the backoff were checked only under the locks, up to 8 older sets that are waiting would fill the candidate list, every one would be skipped, and the claim would return `no_work` while a newer eligible set exists (AC-03).
- Schema facts the rule relies on. `wl_ingestion.leases` already has `set_id`, `work_kind`, `created_at`, `expires_at` and `state`, with the CHECK `expires_at>=created_at`. The lease trigger in `_transition_v1` refuses a cleanup lease on a non-terminal set (`(NEW.work_kind='cleanup')<>(parent.state=ANY(terminal))`), and nothing deletes lease rows, so an overdue live set has no cleanup lease and a terminal set's count only grows. No lease index leads with `set_id` for cleanup work; the existing live-lease `NOT EXISTS` probe already reads leases per candidate. The storage quota (`QUOTA_LIMITS['storage']['sets']`: 8 per portfolio, 64 per instance) bounds how many sets can be waiting, so the extra per-candidate read is small. Function bodies are code-owned: `verify_functions` in `src/kurafolio/persistence/ingestion_migration.py` compares each installed body with the source. Neither the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json` nor `_structure_digest` covers function bodies, and no test or fixture hashes `function_ddl()`.
- Rollback context: `docs/web-v2-imports.md` states that there is no operational `0004` profile, so no installed database needs an in-place upgrade. Restore (`src/kurafolio/persistence/ingestion_restore.py`) brings lease rows back and cancels the live ones, so restored cleanup leases, cancelled ones included, keep counting toward the backoff.
- Tests to start from, in `tests/test_postgres_migration.py`. The cleanup helpers and tests are in `IngestionAppendOnlyPostgresTests` (the class at about line 890, gated by `KURAFOLIO_INGESTION_TEST=1`): `OWN_SET`, `plan_claim`, `cleanup_call`, `cancel_call`, `cleanup_seed`, `CLEANUP_STATE`, `assert_cleanup_lease`, `cleanup_ack`, `NO_WORK`, and the six tests from `test_cleanup_after_cancel_during_reception_releases_the_unbound_slot_once` to `test_claim_selects_the_oldest_terminal_set_first`. `run_labelled` runs one script in `BEGIN ... ROLLBACK` and collects lines whose label is upper case and whose value starts with `{` or `[`. Rows are moved or inserted under `SET LOCAL session_replication_role=replica`, which turns triggers off but not CHECK constraints. `CLEANUP_STATE` reads `set`, `request_digest` and `members` for the own set only, but its `cleanup` and `attempts` lists and its quota rows cover every set. The static `IngestionStorageDDLTests` class runs without PostgreSQL.
- CI pins the gated skip count. In `.github/workflows/ci.yml`, the `postgres-foundation` job runs `test_postgres_*.py` without the ingestion flag and expects `--expect-skipped 118` (comment: "the 117 ingestion tests (job postgres-ingestion) and the runtime-image test"). The `postgres-ingestion` job runs `test_postgres_migration.py` with `--expect-skipped 0`. Each test method of a gated class counts as one skip; subtests do not.
- Public description to update: the `claim_plan_v1` and `cleanup_set_v1` paragraph of `docs/web-v2-imports.md` ("picks the oldest set that is terminal ...", "the next claim retries it (`cleanup_pending`)" and its "Opt-in PostgreSQL tests cover ..." list). The frozen r7 bundle says nothing about cleanup order or backoff and does not change.
- Neighbours: IMP-007M holds the same `ingestion-schema-sql` resource and `tickets/ROADMAP.md` orders it after this ticket. IMP-007F (the worker process) is the first caller that will see `no_work` while every remaining set waits; this ticket does not change the worker.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md). The r7 inventory is the frozen baseline [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json). The inventory the code is tested against is the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`, checked by `tests/test_postgres_migration.py`; it is the r7 baseline plus later approved additions.

## Acceptance criteria

- [x] AC-IMP-007N-01: A set with n earlier cleanup leases is eligible only when it has none, or when the database clock is at or past its latest cleanup lease's `created_at` plus `LEAST(30 seconds × 2^(n−1), 15 minutes)`.
- [x] AC-IMP-007N-02: Among eligible sets the order stays oldest-first (`created_at`, then set ID), as owner decision 6 requires.
- [x] AC-IMP-007N-03: A set in backoff never blocks a newer eligible set. When only backed-off sets remain, the claim returns `no_work`.
- [x] AC-IMP-007N-04: No new table, column or index: the rule uses only existing lease rows, so the r7 inventory does not change.
- [x] AC-IMP-007N-05: Overdue non-terminal sets (no cleanup lease yet) stay eligible at once and are expired before cleanup, as today.
- [x] AC-IMP-007N-06: Opt-in PostgreSQL tests cover: a stuck set skipped for a newer one; the stuck set claimable again after its window; the window doubling across attempts; the 15-minute cap; `no_work` when only backed-off sets remain; replay of an existing claim unaffected.
- [x] AC-IMP-007N-07: `docs/web-v2-imports.md` describes the backoff.

## Build plan

- Based on: `main` at `a2f5f2b` ("Cut pull requests and CI runs that only move ticket paperwork (#78)").
- Shape: the rule is one SQL expression, written once in Python and used twice in `claim_plan_v1`. The first use is in the candidate query, so that `LIMIT 8` counts only eligible sets. The second is a fresh read under the root, set and lease locks, so that a cleanup lease another worker committed after the candidate snapshot is seen. That recheck is the only guard when a racing worker's lease is already `finished` and the live-lease check therefore passes. Nothing else in the schema changes.

### Files

- `src/kurafolio/persistence/ingestion_schema.py`: a new helper `_cleanup_backoff_sql` beside `_TERMINAL_SQL`, two placeholders in `CLAIM_PLAN_DDL`, two new PL/pgSQL variables, the locked recheck, and the fence taken from the recheck's count. Comments cite the owner decision of 2026-11-12.
- `tests/test_postgres_migration.py`: one new static test in `IngestionStorageDDLTests` and one extra fragment in an existing one; five new gated test methods and a few helper methods in `IngestionAppendOnlyPostgresTests`; older cleanup-lease times in three existing gated tests (see "Existing tests").
- `.github/workflows/ci.yml`: in the `postgres-foundation` job, raise `--expect-skipped 118` to 123 and the comment's "117 ingestion tests" to 122, one per new gated test method. If you add a different number of gated methods, use 118 + that number and 117 + that number. Leave `postgres-ingestion` at `--expect-skipped 0`.
- `docs/web-v2-imports.md`: the backoff text (AC-07).
- `tickets/IMP-007N.md`: the builder's own status, Plan ticks, Handoff and Log, as the quick start says.

### Interfaces

The helper, beside `_TERMINAL_SQL`:

```python
def _cleanup_backoff_sql(count, latest):
    """True while a set whose `count` earlier cleanup leases end with one created at `latest` must wait.

    Owner decision 2026-11-12 (IMP-007N): the set waits LEAST(30 s x 2^(count-1), 15 min)
    after its latest cleanup lease's created_at, on the database clock `n`. The exponent is
    clamped to 0..5 before the shift, so no count can overflow the interval or wrap the shift.
    """
    return ("(" + count + ">0 AND n<" + latest + "+LEAST(interval '30 seconds'*(1<<(GREATEST(LEAST(" + count +
            ",6),1)-1)::integer),interval '15 minutes'))")
```

- `n` is the function's clock variable at each call site. `1<<k` for k in 0..5 is exact in `integer`, and `interval * integer` (through `float8`) is exact for 30 s × 1..32. `GREATEST(...,1)` keeps the shift count at 0 or more even when `count` is 0, so the expression never depends on how PostgreSQL orders the `AND`. A count of 0 is false through `count>0`, not through a NULL `max`.
- At 6 earlier leases the uncapped window is 960 s, so the cap first applies there; `LEAST(count,6)` keeps every larger count at 900 s.
- An equivalent expression is acceptable only if it is exact, cannot overflow or error for any `bigint` count, and keeps the boundary: the set is eligible when `n >= latest + window` (AC-01 says "at or past").

Changes to `CLAIM_PLAN_DDL`:

1. DECLARE: add `earlier bigint;latest_cleanup timestamptz;`. Do not reuse `n` (the clock) or `lease` (the new lease ID).
2. Candidate query: after the existing live-lease `NOT EXISTS(...)`, add `AND NOT BACKOFF_CANDIDATE`, where `BACKOFF_CANDIDATE` renders as

   ```sql
   EXISTS(SELECT 1 FROM (SELECT pg_catalog.count(*) AS lease_count,pg_catalog.max(l.created_at) AS last_created
     FROM wl_ingestion.leases l WHERE l.tenant_id=x.tenant_id AND l.portfolio_id=x.portfolio_id AND
      l.set_id=x.id AND l.work_kind='cleanup') b WHERE <_cleanup_backoff_sql('b.lease_count','b.last_created')>)
   ```

   The aggregate subquery always returns one row. Its aliases must not equal any PL/pgSQL variable of the function (`earlier`, `n`, `lease` and the rest of the DECLARE list), so that `variable_conflict` can never fire. Keep the candidate query selecting only `tenant_id, portfolio_id, id`; never carry its counts or times into the locked section. Keep `ORDER BY x.created_at,x.id::text COLLATE "C" LIMIT 8` and `FOR UPDATE SKIP LOCKED` on the root unchanged.
3. Locked recheck: right after `CONTINUE WHEN selected.state NOT IN TERMINAL OR selected.cleanup_state NOT IN ('pending','failed');` and before the `UPDATE ... SET state='expired'` that closes lapsed cleanup leases, add:

   ```sql
   SELECT pg_catalog.count(*),pg_catalog.max(l.created_at) INTO earlier,latest_cleanup FROM wl_ingestion.leases l
    WHERE l.tenant_id=selected.tenant_id AND l.portfolio_id=selected.portfolio_id AND l.set_id=selected.id
     AND l.work_kind='cleanup';
   -- Owner decision 2026-11-12: a set whose cleanup keeps failing waits, and newer sets go first.
   CONTINUE WHEN BACKOFF_LOCKED;
   ```

   `BACKOFF_LOCKED` renders `_cleanup_backoff_sql('earlier','latest_cleanup')`, and `n` there is the value re-read after the locks. A set skipped here is left untouched: its lapsed leases stay as they are until a claim that hands it out.
4. Fence: replace `SELECT pg_catalog.count(*)+1 INTO next_fence FROM ... work_kind='cleanup';` with `next_fence:=earlier+1;`. Closing lapsed leases changes only their `state`, so the count is unchanged and decision 3 still holds. The backoff and the fence then come from one read and cannot disagree.
5. The replace chain at the end of the module: add `.replace('BACKOFF_CANDIDATE', ...)` and `.replace('BACKOFF_LOCKED', ...)`. Neither placeholder contains `ACK_HELD`, `ACK_CLAIMED`, `PREPARE_`, `TERMINAL`, `CLEANUP_SESSION`, `CODES` or `UUID_RE`, and the rendered text contains none of the placeholders replaced later, so their position in the chain does not matter.

Unchanged: the replay path for `held.id IS NOT NULL`, which returns before candidate selection; the prepare branch; the 30-second lease length; `CLEANUP_SESSION_DIGEST`; the acknowledgement shape; the error codes; `no_work` when the loop finds nothing.

AC-05 holds by construction. An overdue non-terminal set cannot have a cleanup lease, because the trigger refuses one, so its count is 0 and the predicate is false. Do not special-case it.

### Expected values (independent of the code)

Here k is the number of earlier cleanup leases of the set, in any state (`active`, `finished`, `expired` or `cancelled`), and the window runs from the `created_at` of the newest of them (not from `expires_at`, and not from the oldest).

| k | Window | Fence of the next claim |
|---|---|---|
| 0 | none: eligible at once | 1 |
| 1 | 30 s | 2 |
| 2 | 60 s | 3 |
| 3 | 120 s | 4 |
| 4 | 240 s | 5 |
| 5 | 480 s | 6 |
| 6 | 900 s (uncapped 960 s) | 7 |
| 7 | 900 s | 8 |
| 70 | 900 s, no error | 71 |

The database clock is `clock_timestamp()` and moves while a script runs, so no test can land exactly on a boundary. Test with margins, with every time set relative to `pg_catalog.clock_timestamp()`:

- inside: the newest lease is `window − 10 s` old, so the claim must return `no_work`. This assumes under 10 s between the update and the claim.
- past: the newest lease is `window + 1 s` old, so the set must be claimed. Time only moves forward, so this cannot flake.

### Tests

Name the acceptance IDs in each test's docstring or comments. Use synthetic rows only.

Static, in `IngestionStorageDDLTests` (no PostgreSQL):

| AC | Case | Expected |
|---|---|---|
| 01, 04 | New `test_cleanup_claim_backoff_is_one_shared_rule`. Count in `schema.CLAIM_PLAN_DDL`: `schema._cleanup_backoff_sql('earlier', 'latest_cleanup')`, `schema._cleanup_backoff_sql('b.lease_count', 'b.last_created')`, `next_fence:=earlier+1;`, `interval '15 minutes'`, `count(*)+1 INTO next_fence`, `CREATE INDEX`, `CREATE TABLE`, `ALTER TABLE`. Order, using anchors that each occur exactly once in today's rendered DDL (keep both comments): the candidate form lies between `-- Owner decision: the oldest terminal set whose cleanup is pending or failed and` and `ORDER BY x.created_at,x.id::text COLLATE "C" LIMIT 8`; the locked form lies between `CONTINUE WHEN selected.state NOT IN` and `-- A lapsed cleanup lease is closed before another one starts.`. Do not anchor on `ORDER BY x.created_at`, `FOR candidate IN` or `SET state='expired'`: each occurs more than once. | Counts 1, 1, 1, 2, 0, 0, 0, 0; both order checks true. Do not count `LEAST(`: the prepare branch already contains one. |
| 01 | Existing `test_cleanup_lease_functions_match_their_worker_declarations`: add `'BACKOFF_'` to its `assertNotIn` fragment list. | No placeholder survives. |
| 04 | Existing `test_inventory_is_the_exact_closed_contract_and_copy_isolated`, unchanged. | Still passes; `oracle.json` is not edited. |

Gated, in `IngestionAppendOnlyPostgresTests`. First add helper methods (not `test_` methods, so they do not change the skip count):

- `clone_set(set_id, *, seconds, cleanup)`: a replica-mode `INSERT INTO wl_ingestion.sets SELECT ...` from the own set, as `test_claim_selects_the_oldest_terminal_set_first` does, with the given ID, a distinct `creation_operation_id`, `created_at` and `expires_at` both shifted by `seconds` (the CHECK requires `expires_at=created_at+86400 s`), `state='CANCELLED'`, the given `cleanup_state`, `receipt_id` NULL and both `prepare_*` columns NULL. Always pass `cleanup` explicitly: a clone taken after `cleanup_call` would otherwise copy `failed`.
- `closed_cleanup_leases(set_sql, rows)`: a replica-mode `INSERT INTO wl_ingestion.leases(<explicit column list>)` that writes one closed cleanup lease per `(fence, state, age_seconds)`. Take `tenant_id`, `portfolio_id`, `incarnation` and `restore_epoch` from the target set row and `worker_id` from `self.WORKER`. Set `work_kind='cleanup'`, `attempt=fence`, `token_digest` the SHA-256 hex of `self.WORKER_TOKEN`, `session_digest=CLEANUP_SESSION_DIGEST`, `credential_version=0`, `created_at=pg_catalog.clock_timestamp()-<age>`, `expires_at=created_at`, `claim_request_id=pg_catalog.gen_random_uuid()` with a 64-hex `claim_request_digest`, and `member_id`, `raw_slot`, `cleanup_proof_bytes`, `last_request_*` and every `prepare_*` column NULL. States are `finished`, `expired` or `cancelled`; never `active` unless the case asks for a lapsed lease, and then `expires_at` must be in the past. Give every copied lease a strictly older `created_at` than the lease the case names as newest.
- `age_cleanup_leases(seconds, set_sql=None)`: a replica-mode `UPDATE wl_ingestion.leases SET created_at=created_at-<s>,expires_at=expires_at-<s> WHERE work_kind='cleanup'`, optionally limited to one set.
- `OWN_CLEANUP`: a labelled query `SELECT 'OWNCLEAN '||COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(l.state,l.fence) ORDER BY l.fence),'[]'::jsonb)::text FROM wl_ingestion.leases l WHERE l.work_kind='cleanup' AND l.set_id=<OWN_SET>::uuid;`. In any test with more than one set, read cleanup leases through this query or through the acknowledgement's `set_id` and `fence`, never through `CLEANUP_STATE['cleanup']`, which covers every set.

Each new gated test starts from `cleanup_seed()` and `cancel_call(catalog)` unless the row says otherwise. "Stuck" means: `plan_claim('first')` gives fence `'1'` and `cleanup_call('stuck', 'first')` with no proofs returns `cleanup_pending`, leaving the own set `['CANCELLED','failed']` with one `finished` cleanup lease. Every later claim in a script needs a fresh `claim_request_id` (`plan_claim(..., request=...)`) unless the row asks for a replay: reusing one lands on the replay path and returns `already_claimed` or `import_stale`, which would look like a backoff bug.

| AC | Test and case | Expected |
|---|---|---|
| 01, 03, 06 | `test_claim_skips_a_backed_off_set_for_a_newer_one`. Clone B (`seconds=1`, `cleanup='pending'`) right after the cancel. Make the own set stuck. Claim with a new request. | B, `claimed`, fence `'1'`: the stuck set does not block a newer one. |
| 01, 06 | Same test: claim again with a new request. | `NO_WORK` (the own set waits; B holds a live lease). |
| 01, 06 | Same test: set the own set's lease to 20 s old (inside), claim. | `NO_WORK`. |
| 01, 06 | Same test: set it to 31 s old (past), claim. | Own set, `claimed`, fence `'2'`; `OWNCLEAN` is `[['finished',1],['active',2]]`. |
| 01, 03, 06 | `test_claim_backoff_doubles_and_caps_at_fifteen_minutes`, one subtest per k in (1, 2, 3, 4, 5, 6, 7, 70). Make the own set stuck, then add k−1 closed leases with fences 2..k, cycling `expired`, `cancelled`, `finished`. Give fence f the age `W(k) − 10 + (k − f)` seconds, moving the real fence-1 lease with a replica `UPDATE`, so fence k is newest at `W(k) − 10` (inside). Claim; then `age_cleanup_leases(11)`; claim again. | Inside: `NO_WORK`. This is the pure "only backed-off sets remain" case of AC-03: the only set is waiting and no lease is live. Past: own set `claimed`, fence `str(k+1)`. Never `import_invalid` or `internal_error`. k = 3 only passes if `expired` and `cancelled` leases count; k = 6 proves the cap; k = 70 proves the clamp. |
| 01 | Same test, subtest `latest_not_earliest`: k = 2, leases 100 s and 40 s old. | `NO_WORK`: 40 s + 60 s is still ahead. Measuring from the oldest lease would wrongly claim. |
| 01 | Same test, subtest `created_not_expires`: k = 1, the lease created 40 s ago with `expires_at` 10 s ago. | `claimed`, fence `'2'`. Measuring from `expires_at` would wrongly return `NO_WORK`. |
| 01 | Same test, subtest `lapsed_counts`: the `finished` fence-1 lease 50 s old, plus an `active` fence-2 lease created 31 s ago whose `expires_at` has passed. Claim; then `age_cleanup_leases(30)`; claim. | First `NO_WORK` (k = 2, window 60 s). Then `claimed`, fence `'3'`, and `OWNCLEAN` is `[['finished',1],['expired',2],['active',3]]`. |
| 02, 03, 06 | `test_claim_backoff_never_fills_the_candidate_limit`. Make the own set stuck. Clone C1..C8 (`seconds` 1..8, `cleanup='failed'`), each with one closed `finished` cleanup lease of age 0. Clone Z (`seconds=9`, `cleanup='pending'`, no lease). Claim; claim; `age_cleanup_leases(31)`; claim; claim. | Z with fence `'1'`; then `NO_WORK`; then the own set with fence `'2'`; then C1 with fence `'2'`. The C leases must be closed: an `active` unexpired lease would already be filtered by the live-lease probe, and the test could not tell a candidate-query rule from a lock-only rule. With the rule only under the locks, the first claim returns `NO_WORK`. |
| 02 | `test_claim_backoff_keeps_oldest_first_and_overdue_sets_eligible`, subtest `tie`. Make the own set stuck. Clone `a7000000-0000-4000-8000-0000000000b2` and then `a7000000-0000-4000-8000-0000000000b1`, both `seconds=1`, `cleanup='pending'`. Claim three times. | `...b1` fence `'1'`, then `...b2` fence `'1'`, then `NO_WORK`. |
| 05 | Same test, subtest `overdue`. No cancel: move the own set two days back as `test_claim_expires_an_overdue_set_before_cleaning_it` does. Then clone O (`seconds=-1`, so it is older; `cleanup='failed'`) with one closed `finished` cleanup lease of age 0. Claim, read `CLEANUP_STATE`, claim. | First claim: the own set, `claimed`, fence `'1'`; `CLEANUP_STATE` shows `set` `['EXPIRED','pending']` and `members` `[['expired',2]]`. Second claim: `NO_WORK` (O waits; the own set holds a live lease). |
| 06 | `test_claim_replay_is_unaffected_by_backoff`. Make the own set stuck, `age_cleanup_leases(31)`, claim with request R. Repeat R. Claim with a new request. Then move the cleanup leases back 2 minutes with `expires_at` 1 s in the past, as the `lapsed` case of `test_cleanup_and_claim_refuse_without_changing_anything` does, and repeat R. | R: `claimed`, fence `'2'`. Repeat while the set is inside its 60 s window: `already_claimed`, equal to the first acknowledgement except `outcome`. New request: `NO_WORK`. Repeat after the lapse: `{'ok': False, 'code': 'import_stale'}`, as today. |

Existing tests that claim the same set again within a window must give the earlier cleanup lease an older time. Do not weaken any assertion; expected fences and states stay as they are. Two of these tests have no `replica` and `origin` strings yet; add them as the other cleanup tests do.

- `test_cleanup_after_cancel_during_reception_releases_the_unbound_slot_once`: let `past_deadline` also move the cleanup lease back 3 minutes, for example `WHERE work_kind IN ('normalize','cleanup')`.
- `test_cleanup_holds_a_launched_attempt_until_its_proof_succeeds`: move cleanup leases back at least 31 s before `second` and at least 61 s before `third`. Two minutes each is simplest.
- `test_cleanup_never_releases_a_slot_finish_already_returned`: move cleanup leases back at least 31 s before `second`. The `finish_proved` subtest still expects `NO_WORK`, because that set is `complete`.
- `test_cleanup_and_claim_refuse_without_changing_anything` already moves the lease back 2 minutes, and `test_claim_selects_the_oldest_terminal_set_first` and `test_claim_expires_an_overdue_set_before_cleaning_it` claim each set once. They need no change.

### Docs (AC-07)

In `docs/web-v2-imports.md`:

- Replace "picks the oldest set that is terminal with cleanup `pending` or `failed` and has no live cleanup lease" with wording that keeps the oldest-first rule and adds the backoff. Proposed: "picks the oldest set that is terminal with cleanup `pending` or `failed`, has no live cleanup lease and is not waiting out a backoff. By owner decision, a set that has had n cleanup leases waits 30 seconds × 2^(n−1), capped at 15 minutes, from the creation of its latest cleanup lease on the database clock. Every earlier cleanup lease counts, including expired and cancelled ones. A waiting set never blocks a newer one, and when only waiting sets remain the claim returns `no_work`."
- Replace "the next claim retries it (`cleanup_pending`)" with "a later claim retries it once its backoff has passed (`cleanup_pending`)".
- Add "backoff" to the list that starts "Opt-in PostgreSQL tests cover cancel during reception".

### Rollback

Revert the commit. The change has no data migration, no table, column or index change and no inventory change. Lease rows written under either function body are valid under the other, and the fence rule is the same. No operational `0004` profile exists to upgrade. A synthetic test database built from the old source fails `verify_functions` against the new source (and the reverse), so recreate it with `python scripts/postgres.py test-environment` rather than editing it.

### Negative cases the review should check

- A backed-off set is filtered inside the candidate query, not only under the locks. `test_claim_backoff_never_fills_the_candidate_limit` proves this; the static test checks the placement.
- The recheck under the locks is a new statement after the locks are taken and reads `n` re-read after them. No single-session test can show the race (the root lock is `SKIP LOCKED`, so a second session never waits between the two reads), so the reviewer checks it by reading the code.
- The count is scoped to tenant, portfolio, set and `work_kind='cleanup'`. The candidate-limit test fails if it counts leases of other sets.
- A huge count gives the 900 s window, not `import_invalid` (k = 70).
- Replay never consults the backoff, and a lapsed replay is still `import_stale`.
- A set skipped by the backoff is not modified: no lease is closed, no fence used.

### Do not touch

- The prepare branch of `claim_plan_v1`, `_PREPARE_CLAIM_SQL`, `cleanup_set_v1`, `_purge_v1`, `_lease_ddl`, the `_transition_v1` lease trigger, `ingestion_restore.py`, `ingestion_migration.py` and the migration files under `src/kurafolio/persistence/migrations/`.
- `tests/fixtures/ingestion/oracle.json`, everything under `docs/specs/imp-007-r7/`, `REVISION` and `PREDECESSOR`.
- The cleanup lease length, the fence rule, the session marker, the acknowledgement fields and the error codes.
- `tickets/ROADMAP.md` and other tickets.

### Stop and ask if

- AC-03 or acceptable claim performance seems to need an index, a column or a stored retry time. AC-04 forbids all three.
- Any inventory, oracle, structure digest or r7 bundle file would have to change.
- An existing test's assertion would have to be weakened, rather than given an older lease time, to pass.
- The opt-in PostgreSQL suite cannot run in your environment. A skipped test is not acceptance; report it and do not open the PR as passing.
- You find an operational `0004` install, or any path that upgrades an installed `0004_ingestion` function in place.
- IMP-007M, or any other change to `claim_plan_v1`, merges to `main` before you start and touches the cleanup branch. Merge `origin/main`, then stop if the two rules interact.
- The backoff should be measured from anything other than the newest cleanup lease's `created_at`, or should leave some lease states out of the count. AC-01 and the Handoff gotcha settle both; any doubt goes to the owner.

## Plan

- [x] Add `_cleanup_backoff_sql`, the two placeholders, the locked recheck and `next_fence:=earlier+1` to `CLAIM_PLAN_DDL`, with the static test and the extra fragment check.
- [x] Give the three existing gated cleanup tests older lease times; add the helper methods and the five gated tests; raise the `postgres-foundation` skip count and comment in `.github/workflows/ci.yml`.
- [ ] Update `docs/web-v2-imports.md`; run the ingestion PostgreSQL and full suites; start the independent review; open the PR.

## Decisions needed

None. The owner's Gate A of 2026-11-12 (30 s × 2^(n−1), capped at 15 minutes; oldest-first among eligible sets; no new columns) and the Handoff's gotchas settle every behaviour this plan needs. No change to a gated section is proposed.

## Handoff

- State: codex/gpt-6.1-sol completed the planned implementation in the five approved paths; the ticket checkpoint is committed at `a22fcf6`, and the remaining implementation is ready for its local commit. Actual opt-in PostgreSQL passes: 139 tests, zero skips/failures/errors (97.585 s). The full Python suite passes: 1385 tests, 251 skips (723.380 s); 248 are optional/opt-in, two lacked optional PostgreSQL dependencies and one was denied a loopback socket by the sandbox. The two configuration tests and the native restart test pass in targeted reruns with no skips. Static DDL tests pass (17), and the inventory/oracle/r7 bundle and approved spec remain unchanged. Language, worktree/history publication and ticket checks pass. Candidate image and independent review remain outstanding.
- Next step: Commit the reviewed scope, run `.venv/bin/python scripts/check_pr_image.py` from the clean tracked tree and retain the exact receipt. After publication approval, open the PR with independent review marked NOT RUN and request `review IMP-007N` in Claude Code. The configured Claude Opus 5.5 reviewer is unavailable in Codex; owner review follows that independent review.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python scripts/run_gated_tests.py --expect-skipped 0 -- discover -s tests -p 'test_postgres_migration.py'`; `PYTHONPATH=src ../../../.venv/bin/python -m unittest discover -s tests -v`; `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_web.py' -k test_native_server_restart_preserves_session_and_settings -v`. Local logs and the validated PR draft are under ignored `work/imp-007n/`.
- Gotchas: Count every earlier cleanup lease, including expired and cancelled rows. Replay and prepare are unchanged; filter before `LIMIT 8` and reread under the locks. Git and Docker socket operations need local administrative permission. The initial dotted native-test invocation failed on a sibling import; use discovery as above. No code repair was needed.
- Open questions: None.

## Log

- 2026-11-12 claude-code/claude-opus-5-5: filed from the IMP-007C review finding; owner chose exponential backoff (30s × 2^(n−1), capped at 15 minutes, oldest-first among eligible sets, no new columns).
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the bullet naming the r7 contract bundle from Context into Requirements and numbered the acceptance criteria AC-IMP-007N-01 to 07. Spec hash sha256:c3e06c751ef4816ad200095284163430738b7a0e1783e78999605dd5035e92eb, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:c3e06c751ef4816ad200095284163430738b7a0e1783e78999605dd5035e92eb.
- 2026-11-19 claude-code/opus-5.5: wrote the Build plan, Context and Plan from `main` at `a2f5f2b` in plan PR https://github.com/gh-slee/kurafolio/pull/81, finishing and correcting an unreviewed earlier draft; no Decisions needed and no gated section changed.

- 2026-11-20 codex/gpt-6.1-sol: claimed the ticket from `d902717` after verifying the merged Build plan and unchanged approved spec; implementation and synthetic verification starting.

- 2026-11-20 codex/gpt-6.1-sol: implemented the five planned paths, with 17 static tests passing and gated PostgreSQL execution still required; no gated section, frozen r7 file, inventory or oracle changed.

- 2026-11-20 codex/gpt-6.1-sol: full Python suite passed (1385 run, 251 skips (248 optional/opt-in, two missing optional PostgreSQL dependencies and one sandbox-denied loopback test), zero failures/errors, 723.380 s); installed the existing locked PostgreSQL test dependencies in an ignored local venv. Actual PostgreSQL acceptance, the sandbox-denied native restart check, candidate image and independent review remain separate gates.

- 2026-11-20 codex/gpt-6.1-sol: actual opt-in PostgreSQL passed (139 tests, 97.585 s, zero skips/failures/errors), including every new backoff case and the unchanged inventory check. Targeted PostgreSQL configuration (two tests) and native restart (one test, 1.354 s) passed without skips; the earlier native invocation failure was an import-path issue. No code repair or unplanned behaviour was needed. Candidate image and independent Claude Opus 5.5 review are still outstanding; no PR exists.
