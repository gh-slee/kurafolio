"""The launcher's private ownership journal.

One content-free record per attempt. It binds the instance, peer, credential
epoch, realm, job, member, fence, nonce and handle digests, the exact engine ID,
the immutable image digest, the raw deadline and the lifecycle state. It never
holds raw bytes, context, results, stderr, a plaintext nonce or a plaintext
handle.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import stat

from .codec import encode, validate

STATES = ('created', 'started', 'result_ready', 'failed', 'cleanup_pending', 'finished')
OUTCOMES = (None, 'ok', 'frame_rejected', 'child_error', 'output_limit', 'resource_exit',
            'wall_limit', 'cancelled', 'cleanup_failed', 'context_rejected')
_FIELDS = frozenset({'version', 'instance_id', 'peer', 'credential_epoch', 'realm_digest',
                     'job_id', 'member_id', 'fence', 'nonce_digest', 'handle_digest',
                     'engine_id', 'image_digest', 'deadline', 'state', 'outcome',
                     'cleanup_complete'})
_NAME = re.compile(r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-'
                   r'([1-9][0-9]{0,17})\.json$')
_TEMPORARY = re.compile(r'^\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-'
                        r'[1-9][0-9]{0,17}\.json\.tmp$')
_ENGINE = re.compile(r'^[0-9a-f]{64}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_COUNTER = re.compile(r'^[1-9][0-9]{0,17}$')


class JournalError(RuntimeError):
    """A fixed journal refusal code: journal_unsafe or journal_invalid."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Record:
    instance_id: str
    peer: str
    credential_epoch: str
    realm_digest: str
    job_id: str
    member_id: str
    fence: str
    nonce_digest: str
    handle_digest: str
    engine_id: str | None
    image_digest: str
    deadline: dict
    state: str
    outcome: str | None
    cleanup_complete: bool


def _check_file(path, uid):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise JournalError('journal_unsafe')


def _check_directory(directory, uid):
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != uid
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise JournalError('journal_unsafe')


def _name(job_id, fence):
    if type(job_id) is not str or _UUID.fullmatch(job_id) is None:
        raise JournalError('journal_invalid')
    if type(fence) is not str or _COUNTER.fullmatch(fence) is None:
        raise JournalError('journal_invalid')
    return f'{job_id}-{fence}.json'


def _build(value):
    if type(value) is not dict or set(value) != _FIELDS or value.get('version') != 1:
        raise JournalError('journal_invalid')
    try:
        deadline = validate(value['deadline'], 'Instant')
    except Exception:
        raise JournalError('journal_invalid') from None
    checked = {
        'instance_id': value['instance_id'], 'peer': value['peer'],
        'credential_epoch': value['credential_epoch'], 'realm_digest': value['realm_digest'],
        'job_id': value['job_id'], 'member_id': value['member_id'], 'fence': value['fence'],
        'nonce_digest': value['nonce_digest'], 'handle_digest': value['handle_digest'],
        'engine_id': value['engine_id'], 'image_digest': value['image_digest'],
        'deadline': deadline, 'state': value['state'], 'outcome': value['outcome'],
        'cleanup_complete': value['cleanup_complete']}
    if (type(checked['instance_id']) is not str or _UUID.fullmatch(checked['instance_id']) is None
            or checked['peer'] != 'worker'
            or type(checked['credential_epoch']) is not str
            or _COUNTER.fullmatch(checked['credential_epoch']) is None
            or type(checked['realm_digest']) is not str
            or _HASH.fullmatch(checked['realm_digest']) is None
            or type(checked['job_id']) is not str or _UUID.fullmatch(checked['job_id']) is None
            or type(checked['member_id']) is not str
            or _UUID.fullmatch(checked['member_id']) is None
            or type(checked['fence']) is not str or _COUNTER.fullmatch(checked['fence']) is None
            or type(checked['nonce_digest']) is not str
            or _HASH.fullmatch(checked['nonce_digest']) is None
            or type(checked['handle_digest']) is not str
            or _HASH.fullmatch(checked['handle_digest']) is None
            or (checked['engine_id'] is not None and (type(checked['engine_id']) is not str
                                                      or _ENGINE.fullmatch(checked['engine_id']) is None))
            or type(checked['image_digest']) is not str
            or _HASH.fullmatch(checked['image_digest']) is None
            or checked['state'] not in STATES or checked['outcome'] not in OUTCOMES
            or type(checked['cleanup_complete']) is not bool):
        raise JournalError('journal_invalid')
    return Record(**checked)


