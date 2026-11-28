"""Build scoped V2 analysis responses from accepted positions."""
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal, localcontext
from threading import Lock

from fastapi import Query, Request
from pydantic import ValidationError

from kurafolio.persistence.context import RequestDatabase
from kurafolio.persistence.errors import PersistenceError
from kurafolio.persistence.identity import IdentityError

from kurafolio.projection.accepted import ProjectionUnavailable, read_accepted_state
from kurafolio.projection.entities import read_current_entities
from kurafolio.projection.model import Money, calculation_id
from kurafolio.projection.positions import ARITHMETIC, calculate, convert_money, counted_activities
from kurafolio.projection.references import NoReferences

from . import schemas
from .auth import RequestError

SCOPES = ('securities', 'crypto', 'total')
ROUTE_MODELS = {'securities': schemas.SecuritiesAnalysis, 'crypto': schemas.CryptoAnalysis,
                'total': schemas.TotalAnalysis}
CURRENCIES = ('CAD', 'USD', 'TWD')
_LINES = {
    'securities': ('securities', 'cash'),
    'crypto': ('crypto',),
    'total': ('securities', 'cash', 'crypto'),
}
_ASSUMPTIONS = {
    'securities': {'missing_from_newer_snapshot_is_sold'},
    'crypto': {'acquisitions_assumed_held', 'sales_counted', 'crypto_fees_not_deducted'},
}
_ACCOUNT_IDENTITY = ('role', 'category')
_INSTRUMENT_FIELDS = ('kind', 'currency', 'ticker', 'mic', 'symbol', 'network')
_INSTRUMENT_IDENTITY = (*_INSTRUMENT_FIELDS, 'settlement_identity')


@dataclass(frozen=True, slots=True)
class _Row:
    document: dict
    value: Decimal | None
    cost: Decimal | None
    gain: Decimal | None
    gain_currency_differs: bool


def _decimal(value):
    return None if value is None else format(value, 'f')


def _amount(money):
    return None if money is None else {'amount': _decimal(money.amount), 'currency': money.currency}


def _timestamp(value):
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _pinned_entities(state):
    accounts, instruments = defaultdict(dict), defaultdict(dict)

    def add_account(account):
        accounts[account.id][account.version] = account

    def add_instrument(instrument):
        instruments[instrument.id][instrument.version] = instrument

    for head in state.holdings:
        add_account(head.account)
        for position in head.positions:
            add_account(position.account)
            add_instrument(position.instrument)
    for activity in state.activities:
        add_account(activity.source_account)
        for leg in activity.legs:
            add_account(leg.account)
            add_instrument(leg.instrument)
    return accounts, instruments


def _shown_entity(entity_id, current, pinned, identity_fields):
    versions = pinned.get(entity_id, {})
    shown = current.get(entity_id)
    if shown is None:
        if len(versions) != 1:
            raise ProjectionUnavailable('projection_reference_missing')
        shown, = versions.values()
    identity = tuple(getattr(shown, field) for field in identity_fields)
    for version in versions.values():
        if any(getattr(version, field) != value for field, value in zip(identity_fields, identity)):
            raise ProjectionUnavailable('projection_head_inconsistent')
    return shown


