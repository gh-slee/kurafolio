"""AC-IMP-007E-05: strict server-output conversions with frozen wire schemas."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('pwdlib'), 'Optional Web dependencies required')
class ImportWireTests(unittest.TestCase):
    def setUp(self):
        from kurafolio.ingestion import cursors
        from kurafolio.web_v2 import import_wire
        from kurafolio.web_v2.auth import RequestError
        self.wire, self.error = import_wire, RequestError
        self.key = cursors.derive_key(b'x' * 32)
        self.page = {'id': '10000000-0000-4000-8000-000000000001',
                     'set_id': '10000000-0000-4000-8000-000000000002',
                     'set_revision': '1', 'state': 'READY', 'preview_digest': 'a' * 64,
                     'expires_at': {'tag': 'instant', 'token': '2026-11-23T20:00:00+00:00',
                                    'zone': None, 'fractional_digits': 0}, 'rows': [],
                     'can_confirm': True, 'review_digest': 'b' * 64, 'content_digest': 'c' * 64,
                     'accepted_generation': '0', 'mapping_generation': '0', 'control_generation': '0'}
        self.cursor = {'version': 1, 'user_id': self.page['id'], 'portfolio_id': self.page['set_id'],
                       'realm_digest': 'd' * 64, 'resource_id': self.page['id'],
                       'resource_revision': '1', 'review_digest': 'b' * 64, 'filter': None,
                       'after_key': '1', 'expires_at': '2026-11-23T20:00:00.000000+00:00'}

    def reject(self, value, method='preview_page'):
        with self.assertRaises(self.error) as caught:
            getattr(self.wire, method)(value, self.key)
        self.assertEqual(('internal_error', 500), (caught.exception.code, caught.exception.status))
        self.assertEqual(str(caught.exception), 'internal_error')

    def test_valid_preview_with_next_last_and_empty_page(self):
        """AC-IMP-007E-05."""
        from kurafolio.ingestion import cursors
        result = self.wire.preview_page({'page': self.page, 'next': self.cursor}, self.key)
        token = result.pop('next_cursor')
        self.assertEqual(result, self.page)
        self.assertEqual(cursors.verify(self.key, token), self.cursor)
        self.assertEqual(self.wire.preview_page({'page': self.page, 'next': None}, self.key),
                         dict(self.page, next_cursor=None))

    def test_closed_wrapper_page_and_cursor_failures(self):
        """AC-IMP-007E-05."""
        base = {'page': self.page, 'next': self.cursor}
        cases = [[], None, {'page': self.page}, {'next': None}, dict(base, next_cursor=None), dict(base, ok=True)]
        cases += [{'page': x, 'next': None} for x in ([], '', None)]
        cases += [{'page': dict(self.page, next_cursor=x), 'next': self.cursor} for x in ('token', None)]
        from kurafolio.ingestion import cursors
        cases.append({'page': dict(self.page, next_cursor=cursors.sign(self.key, self.cursor)), 'next': self.cursor})
        cases += [{'page': {k:v for k,v in self.page.items() if k != missing}, 'next': None} for missing in self.page]
        cases += [{'page': dict(self.page, **{k:None}), 'next': None} for k in ('next', 'extra')]
        cases += [{'page': self.page, 'next': x} for x in ('x', 1, [])]
        cases += [{'page': self.page, 'next': dict(self.cursor, **{k:v})} for k,v in (
            ('resource_id', self.page['set_id']), ('resource_revision', '2'), ('review_digest', 'e'*64), ('filter', 'READY'))]
        cases += [{'page': self.page, 'next': {k:v for k,v in self.cursor.items() if k != missing}} for missing in self.cursor]
        cases += [{'page': self.page, 'next': dict(self.cursor, extra=None)},
                  {'page': dict(self.page, rows=[{}]*51), 'next': None}]
        for value in cases:
            with self.subTest(value=value): self.reject(copy.deepcopy(value))

    def test_signing_limit_is_a_server_error(self):
        """AC-IMP-007E-05."""
        from kurafolio.ingestion.contracts import IngestionError
        with patch.object(self.wire.cursors, 'sign', side_effect=IngestionError('import_limit')):
            self.reject({'page': self.page, 'next': self.cursor})

    def test_set_list_valid_and_closed_failures(self):
        """AC-IMP-007E-05."""
        from kurafolio.ingestion import cursors
        cursor = dict(self.cursor, resource_id=None, resource_revision=None, review_digest=None)
        self.assertEqual(self.wire.set_list({'items': [], 'next': None}, self.key), {'items': [], 'next_cursor': None})
        result = self.wire.set_list({'items': [], 'next': cursor}, self.key)
        self.assertEqual(cursors.verify(self.key, result['next_cursor']), cursor)
        for value in ({'items': []}, {'next': None}, {'items': [], 'next': None, 'extra': 1},
                      {'items': [], 'next': []}, {'items': [{}], 'next': None}, None):
            self.reject(value, 'set_list')

    def test_pure_source(self):
        """AC-IMP-007E-05."""
        source = Path(self.wire.__file__).read_text()
        for token in ('logging', 'print(', 'SELECT ', 'INSERT ', 'UPDATE ', 'DELETE '):
            self.assertNotIn(token, source)
