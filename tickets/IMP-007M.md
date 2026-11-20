---
id: IMP-007M
title: Decide how a re-upload gets back a raw slot that finish could not prove
priority: P0
status: ready
type: decision
parent: IMP-007
depends_on: [IMP-007C]
resources: [ingestion-schema-sql]
risk: high
size: S
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-12, release to write the options and a recommendation; the decision itself stays with the owner"
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:cf968d22fe6dcdfadf0a39af3744c41c18ba150851cc4b05611ef5f8f1fe2aaa
updated: 2026-11-18
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
- Callers: no worker process calls finish or cleanup yet ([docs/web-v2-imports.md](../docs/web-v2-imports.md)). IMP-007F adds the worker and trusted launcher that produce proofs; IMP-007E adds the HTTP routes that will show `import_busy` to users. Both are being planned separately and are not changed here.
- Inventory: every SQL function is listed in the code-tested inventory (the `sql-inventory` key of `tests/fixtures/ingestion/oracle.json`) on top of the frozen r7 baseline. A new function or column is an inventory amendment the owner approves, as IMP-007C's `leases` amendment was.
- Overlap with IMP-007N (plan PR #81, not merged when this plan was written). IMP-007N changes only the cleanup branch of `claim_plan_v1`: a set whose cleanup keeps failing waits `LEAST(30 s × 2^(n−1), 15 min)` after its newest cleanup lease, and the next fence becomes `earlier+1` from the same count. Both tickets hold `ingestion-schema-sql`, and `tickets/ROADMAP.md` orders this ticket after IMP-007N. This ticket changes no SQL, so the only overlap now is the resource lock. The follow-up it may file overlaps as follows:
  - any option that adds cleanup leases on live sets (option D below) changes the trigger and the `claim_plan_v1` cleanup branch that IMP-007N edits, and those leases would count toward its backoff and fence;
  - under option A, a user's way out after cancelling waits on IMP-007N's backoff, up to 15 minutes between cleanup tries;
  - any follow-up that adds gated PostgreSQL test methods starts from the `postgres-foundation` `--expect-skipped` value on `main` when it is built: 118 today, 123 once IMP-007N merges as planned.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).

## Acceptance criteria

- [ ] AC-IMP-007M-01: The owner records a decision on whether and how a held slot of a fenced attempt in a live set is released.
- [ ] AC-IMP-007M-02: If a change is chosen, a follow-up implementation ticket names the function, its fencing and its PostgreSQL tests.

## Build plan

- Based on: `main` at `a2f5f2b` ("Cut pull requests and CI runs that only move ticket paperwork (#78)").
- Shape: this is a decision ticket. The options and a recommendation are under Decisions needed, written in the planning pull request as the owner's release of 2026-11-12 allowed. The build records the owner's answer (AC-01) and, when the answer is a change, files one follow-up ticket that names the function, its fencing and its PostgreSQL tests (AC-02). The build writes no product code, tests, migrations or public docs, whichever option the owner picks. The plan below covers every option and presumes none.

### Files

- `tickets/IMP-007M.md`: the owner's answers under Decisions needed, Plan ticks, the AC ticks, status, Handoff and Log.
- `tickets/<follow-up ID>.md` (new), only when the owner chooses a change. Take the next unused ID after `git fetch origin`. At `a2f5f2b` `IMP-007O` is free; prefer an IMP-007 child letter because the parent is IMP-007.
- Nothing else. The pull request is ticket-only, so `python scripts/check_pr_image.py` exits early (ENG-120).

### Steps

