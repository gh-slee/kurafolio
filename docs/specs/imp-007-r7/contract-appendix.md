# F07-01: Literal codecs and admission semantics

Status: r5 contract candidate for independent review. B07-01 through B07-08 are owner-selected; implementation Gate A remains null. codec-schema.json fixes all new object fields, required nulls, unions and collection bounds. Every object is closed. frozen-shapes.json is a source-annotation index, not a replacement for frozen runtime validators. Final implementation must pass the existing validators where reused and all additional semantics below.

## Wire encoding and validation order

Use canonical UTF-8 JSON: sort object keys, no whitespace separators, ensure_ascii=false, no trailing newline. Arrays retain source order unless a contract explicitly defines sorted unique keys. Every financial value and counter is a string; only declared versions, ordinals and fractional-digit fields use JSON integers, with bool rejected as integer. No floats/exponents, duplicate keys, non-UTF8, nonfinite numbers or unknown fields. Input is byte-bounded before decoding, depth32; maximum minimal bytes4,194,304 and plan bytes16,777,216. A wrapper header is limited separately to4,096 bytes and never widens payload limits.

Order: byte/frame bounds and complete exit -> binding/hash checks -> canonical UTF8/JSON -> closed shape -> exact scalar/date/decimal semantics -> local graph -> scoped mapping/reference/parent/coverage semantics -> current authority/generation -> exact preview. Return the first failing boundary category, with fixed schema paths only. Unknown essential content is blocked, never quietly dropped. Unknown nonessential source_fields are discarded in the explicit projection and are never persisted first.

UUIDs are lowercase canonical nonzero. Counters are canonical nonnegative int8 decimal strings, maximum9223372036854775807; overflow rejects before effects. Decimals use the existing decimal-38s-24f-38i-v1 lexical rule: no exponent/leading plus/leading zero; <=256 characters, <=38 significant coefficient digits after leading/trailing zero removal, <=24 meaningful fractional digits and <=38 integer digits. Original typed token, sign and trailing zeros are retained. BTC/LBTC quantities must be whole satoshis; no rounding sub-sat values. Money currency is uppercase3 ASCII. Unknown money/fee fields remain null, never zero/empty by substitution.

Instant tokens must name real calendar dates, offset<=23:59 as accepted by the frozen codec, and at most6 fractional digits exactly matching fractional_digits; preserve token, offset and optional zone label. Do not use a zone label to alter an already explicit offset. Date-only stays date-only. Legacy-unspecified carries actual token and optional archive lineage, never an invented UTC instant. Interval endpoints/inclusivity and scope membership are preserved. Incomparable ordering blocks a head change; explicit historical-only evidence is separate.

## Minimal representation

Minimal has provenance/accounts/assets/issuers/membership/coverage/snapshots/records. All arrays and nullable members are present. Local IDs are exact contiguous zero-based decimal ordinals within each collection; uniqueness and referenced kind are checked. Records share one ordinal namespace across position/activity. Coverage, snapshots and issuers have their own namespaces. A member may have <=64 accounts and <=2,048 assets/issuers, and records+coverage+snapshots+non-null membership <=10,000. Root issuer list and full typed asset identifiers/issuer/settlement/source_descriptor preserve native-domain evidence; parser2's single optional identifier is also preserved. Missing native membership remains null, not a complete or fabricated unknown declaration.

Role/account/asset consistency is mandatory. CASH symbol/currency agrees and has no MIC/network; SECURITY mapping keeps currency and MIC; CRYPTO keeps network/symbol/settlement identity. UNSUPPORTED remains explicit. Distinct identifier sets are not silently merged by ticker. Unreferenced declared issuer metadata is retained, not dropped merely because the first projection does not use it.

Position identity, observation ID, snapshot header time/revision, account and coverage must agree. Native nullable market_value remains nullable; parser2's required market value stays present. Signed quantities are preserved with explicit unsupported classification where required. An omitted complete-snapshot item is absence evidence in snapshot membership, not a fabricated stored zero position.

Activity source_kind distinguishes cash_flows/crypto_transactions/activity. kind/status/roles/fees/cash_flow/lifecycle are retained. Only original has null parent/revision_reason; correction/void requires an exact explicit parent and reason. Void is not an original cancelled event. Source parent claims never become authority merely because a child supplied them. All economic references are same-scope resolved claims; a child cannot name an accepted tenant/portfolio. Cash leg links are explicit, and purchase cash legs are internal rather than inferred external contributions.

Generic parser2 BUY role projection is allowed only for supported unambiguous purchase shape: one positive crypto delivery ACQUISITION and negative funding/payment legs PAYMENT; lifecycle asset amounts must agree with that shape. Transfer/fee/sale/swap shapes require explicit roles from the reviewed wrapper/core shape rules or an unsupported result. No provider branch in commit or projection. Native supplied roles remain subject to shape validation. Amounts/fees are not recomputed: included_in_leg/included_in_cost are explicit flags, and unknown fees differ from known empty fees.

## Actual lifecycle retention

Preserve all source_v2.Lifecycle fields: created_at, completed_at, sent_at; source_type/subtype/status; payin_status/payout_status; payin/payout asset, exact quantity and method; exchange/index rate amount and unit. Completed lifecycle event time agrees with completed_at under the existing parser rule. Source statuses/methods/units are bounded typed text, not guessed enums. A native domain1 LegacyRecordRef alone is insufficient. A reviewed domain discovery wrapper must provide actual values in the additive lifecycle_by_activity sidecar for every such referenced lifecycle, exactly one per corresponding activity ordinal. Missing or conflicting sidecar blocks admission. Additive values with a null native lifecycle may be retained as explicitly wrapper-provided evidence; do not forge a legacy reference or claim the old domain bytes had those fields.

