# V2 analysis API

The V2 ingestion profile exposes three authenticated, read-only routes. Each
uses the portfolio in the session and requires exactly one query parameter,
`currency=CAD`, `currency=USD` or `currency=TWD`. The API has no analysis page
or daily value series yet.

| GET route | Rows | Value figure |
| --- | --- | --- |
| `/api/v2/analysis/securities` | Securities, cash and unsupported holdings | Securities only |
| `/api/v2/analysis/crypto` | Crypto | Crypto only |
| `/api/v2/analysis/total` | All classes | All classes |

Each response has `contract_version` 1, a `scope`, a `calculation_id`, a
`fact_generation` pair (`accepted`, `mapping`), a UTC `valuation_time` and a
`report_currency`. The calculation ID identifies one set of accepted facts,
mapping generation, reference inputs and reporting currency. The cache also
includes the user, tenant, portfolio, scope, instance incarnation and restore
epoch. The cache is held in memory and disappears on restart.

The `value`, `cost` and `unrealized_gain` figures provide these fields:

- `status` is `available` when all amounts are known, `partial` when only a
  subtotal is known, or `unavailable` when there is no known amount.
- `known_subtotal` sums known amounts. `complete_total` is null when the
  calculation cannot establish a total. Both are null when there are none.
- `counted_count` counts rows with an amount and `position_count` counts rows
  the figure covers. `reasons` explains missing or incomplete figures.
- The cost and gain figures omit cash, which has no applicable cost or gain.

Amounts are decimal strings. An amount with a currency is an object containing
`amount` and `currency`. The API preserves the calculated precision. The
`lines` array shows each included asset class, its value figure and its
`native_known` subtotals by currency. Native subtotals are never added across
currencies. Unsupported positions have an unavailable value.

Each row lists its asset class, account (ID, label, category and role) and
instrument (ID, kind, currency, ticker, MIC, symbol and network). The account
label comes from the current mapping when available. Historical facts keep
the versions they pinned. The row includes its quantity, whether it is
BTC-equivalent, native and converted value, valuation basis and date, native
and converted cost and unrealized gain, cost status, any CAD book cost,
assumption codes and gap codes. Source dates retain the stored time token.
Security values are source-reported until MKT-009B adds stored quotes.

`observations` gives each account's source time, coverage status and position
count. `assumptions` lists calculation conventions and `gaps` lists missing
information with account and instrument IDs where applicable.

On the crypto route, `crypto` gives the tracking basis and state, the
BTC-equivalent quantity, counted purchases and sales, exclusions, eligible
activities, a spending figure and a weighted purchase rate. Each activity
lists its economic group, kind, account, instrument, quantity, cost, source
time and crypto fee flag. The rate uses eligible BTC-equivalent buys with
known costs in a single currency and no duplicate economic group. The rate
stays in that cost currency. With no eligible acquisitions, the quantity and
amounts are null and the figure explains their absence. If purchases and
reported sales leave a known zero, the quantity and converted value show
zero. Broker cash is a separate line on Total.

## References and errors

`references` contains the latest available BTC/USD quote with its date and
source, the USD FX pivot, and any available CAD and TWD rates with their
effective dates and sources. The reference provider uses Coinbase Exchange,
Bank of Canada and CBC. It refreshes the shared snapshot after 60 seconds,
accepts a Bitcoin candle up to five minutes old, and caches FX rates for one
hour. A daily rate older than ten days is unavailable. A failed source is
retried after 60 seconds. Missing inputs can produce `quote_unavailable` or
`fx_unavailable` without discarding independently known values.

On `serve --schema-profile ingestion`, set `--no-reference-fetch` to stop
reference network requests. There is no separate per-user analysis rate limit.
The shared request concurrency limit, scoped database timeouts and shared
reference cache bound work.

| Status and code | Meaning |
| --- | --- |
| 401 `authentication_required` | The request lacks an authenticated session. |
| 404 `not_found` | This route is unavailable outside the ingestion profile. |
| 422 `invalid_input` | The query is missing a currency or contains an invalid value, repeated key or extra parameter. |
| 503 `instance_not_ready` | Storage or the instance is unavailable for a consistent scoped read. |
| 503 `analysis_unavailable` | The accepted facts or entity metadata fail a consistency check. |
| 500 `internal_error` | The request could not produce a valid analysis response. |

See the [generated OpenAPI contract](../tests/fixtures/web_v2/analysis-openapi.json)
for the full schemas and wire enums.
