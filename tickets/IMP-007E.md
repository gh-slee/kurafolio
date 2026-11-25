---
id: IMP-007E
title: Add authenticated V2 import HTTP routes
priority: P0
status: in_progress
type: feature
parent: IMP-007
depends_on: [IMP-007D, IMP-007J, IMP-007W]
resources: [v2-import-routes, identity-api]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-10-31, IMP-007 spec r7 (covers all child tickets); owner 2026-11-21, IMP-007E text after the upload split (Q13)"
review: independent
branch: ticket/imp-007e-add-authenticated-v2-import-http-routes
pr: https://github.com/gh-slee/kurafolio/pull/115
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c
updated: 2026-11-24
---

# IMP-007E: Add authenticated V2 import HTTP routes

## Goal

Add the `ingestion` runtime profile and expose create, read, decide, accept and cancel through authenticated FastAPI routes on it, with CSRF/origin checks. The bounded upload route is IMP-007U.

## Context

- Pattern: `tests/test_web_v2_sources.py` and [web-v2-sources.md](../docs/web-v2-sources.md).
- Background only: the revision 1 planning draft [docs/specs/v2-drafts/WL-P0-007.md](../docs/specs/v2-drafts/WL-P0-007.md) (sha256:fa0971a0da787cb327484c92144e4a5ecd916db4ad0328e03b408d647190acd5), which the r7 bundle supersedes.
- On 2026-11-20 the owner moved the upload route and its acceptance criteria to IMP-007U, which depends on this ticket and on IMP-007O (Decisions needed, item 6). Activation of an instance is IMP-007S (item 4).

### Where to start

- SQL fragments and the function inventory: `src/kurafolio/persistence/ingestion_schema.py`. Existing providers and operator commands: `src/kurafolio/persistence/migration.py`, `source_migration.py`, `migrations/`, `scripts/postgres.py`.
- Python reference checks and DTO codecs: `src/kurafolio/ingestion/` (`approval.py`, `codec.py`, `contracts.py`, `cursors.py`, `reconciliation.py`).
- V2 HTTP application and DTO style: `src/kurafolio/web_v2/api.py`, `web_v2/schemas.py`.
- Tests to extend: `tests/test_postgres_migration.py`, `tests/test_ingestion_*.py`, `tests/test_web_v2_api.py`, `tests/test_web_v2_sources.py`; vectors in `tests/fixtures/ingestion/oracle.json`.
- Public status and boundaries: [web-v2-imports.md](../docs/web-v2-imports.md). Product intent: [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md).

### Findings from the merged code (`main` at `a2f5f2b`)

No file under `src/`, `tests/`, `docs/` or `scripts/` changed between `a2f5f2b` and `main` at `d902717`, so these findings still hold.

- Both dependencies are merged: IMP-007D (`done`, the operator `0004_ingestion` migration and its grants) and IMP-007J (`done`, the granted `admit_rate_v1` gateway function).
- No runtime profile on `main` can serve a `0004_ingestion` database. Every layer accepts only `identity` and `sources`:
  - `Database` (`persistence/context.py:47`) maps only `foundation`, `identity` and `sources` to a revision. The principal check in `_transaction` (`:114`) and `RequestDatabase.__post_init__` (`:154`) accept only `identity` and `sources`.
  - `IdentityStore.__init__` (`persistence/identity.py:104`) accepts only those two profiles, and `role_inventory` runs the source check only for `sources`.
  - `SourceStore.__init__` (`persistence/source_store.py:14`) always opens `schema_mode="sources"`.
  - `Settings.__post_init__` (`web_v2/config.py:49`) and `from_files` accept only those two. So do `serve --schema-profile` (`web_v2/__main__.py:21`) and the operator `--schema-profile` (`:36`).
  - `Auth.__init__` and `Auth.ready` (`web_v2/auth.py:58-106`) build and verify only the `sources` stores.
  - Route gating in `Boundary.request` (`web_v2/api.py:185`) and route registration in `create_app` (`:416`) test `== 'sources'`.
- The r7 bundle, which Requirements adopt, already asks for that branch: [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), "Profile integration and readiness", says to add an explicit ingestion branch in `identity.py`, `source_store.py`, `Database`, Auth and config. IMP-007D built only the operator side. The owner assigned the profile to this ticket on 2026-11-20 (Decisions needed, item 1).
- Nothing on `main` activates the ingestion profile on a database.
  - `migrate_ingestion` leaves `wl_ingestion.instance_state.ready` false. No code writes `wrapper_catalog_bytes`, `wrapper_catalog_digest` or `runtime_profile_digest`, sets `ready`, or adds an enabled `wl_ingestion.workers` row.
  - Until that happens, `_guard_user_v1` answers `instance_not_ready`, and `create_set_v1` fails, because it parses the wrapper catalog.
  - The runtime role cannot read `wl_ingestion.instance_state` (it is not in `READ_TABLES`), so `/readyz` cannot see that flag.
  - IMP-007S builds activation (Decisions needed, item 4). This ticket's tests activate their synthetic database through a test-only helper.
