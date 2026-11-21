---
id: IMP-007W
title: Add a runtime-role readiness check of the 0004 ingestion inventory
priority: P0
status: ready
type: feature
parent: IMP-007
depends_on: [IMP-007D]
resources: [ingestion-schema-sql]
risk: high
size: S
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-21, IMP-007W spec as written (hash 69f601c8…)"
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:69f601c821550d5e487bb972ab128e3a8e71d1bce1ed8110081dba13426f7094
updated: 2026-11-21
---

# IMP-007W: Add a runtime-role readiness check of the 0004 ingestion inventory

## Goal

An API instance on the `ingestion` profile must check the installed `0004_ingestion` inventory before it reports ready, as r7 requires. The only check that exists, `ingestion_migration.verify_inventory`, needs database CREATE, which the approved `0004` grants take away from every application role, so the API cannot run it. Add a read-only check that the runtime role can run with the rights it already has, and that refuses every catalog difference the operator check refuses, without giving any application role more privileges and without weakening the operator check.

## Context

- Filed on 2026-11-21 from IMP-007E, Decisions needed item 7. The owner chose "New prerequisite ticket": option (a), "add a prerequisite ticket providing an approved runtime-safe inventory check, then update this Build plan to use it". IMP-007E depends on this ticket.
- What the IMP-007E builder found on 2026-11-21, on one isolated synthetic PostgreSQL 18 target migrated to `0004_ingestion` from `main` at `cd68c5e`:
  - The operator call to `verify_inventory` passed with 68 functions.
  - The same call through the runtime role's login raised `migration_role_required`.
  - Through the gateway role's login it failed earlier, with a driver privilege error on `wl_pg.alembic_version`.
  - No code was changed. The local evidence is at `work/imp-007e/` in that builder's worktree. It is not part of this spec.
- Why, from the code on `main` at `cd68c5e`:
  - `verify_inventory` (`src/kurafolio/persistence/ingestion_migration.py:394`) reads `wl_pg.alembic_version`, then calls `migration._operator`, which raises `migration_role_required` unless `current_user` has CREATE on the database. It uses `current_user` as the owner of the four schemas.
  - `verify_grants` (`:314`) calls `_checked_roles` (`:68`), which calls `_operator` again.
  - `grants()` (`:94`) revokes CREATE and TEMPORARY on the database and CREATE on `public` from the runtime, gateway and worker roles, and gives the gateway no right on `wl_pg`. The runtime role gets USAGE on `wl_pg`, `wl_sources` and `wl_ingestion`, SELECT on every `wl_pg` and `wl_sources` table and SELECT on the `READ_TABLES` of `wl_ingestion`.
- The `sources` profile already avoids this. `source_migration.verify_inventory` (`src/kurafolio/persistence/source_migration.py:111`) runs on the runtime connection in `Auth.ready()` (`web_v2/auth.py:97-103`). It never calls `_operator`, and it takes the owner from `pg_namespace.nspowner` of `wl_pg`. This ticket applies the same idea to `0004`.
- A second finding, from reading `identity.role_inventory` (`src/kurafolio/persistence/identity.py:172`). With `gateway=False` it requires the runtime role to have INSERT on most `wl_pg` columns and UPDATE on a few (`:222-244`). At `0004` the runtime role has SELECT only on `wl_pg`; `docs/web-v2-imports.md` calls these the profile's "read-only financial grants". So IMP-007E's planned `role_inventory(self.financial, gateway=False)` would also refuse a correct `0004` target. The gateway branch (`gateway=True`) reads only `pg_catalog` and `has_*_privilege` results and should pass. No real-PostgreSQL run has confirmed either result; AC-07 does.
- Other callers of the operator check stay as they are: `migrate_ingestion` (`:479`), `ingestion_restore.backup_ingestion` (`ingestion_restore.py:307`) and `restore_ingestion` (`:692`, `:710`, `:734`, with `quarantined=True`), and IMP-007S's planned activation command. They run as the operator.
- APP-011I (revision `0005`) and APP-011E (revision `0006`) each add a `verify_inventory` of their own on the same pattern. Their plans are updated in the same plan pull request to add runtime counterparts built on this ticket's helper.
- The resource is `ingestion-schema-sql`, because this ticket edits `ingestion_migration.py`, which IMP-007O also edits (it changes the expected structure digests). The lock is free: IMP-007N is `done`, and IMP-007O, IMP-007Q and IMP-007R are `backlog` without Gate A. If IMP-007O merges first, this ticket keeps using the constants as `main` then has them.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file). [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), "Profile integration and readiness", says that before readiness the code inspects the new exact inventory and all inherited definitions and grants, with expected values frozen in code and never generated from the live target.
- Add one public function, `ingestion_migration.verify_runtime_inventory(conn, *, runtime_role, gateway_role, worker_role)`. It runs on a connection logged in as the runtime role and only reads.
- Before it reads any table in `wl_pg`, `wl_identity`, `wl_sources` or `wl_ingestion`, it checks that:
  - the server is PostgreSQL 18, as `_operator` checks;
  - `current_user` is `runtime_role`;
  - the four schemas have exactly one owner;
  - that owner, `runtime_role`, `gateway_role` and `worker_role` are four different roles.
  A wrong caller or role set gets `migration_role_required`. The four-schema check gets `migration_target_invalid`.
