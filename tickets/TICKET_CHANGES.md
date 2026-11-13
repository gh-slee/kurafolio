# Ticket changes from the UI/UX backlog pass (2026-11-10)

Source of the changes: [UX_FEATURE_INVENTORY.md](UX_FEATURE_INVENTORY.md).
All new tickets are `status: backlog`, so `tickets.py next` does not offer them
until the owner releases them. No `gate_approval` was filled in. No done,
claimed, in-progress or in-review ticket was edited (ENG-102, IMP-007,
ENG-017 and ENG-018 are untouched).

## Update after the owner's answers (same day)

The owner decided to put all effort into V2 and not change the shipped application. The eleven shipped-application tickets (APP-104, APP-105, APP-106, ANL-111, APP-107, IMP-105, IMP-106, APP-108, ANL-110, APP-110, RPT-103) are now `superseded`; each names the V2 ticket that carries its finding. Batches 1 to 3 below no longer apply. The owner's answers and the recommendations still awaiting confirmation are in [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md).

Later the same day the owner confirmed the decisions listed in PRODUCT_CONTEXT.md and asked for a V2 MVP first. ANL-008, MKT-009, APP-011B and ANL-012A gained an "Owner decisions" block; OPS-021 (one-command V2 MVP deployment) and MKT-009A (quote adapter contract and optional unofficial adapter) were added, for 31 created tickets and 91 on the board. The MVP order is in ROADMAP.md.

A CI and end-to-end review added ENG-022, ENG-023, ENG-105 and ENG-111 (see CI_E2E_ASSESSMENT.md), for 35 created tickets and 95 on the board. The owner then answered IMP-007J and the APP-011A, 011G and 009A decisions.

## Counts

| | P0 | P1 | P2 | Total |
|---|---|---|---|---|
| Created | 12 | 11 | 6 | 29 |
| Improved in place | 8 | 1 | 1 | 10 |
| Of the improved: split into children | 2 (ANL-012, RPT-013) | | | 2 |
| Merged | 0 | 0 | 0 | 0 |
| Recommended for closure | 0 | 0 | 1 (IMP-102) | 1 |

The board now holds 89 tickets.

## Created

### Shipped application

| ID | Pri | Type | Gate | Title | Why |
|---|---|---|---|---|---|
| APP-104 | P1 | feature | owner | Lead the Overview with the value and collapse evidence detail | Value is followed by two screens of evidence panel |
| APP-105 | P1 | bug | none | Keep the selected edition while navigating and the currency across reloads | Edition silently lost on every sidebar click |
| APP-106 | P1 | feature | none | Remember the interface language | Resets to English on each load |
| ANL-111 | P1 | bug | none | Fix the value chart time axis with few observations | First chart of every new portfolio shows repeated labels |
| APP-107 | P1 | bug | none | Every label in the selected language; no internal codes | Wrong-language labels, raw check code, English sign-in text |
| IMP-105 | P1 | feature | owner | Date, time and zone controls instead of typed ISO timestamps | Users must type a UTC offset |
| IMP-106 | P1 | bug | none | Import page: right step, one introduction, distinguishable jobs | Step 3 current on arrival; identical job rows |
| APP-108 | P1 | feature | owner | Compact mobile navigation for the current shell | Content starts 380 px down on a phone |
| ANL-110 | P2 | feature | owner | Separate cash from securities; label money columns | Cash shown with average cost and P/L |
| APP-110 | P2 | bug | none | Tidy empty, not-found and settings states | Unknown page shows Overview; no password confirmation |
| RPT-103 | P2 | bug | none | Remove repeated headings; descriptive download names | Headings read twice; downloads named by file |

### V2 screens and their contracts

| ID | Pri | Type | Gate | Title | Why |
|---|---|---|---|---|---|
| APP-011E | P0 | feature | owner | User preferences in the V2 identity API | Profile needs language, zone and currency; the API stores none |
| APP-011F | P0 | feature | owner | App Settings and Profile pages | Two of eight destinations had no ticket |
| APP-011G | P0 | feature | owner | Serve the frontend bundle from the V2 backend | V2 has no HTML or asset route |
| ANL-012A | P0 | feature | owner | Analysis read contract | Split from ANL-012 |
| ANL-012B | P0 | feature | owner | Stock/Bond page and shared toolbar | Split from ANL-012 |
| ANL-012C | P0 | feature | owner | Crypto page | Split from ANL-012 |
| ANL-012D | P0 | feature | owner | Total page and Home | Split from ANL-012 |
| ANL-012E | P0 | feature | owner | Exposures page | ETF-010 delivers the data; nothing built the page |
| RPT-013A | P0 | feature | owner | Render exports on demand | Split from RPT-013 |
| RPT-013B | P0 | feature | owner | Download panel | Split from RPT-013 |
| ENG-019 | P0 | decision | owner | V2 delivery order and first-release hardening scope | No ticket is claimable; the path is long and serial |
| RPT-020 | P0 | feature | owner | Legacy report archive in the V2 app | Migrated users would lose access to earlier reports |

