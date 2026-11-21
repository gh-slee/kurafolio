---
id: IMP-007G
title: Prove V2 import acceptance: recovery, concurrency, containment and restore
priority: P0
status: ready
type: review
parent: IMP-007
depends_on: [IMP-007E, IMP-007F, IMP-007U, IMP-007S]
resources: []
risk: critical
size: L
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-10-31, IMP-007 spec r7 (covers all child tickets)"
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:664665500763474ff48fd3779d3e8052c27f181133a0db1193bd429171b5e2b0
updated: 2026-11-18
---

# IMP-007G: Prove V2 import acceptance: recovery, concurrency, containment and restore

## Goal

Independent end-to-end acceptance of AC-WL-P0-007-01..04 on a synthetic instance, including races, shared capacity, cleanup and restore into two independently empty targets.

## Context

- r7 [acceptance.md](../docs/specs/imp-007-r7/acceptance.md), [failure-restore.md](../docs/specs/imp-007-r7/failure-restore.md) and [oracle.json](../docs/specs/imp-007-r7/oracle.json). The r7 fixtures: [fixtures/case-matrix.json](../docs/specs/imp-007-r7/fixtures/case-matrix.json); the fixture files themselves are tracked in `tests/fixtures/ingestion/oracle.json`, as the bundle index explains.
- Background only: the revision 1 planning draft [docs/specs/v2-drafts/WL-P0-007.md](../docs/specs/v2-drafts/WL-P0-007.md) (sha256:fa0971a0da787cb327484c92144e4a5ecd916db4ad0328e03b408d647190acd5), which the r7 bundle supersedes.

### Where to start

- SQL fragments and the function inventory: `src/kurafolio/persistence/ingestion_schema.py`. Existing providers and operator commands: `src/kurafolio/persistence/migration.py`, `source_migration.py`, `migrations/`, `scripts/postgres.py`.
- Python reference checks and DTO codecs: `src/kurafolio/ingestion/` (`approval.py`, `codec.py`, `contracts.py`, `cursors.py`, `reconciliation.py`).
- V2 HTTP application and DTO style: `src/kurafolio/web_v2/api.py`, `web_v2/schemas.py`.
- Tests to extend: `tests/test_postgres_migration.py`, `tests/test_ingestion_*.py`, `tests/test_web_v2_api.py`, `tests/test_web_v2_sources.py`; vectors in `tests/fixtures/ingestion/oracle.json`.
- Public status and boundaries: [web-v2-imports.md](../docs/web-v2-imports.md). Product intent: [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md).

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance. Use the claim's `isolation_id` and `port_base`.

### What to check

The approved acceptance list has 36 cases, A07-01 to A07-36, in `acceptance.md` of the r7 bundle, with literal expected values in `oracle.json` (a different file from the tracked test vectors in `tests/fixtures/ingestion/oracle.json`, which hold the fixture inputs; see the [bundle index](../docs/specs/imp-007-r7/README.md)). Work through all of them on a disposable synthetic instance started from the OPS-021 compose file, or from the IMP-007D to 007F commands if 021 is not merged. They fall into six groups:

| Group | Cases | What it proves |
|---|---|---|
| Booking | A07-01 to 14 | First import, replay, overlap, duplicates, snapshots, corrections, multi-account and precision book the expected facts once |
| Tampering and staleness | A07-15 to 18 | An altered or outdated preview, a disabled source or an ended session books nothing |
| Isolation | A07-19, 26, 27, 33 | Two users never see each other's data; no file bytes remain in the database, logs or backups; roles can do only what is granted |
| Races and faults | A07-20 to 25, 35 | Concurrent confirm and cancel give one result; a failure at any statement leaves no partial booking |
| Limits and containment | A07-28 to 31, 36 | Upload limits at, below and above each threshold; the parser container cannot reach the network, host files or the Docker socket |
| Compatibility and restore | A07-32, 34 | The shipped application's paths are unchanged; a backup restores into two separate empty instances with unaccepted work inactive |

