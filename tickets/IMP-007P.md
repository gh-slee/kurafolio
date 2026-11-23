---
id: IMP-007P
title: Build the ReviewBundle that the worker's prepare step passes to prepare_preview_v1
priority: P0
status: in_progress
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
branch: ticket/imp-007p-build-the-reviewbundle-that-the-worker-s
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766
updated: 2026-11-22
---

# IMP-007P: Build the ReviewBundle that the worker's prepare step passes to prepare_preview_v1

## Goal

After every member of an import set is normalized, the import worker must turn the set's stages, decisions and current references into a `ReviewBundle` (a review document and, when r7 requires one, a complete Plan) and pass it to `prepare_preview_v1`. No merged code builds one, so no set can reach a preview without a human step. Build a deterministic builder that follows the r7 reconciliation rules and reproduces the oracle review and plan vectors exactly.

## Context

- Filed on 2026-11-20 from the IMP-007F plan (PR #86), its Decision D2, option (a), which the owner chose.
- Caller: IMP-007V, the import worker's prepare step (in IMP-007F's `src/kurafolio/ingestion/worker.py`), which depends on this ticket and on IMP-007F. Under one prepare lease it reads every basis resource with `read_plan_basis_v1` (cursor paging, `limit` 50), calls this builder, checks the result with `approval.validate_review_bundle`, and passes `codec.encode(bundle)` as `p_bytes` to `prepare_preview_v1`. A prepare lease lasts at most 60 s and is never renewed (IMP-007F D6), so the builder must finish well inside one lease. IMP-007V imports this module and does not change it; this ticket does not change the worker.
- Contracts, all in the r7 bundle: [reconciliation.md](../docs/specs/imp-007-r7/reconciliation.md) (identity keys, the source revision and activity table, the snapshot and coverage table), [normalized-evidence.md](../docs/specs/imp-007-r7/normalized-evidence.md) and [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md). DTOs: `ReviewBundle` (`{version: 1, review: ReviewDocument, plan: Plan | null}` in `src/kurafolio/ingestion/contracts.py`), `ReviewDocument`, `BasisPage`, `PreparePreviewRequest` (`payload_bytes` at most 16,777,216) in [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json), `Plan` in [codec-schema.json](../docs/specs/imp-007-r7/codec-schema.json).
- Merged code to build on (`main` at `7d7acc1`; since `d902717` only the cleanup claim backoff of IMP-007N, #88, changed `ingestion_schema.py`, in the cleanup part of `claim_plan_v1`, not in `read_plan_basis_v1` or `prepare_preview_v1`):
  - `approval.py`: `validate_review_bundle(data, *, stages)`, `verify_staged_material`, `verify_proposals`.
  - `mapping.py`: `MappingIndex`, `proposed_body`, `compatible`, `verify_target_version`.
  - `reconciliation.py`: `source_revision_key`, `project_record`, `financial_projection`, `reconcile_revision` (`RevisionDecision`), `snapshot_order`.
  - `codec.py` (`encode`, `validate`, `digest`, `sha256`) and `cursors.py`.
  - The checks in `prepare_preview_v1` (`ingestion_schema.py`, IMP-007L, with the r7-A1 to r7-A4 amendments recorded in IMP-007L), which accept or refuse a bundle against the stored stages, decisions and generation pins.
- Expected values: the oracle vectors in `tests/fixtures/ingestion/oracle.json`. Cases with review or plan vectors: `authority-only`, the four `branch-*` cases, `metadata-native` (plan only), `mixed-set`, `snapshot-historical-t1` and `snapshot-seed-t2`, plus `plan-first-use.json` and `plan-native-first-use.json`. Their inputs are the matching `*-minimal.json`, `*-decisions.json`, `*-context.json`, `*-prestate.json` and `*-discovery.json` entries. `builtin-inputs.json` holds the expected facts for the two example files (`wealthsimple_expected`, `bull_expected`) that IMP-007V's AC-IMP-007V-01 checks (formerly IMP-007F's AC-04), and the `large-basis-*` entries the largest basis.
- `tests/test_postgres_migration.py` drives `prepare_preview_v1` with oracle bundles (`prepare_preview_call`, the `basis_call` helpers). Those helpers show how the basis pages look for each case.
- `resources` holds a new `ingestion-review-bundle` lock. It does not overlap IMP-007F's `v2-import-worker` files or the `ingestion-schema-sql` lock.
- Found while planning (2026-11-22, from `7d7acc1`):
  - The basis does not hold every value a bundle needs. `preview_id`, new accepted revision IDs, new economic group IDs and the proposed entity IDs of an initial review come from the caller. The oracle uses arbitrary IDs per case (in `mixed-set`, `60000000-…-01` to `03` for one member and `e0000000-…-64` to `66` for the other), so no derivation rule could reproduce them.
  - A READY Plan's `mappings`, `new_entities`, `authorities` and `parents` must equal the stored decisions verbatim (`_validate_plan_v1`), and the review's mapping, authority and parent rows must equal them in order (`prepare_preview_v1`). `decide_set_v1` does not sort them.
  - The initial (NEEDS_MAPPING) vectors disclose source entities and candidates but no facts, and a READY review requires stored decisions even when every mapping exists. AC-03 therefore builds a READY review from synthetic all-proposed decisions.
  - Under IMP-007V's rule Q25, a builder refusal leaves the set waiting for cancel or expiry with no explanation. The r7 tables, by contrast, call many valid outcomes a conflict or a block, and `prepare_preview_v1` accepts a CONFLICT review without a Plan (Decisions needed item 2).
  - `AcceptedRevisionBasis` has no connection ID, mapped account or coverage windows, so the competing-stream check of `_references_v1` cannot be repeated against accepted revisions of other connections (Decisions needed item 3).
  - CI job `postgres-ingestion` runs only `test_postgres_migration.py`, so the AC-02 tests must live there to run in CI.

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

