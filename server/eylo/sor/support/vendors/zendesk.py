"""Zendesk Support adapter for Eylo's canonical customer-support profile."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from enum import StrEnum
from http import HTTPMethod, HTTPStatus
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    SorOAuthSpec,
    SorOAuthTokenRequestFormat,
    SorProfile,
    SorRecordPage,
    SorRecoveryPolicy,
    SorRelationshipRole,
    SorRelationshipTargets,
    SorVendorErrorCode,
    SorVendorOperationError,
    SorVendorStreamSpec,
    SorWebhookSignal,
    SorWebhookSubscription,
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
from eylo.sor.support.vendors import zendesk_contracts as native
from eylo.sor.support.vendors.zendesk_webhooks import (
    ZENDESK_WEBHOOK_DELIVERY_HEADER,
    ZENDESK_WEBHOOK_SIGNATURE_HEADER,
    ZENDESK_WEBHOOK_TICKET_SUBJECT_PREFIX,
    ZENDESK_WEBHOOK_TIMESTAMP_HEADER,
    ZENDESK_WEBHOOK_UNSPECIFIED_EVENT,
    ZendeskWebhookCreateRequest,
    ZendeskWebhookCreateResponse,
    ZendeskWebhookDelivery,
    ZendeskWebhookDetails,
    ZendeskWebhookEvent,
    ZendeskWebhookListQuery,
    ZendeskWebhookListResponse,
    ZendeskWebhookRequestFormat,
    ZendeskWebhookSigningAlgorithm,
    ZendeskWebhookSigningResponse,
    ZendeskWebhookStatus,
    parse_zendesk_webhook_body,
    parse_zendesk_webhook_response,
)

ZENDESK_API_VERSION = "ticketing-v2"
ZENDESK_CURSOR_VERSION = 1
ZENDESK_CURSOR_MAX_LENGTH = 8_192
ZENDESK_NATIVE_CURSOR_MAX_LENGTH = 4_096
ZENDESK_WEBHOOK_TOLERANCE = timedelta(minutes=5)
ZENDESK_INITIAL_START_TIME = 1
ZENDESK_COMMENT_PAGE_SIZE = 100
ZENDESK_COMMENT_PAGE_LIMIT = 50
ZENDESK_METRIC_EXPANSION_MAX = 14  # Seven native measurements, two calendar bases.

READ_SCOPE = "read"
WRITE_SCOPE = "write"

_TICKET_WEBHOOK_EVENTS = (
    ZendeskWebhookEvent.AGENT_ASSIGNMENT_CHANGED,
    ZendeskWebhookEvent.BRAND_CHANGED,
    ZendeskWebhookEvent.CREATED,
    ZendeskWebhookEvent.CUSTOM_FIELD_CHANGED,
    ZendeskWebhookEvent.CUSTOM_STATUS_CHANGED,
    ZendeskWebhookEvent.DESCRIPTION_CHANGED,
    ZendeskWebhookEvent.EXTERNAL_ID_CHANGED,
    ZendeskWebhookEvent.FORM_CHANGED,
    ZendeskWebhookEvent.GROUP_ASSIGNMENT_CHANGED,
    ZendeskWebhookEvent.MARKED_AS_SPAM,
    ZendeskWebhookEvent.MERGED,
    ZendeskWebhookEvent.ORGANIZATION_CHANGED,
    ZendeskWebhookEvent.PERMANENTLY_DELETED,
    ZendeskWebhookEvent.PRIORITY_CHANGED,
    ZendeskWebhookEvent.PROBLEM_LINK_CHANGED,
    ZendeskWebhookEvent.REQUESTER_CHANGED,
    ZendeskWebhookEvent.SOFT_DELETED,
    ZendeskWebhookEvent.STATUS_CHANGED,
    ZendeskWebhookEvent.SUBJECT_CHANGED,
    ZendeskWebhookEvent.SUBMITTER_CHANGED,
    ZendeskWebhookEvent.TAGS_CHANGED,
    ZendeskWebhookEvent.TASK_DUE_AT_CHANGED,
    ZendeskWebhookEvent.TYPE_CHANGED,
    ZendeskWebhookEvent.UNDELETED,
)
_COMMENT_WEBHOOK_EVENTS = (
    ZendeskWebhookEvent.COMMENT_ADDED,
    ZendeskWebhookEvent.COMMENT_MADE_PRIVATE,
    ZendeskWebhookEvent.COMMENT_REDACTED,
)
_ATTACHMENT_WEBHOOK_EVENTS = (
    ZendeskWebhookEvent.ATTACHMENT_LINKED_TO_COMMENT,
    ZendeskWebhookEvent.ATTACHMENT_REDACTED_FROM_COMMENT,
)
_METRIC_WEBHOOK_EVENTS = (
    ZendeskWebhookEvent.AGENT_ASSIGNMENT_CHANGED,
    ZendeskWebhookEvent.COMMENT_ADDED,
    ZendeskWebhookEvent.GROUP_ASSIGNMENT_CHANGED,
    ZendeskWebhookEvent.NEXT_SLA_BREACH_CHANGED,
    ZendeskWebhookEvent.SCHEDULE_CHANGED,
    ZendeskWebhookEvent.SLA_POLICY_CHANGED,
    ZendeskWebhookEvent.STATUS_CHANGED,
)


class ZendeskStream(StrEnum):
    """Closed vendor stream vocabulary owned by this adapter."""

    TICKETS = "tickets"
    CUSTOMERS = "customers"
    AGENTS = "agents"
    GROUPS = "groups"
    BRANDS = "brands"
    COMMENTS = "comments"
    TAGS = "tags"
    TICKET_METRICS = "ticket_metrics"
    ATTACHMENTS = "attachments"


_STREAM_ENTITY = {
    ZendeskStream.TICKETS: SupportEntityKind.TICKET,
    ZendeskStream.CUSTOMERS: SupportEntityKind.CUSTOMER,
    ZendeskStream.AGENTS: SupportEntityKind.AGENT,
    ZendeskStream.GROUPS: SupportEntityKind.QUEUE,
    ZendeskStream.BRANDS: SupportEntityKind.INBOX,
    ZendeskStream.COMMENTS: SupportEntityKind.MESSAGE,
    ZendeskStream.TAGS: SupportEntityKind.TAG,
    ZendeskStream.TICKET_METRICS: SupportEntityKind.SLA_METRIC,
    ZendeskStream.ATTACHMENTS: SupportEntityKind.ATTACHMENT,
}
_RELATIONSHIP_TARGETS = {
    ZendeskStream.TICKETS: {
        SorRelationshipRole.REQUESTER: ZendeskStream.CUSTOMERS,
        SorRelationshipRole.ASSIGNEE: ZendeskStream.AGENTS,
        SorRelationshipRole.QUEUE: ZendeskStream.GROUPS,
        SorRelationshipRole.INBOX: ZendeskStream.BRANDS,
        SorRelationshipRole.TAG: ZendeskStream.TAGS,
    },
    ZendeskStream.COMMENTS: {SorRelationshipRole.TICKET: ZendeskStream.TICKETS},
    ZendeskStream.TICKET_METRICS: {SorRelationshipRole.TICKET: ZendeskStream.TICKETS},
    ZendeskStream.ATTACHMENTS: {
        SorRelationshipRole.TICKET: ZendeskStream.TICKETS,
        SorRelationshipRole.MESSAGE: ZendeskStream.COMMENTS,
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
    SupportToolName.FIND_CUSTOMER: frozenset({ZendeskStream.CUSTOMERS}),
    SupportToolName.FIND_TICKET: frozenset({ZendeskStream.TICKETS}),
    SupportToolName.GET_TICKET: frozenset(
        {ZendeskStream.TICKETS, ZendeskStream.COMMENTS}
    ),
    SupportToolName.GET_CUSTOMER_HISTORY: frozenset(
        {ZendeskStream.CUSTOMERS, ZendeskStream.TICKETS}
    ),
    SupportToolName.LIST_QUEUES: frozenset({ZendeskStream.GROUPS}),
    SupportToolName.DESCRIBE_TICKET_FIELDS: frozenset({ZendeskStream.TICKETS}),
    SupportToolName.OPEN_TICKET: frozenset({ZendeskStream.TICKETS}),
    SupportToolName.UPDATE_TICKET: frozenset({ZendeskStream.TICKETS}),
    SupportToolName.ASSIGN_TICKET: frozenset(
        {ZendeskStream.TICKETS, ZendeskStream.AGENTS}
    ),
    SupportToolName.REPLY: frozenset({ZendeskStream.TICKETS, ZendeskStream.COMMENTS}),
    SupportToolName.ADD_NOTE: frozenset(
        {ZendeskStream.TICKETS, ZendeskStream.COMMENTS}
    ),
    SupportToolName.CLOSE_TICKET: frozenset({ZendeskStream.TICKETS}),
    SupportToolName.ADD_TAG: frozenset({ZendeskStream.TICKETS, ZendeskStream.TAGS}),
    SupportToolName.REMOVE_TAG: frozenset({ZendeskStream.TICKETS, ZendeskStream.TAGS}),
}
_MUTATION_RESULT_STREAMS = {
    **{name: ZendeskStream.TICKETS for name in _WRITE_TOOLS},
    SupportToolName.REPLY: ZendeskStream.COMMENTS,
    SupportToolName.ADD_NOTE: ZendeskStream.COMMENTS,
}


ZENDESK_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.SUPPORT,
    vendor_key="zendesk",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                ZendeskStream.TICKETS: "Tickets",
                ZendeskStream.CUSTOMERS: "Customers",
                ZendeskStream.AGENTS: "Agents",
                ZendeskStream.GROUPS: "Groups",
                ZendeskStream.BRANDS: "Brands",
                ZendeskStream.COMMENTS: "Comments",
                ZendeskStream.TAGS: "Tags",
                ZendeskStream.TICKET_METRICS: "Ticket metrics",
                ZendeskStream.ATTACHMENTS: "Attachments",
            }[stream_key],
            description={
                ZendeskStream.TICKETS: "Zendesk tickets, ownership, status, tags, and custom fields.",
                ZendeskStream.CUSTOMERS: "Zendesk end users who request support.",
                ZendeskStream.AGENTS: "Zendesk agents and administrators who may own tickets.",
                ZendeskStream.GROUPS: "Zendesk groups used as support queues.",
                ZendeskStream.BRANDS: "Zendesk brands used as ticket inboxes.",
                ZendeskStream.COMMENTS: "Public replies and private internal notes from ticket events.",
                ZendeskStream.TAGS: "Registered and recently used Zendesk ticket tags.",
                ZendeskStream.TICKET_METRICS: "Vendor-measured reply, resolution, and wait durations.",
                ZendeskStream.ATTACHMENTS: "Metadata for files attached to ticket comments.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=(
                frozenset({SorChangeStrategy.CURSOR})
                if stream_key
                in {
                    ZendeskStream.TICKETS,
                    ZendeskStream.CUSTOMERS,
                    ZendeskStream.AGENTS,
                }
                else frozenset({SorChangeStrategy.UPDATED_AT})
                if stream_key in {ZendeskStream.COMMENTS, ZendeskStream.ATTACHMENTS}
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
        {
            SorChangeStrategy.CURSOR,
            SorChangeStrategy.UPDATED_AT,
            SorChangeStrategy.FULL_RECONCILE,
        }
    ),
    required_scopes={stream_key: (READ_SCOPE,) for stream_key in _STREAM_ENTITY},
    tool_required_scopes={name: (WRITE_SCOPE,) for name in _WRITE_TOOLS},
    tool_streams={
        tool.value: frozenset(stream.value for stream in streams)
        for tool, streams in _TOOL_STREAMS.items()
    },
    mutation_result_streams={
        tool.value: stream.value for tool, stream in _MUTATION_RESULT_STREAMS.items()
    },
    oauth=SorOAuthSpec(
        authorization_path="/oauth/authorizations/new",
        token_path="/oauth/tokens",
        base_scopes=(READ_SCOPE, WRITE_SCOPE),
        token_request_format=SorOAuthTokenRequestFormat.JSON,
        instance_host_suffixes=("zendesk.com",),
        operator_instance_origin=True,
    ),
    requires_instance_origin=True,
    change_mode=SorChangeMode.MANAGED_WEBHOOK,
    supports_custom_fields=True,
    supports_conditional_writes=True,
    supports_history=True,
    supports_comments=True,
    supports_attachments=True,
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
        group="Zendesk",
    )


_SCHEMA_FIELDS = {
    ZendeskStream.TICKETS: (
        _field("subject", "Subject", SorFieldDataType.TEXT, writable=True),
        _field(
            "normalized_description",
            "Description",
            SorFieldDataType.TEXT,
            writable=True,
        ),
        _field(
            "requester_external_id",
            "Requester ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field(
            "assignee_external_id",
            "Assignee ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field(
            "group_external_id", "Group ID", SorFieldDataType.REFERENCE, writable=True
        ),
        _field(
            "inbox_external_id", "Brand ID", SorFieldDataType.REFERENCE, writable=True
        ),
        _field("native_status", "Status", SorFieldDataType.TEXT, writable=True),
        _field("normalized_status", "Normalized status", SorFieldDataType.ENUM),
        _field("priority", "Priority", SorFieldDataType.TEXT, writable=True),
        _field("category", "Type", SorFieldDataType.TEXT, writable=True),
        _field("channel", "Channel", SorFieldDataType.TEXT),
        _field(
            "tag_external_ids", "Tags", SorFieldDataType.STRING_ARRAY, writable=True
        ),
        _field("resolved_at", "Solved at", SorFieldDataType.TIMESTAMP),
        _field("closed_at", "Closed at", SorFieldDataType.TIMESTAMP),
    ),
    ZendeskStream.CUSTOMERS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("primary_email", "Email", SorFieldDataType.TEXT),
        _field("primary_phone", "Phone", SorFieldDataType.TEXT),
        _field("company_external_id", "Organization ID", SorFieldDataType.REFERENCE),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
    ),
    ZendeskStream.AGENTS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("primary_email", "Email", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
        _field("assignable", "Assignable", SorFieldDataType.BOOLEAN),
        _field("avatar_url", "Avatar URL", SorFieldDataType.LINK),
    ),
    ZendeskStream.GROUPS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("description", "Description", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
    ),
    ZendeskStream.BRANDS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("kind", "Kind", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
    ),
    ZendeskStream.COMMENTS: (
        _field(
            "ticket_external_id",
            "Ticket ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("visibility", "Visibility", SorFieldDataType.ENUM, nullable=False),
        _field("direction", "Direction", SorFieldDataType.ENUM),
        _field("author_external_id", "Author ID", SorFieldDataType.REFERENCE),
        _field("normalized_text", "Comment", SorFieldDataType.TEXT, nullable=False),
        _field("source_body", "Source body", SorFieldDataType.BOUNDED_JSON),
        _field("body_format", "Body format", SorFieldDataType.TEXT),
        _field(
            "attachment_external_ids", "Attachment IDs", SorFieldDataType.STRING_ARRAY
        ),
        _field("created_at", "Created at", SorFieldDataType.TIMESTAMP, nullable=False),
        _field("updated_at", "Updated at", SorFieldDataType.TIMESTAMP),
    ),
    ZendeskStream.TAGS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
    ),
    ZendeskStream.TICKET_METRICS: (
        _field(
            "ticket_external_id",
            "Ticket ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("metric", "Metric", SorFieldDataType.TEXT, nullable=False),
        _field("value", "Value", SorFieldDataType.DECIMAL),
        _field("unit", "Unit", SorFieldDataType.TEXT),
        _field("native_state", "Source state", SorFieldDataType.TEXT),
        _field("normalized_state", "Normalized state", SorFieldDataType.ENUM),
        _field("target_at", "Target at", SorFieldDataType.TIMESTAMP),
        _field("achieved_at", "Achieved at", SorFieldDataType.TIMESTAMP),
        _field("breached_at", "Breached at", SorFieldDataType.TIMESTAMP),
    ),
    ZendeskStream.ATTACHMENTS: (
        _field(
            "ticket_external_id",
            "Ticket ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("message_external_id", "Comment ID", SorFieldDataType.REFERENCE),
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("content_type", "Content type", SorFieldDataType.TEXT),
        _field("size_bytes", "Size", SorFieldDataType.INTEGER),
        _field("source_url", "Content URL", SorFieldDataType.LINK),
    ),
}

_TICKET_FIELD_MAP = {
    "subject": native.ZendeskTicketWriteField.SUBJECT,
    "normalized_description": native.ZendeskTicketWriteField.DESCRIPTION,
    "requester_external_id": native.ZendeskTicketWriteField.REQUESTER_ID,
    "assignee_external_id": native.ZendeskTicketWriteField.ASSIGNEE_ID,
    "group_external_id": native.ZendeskTicketWriteField.GROUP_ID,
    "inbox_external_id": native.ZendeskTicketWriteField.BRAND_ID,
    "native_status": native.ZendeskTicketWriteField.STATUS,
    "priority": native.ZendeskTicketWriteField.PRIORITY,
    "category": native.ZendeskTicketWriteField.TYPE,
    "tag_external_ids": native.ZendeskTicketWriteField.TAGS,
}
_STATUS_MAP = {
    "new": SupportTicketState.NEW,
    "open": SupportTicketState.OPEN,
    "pending": SupportTicketState.PENDING,
    "hold": SupportTicketState.HOLD,
    "solved": SupportTicketState.RESOLVED,
    "closed": SupportTicketState.CLOSED,
}


class _ExpandedCursor(BaseModel):
    """Zendesk child offset within one native export page."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    vendor_cursor: str | None = Field(
        min_length=1, max_length=ZENDESK_NATIVE_CURSOR_MAX_LENGTH
    )
    offset: int = Field(ge=0)