### Supporting

| ID | Pri | Type | Gate | Title |
|---|---|---|---|---|
| CORE-101 | P1 | research | owner | Configurable time zone for display and month grouping |
| ENG-103 | P1 | chore | owner | Board drift and readiness check (`tickets.py doctor`) |
| ENG-104 | P1 | chore | owner | Owner inbox of open gates and decisions |
| ENG-110 | P2 | chore | owner | Python lint gate for new and changed code |
| OPS-103 | P2 | feature | owner | One-command synthetic demo instance |
| IMP-103 | P2 | research | owner | Retirement plan for superseded import paths |

## Improved in place

Each keeps its ID, status, gate and history and has a dated Log line.

| ID | Change |
|---|---|
| APP-011 | Plan lists all seven children, including new 011E, 011F, 011G |
| APP-011A | Current behaviour with file evidence; routes; coexistence and serving decisions; measurable phone, not-found and persistence criteria |
| APP-011B | Identity routes and DTOs named; per-screen behaviour; password, recovery wording and invitation states |
| APP-011C | Source routes and DTOs named; a plain list, not a storefront; conflict and confirmation states |
| APP-011D | Step-by-step target flow; criteria from defects seen in the shipped import page |
| ANL-012 | Now the epic of 012A to 012E; `type: epic`, no resources; criteria unchanged |
| RPT-013 | Now the epic of 013A and 013B; `type: epic`, size L; criteria unchanged |
| ETF-010 | States that it delivers the exposure contract and that the page is 012E; names the code to port |
| APP-109 | Mobile shell moved to APP-011A and APP-108; keeps page-level layout and balance privacy |
| ENG-101 | Covers all eleven open UX tickets that say "refreshed for V2", not two |

## Recommended, not done

These need the owner or touch tickets this pass must not edit.