Native domain1 IDs are ephemeral discovery IDs in a fresh core-supplied namespace, never real-user authority. Core validates the native batch/reference consistency in that namespace and converts to local ordinals; accepted mappings are separate. Archive references retain their original digest/field meaning as unavailable lineage. No new call to recover_legacy_v1 is promised after deletion. Domain1 source/provenance timestamps, identifiers and issuers must survive the conversion as typed evidence, even when the current read model does not consume them.

## Diagnostics and source metadata

Closed diagnostics are market_math/unrealized_math/nonpositive_cost_quantity, wallet_balance_unverified/wallet_fees_unknown and observed_order_rows. Preserve severity; map source account/symbol context to exact local record references, not arbitrary parameter strings. observed_order_rows retains nonnegative row/duplicate counts; the other codes use null counts. Unknown diagnostics block as unsupported evidence until an operator-reviewed codec/profile extension; do not invent a generic replacement that conceals a financial warning. Essential field names, legacy semantic hash and exact source ID policy are typed metadata; original filenames, free-form messages, addresses/transaction IDs in source_fields and full row bags have no destination here.

Essential source type/status/method/ID strings max128 except source IDs/observations/references256 and source aliases/labels160; exact source basis/ID-policy/revision-reason/source_descriptor text may reach4096 under the frozen metadata limit. This clarifies essential text versus the approved finite-code128 budget; it does not expand raw/payload/text caps in frozen contracts. Records violating the reviewed new profile fail explicitly.

## Mappings and plans

Decisions request contains operation_id, expected_set_revision and <=128 entries in each declared array. Values are only local references, existing opaque IDs/versions, proposed IDs and explicit evidence; financial numbers cannot be edited by this endpoint. Source and entity versions must match actual scoped DB rows. Proposed entities derive immutable body/version from the admitted source metadata; user labels may be a separate reviewed entity proposal, never financial facts. Existing accepted mappings are append-only. Changing a mapping or authority choice makes a fresh preview; the old exact plan cannot be silently altered.

Parent decisions link retained source revisions after normalization without changing source-reported change/parent fields. The plan records an explicit host-correction overlay separately; no parser rerun or relabelled original source revision. A source-supplied correction without valid same-chain parent remains blocked. Duplicate/minor metadata changes preserve source observations without an extra acquisition.

Plan fields are fixed by codec-schema.json: actual server-derived scope/realm fingerprint, set/preview/decision revisions, each pinned source installation/generation/context/profile, exact input digests, entity/mapping/authority/parent decisions, fact actions and head CAS targets. No callback/SQL or arbitrary accepted bytes from browser. New accepted UUIDs are reserved in the immutable preview before user confirmation. Duplicate references target existing revisions; every action is checked against stored stage and current accepted chains. Version hashes cover exact canonical entity bodies. Plan digest is SHA256 of the canonical plan bytes including new IDs, but not its own digest. Minimal digest similarly excludes no fields; raw/discovery hashes are hashes of distinct input bytes and do not refer to the minimal object's own digest.

WrapperProfile.profile_digest is SHA256 of its canonical object with profile_digest omitted. It binds the frozen installation_id, exact image, reviewed wrapper source/distribution/entry point/projection and format list. The operator installs this companion allowlist explicitly; Descriptor v1 is unchanged. No browser target, automatic pull, arbitrary Python import in the core or silent install upgrade is allowed. Unknown wrapper/profile/version is unavailable, even if a frozen plugin descriptor alone is valid.

## Source versus canonical instrument metadata

A parser2 CASH asset has source symbol equal to its currency; a native domain CASH instrument has symbol=null. Minimal evidence preserves the supplied distinction. A canonical CASH target always uses currency and null ticker/MIC/symbol/network/settlement identity as the frozen domain requires. Parser2 CRYPTO carries symbol/network but no settlement_identity: the proposed canonical target uses the existing reviewed network identity convention (settlement_identity=network), shown in the mapping preview. Native explicit settlement identity is retained and must match its chosen target. No provider-specific branch is needed. Existing target labels/source_descriptor may differ from a new source description; validate identifying fields, preserve source metadata in evidence and never overwrite an existing immutable entity body. A proposed shared target must have one exact body/version across members, otherwise conflict. Parser2 source_descriptor is the canonical AssetKey JSON, not an invented company name.

The ChildContext schemas in wire-contracts.json are exhaustive. Parser2 discovery uses a fresh opaque evidence reference and empty revisions/scope_revisions; parent decisions are handled by the explicit core overlay. Native discovery receives only an ephemeral scope/connection namespace, not real user IDs. No unrecognized context field reaches a child.

## Identity-policy authority

WrapperProfile.identity_policy is operator-reviewed and digest-bound: provider_scoped_stable, snapshot_semantic or ambiguous. A child-controlled id_policy text field is retained evidence, never authority to call a hash a unique transaction. provider_scoped_stable requires a reviewed stable provider/source-account ID derivation; source order hash may preserve that identity but row amount/time/hash alone cannot. snapshot_semantic supports declared observation/scope revisions, not automatic activity identity. ambiguous activity cannot reach READY without an actually supported stable identity path; no manual financial-ID fabrication is added here. Equal missing-ID twins remain blocked. Installation/version/profile changes invalidate old plans. This enforces the already selected no-heuristic identity policy without provider branches.


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
