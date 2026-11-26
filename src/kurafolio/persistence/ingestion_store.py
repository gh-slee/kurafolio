"""Bounded EXECUTE-only calls to the closed ingestion gateway."""
import json
import time

from .context import Database
from .identity import IdentityError, Principal, REALM_KEYS, STATUS as IDENTITY_STATUS
from .ingestion_schema import GATEWAY
from ..data_sources.catalog_v1 import catalog_digest
from ..data_sources.lifecycle_v1 import SourceError, STATUS as SOURCE_STATUS
from ..ingestion.contracts import ERROR_STATUS

_MUTATIONS = {'create_set_v1', 'decide_set_v1', 'accept_preview_v1', 'cancel_set_v1', 'reserve_member_v1'}


class IngestionStore:
    def __init__(self, config, catalog):
        self.database = Database(config, schema_mode='ingestion')
        self.catalog_digest = catalog_digest(catalog)

    def close(self):
        self.database.close()

    def call(self, name, principal, payload, *, deadline):
        if name not in GATEWAY or name == 'admit_rate_v1' or type(payload) is not dict:
            raise IdentityError()
        return self._run(name, principal, payload, deadline=deadline)

    def admit(self, principal, bucket):
        if bucket not in {'read', 'control'}:
            raise IdentityError()
        self._run('admit_rate_v1', principal, bucket, deadline=time.monotonic() + 20)

    def _run(self, name, principal, payload, *, deadline):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from ..web_v2.auth import RequestError
        if type(principal) is not Principal:
            raise IdentityError()
        kinds = ('text', 'uuid', 'int8', 'jsonb', 'text', 'text' if name == 'admit_rate_v1' else 'jsonb')
        arguments = (principal.session_digest, principal.user_id, principal.credential_version,
                     dict(zip(REALM_KEYS, principal.realm)), self.catalog_digest, payload)
        parameters, slots = {}, []
        for index, (kind, value) in enumerate(zip(kinds, arguments)):
            key = 'p' + str(index)
            parameters[key] = json.dumps(value, ensure_ascii=False, separators=(',', ':')) if kind == 'jsonb' else value
            slots.append('CAST(:' + key + ' AS pg_catalog.' + kind + ')')
        statement = text('SELECT wl_ingestion.' + name + '(' + ','.join(slots) + ')')
        result = None
        for attempt in range(3):
            if time.monotonic() >= deadline:
                raise IdentityError()
            try:
                with self.database.engine.connect() as conn:
                    transaction = conn.begin()
                    try:
                        remaining = max(1, min(5000, int((deadline - time.monotonic()) * 1000)))
                        conn.execute(text("SELECT pg_catalog.set_config('statement_timeout',:timeout,true),pg_catalog.set_config('lock_timeout',:lock,true)"),
                                     {'timeout': str(remaining), 'lock': str(min(2000, remaining))})
                        result = conn.execute(statement, parameters).scalar_one()
                        if type(result) is not dict or type(result.get('ok')) is not bool:
                            raise IdentityError()
                        if time.monotonic() >= deadline:
                            raise IdentityError()
                    except BaseException:
                        transaction.rollback()
                        raise
                    try:
                        transaction.commit()
                    except DBAPIError as error:
                        if getattr(error.orig, 'sqlstate', None) in {'40001', '40P01'}:
                            raise
                        if name in _MUTATIONS:
                            raise RequestError('import_commit_uncertain', 503) from None
                        raise IdentityError() from None
                    except Exception:
                        if name in _MUTATIONS:
                            raise RequestError('import_commit_uncertain', 503) from None
                        raise IdentityError() from None
                break
            except (IdentityError, RequestError):
                raise
            except DBAPIError as error:
                if getattr(error.orig, 'sqlstate', None) in {'40001', '40P01'} and attempt < 2 and time.monotonic() < deadline:
                    continue
                raise IdentityError() from None
            except Exception:
                raise IdentityError() from None
        if set(result) == {'ok', 'value'} and result['ok'] is True:
            if name == 'admit_rate_v1' and result['value'] is None:
                return None
            if name != 'admit_rate_v1' and type(result['value']) is dict:
                return result['value']
        if set(result) == {'ok', 'code'} and result['ok'] is False:
            code = result['code']
            if type(code) is str:
                if code.startswith('import_') and code in ERROR_STATUS:
                    raise RequestError(code, ERROR_STATUS[code])
                if code in SOURCE_STATUS:
                    raise SourceError(code)
                if code in IDENTITY_STATUS:
                    raise IdentityError(code)
        raise IdentityError()