- After that it makes every check that `verify_inventory` makes for an unrestored target, with the same frozen constants: the revision, the schema set and its owner, the identity inventory, the source and `0004` structure digests, the function definitions, the exact grants and role safety of all three roles, and no CREATE or TEMPORARY for any of them. The only difference is that the owner comes from the catalog, not from `current_user`.
- It has no restored or quarantined mode, and a caller cannot pass the owner in.
- It raises only `PersistenceError` with a code from `errors.CODES`. A database error during the check becomes `migration_target_invalid`. No SQL text, role name, catalog value or driver message goes into an exception or a log line.
- The operator check keeps its behaviour. `verify_inventory`, `grants`, `migrate_ingestion` and the backup and restore functions give the same results and errors as before, and `verify_inventory` still requires CREATE. Shared helpers may take a keyword-only owner, whose default keeps calling `_operator`.
- No change to SQL text, the `0001` to `0004` providers and migration files, `grants()`, `EXPECTED_PREDECESSOR_SHA256`, `EXPECTED_STRUCTURE_SHA256`, `EXPECTED_RESTORED_STRUCTURE_SHA256` or the oracle vectors. No role gets a new grant, membership, CREATE or TEMPORARY. No `SET ROLE`, and the API needs no operator credentials.
- Non-goals: wiring the check into `Auth.ready()` and the `ingestion` profile (IMP-007E); activation, the wrapper catalog and the `ready` flag (IMP-007S); a worker or launcher readiness check; the `0005` and `0006` counterparts (APP-011I, APP-011E); serving a restored target.
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.

## Acceptance criteria

- [ ] AC-IMP-007W-01: On a synthetic target migrated to `0004_ingestion`, `verify_runtime_inventory` through the runtime role's own login returns `{"schema_revision": "0004_ingestion", "functions": 68}`, equal to what the operator's `verify_inventory` returns on the same target.
- [ ] AC-IMP-007W-02: Running the check changes no privilege: on the same target, the effective rights of the three roles and the full ACL rows of the four schemas are identical before and after, and no role has database CREATE or TEMPORARY or CREATE on any schema.
- [ ] AC-IMP-007W-03: The operator check is not weakened: through the runtime role's login, `verify_inventory` still raises `migration_role_required`, and the existing ingestion tests in `tests/test_postgres_migration.py` pass without changes to their assertions.
- [ ] AC-IMP-007W-04: Through the runtime login the check refuses each drift and passes again after it is reverted: EXECUTE on a `wl_ingestion` function granted to PUBLIC, `RESET search_path` on one `wl_ingestion` function, SELECT on `wl_pg.alembic_version` granted to the gateway role, and CREATE on schema `public` granted to the runtime role, each `migration_target_invalid`; the runtime role made a member of another role, `migration_role_required`; an `alembic_version` other than `0004_ingestion`, `schema_unsupported`.
- [ ] AC-IMP-007W-05: Through the gateway role's login or the operator's login, and through the runtime login with `runtime_role` naming another role, the check raises `migration_role_required` before it reads any application table. The exception text is the code only, and no driver exception escapes.
- [ ] AC-IMP-007W-06 [review]: The function has no quarantined or restored mode and no owner parameter, and all its expected values come from code constants.
- [ ] AC-IMP-007W-07: On the same `0004` target, `role_inventory` with `gateway=True` through the gateway login passes, and with `gateway=False` through the runtime login raises `IdentityError`, both on the `sources` branch that IMP-007E extends to `ingestion`.
- [ ] AC-IMP-007W-08: `docs/web-v2-imports.md` says that an API's readiness check of a `0004` target runs through the runtime role with its existing rights, and that `verify_inventory` stays an operator check.

