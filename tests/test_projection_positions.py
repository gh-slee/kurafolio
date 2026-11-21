"""Literal positions oracles from ANL-008's approved Build plan, G05--G09."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import subprocess
import sys
import unittest

from kurafolio.market.contract import DelayClass, Listing, Quote
from kurafolio.projection.model import (
    AcceptedState, Account, ActivityFact, CryptoQuote, FxTable, HoldingsHead,
    Instrument, Leg, Money, PositionFact, ValuationInputs, to_document,
)
from kurafolio.projection.positions import calculate

D = Decimal
NOW = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
TIME = {'tag': 'date_only', 'token': '2026-01-15', 'zone': None}
EXCHANGE = Account('exchange', '1', 'crypto', 'exchange', 'Synthetic exchange')
BROKER = Account('broker', '1', 'investment', 'brokerage', 'Synthetic broker')
BTC = Instrument('btc', '1', 'CRYPTO', None, None, None, 'BTC', 'bitcoin', None)
A = Instrument('a', '1', 'SECURITY', 'USD', 'DEMO-A', 'XNYS', None, None, None)
B = Instrument('b', '1', 'SECURITY', 'CAD', 'DEMO-B', 'XTSE', None, None, None)
CASH = Instrument('cad', '1', 'CASH', 'CAD', None, None, None, None, None)


def buy(name, quantity, cost='700', account=EXCHANGE, instrument=BTC, **changes):
    fact = ActivityFact(name, name + '-r1', True, False, 'BUY', 'completed', (),
                        account, (Leg(account, instrument, D(quantity), 'ACQUISITION'),),
                        None if cost is None else Money(D(cost), 'CAD'), False, TIME)
    return replace(fact, **changes)


def sale(quantity, account=EXCHANGE, **changes):
    fact = buy('sale', quantity, account=account, kind='SELL',
               legs=(Leg(account, BTC, -D(quantity), 'OTHER'),))
    return replace(fact, **changes)


def position(name, instrument=A, quantity='10', value='1000', cost='800', currency='USD', **changes):
    fact = PositionFact(name, BROKER, instrument, D(quantity),
                        None if value is None else Money(D(value), currency),
                        None if cost is None else Money(D(cost), currency), None, TIME, ())
    return replace(fact, **changes)


def head(positions, account=BROKER, coverage='partial'):
    return HoldingsHead('head-' + account.id, account, {'kind': 'all'}, 'snapshot',
                        TIME, coverage, tuple(positions))


def state(activities=(), holdings=()):
    return AcceptedState('tenant', 'portfolio', 2, 1, tuple(holdings), tuple(activities))


def inputs():
    return ValuationInputs(NOW, ('CAD', 'USD', 'TWD'),
        FxTable('USD', {'USD': D(1), 'CAD': D('1.4'), 'TWD': D(32)}, NOW, 'fixture'),
        {Listing.of('XNYS', 'DEMO-A'): Quote(Listing.of('XNYS', 'DEMO-A'), D(100), 'USD',
                                           NOW, 'fixture', DelayClass.END_OF_DAY, NOW)},
        {'BTC': CryptoQuote('BTC', D(60000), 'USD', NOW, 'fixture')})


def purchases():
    return (buy('x', '0.010'), buy('y', '0.020', '1500'))


def securities():
    return (head((position('a'), position('b', B, '8', '800', '600', 'CAD'))),)


class ProjectionPositionsTests(unittest.TestCase):
    def calc(self, activities=None, holdings=(), valuation=None):
        return calculate(state(purchases() if activities is None else activities, holdings),
                         inputs() if valuation is None else valuation)

    def test_ac_anl_008_01_fixed_oracle(self):
        """AC-ANL-008-01: literal G05 purchase oracle."""
        result = self.calc()
        item, = result.positions
        self.assertEqual(item.quantity, D('0.030'))
        self.assertEqual(item.values, {'USD': D(1800), 'CAD': D(2520), 'TWD': D(57600)})
        self.assertEqual(result.crypto.btc_equivalent_quantity, D('0.030'))
        self.assertEqual(result.crypto.purchases_counted, 2)
        self.assertEqual(result.classes['crypto'].complete_total['CAD'], D(2520))
        self.assertEqual(result.total.complete_total['CAD'], D(2520))
        self.assertIn('acquisitions_assumed_held', result.assumptions)

    def test_ac_anl_008_02_transfer_and_balance(self):
        """AC-ANL-008-02: G06 transfer and balance do not add holdings."""
        transfer = buy('transfer', '.030', kind='TRANSFER')
        balance = position('balance', BTC, '.030', account=EXCHANGE)
        result = self.calc((*purchases(), transfer), (head((balance,), EXCHANGE),))
        self.assertEqual(result.crypto.btc_equivalent_quantity, D('.030'))
        self.assertEqual(result.total.complete_total['CAD'], D(2520))
        self.assertEqual(result.crypto.excluded['not_acquisition'], 1)
        self.assertEqual(result.crypto.excluded['balance_observation'], 1)

    def test_ac_anl_008_02_independent_and_mirror(self):
        """AC-ANL-008-02: independent adds once; mirrors add nothing."""
        other = replace(EXCHANGE, id='other')
        independent = buy('independent', '.005', account=other)
        result = self.calc((*purchases(), independent))
        self.assertEqual(result.crypto.btc_equivalent_quantity, D('.035'))
        self.assertEqual(result.total.complete_total,
                         {'USD': D(2100), 'CAD': D(2940), 'TWD': D(67200)})
        mirrored = buy('mirror', '.010', account=other, mirror=True)
        result = self.calc((*purchases(), mirrored))
        self.assertEqual(result.crypto.btc_equivalent_quantity, D('.030'))
        self.assertEqual(result.crypto.excluded['mirror'], 1)

    def test_ac_anl_008_02_sales(self):
        """AC-ANL-008-02: same-account sales reduce quantity, retain purchase cost."""
        result = self.calc((*purchases(), sale('.005')))
        item, = result.positions
        self.assertEqual(item.quantity, D('.025'))
        self.assertEqual(item.values, {'USD': D(1500), 'CAD': D(2100), 'TWD': D(48000)})
        self.assertTrue(result.crypto.sales_counted)
        self.assertEqual(result.crypto.sales_counted_count, 1)
        self.assertEqual(item.cost, Money(D(2200), 'CAD'))
        self.assertIsNone(item.unrealized_gain)
        self.assertIn('sales_counted', item.codes)
        self.assertIn('sales_counted', result.assumptions)

    def test_ac_anl_008_02_excess_sales_and_account_boundary(self):
        """AC-ANL-008-02: negative quantity remains unknown and account-scoped."""
        for sold in (sale('.040'), sale('.005', replace(EXCHANGE, id='other'))):
            with self.subTest(account=sold.source_account.id):
                result = self.calc((*purchases(), sold))
                self.assertIn('sales_exceed_purchases', {gap.code for gap in result.gaps})
                self.assertIsNone(result.crypto.btc_equivalent_quantity)
                self.assertIsNone(result.total.complete_total['CAD'])
                if sold.source_account.id == 'other':
                    known = next(p for p in result.positions if p.account_id == 'exchange')
                    self.assertEqual(known.quantity, D('.030'))
                else:
                    self.assertIsNone(result.positions[0].quantity)
                    self.assertIsNone(result.positions[0].value)

    def test_ac_anl_008_02_eligibility_correction_and_funding(self):
        """AC-ANL-008-02: only active supported completed acquisitions count."""
        excluded = (buy('pending', '.1', status='pending'), buy('cancelled', '.1', status='cancelled'),
                    buy('unsupported', '.1', unsupported_reasons=('shape',)), buy('void', '.1', active=False))
        result = self.calc((*purchases(), *excluded))
        self.assertEqual(result.crypto.btc_equivalent_quantity, D('.030'))
        for code in ('pending', 'cancelled', 'unsupported', 'void'):
            self.assertEqual(result.crypto.excluded[code], 1)
        self.assertEqual(self.calc((buy('correction', '.012'), purchases()[1])).crypto.btc_equivalent_quantity,
                         D('.032'))
        result = self.calc((buy('funding', '1000', kind='FUNDING', instrument=CASH),))
        self.assertEqual(result.classes['cash'].position_count, 0)
        self.assertEqual(result.positions, ())

    def test_ac_anl_008_03_g07_security_and_combined_totals(self):
        """AC-ANL-008-03: independent G07 literals, with display rounding separate."""
        for activities, cad, usd18, twd18, shown in (
            ((), '2200', '1571.428571428571428571', '50285.714285714285714286', ('1571.43', '50285.71')),
            (purchases(), '4720', '3371.428571428571428571', '107885.714285714285714286', ('3371.43', '107885.71')),
        ):
            with self.subTest(cad=cad):
                result = self.calc(activities, securities())
                self.assertEqual(result.classes['securities'].complete_total['CAD'], D(2200))
                total = result.total.complete_total
                self.assertEqual(total['CAD'], D(cad))
                self.assertEqual(total['USD'].quantize(D('.000000000000000001')), D(usd18))
                self.assertEqual(total['TWD'].quantize(D('.000000000000000001')), D(twd18))
                self.assertEqual(tuple(format(total[c].quantize(D('.01'), rounding=ROUND_HALF_UP), 'f')
                                       for c in ('USD', 'TWD')), shown)
                self.assertIn('missing_from_newer_snapshot_is_sold', result.assumptions)

    def test_ac_anl_008_03_cash_class_and_security_bitcoin(self):
        """AC-ANL-008-03: observed cash and Bitcoin securities retain their classes."""
        cash = position('cash', CASH, '50', cost=None)
        result = self.calc(holdings=(head((*securities()[0].positions, cash)),))
        self.assertEqual(result.classes['cash'].complete_total['CAD'], D(50))
        self.assertEqual(result.total.complete_total['CAD'], D(4770))
        cash_result = next(p for p in result.positions if p.asset_class == 'cash')
        self.assertEqual(cash_result.value_basis, 'par')
        self.assertEqual(cash_result.cost_status, 'not_applicable')
        bitcoin_security = replace(A, id='bitcoin-security', ticker='BTC')
        etf = replace(A, id='bitcoin-etf', ticker='DEMO-ETF')
        result = self.calc((), (head((position('btc-security', bitcoin_security), position('etf', etf))),))
        self.assertEqual(result.classes['securities'].position_count, 2)
        self.assertEqual(result.classes['crypto'].position_count, 0)

    def test_ac_anl_008_03_liquid_and_broker_crypto(self):
        """AC-ANL-008-03: LBTC uses BTC 1:1; broker coins remain crypto."""
        lbtc = replace(BTC, id='lbtc', symbol='LBTC', network='liquid')
        result = self.calc((*purchases(), buy('liquid', '.003', instrument=lbtc)))
        self.assertEqual(result.crypto.btc_equivalent_quantity, D('.033'))
        liquid = next(p for p in result.positions if p.instrument_id == 'lbtc')
        self.assertEqual(liquid.values['USD'], D(180))
        self.assertEqual(liquid.values['CAD'], D(252))
        self.assertIn('valued_as_btc_equivalent', liquid.codes)
        result = self.calc((), (head((position('broker-coin', BTC, '.001'),)),))
        self.assertEqual(result.classes['crypto'].complete_total['CAD'], D(84))

    def test_ac_anl_008_03_no_report_or_file_dependency(self):
        """AC-ANL-008-03: isolated import and calculation never read report artifacts."""
        source = str(Path(__file__).resolve().parents[1] / 'src')
        code = '''import sys
sys.path.insert(0, SOURCE)
from kurafolio.projection.positions import calculate
from kurafolio.projection.model import AcceptedState, ValuationInputs
from datetime import datetime, timezone
import builtins
assert not any(name in sys.modules for name in ('kurafolio.source_report', 'kurafolio.source_valuation', 'kurafolio.source_projection', 'kurafolio.reporting', 'kurafolio.workbook', 'kurafolio.publishing'))
def refuse(*args, **kwargs): raise AssertionError('file read')
builtins.open = refuse
result = calculate(AcceptedState('t', 'p', 0, 0, (), ()), ValuationInputs(datetime(2026, 1, 1, tzinfo=timezone.utc), ('CAD',), None, {}, {}))
assert result.total.complete_total['CAD'] == 0
'''.replace('SOURCE', repr(source))
        subprocess.run([sys.executable, '-I', '-c', code], check=True, capture_output=True, text=True)

    def test_ac_anl_008_04_unknown_value_and_fx(self):
        """AC-ANL-008-04: G09 unknown is never a zero subtotal."""
        missing_b = replace(securities()[0].positions[1], market_value=None)
        result = self.calc(holdings=(head((securities()[0].positions[0], missing_b)),))
        self.assertEqual(result.classes['securities'].known_subtotal['CAD'], D(1400))
        self.assertIsNone(result.classes['securities'].complete_total['CAD'])
        self.assertEqual(result.total.known_subtotal['CAD'], D(3920))
        self.assertIsNone(result.total.complete_total['CAD'])
        self.assertEqual(result.total.unknown_value_count, 1)
        self.assertIn('value_unavailable', {g.code for g in result.gaps})
        valuation = inputs()
        valuation = replace(valuation, fx=replace(valuation.fx, per_pivot={'USD': D(1), 'CAD': D('1.4')}))
        result = self.calc(holdings=securities(), valuation=valuation)
        self.assertTrue(all(p.values['TWD'] is None for p in result.positions))
        self.assertIsNone(result.total.known_subtotal['TWD'])
        self.assertEqual(result.total.complete_total['CAD'], D(4720))

    def test_ac_anl_008_04_cost_and_gain(self):
        """AC-ANL-008-04: G08 purchase cost and source-native security gain."""
        result = self.calc()
        self.assertEqual(result.positions[0].cost, Money(D(2200), 'CAD'))
        self.assertEqual(result.positions[0].unrealized_gain, Money(D(320), 'CAD'))
        result = self.calc((purchases()[0], buy('missing-cost', '.020', cost=None)))
        self.assertIsNone(result.positions[0].cost)
        self.assertIsNone(result.positions[0].unrealized_gain)
        self.assertEqual(result.positions[0].cost_status, 'unavailable')
        demo = position('demo-b', replace(B, currency='USD'), '5', '125', '100', 'USD',
                        cost_cad=Money(D(150), 'CAD'))
        result = self.calc((), (head((demo,)),))
        self.assertEqual(result.positions[0].unrealized_gain, Money(D(25), 'USD'))
        self.assertEqual(result.positions[0].gain_values['CAD'], D(35))
        self.assertEqual(result.positions[0].book_cost_cad, Money(D(150), 'CAD'))
        result = self.calc((), (head((replace(demo, cost_native=None),)),))
        self.assertIsNone(result.positions[0].cost)
        self.assertIsNone(result.positions[0].unrealized_gain)

    def test_ac_anl_008_04_unsupported_and_quotes(self):
        """AC-ANL-008-04: unsupported shapes, mismatched or missing quotes fail closed."""
        unsupported = replace(B, id='unsupported', kind='UNSUPPORTED')
        result = self.calc((), (head((position('short', quantity='-3', unsupported_reasons=('signed_position',)),
                                     position('unsupported', unsupported))),))
        self.assertEqual(result.total.position_count, 2)
        self.assertIsNone(result.total.complete_total['CAD'])
        self.assertTrue({'valuation_not_implemented', 'unsupported_position'} <= {g.code for g in result.gaps})
        valuation = inputs()
        mismatch = replace(valuation.security_quotes[Listing.of('XNYS', 'DEMO-A')], currency='CAD')
        result = self.calc((), securities(), replace(valuation, security_quotes={mismatch.listing: mismatch}))
        self.assertIsNone(next(p for p in result.positions if p.instrument_id == 'a').value)
        self.assertIn('quote_currency_mismatch', {g.code for g in result.gaps})
        result = self.calc(valuation=replace(inputs(), crypto_quotes={}))
        self.assertEqual(result.positions[0].quantity, D('.030'))
        self.assertIsNone(result.positions[0].value)
        self.assertIn('quote_unavailable', {g.code for g in result.gaps})

    def test_ac_anl_008_04_corporate_action_and_partial_coverage(self):
        """AC-ANL-008-04: narrow corporate-action guard and decided partial-head rule."""
        action = buy('action', '1', instrument=A, kind='CORPORATE_ACTION', account=BROKER)
        result = self.calc((action,), securities())
        self.assertIsNone(next(p for p in result.positions if p.instrument_id == 'a').value)
        self.assertIn('corporate_action_unresolved', {g.code for g in result.gaps})
        partial = self.calc((), securities())
        complete = self.calc((), (replace(securities()[0], coverage_status='complete'),))
        self.assertIn('missing_from_newer_snapshot_is_sold', partial.assumptions)
        self.assertNotIn('missing_from_newer_snapshot_is_sold', complete.assumptions)
        self.assertEqual(partial.total.complete_total['CAD'], D(2200))
        self.assertEqual(partial.gaps, complete.gaps)

    def test_ac_anl_008_04_sale_shape_zero_fees_mixed_cost(self):
        """AC-ANL-008-04: remaining documented negative cases preserve unknowns."""
        malformed = sale('.005', legs=())
        result = self.calc((*purchases(), malformed))
        self.assertIn('sale_shape_unsupported', {g.code for g in result.gaps})
        self.assertIsNone(result.classes['crypto'].complete_total['CAD'])
        self.assertIsNone(result.total.complete_total['CAD'])
        result = self.calc((*purchases(), sale('.030')))
        self.assertEqual(result.positions[0].quantity, 0)
        self.assertEqual(result.positions[0].value.amount, 0)
        result = self.calc((replace(purchases()[0], has_crypto_fee=True), purchases()[1]))
        self.assertIn('crypto_fees_not_deducted', result.assumptions)
        mixed = replace(purchases()[1], acquisition_cost=Money(D(1500), 'USD'))
        result = self.calc((purchases()[0], mixed))
        self.assertIsNone(result.positions[0].cost)
        self.assertIn('cost_currency_mixed', {g.code for g in result.gaps})

    def test_ac_anl_008_01_to_04_document_identity_and_precision(self):
        """AC-ANL-008-01 AC-ANL-008-02 AC-ANL-008-03 AC-ANL-008-04."""
        accepted = state(purchases(), securities())
        valuation = inputs()
        original = calculate(accepted, valuation)
        document = to_document(original)
        self.assertEqual(document, to_document(calculate(accepted, valuation)))
        self.assertNotIn('float', {type(x).__name__ for x in self.walk(document)})
        text = json.dumps(document).lower()
        for forbidden in ('custody', 'wallet', 'opening', 'self-custod'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(document['crypto']['basis'], 'acquisitions_assumed_held')
        changed_quote = replace(valuation, crypto_quotes={'BTC': replace(valuation.crypto_quotes['BTC'], price=D(61000))})
        changed = calculate(accepted, changed_quote)
        self.assertNotEqual(original.calculation_id, changed.calculation_id)
        self.assertEqual(original.crypto.btc_equivalent_quantity, changed.crypto.btc_equivalent_quantity)
        self.assertNotEqual(original.calculation_id,
                            calculate(replace(accepted, accepted_generation=3), valuation).calculation_id)

    def test_ac_anl_008_04_supported_revisions(self):
        """AC-ANL-008-04: later migrations must explicitly preserve the reader contract."""
        from kurafolio.projection.accepted import SUPPORTED_REVISIONS
        versions = Path(__file__).resolve().parents[1] / 'src/kurafolio/persistence/migrations/versions'
        revisions = tuple(p.stem for p in sorted(versions.glob('*.py')) if p.stem >= '0004_ingestion')
        missing = set(revisions) - set(SUPPORTED_REVISIONS)
        message = ' '.join(f'Add {rev} to SUPPORTED_REVISIONS in src/kurafolio/projection/accepted.py after confirming it leaves READ_TABLES, wl_pg.accounts, wl_pg.instruments and the financial reader grants unchanged; otherwise stop and ask.' for rev in sorted(missing))
        self.assertEqual(SUPPORTED_REVISIONS, revisions, message)

    @classmethod
    def walk(cls, value):
        yield value
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from cls.walk(v)
        elif isinstance(value, list):
            for item in value:
                yield from cls.walk(item)


if __name__ == '__main__':
    unittest.main()
