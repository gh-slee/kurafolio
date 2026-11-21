---
id: IMP-007T
title: Ask "keep, or mark closed?" for an account missing from a newer holdings file and store the answer
priority: P0
status: backlog
type: feature
parent: IMP-007
depends_on: []
resources: [ingestion-schema-sql, migration-order, postgres-schema]
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
updated: 2026-11-21
---

# IMP-007T: Ask "keep, or mark closed?" for an account missing from a newer holdings file and store the answer

## Goal

When a newer holdings file from a source no longer lists an account that an earlier file from the same source had, the owner's rule is that the account stays unchanged and the import preview asks whether to keep it or mark it closed. Today nothing asks, and nothing could store the answer: the import contract has no decision or fact that records "closed", so a closed account stays in Total at its last snapshot for ever. Add the question to the import preview, store a "closed" answer as an append-only accepted fact, and publish how the positions calculation reads it.

## Context

- Owner rule, recorded 2026-11-10 in [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md) ("Account absent from a newer broker file"): kept unchanged; the import preview asks "keep, or mark closed?". A position missing inside an account the file does cover is sold, without asking. The same rule is in the Requirements of [ANL-008](ANL-008.md) and [APP-011D](APP-011D.md).
- Why P0: APP-011D is an approved MVP ticket, and its Requirements say step 2 of the import page "names any account that earlier imports had and this file lacks, and asks whether to keep it unchanged or mark it closed". That page cannot ask until the import backend offers the question and stores the answer. On 2026-11-21 the owner confirmed adding this ticket to APP-011D's `depends_on` (Q27); the change and the owner's words are in APP-011D's Log.
- Filed from [ANL-008](ANL-008.md) Decision 9, which the owner accepted on 2026-11-20: "file an IMP-007 child for the preview question and the canonical fact, and have ANL-008's successor read it". ANL-008 keeps an absent account at its last snapshot and reads no "closed" state (its reader rule 5).
- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file). What it has today:
  - The decisions request is the closed `Decisions` shape in [codec-schema.json](../docs/specs/imp-007-r7/codec-schema.json), version 1, with exactly `mappings`, `new_entities`, `authorities` and `parents`. None of them records "closed".
  - [reconciliation.md](../docs/specs/imp-007-r7/reconciliation.md) keys coverage by the domain D = (S, canonical account, fact kind, scope selector) and says disjoint domains "may coexist; do not erase unrelated domains". An account the newer file does not list therefore keeps its own head; nothing marks it closed.
  - Accepted facts are append-only and pin their mapping; a later change never rewrites history ([persistence.md](../docs/specs/imp-007-r7/persistence.md)). `accepted_generation` increments once per set with new authoritative revisions or head changes.
