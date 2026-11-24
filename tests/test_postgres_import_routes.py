"""Opt-in AC-IMP-007E HTTP acceptance on fully migrated synthetic PostgreSQL."""
import copy
from dataclasses import replace
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('KURAFOLIO_INGESTION_TEST') == '1',
                     'Opt-in isolated ingestion PostgreSQL HTTP acceptance')
class ImportRoutesPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict
        from kurafolio.persistence.config import PostgresConfig
        cls.root = Path(__file__).resolve().parents[1]
        cls.directory = tempfile.TemporaryDirectory(prefix=os.environ.get('KURAFOLIO_TEST_ISOLATION','wl-imp-007e-')+'-')
        cls.path = Path(cls.directory.name)/'fixture'
        cls.addClassCleanup(cls.directory.cleanup)
        spec = importlib.util.spec_from_file_location('imp_007e_test_provisioner', cls.root/'scripts/postgres.py')
        provisioner = importlib.util.module_from_spec(spec); spec.loader.exec_module(provisioner)
        cls.provisioner = provisioner
        original = socket.socket
        port = os.environ.get('KURAFOLIO_TEST_PORT')
        class ReservedSocket(original):
            def bind(self, address):
                return super().bind(('127.0.0.1', int(port)) if port and address == ('127.0.0.1',0) else address)
        with patch.object(socket,'socket',ReservedSocket): provisioner.test_environment(cls.path,identity=True)
        cls.addClassCleanup(provisioner.cleanup_environment, cls.path/'test-config.json')
        cls.fixture = json.loads((cls.path/'test-config.json').read_text())
        options = conninfo_to_dict(PostgresConfig.from_secret_file(cls.path/'migration.conninfo').conninfo)
        cls.admin = dict(options,user='postgres',password=(cls.path/'bootstrap.secret').read_text())
        cls.worker_role = 'synthetic_ingestion_worker'
        with psycopg.connect(**cls.admin,autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(cls.worker_role)))
            conn.execute('CREATE ROLE synthetic_ungranted LOGIN')
        cls.key = (cls.path/'identity.key').read_bytes()
        cls.oracle = json.loads((cls.root/'tests/fixtures/ingestion/oracle.json').read_text())

    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo,conninfo_to_dict
        from fastapi.testclient import TestClient
        from kurafolio.data_sources.contract_v1 import CatalogSnapshot,Definition,Availability,installation_id,canonical,primitive
        from kurafolio.data_sources.compatibility_v1 import builtin_descriptors
        from kurafolio.data_sources.catalog_v1 import catalog_digest
        from kurafolio.persistence.config import PostgresConfig
        from kurafolio.persistence.context import Database,execute
        from kurafolio.persistence.source_migration import migrate_sources
        from kurafolio.persistence.ingestion_migration import migrate_ingestion
        from kurafolio.web_v2.config import Settings
        from kurafolio.web_v2.api import create_app
        self.execute = execute
        self.dbname = 'wl_test_imp007e_'+uuid.uuid4().hex[:12]
        self.admin_target = dict(self.admin,dbname=self.dbname)
        with psycopg.connect(**self.admin,autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(self.dbname),sql.Identifier(self.fixture['migration_role'])))
        self.configs = {kind:PostgresConfig(make_conninfo(**dict(conninfo_to_dict(
            PostgresConfig.from_secret_file(self.path/(kind+'.conninfo')).conninfo),dbname=self.dbname)),pool_size=1)
            for kind in ('migration','runtime','identity')}
        self.owner = Database(self.configs['migration'],schema_mode='sources'); self.addCleanup(self.owner.close)
        empty = CatalogSnapshot(1,'0',(),(),())
        migrate_sources(self.owner,self.fixture['runtime_role'],self.fixture['identity_role'],hashlib.sha256(self.key).hexdigest(),empty)
        plan = self.oracle['plan-first-use.json']; self.tenant,self.portfolio = plan['tenant_id'],plan['portfolio_id']
        from pwdlib import PasswordHash
        self.password = 'Synthetic import password 123'
        self.encoded = PasswordHash.recommended().hash(self.password)
        with self.owner.engine.begin() as conn:
            execute(conn,'INSERT INTO wl_pg.tenant_roots VALUES(:t,:p)',t=self.tenant,p=self.portfolio)
            execute(conn,'INSERT INTO wl_pg.portfolios(tenant_id,portfolio_id) VALUES(:t,:p)',t=self.tenant,p=self.portfolio)
            execute(conn,"""INSERT INTO wl_identity.users(id,portfolio_id,username,username_key,argon_hash,
                credential_incarnation,credential_epoch,created_at) SELECT :t,:p,'SyntheticAdmin','syntheticadmin',:h,
                incarnation,restore_epoch,clock_timestamp() FROM wl_pg.instance_state WHERE id=1""",t=self.tenant,p=self.portfolio,h=self.encoded)
            execute(conn,'UPDATE wl_identity.instance_auth_state SET bootstrap_closed=true,admin_user_id=:t WHERE id=1',t=self.tenant)
        migrate_ingestion(self.owner,self.fixture['runtime_role'],self.fixture['identity_role'],self.worker_role,
                          hashlib.sha256(self.key).hexdigest(),empty)
        descriptor = replace(builtin_descriptors(package_distribution='synthetic-import-tests',package_version='1',
            artifact_sha256='a'*64,execution_image_digest='b'*64,entry_point_target='kurafolio.source_builtin:registrations')[0],
            plugin_id='synthetic.qa',provider_id='synthetic.qa',adapter_id='synthetic.qa.csv',
            format_versions=('synthetic-csv-v1',))
        self.installation = installation_id(descriptor)
        self.catalog = CatalogSnapshot(1,'1',(Definition('synthetic.qa','synthetic.qa','Synthetic','Synthetic test',None),),
                                       (descriptor,),(Availability(self.installation,'ACTIVE','1'),))
        self.profile_digest = plan['pinned_sources'][0]['wrapper_profile_digest']
        wrappers = canonical([dict(installation_id=self.installation,profile_digest=self.profile_digest,
                                   projection='parser2-minimal-v1',format_versions=['synthetic-csv-v1'],image_digest='b'*64)])
        # Test-only metadata activation. It does not execute or attest an installed parser.
        # Keep every schema object, function, grant and constraint from the real migrations.
        with self.owner.engine.begin() as conn:
            execute(conn,"INSERT INTO wl_sources.installations VALUES(:id,'synthetic.qa','synthetic.qa','synthetic.qa.csv',:body,clock_timestamp())",
                    id=self.installation,body=canonical(primitive(descriptor)))
            execute(conn,'UPDATE wl_sources.catalog_state SET revision=1,digest=:d,bundle_bytes=:b,updated_at=clock_timestamp() WHERE id=1',
                    d=catalog_digest(self.catalog),b=canonical(primitive(self.catalog)))
            execute(conn,'INSERT INTO wl_ingestion.instance_state VALUES(1,:b,:d,:p,false)',
                    b=wrappers,d=hashlib.sha256(wrappers).hexdigest(),p='c'*64)
            execute(conn,"INSERT INTO wl_ingestion.workers VALUES(:id,:role,'synthetic-peer',true,1)",id=str(uuid.uuid4()),role=self.worker_role)
            for bucket in ('read','control','raw','storage'):
                execute(conn,'INSERT INTO wl_ingestion.instance_budgets VALUES(:b,clock_timestamp(),0,0,0,0)',b=bucket)
            execute(conn,'UPDATE wl_ingestion.instance_state SET ready=true WHERE id=1')
        self.settings = Settings(self.configs['identity'],self.configs['runtime'],self.key,'http://localhost',
                                 schema_profile='ingestion',source_catalog=self.catalog,worker_role=self.worker_role)
        self.app = create_app(self.settings)
        self.client = TestClient(self.app,base_url='http://localhost')
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.login_client(self.client,'syntheticadmin')
        realm = self.client.get('/api/v2/sources').json()['realm']
        common = dict(operation_id=str(uuid.uuid4()),expected_revision='0',expected_realm=realm)
        self.assertEqual(self.client.put('/api/v2/sources/synthetic.qa/capabilities/FILE_IMPORT',json=common|{
            'enabled':True,'installation_id':self.installation},headers=self.headers).status_code,200)
        response = self.client.post('/api/v2/source-connections',json=common|dict(operation_id=str(uuid.uuid4()),
            plugin_id='synthetic.qa',capability='FILE_IMPORT',installation_id=self.installation,display_label='Synthetic',parser_source_alias=None),headers=self.headers)
        self.assertEqual(response.status_code,201,response.text)
        self.connection = response.json()['resource']
        self.create_body = dict(operation_id=str(uuid.uuid4()),members=[dict(connection_id=self.connection['id'],
            installation_id=self.installation,format_version='synthetic-csv-v1',declared_bytes=None)])

    def login_client(self,client,username):
        from kurafolio.web_v2.auth import digest
        auth = self.app.state.auth
        anonymous = secrets.token_urlsafe(32); token = secrets.token_urlsafe(32)
        auth.store.call('issue_anonymous_v1',digest(anonymous))
        target = auth.store.call('login_target_v1',username)
        auth.store.call('login_commit_v1',target['user_id'],target['credential_version'],digest(anonymous),digest(token))
        client.cookies.set(self.settings.cookie_name,token)
        self.headers = {'Origin':self.settings.origin,'X-CSRF-Token':auth.csrf(token)}

    def scalar(self,statement):
        with self.owner.engine.begin() as conn: return self.execute(conn,statement).scalar_one()

    def create_set(self):
        response = self.client.post('/api/v2/import-sets',json=self.create_body,headers=self.headers)
        self.assertEqual(response.status_code,201,response.text)
        return response

    def seed_preview(self, *, rows=False, unique=False):
        import psycopg
        from kurafolio.ingestion import codec
        from kurafolio.persistence.identity import REALM_KEYS
        from test_postgres_migration import IngestionAppendOnlyPostgresTests as Seed
        plan = copy.deepcopy(self.oracle['plan-first-use.json'])
        minimal = next(copy.deepcopy(v) for v in self.oracle.values() if type(v) is dict and
                       'provenance' in v and codec.digest(v) == plan['inputs'][0]['stage_digest'])
        old_pin = plan['pinned_sources'][0]
        decisions = next(copy.deepcopy(v) for v in self.oracle.values() if type(v) is dict and
                         'operation_id' in v and 'mappings' in v and codec.digest(v)==plan['decision_digest'])
        replacements = {old_pin['installation_id']:self.installation,old_pin['connection_id']:self.connection['id']}
        if unique:
            replacements.update({value:str(uuid.uuid4()) for value in (plan['set_id'],plan['preview_id'],plan['inputs'][0]['member_id'])})
        def rebind(value):
            if isinstance(value,dict): return {k:rebind(v) for k,v in value.items()}
            if isinstance(value,list): return [rebind(v) for v in value]
            return replacements.get(value,value) if type(value) is str else value
        plan, minimal, decisions = rebind(plan), rebind(minimal), rebind(decisions)
        plan['decision_digest']=codec.digest(decisions)
        minimal['provenance']['installation_id']=self.installation
        minimal['provenance']['wrapper_profile_digest']=self.profile_digest
        plan['inputs'][0]['stage_digest']=codec.digest(minimal)
        plan['pinned_sources'][0].update(connection_version=self.connection['connection_version'],connection_generation='0')
        principal=self.app.state.auth.resolve(self.client.cookies.get(self.settings.cookie_name))
        realm=dict(zip(REALM_KEYS,principal.realm))
        plan.update(incarnation=realm['incarnation'],restore_epoch=str(realm['epoch']),realm_digest=codec.digest(realm))
        plan['expires_at']['token']=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=12)).replace(microsecond=0).isoformat()
        document=copy.deepcopy(self.oracle['mixed-set-review.json'])
        document.update(id=plan['preview_id'],set_id=plan['set_id'])
        if not rows: document['content']['rows']=[]
        seed=Seed._plan_seed(plan,decisions=decisions,stages={codec.digest(minimal):minimal})+Seed._preview_seed(plan)
        if unique:
            first,rest=seed.split(';',1)
            seed=first+' ON CONFLICT DO NOTHING;'+rest
        # Only test data bypasses insertion-transition checks; no schema/ACL drift.
        with psycopg.connect(**self.admin_target) as conn:
            conn.execute('SET LOCAL session_replication_role=replica')
            conn.execute(seed,prepare=False)
            conn.execute('UPDATE wl_ingestion.previews SET review_bytes=%s,review_digest=%s',
                         (codec.encode(document),codec.digest(document)))
        return plan,document

    def test_ac_01_02_ready_and_no_operator_verifiers(self):
        """AC-IMP-007E-01, AC-IMP-007E-02."""
        from kurafolio.persistence.identity import role_inventory
        def inventory(database,*,gateway,**kwargs):
            self.assertTrue(gateway);return role_inventory(database,gateway=gateway,**kwargs)
        with patch('kurafolio.persistence.ingestion_migration.verify_inventory',side_effect=AssertionError()), \
             patch('kurafolio.persistence.migration._operator',side_effect=AssertionError()), \
             patch('kurafolio.persistence.source_migration.verify_inventory',side_effect=AssertionError()), \
             patch('kurafolio.web_v2.auth.role_inventory',side_effect=inventory):
            self.assertEqual(self.client.get('/readyz').status_code,200)
        with self.owner.engine.begin() as conn:
            self.execute(conn,'GRANT CREATE ON SCHEMA public TO '+self.fixture['runtime_role'])
        self.assertEqual(self.client.get('/readyz').status_code,503)

    def test_ac_02_role_configuration_and_gateway_grant_drift(self):
        """AC-IMP-007E-02."""
        from kurafolio.web_v2.api import create_app
        from kurafolio.persistence.identity import IdentityError
        for role in (self.fixture['runtime_role'],self.fixture['identity_role'],'synthetic_ungranted'):
            with self.assertRaises(IdentityError): create_app(replace(self.settings,worker_role=role))
        with self.assertRaises(IdentityError):
            create_app(replace(self.settings,identity=self.configs['runtime'],financial=self.configs['identity']))
        with self.owner.engine.begin() as conn:
            self.execute(conn,'GRANT SELECT ON wl_ingestion.sets TO '+self.fixture['identity_role'])
        self.assertEqual(self.client.get('/readyz').status_code,503)

    def test_ac_03_07_create_cancel_replay_conflict_and_stale(self):
        """AC-IMP-007E-03, AC-IMP-007E-07."""
        first=self.create_set();again=self.create_set();self.assertEqual(first.content,again.content)
        changed=copy.deepcopy(self.create_body);changed['members'][0]['declared_bytes']=1
        response=self.client.post('/api/v2/import-sets',json=changed,headers=self.headers)
        self.assertEqual(response.json()['error']['code'],'import_operation_conflict')
        sid=first.json()['id']; path='/api/v2/import-sets/'+sid
        self.assertEqual(self.client.get(path).json(),first.json())
        body=dict(operation_id=str(uuid.uuid4()),expected_set_revision='2')
        self.assertEqual(self.client.post(path+'/cancel',json=body,headers=self.headers).json()['error']['code'],'import_stale')
        body['expected_set_revision']='1'
        cancelled=self.client.post(path+'/cancel',json=body,headers=self.headers)
        self.assertEqual(cancelled.status_code,200,cancelled.text)
        self.assertEqual(cancelled.content,self.client.post(path+'/cancel',json=body,headers=self.headers).content)
        body['expected_set_revision']='2'
        self.assertEqual(self.client.post(path+'/cancel',json=body,headers=self.headers).json()['error']['code'],'import_operation_conflict')
        self.assertIsNone(cancelled.json()['receipt_id'])  # sql-appendix: null before COMMITTED.
        receipt_id=str(self.scalar("SELECT id FROM wl_ingestion.receipts WHERE operation_kind='CANCEL'"))
        receipt=self.client.get('/api/v2/import-receipts/'+receipt_id)
        self.assertEqual(receipt.status_code,200,receipt.text)

    def test_ac_05_preview_paging_and_signed_cursors(self):
        """AC-IMP-007E-05."""
        from kurafolio.ingestion import codec
        plan,document=self.seed_preview(rows=True);path='/api/v2/import-previews/'+plan['preview_id']
        rows=[];cursor=None
        while True:
            response=self.client.get(path,params={'limit':1,**({'cursor':cursor} if cursor else {})})
            self.assertEqual(response.status_code,200,response.text)
            value=codec.validate(response.json(),'PreviewPage');rows.extend(value['rows'])
            self.assertNotIn('page',value);self.assertNotIn('next',value)
            cursor=value['next_cursor']
            if cursor is None: break
        self.assertEqual(rows,document['content']['rows'])
        one=self.client.get(path+'?limit=50');self.assertIsNone(one.json()['next_cursor'])
        cursor=self.client.get(path+'?limit=1').json()['next_cursor']
        other,_=self.seed_preview(rows=True,unique=True)
        response=self.client.get('/api/v2/import-previews/'+other['preview_id'],params={'cursor':cursor})
        self.assertEqual((response.status_code,response.json()['error']['code']),(409,'import_stale'))
        bad=cursor[:-1]+('A' if cursor[-1]!='A' else 'B')
        self.assertEqual(self.client.get(path,params={'cursor':bad}).json()['error']['code'],'import_invalid')

    def test_ac_07_confirm_and_decisions_replay(self):
        """AC-IMP-007E-07."""
        from kurafolio.ingestion import codec
        plan,_=self.seed_preview();path='/api/v2/import-previews/'+plan['preview_id']+'/confirm'
        body=dict(operation_id=str(uuid.uuid4()),preview_digest=codec.digest(plan))
        response=self.client.post(path,json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.content,self.client.post(path,json=body,headers=self.headers).content)
        receipt=self.client.get('/api/v2/import-receipts/'+response.json()['id'])
        self.assertEqual(receipt.content,response.content)
        body['preview_digest']='0'*64
        self.assertEqual(self.client.post(path,json=body,headers=self.headers).json()['error']['code'],'import_operation_conflict')

    def test_ac_03_07_decisions_and_cancel_positive_stale_replay_conflict(self):
        """AC-IMP-007E-03, AC-IMP-007E-07."""
        plan,_=self.seed_preview()
        path='/api/v2/import-sets/'+plan['set_id']
        revision=int(plan['expected_set_revision'])
        body=dict(set_id=plan['set_id'],decisions=dict(version=1,operation_id=str(uuid.uuid4()),
            expected_set_revision=str(revision-1),mappings=[],new_entities=[],authorities=[],parents=[]))
        stale=self.client.put(path+'/decisions',json=body,headers=self.headers)
        self.assertEqual(stale.json()['error']['code'],'import_stale')
        cancelled=self.client.post(path+'/cancel',json=dict(operation_id=str(uuid.uuid4()),
            expected_set_revision=str(revision-1)),headers=self.headers)
        self.assertEqual(cancelled.json()['error']['code'],'import_stale')
        body['decisions']['expected_set_revision']=str(revision)
        first=self.client.put(path+'/decisions',json=body,headers=self.headers)
        self.assertEqual(first.status_code,202,first.text)
        self.assertEqual(first.content,self.client.put(path+'/decisions',json=body,headers=self.headers).content)
        before=self.scalar('SELECT count(*) FROM wl_ingestion.receipts')
        body['decisions']['expected_set_revision']=str(revision+1)
        response=self.client.put(path+'/decisions',json=body,headers=self.headers)
        self.assertEqual(response.json()['error']['code'],'import_operation_conflict')
        self.assertEqual(before,self.scalar('SELECT count(*) FROM wl_ingestion.receipts'))

    def test_ac_03_cross_tenant_and_revoked_session_refusals(self):
        """AC-IMP-007E-03."""
        from fastapi.testclient import TestClient
        plan,_=self.seed_preview()
        user,portfolio=str(uuid.uuid4()),str(uuid.uuid4())
        with self.owner.engine.begin() as conn:
            self.execute(conn,'INSERT INTO wl_pg.tenant_roots VALUES(:t,:p)',t=user,p=portfolio)
            self.execute(conn,'INSERT INTO wl_pg.portfolios(tenant_id,portfolio_id) VALUES(:t,:p)',t=user,p=portfolio)
            self.execute(conn,"""INSERT INTO wl_identity.users(id,portfolio_id,username,username_key,argon_hash,
                credential_incarnation,credential_epoch,created_at) SELECT :t,:p,'SyntheticOther','syntheticother',:h,
                incarnation,restore_epoch,clock_timestamp() FROM wl_pg.instance_state WHERE id=1""",t=user,p=portfolio,h=self.encoded)
        with TestClient(self.app,base_url='http://localhost') as other:
            self.login_client(other,'syntheticother')
            paths=[('GET','/api/v2/import-sets/'+plan['set_id'],None),
                   ('GET','/api/v2/import-previews/'+plan['preview_id'],None),
                   ('POST','/api/v2/import-previews/'+plan['preview_id']+'/confirm',
                    dict(operation_id=str(uuid.uuid4()),preview_digest='a'*64)),
                   ('POST','/api/v2/import-sets/'+plan['set_id']+'/cancel',
                    dict(operation_id=str(uuid.uuid4()),expected_set_revision=plan['expected_set_revision'])),
                   ('PUT','/api/v2/import-sets/'+plan['set_id']+'/decisions',
                    dict(set_id=plan['set_id'],decisions=dict(version=1,operation_id=str(uuid.uuid4()),
                    expected_set_revision=plan['expected_set_revision'],mappings=[],new_entities=[],authorities=[],parents=[])))]
            for method,path,body in paths:
                response=other.request(method,path,json=body,headers=self.headers)
                self.assertEqual((response.status_code,response.json()['error']['code']),(404,'not_found'))
            self.assertEqual(str(self.scalar('SELECT revision FROM wl_ingestion.sets')),plan['expected_set_revision'])
            with self.owner.engine.begin() as conn:
                self.execute(conn,'UPDATE wl_identity.users SET credential_version=credential_version+1 WHERE id=:t',t=user)
            source=other.get('/api/v2/sources');imports=other.get('/api/v2/import-sets')
            self.assertEqual((imports.status_code,imports.json()['error']['code']),
                             (source.status_code,source.json()['error']['code']))

    def test_ac_05_set_list_paging_and_limits(self):
        """AC-IMP-007E-05."""
        self.create_set();self.create_body['operation_id']=str(uuid.uuid4());self.create_set()
        one=self.client.get('/api/v2/import-sets?limit=1').json()
        two=self.client.get('/api/v2/import-sets',params={'cursor':one['next_cursor'],'limit':1}).json()
        self.assertIsNone(two['next_cursor']);self.assertNotEqual(one['items'][0]['id'],two['items'][0]['id'])
        self.assertEqual(self.client.get('/api/v2/import-sets',params={'cursor':one['next_cursor'],'state':'READY'}).json()['error']['code'],'import_invalid')
        for limit in (0,51): self.assertEqual(self.client.get('/api/v2/import-sets',params={'limit':limit}).status_code,422)

    def test_ac_05_sql_rate_admission_read_and_control(self):
        """AC-IMP-007E-05."""
        for index in range(60): self.assertEqual(self.client.get('/api/v2/import-sets').status_code,200,index)
        self.assertEqual(self.client.get('/api/v2/import-sets').json()['error']['code'],'import_busy')
        for index in range(30): self.create_set()
        response=self.client.post('/api/v2/import-sets',json=self.create_body,headers=self.headers)
        self.assertEqual((response.status_code,response.json()['error']['code']),(429,'import_busy'))

    def test_ac_02_inactive_readiness_and_outstanding_set_quota(self):
        """AC-IMP-007E-02."""
        with self.owner.engine.begin() as conn:
            self.execute(conn,'UPDATE wl_ingestion.instance_state SET ready=false WHERE id=1')
        self.assertEqual(self.client.get('/readyz').status_code,200)
        response=self.client.get('/api/v2/import-sets')
        self.assertEqual((response.status_code,response.json()['error']['code']),(503,'instance_not_ready'))
        with self.owner.engine.begin() as conn:
            self.execute(conn,'UPDATE wl_ingestion.instance_state SET ready=true WHERE id=1')
        for index in range(8):
            self.create_body['operation_id']=str(uuid.uuid4());self.create_set()
        self.create_body['operation_id']=str(uuid.uuid4())
        response=self.client.post('/api/v2/import-sets',json=self.create_body,headers=self.headers)
        self.assertEqual((response.status_code,response.json()['error']['code']),(413,'import_limit'))