| Ticket | Recommendation | Why not done here |
|---|---|---|
| IMP-102 | Close: saves one upload click, adds a watcher and a trust boundary | Closing is the owner's call |
| ENG-017, ENG-018 | Mark `done`; both are merged (PR #30, PR #34) | In review; PR #37 already flips 018 |
| IMP-007K | Fold into IMP-007C | The ticket asks the owner this question itself |
| IMP-007D, 007E, 007F | Add dependencies on 007J, 007K, 007L | Backend order; inferred from ticket text, needs an architect |
| MKT-009, OPS-014, IMP-007F | Split | Backend scope, outside a UI/UX pass |
| APP-011, 011A, 016 | `ready` with an unapproved gate is misleading | Status changes belong to the owner |

## Owner decisions that block tickets

Most blocking first.

1. ENG-019: delivery order and first-release hardening. Informs everything in V2.
2. Gate A on APP-011, and whether it covers 011E, 011F, 011G and the 012 and 013 children.
3. APP-011A decisions: one bundle with two shells, and serving the bundle from the V2 app (APP-011G).
4. APP-011E: which preferences live on the server; whether a session list is in the first release.
5. ANL-012A: whether a thin first version may value securities from the import's own market values.
6. Whether to invest in the shipped UI: APP-104, IMP-105, APP-108, ANL-110.
7. RPT-020: where archived editions are served.
8. CORE-101: scope and default of the time zone setting.
9. Workflow and tooling: ENG-103, ENG-104, ENG-110, OPS-103.
10. Release of the ungated tickets: APP-105, APP-106, ANL-111, APP-107, IMP-106; APP-110, RPT-103.

## Execution batches

A row is a lane. Lanes in one batch share no exclusive resource and have no
dependency between them. The three locale catalogs are one resource
(`frontend-i18n`), so tickets that add many strings run one after another.

### Batch 1: releasable today without a design decision

| Lane | Ticket | Tier | Resources |
|---|---|---|---|
| Shell | APP-105 | standard | frontend-shell |
| Charts | ANL-111 | standard | frontend-charts |
| Labels | APP-107 | standard | web-report-view, frontend-analysis, frontend-i18n |

### Batch 2

| Lane | Ticket | Tier | Resources |
|---|---|---|---|
| Shell | APP-106 | any | frontend-shell |
| Imports | IMP-106 | standard | frontend-imports-ui, frontend-i18n |
| Workflow (after its gate) | ENG-103, then ENG-104 | standard, any | public-docs-agent-rules |

### Batch 3: after the owner's answer on the shipped UI

Serial on `frontend-i18n`: APP-104, IMP-105, APP-108, then ANL-110,
APP-110, RPT-103. APP-108 and APP-110 also need `frontend-shell`, so
finish them before APP-011A starts.

### Batch 4: V2 screens, after Gate A

| Step | Tickets | Parallel |
|---|---|---|
| 1 | APP-011A (shell); APP-011E (preferences); APP-011G (serving) | Yes: three different resources |
| 2 | APP-011B; APP-011C; APP-011F | Yes: identity, sources and settings UI resources |
| 3 | APP-011D | After IMP-007E |
| 4 | ANL-012A | After ANL-008 and MKT-009 |
| 5 | ANL-012B, then 012C, then 012D; 012E after ETF-010 | Serial on frontend-analysis and frontend-i18n |
| 6 | RPT-013A, then RPT-013B | Serial |
| 7 | RPT-020 | After OPS-014 |

### Shared files to watch

| File | Tickets | Handling |
|---|---|---|
| `frontend/src/locales/*.json` | every UI ticket | `frontend-i18n` lock; keys in a block named for the ticket |
| `frontend/src/App.tsx` | APP-105, APP-106, APP-108, APP-110, APP-011A | `frontend-shell` lock; shipped-shell tickets first |
| `frontend/src/components/analysis.tsx` | APP-104, APP-107, ANL-110, RPT-103 | `frontend-analysis` lock |
| `frontend/src/components/imports.tsx` | IMP-105, IMP-106 | `frontend-imports-ui` lock |
| `src/kurafolio/web_v2/schemas.py`, `api.py` | APP-011E, 011G, 012A, 013A, IMP-007E | Different resources; rebase before the PR, DTO blocks are additive |
| Migration numbering | APP-011E, IMP-007D | `migration-order` lock |
| README screenshots | every UI ticket | Each ticket refreshes only its own page |

New resource names introduced: `web-report-view`, `frontend-reports-ui`,
`frontend-settings-ui`, `v2-frontend-serving`, `python-lint-config`. Resource
names are free text in the schema.

## What the tickets could not be given

- APP-011D cannot name request and response fields until IMP-007E defines them.
- V2 page tickets cite no observed behaviour, because no V2 page exists; they
  cite the nearest shipped page and its observed defects.
- Criteria that need a browser were written from observation, but the Playwright
  suite itself was not run during this pass.

## Post-MVP planning pass (2026-11-11)

Written after the owner asked for the post-MVP P0 tickets to be planned to the
same depth as the MVP tickets, and answered three questions.

| Ticket | Change | Why |
|---|---|---|
| MKT-009 | Became an epic | Too large for one agent; its provider decision blocked work that does not depend on it |
| MKT-009B | New | Market store, refresh process, refresh and status routes |
| MKT-009C | New | Display currency list and daily FX |
| MKT-009D | New | Daily value curve with carried-forward quantities marked as estimates |
| MKT-009E | New | Official keyed provider: spike, owner choice, adapter |
| ETF-010 | Became an epic | Reference data and the exposure calculation can be built separately |
| ETF-010A | New | Fund holdings in PostgreSQL, refreshed for held funds |
| ETF-010B | New | Exposure endpoint |
| ANL-012E | Dependency ETF-010 replaced by ETF-010B | Follows the split |
| OPS-014 | Rewritten, L and critical to S and medium | Owner: no data migration; import files again |
| OPS-015 | Detailed; one verified platform; depends on ENG-023 | Owner: Apple Silicon Mac with Docker Desktop |
| RPT-020 | P0 to P2, no longer depends on OPS-014 | Owner: old reports are read in the old application |
| OPS-021 | New criterion | Its pull request tells the owner when the MVP is usable |

The owner approved Gate A for MKT-009B to 009E, 010A, 010B, 014 and 015 on
2026-11-11, with the refresh intervals in 009B and the twelve currencies in 009C.
They are `ready` and are offered when their dependencies are done.

| Ticket | Change | Why |
|---|---|---|
| ENG-024 | New, ready; the owner chose the name Kurafolio | Owner: rename the project everywhere, no aliases, before parallel work starts |
| ENG-109 | Superseded by ENG-024 | The owner made the rename a priority |
| IMP-007C, 007J, 009A, 011A, 011G, 022 | Depend on ENG-024 | The rename touches about 290 files and must land first |
| ENG-106 | New, blocked on three owner decisions | A reviewer in CI on every pull request |
| ENG-107 | New | A browser test fails intermittently on unrelated changes |
| `AGENTS.md`, `tickets/README.md` | Reviews rule | The implementer starts fresh-context QA, Architect and PM review itself; the owner reviews last |

## Remaining P0 backlog released (2026-11-12)

| Ticket | Change | Why |
|---|---|---|
| APP-011E | Ready; decisions recorded | Owner: language, time zone and currency on the server; no session list |
| APP-011F, 012E, 013B, 023 | Ready; current-behaviour notes refreshed now that the V2 shell exists | Owner Gate A |
| APP-011H | Ready; adds `asset_classes` to the source catalog; depends on ANL-012A instead of 008 | Owner decision on how a page decides to offer "Enable a source" |
| RPT-013A | Ready; Excel added; data formats moved out | Owner: PDF, Excel, ODS and Markdown for go-live |
| RPT-101 | New, backlog | CSV, JSON, PNG and ZIP exports |
| ENG-022 | Ready | No gate; should land before more import SQL |
| IMP-007M | Ready for the options write-up | The owner still makes the decision |

