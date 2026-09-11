"""Freshdesk adapter for Eylo's canonical customer-support profile."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import IntEnum, StrEnum
from html.parser import HTMLParser
from http import HTTPStatus
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

from eylo.common.http_egress import HttpMethod
from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.runtime.http import SorHttpTransport, SorJsonHttpClient, SorJsonResponse
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterContext,
    SorCapabilityUnavailable,
    SorChangeStrategy,
    SorCommandRequest,
    SorCommandResult,
    SorCommandRevisionConflict,
    SorConnectionVerification,
    SorDeletedRecord,
    SorDiscoveredField,
    SorDiscoveredObject,
    SorDiscoveredSchema,
    SorExternalRecord,
    SorExternalRecordNotFound,
    SorFieldDataType,
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
from eylo.sor.support.vendors.freshdesk_contracts import (
    FreshdeskMutationInput,
    FreshdeskMutationRecord,
    FreshdeskNoteInput,
    FreshdeskReplyInput,
    FreshdeskTagAction,
    FreshdeskTicketCreate,
    FreshdeskTicketPriorityCode,
    FreshdeskTicketStatusCode,
    FreshdeskTicketTags,
    FreshdeskTicketUpdate,
    FreshdeskTicketWriteField,
    FreshdeskWriteInput,
)

FRESHDESK_API_VERSION = "v2"
FRESHDESK_CURSOR_VERSION = 1
FRESHDESK_OVERLAP = timedelta(seconds=60)
FRESHDESK_INITIAL_SINCE = datetime(1970, 1, 1, tzinfo=timezone.utc)
FRESHDESK_MAX_PAGES = 300
FRESHDESK_EXPANSION_TICKET_PAGE = 10
FRESHDESK_MAX_CONVERSATION_PAGES = 5
FRESHDESK_MAX_EMPTY_EXPANSIONS = 30


class FreshdeskTicketSourceCode(IntEnum):
    """Freshdesk's documented numeric ticket source codes."""

    EMAIL = 1
    PORTAL = 2
    PHONE = 3
    CHAT = 7
    FEEDBACK_WIDGET = 9
    OUTBOUND_EMAIL = 10


_STATUS_NAMES = {code: code.name.casefold() for code in FreshdeskTicketStatusCode}
_STATUS_CODES = {value: key for key, value in _STATUS_NAMES.items()}
_NORMALIZED_STATUS = {
    "open": SupportTicketState.OPEN,
    "pending": SupportTicketState.PENDING,
    "resolved": SupportTicketState.RESOLVED,
    "closed": SupportTicketState.CLOSED,
}
_PRIORITY_NAMES = {code: code.name.casefold() for code in FreshdeskTicketPriorityCode}
_PRIORITY_CODES = {value: key for key, value in _PRIORITY_NAMES.items()}
_SOURCE_NAMES = {code: code.name.casefold() for code in FreshdeskTicketSourceCode}


class FreshdeskStream(StrEnum):
    """Closed vendor stream vocabulary owned by this adapter."""

    TICKETS = "tickets"
    CONTACTS = "contacts"
    AGENTS = "agents"
    GROUPS = "groups"
    EMAIL_CONFIGS = "email_configs"
    CONVERSATIONS = "conversations"
    TAGS = "tags"
    SLA_METRICS = "sla_metrics"
    ATTACHMENTS = "attachments"


_STREAM_ENTITY = {
    FreshdeskStream.TICKETS: SupportEntityKind.TICKET,
    FreshdeskStream.CONTACTS: SupportEntityKind.CUSTOMER,
    FreshdeskStream.AGENTS: SupportEntityKind.AGENT,
    FreshdeskStream.GROUPS: SupportEntityKind.QUEUE,
    FreshdeskStream.EMAIL_CONFIGS: SupportEntityKind.INBOX,
    FreshdeskStream.CONVERSATIONS: SupportEntityKind.MESSAGE,
    FreshdeskStream.TAGS: SupportEntityKind.TAG,
    FreshdeskStream.SLA_METRICS: SupportEntityKind.SLA_METRIC,
    FreshdeskStream.ATTACHMENTS: SupportEntityKind.ATTACHMENT,
}
_RELATIONSHIP_TARGETS = {
    FreshdeskStream.TICKETS: {
        SorRelationshipRole.REQUESTER: FreshdeskStream.CONTACTS,
        SorRelationshipRole.ASSIGNEE: FreshdeskStream.AGENTS,
        SorRelationshipRole.QUEUE: FreshdeskStream.GROUPS,
        SorRelationshipRole.INBOX: FreshdeskStream.EMAIL_CONFIGS,
        SorRelationshipRole.TAG: FreshdeskStream.TAGS,
    },
    FreshdeskStream.CONVERSATIONS: {
        SorRelationshipRole.TICKET: FreshdeskStream.TICKETS
    },
    FreshdeskStream.SLA_METRICS: {SorRelationshipRole.TICKET: FreshdeskStream.TICKETS},
    FreshdeskStream.ATTACHMENTS: {
        SorRelationshipRole.TICKET: FreshdeskStream.TICKETS,
        SorRelationshipRole.MESSAGE: FreshdeskStream.CONVERSATIONS,
    },
}
_UPDATED_STREAMS = frozenset(
    {
        FreshdeskStream.TICKETS,
        FreshdeskStream.CONTACTS,
        FreshdeskStream.CONVERSATIONS,
        FreshdeskStream.TAGS,
        FreshdeskStream.SLA_METRICS,
        FreshdeskStream.ATTACHMENTS,
    }
)
_FULL_RECONCILE_STREAMS = frozenset(
    {FreshdeskStream.AGENTS, FreshdeskStream.GROUPS, FreshdeskStream.EMAIL_CONFIGS}
)
_EXPANDED_STREAMS = frozenset(
    {
        FreshdeskStream.CONVERSATIONS,
        FreshdeskStream.TAGS,
        FreshdeskStream.SLA_METRICS,
        FreshdeskStream.ATTACHMENTS,
    }
)
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
    SupportToolName.FIND_CUSTOMER: frozenset({FreshdeskStream.CONTACTS}),
    SupportToolName.FIND_TICKET: frozenset({FreshdeskStream.TICKETS}),
    SupportToolName.GET_TICKET: frozenset(
        {FreshdeskStream.TICKETS, FreshdeskStream.CONVERSATIONS}
    ),
    SupportToolName.GET_CUSTOMER_HISTORY: frozenset(
        {FreshdeskStream.CONTACTS, FreshdeskStream.TICKETS}
    ),
    SupportToolName.LIST_QUEUES: frozenset({FreshdeskStream.GROUPS}),
    SupportToolName.DESCRIBE_TICKET_FIELDS: frozenset({FreshdeskStream.TICKETS}),
    SupportToolName.OPEN_TICKET: frozenset({FreshdeskStream.TICKETS}),
    SupportToolName.UPDATE_TICKET: frozenset({FreshdeskStream.TICKETS}),
    SupportToolName.ASSIGN_TICKET: frozenset(
        {FreshdeskStream.TICKETS, FreshdeskStream.AGENTS}
    ),
    SupportToolName.REPLY: frozenset(
        {FreshdeskStream.TICKETS, FreshdeskStream.CONVERSATIONS}
    ),
    SupportToolName.ADD_NOTE: frozenset(
        {FreshdeskStream.TICKETS, FreshdeskStream.CONVERSATIONS}
    ),
    SupportToolName.CLOSE_TICKET: frozenset({FreshdeskStream.TICKETS}),
    SupportToolName.ADD_TAG: frozenset({FreshdeskStream.TICKETS, FreshdeskStream.TAGS}),
    SupportToolName.REMOVE_TAG: frozenset(
        {FreshdeskStream.TICKETS, FreshdeskStream.TAGS}
    ),
}
_MUTATION_RESULT_STREAMS = {
    **{name: FreshdeskStream.TICKETS for name in _WRITE_TOOLS},
    SupportToolName.REPLY: FreshdeskStream.CONVERSATIONS,
    SupportToolName.ADD_NOTE: FreshdeskStream.CONVERSATIONS,
}


FRESHDESK_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.SUPPORT,
    vendor_key="freshdesk",
    auth_kinds=(ConnectionAuthKind.API_KEY,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                FreshdeskStream.TICKETS: "Tickets",
                FreshdeskStream.CONTACTS: "Contacts",
                FreshdeskStream.AGENTS: "Agents",
                FreshdeskStream.GROUPS: "Groups",
                FreshdeskStream.EMAIL_CONFIGS: "Email inboxes",
                FreshdeskStream.CONVERSATIONS: "Conversations",
                FreshdeskStream.TAGS: "Tags",
                FreshdeskStream.SLA_METRICS: "SLA targets",
                FreshdeskStream.ATTACHMENTS: "Attachments",
            }[stream_key],
            description={
                FreshdeskStream.TICKETS: "Freshdesk tickets, assignment, state, tags, and custom fields.",
                FreshdeskStream.CONTACTS: "Freshdesk contacts who request support.",
                FreshdeskStream.AGENTS: "Freshdesk agents who may own tickets.",
                FreshdeskStream.GROUPS: "Freshdesk groups used as support queues.",
                FreshdeskStream.EMAIL_CONFIGS: "Freshdesk support addresses used as ticket inboxes.",
                FreshdeskStream.CONVERSATIONS: "Customer-visible replies and private Agent notes.",
                FreshdeskStream.TAGS: "Classification tags observed on synchronized tickets.",
                FreshdeskStream.SLA_METRICS: "Response and resolution targets derived from tickets.",
                FreshdeskStream.ATTACHMENTS: "Metadata for files attached to conversations.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=(
                frozenset({SorChangeStrategy.UPDATED_AT})
                if stream_key in _UPDATED_STREAMS
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
    custom_object_change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
    tool_streams={
        tool.value: frozenset(stream.value for stream in streams)
        for tool, streams in _TOOL_STREAMS.items()
    },
    mutation_result_streams={
        tool.value: stream.value for tool, stream in _MUTATION_RESULT_STREAMS.items()
    },
    requires_instance_origin=True,
    supports_custom_fields=True,
    supports_custom_objects=True,
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
    group: str = "Freshdesk",
) -> SorDiscoveredField:
    return SorDiscoveredField(
        key=key,
        label=label,
        data_type=data_type,
        nullable=nullable,
        writable=writable,
        choices=choices,
        description=description,
        group=group,
    )


