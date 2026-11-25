"""The only launcher module that touches the Docker engine.

Every argument list is built from constants and the reviewed profile; no caller
command, image tag, host path or engine name crosses this boundary. Raw and
result bytes stay in memory. The profile is the r7 child profile, not a general
container policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import threading
import time

from .runner_client import ChildOutputCollector, pack_input

PROFILE = ('--user', '10001:10001', '--read-only', '--cap-drop', 'ALL',
           '--security-opt', 'no-new-privileges', '--network', 'none', '--ipc', 'none',
           '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=33554432,uid=10001,gid=10001',
           '--memory', '268435456', '--memory-swap', '268435456', '--cpus', '1',
           '--pids-limit', '16', '--ulimit', 'cpu=2:2', '--ulimit', 'nofile=64:64',
           '--ulimit', 'core=0:0', '-i')
ENVIRONMENT = ('PATH=/usr/local/bin:/usr/bin:/bin', 'LANG=C.UTF-8', 'LC_ALL=C.UTF-8',
               'TZ=UTC', 'HOME=/nonexistent', 'PYTHONDONTWRITEBYTECODE=1',
               'PYTHONHASHSEED=0', 'PYTHONUNBUFFERED=1')
ENTRY = ('/usr/bin/env', '-i', *ENVIRONMENT, 'python', '-I',
         '/app/src/kurafolio/ingestion/runner_child.py')
_IMAGE = re.compile(r'^(?:[a-z0-9][a-z0-9._/-]*(?::[a-z0-9._-]+)?@)?sha256:[0-9a-f]{64}$')
_ENGINE = re.compile(r'^[0-9a-f]{64}$')
SETUP_TIMEOUT = 30
EXECUTION_LIMIT = 10
REAP_TIMEOUT = 5
JOIN_TIMEOUT = 2
REMOVE_TIMEOUT = 5


class EngineError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Run:
    output: bytes | None
    outcome: str | None
    overflow: bool
    exit_code: int | None
    oom_killed: bool
    killed: bool
    started_at: str | None


def _reject():
    raise EngineError('import_runner_unavailable')


class DockerEngine:
    """A fixed-argument Docker CLI adapter with no pull, prune, exec or name lookup."""

    def __init__(self, docker='docker', *, sleep=time.sleep, popen=subprocess.Popen):
        self.docker = docker
        self._sleep = sleep
        self._popen = popen

    def _run(self, args, *, timeout=SETUP_TIMEOUT, input=None):
        try:
            return subprocess.run([self.docker, *args], input=input,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            raise EngineError('import_runner_unavailable') from None

    def image(self, reference):
        if type(reference) is not str or _IMAGE.fullmatch(reference) is None:
            raise EngineError('import_invalid')
        result = self._run(['image', 'inspect', reference])
        if result.returncode:
            raise EngineError('import_runner_unavailable')
        try:
            value = json.loads(result.stdout)[0]
            if '@' in reference:
                for repo_digest in value.get('RepoDigests') or ():
                    if repo_digest == reference:
                        return reference.rsplit('@sha256:', 1)[1]
                raise EngineError('import_runner_unavailable')
            return value['Id'].removeprefix('sha256:')
        except (ValueError, KeyError, IndexError, TypeError):
            raise EngineError('import_runner_unavailable') from None

    def create(self, *, reference, labels, entry=ENTRY):
        if type(reference) is not str or _IMAGE.fullmatch(reference) is None:
            raise EngineError('import_invalid')
        args = ['create', *PROFILE]
        for key, value in labels:
            if (type(key) is not str or type(value) is not str
                    or not re.fullmatch(r'[a-z][a-z0-9._-]{0,63}', key)
                    or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', value)):
                raise EngineError('import_invalid')
            args.extend(['--label', key + '=' + value])
        args.extend(['--entrypoint', entry[0]])
        args.append(reference)
        args.extend(entry[1:])
        result = self._run(args)
        if result.returncode:
            raise EngineError('import_runner_unavailable')
        value = result.stdout.decode('ascii', 'strict').strip()
        if _ENGINE.fullmatch(value) is None:
            raise EngineError('import_runner_unavailable')
        return value

    def start(self, engine_id, frame, *, execution_limit=EXECUTION_LIMIT):
        if _ENGINE.fullmatch(engine_id) is None:
            raise EngineError('import_invalid')
        if type(frame) is not bytes or not frame:
            raise EngineError('import_invalid')
        try:
            process = self._popen([self.docker, 'start', '--attach', '--interactive', engine_id],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        except (OSError, subprocess.SubprocessError):
            raise EngineError('import_runner_unavailable') from None
        collector = ChildOutputCollector()
        readers = []
        for stream, sink in ((process.stdout, collector.stdout),
                             (process.stderr, collector.stderr)):
            def pump(stream=stream, sink=sink):
                try:
                    while True:
                        chunk = stream.read(4096)
                        if not chunk:
                            break
                        sink(chunk)
                finally:
                    stream.close()
            thread = threading.Thread(target=pump, daemon=True)
            thread.start()
            readers.append(thread)
        writer = threading.Thread(target=self._feed, args=(process, frame), daemon=True)
        writer.start()
        started = self._started_at(engine_id)
        outcome = None
        killed = False
        began = time.monotonic()
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - began
                if collector.stdout_overflow or collector.stderr_overflow:
                    outcome = 'output_limit'
                    break
                if elapsed >= execution_limit:
                    outcome = 'wall_limit'
                    break
                self._sleep(.01)
            if outcome is not None:
                killed = True
                self.kill(engine_id)
            process.wait(timeout=REAP_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=REAP_TIMEOUT)
        finally:
            for thread in readers:
                thread.join(timeout=JOIN_TIMEOUT)
            writer.join(timeout=JOIN_TIMEOUT)
        state = self.inspect(engine_id)
        if state is None:
            raise EngineError('import_runner_unavailable')
        if collector.stdout_overflow or collector.stderr_overflow:
            outcome = 'output_limit'
        if outcome is None:
            status = state.get('ExitCode')
            oom = bool(state.get('OOMKilled'))
            if oom or (type(status) is int and status == 137 and not killed):
                outcome = 'resource_exit'
            elif type(status) is not int or status != 0:
                outcome = 'child_error'
        return Run(output=None if outcome else bytes(collector.stdout_bytes()),
                   outcome=outcome, overflow=collector.stdout_overflow or collector.stderr_overflow,
                   exit_code=state.get('ExitCode'), oom_killed=bool(state.get('OOMKilled')),
                   killed=killed, started_at=started)

    @staticmethod
    def _feed(process, frame):
        try:
            process.stdin.write(frame)
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    def _started_at(self, engine_id):
        deadline = time.monotonic() + SETUP_TIMEOUT
        while time.monotonic() < deadline:
            state = self.inspect(engine_id)
            if state is not None:
                value = state.get('StartedAt')
                if type(value) is str and not value.startswith('0001-'):
                    return value
            self._sleep(.01)
        raise EngineError('import_runner_unavailable')

    def inspect(self, engine_id):
        if _ENGINE.fullmatch(engine_id) is None:
            raise EngineError('import_invalid')
        result = self._run(['inspect', engine_id], timeout=SETUP_TIMEOUT)
        if result.returncode:
            detail = result.stderr.decode('utf-8', 'replace').lower()
            if 'no such object' in detail or 'no such container' in detail:
                return None
            raise EngineError('import_runner_unavailable')
        try:
            values = json.loads(result.stdout)
            return values[0]['State']
        except (ValueError, KeyError, IndexError, TypeError):
            raise EngineError('import_runner_unavailable') from None

    def configuration(self, engine_id):
        if _ENGINE.fullmatch(engine_id) is None:
            raise EngineError('import_invalid')
        result = self._run(['inspect', engine_id], timeout=SETUP_TIMEOUT)
        if result.returncode:
            raise EngineError('import_runner_unavailable')
        try:
            return json.loads(result.stdout)[0]
        except (ValueError, IndexError, TypeError):
            raise EngineError('import_runner_unavailable') from None

    def kill(self, engine_id):
        if _ENGINE.fullmatch(engine_id) is None:
            raise EngineError('import_invalid')
        self._run(['kill', engine_id], timeout=REAP_TIMEOUT)

    def remove(self, engine_id):
        if _ENGINE.fullmatch(engine_id) is None:
            raise EngineError('import_invalid')
        result = self._run(['rm', '--force', engine_id], timeout=REMOVE_TIMEOUT)
        return result.returncode == 0

    def find(self, instance_id, nonce_digest):
        if (_ENGINE.fullmatch(nonce_digest) is None
                or not re.fullmatch(r'[0-9a-f-]{36}', instance_id)):
            raise EngineError('import_invalid')
        result = self._run(['ps', '--all', '--no-trunc',
                            '--filter', 'label=kurafolio.launcher.instance=' + instance_id,
                            '--filter', 'label=kurafolio.launcher.nonce=' + nonce_digest],
                           timeout=SETUP_TIMEOUT)
        if result.returncode:
            raise EngineError('import_runner_unavailable')
        return tuple(line.strip() for line in result.stdout.decode('ascii', 'strict').splitlines()
                     if _ENGINE.fullmatch(line.strip()) is not None)