class _EventCursor(BaseModel):
    """Zendesk event-export watermark and child offset."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    start_time: int = Field(ge=ZENDESK_INITIAL_START_TIME)
    offset: int = Field(ge=0)


class _CursorKind(StrEnum):
    VENDOR = "vendor"
    EXPANDED = "expanded"
    EVENT = "event"


class _CursorEnvelope(BaseModel):
    """Stored version-one cursor metadata; unknown legacy extras are ignored."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )

    version: int = Field(
        ge=ZENDESK_CURSOR_VERSION,
        le=ZENDESK_CURSOR_VERSION,
    )
    stream: ZendeskStream


class _VendorCursorEnvelope(_CursorEnvelope):
    kind: Literal[_CursorKind.VENDOR]
    vendor_cursor: str = Field(
        min_length=1, max_length=ZENDESK_NATIVE_CURSOR_MAX_LENGTH
    )


class _ExpandedCursorEnvelope(_CursorEnvelope):
    kind: Literal[_CursorKind.EXPANDED]
    vendor_cursor: str | None = Field(
        default=None, min_length=1, max_length=ZENDESK_NATIVE_CURSOR_MAX_LENGTH
    )
    offset: int = Field(ge=0)


class _EventCursorEnvelope(_CursorEnvelope):
    kind: Literal[_CursorKind.EVENT]
    start_time: int = Field(ge=ZENDESK_INITIAL_START_TIME)
    offset: int = Field(ge=0)


