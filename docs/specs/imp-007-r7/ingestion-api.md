# Import API, shared budgets and state machine

Status: r5 contract candidate for optional profile `ingestion`, after `sources`. Existing identity/sources/default SQLite routes and their 16 KiB JSON budget remain unchanged. No frontend in this slice.

## Closed proposed routes

All private routes require a live session, actual initialized realm, matching configured Host and existing same-origin/CSRF rules. All responses are no-store/private; decimal/counter values are strings. Foreign/missing resources share the existing nondisclosing not-found policy. No original filename is required or echoed.

| Method/path | Request | Result |
|---|---|---|
| POST /api/v2/import-sets | JSON operation_id and 1..4 members, each connection_id, exact installation_id, format_version, optional declared byte count; no tenant | New set and server member UUIDs; replay same payload reuses IDs |
| PUT /api/v2/import-sets/{set}/members/{member}/raw | application/octet-stream, exactly one Content-Length, no Content-Encoding/Transfer-Encoding; body is one CSV | 202 only after bounded reception and launch handoff; status polling establishes normalization/admission |
| GET /api/v2/import-sets | Signed scope/realm-bound cursor, limit1..50, status filter | Content-free set summaries, no raw or broad financial cache |
| GET /api/v2/import-sets/{set} | No body | States, member progress, expiry, fixed errors and preview/receipt IDs |
| PUT /api/v2/import-sets/{set}/decisions | JSON operation_id, expected_set_revision plus bounded account/asset mapping, entity proposals, source-authority/evidence decisions | 202/RECONCILING; worker later stores NEEDS_MAPPING/CONFLICT/READY and preview ID |
| GET /api/v2/import-previews/{preview} | No body | Immutable paged typed plan summaries, required decisions, digest, expiry; max50 rows/page |
| POST /api/v2/import-previews/{preview}/confirm | JSON operation_id, preview_digest | COMMITTED receipt or exact typed error; no financial JSON accepted from browser |
| POST /api/v2/import-sets/{set}/cancel | JSON operation_id and expected_set_revision | Cancelled before commit or already-committed receipt; race rule below |
| GET /api/v2/import-receipts/{receipt} | No body | Authenticated immutable historical receipt, including source realm marker |

No route starts an API provider or installs a plugin. Existing enabled connection is mandatory; multi-account files may map TFSA/RRSP separately. New accounts/instruments/aliases are only proposals until atomic acceptance. Account labels are user data, not identity. Format/alias/parser changes require a new set and raw upload.

## Proposed finite budgets (B07-06/08 owner-selected; implementation Gate A still required)

| Surface | Bound |
|---|---|
| JSON control body / request deadline | 16,384 bytes /10s, preserve existing routes |
| New raw reception | 1..10,485,760 bytes/member;30s total/5s idle; no multipart or content decoding |
| Raw member upload/normalizing concurrent | user 1 / instance 4, shared PG leases, not per-process counters |
| Files/normalized bytes/set | 4 /16,777,216, per member4,194,304 |
| Discovery input/output | raw10 MiB + context<=1 MiB, independently bounded; binary length frames, total<=11 MiB+fixed header; discovery output<=4 MiB |
| New mapping/control decision references | <=128 entries/request; multiple immutable updates allowed; server-derived plans never supplied as financial JSON |
| Fact rows/account/asset membership | <=10,000 combined facts+scopes/member, <=64 source accounts/member, <=2,048 assets/member; total set<=40,000 facts |
| Depth/text/decimal | depth32; essential labels<=160 characters; source IDs<=256; other finite code text<=128; decimal token<=256, frozen precision38-significant/24-fractional and whole sats where required |
| Unaccepted set lifetime | 24h from DB-created_at, no extension; equality expires |
| Outstanding sets | user8 /instance64; reserve worst-case bytes before upload; user 128 MiB /instance1 GiB minimal payload reservation |
| Control admission rate | create/decisions/confirm/cancel user30 and instance300 per300s; reads user60/instance600 per300s; raw attempts user 10/instance60 per300s |
| Raw lifetime | At most120s from first received byte, no queued durable raw; expiry requires re-upload unless stage admission already proved |
| Normalization lease / renew | 60s lease, heartbeat<=10s; authoritative DB clock; expired attempt cannot publish |
| Confirm transaction | total20s, at most 3 whole-transaction attempts for40001/40P01; lock<=2s/statement<=5s bounded by remaining budget |
| Result history pagination | limit1..50; cursors bind actor/portfolio/realm/filter/position; restore invalidates cursors |