- Merged code: the 0004 tables and functions are in `src/kurafolio/persistence/ingestion_schema.py` (`accept_preview_v1`, `_effects_v1`, `snapshot_heads`, `READ_TABLES`, `policies_ddl`) and `ingestion_migration.py` (grants). The inventory the code is tested against is the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`, checked by `tests/test_postgres_migration.py`. The Python decision codec is in `src/kurafolio/ingestion/` (`codec.py`, `contracts.py`, `approval.py`).
- Who builds the preview: the ReviewBundle that `prepare_preview_v1` uses is IMP-007P, and the upload route is IMP-007U. Both are filed on `main` as `backlog` tickets without Gate A. Absence detection most likely belongs where the ReviewBundle compares the incoming file with the accepted heads. This ticket's `depends_on` is still empty; it will likely need IMP-007P and, for the migration order, APP-011E (`0006`). Changing it after Gate A needs the owner's confirmation.
- Migration order: revision `0004_ingestion` is merged; APP-011I plans `0005_invite_status` and APP-011E plans `0006_user_preferences`. The owner chose the next free revision for this ticket (Decision 2). Hence `migration-order` and `postgres-schema` in `resources`. Each of `0005` and `0006` adds an operator `verify_inventory` and a runtime counterpart on the pattern of IMP-007W's `verify_runtime_inventory`, so that an `ingestion` instance at that revision passes readiness. IMP-007S's activation command lists the revisions the `ingestion` profile serves; the new revision will need adding there.
- Lock queue: `ingestion-schema-sql` is also held by IMP-007O, IMP-007Q, IMP-007R and IMP-007W (IMP-007N is `done`). They build one at a time.
- Positions reader: [ANL-008](ANL-008.md) adds `read_accepted_state` in `src/kurafolio/projection/accepted.py`, reading only `READ_TABLES`, `wl_pg.accounts` and `wl_pg.instruments`, with a `SUPPORTED_REVISIONS` list. A new fact table must be readable by the financial reader role under the same forced RLS, or the reader cannot see it.

## Requirements

- Scope: detect absent accounts while a holdings import is prepared, show them as a question in the import preview, accept a "keep" or "mark closed" answer for each with the other import decisions, store a "closed" answer as an append-only accepted fact, and document the read rule for the positions calculation. Includes the contract amendment to the live codec, SQL, grants, the inventory update and PostgreSQL tests.
- Non-goals: the import page (APP-011D shows the question); the change to the positions reader (a new positions ticket, filed with this ticket's Build plan, reads closure facts in `read_accepted_state` and adds the closure to the calculation's output; owner answer Q26, Decision 4); crypto, exchange or funding accounts that appear only in activity files; closing an account by hand outside an import; deleting or rewriting any stored fact.
- An account is absent from an incoming holdings file when all of these hold: it belongs to the same source connection as the file; it has a current holdings head from an earlier accepted import; it is not already closed; and the incoming file has no holdings coverage entry for it. An account with a coverage entry is covered, whatever the entry's declared status, and is never asked about. A file from a different connection never makes another connection's account absent.
- The preview lists each absent account with its label, the time of its last accepted snapshot and its position count. The question and the answers are covered by the preview digest, so a changed answer makes the old preview stale, as other decisions do.
- Answers: "keep" or "mark closed" for each absent account, sent through the import decisions and bound to the expected set revision. An unanswered question means "keep" (owner answer Q26, Decision 3): the preview shows the question with "keep" chosen, and confirming without changing it stores nothing. Confirmation is never blocked by an unanswered absent account.
- "Keep" stores nothing and changes no generation; the account stays at its last snapshot, as today.
- "Mark closed" appends one accepted fact per account to a new append-only accepted-fact table in `wl_ingestion`, written by `_effects_v1` from the accepted plan (owner answer Q26, Decision 1). It is not an authority-style decision record. It names the tenant, portfolio, connection, canonical account, the holdings head and snapshot revision it closes, and the closing time (the incoming file's evidence time, with its original token). It is pinned in the accepted plan bytes with the rest of the acceptance, increments `accepted_generation` exactly once for the set, and appears in the acceptance's facts event. It never deletes, rewrites or zeroes a snapshot, head, lineage row or source revision, and it inserts no zero position.
- Reopening: a holdings observation for the same account, from a later accepted import and newer than the closing time, makes the account current again; the closure applies only to the head it names. Closing an account that is not absent, or one that is already closed, is refused.
- Replaying the same acceptance has no effect. Unknown stays unknown: a closure says the account is no longer held as of its closing time and nothing else (no sale price, no proceeds, no cash).
- Migration (owner answer Q26, Decision 2): the new table, the changed functions and their grants go in a new revision, the next free one after `0005_invite_status` (APP-011I) and `0006_user_preferences` (APP-011E) when the Build plan is written. Revision `0004_ingestion` is not changed in place. The new revision has exact grants and inventory verification as `0004` has: an operator inventory check, and a runtime counterpart on the pattern of IMP-007W's `verify_runtime_inventory` so that an `ingestion` instance at the new revision still passes readiness.
- Isolation and grants: the fact is stored under the same tenant and portfolio forced RLS as the other accepted facts. The financial reader role can `SELECT` it; no role gains any other privilege; the runtime role still cannot write accepted facts directly.
- Read rule for the positions calculation, documented in `docs/web-v2-imports.md`: a holdings head whose latest snapshot revision is named by a closure, with no later head for that account, contributes no position, and the calculation names the closure (account and closing time) so the page can say why the account is gone. The new positions ticket implements this rule; this ticket does not change `src/kurafolio/projection/`.
- The contract change goes in the live artifacts, not the frozen bundle: the new decision entry and fact shape in the runtime codec schemas in `src/kurafolio/ingestion/contracts.py` (a new `Decisions` version if the shape changes), and the SQL additions in the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`. The r7 bundle files under `docs/specs/imp-007-r7/` and their index hash stay unchanged; `docs/web-v2-imports.md` records the amendment.