class ZendeskSupportAdapter:
    """Translate one exact Zendesk tenant into Eylo's support contract."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "zendesk":
            raise ValueError("Zendesk adapter requires the zendesk vendor key.")
        if context.auth_kind is not ConnectionAuthKind.OAUTH2:
            raise ValueError("Zendesk SOR requires OAuth 2.0.")
        self._context = context
        self._origin = _zendesk_origin(context.instance_origin)
        token = _credential(context.credentials, "access_token")
        self._client = SorJsonHttpClient(
            origin=self._origin,
            authorization=f"Bearer {token}",
            transport=transport,
            response_body_limit=8_388_608,
        )

    async def verify_connection(self) -> SorConnectionVerification:
        response = await self._client.request("/api/v2/users/me")
        viewer = _parse_response(
            _expect(response, operation="verify Zendesk account"),
            native.ZendeskUserResponse,
        ).user
        return SorConnectionVerification(
            account_external_id=_required_id(viewer.id, field="Zendesk user ID"),
            account_display_name=_optional_string(viewer.name) or "Zendesk account",
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=ZENDESK_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise SorVendorOperationError(
                SorVendorErrorCode.SOURCE_SELECTION_EMPTY,
                "The Zendesk source selects no streams.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        custom_fields: tuple[SorDiscoveredField, ...] = ()
        if ZendeskStream.TICKETS in self._context.selected_objects:
            response = await self._client.request("/api/v2/ticket_fields")
            data = _parse_response(
                _expect(response, operation="list Zendesk ticket fields"),
                native.ZendeskTicketFieldsResponse,
            )
            rows = (
                data.ticket_fields
                if data.ticket_fields is not None
                else data.ticket_field
            )
            if rows is None:
                raise _invalid_response("Zendesk ticket fields must be a list.")
            custom_fields = tuple(
                sorted(
                    (
                        _custom_ticket_field(row)
                        for row in rows
                        if row.removable is True
                    ),
                    key=lambda item: (item.label.casefold(), item.key),
                )
            )
        streams = {stream.key: stream for stream in ZENDESK_MANIFEST.streams}
        objects: list[SorDiscoveredObject] = []
        for stream_key in self._context.selected_objects:
            stream_key = _require_stream(
                stream_key, selected=self._context.selected_objects
            )
            fields = _SCHEMA_FIELDS[stream_key]
            if stream_key == ZendeskStream.TICKETS:
                fields = (*fields, *custom_fields)
            objects.append(
                SorDiscoveredObject(
                    key=stream_key,
                    label=streams[stream_key].label,
                    fields=fields,
                )
            )
        return SorDiscoveredSchema(
            objects=tuple(objects),
            vendor_api_version=ZENDESK_API_VERSION,
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
        record_id = _required_id(external_id, field="Zendesk record ID")
        if stream_key == ZendeskStream.TAGS:
            return self._external_record(
                ZendeskStream.TAGS, native.ZendeskTag(name=record_id)
            )
        if stream_key == ZendeskStream.COMMENTS:
            ticket_id, comment_id = _split_comment_id(record_id)
            row = await self._fetch_comment(
                ticket_id=ticket_id,
                comment_id=comment_id,
            )
            return self._external_record(
                stream_key, native.ZendeskCommentRow(ticket_id=ticket_id, comment=row)
            )
        if stream_key == ZendeskStream.ATTACHMENTS:
            ticket_id, comment_id, attachment_id = _split_attachment_id(record_id)
            response = await self._client.request(
                f"/api/v2/attachments/{_path_id(attachment_id)}"
            )
            if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            attachment = _parse_response(
                _expect(response, operation="read Zendesk attachment"),
                native.ZendeskAttachmentResponse,
            ).attachment
            return self._external_record(
                stream_key,
                native.ZendeskAttachmentRow(
                    ticket_id=ticket_id, comment_id=comment_id, attachment=attachment
                ),
            )
        if stream_key == ZendeskStream.TICKET_METRICS:
            metric_id, metric_name, basis = _split_metric_id(record_id)
            response = await self._client.request(
                f"/api/v2/ticket_metrics/{_path_id(metric_id)}"
            )
            if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            value = _parse_response(
                _expect(response, operation="read Zendesk ticket metric"),
                native.ZendeskMetricResponse,
            ).ticket_metric
            if isinstance(value, list):
                row = value[0] if value else None
            else:
                row = value
            if row is None:
                raise _invalid_response("Zendesk omitted the requested ticket metric.")
            for expanded in _expand_metric(row):
                if expanded.metric == metric_name and expanded.basis == basis:
                    return self._external_record(stream_key, expanded)
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )

        endpoint = {
            ZendeskStream.TICKETS: f"/api/v2/tickets/{_path_id(record_id)}",
            ZendeskStream.CUSTOMERS: f"/api/v2/users/{_path_id(record_id)}",
            ZendeskStream.AGENTS: f"/api/v2/users/{_path_id(record_id)}",
            ZendeskStream.GROUPS: f"/api/v2/groups/{_path_id(record_id)}",
            ZendeskStream.BRANDS: f"/api/v2/brands/{_path_id(record_id)}",
        }[stream_key]
        response = await self._client.request(endpoint)
        if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        row = _parse_exact_record(
            _expect(response, operation="read Zendesk record"), stream_key
        )
        if isinstance(row, native.ZendeskUser):
            _require_user_role(stream_key, row)
        return self._external_record(stream_key, row)

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "Zendesk deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        events = _webhook_events(self._context.selected_objects)
        if not events:
            raise SorCapabilityUnavailable(
                "The selected Zendesk objects have no exact webhook event surface."
            )
        existing = await self._recover_webhook(
            callback_url=callback_url,
            events=events,
        )
        if existing is not None:
            return existing
        response = await self._client.request(
            "/api/v2/webhooks",
            method=HTTPMethod.POST,
            payload=ZendeskWebhookCreateRequest(
                webhook=ZendeskWebhookDetails(
                    endpoint=callback_url,
                    name=_webhook_name(self._context.source_id),
                    subscriptions=events,
                ),
            ).model_dump(mode="json"),
        )
        data = parse_zendesk_webhook_response(
            _expect(response, operation="register Zendesk webhook"),
            ZendeskWebhookCreateResponse,
        )
        webhook_id = _required_id(data.webhook.id, field="Zendesk webhook ID")
        return await self._webhook_subscription(webhook_id)

    async def _recover_webhook(
        self,
        *,
        callback_url: str,
        events: tuple[ZendeskWebhookEvent, ...],
    ) -> SorWebhookSubscription | None:
        """Recover one exact source webhook after a post-vendor crash."""
        name = _webhook_name(self._context.source_id)
        response = await self._client.request(
            "/api/v2/webhooks",
            query=ZendeskWebhookListQuery(name_contains=name).model_dump(
                mode="json",
                by_alias=True,
            ),
        )
        data = parse_zendesk_webhook_response(
            _expect(response, operation="list Zendesk webhooks"),
            ZendeskWebhookListResponse,
        )
        if data.meta.has_more is True:
            raise _invalid_response(
                "Zendesk webhook recovery exceeded one bounded page."
            )
        expected_events = frozenset(events)
        exact_ids: list[str] = []
        stale_ids: list[str] = []
        for webhook in data.webhooks:
            if _optional_string(webhook.name) != name:
                continue
            webhook_id = _required_id(webhook.id, field="Zendesk webhook ID")
            subscriptions = frozenset(
                _string_list(
                    webhook.subscriptions,
                    field="Zendesk webhook subscriptions",
                )
            )
            if (
                _optional_string(webhook.endpoint) == callback_url
                and _optional_string(webhook.http_method) == HTTPMethod.POST
                and _optional_string(webhook.request_format)
                == ZendeskWebhookRequestFormat.JSON
                and _optional_string(webhook.status) == ZendeskWebhookStatus.ACTIVE
                and subscriptions == expected_events
            ):
                exact_ids.append(webhook_id)
            else:
                stale_ids.append(webhook_id)
        exact_ids.sort()
        if len(exact_ids) > 1:
            stale_ids.extend(exact_ids[1:])
        if stale_ids:
            await self._remove_webhook_ids(stale_ids)
        if not exact_ids:
            return None
        return await self._webhook_subscription(exact_ids[0])

    async def _webhook_subscription(
        self,
        webhook_id: str,
    ) -> SorWebhookSubscription:
        response = await self._client.request(
            f"/api/v2/webhooks/{_webhook_path_id(webhook_id)}/signing_secret"
        )
        data = parse_zendesk_webhook_response(
            _expect(response, operation="read Zendesk webhook signing secret"),
            ZendeskWebhookSigningResponse,
        )
        signing = data.signing_secret
        algorithm = _required_string(
            signing.algorithm,
            field="Zendesk webhook signing algorithm",
        )
        if algorithm.upper() != ZendeskWebhookSigningAlgorithm.SHA256:
            raise _invalid_response(
                "Zendesk returned an unsupported webhook signing algorithm."
            )
        return SorWebhookSubscription(
            external_id=webhook_id,
            signing_secret=_required_string(
                signing.secret,
                field="Zendesk webhook signing secret",
            ),
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        return await self._webhook_subscription(subscription.external_id)

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        await self._remove_webhook_ids((subscription.external_id,))

    async def _remove_webhook_ids(self, webhook_ids: Sequence[str]) -> None:
        for webhook_id in webhook_ids:
            response = await self._client.request(
                f"/api/v2/webhooks/{_webhook_path_id(webhook_id)}",
                method=HTTPMethod.DELETE,
            )
            if response.status_code == HTTPStatus.NOT_FOUND:
                continue
            _expect(response, operation="remove Zendesk webhook")

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        secret = self._context.webhook_signing_secret
        if secret is None or not secret:
            raise SorCapabilityUnavailable(
                "Zendesk webhook verification requires the source signing secret."
            )
        signature = _header(headers, ZENDESK_WEBHOOK_SIGNATURE_HEADER)
        timestamp_text = _header(
            headers,
            ZENDESK_WEBHOOK_TIMESTAMP_HEADER,
        )
        if signature is None or timestamp_text is None:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_WEBHOOK_UNSIGNED,
                "Zendesk webhook signature headers are missing.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        timestamp = _webhook_timestamp(timestamp_text)
        now = datetime.now(timezone.utc)
        if abs(now - timestamp) > ZENDESK_WEBHOOK_TOLERANCE:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_WEBHOOK_STALE,
                "Zendesk webhook timestamp is outside the replay window.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        expected = base64.b64encode(
            hmac.new(
                secret.encode(),
                timestamp_text.encode() + body,
                hashlib.sha256,
            ).digest()
        ).decode()
        if not hmac.compare_digest(signature, expected):
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_WEBHOOK_INVALID,
                "Zendesk webhook signature is invalid.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        data = parse_zendesk_webhook_body(body)
        subject = _optional_string(data.subject)
        ticket_id = _ticket_id_from_subject(subject)
        if ticket_id is None:
            if data.detail is not None:
                ticket_id = _optional_id(data.detail.id)
        if ticket_id is None:
            return ()
        return _webhook_signals(
            data=data,
            headers=headers,
            selected_objects=self._context.selected_objects,
            ticket_id=ticket_id,
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_TOOL_UNSUPPORTED,
                "This Zendesk adapter does not execute the requested support action.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if command.tool_name == SupportToolName.OPEN_TICKET:
            return await self._open_ticket(command)
        ticket_id = _required_target(command)
        if command.tool_name == SupportToolName.UPDATE_TICKET:
            return await self._update_ticket(ticket_id, command)
        if command.tool_name == SupportToolName.ASSIGN_TICKET:
            return await self._assign_ticket(ticket_id, command)
        if command.tool_name in {SupportToolName.REPLY, SupportToolName.ADD_NOTE}:
            return await self._add_comment(
                ticket_id,
                command,
                visibility=(
                    SupportMessageVisibility.PUBLIC
                    if command.tool_name == SupportToolName.REPLY
                    else SupportMessageVisibility.PRIVATE
                ),
            )
        if command.tool_name == SupportToolName.CLOSE_TICKET:
            return await self._close_ticket(ticket_id, command)
        return await self._change_tag(
            ticket_id,
            command,
            action=native.ZendeskTagAction.ADD
            if command.tool_name == SupportToolName.ADD_TAG
            else native.ZendeskTagAction.REMOVE,
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
            name=_required_string(payload.name, field="Zendesk Agent name"),
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
                payload.ticket_external_id,
                field="Zendesk comment ticket ID",
            ),
            visibility=payload.visibility,
            direction=payload.direction,
            author_external_id=_optional_string(payload.author_external_id),
            normalized_text=_required_string(
                payload.normalized_text,
                field="Zendesk comment body",
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
            name=_required_string(payload.name, field="Zendesk group name"),
            description=_optional_string(payload.description),
            active=payload.active,
        )

    def normalize_inbox(
        self,
        record: SorExternalRecord,
        payload: SupportInboxPayload,
    ) -> SupportInbox:
        return SupportInbox(
            external_id=record.external_id,
            name=_required_string(payload.name, field="Zendesk brand name"),
            kind=_optional_string(payload.kind),
            active=payload.active,
        )

    def normalize_tag(
        self,
        record: SorExternalRecord,
        payload: SupportTagPayload,
    ) -> SupportTag:
        return SupportTag(
            external_id=record.external_id,
            name=_required_string(payload.name, field="Zendesk tag name"),
        )

    def normalize_sla_metric(
        self,
        record: SorExternalRecord,
        payload: SupportSlaMetricPayload,
    ) -> SupportSlaMetric:
        return SupportSlaMetric(
            external_id=record.external_id,
            ticket_external_id=_required_string(
                payload.ticket_external_id,
                field="Zendesk metric ticket ID",
            ),
            metric=_required_string(
                payload.metric,
                field="Zendesk metric name",
            ),
            value=payload.value,
            unit=_optional_string(payload.unit),
            native_state=_optional_string(payload.native_state),
            normalized_state=payload.normalized_state,
            target_at=payload.target_at,
            achieved_at=payload.achieved_at,
            breached_at=payload.breached_at,
        )

    def normalize_attachment(
        self,
        record: SorExternalRecord,
        payload: SupportAttachmentPayload,
    ) -> SupportAttachment:
        return SupportAttachment(
            external_id=record.external_id,
            ticket_external_id=_required_string(
                payload.ticket_external_id,
                field="Zendesk attachment ticket ID",
            ),
            message_external_id=_optional_string(payload.message_external_id),
            name=_required_string(
                payload.name,
                field="Zendesk attachment name",
            ),
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
                "Zendesk page limit must be positive.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if stream_key == ZendeskStream.TICKETS:
            return await self._read_cursor_export(
                stream_key=stream_key,
                cursor=cursor,
                limit=min(limit, native.ZENDESK_EXPORT_PAGE_SIZE),
            )
        if stream_key in {ZendeskStream.CUSTOMERS, ZendeskStream.AGENTS}:
            return await self._read_cursor_export(
                stream_key=stream_key,
                cursor=cursor,
                limit=min(limit, native.ZENDESK_EXPORT_PAGE_SIZE),
            )
        if stream_key in {ZendeskStream.COMMENTS, ZendeskStream.ATTACHMENTS}:
            return await self._read_event_stream(
                stream_key=stream_key,
                cursor=cursor,
                limit=limit,
            )
        return await self._read_reconcile_page(
            stream_key=stream_key,
            cursor=cursor,
            limit=limit,
        )

    async def _read_cursor_export(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        vendor_cursor = _decode_vendor_cursor(cursor, stream_key=stream_key)
        path = (
            "/api/v2/incremental/tickets/cursor"
            if stream_key == ZendeskStream.TICKETS
            else "/api/v2/incremental/users/cursor"
        )
        query = (
            native.ZendeskExportQuery(
                per_page=limit, start_time=ZENDESK_INITIAL_START_TIME
            )
            if vendor_cursor is None
            else native.ZendeskExportQuery(per_page=limit, cursor=vendor_cursor)
        )
        if stream_key == ZendeskStream.TICKETS:
            query = native.ZendeskExportQuery.model_validate(
                {
                    **query.model_dump(exclude_unset=True),
                    "exclude_deleted": True,
                    "support_type_scope": native.ZendeskSupportTypeScope.ALL,
                }
            )
        response = await self._client.request(
            path, query=query.model_dump(mode="json", exclude_unset=True)
        )
        value = _expect(response, operation=f"export Zendesk {stream_key}")
        data = (
            _parse_response(value, native.ZendeskTicketExport)
            if stream_key == ZendeskStream.TICKETS
            else _parse_response(value, native.ZendeskUserExport)
        )
        response_rows: Sequence[native.ZendeskTicket | native.ZendeskUser] = (
            data.tickets if isinstance(data, native.ZendeskTicketExport) else data.users
        )
        if len(response_rows) > limit:
            raise _invalid_response(
                f"Zendesk returned more {stream_key} than the requested page limit."
            )
        rows = [
            row
            for row in response_rows
            if not isinstance(row, native.ZendeskUser)
            or _user_matches_stream(stream_key, row)
        ]
        end_of_stream = data.end_of_stream
        raw_after_cursor = data.after_cursor
        if (
            raw_after_cursor is None
            and end_of_stream
            and not response_rows
            and vendor_cursor is not None
        ):
            after_cursor = vendor_cursor
        else:
            after_cursor = _required_string(
                raw_after_cursor,
                field=f"Zendesk {stream_key} after_cursor",
            )
        return SorRecordPage(
            records=tuple(self._external_record(stream_key, row) for row in rows),
            next_cursor=_encode_vendor_cursor(
                stream_key=stream_key,
                vendor_cursor=after_cursor,
            ),
            has_more=not end_of_stream,
        )

    async def _read_event_stream(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_event_cursor(cursor, stream_key=stream_key)
        response = await self._client.request(
            "/api/v2/incremental/ticket_events",
            query=native.ZendeskEventQuery(
                include=native.ZendeskInclude.COMMENT_EVENTS,
                per_page=min(max(limit, 1), native.ZENDESK_EXPORT_PAGE_SIZE),
                start_time=checkpoint.start_time,
                support_type_scope=native.ZendeskSupportTypeScope.ALL,
            ).model_dump(mode="json"),
        )
        data = _parse_response(
            _expect(response, operation="export Zendesk ticket comment events"),
            native.ZendeskEventExport,
        )
        expanded = _expand_event_records(data.ticket_events, stream_key=stream_key)
        if checkpoint.offset > len(expanded):
            raise _invalid_response("Zendesk event cursor exceeds its source page.")
        records = expanded[checkpoint.offset : checkpoint.offset + limit]
        consumed = checkpoint.offset + len(records)
        end_time = data.end_time
        end_of_stream = data.end_of_stream
        if consumed < len(expanded):
            next_checkpoint = _EventCursor(
                start_time=checkpoint.start_time,
                offset=consumed,
            )
            has_more = True
        else:
            if not end_of_stream and end_time <= checkpoint.start_time:
                raise _invalid_response("Zendesk ticket event cursor did not advance.")
            next_checkpoint = _EventCursor(start_time=end_time, offset=0)
            has_more = not end_of_stream
        return SorRecordPage(
            records=tuple(self._external_record(stream_key, row) for row in records),
            next_cursor=_encode_event_cursor(
                next_checkpoint,
                stream_key=stream_key,
            ),
            has_more=has_more,
        )

    async def _read_reconcile_page(
        self,
        *,
        stream_key: ZendeskStream,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_expanded_cursor(cursor, stream_key=stream_key)
        vendor_limit = min(limit, native.ZENDESK_LIST_PAGE_SIZE)
        if stream_key == ZendeskStream.TICKET_METRICS:
            vendor_limit = max(
                1,
                min(
                    native.ZENDESK_LIST_PAGE_SIZE, limit // ZENDESK_METRIC_EXPANSION_MAX
                ),
            )
        endpoint = {
            ZendeskStream.GROUPS: "/api/v2/groups",
            ZendeskStream.BRANDS: "/api/v2/brands",
            ZendeskStream.TAGS: "/api/v2/tags",
            ZendeskStream.TICKET_METRICS: "/api/v2/ticket_metrics",
        }[stream_key]
        query = native.ZendeskPageQuery(
            size=vendor_limit, after=checkpoint.vendor_cursor
        )
        response = await self._client.request(
            endpoint,
            query=query.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        expanded, meta = _parse_reconcile_records(
            _expect(response, operation=f"list Zendesk {stream_key}"), stream_key
        )
        if checkpoint.offset > len(expanded):
            raise _invalid_response("Zendesk reconcile cursor exceeds its source page.")
        selected = expanded[checkpoint.offset : checkpoint.offset + limit]
        consumed = checkpoint.offset + len(selected)
        vendor_has_more, next_vendor_cursor = _cursor_page(meta)
        if consumed < len(expanded):
            next_checkpoint = _ExpandedCursor(
                vendor_cursor=checkpoint.vendor_cursor,
                offset=consumed,
            )
            has_more = True
        elif vendor_has_more:
            if next_vendor_cursor is None:
                raise _invalid_response("Zendesk omitted its next page cursor.")
            next_checkpoint = _ExpandedCursor(
                vendor_cursor=next_vendor_cursor,
                offset=0,
            )
            has_more = True
        else:
            next_checkpoint = None
            has_more = False
        return SorRecordPage(
            records=tuple(self._external_record(stream_key, row) for row in selected),
            next_cursor=(
                _encode_expanded_cursor(next_checkpoint, stream_key=stream_key)
                if next_checkpoint is not None
                else None
            ),
            has_more=has_more,
        )

    async def _fetch_comment(
        self,
        *,
        ticket_id: str,
        comment_id: str,
    ) -> native.ZendeskComment:
        """Find one comment through Zendesk's list-only ticket comment API."""
        after_cursor: str | None = None
        for _page_number in range(ZENDESK_COMMENT_PAGE_LIMIT):
            query = native.ZendeskPageQuery(
                size=ZENDESK_COMMENT_PAGE_SIZE,
                sort=native.ZendeskSort.CREATED_DESCENDING,
                after=after_cursor,
            )
            response = await self._client.request(
                f"/api/v2/tickets/{_path_id(ticket_id)}/comments",
                query=query.model_dump(mode="json", by_alias=True, exclude_none=True),
            )
            if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
                break
            data = _parse_response(
                _expect(response, operation="list Zendesk comments"),
                native.ZendeskCommentsPage,
            )
            rows = data.comments
            match = next(
                (
                    row
                    for row in rows
                    if _required_id(row.id, field="Zendesk comment ID") == comment_id
                ),
                None,
            )
            if match is not None:
                return match
            has_more, next_cursor = _cursor_page(data.meta)
            if not has_more:
                break
            if next_cursor is None or next_cursor == after_cursor:
                raise _invalid_response("Zendesk comment cursor did not advance.")
            after_cursor = next_cursor
        raise SorExternalRecordNotFound(
            vendor_object_key=ZendeskStream.COMMENTS,
            external_id=_comment_external_id(ticket_id, comment_id),
        )

    def _external_record(
        self,
        stream_key: str,
        row: native.ZendeskReadRecord,
    ) -> SorExternalRecord:
        if isinstance(row, native.ZendeskTicket):
            record_id = _required_id(row.id, field="Zendesk ticket ID")
            updated_at = _optional_datetime(row.updated_at)
            status = _optional_string(row.status)
            channel = _optional_string(row.via.channel) if row.via else None
            payload: dict[str, object] = {
                "subject": row.subject,
                "normalized_description": row.description,
                "requester_external_id": _optional_id(row.requester_id),
                "assignee_external_id": _optional_id(row.assignee_id),
                "group_external_id": _optional_id(row.group_id),
                "inbox_external_id": _optional_id(row.brand_id),
                "native_status": status,
                "normalized_status": _STATUS_MAP.get(status or ""),
                "priority": row.priority,
                "category": row.type,
                "channel": channel,
                "tag_external_ids": row.tags,
                "first_response_at": None,
                "resolved_at": row.solved_at,
                "closed_at": row.closed_at,
                "sla_state": None,
            }
            payload.update(_custom_field_values(row.custom_fields))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload=payload,
                source_created_at=_optional_datetime(row.created_at),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=f"{self._origin}/agent/tickets/{record_id}",
            )
        if isinstance(row, native.ZendeskUser):
            record_id = _required_id(row.id, field="Zendesk user ID")
            updated_at = _optional_datetime(row.updated_at)
            avatar_url = _safe_source_url(row.photo.content_url) if row.photo else None
            role = _optional_string(row.role)
            suspended = row.suspended is True
            payload = {
                "name": row.name,
                "primary_email": row.email,
                "primary_phone": row.phone,
                "company_external_id": _optional_id(row.organization_id),
                "active": row.active is not False and not suspended,
                "assignable": role
                in {native.ZendeskUserRole.AGENT, native.ZendeskUserRole.ADMIN}
                and not suspended,
                "avatar_url": avatar_url,
            }
            user_fields = row.user_fields
            if isinstance(user_fields, Mapping):
                payload.update(
                    {
                        f"user_field_{key}": _json_value(value)
                        for key, value in user_fields.items()
                        if isinstance(key, str) and key
                    }
                )
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload=payload,
                source_created_at=_optional_datetime(row.created_at),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=f"{self._origin}/agent/users/{record_id}/tickets",
            )
        if isinstance(row, native.ZendeskGroup):
            record_id = _required_id(row.id, field="Zendesk group ID")
            updated_at = _optional_datetime(row.updated_at)
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload={
                    "name": row.name,
                    "description": row.description,
                    "active": row.deleted is not True,
                },
                source_created_at=_optional_datetime(row.created_at),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=_safe_source_url(row.url),
            )
        if isinstance(row, native.ZendeskBrand):
            record_id = _required_id(row.id, field="Zendesk brand ID")
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload={
                    "name": row.name,
                    "kind": "brand",
                    "active": row.active,
                },
                source_created_at=_optional_datetime(row.created_at),
                source_updated_at=_optional_datetime(row.updated_at),
                source_revision=_revision(_optional_datetime(row.updated_at)),
                source_url=_safe_source_url(row.url),
            )
        if isinstance(row, native.ZendeskCommentRow):
            ticket_id = row.ticket_id
            comment = row.comment
            comment_id = _required_id(comment.id, field="Zendesk comment ID")
            created_at = _required_datetime(
                comment.created_at,
                field="Zendesk comment creation time",
            )
            attachment_ids = tuple(
                _attachment_external_id(ticket_id, comment_id, attachment)
                for attachment in comment.attachments or []
            )
            source_body = comment.html_body or comment.body
            author_external_id = _optional_id(comment.author_id)
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_comment_external_id(ticket_id, comment_id),
                payload={
                    "ticket_external_id": ticket_id,
                    "visibility": SupportMessageVisibility.PUBLIC
                    if comment.public is True
                    else SupportMessageVisibility.PRIVATE,
                    # Zendesk reserves -1 for its system actor, including
                    # automation actions. All person direction remains unknown
                    # until it can be resolved from canonical Support records.
                    # https://developer.zendesk.com/api-reference/ticketing/tickets/activity_stream/#json-format
                    "direction": (
                        SupportMessageDirection.SYSTEM
                        if author_external_id == native.ZENDESK_SYSTEM_ACTOR_ID
                        else SupportMessageDirection.UNKNOWN
                    ),
                    "author_external_id": author_external_id,
                    "normalized_text": comment.plain_body or comment.body,
                    "source_body": _json_value(source_body),
                    "body_format": "html" if comment.html_body else "text",
                    "attachment_external_ids": attachment_ids,
                    "created_at": created_at,
                    "updated_at": comment.updated_at,
                },
                source_created_at=created_at,
                source_updated_at=_optional_datetime(comment.updated_at),
                source_revision=_revision(
                    _optional_datetime(comment.updated_at) or created_at
                ),
                source_url=f"{self._origin}/agent/tickets/{ticket_id}",
            )
        if isinstance(row, native.ZendeskTag):
            name = _required_string(row.name, field="Zendesk tag name")
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=name,
                payload={"name": name},
            )
        if isinstance(row, native.ZendeskMetricRow):
            source = row.source
            metric_id = _required_id(source.id, field="Zendesk ticket metric ID")
            metric = row.metric
            basis = row.basis
            updated_at = _optional_datetime(source.updated_at)
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_metric_external_id(metric_id, metric, basis),
                payload={
                    "ticket_external_id": _required_id(
                        source.ticket_id,
                        field="Zendesk metric ticket ID",
                    ),
                    "metric": f"{metric}:{basis}",
                    "value": row.value,
                    "unit": row.unit,
                    "native_state": None,
                    "normalized_state": None,
                    "target_at": None,
                    "achieved_at": source.solved_at,
                    "breached_at": None,
                },
                source_created_at=_optional_datetime(source.created_at),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=_safe_source_url(source.url),
            )
        ticket_id = row.ticket_id
        comment_id = row.comment_id
        attachment = row.attachment
        attachment_id = _required_id(attachment.id, field="Zendesk attachment ID")
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=_attachment_id(ticket_id, comment_id, attachment_id),
            payload={
                "ticket_external_id": ticket_id,
                "message_external_id": _comment_external_id(ticket_id, comment_id),
                "name": attachment.file_name or attachment.name,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size,
                "source_url": _safe_source_url(attachment.content_url),
            },
            source_url=_safe_source_url(attachment.content_url),
        )

    async def _open_ticket(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command(
                "Opening a support ticket cannot target an existing ticket."
            )
        if not isinstance(command.payload, SupportMappedFieldsCommandPayload):
            raise _invalid_command("Zendesk ticket fields payload is invalid.")
        fields = self._ticket_write_values(command.payload.fields)
        description = fields.description
        if not isinstance(description, str) or not description.strip():
            raise _invalid_command(
                "Opening a Zendesk ticket requires normalized_description for its initial comment."
            )
        fields = _parse_write(
            {
                **fields.model_dump(
                    exclude_unset=True,
                    exclude={native.ZendeskTicketWriteField.DESCRIPTION.value},
                ),
                "comment": native.ZendeskCommentInput(
                    body=description.strip(), public=True
                ),
            },
            native.ZendeskTicketFields,
        )
        response = await self._mutation_request(
            "/api/v2/tickets",
            method="POST",
            payload=native.ZendeskTicketRequest(ticket=fields),
            command=command,
            operation="open a Zendesk ticket",
        )
        ticket = _parse_response(
            _expect(response, operation="open a Zendesk ticket"),
            native.ZendeskTicketResponse,
        ).ticket
        return self._ticket_result(ticket, response=response)

    async def _update_ticket(
        self,
        ticket_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportMappedFieldsCommandPayload):
            raise _invalid_command("Zendesk ticket fields payload is invalid.")
        fields = self._ticket_write_values(command.payload.fields)
        if not fields.model_fields_set:
            raise _invalid_command("Updating a Zendesk ticket requires mapped fields.")
        fields = _with_revision(fields, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}",
            method="PUT",
            payload=native.ZendeskTicketRequest(ticket=fields),
            command=command,
            operation="update a Zendesk ticket",
        )
        ticket = _parse_response(
            _expect(response, operation="update a Zendesk ticket"),
            native.ZendeskTicketResponse,
        ).ticket
        return self._ticket_result(ticket, response=response)

    async def _assign_ticket(
        self,
        ticket_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportAssignCommandPayload):
            raise _invalid_command("Zendesk assignment payload is invalid.")
        values: dict[str, object] = {}
        if command.payload.assignee_external_id is not None:
            values[native.ZendeskTicketWriteField.ASSIGNEE_ID] = _required_id(
                command.payload.assignee_external_id,
                field="Zendesk assignee ID",
            )
        if command.payload.group_external_id is not None:
            values[native.ZendeskTicketWriteField.GROUP_ID] = _required_id(
                command.payload.group_external_id,
                field="Zendesk group ID",
            )
        fields = _with_revision(
            _parse_write(values, native.ZendeskTicketFields),
            command.expected_source_revision,
        )
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}",
            method="PUT",
            payload=native.ZendeskTicketRequest(ticket=fields),
            command=command,
            operation="assign a Zendesk ticket",
        )
        ticket = _parse_response(
            _expect(response, operation="assign a Zendesk ticket"),
            native.ZendeskTicketResponse,
        ).ticket
        return self._ticket_result(ticket, response=response)

    async def _add_comment(
        self,
        ticket_id: str,
        command: SorCommandRequest,
        *,
        visibility: SupportMessageVisibility,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportMessageCommandPayload):
            raise _invalid_command("Zendesk message payload is invalid.")
        text = command.payload.normalized_text
        fields = _with_revision(
            native.ZendeskTicketFields(
                comment=native.ZendeskCommentInput(
                    body=text, public=visibility is SupportMessageVisibility.PUBLIC
                )
            ),
            command.expected_source_revision,
        )
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}",
            method="PUT",
            payload=native.ZendeskTicketRequest(ticket=fields),
            command=command,
            operation=(
                "reply to a Zendesk ticket"
                if visibility is SupportMessageVisibility.PUBLIC
                else "add a Zendesk private note"
            ),
        )
        audit = _parse_response(
            _expect(response, operation="add a Zendesk comment"),
            native.ZendeskCommentResponse,
        ).audit
        comment = _audit_comment(audit, visibility=visibility)
        comment_id = _required_id(comment.id, field="Zendesk comment ID")
        return SorCommandResult(
            vendor_object_key=ZendeskStream.COMMENTS,
            external_id=_comment_external_id(ticket_id, comment_id),
            external_request_id=_request_id(response),
            source_url=f"{self._origin}/agent/tickets/{ticket_id}",
            response={
                "status": "accepted",
                "visibility": visibility.value,
            },
        )

    async def _close_ticket(
        self,
        ticket_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if (
            not isinstance(command.payload, SupportCloseCommandPayload)
            or command.payload.normalized_text is not None
        ):
            raise _invalid_command("Zendesk close payload is invalid.")
        status = command.payload.native_status or native.ZendeskTicketStatus.SOLVED
        if status not in {
            native.ZendeskTicketStatus.SOLVED,
            native.ZendeskTicketStatus.CLOSED,
        }:
            raise _invalid_command("Zendesk close status must be solved or closed.")
        fields = _with_revision(
            native.ZendeskTicketFields(status=native.ZendeskTicketStatus(status)),
            command.expected_source_revision,
        )
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}",
            method="PUT",
            payload=native.ZendeskTicketRequest(ticket=fields),
            command=command,
            operation="close a Zendesk ticket",
        )
        ticket = _parse_response(
            _expect(response, operation="close a Zendesk ticket"),
            native.ZendeskTicketResponse,
        ).ticket
        return self._ticket_result(ticket, response=response)

    async def _change_tag(
        self,
        ticket_id: str,
        command: SorCommandRequest,
        *,
        action: native.ZendeskTagAction,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportTagCommandPayload):
            raise _invalid_command("Zendesk tag payload is invalid.")
        tag = command.payload.tag_external_id
        payload = _with_revision(
            native.ZendeskTagsRequest(tags=[tag]), command.expected_source_revision
        )
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}/tags",
            method=HTTPMethod.PUT
            if action is native.ZendeskTagAction.ADD
            else HTTPMethod.DELETE,
            payload=payload,
            command=command,
            operation="change a Zendesk ticket tag",
        )
        _expect(response, operation="change a Zendesk ticket tag")
        return SorCommandResult(
            vendor_object_key=ZendeskStream.TICKETS,
            external_id=ticket_id,
            external_request_id=_request_id(response),
            source_url=f"{self._origin}/agent/tickets/{ticket_id}",
            response={"status": "accepted"},
        )

    def _ticket_write_values(
        self, payload: Mapping[str, object]
    ) -> native.ZendeskTicketFields:
        writable = {
            field.agent_key: field.vendor_field_key
            for field in self._context.fields
            if field.vendor_object_key == ZendeskStream.TICKETS and field.writable
        }
        if not payload:
            raise _invalid_command("A Zendesk ticket mutation requires mapped fields.")
        unknown = set(payload) - set(writable)
        if unknown:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_FIELD_NOT_WRITABLE,
                "The Zendesk mutation contains fields absent from the writable mapping.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        fields: dict[str, object] = {}
        custom_fields: list[native.ZendeskCustomFieldInput] = []
        for agent_key, value in payload.items():
            vendor_key = writable[agent_key]
            if vendor_key.startswith("custom_field_"):
                custom_fields.append(
                    _parse_write(
                        {
                            "id": _required_id(
                                vendor_key.removeprefix("custom_field_"),
                                field="Zendesk custom field ID",
                            ),
                            "value": value,
                        },
                        native.ZendeskCustomFieldInput,
                    )
                )
                continue
            source_key = _TICKET_FIELD_MAP.get(vendor_key)
            if source_key is None:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_FIELD_NOT_WRITABLE,
                    "The mapped Zendesk field is not writable by this adapter.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                )
            fields[source_key] = value
        if custom_fields:
            fields[native.ZendeskTicketWriteField.CUSTOM_FIELDS] = custom_fields
        return _parse_write(fields, native.ZendeskTicketFields)

    async def _mutation_request(
        self,
        path: str,
        *,
        method: str,
        payload: native.ZendeskWriteInput,
        command: SorCommandRequest,
        operation: str,
    ) -> SorJsonResponse:
        try:
            response = await self._client.request(
                path,
                method=method,
                payload=payload.model_dump(mode="json", exclude_unset=True),
                idempotency_key=command.idempotency_key,
            )
            if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
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
                    "Zendesk may have applied the action; reconcile before retrying.",
                    recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
                ) from error
            raise

    def _ticket_result(
        self,
        ticket: native.ZendeskTicketResult,
        *,
        response: SorJsonResponse,
    ) -> SorCommandResult:
        ticket_id = _required_id(ticket.id, field="Zendesk ticket ID")
        updated_at = _optional_datetime(ticket.updated_at)
        return SorCommandResult(
            vendor_object_key=ZendeskStream.TICKETS,
            external_id=ticket_id,
            external_request_id=_request_id(response),
            source_revision=_revision(updated_at),
            source_url=f"{self._origin}/agent/tickets/{ticket_id}",
            response={"status": "accepted"},
        )


