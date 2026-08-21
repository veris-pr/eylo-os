"""Confluence Cloud adapter for Eylo's canonical Documents profile."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.knowledge.contracts import (
    KnowledgeAttachment,
    KnowledgeAuthor,
    KnowledgeBlock,
    KnowledgeDocument,
    KnowledgeProperty,
    KnowledgeSpace,
    KnowledgeVersion,
)
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

CONFLUENCE_API_ORIGIN = "https://api.atlassian.com"
CONFLUENCE_API_VERSION = "confluence-cloud-rest-v2"
CONFLUENCE_CURSOR_VERSION = 1
MAX_CANONICAL_TEXT_CHARS = 1_000_000
MAX_CANONICAL_BODY_BYTES = 1_048_576

READ_CONTENT_SCOPE = "read:confluence-content.all"
READ_SPACE_SCOPE = "read:confluence-space.summary"
READ_PROPERTY_SCOPE = "read:confluence-props"
WRITE_CONTENT_SCOPE = "write:confluence-content"
OFFLINE_SCOPE = "offline_access"

_STREAM_ENTITY = {
    "spaces": "space",
    "pages": "document",
    "page_bodies": "block",
    "versions": "version",
    "properties": "property",
    "attachments": "attachment",
}
_READ_TOOLS = frozenset(
    {
        "docs_search",
        "docs_get",
        "docs_list_children",
        "docs_get_version",
        "docs_describe_fields",
    }
)
_WRITE_TOOLS = frozenset({"docs_create", "docs_update", "docs_append"})
_TOOL_STREAMS = {
    "docs_search": frozenset({"pages"}),
    "docs_get": frozenset({"pages", "page_bodies", "properties", "attachments"}),
    "docs_list_children": frozenset({"pages"}),
    "docs_get_version": frozenset({"pages", "versions"}),
    "docs_describe_fields": frozenset({"pages"}),
    "docs_create": frozenset({"spaces", "pages"}),
    "docs_update": frozenset({"pages"}),
    "docs_append": frozenset({"pages", "page_bodies"}),
}


CONFLUENCE_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.KNOWLEDGE,
    vendor_key="confluence",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                "spaces": "Spaces",
                "pages": "Pages",
                "page_bodies": "Page bodies",
                "versions": "Page versions",
                "properties": "Page properties",
                "attachments": "Page attachments",
            }[stream_key],
            description={
                "spaces": "Visible Confluence spaces.",
                "pages": "Page identity, hierarchy, body, state, and provenance.",
                "page_bodies": "One loss-aware structured body block per page.",
                "versions": "Available page-version metadata.",
                "properties": "Source-native content properties retained for audit.",
                "attachments": "Attachment metadata and source-hosted links.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
        )
        for stream_key, entity in _STREAM_ENTITY.items()
    ),
    readable_entities=frozenset(_STREAM_ENTITY.values()),
    writable_entities=frozenset({"document"}),
    readable_tools=_READ_TOOLS,
    writable_tools=_WRITE_TOOLS,
    change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
    required_scopes={
        "spaces": (READ_SPACE_SCOPE,),
        "pages": (READ_CONTENT_SCOPE,),
        "page_bodies": (READ_CONTENT_SCOPE,),
        "versions": (READ_CONTENT_SCOPE,),
        "properties": (READ_CONTENT_SCOPE, READ_PROPERTY_SCOPE),
        "attachments": (READ_CONTENT_SCOPE,),
    },
    tool_required_scopes={
        tool_name: (WRITE_CONTENT_SCOPE,) for tool_name in _WRITE_TOOLS
    },
    tool_streams=_TOOL_STREAMS,
    mutation_result_streams={tool_name: "pages" for tool_name in _WRITE_TOOLS},
    oauth=SorOAuthSpec(
        authorization_url="https://auth.atlassian.com/authorize",
        token_url="https://auth.atlassian.com/oauth/token",
        base_scopes=(OFFLINE_SCOPE,),
        authorization_params=(("audience", "api.atlassian.com"), ("prompt", "consent")),
        token_request_format="json",
        instance_host_suffixes=("atlassian.net",),
        operator_instance_origin=True,
    ),
    fixed_origin=CONFLUENCE_API_ORIGIN,
    requires_instance_origin=True,
    supports_history=True,
    supports_attachments=True,
    supports_structured_documents=True,
)


def _field(
    key: str,
    label: str,
    data_type: str,
    *,
    nullable: bool = True,
    writable: bool = False,
) -> SorDiscoveredField:
    return SorDiscoveredField(
        key=key,
        label=label,
        data_type=data_type,
        nullable=nullable,
        writable=writable,
        group="Confluence",
    )


_SCHEMA_FIELDS = {
    "spaces": (
        _field("name", "Name", "text", nullable=False),
        _field("kind", "Kind", "text", nullable=False),
    ),
    "pages": (
        _field("title", "Title", "text", nullable=False, writable=True),
        _field("space_external_id", "Space ID", "reference", writable=True),
        _field("parent_external_id", "Parent page ID", "reference", writable=True),
        _field("path", "Path", "string_array"),
        _field("source_format", "Source format", "text", nullable=False),
        _field("normalized_text", "Content", "text", writable=True),
        _field("source_body", "Source body", "bounded_json"),
        _field("content_hash", "Content hash", "text", nullable=False),
        _field("version", "Version", "text"),
        _field("lifecycle_state", "State", "text"),
        _field("author_external_id", "Author ID", "reference"),
        _field("label_external_ids", "Labels", "string_array"),
        _field("unsupported_blocks", "Unsupported macros", "string_array"),
        _field("source_created_at", "Created", "timestamp"),
        _field("source_updated_at", "Updated", "timestamp"),
    ),
    "page_bodies": (
        _field("document_external_id", "Document ID", "reference", nullable=False),
        _field("parent_external_id", "Parent block ID", "reference"),
        _field("kind", "Kind", "text", nullable=False),
        _field("order", "Order", "integer", nullable=False),
        _field("normalized_text", "Content", "text"),
        _field("source_body", "Source body", "bounded_json"),
        _field("supported", "Supported", "boolean", nullable=False),
        _field("source_created_at", "Created", "timestamp"),
        _field("source_updated_at", "Updated", "timestamp"),
    ),
    "versions": (
        _field("document_external_id", "Document ID", "reference", nullable=False),
        _field("number", "Version", "text", nullable=False),
        _field("author_external_id", "Author ID", "reference"),
        _field("message", "Message", "text"),
        _field("source_format", "Source format", "text"),
        _field("normalized_text", "Content", "text"),
        _field("source_body", "Source body", "bounded_json"),
        _field("source_created_at", "Created", "timestamp", nullable=False),
    ),
    "properties": (
        _field("document_external_id", "Document ID", "reference", nullable=False),
        _field("key", "Key", "text", nullable=False),
        _field("label", "Label", "text", nullable=False),
        _field("value_type", "Value type", "text", nullable=False),
        _field("value", "Value", "bounded_json"),
        _field("source_updated_at", "Updated", "timestamp"),
    ),
    "attachments": (
        _field("document_external_id", "Document ID", "reference", nullable=False),
        _field("name", "Name", "text", nullable=False),
        _field("media_type", "Media type", "text"),
        _field("size_bytes", "Size", "integer"),
        _field("source_url", "Source URL", "link"),
        _field("source_url_expires_at", "URL expires", "timestamp"),
    ),
}


@dataclass(frozen=True, slots=True)
class _NestedCursor:
    page_cursor: str | None
    current_page_id: str | None
    current_page_is_last: bool
    child_cursor: str | None


class ConfluenceKnowledgeAdapter:
    """Translate one exact Confluence site into canonical document records."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "confluence":
            raise ValueError("Confluence adapter requires the confluence vendor key.")
        if context.auth_kind is not ConnectionAuthKind.OAUTH2:
            raise ValueError("Confluence SOR requires OAuth 2.0.")
        self._context = context
        self._site_origin = _confluence_site_origin(context.instance_origin)
        self._cloud_id: str | None = None
        self._site_name: str | None = None
        self._client = SorJsonHttpClient(
            origin=CONFLUENCE_API_ORIGIN,
            authorization=f"Bearer {_credential(context.credentials, 'access_token')}",
            transport=transport,
            response_body_limit=8_388_608,
        )

    async def verify_connection(self) -> SorConnectionVerification:
        cloud_id, site_name = await self._resolve_site()
        response = await self._request("/spaces", query={"limit": 1})
        _object(_expect(response, operation="verify Confluence site"), field="spaces")
        return SorConnectionVerification(
            account_external_id=cloud_id,
            account_display_name=site_name or "Confluence Cloud site",
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=CONFLUENCE_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise _invalid_operation(
                "source_selection_empty",
                "The Confluence source selects no streams.",
            )
        streams = {stream.key: stream for stream in CONFLUENCE_MANIFEST.streams}
        objects = tuple(
            SorDiscoveredObject(
                key=stream_key,
                label=streams[_require_stream(
                    stream_key,
                    selected=self._context.selected_objects,
                )].label,
                fields=_SCHEMA_FIELDS[stream_key],
            )
            for stream_key in self._context.selected_objects
        )
        return SorDiscoveredSchema(
            objects=objects,
            vendor_api_version=CONFLUENCE_API_VERSION,
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
        record_id = _identifier(external_id)
        if stream_key == "spaces":
            response = await self._request(f"/spaces/{record_id}")
            return self._external_space(_required_response(response, stream_key, record_id))
        if stream_key in {"pages", "page_bodies"}:
            page_id = _body_page_id(record_id) if stream_key == "page_bodies" else record_id
            response = await self._request(
                f"/pages/{page_id}",
                query={"body-format": "storage"},
            )
            page = _required_response(response, stream_key, record_id)
            return (
                self._external_page(page)
                if stream_key == "pages"
                else self._external_body(page)
            )
        if stream_key == "versions":
            page_id, version = _split_composite(record_id, label="version")
            response = await self._request(f"/pages/{page_id}/versions/{version}")
            return self._external_version(
                page_id,
                _required_response(response, stream_key, record_id),
            )
        if stream_key == "properties":
            page_id, property_id = _split_composite(record_id, label="property")
            response = await self._request(
                f"/pages/{page_id}/properties/{property_id}"
            )
            return self._external_property(
                page_id,
                _required_response(response, stream_key, record_id),
            )
        response = await self._request(f"/attachments/{record_id}")
        attachment = _required_response(response, stream_key, record_id)
        page_id = _required_id(attachment.get("pageId"), field="attachment page ID")
        return self._external_attachment(page_id, attachment)

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "Confluence deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Confluence webhooks are not available in this adapter revision."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Confluence webhooks are not available in this adapter revision."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "Confluence webhooks are not available in this adapter revision."
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        raise SorCapabilityUnavailable(
            "Confluence webhooks are not available in this adapter revision."
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        raise SorCapabilityUnavailable(
            "Confluence webhooks are not available in this adapter revision."
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise _invalid_operation(
                "vendor_tool_unsupported",
                "This Confluence adapter does not execute the requested document action.",
            )
        if command.tool_name == "docs_create":
            return await self._create_page(command)
        target_id = _required_target(command)
        return await self._replace_page(
            target_id,
            command,
            append=command.tool_name == "docs_append",
        )

    def normalize_space(self, record: SorExternalRecord) -> KnowledgeSpace:
        return KnowledgeSpace(
            external_id=record.external_id,
            name=_required_string(record.payload.get("name"), field="space name"),
            kind=_required_string(record.payload.get("kind"), field="space kind"),
            source_url=record.source_url,
        )

    def normalize_document(self, record: SorExternalRecord) -> KnowledgeDocument:
        values = record.payload
        return KnowledgeDocument(
            external_id=record.external_id,
            title=_required_string(values.get("title"), field="page title"),
            space_external_id=_optional_string(values.get("space_external_id")),
            parent_external_id=_optional_string(values.get("parent_external_id")),
            path=_string_tuple(values.get("path"), field="page path"),
            source_format=_required_string(
                values.get("source_format"), field="page source format"
            ),
            normalized_text=_bounded_string(
                values.get("normalized_text"),
                field="page content",
                allow_empty=True,
            ),
            source_body=_json_value(values.get("source_body")),
            content_hash=_required_string(
                values.get("content_hash"), field="page content hash"
            ),
            version=_optional_string(values.get("version")),
            lifecycle_state=_optional_string(values.get("lifecycle_state")),
            author_external_id=_optional_string(values.get("author_external_id")),
            label_external_ids=_string_tuple(
                values.get("label_external_ids"), field="page labels"
            ),
            unsupported_blocks=_string_tuple(
                values.get("unsupported_blocks"), field="page unsupported macros"
            ),
            source_created_at=record.source_created_at,
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
        )

    def normalize_block(self, record: SorExternalRecord) -> KnowledgeBlock:
        values = record.payload
        return KnowledgeBlock(
            external_id=record.external_id,
            document_external_id=_required_string(
                values.get("document_external_id"), field="body document ID"
            ),
            parent_external_id=None,
            kind="confluence_storage",
            order=0,
            normalized_text=_optional_string(values.get("normalized_text")),
            source_body=_json_value(values.get("source_body")),
            supported=_required_boolean(values.get("supported"), field="body support"),
            source_created_at=record.source_created_at,
            source_updated_at=record.source_updated_at,
        )

    def normalize_version(self, record: SorExternalRecord) -> KnowledgeVersion:
        values = record.payload
        return KnowledgeVersion(
            external_id=record.external_id,
            document_external_id=_required_string(
                values.get("document_external_id"), field="version document ID"
            ),
            number=_required_string(values.get("number"), field="version number"),
            author_external_id=_optional_string(values.get("author_external_id")),
            message=_optional_string(values.get("message")),
            source_format=None,
            normalized_text=None,
            source_body=None,
            created_at=_required_datetime(
                values.get("source_created_at"), field="version creation"
            ),
        )

    def normalize_property(self, record: SorExternalRecord) -> KnowledgeProperty:
        values = record.payload
        return KnowledgeProperty(
            external_id=record.external_id,
            document_external_id=_required_string(
                values.get("document_external_id"), field="property document ID"
            ),
            key=_required_string(values.get("key"), field="property key"),
            label=_required_string(values.get("label"), field="property label"),
            value_type=_required_string(
                values.get("value_type"), field="property value type"
            ),
            value=_json_scalar(values.get("value")),
            source_updated_at=record.source_updated_at,
        )

    def normalize_attachment(self, record: SorExternalRecord) -> KnowledgeAttachment:
        values = record.payload
        return KnowledgeAttachment(
            external_id=record.external_id,
            document_external_id=_required_string(
                values.get("document_external_id"), field="attachment document ID"
            ),
            name=_required_string(values.get("name"), field="attachment name"),
            media_type=_optional_string(values.get("media_type")),
            size_bytes=_optional_integer(values.get("size_bytes"), field="attachment size"),
            source_url=record.source_url,
            source_url_expires_at=None,
        )

    def normalize_author(self, record: SorExternalRecord) -> KnowledgeAuthor:
        raise SorCapabilityUnavailable(
            "Confluence author profiles are not synchronized in this adapter revision."
        )

    async def close(self) -> None:
        return None

    async def _resolve_site(self) -> tuple[str, str | None]:
        if self._cloud_id is not None:
            return self._cloud_id, self._site_name
        response = await self._client.request("/oauth/token/accessible-resources")
        rows = _object_list(
            _expect(response, operation="list accessible Confluence sites"),
            field="Atlassian accessible resources",
        )
        matches = [
            row
            for row in rows
            if _normalized_origin(row.get("url")) == self._site_origin
            and any("confluence" in scope for scope in _string_list(row.get("scopes")))
        ]
        if len(matches) != 1:
            raise SorVendorOperationError(
                "vendor_site_unavailable",
                "The authorized Atlassian account does not expose the configured Confluence site.",
                retryable=False,
                requires_reauthorization=True,
            )
        site = matches[0]
        self._cloud_id = _required_id(site.get("id"), field="Confluence cloud ID")
        self._site_name = _optional_string(site.get("name"))
        return self._cloud_id, self._site_name

    async def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        query: Mapping[str, object] | None = None,
        payload: object | None = None,
        idempotency_key: str | None = None,
    ) -> SorJsonResponse:
        cloud_id, _name = await self._resolve_site()
        return await self._client.request(
            f"/ex/confluence/{_identifier(cloud_id)}/wiki/api/v2{path}",
            method=method,
            query=query,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    async def _read_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        stream_key = _require_stream(stream_key, selected=self._context.selected_objects)
        if limit <= 0:
            raise _invalid_operation(
                "vendor_page_invalid",
                "Confluence page limit must be positive.",
            )
        page_limit = min(limit, 100)
        if stream_key == "spaces":
            response = await self._request(
                "/spaces",
                query=_cursor_query(cursor, limit=page_limit),
            )
            data = _object(_expect(response, operation="list Confluence spaces"))
            rows = _object_list(data.get("results"), field="Confluence spaces")
            next_cursor = _next_cursor(response, data)
            return SorRecordPage(
                records=tuple(self._external_space(row) for row in rows),
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
            )
        if stream_key in {"pages", "page_bodies"}:
            response = await self._request(
                "/pages",
                query={
                    **_cursor_query(cursor, limit=page_limit),
                    "body-format": "storage",
                },
            )
            data = _object(_expect(response, operation="list Confluence pages"))
            rows = _object_list(data.get("results"), field="Confluence pages")
            next_cursor = _next_cursor(response, data)
            convert = (
                self._external_page
                if stream_key == "pages"
                else self._external_body
            )
            return SorRecordPage(
                records=tuple(convert(row) for row in rows),
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
            )
        return await self._read_nested(
            stream_key=stream_key,
            cursor=cursor,
            limit=page_limit,
        )

    async def _read_nested(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_nested_cursor(cursor, stream_key=stream_key)
        scans = 0
        while scans < 25:
            if checkpoint.current_page_id is None:
                page_id, page_cursor, page_is_last = await self._next_page(
                    checkpoint.page_cursor
                )
                if page_id is None:
                    return SorRecordPage(records=(), next_cursor=None, has_more=False)
                checkpoint = _NestedCursor(
                    page_cursor=page_cursor,
                    current_page_id=page_id,
                    current_page_is_last=page_is_last,
                    child_cursor=None,
                )
            assert checkpoint.current_page_id is not None
            rows, child_cursor = await self._read_children(
                stream_key=stream_key,
                page_id=checkpoint.current_page_id,
                cursor=checkpoint.child_cursor,
                limit=limit,
            )
            records = tuple(
                self._external_nested(stream_key, checkpoint.current_page_id, row)
                for row in rows
            )
            if child_cursor is not None:
                if not records:
                    raise _invalid_response(
                        f"Confluence returned an empty partial {stream_key} page."
                    )
                next_checkpoint = _NestedCursor(
                    page_cursor=checkpoint.page_cursor,
                    current_page_id=checkpoint.current_page_id,
                    current_page_is_last=checkpoint.current_page_is_last,
                    child_cursor=child_cursor,
                )
                return SorRecordPage(
                    records=records,
                    next_cursor=_encode_nested_cursor(
                        next_checkpoint,
                        stream_key=stream_key,
                    ),
                    has_more=True,
                )
            if checkpoint.current_page_is_last:
                return SorRecordPage(records=records, next_cursor=None, has_more=False)
            next_checkpoint = _NestedCursor(
                page_cursor=checkpoint.page_cursor,
                current_page_id=None,
                current_page_is_last=False,
                child_cursor=None,
            )
            if records:
                return SorRecordPage(
                    records=records,
                    next_cursor=_encode_nested_cursor(
                        next_checkpoint,
                        stream_key=stream_key,
                    ),
                    has_more=True,
                )
            checkpoint = next_checkpoint
            scans += 1
        return SorRecordPage(
            records=(),
            next_cursor=_encode_nested_cursor(checkpoint, stream_key=stream_key),
            has_more=True,
        )

    async def _next_page(
        self,
        cursor: str | None,
    ) -> tuple[str | None, str | None, bool]:
        response = await self._request(
            "/pages",
            query={**_cursor_query(cursor, limit=1), "body-format": "storage"},
        )
        data = _object(_expect(response, operation="scan Confluence pages"))
        rows = _object_list(data.get("results"), field="Confluence pages")
        next_cursor = _next_cursor(response, data)
        if len(rows) > 1 or (not rows and next_cursor is not None):
            raise _invalid_response("Confluence returned an invalid page scan.")
        if not rows:
            return None, None, True
        return (
            _required_id(rows[0].get("id"), field="Confluence page ID"),
            next_cursor,
            next_cursor is None,
        )

    async def _read_children(
        self,
        *,
        stream_key: str,
        page_id: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict[str, object]], str | None]:
        endpoint = {
            "versions": f"/pages/{page_id}/versions",
            "properties": f"/pages/{page_id}/properties",
            "attachments": f"/pages/{page_id}/attachments",
        }[stream_key]
        response = await self._request(
            endpoint,
            query=_cursor_query(cursor, limit=limit),
        )
        data = _object(_expect(response, operation=f"list Confluence {stream_key}"))
        rows = _object_list(data.get("results"), field=f"Confluence {stream_key}")
        return rows, _next_cursor(response, data)

    def _external_nested(
        self,
        stream_key: str,
        page_id: str,
        row: Mapping[str, object],
    ) -> SorExternalRecord:
        if stream_key == "versions":
            return self._external_version(page_id, row)
        if stream_key == "properties":
            return self._external_property(page_id, row)
        return self._external_attachment(page_id, row)

    def _external_space(self, row: Mapping[str, object]) -> SorExternalRecord:
        space_id = _required_id(row.get("id"), field="Confluence space ID")
        links = _optional_object(row.get("_links"))
        return SorExternalRecord(
            vendor_object_key="spaces",
            external_id=space_id,
            payload={
                "name": _required_string(row.get("name"), field="Confluence space name"),
                "kind": _optional_string(row.get("type")) or "space",
            },
            source_url=self._source_url(links.get("webui")),
        )

    def _external_page(self, row: Mapping[str, object]) -> SorExternalRecord:
        page_id = _required_id(row.get("id"), field="Confluence page ID")
        body = _storage_body(row)
        normalized_text = _storage_text(body)
        version = _optional_object(row.get("version"))
        version_number = _optional_integer(version.get("number"), field="page version")
        source_updated_at = _optional_datetime(version.get("createdAt"))
        source_created_at = _optional_datetime(row.get("createdAt"))
        links = _optional_object(row.get("_links"))
        source_body = _canonical_source_body(body)
        return SorExternalRecord(
            vendor_object_key="pages",
            external_id=page_id,
            payload={
                "title": _required_string(row.get("title"), field="Confluence page title"),
                "space_external_id": _optional_id(row.get("spaceId")),
                "parent_external_id": _optional_id(row.get("parentId")),
                "path": [],
                "source_format": "confluence_storage",
                "normalized_text": normalized_text,
                "source_body": source_body,
                "content_hash": _content_hash(normalized_text, source_body),
                "version": str(version_number) if version_number is not None else None,
                "lifecycle_state": _optional_string(row.get("status")),
                "author_external_id": _optional_id(row.get("authorId")),
                "label_external_ids": [],
                "unsupported_blocks": list(_unsupported_macros(body)),
                "source_created_at": source_created_at,
                "source_updated_at": source_updated_at,
            },
            source_created_at=source_created_at,
            source_updated_at=source_updated_at,
            source_revision=str(version_number) if version_number is not None else None,
            source_url=self._source_url(links.get("webui")),
        )

    def _external_body(self, row: Mapping[str, object]) -> SorExternalRecord:
        page = self._external_page(row)
        body = page.payload["source_body"]
        unsupported = page.payload["unsupported_blocks"]
        return SorExternalRecord(
            vendor_object_key="page_bodies",
            external_id=f"{page.external_id}:body",
            payload={
                "document_external_id": page.external_id,
                "parent_external_id": None,
                "kind": "confluence_storage",
                "order": 0,
                "normalized_text": page.payload["normalized_text"],
                "source_body": body,
                "supported": not bool(unsupported),
                "source_created_at": page.source_created_at,
                "source_updated_at": page.source_updated_at,
            },
            source_created_at=page.source_created_at,
            source_updated_at=page.source_updated_at,
            source_revision=page.source_revision,
            source_url=page.source_url,
        )

    def _external_version(
        self,
        page_id: str,
        row: Mapping[str, object],
    ) -> SorExternalRecord:
        number = _required_integer(row.get("number"), field="Confluence version number")
        created_at = _required_datetime(
            row.get("createdAt"), field="Confluence version creation"
        )
        return SorExternalRecord(
            vendor_object_key="versions",
            external_id=f"{page_id}:{number}",
            payload={
                "document_external_id": page_id,
                "number": str(number),
                "author_external_id": _optional_id(row.get("authorId")),
                "message": _optional_string(row.get("message")),
                "source_format": None,
                "normalized_text": None,
                "source_body": None,
                "source_created_at": created_at,
            },
            source_created_at=created_at,
            source_revision=str(number),
        )

    def _external_property(
        self,
        page_id: str,
        row: Mapping[str, object],
    ) -> SorExternalRecord:
        property_id = _required_id(row.get("id"), field="Confluence property ID")
        key = _required_string(row.get("key"), field="Confluence property key")
        version = _optional_object(row.get("version"))
        updated_at = _optional_datetime(version.get("createdAt"))
        value = _json_scalar(row.get("value"))
        return SorExternalRecord(
            vendor_object_key="properties",
            external_id=f"{page_id}:{property_id}",
            payload={
                "document_external_id": page_id,
                "key": key,
                "label": key,
                "value_type": _json_type(value),
                "value": value,
                "source_updated_at": updated_at,
            },
            source_updated_at=updated_at,
            source_revision=(
                str(version_number)
                if (version_number := _optional_integer(
                    version.get("number"), field="property version"
                ))
                is not None
                else None
            ),
        )

    def _external_attachment(
        self,
        page_id: str,
        row: Mapping[str, object],
    ) -> SorExternalRecord:
        attachment_id = _required_id(row.get("id"), field="Confluence attachment ID")
        links = _optional_object(row.get("_links"))
        return SorExternalRecord(
            vendor_object_key="attachments",
            external_id=attachment_id,
            payload={
                "document_external_id": page_id,
                "name": _required_string(
                    row.get("title"), field="Confluence attachment name"
                ),
                "media_type": _optional_string(row.get("mediaType")),
                "size_bytes": _optional_integer(
                    row.get("fileSize"), field="attachment size"
                ),
                "source_url": self._source_url(
                    row.get("downloadLink") or links.get("download")
                ),
                "source_url_expires_at": None,
            },
            source_created_at=_optional_datetime(row.get("createdAt")),
            source_updated_at=_optional_datetime(row.get("createdAt")),
            source_url=self._source_url(
                row.get("downloadLink") or links.get("download")
            ),
        )

    async def _create_page(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command("Creating a Confluence page cannot target a record.")
        payload = _document_write_payload(command.payload, create=True)
        request: dict[str, object] = {
            "spaceId": payload["space_external_id"],
            "status": "current",
            "title": payload["title"],
            "body": _plain_text_body(payload.get("normalized_text")),
        }
        if payload.get("parent_external_id") is not None:
            request["parentId"] = payload["parent_external_id"]
        try:
            response = await self._request(
                "/pages",
                method="POST",
                payload=request,
                idempotency_key=command.idempotency_key,
            )
            page = _object(_expect_mutation(response, operation="create Confluence page"))
        except SorVendorOperationError as error:
            if error.code in {
                "vendor_timeout",
                "vendor_transport_failed",
                "vendor_server_failed",
            }:
                raise SorVendorOperationError(
                    "vendor_mutation_outcome_unknown",
                    "Confluence may have created the page; reconcile before retrying.",
                    retryable=False,
                ) from error
            raise
        return self._command_result(page, response=response)

    async def _replace_page(
        self,
        page_id: str,
        command: SorCommandRequest,
        *,
        append: bool,
    ) -> SorCommandResult:
        current_response = await self._request(
            f"/pages/{page_id}",
            query={"body-format": "storage"},
        )
        current = _required_response(current_response, "pages", page_id)
        version = _required_integer(
            _object(current.get("version"), field="page version").get("number"),
            field="Confluence page version",
        )
        if (
            command.expected_source_revision is not None
            and command.expected_source_revision != str(version)
        ):
            raise _invalid_operation(
                "vendor_source_conflict",
                "The Confluence page changed after the Agent read it.",
            )
        payload = _document_write_payload(command.payload, create=False)
        current_body = _storage_body(current)
        current_title = _required_string(
            current.get("title"),
            field="Confluence page title",
        )
        requested_text = payload.get("normalized_text")
        if append:
            if not isinstance(requested_text, str) or not requested_text:
                raise _invalid_command("Appending to Confluence requires normalized_text.")
            storage_body = _bounded_storage_body(
                current_body + _plain_text_storage(requested_text),
                response=False,
            )
        elif requested_text is None:
            storage_body = current_body
        elif isinstance(requested_text, str):
            storage_body = _plain_text_storage(requested_text)
        else:
            raise _invalid_command("Confluence normalized_text must be text.")
        response = await self._request(
            f"/pages/{page_id}",
            method="PUT",
            payload={
                "id": page_id,
                "status": "current",
                "title": payload.get("title") or current_title,
                "body": {"representation": "storage", "value": storage_body},
                "version": {"number": version + 1},
            },
            idempotency_key=command.idempotency_key,
        )
        page = _object(_expect_mutation(response, operation="update Confluence page"))
        return self._command_result(page, response=response)

    def _command_result(
        self,
        page: Mapping[str, object],
        *,
        response: SorJsonResponse,
    ) -> SorCommandResult:
        page_id = _required_id(page.get("id"), field="Confluence page ID")
        version = _optional_object(page.get("version"))
        number = _optional_integer(version.get("number"), field="page version")
        links = _optional_object(page.get("_links"))
        request_ids = response.header_values("x-request-id")
        return SorCommandResult(
            vendor_object_key="pages",
            external_id=page_id,
            external_request_id=request_ids[0] if request_ids else None,
            source_revision=str(number) if number is not None else None,
            source_url=self._source_url(links.get("webui")),
            response={"status": "accepted"},
        )

    def _source_url(self, value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = value.strip()
        parsed = urlsplit(candidate)
        if parsed.scheme or parsed.netloc:
            if _normalized_origin(f"{parsed.scheme}://{parsed.netloc}") != self._site_origin:
                return None
            if parsed.username is not None or parsed.password is not None:
                return None
            return candidate
        if not candidate.startswith("/") or candidate.startswith("//"):
            return None
        path = candidate if candidate.startswith("/wiki/") else f"/wiki{candidate}"
        return f"{self._site_origin}{path}"


def create_confluence_adapter(context: SorAdapterContext) -> ConfluenceKnowledgeAdapter:
    """Construct the production Confluence adapter for the explicit registry."""
    return ConfluenceKnowledgeAdapter(context)


class _StorageTextParser(HTMLParser):
    """Bounded best-effort text projection that keeps source XHTML separately."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() in {"br", "li", "p", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _storage_text(value: str) -> str:
    parser = _StorageTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception as error:
        raise _invalid_response("Confluence returned malformed storage content.") from error
    return re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts)).strip()


def _unsupported_macros(value: str) -> tuple[str, ...]:
    names = re.findall(
        r"<ac:structured-macro\b[^>]*\bac:name=[\"']([^\"']+)[\"']",
        value,
        flags=re.IGNORECASE,
    )
    return tuple(dict.fromkeys(name.strip() for name in names if name.strip()))


def _storage_body(row: Mapping[str, object]) -> str:
    body = _object(row.get("body"), field="Confluence page body")
    storage = _object(body.get("storage"), field="Confluence storage body")
    value = storage.get("value")
    if not isinstance(value, str):
        raise _invalid_response("Confluence storage content is invalid.")
    return _bounded_storage_body(value, response=True)


def _content_hash(normalized_text: str, source_body: object) -> str:
    encoded = json.dumps(
        {"normalized_text": normalized_text, "source_body": source_body},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _canonical_source_body(value: str) -> dict[str, object]:
    body: dict[str, object] = {
        "representation": "storage",
        "value": value,
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if len(encoded) > MAX_CANONICAL_BODY_BYTES:
        raise _invalid_response("Confluence storage content is too large.")
    return body


def _plain_text_body(value: object) -> dict[str, str]:
    text = value if isinstance(value, str) else ""
    return {"representation": "storage", "value": _plain_text_storage(text)}


def _plain_text_storage(value: str) -> str:
    if len(value) > MAX_CANONICAL_TEXT_CHARS:
        raise _invalid_command("Confluence document content is too large.")
    paragraphs = [
        f"<p>{html.escape(line)}</p>" if line else "<p />"
        for line in value.split("\n")
    ]
    return _bounded_storage_body(
        "".join(paragraphs) or "<p />",
        response=False,
    )


def _bounded_storage_body(value: str, *, response: bool) -> str:
    if len(value.encode()) > MAX_CANONICAL_BODY_BYTES:
        if response:
            raise _invalid_response("Confluence storage content is too large.")
        raise _invalid_command("Confluence document content is too large.")
    return value


def _document_write_payload(
    payload: Mapping[str, object],
    *,
    create: bool,
) -> dict[str, object]:
    allowed = {"title", "space_external_id", "parent_external_id", "normalized_text"}
    if not payload or set(payload) - allowed:
        raise _invalid_command(
            "Confluence document writes accept only mapped title, space, parent, and content."
        )
    result: dict[str, object] = {}
    title = payload.get("title")
    if title is not None:
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > MAX_CANONICAL_TEXT_CHARS
        ):
            raise _invalid_command("Confluence title is invalid.")
        result["title"] = title.strip()
    for key in ("space_external_id", "parent_external_id"):
        value = payload.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise _invalid_command(f"Confluence {key} must be text.")
            result[key] = _identifier(value)
    normalized_text = payload.get("normalized_text")
    if normalized_text is not None:
        if (
            not isinstance(normalized_text, str)
            or len(normalized_text) > MAX_CANONICAL_TEXT_CHARS
        ):
            raise _invalid_command("Confluence normalized_text is invalid.")
        result["normalized_text"] = normalized_text
    if create and (
        not isinstance(result.get("title"), str)
        or not isinstance(result.get("space_external_id"), str)
    ):
        raise _invalid_command("Creating a Confluence page requires title and space_external_id.")
    return result


def _cursor_query(cursor: str | None, *, limit: int) -> dict[str, object]:
    query: dict[str, object] = {"limit": limit}
    if cursor is not None:
        if not cursor or len(cursor) > 4_096:
            raise _invalid_cursor("collection")
        query["cursor"] = cursor
    return query


def _next_cursor(response: SorJsonResponse, data: Mapping[str, object]) -> str | None:
    links = _optional_object(data.get("_links"))
    candidate = _optional_string(links.get("next"))
    if candidate is None:
        for link in response.header_values("link"):
            match = re.search(r"<([^>]+)>\s*;\s*rel=[\"']?next[\"']?", link)
            if match is not None:
                candidate = match.group(1)
                break
    if candidate is None:
        return None
    values = parse_qs(urlsplit(candidate).query).get("cursor", [])
    if len(values) != 1 or not values[0] or len(values[0]) > 4_096:
        raise _invalid_cursor("collection")
    return values[0]


def _decode_nested_cursor(value: str | None, *, stream_key: str) -> _NestedCursor:
    if value is None:
        return _NestedCursor(None, None, False, None)
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid_cursor(stream_key) from error
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "child_cursor",
            "current_page_id",
            "current_page_is_last",
            "page_cursor",
            "stream",
            "v",
        }
        or payload.get("v") != CONFLUENCE_CURSOR_VERSION
        or payload.get("stream") != stream_key
    ):
        raise _invalid_cursor(stream_key)
    page_cursor = _optional_cursor(payload.get("page_cursor"), stream_key=stream_key)
    child_cursor = _optional_cursor(payload.get("child_cursor"), stream_key=stream_key)
    page_id = _optional_string(payload.get("current_page_id"))
    is_last = payload.get("current_page_is_last")
    if not isinstance(is_last, bool):
        raise _invalid_cursor(stream_key)
    if page_id is None:
        if child_cursor is not None or is_last:
            raise _invalid_cursor(stream_key)
    elif child_cursor is None:
        raise _invalid_cursor(stream_key)
    if page_id is not None:
        _identifier(page_id)
    return _NestedCursor(page_cursor, page_id, is_last, child_cursor)


def _encode_nested_cursor(cursor: _NestedCursor, *, stream_key: str) -> str:
    return json.dumps(
        {
            "child_cursor": cursor.child_cursor,
            "current_page_id": cursor.current_page_id,
            "current_page_is_last": cursor.current_page_is_last,
            "page_cursor": cursor.page_cursor,
            "stream": stream_key,
            "v": CONFLUENCE_CURSOR_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _optional_cursor(value: object, *, stream_key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 4_096:
        raise _invalid_cursor(stream_key)
    return value


def _required_response(
    response: SorJsonResponse,
    stream_key: str,
    external_id: str,
) -> dict[str, object]:
    if response.status_code in {404, 410}:
        raise SorExternalRecordNotFound(
            vendor_object_key=stream_key,
            external_id=external_id,
        )
    return _object(_expect(response, operation="read Confluence record"))


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.status_code in {401, 403}:
        raise SorVendorOperationError(
            "vendor_authorization_failed",
            f"Confluence refused authorization while attempting to {operation}.",
            retryable=False,
            requires_reauthorization=True,
            refreshable_authorization=response.status_code == 401,
        )
    if response.status_code == 429:
        raise SorVendorOperationError(
            "vendor_rate_limited",
            "Confluence rate limited the operation.",
            retryable=True,
        )
    if response.status_code >= 500:
        raise SorVendorOperationError(
            "vendor_server_failed",
            "Confluence could not complete the operation.",
            retryable=True,
        )
    if not response.ok:
        raise _invalid_operation(
            "vendor_request_rejected",
            f"Confluence rejected the request while attempting to {operation}.",
        )
    return response.data


def _expect_mutation(response: SorJsonResponse, *, operation: str) -> object:
    value = _expect(response, operation=operation)
    if response.status_code not in {200, 201}:
        raise _invalid_response("Confluence returned an unexpected mutation status.")
    return value


def _object(value: object, *, field: str = "Confluence response") -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _invalid_response(f"{field} is invalid.")
    return value


def _optional_object(value: object) -> dict[str, object]:
    return _object(value) if isinstance(value, dict) else {}


def _object_list(value: object, *, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise _invalid_response(f"{field} is invalid.")
    return [_object(item, field=field) for item in value]


def _json_value(value: object) -> dict | list | str | None:
    if value is None or isinstance(value, (dict, list, str)):
        return value
    raise _invalid_response("Confluence returned invalid source JSON.")


def _json_scalar(value: object) -> dict | list | str | int | float | bool | None:
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    raise _invalid_response("Confluence returned an invalid property value.")


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "array"
    return "object"


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1_000_000:
        raise _invalid_response(f"Confluence {field} is invalid.")
    return value


def _bounded_string(
    value: object,
    *,
    field: str,
    allow_empty: bool,
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value)
        or len(value) > MAX_CANONICAL_TEXT_CHARS
    ):
        raise _invalid_response(f"Confluence {field} is invalid.")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _required_id(value: object, *, field: str) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise _invalid_response(f"Confluence {field} is invalid.")
    return _identifier(value)


def _optional_id(value: object) -> str | None:
    if value is None:
        return None
    return _required_id(value, field="source ID")


def _identifier(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._~-]{1,512}", normalized):
        raise _invalid_operation(
            "vendor_identifier_invalid",
            "A Confluence source identifier is invalid.",
        )
    return normalized


def _required_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_response(f"Confluence {field} is invalid.")
    return value


def _optional_integer(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    return _required_integer(value, field=field)


def _required_boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_response(f"Confluence {field} is invalid.")
    return value


def _required_datetime(value: object, *, field: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise _invalid_response(f"Confluence {field} is invalid.")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise _invalid_response(f"Confluence {field} is invalid.")
    return tuple(value)


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid_operation(
            "vendor_credentials_invalid",
            "Confluence credentials are unavailable.",
        )
    return value


def _required_target(command: SorCommandRequest) -> str:
    if command.target_external_id is None:
        raise _invalid_command("A Confluence document update requires a target page.")
    return _identifier(command.target_external_id)


def _require_stream(value: str, *, selected: tuple[str, ...]) -> str:
    if value not in _STREAM_ENTITY or value not in selected:
        raise _invalid_operation(
            "vendor_stream_unsupported",
            "The requested Confluence stream is not selected for this source.",
        )
    return value


def _body_page_id(value: str) -> str:
    if not value.endswith(":body"):
        raise _invalid_operation(
            "vendor_identifier_invalid",
            "A Confluence body identity is invalid.",
        )
    return _identifier(value.removesuffix(":body"))


def _split_composite(value: str, *, label: str) -> tuple[str, str]:
    parts = value.split(":")
    if len(parts) != 2:
        raise _invalid_operation(
            "vendor_identifier_invalid",
            f"A Confluence {label} identity is invalid.",
        )
    return _identifier(parts[0]), _identifier(parts[1])


def _confluence_site_origin(value: str | None) -> str:
    normalized = _normalized_origin(value)
    if normalized is None or not normalized.removeprefix("https://").endswith(
        ".atlassian.net"
    ):
        raise _invalid_operation(
            "vendor_site_invalid",
            "Confluence Cloud requires an exact HTTPS *.atlassian.net site URL.",
        )
    return normalized


def _normalized_origin(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().rstrip("/").lower()
    if not normalized.startswith("https://") or "/" in normalized[8:]:
        return None
    return normalized


def _invalid_cursor(stream_key: str) -> SorVendorOperationError:
    return _invalid_operation(
        "vendor_cursor_invalid",
        f"The Confluence {stream_key} cursor is invalid.",
    )


def _invalid_command(message: str) -> SorVendorOperationError:
    return _invalid_operation("vendor_command_invalid", message)


def _invalid_response(message: str) -> SorVendorOperationError:
    return _invalid_operation("vendor_response_invalid", message)


def _invalid_operation(code: str, message: str) -> SorVendorOperationError:
    return SorVendorOperationError(code, message, retryable=False)


__all__ = [
    "CONFLUENCE_MANIFEST",
    "ConfluenceKnowledgeAdapter",
    "create_confluence_adapter",
]
