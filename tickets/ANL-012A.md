---
id: ANL-012A
title: Define the V2 analysis read contract for securities, crypto and total
priority: P0
status: ready
type: feature
parent: ANL-012
depends_on: [ANL-008]
resources: [calculation-contract]
risk: high
size: M
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-11-10, V2 MVP scope as written in this ticket"
review: independent
branch:
pr:
spec:
spec_approved: sha256:53db5ddc3a935a30bdbdefb6bc5d90d43426429e417c2ebb3db32784d205d4ee
updated: 2026-11-18
---

# ANL-012A: Define the V2 analysis read contract for securities, crypto and total

## Goal

The three V2 analysis pages need one versioned read contract so they can be built in parallel with confidence and tested against fixed numbers. Today ANL-012 bundles this contract with all three pages. This child delivers only the endpoints and DTOs.

## Context

### Current behaviour

- No `/api/v2/analysis` route exists (`src/kurafolio/web_v2/api.py:26-37` lists all V2 routes).
- The shipped pages read a frozen report (`GET /api/v1/portfolios/{id}/reports/{report_id}`, `src/kurafolio/web/reports.py:293`); its DTO is edition-based and cannot refresh.
- Positions come from ANL-008 and quotes and FX from MKT-009.

### Findings from the merged code (`main` at `7d7acc1`)