- Based on: `main` at `7d7acc1` (after #104).
- Tier: `frontier`, `risk: critical`, `review: independent`. The reviewer model's fresh-context QA review and a second Architect review are required before the owner's review (tickets/README.md, "Reviews").
- Normative sources, in this order: the r7 tables in `reconciliation.md`, then the checks that `prepare_preview_v1` runs on a bundle. Those checks are `_PREPARE_REVIEW_ROWS` and `_INITIAL_REVIEW_CANDIDATES` (`ingestion_schema.py` about lines 3838 to 4060), `_validate_plan_v1` (about 1015 to 1160), `_stream_authority_sql` (about 1162) and `_references_v1` (about 1232 to 1530). The builder must never return a READY Plan that those checks refuse. Where the r7 text and the SQL disagree, stop and ask.

### Before you claim

1. Decisions needed items 2, 3 and 4 were answered on 2026-11-22: the owner accepted all three recommendations, and this plan follows them. If the copy on `main` records a different answer, or reopens an item, do not claim; report that the ticket needs the planner.
2. Run `python3 scripts/tickets.py spec IMP-007P`. It must report `MATCHES` against `sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766`. If it reports `CHANGED`, do not build.
3. Run `git log 7d7acc1..origin/main -- src/kurafolio/ingestion/ src/kurafolio/persistence/ingestion_schema.py tests/fixtures/ingestion/ docs/specs/imp-007-r7/`. If `approval.py`, `mapping.py`, `reconciliation.py`, `codec.py`, the prepare or basis SQL, or `oracle.json` changed, re-check every rule below against the new text before you edit. Stop and ask if a rule no longer holds.
4. The Handoff still describes the pre-plan state. Overwrite it when you claim.

### Files

- `src/kurafolio/ingestion/review_bundle.py` (new): the builder. Nothing else in `src/` changes.
- `tests/test_ingestion_review_bundle.py` (new): the core tests (AC-01, 03 to 07). They run in the default suite with no PostgreSQL and no Web dependencies.
- `tests/test_postgres_migration.py`: one new gated test class or test methods for AC-02, reusing the existing helpers (below). Change no existing test.
- `.github/workflows/ci.yml`: in job `postgres-foundation`, raise `--expect-skipped` by the number of gated test methods you add, from the value on your build base (128 at `7d7acc1`; IMP-007O raises it to 132 if it merges first), and update the comment above it. Job `postgres-ingestion` keeps `--expect-skipped 0` and runs the new methods, because its pattern is `test_postgres_migration.py`. A gated test in any other file would never run in CI.
- `docs/web-v2-imports.md`: one paragraph after the `prepare_preview_v1` paragraph (AC-09, below).
- `tickets/IMP-007P.md`: status, Handoff, Log and the Plan ticks.

### Interfaces

```python
# src/kurafolio/ingestion/review_bundle.py
RESOURCES = ('inputs', 'entities', 'mappings', 'revisions', 'heads', 'authorities', 'decisions', 'context')

class IdSlot(NamedTuple):
    purpose: str     # 'entity' | 'revision' | 'group'
    member_id: str   # member UUID
    kind: str        # entity_kind for 'entity'; collection for 'revision'; 'records' for 'group'
    local_id: str    # local ordinal in that member's stage

def build_review_bundle(pages, *, preview_id, allocate_id):
    """Return one ReviewBundle dict built from one prepare lease's basis pages.

    pages: an iterable of decoded BasisPage values, every page of every resource
      in RESOURCES, in any order.
    preview_id: the caller's UUID for review.id and plan.preview_id.
    allocate_id: a callable IdSlot -> UUID string for every value that is not
      in the basis. It is called at most once per slot.
    Raises IngestionError(code, field) and returns nothing on refusal.
    """
```

- IMP-007V reads every resource with `read_plan_basis_v1` (cursor paging, `limit` 50) and passes the pages unchanged. It chooses `preview_id` and the allocator, for example `uuid.uuid4()` per slot. It then checks the result with `approval.validate_review_bundle(codec.encode(bundle), stages=...)` and sends `codec.encode(bundle)` as `p_bytes`. The builder never generates an ID. The oracle vectors use arbitrary IDs per case: in `mixed-set`, one member's facts use `60000000-…-01` to `03` and the other's `e0000000-…-64` to `66`. So no derivation rule could reproduce them; the tests pass a dict-backed allocator.
- Slots requested: `('entity', member, kind, local)` for the proposed candidate of every source entity in a NEEDS_MAPPING review; `('revision', member, collection, local)` for every fact whose action is not `duplicate` in a READY review; `('group', member, 'records', local)` for every activity record that starts a new chain (`append` with no prior revision) in a READY review. A CONFLICT review requests nothing. Duplicates take their IDs, and corrections and voids their groups, from the basis.
- Merged helpers the builder calls, unchanged:
  - `codec`: `encode`, `digest`, `sha256`, `validate(value, name, *, namespace=None)`, `decode(data, name='Minimal', *, limit=None, namespace=None)` and `compare_time`.
  - `mapping`: `MappingIndex(mappings, member_id)` with `.target`, `.reference` and `.require_complete(minimal)`, plus `proposed_body(minimal, kind, local_id, entity_id, tenant_id, portfolio_id, mappings)` and `compatible(...)`.
  - `reconciliation`: `source_revision_key(minimal, collection, local_id, *, tenant_id, portfolio_id, connection_id)`, `financial_projection(minimal, collection, local_id, mappings, *, scope)`, `reconcile_revision(*, incoming_key, incoming_material, change, parent_revision_id, current, exact=None)` and `snapshot_order(incoming_time, current_time, *, same_material=False, explicit_parent=False)`.
  - `approval`: `validate_review_bundle(data, *, stages)`, which also runs `verify_staged_material` and `verify_proposals`.
- `reconcile_revision` compares `encode(material)`. The basis holds an accepted revision's `financial_digest`, not its material. Pass `incoming_material=digest(financial_projection(...))` and the basis `financial_digest` as `material` of `current` and `exact`, so both sides are digests. `current` and `exact` are `{'id', 'source_revision_key', 'material', 'active'}`. `source_revision_key` is `{'version': 1, 'source': <the incoming key's source>, 'revision': <basis row source.revision>}`, which is valid only for a row whose `source_key_digest` equals `digest(incoming_key['source'])`.
- Allowed imports in `review_bundle.py`: `__future__`, `collections`, `copy`, `dataclasses`, `functools`, `itertools`, `operator`, `typing` and the package modules `.approval`, `.codec`, `.contracts`, `.mapping` and `.reconciliation`. Nothing else, and no `open`, `eval`, `exec`, `compile` or `__import__` (AC-06).

### Intake: from pages to one basis

1. Validate each page with `codec.validate(page, 'BasisPage', namespace='wire')`. Group the pages by `resource`. Every resource in `RESOURCES` must have at least one page, exactly one page with `next_cursor` null, and every non-null `next_cursor` must name the page's own resource.
2. All pages must carry equal `job_id`, `fence`, `set_revision`, `accepted_generation`, `mapping_generation` and `control_generation` (the pins).
3. Sort each resource's rows by a canonical key, never by delivery order: inputs by member ID; entities by (member ID, kind order account < instrument < issuer, integer local ID, target ID, version); mappings by (member ID, kind order, integer local ID); revisions by ID; heads by (kind, key digest); authorities by link ID; decisions by header first, then (collection order authorities < mappings < new_entities < parents, ordinal); context single. Two identical rows, or two rows with the same key, are a refusal. That is what makes page size and page order irrelevant (AC-04).
4. Inputs: 1 to 4 rows. For each, `sha256(encode(minimal))` must equal `digest`. Then `decode` that byte string, so the full Minimal semantic checks run. The stage map for `validate_review_bundle` is member ID -> those bytes.
5. Context: exactly one `prepare_context` row. Its `pinned_sources` member IDs must equal the input member IDs.
6. Decisions: no rows means "no decisions yet". Otherwise exactly one header plus items. Rebuild `{'version', 'operation_id', 'expected_set_revision', 'mappings', 'new_entities', 'authorities', 'parents'}` from the header and the items in ordinal order. The ordinals must be contiguous from 0 and match `counts`, and `digest(decisions)` must equal the header `digest`.
7. Every decision must name a member in the inputs, and an entity or fact local ID present in that member's stage (`MappingIndex.require_complete` raises `import_invalid` for an extra mapping).
8. Revisions and heads: every head's `next_revision_id` is a revision row. Revisions that share a `source_key_digest` share one `economic_group_id`. A chain without heads (coverage, membership, positions) has at most one tip, meaning a revision no other same-key revision names as `parent_revision_id`.
9. The `mappings` resource is validated (every row names an input entity) but never selects a target. `mapping.py` says "this module never selects a target for a user"; a READY Plan uses only the stored decisions.

Refusals (raise, return nothing). Use these fixed codes, which match `approval.py`:

| Condition | Code | Field |
|---|---|---|
| A resource with no page, no terminal page or two terminal pages, a page that fails `BasisPage` validation, or a duplicate row | `import_invalid` | `$.basis.<resource>` |
| Pages with different pins | `import_stale` | `$.basis` |
| An input whose `digest` differs from the SHA-256 of its Minimal | `import_stale` | `$.basis.inputs` |
| A Minimal that fails `decode` | the code `decode` raises | as raised |
| Context missing or doubled, or its pinned members differ from the inputs; 0 or more than 4 members | `import_invalid` | `$.basis.context` |
| A decisions header and items that disagree (digest, counts, ordinals) | `import_invalid` | `$.basis.decisions` |
| A decision for an unknown member, entity or fact, or a parent or `accepted` authority side naming a revision ID that is not in `revisions` (accepted revisions are immutable, so the decision was never valid) | `import_invalid` | `$.decisions` |
| A head whose revision is missing, one source key with two groups, or two tips of one chain | `import_invalid` | `$.basis.revisions` |
| `allocate_id` returns a non-canonical UUID, a value it returned before, `preview_id`, or an ID already in the basis | `import_conflict` | `$.ids` |
| `len(encode(bundle)) > contracts.MAX_SET` (16,777,216), or a row or collection over its schema bound | `import_limit` | `$` |
| The builder's own final `validate_review_bundle` check fails | that check's code | as raised |

Everything else, every case where r7 says a fact blocks or conflicts, produces a CONFLICT or NEEDS_MAPPING review with no Plan (Decisions needed item 2). Under IMP-007V's rule Q25 a refusal leaves the set waiting for cancel or expiry with no explanation, so only a basis the builder cannot trust is refused.

### Review state

- NEEDS_MAPPING when there are no decisions, or when the decisions cannot map every entity. That covers `require_complete` raising `import_mapping_required`; a proposed version that differs from `digest(proposed_body(...))`; one proposed target ID with two different bodies; and an `existing` target with no matching `entities` row, which means the target is gone or no longer compatible.
- CONFLICT when the mappings are complete but at least one fact gets `action: 'conflict'` (table below).
- READY otherwise.
- `set_revision` is the page `set_revision` plus 1 for READY, otherwise equal. `accepted_generation`, `mapping_generation` and `control_generation` are the pins. `expires_at` is the context `set_expires_at`. `id` is `preview_id`. `content_digest` is `digest(content)`, and `plan_digest` is `digest(plan)` for READY, otherwise null. These match `prepare_preview_v1` (`result_revision`, the pin and expiry checks).

### Row layout

Rows go in member blocks, in ascending member-ID order (the inputs order). `ordinal` is the row's zero-based position as a string. A planning check against all 11 READY review vectors and the four initial vectors confirmed this layout exactly.

READY and CONFLICT block for one member:

1. `source_entity` for every account, then every asset (`entity_kind: 'instrument'`), then every issuer, each in local-ID order; `source` is the staged row.
2. `target_candidate`, one per mapping of this member, in decisions order: the decided target and its body (proposed: `proposed_body` with the member's `MappingIndex`; existing: the body of the matching `entities` row).
3. `mapping`, this member's decision mappings in decisions order.
4. `authority`, the decision authorities that belong to this member: the member of the left side if it is `incoming`, else of the right side if that is `incoming`, else the first member.
5. `parent`, this member's decision parents in decisions order.
6. `fact` rows for records, then coverage, then snapshots, then membership, each in local-ID order. In READY each `fact` row is followed by its `effect` row. `record` holds the staged record for `records` and is null otherwise; `scope` holds the staged coverage, snapshot or membership and is null for records.
7. READY only: `head` rows for this member's facts, in fact order (a snapshot's heads in its `coverage_local_ids` order).
8. `diagnostic` rows, one per entry of this member's `provenance.diagnostics`, in admitted order. Every state discloses them, because `prepare_preview_v1` checks the multiset in every state. No vector holds a diagnostic, so this position is a plan choice.

No `member` rows are produced.

`prepare_preview_v1` and `_validate_plan_v1` require the mapping, authority and parent rows to equal the decisions arrays in order, and Plan `mappings`, `new_entities`, `authorities` and `parents` to equal the decisions verbatim. `decide_set_v1` does not sort them. If the per-member attribution above would reorder any of the three arrays (they are not grouped by member in member order), use one block for the whole set instead. That block holds all `source_entity` rows (members in order), all candidates (decisions order), all mapping rows, authority rows, parent rows, then every member's fact and effect rows, heads and diagnostics in member order. Test this fallback with a two-member case whose decisions are interleaved.

NEEDS_MAPPING block for one member: `source_entity` rows as above, then `target_candidate` rows, then `diagnostic` rows. No mapping, authority, parent, fact, effect or head rows. This matches the four initial vectors, which disclose no facts. Candidates go in the `source_entity` order (accounts, instruments, issuers). For each entity, first every `entities` basis row for it in (target ID, version) order, then one proposed candidate whose ID comes from `allocate_id(('entity', member, kind, local))`. Proposed bodies are `proposed_body(...)` with a `MappingIndex` built from this member's proposed issuer candidates, so a proposed instrument names its issuer's proposed ID. `validate_review_bundle` and the SQL accept a proposed instrument only when exactly one issuer candidate has that ID. Build issuer bodies first. `_INITIAL_REVIEW_CANDIDATES` requires the existing candidates to equal the eligible `entities` rows exactly, so disclose all of them.

### Fact classification (READY and CONFLICT)

For each fact, `scope = {'tenant_id', 'portfolio_id', 'connection_id'}` comes from the context and the member's pinned source. `key = source_revision_key(...)` and `material = digest(financial_projection(minimal, collection, local_id, MappingIndex(decisions['mappings'], member), scope=scope))`. A row of the `revisions` resource belongs to the same source key when its `source_key_digest == digest(key['source'])`, and is the exact revision when its `source.revision` also equals `key['revision']`. A parent decision for the fact, if any, gives `parent_revision_id`.

Activity records (`record_type: 'activity'`):

- With same-key revisions: `group` is their `economic_group_id`. The head row has key `digest({'version': 1, 'tenant_id', 'portfolio_id', 'economic_group_id': group})` and gives `current` (its `next_revision_id`'s revision, with `active` from the head); `exact` is the exact revision or None.
- `change` is the record's `identity.change`. When it is `original` and a parent decision names the fact, pass `'correction'`. Then call `reconcile_revision`.
- `RevisionDecision('duplicate', id, _)` gives action `duplicate`, `accepted_revision_id = id`, the chain's group, `parent_revision_id` null, no head.
- `('append', None, True)` with no same-key revision gives `append`: a new revision ID, a new group from the allocator, and a head `{kind: 'activity', key_digest: <new group's key>, prior_revision_id: null, next_revision_id: <new id>, complete_base_id: null, active: true}`.
- `('append', prior, active)` with a prior gives `correction` (or `void` when `change` is `void`): a new ID, the chain's group, `parent_revision_id = prior`, and a head with `prior_revision_id = prior`, `active` as returned.
- `reconcile_revision` raising `import_conflict` gives a CONFLICT fact. The code is `parent` when a parent decision exists, the source says `correction` or `void`, or the material changed under a new revision. It is `identity` when the same revision key carries changed material.
- Also CONFLICT `parent`: the decided parent already has a child in `revisions` (a fork; `_references_v1` returns `import_stale` for it), or `identity.parent` is set and differs from the parent revision's `source` claim and revision.
- CONFLICT `identity` when the native stage policy is ambiguous (`provenance.parser_api` null and `provenance.id_policy == 'ambiguous'`). Parser2 policy text is prose; admission already checked the profile.

Coverage and membership: there are no heads. `current` is the chain tip from step 8 of Intake (`active` true), `exact` as above. Call `reconcile_revision`. The outcomes are `duplicate` (the existing ID), `append` (new ID, no head), or `correction` with a parent decision, or CONFLICT `parent`/`identity` as for activities. Group is null.

Snapshots, with their positions and coverage:

- The snapshot's head keys are one per `holdings` coverage in `coverage_local_ids`: `digest({'version': 1, 'tenant_id', 'portfolio_id', 'account_id': <mapped account ID of the coverage account>, 'record_kind': 'holdings', 'instrument_scope': {'tag', 'category', 'instrument_ids': <sorted mapped instrument IDs>}})`. This matches `snapshot-history-effects.json` `head_digest` `87eb6e28…`.
- An exact same-key snapshot revision with equal material gives `duplicate`, and its children must then be exact duplicates. Changed material gives CONFLICT `identity`.
- Otherwise, for each head key, the current head row (if any) gives the current revision. Its typed `as_of` goes to `snapshot_order(incoming_as_of, current_as_of, same_material=<digests equal>, explicit_parent=<a parent decision names this snapshot>)`. All head keys must give one result.
  - `new` (a key with no current head counts as `new`): `append` with a new ID. Each key gets a head `{kind: 'snapshot', prior_revision_id: <current head's next or null>, next_revision_id: <new id>, complete_base_id: <new id if that coverage's status is 'complete', else the current head's complete_base_id or null>, active: true}`.
  - `correction`: `correction`, with the decided parent, which must be every key's current head.
  - `historical`: valid only when a decision authority `{kind: 'historical_only', left: {form: 'incoming', member_id, collection: 'snapshots', local_id}}` names this snapshot. The action is then `historical`, with a new ID and no head. Without it the snapshot is CONFLICT `authority`.
  - `duplicate` (equal instant, equal material): `duplicate` of the current head's revision.
  - `snapshot_order` raising, keys that disagree, or an `as_of` that is `legacy_unspecified` or `date_only` without a zone while the snapshot would change a head (`_references_v1` refuses it): CONFLICT `unsupported`.
- Children: positions in `position_local_ids` and coverage in `coverage_local_ids` take `historical` (new IDs) when the snapshot is `historical`. Otherwise each child is classified like coverage above (`append` for a new observation ID, `duplicate` for an exact one). A child of a CONFLICT snapshot is a CONFLICT fact with the snapshot's code. Positions always have a null group and no head.

Across facts of one set:

- Two facts of one member with the same `SourceRevisionKey`: both CONFLICT `identity`, because r7 blocks indistinguishable twins.
- A fact in a later member (member order) with the same key as an earlier member's new fact and the same material: `duplicate` of that earlier fact's new ID, with its group and no head. Different material: both CONFLICT `identity`.
- Every claim in an activity's `economic_references`, `cash_flow.counterpart` and `cash_flow.cash_leg_of` must match exactly one revision among the incoming facts and the `revisions` rows. A revision's claim is its source key without `version`, `tenant_id`, `portfolio_id`, `connection_id` and `collection`, plus its revision; a claim with a null revision matches any revision. Zero or several matches make the activity CONFLICT `identity`. This is the same rule as the claim loop of `_references_v1`.
- Competing streams: two incoming activities from different connections with the same mapped source account and the same `kind`, whose same-account, same-kind coverage windows overlap. Follow `_stream_authority_sql`, where an unknown comparison counts as overlap. Without a decision authority of kind `mirror`, `independent` or `authority` linking them, both are CONFLICT `authority`. The builder cannot run this check against accepted revisions of other connections, because `AcceptedRevisionBasis` has no connection, mapped account or windows (Decisions needed item 3). The database still refuses such a Plan with `import_conflict`. IMP-007X extends the basis so a later builder change can show this CONFLICT.
- A decision authority `mirror` whose left side is incoming: that fact is CONFLICT `unsupported` (Decisions needed item 4; IMP-007Y adds the vectors and the effect). A `historical_only` authority on anything but an incoming snapshot: CONFLICT `unsupported`.

CONFLICT fact rows: `action` is `conflict` with a `required_decision` code for blocked facts. Other facts show the action they would get, with `required_decision` null. `accepted_revision_id` is the existing ID for `duplicate` and null for everything else; no ID is reserved without a Plan. No `effect` or `head` rows. `account`, `instrument`, `issuer` and `coverage` are never used here: missing mappings give NEEDS_MAPPING, and coverage gaps are refused at stage admission.

| `required_decision` | Cases |
|---|---|
| `identity` | Same revision key with changed material; twins in one member; cross-member key collision with different material; unresolved or ambiguous claim; native `ambiguous` policy on an activity |
| `parent` | Changed meaning under a new revision without a parent decision; a source correction or void without one; a decided parent that is not the current active head of the same chain, already has a child, or differs from `identity.parent`; an equal-instant snapshot with different content and no parent |
| `authority` | An older snapshot without `historical_only`; overlapping incoming streams without an authority decision |
| `unsupported` | Incomparable snapshot times, or keys that disagree; a head-changing `as_of` that is legacy or date-only without a zone; a `mirror` with an incoming left side; `historical_only` on a non-snapshot |

### Authority rows

- `prior_choice`, `prior_link_id` and `prior_link_revision` follow the SQL in `_PREPARE_REVIEW_ROWS`. Resolve each side: an `accepted` side to its ID; an `incoming` side, in READY only, to that fact's new `accepted_revision_id`.
- When the left side resolves, and the right side resolves or is null, take the `authorities` row with the highest `link_revision` whose (left, right) equals the pair in either orientation. Its `kind`, `link_id` and `link_revision` fill the three fields. Otherwise all three are null.
- Two links that tie on the highest revision: refuse with `import_conflict` at `$.basis.authorities`. An `accepted` side that is not in `revisions` is refused earlier (Intake table).
- `authority-only` must show `independent`, `d0000000-0000-4000-8000-0000000000ce` and `"1"`.

### Plan (READY only)

`version` 1. `tenant_id`, `portfolio_id`, `set_id`, `realm_digest`, `incarnation` and `restore_epoch` come from context. `preview_id` is the argument. `decision_digest` is the header `digest`. `expected_set_revision` is the review `set_revision`. The three generations are the pins. `expires_at` is the context `set_expires_at`. `pinned_sources` is the context list unchanged. `inputs` holds `{member_id, stage_digest: <input digest>, raw_digest: provenance.raw_sha256, discovery_digest: provenance.discovery_sha256}` in member order. `mappings`, `new_entities`, `authorities` and `parents` are the decisions arrays verbatim. `facts` are the effect rows in row order: `{member_id, collection, local_id, action, accepted_revision_id, parent_revision_id, economic_group_id, financial_digest: material}`. `heads` are the head rows in row order. `review_content_digest` is `digest(review['content'])`.

Last step before returning: run `validate_review_bundle(encode(bundle), stages=<stage map>)` and the size check. A failure is the builder's refusal; never return a bundle that fails it.

### Test basis for the oracle cases (AC-01, 04)

Add a test helper `oracle_basis(case, *, page_size=50, order=None)` that builds BasisPages from oracle literals. It must not call `review_bundle`. The helper takes these values as given, and each must be cross-checked as stated:

| Case | Inputs (member -> stage) | Decisions | Accepted state served by `revisions`, `heads`, `authorities`, `entities`, `mappings` | Expected |
|---|---|---|---|---|
| first-use | `20…01` -> `minimal-parser2.json` | `decisions-first-use.json` | none | `plan-first-use.json`, `review-parser2-ready.json`, `review-bundle-first-use.json` |
| native first-use | `20…01` -> `minimal-native.json` | `decisions-native-first-use.json` | none | `plan-native-first-use.json`, `review-native-ready.json` |
| `metadata-native` | `20…01` -> `metadata-native-minimal.json` | `metadata-native-decisions.json` | none | `metadata-native-plan.json`, `review-metadata-native-ready.json` |
| `mixed-set` | `20…01` -> `minimal-parser2.json`, `e0…01` -> `snapshot-t2-complete-minimal.json` | `mixed-set-decisions.json` | none | `mixed-set-plan.json`, `mixed-set-review.json` |
| `snapshot-seed-t2` | `e0…01` -> `snapshot-t2-complete-minimal.json` | `snapshot-seed-t2-decisions.json` | none | its plan and review |
| `snapshot-historical-t1` | `e0…02` -> `snapshot-t1-minimal.json` | `snapshot-historical-t1-decisions.json` | `snapshot-seed-t2` accepted, as `snapshot-history-effects.json` sequence[0] states | its plan and review |
| `branch-fresh_duplicate_only`, `branch-new_equal_meaning_revision`, `branch-equal_value_explicit_correction` | the case's `*-minimal.json` under the plan's member | the case's `*-decisions.json` | `plan-first-use.json` accepted | its plan and review |
| `branch-mapping_only_existing_issuer` | its `*-minimal.json` | its `*-decisions.json` | `plan-native-first-use.json` accepted, plus the existing issuer | its plan and review |
| `authority-only` | `branch-fresh_duplicate_only-minimal.json` under `d0…65` | `authority-only-decisions.json` | `plan-first-use.json` accepted, plus `authority-only-prestate.json`: `peer_revision` as a `revisions` row, an activity head for its group, and `prior_authority` as an `authorities` row with `link_id` `d0…ce` and `link_revision` `"1"` | its plan and review |
| Initial (NEEDS_MAPPING) | as first-use, native and `metadata-native` | none | none | `review-parser2-initial.json`, `review-native-initial.json`, `review-metadata-native-initial.json`, and the review of `review-bundle-initial.json` |

Rows built from an accepted baseline plan, following `_accepted_basis_seed` in `tests/test_postgres_migration.py`:

- One `revisions` row per baseline fact. `id` and `financial_digest` come from the fact. Use one fixed `input_id`. `collection` and `local_id` come from the fact. `typed` is the staged row of the baseline Minimal. `source` is `source_revision_key(...)['source']` without `version`, `tenant_id`, `portfolio_id`, `connection_id` and `collection`, plus `revision`. `source_key_digest` is `digest(key['source'])`; assert that it equals the matching `key-preimages.json` `sha256` where a vector exists. `accepted_change` is `original`, `parent_revision_id` null, and `economic_group_id` comes from the fact.
- One `heads` row per baseline head (the HeadEffect verbatim).
- One `entities` row per `existing` decision mapping. The body comes from the literal `metadata-native-bodies.json`, `entity-bodies.json`, `entity-bodies-native.json` or `snapshot-target-bodies.json` entry whose digest is the target version. The existing issuer of `branch-mapping_only_existing_issuer` is in no body file; copy it from that case's review candidate and assert its digest equals the target version.
- `mappings` rows: the baseline's mappings as `existing` targets, under the incoming member.

Pass-through values. They come from the case's expected Plan or review, because only the database holds them; AC-08's reviewer should not count them as evidence:

- Context `tenant_id`, `portfolio_id`, `set_id`, `realm_digest`, `incarnation`, `restore_epoch`, `set_expires_at` and `pinned_sources`.
- The pins: `set_revision` is the expected `set_revision` minus 1 for READY and equal for initial; generations as expected; any fixed `job_id` and `fence`.
- The `*-context.json` entries are child contexts, not the `prepare_context` row; do not use them for it.

The test allocator is a dict built from the expected vector: new fact IDs (non-duplicate), new groups (`append` activities) and initial proposed IDs. It raises on any slot not in the dict, and the test asserts that the set of requested slots equals the dict's keys. That checks independently which facts the builder treats as new. `preview_id` is the expected review `id`.

Independent cross-checks the test asserts besides byte equality: the activity head key `ab5991be…` equals `digest` of the `ActivityHeadKey` for group `80000000-…-01`. The snapshot head key equals `snapshot-history-effects.json` `head_digest`. Every duplicate's `accepted_revision_id` and `financial_digest` equal the baseline fact's. The authority row of `authority-only` carries the prestate `prior_link_id` and `prior_link_revision`.

### Tests

Name the acceptance ID in each test's docstring.

| AC | Test (`tests/test_ingestion_review_bundle.py` unless noted) | Expected |
|---|---|---|
| 01 | One subtest per READY case in the table: build with `oracle_basis(case)` | `encode(bundle['review'])` equals `encode` of the case's review vector, and `encode(bundle['plan'])` equals `encode` of its Plan vector, byte for byte. For `review-bundle-first-use.json`, `encode(bundle)` equals `encode` of the whole vector. Requested slots equal the allocator keys. |
| 01 | One subtest per initial vector | `encode(bundle['review'])` equals the vector, `plan` is null, and the requested slots are exactly the `entity` slots. |
| 02 | Gated (`KURAFOLIO_INGESTION_TEST=1`), in `tests/test_postgres_migration.py` `IngestionAppendOnlyPostgresTests` or a new class there. For each of first-use, native first-use, the four `branch-*`, both `snapshot-*`, `authority-only` and `mixed-set`: seed the database (`accept_seed`, `_plan_seed`, `_preview_seed`, `_accepted_basis_seed`, `row` and the link-row pattern of the authority tests), claim the prepare lease (`plan_claim(..., work_kind="'prepare'")`), read every resource with `basis_call(..., resource=...)` following cursors, build with the oracle IDs, then call `prepare_preview_call`. | `prepare_preview_v1` returns `ok: true` with state `READY`, and a replay returns `already_prepared`. `approval.validate_review_bundle` accepts the bundle. For first-use and native first-use, a second subtest builds the initial NEEDS_MAPPING bundle (no decisions, set `NORMALIZING`), and `prepare_preview_v1` accepts it too. Values the database owns (realm, expiry) differ from the vectors; this AC checks acceptance, not bytes. |
| 03 | Stages from `examples/data/wealthsimple-holdings.csv` and `examples/data/bull-orders.csv`, built as in `IngestionDiscoveryTests.builtin` (`tests/test_ingestion_discovery.py`). Build NEEDS_MAPPING, take every proposed candidate as decisions (mappings and `new_entities` in candidate order, no authorities or parents), and build READY. | Wealthsimple: 3 account `source_entity` rows; 6 `records` fact rows, all positions; `market_value` sums by currency CAD 565 and USD 150 (compare as `Decimal`, strings unchanged); 3 coverage facts all `partial`; membership `unknown`; snapshot `as_of` `2024-02-01T10:00:00-05:00`; 3 snapshot heads with null `prior_revision_id` and `complete_base_id`; every group null. Bull: 2 accounts; 2 `BUY` facts whose `ACQUISITION` legs sum to BTC 0.00400000 and LBTC 0.00300000; acquisition cost 700.00 CAD; `FUNDING` cash 1000.00 CAD with `boundary` `unclassified` and no legs; 3 completed activity facts, each `append` with its own group and activity head; 3 `diagnostic` rows equal to the stage's diagnostics. No key or value naming a contribution or wallet balance appears in `encode(bundle)` except the diagnostic codes `wallet_balance_unverified` and `wallet_fees_unknown`. Both values come from `builtin-inputs.json`. |
| 04 | Every case: page sizes 1, 7 and 50; pages in read order, reversed and interleaved across resources; two builds | One identical `encode(bundle)` for all of them. |
| 05 | Mutations of `first-use` and `branch-fresh_duplicate_only` bases: each refusal row of the Intake table, plus an over-limit bundle | Each raises `IngestionError` with exactly the code and field in the table, and returns nothing. The over-limit case is real bytes: four members, each a valid Minimal near `MAX_MINIMAL` (pad `large-basis-minimal.json` with more records, under 10,000 rows), whose encoded bundle exceeds 16,777,216. Do not patch the limit. |
| 05 | CONFLICT literals, each a mutation of an oracle case, with expected rows written by hand from the table above | `branch-new_equal_meaning_revision` with the record's cost changed consistently (cost, legs and lifecycle, so the stage still decodes): the record is `conflict`/`parent`, coverage and membership stay `duplicate` with their IDs, plan null. `snapshot-historical-t1` without its authority: all four facts are `conflict`/`authority`. Two members of one connection carrying the same record key with different cost: both `conflict`/`identity`. A `mirror` decision whose left side is the incoming record: that record `conflict`/`unsupported`. The two-member fallback layout with interleaved decisions, built READY. `authority-only` with the right side replaced by an ID not in `revisions` is a refusal case (`import_invalid`), not a CONFLICT. Each bundle passes `validate_review_bundle`. |
| 06 | Static: parse `review_bundle.py` with `ast` | Imports are exactly within the allowed list; no `open`, `eval`, `exec`, `compile` or `__import__` name. |
| 06 | Runtime: patch `time.time`, `time.time_ns`, `time.monotonic`, `time.perf_counter`, `random.random`, `random.getrandbits`, `os.urandom`, `secrets.token_bytes`, `uuid.uuid1`, `uuid.uuid4`, `os.getenv`, `os.environ` (a mapping that raises on any access), `builtins.open`, `io.open`, `socket.socket` and `socket.create_connection` to raise, then build every AC-01 case | Every build succeeds with the same bytes as unpatched. |
| 07 | `large-basis-minimal.json` as one member, NEEDS_MAPPING then READY as in AC-03; time both builds with `time.perf_counter` outside any patching | Each build under 10 seconds; record the times in the PR. |
| 08 | Review only | The reviewer traces every fact, effect and head of each AC-01 vector to a stage, decision or basis row, against `reconciliation.md`. |
| 09 | `docs/web-v2-imports.md` | Below. |

Do not raise any tolerance and do not weaken an existing test to make these pass.

### Docs (AC-09)

After the paragraph that ends "IMP-007F wires these private calls into the worker, and IMP-007D verifies the installed functions and grants.", add a paragraph on `src/kurafolio/ingestion/review_bundle.py`. It should cover:

- It turns one prepare lease's basis pages into a `ReviewBundle` and decides only from stages, stored decisions and accepted revisions, heads and links.
- It produces NEEDS_MAPPING with every eligible existing candidate plus one proposed candidate per entity, CONFLICT with `required_decision` per blocked fact and no Plan, or READY with the Plan.
- It never chooses a mapping or authority for the user, never generates IDs (the caller passes them), never infers contributions, wallet balances or zero holdings, and copies amounts unchanged.
- It refuses, with the fixed codes, only a basis it cannot trust or a bundle over 16 MiB.
- Its limits: no competing-stream check against accepted revisions of other connections (the database still refuses; IMP-007X); no `mirror` effect for an incoming fact (IMP-007Y).
- No worker calls it until IMP-007V.

### Do not touch

`approval.py`, `mapping.py`, `reconciliation.py`, `codec.py`, `contracts.py`, `cursors.py` and their tests; `src/kurafolio/persistence/` (no SQL, grant or DTO change); `docs/specs/imp-007-r7/`; `tests/fixtures/ingestion/oracle.json`; the worker (`worker.py`, IMP-007F and IMP-007V); the "keep, or mark closed?" question for a missing account (IMP-007T). Existing tests in `tests/test_postgres_migration.py` stay as they are.

### Rollback

The module is pure and nothing calls it until IMP-007V merges. Reverting the pull request removes it and its tests. No data, schema or stored preview depends on it.

### Stop and ask if

- An AC-01 vector cannot be reproduced by the rules above, or a case cannot be expressed as basis pages. Do not change the vector or bend a rule to fit one case.
- `prepare_preview_v1` refuses a bundle that `validate_review_bundle` accepts, and the cause is not a test seed.
- A case in AC-02 has no seed path with the existing helpers short of editing them.
- A r7 outcome is not in the CONFLICT table, or a rule here contradicts `reconciliation.md` or the SQL checks.
- The build of the largest realistic basis (4 members of 10,000 rows) takes more than 30 seconds, half the 60-second lease. Measure it once and report it, even though AC-07 bounds only `large-basis`.

## Plan

- [x] Test helper `oracle_basis` for every case in the Build plan's table; record any case that cannot be mapped and stop.
- [x] Intake and refusals (pages, pins, inputs, context, decisions) with the AC-05 refusal tests.
- [x] NEEDS_MAPPING reviews, matching the four initial vectors.
- [x] Fact classification and the READY Plan: activities, then coverage and membership, then snapshots; AC-01 byte for byte.
- [x] CONFLICT reviews and their literals; AC-03, AC-04, AC-06 and AC-07.
- [x] Gated PostgreSQL acceptance (AC-02) through `read_plan_basis_v1` and `prepare_preview_v1`; the CI skip count.
- [ ] Docs (AC-09); full suite; pull request with the independent QA and Architect reviews.

## Decisions needed

1. Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes. **Resolved 2026-11-21.** Asked "Gate A, tickets whose text is unchanged since filing (full text on PR #95's branch). Which do you approve exactly as written?" with this ticket listed at sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766, the owner selected "IMP-007O,IMP-007P,IMP-007U,IMP-007S" (Q31). `gate_approval` and `spec_approved` record it.

Items 2 to 4 came up while writing the Build plan (2026-11-22). They do not change the gated text; each asked the owner to confirm how the plan reads it. **Resolved 2026-11-22.** Asked "Do you accept the planner's recommendations on decisions 2 to 4?", the owner answered "Accept all three", relayed to this planning session by the coordinating session. Each item below is resolved as option (a), and the Build plan follows it.

2. **Refuse, or show a CONFLICT review?** Requirements say "A basis it cannot reconcile ... raises a fixed error code and returns nothing." The r7 tables call many valid outcomes a conflict or a block: changed facts under a known ID with no parent, an older snapshot with no history choice, identical twins, competing streams. `prepare_preview_v1` accepts a CONFLICT review without a Plan. Under IMP-007V's rule Q25, a refusal leaves the set waiting for cancel or expiry, and the user is not told why.
   - (a) "Cannot reconcile" means a basis the builder cannot trust: the AC-05 cases and the other integrity failures in the Build plan's Intake table. Every r7 conflict outcome produces a CONFLICT review with `required_decision` on each blocked fact, and no Plan, so the user can change a decision or cancel. **Recommended. Chosen 2026-11-22.**
   - (b) Refuse for every r7 conflict outcome too. The builder then produces only NEEDS_MAPPING and READY, and such sets wait for cancel or expiry.
3. **Competing streams against accepted revisions of another connection.** `_references_v1` refuses a Plan when an incoming activity and an active accepted activity of another connection have the same mapped account and kind, overlapping coverage windows, and no authority choice. `AcceptedRevisionBasis` carries no connection ID, mapped account or windows, so the builder cannot detect this from the basis. It can detect it between members of the same set.
   - (a) Build without that check. The database still refuses such a Plan (`import_conflict`), and that set then waits for cancel or expiry under Q25. `docs/web-v2-imports.md` states the limit. File a follow-up that extends the basis (an r7 contract and SQL change) so the builder can show a CONFLICT asking for the choice. **Recommended. Chosen 2026-11-22; the follow-up is IMP-007X.** The reason: it affects only two connections mapped to one real account without an earlier choice, and no oracle case needs it.
   - (b) Over-block: show CONFLICT `authority` whenever an active accepted activity head may come from another connection with the same provider and kind. This would ask for many needless choices and still miss renamed accounts.
   - (c) Hold this ticket until the basis is extended.
4. **`mirror` effect for an incoming fact.** No oracle vector pins the economic group, head or parent of a fact accepted as a mirror. r7 implies the authoritative side's group, but nothing fixes it.
   - (a) Show CONFLICT `unsupported` for an incoming fact on the left of a `mirror` decision, until a follow-up adds vectors. `authority-only`, a mirror between two accepted revisions, is unaffected. **Recommended. Chosen 2026-11-22; the follow-up is IMP-007Y.**
   - (b) Build the `mirror` effect with the authoritative side's group, no head and no parent, checked only by the database.

## Handoff

- State: Local implementation, AC-09 docs and developer validation are complete. The default suite passes 1,440 tests with 267 opt-in skips; the final focused builder suite passes 14 tests, and the real PostgreSQL test accepts/replays all 12 required initial/READY subcases with no skips. No worker, schema, helper or frozen vector changed. The local evidence index is `work/imp-007p/final-handoff.json`.
- Next step: Obtain the exact-HEAD candidate image receipt, record it in the local evidence index, then obtain the applicable owner approval for publication of this branch. Open the PR before the eventual done/pr outcome commit, and request the configured independent reviews.
- Verify: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_ingestion_review_bundle.py -v`; `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src:tests .venv/bin/python -m unittest test_postgres_migration.IngestionAppendOnlyPostgresTests.test_review_bundle_builder_from_live_prepare_basis -v`; `python3 scripts/tickets.py spec IMP-007P --base origin/main`; `python3 scripts/check_pr_image.py` from a clean tracked tree.
- Gotchas: Use an existing equivalent Python 3.12 Web-test environment. Independent QA and Architect reviews remain NOT RUN because the configured reviewer must be started in Claude Code. Run `review IMP-007P` there after PR creation; frontier owner review follows those reviews. No worker calls this module before IMP-007V.
- Open questions: None about the approved behavior; publication and independent reviews are outstanding.

## Log

- 2026-11-20 claude-code/opus-5.5: filed in plan pull request #86 from the owner's decision of 2026-11-20 on "No merged code builds the ReviewBundle ... Who builds it?": the owner chose "New ticket (Recommended)": "risk critical, tier frontier, own review." (IMP-007F D2 = (a).) On the wait, the owner chose "Build now, prepare last (Recommended)": "No depends_on. Builders do PR 1 and PR 2 now; prepare and AC-04 land in a third PR once IMP-007P merges." Status backlog; no Gate A yet.
- 2026-11-20 claude-code/opus-5.5: the owner chose "Split prepare out (Recommended)" (Q16): "Move the prepare step and AC-04 to a new ticket (IMP-007V) that depends on IMP-007F and IMP-007P." The caller of this builder is now IMP-007V, not IMP-007F's third pull request; Context, the Requirements "Not in scope" line and Handoff say so. Spec hash changes from sha256:def5b60480742768882339fd55443e0f9af5f984b7c7d6f5ac094087b21bed27 to sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766; the ticket was never approved.
- 2026-11-21 claude-code/opus-5.5: recorded Gate A in plan pull request #95. Asked "Gate A, tickets whose text is unchanged since filing (full text on PR #95's branch). Which do you approve exactly as written?" (Q31) with this ticket listed at sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766, the owner selected "IMP-007O,IMP-007P,IMP-007U,IMP-007S". `gate_approval` set to "owner 2026-11-21, Gate A on the text as written on PR #95's branch (Q31)"; `spec_approved` set to sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766, which `tickets.py spec` reports as the current hash; status backlog becomes ready. Decisions needed item resolved. No Build plan yet; the planner writes it in a later pull request.
- 2026-11-22 claude-code/opus-5.5: wrote the frontier Build plan from `main` at `7d7acc1` in plan pull request https://github.com/gh-slee/kurafolio/pull/105. Updated the Context with the planning findings (caller-supplied IDs, verbatim decision arrays, no facts in initial reviews, refusals under Q25, the competing-stream gap, the CI job that runs gated tests), replaced the Plan steps and added Decisions needed items 2 to 4 for the owner, with the plan following each recommendation. Gate A (#95, Q31) and the gated sections are unchanged.
- 2026-11-22 claude-code/opus-5.5: recorded the owner's answer to Decisions needed items 2 to 4 in plan pull request https://github.com/gh-slee/kurafolio/pull/105, relayed to this planning session by the coordinating session. Asked "Do you accept the planner's recommendations on decisions 2 to 4?", the owner answered "Accept all three": item 2 (a), refuse only an untrusted basis and show a CONFLICT review for r7 conflict outcomes; item 3 (a), build without the competing-stream check against accepted revisions of other connections; item 4 (a), CONFLICT `unsupported` for an incoming `mirror`. "Before you claim" no longer waits on them. Filed the follow-ups IMP-007X (extend the basis for that check) and IMP-007Y (mirror vectors and effect) as backlog tickets in the same pull request. No Gate A recorded; the gated sections are unchanged.

- 2026-11-22 codex/gpt-6.1-sol: claimed the merged Build plan from origin/main; spec sha256:ab4f0a665240bd37f278712f3dc78aa90db9a7ecb92f3fc7e0700f67a4bab766 matches. Started the independent oracle basis helper before builder implementation.

- 2026-11-22 codex/gpt-6.1-sol: implemented the pure builder and independent literal basis helper. All planned oracle review and Plan bytes match; focused determinism, builtin, CONFLICT and ambient-I/O checks pass. The large-basis fixture builds in 0.013 s (NEEDS_MAPPING) and 0.031 s (READY) locally. Maximum-size and PostgreSQL acceptance remain outstanding.

- 2026-11-22 codex/gpt-6.1-sol: completed the planned core acceptance coverage (14 focused tests), AC-09 docs and one gated PostgreSQL test that accepts/replays 12 live-lease subcases in 9.085 s with no skips. The foundation skip guard increases from 128 to 129. Four valid 4,096,703-byte stages exceed the real bundle limit and are refused in 9.800 s; the separate 4 x 10,000-row probe is refused at the 4 MiB Minimal bound in 10.464 s. The default full suite is still running. Independent QA and Architect review are NOT RUN; no publication.

- 2026-11-22 codex/gpt-6.1-sol: completed the default developer suite: 1,440 tests in 745.501 s, 267 opt-in skips, no failures or errors. The final focused builder suite separately passes 14 tests in 26.157 s; live PostgreSQL accepts/replays all 12 required subcases in 9.085 s without skips. Language, worktree publication, ticket consistency and approved-spec checks pass. Candidate image verification follows this clean local checkpoint. Independent QA and Architect review are NOT RUN; CI and publication are NOT RUN.
