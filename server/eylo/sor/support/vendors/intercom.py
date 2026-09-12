"""Intercom adapter for Eylo's conversation-first customer-support profile."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import StrEnum
from html.parser import HTMLParser
from http import HTTPMethod, HTTPStatus
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.runtime.http import SorHttpTransport, SorJsonHttpClient, SorJsonResponse
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterContext,
    SorCapabilityUnavailable,
    SorChangeMode,
    SorChangeStrategy,
    SorCommandRequest,
    SorCommandResult,
    SorConnectionVerification,
    SorDeletedRecord,
    SorDiscoveredField,
    SorDiscoveredObject,
    SorDiscoveredSchema,
    SorExternalRecord,
    SorExternalRecordNotFound,
    SorFieldDataType,
    SorOAuthOriginOption,
    SorOAuthSpec,
    SorProfile,
    SorRecordPage,
    SorRecoveryPolicy,
    SorRelationshipRole,
    SorRelationshipTargets,
    SorVendorErrorCode,
    SorVendorOperationError,
    SorVendorStreamSpec,
    SorWebhookPayloadError,
    SorWebhookSignal,
    SorWebhookSubscription,
    SorWebhookVerificationError,
)
from eylo.sor.shared.json_values import SorJsonValue, require_json_value
from eylo.sor.support.contracts import (
    SupportAgent,
    SupportAgentPayload,
    SupportAssignCommandPayload,
    SupportAttachment,
    SupportAttachmentPayload,
    SupportCloseCommandPayload,
    SupportCustomer,
    SupportCustomerPayload,
    SupportEntityKind,
    SupportInbox,
    SupportInboxPayload,
    SupportMappedFieldsCommandPayload,
    SupportMessage,
    SupportMessageCommandPayload,
    SupportMessageDirection,
    SupportMessagePayload,
    SupportMessageVisibility,
    SupportQueue,
    SupportQueuePayload,
    SupportSlaMetric,
    SupportSlaMetricPayload,
    SupportSlaState,
    SupportTag,
    SupportTagCommandPayload,
    SupportTagPayload,
    SupportTicket,
    SupportTicketPayload,
    SupportTicketState,
    SupportToolName,
)
from eylo.sor.support.vendors import intercom_wire as native

INTERCOM_API_VERSION = "2.16"
INTERCOM_CURSOR_VERSION = 1
INTERCOM_OVERLAP_SECONDS = 60
INTERCOM_MAX_PARTS = 500
INTERCOM_MAX_EMPTY_EXPANSIONS = 50
INTERCOM_CURSOR_LIMIT = 4_096
INTERCOM_CONTINUATION_LIMIT = 2_048
INTERCOM_CUSTOM_ATTRIBUTE_PREFIX = "custom_attribute:"

READ_USERS = "read_users"
READ_CONVERSATIONS = "read_conversations"
WRITE_CONVERSATIONS = "write_conversations"
READ_ADMINS = "read_admins"
READ_TAGS = "read_tags"
WRITE_TAGS = "write_tags"

_ORIGIN_REGIONS = {
    "https://api.intercom.io": ("United States", "US"),
    "https://api.eu.intercom.io": ("Europe", "EU"),
    "https://api.au.intercom.io": ("Australia", "AU"),
}
_AUTHORIZATION_ORIGINS = {
    "https://api.intercom.io": "https://app.intercom.com",
    "https://api.eu.intercom.io": "https://app.eu.intercom.com",
    "https://api.au.intercom.io": "https://app.au.intercom.com",
}


class IntercomStream(StrEnum):
    """Closed vendor stream vocabulary owned by this adapter."""

    CONVERSATIONS = "conversations"
    CONTACTS = "contacts"
    ADMINS = "admins"
    TEAMS = "teams"
    CONVERSATION_PARTS = "conversation_parts"
    TAGS = "tags"
    ATTACHMENTS = "attachments"


_STREAM_ENTITY = {
    IntercomStream.CONVERSATIONS: SupportEntityKind.TICKET,
    IntercomStream.CONTACTS: SupportEntityKind.CUSTOMER,
    IntercomStream.ADMINS: SupportEntityKind.AGENT,
    IntercomStream.TEAMS: SupportEntityKind.QUEUE,
    IntercomStream.CONVERSATION_PARTS: SupportEntityKind.MESSAGE,
    IntercomStream.TAGS: SupportEntityKind.TAG,
    IntercomStream.ATTACHMENTS: SupportEntityKind.ATTACHMENT,
}
_RELATIONSHIP_TARGETS = {
    IntercomStream.CONVERSATIONS: {
        SorRelationshipRole.REQUESTER: IntercomStream.CONTACTS,
        SorRelationshipRole.ASSIGNEE: IntercomStream.ADMINS,
        SorRelationshipRole.QUEUE: IntercomStream.TEAMS,
        SorRelationshipRole.TAG: IntercomStream.TAGS,
    },
    IntercomStream.CONVERSATION_PARTS: {
        SorRelationshipRole.TICKET: IntercomStream.CONVERSATIONS
    },
    IntercomStream.ATTACHMENTS: {
        SorRelationshipRole.TICKET: IntercomStream.CONVERSATIONS,
        SorRelationshipRole.MESSAGE: IntercomStream.CONVERSATION_PARTS,
    },
}
_READ_TOOLS = frozenset(
    {
        SupportToolName.FIND_CUSTOMER,
        SupportToolName.FIND_TICKET,
        SupportToolName.GET_TICKET,
        SupportToolName.GET_CUSTOMER_HISTORY,
        SupportToolName.LIST_QUEUES,
        SupportToolName.DESCRIBE_TICKET_FIELDS,
    }
)
_WRITE_TOOLS = frozenset(
    {
        SupportToolName.OPEN_TICKET,
        SupportToolName.UPDATE_TICKET,
        SupportToolName.ASSIGN_TICKET,
        SupportToolName.REPLY,
        SupportToolName.ADD_NOTE,
        SupportToolName.CLOSE_TICKET,
        SupportToolName.ADD_TAG,
        SupportToolName.REMOVE_TAG,
    }
)
_TOOL_STREAMS = {
    SupportToolName.FIND_CUSTOMER: frozenset({IntercomStream.CONTACTS}),
    SupportToolName.FIND_TICKET: frozenset({IntercomStream.CONVERSATIONS}),
    SupportToolName.GET_TICKET: frozenset(
        {IntercomStream.CONVERSATIONS, IntercomStream.CONVERSATION_PARTS}
    ),
    SupportToolName.GET_CUSTOMER_HISTORY: frozenset(
        {IntercomStream.CONTACTS, IntercomStream.CONVERSATIONS}
    ),
    SupportToolName.LIST_QUEUES: frozenset({IntercomStream.TEAMS}),
    SupportToolName.DESCRIBE_TICKET_FIELDS: frozenset({IntercomStream.CONVERSATIONS}),
    SupportToolName.OPEN_TICKET: frozenset({IntercomStream.CONVERSATIONS}),
    SupportToolName.UPDATE_TICKET: frozenset({IntercomStream.CONVERSATIONS}),
    SupportToolName.ASSIGN_TICKET: frozenset(
        {IntercomStream.CONVERSATIONS, IntercomStream.ADMINS, IntercomStream.TEAMS}
    ),
    SupportToolName.REPLY: frozenset(
        {IntercomStream.CONVERSATIONS, IntercomStream.CONVERSATION_PARTS}
    ),
    SupportToolName.ADD_NOTE: frozenset(
        {IntercomStream.CONVERSATIONS, IntercomStream.CONVERSATION_PARTS}
    ),
    SupportToolName.CLOSE_TICKET: frozenset({IntercomStream.CONVERSATIONS}),
    SupportToolName.ADD_TAG: frozenset(
        {IntercomStream.CONVERSATIONS, IntercomStream.TAGS}
    ),
    SupportToolName.REMOVE_TAG: frozenset(
        {IntercomStream.CONVERSATIONS, IntercomStream.TAGS}
    ),
}
_MUTATION_RESULT_STREAMS = {
    **{name: IntercomStream.CONVERSATIONS for name in _WRITE_TOOLS},
    SupportToolName.REPLY: IntercomStream.CONVERSATION_PARTS,
    SupportToolName.ADD_NOTE: IntercomStream.CONVERSATION_PARTS,
}
_STREAM_SCOPES = {
    IntercomStream.CONVERSATIONS: (READ_CONVERSATIONS,),
    IntercomStream.CONTACTS: (READ_USERS,),
    IntercomStream.ADMINS: (READ_ADMINS,),
    IntercomStream.TEAMS: (READ_ADMINS,),
    IntercomStream.CONVERSATION_PARTS: (READ_CONVERSATIONS,),
    IntercomStream.TAGS: (READ_TAGS,),
    IntercomStream.ATTACHMENTS: (READ_CONVERSATIONS,),
}
_TOOL_SCOPES = {
    SupportToolName.FIND_CUSTOMER: (READ_USERS,),
    SupportToolName.FIND_TICKET: (READ_CONVERSATIONS,),
    SupportToolName.GET_TICKET: (READ_CONVERSATIONS,),
    SupportToolName.GET_CUSTOMER_HISTORY: (READ_USERS, READ_CONVERSATIONS),
    SupportToolName.LIST_QUEUES: (READ_ADMINS,),
    SupportToolName.DESCRIBE_TICKET_FIELDS: (READ_CONVERSATIONS,),
    SupportToolName.OPEN_TICKET: (WRITE_CONVERSATIONS,),
    SupportToolName.UPDATE_TICKET: (WRITE_CONVERSATIONS,),
    SupportToolName.ASSIGN_TICKET: (WRITE_CONVERSATIONS, READ_ADMINS),
    SupportToolName.REPLY: (WRITE_CONVERSATIONS, READ_ADMINS),
    SupportToolName.ADD_NOTE: (WRITE_CONVERSATIONS, READ_ADMINS),
    SupportToolName.CLOSE_TICKET: (WRITE_CONVERSATIONS, READ_ADMINS),
    SupportToolName.ADD_TAG: (WRITE_CONVERSATIONS, WRITE_TAGS, READ_ADMINS),
    SupportToolName.REMOVE_TAG: (WRITE_CONVERSATIONS, WRITE_TAGS, READ_ADMINS),
}


INTERCOM_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.SUPPORT,
    vendor_key="intercom",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                IntercomStream.CONVERSATIONS: "Conversations",
                IntercomStream.CONTACTS: "Contacts",
                IntercomStream.ADMINS: "Admins",
                IntercomStream.TEAMS: "Teams",
                IntercomStream.CONVERSATION_PARTS: "Conversation messages",
                IntercomStream.TAGS: "Tags",
                IntercomStream.ATTACHMENTS: "Conversation attachments",
            }[stream_key],
            description={
                IntercomStream.CONVERSATIONS: "Intercom conversations represented as support cases.",
                IntercomStream.CONTACTS: "People who open and participate in conversations.",
                IntercomStream.ADMINS: "Workspace teammates who may act on conversations.",
                IntercomStream.TEAMS: "Inbox teams used as canonical support queues.",
                IntercomStream.CONVERSATION_PARTS: "Customer-visible replies and private notes.",
                IntercomStream.TAGS: "Workspace tags available for conversation classification.",
                IntercomStream.ATTACHMENTS: "Metadata for files attached to conversation messages.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=(
                frozenset({SorChangeStrategy.UPDATED_AT})
                if stream_key
                in {
                    IntercomStream.CONVERSATIONS,
                    IntercomStream.CONTACTS,
                    IntercomStream.CONVERSATION_PARTS,
                    IntercomStream.ATTACHMENTS,
                }
                else frozenset({SorChangeStrategy.FULL_RECONCILE})
            ),
            depends_on=frozenset(
                set(_RELATIONSHIP_TARGETS.get(stream_key, {}).values()) - {stream_key}
            ),
            relationship_targets=SorRelationshipTargets(
                by_role=_RELATIONSHIP_TARGETS.get(stream_key, {}),
            ),
        )
        for stream_key, entity in _STREAM_ENTITY.items()
    ),
    readable_entities=frozenset(_STREAM_ENTITY.values()),
    writable_entities=frozenset({"ticket", "message"}),
    readable_tools=_READ_TOOLS,
    writable_tools=_WRITE_TOOLS,
    change_strategies=frozenset(
        {SorChangeStrategy.UPDATED_AT, SorChangeStrategy.FULL_RECONCILE}
    ),
    required_scopes={stream.value: scopes for stream, scopes in _STREAM_SCOPES.items()},
    tool_required_scopes={tool.value: scopes for tool, scopes in _TOOL_SCOPES.items()},
    tool_streams={
        tool.value: frozenset(stream.value for stream in streams)
        for tool, streams in _TOOL_STREAMS.items()
    },
    mutation_result_streams={
        tool.value: stream.value for tool, stream in _MUTATION_RESULT_STREAMS.items()
    },
    oauth=SorOAuthSpec(
        authorization_path="/oauth",
        token_url="https://api.intercom.io/auth/eagle/token",
        base_scopes=(READ_ADMINS,),
        authorization_response_type=None,
        send_authorization_scope=False,
        token_grant_type=None,
        send_token_redirect_uri=False,
        instance_origin_options=tuple(
            SorOAuthOriginOption(
                api_origin=origin,
                authorization_origin=_AUTHORIZATION_ORIGINS[origin],
                label=label,
            )
            for origin, (label, _region) in _ORIGIN_REGIONS.items()
        ),
        operator_instance_origin=True,
    ),
    requires_instance_origin=True,
    change_mode=SorChangeMode.APP_WEBHOOK,
    supports_custom_fields=True,
    supports_history=False,
    supports_comments=True,
    supports_attachments=True,
)


class IntercomAppWebhookDelivery(BaseModel):
    """One signed workspace event before source-selection filtering."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_external_id: str
    signal: SorWebhookSignal