- ANL-008 is merged (PR #94). `kurafolio.projection` has three parts. `read_accepted_state(connection, context)` (`projection/accepted.py:32`) reads accepted `0004` facts inside a caller-owned `REPEATABLE READ READ ONLY` transaction. `calculate(state, inputs)` (`projection/positions.py:24`) is pure. `to_document` and `calculation_id` live in `projection/model.py:225-244`. The calculator has no route and fetches nothing.
- No runtime profile on `main` can serve a `0004_ingestion` database:
  - `Database` (`persistence/context.py:47`) maps only `foundation`, `identity` and `sources`.
  - `_transaction` (`:114`) and `RequestDatabase` (`:154`) accept only `identity` and `sources`.
  - `read_accepted_state` refuses every revision except `0004_ingestion` (`projection/accepted.py:9`).
  - The ANL-008 PostgreSQL test uses a `Database` only for its pool, because "its transaction wrapper refuses 0004" (`tests/test_projection_accepted_postgres.py:92`).
  - IMP-007E Part A adds the `ingestion` profile. IMP-007E is `ready` and not merged. Decisions needed, item 1.
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
  - `error_response` turns any code outside `ERROR_CODES` into 503 `instance_not_ready` (`web_v2/api.py:57`).
  - `ProjectionUnavailable` has six codes, and none of them is in `ERROR_CODES`.
  - `Boundary.request` refuses every query string except on the invitation and source list routes (`api.py:246-248`).
- OpenAPI and frontend types:
  - `create_app` cannot build without PostgreSQL, because `Auth.__init__` calls `ready()` (`web_v2/auth.py:68`).
  - The shipped `scripts/export_web_schema.py` builds the V1 app only.
  - V2 frontend types are hand-written (`frontend/src/v2/api.ts`), and `frontend/package.json` already ships `openapi-typescript` and `decimal.js`.
- What the consumers expect from this contract:
  - ANL-012B: book cost and unrealized difference "only where cost scope matches", a cash table, the last source date, and a chart that "plots import dates" until MKT-009.
  - ANL-012C: known acquisition spending with its cost coverage, a weighted purchase rate, a cumulative acquisitions chart and a monthly table. These need per-purchase data, which `calculate` does not return today. Decisions needed, item 3.
  - RPT-013A: an export request carries a calculation identifier and a currency.
  - MKT-009B: Bitcoin is priced "from a price fetched at request time (ANL-012A, first version)".
  - MKT-009D: it adds a daily `value_series` "in a backward-compatible way", although its Context says the first version has "one point per import date". Decisions needed, item 2.
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

- Based on: `main` at `7d7acc1` ("Set OpenCode to high effort and add a per-request owner model override (#104)"). ANL-008 is merged (PR #94). IMP-007E, IMP-007U, APP-011I, APP-011E and MKT-009B are not.
- Status: this plan follows the recommended option of items 1 to 3 under Decisions needed, which are open. A builder starts only when three things are on `main`:
  - the owner's answers to items 1 to 3;
  - the owner's confirmation, in this ticket's Log, of any `depends_on` or `resources` change;
  - with item 1 (a), IMP-007E with status `done`.

  Where the owner picks another option, the item says what changes. Anything else returns the ticket to the planner.
- Shape:
  - A reference module fetches the Bitcoin price and two FX pairs at request time. It writes nothing.
  - A service reads the accepted state once per request, calculates once for the requested currency and builds the response for one of three scopes from that calculation.
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
- `src/kurafolio/web_v2/analysis.py` (new): `AnalysisService`, the pure `build_document`, the response cache and `install_routes` (Parts C and D).
- `src/kurafolio/web_v2/schemas.py`: appends the analysis models and the error code `analysis_unavailable` (Part C).
- `src/kurafolio/web_v2/api.py`: the analysis route table, its query exemption, route registration on the `ingestion` profile and the `references` argument of `create_app` (Part D).
- `src/kurafolio/web_v2/__main__.py`: the `serve --no-reference-fetch` flag (Part D).
- `scripts/export_web_v2_analysis_schema.py` (new), `tests/fixtures/web_v2/analysis-openapi.json` (new, generated), `frontend/src/v2/analysis-schema.d.ts` (new, generated), `frontend/package.json` (a prettier exclusion only) (Part E).
- Tests:
  - `tests/test_projection_references.py` (new, default suite).
  - `tests/test_web_v2_analysis.py` (new, default suite).
  - `tests/test_web_v2_analysis_postgres.py` (new, opt-in).
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

Append the models after the source models, under a comment "Analysis read contract, version 1". Every model is `Closed`.

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

#### `build_document(calculation, state, snapshot, scope, currency, counted=None) -> dict`

This function is pure. Use `localcontext(ARITHMETIC)` for every sum and conversion.

1. Rows by scope, in `calculation.positions` order:

   | Scope | Asset classes |
   |---|---|
   | `securities` | `securities`, `cash`, `unsupported` |
   | `crypto` | `crypto` |
   | `total` | all |

2. Each row comes from its `PositionResult`:
   - `account` and `instrument` come from the state's `Account` and `Instrument` with the row's IDs.
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

### Part D: service, cache and routes

`web_v2/analysis.py`:

```python
SCOPES = ('securities', 'crypto', 'total')
CURRENCIES = ('CAD', 'USD', 'TWD')

class AnalysisService:
    def __init__(self, financial, references, *, cache_entries=64): ...
    def read(self, principal, scope: str, currency: str) -> dict: ...

def install_routes(app, service_of, errors) -> None: ...
```

`read` runs in this order:

1. `snapshot = references.snapshot()`, before any database work. No network wait happens inside a transaction; the transaction timeout is 5 s.
2. Open `RequestDatabase(financial, principal).transaction(principal.context, readonly=True)`, then call `read_accepted_state(unit.connection, principal.context)`. IMP-007E Part A makes this accept the `ingestion` profile. The realm check is the first read, and the transaction runs only the reader's SELECTs.
3. Set `inputs = snapshot.inputs(currency)` and `identifier = calculation_id(state, inputs)`.
4. Build the cache key: `(principal.user_id, tenant_id, portfolio_id, scope, currency, state.accepted_generation, state.mapping_generation, identifier)`.
5. On a hit, return the cached document. On a miss:
   - call `calculate(state, inputs)`, and `counted_activities(state)` with item 3 (a);
   - call `build_document`;
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
- The handler also refuses `request.state.query` unless its keys are exactly `{'currency'}`, with 422 `invalid_input`. So `portfolio_id`, `user_id`, `tenant_id` and any other key are refused, and `query()` already refuses a repeated key.
- It returns `service_of(request).read(request.state.principal, scope, currency)`.
- `install_routes` imports no `Auth` and opens no database, so Part E can build the schema without PostgreSQL.

`web_v2/api.py`:

- `ANALYSIS_ROUTES` maps the three paths to `('GET',)`. `Boundary.request` consults it only when `settings.schema_profile == 'ingestion'`, next to the import route lookup that IMP-007E adds.
- Set `analysis_request=True` in the scope state.
- The analysis GETs are exempt from the "no query string" refusal (`api.py:246-248`), because the handler checks the keys.
- The existing order still applies: host, headers, route and method (404/405), session (401 `authentication_required`), then query parsing.
- `invalid_response` returns `internal_error` for an analysis request, as it does for a source request.
- `create_app(settings, *, frontend_root=None, references=None)`:
  - On `ingestion`, it sets `app.state.analysis = AnalysisService(auth.financial, references if references is not None else LiveReferences())` and calls `install_routes`.
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
  - `docs/web-frontend.md`: add the V2 export and generation commands next to the V1 ones.

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

A non-terminating value is compared at 18 decimal places with `quantize`, and its emitted string is checked against `DecimalString`. A terminating value is compared as an exact `Decimal`.

| AC | Case | Expected |
|---|---|---|
| 01 | Securities only, in CAD, USD and TWD | `/securities` value `available`: CAD 2200 (10 × 100 × 1.4 + 800), USD 1571.428571428571428571, TWD 50285.714285714285714286. Cost: CAD 1720 (800 × 1.4 + 600), USD 1228.571428571428571429, TWD 39314.285714285714285714. Gain: CAD 480 (200 × 1.4 + 200), USD 342.857142857142857143, TWD 10971.428571428571428571. Row A has `value_basis` `source_reported` and the code `source_reported_value`. `/total` value equals the securities value. |
| 01 | Same, the empty lines | `/total` lines: `crypto` is `unavailable` [`no_eligible_acquisitions`] and `cash` is `unavailable` [`no_positions`], both with null amounts. `/crypto`: value `unavailable` [`no_eligible_acquisitions`], `known_subtotal` and `complete_total` null, `crypto.state` `no_eligible_acquisitions`, `btc_equivalent_quantity` null. A walk of the whole `/crypto` document finds no decimal-string field equal to zero. |
| 01 | No accepted root | All three values `unavailable`: [`no_positions`] for `/securities` and `/total`, [`no_eligible_acquisitions`] for `/crypto`. `fact_generation.accepted` is `"0"`. |
| 01 | PostgreSQL: a new commit generation | The first read is CAD 2200 at generation g. Seed the BTC purchases through the operator connection, as the ANL-008 fixture does, and raise `accepted_generation`. The next read is CAD 4720 at g + 1 with a new `calculation_id`, so no stale cache entry is served. |
| 02 | G07 with G05 | `/total` value: CAD 4720, USD 3371.428571428571428571, TWD 107885.714285714285714286. `/total` cost: CAD 3920, USD 2800.000000000000000000, TWD 89600. `/total` gain: CAD 800, USD 571.428571428571428571, TWD 18285.714285714285714286. `/crypto` value: CAD 2520, USD 1800, TWD 57600, with quantity `0.030` and `crypto.state` `tracked`. `/crypto` cost CAD 2200 (G08). `/crypto` gain: CAD 320, USD 228.571428571428571429, TWD 7314.285714285714285714. With item 3 (a): `spending` CAD 2200 with 2 of 2 counted, and `purchase_rate` CAD 73333.333333333333333333 (18 places). |
| 02 | Bitcoin counted once: a 0.030 TRANSFER, a 0.030 exchange balance snapshot and a mirrored 0.010 BUY added | The same totals. `excluded` shows `not_acquisition` 1, `balance_observation` 1 and `mirror` 1. |
| 02 | Bitcoin counted once: a Bitcoin ETF security (CAD 100 source value) added | `/securities` CAD 2300, `/crypto` CAD 2520 and `/total` CAD 4820. The ETF row is `securities`. |
| 02 | Decision 12: 0.030 bought and 0.030 sold, with no quote | `/crypto` value `available` `"0"`, `crypto.state` `tracked`, quantity `"0.000"`, and `sales_counted` set. It differs from the empty case above. |
| 03 | G09: DEMO-B market value unknown | `/securities` CAD: `partial`, known 1400, complete null, reasons [`value_unavailable`]. Row B has null `value` and the gap `value_unavailable`. `/total` known: CAD 3920, USD 2800, TWD 89600, all with complete null. |
| 03 | No TWD rate | TWD `/total`: `unavailable`, both amounts null, [`fx_unavailable`]; every row has `fx_unavailable`. CAD `/total` stays complete at 4720 with no `fx_unavailable` anywhere. USD `/total` stays complete at 3371.428571428571428571. |
| 03 | No CAD rate | CAD `/total`: `partial`, known 800 (DEMO-B only), complete null, [`fx_unavailable`]. USD `/total`: `partial`, known 2800, complete null, [`fx_unavailable`]; only row B lacks its value. |
| 03 | No BTC quote | `/crypto` value `unavailable` [`quote_unavailable`], quantity `0.030`, `crypto.state` `tracked`. `/total` CAD: known 2200, complete null. `references.btc.status` is `unavailable`. |
| 03 | Cost of y unknown | The crypto row cost is null with `cost_unavailable`, so the `/crypto` cost figure is `unavailable` [`cost_unavailable`]. With item 3 (a): `spending` `partial`, known CAD 700, 1 of 2 counted; `purchase_rate` `unavailable` [`cost_unavailable`]. |
| 04 | PostgreSQL: users A and B in separate tenants with different synthetic holdings | A gets A's literals and B gets B's. Neither response contains the other's account labels, instrument IDs or amounts. `?currency=CAD&portfolio_id=<B>`, `&user_id=<B>`, `&tenant_id=<B>`, a repeated `currency` and an unknown key each return 422 `invalid_input`. A read after B's still returns A's values. No session returns 401. |
| 04 | Pure: the cache | Two principals with equal generations and equal inputs get separate entries and documents. Changing the currency or a generation misses the cache. |
| 05 | Export (default suite) | The three paths are GET with a required `currency` enum of CAD, USD and TWD. The response component property sets equal a literal list in the test. Every `DecimalString` property is `type: string` with the pattern. A walk finds no `number` type. The only `integer` properties are `contract_version`, `counted_count`, `position_count`, `purchases_counted`, `sales_counted_count` and the `excluded` values. The export equals `tests/fixtures/web_v2/analysis-openapi.json` byte for byte. |
| 05 | PostgreSQL: live OpenAPI | `/api/v2/openapi.json` on `ingestion` contains the same three paths and component schemas as the export. On `identity` and `sources` it contains none of them, and the paths return 404. |

Also in the default suite:

- `tests/test_projection_references.py`, with a fake `fetch` and a fake clock, and no network:
  - a candle up to five minutes old becomes a quote, and an older one gives `btc` `None`;
  - synthetic Bank of Canada JSON and CBC HTML give the rates, and a rate eleven days old is missing;
  - an `OSError`, a `TimeoutError`, bad JSON or HTTP 500 leaves out only that piece and raises nothing;
  - within 60 s there is one fetch per source and the same `valuation_time`; at 61 s only Bitcoin is fetched again; a failed source waits `retry_seconds`; while one caller is blocked inside a refresh, a second caller gets the previous snapshot at once;
  - only the three hosts are requested, each with timeout 4;
  - nothing is written to a temporary working directory, and no value appears in the captured logs;
  - `inputs()` maps to `FxTable('USD', …)`, with its oldest date as `as_of`, or to `None` when there is no rate.
- `tests/test_web_v2_analysis.py`, besides the oracles:
  - every `ProjectionUnavailable` code and a `PersistenceError` map to the status and code in Part D;
  - a failing `References` never becomes 500;
  - a `currency` that is missing, is `cad`, is `EUR` or is repeated returns 422;
  - the JSON text of a document contains none of `custody`, `wallet`, `opening` or `self-custod`;
  - a decimal amount never arrives as a float;
  - the existing ANL-008 tests pass unchanged after Part B.
- PostgreSQL HTTP tests: use the ingestion HTTP harness that IMP-007E's merged tests provide, and seed accepted facts as `ProjectionAcceptedPostgresTests.seed` does. Moving that seeding into a shared support module is allowed if its behaviour stays the same. Use the claim's `isolation_id`. A skipped test is not acceptance.
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

- IMP-007E is not `done`, or its `ingestion` profile does not let `RequestDatabase` open a read-only transaction on `0004_ingestion`.
- `main` has a migration after `0004_ingestion` (APP-011I and APP-011E plan one). `projection.accepted.SUPPORTED_REVISIONS` would then refuse it, and changing that contract is a planner decision.
- An ANL-008 test changes or fails after Part B.
- An oracle above disagrees with the code, or a Figure that is not `available` has no reason.
- A case reaches an ANL-008 deferred gap:
  - a broker crypto holding together with BUY activities on the same account and instrument;
  - a BUY across several groups, beyond the purchase-rate refusal;
  - several coverage entries for one account.
- A real accepted value fails `DecimalString`, `Text` or `TimeToken`.
- The frontend checks refuse the generated file.
- A reviewer requires a per-user analysis rate limit.
- Any of the three reference sources needs a key, refuses the request or changes its format.
- IMP-007E's merged tests give no way to start an `ingestion` app on a synthetic database.

### Verify

```bash
PYTHONPATH=src:tests .venv/bin/python -m unittest tests.test_projection_references tests.test_web_v2_analysis tests.test_projection_positions -v
KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src:tests .venv/bin/python -m unittest tests.test_web_v2_analysis_postgres tests.test_projection_accepted_postgres -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/export_web_v2_analysis_schema.py --output work/analysis-openapi.json
cmp work/analysis-openapi.json tests/fixtures/web_v2/analysis-openapi.json
npm --prefix frontend run format:check && npm --prefix frontend run build && npm --prefix frontend test
.venv/bin/python scripts/check_language.py
python3 scripts/tickets.py spec ANL-012A --base origin/main
python scripts/check_pr_image.py
```

The opt-in PostgreSQL run uses the isolated environment of the claim (see `docs/web-v2-identity.md` and IMP-007E's test notes), with `requirements-web-test.lock` installed.

## Plan

- [x] Owner Gate A on the contract (2026-11-10).
- [ ] Owner answers Decisions needed items 1 to 3, and the plan pull request merges. With item 1 (a), IMP-007E is `done`.
- [ ] Part A: reference inputs and `tests/test_projection_references.py`.
- [ ] Part B: calculator helpers; the ANL-008 tests pass unchanged.
- [ ] Part C: DTOs and `build_document`, with the pure oracles for AC-01 to AC-03 and the cache test for AC-04.
- [ ] Part D: service, routes and Boundary changes, with the PostgreSQL HTTP tests for AC-01, AC-02, AC-04 and AC-05.
- [ ] Part E: schema export, generated types and docs; export test for AC-05.
- [ ] Independent QA and Architect review (frontier); repairs.

## Decisions needed

Items 1 to 3 are open. Each needs the owner's answer before a build starts.

1. **The routes need the `ingestion` runtime profile.** Accepted facts exist only in a `0004_ingestion` database, and no profile on `main` serves one (Context, "Findings"). IMP-007E Part A adds that profile, but this ticket's `depends_on` lists only ANL-008. The routes also edit `web_v2/api.py` and `schemas.py`, which IMP-007E, IMP-007U, APP-011I and APP-011E change under the `identity-api` resource.
   - (a) Add IMP-007E to `depends_on` and `identity-api` to `resources`. The ticket is built after IMP-007E merges, and it moves from step 2 to step 3 of ROADMAP.md "Step 1". ANL-012B builds against a mocked contract, so it does not wait. The gated "may start after ANL-008" refers to not waiting for MKT-009, and it does not change.
   - (b) Split the ticket. Parts A to C (pure, no route) are built now. A new child carries Parts D and E and AC-04 and AC-05 after IMP-007E. This changes gated acceptance criteria, so it needs a new Gate A.
   - (c) Build an ingestion profile here. That duplicates IMP-007E Part A on the same files and resource.
   - Recommendation: (a). Changing `depends_on` and `resources` of an approved ticket needs the owner's confirmation in its Log, so this pull request does not edit the front matter.
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
3. **Per-purchase crypto data for ANL-012C.** ANL-012C needs four things that `calculate` does not return: known acquisition spending with its coverage, a weighted purchase rate, a cumulative acquisitions chart and a monthly table. It sends contract changes back here.
   - (a) Include in `/crypto` the counted activity list, the `spending` Figure and the `purchase_rate`. Part B extracts the eligibility rule so that the list and the calculation share one rule. The page groups the list by month with `decimal.js`.
   - (b) Leave them out. ANL-012C then needs a new contract ticket before it can build those sections.
   - Recommendation: (a). Without it, `/crypto` carries no source date for exchange purchases either, and the Requirements ask for source dates.

Answered earlier: on 2026-11-10 the owner answered yes: the first version may value securities from the import's own market values, marked "as of the source file", or from a live quote where the MKT-009A adapter is enabled. This plan uses the source values. Stored quotes arrive with MKT-009B, whose Requirements already wire them into this contract.

## Handoff

- State: Not started. Gate A recorded 2026-11-10 and the decision is answered. Waits only on ANL-008.
- Next step: After ANL-008 merges, write the three response models in `src/kurafolio/web_v2/schemas.py` and review them before any service code.
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
