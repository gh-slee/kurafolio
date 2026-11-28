"""Closed optional V2 wire schemas. Validation errors are never echoed to clients."""
from typing import Annotated, Literal
import re
from pydantic import BaseModel, ConfigDict, Field, AfterValidator, SecretStr, field_validator, model_validator
from kurafolio.persistence.errors import CODES
from kurafolio.projection import model


def password(value, minimum=15):
    if not minimum <= len(value) <= 256 or '\x00' in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError('Invalid password')
    return value


def canonical_uuid(value):
    from kurafolio.persistence.context import identifier
    try:
        identifier(value)
    except Exception:
        raise ValueError("Invalid UUID") from None
    return value


NewPassword = Annotated[str, Field(min_length=15, max_length=256, repr=False), AfterValidator(password)]
CurrentPassword = Annotated[str, Field(min_length=1, max_length=256, repr=False), AfterValidator(lambda v: password(v, 1))]
Username = Annotated[str, Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_.-]+$'),
                     AfterValidator(lambda v: v if re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',v) else (_ for _ in ()).throw(ValueError()))]
UUID = Annotated[str, AfterValidator(canonical_uuid)]
Token = Annotated[str, Field(min_length=43,max_length=43,pattern=r'^[A-Za-z0-9_-]+$',repr=False)]
Hex = Annotated[str, Field(min_length=64,max_length=64,pattern=r'^[0-9a-f]+$',repr=False)]
Timestamp = Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$')]


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True,hide_input_in_errors=True)

    @field_validator('password',check_fields=False)
    @classmethod
    def bounded_password(cls,value):
        password(value.get_secret_value(),1)
        return value


class Empty(Closed):
    pass


class Login(Closed):
    username: Username
    password: SecretStr = Field(min_length=1, max_length=256)


class Register(Closed):
    invite_token: Token
    username: Username
    password: SecretStr = Field(min_length=15, max_length=256)


class Setup(Closed):
    setup_token: Token
    username: Username
    password: SecretStr = Field(min_length=15, max_length=256)


class ChangePassword(Closed):
    current_password: CurrentPassword
    new_password: NewPassword


class InviteIssue(Closed):
    issue_request_id: UUID


class Alive(Closed):
    alive: Literal[True]


class Ready(Closed):
    ready: bool


class Csrf(Closed):
    csrf_token: Hex
    authenticated: bool


class LoggedIn(Closed):
    authenticated: Literal[True]
    csrf_token: Hex


class Registered(Closed):
    registered: Literal[True]


class Initialized(Closed):
    initialized: Literal[True]


class User(Closed):
    id: UUID
    username: Username
    role: Literal['instance_admin','member']


class Portfolio(Closed):
    id: UUID


class Me(Closed):
    authenticated: Literal[True]
    user: User
    portfolio: Portfolio


class Invitation(Closed):
    id: UUID
    issue_request_id: UUID | None
    created_at: Timestamp
    expires_at: Timestamp
    status: Literal['issued','expired','revoked','consumed']
    revocation_reason: Literal['manual','restore'] | None


class InvitationIssued(Closed):
    id: UUID
    issue_request_id: UUID
    invite_token: Token
    expires_at: Timestamp


class Invitations(Closed):
    items: list[Invitation]
    next_after: UUID | None


class Job(Closed):
    id: UUID
    kind: Literal['foundation']
    status: Literal['queued','running','retryable_error','succeeded','failed','cancelled']
    attempt: Annotated[int,Field(ge=0,le=3)]
    error_code: Literal[tuple(sorted(CODES | {'internal_error'}))] | None


ERROR_CODES = ('invalid_headers','invalid_host','invalid_length','not_found','method_not_allowed',
 'origin_rejected','authentication_required','invalid_credentials','csrf_rejected','anonymous_session_required',
 'unsupported_media_type','body_too_large','request_timeout','invalid_input','rate_limited','authentication_busy',
 'credentials_changed','session_changed','registration_rejected','instance_not_ready','internal_error',
 'setup_rejected','setup_closed','setup_required','admin_required','invite_already_issued','invite_not_active',
 'source_catalog_unavailable','source_unavailable','source_capability_unavailable','source_context_incompatible',
 'source_connection_conflict','source_revision_conflict','source_idempotency_conflict','source_repreview_required',
 'source_capacity_reached','source_counter_exhausted','source_commit_uncertain',
 'import_busy','import_cleanup_pending','import_commit_uncertain','import_conflict','import_evidence_unsupported','import_expired','import_invalid','import_limit','import_mapping_required','import_operation_conflict','import_reupload_required','import_runner_unavailable','import_stale','length_required','analysis_unavailable')


