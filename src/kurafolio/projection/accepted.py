"""Read accepted 0004 facts from a caller-owned, scoped read-only snapshot."""
from decimal import Decimal
import json

from kurafolio.persistence.context import TenantContext, execute
from .model import (AcceptedState, Account, ActivityFact, HoldingsHead, Instrument,
                    Leg, Money, PositionFact)

SUPPORTED_REVISIONS = ('0004_ingestion',)
UNAVAILABLE_CODES = frozenset(('projection_snapshot_required', 'projection_scope_mismatch',
    'projection_schema_unsupported', 'restore_required', 'projection_reference_missing',
    'projection_head_inconsistent'))


class ProjectionUnavailable(Exception):
    """Closed failure code; never contains SQL, rows or financial values."""
    def __init__(self, code):
        if code not in UNAVAILABLE_CODES:
            raise ValueError('Unknown projection failure code')
        self.code = code
        super().__init__(code)


def _decode(raw):
    return json.loads(bytes(raw))


def _money(value):
    return None if value is None else Money(Decimal(value['amount']), value['currency'])


def read_accepted_state(connection, context: TenantContext) -> AcceptedState:
    """Run SELECTs only. The caller controls settings, role and transaction."""
    try:
        return _read(connection, context)
    except ProjectionUnavailable:
        raise
    except Exception:
        raise ProjectionUnavailable('projection_reference_missing') from None


