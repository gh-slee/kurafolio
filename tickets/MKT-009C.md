---
id: MKT-009C
title: Add the display currency list and daily FX rates for it
priority: P0
status: ready
type: feature
parent: MKT-009
depends_on: [MKT-009B]
resources: [currency-policy, market-contract]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-11, post-MVP scope as written in this ticket"
review: independent
branch:
pr:
spec:
updated: 2026-11-18
---

# MKT-009C: Add the display currency list and daily FX rates for it

## Goal

The owner wants to switch the whole app to other popular currencies at the latest exchange rate, not only CAD, USD and TWD. Today the rates come from two fixed sources for two pairs. Add a currency list the pages read, and daily rates for every currency on it.

## Context

### Spec material

- Golden cases G07 and G09, cited in Acceptance criteria: [docs/golden-cases.md](../docs/golden-cases.md) (sha256:f7adca063ff68fe0502066608fc6fad6b1f818244679190b3e7cdcf3020e5594).

### Current behaviour

- USD/CAD comes from the Bank of Canada Valet API and TWD from a page of the Central Bank of the Republic of China (`src/kurafolio/fx.py:12-13`, `resolve_rates` at line 71). Both are saved as files in a project directory, which V2 does not have.
- The MVP analysis contract accepts `currency` and supports CAD, USD and TWD (ANL-012A).
- The user's chosen currency is stored by the preferences API (APP-011E).

## Requirements

- Owner decision 2026-11-10: Bank of Canada daily rates stay the source for CAD pairs; Frankfurter, a keyless service that republishes European Central Bank daily reference rates, covers the other currencies. No keyless intraday source was found, so FX is daily.

### Expected behaviour

- `GET /api/v2/currencies` returns the supported display currencies with code, localized name, minor-unit digits and the date of the latest rate. The currency selector in the toolbar (ANL-012B) reads this list.
- List approved by the owner on 2026-11-11: CAD, USD, TWD, EUR, GBP, JPY, AUD, CHF, HKD, SGD, CNY, KRW. A currency is listed only if a source in the instance provides its rate; a currency with no rate today is listed as unavailable with a reason, not hidden.
- Daily rates are stored in the market reference store from MKT-009B and fetched by the same refresh process once per day after each source publishes.
- Conversion is directed and uses one stated path per pair: a direct Bank of Canada rate when the pair includes CAD and the bank publishes it; otherwise the European Central Bank rates through EUR. The response names the source and date of every rate it used.
- Every analysis endpoint accepts any listed currency. Native amounts never change; a converted amount is always native amount times the stated rate.
- A missing rate makes the converted `complete_total` null for that currency only; values in other currencies and native amounts stay available.
- TWD: keep the existing central bank source if it is still reachable from the adapter; otherwise use the Frankfurter rate. Record which in the PR.

### Scope

- In scope: the currency registry, the FX adapters behind the MKT-009A interface, storage and daily refresh, the route, conversion in the analysis service, tests, documentation.
- Out of scope: historical rates for the value curve (MKT-009D), intraday FX, the selector component (ANL-012B), saving the choice (APP-011E).

### Implementation notes

- Port, do not rewrite, the validation in `fx.py:49-62`; keep its evidence fields (source URL, fetch time, hash).
- Rates are `Decimal`; store the published precision and round only at display.
- A weekend or holiday uses the latest earlier published rate and shows that rate's date. Never look up a future rate.
- Currencies are alternative views of one total. Amounts in two display currencies are never added.
- Minor-unit digits differ (JPY and KRW have none); take them from a fixed table in code, not from the provider.
- Tests never call the network; record small synthetic responses.

## Acceptance criteria

- [ ] AC-MKT-009C-01: Given the fixed-rate oracle, then securities CAD 2,200 with Bitcoin gives combined CAD 4,720.00, USD 3,371.43 and TWD 107,885.71 on every analysis endpoint (golden case G07).
- [ ] AC-MKT-009C-02: Given each additional listed currency and a fixed synthetic rate, then the converted total equals native total times that rate to the currency's minor unit.
- [ ] AC-MKT-009C-03: Given a missing USD to TWD path, then the TWD `complete_total` is null with a reason and the CAD and USD values are unchanged (golden case G09).
- [ ] AC-MKT-009C-04: Given a Saturday, then Friday's rate is used and its date is shown.
- [ ] AC-MKT-009C-05: Given a currency code not on the list, then the API answers with a typed validation error, not a default currency.
- [ ] AC-MKT-009C-06: `GET /api/v2/currencies` lists every approved currency with name in en-CA, zh-TW and zh-CN, digits and latest rate date.
- [ ] AC-MKT-009C-07: No test opens a network connection.

### Tests

- Unit tests for path selection, rounding and holiday fallback.
- Opt-in PostgreSQL and HTTP contract tests with fixed oracles.

## Plan

- [x] Owner Gate A, including the currency list.
- [ ] Registry and route.
- [ ] FX adapters and daily refresh.
- [ ] Conversion in the analysis service.
- [ ] Documentation.

## Handoff

- State: Not started. Owner approved Gate A on 2026-11-11. Waits on MKT-009B.
- Next step: Read `src/kurafolio/fx.py`, the MKT-009B store and the ANL-012A conversion code, then write the registry and its tests.
- Verify: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_fx -v` plus the new test modules.
- Gotchas: Check Frankfurter's current base URL and response shape on its own documentation before coding; do not rely on this ticket for them.
- Open questions: None.

## Log

- 2026-11-11 planner: split out of MKT-009. The owner's answer of 2026-11-10 (more currencies at the latest rate, Bank of Canada plus Frankfurter) is recorded here; the exact list is proposed for Gate A.
- 2026-11-11 planner: owner approved Gate A for this ticket on 2026-11-11 and released it (status ready). The owner also approved the proposed list of twelve currencies.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the "Owner decision 2026-11-10" bullet of Current behaviour, "Expected behaviour", "Scope" and "Implementation notes" from Context into Requirements and numbered the acceptance criteria AC-MKT-009C-01 to 07. Spec hash sha256:2dc1a259f993cec292fb8cf63ead552d0051c0801f722a3dde1121d7570ff55f, awaiting the owner's confirmation.
