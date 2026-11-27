"""V2 analysis HTTP acceptance against a disposable migrated PostgreSQL instance."""
from dataclasses import replace
from decimal import Decimal, localcontext
import hashlib

from kurafolio.ingestion.codec import digest, encode
from kurafolio.projection.accepted import ProjectionUnavailable
from kurafolio.projection.entities import read_current_entities
from kurafolio.projection.positions import ARITHMETIC
from tests import test_postgres_import_routes as harness
from tests import test_projection_accepted_postgres as accepted_fixture
from tests import test_web_v2_analysis as fixture


class AnalysisPostgresTests(harness.ImportRoutesPostgresTests):
    @classmethod
    def seed(cls, conn, context, holdings=(), activities=(), *, append=False):
        return accepted_fixture.ProjectionAcceptedPostgresTests.seed.__func__(
            cls, conn, context, holdings, activities, mapping_rows=True, append=append)

    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        from fastapi.testclient import TestClient
        from pwdlib import PasswordHash

        from kurafolio.data_sources.contract_v1 import CatalogSnapshot
        from kurafolio.persistence.config import PostgresConfig
        from kurafolio.persistence.context import Database, TenantContext, execute
        from kurafolio.persistence.ingestion_migration import migrate_ingestion
        from kurafolio.persistence.source_migration import migrate_sources
        from kurafolio.projection.references import FixedReferences
        from kurafolio.web_v2.api import create_app
        from kurafolio.web_v2.config import Settings

        self.execute = execute
        self.dbname = 'wl_test_anl012a_' + accepted_fixture.identity().replace('-', '')[:12]
        with psycopg.connect(**self.admin, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(
                sql.Identifier(self.dbname), sql.Identifier(self.fixture['migration_role'])))
        configs = {kind: PostgresConfig(make_conninfo(**dict(conninfo_to_dict(
            PostgresConfig.from_secret_file(self.path / (kind + '.conninfo')).conninfo),
            dbname=self.dbname)), pool_size=1) for kind in ('migration', 'runtime', 'identity')}
        self.owner = Database(configs['migration'], schema_mode='sources')
        self.addCleanup(self.owner.close)
        catalog = CatalogSnapshot(1, '0', (), (), ())
        key_digest = hashlib.sha256(self.key).hexdigest()
        migrate_sources(self.owner, self.fixture['runtime_role'], self.fixture['identity_role'],
                        key_digest, catalog)
        self.tenants = {name: TenantContext(accepted_fixture.identity(), accepted_fixture.identity())
                        for name in ('SyntheticAlpha', 'SyntheticBeta')}
        self.alpha, self.beta = self.tenants.values()
        self.password = 'Synthetic analysis password 123'
        password_hash = PasswordHash.recommended().hash(self.password)
        with self.owner.engine.begin() as conn:
            for username, context in self.tenants.items():
                identity = {'t': context.tenant_id, 'p': context.portfolio_id}
                execute(conn, 'INSERT INTO wl_pg.tenant_roots VALUES(:t,:p)', **identity)
                execute(conn, 'INSERT INTO wl_pg.portfolios(tenant_id,portfolio_id) VALUES(:t,:p)',
                        **identity)
                execute(conn, """INSERT INTO wl_identity.users(id,portfolio_id,username,username_key,
                    argon_hash,credential_incarnation,credential_epoch,created_at)
                    SELECT :t,:p,:username,:username_key,:password,
                        incarnation,restore_epoch,clock_timestamp() FROM wl_pg.instance_state WHERE id=1""",
                        **identity, username=username, username_key=username.lower(), password=password_hash)
            execute(conn, 'UPDATE wl_identity.instance_auth_state SET bootstrap_closed=true,'
                    'admin_user_id=:admin WHERE id=1', admin=self.alpha.tenant_id)
        migrate_ingestion(self.owner, self.fixture['runtime_role'], self.fixture['identity_role'],
                          self.worker_role, key_digest, catalog)
        descriptor = encode({'plugin_id': 'synthetic.projection', 'provider_id': 'synthetic.projection',
                             'adapter_id': 'synthetic.projection'})
        type(self).installation = hashlib.sha256(descriptor).hexdigest()
        broker_a = replace(fixture.BROKER, label='Synthetic observation A')
        broker_b = replace(fixture.BROKER, label='Synthetic observation B')
        beta_a = fixture.fixture.position('other', fixture.A, value='333', cost='222', account=broker_b)
        with self.owner.engine.begin() as conn:
            execute(conn, 'UPDATE wl_pg.instance_state SET ready=true WHERE id=1')
            execute(conn, """INSERT INTO wl_sources.installations VALUES(
                :id,'synthetic.projection','synthetic.projection','synthetic.projection',:body,now())""",
                id=self.installation, body=descriptor)
            self.alpha_entities = self.seed(conn, self.alpha, fixture.securities(broker=broker_a))
            self.beta_entities = self.seed(conn, self.beta, (fixture.fixture.head((beta_a,), broker_b),))
        self.settings = Settings(configs['identity'], configs['runtime'], self.key, 'http://localhost',
                                 schema_profile='ingestion', source_catalog=catalog,
                                 worker_role=self.worker_role)
        self.app = create_app(self.settings, references=FixedReferences(fixture.snapshot()))
        self.clients = {}
        for name in self.tenants:
            client = TestClient(self.app, base_url=self.settings.origin)
            client.__enter__()
            self.addCleanup(client.__exit__, None, None, None)
            self.clients[name] = client
            token = client.get('/api/v2/auth/csrf').json()['csrf_token']
            response = client.post('/api/v2/auth/login',
                json={'username': name, 'password': self.password},
                headers={'Origin': self.settings.origin, 'X-CSRF-Token': token})
            self.assertEqual(response.status_code, 200, response.text)

    def report(self, name='SyntheticAlpha', scope='total', currency='CAD'):
        result = self.clients[name].get(f'/api/v2/analysis/{scope}?currency={currency}')
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_ac_01_02_04_05_scoped_reads_generation_and_live_contract(self):
        """AC-ANL-012A-01 AC-ANL-012A-02 AC-ANL-012A-04 AC-ANL-012A-05."""
        database = self.app.state.auth.financial
        with database.engine.begin() as conn:
            with self.assertRaises(ProjectionUnavailable) as caught:
                read_current_entities(conn, self.alpha)
            self.assertEqual(caught.exception.code, 'projection_snapshot_required')
        with database.transaction(self.alpha, readonly=True) as unit:
            with self.assertRaises(ProjectionUnavailable) as caught:
                read_current_entities(unit.connection, self.beta)
            self.assertEqual(caught.exception.code, 'projection_scope_mismatch')
        before = self.report()
        other = self.report('SyntheticBeta')
        self.assertEqual(Decimal(before['value']['complete_total']), Decimal('2200'))
        self.assertEqual(Decimal(other['value']['complete_total']), Decimal('466.2'))
        self.assertEqual({row['account']['label'] for row in before['rows']}, {'Synthetic observation A'})
        self.assertEqual({row['account']['label'] for row in other['rows']}, {'Synthetic observation B'})
        self.assertEqual({row['instrument']['id'] for row in before['rows']},
                         {value for (kind, _), value in self.alpha_entities.items() if kind == 'instrument'})
        self.assertEqual({row['instrument']['id'] for row in other['rows']},
                         {value for (kind, _), value in self.beta_entities.items() if kind == 'instrument'})
        self.assertEqual(self.report(), before)
        client = self.clients['SyntheticAlpha']
        refused = client.get('/api/v2/analysis/total?currency=CAD&portfolio_id=' + self.beta.portfolio_id)
        self.assertEqual((refused.status_code, refused.json()['error']['code']), (422, 'invalid_input'))
        self.assertEqual(client.get('/api/v2/analysis/crypto?currency=CAD').json()
                         ['crypto']['state'], 'no_eligible_acquisitions')

        with self.owner.engine.begin() as conn:
            self.seed(conn, self.alpha, activities=fixture.purchases(), append=True)
        combined = self.report()
        self.assertEqual(int(combined['fact_generation']['accepted']), int(before['fact_generation']['accepted']) + 1)
        self.assertNotEqual(combined['calculation_id'], before['calculation_id'])
        self.assertEqual(Decimal(combined['value']['complete_total']), Decimal('4720'))
        self.assertEqual(Decimal(self.report(scope='crypto')['value']['complete_total']), Decimal('2520'))
        for currency, amount in (('USD', '3371.428571428571428571'), ('TWD', '107885.714285714285714286')):
            with localcontext(ARITHMETIC):
                actual = Decimal(self.report(currency=currency)['value']['complete_total']).quantize(Decimal('1E-18'))
                self.assertEqual(actual, Decimal(amount))

        schema = client.get('/api/v2/openapi.json').json()
        self.assertTrue(set(fixture.ROUTES) <= set(schema['paths']))
        client.cookies.clear()
        unauthed = client.get('/api/v2/analysis/total?currency=CAD')
        self.assertEqual((unauthed.status_code, unauthed.json()['error']['code']),
                         (401, 'authentication_required'))

    def test_ac_01_mapping_revision_renames_and_repoint_resolves_history(self):
        """AC-ANL-012A-01: a rename changes metadata generation and a repoint keeps prior labels."""
        before = self.report()
        broker_id = self.alpha_entities['account', fixture.BROKER.id]
        renamed = 'Synthetic renamed A'
        body = {'role': fixture.BROKER.role, 'category': fixture.BROKER.category, 'label': renamed}
        new_version = digest(body)
        scope = {'tenant': self.alpha.tenant_id, 'portfolio': self.alpha.portfolio_id}
        with self.owner.engine.begin() as conn:
            self.execute(conn, """INSERT INTO wl_pg.accounts
                (tenant_id,portfolio_id,id,version,body,role,category,label)
                VALUES(:tenant,:portfolio,:account,:version,:body,:role,:category,:label)""",
                **scope, account=broker_id, version=new_version, body=encode(body).decode(), **body)
            self.append_mapping(conn, broker_id, 1, broker_id, new_version)
        after_rename = self.report()
        self.assertEqual({row['account']['label'] for row in after_rename['rows']}, {renamed})
        self.assert_figures_unchanged(before, after_rename)

        repoint_id = accepted_fixture.identity()
        repoint_body = {**body, 'label': 'Synthetic re-pointed B'}
        repoint_version = digest(repoint_body)
        with self.owner.engine.begin() as conn:
            self.execute(conn, """INSERT INTO wl_pg.accounts
                (tenant_id,portfolio_id,id,version,body,role,category,label)
                VALUES(:tenant,:portfolio,:account,:version,:body,:role,:category,:label)""",
                **scope, account=repoint_id, version=repoint_version, body=encode(repoint_body).decode(),
                **repoint_body)
            self.append_mapping(conn, broker_id, 2, repoint_id, repoint_version)
        after_repoint = self.report()
        self.assertEqual({row['account']['label'] for row in after_repoint['rows']}, {renamed})
        self.assert_figures_unchanged(after_rename, after_repoint)

    def append_mapping(self, conn, prior_id, revision, entity_id, version):
        scope = {'tenant': self.alpha.tenant_id, 'portfolio': self.alpha.portfolio_id}
        self.execute(conn, """INSERT INTO wl_ingestion.mappings
            (tenant_id,portfolio_id,id,revision,connection_id,source_key,entity_kind,evidence_digest,
             plan_id,account_id,account_version)
            SELECT tenant_id,portfolio_id,id,revision+1,connection_id,source_key,entity_kind,
                   evidence_digest,plan_id,:entity,:version FROM wl_ingestion.mappings
            WHERE tenant_id=:tenant AND portfolio_id=:portfolio
              AND account_id=:prior AND revision=:revision""",
            **scope, entity=entity_id, version=version, prior=prior_id, revision=revision)
        self.execute(conn, """UPDATE wl_ingestion.roots SET mapping_generation=mapping_generation+1
            WHERE tenant_id=:tenant AND portfolio_id=:portfolio""", **scope)

    def assert_figures_unchanged(self, before, after):
        self.assertEqual(int(after['fact_generation']['mapping']), int(before['fact_generation']['mapping']) + 1)
        self.assertEqual(after['fact_generation']['accepted'], before['fact_generation']['accepted'])
        self.assertNotEqual(after['calculation_id'], before['calculation_id'])
        for key in ('value', 'cost', 'unrealized_gain', 'lines'):
            self.assertEqual(after[key], before[key])
        self.assertEqual([{k: v for k, v in row.items() if k != 'account'} for row in after['rows']],
                         [{k: v for k, v in row.items() if k != 'account'} for row in before['rows']])


# Reuse the disposable ingestion provisioner, not its import route test cases.
for inherited in dir(harness.ImportRoutesPostgresTests):
    if inherited.startswith('test_'):
        setattr(AnalysisPostgresTests, inherited, None)
