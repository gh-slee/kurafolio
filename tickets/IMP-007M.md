---
id: IMP-007M
title: Decide how a re-upload gets back a raw slot that finish could not prove
priority: P0
status: done
type: decision
parent: IMP-007
depends_on: [IMP-007C]
resources: []
risk: high
size: S
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-12, release to write the options and a recommendation; the decision itself stays with the owner"
review: independent
branch: ticket/imp-007m-decide-how-a-re-upload-gets-back-a-raw-s
pr: https://github.com/gh-slee/kurafolio/pull/97
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:cf968d22fe6dcdfadf0a39af3744c41c18ba150851cc4b05611ef5f8f1fe2aaa
updated: 2026-11-21
---

# IMP-007M: Decide how a re-upload gets back a raw slot that finish could not prove

## Goal

When `finish_member_v1` ends an attempt with `reupload_required` but its launcher proofs are missing, `pending` or `failed`, the attempt keeps its raw slot. Each user has one raw slot, so the next `reserve` for that set returns `import_busy`. IMP-007C releases such a slot only after the set becomes terminal (cancel, rejection, commit or expiry), which can take up to 24 hours. The owner decides whether a live set should also be able to prove and release that slot, and by which call.

## Context

- Background only: the revision 1 planning draft [docs/specs/v2-drafts/WL-P0-007.md](../docs/specs/v2-drafts/WL-P0-007.md) (sha256:fa0971a0da787cb327484c92144e4a5ecd916db4ad0328e03b408d647190acd5), which the r7 bundle supersedes.
- Origin: IMP-007C (PR #42) added per-attempt `raw_slot` and `cleanup_proof_bytes` on normalize leases, `claim_plan_v1` (cleanup) and `cleanup_set_v1`. Its owner decisions of 2026-11-10 still hold: decision 4 (proofs cover every normalize attempt that reached the launcher) and decision 5 (a pending or failed proof keeps cleanup `failed` and holds the reservation until a proof succeeds).
- Current behaviour on `main` at `a2f5f2b`, all in `src/kurafolio/persistence/ingestion_schema.py`:
  - Slot scope. `QUOTA_LIMITS['raw']['leases']` is `(1, 4)`: one held raw slot per tenant and portfolio, four per instance. `reserve_member_v1` (the reserve action, not bind) calls `_quota_v1(tenant,portfolio,'raw',1,0)`, which raises `import_busy` when the slot is taken. The slot is per user, not per set, so one held slot blocks every reserve of that user: the same member's re-upload, the other members of the same set and every other set.
  - Finish. In `_lease_ddl(..., 'finish')`, `cleaned` is true only when at least one proof was sent and every proof says `absent` or `not_created`. The finished lease keeps `raw_slot='held'` otherwise, for all three outcomes. Only `finish_member_v1` moves a member to `reupload_required`. A `stage_admitted` finish without proof also keeps the slot while the member is `admitted`, so a second member of the same set cannot reserve until the set ends (the existing test `test_finish_keeps_the_slot_until_cleanup_is_proven_and_waits_for_every_member` shows the held slot, not the blocked reserve).
  - No late proof path. Once a normalize lease is `finished`, finish answers only the same request with its stored acknowledgement and returns `import_stale` for any other. No function accepts later proofs for a finished normalize attempt.
  - Terminal-only release. `cleanup_set_v1` refuses a set that is not terminal (`import_stale`), and the lease trigger refuses a cleanup lease on a non-terminal set (`(NEW.work_kind='cleanup')<>(parent.state=ANY(terminal))`). After the set ends, a bound attempt's slot still returns only when its proofs, matched by job ID and fence, all say `absent` or `not_created`. With pending or failed proofs the set stays `failed` and is retried, so the Goal's "up to 24 hours" is a lower bound.
  - The trigger already allows a live-set release. The `UPDATE` branch of the lease trigger in `_transition_v1` lets a closed normalize lease move `held` to `released` when its stored `cleanup_proof_bytes` are a non-empty array whose proofs all say `absent` or `not_created` and all name the lease's own fence. It does not look at the set state. A closed lease may still replace its proofs while the slot is held, but may not change `state`, `expires_at`, the token or claim fields, or `last_request_id`, `last_request_digest` and `last_result_bytes`.
  - Lock order. `cleanup_set_v1` takes the raw `instance_budgets` row, the user's raw `quotas` row, the storage pair, then the root, set, members (`ORDER BY id`) and leases (`ORDER BY id`). Finish takes the raw pair before the root only when `cleaned`. Both refuse to release a slot twice through the `raw_slot='held'` guard.
- Trust boundary: [runner.md](../docs/specs/imp-007-r7/runner.md) gives the API neither the worker database role nor the launcher peer credential. Launcher proofs reach the database only through the worker and its work functions.
- Callers: no worker process calls finish or cleanup yet ([docs/web-v2-imports.md](../docs/web-v2-imports.md)). IMP-007F adds the worker and trusted launcher that produce proofs (plan PR #86); IMP-007E and IMP-007U add the HTTP routes that will show `import_busy` to users (plan PR #87). This ticket changes none of them.
- The owner's decision of 2026-11-20 (Decisions needed 1 to 3): "B with F". Where each part is built:
  - Option F, the worker waiting for its launcher proof before `finish` within the 120-second raw deadline, is step 6 of the normalize loop in IMP-007F PR 1 (plan PR #86, IMP-007F decision D8). No SQL change.
  - Option B, the worker-fenced late-proof release, is the new ticket IMP-007Q, filed in this pull request. It covers both an unproved `reupload_required` finish and an unproved `stage_admitted` finish (decision 2). It also adds the worker's call to the new function, which the owner put in B's follow-up ticket rather than in IMP-007F (IMP-007F D8). IMP-007Q holds `ingestion-schema-sql` and `v2-import-worker` and depends on this ticket and on IMP-007F.
  - This ticket holds no resource any more (decision 3). The resource-lock overlap with IMP-007N described below no longer applies. `tickets/ROADMAP.md` still orders this ticket "after IMP-007N (same lock)"; that line is out of date and is the owner's to change.
- The Goal says the next reserve "for that set" returns `import_busy` and that release "can take up to 24 hours". On `main` the block covers every reserve of that user, and release can take longer than 24 hours (see "Slot scope" and "Terminal-only release" above). AC-01 covers the general case, so no gated change is proposed; the owner may ask for a wording fix.
- Inventory: every SQL function is listed in the code-tested inventory (the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`) on top of the frozen r7 baseline. A new function or column is an inventory amendment the owner approves, as IMP-007C's `leases` amendment was.
- Overlap with IMP-007N (its plan merged in PR #81; Codex is building it). Written before the decision, kept for IMP-007Q's planner. IMP-007N changes only the cleanup branch of `claim_plan_v1`: a set whose cleanup keeps failing waits `LEAST(30 s × 2^(n−1), 15 min)` after its newest cleanup lease, and the next fence becomes `earlier+1` from the same count. Both tickets hold `ingestion-schema-sql`, and `tickets/ROADMAP.md` orders this ticket after IMP-007N. This ticket changes no SQL, so the only overlap now is the resource lock. The follow-up it may file overlaps as follows:
  - any option that adds cleanup leases on live sets (option D below) changes the trigger and the `claim_plan_v1` cleanup branch that IMP-007N edits, and those leases would count toward its backoff and fence;
  - under option A, a user's way out after cancelling waits on IMP-007N's backoff, up to 15 minutes between cleanup tries;
  - any follow-up that adds gated PostgreSQL test methods starts from the `postgres-foundation` `--expect-skipped` value on `main` when it is built: 118 today, 123 once IMP-007N merges as planned.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).

## Acceptance criteria

- [x] AC-IMP-007M-01: The owner records a decision on whether and how a held slot of a fenced attempt in a live set is released.
- [x] AC-IMP-007M-02: If a change is chosen, a follow-up implementation ticket names the function, its fencing and its PostgreSQL tests.


## Build plan

- Based on: `main` at `d902717` ("Plan IMP-007N: back off cleanup claims for sets whose cleanup keeps failing (#81)"); the SQL facts in Context were read at `a2f5f2b`, and `d902717` changes only ticket files.
- Shape: this is a decision ticket, and the decision is made. On 2026-11-20 the owner answered decisions 1 to 3 in the planning conversation, and plan PR #85 recorded the answers under Decisions needed and in the Log and filed the follow-up, IMP-007Q. The build is a ticket-only closeout: it checks that the record and the follow-up are on `main`, ticks AC-01 and AC-02 and closes the ticket. It writes no product code, tests, migrations or docs.
- Where the decided work is built (not in this ticket):
  - Option B: IMP-007Q (SQL function, inventory amendment, PostgreSQL tests, the worker's call and the docs).
  - Option F: IMP-007F PR 1, step 6 of the normalize loop ("Wait for the cleanup proof"), plan PR #86.
- Why no docs change here: the slot paragraph of `docs/web-v2-imports.md` is edited by IMP-007F PR 1 (the interim text "a slot without a launcher proof stays held until the set ends and is cleaned, until IMP-007Q lands") and by IMP-007Q (the new release). An edit here would duplicate that text and conflict with both. Neither acceptance criterion asks for docs.

### Files

- `tickets/IMP-007M.md` only: AC ticks, the Plan tick, `status`, `branch`, `pr`, `updated`, Handoff and the Log, including the outcome line.
- Nothing else. The pull request is ticket-only, so `python scripts/check_pr_image.py` takes the early exit (ENG-120).

### Steps

1. `git fetch origin`. Check that `git show origin/main:tickets/IMP-007M.md` has this Build plan, `resources: []` and the three answers under Decisions needed, and that `python3 scripts/tickets.py spec IMP-007M` says MATCHES.
2. Check the follow-up on `main`: `git show origin/main:tickets/IMP-007Q.md` exists, is not `superseded`, and its acceptance criteria name the function (AC-IMP-007Q-01), its fencing (AC-IMP-007Q-05) and its PostgreSQL tests (AC-IMP-007Q-11). AC-02 needs the follow-up filed, not built or approved, so do not wait for IMP-007Q's Gate A, Build plan or build. If the owner's Gate A renames the function or reshapes those criteria, AC-02 still holds as long as the ticket names a function, its fencing and its PostgreSQL tests.
3. Check option F's home: `git show origin/main:tickets/IMP-007F.md` has the proof wait in its PR 1 Build plan (normalize step 6) and D8 resolved. If plan PR #86 has not merged yet, say so in the Log line and go on; this ticket already records where F is built. If IMP-007F on `main` drops the proof wait or says F is not built, stop and ask.
4. Claim with `python3 scripts/tickets.py claim IMP-007M --agent <board name> --worktree`. The claim takes no resource lock now.
5. Tick AC-01 with a pointer to Decisions needed 1 to 3 and the 2026-11-20 Log lines. Tick AC-02 with a pointer to IMP-007Q and its AC IDs from step 2. Tick the last Plan box. Set `status: done`, `branch:`, `pr:` and `updated:`, write the Handoff and add the outcome line to the Log.
6. Run `python3 scripts/tickets.py check`, `python3 scripts/tickets.py spec IMP-007M --base origin/main`, `python scripts/check_language.py`, `python scripts/check_publication.py --worktree` and `python scripts/check_pr_image.py` (ticket-only exit). Open the pull request, start the independent review (frontier tier) and hand it to the owner.

### Tests

No code tests: the build changes only this ticket file. `python3 scripts/tickets.py spec IMP-007M` keeps reporting "no test mentions it yet" for both IDs; that is expected for a decision ticket. The reviewer checks:

| AC | Case | Expected |
|---|---|---|
| 01 | Decisions needed 1 to 3 and the 2026-11-20 Log lines | Each answer is dated and quotes the owner's chosen label from the question as asked (Q3, Q12 and the D8 part of Q11); nothing is paraphrased into a choice the owner did not make |
| 01 | Where each part is built | Option B in IMP-007Q; option F in IMP-007F PR 1 step 6 |
| 02 | `tickets/IMP-007Q.md` on `main` | Exists, not `superseded`; AC-IMP-007Q-01 names `release_member_slot_v1` (or the name the owner approved), AC-IMP-007Q-05 its fencing and AC-IMP-007Q-11 its opt-in PostgreSQL tests; `python3 scripts/tickets.py check` passes |
| 01, 02 | `resources:` | Empty, and the Log quotes the owner's Q12 confirmation |

### Negative cases the review should check

- The closeout changes no file except `tickets/IMP-007M.md`, and no gated section (`spec IMP-007M --base origin/main` MATCHES).
- No AC is ticked before the record and IMP-007Q are on `main`.
- The closeout does not edit IMP-007Q, IMP-007F, IMP-007R, IMP-007N or `tickets/ROADMAP.md`, even to fix the stale "same lock" line.

### Rollback

Revert the closeout commit; the ticket goes back to `ready`. Nothing outside `tickets/` changes, so there is no schema, data or inventory to undo. If the owner later reverses the decision, mark IMP-007Q `superseded` in its own pull request rather than deleting it.

### Do not touch

- `src/`, `tests/`, `docs/`, `.github/`, `tests/fixtures/ingestion/oracle.json`, everything under `docs/specs/imp-007-r7/`.
- `tickets/ROADMAP.md`, `tickets/IMP-007.md`, `tickets/IMP-007Q.md`, IMP-007E, IMP-007F, IMP-007N, IMP-007R and every other ticket.

### Stop and ask if

- Step 1 or 2 fails: the answers, `resources: []` or IMP-007Q are not on `main`, or IMP-007Q is `superseded`.
- IMP-007F on `main` says option F is not built (step 3).
- The owner asks for IMP-007Q, or any SQL or worker change, to be built in this session. One ticket per session, and IMP-007Q needs its own Gate A and Build plan first.

## Plan

- [x] Write the options (for example: a normalize-scoped cleanup call on the finished attempt; a reserve that accepts proofs for the previous fence; keep the current terminal-only release) with a recommendation. Done in the planning pull request: Decisions needed 1 to 3.
- [x] Ask the owner and record the answer (AC-01). The owner answered on 2026-11-20; plan PR #85 recorded the answers under Decisions needed and in the Log.
- [x] If a change is chosen, file the follow-up ticket (AC-02); run the checks, start the independent review and open the pull request. IMP-007Q was filed in plan PR #85; AC-01 and AC-02 are ticked, the checks passed, PR #97 is open and Claude Opus 5.5 ran the independent QA and architecture review. Its three metadata findings were addressed in repair round 1, which Claude Opus 5.5 approved on `e0a6129` in the 2026-11-22 re-review.

## Decisions needed

All three decisions were answered by the owner on 2026-11-20. Nothing is open. The questions are kept as written, with each answer under it.

1. How does a user retry an upload in a live set while the previous attempt's raw slot is still held without proof?
   Every option keeps the Handoff rule: a slot is never released without proof that the attempt has no live child or raw buffer. That excludes a timer-based release in a live set.
   - A. Keep terminal-only release (today). No change. The member cannot be re-uploaded while the set is live. The user either waits for the set to expire (24 hours) or cancels it, then waits for cleanup proofs, retried under IMP-007N's backoff, and starts a new set. Because the slot is per user, every other upload of that user waits too. Cost: none now, a bad retry experience later.
   - B. A worker-fenced proof call on the finished normalize attempt. A new worker function takes fresh launcher proofs for the attempt's exact job and fence and releases the slot under the same rule as finish. The trigger already allows this transition, so only the function and its inventory entry are new. Proofs stay on the worker and launcher channel. Cost: one inventory amendment; IMP-007F's worker must call it; a worker restart before the proof falls back to option A for that attempt.
   - C. Reserve accepts proofs for the previous fence. The API would pass launcher proofs it cannot obtain or check: the r7 runner boundary gives the API no launcher credential. Cost: an r7 trust-model amendment. Not recommended.
   - D. Cleanup leases on live sets. Reuses the cleanup claim and `cleanup_set_v1` for live sets. Cost: changes the lease trigger and the `claim_plan_v1` cleanup branch that IMP-007N is changing; the new leases would count toward N's backoff and fence; needs a new selector for live sets with held slots. Largest change.
   - E. More raw slots per user. Changes `QUOTA_LIMITS['raw']['leases']` from 1. Proves nothing and only delays the block; the instance limit of 4 is still shared by all users.
   - F. The worker waits for its proof before finishing. IMP-007F keeps its lease and asks the launcher again before calling finish. No SQL change, but bounded by the 120-second raw deadline, so a child that takes longer to stop still leaves the slot held. It reduces how often the problem happens and combines with A or B.
   - Recommendation: B, with F as worker behaviour in IMP-007F. B is the smallest change that keeps proofs on the trusted channel and needs no trigger or cleanup-branch change, so it does not collide with IMP-007N.
   - **Resolved 2026-11-20.** The owner chose "B with F (Recommended)": "B = a new worker function takes late launcher proofs and releases the slot (one SQL inventory amendment, a follow-up ticket); F = the worker waits for proof before finishing, within the 120 s raw deadline." On where each part is built, the owner accepted IMP-007F D8 ("Accept all (Recommended)"): "the F wait-for-proof goes in IMP-007F now, and calling B's new release function goes in B's follow-up ticket." B is IMP-007Q (filed in this pull request), including the worker's call; F is IMP-007F PR 1.
2. Should the release also cover a held slot left by a `stage_admitted` finish without proof (Context, "Finish")? There the member is `admitted`, but no other member of the same set can reserve, so a multi-member set cannot finish and stays live until it expires. Options: yes, the same call for any finished normalize attempt in a live set; or no, only `reupload_required`. Recommendation: yes. The slot belongs to the attempt, not to its outcome, and AC-01 already speaks of "a held slot of a fenced attempt in a live set". No gated change is needed either way.
   - **Resolved 2026-11-20: yes.** The owner chose "Accept all (Recommended)" for "IMP-007M #2 the new release also covers a slot held after a stage_admitted finish". IMP-007Q covers both outcomes.
3. Should this ticket drop `resources: [ingestion-schema-sql]`? The decision itself changes no SQL, and the lock makes it wait for IMP-007N's build (ROADMAP: "after IMP-007N (same lock)"). Any follow-up carries the resource. Options: drop it, so the decision can be recorded now; or keep it and wait. Recommendation: drop it. The change must reach `main` before IMP-007M is claimed, because `claim` takes the lock, and neither a planning session nor the builder may edit the field. It is therefore the owner's own edit (or one the owner confirms in the Log), on this pull request or after it. Without it, the ticket waits for IMP-007N as ROADMAP already says.
   - **Resolved 2026-11-20: drop it.** The owner chose "Accept all (Recommended)" for "#3 drop IMP-007M's resources: [ingestion-schema-sql] so it isn't stuck behind IMP-007N's lock (your edit or confirmation)". Plan PR #85 makes the edit, and the Log quotes the confirmation. IMP-007Q carries `ingestion-schema-sql`.

## Handoff

- State: PR #97 is open and awaiting the owner's review. Repair round 1 is confirmed: Claude Opus 5.5 approved `e0a6129` against base `b3a5f1c`, with all three findings fixed and both ACs passing. That head also passed its PR and push CI. This record preserves the approval; the record commit remains subject to normal publication and exact-head CI gates.
- Acceptance evidence: AC-01 is covered by Decisions needed 1 to 3 and the 2026-11-20 Log entries: B with F, `stage_admitted` included and the resource removed. AC-02 is covered by IMP-007Q on `origin/main` at `1274b54`: AC-IMP-007Q-01 names `release_member_slot_v1`, AC-IMP-007Q-05 its fencing and AC-IMP-007Q-11 its opt-in PostgreSQL tests. IMP-007F stage 1 normalize step 6 and resolved D8 retain option F. These records describe the decided follow-up work; this closeout adds no slot-release behaviour.
- Next step: The owner reviews PR #97 and decides whether to merge after the review record has passed its normal publication and CI gates. No further repair or independent re-review was requested. Retain the claim until merge and all checks and questions are resolved, then release it and stop.
- Verify: `python3 scripts/tickets.py check`, `python3 scripts/tickets.py pr-check --branch ticket/imp-007m-decide-how-a-re-upload-gets-back-a-raw-s`, `python3 scripts/tickets.py spec IMP-007M --base origin/main`, `python3 scripts/check_language.py`, `python3 scripts/check_publication.py --worktree` and `python3 scripts/check_pr_image.py` from the clean committed branch.
- Review: APPROVE by `claude-code/opus-5.5` (Claude Opus 5.5, high), QA and Architect, on `e0a6129`; [repair round 1 re-review](https://github.com/gh-slee/kurafolio/pull/97#issuecomment-7082064298). All three findings from the first review are fixed, both ACs still pass and no new problem was found. This approval covers `e0a6129`, not the subsequent record commit. The reviewer checked agreement between ticket records, not the exact owner conversations, and did not run PostgreSQL acceptance or code tests.
- Gotchas: Never release a slot without proof that the attempt has no live child or raw buffer. This closeout changes only this file and leaves the approved gated text unchanged. Option B and the worker's release call belong to IMP-007Q; option F belongs to IMP-007F. No SQL, worker, docs or runtime changes here. `status: done` follows the ticket PR workflow. The approval and green CI above apply to `e0a6129`; the record commit needs its own CI, and only the owner merges.
- Open questions: No product decision is open for this ticket.

## Log

- 2026-11-12 claude-code/claude-opus-5-5: filed as a follow-up from IMP-007C.
- 2026-11-12 planner: owner released this ticket on 2026-11-12 so an agent writes the options; the owner still decides. It shares `ingestion-schema-sql` with IMP-007L, so it starts after that claim ends.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the bullet naming the r7 contract bundle from Context into Requirements and numbered the acceptance criteria AC-IMP-007M-01 to 02. Spec hash sha256:cf968d22fe6dcdfadf0a39af3744c41c18ba150851cc4b05611ef5f8f1fe2aaa, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:cf968d22fe6dcdfadf0a39af3744c41c18ba150851cc4b05611ef5f8f1fe2aaa.
- 2026-11-20 claude-code/opus-5.5: planned in PR #85 (branch `plan/IMP-007M`): Context from `main` at `a2f5f2b`, the options and a recommendation under Decisions needed (released by the owner on 2026-11-12; the owner still decides), and a Build plan to record the answer and file the follow-up. Decision 3 proposes dropping `ingestion-schema-sql` for the owner. No gated section changed.
- 2026-11-20 claude-code/opus-5.5: decision 1 answered. The owner was asked "IMP-007M: ... Which fix?" and chose "B with F (Recommended)": "B = a new worker function takes late launcher proofs and releases the slot (one SQL inventory amendment, a follow-up ticket); F = the worker waits for proof before finishing, within the 120 s raw deadline." Plan PR #85.
- 2026-11-20 claude-code/opus-5.5: where B and F are built. The owner was asked "IMP-007F: D3 ship compose.ingestion.yaml (launcher + worker only) that OPS-021 later includes; D5 change Requirements ... a new Gate A you'd be approving here; D6 prepare and cleanup fit in one lease with no renewal for the MVP; D8 the F wait-for-proof goes in IMP-007F now, and calling B's new release function goes in B's follow-up ticket. Accept all four?" and chose "Accept all (Recommended)". Option F is IMP-007F PR 1 (plan PR #86); option B, including the worker's call, is IMP-007Q. Plan PR #85.
- 2026-11-20 claude-code/opus-5.5: decisions 2 and 3 answered, and the owner's confirmation of the `resources` change. The owner was asked "IMP-007M #2 the new release also covers a slot held after a stage_admitted finish; #3 drop IMP-007M's resources: [ingestion-schema-sql] so it isn't stuck behind IMP-007N's lock (your edit or confirmation). APP-011E #2 preferences routes return 404 and are absent from OpenAPI on identity/sources instances. Accept all three?" and chose "Accept all (Recommended)". Decision 2 is yes; decision 3 is drop. On that confirmation `resources` changes from `[ingestion-schema-sql]` to `[]`. Plan PR #85.
- 2026-11-20 claude-code/opus-5.5: filed IMP-007Q (option B: worker-fenced late-proof release of a held raw slot, covering `reupload_required` and `stage_admitted` finishes, plus the worker's call) in plan PR #85, as `backlog` with no Gate A. Rewrote this ticket's Build plan as a ticket-only closeout that checks the record and IMP-007Q on `main` and ticks AC-01 and AC-02; updated Context, Plan, Decisions needed and Handoff. No gated section changed; `spec IMP-007M` still matches sha256:cf968d22fe6dcdfadf0a39af3744c41c18ba150851cc4b05611ef5f8f1fe2aaa.
- 2026-11-21 codex/gpt-6.1-sol: claimed the ticket-only closeout from `origin/main` at `1274b54`; the Build plan is merged, `resources: []` is unchanged and the approved spec matches. Verified the three recorded owner decisions, IMP-007Q AC-01/05/11 and IMP-007F stage 1 normalize step 6 with D8 resolved. No product implementation is included.
- 2026-11-21 codex/gpt-6.1-sol: verified AC-IMP-007M-01 against Decisions needed 1 to 3 and the 2026-11-20 decision Log entries on `origin/main` at `1274b54`; verified AC-IMP-007M-02 against IMP-007Q AC-01/05/11 on that same base. Both criteria are ticked without changing the approved spec text. IMP-007F stage 1 normalize step 6 and D8 retain option F. The final Plan box remains open because no PR or independent review exists yet.
- 2026-11-21 codex/gpt-6.1-sol: local closeout checks passed: `tickets.py check` (139 tickets, 0 errors), `tickets.py spec IMP-007M --base origin/main` (MATCHES; gated sections unchanged), `check_language.py` (532 files, no violations) and `check_publication.py --worktree` (686 files, no violations). No code tests are required by this ticket-only Build plan. Independent QA and architecture review: NOT RUN, because Codex cannot start the configured Claude Opus 5.5 reviewer; run `review IMP-007M` in Claude Code after the PR opens. Publication, the actual PR URL, final status and outcome line remain pending.
- 2026-11-21 codex/gpt-6.1-sol: PR #97 opened at `6c692dd` with the validated description. Prepared the final ticket metadata locally: `status: done`, the actual PR URL and this outcome record. The final Plan box stays open because the configured independent review is NOT RUN. CI and owner merge remain pending; no application behaviour changed.
- 2026-11-22 codex/gpt-6.1-sol: outcome: implementing model `codex/gpt-6.1-sol`; reviewing model `claude-code/opus-5.5`, independent QA and architecture re-review APPROVE on `e0a6129`; review repair rounds: 1; spec and Build plan: nothing missing. AC-01/02 pass and all three findings are fixed. This commit records that approval and is subject to its own publication and CI gates; the owner reviews and merges PR #97.
- 2026-11-21 codex/gpt-6.1-sol: recorded the [independent reviewer findings](https://github.com/gh-slee/kurafolio/pull/97#issuecomment-7074263111) from `claude-code/opus-5.5` (Claude Opus 5.5, high), QA and Architect, on base `1274b54` and head `b9df7ed`. Verdict CHANGES NEEDED: both ACs pass; update the stale Handoff, tick the final Plan box and replace the current review NOT RUN markers and repair count. The reviewer checked consistency among the ticket records, not the exact owner conversations, and did not run PostgreSQL acceptance or code tests.
- 2026-11-21 codex/gpt-6.1-sol: repair round 1 addresses all three findings in this ticket: refreshed the Handoff with the pushed and reviewed head and its green CI, ticked the completed Plan step, updated the current review and outcome records, and prepared a matching complete PR description. The historical checkpoint Log entries remain as history. No gated text, Build plan, Context, other ticket or product file changed. The repair requires publication, its own CI and independent confirmation; no passing re-review is claimed.
- 2026-11-22 codex/gpt-6.1-sol: recorded the [independent re-review](https://github.com/gh-slee/kurafolio/pull/97#issuecomment-7082064298) by `claude-code/opus-5.5` (Claude Opus 5.5, high), QA and Architect, on base `b3a5f1c` and head `e0a6129`. Verdict APPROVE: all three findings fixed, no new problems, AC-IMP-007M-01 and AC-IMP-007M-02 still pass. Updated the current Handoff, Plan confirmation wording and outcome to reflect the approved repair; repair rounds remain 1. The reviewer requested this evidence record and CI on its commit, not another repair round or mandatory re-review. The approval does not cover this later record commit. Exact owner conversations, PostgreSQL acceptance and code tests were outside the review.
