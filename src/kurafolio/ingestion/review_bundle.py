"""Build deterministic reviews from one pinned prepare basis, without I/O."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import NamedTuple

from .approval import validate_review_bundle
from .codec import compare_time, decode, digest, encode, sha256, validate
from .contracts import IngestionError, MAX_SET
from .mapping import MappingIndex, compatible, proposed_body
from .reconciliation import financial_projection, reconcile_revision, snapshot_order, source_revision_key

RESOURCES = ('inputs', 'entities', 'mappings', 'revisions', 'heads', 'authorities', 'decisions', 'context')
_KINDS = {'account': 'accounts', 'instrument': 'assets', 'issuer': 'issuers'}
_COLLECTIONS = ('records', 'coverage', 'snapshots', 'membership')
_DECISIONS = ('authorities', 'mappings', 'new_entities', 'parents')
_PINS = ('job_id', 'fence', 'set_revision', 'accepted_generation', 'mapping_generation', 'control_generation')


class IdSlot(NamedTuple):
    purpose: str
    member_id: str
    kind: str
    local_id: str


def _fail(field, code='import_invalid'):
    raise IngestionError(code, field)


def _entity_key(row):
    return row['member_id'], tuple(_KINDS).index(row['entity_kind']), int(row['local_id'])


def _row_key(resource, row):
    if resource == 'inputs':
        return row['id']
    if resource == 'entities':
        c = row['candidate']
        return _entity_key(c) + (c['target']['id'], c['target']['version'])
    if resource == 'mappings':
        return _entity_key(row['mapping'])
    if resource == 'revisions':
        return row['revision']['id']
    if resource == 'heads':
        return row['head']['kind'], row['head']['key_digest']
    if resource == 'authorities':
        return row['link_id']
    if resource == 'decisions':
        return (-1, 0) if row['kind'] == 'decisions_header' else (_DECISIONS.index(row['collection']), row['ordinal'])
    return 0


def _intake(pages):
    rows, terminals, pins = {r: [] for r in RESOURCES}, defaultdict(int), None
    expected = {'inputs': {'input'}, 'entities': {'entity'}, 'mappings': {'mapping'},
                'revisions': {'revision'}, 'heads': {'head'}, 'authorities': {'authority'},
                'decisions': {'decisions_header', 'decision_item'}, 'context': {'prepare_context'}}
    for page in pages:
        resource = page.get('resource') if isinstance(page, dict) else None
        field = '$.basis.' + (resource if resource in RESOURCES else 'inputs')
        try:
            validate(page, 'BasisPage', namespace='wire')
        except IngestionError:
            _fail(field)
        if resource not in RESOURCES or any(r['kind'] not in expected[resource] for r in page['rows']):
            _fail(field)
        p = tuple(page[k] for k in _PINS)
        if pins is not None and pins != p:
            _fail('$.basis', 'import_stale')
        pins = p
        if page['next_cursor'] is None:
            terminals[resource] += 1
        elif page['next_cursor']['resource'] != resource:
            _fail(field)
        rows[resource].extend(deepcopy(page['rows']))
    for resource, values in rows.items():
        if terminals[resource] != 1:
            _fail('$.basis.' + resource)
        keys = [_row_key(resource, r) for r in values]
        if len(set(keys)) != len(keys):
            _fail('$.basis.' + resource)
        values.sort(key=lambda r: _row_key(resource, r))
    pins = dict(zip(_PINS, pins))
    inputs, stages = {}, {}
    for row in rows['inputs']:
        raw = encode(row['minimal'])
        if sha256(raw) != row['digest']:
            _fail('$.basis.inputs', 'import_stale')
        inputs[row['id']] = decode(raw)
        stages[row['id']] = raw
    if not 1 <= len(inputs) <= 4 or len(rows['context']) != 1:
        _fail('$.basis.context')
    context = rows['context'][0]
    if sorted(p['member_id'] for p in context['pinned_sources']) != list(inputs):
        _fail('$.basis.context')
    decisions, header = None, None
    if rows['decisions']:
        headers = [r for r in rows['decisions'] if r['kind'] == 'decisions_header']
        if len(headers) != 1:
            _fail('$.basis.decisions')
        header = headers[0]
        decisions = {k: header[k] for k in ('version', 'operation_id', 'expected_set_revision')}
        for collection in _DECISIONS:
            items = [r for r in rows['decisions'] if r.get('collection') == collection]
            if [r['ordinal'] for r in items] != list(range(header['counts'][collection])):
                _fail('$.basis.decisions')
            decisions[collection] = [r['value'] for r in items]
        if digest(decisions) != header['digest']:
            _fail('$.basis.decisions')
    return rows, pins, inputs, stages, context, decisions, header


def _facts(minimal):
    for collection in _COLLECTIONS:
        values = ([dict(minimal['membership'], local_id='0')] if minimal['membership'] is not None else []) if collection == 'membership' else minimal[collection]
        for row in sorted(values, key=lambda r: int(r['local_id'])):
            # Membership has no local_id in its admitted shape.
            yield collection, row['local_id'], minimal['membership'] if collection == 'membership' else row


def _entities(minimal):
    for kind, collection in _KINDS.items():
        for row in sorted(minimal[collection], key=lambda r: int(r['local_id'])):
            yield kind, row['local_id'], row


def _check_references(rows, inputs, decisions):
    entities = {(m, kind, local) for m, minimal in inputs.items() for kind, local, _ in _entities(minimal)}
    facts = {(m, c, local) for m, minimal in inputs.items() for c, local, _ in _facts(minimal)}
    revisions = {r['revision']['id']: r['revision'] for r in rows['revisions']}
    for row in rows['mappings']:
        m = row['mapping']
        if (m['member_id'], m['entity_kind'], m['local_id']) not in entities:
            _fail('$.basis.mappings')
    for row in rows['entities']:
        c = row['candidate']
        if (c['member_id'], c['entity_kind'], c['local_id']) not in entities:
            _fail('$.basis.entities')
    if decisions:
        for m in decisions['mappings']:
            if (m['member_id'], m['entity_kind'], m['local_id']) not in entities:
                _fail('$.decisions')
        for e in decisions['new_entities']:
            if (e['member_id'], e['kind'], e['local_id']) not in entities:
                _fail('$.decisions')
        for parent in decisions['parents']:
            if (parent['member_id'], parent['collection'], parent['local_id']) not in facts or parent['parent_revision_id'] not in revisions:
                _fail('$.decisions')
        for authority in decisions['authorities']:
            for side in (authority['left'], authority['right']):
                if side is None:
                    continue
                if side['form'] == 'accepted':
                    if side['accepted_revision_id'] not in revisions:
                        _fail('$.decisions')
                elif (side['member_id'], side['collection'], side['local_id']) not in facts:
                    _fail('$.decisions')
    chains = defaultdict(list)
    for revision in revisions.values():
        chains[revision['source_key_digest']].append(revision)
    heads = {(r['head']['kind'], r['head']['key_digest']): r['head'] for r in rows['heads']}
    for head in heads.values():
        if head['next_revision_id'] not in revisions:
            _fail('$.basis.revisions')
    tips = {}
    for key, chain in chains.items():
        if len({r['economic_group_id'] for r in chain}) != 1:
            _fail('$.basis.revisions')
        children = {r['parent_revision_id'] for r in chain}
        leaves = [r for r in chain if r['id'] not in children]
        if len(leaves) != 1 and not any(h['next_revision_id'] in {r['id'] for r in chain} for h in heads.values()):
            _fail('$.basis.revisions')
        if len(leaves) == 1:
            tips[key] = leaves[0]
    return revisions, chains, heads, tips


class _Ids:
    def __init__(self, rows, preview_id, allocate):
        validate(preview_id, 'UUID')
        self.used, self.slots, self.allocate = {preview_id}, {}, allocate
        def collect(value):
            if isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
            elif isinstance(value, str):
                self.used.add(value)
        collect(rows)

    def __call__(self, purpose, member, kind, local):
        slot = IdSlot(purpose, member, kind, local)
        if slot not in self.slots:
            value = self.allocate(slot)
            try:
                validate(value, 'UUID')
            except IngestionError:
                _fail('$.ids', 'import_conflict')
            if value in self.used:
                _fail('$.ids', 'import_conflict')
            self.used.add(value)
            self.slots[slot] = value
        return self.slots[slot]


def _candidates(rows, inputs, context, decisions):
    if decisions is None:
        return None
    result, proposed = {}, {}
    existing = {(_entity_key(r['candidate']), r['candidate']['target']['id'], r['candidate']['target']['version']): r['candidate'] for r in rows['entities']}
    for member, minimal in inputs.items():
        index = MappingIndex(decisions['mappings'], member)
        try:
            index.require_complete(minimal)
        except IngestionError as exc:
            if exc.code == 'import_mapping_required':
                return None
            raise
        for m in decisions['mappings']:
            if m['member_id'] != member:
                continue
            target, kind, local = m['target'], m['entity_kind'], m['local_id']
            source = minimal[_KINDS[kind]][int(local)]
            if target['mode'] == 'proposed':
                body = proposed_body(minimal, kind, local, target['id'], context['tenant_id'], context['portfolio_id'], index)
                if target['version'] != digest(body):
                    return None
                key = kind, target['id']
                if key in proposed and proposed[key] != body:
                    return None
                proposed[key] = body
            else:
                candidate = existing.get((_entity_key(m), target['id'], target['version']))
                if candidate is None:
                    return None
                body = candidate['body']
                issuer_id = (None if kind != 'instrument' or source['issuer_local_id'] is None
                             else index.target('issuer', source['issuer_local_id'])['id'])
                if digest(body) != target['version'] or not compatible(source, body, kind,
                        tenant_id=context['tenant_id'], portfolio_id=context['portfolio_id'], issuer_id=issuer_id):
                    return None
            result[member, kind, local] = {**m, 'body': body}
    return result


def _initial_candidates(rows, inputs, context, ids):
    result = defaultdict(list)
    for member, minimal in inputs.items():
        proposed = []
        # Issuers are built before instruments, but disclosed in source order.
        for kind in ('issuer', 'account', 'instrument'):
            for local, source in [(local, source) for k, local, source in _entities(minimal) if k == kind]:
                entity_id = ids('entity', member, kind, local)
                body = proposed_body(minimal, kind, local, entity_id, context['tenant_id'], context['portfolio_id'], MappingIndex(proposed, member))
                proposed.append({'member_id': member, 'entity_kind': kind, 'local_id': local,
                                 'target': {'mode': 'proposed', 'id': entity_id, 'version': digest(body)}})
                result[member, kind, local].append({**proposed[-1], 'body': body})
        for kind, local, _ in _entities(minimal):
            existing = [r['candidate'] for r in rows['entities'] if (r['candidate']['member_id'], r['candidate']['entity_kind'], r['candidate']['local_id']) == (member, kind, local)]
            result[member, kind, local] = existing + result[member, kind, local]
    return result


def _claim(key):
    return {**{k: v for k, v in key['source'].items() if k not in ('version', 'tenant_id', 'portfolio_id', 'connection_id', 'collection')}, 'revision': key['revision']}


def _classify(inputs, context, decisions, revisions, chains, heads, tips, links):
    pins = {p['member_id']: p for p in context['pinned_sources']}
    parents = {(p['member_id'], p['collection'], p['local_id']): p['parent_revision_id'] for p in decisions['parents']}
    facts = {}
    for member, minimal in inputs.items():
        index = MappingIndex(decisions['mappings'], member)
        scope = {k: context[k] for k in ('tenant_id', 'portfolio_id')}
        scope['connection_id'] = pins[member]['connection_id']
        for collection, local, row in _facts(minimal):
            key = source_revision_key(minimal, collection, local, **scope)
            material = digest(financial_projection(minimal, collection, local, index, scope=scope))
            chain = chains.get(digest(key['source']), [])
            exact = next((r for r in chain if r['source']['revision'] == key['revision']), None)
            fact = {'member_id': member, 'collection': collection, 'local_id': local, 'row': row,
                    'key': key, 'material': material, 'action': 'append', 'prior': None, 'group': None,
                    'id': None, 'required': None, 'heads': [], 'duplicate_of': None}
            facts[member, collection, local] = fact
            def trusted(r, active=True):
                return None if r is None else {'id': r['id'], 'source_revision_key': {'version': 1, 'source': key['source'], 'revision': r['source']['revision']},
                                               'material': r['financial_digest'], 'active': active}
            parent = parents.get((member, collection, local))
            activity = collection == 'records' and row['record_type'] == 'activity'
            if collection == 'snapshots':
                continue
            current = tips.get(digest(key['source']))
            active = True
            if activity and chain:
                fact['group'] = chain[0]['economic_group_id']
                hk = digest({'version': 1, **{k: scope[k] for k in ('tenant_id', 'portfolio_id')}, 'economic_group_id': fact['group']})
                head = heads.get(('activity', hk))
                current = None if head is None else revisions[head['next_revision_id']]
                active = head is not None and head['active']
            change = row['identity']['change'] if collection == 'records' else 'original'
            if change == 'original' and parent is not None:
                change = 'correction'
            try:
                decision = reconcile_revision(incoming_key=key, incoming_material=material, change=change,
                    parent_revision_id=parent, current=trusted(current, active), exact=trusted(exact, active))
                fact['prior'] = decision.prior_revision_id if decision.action != 'duplicate' else None
                fact['active'] = decision.active
                if decision.action == 'duplicate':
                    fact['action'], fact['id'] = 'duplicate', decision.prior_revision_id
                elif decision.prior_revision_id is not None:
                    fact['action'] = 'void' if change == 'void' else 'correction'
            except IngestionError as exc:
                if exc.code != 'import_conflict':
                    raise
                fact['required'] = 'identity' if exact is not None and exact['financial_digest'] != material else 'parent'
            if activity and chain and current is None:
                fact['required'] = 'parent'
            if parent is not None:
                if any(r['parent_revision_id'] == parent for r in revisions.values()):
                    fact['required'] = 'parent'
                claim = row['identity']['parent'] if collection == 'records' else row.get('parent')
                if claim is not None and claim != revisions[parent]['source']:
                    fact['required'] = 'parent'
            if activity and minimal['provenance']['parser_api'] is None and minimal['provenance']['id_policy'] == 'ambiguous':
                fact['required'] = 'identity'
    # Snapshots control the historical/conflict classification of their children.
    for (member, collection, local), fact in facts.items():
        if collection != 'snapshots':
            continue
        minimal, row, key = inputs[member], fact['row'], fact['key']
        index = MappingIndex(decisions['mappings'], member)
        parent = parents.get((member, collection, local))
        chain = chains.get(digest(key['source']), [])
        exact = next((r for r in chain if r['source']['revision'] == key['revision']), None)
        if exact is not None:
            if exact['financial_digest'] != fact['material']:
                fact['required'] = 'identity'
            else:
                fact['action'], fact['id'] = 'duplicate', exact['id']
        else:
            results = []
            for coverage_local in row['coverage_local_ids']:
                coverage = minimal['coverage'][int(coverage_local)]
                selector = coverage['instrument_scope']
                key_digest = digest({'version': 1, **{k: context[k] for k in ('tenant_id', 'portfolio_id')},
                    'account_id': index.target('account', coverage['account_local_id'])['id'], 'record_kind': 'holdings',
                    'instrument_scope': {'tag': selector['tag'], 'category': selector['category'],
                        'instrument_ids': sorted(index.target('instrument', x)['id'] for x in selector['asset_local_ids'])}})
                head = heads.get(('snapshot', key_digest))
                current = None if head is None else revisions[head['next_revision_id']]
                try:
                    outcome = snapshot_order(row['as_of'], None if current is None else current['typed']['as_of'],
                        same_material=current is not None and current['financial_digest'] == fact['material'], explicit_parent=parent is not None)
                    results.append(outcome)
                    fact['heads'].append((key_digest, head, coverage['status']))
                except IngestionError:
                    # Equal comparable instants require a parent; incomparable times are unsupported.
                    try:
                        equal = current is not None and compare_time(row['as_of'], current['typed']['as_of']) == 0
                    except IngestionError:
                        equal = False
                    fact['required'] = 'parent' if equal else 'unsupported'
            if len(set(results)) > 1:
                fact['required'] = 'unsupported'
            if not fact['required'] and results:
                outcome = results[0]
                if outcome == 'historical':
                    historical = any(a['kind'] == 'historical_only' and a['left'] == {'form': 'incoming', 'member_id': member, 'collection': collection, 'local_id': local} for a in decisions['authorities'])
                    if historical:
                        fact['action'] = 'historical'
                        fact['heads'] = []
                    else:
                        fact['required'] = 'authority'
                elif outcome == 'duplicate':
                    targets = {h['next_revision_id'] for _, h, _ in fact['heads']}
                    if len(targets) != 1:
                        fact['required'] = 'unsupported'
                    else:
                        fact['action'], fact['id'] = 'duplicate', targets.pop()
                        fact['heads'] = []
                elif outcome == 'correction':
                    if any(h is None or h['next_revision_id'] != parent for _, h, _ in fact['heads']):
                        fact['required'] = 'parent'
                    else:
                        fact['action'], fact['prior'] = 'correction', parent
                if outcome in ('new', 'correction') and (row['as_of']['tag'] == 'legacy_unspecified' or (row['as_of']['tag'] == 'date_only' and row['as_of']['zone'] is None)):
                    fact['required'] = 'unsupported'
        for c, ids in (('records', row['position_local_ids']), ('coverage', row['coverage_local_ids'])):
            for child_local in ids:
                child = facts[member, c, child_local]
                if fact['required']:
                    child['required'] = fact['required']
                elif fact['action'] == 'historical':
                    child.update(action='historical', id=None, prior=None)
                elif fact['action'] == 'duplicate' and child['action'] != 'duplicate':
                    child['required'] = 'identity'
    _across_facts(facts, inputs, context, decisions, revisions, links)
    return facts


def _across_facts(facts, inputs, context, decisions, revisions, links):
    by_key = defaultdict(list)
    for fact in facts.values():
        by_key[encode(fact['key'])].append(fact)
    for same in by_key.values():
        if len(same) < 2:
            continue
        if len({f['member_id'] for f in same}) != len(same) or len({f['material'] for f in same}) != 1:
            for fact in same:
                fact['required'] = 'identity'
        else:
            first = same[0]
            for fact in same[1:]:
                if first['action'] != 'duplicate':
                    fact.update(action='duplicate', duplicate_of=first, prior=None)
    parents = {(p['member_id'], p['collection'], p['local_id']): p['parent_revision_id'] for p in decisions['parents']}
    for key, fact in facts.items():
        if key in parents and not fact['required'] and (fact['action'] not in ('correction', 'void') or fact['prior'] != parents[key]):
            fact['required'] = 'parent'
    activities = [f for f in facts.values() if f['collection'] == 'records' and f['row']['record_type'] == 'activity']
    def revision_token(f):
        if f['duplicate_of'] is not None:
            return revision_token(f['duplicate_of'])
        return ('accepted', f['id']) if f['id'] is not None else ('incoming', f['member_id'], f['collection'], f['local_id'])
    claims = [(_claim(f['key']), revision_token(f)) for f in facts.values()] + [(r['source'], ('accepted', r['id'])) for r in revisions.values()]
    for fact in activities:
        row = fact['row']
        references = list(row['economic_references'])
        if row['cash_flow'] is not None:
            references.extend(row['cash_flow'][k] for k in ('counterpart', 'cash_leg_of') if row['cash_flow'][k] is not None)
        for claim in references:
            if len({token for c, token in claims if all(v == c[k] for k, v in claim.items() if k != 'revision' or v is not None)}) != 1:
                fact['required'] = 'identity'
    for authority in decisions['authorities']:
        if not _unsupported_authority(authority):
            continue
        left = authority['left']
        if left['form'] == 'accepted':
            member = _authority_member(authority, next(iter(inputs)))
            for fact in facts.values():
                if fact['member_id'] == member:
                    fact['required'] = 'unsupported'
        else:
            key = left['member_id'], left['collection'], left['local_id']
            facts[key]['required'] = 'unsupported'
            if authority['kind'] == 'historical_only' and left['collection'] == 'snapshots':
                row = facts[key]['row']
                for collection, local_ids in (('records', row['position_local_ids']), ('coverage', row['coverage_local_ids'])):
                    for local in local_ids:
                        facts[left['member_id'], collection, local]['required'] = 'unsupported'
    # Competing streams within this set. Unknown time comparisons count as overlap.
    indexes = {m: MappingIndex(decisions['mappings'], m) for m in inputs}
    connections = {p['member_id']: p['connection_id'] for p in context['pinned_sources']}
    def side(f):
        return {'form': 'incoming', **{k: f[k] for k in ('member_id', 'collection', 'local_id')}}
    overlap_cache = {}
    def overlaps(a, b):
        am, bm = a['member_id'], b['member_id']
        cache_key = (am, a['row']['source_account_local_id'], a['row']['source_kind'],
                     bm, b['row']['source_account_local_id'], b['row']['source_kind'])
        if cache_key in overlap_cache:
            return overlap_cache[cache_key]
        def interval(time):
            return (time['at'], time['at']) if time['tag'] == 'point' else (time['start'], time['end'])
        def disjoint(end, start, end_inclusive, start_inclusive):
            try:
                comparison = compare_time(end, start)
            except IngestionError:
                return False
            return comparison < 0 or (comparison == 0 and not (end_inclusive and start_inclusive))
        for ca in inputs[am]['coverage']:
            if ca['account_local_id'] != a['row']['source_account_local_id'] or ca['kind'] != a['row']['source_kind']:
                continue
            for cb in inputs[bm]['coverage']:
                if cb['account_local_id'] != b['row']['source_account_local_id'] or cb['kind'] != b['row']['source_kind']:
                    continue
                sa, sb = ca['instrument_scope'], cb['instrument_scope']
                if sa['tag'] == sb['tag'] == 'category' and sa['category'] != sb['category']:
                    continue
                if sa['tag'] == sb['tag'] == 'instruments':
                    ia = {indexes[am].target('instrument', x)['id'] for x in sa['asset_local_ids']}
                    ib = {indexes[bm].target('instrument', x)['id'] for x in sb['asset_local_ids']}
                    if ia.isdisjoint(ib):
                        continue
                ta, tb = ca['time'], cb['time']
                aa, az = interval(ta); ba, bz = interval(tb)
                if disjoint(az, ba, ta.get('end_inclusive', True), tb.get('start_inclusive', True)):
                    continue
                if disjoint(bz, aa, tb.get('end_inclusive', True), ta.get('start_inclusive', True)):
                    continue
                overlap_cache[cache_key] = True
                return True
        overlap_cache[cache_key] = False
        return False
    stream_groups = defaultdict(list)
    for f in activities:
        m = f['member_id']
        stream_groups[indexes[m].target('account', f['row']['source_account_local_id'])['id'], f['row']['kind']].append(f)
    def stream_pairs():
        for group in stream_groups.values():
            by_connection = defaultdict(list)
            for f in group:
                by_connection[connections[f['member_id']]].append(f)
            groups = list(by_connection.values())
            for i, left in enumerate(groups):
                for right in groups[i + 1:]:
                    for a in left:
                        for b in right:
                            yield a, b
    latest_links = {}
    for link in links:
        old = latest_links.get(link['link_id'])
        if old is None or int(old['link_revision']) < int(link['link_revision']):
            latest_links[link['link_id']] = link
    def ref_token(ref):
        if ref is None:
            return None
        if ref['form'] == 'accepted':
            return 'accepted', ref['accepted_revision_id']
        return revision_token(facts[ref['member_id'], ref['collection'], ref['local_id']])
    for a, b in stream_pairs():
        pair = {revision_token(a), revision_token(b)}
        choices = [auth for auth in decisions['authorities'] if {ref_token(auth['left']), ref_token(auth['right'])} == pair]
        if not choices:
            choices = [link['authority'] for link in latest_links.values()
                       if {ref_token(link['authority']['left']), ref_token(link['authority']['right'])} == pair]
        linked = any(auth['kind'] in ('mirror', 'independent', 'authority') for auth in choices)
        if not linked and overlaps(a, b):
            a['required'] = b['required'] = 'authority'


def _unsupported_authority(authority):
    left = authority['left']
    return ((authority['kind'] == 'mirror' and left['form'] == 'incoming') or
            (authority['kind'] == 'historical_only' and
             (left['form'] != 'incoming' or left['collection'] != 'snapshots' or authority['right'] is not None)))


def _authority_member(authority, first):
    for side in (authority['left'], authority['right']):
        if side is not None and side['form'] == 'incoming':
            return side['member_id']
    return first


def _authority_row(authority, rows, facts, ready):
    def resolve(side):
        if side is None:
            return None
        if side['form'] == 'accepted':
            return side['accepted_revision_id']
        return facts[side['member_id'], side['collection'], side['local_id']]['id'] if ready else None
    left, right = resolve(authority['left']), resolve(authority['right'])
    matches = []
    if left is not None and (right is not None or authority['right'] is None):
        for row in rows['authorities']:
            a = row['authority']
            pair = (a['left'].get('accepted_revision_id'), None if a['right'] is None else a['right'].get('accepted_revision_id'))
            if pair == (left, right) or pair == (right, left):
                matches.append(row)
    prior = None
    if matches:
        highest = max(int(r['link_revision']) for r in matches)
        matches = [r for r in matches if int(r['link_revision']) == highest]
        if len(matches) != 1:
            _fail('$.basis.authorities', 'import_conflict')
        prior = matches[0]
    return {'type': 'authority', 'authority': authority, 'prior_choice': None if prior is None else prior['authority']['kind'],
            'prior_link_id': None if prior is None else prior['link_id'], 'prior_link_revision': None if prior is None else prior['link_revision']}


def build_review_bundle(pages, *, preview_id, allocate_id):
    """Return a complete ReviewBundle from all pages of one prepare lease.

    Caller-supplied IDs are requested once per IdSlot, only after classification.
    Refusals raise fixed IngestionError codes without returning a partial bundle.
    """
    rows, pins, inputs, stages, context, decisions, header = _intake(pages)
    revisions, chains, heads, tips = _check_references(rows, inputs, decisions)
    ids = _Ids(rows, preview_id, allocate_id)
    candidates = _candidates(rows, inputs, context, decisions)
    state = 'NEEDS_MAPPING' if candidates is None else 'READY'
    facts = {} if state == 'NEEDS_MAPPING' else _classify(inputs, context, decisions, revisions, chains, heads, tips, rows['authorities'])
    if any(f['required'] for f in facts.values()) or (state != 'NEEDS_MAPPING' and any(_unsupported_authority(a) for a in decisions['authorities'])):
        state = 'CONFLICT'
    ready = state == 'READY'
    if state == 'NEEDS_MAPPING':
        candidates = _initial_candidates(rows, inputs, context, ids)
    if ready:
        for fact in facts.values():
            if fact['duplicate_of'] is not None:
                fact['id'], fact['group'] = fact['duplicate_of']['id'], fact['duplicate_of']['group']
            elif fact['action'] != 'duplicate':
                fact['id'] = ids('revision', fact['member_id'], fact['collection'], fact['local_id'])
                if fact['collection'] == 'records' and fact['row']['record_type'] == 'activity' and fact['group'] is None:
                    fact['group'] = ids('group', fact['member_id'], 'records', fact['local_id'])
    member_order = list(inputs)
    first = member_order[0]
    fallback = False
    if decisions is not None:
        for name in ('mappings', 'authorities', 'parents'):
            attribution = [(_authority_member(v, first) if name == 'authorities' else v['member_id']) for v in decisions[name]]
            if attribution != sorted(attribution):
                fallback = True
    content_rows = []
    def add(row):
        content_rows.append({**row, 'ordinal': str(len(content_rows))})
    def source_rows(members):
        for member in members:
            for kind, local, source in _entities(inputs[member]):
                add({'type': 'source_entity', 'member_id': member, 'entity_kind': kind, 'local_id': local, 'source': source})
    def candidate_rows(members):
        if state == 'NEEDS_MAPPING':
            for member in members:
                for kind, local, _ in _entities(inputs[member]):
                    for candidate in candidates[member, kind, local]:
                        add({'type': 'target_candidate', 'candidate': candidate})
        else:
            for m in decisions['mappings']:
                if m['member_id'] in members:
                    add({'type': 'target_candidate', 'candidate': candidates[m['member_id'], m['entity_kind'], m['local_id']]})
    def decision_rows(members):
        for m in decisions['mappings']:
            if m['member_id'] in members:
                add({'type': 'mapping', 'mapping': m})
        for a in decisions['authorities']:
            if _authority_member(a, first) in members:
                add(_authority_row(a, rows, facts, ready))
        for p in decisions['parents']:
            if p['member_id'] in members:
                add({'type': 'parent', 'parent': p})
    def fact_rows(members):
        pending_heads = []
        for f in facts.values():
            if f['member_id'] not in members:
                continue
            action = 'conflict' if f['required'] else f['action']
            add({'type': 'fact', **{k: f[k] for k in ('member_id', 'collection', 'local_id')},
                'record': f['row'] if f['collection'] == 'records' else None,
                'scope': None if f['collection'] == 'records' else f['row'], 'action': action,
                'accepted_revision_id': f['id'] if ready or action == 'duplicate' else None, 'required_decision': f['required']})
            if not ready:
                continue
            add({'type': 'effect', 'effect': {**{k: f[k] for k in ('member_id', 'collection', 'local_id', 'action')},
                'accepted_revision_id': f['id'], 'parent_revision_id': f['prior'],
                'economic_group_id': f['group'], 'financial_digest': f['material']}})
            if f['collection'] == 'records' and f['row']['record_type'] == 'activity' and f['action'] != 'duplicate':
                pending_heads.append({'kind': 'activity', 'key_digest': digest({'version': 1,
                    'tenant_id': context['tenant_id'], 'portfolio_id': context['portfolio_id'], 'economic_group_id': f['group']}),
                    'prior_revision_id': f['prior'], 'next_revision_id': f['id'], 'complete_base_id': None, 'active': f['active']})
            if f['collection'] == 'snapshots' and f['action'] not in ('duplicate', 'historical'):
                for hk, prior, status in f['heads']:
                    pending_heads.append({'kind': 'snapshot', 'key_digest': hk,
                        'prior_revision_id': None if prior is None else prior['next_revision_id'], 'next_revision_id': f['id'],
                        'complete_base_id': f['id'] if status == 'complete' else None if prior is None else prior['complete_base_id'], 'active': True})
        for head in pending_heads:
            add({'type': 'head', 'head': head})
    def diagnostics(members):
        for member in members:
            for diagnostic in inputs[member]['provenance']['diagnostics']:
                add({'type': 'diagnostic', 'member_id': member, 'diagnostic': diagnostic})
    blocks = [member_order] if fallback else [[m] for m in member_order]
    for members in blocks:
        source_rows(members)
        candidate_rows(members)
        if state != 'NEEDS_MAPPING':
            decision_rows(members)
            fact_rows(members)
        diagnostics(members)
    content = {'version': 1, 'rows': content_rows}
    review = {'version': 1, 'id': preview_id, 'set_id': context['set_id'],
        'set_revision': str(int(pins['set_revision']) + (1 if ready else 0)), 'state': state,
        **{k: pins[k] for k in ('accepted_generation', 'mapping_generation', 'control_generation')},
        'expires_at': context['set_expires_at'], 'content': content, 'content_digest': digest(content), 'plan_digest': None}
    plan = None
    if ready:
        plan = {'version': 1, **{k: context[k] for k in ('tenant_id', 'portfolio_id', 'set_id', 'realm_digest', 'incarnation', 'restore_epoch', 'pinned_sources')},
            'preview_id': preview_id, 'decision_digest': header['digest'], 'expected_set_revision': review['set_revision'],
            **{'expected_' + k: pins[k] for k in ('accepted_generation', 'mapping_generation', 'control_generation')},
            'expires_at': context['set_expires_at'], 'review_content_digest': review['content_digest'],
            'inputs': [{'member_id': member, 'stage_digest': sha256(stages[member]),
                        'raw_digest': minimal['provenance']['raw_sha256'], 'discovery_digest': minimal['provenance']['discovery_sha256']} for member, minimal in inputs.items()],
            **{k: decisions[k] for k in _DECISIONS},
            'facts': [r['effect'] for r in content_rows if r['type'] == 'effect'], 'heads': [r['head'] for r in content_rows if r['type'] == 'head']}
        review['plan_digest'] = digest(plan)
    bundle = {'version': 1, 'review': review, 'plan': plan}
    raw = encode(bundle)
    if len(raw) > MAX_SET:
        _fail('$', 'import_limit')
    try:
        validate_review_bundle(raw, stages=stages)
    except IngestionError as exc:
        if exc.code == 'import_limit':
            _fail('$', 'import_limit')
        raise
    return bundle
