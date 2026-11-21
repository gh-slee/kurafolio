---
id: APP-011I
title: Tell an invitee whether their invitation is still usable
priority: P0
status: ready
type: feature
parent: APP-011
depends_on: [APP-011B, AUTH-101, IMP-007D, IMP-007E]
resources: [identity-api, frontend-identity-ui, identity-contract, migration-order, postgres-schema]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-12, option 1 (anonymous link check before the form), priority P1"
review: independent
branch: ticket/wl-p0-011i-tell-an-invitee-whether-their-invitation
pr: 
spec: docs/specs/v2-drafts/WL-P0-011.md
spec_approved: sha256:4b2a286b772f4c5edbdde50b081fafbaa69205f535dda1002a55419cc2fa13af
updated: 2026-11-21
---

# APP-011I: Tell an invitee whether their invitation is still usable

## Goal

When someone opens an invitation link that has expired, been revoked or already been used, the registration page tells them which, and shows no form. APP-011B could not do this because the API gives the browser no way to tell these states apart.

## Context

### Spec material

- The r7 SQL appendix the Handoff refers to: [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md) in [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file).
- Background only: the revision 1 planning draft [docs/specs/v2-drafts/WL-P0-011.md](../docs/specs/v2-drafts/WL-P0-011.md) (sha256:c1e6032acd9488898f8a71cb0fd8edc2b8867ae4816d33a43bf4c5b9e26b8636). Where it differs from this ticket, this ticket applies.

### Current behaviour

- `POST /api/v2/auth/register` (`src/kurafolio/web_v2/api.py`) answers an inactive invitation and a taken username with the same code, `registration_rejected` (`register_commit_v1` in `src/kurafolio/persistence/identity_schema.py`). It answers only after the person has filled in the form.
- No endpoint reports an invitation's state from its token.
- APP-011B therefore keeps the form after `registration_rejected` and shows one message that names both causes. A missing or malformed token already shows a message and no form.

### Found while planning, 2026-11-19 at `a2f5f2b`

