"""The worker's only database entry point: six fenced TRANSACTION functions.

The worker has no tenant scope. Scope comes from the stored set, and every call
carries the lease fence plus the token the claim was made with. Names outside the
fixed tuple never reach PostgreSQL, and this worker never claims prepare work.
"""
from __future__ import annotations

import logging
import random
import time
import uuid

from ..persistence import ingestion_schema
from .codec import encode, validate
from .contracts import IngestionError

LOG = logging.getLogger('kurafolio.ingestion.worker_sql')

CALLS = ('claim_member_v1', 'renew_member_v1', 'admit_stage_v1', 'finish_member_v1',
         'claim_plan_v1', 'cleanup_set_v1')
_CONTRACTS = {
    'claim_member_v1': ('ClaimMemberRequest', 'LeaseAck', False),
    'renew_member_v1': ('RenewMemberRequest', 'LeaseAck', False),
    'admit_stage_v1': ('AdmitStageRequest', 'StageAck', True),
    'finish_member_v1': ('FinishMemberRequest', 'FinishAck', False),
    'claim_plan_v1': ('ClaimPlanRequest', 'PlanClaimResult', False),
    'cleanup_set_v1': ('CleanupSetRequest', 'CleanupAck', False),
}
if any(name not in ingestion_schema.WORKER for name in CALLS):
    raise RuntimeError('worker function inventory mismatch')

RETRY_SQLSTATES = frozenset({'40001', '40P01', '55P03', '57014'})
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_MS = 30000


class WorkerCallError(RuntimeError):
    """A fixed worker SQL code; never driver text, SQL text or request content."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class WorkerSQL:
    """One worker role; every call is a fresh READ COMMITTED transaction."""

    def __init__(self, database, worker_id, *, sleep=time.sleep, jitter=random.random):
        if type(worker_id) is not str:
            raise ValueError('worker')
        validate(worker_id, 'UUID')
        self._database = database
        self.worker_id = worker_id
        self._sleep = sleep
        self._jitter = jitter

    def call(self, name, request, payload=None, *, token):
        """Run one fenced function and return its value, or raise WorkerCallError."""
        if name not in CALLS:
            raise ValueError('unknown worker function')
        request_schema, value_schema, takes_bytes = _CONTRACTS[name]
        if type(request) is not dict:
            raise ValueError('request')
        if name == 'claim_plan_v1' and request.get('work_kind') != 'cleanup':
            raise ValueError('prepare work is not in this worker')
        if type(token) is not str or not 1 <= len(token) <= 1024:
            raise ValueError('token')
        if takes_bytes:
            if type(payload) is not bytes:
                raise ValueError('payload')
        elif payload is not None:
            raise ValueError('payload')
        request = validate(request, request_schema)
        body = encode(request)
        request_id = request.get('request_id') or request.get('claim_request_id')
        attempt = 0
        while True:
            attempt += 1
            try:
                value = self._execute(name, token, body, payload)
            except Exception as error:  # narrowed below; never log driver text
                sqlstate = getattr(getattr(error, 'orig', None), 'sqlstate', None)
                if sqlstate not in RETRY_SQLSTATES or attempt >= MAX_ATTEMPTS:
                    if sqlstate in RETRY_SQLSTATES:
                        LOG.warning('worker_call function=%s request_id=%s code=import_busy', name, request_id)
                        raise WorkerCallError('import_busy') from None
                    LOG.error('worker_call function=%s request_id=%s code=internal_error', name, request_id)
                    raise WorkerCallError('internal_error') from None
                self._sleep(0.05 * (2 ** (attempt - 1)) * (0.5 + self._jitter()))
                continue
            if type(value) is not dict or value.get('ok') not in (True, False):
                LOG.error('worker_call function=%s request_id=%s code=internal_error', name, request_id)
                raise WorkerCallError('internal_error')
            if value['ok'] is False:
                code = value.get('code') if type(value.get('code')) is str else 'internal_error'
                LOG.info('worker_call function=%s request_id=%s code=%s', name, request_id, code)
                raise WorkerCallError(code)
            try:
                return validate(value.get('value'), value_schema)
            except IngestionError:
                LOG.error('worker_call function=%s request_id=%s code=internal_error', name, request_id)
                raise WorkerCallError('internal_error') from None

    def _execute(self, name, token, body, payload):
        from sqlalchemy import text
        with self._database.engine.connect().execution_options(
                isolation_level='READ COMMITTED') as conn:
            with conn.begin():
                conn.exec_driver_sql('SET LOCAL statement_timeout = ' + str(REQUEST_TIMEOUT_MS))
                statement = text('SELECT wl_ingestion.' + name +
                                 '(CAST(:worker AS uuid),CAST(:token AS text),'
                                 'CAST(:request AS jsonb),CAST(:payload AS bytea))')
                row = conn.execute(statement, {'worker': self.worker_id, 'token': token,
                                               'request': body.decode('utf-8'),
                                               'payload': payload}).scalar_one()
                return row


def module_uuid(namespace, name):
    """Stable operation UUID for a retried worker request."""
    if type(namespace) is not str or type(name) is not str:
        raise ValueError('uuid')
    return str(uuid.uuid5(uuid.UUID(namespace), name))
