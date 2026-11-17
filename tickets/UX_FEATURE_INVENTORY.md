# UI/UX feature inventory and ticket coverage

Built on 2026-11-10 at `main` commit `b771301`. One row per screen and per
user-facing feature. Every row ends in a ticket or in "no change needed".
[TICKET_CHANGES.md](TICKET_CHANGES.md) lists what was written and the batches.

## How it was built

- Read the frontend (`frontend/src`), every HTTP route of both backends
  (`src/kurafolio/web/`, `src/kurafolio/web_v2/`), the product and design
  documents and all tickets.
- Ran the repository's disposable synthetic server (`scripts/web_browser_fixture.py`)
  on 2026-11-09 and 2026-11-10 and visited every page of the shipped application:
  a populated, an empty and a source-pipeline portfolio; 1024x768 and 375x812;
  dark and light themes; English and Traditional Chinese; reload, navigation,
  an unknown page and an unknown portfolio. Only invented data was used.
- Evidence marks: **V** observed in the running application, **S** read in source,
  **D** from documents.

Not run: the V2 backend (needs an opt-in PostgreSQL environment; it has no UI),
the Playwright suite (the audit sandbox cannot start a headless browser), a
screen reader, and Simplified Chinese page by page (catalog parity was checked:
499 keys in each of the three catalogs). V2 rows are therefore **S** or **D**.

Disposition: KEEP, IMPROVE, SIMPLIFY, CONSOLIDATE, COMPLETE, REMOVE, BUILD.

## Shipped application (SQLite, `/api/v1`)