## Build plan

- Based on: `main` at `cd68c5e`.
- One pull request. Order: step 0 (probe), then the code, then the tests, then the docs and CI.

### Step 0: probe catalog visibility first

Before any code change, on one isolated target migrated to `0004` as in Tests below, run through the runtime login and through the operator login:

- `source_migration.structure_digest(conn)`
- `ingestion_migration._structure_digest(conn, runtime_role)`
- `ingestion_migration.verify_functions(conn)`
- `migration._identity_target_inventory(conn, "0002_identity")`
- the `rights` query of `verify_grants` (`ingestion_migration.py:345-373`) with the owner name passed as `:owner`
- the role-safety query of `_checked_roles` (`:78-87`) for each role, including its `pg_shdepend` subquery

Each must give the same value through both logins. If one differs or raises, stop and ask. Do not add a grant to make them agree. Record the comparison in the pull request.

### Files

- `src/kurafolio/persistence/ingestion_migration.py`:
  - `_checked_roles(conn, roles, *, owner=None)`: `owner = _operator(conn) if owner is None else owner`. The rest stays the same.
  - `verify_grants(conn, runtime_role, gateway_role, worker_role, *, quarantined=False, owner=None)` passes `owner` to `_checked_roles`.
  - Move the body of `verify_inventory` after its `_operator` call into a private `_verify_installed(conn, owner, *, runtime_role, gateway_role, worker_role, quarantined)`. It covers the namespace check through `verify_grants(..., quarantined=quarantined, owner=owner)` and returns the result dict. `verify_inventory` keeps its signature and order: the revision read, then `owner = _operator(conn)`, then `_verify_installed(...)`.
  - New private `_runtime_owner(conn, *, runtime_role, gateway_role, worker_role)`:
    1. `_role(name)` for each of the three names (`invalid_config` on a bad name).
    2. `server_version_num` in `[180000, 190000)`, else `schema_unsupported`.
    3. `SELECT current_user` equals `runtime_role`, else `migration_role_required`.
    4. `SELECT nspname, pg_catalog.pg_get_userbyid(nspowner) FROM pg_catalog.pg_namespace WHERE nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion')` returns four rows with one owner, else `migration_target_invalid`.
    5. `len({owner, runtime_role, gateway_role, worker_role}) == 4`, else `migration_role_required`.
    6. Return the owner.
    It reads only `pg_catalog` and `current_user`.
  - New public `verify_runtime_inventory(conn, *, runtime_role, gateway_role, worker_role)`:
    - Inside `try`: `owner = _runtime_owner(...)`; the same revision check as `verify_inventory` (`schema_unsupported`); `return _verify_installed(conn, owner, ..., quarantined=False)`.
    - `except SQLAlchemyError: raise PersistenceError("migration_target_invalid") from None`. Import `SQLAlchemyError` inside the function, as `migrate_ingestion` does.
    - Docstring: read-only; runtime login only; the operator uses `verify_inventory`.
  - Do not change `grants`, `verify_functions`, `_structure_digest`, `verify_role_create_privileges`, `migrate_ingestion` or the three digest constants.
- `tests/test_postgres_migration.py`: two new classes, below: one real-PostgreSQL class and one unit class with no database.
- `docs/web-v2-imports.md`, section "Explicit 0004 installation": one short paragraph for AC-08. Say that IMP-007E wires the check into `/readyz`.
- `.github/workflows/ci.yml`: the `postgres-foundation` job discovers `test_postgres_*.py` and skips the ingestion tests (`--expect-skipped 123`, comment "the 122 ingestion tests"). Raise both numbers by the number of new test methods gated on `KURAFOLIO_INGESTION_TEST`. The unit class is not gated on that variable and runs there, because that job installs `requirements-pg-test.lock`, so it adds no skip. The `postgres-ingestion` job already runs `test_postgres_migration.py` with `--expect-skipped 0`; it runs both new classes.

### Tests

Real PostgreSQL: a new class `IngestionRuntimeInventoryPostgresTests` in `tests/test_postgres_migration.py`, gated on `KURAFOLIO_INGESTION_TEST=1` like `IngestionProviderPostgresTests`.

- `setUpClass` builds one environment with `scripts/postgres.py test-identity-environment` (cleanup in `tearDownClass` with `cleanup-test-environment`).
- It creates the worker role with `CREATE ROLE ... LOGIN` through the bootstrap admin, as `test_install_upgrade_grants_and_transactional_refusal` does.
- It migrates the fixture's own database, so that `runtime.conninfo` and `identity.conninfo` reach it:
  1. `migrate_sources`.
  2. Close identity setup with the synthetic tenant, portfolio and user, as `_verify_targets` does (`tests/test_postgres_migration.py:347-362`).
  3. `migrate_ingestion`.

  This is the order `_verify_targets` uses.