1. Check that the plan is on `main` (`git show origin/main:tickets/IMP-007M.md` has this Build plan) and that `python3 scripts/tickets.py spec IMP-007M` says MATCHES.
2. Re-check each Context fact against `origin/main`. If IMP-007N (or anything else) has merged and changed `claim_plan_v1`, `cleanup_set_v1`, finish, reserve, the lease trigger or `QUOTA_LIMITS`, note the change in the Handoff and stop and ask if it changes an option's cost.
3. Get the owner's answers to decisions 1 to 3. If they are not already recorded on `main`, show the owner the three questions as written and ask in the session. Do not choose for the owner and do not treat the recommendation as an answer. Without an answer, set `status: blocked`, push, and stop.
4. Record each answer under its decision: "Answered by the owner on <date>: "<the owner's exact words>"", and a Log line quoting the owner. Tick AC-01 once decision 1 is answered.
5. Decision 3 changes the `resources:` field. Change it only if the owner confirms that change in words, and quote them in the Log.
6. If decision 1 is option A alone, file no implementation ticket. Record that AC-02 does not apply ("no change chosen") and tick it. Also report to the owner that IMP-007E's user-facing `import_busy` message should say how to get out (cancel the set, then wait for cleanup); filing that is the owner's call.
7. Otherwise file one follow-up ticket from the template in `tickets/README.md`, with the field values and content listed under "Follow-up ticket" below for the chosen option. Write its Goal, Requirements and Acceptance criteria. Leave its Build plan to a planning session. If the owner approves its text in the same session, record that Gate A in the same pull request (`gate_approval` quoting the owner, `spec_approved` from `python3 scripts/tickets.py spec <new ID>`, `status: ready`, and a Log line). Otherwise leave it `backlog`. Tick AC-02.
8. Run `python3 scripts/tickets.py check`, `python scripts/check_language.py`, `python scripts/check_publication.py --worktree` and `python scripts/check_pr_image.py`. Open the pull request, start the independent review (frontier tier) and hand it to the owner.

### Follow-up ticket

Fields for every option: `parent: IMP-007`, `type: feature`, `priority: P0`, `risk: high`, `agent_tier: frontier`, `review: independent`, `gate: owner`, `spec: docs/specs/imp-007-r7/spec.md`, `depends_on: [IMP-007M]`, and `resources: [ingestion-schema-sql]` for any SQL change. Its Requirements repeat the r7 bundle bullet from this ticket and state the owner's answer to decisions 1 and 2. Its acceptance criteria must name each item below (AC-02 needs at least the function, the fencing and the PostgreSQL tests).

Option B (worker-fenced proof call on the finished attempt):

- Function: one new worker function, for example `wl_ingestion.release_member_slot_v1(p_worker uuid,p_token text,p_request jsonb,p_bytes bytea) RETURNS jsonb`, `SECURITY DEFINER`, `search_path=pg_catalog,pg_temp`, `REVOKE ALL ... FROM PUBLIC` and executable by the worker role exactly as `finish_member_v1` is. The final name is the owner's.
- Request: the finish keys without `outcome` and `error_code`, that is `cleanup_proofs`, `credential_epoch`, `fence`, `job_id`, `member_id`, `realm_digest`, `request_id`, `set_id`, `version` (1) and `work_kind` (`normalize`); `p_bytes` NULL; proofs checked by `_proofs_shape_sql(3, same_job=True)`.
- Fencing: `_guard_worker_v1` first; scope only from the stored set; the target is the newest normalize lease of that member at that fence with `state='finished'` and `raw_slot='held'`; `worker_id` and `token_digest` must match the worker and its handoff token; the member's context `job_id` must equal the request's; the member's `fence` must still equal the lease's fence; `incarnation` and `restore_epoch` must match the guard, as in `cleanup_set_v1`. The ticket must say whether a terminal set is refused (`import_stale`, leaving terminal sets to `cleanup_set_v1`) or accepted.
- Lock order: as finish, with the raw `instance_budgets` row and the user's raw `quotas` row always taken before the root, then set, members and leases sorted by `id`. READ COMMITTED only, as `cleanup_set_v1` requires.
- Release rule: exactly finish's `cleaned` rule and the trigger's rule. A non-empty proof list for this fence that is all `absent` or `not_created` sets `raw_slot='released'`, stores the proofs and calls `_quota_v1(...,'raw',-1,0)` once. Otherwise only the proofs are stored and the slot stays held. The trigger forbids writing `last_request_*` on a closed lease, so a repeat call must be answered from the lease's state (released or still held), not from a stored result. The ticket says so, so that no trigger change creeps in.
- Inventory: one new function entry in the `sql-inventory` of `tests/fixtures/ingestion/oracle.json` and in the function inventory of `ingestion_schema.py`. The owner approves this amendment. No table, column or index.
- PostgreSQL tests (opt-in, `IngestionAppendOnlyPostgresTests`): a proven call after an unproved `reupload_required` finish releases the slot once, and the next reserve starts fence 2; a proven call after an unproved `stage_admitted` finish lets the set's second member reserve (if decision 2 is yes); `pending`, `failed` and empty proofs keep the slot and store the proofs; a wrong fence, job, member, worker or token, an `offered` or `active` lease, a lease already `released` and a restored instance each leave lease and quota unchanged; the call then `cleanup_set_v1` after cancel release the slot once in total (raw `lease_count` never below 0); the function is not public. A static test in `IngestionStorageDDLTests` checks the inventory entry and the lock order.
- CI: raise `--expect-skipped` of the `postgres-foundation` job by one per new gated method, starting from the value on `main` when the follow-up is built.
- Docs: the finish and cleanup paragraph of `docs/web-v2-imports.md`.
- Caller: IMP-007F's worker is the only caller. It calls this when finish returned `cleanup_complete: false` and the launcher later proves the child gone. If the worker restarts first, the slot falls back to the terminal-set cleanup, as today. The ticket says whether IMP-007F must change, without editing IMP-007F.

