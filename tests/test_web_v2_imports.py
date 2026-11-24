"""Database-free AC-IMP-007E HTTP boundary, DTO and SQL-call contracts."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ID = '10000000-0000-4000-8000-000000000001'
OTHER = '10000000-0000-4000-8000-000000000002'
INSTANT = {'tag': 'instant', 'token': '2026-11-23T20:00:00+00:00', 'zone': None, 'fractional_digits': 0}
SET = dict(id=ID, state='RECEIVING', revision='1', created_at=INSTANT, expires_at=INSTANT,
           members=[], preview_id=None, receipt_id=None, cleanup_state='not_needed')
CREATE = dict(operation_id=OTHER, members=[dict(connection_id=ID, installation_id='a'*64,
                                             format_version='synthetic-v1', declared_bytes=None)])
DECIDE = dict(set_id=ID, decisions=dict(version=1, operation_id=OTHER, expected_set_revision='1',
                                      mappings=[], new_entities=[], authorities=[], parents=[]))
CANCEL = dict(operation_id=OTHER, expected_set_revision='1')
CONFIRM = dict(operation_id=OTHER, preview_digest='a'*64)
RECEIPT = dict(id=ID, operation_id=OTHER, kind='ACCEPT', origin_incarnation=ID, origin_restore_epoch='0',
               preview_id=ID, plan_digest='a'*64, accepted_generation='1', mapping_generation='0',
               new_facts='1', historical_facts='0', duplicates='0', no_change=False, created_at=INSTANT)
PAGE = dict(id=ID, set_id=OTHER, set_revision='1', state='READY', preview_digest='a'*64,
            expires_at=INSTANT, rows=[], can_confirm=True, review_digest='b'*64,
            content_digest='c'*64, accepted_generation='0', mapping_generation='0', control_generation='0')
CASES = [('POST', '/api/v2/import-sets', 'create_set_v1', CREATE, 201),
         ('GET', '/api/v2/import-sets', 'read_sets_v1', None, 200),
         ('GET', '/api/v2/import-sets/'+ID, 'read_set_v1', None, 200),
         ('PUT', '/api/v2/import-sets/'+ID+'/decisions', 'decide_set_v1', DECIDE, 202),
         ('GET', '/api/v2/import-previews/'+ID, 'read_preview_v1', None, 200),
         ('POST', '/api/v2/import-previews/'+ID+'/confirm', 'accept_preview_v1', CONFIRM, 200),
         ('POST', '/api/v2/import-sets/'+ID+'/cancel', 'cancel_set_v1', CANCEL, 200),
         ('GET', '/api/v2/import-receipts/'+ID, 'read_receipt_v1', None, 200)]


class FakeAuth:
    def __init__(self, settings):
        from kurafolio.ingestion import cursors
        self.settings, self.calls = settings, []
        self.imports = self
        self.cursor_key = cursors.derive_key(b'x'*32)
        self.failure = self.admit_failure = None
        self.values = {'read_sets_v1': {'items': [SET], 'next': None},
                       'read_preview_v1': {'page': PAGE, 'next': None},
                       'read_receipt_v1': RECEIPT, 'accept_preview_v1': RECEIPT}

    def ready(self): return True
    def close(self): pass
    def resolve(self, token):
        from kurafolio.web_v2.auth import RequestError
        self.calls.append(('resolve', token))
        if token != 'x'*43: raise RequestError('authentication_required', 401)
        return SimpleNamespace(user_id=ID)
    def csrf(self, token): return 'a'*64
    def budget(self, *args): self.calls.append(('budget', args))
    def admit(self, principal, bucket):
        self.calls.append(('admit', bucket))
        if self.admit_failure: raise self.admit_failure
    def call(self, name, principal, payload, *, deadline):
        self.calls.append((name, copy.deepcopy(payload)))
        if self.failure: raise self.failure
        return copy.deepcopy(self.values.get(name, SET))
    def source(self, *args, **kwargs):
        from kurafolio.web_v2.auth import RequestError
        raise RequestError('source_unavailable', 409)


@unittest.skipUnless(importlib.util.find_spec('fastapi') and importlib.util.find_spec('pwdlib'),
                     'Optional Web dependencies required')
class ImportHttpTests(unittest.TestCase):
    def client(self, profile='ingestion'):
        from fastapi.testclient import TestClient
        from kurafolio.web_v2.api import create_app
        settings = SimpleNamespace(schema_profile=profile, origin='http://localhost', host='localhost',
                                   secure=False, cookie_name='session')
        with patch('kurafolio.web_v2.api.Auth', FakeAuth): app = create_app(settings)
        client = TestClient(app, base_url='http://localhost')
        client.cookies.set('session', 'x'*43)
        self.addCleanup(client.close)
        return client, app.state.auth, app

    def request(self, client, case, **kwargs):
        method, path, _, body, _ = case
        return client.request(method, path, json=body, headers={'Origin':'http://localhost',
                              'X-CSRF-Token':'a'*64}, **kwargs)

    def test_ac_01_02_routes_success_only_gateway_functions_and_closed_payloads(self):
        from kurafolio.persistence.ingestion_schema import GATEWAY
        client, auth, _ = self.client()
        for case in CASES:
            response = self.request(client, case)
            self.assertEqual(response.status_code, case[4], response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store, private')
            self.assertEqual(auth.calls[-1][0], case[2])
            self.assertEqual(auth.calls[-2], ('admit', 'read' if case[0]=='GET' else 'control'))
        self.assertTrue({x[0] for x in auth.calls if x[0].endswith('_v1')} <= set(GATEWAY))
        self.assertFalse(any(x[0]=='budget' for x in auth.calls))
        for path in ('api.py', '../persistence/ingestion_store.py'):
            source = (Path(__file__).resolve().parents[1]/'src/kurafolio/web_v2'/path).read_text()
            for word in ('INSERT ', 'UPDATE ', 'DELETE ', 'TRUNCATE '): self.assertNotIn(word, source)

    def test_ac_01_unregistered_profiles_upload_and_source_routes(self):
        for profile in ('identity', 'sources', 'ingestion'):
            client, auth, _ = self.client(profile)
            if profile != 'ingestion':
                for case in CASES:
                    response = self.request(client, case)
                    self.assertEqual((response.status_code,response.json()['error']['code']), (404,'not_found'))
                self.assertEqual(auth.calls, [])
                self.assertFalse(any('/import-' in p for p in client.get('/api/v2/openapi.json').json()['paths']))
            response = client.put('/api/v2/import-sets/'+ID+'/members/'+ID+'/raw', content=b'ignored')
            self.assertEqual(response.status_code, 404)
            if profile in ('sources','ingestion'):
                response = client.get('/api/v2/sources')
                self.assertEqual((response.status_code,response.json()['error']['code']), (409,'source_unavailable'))

    def test_ac_01_openapi_frozen_schema_equality(self):
        client, _, _ = self.client()
        doc = client.get('/api/v2/openapi.json').json()
        root = Path(__file__).resolve().parents[1]/'docs/specs/imp-007-r7'
        wire = json.loads((root/'wire-contracts.json').read_text())
        codec = json.loads((root/'codec-schema.json').read_text())
        def rewrite(value):
            if isinstance(value,list): return [rewrite(x) for x in value]
            if not isinstance(value,dict): return value
            return {k: '#/components/schemas/'+v.split('#/$defs/')[1] if k=='$ref' else rewrite(v)
                    for k,v in value.items()}
        routes = [r for r in wire['routes'] if r['request'] != 'RAW_BINARY']
        self.assertEqual(len(routes),8)
        for route in routes:
            operation = doc['paths'][route['path']][route['method'].lower()]
            names = [route['response']]
            if route['request'] in ('Create','Decide','Confirm','Cancel'):
                names.append(route['request'])
                self.assertEqual(operation['requestBody']['content']['application/json']['schema'],
                                 {'$ref':'#/components/schemas/'+route['request']})
            self.assertEqual(operation['responses'][str(route['success_status'])]['content']['application/json']['schema'],
                             {'$ref':'#/components/schemas/'+route['response']})
            for name in names:
                self.assertEqual(doc['components']['schemas'][name], rewrite(wire['$defs'][name]))
        for name, schema in doc['components']['schemas'].items():
            if name in codec['$defs']: self.assertEqual(schema,rewrite(codec['$defs'][name]))

    def test_ac_03_auth_origin_csrf_query_and_stale_typed_refusals(self):
        from kurafolio.web_v2.auth import RequestError
        client, auth, _ = self.client()
        client.cookies.clear()
        for case in CASES: self.assertEqual(self.request(client,case).status_code,401)
        client.cookies.set('session','x'*43)
        for case in CASES:
            if case[0]=='GET': continue
            response = client.request(case[0],case[1],json=case[3],headers={'Origin':'http://wrong'})
            self.assertEqual(response.json()['error']['code'],'origin_rejected')
            response = client.request(case[0],case[1],json=case[3],headers={'Origin':'http://localhost'})
            self.assertEqual(response.json()['error']['code'],'csrf_rejected')
        for query in ('limit=0','limit=51','limit=1&limit=2','extra=1','cursor=bad'):
            self.assertEqual(client.get('/api/v2/import-sets?'+query).status_code,422)
        auth.failure = RequestError('import_stale',409)
        self.assertEqual(self.request(client,CASES[3]).status_code,409)

    def test_ac_05_error_codes_bad_server_values_and_invalid_bodies(self):
        from kurafolio.ingestion.contracts import ERROR_STATUS
        from kurafolio.web_v2.auth import RequestError
        client, auth, _ = self.client()
        for code,status in ERROR_STATUS.items():
            auth.failure = RequestError(code,status)
            response = self.request(client,CASES[2])
            self.assertEqual((response.status_code,response.json()['error']['code']),(status,code))
        auth.failure = None
        for value in (None, [], {}, {'page':PAGE,'next':None,'extra':'secret'},
                      {'page':dict(PAGE,next_cursor='secret'),'next':None}):
            auth.values['read_preview_v1']=value
            response = self.request(client,CASES[4])
            self.assertEqual((response.status_code,response.json()['error']['code']),(500,'internal_error'))
            self.assertNotIn('secret',response.text)
        response = client.post('/api/v2/import-sets',json=dict(CREATE,financial_value='10'),
                               headers={'Origin':'http://localhost','X-CSRF-Token':'a'*64})
        self.assertEqual(response.json()['error']['code'],'import_invalid')

    def test_ac_05_admission_and_404_never_read_body(self):
        from kurafolio.web_v2.auth import RequestError
        _, auth, app = self.client()
        auth.admit_failure = RequestError('import_busy',429)
        async def run(path):
            async def receive(): raise AssertionError('Body read before admission')
            messages=[]
            async def send(message): messages.append(message)
            await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST',
                'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'',
                'root_path':'','server':('localhost',80),'client':('127.0.0.1',1),
                'headers':[(b'host',b'localhost'),(b'cookie',b'session='+b'x'*43),
                           (b'origin',b'http://localhost'),(b'x-csrf-token',b'a'*64),
                           (b'content-type',b'application/json'),(b'content-length',b'1')]},receive,send)
            return messages[0]['status']
        self.assertEqual(asyncio.run(run('/api/v2/import-sets')),429)
        self.assertEqual(asyncio.run(run('/api/v2/import-sets/'+ID+'/members/'+ID+'/raw')),404)

    def test_ac_09_contract_error_map_and_profile_revision(self):
        from kurafolio.ingestion.contracts import ERROR_STATUS
        from kurafolio.persistence import ingestion_schema
        from kurafolio.persistence.context import Database
        from kurafolio.persistence.config import PostgresConfig
        wire = json.loads((Path(__file__).resolve().parents[1]/'docs/specs/imp-007-r7/wire-contracts.json').read_text())
        self.assertEqual(dict(ERROR_STATUS),wire['error_status'])
        database = Database(PostgresConfig('host=localhost port=5432 dbname=synthetic user=synthetic password=synthetic sslmode=disable'),schema_mode='ingestion')
        self.addCleanup(database.close)
        self.assertEqual(database.revision,ingestion_schema.REVISION)