def create_zendesk_adapter(context: SorAdapterContext) -> ZendeskSupportAdapter:
    """Construct the production Zendesk adapter for the explicit registry."""
    return ZendeskSupportAdapter(context)


def _zendesk_origin(value: str | None) -> str:
    if value is None:
        raise ValueError("Zendesk requires an instance origin.")
    parsed = urlsplit(value.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(
            "Zendesk instance origin must be an exact https://<subdomain>.zendesk.com origin."
        ) from error
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".zendesk.com")
        or hostname == "zendesk.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Zendesk instance origin must be an exact https://<subdomain>.zendesk.com origin."
        )
    return f"https://{hostname}"


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CONFIGURATION_INVALID,
            "Zendesk access token is missing.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    return value.strip()


def _require_stream(stream_key: str, *, selected: Sequence[str]) -> ZendeskStream:
    if stream_key not in _STREAM_ENTITY:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNSUPPORTED,
            "This Zendesk adapter does not recognize the requested stream.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if stream_key not in selected:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNAVAILABLE,
            "The requested Zendesk stream is not selected for this source.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return ZendeskStream(stream_key)


def _custom_ticket_field(row: native.ZendeskTicketField) -> SorDiscoveredField:
    field_id = _required_id(row.id, field="Zendesk ticket field ID")
    options = row.custom_field_options
    choices: tuple[str, ...] = ()
    if isinstance(options, list):
        choices = tuple(
            value
            for item in options
            if (value := _optional_string(item.value)) is not None
        )
    return SorDiscoveredField(
        key=f"custom_field_{field_id}",
        label=_optional_string(row.title) or f"Custom field {field_id}",
        data_type=_zendesk_field_type(row.type),
        nullable=row.required is not True,
        writable=row.agent_can_edit is True,
        choices=choices,
        description=(
            _optional_string(row.agent_description) or _optional_string(row.description)
        ),
        group="Zendesk custom fields",
    )


