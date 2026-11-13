# Ticket IDs by area

Ticket IDs changed on 2026-11-13 from `WL-P<priority>-<number>` and `UX-P<priority>-<number>` to
`<AREA>-<number>`. The old prefix named the project before it was called Kurafolio, and the priority inside
the ID went stale whenever a ticket was re-ranked. The `priority` field is now the only place a priority lives.

Pull requests, commits and review comments from before that date use the old IDs. Use the table below to
find a ticket from an old reference. The acceptance labels of the import contract (`AC-WL-P0-007-01` and
similar) and the file names in the owner's local planning package are names inside those documents and
were not changed.

## Areas

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

## Numbers

- 001 to 024 are the tickets of the original V2 plan. They kept their number, so the old `WL-P0-007D` is
  `IMP-007D` and the short forms people already use ("007D", "012A") still point at the same ticket. These
  numbers are unique across all areas. A lettered child stays in its epic's area even where its own work
  leans toward another area (for example `APP-011E`, the preferences API under the screens epic).
- 101 and above are numbered within each area. A new ticket takes the next free number in its area, or the
  next free letter under its epic.

## Old to new

| New ID | Old ID |
|---|---|
| ANL-008 | WL-P0-008 |
| ANL-012 | WL-P0-012 |
| ANL-012A | WL-P0-012A |
| ANL-012B | WL-P0-012B |
| ANL-012C | WL-P0-012C |
| ANL-012D | WL-P0-012D |
| ANL-012E | WL-P0-012E |
| ANL-101 | WL-P1-004 |
| ANL-102 | WL-P2-002 |
| ANL-103 | UX-P1-001 |
| ANL-104 | UX-P1-002 |
| ANL-105 | UX-P1-003 |
| ANL-106 | UX-P1-004 |
| ANL-107 | UX-P1-005 |
| ANL-108 | UX-P2-001 |
| ANL-109 | UX-P2-002 |
| ANL-110 | UX-P2-006 |
| ANL-111 | UX-P1-011 |
| APP-011 | WL-P0-011 |
| APP-011A | WL-P0-011A |
| APP-011B | WL-P0-011B |
| APP-011C | WL-P0-011C |
| APP-011D | WL-P0-011D |
| APP-011E | WL-P0-011E |
| APP-011F | WL-P0-011F |
| APP-011G | WL-P0-011G |
| APP-011H | WL-P0-011H |
| APP-011I | WL-P0-011I |
| APP-101 | WL-P2-004 |
| APP-102 | UX-P0-001 |
| APP-103 | UX-P0-002 |
| APP-104 | UX-P1-008 |
| APP-105 | UX-P1-009 |
| APP-106 | UX-P1-010 |
| APP-107 | UX-P1-012 |
| APP-108 | UX-P1-015 |
| APP-109 | UX-P2-003 |
| APP-110 | UX-P2-007 |
| AUTH-005 | WL-P0-005 |
| AUTH-101 | WL-P1-013 |
| AUTH-102 | WL-P1-017 |
| AUTH-103 | WL-P2-010 |
| CORE-003 | WL-P0-003 |
| CORE-004 | WL-P0-004 |
| CORE-101 | WL-P1-007 |
| ENG-002 | WL-P0-002 |
| ENG-016 | WL-P0-016 |
| ENG-017 | WL-P0-017 |
| ENG-018 | WL-P0-018 |
| ENG-019 | WL-P0-019 |
| ENG-022 | WL-P0-022 |
| ENG-023 | WL-P0-023 |
| ENG-024 | WL-P0-024 |
| ENG-101 | WL-P1-005 |
| ENG-102 | WL-P1-006 |
| ENG-103 | WL-P1-008 |
| ENG-104 | WL-P1-009 |
| ENG-105 | WL-P1-010 |
| ENG-106 | WL-P1-011 |
| ENG-107 | WL-P1-012 |
| ENG-108 | WL-P1-020 |
| ENG-109 | WL-P2-003 |
| ENG-110 | WL-P2-006 |
| ENG-111 | WL-P2-009 |
| ETF-001 | WL-P0-001 |
| ETF-010 | WL-P0-010 |
| ETF-010A | WL-P0-010A |
| ETF-010B | WL-P0-010B |
| ETF-101 | WL-P1-002 |
| ETF-102 | WL-P1-015 |
| ETF-103 | WL-P2-011 |
| IMP-007 | WL-P0-007 |
| IMP-007A | WL-P0-007A |
| IMP-007B | WL-P0-007B |
| IMP-007C | WL-P0-007C |
| IMP-007D | WL-P0-007D |
| IMP-007E | WL-P0-007E |
| IMP-007F | WL-P0-007F |
| IMP-007G | WL-P0-007G |
| IMP-007H | WL-P0-007H |
| IMP-007I | WL-P0-007I |
| IMP-007J | WL-P0-007J |
| IMP-007K | WL-P0-007K |
| IMP-007L | WL-P0-007L |
| IMP-007M | WL-P0-007M |
| IMP-007N | WL-P0-007N |
| IMP-101 | WL-P1-016 |
| IMP-102 | WL-P2-005 |
| IMP-103 | WL-P2-008 |
| IMP-104 | UX-P0-003 |
| IMP-105 | UX-P1-013 |
| IMP-106 | UX-P1-014 |
| MKT-009 | WL-P0-009 |
| MKT-009A | WL-P0-009A |
| MKT-009B | WL-P0-009B |
| MKT-009C | WL-P0-009C |
| MKT-009D | WL-P0-009D |
| MKT-009E | WL-P0-009E |
| OPS-014 | WL-P0-014 |
| OPS-015 | WL-P0-015 |
| OPS-021 | WL-P0-021 |
| OPS-101 | WL-P1-018 |
| OPS-102 | WL-P1-019 |
| OPS-103 | WL-P2-007 |
| OPS-104 | UX-P1-007 |
| OPS-105 | UX-P2-004 |
| PLG-006 | WL-P0-006 |
| PLG-101 | WL-P1-003 |
| PLG-102 | WL-P1-001 |
| PLG-103 | WL-P2-001 |
| PLG-104 | UX-P1-006 |
| RPT-013 | WL-P0-013 |
| RPT-013A | WL-P0-013A |
| RPT-013B | WL-P0-013B |
| RPT-020 | WL-P0-020 |
| RPT-101 | WL-P1-014 |
| RPT-102 | UX-P2-005 |
| RPT-103 | UX-P2-008 |
