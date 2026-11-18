# Golden cases

These are the independent financial acceptance cases G01 to G19 from the V2 planning package. Tickets cite them by ID; this file is the tracked copy (ENG-114). The case IDs, inputs and expected values are copied exactly from the planning package. Only this introduction was added and one reference to an unpublished evidence file was reworded.

Tickets that rely on a case link this file with its SHA-256. Changing a case ID, an input or an expected value changes the spec of every ticket that cites the case, so those tickets need the owner's approval again before anyone builds against the new value. Add a new case under a new ID rather than editing an existing one.

## Independent financial acceptance cases

Revision 1, proposed QA oracle. Values below are invented, dimensioned, fixed examples derived from elementary arithmetic and requirements, not copied from production functions. Planned implementation tests are NOT RUN. A planning-only independent Decimal arithmetic check of the stated constants is recorded in the unpublished planning package. Future QA must approve inputs/oracle separately, then execute against the implementation and compare.

| Case | Inputs / action | Independently expected outcome | Layer / specs |
|---|---|---|---|
| G01 Snapshot replacement | Complete account scope: T1 A=10 B=5; newer complete T2 A=7 with B absent | T2 A=7 B=0, not A=17 B=5; T1 retained historically. Repeat T2 is unchanged. | Domain + PG; 003/007/008 |
| G02 Partial omission | Same T1; partial T2 lists A=7 only | Current listed A=7, B unresolved with last-seen 5/date; B not set to zero or added as current known value. Known subtotal excludes unresolved B. | Domain + UI; 007/008/012 |
| G03 Old/same-time correction | T3 full A=8 accepted; later upload T2 A=7; distinct T3 A=9 without supersession, then explicit correction | Old T2 never replaces T3; conflicting T3 blocks; approved correction yields A=9 with old head retained. | Contract/PG; 007 |
| G04 Duplicates vs legitimate twins | Event IDs x and y each BUY 0.010 BTC, equal time/amount; exact x reimport and overlapping export | x+y=0.020; reimport x adds zero. Missing-ID twins remain ambiguity, not a silent merge. | Domain/contract/PG; 006/007 |
| G05 Approved Option A | BUY x=0.010 and y=0.020 BTC; fixed price USD 60000, 1 USD=1.4 CAD=32 TWD | 0.030 BTC=3,000,000 sat; USD 1800.00, CAD 2520.00, TWD 57600.00. Included in Crypto and Total, no opening required. | Golden/API/E2E; 008/012 |
| G06 Transfer/snapshot/extra buy | G05 plus TRANSFER_IN 0.030 and balance snapshot 0.030; independent Kraken BUY 0.005 | Transfers/snapshot add zero; independent buy yields 0.035 BTC, USD 2100/CAD 2940/TWD 67200. Mirrored/ambiguous Kraken evidence is reviewed before adding. | Domain/PG; 007/008/P1-001 |
| G07 Combined valuation | Securities: 10×USD100 plus CAD800; G05 BTC | Securities CAD2200; combined CAD4720, USD3371.428571..., TWD107885.714285...; displayed 4720.00/3371.43/107885.71. Wealthsimple-only before Bull: CAD2200.00. | Golden/API/export; 008/009/012/013 |
| G08 Cost coverage | Acquisitions 0.010 for CAD700 and 0.020 for CAD1500, fees already included | Cost CAD2200; average CAD73333.333333.../BTC; at G05 value2520, estimated assumed-held difference320 and 14.545454...%. A missing cost makes full-pool result unavailable, not zero cost. | Golden/domain; 008 |
| G09 Missing quote/FX | G07 with unknown price for CAD800 asset, otherwise available; then missing FX USD->TWD | Known CAD3920 (USD stock1400+BTC2520), complete total null, one unknown asset; no 0-valued invented asset. Missing TWD path makes TWD complete total unknown without erasing CAD/USD facts. | Domain/API/UI; 009/012 |
| G10 Market refresh only | No new CSV; G05 quote changes USD60000->61000; same FX | BTC value CAD2520->2562 (+42) and Total +42, same quantity/fact revision, new reference/calculation generation; no inferred contribution. | API/worker/E2E; 009/012 |
| G11 Country TW and denominator | ETF CAD1000: US60%, TW30%, unknown8%, cash2%; direct TW stockCAD200; G05 BTC2520 | Country: US600, TW500, unknown80, cash20, direct crypto2520; sum3720. TW=41.6666...% securities1200 and 13.44086...% Total3720. Unknown never redistributed. | Golden/contract/chart; 001/010 |
| G12 ETF recursion/cycle | ETF A1000: 50% B, 50% US direct; B:60%TW,20%US,20%unknown | TW300, US600, unknown100, sum1000. A/B parent values not added again. A cycle/unsupported child becomes unresolved branch, not recursive infinity or normalized known weight. | Domain/property; 010/P1-002 |
| G13 Time/currency precision | 0.00000001 BTC; illegal 0.000000001; date-only activity around offset snapshot; negative security quantity | Exactly one sat roundtrips; sub-sat rejected; unknown ordering cannot become a verified delta; negatives preserved with allowed policy/warning or blocked unsupported valuation. | Unit/PG; 003/004 |
| G14 Same account / multi-account | One file has TFSA/RRSP; CSV and API aliases map same RRSP; identical ticker on different MICs | Two real accounts, one RRSP authority, no alias double sum; distinct listings stay distinct, company-level optional aggregation separate. | Contract/PG; 003/007 |
| G15 Interrupted sync / concurrency | Page1 staged, page2 fails; duplicate worker; disconnect during request; parallel conflicting imports | Cursor/authoritative snapshot unchanged until covered commit; one event revision wins; stale lease/generation cannot commit; exact preview invalidated on fact changes. | Fault/PG; 004/007/P1-001 |
| G16 Tenant/exports | Users A and B with same provider/order identifiers; A references B account/job/calculation/export/cache | Separate identity namespaces; 403/404 as policy, no financial content/secret/path leak; export pinned to A's selected calculation. | Security/API/E2E; 005/013 |
| G17 Migration equivalence | Synthetic current schemas including source revisions/raw references, legacy openings/wallet/settings/reports/Unicode and exact decimals | Counts/FKs/accepted-head totals/precision/bytes match declared source-target mapping; excluded legacy scope explained separately, original SQLite untouched; fresh restore matches. | Migration/restore; 014 |
| G18 Irregular dates / disabled source | One CSV in January, next in March; source disabled after accepted data; any ETF refresh unavailable | Actual dates/gaps shown, no fabricated February holdings/return; prior facts remain visible, no more sync; reference errors retain dated last-good evidence. | API/E2E; 009/011/012 |

### G19 — Corporate-action quantity/quote basis

Synthetic pre-split snapshot has 10 shares at USD100. A verified 2-for-1 split yields 20 shares against USD50, maintaining USD1000 before other price/FX changes. If the ratio/event cannot be verified, current quantity/price basis is unresolved and complete current value is unavailable; showing USD500 as a verified 50% investment loss fails. Layer: domain/reference/API; WL-P0-003/008/009/012. No split was executed in a real ledger. This is proposed acceptance, NOT RUN.


## Additional must-pass negative properties

No sum of CAD/USD/TWD equivalents; no raw CSV/credential strings in durable DB/logs/exports/backups after V2 TTL; no frontend numeric float used for financial sums; no trade/withdraw endpoint in connector egress; no provider branch in projection; no export changes when 'latest' advances after token selection. Cost proxy is never tax basis or portfolio return. Scope addition/removal/correction is never market gain.

Pilot-only country oracle: use at least 31 distinct countries including TW with unique row names and nonzero values, one unknown and one adjustment row; every country label is reachable visually and in the data table at narrow/wide viewport and keyboard zoom. It does not require touching classification arithmetic or real issuer downloads.
