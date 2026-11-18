# Explicit identities and deterministic reconciliation

Status: r5 detailed contract candidate under owner-selected B07-07. Accepted facts are distinct from 008 projections.

## Identity keys

SourceKey and SourceRevisionKey in codec-schema.json are the exhaustive versioned preimages. They include tenant/portfolio, connection, collection, provider, nullable source account, source kind, nullable coverage record_kind, source ID and observation ID; revision is an outer field only in SourceRevisionKey. See r5-repairs.md and fixtures/key-preimages.json. No abbreviated tuple overrides these forms. Connection aliases map to real account IDs only through the approved mapping plan. Observation IDs distinguish holdings occurrences. Amount, timestamp, filename and row/file hash alone are not economic identity.

Account mapping key=(S,connection_id,provider,source_account_key,mapping_revision). Instrument mapping key=(S,connection_id,full source asset descriptor,mapping_revision); security identity includes currency/MIC/identifier, crypto includes symbol/network/settlement identity. User labels never merge identities. Accepted facts pin entity/mapping versions; later changes do not rewrite history.

An economic group consists of one authoritative accepted source chain plus explicit mirror-evidence links. Both sides must be in the same S and refer to exact admitted/accepted revision keys. Neither a child nor equal fields can assert equivalence. A mirror preserves source evidence but adds no second authoritative acquisition. Choosing independent means two groups remain. Every choice appears in the preview digest, provenance and audit. No API provider is executed to manufacture evidence.

## Source revision and activity table

| Incoming evidence | Outcome |
|---|---|
| Existing exact source revision and same typed financial digest | Duplicate lineage only; no new accepted revision/head or accepted generation |
| Same revision key, changed typed facts | CONFLICT, zero effect |
| New source revision with equal typed financial meaning | Retain new source observation/lineage as duplicate evidence, not new economics; no head or accepted generation change |
| New original stable source ID with no ambiguity/authority conflict | Append accepted source/economic revision; advance its head |
| Same time/amount, two distinct stable source IDs | Two independent trades within the same known stream; both persist |
| Missing stable ID or indistinguishable generated-ID twins | Block as identity_ambiguous; no silent merge/drop/acceptance |
| Known ID changed with no valid parent | CONFLICT; require explicit correction plan to exact current parent |
| Correction points to current same-scope chain head | Append correction, preserve old revision, move head atomically |
| Parent missing/foreign/fork/cycle/not current | Block; never silently pick a branch |
| Void of current head | Append void with exact parent, mark chain inactive; retain source facts/history |
| Pending/cancelled/unsupported original | Preserve diagnostic facts/status, never eligible completed BUY |
| Pending to completed | Needs explicit same-chain parent/status revision; no new order ID inferred |
| Completed later cancelled without explicit void/correction | Conflict, not silent removal |
| Funding/transfer/balance/fees | Persist typed diagnostics and links; not additional acquisitions/contributions |
| Two connections mapped to one real account, overlapping kinds/scopes | Require authority choice: exact mirror link, independent stream confirmation, or block |

Eligibility classification for later 008: only an active authoritative supported completed BUY with positive whole-sat acquisition legs is eligible. 007 stores the reasons/roles/status, not a computed pool. SELL/disposal/transfer/fee/balance/funding never automatically subtract or add to approved Option A. Actual event effects beyond Option A require their own future decision. A cash_leg_of/reference remains same-scope and does not double count cash and purchase spending. Unknown fee/cost remains null.

## Snapshot and coverage table

Coverage domain key D=(S,canonical_account_id,fact_kind,scope_selector), independent of display labels and connection label. Scope selector is all, exact category or sorted explicit instrument set. Competing source authority for D must be resolved; two different connections cannot silently install two complete authoritative heads.

Store immutable accepted coverage observations and snapshot membership. Maintain latest observation head for exactly D and exact item heads only where observation explicitly includes the item. Keep latest complete base marker separately from later partial marker. A newer partial does not authorize carrying omitted old items as verified current. 008 must consume these uncertainty markers, never sum snapshots plus activities.

| Observation | Persisted result |
|---|---|
| Newer complete same D | Historical old observation retained; replace complete/base and latest head for D; full member set, even empty, defines omissions |
| Newer partial same D | Store partial/latest marker and explicit item heads; preserve prior complete base for last-seen evidence only; omissions unresolved |
| Unknown completeness | Store observation/latest marker with unknown status; no closed-world zero |
| Older comparable observation | Append historical evidence/revision; current heads unchanged |
| Equal instant, equal financial content/scope | Duplicate observation lineage; no second head |
| Equal instant, different content without parent | CONFLICT |
| Equal instant explicit correction to current head | Append revision and replace that head |
| all/category/explicit disjoint scopes | May coexist; do not erase unrelated domains |
| Overlapping nonidentical scope, incompatible authority/content | CONFLICT until explicit authority/coverage choice; no broad replacement or double sum |
| Complete empty | Valid only with explicit account/coverage/snapshot membership and complete declaration; replace same D with empty member set |
| Partial empty | Store partial marker, no zero positions or full empty balance |
| Missing coverage or declared members outside scope | Block before READY |

Both timezone-aware instants compare by UTC while retaining original tokens/offset/fractional precision. Equal UTC instants with different offsets are equal. Date-only values compare only to the same precision/date under an explicit applicable source zone; no date-only-vs-instant ordering is guessed. Legacy-unspecified time ordering is unresolved unless source context establishes a reviewed comparable relation. Unsupported ordering that could change a current head blocks; historical-only acceptance may be selected explicitly if no current authority is claimed. Counterexample fixtures must cover exact boundaries.

No synthetic zero fact is inserted for an omitted complete-snapshot instrument. The complete empty/member set is the evidence of absence. G01's later A7/B0 is an008 interpretation;007 stores T2 membership={A} and retains T1={A,B}. G02's omission leaves B last-seen5 but unresolved current. Authority/coverage choices change mappings/control generation and invalidate old previews, even if no immediate accepted position changes.

Financial meaning/digest excludes raw/ingestion/local/ephemeral metadata and is pinned by the explicit projection in fixture-appendix.md. Exact correction/void lineage takes precedence over duplicate-only semantic classification.

