---
id: IMP-007S
title: Add an operator command that activates an ingestion instance
priority: P0
status: backlog
type: feature
parent: IMP-007
depends_on: [IMP-007E, IMP-007F]
resources: [ingestion-operator]
risk: critical
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

# IMP-007S: Add an operator command that activates an ingestion instance

## Goal

An instance migrated to `0004_ingestion` stays not ready. Nothing outside tests installs the wrapper catalog or the runtime profile digest, writes `wl_ingestion.instance_budgets`, registers the worker in `wl_ingestion.workers` or sets `wl_ingestion.instance_state.ready`, so every import call answers `instance_not_ready`. Add one operator command, for example `operator activate-ingestion`, that does all of it in the order r7 requires and sets `ready` last, so an operator can switch a real instance on without hand-written SQL.

## Context

- Filed on 2026-11-20 from the owner's answer to the activation question that the IMP-007E plan (PR #87, its D4) and the IMP-007F plan (PR #86, its D1) both raised.
- Findings from `main` at `d902717`:
  - `operator migrate-ingestion` (`src/kurafolio/web_v2/operator.py`, `persistence/ingestion_migration.py` `migrate_ingestion`) installs the schema and grants only and leaves `wl_ingestion.instance_state.ready` false.
  - `ingestion_migration.verify_inventory(conn, *, runtime_role, gateway_role, worker_role, quarantined=False)` checks the identity and source inventories and the `0004` structure digest.
  - `ingestion_restore` disables every worker row (`UPDATE wl_ingestion.workers SET enabled=false`), so a restored instance also needs this command before it serves imports.
  - The rate and capacity limits live in SQL (`QUOTA_LIMITS` in `ingestion_schema.py`); `instance_budgets` rows hold only counters and windows. `tests/test_postgres_migration.py` seeds `instance_state`, `instance_budgets` and `workers` through the owner connection today; that seeding is the only activation code in the repository.
- r7 rules this command follows: [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md) ("instance_state id=1, wrapper catalog bytes<=4194304 and exact digest, runtime profile digest valid; ready=true only after explicit inventory and native-control readiness. workers peer_identity<=256, role name trusted configured identifier, epoch>=1", and "Profile integration and readiness"), and [protocol-appendix.md](../docs/specs/imp-007-r7/protocol-appendix.md) ("Native controls and restart", including credential and CA rotation).
- It depends on IMP-007E (the runtime profile serves the instance it activates) and IMP-007F (the worker and the launcher that prove native-control readiness).
- `resources` holds a new `ingestion-operator` lock for `web_v2/operator.py` and the operator part of `web_v2/__main__.py`.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.
- One operator command, run with the operator (owner) role after `operator migrate-ingestion`, does these steps in this order:
  1. Runs `ingestion_migration.verify_inventory` on the target and refuses on any mismatch, before it writes anything.
  2. Installs the wrapper catalog bytes, their exact digest and the runtime profile digest in `wl_ingestion.instance_state`, within the r7 bounds (catalog at most 4,194,304 bytes).
  3. Writes the `wl_ingestion.instance_budgets` rows for the `read`, `control`, `raw` and `storage` buckets.
  4. Inserts or enables the one worker row in `wl_ingestion.workers`, with the trusted configured role name, a peer identity of at most 256 characters and `credential_epoch` of at least 1.
  5. Sets `wl_ingestion.instance_state.ready` to true last, only after the inventory check and native-control readiness have passed.
- A run that fails at any step leaves `ready` false.
- The command adds no table, column, function or grant, and changes no SQL. There is no startup DDL: the API and the worker never activate an instance themselves.
- No catalog bytes, key, certificate, password or connection string reaches the command's output or a log line.
- Not in scope: the runtime profile (IMP-007E) and the worker and launcher (IMP-007F).

## Acceptance criteria

- [ ] AC-IMP-007S-01: On a migrated synthetic `0004` instance, the command leaves the wrapper catalog with its digest, the runtime profile digest, the four budget rows, one enabled worker row and `ready = true`, and an import route then answers with a code other than `instance_not_ready`.
- [ ] AC-IMP-007S-02: `ready` is written last; a test that makes each earlier step or check fail finds `ready` still false.
- [ ] AC-IMP-007S-03: The command refuses an unmigrated database and one whose inventory differs from `0004`, and writes nothing to it.
- [ ] AC-IMP-007S-04: The command changes no SQL object; the inventory checked by `tests/test_postgres_migration.py` is unchanged.
- [ ] AC-IMP-007S-05: No catalog bytes, key, certificate or password appears in the command's output or in any log record of the test run.
- [ ] AC-IMP-007S-06: Opt-in real-PostgreSQL tests cover AC-01 to AC-03.
- [ ] AC-IMP-007S-07: The operator documentation describes the command, its inputs and the order of its steps.

## Plan

- [ ] Command and inputs in `web_v2/operator.py` and `web_v2/__main__.py`.
- [ ] Inventory check, catalog and digests, budgets, worker row, readiness check, `ready` last.
- [ ] Real-PostgreSQL tests; docs.

## Decisions needed

The planner turns these into options with a recommendation once the dependencies have merged; only the owner answers.

1. Where the wrapper catalog bytes and the runtime profile digest come from (a file the operator supplies, or a value the worker or launcher reports).
2. How the command proves native-control readiness, which needs an interface from the IMP-007F launcher.
3. Whether the command also covers credential and CA rotation (raise `credential_epoch` and recheck readiness, as protocol-appendix.md "Native controls and restart" asks) and re-activation after `ingestion_restore` disables the workers, or whether those are separate commands.
4. Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes.

## Handoff

- State: Filed on 2026-11-20; backlog, waiting for IMP-007E and IMP-007F, the owner's Gate A and a Build plan.
- Next step: The planner reads the merged IMP-007E and IMP-007F code and writes options for Decisions needed items 1 to 3.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: r7 sets `ready` only after native-control readiness, so a database-only check is not enough.
- Open questions: Decisions needed items 1 to 4.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #87 from the owner's decision of 2026-11-20 on "Nothing on main switches a real instance on: wrapper catalog, runtime profile digest, instance_budgets, the worker row and ready. Who builds activation?": the owner chose "New operator ticket (Recommended)": "e.g. `operator activate-ingestion`, depending on IMP-007E and IMP-007F; neither approved scope changes." Status backlog; no Gate A yet.
