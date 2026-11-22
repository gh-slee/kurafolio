---
id: IMP-007P
title: Build the ReviewBundle that the worker's prepare step passes to prepare_preview_v1
priority: P0
status: ready
type: feature
parent: IMP-007
depends_on: []
resources: [ingestion-review-bundle]
risk: critical
size: L
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-21, Gate A on the text as written on PR #95's branch (Q31)"
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766
updated: 2026-11-21
---

# IMP-007P: Build the ReviewBundle that the worker's prepare step passes to prepare_preview_v1

## Goal

After every member of an import set is normalized, the import worker must turn the set's stages, decisions and current references into a `ReviewBundle` (a review document and, when r7 requires one, a complete Plan) and pass it to `prepare_preview_v1`. No merged code builds one, so no set can reach a preview without a human step. Build a deterministic builder that follows the r7 reconciliation rules and reproduces the oracle review and plan vectors exactly.

## Context

- Filed on 2026-11-20 from the IMP-007F plan (PR #86), its Decision D2, option (a), which the owner chose.
- Caller: IMP-007V, the import worker's prepare step (in IMP-007F's `src/kurafolio/ingestion/worker.py`), which depends on this ticket and on IMP-007F. Under one prepare lease it reads every basis resource with `read_plan_basis_v1` (cursor paging, `limit` 50), calls this builder, checks the result with `approval.validate_review_bundle`, and passes `codec.encode(bundle)` as `p_bytes` to `prepare_preview_v1`. A prepare lease lasts at most 60 s and is never renewed (IMP-007F D6), so the builder must finish well inside one lease. IMP-007V imports this module and does not change it; this ticket does not change the worker.
- `read_plan_basis_v1` serves eight resources on merged `main`, not six: `inputs`, `entities`, `mappings`, `revisions`, `heads`, `authorities`, `decisions` and `context`. The last two came with r7-A2 (the stored Decisions as a header and ordered items) and r7-A3 (one `prepare_context` row with the Plan scope, `realm_digest`, `incarnation`, `restore_epoch`, `set_expires_at` and the ordered `pinned_sources`). The merged `BasisPage`, `BasisCursor`, `BasisRow` and `ReadBasisRequest` in `contracts.py` (`_WIRE`) carry all eight, although `docs/specs/imp-007-r7/wire-contracts.json` still lists six. IMP-007V's Context still says six; its planner should read this ticket's Build plan.
- Contracts, all in the r7 bundle: [reconciliation.md](../docs/specs/imp-007-r7/reconciliation.md) (identity keys, the source revision and activity table, the snapshot and coverage table), [normalized-evidence.md](../docs/specs/imp-007-r7/normalized-evidence.md) and [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md). DTOs: `ReviewBundle` (`{version: 1, review: ReviewDocument, plan: Plan | null}` in `src/kurafolio/ingestion/contracts.py`), `ReviewDocument`, `BasisPage`, `PreparePreviewRequest` (`payload_bytes` at most 16,777,216) in [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json), `Plan` in [codec-schema.json](../docs/specs/imp-007-r7/codec-schema.json).
- Merged code to build on (`main` at `1274b54`; no change under `src/` since `d902717`):
  - `approval.py`: `validate_review_bundle(data, *, stages)`, `verify_staged_material`, `verify_proposals`.
  - `mapping.py`: `MappingIndex`, `proposed_body`, `compatible`, `verify_target_version`.
  - `reconciliation.py`: `source_revision_key`, `project_record`, `financial_projection`, `reconcile_revision` (`RevisionDecision`), `snapshot_order`.
  - `codec.py` (`encode`, `validate`, `decode`, `digest`, `sha256`, `compare_time`) and `cursors.py`.
  - The checks in `prepare_preview_v1` (`ingestion_schema.py`, IMP-007L, with the r7-A1 to r7-A4 amendments recorded in IMP-007L), which accept or refuse a bundle against the stored stages, decisions and generation pins: `_PREPARE_REVIEW_ROWS`, `_INITIAL_REVIEW_CANDIDATES`, and for a READY bundle `_validate_plan_v1` (with `_plan_material_sql` and `_plan_local_relations_sql`) and `_references_v1` (with `_stream_authority_sql`).