- The upload findings (the member context bytes the hand-off frame needs, `expected_set_revision` on a `RAW_BINARY` request, the Boundary's JSON body read, the worker's hand-off answers) moved to IMP-007U with the route.
- `web_v2/schemas.py` `ERROR_CODES` has no `import_*` code and no `length_required`. `error_response` (`api.py:57`) turns any code outside that list into `instance_not_ready` (503).
- `wire-contracts.json` `error_status` lists 13 `import_*` codes. Beyond the eleven in Requirements, it adds `import_cleanup_pending` (503) and `import_evidence_unsupported` (422). Requirements say the DTOs and the status for each error come from that file, so the plan follows it.
- For unsafe methods, `Boundary.request` reads and parses a JSON body before the route runs (`api.py:252-283`). It answers an octet-stream body with 415 and a body over 16 KiB with 413. The eight routes here all take JSON bodies or none.
- `docs/web-v2-imports.md` (around line 209) requires the HTTP gateway to commit `admit_rate_v1` in its own short transaction, before it decodes the request body or calls a read, create, decide, cancel or confirm function. A refusal or rollback later in the request leaves the attempt counted.
- `wire-contracts.json` `Decide` is `{set_id, decisions}`, where `decisions` (codec `Decisions`) carries `operation_id` and `expected_set_revision`. `decide_set_v1` takes exactly those two keys. `accept_preview_v1` takes `operation_id`, `preview_digest` and `preview_id`. `cancel_set_v1` takes `operation_id`, `expected_set_revision` and `set_id`.
- `read_sets_v1` and `read_preview_v1` return an unsigned `next` payload, which the API must sign with `ingestion/cursors.py`.
- `requirements-pg-test.lock` starts with `-r requirements-web-test.lock` (since `64f7f51`), so every CI job that installs it already has FastAPI, `httpx` and the test client. An earlier version of this finding said the opposite; it was wrong.
- `ingestion/contracts.py` already holds `ERROR_STATUS`, a read-only map equal to `wire-contracts.json` `error_status`.
- Inputs from the IMP-007F plan (PR #86, not merged):
  - Its D1 asked who registers the worker and sets `ready`. The owner answered that with IMP-007S (Decisions needed, item 4).
  - Its D2 finds that no merged code builds a `ReviewBundle`, so no worker can prepare a preview yet. IMP-007P (plan in PR #105) builds it. IMP-007E's routes only read previews and confirm them, so this ticket does not depend on it; its tests seed a READY set with a preview from the oracle vectors.

### Readiness at `0004` (2026-11-21, `main` at `cd68c5e`)

- The builder (codex/gpt-6.1-sol) claimed this ticket on 2026-11-21 and stopped before Part A, at the second Stop-and-ask condition. On one isolated synthetic PostgreSQL 18 target migrated to `0004_ingestion`:
  - The operator call to `ingestion_migration.verify_inventory` passed with 68 functions.
  - The same call through the runtime role's login raised `migration_role_required`. It calls `migration._operator`, which requires database CREATE, and the approved `0004` grants revoke CREATE from the runtime, gateway and worker roles.
  - Through the gateway role's login it failed on reading `wl_pg.alembic_version`, because the gateway has no right on `wl_pg`.
  - No code was changed. Decisions needed item 7 records the question and the owner's answer.
- A second refusal, found while revising this plan by reading `identity.role_inventory`: with `gateway=False` it requires INSERT on most `wl_pg` columns, but at `0004` the runtime role has SELECT only on `wl_pg`. So `role_inventory(self.financial, gateway=False)`, which `Auth.ready()` calls today, would also refuse a correct `0004` target. The gateway branch should pass. IMP-007W's AC-07 confirms both on real PostgreSQL.
- IMP-007W adds `ingestion_migration.verify_runtime_inventory(conn, *, runtime_role, gateway_role, worker_role)`. It runs through the runtime login with the rights `0004` gives that role and makes the same checks as the operator verifier. That covers the runtime role's exact grants and role safety, which `role_inventory(gateway=False)` would otherwise check. Part A uses it.

### Recheck after IMP-007W and IMP-007O (2026-11-23, `main` at `cd122a2`)

Since `cd68c5e`, nothing changed under `src/kurafolio/web_v2/`, `src/kurafolio/ingestion/` or `persistence/context.py`, `identity.py` and `source_store.py`, so the Part A to D findings above still hold. What did change:

- IMP-007W is `done` ([PR #96](https://github.com/gh-slee/kurafolio/pull/96)). On `main`, `verify_runtime_inventory(conn, *, runtime_role, gateway_role, worker_role)` has exactly the signature Part A uses and returns `{'schema_revision': '0004_ingestion', 'functions': 68}`. In order, it:
  - validates the three role names;
  - requires PostgreSQL 18 and `current_user == runtime_role`;
  - takes the owner from the four `wl_*` namespaces and requires the owner and the three roles to be four different roles (`migration_role_required` otherwise);
  - checks the revision, then runs the shared installed-inventory check.
  Any driver error becomes `migration_target_invalid`.
- IMP-007W's `test_ac_07_existing_role_inventory_profile_boundary` ran `role_inventory(schema_mode='sources', gateway=True)`, `source_role_inventory` included, through the gateway login on a real `0004` target. It passed and returned the gateway role. The same call with `gateway=False` through the runtime login raised. Part A's `role_inventory` change for `ingestion` runs that same code, so the gateway half of readiness is proven on `0004`.
- IMP-007W's review note N3 left "additional configuration validation" to this ticket. A gateway login called with the runtime and gateway roles swapped fails closed only on the later revision read. Under Part A the swap cannot reach that call:
  - `runtime_role` is the runtime login's own `current_user`;
  - `gateway_role` is what `role_inventory(gateway=True)` returns through the identity login;
  - only `worker_role` comes from configuration.
  A swapped pair of connection URLs fails the gateway `role_inventory` or the runtime check. A `worker_role` equal to another role fails the four-roles rule. A `worker_role` naming a role without the worker grants fails `verify_grants`. The Tests table adds a `/readyz` row for each case. No new validation code is needed.
- The existing `sources` branch of `Auth.ready()` runs `source_migration.verify_inventory` whenever `self.sources is not None`. That verifier requires revision `0003_source_lifecycle` and so refuses every `0004` target. Part A sets `self.sources` on `ingestion` too, so the guard must change; see Part A.
- IMP-007O is `done` ([PR #103](https://github.com/gh-slee/kurafolio/pull/103)). `reserve_member_v1`'s bind result now also returns `context_unpadded_base64`. Only IMP-007U's upload route calls `reserve_member_v1`. No route here calls it, and no public response may carry that key.
- `docs/web-v2-imports.md` gained a sentence from IMP-007W, "IMP-007E is planned to call it from `/readyz`; no application calls it yet", which Part F replaces. It also gained the ANL-008 positions section, which this ticket does not touch.
- The `postgres` CI job's `--expect-skipped` is now 132 (131 gated ingestion tests plus the runtime-image test).

### The preview read's `{page, next}` shape (2026-11-23, `main` at `06c5eea`)

- codex/gpt-6.1-sol claimed this ticket on 2026-11-23 from `9817e3a`. Before any application edit it stopped at the Stop-and-ask condition on extra SQL keys and raised Decisions needed item 8. Its record is on its local ticket branch only.
- `read_preview_v1` (`persistence/ingestion_schema.py`, the `RETURN` at line 4553) answers `{'ok': true, 'value': {'page': {...}, 'next': <cursor payload or null>}}`.
- The `page` object has exactly 13 keys: `id`, `set_id`, `set_revision`, `state`, `preview_digest`, `expires_at`, `rows`, `can_confirm`, `review_digest`, `content_digest`, `accepted_generation`, `mapping_generation` and `control_generation`. These are the `required` keys of `wire-contracts.json` `PreviewPage` minus `next_cursor`.
- `PreviewPage` is flat, has `additionalProperties: false` and requires `next_cursor` (a string of at most 1,024 characters, or null). Renaming `next` alone leaves a `page` key that the DTO forbids, so Part D's "only `next` and `next_cursor` differ" rule stopped the build.
- The preview cursor payload comes from `_cursor_next_sql('preview.id::text', 'preview.set_revision::text', 'preview.review_digest', 'NULL', ...)`. Its `resource_id`, `resource_revision` and `review_digest` equal the page's `id`, `set_revision` and `review_digest`, and its `filter` is null.
- `read_sets_v1` answers `{'items': [...], 'next': ...}`, with no wrapper. `SetList` is `{items, next_cursor}`, so a rename is enough there.
- Both read functions require `limit` as a JSON string (`jsonb_typeof(p_payload->'limit') = 'string'`, matching `^([1-9]|[1-4][0-9]|50)$`). An integer `limit` is `import_invalid` on every call.
- `cursors.sign(key, payload)` checks the closed cursor shape and raises `IngestionError('import_invalid')` on a bad payload, or `IngestionError('import_limit')` for a token over the limit. `codec.validate(value, 'PreviewPage')` raises `IngestionError` on a schema failure.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance. Use the claim's `isolation_id` and `port_base`.

### What to build

The `ingestion` runtime profile that r7 [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md) ("Profile integration and readiness") asks for, so that a `0004_ingestion` database can be served. Activating an instance is IMP-007S.

Eight routes, all under the ingestion profile only. On an `identity` or `sources` instance they do not exist (404), as the source routes behave today in `web_v2/api.py`. The upload route, `PUT /api/v2/import-sets/{set}/members/{member}/raw`, is IMP-007U.

| Route | Purpose | Answer |
|---|---|---|
| `POST /api/v2/import-sets` | Create a set of 1 to 4 members, each naming an enabled connection and a format version | New set and member IDs; the same `operation_id` and payload returns the same IDs |
| `GET /api/v2/import-sets` | History, with a signed cursor, `limit` 1 to 50 and a status filter | Set summaries without file content |
| `GET /api/v2/import-sets/{set}` | One set | State, member progress, expiry, fixed error codes, preview and receipt IDs |
| `PUT /api/v2/import-sets/{set}/decisions` | Mapping and conflict decisions at an expected set revision | 202; the worker prepares a new preview |
| `GET /api/v2/import-previews/{preview}` | The immutable preview, paged, at most 50 rows a page | Plan summaries, required decisions, digest, expiry |
| `POST /api/v2/import-previews/{preview}/confirm` | Confirm with `operation_id` and `preview_digest` only | Committed receipt or a typed error |
| `POST /api/v2/import-sets/{set}/cancel` | Cancel at an expected set revision | Cancelled, or the receipt if the commit won the race |
| `GET /api/v2/import-receipts/{receipt}` | Read a past receipt | The immutable receipt |

Rules that reviewers will check:

- JSON control bodies are at most 16,384 bytes with a 10 second deadline, like the existing V2 routes.
- Errors carry a code only: `import_invalid`, `import_limit`, `import_busy`, `import_expired`, `import_reupload_required`, `import_mapping_required`, `import_conflict`, `import_stale`, `import_operation_conflict`, `import_commit_uncertain`, `import_runner_unavailable`. No file content, path, connection string or parser message reaches a response or a log line.
- The browser never sends financial values. Confirmation carries only the operation ID and the digest of the preview the user saw.
- Rate limits are admitted inside the SQL functions (IMP-007J, merged). Do not add a second limiter in Python.
- The exact DTOs and the status code for each error are in [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json) in the r7 bundle, and the routes in [ingestion-api.md](../docs/specs/imp-007-r7/ingestion-api.md). Do not invent field names, because APP-011D builds its page on them.

## Acceptance criteria

- [x] AC-IMP-007E-01: Each of the eight routes above exists on the ingestion profile, appears in `/api/v2/openapi.json` with its DTOs, and is absent on the `identity` and `sources` profiles.
- [x] AC-IMP-007E-02: Routes call only the r7 SQL functions; no route writes tables directly.
- [x] AC-IMP-007E-03: Unauthenticated, cross-tenant and stale-version requests are refused.
- [x] AC-IMP-007E-05: HTTP tests cover each route and refusal.
- [x] AC-IMP-007E-07: Replaying create, decisions, confirm or cancel with the same `operation_id` and payload returns the first answer and changes nothing; the same `operation_id` with a different payload is `import_operation_conflict`.
- [x] AC-IMP-007E-09: `docs/web-v2-imports.md` lists the routes and their error codes, so APP-011D can be built from the public document.

## Build plan

- Based on: `main` at `a2f5f2b`; rechecked on 2026-11-20 against `main` at `d902717`, with no change under `src/`, `tests/`, `docs/` or `scripts/`. The readiness parts (Part A `config.py` and `auth.py`, the `/readyz` test rows and Stop and ask) were revised on 2026-11-21 from `main` at `cd68c5e` for the owner's answer to Decisions needed item 7. They use IMP-007W's interface as its plan names it. Rechecked on 2026-11-23 against `main` at `cd122a2`, after IMP-007W (#96) and IMP-007O (#103) merged; see Context, "Recheck after IMP-007W and IMP-007O". That recheck made the `Auth.ready()` source-check guard explicit, added the role-configuration `/readyz` rows and corrected the CI install note. All dependencies are `done`. Revised on 2026-11-23 from `main` at `06c5eea` for the owner's answer to Decisions needed item 8: Part D's "Read responses" adds the strict `{page, next}` conversion, and Tests add its unit and real-PostgreSQL HTTP cases. No SQL, route, DTO or error code changes.
- The plan follows the owner's answers of 2026-11-20 under Decisions needed (items 1 to 5) and the new gated text (item 6). The owner approved the new gated text on 2026-11-21 (item 6), recorded in plan pull request #87. A builder starts only after that record is on `main`.
- Build order:
  1. Part A (profile).
  2. Parts B to D (gateway caller, DTOs, the eight JSON routes).
  3. Part F (docs).
- One pull request.
- Acceptance IDs 04, 06 and 08 moved to IMP-007U with the upload route; this ticket keeps 01, 02, 03, 05, 07 and 09 with their numbers.

### Part A: the `ingestion` runtime profile on the API side

Every change is additive. The `identity` and `sources` profiles keep their exact behaviour, revisions and inventory checks.

- `src/kurafolio/persistence/context.py`:
  - `Database.__init__` maps `"ingestion"` to `"0004_ingestion"`. Write the literal and add a unit test asserting that it equals `ingestion_schema.REVISION`; do not import the 5,500-line schema module here.
  - The `ingestion` profile gets the same `connect_timeout` and `statement_timeout`/`lock_timeout`/`idle_in_transaction_session_timeout` options as `identity` and `sources`.
  - Add `ingestion` to the set checked in `_transaction`'s principal branch and in `RequestDatabase.__post_init__`.
- `src/kurafolio/persistence/identity.py`:
  - `IdentityStore.__init__` accepts `"ingestion"`.
  - In `role_inventory`, `source_role_inventory` also runs when `database.schema_mode == "ingestion"`. On `ingestion`, `Auth.ready()` calls only the gateway branch (`gateway=True`); see `auth.py` below.
  - The other counts stay as they are (22 `wl_identity` functions, 7 identity tables, 22 RLS `wl_pg` tables), because `0004` replaces function bodies but adds no identity or `wl_pg` objects. If a real `0004` database disagrees, stop and ask.
- `src/kurafolio/persistence/source_store.py`: `SourceStore.__init__(config, catalog, *, schema_mode="sources")` accepts `"sources"` or `"ingestion"`.
- `src/kurafolio/web_v2/config.py`:
  - `Settings.schema_profile` accepts `"ingestion"`. Like `sources`, `ingestion` requires a valid `source_catalog`.
  - Add one keyword-only field, `worker_role: str | None`, a PostgreSQL role name. It is `None` unless the profile is `ingestion` and is required for it. Validate it with the same rule as the operator's `--worker-role`. `Auth.ready()` passes it to `verify_runtime_inventory`.
  - `from_files(..., worker_role=None)` passes it through.
  - The hand-off settings (worker URL, peer DNS name, instance ID and the TLS files) belong to the upload route and are IMP-007U's. Do not add them here.
- `src/kurafolio/web_v2/__main__.py`:
  - `serve --schema-profile` adds `ingestion`.
  - New `serve` flag `--worker-role`, required with `ingestion` and refused without it.
  - The operator `--schema-profile` choice (setup, invite, account, `identity status`) adds `ingestion`, so that an instance at `0004` can still issue invites and manage accounts.
  - No other operator command changes. The activation command is IMP-007S.
- `src/kurafolio/web_v2/auth.py`:
  - For `sources` or `ingestion`, `Auth.__init__` opens `SourceStore(settings.identity, settings.source_catalog, schema_mode=profile)`.
  - For `ingestion` it also opens `self.imports = IngestionStore(settings.identity, settings.source_catalog)` (Part B) and sets `self.cursor_key = cursors.derive_key(settings.key)`. `close()` closes `self.imports`.
  - `Auth.ready()` on `ingestion`, in this order:
    1. `left = self.instance()` and `gateway_role = role_inventory(self.store.database, gateway=True)`, as today.
    2. Do not call `role_inventory(self.financial, gateway=False)`. It refuses a correct `0004` target (Context, "Readiness at `0004`").
    3. In one `self.financial.engine.begin()` transaction:
       - `runtime_role = execute(conn, "SELECT current_user").scalar_one()`;
       - `ingestion_migration.verify_runtime_inventory(conn, runtime_role=runtime_role, gateway_role=gateway_role, worker_role=self.settings.worker_role)` (IMP-007W). It covers the identity inventory, both structure digests, the functions, the exact grants and role safety of all three roles, and refuses equal roles;
       - the `REALM_SNAPSHOT` read and the same comparison as today: the realm keys match `instance()`, `revision == self.financial.revision` (`0004_ingestion`) and `ready is True` (the identity `wl_pg.instance_state` flag, not `wl_ingestion.instance_state.ready`);
       - the `wl_sources.catalog_state` digest check.
    4. Any exception becomes `IdentityError()`, as today.
  - The existing source check in `ready()` (`source_migration.verify_inventory` and the catalog digest) is guarded today by `if self.sources is not None`. Change that guard to `schema_profile == 'sources'`, because Part A also sets `self.sources` on `ingestion`. `source_migration.verify_inventory` requires revision `0003_source_lifecycle` and would refuse every `0004` target. On `ingestion`, `ready()` never calls it.
  - The API never calls `ingestion_migration.verify_inventory`, `_checked_roles` or `migration._operator`. They are operator-only.
  - Apart from that guard, which leaves their behaviour unchanged, the `identity` and `sources` branches of `ready()` stay exactly as they are.
  - Role configuration (IMP-007W's N3): `runtime_role` and `gateway_role` come from the two logins, so they cannot be swapped by configuration. `worker_role` is checked by `verify_runtime_inventory` (four distinct roles, exact worker grants). Add no other role validation; the Tests table covers the misconfigurations.
  - `ready()` does not read `wl_ingestion.instance_state`. An unactivated instance passes `/readyz`, and every import route answers `instance_not_ready` (503) from SQL. Part F documents this.
- `src/kurafolio/web_v2/api.py`:
  - On `ingestion`, `Boundary.request` and `create_app` serve the source routes exactly as on `sources`, because `create_set_v1` needs an enabled connection and only the source routes create one. They also serve the import routes from Part D.
  - On `identity` and `sources`, the import paths answer 404 `not_found` and are absent from `/api/v2/openapi.json`.
  - The upload path `PUT /api/v2/import-sets/{set}/members/{member}/raw` is not registered by this ticket and answers 404 `not_found` on every profile until IMP-007U adds it.

### Part B: the gateway caller

- `src/kurafolio/persistence/ingestion_store.py` (new), modelled on `SourceStore.call`:
  - `IngestionStore(config, catalog)` opens `Database(config, schema_mode="ingestion")` and keeps `catalog_digest(catalog)`.
  - `call(name, principal, payload, *, deadline) -> dict`:
    - Accepts only names in `ingestion_schema.GATEWAY` other than `admit_rate_v1`; anything else raises `IdentityError()` before any SQL runs. The routes here use `create_set_v1`, `read_sets_v1`, `read_set_v1`, `decide_set_v1`, `read_preview_v1`, `accept_preview_v1`, `cancel_set_v1` and `read_receipt_v1`. `reserve_member_v1` stays callable through the same method for IMP-007U.
    - Arguments are `(session_digest, user_id, credential_version, realm, catalog_digest, payload)`, cast as `text, uuid, int8, jsonb, text, jsonb`.
    - Each transaction sets the same per-transaction `statement_timeout` and `lock_timeout` as `SourceStore.call`.
    - Retries the whole transaction at most 3 times on `40001`/`40P01`, within the deadline.
  - `admit(principal, bucket)` calls `admit_rate_v1`, whose sixth argument is `text`, with `bucket` in `{'read', 'control'}`. It commits in its own transaction and returns nothing. The success value is `NULL`, so do not apply `SourceStore`'s "value is a dict" rule to it.
  - Result mapping:
    - `{'ok': True, 'value': dict}` returns the value.
    - `{'ok': False, 'code': c}` raises `RequestError(c, ERROR_STATUS[c])` when `c` starts with `import_` and is a key of `contracts.ERROR_STATUS`. Otherwise it raises `SourceError(c)` for codes in `lifecycle_v1.STATUS`, `IdentityError(c)` for codes in `identity.STATUS`, and `IdentityError()` for anything else.
    - A commit that fails after the function ran raises `import_commit_uncertain` (503) for `create_set_v1`, `decide_set_v1`, `accept_preview_v1`, `cancel_set_v1` and `reserve_member_v1`, and `IdentityError()` for reads.
  - No SQL text, parameter, payload or driver message reaches an exception or a log.
- Statuses come from `kurafolio.ingestion.contracts.ERROR_STATUS`, which already matches `wire-contracts.json` `error_status`. Add a test that compares the two. Do not load the bundle at runtime and do not keep a second copy.

### Part C: DTOs and error codes

- `src/kurafolio/web_v2/schemas.py`: append to `ERROR_CODES`, in the order of the `wire-contracts.json` `Error` code enum, every code that `error_status` holds and `ERROR_CODES` lacks:
  - the 13 `import_*` codes
  - `length_required`

  Do not remove or rename an existing code. `length_required` stays in this ticket so that `ERROR_CODES` covers `error_status` in one change, although only IMP-007U's upload route returns it.
- Validate request and response bodies with the frozen schemas already in `src/kurafolio/ingestion/contracts.py`, through `codec.validate(value, '<Name>')`. Write no Pydantic copy of any import DTO, because a copy could drift and APP-011D builds on these names.
  - Requests use `Create`, `Decide`, `Confirm` and `Cancel`. A schema failure is `import_invalid` (422).
  - Malformed JSON, duplicate keys and oversized bodies keep the Boundary's `invalid_input` (422) and `body_too_large` (413).
  - Responses use `SetResult`, `SetList`, `PreviewPage` and `Receipt`. A response that fails its schema is `internal_error` (500) and is never sent. `SetList` and `PreviewPage` are built from the SQL value by Part D's "Read responses" before this check.
- OpenAPI: install a custom `app.openapi` that adds every `$defs` entry that the eight routes reach, directly or through references, to `components.schemas`, rewriting `codec-schema.json#/$defs/X` and `#/$defs/X` to `#/components/schemas/X`. Give each import route its request body and its success response through `openapi_extra`. The error responses use the existing `Error` model. Keep the function generic over a route list, so IMP-007U can add the upload route to it.
- `src/kurafolio/web_v2/api.py`: `invalid_response` returns `internal_error` for import requests, as it does for source requests.

### Part D: Boundary changes and the eight JSON routes

- Route tables, consulted only when `settings.schema_profile == 'ingestion'`:

  | Path pattern | Methods | Bucket |
  |---|---|---|
  | `/api/v2/import-sets` | `GET`, `POST` | read, control |
  | `/api/v2/import-sets/[^/]+` | `GET` | read |
  | `/api/v2/import-sets/[^/]+/decisions` | `PUT` | control |
  | `/api/v2/import-sets/[^/]+/cancel` | `POST` | control |
  | `/api/v2/import-previews/[^/]+` | `GET` | read |
  | `/api/v2/import-previews/[^/]+/confirm` | `POST` | control |
  | `/api/v2/import-receipts/[^/]+` | `GET` | read |

- Order in `Boundary.request` for an import route:
  1. The existing host, duplicate-header, length and cookie checks, then route and method (404/405).
  2. Origin for unsafe methods (403 `origin_rejected`).
  3. Session (401 `authentication_required`).
  4. CSRF for unsafe methods (403 `csrf_rejected`).
  5. Query keys: `GET /api/v2/import-sets` allows `cursor`, `limit` and `state`, and `GET /api/v2/import-previews/{preview}` allows `cursor` and `limit`. Any other key, or any query on another import route, is 422 `invalid_input`. The existing `query()` already refuses duplicates.
  6. `await asyncio.to_thread(self.auth.imports.admit, principal, bucket)`, in its own committed transaction. An exhausted bucket is 429 `import_busy`.
  7. Only then the existing 16,384-byte, 10-second JSON body read for unsafe methods.
- The import routes never call `Auth.budget` or `consume_budget_v1`. That would be a second limiter, which Requirements forbid.
- Path IDs go through `checked_uuid` (422 `invalid_input` on failure). The SQL reports foreign or missing IDs as 404 `not_found` and never reveals which.
- The routes are registered in `create_app` under `if settings.schema_profile == 'ingestion'`. Each is a sync function that calls `auth.imports.call(...)` with `deadline=request.state.source_deadline`, which the Boundary sets to entry plus 20 seconds for every request.

| Route | SQL call and payload | Success |
|---|---|---|
| `POST /api/v2/import-sets` | `create_set_v1` with the validated `Create` body | 201 `SetResult`, also on replay |
| `GET /api/v2/import-sets` | `read_sets_v1` with `{cursor: verified payload or null, limit, state or null}`; `limit` defaults to 50 and allows `1..50` and is sent as a JSON string | 200 `SetList`, built by `set_list` (Read responses) |
| `GET /api/v2/import-sets/{set}` | `read_set_v1` with `{set_id}` | 200 `SetResult` |
| `PUT /api/v2/import-sets/{set}/decisions` | `decide_set_v1` with the validated `Decide` body; `body.set_id` must equal `{set}`, otherwise 422 `import_invalid` | 202 `SetResult` |
| `GET /api/v2/import-previews/{preview}` | `read_preview_v1` with `{cursor, limit, preview_id}`; `limit` as for the set list | 200 `PreviewPage`, built by `preview_page` (Read responses) |
| `POST /api/v2/import-previews/{preview}/confirm` | `accept_preview_v1` with `Confirm` plus `preview_id` | 200 `Receipt` |
| `POST /api/v2/import-sets/{set}/cancel` | `cancel_set_v1` with `Cancel` plus `set_id` | 200 `SetResult`; a lost race returns the set with its `receipt_id` |
| `GET /api/v2/import-receipts/{receipt}` | `read_receipt_v1` with `{receipt_id}` | 200 `Receipt` |

- Cursors: `cursors.verify(auth.cursor_key, token)` runs before any SQL read. A bad MAC or shape is 422 `import_invalid`.
- Two differences between the SQL value and the wire DTO are allowed, and only in the two read responses below: `next` becomes `next_cursor`, and `read_preview_v1`'s `page` wrapper is unwrapped. The other six routes send the SQL value unchanged after their schema check. If a SQL value has any other key its DTO lacks, stop and ask; do not drop or rename keys.

#### Read responses: the strict `{page, next}` conversion

The owner approved this conversion on 2026-11-23 (Decisions needed, item 8). It changes no SQL and no public schema.

- New module `src/kurafolio/web_v2/import_wire.py`. It is pure: no database, no I/O, no logging, and no FastAPI import. It imports only `cursors`, `codec` and `RequestError` from `web_v2/auth.py`. Do not put it in `web_v2/imports.py`, which is on the Do-not-touch list.
- `preview_page(value, cursor_key) -> dict` turns the `value` of a successful `read_preview_v1` call into the `PreviewPage` body. In this order:
  1. `value` must be a `dict` whose keys are exactly `{'page', 'next'}`. A missing key or any extra top-level key fails.
  2. `page = value['page']` must be a `dict`.
  3. `page` must not contain `next_cursor`. That fails whatever its value, also when it equals the signed `next` or is null. This check runs before the merge, because `next_cursor` is a valid `PreviewPage` property: a merge would overwrite it silently, and `additionalProperties: false` would never see it.
  4. `nxt = value['next']` must be `None` or a `dict`; any other type fails. For a `dict`:
     - it must agree with the page: `nxt['resource_id'] == page['id']`, `nxt['resource_revision'] == page['set_revision']`, `nxt['review_digest'] == page['review_digest']` and `nxt['filter'] is None`; read the keys with `.get` so a missing one fails as a mismatch, not as a `KeyError`. A mismatch is a conflicting field and fails;
     - `token = cursors.sign(cursor_key, nxt)`.
     For `None`, `token = None` (the last page, or an empty first page).
  5. `out = dict(page)`, then `out['next_cursor'] = token`.
  6. Return `codec.validate(out, 'PreviewPage')`, the admitted copy. This checks the complete DTO: all 14 required keys, no extra key (so a stray `page.next` or an unknown page key fails), the `rows` items as `PreviewRow` and at most 50 rows.
- `set_list(value, cursor_key) -> dict` does the same for `read_sets_v1`, which has no wrapper:
  1. `value` must be a `dict` whose keys are exactly `{'items', 'next'}`.
  2. `next` must be `None` or a `dict`; a `dict` is signed with `cursors.sign`.
  3. Return `codec.validate({'items': value['items'], 'next_cursor': token}, 'SetList')`.
- Failures. Every failure in either function, including an `IngestionError` from `cursors.sign` or `codec.validate`, raises `RequestError('internal_error', 500)` with `from None`. The SQL value is server output, so a fault in it is never `import_invalid` (422) or `import_limit` (413) toward the client. The existing `RequestError` handler in `create_app` sends the generic `Error` body. No value, key name or token is put in the exception, the response or a log line.
- The two read routes call these functions on the value `IngestionStore.call` returns. They return the result as the 200 body.
- What does not change:
  - SQL: `read_preview_v1`, `read_sets_v1` and every other function in `ingestion_schema.py` stay byte-identical. No migration and no provider change.
  - Public schema: `wire-contracts.json`, `codec-schema.json`, `contracts.py`, the `PreviewPage` and `SetList` definitions in `/api/v2/openapi.json` (still equal to `wire-contracts.json` after `$ref` rewriting, as the AC-01 row checks) and so any client type that APP-011D derives from them. No `page` or `next` key ever reaches a response or the OpenAPI document.

### Part F: documentation

- `docs/web-v2-imports.md`:
  - Replace "No route signs or verifies cursors yet", IMP-007W's "IMP-007E is planned to call it from `/readyz`; no application calls it yet" (say that `/readyz` on `ingestion` calls it) and the "Remaining acceptance" lines that this ticket settles ("Runtime profile readiness, authenticated routes").
  - Add a section listing the eight routes (method, path, request DTO, success status) and every error code with its status, taken from `error_status`. Say that the upload route arrives with IMP-007U. List the `serve` flags of the `ingestion` profile (`--schema-profile ingestion` and `--worker-role`).
  - State plainly that an `ingestion` instance passes `/readyz` before activation, and that every import route answers `instance_not_ready` (503) until the instance is activated (IMP-007S). An import also needs the worker (IMP-007F) and the upload route (IMP-007U) before it completes.
  - Say what `import_busy` (429) means on these eight routes: the user's read bucket (60 calls in 300 seconds) or control bucket (30 calls in 300 seconds) is used up, or the instance-wide bucket is; the client waits and retries. The API sends only the code and the existing generic message.
  - The paragraph on `import_busy` for the upload route, with its two causes (the raw rate window and a held raw slot), is IMP-007U's (its D5 (a) requirement). Do not write it here.
- `docs/web-v2-sources.md`: one line saying the source routes are also served on `ingestion`.
- Keep the language and publication checks passing. Quote no non-English strings.

### Tests

Tests that need no database go in `tests/test_web_v2_imports.py` (new). They patch `kurafolio.web_v2.api.Auth` with a fake that records calls, and use `fastapi.testclient` or raw ASGI messages.

Real-PostgreSQL tests go in `tests/test_postgres_import_routes.py` (new), gated on `KURAFOLIO_INGESTION_TEST=1`. Each class builds its own environment the way `IngestionProviderPostgresTests` does:

1. `scripts/postgres.py test-identity-environment`.
2. `migrate-identity`, then `migrate-sources`, then `migrate-ingestion`.
3. Activate the synthetic instance through the owner connection, in a test-only helper that is never shipped: a wrapper catalog for the synthetic source fixture, a runtime profile digest, the `instance_budgets` rows, an enabled `workers` row for the worker role and `ready = true`. Seed them the way `tests/test_postgres_migration.py` does today. If IMP-007F's plan moves those helpers into `tests/ingestion_pg_support.py`, reuse that file. Keep using this helper after IMP-007S lands; its operator command is that ticket's to test.
4. Serve `create_app` on `ingestion`. No route here hands bytes to a worker, so no worker or fake worker is needed.
5. For the preview, confirm and receipt routes, seed a READY set with a stored preview from the oracle vectors through the owner connection, the way the existing `accept_seed` helper does. No worker prepares a preview yet (IMP-007F's D2). The paging rows need a stored review document with at least 3 rows; if the oracle preview has fewer, build one from oracle rows with the same helper. If that needs a SQL change or a new database function, stop and ask.

Every test names its AC ID.

| AC | Case | Expected |
|---|---|---|
| 01 | `GET /api/v2/openapi.json` on `ingestion` | 8 import method/path pairs; each request and success schema equals the `wire-contracts.json` definition after `$ref` rewriting; no `.../members/{member}/raw` path |
| 01 | Each of the 8 method/paths on `identity` and on `sources` | 404 `not_found`; none in OpenAPI; the source routes unchanged on `sources` |
| 01 | `PUT /api/v2/import-sets/{set}/members/{member}/raw` on each profile | 404 `not_found` without reading the body |
| 01 | Source routes on `ingestion` | Served as on `sources` |
| 02 | Fake store records every call during the whole run | Names a subset of `ingestion_schema.GATEWAY`; no `INSERT`, `UPDATE`, `DELETE` or `TRUNCATE` text in `api.py` or `ingestion_store.py` |
| 02 | Real PG: `/readyz` on a migrated `0004` instance | 200; with one extra grant to the gateway role added by the owner connection, 503 |
| 02 | Real PG: `/readyz` on the same instance with `ingestion_migration.verify_inventory`, `migration._operator`, `source_migration.verify_inventory` and `role_inventory` called with `gateway=False` each patched to raise `AssertionError` (wrap `role_inventory` so `gateway=True` still runs) | 200; none of the four is called |
| 02 | Real PG: `/readyz` after the owner connection grants `CREATE ON SCHEMA public` to the runtime role | 503 |
| 02 | Real PG: `Settings` with `worker_role` set to the gateway role's name, then to the runtime role's name | `create_app(settings)` raises `IdentityError` (its `__init__` runs `ready()`, as today), and the message names no role, SQL or URL |
| 02 | Real PG: `worker_role` naming a synthetic role that exists but has no `0004` worker grants | As in the row above |
| 02 | Real PG: identity and financial connection URLs swapped | As in the row above |
| 02 | `sources` profile, unit test with a fake `Auth` store | `ready()` still calls `source_migration.verify_inventory` exactly once |
| 03 | Each of the 8 routes with no cookie | 401 `authentication_required` |
| 03 | Each unsafe route with a wrong `Origin` / without `X-CSRF-Token` | 403 `origin_rejected` / 403 `csrf_rejected` |
| 03 | Real PG: user B reads, decides, cancels or confirms user A's set, preview or receipt | 404 `not_found`; A's set `revision` unchanged |
| 03 | Real PG: decide and cancel with `expected_set_revision` one below current | 409 `import_stale`; nothing changed |
| 03 | Real PG: request with a session that a password change ended | The same status and code a source route gives for that session in the same test |
| 05 | One success case per route, and one per refusal code that route can return | Status and code as in the expected values below |
| 07 | Real PG: create, decide, confirm, cancel each sent twice with the same `operation_id` and body | Second answer byte-equal to the first; set `revision` and receipt list unchanged |
| 07 | Same `operation_id`, different body, for each of the four | 409 `import_operation_conflict` |
| 09 | Docs test | `docs/web-v2-imports.md` names all 8 method/paths and every `error_status` code |
| 05 | Fake store: `GET /api/v2/import-previews/{preview}` where `read_preview_v1` returns each malformed value from the `preview_page` unit list below | 500 `internal_error`; the body is the generic `Error` and contains no key name, value or token; never 422 or 413 |
| 05 | Fake store: `GET /api/v2/import-sets` returning `{items, next, extra}` | 500 `internal_error`, as above |
| 05 | Real PG: page through a seeded preview with at least 3 rows using `limit=1` | Each 200 body validates as `PreviewPage` and has no `page` or `next` key; every page but the last carries a string `next_cursor` that the next request accepts; the last page has `next_cursor` null; the rows of all pages, in order, equal the stored review rows |
| 05 | Real PG: the same preview with `limit=50` | One page, `next_cursor` null |
| 05 | Real PG: a page-1 `next_cursor` of preview A sent to `GET /api/v2/import-previews/{B}` for a second seeded preview B of the same user | 409 `import_stale` (from SQL: the cursor's `resource_id` names A) |
| 05 | Real PG: a page-1 `next_cursor` with one character changed | 422 `import_invalid` (the MAC check runs before SQL) |
| 05 | Real PG: `GET /api/v2/import-sets?limit=1` with 2 sets, then with the returned cursor | `SetList` bodies with no `next` key; the second page's `next_cursor` is null |

Unit tests of `import_wire.py` go in `tests/test_web_v2_imports.py` (or a new `tests/test_web_v2_import_wire.py` with the same optional-dependency handling). They need no database. Build the valid input from the 13 page keys of a real `PreviewPage` example in the oracle vectors (or one built from `wire-contracts.json`), and the cursor payload with the same fields `_cursor_next_sql` writes. Each failing case asserts `RequestError` with code `internal_error` and status 500, and that `str(exc)` holds no input value.

`preview_page`:

- Valid page with `next`: the result equals `page` plus `next_cursor`; `cursors.verify(key, result['next_cursor'])` returns the original payload; the result has no `page` or `next` key.
- Last page (`next` null): `next_cursor` is null.
- Empty first page (`rows: []`, `next` null): valid.
- Missing `page`; missing `next`; one extra top-level key (for example `next_cursor` or `ok` beside `page` and `next`); `value` a list or null.
- `page` a list, a string or null.
- `page` carrying `next_cursor`: equal to the signed token, different from it, and null. All three fail.
- `page` missing one required key (try each of the 13); `page` with one extra key; `page` carrying `next`.
- `next` a string, an integer or a list.
- `next` whose `resource_id`, `resource_revision` or `review_digest` differs from the page, or whose `filter` is not null.
- `next` with a missing or extra cursor field (`cursors.sign` raises `import_invalid`): 500, not 422.
- `cursors.sign` raising `import_limit` (patch it, because a payload of the closed shape may not reach 1,024 characters): 500, not 413.
- A `rows` list of 51 items: 500.

`set_list`:

- Valid with `next`, and with `next` null.
- Missing `items` or `next`; an extra top-level key; `next` of a wrong type; an item that fails `SetResult`.

Also add a source-text test that `import_wire.py` contains no `logging`, `print` or SQL text.

Independent expected values, from `ingestion-api.md` and `wire-contracts.json`, not from the code under test:

- Status codes:
  - 409: `import_busy` is 429; `import_expired`, `import_stale`, `import_conflict`, `import_mapping_required`, `import_reupload_required` and `import_operation_conflict` are 409.
  - 413, 422 and 411: `import_limit` is 413; `import_invalid` and `import_evidence_unsupported` are 422; `length_required` is 411.
  - 503: `import_commit_uncertain`, `import_runner_unavailable` and `import_cleanup_pending` are 503.
- Budgets in a 300-second window:
  - The 31st control call (create, decide, confirm or cancel) by one user is 429 `import_busy`. Calls 1 to 30 are admitted.
  - The 61st read by one user is 429.
  - A 9th outstanding set for one user is refused by `create_set_v1`.
- `limit=0` and `limit=51` are 422; `limit=50` is allowed. A list cursor reused with a different `state` filter is refused.

Negative cases the reviewer will look for:

- An import route on a 404 profile does not touch the database. The fake `Auth` records no call.
- An import route never reads a body before `admit` returns (fake `admit` raises `import_busy`, and `receive` raises if called).
- An unknown `error_status` code from SQL never becomes a 200 or leaks text.

CI and the skip guard:

- Run `tests/test_postgres_import_routes.py` in the `postgres-ingestion` job with `--expect-skipped 0`, as a new step after the existing `test_postgres_migration.py` step. That job installs `requirements-pg-test.lock`, which already includes `requirements-web-test.lock`; add no other install.
- Gate each class with `unittest.skipUnless` on `KURAFOLIO_INGESTION_TEST`, the way `test_postgres_migration.py` does. Import `fastapi.testclient` and `kurafolio.web_v2.*` inside `setUp` or the test methods, as `tests/test_web_v2_api.py` does, so discovery never fails at import time.
- The `postgres` job also discovers `test_postgres_*.py` and skips these tests there. Raise its `--expect-skipped` (132 at `cd122a2`) by the number of new gated tests and update the count in its comment (131 ingestion tests at `cd122a2`).
- Also run the focused commands in Handoff, the full unit suite and `scripts/check_language.py`.

### Rollback

- Everything is additive behind `--schema-profile ingestion`. Reverting the pull request restores today's behaviour.
- This ticket installs no migration and changes no SQL, so a reverted build leaves no database change behind.
- After a revert, a database already at `0004` cannot be served at all, which is the state on `main` today. No data is lost.

### Do not touch

- `src/kurafolio/persistence/ingestion_schema.py`, `ingestion_migration.py`, `ingestion_restore.py` and the `0001` to `0004` providers and migration files: no SQL change in this ticket. IMP-007O changes the `0004` bind result separately, and IMP-007W adds `verify_runtime_inventory`.
- The upload route, `web_v2/handoff.py`, the hand-off settings and their `serve` flags: IMP-007U.
- The operator activation command in `web_v2/operator.py`: IMP-007S.
- `identity` and `sources` route behaviour, error codes and budgets; the SQLite application and legacy routes.
- The bounded reader in `web_v2/imports.py`.
- The IMP-007F worker or launcher, the IMP-007M slot recovery, `tickets/ROADMAP.md` and other tickets' files.
- The non-English strings in `error_response`: do not copy them into tests or docs.

### Stop and ask if

- The Gate A record of 2026-11-21 (Decisions needed, item 6) is not on `main`, or `python3 scripts/tickets.py spec IMP-007E` reports a changed spec.
- `verify_runtime_inventory` on `main` has another name, signature or result than Part A uses. It matched at `cd122a2`.
- `verify_runtime_inventory` through the runtime login, or `role_inventory(gateway=True)` (with `source_role_inventory`) through the gateway login, refuses a correctly migrated `0004` database. Do not grant a role more rights, call the operator verifier or skip a check to get past it.
- A SQL function returns keys that its wire DTO does not have, other than `next` and `read_preview_v1`'s `page` wrapper, or `read_preview_v1`'s `page` has keys other than the 13 that Context lists, or a code outside `error_status`, `lifecycle_v1.STATUS` and `identity.STATUS`.
- A requirement seems to need a SQL change, a new route, a new error code or a new DTO field.
- A real-PostgreSQL test cannot run in the isolated environment. A skipped test is not acceptance.

## Plan

- [x] Part A: the `ingestion` runtime profile (context, identity, source store, config, CLI, Auth, Boundary).
- [x] Part B: `IngestionStore` gateway caller and `admit` for `admit_rate_v1`.
- [x] Part C: error codes, DTO validation from the frozen schemas, OpenAPI components.
- [x] Part D: Boundary order, the eight JSON routes and the strict `{page, next}` read-response conversion (`web_v2/import_wire.py`).
- [x] Part F: docs.
- [x] Unit and real-PostgreSQL HTTP tests; CI job and skip counts.

## Decisions needed

Items 1 to 5 were answered by the owner on 2026-11-20, items 6 and 7 on 2026-11-21 and item 8 on 2026-11-23; all are kept here as the record. None is open.

1. **Which ticket builds the ingestion runtime profile?** Answered 2026-11-20: "IMP-007E (Recommended)", option (a). This ticket builds the profile as Build plan Part A describes, with no gated change for it; `resources` adds `identity-api`; APP-011I and APP-011E add IMP-007E to their `depends_on` in their own plans.
2. **Where does the API get the member's context bytes for the hand-off?** Answered 2026-11-20: "New SQL ticket (Recommended)", option (a). IMP-007O makes the bind result of `reserve_member_v1` also return the stored context bytes. Because the upload route then moved to IMP-007U (item 6), the dependency on IMP-007O belongs to IMP-007U, and this ticket's `depends_on` does not change.
3. **Where does the upload get `expected_set_revision`?** Answered 2026-11-20 with item 5: "Accept both (Recommended)", option (a). The upload route reads the set's current `revision` with `read_set_v1` right before `reserve`, with no wire change. It now applies to IMP-007U, whose Requirements carry it.
4. **Which ticket activates the ingestion profile on a database?** Answered 2026-11-20: "New operator ticket (Recommended)", option (b). IMP-007S adds the operator command (wrapper catalog, runtime profile digest, `instance_budgets`, worker row, `ready` last) and depends on IMP-007E and IMP-007F. No activation work is in this ticket; its tests keep the test-only activation helper.
5. **What does a client learn from `import_busy` on an upload?** Answered 2026-11-20 with item 3: "Accept both (Recommended)", option (a). One code; `docs/web-v2-imports.md` lists both causes and the action for each. It now applies to IMP-007U, whose Requirements carry it. This ticket's Part F documents `import_busy` only for its own read and control buckets.
6. **Gate A for the new gated text.** Resolved 2026-11-21: the owner chose "Approve" for the text with hash sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c. On 2026-11-20 the owner had chosen "Move upload out (Recommended)" and said they would approve the new text after the planner drafts it. The Goal, Requirements and Acceptance criteria above are that text:
   - Goal: drops the upload and "bounded uploads", and names the `ingestion` runtime profile. The approved Goal said "on the explicit sources profile", which did not match Requirements ("On an `identity` or `sources` instance they do not exist"); the draft corrects it.
   - Requirements: one line adopting the r7 "Profile integration and readiness" branch, with activation pointed to IMP-007S; "Nine routes" becomes "Eight routes" and the upload row leaves the table; the "Order of checks on upload", "Upload body" and hand-off bullets move to IMP-007U. Every other bullet is unchanged.
   - Acceptance criteria: AC-01 says "eight" instead of "nine"; AC-04, AC-06 and AC-08 move to IMP-007U (as AC-IMP-007U-04, -05 and -06); AC-02, AC-03, AC-05, AC-07 and AC-09 are unchanged. Surviving IDs keep their numbers.
   - Hashes from `python3 scripts/tickets.py spec IMP-007E`: approved sha256:6db6a5ba54ea92a37456cd15bf51124498e73d86d19d24cb6da26d4dcbac652b; new sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c.
   - `spec_approved` now records the new hash and `gate_approval` adds the 2026-11-21 approval. Both take effect when plan pull request #87 merges.
   - The Build plan above was checked against the new text.
7. **How should the ingestion API perform readiness inventory without operator privileges?** Raised by the builder on 2026-11-21 (Context, "Readiness at `0004`"). The merged plan had `Auth.ready()` call `ingestion_migration.verify_inventory` through the runtime connection, but that function requires database CREATE, and a real migrated `0004` synthetic target refused it after the operator call had passed. Options were (a) add a prerequisite ticket providing an approved runtime-safe inventory check, then update this Build plan to use it (recommended; keeps this ticket's ban on migration and provider changes), or (b) widen this ticket's scope and Build plan to include that check, with a new approval for the changed gated text. Answered 2026-11-21: "New prerequisite ticket", option (a).
   - IMP-007W is that ticket, filed in plan pull request #93. The owner gave it Gate A on 2026-11-21 in the same pull request.
   - `depends_on` adds IMP-007W, as the answer's "prerequisite" says.
   - Part A's `auth.py` and `config.py` bullets, two `/readyz` test rows and Stop and ask now use `verify_runtime_inventory`. The gated sections are unchanged (hash sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c).
8. **How should the preview SQL result become the frozen HTTP DTO?** Raised by codex/gpt-6.1-sol on 2026-11-23 (Context, "The preview read's `{page, next}` shape"). `read_preview_v1` answers `{page, next}`, while `PreviewPage` is flat and forbids `page`, and Part D allowed only `next` to differ. Options were (a) the API unwraps the strict `{page, next}` value, signs `next` as `next_cursor`, validates the complete `PreviewPage` and refuses extra or conflicting keys, with SQL and the public schema unchanged; or (b) a separate SQL prerequisite ticket that returns the flat fields, which would change the frozen `0004` provider. Answered 2026-11-23: option (a).
   - The builder recorded the owner's answer, "agree", on its local ticket branch; that record was not pushed.
   - On 2026-11-23 the owner then asked the planner, in a request relayed to the planning session (translated from the original): "Revise the IMP-007E Build plan: adopt the owner-approved strict {page,next} conversion, unwrap page, produce next_cursor, validate the complete PreviewPage and reject extra/conflicting fields; add unit and PostgreSQL HTTP tests. Keep the SQL and the public schema. Open the plan PR."
   - Part D's "Read responses" and the new Tests rows carry it. Part D's difference rule and Stop and ask now allow the `page` wrapper for `read_preview_v1` only.
   - This is a Build plan decision, not a gated change: the hash stays sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c, and `gate_approval` and `spec_approved` do not change. `depends_on` does not change.

## Handoff

- State: Local implementation and developer verification complete; status stays `in_progress` because PR #115 is open, and the required independent review has not run. Push CI results are recorded separately from the developer checks below. Base `2647ea8` contains the owner-approved strict preview conversion plan. The gated spec and Build plan are unchanged.
- Next step: Verify the local main-reconciliation candidate and arrange the required Claude Code reviewer for PR #115. The reconciliation only combines the updated PostgreSQL skip allowance (143) and preserves newer main. The next push needs approval of its exact additional commit. The Codex builder cannot run that reviewer model. Do not treat developer tests as independent QA or a complete CSV import service.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python scripts/run_gated_tests.py --expect-skipped 0 -- discover -s tests -p test_postgres_import_routes.py` passed 10 tests with zero skips in 14.832 s. `test_postgres_migration.py` passed 154 tests with zero skips in 87.347 s. The focused `test_ingestion_*.py` suite passed 107 tests in 0.825 s. The full default suite passed 1,463 tests in 797.212 s (1,191 passed, 272 explicit skips). IMP-007E API/persistence/SQL source is unchanged since that run; the later merge preserves main's separate ReviewBundle module. Local reconciliation passed 126 ingestion tests in 25.580 s and 15 HTTP/schema tests in 0.842 s. Later test-only fixture narrowing and replay/foreign-receipt assertions passed targeted tests (1 and 4 tests, zero skips). Helper/HTTP/config/docs tests passed 15 tests in 0.785 s.
- Evidence: logs under `work/imp-007e/`, including `full-unit.log`, `postgres-migration.log`, `postgres-http-accepted.log`, `preview-fixture-scope-retest.log` and `replay-scope-retest.log`. The optional host frontend source check could not run because the worktree lacks TypeScript dependencies and the host Node is below the documented version; no frontend source changed. Candidate image validation is a separate exact-HEAD gate.
- Gotchas: Use isolation `wl-imp-007e-5f66` and ports 56400 to 56499. Source/runtime inventory and all SQL/provider files remain unchanged. Upload, activation and the worker remain IMP-007U, IMP-007S and IMP-007F. No real portfolio or existing service was used for these tests.
- Open questions: None. Required independent QA/Architecture review is NOT RUN. PR #115 publishes implementation `18c72ff`; local reconciliation and PR metadata are not pushed. The own-ticket completion gate remains unsatisfied until the required review and final outcome metadata are complete.

## Log

- 2026-11-05 planner: created in the initial backlog plan.
- 2026-11-10 planner: owner re-confirmed this ticket for the V2 MVP on 2026-11-10; released (status ready), added starting files and verify commands.
- 2026-11-10 planner: added the dependency on IMP-007J, whose text requires its decision before routes are wired.
- 2026-11-13 planner: added the route table, the upload and error rules, and five acceptance criteria, all taken from the approved r7 contract. Scope is unchanged; the ticket no longer depends on a reader finding the route list in the local bundle.
- 2026-11-17 planner: the owner confirmed in conversation ("Confirm all six") the changes PR #64 made to this ticket after its approval. The approval in gate_approval covers the text as it stands now.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the bullet naming the r7 contract bundle, the "Real-PostgreSQL tests" bullet of Where to start and "What to build" from Context into Requirements and numbered the acceptance criteria AC-IMP-007E-01 to 09. Spec hash sha256:6db6a5ba54ea92a37456cd15bf51124498e73d86d19d24cb6da26d4dcbac652b, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:6db6a5ba54ea92a37456cd15bf51124498e73d86d19d24cb6da26d4dcbac652b.
- 2026-11-20 claude-code/opus-5.5: wrote the frontier Build plan from `main` at `a2f5f2b` (plan pull request #87). Added findings to Context and five items to Decisions needed, including which ticket builds the ingestion runtime profile; item 5 came from the IMP-007M plan (#85). Goal, Requirements and Acceptance criteria are unchanged.
- 2026-11-20 claude-code/opus-5.5: aligned Part E's hand-off responses with the IMP-007F plan (PR #86), took statuses from `contracts.ERROR_STATUS`, added the preview seeding the tests need while no worker builds a ReviewBundle, and widened Decisions needed item 4 to cover IMP-007F's D1. Gated sections unchanged.
- 2026-11-20 claude-code/opus-5.5: added `identity-api` to `resources`. The owner confirmed it on 2026-11-20 by choosing "IMP-007E (Recommended)" for "Which ticket builds the ingestion runtime profile?", whose text says "IMP-007E adds the `identity-api` resource".
- 2026-11-20 claude-code/opus-5.5: recorded the owner's answers of 2026-11-20 in Decisions needed: item 1 "IMP-007E (Recommended)"; item 2 "New SQL ticket (Recommended)" (IMP-007O); items 3 and 5 "Accept both (Recommended)"; item 4 "New operator ticket (Recommended)" (IMP-007S). `depends_on` is unchanged.
- 2026-11-20 claude-code/opus-5.5: the owner chose "Move upload out (Recommended)": "Upload route and its ACs move to a new ticket that depends on IMP-007O. IMP-007E (profile + 8 routes) can be built now and finishes sooner, unblocking APP-011I and APP-011E. Changes IMP-007E's gated text: you approve the new text after the planner drafts it." Drafted the new Goal, Requirements and Acceptance criteria (AC-04, 06 and 08 moved to IMP-007U), removed Part E and the hand-off settings from the Build plan, and filed IMP-007U, IMP-007O and IMP-007S in plan pull request #87. Spec hash changes from sha256:6db6a5ba54ea92a37456cd15bf51124498e73d86d19d24cb6da26d4dcbac652b to sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c; `spec_approved` and `gate_approval` are unchanged and wait for the owner's Gate A.
- 2026-11-21 claude-code/opus-5.5: recorded Gate A for the new gated text. The owner was asked "Gate A for IMP-007E's new text (PR #87, hash aba3bef4…). Changes from the approved text: the Goal names the ingestion runtime profile and drops uploads ('upload route is IMP-007U'); Requirements add one paragraph adopting the r7 profile branch (activation is IMP-007S), say 'Eight routes' instead of nine with the upload row removed, and move the upload-order, upload-body and hand-off bullets to IMP-007U; AC-04, AC-06 and AC-08 move to IMP-007U, other AC IDs unchanged. Approve this exact text?" and chose "Approve". `spec_approved` changes from sha256:6db6a5ba54ea92a37456cd15bf51124498e73d86d19d24cb6da26d4dcbac652b to sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c; `gate_approval` adds "owner 2026-11-21, IMP-007E text after the upload split (Q13)". Decisions needed item 6 resolved. The Build plan was checked against this text. Handoff now names IMP-007U and APP-011E as `identity-api` holders.
- 2026-11-21 claude-code/opus-5.5: recorded the builder's finding. codex/gpt-6.1-sol claimed this ticket on 2026-11-21 from `cd68c5e` and stopped before Part A at the Stop-and-ask condition on `verify_inventory`. On an isolated synthetic PostgreSQL 18 target at `0004`, the operator verifier passed with 68 functions, the same call through the runtime login raised `migration_role_required`, and the gateway login could not read `wl_pg`. No code changed; the builder's commits stayed on its local branch, and its evidence is under the ignored `work/imp-007e/` of that worktree. The builder raised Decisions needed item 7.
- 2026-11-21 claude-code/opus-5.5: the owner answered Decisions needed item 7 with "New prerequisite ticket", option (a): "add a prerequisite ticket providing an approved runtime-safe inventory check, then update this Build plan to use it". Filed IMP-007W in plan pull request https://github.com/gh-slee/kurafolio/pull/93 and added it to `depends_on`; the owner's answer confirms that change. Revised the readiness parts of the Build plan from `main` at `cd68c5e`: `Auth.ready()` on `ingestion` uses `verify_runtime_inventory` and no longer calls `role_inventory(gateway=False)`, which refuses the read-only runtime role at `0004`. Gated sections unchanged (sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c).
- 2026-11-23 claude-code/opus-5.5: rechecked the Build plan against `main` at `cd122a2`, after IMP-007W (#96) and IMP-007O (#103) merged, in plan pull request https://github.com/gh-slee/kurafolio/pull/110. `verify_runtime_inventory` matches Part A. Part A now changes `Auth.ready()`'s source-check guard to `schema_profile == 'sources'`, because `source_migration.verify_inventory` refuses `0004`. The Tests table adds `/readyz` rows for IMP-007W's N3 role misconfigurations. The CI note no longer asks for a second lock install, and the skip baseline is 132. No new owner decision. Gated sections unchanged (sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c).
- 2026-11-23 claude-code/opus-5.5: revised the Build plan from `main` at `06c5eea` for Decisions needed item 8, in plan pull request https://github.com/gh-slee/kurafolio/pull/111. The owner answered "agree" to option (a) when codex/gpt-6.1-sol asked, and then asked the planner (translated from the original): "Revise the IMP-007E Build plan: adopt the owner-approved strict {page,next} conversion, unwrap page, produce next_cursor, validate the complete PreviewPage and reject extra/conflicting fields; add unit and PostgreSQL HTTP tests. Keep the SQL and the public schema. Open the plan PR." Part D adds `web_v2/import_wire.py` (`preview_page`, `set_list`) with exact-key, no-`next_cursor`-in-page and cursor-agreement checks, full DTO validation and `internal_error` (500) on any fault. Tests add unit cases and real-PostgreSQL paging rows. No SQL, DTO, route or error-code change. Gated sections unchanged (sha256:aba3bef4df145ca2355ad07c3fafb0954169d04ad8a05609502b23528a1c3d4c).

- 2026-11-23 codex/gpt-6.1-sol: claimed the ticket, fast-forwarded its clean worktree to `9817e3a`, verified the approved hash and IMP-007W, and passed both prerequisite readiness checks on isolated PostgreSQL 18. Starting DTOs and profile integration.
- 2026-11-23 codex/gpt-6.1-sol: stopped before application edits because `read_preview_v1` returns an extra `page` wrapper forbidden by Build plan Part D. Recorded Decisions needed item 8 and the isolated readiness and synthetic codec evidence. Status blocked; no push or PR.
- 2026-11-23 codex/gpt-6.1-sol: recorded the owner's "agree" to item 8 option (a): the API flattens the strict `page` / `next` wrapper, signs `next` as `next_cursor`, validates `PreviewPage` and refuses unexpected or conflicting keys. SQL and the public schema remain unchanged; scope is the preview response adapter and its tests. Build plan and gated sections are unchanged. Still blocked until the Claude Code planner amendment merges to `main`; local record only, no push or PR.

- 2026-11-23 codex/gpt-6.1-sol: resumed after PR #111 merged at `2647ea8`. Resolved the ticket-record merge by preserving the exact merged Build plan, the approved spec, and local checkpoint Log lines. Starting the approved implementation; no push or PR.

- 2026-11-24 codex/gpt-6.1-sol: saved the partial profile, gateway store, eight JSON routes, strict read conversions and frozen OpenAPI implementation. Twelve database-free helper/HTTP tests passed in 1.355 s. Real-PostgreSQL HTTP tests, docs, CI and full/candidate checks remain; not ready for review or publication.

- 2026-11-24 codex/gpt-6.1-sol: added real migrated PostgreSQL HTTP fixtures without changing SQL, grants or constraints. Ten HTTP tests passed with zero skips, including replay, cross-tenant scope, positive stale revisions, signed paging, readiness drift, inactive activation and shared quotas. Corrected test assumptions using frozen sql-appendix receipt semantics and pre-existing storage/cursor expectations; failed logs are retained locally. Added 4 passing store fault tests and 15 passing helper/HTTP/config/docs tests. Docs and zero-skip CI wiring added. Full-suite and candidate gates remain pending.

- 2026-11-24 codex/gpt-6.1-sol: completed local developer verification. Existing PostgreSQL migration acceptance passed 154/154 with zero skips; ingestion-focused tests passed 107; full default suite passed 1,463 tests with 272 explicit skips in 797.212 s. The 10-test HTTP acceptance passed with zero skips; test-only exact-preview and replay/foreign-receipt strengthening then passed targeted 1-test and 4-test retests. Runtime source is unchanged. Developer source review, language/privacy/spec/ticket checks passed. Independent review, CI and publication remain NOT RUN; final candidate evidence belongs to its exact-HEAD receipt.

- 2026-11-24 codex/gpt-6.1-sol: pushed the approved implementation `18c72ff` and opened PR https://github.com/gh-slee/kurafolio/pull/115 with the validated canonical body. Current main `f146fc9` adds one gated PostgreSQL test; merging it locally requires only reconciling the foundation skip allowance to 143 (132 main ingestion tests plus 10 HTTP tests plus one runtime-image test). Preserved newer main and added the PR URL; gated spec, Build plan and behavior unchanged. Independent review is NOT RUN; the local merge is not approved for another push.
