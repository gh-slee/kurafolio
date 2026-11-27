"""Resolve current entity metadata without changing the facts' pinned versions."""
from dataclasses import dataclass
from typing import Mapping

from kurafolio.persistence.context import TenantContext, execute

from .accepted import ProjectionUnavailable
from .model import Account, Instrument


@dataclass(frozen=True, slots=True)
class CurrentEntities:
    accounts: Mapping[str, Account]
    instruments: Mapping[str, Instrument]


def resolve_current_entities(mappings, plans, accounts, instruments) -> CurrentEntities:
    """Use the newest current target per entity, or its newest historical target."""
    plan_times = {str(row['id']): row['created_at'] for row in plans}
    newest_by_mapping = {}
    for row in mappings:
        key = str(row['id'])
        if key not in newest_by_mapping or row['revision'] > newest_by_mapping[key]:
            newest_by_mapping[key] = row['revision']

    targets = {}
    for row in mappings:
        mapping_id = str(row['id'])
        plan_id = str(row['plan_id'])
        if plan_id not in plan_times:
            raise ProjectionUnavailable('projection_reference_missing')
        entity = (row['entity_kind'], str(row['entity_id']))
        order = (row['revision'] == newest_by_mapping[mapping_id],
                 plan_times[plan_id], plan_id, row['revision'], mapping_id)
        if entity not in targets or order > targets[entity][0]:
            targets[entity] = (order, row['entity_version'])

    account_rows = {(str(row['id']), row['version']): row for row in accounts}
    instrument_rows = {(str(row['id']), row['version']): row for row in instruments}
    resolved_accounts, resolved_instruments = {}, {}
    for (kind, entity_id), (_, version) in targets.items():
        if kind == 'account':
            row = account_rows.get((entity_id, version))
            if row is None:
                raise ProjectionUnavailable('projection_reference_missing')
            resolved_accounts[entity_id] = Account(
                entity_id, version, row['role'], row['category'], row['label'])
        else:
            row = instrument_rows.get((entity_id, version))
            if row is None:
                raise ProjectionUnavailable('projection_reference_missing')
            resolved_instruments[entity_id] = Instrument(
                entity_id, version, row['kind'], row['currency'], row['ticker'],
                row['mic'], row['symbol'], row['network'], row['settlement_identity'])
    return CurrentEntities(resolved_accounts, resolved_instruments)


def read_current_entities(connection, context: TenantContext) -> CurrentEntities:
    """Read display metadata under the accepted reader's scoped snapshot."""
    try:
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

        def rows(table, columns, condition=''):
            # Identifiers and conditions are fixed literals at these call sites.
            return execute(connection, 'SELECT ' + columns + ' FROM ' + table +
                ' WHERE tenant_id=:tenant AND portfolio_id=:portfolio' + condition,
                tenant=context.tenant_id, portfolio=context.portfolio_id).mappings().all()

        return resolve_current_entities(
            rows('wl_ingestion.mappings', 'id,revision,entity_kind,entity_id,entity_version,plan_id',
                 " AND entity_kind IN ('account','instrument')"),
            rows('wl_ingestion.accepted_plans', 'id,created_at'),
            rows('wl_pg.accounts', 'id,version,role,category,label'),
            rows('wl_pg.instruments',
                 'id,version,kind,currency,ticker,mic,symbol,network,settlement_identity'),
        )
    except ProjectionUnavailable:
        raise
    except Exception:
        raise ProjectionUnavailable('projection_reference_missing') from None
