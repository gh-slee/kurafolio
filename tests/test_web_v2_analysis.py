"""Fixed acceptance oracles for the versioned V2 analysis contract."""
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal, localcontext
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

if not all(importlib.util.find_spec(name) for name in ('fastapi', 'pwdlib')):
    raise unittest.SkipTest('Optional Web dependencies required')

from kurafolio.persistence.errors import PersistenceError
from kurafolio.projection.accepted import ProjectionUnavailable, UNAVAILABLE_CODES
from kurafolio.projection.entities import CurrentEntities
from kurafolio.projection.positions import ARITHMETIC, calculate
from kurafolio.projection.references import FixedReferences, FxRate, ReferenceSnapshot
from kurafolio.web_v2 import schemas
from kurafolio.web_v2.analysis import AnalysisService, build_document
from tests import test_projection_positions as fixture
from tests.test_web_v2_imports import FakeAuth

D = Decimal
DECIMAL_PATTERN = re.compile(r'^-?(0|[1-9][0-9]*)(\.[0-9]+)?$')


def id_(number):
    return str(UUID(int=number, version=4))


BROKER = replace(fixture.BROKER, id=id_(1))
EXCHANGE = replace(fixture.EXCHANGE, id=id_(2))
BTC = replace(fixture.BTC, id=id_(3))
A = replace(fixture.A, id=id_(4))
B = replace(fixture.B, id=id_(5))
ETF = replace(A, id=id_(6), ticker='DEMO-BTC-ETF')
EMPTY_ENTITIES = CurrentEntities({}, {})
MODELS = {'securities': schemas.SecuritiesAnalysis, 'crypto': schemas.CryptoAnalysis,
          'total': schemas.TotalAnalysis}


def purchase(number, qty, cost='700', account=EXCHANGE, **changes):
    return fixture.buy(id_(number), qty, cost, account, BTC, **changes)


def securities(*, missing_value=False, etf=False, broker=BROKER):
    rows = [
        fixture.position('a', A, account=broker),
        fixture.position('b', B, '8', None if missing_value else '800', '600', 'CAD', account=broker),
    ]
    if etf:
        rows.append(fixture.position('etf', ETF, '1', '100', '100', 'CAD', account=broker))
    return (fixture.head(rows, broker),)


def purchases():
    return purchase(10, '0.010'), purchase(11, '0.020', '1500')


def snapshot(*, quote=True, cad=True, twd=True):
    now = fixture.NOW
    fx = tuple(FxRate(currency, D(amount), now.date(), 'Synthetic FX')
               for currency, amount, enabled in (('CAD', '1.4', cad), ('TWD', '32', twd))
               if enabled)
    return ReferenceSnapshot(now, fixture.inputs().crypto_quotes['BTC'] if quote else None, fx)


def document(scope, currency, holdings=(), activities=(), reference=None, entities=EMPTY_ENTITIES,
             generations=(2, 1)):
    state = replace(fixture.state(activities, holdings), tenant_id=id_(201), portfolio_id=id_(202),
                    accepted_generation=generations[0], mapping_generation=generations[1])
    reference = snapshot() if reference is None else reference
    result = calculate(state, reference.inputs(currency))
    response = build_document(result, state, reference, scope, currency, entities)
    return MODELS[scope].model_validate(response).model_dump(), result


