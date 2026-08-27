"""Linear Documents adapter for Eylo's canonical Knowledge profile."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, unquote, urlsplit

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.knowledge.contracts import (
    KnowledgeAttachment,
    KnowledgeAttachmentContent,
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
    SorOAuthSpec,
    SorProfile,
    SorRecordPage,
    SorVendorOperationError,
    SorVendorStreamSpec,
    SorWebhookSignal,
    SorWebhookSubscription,
)

LINEAR_ORIGIN = "https://api.linear.app"
LINEAR_GRAPHQL_PATH = "/graphql"
LINEAR_API_VERSION = "graphql-current"
LINEAR_CURSOR_VERSION = 1
LINEAR_RECONCILIATION_OVERLAP = timedelta(minutes=2)
MAX_DOCUMENT_CHARS = 1_000_000

READ_SCOPE = "read"

_STREAM_ENTITY = {
    "documents": "document",
    "authors": "author",
    "attachments": "attachment",
}
_RELATIONSHIP_TARGETS = {
    "documents": {"author": "authors"},
    "attachments": {"document": "documents"},
}
_READ_TOOLS = frozenset({"docs_search", "docs_get"})
_TOOL_STREAMS = {
    "docs_search": frozenset({"documents"}),
    "docs_get": frozenset({"documents", "attachments"}),
}


LINEAR_KNOWLEDGE_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.KNOWLEDGE,
    vendor_key="linear",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                "documents": "Documents",
                "authors": "Authors",
                "attachments": "Document images",
            }[stream_key],
            description={
                "documents": (
                    "Current Linear documents with Markdown content and source "
                    "provenance. Older revisions remain in Linear."
                ),
                "authors": "Workspace users referenced by current documents.",
                "attachments": (
                    "Images referenced by the latest Linear document content."
                ),
            }[stream_key],
            canonical_entity=entity,
            change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
            depends_on=frozenset(
                set(_RELATIONSHIP_TARGETS.get(stream_key, {}).values())
            ),
            relationship_targets=_RELATIONSHIP_TARGETS.get(stream_key, {}),
        )
        for stream_key, entity in _STREAM_ENTITY.items()
    ),
    readable_entities=frozenset(_STREAM_ENTITY.values()),
    writable_entities=frozenset(),
    readable_tools=_READ_TOOLS,
    writable_tools=frozenset(),
    change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
    required_scopes={stream_key: (READ_SCOPE,) for stream_key in _STREAM_ENTITY},
    tool_streams=_TOOL_STREAMS,
    oauth=SorOAuthSpec(
        authorization_url="https://linear.app/oauth/authorize",
        token_url="https://api.linear.app/oauth/token",
        base_scopes=(READ_SCOPE,),
        scope_delimiter=",",
        scope_response_delimiter=" ",
        authorization_params=(("actor", "app"), ("prompt", "consent")),
        pkce=True,
    ),
    fixed_origin=LINEAR_ORIGIN,
    change_mode=SorChangeMode.APP_WEBHOOK,
    supports_structured_documents=True,
    supports_attachments=True,
)


def _field(
    key: str,
    label: str,
    data_type: str,
    *,
    nullable: bool = True,
) -> SorDiscoveredField:
    return SorDiscoveredField(
        key=key,
        label=label,
        data_type=data_type,
        nullable=nullable,
        writable=False,
        group="Linear",
    )


_SCHEMA_FIELDS = {
    "documents": (
        _field("title", "Title", "text", nullable=False),
        _field("path", "Location", "string_array", nullable=False),
        _field("normalized_text", "Content", "text", nullable=False),
        _field("source_format", "Source format", "text", nullable=False),
        _field("source_body", "Source body", "bounded_json"),
        _field("content_hash", "Content hash", "text", nullable=False),
        _field("version", "Content revision", "text"),
        _field("lifecycle_state", "State", "text"),
        _field("author_external_id", "Creator ID", "reference"),
        _field("source_created_at", "Created", "timestamp"),
        _field("source_updated_at", "Updated", "timestamp"),
        _field("custom_fields", "Linear context", "bounded_json"),
    ),
    "authors": (
        _field("name", "Name", "text", nullable=False),
        _field("primary_email", "Email", "text"),
        _field("kind", "Kind", "text"),
        _field("avatar_url", "Avatar URL", "link"),
    ),
    "attachments": (
        _field("document_external_id", "Document ID", "reference", nullable=False),
        _field("name", "Name", "text", nullable=False),
        _field("media_type", "Media type", "text"),
        _field("size_bytes", "Size", "integer"),
        _field("source_url", "Source URL", "link", nullable=False),
    ),
}

_DOCUMENT_FIELDS = """
  id title content documentContentId slugId url icon color
  createdAt updatedAt archivedAt hiddenAt trashed
  creator { id }
  owner { id }
  updatedBy { id }
  initiative { id name }
  issue { id identifier title }
  project { id name slugId }
  release { id name }
