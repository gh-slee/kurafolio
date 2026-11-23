---
id: IMP-007Y
title: Add expected vectors for an incoming fact accepted as a mirror, and let the review builder produce it
priority: P1
status: backlog
type: feature
parent: IMP-007
depends_on: [IMP-007P]
resources: [ingestion-review-bundle]
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

# IMP-007Y: Add expected vectors for an incoming fact accepted as a mirror, and let the review builder produce it

## Goal

A user who imports the same activities through a second connection can mark the new source as a mirror of the stream already accepted. The import must then keep the new source's evidence without adding a second acquisition. Today the review builder shows CONFLICT `unsupported` for an incoming fact on the left of a `mirror` decision, because no expected vector fixes the economic group, head or parent of such a fact. Add independent expected vectors for that case and let the builder produce the `mirror` effect.

## Context

- Filed on 2026-11-22 in plan pull request #105 (IMP-007P) from the owner's answer to IMP-007P Decisions needed item 4: asked "Do you accept the planner's recommendations on decisions 2 to 4?", the owner answered "Accept all three". Item 4 (a) shows CONFLICT `unsupported` until this follow-up adds vectors.
- r7 rule (`docs/specs/imp-007-r7/reconciliation.md`, "Identity keys"): "An economic group consists of one authoritative accepted source chain plus explicit mirror-evidence links." It implies, but does not state, that a mirror fact joins the authoritative side's group.
- `_references_v1` in `src/kurafolio/persistence/ingestion_schema.py` requires a `mirror` fact to be the left side of a `mirror` edge, refuses `mirror` for a non-snapshot fact whose source key already has accepted revisions, and exempts `mirror` from the activity head rule. It does not check the mirror fact's `economic_group_id`.
- The oracle case `authority-only` covers a `mirror` decision between two accepted revisions only; its facts are duplicates.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md). New expected vectors in `tests/fixtures/ingestion/oracle.json` are written independently of the builder, and say how they were derived. If the vectors need a rule r7 does not state (for example the mirror fact's group), the owner decides it first and the decision is recorded.
- The `mirror` effect keeps the incoming source evidence and adds no acquisition, contribution, head or second authoritative chain.
- The builder produces `mirror` only for an incoming fact on the left of a `mirror` decision, and every Plan it produces passes `_references_v1` and `accept_preview_v1`.
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.
- Not in scope: the competing-stream basis (IMP-007X) and any SQL change. If the database cannot accept the vectors without one, stop and ask.

## Acceptance criteria

- [ ] AC-IMP-007Y-01: New oracle vectors give the decisions, review and Plan for an incoming activity accepted as a mirror of an accepted one, with the derivation recorded.
- [ ] AC-IMP-007Y-02: The builder's review and Plan for that case equal the vectors byte for byte, and `prepare_preview_v1` and `accept_preview_v1` accept them in an opt-in real-PostgreSQL test.
- [ ] AC-IMP-007Y-03: After acceptance, the accepted acquisitions and activity heads are the same as before the mirror import.
- [ ] AC-IMP-007Y-04: Every IMP-007P acceptance test still passes.
- [ ] AC-IMP-007Y-05: `docs/web-v2-imports.md` no longer lists the incoming mirror as a limit of the builder.

## Plan

- [ ] Planner writes the Build plan after Gate A and after IMP-007P merges.
- [ ] Vectors, builder change, tests, docs, pull request with the independent review.

## Decisions needed

Only the owner answers.

1. Gate A: the owner approves the Goal, Requirements and Acceptance criteria above, or asks for changes.

## Handoff

- State: Filed on 2026-11-22; backlog, waiting for the owner's Gate A and for IMP-007P to merge.
- Next step: The owner gives Gate A or asks for changes; then the planner writes the Build plan from the merged IMP-007P code.
- Verify: `python3 scripts/tickets.py spec IMP-007Y`
- Gotchas: Shares `ingestion-review-bundle` with IMP-007P and IMP-007X, so these build one at a time.
- Open questions: Gate A.

## Log

- 2026-11-22 claude-code/opus-5.5: filed in plan pull request https://github.com/gh-slee/kurafolio/pull/105 from the owner's answer to IMP-007P Decisions needed item 4 ("Accept all three", relayed to the planning session by the coordinating session). Status backlog; no Gate A yet.
