# F07-04: Complete synthetic vectors and independent test contract

fixtures/ contains complete literal raw CSV/parser2/native-domain/discovery/minimal/mapping/plan vectors and expected first-use table effects. Snapshot families have their own raw CSVs and full native/minimal representations for complete, partial and empty scopes. Public builtin examples are pinned by hash in builtin-inputs.json, with independently counted row/quantity/native-amount expectations. No private financial file or owner configuration is used.

These vectors are coordinator-authored specification material, not independently accepted QA results. Their image/artifact hashes are invented planning bindings; no built/installed/verified production image is claimed. Independently approve fixture semantics and then execute against implementation. Static JSON/schema/hash/arithmetic checks are not a parser, transaction, containment or restore PASS.

## First use and counts

trade.csv declares one BUY 0.01000000 BTC for CAD700.00. parser2.json includes explicit source account membership and a full lifecycle plus nonessential source_fields canaries. minimal-parser2.json preserves every essential typed field, with those canaries absent. native-domain1.json uses ephemeral discovery IDs and a separate native-discovery lifecycle sidecar; minimal-native.json retains the native field distinctions. Account/instrument target UUIDs and body versions are separate from discovery IDs. decisions-first-use.json and plan-first-use.json freeze exact proposed targets, source/realm/generation/input digests and head effects. No user-supplied balance/opening is needed.

expected-first-use.json fixes the parser2 first ACCEPT result: two foundation accounts, two instruments, four mappings, one accepted input/plan, three source revisions (one BUY, one coverage, one membership), one activity head and three lineage rows. accepted_generation and mapping_generation advance0->1; one ACCEPT receipt/audit/outbox. Snapshot head count0. Null fees, exact lifecycle and unknown contribution/wallet truth remain. Duplicate-only new operations have no financial generation/effect; exact same-operation replay creates no rows at all.

The Decisions control step changes root control_generation0->1 and set revision1->2. Preparation stores READY revision3 without changing financial generations. ACCEPT stores COMMITTED revision4. Create/upload/stage/prepare alone change no accepted/mapping generation. A new decision or winning cancellation invalidates old previews through set revision and control generation; duplicate retries have no increments. Expiry terminalizes/fences its set without changing accepted/mapping generation. Every effect is asserted against the correct control or financial phase, not conflated into one aggregate count.

## Stable semantic digests

financial-projections.json fixes the byte-hashed financial meaning for the first-use record/coverage/membership. It removes local ordinals/archive refs/source revision/parent metadata, maps every account/asset local reference to its pinned canonical ID+version, and retains exact typed quantities/time/status/cost/fees/lifecycle/scope. Record identity retains source_id+observation_id; provenance/raw/job/import-time metadata is outside this financial projection. Full source selector and source revision stay separately preserved and checked. The same source observation with reordered local entities must have the same financial digest after the same canonical mapping.

This projection is normative: recursively replace account_local_id/source_account_local_id with the corresponding canonical reference, asset_local_id with instrument reference, plural account/asset lists with canonical reference arrays; drop only local_id/legacy/revision/parent at their declared schema locations; record identity keeps source_id+observation_id. All other declared financial/coverage/membership fields remain. New codec fields require a reviewed digest-version change, not silent exclusion. Existing exact key content is always compared in addition to key hashes.

Explicit source or host correction/void semantics take precedence over semantic no-op classification: a valid new parent-linked correction remains a new accepted revision even if amounts are equal. Merely changed report metadata with equal meaning and no lineage correction is duplicate evidence only. Accepted lineage never modifies the source-reported original/change fields.

## Matrix and independent execution

case-matrix.json maps all 36 acceptance groups to complete base fixtures, exact actions and literal positive/negative expectations. The22 named r3 elementary oracles remain in oracle.json as additional crosschecks. Each branch resets its synthetic state; do not sum branch effects or compare future008 pool values with007 computed balances. Full source/native validation, mTLS peers, actual PG rows/constraints/roles, concurrent processes, kernel resource denials and initialized restore still need execution in the implementation stage.

Materialize variants only by explicit source-ID/time/quantity/status/coverage overrides from the matrix, applying valid-source changes consistently to raw+expected typed data and recomputing hashes via canonical serialization. A tamper case intentionally changes only one boundary. Fixture helpers may serialize these fixed values; they cannot call production reconciliation/projection to calculate expected heads, receipt counts or eligibility. Native/snapshot wrappers are inert synthetic fixtures, not new real brokers or API connectors.

Mandatory evidence records environment/architecture/engine/PG versions, source/base/HEAD and fixture/oracle hashes, actual commands/counts/skips/errors, effective grants/constraints/RLS, deterministic race barriers, exact owned cleanup and two empty-target restore manifests. Missing/unsupported environments are NOT_RUN, never substituted by mocks or a real personal instance. Required checks must actually run before Gate B; the baseline optional-skipped suite does not certify007.

Native first use is a separate reset with its own decisions/plan/projections/expected files. expected-native-first-use.json fixes two source revisions/lineage rows (BUY+coverage), since native membership is null; the parser2 case has three. Both preserve lifecycle sidecar values without pretending that native domain1 declared a membership scope.


## R7 provenance-only fixture repair

Eight native Minimal fixtures now retain their exact reviewed profile token in
provenance.id_policy. Their stage digests and dependent Plan/review/receipt/event
bindings change. Parser2 inputs, raw CSVs, native discovery/domain payloads, caller
contexts, profiles, source keys, financial projections and row/generation oracles
retain their original values. The delta is recorded in r7-repair-impact.json.
This is static fixture consistency, not native projection or transaction execution.
