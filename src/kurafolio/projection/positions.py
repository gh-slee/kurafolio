"""Pure accepted-position calculator with injected prices and exchange rates."""
from collections import defaultdict
from decimal import (Context, Decimal, DivisionByZero, InvalidOperation, Overflow,
                     ROUND_HALF_EVEN, localcontext)

from kurafolio.market.contract import Listing
from .model import (Calculation, ClassResult, CryptoSummary, EXCLUDED_CODES, Gap,
                    Money, ObservationResult, PositionResult, calculation_id)

_ARITHMETIC = Context(prec=120, rounding=ROUND_HALF_EVEN,
                      traps=[InvalidOperation, DivisionByZero, Overflow])
_ZERO = Decimal(0)


def _time_token(value):
    return value['token']


def calculate(state, inputs) -> Calculation:
    """Calculate without fetching, persisting, logging values or reading files."""
    with localcontext(_ARITHMETIC):
        return _calculate(state, inputs)


def _calculate(state, inputs):
    gaps = set()
    assumptions = set()
    excluded = dict.fromkeys(EXCLUDED_CODES, 0)
    positions = []
    unquoted_zeros = set()
    observations = []
    sale_shape_gap = False
    purchases_counted = 0
    sales_counted_count = 0

    def gap(code, account=None, instrument=None):
        gaps.add((code, account, instrument))

    def convert(money, currency, account, instrument):
        if money is None:
            return None
        if money.currency == currency:
            return money.amount
        fx = inputs.fx
        if fx is None:
            gap('fx_unavailable', account, instrument)
            return None
        source = Decimal(1) if money.currency == fx.pivot else fx.per_pivot.get(money.currency)
        target = Decimal(1) if currency == fx.pivot else fx.per_pivot.get(currency)
        if source is None or target is None:
            gap('fx_unavailable', account, instrument)
            return None
        return money.amount / source * target

    def result(asset_class, account, instrument, quantity, value, basis, as_of,
               cost, book_cost=None, codes=(), gain=None, cost_status=None, btc=False, known_zero=False):
        values = {currency: (_ZERO if known_zero else convert(value, currency, account.id, instrument.id))
                  for currency in inputs.report_currencies}
        gains = {currency: convert(gain, currency, account.id, instrument.id)
                 for currency in inputs.report_currencies}
        position = PositionResult(asset_class, account.id, instrument.id, quantity, btc,
            value, basis, as_of, values, cost,
            cost_status or ('known' if cost is not None else 'unavailable'),
            book_cost, gain, gains, tuple(sorted(codes)))
        if known_zero:
            unquoted_zeros.add(id(position))
        return position

    def crypto_value(account, instrument, quantity, *, tracked=False):
        btc = (instrument.symbol == 'BTC' and instrument.network == 'bitcoin'
               or instrument.symbol == 'LBTC' and instrument.network == 'liquid')
        codes = set()
        if btc and instrument.symbol == 'LBTC':
            codes.add('valued_as_btc_equivalent')
        if quantity is None:
            return None, None, btc, codes
        quote = inputs.crypto_quotes.get('BTC' if btc else instrument.symbol)
        if quote is None:
            if not (tracked and quantity == 0):
                gap('quote_unavailable', account.id, instrument.id)
            return None, None, btc, codes
        return Money(quantity * quote.price, quote.currency), quote.as_of.isoformat(), btc, codes

    corporate_actions = {leg.instrument.id for fact in state.activities
                         if fact.active and not fact.mirror and fact.kind == 'CORPORATE_ACTION'
                         for leg in fact.legs}
    for head in sorted(state.holdings, key=lambda item: item.key_digest):
        if head.account.role == 'funding':
            continue
        observations.append(ObservationResult(head.account.id, head.key_digest,
            _time_token(head.observed_at), head.coverage_status, len(head.positions)))
        if head.coverage_status != 'complete':
            assumptions.add('missing_from_newer_snapshot_is_sold')
        for fact in sorted(head.positions, key=lambda item: item.revision_id):
            account, instrument = fact.account, fact.instrument
            if instrument.kind == 'CRYPTO' and account.role == 'crypto':
                excluded['balance_observation'] += 1
                continue
            cost, gain = fact.cost_native, None
            codes = set()
            basis, as_of, value, btc = None, None, None, False
            if instrument.kind == 'CASH':
                asset_class = 'cash'
                value = Money(fact.quantity, instrument.currency)
                basis, as_of, cost = 'par', _time_token(fact.observed_at), None
                cost_status = 'not_applicable'
            else:
                cost_status = 'known' if cost is not None else 'unavailable'
                if cost is None:
                    gap('cost_unavailable', account.id, instrument.id)
                if instrument.kind == 'UNSUPPORTED':
                    asset_class = 'unsupported'
                    gap('unsupported_position', account.id, instrument.id)
                elif instrument.kind == 'CRYPTO':
                    asset_class = 'crypto'
                    value, as_of, btc, codes = crypto_value(account, instrument, fact.quantity)
                    basis = 'quote' if value is not None else None
                else:
                    asset_class = 'securities'
                    if fact.unsupported_reasons:
                        gap('valuation_not_implemented', account.id, instrument.id)
                    elif instrument.id in corporate_actions:
                        gap('corporate_action_unresolved', account.id, instrument.id)
                    else:
                        try:
                            listing = Listing.of(instrument.mic, instrument.ticker)
                        except ValueError:
                            # Admission accepts broader source tickers than the quote contract.
                            quote = None
                        else:
                            quote = inputs.security_quotes.get(listing)
                        if quote is not None:
                            if quote.currency != instrument.currency:
                                gap('quote_currency_mismatch', account.id, instrument.id)
                            else:
                                value = Money(fact.quantity * quote.price, quote.currency)
                                basis, as_of = 'quote', quote.as_of.isoformat()
                        elif fact.market_value is not None:
                            value = fact.market_value
                            basis, as_of = 'source_reported', _time_token(fact.observed_at)
                            codes.add('source_reported_value')
                        else:
                            gap('value_unavailable', account.id, instrument.id)
                if value is not None and cost is not None and value.currency == cost.currency:
                    gain = Money(value.amount - cost.amount, cost.currency)
            positions.append(result(asset_class, account, instrument, fact.quantity, value,
                basis, as_of, cost, fact.cost_cad, codes, gain, cost_status, btc))

    groups = {}
    for fact in sorted(state.activities, key=lambda item: item.economic_group_id):
        if not fact.active:
            excluded['void'] += 1
            continue
        if fact.mirror:
            excluded['mirror'] += 1
            continue
        if fact.kind not in ('BUY', 'SELL'):
            excluded['unsupported' if fact.kind in ('CORPORATE_ACTION', 'UNSUPPORTED') else 'not_acquisition'] += 1
            continue
        if fact.status in ('pending', 'cancelled'):
            excluded[fact.status] += 1
            continue
        if fact.status != 'completed' or fact.unsupported_reasons:
            excluded['unsupported'] += 1
            continue
        eligible = [leg for leg in fact.legs if leg.instrument.kind == 'CRYPTO' and (
            leg.quantity > 0 and leg.role == 'ACQUISITION' if fact.kind == 'BUY'
            else leg.quantity < 0 and leg.role != 'FEE')]
        if not eligible:
            if fact.kind == 'BUY':
                excluded['non_crypto_purchase'] += 1
            else:
                gap('sale_shape_unsupported', fact.source_account.id)
                sale_shape_gap = True
            continue
        if fact.has_crypto_fee:
            assumptions.add('crypto_fees_not_deducted')
        if fact.kind == 'BUY':
            purchases_counted += 1
        else:
            sales_counted_count += 1
            assumptions.add('sales_counted')
        # One activity may list several acquisition legs in the same position.
        by_key = defaultdict(list)
        for leg in eligible:
            by_key[(leg.account.id, leg.instrument.id)].append(leg)
        for key, legs in by_key.items():
            group = groups.setdefault(key, {'account': legs[0].account, 'instrument': legs[0].instrument,
                'purchased': _ZERO, 'sold': _ZERO, 'costs': [], 'sales': False})
            quantity = sum((leg.quantity for leg in legs), _ZERO)
            if fact.kind == 'BUY':
                group['purchased'] += quantity
                group['costs'].append(fact.acquisition_cost)
            else:
                group['sold'] -= quantity
                group['sales'] = True

    for _, group in sorted(groups.items()):
        account, instrument = group['account'], group['instrument']
        quantity = group['purchased'] - group['sold']
        if quantity < 0:
            quantity = None
            gap('sales_exceed_purchases', account.id, instrument.id)
        value, as_of, btc, codes = crypto_value(account, instrument, quantity, tracked=True)
        cost, gain = None, None
        costs = group['costs']
        if not costs or any(cost is None for cost in costs):
            gap('cost_unavailable', account.id, instrument.id)
        elif len({cost.currency for cost in costs}) > 1:
            gap('cost_currency_mixed', account.id, instrument.id)
        elif costs:
            cost = Money(sum((cost.amount for cost in costs), _ZERO), costs[0].currency)
        if group['sales']:
            codes.add('sales_counted')
        elif cost is not None and value is not None:
            converted = convert(value, cost.currency, account.id, instrument.id)
            if converted is not None:
                gain = Money(converted - cost.amount, cost.currency)
        positions.append(result('crypto', account, instrument, quantity, value,
            'quote' if value is not None else None, as_of, cost, codes=codes, gain=gain, btc=btc,
            known_zero=quantity == 0 and value is None))

    positions = tuple(sorted(positions, key=lambda item: (item.asset_class, item.account_id, item.instrument_id)))
    crypto_positions = [item for item in positions if item.asset_class == 'crypto']
    if crypto_positions:
        assumptions.add('acquisitions_assumed_held')
    btc_quantities = [item.quantity for item in crypto_positions if item.btc_equivalent]
    btc_quantity = None if None in btc_quantities else sum(btc_quantities, _ZERO)

    def aggregate(scope, incomplete=False):
        known, complete = {}, {}
        native = defaultdict(lambda: _ZERO)
        for item in scope:
            if item.value is not None:
                native[item.value.currency] += item.value.amount
        for currency in inputs.report_currencies:
            values = [item.values[currency] for item in scope if item.values[currency] is not None]
            known[currency] = sum(values, _ZERO) if values or not scope else None
            complete[currency] = known[currency] if len(values) == len(scope) and not incomplete else None
        return ClassResult(len(scope), sum(item.value is None and id(item) not in unquoted_zeros for item in scope),
                           known, complete, dict(sorted(native.items())))

    classes = {name: aggregate([item for item in positions if item.asset_class == name],
                               sale_shape_gap and name == 'crypto')
               for name in ('securities', 'cash', 'crypto')}
    return Calculation(calculation_id(state, inputs), state.tenant_id, state.portfolio_id,
        state.accepted_generation, state.mapping_generation, inputs.valuation_time,
        inputs.report_currencies, inputs.fx.as_of if inputs.fx else None,
        inputs.fx.source if inputs.fx else None, positions, tuple(observations), classes,
        aggregate(positions, sale_shape_gap), CryptoSummary('acquisitions_assumed_held',
            btc_quantity, purchases_counted, bool(sales_counted_count), sales_counted_count, excluded),
        tuple(Gap(*item) for item in sorted(gaps, key=lambda item: tuple(value or '' for value in item))),
        tuple(sorted(assumptions)))
