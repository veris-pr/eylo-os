"""Notion adapter for Eylo's canonical Documents profile."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, quote_from_bytes, unquote_to_bytes, urlsplit

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

NOTION_API_ORIGIN = "https://api.notion.com"
NOTION_API_VERSION = "2026-03-11"
NOTION_CURSOR_VERSION = 1
MAX_CANONICAL_TEXT_CHARS = 1_000_000
MAX_CANONICAL_BODY_BYTES = 1_048_576
MAX_TITLE_CHARS = 2_000
MAX_COMMENT_CHARS = 2_000
MAX_TREE_DEPTH = 100
MAX_TREE_FRAMES = 4_096
MAX_PROPERTY_ITEMS = 10_000

_STREAM_ENTITY = {
    "data_sources": "space",
    "pages": "document",
    "blocks": "block",
    "properties": "property",
    "attachments": "attachment",
    "authors": "author",
}
_READ_TOOLS = frozenset(
    {
        "docs_search",
        "docs_get",
        "docs_list_children",
        "docs_describe_fields",
    }
)
_WRITE_TOOLS = frozenset(
    {"docs_create", "docs_update", "docs_append", "docs_comment"}
)
_TOOL_STREAMS = {
    "docs_search": frozenset({"pages"}),
    "docs_get": frozenset({"pages", "blocks", "properties", "attachments"}),
    "docs_list_children": frozenset({"pages"}),
    "docs_describe_fields": frozenset({"pages", "properties"}),
    "docs_create": frozenset({"data_sources", "pages"}),
    "docs_update": frozenset({"pages"}),
    "docs_append": frozenset({"pages", "blocks"}),
    "docs_comment": frozenset({"pages"}),
}
_MUTATION_RESULT_STREAMS = {tool: "pages" for tool in _WRITE_TOOLS}

_SUPPORTED_BLOCK_TYPES = frozenset(
    {
        "audio",
        "bookmark",
        "breadcrumb",
        "bulleted_list_item",
        "callout",
        "child_data_source",
        "child_page",
        "code",
        "column",
        "column_list",
        "divider",
        "embed",
        "equation",
        "file",
        "heading_1",
        "heading_2",
        "heading_3",
        "heading_4",
        "image",
        "link_preview",
        "link_to_page",
        "meeting_notes",
        "numbered_list_item",
        "paragraph",
        "pdf",
        "quote",
        "synced_block",
        "tab",
        "table",
        "table_of_contents",
        "table_row",
        "template",
        "to_do",
        "toggle",
        "video",
    }
)
_FILE_BLOCK_TYPES = frozenset({"audio", "file", "image", "pdf", "video"})


NOTION_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.KNOWLEDGE,
    vendor_key="notion",
    auth_kinds=(ConnectionAuthKind.OAUTH2, ConnectionAuthKind.API_KEY),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                "data_sources": "Data sources",
                "pages": "Pages",
                "blocks": "Page blocks",
                "properties": "Page properties",
                "attachments": "Page files",
                "authors": "Workspace users",
            }[stream_key],
            description={
                "data_sources": "Data sources shared with the Notion connection.",
                "pages": "Pages with enhanced Markdown and source provenance.",
                "blocks": "Recursive structured blocks retained for loss-aware audit.",
                "properties": "Page properties, including completed relation and rollup values.",
                "attachments": "File metadata from page properties and file blocks.",
                "authors": "Users visible to the Notion connection.",
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
    tool_streams=_TOOL_STREAMS,
    mutation_result_streams=_MUTATION_RESULT_STREAMS,
    oauth=SorOAuthSpec(
        authorization_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        send_authorization_scope=False,
        token_request_format="json",
        token_client_auth_method="basic",
    ),
    fixed_origin=NOTION_API_ORIGIN,
    supports_custom_fields=True,
    supports_comments=True,
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
        group="Notion",
    )


_SCHEMA_FIELDS = {
    "data_sources": (
        _field("name", "Name", "text", nullable=False),
        _field("kind", "Kind", "text", nullable=False),
        _field("custom_fields", "Property schema", "bounded_json"),
    ),
    "pages": (
        _field("title", "Title", "text", nullable=False, writable=True),
        _field("space_external_id", "Data source ID", "reference", writable=True),
        _field("parent_external_id", "Parent page ID", "reference", writable=True),
        _field("path", "Path", "string_array"),
        _field("source_format", "Source format", "text", nullable=False),
        _field("normalized_text", "Content", "text", writable=True),
        _field("source_body", "Source body", "bounded_json"),
        _field("content_hash", "Content hash", "text", nullable=False),
        _field("version", "Source revision", "text"),
        _field("lifecycle_state", "State", "text"),
        _field("author_external_id", "Last editor ID", "reference"),
        _field("label_external_ids", "Select option IDs", "string_array"),
        _field("unsupported_blocks", "Unsupported content", "string_array"),
        _field("source_created_at", "Created", "timestamp"),
        _field("source_updated_at", "Updated", "timestamp"),
    ),
    "blocks": (
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
    "properties": (
        _field("document_external_id", "Document ID", "reference", nullable=False),
        _field("key", "Property ID", "text", nullable=False),
        _field("label", "Property name", "text", nullable=False),
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
    "authors": (
        _field("name", "Name", "text", nullable=False),
        _field("primary_email", "Email", "text"),
        _field("kind", "Kind", "text"),
        _field("avatar_url", "Avatar URL", "link"),
    ),
}


@dataclass(frozen=True, slots=True)
class _MemberCursor:
    page_cursor: str | None
    current_page_id: str | None
    current_page_is_last: bool
    offset: int


@dataclass(frozen=True, slots=True)
class _TreeFrame:
    parent_id: str
    parent_external_id: str | None
    child_cursor: str | None
    offset: int
    depth: int


@dataclass(frozen=True, slots=True)
class _TreeCursor:
    page_cursor: str | None
    current_page_id: str | None
    current_page_is_last: bool
    page_attachment_offset: int
    page_attachments_done: bool
    frames: tuple[_TreeFrame, ...]


@dataclass(frozen=True, slots=True)
class _AttachmentValue:
    external_id: str
    document_external_id: str
    name: str
    media_type: str | None
    source_url: str | None
    source_url_expires_at: datetime | None
    source_created_at: datetime | None
    source_updated_at: datetime | None


class NotionKnowledgeAdapter:
    """Translate one Notion connection into canonical document records."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "notion":
            raise ValueError("Notion adapter requires the notion vendor key.")
        if context.auth_kind not in {
            ConnectionAuthKind.OAUTH2,
            ConnectionAuthKind.API_KEY,
        }:
            raise ValueError("Notion SOR requires OAuth 2.0 or an integration token.")
        credential_key = (
            "access_token"
            if context.auth_kind is ConnectionAuthKind.OAUTH2
            else "api_key"
        )
        self._context = context
        self._client = SorJsonHttpClient(
            origin=NOTION_API_ORIGIN,
            authorization=f"Bearer {_credential(context.credentials, credential_key)}",
            transport=transport,
            response_body_limit=8_388_608,
            default_headers={"Notion-Version": NOTION_API_VERSION},
        )

    async def verify_connection(self) -> SorConnectionVerification:
        response = await self._client.request("/v1/users/me")
        user = _object(_expect(response, operation="identify the Notion connection"))
        return SorConnectionVerification(
            account_external_id=_notion_id(user.get("id"), field="connection ID"),
            account_display_name=_optional_string(user.get("name")) or "Notion connection",
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=NOTION_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise _invalid_operation(
                "source_selection_empty",
                "The Notion source selects no streams.",
            )
        streams = {stream.key: stream for stream in NOTION_MANIFEST.streams}
        objects = tuple(
            SorDiscoveredObject(
                key=stream_key,
                label=streams[
                    _require_stream(
                        stream_key,
                        selected=self._context.selected_objects,
                    )
                ].label,
                fields=_SCHEMA_FIELDS[stream_key],
            )
            for stream_key in self._context.selected_objects
        )
        return SorDiscoveredSchema(
            objects=objects,
            vendor_api_version=NOTION_API_VERSION,
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
        if stream_key == "data_sources":
            data_source_id = _notion_id(external_id, field="data source ID")
            response = await self._client.request(
                f"/v1/data_sources/{_path_id(data_source_id)}"
            )
            return self._external_space(
                _required_response(response, stream_key, data_source_id)
            )
        if stream_key == "pages":
            page_id = _notion_id(external_id, field="page ID")
            page, markdown = await self._fetch_page_with_markdown(page_id)
            return self._external_document(page, markdown)
        if stream_key == "blocks":
            block_id = _notion_id(external_id, field="block ID")
            response = await self._client.request(f"/v1/blocks/{_path_id(block_id)}")
            block = _required_response(response, stream_key, block_id)
            page_id = await self._root_page_id(block)
            parent_id = _block_parent_id(block)
            return self._external_block(
                page_id=page_id,
                parent_external_id=parent_id,
                row=block,
                order=0,
            )
        if stream_key == "properties":
            page_id, property_id = _decode_property_external_id(external_id)
            page = await self._fetch_page(page_id)
            label, value = _find_page_property(page, property_id)
            return await self._external_property(
                page_id=page_id,
                label=label,
                value=value,
                page=page,
            )
        if stream_key == "attachments":
            value = await self._fetch_attachment(external_id)
            return _external_attachment(value)
        author_id = _notion_id(external_id, field="user ID")
        response = await self._client.request(f"/v1/users/{_path_id(author_id)}")
        return self._external_author(
            _required_response(response, stream_key, author_id)
        )

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "Notion deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Notion webhooks are not available in this adapter revision."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Notion webhooks are not available in this adapter revision."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "Notion webhooks are not available in this adapter revision."
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        raise SorCapabilityUnavailable(
            "Notion webhooks are not available in this adapter revision."
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        raise SorCapabilityUnavailable(
            "Notion webhooks are not available in this adapter revision."
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise _invalid_operation(
                "vendor_tool_unsupported",
                "This Notion adapter does not execute the requested document action.",
            )
        if command.tool_name == "docs_create":
            return await self._create_page(command)
        target_id = _required_target(command)
        current = await self._fetch_page(target_id)
        if (
            command.expected_source_revision is not None
            and command.expected_source_revision != _page_revision(current)
        ):
            raise _invalid_operation(
                "vendor_source_conflict",
                "The Notion page changed after the Agent read it.",
            )
        if command.tool_name == "docs_update":
            response = await self._update_page(target_id, current, command)
            return _target_command_result(target_id, current, response)
        if command.tool_name == "docs_append":
            response = await self._append_page(target_id, command)
            return _target_command_result(target_id, current, response)
        response = await self._comment_page(target_id, command)
        return _target_command_result(target_id, current, response)

    def normalize_space(self, record: SorExternalRecord) -> KnowledgeSpace:
        values = record.payload
        return KnowledgeSpace(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="data source name"),
            kind=_required_string(values.get("kind"), field="data source kind"),
            source_url=record.source_url,
            custom_fields=_mapping(values.get("custom_fields"), field="data source schema"),
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
                values.get("normalized_text"), field="page content", allow_empty=True
            ),
            source_body=_json_value(values.get("source_body")),
            content_hash=_required_string(
                values.get("content_hash"), field="page content hash"
            ),
            version=_optional_string(values.get("version")),
            lifecycle_state=_optional_string(values.get("lifecycle_state")),
            author_external_id=_optional_string(values.get("author_external_id")),
            label_external_ids=_string_tuple(
                values.get("label_external_ids"), field="page option IDs"
            ),
            unsupported_blocks=_string_tuple(
                values.get("unsupported_blocks"), field="page unsupported content"
            ),
            source_created_at=record.source_created_at,
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
        )

    def normalize_block(self, record: SorExternalRecord) -> KnowledgeBlock:
        values = record.payload
        order = values.get("order")
        if isinstance(order, bool) or not isinstance(order, int) or order < 0:
            raise _invalid_response("Notion block order is invalid.")
        return KnowledgeBlock(
            external_id=record.external_id,
            document_external_id=_required_string(
                values.get("document_external_id"), field="block document ID"
            ),
            parent_external_id=_optional_string(values.get("parent_external_id")),
            kind=_required_string(values.get("kind"), field="block kind"),
            order=order,
            normalized_text=_optional_string(values.get("normalized_text")),
            source_body=_json_value(values.get("source_body")),
            supported=_required_boolean(values.get("supported"), field="block support"),
            source_created_at=record.source_created_at,
            source_updated_at=record.source_updated_at,
        )

    def normalize_version(self, record: SorExternalRecord) -> KnowledgeVersion:
        raise SorCapabilityUnavailable(
            "Notion source versions are not available in this adapter revision."
        )

    def normalize_property(self, record: SorExternalRecord) -> KnowledgeProperty:
        values = record.payload
        return KnowledgeProperty(
            external_id=record.external_id,
            document_external_id=_required_string(
                values.get("document_external_id"), field="property document ID"
            ),
            key=_required_string(values.get("key"), field="property ID"),
            label=_required_string(values.get("label"), field="property name"),
            value_type=_required_string(values.get("value_type"), field="property type"),
            value=_json_scalar(values.get("value")),
            source_updated_at=record.source_updated_at,
        )

    def normalize_attachment(
        self,
        record: SorExternalRecord,
    ) -> KnowledgeAttachment:
        values = record.payload
        return KnowledgeAttachment(
            external_id=record.external_id,
            document_external_id=_required_string(
                values.get("document_external_id"), field="attachment document ID"
            ),
            name=_required_string(values.get("name"), field="attachment name"),
            media_type=_optional_string(values.get("media_type")),
            size_bytes=None,
            source_url=record.source_url,
            source_url_expires_at=_optional_datetime(
                values.get("source_url_expires_at")
            ),
        )

    def normalize_author(self, record: SorExternalRecord) -> KnowledgeAuthor:
        values = record.payload
        return KnowledgeAuthor(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="user name"),
            primary_email=_optional_string(values.get("primary_email")),
            kind=_optional_string(values.get("kind")),
            avatar_url=record.source_url,
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
            raise _invalid_operation(
                "vendor_page_invalid",
                "Notion page limit must be positive.",
            )
        page_limit = min(limit, 100)
        if stream_key == "data_sources":
            data, next_cursor = await self._search(
                object_kind="data_source",
                cursor=cursor,
                limit=page_limit,
            )
            return SorRecordPage(
                records=tuple(self._external_space(row) for row in data),
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
            )
        if stream_key == "pages":
            return await self._read_documents(cursor=cursor, limit=min(page_limit, 25))
        if stream_key == "authors":
            return await self._read_authors(cursor=cursor, limit=page_limit)
        if stream_key == "properties":
            return await self._read_properties(cursor=cursor, limit=page_limit)
        return await self._read_tree(
            stream_key=stream_key,
            cursor=cursor,
            limit=page_limit,
        )

    async def _search(
        self,
        *,
        object_kind: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict[str, object]], str | None]:
        payload: dict[str, object] = {
            "filter": {"property": "object", "value": object_kind},
            "page_size": limit,
            "sort": {"direction": "ascending", "timestamp": "last_edited_time"},
        }
        if cursor is not None:
            payload["start_cursor"] = _vendor_cursor(cursor, stream="search")
        response = await self._client.request("/v1/search", method="POST", payload=payload)
        data = _object(_expect(response, operation=f"search Notion {object_kind}s"))
        rows = _object_list(data.get("results"), field=f"Notion {object_kind}s")
        for row in rows:
            if row.get("object") != object_kind:
                raise _invalid_response("Notion search returned an unexpected object type.")
        return rows, _next_cursor(data, stream="search")

    async def _read_documents(self, *, cursor: str | None, limit: int) -> SorRecordPage:
        pages, next_cursor = await self._search(
            object_kind="page",
            cursor=cursor,
            limit=limit,
        )
        records: list[SorExternalRecord] = []
        for page in pages:
            page_id = _notion_id(page.get("id"), field="page ID")
            markdown = await self._fetch_markdown(page_id)
            records.append(self._external_document(page, markdown))
        return SorRecordPage(
            records=tuple(records),
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )

    async def _read_authors(self, *, cursor: str | None, limit: int) -> SorRecordPage:
        query: dict[str, object] = {"page_size": limit}
        if cursor is not None:
            query["start_cursor"] = _vendor_cursor(cursor, stream="authors")
        response = await self._client.request("/v1/users", query=query)
        data = _object(_expect(response, operation="list Notion users"))
        rows = _object_list(data.get("results"), field="Notion users")
        next_cursor = _next_cursor(data, stream="authors")
        return SorRecordPage(
            records=tuple(self._external_author(row) for row in rows),
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )

    async def _read_properties(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_member_cursor(cursor)
        scans = 0
        while scans < 25:
            if checkpoint.current_page_id is None:
                page_id, page_cursor, page_is_last = await self._next_page(
                    checkpoint.page_cursor
                )
                if page_id is None:
                    return SorRecordPage(records=(), next_cursor=None, has_more=False)
                checkpoint = _MemberCursor(page_cursor, page_id, page_is_last, 0)
            assert checkpoint.current_page_id is not None
            page = await self._fetch_page(checkpoint.current_page_id)
            properties = _page_properties(page)
            if checkpoint.offset > len(properties):
                raise _invalid_cursor("properties")
            selected = properties[checkpoint.offset : checkpoint.offset + limit]
            records = tuple(
                [
                    await self._external_property(
                        page_id=checkpoint.current_page_id,
                        label=label,
                        value=value,
                        page=page,
                    )
                    for label, value in selected
                ]
            )
            next_offset = checkpoint.offset + len(selected)
            if next_offset < len(properties):
                next_checkpoint = _MemberCursor(
                    checkpoint.page_cursor,
                    checkpoint.current_page_id,
                    checkpoint.current_page_is_last,
                    next_offset,
                )
                return SorRecordPage(
                    records=records,
                    next_cursor=_encode_member_cursor(next_checkpoint),
                    has_more=True,
                )
            if checkpoint.current_page_is_last:
                return SorRecordPage(records=records, next_cursor=None, has_more=False)
            boundary = _MemberCursor(checkpoint.page_cursor, None, False, 0)
            if records:
                return SorRecordPage(
                    records=records,
                    next_cursor=_encode_member_cursor(boundary),
                    has_more=True,
                )
            checkpoint = boundary
            scans += 1
        return SorRecordPage(
            records=(),
            next_cursor=_encode_member_cursor(checkpoint),
            has_more=True,
        )

    async def _read_tree(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_tree_cursor(cursor, stream_key=stream_key)
        scans = 0
        while scans < 25:
            if checkpoint.current_page_id is None:
                page_id, page_cursor, page_is_last = await self._next_page(
                    checkpoint.page_cursor
                )
                if page_id is None:
                    return SorRecordPage(records=(), next_cursor=None, has_more=False)
                checkpoint = _TreeCursor(
                    page_cursor=page_cursor,
                    current_page_id=page_id,
                    current_page_is_last=page_is_last,
                    page_attachment_offset=0,
                    page_attachments_done=stream_key != "attachments",
                    frames=(_TreeFrame(page_id, None, None, 0, 0),),
                )
            current_page_id = checkpoint.current_page_id
            assert current_page_id is not None
            if stream_key == "attachments" and not checkpoint.page_attachments_done:
                page = await self._fetch_page(current_page_id)
                attachments = _page_attachments(page)
                if checkpoint.page_attachment_offset > len(attachments):
                    raise _invalid_cursor(stream_key)
                selected = attachments[
                    checkpoint.page_attachment_offset : checkpoint.page_attachment_offset
                    + limit
                ]
                next_offset = checkpoint.page_attachment_offset + len(selected)
                done = next_offset >= len(attachments)
                next_checkpoint = _TreeCursor(
                    page_cursor=checkpoint.page_cursor,
                    current_page_id=checkpoint.current_page_id,
                    current_page_is_last=checkpoint.current_page_is_last,
                    page_attachment_offset=next_offset,
                    page_attachments_done=done,
                    frames=checkpoint.frames,
                )
                if selected:
                    return SorRecordPage(
                        records=tuple(_external_attachment(value) for value in selected),
                        next_cursor=_encode_tree_cursor(
                            next_checkpoint,
                            stream_key=stream_key,
                        ),
                        has_more=True,
                    )
                checkpoint = next_checkpoint
            if not checkpoint.frames:
                if checkpoint.current_page_is_last:
                    return SorRecordPage(records=(), next_cursor=None, has_more=False)
                checkpoint = _TreeCursor(
                    checkpoint.page_cursor,
                    None,
                    False,
                    0,
                    stream_key != "attachments",
                    (),
                )
                scans += 1
                continue
            frame = checkpoint.frames[0]
            rows, child_cursor = await self._read_block_children(frame, limit=limit)
            continuation = (
                (_TreeFrame(
                    frame.parent_id,
                    frame.parent_external_id,
                    child_cursor,
                    frame.offset + len(rows),
                    frame.depth,
                ),)
                if child_cursor is not None
                else ()
            )
            child_frames = tuple(
                _TreeFrame(
                    _notion_id(row.get("id"), field="block ID"),
                    _notion_id(row.get("id"), field="block ID"),
                    None,
                    0,
                    frame.depth + 1,
                )
                for row in rows
                if row.get("has_children") is True
            )
            frames = (*child_frames, *continuation, *checkpoint.frames[1:])
            if len(frames) > MAX_TREE_FRAMES:
                raise _invalid_response("Notion block hierarchy is too broad.")
            records: tuple[SorExternalRecord, ...]
            if stream_key == "blocks":
                records = tuple(
                    self._external_block(
                        page_id=current_page_id,
                        parent_external_id=frame.parent_external_id,
                        row=row,
                        order=frame.offset + index,
                    )
                    for index, row in enumerate(rows)
                )
            else:
                records = tuple(
                    _external_attachment(value)
                    for row in rows
                    for value in _block_attachments(
                        page_id=current_page_id,
                        row=row,
                    )
                )
            next_checkpoint = _TreeCursor(
                checkpoint.page_cursor,
                checkpoint.current_page_id,
                checkpoint.current_page_is_last,
                checkpoint.page_attachment_offset,
                checkpoint.page_attachments_done,
                tuple(frames),
            )
            if not frames:
                if checkpoint.current_page_is_last:
                    return SorRecordPage(records=records, next_cursor=None, has_more=False)
                next_checkpoint = _TreeCursor(
                    checkpoint.page_cursor,
                    None,
                    False,
                    0,
                    stream_key != "attachments",
                    (),
                )
            if records:
                return SorRecordPage(
                    records=records,
                    next_cursor=_encode_tree_cursor(
                        next_checkpoint,
                        stream_key=stream_key,
                    ),
                    has_more=True,
                )
            checkpoint = next_checkpoint
            scans += 1
        return SorRecordPage(
            records=(),
            next_cursor=_encode_tree_cursor(checkpoint, stream_key=stream_key),
            has_more=True,
        )

    async def _next_page(
        self,
        cursor: str | None,
    ) -> tuple[str | None, str | None, bool]:
        rows, next_cursor = await self._search(
            object_kind="page",
            cursor=cursor,
            limit=1,
        )
        if len(rows) > 1 or (not rows and next_cursor is not None):
            raise _invalid_response("Notion returned an invalid page scan.")
        if not rows:
            return None, None, True
        return (
            _notion_id(rows[0].get("id"), field="page ID"),
            next_cursor,
            next_cursor is None,
        )

    async def _read_block_children(
        self,
        frame: _TreeFrame,
        *,
        limit: int,
    ) -> tuple[list[dict[str, object]], str | None]:
        if frame.depth > MAX_TREE_DEPTH:
            raise _invalid_response("Notion block hierarchy is too deep.")
        query: dict[str, object] = {"page_size": limit}
        if frame.child_cursor is not None:
            query["start_cursor"] = frame.child_cursor
        response = await self._client.request(
            f"/v1/blocks/{_path_id(frame.parent_id)}/children",
            query=query,
        )
        data = _object(_expect(response, operation="list Notion block children"))
        rows = _object_list(data.get("results"), field="Notion blocks")
        return rows, _next_cursor(data, stream="blocks")

    async def _fetch_page(self, page_id: str) -> dict[str, object]:
        response = await self._client.request(f"/v1/pages/{_path_id(page_id)}")
        return _required_response(response, "pages", page_id)

    async def _fetch_markdown(self, page_id: str) -> dict[str, object]:
        response = await self._client.request(
            f"/v1/pages/{_path_id(page_id)}/markdown",
            query={"include_transcript": False},
        )
        markdown = _object(_expect(response, operation="retrieve Notion page Markdown"))
        if markdown.get("object") != "page_markdown":
            raise _invalid_response("Notion returned an invalid Markdown document.")
        if _notion_id(markdown.get("id"), field="Markdown page ID") != page_id:
            raise _invalid_response("Notion Markdown belongs to a different page.")
        _bounded_string(markdown.get("markdown"), field="Markdown content", allow_empty=True)
        _required_boolean(markdown.get("truncated"), field="Markdown truncation")
        _id_tuple(markdown.get("unknown_block_ids"), field="unknown block IDs")
        _bounded_json(markdown, field="Markdown source")
        return markdown

    async def _fetch_page_with_markdown(
        self,
        page_id: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        page = await self._fetch_page(page_id)
        return page, await self._fetch_markdown(page_id)

    async def _root_page_id(self, block: Mapping[str, object]) -> str:
        current = block
        visited: set[str] = set()
        for _depth in range(MAX_TREE_DEPTH + 1):
            parent = _object(current.get("parent"), field="Notion block parent")
            parent_type = _required_string(parent.get("type"), field="block parent type")
            if parent_type == "page_id":
                return _notion_id(parent.get("page_id"), field="parent page ID")
            if parent_type != "block_id":
                raise _invalid_response("Notion block has no owning page.")
            parent_id = _notion_id(parent.get("block_id"), field="parent block ID")
            if parent_id in visited:
                raise _invalid_response("Notion block hierarchy contains a cycle.")
            visited.add(parent_id)
            response = await self._client.request(f"/v1/blocks/{_path_id(parent_id)}")
            current = _required_response(response, "blocks", parent_id)
        raise _invalid_response("Notion block hierarchy is too deep.")

    def _external_space(self, row: Mapping[str, object]) -> SorExternalRecord:
        data_source_id = _notion_id(row.get("id"), field="data source ID")
        properties = _mapping(row.get("properties"), field="data source properties")
        return SorExternalRecord(
            vendor_object_key="data_sources",
            external_id=data_source_id,
            payload={
                "name": _rich_text(row.get("title")) or "Untitled data source",
                "kind": "data_source",
                "custom_fields": _bounded_json(properties, field="data source schema"),
            },
            source_created_at=_optional_datetime(row.get("created_time")),
            source_updated_at=_optional_datetime(row.get("last_edited_time")),
            source_revision=_optional_string(row.get("last_edited_time")),
            source_url=_safe_url(row.get("url")),
        )

    def _external_document(
        self,
        row: Mapping[str, object],
        markdown: Mapping[str, object],
    ) -> SorExternalRecord:
        page_id = _notion_id(row.get("id"), field="page ID")
        if _notion_id(markdown.get("id"), field="Markdown page ID") != page_id:
            raise _invalid_response("Notion Markdown belongs to a different page.")
        normalized_text = _bounded_string(
            markdown.get("markdown"),
            field="Markdown content",
            allow_empty=True,
        )
        source_body = _bounded_json(
            {"page": dict(row), "markdown": dict(markdown)},
            field="page source body",
        )
        parent = _optional_mapping(row.get("parent"))
        parent_type = _optional_string(parent.get("type"))
        parent_external_id = None
        space_external_id = None
        if parent_type == "page_id":
            parent_external_id = _optional_notion_id(parent.get("page_id"))
        elif parent_type == "data_source_id":
            space_external_id = _optional_notion_id(parent.get("data_source_id"))
        unsupported: list[str] = []
        if markdown.get("truncated") is True:
            unsupported.append("notion_markdown_truncated")
        if _id_tuple(markdown.get("unknown_block_ids"), field="unknown block IDs"):
            unsupported.append("notion_unknown_block")
        created_at = _optional_datetime(row.get("created_time"))
        updated_at = _optional_datetime(row.get("last_edited_time"))
        revision = _page_revision(row)
        return SorExternalRecord(
            vendor_object_key="pages",
            external_id=page_id,
            payload={
                "title": _page_title(row),
                "space_external_id": space_external_id,
                "parent_external_id": parent_external_id,
                "path": [],
                "source_format": "notion_markdown",
                "normalized_text": normalized_text,
                "source_body": source_body,
                "content_hash": _content_hash(normalized_text, source_body),
                "version": revision,
                "lifecycle_state": "trashed" if row.get("in_trash") is True else "active",
                "author_external_id": _user_reference(row.get("last_edited_by")),
                "label_external_ids": list(_page_option_ids(row)),
                "unsupported_blocks": unsupported,
                "source_created_at": created_at,
                "source_updated_at": updated_at,
            },
            source_created_at=created_at,
            source_updated_at=updated_at,
            source_revision=revision,
            source_url=_safe_url(row.get("url")),
        )

    def _external_block(
        self,
        *,
        page_id: str,
        parent_external_id: str | None,
        row: Mapping[str, object],
        order: int,
    ) -> SorExternalRecord:
        block_id = _notion_id(row.get("id"), field="block ID")
        kind = _required_string(row.get("type"), field="block type")
        created_at = _optional_datetime(row.get("created_time"))
        updated_at = _optional_datetime(row.get("last_edited_time"))
        return SorExternalRecord(
            vendor_object_key="blocks",
            external_id=block_id,
            payload={
                "document_external_id": page_id,
                "parent_external_id": parent_external_id,
                "kind": kind,
                "order": order,
                "normalized_text": _block_text(row),
                "source_body": _bounded_json(dict(row), field="block source body"),
                "supported": kind in _SUPPORTED_BLOCK_TYPES,
                "source_created_at": created_at,
                "source_updated_at": updated_at,
            },
            source_created_at=created_at,
            source_updated_at=updated_at,
            source_revision=_optional_string(row.get("last_edited_time")),
        )

    async def _external_property(
        self,
        *,
        page_id: str,
        label: str,
        value: Mapping[str, object],
        page: Mapping[str, object],
    ) -> SorExternalRecord:
        property_id = _source_key(value.get("id"), field="property ID")
        complete_value = await self._complete_property(page_id, value)
        updated_at = _optional_datetime(page.get("last_edited_time"))
        return SorExternalRecord(
            vendor_object_key="properties",
            external_id=_property_external_id(page_id, property_id),
            payload={
                "document_external_id": page_id,
                "key": property_id,
                "label": _bounded_string(label, field="property name", allow_empty=False),
                "value_type": _required_string(value.get("type"), field="property type"),
                "value": complete_value,
                "source_updated_at": updated_at,
            },
            source_updated_at=updated_at,
            source_revision=_page_revision(page),
        )

    def _external_author(self, row: Mapping[str, object]) -> SorExternalRecord:
        author_id = _notion_id(row.get("id"), field="user ID")
        person = _optional_mapping(row.get("person"))
        return SorExternalRecord(
            vendor_object_key="authors",
            external_id=author_id,
            payload={
                "name": _optional_string(row.get("name")) or "Notion user",
                "primary_email": _optional_string(person.get("email")),
                "kind": _optional_string(row.get("type")),
                "avatar_url": _safe_url(row.get("avatar_url")),
            },
            source_url=_safe_url(row.get("avatar_url")),
        )

    async def _complete_property(
        self,
        page_id: str,
        value: Mapping[str, object],
    ) -> object:
        if not _property_needs_expansion(value):
            return _bounded_json(dict(value), field="page property")
        property_id = _source_key(value.get("id"), field="property ID")
        items: list[object] = []
        cursor: str | None = None
        while True:
            query: dict[str, object] = {"page_size": 100}
            if cursor is not None:
                query["start_cursor"] = cursor
            response = await self._client.request(
                f"/v1/pages/{_path_id(page_id)}/properties/{_property_path_id(property_id)}",
                query=query,
            )
            data = _expect(response, operation="retrieve a complete Notion property")
            if not isinstance(data, Mapping):
                raise _invalid_response("Notion returned an invalid property value.")
            if data.get("object") != "list":
                return _bounded_json(dict(data), field="page property")
            page_items = data.get("results")
            if not isinstance(page_items, list):
                raise _invalid_response("Notion returned invalid property items.")
            items.extend(page_items)
            if len(items) > MAX_PROPERTY_ITEMS:
                raise _invalid_response("Notion property contains too many values.")
            cursor = _next_cursor(data, stream="property")
            if cursor is None:
                break
        return _bounded_json(
            {"summary": dict(value), "property_items": items},
            field="page property",
        )

    async def _fetch_attachment(self, external_id: str) -> _AttachmentValue:
        kind, owner_id, property_id, index = _decode_attachment_id(external_id)
        if kind == "block":
            response = await self._client.request(f"/v1/blocks/{_path_id(owner_id)}")
            block = _required_response(response, "attachments", external_id)
            page_id = await self._root_page_id(block)
            values = _block_attachments(page_id=page_id, row=block)
        else:
            page = await self._fetch_page(owner_id)
            values = tuple(
                value
                for value in _page_attachments(page)
                if _attachment_property_id(value.external_id) == property_id
            )
        try:
            value = values[index]
        except IndexError as error:
            raise SorExternalRecordNotFound(
                vendor_object_key="attachments",
                external_id=external_id,
            ) from error
        if value.external_id != external_id:
            raise SorExternalRecordNotFound(
                vendor_object_key="attachments",
                external_id=external_id,
            )
        return value

    async def _create_page(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command("Creating a Notion page cannot target a record.")
        payload = _document_write_payload(command.payload, create=True)
        parent_page = payload.get("parent_external_id")
        data_source = payload.get("space_external_id")
        if (parent_page is None) == (data_source is None):
            raise _invalid_command(
                "Creating a Notion page requires exactly one parent page or data source."
            )
        title = _required_payload_text(payload, "title")
        request: dict[str, object] = {}
        if isinstance(parent_page, str):
            request["parent"] = {"type": "page_id", "page_id": parent_page}
            title_key = "title"
        else:
            assert isinstance(data_source, str)
            request["parent"] = {
                "type": "data_source_id",
                "data_source_id": data_source,
            }
            response = await self._client.request(
                f"/v1/data_sources/{_path_id(data_source)}"
            )
            schema = _required_response(response, "data_sources", data_source)
            title_key = _data_source_title_key(schema)
        request["properties"] = {title_key: _title_property(title)}
        if "normalized_text" in payload:
            request["markdown"] = payload["normalized_text"]
        try:
            response = await self._client.request(
                "/v1/pages",
                method="POST",
                payload=request,
                idempotency_key=command.idempotency_key,
            )
            page = _object(_expect_mutation(response, operation="create Notion page"))
        except SorVendorOperationError as error:
            _raise_unknown_mutation(error, "created the page")
            raise
        page_id = _notion_id(page.get("id"), field="page ID")
        return _created_command_result(page_id, page, response)

    async def _update_page(
        self,
        page_id: str,
        current: Mapping[str, object],
        command: SorCommandRequest,
    ) -> SorJsonResponse:
        payload = _document_write_payload(command.payload, create=False)
        selected = set(payload) & {"title", "normalized_text"}
        if len(selected) != 1 or set(payload) != selected:
            raise _invalid_command(
                "A Notion update changes either title or content per command."
            )
        if "title" in payload:
            title_key = _page_title_key(current)
            response = await self._client.request(
                f"/v1/pages/{_path_id(page_id)}",
                method="PATCH",
                payload={"properties": {title_key: _title_property(payload["title"])}},
                idempotency_key=command.idempotency_key,
            )
        else:
            response = await self._client.request(
                f"/v1/pages/{_path_id(page_id)}/markdown",
                method="PATCH",
                payload={
                    "type": "replace_content",
                    "replace_content": {
                        "new_str": payload["normalized_text"],
                    },
                },
                idempotency_key=command.idempotency_key,
            )
        _expect_mutation(response, operation="update Notion page")
        return response

    async def _append_page(
        self,
        page_id: str,
        command: SorCommandRequest,
    ) -> SorJsonResponse:
        payload = _document_write_payload(command.payload, create=False)
        if set(payload) != {"normalized_text"} or not payload["normalized_text"]:
            raise _invalid_command("Appending to Notion requires non-empty normalized_text.")
        try:
            response = await self._client.request(
                f"/v1/pages/{_path_id(page_id)}/markdown",
                method="PATCH",
                payload={
                    "type": "insert_content",
                    "insert_content": {
                        "content": payload["normalized_text"],
                        "position": {"type": "end"},
                    },
                },
                idempotency_key=command.idempotency_key,
            )
            _expect_mutation(response, operation="append to Notion page")
        except SorVendorOperationError as error:
            _raise_unknown_mutation(error, "appended the page content")
            raise
        return response

    async def _comment_page(
        self,
        page_id: str,
        command: SorCommandRequest,
    ) -> SorJsonResponse:
        if set(command.payload) != {"normalized_text"}:
            raise _invalid_command("Commenting in Notion requires normalized_text only.")
        text = command.payload.get("normalized_text")
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_COMMENT_CHARS
        ):
            raise _invalid_command("Notion comment text is invalid.")
        try:
            response = await self._client.request(
                "/v1/comments",
                method="POST",
                payload={"parent": {"page_id": page_id}, "markdown": text},
                idempotency_key=command.idempotency_key,
            )
            _expect_mutation(response, operation="comment on Notion page")
        except SorVendorOperationError as error:
            _raise_unknown_mutation(error, "created the comment")
            raise
        return response


def create_notion_adapter(context: SorAdapterContext) -> NotionKnowledgeAdapter:
    """Construct the production Notion adapter for the explicit registry."""
    return NotionKnowledgeAdapter(context)


def _page_properties(page: Mapping[str, object]) -> tuple[tuple[str, dict[str, object]], ...]:
    properties = _mapping(page.get("properties"), field="page properties")
    rows: list[tuple[str, dict[str, object]]] = []
    for label, value in properties.items():
        if not isinstance(value, Mapping):
            raise _invalid_response("Notion returned an invalid page property.")
        row = _object(dict(value), field="Notion page property")
        _source_key(row.get("id"), field="property ID")
        rows.append((label, row))
    return tuple(sorted(rows, key=lambda item: (_source_key(item[1].get("id"), field="property ID"), item[0])))


def _find_page_property(
    page: Mapping[str, object],
    property_id: str,
) -> tuple[str, dict[str, object]]:
    matches = [
        (label, value)
        for label, value in _page_properties(page)
        if _source_key(value.get("id"), field="property ID") == property_id
    ]
    if len(matches) != 1:
        raise SorExternalRecordNotFound(
            vendor_object_key="properties",
            external_id=_property_external_id(
                _notion_id(page.get("id"), field="page ID"),
                property_id,
            ),
        )
    return matches[0]


def _page_title(page: Mapping[str, object]) -> str:
    _key, value = _page_title_property(page)
    return _rich_text(value.get("title")) or "Untitled"


def _page_title_key(page: Mapping[str, object]) -> str:
    return _page_title_property(page)[0]


def _page_title_property(
    page: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    matches = [
        (label, value)
        for label, value in _page_properties(page)
        if value.get("type") == "title"
    ]
    if len(matches) != 1:
        raise _invalid_response("Notion page has no unique title property.")
    return matches[0]


def _data_source_title_key(data_source: Mapping[str, object]) -> str:
    properties = _mapping(data_source.get("properties"), field="data source properties")
    matches = [
        label
        for label, value in properties.items()
        if isinstance(value, Mapping) and value.get("type") == "title"
    ]
    if len(matches) != 1:
        raise _invalid_response("Notion data source has no unique title property.")
    return matches[0]


def _title_property(value: object) -> dict[str, object]:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TITLE_CHARS:
        raise _invalid_command("Notion title is invalid.")
    return {
        "type": "title",
        "title": [
            {
                "type": "text",
                "text": {"content": value.strip()},
            }
        ],
    }


def _page_revision(page: Mapping[str, object]) -> str:
    value = _required_string(page.get("last_edited_time"), field="page revision")
    if _optional_datetime(value) is None:
        raise _invalid_response("Notion page revision is invalid.")
    return value


def _page_option_ids(page: Mapping[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    for _label, prop in _page_properties(page):
        kind = prop.get("type")
        if kind in {"select", "status"}:
            option = prop.get(str(kind))
            if isinstance(option, Mapping):
                option_id = _optional_string(option.get("id"))
                if option_id is not None:
                    values.append(option_id)
        elif kind == "multi_select":
            options = prop.get("multi_select")
            if isinstance(options, list):
                values.extend(
                    option_id
                    for option in options
                    if isinstance(option, Mapping)
                    and (option_id := _optional_string(option.get("id"))) is not None
                )
    return tuple(dict.fromkeys(values))


def _property_needs_expansion(value: Mapping[str, object]) -> bool:
    kind = value.get("type")
    if kind == "relation":
        return value.get("has_more") is True
    if kind == "rollup":
        rollup = value.get("rollup")
        return isinstance(rollup, Mapping) and (
            value.get("has_more") is True or rollup.get("type") == "array"
        )
    return False


def _page_attachments(page: Mapping[str, object]) -> tuple[_AttachmentValue, ...]:
    page_id = _notion_id(page.get("id"), field="page ID")
    created_at = _optional_datetime(page.get("created_time"))
    updated_at = _optional_datetime(page.get("last_edited_time"))
    values: list[_AttachmentValue] = []
    for _label, prop in _page_properties(page):
        if prop.get("type") != "files":
            continue
        property_id = _source_key(prop.get("id"), field="property ID")
        files = prop.get("files")
        if not isinstance(files, list):
            raise _invalid_response("Notion file property is invalid.")
        for index, item in enumerate(files):
            if not isinstance(item, Mapping):
                raise _invalid_response("Notion file property item is invalid.")
            values.append(
                _attachment_value(
                    external_id=_page_attachment_id(page_id, property_id, index),
                    document_external_id=page_id,
                    item=item,
                    fallback_name="Notion file",
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
    return tuple(values)


def _block_attachments(
    *,
    page_id: str,
    row: Mapping[str, object],
) -> tuple[_AttachmentValue, ...]:
    kind = _optional_string(row.get("type"))
    if kind is None or kind not in _FILE_BLOCK_TYPES:
        return ()
    block_id = _notion_id(row.get("id"), field="block ID")
    item = _mapping(row.get(kind), field="file block")
    caption = _rich_text(item.get("caption"))
    return (
        _attachment_value(
            external_id=_block_attachment_id(block_id, 0),
            document_external_id=page_id,
            item=item,
            fallback_name=caption or f"Notion {kind}",
            created_at=_optional_datetime(row.get("created_time")),
            updated_at=_optional_datetime(row.get("last_edited_time")),
        ),
    )


def _attachment_value(
    *,
    external_id: str,
    document_external_id: str,
    item: Mapping[str, object],
    fallback_name: str,
    created_at: datetime | None,
    updated_at: datetime | None,
) -> _AttachmentValue:
    name = _optional_string(item.get("name")) or fallback_name
    file_type = _optional_string(item.get("type"))
    file_data = _optional_mapping(item.get(file_type)) if file_type is not None else {}
    source_url = _safe_url(file_data.get("url"))
    expiry = _optional_datetime(file_data.get("expiry_time"))
    media_type, _encoding = mimetypes.guess_type(name)
    return _AttachmentValue(
        external_id=external_id,
        document_external_id=document_external_id,
        name=name,
        media_type=media_type,
        source_url=source_url,
        source_url_expires_at=expiry,
        source_created_at=created_at,
        source_updated_at=updated_at,
    )


def _external_attachment(value: _AttachmentValue) -> SorExternalRecord:
    return SorExternalRecord(
        vendor_object_key="attachments",
        external_id=value.external_id,
        payload={
            "document_external_id": value.document_external_id,
            "name": value.name,
            "media_type": value.media_type,
            "size_bytes": None,
            "source_url": value.source_url,
            "source_url_expires_at": value.source_url_expires_at,
        },
        source_created_at=value.source_created_at,
        source_updated_at=value.source_updated_at,
        source_url=value.source_url,
    )


def _block_text(row: Mapping[str, object]) -> str | None:
    kind = _optional_string(row.get("type"))
    if kind is None:
        return None
    value = _optional_mapping(row.get(kind))
    parts: list[str] = []
    for key in ("rich_text", "caption"):
        text = _rich_text(value.get(key))
        if text:
            parts.append(text)
    for key in ("title", "expression", "url"):
        text = _optional_string(value.get(key))
        if text:
            parts.append(text)
    cells = value.get("cells")
    if isinstance(cells, list):
        parts.extend(_rich_text(cell) for cell in cells if _rich_text(cell))
    text = "\n".join(parts)
    if len(text) > MAX_CANONICAL_TEXT_CHARS:
        raise _invalid_response("Notion block content is too large.")
    return text or None


def _rich_text(value: object) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise _invalid_response("Notion rich text is invalid.")
        plain = item.get("plain_text")
        if isinstance(plain, str):
            parts.append(plain)
            continue
        item_type = item.get("type")
        nested = item.get(item_type) if isinstance(item_type, str) else None
        if isinstance(nested, Mapping):
            content = nested.get("content") or nested.get("expression")
            if isinstance(content, str):
                parts.append(content)
    text = "".join(parts)
    if len(text) > MAX_CANONICAL_TEXT_CHARS:
        raise _invalid_response("Notion rich text is too large.")
    return text


def _content_hash(normalized_text: str, source_body: object) -> str:
    encoded = json.dumps(
        {"normalized_text": normalized_text, "source_body": source_body},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _document_write_payload(
    payload: Mapping[str, object],
    *,
    create: bool,
) -> dict[str, object]:
    allowed = {"title", "space_external_id", "parent_external_id", "normalized_text"}
    if not payload or set(payload) - allowed:
        raise _invalid_command(
            "Notion document writes accept only title, data source, parent, and content."
        )
    result: dict[str, object] = {}
    title = payload.get("title")
    if title is not None:
        if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE_CHARS:
            raise _invalid_command("Notion title is invalid.")
        result["title"] = title.strip()
    for key in ("space_external_id", "parent_external_id"):
        value = payload.get(key)
        if value is not None:
            result[key] = _notion_id(value, field=key)
    content = payload.get("normalized_text")
    if content is not None:
        if not isinstance(content, str) or len(content) > MAX_CANONICAL_TEXT_CHARS:
            raise _invalid_command("Notion normalized_text is invalid.")
        result["normalized_text"] = content
    if create and "title" not in result:
        raise _invalid_command("Creating a Notion page requires a title.")
    return result


def _required_payload_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise _invalid_command(f"Notion {key} is required.")
    return value


def _created_command_result(
    page_id: str,
    page: Mapping[str, object],
    response: SorJsonResponse,
) -> SorCommandResult:
    request_ids = response.header_values("x-request-id")
    return SorCommandResult(
        vendor_object_key="pages",
        external_id=page_id,
        external_request_id=request_ids[0] if request_ids else None,
        source_revision=_optional_string(page.get("last_edited_time")),
        source_url=_safe_url(page.get("url")),
        response={"status": "accepted"},
    )


def _target_command_result(
    page_id: str,
    current: Mapping[str, object],
    response: SorJsonResponse,
) -> SorCommandResult:
    request_ids = response.header_values("x-request-id")
    return SorCommandResult(
        vendor_object_key="pages",
        external_id=page_id,
        external_request_id=request_ids[0] if request_ids else None,
        source_url=_safe_url(current.get("url")),
        response={"status": "accepted"},
    )


def _raise_unknown_mutation(error: SorVendorOperationError, action: str) -> None:
    if error.code in {"vendor_timeout", "vendor_transport_failed", "vendor_server_failed"}:
        raise SorVendorOperationError(
            "vendor_mutation_outcome_unknown",
            f"Notion may have {action}; reconcile before retrying.",
            retryable=False,
        ) from error


def _required_target(command: SorCommandRequest) -> str:
    if command.target_external_id is None:
        raise _invalid_command("A Notion document action requires a target page.")
    return _notion_id(command.target_external_id, field="target page ID")


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
    return _object(_expect(response, operation="read Notion record"))


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.status_code in {401, 403}:
        raise SorVendorOperationError(
            "vendor_authorization_failed",
            f"Notion refused authorization while attempting to {operation}.",
            retryable=False,
            requires_reauthorization=True,
            refreshable_authorization=response.status_code == 401,
        )
    if response.status_code == 409:
        raise _invalid_operation(
            "vendor_source_conflict",
            "The Notion source changed during the operation.",
        )
    if response.status_code == 429:
        raise SorVendorOperationError(
            "vendor_rate_limited",
            "Notion rate limited the operation.",
            retryable=True,
        )
    if response.status_code >= 500:
        raise SorVendorOperationError(
            "vendor_server_failed",
            "Notion could not complete the operation.",
            retryable=True,
        )
    if not response.ok:
        raise _invalid_operation(
            "vendor_request_rejected",
            f"Notion rejected the request while attempting to {operation}.",
        )
    return response.data


def _expect_mutation(response: SorJsonResponse, *, operation: str) -> object:
    value = _expect(response, operation=operation)
    if response.status_code not in {200, 201}:
        raise _invalid_response("Notion returned an unexpected mutation status.")
    return value


def _next_cursor(data: Mapping[str, object], *, stream: str) -> str | None:
    has_more = data.get("has_more")
    next_cursor = data.get("next_cursor")
    if not isinstance(has_more, bool):
        raise _invalid_response("Notion pagination is invalid.")
    if not has_more:
        if next_cursor is not None:
            raise _invalid_response("Notion pagination is inconsistent.")
        return None
    if not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 4_096:
        raise _invalid_cursor(stream)
    return next_cursor


def _vendor_cursor(value: str, *, stream: str) -> str:
    if not value or len(value) > 4_096:
        raise _invalid_cursor(stream)
    return value


def _decode_member_cursor(value: str | None) -> _MemberCursor:
    if value is None:
        return _MemberCursor(None, None, False, 0)
    payload = _cursor_payload(value, stream_key="properties")
    expected = {"current_page_id", "current_page_is_last", "offset", "page_cursor", "stream", "v"}
    if set(payload) != expected:
        raise _invalid_cursor("properties")
    page_cursor = _optional_cursor(payload.get("page_cursor"), stream="properties")
    page_id = _optional_notion_id(payload.get("current_page_id"))
    is_last = payload.get("current_page_is_last")
    offset = payload.get("offset")
    if (
        not isinstance(is_last, bool)
        or isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or page_id is None and (offset != 0 or is_last)
    ):
        raise _invalid_cursor("properties")
    return _MemberCursor(page_cursor, page_id, is_last, offset)


def _encode_member_cursor(cursor: _MemberCursor) -> str:
    return _encode_cursor(
        {
            "current_page_id": cursor.current_page_id,
            "current_page_is_last": cursor.current_page_is_last,
            "offset": cursor.offset,
            "page_cursor": cursor.page_cursor,
            "stream": "properties",
            "v": NOTION_CURSOR_VERSION,
        },
        stream="properties",
    )


def _decode_tree_cursor(value: str | None, *, stream_key: str) -> _TreeCursor:
    if value is None:
        return _TreeCursor(None, None, False, 0, stream_key != "attachments", ())
    payload = _cursor_payload(value, stream_key=stream_key)
    expected = {
        "current_page_id",
        "current_page_is_last",
        "frames",
        "page_attachment_offset",
        "page_attachments_done",
        "page_cursor",
        "stream",
        "v",
    }
    if set(payload) != expected:
        raise _invalid_cursor(stream_key)
    page_cursor = _optional_cursor(payload.get("page_cursor"), stream=stream_key)
    page_id = _optional_notion_id(payload.get("current_page_id"))
    is_last = payload.get("current_page_is_last")
    attachment_offset = payload.get("page_attachment_offset")
    attachments_done = payload.get("page_attachments_done")
    raw_frames = payload.get("frames")
    if (
        not isinstance(is_last, bool)
        or isinstance(attachment_offset, bool)
        or not isinstance(attachment_offset, int)
        or attachment_offset < 0
        or not isinstance(attachments_done, bool)
        or not isinstance(raw_frames, list)
        or len(raw_frames) > MAX_TREE_FRAMES
    ):
        raise _invalid_cursor(stream_key)
    frames = tuple(_decode_tree_frame(frame, stream_key=stream_key) for frame in raw_frames)
    if page_id is None and (
        is_last or attachment_offset != 0 or frames or attachments_done != (stream_key != "attachments")
    ):
        raise _invalid_cursor(stream_key)
    return _TreeCursor(
        page_cursor,
        page_id,
        is_last,
        attachment_offset,
        attachments_done,
        frames,
    )


def _decode_tree_frame(value: object, *, stream_key: str) -> _TreeFrame:
    if not isinstance(value, Mapping) or set(value) != {
        "child_cursor",
        "depth",
        "offset",
        "parent_external_id",
        "parent_id",
    }:
        raise _invalid_cursor(stream_key)
    parent_id = _notion_id(value.get("parent_id"), field="cursor parent ID")
    parent_external_id = _optional_notion_id(value.get("parent_external_id"))
    child_cursor = _optional_cursor(value.get("child_cursor"), stream=stream_key)
    offset = value.get("offset")
    depth = value.get("depth")
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or isinstance(depth, bool)
        or not isinstance(depth, int)
        or not 0 <= depth <= MAX_TREE_DEPTH
    ):
        raise _invalid_cursor(stream_key)
    return _TreeFrame(parent_id, parent_external_id, child_cursor, offset, depth)


def _encode_tree_cursor(cursor: _TreeCursor, *, stream_key: str) -> str:
    return _encode_cursor(
        {
            "current_page_id": cursor.current_page_id,
            "current_page_is_last": cursor.current_page_is_last,
            "frames": [
                {
                    "child_cursor": frame.child_cursor,
                    "depth": frame.depth,
                    "offset": frame.offset,
                    "parent_external_id": frame.parent_external_id,
                    "parent_id": frame.parent_id,
                }
                for frame in cursor.frames
            ],
            "page_attachment_offset": cursor.page_attachment_offset,
            "page_attachments_done": cursor.page_attachments_done,
            "page_cursor": cursor.page_cursor,
            "stream": stream_key,
            "v": NOTION_CURSOR_VERSION,
        },
        stream=stream_key,
    )


def _cursor_payload(value: str, *, stream_key: str) -> dict[str, object]:
    if not value or len(value) > MAX_CANONICAL_BODY_BYTES:
        raise _invalid_cursor(stream_key)
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid_cursor(stream_key) from error
    if (
        not isinstance(payload, dict)
        or payload.get("v") != NOTION_CURSOR_VERSION
        or payload.get("stream") != stream_key
    ):
        raise _invalid_cursor(stream_key)
    return payload


def _encode_cursor(payload: Mapping[str, object], *, stream: str) -> str:
    value = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if len(value.encode()) > MAX_CANONICAL_BODY_BYTES:
        raise _invalid_response(f"Notion {stream} cursor is too large.")
    return value


def _optional_cursor(value: object, *, stream: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 4_096:
        raise _invalid_cursor(stream)
    return value


def _property_external_id(page_id: str, property_id: str) -> str:
    encoded = base64.urlsafe_b64encode(property_id.encode()).decode().rstrip("=")
    value = f"{page_id}:{encoded}"
    if len(value) > 512:
        raise _invalid_response("Notion property identity is too large.")
    return value


def _decode_property_external_id(value: str) -> tuple[str, str]:
    try:
        page_id, encoded = value.split(":", 1)
        padding = "=" * (-len(encoded) % 4)
        property_id = base64.urlsafe_b64decode(f"{encoded}{padding}").decode()
    except (ValueError, UnicodeDecodeError) as error:
        raise _invalid_operation(
            "vendor_identifier_invalid",
            "A Notion property identity is invalid.",
        ) from error
    return _notion_id(page_id, field="property page ID"), _source_key(
        property_id,
        field="property ID",
    )


def _block_attachment_id(block_id: str, index: int) -> str:
    return f"b:{block_id}:{index}"


def _page_attachment_id(page_id: str, property_id: str, index: int) -> str:
    encoded = base64.urlsafe_b64encode(property_id.encode()).decode().rstrip("=")
    value = f"p:{page_id}:{encoded}:{index}"
    if len(value) > 512:
        raise _invalid_response("Notion attachment identity is too large.")
    return value


def _decode_attachment_id(value: str) -> tuple[str, str, str | None, int]:
    parts = value.split(":")
    try:
        if len(parts) == 3 and parts[0] == "b":
            return "block", _notion_id(parts[1], field="attachment block ID"), None, _index(parts[2])
        if len(parts) == 4 and parts[0] == "p":
            padding = "=" * (-len(parts[2]) % 4)
            property_id = base64.urlsafe_b64decode(f"{parts[2]}{padding}").decode()
            return (
                "property",
                _notion_id(parts[1], field="attachment page ID"),
                _source_key(property_id, field="attachment property ID"),
                _index(parts[3]),
            )
    except (ValueError, UnicodeDecodeError) as error:
        raise _invalid_operation(
            "vendor_identifier_invalid",
            "A Notion attachment identity is invalid.",
        ) from error
    raise _invalid_operation(
        "vendor_identifier_invalid",
        "A Notion attachment identity is invalid.",
    )


def _attachment_property_id(external_id: str) -> str | None:
    kind, _owner, property_id, _index_value = _decode_attachment_id(external_id)
    return property_id if kind == "property" else None


def _index(value: str) -> int:
    if not value.isdigit():
        raise ValueError("invalid attachment index")
    index = int(value)
    if not 0 <= index < MAX_PROPERTY_ITEMS:
        raise ValueError("invalid attachment index")
    return index


def _block_parent_id(block: Mapping[str, object]) -> str | None:
    parent = _optional_mapping(block.get("parent"))
    return (
        _optional_notion_id(parent.get("block_id"))
        if parent.get("type") == "block_id"
        else None
    )


def _user_reference(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    return _optional_notion_id(value.get("id"))


def _notion_id(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise _invalid_response(f"Notion {field} is invalid.")
    normalized = value.strip()
    compact = normalized.replace("-", "")
    if len(compact) != 32 or re.fullmatch(r"[0-9A-Fa-f]{32}", compact) is None:
        raise _invalid_response(f"Notion {field} is invalid.")
    return normalized.lower()


def _optional_notion_id(value: object) -> str | None:
    if value is None:
        return None
    return _notion_id(value, field="source ID")


def _path_id(value: str) -> str:
    return quote(value, safe="")


def _property_path_id(value: str) -> str:
    """Preserve Notion's already URL-encoded property identity in one path segment."""
    return quote_from_bytes(unquote_to_bytes(value), safe="")


def _source_key(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 320:
        raise _invalid_response(f"Notion {field} is invalid.")
    return value


def _safe_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2_048:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return value


def _object(value: object, *, field: str = "Notion response") -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _invalid_response(f"{field} is invalid.")
    return value


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _invalid_response(f"Notion {field} is invalid.")
    return dict(value)


def _optional_mapping(value: object) -> dict[str, object]:
    return _mapping(value, field="object") if isinstance(value, Mapping) else {}


def _object_list(value: object, *, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise _invalid_response(f"{field} is invalid.")
    return [_object(item, field=field) for item in value]


def _bounded_json(value: object, *, field: str) -> object:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        raise _invalid_response(f"Notion {field} is invalid JSON.") from error
    if len(encoded) > MAX_CANONICAL_BODY_BYTES:
        raise _invalid_response(f"Notion {field} is too large.")
    return value


def _json_value(value: object) -> dict | list | str | None:
    if value is None or isinstance(value, (dict, list, str)):
        _bounded_json(value, field="source JSON")
        return value
    raise _invalid_response("Notion returned invalid source JSON.")


def _json_scalar(value: object) -> dict | list | str | int | float | bool | None:
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        _bounded_json(value, field="property value")
        return value
    raise _invalid_response("Notion returned an invalid property value.")


def _required_string(value: object, *, field: str) -> str:
    return _bounded_string(value, field=field, allow_empty=False)


def _bounded_string(value: object, *, field: str, allow_empty: bool) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value)
        or len(value) > MAX_CANONICAL_TEXT_CHARS
    ):
        raise _invalid_response(f"Notion {field} is invalid.")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _required_boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_response(f"Notion {field} is invalid.")
    return value


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _id_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 100:
        raise _invalid_response(f"Notion {field} is invalid.")
    return tuple(_notion_id(item, field=field) for item in value)


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise _invalid_response(f"Notion {field} is invalid.")
    return tuple(value)


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid_operation(
            "vendor_credentials_invalid",
            "Notion credentials are unavailable.",
        )
    return value


def _require_stream(value: str, *, selected: tuple[str, ...]) -> str:
    if value not in _STREAM_ENTITY or value not in selected:
        raise _invalid_operation(
            "vendor_stream_unsupported",
            "The requested Notion stream is not selected for this source.",
        )
    return value


def _invalid_cursor(stream: str) -> SorVendorOperationError:
    return _invalid_operation(
        "vendor_cursor_invalid",
        f"The Notion {stream} cursor is invalid.",
    )


def _invalid_command(message: str) -> SorVendorOperationError:
    return _invalid_operation("vendor_command_invalid", message)


def _invalid_response(message: str) -> SorVendorOperationError:
    return _invalid_operation("vendor_response_invalid", message)


def _invalid_operation(code: str, message: str) -> SorVendorOperationError:
    return SorVendorOperationError(code, message, retryable=False)


__all__ = [
    "NOTION_MANIFEST",
    "NotionKnowledgeAdapter",
    "create_notion_adapter",
]
