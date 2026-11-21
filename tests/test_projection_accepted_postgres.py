"""Opt-in reader acceptance against a migrated, isolated synthetic PostgreSQL."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from kurafolio.ingestion.codec import digest, encode
from kurafolio.persistence.context import TenantContext, execute
from kurafolio.projection.accepted import ProjectionUnavailable, read_accepted_state
from kurafolio.projection.positions import calculate
import tests.test_projection_positions as pure

ROOT = Path(__file__).resolve().parents[1]
ORACLE = json.loads((ROOT / 'tests/fixtures/ingestion/oracle.json').read_text())


def identity():
    return str(uuid.uuid4())


@unittest.skipUnless(os.environ.get('KURAFOLIO_INGESTION_TEST') == '1',
                     'Opt-in isolated ingestion PostgreSQL provider acceptance')
class ProjectionAcceptedPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from psycopg import connect, sql
        from psycopg.conninfo import conninfo_to_dict
        from kurafolio.data_sources.contract_v1 import CatalogSnapshot
        from kurafolio.persistence.config import PostgresConfig
        from kurafolio.persistence.context import Database
        from kurafolio.persistence.ingestion_migration import migrate_ingestion
        from kurafolio.persistence.source_migration import migrate_sources

        claim = json.loads((ROOT / 'work/agent-claim.json').read_text()) if (ROOT / 'work/agent-claim.json').exists() else {}
        prefix = 'wl-anl-008-' + claim.get('ticket', 'synthetic').lower() + '-'
        cls.directory = tempfile.TemporaryDirectory(prefix=prefix)
        cls.addClassCleanup(cls.directory.cleanup)
        cls.path = Path(cls.directory.name) / 'fixture'
        command = [sys.executable, str(ROOT / 'scripts/postgres.py'), 'test-identity-environment',
                   '--output', str(cls.path)]
        subprocess.run(command, check=True, capture_output=True, timeout=120)
        cls.addClassCleanup(cls.cleanup_environment)
        fixture = json.loads((cls.path / 'test-config.json').read_text())
        operator_config = PostgresConfig.from_secret_file(cls.path / 'migration.conninfo')
        operator = conninfo_to_dict(operator_config.conninfo)
        admin = dict(operator, user='postgres', password=(cls.path / 'bootstrap.secret').read_text())
        worker = fixture['migration_role'] + '_worker'
        with connect(**admin, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(worker)))
        cls.database = Database(operator_config, schema_mode='sources')
        cls.addClassCleanup(cls.database.close)
        key = hashlib.sha256((cls.path / 'identity.key').read_bytes()).hexdigest()
        catalog = CatalogSnapshot(1, '0', (), (), ())
        migrate_sources(cls.database, fixture['runtime_role'], fixture['identity_role'], key, catalog)
        cls.contexts = {name: TenantContext(identity(), identity()) for name in ('combined', 'other', 'history', 'empty')}
        with cls.database.engine.begin() as conn:
            context = cls.contexts['combined']
            execute(conn, 'INSERT INTO wl_pg.tenant_roots VALUES(:t,:p)', t=context.tenant_id, p=context.portfolio_id)
            execute(conn, 'INSERT INTO wl_pg.portfolios(tenant_id,portfolio_id) VALUES(:t,:p)', t=context.tenant_id, p=context.portfolio_id)
            execute(conn, """INSERT INTO wl_identity.users(id,portfolio_id,username,username_key,argon_hash,
                credential_incarnation,credential_epoch,created_at)
                SELECT :t,:p,'SyntheticReader','syntheticreader','synthetic-unused',incarnation,restore_epoch,now()
                FROM wl_pg.instance_state WHERE id=1""", t=context.tenant_id, p=context.portfolio_id)
            execute(conn, 'UPDATE wl_identity.instance_auth_state SET bootstrap_closed=true,admin_user_id=:t WHERE id=1',
                    t=context.tenant_id)
        migrate_ingestion(cls.database, fixture['runtime_role'], fixture['identity_role'], worker, key, catalog)
        with cls.database.engine.begin() as conn:
            execute(conn, 'UPDATE wl_pg.instance_state SET ready=true WHERE id=1')
            descriptor = encode({'plugin_id': 'synthetic.projection', 'provider_id': 'synthetic.projection',
                                 'adapter_id': 'synthetic.projection'})
            cls.installation = hashlib.sha256(descriptor).hexdigest()
            execute(conn, """INSERT INTO wl_sources.installations VALUES(
                :id,'synthetic.projection','synthetic.projection','synthetic.projection',:body,now())""",
                id=cls.installation, body=descriptor)
            for name, context in cls.contexts.items():
                if name != 'combined':
                    execute(conn, 'INSERT INTO wl_pg.tenant_roots VALUES(:t,:p)', t=context.tenant_id, p=context.portfolio_id)
                    execute(conn, 'INSERT INTO wl_pg.portfolios(tenant_id,portfolio_id) VALUES(:t,:p)',
                            t=context.tenant_id, p=context.portfolio_id)
            cls.seed_combined(conn)
            cls.seed_other(conn)
            cls.seed_history(conn)
        runtime_config = PostgresConfig.from_secret_file(cls.path / 'runtime.conninfo')
        # Database is used only for its connection pool; its transaction wrapper refuses 0004.
        cls.runtime = Database(runtime_config, schema_mode='sources')
        cls.addClassCleanup(cls.runtime.close)

    @classmethod
    def cleanup_environment(cls):
        subprocess.run([sys.executable, str(ROOT / 'scripts/postgres.py'), 'cleanup-test-environment',
                        '--config', str(cls.path / 'test-config.json')], check=True, capture_output=True, timeout=45)

    @classmethod
    def seed(cls, conn, context, holdings, activities, *, old_heads=(), mirror=None):
        """Direct accepted storage fixture, with all migrated constraints/triggers active."""
        scope = {'tenant_id': context.tenant_id, 'portfolio_id': context.portfolio_id}
        def insert(table, values):
            parameters = {**scope, **values}
            execute(conn, 'INSERT INTO ' + table + '(' + ','.join(parameters) + ') VALUES(' +
                    ','.join(':' + name for name in parameters) + ')', **parameters)
        insert('wl_ingestion.roots', {'accepted_generation': 0, 'mapping_generation': 0, 'control_generation': 0})
        accounts, instruments = {}, {}
        all_heads = (*old_heads, *holdings)
        for head in all_heads:
            accounts[head.account.id] = head.account
            for position in head.positions:
                accounts[position.account.id] = position.account
                instruments[position.instrument.id] = position.instrument
        for activity in activities:
            accounts[activity.source_account.id] = activity.source_account
            for leg in activity.legs:
                accounts[leg.account.id] = leg.account
                instruments[leg.instrument.id] = leg.instrument
        entity_ids = {('account', name): identity() for name in accounts}
        entity_ids.update({('instrument', name): identity() for name in instruments})
        versions = {}
        for name, account in accounts.items():
            body = {'role': account.role, 'category': account.category, 'label': account.label}
            version = versions[('account', name)] = digest(body)
            insert('wl_pg.accounts', {'id': entity_ids[('account', name)], 'version': version,
                'body': encode(body).decode(), **body})
        for name, instrument in instruments.items():
            body = {field: getattr(instrument, field) for field in
                    ('kind', 'currency', 'ticker', 'mic', 'symbol', 'network', 'settlement_identity')}
            version = versions[('instrument', name)] = digest(body)
            insert('wl_pg.instruments', {'id': entity_ids[('instrument', name)], 'version': version,
                'body': encode(body).decode(), **body, 'identifiers': '[]'})
        locals_ = {key: str(index) for index, key in enumerate(entity_ids)}
        member, input_id, plan_id, receipt_id, preview_id = (identity() for _ in range(5))
        plan = deepcopy(ORACLE['plan-first-use.json'])
        plan.update(tenant_id=context.tenant_id, portfolio_id=context.portfolio_id,
                    mappings=[{'member_id': member, 'entity_kind': kind, 'local_id': locals_[(kind, name)],
                        'target': {'mode': 'existing', 'id': entity_ids[(kind, name)], 'version': versions[(kind, name)]}}
                        for kind, name in entity_ids], facts=[])
        documents = []
        def add(collection, typed, *, parent=None):
            revision = identity()
            typed = deepcopy(typed)
            typed['local_id'] = str(sum(item[0] == collection for item in documents))
            plan['facts'].append({'member_id': member, 'accepted_revision_id': revision, 'action': 'append',
                'collection': collection, 'local_id': typed['local_id'], 'economic_group_id': None,
                'financial_digest': digest(typed), 'parent_revision_id': parent})
            documents.append((collection, typed, revision, parent))
            return typed['local_id'], revision
        snapshot_heads = []
        old_by_account = {}
        position_template = ORACLE['snapshot-t1-minimal.json']['records'][0]
        coverage_template = ORACLE['snapshot-t1-minimal.json']['coverage'][0]
        snapshot_template = ORACLE['snapshot-t1-minimal.json']['snapshots'][0]
        # Heads with the same fixture revision share one multi-account snapshot.
        snapshot_groups = {}
        for head in all_heads:
            snapshot_groups.setdefault(head.snapshot_revision_id, []).append(head)
        for group in snapshot_groups.values():
            local_positions, coverage_locals = [], []
            for head in group:
                for item in head.positions:
                    typed = deepcopy(position_template)
                    typed.update(source_account_local_id=locals_[('account', item.account.id)],
                        asset_local_id=locals_[('instrument', item.instrument.id)], quantity=str(item.quantity),
                        market_value=money_doc(item.market_value), cost_native=money_doc(item.cost_native),
                        cost_cad=money_doc(item.cost_cad), as_of=item.observed_at,
                        support={'classification': 'supported_shape', 'reasons': []})
                    local, _ = add('records', typed)
                    local_positions.append(local)
                coverage = deepcopy(coverage_template)
                coverage.update(account_local_id=locals_[('account', head.account.id)], kind='holdings',
                                status=head.coverage_status)
                coverage_local, _ = add('coverage', coverage)
                coverage_locals.append(coverage_local)
            snapshot = deepcopy(snapshot_template)
            snapshot.update(account_local_ids=[locals_[('account', head.account.id)] for head in group],
                            as_of=group[0].observed_at, position_local_ids=local_positions,
                            coverage_local_ids=coverage_locals)
            _, revision = add('snapshots', snapshot)
            for head in group:
                if head in old_heads:
                    old_by_account[head.account.id] = revision
                else:
                    canonical_scope = {'tag': 'all', 'category': None, 'instrument_ids': []}
                    snapshot_heads.append((head, revision, canonical_scope))
        activity_revisions = []
        for activity in activities:
            typed = deepcopy(ORACLE['minimal-native.json']['records'][0])
            typed.update(source_account_local_id=locals_[('account', activity.source_account.id)],
                kind=activity.kind, status=activity.status, event_time=activity.occurred_at,
                legs=[{'account_local_id': locals_[('account', leg.account.id)],
                       'asset_local_id': locals_[('instrument', leg.instrument.id)],
                       'quantity': str(leg.quantity), 'role': leg.role} for leg in activity.legs],
                acquisition_cost=money_doc(activity.acquisition_cost), fees=None,
                support={'classification': 'supported_shape', 'reasons': []})
            _, revision = add('records', typed)
            group = identity()
            plan['facts'][-1]['economic_group_id'] = group
            activity_revisions.append((activity, group, revision))
        evidence = deepcopy(ORACLE['minimal-native.json'])
        evidence.update(records=[typed for collection, typed, _, _ in documents if collection == 'records'],
                        coverage=[typed for collection, typed, _, _ in documents if collection == 'coverage'],
                        snapshots=[typed for collection, typed, _, _ in documents if collection == 'snapshots'])
        insert('wl_ingestion.accepted_inputs', {'id': input_id, 'codec': 'minimal-evidence-v1',
            'canonical_bytes': encode(evidence), 'digest': digest(evidence), 'raw_digest': '1' * 64,
            'discovery_digest': '2' * 64, 'installation_id': cls.installation, 'created_at': pure.NOW})
        insert('wl_ingestion.accepted_plans', {'id': plan_id, 'preview_id': preview_id,
            'codec': 'acceptance-plan-v1', 'canonical_bytes': encode(plan), 'digest': digest(plan),
            'receipt_id': receipt_id, 'created_at': pure.NOW})
        realm = execute(conn, 'SELECT incarnation,restore_epoch FROM wl_pg.instance_state WHERE id=1').mappings().one()
        insert('wl_ingestion.receipts', {'id': receipt_id, **realm, 'operation_id': identity(),
            'operation_kind': 'ACCEPT', 'request_digest': '3' * 64, 'preview_id': preview_id,
            'accepted_plan_id': plan_id, 'plan_digest': digest(plan), 'result_bytes': encode({}), 'created_at': pure.NOW})
        for collection, typed, revision, parent in documents:
            insert('wl_ingestion.source_revisions', {'id': revision, 'source_key': digest({'revision': revision}),
                'source_revision': 'r1', 'financial_digest': digest(typed), 'source_change': 'original',
                'accepted_change': 'original', 'parent_id': parent, 'input_id': input_id, 'collection': collection,
                'local_id': typed['local_id'], 'typed_bytes': encode(typed), 'typed_digest': digest(typed), 'created_at': pure.NOW})
            insert('wl_ingestion.lineage', {'source_revision_id': revision, 'raw_digest': '1' * 64,
                'installation_id': cls.installation, 'evidence_digest': digest(typed), 'input_id': input_id,
                'collection': collection, 'local_id': typed['local_id'], 'source_claim_bytes': encode({})})
        for head, revision, canonical_scope in snapshot_heads:
            head_key = digest({'version': 1, **scope, 'account_id': entity_ids[('account', head.account.id)],
                               'record_kind': 'holdings', 'instrument_scope': canonical_scope})
            initial = old_by_account.get(head.account.id, revision)
            insert('wl_ingestion.snapshot_heads', {'key_digest': head_key,
                'account_id': entity_ids[('account', head.account.id)], 'account_version': versions[('account', head.account.id)],
                'fact_kind': 'holdings', 'scope_bytes': encode(canonical_scope), 'latest_revision_id': initial,
                'complete_base_revision_id': initial})
            if initial != revision:
                execute(conn, 'UPDATE wl_ingestion.snapshot_heads SET latest_revision_id=:revision '
                        'WHERE tenant_id=:tenant_id AND portfolio_id=:portfolio_id AND key_digest=:key',
                        **scope, revision=revision, key=head_key)
        for activity, group, revision in activity_revisions:
            insert('wl_ingestion.activity_heads', {'economic_group_id': group, 'revision_id': revision, 'active': activity.active})
        if mirror:
            link_id = identity()
            left = next(revision for activity, _, revision in activity_revisions if activity.economic_group_id == mirror)
            right = activity_revisions[0][2]
            for revision, kind in ((1, 'independent'), (2, 'mirror')):
                insert('wl_ingestion.authority_links', {'id': link_id, 'revision': revision,
                    'left_revision_id': left, 'right_revision_id': right, 'decision_kind': kind,
                    'evidence_reference': 'synthetic', 'evidence_digest': '4' * 64, 'plan_id': plan_id})
        execute(conn, 'UPDATE wl_ingestion.roots SET accepted_generation=1,mapping_generation=1 '
                'WHERE tenant_id=:tenant_id AND portfolio_id=:portfolio_id', **scope)
        execute(conn, 'UPDATE wl_ingestion.roots SET accepted_generation=2 '
                'WHERE tenant_id=:tenant_id AND portfolio_id=:portfolio_id', **scope)
        return entity_ids

    @classmethod
    def seed_combined(cls, conn):
        from dataclasses import replace
        third = pure.buy('mirror', '.010', account=replace(pure.EXCHANGE, id='other-exchange'))
        cls.combined_ids = cls.seed(conn, cls.contexts['combined'], pure.securities(),
                                   (*pure.purchases(), third), mirror='mirror')

    @classmethod
    def seed_other(cls, conn):
        cls.other_ids = cls.seed(conn, cls.contexts['other'], (pure.head((pure.position('other'),)),), ())

    @classmethod
    def seed_history(cls, conn):
        from dataclasses import replace
        p = replace(pure.BROKER, id='P')
        q = replace(pure.BROKER, id='Q')
        t1 = {**pure.TIME, 'token': '2026-01-14'}
        old = pure.head((pure.position('old-A', account=p, observed_at=t1),
                         pure.position('old-B', pure.B, '5', account=p, observed_at=t1)), p, 'complete')
        old = replace(old, snapshot_revision_id='T1', observed_at=t1)
        current = replace(pure.head((pure.position('current-A', quantity='7', account=p),), p),
                          snapshot_revision_id='T2')
        unchanged = pure.head((pure.position('unchanged', account=q, observed_at=t1),), q, 'complete')
        unchanged = replace(unchanged, snapshot_revision_id='T1', observed_at=t1)
        cls.history_ids = cls.seed(conn, cls.contexts['history'], (current, unchanged), (), old_heads=(old,))

    @contextmanager
    def snapshot(self, name, *, isolation='REPEATABLE READ', readonly=True, settings=None):
        with self.runtime.engine.connect().execution_options(isolation_level=isolation) as conn:
            with conn.begin():
                if readonly:
                    execute(conn, 'SET TRANSACTION READ ONLY')
                context = self.contexts[name]
                selected = settings or context
                execute(conn, "SELECT set_config('ledger.tenant_id',:t,true),set_config('ledger.portfolio_id',:p,true)",
                        t=selected.tenant_id, p=selected.portfolio_id)
                yield conn, context

    def test_ac_anl_008_01_02_03_combined_and_latest_mirror(self):
        """AC-ANL-008-01 AC-ANL-008-02 AC-ANL-008-03: runtime-only accepted read."""
        with self.snapshot('combined') as (conn, context):
            accepted = read_accepted_state(conn, context)
            self.assertEqual(len(accepted.activities), 3)
            self.assertEqual(sum(fact.mirror for fact in accepted.activities), 1)
            self.assertTrue(all(fact.active for fact in accepted.activities))
            authoritative = [fact for fact in accepted.activities if not fact.mirror]
            self.assertEqual(len(authoritative), 2)
            self.assertEqual(sorted(leg.quantity for fact in authoritative for leg in fact.legs),
                             [pure.D('.010'), pure.D('.020')])
            self.assertEqual({leg.instrument.id for fact in authoritative for leg in fact.legs},
                             {self.combined_ids[('instrument', 'btc')]})
            result = calculate(accepted, pure.inputs())
        self.assertEqual(result.crypto.btc_equivalent_quantity, pure.D('.030'))
        self.assertEqual(result.total.complete_total['CAD'], pure.D(4720))
        self.assertEqual(result.total.complete_total['USD'].quantize(pure.D('.000000000000000001')),
                         pure.D('3371.428571428571428571'))
        self.assertEqual(result.total.complete_total['TWD'].quantize(pure.D('.000000000000000001')),
                         pure.D('107885.714285714285714286'))

    def test_ac_anl_008_04_partial_latest_and_absent_account(self):
        """AC-ANL-008-04: latest partial head replaces P, while Q retains its head."""
        with self.snapshot('history') as (conn, context):
            accepted = read_accepted_state(conn, context)
            quantities = {head.account.id: [position.quantity for position in head.positions] for head in accepted.holdings}
            self.assertEqual(quantities[self.history_ids[('account', 'P')]], [pure.D(7)])
            self.assertEqual(quantities[self.history_ids[('account', 'Q')]], [pure.D(10)])
            by_account = {head.account.id: head for head in accepted.holdings}
            p_id, q_id = self.history_ids[('account', 'P')], self.history_ids[('account', 'Q')]
            p_head, q_head = by_account[p_id], by_account[q_id]
            self.assertNotEqual(p_head.snapshot_revision_id, q_head.snapshot_revision_id)
            self.assertEqual((p_head.coverage_status, q_head.coverage_status), ('partial', 'complete'))
            self.assertEqual({position.instrument.id for head in accepted.holdings for position in head.positions},
                             {self.history_ids[('instrument', 'a')]})
            t1_bytes = execute(conn, 'SELECT typed_bytes FROM wl_ingestion.source_revisions '
                'WHERE tenant_id=:t AND portfolio_id=:p AND id=:revision',
                t=context.tenant_id, p=context.portfolio_id, revision=q_head.snapshot_revision_id).scalar_one()
            t1 = json.loads(bytes(t1_bytes))
            self.assertEqual(len(t1['account_local_ids']), 2)
            self.assertEqual(len(t1['coverage_local_ids']), 2)
            self.assertEqual(len(t1['position_local_ids']), 3)
            p_base = execute(conn, 'SELECT complete_base_revision_id FROM wl_ingestion.snapshot_heads '
                'WHERE tenant_id=:t AND portfolio_id=:p AND account_id=:account',
                t=context.tenant_id, p=context.portfolio_id, account=p_id).scalar_one()
            self.assertEqual(str(p_base), q_head.snapshot_revision_id)
            result = calculate(accepted, pure.inputs())
            self.assertFalse(any(gap.account_id == p_id for gap in result.gaps))
            self.assertIn('missing_from_newer_snapshot_is_sold', result.assumptions)

    def test_ac_anl_008_04_tenant_isolation_and_empty_root(self):
        """AC-ANL-008-04: no other tenant's positions or generations leak."""
        for name in ('combined', 'other'):
            with self.snapshot(name) as (conn, context):
                accepted = read_accepted_state(conn, context)
                ids = {position.account.id for head in accepted.holdings for position in head.positions}
                expected = self.combined_ids if name == 'combined' else self.other_ids
                self.assertEqual(ids, {expected[('account', 'broker')]})
        with self.snapshot('empty') as (conn, context):
            accepted = read_accepted_state(conn, context)
            self.assertEqual((accepted.accepted_generation, accepted.mapping_generation), (0, 0))
            self.assertEqual((accepted.holdings, accepted.activities), ((), ()))

    def test_ac_anl_008_04_preconditions(self):
        """AC-ANL-008-04: fail before reading facts outside a scoped snapshot."""
        for options, code in (({'isolation': 'READ COMMITTED'}, 'projection_snapshot_required'),
                              ({'readonly': False}, 'projection_snapshot_required'),
                              ({'settings': self.contexts['other']}, 'projection_scope_mismatch')):
            with self.subTest(options=options):
                with self.snapshot('combined', **options) as (conn, context):
                    with self.assertRaises(ProjectionUnavailable) as raised:
                        read_accepted_state(conn, context)
                    self.assertEqual(raised.exception.code, code)
        with self.snapshot('combined') as (conn, context):
            with patch('kurafolio.projection.accepted.SUPPORTED_REVISIONS', ()):
                with self.assertRaises(ProjectionUnavailable) as raised:
                    read_accepted_state(conn, context)
                self.assertEqual(raised.exception.code, 'projection_schema_unsupported')

    def test_ac_anl_008_04_optional_effects_sequence(self):
        """AC-ANL-008-04: optional original effects vectors need lifecycle prerequisites."""
        self.skipTest('NOT RUN: existing _plan_seed/_preview_seed omit required source-lifecycle rows on the migrated profile; no new seeding machinery')


def money_doc(value):
    return None if value is None else {'amount': str(value.amount), 'currency': value.currency}
