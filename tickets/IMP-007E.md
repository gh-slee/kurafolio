---
id: IMP-007E
title: Add authenticated V2 import HTTP routes
priority: P0
status: ready
type: feature
parent: IMP-007
depends_on: [IMP-007D, IMP-007J]
resources: [v2-import-routes]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-10-31, IMP-007 spec r7 (covers all child tickets)"
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:6db6a5ba54ea92a37456cd15bf51124498e73d86d19d24cb6da26d4dcbac652b
updated: 2026-11-18
---

# IMP-007E: Add authenticated V2 import HTTP routes

## Goal

Expose create, upload, read, decide, accept and cancel through authenticated FastAPI routes on the explicit sources profile, with CSRF/origin checks and bounded uploads.

## Context

- Pattern: `tests/test_web_v2_sources.py` and [web-v2-sources.md](../docs/web-v2-sources.md).
- Background only: the revision 1 planning draft [docs/specs/v2-drafts/WL-P0-007.md](../docs/specs/v2-drafts/WL-P0-007.md) (sha256:fa0971a0da787cb327484c92144e4a5ecd916db4ad0328e03b408d647190acd5), which the r7 bundle supersedes.

### Where to start

- SQL fragments and the function inventory: `src/kurafolio/persistence/ingestion_schema.py`. Existing providers and operator commands: `src/kurafolio/persistence/migration.py`, `source_migration.py`, `migrations/`, `scripts/postgres.py`.
- Python reference checks and DTO codecs: `src/kurafolio/ingestion/` (`approval.py`, `codec.py`, `contracts.py`, `cursors.py`, `reconciliation.py`).
- V2 HTTP application and DTO style: `src/kurafolio/web_v2/api.py`, `web_v2/schemas.py`.
- Tests to extend: `tests/test_postgres_migration.py`, `tests/test_ingestion_*.py`, `tests/test_web_v2_api.py`, `tests/test_web_v2_sources.py`; vectors in `tests/fixtures/ingestion/oracle.json`.
- Public status and boundaries: [web-v2-imports.md](../docs/web-v2-imports.md). Product intent: [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md).

### Findings from the merged code (`main` at `a2f5f2b`)

- Both dependencies are merged: IMP-007D (`done`, the operator `0004_ingestion` migration and its grants) and IMP-007J (`done`, the granted `admit_rate_v1` gateway function).
- No runtime profile on `main` can serve a `0004_ingestion` database. Every layer accepts only `identity` and `sources`:
  - `Database` (`persistence/context.py:47`) maps only `foundation`, `identity` and `sources` to a revision. The principal check in `_transaction` (`:114`) and `RequestDatabase.__post_init__` (`:154`) accept only `identity` and `sources`.
  - `IdentityStore.__init__` (`persistence/identity.py:104`) accepts only those two profiles, and `role_inventory` runs the source check only for `sources`.
  - `SourceStore.__init__` (`persistence/source_store.py:14`) always opens `schema_mode="sources"`.
  - `Settings.__post_init__` (`web_v2/config.py:49`) and `from_files` accept only those two. So do `serve --schema-profile` (`web_v2/__main__.py:21`) and the operator `--schema-profile` (`:36`).
  - `Auth.__init__` and `Auth.ready` (`web_v2/auth.py:58-106`) build and verify only the `sources` stores.
  - Route gating in `Boundary.request` (`web_v2/api.py:185`) and route registration in `create_app` (`:416`) test `== 'sources'`.
- The r7 bundle, which Requirements adopt, already asks for that branch: [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), "Profile integration and readiness", says to add an explicit ingestion branch in `identity.py`, `source_store.py`, `Database`, Auth and config. IMP-007D built only the operator side. See Decisions needed, item 1.
- Nothing on `main` activates the ingestion profile on a database.
  - `migrate_ingestion` leaves `wl_ingestion.instance_state.ready` false. No code writes `wrapper_catalog_bytes`, `wrapper_catalog_digest` or `runtime_profile_digest`, sets `ready`, or adds an enabled `wl_ingestion.workers` row.
  - Until that happens, `_guard_user_v1` answers `instance_not_ready`, and `create_set_v1` fails, because it parses the wrapper catalog. The bind step of `reserve_member_v1` refuses without an enabled worker.
  - The runtime role cannot read `wl_ingestion.instance_state` (it is not in `READ_TABLES`), so `/readyz` cannot see that flag. See Decisions needed, item 4.
- The upload hand-off cannot be built from the merged functions.
  - The worker frame (`protocol-appendix.md`, `POST /internal/v1/handoffs`) carries the Handoff metadata, then the member's context bytes, then the raw bytes, and `runner_client.pack_input(..., schema='Handoff')` checks all three.
  - The bind step of `reserve_member_v1` returns `context_sha256` and the context length, not the bytes. No gateway function returns `members.context_bytes`, and the gateway role has no table access.
  - See Decisions needed, item 2.