def _read(connection, context):
    status = execute(connection, """SELECT
        current_setting('transaction_isolation') AS isolation,
        current_setting('transaction_read_only') AS readonly,
        current_setting('ledger.tenant_id', true) AS tenant,
        current_setting('ledger.portfolio_id', true) AS portfolio"""
    ).mappings().one()
    if status['isolation'] != 'repeatable read' or status['readonly'] != 'on':
        raise ProjectionUnavailable('projection_snapshot_required')
    if status['tenant'] != context.tenant_id or status['portfolio'] != context.portfolio_id:
        raise ProjectionUnavailable('projection_scope_mismatch')
    try:
        versions = execute(connection, 'SELECT version_num FROM wl_pg.alembic_version').scalars().all()
        if len(versions) != 1 or versions[0] not in SUPPORTED_REVISIONS:
            raise ProjectionUnavailable('projection_schema_unsupported')
        ready = execute(connection, 'SELECT ready FROM wl_pg.instance_state WHERE id=1').scalars().all()
    except ProjectionUnavailable:
        raise
    except Exception:
        raise ProjectionUnavailable('projection_schema_unsupported') from None
    if ready != [True]:
        raise ProjectionUnavailable('restore_required')

    def rows(table, columns, order=''):
        # All identifiers are fixed call-site literals, never caller data.
        return execute(connection, 'SELECT ' + columns + ' FROM ' + table +
            ' WHERE tenant_id=:tenant AND portfolio_id=:portfolio' + order,
            tenant=context.tenant_id, portfolio=context.portfolio_id).mappings().all()

    roots = rows('wl_ingestion.roots', 'accepted_generation,mapping_generation')
    if not roots:
        return AcceptedState(context.tenant_id, context.portfolio_id, 0, 0, (), ())
    if len(roots) != 1:
        raise ProjectionUnavailable('projection_head_inconsistent')
    plans = rows('wl_ingestion.accepted_plans', 'canonical_bytes', ' ORDER BY created_at,id')
    revisions = {str(row['id']): row for row in rows('wl_ingestion.source_revisions',
        'id,parent_id,input_id,collection,local_id,typed_bytes')}
    lineage = {}
    for row in rows('wl_ingestion.lineage', 'source_revision_id,input_id,collection,local_id'):
        key = (str(row['input_id']), row['collection'], row['local_id'])
        lineage.setdefault(key, set()).add(str(row['source_revision_id']))
    accounts = {(str(row['id']), row['version']): Account(str(row['id']), row['version'],
        row['role'], row['category'], row['label']) for row in rows('wl_pg.accounts',
        'id,version,role,category,label')}
    instruments = {(str(row['id']), row['version']): Instrument(str(row['id']), row['version'],
        row['kind'], row['currency'], row['ticker'], row['mic'], row['symbol'], row['network'],
        row['settlement_identity']) for row in rows('wl_pg.instruments',
        'id,version,kind,currency,ticker,mic,symbol,network,settlement_identity')}
    fact_index = {}
    for row in plans:
        plan = _decode(row['canonical_bytes'])
        mappings = {(mapping['member_id'], mapping['entity_kind'], mapping['local_id']):
                    (mapping['target']['id'], mapping['target']['version'])
                    for mapping in plan['mappings']}
        for fact in plan['facts']:
            if fact['action'] != 'duplicate':
                fact_index.setdefault(fact['accepted_revision_id'], (mappings, fact['member_id']))

    def reference(revision_id):
        revision = revisions.get(revision_id)
        if revision is None or revision_id not in fact_index:
            raise ProjectionUnavailable('projection_reference_missing')
        return revision, _decode(revision['typed_bytes'])

    def entity(revision_id, kind, local):
        mappings, member = fact_index[revision_id]
        key = mappings.get((member, kind, local))
        target = (accounts if kind == 'account' else instruments).get(key)
        if target is None:
            raise ProjectionUnavailable('projection_reference_missing')
        return target

    def child(snapshot, collection, local):
        matches = lineage.get((str(snapshot['input_id']), collection, local), set())
        if len(matches) != 1:
            raise ProjectionUnavailable('projection_reference_missing')
        revision_id, = matches
        revision, typed = reference(revision_id)
        if revision['collection'] != collection:
            raise ProjectionUnavailable('projection_head_inconsistent')
        return revision_id, typed

    holdings, kept = [], set()
    for head in rows('wl_ingestion.snapshot_heads',
            'key_digest,account_id,account_version,scope_bytes,latest_revision_id',
            " AND fact_kind='holdings' ORDER BY key_digest"):
        snapshot_id = str(head['latest_revision_id'])
        snapshot, typed = reference(snapshot_id)
        if snapshot['collection'] != 'snapshots':
            raise ProjectionUnavailable('projection_head_inconsistent')
        account = accounts.get((str(head['account_id']), head['account_version']))
        if account is None:
            raise ProjectionUnavailable('projection_reference_missing')
        scope = _decode(head['scope_bytes'])
        positions = []
        for local in typed['position_local_ids']:
            revision_id, position = child(snapshot, 'records', local)
            if position['record_type'] != 'position':
                raise ProjectionUnavailable('projection_head_inconsistent')
            mapped_account = entity(revision_id, 'account', position['source_account_local_id'])
            instrument = entity(revision_id, 'instrument', position['asset_local_id'])
            in_scope = (scope['tag'] == 'all' or scope['tag'] == 'category' and
                scope['category'] == instrument.kind or scope['tag'] == 'instruments' and
                instrument.id in scope['instrument_ids'])
            if mapped_account.id != account.id or not in_scope:
                continue
            if revision_id in kept:
                raise ProjectionUnavailable('projection_head_inconsistent')
            kept.add(revision_id)
            positions.append(PositionFact(revision_id, mapped_account, instrument,
                Decimal(position['quantity']), _money(position['market_value']),
                _money(position['cost_native']), _money(position['cost_cad']), position['as_of'],
                tuple(position['support']['reasons'])))
        coverage = []
        for local in typed['coverage_local_ids']:
            revision_id, item = child(snapshot, 'coverage', local)
            if item['kind'] == 'holdings' and entity(revision_id, 'account', item['account_local_id']).id == account.id:
                coverage.append(item['status'])
        if len(coverage) != 1:
            raise ProjectionUnavailable('projection_head_inconsistent')
        holdings.append(HoldingsHead(head['key_digest'], account, scope, snapshot_id,
            typed['as_of'], coverage[0], tuple(sorted(positions, key=lambda item: item.revision_id))))

    latest_links = {}
    for link in rows('wl_ingestion.authority_links', 'id,revision,left_revision_id,decision_kind'):
        identity = str(link['id'])
        if identity not in latest_links or latest_links[identity]['revision'] < link['revision']:
            latest_links[identity] = link
    links = {}
    for link in latest_links.values():
        left = str(link['left_revision_id'])
        links.setdefault(left, []).append(link['decision_kind'])

    activities = []
    for head in rows('wl_ingestion.activity_heads', 'economic_group_id,revision_id,active',
                     ' ORDER BY economic_group_id'):
        revision_id = str(head['revision_id'])
        revision, typed = reference(revision_id)
        if revision['collection'] != 'records' or typed['record_type'] != 'activity':
            raise ProjectionUnavailable('projection_head_inconsistent')
        mirror, ancestor, seen = False, revision_id, set()
        while ancestor is not None:
            if ancestor in seen:
                raise ProjectionUnavailable('projection_head_inconsistent')
            seen.add(ancestor)
            parent = revisions.get(ancestor)
            if parent is None:
                raise ProjectionUnavailable('projection_reference_missing')
            kinds = links.get(ancestor, [])
            if any(kind not in ('mirror', 'independent') for kind in kinds):
                raise ProjectionUnavailable('projection_head_inconsistent')
            mirror = mirror or 'mirror' in kinds
            ancestor = str(parent['parent_id']) if parent['parent_id'] is not None else None
        legs = tuple(Leg(entity(revision_id, 'account', leg['account_local_id']),
                         entity(revision_id, 'instrument', leg['asset_local_id']),
                         Decimal(leg['quantity']), leg['role']) for leg in typed['legs'])
        has_crypto_fee = False
        for fee in typed['fees'] or ():
            # Resolve all named entities even when a zero fee contributes nothing.
            entity(revision_id, 'account', fee['account_local_id'])
            instrument = entity(revision_id, 'instrument', fee['asset_local_id'])
            has_crypto_fee |= instrument.kind == 'CRYPTO' and Decimal(fee['quantity']) > 0
        activities.append(ActivityFact(str(head['economic_group_id']), revision_id,
            head['active'], mirror, typed['kind'], typed['status'], tuple(typed['support']['reasons']),
            entity(revision_id, 'account', typed['source_account_local_id']), legs,
            _money(typed['acquisition_cost']), has_crypto_fee, typed['event_time']))
    return AcceptedState(context.tenant_id, context.portfolio_id, roots[0]['accepted_generation'],
        roots[0]['mapping_generation'], tuple(holdings), tuple(activities))