| Screen / feature | User goal | Works today | Problems found | Missing capability | Tickets | Disposition |
|---|---|---|---|---|---|---|
| Sign-in | Enter the instance | Yes (V) | Decorative text stays English in zh-TW (V, `App.tsx:212-218`); raw error code after the message (S, `App.tsx:226-228`) | In-browser recovery (host only by design) | APP-107 | IMPROVE |
| Session expiry and sign-out | Leave safely | Yes (S, browser suite) | None | None | no change needed | KEEP |
| Shell and navigation, desktop | Reach nine pages | Yes (V) | Nine destinations; V2 reduces to eight | None | APP-011A | KEEP until cutover |
| Shell and navigation, phone | Reach content on a phone | Poorly (V) | Content starts at 380 px, value at 989 px; three of nine destinations visible; 37 px targets | Compact menu | APP-108 | IMPROVE |
| Unknown page or portfolio | Understand a wrong link | No (V) | Unknown page renders Overview; unknown portfolio offers a useless retry | Not-found states | APP-110 | IMPROVE |
| Interface language | Read in my language | Partly (V) | Reset to English on every load (`main.tsx:25`) | Persistence, browser default | APP-106 | IMPROVE |
| Appearance (light, dark, system) | Comfortable reading | Yes (V) | None | None | no change needed | KEEP |
| Display currency | See CAD, USD or TWD | Partly (V) | Survives navigation; resets on reload (`App.tsx:299`); offered on three pages only | Persistence | APP-105 | IMPROVE |
| Report edition selector | Read an earlier edition | Partly (V) | Selection lost on every sidebar navigation (`App.tsx:396`); hash-like labels | Carry selection; notice | APP-105 | IMPROVE; REMOVE in V2 |
| Time display | Know when | Yes (V) | Fixed to Toronto (`lib/format.ts:52`, `chart-view.tsx:115`, seven core modules) | Configurable zone | CORE-101, APP-011E | IMPROVE |
| Portfolio selector and creation | Separate ledgers | Yes (V) | No rename or delete | None wanted: V2 has one portfolio | APP-011A removes it | REMOVE (V2) |
| First-run guide | Know what to prepare | Yes (V) | Full guide repeated on four other pages under an inert currency selector | Short pointer | APP-110 | SIMPLIFY |
| Overview | What is it worth | Yes (V) | Value followed by two screens of evidence panel (`analysis.tsx:60`) | Value-first layout | APP-104; ANL-012D | SIMPLIFY |
| Value chart | See change over time | Broken with one observation (V) | Eight repeated axis labels (`chart-view.tsx:105-118`) | None | ANL-111 | IMPROVE |
| Evidence status and next steps | Know what is uncertain | Yes (V) | Raw check code shown (`lib/evidence-status.ts:182`) | Localized titles | APP-107, APP-104 | SIMPLIFY |
| Holdings | See positions | Yes (V) | Cash rows as securities; native and display currency mixed; one account label in the wrong language (`web/reports.py:259`) | Cash table; labelled columns | ANL-110, APP-107; ANL-012B | IMPROVE |
| Exposure and ETF look-through | Underlying companies, sectors, countries | Yes (V) | Heading repeated as caption | Denominator choice (V2) | RPT-103; ETF-010, ANL-012E | KEEP |
| History | Value by observation | Yes (V) | Same chart defect | Ranges (ANL-107) | ANL-111 | IMPROVE |
| Bitcoin and flows | BTC quantity and cost | Yes (V) | Provider-specific wording; funding and cash flows mixed in | Generic acquisition view | ANL-012C (V2); no change on the shipped page | SIMPLIFY (V2) |
| Import: upload, preview, confirm | Add an observation | Yes (V, browser suite) | Typed ISO timestamps (`imports.tsx:507,521`); step 3 current on arrival (`:170-176`); duplicate introduction; identical job rows | Pickers; truthful steps | IMP-105, IMP-106; APP-011D | IMPROVE |
| Import recovery (stale, uncertain, resume) | Recover safely | Yes (S, browser suite) | None found | None | no change needed | KEEP |
| Financial records (declarations) | Record BTC totals, events, cash flows | Yes (V) | Seven record types on one form; typed timestamps | None wanted: V2 drops it from navigation | IMP-105 (timestamps only) | RECONSIDER; REMOVE from V2 navigation |
| Report reader | Read a saved edition | Yes (V) | Downloads labelled by file name; attachment captioned by file name | Descriptive labels | RPT-103 | KEEP |
| Report downloads and data export | Take files away | Yes (V) | None beyond labels | On-demand export (V2) | RPT-013A, RPT-013B | KEEP; becomes on demand |
| Settings | Report language, BTC cost policy, password | Yes (V) | One new-password field; unrelated closing sentence | Confirmation | APP-110 | IMPROVE |
| Backup, restore, adoption | Protect data | Yes, host commands (D) | Not discoverable in the UI | UI entry points | OPS-105 | KEEP |
| Headings and table names | Scan by structure | Partly (V) | Heading repeated as hidden caption on four panels | None | RPT-103 | IMPROVE |
| Locales (three) | Use the product in my language | Yes (V, parity checked) | See language and labels rows | More locales | APP-101 | KEEP |

## V2 (PostgreSQL, `/api/v2`): planned screens

