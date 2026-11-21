---
id: IMP-007O
title: Return the stored member context bytes from the bind result of reserve_member_v1
priority: P0
status: ready
type: feature
parent: IMP-007
depends_on: []
resources: [ingestion-schema-sql]
risk: high
size: S
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-21, Gate A on the text as written on PR #95's branch (Q31)"
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60
updated: 2026-11-21
---

# IMP-007O: Return the stored member context bytes from the bind result of reserve_member_v1

## Goal

The upload route (IMP-007U) must send the import worker one frame holding the hand-off metadata, the member's stored context bytes and the raw bytes, as the frozen r7 protocol requires. Today the bind step of `reserve_member_v1` returns only the digest and the length of those context bytes, and the gateway role cannot read `wl_ingestion.members`. Make a successful bind also return the stored context bytes, so the API can build the frozen frame without any new table access or wire change.

## Context

- Filed on 2026-11-20 from the IMP-007E plan (PR #87), Decisions needed item 2, option (a), which the owner chose.
- The bind result is built in `RESERVE_DDL` in `src/kurafolio/persistence/ingestion_schema.py` (around line 2788). It returns `version`, `job_id`, `set_id`, `member_id`, `fence`, `raw_sha256`, `raw_bytes`, `context_sha256`, `context_bytes` (the length, from `octet_length(mem.context_bytes)`), `realm_digest`, `expires_at` and `raw_deadline`.
- The worker frame (`POST /internal/v1/handoffs` in [protocol-appendix.md](../docs/specs/imp-007-r7/protocol-appendix.md)) carries the `Handoff` metadata, then the context bytes, then the raw bytes. `runner_client.pack_input(..., schema='Handoff')` checks all three.
- The `Handoff` DTO in [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json) has `additionalProperties: false`, and its `context_bytes` is an integer length. The new key therefore cannot be called `context_bytes`, and the API (IMP-007U) removes it before it validates `Handoff`.
- The frozen [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json) pins the function's signature (`text, uuid, bigint, jsonb, text, jsonb` returning `jsonb`), its grant (`identity_source_gateway`) and `search_path`, not its body. The body is pinned on the code side: `ingestion_migration.py` checks `EXPECTED_STRUCTURE_SHA256` and `EXPECTED_RESTORED_STRUCTURE_SHA256`, whose digest covers each function's `prosrc`, and `tests/fixtures/ingestion/oracle.json` holds the vectors.
- Changing the `0004` function text in place is safe only if no database outside disposable tests ran `operator migrate-ingestion` at `0004`. On `main` at `d902717` no runtime profile can serve `0004` (IMP-007E adds it) and the repository has no release tags, but that does not prove no operator ran the migration. Requirements make this a check with a stop point.
- Shares `ingestion-schema-sql` with IMP-007Q, IMP-007R, IMP-007T and IMP-007W, so these build one at a time. IMP-007N, which also held it, is `done`. IMP-007W edits `ingestion_migration.py` but not the expected structure digests; if it merges first, this ticket changes the digests as `main` then has them.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md). The r7 inventory is the frozen baseline [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json). The inventory the code is tested against is the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`, checked by `tests/test_postgres_migration.py`; it is the r7 baseline plus later approved additions.
- A successful `reserve_member_v1` call with `action: bind` also returns the member's stored `context_bytes`, encoded as unpadded base64 under one new private key. The key's name differs from every key of the `Handoff` DTO. Every other key and value of the bind result stays as it is, including `context_bytes` as the length.
- `action: reserve` results and every refusal of either action do not change.
- No DTO in `wire-contracts.json` or `codec-schema.json` changes. No function, argument, return type, grant, table, column, index or trigger is added or changed; only the body of `reserve_member_v1` changes.
- The change is made in place at revision `0004_ingestion`: the `0004` provider's function text, `EXPECTED_STRUCTURE_SHA256`, `EXPECTED_RESTORED_STRUCTURE_SHA256` and the oracle vectors change with it. The `0001` to `0003` providers stay byte-identical.
- Before building, confirm that no database outside disposable tests has run `operator migrate-ingestion` at `0004`. If that cannot be confirmed, stop and ask the owner whether a new revision is needed instead.
- The new key never carries raw bytes or the hand-off token. No error, notice or log line carries the context bytes.
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.

## Acceptance criteria

- [ ] AC-IMP-007O-01: A successful bind returns the new key, and its value decodes to exactly the member's stored `context_bytes`, whose SHA-256 equals `context_sha256` and whose length equals `context_bytes` in the same result.
- [ ] AC-IMP-007O-02: Every other key and value of the bind result, every `action: reserve` result and every refusal are unchanged; a test compares them with the vectors recorded before this change.
- [ ] AC-IMP-007O-03: The function's signature, return type, grant and `search_path`, and the frozen and oracle inventories, are unchanged; only the function text and the two expected structure digests change, and `tests/test_postgres_migration.py` passes against them.
- [ ] AC-IMP-007O-04: No DTO in `wire-contracts.json` or `codec-schema.json` changes, and the new key is not a property of `Handoff`.
- [ ] AC-IMP-007O-05: Opt-in PostgreSQL tests cover a bind at the smallest and the largest allowed context sizes (1 and 1,048,576 bytes).
- [ ] AC-IMP-007O-06: The pull request records the evidence that no database outside disposable tests ran `operator migrate-ingestion` at `0004`, or the owner's decision to use a new revision.
- [ ] AC-IMP-007O-07: `docs/web-v2-imports.md` says that the bind result carries the context bytes for the trusted API only.

## Plan

- [ ] Change the bind result in `RESERVE_DDL`; update the `0004` provider text, the expected structure digests and the oracle vectors.
- [ ] Add the PostgreSQL tests for each acceptance ID.
- [ ] Record the `0004` evidence; update the docs; run the PostgreSQL and full suites; open the PR.

## Decisions needed

- Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes. **Resolved 2026-11-21.** Asked "Gate A, tickets whose text is unchanged since filing (full text on PR #95's branch). Which do you approve exactly as written?" with this ticket listed at sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60, the owner selected "IMP-007O,IMP-007P,IMP-007U,IMP-007S" (Q31). `gate_approval` and `spec_approved` record it.

## Handoff

- State: Filed on 2026-11-20; backlog, waiting for the owner's Gate A and a Build plan.
- Next step: The planner writes the Build plan from `RESERVE_DDL` and `ingestion_migration.py` after Gate A.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: The bind result already uses the key `context_bytes` for the length; do not reuse it.
- Open questions: Gate A.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #87 from the owner's decision of 2026-11-20 on IMP-007E's question "Where should the bytes come from?": the owner chose "New SQL ticket (Recommended)": "a frontier SQL ticket makes the bind result also return the stored context bytes; keeps the frozen r7 frame." Status backlog; no Gate A yet.
- 2026-11-21 claude-code/opus-5.5: checked against `main` at `1a6ff31` in plan pull request #95. Only the Context's lock line was stale: IMP-007N is `done`, and IMP-007T and IMP-007W also hold `ingestion-schema-sql`. Gated sections unchanged (sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60); still backlog, no Gate A.
- 2026-11-21 claude-code/opus-5.5: recorded Gate A in plan pull request #95. Asked "Gate A, tickets whose text is unchanged since filing (full text on PR #95's branch). Which do you approve exactly as written?" (Q31) with this ticket listed at sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60, the owner selected "IMP-007O,IMP-007P,IMP-007U,IMP-007S". `gate_approval` set to "owner 2026-11-21, Gate A on the text as written on PR #95's branch (Q31)"; `spec_approved` set to sha256:664d5c3a0b844ef78057e53c216de1711001c867cff0a6165f97edf1ee4e1f60, which `tickets.py spec` reports as the current hash; status backlog becomes ready. Decisions needed item resolved. No Build plan yet; the planner writes it in a later pull request.