def _zendesk_field_type(value: object) -> SorFieldDataType:
    return {
        "checkbox": SorFieldDataType.BOOLEAN,
        "date": SorFieldDataType.DATE,
        "decimal": SorFieldDataType.DECIMAL,
        "integer": SorFieldDataType.INTEGER,
        "lookup": SorFieldDataType.REFERENCE,
        "multiselect": SorFieldDataType.STRING_ARRAY,
        "regexp": SorFieldDataType.TEXT,
        "tagger": SorFieldDataType.ENUM,
        "textarea": SorFieldDataType.TEXT,
        "text": SorFieldDataType.TEXT,
    }.get(_optional_string(value) or "", SorFieldDataType.JSON)


def _custom_field_values(
    value: Sequence[native.ZendeskCustomFieldValue] | None,
) -> dict[str, object]:
    values: dict[str, object] = {}
    for item in value or []:
        field_id = _required_id(item.id, field="Zendesk custom field ID")
        values[f"custom_field_{field_id}"] = item.value
    return values


def _encode_vendor_cursor(*, stream_key: str, vendor_cursor: str) -> str:
    return _encode_cursor(
        _VendorCursorEnvelope(
            version=ZENDESK_CURSOR_VERSION,
            kind=_CursorKind.VENDOR,
            stream=ZendeskStream(stream_key),
            vendor_cursor=vendor_cursor,
        )
    )


