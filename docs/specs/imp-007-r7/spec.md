---
spec_id: WL-P0-007
revision: 6
review_status: NEEDS_REVIEW
execution_status: NOT_READY
priority: P0
change_size: LARGE
risk: CRITICAL
human_gate_a: null
implementation_authorized: false
---

# Reviewed imports that become accepted facts once

A user selects existing enabled source connections, uploads one or more supported CSVs, reviews mappings and conflicts, and confirms the complete selected set. Acceptance stores immutable financial facts, provenance, a receipt and one invalidation event without calculating a portfolio value or generating a report. Exact retries recover that receipt.

This is a coordinator PM/Architect contract candidate, not independent review. All eight directions B07-01..08 now have owner design sign-off. Human implementation Gate A remains null. The r2/r3/r4 sealed packets and all prior independent reports remain unchanged. This revision adds literal codecs, SQL/wire inventories and full synthetic fixtures; they are not shipped implementation.

## Preserved outcome and boundary

D01-D14 and accepted 003-006 contracts remain authoritative. One portfolio belongs to each user; it may contain multiple accounts and explicitly selected source connections. BTC Option A derives assumed-held quantities from unique eligible acquisitions in 008; 007 records facts, not wallet truth, contributions or profit. Holdings observations and activities remain separate. Funding/transfer/balance facts cannot become additional purchases. Domain precision, source times and unknown values survive exactly.

Python/FastAPI stays a modular monolith with bounded processes and PostgreSQL as the optional V2 target. Current SQLite/CLI, old source archives, current report editions and deployed services remain intact. No runtime LLM, API-provider activation, new real adapter, UI screens, quote retrieval, ETF retrieval, valuation, report rendering, legacy adoption or deployment is in this slice. PULL_API remains recognized but unavailable. Work 008-015 is not granted by this draft.

## Selected directions and contract details

B07-01: admit minimal typed staging before deleting new raw. Compatible mapping uses that stage; genuine reparsing requires re-upload.
B07-02: a separate trusted launcher uses an operator-approved existing Docker engine. API and financial worker have no Docker socket. This retains substantial launcher trust.
B07-03: one confirmation atomically accepts the entire selected set; no silent row or file subset.
B07-04: narrow database functions, ordinary financial queries read-only, separate accepted-fact generation.

B07-05..08 in decisions.md are also selected: additive discovery compatibility wrappers, fixed 24h normalized preview/capacity policy, explicit cross-connection evidence choices and dedicated restricted worker/private launcher channels. contract-appendix.md, sql-appendix.md, protocol-appendix.md and fixture-appendix.md address F07-01..04 as reviewable contract proposals. No coordinator self-check closes an independent finding or grants READY. New material findings still require owner direction sign-off.

## Contract map

- normalized-evidence.md: two-stage discovery, strict admission, lossless typed fields, provisional references and remapping after raw deletion.
- ingestion-api.md: finite endpoints, body handling, budgets, states and explicit user decisions.
- runner.md: launcher trust, image authority, peer authentication, containment, fencing and owned-child recovery.
- reconciliation.md: source/economic identities, coverage, comparisons, correction and ambiguity tables.
- persistence.md: tables, roles/functions, constraints, generations and mutation counts.
- failure-restore.md: replay ordering, races, faults, cleanup, additive migration and initialized empty-target restore.
- acceptance.md, oracle.json, traceability.json: fixed expected outcomes and evidence owners. All feature execution NOT_RUN.
- scope.json: proposed finite public paths and exclusive resources. It is not a write grant.

## End-to-end journey

1. The authenticated owner creates a bounded import set with exact connection/version and format selections. No connection is auto-created for a CSV.
2. Each member receives one bounded raw upload. Raw exists only in the controlled memory path. No generic multipart/temp-file persistence is permitted.
3. The fresh isolated child returns discovery data. Core checks bytes, provenance, format, limits and graph shape. Core creates only local provisional IDs, validates the minimal typed stage and persists that stage; then all raw copies are released and the child is reaped.
4. Unknown account/instrument mappings produce NEEDS_MAPPING. The owner explicitly chooses existing entities or proposes new entities. No accepted entity is created yet. Immutable mapping proposals plus deterministic core remapping produce a new plan digest without rerunning a parser.
5. Reconciliation either produces READY or explicit CONFLICT. A preview lists every member, new entity, mapping, accepted revision, historical-only fact, duplicate and diagnostic. No omitted/rejected row may be hidden behind READY.
6. Confirmation carries only the server preview ID/digest and operation ID. Within one transaction, authenticate, fence, check all state, validate the stored plan and write once. Accepted entity creation, revisions/heads, receipt, audit, generation and outbox are atomic.
7. COMMITTED means facts were accepted. Read-only receipt/history queries remain independent of later 008/013 work. A lost response recovers a proven existing receipt without parser execution.

## Prior exact-review repairs

[r5-repairs.md](r5-repairs.md) completes the closed review/worker/key contracts and fixed counterexamples requested by both r4 reviewers. It governs the identified shorthand inconsistencies without replacing frozen actual source contracts. No independent r5 approval is claimed.

## Gate conditions

The r2 review-resolution contains 19 review items grouped into seven overlapping workstreams, not 19 running-product defects. This r5 proposes remedies and literal expected states, but none is independently accepted yet. Required evidence includes actual PostgreSQL privilege/concurrency/fault/restore tests, real ASGI reception, native containment and compatibility checks on synthetic isolated resources. Missing Docker/platform evidence is NOT_RUN or unsupported, never PASS.

Before implementation: independently review the completed codecs/DTO/SQL signatures/path inventory and fixed oracles; resolve returned material findings with owner sign-off where needed, then obtain exact owner Gate A and serialized sole-writer reservation. Before publication: concrete diff, tests, independent QA, source-only image check, staged/history privacy checks and fresh push approval. Gate B, merge, release, deployment and private adoption remain separate.

The literal appendices and their JSON schemas/inventories supersede any shorthand in the carried-forward narrative summaries. They do not supersede frozen actual source contracts. The finite proposed public scope is59 paths, including two profile-routing files discovered through actual constructor/inventory code. There is no public implementation write claim. All 36 functional groups and independent r6 review remain NOT_RUN.

Image contexts require scripts/docker_context.py and its dedicated regression tests in the finite proposed scope: copy only the two reviewed new Dockerfiles plus already-audited source/locks, never the whole checkout/private work. The source-only main candidate gate remains mandatory. Synthetic child/launcher build evidence must pin the exact base image, source manifest and actual immutable result; fixture placeholder image hashes are not that evidence. All full planning vectors may be embedded into the one reviewed public tests/fixtures/ingestion/oracle.json; the private planning directory itself is never published.



## R6 exact-review corrections

[r6-repairs.md](r6-repairs.md) makes the three r5 corrections explicit without changing selected policies or frozen actual source. Native caller-owned capture time is checked separately from preserved source observation time. Read-only BasisPage regeneration does not use durable control-ack storage. All positive context files are the canonical wire bytes; dependent hashes are recomputed. Independent r6 review and human Gate A remain pending.

## Revision 7: selected native provenance source

The owner selected the no-new-field policy-token direction. r7-native-policy.md
supersedes the earlier native id_policy prose expectation only. Cumulative B07
policies, financial invariants and the exact 59-path scope remain unchanged. The
candidate's manifest/hash requires its own review and applicable human Gate A;
previous r6 implementation authority is not approval of this changed contract.