- Expected values: the oracle vectors in `tests/fixtures/ingestion/oracle.json`. Cases with review or plan vectors: `authority-only`, the four `branch-*` cases, `metadata-native` (plan only; its READY review is `review-metadata-native-ready.json`), `mixed-set`, `snapshot-historical-t1` and `snapshot-seed-t2`, plus `plan-first-use.json` and `plan-native-first-use.json` (their READY reviews are `review-parser2-ready.json` and `review-native-ready.json`). The initial NEEDS_MAPPING reviews are `review-parser2-initial.json`, `review-native-initial.json` and `review-metadata-native-initial.json`; `review-bundle-initial.json` and `review-bundle-first-use.json` wrap the parser2 ones. Their inputs are the matching `*-minimal.json`, `*-decisions.json`, `*-context.json`, `*-prestate.json` and `*-discovery.json` entries; the `effect-oracles.json` cases name each branch case's accepted prestate. `builtin-inputs.json` holds the expected facts for the two example files (`wealthsimple_expected`, `bull_expected`) that IMP-007V's AC-IMP-007V-01 checks (formerly IMP-007F's AC-04), and the `large-basis-*` entries the largest basis.
- `tests/test_postgres_migration.py` drives `prepare_preview_v1` with oracle bundles (`prepare_preview_call`, the `basis_call` helpers). Those helpers show how the basis pages look for each case.
- `resources` holds a new `ingestion-review-bundle` lock. It does not overlap IMP-007F's `v2-import-worker` files or the `ingestion-schema-sql` lock.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.
- The builder lives in its own new module, `src/kurafolio/ingestion/review_bundle.py`. It takes the decoded basis pages of one prepare lease (every resource `read_plan_basis_v1` serves, with their generation pins) and returns one `ReviewBundle` value that passes `codec.validate(value, 'ReviewBundle')`.
- It follows `reconciliation.md`, `normalized-evidence.md` and `contract-appendix.md`. Where the merged helpers in `approval.py`, `mapping.py` and `reconciliation.py` implement a rule, the builder calls them; it does not change their behaviour or their tests.
- It is deterministic: the same basis gives byte-identical `codec.encode` output whatever the page size or page order of delivery. It reads no clock, randomness, environment, file, database or network. Values that do not come from the basis come from the r7 rules or from explicit arguments the caller passes.
- Finance rules: amounts stay `Decimal` strings exactly as staged; unknown values stay unknown and are never zero; no contribution is inferred from holdings or purchase spend; no wallet total or opening balance is inferred; coverage and membership stay as staged (for example `partial` and `unknown`). Every fact in the review and Plan traces to a stage, a decision or a current reference in the basis.
- It never builds a partial or guessed bundle. A basis it cannot reconcile, or a bundle over 16,777,216 encoded bytes, raises a fixed error code and returns nothing.
- It builds the largest oracle basis (`large-basis-*`) in well under one prepare lease; the acceptance bound is 10 seconds on the CI runner.
- Not in scope: the worker's prepare loop and lease handling (IMP-007V), any SQL, grant or DTO change, and the frozen r7 bundle and `oracle.json`, which stay as they are. If an oracle vector seems wrong, or a case cannot be expressed as basis pages, stop and ask.

## Acceptance criteria

- [ ] AC-IMP-007P-01: For every oracle case with a `*-review.json` or `*-plan.json` vector, and for `plan-first-use.json` and `plan-native-first-use.json`, a test builds the basis pages from that case's oracle inputs, and the builder's review and Plan equal the vectors byte for byte after `codec.encode`.
- [ ] AC-IMP-007P-02: Every bundle the builder produces passes `approval.validate_review_bundle`, and an opt-in real-PostgreSQL test shows that `prepare_preview_v1` accepts it for the first-use, native first-use, `branch-*`, `snapshot-*`, `authority-only` and `mixed-set` cases.
- [ ] AC-IMP-007P-03: For the stages of `examples/data/wealthsimple-holdings.csv` and `examples/data/bull-orders.csv`, the review's facts equal `wealthsimple_expected` and `bull_expected` in oracle `builtin-inputs.json`, and no contribution or wallet balance appears.
- [ ] AC-IMP-007P-04: Building twice from the same basis, and from the same basis delivered with page sizes 1, 7 and 50, gives identical bytes.
- [ ] AC-IMP-007P-05: A missing basis resource, a stage whose digest does not match its row, a decision for an unknown member or entity, pages with different generation pins, and an encoded bundle over 16,777,216 bytes are each refused with a fixed error code, and no bundle is returned.
- [ ] AC-IMP-007P-06: A static test and a test that patches the clock, randomness, environment, file and socket APIs to raise show that the module reads none of them.
- [ ] AC-IMP-007P-07: The `large-basis` oracle case builds in under 10 seconds on the CI runner.
- [ ] AC-IMP-007P-08: [review] Every fact in each produced review and Plan traces to the basis; no value is invented, rounded or defaulted to zero; a reviewer checks this against `reconciliation.md`.
- [ ] AC-IMP-007P-09: `docs/web-v2-imports.md` says what the builder decides, which review states it produces and its limits.

## Build plan

- Based on: `main` at `1274b54` (2026-11-21). Nothing under `src/kurafolio/ingestion/`, `src/kurafolio/persistence/ingestion_schema.py` or `tests/fixtures/ingestion/` changed since `d902717`.
- Owner decisions, recorded 2026-11-21 under Decisions needed: D1 is (b), so the builder also produces CONFLICT and NEEDS_MAPPING reviews at a reconciling set and Part G with its tests is required; D2 is (a), so an initial review always offers a proposed new entity beside the existing candidates (Part C).
- The planner checked the review layout of Part F against every READY oracle review (all eleven reproduce row for row, with their `content_digest`, `plan_digest` and `review_content_digest`), the two head key formulas of Part E against `ab5991be…` and `87eb6e28…`, that every case's decisions digest equals its Plan's `decision_digest`, and that every existing-mode target body is in the oracle. A builder repeats none of this; it is recorded so the reviewer knows what was checked.
- Build order: Part A, then B to F with the AC-01 tests case by case (first-use, native, metadata-native, mixed-set, snapshot-seed-t2, then the cases with an accepted prestate), then G, H and the other tests, then the real-PostgreSQL tests, then docs. One pull request.

### Files

- `src/kurafolio/ingestion/review_bundle.py` (new): the whole builder. Imports only `__future__`, `collections`, `copy`, `dataclasses`, `functools`, `itertools`, `operator`, `typing`, and from this package `approval`, `codec`, `contracts`, `mapping` and `reconciliation`. Nothing else (AC-06).
- `tests/test_ingestion_review_bundle.py` (new): AC-01, 03, 04, 05, 06 and 07, and the Part G cases. Core-only; runs in the default suite.
- `tests/test_postgres_review_bundle.py` (new, opt-in with `KURAFOLIO_INGESTION_TEST=1`): AC-02.
- `tests/fixtures/ingestion/review-bundle-cases.json` (new): literal expected reviews for the Part G cases. `oracle.json` is not edited.
- `docs/web-v2-imports.md`: a new subsection "Review bundle builder" after the paragraph on `read_plan_basis_v1` and `prepare_preview_v1` (around line 389), and one sentence in "Remaining acceptance" (AC-09).
- `tickets/IMP-007P.md`: this ticket only.

### Interfaces

```python
RESOURCES = ('inputs', 'entities', 'mappings', 'revisions', 'heads', 'authorities', 'decisions', 'context')
ERROR_CODES = frozenset({'import_invalid', 'import_stale', 'import_limit', 'import_conflict',
                         'import_mapping_required', 'import_evidence_unsupported'})

def build_review_bundle(pages, *, preview_id, new_id):
    """Return one checked ReviewBundle value built from one prepare lease's basis pages."""

def basis_stages(pages):
    """Return {member_id: canonical Minimal bytes} for validate_review_bundle(stages=...)."""
```

- `pages`: a list or tuple of decoded `BasisPage` values, the `value` of each successful `read_plan_basis_v1` call, for all eight resources, in any order and of any page size.
- `preview_id`: a canonical UUID string. It becomes `review.id` and `plan.preview_id`. The caller makes a fresh one for each attempt (IMP-007V: `str(uuid.uuid4())`).
- `new_id`: a callable that takes one key tuple and returns a canonical UUID string. Keys:
  - `('entity', member_id, entity_kind, local_id)`: the target of the proposed candidate for one source entity in a NEEDS_MAPPING review.
  - `('revision', member_id, collection, local_id)`: the new accepted revision of one fact whose action is `append`, `correction`, `void` or `historical`, in a READY review only.
  - `('group', member_id, 'records', local_id)`: the new economic group of one appended activity record, in a READY review only.
  - The builder calls it at most once per key and only for those cases. It never calls it for a duplicate, a CONFLICT review or anything else. IMP-007V passes `lambda key: str(uuid.uuid4())`; tests pass a dict lookup with the oracle literals.
- Return: a dict `{'version': 1, 'review': ..., 'plan': ... | None}` that has passed `codec.validate(..., 'ReviewBundle')` and `approval.validate_review_bundle(codec.encode(bundle), stages=basis_stages(pages))`.
- Errors: only `contracts.IngestionError(code, field)` with `code` in `ERROR_CODES` and `field` a fixed path from the tables below. The message is the code; no source text, value or ID goes into it. Wrap the whole build: an `IngestionError` whose code is not in `ERROR_CODES`, and any `KeyError`, `IndexError`, `TypeError`, `ValueError` or `AttributeError`, becomes `IngestionError('import_invalid', '$')` raised `from None`. Nothing is returned on any error.
- No module state, cache or global; no logging. Every intermediate structure is local to one call.
- Complexity: index revisions by `source_key_digest`, heads by `(kind, key_digest)`, entity rows by `(member_id, entity_kind, local_id)` and facts by `(member_id, collection, local_id)`. No scan of all revisions per fact.

### Part A: basis assembly and refusals

Do these checks first, in this order. Each failing check raises the code shown and the build stops.

| # | Check | Code, field |
|---|---|---|
| A1 | `preview_id` passes `codec.validate(preview_id, 'UUID')` | `import_invalid`, `$.preview_id` |
| A2 | Each page passes `codec.validate(page, 'BasisPage')` | `import_invalid`, `$.pages` |
| A3 | All pages have equal `version`, `job_id`, `fence`, `set_revision`, `accepted_generation`, `mapping_generation` and `control_generation` | `import_stale`, `$.pages` |
| A4 | Every resource in `RESOURCES` has exactly one page with `next_cursor` null | `import_invalid`, `$.pages` |
| A5 | Each non-final page has at least one row; its cursor's `resource` and pins equal the page's; its `after_key` equals the key (below) of the page's last row; all cursors in the call have the same `expires_at` | `import_invalid`, `$.pages` |
| A6 | Row kinds match the resource: `inputs` only `input`, `entities` only `entity`, `mappings` only `mapping`, `revisions` only `revision`, `heads` only `head`, `authorities` only `authority`, `decisions` only `decisions_header` and `decision_item`, `context` only `prepare_context` | `import_invalid`, `$.pages` |
| A7 | No two rows of one resource have the same key | `import_invalid`, `$.pages` |
| A8 | `context` has exactly one row; `inputs` has 1 to 4 rows; the input IDs equal the `member_id`s of `context.pinned_sources` | `import_invalid`, `$.context` |
| A9 | For each input row, `codec.sha256(codec.encode(row['minimal'])) == row['digest']`, and `codec.decode(codec.encode(row['minimal']))` succeeds (full Minimal checks) | `import_invalid`, `$.inputs` (a decode error keeps its own code) |
| A10 | `decisions` has no rows, or exactly one `decisions_header` and, for each of `authorities`, `mappings`, `new_entities` and `parents`, items with ordinals exactly `0` to `counts[name] - 1`. Rebuild the document as `{version, operation_id, expected_set_revision}` from the header plus one list per collection in ordinal order. It must pass `codec.validate(doc, 'Decisions')`, and `codec.digest(doc)` must equal the header's `digest` | `import_invalid`, `$.decisions` |
| A11 | With decisions, `int(expected_set_revision) + 1 == int(page set_revision)` | `import_stale`, `$.decisions` |
| A12 | Every `member_id` in decisions `mappings`, `new_entities` and `parents` is an input; every `(entity_kind, local_id)` in `mappings` and every `(kind, local_id)` in `new_entities` names an entity of that member's Minimal; every `parents` item names a fact of that member (`membership` only with `local_id` `'0'` and a non-null membership); no fact has two `parents` items; every `form: incoming` reference in `authorities` names a fact of an input | `import_invalid`, `$.decisions` |

Row keys, the same strings the SQL pages by (`ORDER BY key COLLATE "C"`; Python `str` order on these ASCII keys is the same):

| Resource | Key |
|---|---|
| `inputs` | `id` |
| `entities` | `f"{member_id}:{entity_kind}:{local_id:0>8}:{target id}:{target version}"` |
| `mappings` | `f"{member_id}:{entity_kind}:{local_id:0>8}"` |
| `revisions` | `revision.id` |
| `heads` | `f"{head.kind}:{head.key_digest}"` |
| `authorities` | `link_id` |
| `decisions` | header `'0'`; items `prefix + f"{ordinal:03d}"`, prefix `1:` authorities, `2:` mappings, `3:` new_entities, `4:` parents |
| `context` | `'0'` |

After the checks, sort each resource's rows by key and work only from those sorted lists. Members are processed in ascending `member_id` order (the SQL's member order).

