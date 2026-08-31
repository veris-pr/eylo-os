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
from html.parser import HTMLParser
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
    SorOAuthOriginOption,
    SorOAuthSpec,
    SorProfile,
    SorRecordPage,
    SorVendorOperationError,
    SorVendorStreamSpec,
    SorWebhookSignal,
    SorWebhookSubscription,
)
from eylo.sor.support.contracts import (
    SupportAgent,
    SupportAttachment,
    SupportCustomer,
    SupportInbox,
    SupportMessage,
    SupportQueue,
    SupportSlaMetric,
    SupportTag,
    SupportTicket,
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
_STREAM_ENTITY = {
    "conversations": "ticket",
    "contacts": "customer",
    "admins": "agent",
    "teams": "queue",
    "conversation_parts": "message",
    "tags": "tag",
    "attachments": "attachment",
}
_RELATIONSHIP_TARGETS = {
    "conversations": {
        "requester": "contacts",
        "assignee": "admins",
        "queue": "teams",
        "tag": "tags",
    },
    "conversation_parts": {"ticket": "conversations"},
    "attachments": {
        "ticket": "conversations",
        "message": "conversation_parts",
    },
}
_READ_TOOLS = frozenset(
    {
        "support_find_customer",
        "support_find_ticket",
        "support_get_ticket",
        "support_get_customer_history",
        "support_list_queues",
        "support_describe_ticket_fields",
    }
)
_WRITE_TOOLS = frozenset(
    {
        "support_open_ticket",
        "support_update_ticket",
        "support_assign_ticket",
        "support_reply",
        "support_add_note",
        "support_close_ticket",
        "support_add_tag",
        "support_remove_tag",
    }
)
_TOOL_STREAMS = {
    "support_find_customer": frozenset({"contacts"}),
    "support_find_ticket": frozenset({"conversations"}),
    "support_get_ticket": frozenset({"conversations", "conversation_parts"}),
    "support_get_customer_history": frozenset({"contacts", "conversations"}),
    "support_list_queues": frozenset({"teams"}),
    "support_describe_ticket_fields": frozenset({"conversations"}),
    "support_open_ticket": frozenset({"conversations"}),
    "support_update_ticket": frozenset({"conversations"}),
    "support_assign_ticket": frozenset({"conversations", "admins", "teams"}),
    "support_reply": frozenset({"conversations", "conversation_parts"}),
    "support_add_note": frozenset({"conversations", "conversation_parts"}),
    "support_close_ticket": frozenset({"conversations"}),
    "support_add_tag": frozenset({"conversations", "tags"}),
    "support_remove_tag": frozenset({"conversations", "tags"}),
}
_MUTATION_RESULT_STREAMS = {
    **{name: "conversations" for name in _WRITE_TOOLS},
    "support_reply": "conversation_parts",
    "support_add_note": "conversation_parts",
}
_STREAM_SCOPES = {
    "conversations": (READ_CONVERSATIONS,),
    "contacts": (READ_USERS,),
    "admins": (READ_ADMINS,),
    "teams": (READ_ADMINS,),
    "conversation_parts": (READ_CONVERSATIONS,),
    "tags": (READ_TAGS,),
    "attachments": (READ_CONVERSATIONS,),
}
_TOOL_SCOPES = {
    "support_find_customer": (READ_USERS,),
    "support_find_ticket": (READ_CONVERSATIONS,),
    "support_get_ticket": (READ_CONVERSATIONS,),
    "support_get_customer_history": (READ_USERS, READ_CONVERSATIONS),
    "support_list_queues": (READ_ADMINS,),
    "support_describe_ticket_fields": (READ_CONVERSATIONS,),
    "support_open_ticket": (WRITE_CONVERSATIONS,),
    "support_update_ticket": (WRITE_CONVERSATIONS,),
    "support_assign_ticket": (WRITE_CONVERSATIONS, READ_ADMINS),
    "support_reply": (WRITE_CONVERSATIONS, READ_ADMINS),
    "support_add_note": (WRITE_CONVERSATIONS, READ_ADMINS),
    "support_close_ticket": (WRITE_CONVERSATIONS, READ_ADMINS),
    "support_add_tag": (WRITE_CONVERSATIONS, WRITE_TAGS, READ_ADMINS),
    "support_remove_tag": (WRITE_CONVERSATIONS, WRITE_TAGS, READ_ADMINS),
}


INTERCOM_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.SUPPORT,
    vendor_key="intercom",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                "conversations": "Conversations",
                "contacts": "Contacts",
                "admins": "Admins",
                "teams": "Teams",
                "conversation_parts": "Conversation messages",
                "tags": "Tags",
                "attachments": "Conversation attachments",
            }[stream_key],
            description={
                "conversations": "Intercom conversations represented as support cases.",
                "contacts": "People who open and participate in conversations.",
                "admins": "Workspace teammates who may act on conversations.",
                "teams": "Inbox teams used as canonical support queues.",
                "conversation_parts": "Customer-visible replies and private notes.",
                "tags": "Workspace tags available for conversation classification.",
                "attachments": "Metadata for files attached to conversation messages.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=(
                frozenset({SorChangeStrategy.UPDATED_AT})
                if stream_key
                in {"conversations", "contacts", "conversation_parts", "attachments"}
                else frozenset({SorChangeStrategy.FULL_RECONCILE})
            ),
            depends_on=frozenset(
                set(_RELATIONSHIP_TARGETS.get(stream_key, {}).values())
                - {stream_key}
            ),
            relationship_targets=_RELATIONSHIP_TARGETS.get(stream_key, {}),
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
    change_mode=SorChangeMode.OPERATOR_WEBHOOK,
    supports_custom_fields=True,
    supports_history=False,
    supports_comments=True,
    supports_attachments=True,
)


