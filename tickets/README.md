# Tickets and the parallel agent workflow

This directory is the single tracked backlog for Kurafolio. Any coding agent
(Codex, Claude Code, opencode with DeepSeek or another model, or a human) can pick
up any ticket, including one another agent started and could not finish. Several
agents can work on different tickets at the same time.

Nothing here depends on a particular vendor. The protocol is Markdown files, Git
branches and worktrees, and one standard-library script:
[`scripts/tickets.py`](../scripts/tickets.py). [AGENTS.md](../AGENTS.md) stays the
authority for safety, finance and publication rules. A ticket never widens those rules.

- [ROADMAP.md](ROADMAP.md) has the end-to-end plan, phases and parallel lanes.
- `python3 scripts/tickets.py list` shows the live board.
- `python3 scripts/tickets.py next` lists the tickets ready to claim, of every tier;
  `next --plan` lists those that still need a Build plan.
- [AGENTS.md](../AGENTS.md#models-and-roles) names the planner, builder and reviewer
  models and how each tool routes "plan", "pick up" and "review" a ticket.

## Quick start for an agent

Run all commands from a checkout of this repository. The script finds the shared
Git directory itself, so it works from the primary checkout or any worktree.

```bash
git fetch origin
python3 scripts/tickets.py cleanup
python3 scripts/tickets.py next
python3 scripts/tickets.py resume ENG-018
python3 scripts/tickets.py claim ENG-018 --agent opencode/deepseek-flash --worktree
```

`claim` creates or attaches `work/worktrees/<ticket-id>` on the ticket branch. Do
all work there, never in the primary checkout. Then:

1. Read the ticket's **Handoff** section first, then Goal, Requirements, Acceptance
   criteria and Build plan. The ticket is the spec ([Writing a ticket as a spec](#writing-a-ticket-as-a-spec)).
   If the copy on `origin/main` has no Build plan, do not build: report that the
   ticket needs planning and stop. Read only the docs the ticket links, plus AGENTS.md. Run
   `python3 scripts/tickets.py spec <ID>`: if it reports the spec changed since
   approval, do not build; tell the owner. If the Build plan or the spec is silent on
   behaviour, data or an interface you need, write the question under Decisions
   needed, set `status: blocked`, commit, push, tell the owner and stop. Keep the
   claim. Do not guess.
2. Set `status: in_progress` and `updated:`, add a Log line, and commit.
3. Work through the Plan checkboxes. After each meaningful step, update Handoff,
   commit (WIP commits are fine on a ticket branch; the owner squashes them at
   merge) and run
   `python3 scripts/tickets.py heartbeat <ID> --note "<one line>"`.
4. Before you stop for any reason, write the Handoff (see below), commit and push
   the ticket branch. Assume you can be cut off at any moment by a usage limit.
5. When the acceptance criteria pass and any required independent review is
   recorded, set `status: done` and `pr:` in the PR's final commit, then open the
   PR using the repository PR rules. Write the PR title as a one-line summary of the
   change, because it becomes the subject of the squashed commit on `main` and the
   PR description becomes its body. Because only the owner merges, the ticket reads
   `done` on `main` only after the merge. While the PR is open, its branch copy
   and the live claim show it as under review. If review requests changes, keep
   the claim and set `status: in_review` until the repair is pushed. In the same
   final commit, add one outcome line to the Log: the implementing model, the
   reviewing model, the number of review repair rounds, and anything the spec or Build
   plan failed to say (or "nothing missing"); update it if review leads to more
   repairs. Before handing over, run `python3 scripts/tickets.py spec <ID> --base origin/main`:
   a build must not change the gated sections.
6. Work on one ticket per session, so the session's context holds only that
   ticket. Until the PR is merged, use the session only for that ticket: review
   repairs, CI fixes and the owner's questions about it. Do not claim a second
   ticket or take on unrelated work in it. File a follow-up ticket instead, or ask
   the owner to start a new session for the other work.
7. End the session once the owner has merged the PR and nothing on the ticket is
   outstanding: no unanswered review finding or owner question, no failing check,
   no unpushed commit and no unfiled follow-up. Run
   `python3 scripts/tickets.py release <ID>`, report the merge and stop. Do not pick
   up the next ticket; it starts in a new session. If the PR is closed without
   merging, set the ticket back to `ready` with a Log line, release it and stop. If
   a session stops before the merge, the next agent's `cleanup` at pickup removes
   the merged worktree and its local branch and releases the leftover stale claim.

## Capability tiers

Each ticket has an `agent_tier`. It does not decide which model may build: the
planner model plans every ticket and any builder model in
[AGENTS.md](../AGENTS.md#models-and-roles) may build a ticket of any tier once its
Build plan is on `main`. The tier sets how much the Build plan must cover and how
the result is reviewed.

| Tier | Tickets | Build plan | Review |
|---|---|---|---|
| `any` | Low-risk, well-specified chores, docs and tests with no financial, SQL, auth or migration semantics | Short: files, the test per acceptance ID and when to stop and ask | As the ticket's `review` field says |
| `standard` | Normal features with clear contracts; medium risk | Full, as the [template](#writing-a-ticket-as-a-spec) describes | As the ticket's `review` field says |
| `frontier` | Critical or high-risk finance, SQL/RLS, auth, migration, concurrency and recovery | Full, plus independent expected values, negative cases, rollback and the points where the builder must stop and ask | The reviewer model's independent review is required before the owner's review |

`next` lists every tier; `--tier` only narrows the list to tickets at or below a tier.

## Running several agents at once

Parallel safety comes from four mechanisms. All of them are enforced by the
script or by review, not by trust.

1. **One ticket, one writer.** `claim` creates
   `<git-common-dir>/agent-tickets/claims/<ID>.json` with an atomic exclusive
   create. A second claim on the same ticket fails, even if it comes from a
   different worktree or a different agent product on the same machine.
2. **Exclusive resources.** A ticket lists `resources:` such as `ingestion-schema-sql`
   or `frontend-shell`. Claiming locks each one atomically. Tickets that share a
   resource cannot be worked at the same time, which keeps two agents out of the
   same schema, migration order, locale catalog or contract.
3. **One worktree and branch per ticket.** Never share a worktree. Never check
   out another ticket's branch for writing.
4. **Isolated runtime resources.** Each claim records an `isolation_id` and a
   `port_base`. Use the isolation ID as a prefix for Docker/Compose project
   names, PostgreSQL test environments (`scripts/postgres.py test-environment
   --output work/pg-tests-<isolation_id>`), temp directories and queues. Use
   ports from `port_base` to `port_base + 99`. When running the browser suite
   in parallel, set `KURAFOLIO_E2E_PORT` to your claim's `port_base` before
   running `npm --prefix frontend run test:e2e` in your own worktree. The browser
   suite uses port 8765 when the variable is unset.

Lanes that can usually run in parallel are listed in [ROADMAP.md](ROADMAP.md).

Claims are local to one machine. If agents work on different machines, the
pushed ticket branch is the shared record: before you claim, run `git fetch`, and
if `origin/<branch>` has commits not in `main`, treat the ticket as owned
elsewhere unless the owner says otherwise.

## Picking up interrupted work

A claim carries a heartbeat. If the heartbeat is older than
`KURAFOLIO_TICKET_STALE_MINUTES` (default 120), the previous agent is presumed stopped,
for example by a 5-hour or weekly usage limit.

```bash
python3 scripts/tickets.py resume IMP-007A     # ticket from its branch, claim, git state
python3 scripts/tickets.py takeover IMP-007A --agent codex/gpt-6.1-sol --worktree --reason "previous agent hit usage limit"
```

Before you take over, confirm that no process is still writing in that worktree. Then:

- Read Handoff and the last commits on the branch. Run `git status` in the worktree:
  uncommitted changes are the previous agent's unfinished step. Keep them.
- Re-run the Handoff **Verify** commands before trusting any claim in it.
- Add a Log line naming the former and new agents.

Never take over a live (non-stale) claim unless the owner tells you to
(`--owner-approved`). Time passing alone does not make a non-stale claim free.

## Ticket file format

File name equals ID: `tickets/IMP-007A.md`. An ID is an area prefix, a three-digit
number and, for the child of an epic, a letter: `<AREA>-<number>[letter]`. The area says
which part of the product the ticket belongs to. The ID never carries the priority; the
`priority` field does, so re-ranking a ticket never renames it.

| Prefix | Covers |
|---|---|
| `CORE` | Domain model and database foundation |
| `AUTH` | Accounts, sign-in and user administration |
| `PLG` | Source plugins and institutions |
| `IMP` | Imports |
| `MKT` | Prices, exchange rates and currencies |
| `ANL` | Positions, analysis pages and calculations |
| `ETF` | Fund look-through and exposure |
| `RPT` | Downloads and reports |
| `APP` | App shell, onboarding, sign-in and settings screens, languages |
| `OPS` | Deployment, release and security operations |
| `ENG` | Agent workflow, CI, tests and planning |

Tickets created before 2026-11-13 had IDs of the form `WL-P0-007A` or `UX-P1-004`.
[ID_MAP.md](ID_MAP.md) lists every old ID with its new one; older pull requests and commits
use the old form.

```markdown
---
id: ENG-018
title: Make browser and dev-server test ports configurable for parallel agents
priority: P0            # P0 | P1 | P2
status: ready           # backlog | ready | in_progress | paused | in_review | blocked | done | superseded
type: chore             # epic | feature | bug | chore | docs | review | decision | research
parent:                 # optional epic ID
depends_on: []          # ticket IDs that must be done first
resources: [browser-test-harness]
risk: low               # low | medium | high | critical
size: S                 # XS | S | M | L | XL
agent_tier: any         # any | standard | frontier
gate: none              # none | owner
gate_approval:          # set only when the owner approved, e.g. "owner 2026-11-05, scope as written"
review: self            # self | independent
branch:                 # set when work starts
pr:
spec:                   # optional link to a tracked document this ticket depends on
spec_approved:          # set only when the owner approved the spec text: sha256:<hash from "tickets.py spec">
updated: 2026-11-05
---
```

The body must contain `## Goal`, `## Acceptance criteria`, `## Plan` and `## Handoff`;
`check` enforces these. A ticket written as a spec uses all of these, in this order:

- `## Goal` (gated): the user outcome in two to five sentences.
- `## Context`: background, current behaviour, links and files to start from.
- `## Requirements` (gated): scope, non-goals, and the rules and invariants the
  result must keep.
- `## Acceptance criteria` (gated): verifiable checkboxes, each starting with an ID
  `AC-<ticket>-NN`. Add `[review]` after the ID when only a reviewer can judge it.
- `## Build plan`: the design a builder follows (below).
- `## Plan`: checkbox steps small enough for one session each.
- `## Decisions needed`: required when `status: blocked`. Each question gives options
  and a recommendation. Only the owner answers.
- `## Handoff`: the resume point (format below).
- `## Log`: append-only dated lines, `YYYY-MM-DD agent: what happened`.

Older tickets without Requirements or acceptance IDs stay valid until they are
migrated (ENG-113).

### Writing a ticket as a spec

The full rules are in [spec-development.md](../docs/spec-development.md#the-ticket-is-the-spec).
In short:

- **The ticket is the spec.** Anything a builder needs is in the ticket or in a
  tracked document it links. Never rely on an untracked or ignored file.
- **Gated sections.** Goal, Requirements and Acceptance criteria are what the owner
  approves. `python3 scripts/tickets.py spec <ID>` prints their hash. When the owner
  approves the text, record their words in `gate_approval` and the hash in
  `spec_approved`. Changing a gated section afterwards makes the ticket unclaimable
  until the owner approves the new hash. Ticks, Context, Build plan, Plan, Handoff
  and Log can change freely.
- **Approvals and plans live on `main`.** Build a ticket from its copy on `main`;
  `spec_approved` and the Build plan arrive there through a merged pull request.
  Changing `agent_tier`, `risk`, `review`, `depends_on` or `resources` of an approved
  ticket needs the owner's confirmation in its Log.
- **Build plan.** The planner writes one for every ticket, of every tier, once the
  ticket's dependencies have merged, from the merged code. Its depth follows the
  [tier](#capability-tiers). It merges to `main` before a build is claimed; no ticket
  is planned and built in one session. `python3 scripts/tickets.py next --plan`
  lists tickets that need one. `next` marks a ticket of any tier without one
  `no build plan`; a builder skips it and reports it as needing planning. Only one planning session works at a time. It
  plans one or more tickets on its own branch from `origin/main` without claiming
  them, edits only their Context, Build plan, Plan and Decisions needed (the planning
  exception to the rule below), marks any proposed change to a gated section for the
  owner, records the plan PR in each ticket's Log and opens one docs pull request.
  Template:

```markdown
## Build plan

- Based on: the `main` commit this plan was written from.
- Files: `path/to/file.py`: what changes. `path/to/new.tsx` (new): what it holds.
- Interfaces: the signatures and data shapes the code must use, from merged code.
- Tests: `tests/test_x.py`, one case per acceptance ID:
  | AC | Case | Expected |
  |---|---|---|
  | 01 | Given 0.010 and 0.020 BTC | 0.03000000 BTC |
- Do not touch: paths, contracts and behaviour outside this ticket.
- Stop and ask if: the conditions that need a planner or owner decision.
```

- **Traceability.** Name the acceptance ID in each test that verifies it (test name,
  docstring or comment). `spec <ID>` counts the test files that mention each ID.
  Reviewers give a verdict per ID.

### Handoff format

Keep it current. Overwrite it at each checkpoint; the Log keeps history.

```markdown
## Handoff
- State: what is done and committed, what is uncommitted and why.
- Next step: the single next action, specific enough to start without re-reading everything.
- Verify: exact commands that prove the current state (tests, checks).
- Gotchas: traps found so far (sandbox limits, flaky tests, environment needs).
- Open questions: anything waiting on the owner (mirror into Decisions needed).
```

## Rules that keep the board consistent

- **Edit only your own ticket file** in a ticket branch. To change another ticket,
  for example to file a follow-up, create a new ticket file, or note it in your
  Handoff for the owner. This keeps parallel PRs from conflicting.
- **New tickets:** copy an existing file. Pick the area prefix from the table above, then
  use the next free number in that area (101 and above; 001 to 024 are the original V2
  plan), or the next free letter under its epic. `python3 scripts/tickets.py check`
  catches duplicate IDs and broken dependencies after a merge.
- **Gates:** `gate: owner` tickets need `gate_approval` before work starts. Only the
  owner grants it, in conversation with an agent, and the agent records the date and
  scope. Never infer approval from priority, a roadmap or a passed test. For a
  ticket written as a spec, also record the approved hash in `spec_approved`, and
  only when the owner approved that exact text. Any change to `gate_approval` or
  `spec_approved`, including clearing it, quotes the owner's words in the Log; the
  script cannot tell who approved, so the owner checks this at review.
- **Reviews:** `review: independent` means a different agent session than the
  implementer reviews the diff against the acceptance criteria. The same session
  cannot self-certify. Using a different model is welcome but does not by itself
  count as independence. The implementer starts this review itself, without
  being asked, once the work is pushed and before it hands the PR to the owner:
  1. Start a reviewer with a fresh context (a subagent or a separate session) on
     the reviewer model; in Claude Code that is the `reviewer` agent. Give it the
     ticket file, the diff against the base branch and the repository rules. Do
     not give it your conversation or your reasoning.
  2. The reviewer follows `.agents/skills/kurafolio-qa-automation/SKILL.md` on
     every ticket. For `risk: high` or `critical`, a second reviewer follows
     `.agents/skills/kurafolio-software-architect/SKILL.md`. For a ticket that
     changes a page or user-facing wording, one reviewer also checks it against
     [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md) with
     `.agents/skills/kurafolio-fintech-pm/SKILL.md`.
  3. The reviewer gives a verdict for each acceptance criterion, runs the Verify
     commands it can, and lists what it could not check. It does not edit the
     branch. Its findings go on the PR as a comment and in one ticket Log line.
  4. The implementer fixes or answers every finding and reports the result under
     "Independent QA / Architecture Review" in the PR description. Open findings
     are listed there, not hidden.
  5. If the tool cannot start a reviewer on the reviewer model (Codex and OpenCode
     cannot), write "NOT RUN" with the reason in the PR and the Handoff, and ask the
     owner to say "review <ID>" in Claude Code. A `frontier` ticket waits for that
     review before the owner's. Never describe your own checks as independent review.
  The owner reviews last, on GitHub, and is the only one who merges.
- **Squash merge:** every PR lands on `main` as one squashed commit, so a branch's
  WIP and Handoff commits stay off the main history. While a PR is open, bring in
  newer `main` with `git merge origin/main`, never a rebase, because agents do not
  force-push. Once a PR is merged, its branch is finished: do not push more commits
  to it. Repairs and follow-ups start a new branch from `origin/main`, under a new
  ticket where one is needed.
- **Public repository:** ticket text is public. Never write credentials, financial
  data, account names, personal paths or private approval transcripts. Detailed
  private evidence stays under ignored `work/`; reference it only by a relative path.
- **Done** means the PR is merged by the owner, required CI passed, and the
  capability docs are truthful. Agents never merge, force-push or deploy.

## Script reference

| Command | Purpose |
|---|---|
| `check` | Validate every ticket file (fields, enums, dependencies, cycles, sections, privacy). Runs in the test suite. |
| `list [--priority P0] [--status ready] [--all]` | Board with live claims. |
| `next [--tier any\|standard\|frontier]` | Claimable or resumable tickets of every tier; `--tier` narrows the list. A ticket of any tier without a Build plan is marked `no build plan`. |
| `next --plan` | Ready tickets of every tier that still need a Build plan. |
| `spec ID [--base REF]` | Spec hash, approval state, Build plan presence and each acceptance ID with its test mentions; with `--base`, whether the gated sections differ from that ref. Exits 1 when the spec changed since approval. |
| `show ID` / `resume ID` | Ticket text (newest copy from its branch), claim and git state. |
| `claim ID --agent NAME [--worktree]` | Atomic claim plus resource locks; writes `work/agent-claim.json` in the worktree. |
| `heartbeat ID [--note TEXT]` | Refresh the claim from the owning worktree. |
| `takeover ID --agent NAME [--worktree] --reason TEXT` | Take a stale claim; records the previous owner. |
| `release ID` | Drop the claim and its resources. |
| `cleanup [--base origin/main] [--dry-run]` | Remove merged ticket worktrees and their local branches (see below). |

`cleanup` only touches worktrees under `work/worktrees/`. It removes one when its
branch has landed on the base, it has no uncommitted or untracked changes and no
live claim. A branch has landed when the base reached its tip through a merge
commit, or when it was squash- or rebase-merged: it changes something, and merging
it into the base now would not change the base. It also releases a stale claim on
that worktree. It keeps the worktree you run it from, a branch with changes that are
not on the base yet, a branch with no net changes, and a new branch that still
points at the base tip. If `main` later edited the same lines as a squash-merged
branch, that branch is kept too; check its PR is merged and remove it by hand.
Ignored files inside a removed worktree, such as `node_modules/` or `work/`
evidence, are deleted with it, so move anything you still need first. Run
`git fetch origin` before it so the base is current.

Agent names use `tool/model`. Use the board names in
[AGENTS.md](../AGENTS.md#models-and-roles), for example `claude-code/sonnet-5.5`,
`codex/gpt-6.1-sol` or `opencode/deepseek-flash`. The board uses them to show who is working.