Option C (reserve accepts proofs for the previous fence): `reserve_member_v1` would take proofs from the API. Context shows the API has no launcher credential, so this changes the r7 trust model in `runner.md`. Do not file it. Stop and ask the owner for the r7 amendment first.

Option D (cleanup leases on live sets): changes the lease trigger and the `claim_plan_v1` cleanup branch. The ticket must depend on IMP-007N, keep N's backoff and fence rule (or state how live-set cleanup leases are left out of them), add a claim selector for live sets with held slots, and list the same tests as option B plus a backoff interaction test.

Option E (more raw slots per user): a `QUOTA_LIMITS['raw']['leases']` change; the ticket must check whether the r7 bundle fixes the value and name the quota tests that change (`test_quota_rates_slots_and_storage_are_shared_and_released_once`).

Option F (the worker waits for its proof before finishing): IMP-007F behaviour only, no SQL. The ticket names the worker step, its bound (finish must still land before the 120-second raw deadline, which leases never extend) and its worker tests. If the owner reads AC-02 as needing a SQL function here, stop and ask.

### Tests

No code tests: the build changes only ticket files. `python3 scripts/tickets.py spec IMP-007M` will keep reporting "no test mentions it yet" for both IDs; that is expected for a decision ticket. The reviewer checks:

| AC | Case | Expected |
|---|---|---|
| 01 | Decisions needed 1 to 3 and the Log | The owner's exact words, dated, under each decision; no answer paraphrased into a choice the owner did not make |
| 02 | A change chosen | One new ticket whose acceptance criteria name the function, its fencing and its PostgreSQL tests from the list above; `python3 scripts/tickets.py check` passes |
| 02 | Option A alone | No new ticket; AC-02 marked as not applying, with the owner's words |

### Negative cases the review should check

- No option is recorded as chosen without the owner's words.
- The follow-up never releases a slot without proofs for that exact fence (the Handoff gotcha) and never takes proofs through the API.
- The follow-up does not reuse `last_request_*` on a closed lease, and does not touch the lease trigger unless the chosen option is D.
- No file outside `tickets/` changes, and no other ticket file changes except the new follow-up.

### Rollback

Revert the commits. Nothing outside `tickets/` changes, so there is no schema, data or inventory to undo. If a follow-up ticket was filed and the decision is reverted, mark it `superseded` rather than deleting it.

### Do not touch

- `src/`, `tests/`, `docs/`, `.github/`, `tests/fixtures/ingestion/oracle.json`, everything under `docs/specs/imp-007-r7/`.
- `tickets/ROADMAP.md`, `tickets/IMP-007.md`, IMP-007E, IMP-007F, IMP-007N and every other ticket except the new follow-up.

### Stop and ask if

- The owner's answer is unclear, combines options in a way not listed here, or picks C (it needs an r7 trust-model amendment first).
- A Context fact no longer holds on `origin/main` (step 2).
- The owner asks for the follow-up to be built in this session. One ticket per session, and the follow-up needs its own Build plan first.
- Decision 3 is answered without explicit words about `resources:`.

## Plan

- [x] Write the options (for example: a normalize-scoped cleanup call on the finished attempt; a reserve that accepts proofs for the previous fence; keep the current terminal-only release) with a recommendation. Done in the planning pull request: Decisions needed 1 to 3.
- [ ] Ask the owner and record the answer (AC-01).
- [ ] If a change is chosen, file the follow-up ticket (AC-02); run the checks, start the independent review and open the pull request.

## Decisions needed

