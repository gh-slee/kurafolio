---
id: ANL-012A
title: Define the V2 analysis read contract for securities, crypto and total
priority: P0
status: in_progress
type: feature
parent: ANL-012
depends_on: [ANL-008, IMP-007E]
resources: [calculation-contract, identity-api]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-10, V2 MVP scope as written in this ticket"
review: independent
branch: ticket/anl-012a-define-the-v2-analysis-read-contract-for
pr:
spec:
spec_approved: sha256:53db5ddc3a935a30bdbdefb6bc5d90d43426429e417c2ebb3db32784d205d4ee
updated: 2026-11-26
---

# ANL-012A: Define the V2 analysis read contract for securities, crypto and total

## Goal

The three V2 analysis pages need one versioned read contract so they can be built in parallel with confidence and tested against fixed numbers. Today ANL-012 bundles this contract with all three pages. This child delivers only the endpoints and DTOs.

## Context

### Current behaviour

- No `/api/v2/analysis` route exists (`src/kurafolio/web_v2/api.py:26-37` lists all V2 routes).
- The shipped pages read a frozen report (`GET /api/v1/portfolios/{id}/reports/{report_id}`, `src/kurafolio/web/reports.py:293`); its DTO is edition-based and cannot refresh.
- Positions come from ANL-008 and quotes and FX from MKT-009.

### Findings from the merged code (`main` at `574896b`, rechecked 2026-11-26)

