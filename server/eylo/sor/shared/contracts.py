"""Vendor-neutral SOR lifecycle, state, schema, and execution contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    InstanceOf,
    JsonValue,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.shared.json_values import SorJsonValue, to_json_value


class _SorValue(BaseModel):
    """Strict immutable shared values; services retain domain policy ownership."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_default=True,
        hide_input_in_errors=True,
    )


class SorProfile(str, Enum):
    """Stable domain namespaces exposed by the SOR product."""

    CRM = "crm"
    TICKETING = "ticketing"
    SUPPORT = "support"
    KNOWLEDGE = "knowledge"


class SorVendorErrorCode(str, Enum):
    """Stable failure reasons shared by vendor adapters and durable work."""

    MAPPING_INVALID = "mapping_invalid"
    SOURCE_CONFIGURATION_INVALID = "source_configuration_invalid"
    SOURCE_MAPPING_EMPTY = "source_mapping_empty"
    SOURCE_MAPPING_INVALID = "source_mapping_invalid"
    SOURCE_SELECTION_EMPTY = "source_selection_empty"
    VENDOR_ACCESS_TOKEN_EXPIRED = "vendor_access_token_expired"
    VENDOR_AUTHORIZATION_EXPIRED = "vendor_authorization_expired"
    VENDOR_AUTHORIZATION_FAILED = "vendor_authorization_failed"
    VENDOR_AUTHORIZATION_REFRESH_DEFERRED = "vendor_authorization_refresh_deferred"
    VENDOR_AUTHORIZATION_REFRESHED = "vendor_authorization_refreshed"
    VENDOR_BATCH_PARTIAL = "vendor_batch_partial"
    VENDOR_COMMAND_INVALID = "vendor_command_invalid"
    VENDOR_CONFIGURATION_INVALID = "vendor_configuration_invalid"
    VENDOR_CONFLICT = "vendor_conflict"
    VENDOR_CREDENTIALS_INVALID = "vendor_credentials_invalid"
    VENDOR_CURSOR_INVALID = "vendor_cursor_invalid"
    VENDOR_CUSTOM_OBJECT_LIMIT_EXCEEDED = "vendor_custom_object_limit_exceeded"
    VENDOR_EXPANSION_BUDGET_EXCEEDED = "vendor_expansion_budget_exceeded"
    VENDOR_EXPANSION_LIMIT_EXCEEDED = "vendor_expansion_limit_exceeded"
    VENDOR_FIELD_NOT_WRITABLE = "vendor_field_not_writable"
    VENDOR_FORBIDDEN = "vendor_forbidden"
    VENDOR_HISTORY_TRUNCATED = "vendor_history_truncated"
    VENDOR_IDENTIFIER_INVALID = "vendor_identifier_invalid"
    VENDOR_MUTATION_OUTCOME_UNKNOWN = "vendor_mutation_outcome_unknown"
    VENDOR_MEDIA_UNSUPPORTED = "vendor_media_unsupported"
    VENDOR_DNS_UNAVAILABLE = "vendor_dns_unavailable"
    VENDOR_EGRESS_REJECTED = "vendor_egress_rejected"
    VENDOR_ORIGIN_INVALID = "vendor_origin_invalid"
    VENDOR_PATH_INVALID = "vendor_path_invalid"
    VENDOR_PAGE_INVALID = "vendor_page_invalid"
    VENDOR_RATE_LIMITED = "vendor_rate_limited"
    VENDOR_QUERY_INVALID = "vendor_query_invalid"
    VENDOR_REDIRECT_INVALID = "vendor_redirect_invalid"
    VENDOR_REDIRECT_LIMIT = "vendor_redirect_limit"
    VENDOR_REAUTHORIZATION_REQUIRED = "vendor_reauthorization_required"
    VENDOR_REGION_MISMATCH = "vendor_region_mismatch"
    VENDOR_RELATIONSHIP_LIMIT_EXCEEDED = "vendor_relationship_limit_exceeded"
    VENDOR_REQUEST_FAILED = "vendor_request_failed"
    VENDOR_REQUEST_INVALID = "vendor_request_invalid"
    VENDOR_REQUEST_REJECTED = "vendor_request_rejected"
    VENDOR_RESOURCE_UNAVAILABLE = "vendor_resource_unavailable"
    VENDOR_RESPONSE_INVALID = "vendor_response_invalid"
    VENDOR_REVISION_CONFLICT = "vendor_revision_conflict"
    VENDOR_SCAN_LIMIT_EXCEEDED = "vendor_scan_limit_exceeded"
    VENDOR_SCOPE_MISSING = "vendor_scope_missing"
    VENDOR_SCHEMA_EMPTY = "vendor_schema_empty"
    VENDOR_SCHEMA_INVALID = "vendor_schema_invalid"
    VENDOR_SERVER_FAILED = "vendor_server_failed"
    VENDOR_SITE_INVALID = "vendor_site_invalid"
    VENDOR_SITE_UNAVAILABLE = "vendor_site_unavailable"
    VENDOR_STREAM_UNAVAILABLE = "vendor_stream_unavailable"
    VENDOR_STREAM_UNSUPPORTED = "vendor_stream_unsupported"
    VENDOR_SOURCE_CONFLICT = "vendor_source_conflict"
    VENDOR_TIMEOUT = "vendor_timeout"
    VENDOR_TOOL_UNSUPPORTED = "vendor_tool_unsupported"
    VENDOR_TRANSPORT_FAILED = "vendor_transport_failed"
    VENDOR_TRANSPORT_INVALID = "vendor_transport_invalid"
    VENDOR_WEBHOOK_AMBIGUOUS = "vendor_webhook_ambiguous"
    VENDOR_WEBHOOK_IDENTITY_INVALID = "vendor_webhook_identity_invalid"
    VENDOR_WEBHOOK_INVALID = "vendor_webhook_invalid"
    VENDOR_WEBHOOK_REJECTED = "vendor_webhook_rejected"
    VENDOR_WEBHOOK_STALE = "vendor_webhook_stale"
    VENDOR_WEBHOOK_UNSIGNED = "vendor_webhook_unsigned"


