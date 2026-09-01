"""Intercom adapter for Eylo's conversation-first customer-support profile."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from html.parser import HTMLParser
from http import HTTPStatus
from urllib.parse import urlsplit

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

INTERCOM_API_VERSION = "2.16"
INTERCOM_CURSOR_VERSION = 1
INTERCOM_OVERLAP_SECONDS = 60
INTERCOM_MAX_PARTS = 500
INTERCOM_MAX_EMPTY_EXPANSIONS = 50

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
                _RELATIONSHIP_TARGETS.get(stream_key, {})
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
    required_scopes=_STREAM_SCOPES,
    tool_required_scopes=_TOOL_SCOPES,
    tool_streams=_TOOL_STREAMS,
    mutation_result_streams=_MUTATION_RESULT_STREAMS,
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


@dataclass(frozen=True, slots=True)
class IntercomAppWebhookDelivery:
    """One signed workspace event before source-selection filtering."""

    organization_external_id: str
    signal: SorWebhookSignal


def verify_intercom_app_webhook(
    *,
    headers: Mapping[str, str],
    body: bytes,
    client_secret: str,
) -> None:
    """Authenticate one Intercom app delivery against its raw request bytes."""
    signature = _header(headers, "x-hub-signature")
    if signature is None or not signature.startswith("sha1="):
        raise SorWebhookVerificationError("Intercom webhook signature is missing.")
    expected = (
        "sha1="
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
        data = _object(payload, field="Intercom webhook")
        topic = _required_string(data.get("topic"), field="Intercom webhook topic")
        workspace_id = _required_id(
            data.get("app_id"),
            field="Intercom webhook workspace ID",
        )
        envelope = data.get("data")
        item = (
            _object(envelope.get("item"), field="Intercom webhook item")
            if isinstance(envelope, Mapping) and envelope.get("item") is not None
            else {}
        )
        object_key, external_id = _webhook_identity(topic, item)
        signal = SorWebhookSignal(
            delivery_id=_optional_id(data.get("id")),
            event_type=topic,
            vendor_object_key=object_key,
            external_id=external_id,
            occurred_at=_optional_datetime(data.get("created_at")),
        )
    except SorVendorOperationError as error:
        raise SorWebhookPayloadError(str(error)) from error
    return IntercomAppWebhookDelivery(
        organization_external_id=workspace_id,
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
        _field("normalized_description", "Opening message", SorFieldDataType.TEXT, writable=True),
        _field("requester_external_id", "Contact ID", SorFieldDataType.REFERENCE, writable=True),
        _field("assignee_external_id", "Admin assignee ID", SorFieldDataType.REFERENCE),
        _field("group_external_id", "Team assignee ID", SorFieldDataType.REFERENCE),
        _field("native_status", "State", SorFieldDataType.ENUM, choices=("open", "closed", "snoozed")),
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
        _field("ticket_external_id", "Conversation ID", SorFieldDataType.REFERENCE, nullable=False),
        _field("visibility", "Visibility", SorFieldDataType.ENUM, nullable=False),
        _field("direction", "Direction", SorFieldDataType.ENUM),
        _field("author_external_id", "Author ID", SorFieldDataType.REFERENCE),
        _field("normalized_text", "Message", SorFieldDataType.TEXT, nullable=False),
        _field("source_body", "Source body", SorFieldDataType.BOUNDED_JSON),
        _field("body_format", "Body format", SorFieldDataType.TEXT),
        _field("attachment_external_ids", "Attachment IDs", SorFieldDataType.STRING_ARRAY),
        _field("created_at", "Created at", SorFieldDataType.TIMESTAMP, nullable=False),
        _field("updated_at", "Updated at", SorFieldDataType.TIMESTAMP),
    ),
    IntercomStream.TAGS: (_field("name", "Name", SorFieldDataType.TEXT, nullable=False),),
    IntercomStream.ATTACHMENTS: (
        _field("ticket_external_id", "Conversation ID", SorFieldDataType.REFERENCE, nullable=False),
        _field("message_external_id", "Message ID", SorFieldDataType.REFERENCE),
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("content_type", "Content type", SorFieldDataType.TEXT),
        _field("size_bytes", "Size", SorFieldDataType.INTEGER),
        _field("source_url", "Download URL", SorFieldDataType.LINK),
    ),
}
_STATUS_MAP = {
    "open": SupportTicketState.OPEN,
    "closed": SupportTicketState.CLOSED,
    "snoozed": SupportTicketState.PENDING,
}


@dataclass(frozen=True, slots=True)
class _SearchCursor:
    watermark: int = 0
    starting_after: str | None = None
    max_seen: int = 0
    item_offset: int = 0


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
            response_body_limit=8_388_608,
            default_headers={"Intercom-Version": INTERCOM_API_VERSION},
        )
        self._acting_admin_id: str | None = None

    async def verify_connection(self) -> SorConnectionVerification:
        viewer = await self._current_admin()
        app = _object(viewer.get("app"), field="Intercom workspace")
        region = _required_string(app.get("region"), field="Intercom region").upper()
        expected_region = _ORIGIN_REGIONS[self._origin][1]
        if region != expected_region:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_REGION_MISMATCH,
                "The selected Intercom data region does not match this workspace.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        return SorConnectionVerification(
            account_external_id=_required_id(
                app.get("id_code"), field="Intercom workspace ID"
            ),
            account_display_name=_optional_string(app.get("name"))
            or "Intercom workspace",
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
                "/data_attributes", query={"model": "contact"}
            )
            data = _object(_expect(response, operation="list Intercom contact fields"))
            contact_attributes = _attribute_fields(
                _object_list(data.get("data"), field="Intercom contact fields"),
                writable=False,
            )
        if IntercomStream.CONVERSATIONS in self._context.selected_objects:
            response = await self._client.request("/conversations/attributes")
            data = _object(
                _expect(response, operation="list Intercom conversation fields")
            )
            conversation_attributes = _attribute_fields(
                _object_list(data.get("data"), field="Intercom conversation fields"),
                writable=True,
            )

        streams = {stream.key: stream for stream in INTERCOM_MANIFEST.streams}
        objects: list[SorDiscoveredObject] = []
        for stream_key in self._context.selected_objects:
            _require_stream(stream_key, selected=self._context.selected_objects)
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
                _object(_expect(response, operation="read Intercom contact")),
            )
        if stream_key in {
            IntercomStream.ADMINS,
            IntercomStream.TEAMS,
            IntercomStream.TAGS,
        }:
            rows = await self._reconcile_rows(stream_key)
            row = next(
                (item for item in rows if _optional_id(item.get("id")) == record_id),
                None,
            )
            if row is None:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            return self._external_record(stream_key, row)
        if stream_key == IntercomStream.CONVERSATION_PARTS:
            conversation_id, part_id = _split_expanded_id(record_id)
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
            conversation_id, _message_id, _attachment_id = _split_attachment_id(
                record_id
            )
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
            add=command.tool_name == SupportToolName.ADD_TAG,
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
            name=_required_string(
                payload.name, field="Intercom tag name"
            ),
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
                limit=min(limit, 150),
            )
        if stream_key in {
            IntercomStream.CONVERSATION_PARTS,
            IntercomStream.ATTACHMENTS,
        }:
            return await self._read_expanded_page(
                stream_key=stream_key,
                cursor=cursor,
                limit=min(limit, 500),
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
            conversation_id = _required_id(
                rows[0].get("id"), field="Intercom conversation ID"
            )
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
    ) -> tuple[list[dict[str, object]], str | None, int]:
        lower_bound = max(0, state.watermark - INTERCOM_OVERLAP_SECONDS)
        pagination: dict[str, object] = {"per_page": limit}
        if state.starting_after is not None:
            pagination["starting_after"] = state.starting_after
        response = await self._client.request(
            "/contacts/search"
            if stream_key == IntercomStream.CONTACTS
            else "/conversations/search",
            method="POST",
            payload={
                "query": {
                    "field": "updated_at",
                    "operator": ">",
                    "value": lower_bound,
                },
                "pagination": pagination,
                "sort": {"field": "updated_at", "order": "ascending"},
            },
        )
        data = _object(_expect(response, operation=f"search Intercom {stream_key}"))
        rows = _object_list(
            data.get(
                "data"
                if stream_key == IntercomStream.CONTACTS
                else IntercomStream.CONVERSATIONS
            ),
            field=f"Intercom {stream_key}",
        )
        if len(rows) > limit:
            raise _invalid_response(
                f"Intercom returned more {stream_key} than requested."
            )
        max_seen = max(
            [state.max_seen, state.watermark]
            + [_optional_epoch(row.get("updated_at")) or 0 for row in rows]
        )
        return rows, _next_starting_after(data), max_seen

    async def _read_reconcile_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        offset = _decode_offset_cursor(cursor, stream_key=stream_key)
        rows = sorted(
            await self._reconcile_rows(stream_key),
            key=lambda row: _required_id(row.get("id"), field="Intercom record ID"),
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

    async def _reconcile_rows(self, stream_key: str) -> list[dict[str, object]]:
        endpoint, response_key = {
            IntercomStream.ADMINS: ("/admins", IntercomStream.ADMINS),
            IntercomStream.TEAMS: ("/teams", IntercomStream.TEAMS),
            IntercomStream.TAGS: ("/tags", "data"),
        }[stream_key]
        response = await self._client.request(
            endpoint,
            query={"display_avatar": True}
            if stream_key == IntercomStream.ADMINS
            else None,
        )
        data = _object(_expect(response, operation=f"list Intercom {stream_key}"))
        return _object_list(data.get(response_key), field=f"Intercom {stream_key}")

    async def _conversation(self, conversation_id: str) -> dict[str, object]:
        response = await self._client.request(
            f"/conversations/{_path_id(conversation_id)}",
            query={"display_as": "plaintext"},
        )
        if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
            raise SorExternalRecordNotFound(
                vendor_object_key=IntercomStream.CONVERSATIONS,
                external_id=conversation_id,
            )
        return _object(_expect(response, operation="read Intercom conversation"))

    async def _current_admin(self) -> dict[str, object]:
        response = await self._client.request("/me")
        viewer = _object(_expect(response, operation="identify Intercom admin"))
        self._acting_admin_id = _required_id(
            viewer.get("id"), field="Intercom admin ID"
        )
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
        row: Mapping[str, object],
    ) -> SorExternalRecord:
        if stream_key == IntercomStream.CONVERSATIONS:
            record_id = _required_id(row.get("id"), field="Intercom conversation ID")
            source = _optional_object(row.get("source"))
            statistics = _optional_object(row.get("statistics"))
            sla = _optional_object(row.get("sla_applied"))
            state = _optional_string(row.get("state"))
            contacts = _nested_object_list(
                row.get(IntercomStream.CONTACTS),
                IntercomStream.CONTACTS,
                field="Intercom conversation contacts",
            )
            tags = _nested_object_list(
                row.get(IntercomStream.TAGS),
                IntercomStream.TAGS,
                field="Intercom conversation tags",
            )
            updated_epoch = _optional_epoch(row.get("updated_at"))
            payload: dict[str, object] = {
                "subject": row.get("title") or source.get("subject"),
                "normalized_description": _plain_text(source.get("body")),
                "requester_external_id": (
                    _optional_id(contacts[0].get("id")) if contacts else None
                ),
                "assignee_external_id": _optional_id(row.get("admin_assignee_id")),
                "group_external_id": _optional_id(row.get("team_assignee_id")),
                "native_status": state,
                "normalized_status": _STATUS_MAP.get(state or ""),
                "priority": row.get("priority"),
                "category": source.get("type"),
                "channel": source.get("delivered_as"),
                "tag_external_ids": [
                    tag_id
                    for item in tags
                    if (tag_id := _optional_id(item.get("id"))) is not None
                ],
                "first_response_at": _optional_datetime(
                    statistics.get("first_admin_reply_at")
                ),
                "resolved_at": (
                    _optional_datetime(statistics.get("last_close_at"))
                    if state == "closed"
                    else None
                ),
                "closed_at": (
                    _optional_datetime(statistics.get("last_close_at"))
                    if state == "closed"
                    else None
                ),
                "sla_state": sla.get("sla_status"),
            }
            payload.update(_custom_attribute_values(row.get("custom_attributes")))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload=payload,
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=_epoch_datetime(updated_epoch),
                source_revision=_epoch_revision(updated_epoch),
            )
        if stream_key == IntercomStream.CONTACTS:
            record_id = _required_id(row.get("id"), field="Intercom contact ID")
            companies = _nested_object_list(
                row.get("companies"),
                "data",
                field="Intercom contact companies",
            )
            updated_epoch = _optional_epoch(row.get("updated_at"))
            payload = {
                "name": row.get("name"),
                "primary_email": row.get("email"),
                "primary_phone": row.get("phone"),
                "company_external_id": (
                    _optional_id(companies[0].get("id")) if companies else None
                ),
                "active": None,
            }
            payload.update(_custom_attribute_values(row.get("custom_attributes")))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload=payload,
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=_epoch_datetime(updated_epoch),
                source_revision=_epoch_revision(updated_epoch),
            )
        if stream_key == IntercomStream.ADMINS:
            avatar = _optional_object(row.get("avatar"))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.get("id"), field="Intercom admin ID"),
                payload={
                    "name": row.get("name"),
                    "primary_email": row.get("email"),
                    "active": True,
                    "assignable": row.get("has_inbox_seat"),
                    "avatar_url": _safe_source_url(avatar.get("image_url")),
                },
            )
        if stream_key == IntercomStream.TEAMS:
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.get("id"), field="Intercom team ID"),
                payload={"name": row.get("name"), "description": None, "active": True},
            )
        if stream_key == IntercomStream.TAGS:
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.get("id"), field="Intercom tag ID"),
                payload={"name": row.get("name")},
            )
        if stream_key == IntercomStream.CONVERSATION_PARTS:
            conversation_id = _required_id(
                row.get("_conversation_id"), field="Intercom conversation ID"
            )
            message_id = _required_id(row.get("id"), field="Intercom message ID")
            author = _optional_object(row.get("author"))
            part_type = _required_string(
                row.get("_part_type"), field="Intercom message type"
            )
            created_at = _required_datetime(
                row.get("created_at"), field="Intercom message creation time"
            )
            attachments = _object_list(
                row.get(IntercomStream.ATTACHMENTS) or [],
                field="Intercom message attachments",
            )
            attachment_ids = [
                _attachment_external_id(conversation_id, item) for item in attachments
            ]
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_expanded_id(conversation_id, message_id),
                payload={
                    "ticket_external_id": conversation_id,
                    "visibility": "PRIVATE" if part_type == "note" else "PUBLIC",
                    "direction": _message_direction(author.get("type")),
                    "author_external_id": _optional_id(author.get("id")),
                    "normalized_text": _message_text(row),
                    "source_body": dict(row),
                    "body_format": "text/plain",
                    "attachment_external_ids": attachment_ids,
                    "created_at": created_at,
                    "updated_at": _optional_datetime(row.get("updated_at")),
                },
                source_created_at=created_at,
                source_updated_at=_optional_datetime(row.get("updated_at")),
                source_revision=_epoch_revision(_optional_epoch(row.get("updated_at"))),
            )
        conversation_id = _required_id(
            row.get("_conversation_id"), field="Intercom conversation ID"
        )
        message_id = _required_id(row.get("_message_id"), field="Intercom message ID")
        attachment_id = _required_id(row.get("id"), field="Intercom attachment ID")
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=_attachment_id(
                conversation_id,
                message_id,
                attachment_id,
            ),
            payload={
                "ticket_external_id": conversation_id,
                "message_external_id": _expanded_id(conversation_id, message_id),
                "name": row.get("name"),
                "content_type": row.get("content_type"),
                "size_bytes": row.get("filesize") or row.get("size"),
                "source_url": _safe_source_url(row.get("url")),
            },
            source_url=_safe_source_url(row.get("url")),
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
        requester_id = values.pop("_requester_external_id", None)
        body = values.pop("_normalized_description", None)
        if not isinstance(requester_id, str) or not requester_id:
            raise _invalid_command(
                "Opening an Intercom conversation requires requester_external_id."
            )
        if not isinstance(body, str) or not body.strip():
            raise _invalid_command(
                "Opening an Intercom conversation requires normalized_description."
            )
        response = await self._mutation_request(
            "/conversations",
            method="POST",
            payload={
                "from": {"type": "contact", "id": requester_id},
                "body": body.strip(),
            },
            operation="open an Intercom conversation",
        )
        message = _object(_expect(response, operation="open an Intercom conversation"))
        conversation_id = _required_id(
            message.get("conversation_id"), field="Intercom conversation ID"
        )
        if values:
            await self._mutation_request(
                f"/conversations/{_path_id(conversation_id)}",
                method="PUT",
                payload=values,
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
        unsupported = {key for key in values if key.startswith("_")}
        if unsupported:
            raise _invalid_command(
                "Intercom cannot update a conversation requester or opening message."
            )
        if not values:
            raise _invalid_command(
                "Updating an Intercom conversation requires mapped fields."
            )
        response = await self._mutation_request(
            f"/conversations/{_path_id(conversation_id)}",
            method="PUT",
            payload=values,
            operation="update an Intercom conversation",
        )
        data = _object(_expect(response, operation="update an Intercom conversation"))
        return self._conversation_result(data, response=response)

    async def _assign_conversation(
        self,
        conversation_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportAssignCommandPayload):
            raise _invalid_command("Intercom assignment payload is invalid.")
        admin_id = await self._admin_id()
        response: SorJsonResponse | None = None
        data: dict[str, object] | None = None
        for raw_assignee_id, assignee_type in (
            (command.payload.group_external_id, "team"),
            (command.payload.assignee_external_id, "admin"),
        ):
            if raw_assignee_id is None:
                continue
            assignee_id = _required_id(
                raw_assignee_id,
                field=f"Intercom {assignee_type} assignee ID",
            )
            response = await self._mutation_request(
                f"/conversations/{_path_id(conversation_id)}/parts",
                method="POST",
                payload={
                    "message_type": "assignment",
                    "type": assignee_type,
                    "admin_id": admin_id,
                    "assignee_id": assignee_id,
                },
                operation="assign an Intercom conversation",
            )
            data = _object(
                _expect(response, operation="assign an Intercom conversation")
            )
        if response is None or data is None:
            raise _invalid_command("Intercom assignment contains no assignee.")
        return self._conversation_result(data, response=response)

    async def _reply(
        self,
        conversation_id: str,
        command: SorCommandRequest,
        *,
        visibility: SupportMessageVisibility,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportMessageCommandPayload):
            raise _invalid_command("Intercom message payload is invalid.")
        text = command.payload.normalized_text
        response = await self._mutation_request(
            f"/conversations/{_path_id(conversation_id)}/reply",
            method="POST",
            payload={
                "type": "admin",
                "admin_id": await self._admin_id(),
                "message_type": (
                    "comment"
                    if visibility is SupportMessageVisibility.PUBLIC
                    else "note"
                ),
                "body": text,
            },
            operation=(
                "reply to an Intercom conversation"
                if visibility is SupportMessageVisibility.PUBLIC
                else "add an Intercom private note"
            ),
        )
        conversation = _object(
            _expect(response, operation="write an Intercom conversation message")
        )
        part = _latest_message_part(conversation, visibility=visibility)
        part_id = _required_id(part.get("id"), field="Intercom message ID")
        return SorCommandResult(
            vendor_object_key=IntercomStream.CONVERSATION_PARTS,
            external_id=_expanded_id(conversation_id, part_id),
            external_request_id=_request_id(response),
            source_revision=_epoch_revision(
                _optional_epoch(conversation.get("updated_at"))
            ),
            response={
                "status": "accepted",
                "visibility": visibility.value,
            },
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
        payload: dict[str, object] = {
            "message_type": "close",
            "type": "admin",
            "admin_id": await self._admin_id(),
        }
        if command.payload.normalized_text is not None:
            payload["body"] = command.payload.normalized_text
        response = await self._mutation_request(
            f"/conversations/{_path_id(conversation_id)}/parts",
            method="POST",
            payload=payload,
            operation="close an Intercom conversation",
        )
        data = _object(_expect(response, operation="close an Intercom conversation"))
        return self._conversation_result(data, response=response)

    async def _change_tag(
        self,
        conversation_id: str,
        command: SorCommandRequest,
        *,
        add: bool,
    ) -> SorCommandResult:
        if not isinstance(command.payload, SupportTagCommandPayload):
            raise _invalid_command("Intercom tag payload is invalid.")
        tag_id = _required_id(
            command.payload.tag_external_id,
            field="Intercom tag ID",
        )
        path = f"/conversations/{_path_id(conversation_id)}/tags"
        if not add:
            path = f"{path}/{_path_id(tag_id)}"
        response = await self._mutation_request(
            path,
            method="POST" if add else "DELETE",
            payload={
                "id": tag_id,
                "admin_id": await self._admin_id(),
            }
            if add
            else {"admin_id": await self._admin_id()},
            operation="change an Intercom conversation tag",
        )
        _expect(response, operation="change an Intercom conversation tag")
        return SorCommandResult(
            vendor_object_key=IntercomStream.CONVERSATIONS,
            external_id=conversation_id,
            external_request_id=_request_id(response),
            response={"status": "accepted"},
        )

    def _ticket_write_values(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
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
        for agent_key, value in payload.items():
            vendor_key = writable[agent_key]
            if vendor_key == "subject":
                values["title"] = value
            elif vendor_key == "requester_external_id":
                values["_requester_external_id"] = _required_id(
                    value, field="Intercom requester ID"
                )
            elif vendor_key == "normalized_description":
                values["_normalized_description"] = _required_string(
                    value, field="Intercom opening message"
                )
            elif vendor_key.startswith("custom_attribute:"):
                custom[_custom_attribute_name(vendor_key)] = value
            else:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_FIELD_NOT_WRITABLE,
                    "The mapped Intercom field is not writable by this adapter.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                )
        if custom:
            values["custom_attributes"] = custom
        return values

    async def _mutation_request(
        self,
        path: str,
        *,
        method: str,
        payload: object,
        operation: str,
    ) -> SorJsonResponse:
        try:
            response = await self._client.request(
                path,
                method=method,
                payload=payload,
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

    def _conversation_result(
        self,
        conversation: Mapping[str, object],
        *,
        response: SorJsonResponse,
    ) -> SorCommandResult:
        conversation_id = _required_id(
            conversation.get("id"), field="Intercom conversation ID"
        )
        updated_epoch = _optional_epoch(conversation.get("updated_at"))
        return SorCommandResult(
            vendor_object_key=IntercomStream.CONVERSATIONS,
            external_id=conversation_id,
            external_request_id=_request_id(response),
            source_revision=_epoch_revision(updated_epoch),
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


def _require_stream(stream_key: str, *, selected: Sequence[str]) -> str:
    if stream_key not in _STREAM_ENTITY or stream_key not in selected:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNAVAILABLE,
            "The requested Intercom stream is not selected for this source.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return stream_key


def _attribute_fields(
    attributes: Sequence[Mapping[str, object]],
    *,
    writable: bool,
) -> tuple[SorDiscoveredField, ...]:
    result: list[SorDiscoveredField] = []
    for attribute in attributes:
        name = _required_string(
            attribute.get("name") or attribute.get("full_name"),
            field="Intercom attribute name",
        )
        native_type = (
            _optional_string(attribute.get("data_type")) or "string"
        ).casefold()
        result.append(
            _field(
                _custom_attribute_key(name),
                _optional_string(attribute.get("label")) or name,
                {
                    "boolean": "boolean",
                    "date": "timestamp",
                    "datetime": "timestamp",
                    "float": "decimal",
                    "integer": "integer",
                    "list": "bounded_json",
                    "object": "bounded_json",
                }.get(native_type, "text"),
                writable=writable,
                description=_optional_string(attribute.get("description")),
            )
        )
    return tuple(sorted(result, key=lambda item: item.key))


def _custom_attribute_key(name: str) -> str:
    encoded = base64.urlsafe_b64encode(name.encode()).decode().rstrip("=")
    return f"custom_attribute:{encoded}"


def _custom_attribute_name(key: str) -> str:
    prefix = "custom_attribute:"
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


def _custom_attribute_values(value: object) -> dict[str, object]:
    attributes = _optional_object(value)
    result: dict[str, object] = {}
    for name, item in attributes.items():
        if not name:
            raise _invalid_response("Intercom custom attribute name is empty.")
        result[_custom_attribute_key(name)] = item
    return result


def _encode_search_cursor(state: _SearchCursor, *, stream_key: str) -> str:
    return _encode_cursor(
        {
            "v": INTERCOM_CURSOR_VERSION,
            "stream": stream_key,
            "watermark": state.watermark,
            "starting_after": state.starting_after,
            "max_seen": state.max_seen,
            "item_offset": state.item_offset,
        }
    )


def _decode_search_cursor(value: str | None, *, stream_key: str) -> _SearchCursor:
    if value is None:
        return _SearchCursor()
    data = _decode_cursor(value)
    if set(data) != {
        "v",
        "stream",
        "watermark",
        "starting_after",
        "max_seen",
        "item_offset",
    }:
        raise _invalid_cursor()
    watermark = data.get("watermark")
    max_seen = data.get("max_seen")
    item_offset = data.get("item_offset")
    starting_after = data.get("starting_after")
    if (
        data.get("v") != INTERCOM_CURSOR_VERSION
        or data.get("stream") != stream_key
        or not isinstance(watermark, int)
        or isinstance(watermark, bool)
        or watermark < 0
        or not isinstance(max_seen, int)
        or isinstance(max_seen, bool)
        or max_seen < watermark
        or not isinstance(item_offset, int)
        or isinstance(item_offset, bool)
        or item_offset < 0
        or (
            starting_after is not None
            and (
                not isinstance(starting_after, str)
                or not 1 <= len(starting_after) <= 2_048
            )
        )
    ):
        raise _invalid_cursor()
    return _SearchCursor(
        watermark=watermark,
        starting_after=starting_after,
        max_seen=max_seen,
        item_offset=item_offset,
    )


def _encode_offset_cursor(offset: int, *, stream_key: str) -> str:
    return _encode_cursor(
        {"v": INTERCOM_CURSOR_VERSION, "stream": stream_key, "offset": offset}
    )


def _decode_offset_cursor(value: str | None, *, stream_key: str) -> int:
    if value is None:
        return 0
    data = _decode_cursor(value)
    offset = data.get("offset")
    if (
        set(data) != {"v", "stream", "offset"}
        or data.get("v") != INTERCOM_CURSOR_VERSION
        or data.get("stream") != stream_key
        or not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
    ):
        raise _invalid_cursor()
    return offset


def _encode_cursor(data: Mapping[str, object]) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> dict[str, object]:
    if not value or len(value) > 4_096:
        raise _invalid_cursor()
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        decoded = json.loads(raw)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid_cursor() from error
    return _object(decoded, field="Intercom cursor")


def _invalid_cursor() -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_CURSOR_INVALID,
        "The Intercom cursor is invalid or belongs to another stream.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _next_starting_after(data: Mapping[str, object]) -> str | None:
    pages = data.get("pages")
    if pages is None:
        return None
    page_data = _object(pages, field="Intercom pagination")
    next_page = page_data.get("next")
    if next_page is None:
        return None
    if isinstance(next_page, Mapping):
        return _required_string(
            next_page.get("starting_after"),
            field="Intercom next cursor",
        )
    if isinstance(next_page, str):
        parsed = urlsplit(next_page)
        if not parsed.query:
            return _required_string(next_page, field="Intercom next cursor")
        for pair in parsed.query.split("&"):
            name, separator, raw_value = pair.partition("=")
            if separator and name == "starting_after":
                from urllib.parse import unquote

                return _required_string(
                    unquote(raw_value), field="Intercom next cursor"
                )
    raise _invalid_response("Intercom returned an invalid next cursor.")


def _message_rows(conversation: Mapping[str, object]) -> list[dict[str, object]]:
    conversation_id = _required_id(
        conversation.get("id"), field="Intercom conversation ID"
    )
    result: list[dict[str, object]] = []
    source = _optional_object(conversation.get("source"))
    if _has_message_content(source):
        opening = dict(source)
        opening["_conversation_id"] = conversation_id
        opening["_part_type"] = "comment"
        opening["created_at"] = source.get("created_at") or conversation.get(
            "created_at"
        )
        opening["updated_at"] = conversation.get("updated_at")
        opening[IntercomStream.ATTACHMENTS] = _annotated_attachments(
            opening.get(IntercomStream.ATTACHMENTS),
            conversation_id=conversation_id,
            message_id=_required_id(opening.get("id"), field="Intercom message ID"),
        )
        result.append(opening)
    parts = _optional_object(conversation.get(IntercomStream.CONVERSATION_PARTS))
    for raw_part in _object_list(
        parts.get(IntercomStream.CONVERSATION_PARTS) or [],
        field="Intercom conversation parts",
    ):
        part_type = _optional_string(raw_part.get("part_type"))
        if part_type not in {"comment", "note"} or not _has_message_content(raw_part):
            continue
        part = dict(raw_part)
        part["_conversation_id"] = conversation_id
        part["_part_type"] = part_type
        part[IntercomStream.ATTACHMENTS] = _annotated_attachments(
            part.get(IntercomStream.ATTACHMENTS),
            conversation_id=conversation_id,
            message_id=_required_id(part.get("id"), field="Intercom message ID"),
        )
        result.append(part)
    return sorted(
        result,
        key=lambda item: (
            _optional_epoch(item.get("created_at")) or 0,
            _required_id(item.get("id"), field="Intercom message ID"),
        ),
    )


def _has_message_content(row: Mapping[str, object]) -> bool:
    if _plain_text(row.get("body")):
        return True
    attachments = row.get(IntercomStream.ATTACHMENTS)
    return isinstance(attachments, list) and bool(attachments)


def _message_text(row: Mapping[str, object]) -> str:
    body = _plain_text(row.get("body"))
    if body:
        return body
    attachments = _object_list(
        row.get(IntercomStream.ATTACHMENTS) or [],
        field="Intercom message attachments",
    )
    names = [
        _optional_string(item.get("name")) or "unnamed file" for item in attachments
    ]
    if names:
        return "\n".join(f"[Attachment: {name}]" for name in names)
    raise _invalid_response("Intercom message has no readable content.")


def _attachment_rows(conversation: Mapping[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for message in _message_rows(conversation):
        result.extend(
            _object_list(
                message.get(IntercomStream.ATTACHMENTS) or [],
                field="Intercom message attachments",
            )
        )
    return result


def _annotated_attachments(
    value: object,
    *,
    conversation_id: str,
    message_id: str,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for raw in _object_list(value or [], field="Intercom message attachments"):
        item = dict(raw)
        item["_conversation_id"] = conversation_id
        item["_message_id"] = message_id
        result.append(item)
    return result


def _require_complete_parts(conversation: Mapping[str, object]) -> None:
    parts = _optional_object(conversation.get(IntercomStream.CONVERSATION_PARTS))
    rows = _object_list(
        parts.get(IntercomStream.CONVERSATION_PARTS) or [],
        field="Intercom conversation parts",
    )
    total = _optional_integer(parts.get("total_count"))
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
    conversation: Mapping[str, object],
    *,
    visibility: SupportMessageVisibility,
) -> dict[str, object]:
    expected = "comment" if visibility is SupportMessageVisibility.PUBLIC else "note"
    parts = _optional_object(conversation.get(IntercomStream.CONVERSATION_PARTS))
    rows = _object_list(
        parts.get(IntercomStream.CONVERSATION_PARTS) or [],
        field="Intercom conversation parts",
    )
    for part in reversed(rows):
        if _optional_string(part.get("part_type")) == expected:
            return part
    raise _invalid_response("Intercom omitted the written conversation message.")


def _webhook_identity(
    topic: str,
    item: Mapping[str, object],
) -> tuple[str | None, str | None]:
    lowered = topic.casefold()
    if lowered.startswith("contact.") or lowered.startswith("user."):
        return IntercomStream.CONTACTS, _optional_id(item.get("id"))
    if lowered.startswith("conversation."):
        direct = _optional_id(item.get("conversation_id"))
        if direct is None:
            conversation = _optional_object(item.get("conversation"))
            direct = _optional_id(conversation.get("id"))
        if direct is None and _optional_string(item.get("type")) == "conversation":
            direct = _optional_id(item.get("id"))
        return IntercomStream.CONVERSATIONS, direct
    return None, None


def _expanded_id(conversation_id: str, message_id: str) -> str:
    return f"{conversation_id}:{message_id}"


def _message_external_id(
    conversation_id: str,
    row: Mapping[str, object],
) -> str:
    return _expanded_id(
        conversation_id,
        _required_id(row.get("id"), field="Intercom message ID"),
    )


def _split_expanded_id(value: str) -> tuple[str, str]:
    conversation_id, separator, message_id = value.partition(":")
    if not separator or not conversation_id or not message_id or ":" in message_id:
        raise _invalid_command("Intercom message identity is invalid.")
    return conversation_id, message_id


def _attachment_id(
    conversation_id: str,
    message_id: str,
    attachment_id: str,
) -> str:
    return f"{conversation_id}:{message_id}:{attachment_id}"


def _attachment_external_id(
    conversation_id: str,
    row: Mapping[str, object],
) -> str:
    return _attachment_id(
        conversation_id,
        _required_id(row.get("_message_id"), field="Intercom message ID"),
        _required_id(row.get("id"), field="Intercom attachment ID"),
    )


def _split_attachment_id(value: str) -> tuple[str, str, str]:
    parts = value.split(":")
    if len(parts) != 3 or any(not part for part in parts):
        raise _invalid_command("Intercom attachment identity is invalid.")
    return parts[0], parts[1], parts[2]


def _message_direction(value: object) -> str | None:
    author_type = _optional_string(value)
    if author_type in {"contact", "lead", "user", "visitor"}:
        return "INBOUND"
    if author_type in {"admin", "bot", "team"}:
        return "OUTBOUND"
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


def _object(value: object, *, field: str = "Intercom response") -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _invalid_response(f"{field} must be an object.")
    return dict(value)


def _optional_object(value: object) -> dict[str, object]:
    if value is None:
        return {}
    return _object(value)


def _object_list(value: object, *, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise _invalid_response(f"{field} must be a list.")
    return [_object(item, field=field) for item in value]


def _nested_object_list(
    value: object,
    key: str,
    *,
    field: str,
) -> list[dict[str, object]]:
    container = _optional_object(value)
    return _object_list(container.get(key) or [], field=field)


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


def _path_id(value: str) -> str:
    normalized = _required_id(value, field="Intercom path identity")
    if any(character in normalized for character in "/\\?#%") or normalized in {
        ".",
        "..",
    }:
        raise _invalid_command("Intercom path identity is invalid.")
    return normalized


def _optional_boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


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


def _json_value(value: object) -> object | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise _invalid_response("Intercom value is not JSON-compatible.")


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