## Acceptance criteria

- [ ] AC-IMP-007T-01: Given accepted holdings for accounts P and Q from one connection, when a newer file from the same connection has coverage only for P, then the preview lists Q as absent with its label, last snapshot time and position count, and does not list P.
- [ ] AC-IMP-007T-02: Given the same accepted state, when a file from a different connection is prepared, then no account of the first connection is listed as absent.
- [ ] AC-IMP-007T-03: Given Q marked closed, when the set is accepted, then exactly one closure fact for Q names its head and snapshot revision and the closing time, `accepted_generation` increments once for the set, and Q's earlier snapshot, head, lineage and source revision rows are unchanged.
- [ ] AC-IMP-007T-04: Given Q kept, or given no answer for Q (which means "keep"), when the set is accepted, then no closure fact is stored for Q and the generations are the same as an acceptance without the question.
- [ ] AC-IMP-007T-05: Given an accepted closure, when the same acceptance is replayed, then nothing changes; when an answer changes after the preview was prepared, then that preview is stale and cannot be accepted.
- [ ] AC-IMP-007T-06: Given a closure of Q, when a later accepted file has newer coverage for Q, then Q has a new current head and the closure no longer applies to it; closing an account that is covered or already closed is refused.
- [ ] AC-IMP-007T-07: The financial reader role reads closure facts of its own tenant and portfolio only, never another's; no role gains another privilege; the `sql-inventory` in `tests/fixtures/ingestion/oracle.json` lists every new object and the migration verification passes.
- [ ] AC-IMP-007T-09: The closure table and its grants arrive in a new revision after `0006_user_preferences`, `0004_ingestion` and its expected structure digests are unchanged by this ticket, and on a synthetic instance migrated to the new revision both the operator inventory check and its runtime counterpart pass and refuse a drifted grant.
- [ ] AC-IMP-007T-08: [review] `docs/web-v2-imports.md` documents the question, the stored fact, the contract amendment and the read rule for the positions calculation, and no file under `docs/specs/imp-007-r7/` changes.

## Plan

- [x] Owner answers Decisions 1 to 4 (2026-11-21: all four recommendations accepted).
- [ ] Owner Gate A.
- [ ] Planning session writes the Build plan from merged code once IMP-007P (and the ReviewBundle it builds) is on `main`, sets `depends_on` and files the new positions ticket (Decision 4).
- [ ] Contract amendment and SQL with PostgreSQL tests.
- [ ] Preview question and decision codec; docs.
- [ ] Independent QA and Architect review (`risk: high`).

## Decisions needed

1. **How a "closed" answer is stored.**
   - (a) A new accepted fact in its own append-only table in `wl_ingestion`, written by `_effects_v1` from the accepted plan, with RLS and a reader grant.
   - (b) A new authority-style decision record next to `authority_links`, with no fact row.
   - Recommendation: (a). A closure changes what is held, so it should be a typed accepted fact with provenance and a generation bump, readable like the other facts.
   - **Resolved 2026-11-21: (a)** (owner answer Q26, quoted under item 4).
2. **Migration revision.**
   - (a) The next free revision after those already planned (`0005` APP-011I, `0006` APP-011E) when the Build plan is written, with exact grants and inventory verification as in 0004.
   - (b) Change revision `0004_ingestion` in place.
   - Recommendation: (a). 0004 is merged and may be installed; changing it in place would leave existing databases different from new ones.
   - **Resolved 2026-11-21: (a)** (owner answer Q26, quoted under item 4).