class SorRecoveryPolicy(str, Enum):
    """One explicit durable response to a vendor operation failure."""

    TERMINAL = "TERMINAL"
    RETRY = "RETRY"
    REFRESH_AND_RETRY = "REFRESH_AND_RETRY"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"

    @property
    def retryable(self) -> bool:
        return self in {SorRecoveryPolicy.RETRY, SorRecoveryPolicy.REFRESH_AND_RETRY}

    @property
    def requires_reauthorization(self) -> bool:
        return self is SorRecoveryPolicy.REAUTH_REQUIRED

    @property
    def refreshable_authorization(self) -> bool:
        return self is SorRecoveryPolicy.REFRESH_AND_RETRY


class SorFieldDataType(str, Enum):
    """Bounded semantic types exposed by SOR discovery and mappings."""

    TEXT = "text"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    TIMESTAMP = "timestamp"
    ENUM = "enum"
    REFERENCE = "reference"
    STRING_ARRAY = "string_array"
    STRING_LIST = "string_list"
    LINK = "link"
    URL = "url"
    JSON = "json"
    BOUNDED_JSON = "bounded_json"
    UNKNOWN = "unknown"


class SorCanonicalRelationKind(str, Enum):
    """Stable relationship meanings shared across SOR profiles."""

    ACTIVITY_FOR_COMPANY = "ACTIVITY_FOR_COMPANY"
    ACTIVITY_FOR_DEAL = "ACTIVITY_FOR_DEAL"
    ACTIVITY_WITH_CONTACT = "ACTIVITY_WITH_CONTACT"
    ASSIGNED_TO = "ASSIGNED_TO"
    ATTACHED_TO = "ATTACHED_TO"
    ATTACHED_TO_MESSAGE = "ATTACHED_TO_MESSAGE"
    AUTHORED_BY = "AUTHORED_BY"
    BELONGS_TO_PROJECT = "BELONGS_TO_PROJECT"
    BELONGS_TO_TEAM = "BELONGS_TO_TEAM"
    BLOCKED_BY = "BLOCKED_BY"
    BLOCKS = "BLOCKS"
    CHILD = "CHILD"
    COMMENT_ON = "COMMENT_ON"
    DUPLICATE = "DUPLICATE"
    FOR_COMPANY = "FOR_COMPANY"
    HAS_CONTACT = "HAS_CONTACT"
    HAS_LABEL = "HAS_LABEL"
    HAS_TAG = "HAS_TAG"
    IN_CYCLE = "IN_CYCLE"
    IN_INBOX = "IN_INBOX"
    IN_QUEUE = "IN_QUEUE"
    IN_SPACE = "IN_SPACE"
    MEASURES = "MEASURES"
    MESSAGE_IN = "MESSAGE_IN"
    PARENT = "PARENT"
    PART_OF_DOCUMENT = "PART_OF_DOCUMENT"
    PROPERTY_OF = "PROPERTY_OF"
    RELATED = "RELATED"
    REPORTED_BY = "REPORTED_BY"
    REQUESTED_BY = "REQUESTED_BY"
    SCOPED_TO_PROJECT = "SCOPED_TO_PROJECT"
    VERSION_OF = "VERSION_OF"