- `reserve_member_v1` with `action: reserve` requires `expected_set_revision`. The upload route's request is `RAW_BINARY` in [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json), and `query_semantics` gives it no query keys, so the browser has no field to send it in. See Decisions needed, item 3.
- `web_v2/schemas.py` `ERROR_CODES` has no `import_*` code and no `length_required`. `error_response` (`api.py:57`) turns any code outside that list into `instance_not_ready` (503).
- `wire-contracts.json` `error_status` lists 13 `import_*` codes. Beyond the eleven in Requirements, it adds `import_cleanup_pending` (503) and `import_evidence_unsupported` (422). Requirements say the DTOs and the status for each error come from that file, so the plan follows it.
- For unsafe methods, `Boundary.request` reads and parses a JSON body before the route runs (`api.py:252-283`). It answers an octet-stream body with 415 and a body over 16 KiB with 413. The upload route needs its own branch.
- `docs/web-v2-imports.md` (around line 209) requires the HTTP gateway to commit `admit_rate_v1` in its own short transaction, before it decodes the request body or calls a read, create, decide, cancel or confirm function. A refusal or rollback later in the request leaves the attempt counted.
- `wire-contracts.json` `Decide` is `{set_id, decisions}`, where `decisions` (codec `Decisions`) carries `operation_id` and `expected_set_revision`. `decide_set_v1` takes exactly those two keys. `accept_preview_v1` takes `operation_id`, `preview_digest` and `preview_id`. `cancel_set_v1` takes `operation_id`, `expected_set_revision` and `set_id`.
- `read_sets_v1` and `read_preview_v1` return an unsigned `next` payload, which the API must sign with `ingestion/cursors.py`.
- A worker checks a hand-off token as `sha256(bytes.fromhex(token))` in hex (`ingestion_schema.py:4660`).
- `requirements-pg-test.lock` has no FastAPI. The CI job that runs real-PostgreSQL HTTP tests must also install `requirements-web-test.lock`.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance. Use the claim's `isolation_id` and `port_base`.

### What to build

Nine routes, all under the ingestion profile only. On an `identity` or `sources` instance they do not exist (404), as the source routes behave today in `web_v2/api.py`.

| Route | Purpose | Answer |
|---|---|---|
| `POST /api/v2/import-sets` | Create a set of 1 to 4 members, each naming an enabled connection and a format version | New set and member IDs; the same `operation_id` and payload returns the same IDs |
| `PUT /api/v2/import-sets/{set}/members/{member}/raw` | Upload one CSV as `application/octet-stream` | 202 after bounded reception and hand-off to the worker; the client then polls the set |
| `GET /api/v2/import-sets` | History, with a signed cursor, `limit` 1 to 50 and a status filter | Set summaries without file content |
| `GET /api/v2/import-sets/{set}` | One set | State, member progress, expiry, fixed error codes, preview and receipt IDs |
| `PUT /api/v2/import-sets/{set}/decisions` | Mapping and conflict decisions at an expected set revision | 202; the worker prepares a new preview |
| `GET /api/v2/import-previews/{preview}` | The immutable preview, paged, at most 50 rows a page | Plan summaries, required decisions, digest, expiry |
| `POST /api/v2/import-previews/{preview}/confirm` | Confirm with `operation_id` and `preview_digest` only | Committed receipt or a typed error |
| `POST /api/v2/import-sets/{set}/cancel` | Cancel at an expected set revision | Cancelled, or the receipt if the commit won the race |
| `GET /api/v2/import-receipts/{receipt}` | Read a past receipt | The immutable receipt |

Rules that reviewers will check:

- Order of checks on upload: route, method and headers first; then session, origin and CSRF; then the database reservation (`reserve_member_v1`); only then read the body. Never read a body for a request that will be refused.
- Upload body: exactly one `Content-Length`, 1 to 10,485,760 bytes; no multipart, `Content-Encoding` or `Transfer-Encoding`; 30 seconds total and 5 seconds idle. Missing length is 411, both length and chunked is 400, an encoding is 415, too large is 413. `web_v2/imports.py` (`receive_raw`) already implements the bounded reader; call it, do not write another.
- JSON control bodies are at most 16,384 bytes with a 10 second deadline, like the existing V2 routes.
- Errors carry a code only: `import_invalid`, `import_limit`, `import_busy`, `import_expired`, `import_reupload_required`, `import_mapping_required`, `import_conflict`, `import_stale`, `import_operation_conflict`, `import_commit_uncertain`, `import_runner_unavailable`. No file content, path, connection string or parser message reaches a response or a log line.
- The browser never sends financial values. Confirmation carries only the operation ID and the digest of the preview the user saw.
- Rate limits are admitted inside the SQL functions (IMP-007J, merged). Do not add a second limiter in Python.
- The hand-off of received bytes to the worker uses the one-use token from `reserve_member_v1` and the client in `src/kurafolio/ingestion/runner_client.py`. Until IMP-007F merges, test against a fake worker endpoint; the route's contract does not change when the real worker arrives.
- The exact DTOs and the status code for each error are in [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json) in the r7 bundle, and the routes in [ingestion-api.md](../docs/specs/imp-007-r7/ingestion-api.md). Do not invent field names, because APP-011D builds its page on them.

## Acceptance criteria

- [ ] AC-IMP-007E-01: Each of the nine routes above exists on the ingestion profile, appears in `/api/v2/openapi.json` with its DTOs, and is absent on the `identity` and `sources` profiles.
- [ ] AC-IMP-007E-02: Routes call only the r7 SQL functions; no route writes tables directly.
- [ ] AC-IMP-007E-03: Unauthenticated, cross-tenant and stale-version requests are refused.
- [ ] AC-IMP-007E-04: Upload size/time bounds and raw-byte retention follow r7.
- [ ] AC-IMP-007E-05: HTTP tests cover each route and refusal.
- [ ] AC-IMP-007E-06: A refused upload (no session, wrong origin, missing CSRF token, no reservation) is answered without reading the body; a test proves it with a body that would fail if read.
- [ ] AC-IMP-007E-07: Replaying create, decisions, confirm or cancel with the same `operation_id` and payload returns the first answer and changes nothing; the same `operation_id` with a different payload is `import_operation_conflict`.
- [ ] AC-IMP-007E-08: No response or log line in the test run contains bytes of an uploaded file.
- [ ] AC-IMP-007E-09: `docs/web-v2-imports.md` lists the routes and their error codes, so APP-011D can be built from the public document.