class AnalysisDocumentTests(unittest.TestCase):
    def amount(self, value, expected):
        self.assertIsNotNone(value)
        self.assertRegex(value, DECIMAL_PATTERN)
        parsed = D(value)
        if expected.find('.') > 0 and len(expected.split('.')[1]) == 18:
            with localcontext(ARITHMETIC):
                parsed = parsed.quantize(D('1E-18'))
        self.assertEqual(parsed, D(expected))

    def figures(self, doc, *expected):
        for key, literal in zip(('value', 'cost', 'unrealized_gain'), expected, strict=True):
            figure = doc[key]
            self.assertEqual(figure['status'], 'available')
            self.amount(figure['known_subtotal'], literal)
            self.amount(figure['complete_total'], literal)
            self.assertEqual(figure['reasons'], [])

    def unavailable(self, figure, *reasons):
        self.assertEqual(figure['status'], 'unavailable')
        self.assertIsNone(figure['known_subtotal'])
        self.assertIsNone(figure['complete_total'])
        self.assertEqual(figure['reasons'], list(reasons))

    def test_ac_01_only_securities_and_empty_crypto(self):
        """AC-ANL-012A-01: source-reported totals and an empty crypto scope."""
        for currency, value, cost, gain in (
            ('CAD', '2200', '1720', '480'),
            ('USD', '1571.428571428571428571', '1228.571428571428571429', '342.857142857142857143'),
            ('TWD', '50285.714285714285714286', '39314.285714285714285714', '10971.428571428571428571'),
        ):
            with self.subTest(currency=currency):
                doc, _ = document('securities', currency, securities())
                self.figures(doc, value, cost, gain)
                row = next(row for row in doc['rows'] if row['instrument']['id'] == A.id)
                self.assertEqual(row['value_basis'], 'source_reported')
                self.assertIn('source_reported_value', row['codes'])
                total, _ = document('total', currency, securities())
                self.assertEqual(total['value'], doc['value'])
                lines = {line['asset_class']: line['value'] for line in total['lines']}
                self.unavailable(lines['crypto'], 'no_eligible_acquisitions')
                self.unavailable(lines['cash'], 'no_positions')
                crypto, _ = document('crypto', currency, securities())
                self.unavailable(crypto['value'], 'no_eligible_acquisitions')
                self.assertEqual(crypto['crypto']['state'], 'no_eligible_acquisitions')
                self.assertIsNone(crypto['crypto']['btc_equivalent_quantity'])
                self.assert_no_decimal_zero(crypto)
                encoded = json.dumps(crypto).lower()
                for banned in ('custody', 'wallet', 'opening', 'self-custod'):
                    self.assertNotIn(banned, encoded)

    def assert_no_decimal_zero(self, value):
        if isinstance(value, dict):
            for item in value.values():
                self.assert_no_decimal_zero(item)
        elif isinstance(value, list):
            for item in value:
                self.assert_no_decimal_zero(item)
        elif isinstance(value, float):
            self.fail('Decimal amount arrived as a float')
        elif isinstance(value, str) and DECIMAL_PATTERN.fullmatch(value):
            self.assertNotEqual(D(value), 0)

    def test_ac_01_no_accepted_root(self):
        """AC-ANL-012A-01: an absent root produces typed empty documents."""
        for scope, reason in (('securities', 'no_positions'), ('total', 'no_positions'),
                              ('crypto', 'no_eligible_acquisitions')):
            doc, _ = document(scope, 'CAD', generations=(0, 0))
            self.unavailable(doc['value'], reason)
            self.assertEqual(doc['fact_generation']['accepted'], '0')

    def test_ac_02_combined_and_unrounded(self):
        """AC-ANL-012A-02: fixed G07 figures and unrounded JSON decimal strings."""
        for currency, value, cost, gain, btc_value, btc_cost, btc_gain in (
            ('CAD', '4720', '3920', '800', '2520', '2200', '320'),
            ('USD', '3371.428571428571428571', '2800.000000000000000000',
             '571.428571428571428571', '1800', '1571.428571428571428571', '228.571428571428571429'),
            ('TWD', '107885.714285714285714286', '89600.000000000000000000',
             '18285.714285714285714286', '57600', '50285.714285714285714286', '7314.285714285714285714'),
        ):
            with self.subTest(currency=currency):
                total, calculated = document('total', currency, securities(), purchases())
                self.figures(total, value, cost, gain)
                for field in ('known_subtotal', 'complete_total'):
                    self.assertEqual(total['value'][field], format(getattr(calculated.total, field)[currency], 'f'))
                if currency == 'USD':
                    for key in ('value', 'unrealized_gain'):
                        self.assertGreater(len(total[key]['complete_total'].split('.')[1]), 18)
                crypto, _ = document('crypto', currency, securities(), purchases())
                self.figures(crypto, btc_value, btc_cost, btc_gain)
                detail = crypto['crypto']
                self.assertEqual(detail['btc_equivalent_quantity'], '0.030')
                self.assertEqual(detail['state'], 'tracked')
                self.assertEqual(detail['spending']['counted_count'], 2)
                self.assertEqual(detail['spending']['position_count'], 2)
                self.amount(detail['spending']['known_subtotal'], btc_cost)
                self.amount(detail['purchase_rate']['rate']['amount'], '73333.333333333333333333')
                self.assertEqual(detail['purchase_rate']['rate']['currency'], 'CAD')

    def test_ac_02_ignored_exchange_events_and_security_etf(self):
        """AC-ANL-012A-02: transfers, mirrors and balance snapshots do not add Bitcoin."""
        transfer = purchase(12, '0.030', kind='TRANSFER')
        mirror = purchase(13, '0.010', mirror=True)
        balance = fixture.position('balance', BTC, '0.030', account=EXCHANGE)
        holdings = (*securities(), fixture.head((balance,), EXCHANGE))
        total, _ = document('total', 'CAD', holdings, (*purchases(), transfer, mirror))
        self.amount(total['value']['complete_total'], '4720')
        crypto, _ = document('crypto', 'CAD', holdings, (*purchases(), transfer, mirror))
        for code in ('not_acquisition', 'balance_observation', 'mirror'):
            self.assertEqual(crypto['crypto']['excluded'][code], 1)
        total, _ = document('total', 'CAD', securities(etf=True), purchases())
        self.amount(total['value']['complete_total'], '4820')
        self.amount(total['lines'][0]['value']['complete_total'], '2300')
        self.amount(total['lines'][2]['value']['complete_total'], '2520')
        etf = next(row for row in total['rows'] if row['instrument']['id'] == ETF.id)
        self.assertEqual(etf['asset_class'], 'securities')

    def test_ac_02_tracked_zero_keeps_null_native_value(self):
        """AC-ANL-012A-02: reported sales can leave a tracked zero without a quote."""
        sale = purchase(12, '0.030', kind='SELL',
                        legs=(fixture.Leg(EXCHANGE, BTC, D('-0.030'), 'OTHER'),))
        doc, _ = document('crypto', 'CAD', activities=(*purchases(), sale), reference=snapshot(quote=False))
        self.assertEqual(doc['value']['status'], 'available')
        self.assertEqual(doc['value']['complete_total'], '0')
        self.assertIsNone(doc['rows'][0]['value'])
        self.assertEqual(doc['rows'][0]['value_converted'], '0')
        self.assertEqual(doc['crypto']['state'], 'tracked')
        self.assertEqual(doc['crypto']['btc_equivalent_quantity'], '0.000')
        self.assertTrue(doc['crypto']['sales_counted'])

    def test_ac_03_missing_value_keeps_only_known_subtotal(self):
        """AC-ANL-012A-03: G09 leaves one unknown row and no complete total."""
        holdings = securities(missing_value=True)
        doc, _ = document('securities', 'CAD', holdings, purchases())
        self.amount(doc['value']['known_subtotal'], '1400')
        self.assertEqual(doc['value']['status'], 'partial')
        self.assertEqual(doc['value']['reasons'], ['value_unavailable'])
        row = next(row for row in doc['rows'] if row['instrument']['id'] == B.id)
        self.assertIsNone(row['value'])
        self.assertIn('value_unavailable', row['gaps'])
        for currency, known in (('CAD', '3920'), ('USD', '2800'), ('TWD', '89600')):
            total, _ = document('total', currency, holdings, purchases())
            self.assertIsNone(total['value']['complete_total'])
            self.amount(total['value']['known_subtotal'], known)

    def test_ac_03_missing_fx_is_per_currency_and_row(self):
        """AC-ANL-012A-03: absent FX does not mark rows valid in another currency."""
        for currency, known in (('CAD', '4720'), ('USD', '3371.428571428571428571')):
            doc, _ = document('total', currency, securities(), purchases(), snapshot(twd=False))
            self.amount(doc['value']['complete_total'], known)
            self.assertNotIn('fx_unavailable', json.dumps(doc))
        twd, _ = document('total', 'TWD', securities(), purchases(), snapshot(twd=False))
        self.unavailable(twd['value'], 'fx_unavailable')
        self.assertTrue(all('fx_unavailable' in row['gaps'] for row in twd['rows']))
        for currency, known in (('CAD', '800'), ('USD', '2800')):
            doc, _ = document('total', currency, securities(), purchases(), snapshot(cad=False))
            self.amount(doc['value']['known_subtotal'], known)
            self.assertEqual(doc['value']['reasons'], ['fx_unavailable'])
            self.assertIsNone(doc['value']['complete_total'])
            if currency == 'USD':
                self.assertEqual([row['instrument']['id'] for row in doc['rows']
                                  if row['value_converted'] is None], [B.id])

    def test_ac_03_missing_btc_quote_and_missing_purchase_cost(self):
        """AC-ANL-012A-03: quote failure keeps quantity and unknown cost keeps spending coverage."""
        missing_quote = snapshot(quote=False)
        crypto, _ = document('crypto', 'CAD', securities(), purchases(), missing_quote)
        self.unavailable(crypto['value'], 'quote_unavailable')
        self.assertEqual(crypto['crypto']['btc_equivalent_quantity'], '0.030')
        self.assertEqual(crypto['crypto']['state'], 'tracked')
        self.assertEqual(crypto['references']['btc']['status'], 'unavailable')
        total, _ = document('total', 'CAD', securities(), purchases(), missing_quote)
        self.amount(total['value']['known_subtotal'], '2200')
        self.assertIsNone(total['value']['complete_total'])
        crypto, _ = document('crypto', 'CAD', activities=(purchases()[0], purchase(11, '0.020', None)))
        self.unavailable(crypto['cost'], 'cost_unavailable')
        detail = crypto['crypto']
        self.assertEqual(detail['spending']['status'], 'partial')
        self.amount(detail['spending']['known_subtotal'], '700')
        self.assertEqual(detail['spending']['counted_count'], 1)
        self.assertEqual(detail['spending']['position_count'], 2)
        self.assertEqual(detail['purchase_rate'],
                         {'status': 'unavailable', 'rate': None, 'reasons': ['cost_unavailable']})

    def test_ac_03_broker_crypto_cost_currency_differs_from_quote(self):
        """AC-ANL-012A-03: an observed holding can lack a gain when its currencies differ."""
        holding = fixture.position('broker-btc', BTC, '0.010', None, '700', 'CAD', account=BROKER)
        doc, _ = document('crypto', 'CAD', (fixture.head((holding,), BROKER),))
        self.amount(doc['value']['complete_total'], '840')
        self.amount(doc['cost']['complete_total'], '700')
        self.unavailable(doc['unrealized_gain'], 'value_cost_currency_differs')
        self.assertIsNone(doc['rows'][0]['unrealized_gain'])

    def test_ac_01_current_label_and_missing_mapping_fallback(self):
        """AC-ANL-012A-01: resolved metadata affects labels but cannot change amounts."""
        renamed = replace(EXCHANGE, label='New', version='2')
        mixed = (purchases()[0], purchase(11, '0.020', '1500', account=renamed))
        current = CurrentEntities({EXCHANGE.id: renamed}, {BTC.id: BTC})
        doc, _ = document('crypto', 'CAD', activities=mixed, entities=current)
        row, = doc['rows']
        self.assertEqual(row['account']['label'], 'New')
        self.figures(doc, '2520', '2200', '320')
        self.assertIsNone(row['instrument']['ticker'])
        self.assertEqual(document('crypto', 'CAD', activities=purchases())[0]['rows'][0]['account']['label'],
                         EXCHANGE.label)
        empty_label = CurrentEntities({EXCHANGE.id: replace(renamed, label='')}, {})
        self.assertEqual(document('crypto', 'CAD', activities=mixed, entities=empty_label)[0]
                         ['rows'][0]['account']['label'], '')
        with self.assertRaises(ProjectionUnavailable) as caught:
            document('crypto', 'CAD', activities=mixed)
        self.assertEqual(caught.exception.code, 'projection_reference_missing')

    def test_ac_01_inconsistent_current_metadata_is_refused(self):
        """AC-ANL-012A-01: the display row cannot contradict its pinned identity."""
        for current in (CurrentEntities({EXCHANGE.id: replace(EXCHANGE, role='funding')}, {}),
                        CurrentEntities({}, {BTC.id: replace(BTC, kind='SECURITY')})):
            with self.assertRaises(ProjectionUnavailable) as caught:
                document('crypto', 'CAD', activities=purchases(), entities=current)
            self.assertEqual(caught.exception.code, 'projection_head_inconsistent')


