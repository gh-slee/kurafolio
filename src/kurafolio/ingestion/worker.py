"""The dedicated ingestion worker: fenced normalize and cleanup loops.

Raw bytes live only in this process. The worker talks to PostgreSQL through the
restricted worker functions and to one authenticated launcher, never to Docker.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import secrets
import signal
import threading
import time
import uuid

from ..persistence.context import Database
from . import discovery
from .codec import decode, digest, encode, sha256, validate
from .contracts import MAX_CONTEXT, MAX_RAW, IngestionError
from .handoff_server import HandoffServer
from .runner_client import unpack_input, unpack_result
from .worker_config import ConfigError, load, read_profiles_file
from .worker_journal import JournalError, WorkerJournal
from .worker_sql import CALLS, WorkerCallError, WorkerSQL

LOG = logging.getLogger('kurafolio.ingestion.worker')
UTC = timezone.utc
REQUEST_NAMESPACE = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'kurafolio.ingestion.worker.request.v1'))
RAW_SLACK = timedelta(seconds=5)
MAX_ACTIVE = 4


def _now():
    return datetime.now(UTC)


def _instant(value):
    return validate({'tag': 'instant', 'token': value.astimezone(UTC).isoformat(timespec='seconds'),
                     'zone': None, 'fractional_digits': 0}, 'Instant')


def _time(value):
    return datetime.fromisoformat(value['token'].replace('Z', '+00:00'))


class RawHold:
    """In-memory ownership of one attempt's raw and context bytes."""

    def __init__(self, raw, context, deadline):
        self.raw = bytearray(raw)
        self.context = bytearray(context)
        self.deadline = deadline
        self._dropped = False
        self._lock = threading.Lock()

    def expired(self):
        return _now() >= self.deadline

    def drop(self):
        with self._lock:
            if self._dropped:
                return
            self._dropped = True
            for buffer in (self.raw, self.context):
                for index in range(len(buffer)):
                    buffer[index] = 0
                buffer.clear()


@dataclass(slots=True)
class Attempt:
    job_id: str
    set_id: str
    member_id: str
    fence: str
    token: str
    expires_at: datetime
    hold: RawHold | None = None
    handle: str | None = None
    lost: threading.Event | None = None
    next_renew: datetime | None = None

    def mark_lost(self):
        self.lost.set()


class LauncherClient:
    """The worker-facing launcher protocol; implemented over mTLS in stage 2."""

    def start(self, metadata, context, raw):
        raise NotImplementedError

    def control(self, request):
        """Return (LaunchStatus, frame or None)."""
        raise NotImplementedError


class LeaseKeeper:
    """Renews normalize leases; never past their deadline and never after an error."""

    def __init__(self, sql, attempts, *, realm_digest, credential_epoch, clock=_now, sleep=time.sleep,
                 wait=None):
        self._sql = sql
        self._attempts = attempts
        self._realm_digest = realm_digest
        self._credential_epoch = credential_epoch
        self._clock = clock
        self._sleep = sleep
        self._wait = wait if wait is not None else self._stop.wait
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name='lease-keeper', daemon=True)
        self._thread.start()

    def stop(self, timeout=5):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self):
        while not self._stop.is_set():
            now = self._clock()
            for attempt in list(self._attempts.values()):
                if attempt.lost.is_set() or attempt.member_id is None:
                    continue
                if now >= attempt.expires_at - RAW_SLACK:
                    attempt.mark_lost()
                    LOG.warning('lease_expired job_id=%s fence=%s', attempt.job_id, attempt.fence)
                    continue
                if attempt.next_renew is not None and now < attempt.next_renew:
                    continue
                request = {'version': 1, 'realm_digest': self._realm_digest,
                           'credential_epoch': self._credential_epoch,
                           'job_id': attempt.job_id, 'set_id': attempt.set_id,
                           'member_id': attempt.member_id, 'work_kind': 'normalize',
                           'fence': attempt.fence, 'request_id': str(uuid.uuid4())}
                try:
                    ack = self._sql.call('renew_member_v1', request, token=attempt.token)
                except WorkerCallError as error:
                    attempt.mark_lost()
                    attempt.next_renew = None
                    LOG.warning('lease_lost job_id=%s fence=%s code=%s', attempt.job_id,
                                attempt.fence, error.code)
                    continue
                expires = _time(ack['expires_at'])
                attempt.expires_at = expires
                attempt.next_renew = min(now + timedelta(seconds=10), expires - RAW_SLACK)
            if self._wait(0.25):
                return