## Build plan

- Based on: `main` at `a2f5f2b`.
- The plan assumes the recommended answers under Decisions needed (1a, 2a, 3a, 4a, 5a). The owner answers them before merging this plan. If any answer differs, the planner revises the plan before it merges.
- Build order:
  1. Part A (profile).
  2. Parts B to D (gateway caller, DTOs, the eight JSON routes).
  3. Part E (upload), which starts only once the ticket from Decision 2 has merged.
  4. Part F (docs).
- One pull request. If the Decision 2 ticket has not merged when Parts A to D are done, stop and report rather than opening a partial pull request.

### Part A: the `ingestion` runtime profile on the API side

Every change is additive. The `identity` and `sources` profiles keep their exact behaviour, revisions and inventory checks.

- `src/kurafolio/persistence/context.py`:
  - `Database.__init__` maps `"ingestion"` to `"0004_ingestion"`. Write the literal and add a unit test asserting that it equals `ingestion_schema.REVISION`; do not import the 5,500-line schema module here.
  - The `ingestion` profile gets the same `connect_timeout` and `statement_timeout`/`lock_timeout`/`idle_in_transaction_session_timeout` options as `identity` and `sources`.
  - Add `ingestion` to the set checked in `_transaction`'s principal branch and in `RequestDatabase.__post_init__`.
- `src/kurafolio/persistence/identity.py`:
  - `IdentityStore.__init__` accepts `"ingestion"`.
  - In `role_inventory`, `source_role_inventory` also runs when `database.schema_mode == "ingestion"`.
  - The other counts stay as they are (22 `wl_identity` functions, 7 identity tables, 22 RLS `wl_pg` tables), because `0004` replaces function bodies but adds no identity or `wl_pg` objects. If a real `0004` database disagrees, stop and ask.
- `src/kurafolio/persistence/source_store.py`: `SourceStore.__init__(config, catalog, *, schema_mode="sources")` accepts `"sources"` or `"ingestion"`.
- `src/kurafolio/web_v2/config.py`:
  - `Settings.schema_profile` accepts `"ingestion"`. Like `sources`, `ingestion` requires a valid `source_catalog`.
  - Add two keyword-only fields, both `None` unless the profile is `ingestion` and both required for it:
    - `worker_role: str | None`, a PostgreSQL role name. Validate it with the same rule as the operator's `--worker-role`.
    - `handoff: HandoffSettings | None`.
  - `HandoffSettings` is a new frozen dataclass in the same module:
    - `url`: `https://host:port` with no path, query or credentials.
    - `peer_dns`.
    - `instance_id`: a canonical non-zero UUID.
    - `ca_file`, `cert_file` and `key_file`.
    - A `peer_tls()` method that returns `runner_client.PeerTLS(ca_file, cert_file, key_file, peer_dns, instance_id, 'worker')`.
  - `from_files(..., worker_role=None, handoff=None)` passes both through.
- `src/kurafolio/web_v2/__main__.py`:
  - `serve --schema-profile` adds `ingestion`.
  - New `serve` flags, all required with `ingestion` and refused without it: `--worker-role`, `--handoff-url`, `--handoff-peer-dns`, `--instance-id`, `--peer-ca-file`, `--peer-cert-file` and `--peer-key-file`.
  - The operator `--schema-profile` choice (setup, invite, account, `identity status`) adds `ingestion`, so that an instance at `0004` can still issue invites and manage accounts.
  - No other operator command changes.
- `src/kurafolio/web_v2/auth.py`:
  - For `sources` or `ingestion`, `Auth.__init__` opens `SourceStore(settings.identity, settings.source_catalog, schema_mode=profile)`.
  - For `ingestion` it also opens `self.imports = IngestionStore(settings.identity, settings.source_catalog)` (Part B) and sets `self.cursor_key = cursors.derive_key(settings.key)`. `close()` closes `self.imports`.
  - `Auth.ready()` on `ingestion` replaces the `sources` verification with `ingestion_migration.verify_inventory(conn, runtime_role=runtime_role, gateway_role=gateway_role, worker_role=self.settings.worker_role)`. That call already covers the identity inventory, the source structure digest, the `0004` structure digest, the functions and the grants. `ready()` keeps the realm comparison and the `wl_sources.catalog_state` digest check.
  - `ready()` does not read `wl_ingestion.instance_state`. An unactivated instance passes `/readyz`, and every import route answers `instance_not_ready` (503) from SQL. Part F documents this.
- `src/kurafolio/web_v2/api.py`:
  - On `ingestion`, `Boundary.request` and `create_app` serve the source routes exactly as on `sources`, because `create_set_v1` needs an enabled connection and only the source routes create one. They also serve the import routes from Part D.
  - On `identity` and `sources`, the import paths answer 404 `not_found` and are absent from `/api/v2/openapi.json`.

### Part B: the gateway caller