def _position_rows(calculation, state, entities, scope, currency, fx):
    accounts, instruments = _pinned_entities(state)
    holdings = {(position.account.id, position.instrument.id)
                for head in state.holdings for position in head.positions
                if position.instrument.kind != 'CRYPTO' or position.account.role != 'crypto'}
    position_gaps = defaultdict(set)
    for gap in calculation.gaps:
        position_gaps[gap.account_id, gap.instrument_id].add(gap.code)
    for item in calculation.positions:
        if item.asset_class not in _LINES[scope] and not (
            item.asset_class == 'unsupported' and scope != 'crypto'
        ):
            continue
        account = _shown_entity(item.account_id, entities.accounts, accounts, _ACCOUNT_IDENTITY)
        instrument = _shown_entity(item.instrument_id, entities.instruments, instruments,
                                   _INSTRUMENT_IDENTITY)
        value = item.values[currency]
        cost = convert_money(item.cost, currency, fx) if item.cost is not None else None
        gain = item.gain_values[currency]
        gaps = position_gaps[item.account_id, item.instrument_id]
        if item.cost is not None and cost is None:
            gaps.add('fx_unavailable')
        gain_currency_differs = ((item.account_id, item.instrument_id) in holdings
                                 and item.unrealized_gain is None
                                 and item.value is not None and item.cost is not None
                                 and item.value.currency != item.cost.currency)
        yield _Row({
            'asset_class': item.asset_class,
            'account': {field: getattr(account, field)
                        for field in ('id', 'label', *_ACCOUNT_IDENTITY)},
            'instrument': {field: getattr(instrument, field)
                           for field in ('id', *_INSTRUMENT_FIELDS)},
            'quantity': _decimal(item.quantity),
            'btc_equivalent': item.btc_equivalent,
            'value': _amount(item.value),
            'value_converted': _decimal(value),
            'value_basis': item.value_basis,
            'value_as_of': item.value_as_of,
            'cost': _amount(item.cost),
            'cost_converted': _decimal(cost),
            'cost_status': item.cost_status,
            'book_cost_cad': _amount(item.book_cost_cad),
            'unrealized_gain': _amount(item.unrealized_gain),
            'unrealized_gain_converted': _decimal(gain),
            'codes': list(item.codes),
            'gaps': sorted(gaps),
        }, value, cost, gain, gain_currency_differs)


def _figure(known, complete, counted, count, reasons):
    status = ('available' if complete is not None else
              'partial' if known is not None else 'unavailable')
    if status != 'available' and not reasons:
        raise ValueError('Incomplete analysis figure has no reason')
    return {'status': status, 'known_subtotal': _decimal(known), 'complete_total': _decimal(complete),
            'counted_count': counted, 'position_count': count, 'reasons': sorted(set(reasons))}


def _empty_figure(scope):
    reason = 'no_eligible_acquisitions' if scope == 'crypto' else 'no_positions'
    return _figure(None, None, 0, 0, [reason])


def _sum_figure(items, scope):
    if not items:
        return _empty_figure(scope)
    known = [amount for amount, _ in items if amount is not None]
    reasons = {reason for amount, gaps in items if amount is None for reason in gaps}
    subtotal = sum(known, Decimal(0)) if known else None
    complete = subtotal if len(known) == len(items) else None
    return _figure(subtotal, complete, len(known), len(items), reasons)


def _value_figure(rows, result, currency, scope, gaps=()):
    if not rows:
        return _empty_figure(scope)
    reasons = {reason for row in rows if row.value is None for reason in row.document['gaps']}
    return _figure(result.known_subtotal[currency], result.complete_total[currency],
                   sum(row.value is not None for row in rows), len(rows), reasons.union(gaps))


def _gain_reasons(row):
    document = row.document
    reasons = set(document['gaps'])
    if 'sales_counted' in document['codes']:
        reasons.add('sales_counted')
    if row.gain_currency_differs:
        reasons.add('value_cost_currency_differs')
    return reasons


def _references(snapshot):
    quote = snapshot.btc
    btc = ({'status': 'available', 'price': _amount(Money(quote.price, 'USD')),
            'as_of': _timestamp(quote.as_of), 'source': quote.source} if quote is not None else
           {'status': 'unavailable', 'price': None, 'as_of': None, 'source': None})
    fx = [{'currency': rate.currency, 'per_pivot': _decimal(rate.per_usd),
           'effective_date': rate.effective_date.isoformat(), 'source': rate.source}
          for rate in snapshot.fx]
    return {'btc': btc, 'fx_pivot': 'USD', 'fx': fx}