class LauncherJournal:
    def __init__(self, directory):
        self.directory = Path(directory)
        try:
            _check_directory(self.directory, os.getuid())
            for entry in self.directory.iterdir():
                if _NAME.fullmatch(entry.name) is not None:
                    self.get(*self._split(entry.name))
                elif _TEMPORARY.fullmatch(entry.name) is not None:
                    _check_file(entry, os.getuid())
                else:
                    raise JournalError('journal_invalid')
        except OSError:
            raise JournalError('journal_unsafe') from None

    @staticmethod
    def _split(name):
        match = _NAME.fullmatch(name)
        if match is None:
            raise JournalError('journal_invalid')
        return match.group(1), match.group(2)

    def _write(self, record):
        body = encode({'version': 1, 'instance_id': record.instance_id, 'peer': record.peer,
                       'credential_epoch': record.credential_epoch,
                       'realm_digest': record.realm_digest, 'job_id': record.job_id,
                       'member_id': record.member_id, 'fence': record.fence,
                       'nonce_digest': record.nonce_digest, 'handle_digest': record.handle_digest,
                       'engine_id': record.engine_id, 'image_digest': record.image_digest,
                       'deadline': record.deadline, 'state': record.state,
                       'outcome': record.outcome, 'cleanup_complete': record.cleanup_complete})
        name = _name(record.job_id, record.fence)
        temporary = self.directory / ('.' + name + '.tmp')
        descriptor = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(descriptor, body)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(temporary, self.directory / name)
            self._sync()
        except OSError:
            raise JournalError('journal_unsafe') from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink()
            except OSError:
                pass

    def create(self, record):
        """Create-only; an existing record keeps its old content and returns False."""
        if self.get(record.job_id, record.fence) is not None:
            return False
        self._write(record)
        return True

    def update(self, job_id, fence, **changes):
        current = self.get(job_id, fence)
        if current is None:
            raise JournalError('journal_invalid')
        updated = replace(current, **changes)
        _build({'version': 1, 'instance_id': updated.instance_id, 'peer': updated.peer,
                'credential_epoch': updated.credential_epoch,
                'realm_digest': updated.realm_digest, 'job_id': updated.job_id,
                'member_id': updated.member_id, 'fence': updated.fence,
                'nonce_digest': updated.nonce_digest,
                'handle_digest': updated.handle_digest, 'engine_id': updated.engine_id,
                'image_digest': updated.image_digest, 'deadline': updated.deadline,
                'state': updated.state, 'outcome': updated.outcome,
                'cleanup_complete': updated.cleanup_complete})
        self._write(updated)
        return updated

    def get(self, job_id, fence):
        name = _name(job_id, fence)
        path = self.directory / name
        if not path.exists():
            return None
        try:
            _check_file(path, os.getuid())
            raw = path.read_bytes()
        except OSError:
            raise JournalError('journal_unsafe') from None
        try:
            value = json.loads(raw)
            if encode(value) != raw:
                raise JournalError('journal_invalid')
            record = _build(value)
        except JournalError:
            raise
        except (ValueError, UnicodeError):
            raise JournalError('journal_invalid') from None
        if name != _name(record.job_id, record.fence):
            raise JournalError('journal_invalid')
        return record

    def records(self):
        values = []
        for entry in sorted(self.directory.iterdir()):
            if entry.name.startswith('.'):
                continue
            values.append(self.get(*self._split(entry.name)))
        return values

    def remove(self, job_id, fence):
        name = _name(job_id, fence)
        try:
            (self.directory / name).unlink()
        except FileNotFoundError:
            return False
        except OSError:
            raise JournalError('journal_unsafe') from None
        self._sync()
        return True

    def _sync(self):
        descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