def _decode_vendor_cursor(cursor: str | None, *, stream_key: str) -> str | None:
    if cursor is None:
        return None
    return _decode_cursor(
        cursor, stream_key=stream_key, model=_VendorCursorEnvelope
    ).vendor_cursor


def _encode_expanded_cursor(cursor: _ExpandedCursor, *, stream_key: str) -> str:
    return _encode_cursor(
        _ExpandedCursorEnvelope(
            version=ZENDESK_CURSOR_VERSION,
            kind=_CursorKind.EXPANDED,
            stream=ZendeskStream(stream_key),
            vendor_cursor=cursor.vendor_cursor,
            offset=cursor.offset,
        )
    )


def _decode_expanded_cursor(cursor: str | None, *, stream_key: str) -> _ExpandedCursor:
    if cursor is None:
        return _ExpandedCursor(vendor_cursor=None, offset=0)
    parsed = _decode_cursor(
        cursor, stream_key=stream_key, model=_ExpandedCursorEnvelope
    )
    return _ExpandedCursor(vendor_cursor=parsed.vendor_cursor, offset=parsed.offset)


def _encode_event_cursor(cursor: _EventCursor, *, stream_key: str) -> str:
    return _encode_cursor(
        _EventCursorEnvelope(
            version=ZENDESK_CURSOR_VERSION,
            kind=_CursorKind.EVENT,
            stream=ZendeskStream(stream_key),
            start_time=cursor.start_time,
            offset=cursor.offset,
        )
    )