def _purchase_rate(purchases, rows):
    btc_positions = {(row.document['account']['id'], row.document['instrument']['id'])
                     for row in rows if row.document['btc_equivalent']}
    btc = [activity for activity in purchases
           if (activity.account_id, activity.instrument_id) in btc_positions]
    costs = [activity.cost for activity in btc if activity.cost is not None]
    currencies = {cost.currency for cost in costs}
    quantity = sum((activity.quantity for activity in btc), Decimal(0))
    reasons = []
    if quantity <= 0:
        reasons.append('no_eligible_acquisitions')
    if len(costs) != len(btc):
        reasons.append('cost_unavailable')
    if len(currencies) > 1:
        reasons.append('cost_currency_mixed')
    if len({activity.economic_group_id for activity in btc}) != len(btc):
        reasons.append('cost_allocation_unresolved')
    if reasons:
        return {'status': 'unavailable', 'rate': None, 'reasons': sorted(reasons)}
    currency, = currencies
    amount = sum((cost.amount for cost in costs), Decimal(0)) / quantity
    return {'status': 'available', 'rate': _amount(Money(amount, currency)), 'reasons': []}


def _crypto_detail(calculation, rows, counted, currency, fx):
    summary = calculation.crypto
    purchases = [item for item in counted if item.kind == 'BUY']
    spending = []
    for activity in purchases:
        if activity.cost is None:
            spending.append((None, ['cost_unavailable']))
        else:
            converted = convert_money(activity.cost, currency, fx)
            spending.append((converted, ['fx_unavailable'] if converted is None else []))
    return {
        'basis': summary.basis,
        'state': 'tracked' if rows else 'no_eligible_acquisitions',
        'btc_equivalent_quantity': _decimal(summary.btc_equivalent_quantity) if rows else None,
        'purchases_counted': summary.purchases_counted,
        'sales_counted': summary.sales_counted,
        'sales_counted_count': summary.sales_counted_count,
        'excluded': dict(summary.excluded),
        'activities': [
            {'economic_group_id': item.economic_group_id, 'kind': item.kind,
             'account_id': item.account_id, 'instrument_id': item.instrument_id,
             'quantity': _decimal(item.quantity), 'cost': _amount(item.cost),
             'occurred_at': item.occurred_at['token'], 'has_crypto_fee': item.has_crypto_fee}
            for item in counted
        ],
        'spending': _sum_figure(spending, 'crypto'),
        'purchase_rate': _purchase_rate(purchases, rows),
    }


def build_document(calculation, state, snapshot, scope, currency, entities, counted=None) -> dict:
    """Assemble the contract without fetching references or rounding for display."""
    with localcontext(ARITHMETIC):
        fx = snapshot.inputs(currency).fx
        rows = list(_position_rows(calculation, state, entities, scope, currency, fx))
        by_class = defaultdict(list)
        for row in rows:
            by_class[row.document['asset_class']].append(row)
        unscoped_gaps = [(gap.code, gap.account_id, gap.instrument_id)
                         for gap in calculation.gaps
                         if gap.instrument_id is None and scope in ('crypto', 'total')]
        gaps = set(unscoped_gaps)
        for row in rows:
            doc = row.document
            gaps.update((code, doc['account']['id'], doc['instrument']['id']) for code in doc['gaps'])
        crypto_reasons = {code for code, _, _ in unscoped_gaps}
        lines = []
        for name in _LINES[scope]:
            result = calculation.classes[name]
            line_reasons = crypto_reasons if name == 'crypto' else ()
            lines.append({'asset_class': name,
                          'value': _value_figure(by_class[name], result, currency, name, line_reasons),
                          'native_known': [_amount(Money(amount, native))
                                           for native, amount in sorted(result.native_known.items())]})
        if unsupported := by_class['unsupported']:
            reasons = {code for row in unsupported for code in row.document['gaps']}
            lines.append({'asset_class': 'unsupported', 'native_known': [],
                          'value': _figure(None, None, 0, len(unsupported), reasons)})
        cost_rows = [row for row in rows if row.document['cost_status'] != 'not_applicable']
        assumptions = (calculation.assumptions if scope == 'total' else
                       [code for code in calculation.assumptions if code in _ASSUMPTIONS[scope]])
        document = {
            'scope': scope,
            'contract_version': 1,
            'calculation_id': calculation.calculation_id,
            'fact_generation': {'accepted': str(calculation.accepted_generation),
                                'mapping': str(calculation.mapping_generation)},
            'valuation_time': _timestamp(calculation.valuation_time),
            'report_currency': currency,
            'references': _references(snapshot),
            'value': (_value_figure(rows, calculation.total, currency, scope, crypto_reasons)
                      if scope == 'total' else lines[0]['value']),
            'cost': _sum_figure([(row.cost, row.document['gaps']) for row in cost_rows], scope),
            'unrealized_gain': _sum_figure([(row.gain, _gain_reasons(row)) for row in cost_rows], scope),
            'lines': lines,
            'rows': [row.document for row in rows],
            'observations': [{'account_id': observation.account_id, 'observed_at': observation.observed_at,
                              'coverage_status': observation.coverage_status,
                              'position_count': observation.position_count}
                             for observation in calculation.observations],
            'assumptions': list(assumptions),
            'gaps': [{'code': code, 'account_id': account, 'instrument_id': instrument}
                     for code, account, instrument in sorted(
                         gaps, key=lambda gap: tuple(value or '' for value in gap))],
        }
        if scope == 'crypto':
            if counted is None:
                counted = counted_activities(state)
            document['crypto'] = _crypto_detail(calculation, by_class['crypto'], counted, currency, fx)
        return document


