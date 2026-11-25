"""Closed worker configuration: paths, identifiers and private TLS only."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat

from ..persistence.config import PostgresConfig
from .codec import validate
from .runner_client import PeerTLS

MAX_CONFIG = 65536
_KEYS = {'version', 'database', 'worker_id', 'credential_epoch', 'instance_id', 'realm_digest',
         'api_tls', 'launcher_tls', 'launcher_host', 'launcher_port', 'bind_address', 'bind_port',
         'journal_directory', 'catalog_file', 'profiles_file'}
_TLS_KEYS = {'ca_file', 'cert_file', 'key_file', 'peer_dns'}
_DATABASE_KEYS = {'secret_file', 'pool_size'}


class ConfigError(RuntimeError):
    def __init__(self, code='invalid_config'):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    database: PostgresConfig
    worker_id: str
    credential_epoch: str
    instance_id: str
    realm_digest: str
    api_tls: PeerTLS
    launcher_tls: PeerTLS
    launcher_host: str
    launcher_port: int
    bind_address: str
    bind_port: int
    journal_directory: Path
    catalog_file: Path
    profiles_file: Path


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


def _text(value, pattern, maximum=4096):
    if (type(value) is not str or not 1 <= len(value) <= maximum
            or re.fullmatch(pattern, value) is None):
        raise ConfigError()
    return value


def read_profiles_file(path):
    """Read the operator's trusted wrapper profiles; never from a staged document."""
    _regular(path, secret=False)
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise ConfigError() from None
    if not 0 < len(raw) <= MAX_CONFIG:
        raise ConfigError()
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ConfigError() from None
    if type(value) is not list or not 1 <= len(value) <= 64:
        raise ConfigError()
    return [validate(profile, 'WrapperProfile') for profile in value]


def load(path):
    _regular(path, secret=True)
    try:
        descriptor = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            raw = os.read(descriptor, MAX_CONFIG + 1)
        finally:
            os.close(descriptor)
        if not 0 < len(raw) <= MAX_CONFIG:
            raise ConfigError()
        value = json.loads(raw)
    except ConfigError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise ConfigError() from None
    if type(value) is not dict or set(value) != _KEYS or value.get('version') != 1:
        raise ConfigError()

    database = value['database']
    if type(database) is not dict or set(database) != _DATABASE_KEYS:
        raise ConfigError()
    pool_size = database['pool_size']
    if type(pool_size) is not int or not 1 <= pool_size <= 5:
        raise ConfigError()
    secret_file = Path(_text(database['secret_file'], r'.+'))
    _regular(secret_file, secret=True)
    try:
        connection = PostgresConfig.from_secret_file(secret_file, pool_size=pool_size)
    except Exception:
        raise ConfigError() from None

    instance_id = validate(_text(value['instance_id'], r'[0-9a-f-]{36}'), 'UUID')
    worker_id = validate(_text(value['worker_id'], r'[0-9a-f-]{36}'), 'UUID')
    credential_epoch = _text(value['credential_epoch'], r'(0|[1-9][0-9]{0,18})', 19)
    realm_digest = validate(_text(value['realm_digest'], r'[0-9a-f]{64}', 64), 'Hash')

    def tls(name, role):
        group = value[name]
        if type(group) is not dict or set(group) != _TLS_KEYS:
            raise ConfigError()
        paths = {key: Path(_text(group[key], r'.+')) for key in ('ca_file', 'cert_file', 'key_file')}
        _regular(paths['ca_file'], secret=False)
        _regular(paths['cert_file'], secret=False)
        _regular(paths['key_file'], secret=True)
        peer_dns = _text(group['peer_dns'], r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}')
        try:
            PeerTLS(ca_file=paths['ca_file'], cert_file=paths['cert_file'], key_file=paths['key_file'],
                    peer_dns=peer_dns, instance_id=instance_id, peer_role=role).context()
        except Exception:
            raise ConfigError() from None
        return group

    api = tls('api_tls', 'api')
    launcher = tls('launcher_tls', 'launcher')

    launcher_host = _text(value['launcher_host'], r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}')
    bind_address = _text(value['bind_address'], r'[0-9A-Fa-f:.]{2,64}')
    for name in ('launcher_port', 'bind_port'):
        if type(value[name]) is not int or not 1 <= value[name] <= 65535:
            raise ConfigError()
    journal_directory = Path(_text(value['journal_directory'], r'.+'))
    catalog_file = Path(_text(value['catalog_file'], r'.+'))
    profiles_file = Path(_text(value['profiles_file'], r'.+'))
    _regular(catalog_file, secret=False)

    def peer(group, role):
        return PeerTLS(ca_file=Path(group['ca_file']), cert_file=Path(group['cert_file']),
                       key_file=Path(group['key_file']), peer_dns=group['peer_dns'],
                       instance_id=instance_id, peer_role=role)

    return WorkerConfig(database=connection, worker_id=worker_id, credential_epoch=credential_epoch,
                        instance_id=instance_id, realm_digest=realm_digest,
                        api_tls=peer(api, 'api'), launcher_tls=peer(launcher, 'launcher'),
                        launcher_host=launcher_host, launcher_port=value['launcher_port'],
                        bind_address=bind_address, bind_port=value['bind_port'],
                        journal_directory=journal_directory, catalog_file=catalog_file,
                        profiles_file=profiles_file)
