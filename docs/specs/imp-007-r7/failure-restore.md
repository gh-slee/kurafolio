# Exact confirmation, failure and restore behavior

Status: proposed contract. Functions/code below are algorithm descriptions, not executable implementation or invented CLI commands.

## Three different operations

Historical GET receipt: authenticate current session and actual current realm, derive owner portfolio, then read same-scope historical receipt by opaque ID. Historical origin realm is shown as evidence only. A source disabled/retired after acceptance does not erase prior receipt or facts. Foreign/missing is nondisclosing. No old receipt is a new capability.

Same-operation POST retry: authenticate current session/credential/actual realm and derive scope first. Verify closed request and request_digest; operation namespace is(scope,actual incarnation,restore_epoch,operation UUID), shared across ingestion operation kinds. Look up an existing matching receipt before preview-expiry/source/mapping/generation checks. Same kind+digest returns immutable original result even after source disable/parser upgrade/mapping change/preview expiry. Changed kind/digest conflicts. No receipt means this is a new effect, not successful recovery. A stale/disabled/logged-out session must reauthenticate to read history or retry; replay never bypasses live auth.

New confirmation: current session/realm guard; find no existing operation receipt; lock deterministic resources; reauthenticate after lock wait; verify preview/set READY/unexpired and all pinned authority/installation/connection/mapping/control/accepted generations; validate every immutable input/plan/entity/reference/parent/coverage/economic choice; then execute all writes and COMMIT. Do not rerun parser/reconciliation under old approval. Stale state returns re-preview required with no financial effect.

After restore, old realm operations cannot execute POST replay as current authority. Fresh authenticated GET may read restored receipts. New effects need new operation/set/preview in the new realm. Deleted raw never reappears; lost pre-admission raw requires re-upload. Changing identity of an old request to the new realm is not a legitimate replay.

## Locking and bounded transactions

Global order: instance readiness/realm shared; identity auth state/session/user guards; source catalog/availability+enablement/connection rows sorted by installation/connection ID; ingestion scope root; set; preview; canonical entity/mapping/source/economic/head keys sorted by canonical key. All operations that touch these resources, including source disable/logout and cancel, must use a compatible reviewed order. Use the exact source-compatible order in sql-appendix.md; real PG deadlock/fault tests must verify it.

Use DB clock after final locks; finite monotonic auth-clock checks preserve existing contract. No DB transaction while receiving raw, launching/reading child, fetching quote or rendering. Transaction-local CONFIRMING has no durable committed row before actual COMMIT. At most3 whole attempts for serialization/deadlock, fresh authority validation each time and 20s total deadline. Lost COMMIT acknowledgement is import_commit_uncertain, then receipt recovery. Never infer rollback from a broken connection.

Cancel and confirm serialize on the same root/set. Cancel winning first makes a terminal cancelled set/fence and confirm cannot write. Acceptance winning first makes receipt authoritative; cancel returns already committed and does not reverse facts. Expiry equality is expired. A stale lease/fence or late child result cannot revive any terminal set. Cleanup status is independent; cleanup_pending does not imply financial rollback.

## Fixed fault table

| Injection boundary | Required result |
|---|---|
| Before raw completes | No stage/accepted effect; release bytes, REUPLOAD_REQUIRED or terminal rejected as code |
| After raw but before child create/start | Exact owned cleanup; no accepted effect; retry needs raw if lost |
| After create before ownership journal | Reconcile only exact launcher-instance nonce labels; never adopt unrelated child |
| After result before stage admission | No durable discovery/raw; crash requires re-upload |
| Stage COMMIT succeeds, response lost | Recover stage by exact member/fence/digest before dropping/retrying; never parse twice merely for uncertain acknowledgement |
| After proven stage and raw deletion | Minimal typed preview survives only its fixed TTL; remap without parser; after TTL require new set/upload |
| After fact/entity/head/generation/receipt/audit/outbox statements but before COMMIT | Full rollback; every table/counter/head equals pretransaction fixture |
| After accepted COMMIT before HTTP acknowledgement | One ACCEPT receipt and effect; exact retry returns it with zero new rows/counters |
| Outbox consumer/rendering failure | Acceptance stays committed; no second acceptance; later consumer handles its own retry |
| Stream overflow/OOM/wall/cancel | Fixed code; bounded exact child/cgroup cleanup, no decoder of over-limit result |
| Cleanup/journal/disk capacity failure | No false clean/readiness, retain reservation/opaque evidence, fail new admission safely |
| Runtime/DB/network unavailable | No fallback in-process plugin execution, no SQLite switch, no false successful receipt |