class AnalysisService:
    """Read one scoped snapshot and cache only validated response documents."""

    def __init__(self, database_of, references, *, cache_entries=64):
        self._database_of = database_of
        self._references = references
        self._no_references = NoReferences()
        self._cache_entries = cache_entries
        self._cache = OrderedDict()
        self._cache_lock = Lock()

    def read(self, principal, scope: str, currency: str) -> dict:
        try:
            snapshot = self._references.snapshot()
        except Exception:
            snapshot = self._no_references.snapshot()
        try:
            return self._read(principal, scope, currency, snapshot)
        except ProjectionUnavailable as error:
            if error.code in ('restore_required', 'projection_schema_unsupported'):
                raise IdentityError() from None
            if error.code in ('projection_reference_missing', 'projection_head_inconsistent'):
                raise RequestError('analysis_unavailable', 503) from None
            raise RequestError('internal_error', 500) from None
        except PersistenceError:
            raise IdentityError() from None
        except ValidationError:
            raise RequestError('internal_error', 500) from None

    def _read(self, principal, scope, currency, snapshot):
        context = principal.context
        database = RequestDatabase(self._database_of(), principal)
        with database.transaction(context, readonly=True) as unit:
            state = read_accepted_state(unit.connection, context)
            entities = read_current_entities(unit.connection, context)
            incarnation, restore_epoch = unit.incarnation, unit.epoch
        inputs = snapshot.inputs(currency)
        identifier = calculation_id(state, inputs)
        key = (principal.user_id, context.tenant_id, context.portfolio_id,
               incarnation, restore_epoch, scope, currency, state.accepted_generation,
               state.mapping_generation, identifier)
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        calculation = calculate(state, inputs)
        document = build_document(calculation, state, snapshot, scope, currency, entities,
                                  counted_activities(state))
        validated = ROUTE_MODELS[scope].model_validate(document).model_dump()
        with self._cache_lock:
            self._cache[key] = validated
            self._cache.move_to_end(key)
            if len(self._cache) > self._cache_entries:
                self._cache.popitem(last=False)
        return validated


def install_routes(app, service_of, errors) -> None:
    def handler(scope):
        def read(request: Request, currency: schemas.ReportCurrency = Query()):
            return service_of(request).read(request.state.principal, scope, currency)
        return read

    for scope in SCOPES:
        app.add_api_route(f'/api/v2/analysis/{scope}', handler(scope), methods=['GET'],
                          response_model=ROUTE_MODELS[scope], responses=errors)