- It opens three `Database` objects with `schema_mode='sources'`, as `_verify_targets` does on its `0004` targets: operator (`migration.conninfo`), runtime (`runtime.conninfo`) and gateway (`identity.conninfo`). There is no `ingestion` mode until IMP-007E. Only their engines are used.
- Drift cases commit through the operator, check through the runtime login, then revert and commit in `finally`. The savepoint pattern at `:405-413` does not work here, because the check runs on another connection. The role-membership case needs the bootstrap admin, because the operator has no CREATEROLE. Each case ends by asserting that the clean target passes again.

Unit tests without a database go in a second new class, `IngestionRuntimeInventoryUnitTests`, in the same file and not gated on `KURAFOLIO_INGESTION_TEST`. A fake connection records each SQL text and answers from a script. Skip the class when SQLAlchemy is not installed (`importlib.util.find_spec('sqlalchemy')`, as `tests/test_postgres_config.py:15` does), because `context.execute` and the `SQLAlchemyError` case need it. The default unit job installs no SQLAlchemy and skips it; `postgres-foundation` and `postgres-ingestion` run it.

Every test names its AC ID.

| AC | Case | Expected |
|---|---|---|
| 01 | Operator `verify_inventory`; runtime `verify_runtime_inventory` on the same target | Both `{"schema_revision": "0004_ingestion", "functions": 68}` |
| 02 | Before and after AC-01's runtime call: the `aclexplode` rows over the four schemas, their tables, columns and functions; `has_database_privilege(r, current_database(), 'CREATE,TEMPORARY')` and `has_schema_privilege(r, n.oid, 'CREATE')` for each role and schema | Rows identical; every privilege `false` |
| 03 | `verify_inventory` through the runtime login | `PersistenceError('migration_role_required')` |
| 03 | The existing classes in `tests/test_postgres_migration.py` | Pass; no existing assertion changed |
| 04 | `GRANT EXECUTE ON FUNCTION wl_ingestion._validate_minimal_v1(bytea) TO PUBLIC` | `migration_target_invalid` |
| 04 | `ALTER FUNCTION wl_ingestion.read_plan_basis_v1(uuid,text,jsonb,bytea) RESET search_path` | `migration_target_invalid` |
| 04 | `GRANT SELECT ON wl_pg.alembic_version TO <gateway>` | `migration_target_invalid` |
| 04 | `GRANT CREATE ON SCHEMA public TO <runtime>` | `migration_target_invalid` |
| 04 | `GRANT <worker> TO <runtime>` | `migration_role_required` |
| 04 | `UPDATE wl_pg.alembic_version SET version_num='0003_source_lifecycle'` | `schema_unsupported` |
| 04 | After each revert | Passes, as AC-01 |
| 05 | Real PG: the check through the gateway login, through the operator login, and through the runtime login with `runtime_role=<gateway>` | `migration_role_required`; `str(error) == 'migration_role_required'` |
| 05 | Unit: `current_user` answers another role | `migration_role_required`; no recorded SQL names `wl_pg.`, `wl_identity.`, `wl_sources.` or `wl_ingestion.` |
| 05 | Unit: the fake raises `sqlalchemy.exc.ProgrammingError` on the revision read | `PersistenceError('migration_target_invalid')`, with no cause or context attached |
| 06 | Unit: `inspect.signature(verify_runtime_inventory)` | Exactly `conn` and the keyword-only `runtime_role`, `gateway_role` and `worker_role` |
| 07 | `role_inventory(SimpleNamespace(schema_mode='sources'), gateway=True, connection=<gateway conn>)` | Returns the gateway role's name |
| 07 | The same with `gateway=False` on the runtime connection | `IdentityError` |
| 08 | Unit: read `docs/web-v2-imports.md` | Names `verify_runtime_inventory` and says `verify_inventory` is an operator check |

Independent expected values, not taken from the code under test:

- 68 functions at `0004`: the `expected` value of `test_install_upgrade_grants_and_transactional_refusal`, and the IMP-007E builder's probe.
- The privileges in AC-02: `grants()` revokes CREATE and TEMPORARY from all three roles, and `docs/web-v2-imports.md` says the command "applies the profile's read-only financial grants".
- AC-07: `role_inventory` with `gateway=False` asserts INSERT on `wl_pg` columns (`identity.py:240-244`). `verify_grants` expects SELECT only for the runtime role on `wl_pg`.