- All three dependencies are merged: APP-011B (PR #49), AUTH-101 (PR #54) and
  IMP-007D (PR #60). `migrations/versions/` holds `0001` to `0004`; no file or ticket
  claims `0005`. Every operator migration upgrades to an explicit revision
  (`migration.py:73` and `:273`, `source_migration.py:248`,
  `ingestion_migration.py:475`), never to `head`, so a `0005` file changes nothing
  they install.
- No runtime profile can serve a `0004` database, so none can serve `0005` yet.
  `Database` (`persistence/context.py:47`) maps only `foundation`, `identity` and
  `sources`, and the profile checks at `context.py:55`, `:114` and `:154` accept only
  `identity` and `sources`. So do `IdentityStore` (`identity.py:104`),
  `role_inventory` (`identity.py:202` and `:245`), `Settings.schema_profile`
  (`web_v2/config.py`), `serve --schema-profile` and the operator
  `--schema-profile` (`web_v2/__main__.py`), `Auth.__init__` and `Auth.ready`
  (`web_v2/auth.py:58-106`) and route registration (`web_v2/api.py:185` and `:416`).
  [web-v2-imports.md](../docs/web-v2-imports.md) says there is no operational `0004`
  profile, and `migrate_ingestion` leaves `wl_ingestion.instance_state.ready` false.
  The r7 appendix ("Profile integration and readiness") requires an explicit
  ingestion branch in `Database`, Auth and config. On 2026-11-20 the owner assigned
  that branch to IMP-007E (Decisions needed, item 1), which builds it as its Build
  plan Part A (plan pull request #87) and serves `0004_ingestion`. This ticket then
  moves it to `0005_invite_status` (Build plan step 9).
- `0004` re-guards 28 functions with `'0004_ingestion'`: 20 of the 22 `wl_identity`
  functions (all but `identity_status_v1` and `_clock_timestamp_v1`, which carry no
  guard) and the 6 `wl_sources` gateway functions, rendered by
  `ingestion_migration.inherited_guard_replacements()` from their `0003` text, plus
  `wl_ingestion._guard_user_v1` and `_guard_worker_v1` (`ingestion_schema.py:4565`
  and `:4640`). Rendering the `0004` providers at `a2f5f2b` gives the literal 26 times
  in `inherited_guard_replacements()` (once per function), twice in
  `ingestion_migration.function_ddl()` and never in `tables_ddl()`,
  `policies_ddl()` or `triggers_ddl()`. `ingestion_migration.verify_functions` counts
  68 functions on a `0004` database (36 inherited and 32 `wl_ingestion`);
  `tests/test_postgres_migration.py` expects 68 (line 383 at `4c87113`).
- The re-guarded identity functions check `wl_pg.instance_state.ready` and the
  revision, not `wl_ingestion.instance_state.ready`. Registration therefore works on
  a `0004` database although the ingestion flag is false, and `invite_status_v1`
  behaves the same way.
- Verification that pins the `0002` identity function set: `_identity_target_inventory`
  (`migration.py:149`, compares `wl_identity` functions with `SIGNATURES`, called by
  the `0004` `verify_inventory`), `role_inventory` (`identity.py:202`, exactly 22),
  `ingestion_migration.verify_functions`/`verify_grants` and the restore manifest
  profile (`ingestion_restore.PROFILE`, `"functions": "68"`). `backup_ingestion` and
  `restore_ingestion` call the `0004` `verify_inventory`, which refuses any revision
  but `0004_ingestion`.
- Budgets are consumed in Python before each identity call (`Auth.budget` →
  `consume_budget_v1`). The `register` operation allows 5 attempts per peer and 20 per
  instance in a 900-second window (`identity_schema.py:243-253`).
- Every restore path (`finalize_identity_restore`, `finalize_sources_restore`,
  `ingestion_restore._fence_authority`) revokes all `issued` invites with reason
  `restore` in the transaction that rotates the incarnation. An `issued` invite from
  another incarnation or epoch therefore exists only after an out-of-band edit;
  `admin_read_invites_v1` already answers `instance_not_ready` for it.
- The browser tests fake the V2 API (`frontend/tests/browser/v2-identity.spec.ts`);
  they need no real `0005` instance. The fake answers an unhandled path with 404
  `not_found`, but it records the body of every `POST` that passes its CSRF check
  (lines 66-80), and the registration test asserts that `bodies[0]` is the register
  body. The Python HTTP tests (`tests/test_web_v2_api.py`) run on real disposable
  PostgreSQL targets.
- In `CredentialsPage` (`frontend/src/v2/auth-pages.tsx:275`) every hook runs before
  the early `if (shown) return` at line 311; the blocked view already renders an
  alert, a sign-in link and no form. `main.tsx` mounts the app in `StrictMode`, so
  effects run twice in development.

### Rechecked 2026-11-21 at `4c87113`

- Since `a2f5f2b`, `src/` changed only in `ingestion_schema.py` (IMP-007N, PR #88):
  the body of `wl_ingestion.claim_plan_v1` and a Python helper. No function was
  added, and `ingestion_migration.py`, `ingestion_restore.py` and every frozen hash
  are unchanged. Rendering the `0004` providers at `4c87113` still gives the literal
  26 times in `inherited_guard_replacements()` and twice in `function_ddl()`.
- `.github/workflows/ci.yml`: the `postgres-foundation` job discovers
  `test_postgres_*.py` with `--expect-skipped 123` at `4c87113` (118 at
  `a2f5f2b`). The `postgres-ingestion` job runs only `test_postgres_migration.py`.
- IMP-007E's plan (pull request #87, not merged) builds the profile with these
  interfaces, which step 9 changes:
  - `Database.__init__` maps `"ingestion"` to the literal `"0004_ingestion"`, with a
    unit test asserting that it equals `ingestion_schema.REVISION`. `context.py`
    does not import the schema module.
  - `IdentityStore` and `SourceStore(..., schema_mode="ingestion")` and the new
    `IngestionStore` all open `Database(config, schema_mode="ingestion")`, so the
    literal is the only revision the runtime pins.
  - `role_inventory` also runs `source_role_inventory` on `ingestion` and keeps
    22 `wl_identity` functions.
  - `Settings` gains `worker_role`; `serve` gains `--schema-profile ingestion` and
    `--worker-role`; the operator `--schema-profile` choice adds `ingestion`.
  - `Auth.ready()` on `ingestion` calls `ingestion_migration.verify_runtime_inventory(conn,
    runtime_role=runtime_role, gateway_role=gateway_role,
    worker_role=self.settings.worker_role)` through the runtime connection, with
    `runtime_role` from `SELECT current_user`, and keeps the realm and catalog
    digest checks. It calls `role_inventory` only with `gateway=True`. Revised on
    2026-11-21: the operator `verify_inventory` needs database CREATE, which `0004`
    takes from every application role, and `role_inventory(gateway=False)` expects
    INSERT rights the read-only runtime role lacks at `0004`. IMP-007W (Gate A
    given 2026-11-21, not built) adds the runtime check with a private
    `ingestion_migration._runtime_owner(conn, *, runtime_role, gateway_role,
    worker_role)` and a keyword-only `owner` on `_checked_roles` and
    `verify_grants`; IMP-007E depends on it.
  - `Boundary.request` and `create_app` serve the source routes and the eight
    import routes on `ingestion`.
  - Real-PostgreSQL HTTP tests in `tests/test_postgres_import_routes.py` build
    identity, sources and ingestion targets, activate them with a test-only
    helper and serve `create_app` on `ingestion`. They include a case that
    `/readyz` answers 200 on a migrated `0004` instance.
- APP-011I and IMP-007E share the `identity-api` resource. Since APP-011I depends
  on IMP-007E, they never build at the same time.
- ANL-008's plan (pull request #83, not merged) adds `SUPPORTED_REVISIONS` in
  `src/kurafolio/projection/accepted.py`, starting as `("0004_ingestion",)`, and a
  default-suite test in `tests/test_projection_positions.py` that fails unless the
  constant lists every revision file from `0004_ingestion` on. A revision may be
  added only if it leaves the twelve `READ_TABLES`, `wl_pg.accounts`,
  `wl_pg.instruments` and the reader's grants unchanged. `0005` adds no relation,
  and its `grants` re-runs the `0004` matrix and adds one gateway `EXECUTE`, so it
  meets that condition.
- IMP-007S (activation, filed in pull request #87 as backlog, not approved) has a
  draft AC-03 that refuses a database "whose inventory differs from `0004`". If
  that text is kept, activation would refuse a `0005` instance. This is for
  IMP-007S's planner and the owner; see Stop and ask.

## Requirements

### Expected behaviour

- Before showing the form, the registration page learns whether the token is usable, expired, revoked or used, and shows a distinct message with no form for each inactive state.
- After submit, a taken username is reported on the username field, separately from an inactive invitation.

### Owner decision recorded 2026-11-12

The owner chose option 1 and priority P1. The single code looks deliberate: it avoids telling an anonymous caller whether a token or a username exists. The options considered were:

1. A rate-limited anonymous `POST` that takes the token in the body and returns only `usable | expired | revoked | consumed` (no IDs, dates or usernames). The token is a 256-bit secret, so the answer reveals nothing a guesser could use.
2. Split `registration_rejected` into `invite_not_active` and `username_unavailable` on submit only. No new endpoint, but the form is still shown first.
3. Keep the current behaviour and amend the APP-011B criterion text.

Notes from the APP-011B product review:

- Option 1 also covers a taken username: once the link is known to be usable, a
  later `registration_rejected` almost always means the username, and the page can
  say so on that field. A separate username code (option 2) then only adds certainty.
- Each username retry uses one of the five registration attempts per 15 minutes per
  peer, so the page should ask for one retry, not several.
- The reviewer suggested P1 instead of P0 for a few-user, invite-only MVP; the owner
  decides.

### Scope

- In scope: the chosen API change, its persistence function and tests, the registration page states, locale keys, browser tests.
- Out of scope: open self-registration (post-MVP owner decision of 2026-11-10).

## Acceptance criteria

- [ ] AC-APP-011I-01: Given an expired, revoked or consumed invitation on an instance at `0005_invite_status` or later, then a distinct message is shown and no form.
- [ ] AC-APP-011I-02: Given an instance on the `identity` (`0002`) or `sources` (`0003`) profile, then the page shows the form and keeps the current combined `registration_rejected` message, with no error from the missing status check.
- [ ] AC-APP-011I-03: Given a usable invitation and a taken username, then the username field shows its own message and the form stays.
- [ ] AC-APP-011I-04: Anonymous callers learn nothing about other tokens, users or invitations; budgets apply as for registration.

## Build plan

- Based on: `main` at `a2f5f2b` (2026-11-19); rechecked on 2026-11-21 against
  `main` at `4c87113` (Context, "Rechecked") and against IMP-007E's Build plan
  Part A in pull request #87. The readiness check (step 4's
  `verify_runtime_inventory`, step 9's `Auth.ready()` and one test row) was revised
  on 2026-11-21 from `main` at `cd68c5e` for IMP-007W.
- Do not claim this ticket until IMP-007E has merged. IMP-007E's new gated text
  waits for the owner's Gate A, so it cannot be built before that approval is on
  `main`. Part B changes the ingestion runtime profile that IMP-007E adds.
- Answered here by the planner (not gated): the state mapping (step 2), the shared
  `register` budget (step 12) and route registration on the ingestion profile only
  (step 13).
- Order: Part A (revision, operator command, backup and restore), then Part B
  (runtime profile at `0005`, route, page), then docs and CI. One pull request.

### Part A: revision `0005_invite_status`

1. `src/kurafolio/persistence/invite_status_schema.py` (new). Constants
   `REVISION = "0005_invite_status"`, `PREDECESSOR = "0004_ingestion"`,
   `SIGNATURES = {"invite_status_v1": ("text",)}` and `FUNCTIONS = 69`. Do not add the
   function to `identity_schema.SIGNATURES` or `GATEWAY`; `identity_schema.function()`
   asserts its parameters against `SIGNATURES`.
   - `guard_replacements()` returns `CREATE OR REPLACE` text for exactly 28 functions:
     the 26 definitions in `ingestion_migration.inherited_guard_replacements()` (their
     `0004` text, which already carries the `0003` budget changes) plus
     `ingestion_schema.user_guard_ddl()` and `worker_guard_ddl()` with the leading
     `CREATE FUNCTION ` changed to `CREATE OR REPLACE FUNCTION ` (once each). In each,
     replace `'0004_ingestion'` with `'0005_invite_status'`. Raise
     `ValueError("Inherited guard provider changed")` unless there are 28 distinct
     `(schema, name)` pairs, each definition holds the old literal exactly once before
     replacement, and the result holds `'0005_invite_status'` 28 times and
     `'0004_ingestion'` 0 times. Start from these renderers, never from
     `identity_schema.ddl()` or `source_schema.ddl()`.
   - `ddl()` returns `guard_replacements()` followed by `invite_status_ddl()`.
2. `wl_identity.invite_status_v1`. Write its own renderer in the new module,
   `invite_status_ddl() -> str` (APP-011E re-guards its text for `0006`); the
   `identity_schema.function()` helper would reject the new name. Use the same
   header shape as its neighbours:
   `CREATE FUNCTION wl_identity.invite_status_v1(p_digest pg_catalog.text) RETURNS
   pg_catalog.jsonb LANGUAGE plpgsql SECURITY DEFINER SET
   search_path=pg_catalog,pg_temp AS $identity$`, a `DECLARE` block with
   `st wl_pg.instance_state%ROWTYPE; a wl_identity.instance_auth_state%ROWTYPE;
   inv wl_identity.invites%ROWTYPE; n pg_catalog.timestamptz;`, then
   `REVOKE ALL ON FUNCTION wl_identity.invite_status_v1(text) FROM PUBLIC;`. Reuse
   `identity_schema` fragments as text: `GUARD` with `'0002_identity'` replaced by
   `'0005_invite_status'` (raise `ValueError` unless it occurs exactly once), `CLOCK`,
   `validated_digest`, `fail` and `success`. Body, in this order:
   1. guard, clock, `validated_digest('p_digest')` (a malformed digest is
      `instance_not_ready`);
   2. `NOT a.bootstrap_closed` → `setup_required`;
   3. `SELECT * INTO inv FROM wl_identity.invites WHERE token_digest=p_digest;` with
      no row lock: the answer is advisory and `register_commit_v1` rechecks under
      `FOR UPDATE`;
   4. no row → `registration_rejected`;
   5. `n<inv.created_at` → `instance_not_ready`;
   6. `inv.status='issued'` and (`inv.incarnation<>st.incarnation` or
      `inv.epoch<>st.restore_epoch`) → `instance_not_ready`. Planner decision: such a
      row exists only after an out-of-band edit (see Context), and
      `admin_read_invites_v1` fails closed on it the same way;
   7. success with `pg_catalog.jsonb_build_object('status', s)` and nothing else,
      where `s` is `expired` when `inv.status='issued' AND n>=inv.expires_at`,
      `usable` for any other `issued` row, and the stored `revoked` or `consumed`
      otherwise. A stored terminal state wins over expiry, as in
      `admin_read_invites_v1`. A consumed or revoked row from an earlier incarnation
      still answers its stored state.

   It writes nothing except the clock row `CLOCK` already updates, and never returns
   IDs, timestamps, usernames, reasons or counts.
3. `src/kurafolio/persistence/migrations/versions/0005_invite_status.py` (new),
   `revision = "0005_invite_status"`, `down_revision = "0004_ingestion"`. As in
   `0004`: require `context.config.attributes["invite_status_operator"]` and raise
   `RuntimeError("Explicit invite status operator transaction required")` without
   it; execute `invite_status_schema.ddl()` with `execution_options={"no_parameters":
   True}`; call an optional `attributes["invite_status_fault"]("after_functions")`.
   `downgrade()` raises `RuntimeError("Destructive invite status downgrade is not
   supported")`.
4. `src/kurafolio/persistence/invite_status_migration.py` (new):
   - `grants(conn, runtime_role, gateway_role, worker_role)`: call
     `ingestion_migration.grants(...)` (it revokes every function from every role
     first), then `GRANT EXECUTE ON FUNCTION wl_identity.invite_status_v1(text)` to
     the gateway role only.
   - `verify_inventory(conn, *, runtime_role, gateway_role, worker_role,
     quarantined=False)`: `alembic_version` must be exactly `["0005_invite_status"]`,
     else `schema_unsupported`; the same namespace check as the `0004` function;
     `migration._identity_target_inventory(conn, "0002_identity",
     extra_functions=(("wl_identity", "invite_status_v1", ("text",)),))`; the sources
     structure digest; `ingestion_migration._structure_digest` equal to the `0004`
     `EXPECTED_STRUCTURE_SHA256`, or `EXPECTED_RESTORED_STRUCTURE_SHA256` when
     quarantined (`0005` adds no relation, column, constraint, index, policy, type or
     trigger, and the digest covers no functions); `verify_functions` and
     `verify_grants` with the extensions in step 5. Return
     `{"schema_revision": "0005_invite_status", "functions": 69}`.
   - `verify_runtime_inventory(conn, *, runtime_role, gateway_role, worker_role)`:
     the runtime-login counterpart, built the way IMP-007W builds the `0004` one.
     Put the checks after the owner lookup in one private body that takes the
     owner, shared with `verify_inventory`. The runtime function takes
     `owner = ingestion_migration._runtime_owner(conn, runtime_role=...,
     gateway_role=..., worker_role=...)` first, before any application table read,
     then makes the same checks with `quarantined=False` and passes `owner=owner`
     to `verify_grants`. It maps `SQLAlchemyError` to `migration_target_invalid`,
     has no quarantined mode and returns the same result. `verify_inventory` keeps
     calling `_operator`.
   - `migrate_invite_status(database, runtime_role, gateway_role, worker_role,
     key_digest, catalog, *, fault=None)`: copy the structure of
     `migrate_ingestion` (key digest and catalog validation, `_checked_roles`, advisory
     lock `1950174004`, an explicit Alembic `Config` whose attributes carry the
     connection, `invite_status_operator=True` and `invite_status_fault=fault`,
     `_source_operator_lock`, the ready, initialized, key and catalog checks). Accept
     `alembic_version` in `([PREDECESSOR], [REVISION])`, else `schema_unsupported`. On
     the predecessor: `ingestion_migration.verify_inventory` must pass, then
     `command.upgrade(configuration, REVISION)`, `grants`, `fault("after_grants")`.
     Always end with the `0005` `verify_inventory` and `fault("before_commit")`, all
     in one transaction. Result: `{"schema_revision": "0005_invite_status",
     "functions": 69, "ready": <wl_ingestion.instance_state.ready is True>}`. A second
     run on `0005` only verifies. Map `SQLAlchemyError` to `migration_target_invalid`
     as `migrate_ingestion` does.
5. Shared verification helpers gain keyword-only parameters whose defaults keep
   today's behaviour byte for byte. Do not change any `0002`, `0003` or `0004` call
   site.
   - `migration._identity_target_inventory(conn, version, *, extra_functions=())`:
     adds the given `(schema, name, types)` entries to `expected_functions`.
   - `ingestion_migration.verify_functions(conn, *, revision=ingestion.REVISION,
     extra=None)`: after today's `0003→0004` body replacement, also replace
     `'0004_ingestion'` with `'<revision>'` in the inherited bodies and in the new
     `wl_ingestion` bodies (only the two guards hold it). `extra` maps
     `(schema, name)` to the expected tuple in the order of `actual` (argument
     names, argument types, `"jsonb"`, body, `True`,
     `("search_path=pg_catalog,pg_temp",)`, `"plpgsql"`, `False`, `"v"`, `"u"`).
     Derive the names and body from the rendered `invite_status_v1` text with the
     same regular expression used for `wl_ingestion` (schema name changed), never
     from the live database. Check a row whose key is in `extra` before the inherited
     lookup, and expect `len(inherited) + len(new) + len(extra)` rows.
   - `ingestion_migration.verify_grants(..., *, extra_gateway=())`: adds
     `(namespace, "function", name, gateway_role, "EXECUTE")` rows before the
     `if quarantined: expected.clear()` line, so a quarantined target still expects
     no grants.
   - `ingestion_migration.verify_inventory` keeps its exact `[0004_ingestion]` check
     and its current calls.
6. Backup and restore, `src/kurafolio/persistence/ingestion_restore.py`. Keep
   `FORMAT` and the `0004` `PROFILE` dictionary unchanged, so existing manifests
   verify. Add a `0005` profile with the same keys (`revision`
   `"0005_invite_status"`, `functions` `"69"`, the same two structure digests).
   `backup_ingestion` reads `alembic_version` inside its read-only snapshot, picks the
   profile and the matching `verify_inventory`, and refuses any other revision with
   `restore_required`. `_manifest` reads `value["revision"]`, selects the profile for
   it and validates every key against that profile; any other revision is
   `restore_required`. `restore_ingestion` calls the selected `verify_inventory`
   (with `quarantined=True`, as today) and returns the selected revision.
7. Operator command `operator migrate-invite-status` (same arguments as
   `migrate-ingestion`): add it to the operation list and to every argument set that
   names `migrate-ingestion` in `web_v2/__main__.py:30-46`, and give it a branch in
   `web_v2/operator.py` shaped like the `migrate-ingestion` branch (lines 136-150).
   `backup-ingestion` and `restore-ingestion` keep their names and arguments.
8. `migrate_ingestion` is not changed: it stops at `0004`, and on a `0005` database
   it still answers `schema_unsupported`.

### Part B: runtime profile at `0005`, route and page

9. The ingestion runtime profile, as IMP-007E merged it. First check that the merged
   code matches the interfaces listed in Context ("Rechecked"): the `"ingestion"`
   literal in `Database.__init__` and its unit test, `IdentityStore`, `SourceStore`
   and `IngestionStore` opening `Database(..., schema_mode="ingestion")`,
   `role_inventory`, `Settings.worker_role`, both `--schema-profile` choices,
   `Auth.__init__`, `Auth.ready`, `Boundary` and `create_app`. If one is missing,
   pins a second revision, or has another shape, set the ticket `blocked` and ask
   for a plan refresh; do not choose new interfaces. Then:
   - `src/kurafolio/persistence/context.py`: in `Database.__init__`, change the
     `"ingestion"` value from `"0004_ingestion"` to `"0005_invite_status"`. Keep it a
     literal; do not import `invite_status_schema` there, because it imports the
     ingestion schema module that IMP-007E keeps out of `context.py`. Change
     IMP-007E's unit test for that literal to compare it with
     `invite_status_schema.REVISION` instead of `ingestion_schema.REVISION`. This is
     the only change to what an IMP-007E test asserts about the revision, apart from
     the `/readyz` case below.
   - `src/kurafolio/web_v2/auth.py`: in `Auth.ready()` on `ingestion`, replace
     `ingestion_migration.verify_runtime_inventory(...)` with
     `invite_status_migration.verify_runtime_inventory(conn, runtime_role=runtime_role,
     gateway_role=gateway_role, worker_role=self.settings.worker_role)`. Keep the
     realm comparison and the `wl_sources.catalog_state` digest check. Never call
     an operator `verify_inventory` from the API.
   - `src/kurafolio/persistence/identity.py`, `role_inventory`: when
     `database.schema_mode == "ingestion"`, expect exactly 23 `wl_identity`
     functions named `set(SIGNATURES) | set(invite_status_schema.SIGNATURES)`, and
     gateway `EXECUTE` on exactly `GATEWAY` plus `invite_status_v1`. The `identity`
     and `sources` branches stay at 22 and `GATEWAY`. Keep IMP-007E's
     `source_role_inventory` call on `ingestion`.
   - No change to `Settings`, `--worker-role`, the `--schema-profile` choices,
     `SourceStore` or `IngestionStore`: they take the revision from `Database`. The
     operator's `setup`, `invite`, `account` and `identity status` on
     `--schema-profile ingestion` then need a `0005` database.
   - Test helpers: find every test that builds an ingestion-profile target (search
     `tests/` for `schema_profile='ingestion'`, `schema_profile="ingestion"` and
     `schema_mode="ingestion"`). At least the environment builder in
     `tests/test_postgres_import_routes.py` (IMP-007E), and
     `tests/ingestion_pg_support.py` if it builds served targets, run
     `migrate_invite_status` after `migrate_ingestion`. The test-only activation
     helper is unchanged, because `0005` touches only functions.
   - IMP-007E's case "`/readyz` on a migrated `0004` instance → 200" runs on the
     `0005` target instead. Add a case to the HTTP class of
     `tests/test_invite_status_postgres.py` (not to IMP-007E's file, so no skip
     count changes): a database left at
     `0004_ingestion`, served on `ingestion`, is refused: `Auth(settings)` raises
     `IdentityError`, because `Auth.__init__` calls `ready()` and
     `IdentityStore.status` refuses a `schema_revision` other than
     `self.database.revision`. Its extra-grant case keeps its 503.
10. `IdentityStore`: on the ingestion profile, `call()` accepts names from
    `SIGNATURES | invite_status_schema.SIGNATURES` (casts from the same table);
    elsewhere it stays as today. Add `IdentityStore.invite_status(token_digest) ->
    str`, which calls `invite_status_v1` and raises `IdentityError()` unless the
    value is exactly `{"status": s}` with `s` one of the four answers.
11. `web_v2/schemas.py`: `InvitationStatusRequest(Closed)` with `invite_token: Token`;
    `InvitationStatus(Closed)` with `status: Literal['usable','expired','revoked',
    'consumed']`. No new error code: `registration_rejected`, `setup_required`,
    `rate_limited` and `instance_not_ready` are already in `ERROR_CODES`.
12. `web_v2/auth.py`: `Auth.invite_status(body, peer)` runs
    `self.budget('register', peer)` and then
    `self.store.invite_status(digest(body.invite_token))`, returning
    `{"status": ...}`. Planner decision: the check shares the `register` budget (5 per
    peer and 20 per instance per 900 seconds), which is the literal reading of
    "budgets apply as for registration" and needs no change to `consume_budget_v1`. A
    page load and one submit cost two of the five attempts.
13. `web_v2/api.py`: `POST /api/v2/auth/invitation-status`, registered in the
    `Boundary` route table and in `create_app` only on the ingestion profile, the way
    `SOURCE_ROUTES` exist only on `sources`. On `identity` and `sources` it is 404
    `not_found` (the boundary answers before origin and CSRF checks) and absent from
    `/api/v2/openapi.json`. Add the path to `ANONYMOUS`: it needs the anonymous
    cookie, the exact `Origin` and CSRF, and refuses a signed-in caller with
    `anonymous_session_required`. Body as in step 11; a query string is 422. 200
    `{"status": ...}`; an unknown token is 400 `registration_rejected`. The cookie is
    not cleared.
14. `frontend/src/v2/api.ts`: add `/auth/invitation-status` to `anonymous` (not to
    `cookieResets`), so a lapsed anonymous session is renewed once as for register;
    export `type InvitationStatus = "usable" | "expired" | "revoked" | "consumed"`.
15. `frontend/src/v2/auth-pages.tsx`, `CredentialsPage`. Only `kind === "register"`
    with a token and no signed-in user runs the check; the setup page is unchanged.
    - Add the check's state and its effect above the `if (shown)` early return, so
      hooks keep their order. Start the check once per page: a ref guards against
      StrictMode's second effect, and an answer that arrives after unmount is
      ignored. Call `mutate<{ status: InvitationStatus }>("/auth/invitation-status",
      { invite_token: token })`; `mutate` fetches the CSRF token first, which creates
      the anonymous session that the register submit then reuses.
    - Extend `Blocked` with `"expired" | "revoked" | "consumed"`. Register maps them
      to the `wlP0011i.register.*` keys below; setup maps them to
      `"wlP0011b.failed"` (unreachable). The existing blocked view then shows the
      message as an alert, a link to sign-in and no form.

    | Answer | Page |
    |---|---|
    | Still waiting | The title and `<p role="status">{t("loading")}</p>`; no form |
    | `usable` | The form |
    | `expired`, `revoked`, `consumed` | `setBlocked(answer)`: its own message, sign-in link, no form |
    | 404 `not_found` (`identity`/`sources`) | The form and today's behaviour, including the combined `wlP0011b.register.rejected` after submit; no alert before submit |
    | 400 `registration_rejected` (unknown token) | `setBlocked("missing")`: `wlP0011b.register.missing`, no form |
    | 409 `setup_required` | `setBlocked("setupRequired")`: `wlP0011b.register.setupRequired`, no form |
    | Anything else (429, 503, 403, network) | `failureMessage(error)` as an alert and a `t("retry")` button that runs the check again; no form |

    After a `usable` answer, a submit that returns `registration_rejected` sets
    `problems.username` to `wlP0011i.username.taken`, shows no alert, keeps the form
    and focuses the username field. Known limit, accepted by the product review
    note: an invitation that expires between the check and the submit also shows
    this message. Other submit errors behave as today.
16. Locale keys in `frontend/src/locales/en-CA.json`, `zh-TW.json` and `zh-CN.json`,
    following [i18n-plan.md](../docs/i18n-plan.md). "Revoked" matches the existing
    invitee and administrator wording.

    | Key | en-CA |
    |---|---|
    | `wlP0011i.register.expired` | This invitation has expired. Ask the person who invited you for a new one. |
    | `wlP0011i.register.revoked` | This invitation was revoked. Ask the person who invited you for a new one. |
    | `wlP0011i.register.consumed` | This invitation was already used to create an account. Sign in with that account. |
    | `wlP0011i.username.taken` | This username is not available. Choose a different one. |

    Translate each text into zh-TW and zh-CN with no new terms: take the words for
    "invitation", "expired", "revoked", "used" and "ask the person who invited you
    for a new one" from each catalog's `wlP0011b.register.rejected`; "account" and
    "create" from `wlP0011b.register.title`; "sign in" from `wlP0011b.goToSignIn`;
    and "username" from `username`. Tickets carry English only
    (`scripts/check_language.py`), so the translations live only in the catalogs.

17. Docs, all required:
    - [web-v2-identity.md](../docs/web-v2-identity.md): the route in the HTTP
      contract, its four answers and errors, the shared `register` budget, and the
      fallback on `identity`/`sources`;
    - [web-v2-imports.md](../docs/web-v2-imports.md): `migrate-invite-status`,
      backup and restore at `0005`, and that the ingestion profile needs `0005`;
    - [web-frontend.md](../docs/web-frontend.md): replace the paragraph at line 77
      ("The registration API answers ...") with the page states above;
    - [capability-status.md](../docs/capability-status.md): the "Optional V2
      identity" row (line 23) names APP-011I; say what now works and that it needs
      the ingestion profile.
    - In web-v2-imports.md, give the operator order for an ingestion instance:
      `migrate-ingestion`, then `migrate-invite-status`, then `serve
      --schema-profile ingestion`.
18. ANL-008's revision list. If `src/kurafolio/projection/accepted.py` exists on
    `main` when this ticket is built (ANL-008 merged), first confirm that `0005`
    leaves the twelve `ingestion_schema.READ_TABLES`, `wl_pg.accounts`,
    `wl_pg.instruments` and the runtime role's grants unchanged (Context explains
    why it should), then append `"0005_invite_status"` after `"0004_ingestion"` in
    its `SUPPORTED_REVISIONS` tuple. Its guard test in
    `tests/test_projection_positions.py` then passes. Change nothing else in that
    file. If the file does not exist, do nothing; ANL-008's builder adds `0005`.
    If the confirmation fails, stop and ask.
19. CI, `.github/workflows/ci.yml`. No job runs `tests/test_invite_status_postgres.py`
    today, because the file matches neither `test_postgres_migration.py` nor
    `test_postgres_*.py`. Add a step to the `postgres-ingestion` job, after the
    step that runs `test_postgres_migration.py`:
    `PYTHONPATH=src python scripts/run_gated_tests.py --expect-skipped 0 -- discover
    -s tests -p 'test_invite_status_postgres.py'`. That job needs FastAPI for the
    HTTP class; IMP-007E installs `requirements-web-test.lock` there. Because the
    name does not match `test_postgres_*.py`, the `postgres-foundation` skip count
    does not change. This ticket adds no test to a `test_postgres_*.py` file; if
    it must, raise the `postgres-foundation` `--expect-skipped` value on `main` at
    build time by their number and update its comment.

### Interfaces

- SQL: `wl_identity.invite_status_v1(text) → jsonb`, returning
  `{"ok":true,"value":{"status":"usable"|"expired"|"revoked"|"consumed"}}` or
  `{"ok":false,"code":"instance_not_ready"|"setup_required"|"registration_rejected"}`.
  Gateway role only.
- HTTP: `POST /api/v2/auth/invitation-status`, body `{"invite_token": "<43 base64url
  characters>"}`, 200 `{"status": ...}`; errors use the existing envelope and codes.
- Python: `invite_status_schema.{REVISION, PREDECESSOR, SIGNATURES, FUNCTIONS,
  guard_replacements(), invite_status_ddl(), ddl()}`; `invite_status_migration.{grants, verify_inventory,
  migrate_invite_status}`; `IdentityStore.invite_status(token_digest) → str`;
  `Auth.invite_status(body, peer) → dict`.
- Browser: `InvitationStatus` in `frontend/src/v2/api.ts`; four `wlP0011i.*` keys.

### Tests and expected values

Independent values, taken from the merged code rather than the new code: an
invitation lasts exactly 86,400 seconds (`invites` CHECK); `register` allows 5
attempts per peer and 20 per instance in 900 seconds; `0004` has 68 functions, so
`0005` has 69; `wl_identity` has 22 functions on `0004` and 23 on `0005`; the gateway
can execute 15 `wl_identity` functions on `0004` and 16 on `0005`; 28 functions carry
the revision literal. Name the acceptance ID in each test.

Unit tests, `tests/test_invite_status_schema.py` (new, no database):

| AC | Case | Expected |
|---|---|---|
| 02 | Render `identity_schema.ddl()`, `source_schema.ddl()`, `ingestion_migration.function_ddl()` and `inherited_guard_replacements()` before and after importing the new module | Byte-identical; the existing frozen-text tests still pass unchanged |
| 04 | `guard_replacements()` | 28 definitions, 28 × `'0005_invite_status'`, 0 × `'0004_ingestion'`; each equals its `0004` text with only that literal and the `CREATE OR REPLACE` prefix changed |
| 04 | A predecessor text with the literal removed from one function (patched) | `ValueError` |
| 04 | `invite_status_v1` text | Holds `'0005_invite_status'` once; the only success value is `jsonb_build_object('status',...)`; no `inv.id`, `expires_at`, `created_at`, `username` or `revocation_reason` in a returned object |

PostgreSQL tests, `tests/test_invite_status_postgres.py` (new; opt-in with
`KURAFOLIO_INGESTION_TEST=1`). Build each `0004` target as
`IngestionProviderPostgresTests` does (`scripts/postgres.py
test-identity-environment`, `migrate_sources`, the seeded administrator,
`migrate_ingestion`), then `migrate_invite_status`. Pin the clock with the
operator's `_clock_timestamp_v1` replacement (`tests/test_identity_support.py:99`)
and only move it forward: `CLOCK` refuses a time earlier than `last_observed_at`. Use
a new target where a case needs an earlier time. `verify_functions` compares the
clock function's body too, so restore it (`test_identity_support.py:105`) before any
`verify_inventory`, `migrate_invite_status` or backup, or keep those cases on
unpinned targets. Call `invite_status_v1` as the gateway role.

| AC | Case | Expected |
|---|---|---|
| 01 | Invite issued at T, checked at T+86,399.999999 s | `usable` |
| 01 | Same invite at T+86,400 s | `expired` |
| 01 | Invite revoked at T+1 s, checked at T+86,401 s | `revoked` |
| 01 | Invite consumed by `register_commit_v1`, checked at T+90,000 s | `consumed` |
| 01 | A consumed invite whose `incarnation` the operator changed | `consumed` |
| 03 | Usable invite; `register_commit_v1` with a taken username | `registration_rejected`; `invite_status_v1` still `usable` |
| 04 | Unknown well-formed digest; a second unknown digest | `registration_rejected`, identical results |
| 04 | Malformed digest (`'x'`, 63 hex characters, uppercase hex) | `instance_not_ready` |
| 04 | `issued` invite whose `incarnation` the operator changed | `instance_not_ready` |
| 04 | `bootstrap_closed=false, admin_user_id=NULL` set by the operator | `setup_required` |
| 04 | `alembic_version` set to `0004_ingestion` in a rolled-back nested transaction | `invite_status_v1`, `register_commit_v1`, `sources_catalog_v1` and `_guard_user_v1` answer `instance_not_ready` |
| 04 | Gateway, runtime, worker and PUBLIC privileges | Only the gateway can execute `invite_status_v1` |
| 04 | `verify_inventory` after `GRANT EXECUTE ... TO PUBLIC`, after `ALTER FUNCTION ... RESET search_path`, after replacing its body | `migration_target_invalid` each time |
| 04 | Fresh `0005` target | `verify_inventory` gives 69 functions; `_structure_digest` equals the `0004` `EXPECTED_STRUCTURE_SHA256` |
| 04 | Fresh `0005` target through the runtime role's login | `verify_runtime_inventory` gives the same result as the operator's `verify_inventory`; `verify_inventory` raises `migration_role_required`; after `GRANT EXECUTE ON FUNCTION wl_identity.invite_status_v1(text) TO PUBLIC` (committed, then reverted), `migration_target_invalid` |
| 02 | `migrate_invite_status` on `0002` and `0003` targets | `schema_unsupported`; the target is unchanged |
| 02 | `migrate_invite_status` with `fault` raising at `after_grants` | Still `0004_ingestion`, no `invite_status_v1`, the `0004` `verify_inventory` passes |
| 02 | A second `migrate_invite_status`; `migrate_ingestion` on `0005` | The same result; `schema_unsupported` |
| 02 | `operator migrate-invite-status` through `python -m kurafolio.web_v2` | Prints `{"schema_revision": "0005_invite_status", "functions": 69, "ready": false}` |
| 04 | `backup-ingestion` on `0005`, `restore-ingestion` into an empty target | Manifest `revision` `"0005_invite_status"`, `functions` `"69"`; restore returns `0005_invite_status`, quarantined; issued invites revoked with reason `restore` |
| 04 | A `0004` backup still restores; a `0004` manifest edited to say `0005` | `0004_ingestion`, quarantined; `restore_required` |

HTTP tests: ingestion-profile cases go in a second class in
`tests/test_invite_status_postgres.py`. It builds and activates its target with
the environment helpers of `tests/test_postgres_import_routes.py` (or
`tests/ingestion_pg_support.py` if IMP-007E put them there), which step 9 extends
with `migrate_invite_status`, and serves `create_app` on `ingestion` with
`worker_role`. Import those helpers; do not copy them. `identity` cases go in
`tests/test_web_v2_api.py` and `sources` cases in `tests/test_web_v2_sources.py`.
Use real targets; a different peer is `TestClient(..., client=('127.0.0.2', 1234))`.

| AC | Case | Expected |
|---|---|---|
| 01 | Status of usable, expired, revoked and consumed tokens | 200; body exactly `{"status": ...}` |
| 01 | A database left at `0004_ingestion`, settings on `ingestion` (step 9) | `Auth(settings)` raises `IdentityError`; the same target after `migrate_invite_status` is served and `/readyz` is 200 |
| 02 | `identity` and `sources` profiles | Route 404 `not_found`, absent from `/api/v2/openapi.json`; register still answers `registration_rejected` for an inactive invite and for a taken username |
| 03 | Usable token, register with a taken username | 400 `registration_rejected`; status still `usable` |
| 04 | Unknown token | 400 `registration_rejected`; two unknown tokens give the same body apart from `request_id` |
| 04 | Signed-in caller; missing CSRF; wrong `Origin`; extra body field; query string | 403 `anonymous_session_required`; 403 `csrf_rejected`; 403 `origin_rejected`; 422; 422 |
| 04 | Five checks from one peer, then a check and a register from it | Sixth and seventh 429 `rate_limited`; a different peer still gets an answer |
| 04 | Four checks and one register from one peer, then a check | 429 `rate_limited` (shared budget) |

Browser tests, `frontend/tests/browser/v2-identity.spec.ts`. Give the fake an
`inviteStatus` option (one of the four answers, or `{ status, code }` for an error).
When it is unset, answer `POST /auth/invitation-status` with 404 `not_found` before
the CSRF check and before recording the body, as the server answers an unknown path
before origin and CSRF (`api.py:181-191`). The existing tests, including
`accepted.bodies[0]`, then pass unchanged and keep covering AC-02. Unit tests for any
mapping you extract go in `frontend/tests/v2-identity.test.ts`.

| AC | Case | Expected |
|---|---|---|
| 01 | `expired`, `revoked`, `consumed` | Each English text above in an alert, no textbox, a sign-in link; axe passes |
| 01 | The three answers in zh-TW and zh-CN, dark mode and phone width (extend the locale test) | Translated text, no textbox, no wire code on the page |
| 02 | No `inviteStatus` (404) | Form shown, no alert before submit; after `registration_rejected` the combined message, as today |
| 03 | `usable`, then `registration_rejected` on submit | The username field's description is the taken message; the form stays; focus on the username field; no alert |
| 03 | `usable`, then success | Signed-in flow as today; requests in order: check, then register |
| 04 | `registration_rejected` from the check; `setup_required`; `rate_limited` then retry to `usable` | The missing-link message, no form; the set-up message, no form; the rate message and a retry button, then the form |
| 04 | Request log | Exactly one `POST /auth/invitation-status` per page load; the token appears only in request bodies, never in a URL or browser storage |

Verify: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`;
`KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s
tests -p 'test_invite_status_postgres.py' -v` and the same for
`test_postgres_migration.py`; the identity HTTP suite with `KURAFOLIO_IDENTITY_TEST=1`
as [web-v2-identity.md](../docs/web-v2-identity.md) describes; IMP-007E's
`KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s
tests -p 'test_postgres_import_routes.py' -v` with `requirements-web-test.lock`
installed; when ANL-008 has merged, `PYTHONPATH=src .venv/bin/python -m unittest
tests.test_projection_positions -v`; `npm --prefix frontend test`,
`npm --prefix frontend run check:source` and `npm --prefix frontend run test:e2e` with
`KURAFOLIO_E2E_PORT` from the claim. A skipped PostgreSQL test is not acceptance.

### Rollback

- `0005` is one operator transaction; any failure leaves `0004` intact (tested
  above). There is no downgrade, as for `0004`. Take `backup-ingestion` before
  migrating; to go back, restore that `0004` backup into a new empty database.
- Reverting the code leaves `0005` databases unreadable by the old code, which
  refuses a newer revision. Only synthetic ingestion targets exist today, because the
  profile is not operational.
- `identity` and `sources` instances get no schema change; reverting the page returns
  them to today's behaviour.

### Do not touch

- The text of `identity_schema.py`, `source_schema.py`, `ingestion_schema.py`, the
  `0001` to `0004` migration files, and every frozen hash (`EXPECTED_*_SHA256`, the
  `known` hashes in `_identity_target_inventory`, the `0004` restore `PROFILE`).
- `register_commit_v1`, `consume_budget_v1` and the meaning of
  `registration_rejected`.
- The setup page, the invitation management page, the sources routes, and the
  ingestion profile's other routes and surfaces beyond steps 9 to 13. In
  IMP-007E's files, change only what step 9 names: the `"ingestion"` literal in
  `context.py` and its unit test, the `Auth.ready()` call, the `role_inventory`
  branch, the test environment builders and the `/readyz` cases. The import
  routes, `IngestionStore`, `Settings.worker_role` and the CLI flags stay as
  IMP-007E left them.
- In `src/kurafolio/projection/accepted.py` (ANL-008), only the
  `SUPPORTED_REVISIONS` tuple, and only as step 18 says.
- In `.github/workflows/ci.yml`, only the `postgres-ingestion` step of step 19.
- IMP-007S's files and its activation command, if they have merged; see Stop and
  ask.
- Revision numbers after `0005`: APP-011E's preferences revision `0006` comes after
  this one (owner, 2026-11-20) and must re-guard the 29 functions `0005` leaves
  guarded.

### Stop and ask if

- IMP-007E has not merged.
- IMP-007W's `ingestion_migration._runtime_owner` or the keyword-only `owner` on
  `_checked_roles` and `verify_grants` has another name or signature on `main`
  than step 4 uses.
- The merged ingestion profile misses a surface listed in step 9, pins more than one
  revision, or has a shape steps 9 to 13 do not describe. Set the ticket `blocked`
  and ask for a plan refresh.
- IMP-007S has merged and its activation command refuses a `0005` database, or
  checks `0004_ingestion` exactly. Do not change IMP-007S's code; set the ticket
  `blocked` and ask.
- ANL-008 has merged and step 18's confirmation fails.
- Any `0004` count differs from this plan (28 guarded functions, 68 functions), or
  `_structure_digest` on a fresh `0005` target differs from the `0004` value.
- Another revision `0005` exists on `main`.
- Meeting a criterion would need an edit to `0002`, `0003` or `0004` DDL text or a
  frozen hash, a change to `register_commit_v1`, or a new public error code.
- Selecting a restore profile would change the bytes of a `0004` manifest.
- A merged test other than those step 9 names asserts that the ingestion runtime
  revision is `0004_ingestion`; ask before changing what it asserts.

## Plan

- [x] Record the owner decision.
- [x] Decide where the new SQL function lands (AUTH-101).
- [x] Write the Build plan from `main` at `a2f5f2b`.
- [x] Owner answers Decision 1 and confirms the change to `depends_on` in the Log
  (2026-11-20).
- [x] Recheck the Build plan against `main` at `4c87113` and IMP-007E's Part A.
- [ ] Wait for IMP-007E to merge.
- [ ] Part A: revision `0005_invite_status`, operator command, backup and restore, with
  unit and PostgreSQL tests.
- [ ] Part B: ingestion runtime profile at `0005`, route, registration page states,
  locale keys, HTTP and browser tests.
- [ ] Docs: web-v2-identity.md, web-v2-imports.md, web-frontend.md, capability-status.md.
- [ ] ANL-008's `SUPPORTED_REVISIONS` if it has merged; CI step for
  `test_invite_status_postgres.py`.

## Decisions needed

The migration path was decided in AUTH-101 on 2026-11-12 (option (b), revision
`0005_invite_status`). Item 1 was answered by the owner on 2026-11-20 and is kept
here as the record. No question is open.

1. **Answered 2026-11-20: option (a), with IMP-007E.** Asked "Which ticket builds
   the ingestion runtime profile?", the owner chose "IMP-007E (Recommended)": its
   approved r7 scope already covers it; IMP-007E adds the `identity-api` resource;
   APP-011I and APP-011E add IMP-007E to `depends_on`. IMP-007E's plan (pull
   request #87) builds the profile as its Part A. `depends_on` now lists IMP-007E,
   and Build plan step 9 moves the profile to `0005`. In the same conversation the
   owner raised this ticket to P0 ("Raise APP-011I to P0 (Recommended)"), so that
   APP-011E's `0006` can follow it. The options as asked:

   Which ticket gives APP-011I an ingestion runtime profile? `0005` reaches only
   ingestion-profile instances (AUTH-101), and no runtime profile can serve `0004` or
   `0005` on `main` (Context). IMP-007E's routes need the same profile, but no
   ticket's text assigns the work to build it.
   - (a) The profile arrives with IMP-007E, or with a ticket the owner files for it,
     and APP-011I adds that ticket to `depends_on`. APP-011I then moves the profile
     from `0004` to `0005` (Build plan step 9) and builds everything in one pull
     request after that ticket merges. Changing `depends_on` of this approved ticket
     needs the owner's confirmation in its Log. IMP-007E is P0 and APP-011I is P1,
     so this keeps the existing order.
   - (b) APP-011I builds a minimal ingestion profile itself (the surfaces listed in
     Context). This overlaps the profile IMP-007E needs, may fix interfaces before
     the import routes are designed, and puts profile plumbing in a scope that the
     approved Requirements do not list, so Requirements would change and need a new
     approval.
   - (c) Split: APP-011I keeps Part A and the page with its 404 fallback, and a new
     follow-up ticket adds the route and profile wiring after the profile exists.
     AC-01, AC-03 and AC-04 could then not be met on a real instance in this ticket,
     so the gated Requirements and Acceptance criteria would change and need a new
     approval. Until the follow-up merges, every instance keeps today's behaviour.

   Recommendation: (a), with IMP-007E as the named ticket, and a note in IMP-007E's
   Build plan (by its planner) that it builds the ingestion runtime profile across
   the surfaces listed in this ticket's Context.

## Handoff

- State: Not started. No code written. The Build plan is complete and records the
  owner's answers of 2026-11-20. The build waits for IMP-007E, which supplies the
  ingestion runtime profile. IMP-007E itself waits for the owner's Gate A on its
  new gated text (pull request #87), so it cannot be built yet.
- Next step: After IMP-007E has merged, run `git fetch origin` and
  `python3 scripts/tickets.py spec APP-011I`. Then check the merged profile against
  Build plan step 9 before writing Part A. Start with
  `src/kurafolio/persistence/invite_status_schema.py` and its unit tests.
- Verify: the commands under "Tests and expected values" in the Build plan.
- Gotchas:
  - `identity-api` is shared with IMP-007E and IMP-007U. Only one of them builds at
    a time; `claim` refuses while another holds it. APP-011E shares
    `migration-order` and `postgres-schema` with this ticket and is ordered after it
    by `depends_on`; it would also hold `identity-api` only if the owner answers its
    Decision 3 with (a).
  - APP-011E's `0006_user_preferences` follows `0005` (owner, 2026-11-20). Do not
    take `0006`.
  - IMP-007S's draft AC-03 (pull request #87, not approved) refuses an inventory
    other than `0004`. If IMP-007S merges first with that rule, activation refuses
    a `0005` instance; Stop and ask covers it.
  - ANL-008 may merge before this build. If it has, step 18 applies, and its
    `tests/test_projection_positions.py` fails until `0005_invite_status` is added.
- Open questions: none.

## Log

- 2026-11-12 claude-code/opus-5.5: filed from APP-011B, which could not meet its inactive-invitation criterion with the current API.
- 2026-11-12 claude-code/opus-5.5: added notes from the APP-011B product review.
- 2026-11-12 claude-code/opus-5.5: recorded the owner decision: option 1, priority P1; released (status ready, waits on APP-011B).
- 2026-11-12 claude-code/opus-5.5: claimed; found that the identity schema is a frozen provider, so the new function needs a migration decision. Owner chose to pause; filed AUTH-101 and set status blocked.
- 2026-11-12 claude-code/opus-5.5: AUTH-101 decided (option (b), revision `0005_invite_status`); added the migration path to Handoff, depends on IMP-007D, status ready.
- 2026-11-12 claude-code/opus-5.5: added AUTH-101 review findings (replacement baseline, profile plumbing, budget trade-off, state mapping) and the owner's fallback for `identity`/`sources` instances.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved "Expected behaviour", "Owner decision recorded 2026-11-12" and "Scope" from Context into Requirements and numbered the acceptance criteria AC-APP-011I-01 to 04. Spec hash sha256:4b2a286b772f4c5edbdde50b081fafbaa69205f535dda1002a55419cc2fa13af, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:4b2a286b772f4c5edbdde50b081fafbaa69205f535dda1002a55419cc2fa13af.
- 2026-11-19 claude-code/opus-5.5: wrote the Build plan from `main` at `a2f5f2b` in plan PR https://github.com/gh-slee/kurafolio/pull/82, finishing and correcting an unreviewed draft; added Decision 1 (which ticket supplies the ingestion runtime profile). Do not claim until it is answered.
- 2026-11-21 claude-code/opus-5.5: added IMP-007E to `depends_on`. The owner confirmed it on 2026-11-20: asked "Which ticket builds the ingestion runtime profile?", they chose "IMP-007E (Recommended)": "its approved r7 scope already covers it; IMP-007E adds the `identity-api` resource; APP-011I and APP-011E add IMP-007E to depends_on." This answers Decision 1 with option (a).
- 2026-11-21 claude-code/opus-5.5: raised `priority` from P1 to P0. Asked how APP-011E's revision 0006 should follow this ticket's 0005, the owner chose on 2026-11-20 "Raise APP-011I to P0 (Recommended)": "keep 0005 invite status, 0006 preferences; APP-011E depends on APP-011I and the profile ticket (IMP-007E)." `gate_approval` and the gated Requirements still record the 2026-11-12 choice of P1 as history; neither was edited.
- 2026-11-21 claude-code/opus-5.5: updated the plan in plan pull request https://github.com/gh-slee/kurafolio/pull/82. Rechecked against `main` at `4c87113` and against IMP-007E's Part A in pull request #87; step 9 now names IMP-007E's interfaces (the `"ingestion"` literal in `Database.__init__` and its unit test, `Auth.ready()`'s `verify_inventory` call, `role_inventory`, the test environment builders and the `/readyz` cases). Added step 18 (ANL-008's `SUPPORTED_REVISIONS`) and step 19 (a CI step for the new PostgreSQL test file), recorded Decision 1 as answered, and rewrote Handoff. Goal, Requirements and Acceptance criteria unchanged.
- 2026-11-21 claude-code/opus-5.5: revised the readiness check in the Build plan for IMP-007W in plan pull request https://github.com/gh-slee/kurafolio/pull/93 (filed from IMP-007E Decisions needed item 7, owner answer "New prerequisite ticket"). The operator `verify_inventory` needs database CREATE, which no application role has from `0004` on, so step 4 adds `invite_status_migration.verify_runtime_inventory` on IMP-007W's `_runtime_owner` and `owner` keyword, step 9's `Auth.ready()` calls it, and a test row covers it. Gated sections and `depends_on` unchanged; IMP-007E now depends on IMP-007W.
