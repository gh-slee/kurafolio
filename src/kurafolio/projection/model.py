"""Frozen calculation inputs and JSON-safe outputs; no persistence or registration."""
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import hashlib
from typing import Mapping

from kurafolio.ingestion.codec import encode
from kurafolio.market.contract import Listing, Quote

GAP_CODES = frozenset(('value_unavailable', 'quote_unavailable', 'quote_currency_mismatch',
    'fx_unavailable', 'valuation_not_implemented', 'unsupported_position',
    'corporate_action_unresolved', 'cost_unavailable', 'cost_currency_mixed',
    'sales_exceed_purchases', 'sale_shape_unsupported'))
ASSUMPTION_CODES = frozenset(('acquisitions_assumed_held', 'sales_counted',
    'valued_as_btc_equivalent', 'crypto_fees_not_deducted', 'source_reported_value',
    'missing_from_newer_snapshot_is_sold'))
EXCLUDED_CODES = ('pending', 'cancelled', 'unsupported', 'void', 'mirror',
                  'not_acquisition', 'non_crypto_purchase', 'balance_observation')


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    version: str
    role: str
    category: str
    label: str


@dataclass(frozen=True, slots=True)
class Instrument:
    id: str
    version: str
    kind: str
    currency: str | None
    ticker: str | None
    mic: str | None
    symbol: str | None
    network: str | None
    settlement_identity: str | None


@dataclass(frozen=True, slots=True)
class PositionFact:
    revision_id: str
    account: Account
    instrument: Instrument
    quantity: Decimal
    market_value: Money | None
    cost_native: Money | None
    cost_cad: Money | None
    observed_at: dict
    unsupported_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HoldingsHead:
    key_digest: str
    account: Account
    scope: dict
    snapshot_revision_id: str
    observed_at: dict
    coverage_status: str
    positions: tuple[PositionFact, ...]


@dataclass(frozen=True, slots=True)
class Leg:
    account: Account
    instrument: Instrument
    quantity: Decimal
    role: str


@dataclass(frozen=True, slots=True)
class ActivityFact:
    economic_group_id: str
    revision_id: str
    active: bool
    mirror: bool
    kind: str
    status: str
    unsupported_reasons: tuple[str, ...]
    source_account: Account
    legs: tuple[Leg, ...]
    acquisition_cost: Money | None
    has_crypto_fee: bool
    occurred_at: dict


@dataclass(frozen=True, slots=True)
class AcceptedState:
    tenant_id: str
    portfolio_id: str
    accepted_generation: int
    mapping_generation: int
    holdings: tuple[HoldingsHead, ...]
    activities: tuple[ActivityFact, ...]


@dataclass(frozen=True, slots=True)
class CryptoQuote:
    symbol: str
    price: Decimal
    currency: str
    as_of: datetime
    source: str


@dataclass(frozen=True, slots=True)
class FxTable:
    pivot: str
    per_pivot: Mapping[str, Decimal]
    as_of: datetime
    source: str


@dataclass(frozen=True, slots=True)
class ValuationInputs:
    valuation_time: datetime
    report_currencies: tuple[str, ...]
    fx: FxTable | None
    security_quotes: Mapping[Listing, Quote]
    crypto_quotes: Mapping[str, CryptoQuote]


@dataclass(frozen=True, slots=True)
class PositionResult:
    asset_class: str
    account_id: str
    instrument_id: str
    quantity: Decimal | None
    btc_equivalent: bool
    value: Money | None
    value_basis: str | None
    value_as_of: str | None
    values: Mapping[str, Decimal | None]
    cost: Money | None
    cost_status: str
    book_cost_cad: Money | None
    unrealized_gain: Money | None
    gain_values: Mapping[str, Decimal | None]
    codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClassResult:
    position_count: int
    unknown_value_count: int
    known_subtotal: Mapping[str, Decimal | None]
    complete_total: Mapping[str, Decimal | None]
    native_known: Mapping[str, Decimal]


@dataclass(frozen=True, slots=True)
class ObservationResult:
    account_id: str
    key_digest: str
    observed_at: str
    coverage_status: str
    position_count: int


@dataclass(frozen=True, slots=True)
class CryptoSummary:
    basis: str
    btc_equivalent_quantity: Decimal | None
    purchases_counted: int
    sales_counted: bool
    sales_counted_count: int
    excluded: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class Gap:
    code: str
    account_id: str | None
    instrument_id: str | None


@dataclass(frozen=True, slots=True)
class Calculation:
    calculation_id: str
    tenant_id: str
    portfolio_id: str
    accepted_generation: int
    mapping_generation: int
    valuation_time: datetime
    report_currencies: tuple[str, ...]
    fx_as_of: datetime | None
    fx_source: str | None
    positions: tuple[PositionResult, ...]
    observations: tuple[ObservationResult, ...]
    classes: Mapping[str, ClassResult]
    total: ClassResult
    crypto: CryptoSummary
    gaps: tuple[Gap, ...]
    assumptions: tuple[str, ...]


def _document(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _document(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _document(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_document(item) for item in value]
    return value


def to_document(calculation: Calculation) -> dict:
    """Render every Decimal as a decimal string, without display rounding."""
    return _document(calculation)


def calculation_id(state: AcceptedState, inputs: ValuationInputs) -> str:
    """Bind one accepted generation pair to every injected valuation input."""
    canonical = {
        'valuation_time': inputs.valuation_time.isoformat(),
        'report_currencies': list(inputs.report_currencies),
        'fx': _document(inputs.fx),
        'security_quotes': [{'key': listing.key(), 'quote': _document(quote)}
                            for listing, quote in sorted(inputs.security_quotes.items())],
        'crypto_quotes': [{'key': symbol, 'quote': _document(quote)}
                          for symbol, quote in sorted(inputs.crypto_quotes.items())],
    }
    return hashlib.sha256(encode({'format': 'kurafolio-calculation', 'version': 1,
        'tenant_id': state.tenant_id, 'portfolio_id': state.portfolio_id,
        'accepted_generation': str(state.accepted_generation),
        'mapping_generation': str(state.mapping_generation), 'inputs': canonical})).hexdigest()
