"""The worker's private attempt journal: content-free launcher handles.

An entry names the set, job, member and fence, plus the launcher handle once it is
known. It never holds raw bytes, context, results, the handoff token or a nonce.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat

from .codec import encode, validate

_FIELDS = ('handle', 'fence', 'job_id', 'member_id', 'set_id', 'version')
_NAME = re.compile(r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-'
                   r'([1-9][0-9]{0,17})\.json$')
_TEMPORARY = re.compile(r'^\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-'
                        r'[1-9][0-9]{0,17}\.json\.tmp$')


class JournalError(RuntimeError):
    """A fixed journal refusal code: journal_unsafe or journal_invalid."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Record:
    set_id: str
    job_id: str
    member_id: str
    fence: str
    handle: str | None


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


class WorkerJournal:
    def __init__(self, directory):
        self.directory = Path(directory)
        try:
            _check_directory(self.directory, os.getuid())
            for entry in self.directory.iterdir():
                if _NAME.fullmatch(entry.name) is not None:
                    self._read(entry.name)
                elif _TEMPORARY.fullmatch(entry.name) is not None:
                    _check_file(entry, os.getuid())
                else:
                    raise JournalError('journal_invalid')
        except OSError:
            raise JournalError('journal_unsafe') from None

    @staticmethod
    def _name(job_id, fence):
        validate(job_id, 'UUID')
        if type(fence) is not str or not re.fullmatch(r'[1-9][0-9]{0,17}', fence):
            raise ValueError('fence')
        return f'{job_id}-{fence}.json'

    def record(self, set_id, job_id, member_id, fence):
        """Create-only: an existing record keeps its old content and returns False."""
        name = self._name(job_id, fence)
        path = self.directory / name
        if path.exists():
            return False
        value = {'version': 1, 'set_id': validate(set_id, 'UUID'),
                 'job_id': validate(job_id, 'UUID'), 'member_id': validate(member_id, 'UUID'),
                 'fence': fence, 'handle': None}
        body = encode(value)
        temporary = self.directory / ('.' + name + '.tmp')
        descriptor = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(descriptor, body)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(temporary, path)
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
        return True

    def set_handle(self, job_id, fence, handle):
        name = self._name(job_id, fence)
        current = self._read(name)
        if current.handle is not None:
            if current.handle != handle:
                raise JournalError('journal_invalid')
            return
        if type(handle) is not str or not re.fullmatch(r'[0-9a-f]{64}', handle):
            raise ValueError('handle')
        value = {'version': 1, 'set_id': current.set_id, 'job_id': current.job_id,
                 'member_id': current.member_id, 'fence': current.fence, 'handle': handle}
        body = encode(value)
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

    def for_set(self, set_id):
        return [record for record in self.records() if record.set_id == set_id]

    def records(self):
        values = []
        for entry in sorted(self.directory.iterdir()):
            if entry.name.startswith('.'):
                continue
            values.append(self._read(entry.name))
        return values

    def remove(self, job_id, fence):
        name = self._name(job_id, fence)
        try:
            (self.directory / name).unlink()
        except FileNotFoundError:
            return False
        except OSError:
            raise JournalError('journal_unsafe') from None
        self._sync()
        return True

    def _read(self, name):
        match = _NAME.fullmatch(name)
        if match is None:
            raise JournalError('journal_invalid')
        path = self.directory / name
        try:
            _check_file(path, os.getuid())
            raw = path.read_bytes()
        except OSError:
            raise JournalError('journal_unsafe') from None
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise JournalError('journal_invalid') from None
        if type(value) is not dict or sorted(value) != sorted(_FIELDS) or value.get('version') != 1:
            raise JournalError('journal_invalid')
        try:
            if encode(value) != raw:
                raise JournalError('journal_invalid')
            set_id = validate(value['set_id'], 'UUID')
            job_id = validate(value['job_id'], 'UUID')
            member_id = validate(value['member_id'], 'UUID')
        except (ValueError, TypeError):
            raise JournalError('journal_invalid') from None
        fence = value['fence']
        handle = value['handle']
        if (type(fence) is not str or not re.fullmatch(r'[1-9][0-9]{0,17}', fence)
                or (handle is not None and (type(handle) is not str
                                            or not re.fullmatch(r'[0-9a-f]{64}', handle)))
                or match[1] != job_id or match[2] != fence):
            raise JournalError('journal_invalid')
        return Record(set_id=set_id, job_id=job_id, member_id=member_id, fence=fence, handle=handle)

    def _sync(self):
        descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