Derive every expected value yourself from the fixture files. Do not call the implementation to compute what it should return. A case you could not run is recorded as NOT RUN with the reason, never as passed.

## Acceptance criteria

- [ ] AC-IMP-007G-01: All four epic acceptance criteria pass with independently derived expected values.
- [ ] AC-IMP-007G-02: A results table lists each of A07-01 to A07-36 as PASS, FAIL or NOT RUN, with the command or test that produced it. It is committed under `docs/` or linked from the pull request, with no private data.
- [ ] AC-IMP-007G-03: Restore into two empty targets keeps unaccepted authority inactive.
- [ ] AC-IMP-007G-04: Findings are recorded; repairs go back through the owning child ticket.
- [ ] AC-IMP-007G-05: Each FAIL has a bug ticket that names the case, the expected value and the observed value. A FAIL in booking, isolation, or races and faults blocks OPS-015; the pull request says so plainly.
- [ ] AC-IMP-007G-06: The cases are automated where they can be, as opt-in PostgreSQL or Docker tests, so they run again in CI and for OPS-015.

## Plan

- [ ] Derive oracles independently from r7 fixtures.
- [ ] Run the scenarios.
- [ ] Record results in the Log; file bug tickets for defects.

## Handoff

- State: Not started.
- Next step: Read `acceptance.md` and `oracle.json` in the r7 bundle and build the 36-row results table with every row NOT RUN. Then start with the booking group, which needs only PostgreSQL.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_postgres_migration.py' -v` and `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_ingestion_*.py' -v`; environment setup in [postgres-foundation.md](../docs/postgres-foundation.md) and [web-v2-imports.md](../docs/web-v2-imports.md)
- Gotchas: Must be a different agent session from the implementers of 007A-F.
- Open questions: None.

## Log

- 2026-11-05 planner: created in the initial backlog plan.
- 2026-11-10 planner: owner re-confirmed this ticket for the V2 MVP on 2026-11-10; released (status ready), added starting files and verify commands.
- 2026-11-13 planner: added the six groups of the 36 approved acceptance cases and three acceptance criteria about recording results. Scope is unchanged.
- 2026-11-17 planner: the owner confirmed in conversation ("Confirm all six") the changes PR #64 made to this ticket after its approval. The approval in gate_approval covers the text as it stands now.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the bullet naming the r7 contract bundle, the "Real-PostgreSQL tests" bullet of Where to start and "What to check" from Context into Requirements and numbered the acceptance criteria AC-IMP-007G-01 to 06. Spec hash sha256:664665500763474ff48fd3779d3e8052c27f181133a0db1193bd429171b5e2b0, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:664665500763474ff48fd3779d3e8052c27f181133a0db1193bd429171b5e2b0.
- 2026-11-20 claude-code/opus-5.5: added IMP-007U and IMP-007S to depends_on in plan PR #87, because the upload route moved out of IMP-007E into IMP-007U and activation is IMP-007S. The owner confirmed the change on 2026-11-20 (Q17). Question: "Three approved tickets still list only IMP-007E/IMP-007F, but upload moved to IMP-007U and activation to IMP-007S. Proposed depends_on changes: APP-011D (import UI) adds IMP-007U; OPS-021 (one-command deploy) adds IMP-007S and IMP-007U; IMP-007G (end-to-end acceptance) adds IMP-007U, IMP-007S and the prepare ticket (IMP-007P, or IMP-007V if split). Confirm?" Owner chose: "Confirm all (Recommended)": "Recorded with your confirmation in each ticket's Log, in the IMP-007E plan PR (#87)." The same confirmation covers adding IMP-007V (the prepare step); that waits for a small follow-up PR after #86 and #87 merge, because IMP-007V is filed in #86 and `tickets.py check` rejects a dependency missing from the tree. Goal, Requirements and Acceptance criteria are unchanged; the spec hash still matches `spec_approved`.
