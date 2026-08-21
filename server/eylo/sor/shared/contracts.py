"""Vendor-neutral SOR lifecycle, state, schema, and execution contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from eylo.modules.connections.domain import ConnectionAuthKind


class SorProfile(str, Enum):
    """Stable domain namespaces exposed by the SOR product."""

    CRM = "crm"
    TICKETING = "ticketing"
    SUPPORT = "support"
    KNOWLEDGE = "knowledge"


class SorSourceState(str, Enum):
    """Persisted lifecycle of one configured source."""

    DRAFT = "DRAFT"
    VERIFYING = "VERIFYING"
    DISCOVERING = "DISCOVERING"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    DISABLED = "DISABLED"


class SorSourceTransition(str, Enum):
    """Commands that move one source through its lifecycle."""

    BEGIN_VERIFICATION = "begin_verification"
    VERIFICATION_SUCCEEDED = "verification_succeeded"
    VERIFICATION_FAILED = "verification_failed"
    DISCOVERY_SUCCEEDED = "discovery_succeeded"
    DISCOVERY_FAILED = "discovery_failed"
    BEGIN_BOOTSTRAP = "begin_bootstrap"
    BOOTSTRAP_SUCCEEDED = "bootstrap_succeeded"
    BOOTSTRAP_FAILED = "bootstrap_failed"
    SYNC_SUCCEEDED = "sync_succeeded"
    SYNC_FAILED = "sync_failed"
    REAUTHORIZATION_REQUIRED = "reauthorization_required"
    DISABLE = "disable"
    REENABLE = "reenable"


class SorSourceTransitionError(Exception):
    """A source lifecycle command is not valid from its current state."""


_SOURCE_TRANSITIONS: dict[
    tuple[SorSourceState, SorSourceTransition], SorSourceState
] = {
    (SorSourceState.DRAFT, SorSourceTransition.BEGIN_VERIFICATION): (
        SorSourceState.VERIFYING
    ),
    (SorSourceState.REAUTH_REQUIRED, SorSourceTransition.BEGIN_VERIFICATION): (
        SorSourceState.VERIFYING
    ),
    (SorSourceState.DEGRADED, SorSourceTransition.BEGIN_VERIFICATION): (
        SorSourceState.VERIFYING
    ),
    (SorSourceState.VERIFYING, SorSourceTransition.VERIFICATION_SUCCEEDED): (
        SorSourceState.DISCOVERING
    ),
    (SorSourceState.VERIFYING, SorSourceTransition.VERIFICATION_FAILED): (
        SorSourceState.DEGRADED
    ),
    (SorSourceState.DISCOVERING, SorSourceTransition.DISCOVERY_SUCCEEDED): (
        SorSourceState.DRAFT
    ),
    (SorSourceState.DISCOVERING, SorSourceTransition.DISCOVERY_FAILED): (
        SorSourceState.DEGRADED
    ),
    (SorSourceState.DRAFT, SorSourceTransition.BEGIN_BOOTSTRAP): (
        SorSourceState.BOOTSTRAPPING
    ),
    (SorSourceState.ACTIVE, SorSourceTransition.BEGIN_BOOTSTRAP): (
        SorSourceState.BOOTSTRAPPING
    ),
    (SorSourceState.DEGRADED, SorSourceTransition.BEGIN_BOOTSTRAP): (
        SorSourceState.BOOTSTRAPPING
    ),
    (SorSourceState.BOOTSTRAPPING, SorSourceTransition.BOOTSTRAP_SUCCEEDED): (
        SorSourceState.ACTIVE
    ),
    (SorSourceState.DEGRADED, SorSourceTransition.BOOTSTRAP_SUCCEEDED): (
        SorSourceState.ACTIVE
    ),
    (SorSourceState.BOOTSTRAPPING, SorSourceTransition.BOOTSTRAP_FAILED): (
        SorSourceState.DEGRADED
    ),
    (SorSourceState.DEGRADED, SorSourceTransition.BOOTSTRAP_FAILED): (
        SorSourceState.DEGRADED
    ),
    (SorSourceState.ACTIVE, SorSourceTransition.SYNC_SUCCEEDED): (
        SorSourceState.ACTIVE
    ),
    (SorSourceState.DEGRADED, SorSourceTransition.SYNC_SUCCEEDED): (
        SorSourceState.ACTIVE
    ),
    (SorSourceState.ACTIVE, SorSourceTransition.SYNC_FAILED): (SorSourceState.DEGRADED),
    (SorSourceState.DEGRADED, SorSourceTransition.SYNC_FAILED): (
        SorSourceState.DEGRADED
    ),
    (SorSourceState.DISABLED, SorSourceTransition.REENABLE): (SorSourceState.VERIFYING),
}

for _state in (
    SorSourceState.DRAFT,
    SorSourceState.VERIFYING,
    SorSourceState.DISCOVERING,
    SorSourceState.BOOTSTRAPPING,
    SorSourceState.ACTIVE,
    SorSourceState.DEGRADED,
    SorSourceState.REAUTH_REQUIRED,
):
    _SOURCE_TRANSITIONS[(_state, SorSourceTransition.REAUTHORIZATION_REQUIRED)] = (
        SorSourceState.REAUTH_REQUIRED
    )

for _state in SorSourceState:
    if _state is not SorSourceState.DISABLED:
        _SOURCE_TRANSITIONS[(_state, SorSourceTransition.DISABLE)] = (
            SorSourceState.DISABLED
        )


def transition_source_state(
    current: SorSourceState,
    transition: SorSourceTransition,
) -> SorSourceState:
    """Return the only permitted next state or reject the command."""
    next_state = _SOURCE_TRANSITIONS.get((current, transition))
    if next_state is None:
        raise SorSourceTransitionError(
            f"Source transition '{transition.value}' is invalid from '{current.value}'."
        )
    return next_state


class SorChangeStrategy(str, Enum):
    """How an adapter advances one selected stream."""

    DELTA = "DELTA"
    CURSOR = "CURSOR"
    UPDATED_AT = "UPDATED_AT"
    FULL_RECONCILE = "FULL_RECONCILE"


class SorMappingState(str, Enum):
    """Lifecycle of one immutable mapping revision."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    INVALID = "INVALID"
    SUPERSEDED = "SUPERSEDED"


