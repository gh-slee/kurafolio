"""Independent literal bases and acceptance checks for the pure review builder."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from kurafolio.ingestion.codec import digest, encode, validate
from kurafolio.ingestion.mapping import MappingIndex
from kurafolio.ingestion.reconciliation import financial_projection, source_revision_key

ORACLE = json.loads((Path(__file__).parent / 'fixtures/ingestion/oracle.json').read_text())
RESOURCES = ('inputs', 'entities', 'mappings', 'revisions', 'heads', 'authorities', 'decisions', 'context')
CASES = {
    'first-use': ('plan-first-use.json', 'review-parser2-ready.json', 'decisions-first-use.json', None),
    'native-first-use': ('plan-native-first-use.json', 'review-native-ready.json', 'decisions-native-first-use.json', None),
    'metadata-native': ('metadata-native-plan.json', 'review-metadata-native-ready.json', 'metadata-native-decisions.json', None),
    'mixed-set': ('mixed-set-plan.json', 'mixed-set-review.json', 'mixed-set-decisions.json', None),
    'snapshot-seed-t2': ('snapshot-seed-t2-plan.json', 'snapshot-seed-t2-review.json', 'snapshot-seed-t2-decisions.json', None),
    'snapshot-historical-t1': ('snapshot-historical-t1-plan.json', 'snapshot-historical-t1-review.json', 'snapshot-historical-t1-decisions.json', 'snapshot-seed-t2-plan.json'),
    **{c: (c + '-plan.json', c + '-review.json', c + '-decisions.json', 'plan-native-first-use.json' if c.endswith('existing_issuer') else 'plan-first-use.json') for c in (
        'branch-fresh_duplicate_only', 'branch-new_equal_meaning_revision',
        'branch-equal_value_explicit_correction', 'branch-mapping_only_existing_issuer')},
    'authority-only': ('authority-only-plan.json', 'authority-only-review.json', 'authority-only-decisions.json', 'plan-first-use.json'),
}
INITIALS = {'first-use': 'review-parser2-initial.json', 'native-first-use': 'review-native-initial.json',
            'metadata-native': 'review-metadata-native-initial.json'}


def _minimal(input_):
    return next(v for v in ORACLE.values() if isinstance(v, dict) and 'provenance' in v
                and 'accounts' in v and digest(v) == input_['stage_digest'])


def _bodies(value):
    if isinstance(value, dict):
        if isinstance(value.get('id'), dict) and 'value' in value['id']:
            yield value
        for v in value.values():
            yield from _bodies(v)
    elif isinstance(value, list):
        for v in value:
            yield from _bodies(v)


def oracle_basis(case, *, page_size=50, order=None, initial=False):
    """Build trusted pages from literals, without importing the implementation."""
    plan_name, review_name, decisions_name, baseline_name = CASES[case]
    plan = deepcopy(ORACLE[plan_name])
    review = deepcopy(ORACLE[INITIALS[case] if initial else review_name])
    rows = {r: [] for r in RESOURCES}
    for input_ in plan['inputs']:
        rows['inputs'].append({'kind': 'input', 'id': input_['member_id'],
                              'digest': input_['stage_digest'], 'minimal': deepcopy(_minimal(input_))})
    rows['context'] = [{'kind': 'prepare_context', **{k: deepcopy(plan[k]) for k in (
        'tenant_id', 'portfolio_id', 'set_id', 'realm_digest', 'incarnation', 'restore_epoch', 'pinned_sources')},
        'set_expires_at': plan['expires_at']}]
    if not initial:
        decisions = deepcopy(ORACLE[decisions_name])
        rows['decisions'] = [{'kind': 'decisions_header', 'decision_revision': str(int(plan['expected_set_revision']) - 1),
            'digest': digest(decisions), **{k: decisions[k] for k in ('version', 'operation_id', 'expected_set_revision')},
            'counts': {k: len(decisions[k]) for k in ('authorities', 'mappings', 'new_entities', 'parents')}}]
        rows['decisions'] += [{'kind': 'decision_item', 'collection': k, 'ordinal': i, 'value': v}
                             for k in ('authorities', 'mappings', 'new_entities', 'parents')
                             for i, v in enumerate(decisions[k])]
        bodies = list(_bodies(ORACLE))
        for m in decisions['mappings']:
            if m['target']['mode'] == 'existing':
                body = next(b for b in bodies if b['id']['value'] == m['target']['id'] and digest(b) == m['target']['version'])
                rows['entities'].append({'kind': 'entity', 'candidate': {**m, 'body': deepcopy(body)}})
    if baseline_name and not initial:
        baseline = ORACLE[baseline_name]
        for input_ in baseline['inputs']:
            minimal = _minimal(input_)
            member = input_['member_id']
            scope = {k: baseline[k] for k in ('tenant_id', 'portfolio_id')}
            scope['connection_id'] = next(p['connection_id'] for p in baseline['pinned_sources'] if p['member_id'] == member)
            index = MappingIndex(baseline['mappings'], member)
            for fact in baseline['facts']:
                collection, local = fact['collection'], fact['local_id']
                typed = minimal['membership'] if collection == 'membership' else minimal[collection][int(local)]
                key = source_revision_key(minimal, collection, local, **scope)
                assert digest(financial_projection(minimal, collection, local, index, scope=scope)) == fact['financial_digest']
                for vector in ORACLE['key-preimages.json']['vectors']:
                    if vector['preimage'] == key['source']:
                        assert vector['sha256'] == digest(key['source'])
                claim = {k: v for k, v in key['source'].items() if k not in ('version', 'tenant_id', 'portfolio_id', 'connection_id', 'collection')}
                claim['revision'] = key['revision']
                rows['revisions'].append({'kind': 'revision', 'revision': {
                    'id': fact['accepted_revision_id'], 'input_id': 'f0000000-0000-4000-8000-000000000001',
                    'collection': collection, 'local_id': local, 'source': claim, 'source_key_digest': digest(key['source']),
                    'financial_digest': fact['financial_digest'], 'economic_group_id': fact['economic_group_id'],
                    'parent_revision_id': None, 'accepted_change': 'original', 'typed': deepcopy(typed)}})
        rows['heads'] = [{'kind': 'head', 'head': deepcopy(h)} for h in baseline['heads']]
        incoming = plan['inputs'][0]['member_id']
        rows['mappings'] = [{'kind': 'mapping', 'mapping': {**deepcopy(m), 'member_id': incoming,
                            'target': {**m['target'], 'mode': 'existing'}}} for m in baseline['mappings']]
    if case == 'authority-only':
        prestate = ORACLE['authority-only-prestate.json']
        peer = deepcopy(prestate['peer_revision'])
        rows['revisions'].append({'kind': 'revision', 'revision': peer})
        key = {'version': 1, 'tenant_id': plan['tenant_id'], 'portfolio_id': plan['portfolio_id'], 'economic_group_id': peer['economic_group_id']}
        rows['heads'].append({'kind': 'head', 'head': {'kind': 'activity', 'key_digest': digest(key),
            'prior_revision_id': None, 'next_revision_id': peer['id'], 'complete_base_id': None, 'active': True}})
        rows['authorities'] = [{'kind': 'authority', 'authority': deepcopy(prestate['prior_authority']),
            'link_id': prestate['prior_link_id'], 'link_revision': prestate['prior_link_revision']}]
    pins = {'version': 1, 'job_id': 'a0000000-0000-4000-8000-000000000001', 'fence': '1',
        'set_revision': review['set_revision'] if initial else str(int(review['set_revision']) - 1),
        **{k: review[k] for k in ('accepted_generation', 'mapping_generation', 'control_generation')}}
    pages = []
    for resource, resource_rows in rows.items():
        chunks = [resource_rows[i:i + page_size] for i in range(0, len(resource_rows), page_size)] or [[]]
        for i, chunk in enumerate(chunks):
            cursor = None if i == len(chunks) - 1 else {k: pins[k] for k in (
                'job_id', 'fence', 'set_revision', 'accepted_generation', 'mapping_generation', 'control_generation')}
            if cursor is not None:
                cursor.update(resource=resource, after_key=str(i), expires_at=review['expires_at'])
            pages.append({**pins, 'resource': resource, 'rows': chunk, 'next_cursor': cursor})
    if order == 'reversed':
        pages.reverse()
    elif order == 'interleaved':
        pages = pages[::2] + pages[1::2]
    slots = {}
    if initial:
        for row in review['content']['rows']:
            if row['type'] == 'target_candidate' and row['candidate']['target']['mode'] == 'proposed':
                c = row['candidate']
                slots['entity', c['member_id'], c['entity_kind'], c['local_id']] = c['target']['id']
    else:
        for fact in plan['facts']:
            if fact['action'] != 'duplicate':
                slots['revision', fact['member_id'], fact['collection'], fact['local_id']] = fact['accepted_revision_id']
            if fact['action'] == 'append' and fact['economic_group_id'] is not None:
                slots['group', fact['member_id'], 'records', fact['local_id']] = fact['economic_group_id']
    return pages, review, None if initial else plan, slots


def replace_minimal(pages, minimal, member=None):
    member = member or next(r['id'] for p in pages if p['resource'] == 'inputs' for r in p['rows'])
    for page in pages:
        if page['resource'] == 'inputs':
            for row in page['rows']:
                if row['id'] == member:
                    row.update(minimal=deepcopy(minimal), digest=digest(minimal))
    return pages


def store_decisions(pages, decisions):
    pages = deepcopy(pages)
    template = next(p for p in pages if p['resource'] == 'decisions')
    pages = [p for p in pages if p['resource'] != 'decisions']
    rows = []
    if decisions is not None:
        rows.append({'kind': 'decisions_header', 'decision_revision': template['set_revision'],
            'digest': digest(decisions), **{k: decisions[k] for k in ('version', 'operation_id', 'expected_set_revision')},
            'counts': {k: len(decisions[k]) for k in ('authorities', 'mappings', 'new_entities', 'parents')}})
        rows += [{'kind': 'decision_item', 'collection': k, 'ordinal': i, 'value': v}
                 for k in ('authorities', 'mappings', 'new_entities', 'parents') for i, v in enumerate(decisions[k])]
    pages.append({**template, 'rows': rows, 'next_cursor': None})
    return pages


def sequential_allocator():
    count = 0
    def allocate(slot):
        nonlocal count
        count += 1
        return {'entity': 'b1000000', 'revision': 'b2000000', 'group': 'b3000000'}[slot.purpose] + '-0000-4000-8000-' + format(count, '012x')
    return allocate


def proposed_ready(pages):
    from kurafolio.ingestion.review_bundle import build_review_bundle
    preview = 'a1000000-0000-4000-8000-000000000001'
    initial = build_review_bundle(store_decisions(pages, None), preview_id=preview, allocate_id=sequential_allocator())
    candidates = [r['candidate'] for r in initial['review']['content']['rows'] if r['type'] == 'target_candidate' and r['candidate']['target']['mode'] == 'proposed']
    decisions = {'version': 1, 'operation_id': 'a2000000-0000-4000-8000-000000000001',
        'expected_set_revision': pages[0]['set_revision'],
        'mappings': [{k: c[k] for k in ('member_id', 'entity_kind', 'local_id', 'target')} for c in candidates],
        'new_entities': [{'member_id': c['member_id'], 'kind': c['entity_kind'], 'local_id': c['local_id'],
                          'id': c['target']['id'], 'version': c['target']['version']} for c in candidates],
        'authorities': [], 'parents': []}
    return store_decisions(pages, decisions)


class OracleBasisTests(unittest.TestCase):
    def test_every_oracle_basis_is_expressible(self):
        """AC-IMP-007P-01: every planned vector has independent valid basis pages."""
        for case in CASES:
            for initial in (False, True) if case in INITIALS else (False,):
                with self.subTest(case=case, initial=initial):
                    pages, _, _, _ = oracle_basis(case, page_size=1, initial=initial)
                    for page in pages:
                        validate(page, 'BasisPage', namespace='wire')


class ReviewBundleTests(unittest.TestCase):
    def build_case(self, case, **options):
        from kurafolio.ingestion.review_bundle import build_review_bundle
        pages, review, plan, slots = oracle_basis(case, **options)
        requested = []
        def allocate(slot):
            self.assertNotIn(slot, requested)
            requested.append(slot)
            return slots[slot]
        actual = build_review_bundle(pages, preview_id=review['id'], allocate_id=allocate)
        self.assertEqual(set(slots), set(requested))
        self.assertEqual(encode(review), encode(actual['review']))
        self.assertEqual(encode(plan), encode(actual['plan']))
        return actual

    def test_oracle_vectors(self):
        """AC-IMP-007P-01: every READY and initial literal matches byte for byte."""
        for case in CASES:
            for initial in (False, True) if case in INITIALS else (False,):
                with self.subTest(case=case, initial=initial):
                    self.build_case(case, initial=initial)


class ReviewBundleSafetyTests(unittest.TestCase):
    def build(self, pages, allocate=None):
        from kurafolio.ingestion.review_bundle import build_review_bundle
        return build_review_bundle(pages, preview_id='a1000000-0000-4000-8000-000000000001',
                                   allocate_id=allocate or sequential_allocator())

    def refusal(self, pages, code, field, allocate=None):
        from kurafolio.ingestion.contracts import IngestionError
        with self.assertRaises(IngestionError) as caught:
            self.build(pages, allocate)
        self.assertEqual((code, field), (caught.exception.code, caught.exception.field))

    def test_integrity_refusals(self):
        """AC-IMP-007P-05: incomplete or untrusted bases return fixed refusals."""
        original = oracle_basis('first-use')[0]
        for resource in RESOURCES:
            with self.subTest(missing=resource):
                self.refusal([p for p in original if p['resource'] != resource], 'import_invalid', '$.basis.' + resource)
            pages = deepcopy(original)
            page = next(p for p in pages if p['resource'] == resource)
            pages.append(deepcopy(page))
            with self.subTest(two_terminals=resource):
                self.refusal(pages, 'import_invalid', '$.basis.' + resource)
            pages = deepcopy(original)
            page = next(p for p in pages if p['resource'] == resource)
            if page['rows']:
                page['rows'].append(deepcopy(page['rows'][0]))
                with self.subTest(duplicate=resource):
                    self.refusal(pages, 'import_invalid', '$.basis.' + resource)
        pages = deepcopy(original)
        pages[0]['rows'][0]['digest'] = '0' * 64
        self.refusal(pages, 'import_stale', '$.basis.inputs')
        for pin in ('job_id', 'fence', 'set_revision', 'accepted_generation', 'mapping_generation', 'control_generation'):
            pages = deepcopy(original)
            pages[-1][pin] = 'a3000000-0000-4000-8000-000000000001' if pin == 'job_id' else '4'
            with self.subTest(pin=pin):
                self.refusal(pages, 'import_stale', '$.basis')
        pages = deepcopy(original)
        next(p for p in pages if p['resource'] == 'context')['rows'][0]['pinned_sources'] = []
        self.refusal(pages, 'import_invalid', '$.basis.context')
        for mutate in ('unknown_member', 'unknown_entity', 'digest', 'ordinal', 'count'):
            pages = deepcopy(original)
            d = deepcopy(ORACLE['decisions-first-use.json'])
            if mutate == 'unknown_member':
                d['mappings'][0]['member_id'] = 'a4000000-0000-4000-8000-000000000001'
            elif mutate == 'unknown_entity':
                d['mappings'][0]['local_id'] = '99'
            pages = store_decisions(pages, d)
            rows = next(p for p in pages if p['resource'] == 'decisions')['rows']
            if mutate == 'digest':
                rows[0]['digest'] = '0' * 64
            elif mutate == 'ordinal':
                rows[1]['ordinal'] = 9
            elif mutate == 'count':
                rows[0]['counts']['mappings'] += 1
            self.refusal(pages, 'import_invalid', '$.decisions' if mutate.startswith('unknown') else '$.basis.decisions')
        for value in ('BAD', original[0]['rows'][0]['id'], 'a1000000-0000-4000-8000-000000000001'):
            self.refusal(original, 'import_conflict', '$.ids', lambda slot: value)
        self.refusal(original, 'import_conflict', '$.ids', lambda slot: 'b1000000-0000-4000-8000-000000000001')
        pages = oracle_basis('branch-fresh_duplicate_only')[0]
        next(p for p in pages if p['resource'] == 'heads')['rows'][0]['head']['next_revision_id'] = 'a5000000-0000-4000-8000-000000000001'
        self.refusal(pages, 'import_invalid', '$.basis.revisions')

    def test_page_and_delivery_determinism(self):
        """AC-IMP-007P-04: page sizes, delivery order and repeat builds cannot change bytes."""
        for case in CASES:
            for initial in (False, True) if case in INITIALS else (False,):
                baseline = encode(ReviewBundleTests().build_case(case, initial=initial))
                for size in (1, 7, 50):
                    for order in (None, 'reversed', 'interleaved'):
                        with self.subTest(case=case, initial=initial, size=size, order=order):
                            for _ in range(2):
                                self.assertEqual(baseline, encode(ReviewBundleTests().build_case(case, initial=initial, page_size=size, order=order)))

    def test_no_ambient_io(self):
        """AC-IMP-007P-06: static imports and runtime traps prohibit ambient inputs."""
        import ast
        import builtins
        import io
        import os
        import random
        import secrets
        import socket
        import time
        import uuid
        from contextlib import ExitStack
        from unittest.mock import patch
        from kurafolio.ingestion import review_bundle
        tree = ast.parse(Path(review_bundle.__file__).read_text())
        allowed = {'__future__', 'collections', 'copy', 'dataclasses', 'functools', 'itertools', 'operator', 'typing',
                   'approval', 'codec', 'contracts', 'mapping', 'reconciliation'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(n.name in allowed for n in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed)
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, {'open', 'eval', 'exec', 'compile', '__import__'})
        cases = [(case, initial, oracle_basis(case, initial=initial)) for case in CASES
                 for initial in ((False, True) if case in INITIALS else (False,))]
        def forbidden(*args, **kwargs):
            raise AssertionError('Ambient input read')
        class NoEnvironment(dict):
            __getitem__ = get = __iter__ = __contains__ = keys = items = values = forbidden
        with ExitStack() as stack:
            for module, names in ((time, ('time', 'time_ns', 'monotonic', 'perf_counter')),
                    (random, ('random', 'getrandbits')), (os, ('urandom', 'getenv')),
                    (secrets, ('token_bytes',)), (uuid, ('uuid1', 'uuid4')),
                    (builtins, ('open',)), (io, ('open',)), (socket, ('socket', 'create_connection'))):
                for name in names:
                    stack.enter_context(patch.object(module, name, forbidden))
            stack.enter_context(patch.object(os, 'environ', NoEnvironment()))
            for case, initial, (pages, review, plan, slots) in cases:
                actual = review_bundle.build_review_bundle(pages, preview_id=review['id'], allocate_id=slots.__getitem__)
                self.assertEqual(encode(review), encode(actual['review']))
                self.assertEqual(encode(plan), encode(actual['plan']))

    def test_conflict_literals_and_unknown_authority_refusal(self):
        """AC-IMP-007P-05: valid blocked facts are disclosed without any ID allocation."""
        def no_ids(slot):
            raise AssertionError('CONFLICT reserved an ID')
        pages = oracle_basis('branch-new_equal_meaning_revision')[0]
        minimal = deepcopy(next(r['minimal'] for p in pages if p['resource'] == 'inputs' for r in p['rows']))
        r = minimal['records'][0]
        r['acquisition_cost']['amount'] = r['acquisition_cost_cad']['amount'] = '701.00'
        r['legs'][0]['quantity'] = '-701.00'
        r['lifecycle']['payin']['quantity'] = '701.00'
        r['lifecycle']['exchange_rate']['amount'] = '70100.0000'
        replace_minimal(pages, minimal)
        bundle = self.build(pages, no_ids)
        expected = [('records', '0', 'conflict', 'parent', None),
                    ('coverage', '0', 'duplicate', None, '60000000-0000-4000-8000-000000000002'),
                    ('membership', '0', 'duplicate', None, '60000000-0000-4000-8000-000000000003')]
        self.assertEqual('CONFLICT', bundle['review']['state'])
        self.assertIsNone(bundle['plan'])
        facts = [r for r in bundle['review']['content']['rows'] if r['type'] == 'fact']
        self.assertEqual(expected, [(r['collection'], r['local_id'], r['action'], r['required_decision'], r['accepted_revision_id']) for r in facts])
        pages = oracle_basis('snapshot-historical-t1')[0]
        decisions = deepcopy(ORACLE['snapshot-historical-t1-decisions.json'])
        decisions['authorities'] = []
        bundle = self.build(store_decisions(pages, decisions), no_ids)
        facts = [r for r in bundle['review']['content']['rows'] if r['type'] == 'fact']
        self.assertEqual([('records', '0'), ('records', '1'), ('coverage', '0'), ('snapshots', '0')], [(r['collection'], r['local_id']) for r in facts])
        self.assertEqual([('conflict', 'authority', None)] * 4,
                         [(r['action'], r['required_decision'], r['accepted_revision_id']) for r in facts])
        pages = oracle_basis('authority-only')[0]
        decisions = deepcopy(ORACLE['authority-only-decisions.json'])
        member = decisions['mappings'][0]['member_id']
        decisions['authorities'][0]['left'] = {'form': 'incoming', 'member_id': member, 'collection': 'records', 'local_id': '0'}
        bundle = self.build(store_decisions(pages, decisions), no_ids)
        fact = next(r for r in bundle['review']['content']['rows'] if r['type'] == 'fact')
        self.assertEqual(('conflict', 'unsupported', None), (fact['action'], fact['required_decision'], fact['accepted_revision_id']))
        decisions['authorities'][0]['right']['accepted_revision_id'] = 'a6000000-0000-4000-8000-000000000001'
        self.refusal(store_decisions(pages, decisions), 'import_invalid', '$.decisions')

    def test_cross_member_collision_and_interleaved_decisions(self):
        """AC-IMP-007P-05: collisions block both sides and interleaving preserves decision order."""
        pages = oracle_basis('first-use')[0]
        original = deepcopy(pages[0]['rows'][0])
        second = deepcopy(original)
        second['id'] = 'e0000000-0000-4000-8000-000000000001'
        r = second['minimal']['records'][0]
        r['acquisition_cost']['amount'] = r['acquisition_cost_cad']['amount'] = '701.00'
        r['legs'][0]['quantity'] = '-701.00'
        r['lifecycle']['payin']['quantity'] = '701.00'
        r['lifecycle']['exchange_rate']['amount'] = '70100.0000'
        second['digest'] = digest(second['minimal'])
        pages[0]['rows'].append(second)
        context = next(p for p in pages if p['resource'] == 'context')['rows'][0]
        context['pinned_sources'].append({**context['pinned_sources'][0], 'member_id': second['id']})
        decisions = deepcopy(ORACLE['decisions-first-use.json'])
        decisions['mappings'] += [{**m, 'member_id': second['id']} for m in deepcopy(decisions['mappings'])]
        def no_ids(slot):
            raise AssertionError('CONFLICT reserved an ID')
        bundle = self.build(store_decisions(pages, decisions), no_ids)
        records = [r for r in bundle['review']['content']['rows'] if r['type'] == 'fact' and r['collection'] == 'records']
        self.assertEqual([('conflict', 'identity', None)] * 2, [(r['action'], r['required_decision'], r['accepted_revision_id']) for r in records])
        pages = oracle_basis('mixed-set')[0]
        d = deepcopy(ORACLE['mixed-set-decisions.json'])
        mappings = d['mappings']
        left = [m for m in mappings if m['member_id'] == mappings[0]['member_id']]
        right = [m for m in mappings if m['member_id'] != mappings[0]['member_id']]
        d['mappings'] = [v for pair in zip(left, right) for v in pair] + left[len(right):]
        pages = store_decisions(pages, d)
        bundle = self.build(pages)
        self.assertEqual('READY', bundle['review']['state'])
        rows = bundle['review']['content']['rows']
        self.assertEqual(d['mappings'], [r['mapping'] for r in rows if r['type'] == 'mapping'])
        self.assertEqual(d['mappings'], bundle['plan']['mappings'])
        source_indices = [i for i, r in enumerate(rows) if r['type'] == 'source_entity']
        candidate_indices = [i for i, r in enumerate(rows) if r['type'] == 'target_candidate']
        self.assertLess(max(source_indices), min(candidate_indices))

    def test_builtin_examples(self):
        """AC-IMP-007P-03: public parser stages retain literal facts and unknown boundaries."""
        from decimal import Decimal
        from test_ingestion_discovery import IngestionDiscoveryTests
        for provider, expected_name in (('wealthsimple', 'wealthsimple_expected'), ('bullbitcoin', 'bull_expected')):
            with self.subTest(provider=provider):
                minimal = IngestionDiscoveryTests().builtin(provider)
                pages = oracle_basis('first-use', initial=True)[0]
                replace_minimal(pages, minimal)
                pin = next(p for p in pages if p['resource'] == 'context')['rows'][0]['pinned_sources'][0]
                pin.update(installation_id=minimal['provenance']['installation_id'],
                    wrapper_profile_digest=minimal['provenance']['wrapper_profile_digest'],
                    format_version=minimal['provenance']['format_selection'])
                bundle = self.build(proposed_ready(pages))
                rows = bundle['review']['content']['rows']
                facts = [r for r in rows if r['type'] == 'fact']
                records = [r['record'] for r in facts if r['collection'] == 'records']
                expected = ORACLE['builtin-inputs.json'][expected_name]
                accounts = [r for r in rows if r['type'] == 'source_entity' and r['entity_kind'] == 'account']
                self.assertEqual(expected['accounts'], len(accounts))
                self.assertEqual(minimal['records'], records)
                heads = [r['head'] for r in rows if r['type'] == 'head']
                if provider == 'wealthsimple':
                    self.assertEqual(expected['positions'], len(records))
                    for currency, key in (('CAD', 'cad_native_positions_sum'), ('USD', 'usd_native_positions_sum')):
                        self.assertEqual(Decimal(expected[key]), sum(Decimal(r['market_value']['amount']) for r in records if r['market_value']['currency'] == currency))
                    coverage = [r for r in facts if r['collection'] == 'coverage']
                    self.assertEqual(['partial'] * 3, [r['scope']['status'] for r in coverage])
                    self.assertEqual('unknown', next(r['scope']['status'] for r in facts if r['collection'] == 'membership'))
                    self.assertEqual(expected['as_of'], next(r['scope']['as_of']['token'] for r in facts if r['collection'] == 'snapshots'))
                    self.assertEqual([('snapshot', None, None)] * 3, [(h['kind'], h['prior_revision_id'], h['complete_base_id']) for h in heads])
                    self.assertTrue(all(f['economic_group_id'] is None for f in bundle['plan']['facts']))
                else:
                    buys = [r for r in records if r['kind'] == 'BUY']
                    self.assertEqual(expected['completed_buys'], len(buys))
                    for symbol, key in (('BTC', 'btc'), ('LBTC', 'lbtc')):
                        local = next(a['local_id'] for a in minimal['assets'] if a['symbol'] == symbol)
                        self.assertEqual(Decimal(expected[key]), sum(Decimal(leg['quantity']) for r in buys for leg in r['legs'] if leg['role'] == 'ACQUISITION' and leg['asset_local_id'] == local))
                    self.assertEqual(Decimal(expected['purchase_cost_cad']), sum(Decimal(r['acquisition_cost_cad']['amount']) for r in buys))
                    funding = next(r for r in records if r['kind'] == 'FUNDING')
                    self.assertEqual(Decimal(expected['funding_cad']), Decimal(funding['cash_flow']['cash_amount']['amount']))
                    self.assertEqual('unclassified', funding['cash_flow']['boundary'])
                    self.assertEqual([], funding['legs'])
                    self.assertEqual(['completed'] * 3, [r['status'] for r in records])
                    self.assertEqual(['activity'] * 3, [h['kind'] for h in heads])
                    groups = [f['economic_group_id'] for f in bundle['plan']['facts'] if f['collection'] == 'records']
                    self.assertEqual(3, len(set(groups)))
                    self.assertNotIn(None, groups)
                self.assertEqual(minimal['provenance']['diagnostics'], [r['diagnostic'] for r in rows if r['type'] == 'diagnostic'])
                wire = encode(bundle).replace(b'wallet_balance_unverified', b'').replace(b'wallet_fees_unknown', b'')
                self.assertNotIn(b'contribution', wire)
                self.assertNotIn(b'wallet_balance', wire)

    def test_large_basis_performance(self):
        """AC-IMP-007P-07: both large-basis review states finish within 10 seconds."""
        import time
        pages = oracle_basis('first-use', initial=True)[0]
        replace_minimal(pages, ORACLE['large-basis-minimal.json'])
        started = time.perf_counter()
        initial = self.build(pages)
        initial_elapsed = time.perf_counter() - started
        self.assertEqual('NEEDS_MAPPING', initial['review']['state'])
        pages = proposed_ready(pages)
        started = time.perf_counter()
        ready = self.build(pages)
        ready_elapsed = time.perf_counter() - started
        self.assertEqual('READY', ready['review']['state'])
        print(f'large-basis NEEDS_MAPPING={initial_elapsed:.3f}s READY={ready_elapsed:.3f}s')
        self.assertLess(initial_elapsed, 10)
        self.assertLess(ready_elapsed, 10)


if __name__ == '__main__':
    unittest.main()