def _decode_event_cursor(cursor: str | None, *, stream_key: str) -> _EventCursor:
    if cursor is None:
        return _EventCursor(start_time=ZENDESK_INITIAL_START_TIME, offset=0)
    parsed = _decode_cursor(cursor, stream_key=stream_key, model=_EventCursorEnvelope)
    return _EventCursor(start_time=parsed.start_time, offset=parsed.offset)


def _encode_cursor(payload: _CursorEnvelope) -> str:
    # Keep byte-for-byte stable encoding for saved version-one checkpoints.
    raw = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor[CursorT: _CursorEnvelope](
    cursor: str, *, stream_key: str, model: type[CursorT]
) -> CursorT:
    if not cursor or len(cursor) > ZENDESK_CURSOR_MAX_LENGTH:
        raise _invalid_cursor("Zendesk cursor is invalid.")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        parsed = model.model_validate_json(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise _invalid_cursor("Zendesk cursor is invalid.") from error
    if parsed.stream != stream_key:
        raise _invalid_cursor("Zendesk cursor does not match this stream.")
    return parsed


def _cursor_page(meta: native.ZendeskPageMeta) -> tuple[bool, str | None]:
    return meta.has_more, _optional_string(meta.after_cursor)


def _expand_event_records(
    events: Sequence[native.ZendeskTicketEvent],
    *,
    stream_key: str,
) -> list[native.ZendeskCommentRow | native.ZendeskAttachmentRow]:
    records: list[native.ZendeskCommentRow | native.ZendeskAttachmentRow] = []
    for event in events:
        ticket_id = _required_id(
            event.ticket_id,
            field="Zendesk ticket event ticket ID",
        )
        children = event.child_events or []
        for child in children:
            event_type = _optional_string(child.event_type) or _optional_string(
                child.type
            )
            if event_type != native.ZendeskAuditEventKind.COMMENT:
                continue
            comment = _parse_response(
                child.model_dump(exclude_unset=True), native.ZendeskComment
            )
            if stream_key == ZendeskStream.COMMENTS:
                records.append(
                    native.ZendeskCommentRow(ticket_id=ticket_id, comment=comment)
                )
                continue
            comment_id = _required_id(
                child.id,
                field="Zendesk comment ID",
            )
            for attachment in child.attachments or []:
                records.append(
                    native.ZendeskAttachmentRow(
                        ticket_id=ticket_id,
                        comment_id=comment_id,
                        attachment=attachment,
                    )
                )
    return records


def _expand_metric(row: native.ZendeskTicketMetric) -> list[native.ZendeskMetricRow]:
    expanded: list[native.ZendeskMetricRow] = []
    for metric, unit, value in row.measurements():
        if value is None:
            continue
        for basis, measurement in (
            (native.ZendeskMetricBasis.BUSINESS, value.business),
            (native.ZendeskMetricBasis.CALENDAR, value.calendar),
        ):
            if measurement is None:
                continue
            decimal_value = _optional_decimal(measurement)
            if decimal_value is None:
                continue
            expanded.append(
                native.ZendeskMetricRow(
                    source=row,
                    metric=metric,
                    basis=basis,
                    value=str(decimal_value),
                    unit=unit,
                )
            )
    return expanded


def _user_matches_stream(stream_key: str, row: native.ZendeskUser) -> bool:
    role = _optional_string(row.role)
    return (
        role == native.ZendeskUserRole.END_USER
        if stream_key == ZendeskStream.CUSTOMERS
        else role in {native.ZendeskUserRole.AGENT, native.ZendeskUserRole.ADMIN}
    )


def _require_user_role(stream_key: str, row: native.ZendeskUser) -> None:
    if not _user_matches_stream(stream_key, row):
        raise SorExternalRecordNotFound(
            vendor_object_key=stream_key,
            external_id=_required_id(row.id, field="Zendesk user ID"),
            reason="Zendesk user does not belong to this canonical role stream",
        )


def _comment_external_id(ticket_id: str, comment_id: str) -> str:
    return f"{ticket_id}:{comment_id}"


def _webhook_name(source_id: object) -> str:
    return f"Eylo Zendesk source {source_id}"


def _webhook_path_id(value: object) -> str:
    webhook_id = _required_id(value, field="Zendesk webhook ID")
    if len(webhook_id) > 128 or any(
        not (character.isalnum() or character in {"-", "_"}) for character in webhook_id
    ):
        raise _invalid_response("Zendesk webhook ID is invalid.")
    return webhook_id


def _webhook_events(selected_objects: Sequence[str]) -> tuple[ZendeskWebhookEvent, ...]:
    selected = frozenset(selected_objects)
    events: list[ZendeskWebhookEvent] = []
    if ZendeskStream.TICKETS in selected:
        events.extend(_TICKET_WEBHOOK_EVENTS)
        events.extend(_COMMENT_WEBHOOK_EVENTS)
        events.extend(_ATTACHMENT_WEBHOOK_EVENTS)
    if ZendeskStream.COMMENTS in selected:
        events.extend(_COMMENT_WEBHOOK_EVENTS)
    if ZendeskStream.ATTACHMENTS in selected:
        events.extend(_ATTACHMENT_WEBHOOK_EVENTS)
    if ZendeskStream.TAGS in selected:
        events.append(ZendeskWebhookEvent.TAGS_CHANGED)
    if ZendeskStream.TICKET_METRICS in selected:
        events.extend(_METRIC_WEBHOOK_EVENTS)
    return tuple(dict.fromkeys(events))


def _webhook_signals(
    *,
    data: ZendeskWebhookDelivery,
    headers: Mapping[str, str],
    selected_objects: Sequence[str],
    ticket_id: str,
) -> tuple[SorWebhookSignal, ...]:
    """Translate one Zendesk ticket event into bounded selected-stream hints."""
    selected = frozenset(selected_objects)
    event_type = _optional_string(data.type) or ZENDESK_WEBHOOK_UNSPECIFIED_EVENT
    delivery_id = _header(headers, ZENDESK_WEBHOOK_DELIVERY_HEADER) or _optional_string(
        data.id
    )
    occurred_at = _optional_datetime(data.time)
    hints: list[tuple[str | None, str | None]] = []
    if ZendeskStream.TICKETS in selected:
        hints.append((ZendeskStream.TICKETS, ticket_id))

    comment = data.event.comment if data.event is not None else None
    comment_id = _optional_id(comment.id) if comment is not None else None
    if event_type in _COMMENT_WEBHOOK_EVENTS and ZendeskStream.COMMENTS in selected:
        hints.append(
            (
                ZendeskStream.COMMENTS if comment_id is not None else None,
                _comment_external_id(ticket_id, comment_id)
                if comment_id is not None
                else None,
            )
        )

    attachment = comment.attachment if comment is not None else None
    attachment_id = _optional_id(attachment.id) if attachment is not None else None
    if (
        event_type in _ATTACHMENT_WEBHOOK_EVENTS
        and ZendeskStream.ATTACHMENTS in selected
    ):
        hints.append(
            (
                ZendeskStream.ATTACHMENTS
                if comment_id is not None and attachment_id is not None
                else None,
                _attachment_id(ticket_id, comment_id, attachment_id)
                if comment_id is not None and attachment_id is not None
                else None,
            )
        )

    if (
        event_type == ZendeskWebhookEvent.TAGS_CHANGED
        and ZendeskStream.TAGS in selected
    ):
        hints.append((None, None))
    if (
        event_type in _METRIC_WEBHOOK_EVENTS
        and ZendeskStream.TICKET_METRICS in selected
    ):
        hints.append((None, None))

    unique_hints = tuple(dict.fromkeys(hints))
    return tuple(
        SorWebhookSignal(
            delivery_id=delivery_id,
            event_type=event_type,
            vendor_object_key=vendor_object_key,
            external_id=external_id,
            occurred_at=occurred_at,
        )
        for vendor_object_key, external_id in unique_hints
    )


def _split_comment_id(value: str) -> tuple[str, str]:
    parts = value.split(":")
    if len(parts) != 2:
        raise _invalid_command("Zendesk comment identity is invalid.")
    return _path_id(parts[0]), _path_id(parts[1])


def _attachment_id(ticket_id: str, comment_id: str, attachment_id: str) -> str:
    return f"{ticket_id}:{comment_id}:{attachment_id}"


def _attachment_external_id(
    ticket_id: str,
    comment_id: str,
    attachment: native.ZendeskAttachment,
) -> str:
    attachment_id = _required_id(
        attachment.id,
        field="Zendesk attachment ID",
    )
    return _attachment_id(ticket_id, comment_id, attachment_id)


def _split_attachment_id(value: str) -> tuple[str, str, str]:
    parts = value.split(":")
    if len(parts) != 3:
        raise _invalid_command("Zendesk attachment identity is invalid.")
    return _path_id(parts[0]), _path_id(parts[1]), _path_id(parts[2])


def _metric_external_id(
    metric_id: str, metric: native.ZendeskMetricName, basis: native.ZendeskMetricBasis
) -> str:
    """Keep legacy minute IDs; the native seconds name prevents unit collisions."""
    return f"{metric_id}:{metric}:{basis}"


def _split_metric_id(
    value: str,
) -> tuple[str, native.ZendeskMetricName, native.ZendeskMetricBasis]:
    parts = value.split(":")
    if (
        len(parts) != 3
        or parts[1] not in native.ZendeskMetricName
        or parts[2] not in native.ZendeskMetricBasis
    ):
        raise _invalid_command("Zendesk metric identity is invalid.")
    return (
        _path_id(parts[0]),
        native.ZendeskMetricName(parts[1]),
        native.ZendeskMetricBasis(parts[2]),
    )


def _path_id(value: object) -> str:
    record_id = _required_id(value, field="Zendesk resource ID")
    if not record_id.isdecimal():
        raise _invalid_command("Zendesk resource ID must be numeric.")
    return record_id


def _required_target(command: SorCommandRequest) -> str:
    if command.target_external_id is None:
        raise _invalid_command("This Zendesk action requires an existing ticket.")
    return _path_id(command.target_external_id)


def _ticket_id_from_subject(value: str | None) -> str | None:
    prefix = ZENDESK_WEBHOOK_TICKET_SUBJECT_PREFIX
    if value is None or not value.startswith(prefix):
        return None
    ticket_id = value.removeprefix(prefix)
    return ticket_id if ticket_id.isdecimal() else None


def _webhook_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError) as error:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_WEBHOOK_INVALID,
                "Zendesk webhook timestamp is invalid.",
                recovery=SorRecoveryPolicy.TERMINAL,
            ) from error
    if parsed.tzinfo is None:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_WEBHOOK_INVALID,
            "Zendesk webhook timestamp must include a timezone.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return parsed.astimezone(timezone.utc)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    for key, value in headers.items():
        if key.casefold() == expected:
            normalized = value.strip()
            return normalized or None
    return None