class SorFieldMappingDirection(str, Enum):
    """Permitted flow for one discovered source field."""

    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"
    IGNORE = "IGNORE"


class SorFieldMappingState(str, Enum):
    """Compatibility of one field mapping with its source schema."""

    ACTIVE = "ACTIVE"
    INCOMPATIBLE = "INCOMPATIBLE"


class SorTransformKind(str, Enum):
    """Bounded code-owned transforms available to mapping rows."""

    DIRECT = "DIRECT"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    MONEY = "MONEY"
    RICH_TEXT_TO_PLAIN_TEXT = "RICH_TEXT_TO_PLAIN_TEXT"
    ENUM = "ENUM"
    IDENTITY_REFERENCE = "IDENTITY_REFERENCE"
    ARRAY = "ARRAY"


class SorCustomFieldType(str, Enum):
    """Queryable storage type for one source-defined field."""

    TEXT = "TEXT"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    STRING_ARRAY = "STRING_ARRAY"
    REFERENCE = "REFERENCE"
    BOUNDED_JSON = "BOUNDED_JSON"


class SorSensitivity(str, Enum):
    """Operator-selected handling label for projected source data."""

    STANDARD = "STANDARD"
    PERSONAL = "PERSONAL"
    SENSITIVE = "SENSITIVE"


class SorStreamState(str, Enum):
    """Operational availability of one selected source stream."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"


class SorSyncRunKind(str, Enum):
    """Reason one durable projection run exists."""

    SCHEMA = "SCHEMA"
    BOOTSTRAP = "BOOTSTRAP"
    INCREMENTAL = "INCREMENTAL"
    WEBHOOK_REFETCH = "WEBHOOK_REFETCH"
    RECONCILIATION = "RECONCILIATION"
    REPROJECTION = "REPROJECTION"


class SorWorkState(str, Enum):
    """Product projection of Absurd-owned durable work."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SorWebhookReceiptState(str, Enum):
    """Processing lifecycle of one verified webhook delivery."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class SorCommandState(str, Enum):
    """Durable result of one Agent-requested vendor mutation."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CONFLICT = "CONFLICT"
    CANCELLED = "CANCELLED"


class SorSourceAccess(str, Enum):
    """Maximum source authority granted to one Agent."""

    READ = "READ"
    READ_WRITE = "READ_WRITE"


class SorProjectionDisposition(str, Enum):
    """Result of idempotently applying one source record snapshot."""

    ADDED = "ADDED"
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"


class SorToolEffect(str, Enum):
    """Whether a profile tool reads or mutates the authoritative source."""

    READ = "READ"
    MUTATION = "MUTATION"