class ImportWorker:
    def __init__(self, config, *, sql=None, launcher=None, journal=None, clock=_now, sleep=time.sleep,
                 profiles=None, descriptors=None):
        self.config = config
        self.clock = clock
        self.sleep = sleep
        self.journal = journal if journal is not None else WorkerJournal(config.journal_directory)
        self.database = Database(config.database, schema_mode='sources') if sql is None else None
        self.sql = sql if sql is not None else WorkerSQL(self.database, config.worker_id)
        self.launcher = launcher
        self._attempts = {}
        self._lock = threading.Lock()
        self._slots = threading.Semaphore(MAX_ACTIVE)
        self._stop = threading.Event()
        self._executor = None
        self._server = None
        self._keeper = None
        self._cleanup = None
        if profiles is not None:
            self._profiles = list(profiles)
        else:
            self._profiles = read_profiles_file(config.profiles_file)
        if descriptors is not None:
            self._descriptors = tuple(descriptors)
        else:
            from ..data_sources import contract_v1 as source
            from ..data_sources import catalog_v1
            catalog = catalog_v1.read_catalog_file(config.catalog_file)
            self._descriptors = tuple((source.installation_id(desc),
                                       source.canonical(source.primitive(desc)))
                                      for desc in catalog.installations)

    # lifecycle ---------------------------------------------------------------

    def start(self):
        from concurrent.futures import ThreadPoolExecutor
        self._executor = ThreadPoolExecutor(max_workers=MAX_ACTIVE, thread_name_prefix='normalize')
        self._keeper = LeaseKeeper(self.sql, self._attempts,
                                   realm_digest=self.config.realm_digest,
                                   credential_epoch=self.config.credential_epoch)
        self._keeper.start()
        self._server = HandoffServer(self.config.api_tls, self.config.bind_address,
                                     self.config.bind_port, self.handoff)
        self._server.start()
        self._cleanup = threading.Thread(target=self._cleanup_loop, name='cleanup', daemon=True)
        self._cleanup.start()
        LOG.info('worker_started instance=%s worker=%s', self.config.instance_id, self.config.worker_id)

    def stop(self):
        self._stop.set()
        if self._server is not None:
            self._server.stop()
            self._server = None
        if self._keeper is not None:
            self._keeper.stop()
            self._keeper = None
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        for attempt in list(self._attempts.values()):
            self._cancel_launch(attempt)
            if attempt.hold is not None:
                attempt.hold.drop()
        if self._cleanup is not None:
            self._cleanup.join(timeout=5)
            self._cleanup = None
        if self.database is not None:
            self.database.close()
        LOG.info('worker_stopped')

    # handoff ----------------------------------------------------------------

    def handoff(self, metadata, context, raw):
        if self._stop.is_set():
            raise IngestionError('import_runner_unavailable')
        if _now() >= _time(metadata['raw_deadline']) or _now() >= _time(metadata['expires_at']):
            return self._ack(metadata, 'reupload_required', False, None)
        key = (metadata['job_id'], metadata['fence'])
        with self._lock:
            current = self._attempts.get(key)
        if current is not None:
            return self._ack(metadata, 'already_owned', True, None)
        context_digest = sha256(context)
        raw_digest = sha256(raw)
        if context_digest != metadata['context_sha256'] or raw_digest != metadata['raw_sha256']:
            raise IngestionError('import_invalid')
        if not self._slots.acquire(blocking=False):
            raise IngestionError('import_busy')
        created = False
        try:
            created = self.journal.record(metadata['set_id'], metadata['job_id'],
                                          metadata['member_id'], metadata['fence'])
            request = {'version': 1, 'realm_digest': metadata['realm_digest'],
                       'credential_epoch': self.config.credential_epoch,
                       'job_id': metadata['job_id'], 'set_id': metadata['set_id'],
                       'member_id': metadata['member_id'], 'work_kind': 'normalize',
                       'fence': metadata['fence'],
                       'request_id': str(uuid.uuid5(uuid.UUID(REQUEST_NAMESPACE),
                                                    metadata['job_id'] + ':' + metadata['fence'])),
                       'raw_digest': raw_digest, 'context_digest': context_digest}
            try:
                ack = self.sql.call('claim_member_v1', request, token=metadata['handoff_token'])
            except WorkerCallError as error:
                if error.code == 'import_reupload_required':
                    if created:
                        self.journal.remove(metadata['job_id'], metadata['fence'])
                    return self._ack(metadata, 'reupload_required', False, None)
                raise IngestionError(error.code) from None
            if ack['outcome'] == 'already_claimed':
                # A restarted worker may not reuse the dead process's bytes or launch.
                raise IngestionError('import_runner_unavailable')
            if ack['outcome'] != 'claimed':
                raise IngestionError('import_runner_unavailable')
            hold = RawHold(raw, context, _time(metadata['raw_deadline']))
            attempt = Attempt(job_id=metadata['job_id'], set_id=metadata['set_id'],
                              member_id=metadata['member_id'], fence=metadata['fence'],
                              token=metadata['handoff_token'], expires_at=_time(ack['expires_at']),
                              hold=hold, lost=threading.Event(), next_renew=_now())
            with self._lock:
                self._attempts[key] = attempt
            self._executor.submit(self._normalize, attempt)
            return self._ack(metadata, 'owned', True, None)
        except WorkerCallError:
            if created:
                self.journal.remove(metadata['job_id'], metadata['fence'])
            self._slots.release()
            raise
        except (JournalError, IngestionError):
            self._slots.release()
            raise
        except Exception:
            self._slots.release()
            raise

    @staticmethod
    def _ack(metadata, outcome, owned, stage_digest):
        return validate({'version': 1, 'job_id': metadata['job_id'], 'member_id': metadata['member_id'],
                         'fence': metadata['fence'], 'input_owned': owned, 'outcome': outcome,
                         'stage_digest': stage_digest}, 'HandoffAck')

    # normalize --------------------------------------------------------------

    def _normalize(self, attempt):
        hold = attempt.hold
        outcome, code, proof = 'reupload_required', 'import_runner_unavailable', None
        try:
            try:
                context_value = self._context(attempt)
            except IngestionError:
                return
            try:
                status = self.launcher.start(self._start_metadata(attempt, context_value),
                                             bytes(hold.context), bytes(hold.raw))
                if attempt.lost.is_set():
                    self._cancel_launch(attempt)
                    return
                handle = validate(status, 'LaunchStatus')['handle']
                self.journal.set_handle(attempt.job_id, attempt.fence, handle)
                attempt.handle = handle
                outcome, code = self._run_child(attempt, context_value, hold)
            except (WorkerCallError, IngestionError) as error:
                if getattr(error, 'code', None) == 'import_stale':
                    self._cancel_launch(attempt)
                    return
                outcome, code = 'reupload_required', 'import_runner_unavailable'
            except Exception:
                LOG.exception('normalize_failed job_id=%s fence=%s', attempt.job_id, attempt.fence)
                outcome, code = 'reupload_required', 'import_runner_unavailable'
            finally:
                if hold is not None:
                    hold.drop()
            if attempt.lost.is_set():
                self._cancel_launch(attempt)
                return
            proof = self._proof_wait(attempt, hold.deadline if hold else _now())
            if attempt.lost.is_set():
                return
            proofs = [proof] if proof is not None else []
            request = {'version': 1, 'realm_digest': self.config.realm_digest,
                       'credential_epoch': self.config.credential_epoch,
                       'job_id': attempt.job_id, 'set_id': attempt.set_id,
                       'member_id': attempt.member_id, 'work_kind': 'normalize',
                       'fence': attempt.fence, 'request_id': str(uuid.uuid4()),
                       'outcome': outcome, 'error_code': code, 'cleanup_proofs': proofs}
            ack = self.sql.call('finish_member_v1', request, token=attempt.token)
            if proof is not None and proof['state'] in {'absent', 'not_created'}:
                self.journal.remove(attempt.job_id, attempt.fence)
                self._forget(attempt)
            LOG.info('normalize_finished job_id=%s fence=%s state=%s cleanup=%s',
                     attempt.job_id, attempt.fence, ack['state'], ack['cleanup_complete'])
        except WorkerCallError as error:
            LOG.warning('normalize_refused job_id=%s fence=%s code=%s',
                        attempt.job_id, attempt.fence, error.code)
            self._cancel_launch(attempt)
        except JournalError as error:
            LOG.error('journal_refused job_id=%s fence=%s code=%s', attempt.job_id, attempt.fence, error.code)
            self._cancel_launch(attempt)
        finally:
            if attempt.hold is not None:
                attempt.hold.drop()
            with self._lock:
                self._attempts.pop((attempt.job_id, attempt.fence), None)
            self._slots.release()

    def _context(self, attempt):
        from ..data_sources.contract_v1 import load_json
        primitive = load_json(bytes(attempt.hold.context), limit=MAX_CONTEXT)
        schema = {'parser_v2': 'ParserChildContext',
                  'native_discovery_v1': 'NativeChildContext'}[primitive['payload_kind']]
        value = decode(bytes(attempt.hold.context), schema, limit=MAX_CONTEXT)
        for name in ('job_id', 'member_id', 'fence'):
            if value[name] != getattr(attempt, name):
                raise IngestionError('import_stale')
        return {'primitive': primitive, **value}

    def _start_metadata(self, attempt, context_value):
        raw = attempt.hold.raw
        context = attempt.hold.context
        return {'version': 1, 'operation': 'start', 'job_id': attempt.job_id,
                'member_id': attempt.member_id, 'fence': attempt.fence,
                'instance_id': self.config.instance_id, 'realm_digest': self.config.realm_digest,
                'credential_epoch': self.config.credential_epoch,
                'installation_id': context_value['installation_id'],
                'image_digest': context_value['image_digest'],
                'wrapper_profile_digest': context_value['wrapper_profile_digest'],
                'format_version': context_value['format_version'],
                'context_sha256': sha256(bytes(context)), 'context_bytes': len(context),
                'raw_sha256': sha256(bytes(raw)), 'raw_bytes': len(raw),
                'deadline': _instant(attempt.hold.deadline),
                'nonce': secrets.token_hex(32)}

    def _run_child(self, attempt, context_value, hold):
        expected = {'job_id': attempt.job_id, 'member_id': attempt.member_id,
                    'fence': attempt.fence,
                    'installation_id': context_value['installation_id'],
                    'image_digest': context_value['image_digest'],
                    'wrapper_profile_digest': context_value['wrapper_profile_digest'],
                    'raw_sha256': sha256(bytes(hold.raw)),
                    'context_sha256': sha256(bytes(hold.context)),
                    'payload_kind': context_value['payload_kind']}
        status, frame = None, None
        reason = None
        while True:
            if attempt.lost.is_set():
                raise WorkerCallError('import_stale')
            if hold.expired():
                reason = 'deadline'
                break
            status, _ = self.launcher.control(self._control(attempt, 'status', False))
            self._check_status(attempt, status)
            if status['state'] == 'result_ready' and status['outcome'] == 'ok':
                ready, frame = self.launcher.control(self._control(attempt, 'status', True))
                if ready is not None:
                    self._check_status(attempt, ready)
                    status = ready
                break
            if status['state'] == 'failed' or status['outcome'] not in (None, 'ok'):
                reason = status['outcome'] or 'child_error'
                break
            self.sleep(0.2)
        if reason == 'deadline':
            return 'reupload_required', 'import_reupload_required'
        if frame is None and reason is None and status['outcome'] == 'ok':
            raise IngestionError('import_runner_unavailable')
        if reason is not None:
            return self._outcome(reason)
        try:
            expected = {**expected, 'handle': status['handle']}
            header, payload = unpack_result(frame, expected, child=False)
        except IngestionError as error:
            return ('rejected', 'import_limit') if error.code == 'import_limit' else (
                'rejected', 'import_invalid')
        if header['outcome'] != 'ok':
            return 'rejected', 'import_invalid'
        try:
            minimal = self._admit(context_value, payload, hold)
        except IngestionError as error:
            return 'rejected', error.code if error.code != 'import_limit' else 'import_limit'
        request = {'version': 1, 'realm_digest': self.config.realm_digest,
                   'credential_epoch': self.config.credential_epoch,
                   'job_id': attempt.job_id, 'set_id': attempt.set_id,
                   'member_id': attempt.member_id, 'work_kind': 'normalize',
                   'fence': attempt.fence, 'request_id': str(uuid.uuid4()),
                   'stage_digest': sha256(minimal), 'raw_digest': sha256(bytes(hold.raw)),
                   'discovery_digest': sha256(payload), 'payload_bytes': len(minimal)}
        try:
            self.sql.call('admit_stage_v1', request, payload=minimal, token=attempt.token)
        finally:
            del minimal
            hold.drop()
        return 'stage_admitted', None

    def _admit(self, context_value, payload, hold):
        profile = [item for item in self._profiles
                   if item['installation_id'] == context_value['installation_id']
                   and item['profile_digest'] == context_value['wrapper_profile_digest']]
        descriptor = [item for item in self._descriptors
                      if item[0] == context_value['installation_id']]
        if len(profile) != 1 or len(descriptor) != 1:
            raise IngestionError('import_evidence_unsupported')
        profile, (_, descriptor_bytes) = profile[0], descriptor[0]
        raw = bytes(hold.raw)
        context = bytes(hold.context)
        if profile['projection'] == 'parser2-minimal-v1':
            return discovery.admit_parser2(raw, payload, context, descriptor_bytes, profile)
        return discovery.admit_native(raw, payload, context, descriptor_bytes, profile)

    @staticmethod
    def _outcome(reason):
        return {'output_limit': ('rejected', 'import_limit'),
                'resource_exit': ('rejected', 'import_limit'),
                'wall_limit': ('rejected', 'import_limit'),
                'child_error': ('rejected', 'import_invalid'),
                'frame_rejected': ('rejected', 'import_invalid'),
                'context_rejected': ('rejected', 'import_stale'),
                'cancelled': ('reupload_required', 'import_runner_unavailable'),
                'cleanup_failed': ('reupload_required', 'import_runner_unavailable')}.get(
                    reason, ('reupload_required', 'import_runner_unavailable'))

    def _control(self, attempt, operation, include_result, handle=None):
        return {'version': 1, 'operation': operation, 'instance_id': self.config.instance_id,
                'realm_digest': self.config.realm_digest,
                'credential_epoch': self.config.credential_epoch,
                'job_id': attempt.job_id, 'member_id': attempt.member_id,
                'fence': attempt.fence, 'handle': handle or attempt.handle,
                'include_result': include_result}

    def _check_status(self, attempt, status):
        if (status['job_id'] != attempt.job_id or status['fence'] != attempt.fence
                or status['handle'] != attempt.handle):
            raise IngestionError('import_invalid')

    def _cancel_launch(self, attempt):
        if attempt.handle is None or self.launcher is None:
            return
        try:
            status, _ = self.launcher.control(self._control(attempt, 'cancel', False))
            self._check_status(attempt, status)
        except Exception:
            LOG.warning('cancel_failed job_id=%s fence=%s', attempt.job_id, attempt.fence)

    def _forget(self, attempt):
        """Drop a launcher record only after its own proof said the child was gone."""
        if attempt.handle is None or self.launcher is None:
            return
        try:
            status, _ = self.launcher.control(self._control(attempt, 'forget', False))
            self._check_status(attempt, status)
        except Exception:
            LOG.warning('forget_failed job_id=%s fence=%s', attempt.job_id, attempt.fence)

    def _proof_wait(self, attempt, deadline):
        if attempt.handle is None or self.launcher is None:
            return None
        end = min(deadline - RAW_SLACK, _now() + timedelta(seconds=60))
        status = None
        try:
            status, _ = self.launcher.control(self._control(attempt, 'cancel', False))
            self._check_status(attempt, status)
            while _now() < end:
                if status['state'] == 'finished' and status['cleanup_complete']:
                    return self._proof(attempt, 'absent', status)
                if status['state'] == 'failed' and status['cleanup_complete']:
                    return self._proof(attempt, 'not_created', status)
                self.sleep(0.5)
                status, _ = self.launcher.control(self._control(attempt, 'status', False))
                self._check_status(attempt, status)
        except Exception:
            LOG.warning('proof_wait_failed job_id=%s fence=%s', attempt.job_id, attempt.fence)
        if status is None:
            return None
        if status['cleanup_complete']:
            return self._proof(attempt, 'absent', status)
        if status['state'] == 'failed':
            return self._proof(attempt, 'failed', status)
        return self._proof(attempt, 'pending', status)

    def _proof(self, attempt, state, status):
        proof = {'job_id': attempt.job_id, 'fence': attempt.fence, 'state': state,
                 'launcher_instance_id': self.config.instance_id,
                 'proof_digest': digest(status), 'checked_at': _instant(_now())}
        try:
            return validate(proof, 'CleanupProof')
        except IngestionError:
            return None

    # cleanup ----------------------------------------------------------------

    def _cleanup_loop(self):
        while not self._stop.is_set():
            try:
                self._cleanup_once()
            except WorkerCallError as error:
                LOG.warning('cleanup_refused code=%s', error.code)
            except Exception:
                LOG.exception('cleanup_failed')
                if self._stop.wait(2):
                    return
                continue
            if self._stop.wait(1 + secrets.randbelow(1000) / 1000):
                return

    def _cleanup_once(self):
        token = secrets.token_hex(32)
        request = {'version': 1, 'realm_digest': self.config.realm_digest,
                   'credential_epoch': self.config.credential_epoch, 'work_kind': 'cleanup',
                   'claim_request_id': str(uuid.uuid4())}
        result = self.sql.call('claim_plan_v1', request, token=token)
        if result['outcome'] == 'no_work':
            return
        lease = result['lease']
        if lease is None:
            return
        proofs = []
        probes = {}
        for record in self.journal.for_set(lease['set_id'])[:12]:
            if record.handle is None:
                continue
            probe = Attempt(job_id=record.job_id, set_id=record.set_id, member_id=record.member_id,
                            fence=record.fence, token=token, expires_at=_now(),
                            handle=record.handle, lost=threading.Event())
            probes[(record.job_id, record.fence)] = (probe, None)
            try:
                status, _ = self.launcher.control(self._control(probe, 'status', False))
            except Exception:
                continue
            if (status['job_id'] != record.job_id or status['fence'] != record.fence
                    or status['handle'] != record.handle):
                continue
            if status['state'] == 'finished' and status['cleanup_complete']:
                state = 'absent'
            elif status['state'] == 'failed' and status['cleanup_complete']:
                state = 'not_created'
            elif status['state'] == 'failed':
                state = 'failed'
            else:
                state = 'pending'
            proof = self._proof(probe, state, status)
            if proof is not None:
                proofs.append(proof)
                probes[(record.job_id, record.fence)] = (probe, state)
        cleanup = {'version': 1, 'realm_digest': self.config.realm_digest,
                   'credential_epoch': self.config.credential_epoch,
                   'job_id': lease['job_id'], 'set_id': lease['set_id'], 'member_id': None,
                   'work_kind': 'cleanup', 'fence': lease['fence'],
                   'request_id': str(uuid.uuid4()), 'cleanup_proofs': proofs}
        ack = self.sql.call('cleanup_set_v1', cleanup, token=token)
        if ack['outcome'] in {'purged', 'already_purged'}:
            for record in self.journal.for_set(lease['set_id']):
                probe, state = probes.get((record.job_id, record.fence), (None, None))
                if probe is not None and state in {'absent', 'not_created'}:
                    self._forget(probe)
                self.journal.remove(record.job_id, record.fence)
        LOG.info('cleanup_done set_id=%s outcome=%s released=%s', lease['set_id'],
                 ack['outcome'], ack['quota_released'])


def main(argv=None):
    parser = argparse.ArgumentParser(prog='kurafolio.ingestion.worker')
    commands = parser.add_subparsers(dest='command', required=True)
    serve = commands.add_parser('serve')
    serve.add_argument('--config', required=True)
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    try:
        config = load(arguments.config)
        worker = ImportWorker(config)
    except (ConfigError, JournalError) as error:
        LOG.error('worker_refused code=%s', error.code)
        return 2
    from .launcher_client import HttpLauncherClient
    worker.launcher = HttpLauncherClient(config)
    stopped = threading.Event()

    def stop(signum, frame):
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker.start()
    try:
        stopped.wait()
    finally:
        worker.stop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