_SCHEMA_FIELDS = {
    FreshdeskStream.TICKETS: (
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
            "inbox_external_id",
            "Email config ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field(
            "native_status",
            "Status",
            SorFieldDataType.ENUM,
            writable=True,
            choices=tuple(_STATUS_CODES),
        ),
        _field("normalized_status", "Normalized status", SorFieldDataType.ENUM),
        _field(
            "priority",
            "Priority",
            SorFieldDataType.ENUM,
            writable=True,
            choices=tuple(_PRIORITY_CODES),
        ),
        _field("category", "Type", SorFieldDataType.TEXT, writable=True),
        _field("channel", "Source channel", SorFieldDataType.TEXT),
        _field(
            "tag_external_ids", "Tags", SorFieldDataType.STRING_ARRAY, writable=True
        ),
        _field("first_response_at", "First response", SorFieldDataType.TIMESTAMP),
        _field("resolved_at", "Resolved", SorFieldDataType.TIMESTAMP),
        _field("closed_at", "Closed", SorFieldDataType.TIMESTAMP),
        _field("sla_state", "SLA state", SorFieldDataType.ENUM),
    ),
    FreshdeskStream.CONTACTS: (
        _field("name", "Name", SorFieldDataType.TEXT, writable=True),
        _field("primary_email", "Email", SorFieldDataType.TEXT, writable=True),
        _field("primary_phone", "Phone", SorFieldDataType.TEXT, writable=True),
        _field(
            "company_external_id",
            "Company ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field("active", "Active", SorFieldDataType.BOOLEAN, writable=True),
    ),
    FreshdeskStream.AGENTS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("primary_email", "Email", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
        _field("assignable", "Assignable", SorFieldDataType.BOOLEAN),
        _field("avatar_url", "Avatar URL", SorFieldDataType.URL),
    ),
    FreshdeskStream.GROUPS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("description", "Description", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
    ),
    FreshdeskStream.EMAIL_CONFIGS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("kind", "Kind", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
    ),
    FreshdeskStream.CONVERSATIONS: (
        _field(
            "ticket_external_id",
            "Ticket ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("visibility", "Visibility", SorFieldDataType.ENUM, nullable=False),
        _field("direction", "Direction", SorFieldDataType.ENUM),
        _field("author_external_id", "Author ID", SorFieldDataType.REFERENCE),
        _field("normalized_text", "Message", SorFieldDataType.TEXT, nullable=False),
        _field("source_body", "Source body", SorFieldDataType.JSON),
        _field("body_format", "Body format", SorFieldDataType.TEXT),
        _field(
            "attachment_external_ids", "Attachment IDs", SorFieldDataType.STRING_ARRAY
        ),
        _field("created_at", "Created", SorFieldDataType.TIMESTAMP, nullable=False),
        _field("updated_at", "Updated", SorFieldDataType.TIMESTAMP),
    ),
    FreshdeskStream.TAGS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
    ),
    FreshdeskStream.SLA_METRICS: (
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
        _field("target_at", "Target", SorFieldDataType.TIMESTAMP),
        _field("achieved_at", "Achieved", SorFieldDataType.TIMESTAMP),
        _field("breached_at", "Breached", SorFieldDataType.TIMESTAMP),
    ),
    FreshdeskStream.ATTACHMENTS: (
        _field(
            "ticket_external_id",
            "Ticket ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("message_external_id", "Message ID", SorFieldDataType.REFERENCE),
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("content_type", "Content type", SorFieldDataType.TEXT),
        _field("size_bytes", "Size", SorFieldDataType.INTEGER),
        _field("source_url", "Source URL", SorFieldDataType.URL),
    ),
}

_COMPANY_FIELDS = (
    _field(
        "name", "Name", SorFieldDataType.TEXT, nullable=False, group="Freshdesk company"
    ),
    _field(
        "domains", "Domains", SorFieldDataType.STRING_ARRAY, group="Freshdesk company"
    ),
    _field(
        "description", "Description", SorFieldDataType.TEXT, group="Freshdesk company"
    ),
    _field("note", "Note", SorFieldDataType.TEXT, group="Freshdesk company"),
    _field(
        "health_score", "Health score", SorFieldDataType.TEXT, group="Freshdesk company"
    ),
    _field(
        "account_tier", "Account tier", SorFieldDataType.TEXT, group="Freshdesk company"
    ),
    _field("industry", "Industry", SorFieldDataType.TEXT, group="Freshdesk company"),
    _field(
        "created_at", "Created", SorFieldDataType.TIMESTAMP, group="Freshdesk company"
    ),
    _field(
        "updated_at", "Updated", SorFieldDataType.TIMESTAMP, group="Freshdesk company"
    ),
)


class _UpdatedCursor(BaseModel):
    """Freshdesk updated-since watermark and native page number."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    since: datetime
    page: int


class _ExpansionCursor(BaseModel):
    """Freshdesk child offset within an updated-ticket scan."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    scan: _UpdatedCursor
    offset: int


class FreshdeskSupportAdapter:
    """Translate one exact Freshdesk tenant into Eylo's Support contract."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "freshdesk":
            raise ValueError("Freshdesk adapter requires the freshdesk vendor key.")
        if context.auth_kind is not ConnectionAuthKind.API_KEY:
            raise ValueError("Freshdesk SOR requires API-key authentication.")
        self._context = context
        self._origin = _freshdesk_origin(context.instance_origin)
        api_key = _credential(context.credentials, "api_key")
        authorization = base64.b64encode(f"{api_key}:X".encode()).decode()
        self._client = SorJsonHttpClient(
            origin=self._origin,
            authorization=f"Basic {authorization}",
            transport=transport,
            response_body_limit=8_388_608,
        )

    async def verify_connection(self) -> SorConnectionVerification:
        response = await self._client.request("/api/v2/agents/me")
        agent = _object(_expect(response, operation="identify the Freshdesk Agent"))
        contact = agent.get("contact")
        contact_name = (
            _optional_string(contact.get("name"))
            if isinstance(contact, Mapping)
            else None
        )
        return SorConnectionVerification(
            account_external_id=_required_id(
                agent.get("id"), field="Freshdesk Agent ID"
            ),
            account_display_name=(contact_name or _optional_string(agent.get("name")))
            or _optional_string(agent.get("email"))
            or "Freshdesk account",
            granted_scopes=(),
            vendor_api_version=FRESHDESK_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise SorVendorOperationError(
                SorVendorErrorCode.SOURCE_SELECTION_EMPTY,
                "The Freshdesk source selects no streams.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        manifest_streams = {stream.key: stream for stream in FRESHDESK_MANIFEST.streams}
        objects: list[SorDiscoveredObject] = []
        for stream_key in self._context.selected_objects:
            if stream_key not in manifest_streams and not _is_custom_stream(stream_key):
                raise _invalid_stream("Freshdesk does not recognize a selected stream.")
            if stream_key in manifest_streams:
                fields = _SCHEMA_FIELDS[FreshdeskStream(stream_key)]
                if stream_key == FreshdeskStream.TICKETS:
                    fields = (
                        *fields,
                        *await self._discover_fields("ticket_fields", "ticket"),
                    )
                elif stream_key == FreshdeskStream.CONTACTS:
                    fields = (
                        *fields,
                        *await self._discover_fields("contact_fields", "contact"),
                    )
                objects.append(
                    SorDiscoveredObject(
                        key=stream_key,
                        label=manifest_streams[stream_key].label,
                        fields=fields,
                    )
                )

        company_fields = await self._discover_fields(
            "company_fields",
            "company",
            optional=True,
        )
        objects.append(
            SorDiscoveredObject(
                key="companies",
                label="Companies",
                fields=(*_COMPANY_FIELDS, *company_fields),
                custom=True,
            )
        )
        objects.extend(await self._discover_custom_objects())
        return SorDiscoveredSchema(
            objects=tuple(_unique_objects(objects)),
            vendor_api_version=FRESHDESK_API_VERSION,
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
        if stream_key == FreshdeskStream.TAGS:
            name = _required_string(external_id, field="Freshdesk tag")
            return self._external_record(FreshdeskStream.TAGS, {"name": name})
        if stream_key in {FreshdeskStream.CONVERSATIONS, FreshdeskStream.ATTACHMENTS}:
            ticket_id, child_id, attachment_id = _split_expanded_id(
                external_id,
                attachment=stream_key == FreshdeskStream.ATTACHMENTS,
            )
            conversations = await self._ticket_conversations(ticket_id)
            conversation = next(
                (
                    row
                    for row in conversations
                    if _required_id(row.get("id"), field="Freshdesk conversation ID")
                    == child_id
                ),
                None,
            )
            if conversation is None:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=external_id,
                )
            if stream_key == FreshdeskStream.CONVERSATIONS:
                row = dict(conversation)
                row["_ticket_id"] = ticket_id
                return self._external_record(stream_key, row)
            attachment = next(
                (
                    row
                    for row in _object_list(
                        conversation.get(FreshdeskStream.ATTACHMENTS) or [],
                        field="Freshdesk conversation attachments",
                    )
                    if _required_id(row.get("id"), field="Freshdesk attachment ID")
                    == attachment_id
                ),
                None,
            )
            if attachment is None:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=external_id,
                )
            row = dict(attachment)
            row["_ticket_id"] = ticket_id
            row["_conversation_id"] = child_id
            return self._external_record(stream_key, row)
        if stream_key == FreshdeskStream.SLA_METRICS:
            ticket_id, metric = _split_metric_id(external_id)
            ticket = await self._ticket(ticket_id)
            row = next(
                (
                    item
                    for item in _expand_sla_metrics(ticket)
                    if item["_metric"] == metric
                ),
                None,
            )
            if row is None:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=external_id,
                )
            return self._external_record(stream_key, row)
        if stream_key == "companies":
            response = await self._client.request(
                f"/api/v2/companies/{_path_id(external_id)}"
            )
            return self._fetched_record(stream_key, external_id, response)
        if _is_freshdesk_custom_object(stream_key):
            schema_id = _custom_schema_id(stream_key)
            response = await self._client.request(
                f"/api/v2/custom_objects/schemas/{schema_id}/records/{_path_token(external_id)}"
            )
            return self._fetched_record(stream_key, external_id, response)

        endpoint = {
            FreshdeskStream.TICKETS: f"/api/v2/tickets/{_path_id(external_id)}",
            FreshdeskStream.CONTACTS: f"/api/v2/contacts/{_path_id(external_id)}",
            FreshdeskStream.AGENTS: f"/api/v2/agents/{_path_id(external_id)}",
            FreshdeskStream.GROUPS: f"/api/v2/groups/{_path_id(external_id)}",
            FreshdeskStream.EMAIL_CONFIGS: f"/api/v2/email_configs/{_path_id(external_id)}",
        }[FreshdeskStream(stream_key)]
        response = await self._client.request(
            endpoint,
            query={"include": "stats"}
            if stream_key == FreshdeskStream.TICKETS
            else None,
        )
        return self._fetched_record(stream_key, external_id, response)

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "Freshdesk deletion polling is unavailable; complete reconciliation infers removals."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Freshdesk product events require a separately installed Freshworks app."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Freshdesk polling sources have no webhook lease."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "Freshdesk polling sources have no webhook lease."
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        raise SorCapabilityUnavailable(
            "Freshdesk product-event verification is not enabled for API-key sources."
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        raise SorCapabilityUnavailable(
            "Freshdesk product events are not enabled for API-key sources."
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_TOOL_UNSUPPORTED,
                "This Freshdesk adapter does not execute the requested support action.",
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
            return await self._add_conversation(
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
            action=(
                FreshdeskTagAction.ADD
                if command.tool_name == SupportToolName.ADD_TAG
                else FreshdeskTagAction.REMOVE
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
            requester_external_id=_optional_id(payload.requester_external_id),
            assignee_external_id=_optional_id(payload.assignee_external_id),
            group_external_id=_optional_id(payload.group_external_id),
            inbox_external_id=_optional_id(payload.inbox_external_id),
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
            company_external_id=_optional_id(payload.company_external_id),
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
            name=_required_string(payload.name, field="Freshdesk Agent name"),
            primary_email=_optional_string(payload.primary_email),
            active=payload.active,
            assignable=payload.assignable,
            avatar_url=_safe_source_url(payload.avatar_url),
        )

    def normalize_message(
        self,
        record: SorExternalRecord,
        payload: SupportMessagePayload,
    ) -> SupportMessage:
        return SupportMessage(
            external_id=record.external_id,
            ticket_external_id=_required_id(
                payload.ticket_external_id,
                field="Freshdesk conversation ticket ID",
            ),
            visibility=payload.visibility,
            direction=payload.direction,
            author_external_id=_optional_id(payload.author_external_id),
            normalized_text=_required_string(
                payload.normalized_text,
                field="Freshdesk conversation body",
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
            name=_required_string(payload.name, field="Freshdesk group name"),
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
            name=_required_string(payload.name, field="Freshdesk inbox name"),
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
            name=_required_string(payload.name, field="Freshdesk tag"),
        )

    def normalize_sla_metric(
        self,
        record: SorExternalRecord,
        payload: SupportSlaMetricPayload,
    ) -> SupportSlaMetric:
        return SupportSlaMetric(
            external_id=record.external_id,
            ticket_external_id=_required_id(
                payload.ticket_external_id,
                field="Freshdesk SLA ticket ID",
            ),
            metric=_required_string(payload.metric, field="Freshdesk SLA metric"),
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
            ticket_external_id=_required_id(
                payload.ticket_external_id,
                field="Freshdesk attachment ticket ID",
            ),
            message_external_id=_optional_id(payload.message_external_id),
            name=_required_string(payload.name, field="Freshdesk attachment name"),
            content_type=_optional_string(payload.content_type),
            size_bytes=payload.size_bytes,
            source_url=_safe_source_url(payload.source_url),
        )

    async def close(self) -> None:
        return None

    async def _discover_fields(
        self,
        endpoint: str,
        kind: str,
        *,
        optional: bool = False,
    ) -> tuple[SorDiscoveredField, ...]:
        response = await self._client.request(f"/api/v2/{endpoint}")
        if optional and response.status_code in {
            HTTPStatus.FORBIDDEN,
            HTTPStatus.NOT_FOUND,
        }:
            return ()
        rows = _object_list(
            _expect(response, operation=f"list Freshdesk {kind} fields"),
            field=f"Freshdesk {kind} fields",
        )
        fields = [
            _custom_field(row, kind=kind)
            for row in rows
            if row.get("default") is not True
        ]
        return tuple(sorted(fields, key=lambda item: (item.label.casefold(), item.key)))

    async def _discover_custom_objects(self) -> tuple[SorDiscoveredObject, ...]:
        response = await self._client.request("/api/v2/custom_objects/schemas")
        if response.status_code in {HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND}:
            return ()
        data = _object(_expect(response, operation="list Freshdesk custom objects"))
        schemas = _object_list(
            data.get("schemas") or [], field="Freshdesk custom schemas"
        )
        objects: list[SorDiscoveredObject] = []
        for schema in schemas:
            if schema.get("deleted") is True:
                continue
            schema_id = _path_id(schema.get("id"))
            fields = [
                _custom_object_field(row)
                for row in _object_list(
                    schema.get("fields") or [],
                    field="Freshdesk custom object fields",
                )
                if row.get("deleted") is not True and row.get("visible") is not False
            ]
            fields.extend(
                (
                    _field(
                        "display_id",
                        "Display ID",
                        SorFieldDataType.TEXT,
                        nullable=False,
                        group="Freshdesk custom object",
                    ),
                    _field(
                        "created_time",
                        "Created",
                        SorFieldDataType.TIMESTAMP,
                        group="Freshdesk custom object",
                    ),
                    _field(
                        "updated_time",
                        "Updated",
                        SorFieldDataType.TIMESTAMP,
                        group="Freshdesk custom object",
                    ),
                )
            )
            objects.append(
                SorDiscoveredObject(
                    key=f"freshdesk_custom_{schema_id}",
                    label=_optional_string(schema.get("name"))
                    or f"Custom object {schema_id}",
                    fields=tuple(_unique_fields(fields)),
                    custom=True,
                )
            )
        return tuple(
            sorted(objects, key=lambda item: (item.label.casefold(), item.key))
        )

    async def _read_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        stream_key = _require_stream(
            stream_key, selected=self._context.selected_objects
        )
        page_limit = _page_limit(limit)
        if stream_key in _UPDATED_STREAMS:
            if stream_key in _EXPANDED_STREAMS:
                return await self._read_expanded_page(
                    stream_key=stream_key,
                    cursor=cursor,
                    limit=page_limit,
                )
            return await self._read_updated_page(
                stream_key=stream_key,
                cursor=cursor,
                limit=page_limit,
            )
        if stream_key in _FULL_RECONCILE_STREAMS:
            return await self._read_reconcile_page(
                stream_key=stream_key,
                cursor=cursor,
                limit=page_limit,
            )
        if stream_key == "companies":
            return await self._read_reconcile_page(
                stream_key=stream_key,
                cursor=cursor,
                limit=page_limit,
            )
        return await self._read_custom_object_page(
            stream_key=stream_key,
            cursor=cursor,
            limit=page_limit,
        )

    async def _read_updated_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_updated_cursor(cursor, stream_key=stream_key)
        rows, next_checkpoint, has_more = await self._updated_rows(
            stream_key=stream_key,
            checkpoint=checkpoint,
            limit=limit,
        )
        return SorRecordPage(
            records=tuple(self._external_record(stream_key, row) for row in rows),
            next_cursor=_encode_updated_cursor(next_checkpoint, stream_key=stream_key),
            has_more=has_more,
        )

    async def _read_reconcile_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        page = _decode_page_cursor(cursor, stream_key=stream_key)
        if page > FRESHDESK_MAX_PAGES:
            raise _scan_limit()
        response = await self._client.request(
            {
                FreshdeskStream.AGENTS: "/api/v2/agents",
                FreshdeskStream.GROUPS: "/api/v2/groups",
                FreshdeskStream.EMAIL_CONFIGS: "/api/v2/email_configs",
                "companies": "/api/v2/companies",
            }[stream_key],
            query={"page": page, "per_page": limit},
        )
        rows = _object_list(
            _expect(response, operation=f"list Freshdesk {stream_key}"),
            field=f"Freshdesk {stream_key}",
        )
        if len(rows) > limit:
            raise _invalid_response("Freshdesk returned more rows than requested.")
        if len(rows) == limit:
            if page >= FRESHDESK_MAX_PAGES:
                raise _scan_limit()
            next_cursor = _encode_page_cursor(page + 1, stream_key=stream_key)
            has_more = True
        else:
            next_cursor = None
            has_more = False
        return SorRecordPage(
            records=tuple(self._external_record(stream_key, row) for row in rows),
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def _read_expanded_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_expansion_cursor(cursor, stream_key=stream_key)
        empty_expansions = 0
        while True:
            tickets, next_scan, scan_has_more = await self._updated_rows(
                stream_key=FreshdeskStream.TICKETS,
                checkpoint=checkpoint.scan,
                limit=FRESHDESK_EXPANSION_TICKET_PAGE,
            )
            expanded = await self._expand_tickets(stream_key, tickets)
            if checkpoint.offset > len(expanded):
                raise _invalid_cursor("Freshdesk expansion cursor is outside its page.")
            selected = expanded[checkpoint.offset : checkpoint.offset + limit]
            consumed = checkpoint.offset + len(selected)
            if selected:
                if consumed < len(expanded):
                    next_checkpoint = _ExpansionCursor(
                        scan=checkpoint.scan,
                        offset=consumed,
                    )
                    has_more = True
                else:
                    next_checkpoint = _ExpansionCursor(scan=next_scan, offset=0)
                    has_more = scan_has_more
                return SorRecordPage(
                    records=tuple(
                        self._external_record(stream_key, row) for row in selected
                    ),
                    next_cursor=_encode_expansion_cursor(
                        next_checkpoint,
                        stream_key=stream_key,
                    ),
                    has_more=has_more,
                )
            if not scan_has_more:
                return SorRecordPage(
                    records=(),
                    next_cursor=_encode_expansion_cursor(
                        _ExpansionCursor(scan=next_scan, offset=0),
                        stream_key=stream_key,
                    ),
                    has_more=False,
                )
            empty_expansions += 1
            if empty_expansions > FRESHDESK_MAX_EMPTY_EXPANSIONS:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_EXPANSION_BUDGET_EXCEEDED,
                    "Freshdesk returned too many ticket pages without the selected child records.",
                    recovery=SorRecoveryPolicy.RETRY,
                )
            checkpoint = _ExpansionCursor(scan=next_scan, offset=0)

    async def _read_custom_object_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        schema_id = _custom_schema_id(stream_key)
        path = _decode_custom_cursor(cursor, stream_key=stream_key, schema_id=schema_id)
        if path is None:
            path = f"/api/v2/custom_objects/schemas/{schema_id}/records"
            query: Mapping[str, object] | None = {"page_size": limit}
        else:
            query = None
        response = await self._client.request(path, query=query)
        data = _object(_expect(response, operation="list Freshdesk custom records"))
        rows = _object_list(data.get("records") or [], field="Freshdesk custom records")
        if len(rows) > limit:
            raise _invalid_response("Freshdesk returned too many custom records.")
        next_path = _custom_next_path(data.get("_links"), schema_id=schema_id)
        return SorRecordPage(
            records=tuple(self._external_record(stream_key, row) for row in rows),
            next_cursor=(
                _encode_custom_cursor(next_path, stream_key=stream_key)
                if next_path is not None
                else None
            ),
            has_more=next_path is not None,
        )

    async def _updated_rows(
        self,
        *,
        stream_key: str,
        checkpoint: _UpdatedCursor,
        limit: int,
    ) -> tuple[list[dict[str, object]], _UpdatedCursor, bool]:
        if checkpoint.page > FRESHDESK_MAX_PAGES:
            raise _scan_limit()
        requested_at = datetime.now(timezone.utc)
        query: dict[str, object] = {
            "updated_since": _timestamp(checkpoint.since),
            "page": checkpoint.page,
            "per_page": limit,
        }
        if stream_key == FreshdeskStream.TICKETS:
            query.update(
                {
                    "include": "stats",
                    "order_by": "updated_at",
                    "order_type": "asc",
                }
            )
        response = await self._client.request(
            {
                FreshdeskStream.TICKETS: "/api/v2/tickets",
                FreshdeskStream.CONTACTS: "/api/v2/contacts",
            }[FreshdeskStream(stream_key)],
            query=query,
        )
        rows = _object_list(
            _expect(response, operation=f"list updated Freshdesk {stream_key}"),
            field=f"Freshdesk {stream_key}",
        )
        if len(rows) > limit:
            raise _invalid_response("Freshdesk returned more rows than requested.")
        if len(rows) == limit:
            if checkpoint.page >= FRESHDESK_MAX_PAGES:
                raise _scan_limit()
            return (
                rows,
                _UpdatedCursor(since=checkpoint.since, page=checkpoint.page + 1),
                True,
            )
        return (
            rows,
            _UpdatedCursor(
                since=max(FRESHDESK_INITIAL_SINCE, requested_at - FRESHDESK_OVERLAP),
                page=1,
            ),
            False,
        )

    async def _expand_tickets(
        self,
        stream_key: str,
        tickets: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        if stream_key == FreshdeskStream.TAGS:
            return _deduplicate_rows(
                [
                    {"name": tag}
                    for ticket in tickets
                    for tag in _string_list(
                        ticket.get(FreshdeskStream.TAGS) or [], field="Freshdesk tags"
                    )
                ],
                identity="name",
            )
        if stream_key == FreshdeskStream.SLA_METRICS:
            return [
                metric for ticket in tickets for metric in _expand_sla_metrics(ticket)
            ]
        rows: list[dict[str, object]] = []
        for ticket in tickets:
            ticket_id = _required_id(ticket.get("id"), field="Freshdesk ticket ID")
            conversations = await self._ticket_conversations(ticket_id)
            for conversation in conversations:
                conversation_id = _required_id(
                    conversation.get("id"),
                    field="Freshdesk conversation ID",
                )
                if stream_key == FreshdeskStream.CONVERSATIONS:
                    row = dict(conversation)
                    row["_ticket_id"] = ticket_id
                    rows.append(row)
                    continue
                for attachment in _object_list(
                    conversation.get(FreshdeskStream.ATTACHMENTS) or [],
                    field="Freshdesk conversation attachments",
                ):
                    row = dict(attachment)
                    row["_ticket_id"] = ticket_id
                    row["_conversation_id"] = conversation_id
                    rows.append(row)
        return rows

    async def _ticket_conversations(self, ticket_id: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for page in range(1, FRESHDESK_MAX_CONVERSATION_PAGES + 1):
            response = await self._client.request(
                f"/api/v2/tickets/{_path_id(ticket_id)}/conversations",
                query={"page": page, "per_page": 100},
            )
            page_rows = _object_list(
                _expect(response, operation="list Freshdesk ticket conversations"),
                field="Freshdesk ticket conversations",
            )
            rows.extend(page_rows)
            if len(page_rows) < 100:
                return rows
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_EXPANSION_LIMIT_EXCEEDED,
            "A Freshdesk ticket has more conversations than this adapter can safely expand.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )

    async def _ticket(self, ticket_id: str) -> dict[str, object]:
        response = await self._client.request(
            f"/api/v2/tickets/{_path_id(ticket_id)}",
            query={"include": "stats"},
        )
        if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
            raise SorExternalRecordNotFound(
                vendor_object_key=FreshdeskStream.TICKETS,
                external_id=ticket_id,
            )
        return _object(_expect(response, operation="read a Freshdesk ticket"))

    def _fetched_record(
        self,
        stream_key: str,
        external_id: str,
        response: SorJsonResponse,
    ) -> SorExternalRecord:
        if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=external_id,
            )
        row = _object(_expect(response, operation=f"read Freshdesk {stream_key}"))
        return self._external_record(stream_key, row)

    def _external_record(
        self,
        stream_key: str,
        row: Mapping[str, object],
    ) -> SorExternalRecord:
        if stream_key == FreshdeskStream.TICKETS:
            ticket_id = _required_id(row.get("id"), field="Freshdesk ticket ID")
            status = _status_name(row.get("status"))
            stats = _optional_object(row.get("stats"))
            updated_at = _optional_datetime(row.get("updated_at"))
            payload: dict[str, object] = {
                "subject": row.get("subject"),
                "normalized_description": _plain_text(
                    row.get("description_text") or row.get("description")
                ),
                "requester_external_id": row.get("requester_id"),
                "assignee_external_id": row.get("responder_id"),
                "group_external_id": row.get("group_id"),
                "inbox_external_id": row.get("email_config_id"),
                "native_status": status,
                "normalized_status": _NORMALIZED_STATUS.get(status or ""),
                "priority": _priority_name(row.get("priority")),
                "category": row.get("type"),
                "channel": _source_name(row.get("source")),
                "tag_external_ids": row.get(FreshdeskStream.TAGS) or [],
                "first_response_at": stats.get("first_responded_at"),
                "resolved_at": stats.get("resolved_at"),
                "closed_at": stats.get("closed_at"),
                "sla_state": _ticket_sla_state(row, status=status),
            }
            payload.update(_custom_field_values(row.get("custom_fields")))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=ticket_id,
                payload=payload,
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=f"{self._origin}/a/tickets/{ticket_id}",
            )
        if stream_key == FreshdeskStream.CONTACTS:
            contact_id = _required_id(row.get("id"), field="Freshdesk contact ID")
            updated_at = _optional_datetime(row.get("updated_at"))
            payload = {
                "name": row.get("name"),
                "primary_email": row.get("email"),
                "primary_phone": row.get("phone") or row.get("mobile"),
                "company_external_id": row.get("company_id"),
                "active": row.get("active"),
            }
            payload.update(_custom_field_values(row.get("custom_fields")))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=contact_id,
                payload=payload,
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=f"{self._origin}/a/contacts/{contact_id}",
            )
        if stream_key == FreshdeskStream.AGENTS:
            contact = _optional_object(row.get("contact"))
            agent_id = _required_id(row.get("id"), field="Freshdesk Agent ID")
            avatar = _optional_object(contact.get("avatar"))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=agent_id,
                payload={
                    "name": contact.get("name") or row.get("name") or row.get("email"),
                    "primary_email": contact.get("email") or row.get("email"),
                    "active": row.get("active", contact.get("active")),
                    "assignable": row.get("occasional") is not True,
                    "avatar_url": avatar.get("avatar_url"),
                },
            )
        if stream_key == FreshdeskStream.GROUPS:
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.get("id"), field="Freshdesk group ID"),
                payload={
                    "name": row.get("name"),
                    "description": row.get("description"),
                    "active": row.get("deleted") is not True,
                },
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=_optional_datetime(row.get("updated_at")),
            )
        if stream_key == FreshdeskStream.EMAIL_CONFIGS:
            inbox_id = _required_id(row.get("id"), field="Freshdesk email config ID")
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=inbox_id,
                payload={
                    "name": row.get("name")
                    or row.get("reply_email")
                    or row.get("email"),
                    "kind": "email",
                    "active": row.get("active"),
                },
            )
        if stream_key == FreshdeskStream.CONVERSATIONS:
            ticket_id = _required_id(row.get("_ticket_id"), field="Freshdesk ticket ID")
            conversation_id = _required_id(
                row.get("id"), field="Freshdesk conversation ID"
            )
            attachments = _object_list(
                row.get(FreshdeskStream.ATTACHMENTS) or [],
                field="Freshdesk conversation attachments",
            )
            created_at = _required_datetime(
                row.get("created_at"), field="Freshdesk conversation creation time"
            )
            updated_at = _optional_datetime(row.get("updated_at"))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_conversation_id(ticket_id, conversation_id),
                payload={
                    "ticket_external_id": ticket_id,
                    "visibility": "PRIVATE" if row.get("private") is True else "PUBLIC",
                    "direction": "INBOUND"
                    if row.get("incoming") is True
                    else "OUTBOUND",
                    "author_external_id": row.get("user_id") or row.get("from_email"),
                    "normalized_text": _plain_text(
                        row.get("body_text") or row.get("body")
                    ),
                    "source_body": dict(row),
                    "body_format": "text/html" if row.get("body") else "text/plain",
                    "attachment_external_ids": [
                        _attachment_id(
                            ticket_id,
                            conversation_id,
                            _required_id(
                                item.get("id"), field="Freshdesk attachment ID"
                            ),
                        )
                        for item in attachments
                    ],
                    "created_at": created_at,
                    "updated_at": updated_at,
                },
                source_created_at=created_at,
                source_updated_at=updated_at,
                source_revision=_revision(updated_at or created_at),
                source_url=f"{self._origin}/a/tickets/{ticket_id}",
            )
        if stream_key == FreshdeskStream.TAGS:
            name = _required_string(row.get("name"), field="Freshdesk tag")
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=name,
                payload={"name": name},
            )
        if stream_key == FreshdeskStream.SLA_METRICS:
            ticket_id = _required_id(row.get("id"), field="Freshdesk SLA ticket ID")
            metric = _required_string(row.get("_metric"), field="Freshdesk SLA metric")
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_metric_id(ticket_id, metric),
                payload={
                    "ticket_external_id": ticket_id,
                    "metric": metric,
                    "value": None,
                    "unit": None,
                    "native_state": row.get("_native_state"),
                    "normalized_state": row.get("_normalized_state"),
                    "target_at": row.get("_target_at"),
                    "achieved_at": row.get("_achieved_at"),
                    "breached_at": row.get("_breached_at"),
                },
                source_updated_at=_optional_datetime(row.get("updated_at")),
                source_revision=_revision(_optional_datetime(row.get("updated_at"))),
                source_url=f"{self._origin}/a/tickets/{ticket_id}",
            )
        if stream_key == FreshdeskStream.ATTACHMENTS:
            ticket_id = _required_id(row.get("_ticket_id"), field="Freshdesk ticket ID")
            conversation_id = _required_id(
                row.get("_conversation_id"), field="Freshdesk conversation ID"
            )
            attachment_id = _required_id(row.get("id"), field="Freshdesk attachment ID")
            source_url = _safe_source_url(row.get("attachment_url"))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_attachment_id(ticket_id, conversation_id, attachment_id),
                payload={
                    "ticket_external_id": ticket_id,
                    "message_external_id": _conversation_id(ticket_id, conversation_id),
                    "name": row.get("name"),
                    "content_type": row.get("content_type"),
                    "size_bytes": row.get("size"),
                    "source_url": source_url,
                },
                source_url=source_url,
            )
        if stream_key == "companies":
            company_id = _required_id(row.get("id"), field="Freshdesk company ID")
            payload = dict(row)
            payload.update(_custom_field_values(row.get("custom_fields")))
            payload.pop("custom_fields", None)
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=company_id,
                payload=_json_mapping(payload),
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=_optional_datetime(row.get("updated_at")),
                source_revision=_revision(_optional_datetime(row.get("updated_at"))),
                source_url=f"{self._origin}/a/companies/{company_id}",
            )
        display_id = _required_id(
            row.get("display_id"), field="Freshdesk custom record ID"
        )
        payload = _object(row.get("data"), field="Freshdesk custom record data")
        created_at = _epoch_millis_datetime(row.get("created_time"))
        updated_at = _epoch_millis_datetime(row.get("updated_time"))
        payload.update(
            {
                "display_id": display_id,
                "created_time": _revision(created_at),
                "updated_time": _revision(updated_at),
            }
        )
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=display_id,
            payload=_json_mapping(payload),
            source_created_at=created_at,
            source_updated_at=updated_at,
            source_revision=_revision(updated_at),
        )

    async def _open_ticket(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command(
                "Opening a Freshdesk ticket cannot target an existing ticket."
            )
        if not isinstance(command.payload, SupportMappedFieldsCommandPayload):
            raise _invalid_command("Freshdesk ticket fields payload is invalid.")
        fields = self._ticket_write_values(command.payload.fields)
        payload = _parse_write(
            fields.model_dump(exclude_unset=True), FreshdeskTicketCreate
        )
        response = await self._mutation_request(
            "/api/v2/tickets",
            method=HttpMethod.POST,
            payload=payload,
            command=command,
            operation="open a Freshdesk ticket",
        )
        ticket = _parse_mutation_record(
            _expect(response, operation="open a Freshdesk ticket"),
            FreshdeskMutationRecord,
        )
        return self._ticket_result(ticket, response=response)

    async def _update_ticket(
        self,
        ticket_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportMappedFieldsCommandPayload):
            raise _invalid_command("Freshdesk ticket fields payload is invalid.")
        fields = self._ticket_write_values(command.payload.fields)
        await self._require_revision(ticket_id, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{ticket_id}",
            method=HttpMethod.PUT,
            payload=fields,
            command=command,
            operation="update a Freshdesk ticket",
        )
        ticket = _parse_mutation_record(
            _expect(response, operation="update a Freshdesk ticket"),
            FreshdeskMutationRecord,
        )
        return self._ticket_result(ticket, response=response)

    async def _assign_ticket(
        self,
        ticket_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportAssignCommandPayload):
            raise _invalid_command("Freshdesk assignment payload is invalid.")
        assignment: dict[str, int] = {}
        if command.payload.assignee_external_id is not None:
            assignment[FreshdeskTicketWriteField.RESPONDER_ID] = _numeric_id(
                command.payload.assignee_external_id,
                field="Freshdesk assignee ID",
            )
        if command.payload.group_external_id is not None:
            assignment[FreshdeskTicketWriteField.GROUP_ID] = _numeric_id(
                command.payload.group_external_id,
                field="Freshdesk group ID",
            )
        await self._require_revision(ticket_id, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{ticket_id}",
            method=HttpMethod.PUT,
            payload=_parse_write(assignment, FreshdeskTicketUpdate),
            command=command,
            operation="assign a Freshdesk ticket",
        )
        ticket = _parse_mutation_record(
            _expect(response, operation="assign a Freshdesk ticket"),
            FreshdeskMutationRecord,
        )
        return self._ticket_result(ticket, response=response)

    async def _add_conversation(
        self,
        ticket_id: str,
        command: SorCommandRequest,
        *,
        visibility: SupportMessageVisibility,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportMessageCommandPayload):
            raise _invalid_command("Freshdesk message payload is invalid.")
        text = command.payload.normalized_text
        await self._require_revision(ticket_id, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{ticket_id}/"
            f"{'reply' if visibility is SupportMessageVisibility.PUBLIC else 'notes'}",
            method=HttpMethod.POST,
            payload=(
                FreshdeskReplyInput(body=text)
                if visibility is SupportMessageVisibility.PUBLIC
                else FreshdeskNoteInput(body=text, private=True)
            ),
            command=command,
            operation=(
                "reply to a Freshdesk customer"
                if visibility is SupportMessageVisibility.PUBLIC
                else "add a Freshdesk private note"
            ),
        )
        conversation = _parse_mutation_record(
            _expect(response, operation="create a Freshdesk conversation"),
            FreshdeskMutationRecord,
        )
        return SorCommandResult(
            vendor_object_key=FreshdeskStream.CONVERSATIONS,
            external_id=_conversation_id(ticket_id, conversation.id),
            external_request_id=_request_id(response),
            source_revision=_revision(conversation.updated_at),
            source_url=f"{self._origin}/a/tickets/{ticket_id}",
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
            or command.payload.native_status is None
            or command.payload.normalized_text is not None
        ):
            raise _invalid_command(
                "Closing a Freshdesk ticket requires native_status: resolved or closed."
            )
        status = _status_code(command.payload.native_status)
        if status not in {
            FreshdeskTicketStatusCode.RESOLVED,
            FreshdeskTicketStatusCode.CLOSED,
        }:
            raise _invalid_command("Freshdesk close status must be resolved or closed.")
        await self._require_revision(ticket_id, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{ticket_id}",
            method=HttpMethod.PUT,
            payload=FreshdeskTicketUpdate(status=status),
            command=command,
            operation="close a Freshdesk ticket",
        )
        ticket = _parse_mutation_record(
            _expect(response, operation="close a Freshdesk ticket"),
            FreshdeskMutationRecord,
        )
        return self._ticket_result(ticket, response=response)

    async def _change_tag(
        self,
        ticket_id: str,
        command: SorCommandRequest,
        *,
        action: FreshdeskTagAction,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportTagCommandPayload):
            raise _invalid_command("Freshdesk tag payload is invalid.")
        tag = command.payload.tag_external_id
        ticket = _parse_mutation_record(
            await self._ticket(ticket_id), FreshdeskTicketTags
        )
        self._assert_revision(ticket, command.expected_source_revision)
        tags = list(ticket.tags or [])
        if action is FreshdeskTagAction.ADD and tag not in tags:
            tags.append(tag)
        if action is FreshdeskTagAction.REMOVE:
            tags = [value for value in tags if value != tag]
        response = await self._mutation_request(
            f"/api/v2/tickets/{ticket_id}",
            method=HttpMethod.PUT,
            payload=FreshdeskTicketUpdate(tags=tags),
            command=command,
            operation="change a Freshdesk ticket tag",
        )
        updated = _parse_mutation_record(
            _expect(response, operation="change a Freshdesk ticket tag"),
            FreshdeskMutationRecord,
        )
        return self._ticket_result(updated, response=response)

    def _ticket_write_values(
        self, payload: Mapping[str, object]
    ) -> FreshdeskTicketUpdate:
        writable = {
            field.agent_key: field.vendor_field_key
            for field in self._context.fields
            if field.vendor_object_key == FreshdeskStream.TICKETS and field.writable
        }
        if not payload:
            raise _invalid_command(
                "A Freshdesk ticket mutation requires mapped fields."
            )
        unknown = set(payload) - set(writable)
        if unknown:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_FIELD_NOT_WRITABLE,
                "The Freshdesk mutation contains fields absent from the writable mapping.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        result: dict[str, object] = {}
        custom_fields: dict[str, SorJsonValue] = {}
        mapping = {
            "subject": FreshdeskTicketWriteField.SUBJECT,
            "normalized_description": FreshdeskTicketWriteField.DESCRIPTION,
            "requester_external_id": FreshdeskTicketWriteField.REQUESTER_ID,
            "assignee_external_id": FreshdeskTicketWriteField.RESPONDER_ID,
            "group_external_id": FreshdeskTicketWriteField.GROUP_ID,
            "inbox_external_id": FreshdeskTicketWriteField.EMAIL_CONFIG_ID,
            "native_status": FreshdeskTicketWriteField.STATUS,
            "priority": FreshdeskTicketWriteField.PRIORITY,
            "category": FreshdeskTicketWriteField.TYPE,
            "tag_external_ids": FreshdeskTicketWriteField.TAGS,
        }
        for agent_key, value in payload.items():
            vendor_key = writable[agent_key]
            if vendor_key.startswith("custom_field_"):
                custom_fields[vendor_key.removeprefix("custom_field_")] = _json_value(
                    value
                )
                continue
            source_key = mapping.get(vendor_key)
            if source_key is None:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_FIELD_NOT_WRITABLE,
                    "The mapped Freshdesk field is not writable by this adapter.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                )
            if source_key in {
                FreshdeskTicketWriteField.REQUESTER_ID,
                FreshdeskTicketWriteField.RESPONDER_ID,
                FreshdeskTicketWriteField.GROUP_ID,
                FreshdeskTicketWriteField.EMAIL_CONFIG_ID,
            }:
                result[source_key] = _numeric_id(value, field=f"Freshdesk {source_key}")
            elif source_key is FreshdeskTicketWriteField.STATUS:
                result[source_key] = _status_code(value)
            elif source_key is FreshdeskTicketWriteField.PRIORITY:
                result[source_key] = _priority_code(value)
            elif source_key is FreshdeskTicketWriteField.TAGS:
                result[source_key] = _string_list(value, field="Freshdesk tags")
            else:
                result[source_key] = value
        if custom_fields:
            result[FreshdeskTicketWriteField.CUSTOM_FIELDS] = custom_fields
        return _parse_write(result, FreshdeskTicketUpdate)

    async def _require_revision(self, ticket_id: str, revision: str | None) -> None:
        if revision is None:
            return
        ticket = _parse_mutation_record(
            await self._ticket(ticket_id), FreshdeskMutationRecord
        )
        self._assert_revision(ticket, revision)

    @staticmethod
    def _assert_revision(
        ticket: FreshdeskMutationRecord, revision: str | None
    ) -> None:
        if revision is None:
            return
        expected = _required_datetime(revision, field="Freshdesk expected revision")
        current = ticket.updated_at
        if current is None:
            raise _invalid_response("Freshdesk ticket revision is invalid.")
        if current != expected:
            raise SorCommandRevisionConflict(
                "Freshdesk ticket changed after the Agent selected it."
            )

    async def _mutation_request(
        self,
        path: str,
        *,
        method: HttpMethod,
        payload: FreshdeskWriteInput,
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
                    "Freshdesk may have applied the action; reconcile before retrying.",
                    recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
                ) from error
            raise

    def _ticket_result(
        self,
        ticket: FreshdeskMutationRecord,
        *,
        response: SorJsonResponse,
    ) -> SorCommandResult:
        ticket_id = ticket.id
        return SorCommandResult(
            vendor_object_key=FreshdeskStream.TICKETS,
            external_id=ticket_id,
            external_request_id=_request_id(response),
            source_revision=_revision(ticket.updated_at),
            source_url=f"{self._origin}/a/tickets/{ticket_id}",
            response={"status": "accepted"},
        )


def _parse_write[InputT: FreshdeskMutationInput](
    value: object, model: type[InputT]
) -> InputT:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise _invalid_command("Freshdesk mutation fields are invalid.") from error


def _parse_mutation_record[RecordT: FreshdeskMutationRecord](
    value: object, model: type[RecordT]
) -> RecordT:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise _invalid_response("Freshdesk mutation record is invalid.") from error


def create_freshdesk_adapter(context: SorAdapterContext) -> FreshdeskSupportAdapter:
    """Construct the production Freshdesk adapter for the explicit registry."""
    return FreshdeskSupportAdapter(context)


def _freshdesk_origin(value: str | None) -> str:
    if value is None:
        raise ValueError("Freshdesk requires an instance origin.")
    parsed = urlsplit(value.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(
            "Freshdesk origin must be an exact https://<site>.freshdesk.com origin."
        ) from error
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".freshdesk.com")
        or hostname == "freshdesk.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Freshdesk origin must be an exact https://<site>.freshdesk.com origin."
        )
    return f"https://{hostname}"


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CONFIGURATION_INVALID,
            "Freshdesk API key is missing.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    return value.strip()


def _require_stream(stream_key: str, *, selected: Sequence[str]) -> str:
    """Selected custom object keys stay open; static catalog lookups use enums."""
    if stream_key not in _STREAM_ENTITY and not _is_custom_stream(stream_key):
        raise _invalid_stream("This Freshdesk adapter does not recognize the stream.")
    if stream_key not in selected:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNAVAILABLE,
            "The requested Freshdesk stream is not selected for this source.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return stream_key


def _is_custom_stream(value: str) -> bool:
    return value == "companies" or _is_freshdesk_custom_object(value)


def _is_freshdesk_custom_object(value: str) -> bool:
    return (
        value.startswith("freshdesk_custom_")
        and value.removeprefix("freshdesk_custom_").isdecimal()
    )


def _custom_schema_id(value: str) -> str:
    if not _is_freshdesk_custom_object(value):
        raise _invalid_stream("Freshdesk custom object identity is invalid.")
    return _path_id(value.removeprefix("freshdesk_custom_"))


def _custom_field(row: Mapping[str, object], *, kind: str) -> SorDiscoveredField:
    name = _required_string(row.get("name"), field=f"Freshdesk {kind} field name")
    choices = _field_choices(row.get("choices"))
    return _field(
        f"custom_field_{name}",
        _optional_string(row.get("label")) or name,
        _freshdesk_field_type(row.get("type")),
        nullable=row.get("required_for_agents") is not True,
        writable=row.get("agents_can_edit") is not False,
        choices=choices,
        group=f"Freshdesk {kind} custom fields",
    )


def _custom_object_field(row: Mapping[str, object]) -> SorDiscoveredField:
    name = _required_string(row.get("name"), field="Freshdesk custom field name")
    return _field(
        name,
        _optional_string(row.get("label")) or name,
        _freshdesk_custom_object_type(row.get("type")),
        nullable=row.get("required") is not True,
        group="Freshdesk custom object",
    )


def _freshdesk_field_type(value: object) -> SorFieldDataType:
    normalized = (_optional_string(value) or "").casefold()
    if "checkbox" in normalized:
        return SorFieldDataType.BOOLEAN
    if "date" in normalized:
        return SorFieldDataType.DATE
    if "number" in normalized or "decimal" in normalized:
        return SorFieldDataType.DECIMAL
    if "dropdown" in normalized:
        return SorFieldDataType.ENUM
    if "lookup" in normalized:
        return SorFieldDataType.REFERENCE
    if "multi" in normalized:
        return SorFieldDataType.STRING_ARRAY
    if any(name in normalized for name in ("text", "paragraph", "url", "phone")):
        return SorFieldDataType.TEXT
    return SorFieldDataType.JSON


def _freshdesk_custom_object_type(value: object) -> SorFieldDataType:
    normalized = (_optional_string(value) or "").casefold()
    return {
        "boolean": SorFieldDataType.BOOLEAN,
        "checkbox": SorFieldDataType.BOOLEAN,
        "date": SorFieldDataType.DATE,
        "datetime": SorFieldDataType.TIMESTAMP,
        "decimal": SorFieldDataType.DECIMAL,
        "number": SorFieldDataType.DECIMAL,
        "integer": SorFieldDataType.INTEGER,
        "lookup": SorFieldDataType.REFERENCE,
        "multi_select": SorFieldDataType.STRING_ARRAY,
        "primary": SorFieldDataType.TEXT,
        "text": SorFieldDataType.TEXT,
    }.get(normalized, SorFieldDataType.JSON)


def _field_choices(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return tuple(str(item) for item in value if str(item))[:256]
    if isinstance(value, list):
        choices: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                choices.append(item.strip())
            elif isinstance(item, Mapping):
                label = _optional_string(item.get("value") or item.get("label"))
                if label is not None:
                    choices.append(label)
        return tuple(dict.fromkeys(choices))[:256]
    return ()


def _custom_field_values(value: object) -> dict[str, object]:
    if value is None:
        return {}
    fields = _object(value, field="Freshdesk custom fields")
    return {f"custom_field_{key}": _json_value(item) for key, item in fields.items()}


def _unique_objects(values: Sequence[SorDiscoveredObject]) -> list[SorDiscoveredObject]:
    by_key: dict[str, SorDiscoveredObject] = {}
    for value in values:
        existing = by_key.get(value.key)
        if existing is not None and existing != value:
            raise _invalid_response("Freshdesk returned conflicting object schemas.")
        by_key[value.key] = value
    return sorted(
        by_key.values(), key=lambda item: (item.custom, item.label.casefold(), item.key)
    )


def _unique_fields(values: Sequence[SorDiscoveredField]) -> list[SorDiscoveredField]:
    by_key: dict[str, SorDiscoveredField] = {}
    for value in values:
        existing = by_key.get(value.key)
        if existing is not None and existing != value:
            raise _invalid_response("Freshdesk returned conflicting field schemas.")
        by_key[value.key] = value
    return sorted(
        by_key.values(),
        key=lambda item: (item.group or "", item.label.casefold(), item.key),
    )


def _page_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_PAGE_INVALID,
            "Freshdesk page limit must be positive.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return min(limit, 100)


def _encode_updated_cursor(cursor: _UpdatedCursor, *, stream_key: str) -> str:
    return _encode_cursor(
        {
            "version": FRESHDESK_CURSOR_VERSION,
            "kind": "updated",
            "stream": stream_key,
            "since": _timestamp(cursor.since),
            "page": cursor.page,
        }
    )


def _decode_updated_cursor(cursor: str | None, *, stream_key: str) -> _UpdatedCursor:
    if cursor is None:
        return _UpdatedCursor(since=FRESHDESK_INITIAL_SINCE, page=1)
    data = _decode_cursor(cursor, stream_key=stream_key, kind="updated")
    return _updated_cursor_values(data)


def _encode_expansion_cursor(cursor: _ExpansionCursor, *, stream_key: str) -> str:
    return _encode_cursor(
        {
            "version": FRESHDESK_CURSOR_VERSION,
            "kind": "expanded",
            "stream": stream_key,
            "since": _timestamp(cursor.scan.since),
            "page": cursor.scan.page,
            "offset": cursor.offset,
        }
    )


def _decode_expansion_cursor(
    cursor: str | None, *, stream_key: str
) -> _ExpansionCursor:
    if cursor is None:
        return _ExpansionCursor(
            scan=_UpdatedCursor(since=FRESHDESK_INITIAL_SINCE, page=1), offset=0
        )
    data = _decode_cursor(cursor, stream_key=stream_key, kind="expanded")
    offset = data.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise _invalid_cursor("Freshdesk expansion cursor offset is invalid.")
    return _ExpansionCursor(scan=_updated_cursor_values(data), offset=offset)


def _updated_cursor_values(data: Mapping[str, object]) -> _UpdatedCursor:
    since = _required_datetime(data.get("since"), field="Freshdesk cursor timestamp")
    page = data.get("page")
    if (
        isinstance(page, bool)
        or not isinstance(page, int)
        or not 1 <= page <= FRESHDESK_MAX_PAGES
    ):
        raise _invalid_cursor("Freshdesk cursor page is invalid.")
    return _UpdatedCursor(since=since, page=page)


def _encode_page_cursor(page: int, *, stream_key: str) -> str:
    return _encode_cursor(
        {
            "version": FRESHDESK_CURSOR_VERSION,
            "kind": "page",
            "stream": stream_key,
            "page": page,
        }
    )


def _decode_page_cursor(cursor: str | None, *, stream_key: str) -> int:
    if cursor is None:
        return 1
    data = _decode_cursor(cursor, stream_key=stream_key, kind="page")
    page = data.get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise _invalid_cursor("Freshdesk page cursor is invalid.")
    return page


def _encode_custom_cursor(path: str, *, stream_key: str) -> str:
    return _encode_cursor(
        {
            "version": FRESHDESK_CURSOR_VERSION,
            "kind": "custom",
            "stream": stream_key,
            "path": path,
        }
    )


def _decode_custom_cursor(
    cursor: str | None,
    *,
    stream_key: str,
    schema_id: str,
) -> str | None:
    if cursor is None:
        return None
    data = _decode_cursor(cursor, stream_key=stream_key, kind="custom")
    path = data.get("path")
    if not isinstance(path, str):
        raise _invalid_cursor("Freshdesk custom cursor path is invalid.")
    return _validate_custom_path(path, schema_id=schema_id)


def _encode_cursor(payload: Mapping[str, object]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, *, stream_key: str, kind: str) -> dict[str, object]:
    if not cursor or len(cursor) > 8_192:
        raise _invalid_cursor("Freshdesk cursor is invalid.")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _invalid_cursor("Freshdesk cursor is invalid.") from error
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) for key in payload
    ):
        raise _invalid_cursor("Freshdesk cursor payload is invalid.")
    if (
        payload.get("version") != FRESHDESK_CURSOR_VERSION
        or payload.get("kind") != kind
        or payload.get("stream") != stream_key
    ):
        raise _invalid_cursor("Freshdesk cursor does not match this stream.")
    return payload


def _custom_next_path(value: object, *, schema_id: str) -> str | None:
    links = _optional_object(value)
    next_link = links.get("next")
    if next_link is None:
        return None
    href = (
        _optional_string(next_link.get("href"))
        if isinstance(next_link, Mapping)
        else _optional_string(next_link)
    )
    if href is None:
        return None
    return _validate_custom_path(href, schema_id=schema_id)


def _validate_custom_path(value: str, *, schema_id: str) -> str:
    if len(value) > 4_096:
        raise _invalid_cursor("Freshdesk custom cursor path is too long.")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise _invalid_cursor("Freshdesk custom cursor must be origin-relative.")
    expected = f"/api/v2/custom_objects/schemas/{schema_id}/records"
    alternate = f"/schemas/{schema_id}/records"
    if parsed.path == alternate:
        path = expected
    elif parsed.path == expected:
        path = expected
    else:
        raise _invalid_cursor("Freshdesk custom cursor left its record endpoint.")
    allowed = {"page_size", "next_token", "prev_token"}
    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    if any(key not in allowed or len(value) > 2_048 for key, value in pairs):
        raise _invalid_cursor("Freshdesk custom cursor query is invalid.")
    return f"{path}?{urlencode(pairs)}" if pairs else path


def _expand_sla_metrics(ticket: Mapping[str, object]) -> list[dict[str, object]]:
    ticket_id = _required_id(ticket.get("id"), field="Freshdesk ticket ID")
    stats = _optional_object(ticket.get("stats"))
    updated_at = ticket.get("updated_at")
    metrics: list[dict[str, object]] = []
    for metric, target_key, achieved_key, breached in (
        (
            "first_response",
            "fr_due_by",
            "first_responded_at",
            ticket.get("fr_escalated") is True,
        ),
        ("resolution", "due_by", "resolved_at", ticket.get("is_escalated") is True),
    ):
        target = ticket.get(target_key)
        achieved = stats.get(achieved_key)
        if target is None and achieved is None:
            continue
        state = (
            "breached" if breached else "achieved" if achieved is not None else "active"
        )
        metrics.append(
            {
                "id": ticket_id,
                "_metric": metric,
                "_target_at": target,
                "_achieved_at": achieved,
                "_breached_at": updated_at if breached else None,
                "_native_state": state,
                "_normalized_state": state.upper(),
                "updated_at": updated_at,
            }
        )
    return metrics


def _ticket_sla_state(ticket: Mapping[str, object], *, status: str | None) -> str:
    if ticket.get("is_escalated") is True or ticket.get("fr_escalated") is True:
        return "BREACHED"
    if status in {"resolved", "closed"}:
        return "ACHIEVED"
    return "ACTIVE"


def _deduplicate_rows(
    rows: Sequence[dict[str, object]],
    *,
    identity: str,
) -> list[dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    for row in rows:
        key = _required_string(row.get(identity), field="Freshdesk expanded identity")
        values[key] = row
    return list(values.values())


def _conversation_id(ticket_id: str, conversation_id: str) -> str:
    return f"{ticket_id}:{conversation_id}"


def _attachment_id(ticket_id: str, conversation_id: str, attachment_id: str) -> str:
    return f"{ticket_id}:{conversation_id}:{attachment_id}"


def _split_expanded_id(
    value: str,
    *,
    attachment: bool,
) -> tuple[str, str, str | None]:
    parts = value.split(":")
    expected = 3 if attachment else 2
    if len(parts) != expected:
        raise _invalid_command("Freshdesk expanded record identity is invalid.")
    ticket_id = _path_id(parts[0])
    child_id = _path_id(parts[1])
    return ticket_id, child_id, _path_id(parts[2]) if attachment else None


def _metric_id(ticket_id: str, metric: str) -> str:
    return f"{ticket_id}:{metric}"


def _split_metric_id(value: str) -> tuple[str, str]:
    parts = value.split(":")
    if len(parts) != 2 or parts[1] not in {"first_response", "resolution"}:
        raise _invalid_command("Freshdesk SLA metric identity is invalid.")
    return _path_id(parts[0]), parts[1]


def _required_target(command: SorCommandRequest) -> str:
    if command.target_external_id is None:
        raise _invalid_command("This Freshdesk action requires an existing ticket.")
    return _path_id(command.target_external_id)


def _path_id(value: object) -> str:
    record_id = _required_id(value, field="Freshdesk resource ID")
    if not record_id.isdecimal():
        raise _invalid_command("Freshdesk resource ID must be numeric.")
    return record_id


def _path_token(value: object) -> str:
    token = _required_id(value, field="Freshdesk record ID")
    if not all(character.isalnum() or character in {"-", "_"} for character in token):
        raise _invalid_command("Freshdesk record ID contains unsupported characters.")
    return token


def _numeric_id(value: object, *, field: str) -> int:
    record_id = _required_id(value, field=field)
    if not record_id.isdecimal():
        raise _invalid_command(f"{field} must be numeric.")
    return int(record_id)


def _status_name(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise _invalid_response("Freshdesk ticket status is invalid.")
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in _STATUS_CODES:
            return normalized
        if normalized.isdecimal():
            value = int(normalized)
        else:
            return normalized
    try:
        status = FreshdeskTicketStatusCode(value)
    except ValueError:
        return str(value)
    return _STATUS_NAMES[status]


def _status_code(value: object) -> FreshdeskTicketStatusCode:
    name = _status_name(value)
    if name is None or name not in _STATUS_CODES:
        raise _invalid_command(
            f"Freshdesk status must be one of: {', '.join(sorted(_STATUS_CODES))}."
        )
    return _STATUS_CODES[name]


def _priority_name(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise _invalid_response("Freshdesk priority is invalid.")
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in _PRIORITY_CODES:
            return normalized
        if normalized.isdecimal():
            value = int(normalized)
        else:
            return normalized
    try:
        priority = FreshdeskTicketPriorityCode(value)
    except ValueError:
        return str(value)
    return _PRIORITY_NAMES[priority]


def _priority_code(value: object) -> FreshdeskTicketPriorityCode:
    name = _priority_name(value)
    if name is None or name not in _PRIORITY_CODES:
        raise _invalid_command(
            f"Freshdesk priority must be one of: {', '.join(sorted(_PRIORITY_CODES))}."
        )
    return _PRIORITY_CODES[name]


def _source_name(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise _invalid_response("Freshdesk ticket source is invalid.")
    if isinstance(value, str) and not value.isdecimal():
        return value.strip().casefold() or None
    code = int(value)
    try:
        source = FreshdeskTicketSourceCode(code)
    except ValueError:
        return str(code)
    return _SOURCE_NAMES[source]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _plain_text(value: object) -> str | None:
    text = _optional_string(value)
    if text is None:
        return None
    if "<" not in text and ">" not in text:
        return text
    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
    except ValueError as error:
        raise _invalid_response("Freshdesk returned invalid HTML content.") from error
    normalized = "\n".join(parser.parts).strip()
    return normalized or None


def _revision(value: datetime | None) -> str | None:
    return _timestamp(value) if value is not None else None


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _request_id(response: SorJsonResponse) -> str | None:
    values = response.header_values("x-request-id") or response.header_values(
        "x-freshdesk-request-id"
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
            f"Freshdesk refused the API key while attempting to {operation}.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    if response.status_code == HTTPStatus.FORBIDDEN:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_FORBIDDEN,
            f"Freshdesk refused permission to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code == HTTPStatus.NOT_FOUND:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESOURCE_UNAVAILABLE,
            f"Freshdesk could not find the resource needed to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code in {HTTPStatus.CONFLICT, HTTPStatus.PRECONDITION_FAILED}:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_REVISION_CONFLICT,
            f"Freshdesk rejected stale state while attempting to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code in {
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.UNPROCESSABLE_CONTENT,
    }:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            f"Freshdesk rejected the data used to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RATE_LIMITED,
            "Freshdesk rate-limited the source.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SERVER_FAILED,
            f"Freshdesk failed while attempting to {operation}.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    raise SorVendorOperationError(
        SorVendorErrorCode.VENDOR_REQUEST_FAILED,
        f"Freshdesk refused the request to {operation}.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _object(value: object, *, field: str = "Freshdesk response") -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _invalid_response(f"{field} must be an object.")
    return dict(value)


def _optional_object(value: object) -> dict[str, object]:
    return {} if value is None else _object(value)


def _object_list(value: object, *, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise _invalid_response(f"{field} must be a list.")
    return [_object(item, field=field) for item in value]


def _string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise _invalid_response(f"{field} must be a string list.")
    return list(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(_string_list(value, field="Freshdesk string list"))


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
    return _required_id(value, field="Freshdesk optional ID")


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1_000_000:
        raise _invalid_response(f"{field} is invalid.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 1_000_000:
        raise _invalid_response("Freshdesk string value is invalid.")
    normalized = value.strip()
    return normalized or None


def _optional_boolean(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise _invalid_response("Freshdesk boolean value is invalid.")
    return value


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid_response("Freshdesk integer value is invalid.")
    return value


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
            raise _invalid_response("Freshdesk timestamp is invalid.") from error
    else:
        raise _invalid_response("Freshdesk timestamp is invalid.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid_response("Freshdesk timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _epoch_millis_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid_response("Freshdesk epoch timestamp is invalid.")
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise _invalid_response("Freshdesk epoch timestamp is invalid.") from error


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _invalid_response("Freshdesk decimal value is invalid.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise _invalid_response("Freshdesk decimal value is invalid.") from error
    if not parsed.is_finite() or parsed.copy_abs() >= Decimal("1e18"):
        raise _invalid_response("Freshdesk decimal value is invalid.")
    return parsed


def _json_value(value: object) -> SorJsonValue:
    try:
        return require_json_value(value)
    except ValueError as error:
        raise _invalid_response("Freshdesk value is not JSON compatible.") from error


def _json_mapping(value: Mapping[str, object]) -> dict[str, SorJsonValue]:
    result = {key: _json_value(item) for key, item in value.items()}
    return result


def _scan_limit() -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_SCAN_LIMIT_EXCEEDED,
        "Freshdesk's 300-page listing limit was reached; narrow or partition the source.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


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


def _invalid_stream(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_STREAM_UNSUPPORTED,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


__all__ = [
    "FRESHDESK_MANIFEST",
    "FreshdeskSupportAdapter",
    "create_freshdesk_adapter",
]