## Explicit operator migration

Only a verified initialized 0003 source profile with predecessor inventories/hashes and required maintenance lock may upgrade to the proposed 0004. Inspect exact function bodies, owners, grants, RLS/columns/constraints, actual server/DB identity and initialized closed setup marker before DDL. Empty/no profile, mixed/newer schema or altered predecessor fails with no stamp/repair. No startup migration, in-place downgrade or private backend switch. New schema/data/roles/readiness installation is atomic; injected failure rolls back and leaves pre-upgrade profile authoritative. Exact dependency inventory and SQL signatures are specified in sql-inventory.json/sql-appendix.md and require independent review before Gate A.

Rollback before accepted writes: disable ingestion routes/worker/launcher through explicit configuration; preserve DB. After any0004 writes, an older0003 app must refuse the newer schema, not reinterpret it; keep compatible0004 reader or restore an explicitly approved matching backup into a verified empty target with disclosed lost later writes. Never delete accepted tables to manufacture downgrade success.

## Acceptance-specific backup and restore

A synthetic initialized dump plus immutable manifest pins schema/provider versions, all minimal accepted input/plan bytes/digests, scoped entity/mapping versions, revision parents, exact head targets/membership, receipts/request+plan digests, generations, audit/outbox bodies and instance initialization marker. This covers007 accepted facts, not full application artifacts/keys/quote caches or post-backup changes;015 remains full operations work. Unaccepted stages/jobs in a dump cannot become live after restore.

1. Verify target truly empty, no application traffic, exact supported dump+manifest version, required operator/role trust and initialized source. No restore into an existing or uninitialized instance.
2. Restore with ready=false and no app grants. Verify exact bytes, FK/parent/head/receipt/plan relations, counters and effective schema/function/role inventories against matching manifest, not just row counts or an auto-generated live hash oracle.
3. Generate fresh incarnation/restore epoch per existing identity semantics; invalidate old sessions/forms/cursors/leases/raw handles, revoke unused invitations as005 requires, cancel old unaccepted jobs/sets and purge unaccepted stage payload. Preserve used/revoked invitation and receipt history.
4. Reconcile launcher-owned old children before its readiness. Grant reviewed minimal roles only after data and identity checks pass; mark ready last in the protected finalization. An interruption at any barrier leaves target not ready, with no partial enabled grants. Explicit operator recovery may restart validation; no automatic activation.
5. Restore the same dump into TWO independently empty synthetic targets; each has distinct new realm and matching immutable accepted evidence. Authenticated fresh receipt history works; pre-restore sessions, previews/jobs cannot mutate.

Refuse wrong/newer/mixed schema, corrupted/missing normalized bytes, dangling or foreign heads/parents/receipts, altered function/owner/search_path/grants, nonempty target and uninitialized source. Fault each DDL/grant/check/realm/invalidation/final-ready barrier. A known post-backup accepted write is absent and reported lost; do not reconstruct it or raw from hashes. Tests never restore into the personal instance.

Historical UUID reuse under a fresh restore realm is not a replay: only a newly reviewed preview/current authority can create a new operation in that namespace. Old preview/session/job requests remain fenced. Live unaccepted expiry does not imply physical WAL/backup erasure; all restores purge expired/transient authority before readiness, as protocol-appendix.md states.