- `src/kurafolio/persistence/ingestion_store.py` (new), modelled on `SourceStore.call`:
  - `IngestionStore(config, catalog)` opens `Database(config, schema_mode="ingestion")` and keeps `catalog_digest(catalog)`.
  - `call(name, principal, payload, *, deadline) -> dict`:
    - Accepts only names in `ingestion_schema.GATEWAY` other than `admit_rate_v1`; anything else raises `IdentityError()` before any SQL runs.
    - Arguments are `(session_digest, user_id, credential_version, realm, catalog_digest, payload)`, cast as `text, uuid, int8, jsonb, text, jsonb`.
    - Each transaction sets the same per-transaction `statement_timeout` and `lock_timeout` as `SourceStore.call`.
    - Retries the whole transaction at most 3 times on `40001`/`40P01`, within the deadline.
  - `admit(principal, bucket)` calls `admit_rate_v1`, whose sixth argument is `text`, with `bucket` in `{'read', 'control'}`. It commits in its own transaction and returns nothing. The success value is `NULL`, so do not apply `SourceStore`'s "value is a dict" rule to it.
  - Result mapping:
    - `{'ok': True, 'value': dict}` returns the value.
    - `{'ok': False, 'code': c}` raises `RequestError(c, IMPORT_STATUS[c])` when `c` is a key of `IMPORT_STATUS`. Otherwise it raises `SourceError(c)` for codes in `lifecycle_v1.STATUS`, `IdentityError(c)` for codes in `identity.STATUS`, and `IdentityError()` for anything else.
    - A commit that fails after the function ran raises `import_commit_uncertain` (503) for `create_set_v1`, `decide_set_v1`, `accept_preview_v1`, `cancel_set_v1` and `reserve_member_v1`, and `IdentityError()` for reads.
  - No SQL text, parameter, payload or driver message reaches an exception or a log.
- `IMPORT_STATUS`: a code-owned `dict` in `src/kurafolio/web_v2/schemas.py`, copied by hand from `wire-contracts.json` `error_status`. A test compares it with the file. Do not load the bundle at runtime.

### Part C: DTOs and error codes

- `src/kurafolio/web_v2/schemas.py`: append to `ERROR_CODES`, in the order of the `wire-contracts.json` `Error` code enum, every code that `error_status` holds and `ERROR_CODES` lacks:
  - the 13 `import_*` codes
  - `length_required`

  Do not remove or rename an existing code.
- Validate request and response bodies with the frozen schemas already in `src/kurafolio/ingestion/contracts.py`, through `codec.validate(value, '<Name>')`. Write no Pydantic copy of any import DTO, because a copy could drift and APP-011D builds on these names.
  - Requests use `Create`, `Decide`, `Confirm` and `Cancel`. A schema failure is `import_invalid` (422).
  - Malformed JSON, duplicate keys and oversized bodies keep the Boundary's `invalid_input` (422) and `body_too_large` (413).
  - Responses use `SetResult`, `SetList`, `PreviewPage` and `Receipt`. A response that fails its schema is `internal_error` (500) and is never sent.
- OpenAPI: install a custom `app.openapi` that adds every `$defs` entry that the nine routes reach, directly or through references, to `components.schemas`, rewriting `codec-schema.json#/$defs/X` and `#/$defs/X` to `#/components/schemas/X`. Give each import route its request body and its success response through `openapi_extra`. The upload body is `application/octet-stream` with `format: binary`, and the error responses use the existing `Error` model.
- `src/kurafolio/web_v2/api.py`: `invalid_response` returns `internal_error` for import requests, as it does for source requests.

### Part D: Boundary changes and the eight JSON routes

- Route tables, consulted only when `settings.schema_profile == 'ingestion'`:

  | Path pattern | Methods | Bucket |
  |---|---|---|
  | `/api/v2/import-sets` | `GET`, `POST` | read, control |
  | `/api/v2/import-sets/[^/]+` | `GET` | read |
  | `/api/v2/import-sets/[^/]+/members/[^/]+/raw` | `PUT` | none (raw bucket inside `reserve_member_v1`) |
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
| `GET /api/v2/import-sets` | `read_sets_v1` with `{cursor: verified payload or null, limit, state or null}`; `limit` defaults to 50 and allows `1..50` | 200 `SetList`; replace `next` with `next_cursor = cursors.sign(key, next)`, or null |
| `GET /api/v2/import-sets/{set}` | `read_set_v1` with `{set_id}` | 200 `SetResult` |
| `PUT /api/v2/import-sets/{set}/decisions` | `decide_set_v1` with the validated `Decide` body; `body.set_id` must equal `{set}`, otherwise 422 `import_invalid` | 202 `SetResult` |
| `GET /api/v2/import-previews/{preview}` | `read_preview_v1` with `{cursor, limit, preview_id}` | 200 `PreviewPage`, with `next_cursor` as above |
| `POST /api/v2/import-previews/{preview}/confirm` | `accept_preview_v1` with `Confirm` plus `preview_id` | 200 `Receipt` |
| `POST /api/v2/import-sets/{set}/cancel` | `cancel_set_v1` with `Cancel` plus `set_id` | 200 `SetResult`; a lost race returns the set with its `receipt_id` |
| `GET /api/v2/import-receipts/{receipt}` | `read_receipt_v1` with `{receipt_id}` | 200 `Receipt` |