ROOT = Path(__file__).resolve().parents[1]
ROUTES = [f'/api/v2/analysis/{scope}' for scope in MODELS]
FIXED_SCHEMA = ROOT / 'tests/fixtures/web_v2/analysis-openapi.json'


class AnalysisServiceTests(unittest.TestCase):
    def setUp(self):
        self.state = fixture.state((), securities())
        self.unit = SimpleNamespace(connection=object(), incarnation='first', epoch=0)
        self.context = SimpleNamespace(tenant_id=id_(101), portfolio_id=id_(102))
        self.principal = SimpleNamespace(user_id=id_(100), context=self.context)
        self.database = self.start_patch('RequestDatabase')
        self.accepted = self.start_patch('read_accepted_state', return_value=self.state)
        self.entities = self.start_patch('read_current_entities', return_value=EMPTY_ENTITIES)
        self.database.return_value.transaction.side_effect = self.transaction
        self.service = AnalysisService(lambda: object(), FixedReferences(snapshot()))

    def start_patch(self, name, **kwargs):
        patcher = patch(f'kurafolio.web_v2.analysis.{name}', **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    @contextmanager
    def transaction(self, context, *, readonly):
        self.assertTrue(readonly)
        yield self.unit

    def test_ac_04_cache_is_scoped_by_principal_currency_generations_and_realm(self):
        """AC-ANL-012A-04: a matching generation never allows cross-principal reuse."""
        build = self.start_patch('build_document', wraps=build_document)
        read = self.service.read
        first = read(self.principal, 'total', 'CAD')
        self.assertIs(read(self.principal, 'total', 'CAD'), first)
        self.assertEqual(build.call_count, 1)
        second = read(SimpleNamespace(user_id=id_(103), context=self.context), 'total', 'CAD')
        self.assertIsNot(second, first)
        read(self.principal, 'total', 'USD')
        self.accepted.return_value = replace(self.state, accepted_generation=3)
        read(self.principal, 'total', 'CAD')
        self.accepted.return_value = replace(self.accepted.return_value, mapping_generation=9)
        read(self.principal, 'total', 'CAD')
        self.unit.incarnation = 'replacement'
        read(self.principal, 'total', 'CAD')
        self.unit.epoch = 1
        read(self.principal, 'total', 'CAD')
        self.assertEqual(build.call_count, 7)
        self.accepted.assert_called_with(self.unit.connection, self.context)
        self.entities.assert_called_with(self.unit.connection, self.context)

    def test_ac_04_errors_are_bounded_and_failed_documents_are_not_cached(self):
        """AC-ANL-012A-04: a failed scoped read cannot populate the cache."""
        expected = {
            'restore_required': (503, 'instance_not_ready'),
            'projection_schema_unsupported': (503, 'instance_not_ready'),
            'projection_reference_missing': (503, 'analysis_unavailable'),
            'projection_head_inconsistent': (503, 'analysis_unavailable'),
            'projection_snapshot_required': (500, 'internal_error'),
            'projection_scope_mismatch': (500, 'internal_error'),
        }
        self.assertEqual(set(expected), UNAVAILABLE_CODES)
        for code, status in expected.items():
            with self.subTest(code=code):
                self.accepted.side_effect = ProjectionUnavailable(code)
                self.assert_read_error(status)
        self.accepted.side_effect = PersistenceError('invalid_context')
        self.assert_read_error((503, 'instance_not_ready'))
        self.accepted.side_effect = None
        build = self.start_patch('build_document', side_effect=(
            ProjectionUnavailable('projection_reference_missing'), {},
            document('total', 'CAD', securities())[0],
        ))
        self.assert_read_error((503, 'analysis_unavailable'))
        self.assert_read_error((500, 'internal_error'))
        self.service.read(self.principal, 'total', 'CAD')
        self.service.read(self.principal, 'total', 'CAD')
        self.assertEqual(build.call_count, 3)

    def assert_read_error(self, status):
        from kurafolio.persistence.identity import IdentityError
        from kurafolio.web_v2.auth import RequestError
        with self.assertRaises((RequestError, IdentityError)) as caught:
            self.service.read(self.principal, 'total', 'CAD')
        self.assertEqual((caught.exception.status, caught.exception.code), status)

    def test_ac_03_failed_references_degrade_to_availability_gaps(self):
        """AC-ANL-012A-03: a failed provider still permits a read of accepted facts."""
        class BrokenReferences:
            def snapshot(self):
                raise OSError('synthetic failure')
        self.accepted.return_value = fixture.state(purchases(), ())
        service = AnalysisService(lambda: object(), BrokenReferences())
        result = service.read(self.principal, 'crypto', 'CAD')
        self.assertEqual(result['references']['btc']['status'], 'unavailable')
        self.assertEqual(result['value']['reasons'], ['quote_unavailable'])


class AnalysisHttpTests(unittest.TestCase):
    def client(self, profile='ingestion', *, authenticated=True):
        from fastapi.testclient import TestClient
        from kurafolio.web_v2.api import create_app
        settings = SimpleNamespace(schema_profile=profile, origin='http://localhost',
                                   host='localhost', secure=False, cookie_name='session')
        with patch('kurafolio.web_v2.api.Auth', FakeAuth):
            app = create_app(settings, references=FixedReferences(snapshot()))
        client = TestClient(app, base_url=settings.origin)
        self.addCleanup(client.close)
        if authenticated:
            client.cookies.set('session', 'x' * 43)
        return client, app

    def assert_error(self, response, expected):
        self.assertEqual((response.status_code, response.json()['error']['code']), expected)

    def test_ac_04_profile_session_and_query_boundary(self):
        """AC-ANL-012A-04: scope overrides never reach the service."""
        client, app = self.client()
        calls = []

        def read(principal, scope, currency):
            calls.append((principal.user_id, scope, currency))
            return document(scope, currency, securities())[0]

        app.state.analysis = SimpleNamespace(read=read)
        for query in ('', 'currency=CAD&currency=USD', 'currency=cad', 'currency=EUR',
                      'currency=CAD&' + 'portfolio_id=' + id_(88),
                      'currency=CAD&' + 'user_id=' + id_(89),
                      'currency=CAD&' + 'tenant_id=' + id_(90), 'currency=CAD&other=0'):
            self.assert_error(client.get('/api/v2/analysis/securities?' + query),
                              (422, 'invalid_input'))
        self.assertEqual(calls, [])
        client.cookies.clear()
        self.assert_error(client.get('/api/v2/analysis/securities'), (401, 'authentication_required'))
        self.assertEqual(calls, [])
        client.cookies.set('session', 'x' * 43)
        for route in ROUTES:
            response = client.get(route + '?currency=CAD')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store, private')
        self.assertEqual(len(calls), 3)
        self.assertNotIn('admit', [call[0] for call in app.state.auth.calls])

    def test_ac_05_ingestion_only_openapi_matches_export(self):
        """AC-ANL-012A-05: analysis paths and their component schemas match the export."""
        from fastapi import FastAPI
        from kurafolio.ingestion.contracts import ROUTES as IMPORT_ROUTES
        frozen = json.loads(FIXED_SCHEMA.read_text())
        import_only = FastAPI()
        schemas.install_import_openapi(import_only,
            [route for route in IMPORT_ROUTES if route['request'] != 'RAW_BINARY'])
        import_names = set(import_only.openapi()['components']['schemas'])
        self.assertTrue(import_names.isdisjoint(frozen['components']['schemas']))
        for profile in ('ingestion', 'sources', 'identity'):
            client, _ = self.client(profile)
            live = client.get('/api/v2/openapi.json').json()
            if profile == 'ingestion':
                for path in ROUTES:
                    self.assertEqual(live['paths'][path], frozen['paths'][path])
                for name, schema in frozen['components']['schemas'].items():
                    self.assertEqual(live['components']['schemas'][name], schema)
            else:
                for path in ROUTES:
                    self.assertNotIn(path, live['paths'])
                    self.assert_error(client.get(path + '?currency=CAD'), (404, 'not_found'))

    def test_ac_05_frozen_export_and_decimal_type_contract(self):
        """AC-ANL-012A-05: fixed component field sets and explicit decimal string schemas."""
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'schema.json'
            subprocess.run([sys.executable, str(ROOT / 'scripts/export_web_v2_analysis_schema.py'),
                            '--output', str(output)], check=True, capture_output=True)
            self.assertEqual(output.read_bytes(), FIXED_SCHEMA.read_bytes())
        frozen = json.loads(FIXED_SCHEMA.read_text())
        self.assertEqual(set(frozen['paths']), set(ROUTES))
        for path in ROUTES:
            self.assertEqual(set(frozen['paths'][path]), {'get'})
            parameters = frozen['paths'][path]['get']['parameters']
            self.assertEqual(len(parameters), 1)
            parameter, = parameters
            self.assertEqual((parameter['name'], parameter['required'], parameter['in']),
                             ('currency', True, 'query'))
            self.assertEqual(parameter['schema']['enum'], ['CAD', 'USD', 'TWD'])

        base = ('contract_version calculation_id fact_generation valuation_time report_currency '
                'references value cost unrealized_gain lines rows observations assumptions gaps scope')
        expected_properties = {
            'Amount': 'amount currency',
            'FactGeneration': 'accepted mapping',
            'Figure': 'status known_subtotal complete_total counted_count position_count reasons',
            'AnalysisAccount': 'id label category role',
            'AnalysisInstrument': 'id kind currency ticker mic symbol network',
            'AnalysisRow': ('asset_class account instrument quantity btc_equivalent value '
                            'value_converted value_basis value_as_of cost cost_converted cost_status '
                            'book_cost_cad unrealized_gain unrealized_gain_converted codes gaps'),
            'ClassLine': 'asset_class value native_known',
            'Observation': 'account_id observed_at coverage_status position_count',
            'GapItem': 'code account_id instrument_id',
            'BtcReference': 'status price as_of source',
            'FxReference': 'currency per_pivot effective_date source',
            'References': 'btc fx_pivot fx',
            'SecuritiesAnalysis': base,
            'TotalAnalysis': base,
            'CryptoAnalysis': base + ' crypto',
            'CountedActivityRow': ('economic_group_id kind account_id instrument_id quantity cost '
                                   'occurred_at has_crypto_fee'),
            'PurchaseRate': 'status rate reasons',
            'CryptoDetail': ('basis state btc_equivalent_quantity purchases_counted sales_counted '
                             'sales_counted_count excluded activities spending purchase_rate'),
            'Error': 'error',
            'ErrorDetail': 'code message request_id',
        }
        schemas_by_name = frozen['components']['schemas']
        self.assertEqual(set(schemas_by_name), set(expected_properties))
        integer_fields = {'contract_version', 'counted_count', 'position_count',
                          'purchases_counted', 'sales_counted_count', 'additionalProperties'}
        for name, fields in expected_properties.items():
            with self.subTest(component=name):
                self.assertEqual(set(schemas_by_name[name]['properties']), set(fields.split()))
                self.assertFalse(schemas_by_name[name]['additionalProperties'])
                self.walk_types(schemas_by_name[name], integer_fields)

        decimal_fields = {
            'Amount': 'amount',
            'Figure': 'known_subtotal complete_total',
            'AnalysisRow': 'quantity value_converted cost_converted unrealized_gain_converted',
            'FxReference': 'per_pivot',
            'CountedActivityRow': 'quantity',
            'CryptoDetail': 'btc_equivalent_quantity',
        }
        for name, fields in decimal_fields.items():
            for field in fields.split():
                property_ = schemas_by_name[name]['properties'][field]
                typed = property_['anyOf'][0] if 'anyOf' in property_ else property_
                self.assertEqual(typed['type'], 'string')
                self.assertEqual(typed['pattern'], DECIMAL_PATTERN.pattern)

    def walk_types(self, value, integer_fields, parent=None):
        if isinstance(value, list):
            for item in value:
                self.walk_types(item, integer_fields, parent)
        elif isinstance(value, dict):
            self.assertNotEqual(value.get('type'), 'number')
            if value.get('type') == 'integer':
                self.assertIn(parent, integer_fields)
            for key, item in value.items():
                self.walk_types(item, integer_fields, key)