class SorRelationshipRole(str, Enum):
    """Platform role used to resolve one relation endpoint."""

    ASSIGNEE = "assignee"
    AUTHOR = "author"
    COMPANY = "company"
    CONTACT = "contact"
    CYCLE = "cycle"
    DEAL = "deal"
    DOCUMENT = "document"
    EXPLICIT_ISSUE_RELATION = "explicit_issue_relation"
    FROM_ISSUE = "from_issue"
    INBOX = "inbox"
    ISSUE = "issue"
    LABEL = "label"
    MESSAGE = "message"
    PARENT = "parent"
    PROJECT = "project"
    QUEUE = "queue"
    REPORTER = "reporter"
    REQUESTER = "requester"
    SPACE = "space"
    TAG = "tag"
    TEAM = "team"
    TICKET = "ticket"
    TO_ISSUE = "to_issue"


class SorOAuthTokenRequestFormat(str, Enum):
    """Wire encoding used for an OAuth token request."""

    FORM = "form"
    JSON = "json"


class SorOAuthClientAuthMethod(str, Enum):
    """Placement of OAuth client credentials in token requests."""

    BODY = "body"
    BASIC = "basic"


class SorRelationshipDirection(str, Enum):
    """Direction of an edge relative to the record being viewed."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"


class SorRelationshipTargets(_SorValue):
    """Typed relationship-role routing with explicit JSON conversion."""

    by_role: Mapping[SorRelationshipRole, str] = Field(default_factory=dict)

    @field_validator("by_role")
    @classmethod
    def _seal_targets(
        cls, values: Mapping[SorRelationshipRole, str]
    ) -> Mapping[SorRelationshipRole, str]:
        if not all(values.values()):
            raise ValueError("SOR relationship targets must be non-empty strings.")
        return MappingProxyType(dict(values))

    @field_serializer("by_role")
    def _targets_snapshot(
        self, values: Mapping[SorRelationshipRole, str]
    ) -> dict[str, str]:
        return {role.value: target for role, target in values.items()}

    @classmethod
    def from_wire(cls, values: Mapping[str, str]) -> "SorRelationshipTargets":
        return cls(
            by_role={
                SorRelationshipRole(role): target for role, target in values.items()
            }
        )

    def target(self, role: SorRelationshipRole) -> str | None:
        return self.by_role.get(role)

    def target_streams(self) -> frozenset[str]:
        return frozenset(self.by_role.values())

    def to_wire(self) -> dict[str, str]:
        return {role.value: target for role, target in self.by_role.items()}


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
    REAUTHORIZATION_SUCCEEDED = "reauthorization_succeeded"
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
    (
        SorSourceState.REAUTH_REQUIRED,
        SorSourceTransition.REAUTHORIZATION_SUCCEEDED,
    ): SorSourceState.ACTIVE,
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


class SorChangeMode(str, Enum):
    """How a source adapter receives change notifications between reconciliations."""

    MANAGED_WEBHOOK = "MANAGED_WEBHOOK"
    OPERATOR_WEBHOOK = "OPERATOR_WEBHOOK"
    APP_WEBHOOK = "APP_WEBHOOK"
    CHANGE_STREAM = "CHANGE_STREAM"
    POLL_ONLY = "POLL_ONLY"

    @property
    def accepts_webhooks(self) -> bool:
        """Return whether the mode accepts signed HTTP webhook deliveries."""
        return self in {
            SorChangeMode.MANAGED_WEBHOOK,
            SorChangeMode.OPERATOR_WEBHOOK,
            SorChangeMode.APP_WEBHOOK,
        }


class SorAppWebhookState(str, Enum):
    """Operator-visible lifecycle for one connector-owned app webhook."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    PUBLIC_ENDPOINT_REQUIRED = "PUBLIC_ENDPOINT_REQUIRED"
    SIGNING_SECRET_REQUIRED = "SIGNING_SECRET_REQUIRED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    REINSTALLATION_REQUIRED = "REINSTALLATION_REQUIRED"
    ACTIVE = "ACTIVE"


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