- Cursors: `cursors.verify(auth.cursor_key, token)` runs before any SQL read. A bad MAC or shape is 422 `import_invalid`.
- The `next` key and the `next_cursor` key are the only differences allowed between the SQL value and the wire DTO. If the SQL value has any other key the DTO lacks, stop and ask; do not drop or rename keys.

### Part E: the upload route (after Decisions 2 and 3)

- Boundary branch for `PUT /api/v2/import-sets/{set}/members/{member}/raw`, in this order:
  1. Existing header checks and route/method.
  2. `imports.upload_length(scope['headers'])`, mapping `length_required` to 411, `invalid_length` and `invalid_headers` to 400, `import_limit` to 413 and `unsupported_media_type` to 415. This branch skips the JSON content-type check and the JSON body read.
  3. An empty query (422) and canonical path UUIDs (422).
  4. Origin, then session, then CSRF, as in Part D.
  5. Hand off to the route with the original `receive`, which has not been called.
- Route `async def upload(...)`:
  1. `read_set_v1` for the current `revision` (Decision 3, option a).
  2. `reserve_member_v1` with `{action: 'reserve', set_id, member_id, expected_set_revision}`. A refusal here returns without calling `receive`.
  3. `receive_raw(request.receive, scope headers, entered=entered, total_seconds=UPLOAD_TOTAL_SECONDS, idle_seconds=UPLOAD_IDLE_SECONDS)`. The module constants are exactly `30.0` and `5.0`; tests patch them lower, and a unit test pins the values.
  4. Compute `raw_sha256` and `token = secrets.token_bytes(32).hex()`.
  5. `reserve_member_v1` with `{action: 'bind', set_id, member_id, fence, raw_sha256, raw_bytes, handoff_token_digest: sha256(bytes.fromhex(token)).hexdigest()}`.
  6. Build the metadata as the bind value plus `handoff_token`, validated as `Handoff`. Frame it with `runner_client.pack_input(metadata, context, raw, schema='Handoff')`, taking the context bytes from the interface the Decision 2 ticket provides.
  7. Send it with `handoff.post_handoff`.
  8. Return 202 with `read_set_v1`'s `SetResult`.
- `src/kurafolio/web_v2/handoff.py` (new): `post_handoff(settings.handoff, frame, *, deadline) -> dict`.
  - One HTTPS `POST /internal/v1/handoffs` with `Content-Type: application/octet-stream`, an exact `Content-Length` and no chunking or compression.
  - TLS 1.3 through `HandoffSettings.peer_tls().context()`, and `verify_peer` on the connection before the first body byte.
  - The deadline is the earlier of the bind's `expires_at` and 20 seconds.
  - The response must be a JSON `HandoffAck` of at most 16,384 bytes, validated with `codec.validate`.
  - Outcomes:
    - `owned`, `already_owned` or `stage_already_admitted`: success.
    - `reupload_required`: 409 `import_reupload_required`.
    - Any connect, TLS, timeout, status or shape failure: 503 `import_runner_unavailable`.
  - Never retry the hand-off with new bytes. A retry needs a new upload.
- Raw retention:
  - Keep the received bytes only in the local variables of `upload`.
  - `receive_raw` clears its own buffer. Clear every `bytearray` you create in a `finally` block, and drop the references before you return.
  - Never log or echo the bytes, the token, the context, the hash or the frame.
  - On any failure after `reserve` and before the hand-off, return the error and leave the member to the SQL deadline (`raw_deadline`, 120 s). Do not add a SQL call for it; IMP-007M owns slot recovery.
- The upload holds a Boundary slot (8 at most) for up to 30 seconds plus the hand-off. Keep that limit unchanged.

### Part F: documentation

- `docs/web-v2-imports.md`:
  - Replace "No route signs or verifies cursors yet" and the "Remaining acceptance" lines that this ticket settles.
  - Add a section listing the nine routes (method, path, request DTO, success status) and every error code with its status, taken from `error_status`. List the `serve` flags of the `ingestion` profile.
  - State plainly that the profile still needs activation (Decision 4) and a worker (IMP-007F) before an upload completes.
  - Say what `import_busy` (429) on the upload route means and what the client does (Decision 5). The API sends only the code and the existing generic message; it never picks a message per cause.
    - The user's raw rate window is used up (10 reservations in 300 seconds): wait and retry.
    - The user's one raw slot is held, either by an upload still in progress or by an earlier attempt whose slot could not be proved free. With the SQL on `main`, such a slot is released only when its set ends. The user cancels that set (or lets it expire), waits for cleanup, then starts a new set. This holds every upload of that user, not only that set.
    - Mark the second case as current behaviour pending IMP-007M, and do not describe a fix that IMP-007M has not decided.
- `docs/web-v2-sources.md`: one line saying the source routes are also served on `ingestion`.
- Keep the language and publication checks passing. Quote no non-English strings.

### Tests

Tests that need no database go in `tests/test_web_v2_imports.py` (new). They patch `kurafolio.web_v2.api.Auth` with a fake that records calls, and use `fastapi.testclient` or raw ASGI messages.

Real-PostgreSQL tests go in `tests/test_postgres_import_routes.py` (new), gated on `KURAFOLIO_INGESTION_TEST=1`. Each class builds its own environment the way `IngestionProviderPostgresTests` does:

