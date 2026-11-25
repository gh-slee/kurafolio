"""Worker-side unit acceptance: SQL guards, journal, configuration, loops.

AC-IMP-007F-01 (static inventory), AC-IMP-007F-03 (worker side), AC-IMP-007F-05
(renewal and fenced requests), AC-IMP-007F-07 (database side) and the AC-08
configuration and journal refusals, without a database or Docker.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import http.client
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import tempfile
import threading
import time
import unittest
from datetime import datetime as clock_type
import uuid
from unittest import mock

from kurafolio.ingestion import codec, contracts, worker as worker_module
from kurafolio.ingestion.codec import digest, encode, sha256, validate
from kurafolio.ingestion.contracts import IngestionError
from kurafolio.ingestion.handoff_server import HandoffServer
from kurafolio.ingestion.runner_client import PeerTLS, pack_input, pack_result
from kurafolio.ingestion.worker import ImportWorker, LeaseKeeper, RawHold
from kurafolio.ingestion.worker_config import ConfigError, load
from kurafolio.ingestion.worker_journal import JournalError, WorkerJournal
from kurafolio.ingestion.worker_sql import CALLS, WorkerCallError, WorkerSQL
import subprocess

UTC = timezone.utc
INSTANCE = '70000000-0000-4000-8000-000000000002'
REALM = 'a' * 64
INSTALL = 'b' * 64
IMAGE = 'c' * 64
_PROFILE_BODY = {'version': 1, 'installation_id': INSTALL, 'image_digest': IMAGE,
                 'distribution': 'synthetic-wheel',
                 'entry_point': 'kurafolio.ingestion.runner_child:main',
                 'wrapper_sha256': '1' * 64, 'projection': 'domain1-minimal-v1',
                 'format_versions': ['v1'], 'identity_policy': 'provider_scoped_stable'}
PROFILE = digest(_PROFILE_BODY)
FENCE = '1'
TOKEN = 'e' * 64


def _certificate_command(*args):
    result = subprocess.run(args, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('synthetic certificate command failed: ' + args[0])
    return result


def make_peers(directory, roles, *, instance=INSTANCE):
    """Return {role: (ca_file, cert_file, key_file, dns)} for each synthetic TLS peer.

    Each certificate carries the DNS and instance URI names the r7 contract
    requires, so ``PeerTLS.verify_peer`` accepts it. The keys are disposable and
    live only in a temporary directory.
    """
    directory = Path(directory)
    ca_key, ca_cert = directory / 'ca.key', directory / 'ca.crt'
    config = directory / 'ca.cnf'
    config.write_text('[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=ingestion-test-ca\n'
                      '[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n')
    _certificate_command('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-sha256', '-days', '2',
                         '-nodes', '-keyout', str(ca_key), '-out', str(ca_cert),
                         '-config', str(config), '-extensions', 'ca')
    os.chmod(ca_key, 0o600)
    peers = {}
    for role in roles:
        dns = f'{role}.ingestion.test'
        key, cert, csr = directory / f'{role}.key', directory / f'{role}.crt', directory / f'{role}.csr'
        extensions = directory / f'{role}.ext'
        extensions.write_text(
            'basicConstraints=critical,CA:FALSE\n'
            'keyUsage=critical,digitalSignature,keyEncipherment\n'
            'extendedKeyUsage=serverAuth,clientAuth\n'
            f'subjectAltName=DNS:{dns},URI:urn:wealth-ledger:instance:{instance}:peer:{role}\n')
        _certificate_command('openssl', 'req', '-newkey', 'rsa:2048', '-sha256', '-nodes',
                             '-keyout', str(key), '-out', str(csr), '-subj', '/CN=' + dns)
        os.chmod(key, 0o600)
        _certificate_command('openssl', 'x509', '-req', '-in', str(csr), '-CA', str(ca_cert),
                             '-CAkey', str(ca_key), '-CAcreateserial', '-days', '2', '-sha256',
                             '-extfile', str(extensions), '-out', str(cert))
        peers[role] = (ca_cert, cert, key, dns)
    return peers


def instant(value):
    return validate({'tag': 'instant', 'token': value.astimezone(UTC).isoformat(timespec='seconds'),
                     'zone': None, 'fractional_digits': 0}, 'Instant')


def later(**kwargs):
    return datetime.now(UTC) + timedelta(**kwargs)


def native_context(job, member, fence=FENCE):
    return encode(validate({
        'version': 1, 'job_id': job, 'member_id': member, 'fence': fence,
        'installation_id': INSTALL, 'wrapper_profile_digest': PROFILE,
        'format_version': 'v1', 'payload_kind': 'native_discovery_v1',
        'namespace': {'tenant_id': str(uuid.uuid4()), 'portfolio_id': str(uuid.uuid4()),
                      'connection_id': str(uuid.uuid4())},
        'evidence_reference': str(uuid.uuid4()), 'evidence_at': instant(later(minutes=-1)),
        'provider_id': 'synthetic.native', 'image_digest': IMAGE}, 'NativeChildContext'))


def profile_value():
    value = dict(_PROFILE_BODY)
    value['profile_digest'] = PROFILE
    return validate(value, 'WrapperProfile')


def handoff_metadata(context, raw, job, set_id, member, *, token=TOKEN, fence=FENCE,
                     deadline=None, expires=None):
    return validate({'version': 1, 'job_id': job, 'set_id': set_id, 'member_id': member,
                     'fence': fence, 'raw_sha256': sha256(raw), 'raw_bytes': len(raw),
                     'context_sha256': sha256(context), 'context_bytes': len(context),
                     'handoff_token': token, 'realm_digest': REALM,
                     'expires_at': instant(expires or later(minutes=10)),
                     'raw_deadline': instant(deadline or later(minutes=2))}, 'Handoff')


def status_value(handle, job, fence=FENCE, *, state='result_ready', outcome='ok',
                 cleanup=False):
    return validate({'version': 1, 'job_id': job, 'fence': fence, 'handle': handle,
                     'state': state, 'outcome': outcome, 'payload_sha256': None,
                     'cleanup_complete': cleanup}, 'LaunchStatus')


class FakeConfig:
    def __init__(self, directory, journal_directory=None, port=0):
        self.database = None
        self.worker_id = str(uuid.uuid4())
        self.credential_epoch = '1'
        self.instance_id = INSTANCE
        self.realm_digest = REALM
        self.api_tls = None
        self.launcher_tls = None
        self.launcher_host = '127.0.0.1'
        self.launcher_port = port
        self.bind_address = '127.0.0.1'
        self.bind_port = port
        self.journal_directory = journal_directory or directory
        self.catalog_file = Path(directory) / 'catalog.json'
        self.profiles_file = Path(directory) / 'profiles.json'


class InlineExecutor:
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


class FakeSQL:
    """Records every request; answers with contract-valid acknowledgements."""

    def __init__(self, clock=None, *, claim_outcome='claimed', cleanup=None):
        self.calls = []
        self.clock = clock or (lambda: datetime.now(UTC))
        self.claim_outcome = claim_outcome
        self.cleanup = cleanup
        self.renew_error = None
        self.renews = 0
        self.renew_times = []
        self.cleanup_ack = 'purged'

    def call(self, name, request, payload=None, *, token):
        request = json.loads(encode(request))
        self.calls.append((name, request, payload, token))
        if name == 'claim_member_v1':
            return validate({'version': 1, 'job_id': request['job_id'], 'set_id': request['set_id'],
                             'member_id': request['member_id'], 'work_kind': 'normalize',
                             'fence': request['fence'], 'credential_epoch': '1',
                             'expires_at': instant(self.clock() + timedelta(seconds=30)),
                             'outcome': self.claim_outcome, 'source_fingerprint': 'f' * 64}, 'LeaseAck')
        if name == 'renew_member_v1':
            self.renews += 1
            self.renew_times.append(self.clock())
            if self.renew_error is not None:
                raise WorkerCallError(self.renew_error)
            return validate({'version': 1, 'job_id': request['job_id'], 'set_id': request['set_id'],
                             'member_id': request['member_id'], 'work_kind': 'normalize',
                             'fence': request['fence'], 'credential_epoch': '1',
                             'expires_at': instant(self.clock() + timedelta(seconds=30)),
                             'outcome': 'renewed', 'source_fingerprint': 'f' * 64}, 'LeaseAck')
        if name == 'admit_stage_v1':
            return validate({'version': 1, 'job_id': request['job_id'], 'fence': request['fence'],
                             'member_id': request['member_id'], 'stage_digest': request['stage_digest'],
                             'outcome': 'admitted'}, 'StageAck')
        if name == 'finish_member_v1':
            return validate({'version': 1, 'job_id': request['job_id'], 'fence': request['fence'],
                             'member_id': request['member_id'], 'state': 'admitted',
                             'cleanup_complete': True}, 'FinishAck')
        if name == 'claim_plan_v1':
            value = self.cleanup or {'version': 1, 'lease': None, 'outcome': 'no_work'}
            return validate(json.loads(encode(value)), 'PlanClaimResult')
        if name == 'cleanup_set_v1':
            return validate({'version': 1, 'job_id': request['job_id'], 'fence': request['fence'],
                             'set_id': request['set_id'],
                             'cleanup_complete': self.cleanup_ack == 'purged',
                             'quota_released': self.cleanup_ack == 'purged',
                             'outcome': self.cleanup_ack}, 'CleanupAck')
        raise AssertionError('unexpected worker function ' + name)

    def names(self):
        return [call[0] for call in self.calls]


class FakeLauncher:
    """The stage-1 launcher protocol, answering from a scripted sequence."""

    def __init__(self, metadata, payload=b'minimal', *, cleanup=('finished', True), child='ok',
                 payload_kind='native_discovery_v1'):
        self.metadata = metadata
        self.payload = payload
        self.cleanup = cleanup
        self.child = child
        self.payload_kind = payload_kind
        self.starts = []
        self.controls = []
        self.handle = secrets.token_hex(32)
        self.cancelled = False

    def start(self, metadata, context, raw):
        metadata = validate(metadata, 'LaunchStart')
        if metadata['raw_sha256'] != sha256(raw) or metadata['context_sha256'] != sha256(context):
            raise IngestionError('import_invalid')
        self.starts.append((metadata, bytes(context), bytes(raw)))
        self.metadata = metadata
        return status_value(self.handle, metadata['job_id'], metadata['fence'],
                            state='created', outcome=None)

    def _result(self):
        metadata = self.metadata
        header = validate({'version': 1, 'job_id': metadata['job_id'],
                           'member_id': metadata['member_id'], 'fence': metadata['fence'],
                           'installation_id': metadata['installation_id'],
                           'image_digest': metadata['image_digest'],
                           'wrapper_profile_digest': metadata['wrapper_profile_digest'],
                           'raw_sha256': metadata['raw_sha256'],
                           'context_sha256': metadata['context_sha256'],
                           'payload_sha256': sha256(self.payload),
                           'payload_bytes': len(self.payload),
                           'payload_kind': self.payload_kind, 'outcome': 'ok',
                           'handle': self.handle}, 'LaunchResult')
        return pack_result(header, self.payload)

    def _cleanup_status(self, request):
        return status_value(self.handle, request['job_id'], request['fence'],
                            state=self.cleanup[0], outcome='ok',
                            cleanup=self.cleanup[1])

    def control(self, request):
        request = validate(request, 'LaunchControl')
        self.controls.append(request)
        if request['operation'] == 'cancel':
            self.cancelled = True
            return self._cleanup_status(request), None
        if request['operation'] == 'forget':
            return self._cleanup_status(request), None
        if request['operation'] != 'status':
            raise IngestionError('import_invalid')
        if self.cancelled:
            return self._cleanup_status(request), None
        if self.child != 'ok':
            return status_value(self.handle, request['job_id'], request['fence'], state='failed',
                                outcome=self.child, cleanup=True), None
        if request['include_result']:
            return status_value(self.handle, request['job_id'], request['fence'],
                                state='result_ready', outcome='ok'), self._result()
        return status_value(self.handle, request['job_id'], request['fence'],
                            state='result_ready', outcome='ok'), None


class FakeClock:
    def __init__(self, start=None):
        self.value = start or datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += timedelta(seconds=seconds)


class FakeTLS:
    def __init__(self, peer):
        self.peer = peer

    def context(self, *, server=False):
        return self.peer.context(server=server)

    def verify_peer(self, connection):
        return self.peer.verify_peer(connection)


class WorkerSQLUnitTests(unittest.TestCase):
    def test_ac_01_calls_are_the_six_worker_functions_and_nothing_else(self):
        """AC-IMP-007F-01: the fixed inventory and no prepare function."""
        from kurafolio.persistence import ingestion_schema
        self.assertEqual(('claim_member_v1', 'renew_member_v1', 'admit_stage_v1',
                          'finish_member_v1', 'claim_plan_v1', 'cleanup_set_v1'), CALLS)
        for name in CALLS:
            self.assertIn(name, ingestion_schema.WORKER)
        for name in ('read_plan_basis_v1', 'prepare_preview_v1'):
            self.assertNotIn(name, CALLS)
        directory = Path(__file__).resolve().parents[1] / 'src/kurafolio/ingestion'
        for path in sorted(directory.glob('worker*.py')):
            text = path.read_text()
            self.assertNotIn('read_plan_basis_v1', text, path.name)
            self.assertNotIn('prepare_preview_v1', text, path.name)
            self.assertNotIn("'prepare'", text, path.name)

    def test_ac_01_refuses_unknown_and_prepare_names_before_connecting(self):
        """AC-IMP-007F-01: programming errors never reach PostgreSQL."""
        class Database:
            @property
            def engine(self):
                raise AssertionError('connection opened')

        sql = WorkerSQL(Database(), str(uuid.uuid4()))
        for name in ('read_plan_basis_v1', 'prepare_preview_v1', 'wl_ingestion.claim_member_v1'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    sql.call(name, {}, token=TOKEN)
        with self.assertRaises(ValueError):
            sql.call('claim_plan_v1', {'version': 1, 'realm_digest': REALM, 'credential_epoch': '1',
                                       'work_kind': 'prepare',
                                       'claim_request_id': str(uuid.uuid4())}, token=TOKEN)

    def test_ac_01_transient_database_failure_retries_the_same_request(self):
        """AC-IMP-007F-03: a serialization failure retries with one request id."""
        class Failure(Exception):
            def __init__(self):
                self.orig = type('Orig', (), {'sqlstate': '40001'})()

        request = {'version': 1, 'realm_digest': REALM, 'credential_epoch': '1',
                   'work_kind': 'cleanup', 'claim_request_id': '10000000-0000-4000-8000-000000000001'}
        attempts = []

        class Retrying(WorkerSQL):
            def _execute(self, name, token, body, payload):
                attempts.append(body)
                if len(attempts) < 2:
                    raise Failure()
                return {'ok': True, 'value': {'version': 1, 'lease': None, 'outcome': 'no_work'}}

        sleeps = []
        sql = Retrying(_Unused(), str(uuid.uuid4()), sleep=sleeps.append, jitter=lambda: 0.0)
        self.assertEqual('no_work', sql.call('claim_plan_v1', request, token=TOKEN)['outcome'])
        self.assertEqual(2, len(attempts))
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(1, len(sleeps))

    def test_ac_01_retries_end_as_import_busy(self):
        class Failure(Exception):
            def __init__(self):
                self.orig = type('Orig', (), {'sqlstate': '40P01'})()

        class Failing(WorkerSQL):
            def _execute(self, name, token, body, payload):
                raise Failure()

        sql = Failing(_Unused(), str(uuid.uuid4()), sleep=lambda _: None, jitter=lambda: 0.0)
        with self.assertRaises(WorkerCallError) as caught:
            sql.call('claim_plan_v1', {'version': 1, 'realm_digest': REALM, 'credential_epoch': '1',
                                       'work_kind': 'cleanup',
                                       'claim_request_id': str(uuid.uuid4())}, token=TOKEN)
        self.assertEqual('import_busy', caught.exception.code)


class _Unused:
    engine = None


class WorkerJournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wl-007f-journal-')
        os.chmod(self.directory.name, 0o700)
        self.addCleanup(self.directory.cleanup)
        self.set_id, self.job_id, self.member_id = (str(uuid.uuid4()) for _ in range(3))

    def test_ac_08_record_is_create_only_and_content_free(self):
        journal = WorkerJournal(self.directory.name)
        self.assertTrue(journal.record(self.set_id, self.job_id, self.member_id, FENCE))
        self.assertFalse(journal.record(self.set_id, self.job_id, self.member_id, FENCE))
        journal.set_handle(self.job_id, FENCE, 'a' * 64)
        self.assertFalse(journal.record(self.set_id, self.job_id, self.member_id, FENCE))
        record = journal.for_set(self.set_id)[0]
        self.assertEqual(('a' * 64, FENCE, self.job_id, self.member_id, self.set_id),
                         (record.handle, record.fence, record.job_id, record.member_id, record.set_id))
        path = Path(self.directory.name) / f'{self.job_id}-{FENCE}.json'
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        raw = path.read_bytes()
        self.assertEqual(sorted(['version', 'set_id', 'job_id', 'member_id', 'fence', 'handle']),
                         sorted(json.loads(raw)))
        journal.remove(self.job_id, FENCE)
        self.assertEqual([], journal.records())

    def test_ac_08_unsafe_directory_and_records_are_refused(self):
        other = tempfile.TemporaryDirectory(prefix='wl-007f-unsafe-')
        self.addCleanup(other.cleanup)
        os.chmod(other.name, 0o700)
        unsafe = Path(other.name) / 'unsafe'
        unsafe.mkdir(mode=0o755)
        with self.assertRaises(JournalError) as caught:
            WorkerJournal(unsafe)
        self.assertEqual('journal_unsafe', caught.exception.code)
        link = Path(other.name) / 'link'
        os.symlink(self.directory.name, link)
        with self.assertRaises(JournalError):
            WorkerJournal(link)

        journal = WorkerJournal(self.directory.name)
        journal.record(self.set_id, self.job_id, self.member_id, FENCE)
        path = Path(self.directory.name) / f'{self.job_id}-{FENCE}.json'
        os.chmod(path, 0o644)
        with self.assertRaises(JournalError) as caught:
            WorkerJournal(self.directory.name)
        self.assertEqual('journal_unsafe', caught.exception.code)
        os.chmod(path, 0o600)

        os.link(path, Path(self.directory.name) / 'second-link')
        with self.assertRaises(JournalError):
            WorkerJournal(self.directory.name)
        (Path(self.directory.name) / 'second-link').unlink()

        path.write_bytes(encode({'version': 1, 'set_id': self.set_id, 'job_id': self.job_id,
                                 'member_id': self.member_id, 'fence': FENCE, 'handle': None,
                                 'extra': True}))
        with self.assertRaises(JournalError) as caught:
            WorkerJournal(self.directory.name)
        self.assertEqual('journal_invalid', caught.exception.code)

        other = str(uuid.uuid4())
        path.write_bytes(encode({'version': 1, 'set_id': self.set_id, 'job_id': other,
                                 'member_id': self.member_id, 'fence': FENCE, 'handle': None}))
        with self.assertRaises(JournalError) as caught:
            WorkerJournal(self.directory.name)
        self.assertEqual('journal_invalid', caught.exception.code)

    def test_ac_08_unknown_name_is_refused(self):
        journal = WorkerJournal(self.directory.name)
        journal.record(self.set_id, self.job_id, self.member_id, FENCE)
        (Path(self.directory.name) / 'not-a-record.json').write_bytes(b'{}')
        os.chmod(Path(self.directory.name) / 'not-a-record.json', 0o600)
        with self.assertRaises(JournalError) as caught:
            WorkerJournal(self.directory.name)
        self.assertEqual('journal_invalid', caught.exception.code)


class WorkerConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wl-007f-config-')
        self.addCleanup(self.directory.cleanup)
        os.chmod(self.directory.name, 0o700)
        self.peers = make_peers(self.directory.name, ['worker', 'api', 'launcher'])

    def _write(self, name, data, mode=0o600):
        path = Path(self.directory.name) / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data if isinstance(data, bytes) else data.encode())
        os.chmod(path, mode)
        return path

    def _config(self, **changes):
        secret = self._write('dsn.txt', 'host=127.0.0.1 port=1 dbname=postgres user=postgres')
        catalog = self._write('catalog.json', '{}', 0o644)
        value = {
            'version': 1,
            'database': {'secret_file': str(secret), 'pool_size': 2},
            'worker_id': str(uuid.uuid4()), 'credential_epoch': '1', 'instance_id': INSTANCE,
            'realm_digest': REALM,
            'api_tls': {'ca_file': str(self.peers['worker'][0]),
                        'cert_file': str(self.peers['worker'][1]),
                        'key_file': str(self.peers['worker'][2]),
                        'peer_dns': self.peers['api'][3]},
            'launcher_tls': {'ca_file': str(self.peers['worker'][0]),
                             'cert_file': str(self.peers['worker'][1]),
                             'key_file': str(self.peers['worker'][2]),
                             'peer_dns': self.peers['launcher'][3]},
            'launcher_host': 'launcher', 'launcher_port': 8443,
            'bind_address': '0.0.0.0', 'bind_port': 8444,
            'journal_directory': self.directory.name, 'catalog_file': str(catalog),
            'profiles_file': str(self._write('profiles.json', '[]', 0o644)),
        }
        value.update(changes)
        return self._write('worker.json', json.dumps(value))

    @unittest.skipUnless(importlib.util.find_spec('psycopg'),
                         'psycopg is installed only with the PostgreSQL requirements')
    def test_ac_08_closed_configuration_loads_from_files(self):
        config = load(self._config())
        self.assertEqual((REALM, '1', INSTANCE), (config.realm_digest, config.credential_epoch,
                                                  config.instance_id))

    def _rewrite(self, path, value):
        path.write_text(json.dumps(value))
        os.chmod(path, 0o600)
        return path

    def test_ac_08_unknown_key_is_refused(self):
        path = self._config()
        value = json.loads(path.read_bytes())
        value['extra'] = True
        self._rewrite(path, value)
        with self.assertRaises(ConfigError):
            load(path)

    def test_ac_08_group_readable_or_symlinked_secret_is_refused(self):
        path = self._config()
        value = json.loads(path.read_bytes())
        os.chmod(value['database']['secret_file'], 0o640)
        with self.assertRaises(ConfigError):
            load(path)
        os.chmod(value['database']['secret_file'], 0o600)
        link = Path(self.directory.name) / 'dsn-link.txt'
        os.symlink(value['database']['secret_file'], link)
        value['database']['secret_file'] = str(link)
        self._rewrite(path, value)
        with self.assertRaises(ConfigError):
            load(path)

    def test_ac_08_key_file_must_be_private(self):
        path = self._config()
        value = json.loads(path.read_bytes())
        os.chmod(value['api_tls']['key_file'], 0o644)
        with self.assertRaises(ConfigError):
            load(path)


class HandoffServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wl-007f-handoff-')
        self.addCleanup(self.directory.cleanup)
        os.chmod(self.directory.name, 0o700)
        self.peers = make_peers(self.directory.name,
                                              ['worker', 'api', 'launcher', 'intruder'])
        self.received = []
        real = socket.getaddrinfo
        host = self.peers['worker'][3]

        def resolve(name, port, *args, **kwargs):
            return real('127.0.0.1' if name == host else name, port, *args, **kwargs)

        patch = mock.patch.object(socket, 'getaddrinfo', resolve)
        patch.start()
        self.addCleanup(patch.stop)

    def _server(self, handler):
        ca, cert, key, dns = self.peers['worker']
        peer = PeerTLS(ca_file=ca, cert_file=cert, key_file=key, peer_dns=self.peers['api'][3],
                       instance_id=INSTANCE, peer_role='api')
        server = HandoffServer(peer, '127.0.0.1', 0, handler)
        address = server.start()
        self.addCleanup(server.stop)
        return address

    def _client(self, role='api', peer_role='worker'):
        ca, cert, key, dns = self.peers[role]
        return PeerTLS(ca_file=ca, cert_file=cert, key_file=key,
                       peer_dns=self.peers[peer_role][3], instance_id=INSTANCE,
                       peer_role=peer_role)

    def _frame(self):
        job, set_id, member = (str(uuid.uuid4()) for _ in range(3))
        context = native_context(job, member)
        raw = b'synthetic raw bytes'
        metadata = handoff_metadata(context, raw, job, set_id, member)
        return metadata, context, raw

    def test_ac_01_handoff_accepts_the_frame_and_returns_one_ack(self):
        """AC-IMP-007F-01: the single private handoff route."""
        def handler(metadata, context, raw):
            self.received.append((metadata, context, raw))
            return validate({'version': 1, 'job_id': metadata['job_id'],
                             'member_id': metadata['member_id'], 'fence': metadata['fence'],
                             'input_owned': True, 'outcome': 'owned',
                             'stage_digest': None}, 'HandoffAck')

        address = self._server(handler)
        metadata, context, raw = self._frame()
        body = pack_input(metadata, context, raw, schema='Handoff')
        tls = self._client()
        connection = http.client.HTTPSConnection(self.peers['worker'][3], address[1], timeout=10,
                                                 context=tls.context())
        connection.connect()
        tls.verify_peer(connection.sock)
        connection.request('POST', '/internal/v1/handoffs', body=body,
                           headers={'Content-Type': 'application/octet-stream',
                                    'Content-Length': str(len(body))})
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        self.assertEqual(202, response.status)
        ack = json.loads(payload)
        self.assertEqual(('owned', True, metadata['job_id']), (ack['outcome'], ack['input_owned'],
                                                               ack['job_id']))
        self.assertEqual(1, len(self.received))

    def test_ac_01_other_paths_and_headers_are_refused_without_detail(self):
        def handler(metadata, context, raw):
            raise AssertionError('handler must not run')

        address = self._server(handler)
        tls = self._client()

        def request(method, path, headers=None, body=b''):
            connection = http.client.HTTPSConnection(self.peers['worker'][3], address[1], timeout=10,
                                                     context=tls.context())
            connection.connect()
            tls.verify_peer(connection.sock)
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            payload = response.read()
            connection.close()
            return response.status, json.loads(payload) if payload else None

        self.assertEqual((404, {'code': 'not_found'}), request('GET', '/internal/v1/handoffs'))
        self.assertEqual((405, {'code': 'method_not_allowed'}),
                         request('PUT', '/internal/v1/handoffs', body=b'x'))
        self.assertEqual((404, {'code': 'not_found'}), request('POST', '/other', body=b'x'))
        self.assertEqual((400, {'code': 'invalid_headers'}),
                         request('POST', '/internal/v1/handoffs',
                                 {'Content-Encoding': 'gzip', 'Content-Length': '1'}, b'x'))
        self.assertEqual((413, {'code': 'import_limit'}),
                         request('POST', '/internal/v1/handoffs', {'Content-Length': '0'}))

    def test_ac_01_wrong_peer_certificate_is_refused_before_the_body(self):
        def handler(metadata, context, raw):
            raise AssertionError('handler must not run')

        address = self._server(handler)
        intruder = self._client(role='intruder')
        with self.assertRaises(Exception):
            connection = http.client.HTTPSConnection(self.peers['worker'][3], address[1], timeout=10,
                                                     context=intruder.context())
            connection.connect()
            intruder.verify_peer(connection.sock)
            connection.request('POST', '/internal/v1/handoffs', body=b'x',
                               headers={'Content-Length': '1'})
            connection.getresponse().read()


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wl-007f-normalize-')
        self.addCleanup(self.directory.cleanup)
        os.chmod(self.directory.name, 0o700)
        self.job, self.set_id, self.member = (str(uuid.uuid4()) for _ in range(3))
        self.context = native_context(self.job, self.member)
        self.raw = b'synthetic raw bytes'
        self.metadata = handoff_metadata(self.context, self.raw, self.job, self.set_id, self.member)
        self.clock = FakeClock()
        self.patch = mock.patch.object(worker_module, '_now', self.clock.now)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.sql = FakeSQL(self.clock.now)

    def _worker(self, launcher):
        config = FakeConfig(self.directory.name)
        worker = ImportWorker(config, sql=self.sql, launcher=launcher, sleep=self.clock.sleep,
                              profiles=[profile_value()], descriptors=[(INSTALL, b'descriptor')])
        worker._executor = InlineExecutor()
        return worker

    def test_ac_03_normalize_admits_stage_then_finishes_with_an_absent_proof(self):
        launcher = FakeLauncher(self.metadata)
        worker = self._worker(launcher)
        with mock.patch.object(worker_module.discovery, 'admit_native', return_value=b'minimal'):
            ack = worker.handoff(self.metadata, self.context, self.raw)
            worker._executor.run()
        self.assertEqual('owned', ack['outcome'])
        names = self.sql.names()
        self.assertEqual(['claim_member_v1', 'admit_stage_v1', 'finish_member_v1'], names)
        claim = self.sql.calls[0][1]
        admit = self.sql.calls[1]
        finish = self.sql.calls[2][1]
        self.assertEqual((claim['fence'], claim['job_id'], 'normalize'),
                         (admit[1]['fence'], admit[1]['job_id'], admit[1]['work_kind']))
        self.assertEqual((claim['fence'], claim['job_id']), (finish['fence'], finish['job_id']))
        self.assertEqual(('stage_admitted', None), (finish['outcome'], finish['error_code']))
        self.assertEqual(['absent'], [proof['state'] for proof in finish['cleanup_proofs']])
        self.assertEqual(TOKEN, admit[3])
        self.assertEqual(b'minimal', admit[2])
        self.assertEqual([], worker.journal.records())
        self.assertTrue(any(control['operation'] == 'forget' for control in launcher.controls))
        self.assertEqual({}, worker._attempts)

    def test_ac_03_context_rejection_finishes_rejected_without_a_launch(self):
        launcher = FakeLauncher(self.metadata)
        worker = self._worker(launcher)
        with mock.patch.object(worker, '_context',
                               side_effect=IngestionError('import_stale')):
            worker.handoff(self.metadata, self.context, self.raw)
            worker._executor.run()
        finish = [call[1] for call in self.sql.calls if call[0] == 'finish_member_v1'][0]
        self.assertEqual(('rejected', 'import_stale'),
                         (finish['outcome'], finish['error_code']))
        self.assertEqual([], finish['cleanup_proofs'])
        self.assertEqual([], launcher.starts)

    def test_ac_03_output_limits_reject_the_member_and_keep_an_absent_proof(self):
        launcher = FakeLauncher(self.metadata, child='output_limit')
        worker = self._worker(launcher)
        worker.handoff(self.metadata, self.context, self.raw)
        worker._executor.run()
        finish = [call[1] for call in self.sql.calls if call[0] == 'finish_member_v1'][0]
        self.assertEqual(('rejected', 'import_limit'),
                         (finish['outcome'], finish['error_code']))
        self.assertEqual('absent', finish['cleanup_proofs'][0]['state'])
        self.assertEqual([], worker.journal.records())

    def test_ac_03_pending_cleanup_proof_keeps_the_journal_and_slot(self):
        launcher = FakeLauncher(self.metadata, cleanup=('cleanup_pending', False))
        worker = self._worker(launcher)
        with mock.patch.object(worker_module.discovery, 'admit_native', return_value=b'minimal'):
            worker.handoff(self.metadata, self.context, self.raw)
            worker._executor.run()
        finish = [call[1] for call in self.sql.calls if call[0] == 'finish_member_v1'][0]
        self.assertEqual(['pending'], [proof['state'] for proof in finish['cleanup_proofs']])
        self.assertEqual(1, len(worker.journal.records()))
        self.assertFalse(any(control['operation'] == 'forget' for control in launcher.controls))

    def test_ac_03_proof_wait_ends_before_the_raw_deadline(self):
        """AC-IMP-007F-03: the wait stops `raw_deadline - 5 s` with a pending proof."""
        deadline = self.clock.now() + timedelta(seconds=40)
        self.metadata = handoff_metadata(self.context, self.raw, self.job, self.set_id,
                                         self.member, deadline=deadline)
        launcher = FakeLauncher(self.metadata, cleanup=('cleanup_pending', False))
        worker = self._worker(launcher)
        with mock.patch.object(worker_module.discovery, 'admit_native', return_value=b'minimal'):
            worker.handoff(self.metadata, self.context, self.raw)
            worker._executor.run()
        finish = [call[1] for call in self.sql.calls if call[0] == 'finish_member_v1'][0]
        self.assertEqual('pending', finish['cleanup_proofs'][0]['state'])
        self.assertLessEqual(self.clock.now(), deadline - timedelta(seconds=5))
        self.assertEqual(1, len(worker.journal.records()))

    def test_ac_03_duplicate_handoff_is_owned_once(self):
        launcher = FakeLauncher(self.metadata)
        worker = self._worker(launcher)
        with mock.patch.object(worker_module.discovery, 'admit_native', return_value=b'minimal'):
            self.assertEqual('owned', worker.handoff(self.metadata, self.context, self.raw)['outcome'])
            second = worker.handoff(self.metadata, self.context, self.raw)
            self.assertEqual(('already_owned', True), (second['outcome'], second['input_owned']))
            self.assertEqual(1, len(self.sql.calls))
            worker._executor.run()
        self.assertEqual(1, len(launcher.starts))

    def test_ac_03_restart_already_claimed_starts_no_launch_and_keeps_the_record(self):
        self.sql.claim_outcome = 'already_claimed'
        launcher = FakeLauncher(self.metadata)
        worker = self._worker(launcher)
        with self.assertRaises(IngestionError) as caught:
            worker.handoff(self.metadata, self.context, self.raw)
        self.assertEqual('import_runner_unavailable', caught.exception.code)
        self.assertEqual([], launcher.starts)
        self.assertEqual(1, len(worker.journal.records()))

    def test_ac_03_mismatched_hash_is_refused_before_any_claim(self):
        worker = self._worker(FakeLauncher(self.metadata))
        with self.assertRaises(IngestionError) as caught:
            worker.handoff(self.metadata, self.context, b'other bytes')
        self.assertEqual('import_invalid', caught.exception.code)
        self.assertEqual([], self.sql.calls)

    def test_ac_01_every_normalize_request_carries_the_claimed_fence(self):
        launcher = FakeLauncher(self.metadata)
        worker = self._worker(launcher)
        with mock.patch.object(worker_module.discovery, 'admit_native', return_value=b'minimal'):
            worker.handoff(self.metadata, self.context, self.raw)
            worker._executor.run()
        after_claim = [(name, request) for name, request, _, _ in self.sql.calls
                       if name != 'claim_member_v1']
        self.assertTrue(after_claim)
        for name, request in after_claim:
            self.assertEqual(FENCE, request['fence'], name)
            self.assertEqual(self.job, request['job_id'], name)

    def test_ac_03_raw_hold_is_zeroed_after_finish(self):
        launcher = FakeLauncher(self.metadata)
        worker = self._worker(launcher)
        holds = []

        class Capture(RawHold):
            def __init__(self, raw, context, deadline):
                super().__init__(raw, context, deadline)
                holds.append(self)

        with mock.patch.object(worker_module, 'RawHold', Capture):
            with mock.patch.object(worker_module.discovery, 'admit_native', return_value=b'minimal'):
                worker.handoff(self.metadata, self.context, self.raw)
                worker._executor.run()
        self.assertEqual(1, len(holds))
        self.assertEqual(bytearray(), holds[0].raw)
        self.assertEqual(bytearray(), holds[0].context)


class RenewalTests(unittest.TestCase):
    def test_ac_01_lease_keeper_constructs_and_starts(self):
        """AC-IMP-007F-01: ImportWorker.start() can create the real keeper."""
        clock = FakeClock()
        keeper = LeaseKeeper(FakeSQL(clock.now), {}, realm_digest=REALM,
                             credential_epoch='1', clock=clock.now, wait=lambda seconds: True)
        keeper.start()
        keeper.stop()
    def test_ac_05_renews_at_most_ten_seconds_apart_and_stops_after_an_error(self):
        clock = FakeClock()
        sql = FakeSQL(clock.now)
        attempt = worker_module.Attempt(job_id=str(uuid.uuid4()), set_id=str(uuid.uuid4()),
                                        member_id=str(uuid.uuid4()), fence=FENCE, token=TOKEN,
                                        expires_at=clock.now() + timedelta(seconds=30),
                                        lost=threading.Event(), next_renew=clock.now())
        stop_at = clock.now() + timedelta(seconds=45)
        stops = []

        def wait(seconds):
            clock.sleep(seconds)
            return clock.now() >= stop_at

        keeper = LeaseKeeper(sql, {(attempt.job_id, attempt.fence): attempt},
                             realm_digest=REALM, credential_epoch='1', clock=clock.now, wait=wait)
        keeper._run()
        renews = [call for call in sql.calls if call[0] == 'renew_member_v1']
        self.assertGreaterEqual(len(renews), 4)
        gaps = [later - earlier for earlier, later in zip(sql.renew_times, sql.renew_times[1:])]
        self.assertTrue(gaps)
        self.assertLessEqual(max(gaps), timedelta(seconds=10))
        # Every renewal request repeats the claimed fence, job and token.
        for _, request, _, token in renews:
            self.assertEqual((FENCE, attempt.job_id, TOKEN),
                             (request['fence'], request['job_id'], token))
        self.assertFalse(attempt.lost.is_set())


class LeaseKeeperErrorTests(unittest.TestCase):
    def test_ac_05_no_renewal_after_the_first_renew_error(self):
        clock = FakeClock()
        sql = FakeSQL(clock.now)
        sql.renew_error = 'import_stale'
        attempt = worker_module.Attempt(job_id=str(uuid.uuid4()), set_id=str(uuid.uuid4()),
                                        member_id=str(uuid.uuid4()), fence=FENCE, token=TOKEN,
                                        expires_at=clock.now() + timedelta(seconds=30),
                                        lost=threading.Event(), next_renew=clock.now())
        stop_at = clock.now() + timedelta(seconds=30)

        def wait(seconds):
            clock.sleep(seconds)
            return clock.now() >= stop_at

        keeper = LeaseKeeper(sql, {(attempt.job_id, attempt.fence): attempt},
                             realm_digest=REALM, credential_epoch='1', clock=clock.now, wait=wait)
        keeper._run()
        self.assertEqual(1, sql.renews)
        self.assertTrue(attempt.lost.is_set())


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wl-007f-cleanup-')
        self.addCleanup(self.directory.cleanup)
        os.chmod(self.directory.name, 0o700)
        self.clock = FakeClock()
        self.patch = mock.patch.object(worker_module, '_now', self.clock.now)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.job, self.set_id, self.member = (str(uuid.uuid4()) for _ in range(3))
        self.handle = secrets.token_hex(32)
        lease = validate({'version': 1, 'job_id': self.job, 'set_id': self.set_id, 'member_id': None,
                          'work_kind': 'cleanup', 'fence': '4', 'credential_epoch': '1',
                          'expires_at': instant(later(seconds=30)), 'outcome': 'claimed',
                          'source_fingerprint': 'f' * 64}, 'LeaseAck')
        self.sql = FakeSQL(self.clock.now,
                           cleanup={'version': 1, 'lease': lease, 'outcome': 'claimed'})

    def _worker(self, launcher):
        worker = ImportWorker(FakeConfig(self.directory.name), sql=self.sql, launcher=launcher,
                              profiles=[], descriptors=[])
        worker.journal.record(self.set_id, self.job, self.member, FENCE)
        worker.journal.set_handle(self.job, FENCE, self.handle)
        return worker

    def test_ac_07_cleanup_sends_the_journal_proof_and_drops_the_record(self):
        class Launcher:
            def __init__(self):
                self.controls = []

            def control(self, request):
                self.controls.append(request)
                return status_value(self.handle, request['job_id'], request['fence'],
                                    state='finished', outcome='ok', cleanup=True), None

            handle = secrets.token_hex(32)

        launcher = Launcher()
        launcher.handle = self.handle
        worker = self._worker(launcher)
        worker._cleanup_once()
        cleanup = [call[1] for call in self.sql.calls if call[0] == 'cleanup_set_v1'][0]
        self.assertEqual(['absent'], [proof['state'] for proof in cleanup['cleanup_proofs']])
        self.assertEqual((self.handle, 'cancel'),
                         (launcher.controls[0]['handle'], launcher.controls[0]['operation']))
        self.assertEqual([], worker.journal.records())
        self.assertTrue(any(control['operation'] == 'forget' for control in launcher.controls))

    def test_ac_07_pending_proof_keeps_the_record_and_the_reservation(self):
        class Launcher:
            handle = self.handle

            def control(self, request):
                return status_value(self.handle, request['job_id'], request['fence'],
                                    state='cleanup_pending', outcome='ok', cleanup=False), None

        worker = self._worker(Launcher())
        worker.sql.cleanup_ack = 'cleanup_pending'
        worker._cleanup_once()
        cleanup = [call[1] for call in self.sql.calls if call[0] == 'cleanup_set_v1'][0]
        self.assertEqual(['pending'], [proof['state'] for proof in cleanup['cleanup_proofs']])
        self.assertEqual(1, len(worker.journal.records()))
        self.assertEqual('cancel', worker.launcher.controls[0]['operation']) if hasattr(worker.launcher, 'controls') else None


if __name__ == '__main__':
    unittest.main()
