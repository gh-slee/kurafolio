# Discovery, raw deletion and retained evidence

B07-01/05 are owner-selected. [contract-appendix.md](contract-appendix.md) and [codec-schema.json](codec-schema.json) fix the new closed discovery/minimal/mapping/plan types. Existing parser2/domain1/source-transport1 semantics stay frozen; the new discovery wrapper does not impersonate source-transport1 financial authority.

The core captures an exact source/profile/format/context fingerprint, receives bounded raw and calls one reviewed isolated child. Parser2 output is strictly decoded against raw and saved parser context while raw is still available. Native domain1 output is validated in a fresh ephemeral namespace; actual required lifecycle values arrive through the new typed sidecar. Child UUIDs/references are discovery claims, never real user/portfolio authority.

Core assigns only member-local provisional references and projects to minimal-evidence-v1. All required account/instrument/issuer/coverage/snapshot/activity/time/quantity/cost/lifecycle/identifier data is retained as typed values. Native absent membership stays null. Legacy archive hashes are lineage only; no claim that deleted original bytes can be reconstructed. Arbitrary source_fields/rows/messages/filenames have no durable destination. Wrapper identity_policy is operator-reviewed, so a child cannot label a row hash a unique transaction.

After strict stage admission is durably acknowledged, release raw/discovery buffers and reap the exact child. Lost stage acknowledgement first recovers stage status by exact member/fence/digest. If raw is lost before provable admission, re-upload is required. Compatible account/instrument/parent/authority decisions can produce a new core-only immutable plan from retained minimal data; changing parser/format/alias/time semantics requires new raw/context.

New raw is never written to DB/WAL/files/artifacts/logs/backups or substituted by a reversible blob. Controlled memory/tmpfs has separate receive/normalization/resource/lifetime bounds. The privacy threat model is reviewed code and controlled storage, not secure RAM/swap erasure or defeating a hostile plugin's arbitrary covert channel. Existing legacy archives remain preserved.

Unaccepted minimal data expires after fixed 24 hours under the shared byte quotas. Cleanup removes live transient payloads, not accepted evidence; physical WAL/backup retention limits are explicitly disclosed in protocol-appendix.md. Accepted minimal input and exact approved plan bytes stay immutable for report/history/recovery. A restored old dump never reactivates unaccepted previews/jobs.


## R7 native policy provenance

For native discovery, Minimal.provenance.parser_api is null and provenance.id_policy
is copied exactly from the current, operator-reviewed WrapperProfile.identity_policy
selected and digest-bound for that member. It records the selected profile policy;
it does not claim that native DomainBatchV1 supplied source prose. Preserve parser2
provenance.id_policy from its existing evidence.id_policy unchanged. The closed
schemas and all function/route signatures remain unchanged.

The reviewed profile remains identity authority for both paths. Native child input
cannot supply or override this token through an extra field. New native stage
admission and new Plan preparation verify the retained token against the exact
selected profile under existing live source/profile pins. Profile changes invalidate
old unaccepted pins under existing rules; do not reinterpret immutable accepted
history or move mutable source checks ahead of proven receipt replay.

An ambiguous profile token does not establish stable economic identity. Keep all
existing ambiguity/unsupported/READY guards. See [the full repair](r7-native-policy.md).