_INTERCOM_SIGNATURE_HEADER = "x-hub-signature"
_INTERCOM_SIGNATURE_PREFIX = "sha1="


class IntercomWebhookTopicPrefix(StrEnum):
    """Native routing families; the complete topic remains open vendor data."""

    CONTACT = "contact."
    USER = "user."
    CONVERSATION = "conversation."


class IntercomWebhookItemType(StrEnum):
    """Item kind used when conversation notifications carry the conversation itself."""

    CONVERSATION = "conversation"


class IntercomWebhookModel(BaseModel):
    """Retain only consumed webhook metadata, never customer message content."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class IntercomWebhookItem(IntercomWebhookModel):
    """Optional native identity; absent identity requests the existing broad sync."""

    id: str | None = None
    type: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: object) -> str | None:
        return _optional_id(value)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: object) -> str | None:
        return _optional_string(value)


class IntercomWebhookConversationItem(IntercomWebhookItem):
    """Direct conversation identity precedes the optional nested conversation."""

    conversation_id: str | None = None
    conversation: IntercomWebhookItem | None = None

    @field_validator("conversation_id", mode="before")
    @classmethod
    def normalize_conversation_id(cls, value: object) -> str | None:
        return _optional_id(value)

    @model_validator(mode="before")
    @classmethod
    def select_identity_source(cls, value: object) -> object:
        # A direct ID makes the nested vendor object irrelevant. Preserve that
        # precedence rather than newly rejecting unrelated nested fields.
        if (
            isinstance(value, Mapping)
            and _optional_id(value.get("conversation_id")) is not None
        ):
            return {**value, "conversation": None}
        return value


class IntercomWebhookData[Item: IntercomWebhookItem](IntercomWebhookModel):
    """Optional item envelope for the already-selected notification family."""

    item: Item | None = None


class IntercomWebhookHeader(IntercomWebhookModel):
    """Account and topic authority independent of the vendor item's shape."""

    topic: str
    app_id: str
    id: str | None = None
    created_at: datetime | None = None

    @field_validator("topic", mode="before")
    @classmethod
    def validate_topic(cls, value: object) -> str:
        return _required_string(value, field="Intercom webhook topic")

    @field_validator("app_id", mode="before")
    @classmethod
    def validate_workspace(cls, value: object) -> str:
        return _required_id(value, field="Intercom webhook workspace ID")

    @field_validator("id", mode="before")
    @classmethod
    def normalize_delivery(cls, value: object) -> str | None:
        return _optional_id(value)

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_time(cls, value: object) -> datetime | None:
        return _optional_datetime(value)


class IntercomWebhookPayload[Item: IntercomWebhookItem](IntercomWebhookHeader):
    """A topic-selected typed item, with the existing absent-envelope behavior."""

    data: IntercomWebhookData[Item] | None = None

    @field_validator("data", mode="before")
    @classmethod
    def normalize_envelope(cls, value: object) -> object:
        return value if isinstance(value, (Mapping, IntercomWebhookData)) else None


def verify_intercom_app_webhook(
    *,
    headers: Mapping[str, str],
    body: bytes,
    client_secret: str,
) -> None:
    """Authenticate one Intercom app delivery against its raw request bytes."""
    signature = _header(headers, _INTERCOM_SIGNATURE_HEADER)
    if signature is None or not signature.startswith(_INTERCOM_SIGNATURE_PREFIX):
        raise SorWebhookVerificationError("Intercom webhook signature is missing.")
    expected = (
        _INTERCOM_SIGNATURE_PREFIX
        + hmac.new(
            client_secret.encode("utf-8"),
            body,
            hashlib.sha1,
        ).hexdigest()
    )
    if not hmac.compare_digest(signature, expected):
        raise SorWebhookVerificationError("Intercom webhook signature is invalid.")


def parse_intercom_app_webhook(*, body: bytes) -> IntercomAppWebhookDelivery:
    """Extract the workspace boundary and one refetch signal from a delivery."""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SorWebhookPayloadError(
            "Intercom webhook body is not valid JSON."
        ) from error
    try:
        header = IntercomWebhookHeader.model_validate(payload)
        if header.topic.casefold().startswith(IntercomWebhookTopicPrefix.CONVERSATION):
            event = IntercomWebhookPayload[
                IntercomWebhookConversationItem
            ].model_validate(payload)
        else:
            event = IntercomWebhookPayload[IntercomWebhookItem].model_validate(payload)
        item = event.data.item if event.data is not None else None
        object_key, external_id = _webhook_identity(event.topic, item)
        signal = SorWebhookSignal(
            delivery_id=event.id,
            event_type=event.topic,
            vendor_object_key=object_key,
            external_id=external_id,
            occurred_at=event.created_at,
        )
    except SorVendorOperationError as error:
        raise SorWebhookPayloadError(str(error)) from error
    except ValidationError as error:
        raise SorWebhookPayloadError("Intercom webhook metadata is invalid.") from error
    return IntercomAppWebhookDelivery(
        organization_external_id=event.app_id,
        signal=signal,
    )


def _field(
    key: str,
    label: str,
    data_type: SorFieldDataType,
    *,
    nullable: bool = True,
    writable: bool = False,
    choices: tuple[str, ...] = (),
    description: str | None = None,
) -> SorDiscoveredField:
    return SorDiscoveredField(
        key=key,
        label=label,
        data_type=data_type,
        nullable=nullable,
        writable=writable,
        choices=choices,
        description=description,
        group="Intercom",
    )


