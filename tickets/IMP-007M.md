---
id: IMP-007M
title: Decide how a re-upload gets back a raw slot that finish could not prove
priority: P0
status: ready
type: decision
parent: IMP-007
depends_on: [IMP-007C]
resources: [ingestion-schema-sql]
risk: high
size: S
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-12, release to write the options and a recommendation; the decision itself stays with the owner"
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
updated: 2026-11-18
---

# IMP-007M: Decide how a re-upload gets back a raw slot that finish could not prove

## Goal

When `finish_member_v1` ends an attempt with `reupload_required` but its launcher proofs are missing, `pending` or `failed`, the attempt keeps its raw slot. Each user has one raw slot, so the next `reserve` for that set returns `import_busy`. IMP-007C releases such a slot only after the set becomes terminal (cancel, rejection, commit or expiry), which can take up to 24 hours. The owner decides whether a live set should also be able to prove and release that slot, and by which call.

## Context

- Background only: the revision 1 planning draft [docs/specs/v2-drafts/WL-P0-007.md](../docs/specs/v2-drafts/WL-P0-007.md) (sha256:fa0971a0da787cb327484c92144e4a5ecd916db4ad0328e03b408d647190acd5), which the r7 bundle supersedes.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).

## Acceptance criteria

- [ ] AC-IMP-007M-01: The owner records a decision on whether and how a held slot of a fenced attempt in a live set is released.
- [ ] AC-IMP-007M-02: If a change is chosen, a follow-up implementation ticket names the function, its fencing and its PostgreSQL tests.

## Plan

- [ ] Write the options (for example: a normalize-scoped cleanup call on the finished attempt; a reserve that accepts proofs for the previous fence; keep the current terminal-only release) with a recommendation.
- [ ] Ask the owner and record the answer.

## Decisions needed

1. How does a user retry an upload in a live set while the previous attempt's raw slot is still held without proof? Options and a recommendation are still to be written.

## Handoff

- State: Not started. Released 2026-11-12 for the options write-up. Found while implementing IMP-007C: each normalize lease records `raw_slot`, and only `finish_member_v1` (with proofs) or `cleanup_set_v1` (terminal sets) releases it.
- Next step: Write the options with a recommendation.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: Never release a slot without proof that the attempt has no live child or raw buffer.
- Open questions: The decision above.

## Log

- 2026-11-12 claude-code/claude-opus-5-5: filed as a follow-up from IMP-007C.
- 2026-11-12 planner: owner released this ticket on 2026-11-12 so an agent writes the options; the owner still decides. It shares `ingestion-schema-sql` with IMP-007L, so it starts after that claim ends.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the bullet naming the r7 contract bundle from Context into Requirements and numbered the acceptance criteria AC-IMP-007M-01 to 02. Spec hash sha256:cf968d22fe6dcdfadf0a39af3744c41c18ba150851cc4b05611ef5f8f1fe2aaa, awaiting the owner's confirmation.
