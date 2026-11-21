---
id: IMP-007U
title: Add the authenticated V2 upload route
priority: P0
status: backlog
type: feature
parent: IMP-007
depends_on: [IMP-007E, IMP-007O]
resources: [v2-import-routes, identity-api]
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

# IMP-007U: Add the authenticated V2 upload route

## Goal

Let a signed-in user upload one CSV for a member of an import set through `PUT /api/v2/import-sets/{set}/members/{member}/raw` on the `ingestion` profile. The route refuses a request before it reads any body byte, receives the file within the r7 size and time bounds, and hands the bytes to the import worker with a one-use token; the client then polls the set. This route moved out of IMP-007E on 2026-11-20.

## Context

- Filed on 2026-11-20 when the owner moved the upload route out of IMP-007E (plan pull request #87). The earlier upload design, IMP-007E's Build plan Part E, is in that pull request at commit `95762ce`; the planner of this ticket checks it against the merged IMP-007E and IMP-007O code before reusing it.
- Acceptance IDs moved from IMP-007E: AC-IMP-007U-04 was AC-IMP-007E-04, AC-IMP-007U-05 was AC-IMP-007E-06 and AC-IMP-007U-06 was AC-IMP-007E-08 (widened to the token and the context). AC-IMP-007U-01, -02, -03, -07 and -08 apply IMP-007E's AC-01, -02, -03, -05 and -09 to this route.
- Findings from `main` at `d902717` (carried from the IMP-007E plan):
  - The worker frame (`POST /internal/v1/handoffs` in [protocol-appendix.md](../docs/specs/imp-007-r7/protocol-appendix.md)) carries the `Handoff` metadata, then the member's context bytes, then the raw bytes, and `runner_client.pack_input(..., schema='Handoff')` checks all three. The bind step of `reserve_member_v1` returns only the context digest and length; IMP-007O adds the bytes under a private key.
  - `reserve_member_v1` with `action: reserve` requires `expected_set_revision`, but the frozen request is `RAW_BINARY` and `query_semantics` gives it no query keys. The owner chose the answer in Requirements (IMP-007E D3, option (a)).
  - For unsafe methods, `Boundary.request` reads and parses a JSON body before the route runs (`web_v2/api.py:252-283`) and answers an octet-stream body with 415. The upload route needs its own Boundary branch.
  - `web_v2/imports.py` already has `upload_length` and the bounded reader `receive_raw`.
  - A worker checks a hand-off token as `sha256(bytes.fromhex(token))` in hex (`ingestion_schema.py:4660`).
  - The hand-off settings (worker URL and DNS name, instance ID, and the API's TLS files, with the client certificate URI `urn:wealth-ledger:instance:<instance_id>:peer:api`) and their `serve` flags are this ticket's. IMP-007E adds only `--worker-role`.
  - The IMP-007F plan (PR #86) answers a hand-off with 202 and a `HandoffAck`, or with status `contracts.ERROR_STATUS[code]` and the body `{"code": <code>}`.
- `import_busy` on an upload: `reserve_member_v1` answers it both for an exhausted raw rate window (10 reservations in 300 seconds) and for the user's one held raw slot. With the SQL on `main`, a slot whose release could not be proved is freed only when its set ends. The owner chose IMP-007Q (late-proof release) for that on 2026-11-20; until it lands, the docs describe today's behaviour.
- `resources` holds `identity-api` because the route edits `web_v2/api.py`, `config.py` and `__main__.py`, the files IMP-007E, APP-011I and APP-011E also change.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance. Use the claim's `isolation_id` and `port_base`.

### What to build

One route, under the ingestion profile only. On an `identity` or `sources` instance it does not exist (404), as the source routes behave today in `web_v2/api.py`.

| Route | Purpose | Answer |
|---|---|---|
| `PUT /api/v2/import-sets/{set}/members/{member}/raw` | Upload one CSV as `application/octet-stream` | 202 after bounded reception and hand-off to the worker; the client then polls the set |

Rules that reviewers will check:

- Order of checks on upload: route, method and headers first; then session, origin and CSRF; then the database reservation (`reserve_member_v1`); only then read the body. Never read a body for a request that will be refused.
- Upload body: exactly one `Content-Length`, 1 to 10,485,760 bytes; no multipart, `Content-Encoding` or `Transfer-Encoding`; 30 seconds total and 5 seconds idle. Missing length is 411, both length and chunked is 400, an encoding is 415, too large is 413. `web_v2/imports.py` (`receive_raw`) already implements the bounded reader; call it, do not write another.
- The route reads the set's current `revision` with `read_set_v1` right before `reserve_member_v1` (`action: reserve`) and passes it as `expected_set_revision`. The wire contract does not change: the request stays `RAW_BINARY` with no query keys.
- The hand-off of received bytes to the worker uses the one-use token from `reserve_member_v1` and the client in `src/kurafolio/ingestion/runner_client.py`. Until IMP-007F merges, test against a fake worker endpoint; the route's contract does not change when the real worker arrives.
- The frame's context bytes come from the bind result of `reserve_member_v1` as IMP-007O changes it. The API removes that private key before it validates the `Handoff` metadata.
- Errors carry a code only, with the status `wire-contracts.json` gives it. No file content, path, connection string, parser message, hand-off token or member context reaches a response or a log line.
- `import_busy` (429) has two causes on this route: the user's raw rate window is used up, or the user's one raw slot is held. The route sends the one code with the existing generic message and never picks a message per cause. `docs/web-v2-imports.md` lists both causes and what the client does for each.
- Rate limits are admitted inside the SQL functions (the raw bucket inside `reserve_member_v1`). Do not add a second limiter in Python.
- The exact DTOs and the status code for each error are in [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json) in the r7 bundle, and the route in [ingestion-api.md](../docs/specs/imp-007-r7/ingestion-api.md). Do not invent field names, because APP-011D builds its page on them.

## Acceptance criteria

- [ ] AC-IMP-007U-01: The route exists on the ingestion profile, appears in `/api/v2/openapi.json` with an `application/octet-stream` request body and its `SetResult` response, and is absent on the `identity` and `sources` profiles.
- [ ] AC-IMP-007U-02: The route calls only r7 SQL functions; it writes no table directly.
- [ ] AC-IMP-007U-03: Unauthenticated, cross-tenant and stale-set uploads are refused.
- [ ] AC-IMP-007U-04: Upload size/time bounds and raw-byte retention follow r7.
- [ ] AC-IMP-007U-05: A refused upload (no session, wrong origin, missing CSRF token, no reservation) is answered without reading the body; a test proves it with a body that would fail if read.
- [ ] AC-IMP-007U-06: No response or log line in the test run contains bytes of an uploaded file, the hand-off token or the member context.
- [ ] AC-IMP-007U-07: HTTP tests cover the route, each refusal and each hand-off answer of the worker.
- [ ] AC-IMP-007U-08: `docs/web-v2-imports.md` lists the upload route, its error codes, the hand-off settings the operator supplies, and both causes of `import_busy` with the client's action for each.

## Plan

- [ ] Hand-off settings and `serve` flags; Boundary branch for the upload path.
- [ ] Upload route: read the revision, reserve, bounded receive, bind, hand-off.
- [ ] Hand-off client with a fake TLS worker in tests.
- [ ] Docs, including the two causes of `import_busy`; unit and real-PostgreSQL tests.

## Decisions needed

- Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes.

## Handoff

- State: Filed on 2026-11-20; backlog, waiting for IMP-007E and IMP-007O, the owner's Gate A and a Build plan.
- Next step: The planner reads the merged IMP-007E and IMP-007O code and the earlier Part E design (PR #87, commit `95762ce`) and writes the Build plan.
- Verify: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_web_v2_*.py' -v`
- Gotchas: The bind result's `context_bytes` key is the length; the bytes are under IMP-007O's private key, which must not reach `Handoff` validation.
- Open questions: Gate A.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #87 from the owner's decision of 2026-11-20 on IMP-007E. The owner chose "Move upload out (Recommended)": "Upload route and its ACs move to a new ticket that depends on IMP-007O. IMP-007E (profile + 8 routes) can be built now and finishes sooner, unblocking APP-011I and APP-011E." The owner's "Accept both (Recommended)" for IMP-007E D3 (read the revision with `read_set_v1` before reserve, no wire change) and D5 (keep a single `import_busy` code and have the docs list both causes) is in Requirements. The context bytes come from IMP-007O ("New SQL ticket (Recommended)"). Status backlog; no Gate A yet.
