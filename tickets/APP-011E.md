---
id: APP-011E
title: Add user preferences to the V2 identity API
priority: P0
status: ready
type: feature
parent: APP-011
depends_on: [APP-011I, IMP-007E]
resources: [identity-contract, migration-order, postgres-schema]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-12, scope as written; locale, time zone and reporting currency stored on the server; session list deferred"
review: independent
branch:
pr:
spec:
spec_approved: sha256:3c4a7cd2b13f7fe8a817e6aaa23b8058c6a5a4a01f56df10dad50048674932b8
updated: 2026-11-21
---

# APP-011E: Add user preferences to the V2 identity API

## Goal

The V2 Profile page is specified to hold a user's language, time zone and default reporting currency, and the analysis pages need the currency and zone on every device the user signs in from. The identity API stores none of them, so the Profile page cannot be built. Add a small per-user preferences contract.

## Context

### Current behaviour

- `src/kurafolio/web_v2/schemas.py:109-112` `Me` returns `user` and `portfolio` only.
- `src/kurafolio/web_v2/api.py:27-34` lists every V2 route; none reads or writes preferences, and there is no session list or per-session revoke route. `GET /api/v2/me` is at `api.py:363`. Password change exists at `api.py:381` and ends other sessions per [web-v2-identity.md](../docs/web-v2-identity.md).
- The shipped app keeps interface language in memory (`frontend/src/main.tsx:97`) and hard-codes the zone (`frontend/src/lib/format.ts:52`).

### Found while planning, 2026-11-19 at `a2f5f2b`

- Where the table can go. Revisions form one linear chain: `0001_foundation`,
  `0002_identity`, `0003_source_lifecycle`, `0004_ingestion`
  (`persistence/migrations/versions/`). AUTH-101 (owner, 2026-11-12) reserved
  `0005_invite_status` for APP-011I and recorded "APP-011E gets its own later
  revision". No `0005` exists on `main`; plan PR #82 (APP-011I, unmerged) describes it.