class ErrorDetail(Closed):
    code: Literal[ERROR_CODES]
    message: str
    request_id: Annotated[str,Field(pattern=r'^[0-9a-f]{32}$')]


class Error(Closed):
    error: ErrorDetail


# Sources are available only in the explicit0003 backend profile. These models
# contain metadata, never financial values or executable plugin configuration.
def source_counter(value):
    from kurafolio.data_sources.contract_v1 import counter
    return counter(value)


def source_text(value):
    import unicodedata
    if value != value.strip() or any(unicodedata.category(ch)=='Cc' or 0xD800<=ord(ch)<=0xDFFF for ch in value):
        raise ValueError('Invalid source label')
    return value


Counter = Annotated[str,AfterValidator(source_counter)]
PositiveCounter = Annotated[str,AfterValidator(lambda v: source_counter(v) if v!='0' else (_ for _ in ()).throw(ValueError('Positive counter required')))]
Namespace = Annotated[str,Field(min_length=1,max_length=64,pattern=r'^[a-z][a-z0-9_.-]{0,63}$')]
SourceLabel = Annotated[str,Field(min_length=1,max_length=100),AfterValidator(source_text)]
SourceAlias = Annotated[str,Field(min_length=1,max_length=160),AfterValidator(source_text)]
SourceCapability = Literal['FILE_IMPORT','PULL_API']
VersionOne = Annotated[int,Field(strict=True,ge=1,le=1)]


class SourceRealm(Closed):
    incarnation: UUID
    restore_epoch: Counter


class SourceCommon(Closed):
    operation_id: UUID
    expected_revision: Counter
    expected_realm: SourceRealm


class SourceEnableRequest(SourceCommon):
    enabled: bool
    installation_id: Hex | None

    @model_validator(mode='after')
    def installation_required(self):
        if self.enabled != (self.installation_id is not None):
            raise ValueError('Explicit installation confirmation required')
        return self


class SourceCreateRequest(SourceCommon):
    plugin_id: Namespace
    capability: SourceCapability
    installation_id: Hex
    display_label: SourceLabel
    parser_source_alias: SourceAlias | None

    @model_validator(mode='after')
    def initial_revision(self):
        if self.expected_revision!='0':
            raise ValueError('Create revision must be zero')
        return self


class SourceUpdateRequest(SourceCommon):
    enabled: bool
    installation_id: Hex
    display_label: SourceLabel


class SourceEnablement(Closed):
    enabled: bool
    installation_id: Hex | None
    revision: Counter
    generation: Counter


class Capability(Closed):
    capability: SourceCapability
    active_installation_id: Hex | None
    availability_generation: PositiveCounter | None
    adapter_id: Namespace | None
    package_version: Annotated[str,Field(min_length=1,max_length=200)] | None
    format_versions: Annotated[list[Annotated[str,Field(min_length=1,max_length=128)]],Field(max_length=32)]
    domain_contract_version: VersionOne
    parser_api_version: Annotated[int,Field(strict=True,ge=2,le=2)] | None
    enablement: SourceEnablement
    status: Literal['DISABLED','CONFIRMATION_REQUIRED','UNAVAILABLE','ENABLED']
    reason: Literal['source_unavailable','source_capability_unavailable','source_counter_exhausted'] | None
    connection_count: Annotated[int,Field(strict=True,ge=0,le=256)]


class CatalogItem(Closed):
    plugin_id: Namespace
    provider_id: Namespace
    display_name: Annotated[str,Field(min_length=1,max_length=100)]
    publisher_label: Annotated[str,Field(min_length=1,max_length=100)]
    docs_url: Annotated[str,Field(max_length=1024)] | None
    capabilities: Annotated[list[Capability],Field(max_length=2)]


class SourceCatalogPage(Closed):
    items: Annotated[list[CatalogItem],Field(max_length=100)]
    next_after: Namespace | None
    catalog_revision: Counter
    state_revision: Counter
    realm: SourceRealm