Negative cases the reviewer will look for:

- A gateway connection never reaches a `wl_pg` read, so no `InsufficientPrivilege` reaches the caller.
- An operator connection cannot pass the runtime check by accident: the owner is the caller.
- No new `GRANT`, `ALTER DEFAULT PRIVILEGES` or `SET ROLE` text anywhere in the diff outside test drift cases.

### Rollback

- Revert the pull request. The change adds a function and keyword-only parameters whose defaults keep the old behaviour. It changes no SQL and no grant, so a revert leaves no database change behind.
- IMP-007E cannot report ready on `ingestion` without this function, which is the state on `main` today.

### Do not touch

- `src/kurafolio/persistence/ingestion_schema.py`, `ingestion_restore.py`, `migration.py`, `source_migration.py`, `identity.py`, `context.py` and the `0001` to `0004` providers and migration files.
- `grants()`, `migrate_ingestion`, the three digest constants, `tests/fixtures/ingestion/oracle.json`.
- `web_v2/` (IMP-007E wires the check), the worker and launcher, the activation command (IMP-007S).
- Other tickets' files and `tickets/ROADMAP.md`.

### Stop and ask if

- Step 0 gives a different value through the runtime login, or any of its queries raises there.
- A check seems to need a privilege the runtime role lacks, or a change to SQL, grants or a digest.
- An existing test assertion would have to change.
- AC-07 comes out the other way: `role_inventory(gateway=False)` passes through the runtime login, or `gateway=True` refuses through the gateway login. IMP-007E's plan depends on both results.
- The real-PostgreSQL tests cannot run in the isolated environment.

## Plan

- [x] Gate A: the owner approves Goal, Requirements and Acceptance criteria.
- [ ] Step 0: probe catalog visibility through the runtime login; stop on any difference.
- [ ] Owner keyword on `_checked_roles` and `verify_grants`; `_verify_installed`; `_runtime_owner`; `verify_runtime_inventory`.
- [ ] Real-PostgreSQL class and unit tests, one per AC; CI skip count.
- [ ] Docs; full suite, focused PostgreSQL run, language and publication checks; pull request with independent review.

## Decisions needed

1. **Gate A.** Resolved 2026-11-21: the owner chose "Approve" for the Goal, Requirements and Acceptance criteria above, hash sha256:69f601c821550d5e487bb972ab128e3a8e71d1bce1ed8110081dba13426f7094. Recorded in plan pull request #93; it takes effect when that pull request merges.

## Handoff

- State: Filed on 2026-11-21 in plan pull request #93, with a Build plan. The owner gave Gate A on 2026-11-21 (Decisions needed, item 1); status `ready` once #93 merges. Not started.
- Next step: After Gate A is on `main`, run step 0 of the Build plan before writing code.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`, in a virtual environment with `requirements-pg-test.lock`; environment setup in [postgres-foundation.md](../docs/postgres-foundation.md) and [web-v2-imports.md](../docs/web-v2-imports.md).
- Gotchas: The runtime login sees the catalog but not `wl_identity` tables; the gateway login cannot read `wl_pg`. Drift cases must commit, because the check runs on another connection.
- Open questions: none.

## Log

- 2026-11-21 claude-code/opus-5.5: filed from the owner's answer "New prerequisite ticket" to IMP-007E Decisions needed item 7, with a frontier Build plan from `main` at `cd68c5e`, in plan pull request https://github.com/gh-slee/kurafolio/pull/93. Spec hash at filing sha256:69f601c821550d5e487bb972ab128e3a8e71d1bce1ed8110081dba13426f7094, awaiting the owner's Gate A. Status backlog; no Gate A yet.
- 2026-11-21 claude-code/opus-5.5: recorded Gate A, as relayed from the owner's conversation by the coordinating session. The owner was asked "Approve IMP-007W's spec (hash 69f601c8…) for Gate A?", with the full hash sha256:69f601c821550d5e487bb972ab128e3a8e71d1bce1ed8110081dba13426f7094 stated, and answered "Approve". `spec_approved` records that hash, `gate_approval` adds "owner 2026-11-21, IMP-007W spec as written (hash 69f601c8…)", status changes from backlog to ready, and Decisions needed item 1 is resolved. The gated text is unchanged since filing, so the Build plan was written against the approved text.