1. How does a user retry an upload in a live set while the previous attempt's raw slot is still held without proof?
   Every option keeps the Handoff rule: a slot is never released without proof that the attempt has no live child or raw buffer. That excludes a timer-based release in a live set.
   - A. Keep terminal-only release (today). No change. The member cannot be re-uploaded while the set is live. The user either waits for the set to expire (24 hours) or cancels it, then waits for cleanup proofs, retried under IMP-007N's backoff, and starts a new set. Because the slot is per user, every other upload of that user waits too. Cost: none now, a bad retry experience later.
   - B. A worker-fenced proof call on the finished normalize attempt. A new worker function takes fresh launcher proofs for the attempt's exact job and fence and releases the slot under the same rule as finish. The trigger already allows this transition, so only the function and its inventory entry are new. Proofs stay on the worker and launcher channel. Cost: one inventory amendment; IMP-007F's worker must call it; a worker restart before the proof falls back to option A for that attempt.
   - C. Reserve accepts proofs for the previous fence. The API would pass launcher proofs it cannot obtain or check: the r7 runner boundary gives the API no launcher credential. Cost: an r7 trust-model amendment. Not recommended.
   - D. Cleanup leases on live sets. Reuses the cleanup claim and `cleanup_set_v1` for live sets. Cost: changes the lease trigger and the `claim_plan_v1` cleanup branch that IMP-007N is changing; the new leases would count toward N's backoff and fence; needs a new selector for live sets with held slots. Largest change.
   - E. More raw slots per user. Changes `QUOTA_LIMITS['raw']['leases']` from 1. Proves nothing and only delays the block; the instance limit of 4 is still shared by all users.
   - F. The worker waits for its proof before finishing. IMP-007F keeps its lease and asks the launcher again before calling finish. No SQL change, but bounded by the 120-second raw deadline, so a child that takes longer to stop still leaves the slot held. It reduces how often the problem happens and combines with A or B.
   - Recommendation: B, with F as worker behaviour in IMP-007F. B is the smallest change that keeps proofs on the trusted channel and needs no trigger or cleanup-branch change, so it does not collide with IMP-007N.
2. Should the release also cover a held slot left by a `stage_admitted` finish without proof (Context, "Finish")? There the member is `admitted`, but no other member of the same set can reserve, so a multi-member set cannot finish and stays live until it expires. Options: yes, the same call for any finished normalize attempt in a live set; or no, only `reupload_required`. Recommendation: yes. The slot belongs to the attempt, not to its outcome, and AC-01 already speaks of "a held slot of a fenced attempt in a live set". No gated change is needed either way.
3. Should this ticket drop `resources: [ingestion-schema-sql]`? The decision itself changes no SQL, and the lock makes it wait for IMP-007N's build (ROADMAP: "after IMP-007N (same lock)"). Any follow-up carries the resource. Options: drop it, so the decision can be recorded now; or keep it and wait. Recommendation: drop it. Changing `resources` of an approved ticket needs the owner's confirmation in the Log.

Not proposed for a gated change: the Goal says the next reserve "for that set" returns `import_busy` and that release "can take up to 24 hours". On `main` the block covers every reserve of that user, and release can take longer than 24 hours (Context). AC-01 already covers the general case, so the owner may leave the Goal as it is or ask for a wording fix.

## Handoff

- State: Not started. Released 2026-11-12 for the options write-up. Found while implementing IMP-007C: each normalize lease records `raw_slot`, and only `finish_member_v1` (with proofs) or `cleanup_set_v1` (terminal sets) releases it.
- Next step: Write the options with a recommendation.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_migration -v`
- Gotchas: Never release a slot without proof that the attempt has no live child or raw buffer.
- Open questions: The decision above.

## Log

- 2026-11-12 claude-code/claude-opus-5-5: filed as a follow-up from IMP-007C.
- 2026-11-12 planner: owner released this ticket on 2026-11-12 so an agent writes the options; the owner still decides. It shares `ingestion-schema-sql` with IMP-007L, so it starts after that claim ends.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the bullet naming the r7 contract bundle from Context into Requirements and numbered the acceptance criteria AC-IMP-007M-01 to 02. Spec hash sha256:cf968d22fe6dcdfadf0a39af3744c41c18ba150851cc4b05611ef5f8f1fe2aaa, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:cf968d22fe6dcdfadf0a39af3744c41c18ba150851cc4b05611ef5f8f1fe2aaa.
- 2026-11-20 claude-code/opus-5.5: planned in PR #85 (branch `plan/IMP-007M`): Context from `main` at `a2f5f2b`, the options and a recommendation under Decisions needed (released by the owner on 2026-11-12; the owner still decides), and a Build plan to record the answer and file the follow-up. Decision 3 proposes dropping `ingestion-schema-sql` for the owner. No gated section changed.
