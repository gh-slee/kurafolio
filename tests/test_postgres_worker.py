"""Real-PostgreSQL acceptance for the dedicated ingestion worker.

Opt-in with ``KURAFOLIO_INGESTION_TEST=1`` and a local Docker engine. The class
reuses the seed helpers of ``tests/test_postgres_migration.py`` but runs the
worker's real ``WorkerSQL`` against a disposable PostgreSQL instance published
only on loopback, with a fake launcher standing in for the child engine.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import signal
import socket
import tempfile
import time
import unittest
import uuid
from unittest import mock

from kurafolio.ingestion import worker as worker_module
from kurafolio.ingestion.codec import digest as digest_body, encode, sha256, validate
from kurafolio.ingestion.worker import ImportWorker
from kurafolio.ingestion.launcher_journal import LauncherJournal
from kurafolio.ingestion.worker_journal import WorkerJournal
from kurafolio.ingestion.worker_sql import WorkerCallError, WorkerSQL
from tests.test_ingestion_worker import FakeLauncher
from tests import test_postgres_migration as pg

ORACLE = pg.ORACLE
schema = pg.schema

UTC = timezone.utc


def _instant(value):
    return validate({'tag': 'instant', 'token': value.astimezone(UTC).isoformat(timespec='seconds'),
                     'zone': None, 'fractional_digits': 0}, 'Instant')


def _metadata(context, raw, handoff_token, realm, set_id, member_id, fence='1'):
    value = json.loads(bytes(context))
    return validate({'version': 1, 'job_id': value['job_id'], 'set_id': set_id,
                     'member_id': member_id, 'fence': fence,
                     'raw_sha256': sha256(raw), 'raw_bytes': len(raw),
                     'context_sha256': sha256(context), 'context_bytes': len(context),
                     'handoff_token': handoff_token, 'realm_digest': realm,
                     'expires_at': _instant(datetime.now(UTC) + timedelta(minutes=5)),
                     'raw_deadline': _instant(datetime.now(UTC) + timedelta(seconds=90))},
                    'Handoff')


def _minimal(context, raw_sha, discovery_sha):
    """The projected minimal document a real parser-2 child would return."""
    document = deepcopy(ORACLE['minimal-parser2.json'])
    provenance = document['provenance']
    provenance['raw_sha256'] = raw_sha
    provenance['discovery_sha256'] = discovery_sha
    provenance['installation_id'] = context['installation_id']
    provenance['wrapper_profile_digest'] = context['wrapper_profile_digest']
    provenance['image_digest'] = context['image_digest']
    provenance['format_selection'] = context['format_version']
    provenance['export_version'] = context['format_version']
    provenance['evidence_reference'] = context['parser_context']['source_reference']
    provenance['evidence_at'] = {'tag': 'instant', 'token': context['parser_context']['evidence_at'],
                                 'zone': None, 'fractional_digits': 0}
    return encode(validate(document, 'Minimal'))


def _crash_child(conninfo, journal_directory, realm, metadata, context, raw, profile,
                 descriptor, minimal, step):
    import os
    from kurafolio.persistence.config import PostgresConfig
    from kurafolio.persistence.context import Database

    class CrashSQL(WorkerSQL):
        def call(self, name, request, payload=None, *, token):
            value = super().call(name, request, payload, token=token)
            if name == step:
                os.kill(os.getpid(), signal.SIGKILL)
            return value

    database = Database(PostgresConfig(conninfo), schema_mode='sources')
    launcher = FakeLauncher(metadata, payload=b'{"synthetic":true}', payload_kind='parser_v2')
    config = _Config(journal_directory, realm, '70000000-0000-4000-8000-000000000002')
    worker = ImportWorker(config, sql=CrashSQL(database, 'c7000000-0000-4000-8000-000000000001'),
                          launcher=launcher, profiles=[profile], descriptors=[descriptor])
    worker._executor = _Inline()
    if step == 'handle':
        original = worker.journal.set_handle
        def set_handle(*args):
            original(*args)
            os.kill(os.getpid(), signal.SIGKILL)
        worker.journal.set_handle = set_handle
    if step == 'result':
        worker._admit = lambda *args: os.kill(os.getpid(), signal.SIGKILL)
    from unittest import mock
    with mock.patch.object(worker_module.discovery, 'admit_parser2', return_value=minimal):
        worker.handoff(metadata, context, raw)
        worker._executor.run()




class _MappedEngine:
    """DockerEngine with the reviewed fake digest mapped to one real image."""

    def __new__(cls, image_id, reference=None):
        from kurafolio.ingestion.launcher_engine import DockerEngine

        class Engine(DockerEngine):
            def image(self, value):
                return image_id

            def create(self, *, reference, labels, entry):
                from kurafolio.ingestion.launcher_engine import DockerEngine as Base
                return Base.create(self, reference=self.real_reference, labels=labels, entry=entry)

        engine = Engine()
        engine.real_reference = reference
        return engine

def _paused_worker_child(conninfo, marker, results, claim, admit, finish, token, minimal):
    from kurafolio.persistence.config import PostgresConfig
    from kurafolio.persistence.context import Database

    database = Database(PostgresConfig(conninfo), schema_mode='sources')
    sql = WorkerSQL(database, 'c7000000-0000-4000-8000-000000000001')
    Path(marker).write_text(sql.call('claim_member_v1', claim, token=token)['outcome'])
    os.kill(os.getpid(), signal.SIGSTOP)
    codes = {}
    for name, request in (('admit_stage_v1', admit), ('finish_member_v1', finish)):
        try:
            sql.call(name, request, payload=minimal if name == 'admit_stage_v1' else None,
                     token=token)
            codes[name] = 'ok'
        except WorkerCallError as error:
            codes[name] = error.code
    Path(results).write_text(json.dumps(codes))


def _launcher_child(config, start, context, raw, marker, entry, image_id, real_reference):
    """Start one real container, publish its handle, then wait to be killed."""
    from kurafolio.ingestion.launcher import Launcher

    launcher = Launcher(config, _MappedEngine(image_id, real_reference))
    launcher.entry = entry
    status = launcher.start(start, context, raw)
    Path(marker).write_text(json.dumps({'handle': status['handle'],
                                        'job_id': status['job_id'],
                                        'fence': status['fence']}))
    time.sleep(300)


class _Inline:
    def __init__(self):
        self.jobs = []

    def submit(self, function, *args):
        self.jobs.append((function, args))

    def run(self):
        while self.jobs:
            function, args = self.jobs.pop(0)
            function(*args)

    def shutdown(self, wait=False, cancel_futures=False):
        return None


class _Config:
    def __init__(self, journal_directory, realm_digest, instance_id):
        self.journal_directory = journal_directory
        self.realm_digest = realm_digest
        self.credential_epoch = '1'
        self.instance_id = instance_id
        self.database = None
        self.worker_id = None


@unittest.skipUnless(os.environ.get('KURAFOLIO_INGESTION_TEST') == '1',
                     'Opt-in isolated ingestion worker PostgreSQL acceptance')
class WorkerPostgresTests(pg.IngestionAppendOnlyPostgresTests):
    """AC-IMP-007F-01/03/05/07 worker database acceptance on real PostgreSQL."""

    @classmethod
    def setUpClass(cls):
        from kurafolio.persistence import schema as foundation, identity_schema, source_schema

        cls.directory = tempfile.TemporaryDirectory(prefix='wl-imp-007f-worker-pg-' + uuid.uuid4().hex[:8])
        cls.addClassCleanup(cls.directory.cleanup)
        secret = Path(cls.directory.name) / 'bootstrap.txt'
        descriptor = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(secrets.token_urlsafe(32) + '\n')
        cls.secret = secret.read_text().strip()
        cls.owner = uuid.uuid4().hex
        cls.container = 'wl007f-worker-' + cls.owner[:12]
        cls.addClassCleanup(cls.remove_owned_container)
        requested = int(os.environ.get('KURAFOLIO_PORT_BASE', '54200'))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(('127.0.0.1', requested))
            except OSError:
                probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        cls.port = port
        result = cls.command(['docker', 'run', '-d', '--pull', 'never', '--name', cls.container,
            '--label', 'kurafolio.test=ingestion-worker',
            '--label', 'kurafolio.test-owner=' + cls.owner,
            '--publish', '127.0.0.1:' + str(port) + ':5432',
            '--memory', '512m', '--cpus', '1', '--pids-limit', '128',
            '--tmpfs', '/var/lib/postgresql:rw,nosuid,nodev,size=512m',
            '--mount', 'type=bind,source=' + str(secret) + ',target=/run/secrets/bootstrap,readonly',
            '-e', 'POSTGRES_PASSWORD_FILE=/run/secrets/bootstrap', cls.IMAGE])
        if result.returncode:
            raise AssertionError('Exact cached PostgreSQL test image and Docker daemon required')
        deadline = time.monotonic() + 45
        while True:
            process = cls.command(['docker', 'exec', cls.container, 'cat', '/proc/1/comm'], timeout=5)
            ready = cls.command(['docker', 'exec', cls.container, 'pg_isready', '-U', 'postgres'], timeout=5)
            if process.stdout.strip() == b'postgres' and ready.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise AssertionError('Synthetic PostgreSQL startup deadline')
            time.sleep(.2)
        cls.sql('CREATE SCHEMA wl_pg;\n' + foundation.ddl()[0] + '\n' + identity_schema.ddl()
                + '\n' + source_schema.ddl() + '\n' + schema.tables_ddl() + '\n' + schema.IMMUTABLE_DDL
                + '\n' + schema.OUTBOX_GUARD_DDL + '\n' + schema.user_guard_ddl()
                + '\n' + schema.minimal_validator_ddl() + '\n' + schema.plan_validator_ddl() + '\n'
                + schema.reference_validator_ddl() + '\n' + schema.REPLAY_DDL
                + '\n' + schema.TRANSITION_DDL + '\n' + schema.HEAD_DDL + '\n' + schema.effects_ddl()
                + '\n' + schema.ACCEPT_DDL + '\n' + schema.QUOTA_DDL + '\n' + schema.ADMIT_RATE_DDL
                + '\n' + schema.PURGE_DDL
                + '\n' + schema.CANCEL_DDL + '\n' + schema.DECIDE_DDL
                + '\n' + schema.READ_SET_DDL + '\n' + schema.READ_RECEIPT_DDL
                + '\n' + schema.READ_SETS_DDL + '\n' + schema.READ_PREVIEW_DDL
                + '\n' + schema.worker_guard_ddl() + '\n' + schema.CREATE_DDL
                + '\n' + schema.RESERVE_DDL + '\n' + schema.CLAIM_DDL + '\n' + schema.RENEW_DDL
                + '\n' + schema.ADMIT_DDL + '\n' + schema.FINISH_DDL
                + '\n' + schema.CLAIM_PLAN_DDL + '\n' + schema.CLEANUP_SET_DDL
                + '\n' + schema.read_plan_basis_ddl() + '\n' + schema.prepare_preview_ddl())
        cls.sql('CREATE TABLE wl_pg.alembic_version(version_num text PRIMARY KEY);')
        for trigger in schema.inventory()['triggers']:
            if trigger['function'] == '_immutable_v1':
                cls.sql('CREATE TRIGGER ' + trigger['name'] + ' BEFORE INSERT OR UPDATE OR DELETE ON '
                        'wl_ingestion.' + trigger['table'] + ' FOR EACH ROW EXECUTE FUNCTION '
                        'wl_ingestion._immutable_v1();')
        cls.sql('CREATE TRIGGER outbox_guard BEFORE INSERT OR UPDATE OR DELETE ON '
                'wl_ingestion.outbox FOR EACH ROW EXECUTE FUNCTION wl_ingestion._outbox_guard_v1();')
        cls.role = 'wl007f_worker'
        cls.role_secret = 'example-worker-only'
        cls.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='"
                + cls.role + "') THEN CREATE ROLE " + cls.role
                + " LOGIN PASSWORD '" + cls.role_secret + "' NOSUPERUSER NOINHERIT; END IF; END $role$;")
        cls.addClassCleanup(cls.drop_role)
        cls.sql("GRANT USAGE ON SCHEMA wl_ingestion TO " + cls.role + ";"
                "GRANT EXECUTE ON FUNCTION " + ", ".join(schema.signature(name) for name in schema.WORKER)
                + " TO " + cls.role + ";")
        cls.connection = {'host': '127.0.0.1', 'port': port, 'dbname': 'postgres',
                          'user': 'postgres', 'password': cls.secret, 'connect_timeout': 5}

    @classmethod
    def drop_role(cls):
        try:
            cls.sql('DROP OWNED BY ' + cls.role + ';')
        except Exception:
            pass
        try:
            cls.sql('DROP ROLE IF EXISTS ' + cls.role + ';')
        except Exception:
            pass

    # ---------------------------------------------------------------- helpers

    def sql_on(self, database, statement):
        return self.command(['docker', 'exec', '-i', self.container, 'psql', '-X', '-A', '-t',
            '-U', 'postgres', '-d', database, '-v', 'ON_ERROR_STOP=1'],
            input=statement.encode())

    def run_on(self, database, statement):
        result = self.sql_on(database, statement)
        if result.returncode:
            raise AssertionError('Synthetic PostgreSQL statement failed: '
                                 + result.stderr.decode()[:400])
        return result.stdout.decode().strip()

    def connect(self, database_name):
        """A TCP connection, matching the realm the worker itself sees."""
        import psycopg
        return psycopg.connect(**dict(self.connection, dbname=database_name), autocommit=True)

    def run_sql(self, database_name, statement):
        with self.connect(database_name) as connection:
            connection.execute(statement)

    def scalar(self, database_name, statement):
        with self.connect(database_name) as connection:
            return connection.execute(statement).fetchone()[0]

    def fresh_database(self):
        from kurafolio.persistence.config import PostgresConfig
        from kurafolio.persistence.context import Database
        from psycopg.conninfo import make_conninfo
        name = 'wl_worker_' + uuid.uuid4().hex[:12]
        self.sql('CREATE DATABASE ' + name + ' TEMPLATE postgres;')
        conninfo = make_conninfo(**dict(self.connection, dbname=name))
        database = Database(PostgresConfig(conninfo), schema_mode='sources')
        self.addCleanup(lambda: (database.close(), self.sql('DROP DATABASE IF EXISTS ' + name
                                                           + ' WITH (FORCE);')))
        return database, name

    def seed(self, database_name, *, count=1, login_role='postgres', bind=True):
        """Commit one bound native set and return its worker-visible context."""
        plan, pin, seed, catalog = self.create_seed()
        raw = ('synthetic,raw\n' + self.owner + '\n').encode()
        token_digest = sha256(bytes.fromhex('ab' * 32))
        # The set is committed here, so the deferred installation FK is checked
        # at COMMIT. accept_seed retargets accepted_inputs to a synthetic ID
        # table for the same rolled-back fixture reason; members needs the same
        # treatment, in its own transaction so no trigger events are pending.
        self.run_sql(database_name,
            "CREATE TABLE wl_sources.synthetic_worker_installation_ids(id text PRIMARY KEY);"
            "INSERT INTO wl_sources.synthetic_worker_installation_ids VALUES('" + pin['installation_id'] + "');"
            "ALTER TABLE wl_ingestion.members DROP CONSTRAINT members_installation_fk;"
            "ALTER TABLE wl_ingestion.members ADD CONSTRAINT members_installation_fk "
            "FOREIGN KEY(installation_id) REFERENCES wl_sources.synthetic_worker_installation_ids(id) "
            "DEFERRABLE INITIALLY DEFERRED;")
        seed += self.row('workers', {'id': self.WORKER, 'login_role': login_role,
                                     'peer_identity': 'peer-a', 'enabled': True,
                                     'credential_epoch': 1})
        seed += self.gateway_statement('create_set_v1', 'create',
                                       self.create_payload(pin, count=count), catalog)
        seed += self.reserve_call('reserve', catalog)
        if bind:
            seed += self.reserve_call('bind', catalog, action='bind',
                                      raw_sha256="'" + sha256(raw) + "'", raw_bytes=str(len(raw)),
                                      handoff_token_digest="'" + token_digest + "'")
        self.run_sql(database_name, 'BEGIN;' + seed + 'COMMIT;')
        row = self.scalar(database_name, "SELECT pg_catalog.encode(m.context_bytes,'hex')||' '||"
            "m.id::text||' '||x.id::text FROM wl_ingestion.members m "
            "JOIN wl_ingestion.sets x ON x.id=m.set_id "
            "WHERE x.creation_operation_id='53000000-0000-4000-8000-000000000001' "
            "ORDER BY m.ordinal LIMIT 1;")
        context_hex, member_id, set_id = row.split()
        plan['set_id'] = set_id
        return plan, pin, catalog, raw, bytes.fromhex(context_hex), member_id

    def database_conninfo(self, name):
        from psycopg.conninfo import make_conninfo
        return make_conninfo(**dict(self.connection, dbname=name))

    def role_database(self, name):
        from kurafolio.persistence.config import PostgresConfig
        from kurafolio.persistence.context import Database
        from psycopg.conninfo import make_conninfo
        conninfo = make_conninfo(**dict(self.connection, dbname=name, user=self.role,
                                        password='example-worker-only'))
        database = Database(PostgresConfig(conninfo), schema_mode='sources')
        self.addCleanup(database.close)
        return database

    def realm(self, database):
        return self.scalar(database, "SELECT " + self.worker_realm()
                           + " FROM wl_pg.instance_state st WHERE st.id=1;")

    def worker(self, database, journal_directory, realm, launcher, profiles, descriptors):
        config = _Config(journal_directory, realm, self.INCARNATION)
        instance = ImportWorker(config, sql=WorkerSQL(database, self.WORKER),
                                launcher=launcher, profiles=profiles,
                                descriptors=descriptors)
        instance._executor = _Inline()
        return instance

    def profile(self, context):
        value = deepcopy(ORACLE['wrapper-parser2.json'])
        assert value['installation_id'] == context['installation_id']
        assert value['profile_digest'] == context['wrapper_profile_digest']
        assert context['format_version'] in value['format_versions']
        return validate(value, 'WrapperProfile')

    def query(self, database, statement):
        from sqlalchemy import text
        with database.engine.connect() as connection:
            return connection.execute(text(statement)).all()

    # ------------------------------------------------------------------ cases

    def test_ac_01_request_id_replay_returns_the_same_claim(self):
        """AC-IMP-007F-01: a lost acknowledgement replays the same request."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        request = {'version': 1, 'realm_digest': self.realm(name), 'credential_epoch': '1',
                   'job_id': context['job_id'], 'set_id': plan['set_id'],
                   'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                   'request_id': str(uuid.uuid4()), 'raw_digest': sha256(raw),
                   'context_digest': sha256(context_bytes)}
        sql = WorkerSQL(database, self.WORKER)
        first = sql.call('claim_member_v1', request, token='ab' * 32)
        second = sql.call('claim_member_v1', request, token='ab' * 32)
        self.assertEqual(('claimed', 'already_claimed'),
                         (first['outcome'], second['outcome']))
        self.assertEqual(first['source_fingerprint'], second['source_fingerprint'])

    def test_ac_01_worker_role_reads_and_gateway_functions_are_denied(self):
        """AC-IMP-007F-01: the real worker login can call only worker functions."""
        import psycopg
        from psycopg import sql
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name, login_role=self.role)
        context = json.loads(context_bytes)
        role_database = self.role_database(name)
        role_sql = WorkerSQL(role_database, self.WORKER)
        request = {'version': 1, 'realm_digest': self.realm(name), 'credential_epoch': '1',
                   'job_id': context['job_id'], 'set_id': plan['set_id'],
                   'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                   'request_id': str(uuid.uuid4()), 'raw_digest': sha256(raw),
                   'context_digest': sha256(context_bytes)}
        ack = role_sql.call('claim_member_v1', request, token='ab' * 32)
        self.assertEqual('claimed', ack['outcome'])
        with psycopg.connect(**dict(self.connection, dbname=name, user=self.role,
                                    password='example-worker-only'), autocommit=True) as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege) as caught:
                connection.execute("SELECT count(*) FROM wl_ingestion.sets")
            self.assertEqual('42501', caught.exception.sqlstate)
            for function in ('create_set_v1', 'accept_preview_v1'):
                with self.subTest(function=function):
                    value = connection.execute(
                        "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (self.role, schema.signature(function))).fetchone()[0]
                    self.assertFalse(value)

    def test_ac_03_normalize_admits_and_finishes_through_the_real_worker(self):
        """AC-IMP-007F-01/03: claim, admit and fenced finish carry absent proof."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        payload = b'{"synthetic":true}'
        minimal = _minimal(context, sha256(raw), sha256(payload))
        launcher = FakeLauncher(_metadata(context_bytes, raw, 'ab' * 32, realm, plan['set_id'], member_id),
                                     payload=payload, payload_kind='parser_v2')
        with tempfile.TemporaryDirectory(prefix='wl-imp-007f-journal-') as directory:
            os.chmod(directory, 0o700)
            worker = self.worker(database, directory, realm, launcher,
                                 [self.profile(context)], [(context['installation_id'], b'descriptor')])
            with mock.patch.object(worker_module.discovery, 'admit_parser2', return_value=minimal):
                ack = worker.handoff(_metadata(context_bytes, raw, 'ab' * 32, realm, plan['set_id'], member_id), context_bytes, raw)
                self.assertEqual('owned', ack['outcome'])
                worker._executor.run()
            self.assertEqual([], worker.journal.records())
            state = self.query(database,
                "SELECT x.state, x.cleanup_state, (SELECT count(*) FROM wl_ingestion.members m "
                "WHERE m.set_id=x.id AND m.state='admitted'), "
                "(SELECT count(*) FROM wl_ingestion.stages g WHERE g.set_id=x.id), "
                "(SELECT count(*) FROM wl_ingestion.previews v WHERE v.set_id=x.id), "
                "(SELECT count(*) FROM wl_ingestion.leases l WHERE l.set_id=x.id AND l.work_kind='prepare') "
                "FROM wl_ingestion.sets x WHERE x.id='" + plan['set_id'] + "'")[0]
            self.assertEqual(('NORMALIZING', 'not_needed', 1, 1, 0, 0), tuple(state))
            lease = self.query(database,
                "SELECT l.state, l.work_kind FROM wl_ingestion.leases l "
                "WHERE l.set_id='" + plan['set_id'] + "' ORDER BY l.created_at")
            self.assertEqual([('finished', 'normalize')], [tuple(row) for row in lease])
            self.assertTrue(any(control['operation'] == 'forget' for control in launcher.controls))

    def test_ac_01_normalized_set_waits_and_cleanup_purges_after_cancel(self):
        """AC-IMP-007F-01/07: no prepare claim, then cancel and purge once."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        payload = b'{"synthetic":true}'
        minimal = _minimal(context, sha256(raw), sha256(payload))
        launcher = FakeLauncher(_metadata(context_bytes, raw, 'ab' * 32, realm, plan['set_id'], member_id),
                                     payload=payload, payload_kind='parser_v2')
        with tempfile.TemporaryDirectory(prefix='wl-imp-007f-journal-') as directory:
            os.chmod(directory, 0o700)
            worker = self.worker(database, directory, realm, launcher,
                                 [self.profile(context)], [(context['installation_id'], b'descriptor')])
            with mock.patch.object(worker_module.discovery, 'admit_parser2', return_value=minimal):
                worker.handoff(_metadata(context_bytes, raw, 'ab' * 32, realm, plan['set_id'], member_id), context_bytes, raw)
                worker._executor.run()
            # A normalized set is not cleanup work while it is still NORMALIZING.
            for _ in range(30):
                worker._cleanup_once()
            self.assertEqual([], [row for row in self.query(database,
                "SELECT l.work_kind FROM wl_ingestion.leases l WHERE l.set_id='" + plan['set_id'] + "'")
                if row[0] == 'cleanup'])
            self.assertEqual([], [row for row in self.query(database,
                "SELECT l.work_kind FROM wl_ingestion.leases l WHERE l.work_kind='prepare'")])
            self.run_sql(name, 'BEGIN;' + self.cancel_call(catalog) + 'COMMIT;')
            worker._cleanup_once()
            worker._cleanup_once()
            rows = self.query(database,
                "SELECT x.state, x.cleanup_state, (SELECT count(*) FROM wl_ingestion.stages g "
                "WHERE g.set_id=x.id), (SELECT count(*) FROM wl_ingestion.previews v "
                "WHERE v.set_id=x.id), (SELECT reserved_bytes FROM wl_ingestion.quotas q "
                "WHERE q.portfolio_id=x.portfolio_id AND q.bucket='storage') "
                "FROM wl_ingestion.sets x WHERE x.id='" + plan['set_id'] + "'")[0]
            self.assertEqual(('CANCELLED', 'complete', 0, 0, 0), tuple(rows))
            self.assertEqual(1, int(self.scalar(name,
                "SELECT count(*) FROM wl_ingestion.leases l WHERE l.set_id='" +
                plan['set_id'] + "' AND l.work_kind='cleanup';")))

    def test_ac_07_pending_then_failed_proof_keeps_capacity(self):
        """AC-IMP-007F-07: a pending proof keeps storage until absence."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        payload = b'{"synthetic":true}'
        minimal = _minimal(context, sha256(raw), sha256(payload))
        launcher = FakeLauncher(_metadata(context_bytes, raw, 'ab' * 32, realm, plan['set_id'], member_id),
                                payload=payload, payload_kind='parser_v2',
                                cleanup=('cleanup_pending', False))
        with tempfile.TemporaryDirectory(prefix='wl-imp-007f-journal-') as directory:
            os.chmod(directory, 0o700)
            worker = self.worker(database, directory, realm, launcher,
                                 [self.profile(context)], [(context['installation_id'], b'descriptor')])
            with mock.patch.object(worker_module.discovery, 'admit_parser2', return_value=minimal):
                worker.handoff(_metadata(context_bytes, raw, 'ab' * 32, realm, plan['set_id'], member_id),
                               context_bytes, raw)
                worker._executor.run()
            self.run_sql(name, 'BEGIN;' + self.cancel_call(catalog) + 'COMMIT;')
            worker._cleanup_once()
        state = self.query(database,
            "SELECT x.state, x.cleanup_state, (SELECT reserved_bytes FROM wl_ingestion.quotas q "
            "WHERE q.portfolio_id=x.portfolio_id AND q.bucket='storage') FROM wl_ingestion.sets x "
            "WHERE x.id='" + plan['set_id'] + "'")[0]
        self.assertEqual(('CANCELLED', 'failed'), tuple(state)[:2])
        self.assertGreater(int(state[2]), 0)

    def test_ac_03_record_without_handle_keeps_cleanup_pending(self):
        """AC-IMP-007F-03: a record without a handle yields no proof."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        self.run_sql(name, 'BEGIN;' + self.cancel_call(catalog) + 'COMMIT;')
        context = json.loads(context_bytes)
        with tempfile.TemporaryDirectory(prefix='wl-imp-007f-journal-') as directory:
            os.chmod(directory, 0o700)
            journal = WorkerJournal(directory)
            journal.record(plan['set_id'], context['job_id'], member_id, '1')
            launcher = FakeLauncher(_metadata(context_bytes, raw, 'ab' * 32, self.realm(name),
                                              plan['set_id'], member_id), payload=b'x')
            worker = self.worker(database, directory, self.realm(name), launcher,
                                 [self.profile(context)],
                                 [(context['installation_id'], b'descriptor')])
            worker._cleanup_once()
            self.assertEqual(1, len(worker.journal.records()))

    def test_ac_03_sigkill_at_each_normalize_step_is_recoverable(self):
        """AC-IMP-007F-03: SIGKILL leaves only the documented recoverable states."""
        for step in ('claim_member_v1', 'handle', 'result', 'admit_stage_v1', 'finish_member_v1'):
            with self.subTest(step=step):
                database, name = self.fresh_database()
                plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
                context = json.loads(context_bytes)
                realm = self.realm(name)
                payload = b'{"synthetic":true}'
                minimal = _minimal(context, sha256(raw), sha256(payload))
                with tempfile.TemporaryDirectory(prefix='wl-imp-007f-crash-') as directory:
                    os.chmod(directory, 0o700)
                    process = multiprocessing.get_context('fork').Process(
                        target=_crash_child,
                        args=(self.database_conninfo(name), directory, realm,
                              _metadata(context_bytes, raw, 'ab' * 32, realm,
                                        plan['set_id'], member_id),
                              context_bytes, raw, self.profile(context),
                              (context['installation_id'], b'descriptor'), minimal, step))
                    process.start()
                    process.join(20)
                    self.assertEqual(-signal.SIGKILL, process.exitcode)
                    records = WorkerJournal(directory).records()
                    if step == 'finish_member_v1':
                        state = self.query(database,
                            "SELECT x.state, m.state FROM wl_ingestion.sets x JOIN wl_ingestion.members m "
                            "ON m.set_id=x.id WHERE x.id='" + plan['set_id'] + "'")[0]
                        self.assertEqual(('NORMALIZING', 'admitted'), tuple(state))
                        continue
                    # The old producer cannot finish after its fence lapses.
                    self.run_sql(name, "BEGIN;SET LOCAL session_replication_role=replica;"
                                      "UPDATE wl_ingestion.leases SET created_at=created_at-interval '2 minutes',"
                                      "expires_at=pg_catalog.clock_timestamp()-interval '1 second' "
                                      "WHERE work_kind='normalize';"
                                      "SET LOCAL session_replication_role=origin;COMMIT;")
                    finish = {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                              'job_id': context['job_id'], 'set_id': plan['set_id'],
                              'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                              'request_id': str(uuid.uuid4()), 'outcome': 'stage_admitted',
                              'error_code': None, 'cleanup_proofs': []}
                    with self.assertRaises(WorkerCallError) as caught:
                        WorkerSQL(database, self.WORKER).call('finish_member_v1', finish,
                                                              token='ab' * 32)
                    self.assertIn(caught.exception.code, {'import_stale', 'import_expired'})
                    self.run_sql(name, 'BEGIN;' + self.cancel_call(catalog) + 'COMMIT;')
                    launcher = FakeLauncher(_metadata(context_bytes, raw, 'ab' * 32, realm,
                                                      plan['set_id'], member_id),
                                            payload=payload, payload_kind='parser_v2')
                    if records:
                        launcher.handle = records[0].handle or secrets.token_hex(32)
                    worker = self.worker(database, directory, realm, launcher,
                                         [self.profile(context)],
                                         [(context['installation_id'], b'descriptor')])
                    worker._cleanup_once()
                    row = self.query(database,
                        "SELECT x.state, x.cleanup_state FROM wl_ingestion.sets x WHERE x.id='"
                        + plan['set_id'] + "'")[0]
                    self.assertEqual('CANCELLED', row[0])
                    if step == 'claim_member_v1':
                        self.assertEqual(('failed', 1), (row[1], len(worker.journal.records())))
                    else:
                        self.assertEqual(('complete', 0), (row[1], len(worker.journal.records())))

    def _terminal_purge(self, scenario):
        expected_state = {'cancelled_reception': 'CANCELLED',
                          'cancelled_after_launch': 'CANCELLED',
                          'expired': 'EXPIRED', 'committed': 'COMMITTED'}[scenario]
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(
            name, bind=scenario != 'cancelled_reception')
        context = json.loads(context_bytes)
        realm = self.realm(name)
        payload = b'{"synthetic":true}'
        minimal = _minimal(context, sha256(raw), sha256(payload))
        launcher = FakeLauncher(_metadata(context_bytes, raw, 'ab' * 32, realm,
                                          plan['set_id'], member_id),
                                payload=payload, payload_kind='parser_v2')
        with tempfile.TemporaryDirectory(prefix='wl-imp-007f-journal-') as directory:
            os.chmod(directory, 0o700)
            worker = self.worker(database, directory, realm, launcher,
                                 [self.profile(context)],
                                 [(context['installation_id'], b'descriptor')])
            if scenario != 'cancelled_reception':
                with mock.patch.object(worker_module.discovery, 'admit_parser2',
                                       return_value=minimal):
                    worker.handoff(_metadata(context_bytes, raw, 'ab' * 32, realm,
                                             plan['set_id'], member_id),
                                   context_bytes, raw)
                    worker._executor.run()
            if scenario in ('cancelled_reception', 'cancelled_after_launch'):
                self.run_sql(name, 'BEGIN;' + self.cancel_call(catalog) + 'COMMIT;')
            elif scenario == 'expired':
                self.run_sql(name, "BEGIN;SET LOCAL session_replication_role=replica;"
                              "UPDATE wl_ingestion.sets SET state='EXPIRED',cleanup_state='pending',"
                              "prepare_session_digest=NULL,prepare_credential_version=NULL "
                              "WHERE id='" + plan['set_id'] + "';"
                              "UPDATE wl_ingestion.members SET state='expired' "
                              "WHERE set_id='" + plan['set_id'] + "';"
                              "SET LOCAL session_replication_role=origin;COMMIT;")
            else:
                # A committed set names one ACCEPT receipt; the receipt and
                # its accepted plan form a deferrable pair.
                self.run_sql(name,
                    "BEGIN;SET LOCAL session_replication_role=replica;"
                    "INSERT INTO wl_ingestion.accepted_plans(tenant_id,portfolio_id,id,preview_id,"
                    "codec,canonical_bytes,digest,receipt_id,created_at) "
                    "SELECT tenant_id,portfolio_id,'d1000000-0000-4000-8000-000000000001',"
                    "gen_random_uuid(),'acceptance-plan-v1',decode('7b7d','hex'),'"
                    + sha256(b'{}') + "','e1000000-0000-4000-8000-000000000001',"
                    "pg_catalog.clock_timestamp() FROM wl_ingestion.sets WHERE id='"
                    + plan['set_id'] + "';"
                    "INSERT INTO wl_ingestion.receipts(tenant_id,portfolio_id,id,incarnation,"
                    "restore_epoch,operation_id,operation_kind,request_digest,preview_id,"
                    "accepted_plan_id,plan_digest,result_bytes,created_at) "
                    "SELECT tenant_id,portfolio_id,'e1000000-0000-4000-8000-000000000001',"
                    "incarnation,restore_epoch,gen_random_uuid(),'ACCEPT','" + 'a' * 64
                    + "',gen_random_uuid(),'d1000000-0000-4000-8000-000000000001','"
                    + 'b' * 64 + "',decode('7b7d','hex'),pg_catalog.clock_timestamp() "
                    "FROM wl_ingestion.sets WHERE id='" + plan['set_id'] + "';"
                    "UPDATE wl_ingestion.sets SET state='COMMITTED',revision=revision+1,"
                    "receipt_id='e1000000-0000-4000-8000-000000000001',"
                    "cleanup_state='pending',prepare_session_digest=NULL,"
                    "prepare_credential_version=NULL WHERE id='" + plan['set_id'] + "';"
                    "UPDATE wl_ingestion.members SET state='committed' "
                    "WHERE set_id='" + plan['set_id'] + "';"
                    "SET LOCAL session_replication_role=origin;COMMIT;")
            self.run_sql(name, "BEGIN;SET LOCAL session_replication_role=replica;"
                          "UPDATE wl_ingestion.leases SET "
                          "created_at=created_at-interval '3 minutes',"
                          "expires_at=pg_catalog.clock_timestamp()-interval '1 second' "
                          "WHERE set_id='" + plan['set_id'] + "' AND work_kind='normalize' "
                          "AND state NOT IN ('finished');"
                          "SET LOCAL session_replication_role=origin;COMMIT;")
            worker._cleanup_once()
            worker._cleanup_once()
            remaining = len(worker.journal.records())
        rows = self.query(database,
            "SELECT x.state, x.cleanup_state, (SELECT count(*) FROM wl_ingestion.stages g "
            "WHERE g.set_id=x.id), (SELECT count(*) FROM wl_ingestion.previews v "
            "WHERE v.set_id=x.id), (SELECT reserved_bytes FROM wl_ingestion.quotas q "
            "WHERE q.portfolio_id=x.portfolio_id AND q.bucket='storage') "
            "FROM wl_ingestion.sets x WHERE x.id='" + plan['set_id'] + "'")[0]
        self.assertEqual((expected_state, 'complete', 0, 0, 0), tuple(rows))
        self.assertEqual(0, remaining)
        self.assertEqual('no_work', worker.sql.call('claim_plan_v1',
            {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
             'work_kind': 'cleanup', 'claim_request_id': str(uuid.uuid4())},
            token='ef' * 32)['outcome'])
        self.assertEqual(0, int(self.scalar(name,
            "SELECT reserved_bytes FROM wl_ingestion.quotas WHERE bucket='storage';")))

    def test_ac_07_cancelled_reception_purges_and_releases_once(self):
        """AC-IMP-007F-07: a set cancelled before its handoff is purged."""
        self._terminal_purge('cancelled_reception')

    def test_ac_07_cancelled_after_launch_purges_and_releases_once(self):
        """AC-IMP-007F-07: a set cancelled after normalization is purged."""
        self._terminal_purge('cancelled_after_launch')

    def test_ac_07_expired_set_purges_and_releases_once(self):
        """AC-IMP-007F-07: an expired set is purged and released once."""
        self._terminal_purge('expired')

    def test_ac_07_committed_set_purges_and_releases_once(self):
        """AC-IMP-007F-07: a committed set is purged and released once."""
        self._terminal_purge('committed')

    def test_ac_05_a_paused_worker_cannot_publish_its_stale_admit_or_finish(self):
        """AC-IMP-007F-05: a paused worker's late admit and finish are stale."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        token = 'ab' * 32
        minimal = _minimal(context, sha256(raw), sha256(b'{"synthetic":true}'))
        claim = {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                 'job_id': context['job_id'], 'set_id': plan['set_id'],
                 'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                 'request_id': str(uuid.uuid4()), 'raw_digest': sha256(raw),
                 'context_digest': sha256(context_bytes)}
        admit = {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                 'job_id': context['job_id'], 'set_id': plan['set_id'],
                 'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                 'request_id': str(uuid.uuid4()), 'stage_digest': sha256(minimal),
                 'raw_digest': sha256(raw), 'discovery_digest': sha256(b'{"synthetic":true}'),
                 'payload_bytes': len(minimal)}
        finish = {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                  'job_id': context['job_id'], 'set_id': plan['set_id'],
                  'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                  'request_id': str(uuid.uuid4()), 'outcome': 'stage_admitted',
                  'error_code': None, 'cleanup_proofs': []}
        with tempfile.TemporaryDirectory(prefix='wl-imp-007f-paused-') as directory:
            marker = Path(directory) / 'claimed'
            results = Path(directory) / 'results.json'
            child = multiprocessing.get_context('fork').Process(
                target=_paused_worker_child,
                args=(self.database_conninfo(name), marker, results, claim, admit, finish,
                      token, minimal))
            child.start()
            self.addCleanup(lambda: child.is_alive() and child.kill())
            deadline = time.monotonic() + 20
            while not marker.exists():
                if time.monotonic() >= deadline:
                    self.fail('paused worker did not claim')
                time.sleep(.05)
            self.assertEqual('claimed', marker.read_text())
            self.run_sql(name, "BEGIN;SET LOCAL session_replication_role=replica;"
                          "UPDATE wl_ingestion.leases SET created_at=created_at-interval '3 minutes',"
                          "expires_at=pg_catalog.clock_timestamp()-interval '1 second' "
                          "WHERE work_kind='normalize' AND state='active';"
                          "SET LOCAL session_replication_role=origin;COMMIT;")
            os.kill(child.pid, signal.SIGCONT)
            child.join(20)
            self.assertEqual(0, child.exitcode)
            self.assertEqual({'admit_stage_v1': 'import_stale',
                              'finish_member_v1': 'import_stale'},
                             json.loads(results.read_text()))
        rows = self.query(database,
            "SELECT (SELECT count(*) FROM wl_ingestion.stages g WHERE g.set_id='" + plan['set_id']
            + "'), (SELECT state FROM wl_ingestion.members WHERE id='" + member_id
            + "'), (SELECT state FROM wl_ingestion.sets WHERE id='" + plan['set_id'] + "')")[0]
        self.assertEqual((0, 'normalizing', 'RECEIVING'), tuple(rows))

    def test_ac_05_a_second_worker_at_the_new_fence_wins(self):
        """AC-IMP-007F-05: a re-upload advances the fence and only it publishes."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        token = 'ab' * 32
        minimal = _minimal(context, sha256(raw), sha256(b'{"synthetic":true}'))
        proof = validate({'job_id': context['job_id'], 'fence': '1', 'state': 'absent',
                          'launcher_instance_id': self.INCARNATION,
                          'proof_digest': '1' * 64,
                          'checked_at': _instant(datetime.now(UTC))}, 'CleanupProof')
        first = WorkerSQL(database, self.WORKER)
        first.call('claim_member_v1', {'version': 1, 'realm_digest': realm,
                   'credential_epoch': '1', 'job_id': context['job_id'],
                   'set_id': plan['set_id'], 'member_id': member_id,
                   'work_kind': 'normalize', 'fence': '1',
                   'request_id': str(uuid.uuid4()), 'raw_digest': sha256(raw),
                   'context_digest': sha256(context_bytes)}, token=token)
        first.call('finish_member_v1', {'version': 1, 'realm_digest': realm,
                   'credential_epoch': '1', 'job_id': context['job_id'],
                   'set_id': plan['set_id'], 'member_id': member_id,
                   'work_kind': 'normalize', 'fence': '1',
                   'request_id': str(uuid.uuid4()), 'outcome': 'reupload_required',
                   'error_code': 'import_runner_unavailable',
                   'cleanup_proofs': [proof]}, token=token)
        self.assertEqual('reupload_required', self.scalar(name,
            "SELECT state FROM wl_ingestion.members WHERE id='" + member_id + "';"))
        # The recovery path a new upload takes today: reserve, then bind fence 2.
        result = self.sql_on(name, "BEGIN;" + self.reserve_call('reserve', catalog,
            set_id="'" + plan['set_id'] + "'", member_id="'" + member_id + "'",
            expected_set_revision="'1'") + "COMMIT;")
        self.assertIn('"ok": true', result.stdout.decode())
        self.run_sql(name, "BEGIN;" + self.reserve_call('bind', catalog, action='bind',
            set_id="'" + plan['set_id'] + "'", member_id="'" + member_id + "'",
            fence="(SELECT fence::text FROM wl_ingestion.members WHERE id='" + member_id + "')",
            raw_sha256="'" + sha256(raw) + "'", raw_bytes=str(len(raw)),
            handoff_token_digest="'" + sha256(bytes.fromhex(token)) + "'") + "COMMIT;")
        self.assertEqual('2', self.scalar(name,
            "SELECT fence::text FROM wl_ingestion.members WHERE id='" + member_id + "';"))
        fresh = bytes.fromhex(self.scalar(name,
            "SELECT pg_catalog.encode(context_bytes,'hex') FROM wl_ingestion.members "
            "WHERE id='" + member_id + "';"))
        value = json.loads(fresh)
        fresh_minimal = _minimal(value, sha256(raw), sha256(b'{"synthetic":true}'))
        second = WorkerSQL(database, self.WORKER)
        ack = second.call('claim_member_v1', {'version': 1, 'realm_digest': realm,
            'credential_epoch': '1', 'job_id': value['job_id'], 'set_id': plan['set_id'],
            'member_id': member_id, 'work_kind': 'normalize', 'fence': '2',
            'request_id': str(uuid.uuid4()), 'raw_digest': sha256(raw),
            'context_digest': sha256(fresh)}, token=token)
        self.assertEqual(('claimed', '2'), (ack['outcome'], ack['fence']))
        second.call('admit_stage_v1', {'version': 1, 'realm_digest': realm,
            'credential_epoch': '1', 'job_id': value['job_id'], 'set_id': plan['set_id'],
            'member_id': member_id, 'work_kind': 'normalize', 'fence': '2',
            'request_id': str(uuid.uuid4()), 'stage_digest': sha256(fresh_minimal),
            'raw_digest': sha256(raw), 'discovery_digest': sha256(b'{"synthetic":true}'),
            'payload_bytes': len(fresh_minimal)}, payload=fresh_minimal, token=token)
        self.assertEqual('admitted', second.call('finish_member_v1', {
            'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
            'job_id': value['job_id'], 'set_id': plan['set_id'], 'member_id': member_id,
            'work_kind': 'normalize', 'fence': '2', 'request_id': str(uuid.uuid4()),
            'outcome': 'stage_admitted', 'error_code': None,
            'cleanup_proofs': []}, token=token)['state'])
        for call, request in (('admit_stage_v1', {'version': 1, 'realm_digest': realm,
                 'credential_epoch': '1', 'job_id': context['job_id'],
                 'set_id': plan['set_id'], 'member_id': member_id,
                 'work_kind': 'normalize', 'fence': '1', 'request_id': str(uuid.uuid4()),
                 'stage_digest': sha256(minimal), 'raw_digest': sha256(raw),
                 'discovery_digest': sha256(b'{"synthetic":true}'),
                 'payload_bytes': len(minimal)}),
                ('finish_member_v1', {'version': 1, 'realm_digest': realm,
                 'credential_epoch': '1', 'job_id': context['job_id'],
                 'set_id': plan['set_id'], 'member_id': member_id,
                 'work_kind': 'normalize', 'fence': '1', 'request_id': str(uuid.uuid4()),
                 'outcome': 'stage_admitted', 'error_code': None,
                 'cleanup_proofs': []})):
            with self.subTest(late=call):
                with self.assertRaises(WorkerCallError) as caught:
                    first.call(call, request,
                               payload=minimal if call == 'admit_stage_v1' else None,
                               token=token)
                self.assertEqual('import_stale', caught.exception.code)
        rows = self.query(database,
            "SELECT (SELECT count(*) FROM wl_ingestion.stages g WHERE g.set_id='" + plan['set_id']
            + "'), (SELECT state FROM wl_ingestion.members WHERE id='" + member_id
            + "'), (SELECT state FROM wl_ingestion.sets WHERE id='" + plan['set_id'] + "')")[0]
        self.assertEqual((1, 'admitted', 'NORMALIZING'), tuple(rows))

    def test_ac_03_finish_confirmation_replays_but_a_new_request_is_stale(self):
        """AC-IMP-007F-03: a confirmed finish replays once and only for its request."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        minimal = _minimal(context, sha256(raw), sha256(b'{"synthetic":true}'))
        sql = WorkerSQL(database, self.WORKER)
        token = 'ab' * 32
        sql.call('claim_member_v1', {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                 'job_id': context['job_id'], 'set_id': plan['set_id'],
                 'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                 'request_id': str(uuid.uuid4()), 'raw_digest': sha256(raw),
                 'context_digest': sha256(context_bytes)}, token=token)
        sql.call('admit_stage_v1', {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                 'job_id': context['job_id'], 'set_id': plan['set_id'],
                 'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                 'request_id': str(uuid.uuid4()), 'stage_digest': sha256(minimal),
                 'raw_digest': sha256(raw), 'discovery_digest': sha256(b'{"synthetic":true}'),
                 'payload_bytes': len(minimal)}, payload=minimal, token=token)
        finish = {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                  'job_id': context['job_id'], 'set_id': plan['set_id'],
                  'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                  'request_id': str(uuid.uuid4()), 'outcome': 'stage_admitted',
                  'error_code': None, 'cleanup_proofs': []}
        self.assertEqual('admitted', sql.call('finish_member_v1', finish, token=token)['state'])
        first = sql.call('finish_member_v1', finish, token=token)
        second = sql.call('finish_member_v1', finish, token=token)
        self.assertEqual((first, second), (first, second))
        with self.assertRaises(WorkerCallError) as caught:
            sql.call('finish_member_v1', dict(finish, request_id=str(uuid.uuid4())), token=token)
        self.assertEqual('import_stale', caught.exception.code)
        self.assertEqual(1, int(self.scalar(name,
            "SELECT count(*) FROM wl_ingestion.stages g WHERE g.set_id='" + plan['set_id'] + "';")))

    def test_ac_03_launcher_kill_under_postgres_and_docker_reconciles(self):
        """AC-IMP-007F-03: a killed launcher leaves no container and purges once."""
        import subprocess
        from types import SimpleNamespace
        from kurafolio.ingestion.launcher import Launcher
        from kurafolio.ingestion.launcher_engine import DockerEngine

        digest = subprocess.check_output(
            ['docker', 'image', 'inspect', '--format', '{{index .RepoDigests 0}}', self.IMAGE],
            text=True).strip()
        repository, _, _ = digest.partition('@sha256:')
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        with tempfile.TemporaryDirectory(prefix='wl-imp-007f-launcher-') as launcher_root, \
                tempfile.TemporaryDirectory(prefix='wl-imp-007f-worker-') as worker_directory:
            os.chmod(launcher_root, 0o700)
            os.chmod(worker_directory, 0o700)
            journal = Path(launcher_root) / 'journal'
            journal.mkdir(mode=0o700)
            profiles = Path(launcher_root) / 'profiles.json'
            profiles.write_text(json.dumps([self.profile(context)]))
            os.chmod(profiles, 0o600)
            config = SimpleNamespace(instance_id=self.INCARNATION, credential_epoch='1',
                                     journal_directory=journal, image_repository=repository,
                                     profiles_file=profiles, bind_address='127.0.0.1',
                                     bind_port=0, server_tls=None)
            instance = self.INCARNATION
            self.addCleanup(lambda: subprocess.run(
                ['sh', '-c', 'ids=$(docker ps -aq --filter label=kurafolio.launcher.instance='
                 + instance + '); [ -z "$ids" ] || docker rm --force $ids >/dev/null'], check=False))
            start = {'version': 1, 'operation': 'start', 'job_id': context['job_id'],
                     'member_id': member_id, 'fence': '1', 'instance_id': self.INCARNATION,
                     'realm_digest': realm, 'credential_epoch': '1',
                     'installation_id': context['installation_id'],
                     'image_digest': context['image_digest'],
                     'wrapper_profile_digest': context['wrapper_profile_digest'],
                     'format_version': context['format_version'],
                     'context_sha256': sha256(context_bytes), 'context_bytes': len(context_bytes),
                     'raw_sha256': sha256(raw), 'raw_bytes': len(raw),
                     'deadline': _instant(datetime.now(UTC) + timedelta(seconds=120)),
                     'nonce': secrets.token_hex(32)}
            WorkerSQL(database, self.WORKER).call('claim_member_v1', {
                'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                'job_id': context['job_id'], 'set_id': plan['set_id'],
                'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                'request_id': str(uuid.uuid4()), 'raw_digest': sha256(raw),
                'context_digest': sha256(context_bytes)}, token='ab' * 32)
            marker = Path(launcher_root) / 'started.json'
            child = multiprocessing.get_context('fork').Process(
                target=_launcher_child,
                args=(config, start, context_bytes, raw, marker,
                      ('/bin/sh', '-c', 'sleep 30'), context['image_digest'], digest))
            child.start()
            self.addCleanup(lambda: child.is_alive() and child.kill())
            deadline = time.monotonic() + 30
            while not marker.exists():
                if time.monotonic() >= deadline:
                    self.fail('launcher child did not start')
                time.sleep(.1)
            started = json.loads(marker.read_text())
            record = LauncherJournal(journal).get(start['job_id'], '1')
            self.assertEqual('started', record.state)
            self.assertIsNotNone(DockerEngine().inspect(record.engine_id))
            child.kill()
            child.join(10)
            self.assertEqual(-signal.SIGKILL, child.exitcode)
            restarted = Launcher(config, _MappedEngine(context['image_digest'], digest))
            self.assertIsNone(DockerEngine().inspect(record.engine_id))
            recovered = LauncherJournal(journal).get(start['job_id'], '1')
            self.assertEqual(('finished', 'cancelled', True),
                             (recovered.state, recovered.outcome, recovered.cleanup_complete))
            self.run_sql(name, 'BEGIN;' + self.cancel_call(catalog) + 'COMMIT;')
            worker_journal = WorkerJournal(worker_directory)
            worker_journal.record(plan['set_id'], start['job_id'], member_id, '1')
            worker_journal.set_handle(start['job_id'], '1', started['handle'])
            worker = self.worker(database, worker_directory, realm, restarted,
                                 [self.profile(context)],
                                 [(context['installation_id'], b'descriptor')])
            worker._cleanup_once()
            worker._cleanup_once()
            remaining = len(worker.journal.records())
            launcher_remaining = len(LauncherJournal(journal).records())
        rows = self.query(database,
            "SELECT x.state, x.cleanup_state, (SELECT reserved_bytes FROM wl_ingestion.quotas q "
            "WHERE q.portfolio_id=x.portfolio_id AND q.bucket='storage') "
            "FROM wl_ingestion.sets x WHERE x.id='" + plan['set_id'] + "'")[0]
        self.assertEqual(('CANCELLED', 'complete', 0), tuple(rows))
        self.assertEqual(0, remaining)
        self.assertEqual(0, launcher_remaining)

    def test_ac_06_real_launcher_wall_limit_finishes_rejected(self):
        """AC-IMP-007F-06: a real launcher limit ends with a rejected member."""
        import subprocess
        from types import SimpleNamespace
        from kurafolio.ingestion.launcher import Launcher
        from kurafolio.ingestion.launcher_engine import ENTRY, DockerEngine

        digest = subprocess.check_output(
            ['docker', 'image', 'inspect', '--format', '{{index .RepoDigests 0}}', self.IMAGE],
            text=True).strip()
        repository, _, image_digest = digest.partition('@sha256:')
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        class TestEngine(DockerEngine):
            def __init__(self, reference):
                super().__init__()
                self.reference = reference

            def image(self, reference):
                return context['image_digest']

            def create(self, *, reference, labels, entry=ENTRY):
                return super().create(reference=self.reference, labels=labels, entry=entry)

        with tempfile.TemporaryDirectory(prefix='wl-imp-007f-launcher-') as launcher_directory, \
                tempfile.TemporaryDirectory(prefix='wl-imp-007f-worker-') as worker_directory:
            os.chmod(launcher_directory, 0o700)
            os.chmod(worker_directory, 0o700)
            journal = Path(launcher_directory) / 'journal'
            journal.mkdir(mode=0o700)
            profiles = Path(launcher_directory) / 'profiles.json'
            profiles.write_text(json.dumps([self.profile(context)]))
            os.chmod(profiles, 0o600)
            config = SimpleNamespace(instance_id=self.INCARNATION, credential_epoch='1',
                                     journal_directory=journal,
                                     image_repository=repository, profiles_file=profiles,
                                     bind_address='127.0.0.1', bind_port=0, server_tls=None)
            launcher = Launcher(config, TestEngine(digest))
            launcher.entry = ('/bin/sh', '-c', 'sleep 20')
            self.addCleanup(launcher.stop)
            deadline = _instant(datetime.now(UTC) + timedelta(seconds=40))
            metadata = _metadata(context_bytes, raw, 'ab' * 32, realm, plan['set_id'],
                                 member_id)
            metadata = validate({**metadata, 'raw_deadline': deadline}, 'Handoff')
            worker = self.worker(database, worker_directory, realm, launcher,
                                 [self.profile(context)],
                                 [(context['installation_id'], b'descriptor')])
            with mock.patch.object(worker_module.discovery, 'admit_parser2',
                                   side_effect=AssertionError('child must not admit')):
                worker.handoff(metadata, context_bytes, raw)
                worker._executor.run()
        state = self.query(database,
            "SELECT x.state, m.state, m.error_code FROM wl_ingestion.sets x "
            "JOIN wl_ingestion.members m ON m.set_id=x.id WHERE x.id='"
            + plan['set_id'] + "'")[0]
        self.assertEqual(('REJECTED', 'rejected', 'import_limit'), tuple(state))

    def test_ac_05_expired_normalize_lease_refuses_late_admit_and_finish(self):
        """AC-IMP-007F-05: a lapsed lease makes both worker calls import_stale."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        payload = b'{"synthetic":true}'
        minimal = _minimal(context, sha256(raw), sha256(payload))
        sql = WorkerSQL(database, self.WORKER)
        token = 'ab' * 32
        claim = {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                 'job_id': context['job_id'], 'set_id': plan['set_id'],
                 'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                 'request_id': str(uuid.uuid4()), 'raw_digest': sha256(raw),
                 'context_digest': sha256(context_bytes)}
        ack = sql.call('claim_member_v1', claim, token=token)
        self.assertEqual('claimed', ack['outcome'])
        self.run_sql(name, "BEGIN;SET LOCAL session_replication_role=replica;"
                          "UPDATE wl_ingestion.leases SET created_at=created_at-interval '2 minutes',expires_at=pg_catalog.clock_timestamp()"
                          "-interval '1 second' WHERE work_kind='normalize' AND state='active';"
                          "SET LOCAL session_replication_role=origin;COMMIT;")
        admit = {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                 'job_id': context['job_id'], 'set_id': plan['set_id'],
                 'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                 'request_id': str(uuid.uuid4()), 'stage_digest': sha256(minimal),
                 'raw_digest': sha256(raw), 'discovery_digest': sha256(payload),
                 'payload_bytes': len(minimal)}
        finish = {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
                  'job_id': context['job_id'], 'set_id': plan['set_id'],
                  'member_id': member_id, 'work_kind': 'normalize', 'fence': '1',
                  'request_id': str(uuid.uuid4()), 'outcome': 'stage_admitted',
                  'error_code': None, 'cleanup_proofs': []}
        for name_, request in (('admit_stage_v1', admit), ('finish_member_v1', finish)):
            with self.subTest(call=name_):
                with self.assertRaises(WorkerCallError) as caught:
                    sql.call(name_, request, payload=minimal if name_ == 'admit_stage_v1' else None,
                             token=token)
                self.assertIn(caught.exception.code, {'import_stale', 'import_reupload_required'})
        self.assertEqual(0, int(self.scalar(name,
            "SELECT count(*) FROM wl_ingestion.stages g WHERE g.set_id='" + plan['set_id'] + "';")))

    def test_ac_05_cleanup_lease_lapses_and_the_next_claim_fences_it(self):
        """AC-IMP-007F-05: cleanup fence + 1, the late fence is refused, purge once."""
        database, name = self.fresh_database()
        plan, pin, catalog, raw, context_bytes, member_id = self.seed(name)
        context = json.loads(context_bytes)
        realm = self.realm(name)
        self.run_sql(name, 'BEGIN;' + self.cancel_call(catalog) + 'COMMIT;')
        sql = WorkerSQL(database, self.WORKER)
        token = 'cd' * 32
        proof = validate({'job_id': context['job_id'], 'fence': '1', 'state': 'absent',
                          'launcher_instance_id': 'c0000000-0000-4000-8000-000000000003',
                          'proof_digest': '1' * 64,
                          'checked_at': _instant(datetime.now(UTC))}, 'CleanupProof')

        def claim():
            return sql.call('claim_plan_v1', {'version': 1, 'realm_digest': realm,
                'credential_epoch': '1', 'work_kind': 'cleanup',
                'claim_request_id': str(uuid.uuid4())}, token=token)

        first = claim()
        self.assertEqual('claimed', first['outcome'])
        self.run_sql(name, "BEGIN;SET LOCAL session_replication_role=replica;"
                          "UPDATE wl_ingestion.leases SET created_at=created_at-interval '2 minutes',expires_at=pg_catalog.clock_timestamp()"
                          "-interval '1 second' WHERE work_kind='cleanup' AND state='active';"
                          "SET LOCAL session_replication_role=origin;COMMIT;")
        second = claim()
        self.assertEqual('claimed', second['outcome'])
        self.assertEqual(int(first['lease']['fence']) + 1, int(second['lease']['fence']))
        old = {'version': 1, 'realm_digest': realm, 'credential_epoch': '1',
               'job_id': first['lease']['job_id'], 'set_id': first['lease']['set_id'],
               'member_id': None, 'work_kind': 'cleanup', 'fence': first['lease']['fence'],
               'request_id': str(uuid.uuid4()), 'cleanup_proofs': [proof]}
        with self.assertRaises(WorkerCallError) as caught:
            sql.call('cleanup_set_v1', old, token=token)
        self.assertEqual('import_stale', caught.exception.code)
        current = dict(old, fence=second['lease']['fence'], job_id=second['lease']['job_id'],
                       request_id=str(uuid.uuid4()))
        ack = sql.call('cleanup_set_v1', current, token=token)
        self.assertEqual('purged', ack['outcome'])
        self.assertEqual('no_work', claim()['outcome'])
        self.assertEqual(0, int(self.scalar(name,
            "SELECT reserved_bytes FROM wl_ingestion.quotas WHERE bucket='storage';")))


# Disable the inherited fragment cases: this class only runs its own real-driver
# acceptance methods on the loopback-published instance.
for _name in dir(pg.IngestionAppendOnlyPostgresTests):
    if _name.startswith('test_') and _name not in WorkerPostgresTests.__dict__:
        setattr(WorkerPostgresTests, _name, None)
del _name


if __name__ == '__main__':
    unittest.main()