These numbers are proposals, not measured capacity claims. Raw admission reserves the maximum size if declared count is not trusted, and shared quotas are released exactly once by attempt/fence. Invalid body attempts consume rate budget but not accepted generation. Expired storage is reclaimed only after physical deletion is verified; a cleanup failure cannot free a still-used storage reservation. Persistent cleanup failure disables new admissions rather than overcommitting resources.

## HTTP and error ordering

1. Validate known route/method/Host and duplicate authority/framing headers without consuming body. Enforce identity/origin/CSRF and content-type before reserving raw resources or starting a parser.
2. Require exactly one canonical ASCII positive Content-Length<=raw cap; reject absent length411, duplicates/CL+TE400, unsupported encoding415, oversized413. Reject Expect unless explicitly supported; no forwarded header can supply identity.
3. Authenticate DB scope/source state, acquire shared rate/capacity slot and unique member receive fence. Only then pull ASGI chunks into bounded memory/tmpfs. Count every byte. Extra/short body, disconnect, idle/total expiry, reused slot or cancellation yields no candidate/accepted effect. No generic FastAPI multipart path is used.
4. Launch only after exact body length/hash is established. Once bytes are handed to the owned attempt, a dropped HTTP response does not prove cancellation; poll set status. Before handing off, disconnect discards raw and marks member REUPLOAD_REQUIRED.
5. Decode child output only after stream/exit/limit validation. For a discovery envelope, check outer byte/header limits, version/job/fence/image/raw/context identity, encoding/hash, then schema/semantics. Do not claim frozen source-transport1 error codes apply to this new protocol.
6. Code-only errors: import_invalid, import_limit, import_busy, import_expired, import_reupload_required, import_mapping_required, import_conflict, import_stale, import_operation_conflict, import_commit_uncertain, import_runner_unavailable. Reuse existing auth/source codes where exact; never expose raw, path, DSN, arbitrary stderr or parser exception text. Exact status/code map must be fixed in a final DTO appendix before Gate A.

## Transitions and linearization

| From | Actor and condition | To / effect |
|---|---|---|
| New | Authenticated create, quota/connection checks | RECEIVING; no accepted entity/fact |
| RECEIVING | All members complete and their owned launch handoffs valid | NORMALIZING; no accepted facts |
| Member waiting/receiving | Disconnect/crash before proven stage | REUPLOAD_REQUIRED; new attempt only before expiry, new fence |
| NORMALIZING | All minimal stages admitted, raw deleted/reaped | NEEDS_MAPPING, CONFLICT or READY based on core evaluation |
| NEEDS_MAPPING/CONFLICT/READY | Owner decisions at expected revision | RECONCILING and a new immutable decisions revision; worker prepares a fresh preview |
| READY | Live valid exact confirmation obtains scoped locks | Transaction-local CONFIRMING; no separately durable CONFIRMING state |
| CONFIRMING | Fact/entity/head/receipt/audit/generation/outbox COMMIT | COMMITTED (may be committed_no_change) |
| Any uncommitted state | Owner cancel wins scoped set lock | CANCELLED, fence++, children scheduled for owned cleanup |
| Any uncommitted state | DB clock>=expires_at under lock | EXPIRED, fence++, no accepted effect |
| Any uncommitted state | Unrecoverable schema/normalization failure | REJECTED, fixed error; no hidden subset accepted |
| COMMITTED | Cancel/new normalization/late result | Unchanged; read original receipt, no reversal |
| Terminal | Stale worker/result/retry | No revival; permit only cleanup/history |

Member states and set state are distinct: one slow member cannot make a partial set READY. Cancel/expiry and confirm lock the same set/root; transaction commit is the single financial linearization point. If cancel wins, confirm fails; if acceptance commits first, cancellation returns already committed with its receipt. Cleanup progress is separate from financial status. No durable row may claim COMMITTED before financial COMMIT.

The public API hands received raw to the dedicated trusted ingestion worker over an authenticated internal nonpublished channel using a one-use member/attempt-bound handoff minted by reserve_member_v1. The worker alone holds its restricted DB role and launcher peer credential. API holds neither worker DB credentials nor launcher credentials. No durable raw queue exists. Handoff loss before proven admission yields REUPLOAD_REQUIRED. The exact reserve/bind/claim and peer/realm rollover contract is in protocol-appendix.md and sql-appendix.md.

wire-contracts.json is the closed route/DTO/error inventory. protocol-appendix.md supplies exact handoff/cursor/framing and r4 state precedence; it supersedes summary shorthand. All requests remain authenticated and no financial effect is permitted by raw admission or preview preparation.