def _field(
    key: str,
    label: str,
    data_type: str,
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
    "conversations": (
        _field("subject", "Title", "text", writable=True),
        _field("normalized_description", "Opening message", "text", writable=True),
        _field("requester_external_id", "Contact ID", "reference", writable=True),
        _field("assignee_external_id", "Admin assignee ID", "reference"),
        _field("group_external_id", "Team assignee ID", "reference"),
        _field("native_status", "State", "enum", choices=("open", "closed", "snoozed")),
        _field("normalized_status", "Normalized state", "enum"),
        _field("priority", "Priority", "enum"),
        _field("category", "Source type", "text"),
        _field("channel", "Delivery channel", "text"),
        _field("tag_external_ids", "Tag IDs", "string_array"),
        _field("first_response_at", "First admin reply", "timestamp"),
        _field("resolved_at", "Resolved at", "timestamp"),
        _field("closed_at", "Closed at", "timestamp"),
        _field("sla_state", "SLA state", "text"),
    ),
    "contacts": (
        _field("name", "Name", "text"),
        _field("primary_email", "Email", "text"),
        _field("primary_phone", "Phone", "text"),
        _field("company_external_id", "Company ID", "reference"),
        _field("active", "Active", "boolean"),
    ),
    "admins": (
        _field("name", "Name", "text", nullable=False),
        _field("primary_email", "Email", "text"),
        _field("active", "Active", "boolean"),
        _field("assignable", "Has inbox seat", "boolean"),
        _field("avatar_url", "Avatar URL", "link"),
    ),
    "teams": (
        _field("name", "Name", "text", nullable=False),
        _field("description", "Description", "text"),
        _field("active", "Active", "boolean"),
    ),
    "conversation_parts": (
        _field("ticket_external_id", "Conversation ID", "reference", nullable=False),
        _field("visibility", "Visibility", "enum", nullable=False),
        _field("direction", "Direction", "enum"),
        _field("author_external_id", "Author ID", "reference"),
        _field("normalized_text", "Message", "text", nullable=False),
        _field("source_body", "Source body", "bounded_json"),
        _field("body_format", "Body format", "text"),
        _field("attachment_external_ids", "Attachment IDs", "string_array"),
        _field("created_at", "Created at", "timestamp", nullable=False),
        _field("updated_at", "Updated at", "timestamp"),
    ),
    "tags": (_field("name", "Name", "text", nullable=False),),
    "attachments": (
        _field("ticket_external_id", "Conversation ID", "reference", nullable=False),
        _field("message_external_id", "Message ID", "reference"),
        _field("name", "Name", "text", nullable=False),
        _field("content_type", "Content type", "text"),
        _field("size_bytes", "Size", "integer"),
        _field("source_url", "Download URL", "link"),
    ),
}
_STATUS_MAP = {"open": "OPEN", "closed": "CLOSED", "snoozed": "PENDING"}


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
                "vendor_region_mismatch",
                "The selected Intercom data region does not match this workspace.",
                retryable=False,
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
                "source_selection_empty",
                "The Intercom source selects no streams.",
                retryable=False,
            )
        contact_attributes: tuple[SorDiscoveredField, ...] = ()
        conversation_attributes: tuple[SorDiscoveredField, ...] = ()
        if "contacts" in self._context.selected_objects:
            response = await self._client.request(
                "/data_attributes", query={"model": "contact"}
            )
            data = _object(_expect(response, operation="list Intercom contact fields"))
            contact_attributes = _attribute_fields(
                _object_list(data.get("data"), field="Intercom contact fields"),
                writable=False,
            )
        if "conversations" in self._context.selected_objects:
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
            if stream_key == "contacts":
                fields = (*fields, *contact_attributes)
            elif stream_key == "conversations":
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
        if stream_key == "conversations":
            return self._external_record(
                stream_key,
                await self._conversation(record_id),
            )
        if stream_key == "contacts":
            response = await self._client.request(f"/contacts/{_path_id(record_id)}")
            if response.status_code in {404, 410}:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            return self._external_record(
                stream_key,
                _object(_expect(response, operation="read Intercom contact")),
            )
        if stream_key in {"admins", "teams", "tags"}:
            rows = await self._reconcile_rows(stream_key)
            row = next(
                (
                    item
                    for item in rows
                    if _optional_id(item.get("id")) == record_id
                ),
                None,
            )
            if row is None:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            return self._external_record(stream_key, row)
        if stream_key == "conversation_parts":
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
        raise SorCapabilityUnavailable(
            "Remove the Intercom webhook in Developer Hub."
        )

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
        signature = _header(headers, "x-hub-signature")
        if signature is None or not signature.startswith("sha1="):
            raise SorVendorOperationError(
                "vendor_webhook_unsigned",
                "Intercom webhook signature is missing.",
                retryable=False,
            )
        expected = "sha1=" + hmac.new(
            secret.encode(),
            body,
            hashlib.sha1,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise SorVendorOperationError(
                "vendor_webhook_invalid",
                "Intercom webhook signature is invalid.",
                retryable=False,
            )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SorVendorOperationError(
                "vendor_webhook_invalid",
                "Intercom webhook body is not valid JSON.",
                retryable=False,
            ) from error
        data = _object(payload, field="Intercom webhook")
        topic = _required_string(data.get("topic"), field="Intercom webhook topic")
        envelope = data.get("data")
        item = (
            _object(envelope.get("item"), field="Intercom webhook item")
            if isinstance(envelope, Mapping) and envelope.get("item") is not None
            else {}
        )
        object_key, external_id = _webhook_identity(topic, item)
        return (
            SorWebhookSignal(
                delivery_id=_optional_id(data.get("id")),
                event_type=topic,
                vendor_object_key=object_key,
                external_id=external_id,
                occurred_at=_optional_datetime(data.get("created_at")),
            ),
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise SorVendorOperationError(
                "vendor_tool_unsupported",
                "This Intercom adapter does not execute the requested support action.",
                retryable=False,
            )
        if command.tool_name == "support_open_ticket":
            return await self._open_conversation(command)
        conversation_id = _required_target(command)
        if command.tool_name == "support_update_ticket":
            return await self._update_conversation(conversation_id, command)
        if command.tool_name == "support_assign_ticket":
            return await self._assign_conversation(conversation_id, command)
        if command.tool_name in {"support_reply", "support_add_note"}:
            return await self._reply(
                conversation_id,
                command,
                public=command.tool_name == "support_reply",
            )
        if command.tool_name == "support_close_ticket":
            return await self._close_conversation(conversation_id, command)
        return await self._change_tag(
            conversation_id,
            command,
            add=command.tool_name == "support_add_tag",
        )

    def normalize_ticket(self, record: SorExternalRecord) -> SupportTicket:
        values = record.payload
        return SupportTicket(
            external_id=record.external_id,
            subject=_optional_string(values.get("subject")),
            normalized_description=_optional_string(
                values.get("normalized_description")
            ),
            requester_external_id=_optional_string(
                values.get("requester_external_id")
            ),
            assignee_external_id=_optional_string(values.get("assignee_external_id")),
            group_external_id=_optional_string(values.get("group_external_id")),
            inbox_external_id=None,
            native_status=_optional_string(values.get("native_status")),
            normalized_status=_optional_string(values.get("normalized_status")),
            priority=_optional_string(values.get("priority")),
            category=_optional_string(values.get("category")),
            channel=_optional_string(values.get("channel")),
            tag_external_ids=_string_tuple(values.get("tag_external_ids")),
            first_response_at=_optional_datetime(values.get("first_response_at")),
            resolved_at=_optional_datetime(values.get("resolved_at")),
            closed_at=_optional_datetime(values.get("closed_at")),
            sla_state=_optional_string(values.get("sla_state")),
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
            custom_fields={
                key: value
                for key, value in values.items()
                if key.startswith("custom_attribute:")
            },
        )

    def normalize_customer(self, record: SorExternalRecord) -> SupportCustomer:
        values = record.payload
        return SupportCustomer(
            external_id=record.external_id,
            name=_optional_string(values.get("name")),
            primary_email=_optional_string(values.get("primary_email")),
            primary_phone=_optional_string(values.get("primary_phone")),
            company_external_id=_optional_string(values.get("company_external_id")),
            active=_optional_boolean(values.get("active")),
            source_url=record.source_url,
            custom_fields={
                key: value
                for key, value in values.items()
                if key.startswith("custom_attribute:")
            },
        )

    def normalize_agent(self, record: SorExternalRecord) -> SupportAgent:
        values = record.payload
        return SupportAgent(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="Intercom admin name"),
            primary_email=_optional_string(values.get("primary_email")),
            active=_optional_boolean(values.get("active")),
            assignable=_optional_boolean(values.get("assignable")),
            avatar_url=_optional_string(values.get("avatar_url")),
        )

    def normalize_message(self, record: SorExternalRecord) -> SupportMessage:
        values = record.payload
        return SupportMessage(
            external_id=record.external_id,
            ticket_external_id=_required_string(
                values.get("ticket_external_id"), field="Intercom conversation ID"
            ),
            visibility=_required_string(
                values.get("visibility"), field="Intercom message visibility"
            ),
            direction=_optional_string(values.get("direction")),
            author_external_id=_optional_string(values.get("author_external_id")),
            normalized_text=_required_string(
                values.get("normalized_text"), field="Intercom message text"
            ),
            source_body=_json_value(values.get("source_body")),
            body_format=_optional_string(values.get("body_format")),
            attachment_external_ids=_string_tuple(
                values.get("attachment_external_ids")
            ),
            created_at=_required_datetime(
                values.get("created_at"), field="Intercom message creation time"
            ),
            updated_at=_optional_datetime(values.get("updated_at")),
        )

    def normalize_queue(self, record: SorExternalRecord) -> SupportQueue:
        values = record.payload
        return SupportQueue(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="Intercom team name"),
            description=_optional_string(values.get("description")),
            active=_optional_boolean(values.get("active")),
        )

    def normalize_inbox(self, record: SorExternalRecord) -> SupportInbox:
        raise SorCapabilityUnavailable(
            "Intercom inboxes are not a selected canonical stream."
        )

    def normalize_tag(self, record: SorExternalRecord) -> SupportTag:
        return SupportTag(
            external_id=record.external_id,
            name=_required_string(record.payload.get("name"), field="Intercom tag name"),
        )

    def normalize_sla_metric(self, record: SorExternalRecord) -> SupportSlaMetric:
        raise SorCapabilityUnavailable(
            "Intercom SLA metrics are summarized on conversations in this revision."
        )

    def normalize_attachment(self, record: SorExternalRecord) -> SupportAttachment:
        values = record.payload
        return SupportAttachment(
            external_id=record.external_id,
            ticket_external_id=_required_string(
                values.get("ticket_external_id"), field="Intercom conversation ID"
            ),
            message_external_id=_optional_string(values.get("message_external_id")),
            name=_required_string(
                values.get("name"), field="Intercom attachment name"
            ),
            content_type=_optional_string(values.get("content_type")),
            size_bytes=_optional_integer(values.get("size_bytes")),
            source_url=_optional_string(values.get("source_url")),
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
                "vendor_page_invalid",
                "Intercom page limit must be positive.",
                retryable=False,
            )
        if stream_key in {"conversations", "contacts"}:
            return await self._read_search_page(
                stream_key=stream_key,
                cursor=cursor,
                limit=min(limit, 150),
            )
        if stream_key in {"conversation_parts", "attachments"}:
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
                stream_key="conversations",
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
                if stream_key == "conversation_parts"
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
            if stream_key == "contacts"
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
        data = _object(
            _expect(response, operation=f"search Intercom {stream_key}")
        )
        rows = _object_list(
            data.get("data" if stream_key == "contacts" else "conversations"),
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
            "admins": ("/admins", "admins"),
            "teams": ("/teams", "teams"),
            "tags": ("/tags", "data"),
        }[stream_key]
        response = await self._client.request(
            endpoint,
            query={"display_avatar": True} if stream_key == "admins" else None,
        )
        data = _object(_expect(response, operation=f"list Intercom {stream_key}"))
        return _object_list(data.get(response_key), field=f"Intercom {stream_key}")

    async def _conversation(self, conversation_id: str) -> dict[str, object]:
        response = await self._client.request(
            f"/conversations/{_path_id(conversation_id)}",
            query={"display_as": "plaintext"},
        )
        if response.status_code in {404, 410}:
            raise SorExternalRecordNotFound(
                vendor_object_key="conversations",
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
        if stream_key == "conversations":
            record_id = _required_id(row.get("id"), field="Intercom conversation ID")
            source = _optional_object(row.get("source"))
            statistics = _optional_object(row.get("statistics"))
            sla = _optional_object(row.get("sla_applied"))
            state = _optional_string(row.get("state"))
            contacts = _nested_object_list(
                row.get("contacts"),
                "contacts",
                field="Intercom conversation contacts",
            )
            tags = _nested_object_list(
                row.get("tags"),
                "tags",
                field="Intercom conversation tags",
            )
            updated_epoch = _optional_epoch(row.get("updated_at"))
            payload: dict[str, object] = {
                "subject": row.get("title") or source.get("subject"),
                "normalized_description": _plain_text(source.get("body")),
                "requester_external_id": (
                    _optional_id(contacts[0].get("id")) if contacts else None
                ),
                "assignee_external_id": _optional_id(
                    row.get("admin_assignee_id")
                ),
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
        if stream_key == "contacts":
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
        if stream_key == "admins":
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
        if stream_key == "teams":
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.get("id"), field="Intercom team ID"),
                payload={"name": row.get("name"), "description": None, "active": True},
            )
        if stream_key == "tags":
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_required_id(row.get("id"), field="Intercom tag ID"),
                payload={"name": row.get("name")},
            )
        if stream_key == "conversation_parts":
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
                row.get("attachments") or [], field="Intercom message attachments"
            )
            attachment_ids = [
                _attachment_external_id(conversation_id, item)
                for item in attachments
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
        message_id = _required_id(
            row.get("_message_id"), field="Intercom message ID"
        )
        attachment_id = _required_id(
            row.get("id"), field="Intercom attachment ID"
        )
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
        values = self._ticket_write_values(command.payload)
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
            vendor_object_key="conversations",
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
        values = self._ticket_write_values(command.payload)
        unsupported = {
            key for key in values if key.startswith("_")
        }
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
        allowed = {"assignee_external_id", "group_external_id"}
        if not command.payload or set(command.payload) - allowed:
            raise _invalid_command(
                "Assigning an Intercom conversation requires an admin or team ID."
            )
        admin_id = await self._admin_id()
        response: SorJsonResponse | None = None
        data: dict[str, object] | None = None
        for key, assignee_type in (
            ("group_external_id", "team"),
            ("assignee_external_id", "admin"),
        ):
            if key not in command.payload:
                continue
            assignee_id = _required_id(
                command.payload[key], field=f"Intercom {assignee_type} assignee ID"
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
        public: bool,
    ) -> SorCommandResult:
        if set(command.payload) != {"normalized_text"}:
            raise _invalid_command(
                "An Intercom reply or note requires only normalized_text."
            )
        text = _required_string(
            command.payload.get("normalized_text"),
            field="Intercom message text",
        )
        response = await self._mutation_request(
            f"/conversations/{_path_id(conversation_id)}/reply",
            method="POST",
            payload={
                "type": "admin",
                "admin_id": await self._admin_id(),
                "message_type": "comment" if public else "note",
                "body": text,
            },
            operation=(
                "reply to an Intercom conversation"
                if public
                else "add an Intercom private note"
            ),
        )
        conversation = _object(
            _expect(response, operation="write an Intercom conversation message")
        )
        part = _latest_message_part(conversation, public=public)
        part_id = _required_id(part.get("id"), field="Intercom message ID")
        return SorCommandResult(
            vendor_object_key="conversation_parts",
            external_id=_expanded_id(conversation_id, part_id),
            external_request_id=_request_id(response),
            source_revision=_epoch_revision(
                _optional_epoch(conversation.get("updated_at"))
            ),
            response={
                "status": "accepted",
                "visibility": "PUBLIC" if public else "PRIVATE",
            },
        )

    async def _close_conversation(
        self,
        conversation_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if set(command.payload) - {"normalized_text"}:
            raise _invalid_command(
                "Closing an Intercom conversation accepts only normalized_text."
            )
        payload: dict[str, object] = {
            "message_type": "close",
            "type": "admin",
            "admin_id": await self._admin_id(),
        }
        if "normalized_text" in command.payload:
            payload["body"] = _required_string(
                command.payload.get("normalized_text"),
                field="Intercom close message",
            )
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
        if set(command.payload) != {"tag_external_id"}:
            raise _invalid_command(
                "Changing an Intercom tag requires only tag_external_id."
            )
        tag_id = _required_id(
            command.payload.get("tag_external_id"), field="Intercom tag ID"
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
            vendor_object_key="conversations",
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
            if field.vendor_object_key == "conversations" and field.writable
        }
        if not payload:
            raise _invalid_command(
                "An Intercom conversation mutation requires mapped fields."
            )
        unknown = set(payload) - set(writable)
        if unknown:
            raise SorVendorOperationError(
                "vendor_field_not_writable",
                "The requested Intercom field is not writable by this source mapping.",
                retryable=False,
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
                    "vendor_field_not_writable",
                    "The mapped Intercom field is not writable by this adapter.",
                    retryable=False,
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
                "vendor_timeout",
                "vendor_transport_failed",
                "vendor_server_failed",
            }:
                raise SorVendorOperationError(
                    "vendor_mutation_outcome_unknown",
                    "Intercom may have applied the action; reconcile before retrying.",
                    retryable=False,
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
            vendor_object_key="conversations",
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
            "vendor_stream_unavailable",
            "The requested Intercom stream is not selected for this source.",
            retryable=False,
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
        raise _invalid_command("Intercom custom attribute identity is invalid.") from error
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
        "vendor_cursor_invalid",
        "The Intercom cursor is invalid or belongs to another stream.",
        retryable=False,
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
        opening["attachments"] = _annotated_attachments(
            opening.get("attachments"),
            conversation_id=conversation_id,
            message_id=_required_id(opening.get("id"), field="Intercom message ID"),
        )
        result.append(opening)
    parts = _optional_object(conversation.get("conversation_parts"))
    for raw_part in _object_list(
        parts.get("conversation_parts") or [],
        field="Intercom conversation parts",
    ):
        part_type = _optional_string(raw_part.get("part_type"))
        if part_type not in {"comment", "note"} or not _has_message_content(
            raw_part
        ):
            continue
        part = dict(raw_part)
        part["_conversation_id"] = conversation_id
        part["_part_type"] = part_type
        part["attachments"] = _annotated_attachments(
            part.get("attachments"),
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
    attachments = row.get("attachments")
    return isinstance(attachments, list) and bool(attachments)


def _message_text(row: Mapping[str, object]) -> str:
    body = _plain_text(row.get("body"))
    if body:
        return body
    attachments = _object_list(
        row.get("attachments") or [],
        field="Intercom message attachments",
    )
    names = [
        _optional_string(item.get("name")) or "unnamed file"
        for item in attachments
    ]
    if names:
        return "\n".join(f"[Attachment: {name}]" for name in names)
    raise _invalid_response("Intercom message has no readable content.")


def _attachment_rows(conversation: Mapping[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for message in _message_rows(conversation):
        result.extend(
            _object_list(
                message.get("attachments") or [],
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
    parts = _optional_object(conversation.get("conversation_parts"))
    rows = _object_list(
        parts.get("conversation_parts") or [],
        field="Intercom conversation parts",
    )
    total = _optional_integer(parts.get("total_count"))
    if total is not None and total < len(rows):
        raise _invalid_response(
            "Intercom conversation part count is smaller than its returned data."
        )
    if total is not None and total > len(rows):
        raise SorVendorOperationError(
            "vendor_history_truncated",
            "Intercom exposes only the 500 most recent parts for this conversation.",
            retryable=False,
        )
    if len(rows) > INTERCOM_MAX_PARTS:
        raise _invalid_response("Intercom returned more than 500 conversation parts.")
    if total is None and len(rows) == INTERCOM_MAX_PARTS:
        raise SorVendorOperationError(
            "vendor_history_truncated",
            "Intercom may have truncated this conversation at its 500-part limit.",
            retryable=False,
        )


def _latest_message_part(
    conversation: Mapping[str, object],
    *,
    public: bool,
) -> dict[str, object]:
    expected = "comment" if public else "note"
    parts = _optional_object(conversation.get("conversation_parts"))
    rows = _object_list(
        parts.get("conversation_parts") or [],
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
        return "contacts", _optional_id(item.get("id"))
    if lowered.startswith("conversation."):
        direct = _optional_id(item.get("conversation_id"))
        if direct is None:
            conversation = _optional_object(item.get("conversation"))
            direct = _optional_id(conversation.get("id"))
        if direct is None and _optional_string(item.get("type")) == "conversation":
            direct = _optional_id(item.get("id"))
        return "conversations", direct
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
    if response.status_code == 401:
        raise SorVendorOperationError(
            "vendor_authorization_expired",
            f"Intercom refused authorization while attempting to {operation}.",
            retryable=False,
            requires_reauthorization=True,
        )
    if response.status_code == 403:
        raise SorVendorOperationError(
            "vendor_forbidden",
            f"Intercom refused permission to {operation}.",
            retryable=False,
        )
    if response.status_code == 404:
        raise SorVendorOperationError(
            "vendor_resource_unavailable",
            f"Intercom could not find the resource needed to {operation}.",
            retryable=False,
        )
    if response.status_code in {409, 422}:
        raise SorVendorOperationError(
            "vendor_command_invalid",
            f"Intercom rejected the data used to {operation}.",
            retryable=False,
        )
    if response.status_code == 429:
        raise SorVendorOperationError(
            "vendor_rate_limited",
            "Intercom rate-limited the source.",
            retryable=True,
        )
    if response.status_code >= 500:
        raise SorVendorOperationError(
            "vendor_server_failed",
            f"Intercom failed while attempting to {operation}.",
            retryable=True,
        )
    raise SorVendorOperationError(
        "vendor_request_failed",
        f"Intercom refused the request to {operation}.",
        retryable=False,
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
        raise _invalid_response("Intercom timestamp is outside the supported range.") from error


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
    values = [value.strip() for key, value in headers.items() if key.casefold() == expected]
    if len(values) != 1 or not values[0] or len(values[0]) > 4_096:
        return None
    return values[0]


def _invalid_response(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_response_invalid",
        message,
        retryable=False,
    )


def _invalid_command(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_command_invalid",
        message,
        retryable=False,
    )


__all__ = [
    "INTERCOM_API_VERSION",
    "INTERCOM_MANIFEST",
    "IntercomSupportAdapter",
    "create_intercom_adapter",
]