class SorImplementationStatus(str, Enum):
    """Catalog status derived from whether an executable factory exists."""

    PLANNED = "PLANNED"
    AVAILABLE = "AVAILABLE"


class SorConfigurationFieldKind(str, Enum):
    """Input shape for one non-secret, adapter-owned source setting."""

    STRING_LIST = "STRING_LIST"


@dataclass(frozen=True, slots=True)
class SorCanonicalFieldSpec:
    """One stable Eylo-owned field available as a mapping target."""

    key: str
    label: str
    description: str
    data_type: str
    writable: bool = True
    required: bool = False


@dataclass(frozen=True, slots=True)
class SorEntitySpec:
    """One canonical entity exposed by a profile."""

    key: str
    label: str
    description: str
    fields: tuple[SorCanonicalFieldSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class SorToolSpec:
    """One stable profile-native Agent tool name."""

    name: str
    effect: SorToolEffect
    description: str
    primary_entity: str
    target_entities: frozenset[str]
    entities: frozenset[str]


@dataclass(frozen=True, slots=True)
class SorProfileSpec:
    """Human and Agent-facing contract for one SOR profile."""

    profile: SorProfile
    label: str
    description: str
    entities: tuple[SorEntitySpec, ...]
    tools: tuple[SorToolSpec, ...]


@dataclass(frozen=True, slots=True)
class SorVendorCandidate:
    """A roadmap catalog entry that does not claim an executable adapter."""

    profile: SorProfile
    vendor_key: str
    display_name: str
    description: str
    planned_auth_kinds: tuple[ConnectionAuthKind, ...]
    requires_instance_origin: bool = False
    setup_notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SorVendorStreamSpec:
    """One explicit vendor object operators may select for synchronization."""

    key: str
    label: str
    description: str
    canonical_entity: str
    change_strategies: frozenset[SorChangeStrategy]
    scope_category: str | None = None


@dataclass(frozen=True, slots=True)
class SorOAuthOriginOption:
    """One exact API region and the consent host paired with it."""

    api_origin: str
    authorization_origin: str
    label: str


@dataclass(frozen=True, slots=True)
class SorOAuthSpec:
    """Pinned OAuth protocol facts owned by one executable vendor adapter."""

    authorization_url: str | None = None
    token_url: str | None = None
    authorization_path: str | None = None
    token_path: str | None = None
    base_scopes: tuple[str, ...] = ()
    scope_delimiter: str = " "
    scope_response_delimiter: str | None = None
    authorization_params: tuple[tuple[str, str], ...] = ()
    authorization_response_type: str | None = "code"
    send_authorization_scope: bool = True
    token_request_format: Literal["form", "json"] = "form"
    token_client_auth_method: Literal["body", "basic"] = "body"
    token_grant_type: str | None = "authorization_code"
    send_token_redirect_uri: bool = True
    pkce: bool = False
    instance_origin_field: str | None = None
    instance_host_suffixes: tuple[str, ...] = ()
    instance_origin_options: tuple[SorOAuthOriginOption, ...] = ()
    operator_instance_origin: bool = False


@dataclass(frozen=True, slots=True)
class SorAdapterConfigurationFieldSpec:
    """One schema-driven non-secret source setting rendered by the console."""

    key: str
    label: str
    description: str
    kind: SorConfigurationFieldKind
    required: bool = False
    placeholder: str | None = None
    minimum_items: int = 0
    maximum_items: int = 100


@dataclass(frozen=True, slots=True)
class SorAdapterCapabilityManifest:
    """Executable facts declared only beside a real adapter factory."""

    profile: SorProfile
    vendor_key: str
    auth_kinds: tuple[ConnectionAuthKind, ...]
    streams: tuple[SorVendorStreamSpec, ...]
    readable_entities: frozenset[str]
    writable_entities: frozenset[str]
    readable_tools: frozenset[str]
    writable_tools: frozenset[str]
    change_strategies: frozenset[SorChangeStrategy]
    configuration_fields: tuple[SorAdapterConfigurationFieldSpec, ...] = ()
    required_scopes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    custom_object_required_scopes: tuple[str, ...] = ()
    custom_object_change_strategies: frozenset[SorChangeStrategy] = frozenset()
    tool_required_scopes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    tool_streams: Mapping[str, frozenset[str]] = field(default_factory=dict)
    mutation_result_streams: Mapping[str, str] = field(default_factory=dict)
    oauth: SorOAuthSpec | None = None
    fixed_origin: str | None = None
    requires_instance_origin: bool = False
    supports_webhooks: bool = False
    supports_deletions: bool = False
    supports_custom_fields: bool = False
    supports_custom_objects: bool = False
    supports_conditional_writes: bool = False
    supports_history: bool = False
    supports_comments: bool = False
    supports_attachments: bool = False
    supports_structured_documents: bool = False


@dataclass(frozen=True, slots=True)
class SorAdapterFieldSelection:
    """One field selected by the active mapping and exposed to an adapter."""

    vendor_object_key: str
    vendor_field_key: str
    agent_key: str
    writable: bool


@dataclass(frozen=True, slots=True)
class SorAdapterContext:
    """Resolved, tenant-owned inputs used to construct one adapter instance."""

    organization_id: UUID
    source_id: UUID
    external_connection_id: UUID
    vendor_key: str
    auth_kind: ConnectionAuthKind
    instance_origin: str | None
    granted_scopes: frozenset[str]
    selected_objects: tuple[str, ...]
    mapping_revision_id: UUID | None
    fields: tuple[SorAdapterFieldSelection, ...]
    credentials: Mapping[str, object] = field(repr=False)
    webhook_signing_secret: str | None = field(default=None, repr=False)
    configuration: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SorConnectionVerification:
    """Bounded result of checking one configured external account."""

    account_external_id: str | None = None
    account_display_name: str | None = None
    granted_scopes: tuple[str, ...] = ()
    vendor_api_version: str | None = None


@dataclass(frozen=True, slots=True)
class SorDiscoveredField:
    """One stable field identity discovered from a vendor object."""

    key: str
    label: str
    data_type: str
    nullable: bool
    writable: bool
    choices: tuple[str, ...] = ()
    description: str | None = None
    group: str | None = None


@dataclass(frozen=True, slots=True)
class SorDiscoveredObject:
    """One source object and its stable fields."""

    key: str
    label: str
    fields: tuple[SorDiscoveredField, ...]
    custom: bool = False


@dataclass(frozen=True, slots=True)
class SorDiscoveredSchema:
    """Complete immutable discovery result from one adapter invocation."""

    objects: tuple[SorDiscoveredObject, ...]
    vendor_api_version: str | None = None


@dataclass(frozen=True, slots=True)
class SorExternalRecord:
    """One source record before profile normalization and projection."""

    vendor_object_key: str
    external_id: str
    payload: Mapping[str, object]
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    source_revision: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class SorRecordPage:
    """One bounded page plus the opaque checkpoint it covers."""

    records: tuple[SorExternalRecord, ...]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class SorDeletedRecord:
    """One source identity the vendor reports deleted or archived."""

    vendor_object_key: str
    external_id: str
    deleted_at: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SorWebhookSubscription:
    """Vendor subscription identity and renewal deadline."""

    external_id: str
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SorWebhookSignal:
    """Verified hint that identifies records to refetch."""

    delivery_id: str | None
    event_type: str
    vendor_object_key: str | None
    external_id: str | None
    occurred_at: datetime | None


@dataclass(frozen=True, slots=True)
class SorCommandRequest:
    """One typed, idempotent authoritative-source mutation."""

    tool_name: str
    idempotency_key: str
    payload: Mapping[str, object]
    target_external_id: str | None = None
    expected_source_revision: str | None = None


@dataclass(frozen=True, slots=True)
class SorCommandResult:
    """Vendor mutation result used for receipt completion and refetch."""

    vendor_object_key: str
    external_id: str
    external_request_id: str | None = None
    source_revision: str | None = None
    source_url: str | None = None
    response: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SorFieldMappingDraft:
    """Operator-selected target for one exact discovered source field."""

    vendor_object_key: str
    vendor_field_key: str
    canonical_target_path: str | None = None
    custom_type: SorCustomFieldType | None = None
    transform_kind: SorTransformKind = SorTransformKind.DIRECT
    transform_config: Mapping[str, object] = field(default_factory=dict)
    direction: SorFieldMappingDirection = SorFieldMappingDirection.READ_ONLY
    agent_visible: bool = False
    ui_default_column: bool = False
    sensitivity: SorSensitivity = SorSensitivity.STANDARD


@dataclass(frozen=True, slots=True)
class SorStreamDraft:
    """Operator-selected execution policy for one source object."""

    vendor_object_key: str
    canonical_entity_kind: str
    strategy: SorChangeStrategy
    lookback_seconds: int = 0
    schedule: str | None = None


@dataclass(frozen=True, slots=True)
class SorSchemaDifference:
    """Human-auditable difference between two immutable discoveries."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    renamed: tuple[str, ...] = ()
    type_changed: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return any((self.added, self.removed, self.renamed, self.type_changed))


@dataclass(frozen=True, slots=True)
class SorProjectionOutcome:
    """Canonical values and record identity produced by shared projection."""

    record_id: UUID
    disposition: SorProjectionDisposition
    canonical_values: Mapping[str, object]
    custom_field_keys: tuple[str, ...]


@runtime_checkable
class SorLifecycleAdapter(Protocol):
    """Shared lifecycle every profile adapter implements explicitly."""

    async def verify_connection(self) -> SorConnectionVerification: ...

    async def discover_schema(self) -> SorDiscoveredSchema: ...

    async def bootstrap_stream(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage: ...

    async def pull_changes(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage: ...

    async def fetch_record(
        self,
        *,
        vendor_object_key: str,
        external_id: str,
    ) -> SorExternalRecord: ...

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]: ...

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription: ...

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription: ...

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None: ...

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None: ...

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]: ...

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult: ...

    async def close(self) -> None: ...


class SorCapabilityUnavailable(Exception):
    """The adapter manifest says an optional lifecycle capability is absent."""


class SorVendorOperationError(Exception):
    """A safe vendor failure with durable retry and authorization semantics."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        requires_reauthorization: bool = False,
        refreshable_authorization: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.requires_reauthorization = requires_reauthorization
        self.refreshable_authorization = refreshable_authorization


class SorExternalRecordNotFound(Exception):
    """A verified source lookup proves the requested record is gone."""

    def __init__(
        self,
        *,
        vendor_object_key: str,
        external_id: str,
        reason: str = "Deleted or archived in the authoritative source",
        deleted_at: datetime | None = None,
    ) -> None:
        super().__init__(reason)
        self.vendor_object_key = vendor_object_key
        self.external_id = external_id
        self.reason = reason
        self.deleted_at = deleted_at


class SorWebhookVerificationError(Exception):
    """A webhook signature, timestamp, or replay proof is invalid."""


class SorWebhookPayloadError(Exception):
    """A verified webhook cannot be normalized into bounded source signals."""


class SorCommandRevisionConflict(Exception):
    """A command observed source state newer than its pinned target version."""


def require_unique_names(values: Sequence[str], *, kind: str) -> None:
    """Reject duplicate catalog names before they become an ambiguous API."""
    if len(values) != len(set(values)):
        raise ValueError(f"SOR {kind} names must be unique.")


__all__ = [
    "SorAdapterCapabilityManifest",
    "SorAdapterConfigurationFieldSpec",
    "SorAdapterContext",
    "SorAdapterFieldSelection",
    "SorCanonicalFieldSpec",
    "SorCapabilityUnavailable",
    "SorChangeStrategy",
    "SorCommandRevisionConflict",
    "SorCommandState",
    "SorCommandRequest",
    "SorCommandResult",
    "SorConnectionVerification",
    "SorConfigurationFieldKind",
    "SorDeletedRecord",
    "SorDiscoveredField",
    "SorDiscoveredObject",
    "SorDiscoveredSchema",
    "SorEntitySpec",
    "SorExternalRecordNotFound",
    "SorExternalRecord",
    "SorCustomFieldType",
    "SorFieldMappingDraft",
    "SorFieldMappingDirection",
    "SorFieldMappingState",
    "SorImplementationStatus",
    "SorLifecycleAdapter",
    "SorMappingState",
    "SorOAuthOriginOption",
    "SorOAuthSpec",
    "SorProfile",
    "SorProfileSpec",
    "SorProjectionDisposition",
    "SorProjectionOutcome",
    "SorRecordPage",
    "SorSchemaDifference",
    "SorSensitivity",
    "SorSourceAccess",
    "SorSourceState",
    "SorSourceTransition",
    "SorSourceTransitionError",
    "SorStreamState",
    "SorStreamDraft",
    "SorSyncRunKind",
    "SorToolEffect",
    "SorToolSpec",
    "SorTransformKind",
    "SorVendorCandidate",
    "SorVendorOperationError",
    "SorVendorStreamSpec",
    "SorWebhookReceiptState",
    "SorWebhookPayloadError",
    "SorWebhookSignal",
    "SorWebhookSubscription",
    "SorWebhookVerificationError",
    "SorWorkState",
    "require_unique_names",
    "transition_source_state",
]
