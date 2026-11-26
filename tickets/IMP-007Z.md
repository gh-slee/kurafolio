---
id: IMP-007Z
title: Run native-discovery members in the contained parser child
priority: P1
status: backlog
type: feature
parent: IMP-007
depends_on: [IMP-007F]
resources: [v2-import-worker]
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
updated: 2026-11-25
---

# IMP-007Z: Run native-discovery members in the contained parser child

## Goal

A file whose source installation uses the native discovery projection (`domain1-minimal-v1`) must be normalized in the same contained child as a parser2 file, and the worker must admit the result through the existing native admission checks. Until this ticket, IMP-007F's worker rejects such a member with `import_evidence_unsupported` before any launch (AC-IMP-007F-10). This ticket replaces that refusal with real native normalization, for the reviewed native adapters the child image ships.

## Context

- Filed on 2026-11-25 from the owner's decision on IMP-007F. The owner was asked "For AC-02, should OpenCode build a native parser or the planner rescope it?" and chose "Planner rescopes AC-02". IMP-007F's AC-02 now covers parser2 children only (proposed text, IMP-007F decision D12), and native discovery in the child moved here.
- r7 contracts: [r7-native-policy.md](../docs/specs/imp-007-r7/r7-native-policy.md) (the retained `id_policy` token is the selected profile's `identity_policy`), [protocol-appendix.md](../docs/specs/imp-007-r7/protocol-appendix.md) ("Child stdout ... native payload is closed NativeDiscovery"), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) (`WrapperProfile` binds the installation, image, wrapper distribution, entry point, projection and formats) and [fixture-appendix.md](../docs/specs/imp-007-r7/fixture-appendix.md) (native first use has two source revisions; native wrappers there are inert synthetic fixtures).
- Merged state on `main` at 301588b:
  - `discovery.admit_native(raw, payload, context_bytes, descriptor, profile)` validates a `NativeDiscovery` payload against a `NativeChildContext` and the frozen domain validator, and returns Minimal bytes. Nothing outside tests calls it.
  - `claim_set` SQL in `src/kurafolio/persistence/ingestion_schema.py` builds a `native_discovery_v1` context for any member whose selected wrapper profile has `projection: domain1-minimal-v1`.
  - No adapter produces a native payload. `kurafolio.source_builtin.registrations()` holds two parser2 adapters (Wealthsimple holdings, Bull Bitcoin orders) with neither `normalize_native` nor `installation_ids`, and `data_sources.compatibility_v1.builtin_descriptors` declares only `payload_kind: "parser_v2"`.
- After IMP-007F merges: `src/kurafolio/ingestion/runner_child.py` has no native branch, and `worker.py` refuses a native context before `LaunchStart`. Both are the places this ticket changes.
- Related tickets: IMP-007S (activation, which could refuse `domain1-minimal-v1` profiles until this lands; Decision 3) and IMP-007G (end-to-end acceptance, whose native first-use cases need this; Decision 4).

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [r7-native-policy.md](../docs/specs/imp-007-r7/r7-native-policy.md), [protocol-appendix.md](../docs/specs/imp-007-r7/protocol-appendix.md), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL and Docker tests need the explicit isolated environment; a skipped test is not acceptance. Use the claim's `isolation_id` and `port_base`.

### What to build

1. The child. `runner_child.py` also accepts a `native_discovery_v1` context, decoded as `NativeChildContext`, and runs a reviewed native adapter that the image registers for that installation. It writes a closed `NativeDiscovery` payload. Selection never follows a caller-named import path, and an unknown or ambiguous selection is refused with no output.
2. The worker. For a native member it launches the child like a parser2 member and admits the result with `discovery.admit_native`, then `admit_stage_v1`. The pre-launch refusal from AC-IMP-007F-10 stays for any native installation without a reviewed adapter in the image.
3. The reviewed native adapter or adapters the image ships, as Decision 1 settles.

Rules that reviewers will check:

- No schema property, table, role, route, SQL signature, transport or wire version changes, as `r7-native-policy.md` "Boundaries" says. `NativeDiscovery`, `NativeChildContext` and the operator profile input keep their exact shapes.
- The retained native `id_policy` is copied from the selected profile's `identity_policy`; child output, raw text or the retained string alone never establishes identity.
- The child runs under the same containment profile as a parser2 child, and the same evidence applies.
- No test-only or synthetic adapter is registered in the production image.

## Acceptance criteria

- [ ] AC-IMP-007Z-01: The child decodes `NativeChildContext` and runs only a reviewed native adapter the image registers for that installation; any other selection exits nonzero with nothing on stdout.
- [ ] AC-IMP-007Z-02: The worker admits a native child result through `admit_native` and `admit_stage_v1`; the retained `id_policy` equals the selected profile's `identity_policy`, and a mismatching token is rejected with `import_invalid`.
- [ ] AC-IMP-007Z-03: A native member goes from handoff to `stage_admitted` through the real worker, launcher and child on real PostgreSQL, with expected values derived independently of the implementation.
- [ ] AC-IMP-007Z-04: The native child passes the same containment checks as AC-IMP-007F-02 and AC-IMP-007F-06.
- [ ] AC-IMP-007Z-05: A native installation without a reviewed adapter in the image is still rejected before launch with `import_evidence_unsupported`.

## Plan

- [ ] Owner answers Decisions needed 1 to 4 and gives Gate A on the gated text.
- [ ] Planner writes the Build plan from the merged IMP-007F code.
- [ ] Builder implements, with unit, real-PostgreSQL and Docker tests per acceptance ID.
- [ ] Independent review, then the owner's review.

## Decisions needed

1. **Which native adapter does the image ship?** No source in the repository produces a `domain_v1` payload today. Options: (a) wait until a source ticket (for example a PLG ticket for a new institution) brings a reviewed native wrapper, and keep this ticket in backlog until then (recommended, because the owner ruled out a native stub); (b) build a reviewed native wrapper for an existing source in this ticket, which needs its own product and parser review; (c) ship a synthetic native adapter for tests only, in a test image and never in the production image.
2. **How does the child pick a native adapter for an installation?** The child sees the installation ID, profile digest and provider ID, not the descriptor. Options: (a) a fixed map in the image from installation ID to adapter, written when the image is built (recommended); (b) select by provider ID and format, with `admit_native` as the binding check, as the parser2 child selects by format; (c) add an attribute to `AdapterRegistration`, which changes a shared contract.
3. **Should IMP-007S's activation refuse `domain1-minimal-v1` profiles until this ticket is done?** Options: (a) yes, so an operator cannot activate an installation that the worker will only reject (recommended); (b) no, and rely on IMP-007F's pre-launch refusal and the documentation.
4. **Should IMP-007G depend on this ticket?** r7's native first use (two source revisions, `expected-native-first-use.json`) needs a native member to run end to end. Options: (a) add IMP-007Z to IMP-007G's `depends_on`, which needs the owner's confirmation in IMP-007G's Log; (b) IMP-007G records the native first-use cases as NOT RUN with this ticket as the reason (recommended while Decision 1 is (a)).

## Handoff

- State: Filed on 2026-11-25; backlog. Waiting for IMP-007F, the owner's answers to Decisions needed 1 to 4, Gate A and a Build plan.
- Next step: After IMP-007F merges and Decision 1 is answered, the planner reads the merged `runner_child.py`, `worker.py` and `discovery.admit_native` and writes the Build plan.
- Verify: `python3 scripts/tickets.py spec IMP-007Z`.
- Gotchas: In IMP-007S, IMP-007F's AC-09 and the r7 runner text, "native" often means native Linux containment controls, not native discovery. Do not confuse the two.
- Open questions: Decisions needed 1 to 4.

## Log

- 2026-11-25 claude-code/opus-5.5: filed from the owner's decision on IMP-007F: asked "For AC-02, should OpenCode build a native parser or the planner rescope it?", the owner chose "Planner rescopes AC-02". Native discovery in the child moved here from IMP-007F's AC-02 (IMP-007F decision D12). Gated text drafted; no Gate A yet. Plan PR #119.