The `mappings` resource (the latest accepted mapping for each incoming source identity) is checked by A2 to A7 and not used further. r7-A4 makes every READY Plan carry the user's explicit Decisions, and the initial review must offer every eligible existing target, which the `entities` resource already lists.

### Part B: which review the builder produces

The owner chose D1 (b) on 2026-11-21, so the builder produces all three states.

| Basis | Outcome |
|---|---|
| No decisions (the set is `NORMALIZING`) | NEEDS_MAPPING, initial layout (Part C) |
| Decisions, and a source entity has no mapping, or an existing-mode mapping names a target that is not an `entities` row of that entity | NEEDS_MAPPING, initial layout, decisions ignored (Part G) |
| Decisions, a proposed-mode mapping whose `mapping.proposed_body(...)` digest differs from `target.version`, or that `proposed_body` refuses | refuse with `import_conflict` (or the helper's code), `$.decisions` |
| Decisions, two mappings for one entity (`MappingIndex` raises) | refuse `import_conflict`, `$.decisions` |
| Decisions, every entity mapped, every fact classified by Part D without `conflict` | READY with a Plan |
| Decisions, every entity mapped, at least one fact classified `conflict` | CONFLICT, no Plan (Part G) |

### Part C: entity rows and candidates

- Source entities of a member, in this order: `accounts` (kind `account`), `assets` (kind `instrument`), `issuers` (kind `issuer`), each by ascending `local_id`. One `source_entity` row each: `{type, ordinal, member_id, entity_kind, local_id, source}` with `source` the Minimal row unchanged.
- NEEDS_MAPPING candidates (initial layout):
  1. Allocate the proposed IDs first: for each member, each entity in the order above, call `new_id(('entity', member_id, kind, local_id))`.
  2. Build the issuer proposals first: `body = mapping.proposed_body(minimal, 'issuer', local, id, tenant, portfolio, MappingIndex([], member))`, `version = codec.digest(body)`.
  3. Then accounts and instruments with `MappingIndex(issuer_mappings, member)`, where `issuer_mappings` is one `{member_id, entity_kind: 'issuer', local_id, target: {mode: 'proposed', id, version}}` per issuer of that member. An instrument with an issuer therefore names the proposed issuer, as `review-metadata-native-initial.json` shows.
  4. Candidates of one entity, in order: every `entities` row for `(member, kind, local)` in key order (mode `existing`, body as served), then the proposed one (`{member_id, entity_kind, local_id, target: {mode: 'proposed', id, version}, body}`). The proposed candidate is always offered beside the existing ones, even when an existing entity matches (D2 (a), the owner's answer of 2026-11-21). The one exception: if `proposed_body` raises `import_evidence_unsupported` and the entity has at least one existing candidate, leave the proposed one out; with no existing candidate, re-raise.
- READY and CONFLICT candidates: exactly one per source entity, the decisions mapping's target. For mode `existing` the body is the `entities` row with the same target ID and version. For mode `proposed` the body is `mapping.proposed_body(minimal, kind, local, target id, tenant, portfolio, MappingIndex(decisions['mappings'], member))`.
- `tenant` and `portfolio` come from the `context` row.

### Part D: fact classification (decisions present, every entity mapped)

For each member, `index = MappingIndex(decisions['mappings'], member)`; `index.require_complete(minimal)` (an extra mapping raises `import_invalid`; a missing one was handled in Part B). `scope = {'tenant_id', 'portfolio_id'}` from context plus `'connection_id'` from that member's pinned source.

Facts of a member, in this order: `records`, `coverage`, `snapshots` by ascending `local_id`, then `membership` (`local_id` `'0'`) when it is not null. For each fact:

- `key = reconciliation.source_revision_key(minimal, collection, local_id, **scope)`; `sk = codec.digest(key['source'])`; `claim` = `key['source']` without `version`, `tenant_id`, `portfolio_id`, `connection_id` and `collection`, plus `revision: key['revision']`.
- `fd = codec.digest(reconciliation.financial_projection(minimal, collection, local_id, index, scope=scope))`.
- `C` = the `revisions` rows with `source_key_digest == sk`. Each must have `collection` equal to the fact's and `source` equal to `claim` in every field except `revision`, otherwise refuse `import_conflict`, `$.revisions` (a hash match without equal bytes is not identity). At most one row of `C` may have `source.revision == key['revision']`; that row is `E`. Two such rows, or rows of `C` with different `economic_group_id`s: refuse `import_conflict`, `$.revisions`.
- Tip `T` of `C`: for an activity record, the one row of `C` that is the `next_revision_id` of an active `heads` row of kind `activity` whose `key_digest` is `codec.digest({'version': 1, 'tenant_id', 'portfolio_id', 'economic_group_id': <the group of C>})`. For other collections, the one row of `C` that no other row of `C` names as `parent_revision_id`. If no such row exists for an activity (a voided chain), `T` is none. More than one: refuse `import_conflict`, `$.revisions`.
- `P` = the decisions `parents` item for this fact, if any. `H` = a decisions `authorities` item with `kind: 'historical_only'` and `left == {form: 'incoming', member_id, collection, local_id}` of this fact.

Apply the first rule that matches:

| # | Condition | Outcome |
|---|---|---|
| D1 | Another incoming fact anywhere in the set has the same `sk` | `conflict`, `identity` (both facts) |
| D2 | A records activity row, and the member's `provenance.parser_api` is null and `provenance.id_policy == 'ambiguous'` | `conflict`, `identity` |
| D3 | `E` exists and `P` exists | `conflict`, `parent` |
| D4 | `E` exists and `E.financial_digest == fd` | `duplicate` of `E` |
| D5 | `E` exists, digest differs | `conflict`, `identity` |
| D6 | `C` not empty and `P` exists | `correction` (or `void` when the record's `identity.change` is `void`) with parent `T`, if `T` exists, `P.parent_revision_id == T.id`, `P.reason` is not empty, and the fact is an activity record, a coverage row or the membership. Otherwise `conflict`, `parent` |
| D7 | `C` not empty, no `P`, and the record's `identity.change` is not `original`, or a coverage, snapshot or membership row has a non-null `parent` | `conflict`, `parent` |
| D8 | `C` not empty, no `P`, `T` exists and `T.financial_digest == fd` | `duplicate` of `T` |
| D9 | `C` not empty, otherwise | `conflict`, `parent` |
| D10 | `C` empty and `P` exists | `conflict`, `parent` |
| D11 | `C` empty and the record's `identity.change` is not `original` or its `identity.parent` is not null, or a coverage, snapshot or membership row has a non-null `parent` | `conflict`, `parent` |
| D12 | `C` empty, otherwise | `append` (snapshots go on to Part E) |

- A `duplicate` takes `accepted_revision_id`, `economic_group_id` and the financial digest from the matched row (`E` or `T`), with `parent_revision_id` null.
- A `correction` or `void` takes `economic_group_id` from `T` (null outside activities) and `parent_revision_id = T.id`.
- An `append` has `parent_revision_id` null and `economic_group_id` null except for activity records (a new group).
- Snapshot positions and snapshot corrections with a `P` fall under D6's "otherwise" and become `conflict`, `parent`. That is a named limit.
- Authorities (all from decisions):
  - A `historical_only` item must have `right` null and `left` an incoming snapshot fact. Otherwise: an incoming `left` makes that fact `conflict`, `authority`; an `accepted` `left` refuses `import_conflict`, `$.decisions`.
  - `mirror` or `authority` with an incoming side makes that fact `conflict`, `authority`. The builder never produces the `mirror` action.
  - `independent` changes no outcome.
  - Every `accepted` reference must be a `revisions` row, otherwise refuse `import_conflict`, `$.decisions`.
- The builder never computes an amount, balance, contribution, cost or eligibility. It copies staged rows and digests only.

### Part E: snapshots and heads

- Snapshot that reached D12:
  - If `H` exists, the snapshot is `historical`, and so is each of its `position_local_ids` records and `coverage_local_ids` coverage rows whose outcome is `append`. A `historical` fact gets no head.
  - If `H` exists for a snapshot whose outcome is not D12's, that snapshot becomes `conflict`, `authority`.
  - Without `H`: for each holdings coverage in `coverage_local_ids` order (rows with `kind == 'holdings'`), compute the domain key `codec.digest({'version': 1, 'tenant_id', 'portfolio_id', 'account_id': <account mapping target id>, 'record_kind': 'holdings', 'instrument_scope': <the coverage's instrument_scope without asset_local_ids, plus 'instrument_ids': the target ids of every decisions instrument mapping of this member whose local_id is in asset_local_ids, sorted>})`. Keep the first coverage of each distinct key. Two coverages with the same key but different `status`: the snapshot becomes `conflict`, `coverage`.
  - For each key, the current head is the `heads` row of kind `snapshot` with that `key_digest`, if any. Its `as_of` is `typed.as_of` of the `revisions` row whose `id` is the head's `next_revision_id`; a missing row refuses `import_conflict`, `$.heads`.
  - Call `reconciliation.snapshot_order(incoming_as_of, current_as_of_or_None)` with the defaults (`same_material=False`, `explicit_parent=False`). `'new'` for every key keeps `append`. `'historical'` for any key, or any `IngestionError` from it, makes the snapshot `conflict`, `authority`.
- Heads, built only for READY, per member in fact order:
  - Activity `append`: `{active: true, complete_base_id: null, key_digest: digest({version 1, tenant_id, portfolio_id, economic_group_id: new group}), kind: 'activity', next_revision_id: new id, prior_revision_id: null}`.
  - Activity `correction` or `void`: the same with the group of `T`, `prior_revision_id: T.id` and `active: action == 'correction'`.
  - Snapshot `append`: one head per distinct domain key, in coverage order: `{active: true, kind: 'snapshot', key_digest, next_revision_id: the snapshot's new id, prior_revision_id: the current head's next_revision_id or null, complete_base_id: the new id when that coverage's status is 'complete', otherwise the current head's complete_base_id or null}`.
  - No other fact gets a head.
- ID allocation happens after classification, only for READY: for each member and fact in order, a `group` key (activity `append` only) and then a `revision` key.

### Part F: review layout and Plan

- One block per member in ascending `member_id` order. Ordinals are `str(i)` over the whole list.
  1. `source_entity` rows (Part C).
  2. `target_candidate` rows: `{type, ordinal, candidate}`, entities in the same order.
  3. `mapping` rows: `{type, ordinal, mapping}` for this member's decisions mappings in decisions order. Exception: if the decisions `mappings` are not grouped by ascending `member_id` (a member's items appear after a later member's), put all mapping rows, in decisions order, in the first member's block and none in the others. This keeps the review rows equal to the Plan array that the SQL compares byte for byte.
  4. First member's block only: all `authority` rows in decisions order, then all `parent` rows in decisions order.
  5. For each fact in order: a `fact` row `{type, ordinal, member_id, collection, local_id, action, accepted_revision_id, record, scope, required_decision}`. `record` is the staged row for records and null otherwise; `scope` is the staged row for the others and null for records. In READY it is followed by an `effect` row `{type, ordinal, effect: <the Plan fact>}`.
  6. READY only: `head` rows for this member's heads.
  7. `diagnostic` rows `{type, ordinal, member_id, diagnostic}`, one per `provenance.diagnostics` entry in order, never merged.
  - A NEEDS_MAPPING review has only rows 1, 2 and 7. No `member` rows are produced.
- `authority` row prior fields follow the SQL in `_PREPARE_REVIEW_ROWS`:
  - Resolve each side: `accepted` gives its `accepted_revision_id`. `incoming` gives the Plan fact's `accepted_revision_id` in READY and nothing otherwise.
  - Look up only when the left side resolved and the right side resolved or is null.
  - The prior link is the `authorities` row whose `authority.left`/`right` revision IDs equal the resolved pair in either orientation (left only when right is null). Take the highest `link_revision`; a tie between two link IDs refuses `import_conflict`, `$.authorities`.
  - `prior_link_id`, `prior_link_revision` and `prior_choice` (its `authority.kind`) come from that row; all null without one.
- Review document: `{version: 1, id: preview_id, set_id: context.set_id, set_revision, state, accepted_generation, mapping_generation, control_generation: the page pins, expires_at: context.set_expires_at copied unchanged (never re-formatted), content: {version: 1, rows}, content_digest: codec.digest(content), plan_digest}`.
  - `set_revision` is `str(int(page set_revision) + 1)` for READY (more than `contracts.MAX_COUNTER` refuses `import_limit`, `$.review.set_revision`) and the page `set_revision` otherwise.
  - `plan_digest` is `codec.digest(plan)` for READY, null otherwise.
  - More than 131,072 rows refuses `import_limit`, `$.review.content.rows`.
- READY Plan:
  - From context: `version: 1`, `tenant_id`, `portfolio_id`, `set_id`, `realm_digest`, `incarnation`, `restore_epoch` and `pinned_sources` (copied, in context order). Also `preview_id`, `decision_digest` (the header's `digest`), `expected_set_revision` (the review's `set_revision`) and `expected_accepted_generation`, `expected_mapping_generation`, `expected_control_generation` (the pins).
  - `expires_at` is the review's value.
  - `inputs`: per member in order, `{member_id, stage_digest: row digest, raw_digest: provenance.raw_sha256, discovery_digest: provenance.discovery_sha256}`.
  - `mappings`, `new_entities`, `authorities` and `parents` are the decisions lists, unchanged.
  - `facts`: every fact of every member, in fact order: `{member_id, collection, local_id, action, accepted_revision_id, parent_revision_id, economic_group_id, financial_digest: fd}`.
  - `heads`: all members' heads in order.
  - `review_content_digest` is the review's `content_digest`.

### Part G: CONFLICT and NEEDS_MAPPING at a reconciling set (required, D1 (b))

- A CONFLICT review uses the READY layout without `effect` and `head` rows, with `state: 'CONFLICT'`, `set_revision` the page value, `plan` and `plan_digest` null.
- Every fact gets a row: its outcome as `action` (`conflict` for D1, D2, D3, D5 to D7, D9 to D11 and the Part D and E authority and coverage cases).
  - `accepted_revision_id` is the matched row's ID for `duplicate` and null for everything else.
  - `required_decision` is the code from the tables (`identity`, `parent`, `authority` or `coverage`) for `conflict` and null otherwise.
- No `new_id` call is made for a CONFLICT review.
- A NEEDS_MAPPING review at a reconciling set is the initial layout of Part C and F, with the page `set_revision` and pins.

### Part H: final checks

1. `codec.validate(bundle, 'ReviewBundle')`.
2. `data = codec.encode(bundle)`; `len(data) > contracts.MAX_SET` refuses `import_limit`, `$.bundle`. Check this before step 3.
3. `approval.validate_review_bundle(data, stages=basis_stages(pages))`. Its error propagates under the wrapper rules.
4. Every UUID returned by `new_id` passes `codec.validate(x, 'UUID')` (else `import_invalid`, `$.new_id`), is not returned twice, and is not equal to `preview_id` or to any UUID string anywhere in the pages (else `import_conflict`, `$.new_id`). `preview_id` must not equal a UUID in the pages either (`import_conflict`, `$.preview_id`). Do this check when each ID is returned, not at the end.
5. Return the validated copy from step 1.

### How `reconciliation.md` maps to the builder (the AC-08 checklist)

| `reconciliation.md` row | Builder |
|---|---|
| Existing exact revision, same digest | D4 duplicate, no head |
| Same revision key, changed facts | D5 conflict `identity` |
| New revision with equal meaning | D8 duplicate of the chain tip, no head |
| New original stable source ID | D12 append, new group and activity head |
| Same time and amount, two source IDs | Two keys, two appends |
| Missing stable ID or generated-ID twins | D1 and D2 conflict `identity`. Limit: a parser2 member's profile policy is not in the basis (its `id_policy` is source prose), so admission and the profile remain the guard |
| Known ID changed with no valid parent | D7 or D9 conflict `parent` |
| Correction to the current head | D6 correction, head moves from `T` |
| Parent missing, foreign, fork, cycle or not current | D6 or D10 conflict `parent` |
| Void of current head | D6 void, head `active: false` |
| Pending, cancelled or unsupported original | Appended with its staged status; the builder computes no eligibility |
| Pending to completed | Needs a `parents` decision (D6); otherwise D9 |
| Completed later cancelled without void or correction | D9 conflict `parent` |
| Funding, transfer, balance, fees | Appended as staged; no acquisition, contribution or balance is added |
| Two connections, one account, overlapping kinds | Not decidable from the basis (accepted mappings of earlier inputs are not served). `_references_v1` refuses such a READY Plan with `import_conflict` at `prepare_preview_v1`. Limit, documented |
| Newer complete snapshot, same domain | Append, head `prior` is the current head, `complete_base_id` the new snapshot |
| Newer partial or unknown completeness | Append, `complete_base_id` kept from the current head |
| Older comparable observation | `historical` with `historical_only`; otherwise conflict `authority` |
| Equal instant, equal or different content, different source ID | Conflict `authority` (`snapshot_order` raises). Limit |
| Equal instant explicit snapshot correction | Not supported: conflict `parent`. Limit |
| Disjoint scopes | Separate domain keys and heads |
| Overlapping non-identical scopes | Only exact domain keys are compared. Limit, as in the merged SQL |
| Complete or partial empty | Heads per Part E; no position is invented |
| Missing coverage, members outside scope | `codec.decode` refuses at A9 |
| Time comparison | Only through `codec.compare_time` inside `snapshot_order` |

### Tests

`tests/test_ingestion_review_bundle.py` has one fixture helper that turns an oracle case into pages. It does not call `review_bundle`.

- `inputs`: one row per Plan input, `{kind: 'input', id: member_id, digest: stage_digest, minimal}`, with the Minimal found in `oracle.json` by `codec.digest(minimal) == stage_digest`. For initial cases use the inputs of the matching READY Plan.
- `context`: one row `{kind: 'prepare_context', tenant_id, portfolio_id, set_id, realm_digest, incarnation, restore_epoch, set_expires_at, pinned_sources}`, with every value copied from the case's Plan (`set_expires_at` is the Plan's `expires_at`). The oracle has no separate prepare-context vector, so these pass-through fields come from the Plan. The test still checks every computed field.
- `decisions`: from the case's decisions vector, as a header (`decision_revision '1'`, `digest`, `version`, `operation_id`, `expected_set_revision`, `counts`) and items; no rows for initial cases.
- `entities`: one `entity` row per existing-mode decisions mapping, with the body from the oracle whose `codec.digest` equals the target version (the `entity-bodies*.json`, `snapshot-target-bodies.json` and `metadata-native-bodies.json` lists, and `existing_issuer_body` of the `mapping_only_existing_issuer` effect case). `mappings`: one `mapping` row per existing-mode decisions mapping. The builder ignores these.
- `revisions` and `heads` for an accepted prestate: for each fact of the prestate Plan, an `AcceptedRevisionBasis` row:
  - `id: accepted_revision_id`, `input_id: 'f0000000-0000-4000-8000-000000000001'`, `collection`, `local_id`.
  - `source`: the claim form of `reconciliation.source_revision_key` over the prestate Minimal, as `_accepted_basis_seed` already does in `test_postgres_migration.py`. `source_key_digest`: the digest of its `source`.
  - `financial_digest` and `economic_group_id` from the Plan fact; `parent_revision_id: None`, `accepted_change: 'original'`, `typed`: the staged row.
  - Plus one `head` row per prestate Plan head, unchanged.
- Pins for every case: `job_id 'c0000000-0000-4000-8000-000000000004'`, `fence '1'`, `set_revision` the Plan's `expected_set_revision` minus 1 (initial: `'1'`), generations from the Plan (initial: all `'0'`).
- Paging: sort each resource by the Part A key, cut into pages of the requested size, and give each non-final page `next_cursor = {pins, resource, after_key: last key, expires_at: {fractional_digits: 0, tag: 'instant', token: '2026-02-03T12:00:00+00:00', zone: None}}`. An empty resource is one page with no rows.
- `new_id`: a dict from key tuple to the oracle literal; the test records every key asked for.

AC-01 cases (expected: `codec.encode(bundle['review'])` and `codec.encode(bundle['plan'])` equal the oracle bytes; `new_id` keys asked equal the listed set):

| Case | Basis | Prestate | `preview_id`; `new_id` keys → IDs | Expected |
|---|---|---|---|---|
| parser2 initial | `minimal-parser2.json`, no decisions | none | `a0000000-…-000000000065`; entity account 0,1 → `40000000-…-01`, `…-02`; instrument 0,1 → `…-03`, `…-04` | `review-parser2-initial.json`, plan null; the bundle equals `review-bundle-initial.json` |
| native initial | `minimal-native.json` | none | `a0000000-…-066`; same four | `review-native-initial.json` |
| metadata-native initial | `metadata-native-minimal.json` | none | `c0000000-…-066`; the four plus issuer 0,1 → `a0000000-…-0d2`, `…-0d3` | `review-metadata-native-initial.json` |
| first use | `decisions-first-use.json` | none | Plan's; revision records/0, coverage/0, membership/0 → `60000000-…-01`, `-02`, `-03`; group records/0 → `80000000-…-01` | `review-parser2-ready.json`, `plan-first-use.json`; bundle equals `review-bundle-first-use.json` |
| native first use | `decisions-native-first-use.json` | none | revision records/0, coverage/0 → `60…-01`, `-02`; group → `80…-01` | `review-native-ready.json`, `plan-native-first-use.json` |
| metadata-native | `metadata-native-decisions.json` | none | as native first use | `review-metadata-native-ready.json`, `metadata-native-plan.json` |
| mixed-set | `mixed-set-decisions.json` | none | member `20…-01` as first use; member `e0…-01` records/0, coverage/0, snapshots/0 → `e0000000-…-064`, `-065`, `-066` | `mixed-set-review.json`, `mixed-set-plan.json` |
| snapshot-seed-t2 | `snapshot-seed-t2-decisions.json` | none | `e0…-064`, `-065`, `-066` | `snapshot-seed-t2-review.json`, `-plan.json` |
| snapshot-historical-t1 | `snapshot-historical-t1-decisions.json` | `snapshot-seed-t2-plan.json` over `snapshot-t2-complete-minimal.json` | records/0, records/1, coverage/0, snapshots/0 → `e0…-06e`, `-06f`, `-070`, `-071` | `snapshot-historical-t1-review.json`, `-plan.json` |
| fresh duplicate | `branch-fresh_duplicate_only-*` | `plan-first-use.json` over `minimal-parser2.json` | none asked | `branch-fresh_duplicate_only-review.json`, `-plan.json` |
| new equal-meaning revision | `branch-new_equal_meaning_revision-*` | same | none asked | its review and Plan |
| explicit correction | `branch-equal_value_explicit_correction-*` | same | revision records/0 → `b0000000-…-032` only | its review and Plan |
| existing issuer | `branch-mapping_only_existing_issuer-*` | `plan-native-first-use.json` over `minimal-native.json` | none asked | its review and Plan |
| authority only | `branch-fresh_duplicate_only-minimal.json`, `authority-only-decisions.json` | first-use rows, plus the prestate's `peer_revision` as a revision row, a peer activity head (`key_digest` digest of group `d0…-0c9`, `next_revision_id` `d0…-0c8`), and one `authorities` row `{link_id: prior_link_id, link_revision: '1', authority: prior_authority}` | none asked | `authority-only-review.json`, `-plan.json` |

Other tests:

| AC | Case | Expected |
|---|---|---|
| 02 | Every READY bundle of the AC-01 table and the three initial ones | `approval.validate_review_bundle(codec.encode(bundle), stages=basis_stages(pages))` returns without error (also asserted inside each AC-01 test) |
| 02 | Real PostgreSQL (below) | `prepare_preview_v1` accepts |
| 03 | `examples/data/wealthsimple-holdings.csv`, Minimal from `admit_parser2` exactly as `tests/test_ingestion_discovery.py` `builtin()` builds it (copy that helper; do not import the test class), one member (`20000000-0000-4000-8000-000000000001`), no prestate. Its pinned source takes `installation_id`, `wrapper_profile_digest` and `format_version` from the Minimal's `provenance.installation_id`, `provenance.wrapper_profile_digest` and `provenance.format_selection` (`verify_staged_material` compares them); `connection_id`, `connection_version`, the three generations and `context_digest` are the first-use pin's literals. The Plan's `raw_digest` and `discovery_digest` come from provenance (Part F). Context otherwise as for first use. Build initial; make decisions from its proposed candidates (each candidate's target as a mapping, and `{kind, id, version, member_id, local_id}` as `new_entities`); build READY | Initial: NEEDS_MAPPING with 8 candidates (3 accounts, 5 instruments). READY: 3 account `source_entity` rows; 6 records fact rows, all `record_type 'position'`; the Decimal sum of `market_value.amount` is CAD `565` and USD `150`; the snapshot fact's `scope.as_of.token` is `2024-02-01T10:00:00-05:00`; 3 coverage facts with `status 'partial'`; membership `status 'unknown'`; 3 snapshot heads with `complete_base_id` null; no activity record; every action `append` |
| 03 | `examples/data/bull-orders.csv` the same way | Initial: 5 candidates. READY: 2 accounts; 3 records, all `status 'completed'`; 2 `BUY` whose `ACQUISITION` legs sum to BTC `0.00400000` and LBTC `0.00300000` by asset symbol, and whose `acquisition_cost_cad` sums to `700.00`; 1 `FUNDING` with `cash_flow.cash_amount` `1000.00`, `boundary 'unclassified'` and no legs; no snapshot or position fact; 3 diagnostic rows equal to the staged ones (`wallet_balance_unverified`, `wallet_fees_unknown`, `observed_order_rows` with `row_count '3'`); 3 activity heads |
| 04 | First use, mixed-set, snapshot-historical-t1 and authority only, each built twice, and with page sizes 1, 7 and 50, each in forward, reversed and interleaved (odd pages first) order | All encodings equal; the `new_id` keys asked are the same |
| 05 | Remove all pages of each resource in turn (8 subtests) | `import_invalid` |
| 05 | Input row `digest` set to `'0' * 64` | `import_invalid` |
| 05 | Decisions mapping `member_id` `20000000-0000-4000-8000-000000000099`; mapping `local_id` `'9'`; a `parents` item for records `'5'`; an authority incoming `local_id '5'`; a `new_entities` item with an unknown member (header digest and counts rebuilt each time) | `import_invalid` each |
| 05 | One page with `control_generation`, `accepted_generation`, `mapping_generation`, `set_revision`, `job_id` or `fence` changed (6 subtests) | `import_stale` |
| 05 | Two final pages for one resource; a cursor whose `after_key` is not its last row; one row repeated on two pages; the decisions header digest `'0' * 64` | `import_invalid` |
| 05 | Four members (IDs `20000000-0000-4000-8000-0000000000a1` to `…-0a4`, each pinned source a copy of the first-use pin with its own `member_id` and `connection_id`), each with `large-basis-minimal.json` plus 900 extra assets (copies of asset 0 with `local_id` `'2'` to `'901'` and `source_descriptor` `'A' * 4096`; the planner checked that this decodes at 3,899,288 bytes), no decisions | `import_limit`, `$.bundle` |
| 05 | `new_id` returns `'not-a-uuid'`; returns a member ID; returns the same UUID twice; `preview_id` `'x'` | `import_invalid`; `import_conflict`; `import_conflict`; `import_invalid` |
| 05 | Every refusal above | `IngestionError` with that exact code, `str(error)` equals the code, and no return value |
| 06 | Static: parse `review_bundle.py` with `ast` | Only the imports listed under Files. No name `open`, `input`, `eval`, `exec`, `compile`, `__import__`, `globals`, `getattr` or `setattr` |
| 06 | Dynamic: inside `unittest.mock.patch` contexts, make these raise: `time.time`, `time.time_ns`, `time.monotonic`, `time.perf_counter`, `random.random`, `random.getrandbits`, `os.urandom`, `secrets.token_bytes`, `uuid.uuid1`, `uuid.uuid4`, `os.getenv`, `os.environ.__getitem__` and `os.environ.get` (a raising mapping), `builtins.open`, `io.open`, `socket.socket` and `socket.create_connection`. Build first use (READY) and metadata-native initial | Both bundles equal those built without patches |
| 07 | `large-basis-page.json` as the literal `inputs` page; context from `plan-first-use.json` with `pinned_sources[0].member_id = 'c0000000-0000-4000-8000-000000000007'`; decisions with one proposed mapping and `new_entities` item per entity, IDs `'aa000000-0000-4000-8000-' + f'{i:012d}'`, versions from `mapping.proposed_body` (input preparation only); pins from the page; `new_id` returns `'bb000000-0000-4000-8000-' + f'{n:012d}'` for the n-th call (the planner checked that the 13 records and coverage keys are distinct, so the case is READY) | Initial and READY each finish in under 10 s by `time.perf_counter` in the test; READY passes `validate_review_bundle` |
| 07 | The four-member case of AC-05 | Refused in under 10 s |
| 09 | Docs | See Docs below |

Part G tests (required; they run in the default suite with the AC-01 tests). Expected values are literal in `tests/fixtures/ingestion/review-bundle-cases.json`. Write that file once, by copying the named oracle rows and applying exactly the listed edits; recompute `content_digest` with `codec.digest`. Never generate it with `review_bundle`.

| Case | Basis | Expected review (`plan` null, `plan_digest` null) |
|---|---|---|
| `conflict-parent` | The new equal-meaning revision case, with revision row `60000000-…-01`'s `financial_digest` set to `'0' * 64` | `branch-new_equal_meaning_revision-review.json` without `effect` rows, ordinals renumbered; the records/0 fact row has `action 'conflict'`, `accepted_revision_id` null and `required_decision 'parent'`; coverage and membership rows unchanged; `state 'CONFLICT'`, `set_revision '2'`; no `new_id` call |
| `conflict-authority` | snapshot-historical-t1 with decisions `authorities` emptied | `snapshot-historical-t1-review.json` without the `authority` and `effect` rows, renumbered; records/0, records/1 and coverage/0 have `action 'append'` and `accepted_revision_id` null; snapshots/0 has `action 'conflict'`, `accepted_revision_id` null and `required_decision 'authority'`; `state 'CONFLICT'`, `set_revision '2'`; no `new_id` call |
| `needs-mapping` | First use with decisions whose `mappings` and `new_entities` are both empty (so no `40000000-…` ID is in the basis and Part H's collision check passes); `new_id` as for the parser2 initial case | The rows of `review-parser2-initial.json` unchanged; `id` the case's `preview_id`, `set_revision '2'`, `control_generation '1'`, `state 'NEEDS_MAPPING'`, same `content_digest` |
| twins | Two members with the same `minimal-parser2.json` and the same pinned connection, decisions mapping both members to the same four proposed targets | `state 'CONFLICT'`; all six fact rows have `action 'conflict'` and `required_decision 'identity'` (asserted directly, no fixture) |

`tests/test_postgres_review_bundle.py` (AC-02):

- Structure: `from test_postgres_migration import IngestionAppendOnlyPostgresTests, ORACLE` and one subclass. Add `load_tests` so that only the subclass's own `test_` methods run, not the inherited ones. The class keeps the inherited `KURAFOLIO_INGESTION_TEST` skip and container setup.
- Each case uses two rolled-back runs of one deterministic seed string, built once:
  1. Run 1: `seed + plan_claim('claim', work_kind="'prepare'")`, then `basis_call` for each of the eight resources with `limit` 50, following `next_cursor` with `previous(...)` until it is null. Parse the pages.
  2. Build the bundle in Python with the case's oracle `new_id` map.
  3. Run 2: `seed + plan_claim(...)` again, the same eight reads, then `prepare_preview_call(label, bundle, ready=..., expected_set_revision=..., accepted_generation=..., mapping_generation=..., control_generation=...)` with the pins from run 1's pages.
  - The bundle does not depend on the lease's `job_id` or fence, or on IDs the seed's acceptance draws at random (`_effects_v1` gives `accepted_inputs`, `accepted_plans`, mappings and receipts `gen_random_uuid()` IDs, so `revisions.input_id` differs between runs). Do not compare raw pages across runs. Instead, after run 2 returns, build a second bundle from run 2's pages and assert its bytes equal the bundle sent.
- Assert:
  - run 2's result is `ok`, its `PreviewAck` state is the expected one (NEEDS_MAPPING for the two initial cases, READY otherwise) and its `set_revision` is the bundle's;
  - the bundle's review and Plan equal the oracle vectors after replacing `expires_at` (the live 6-digit value) and `realm_digest` (the live realm), with `content_digest`, `review_content_digest` and `plan_digest` recomputed.
- Seeds, from the existing helpers only:
  - First-use initial: as `test_initial_prepare_cannot_store_ready_before_explicit_decisions` does ( `NORMALIZING`, revision 1, decisions and previews deleted, control generation 0).
  - Native first-use initial: `case_seed(plan-native-first-use)` (below) with the same `NORMALIZING` edits.
  - First-use READY: as `test_prepare_preview_checks_initial_and_ready_bundles_and_replays` does (`RECONCILING`, revision 2, decisions revision 1, previews deleted).
  - Native first use, `snapshot-seed-t2`, `mixed-set`: a `case_seed(plan)` written in the new class by following `accept_seed` line for line but with one enablement, connection, connection lifecycle, catalog availability entry and synthetic installation row per distinct pinned source, and the wrapper list holding every installation and profile pair. Then `RECONCILING`, revision 2, previews deleted.
  - The four `branch-*` cases and authority only: as `test_prepare_authority_basis_and_preview_use_scoped_latest_history` does (`accept_seed()`, `accept_statement` for first use, `later_plan_seed(case plan)`, root generations set to the case's, decisions revision 1, `RECONCILING` revision 2). For the existing-issuer case the base is native first use via `case_seed`. Authority only adds the peer revision and prior link rows exactly as that test does.
  - `snapshot-historical-t1`: `case_seed(snapshot-seed-t2 plan)`, accept it, then `later_plan_seed(t1 plan)`, root generations 1/1/1, `RECONCILING` revision 2.

### Docs (AC-09)

In `docs/web-v2-imports.md`, subsection "Review bundle builder", plain English:

- what the builder reads (the eight resources of one lease), its entry point and that it is pure;
- the three states it produces and when (Part B);
- what it decides: actions, heads, candidates and the `required_decision` codes;
- what it never does: no amount, balance, contribution or eligibility, no zero for unknown values, no target chosen for the user;
- its fixed error codes;
- its limits: the "Limit" rows of the table above; that two connections mapped to one account are refused by `prepare_preview_v1`, not by the builder; the member-order rule for decisions mappings; parser2 ambiguity.

In "Remaining acceptance", say that the worker does not call the builder until IMP-007V lands.

### Rollback

The change adds one module, two test files, one fixture file and a docs section. No SQL, grant, DTO, stored data or existing behaviour changes, and no caller exists until IMP-007V. Rollback is reverting the pull request.

### Do not touch

- `src/kurafolio/ingestion/approval.py`, `mapping.py`, `reconciliation.py`, `codec.py`, `contracts.py`, `cursors.py`, `discovery.py`, `runner_client.py` and their tests.
- `src/kurafolio/persistence/` (all SQL, grants and inventories), `src/kurafolio/ingestion/worker.py` and `worker_sql.py` (IMP-007F, IMP-007V).
- `tests/test_postgres_migration.py`, `tests/fixtures/ingestion/oracle.json`, `docs/specs/imp-007-r7/**`.
- Other tickets and `tickets/ROADMAP.md`.

### Stop and ask if

- An AC-01 vector cannot be reproduced with these rules. Report the case and the first differing row. Never edit the oracle or add a per-case rule.
- A case cannot be expressed as basis pages from oracle inputs, or needs data outside the eight resources.
- `prepare_preview_v1` refuses a builder bundle for a listed AC-02 case, or `validate_review_bundle` refuses a bundle these rules produced.
- An AC-02 seed cannot be built from the existing helpers without editing `tests/test_postgres_migration.py`, or IMP-007F has moved those helpers (for example into `tests/ingestion_pg_support.py`): rebase the imports on the moved helpers only if their assertions are unchanged, otherwise ask.
- Any merged interface named here differs on `main` at claim time (the eight resources and their row shapes, `validate_review_bundle`, `proposed_body`, `source_revision_key`, `financial_projection`, `snapshot_order`).
- A build takes 10 s or more, or a rule seems to need a helper's behaviour changed.

## Plan

- [x] Owner answers D1 and D2 (Decisions needed); the planner records them in this plan pull request (2026-11-21: D1 (b), D2 (a)).
- [ ] Part A basis assembly and the AC-05 refusal tests.
- [ ] Parts B, C and F for NEEDS_MAPPING; the three initial AC-01 cases.
- [ ] Parts D, E and F for READY; the AC-01 cases without prestate, then with prestate.
- [ ] Part G with `review-bundle-cases.json`; Part H; AC-03, 04, 06 and 07.
- [ ] Real-PostgreSQL acceptance (AC-02).
- [ ] Docs (AC-09); full suite; pull request with the independent review.

## Decisions needed

- Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes. **Resolved 2026-11-21.** Asked "Gate A, tickets whose text is unchanged since filing (full text on PR #95's branch). Which do you approve exactly as written?" with this ticket listed at sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766, the owner selected "IMP-007O,IMP-007P,IMP-007U,IMP-007S" (Q31). `gate_approval` and `spec_approved` record it.

The owner answered D1 and D2 on 2026-11-21. Neither changes a gated section.

- **D1. What the builder does when the user's decisions do not make the set READY.** **Resolved 2026-11-21: (b).** The owner chose "CONFLICT/NEEDS_MAPPING too (Recommended)": "(b) The builder also produces CONFLICT and NEEDS_MAPPING reviews, so the user sees what is still open and can answer it. Adds Part G (4 more test cases)." (Q34). Part G and its four tests are required.
  - **The problem.** After a decision, the set is `RECONCILING` and the user cannot decide again until a preview exists (`decide_set_v1` accepts only `NEEDS_MAPPING`, `CONFLICT` and `READY`). `prepare_preview_v1` accepts a CONFLICT or NEEDS_MAPPING review there, but no oracle vector has one.
  - **A common case.** The merged Bull Bitcoin parser gives the order coverage row the same source identity in every export: scope `exported-orders`, no observation ID, revision = a digest of the rows. A later export with more orders therefore has a new coverage revision with different meaning. An order whose content changed (for example pending, then completed) gets a new revision the same way. Both need a `parents` decision under r7. The initial review cannot ask for one, because it has no fact rows. Wealthsimple exports are not affected: each snapshot and its coverage have a new identity per export time.
  - **(a)** Produce READY or refuse. A set whose decisions leave a conflict or an unmapped entity gets a fixed error code; under IMP-007V's Decision 1 it waits until it is cancelled or expires, and the user is not told why. A Bull Bitcoin re-import with new orders cannot reach a preview through the worker.
  - **(b)** Also produce a CONFLICT review, listing every fact with its `required_decision` (`parent`, `authority`, `identity` or `coverage`), and a NEEDS_MAPPING review when an entity has no valid mapping. The user can then decide again. Expected values for these reviews are oracle rows with named edits, in a new fixture file (Build plan, Part G). Scope grows by Part G and four tests; no SQL or DTO changes.
  - **Recommendation: (b).** Without it, the "import a newer file" journey in PRODUCT_CONTEXT.md does not work for Bull Bitcoin, and refusals would be routine rather than rare, which IMP-007V's Decision 1 assumed. The UI still has to show the CONFLICT review and send the parent decisions; that is the UI tickets' work, not this one.
- **D2. Offer "new entity" when an existing one matches.** **Resolved 2026-11-21: (a).** The owner chose "Always offer new (Recommended)": "(a) The user can always choose a new entity instead of a match." (Q35). Part C states it as the rule.
  - In an initial review, the SQL requires every compatible existing entity to be offered. It allows a proposed new one beside them, and no vector shows that case.
  - **(a)** Always also offer a proposed new entity (left out only when the source metadata cannot form one and an existing candidate is available). Accounts match only on category and role, so the user may need a separate account.
  - **(b)** Offer a proposed one only when no existing entity matches.
  - **Recommendation: (a).** The user keeps the choice; mapping.py's rule is that the module never selects a target for a user. The Build plan (Part C) follows (a).

## Handoff

- State: Ready, Gate A recorded. The Build plan is in plan pull request #99 with D1 (b) and D2 (a) recorded; the ticket is buildable once that pull request merges to `main`. Not claimed.
- Next step: After #99 merges, a builder claims the ticket and follows the Build plan in its build order, Part G included.
- Verify: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_ingestion_*.py' -v` and `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: IMP-007V (the worker's prepare step) waits for this ticket, so no set reaches a preview through the worker until both land. IMP-007F and the activation ticket IMP-007S do not wait for it.
- Open questions: none.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #86 from the owner's decision of 2026-11-20 on "No merged code builds the ReviewBundle ... Who builds it?": the owner chose "New ticket (Recommended)": "risk critical, tier frontier, own review." (IMP-007F D2 = (a).) On the wait, the owner chose "Build now, prepare last (Recommended)": "No depends_on. Builders do PR 1 and PR 2 now; prepare and AC-04 land in a third PR once IMP-007P merges." Status backlog; no Gate A yet.
- 2026-11-20 claude-code/opus-5.5: the owner chose "Split prepare out (Recommended)" (Q16): "Move the prepare step and AC-04 to a new ticket (IMP-007V) that depends on IMP-007F and IMP-007P." The caller of this builder is now IMP-007V, not IMP-007F's third pull request; Context, the Requirements "Not in scope" line and Handoff say so. Spec hash changes from sha256:def5b60480742768882339fd55443e0f9af5f984b7c7d6f5ac094087b21bed27 to sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766; the ticket was never approved.
- 2026-11-21 claude-code/opus-5.5: recorded Gate A in plan pull request #95. Asked "Gate A, tickets whose text is unchanged since filing (full text on PR #95's branch). Which do you approve exactly as written?" (Q31) with this ticket listed at sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766, the owner selected "IMP-007O,IMP-007P,IMP-007U,IMP-007S". `gate_approval` set to "owner 2026-11-21, Gate A on the text as written on PR #95's branch (Q31)"; `spec_approved` set to sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766, which `tickets.py spec` reports as the current hash; status backlog becomes ready. Decisions needed item resolved. No Build plan yet; the planner writes it in a later pull request.
- 2026-11-21 claude-code/opus-5.5: wrote the Build plan from `main` at `1274b54` in plan pull request #99 (not claimed). Context now lists the eight basis resources that merged `read_plan_basis_v1` serves; IMP-007V's Context still says six, and its planner should read this plan. New Decisions needed D1 (CONFLICT and NEEDS_MAPPING reviews at a reconciling set; recommended (b)) and D2 (offer a new entity beside existing ones; recommended (a)). Gated sections unchanged; `spec IMP-007P` still matches sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766.
- 2026-11-21 claude-code/opus-5.5: recorded the owner's plan decisions in plan pull request #99. D1 (Q34, "IMP-007P D1: after the user's decisions, a reconciling set can still be short of READY (a conflict or a missing mapping remains). What should the ReviewBundle builder produce then?"): the owner chose "CONFLICT/NEEDS_MAPPING too (Recommended)": "(b) The builder also produces CONFLICT and NEEDS_MAPPING reviews, so the user sees what is still open and can answer it. Adds Part G (4 more test cases)." D2 (Q35, "IMP-007P D2: when an incoming account or instrument matches existing ones, should the review always also offer 'create a new entity' beside the matches?"): the owner chose "Always offer new (Recommended)": "(a) The user can always choose a new entity instead of a match." Part G and its tests are now required; the D1 stop point, the D1 (a) column and refusals, and the D2 fallback are removed. No Decisions needed remain open. Gated sections unchanged; `spec IMP-007P` still matches sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766.