- Which instances a revision after `0004` reaches. `Database` (`persistence/context.py:47`)
  maps the `identity` profile to `0002` and `sources` to `0003`; `Settings.schema_profile`
  (`web_v2/config.py`) accepts only those two. No runtime profile serves `0004` or
  later ([web-v2-imports.md](../docs/web-v2-imports.md): "There is no operational
  `0004` profile"). On 2026-11-20 the owner assigned that profile to IMP-007E (its
  Build plan Part A, plan pull request #87); APP-011I moves it to `0005` and this
  ticket to `0006`. A preferences revision reaches only instances on that profile.
- Every guarded function checks one exact revision literal (`identity_schema.GUARD`,
  `identity_schema.py:67-73`). Each new revision re-creates every function its
  predecessor leaves guarded, with its own literal (`source_schema.identity_replacements()`,
  `ingestion_migration.inherited_guard_replacements()`).
- Checks that pin today's `wl_identity` shape and that a new table there changes:
  - `identity.role_inventory` (`identity.py:202`, exactly 22 functions equal to
    `SIGNATURES`; `identity.py:219`, exactly 7 tables equal to `TABLES`).
  - `migration._identity_target_inventory` (`migration.py:149`): the relation set,
    the function set and two frozen hashes over every `wl_identity` constraint and
    column row (`known['0002_identity']`). The `0004` `verify_inventory` calls it.
  - `ingestion_migration._structure_digest` (`ingestion_migration.py:221`) covers all
    four schemas, including `wl_identity`; its frozen values are
    `EXPECTED_STRUCTURE_SHA256` and `EXPECTED_RESTORED_STRUCTURE_SHA256`.
  - `ingestion_migration.verify_inventory` (`:394`) accepts exactly the four
    namespaces `wl_pg`, `wl_identity`, `wl_sources`, `wl_ingestion`, so a new schema
    would break it too.
- Isolation in `wl_identity` today: the gateway role has no table privilege at all
  (`role_inventory` refuses any raw access); every read or write goes through a
  `SECURITY DEFINER` function that finds the user from the session digest
  (`identity_schema.session_user`, used by `touch_session_v1` and
  `password_target_v1`). The `wl_identity` tables have no row-level security; the
  finance tables in `wl_pg` do.
- `GUARD` takes `wl_identity.instance_auth_state ... FOR UPDATE`, so identity calls
  already run one at a time.
- Error codes: `persistence/identity.py:9` `STATUS` and `web_v2/schemas.py:144`
  `ERROR_CODES` have no identity revision-conflict code; `source_revision_conflict`
  belongs to the sources contract. A request DTO that fails validation becomes 422
  `invalid_input` (`api.py`, `RequestValidationError` handler).
- Frozen SQL text that this ticket must not edit: the `consume_budget_v1` operation
  allow-list (`identity_schema.py:235`) and the `auth_audit.action` CHECK (`identity_schema.py:214-218`).
- Constants: Python has `i18n.DEFAULT_LOCALE = "en-CA"` (`i18n.py:19`) but no tuple of
  supported locales; the catalogs are `src/kurafolio/locales/en-CA.json`, `zh-TW.json`
  and `zh-CN.json`. No module holds the twelve display currencies;
  `source_projection.CURRENCIES` (`source_projection.py:19`) is the three-code report
  contract. MKT-009C (ready, no Build plan) will serve the twelve from
  `GET /api/v2/currencies`.
- Time zones: `requirements.lock` pins `tzdata==2026.5` (IANA 2026e). Its `zones`
  resource lists 598 names, including `Factory` and backward links such as
  `US/Eastern`. `zoneinfo.available_timezones()` also merges the host's TZPATH, and
  `ZoneInfo(name)` can match a name in another letter case on a case-insensitive file
  system, so neither is a stable allow-list. PostgreSQL's `pg_timezone_names` comes
  from the server's own files and can differ from Python's.
- APP-011F (P0, depends on this ticket) tests against a mocked `/api/v2` and does not
  say what the Profile page does when the preferences routes are absent.

### Rechecked 2026-11-21 at `4c87113`

- Since `a2f5f2b`, `src/` changed only in the body of `wl_ingestion.claim_plan_v1`
  (IMP-007N, PR #88). No function or table was added, and `ingestion_migration.py`,
  `ingestion_restore.py` and every frozen hash are unchanged.
- `.github/workflows/ci.yml` at `4c87113`: `postgres-foundation` discovers
  `test_postgres_*.py` with `--expect-skipped 123`; `postgres-ingestion` runs only
  `test_postgres_migration.py`; `postgres-identity` runs `test_web_v2_api.py` with
  `--expect-skipped 0`. No job would run a new `tests/test_preferences_postgres.py`
  or an ingestion-only class in `tests/test_web_v2_api.py` without a new step.
- IMP-007E's plan (pull request #87, not merged; its new gated text waits for the
  owner's Gate A) builds the `ingestion` runtime profile:
  - `Database.__init__` maps `"ingestion"` to a literal revision, with a unit test
    comparing it to the schema module's `REVISION`; `context.py` imports no
    schema module.
  - `IdentityStore`, `SourceStore(..., schema_mode="ingestion")` and the new
    `IngestionStore` open `Database(config, schema_mode="ingestion")`, so the
    literal is the only revision the runtime pins.
  - `Settings.worker_role` and the `serve --worker-role` flag; the operator
    `--schema-profile` choice adds `ingestion`.
  - `Auth.ready()` on `ingestion` calls the newest revision's `verify_inventory(conn,
    runtime_role=runtime_role, gateway_role=gateway_role,
    worker_role=self.settings.worker_role)`.
  - `Boundary.request` and `create_app` add routes under
    `settings.schema_profile == 'ingestion'`.
  - Real-PostgreSQL HTTP tests in `tests/test_postgres_import_routes.py` build,
    activate (test-only helper) and serve `ingestion` targets.
- APP-011I's updated plan (pull request #82, not merged) moves that profile to
  `0005_invite_status`. The names this plan builds on:
  - `invite_status_schema.{REVISION, PREDECESSOR, SIGNATURES, FUNCTIONS = 69,
    guard_replacements(), invite_status_ddl(), ddl()}`. `guard_replacements()` returns 28 definitions,
    and `ddl()` appends `invite_status_v1`, so `0005` leaves 29 functions guarded
    with `'0005_invite_status'`.
  - `invite_status_migration.{grants, verify_inventory, migrate_invite_status}`.
  - Keyword-only extensions with defaults that keep today's results:
    `migration._identity_target_inventory(..., extra_functions=())`,
    `ingestion_migration.verify_functions(conn, *, revision, extra)` and
    `ingestion_migration.verify_grants(..., extra_gateway=())`.
  - A revision-selected restore profile in `ingestion_restore.py` (`0004` and `0005`
    entries).
  - `role_inventory` on `ingestion`: 23 `wl_identity` functions, gateway `EXECUTE`
    on `GATEWAY` plus `invite_status_v1`.
  - The operator command `migrate-invite-status`.
  - Tests in `tests/test_invite_status_postgres.py`: SQL cases on `0005` targets,
    plus an HTTP class that serves `ingestion` and checks that a `0004` database is
    refused.
- ANL-008's plan (pull request #83, not merged) adds `SUPPORTED_REVISIONS` in
  `src/kurafolio/projection/accepted.py` and a default-suite test in
  `tests/test_projection_positions.py` that fails unless the tuple lists every
  revision file from `0004_ingestion` on. A revision may be added only if it leaves
  the twelve `READ_TABLES`, `wl_pg.accounts`, `wl_pg.instruments` and the reader's
  grants unchanged. `0006` adds one `wl_identity` table with no grant and two
  gateway functions, so it meets that condition.
- IMP-007S (activation, filed in pull request #87 as backlog, not approved) has a
  draft AC-03 that refuses a database "whose inventory differs from `0004`". If that
  text is kept, activation would refuse a `0006` instance; see Stop and ask.
- `resources`: this ticket does not hold `identity-api`, which IMP-007E, IMP-007U
  and APP-011I hold for `web_v2/api.py`, `auth.py`, `config.py` and `__main__.py`.
  This ticket edits `api.py`, `auth.py` and `__main__.py` too. See Decisions
  needed, item 3.

## Requirements

### Expected behaviour

- `GET /api/v2/me/preferences` returns `locale`, `time_zone`, `reporting_currency` and a `revision`.
- `PUT /api/v2/me/preferences` replaces them with an expected revision; a stale revision is refused with the existing conflict error shape.
- A new user gets defaults (`en-CA`, `UTC`, `CAD`) until they save. Values are validated against the supported locale list (en-CA, zh-TW, zh-CN), the IANA zone database and the twelve display currencies the owner approved on 2026-11-11 (CAD, USD, TWD, EUR, GBP, JPY, AUD, CHF, HKD, SGD, CNY, KRW).
- Preferences are tenant-scoped: one user can never read or write another user's row.

### Scope

- In scope: storage, the two routes, validation, OpenAPI, tests, documentation.
- Out of scope: appearance (stays in the browser), a session list and per-session revoke (deferred by the owner; password change already ends other sessions), month grouping rules (CORE-101), any UI (APP-011F).

### Owner decisions recorded 2026-11-12

- The server stores locale, time zone and reporting currency, so a second device behaves the same.
- A session list is not part of the first release.

### Implementation notes

- Follow the route, error and CSRF patterns in `src/kurafolio/web_v2/api.py` and DTO style in `web_v2/schemas.py` (closed models).
- Identity SQL lives in `src/kurafolio/persistence/identity_schema.py` and `identity.py`; row-level security patterns are in [postgres-foundation.md](../docs/postgres-foundation.md).
- A new table needs an operator migration. Coordinate numbering with IMP-007D, which holds `migration-order`.
- Keep the currency list in one module constant. MKT-009C serves the same list from `GET /api/v2/currencies`; whichever ticket lands second reuses the first one's constant instead of adding a second copy.
- Tests: `tests/test_web_v2_api.py`, `tests/test_identity_transactions.py`.

## Acceptance criteria

- [ ] AC-APP-011E-01: Given a signed-in user with no saved preferences, when they GET, then defaults and revision 0 are returned.
- [ ] AC-APP-011E-02: Given a valid PUT with the current revision, then the values are stored and the revision increases by one.
- [ ] AC-APP-011E-03: Given a stale revision, an unsupported locale, an unknown zone or an unsupported currency, then the request is refused and nothing changes.
- [ ] AC-APP-011E-04: Given user A's session, then no request can read or change user B's preferences (SQL-level test, not only HTTP).
- [ ] AC-APP-011E-05: Unauthenticated and missing-CSRF requests are refused as other V2 mutations are.
- [ ] AC-APP-011E-06: `/api/v2/openapi.json` describes both routes; [web-v2-identity.md](../docs/web-v2-identity.md) documents them.

### Tests

- HTTP tests per refusal in `tests/test_web_v2_api.py`.
- Opt-in PostgreSQL tests for isolation and revision conflict.

## Build plan

- Based on: `main` at `a2f5f2b` (2026-11-19); rechecked on 2026-11-21 against
  `main` at `4c87113`, IMP-007E's Part A (pull request #87) and APP-011I's updated
  plan (pull request #82). See Context, "Rechecked".
- Do not claim this ticket until IMP-007E (the `ingestion` runtime profile) and
  APP-011I (revision `0005_invite_status`, which moves that profile to `0005`) have
  both merged; `depends_on` lists both. Steps 1 to 8 build on `0005`; steps 9 to 13
  move the profile to `0006`.
- Written for the owner's answer (a) to Decisions 1 and 2 (2026-11-20). Where a step
  names an APP-011I or IMP-007E interface, it uses the name in their plans. If the
  merged code differs, stop and ask (Stop and ask if).
- Planner decisions inside the approved scope (not gated): the table lives in
  `wl_identity`; the SQL functions take no user ID; the conflict code is
  `revision_conflict`; no rate budget and no audit row; the zone allow-list is the
  pinned `tzdata` list without `Factory`; the SQL side checks only formats; a write
  always increases the revision; preferences survive a restore.
- Order: Part A (revision `0006_user_preferences`, operator command, backup and
  restore), Part B (runtime profile at `0006`, constants, DTOs, routes), then docs,
  ANL-008's revision list and CI. One pull request.

### Part A: revision `0006_user_preferences`

1. `src/kurafolio/persistence/preferences_schema.py` (new). Constants
   `REVISION = "0006_user_preferences"`, `PREDECESSOR = "0005_invite_status"`,
   `TABLE = "user_preferences"` and
   `SIGNATURES = {"read_preferences_v1": ("text", "bigint"), "write_preferences_v1":
   ("text", "bigint", "bigint", "text", "text", "text")}`. Do not add them to
   `identity_schema.SIGNATURES`, `GATEWAY` or `TABLES`; `identity_schema.function()`
   asserts its parameters against `SIGNATURES`, so write a renderer in this module
   with the same header shape (`RETURNS pg_catalog.jsonb LANGUAGE plpgsql SECURITY
   DEFINER SET search_path=pg_catalog,pg_temp`, then `REVOKE ALL ON FUNCTION ... FROM
   PUBLIC`).
   - `guard_replacements()` returns `CREATE OR REPLACE` text for the 29 functions
     that `0005_invite_status` leaves guarded, rendered from the merged `0005`
     provider's own renderers: the 28 definitions of
     `invite_status_schema.guard_replacements()`, plus
     `invite_status_schema.invite_status_ddl()` (the `invite_status_v1` definition
     that `ddl()` appends), with its leading
     `CREATE FUNCTION ` changed to `CREATE OR REPLACE FUNCTION ` once. Never start
     from `identity_schema.ddl()`, `source_schema.ddl()` or the `0004` renderers. In
     each, replace `'0005_invite_status'` with `'0006_user_preferences'`. Raise
     `ValueError("Inherited guard provider changed")` unless there are 29 distinct
     `(schema, name)` pairs, each holds the old literal exactly once, and the result
     holds the new literal 29 times and the old one zero times. If the merged
     `invite_status_schema` states a count other than 29, stop and ask.
   - `table_ddl()` returns exactly:

     ```sql
     CREATE TABLE wl_identity.user_preferences(
      user_id uuid NOT NULL,
      locale text COLLATE "C" NOT NULL,
      time_zone text COLLATE "C" NOT NULL,
      reporting_currency text COLLATE "C" NOT NULL,
      revision bigint NOT NULL,
      updated_at timestamptz NOT NULL,
      CONSTRAINT user_preferences_pkey PRIMARY KEY(user_id),
      CONSTRAINT user_preferences_user_fkey FOREIGN KEY(user_id) REFERENCES wl_identity.users(id),
      CONSTRAINT user_preferences_locale_format CHECK(locale ~ '^[a-z]{2}-[A-Z]{2}$'),
      CONSTRAINT user_preferences_zone_format CHECK(length(time_zone) BETWEEN 1 AND 64
        AND time_zone ~ '^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$'),
      CONSTRAINT user_preferences_currency_format CHECK(reporting_currency ~ '^[A-Z]{3}$'),
      CONSTRAINT user_preferences_revision_range CHECK(revision BETWEEN 1 AND 9007199254740991),
      CONSTRAINT user_preferences_updated_finite CHECK(pg_catalog.isfinite(updated_at))
     );
     REVOKE ALL ON TABLE wl_identity.user_preferences FROM PUBLIC;
     ```

     No row-level security: `wl_identity` keeps its definer-function boundary (see
     Context), and the gateway gets no table privilege. Membership in the supported
     lists is checked in Python (step 10), so a later list change needs no migration.
     `9007199254740991` is the largest integer a browser reads exactly.
   - `ddl()` returns `table_ddl()`, then `guard_replacements()`, then both new
     functions.
2. The two functions. Build each body from `identity_schema` fragments as text: `GUARD`
   with `'0002_identity'` replaced by `'0006_user_preferences'` (raise `ValueError`
   unless it occurs exactly once), `session_user('p_digest')`, `user_lock`,
   `session_lock('p_digest')`, `CLOCK`, `check_user(version='p_version')`,
   `check_session()`, `fail` and `success`. Declare `st`, `a`, `u`, `ss`, `uid`, `n`
   and `pr wl_identity.user_preferences%ROWTYPE`. Both start, in this order: guard,
   `session_user('p_digest')` (which locks the user row), `session_lock('p_digest')`,
   clock, `check_user(version='p_version')`, `check_session()`, then
   `IF ss.user_id<>u.id OR ss.credential_version<>u.credential_version THEN`
   `session_changed`. The user comes only from the session row; no parameter names a
   user.
   - `read_preferences_v1(p_digest, p_version)`: `SELECT * INTO pr FROM
     wl_identity.user_preferences WHERE user_id=u.id;`. No row: success with
     `{"locale":"en-CA","time_zone":"UTC","reporting_currency":"CAD","revision":0}`.
     Otherwise the stored values and `pr.revision`. It inserts nothing.
   - `write_preferences_v1(p_digest, p_version, p_expected, p_locale, p_zone,
     p_currency)`: after the shared checks, any NULL argument, `p_expected<0`, or a
     value that fails the table's format CHECKs is `instance_not_ready`. Then
     `SELECT * INTO pr ... WHERE user_id=u.id FOR UPDATE;`. If
     `COALESCE(pr.revision,0)<>p_expected` → `revision_conflict`. If
     `p_expected>=9007199254740991` → `instance_not_ready`. No row: `INSERT` with
     revision 1 and `updated_at=n`; otherwise `UPDATE ... SET locale, time_zone,
     reporting_currency, revision=revision+1, updated_at=n`. A write with unchanged
     values still increases the revision. Success returns the four fields with
     `revision = p_expected+1`. No audit row (the `auth_audit` CHECK is frozen) and no
     budget call.
   - Concurrency: `GUARD` serializes identity calls and the user row is locked
     before the preferences row, so of two first writes with `p_expected=0` one
     inserts and the other answers `revision_conflict`; never a key violation.
3. `src/kurafolio/persistence/migrations/versions/0006_user_preferences.py` (new),
   `down_revision = "0005_invite_status"`. Copy the shape `0005_invite_status.py`
   uses: require an
   explicit operator attribute (`preferences_operator`) and raise
   `RuntimeError("Explicit preferences operator transaction required")` without it;
   run `preferences_schema.ddl()` with `execution_options={"no_parameters": True}`;
   call an optional `preferences_fault("after_functions")`. `downgrade()` raises
   `RuntimeError("Destructive preferences downgrade is not supported")`.
4. `src/kurafolio/persistence/preferences_migration.py` (new), shaped like
   `invite_status_migration.py`:
   - `grants(conn, runtime_role, gateway_role, worker_role)`: call
     `invite_status_migration.grants(...)` (which runs the `0004` matrix, revoking
     every function and table privilege first, and grants `invite_status_v1`), then
     `GRANT EXECUTE` on both new functions to the gateway role only. No table grant
     to any role.
   - `verify_inventory(conn, *, runtime_role, gateway_role, worker_role,
     quarantined=False)`: `alembic_version` exactly `["0006_user_preferences"]`, else
     `schema_unsupported`; the four-namespace check; the identity inventory with the
     extensions in step 5; the sources structure digest; the ingestion structure
     digest equal to `EXPECTED_STRUCTURE_SHA256_0006` (or
     `EXPECTED_RESTORED_STRUCTURE_SHA256_0006` when quarantined);
     `ingestion_migration.verify_functions(conn, revision=REVISION, extra=...)` with
     three `extra` entries (`invite_status_v1` as re-guarded by step 1, and the two
     new functions), each derived from the rendered `0006` text as APP-011I derives
     its entry, never from the live database; and
     `ingestion_migration.verify_grants(..., extra_gateway=...)` naming the same
     three functions. Return `{"schema_revision": "0006_user_preferences",
     "functions": 71}`.
   - `migrate_preferences(database, runtime_role, gateway_role, worker_role,
     key_digest, catalog, *, fault=None)`: copy `migrate_invite_status` (roles,
     advisory lock `1950174004`, explicit Alembic `Config`, operator lock, ready,
     initialized, key and catalog checks). Accept `[PREDECESSOR]` or `[REVISION]`,
     else `schema_unsupported`. On the predecessor:
     `invite_status_migration.verify_inventory` must pass, then upgrade, `grants`,
     `fault("after_grants")`. Always end with the `0006` `verify_inventory` and
     `fault("before_commit")`, in one transaction. A second run only verifies.
     Result `{"schema_revision": "0006_user_preferences", "functions": 71, "ready":
     <wl_ingestion.instance_state.ready is True>}`. `SQLAlchemyError` →
     `migration_target_invalid`.
5. Shared verification helpers gain keyword-only parameters whose defaults keep
   today's results byte for byte. Change no `0002` to `0005` call site.
   - `migration._identity_target_inventory(conn, version, *, extra_functions=(),
     extra_tables=(), extra_hashes=None)`: `extra_functions` is APP-011I's; this
     ticket passes all three extra functions through it. The extra `wl_identity`
     tables join the expected relation set; their constraint and column rows are
     left out of the two `known['0002_identity']` hashes and hashed separately
     against `extra_hashes`, using the same `sha256(json.dumps(sorted(...)))` form.
     Freeze the two `user_preferences` hashes in `preferences_schema.py`.
   - `ingestion_migration.verify_functions` and `verify_grants` need no new
     parameter: APP-011I's `revision`, `extra` and `extra_gateway` cover this
     ticket. With `revision="0006_user_preferences"`, the inherited and
     `wl_ingestion` guard bodies get the `0006` literal.
   - `ingestion_migration._structure_digest`: split the queries into
     `_structure_snapshot(conn, runtime_role, *, predecessor=False, restored=False)`,
     which returns the dict, and keep `_structure_digest` returning the same digest
     of it. Existing tests that pin the `0004` values must pass unchanged.
   - Freeze `EXPECTED_STRUCTURE_SHA256_0006` and its restored twin in
     `preferences_migration.py` from a PG18 synthetic install, with a comment saying
     so. Never compute them at startup.
6. `identity.role_inventory` when `database.schema_mode == "ingestion"`: 8
   `wl_identity` tables (`TABLES` plus `user_preferences`) with no raw access for
   the checked role; 25 `wl_identity` functions named `set(SIGNATURES) |
   set(invite_status_schema.SIGNATURES) | set(preferences_schema.SIGNATURES)` (the
   23 APP-011I expects, plus 2); gateway `EXECUTE` on exactly `GATEWAY`,
   `invite_status_v1` and the two new functions. `identity` and `sources` keep 7
   tables and 22 functions. Keep IMP-007E's `source_role_inventory` call on
   `ingestion`.
7. Backup and restore (`persistence/ingestion_restore.py`). Extend the
   revision-selected profile mechanism APP-011I adds (`backup_ingestion` and
   `_manifest` pick the profile and the matching `verify_inventory` by
   `alembic_version`) with a `0006` entry (`revision`
   `"0006_user_preferences"`, `functions` the `0006` total, the `0006` structure
   digests, the same sources digest). Do not change `FORMAT`, the `0004` `PROFILE`
   or the `0005` entry, so existing manifests verify byte for byte. Do not add
   `wl_identity.user_preferences` to `RELATIONS`: identity tables are not in the row
   evidence today. Restore keeps preference rows and revisions as they were; it
   still revokes sessions, invites and setup codes (`_fence_authority`).
8. Operator command `operator migrate-preferences`, same arguments as
   `migrate-ingestion`: add it to every argument set in `web_v2/__main__.py` that
   names `migrate-ingestion` and `migrate-invite-status` (lines 30-46 at `a2f5f2b`;
   IMP-007E and APP-011I add lines there, so find them by name), and a branch in
   `web_v2/operator.py` like the `migrate-invite-status` branch. Earlier migrators
   are not changed and answer `schema_unsupported` on `0006`.

### Part B: constants, DTOs, runtime profile and routes

9. `src/kurafolio/market/currencies.py` (new): `DISPLAY_CURRENCIES = ("CAD", "USD",
   "TWD", "EUR", "GBP", "JPY", "AUD", "CHF", "HKD", "SGD", "CNY", "KRW")`, the
   owner's order of 2026-11-11, and nothing else. If MKT-009C merged first with its
   own constant, import that instead and do not add this module. Leave
   `source_projection.CURRENCIES` alone.
10. `src/kurafolio/web_v2/preferences.py` (new):
    - `LOCALES = ("en-CA", "zh-TW", "zh-CN")`; `DEFAULTS = {"locale": "en-CA",
      "time_zone": "UTC", "reporting_currency": "CAD"}`.
    - `time_zones() -> frozenset[str]`, cached: the lines of
      `importlib.resources.files("tzdata").joinpath("zones")` minus `"Factory"`.
      Backward links such as `US/Eastern` stay valid because they are in the IANA
      database. Do not use `zoneinfo.available_timezones()` or `ZoneInfo(name)` as
      the test of membership.
    - `zone(value)`: a `str` that is exactly a member, else `ValueError`.
11. `src/kurafolio/web_v2/schemas.py`:
    - `Locale = Literal[LOCALES]`, `Currency = Literal[DISPLAY_CURRENCIES]`,
      `TimeZone = Annotated[str, Field(min_length=1, max_length=64),
      AfterValidator(zone)]`, `Revision = Annotated[int, Field(strict=True, ge=0,
      le=9007199254740991)]`.
    - `Preferences(Closed)`: `locale`, `time_zone`, `reporting_currency`, `revision`.
    - `PreferencesUpdate(Closed)`: `locale`, `time_zone`, `reporting_currency`,
      `expected_revision: Revision`.
    - Add `'revision_conflict'` to `ERROR_CODES`; the OpenAPI `Error` enum grows by
      one value.
12. `persistence/identity.py`: `STATUS['revision_conflict'] = 409`. On `ingestion`,
    `IdentityStore.call()` accepts names from `SIGNATURES`,
    `invite_status_schema.SIGNATURES` and `preferences_schema.SIGNATURES` (same cast
    table); elsewhere unchanged. Add `read_preferences(digest, version) -> dict` and
    `write_preferences(digest, version, expected, locale, zone, currency) -> dict`;
    each raises `IdentityError()` unless the value has exactly the four keys with the
    right types. `web_v2/auth.py`: `Auth.preferences(principal)` and
    `Auth.save_preferences(principal, body)` pass `principal.session_digest` and
    `principal.credential_version`, never a user ID.
13. The runtime profile at `0006`, after checking that the merged IMP-007E and
    APP-011I code has the shapes listed in Context ("Rechecked"); if not, set the
    ticket `blocked` and ask for a plan refresh:
    - `src/kurafolio/persistence/context.py`: in `Database.__init__`, change the
      `"ingestion"` value from `"0005_invite_status"` to `"0006_user_preferences"`.
      Keep it a literal; do not import `preferences_schema` there. Change the unit
      test for that literal (IMP-007E's, which APP-011I pointed at
      `invite_status_schema.REVISION`) to compare it with
      `preferences_schema.REVISION`.
    - `web_v2/auth.py`: `Auth.ready()` on `ingestion` calls
      `preferences_migration.verify_inventory(conn, runtime_role=runtime_role,
      gateway_role=gateway_role, worker_role=self.settings.worker_role)` instead of
      `invite_status_migration.verify_inventory`. Keep the realm comparison and the
      `wl_sources.catalog_state` digest check.
    - No change to `Settings`, `--worker-role`, the `--schema-profile` choices,
      `SourceStore` or `IngestionStore`.
    - Test helpers: every test that serves or opens an `ingestion` target (search
      `tests/` for `schema_profile='ingestion'`, `schema_profile="ingestion"` and
      `schema_mode="ingestion"`) runs `migrate_preferences` after
      `migrate_invite_status`. At least the environment builder in
      `tests/test_postgres_import_routes.py` (or `tests/ingestion_pg_support.py`)
      and the HTTP class of `tests/test_invite_status_postgres.py`. In that class,
      the case that a `0004` database is refused keeps its refusal; its second half
      (served after migrating) migrates through `migrate_preferences`. APP-011I's
      SQL-level cases on `0005` targets that never serve the profile stay at `0005`.
    - Add a case to this ticket's HTTP class (`PreferencesIngestionHttpTests`,
      Tests): a database left at `0005_invite_status`, served on `ingestion`, is
      refused (`Auth(settings)` raises `IdentityError`).
14. `web_v2/api.py`: `GET` and `PUT /api/v2/me/preferences`, in the `Boundary` route
    table and in `create_app` only when `settings.schema_profile == 'ingestion'`,
    the way IMP-007E registers its import routes and APP-011I its invitation-status
    route. They are authenticated routes like `GET /api/v2/me`, not import routes:
    they do not call `admit_rate_v1` and take no budget. `GET` → 200 `Preferences`;
    a query string is 422. `PUT` takes `PreferencesUpdate` and returns 200 with the
    new `Preferences`; the boundary already requires a session, the exact `Origin`,
    CSRF, `application/json` and at most 16 KiB. Stale revision → 409
    `revision_conflict`. Neither route touches `last_activity`. Owner decision of
    2026-11-20 (Decision 2, option (a)): on `identity` and `sources` both paths are
    404 `not_found`, answered before origin and CSRF checks, and absent from
    `/api/v2/openapi.json`.
15. Docs, all required:
    - [web-v2-identity.md](../docs/web-v2-identity.md), "HTTP/security contract": both
      routes, fields, defaults, the three lists, revision rules, the 409 code, that
      appearance stays in the browser, and that only the `ingestion` profile at
      `0006` serves them (404 on `identity` and `sources`).
    - [web-v2-imports.md](../docs/web-v2-imports.md): `migrate-preferences`, backup
      and restore at `0006`, and the operator order `migrate-ingestion`,
      `migrate-invite-status`, `migrate-preferences`, then `serve --schema-profile
      ingestion`.
    - [capability-status.md](../docs/capability-status.md): the "Optional V2 identity"
      row names server-side preferences and the profile they need.
16. ANL-008's revision list. If `src/kurafolio/projection/accepted.py` exists on
    `main` when this ticket is built (ANL-008 merged), first confirm that `0006`
    leaves the twelve `ingestion_schema.READ_TABLES`, `wl_pg.accounts`,
    `wl_pg.instruments` and the runtime role's grants unchanged (Context explains
    why it should), then append `"0006_user_preferences"` as the last entry of its
    `SUPPORTED_REVISIONS` tuple, after `"0005_invite_status"`. Its guard test in
    `tests/test_projection_positions.py` then passes. Change nothing else in that
    file. If the file does not exist, do nothing; ANL-008's builder adds `0006`. If
    the confirmation fails, stop and ask.
17. CI, `.github/workflows/ci.yml`:
    - `postgres-ingestion` job: add a step after APP-011I's
      `test_invite_status_postgres.py` step:
      `PYTHONPATH=src python scripts/run_gated_tests.py --expect-skipped 0 --
      discover -s tests -p 'test_preferences_postgres.py'`, and a step that runs
      only the new HTTP class:
      `PYTHONPATH=src:tests python scripts/run_gated_tests.py --expect-skipped 0 --
      test_web_v2_api.PreferencesIngestionHttpTests`. IMP-007E installs
      `requirements-web-test.lock` in that job.
    - `postgres-identity` job: the step that runs `test_web_v2_api.py` with
      `--expect-skipped 0` now skips the new class, which needs
      `KURAFOLIO_INGESTION_TEST`. Raise that value by the number of tests in the
      class and add a comment naming the job that runs them.
    - `postgres-foundation` is unchanged: no new file matches `test_postgres_*.py`.

### Interfaces

- SQL: `wl_identity.read_preferences_v1(text, bigint) → jsonb` and
  `wl_identity.write_preferences_v1(text, bigint, bigint, text, text, text) → jsonb`,
  returning `{"ok":true,"value":{"locale":...,"time_zone":...,"reporting_currency":...,
  "revision":<int>}}` or `{"ok":false,"code":...}` with one of `instance_not_ready`,
  `credentials_changed`, `session_changed`, `authentication_required`,
  `revision_conflict`. Gateway role only.
- HTTP: `GET /api/v2/me/preferences` → `{"locale","time_zone","reporting_currency",
  "revision"}`; `PUT /api/v2/me/preferences` with `{"locale","time_zone",
  "reporting_currency","expected_revision"}` → the same shape. Errors use the existing
  envelope.
- Python: `market.currencies.DISPLAY_CURRENCIES`; `web_v2.preferences.{LOCALES,
  DEFAULTS, time_zones, zone}`; `preferences_schema.{REVISION, PREDECESSOR, TABLE,
  SIGNATURES, table_ddl, guard_replacements, ddl}`;
  `preferences_migration.{grants, verify_inventory, migrate_preferences}`.

### Tests and expected values

Independent values, from the approved text and merged code, not from the new code:
defaults `en-CA`/`UTC`/`CAD` with revision 0; three locales; the twelve currencies in
the order above; `tzdata` 2026.5 lists 598 zones, so the allow-list has 597; the
`0006` function total is 71 (APP-011I's 69 plus 2); `wl_identity` has 8 tables and
25 functions on `0006`; the gateway can execute 18 `wl_identity` functions (APP-011I's
16 plus 2); 31 functions carry the `0006` literal (29 re-guarded plus the 2 new). Name
the acceptance ID in each test.

Unit tests, `tests/test_preferences_schema.py` (new, no database):

| AC | Case | Expected |
|---|---|---|
| 03 | `PreferencesUpdate` with `en-CA`/`zh-TW`/`zh-CN`; with `en`, `en-US`, `EN-CA`, `fr-CA` | Accepted; each refused |
| 03 | Zones `America/Toronto`, `Asia/Taipei`, `UTC`, `US/Eastern`, `Etc/GMT+5`; zones `america/toronto`, `UTC ` , ` UTC`, `Mars/Olympus`, `Factory`, `localtime`, `posixrules`, `""`, 65 characters, `../etc/passwd` | Accepted; each refused |
| 03 | Currencies `CAD`, `KRW`; `cad`, `BTC`, `XAU`, `CAD ` | Accepted; each refused |
| 03 | `expected_revision` of `true`, `1.0`, `"1"`, `-1`, `9007199254740992`; an extra field | Each refused |
| 03 | `len(time_zones())`, `"Factory" in time_zones()` | 597, False |
| 06 | `DISPLAY_CURRENCIES` | The twelve codes, typed out in the test, in order |
| 06 | `LOCALES` | Equals the catalog file names in `src/kurafolio/locales/` other than `legacy` and `registry`; first is `i18n.DEFAULT_LOCALE` |
| 04 | `preferences_schema.ddl()` | Both functions hold `'0006_user_preferences'` once; neither signature has a `uuid` parameter; no `GRANT` on the table |
| 04 | `guard_replacements()` | 29 definitions, 29 × `'0006_user_preferences'`, no `'0005_invite_status'` left; each equals its `0005` text except the literal and, for `invite_status_v1`, the `CREATE OR REPLACE` prefix |
| 04 | Rendering the `0002` to `0005` providers before and after importing the new modules | Byte-identical |

PostgreSQL tests, `tests/test_preferences_postgres.py` (new; opt-in with
`KURAFOLIO_INGESTION_TEST=1`). Build a `0005` target as
`tests/test_invite_status_postgres.py` does (identity, sources, the seeded
administrator, `migrate_ingestion`, `migrate_invite_status`), then
`migrate_preferences`. Call the functions as the gateway role, with two users A
and B and their session digests.

| AC | Case | Expected |
|---|---|---|
| 01 | A reads with no row | `en-CA`, `UTC`, `CAD`, revision 0; table still has 0 rows |
| 02 | A writes `zh-TW`, `Asia/Taipei`, `TWD`, expected 0; then `zh-CN`, `America/Toronto`, `USD`, expected 1; then the same values, expected 2 | Revisions 1, 2, 3; the read returns the last values |
| 03 | A writes with expected 2 when the row is at 3; expected 0 when a row exists | `revision_conflict`; the row (all six columns) unchanged |
| 03 | SQL-level bad values: locale `en_CA`, zone `a b`, currency `cad`, expected -1, a NULL argument | `instance_not_ready`; row unchanged |
| 03 | Two threads write with expected 0 at once | One revision 1, one `revision_conflict`; no driver error |
| 04 | B saves `zh-TW`/`Asia/Taipei`/`TWD`; A reads, A writes | A sees defaults then its own values; B's row byte-identical |
| 04 | Gateway `SELECT`, `INSERT`, `UPDATE`, `DELETE` on `wl_identity.user_preferences`; runtime and worker role the same and `EXECUTE` on both functions; PUBLIC | Each refused with SQLSTATE `42501` |
| 04 | `pg_proc` argument types of both functions | `text, bigint` and `text, bigint, bigint, text, text, text` |
| 04 | A's digest with B's credential version; a logged-out digest; an anonymous digest | `credentials_changed` or `session_changed`; never B's values; nothing changes |
| 04 | `alembic_version` set to `0005_invite_status` in a rolled-back nested transaction | Both new functions and a re-guarded identity function answer `instance_not_ready` |
| 04 | Password change for A, then a new session | Old session refused; new session reads A's saved values |
| 06 | `_structure_snapshot` on the same target before and after `migrate_preferences` | The difference is exactly the `user_preferences` relation, its `user_preferences_pkey` index, its six columns, its seven named constraints plus the NOT NULL constraints PG18 records, and its two row types; nothing removed |
| 06 | `verify_inventory` on a fresh `0006` target; after `GRANT SELECT` on the table to the gateway; after `GRANT EXECUTE` to PUBLIC; after replacing a function body | Passes with the expected total; then `migration_target_invalid` each time |
| 06 | `migrate_preferences` on `0002`, `0003` and `0004` targets; with `fault` at `after_grants`; a second run; the `0005` migrator on `0006` | `schema_unsupported`, target unchanged; still `0005` and its `verify_inventory` passes; same result; `schema_unsupported` |
| 06 | `operator migrate-preferences` through `python -m kurafolio.web_v2` | Prints `{"schema_revision": "0006_user_preferences", "functions": 71, "ready": false}` |
| 02 | `backup-ingestion` at `0006` with saved preferences, `restore-ingestion` into an empty target | Manifest revision `0006_user_preferences`; restored rows and revisions identical; sessions revoked |
| 06 | A `0004` and a `0005` backup | Still restore; their manifests are unchanged |

HTTP tests: a new class `PreferencesIngestionHttpTests` in `tests/test_web_v2_api.py`
(the file Requirements name), skipped unless `KURAFOLIO_INGESTION_TEST=1`. It builds
and activates a `0006` target with the environment helpers of
`tests/test_postgres_import_routes.py` (or `tests/ingestion_pg_support.py` if
IMP-007E put them there), which step 13 extends with `migrate_preferences`, and
serves `create_app` on `ingestion` with `worker_role`. Import those helpers inside
the class's `setUpClass`, after its skip guard, not at module level: the default and
core-only suites import `tests/test_web_v2_api.py`, and a module-level import of
PostgreSQL helpers could break their discovery. Do not copy the helpers. CI runs the
class in `postgres-ingestion` (step 17). Real disposable targets only.

| AC | Case | Expected |
|---|---|---|
| 01 | `GET` for a new user | 200, body exactly `{"locale":"en-CA","time_zone":"UTC","reporting_currency":"CAD","revision":0}` |
| 02 | `PUT` `zh-TW`/`Asia/Taipei`/`TWD`, `expected_revision` 0; `GET`; a second login with a new client, `GET` | 200 revision 1; the same body; the same body |
| 03 | `PUT` with a stale revision; locale `fr-CA`; zone `Mars/Olympus`; currency `BTC`; each followed by `GET` | 409 `revision_conflict`; 422 `invalid_input` three times; `GET` unchanged every time |
| 04 | A and B with different saved values each `GET`; `GET /api/v2/me/preferences?user=<B's id>` | Each sees only their own; 422 |
| 05 | No cookie; an anonymous session; `PUT` without CSRF; wrong `Origin`; `text/plain` body; `POST` | 401 `authentication_required` twice; 403 `csrf_rejected`; 403 `origin_rejected`; 415; 405 with `Allow: GET, PUT` |
| 06 | `/api/v2/openapi.json` | Path with `get` and `put`; locale enum of 3, currency enum of 12; `revision_conflict` in the error enum |
| 06 | `identity` and `sources` profiles (in their existing classes in `tests/test_web_v2_api.py` and `tests/test_web_v2_sources.py`) | Both methods 404 `not_found` before origin and CSRF checks; the path absent from OpenAPI |
| 06 | A database left at `0005_invite_status`, settings on `ingestion` (step 13) | `Auth(settings)` raises `IdentityError`; after `migrate_preferences` the same target is served and `/readyz` is 200 |

Verify: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`;
`KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s
tests -p 'test_preferences_postgres.py' -v` and the same for
`test_postgres_migration.py`, `test_invite_status_postgres.py` and
`test_postgres_import_routes.py`;
`KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src:tests .venv/bin/python -m unittest
test_web_v2_api.PreferencesIngestionHttpTests -v` with `requirements-web-test.lock`
installed; the identity HTTP suite with `KURAFOLIO_IDENTITY_TEST=1` as
[web-v2-identity.md](../docs/web-v2-identity.md) describes; when ANL-008 has merged,
`PYTHONPATH=src .venv/bin/python -m unittest tests.test_projection_positions -v`. A
skipped PostgreSQL test is not acceptance.

### Rollback

- `0006` is one operator transaction; any failure leaves `0005` intact (tested). There
  is no downgrade. Take `backup-ingestion` before migrating; to go back, restore that
  `0005` backup into a new empty database. Preferences saved after the backup are lost.
- Reverting the code leaves `0006` databases refused by the old code, which accepts
  only its own revision.
- `identity` and `sources` instances get no schema change.

### Do not touch

- The text of `identity_schema.py`, `source_schema.py`, `ingestion_schema.py`, the
  `0005` provider, the `0001` to `0005` migration files, and every frozen hash
  (`EXPECTED_*_SHA256`, `known` in `_identity_target_inventory`, the `0004` and `0005`
  restore profiles).
- `consume_budget_v1`, the `auth_audit` actions, `GET /api/v2/me`, password change.
- Any UI (APP-011F), the currencies route and FX (MKT-009C), sessions lists.
- In IMP-007E's and APP-011I's files, change only what step 13 names: the
  `"ingestion"` literal in `context.py` and its unit test, the `Auth.ready()` call,
  the `role_inventory` branch (step 6), `IdentityStore.call()` (step 12), the test
  environment builders and the cases step 13 lists. The import routes, the
  invitation-status route, `IngestionStore`, `Settings.worker_role` and the CLI flags
  stay as they were.
- In `src/kurafolio/projection/accepted.py` (ANL-008), only the
  `SUPPORTED_REVISIONS` tuple, and only as step 16 says.
- In `.github/workflows/ci.yml`, only the steps and the skip count of step 17.
- IMP-007S's files and its activation command, if they have merged; see Stop and
  ask.

### Stop and ask if

- APP-011I or IMP-007E has not merged.
- The merged `0005` differs from what this plan assumes: no revision-selected restore
  profile, a guarded-function count other than 29, a function total other than 69,
  or helper names (`invite_status_schema`, `invite_status_migration`, the
  `extra_functions`, `revision`, `extra` and `extra_gateway` parameters) that steps 1
  to 7 cannot use or extend with defaults that keep today's results.
- The merged ingestion profile pins its revision somewhere other than the
  `"ingestion"` literal in `Database.__init__`, or `Auth.ready()` does not call one
  `verify_inventory`. Set the ticket `blocked` and ask for a plan refresh.
- IMP-007S has merged and its activation command refuses a `0006` database, or
  checks `0004_ingestion` exactly. Do not change IMP-007S's code; set the ticket
  `blocked` and ask.
- ANL-008 has merged and step 16's confirmation fails.
- A merged test other than those step 13 names asserts that the ingestion runtime
  revision is `0005_invite_status`; ask before changing what it asserts.
- Another revision `0006` exists on `main`.
- The `_structure_snapshot` difference holds anything beyond the new table's rows,
  or a frozen `0004`/`0005` value changes.
- Meeting a criterion would need an edit to frozen provider text, a budget, an audit
  action, or a second new error code.
- MKT-009C merged a currency constant whose list or order differs from the twelve
  above.

## Plan

- [x] Owner answers the decisions and gates the contract.
- [x] Write the Build plan from `main` at `a2f5f2b`.
- [x] Owner answers Decisions 1 and 2 and confirms the `depends_on` change in the Log (2026-11-20).
- [x] Recheck the Build plan against `main` at `4c87113`, IMP-007E's Part A and APP-011I's updated plan.
- [ ] Wait for IMP-007E and APP-011I to merge.
- [ ] Part A: revision `0006_user_preferences`, operator command, backup and restore, with unit and PostgreSQL tests.
- [ ] Part B: constants, DTOs, runtime profile at `0006`, routes and HTTP tests.
- [ ] Documentation.
- [ ] ANL-008's `SUPPORTED_REVISIONS` if it has merged; CI steps.

## Decisions needed

Items 1 and 2 were answered by the owner on 2026-11-20 and are kept here as the
record. Item 3 is a confirmation that does not block the build.

1. **Answered 2026-11-20: option (a).** Asked how this ticket's `0006` should follow
   APP-011I's `0005`, the owner chose "Raise APP-011I to P0 (Recommended)": keep
   `0005` invite status, `0006` preferences; APP-011E depends on APP-011I and the
   profile ticket (IMP-007E). Asked "Which ticket builds the ingestion runtime
   profile?", the owner chose "IMP-007E (Recommended)", whose text says APP-011I and
   APP-011E add IMP-007E to `depends_on`. `depends_on` now lists APP-011I and
   IMP-007E, and APP-011I is P0. The question and options as asked:

   Which revision carries the preferences table, and what must merge first? Today no
   running instance could serve it (Context: no runtime profile serves anything after
   `0003`, and AUTH-101 put this ticket's revision after `0005_invite_status`).
   - (a) Revision `0006_user_preferences` after `0005_invite_status`, as AUTH-101
     recorded. Add APP-011I and the ticket that builds the runtime profile (APP-011I's
     Decision 1) to `depends_on`; the owner confirms that in this ticket's Log. No
     gated text changes. Cost: this P0 ticket waits on P1 APP-011I, so the owner may
     want APP-011I raised to P0.
   - (b) This ticket takes `0005_user_preferences` and APP-011I moves to `0006`. It
     removes the wait on APP-011I but still needs the runtime profile. It reverses part
     of the AUTH-101 record, changes APP-011I's gated AC-01 (which names
     `0005_invite_status`) and invalidates its plan in PR #82, so APP-011I needs a new
     approval and a new plan.
   - (c) Serve preferences on the `identity` and `sources` profiles too. Those
     instances stop at `0002` or `0003`, and the revision chain is linear and frozen,
     so this needs a new migration design (an Architect decision like AUTH-101) and a
     change to this ticket's Requirements, which then needs a new approval.

   Recommendation: (a). It follows the recorded AUTH-101 decision, changes no gated
   text, and the V2 MVP's real instances will run the import profile anyway.

2. **Answered 2026-11-20: option (a).** The owner accepted "APP-011E #2 preferences
   routes return 404 and are absent from OpenAPI on identity/sources instances" with
   "Accept all (Recommended)". Build plan step 14 follows it. APP-011F's planner must
   raise the "preferences are not available on this instance" state with the owner
   before APP-011F is planned; this ticket does not edit APP-011F. The question and
   options as asked:

   What do the preferences routes do on an `identity` or `sources` instance?
   - (a) They do not exist: 404 `not_found`, and they are absent from
     `/api/v2/openapi.json`, as the source routes are on `identity` today. APP-011F
     then needs a state for "preferences are not available on this instance" (for
     example browser-only language and the fixed zone), which its approved text does
     not describe, so APP-011F's planner raises it with the owner.
   - (b) `GET` returns the defaults with revision 0 and `PUT` is refused with a new
     error code. The page could load the same way everywhere, but a user would see
     values they cannot save, and the contract gains a code only for this case.

   Recommendation: (a).

With answer (a) to both, no change to Goal, Requirements or Acceptance criteria is
needed: the criteria are met and tested on the `ingestion` profile at `0006`.

3. **Add `identity-api` to `resources`? (owner confirmation, not blocking).** This
   ticket edits `web_v2/api.py`, `auth.py` and `__main__.py`, which IMP-007E,
   IMP-007U and APP-011I lock with `identity-api`. Because `depends_on` already
   orders it after IMP-007E and APP-011I, only IMP-007U could build at the same
   time and touch the same files. Changing `resources` of this approved ticket needs
   the owner's confirmation in the Log.
   - (a) Add `identity-api`, so IMP-007U and this ticket never build at once.
   - (b) Keep `resources` as they are and accept a possible merge conflict in
     those files with IMP-007U.

   Recommendation: (a). Without an answer the build may go ahead under (b).

## Handoff

- State: Not started. No code written. Gate A recorded 2026-11-12; the owner's
  answers of 2026-11-20 to Decisions 1 and 2 are in the Build plan. The build waits
  for IMP-007E and APP-011I. IMP-007E itself waits for the owner's Gate A on its new
  gated text (pull request #87), and APP-011I waits for IMP-007E.
- Next step: After both have merged, run `git fetch origin` and
  `python3 scripts/tickets.py spec APP-011E`, then check the merged `0005` and
  profile code against Context ("Rechecked") and Build plan step 13 before writing
  `src/kurafolio/persistence/preferences_schema.py`.
- Verify: the commands under "Tests and expected values" in the Build plan.
- Gotchas:
  - Real-PostgreSQL tests need the explicit isolated environment; a skipped test is
    not acceptance. Never run against a real instance.
  - IMP-007S's draft AC-03 (pull request #87, not approved) refuses an inventory
    other than `0004`. If IMP-007S merges with that rule, activation refuses a
    `0006` instance; Stop and ask covers it.
  - ANL-008 may merge before this build. If it has, step 16 applies, and its
    `tests/test_projection_positions.py` fails until `0006_user_preferences` is
    added.
  - APP-011F's planner must raise the "preferences unavailable" state with the
    owner (Decision 2).
- Open questions: Decision 3 (`identity-api` in `resources`), not blocking.

## Log

- 2026-11-10 planner: created from the UI/UX feature inventory (tickets/UX_FEATURE_INVENTORY.md).
- 2026-11-12 planner: owner approved Gate A on 2026-11-12 and released the ticket (status ready). Decisions: locale, time zone and currency on the server (option a); session list deferred (option b).
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved "Expected behaviour", "Scope", "Owner decisions recorded 2026-11-12" and "Implementation notes" from Context into Requirements and numbered the acceptance criteria AC-APP-011E-01 to 06. Spec hash sha256:3c4a7cd2b13f7fe8a817e6aaa23b8058c6a5a4a01f56df10dad50048674932b8, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:3c4a7cd2b13f7fe8a817e6aaa23b8058c6a5a4a01f56df10dad50048674932b8.
- 2026-11-19 claude-code/opus-5.5: wrote the Build plan from `main` at `a2f5f2b` in plan PR https://github.com/gh-slee/kurafolio/pull/84 (revision `0006_user_preferences` after `0005_invite_status`; routes only on the profile at `0006`); corrected Context line numbers and added planning findings; added Decisions 1 (revision order and dependencies) and 2 (behaviour on `identity`/`sources`). Do not claim until both are answered. Gated sections unchanged.
- 2026-11-21 claude-code/opus-5.5: added APP-011I and IMP-007E to `depends_on`. The owner confirmed both on 2026-11-20. For APP-011I: asked how this ticket's 0006 should follow APP-011I's 0005, they chose "Raise APP-011I to P0 (Recommended)": "keep 0005 invite status, 0006 preferences; APP-011E depends on APP-011I and the profile ticket (IMP-007E)." For IMP-007E: asked "Which ticket builds the ingestion runtime profile?", they chose "IMP-007E (Recommended)": "its approved r7 scope already covers it; IMP-007E adds the `identity-api` resource; APP-011I and APP-011E add IMP-007E to depends_on." This answers Decision 1 with option (a).
- 2026-11-21 claude-code/opus-5.5: recorded Decision 2 as option (a). The owner accepted "APP-011E #2 preferences routes return 404 and are absent from OpenAPI on identity/sources instances" with "Accept all (Recommended)" on 2026-11-20. APP-011F's planner must raise the "preferences unavailable" state with the owner; APP-011F was not edited.
- 2026-11-21 claude-code/opus-5.5: updated the plan in plan pull request https://github.com/gh-slee/kurafolio/pull/84. Rechecked against `main` at `4c87113`, IMP-007E's Part A (pull request #87) and APP-011I's updated plan (pull request #82). Steps now use their interfaces: `0006` re-guards the 29 functions `0005` leaves guarded, 71 functions in total, and the `ingestion` profile moves from `0005` to `0006` (step 13). Added step 16 (ANL-008's `SUPPORTED_REVISIONS`), step 17 (CI steps), and Decision 3 (`identity-api` in `resources`, not blocking). Goal, Requirements and Acceptance criteria unchanged.