| Screen / feature | User goal | Backend today | UI today | Tickets | Disposition |
|---|---|---|---|---|---|
| Bundle delivery | Open V2 in a browser | No HTML or asset route (S, `web_v2/api.py:26-38`) | None | APP-011G | BUILD |
| Shell, eight destinations, phone menu, not-found | Find everything | n/a | None | APP-011A | BUILD |
| First setup, registration by invitation, sign-in | Get an account | Merged (S, `web_v2/api.py:310-346`) | None | APP-011B | BUILD |
| Invitation management | Admin invites people | Merged (S, `:361-377`) | None | APP-011B | BUILD |
| Parser Plugin Store: enable, connections | Choose my institutions | Merged, explicit profile (S, `:412-437`) | None | APP-011C | BUILD |
| Import Data: upload, review, confirm, history | Add data | SQL about half merged; no routes (D) | None | IMP-007E (routes), APP-011D (UI) | BUILD |
| Preferences: language, time zone, currency | Same settings on every device | Missing: `Me` has none (S, `schemas.py:109-112`) | None | APP-011E | BUILD |
| Profile and App Settings pages | Manage my account and defaults | Password change exists (S, `:346`) | None | APP-011F | BUILD |
| Analysis read contract | Consistent numbers | Missing (S) | n/a | ANL-012A | BUILD |
| Stock/Bond page and shared toolbar (currency, refresh, download) | See securities now | Needs 012A | None | ANL-012B | BUILD |
| Crypto page | See acquired Bitcoin | Needs 012A | None | ANL-012C | BUILD |
| Total page and Home | Combined picture; where to go next | Needs 012A | None | ANL-012D | BUILD |
| Exposures page | Underlying concentration | Contract in ETF-010 | None | ANL-012E | BUILD |
| Price and FX refresh | Current values | Missing | Toolbar control in 012B | MKT-009 | BUILD |
| Download panel | Take a report away | Needs 013A | None | RPT-013A, RPT-013B | BUILD |
| Legacy report archive | Read my earlier reports after migration | Not defined | Reader exists in the shipped app | RPT-020 | BUILD |
| ETF search for unheld funds | Look up any ETF | Missing | None | ETF-101 | BUILD later |
| API source connection | Sync without CSV | Missing | None | PLG-102 | BUILD later |
| Plugin authoring guide | Add an institution | SDK exists | Link from the Parser Plugin Store | PLG-101, APP-011C | BUILD later |
| Drill-downs, targets, overlap | Deeper analysis | Missing | None | ANL-106, ANL-107, ANL-101 | BUILD later |
| Page-level mobile layout, balance privacy | Use on a phone in public | n/a | None | APP-109 | BUILD later |
| Operations and account security UX | Back up from the app | Host commands | None | OPS-105 | BUILD later |
| Activity, performance, income, risk, goals, tax exports | Returns and planning | Out of the approved baseline | None | ANL-103, ANL-104, ANL-105, ANL-108, ANL-109, RPT-102 (all wait on ANL-102) | Deferred by decision |

## User journeys

| Journey | Steps | Covered by |
|---|---|---|
| Evaluate before installing | README, screenshots | OPS-103 (synthetic demo) |
| Install and first sign-in (shipped) | Source build, host owner setup | OPS-104 (pull-only install, after V2 release) |
| First import (shipped) | Import page, preview, confirm, open report | IMP-105, IMP-106 |
| Read the result (shipped) | Overview, Holdings, Exposure, History, Bitcoin, Reports | APP-104, APP-105, ANL-111, APP-107; ANL-110, RPT-103 |
| Return next month (shipped) | Sign in, import, compare editions | APP-105, APP-106 |
| Use on a phone (shipped) | Any page at 375 px | APP-108 |
| Recover from a wrong link or typo | Not-found, password change | APP-110 |
| V2: invitation to first analysis | Register, sign in, enable a source, import, see Stock/Bond | APP-011G, 011A, 011B, 011C, 011D, 012A, 012B |
| V2: add Bitcoin and see the total | Import orders, Crypto, Total, Home | ANL-012C, 012D |
| V2: refresh and download | Refresh prices, download PDF | MKT-009, 012B, 013A, 013B |
| V2: set language, zone and currency | Profile | APP-011E, 011F |
| V2: migrate and keep old reports | Cutover, archive | OPS-014, RPT-020 |

## Coverage check

Every row above names at least one ticket or "no change needed". Rows marked
"no change needed": session expiry and sign-out, appearance, import recovery,
and the shipped Bitcoin page (replaced in V2, left alone meanwhile).

Known limits of this inventory: V2 rows describe intended screens, not observed
ones; the V2 import routes are not built, so APP-011D's field-level detail
waits on IMP-007E; contrast and screen-reader behaviour were not measured.
