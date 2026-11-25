"""Opt-in real-engine acceptance for the launcher's child containment.

Set ``KURAFOLIO_LAUNCHER_TEST=1`` and ``KURAFOLIO_LAUNCHER_BASE_IMAGE`` to an
immutable local image ID (``sha256:...``). The probe image is built offline from
that base with ``--network none``; no pull, tag or lock-file change is involved.
A skipped test is not acceptance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid

from kurafolio.ingestion.launcher_engine import ENVIRONMENT, PROFILE, DockerEngine

ENABLED = os.environ.get('KURAFOLIO_LAUNCHER_TEST') == '1'

PROBE = r'''
import json, os, resource, socket, sys, time
data = sys.stdin.buffer.read(4096).decode("utf-8", "strict")
operation, _, rest = data.partition("\n")
paths = json.loads(rest or "{}").get("paths", [])


def probe(operation):
    if operation == "inspect":
        status = dict(line.split(":", 1) for line in open("/proc/self/status").read().splitlines() if ":" in line)
        return {"uid": os.getuid(), "gid": os.getgid(), "environment": dict(os.environ),
                "cpu": list(resource.getrlimit(resource.RLIMIT_CPU)),
                "nofile": list(resource.getrlimit(resource.RLIMIT_NOFILE)),
                "core": list(resource.getrlimit(resource.RLIMIT_CORE)),
                "cpus": len(os.sched_getaffinity(0)),
                "cap_effective": int(status.get("CapEff", "1").strip(), 16),
                "no_new_privs": int(status.get("NoNewPrivs", "0").strip()),
                "sockets": [os.path.exists(p) for p in ("/var/run/docker.sock",
                                                        "/run/postgresql/.s.PGSQL.5432")]}
    if operation == "network":
        denied = []
        for target in (("1.1.1.1", 53), ("172.17.0.1", 80), ("127.0.0.1", 5432)):
            sock = socket.socket(); sock.settimeout(0.25)
            try:
                sock.connect(target); denied.append(False)
            except OSError:
                denied.append(True)
            finally:
                sock.close()
        return {"denied": denied, "interfaces": [list(v) for v in socket.if_nameindex()],
                "routes": open("/proc/net/route").read().splitlines()[1:]}
    if operation == "files":
        denied = []
        for path in paths:
            try:
                open(path, "rb").read(1); denied.append(False)
            except OSError:
                denied.append(True)
        return {"denied": denied, "socket": not os.path.exists("/var/run/docker.sock")}
    if operation == "readonly":
        blocked = []
        for name in ("/app/source-test", "/etc/source-test", "/data/source-test"):
            try:
                open(name, "xb").write(b"invented"); blocked.append(False)
            except OSError:
                blocked.append(True)
        open("/tmp/allowed", "xb").write(b"invented")
        return {"blocked": blocked, "tmp_writable": True}
    if operation == "pids":
        children = []
        try:
            for _ in range(64):
                pid = os.fork()
                if pid == 0:
                    time.sleep(30); os._exit(0)
                children.append(pid)
        except OSError:
            return {"limited": True}
        finally:
            for pid in children:
                os.kill(pid, 9); os.waitpid(pid, 0)
        return {"limited": False}
    if operation == "memory":
        held = []
        while True:
            held.append(bytearray(8 * 1024 * 1024))
    if operation == "cpu":
        while True:
            pass
    if operation in ("stdout", "stderr"):
        stream = sys.stdout.buffer if operation == "stdout" else sys.stderr.buffer
        while True:
            stream.write(b"x" * 8192); stream.flush()
    if operation == "descendant":
        if os.fork() == 0:
            time.sleep(30); os._exit(0)
    time.sleep(20)
    return {"unexpected_completion": True}


print(json.dumps(probe(operation)))
sys.stdout.flush()
'''


def docker(*args, timeout=60):
    result = subprocess.run(['docker', *args], capture_output=True, timeout=timeout)
    if result.returncode:
        raise AssertionError('Synthetic Docker operation failed')
    return result.stdout


@unittest.skipUnless(ENABLED, 'Explicit real launcher containment required')
class LauncherContainmentTests(unittest.TestCase):
    """AC-IMP-007F-02, AC-IMP-007F-03 and AC-IMP-007F-06 on a real engine."""

    @classmethod
    def setUpClass(cls):
        cls.base = os.environ.get('KURAFOLIO_LAUNCHER_BASE_IMAGE')
        if not cls.base or not cls.base.startswith('sha256:'):
            raise AssertionError('KURAFOLIO_LAUNCHER_BASE_IMAGE must be an immutable image ID')
        cls.directory = tempfile.TemporaryDirectory(prefix='wl-imp-007f-containment-')
        context = Path(cls.directory.name)
        (context / 'probe.py').write_text(PROBE)
        tag = 'kurafolio-launcher-base:test'
        docker('tag', cls.base, tag)
        cls.addClassCleanup(docker, 'image', 'rm', tag)
        (context / 'Dockerfile').write_text('FROM ' + tag + '\nCOPY probe.py /probe.py\n')
        docker('build', '--network', 'none', '-t', 'kurafolio-launcher-probe:test', str(context))
        cls.image = json.loads(docker('image', 'inspect', '--format', '{{json .Id}}',
                                      'kurafolio-launcher-probe:test'))
        cls.engine = DockerEngine()
        cls.addClassCleanup(docker, 'image', 'rm', 'kurafolio-launcher-probe:test')

    def run_probe(self, operation, paths=None, *, cancel_after=None):
        labels = (('kurafolio.launcher.instance', '70000000-0000-4000-8000-000000000002'),
                  ('kurafolio.launcher.nonce', 'a' * 64),
                  ('kurafolio.launcher.fence', str(uuid.uuid4().int % 100000 + 1)))
        entry = ('/usr/bin/env', '-i', *ENVIRONMENT, 'python3', '/probe.py')
        engine_id = self.engine.create(reference=self.image, labels=labels, entry=entry)
        self.addCleanup(lambda: self.engine.remove(engine_id))
        frame = operation.encode() + b'\n' + json.dumps({'paths': paths or []}).encode()
        run = self.engine.start(engine_id, frame, execution_limit=cancel_after or 10)
        return engine_id, run

    def test_ac_02_effective_profile_and_environment(self):
        engine_id, run = self.run_probe('inspect')
        self.assertIsNone(run.outcome)
        value = json.loads(run.output)
        self.assertEqual((value['uid'], value['gid']), (10001, 10001))
        self.assertEqual(value['environment'], dict(item.split('=', 1) for item in ENVIRONMENT))
        self.assertEqual((value['cpu'], value['nofile'], value['core']), ([2, 2], [64, 64], [0, 0]))
        self.assertEqual(value['sockets'], [False, False])
        self.assertEqual(value['cap_effective'], 0)
        self.assertEqual(value['no_new_privs'], 1)
        self.assertGreaterEqual(value['cpus'], 1)
        config = json.loads(docker('inspect', engine_id))[0]
        host = config['HostConfig']
        self.assertTrue(host['ReadonlyRootfs'])
        self.assertEqual((host['NetworkMode'], host['IpcMode']), ('none', 'none'))
        self.assertEqual(host['CapDrop'], ['ALL'])
        self.assertIn('no-new-privileges', host['SecurityOpt'])
        self.assertEqual((host['Memory'], host['MemorySwap'], host['NanoCpus'], host['PidsLimit']),
                         (268435456, 268435456, 1000000000, 16))
        self.assertEqual(host['User'] if 'User' in host else config['Config']['User'], '10001:10001')
        self.assertFalse(config['Mounts'])
        self.assertFalse(host.get('Binds'))
        self.assertEqual(host['Tmpfs'],
                         {'/tmp': 'rw,noexec,nosuid,nodev,size=33554432,uid=10001,gid=10001'})

    def test_ac_06_network_and_filesystem_denials(self):
        _, run = self.run_probe('network')
        value = json.loads(run.output)
        self.assertEqual(value['denied'], [True, True, True])
        self.assertIn([1, 'lo'], value['interfaces'])
        self.assertEqual(value['routes'], [])
        with tempfile.TemporaryDirectory(prefix='kurafolio-launcher-host-') as temporary:
            canary = Path(temporary) / 'canary'
            canary.write_text('invented')
            _, run = self.run_probe('files', [str(canary)])
            value = json.loads(run.output)
            self.assertEqual(value, {'denied': [True], 'socket': True})
            _, run = self.run_probe('readonly')
            value = json.loads(run.output)
            self.assertEqual(value, {'blocked': [True, True, True], 'tmp_writable': True})

    def test_ac_06_resource_and_output_limits(self):
        cases = {'memory': 'resource_exit', 'cpu': 'resource_exit', 'stdout': 'output_limit',
                 'stderr': 'output_limit', 'sleep': 'wall_limit'}
        for operation, expected in cases.items():
            with self.subTest(operation=operation):
                started = time.monotonic()
                engine_id, run = self.run_probe(operation)
                self.assertLess(time.monotonic() - started, 15)
                self.assertEqual(run.outcome, expected)
                self.assertIsNotNone(self.engine.inspect(engine_id))
                self.assertTrue(self.engine.remove(engine_id))
                self.assertIsNone(self.engine.inspect(engine_id))

    def test_ac_03_restart_reconciles_a_real_container(self):
        from types import SimpleNamespace
        from kurafolio.ingestion.launcher import Launcher
        from kurafolio.ingestion.launcher_journal import LauncherJournal, Record
        with tempfile.TemporaryDirectory(prefix='wl-imp-007f-launcher-journal-') as directory:
            os.chmod(directory, 0o700)
            engine_id = self.engine.create(
                reference=self.image,
                labels=(('kurafolio.launcher.instance', '70000000-0000-4000-8000-000000000002'),
                        ('kurafolio.launcher.nonce', 'a' * 64),
                        ('kurafolio.launcher.fence', '7')),
                entry=('/usr/bin/env', '-i', *ENVIRONMENT, 'python3', '/probe.py'))
            self.addCleanup(lambda: self.engine.remove(engine_id))
            journal = LauncherJournal(directory)
            journal.create(Record(
                instance_id='70000000-0000-4000-8000-000000000002', peer='worker',
                credential_epoch='1', realm_digest='b' * 64,
                job_id=str(uuid.uuid4()), member_id=str(uuid.uuid4()), fence='7',
                nonce_digest='a' * 64, handle_digest='c' * 64, engine_id=engine_id,
                image_digest=self.image.removeprefix('sha256:'),
                deadline={'tag': 'instant', 'token': '2099-01-01T00:00:00+00:00',
                          'zone': None, 'fractional_digits': 0},
                state='started', outcome=None, cleanup_complete=False))
            launcher = object.__new__(Launcher)
            launcher.config = SimpleNamespace(
                instance_id='70000000-0000-4000-8000-000000000002')
            launcher.engine, launcher.journal = self.engine, journal
            launcher._reconcile()
            record = journal.records()[0]
            self.assertEqual(('finished', True, 'cancelled'),
                             (record.state, record.cleanup_complete, record.outcome))
            self.assertIsNone(self.engine.inspect(engine_id))

    def test_ac_06_pids_limit_stops_a_fork_bomb(self):
        _, run = self.run_probe('pids')
        self.assertIsNone(run.outcome)
        self.assertTrue(json.loads(run.output)['limited'])

    def test_ac_06_cancel_removes_the_exact_engine_id(self):
        engine_id, run = self.run_probe('descendant')
        self.assertIsNotNone(self.engine.inspect(engine_id))
        self.engine.kill(engine_id)
        self.assertTrue(self.engine.remove(engine_id))
        self.assertIsNone(self.engine.inspect(engine_id))


class DocumentationTests(unittest.TestCase):
    def test_ac_09_containment_matrix_names_both_platforms_and_tests(self):
        """AC-IMP-007F-09: the table is present, with both platform columns."""
        text = (Path(__file__).resolve().parents[1]
                / 'docs/web-v2-import-worker.md').read_text()
        self.assertIn('| Control | Docker Desktop, Apple Silicon | Native Linux CI |', text)
        for row in ('Network', 'Read-only root', 'PIDs limit 16', 'Output limits',
                    'Docker socket absent'):
            self.assertIn('| ' + row + ' |', text)
        self.assertIn('test_ac_06_network_and_filesystem_denials', text)
        self.assertIn('not tested', text)


if __name__ == '__main__':
    unittest.main()