1. `scripts/postgres.py test-identity-environment`.
2. `migrate-identity`, then `migrate-sources`, then `migrate-ingestion`.
3. Activate the synthetic instance through the owner connection, in a test-only helper that is never shipped: a wrapper catalog for the synthetic source fixture, a runtime profile digest, an enabled `workers` row for the worker role and `ready = true`.
4. Serve `create_app` on `ingestion` with a fake worker. The fake is an in-process TLS 1.3 server using disposable certificates, like the existing runner tests, that answers `/internal/v1/handoffs` with a `HandoffAck`.

Every test names its AC ID.

| AC | Case | Expected |
|---|---|---|
| 01 | `GET /api/v2/openapi.json` on `ingestion` | 9 import method/path pairs; each request and success schema equals the `wire-contracts.json` definition after `$ref` rewriting |
| 01 | Each of the 9 method/paths on `identity` and on `sources` | 404 `not_found`; none in OpenAPI; the source routes unchanged on `sources` |
| 01 | Source routes on `ingestion` | Served as on `sources` |
| 02 | Fake store records every call during the whole run | Names a subset of `ingestion_schema.GATEWAY`; no `INSERT`, `UPDATE`, `DELETE` or `TRUNCATE` text in `api.py`, `handoff.py` or `ingestion_store.py` |
| 02 | Real PG: `/readyz` on a migrated `0004` instance | 200; with one extra grant to the gateway role added by the owner connection, 503 |
| 03 | Each of the 9 routes with no cookie | 401 `authentication_required` |
| 03 | Each unsafe route with a wrong `Origin` / without `X-CSRF-Token` | 403 `origin_rejected` / 403 `csrf_rejected` |
| 03 | Real PG: user B reads, decides, cancels, confirms or uploads to user A's set, preview or receipt | 404 `not_found`; A's set `revision` unchanged |
| 03 | Real PG: decide and cancel with `expected_set_revision` one below current | 409 `import_stale`; nothing changed |
| 03 | Real PG: request with a session that a password change ended | The same status and code a source route gives for that session in the same test |
| 04 | `Content-Length: 10485761` | 413 `import_limit`, body not read |
| 04 | No `Content-Length` / `Content-Length: 0` / two lengths / length plus `Transfer-Encoding` | 411 `length_required` / 400 `invalid_length` / 400 `invalid_length` / 400 `invalid_length` |
| 04 | `Content-Encoding: gzip` / `multipart/form-data` / `Expect: 100-continue` | 415 `unsupported_media_type` |
| 04 | Body shorter than its length, then end of stream | 400 `invalid_length` |
| 04 | Idle longer than the (patched) idle limit / total longer than the (patched) total limit | 408 `request_timeout` |
| 04 | Exactly 10,485,760 bytes, real PG and fake worker | 202 `SetResult`; the worker received exactly those bytes once |
| 04 | Constants | `UPLOAD_TOTAL_SECONDS == 30.0`, `UPLOAD_IDLE_SECONDS == 5.0` |
| 04 | Real PG, after a successful upload and after a failed one | The owner connection finds the marker bytes in no `bytea` or `text` column of `wl_ingestion`, `wl_sources`, `wl_identity` or `wl_pg` |
| 05 | One success case per route, and one per refusal code that route can return | Status and code as in the expected values below |
| 06 | Upload with no session, wrong origin, missing CSRF, or reserve refused (`import_busy`) | Refusal sent; the ASGI `receive` callable, which raises `AssertionError` if called, was never called |
| 07 | Real PG: create, decide, confirm, cancel each sent twice with the same `operation_id` and body | Second answer byte-equal to the first; set `revision` and receipt list unchanged |
| 07 | Same `operation_id`, different body, for each of the four | 409 `import_operation_conflict` |
| 08 | A logging handler at `DEBUG` on the root logger for the whole module; a marker file of 4,096 random bytes | Neither the marker, its hex nor its base64 appears in any log record or response body; the token and the context appear in neither |
| 09 | Docs test | `docs/web-v2-imports.md` names all 9 method/paths and every `error_status` code |

Independent expected values, from `ingestion-api.md` and `wire-contracts.json`, not from the code under test:

- Status codes:
  - 409: `import_busy` is 429; `import_expired`, `import_stale`, `import_conflict`, `import_mapping_required`, `import_reupload_required` and `import_operation_conflict` are 409.
  - 413, 422 and 411: `import_limit` is 413; `import_invalid` and `import_evidence_unsupported` are 422; `length_required` is 411.
  - 503: `import_commit_uncertain`, `import_runner_unavailable` and `import_cleanup_pending` are 503.
- Budgets in a 300-second window:
  - The 31st control call (create, decide, confirm or cancel) by one user is 429 `import_busy`. Calls 1 to 30 are admitted.
  - The 61st read by one user is 429.
  - The 11th raw reservation by one user is 429.
  - A second concurrent upload by the same user while the first holds its raw slot is 429.
  - A 9th outstanding set for one user is refused by `create_set_v1`.
- `limit=0` and `limit=51` are 422; `limit=50` is allowed. A list cursor reused with a different `state` filter is refused.

Negative cases the reviewer will look for:

- An import route on a 404 profile does not touch the database. The fake `Auth` records no call.
- An import route never reads a body before `admit` returns (fake `admit` raises `import_busy`, and `receive` raises if called).
- An unknown `error_status` code from SQL never becomes a 200 or leaks text.

CI and the skip guard:

