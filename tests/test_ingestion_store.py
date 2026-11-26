"""AC-IMP-007E-02/05: bounded gateway calls, committed admission and fault mapping."""
import datetime
import importlib.util
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('sqlalchemy') and importlib.util.find_spec('pwdlib'),
                     'Optional PostgreSQL/Web dependencies required')
class IngestionStoreTests(unittest.TestCase):
    def setUp(self):
        from kurafolio.persistence.identity import Principal
        from kurafolio.persistence.ingestion_store import IngestionStore
        now=datetime.datetime.now(datetime.timezone.utc)
        self.principal=Principal('10000000-0000-4000-8000-000000000001',
            '10000000-0000-4000-8000-000000000002','Synthetic',1,'a'*64,
            now+datetime.timedelta(hours=1),now+datetime.timedelta(minutes=30),now,False,
            ('synthetic',1,'127.0.0.1',5432,'10000000-0000-4000-8000-000000000003',0))
        self.store=IngestionStore.__new__(IngestionStore)
        self.store.catalog_digest='b'*64
        self.calls=[];self.commits=0;self.rollbacks=0
        self.result={'ok':True,'value':{'synthetic':True}}
        self.faults=[]
        outer=self
        class Connection:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def begin(self):return self
            def execute(self,statement,parameters):
                outer.calls.append((str(statement),parameters))
                return SimpleNamespace(scalar_one=lambda:outer.result)
            def commit(self):
                outer.commits+=1
                if outer.faults: raise outer.faults.pop(0)
            def rollback(self):outer.rollbacks+=1
        self.store.database=SimpleNamespace(engine=SimpleNamespace(connect=lambda:Connection()))

    def call(self,name='read_set_v1',payload=None):
        return self.store.call(name,self.principal,payload or {'set_id':self.principal.user_id},deadline=time.monotonic()+20)

    def test_whitelist_principal_and_payload_reject_before_sql(self):
        """AC-IMP-007E-02."""
        from kurafolio.persistence.identity import IdentityError
        for name in ('admit_rate_v1','_effects_v1','read_set_v1; synthetic'):
            with self.assertRaises(IdentityError):self.call(name)
        with self.assertRaises(IdentityError):self.store.call('read_set_v1',None,{},deadline=time.monotonic()+20)
        self.assertEqual(self.calls,[])

    def test_arguments_timeout_casts_and_null_admission_commit(self):
        """AC-IMP-007E-02."""
        self.assertEqual(self.call(),{'synthetic':True})
        statement,parameters=self.calls[-1]
        self.assertIn('pg_catalog.int8',statement)
        self.assertEqual(json.loads(parameters['p5']),{'set_id':self.principal.user_id})
        self.assertEqual(json.loads(parameters['p3'])['epoch'],0)
        self.assertEqual(parameters['p4'],'b'*64)
        self.result={'ok':True,'value':None}
        self.assertIsNone(self.store.admit(self.principal,'read'))
        statement,parameters=self.calls[-1]
        self.assertIn('admit_rate_v1',statement)
        self.assertEqual(parameters['p5'],'read')
        self.assertEqual(self.commits,2)

    def test_refusals_commit_before_closed_mapping_and_no_diagnostics(self):
        """AC-IMP-007E-02."""
        from kurafolio.web_v2.auth import RequestError
        from kurafolio.persistence.identity import IdentityError
        from kurafolio.data_sources.lifecycle_v1 import SourceError
        for code,error,status in (('import_busy',RequestError,429),('source_unavailable',SourceError,409),
                                  ('not_found',IdentityError,404),('synthetic-secret-driver-text',IdentityError,503)):
            self.result={'ok':False,'code':code}
            with self.assertRaises(error) as caught:self.call()
            self.assertEqual(caught.exception.status,status)
            self.assertNotIn('synthetic-secret',str(caught.exception))
        self.assertEqual(self.commits,4)
        for result in ({'ok':True,'value':None},{'ok':True,'value':{},'extra':'secret'},
                       {'ok':False,'code':['secret']},{'value':{}},None):
            self.result=result
            with self.assertRaises(IdentityError):self.call()

    def test_commit_uncertainty_and_bounded_whole_transaction_retry(self):
        """AC-IMP-007E-02."""
        from sqlalchemy.exc import DBAPIError
        from kurafolio.web_v2.auth import RequestError
        from kurafolio.persistence.identity import IdentityError
        for name in ('create_set_v1','decide_set_v1','accept_preview_v1','cancel_set_v1','reserve_member_v1'):
            self.faults=[RuntimeError('synthetic-secret')]
            with self.assertRaises(RequestError) as caught:self.call(name)
            self.assertEqual((caught.exception.code,caught.exception.status),('import_commit_uncertain',503))
        self.faults=[RuntimeError('synthetic-secret')]
        with self.assertRaises(IdentityError):self.call()
        original=RuntimeError('synthetic-secret');original.sqlstate='40001'
        self.faults=[DBAPIError('secret-sql',{},original),DBAPIError('secret-sql',{},original)]
        before=self.commits
        self.assertEqual(self.call(),{'synthetic':True});self.assertEqual(self.commits-before,3)
        self.faults=[DBAPIError('secret-sql',{},original)]*3
        before=self.commits
        with self.assertRaises(IdentityError):self.call()
        self.assertEqual(self.commits-before,3)