"""
_PAGE_QUERIES = {
    "documents": f"""
      query EyloLinearDocuments(
        $first: Int!, $after: String, $filter: DocumentFilter
      ) {{
        documents(first: $first, after: $after, filter: $filter, orderBy: updatedAt) {{
          nodes {{{_DOCUMENT_FIELDS}}}
          pageInfo {{ hasNextPage endCursor }}
        }}
      }}
    """,
    "authors": """
      query EyloLinearDocumentAuthors(
        $first: Int!, $after: String, $filter: UserFilter
      ) {
        users(
          first: $first, after: $after, filter: $filter,
          includeDisabled: true, orderBy: updatedAt
        ) {
          nodes {
            id name displayName email active avatarUrl url
            createdAt updatedAt archivedAt
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    """,
}


@dataclass(frozen=True, slots=True)
class _LinearCursor:
    floor: datetime | None
    after: str | None
    high: datetime | None
    started_at: datetime


@dataclass(frozen=True, slots=True)
class _LinearAttachmentCursor:
    floor: datetime | None
    page_after: str | None
    document_index: int
    attachment_index: int
    high: datetime | None
    started_at: datetime


@dataclass(frozen=True, slots=True)
class _LinearAttachment:
    external_id: str
    name: str
    media_type: str | None
    source_url: str


class LinearKnowledgeAdapter:
    """Translate Linear documents into Eylo's read-only Knowledge contract."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "linear":
            raise ValueError("Linear adapter requires the linear vendor key.")
        if context.auth_kind is not ConnectionAuthKind.OAUTH2:
            raise ValueError("Linear Documents currently requires OAuth 2.0.")
        token = _credential(context.credentials, "access_token")
        self._context = context
        self._client = SorJsonHttpClient(
            origin=LINEAR_ORIGIN,
            authorization=f"Bearer {token}",
            transport=transport,
            response_body_limit=8_388_608,
        )
        self._uploads_client = SorJsonHttpClient(
            origin="https://uploads.linear.app",
            authorization=f"Bearer {token}",
            transport=transport,
            response_body_limit=8_388_608,
        )

    async def verify_connection(self) -> SorConnectionVerification:
        data, _response = await self._graphql(
            """
              query EyloVerifyLinearDocuments {
                organization { id name }
                viewer { id name email }
              }
            """,
            operation="verify Linear workspace",
        )
        organization = _object(data.get("organization"), field="Linear organization")
        return SorConnectionVerification(
            account_external_id=_required_id(
                organization.get("id"), field="Linear organization ID"
            ),
            account_display_name=(
                _optional_string(organization.get("name")) or "Linear workspace"
            ),
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=LINEAR_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        objects = tuple(
            SorDiscoveredObject(
                key=stream_key,
                label=next(
                    stream.label
                    for stream in LINEAR_KNOWLEDGE_MANIFEST.streams
                    if stream.key == stream_key
                ),
                fields=_SCHEMA_FIELDS[stream_key],
            )
            for stream_key in self._context.selected_objects
        )
        if not objects:
            raise SorVendorOperationError(
                "source_selection_empty",
                "The Linear Documents source selects no streams.",
                retryable=False,
            )
        return SorDiscoveredSchema(
            objects=objects,
            vendor_api_version=LINEAR_API_VERSION,
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
        record_id = _required_id(external_id, field="Linear record ID")
        if stream_key == "attachments":
            document_id, _separator, _digest = record_id.partition(":")
            if not document_id or not _digest:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=record_id,
                )
            document = await self._fetch_document(document_id)
            for attachment in _document_attachments(document):
                if attachment.external_id == record_id:
                    return self._external_attachment(document, attachment)
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        singular = "document" if stream_key == "documents" else "user"
        selection = (
            _DOCUMENT_FIELDS
            if stream_key == "documents"
            else (
                "id name displayName email active avatarUrl url "
                "createdAt updatedAt archivedAt"
            )
        )
        data, _response = await self._graphql(
            f"""
              query EyloLinearKnowledgeRecord($id: String!) {{
                {singular}(id: $id) {{ {selection} }}
              }}
            """,
            {"id": record_id},
            operation="read Linear knowledge record",
        )
        row = data.get(singular)
        if row is None:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        record = _object(row, field="Linear knowledge record")
        archived_at = _optional_datetime(record.get("archivedAt"))
        if archived_at is not None:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
                deleted_at=archived_at,
                reason="Archived in Linear",
            )
        return self._external_record(stream_key, record)

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "Linear deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Linear webhooks use the operator-configured OAuth app callback."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Linear webhooks use the operator-configured OAuth app callback."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "Linear webhooks use the operator-configured OAuth app callback."
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        raise SorCapabilityUnavailable(
            "Linear app webhook verification is owned by the connector endpoint."
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        raise SorCapabilityUnavailable(
            "Linear app webhook parsing is owned by the connector endpoint."
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        raise SorCapabilityUnavailable(
            "Linear Documents is read-only in this adapter revision."
        )

    def normalize_space(self, record: SorExternalRecord) -> KnowledgeSpace:
        raise _normalization_unavailable("space")

    def normalize_document(self, record: SorExternalRecord) -> KnowledgeDocument:
        values = record.payload
        return KnowledgeDocument(
            external_id=record.external_id,
            title=_required_string(values.get("title"), field="document title"),
            space_external_id=None,
            parent_external_id=None,
            path=_string_tuple(values.get("path"), field="document path"),
            source_format=_required_string(
                values.get("source_format"), field="document source format"
            ),
            normalized_text=_bounded_string(
                values.get("normalized_text"), field="document content"
            ),
            source_body=_json_value(values.get("source_body")),
            content_hash=_required_string(
                values.get("content_hash"), field="document content hash"
            ),
            version=_optional_string(values.get("version")),
            lifecycle_state=_optional_string(values.get("lifecycle_state")),
            author_external_id=_optional_string(values.get("author_external_id")),
            label_external_ids=(),
            unsupported_blocks=(),
            source_created_at=record.source_created_at,
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
            custom_fields=_mapping(values.get("custom_fields"), field="Linear context"),
        )

    def normalize_block(self, record: SorExternalRecord) -> KnowledgeBlock:
        raise _normalization_unavailable("block")

    def normalize_version(self, record: SorExternalRecord) -> KnowledgeVersion:
        raise _normalization_unavailable("version")

    def normalize_property(self, record: SorExternalRecord) -> KnowledgeProperty:
        raise _normalization_unavailable("property")

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
            source_url=_safe_upload_url(values.get("source_url")),
            source_url_expires_at=None,
        )

    def normalize_author(self, record: SorExternalRecord) -> KnowledgeAuthor:
        values = record.payload
        return KnowledgeAuthor(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="author name"),
            primary_email=_optional_string(values.get("primary_email")),
            kind=_optional_string(values.get("kind")),
            avatar_url=_optional_string(values.get("avatar_url")),
        )

    async def close(self) -> None:
        """Linear's bounded HTTP transport owns no persistent session."""

    async def read_attachment_content(
        self,
        *,
        document_external_id: str,
        attachment_external_id: str,
        maximum_bytes: int,
    ) -> KnowledgeAttachmentContent:
        """Read a current Linear upload only after its document ownership is proven."""
        document_id = _required_id(
            document_external_id,
            field="attachment document ID",
        )
        attachment_id = _required_id(
            attachment_external_id,
            field="attachment ID",
        )
        document = await self._fetch_document(document_id)
        attachment = next(
            (
                item
                for item in _document_attachments(document)
                if item.external_id == attachment_id
            ),
            None,
        )
        if attachment is None:
            raise SorExternalRecordNotFound(
                vendor_object_key="attachments",
                external_id=attachment_id,
            )
        parsed = urlsplit(attachment.source_url)
        response = await self._uploads_client.request_binary(
            parsed.path,
            query=dict(parse_qsl(parsed.query, keep_blank_values=True)),
            response_body_limit=maximum_bytes,
        )
        if response.status_code in {404, 410}:
            raise SorExternalRecordNotFound(
                vendor_object_key="attachments",
                external_id=attachment_id,
            )
        if not 200 <= response.status_code < 300:
            raise SorVendorOperationError(
                "vendor_request_rejected",
                "Linear did not return the requested document image.",
                retryable=response.status_code >= 500,
            )
        media_types = response.header_values("content-type")
        return KnowledgeAttachmentContent(
            content=response.content,
            media_type=(
                media_types[0].split(";", 1)[0].strip().casefold()
                if media_types
                else attachment.media_type
            ),
        )

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
        if not 1 <= limit <= 200:
            raise SorVendorOperationError(
                "vendor_page_invalid",
                "Linear page limit must be between 1 and 200.",
                retryable=False,
            )
        if stream_key == "attachments":
            return await self._read_attachment_page(cursor=cursor, limit=limit)
        selected_fields = self._selected_fields(stream_key)
        checkpoint = _decode_cursor(cursor)
        variables: dict[str, object] = {
            "first": limit,
            "after": checkpoint.after,
            "filter": (
                {"updatedAt": {"gte": _linear_datetime(checkpoint.floor)}}
                if checkpoint.floor is not None
                else None
            ),
        }
        data, _response = await self._graphql(
            _PAGE_QUERIES[stream_key],
            variables,
            operation=f"list Linear {stream_key}",
        )
        connection_name = "documents" if stream_key == "documents" else "users"
        connection = _object(
            data.get(connection_name), field=f"Linear {stream_key} page"
        )
        rows = _object_list(connection.get("nodes"), field="Linear page nodes")
        if len(rows) > limit:
            raise _invalid_response("Linear returned more records than requested.")
        page_info = _object(connection.get("pageInfo"), field="Linear page info")
        has_more = page_info.get("hasNextPage")
        if not isinstance(has_more, bool):
            raise _invalid_response("Linear returned no page completion flag.")
        end_cursor = _optional_string(page_info.get("endCursor"))
        if has_more and end_cursor is None:
            raise _invalid_response("Linear returned no cursor for a partial page.")
        high = _maximum_updated_at(rows, current=checkpoint.high)
        next_cursor = _encode_cursor(
            _LinearCursor(
                floor=checkpoint.floor,
                after=end_cursor if has_more else None,
                high=high,
                started_at=checkpoint.started_at,
            )
            if has_more
            else _completed_cursor(
                floor=checkpoint.floor,
                high=high,
                started_at=checkpoint.started_at,
            )
        )
        return SorRecordPage(
            records=tuple(
                self._external_record(
                    stream_key,
                    row,
                    selected_fields=selected_fields,
                )
                for row in rows
                if _optional_datetime(row.get("archivedAt")) is None
            ),
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def _read_attachment_page(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        selected_fields = self._selected_fields("attachments")
        checkpoint = _decode_attachment_cursor(cursor)
        data, _response = await self._graphql(
            _PAGE_QUERIES["documents"],
            {
                "first": min(limit, 25),
                "after": checkpoint.page_after,
                "filter": (
                    {"updatedAt": {"gte": _linear_datetime(checkpoint.floor)}}
                    if checkpoint.floor is not None
                    else None
                ),
            },
            operation="list Linear document images",
        )
        connection = _object(data.get("documents"), field="Linear document page")
        documents = _object_list(connection.get("nodes"), field="Linear documents")
        page_info = _object(connection.get("pageInfo"), field="Linear page info")
        page_has_more = page_info.get("hasNextPage")
        if not isinstance(page_has_more, bool):
            raise _invalid_response("Linear returned no page completion flag.")
        end_cursor = _optional_string(page_info.get("endCursor"))
        if page_has_more and end_cursor is None:
            raise _invalid_response("Linear returned no cursor for a partial page.")

        high = _maximum_updated_at(documents, current=checkpoint.high)
        records: list[SorExternalRecord] = []
        document_index = checkpoint.document_index
        attachment_index = checkpoint.attachment_index
        while document_index < len(documents):
            document = documents[document_index]
            attachments = _document_attachments(document)
            while attachment_index < len(attachments):
                records.append(
                    self._external_attachment(
                        document,
                        attachments[attachment_index],
                        selected_fields=selected_fields,
                    )
                )
                attachment_index += 1
                if len(records) == limit:
                    if attachment_index >= len(attachments):
                        document_index += 1
                        attachment_index = 0
                    if document_index >= len(documents) and not page_has_more:
                        return SorRecordPage(
                            records=tuple(records),
                            next_cursor=_encode_attachment_cursor(
                                _completed_attachment_cursor(
                                    floor=checkpoint.floor,
                                    high=high,
                                    started_at=checkpoint.started_at,
                                )
                            ),
                            has_more=False,
                        )
                    next_page_after = checkpoint.page_after
                    if document_index >= len(documents):
                        next_page_after = end_cursor
                        document_index = 0
                    return SorRecordPage(
                        records=tuple(records),
                        next_cursor=_encode_attachment_cursor(
                            _LinearAttachmentCursor(
                                floor=checkpoint.floor,
                                page_after=next_page_after,
                                document_index=document_index,
                                attachment_index=attachment_index,
                                high=high,
                                started_at=checkpoint.started_at,
                            )
                        ),
                        has_more=True,
                    )
            document_index += 1
            attachment_index = 0

        if page_has_more:
            next_cursor = _encode_attachment_cursor(
                _LinearAttachmentCursor(
                    floor=checkpoint.floor,
                    page_after=end_cursor,
                    document_index=0,
                    attachment_index=0,
                    high=high,
                    started_at=checkpoint.started_at,
                )
            )
            has_more = True
        else:
            next_cursor = _encode_attachment_cursor(
                _completed_attachment_cursor(
                    floor=checkpoint.floor,
                    high=high,
                    started_at=checkpoint.started_at,
                )
            )
            has_more = False
        return SorRecordPage(
            records=tuple(records),
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def _selected_fields(self, stream_key: str) -> tuple[str, ...]:
        fields = tuple(
            sorted(
                {
                    field.vendor_field_key
                    for field in self._context.fields
                    if field.vendor_object_key == stream_key
                }
            )
        )
        allowed = {field.key for field in _SCHEMA_FIELDS[stream_key]}
        unknown = set(fields) - allowed
        if unknown:
            raise SorVendorOperationError(
                "source_mapping_invalid",
                f"The Linear mapping selects unknown {stream_key} fields.",
                retryable=False,
            )
        if not fields:
            raise SorVendorOperationError(
                "source_mapping_empty",
                f"The active mapping selects no {stream_key} fields.",
                retryable=False,
            )
        return fields

    def _external_record(
        self,
        stream_key: str,
        row: Mapping[str, object],
        *,
        selected_fields: tuple[str, ...] | None = None,
    ) -> SorExternalRecord:
        selected = selected_fields or self._selected_fields(stream_key)
        values = _linear_payload(stream_key, row)
        payload = {field: values.get(field) for field in selected}
        record_id = _required_id(row.get("id"), field="Linear record ID")
        updated_at = _required_datetime(
            row.get("updatedAt"), field="Linear record update time"
        )
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=record_id,
            payload=payload,
            source_created_at=_optional_datetime(row.get("createdAt")),
            source_updated_at=updated_at,
            source_revision=updated_at.isoformat(),
            source_url=_safe_linear_url(row.get("url")),
        )

    def _external_attachment(
        self,
        document: Mapping[str, object],
        attachment: _LinearAttachment,
        *,
        selected_fields: tuple[str, ...] | None = None,
    ) -> SorExternalRecord:
        selected = selected_fields or self._selected_fields("attachments")
        values: dict[str, object | None] = {
            "document_external_id": _required_id(
                document.get("id"), field="attachment document ID"
            ),
            "name": attachment.name,
            "media_type": attachment.media_type,
            "size_bytes": None,
            "source_url": attachment.source_url,
        }
        payload = {field: values.get(field) for field in selected}
        updated_at = _required_datetime(
            document.get("updatedAt"), field="attachment document update time"
        )
        return SorExternalRecord(
            vendor_object_key="attachments",
            external_id=attachment.external_id,
            payload=payload,
            source_created_at=_optional_datetime(document.get("createdAt")),
            source_updated_at=updated_at,
            source_revision=f"{updated_at.isoformat()}:{attachment.external_id}",
            source_url=attachment.source_url,
        )

    async def _fetch_document(self, document_id: str) -> dict[str, object]:
        data, _response = await self._graphql(
            f"""
              query EyloLinearDocument($id: String!) {{
                document(id: $id) {{ {_DOCUMENT_FIELDS} }}
              }}
            """,
            {"id": document_id},
            operation="read Linear document",
        )
        row = data.get("document")
        if row is None:
            raise SorExternalRecordNotFound(
                vendor_object_key="documents",
                external_id=document_id,
            )
        return _object(row, field="Linear document")

    async def _graphql(
        self,
        document: str,
        variables: Mapping[str, object] | None = None,
        *,
        operation: str,
    ) -> tuple[dict[str, object], SorJsonResponse]:
        response = await self._client.request(
            LINEAR_GRAPHQL_PATH,
            method="POST",
            payload={"query": document, "variables": dict(variables or {})},
        )
        return _graphql_data(response, operation=operation), response


def create_linear_knowledge_adapter(
    context: SorAdapterContext,
) -> LinearKnowledgeAdapter:
    """Construct the explicit Linear Knowledge adapter."""
    return LinearKnowledgeAdapter(context)


def _linear_payload(
    stream_key: str,
    row: Mapping[str, object],
) -> dict[str, object | None]:
    if stream_key == "authors":
        return {
            "name": row.get("displayName") or row.get("name"),
            "primary_email": row.get("email"),
            "kind": "user" if row.get("active") is True else "inactive_user",
            "avatar_url": row.get("avatarUrl"),
        }
    content = _bounded_string(row.get("content"), field="document content")
    title = _optional_string(row.get("title")) or "Untitled document"
    creator = _optional_object(row.get("creator"))
    owner = _optional_object(row.get("owner"))
    updated_by = _optional_object(row.get("updatedBy"))
    parent_type, parent_id, parent_label = _document_parent(row)
    return {
        "title": title,
        "normalized_text": content,
        "source_format": "linear_markdown",
        "source_body": {"representation": "markdown", "value": content},
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "version": row.get("documentContentId"),
        "lifecycle_state": _document_lifecycle(row),
        "author_external_id": creator.get("id"),
        "source_created_at": row.get("createdAt"),
        "source_updated_at": row.get("updatedAt"),
        "custom_fields": {
            "document_content_id": row.get("documentContentId"),
            "slug_id": row.get("slugId"),
            "icon": row.get("icon"),
            "color": row.get("color"),
            "parent_type": parent_type,
            "parent_external_id": parent_id,
            "parent_label": parent_label,
            "owner_external_id": owner.get("id"),
            "updated_by_external_id": updated_by.get("id"),
        },
        "path": [parent_label, title] if parent_label else [title],
    }


def _document_parent(
    row: Mapping[str, object],
) -> tuple[str | None, object | None, str | None]:
    for parent_type in ("initiative", "issue", "project", "release"):
        parent = _optional_object(row.get(parent_type))
        parent_id = parent.get("id")
        if parent_id is None:
            continue
        label = (
            _optional_string(parent.get("identifier"))
            or _optional_string(parent.get("name"))
            or _optional_string(parent.get("title"))
        )
        return parent_type, parent_id, label
    return None, None, None


def _document_lifecycle(row: Mapping[str, object]) -> str:
    if row.get("trashed") is True:
        return "TRASHED"
    if _optional_datetime(row.get("archivedAt")) is not None:
        return "ARCHIVED"
    if _optional_datetime(row.get("hiddenAt")) is not None:
        return "HIDDEN"
    return "ACTIVE"


def _normalization_unavailable(entity: str) -> SorCapabilityUnavailable:
    return SorCapabilityUnavailable(
        f"Linear Documents does not project {entity} records in this adapter revision."
    )


def _graphql_data(
    response: SorJsonResponse,
    *,
    operation: str,
) -> dict[str, object]:
    if response.status_code in {401, 403}:
        raise SorVendorOperationError(
            "vendor_authorization_failed",
            f"Linear refused authorization while attempting to {operation}.",
            retryable=False,
            requires_reauthorization=True,
            refreshable_authorization=response.status_code == 401,
        )
    if response.status_code == 429:
        raise SorVendorOperationError(
            "vendor_rate_limited",
            "Linear rate limited the operation.",
            retryable=True,
        )
    if response.status_code >= 500:
        raise SorVendorOperationError(
            "vendor_server_failed",
            "Linear could not complete the operation.",
            retryable=True,
        )
    if not response.ok:
        raise SorVendorOperationError(
            "vendor_request_rejected",
            f"Linear rejected the request while attempting to {operation}.",
            retryable=False,
        )
    payload = _object(response.data, field="Linear GraphQL response")
    errors = payload.get("errors")
    if errors:
        rows = _object_list(errors, field="Linear GraphQL errors")
        first = rows[0] if rows else {}
        extensions = _optional_object(first.get("extensions"))
        native_code = str(extensions.get("code") or "").upper()
        if native_code in {"AUTHENTICATION_ERROR", "UNAUTHENTICATED", "FORBIDDEN"}:
            raise SorVendorOperationError(
                "vendor_authorization_failed",
                "Linear authorization is no longer valid.",
                retryable=False,
                requires_reauthorization=True,
                refreshable_authorization=True,
            )
        if native_code in {"RATELIMITED", "RATE_LIMITED", "INTERNAL_SERVER_ERROR"}:
            raise SorVendorOperationError(
                (
                    "vendor_rate_limited"
                    if "RATE" in native_code
                    else "vendor_server_failed"
                ),
                "Linear could not complete the operation yet.",
                retryable=True,
            )
        message = _optional_string(first.get("message"))
        raise SorVendorOperationError(
            "vendor_request_rejected",
            (message or "Linear rejected the operation.")[:500],
            retryable=False,
        )
    return _object(payload.get("data"), field="Linear GraphQL data")


def _decode_cursor(value: str | None) -> _LinearCursor:
    now = datetime.now(timezone.utc)
    if value is None:
        return _LinearCursor(floor=None, after=None, high=None, started_at=now)
    try:
        payload = json.loads(value)
    except (TypeError, ValueError) as error:
        raise SorVendorOperationError(
            "vendor_cursor_invalid",
            "Linear cursor is invalid.",
            retryable=False,
        ) from error
    if not isinstance(payload, dict) or payload.get("version") != LINEAR_CURSOR_VERSION:
        raise SorVendorOperationError(
            "vendor_cursor_invalid",
            "Linear cursor version is invalid.",
            retryable=False,
        )
    return _LinearCursor(
        floor=_optional_datetime(payload.get("floor")),
        after=_optional_string(payload.get("after")),
        high=_optional_datetime(payload.get("high")),
        started_at=_required_datetime(
            payload.get("started_at"), field="Linear cursor start"
        ),
    )


def _encode_cursor(cursor: _LinearCursor) -> str:
    return json.dumps(
        {
            "version": LINEAR_CURSOR_VERSION,
            "floor": _linear_datetime(cursor.floor),
            "after": cursor.after,
            "high": _linear_datetime(cursor.high),
            "started_at": _linear_datetime(cursor.started_at),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_attachment_cursor(value: str | None) -> _LinearAttachmentCursor:
    now = datetime.now(timezone.utc)
    if value is None:
        return _LinearAttachmentCursor(
            floor=None,
            page_after=None,
            document_index=0,
            attachment_index=0,
            high=None,
            started_at=now,
        )
    try:
        payload = json.loads(value)
    except (TypeError, ValueError) as error:
        raise SorVendorOperationError(
            "vendor_cursor_invalid",
            "Linear attachment cursor is invalid.",
            retryable=False,
        ) from error
    if not isinstance(payload, dict) or payload.get("version") != LINEAR_CURSOR_VERSION:
        raise SorVendorOperationError(
            "vendor_cursor_invalid",
            "Linear attachment cursor version is invalid.",
            retryable=False,
        )
    document_index = payload.get("document_index")
    attachment_index = payload.get("attachment_index")
    if (
        isinstance(document_index, bool)
        or not isinstance(document_index, int)
        or document_index < 0
        or isinstance(attachment_index, bool)
        or not isinstance(attachment_index, int)
        or attachment_index < 0
    ):
        raise SorVendorOperationError(
            "vendor_cursor_invalid",
            "Linear attachment cursor position is invalid.",
            retryable=False,
        )
    return _LinearAttachmentCursor(
        floor=_optional_datetime(payload.get("floor")),
        page_after=_optional_string(payload.get("page_after")),
        document_index=document_index,
        attachment_index=attachment_index,
        high=_optional_datetime(payload.get("high")),
        started_at=_required_datetime(
            payload.get("started_at"), field="Linear attachment cursor start"
        ),
    )


def _encode_attachment_cursor(cursor: _LinearAttachmentCursor) -> str:
    return json.dumps(
        {
            "version": LINEAR_CURSOR_VERSION,
            "floor": _linear_datetime(cursor.floor),
            "page_after": cursor.page_after,
            "document_index": cursor.document_index,
            "attachment_index": cursor.attachment_index,
            "high": _linear_datetime(cursor.high),
            "started_at": _linear_datetime(cursor.started_at),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _completed_cursor(
    *,
    floor: datetime | None,
    high: datetime | None,
    started_at: datetime,
) -> _LinearCursor:
    observed = high or started_at
    next_floor = observed - LINEAR_RECONCILIATION_OVERLAP
    if floor is not None and next_floor < floor:
        next_floor = floor
    return _LinearCursor(
        floor=next_floor,
        after=None,
        high=None,
        started_at=datetime.now(timezone.utc),
    )


def _completed_attachment_cursor(
    *,
    floor: datetime | None,
    high: datetime | None,
    started_at: datetime,
) -> _LinearAttachmentCursor:
    completed = _completed_cursor(floor=floor, high=high, started_at=started_at)
    return _LinearAttachmentCursor(
        floor=completed.floor,
        page_after=None,
        document_index=0,
        attachment_index=0,
        high=None,
        started_at=completed.started_at,
    )


def _maximum_updated_at(
    rows: tuple[dict[str, object], ...],
    *,
    current: datetime | None,
) -> datetime | None:
    result = current
    for row in rows:
        value = _optional_datetime(row.get("updatedAt"))
        if value is not None and (result is None or value > result):
            result = value
    return result


def _linear_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _credential(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Linear credential {key} is missing.")
    return value.strip()


def _require_stream(value: str, *, selected: tuple[str, ...]) -> str:
    if value not in _STREAM_ENTITY or value not in selected:
        raise SorVendorOperationError(
            "vendor_stream_unsupported",
            "The requested Linear Documents stream is not selected.",
            retryable=False,
        )
    return value


def _required_id(value: object, *, field: str) -> str:
    result = _optional_string(value)
    if result is None or len(result) > 500:
        raise _invalid_response(f"Linear {field} is invalid.")
    return result


def _required_string(value: object, *, field: str) -> str:
    result = _optional_string(value)
    if result is None:
        raise _invalid_response(f"Linear {field} is invalid.")
    return result


def _bounded_string(value: object, *, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_DOCUMENT_CHARS:
        raise _invalid_response(f"Linear {field} is invalid.")
    return value


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    result = value.strip()
    return result or None


def _required_datetime(value: object, *, field: str) -> datetime:
    result = _optional_datetime(value)
    if result is None:
        raise _invalid_response(f"Linear {field} is invalid.")
    return result


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None else result.replace(tzinfo=timezone.utc)


def _object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid_response(f"{field} is invalid.")
    return {str(key): item for key, item in value.items()}


def _optional_object(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _object_list(value: object, *, field: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise _invalid_response(f"{field} is invalid.")
    return tuple(_object(item, field=field) for item in value)


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    return _object(value, field=field)


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _invalid_response(f"Linear {field} is invalid.")
    items: list[str] = []
    for item in value:
        normalized = _optional_string(item)
        if normalized is None:
            raise _invalid_response(f"Linear {field} is invalid.")
        items.append(normalized)
    return tuple(items)


def _json_value(value: object) -> object | None:
    if value is None:
        return None
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise _invalid_response("Linear returned invalid structured content.") from error


def _safe_linear_url(value: object) -> str | None:
    url = _optional_string(value)
    if url is None or not url.startswith("https://linear.app/"):
        return None
    return url


_LINEAR_UPLOAD_PATTERN = re.compile(
    r"https://uploads\.linear\.app/[^\s<>)\]\"']+",
    flags=re.IGNORECASE,
)


def _document_attachments(
    document: Mapping[str, object],
) -> tuple[_LinearAttachment, ...]:
    document_id = _required_id(document.get("id"), field="document ID")
    content = _bounded_string(document.get("content"), field="document content")
    result: list[_LinearAttachment] = []
    seen: set[str] = set()
    for match in _LINEAR_UPLOAD_PATTERN.finditer(content):
        source_url = _safe_upload_url(match.group(0))
        if source_url is None or source_url in seen:
            continue
        seen.add(source_url)
        parsed = urlsplit(source_url)
        name = unquote(parsed.path.rsplit("/", 1)[-1]).strip() or "Linear image"
        media_type, _encoding = mimetypes.guess_type(name)
        digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:32]
        result.append(
            _LinearAttachment(
                external_id=f"{document_id}:{digest}",
                name=name[:500],
                media_type=media_type,
                source_url=source_url,
            )
        )
    return tuple(result)


def _safe_upload_url(value: object) -> str | None:
    url = _optional_string(value)
    if url is None:
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "uploads.linear.app"
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
    ):
        return None
    return parsed.geturl()


def _invalid_response(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_response_invalid",
        message,
        retryable=False,
    )


__all__ = [
    "LINEAR_KNOWLEDGE_MANIFEST",
    "LinearKnowledgeAdapter",
    "create_linear_knowledge_adapter",
]