def _audit_comment(
    audit: native.ZendeskAudit,
    *,
    visibility: SupportMessageVisibility,
) -> native.ZendeskAuditEvent:
    matches = [
        event
        for event in audit.events
        if event.type == native.ZendeskAuditEventKind.COMMENT
        and event.public is (visibility is SupportMessageVisibility.PUBLIC)
    ]
    if len(matches) != 1:
        raise _invalid_response("Zendesk did not return the exact created comment.")
    return matches[0]


def _with_revision[InputT: native.ZendeskSafeUpdate](
    values: InputT, revision: str | None
) -> InputT:
    if revision is None:
        return values
    timestamp = _required_datetime(revision, field="Zendesk expected revision")
    return _parse_write(
        {
            **values.model_dump(exclude_unset=True),
            "safe_update": True,
            "updated_stamp": _revision(timestamp),
        },
        type(values),
    )


def _parse_write[InputT: native.ZendeskWriteInput](
    value: object, model: type[InputT]
) -> InputT:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise _invalid_command("Zendesk native write fields are invalid.") from error


def _parse_response[ResultT: native.ZendeskResponse](
    value: object, model: type[ResultT]
) -> ResultT:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise _invalid_response("Zendesk response is invalid.") from error


def _parse_exact_record(value: object, stream_key: str) -> native.ZendeskReadRecord:
    if stream_key == ZendeskStream.TICKETS:
        return _parse_response(value, native.ZendeskTicketReadResponse).ticket
    if stream_key in {ZendeskStream.CUSTOMERS, ZendeskStream.AGENTS}:
        return _parse_response(value, native.ZendeskUserResponse).user
    if stream_key == ZendeskStream.GROUPS:
        return _parse_response(value, native.ZendeskGroupResponse).group
    if stream_key == ZendeskStream.BRANDS:
        return _parse_response(value, native.ZendeskBrandResponse).brand
    raise _invalid_command("Zendesk exact-read stream is unsupported.")


def _parse_reconcile_records(
    value: object, stream_key: str
) -> tuple[Sequence[native.ZendeskReadRecord], native.ZendeskPageMeta]:
    if stream_key == ZendeskStream.GROUPS:
        groups = _parse_response(value, native.ZendeskGroupsPage)
        return groups.groups, groups.meta
    if stream_key == ZendeskStream.BRANDS:
        brands = _parse_response(value, native.ZendeskBrandsPage)
        return brands.brands, brands.meta
    if stream_key == ZendeskStream.TAGS:
        tags = _parse_response(value, native.ZendeskTagsPage)
        return [
            native.ZendeskTag(name=row) if isinstance(row, str) else row
            for row in tags.tags
        ], tags.meta
    if stream_key == ZendeskStream.TICKET_METRICS:
        metrics = _parse_response(value, native.ZendeskMetricsPage)
        return [
            expanded
            for row in metrics.ticket_metrics
            for expanded in _expand_metric(row)
        ], metrics.meta
    raise _invalid_command("Zendesk reconciliation stream is unsupported.")


def _revision(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _request_id(response: SorJsonResponse) -> str | None:
    values = response.header_values("x-zendesk-request-id") or response.header_values(
        "x-request-id"
    )
    return values[0][:512] if values else None


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


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.ok:
        return response.data
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_AUTHORIZATION_EXPIRED,
            f"Zendesk refused authorization while attempting to {operation}.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    if response.status_code == HTTPStatus.FORBIDDEN:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_FORBIDDEN,
            f"Zendesk refused permission to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code == HTTPStatus.NOT_FOUND:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESOURCE_UNAVAILABLE,
            f"Zendesk could not find the resource needed to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code in {HTTPStatus.CONFLICT, HTTPStatus.PRECONDITION_FAILED}:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_REVISION_CONFLICT,
            f"Zendesk rejected stale state while attempting to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            f"Zendesk rejected the data used to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RATE_LIMITED,
            "Zendesk rate-limited the source.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SERVER_FAILED,
            f"Zendesk failed while attempting to {operation}.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    raise SorVendorOperationError(
        SorVendorErrorCode.VENDOR_REQUEST_FAILED,
        f"Zendesk refused the request to {operation}.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise _invalid_response(f"{field} must be a string list.")
    return list(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(_string_list(value, field="Zendesk string list"))


def _required_id(value: object, *, field: str) -> str:
    if isinstance(value, bool):
        raise _invalid_response(f"{field} is invalid.")
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
        raise _invalid_response(f"{field} is invalid.")
    return value.strip()


def _optional_id(value: object) -> str | None:
    if value is None:
        return None
    return _required_id(value, field="Zendesk optional ID")


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1_000_000:
        raise _invalid_response(f"{field} is invalid.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 1_000_000:
        raise _invalid_response("Zendesk string value is invalid.")
    normalized = value.strip()
    return normalized or None


def _required_boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_response(f"{field} must be a boolean.")
    return value


def _optional_boolean(value: object) -> bool | None:
    if value is None:
        return None
    return _required_boolean(value, field="Zendesk boolean value")


def _required_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid_response(f"{field} must be an integer.")
    return value


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    return _required_integer(value, field="Zendesk integer value")


def _required_datetime(value: object, *, field: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise _invalid_response(f"{field} is invalid.")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise _invalid_response("Zendesk timestamp is invalid.") from error
    else:
        raise _invalid_response("Zendesk timestamp is invalid.")
    if parsed.tzinfo is None:
        raise _invalid_response("Zendesk timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _invalid_response("Zendesk decimal value is invalid.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise _invalid_response("Zendesk decimal value is invalid.") from error
    if not parsed.is_finite() or parsed.copy_abs() >= Decimal("1e18"):
        raise _invalid_response("Zendesk decimal value is invalid.")
    return parsed


def _json_value(value: object) -> SorJsonValue:
    try:
        return require_json_value(value)
    except ValueError as error:
        raise _invalid_response("Zendesk value is not JSON compatible.") from error


def _invalid_command(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_COMMAND_INVALID,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _invalid_cursor(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_CURSOR_INVALID,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _invalid_response(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


__all__ = [
    "ZENDESK_MANIFEST",
    "ZendeskSupportAdapter",
    "create_zendesk_adapter",
]