- ANL-008 is merged (PR #94). `kurafolio.projection` has three parts. `read_accepted_state(connection, context)` (`projection/accepted.py:32`) reads accepted `0004` facts inside a caller-owned `REPEATABLE READ READ ONLY` transaction. `calculate(state, inputs)` (`projection/positions.py:24`) is pure. `to_document` and `calculation_id` live in `projection/model.py:225-244`. The calculator has no route and fetches nothing. No file under `src/kurafolio/projection/` changed between `7d7acc1` and `574896b`.
- IMP-007E is merged (PR #115, status `done`), and its `ingestion` profile serves a `0004_ingestion` database:
  - `Database` (`persistence/context.py:45`) maps `ingestion` to `0004_ingestion`, with the same 5 s statement and idle-in-transaction timeouts as `identity` and `sources` (`:56`).
  - `_transaction` (`:101`) and `RequestDatabase` (`:147`) accept `ingestion`. A read-only principal transaction checks the realm first, then sets `ledger.tenant_id` and `ledger.portfolio_id`, which is what `read_accepted_state` checks.
  - The runtime login has SELECT on every table of `wl_pg` and on `ingestion_schema.READ_TABLES` (`ingestion_schema.py:214`, granted in `ingestion_migration.py:126-128`). That covers every table `read_accepted_state` reads, so this ticket needs no grant.
  - `read_accepted_state` still refuses every revision except `0004_ingestion` (`projection/accepted.py:9`). `migrations/versions/` holds only `0001` to `0004`.
  - `Auth.__init__` builds `self.financial` (`web_v2/auth.py:61`), and on `ingestion` `ready()` also checks the runtime grant inventory and the catalog digest.
  - The ANL-008 PostgreSQL test still opens its runtime pool with `schema_mode='sources'` and a comment saying the wrapper refuses 0004 (`tests/test_projection_accepted_postgres.py:92-93`). That comment is now stale. This ticket leaves that test unchanged.
  - Decisions needed, item 1 (a) is therefore satisfied: the build can start once this recheck merges.
- The ingestion Boundary as merged (`web_v2/api.py`):
  - `IMPORT_ROUTES` and `IMPORT_DYNAMIC` (`:40-47`) are looked up only when `schema_profile == 'ingestion'`, after the source routes, which `ingestion` also serves.
  - After the session check, an import request has its own allowed query keys and calls `auth.imports.admit(principal, 'read' | 'control')`. Every other route refuses any query string except the invitation and source list GETs (`:258-268`).
  - The scope state carries `import_request` (`:271`), and `invalid_response` (`:335`) maps a response validation failure on a source or import request to 500 `internal_error`.
  - `install_import_openapi` (`schemas.py:345`, called at `api.py:591`) wraps `app.openapi` and writes the frozen import definitions into `components.schemas` by name, overwriting any existing entry with that name. Its 63 names include `Account`, `Counter`, `Date`, `Decimal`, `Money`, `Position`, `Rate`, `Snapshot`, `State`, `Time` and `UUID`.
  - `tests/test_web_v2_imports.py` builds an `ingestion` app without PostgreSQL by patching `kurafolio.web_v2.api.Auth` with a `FakeAuth` that has no `financial` attribute. Its OpenAPI test requires that every component whose name is in the frozen codec set equals the frozen definition (`:163-164`).
  - `tests/test_postgres_import_routes.py` (`KURAFOLIO_INGESTION_TEST=1`) is the merged ingestion HTTP harness: one disposable database per test, `migrate_sources` then `migrate_ingestion`, a synthetic worker role, and a `TestClient` over `create_app`.
- An empty class comes back as zero. `aggregate` (`positions.py:235-246`) returns `known_subtotal` and `complete_total` of `0` for a class with no positions, and `btc_equivalent_quantity` is `0` with no crypto position. AC-01 forbids that zero on `/crypto`. The calculator stays as it is; the DTO layer below maps an empty scope to a typed status.
- Decision 12 of ANL-008 makes fully sold purchases a known zero. That zero is real and must stay distinct from an empty scope.
- The calculator reports each gap once per account and instrument, and per call, over all `report_currencies`. A missing TWD rate would put `fx_unavailable` on rows of a CAD response if one calculation served every currency. The plan therefore calculates once per requested currency.
- The existing live sources write workspace files and use long timeouts:
  - `prices.resolve_btc_price` (`prices.py:78`) and `fx.resolve_rates` (`fx.py:71`) save quotes, rates and evidence under a project `data/` folder. They time out after 30 s and 25 s. The Boundary gives a request 20 s, and `idle_in_transaction_session_timeout` is 5 s (`context.py:56`).
  - The pure parts can be reused unchanged: `prices.select_candle` (`:24`), `fx._select` (`:22`) and `fx.parse_cbc_html` (`:32`).
  - `fx.validate_rates` (`:49`) needs both pairs at once, so it cannot judge one pair alone.
  - The shipped SQLite application must not change (PRODUCT_CONTEXT.md), so neither file is edited.
- Market data is off unless the operator enables it. `market/config.py` builds a `QuoteService` with no provider by default, and nothing reads that configuration until MKT-009B.
- Rate limits:
  - `consume_budget_v1` accepts a fixed list of operations, and none of them is an analysis read (`persistence/identity_schema.py:235`, `source_schema.py:32`). Adding one needs SQL and a migration.
  - `admit_rate_v1` (`ingestion_schema.py:2139`) has only the import `read` and `control` buckets, and it answers `import_busy`.
- Errors:
  - `error_response` turns any code outside `ERROR_CODES` into 503 `instance_not_ready` (`web_v2/api.py:60`).
  - `ProjectionUnavailable` has six codes, and none of them is in `ERROR_CODES`. `ERROR_CODES` now ends with `length_required` (`schemas.py:144-152`).
- OpenAPI and frontend types:
  - A real `create_app` needs PostgreSQL, because `Auth.__init__` calls `ready()` (`web_v2/auth.py:74`). The default suite gets around that by patching `Auth`, as `tests/test_web_v2_imports.py` does.
  - The shipped `scripts/export_web_schema.py` builds the V1 app only. Its commands are in `docs/web-frontend.md:185-186`.
  - V2 frontend types are hand-written (`frontend/src/v2/api.ts`), and `frontend/package.json` already ships `openapi-typescript` and `decimal.js`.
- What the consumers expect from this contract:
  - ANL-012B: book cost and unrealized difference "only where cost scope matches", a cash table, the last source date, and a chart that "plots import dates" until MKT-009.
  - ANL-012C: known acquisition spending with its cost coverage, a weighted purchase rate, a cumulative acquisitions chart and a monthly table. These need per-purchase data, which `calculate` does not return today. Decisions needed, item 3.
  - RPT-013A: an export request carries a calculation identifier and a currency.
  - MKT-009B: Bitcoin is priced "from a price fetched at request time (ANL-012A, first version)".
  - MKT-009D: it adds a daily `value_series` "in a backward-compatible way", although its Context says the first version has "one point per import date". Decisions needed, item 2.
- Account and instrument metadata (`main` at `d3588b2`, checked 2026-11-26 for Part C):
  - `wl_pg.accounts` and `wl_pg.instruments` hold one row per `(id, version)`, where the version is the hash of the body. Both tables are frozen: a `BEFORE UPDATE OR DELETE` trigger rejects every change (`persistence/schema.py:185-186`). No route renames or deletes an account or instrument.
  - Each accepted fact pins an `(id, version)` through its plan's mappings, and `read_accepted_state` resolves the fact to that pinned version (`projection/accepted.py:106`). `PositionResult` keeps only the two IDs. An activity position takes the account and instrument of its first eligible leg (`positions.py:193`).
  - `wl_ingestion.mappings` is append-only. Accepting a plan appends a mapping revision only when a source identity gets a different target. The same step sets `mapping_changed`, which raises `roots.mapping_generation` by one (`ingestion_schema.py:1643-1658`, `:1778`). That is the only INSERT into the table.
  - An existing entity is reused only when its identifying fields match the source. For an account these are `category` and `role`. For an instrument they are `kind`, `currency`, `ticker`, `mic`, `symbol`, `network`, `settlement_identity`, the identifiers and the issuer (`ingestion/mapping.py:87`, `ingestion_schema.py:1106`). A label never establishes identity. A proposed entity always gets a newly allocated ID (`ingestion/review_bundle.py:195-205`, `:257`).
  - So on the merged code each entity ID has exactly one version, and an account's label is fixed when it is first accepted. A second version of one ID can come only from a later feature or a write that bypasses the acceptance functions.
  - A mapping can be re-pointed: a later plan can map a source identity to a new entity. No current mapping then targets the old ID, but its earlier facts still pin it.
  - The runtime login has SELECT on `wl_ingestion.mappings` and `wl_ingestion.accepted_plans` (`ingestion_schema.READ_TABLES`) and on `wl_pg.accounts` and `wl_pg.instruments`.
  - `AnalysisInstrument` has no name field. Every field it carries is an identifying field, which reuse requires to be equal.
  - The ANL-008 PostgreSQL seed writes mappings only inside the plan document (`tests/test_projection_accepted_postgres.py:140`). It writes no `wl_ingestion.mappings` row.
  - `RequestDatabase.transaction` yields a `UnitOfWork` with `incarnation` and `restore_epoch` (`persistence/context.py:128`).
- ROADMAP.md, "V2 MVP first", step 4: the first version takes "Bitcoin from the existing live price; CAD, USD and TWD from the existing daily FX". PRODUCT_CONTEXT.md names the sources: Coinbase Exchange for Bitcoin, the Bank of Canada for USD/CAD and the CBC page for USD/TWD. The existing FX code reads CBC.

## Requirements

### Expected behaviour

- `GET /api/v2/analysis/securities`, `/crypto` and `/total`, each taking `currency`.
- Every response carries: a calculation identifier, fact generation, valuation time, report currency, exact decimal strings in native and converted currency, `known_subtotal`, a nullable `complete_total`, source, quote and FX dates, and typed coverage or assumption codes.
- A KPI that cannot be computed is a typed "unavailable" status with a reason, never zero.
- Responses are tenant-scoped and cache keys include user, currency and generation.

### Scope

- In scope: the three endpoints, DTOs, OpenAPI, fixed-oracle tests.
- Out of scope: exposures (ETF-010), exports (RPT-013A), refresh scheduling (MKT-009), any page.

### Implementation notes

- DTO and error conventions: `src/kurafolio/web_v2/schemas.py`. Decimal rules: [canonical-domain.md](../docs/canonical-domain.md).
- Unknown is never zero and CAD, USD and TWD are alternative equivalents, never additive (AGENTS.md).
- The frontend types are generated: see `docs/web-frontend.md` lines 130-140 for `scripts/export_web_schema.py` and `openapi-typescript`. Decide whether V2 gets its own generated file.
- Acceptance numbers come from the golden cases referenced by ANL-008 and the original ANL-012 criteria, in [docs/golden-cases.md](../docs/golden-cases.md) (sha256:f7adca063ff68fe0502066608fc6fad6b1f818244679190b3e7cdcf3020e5594).

### Owner decisions recorded 2026-11-10

- Each analysis response includes a daily value series revalued with fetched prices, not only import dates. Days without a price carry the last known price and are marked.
- Securities responses expose book cost and unrealized gain where the source provided cost, as a typed "unavailable" otherwise. Cash is a separate class and a separate line in Total.
- Crypto quantity is purchases minus sales reported by the same exchange file; the response says when sales were counted.
- Assets are classified by asset class, not institution. A Bitcoin ETF is in securities.
- MVP order (owner: a usable V2 as soon as possible): the first version may value securities from the import's own market values and Bitcoin from the existing live price, before MKT-009 delivers stock quotes. The decision below is answered yes. This ticket may therefore start after ANL-008 for that first version; stored live quotes follow in MKT-009B, more currencies in MKT-009C and the daily series in MKT-009D, each of which extends this contract.

## Acceptance criteria

- [ ] AC-ANL-012A-01: Given only a securities import, then `/securities` and `/total` match the fixed oracle right after the commit generation and `/crypto` reports "no eligible acquisitions" without a zero value.
- [ ] AC-ANL-012A-02: Given securities and Bitcoin acquisitions, then `/total` counts Bitcoin once and equals the oracle in each supported currency.
- [ ] AC-ANL-012A-03: Given a missing quote or FX rate, then `known_subtotal` is returned, `complete_total` is null and the affected rows carry a reason code.
- [ ] AC-ANL-012A-04: Given user A, then no parameter returns user B's data.
- [ ] AC-ANL-012A-05: OpenAPI lists the routes and every field; decimal values are strings.

### Tests

- Opt-in PostgreSQL tests with independently derived oracles.
- HTTP contract tests in the style of `tests/test_web_v2_api.py`.

## Build plan

- Based on: `main` at `9503737` ("Plan ANL-012A Part C entity metadata rules (#123)"). First written from `7d7acc1` in #106 and rechecked on 2026-11-26 against the merged IMP-007E (PR #115) in #122. Amended on 2026-11-26 for the Part C entity metadata rules in #123, and again on 2026-11-26 for the oracle comparison rule. No file under `src/` changed between `574896b` and `9503737`. ANL-008 and IMP-007E are merged. IMP-007U, APP-011I, APP-011E and MKT-009B are not, and no migration after `0004_ingestion` exists.
- Status: on 2026-11-22 the owner answered items 1 to 3 under Decisions needed with "Accept all recommended", so this plan implements option (a) of each item as a decided rule. The `depends_on` and `resources` changes of item 1 (a) are in the front matter, with the owner's confirmation in the Log. Both dependencies are `done`. The builder, who has built Parts A and B, resumes Part C when the amendment pull request has merged to `main`.

  A question the plan does not answer returns the ticket to the planner.
- What the recheck changed (no gated text, front matter or `spec_approved` changed):
  - Part D now follows the merged ingestion Boundary: the analysis lookup sits in the `ingestion` block next to `IMPORT_ROUTES`, the query keys are checked in the Boundary, and analysis requests skip `auth.imports.admit`.
  - `create_app` must not read `auth.financial` while it builds the app, so the existing `FakeAuth` import tests keep passing.
  - Analysis component names must not collide with the import component names that `install_import_openapi` writes.
  - The live OpenAPI check, the 404s on other profiles and the query-key refusals move to the default suite. PostgreSQL keeps the tenant isolation and generation cases.
  - The Stop-and-ask items about the missing profile and harness are removed, because both exist now.
- What the amendment of 2026-11-26 changed (no gated text, front matter or `spec_approved` changed):
  - Part C gains "Entity metadata". It sets how a row's account and instrument are looked up, why no extra cache invalidation is needed, and what happens when the current metadata is missing. It implements the owner's "go C" choice (Decisions needed, item 4).
  - `build_document` takes the resolved entities as an argument. Part C step 2 no longer reads entities from the state by ID.
  - Part D reads the current entities in the same transaction as the accepted state, and the cache key gains the instance incarnation and restore epoch.
  - New tests, new Stop-and-ask items and an opt-in mapping-row seed for the PostgreSQL suite.
- What the comparison amendment of 2026-11-26 changed (no gated text, front matter or `spec_approved` changed):
  - "Tests and expected values" gains a comparison rule keyed on how each literal is written. A literal with exactly 18 fractional digits is compared at 18 places; every other literal is compared exactly. It implements Decisions needed, item 5.
  - The AC-02 `/total` cost in TWD is now written `89600.000000000000000000`. Summing the converted rows in the 120-digit context gives 89600 plus 1E-115, and the API keeps that value.
  - A new default-suite assertion checks that the API does not round, and a new Stop-and-ask item covers an oracle that would pass only by rounding.
  - No calculation, DTO, cache or export rule changes.
- Shape:
  - A reference module fetches the Bitcoin price and two FX pairs at request time. It writes nothing.
  - A service reads the accepted state and the current entity metadata once per request, calculates once for the requested currency and builds the response for one of three scopes from that calculation.
  - Nothing is persisted. One bounded in-process cache holds recent responses.
  - This ticket adds no table, SQL function, grant, migration or page.
- Build order:
  1. Parts A to C. They are pure and run in the default suite.
  2. Part D, the routes. It needs IMP-007E's `ingestion` profile.
  3. Part E, the types and the docs.
- One pull request.

### Files

- `src/kurafolio/projection/references.py` (new): the reference snapshot and its live, fixed and no-fetch providers (Part A).
- `src/kurafolio/projection/positions.py`: refactor only (Part B). It adds a public `ARITHMETIC`, `convert_money`, and with item 3 (a) the activity eligibility helper and `counted_activities`. No output of `calculate` changes.
- `src/kurafolio/projection/model.py`: `CountedActivity`, with item 3 (a) only.
- `src/kurafolio/projection/entities.py` (new): `CurrentEntities`, `read_current_entities` and the pure `resolve_current_entities` (Part C, "Entity metadata").
- `src/kurafolio/web_v2/analysis.py` (new): `AnalysisService`, the pure `build_document`, the response cache and `install_routes` (Parts C and D).
- `src/kurafolio/web_v2/schemas.py`: appends the analysis models and the error code `analysis_unavailable` (Part C).
- `src/kurafolio/web_v2/api.py`: the analysis route table, its query exemption, route registration on the `ingestion` profile and the `references` argument of `create_app` (Part D).
- `src/kurafolio/web_v2/__main__.py`: the `serve --no-reference-fetch` flag (Part D).
- `scripts/export_web_v2_analysis_schema.py` (new), `tests/fixtures/web_v2/analysis-openapi.json` (new, generated), `frontend/src/v2/analysis-schema.d.ts` (new, generated), `frontend/package.json` (a prettier exclusion only) (Part E).
- Tests:
  - `tests/test_projection_references.py` (new, default suite).
  - `tests/test_web_v2_analysis.py` (new, default suite).
  - `tests/test_web_v2_analysis_postgres.py` (new, opt-in).
  - `tests/test_projection_entities.py` (new, default suite) for `resolve_current_entities`.
- Docs:
  - `docs/web-v2-analysis.md` (new).
  - `docs/web-v2-imports.md`: the positions section links to it.
  - `docs/capability-status.md`: the V2 positions row.
  - `docs/web-frontend.md`: the V2 type generation command.

### Part A: reference inputs (`projection/references.py`)

```python
@dataclass(frozen=True, slots=True)
class FxRate:
    currency: str          # 'CAD' or 'TWD'
    per_usd: Decimal       # units of the currency per 1 USD, finite and > 0
    effective_date: date
    source: str            # 'Bank of Canada' or 'Central Bank of the Republic of China (Taiwan)'

@dataclass(frozen=True, slots=True)
class ReferenceSnapshot:
    valuation_time: datetime        # aware UTC, whole seconds
    btc: CryptoQuote | None         # symbol 'BTC', currency 'USD'
    fx: tuple[FxRate, ...]          # sorted by currency; may be empty
    def inputs(self, currency: str) -> ValuationInputs: ...

class References(Protocol):
    def snapshot(self) -> ReferenceSnapshot: ...

class FixedReferences: ...   # returns the snapshot it was given (tests)
class NoReferences: ...      # btc None and fx (); valuation_time from its clock, cached like LiveReferences
class LiveReferences:
    def __init__(self, *, fetch=None, clock=utc_now, snapshot_seconds=60,
                 fx_seconds=3600, retry_seconds=60, timeout=4): ...
```

- `inputs(currency)` returns `ValuationInputs(valuation_time, (currency,), fx_table, {}, crypto_quotes)`:
  - `fx_table` is `None` when `fx` is empty. Otherwise it is `FxTable('USD', {'USD': Decimal(1), <currency>: per_usd, ...}, as_of, source)`.
    - `as_of` is the oldest `effective_date` at 00:00 UTC.
    - `source` is the sources joined with `'; '`, in currency order.
  - `crypto_quotes` is `{'BTC': btc}`, or `{}` when `btc` is `None`.
  - `security_quotes` is always `{}`. Securities use their source-reported values until MKT-009B wires stored quotes (owner decision "MVP order"). This ticket neither builds nor reads a `QuoteService`.
- `LiveReferences` fetches three sources:
  - Bitcoin: GET `https://api.exchange.coinbase.com/products/BTC-USD/candles` with `granularity=60`, `start` = T minus 10 minutes and `end` = T, the query `prices.py:86-88` builds.
    - Parse with `json.loads(raw, parse_float=Decimal)`, then call `prices.select_candle(rows, T.isoformat())`. It keeps the last completed one-minute candle that is at most five minutes old.
    - The quote is `CryptoQuote('BTC', Decimal(close), 'USD', candle_end, 'Coinbase Exchange')`.
  - USD/CAD: GET `fx.BOC_URL` with `start_date` = D minus 10 days and `end_date` = D, where D is T's UTC date. Read the rows as `fx.py:83-85` does, then call `fx._select(rows, D)`.
  - USD/TWD: GET `fx.CBC_URL`, call `fx.parse_cbc_html`, then `fx._select(rows, D)`.
- Rate checks:
  - A rate must be finite and positive.
  - `_select`'s ten-day rule applies to each pair on its own.
  - Do not call `fx.validate_rates`, which needs both pairs.
- The fetch function:
  - Signature: `fetch(url, timeout) -> bytes`.
  - The default is a `urllib.request` GET with `User-Agent: Kurafolio/1.0`, `prices.tls_context()` and the timeout.
  - Each request gets `timeout` seconds (default 4), and one refresh sends at most three requests.
- Caching:
  - One snapshot serves `snapshot_seconds`. Every request in that window gets the same snapshot, so the same `valuation_time`, and the same calculation identifier while the facts do not change.
  - Bitcoin is fetched again for each new snapshot. Each FX pair is reused for `fx_seconds`.
  - A failed source is retried after `retry_seconds`, not on every request.
  - A lock lets one caller refresh. While it refreshes, other callers get the previous snapshot at once and do not wait. Only the first request after start, when no snapshot exists yet, waits for the fetch. Waiting callers would otherwise hold the Boundary's eight in-flight slots for up to about 12 s, and every V2 route would answer 429 meanwhile.
- Failures: a network error, an HTTP status other than 200, a parse error, a `ValueError` from the helpers, a stale candle or a timeout leaves that piece out. `btc` is `None`, or the pair is missing from `fx`. The calculator then reports `quote_unavailable` or `fx_unavailable`. A fetch never raises into the request and never becomes zero.
- Boundaries:
  - It writes no file and sends no portfolio data.
  - It logs no value, URL or body.
  - It is never called inside a database transaction.
  - `prices.py` and `fx.py` do not change.

### Part B: calculator helpers (`projection/positions.py`, `projection/model.py`)

This is a refactor. Every existing test in `tests/test_projection_positions.py` and `tests/test_projection_accepted_postgres.py` passes unchanged.

- Add a public `ARITHMETIC` and keep `_ARITHMETIC` as an alias.
- Move the arithmetic of the inner `convert` (`positions.py:45-59`) into `convert_money(money: Money, currency: str, fx: FxTable | None) -> Decimal | None`. The rule stays the same:
  - The same currency returns the amount.
  - Otherwise the result is `amount / source * target`, with 1 for the pivot.
  - A missing rate or a missing table returns `None`.

  The inner `convert` calls it and still records `fx_unavailable` when it returns `None`. Callers run it under `localcontext(ARITHMETIC)`.
- With item 3 (a) only:
  - Move the activity eligibility rules (`positions.py:155-201`, the void, mirror, kind, status, reason and leg checks) into one helper, `_classify(fact) -> tuple[str | None, tuple[Leg, ...]]`. It returns an excluded code or `None`, and the eligible legs. `calculate` and the new `counted_activities(state) -> tuple[CountedActivity, ...]` both use it, so the two cannot disagree.
  - `counted_activities` returns one item for each account and instrument group of an eligible BUY or SELL, grouped as `calculate` groups it, and sorted by `(economic_group_id, account_id, instrument_id)`:

```python
@dataclass(frozen=True, slots=True)
class CountedActivity:
    economic_group_id: str
    kind: str              # 'BUY' or 'SELL'
    account_id: str
    instrument_id: str
    quantity: Decimal      # signed sum of the eligible legs of this group
    cost: Money | None     # acquisition_cost for a BUY, None for a SELL
    occurred_at: dict      # the accepted event-time token, unchanged
    has_crypto_fee: bool
```

- A BUY with eligible legs in several groups repeats its `cost` on each item, as `calculate` does today (ANL-008 deferred gap). The purchase rate below refuses that case and does not allocate the cost.

### Part C: DTOs (`web_v2/schemas.py`) and the document builder (`web_v2/analysis.py`)

Append the models at the end of the file, after the source models and the import OpenAPI helpers (`import_openapi_extra`, `install_import_openapi`), under a comment "Analysis read contract, version 1". Reuse the existing `Counter`, `Hex`, `Timestamp` and `UUID` types. Every model is `Closed`.

#### Types

- `DecimalString`: `Annotated[str, Field(min_length=1, max_length=256, pattern=r'^-?(0|[1-9][0-9]*)(\.[0-9]+)?$')]`.
  - Its value is `format(value, 'f')` of the calculator's `Decimal`, with no rounding or quantizing, as ANL-008's `to_document` does.
  - The 120-digit context keeps a value under about 125 characters.
  - It is never a JSON number. The pattern is the canonical `DecimalTokenV1` spelling. The 38-digit admission bound applies to inputs, not to calculated quotients.
- `ReportCurrency`: `Literal['CAD','USD','TWD']`, the module constant `CURRENCIES`. MKT-009C extends it.
- `NativeCurrency`: a pattern of three upper-case letters.
- `Amount`: `{amount: DecimalString, currency: NativeCurrency}`.
- `DateString`: the pattern `^\d{4}-\d{2}-\d{2}$`.
- `Timestamp` is the existing type.
- `Text`: `Annotated[str, Field(min_length=0, max_length=4096)]`.
- `TimeToken`: `Annotated[str, Field(min_length=1, max_length=4096)]`. It holds a source time token unchanged: a date, an ISO instant with an offset, or a legacy token.
- `GapCode`: `Literal[*sorted(model.GAP_CODES)]`.
- `AssumptionCode`: `Literal[*sorted(model.ASSUMPTION_CODES)]`.
- `ExcludedCode`: `Literal[*model.EXCLUDED_CODES]`.
- `ReasonCode`: `Literal` of the sorted union of `GAP_CODES` and `{'sales_counted', 'no_positions', 'no_eligible_acquisitions', 'value_cost_currency_differs', 'cost_allocation_unresolved'}`.
- `ERROR_CODES` gains `analysis_unavailable`, appended after every code on `main` at build time.

#### Models

```python
class FactGeneration(Closed): accepted: Counter; mapping: Counter

class Figure(Closed):
    status: Literal['available', 'partial', 'unavailable']
    known_subtotal: DecimalString | None
    complete_total: DecimalString | None
    counted_count: int        # rows the figure covers that have a known amount
    position_count: int       # rows the figure covers
    reasons: list[ReasonCode] # sorted and unique; empty only when available

class AnalysisAccount(Closed):
    id: UUID; label: Text; category: Text; role: Literal['investment', 'crypto', 'funding']

class AnalysisInstrument(Closed):
    id: UUID; kind: Literal['SECURITY', 'CASH', 'CRYPTO', 'UNSUPPORTED']
    currency: NativeCurrency | None; ticker: Text | None; mic: Text | None
    symbol: Text | None; network: Text | None

class AnalysisRow(Closed):
    asset_class: Literal['securities', 'cash', 'crypto', 'unsupported']
    account: AnalysisAccount; instrument: AnalysisInstrument
    quantity: DecimalString | None; btc_equivalent: bool
    value: Amount | None; value_converted: DecimalString | None
    value_basis: Literal['quote', 'source_reported', 'par'] | None; value_as_of: TimeToken | None
    cost: Amount | None; cost_converted: DecimalString | None
    cost_status: Literal['known', 'unavailable', 'not_applicable']; book_cost_cad: Amount | None
    unrealized_gain: Amount | None; unrealized_gain_converted: DecimalString | None
    codes: list[AssumptionCode]; gaps: list[GapCode]

class ClassLine(Closed):
    asset_class: Literal['securities', 'cash', 'crypto', 'unsupported']
    value: Figure; native_known: list[Amount]

class Observation(Closed):
    account_id: UUID; observed_at: TimeToken
    coverage_status: Literal['complete', 'partial', 'unknown']; position_count: int

class GapItem(Closed): code: GapCode; account_id: UUID | None; instrument_id: UUID | None

class BtcReference(Closed):
    status: Literal['available', 'unavailable']
    price: Amount | None; as_of: Timestamp | None; source: Text | None

class FxReference(Closed):
    currency: Literal['CAD', 'TWD']; per_pivot: DecimalString; effective_date: DateString; source: Text

class References(Closed): btc: BtcReference; fx_pivot: Literal['USD']; fx: list[FxReference]

class AnalysisBase(Closed):
    contract_version: Literal[1]
    calculation_id: Hex
    fact_generation: FactGeneration
    valuation_time: Timestamp
    report_currency: ReportCurrency
    references: References
    value: Figure; cost: Figure; unrealized_gain: Figure
    lines: list[ClassLine]; rows: list[AnalysisRow]
    observations: list[Observation]; assumptions: list[AssumptionCode]; gaps: list[GapItem]

class SecuritiesAnalysis(AnalysisBase): scope: Literal['securities']
class TotalAnalysis(AnalysisBase): scope: Literal['total']
class CryptoAnalysis(AnalysisBase): scope: Literal['crypto']; crypto: CryptoDetail

class CryptoDetail(Closed):
    basis: Literal['acquisitions_assumed_held']
    state: Literal['tracked', 'no_eligible_acquisitions']
    btc_equivalent_quantity: DecimalString | None
    purchases_counted: int; sales_counted: bool; sales_counted_count: int
    excluded: dict[ExcludedCode, int]           # every code, including zeros
    # With item 3 (a) only:
    activities: list[CountedActivityRow]
    spending: Figure
    purchase_rate: PurchaseRate

class CountedActivityRow(Closed):
    economic_group_id: UUID; kind: Literal['BUY', 'SELL']
    account_id: UUID; instrument_id: UUID
    quantity: DecimalString; cost: Amount | None
    occurred_at: TimeToken; has_crypto_fee: bool

class PurchaseRate(Closed):
    status: Literal['available', 'unavailable']; rate: Amount | None; reasons: list[ReasonCode]
```

Every count is a non-negative `int`. Canonical IDs come from PostgreSQL `uuid` columns, so pure tests use UUID strings.

#### `build_document(calculation, state, snapshot, scope, currency, entities, counted=None) -> dict`

This function is pure. Use `localcontext(ARITHMETIC)` for every sum and conversion. `entities` is the `CurrentEntities` that Part D reads in the request's transaction; pure tests build it directly.

1. Rows by scope, in `calculation.positions` order:

   | Scope | Asset classes |
   |---|---|
   | `securities` | `securities`, `cash`, `unsupported` |
   | `crypto` | `crypto` |
   | `total` | all |

2. Each row comes from its `PositionResult`:
   - `account` and `instrument` come from `entities` under the rules in "Entity metadata" below, never from the state by ID alone.
   - `value` is `PositionResult.value`, and `value_converted` is `values[currency]`.
   - `cost` is `PositionResult.cost`. `cost_converted` is `convert_money(cost, currency, inputs.fx)`, or `None` when the cost is `None`.
   - `unrealized_gain` is `PositionResult.unrealized_gain`, and `unrealized_gain_converted` is `gain_values[currency]`.
   - `codes` are `PositionResult.codes`.
   - `gaps` are the sorted codes of `calculation.gaps` with this `(account_id, instrument_id)`, plus `fx_unavailable` when the cost is known and `cost_converted` is `None`.
   - The Decision 12 tracked zero keeps a null `value` and `"0"` for `value_converted`.
3. A `Figure` has a row set, a known amount per row, and this rule:
   - With no rows, it is `unavailable` and both amounts are null. Its reason is `no_eligible_acquisitions` for crypto and `no_positions` otherwise. An empty scope is never `"0"`.
   - Otherwise:
     - `known_subtotal` is the sum of the known amounts, or null when none is known.
     - `complete_total` equals `known_subtotal` when every row is known, else null.
     - The status is `available` when `complete_total` is set, `partial` when only `known_subtotal` is set, and `unavailable` otherwise.
     - `reasons` is the sorted union of `gaps` of every row missing its amount, plus the codes in the bullets below. A Figure that is not `available` and has no reason is a bug: stop and ask.
   - `value`, for the scope and for each line:
     - The rows are that class's rows. The scope is the `securities` class for `/securities`, the `crypto` class for `/crypto`, and every row for `/total`.
     - `known_subtotal` and `complete_total` come from the calculator's `ClassResult` (`calculation.classes[name]` or `calculation.total`) for `currency`, so ANL-008's rules, including the `sale_shape_unsupported` incompleteness, stay authoritative.
     - `counted_count` is the number of rows with a `value_converted`.
     - A gap without an instrument (`sale_shape_unsupported`) adds its code when the figure covers crypto.
   - `cost` and `unrealized_gain`: the rows are the scope rows whose `cost_status` is not `not_applicable`, so cash is left out. The known amount is `cost_converted` or `unrealized_gain_converted`. For the gain:
     - add `sales_counted` when a missing row carries that code;
     - add `value_cost_currency_differs` when a row with a known value and a known cost has no gain because the two currencies differ (`positions.py:149`).
   - The `unsupported` line has no `ClassResult`. Its value is `unavailable`, with both amounts null, `counted_count` 0 and the rows' gaps as reasons.
4. `lines`:

   | Scope | Lines |
   |---|---|
   | `securities` | `securities`, `cash`, then `unsupported` when such rows exist |
   | `crypto` | `crypto` |
   | `total` | `securities`, `cash`, `crypto`, then `unsupported` when such rows exist |

   `native_known` lists `ClassResult.native_known` as `Amount`s sorted by currency, or `[]` for `unsupported`. Currencies are never added together.
5. `observations` lists every `calculation.observations` entry, in every scope, without `key_digest`.
6. `assumptions` are filtered by scope:

   | Scope | Assumptions |
   |---|---|
   | `securities` | `missing_from_newer_snapshot_is_sold` |
   | `crypto` | `acquisitions_assumed_held`, `sales_counted`, `crypto_fees_not_deducted` |
   | `total` | all |

7. `gaps` holds the calculation gaps of in-scope rows, the instrument-less gaps for `crypto` and `total`, and the derived cost `fx_unavailable` gaps. They are sorted by code, account ID and instrument ID, with null sorting first.
8. `references`:
   - `btc` comes from `snapshot.btc`: price `Amount(price, 'USD')`, its `as_of` and its source, or `unavailable` with null fields.
   - `fx` comes from `snapshot.fx`.
   - Every scope carries them.
9. Identity and time:
   - `calculation_id` and `fact_generation` (as decimal strings) come from the calculation.
   - `valuation_time` is formatted as `%Y-%m-%dT%H:%M:%S.%fZ` in UTC.
   - `report_currency` is `currency`, and `contract_version` is 1.
10. `crypto`:
    - `state` is `no_eligible_acquisitions` when the crypto class has no row. `btc_equivalent_quantity` is then null, not the calculator's `0`.
    - Otherwise `state` is `tracked` and the quantity comes from the calculator. It can be null (unknown) or a known zero such as `"0.000"`.
    - The counts and `excluded` come from `calculation.crypto`.
    - With item 3 (a), `activities` lists `counted`.
    - `spending` is a Figure over the counted BUY items:
      - the known amount is the cost converted to `currency`;
      - the reasons are `cost_unavailable` and `fx_unavailable`;
      - with no BUY, it is `no_eligible_acquisitions`.
    - `purchase_rate` is `available` only when four conditions hold:
      - every counted BUY of a BTC-equivalent instrument has a cost;
      - those costs share one currency;
      - no `economic_group_id` appears twice among them;
      - their quantity sums above zero.

      The rate is then `Amount(sum(cost) / sum(quantity), cost currency)`. It stays in the cost's own currency, because converting a historical rate at today's FX would mislead. Otherwise the rate is null and the reasons are among `cost_unavailable`, `cost_currency_mixed`, `cost_allocation_unresolved` and `no_eligible_acquisitions`.
11. No `value_series` field is built under item 2 (a). See item 2 for (b) and (c).

#### Entity metadata

The owner chose "go C" on 2026-11-26 (Decisions needed, item 4): analysis shows the current account and instrument metadata, and the facts keep the version they pinned. The numbers always come from the pinned versions, because the calculator reads those. The rules below only pick what the `account` and `instrument` objects of a row show. Context, "Account and instrument metadata", has the findings they rest on.

`projection/entities.py` (new):

```python
@dataclass(frozen=True, slots=True)
class CurrentEntities:
    accounts: Mapping[str, Account]        # by entity ID
    instruments: Mapping[str, Instrument]  # by entity ID

def read_current_entities(connection, context: TenantContext) -> CurrentEntities: ...
def resolve_current_entities(mappings, plans, accounts, instruments) -> CurrentEntities: ...
```

Rule 1: the lookup.

- `read_current_entities` runs SELECTs only. It is called inside the transaction of `read_accepted_state`, right after it, so the metadata and the generations come from one snapshot.
  - It checks the four transaction settings as `_read` does (`accepted.py:43-51`) and raises the same `projection_snapshot_required` or `projection_scope_mismatch`.
  - Every query filters by the same `tenant_id` and `portfolio_id` literals as the reader's `rows()` (`accepted.py:65`).
  - It reads `wl_ingestion.mappings` (`id, revision, entity_kind, entity_id, entity_version, plan_id`) for `entity_kind` in `account` and `instrument`, `wl_ingestion.accepted_plans` (`id, created_at`), and `wl_pg.accounts` and `wl_pg.instruments` with the reader's columns.
  - It passes the rows to the pure `resolve_current_entities`. Any other failure raises `projection_reference_missing`, as the reader does.
  - `read_accepted_state` does not change.
- `resolve_current_entities` picks one version for each entity ID that any mapping row targets. It orders mapping rows by the plan's `(created_at, id)`, the order the reader uses, then by mapping `revision`, then by mapping `id` in C order. It takes the last row of that order:
  1. among the current mapping rows that target the ID (the highest `revision` of each mapping `id`);
  2. or, when no current mapping targets the ID (re-pointed), among every mapping row that ever targeted it.
- The chosen `(id, version)` must exist in the entity rows, and its `plan_id` in the plans. Otherwise it raises `projection_reference_missing`. The foreign keys make this unreachable on a consistent database.
- An ID that no mapping row targets is absent from the result. Only storage written around the acceptance functions can produce one.

For each row, `build_document` collects the pinned versions of the row's account ID and instrument ID from `state`: head accounts, position accounts and instruments, activity source accounts, and leg accounts and instruments. It then resolves each entity:

- The shown version is `entities.<kind>[id]`. When the ID is absent (rule 3), it is the single pinned version.
- Identity check: the shown version and every pinned version must agree on the identifying fields. For an account that is `role` and `category`. For an instrument it is `kind`, `currency`, `ticker`, `mic`, `symbol`, `network` and `settlement_identity`. A disagreement raises `ProjectionUnavailable('projection_head_inconsistent')`. The merged code cannot produce one.
- `AnalysisAccount`: `id`, `role` and `category` (equal on every version by the check), and `label` from the shown version. The label is the only field that can differ between versions.
- `AnalysisInstrument`: every field from the shown version. By the check, these equal the pinned fields the calculator used, so a row never contradicts its own figures.
- No instrument name (issuer label or source descriptor) is added. No consumer ticket asks for one.

Rule 2: invalidation.

- An account's label, or which version is current, can change only when a mapping revision is appended, because the entity rows are frozen. That append raises `mapping_generation` in the same acceptance step.
- The cache key and `calculation_id` already include `mapping_generation`. So a metadata change always gives a cache miss and a new `calculation_id`. No other invalidation, TTL or stored copy is added, and the `calculation_id` formula does not change. RPT-013A, which pins a calculation, therefore pins the metadata too.
- Part D adds `unit.incarnation` and `unit.restore_epoch` to the cache key. A restore can reuse generation numbers, and a session signed in after it would otherwise hit an entry built before it.
- The direct PostgreSQL seed bypasses the acceptance functions. A test that changes metadata must append the mapping revision and raise `roots.mapping_generation` itself, or it proves nothing.

Rule 3: missing or deleted metadata.

- No row is ever deleted: entity rows and mappings are frozen, and mappings reference the entity rows by foreign key.
- "No current metadata" means that every mapping that targeted the ID has been re-pointed. Rule 1, step 2, then shows the version that the newest of those mapping rows targeted. On the merged code that is the pinned version.
- An ID absent from `entities` uses its pinned version when the state pins exactly one. When the state pins several, `build_document` raises `ProjectionUnavailable('projection_reference_missing')`. The response is then 503 `analysis_unavailable`, and nothing is cached.
- Fields are passed through as stored. A null `ticker`, `mic`, `symbol`, `network` or `currency` stays null, and an empty `label` stays `""`.
- The server never fills a name with the UUID, another version's value, another entity's value or a placeholder string. Display text for an empty name belongs to the pages (ANL-012B to 012D) and their locale catalogs.
- The contract adds no field for the metadata source, so the AC-05 property lists do not change.

### Part D: service, cache and routes

`web_v2/analysis.py`:

```python
SCOPES = ('securities', 'crypto', 'total')
CURRENCIES = ('CAD', 'USD', 'TWD')

class AnalysisService:
    def __init__(self, database_of, references, *, cache_entries=64): ...
    def read(self, principal, scope: str, currency: str) -> dict: ...

def install_routes(app, service_of, errors) -> None: ...
```

`read` runs in this order:

1. `snapshot = references.snapshot()`, before any database work. No network wait happens inside a transaction; the transaction timeout is 5 s.
2. Open `RequestDatabase(database_of(), principal).transaction(principal.context, readonly=True)`, then call `read_accepted_state(unit.connection, principal.context)`. The merged `ingestion` profile accepts this (Context, "Findings"). The realm check is the first read, and the transaction runs only the reader's SELECTs.
   - `database_of` is a zero-argument callable that returns the financial `Database`. It is called on each read, never in `__init__`.
   - In the same transaction, call `entities = read_current_entities(unit.connection, principal.context)` (Part C, "Entity metadata"). Keep `unit.incarnation` and `unit.restore_epoch`.
3. Set `inputs = snapshot.inputs(currency)` and `identifier = calculation_id(state, inputs)`.
4. Build the cache key: `(principal.user_id, tenant_id, portfolio_id, unit.incarnation, unit.restore_epoch, scope, currency, state.accepted_generation, state.mapping_generation, identifier)`.
5. On a hit, return the cached document. On a miss:
   - call `calculate(state, inputs)`, and `counted_activities(state)` with item 3 (a);
   - call `build_document` with `entities`. A `ProjectionUnavailable` it raises maps as in the table below and is not cached;
   - validate the result with the scope's model;
   - store it.

   The cache is a lock-guarded LRU of `cache_entries`. A document that fails validation raises `internal_error` (500) and is not stored.

Error mapping:

| Raised | Response |
|---|---|
| `ProjectionUnavailable('restore_required')` or `('projection_schema_unsupported')` | 503 `instance_not_ready` |
| `ProjectionUnavailable('projection_reference_missing')` or `('projection_head_inconsistent')` | 503 `analysis_unavailable` |
| `ProjectionUnavailable('projection_snapshot_required')` or `('projection_scope_mismatch')` | 500 `internal_error` |
| `PersistenceError` (for example a realm mismatch) | `IdentityError()`, 503 `instance_not_ready`, as `Auth.candidate` does |

Routes (`install_routes`):

- Three sync GET handlers: `/api/v2/analysis/securities`, `/api/v2/analysis/crypto` and `/api/v2/analysis/total`.
- Each has `response_model` set to its scope model, `responses=errors` and a required `currency: Literal['CAD','USD','TWD'] = Query()`. A FastAPI validation failure already maps to 422 `invalid_input`.
- The Boundary checks the query keys before the handler runs (below). The handler does not check them again.
- It returns `service_of(request).read(request.state.principal, scope, currency)`.
- `install_routes` imports no `Auth` and opens no database, so Part E can build the schema without PostgreSQL.

`web_v2/api.py`:

- `ANALYSIS_ROUTES` maps the three paths to `('GET',)`.
- `Boundary.request` looks it up inside the same `schema_profile == 'ingestion'` step as `IMPORT_ROUTES` (`api.py:198-203`), after the import lookup, and sets `analysis_request = methods is not None`. Analysis paths are exact, so no dynamic pattern is added.
- Query keys: add an `elif analysis_request:` branch to the existing `if import_request: ... elif ...` chain (`api.py:260-268`). It raises 422 `invalid_input` unless `set(params) == {'currency'}`.
  - So a missing `currency`, `portfolio_id`, `user_id`, `tenant_id` and any other key are refused, and `query()` already refuses a repeated key.
  - The value itself (`cad`, `EUR`) is refused by the handler's `Literal` query with 422 `invalid_input`.
  - This branch does not call `auth.imports.admit`. The import read budget answers `import_busy` and is not an analysis limit (see "No rate limit" below).
- Add `analysis_request=analysis_request` to the scope state next to `import_request` (`api.py:271`).
- The existing order still applies: host, headers, route and method (404/405), session (401 `authentication_required`), then query parsing.
- `invalid_response` (`api.py:335`) returns `internal_error` when `source_request`, `import_request` or `analysis_request` is set.
- `api.py` gains no `INSERT `, `UPDATE `, `DELETE ` or `TRUNCATE ` text; `tests/test_web_v2_imports.py` checks that.
- `create_app(settings, *, frontend_root=None, references=None)`:
  - On `ingestion`, it sets `app.state.analysis = AnalysisService(lambda: auth.financial, references if references is not None else LiveReferences())` and calls `install_routes`. Constructing `LiveReferences` starts no fetch.
  - `create_app` must not read `auth.financial` itself. The `FakeAuth` of `tests/test_web_v2_imports.py` has no such attribute, and those tests must keep passing unchanged.
  - Call `install_routes` before `s.install_import_openapi` (`api.py:591`), so both sets of operations sit in the one wrapped document.
  - On `identity` and `sources`, the three paths answer 404 `not_found` and do not appear in `/api/v2/openapi.json`. `references` is ignored there.
- No rate limit is added:
  - `consume_budget_v1` has no analysis operation. Adding one needs SQL and a migration, which is out of scope.
  - `admit_rate_v1` is the import budget, and it answers `import_busy`.
  - What bounds the cost instead: the Boundary admits eight requests at a time, the reader's statements stop at 5 s, and the references are fetched once per window for the whole instance.

`web_v2/__main__.py`:

- `serve --no-reference-fetch` is valid only with `--schema-profile ingestion`; the parser refuses it otherwise.
- It passes `references=NoReferences()`.
- Live fetching stays on by default. That follows the owner's MVP decision ("Bitcoin from the existing live price; CAD, USD and TWD from the existing daily FX"). The flag lets an operator stop all egress.

### Part E: OpenAPI export, generated types and docs

- Decision on the frontend types: V2 gets its own generated file for this contract.
  - The contract has about 15 nested models of decimal strings. ANL-012B to 012E, MKT-009C and MKT-009D all build on or extend it, so hand-copied types would drift.
  - The small identity types in `frontend/src/v2/api.ts` stay hand-written.
- `scripts/export_web_v2_analysis_schema.py --output <file>`:
  - Builds `FastAPI(title='Kurafolio V2 identity API', version='2')` and calls `install_routes` with a stub service that fails if it is ever called. It needs no database.
  - Writes the three paths and the component schemas they reach as `json.dumps(value, indent=2, sort_keys=True) + '\n'`.
- Component names: no analysis component may share a name with a component that `install_import_openapi` writes (Context, "Findings"), because that function overwrites by name. The model names in Part C (`Amount`, `Figure`, `FactGeneration`, `AnalysisAccount`, `AnalysisInstrument`, `AnalysisRow`, `ClassLine`, `Observation`, `GapItem`, `BtcReference`, `FxReference`, `References`, `CryptoDetail`, `CountedActivityRow`, `PurchaseRate` and the three scope models) do not collide today. A default-suite test computes the import name set from `kurafolio.ingestion.contracts` the way `install_import_openapi` walks it and asserts that the two sets are disjoint. If a name collides, rename the analysis model with an `Analysis` prefix; never rename an import definition.
- Commit its output as `tests/fixtures/web_v2/analysis-openapi.json`.
- Generate the types with `frontend/node_modules/.bin/openapi-typescript tests/fixtures/web_v2/analysis-openapi.json -o frontend/src/v2/analysis-schema.d.ts` and commit the result.
- Add `"!src/v2/analysis-schema.d.ts"` to the `format:check` script of `frontend/package.json`, as `src/lib/schema.d.ts` has.
- Docs:
  - `docs/web-v2-analysis.md` (new) describes:
    - the routes, query and errors;
    - every field and figure rule;
    - the empty states and the tracked zero;
    - the per-currency calculation identifier (RPT-013A pins a calculation in its currency);
    - the reference sources, their cache windows and their failure codes;
    - `--no-reference-fetch`, and the absence of a rate limit;
    - that securities are source-reported until MKT-009B.
  - `docs/web-v2-imports.md`: the positions section says the routes now exist and links to the new page.
  - `docs/capability-status.md`: the row reads "routes on the ingestion profile; no page until ANL-012B".
  - `docs/web-frontend.md`: add the V2 export and generation commands next to the V1 ones (`:185-186`). The gated Implementation note cites lines 130-140; the commands have since moved, and the note is not edited.

### Tests and expected values

These values are derived by hand from the stated inputs, not from the code. They use `docs/golden-cases.md` (sha256:f7adca06…e5594): G05, G07, G08 and G09.

Fixture:

- FX: 1 USD = 1.4 CAD = 32 TWD, with USD as the pivot.
- BTC: USD 60000.
- Valuation time: 2026-01-15T12:00:00Z.
- No security quotes, so securities are `source_reported`.
- DEMO-A (USD): 10 units, market value USD 1000, cost USD 800.
- DEMO-B (CAD): 8 units, market value CAD 800, cost CAD 600.
- Exchange purchases: x = 0.010 BTC for CAD 700 and y = 0.020 BTC for CAD 1500.
- Every ID is a UUID.

Comparison rule (Decisions needed, item 5):

- The rule is set by how each literal in the table is written, not by whether the true value terminates:
  - A literal with exactly 18 fractional digits, such as `USD 2800.000000000000000000` or `TWD 89600.000000000000000000`, is compared at 18 places. The test parses the response string with `Decimal`, calls `quantize(Decimal('1E-18'))` under `localcontext(ARITHMETIC)` (120 digits, `ROUND_HALF_EVEN`), and compares that result to the literal with `==`.
  - Every other literal, such as `CAD 4720`, `USD 1800` or `"0"`, is compared exactly: `Decimal(response) == Decimal(literal)`.
  - Neither comparison is a string comparison. `4720.0000` equals `4720`.
- Why: a cross-currency conversion that does not terminate is held at 120 significant digits. A sum of such rows can then differ from its true value far below the 18th place, even when the true value terminates. The AC-02 TWD `/total` cost is the case on `main`. CAD 600 and CAD 2200 each convert to a non-terminating TWD amount, and with USD 800 the sum is 89600 plus 1E-115.
- The rule does not depend on the summation order (by row, by class or by total line). Every tail in these fixtures is below 1E-18 by many orders of magnitude.
- Only the test's parsed copy is quantized, and nothing is emitted again. `calculate`, `build_document`, the DTOs, the cache and the export never round or quantize. The response carries `format(value, 'f')` of the calculated `Decimal`, as `DecimalString` in Part C says, and each emitted string is checked against `DecimalString`. Rounding for display belongs to the pages (ANL-012B to 012D), not to this contract.
- A new oracle literal for a converted amount that may carry a tail is written with 18 fractional digits.

| AC | Case | Expected |
|---|---|---|
| 01 | Securities only, in CAD, USD and TWD | `/securities` value `available`: CAD 2200 (10 × 100 × 1.4 + 800), USD 1571.428571428571428571, TWD 50285.714285714285714286. Cost: CAD 1720 (800 × 1.4 + 600), USD 1228.571428571428571429, TWD 39314.285714285714285714. Gain: CAD 480 (200 × 1.4 + 200), USD 342.857142857142857143, TWD 10971.428571428571428571. Row A has `value_basis` `source_reported` and the code `source_reported_value`. `/total` value equals the securities value. |
| 01 | Same, the empty lines | `/total` lines: `crypto` is `unavailable` [`no_eligible_acquisitions`] and `cash` is `unavailable` [`no_positions`], both with null amounts. `/crypto`: value `unavailable` [`no_eligible_acquisitions`], `known_subtotal` and `complete_total` null, `crypto.state` `no_eligible_acquisitions`, `btc_equivalent_quantity` null. A walk of the whole `/crypto` document finds no decimal-string field equal to zero. |
| 01 | No accepted root | All three values `unavailable`: [`no_positions`] for `/securities` and `/total`, [`no_eligible_acquisitions`] for `/crypto`. `fact_generation.accepted` is `"0"`. |
| 01 | PostgreSQL: a new commit generation | The first read is CAD 2200 at generation g. Seed the BTC purchases through the operator connection, as the ANL-008 fixture does, and raise `accepted_generation`. The next read is CAD 4720 at g + 1 with a new `calculation_id`, so no stale cache entry is served. |
| 02 | G07 with G05 | `/total` value: CAD 4720, USD 3371.428571428571428571, TWD 107885.714285714285714286. `/total` cost: CAD 3920, USD 2800.000000000000000000, TWD 89600.000000000000000000. `/total` gain: CAD 800, USD 571.428571428571428571, TWD 18285.714285714285714286. `/crypto` value: CAD 2520, USD 1800, TWD 57600, with quantity `0.030` and `crypto.state` `tracked`. `/crypto` cost CAD 2200 (G08). `/crypto` gain: CAD 320, USD 228.571428571428571429, TWD 7314.285714285714285714. With item 3 (a): `spending` CAD 2200 with 2 of 2 counted, and `purchase_rate` CAD 73333.333333333333333333 (18 places). |
| 02 | Bitcoin counted once: a 0.030 TRANSFER, a 0.030 exchange balance snapshot and a mirrored 0.010 BUY added | The same totals, under the same comparison rule. `excluded` shows `not_acquisition` 1, `balance_observation` 1 and `mirror` 1. |
| 02 | Bitcoin counted once: a Bitcoin ETF security (CAD 100 source value) added | `/securities` CAD 2300, `/crypto` CAD 2520 and `/total` CAD 4820. The ETF row is `securities`. |
| 02 | Decision 12: 0.030 bought and 0.030 sold, with no quote | `/crypto` value `available` `"0"`, `crypto.state` `tracked`, quantity `"0.000"`, and `sales_counted` set. It differs from the empty case above. |
| 03 | G09: DEMO-B market value unknown | `/securities` CAD: `partial`, known 1400, complete null, reasons [`value_unavailable`]. Row B has null `value` and the gap `value_unavailable`. `/total` known: CAD 3920, USD 2800, TWD 89600, all with complete null. |
| 03 | No TWD rate | TWD `/total`: `unavailable`, both amounts null, [`fx_unavailable`]; every row has `fx_unavailable`. CAD `/total` stays complete at 4720 with no `fx_unavailable` anywhere. USD `/total` stays complete at 3371.428571428571428571. |
| 03 | No CAD rate | CAD `/total`: `partial`, known 800 (DEMO-B only), complete null, [`fx_unavailable`]. USD `/total`: `partial`, known 2800, complete null, [`fx_unavailable`]; only row B lacks its value. |
| 03 | No BTC quote | `/crypto` value `unavailable` [`quote_unavailable`], quantity `0.030`, `crypto.state` `tracked`. `/total` CAD: known 2200, complete null. `references.btc.status` is `unavailable`. |
| 03 | Cost of y unknown | The crypto row cost is null with `cost_unavailable`, so the `/crypto` cost figure is `unavailable` [`cost_unavailable`]. With item 3 (a): `spending` `partial`, known CAD 700, 1 of 2 counted; `purchase_rate` `unavailable` [`cost_unavailable`]. |
| 04 | PostgreSQL: users A and B in separate tenants with different synthetic holdings and distinct account labels | A gets A's literals and B gets B's. Neither response contains the other's account labels, instrument IDs or amounts. `?currency=CAD&portfolio_id=<B>` returns 422 `invalid_input`. A read after B's still returns A's values. No session returns 401. |
| 04 | Default suite: the Boundary, with `Auth` patched as in `tests/test_web_v2_imports.py` and a recording stub service | `?currency=CAD&portfolio_id=<B>`, `&user_id=<B>`, `&tenant_id=<B>`, a repeated `currency`, a missing `currency` and an unknown key each return 422 `invalid_input`, and the stub service is never called. No session returns 401 before any query check. No analysis request calls `admit`. |
| 04 | Pure: the cache | Two principals with equal generations and equal inputs get separate entries and documents. Changing the currency, a generation, the incarnation or the restore epoch misses the cache. |
| 01 | Pure: entity metadata. Account A is pinned at v1 (label "Old") by BUY x and at v2 (label "New", same role and category) by BUY y; `entities` holds v2 | One crypto row for A, with label "New". Every amount equals the G07 oracle above. |
| 01 | Pure: A absent from `entities`, one pinned version | The row shows the pinned label. |
| 01 | Pure: A absent from `entities`, two pinned versions | `ProjectionUnavailable('projection_reference_missing')`; the service answers 503 `analysis_unavailable` and caches nothing. |
| 01 | Pure: the shown account's `role`, or the shown instrument's `kind`, differs from a pinned version | `ProjectionUnavailable('projection_head_inconsistent')`. |
| 01 | Pure: a null `ticker` and an empty label | They arrive as `null` and `""`. No `label` equals any UUID in the document. |
| 01 | PostgreSQL: metadata rename | Seed with mapping rows. Append account v2 with a new label and revision 2 of A's mapping, and raise `mapping_generation` by one. The next read shows the new label and `fact_generation.mapping` g + 1, has a new `calculation_id` and is not served from the cache. Every amount is unchanged. |
| 01 | PostgreSQL: re-pointed mapping | Append revision 2 of A's only mapping targeting another account, and raise `mapping_generation`. A's rows show A's own label (rule 1, step 2). |
| 05 | Export (default suite) | The three paths are GET with a required `currency` enum of CAD, USD and TWD. The response component property sets equal a literal list in the test. Every `DecimalString` property is `type: string` with the pattern. A walk finds no `number` type. The only `integer` properties are `contract_version`, `counted_count`, `position_count`, `purchases_counted`, `sales_counted_count` and the `excluded` values. The export equals `tests/fixtures/web_v2/analysis-openapi.json` byte for byte. |
| 05 | Default suite: live OpenAPI, with `Auth` patched | `/api/v2/openapi.json` on `ingestion` contains the same three paths and component schemas as the export, and the import operations and components stay as `test_ac_01_openapi_frozen_schema_equality` expects. On `identity` and `sources` it contains none of the analysis paths, and they return 404 `not_found`. |
| 05 | Default suite: component names | The analysis component names and the import component names are disjoint. |
| 05 | PostgreSQL: live OpenAPI | One read of `/api/v2/openapi.json` on the real ingestion app contains the three analysis paths. |

Also in the default suite:

- `tests/test_projection_references.py`, with a fake `fetch` and a fake clock, and no network:
  - a candle up to five minutes old becomes a quote, and an older one gives `btc` `None`;
  - synthetic Bank of Canada JSON and CBC HTML give the rates, and a rate eleven days old is missing;
  - an `OSError`, a `TimeoutError`, bad JSON or HTTP 500 leaves out only that piece and raises nothing;
  - within 60 s there is one fetch per source and the same `valuation_time`; at 61 s only Bitcoin is fetched again; a failed source waits `retry_seconds`; while one caller is blocked inside a refresh, a second caller gets the previous snapshot at once;
  - only the three hosts are requested, each with timeout 4;
  - nothing is written to a temporary working directory, and no value appears in the captured logs;
  - `inputs()` maps to `FxTable('USD', …)`, with its oldest date as `as_of`, or to `None` when there is no rate.
- `tests/test_projection_entities.py`, on synthetic rows: a current mapping wins over an older revision of the same mapping; across mapping IDs the newest plan wins; within one plan, the higher revision and then the mapping ID decide; a re-pointed ID takes the newest row that ever targeted it; a missing entity row or plan raises `projection_reference_missing`; an ID with no mapping row is absent.
- `tests/test_web_v2_analysis.py`, besides the oracles:
  - every `ProjectionUnavailable` code and a `PersistenceError` map to the status and code in Part D;
  - a failing `References` never becomes 500;
  - a `currency` that is missing, is `cad`, is `EUR` or is repeated returns 422;
  - the JSON text of a document contains none of `custody`, `wallet`, `opening` or `self-custod`;
  - a decimal amount never arrives as a float;
  - the existing ANL-008 tests pass unchanged after Part B;
  - the API does not round (AC-02, item 5). In the G07 case, the USD `/total` value and gain strings each have more than 18 fractional digits. In CAD, USD and TWD, the `/total` value strings `known_subtotal` and `complete_total` equal `format(x, 'f')`, where x is `calculation.total.known_subtotal[currency]` or `calculation.total.complete_total[currency]` from `calculate` on the same inputs. The test does not assert the size of the TWD cost tail, which depends on the summation order.
- The existing `tests/test_web_v2_imports.py` and `tests/test_web_v2_api.py` pass unchanged. Their `FakeAuth` has no `financial`, so this also checks that `create_app` reads the database lazily.
- PostgreSQL HTTP tests (`tests/test_web_v2_analysis_postgres.py`, skipped unless `KURAFOLIO_INGESTION_TEST=1`):
  - Build the app as `tests/test_postgres_import_routes.py` does: a disposable database per test class or test, `migrate_sources` then `migrate_ingestion` with a synthetic worker role, `ready=true`, then `create_app(Settings(..., schema_profile='ingestion', worker_role=...), references=FixedReferences(snapshot))`. Sign in through the real login route.
  - Seed accepted facts through the operator connection as `ProjectionAcceptedPostgresTests.seed` does. Moving that seeding into a shared support module under `tests/` is allowed if its behaviour stays the same and both existing PostgreSQL suites still pass.
  - The analysis suite also needs `wl_ingestion.mappings` rows. Without them every row would use the rule 3 fallback. Add an opt-in `mapping_rows=True` to the seed that writes one row per entity: revision 1, the seed's plan ID, a synthetic `connection_id` and `source_key`, and the entity's `(id, version)`. The default stays off, so the ANL-008 suite runs unchanged. The metadata cases append rows through the operator connection and raise `roots.mapping_generation` themselves.
  - Use the claim's `isolation_id` and `port_base`. A skipped test is not acceptance.
- Every test names its acceptance ID.

### Negative cases and failure handling

- An unknown amount is null with a reason, never `"0"`. An empty scope is a typed state. A known zero appears only for the Decision 12 tracked zero, for supported zero cash and for a real zero quantity.
- Amounts in two report currencies are never added. A response carries one `report_currency`, and `native_known` stays per currency.
- A reference failure degrades to a typed gap. A projection or database failure maps to a fixed code with no SQL, rows or values. A response that fails its model is never sent.
- A cache entry is keyed by user, tenant, portfolio, scope, currency, both generations and the calculation identifier. An entry that fails validation is never stored.

### Rollback

The change is code only: no schema, migration, grant or stored data. Reverting the pull request removes the routes and the cache, and a restart clears the cache anyway. `--no-reference-fetch` turns off the egress without a revert. Frontend pages do not exist yet, so nothing in the browser depends on the routes.

### Do not touch

- `prices.py`, `fx.py`, the shipped `web/` application and `scripts/export_web_schema.py`.
- The behaviour of `calculate` and `read_accepted_state`. Part B is a refactor checked by the unchanged ANL-008 tests.
- Ingestion SQL, migrations and grants; `identity_schema.py` and `source_schema.py` budgets; and `market/`.
- IMP-007E's profile and import route code, except for adding the analysis branch next to it.
- Frontend pages and components. ANL-012B builds them.

### Stop and ask if

- The merged `ingestion` profile does not let `RequestDatabase` open a read-only transaction on `0004_ingestion` under the runtime login, or that login lacks SELECT on a table `read_accepted_state` reads.
- `main` has a migration after `0004_ingestion` (APP-011I and APP-011E plan one). `projection.accepted.SUPPORTED_REVISIONS` would then refuse it, and changing that contract is a planner decision.
- An ANL-008 test changes or fails after Part B.
- An oracle above disagrees with the code under the comparison rule, or a Figure that is not `available` has no reason.
- An oracle would pass only if `calculate`, `build_document`, the DTOs, the cache or the export rounded or quantized a value.
- A case reaches an ANL-008 deferred gap:
  - a broker crypto holding together with BUY activities on the same account and instrument;
  - a BUY across several groups, beyond the purchase-rate refusal;
  - several coverage entries for one account.
- A real accepted value fails `DecimalString`, `Text` or `TimeToken`.
- The frontend checks refuse the generated file.
- A reviewer requires a per-user analysis rate limit.
- Any of the three reference sources needs a key, refuses the request or changes its format.
- An existing test in `tests/test_web_v2_imports.py`, `tests/test_web_v2_api.py` or `tests/test_postgres_import_routes.py` has to change.
- An analysis component name would have to collide with an import component name.
- A fixture built through the acceptance functions gives one entity ID two versions, or fails the identity check in "Entity metadata".
- A consumer or a reviewer requires an instrument name field, a field saying which metadata version is shown, or a typed "unavailable" in place of the 503 of rule 3. Each of these changes the contract.
- `read_current_entities` would need a column or table outside the runtime grants named in Context.

### Verify

```bash
PYTHONPATH=src:tests .venv/bin/python -m unittest tests.test_projection_references tests.test_web_v2_analysis tests.test_projection_positions tests.test_web_v2_imports tests.test_web_v2_api -v
KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src:tests .venv/bin/python -m unittest tests.test_web_v2_analysis_postgres tests.test_projection_accepted_postgres tests.test_postgres_import_routes -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/export_web_v2_analysis_schema.py --output work/analysis-openapi.json
cmp work/analysis-openapi.json tests/fixtures/web_v2/analysis-openapi.json
npm --prefix frontend run format:check && npm --prefix frontend run build && npm --prefix frontend test
.venv/bin/python scripts/check_language.py
python3 scripts/tickets.py spec ANL-012A --base origin/main
python scripts/check_pr_image.py
```

The opt-in PostgreSQL run uses the isolated environment of the claim (see `docs/web-v2-identity.md` and the setup of `tests/test_postgres_import_routes.py`), with `requirements-web-test.lock` installed.

## Plan

- [x] Owner Gate A on the contract (2026-11-10).
- [x] Owner answers Decisions needed items 1 to 3 (2026-11-22, "Accept all recommended": option (a) of each).
- [x] IMP-007E is `done` (PR #115).
- [x] Build plan rechecked against `main` at `574896b`.
- [x] The recheck pull request merges (#122).
- [x] Build plan amended for the Part C entity metadata rules (2026-11-26).
- [x] The amendment pull request merges (#123).
- [x] Build plan amended for the oracle comparison rule (2026-11-26, item 5).
- [ ] The comparison amendment pull request merges.
- [x] Part A: reference inputs and `tests/test_projection_references.py`.
- [ ] Part B: calculator helpers; the ANL-008 tests pass unchanged.
- [ ] Part C: DTOs and `build_document`, with the pure oracles for AC-01 to AC-03 and the cache test for AC-04.
- [ ] Part D: service, routes and Boundary changes, with the default-suite Boundary and OpenAPI tests for AC-04 and AC-05 and the PostgreSQL HTTP tests for AC-01, AC-02, AC-04 and AC-05.
- [ ] Part E: schema export, generated types and docs; export test for AC-05.
- [ ] Independent QA and Architect review (frontier); repairs.

## Decisions needed

None open. On 2026-11-22 the owner answered items 1 to 3 with "Accept all recommended". The recheck of 2026-11-26 found that item 1 (a) is now satisfied: IMP-007E merged in #115 with the `ingestion` profile, and the recheck raised no new question. Items 4 and 5 were raised and answered during the build on 2026-11-26. Each item below keeps its question and options for the record and states the option taken; the Build plan implements each as a rule.

1. **The routes need the `ingestion` runtime profile.** Accepted facts exist only in a `0004_ingestion` database, and no profile on `main` serves one (Context, "Findings"). IMP-007E Part A adds that profile, but this ticket's `depends_on` lists only ANL-008. The routes also edit `web_v2/api.py` and `schemas.py`, which IMP-007E, IMP-007U, APP-011I and APP-011E change under the `identity-api` resource.
   - (a) Add IMP-007E to `depends_on` and `identity-api` to `resources`. The ticket is built after IMP-007E merges, and it moves from step 2 to step 3 of ROADMAP.md "Step 1". ANL-012B builds against a mocked contract, so it does not wait. The gated "may start after ANL-008" refers to not waiting for MKT-009, and it does not change.
   - (b) Split the ticket. Parts A to C (pure, no route) are built now. A new child carries Parts D and E and AC-04 and AC-05 after IMP-007E. This changes gated acceptance criteria, so it needs a new Gate A.
   - (c) Build an ingestion profile here. That duplicates IMP-007E Part A on the same files and resource.
   - Recommendation: (a). Changing `depends_on` and `resources` of an approved ticket needs the owner's confirmation in its Log.
   - Resolved 2026-11-22 ("Accept all recommended"): (a). The front matter now lists IMP-007E in `depends_on` and `identity-api` in `resources`. The owner's confirmation is in the Log.
2. **The value series in the first version.**
   - The texts disagree:
     - The owner decision of 2026-11-10 says each response includes a daily series.
     - The "MVP order" decision moves the daily series to MKT-009D.
     - MKT-009D's Requirements add `value_series` "in a backward-compatible way", but its Context says the first version has "one point per import date".
     - ANL-012B, 012C and 012D say the chart "plots import dates" until MKT-009.
   - `read_accepted_state` reads current heads only, and no historical Bitcoin price or FX exists before MKT-009D.
   - (a) Leave the field out. MKT-009D adds it. Until then the pages show the chart's empty state, so the "plots import dates" line of ANL-012B to 012D waits for MKT-009D, and the owner would confirm that reading.
   - (b) One point per holdings import. Securities points use each accepted snapshot's own source values. Crypto points are `unavailable` without historical prices, and so are Total points whenever crypto exists. This needs a reader for superseded snapshot revisions beyond ANL-008, the size grows to L, and the plan returns to the planner.
   - (c) One point, the current calculation. It is cheap, but it is dated today while securities values come from their import date, so `observed` would overstate it. The shape would be `value_series: [{date, value, basis, estimated_from, reasons}]`, with `basis` in `observed`, `estimated` and `unavailable`, as MKT-009D describes.
   - Recommendation: (a). It is the smallest honest step and matches MKT-009D's Requirements. The Build plan is written for (a). For (c), add the `SeriesPoint` model and one point built from the scope's value Figure.
   - For the owner, about gated text: (a) relies on the "MVP order" sentence of this ticket's Requirements, which moves the daily series to MKT-009D. If the owner treats the sentence "Each analysis response includes a daily value series" as binding for the first version, then (a) needs revised Requirements here and a new Gate A. The "chart plots import dates" wording of ANL-012B, 012C and 012D needs the same. This pull request edits no gated text.
   - Resolved 2026-11-22 ("Accept all recommended"): (a). This plan reads the owner's choice as accepting the "MVP order" sentence for the first version, so the daily series stays with MKT-009D and no gated text changes. The "chart plots import dates" line of ANL-012B, 012C and 012D then waits for MKT-009D; those tickets are not edited here.
3. **Per-purchase crypto data for ANL-012C.** ANL-012C needs four things that `calculate` does not return: known acquisition spending with its coverage, a weighted purchase rate, a cumulative acquisitions chart and a monthly table. It sends contract changes back here.
   - (a) Include in `/crypto` the counted activity list, the `spending` Figure and the `purchase_rate`. Part B extracts the eligibility rule so that the list and the calculation share one rule. The page groups the list by month with `decimal.js`.
   - (b) Leave them out. ANL-012C then needs a new contract ticket before it can build those sections.
   - Recommendation: (a). Without it, `/crypto` carries no source date for exchange purchases either, and the Requirements ask for source dates.
   - Resolved 2026-11-22 ("Accept all recommended"): (a). Part B's shared eligibility helper and the `/crypto` fields marked "item 3 (a)" are part of the build.

4. **Which version of an account or instrument a row shows.** Raised by the builder at Part C. Facts pin `(id, version)`, but a position keeps only the IDs, and two facts of one position could pin different versions.
   - The owner's choice, as the builder's Log on the claim branch records it for 2026-11-26: "go C". Analysis shows the current account and instrument names, and historical facts keep their source-pinned metadata.
   - Resolved: Part C, "Entity metadata", implements that choice with three rules: the lookup, the invalidation and the fallback. The numbers stay on the pinned versions, and only display fields can differ. No gated text changes.

5. **How the AC-02 oracle compares a total that terminates but is summed from rows that do not.** Raised by the builder at Part C. Part C emits the calculated `Decimal` without rounding. In G07, USD 800 converts to TWD 25600 exactly, but CAD 600 and CAD 2200 each give a non-terminating TWD amount at the fixture rates. Summed in the 120-digit context, the TWD `/total` cost is 89600 plus 1E-115, so the exact literal `TWD 89600` fails the rule for terminating values.
   - (a) Keep the API value and clarify the test comparison. A figure summed from converted rows is compared at 18 places even when its true value terminates. Only the acceptance comparison changes.
   - (b) Sum the native amounts per currency before converting. This fixture would then be exact, but a total could differ from the sum of its converted rows at wire precision. It changes `calculate`, which "Do not touch" forbids, and needs a new plan.
   - Recommendation: (a).
   - The owner's choice, given on 2026-11-26 in Chinese with the request to plan this ticket and relayed by the coordinating session (in English): "clarify the acceptance comparison rule for the G07 currency-exchange rounding tail, keeping the API result unrounded."
   - Resolved: (a). "Tests and expected values" now has a comparison rule keyed on how each literal is written, and the TWD cost literal has 18 fractional digits. (b) is not taken. No calculation, DTO or wire value changes, and no gated text changes. AC-02's "equals the oracle" is read through this comparison rule, as the Build plan already read it for non-terminating values.

Answered earlier: on 2026-11-10 the owner answered yes: the first version may value securities from the import's own market values, marked "as of the source file", or from a live quote where the MKT-009A adapter is enabled. This plan uses the source values. Stored quotes arrive with MKT-009B, whose Requirements already wire them into this contract.

## Handoff

- State: Claimed by codex/gpt-6.2-sol from origin/main at 0b7d03c49. Gate A matches. IMP-007E is done, and the ingestion profile supports scoped read-only transactions on 0004.
- Next step: Refactor the calculator helpers in Part B and run the unchanged ANL-008 tests.
- Part A: Eight synthetic reference tests passed, covering source parsing, cache windows, failure isolation and concurrent refresh.
- Verify: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_web_v2_api -v` with the opt-in identity environment from [web-v2-identity.md](../docs/web-v2-identity.md)
- Gotchas: Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance.
- Open questions: None.

## Log

- 2026-11-10 planner: created from the UI/UX feature inventory (tickets/UX_FEATURE_INVENTORY.md).
- 2026-11-10 planner: recorded owner decisions on the daily series, cost and gain, cash, sales and the MVP-first order.
- 2026-11-10 planner: owner approved Gate A for the V2 MVP scope of this ticket on 2026-11-10 and released it (status ready).
- 2026-11-10 planner: dependency on MKT-009 removed for the first version by the owner's MVP decision; live stock quotes and the daily series are added when MKT-009 and MKT-009A land.
- 2026-11-11 planner: named the MKT-009 children that extend this contract after the MVP.
- 2026-11-13 planner: removed the answered decision and the stale gate wording; the ticket waits only on ANL-008.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved "Expected behaviour", "Scope", "Implementation notes" and "Owner decisions recorded 2026-11-10" from Context into Requirements and numbered the acceptance criteria AC-ANL-012A-01 to 05. Spec hash sha256:53db5ddc3a935a30bdbdefb6bc5d90d43426429e417c2ebb3db32784d205d4ee, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:53db5ddc3a935a30bdbdefb6bc5d90d43426429e417c2ebb3db32784d205d4ee.
- 2026-11-22 claude-code/opus-5.5: wrote the Build plan from `main` at `7d7acc1` in plan pull request #106 (https://github.com/gh-slee/kurafolio/pull/106). It adds Context findings, updates the Plan steps and opens Decisions needed items 1 to 3: the dependency on IMP-007E's `ingestion` profile with the `identity-api` resource, the value series in the first version, and per-purchase crypto data for ANL-012C. Gated sections and front matter are unchanged; the spec hash still matches. A build waits for the owner's answers.
- 2026-11-22 claude-code/opus-5.5: the owner answered Decisions needed items 1 to 3 with "Accept all recommended", relayed verbatim by the coordinating session of this planning conversation: option (a) of each. The same words confirm the front-matter change of item 1 (a): `depends_on` gains IMP-007E and `resources` gains `identity-api`. Gated sections, `gate_approval` and `spec_approved` are unchanged; the spec hash still matches. ROADMAP.md "Step 1" still lists ANL-012A at step 2; planner rules keep that file out of this pull request.
- 2026-11-22 claude-code/opus-5.5: at the owner's request ("Yes, separate PR"), refreshed the stale Handoff and moved this ticket to step 3 of the roadmap's Step 1, after IMP-007E. No gated section changed.
- 2026-11-26 claude-code/opus-5.5: on the owner's request "plan ANL-012A", rechecked the Build plan against `main` at `574896b` after IMP-007E merged (#115), in plan pull request #122 (https://github.com/gh-slee/kurafolio/pull/122). Updated the Context findings, Part D (Boundary lookup, query-key check and no `admit` for analysis; lazy database access in `create_app`), the OpenAPI component-name rule, the test split between the default suite and PostgreSQL, Stop-and-ask, Verify and the Plan steps. Gated sections, front matter, `gate_approval` and `spec_approved` are unchanged; the spec hash still matches. Decisions needed stays at none open.
- 2026-11-26 claude-code/opus-5.5: on the owner's request to revise the Build plan so that the builder can continue Part C, amended the plan from `main` at `d3588b2` in plan pull request #123 (https://github.com/gh-slee/kurafolio/pull/123). Added the Context findings on entity metadata, Part C "Entity metadata" (current-version lookup, invalidation through `mapping_generation`, fallback for missing metadata), the Part D transaction and cache-key changes, tests, the opt-in mapping-row seed, Stop-and-ask items, the Plan steps and the resolved Decisions needed item 4, which records the owner's "go C" from the builder's Log. Gated sections, front matter, Handoff, `gate_approval` and `spec_approved` are unchanged; the spec hash still matches.
- 2026-11-26 claude-code/opus-5.5: on the owner's request "plan ANL-012A" to clarify the acceptance comparison for the G07 exchange rounding tail while the API keeps its unrounded result (given in Chinese, quoted here in English), amended the Build plan from `main` at `9503737` in plan pull request #125 (https://github.com/gh-slee/kurafolio/pull/125). Added the literal-keyed comparison rule in "Tests and expected values", rewrote the AC-02 TWD `/total` cost as `89600.000000000000000000`, added a no-rounding test and a Stop-and-ask item, and recorded Decisions needed item 5 as resolved with option (a). Gated sections, front matter, Handoff, `gate_approval` and `spec_approved` are unchanged; the spec hash still matches.
- 2026-11-26 codex/gpt-6.2-sol: claimed the build after verifying the approved spec, the merged Build plan, and the ingestion prerequisite.
- 2026-11-26 codex/gpt-6.2-sol: implemented the reference snapshot providers and passed eight synthetic reference tests.
