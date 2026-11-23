---
id: IMP-007O
title: Return the stored member context bytes from the bind result of reserve_member_v1
priority: P0
status: done
type: feature
parent: IMP-007
depends_on: []
resources: [ingestion-schema-sql]
risk: high
size: S
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-22, Gate A on the amended text (hash 53f3126f…): Approve Gate A"
review: independent
branch: ticket/imp-007o-return-the-stored-member-context-bytes-f
pr: https://github.com/gh-slee/kurafolio/pull/103
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:53f3126f8a92fbaaf5bb874cdfaf90d5107dd1305a6f7efc5ef76b41f9faef06
updated: 2026-11-22
---

# IMP-007O: Return the stored member context bytes from the bind result of reserve_member_v1

## Goal

The upload route (IMP-007U) must send the import worker one frame holding the hand-off metadata, the member's stored context bytes and the raw bytes, as the frozen r7 protocol requires. Today the bind step of `reserve_member_v1` returns only the digest and the length of those context bytes, and the gateway role cannot read `wl_ingestion.members`. Make a successful bind also return the stored context bytes, so the API can build the frozen frame without any new table access or wire change.

## Context

- Filed on 2026-11-20 from the IMP-007E plan (PR #87), Decisions needed item 2, option (a), which the owner chose.
- The bind result is built in `RESERVE_DDL` in `src/kurafolio/persistence/ingestion_schema.py` (the final `RETURN` of the bind branch, lines 2787 to 2793 on `main` at `96eadc2`). It returns `version`, `job_id`, `set_id`, `member_id`, `fence`, `raw_sha256`, `raw_bytes`, `context_sha256`, `context_bytes` (the length, from `octet_length(mem.context_bytes)`), `realm_digest`, `expires_at` and `raw_deadline`.
- The worker frame (`POST /internal/v1/handoffs` in [protocol-appendix.md](../docs/specs/imp-007-r7/protocol-appendix.md)) carries the `Handoff` metadata, then the context bytes, then the raw bytes. `runner_client.pack_input(..., schema='Handoff')` checks all three.
- The `Handoff` DTO in [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json) has `additionalProperties: false`, and its `context_bytes` is an integer length. The new key therefore cannot be called `context_bytes`, and the API (IMP-007U) removes it before it validates `Handoff`.
- The frozen [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json) pins the function's signature (`text, uuid, bigint, jsonb, text, jsonb` returning `jsonb`), its grant (`identity_source_gateway`) and `search_path`, not its body. The body is pinned on the code side, by `verify_functions` (`src/kurafolio/persistence/ingestion_migration.py:139`), which compares each installed `prosrc` with the text that `function_ddl()` renders from the current source. Corrected in the plan pull request: an earlier version of this bullet said the structure digests cover `prosrc`. They do not. `_structure_digest` (`:221`) hashes relations, columns, constraints, indexes, policies, types and triggers only, so `EXPECTED_STRUCTURE_SHA256` (`:306`) and `EXPECTED_RESTORED_STRUCTURE_SHA256` (`:311`) do not move when a function body changes. The `sql-inventory` key of `tests/fixtures/ingestion/oracle.json` has no body either, and no oracle vector holds a `reserve_member_v1` result. IMP-007N found the same when it changed `claim_plan_v1` in place, and it changed no digest. The owner chose to amend the Requirements bullet and AC-03 to say so (Decisions needed item 1) and gave Gate A on the amended text on 2026-11-22.
- Changing the `0004` function text in place is safe only if no database outside disposable tests ran `operator migrate-ingestion` at `0004`. Evidence on `main` at `96eadc2`:
  - `Database` (`src/kurafolio/persistence/context.py:47`) maps only `foundation`, `identity` and `sources` to a revision, so no runtime profile can serve `0004`. IMP-007E adds it.
  - The repository has no tags or releases.
  - `docs/web-v2-imports.md` says there is no operational `0004` profile, and its "Explicit 0004 installation" section tells operators to use a synthetic instance.
  - None of this proves that no operator ran the command, so Decisions needed item 2 asked the owner. On 2026-11-22 the owner answered "No, none has" (option (a)).
- The same applies to backups. `backup-ingestion` dumps the whole `0004` catalog, function bodies included, and `restore-ingestion` then runs `verify_inventory(..., quarantined=True)` (`src/kurafolio/persistence/ingestion_restore.py:710`, `:734`), which reaches `verify_functions`. A backup taken before this change would therefore be refused with `migration_target_invalid` after it. The backup manifest pins `EXPECTED_STRUCTURE_SHA256` (`ingestion_restore.py:35`), which does not change.
- Shares `ingestion-schema-sql` with IMP-007Q, IMP-007R and IMP-007T, so these build one at a time. IMP-007N and IMP-007W, which also held it, are `done`; IMP-007W merged first (#96) and changed no structure digest. On 2026-11-22 IMP-007W's claim file was still recorded and held the lock, which is why `next` and `next --plan` did not list this ticket. `python3 scripts/tickets.py cleanup` releases that claim once its worktree is clean and merged.
- No caller of `reserve_member_v1` exists outside the tests on `main`: the upload route is IMP-007U, which depends on this ticket. The existing gated tests are in `tests/test_postgres_migration.py`, class `IngestionAppendOnlyPostgresTests`: `reserve_seed`, `reserve_call`, `RESERVE_STATE` and the three tests from `test_reserve_then_bind_opens_one_bounded_attempt_and_hands_off_metadata` to `test_reserve_and_bind_refuse_without_keeping_a_slot`. `run_labelled` runs one psql script in `BEGIN ... ROLLBACK` and collects lines whose label is upper case and whose value starts with `{` or `[`.
- The members CHECKs allow `context_bytes` of 1 to 1,048,576 bytes and require `context_digest` to be its SHA-256 hex (`ingestion_schema.py:5385-5386`). The members trigger (`ingestion_schema.py:5000`) refuses any change to `context_bytes` other than clearing them on a terminal set, so a test that sets the bytes uses a replica-mode `UPDATE` (triggers off, CHECKs still on).

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md). The r7 inventory is the frozen baseline [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json). The inventory the code is tested against is the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`, checked by `tests/test_postgres_migration.py`; it is the r7 baseline plus later approved additions.
- A successful `reserve_member_v1` call with `action: bind` also returns the member's stored `context_bytes`, encoded as unpadded base64 under one new private key. The key's name differs from every key of the `Handoff` DTO. Every other key and value of the bind result stays as it is, including `context_bytes` as the length.
- `action: reserve` results and every refusal of either action do not change.
- No DTO in `wire-contracts.json` or `codec-schema.json` changes. No function, argument, return type, grant, table, column, index or trigger is added or changed; only the body of `reserve_member_v1` changes.
- The change is made in place at revision `0004_ingestion`: only the `0004` function text of `reserve_member_v1` changes. `EXPECTED_STRUCTURE_SHA256`, `EXPECTED_RESTORED_STRUCTURE_SHA256` and `tests/fixtures/ingestion/oracle.json` stay as they are, because neither the structure digest nor the oracle covers function bodies; `verify_functions` checks each installed body against the code. The `0001` to `0003` providers stay byte-identical.
- Before building, confirm that no database outside disposable tests has run `operator migrate-ingestion` at `0004`. If that cannot be confirmed, stop and ask the owner whether a new revision is needed instead.
- The new key never carries raw bytes or the hand-off token. No error, notice or log line carries the context bytes.
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.

## Acceptance criteria

- [x] AC-IMP-007O-01: A successful bind returns the new key, and its value decodes to exactly the member's stored `context_bytes`, whose SHA-256 equals `context_sha256` and whose length equals `context_bytes` in the same result.
- [x] AC-IMP-007O-02: Every other key and value of the bind result, every `action: reserve` result and every refusal are unchanged; a test compares them with the vectors recorded before this change.
- [x] AC-IMP-007O-03: The function's signature, return type, grant and `search_path`, the frozen and oracle inventories, `EXPECTED_STRUCTURE_SHA256` and `EXPECTED_RESTORED_STRUCTURE_SHA256` are unchanged; only the text of `reserve_member_v1` changes, and `tests/test_postgres_migration.py` passes against a real `0004` install.
- [x] AC-IMP-007O-04: No DTO in `wire-contracts.json` or `codec-schema.json` changes, and the new key is not a property of `Handoff`.
- [x] AC-IMP-007O-05: Opt-in PostgreSQL tests cover a bind at the smallest and the largest allowed context sizes (1 and 1,048,576 bytes).
- [x] AC-IMP-007O-06: The pull request records the evidence that no database outside disposable tests ran `operator migrate-ingestion` at `0004`, or the owner's decision to use a new revision.
- [x] AC-IMP-007O-07: `docs/web-v2-imports.md` says that the bind result carries the context bytes for the trusted API only.

## Build plan

- Based on: `main` at `96eadc2` (after IMP-007W, #96).
- Tier: `frontier`, `risk: high`, `review: independent`. The reviewer model's fresh-context QA review and a second Architect review are required before the owner's review (tickets/README.md, "Reviews").

### Before you claim

1. On `main`, `spec_approved` must hold the hash of the amended gated text (Gate A given 2026-11-22, Decisions needed item 1). The `0004` confirmation the Requirements ask for is Decisions needed item 2, answered "No, none has" on 2026-11-22, so the in-place change goes ahead; cite that Log line as the AC-06 evidence. If `spec_approved` does not match, do not claim; report that the ticket waits on the owner.
2. `git fetch origin`, then `python3 scripts/tickets.py cleanup`. IMP-007W's merged claim held `ingestion-schema-sql` on 2026-11-22. If `claim` still refuses the lock, run `python3 scripts/tickets.py list` and stop if a live claim holds it. Never release another agent's live claim.
3. Run `python3 scripts/tickets.py spec IMP-007O`. It must report `MATCHES`, with `spec_approved` holding the hash of the amended text (sha256:53f3126f8a92fbaaf5bb874cdfaf90d5107dd1305a6f7efc5ef76b41f9faef06, approved 2026-11-22). If it reports `CHANGED`, the gated text moved after that approval; do not build.
4. Check whether `src/kurafolio/persistence/ingestion_schema.py` or `ingestion_migration.py` changed on `origin/main` since `96eadc2` (`git log 96eadc2..origin/main -- src/kurafolio/persistence/`). If they did, recompute the pre-change values in "Baseline" from `origin/main` before you edit and use those. If the bind `RETURN` itself changed, stop and ask.

### Baseline (record before editing)

On the unchanged tree, save the output of these commands under ignored `work/imp-007o/` and quote the results in the PR:

- `PYTHONPATH=src .venv/bin/python -c "import hashlib; from kurafolio.persistence import ingestion_schema as s, ingestion_migration as m; print(*(hashlib.sha256(t.encode()).hexdigest() for t in (s.RESERVE_DDL, m.function_ddl(), s.tables_ddl(), s.triggers_ddl(), m.inherited_guard_replacements())), sep='\n')"`. At `96eadc2` this prints, in order: `a697e3798ee898150bf1291773cb154b63680705b7ea845aef48f7217ada2e47` (`RESERVE_DDL`), `7ad71d22dd67d7ed49b7a3f095040d2c04c3eddf97015aed8f4abde002ba8852` (`function_ddl()`), `64b4b1b52df00c6c3f8efb59f7917ed176a7f2b455573bb935052e5a737ca7e9` (`tables_ddl()`), `585b16d1c69965a595ea43e35fef6b1bc03dd7bd98500057c50281c848575f56` (`triggers_ddl()`) and `09b6dbb7eceea20cbfb8becc711bfc5a5dafd5a2b841023938214aeb6de62475` (`inherited_guard_replacements()`). The values are the same for any `PYTHONHASHSEED`.
- The three existing gated reserve tests, on unchanged code: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_postgres_migration.IngestionAppendOnlyPostgresTests.test_reserve_then_bind_opens_one_bounded_attempt_and_hands_off_metadata tests.test_postgres_migration.IngestionAppendOnlyPostgresTests.test_reupload_advances_the_fence_and_clears_old_raw_fields tests.test_postgres_migration.IngestionAppendOnlyPostgresTests.test_reserve_and_bind_refuse_without_keeping_a_slot`. All three must pass with no skip.

### Files

- `src/kurafolio/persistence/ingestion_schema.py`: one insertion in the bind `RETURN` of `RESERVE_DDL` (below), and one Python comment line above `RESERVE_DDL`. Nothing else in the module changes.
- `tests/test_postgres_migration.py`: four module constants, one static test, four gated tests, one extra assertion in an existing test (below).
- `.github/workflows/ci.yml`: in job `postgres-foundation`, `--expect-skipped 128` becomes `--expect-skipped 132`, and the comment above it says "the 131 ingestion tests". The four new gated methods each add one skip there. Job `postgres-ingestion` keeps `--expect-skipped 0`.
- `docs/web-v2-imports.md`: the `reserve_member_v1` paragraph (AC-07, below).
- `tickets/IMP-007O.md`: status, Handoff, Log and the AC-06 evidence.

### Interfaces

- New key: `context_unpadded_base64`. It differs from all 13 `Handoff` properties (`version`, `job_id`, `set_id`, `member_id`, `fence`, `raw_sha256`, `raw_bytes`, `context_sha256`, `context_bytes`, `handoff_token`, `realm_digest`, `expires_at`, `raw_deadline`). The test harness of the sources profile already uses `context_base64` for padded base64 (`tests/fixtures/source_capabilities/worker.py:108`), so do not use that name.
- Value: the member's stored `context_bytes` as base64 in the standard alphabet of RFC 4648 section 4 (`A-Z`, `a-z`, `0-9`, `+`, `/`), with no `=` padding and no line breaks. It is never base64url. A decoder accepts only `^[A-Za-z0-9+/]+$` with length mod 4 not equal to 1, then decodes after adding `'=' * (-len(value) % 4)` with `validate=True`. IMP-007U decodes it that way and removes the key before it validates `Handoff`.
- SQL: PostgreSQL's `encode(bytea,'base64')` follows RFC 2045. It breaks the output with a newline after every 76 characters and pads with `=`. A disposable PostgreSQL 16 check during planning showed the first newline at position 77 of a 100-byte input. The expression strips both:

  ```sql
  pg_catalog.translate(pg_catalog.encode(mem.context_bytes,'base64'),pg_catalog.chr(10)||'=','')
  ```

  `=` appears only as padding, so removing every `=` is the same as trimming the end. `pg_catalog.chr(10)` follows the module's `CONTROLS` idiom and avoids an `E''` string inside the raw Python string.
- The exact edit. In `RESERVE_DDL` the bind `RETURN` line

  ```text
    'context_bytes',pg_catalog.octet_length(mem.context_bytes),'realm_digest',selected.realm_digest,
  ```

  becomes the two lines

  ```text
    'context_bytes',pg_catalog.octet_length(mem.context_bytes),
    'context_unpadded_base64',pg_catalog.translate(pg_catalog.encode(mem.context_bytes,'base64'),pg_catalog.chr(10)||'=',''),'realm_digest',selected.realm_digest,
  ```

  That is, insert exactly the string `IMP_007O_ADDED` (below) right after `'context_bytes',pg_catalog.octet_length(mem.context_bytes),`. Do not change the SQL comment `-- Handoff metadata for the trusted API only; it adds its own plaintext token.`, any other key, the reserve branch, the refusals, the exception block or the `.replace(...)` chain. The inserted text contains none of the chain's placeholders (`MEMBER_PINS`, `SESSION_RECHECK`, `UUID_RE`, `INSTANT_*`).
- Python comment: below the two existing comment lines above `RESERVE_DDL`, add `# bind also returns the stored context bytes (unpadded base64) for the trusted API's worker frame.` It sits outside the SQL string, so `prosrc` does not see it.
- The stored bytes cannot be NULL while a bind can succeed: the members trigger clears `context_bytes` only on a terminal set, and bind needs a `RECEIVING` set. Add no new refusal for NULL; AC-02 forbids new refusals. With NULL the key would be JSON null by construction.
- Unchanged: the `_FUNCTIONS` declaration (`ingestion_schema.py:176`), every grant, `function_ddl()` order, `ingestion_migration.py` (including `EXPECTED_STRUCTURE_SHA256` `bfa65a66...` and `EXPECTED_RESTORED_STRUCTURE_SHA256` `7008e006...`), `ingestion_restore.py` (`PROFILE` keeps `"functions": "68"`), `migrations/versions/0004_ingestion.py` (it only calls `function_ddl()`), `tests/fixtures/ingestion/oracle.json`, `src/kurafolio/ingestion/contracts.py` and every file under `docs/specs/imp-007-r7/`.

### Expected values (independent of the code)

Computed with Python's `base64` and `hashlib` while planning. The 1, 4 and 1,048,576-byte strings were also checked with the expression above on a disposable PostgreSQL 16 container. The test image is PostgreSQL 18, which the gated run confirms.

| Case | Stored bytes | `context_unpadded_base64` | `context_bytes` | `context_sha256` | `job_id` |
|---|---|---|---|---|---|
| 1 byte (smallest allowed) | hex `37` (`7`) | `Nw` | 1 | `7902699be42c8a8e46fbbb4501726517e86b22c56a189f7625a6da49081b2451` | `None` |
| 2 bytes | hex `3132` (`12`) | `MTI` | 2 | `6b51d431df5d7f141cbececcf79edf3dd861c3b4069f0b11661a3eefacbba918` | `None` |
| 3 bytes, no padding | hex `313233` (`123`) | `MTIz` | 3 | `a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3` | `None` |
| 4 bytes, standard alphabet | hex `22dfbf22` (a JSON string holding U+07FF) | `It+/Ig` (base64url would give `It-_Ig`) | 4 | `96f88d3928c2796bc818c6fc1e7e77602e02d53cc796b5187cabab09ced06a07` | `None` |
| 1,048,576 bytes (largest allowed) | `{"job_id":"90000000-0000-4000-8000-00000000a001","x":"` + 1,048,520 × `a` + `"}` (54 + 1,048,520 + 2 bytes) | 1,398,102 characters, starting `eyJqb2JfaWQiOiI5MDAwMDAw` and ending `FhYWEifQ` | 1048576 | `eefc21395b5b6c4f8b8b03b673c889e05029c574b1339d9d3020a0212a91bb43` | `90000000-0000-4000-8000-00000000a001` |

The JSON null `job_id` for the small cases is today's behaviour: `convert_from(...)::jsonb->>'job_id'` is NULL for a JSON number or string. These contexts cannot come from `create_set_v1`; they exist only to test the size bounds. A context that is not JSON would make the existing `::jsonb` cast fail with `data_exception`, which bind returns as `import_invalid`, so every synthetic context above is valid JSON.

Recorded vectors of the pre-change body, from `RESERVE_DDL` at `96eadc2` (AC-02):

- Bind value keys, exactly: `BIND_KEYS = {'version', 'job_id', 'set_id', 'member_id', 'fence', 'raw_sha256', 'raw_bytes', 'context_sha256', 'context_bytes', 'realm_digest', 'expires_at', 'raw_deadline'}`. After the change the key set is `BIND_KEYS | {'context_unpadded_base64'}`. `version` is `1`; `job_id` is the context's `job_id`; `fence` is the member's fence as a string; `raw_sha256` and `raw_bytes` echo the request; `context_sha256` is `members.context_digest`; `context_bytes` is the stored length; `realm_digest` is the set's; `expires_at` is `LEAST(bind clock + 60 s, raw_deadline)` and `raw_deadline` the member's, both as Instants with `fractional_digits` 6.
- Reserve value keys, exactly: `RESERVE_KEYS = {'action', 'set_id', 'member_id', 'lease_id', 'fence', 'raw_deadline', 'offer_expires_at'}`, with `action` `'reserve'`.
- Refusals, exactly `{'ok': False, 'code': <code>}` with no other key. From the existing tests: second reserve while the attempt is live `import_busy`; bind with a wrong fence `import_stale`; a second bind `import_conflict`; a bind after the raw deadline `import_reupload_required`; `raw_bytes` 10485761, a string `raw_bytes` or a bad digest `import_invalid`; plus each case of `test_reserve_and_bind_refuse_without_keeping_a_slot`.

### Tests

Name the acceptance IDs in each test's docstring. Use synthetic rows only. Add four module constants near `ORACLE` in `tests/test_postgres_migration.py`:

```python
# IMP-007O: the one insertion into the bind RETURN of reserve_member_v1.
IMP_007O_ADDED = ("\n  'context_unpadded_base64',pg_catalog.translate(pg_catalog.encode("
                  "mem.context_bytes,'base64'),pg_catalog.chr(10)||'=',''),")
# SHA-256 of RESERVE_DDL before IMP-007O. A later ticket that changes another part
# of reserve_member_v1 replaces this pin with its own pre-change hash or retires the
# IMP-007O comparison tests; its plan decides which.
PRE_IMP_007O_RESERVE_SHA256 = 'a697e3798ee898150bf1291773cb154b63680705b7ea845aef48f7217ada2e47'
# Result keys recorded from the pre-change body (AC-IMP-007O-02).
BIND_KEYS = frozenset({'version', 'job_id', 'set_id', 'member_id', 'fence', 'raw_sha256', 'raw_bytes',
                       'context_sha256', 'context_bytes', 'realm_digest', 'expires_at', 'raw_deadline'})
RESERVE_KEYS = frozenset({'action', 'set_id', 'member_id', 'lease_id', 'fence', 'raw_deadline',
                          'offer_expires_at'})
```

The pre-change body for the comparison tests is `schema.RESERVE_DDL.replace(IMP_007O_ADDED, '', 1)`. Installed in a test, it becomes `CREATE OR REPLACE FUNCTION` with `.replace('CREATE FUNCTION ', 'CREATE OR REPLACE FUNCTION ', 1)`.

Static, in `IngestionStorageDDLTests` (no PostgreSQL), one new test `test_bind_returns_the_context_bytes_under_one_private_key`:

| AC | Case | Expected |
|---|---|---|
| 01, 02 | Counts in `schema.RESERVE_DDL`: `IMP_007O_ADDED`, `'context_unpadded_base64'`, `'base64'`, `pg_catalog.encode(mem.context_bytes` | 1, 1, 1, 1 |
| 01, 02 | Position of `IMP_007O_ADDED` | After `-- Handoff metadata for the trusted API only` and after `'offer_expires_at',` (the reserve `RETURN`), and before `EXCEPTION WHEN SQLSTATE '22023'` |
| 02, 03 | `hashlib.sha256(schema.RESERVE_DDL.replace(IMP_007O_ADDED, '', 1).encode()).hexdigest()` | `PRE_IMP_007O_RESERVE_SHA256`: every other byte of the function is the pre-change text |
| 04 | `'context_unpadded_base64'` among the property names of every DTO in `json.loads` of each value of `contracts._WIRE`, and of every `$defs` entry of `docs/specs/imp-007-r7/wire-contracts.json` | Absent in both; `Handoff` still has exactly the 13 properties listed in Interfaces |
| 01 | `re.search(r'RAISE\s+(NOTICE\|LOG\|WARNING\|INFO\|DEBUG)', schema.RESERVE_DDL)` | `None`: no notice or log line can carry the bytes |

The existing `test_create_and_reserve_match_their_gateway_declarations` and `test_inventory_is_the_exact_closed_contract_and_copy_isolated` pass unchanged.

Gated, in `IngestionAppendOnlyPostgresTests` (`KURAFOLIO_INGESTION_TEST=1`). Use `reserve_seed()` and `reserve_call(...)`. Two small helpers (not `test_` methods):

- `context_update(expression)`: `SET LOCAL session_replication_role=replica;UPDATE wl_ingestion.members m SET context_bytes=v.b,context_digest=pg_catalog.encode(pg_catalog.sha256(v.b),'hex') FROM (SELECT <expression> AS b) v WHERE m.id=<NEW_MEMBER>::uuid;SET LOCAL session_replication_role=origin;`. Both columns change in one statement because of the CHECKs.
- `STORED`: `SELECT 'STORED '||pg_catalog.jsonb_build_object('hex',pg_catalog.encode(m.context_bytes,'hex'),'digest',m.context_digest)::text FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1;`

| AC | Test and case | Expected |
|---|---|---|
| 01, 04 | `test_bind_returns_the_stored_context_bytes_for_the_worker_frame`. Synthetic raw `raw = b'synthetic,raw\n'` and token `token = 'ab' * 32`. Reserve, then bind with `raw_sha256` and `raw_bytes` of `raw` and `handoff_token_digest` the SHA-256 hex of `bytes.fromhex(token)`, then `STORED`. Let `ctx = bytes.fromhex(STORED['hex'])`, the context `create_set_v1` built. | `BIND['ok']` is true. The value's key set is `BIND_KEYS \| {'context_unpadded_base64'}`. `len(ctx) > 57`, so PostgreSQL's line break would have appeared. The new value fully matches `[A-Za-z0-9+/]+`, contains no `\n` and no `=`, and equals `base64.b64encode(ctx).decode().rstrip('=')`. Decoding it with padding added and `validate=True` gives `ctx`. `hashlib.sha256(ctx).hexdigest()` equals both `context_sha256` and `STORED['digest']`, and `len(ctx)` equals `context_bytes`. Neither `token` nor its digest nor `raw.hex()` occurs in `json.dumps(out['BIND'])`, and there is no `handoff_token` key. |
| 04 | Same test: build `metadata` as the value without `context_unpadded_base64`, plus `handoff_token=token`, and call `runner_client.pack_input(metadata, ctx, raw, schema='Handoff')`. Then call it again with the key left in. | The first call returns a frame ending in `ctx + raw` whose first four bytes are the length of the encoded metadata. The second raises `IngestionError`, because `Handoff` is closed. |
| 05, 01 | `test_bind_returns_context_bytes_at_the_size_bounds`, one subtest per row of the expected-values table. Reserve, `context_update(...)`, then bind. Use `pg_catalog.decode('<hex>','hex')` for the four small cases and `pg_catalog.convert_to('{"job_id":"90000000-0000-4000-8000-00000000a001","x":"'\|\|pg_catalog.repeat('a',1048520)\|\|'"}','UTF8')` for the largest, so the script stays small. Build the expected bytes in Python. | Per row: `ok` true; `context_unpadded_base64`, `context_bytes`, `context_sha256` and `job_id` exactly as in the table; decoding with `validate=True` gives the Python bytes. For the largest case also check the length 1,398,102 and that the value fully matches `[A-Za-z0-9+/]+`. |
| 02 | `test_bind_and_reserve_match_the_pre_change_body_except_the_new_key`, part 1 (bind). After the reserve, set the member's `raw_deadline` to `pg_catalog.clock_timestamp()+interval '20 seconds'` in replica mode, so `expires_at` becomes `raw_deadline` under either body. Then `SAVEPOINT imp007o;`, bind (`NEW`), bind again (`NEWAGAIN`), `ROLLBACK TO SAVEPOINT imp007o;`, install the pre-change body, bind (`OLD`), bind again (`OLDAGAIN`). The `SELECT` lines are printed before each rollback, so `run_labelled` keeps them. | First assert the stripped text's SHA-256 equals `PRE_IMP_007O_RESERVE_SHA256`. Both binds `ok`. The `OLD` value's key set is `BIND_KEYS`. `NEW` without `context_unpadded_base64` equals `OLD` exactly, `expires_at` and `raw_deadline` included. `NEWAGAIN` and `OLDAGAIN` both equal `{'ok': False, 'code': 'import_conflict'}`. |
| 02 | Same test, part 2 (reserve and refusals), in a second script. `SAVEPOINT imp007o;`, install the pre-change body, then reserve (`OLDRESERVE`), a second reserve (`OLDBUSY`), a bind with `fence="'2'"` (`OLDFENCE`) and a bind with `raw_sha256="'XYZ'"` (`OLDBAD`). `ROLLBACK TO SAVEPOINT imp007o;`, then the same four calls under the new body (`NEWRESERVE`, `NEWBUSY`, `NEWFENCE`, `NEWBAD`). | Both reserve values have exactly `RESERVE_KEYS`, with equal `action` (`'reserve'`), `set_id`, `member_id` and `fence` (`'1'`). `lease_id` is a fresh random UUID under each body, and the two Instants are Instants with `fractional_digits` 6. The refusals are `import_busy`, `import_stale` and `import_invalid`, the same dict under both bodies. |
| 02 | Existing `test_reserve_then_bind_opens_one_bounded_attempt_and_hands_off_metadata`: add `self.assertEqual(BIND_KEYS \| {'context_unpadded_base64'}, set(handoff))`. Change no other assertion. | Passes. The other two existing reserve tests pass with no change. |

Gated, in `IngestionRuntimeInventoryPostgresTests` (a real `migrate_ingestion` on a disposable target), one new test `test_imp_007o_installed_bind_body_with_unchanged_digests`:

| AC | Case | Expected |
|---|---|---|
| 03 | `self._assert_clean()` first; then, as the operator, read `prosrc` of `wl_ingestion.reserve_member_v1` from `pg_proc` | The runtime and operator checks both pass with 68 functions, so the live catalog matches the unchanged `EXPECTED_STRUCTURE_SHA256`. The installed body contains `'context_unpadded_base64'` once. |
| 03, rollback | In `try`/`finally`, commit the pre-change body as the operator with `conn.exec_driver_sql(ddl, execution_options={'no_parameters': True})`, as `0004_ingestion.py` does (the DDL contains `%ROWTYPE`, so a parameter-parsing call would break). Then run `self._check()` and the operator's `verify_inventory`. In `finally`, reinstall `schema.RESERVE_DDL` the same way, then call `self._assert_clean()`. | Both checks raise `PersistenceError('migration_target_invalid')`: an install that still has the old body fails closed. After the reinstall the target is clean again. `CREATE OR REPLACE` keeps the owner and grants. |

Do not raise any assertion's tolerance and do not weaken an existing test to make these pass.

### Docs (AC-07)

In `docs/web-v2-imports.md`, in the `reserve_member_v1` paragraph:

- Replace "It extends the offer by up to 60 seconds within the raw deadline and returns handoff metadata only; the trusted API adds its own plaintext token." with: "It extends the offer by up to 60 seconds within the raw deadline. It returns the handoff metadata and, under `context_unpadded_base64`, the member's stored context bytes as unpadded standard base64 without line breaks. Both are for the trusted API only and never belong in a public response. The planned upload route (IMP-007U) adds its own plaintext token, decodes the context for the worker frame and removes that key before it validates `Handoff`."
- In the sentence that starts "Opt-in PostgreSQL tests cover replay", replace "missing or ambiguous workers and re-upload fencing" with "missing or ambiguous workers, re-upload fencing and the returned context bytes at 1 byte and 1 MiB".
- Keep "No upload route, worker claim or raw transport calls them yet." It is still true.

### AC-06 evidence

Put it in the PR under "Behavior & Compatibility" and in one ticket Log line:

- The owner's answer to Decisions needed item 2 ("No, none has", 2026-11-22), quoted from the ticket Log on `main`.
- `git tag --list` prints nothing, and `gh release list --repo gh-slee/kurafolio` lists nothing.
- `src/kurafolio/persistence/context.py` on the build base still maps no runtime profile to `0004_ingestion`.
- `docs/web-v2-imports.md` still says that there is no operational `0004` profile.

If you learn of a `0004` database or backup outside disposable tests despite that answer, stop and ask; the ticket would go back to the planner and the owner for a new revision.

### Verify

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_postgres_migration.IngestionStorageDDLTests`
- `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python scripts/run_gated_tests.py --expect-skipped 0 -- discover -s tests -p 'test_postgres_migration.py'`. It needs Docker, the pinned image in `IngestionAppendOnlyPostgresTests.IMAGE` pulled beforehand (the test uses `--pull never`), and `scripts/postgres.py test-identity-environment` for the runtime-inventory class. If your sandbox blocks Docker or local ports, run it in the owner's terminal or rely on the `postgres-ingestion` CI job, and say which. A skipped test is not acceptance.
- Without the variable: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration` reports 131 skips with an "Opt-in isolated ingestion" reason (124 fragment, 1 provider, 6 runtime inventory), which matches the new `postgres-foundation` count of 132 together with the one runtime-image test.
- The baseline hash command again. `RESERVE_DDL` and `function_ddl()` now differ, and both match their baseline values once `IMP_007O_ADDED` is removed once. `tables_ddl()`, `triggers_ddl()` and `inherited_guard_replacements()` are unchanged.
- `git diff --exit-code origin/main -- src/kurafolio/persistence/ingestion_migration.py src/kurafolio/persistence/ingestion_restore.py src/kurafolio/persistence/migrations/ src/kurafolio/persistence/schema.py src/kurafolio/persistence/identity_schema.py src/kurafolio/persistence/source_schema.py src/kurafolio/ingestion/contracts.py docs/specs/imp-007-r7/ tests/fixtures/ingestion/oracle.json` exits 0. That shows the `0001` to `0004` provider files, both structure digests, the inventories, the DTOs and the oracle are unchanged (AC-03, AC-04).
- The full suite (`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`), `scripts/check_language.py`, `scripts/check_publication.py --worktree` and `--staged`, and `python scripts/check_pr_image.py` from a clean tree.

### Rollback

Revert the commit. There is no data migration and no table, column, index, grant or inventory change. Rows written under either body are valid under the other. A database installed from one body fails `verify_functions` against the other source with `migration_target_invalid`, and so does a `restore-ingestion` of a backup taken under the other body. That is safe only because no `0004` database or backup exists outside disposable tests (Decisions needed item 2). Recreate synthetic test databases with `python scripts/postgres.py test-environment` rather than editing them.

### Negative cases the review should check

- The value has no line break and no padding at any size; the 1 MiB case and the created context (over 57 bytes) both prove it.
- The alphabet is standard, not URL-safe (the 4-byte `It+/Ig` case).
- The new key appears only in the successful bind result: reserve results and every refusal are byte-for-byte the pre-change dicts.
- `Handoff` validation refuses the bind value while the key is still in it, so a caller that forgets to remove it fails closed.
- No raw byte, plaintext token or token digest is in the result, and no `RAISE NOTICE` or log path exists.
- An install or backup with the old body is refused, never accepted as current.

### Do not touch

- `ingestion_migration.py`, `ingestion_restore.py`, every file under `src/kurafolio/persistence/migrations/`, `schema.py`, `identity_schema.py`, `source_schema.py`, `src/kurafolio/ingestion/` and `src/kurafolio/web_v2/`.
- `tests/fixtures/ingestion/oracle.json` and everything under `docs/specs/imp-007-r7/`.
- Every other DDL constant and function of `ingestion_schema.py`, `REVISION`, `PREDECESSOR`, `_FUNCTIONS` and `READ_TABLES`.
- `tickets/ROADMAP.md` and other tickets.

### Stop and ask if

- `spec_approved` on `main` does not match the amended text, or you find evidence of a `0004` database or backup outside disposable tests, contrary to the owner's answer to Decisions needed item 2.
- After the change, the live `_structure_digest` differs from `EXPECTED_STRUCTURE_SHA256` or the restored digest differs from `EXPECTED_RESTORED_STRUCTURE_SHA256`, or any inventory, oracle, DTO or r7 file would have to change.
- The expression gives anything other than the expected strings on PostgreSQL 18 (another whitespace character, for example). Do not swap in a different encoding.
- `pack_input(..., schema='Handoff')` refuses the bind value after the new key is removed. That would be an existing mismatch between the unchanged keys and `Handoff`, and AC-02 forbids changing them; report it for IMP-007U.
- Making a test pass seems to need a new refusal, a changed key or a weakened existing assertion.
- `reserve_member_v1` or `function_ddl()` changed on `main` after `96eadc2` in a way that touches the bind `RETURN`.
- The opt-in PostgreSQL suite cannot run anywhere you can reach. Report it and do not open the PR as passing.

## Plan

- [x] Owner chooses how to reconcile the digest wording (Decisions needed item 1: option B, amend the spec).
- [x] Owner gives Gate A on the amended text (2026-11-22, sha256:53f3126f8a92fbaaf5bb874cdfaf90d5107dd1305a6f7efc5ef76b41f9faef06).
- [x] Owner answers Decisions needed item 2 (2026-11-22: "No, none has"; proceed in place).
- [x] Claim after `cleanup`; record the baseline hashes and the passing baseline run of the three reserve tests.
- [x] Insert the key into the bind `RETURN`; add the constants and the static test.
- [x] Add the four gated tests and the extra assertion; raise the `postgres-foundation` skip count to 132.
- [x] Update `docs/web-v2-imports.md`; record the AC-06 evidence; run the gated and full suites; start the independent review; open the PR.

## Decisions needed

- Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes. **Resolved 2026-11-21.** Asked "Gate A, tickets whose text is unchanged since filing (full text on PR #95's branch). Which do you approve exactly as written?" with this ticket listed at sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60, the owner selected "IMP-007O,IMP-007P,IMP-007U,IMP-007S" (Q31). `gate_approval` and `spec_approved` record it.
1. **The approved text said the structure digests and the oracle vectors change; on `main` they cannot.** **Resolved 2026-11-22: option B, amend the spec; Gate A given on the amended text.**
   - The approved Requirements bullet said the `0004` function text, `EXPECTED_STRUCTURE_SHA256`, `EXPECTED_RESTORED_STRUCTURE_SHA256` and the oracle vectors "change with it", and AC-03 said "only the function text and the two expected structure digests change". `_structure_digest` does not read `pg_proc`, and no oracle vector holds a `reserve_member_v1` result (Context), so a body change leaves both digests and `oracle.json` as they are.
   - Options offered: (A) keep the gated text and confirm in the Log that the digests stay unchanged, with no new Gate A; (B) amend the Requirements bullet and AC-03 and give a new Gate A. Recommended: (B).
   - The owner chose "Option B: amend spec" (relayed to this planning session by the coordinating session). The Requirements bullet and AC-03 now carry the proposed wording, and `tickets.py spec` reports sha256:53f3126f8a92fbaaf5bb874cdfaf90d5107dd1305a6f7efc5ef76b41f9faef06.
   - Gate A on the amended text: asked "Do you give Gate A on IMP-007O hash sha256:53f3126f…faef06?" after being shown the amended Requirements bullet, the amended AC-03 and the hash, the owner replied "Approve Gate A" (relayed to this planning session by the coordinating session). `gate_approval` and `spec_approved` record it.
2. **Has any database outside disposable tests run `operator migrate-ingestion` at `0004`, or has any such database been backed up with `backup-ingestion`?** **Resolved 2026-11-22: (a) No; the in-place change goes ahead.** Asked "Has any database outside disposable tests run `operator migrate-ingestion` at `0004`, or been backed up with `backup-ingestion`: no, or yes/unsure?", the owner replied "No, none has" (relayed to this planning session by the coordinating session). The Requirements make this a stop point, and only the owner can answer it. Repository evidence (Context) shows no supported path to an operational `0004`, but it cannot prove that no operator ran the command.
   - (a) No. The in-place change goes ahead as planned. Recommended, if it is true.
   - (b) Yes, or unsure. Do not build. The function needs a new revision that replaces it on installed targets, which changes this ticket's Requirements and the revision numbers that APP-011I (`0005`) and APP-011E (`0006`) plan to use. The ticket goes back to the planner and the owner.

## Handoff

- State: Reviewed implementation and PR metadata are published at 6d4a05e in PR https://github.com/gh-slee/kurafolio/pull/103. CI https://github.com/gh-slee/kurafolio/actions/runs/45056241914 passed all nine jobs, including 154 ingestion PostgreSQL tests with 0 skips. The fresh-context review https://github.com/gh-slee/kurafolio/pull/103#issuecomment-7089598969 reports PASS for all seven ACs with no blocking findings. QA and Architecture were assessed in one session, not two independent sessions. This follow-up corrects only the ticket and PR status prose; source, gated text and Build plan stay unchanged.
- Next step: Publish this review-metadata correction after the applicable approval. Resolve whether a separate second Architecture reviewer is required, then proceed to the owner's final review. Return any new findings through this claim; do not merge automatically.
- Verify: `python3 scripts/tickets.py spec IMP-007O --base origin/main`; `python3 scripts/tickets.py check`; `python3 scripts/tickets.py pr-check --branch ticket/imp-007o-return-the-stored-member-context-bytes-f`; `python3 scripts/check_pr_image.py`. The reviewed source passed the full Python suite (1,433 tests, 261 opt-in skips); focused metadata checks and an exact-HEAD candidate receipt are retained under ignored `work/imp-007o/` and `work/pr-images/` before publication.
- Findings disposition: The two low findings (stale PR CI/review text and stale Handoff) are corrected in this ticket and the prepared complete PR body. The exception-reason assertion nit is accepted unchanged, as the reviewer allowed. The recommended 1 MiB end-to-end framing check belongs to IMP-007U planning; no code or other ticket is changed here.
- Gotchas: The review's local runtime-inventory setup stopped at a sandbox network limit; CI covers that class successfully. The reviewer did not rerun the full Python suite, publication guard or candidate image check and relied on builder/CI evidence for those. An installed old function body or its ingestion backup still fails current-source verification despite unchanged structure digests.
- Open questions: The review combined QA and Architecture in one session. The owner's decision about a separate second Architecture reviewer remains outstanding; no second session is claimed. The owner's final review and merge remain pending.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #87 from the owner's decision of 2026-11-20 on IMP-007E's question "Where should the bytes come from?": the owner chose "New SQL ticket (Recommended)": "a frontier SQL ticket makes the bind result also return the stored context bytes; keeps the frozen r7 frame." Status backlog; no Gate A yet.
- 2026-11-21 claude-code/opus-5.5: checked against `main` at `1a6ff31` in plan pull request #95. Only the Context's lock line was stale: IMP-007N is `done`, and IMP-007T and IMP-007W also hold `ingestion-schema-sql`. Gated sections unchanged (sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60); still backlog, no Gate A.
- 2026-11-21 claude-code/opus-5.5: recorded Gate A in plan pull request #95. Asked "Gate A, tickets whose text is unchanged since filing (full text on PR #95's branch). Which do you approve exactly as written?" (Q31) with this ticket listed at sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60, the owner selected "IMP-007O,IMP-007P,IMP-007U,IMP-007S". `gate_approval` set to "owner 2026-11-21, Gate A on the text as written on PR #95's branch (Q31)"; `spec_approved` set to sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60, which `tickets.py spec` reports as the current hash; status backlog becomes ready. Decisions needed item resolved. No Build plan yet; the planner writes it in a later pull request.
- 2026-11-22 claude-code/opus-5.5: wrote the frontier Build plan from `main` at `96eadc2` in plan pull request https://github.com/gh-slee/kurafolio/pull/101. Corrected the Context: `_structure_digest` and `oracle.json` do not cover function bodies, so the structure digests cannot change. Added Decisions needed items 1 (reconcile the approved text that says the digests and oracle change, with proposed wording for a new Gate A) and 2 (the owner's `0004` install and backup confirmation). Both block the build, not this plan. Goal, Requirements and Acceptance criteria unchanged (sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60).
- 2026-11-22 claude-code/opus-5.5: on Decisions needed item 1 the owner chose "Option B: amend spec", relayed to this planning session by the coordinating session. Replaced the Requirements bullet on the in-place `0004` change and AC-IMP-007O-03 with the wording proposed in item 1: the structure digests and `oracle.json` stay unchanged. New spec hash sha256:53f3126f8a92fbaaf5bb874cdfaf90d5107dd1305a6f7efc5ef76b41f9faef06. No Gate A on the amended text yet; `spec_approved` keeps sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60, so the ticket cannot be claimed until the owner approves the new hash. Item 2 stays open. Build plan checked against the amended text: unchanged apart from the claim preconditions. Plan pull request https://github.com/gh-slee/kurafolio/pull/101.
- 2026-11-22 claude-code/opus-5.5: recorded Gate A on the amended text in plan pull request https://github.com/gh-slee/kurafolio/pull/101. Shown the amended Requirements bullet, the amended AC-IMP-007O-03 and the hash, and asked "Do you give Gate A on IMP-007O hash sha256:53f3126f…faef06?", the owner replied "Approve Gate A" (relayed to this planning session by the coordinating session). Before recording, `tickets.py spec` reported the current hash as sha256:53f3126f8a92fbaaf5bb874cdfaf90d5107dd1305a6f7efc5ef76b41f9faef06. `gate_approval` changed from "owner 2026-11-21, Gate A on the text as written on PR #95's branch (Q31)" to "owner 2026-11-22, Gate A on the amended text (hash 53f3126f…): Approve Gate A"; `spec_approved` changed from sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60 to sha256:53f3126f8a92fbaaf5bb874cdfaf90d5107dd1305a6f7efc5ef76b41f9faef06. Status stays ready. Decisions needed item 2 is still open and blocks the build.
- 2026-11-22 claude-code/opus-5.5: recorded the owner's answer to Decisions needed item 2 in plan pull request https://github.com/gh-slee/kurafolio/pull/101. Asked "Has any database outside disposable tests run `operator migrate-ingestion` at `0004`, or been backed up with `backup-ingestion`: no, or yes/unsure?", the owner replied "No, none has" (relayed to this planning session by the coordinating session). That is option (a): the change is made in place at `0004_ingestion`, and this line is the owner's part of the AC-IMP-007O-06 evidence. Updated the Build plan's claim steps and stop points so a builder is no longer held on item 2. Gated sections unchanged; `tickets.py spec` reports MATCHES at sha256:53f3126f8a92fbaaf5bb874cdfaf90d5107dd1305a6f7efc5ef76b41f9faef06.
- 2026-11-22 codex/gpt-6.1-sol: claimed from origin/main 9a10704 after cleanup and matching amended spec; no persistence changes since the plan base 96eadc2. Baseline hashes match the Build plan and the three pre-change reserve tests passed (3 tests, 0 skips, 4.916s) on disposable PostgreSQL. AC-IMP-007O-06: the owner answered "No, none has" on 2026-11-22 in the preceding planning Log line; `git tag --list` and `gh release list --repo gh-slee/kurafolio` are empty, the build-base Database profiles stop at 0003 and docs still state there is no operational 0004 profile.
- 2026-11-22 codex/gpt-6.1-sol: implemented only the planned SQL insertion/comment, four gated tests plus static and existing-bind assertions, CI skip count and trusted-API docs. PostgreSQL acceptance PASS: 154 tests, 0 skips/failures/errors in 97.968s, including size/alphabet vectors, exact old-body result comparison, closed Handoff framing and installed-body rejection/recovery. Static suite PASS 18 tests; non-opt-in suite PASS 154 tests with 131 expected skips. Hash and protected-path checks, language and worktree/staged/reachable-history privacy guards PASS. Full Python suite remains running; candidate image, CI and independent reviews remain outstanding. No push or PR.
- 2026-11-22 codex/gpt-6.1-sol: full Python suite PASS (1,433 tests in 757.560s, 261 opt-in skips); this was the single full run required by the Build plan. The separate real PostgreSQL suite passed with 0 skips. Prepared the canonical PR body locally with independent QA/Architecture and CI marked NOT RUN; the exact-HEAD source-only image check follows this clean checkpoint. Publication and the final PR/status outcome commit remain outstanding.
- 2026-11-22 codex/gpt-6.1-sol: published the three implementation/checkpoint commits and opened PR https://github.com/gh-slee/kurafolio/pull/103 using the validated canonical body, with QA/Architecture marked NOT RUN. CI run https://github.com/gh-slee/kurafolio/actions/runs/45052664580 was queued at the last check. Recorded the PR and set implementation status done; this metadata checkpoint awaits its own publication approval.
- 2026-11-22 codex/gpt-6.1-sol: outcome: implementing model codex/gpt-6.1-sol; reviewing model claude-code/opus-5.5 (NOT RUN, unavailable in Codex); review repair rounds 0; spec or Build plan omissions: nothing missing. Developer checks pass; independent QA and Architecture review remain outstanding, so the frontier ticket is not ready for the owner's final review.
- 2026-11-22 codex/gpt-6.1-sol: verified CI run https://github.com/gh-slee/kurafolio/actions/runs/45056241914 passed all nine jobs on 6d4a05e and read the complete review https://github.com/gh-slee/kurafolio/pull/103#issuecomment-7089598969. The combined QA/Architecture session reports all seven ACs PASS and no blockers. Corrected the two low stale-metadata findings in the Handoff and prepared PR body; accepted the exception-reason nit unchanged. Recorded the IMP-007U framing recommendation without changing that ticket or code. A separate second Architecture session has not run; the owner decides that remaining review question.
- 2026-11-22 codex/gpt-6.1-sol: outcome: implementing model codex/gpt-6.1-sol; reviewing model claude-code/opus-5.5 (combined QA/Architecture session PASS at 6d4a05e); review repair rounds 1 (documentation only); spec or Build plan omissions: nothing missing. All review findings are answered; the separate-second-review decision and owner final review remain outstanding.
