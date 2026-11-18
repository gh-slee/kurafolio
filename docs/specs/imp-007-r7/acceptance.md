# Proposed acceptance and independent evidence

All 007 feature execution is NOT_RUN. Coordinator literals and static validation are not independent QA approval. Original r2 reviewers completed only r2 and are STOPPED. All material directions are selected; authorize exact r4 review separately. Developer self-tests and independent execution remain separate evidence categories.

Oracle `oracle.json` version1 supplies literal synthetic source keys/revisions/quantities, expected history/head/receipt/generation effects and equality boundaries. QA must independently approve/extend it without calling implementation to calculate expected values. Its quantities for008 are labels of future expectations, not calculated007 portfolio values.

| ID | Required cases, including negatives | Fixed expected evidence | Golden/requirements |
|---|---|---|---|
| A07-01 | First Wealthsimple-only and Bull-only; one combined 4-member cap; no renderers/quotes configured | Facts once; first unmapped accounts/instruments reach NEEDS_MAPPING then READY; no invented BTC/valuation | R03/R09; AC01/04 |
| A07-02 | Same operation replay vs new duplicate operation; source disabled/preview expired after success | Exact replay all deltas 0; new duplicate receipt 1/audit 1/financial generations 0/outbox 0; auth still live | R05/R54; AC01/04 |
| A07-03 | Bull exports[x,y] then[y,z], z=0.005 | Exactly x/y/z source/economic heads, no second y; future 008 0.035 for0.010+0.020+0.005 | G04/G05/G06; R05/R34 |
| A07-04 | Equal time/quantity distinct IDs x/y each0.010 | Two facts and two heads, future0.020; x reimport0 | G04; R05 |
| A07-05 | Missing-ID indistinguishable twins, identical file hashes | CONFLICT, zero ACCEPT receipt/facts/generation; no hash-only identity | G04; R05 |
| A07-06 | Complete T1 A10/B5 then T2 A7; complete-empty; all/category/explicit scopes | Literal snapshot memberships/base/latest heads; empty complete valid; no stored synthetic zero row | G01; R05/R31 |
| A07-07 | Partial/unknown T2 A7 and empty partial; disjoint/overlap scopes | Explicit partial latest marker, preserved last-seen base, no zero/completeness inference; overlap conflict as table | G02; R05/R31 |
| A07-08 | Older T2 after T3 A8; equal UTC offsets; different same-time; explicit parent A9; invalid branches | Older history only; equal conflicting blocked; corrected head A9 with prior8 retained; foreign/missing/cyclic parent denied | G03/G13; R05 |
| A07-09 | TFSA/RRSP, two connections one account, exact mirror vs independent vs unresolved | No label merge; mirror one economic head/two source evidences, independent two; unresolved blocked | G14; R41 |
| A07-10 | Same ticker different MIC/currency, BTC/LBTC networks | Distinct mapped entities and source facts; no ticker-only or network collapse | G14; R31 |
| A07-11 | BUY 0.010+0.020; transfer 0.030; balance 0.030; funding; independent third BUY 0.005; pending->completed->void/correction | Exact retained diagnostics/status/fee/cash links; only authoritative active supported completed BUY eligible; optional third yields 0.035 BTC future oracle | G05/G06; R34 |
| A07-12 | Null vs zero cost/fees; signed security; date-only/legacy time;1sat/sub-sat; lifecycle rates | Exact token/precision/nullness survives staging->accept->restore; invalid sub-sat rejects, no invented time | G13; R31 |
| A07-13 | Missing quotes/FX/export backend; unavailable/unknown format/PULL_API | Acceptance independent of references/rendering; supported explicit CSV only | R03/R09; AC04 |
| A07-14 | Unknown first mappings and remap after raw deletion; real reparse/version/alias change | Deterministic core remap+new digest with no child call; actual reparse requires re-upload; frozen bridge not bypassed | R13/R31 |
| A07-15 | Alter raw/context/discovery/minimal/plan/hash/ordinal/local ref/external ref | Reject exact invalid boundary with zero accepted effects and no content leak | R13/R31/R54 |
| A07-16 | Installation/availability/enablement/connection disable/re-enable ABA | Stale preview; generation mismatch prevents new effect; historical success replay separately allowed | R09/R54 |
| A07-17 | Mapping/authority/accepted generation changes between preview/lock | Re-preview, no changed plan committed under old approval | R31/R41/R54 |
| A07-18 | Logout/credential-disable/restore after queue or lock wait; expiry equality | Final live guard denies; no return of private payload on rejected request; expiry at equality | R54 |
| A07-19 | Two users same IDs; worker/API pool reuse, failed tx/savepoint | No cross-scope facts/stage/previews/receipts/links; no retained role/tenant scope | R31/R54 |
| A07-20 | Conflicting concurrent confirms; cancel-vs-commit; stale duplicate worker | One effect; explicit loser; terminal state and actual receipt agree | G15; R54; AC03 |
| A07-21 | Lose accepted COMMIT ack, expire preview/change source/mapping, retry with same/new session; restore | Live-auth same-operation recovers once; changed payload/kind conflicts; old-realm POST cannot write | G15; R54 |
| A07-22 | Fault after each entity/fact/head/lineage/gen/receipt/audit/outbox statement | Literal prestate exactly restored, no partial financial delta | G15; R54; AC04 |
| A07-23 | Serialization/deadlock/total deadline/exhausted counters | At most3 whole attempts/20s; no overflow, partial commit or hidden timeout success | R54 |
| A07-24 | Two accounts/files where last member fails or changes | Whole selected unit no effect; explicit smaller new set only, no row subset | G14/G15; R31; AC01 |
| A07-25 | Crash/disconnect/cancel/expiry at every state and child boundary | Fixed fault/state table; late result fenced; raw lost -> reupload; stage admitted -> remap within TTL | R13/R54 |
| A07-26 | Forbidden canaries in unused fields/comments/filename/source_fields and separate allowed financial/time markers | Check live reception, DB/WAL/dumps/logs/backups before/after cleanup; no raw insert-and-delete; allowed typed values retained | R13; AC02 |
| A07-27 | Guessed raw handles/path/symlink/cross-job access | No arbitrary path read or value/path leak; opaque owned handles only | R13/R31 |
| A07-28 | Real ASGI headers/chunks/deadlines/CL+TE/extra-short body, framing/base64 where frozen transport used, output overflow | Exact route-specific precedence; thresholds below/equal/above; no decode of over-limit output | R09/R13 |
| A07-29 | Actual engine network/host file/socket/env/readonly/privilege probes | Actual effective controls and denial evidence for each declared platform/arch/image; NOT_RUN is not PASS | R13/R31 |
| A07-30 | CPU/memory/PID/stdout/stderr/wall/descendants/cancellation/cleanup failure | Separate measured bounds and owned-child removal; no kill-all/prune | R13/R54 |
| A07-31 | Wrong peer/mTLS/job/image/nonce/fence; replay/substituted output/arbitrary flags/paths | No unauthorized start/read/cancel; launcher privilege remains disclosed | R09/R31 |
| A07-32 | Frozen providers/domain/parser/transport1; legacy CLI/Web/report/archive regressions | Frozen source hashes unchanged; no old raw cleanup or candidate promotion | R13/R31 |
| A07-33 | Real SQL per-role DML/column/DDL/EXECUTE bypass; altered predecessor/inventory/roles; migrationfaults | Only declared functions allowed; forced scope/immutability; no ready/stamp/repair on drift | R31/R54 |
| A07-34 | Two empty initialized restores plus corrupt/missing/foreign/dangling/newer/nonempty/uninitialized and barrier faults | Exact immutable bytes/relations/counters, different realms; ready last; old forms/jobs/sessions invalid | R13/R54 |
| A07-35 | Outbox/render failure after acceptance; duplicate delivery | Acceptance preserved; no rendering in transaction; one financial outbox event/effect | R03/R54; AC04 |
| A07-36 | Error/log/DTO/locale precision; two API processes concurrent quotas/rates, worker restart | Code-only errors, no float finance, exact shared quotas held through cleanup; all 3 locale contracts preserved | R09/R13/R31 |