_SCHEMA_FIELDS = {
    IntercomStream.CONVERSATIONS: (
        _field("subject", "Title", SorFieldDataType.TEXT, writable=True),
        _field(
            "normalized_description",
            "Opening message",
            SorFieldDataType.TEXT,
            writable=True,
        ),
        _field(
            "requester_external_id",
            "Contact ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field("assignee_external_id", "Admin assignee ID", SorFieldDataType.REFERENCE),
        _field("group_external_id", "Team assignee ID", SorFieldDataType.REFERENCE),
        _field(
            "native_status",
            "State",
            SorFieldDataType.ENUM,
            choices=("open", "closed", "snoozed"),
        ),
        _field("normalized_status", "Normalized state", SorFieldDataType.ENUM),
        _field("priority", "Priority", SorFieldDataType.ENUM),
        _field("category", "Source type", SorFieldDataType.TEXT),
        _field("channel", "Delivery channel", SorFieldDataType.TEXT),
        _field("tag_external_ids", "Tag IDs", SorFieldDataType.STRING_ARRAY),
        _field("first_response_at", "First admin reply", SorFieldDataType.TIMESTAMP),
        _field("resolved_at", "Resolved at", SorFieldDataType.TIMESTAMP),
        _field("closed_at", "Closed at", SorFieldDataType.TIMESTAMP),
        _field("sla_state", "SLA state", SorFieldDataType.TEXT),
    ),
    IntercomStream.CONTACTS: (
        _field("name", "Name", SorFieldDataType.TEXT),
        _field("primary_email", "Email", SorFieldDataType.TEXT),
        _field("primary_phone", "Phone", SorFieldDataType.TEXT),
        _field("company_external_id", "Company ID", SorFieldDataType.REFERENCE),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
    ),
    IntercomStream.ADMINS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("primary_email", "Email", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
        _field("assignable", "Has inbox seat", SorFieldDataType.BOOLEAN),
        _field("avatar_url", "Avatar URL", SorFieldDataType.LINK),
    ),
    IntercomStream.TEAMS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("description", "Description", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
    ),
    IntercomStream.CONVERSATION_PARTS: (
        _field(
            "ticket_external_id",
            "Conversation ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("visibility", "Visibility", SorFieldDataType.ENUM, nullable=False),
        _field("direction", "Direction", SorFieldDataType.ENUM),
        _field("author_external_id", "Author ID", SorFieldDataType.REFERENCE),
        _field("normalized_text", "Message", SorFieldDataType.TEXT, nullable=False),
        _field("source_body", "Source body", SorFieldDataType.BOUNDED_JSON),
        _field("body_format", "Body format", SorFieldDataType.TEXT),
        _field(
            "attachment_external_ids", "Attachment IDs", SorFieldDataType.STRING_ARRAY
        ),
        _field("created_at", "Created at", SorFieldDataType.TIMESTAMP, nullable=False),
        _field("updated_at", "Updated at", SorFieldDataType.TIMESTAMP),
    ),
    IntercomStream.TAGS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
    ),
    IntercomStream.ATTACHMENTS: (
        _field(
            "ticket_external_id",
            "Conversation ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("message_external_id", "Message ID", SorFieldDataType.REFERENCE),
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("content_type", "Content type", SorFieldDataType.TEXT),
        _field("size_bytes", "Size", SorFieldDataType.INTEGER),
        _field("source_url", "Download URL", SorFieldDataType.LINK),
    ),
}
_STATUS_MAP: dict[str, SupportTicketState] = {
    native.ConversationState.OPEN: SupportTicketState.OPEN,
    native.ConversationState.CLOSED: SupportTicketState.CLOSED,
    native.ConversationState.SNOOZED: SupportTicketState.PENDING,
}
_ATTRIBUTE_TYPES: dict[str, SorFieldDataType] = {
    native.AttributeType.BOOLEAN: SorFieldDataType.BOOLEAN,
    native.AttributeType.DATE: SorFieldDataType.TIMESTAMP,
    native.AttributeType.DATETIME: SorFieldDataType.TIMESTAMP,
    native.AttributeType.FLOAT: SorFieldDataType.DECIMAL,
    native.AttributeType.INTEGER: SorFieldDataType.INTEGER,
    native.AttributeType.LIST: SorFieldDataType.BOUNDED_JSON,
    native.AttributeType.OBJECT: SorFieldDataType.BOUNDED_JSON,
}


class _SearchCursor(BaseModel):
    """Intercom search watermark and native continuation position."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    watermark: int = Field(default=0, ge=0)
    starting_after: str | None = None
    max_seen: int = Field(default=0, ge=0)
    item_offset: int = Field(default=0, ge=0)


class _SearchCursorEnvelope(_SearchCursor):
    """Stored version-1 cursor requires every field and a nondecreasing watermark."""

    v: int = Field(ge=INTERCOM_CURSOR_VERSION, le=INTERCOM_CURSOR_VERSION)
    stream: str
    watermark: int = Field(ge=0)
    starting_after: str | None
    max_seen: int = Field(ge=0)
    item_offset: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_position(self) -> "_SearchCursorEnvelope":
        if self.max_seen < self.watermark:
            raise ValueError("Intercom max_seen precedes the watermark.")
        if self.starting_after is not None and not (
            1 <= len(self.starting_after) <= INTERCOM_CONTINUATION_LIMIT
        ):
            raise ValueError("Intercom continuation length is invalid.")
        return self


class _OffsetCursorEnvelope(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    v: int = Field(ge=INTERCOM_CURSOR_VERSION, le=INTERCOM_CURSOR_VERSION)
    stream: str
    offset: int = Field(ge=0)


class _TicketWriteField(StrEnum):
    SUBJECT = "subject"
    REQUESTER = "requester_external_id"
    DESCRIPTION = "normalized_description"


class _TicketWrite(BaseModel):
    """Separate opening-message inputs from an Intercom update body."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    requester_id: str | None
    description: str | None = Field(repr=False)
    update: native.UpdateConversation


class _IdentitySegment(StrEnum):
    SOURCE = "source"
    POSITION = "position"


class _MessageIdentity(BaseModel):
    """A native message ID, or the singleton opening source when it has no ID."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    conversation_id: str
    message_id: str | None

    def to_external_id(self) -> str:
        conversation_id = _identity_segment(self.conversation_id)
        if self.message_id is None:
            return f"{conversation_id}::{_IdentitySegment.SOURCE}"
        return f"{conversation_id}:{_identity_segment(self.message_id)}"


class _AttachmentIdentity(BaseModel):
    """Native attachment identity or an explicitly positional current-snapshot slot."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    message: _MessageIdentity
    attachment_id: str | None = None
    position: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_one_identity(self) -> _AttachmentIdentity:
        if (self.attachment_id is None) == (self.position is None):
            raise ValueError("An attachment requires either a native ID or a position.")
        return self

    def to_external_id(self) -> str:
        message_id = self.message.to_external_id()
        if self.attachment_id is not None:
            return f"{message_id}:{_identity_segment(self.attachment_id)}"
        return f"{message_id}::{_IdentitySegment.POSITION}:{self.position}"


class _ExpandedAttachment(BaseModel):
    """Parent identity belongs to the adapter, never injected into native fields."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    conversation_id: str
    message_id: str | None
    position: int = Field(ge=0)
    attachment: native.Attachment

    def source_snapshot(self) -> dict[str, object]:
        return {
            **self.attachment.model_dump(mode="json", exclude_unset=True),
            "_conversation_id": self.conversation_id,
            "_message_id": self.message_id,
        }


class _ExpandedMessage(BaseModel):
    """One retained message with explicit parent and effective source timestamps."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    conversation_id: str
    message_id: str | None
    part_type: native.MessageType
    message: native.Message = Field(repr=False)
    created_at: native.Timestamp | None
    updated_at: native.Timestamp | None
    attachments: tuple[_ExpandedAttachment, ...]

    def source_snapshot(self) -> dict[str, object]:
        snapshot = self.message.model_dump(mode="json", exclude_unset=True)
        if isinstance(self.message, native.ConversationSource):
            snapshot.update(created_at=self.created_at, updated_at=self.updated_at)
        return {
            **snapshot,
            "_conversation_id": self.conversation_id,
            "_part_type": self.part_type.value,
            IntercomStream.ATTACHMENTS: [
                item.source_snapshot() for item in self.attachments
            ],
        }


type _SourceRecord = (
    native.Conversation
    | native.Contact
    | native.Admin
    | native.Team
    | native.Tag
    | _ExpandedMessage
    | _ExpandedAttachment
)


class IntercomSupportAdapter:
    """Translate one exact Intercom workspace into Eylo Support records."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "intercom":
            raise ValueError("Intercom adapter requires the intercom vendor key.")
        if context.auth_kind is not ConnectionAuthKind.OAUTH2:
            raise ValueError("Intercom SOR requires OAuth 2.0.")
        self._context = context
        self._origin = _intercom_origin(context.instance_origin)
        self._client = SorJsonHttpClient(
            origin=self._origin,
            authorization=f"Bearer {_credential(context.credentials, 'access_token')}",
            transport=transport,
            response_body_limit=native.RESPONSE_BODY_LIMIT,
            default_headers={"Intercom-Version": INTERCOM_API_VERSION},
        )
        self._acting_admin_id: str | None = None

    async def verify_connection(self) -> SorConnectionVerification:
        viewer = await self._current_admin()
        app = viewer.app
        if app is None:
            raise _invalid_response("Intercom workspace is missing.")
        region = _required_string(app.region, field="Intercom region").upper()
        expected_region = _ORIGIN_REGIONS[self._origin][1]
        if region != expected_region:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_REGION_MISMATCH,
                "The selected Intercom data region does not match this workspace.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        return SorConnectionVerification(
            account_external_id=_required_id(
                app.id_code, field="Intercom workspace ID"
            ),
            account_display_name=_optional_string(app.name) or "Intercom workspace",
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=INTERCOM_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise SorVendorOperationError(
                SorVendorErrorCode.SOURCE_SELECTION_EMPTY,
                "The Intercom source selects no streams.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        contact_attributes: tuple[SorDiscoveredField, ...] = ()
        conversation_attributes: tuple[SorDiscoveredField, ...] = ()
        if IntercomStream.CONTACTS in self._context.selected_objects:
            response = await self._client.request(
                "/data_attributes", query=native.AttributeQuery().to_wire()
            )
            data = native.parse_response(
                _expect(response, operation="list Intercom contact fields"),
                native.AttributeList,
            )
            contact_attributes = _attribute_fields(
                data.data,
                writable=False,
            )
        if IntercomStream.CONVERSATIONS in self._context.selected_objects:
            response = await self._client.request("/conversations/attributes")
            data = native.parse_response(
                _expect(response, operation="list Intercom conversation fields"),
                native.AttributeList,
            )
            conversation_attributes = _attribute_fields(
                data.data,
                writable=True,
            )

        streams = {stream.key: stream for stream in INTERCOM_MANIFEST.streams}
        objects: list[SorDiscoveredObject] = []
        for stream_key in self._context.selected_objects:
            stream_key = _require_stream(
                stream_key, selected=self._context.selected_objects
            )
            fields = _SCHEMA_FIELDS[stream_key]
            if stream_key == IntercomStream.CONTACTS:
                fields = (*fields, *contact_attributes)
            elif stream_key == IntercomStream.CONVERSATIONS:
                fields = (*fields, *conversation_attributes)
            objects.append(
                SorDiscoveredObject(
                    key=stream_key,
                    label=streams[stream_key].label,
                    fields=fields,
                )
            )
        return SorDiscoveredSchema(
            objects=tuple(objects),
            vendor_api_version=INTERCOM_API_VERSION,
        )

    async def bootstrap_stream(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        return await self._read_page(stream_key=stream_key, cursor=cursor, limit=limit)

    async def pull_changes(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        return await self._read_page(stream_key=stream_key, cursor=cursor, limit=limit)

    async def fetch_record(
        self,
        *,
        vendor_object_key: str,
        external_id: str,
    ) -> SorExternalRecord:
        stream_key = _require_stream(
            vendor_object_key,
            selected=self._context.selected_objects,
        )
        record_id = _required_id(external_id, field="Intercom record ID")
        if stream_key == IntercomStream.CONVERSATIONS:
            return self._external_record(
                stream_key,
                await self._conversation(record_id),
            )
        if stream_key == IntercomStream.CONTACTS:
            response = await self._client.request(f"/contacts/{_path_id(record_id)}")
            if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            return self._external_record(
                stream_key,
                native.parse_response(
                    _expect(response, operation="read Intercom contact"),
                    native.Contact,
                ),
            )
        if stream_key in {
            IntercomStream.ADMINS,
            IntercomStream.TEAMS,
            IntercomStream.TAGS,
        }:
            rows = await self._reconcile_rows(stream_key)
            row = next(
                (item for item in rows if _optional_id(item.id) == record_id),
                None,
            )
            if row is None:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            return self._external_record(stream_key, row)
        if stream_key == IntercomStream.CONVERSATION_PARTS:
            conversation_id = _decode_message_identity(record_id).conversation_id
            conversation = await self._conversation(conversation_id)
            _require_complete_parts(conversation)
            row = next(
                (
                    item
                    for item in _message_rows(conversation)
                    if _message_external_id(conversation_id, item) == record_id
                ),
                None,
            )
        else:
            conversation_id = _decode_attachment_identity(
                record_id
            ).message.conversation_id
            conversation = await self._conversation(conversation_id)
            _require_complete_parts(conversation)
            row = next(
                (
                    item
                    for item in _attachment_rows(conversation)
                    if _attachment_external_id(conversation_id, item) == record_id
                ),
                None,
            )
        if row is None:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        return self._external_record(stream_key, row)

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "Intercom deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Configure the Intercom webhook URL and topics in Developer Hub."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Developer Hub webhooks do not have an Eylo renewal flow."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable("Remove the Intercom webhook in Developer Hub.")

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        secret = self._context.webhook_signing_secret
        if secret is None or not secret:
            raise SorCapabilityUnavailable(
                "Intercom webhook verification requires the app client secret."
            )
        verify_intercom_app_webhook(
            headers=headers,
            body=body,
            client_secret=secret,
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        return (parse_intercom_app_webhook(body=body).signal,)

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_TOOL_UNSUPPORTED,
                "This Intercom adapter does not execute the requested support action.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if command.tool_name == SupportToolName.OPEN_TICKET:
            return await self._open_conversation(command)
        conversation_id = _required_target(command)
        if command.tool_name == SupportToolName.UPDATE_TICKET:
            return await self._update_conversation(conversation_id, command)
        if command.tool_name == SupportToolName.ASSIGN_TICKET:
            return await self._assign_conversation(conversation_id, command)
        if command.tool_name in {SupportToolName.REPLY, SupportToolName.ADD_NOTE}:
            return await self._reply(
                conversation_id,
                command,
                visibility=(
                    SupportMessageVisibility.PUBLIC
                    if command.tool_name == SupportToolName.REPLY
                    else SupportMessageVisibility.PRIVATE
                ),
            )
        if command.tool_name == SupportToolName.CLOSE_TICKET:
            return await self._close_conversation(conversation_id, command)
        return await self._change_tag(
            conversation_id,
            command,
            action=(
                native.TagAction.ADD
                if command.tool_name == SupportToolName.ADD_TAG
                else native.TagAction.REMOVE
            ),
        )

    def normalize_ticket(
        self,
        record: SorExternalRecord,
        payload: SupportTicketPayload,
    ) -> SupportTicket:
        return SupportTicket(
            external_id=record.external_id,
            subject=_optional_string(payload.subject),
            normalized_description=_optional_string(payload.normalized_description),
            requester_external_id=_optional_string(payload.requester_external_id),
            assignee_external_id=_optional_string(payload.assignee_external_id),
            group_external_id=_optional_string(payload.group_external_id),
            inbox_external_id=_optional_string(payload.inbox_external_id),
            native_status=_optional_string(payload.native_status),
            normalized_status=payload.normalized_status,
            priority=_optional_string(payload.priority),
            category=_optional_string(payload.category),
            channel=_optional_string(payload.channel),
            tag_external_ids=payload.tag_external_ids,
            first_response_at=payload.first_response_at,
            resolved_at=payload.resolved_at,
            closed_at=payload.closed_at,
            sla_state=payload.sla_state,
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
            custom_fields={},
        )

    def normalize_customer(
        self,
        record: SorExternalRecord,
        payload: SupportCustomerPayload,
    ) -> SupportCustomer:
        return SupportCustomer(
            external_id=record.external_id,
            name=_optional_string(payload.name),
            primary_email=_optional_string(payload.primary_email),
            primary_phone=_optional_string(payload.primary_phone),
            company_external_id=_optional_string(payload.company_external_id),
            active=payload.active,
            source_url=record.source_url,
            custom_fields={},
        )

    def normalize_agent(
        self,
        record: SorExternalRecord,
        payload: SupportAgentPayload,
    ) -> SupportAgent:
        return SupportAgent(
            external_id=record.external_id,
            name=_required_string(payload.name, field="Intercom admin name"),
            primary_email=_optional_string(payload.primary_email),
            active=payload.active,
            assignable=payload.assignable,
            avatar_url=_optional_string(payload.avatar_url),
        )

    def normalize_message(
        self,
        record: SorExternalRecord,
        payload: SupportMessagePayload,
    ) -> SupportMessage:
        return SupportMessage(
            external_id=record.external_id,
            ticket_external_id=_required_string(
                payload.ticket_external_id, field="Intercom conversation ID"
            ),
            visibility=payload.visibility,
            direction=payload.direction,
            author_external_id=_optional_string(payload.author_external_id),
            normalized_text=_required_string(
                payload.normalized_text, field="Intercom message text"
            ),
            source_body=_json_value(payload.source_body),
            body_format=_optional_string(payload.body_format),
            attachment_external_ids=payload.attachment_external_ids,
            created_at=payload.created_at,
            updated_at=payload.updated_at,
        )

    def normalize_queue(
        self,
        record: SorExternalRecord,
        payload: SupportQueuePayload,
    ) -> SupportQueue:
        return SupportQueue(
            external_id=record.external_id,
            name=_required_string(payload.name, field="Intercom team name"),
            description=_optional_string(payload.description),
            active=payload.active,
        )

    def normalize_inbox(
        self,
        record: SorExternalRecord,
        payload: SupportInboxPayload,
    ) -> SupportInbox:
        raise SorCapabilityUnavailable(
            "Intercom inboxes are not a selected canonical stream."
        )

    def normalize_tag(
        self,
        record: SorExternalRecord,
        payload: SupportTagPayload,
    ) -> SupportTag:
        return SupportTag(
            external_id=record.external_id,
            name=_required_string(payload.name, field="Intercom tag name"),
        )

    def normalize_sla_metric(
        self,
        record: SorExternalRecord,
        payload: SupportSlaMetricPayload,
    ) -> SupportSlaMetric:
        raise SorCapabilityUnavailable(
            "Intercom SLA metrics are summarized on conversations in this revision."
        )

    def normalize_attachment(
        self,
        record: SorExternalRecord,
        payload: SupportAttachmentPayload,
    ) -> SupportAttachment:
        return SupportAttachment(
            external_id=record.external_id,
            ticket_external_id=_required_string(
                payload.ticket_external_id, field="Intercom conversation ID"
            ),
            message_external_id=_optional_string(payload.message_external_id),
            name=_required_string(payload.name, field="Intercom attachment name"),
            content_type=_optional_string(payload.content_type),
            size_bytes=payload.size_bytes,
            source_url=_optional_string(payload.source_url),
        )

    async def close(self) -> None:
        return None

    async def _read_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        stream_key = _require_stream(
            stream_key,
            selected=self._context.selected_objects,
        )
        if limit <= 0:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_PAGE_INVALID,
                "Intercom page limit must be positive.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if stream_key in {IntercomStream.CONVERSATIONS, IntercomStream.CONTACTS}:
            return await self._read_search_page(
                stream_key=stream_key,
                cursor=cursor,
                limit=min(limit, native.SEARCH_PAGE_LIMIT),
            )
        if stream_key in {
            IntercomStream.CONVERSATION_PARTS,
            IntercomStream.ATTACHMENTS,
        }:
            return await self._read_expanded_page(
                stream_key=stream_key,
                cursor=cursor,
                limit=min(limit, native.EXPANDED_PAGE_LIMIT),
            )
        return await self._read_reconcile_page(
            stream_key=stream_key,
            cursor=cursor,
            limit=limit,
        )

    async def _read_search_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        state = _decode_search_cursor(cursor, stream_key=stream_key)
        rows, next_page, max_seen = await self._search_rows(
            stream_key=stream_key,
            state=state,
            limit=limit,
        )
        if next_page is None:
            terminal = _SearchCursor(
                watermark=max(state.watermark, max_seen),
                max_seen=max(state.watermark, max_seen),
            )
            next_cursor = _encode_search_cursor(terminal, stream_key=stream_key)
        else:
            next_cursor = _encode_search_cursor(
                _SearchCursor(
                    watermark=state.watermark,
                    starting_after=next_page,
                    max_seen=max_seen,
                ),
                stream_key=stream_key,
            )
        return SorRecordPage(
            records=tuple(self._external_record(stream_key, row) for row in rows),
            next_cursor=next_cursor,
            has_more=next_page is not None,
        )

    async def _read_expanded_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        state = _decode_search_cursor(cursor, stream_key=stream_key)
        records: list[SorExternalRecord] = []
        empty_expansions = 0
        while len(records) < limit:
            rows, next_page, max_seen = await self._search_rows(
                stream_key=IntercomStream.CONVERSATIONS,
                state=state,
                limit=1,
            )
            if not rows:
                terminal_watermark = max(state.watermark, max_seen)
                return SorRecordPage(
                    records=tuple(records),
                    next_cursor=_encode_search_cursor(
                        _SearchCursor(
                            watermark=terminal_watermark,
                            max_seen=terminal_watermark,
                        ),
                        stream_key=stream_key,
                    ),
                    has_more=False,
                )
            conversation_id = _required_id(rows[0].id, field="Intercom conversation ID")
            conversation = await self._conversation(conversation_id)
            _require_complete_parts(conversation)
            expanded = (
                _message_rows(conversation)
                if stream_key == IntercomStream.CONVERSATION_PARTS
                else _attachment_rows(conversation)
            )
            if state.item_offset > len(expanded):
                raise _invalid_response(
                    "Intercom expanded cursor exceeds its conversation."
                )
            remaining = expanded[state.item_offset :]
            take = min(limit - len(records), len(remaining))
            records.extend(
                self._external_record(stream_key, row) for row in remaining[:take]
            )
            new_offset = state.item_offset + take
            if new_offset < len(expanded):
                return SorRecordPage(
                    records=tuple(records),
                    next_cursor=_encode_search_cursor(
                        _SearchCursor(
                            watermark=state.watermark,
                            starting_after=state.starting_after,
                            max_seen=max_seen,
                            item_offset=new_offset,
                        ),
                        stream_key=stream_key,
                    ),
                    has_more=True,
                )
            if next_page is None:
                terminal_watermark = max(state.watermark, max_seen)
                return SorRecordPage(
                    records=tuple(records),
                    next_cursor=_encode_search_cursor(
                        _SearchCursor(
                            watermark=terminal_watermark,
                            max_seen=terminal_watermark,
                        ),
                        stream_key=stream_key,
                    ),
                    has_more=False,
                )
            state = _SearchCursor(
                watermark=state.watermark,
                starting_after=next_page,
                max_seen=max_seen,
            )
            if not remaining:
                empty_expansions += 1
                if empty_expansions >= INTERCOM_MAX_EMPTY_EXPANSIONS:
                    return SorRecordPage(
                        records=tuple(records),
                        next_cursor=_encode_search_cursor(
                            state,
                            stream_key=stream_key,
                        ),
                        has_more=True,
                    )
        return SorRecordPage(
            records=tuple(records),
            next_cursor=_encode_search_cursor(state, stream_key=stream_key),
            has_more=True,
        )

    async def _search_rows(
        self,
        *,
        stream_key: str,
        state: _SearchCursor,
        limit: int,
    ) -> tuple[list[native.Contact] | list[native.Conversation], str | None, int]:
        request = native.SearchRequest(
            query=native.SearchFilter(
                value=max(0, state.watermark - INTERCOM_OVERLAP_SECONDS)
            ),
            pagination=native.SearchPagination(
                per_page=limit, starting_after=state.starting_after
            ),
        )
        response = await self._client.request(
            "/contacts/search"
            if stream_key == IntercomStream.CONTACTS
            else "/conversations/search",
            method=HTTPMethod.POST,
            payload=request.model_dump(mode="json", exclude_none=True),
        )
        data = _expect(response, operation=f"search Intercom {stream_key}")
        if stream_key == IntercomStream.CONTACTS:
            page = native.parse_response(data, native.ContactPage)
            rows = page.data
        else:
            page = native.parse_response(data, native.ConversationPage)
            rows = page.conversations
        if len(rows) > limit:
            raise _invalid_response(
                f"Intercom returned more {stream_key} than requested."
            )
        max_seen = max(
            [state.max_seen, state.watermark]
            + [_optional_epoch(row.updated_at) or 0 for row in rows]
        )
        return rows, _next_starting_after(page.pages), max_seen

    async def _read_reconcile_page(
        self,
        *,
        stream_key: IntercomStream,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        offset = _decode_offset_cursor(cursor, stream_key=stream_key)
        rows = sorted(
            await self._reconcile_rows(stream_key),
            key=lambda row: _required_id(row.id, field="Intercom record ID"),
        )
        selected = rows[offset : offset + limit]
        next_offset = offset + len(selected)
        has_more = next_offset < len(rows)
        return SorRecordPage(
            records=tuple(self._external_record(stream_key, row) for row in selected),
            next_cursor=(
                _encode_offset_cursor(next_offset, stream_key=stream_key)
                if has_more
                else None
            ),
            has_more=has_more,
        )

    async def _reconcile_rows(
        self, stream_key: IntercomStream
    ) -> list[native.Admin] | list[native.Team] | list[native.Tag]:
        if stream_key == IntercomStream.ADMINS:
            response = await self._client.request(
                "/admins", query=native.AdminQuery().to_wire()
            )
            return native.parse_response(
                _expect(response, operation="list Intercom admins"), native.AdminList
            ).admins
        if stream_key == IntercomStream.TEAMS:
            response = await self._client.request("/teams")
            return native.parse_response(
                _expect(response, operation="list Intercom teams"), native.TeamList
            ).teams
        response = await self._client.request("/tags")
        return native.parse_response(
            _expect(response, operation="list Intercom tags"), native.TagList
        ).data

    async def _conversation(self, conversation_id: str) -> native.Conversation:
        response = await self._client.request(
            f"/conversations/{_path_id(conversation_id)}",
            query=native.ConversationQuery().to_wire(),
        )
        if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
            raise SorExternalRecordNotFound(
                vendor_object_key=IntercomStream.CONVERSATIONS,
                external_id=conversation_id,
            )
        return native.parse_response(
            _expect(response, operation="read Intercom conversation"),
            native.Conversation,
        )

    async def _current_admin(self) -> native.Viewer:
        response = await self._client.request("/me")
        viewer = native.parse_response(
            _expect(response, operation="identify Intercom admin"), native.Viewer
        )
        self._acting_admin_id = _required_id(viewer.id, field="Intercom admin ID")
        return viewer

    async def _admin_id(self) -> str:
        if self._acting_admin_id is None:
            await self._current_admin()
        if self._acting_admin_id is None:
            raise _invalid_response("Intercom omitted the authorized admin ID.")
        return self._acting_admin_id

    def _external_record(
        self,
        stream_key: str,
        row: _SourceRecord,
    ) -> SorExternalRecord:
        if isinstance(row, native.Conversation):
            source = row.source or native.ConversationSource()
            statistics = row.statistics or native.Statistics()
            contacts = row.contacts.contacts or [] if row.contacts else []
            tags = row.tags.tags or [] if row.tags else []
            state = _optional_string(row.state)
            updated_epoch = _optional_epoch(row.updated_at)
            payload: dict[str, object] = {
                "subject": row.title or source.subject,
                "normalized_description": _plain_text(source.body),
                "requester_external_id": (
                    _optional_id(contacts[0].id) if contacts else None
                ),
                "assignee_external_id": _optional_assignee_id(row.admin_assignee_id),
                "group_external_id": _optional_assignee_id(row.team_assignee_id),
                "native_status": state,
                "normalized_status": _STATUS_MAP.get(state or ""),
                "priority": row.priority,
                "category": source.type,
                "channel": source.delivered_as,
                "tag_external_ids": [
                    tag_id
                    for item in tags
                    if (tag_id := _optional_id(item.id)) is not None
                ],
                "first_response_at": _optional_datetime(
                    statistics.first_admin_reply_at
                ),
                "resolved_at": (
                    _optional_datetime(statistics.last_close_at)
                    if state == native.ConversationState.CLOSED
                    else None
                ),
                "closed_at": (
                    _optional_datetime(statistics.last_close_at)
                    if state == native.ConversationState.CLOSED
                    else None
                ),
                "sla_state": row.sla_applied.sla_status if row.sla_applied else None,
            }
            payload.update(_custom_attribute_values(row.custom_attributes))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.id, field="Intercom conversation ID"),
                payload=payload,
                source_created_at=_optional_datetime(row.created_at),
                source_updated_at=_epoch_datetime(updated_epoch),
                source_revision=_epoch_revision(updated_epoch),
            )
        if isinstance(row, native.Contact):
            companies = row.companies.data or [] if row.companies else []
            updated_epoch = _optional_epoch(row.updated_at)
            payload = {
                "name": row.name,
                "primary_email": row.email,
                "primary_phone": row.phone,
                "company_external_id": (
                    _optional_id(companies[0].id) if companies else None
                ),
                "active": None,
            }
            payload.update(_custom_attribute_values(row.custom_attributes))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.id, field="Intercom contact ID"),
                payload=payload,
                source_created_at=_optional_datetime(row.created_at),
                source_updated_at=_epoch_datetime(updated_epoch),
                source_revision=_epoch_revision(updated_epoch),
            )
        if isinstance(row, native.Admin):
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.id, field="Intercom admin ID"),
                payload={
                    "name": row.name,
                    "primary_email": row.email,
                    "active": True,
                    "assignable": row.has_inbox_seat,
                    "avatar_url": _safe_source_url(
                        row.avatar.image_url if row.avatar else None
                    ),
                },
            )
        if isinstance(row, native.Team):
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.id, field="Intercom team ID"),
                payload={"name": row.name, "description": None, "active": True},
            )
        if isinstance(row, native.Tag):
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.id, field="Intercom tag ID"),
                payload={"name": row.name},
            )
        if isinstance(row, _ExpandedMessage):
            author = row.message.author or native.Author()
            created_at = _required_datetime(
                row.created_at, field="Intercom message creation time"
            )
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_expanded_id(row.conversation_id, row.message_id),
                payload={
                    "ticket_external_id": row.conversation_id,
                    "visibility": (
                        SupportMessageVisibility.PRIVATE
                        if row.part_type == native.MessageType.NOTE
                        else SupportMessageVisibility.PUBLIC
                    ),
                    "direction": _message_direction(author.type),
                    "author_external_id": _optional_id(author.id),
                    "normalized_text": _message_text(row),
                    "source_body": row.source_snapshot(),
                    "body_format": "text/plain",
                    "attachment_external_ids": [
                        _attachment_external_id(row.conversation_id, item)
                        for item in row.attachments
                    ],
                    "created_at": created_at,
                    "updated_at": _optional_datetime(row.updated_at),
                },
                source_created_at=created_at,
                source_updated_at=_optional_datetime(row.updated_at),
                source_revision=_epoch_revision(_optional_epoch(row.updated_at)),
            )
        attachment = row.attachment
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=_attachment_external_id(row.conversation_id, row),
            payload={
                "ticket_external_id": row.conversation_id,
                "message_external_id": _expanded_id(
                    row.conversation_id, row.message_id
                ),
                "name": attachment.name,
                "content_type": attachment.content_type,
                "size_bytes": attachment.filesize or attachment.size,
                "source_url": _safe_source_url(attachment.url),
            },
            source_url=_safe_source_url(attachment.url),
        )

    async def _open_conversation(
        self,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command(
                "Opening an Intercom conversation cannot target an existing one."
            )
        if not isinstance(command.payload, SupportMappedFieldsCommandPayload):
            raise _invalid_command("Intercom conversation fields payload is invalid.")
        values = self._ticket_write_values(command.payload.fields)
        if values.requester_id is None:
            raise _invalid_command(
                "Opening an Intercom conversation requires requester_external_id."
            )
        if values.description is None:
            raise _invalid_command(
                "Opening an Intercom conversation requires normalized_description."
            )
        response = await self._mutation_request(
            "/conversations",
            method=HTTPMethod.POST,
            payload=native.OpenConversation(
                sender=native.ContactSender(id=values.requester_id),
                body=values.description,
            ),
            operation="open an Intercom conversation",
        )
        message = native.parse_response(
            _expect(response, operation="open an Intercom conversation"),
            native.OpenResult,
        )
        conversation_id = _required_id(
            message.conversation_id, field="Intercom conversation ID"
        )
        if values.update.model_fields_set:
            await self._mutation_request(
                f"/conversations/{_path_id(conversation_id)}",
                method=HTTPMethod.PUT,
                payload=values.update,
                operation="finish an Intercom conversation",
            )
        return SorCommandResult(
            vendor_object_key=IntercomStream.CONVERSATIONS,
            external_id=conversation_id,
            external_request_id=_request_id(response),
            source_url=None,
            response={"status": "accepted"},
        )

    async def _update_conversation(
        self,
        conversation_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportMappedFieldsCommandPayload):
            raise _invalid_command("Intercom conversation fields payload is invalid.")
        values = self._ticket_write_values(command.payload.fields)
        if values.requester_id is not None or values.description is not None:
            raise _invalid_command(
                "Intercom cannot update a conversation requester or opening message."
            )
        if not values.update.model_fields_set:
            raise _invalid_command(
                "Updating an Intercom conversation requires mapped fields."
            )
        response = await self._mutation_request(
            f"/conversations/{_path_id(conversation_id)}",
            method=HTTPMethod.PUT,
            payload=values.update,
            operation="update an Intercom conversation",
        )
        return self._conversation_result(response)

    async def _assign_conversation(
        self,
        conversation_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportAssignCommandPayload):
            raise _invalid_command("Intercom assignment payload is invalid.")
        admin_id = await self._admin_id()
        response: SorJsonResponse | None = None
        for raw_assignee_id, assignee_type in (
            (command.payload.group_external_id, native.ActorType.TEAM),
            (command.payload.assignee_external_id, native.ActorType.ADMIN),
        ):
            if raw_assignee_id is None:
                continue
            assignee_id = _required_id(
                raw_assignee_id, field=f"Intercom {assignee_type} assignee ID"
            )
            response = await self._mutation_request(
                f"/conversations/{_path_id(conversation_id)}/parts",
                method=HTTPMethod.POST,
                payload=native.AssignConversation(
                    type=assignee_type, admin_id=admin_id, assignee_id=assignee_id
                ),
                operation="assign an Intercom conversation",
            )
            # Refuse malformed first acknowledgements before a possible second write.
            native.parse_response(
                _expect(response, operation="assign an Intercom conversation"),
                native.ConversationResult,
            )
        if response is None:
            raise _invalid_command("Intercom assignment contains no assignee.")
        return self._conversation_result(response)

    async def _reply(
        self,
        conversation_id: str,
        command: SorCommandRequest,
        *,
        visibility: SupportMessageVisibility,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportMessageCommandPayload):
            raise _invalid_command("Intercom message payload is invalid.")
        response = await self._mutation_request(
            f"/conversations/{_path_id(conversation_id)}/reply",
            method=HTTPMethod.POST,
            payload=native.Reply(
                admin_id=await self._admin_id(),
                message_type=(
                    native.MessageType.COMMENT
                    if visibility is SupportMessageVisibility.PUBLIC
                    else native.MessageType.NOTE
                ),
                body=command.payload.normalized_text,
            ),
            operation=(
                "reply to an Intercom conversation"
                if visibility is SupportMessageVisibility.PUBLIC
                else "add an Intercom private note"
            ),
        )
        conversation = native.parse_response(
            _expect(response, operation="write an Intercom conversation message"),
            native.ReplyResult,
        )
        part = _latest_message_part(conversation, visibility=visibility)
        part_id = _required_id(part.id, field="Intercom message ID")
        return SorCommandResult(
            vendor_object_key=IntercomStream.CONVERSATION_PARTS,
            external_id=_expanded_id(conversation_id, part_id),
            external_request_id=_request_id(response),
            source_revision=_epoch_revision(_optional_epoch(conversation.updated_at)),
            response={"status": "accepted", "visibility": visibility.value},
        )

    async def _close_conversation(
        self,
        conversation_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if (
            not isinstance(command.payload, SupportCloseCommandPayload)
            or command.payload.native_status is not None
        ):
            raise _invalid_command("Intercom close payload is invalid.")
        request = native.CloseConversation(admin_id=await self._admin_id())
        if command.payload.normalized_text is not None:
            request = native.CloseConversation(
                admin_id=request.admin_id, body=command.payload.normalized_text
            )
        response = await self._mutation_request(
            f"/conversations/{_path_id(conversation_id)}/parts",
            method=HTTPMethod.POST,
            payload=request,
            operation="close an Intercom conversation",
        )
        return self._conversation_result(response)

    async def _change_tag(
        self,
        conversation_id: str,
        command: SorCommandRequest,
        *,
        action: native.TagAction,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportTagCommandPayload):
            raise _invalid_command("Intercom tag payload is invalid.")
        tag_id = _required_id(command.payload.tag_external_id, field="Intercom tag ID")
        path = f"/conversations/{_path_id(conversation_id)}/tags"
        if action is native.TagAction.REMOVE:
            path = f"{path}/{_path_id(tag_id)}"
        admin_id = await self._admin_id()
        response = await self._mutation_request(
            path,
            method=HTTPMethod.POST
            if action is native.TagAction.ADD
            else HTTPMethod.DELETE,
            payload=(
                native.TagMutation(id=tag_id, admin_id=admin_id)
                if action is native.TagAction.ADD
                else native.TagMutation(admin_id=admin_id)
            ),
            operation="change an Intercom conversation tag",
        )
        return SorCommandResult(
            vendor_object_key=IntercomStream.CONVERSATIONS,
            external_id=conversation_id,
            external_request_id=_request_id(response),
            response={"status": "accepted"},
        )

    def _ticket_write_values(self, payload: Mapping[str, object]) -> _TicketWrite:
        writable = {
            field.agent_key: field.vendor_field_key
            for field in self._context.fields
            if field.vendor_object_key == IntercomStream.CONVERSATIONS
            and field.writable
        }
        if not payload:
            raise _invalid_command(
                "An Intercom conversation mutation requires mapped fields."
            )
        unknown = set(payload) - set(writable)
        if unknown:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_FIELD_NOT_WRITABLE,
                "The requested Intercom field is not writable by this source mapping.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        values: dict[str, object] = {}
        custom: dict[str, object] = {}
        requester_id: str | None = None
        description: str | None = None
        for agent_key, value in payload.items():
            vendor_key = writable[agent_key]
            if vendor_key == _TicketWriteField.SUBJECT:
                values["title"] = value
            elif vendor_key == _TicketWriteField.REQUESTER:
                requester_id = _required_id(value, field="Intercom requester ID")
            elif vendor_key == _TicketWriteField.DESCRIPTION:
                description = _required_string(value, field="Intercom opening message")
            elif vendor_key.startswith(INTERCOM_CUSTOM_ATTRIBUTE_PREFIX):
                custom[_custom_attribute_name(vendor_key)] = value
            else:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_FIELD_NOT_WRITABLE,
                    "The mapped Intercom field is not writable by this adapter.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                )
        if custom:
            values["custom_attributes"] = custom
        return _TicketWrite(
            requester_id=requester_id,
            description=description,
            update=native.parse_request(values, native.UpdateConversation),
        )

    async def _mutation_request(
        self,
        path: str,
        *,
        method: HTTPMethod,
        payload: native.IntercomRequest,
        operation: str,
    ) -> SorJsonResponse:
        try:
            response = await self._client.request(
                path, method=method, payload=payload.to_wire()
            )
            _expect(response, operation=operation)
            return response
        except SorVendorOperationError as error:
            if error.code in {
                SorVendorErrorCode.VENDOR_TIMEOUT,
                SorVendorErrorCode.VENDOR_TRANSPORT_FAILED,
                SorVendorErrorCode.VENDOR_SERVER_FAILED,
            }:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_MUTATION_OUTCOME_UNKNOWN,
                    "Intercom may have applied the action; reconcile before retrying.",
                    recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
                ) from error
            raise

    def _conversation_result(self, response: SorJsonResponse) -> SorCommandResult:
        conversation = native.parse_response(
            _expect(response, operation="read Intercom mutation acknowledgement"),
            native.ConversationResult,
        )
        return SorCommandResult(
            vendor_object_key=IntercomStream.CONVERSATIONS,
            external_id=_required_id(conversation.id, field="Intercom conversation ID"),
            external_request_id=_request_id(response),
            source_revision=_epoch_revision(_optional_epoch(conversation.updated_at)),
            response={"status": "accepted"},
        )


def create_intercom_adapter(context: SorAdapterContext) -> IntercomSupportAdapter:
    """Construct the production Intercom adapter for the explicit registry."""
    return IntercomSupportAdapter(context)


def _intercom_origin(value: str | None) -> str:
    if value is None:
        raise ValueError("Intercom requires a data-region API origin.")
    parsed = urlsplit(value.strip())
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Intercom API origin is invalid.") from error
    origin = f"https://{(parsed.hostname or '').lower().rstrip('.')}"
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or origin not in _ORIGIN_REGIONS
    ):
        raise ValueError("Intercom API origin is not an exact supported region.")
    return origin


def _credential(credentials: Mapping[str, object], name: str) -> str:
    value = credentials.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Intercom OAuth credentials are incomplete.")
    return value.strip()


def _require_stream(stream_key: str, *, selected: Sequence[str]) -> IntercomStream:
    if stream_key not in _STREAM_ENTITY or stream_key not in selected:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNAVAILABLE,
            "The requested Intercom stream is not selected for this source.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return IntercomStream(stream_key)


def _attribute_fields(
    attributes: Sequence[native.Attribute],
    *,
    writable: bool,
) -> tuple[SorDiscoveredField, ...]:
    result: list[SorDiscoveredField] = []
    for attribute in attributes:
        name = _required_string(
            attribute.name or attribute.full_name,
            field="Intercom attribute name",
        )
        native_type = (
            _optional_string(attribute.data_type) or native.AttributeType.STRING
        ).casefold()
        result.append(
            _field(
                _custom_attribute_key(name),
                _optional_string(attribute.label) or name,
                _ATTRIBUTE_TYPES.get(native_type, SorFieldDataType.TEXT),
                writable=writable,
                description=_optional_string(attribute.description),
            )
        )
    return tuple(sorted(result, key=lambda item: item.key))


def _custom_attribute_key(name: str) -> str:
    encoded = base64.urlsafe_b64encode(name.encode()).decode().rstrip("=")
    return f"{INTERCOM_CUSTOM_ATTRIBUTE_PREFIX}{encoded}"


def _custom_attribute_name(key: str) -> str:
    prefix = INTERCOM_CUSTOM_ATTRIBUTE_PREFIX
    if not key.startswith(prefix):
        raise _invalid_command("Intercom custom attribute identity is invalid.")
    encoded = key[len(prefix) :]
    try:
        decoded = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        ).decode()
    except (UnicodeDecodeError, ValueError) as error:
        raise _invalid_command(
            "Intercom custom attribute identity is invalid."
        ) from error
    if not decoded or _custom_attribute_key(decoded) != key:
        raise _invalid_command("Intercom custom attribute identity is invalid.")
    return decoded


def _custom_attribute_values(
    value: Mapping[str, SorJsonValue] | None,
) -> dict[str, SorJsonValue]:
    result: dict[str, SorJsonValue] = {}
    for name, item in (value or {}).items():
        if not name:
            raise _invalid_response("Intercom custom attribute name is empty.")
        result[_custom_attribute_key(name)] = item
    return result


def _encode_search_cursor(state: _SearchCursor, *, stream_key: str) -> str:
    return _encode_cursor(
        _SearchCursorEnvelope(
            v=INTERCOM_CURSOR_VERSION,
            stream=stream_key,
            watermark=state.watermark,
            starting_after=state.starting_after,
            max_seen=state.max_seen,
            item_offset=state.item_offset,
        )
    )


def _decode_search_cursor(value: str | None, *, stream_key: str) -> _SearchCursor:
    if value is None:
        return _SearchCursor()
    data = _decode_cursor(value, _SearchCursorEnvelope)
    if data.stream != stream_key:
        raise _invalid_cursor()
    return _SearchCursor(
        watermark=data.watermark,
        starting_after=data.starting_after,
        max_seen=data.max_seen,
        item_offset=data.item_offset,
    )


def _encode_offset_cursor(offset: int, *, stream_key: str) -> str:
    return _encode_cursor(
        _OffsetCursorEnvelope(
            v=INTERCOM_CURSOR_VERSION, stream=stream_key, offset=offset
        )
    )


def _decode_offset_cursor(value: str | None, *, stream_key: str) -> int:
    if value is None:
        return 0
    data = _decode_cursor(value, _OffsetCursorEnvelope)
    if data.stream != stream_key:
        raise _invalid_cursor()
    return data.offset


def _encode_cursor(data: _SearchCursorEnvelope | _OffsetCursorEnvelope) -> str:
    raw = json.dumps(
        data.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor[T: BaseModel](value: str, model: type[T]) -> T:
    if not value or len(value) > INTERCOM_CURSOR_LIMIT:
        raise _invalid_cursor()
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
        return model.model_validate_json(raw)
    except (UnicodeDecodeError, ValueError) as error:
        raise _invalid_cursor() from error


def _invalid_cursor() -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_CURSOR_INVALID,
        "The Intercom cursor is invalid or belongs to another stream.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _next_starting_after(pages: native.Pages | None) -> str | None:
    if pages is None or pages.next is None:
        return None
    next_page = pages.next
    if isinstance(next_page, native.NextPage):
        return _required_string(next_page.starting_after, field="Intercom next cursor")
    parsed = urlsplit(next_page)
    if not parsed.query:
        return _required_string(next_page, field="Intercom next cursor")
    for pair in parsed.query.split("&"):
        name, separator, raw_value = pair.partition("=")
        if separator and name == "starting_after":
            from urllib.parse import unquote

            return _required_string(unquote(raw_value), field="Intercom next cursor")
    raise _invalid_response("Intercom returned an invalid next cursor.")


def _message_rows(conversation: native.Conversation) -> list[_ExpandedMessage]:
    conversation_id = _required_id(conversation.id, field="Intercom conversation ID")
    result: list[_ExpandedMessage] = []
    source = conversation.source
    if source is not None and _has_message_content(source):
        result.append(
            _expanded_message(
                source,
                conversation_id=conversation_id,
                part_type=native.MessageType.COMMENT,
                created_at=source.created_at or conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )
    parts = conversation.conversation_parts
    for header in parts.conversation_parts or [] if parts else []:
        part_type = _optional_string(header.part_type)
        if part_type not in {native.MessageType.COMMENT, native.MessageType.NOTE}:
            continue
        part = native.parse_response(
            header.model_dump(mode="json", exclude_unset=True), native.MessagePart
        )
        if not _has_message_content(part):
            continue
        result.append(
            _expanded_message(
                part,
                conversation_id=conversation_id,
                part_type=native.MessageType(part_type),
                created_at=part.created_at,
                updated_at=part.updated_at,
            )
        )
    return sorted(
        result,
        key=lambda item: (_optional_epoch(item.created_at) or 0, item.message_id or ""),
    )


def _expanded_message(
    message: native.Message,
    *,
    conversation_id: str,
    part_type: native.MessageType,
    created_at: native.Timestamp | None,
    updated_at: native.Timestamp | None,
) -> _ExpandedMessage:
    message_id = (
        None
        if isinstance(message, native.ConversationSource) and message.id is None
        else _required_id(message.id, field="Intercom message ID")
    )
    return _ExpandedMessage(
        conversation_id=conversation_id,
        message_id=message_id,
        part_type=part_type,
        message=message,
        created_at=created_at,
        updated_at=updated_at,
        attachments=tuple(
            _ExpandedAttachment(
                conversation_id=conversation_id,
                message_id=message_id,
                position=position,
                attachment=item,
            )
            for position, item in enumerate(message.attachments or [])
        ),
    )


def _has_message_content(message: native.Message) -> bool:
    return bool(_plain_text(message.body) or message.attachments)


def _message_text(row: _ExpandedMessage) -> str:
    body = _plain_text(row.message.body)
    if body:
        return body
    names = [
        _optional_string(item.attachment.name) or "unnamed file"
        for item in row.attachments
    ]
    if names:
        return "\n".join(f"[Attachment: {name}]" for name in names)
    raise _invalid_response("Intercom message has no readable content.")


def _attachment_rows(conversation: native.Conversation) -> list[_ExpandedAttachment]:
    return [
        attachment
        for message in _message_rows(conversation)
        for attachment in message.attachments
    ]


def _require_complete_parts(conversation: native.Conversation) -> None:
    parts = conversation.conversation_parts
    rows = parts.conversation_parts or [] if parts else []
    total = parts.total_count if parts else None
    if total is not None and total < len(rows):
        raise _invalid_response(
            "Intercom conversation part count is smaller than its returned data."
        )
    if total is not None and total > len(rows):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_HISTORY_TRUNCATED,
            "Intercom exposes only the 500 most recent parts for this conversation.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if len(rows) > INTERCOM_MAX_PARTS:
        raise _invalid_response("Intercom returned more than 500 conversation parts.")
    if total is None and len(rows) == INTERCOM_MAX_PARTS:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_HISTORY_TRUNCATED,
            "Intercom may have truncated this conversation at its 500-part limit.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )


def _latest_message_part(
    conversation: native.ReplyResult,
    *,
    visibility: SupportMessageVisibility,
) -> native.Reference:
    expected = (
        native.MessageType.COMMENT
        if visibility is SupportMessageVisibility.PUBLIC
        else native.MessageType.NOTE
    )
    parts = conversation.conversation_parts
    for part in reversed(parts.conversation_parts or [] if parts else []):
        if _optional_string(part.part_type) == expected:
            return native.parse_response(
                part.model_dump(mode="json", exclude_unset=True), native.Reference
            )
    raise _invalid_response("Intercom omitted the written conversation message.")


def _webhook_identity(
    topic: str,
    item: IntercomWebhookItem | None,
) -> tuple[IntercomStream | None, str | None]:
    lowered = topic.casefold()
    if lowered.startswith(
        (IntercomWebhookTopicPrefix.CONTACT, IntercomWebhookTopicPrefix.USER)
    ):
        return IntercomStream.CONTACTS, item.id if item is not None else None
    if lowered.startswith(IntercomWebhookTopicPrefix.CONVERSATION):
        direct = None
        if isinstance(item, IntercomWebhookConversationItem):
            direct = item.conversation_id
            if direct is None and item.conversation is not None:
                direct = item.conversation.id
            if direct is None and item.type == IntercomWebhookItemType.CONVERSATION:
                direct = item.id
        return IntercomStream.CONVERSATIONS, direct
    return None, None


def _identity_segment(value: str) -> str:
    normalized = _required_id(value, field="Intercom identity segment")
    if ":" in normalized:
        raise _invalid_response("Intercom returned an ambiguous identity segment.")
    return normalized


def _expanded_id(conversation_id: str, message_id: str | None) -> str:
    value = _MessageIdentity(
        conversation_id=conversation_id,
        message_id=message_id,
    ).to_external_id()
    return _required_id(value, field="Intercom message identity")


def _message_external_id(conversation_id: str, row: _ExpandedMessage) -> str:
    return _expanded_id(conversation_id, row.message_id)


def _decode_message_identity(value: str) -> _MessageIdentity:
    parts = value.split(":")
    if len(parts) == 2 and all(parts):
        identity = _MessageIdentity(conversation_id=parts[0], message_id=parts[1])
    elif (
        len(parts) == 3
        and parts[0]
        and not parts[1]
        and parts[2] == _IdentitySegment.SOURCE
    ):
        identity = _MessageIdentity(conversation_id=parts[0], message_id=None)
    else:
        raise _invalid_command("Intercom message identity is invalid.")
    if identity.to_external_id() != value:
        raise _invalid_command("Intercom message identity is invalid.")
    return identity


def _attachment_external_id(conversation_id: str, row: _ExpandedAttachment) -> str:
    message = _MessageIdentity(
        conversation_id=conversation_id, message_id=row.message_id
    )
    identity = (
        _AttachmentIdentity(message=message, position=row.position)
        if row.attachment.id is None
        else _AttachmentIdentity(
            message=message,
            attachment_id=_required_id(
                row.attachment.id, field="Intercom attachment ID"
            ),
        )
    )
    return _required_id(identity.to_external_id(), field="Intercom attachment identity")


def _decode_attachment_identity(value: str) -> _AttachmentIdentity:
    message_value, separator, position = value.rpartition(
        f"::{_IdentitySegment.POSITION}:"
    )
    if separator:
        if not position.isascii() or not position.isdigit():
            raise _invalid_command("Intercom attachment identity is invalid.")
        identity = _AttachmentIdentity(
            message=_decode_message_identity(message_value),
            position=int(position),
        )
    else:
        message_value, separator, attachment_id = value.rpartition(":")
        if not separator or not attachment_id:
            raise _invalid_command("Intercom attachment identity is invalid.")
        identity = _AttachmentIdentity(
            message=_decode_message_identity(message_value),
            attachment_id=attachment_id,
        )
    if identity.to_external_id() != value:
        raise _invalid_command("Intercom attachment identity is invalid.")
    return identity


def _message_direction(value: str | None) -> SupportMessageDirection | None:
    author_type = _optional_string(value)
    if author_type in {
        native.ActorType.CONTACT,
        native.ActorType.LEAD,
        native.ActorType.USER,
        native.ActorType.VISITOR,
    }:
        return SupportMessageDirection.INBOUND
    if author_type in {
        native.ActorType.ADMIN,
        native.ActorType.BOT,
        native.ActorType.TEAM,
    }:
        return SupportMessageDirection.OUTBOUND
    return None


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in {"br", "div", "li", "p"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"div", "li", "p"}:
            self.parts.append("\n")


def _plain_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parser = _PlainTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception as error:
        raise _invalid_response("Intercom message body is not readable.") from error
    normalized = "\n".join(
        line.strip()
        for line in html.unescape("".join(parser.parts)).splitlines()
        if line.strip()
    )
    return normalized or None


def _request_id(response: SorJsonResponse) -> str | None:
    values = response.header_values("x-request-id") or response.header_values(
        "x-intercom-request-id"
    )
    return values[0][:512] if values else None


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.ok:
        return response.data
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_AUTHORIZATION_EXPIRED,
            f"Intercom refused authorization while attempting to {operation}.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    if response.status_code == HTTPStatus.FORBIDDEN:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_FORBIDDEN,
            f"Intercom refused permission to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code == HTTPStatus.NOT_FOUND:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESOURCE_UNAVAILABLE,
            f"Intercom could not find the resource needed to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code in {HTTPStatus.CONFLICT, HTTPStatus.UNPROCESSABLE_CONTENT}:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            f"Intercom rejected the data used to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RATE_LIMITED,
            "Intercom rate-limited the source.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SERVER_FAILED,
            f"Intercom failed while attempting to {operation}.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    raise SorVendorOperationError(
        SorVendorErrorCode.VENDOR_REQUEST_FAILED,
        f"Intercom refused the request to {operation}.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _required_string(value: object, *, field: str) -> str:
    result = _optional_string(value)
    if result is None:
        raise _invalid_response(f"{field} is missing or invalid.")
    return result


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if 1 <= len(stripped) <= 16_384 else None


def _required_id(value: object, *, field: str) -> str:
    result = _optional_id(value)
    if result is None:
        raise _invalid_response(f"{field} is missing or invalid.")
    return result


def _optional_id(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not 1 <= len(text) <= 320 or any(character in text for character in "\r\n"):
        return None
    return text


def _optional_assignee_id(value: native.Identifier | None) -> str | None:
    """Keep Intercom's unassigned sentinel out of canonical relationship targets."""
    identity = _optional_id(value)
    if identity == str(native.AssignmentSentinel.UNASSIGNED):
        return None
    return identity


def _path_id(value: str) -> str:
    normalized = _required_id(value, field="Intercom path identity")
    if any(character in normalized for character in "/\\?#%") or normalized in {
        ".",
        "..",
    }:
        raise _invalid_command("Intercom path identity is invalid.")
    return normalized


def _optional_epoch(value: object) -> int | None:
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _epoch_datetime(value: int | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise _invalid_response(
            "Intercom timestamp is outside the supported range."
        ) from error


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    epoch = _optional_epoch(value)
    if epoch is not None:
        return _epoch_datetime(epoch)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _required_datetime(value: object, *, field: str) -> datetime:
    result = _optional_datetime(value)
    if result is None:
        raise _invalid_response(f"{field} is missing or invalid.")
    return result


def _epoch_revision(value: int | None) -> str | None:
    return str(value) if value is not None else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise _invalid_response("Intercom value must be a string list.")
    return tuple(value)


def _json_value(value: object) -> SorJsonValue:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    try:
        return require_json_value(value)
    except ValueError as error:
        raise _invalid_response("Intercom value is not JSON-compatible.") from error


def _safe_source_url(value: object) -> str | None:
    url = _optional_string(value)
    if url is None or len(url) > 2_048:
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return url


def _required_target(command: SorCommandRequest) -> str:
    if command.target_external_id is None:
        raise _invalid_command("This Intercom action requires a conversation target.")
    return _required_id(
        command.target_external_id,
        field="Intercom conversation ID",
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    values = [
        value.strip() for key, value in headers.items() if key.casefold() == expected
    ]
    if len(values) != 1 or not values[0] or len(values[0]) > 4_096:
        return None
    return values[0]


def _invalid_response(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _invalid_command(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_COMMAND_INVALID,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


__all__ = [
    "INTERCOM_API_VERSION",
    "INTERCOM_MANIFEST",
    "IntercomAppWebhookDelivery",
    "IntercomSupportAdapter",
    "create_intercom_adapter",
    "parse_intercom_app_webhook",
    "verify_intercom_app_webhook",
]