- Run `tests/test_postgres_import_routes.py` in the `postgres-ingestion` job with `--expect-skipped 0`, after installing `requirements-web-test.lock` as well as `requirements-pg-test.lock`.
- The `postgres` job also discovers `test_postgres_*.py` and skips these tests there, so raise its `--expect-skipped 118` by the number of new gated tests and update its comment.
- Also run the focused commands in Handoff, the full unit suite and `scripts/check_language.py`.

### Rollback

- Everything is additive behind `--schema-profile ingestion`. Reverting the pull request restores today's behaviour.
- This ticket installs no migration and changes no SQL, so a reverted build leaves no database change behind.
- After a revert, a database already at `0004` cannot be served at all, which is the state on `main` today. No data is lost.

### Do not touch

- `src/kurafolio/persistence/ingestion_schema.py`, `ingestion_migration.py`, `ingestion_restore.py` and the `0001` to `0004` providers and migration files: no SQL change in this ticket.
- `identity` and `sources` route behaviour, error codes and budgets; the SQLite application and legacy routes.
- The bounded reader in `web_v2/imports.py`: call it, do not fork it.
- The IMP-007F worker or launcher, the IMP-007M slot recovery, `tickets/ROADMAP.md` and other tickets' files.
- The non-English strings in `error_response`: do not copy them into tests or docs.

### Stop and ask if

- Any of Decisions 1 to 4 is still open on `main`, or was answered differently from what this plan assumes.
- `role_inventory`, `source_role_inventory` or `verify_inventory` refuses a correctly migrated `0004` database when called from the runtime or gateway role.
- A SQL function returns keys that its wire DTO does not have, other than `next`, or a code outside `error_status`, `lifecycle_v1.STATUS` and `identity.STATUS`.
- `reserve_member_v1` or `read_set_v1` changes the set `revision` during `RECEIVING`, which would make Decision 3's answer (a) unsafe.
- A requirement seems to need a SQL change, a new route, a new error code or a new DTO field.
- A real-PostgreSQL test cannot run in the isolated environment. A skipped test is not acceptance.

## Plan

- [ ] Part A: the `ingestion` runtime profile (context, identity, source store, config, CLI, Auth, Boundary).
- [ ] Part B: `IngestionStore` gateway caller and `admit` for `admit_rate_v1`.
- [ ] Part C: error codes, DTO validation from the frozen schemas, OpenAPI components.
- [ ] Part D: Boundary order and the eight JSON routes.
- [ ] Part E: upload route and hand-off (after Decisions 2 and 3).
- [ ] Part F: docs.
- [ ] Unit and real-PostgreSQL HTTP tests; CI job and skip counts.

## Decisions needed

The owner answers these before merging the plan. Items 1, 3, 4 and 5 need no change to this ticket's gated sections under the recommended option. Item 2 needs a new ticket, or a gated change here.

