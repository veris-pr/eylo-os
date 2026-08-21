"""Zendesk Support adapter for Eylo's canonical customer-support profile."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.runtime.http import SorHttpTransport, SorJsonHttpClient, SorJsonResponse
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterContext,
    SorCapabilityUnavailable,
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

ZENDESK_API_VERSION = "ticketing-v2"
ZENDESK_CURSOR_VERSION = 1
ZENDESK_WEBHOOK_TOLERANCE = timedelta(minutes=5)
ZENDESK_INITIAL_START_TIME = 1

READ_SCOPE = "read"
WRITE_SCOPE = "write"

_STREAM_ENTITY = {
    "tickets": "ticket",
    "customers": "customer",
    "agents": "agent",
    "groups": "queue",
    "brands": "inbox",
    "comments": "message",
    "tags": "tag",
    "ticket_metrics": "sla_metric",
    "attachments": "attachment",
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
    "support_find_customer": frozenset({"customers"}),
    "support_find_ticket": frozenset({"tickets"}),
    "support_get_ticket": frozenset({"tickets", "comments"}),
    "support_get_customer_history": frozenset({"customers", "tickets"}),
    "support_list_queues": frozenset({"groups"}),
    "support_describe_ticket_fields": frozenset({"tickets"}),
    "support_open_ticket": frozenset({"tickets"}),
    "support_update_ticket": frozenset({"tickets"}),
    "support_assign_ticket": frozenset({"tickets", "agents"}),
    "support_reply": frozenset({"tickets", "comments"}),
    "support_add_note": frozenset({"tickets", "comments"}),
    "support_close_ticket": frozenset({"tickets"}),
    "support_add_tag": frozenset({"tickets", "tags"}),
    "support_remove_tag": frozenset({"tickets", "tags"}),
}
_MUTATION_RESULT_STREAMS = {
    **{name: "tickets" for name in _WRITE_TOOLS},
    "support_reply": "comments",
    "support_add_note": "comments",
}


ZENDESK_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.SUPPORT,
    vendor_key="zendesk",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                "tickets": "Tickets",
                "customers": "Customers",
                "agents": "Agents",
                "groups": "Groups",
                "brands": "Brands",
                "comments": "Comments",
                "tags": "Tags",
                "ticket_metrics": "Ticket metrics",
                "attachments": "Attachments",
            }[stream_key],
            description={
                "tickets": "Zendesk tickets, ownership, status, tags, and custom fields.",
                "customers": "Zendesk end users who request support.",
                "agents": "Zendesk agents and administrators who may own tickets.",
                "groups": "Zendesk groups used as support queues.",
                "brands": "Zendesk brands used as ticket inboxes.",
                "comments": "Public replies and private internal notes from ticket events.",
                "tags": "Registered and recently used Zendesk ticket tags.",
                "ticket_metrics": "Vendor-measured reply, resolution, and wait durations.",
                "attachments": "Metadata for files attached to ticket comments.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=(
                frozenset({SorChangeStrategy.CURSOR})
                if stream_key in {"tickets", "customers", "agents"}
                else frozenset({SorChangeStrategy.UPDATED_AT})
                if stream_key in {"comments", "attachments"}
                else frozenset({SorChangeStrategy.FULL_RECONCILE})
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
    tool_streams=_TOOL_STREAMS,
    mutation_result_streams=_MUTATION_RESULT_STREAMS,
    oauth=SorOAuthSpec(
        authorization_path="/oauth/authorizations/new",
        token_path="/oauth/tokens",
        base_scopes=(READ_SCOPE,),
        token_request_format="json",
        instance_host_suffixes=("zendesk.com",),
        operator_instance_origin=True,
    ),
    requires_instance_origin=True,
    supports_webhooks=True,
    supports_custom_fields=True,
    supports_conditional_writes=True,
    supports_history=True,
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
        group="Zendesk",
    )


_SCHEMA_FIELDS = {
    "tickets": (
        _field("subject", "Subject", "text", writable=True),
        _field("normalized_description", "Description", "text", writable=True),
        _field("requester_external_id", "Requester ID", "reference", writable=True),
        _field("assignee_external_id", "Assignee ID", "reference", writable=True),
        _field("group_external_id", "Group ID", "reference", writable=True),
        _field("inbox_external_id", "Brand ID", "reference", writable=True),
        _field("native_status", "Status", "text", writable=True),
        _field("normalized_status", "Normalized status", "enum"),
        _field("priority", "Priority", "text", writable=True),
        _field("category", "Type", "text", writable=True),
        _field("channel", "Channel", "text"),
        _field("tag_external_ids", "Tags", "string_array", writable=True),
        _field("resolved_at", "Solved at", "timestamp"),
        _field("closed_at", "Closed at", "timestamp"),
    ),
    "customers": (
        _field("name", "Name", "text", nullable=False),
        _field("primary_email", "Email", "text"),
        _field("primary_phone", "Phone", "text"),
        _field("company_external_id", "Organization ID", "reference"),
        _field("active", "Active", "boolean"),
    ),
    "agents": (
        _field("name", "Name", "text", nullable=False),
        _field("primary_email", "Email", "text"),
        _field("active", "Active", "boolean"),
        _field("assignable", "Assignable", "boolean"),
        _field("avatar_url", "Avatar URL", "link"),
    ),
    "groups": (
        _field("name", "Name", "text", nullable=False),
        _field("description", "Description", "text"),
        _field("active", "Active", "boolean"),
    ),
    "brands": (
        _field("name", "Name", "text", nullable=False),
        _field("kind", "Kind", "text"),
        _field("active", "Active", "boolean"),
    ),
    "comments": (
        _field("ticket_external_id", "Ticket ID", "reference", nullable=False),
        _field("visibility", "Visibility", "enum", nullable=False),
        _field("direction", "Direction", "enum"),
        _field("author_external_id", "Author ID", "reference"),
        _field("normalized_text", "Comment", "text", nullable=False),
        _field("source_body", "Source body", "bounded_json"),
        _field("body_format", "Body format", "text"),
        _field("attachment_external_ids", "Attachment IDs", "string_array"),
        _field("created_at", "Created at", "timestamp", nullable=False),
        _field("updated_at", "Updated at", "timestamp"),
    ),
    "tags": (_field("name", "Name", "text", nullable=False),),
    "ticket_metrics": (
        _field("ticket_external_id", "Ticket ID", "reference", nullable=False),
        _field("metric", "Metric", "text", nullable=False),
        _field("value", "Value", "decimal"),
        _field("unit", "Unit", "text"),
        _field("native_state", "Source state", "text"),
        _field("normalized_state", "Normalized state", "enum"),
        _field("target_at", "Target at", "timestamp"),
        _field("achieved_at", "Achieved at", "timestamp"),
        _field("breached_at", "Breached at", "timestamp"),
    ),
    "attachments": (
        _field("ticket_external_id", "Ticket ID", "reference", nullable=False),
        _field("message_external_id", "Comment ID", "reference"),
        _field("name", "Name", "text", nullable=False),
        _field("content_type", "Content type", "text"),
        _field("size_bytes", "Size", "integer"),
        _field("source_url", "Content URL", "link"),
    ),
}

_TICKET_FIELD_MAP = {
    "subject": "subject",
    "normalized_description": "description",
    "requester_external_id": "requester_id",
    "assignee_external_id": "assignee_id",
    "group_external_id": "group_id",
    "inbox_external_id": "brand_id",
    "native_status": "status",
    "priority": "priority",
    "category": "type",
    "tag_external_ids": "tags",
}
_STATUS_MAP = {
    "new": "NEW",
    "open": "OPEN",
    "pending": "PENDING",
    "hold": "HOLD",
    "solved": "RESOLVED",
    "closed": "CLOSED",
}
_METRIC_FIELDS = (
    "agent_wait_time_in_minutes",
    "first_resolution_time_in_minutes",
    "full_resolution_time_in_minutes",
    "on_hold_time_in_minutes",
    "reply_time_in_minutes",
    "reply_time_in_seconds",
    "requester_wait_time_in_minutes",
)


@dataclass(frozen=True, slots=True)
class _ExpandedCursor:
    vendor_cursor: str | None
    offset: int


@dataclass(frozen=True, slots=True)
class _EventCursor:
    start_time: int
    offset: int


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
        data = _object(_expect(response, operation="verify Zendesk account"))
        viewer = _object(data.get("user"), field="Zendesk user")
        return SorConnectionVerification(
            account_external_id=_required_id(viewer.get("id"), field="Zendesk user ID"),
            account_display_name=_optional_string(viewer.get("name"))
            or "Zendesk account",
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=ZENDESK_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise SorVendorOperationError(
                "source_selection_empty",
                "The Zendesk source selects no streams.",
                retryable=False,
            )
        custom_fields: tuple[SorDiscoveredField, ...] = ()
        if "tickets" in self._context.selected_objects:
            response = await self._client.request("/api/v2/ticket_fields")
            data = _object(_expect(response, operation="list Zendesk ticket fields"))
            rows = _object_list(
                data.get("ticket_fields") or data.get("ticket_field"),
                field="Zendesk ticket fields",
            )
            custom_fields = tuple(
                sorted(
                    (
                        _custom_ticket_field(row)
                        for row in rows
                        if row.get("removable") is True
                    ),
                    key=lambda item: (item.label.casefold(), item.key),
                )
            )
        streams = {stream.key: stream for stream in ZENDESK_MANIFEST.streams}
        objects: list[SorDiscoveredObject] = []
        for stream_key in self._context.selected_objects:
            _require_stream(stream_key, selected=self._context.selected_objects)
            fields = _SCHEMA_FIELDS[stream_key]
            if stream_key == "tickets":
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
        if stream_key == "tags":
            return self._external_record("tags", {"name": record_id})
        if stream_key == "comments":
            ticket_id, comment_id = _split_comment_id(record_id)
            response = await self._client.request(
                f"/api/v2/tickets/{_path_id(ticket_id)}/comments/{_path_id(comment_id)}"
            )
            if response.status_code in {404, 410}:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            data = _object(_expect(response, operation="read Zendesk comment"))
            row = _object(data.get("comment"), field="Zendesk comment")
            row["_ticket_id"] = ticket_id
            return self._external_record(stream_key, row)
        if stream_key == "attachments":
            ticket_id, comment_id, attachment_id = _split_attachment_id(record_id)
            response = await self._client.request(
                f"/api/v2/attachments/{_path_id(attachment_id)}"
            )
            if response.status_code in {404, 410}:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            data = _object(_expect(response, operation="read Zendesk attachment"))
            row = _object(data.get("attachment"), field="Zendesk attachment")
            row["_ticket_id"] = ticket_id
            row["_comment_id"] = comment_id
            return self._external_record(stream_key, row)
        if stream_key == "ticket_metrics":
            metric_id, metric_name, basis = _split_metric_id(record_id)
            response = await self._client.request(
                f"/api/v2/ticket_metrics/{_path_id(metric_id)}"
            )
            if response.status_code in {404, 410}:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            data = _object(_expect(response, operation="read Zendesk ticket metric"))
            value = data.get("ticket_metric")
            if isinstance(value, list):
                rows = _object_list(value, field="Zendesk ticket metric")
                row = rows[0] if rows else None
            else:
                row = _object(value, field="Zendesk ticket metric")
            if row is None:
                raise _invalid_response("Zendesk omitted the requested ticket metric.")
            for expanded in _expand_metric(row):
                if expanded["_metric"] == metric_name and expanded["_basis"] == basis:
                    return self._external_record(stream_key, expanded)
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )

        endpoint, response_key = {
            "tickets": (f"/api/v2/tickets/{_path_id(record_id)}", "ticket"),
            "customers": (f"/api/v2/users/{_path_id(record_id)}", "user"),
            "agents": (f"/api/v2/users/{_path_id(record_id)}", "user"),
            "groups": (f"/api/v2/groups/{_path_id(record_id)}", "group"),
            "brands": (f"/api/v2/brands/{_path_id(record_id)}", "brand"),
        }[stream_key]
        response = await self._client.request(endpoint)
        if response.status_code in {404, 410}:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        data = _object(_expect(response, operation="read Zendesk record"))
        row = _object(data.get(response_key), field="Zendesk record")
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
        raise SorCapabilityUnavailable(
            "Configure the signed Zendesk webhook and trigger in Zendesk Admin Center."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Operator-configured Zendesk webhooks do not have an Eylo renewal flow."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "Remove the operator-configured webhook in Zendesk Admin Center."
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
                "Zendesk webhook verification requires the source signing secret."
            )
        signature = _header(headers, "x-zendesk-webhook-signature")
        timestamp_text = _header(
            headers,
            "x-zendesk-webhook-signature-timestamp",
        )
        if signature is None or timestamp_text is None:
            raise SorVendorOperationError(
                "vendor_webhook_unsigned",
                "Zendesk webhook signature headers are missing.",
                retryable=False,
            )
        timestamp = _webhook_timestamp(timestamp_text)
        now = datetime.now(timezone.utc)
        if abs(now - timestamp) > ZENDESK_WEBHOOK_TOLERANCE:
            raise SorVendorOperationError(
                "vendor_webhook_stale",
                "Zendesk webhook timestamp is outside the replay window.",
                retryable=False,
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
                "vendor_webhook_invalid",
                "Zendesk webhook signature is invalid.",
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
                "Zendesk webhook body is not valid JSON.",
                retryable=False,
            ) from error
        data = _object(payload, field="Zendesk webhook")
        subject = _optional_string(data.get("subject"))
        ticket_id = _ticket_id_from_subject(subject)
        if ticket_id is None:
            detail = data.get("detail")
            if isinstance(detail, Mapping):
                ticket_id = _optional_id(detail.get("id"))
        if ticket_id is None:
            return ()
        return (
            SorWebhookSignal(
                delivery_id=(
                    _header(headers, "x-zendesk-webhook-invocation-id")
                    or _optional_string(data.get("id"))
                ),
                event_type=_optional_string(data.get("type"))
                or "zendesk.ticket.changed",
                vendor_object_key="tickets",
                external_id=ticket_id,
                occurred_at=_optional_datetime(data.get("time")),
            ),
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise SorVendorOperationError(
                "vendor_tool_unsupported",
                "This Zendesk adapter does not execute the requested support action.",
                retryable=False,
            )
        if command.tool_name == "support_open_ticket":
            return await self._open_ticket(command)
        ticket_id = _required_target(command)
        if command.tool_name == "support_update_ticket":
            return await self._update_ticket(ticket_id, command)
        if command.tool_name == "support_assign_ticket":
            return await self._assign_ticket(ticket_id, command)
        if command.tool_name in {"support_reply", "support_add_note"}:
            return await self._add_comment(
                ticket_id,
                command,
                public=command.tool_name == "support_reply",
            )
        if command.tool_name == "support_close_ticket":
            return await self._close_ticket(ticket_id, command)
        return await self._change_tag(
            ticket_id,
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
            requester_external_id=_optional_string(values.get("requester_external_id")),
            assignee_external_id=_optional_string(values.get("assignee_external_id")),
            group_external_id=_optional_string(values.get("group_external_id")),
            inbox_external_id=_optional_string(values.get("inbox_external_id")),
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
                if key.startswith("custom_field_")
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
                if key.startswith("user_field_")
            },
        )

    def normalize_agent(self, record: SorExternalRecord) -> SupportAgent:
        values = record.payload
        return SupportAgent(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="Zendesk Agent name"),
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
                values.get("ticket_external_id"),
                field="Zendesk comment ticket ID",
            ),
            visibility=_required_string(
                values.get("visibility"),
                field="Zendesk comment visibility",
            ),
            direction=_optional_string(values.get("direction")),
            author_external_id=_optional_string(values.get("author_external_id")),
            normalized_text=_required_string(
                values.get("normalized_text"),
                field="Zendesk comment body",
            ),
            source_body=_json_value(values.get("source_body")),
            body_format=_optional_string(values.get("body_format")),
            attachment_external_ids=_string_tuple(
                values.get("attachment_external_ids")
            ),
            created_at=_required_datetime(
                values.get("created_at"),
                field="Zendesk comment creation time",
            ),
            updated_at=_optional_datetime(values.get("updated_at")),
        )

    def normalize_queue(self, record: SorExternalRecord) -> SupportQueue:
        values = record.payload
        return SupportQueue(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="Zendesk group name"),
            description=_optional_string(values.get("description")),
            active=_optional_boolean(values.get("active")),
        )

    def normalize_inbox(self, record: SorExternalRecord) -> SupportInbox:
        values = record.payload
        return SupportInbox(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="Zendesk brand name"),
            kind=_optional_string(values.get("kind")),
            active=_optional_boolean(values.get("active")),
        )

    def normalize_tag(self, record: SorExternalRecord) -> SupportTag:
        return SupportTag(
            external_id=record.external_id,
            name=_required_string(record.payload.get("name"), field="Zendesk tag name"),
        )

    def normalize_sla_metric(self, record: SorExternalRecord) -> SupportSlaMetric:
        values = record.payload
        return SupportSlaMetric(
            external_id=record.external_id,
            ticket_external_id=_required_string(
                values.get("ticket_external_id"),
                field="Zendesk metric ticket ID",
            ),
            metric=_required_string(
                values.get("metric"),
                field="Zendesk metric name",
            ),
            value=_optional_decimal(values.get("value")),
            unit=_optional_string(values.get("unit")),
            native_state=_optional_string(values.get("native_state")),
            normalized_state=_optional_string(values.get("normalized_state")),
            target_at=_optional_datetime(values.get("target_at")),
            achieved_at=_optional_datetime(values.get("achieved_at")),
            breached_at=_optional_datetime(values.get("breached_at")),
        )

    def normalize_attachment(self, record: SorExternalRecord) -> SupportAttachment:
        values = record.payload
        return SupportAttachment(
            external_id=record.external_id,
            ticket_external_id=_required_string(
                values.get("ticket_external_id"),
                field="Zendesk attachment ticket ID",
            ),
            message_external_id=_optional_string(values.get("message_external_id")),
            name=_required_string(
                values.get("name"),
                field="Zendesk attachment name",
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
                "Zendesk page limit must be positive.",
                retryable=False,
            )
        if stream_key == "tickets":
            return await self._read_cursor_export(
                stream_key=stream_key,
                cursor=cursor,
                limit=min(limit, 1_000),
            )
        if stream_key in {"customers", "agents"}:
            return await self._read_cursor_export(
                stream_key=stream_key,
                cursor=cursor,
                limit=min(limit, 1_000),
            )
        if stream_key in {"comments", "attachments"}:
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
            if stream_key == "tickets"
            else "/api/v2/incremental/users/cursor"
        )
        query: dict[str, object] = {"per_page": limit}
        if vendor_cursor is None:
            query["start_time"] = ZENDESK_INITIAL_START_TIME
        else:
            query["cursor"] = vendor_cursor
        if stream_key == "tickets":
            query["exclude_deleted"] = True
            query["support_type_scope"] = "all"
        response = await self._client.request(path, query=query)
        data = _object(_expect(response, operation=f"export Zendesk {stream_key}"))
        rows = _object_list(
            data.get("tickets" if stream_key == "tickets" else "users"),
            field=f"Zendesk {stream_key}",
        )
        if len(rows) > limit:
            raise _invalid_response(
                f"Zendesk returned more {stream_key} than the requested page limit."
            )
        if stream_key in {"customers", "agents"}:
            rows = [row for row in rows if _user_matches_stream(stream_key, row)]
        end_of_stream = _required_boolean(
            data.get("end_of_stream"),
            field=f"Zendesk {stream_key} end_of_stream",
        )
        after_cursor = _required_string(
            data.get("after_cursor"),
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
            query={
                "include": "comment_events",
                "per_page": min(max(limit, 1), 1_000),
                "start_time": checkpoint.start_time,
                "support_type_scope": "all",
            },
        )
        data = _object(
            _expect(response, operation="export Zendesk ticket comment events")
        )
        events = _object_list(data.get("ticket_events"), field="Zendesk ticket events")
        expanded = _expand_event_records(events, stream_key=stream_key)
        if checkpoint.offset > len(expanded):
            raise _invalid_response("Zendesk event cursor exceeds its source page.")
        records = expanded[checkpoint.offset : checkpoint.offset + limit]
        consumed = checkpoint.offset + len(records)
        end_time = _required_integer(
            data.get("end_time"),
            field="Zendesk ticket event end_time",
        )
        end_of_stream = _required_boolean(
            data.get("end_of_stream"),
            field="Zendesk ticket event end_of_stream",
        )
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
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_expanded_cursor(cursor, stream_key=stream_key)
        vendor_limit = min(limit, 100)
        if stream_key == "ticket_metrics":
            vendor_limit = max(1, min(100, limit // 14))
        endpoint, response_key = {
            "groups": ("/api/v2/groups", "groups"),
            "brands": ("/api/v2/brands", "brands"),
            "tags": ("/api/v2/tags", "tags"),
            "ticket_metrics": ("/api/v2/ticket_metrics", "ticket_metrics"),
        }[stream_key]
        query: dict[str, object] = {"page[size]": vendor_limit}
        if checkpoint.vendor_cursor is not None:
            query["page[after]"] = checkpoint.vendor_cursor
        response = await self._client.request(endpoint, query=query)
        data = _object(_expect(response, operation=f"list Zendesk {stream_key}"))
        raw = data.get(response_key)
        if stream_key == "tags":
            rows = _tag_rows(raw)
        else:
            rows = _object_list(raw, field=f"Zendesk {stream_key}")
        expanded = (
            [item for row in rows for item in _expand_metric(row)]
            if stream_key == "ticket_metrics"
            else rows
        )
        if checkpoint.offset > len(expanded):
            raise _invalid_response("Zendesk reconcile cursor exceeds its source page.")
        selected = expanded[checkpoint.offset : checkpoint.offset + limit]
        consumed = checkpoint.offset + len(selected)
        vendor_has_more, next_vendor_cursor = _cursor_page(data)
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

    def _external_record(
        self,
        stream_key: str,
        row: Mapping[str, object],
    ) -> SorExternalRecord:
        if stream_key == "tickets":
            record_id = _required_id(row.get("id"), field="Zendesk ticket ID")
            updated_at = _optional_datetime(row.get("updated_at"))
            status = _optional_string(row.get("status"))
            via = row.get("via")
            channel = (
                _optional_string(via.get("channel"))
                if isinstance(via, Mapping)
                else None
            )
            payload: dict[str, object] = {
                "subject": row.get("subject"),
                "normalized_description": row.get("description"),
                "requester_external_id": _optional_id(row.get("requester_id")),
                "assignee_external_id": _optional_id(row.get("assignee_id")),
                "group_external_id": _optional_id(row.get("group_id")),
                "inbox_external_id": _optional_id(row.get("brand_id")),
                "native_status": status,
                "normalized_status": _STATUS_MAP.get(status or ""),
                "priority": row.get("priority"),
                "category": row.get("type"),
                "channel": channel,
                "tag_external_ids": _string_list(
                    row.get("tags"), field="Zendesk ticket tags"
                ),
                "first_response_at": None,
                "resolved_at": row.get("solved_at"),
                "closed_at": row.get("closed_at"),
                "sla_state": None,
            }
            payload.update(_custom_field_values(row.get("custom_fields")))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload=payload,
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=f"{self._origin}/agent/tickets/{record_id}",
            )
        if stream_key in {"customers", "agents"}:
            record_id = _required_id(row.get("id"), field="Zendesk user ID")
            updated_at = _optional_datetime(row.get("updated_at"))
            photo = row.get("photo")
            avatar_url = (
                _safe_source_url(photo.get("content_url"))
                if isinstance(photo, Mapping)
                else None
            )
            role = _optional_string(row.get("role"))
            suspended = row.get("suspended") is True
            payload = {
                "name": row.get("name"),
                "primary_email": row.get("email"),
                "primary_phone": row.get("phone"),
                "company_external_id": _optional_id(row.get("organization_id")),
                "active": row.get("active") is not False and not suspended,
                "assignable": role in {"agent", "admin"} and not suspended,
                "avatar_url": avatar_url,
            }
            user_fields = row.get("user_fields")
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
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=f"{self._origin}/agent/users/{record_id}/tickets",
            )
        if stream_key == "groups":
            record_id = _required_id(row.get("id"), field="Zendesk group ID")
            updated_at = _optional_datetime(row.get("updated_at"))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload={
                    "name": row.get("name"),
                    "description": row.get("description"),
                    "active": row.get("deleted") is not True,
                },
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=_safe_source_url(row.get("url")),
            )
        if stream_key == "brands":
            record_id = _required_id(row.get("id"), field="Zendesk brand ID")
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload={
                    "name": row.get("name"),
                    "kind": "brand",
                    "active": row.get("active"),
                },
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=_optional_datetime(row.get("updated_at")),
                source_revision=_revision(_optional_datetime(row.get("updated_at"))),
                source_url=_safe_source_url(row.get("url")),
            )
        if stream_key == "comments":
            ticket_id = _required_id(
                row.get("_ticket_id") or row.get("ticket_id"),
                field="Zendesk comment ticket ID",
            )
            comment_id = _required_id(row.get("id"), field="Zendesk comment ID")
            created_at = _required_datetime(
                row.get("created_at"),
                field="Zendesk comment creation time",
            )
            attachment_ids = tuple(
                _attachment_external_id(ticket_id, comment_id, attachment)
                for attachment in _object_list(
                    row.get("attachments") or [],
                    field="Zendesk comment attachments",
                )
            )
            source_body = row.get("html_body") or row.get("body")
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_comment_external_id(ticket_id, comment_id),
                payload={
                    "ticket_external_id": ticket_id,
                    "visibility": "PUBLIC" if row.get("public") is True else "PRIVATE",
                    "direction": "UNKNOWN",
                    "author_external_id": _optional_id(row.get("author_id")),
                    "normalized_text": row.get("plain_body") or row.get("body"),
                    "source_body": _json_value(source_body),
                    "body_format": "html" if row.get("html_body") else "text",
                    "attachment_external_ids": attachment_ids,
                    "created_at": created_at,
                    "updated_at": row.get("updated_at"),
                },
                source_created_at=created_at,
                source_updated_at=_optional_datetime(row.get("updated_at")),
                source_revision=_revision(
                    _optional_datetime(row.get("updated_at")) or created_at
                ),
                source_url=f"{self._origin}/agent/tickets/{ticket_id}",
            )
        if stream_key == "tags":
            name = _required_string(row.get("name"), field="Zendesk tag name")
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=name,
                payload={"name": name},
            )
        if stream_key == "ticket_metrics":
            metric_id = _required_id(row.get("id"), field="Zendesk ticket metric ID")
            metric = _required_string(row.get("_metric"), field="Zendesk metric name")
            basis = _required_string(row.get("_basis"), field="Zendesk metric basis")
            updated_at = _optional_datetime(row.get("updated_at"))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=_metric_external_id(metric_id, metric, basis),
                payload={
                    "ticket_external_id": _required_id(
                        row.get("ticket_id"),
                        field="Zendesk metric ticket ID",
                    ),
                    "metric": f"{metric}:{basis}",
                    "value": row.get("_value"),
                    "unit": row.get("_unit"),
                    "native_state": None,
                    "normalized_state": None,
                    "target_at": None,
                    "achieved_at": row.get("solved_at"),
                    "breached_at": None,
                },
                source_created_at=_optional_datetime(row.get("created_at")),
                source_updated_at=updated_at,
                source_revision=_revision(updated_at),
                source_url=_safe_source_url(row.get("url")),
            )
        ticket_id = _required_id(
            row.get("_ticket_id"), field="Zendesk attachment ticket ID"
        )
        comment_id = _required_id(
            row.get("_comment_id"), field="Zendesk attachment comment ID"
        )
        attachment_id = _required_id(row.get("id"), field="Zendesk attachment ID")
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=_attachment_id(ticket_id, comment_id, attachment_id),
            payload={
                "ticket_external_id": ticket_id,
                "message_external_id": _comment_external_id(ticket_id, comment_id),
                "name": row.get("file_name") or row.get("name"),
                "content_type": row.get("content_type"),
                "size_bytes": row.get("size"),
                "source_url": _safe_source_url(row.get("content_url")),
            },
            source_url=_safe_source_url(row.get("content_url")),
        )

    async def _open_ticket(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command(
                "Opening a support ticket cannot target an existing ticket."
            )
        fields = self._ticket_write_values(command.payload)
        description = fields.pop("description", None)
        if not isinstance(description, str) or not description.strip():
            raise _invalid_command(
                "Opening a Zendesk ticket requires normalized_description for its initial comment."
            )
        fields["comment"] = {"body": description.strip(), "public": True}
        response = await self._mutation_request(
            "/api/v2/tickets",
            method="POST",
            payload={"ticket": fields},
            command=command,
            operation="open a Zendesk ticket",
        )
        data = _object(_expect(response, operation="open a Zendesk ticket"))
        ticket = _object(data.get("ticket"), field="Zendesk ticket")
        return self._ticket_result(ticket, response=response)

    async def _update_ticket(
        self,
        ticket_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        fields = self._ticket_write_values(command.payload)
        if not fields:
            raise _invalid_command("Updating a Zendesk ticket requires mapped fields.")
        _add_safe_update(fields, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}",
            method="PUT",
            payload={"ticket": fields},
            command=command,
            operation="update a Zendesk ticket",
        )
        data = _object(_expect(response, operation="update a Zendesk ticket"))
        ticket = _object(data.get("ticket"), field="Zendesk ticket")
        return self._ticket_result(ticket, response=response)

    async def _assign_ticket(
        self,
        ticket_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if set(command.payload) - {"assignee_external_id", "group_external_id"}:
            raise _invalid_command(
                "Assigning a Zendesk ticket accepts only assignee_external_id and group_external_id."
            )
        if not command.payload:
            raise _invalid_command(
                "Assigning a Zendesk ticket requires an assignee or group."
            )
        fields: dict[str, object] = {}
        if "assignee_external_id" in command.payload:
            fields["assignee_id"] = _required_id(
                command.payload["assignee_external_id"],
                field="Zendesk assignee ID",
            )
        if "group_external_id" in command.payload:
            fields["group_id"] = _required_id(
                command.payload["group_external_id"],
                field="Zendesk group ID",
            )
        _add_safe_update(fields, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}",
            method="PUT",
            payload={"ticket": fields},
            command=command,
            operation="assign a Zendesk ticket",
        )
        data = _object(_expect(response, operation="assign a Zendesk ticket"))
        ticket = _object(data.get("ticket"), field="Zendesk ticket")
        return self._ticket_result(ticket, response=response)

    async def _add_comment(
        self,
        ticket_id: str,
        command: SorCommandRequest,
        *,
        public: bool,
    ) -> SorCommandResult:
        if set(command.payload) != {"normalized_text"}:
            raise _invalid_command(
                "A Zendesk reply or note requires only normalized_text."
            )
        text = _required_string(
            command.payload.get("normalized_text"),
            field="Zendesk comment text",
        )
        fields: dict[str, object] = {
            "comment": {"body": text, "public": public},
        }
        _add_safe_update(fields, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}",
            method="PUT",
            payload={"ticket": fields},
            command=command,
            operation=(
                "reply to a Zendesk ticket" if public else "add a Zendesk private note"
            ),
        )
        data = _object(_expect(response, operation="add a Zendesk comment"))
        audit = _object(data.get("audit"), field="Zendesk ticket audit")
        comment = _audit_comment(audit, public=public)
        comment_id = _required_id(comment.get("id"), field="Zendesk comment ID")
        return SorCommandResult(
            vendor_object_key="comments",
            external_id=_comment_external_id(ticket_id, comment_id),
            external_request_id=_request_id(response),
            source_url=f"{self._origin}/agent/tickets/{ticket_id}",
            response={
                "status": "accepted",
                "visibility": "PUBLIC" if public else "PRIVATE",
            },
        )

    async def _close_ticket(
        self,
        ticket_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if set(command.payload) - {"native_status"}:
            raise _invalid_command(
                "Closing a Zendesk ticket accepts only native_status."
            )
        status = _optional_string(command.payload.get("native_status")) or "solved"
        if status not in {"solved", "closed"}:
            raise _invalid_command("Zendesk close status must be solved or closed.")
        fields: dict[str, object] = {"status": status}
        _add_safe_update(fields, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}",
            method="PUT",
            payload={"ticket": fields},
            command=command,
            operation="close a Zendesk ticket",
        )
        data = _object(_expect(response, operation="close a Zendesk ticket"))
        ticket = _object(data.get("ticket"), field="Zendesk ticket")
        return self._ticket_result(ticket, response=response)

    async def _change_tag(
        self,
        ticket_id: str,
        command: SorCommandRequest,
        *,
        add: bool,
    ) -> SorCommandResult:
        if set(command.payload) != {"tag_external_id"}:
            raise _invalid_command(
                "Changing a Zendesk tag requires only tag_external_id."
            )
        tag = _required_string(
            command.payload.get("tag_external_id"),
            field="Zendesk tag",
        )
        payload: dict[str, object] = {"tags": [tag]}
        _add_safe_update(payload, command.expected_source_revision)
        response = await self._mutation_request(
            f"/api/v2/tickets/{_path_id(ticket_id)}/tags",
            method="PUT" if add else "DELETE",
            payload=payload,
            command=command,
            operation="change a Zendesk ticket tag",
        )
        _expect(response, operation="change a Zendesk ticket tag")
        return SorCommandResult(
            vendor_object_key="tickets",
            external_id=ticket_id,
            external_request_id=_request_id(response),
            source_url=f"{self._origin}/agent/tickets/{ticket_id}",
            response={"status": "accepted"},
        )

    def _ticket_write_values(self, payload: Mapping[str, object]) -> dict[str, object]:
        writable = {
            field.agent_key: field.vendor_field_key
            for field in self._context.fields
            if field.vendor_object_key == "tickets" and field.writable
        }
        if not payload:
            raise _invalid_command("A Zendesk ticket mutation requires mapped fields.")
        unknown = set(payload) - set(writable)
        if unknown:
            raise SorVendorOperationError(
                "vendor_field_not_writable",
                "The Zendesk mutation contains fields absent from the writable mapping.",
                retryable=False,
            )
        fields: dict[str, object] = {}
        custom_fields: list[dict[str, object]] = []
        for agent_key, value in payload.items():
            vendor_key = writable[agent_key]
            if vendor_key.startswith("custom_field_"):
                custom_fields.append(
                    {
                        "id": _required_id(
                            vendor_key.removeprefix("custom_field_"),
                            field="Zendesk custom field ID",
                        ),
                        "value": value,
                    }
                )
                continue
            source_key = _TICKET_FIELD_MAP.get(vendor_key)
            if source_key is None:
                raise SorVendorOperationError(
                    "vendor_field_not_writable",
                    "The mapped Zendesk field is not writable by this adapter.",
                    retryable=False,
                )
            fields[source_key] = value
        if custom_fields:
            fields["custom_fields"] = custom_fields
        return fields

    async def _mutation_request(
        self,
        path: str,
        *,
        method: str,
        payload: object,
        command: SorCommandRequest,
        operation: str,
    ) -> SorJsonResponse:
        try:
            response = await self._client.request(
                path,
                method=method,
                payload=payload,
                idempotency_key=command.idempotency_key,
            )
            if response.status_code >= 500:
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
                    "Zendesk may have applied the action; reconcile before retrying.",
                    retryable=False,
                ) from error
            raise

    def _ticket_result(
        self,
        ticket: Mapping[str, object],
        *,
        response: SorJsonResponse,
    ) -> SorCommandResult:
        ticket_id = _required_id(ticket.get("id"), field="Zendesk ticket ID")
        updated_at = _optional_datetime(ticket.get("updated_at"))
        return SorCommandResult(
            vendor_object_key="tickets",
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
            "vendor_configuration_invalid",
            "Zendesk access token is missing.",
            retryable=False,
            requires_reauthorization=True,
        )
    return value.strip()


def _require_stream(stream_key: str, *, selected: Sequence[str]) -> str:
    if stream_key not in _STREAM_ENTITY:
        raise SorVendorOperationError(
            "vendor_stream_unsupported",
            "This Zendesk adapter does not recognize the requested stream.",
            retryable=False,
        )
    if stream_key not in selected:
        raise SorVendorOperationError(
            "vendor_stream_unavailable",
            "The requested Zendesk stream is not selected for this source.",
            retryable=False,
        )
    return stream_key


def _custom_ticket_field(row: Mapping[str, object]) -> SorDiscoveredField:
    field_id = _required_id(row.get("id"), field="Zendesk ticket field ID")
    options = row.get("custom_field_options")
    choices: tuple[str, ...] = ()
    if isinstance(options, list):
        choices = tuple(
            value
            for item in options
            if isinstance(item, Mapping)
            if (value := _optional_string(item.get("value"))) is not None
        )
    return SorDiscoveredField(
        key=f"custom_field_{field_id}",
        label=_optional_string(row.get("title")) or f"Custom field {field_id}",
        data_type=_zendesk_field_type(row.get("type")),
        nullable=row.get("required") is not True,
        writable=row.get("agent_can_edit") is True,
        choices=choices,
        description=(
            _optional_string(row.get("agent_description"))
            or _optional_string(row.get("description"))
        ),
        group="Zendesk custom fields",
    )


def _zendesk_field_type(value: object) -> str:
    return {
        "checkbox": "boolean",
        "date": "date",
        "decimal": "decimal",
        "integer": "integer",
        "lookup": "reference",
        "multiselect": "string_array",
        "regexp": "text",
        "tagger": "enum",
        "textarea": "text",
        "text": "text",
    }.get(_optional_string(value) or "", "json")


def _custom_field_values(value: object) -> dict[str, object]:
    values: dict[str, object] = {}
    for item in _object_list(value or [], field="Zendesk custom fields"):
        field_id = _required_id(item.get("id"), field="Zendesk custom field ID")
        values[f"custom_field_{field_id}"] = _json_value(item.get("value"))
    return values


def _tag_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise _invalid_response("Zendesk tags must be a list.")
    rows: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, str):
            rows.append({"name": item})
        elif isinstance(item, Mapping):
            row = _object(item, field="Zendesk tag")
            _required_string(row.get("name"), field="Zendesk tag name")
            rows.append(row)
        else:
            raise _invalid_response("Zendesk tag entry is invalid.")
    return rows


def _encode_vendor_cursor(*, stream_key: str, vendor_cursor: str) -> str:
    return _encode_cursor(
        {
            "version": ZENDESK_CURSOR_VERSION,
            "kind": "vendor",
            "stream": stream_key,
            "vendor_cursor": vendor_cursor,
        }
    )


def _decode_vendor_cursor(cursor: str | None, *, stream_key: str) -> str | None:
    if cursor is None:
        return None
    payload = _decode_cursor(cursor, stream_key=stream_key, kind="vendor")
    value = payload.get("vendor_cursor")
    if not isinstance(value, str) or not value or len(value) > 4_096:
        raise _invalid_cursor("Zendesk vendor cursor is invalid.")
    return value


def _encode_expanded_cursor(cursor: _ExpandedCursor, *, stream_key: str) -> str:
    return _encode_cursor(
        {
            "version": ZENDESK_CURSOR_VERSION,
            "kind": "expanded",
            "stream": stream_key,
            "vendor_cursor": cursor.vendor_cursor,
            "offset": cursor.offset,
        }
    )


def _decode_expanded_cursor(
    cursor: str | None,
    *,
    stream_key: str,
) -> _ExpandedCursor:
    if cursor is None:
        return _ExpandedCursor(vendor_cursor=None, offset=0)
    payload = _decode_cursor(cursor, stream_key=stream_key, kind="expanded")
    vendor_cursor = payload.get("vendor_cursor")
    offset = payload.get("offset")
    if vendor_cursor is not None and (
        not isinstance(vendor_cursor, str)
        or not vendor_cursor
        or len(vendor_cursor) > 4_096
    ):
        raise _invalid_cursor("Zendesk page cursor is invalid.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise _invalid_cursor("Zendesk page offset is invalid.")
    return _ExpandedCursor(vendor_cursor=vendor_cursor, offset=offset)


def _encode_event_cursor(cursor: _EventCursor, *, stream_key: str) -> str:
    return _encode_cursor(
        {
            "version": ZENDESK_CURSOR_VERSION,
            "kind": "event",
            "stream": stream_key,
            "start_time": cursor.start_time,
            "offset": cursor.offset,
        }
    )


def _decode_event_cursor(cursor: str | None, *, stream_key: str) -> _EventCursor:
    if cursor is None:
        return _EventCursor(start_time=ZENDESK_INITIAL_START_TIME, offset=0)
    payload = _decode_cursor(cursor, stream_key=stream_key, kind="event")
    start_time = payload.get("start_time")
    offset = payload.get("offset")
    if (
        isinstance(start_time, bool)
        or not isinstance(start_time, int)
        or start_time < 1
    ):
        raise _invalid_cursor("Zendesk event start time is invalid.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise _invalid_cursor("Zendesk event offset is invalid.")
    return _EventCursor(start_time=start_time, offset=offset)


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
        raise _invalid_cursor("Zendesk cursor is invalid.")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _invalid_cursor("Zendesk cursor is invalid.") from error
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) for key in payload
    ):
        raise _invalid_cursor("Zendesk cursor payload is invalid.")
    if (
        payload.get("version") != ZENDESK_CURSOR_VERSION
        or payload.get("kind") != kind
        or payload.get("stream") != stream_key
    ):
        raise _invalid_cursor("Zendesk cursor does not match this stream.")
    return payload


def _cursor_page(data: Mapping[str, object]) -> tuple[bool, str | None]:
    meta = _object(data.get("meta"), field="Zendesk pagination metadata")
    has_more = _required_boolean(
        meta.get("has_more"),
        field="Zendesk pagination has_more",
    )
    cursor = _optional_string(meta.get("after_cursor"))
    return has_more, cursor


def _expand_event_records(
    events: Sequence[Mapping[str, object]],
    *,
    stream_key: str,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for event in events:
        ticket_id = _required_id(
            event.get("ticket_id"),
            field="Zendesk ticket event ticket ID",
        )
        children = _object_list(
            event.get("child_events") or [],
            field="Zendesk ticket child events",
        )
        for child in children:
            event_type = _optional_string(child.get("event_type")) or _optional_string(
                child.get("type")
            )
            if event_type != "Comment":
                continue
            comment = dict(child)
            comment["_ticket_id"] = ticket_id
            if stream_key == "comments":
                records.append(comment)
                continue
            comment_id = _required_id(
                child.get("id"),
                field="Zendesk comment ID",
            )
            for attachment in _object_list(
                child.get("attachments") or [],
                field="Zendesk comment attachments",
            ):
                row = dict(attachment)
                row["_ticket_id"] = ticket_id
                row["_comment_id"] = comment_id
                records.append(row)
    return records


def _expand_metric(row: Mapping[str, object]) -> list[dict[str, object]]:
    expanded: list[dict[str, object]] = []
    for metric in _METRIC_FIELDS:
        value = row.get(metric)
        if not isinstance(value, Mapping):
            continue
        unit = "seconds" if metric.endswith("_in_seconds") else "minutes"
        for basis in ("business", "calendar"):
            measurement = value.get(basis)
            if measurement is None:
                continue
            decimal_value = _optional_decimal(measurement)
            if decimal_value is None:
                continue
            item = dict(row)
            item["_metric"] = metric.removesuffix("_in_minutes").removesuffix(
                "_in_seconds"
            )
            item["_basis"] = basis
            item["_value"] = str(decimal_value)
            item["_unit"] = unit
            expanded.append(item)
    return expanded


def _user_matches_stream(stream_key: str, row: Mapping[str, object]) -> bool:
    role = _optional_string(row.get("role"))
    return (
        role == "end-user" if stream_key == "customers" else role in {"agent", "admin"}
    )


def _require_user_role(stream_key: str, row: Mapping[str, object]) -> None:
    if not _user_matches_stream(stream_key, row):
        raise SorExternalRecordNotFound(
            vendor_object_key=stream_key,
            external_id=_required_id(row.get("id"), field="Zendesk user ID"),
            reason="Zendesk user does not belong to this canonical role stream",
        )


def _comment_external_id(ticket_id: str, comment_id: str) -> str:
    return f"{ticket_id}:{comment_id}"


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
    attachment: Mapping[str, object],
) -> str:
    attachment_id = _required_id(
        attachment.get("id"),
        field="Zendesk attachment ID",
    )
    return _attachment_id(ticket_id, comment_id, attachment_id)


def _split_attachment_id(value: str) -> tuple[str, str, str]:
    parts = value.split(":")
    if len(parts) != 3:
        raise _invalid_command("Zendesk attachment identity is invalid.")
    return _path_id(parts[0]), _path_id(parts[1]), _path_id(parts[2])


def _metric_external_id(metric_id: str, metric: str, basis: str) -> str:
    return f"{metric_id}:{metric}:{basis}"


def _split_metric_id(value: str) -> tuple[str, str, str]:
    parts = value.split(":")
    if (
        len(parts) != 3
        or parts[1]
        not in {
            item.removesuffix("_in_minutes").removesuffix("_in_seconds")
            for item in _METRIC_FIELDS
        }
        or parts[2] not in {"business", "calendar"}
    ):
        raise _invalid_command("Zendesk metric identity is invalid.")
    return _path_id(parts[0]), parts[1], parts[2]


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
    prefix = "zen:ticket:"
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
                "vendor_webhook_invalid",
                "Zendesk webhook timestamp is invalid.",
                retryable=False,
            ) from error
    if parsed.tzinfo is None:
        raise SorVendorOperationError(
            "vendor_webhook_invalid",
            "Zendesk webhook timestamp must include a timezone.",
            retryable=False,
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
    audit: Mapping[str, object],
    *,
    public: bool,
) -> Mapping[str, object]:
    events = _object_list(audit.get("events"), field="Zendesk ticket audit events")
    matches = [
        event
        for event in events
        if event.get("type") == "Comment" and event.get("public") is public
    ]
    if len(matches) != 1:
        raise _invalid_response("Zendesk did not return the exact created comment.")
    return matches[0]


def _add_safe_update(values: dict[str, object], revision: str | None) -> None:
    if revision is None:
        return
    timestamp = _required_datetime(revision, field="Zendesk expected revision")
    values["safe_update"] = True
    values["updated_stamp"] = _revision(timestamp)


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
    if response.status_code == 401:
        raise SorVendorOperationError(
            "vendor_authorization_expired",
            f"Zendesk refused authorization while attempting to {operation}.",
            retryable=False,
            requires_reauthorization=True,
        )
    if response.status_code == 403:
        raise SorVendorOperationError(
            "vendor_forbidden",
            f"Zendesk refused permission to {operation}.",
            retryable=False,
        )
    if response.status_code == 404:
        raise SorVendorOperationError(
            "vendor_resource_unavailable",
            f"Zendesk could not find the resource needed to {operation}.",
            retryable=False,
        )
    if response.status_code in {409, 412}:
        raise SorVendorOperationError(
            "vendor_revision_conflict",
            f"Zendesk rejected stale state while attempting to {operation}.",
            retryable=False,
        )
    if response.status_code == 422:
        raise SorVendorOperationError(
            "vendor_command_invalid",
            f"Zendesk rejected the data used to {operation}.",
            retryable=False,
        )
    if response.status_code == 429:
        raise SorVendorOperationError(
            "vendor_rate_limited",
            "Zendesk rate-limited the source.",
            retryable=True,
        )
    if response.status_code >= 500:
        raise SorVendorOperationError(
            "vendor_server_failed",
            f"Zendesk failed while attempting to {operation}.",
            retryable=True,
        )
    raise SorVendorOperationError(
        "vendor_request_failed",
        f"Zendesk refused the request to {operation}.",
        retryable=False,
    )


def _object(value: object, *, field: str = "Zendesk response") -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _invalid_response(f"{field} must be an object.")
    return dict(value)


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


def _json_value(value: object) -> object | None:
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise _invalid_response("Zendesk value is not JSON compatible.") from error
        return value
    raise _invalid_response("Zendesk value is not JSON compatible.")


def _invalid_command(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_command_invalid",
        message,
        retryable=False,
    )


def _invalid_cursor(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_cursor_invalid",
        message,
        retryable=False,
    )


def _invalid_response(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_response_invalid",
        message,
        retryable=False,
    )


__all__ = [
    "ZENDESK_MANIFEST",
    "ZendeskSupportAdapter",
    "create_zendesk_adapter",
]