class SourceConnection(Closed):
    id: UUID
    connection_version: Hex
    plugin_id: Namespace
    provider_id: Namespace
    capability: Literal['FILE_IMPORT']
    installation_id: Hex
    availability_generation: PositiveCounter
    display_label: SourceLabel
    parser_source_alias: SourceAlias | None
    enabled: bool
    revision: Counter
    generation: Counter
    status: Literal['DISABLED','SOURCE_DISABLED','CONFIRMATION_REQUIRED','UNAVAILABLE','ENABLED']
    reason: Literal['source_unavailable','source_context_incompatible','source_counter_exhausted'] | None


class SourceConnectionPage(Closed):
    items: Annotated[list[SourceConnection],Field(max_length=100)]
    next_after: UUID | None
    catalog_revision: Counter
    state_revision: Counter
    realm: SourceRealm


class SourceConnectionRead(Closed):
    resource: SourceConnection
    catalog_revision: Counter
    state_revision: Counter
    realm: SourceRealm


class SourceMutation(Closed):
    operation_id: UUID
    replayed: bool
    representation: Literal['committed','historical']
    changed: bool
    resource: SourceEnablement | SourceConnection
    catalog_revision: Counter
    state_revision: Counter
    realm: SourceRealm


class SourceEnableMutation(SourceMutation):
    resource: SourceEnablement


class SourceConnectionMutation(SourceMutation):
    resource: SourceConnection


def import_openapi_extra(route):
    """Reference code-owned frozen DTOs without a second model definition."""
    result = {'responses': {str(route['success_status']): {
        'description': 'Successful response', 'content': {'application/json': {
            'schema': {'$ref': '#/components/schemas/' + route['response']}}}}}}
    if route['request'] in {'Create', 'Decide', 'Confirm', 'Cancel'}:
        result['requestBody'] = {'required': True, 'content': {'application/json': {
            'schema': {'$ref': '#/components/schemas/' + route['request']}}}}
    if route['method'] == 'GET' and route['response'] in {'SetList', 'PreviewPage'}:
        from kurafolio.ingestion.cursors import MAX_TOKEN, STATES

        parameters = [
            {'name': 'cursor', 'in': 'query', 'required': False,
             'description': 'Signed next_cursor from the previous page.',
             'schema': {'type': 'string', 'maxLength': MAX_TOKEN}},
            {'name': 'limit', 'in': 'query', 'required': False,
             'schema': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 50}},
        ]
        if route['response'] == 'SetList':
            parameters.append({'name': 'state', 'in': 'query', 'required': False,
                               'schema': {'type': 'string', 'enum': list(STATES)}})
        result['parameters'] = parameters
    return result


def install_import_openapi(app, routes):
    """Install only the frozen definitions reachable from the supplied routes."""
    from kurafolio.ingestion.contracts import definition, CORE_NAMES
    original = app.openapi

    def openapi():
        if app.openapi_schema is not None:
            return app.openapi_schema
        document = original()
        definitions = document.setdefault('components', {}).setdefault('schemas', {})
        visited = set()

        def add(name, namespace):
            key = (name, namespace)
            if key in visited:
                return
            visited.add(key)
            definitions[name] = rewrite(definition(name, namespace), namespace)

        def rewrite(value, namespace):
            if type(value) is list:
                return [rewrite(x, namespace) for x in value]
            if type(value) is not dict:
                return value
            result = {}
            for key, item in value.items():
                if key == '$ref':
                    prefix, name = item.split('#/$defs/', 1)
                    target = {'codec-schema.json': 'core', 'wire-contracts.json': 'wire',
                              'frozen-shapes.json': 'frozen'}.get(prefix, namespace)
                    add(name, target)
                    result[key] = '#/components/schemas/' + name
                else:
                    result[key] = rewrite(item, namespace)
            return result

        for route in routes:
            for name in (route['request'], route['response']):
                if name and not name.startswith(('QUERY_', 'RAW_')):
                    add(name, 'core' if name in CORE_NAMES else 'wire')
        app.openapi_schema = document
        return document

    app.openapi = openapi


# Analysis read contract, version 1.
DecimalString = Annotated[str, Field(
    min_length=1, max_length=256, pattern=r'^-?(0|[1-9][0-9]*)(\.[0-9]+)?$')]