3. **An unanswered question.**
   - (a) It means "keep": the preview shows the question with "keep" chosen, and confirming without changing it stores nothing.
   - (b) Confirmation is blocked until every absent account has an explicit answer, as conflicts are in APP-011D.
   - Recommendation: (a). "Keep" is the data-preserving answer and today's behaviour, so an import never stalls on it; APP-011D still shows the question.
   - **Resolved 2026-11-21: (a)** (owner answer Q26, quoted under item 4).
4. **Which ticket changes the positions reader.**
   - (a) A new positions ticket, filed when this ticket's Build plan is written, that reads closure facts in `read_accepted_state` and adds the closure to the calculation's output.
   - (b) This ticket also changes `src/kurafolio/projection/` and the ANL-008 tests.
   - Recommendation: (a). It follows the 2026-11-20 decision ("ANL-008's successor reads it") and keeps the SQL lock and the projection resources apart.
   - **Resolved 2026-11-21: (a).** The owner was asked "IMP-007T ... has four decisions. Recommendations: (1) new append-only accepted fact table with RLS and a reader grant; (2) the next free migration revision after 0005/0006, not an in-place 0004 change; (3) an unanswered question means 'keep'; (4) a new positions ticket, filed with IMP-007T's Build plan, changes the positions reader. Accept all four?" and chose "Accept all (Recommended)". Requirements and AC-04 and AC-09 state each rule.
5. **Gate A.** The owner approves the Goal, Requirements and Acceptance criteria above, with the answers to items 1 to 4 written into them, or asks for changes.

## Handoff

- State: Not started. Decisions 1 to 4 were resolved on 2026-11-21; backlog until the owner gives Gate A.
- Next step: Owner Gate A; then a planning session writes the Build plan once IMP-007P is on `main`, and files the new positions ticket.
- Verify: `python3 scripts/tickets.py check`; `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`; `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_ingestion_*.py' -v`
- Gotchas: ANL-008's reader accepts only the revisions in its `SUPPORTED_REVISIONS` list; a new revision here must be added to it, as ANL-008's reader rule 1 says.
- Open questions: Gate A (Decisions needed item 5). `depends_on` (likely IMP-007P and APP-011E) is set by the Build plan.

## Log

- 2026-11-20 claude-code/opus-5.5: filed from ANL-008 Decision 9. The owner, asked "Accept all 11 recommendations?" for ANL-008, answered "Accept all (Recommended)", which includes filing an IMP-007 child for the preview question and the canonical fact. Priority P0 because the approved MVP ticket APP-011D already promises the question in its import review step. Filed in https://github.com/gh-slee/kurafolio/pull/83; Gate A not given.
- 2026-11-21 claude-code/opus-5.5: recorded the owner's answers of 2026-11-21 in plan pull request `plan/new-ticket-decisions`. Asked "IMP-007T ... has four decisions. Recommendations: (1) new append-only accepted fact table with RLS and a reader grant; (2) the next free migration revision after 0005/0006, not an in-place 0004 change; (3) an unanswered question means 'keep'; (4) a new positions ticket, filed with IMP-007T's Build plan, changes the positions reader. Accept all four?", the owner chose "Accept all (Recommended)". Gated changes: the non-goal names the new positions ticket; an unanswered question means "keep" and never blocks confirmation; "mark closed" writes to a new append-only accepted-fact table through `_effects_v1`; a new Migration bullet puts the table in the next free revision after `0006_user_preferences`, leaves `0004` unchanged, and requires an operator inventory check and a runtime counterpart on IMP-007W's pattern; AC-04 covers no answer; new AC-09 for the revision. Context: APP-011D now depends on this ticket (Q27), IMP-007P and IMP-007U are filed on `main`, the lock list. Spec hash sha256:fd61a31bac0ce6747a1c237d34e25da14386dbf8a91d63094acdb6ad5ec38340 becomes sha256:66ca4f184ece07cda36d3d9228fb6d7479ea0abc36b888f325948e160d6b0f69; still backlog, no Gate A.