## Evidence ownership and required environments

Developer: syntax/unit/type/contract/ASGI and realPG self-tests, exact fixture/oracle/source hashes, actual count/skips and cleanup manifests. Architect: exact authority/codec/SQL/profile/launcher review and security negatives. Independent QA: independently derive literal expected state, execute realPG process races/negative grants, native launcher controls and two fresh-target restore faults, verify end-to-end API without renderers. Owner: material policy sign-off, exact Gate A, later concrete Gate B and separate publication/deployment approvals.

Test resources use unique disposable PG databases/roles, Compose project, queues, ports and launcher ownership labels under a random test run ID. Never use personal DB/volume/CSV/reports/config. Do not reserve real resources during planning. Existing commands in AGENTS.md can check the baseline; do not invent executed007 test commands. New actual commands/results must be documented during approved implementation. Optional environment tests skipped by a core-only suite do not certify this critical scope.

Before Gate A, independently review the completed codec/SQL/error-map/inventory appendices and full fixture/case matrix; approve the fixed expected hashes without copying production outcomes. Before Gate B, all approved mandatory groups must actually run or the corresponding scope remains blocked. Unavailable Windows/macOS-native coverage must never be relabeled Linux evidence.

fixtures/case-matrix.json explicitly maps all 36 groups to full base fixtures and fixed actions/expected outcomes; fixture-appendix.md distinguishes the parser2 three-source-revision first use from native two-source-revision first use. Native actual kernel/PG/ASGI tests remain required during implementation, not replaced by static validation.