1. **Which ticket builds the ingestion runtime profile?** Sibling plans APP-011I (PR #82, its Decision 1) and APP-011E (PR #84, its Decision 1) depend on the answer.
   - What this ticket's routes need from the profile is listed in Context and in Build plan Part A:
     - `Database` at `0004_ingestion`
     - `IdentityStore` and `role_inventory`
     - `SourceStore`
     - `Settings` and the `serve` and operator flags
     - `Auth.__init__` and `Auth.ready` with `ingestion_migration.verify_inventory`
     - Boundary and route registration
     - the hand-off settings
   - The approved text already covers building it:
     - Requirements adopt the frozen r7 bundle, whose `sql-appendix.md` ("Profile integration and readiness") asks for exactly this branch.
     - AC-IMP-007E-01 needs the routes to exist "on the ingestion profile".
     - Requirements say a skipped real-PostgreSQL test is not acceptance.
     - IMP-007D, the only other ticket in that area, built the operator side alone.
   - Options:
     - (a) IMP-007E builds the profile as Build plan Part A describes. No gated text changes.
       - This ticket's `resources` should then add `identity-api`, the resource APP-011I holds for the same files (`api.py`, `auth.py`, `config.py`, `context.py`, `identity.py`), so the two builds cannot run at once. Changing `resources` of an approved ticket needs the owner's confirmation in its Log.
       - APP-011I adds IMP-007E to its `depends_on` (APP-011I option (a)) and later moves the profile from `0004` to `0005`.
     - (b) A new ticket builds the profile, and IMP-007E adds it to `depends_on`. This also needs the owner's confirmation in the Log. It splits one set of edits to the same files across two reviews and delays this P0 ticket.
     - (c) APP-011I builds a minimal profile. APP-011I is P1 and its Requirements do not list the work, so its gated text would change. The profile would also be designed before the routes that need most of it.
   - Recommendation: (a).

2. **Where does the API get the member's context bytes for the hand-off?** This blocks Part E (upload) only.
   - The r7 worker frame needs the context bytes, and `pack_input(..., schema='Handoff')` checks them.
   - `reserve_member_v1` with `action: bind` returns only their digest and length. No gateway function returns them, and the gateway role cannot read `wl_ingestion.members`.
   - Options:
     - (a) A new frontier SQL ticket changes the bind result of `reserve_member_v1` to also return the stored context bytes, for example as unpadded base64 under a new private key. The `0004` provider, its verified function text and the oracle vectors change with it. No public DTO changes. IMP-007E adds that ticket to `depends_on`, with the owner's confirmation in the Log.
     - (b) The worker reads the context from the database at claim time, and the API sends only metadata and raw bytes. This changes the r7 frame in `protocol-appendix.md` and the worker functions, so it is an r7 amendment that also touches IMP-007F.
     - (c) IMP-007E makes the SQL change in (a) itself. This changes Requirements (no SQL change is listed, and AC-02 says "only the r7 SQL functions"), so it needs a new Gate A.
   - Recommendation: (a). It keeps the frozen frame, keeps this ticket free of SQL and gives the SQL change its own frontier review. Because `0004` has never served an instance (no runtime profile could), changing its function text in place strands no database. Whoever plans that ticket confirms this.

3. **Where does the upload get `expected_set_revision`?** This blocks Part E only.
   - `reserve_member_v1` requires it, but the frozen upload request is `RAW_BINARY` with no query keys or headers.
   - Options:
     - (a) The route reads the set's current `revision` with `read_set_v1` and passes it straight to `reserve`. This needs no contract change.
       - The upload is still refused when the set has left `RECEIVING` (`import_stale`) or expired.
       - The only extra race is a change between the two calls, which `reserve` then refuses.
       - AC-03's stale-version refusals stay covered by decide and cancel.
     - (b) Add an `expected_set_revision` query key to the upload route. This amends the frozen r7 wire contract that APP-011D builds on, so it needs the owner's approval of that amendment.
   - Recommendation: (a). The plan has a stop point in case `RECEIVING` turns out to change the revision.

4. **Which ticket activates the ingestion profile on a database?**
   - Activation means installing the wrapper catalog and the runtime profile digest, registering the worker in `wl_ingestion.workers` and setting `wl_ingestion.instance_state.ready`.
   - No merged code does it, and no ticket's text assigns it. IMP-007F's text covers the worker and launcher but not this operator step.
   - Without it, every import route answers `instance_not_ready` on a real instance. This ticket's tests activate their synthetic database through a test-only helper.
   - Options:
     - (a) The owner files a new operator ticket, for example `operator activate-ingestion`. It verifies the `0004` inventory and the native-control readiness that r7 requires, then sets `ready` last. It depends on IMP-007E and IMP-007F.
     - (b) IMP-007F takes it, which changes IMP-007F's gated text. Its planner raises that.
     - (c) IMP-007E takes it. This changes this ticket's Requirements, and the step needs the worker identity that IMP-007F defines.
   - Recommendation: (a). This plan does not depend on the answer, but the V2 MVP cannot run without it.

5. **What does a client learn from `import_busy` on an upload?** Input from the IMP-007M plan (PR #85): the raw slot is held per user, and with the SQL on `main` an attempt whose slot could not be proved free blocks every reservation of that user until its set ends and cleanup releases the slot. The owner has not chosen IMP-007M's fix.
   - `reserve_member_v1` answers `import_busy` both for an exhausted raw rate window and for a held slot, and the wire contract gives the API only the code and a generic message. The API cannot tell the two apart.
   - Options:
     - (a) Keep the one code. `docs/web-v2-imports.md` (Part F) lists both causes and the action for each: wait for the rate window, or cancel the set that holds the slot, wait for cleanup and start a new set. APP-011D shows that guidance. The second action is marked as current behaviour until IMP-007M decides. No gated change.
     - (b) Add a distinct code for a held slot. This amends the r7 wire contract and the SQL in `reserve_member_v1`, which is a new SQL ticket or part of IMP-007M's follow-up, and changes APP-011D's input.
   - Recommendation: (a). It needs nothing beyond this ticket's AC-09, and it does not assume IMP-007M's answer. If IMP-007M's fix changes the action, that ticket updates the paragraph.

## Handoff

- State: Not started.
- Next step: Read `wire-contracts.json` and `ingestion-api.md` in the r7 bundle, then `web_v2/api.py` lines 440 to 475 (how the source routes are registered per profile) and `web_v2/imports.py`. Write the DTOs first and review them before any route code.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_postgres_migration.py' -v` and `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_ingestion_*.py' -v`; environment setup in [postgres-foundation.md](../docs/postgres-foundation.md) and [web-v2-imports.md](../docs/web-v2-imports.md)
- Gotchas: None recorded.
- Open questions: None.

## Log

- 2026-11-05 planner: created in the initial backlog plan.
- 2026-11-10 planner: owner re-confirmed this ticket for the V2 MVP on 2026-11-10; released (status ready), added starting files and verify commands.
- 2026-11-10 planner: added the dependency on IMP-007J, whose text requires its decision before routes are wired.
- 2026-11-13 planner: added the route table, the upload and error rules, and five acceptance criteria, all taken from the approved r7 contract. Scope is unchanged; the ticket no longer depends on a reader finding the route list in the local bundle.
- 2026-11-17 planner: the owner confirmed in conversation ("Confirm all six") the changes PR #64 made to this ticket after its approval. The approval in gate_approval covers the text as it stands now.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the bullet naming the r7 contract bundle, the "Real-PostgreSQL tests" bullet of Where to start and "What to build" from Context into Requirements and numbered the acceptance criteria AC-IMP-007E-01 to 09. Spec hash sha256:6db6a5ba54ea92a37456cd15bf51124498e73d86d19d24cb6da26d4dcbac652b, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:6db6a5ba54ea92a37456cd15bf51124498e73d86d19d24cb6da26d4dcbac652b.
- 2026-11-20 claude-code/opus-5.5: wrote the frontier Build plan from `main` at `a2f5f2b` (plan pull request: PENDING). Added findings to Context and four items to Decisions needed, including which ticket builds the ingestion runtime profile. Goal, Requirements and Acceptance criteria are unchanged.