class SorRelationIntentState(str, Enum):
    """Resolution lifecycle for one vendor-normalized canonical relationship."""

    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    TOMBSTONED = "TOMBSTONED"


class SorWebhookReceiptState(str, Enum):
    """Processing lifecycle of one verified webhook delivery."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class SorWebhookSubscriptionState(str, Enum):
    """Lifecycle of one vendor-managed webhook subscription."""

    REGISTERING = "REGISTERING"
    ACTIVE = "ACTIVE"
    RENEWING = "RENEWING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REGISTRATION_FAILED = "REGISTRATION_FAILED"
    RENEWAL_FAILED = "RENEWAL_FAILED"
    REMOVING = "REMOVING"
    REMOVAL_FAILED = "REMOVAL_FAILED"


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


class SorMutationOperation(str, Enum):
    """Whether a vendor mutation creates or updates a source record."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"


class SorImplementationStatus(str, Enum):
    """Catalog status derived from whether an executable factory exists."""

    PLANNED = "PLANNED"
    AVAILABLE = "AVAILABLE"


class SorConfigurationFieldKind(str, Enum):
    """Input shape for one non-secret, adapter-owned source setting."""

    STRING_LIST = "STRING_LIST"


class SorCanonicalFieldSpec(_SorValue):
    """One stable Eylo-owned field available as a mapping target."""

    key: str
    label: str
    description: str
    data_type: SorFieldDataType
    writable: bool = True
    required: bool = False


class SorEntitySpec(_SorValue):
    """One canonical entity exposed by a profile."""

    key: str
    label: str
    description: str
    fields: tuple[SorCanonicalFieldSpec, ...] = ()


class SorToolSpec(_SorValue):
    """One stable profile-native Agent tool name."""

    name: str
    effect: SorToolEffect
    description: str
    primary_entity: str
    target_entities: frozenset[str]
    entities: frozenset[str]


class SorProfileSpec(_SorValue):
    """Human and Agent-facing contract for one SOR profile."""

    profile: SorProfile
    label: str
    description: str
    entities: tuple[SorEntitySpec, ...]
    tools: tuple[SorToolSpec, ...]


class SorVendorCandidate(_SorValue):
    """A roadmap catalog entry that does not claim an executable adapter."""

    profile: SorProfile
    vendor_key: str
    display_name: str
    description: str
    planned_auth_kinds: tuple[ConnectionAuthKind, ...]
    requires_instance_origin: bool = False
    setup_notes: tuple[str, ...] = ()


class SorVendorStreamSpec(BaseModel):
    """One explicit vendor object operators may select for synchronization."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    key: str
    label: str
    description: str
    canonical_entity: str
    change_strategies: frozenset[SorChangeStrategy]
    scope_category: str | None = None
    depends_on: frozenset[str] = frozenset()
    relationship_targets: SorRelationshipTargets = Field(
        default_factory=SorRelationshipTargets
    )

    @field_serializer("relationship_targets")
    def _relationship_snapshot(
        self, value: SorRelationshipTargets
    ) -> dict[str, dict[str, str]]:
        return {"by_role": value.to_wire()}


class SorRelationIntentDraft(_SorValue):
    """Exact same-source endpoint identities emitted by profile projection."""

    from_vendor_object_key: str
    from_vendor_external_id: str
    to_vendor_object_key: str
    to_vendor_external_id: str
    canonical_relation_kind: SorCanonicalRelationKind
    relationship_role: SorRelationshipRole
    vendor_relation_kind: str | None
    external_relation_id: str
    source_revision: str | None = None


class SorOAuthOriginOption(BaseModel):
    """One exact API region and the consent host paired with it."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    api_origin: str
    authorization_origin: str
    label: str


