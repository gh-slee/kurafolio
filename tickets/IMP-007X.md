---
id: IMP-007X
title: Extend the prepare basis so the review can ask for a choice between competing source streams
priority: P1
status: backlog
type: feature
parent: IMP-007
depends_on: [IMP-007P]
resources: [ingestion-schema-sql, ingestion-review-bundle]
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
updated: 2026-11-22
---

# IMP-007X: Extend the prepare basis so the review can ask for a choice between competing source streams

## Goal

When a user imports activities from a second connection that maps to the same real account as an earlier connection, and the two streams overlap, the preview must ask which stream is authoritative instead of failing. Today the database refuses such a Plan, and the set waits for cancel or expiry without telling the user why. Give the prepare basis the facts the review builder needs to detect the overlap and show a CONFLICT review that asks for the authority choice.

## Context

- Filed on 2026-11-22 in plan pull request #105 (IMP-007P) from the owner's answer to IMP-007P Decisions needed item 3: asked "Do you accept the planner's recommendations on decisions 2 to 4?", the owner answered "Accept all three". Item 3 (a) builds IMP-007P without this check and files this follow-up.
- `_stream_authority_sql` in `src/kurafolio/persistence/ingestion_schema.py` (about line 1162, called from `_references_v1`) refuses a Plan with `import_conflict` when an incoming activity and an active accepted activity of another connection have the same mapped source account and `kind`, overlapping same-account coverage windows, and no `mirror`, `independent` or `authority` link or decision.
- `AcceptedRevisionBasis` in `docs/specs/imp-007-r7/wire-contracts.json`, served by the `revisions` resource of `read_plan_basis_v1`, carries the source claim, `source_key_digest`, `financial_digest`, `economic_group_id`, `parent_revision_id`, `accepted_change` and `typed`. It has no connection ID, no mapped source account, no mapped kind and no accepted coverage windows. `typed` holds local IDs of the accepted input, whose mappings the basis does not serve. The builder therefore cannot repeat the check.
- Under IMP-007V's rule Q25, the refused set is claimed again after each lease lapse until the user cancels it or it expires.
- The IMP-007P builder (`src/kurafolio/ingestion/review_bundle.py`) already detects overlapping streams between members of one set and shows CONFLICT `authority` for them.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md). Adding fields to `AcceptedRevisionBasis`, or a new basis resource, is an r7 contract change. It needs its own recorded amendment, approved by the owner, before any code changes.
- The basis gives the builder, for every active accepted activity head, exactly the inputs `_stream_authority_sql` uses: the revision's connection, mapped source account, material kind and the coverage windows of its accepted input. It gives nothing else, and only within the scoped tenant and portfolio.
- The builder shows CONFLICT with `required_decision: 'authority'` on each incoming activity that the database check would refuse, and never on one it would accept. A READY Plan the builder produces passes `_references_v1`.
- No accepted history, mapping or link changes. Existing previews and stored plans stay valid.
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.
- Not in scope: the `mirror` effect (IMP-007Y) and any change to the authority choices themselves.

## Acceptance criteria

- [ ] AC-IMP-007X-01: The r7 amendment is recorded and approved before the code changes, and the frozen bundle's index and file hashes are updated as that amendment says.
- [ ] AC-IMP-007X-02: For an incoming activity and an active accepted activity of another connection mapped to the same account and kind with overlapping windows and no link, the builder's review is CONFLICT with `required_decision: 'authority'` on the incoming activity, and `prepare_preview_v1` accepts it.
- [ ] AC-IMP-007X-03: With non-overlapping windows, a different mapped account, a different kind or an existing link, the builder's review is READY, and `prepare_preview_v1` accepts the Plan.
- [ ] AC-IMP-007X-04: Every IMP-007P acceptance test still passes, and the oracle vectors are reproduced byte for byte.
- [ ] AC-IMP-007X-05: `docs/web-v2-imports.md` no longer lists this as a limit of the builder.

## Plan

- [ ] Planner writes the Build plan after Gate A and after IMP-007P merges.
- [ ] r7 amendment, basis SQL, builder change, tests, docs, pull request with the independent review.

## Decisions needed

Only the owner answers.

1. Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes.

## Handoff

- State: Filed on 2026-11-22; backlog, waiting for the owner's Gate A and for IMP-007P to merge.
- Next step: The owner gives Gate A or asks for changes; then the planner writes the Build plan from the merged IMP-007P code.
- Verify: `python3 scripts/tickets.py spec IMP-007X`
- Gotchas: Shares `ingestion-schema-sql` with the other SQL tickets and `ingestion-review-bundle` with IMP-007P and IMP-007Y, so these build one at a time.
- Open questions: Gate A.

## Log

- 2026-11-22 claude-code/opus-5.5: filed in plan pull request https://github.com/gh-slee/kurafolio/pull/105 from the owner's answer to IMP-007P Decisions needed item 3 ("Accept all three", relayed to the planning session by the coordinating session). Status backlog; no Gate A yet.
