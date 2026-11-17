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
spec: docs/specs/wealth-ledger-v2/P0/WL-P0-007.md
updated: 2026-11-17
---

# IMP-007E: Add authenticated V2 import HTTP routes

## Goal

Expose create, upload, read, decide, accept and cancel through authenticated FastAPI routes on the explicit sources profile, with CSRF/origin checks and bounded uploads.

## Context

- Frozen r7 contract bundle (local only until ENG-016): `work/wl-p0-007/r7/` in the primary checkout, notably `spec.md`, `sql-appendix.md`, `sql-inventory.json`, `contract-appendix.md` and `acceptance.md`.
- Pattern: `tests/test_web_v2_sources.py` and [web-v2-sources.md](../docs/web-v2-sources.md).
- The detailed draft spec is in the local planning package `docs/specs/wealth-ledger-v2/P0/WL-P0-007.md` until ENG-016 publishes it. If it is not in your checkout, work from this ticket and ask the owner.

### Where to start

- SQL fragments and the function inventory: `src/kurafolio/persistence/ingestion_schema.py`. Existing providers and operator commands: `src/kurafolio/persistence/migration.py`, `source_migration.py`, `migrations/`, `scripts/postgres.py`.
- Python reference checks and DTO codecs: `src/kurafolio/ingestion/` (`approval.py`, `codec.py`, `contracts.py`, `cursors.py`, `reconciliation.py`).
- V2 HTTP application and DTO style: `src/kurafolio/web_v2/api.py`, `web_v2/schemas.py`.
- Tests to extend: `tests/test_postgres_migration.py`, `tests/test_ingestion_*.py`, `tests/test_web_v2_api.py`, `tests/test_web_v2_sources.py`; vectors in `tests/fixtures/ingestion/oracle.json`.
- Public status and boundaries: [web-v2-imports.md](../docs/web-v2-imports.md). Product intent: [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md).
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
- The exact DTOs and the status code for each error are in `wire-contracts.json` in the r7 bundle. If that file is not in your checkout, stop and ask the owner; do not invent field names, because APP-011D builds its page on them.

## Acceptance criteria

- [ ] Each of the nine routes above exists on the ingestion profile, appears in `/api/v2/openapi.json` with its DTOs, and is absent on the `identity` and `sources` profiles.
- [ ] Routes call only the r7 SQL functions; no route writes tables directly.
- [ ] Unauthenticated, cross-tenant and stale-version requests are refused.
- [ ] Upload size/time bounds and raw-byte retention follow r7.
- [ ] HTTP tests cover each route and refusal.
- [ ] A refused upload (no session, wrong origin, missing CSRF token, no reservation) is answered without reading the body; a test proves it with a body that would fail if read.
- [ ] Replaying create, decisions, confirm or cancel with the same `operation_id` and payload returns the first answer and changes nothing; the same `operation_id` with a different payload is `import_operation_conflict`.
- [ ] No response or log line in the test run contains bytes of an uploaded file.
- [ ] `docs/web-v2-imports.md` lists the routes and their error codes, so APP-011D can be built from the public document.

## Plan

- [ ] Route DTOs from r7 `wire-contracts.json`.
- [ ] Implement routes.
- [ ] HTTP tests.
- [ ] Docs.

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