class SorOAuthSpec(BaseModel):
    """Pinned OAuth protocol facts owned by one executable vendor adapter."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

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
    token_request_format: SorOAuthTokenRequestFormat = SorOAuthTokenRequestFormat.FORM
    token_client_auth_method: SorOAuthClientAuthMethod = SorOAuthClientAuthMethod.BODY
    token_grant_type: str | None = "authorization_code"
    send_token_redirect_uri: bool = True
    pkce: bool = False
    instance_origin_field: str | None = None
    instance_host_suffixes: tuple[str, ...] = ()
    instance_origin_options: tuple[SorOAuthOriginOption, ...] = ()
    operator_instance_origin: bool = False


class SorAdapterConfigurationFieldSpec(_SorValue):
    """One schema-driven non-secret source setting rendered by the console."""

    key: str
    label: str
    description: str
    kind: SorConfigurationFieldKind
    required: bool = False
    placeholder: str | None = None
    minimum_items: int = 0
    maximum_items: int = 100


class SorAdapterCapabilityManifest(BaseModel):
    """Executable facts declared only beside a real adapter factory."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", validate_default=True
    )

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
    required_scopes: Mapping[str, tuple[str, ...]] = Field(default_factory=dict)
    custom_object_required_scopes: tuple[str, ...] = ()
    custom_object_change_strategies: frozenset[SorChangeStrategy] = frozenset()
    tool_required_scopes: Mapping[str, tuple[str, ...]] = Field(default_factory=dict)
    tool_streams: Mapping[str, frozenset[str]] = Field(default_factory=dict)
    mutation_result_streams: Mapping[str, str] = Field(default_factory=dict)
    oauth: SorOAuthSpec | None = None
    fixed_origin: str | None = None
    requires_instance_origin: bool = False
    change_mode: SorChangeMode = SorChangeMode.POLL_ONLY
    supports_deletions: bool = False
    supports_custom_fields: bool = False
    supports_custom_objects: bool = False
    supports_conditional_writes: bool = False
    supports_history: bool = False
    supports_comments: bool = False
    supports_attachments: bool = False
    supports_structured_documents: bool = False

    @field_validator("required_scopes", "tool_required_scopes")
    @classmethod
    def _freeze_scopes(
        cls, value: Mapping[str, tuple[str, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType(dict(value))

    @field_validator("tool_streams")
    @classmethod
    def _freeze_tool_streams(
        cls, value: Mapping[str, frozenset[str]]
    ) -> Mapping[str, frozenset[str]]:
        return MappingProxyType(dict(value))

    @field_validator("mutation_result_streams")
    @classmethod
    def _freeze_result_streams(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(value))

    @field_serializer(
        "required_scopes",
        "tool_required_scopes",
        "tool_streams",
        "mutation_result_streams",
    )
    def _mapping_snapshot(
        self,
        value: Mapping[str, tuple[str, ...]]
        | Mapping[str, frozenset[str]]
        | Mapping[str, str],
    ) -> dict[str, tuple[str, ...] | frozenset[str] | str]:
        return dict(value)


class SorAdapterFieldSelection(BaseModel):
    """One field selected by the active mapping and exposed to an adapter."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    vendor_object_key: str
    vendor_field_key: str
    agent_key: str
    writable: bool


class SorAdapterContext(BaseModel):
    """Resolved, tenant-owned inputs used to construct one adapter instance."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        hide_input_in_errors=True,
        validate_default=True,
    )

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
    credentials: Mapping[str, SorJsonValue] = Field(repr=False, exclude=True)
    webhook_signing_secret: str | None = Field(default=None, repr=False, exclude=True)
    webhook_auth_secret: str | None = Field(default=None, repr=False, exclude=True)
    webhook_subscription_id: str | None = None
    configuration: Mapping[str, SorJsonValue] = Field(default_factory=dict)

    @field_validator("credentials", "configuration")
    @classmethod
    def _seal_mapping(
        cls, value: Mapping[str, SorJsonValue]
    ) -> Mapping[str, SorJsonValue]:
        return MappingProxyType(dict(value))

    @field_serializer("configuration")
    def _configuration_snapshot(
        self, value: Mapping[str, SorJsonValue]
    ) -> dict[str, JsonValue]:
        return dict(value)


class SorConnectionVerification(BaseModel):
    """Bounded result of checking one configured external account."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    account_external_id: str | None = None
    account_display_name: str | None = None
    granted_scopes: tuple[str, ...] = ()
    vendor_api_version: str | None = None


class SorDiscoveredField(BaseModel):
    """One stable field identity discovered from a vendor object."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    key: str
    label: str
    data_type: SorFieldDataType
    nullable: bool
    writable: bool
    choices: tuple[str, ...] = ()
    description: str | None = None
    group: str | None = None
    vendor_type: str | None = None


class SorDiscoveredObject(BaseModel):
    """One source object and its stable fields."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    key: str
    label: str
    fields: tuple[SorDiscoveredField, ...]
    custom: bool = False


class SorDiscoveredSchema(BaseModel):
    """Complete immutable discovery result from one adapter invocation."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    objects: tuple[SorDiscoveredObject, ...]
    vendor_api_version: str | None = None


class SorSourcePayload(BaseModel):
    """Immutable dynamic source fields at the vendor-to-mapping boundary.

    Vendor and custom fields are runtime data, so they cannot be represented by
    one closed schema. Domain code must not inspect this object; only the mapping
    engine resolves its configured field names before producing a typed canonical
    payload.
    """

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    values: Mapping[str, object] = Field(repr=False, exclude=True)

    @field_validator("values")
    @classmethod
    def seal_fields(cls, values: Mapping[str, object]) -> Mapping[str, object]:
        if not all(values):
            raise ValueError("SOR source payload keys must be non-empty strings.")
        return MappingProxyType(dict(values))

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "SorSourcePayload":
        """Copy a vendor-owned field mapping into the immutable boundary object."""
        return cls(values=values)

    def has_field(self, key: str) -> bool:
        return key in self.values

    def field_names(self) -> tuple[str, ...]:
        """Return the sealed source-field vocabulary without exposing its mapping."""
        return tuple(self.values)

    def value(self, key: str) -> object:
        return self.values[key]

    def to_wire(self) -> dict[str, object]:
        """Return a detached mapping for durable and persistence serialization."""
        return dict(self.values)


class SorCanonicalRecord(BaseModel):
    """Validated adapter output before profile storage and relationship linking.

    Native constructors require exact platform types. Fields are top-level frozen
    and nested JSON is independently validated/copied, not recursively immutable.
    Raw source bodies are excluded from generic snapshots; profile services write
    explicit fields, not these snapshots. Domain services still own field budgets,
    source identity, relationships and transaction policy.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_default=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class SorCanonicalPayload(BaseModel):
    """Base for closed, profile-owned payloads after field mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SorCommandPayload(BaseModel):
    """Closed Agent command data after validation at the tool boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def to_wire(self) -> dict[str, object]:
        """Convert a typed command only at an encrypted durable boundary."""
        return self.model_dump(mode="json")


_MAPPED_COMMAND_FIELDS = TypeAdapter(
    dict[str, JsonValue],
    config=ConfigDict(strict=True),
)


class SorMappedFieldsCommandPayload(SorCommandPayload):
    """Dynamic mapped fields for create/update commands.

    The active source mapping owns these keys, so their vocabulary cannot be a
    static Python model. The wrapper still validates JSON values, freezes the
    command as an object, and keeps mapping access at the vendor translation
    edge instead of throughout orchestration code.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def validate_json_fields(cls, value: object) -> dict[str, JsonValue]:
        if not isinstance(value, Mapping):
            raise ValueError("Mapped command fields must be an object.")
        validated = _MAPPED_COMMAND_FIELDS.validate_python(dict(value))
        normalized = to_json_value(validated)
        if not isinstance(normalized, dict):
            raise ValueError("Mapped command fields must be a JSON object.")
        return normalized

    @model_validator(mode="after")
    def require_fields(self) -> "SorMappedFieldsCommandPayload":
        if not self.__pydantic_extra__:
            raise ValueError("A mapped-field command requires at least one field.")
        return self

    @property
    def fields(self) -> Mapping[str, object]:
        """Expose immutable mapped values only to a vendor field translator."""
        return MappingProxyType(dict(self.__pydantic_extra__ or {}))


class SorExternalRecord(BaseModel):
    """One source record before profile normalization and projection."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    vendor_object_key: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    payload: SorSourcePayload = Field(repr=False, exclude=True)
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    source_revision: str | None = None
    source_url: str | None = None

    def __init__(
        self,
        vendor_object_key: str,
        external_id: str,
        payload: SorSourcePayload | Mapping[str, object],
        source_created_at: datetime | None = None,
        source_updated_at: datetime | None = None,
        source_revision: str | None = None,
        source_url: str | None = None,
    ) -> None:
        """Seal a vendor mapping while exposing only the typed payload object."""
        if not isinstance(payload, (SorSourcePayload, Mapping)):
            raise TypeError("SOR external record payload must be a field mapping.")
        sealed_payload = (
            payload
            if isinstance(payload, SorSourcePayload)
            else SorSourcePayload.from_mapping(payload)
        )
        super().__init__(
            vendor_object_key=vendor_object_key,
            external_id=external_id,
            payload=sealed_payload,
            source_created_at=source_created_at,
            source_updated_at=source_updated_at,
            source_revision=source_revision,
            source_url=source_url,
        )


class SorRecordPage(BaseModel):
    """One bounded page plus the opaque checkpoint it covers."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    records: tuple[SorExternalRecord, ...]
    next_cursor: str | None
    has_more: bool


class SorDeletedRecord(_SorValue):
    """One source identity the vendor reports deleted or archived."""

    vendor_object_key: str
    external_id: str
    deleted_at: datetime | None = None
    reason: str | None = None


class SorWebhookSubscription(BaseModel):
    """Vendor subscription identity and renewal deadline."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    external_id: str
    expires_at: datetime | None = None
    signing_secret: str | None = Field(default=None, repr=False, exclude=True)


class SorWebhookSignal(BaseModel):
    """Verified hint that identifies records to refetch."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    delivery_id: str | None
    event_type: str
    vendor_object_key: str | None
    external_id: str | None
    occurred_at: datetime | None


class SorCommandRequest(BaseModel):
    """One typed, idempotent authoritative-source mutation."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    tool_name: str
    idempotency_key: str
    payload: SkipJsonSchema[InstanceOf[SorCommandPayload]] = Field(
        repr=False, exclude=True
    )
    target_external_id: str | None = None
    expected_source_revision: str | None = None


class SorCommandResult(BaseModel):
    """Validated mutation result; durable codecs explicitly persist response data."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    vendor_object_key: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    external_request_id: str | None = None
    source_revision: str | None = None
    source_url: str | None = None
    response: dict[str, SorJsonValue] = Field(
        default_factory=dict, repr=False, exclude=True
    )

    def __init__(
        self,
        *,
        vendor_object_key: str,
        external_id: str,
        external_request_id: str | None = None,
        source_revision: str | None = None,
        source_url: str | None = None,
        response: Mapping[str, object] | None = None,
    ) -> None:
        """Accept vendor mappings at construction, expose only validated JSON."""
        super().__init__(
            vendor_object_key=vendor_object_key,
            external_id=external_id,
            external_request_id=external_request_id,
            source_revision=source_revision,
            source_url=source_url,
            response={} if response is None else dict(response),
        )


class SorFieldMappingDraft(_SorValue):
    """Operator-selected target for one exact discovered source field."""

    vendor_object_key: str
    vendor_field_key: str
    canonical_target_path: str | None = None
    custom_type: SorCustomFieldType | None = None
    transform_kind: SorTransformKind = SorTransformKind.DIRECT
    transform_config: dict[str, SorJsonValue] = Field(default_factory=dict)
    direction: SorFieldMappingDirection = SorFieldMappingDirection.READ_ONLY
    agent_visible: bool = False
    ui_default_column: bool = False
    sensitivity: SorSensitivity = SorSensitivity.STANDARD


class SorStreamDraft(_SorValue):
    """Operator-selected execution policy for one source object."""

    vendor_object_key: str
    canonical_entity_kind: str
    strategy: SorChangeStrategy
    lookback_seconds: int = 0
    schedule: str | None = None


class SorSchemaDifference(BaseModel):
    """Human-auditable difference between two immutable discoveries."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    renamed: tuple[str, ...] = ()
    type_changed: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return any((self.added, self.removed, self.renamed, self.type_changed))


class SorProjectionOutcome(_SorValue):
    """Canonical values and record identity produced by shared projection."""

    record_id: UUID
    disposition: SorProjectionDisposition
    canonical_payload: SorCanonicalPayload = Field(repr=False, exclude=True)
    custom_field_keys: tuple[str, ...]


@runtime_checkable
class SorLifecycleAdapter(Protocol):
    """Vendor I/O port; async methods must run outside DB transactions."""

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
        code: SorVendorErrorCode,
        message: str,
        *,
        recovery: SorRecoveryPolicy,
    ) -> None:
        super().__init__(message)
        if not isinstance(code, SorVendorErrorCode):
            raise TypeError("SOR vendor error code must be a SorVendorErrorCode.")
        if not isinstance(recovery, SorRecoveryPolicy):
            raise TypeError("SOR recovery policy must be a SorRecoveryPolicy.")
        self.code = code
        self.recovery = recovery

    @property
    def retryable(self) -> bool:
        """Compatibility projection used by durable retry callers."""
        return self.recovery.retryable

    @property
    def requires_reauthorization(self) -> bool:
        """Compatibility projection used by source lifecycle callers."""
        return self.recovery.requires_reauthorization

    @property
    def refreshable_authorization(self) -> bool:
        """Compatibility projection used by the credential refresh boundary."""
        return self.recovery.refreshable_authorization


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
    "SorAppWebhookState",
    "SorCanonicalFieldSpec",
    "SorCanonicalPayload",
    "SorCanonicalRelationKind",
    "SorCapabilityUnavailable",
    "SorChangeMode",
    "SorChangeStrategy",
    "SorCommandRevisionConflict",
    "SorCommandPayload",
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
    "SorFieldDataType",
    "SorExternalRecordNotFound",
    "SorExternalRecord",
    "SorCustomFieldType",
    "SorFieldMappingDraft",
    "SorFieldMappingDirection",
    "SorFieldMappingState",
    "SorImplementationStatus",
    "SorLifecycleAdapter",
    "SorMappingState",
    "SorMappedFieldsCommandPayload",
    "SorMutationOperation",
    "SorOAuthOriginOption",
    "SorOAuthClientAuthMethod",
    "SorOAuthSpec",
    "SorOAuthTokenRequestFormat",
    "SorProfile",
    "SorProfileSpec",
    "SorProjectionDisposition",
    "SorProjectionOutcome",
    "SorRecordPage",
    "SorRecoveryPolicy",
    "SorRelationIntentDraft",
    "SorRelationIntentState",
    "SorRelationshipDirection",
    "SorRelationshipRole",
    "SorRelationshipTargets",
    "SorSchemaDifference",
    "SorSensitivity",
    "SorSourceAccess",
    "SorSourcePayload",
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
    "SorVendorErrorCode",
    "SorVendorOperationError",
    "SorVendorStreamSpec",
    "SorWebhookReceiptState",
    "SorWebhookPayloadError",
    "SorWebhookSignal",
    "SorWebhookSubscription",
    "SorWebhookSubscriptionState",
    "SorWebhookVerificationError",
    "SorWorkState",
    "require_unique_names",
    "transition_source_state",
]
