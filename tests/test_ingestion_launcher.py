"""Launcher unit acceptance: framing, journal, controls, restart reconciliation.

AC-IMP-007F-02 (the exact child profile is asserted by the engine argument
builder), AC-IMP-007F-03 (restart and late output), AC-IMP-007F-07 (ownership
cleanup) and the refusal rows, with a fake engine and no Docker.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import secrets
import ssl
import tempfile
import time
import unittest
import uuid

from kurafolio.ingestion.codec import digest, encode, sha256, validate
from kurafolio.ingestion.contracts import IngestionError
from kurafolio.ingestion.launcher import Launcher, LauncherConfig
from kurafolio.ingestion.launcher_engine import ENTRY, PROFILE, Run
from kurafolio.ingestion.launcher_journal import LauncherJournal, Record
from kurafolio.ingestion.runner_client import PeerTLS, pack_input, pack_result, unpack_result
from tests.test_ingestion_worker import make_peers

INSTANCE = '70000000-0000-4000-8000-000000000002'
IMAGE = '83125eb1979a26b9249616951138ab5afc27bd21a215bb5b4612b235acd3c34f'
REALM = 'a' * 64
INSTALL = 'f06bc8ee0d18a396929d1d727e33e6bf797ed77ba5464694d24f3bcb18032faf'
PROFILE_DIGEST = 'abbf287e139480d72e231047d92127a9a564fa01d6a74faaa395b1bc1ad65fbe'
FORMAT = 'synthetic-csv-v1'
ENGINE_ID = 'b' * 64


def wrapper():
    oracle = json.loads((Path(__file__).parent / 'fixtures/ingestion/oracle.json').read_text())
    return validate(oracle['wrapper-parser2.json'], 'WrapperProfile')


def context(job=None, member=None, fence='1'):
    value = {'version': 1, 'job_id': job or str(uuid.uuid4()),
             'member_id': member or str(uuid.uuid4()), 'fence': fence,
             'installation_id': INSTALL, 'wrapper_profile_digest': PROFILE_DIGEST,
             'format_version': FORMAT, 'image_digest': IMAGE, 'payload_kind': 'parser_v2',
             'parser_context': {'evidence_at': '2026-02-02T13:00:00+00:00',
                                'source_reference': str(uuid.uuid4()), 'account_alias': None,
                                'source_timezone': None, 'format_selection': FORMAT,
                                'revisions': [], 'scope_revisions': []}}
    return encode(validate(value, 'ParserChildContext'))


def metadata(context_value, raw, *, nonce=None, epoch='1', realm=REALM):
    value = json.loads(context_value)
    return validate({'version': 1, 'operation': 'start', 'job_id': value['job_id'],
                     'member_id': value['member_id'], 'fence': value['fence'],
                     'instance_id': INSTANCE, 'realm_digest': realm, 'credential_epoch': epoch,
                     'installation_id': INSTALL, 'image_digest': IMAGE,
                     'wrapper_profile_digest': PROFILE_DIGEST, 'format_version': FORMAT,
                     'context_sha256': sha256(context_value), 'context_bytes': len(context_value),
                     'raw_sha256': sha256(raw), 'raw_bytes': len(raw),
                     'deadline': {'tag': 'instant', 'token': '2099-01-01T00:00:00+00:00',
                                  'zone': None, 'fractional_digits': 0},
                     'nonce': nonce or secrets.token_hex(32)}, 'LaunchStart')


def child_frame(meta, payload=b'{"synthetic":true}'):
    return pack_result({'version': 1, 'job_id': meta['job_id'], 'member_id': meta['member_id'],
                        'fence': meta['fence'], 'installation_id': INSTALL,
                        'image_digest': IMAGE, 'wrapper_profile_digest': PROFILE_DIGEST,
                        'raw_sha256': meta['raw_sha256'], 'context_sha256': meta['context_sha256'],
                        'payload_sha256': sha256(payload), 'payload_bytes': len(payload),
                        'payload_kind': 'parser_v2', 'outcome': 'ok'},
                       payload, child=True)


class FakeEngine:
    def __init__(self, *, frame=None, outcome=None, oom=False, exit_code=0, created=True):
        self.frame = frame
        self.outcome = outcome
        self.oom = oom
        self.exit_code = exit_code
        self.created = []
        self.starts = []
        self.killed = []
        self.removed = set()
        self.found = ()
        self.created_ok = created
        self.image_calls = []

    def image(self, reference):
        self.image_calls.append(reference)
        return 'sha256:' + reference.rsplit('@sha256:', 1)[1]

    def create(self, *, reference, labels, entry=ENTRY):
        self.created.append((reference, tuple(labels), tuple(entry)))
        if not self.created_ok:
            from kurafolio.ingestion.launcher_engine import EngineError
            raise EngineError('import_runner_unavailable')
        return ENGINE_ID

    def start(self, engine_id, frame, execution_limit=10):
        self.starts.append((engine_id, frame, execution_limit))
        return Run(output=None if self.outcome else (self.frame or b''), outcome=self.outcome,
                   overflow=False, exit_code=self.exit_code, oom_killed=self.oom,
                   killed=False, started_at='2026-11-24T00:00:00Z')

    def inspect(self, engine_id):
        if engine_id in self.removed:
            return None
        return {'ExitCode': self.exit_code, 'OOMKilled': self.oom,
                'StartedAt': '2026-11-24T00:00:00Z'}

    def kill(self, engine_id):
        self.killed.append(engine_id)

    def remove(self, engine_id):
        self.removed.add(engine_id)
        return True

    def find(self, instance_id, nonce_digest):
        return self.found


class Config:
    instance_id = INSTANCE
    credential_epoch = '1'
    bind_address = '127.0.0.1'
    bind_port = 1
    image_repository = 'kurafolio-source'
    server_tls = None


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wl-imp-007f-launcher-')
        self.addCleanup(self.directory.cleanup)
        journal = Path(self.directory.name) / 'journal'
        journal.mkdir(mode=0o700)
        self.journal_directory = journal
        self.profiles = Path(self.directory.name) / 'profiles.json'
        self.profiles.write_text(json.dumps([wrapper()]))
        config = Config()
        config.journal_directory = journal
        config.profiles_file = self.profiles
        self.config = config

    def launcher(self, engine=None):
        return Launcher(self.config, engine or FakeEngine())

    def start(self, launcher, engine, *, raw=b'synthetic,raw\n', nonce=None, epoch='1'):
        value = context()
        meta = metadata(value, raw, nonce=nonce, epoch=epoch)
        engine.frame = engine.frame or child_frame(meta)
        status = launcher.start(meta, value, raw)
        deadline = time.monotonic() + 5
        attempt = launcher._attempts[(meta['job_id'], meta['fence'])]
        while attempt.record.state not in {'result_ready', 'failed'} and time.monotonic() < deadline:
            time.sleep(.01)
        return meta, attempt

    def control(self, launcher, meta, handle_value=None, operation='status', include=False, **changes):
        request = {'version': 1, 'operation': operation, 'instance_id': INSTANCE,
                   'realm_digest': REALM, 'credential_epoch': '1', 'job_id': meta['job_id'],
                   'member_id': meta['member_id'], 'fence': meta['fence'],
                   'handle': changes.pop('handle', handle_value),
                   'include_result': include, **changes}
        return launcher.control(validate(request, 'LaunchControl'))

    def test_ac_02_start_uses_the_exact_profile_and_returns_a_bound_result(self):
        engine = FakeEngine()
        launcher = self.launcher(engine)
        meta, attempt = self.start(launcher, engine)
        reference, labels, entry = engine.created[0]
        self.assertEqual('kurafolio-source@sha256:' + IMAGE, reference)
        self.assertEqual((('kurafolio.launcher.instance', INSTANCE),
                          ('kurafolio.launcher.nonce', sha256(meta['nonce'].encode())),
                          ('kurafolio.launcher.fence', meta['fence'])), labels)
        self.assertEqual(ENTRY, entry)
        self.assertEqual('--read-only', PROFILE[PROFILE.index('--read-only')])
        self.assertIn('--cap-drop', PROFILE)
        self.assertEqual('result_ready', attempt.record.state)
        status, frame = self.control(launcher, meta, attempt.handle, include=True)
        self.assertEqual(('ok', True), (status['outcome'], status['payload_sha256'] is not None))
        header, payload = unpack_result(frame, {**{k: meta[k] for k in
            ('job_id', 'member_id', 'fence', 'installation_id', 'image_digest',
             'wrapper_profile_digest', 'raw_sha256', 'context_sha256')},
            'payload_kind': 'parser_v2', 'handle': attempt.handle})
        self.assertEqual(b'{"synthetic":true}', payload)
        self.assertEqual(header['handle'], attempt.handle)

    def test_ac_01_journal_holds_digests_only_and_status_echoes_the_handle(self):
        engine = FakeEngine()
        launcher = self.launcher(engine)
        meta, attempt = self.start(launcher, engine)
        record = LauncherJournal(self.journal_directory).get(meta['job_id'], meta['fence'])
        self.assertEqual((sha256(meta['nonce'].encode()), sha256(attempt.handle.encode())),
                         (record.nonce_digest, record.handle_digest))
        raw = b''.join(path.read_bytes() for path in self.journal_directory.iterdir())
        for value in (meta['nonce'].encode(), attempt.handle.encode(), b'synthetic,raw'):
            self.assertNotIn(value, raw)
        status, frame = self.control(launcher, meta, attempt.handle)
        self.assertIsNone(frame)
        self.assertEqual(attempt.handle, status['handle'])

    def test_ac_03_cancel_finishes_removal_and_forget_drops_only_terminal_records(self):
        engine = FakeEngine()
        launcher = self.launcher(engine)
        meta, attempt = self.start(launcher, engine)
        with self.assertRaises(IngestionError) as refused:
            self.control(launcher, meta, attempt.handle, 'forget')
        self.assertEqual('import_conflict', refused.exception.code)
        status, _ = self.control(launcher, meta, attempt.handle, 'cancel')
        self.assertEqual(('finished', True), (status['state'], status['cleanup_complete']))
        self.assertIn(ENGINE_ID, engine.killed)
        self.assertIn(ENGINE_ID, engine.removed)
        status, _ = self.control(launcher, meta, attempt.handle, 'forget')
        self.assertEqual('finished', status['state'])
        self.assertIsNone(LauncherJournal(self.journal_directory).get(meta['job_id'], meta['fence']))

    def test_ac_03_restart_reconciles_owned_children_and_discards_late_results(self):
        engine = FakeEngine()
        launcher = self.launcher(engine)
        meta, attempt = self.start(launcher, engine)
        journal = LauncherJournal(self.journal_directory)
        journal.update(meta['job_id'], meta['fence'], state='started', outcome=None,
                       cleanup_complete=False)
        restarted = self.launcher(engine)
        record = LauncherJournal(self.journal_directory).get(meta['job_id'], meta['fence'])
        self.assertEqual(('finished', True, 'cancelled'),
                         (record.state, record.cleanup_complete, record.outcome))
        self.assertIn(ENGINE_ID, engine.removed)
        status, frame = self.control(restarted, meta, attempt.handle)
        self.assertEqual(('finished', True), (status['state'], status['cleanup_complete']))
        self.assertIsNone(frame)

    def test_ac_03_created_record_without_engine_id_is_found_by_exact_labels(self):
        engine = FakeEngine()
        launcher = self.launcher(engine)
        value = context()
        raw = b'synthetic,raw\n'
        meta = metadata(value, raw)
        record = Record(instance_id=INSTANCE, peer='worker', credential_epoch='1',
                        realm_digest=REALM, job_id=meta['job_id'], member_id=meta['member_id'],
                        fence=meta['fence'], nonce_digest=sha256(meta['nonce'].encode()),
                        handle_digest='1' * 64, engine_id=None, image_digest=IMAGE,
                        deadline=meta['deadline'], state='created', outcome=None,
                        cleanup_complete=False)
        LauncherJournal(self.journal_directory).create(record)
        engine.found = (ENGINE_ID,)
        self.launcher(engine)
        self.assertIn(ENGINE_ID, engine.removed)
        self.assertEqual('finished', LauncherJournal(self.journal_directory).get(
            meta['job_id'], meta['fence']).state)

    def test_ac_06_bounded_outcomes_are_classified_before_any_frame_is_decoded(self):
        for outcome in ('output_limit', 'resource_exit', 'wall_limit', 'child_error'):
            with self.subTest(outcome=outcome):
                engine = FakeEngine(outcome=outcome)
                launcher = self.launcher(engine)
                meta, attempt = self.start(launcher, engine)
                self.assertEqual(('failed', outcome),
                                 (attempt.record.state, attempt.record.outcome))

    def test_ac_07_unreachable_docker_never_proves_absence(self):
        from kurafolio.ingestion.launcher_engine import EngineError

        class Unreachable(FakeEngine):
            failed = False

            def remove(self, engine_id):
                self.failed = True
                return False

            def inspect(self, engine_id):
                if self.failed:
                    raise EngineError('import_runner_unavailable')
                return super().inspect(engine_id)

        engine = Unreachable()
        launcher = self.launcher(engine)
        meta, attempt = self.start(launcher, engine)
        with self.assertRaises(EngineError):
            self.control(launcher, meta, attempt.handle, 'cancel')
        record = LauncherJournal(self.journal_directory).get(meta['job_id'], meta['fence'])
        self.assertFalse(record.cleanup_complete)
        self.assertNotEqual('finished', record.state)

    def test_ac_03_a_refused_child_frame_is_frame_rejected(self):
        engine = FakeEngine(frame=b'not-a-frame')
        launcher = self.launcher(engine)
        meta, attempt = self.start(launcher, engine)
        self.assertEqual(('failed', 'frame_rejected'),
                         (attempt.record.state, attempt.record.outcome))

    def test_ac_02_unknown_or_non_matching_profiles_create_nothing(self):
        engine = FakeEngine()
        launcher = self.launcher(engine)
        value = context()
        raw = b'synthetic,raw\n'
        good = metadata(value, raw)
        bad = validate({**good, 'wrapper_profile_digest': '0' * 64}, 'LaunchStart')
        with self.assertRaises(IngestionError) as refused:
            launcher.start(bad, value, raw)
        self.assertEqual('import_evidence_unsupported', refused.exception.code)
        self.assertEqual([], engine.created)

    def test_ac_08_other_credentials_or_handles_are_refused(self):
        engine = FakeEngine()
        launcher = self.launcher(engine)
        meta, attempt = self.start(launcher, engine)
        for changes, code in (({'credential_epoch': '2'}, 'authentication_required'),
                              ({'realm_digest': 'b' * 64}, 'authentication_required'),
                              ({'handle': 'c' * 64}, 'authentication_required')):
            with self.subTest(changes=changes):
                with self.assertRaises(IngestionError) as refused:
                    self.control(launcher, meta, None if 'handle' in changes else attempt.handle,
                                 **changes)
                self.assertEqual(code, refused.exception.code)

    def test_ac_08_private_endpoint_refuses_wrong_peers_and_bad_frames(self):
        directory = Path(self.directory.name) / 'peers'
        directory.mkdir(mode=0o700)
        peers = make_peers(directory, ['worker', 'api', 'launcher'])
        ca, cert, key, _ = peers['launcher']
        server = PeerTLS(ca, cert, key, peers['worker'][3], INSTANCE, 'worker')
        config = Config()
        config.journal_directory = self.journal_directory
        config.profiles_file = self.profiles
        config.server_tls = server
        config.bind_port = 0
        engine = FakeEngine()
        launcher = Launcher(config, engine)
        address = launcher.start_server()
        self.addCleanup(launcher.stop)
        port = address[1]

        def client(role):
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(peers[role][0]))
            context.check_hostname = False
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
            context.load_cert_chain(str(peers[role][1]), str(peers[role][2]))
            return http.client.HTTPSConnection('127.0.0.1', port, context=context, timeout=5)

        def post(role, path, body):
            connection = client(role)
            try:
                connection.request('POST', path, body=body,
                                   headers={'Content-Type': 'application/octet-stream',
                                            'Content-Length': str(len(body))})
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        value = context()
        raw = b'synthetic,raw\n'
        meta = metadata(value, raw)
        engine.frame = child_frame(meta)
        status, body = post('worker', '/internal/v1/jobs', pack_input(meta, value, raw, schema='LaunchStart'))
        self.assertEqual(200, status)
        status_value = json.loads(body)
        self.assertEqual((meta['job_id'], meta['fence']), (status_value['job_id'], status_value['fence']))
        with self.assertRaises((OSError, ssl.SSLError, ConnectionError)):
            post('api', '/internal/v1/jobs', pack_input(meta, value, raw, schema='LaunchStart'))
        status, body = post('worker', '/internal/v1/jobs', b'\x00\x00\x00\x01{')
        self.assertEqual((422, {'code': 'import_invalid'}), (status, json.loads(body)))
        self.assertEqual(1, len(engine.created))
        control = {'version': 1, 'operation': 'forget', 'instance_id': INSTANCE,
                   'realm_digest': REALM, 'credential_epoch': '1', 'job_id': meta['job_id'],
                   'member_id': meta['member_id'], 'fence': meta['fence'],
                   'handle': 'f' * 64, 'include_result': False}
        status, body = post('worker', '/internal/v1/control', encode(control))
        self.assertEqual((401, {'code': 'authentication_required'}), (status, json.loads(body)))
        control['handle'] = status_value['handle']
        status, body = post('worker', '/internal/v1/control', encode(control))
        self.assertEqual((409, {'code': 'import_conflict'}), (status, json.loads(body)))

    def test_ac_08_module_entry_points_call_main(self):
        """AC-IMP-007F-08: both services reach their own CLI entry point."""
        from kurafolio.ingestion import launcher as launcher_module
        from kurafolio.ingestion import worker as worker_module
        with self.assertRaises(SystemExit) as launcher_exit:
            launcher_module.main(['--help'])
        self.assertEqual(0, launcher_exit.exception.code)
        with self.assertRaises(SystemExit) as worker_exit:
            worker_module.main(['--help'])
        self.assertEqual(0, worker_exit.exception.code)

    def test_ac_02_child_refuses_unreviewed_frames(self):
        from kurafolio.ingestion.runner_child import run as child_run
        from kurafolio.ingestion.runner_client import pack_input
        with self.assertRaises(IngestionError):
            child_run(b'not-a-frame')
        value = context()
        raw = b'synthetic,raw\n'
        meta = metadata(value, raw)
        with self.assertRaises(IngestionError) as refused:
            child_run(pack_input(meta, value, raw, schema='LaunchStart'))
        self.assertEqual('import_evidence_unsupported', refused.exception.code)

    def test_ac_01_a_second_start_with_another_nonce_conflicts_and_creates_once(self):
        engine = FakeEngine()
        launcher = self.launcher(engine)
        value = context()
        raw = b'synthetic,raw\n'
        meta = metadata(value, raw)
        engine.frame = child_frame(meta)
        launcher.start(meta, value, raw)
        with self.assertRaises(IngestionError) as refused:
            launcher.start(validate({**meta, 'nonce': 'd' * 64}, 'LaunchStart'), value, raw)
        self.assertEqual('import_conflict', refused.exception.code)
        self.assertEqual(1, len(engine.created))


if __name__ == '__main__':
    unittest.main()