ReportCurrency = Literal['CAD', 'USD', 'TWD']
NativeCurrency = Annotated[str, Field(pattern=r'^[A-Z]{3}$')]
DateString = Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
Text = Annotated[str, Field(min_length=0, max_length=4096)]
TimeToken = Annotated[str, Field(min_length=1, max_length=4096)]
GapCode = Literal[*sorted(model.GAP_CODES)]
AssumptionCode = Literal[*sorted(model.ASSUMPTION_CODES)]
ExcludedCode = Literal[*model.EXCLUDED_CODES]
ReasonCode = Literal[*sorted(model.GAP_CODES | {
    'sales_counted', 'no_positions', 'no_eligible_acquisitions',
    'value_cost_currency_differs', 'cost_allocation_unresolved',
})]
AssetClass = Literal['securities', 'cash', 'crypto', 'unsupported']
Count = Annotated[int, Field(ge=0)]


class Amount(Closed):
    amount: DecimalString
    currency: NativeCurrency


class FactGeneration(Closed):
    accepted: Counter
    mapping: Counter


class Figure(Closed):
    status: Literal['available', 'partial', 'unavailable']
    known_subtotal: DecimalString | None
    complete_total: DecimalString | None
    counted_count: Count
    position_count: Count
    reasons: list[ReasonCode]


class AnalysisAccount(Closed):
    id: UUID
    label: Text
    category: Text
    role: Literal['investment', 'crypto', 'funding']


class AnalysisInstrument(Closed):
    id: UUID
    kind: Literal['SECURITY', 'CASH', 'CRYPTO', 'UNSUPPORTED']
    currency: NativeCurrency | None
    ticker: Text | None
    mic: Text | None
    symbol: Text | None
    network: Text | None


class AnalysisRow(Closed):
    asset_class: AssetClass
    account: AnalysisAccount
    instrument: AnalysisInstrument
    quantity: DecimalString | None
    btc_equivalent: bool
    value: Amount | None
    value_converted: DecimalString | None
    value_basis: Literal['quote', 'source_reported', 'par'] | None
    value_as_of: TimeToken | None
    cost: Amount | None
    cost_converted: DecimalString | None
    cost_status: Literal['known', 'unavailable', 'not_applicable']
    book_cost_cad: Amount | None
    unrealized_gain: Amount | None
    unrealized_gain_converted: DecimalString | None
    codes: list[AssumptionCode]
    gaps: list[GapCode]


class ClassLine(Closed):
    asset_class: AssetClass
    value: Figure
    native_known: list[Amount]


class Observation(Closed):
    account_id: UUID
    observed_at: TimeToken
    coverage_status: Literal['complete', 'partial', 'unknown']
    position_count: Count


class GapItem(Closed):
    code: GapCode
    account_id: UUID | None
    instrument_id: UUID | None


class BtcReference(Closed):
    status: Literal['available', 'unavailable']
    price: Amount | None
    as_of: Timestamp | None
    source: Text | None


class FxReference(Closed):
    currency: Literal['CAD', 'TWD']
    per_pivot: DecimalString
    effective_date: DateString
    source: Text


class References(Closed):
    btc: BtcReference
    fx_pivot: Literal['USD']
    fx: list[FxReference]


class AnalysisBase(Closed):
    contract_version: Literal[1]
    calculation_id: Hex
    fact_generation: FactGeneration
    valuation_time: Timestamp
    report_currency: ReportCurrency
    references: References
    value: Figure
    cost: Figure
    unrealized_gain: Figure
    lines: list[ClassLine]
    rows: list[AnalysisRow]
    observations: list[Observation]
    assumptions: list[AssumptionCode]
    gaps: list[GapItem]


class CountedActivityRow(Closed):
    economic_group_id: UUID
    kind: Literal['BUY', 'SELL']
    account_id: UUID
    instrument_id: UUID
    quantity: DecimalString
    cost: Amount | None
    occurred_at: TimeToken
    has_crypto_fee: bool


class PurchaseRate(Closed):
    status: Literal['available', 'unavailable']
    rate: Amount | None
    reasons: list[ReasonCode]


class CryptoDetail(Closed):
    basis: Literal['acquisitions_assumed_held']
    state: Literal['tracked', 'no_eligible_acquisitions']
    btc_equivalent_quantity: DecimalString | None
    purchases_counted: Count
    sales_counted: bool
    sales_counted_count: Count
    excluded: dict[ExcludedCode, Count]
    activities: list[CountedActivityRow]
    spending: Figure
    purchase_rate: PurchaseRate


class SecuritiesAnalysis(AnalysisBase):
    scope: Literal['securities']


class TotalAnalysis(AnalysisBase):
    scope: Literal['total']


class CryptoAnalysis(AnalysisBase):
    scope: Literal['crypto']
    crypto: CryptoDetail
