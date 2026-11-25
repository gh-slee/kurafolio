"""The trusted launcher: one worker peer, fixed child profile, no prepare work.

It creates and starts only the reviewed image at the profile's image digest,
keeps raw and result bytes in memory, and journals ownership as digests. A
restart removes only engine IDs it owns, then reports the exact removal state so
the worker can ask for a cleanup proof.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import stat
import threading
import time

from .codec import digest, encode, sha256, validate
from .contracts import (ERROR_STATUS, IngestionError, MAX_CONTEXT, MAX_CONTROL,
                        MAX_MINIMAL, MAX_RAW)
from .launcher_engine import ENTRY, EngineError, PROFILE, DockerEngine
from .launcher_journal import JournalError, LauncherJournal, Record
from .runner_client import PeerTLS, pack_input, pack_result, unpack_input, unpack_result
from .worker_config import ConfigError, read_profiles_file

LOG = logging.getLogger('kurafolio.launcher')
TOTAL_SECONDS = 30
IDLE_SECONDS = 5
CONTROL_BODY = 4 + MAX_CONTROL
JOB_BODY = 4 + MAX_CONTROL + MAX_CONTEXT + MAX_RAW
_CONFIG_KEYS = {'version', 'instance_id', 'credential_epoch', 'bind_address', 'bind_port',
                'journal_directory', 'server_tls', 'image_repository', 'profiles_file'}
_TLS_KEYS = {'ca_file', 'cert_file', 'key_file', 'peer_dns'}
_REPOSITORY = re.compile(r'^[a-z0-9][a-z0-9]{0,63}(?:[._/-][a-z0-9._-]{0,63})*$')
_REFUSED_HEADERS = ('Transfer-Encoding', 'Content-Encoding', 'Expect')


def _regular(path, *, secret):
    try:
        info = os.lstat(path)
    except OSError:
        raise ConfigError() from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise ConfigError()
    if secret and stat.S_IMODE(info.st_mode) & 0o077:
        raise ConfigError()
    return info


@dataclass(frozen=True, slots=True)
class LauncherConfig:
    instance_id: str
    credential_epoch: str
    bind_address: str
    bind_port: int
    journal_directory: Path
    server_tls: PeerTLS
    image_repository: str
    profiles_file: Path


def load_config(path):
    _regular(path, secret=True)
    try:
        descriptor = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            raw = os.read(descriptor, 65537)
        finally:
            os.close(descriptor)
        if not 0 < len(raw) <= 65536:
            raise ConfigError()
        value = json.loads(raw)
    except ConfigError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise ConfigError() from None
    if type(value) is not dict or set(value) != _CONFIG_KEYS or value.get('version') != 1:
        raise ConfigError()
    instance_id = value['instance_id']
    if type(instance_id) is not str or validate(instance_id, 'UUID') is None:
        raise ConfigError()
    epoch = value['credential_epoch']
    if type(epoch) is not str or re.fullmatch(r'(0|[1-9][0-9]{0,18})', epoch) is None:
        raise ConfigError()
    address, port = value['bind_address'], value['bind_port']
    if (type(address) is not str or re.fullmatch(r'[A-Za-z0-9.:-]{1,64}', address) is None
            or type(port) is not int or not 1 <= port <= 65535):
        raise ConfigError()
    repository = value['image_repository']
    if type(repository) is not str or _REPOSITORY.fullmatch(repository) is None:
        raise ConfigError()
    journal = Path(value['journal_directory'])
    profile_path = Path(value['profiles_file'])
    for item, secret in ((profile_path, False),):
        _regular(item, secret=secret)
    group = value['server_tls']
    if type(group) is not dict or set(group) != _TLS_KEYS:
        raise ConfigError()
    paths = {}
    for key in ('ca_file', 'cert_file', 'key_file'):
        if type(group[key]) is not str or not group[key]:
            raise ConfigError()
        paths[key] = Path(group[key])
    _regular(paths['ca_file'], secret=False)
    _regular(paths['cert_file'], secret=False)
    _regular(paths['key_file'], secret=True)
    dns = group['peer_dns']
    if type(dns) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', dns) is None:
        raise ConfigError()
    return LauncherConfig(instance_id=instance_id, credential_epoch=epoch,
                          bind_address=address, bind_port=port, journal_directory=journal,
                          server_tls=PeerTLS(paths['ca_file'], paths['cert_file'],
                                             paths['key_file'], dns, instance_id, 'worker'),
                          image_repository=repository, profiles_file=profile_path)


@dataclass(slots=True)
class Attempt:
    record: Record
    handle: str
    nonce: str
    context_sha256: str
    raw_sha256: str
    payload_kind: str
    installation_id: str
    wrapper_profile_digest: str
    frame: bytes | None = None
    payload: bytes | None = None
    result: bytes | None = None
    cancelled: bool = False


def _status(attempt, *, state=None, outcome=None, cleanup_complete=None):
    return validate({'version': 1, 'job_id': attempt.record.job_id,
                     'fence': attempt.record.fence, 'handle': attempt.handle,
                     'state': state or attempt.record.state,
                     'outcome': outcome if outcome is not None else attempt.record.outcome,
                     'cleanup_complete': (attempt.record.cleanup_complete
                                          if cleanup_complete is None else cleanup_complete),
                     'payload_sha256': sha256(attempt.payload) if attempt.payload else None},
                    'LaunchStatus')


class Launcher:
    def __init__(self, config, engine=None):
        self.config = config
        self.engine = engine or DockerEngine()
        self.journal = LauncherJournal(config.journal_directory)
        self.profiles = read_profiles_file(config.profiles_file)
        self._lock = threading.RLock()
        self._attempts = {}
        self._server = None
        self._reference = {profile['image_digest']: config.image_repository + '@sha256:'
                           + profile['image_digest'] for profile in self.profiles}
        for reference in set(self._reference.values()):
            image_id = self.engine.image(reference)
            if image_id.removeprefix('sha256:') != reference.rsplit('@sha256:', 1)[1]:
                raise RuntimeError('image digest mismatch')
        self._reconcile()

    # ---------------------------------------------------------------- records

    def _record_for(self, metadata, handle, nonce):
        return Record(instance_id=self.config.instance_id, peer='worker',
                      credential_epoch=metadata['credential_epoch'],
                      realm_digest=metadata['realm_digest'], job_id=metadata['job_id'],
                      member_id=metadata['member_id'], fence=metadata['fence'],
                      nonce_digest=sha256(nonce.encode()), handle_digest=sha256(handle.encode()),
                      engine_id=None, image_digest=metadata['image_digest'],
                      deadline=metadata['deadline'], state='created', outcome=None,
                      cleanup_complete=False)

    def _reconcile(self):
        for record in self.journal.records():
            if record.state == 'finished':
                continue
            engine_id = record.engine_id
            if engine_id is None:
                found = list(self.engine.find(record.instance_id, record.nonce_digest))
                engine_id = found[0] if len(found) == 1 else None
            removed = True
            if engine_id is not None:
                try:
                    self.engine.kill(engine_id)
                except EngineError:
                    pass
                self.engine.remove(engine_id)
                removed = self.engine.inspect(engine_id) is None
            self.journal.update(record.job_id, record.fence,
                                state='finished' if removed else 'cleanup_pending',
                                outcome='cancelled', cleanup_complete=removed,
                                engine_id=engine_id)

    # ------------------------------------------------------------------ start

    def start(self, metadata, context, raw):
        metadata = validate(metadata, 'LaunchStart')
        if (sha256(context) != metadata['context_sha256']
                or sha256(raw) != metadata['raw_sha256']):
            raise IngestionError('import_invalid')
        if metadata['instance_id'] != self.config.instance_id:
            raise IngestionError('import_stale')
        if metadata['credential_epoch'] != self.config.credential_epoch:
            raise IngestionError('credentials_changed')
        profile = [item for item in self.profiles
                   if item['image_digest'] == metadata['image_digest']
                   and item['installation_id'] == metadata['installation_id']
                   and item['profile_digest'] == metadata['wrapper_profile_digest']
                   and metadata['format_version'] in item['format_versions']]
        if len(profile) != 1:
            raise IngestionError('import_evidence_unsupported')
        reference = self._reference.get(metadata['image_digest'])
        if reference is None:
            raise IngestionError('import_evidence_unsupported')
        key = (metadata['job_id'], metadata['fence'])
        with self._lock:
            existing = self._attempts.get(key)
            if existing is not None:
                if existing.record.nonce_digest != sha256(metadata['nonce'].encode()):
                    raise IngestionError('import_conflict')
                return _status(existing)
            record = self._record_for(metadata, '0' * 64, metadata['nonce'])
            handle = secrets.token_hex(32)
            record = replace(record, handle_digest=sha256(handle.encode()))
            if not self.journal.create(record):
                raise IngestionError('import_conflict')
            attempt = Attempt(record=record, handle=handle, nonce=metadata['nonce'],
                              context_sha256=metadata['context_sha256'],
                              raw_sha256=metadata['raw_sha256'],
                              payload_kind=json.loads(context)['payload_kind'],
                              installation_id=metadata['installation_id'],
                              wrapper_profile_digest=metadata['wrapper_profile_digest'])
            self._attempts[key] = attempt
        labels = (('kurafolio.launcher.instance', self.config.instance_id),
                  ('kurafolio.launcher.nonce', record.nonce_digest),
                  ('kurafolio.launcher.fence', metadata['fence']))
        try:
            engine_id = self.engine.create(reference=reference, labels=labels)
        except EngineError:
            self.journal.remove(record.job_id, record.fence)
            with self._lock:
                self._attempts.pop(key, None)
            raise IngestionError('import_runner_unavailable') from None
        with self._lock:
            attempt.record = self.journal.update(record.job_id, record.fence,
                                                 engine_id=engine_id, state='started')
        frame = pack_input(metadata, context, raw, schema='LaunchStart')
        threading.Thread(target=self._execute, args=(attempt, engine_id, frame),
                         name='launcher-child', daemon=True).start()
        return _status(attempt)

    def _execute(self, attempt, engine_id, frame):
        try:
            deadline = datetime.fromisoformat(attempt.record.deadline['token'])
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            limit = max(0, min(10, remaining))
            run = self.engine.start(engine_id, frame, execution_limit=limit)
            if limit <= 0 and run.outcome is None:
                run = type(run)(output=None, outcome='wall_limit', overflow=False,
                                exit_code=run.exit_code, oom_killed=run.oom_killed,
                                killed=True, started_at=run.started_at)
        except EngineError as error:
            LOG.warning('launch_failed job_id=%s fence=%s code=%s',
                        attempt.record.job_id, attempt.record.fence, error.code)
            self._finish(attempt, 'failed', 'child_error', cleanup_complete=False)
            return
        if run.outcome is not None:
            self._finish(attempt, 'failed', run.outcome, cleanup_complete=False)
            return
        expected = {'job_id': attempt.record.job_id, 'member_id': attempt.record.member_id,
                    'fence': attempt.record.fence,
                    'installation_id': attempt.installation_id,
                    'image_digest': attempt.record.image_digest,
                    'wrapper_profile_digest': attempt.wrapper_profile_digest,
                    'raw_sha256': attempt.raw_sha256,
                    'context_sha256': attempt.context_sha256,
                    'payload_kind': attempt.payload_kind}
        try:
            header, payload = unpack_result(run.output or b'', expected, child=True,
                                            exit_code=run.exit_code or 0,
                                            overflow=run.overflow)
            result = pack_result({**header, 'handle': attempt.handle}, payload)
        except IngestionError:
            self._finish(attempt, 'failed', 'frame_rejected', cleanup_complete=False)
            return
        with self._lock:
            attempt.payload, attempt.result = payload, result
            attempt.record = self.journal.update(attempt.record.job_id, attempt.record.fence,
                                                 state='result_ready', outcome='ok')
            deadline = datetime.fromisoformat(attempt.record.deadline['token'])
            delay = max(0, (deadline - datetime.now(timezone.utc)).total_seconds())
            timer = threading.Timer(delay, self._drop_result, args=(attempt,))
            timer.daemon = True
            timer.start()

    def _drop_result(self, attempt):
        with self._lock:
            attempt.payload = None
            attempt.result = None

    def _finish(self, attempt, state, outcome, *, cleanup_complete):
        with self._lock:
            attempt.record = self.journal.update(attempt.record.job_id, attempt.record.fence,
                                                 state=state, outcome=outcome,
                                                 cleanup_complete=cleanup_complete)

    # ----------------------------------------------------------------- control

    def control(self, request):
        request = validate(request, 'LaunchControl')
        if request['instance_id'] != self.config.instance_id:
            raise IngestionError('import_stale')
        with self._lock:
            attempt = self._attempts.get((request['job_id'], request['fence']))
            if attempt is None:
                attempt = self._attempt_from_journal(request)
            if attempt is None:
                raise IngestionError('not_found')
        if (request['credential_epoch'] != attempt.record.credential_epoch
                or request['realm_digest'] != attempt.record.realm_digest
                or request['member_id'] != attempt.record.member_id
                or sha256(request['handle'].encode()) != attempt.record.handle_digest):
            raise IngestionError('authentication_required')
        with self._lock:
            self._attempts.setdefault((attempt.record.job_id, attempt.record.fence), attempt)
        self._expire_results(attempt)
        operation = request['operation']
        if operation == 'status':
            return self._status_result(attempt, request['include_result'])
        if operation == 'cancel':
            self._cancel(attempt)
            return _status(attempt), None
        if operation == 'forget':
            if attempt.record.state != 'finished' or not attempt.record.cleanup_complete:
                raise IngestionError('import_conflict')
            status = _status(attempt)
            self.journal.remove(attempt.record.job_id, attempt.record.fence)
            with self._lock:
                self._attempts.pop((attempt.record.job_id, attempt.record.fence), None)
            return status, None
        raise IngestionError('import_invalid')

    def _attempt_from_journal(self, request):
        record = self.journal.get(request['job_id'], request['fence'])
        if record is None:
            return None
        return Attempt(record=record, handle=request['handle'], nonce=None,
                       context_sha256='', raw_sha256='', payload_kind='parser_v2',
                       installation_id='', wrapper_profile_digest='')

    def _expire_results(self, attempt):
        if attempt.payload is None and attempt.result is None:
            return
        deadline = datetime.fromisoformat(attempt.record.deadline['token'])
        if datetime.now(timezone.utc) >= deadline:
            attempt.payload = None
            attempt.result = None

    def _status_result(self, attempt, include_result):
        status = _status(attempt)
        if include_result and attempt.result is not None and attempt.record.state == 'result_ready':
            return status, attempt.result
        return status, None

    def _cancel(self, attempt):
        engine_id = attempt.record.engine_id
        if attempt.record.state == 'finished':
            return
        attempt.cancelled = True
        if engine_id is not None:
            try:
                self.engine.kill(engine_id)
            except EngineError:
                pass
            self.engine.remove(engine_id)
            removed = self.engine.inspect(engine_id) is None
            self._finish(attempt, 'finished' if removed else 'cleanup_pending',
                         attempt.record.outcome or 'cancelled', cleanup_complete=removed)
        else:
            self._finish(attempt, 'finished', attempt.record.outcome or 'cancelled',
                         cleanup_complete=True)
        attempt.result = None

    # -------------------------------------------------------------------- http

    def start_server(self):
        self._server = LauncherServer(self.config.server_tls, self.config.bind_address,
                                      self.config.bind_port, self)
        return self._server.start()

    def stop(self):
        if self._server is not None:
            self._server.stop()
            self._server = None
        with self._lock:
            attempts = list(self._attempts.values())
        for attempt in attempts:
            self._cancel(attempt)


class LauncherServer:
    def __init__(self, peer_tls, address, port, launcher):
        self._peer_tls = peer_tls
        self._address = address
        self._port = port
        self._launcher = launcher
        self._httpd = None
        self._thread = None

    def start(self):
        if self._httpd is not None:
            raise RuntimeError('already started')
        server = _Server((self._address, self._port), _Handler)
        server.ssl_context = self._peer_tls.context(server=True)
        server.peer_tls = self._peer_tls
        server.launcher = self._launcher
        server.daemon_threads = True
        server.handshake_slots = threading.BoundedSemaphore(16)
        self._httpd = server
        self._thread = threading.Thread(target=server.serve_forever, name='launcher', daemon=True)
        self._thread.start()
        return server.server_address

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._thread.join(timeout=5)
            self._httpd = None
            self._thread = None


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        if not self.handshake_slots.acquire(blocking=False):
            try:
                request.close()
            except OSError:
                pass
            return

        def handshake():
            try:
                request.settimeout(5)
                tls = self.ssl_context.wrap_socket(request, server_side=True)
                self.peer_tls.verify_peer(tls)
            except (ssl.SSLError, OSError, ValueError):
                try:
                    request.close()
                except OSError:
                    pass
                return
            try:
                self.finish_request(tls, client_address)
            finally:
                self.shutdown_request(tls)
                self.handshake_slots.release()
        threading.Thread(target=handshake, daemon=True).start()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'kurafolio-ingestion-launcher'
    sys_version = ''

    def log_message(self, format, *args):
        LOG.info('launcher method=%s path=%s status=%s', self.command, self.path,
                 getattr(self, '_status', '-'))

    def log_error(self, format, *args):
        LOG.warning('launcher method=%s path=%s status=%s', self.command, self.path,
                    getattr(self, '_status', '-'))

    def _refuse(self, status, code):
        self._send(status, encode({'code': code}), 'application/json')

    def do_GET(self):
        self._refuse(404, 'not_found')

    def do_PUT(self):
        self._refuse(405, 'method_not_allowed')

    def do_DELETE(self):
        self._refuse(405, 'method_not_allowed')

    def do_HEAD(self):
        self._refuse(405, 'method_not_allowed')

    def do_POST(self):
        self.close_connection = True
        try:
            if self.path == '/internal/v1/jobs':
                metadata, context, raw = unpack_input(self._body(JOB_BODY), schema='LaunchStart')
                status = self.server.launcher.start(metadata, context, raw)
                self._send(200, encode(status), 'application/json')
                return
            if self.path == '/internal/v1/control':
                request = validate(self._json_body(), 'LaunchControl')
                status, frame = self.server.launcher.control(request)
                if frame is not None:
                    self._send(200, frame, 'application/octet-stream')
                else:
                    self._send(200, encode(status), 'application/json')
                return
            self._refuse(404, 'not_found')
        except IngestionError as error:
            self._refuse(ERROR_STATUS.get(error.code, 422), error.code)
        except Exception as error:
            code = getattr(error, 'code', None)
            self._refuse(ERROR_STATUS.get(code, 500) if type(code) is str else 500,
                         code if type(code) is str and code in ERROR_STATUS else 'internal_error')

    def _json_body(self):
        body = self._body(CONTROL_BODY)
        try:
            value = json.loads(body)
            if encode(value) != body:
                raise ValueError()
            return value
        except (ValueError, UnicodeError):
            raise IngestionError('import_invalid') from None

    def _body(self, maximum):
        for name in _REFUSED_HEADERS:
            if self.headers.get_all(name):
                raise IngestionError('invalid_headers')
        lengths = self.headers.get_all('Content-Length') or []
        if len(lengths) != 1:
            raise IngestionError('length_required' if not lengths else 'invalid_length')
        text = lengths[0].strip()
        if not text.isdigit() or not 0 < int(text) <= maximum:
            raise IngestionError('import_limit')
        length = int(text)
        deadline = time.monotonic() + TOTAL_SECONDS
        body = bytearray()
        while len(body) < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IngestionError('request_timeout')
            self.connection.settimeout(min(IDLE_SECONDS, remaining))
            try:
                chunk = self.rfile.read(min(65536, length - len(body)))
            except (socket.timeout, TimeoutError):
                raise IngestionError('request_timeout') from None
            if not chunk:
                raise IngestionError('invalid_length')
            body.extend(chunk)
        return bytes(body)

    def _send(self, status, body, content_type):
        self._status = status
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)


def main(argv=None):
    import argparse
    import signal

    parser = argparse.ArgumentParser(prog='kurafolio-import-launcher')
    parser.add_argument('command', choices=('serve', 'check'))
    parser.add_argument('--config', required=True)
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    try:
        config = load_config(options.config)
        launcher = Launcher(config)
    except (ConfigError, JournalError, RuntimeError) as error:
        LOG.error('launcher_refused code=%s', getattr(error, 'code', 'invalid_config'))
        return 2
    if options.command == 'check':
        for digest, reference in sorted(launcher._reference.items()):
            image_id = launcher.engine.image(reference)
            engine_id = launcher.engine.create(
                reference=reference,
                labels=(('kurafolio.launcher.instance', config.instance_id),
                        ('kurafolio.launcher.nonce', sha256(secrets.token_hex(32).encode())),
                        ('kurafolio.launcher.fence', '1')),
                entry=('/bin/true',))
            try:
                value = launcher.engine.configuration(engine_id)
            finally:
                launcher.engine.remove(engine_id)
            host = value['HostConfig']
            print(json.dumps({'image_digest': digest, 'reference': reference,
                              'image_id': image_id,
                              'network': host['NetworkMode'], 'readonly': host['ReadonlyRootfs'],
                              'user': value['Config'].get('User'),
                              'cap_drop': host.get('CapDrop'), 'security_opt': host.get('SecurityOpt'),
                              'ipc': host.get('IpcMode'), 'pids': host.get('PidsLimit'),
                              'memory': host.get('Memory'), 'memory_swap': host.get('MemorySwap'),
                              'nano_cpus': host.get('NanoCpus'), 'tmpfs': host.get('Tmpfs')}))
        return 0
    address = launcher.start_server()

    def stop(signum, frame):
        launcher.stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info('launcher_started address=%s', address)
    while launcher._server is not None:
        time.sleep(1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
