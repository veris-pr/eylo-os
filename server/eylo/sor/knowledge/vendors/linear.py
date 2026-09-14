"""Linear Documents adapter for Eylo's canonical Knowledge profile."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from http import HTTPStatus
from typing import overload
from urllib.parse import parse_qsl, unquote, urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from eylo.common.contracts.json_values import JsonObject
from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.knowledge.contracts import (
    KnowledgeAttachment,
    KnowledgeAttachmentContent,
    KnowledgeAttachmentPayload,
    KnowledgeAuthor,
    KnowledgeAuthorPayload,
    KnowledgeBlock,
    KnowledgeBlockPayload,
    KnowledgeBodyRepresentation,
    KnowledgeDocument,
    KnowledgeDocumentPayload,
    KnowledgeEntityKind,
    KnowledgeProperty,
    KnowledgePropertyPayload,
    KnowledgeSourceFormat,
    KnowledgeSpace,
    KnowledgeSpacePayload,
    KnowledgeToolName,
    KnowledgeVersion,
    KnowledgeVersionPayload,
    knowledge_source_body,
)
from eylo.sor.knowledge.vendors.linear_contracts import (
    MAX_DOCUMENT_CHARS,
    MAX_PAGE_RECORDS,
    LinearDateComparator,
    LinearDocument,
    LinearDocumentResult,
    LinearDocumentsResult,
    LinearIssueReference,
    LinearNativeModel,
    LinearPageVariables,
    LinearRecord,
    LinearRecordVariables,
    LinearUpdatedFilter,
    LinearUser,
    LinearUserResult,
    LinearUsersResult,
    LinearWorkspaceResult,
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
    SorFieldDataType,
    SorOAuthSpec,
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
from eylo.sor.shared.linear import linear_graphql_data

LINEAR_ORIGIN = "https://api.linear.app"
LINEAR_GRAPHQL_PATH = "/graphql"
LINEAR_API_VERSION = "graphql-current"
LINEAR_CURSOR_VERSION = 1
LINEAR_RECONCILIATION_OVERLAP = timedelta(minutes=2)
_ATTACHMENT_DOCUMENT_PAGE_SIZE = 25

READ_SCOPE = "read"


class LinearKnowledgeStream(StrEnum):
    """Closed vendor stream vocabulary owned by this adapter."""

    DOCUMENTS = "documents"
    AUTHORS = "authors"
    ATTACHMENTS = "attachments"


class _DocumentParentKind(StrEnum):
    """Native document parent kinds exposed in the existing source metadata."""

    INITIATIVE = "initiative"
    ISSUE = "issue"
    PROJECT = "project"
    RELEASE = "release"


class _DocumentLifecycle(StrEnum):
    """Projected document states derived from Linear's flags and timestamps."""

    ACTIVE = "ACTIVE"
    HIDDEN = "HIDDEN"
    ARCHIVED = "ARCHIVED"
    TRASHED = "TRASHED"


class _AuthorKind(StrEnum):
    """Existing Knowledge author labels derived from a native user predicate."""

    USER = "user"
    INACTIVE_USER = "inactive_user"


_STREAM_ENTITY = {
    LinearKnowledgeStream.DOCUMENTS: KnowledgeEntityKind.DOCUMENT,
    LinearKnowledgeStream.AUTHORS: KnowledgeEntityKind.AUTHOR,
    LinearKnowledgeStream.ATTACHMENTS: KnowledgeEntityKind.ATTACHMENT,
}
_RELATIONSHIP_TARGETS = {
    LinearKnowledgeStream.DOCUMENTS: {
        SorRelationshipRole.AUTHOR: LinearKnowledgeStream.AUTHORS
    },
    LinearKnowledgeStream.ATTACHMENTS: {
        SorRelationshipRole.DOCUMENT: LinearKnowledgeStream.DOCUMENTS
    },
}
_READ_TOOLS = frozenset({KnowledgeToolName.SEARCH, KnowledgeToolName.GET})
_TOOL_STREAMS = {
    KnowledgeToolName.SEARCH: frozenset({LinearKnowledgeStream.DOCUMENTS}),
    KnowledgeToolName.GET: frozenset(
        {LinearKnowledgeStream.DOCUMENTS, LinearKnowledgeStream.ATTACHMENTS}
    ),
}


LINEAR_KNOWLEDGE_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.KNOWLEDGE,
    vendor_key="linear",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                LinearKnowledgeStream.DOCUMENTS: "Documents",
                LinearKnowledgeStream.AUTHORS: "Authors",
                LinearKnowledgeStream.ATTACHMENTS: "Document images",
            }[stream_key],
            description={
                LinearKnowledgeStream.DOCUMENTS: (
                    "Current Linear documents with Markdown content and source "
                    "provenance. Older revisions remain in Linear."
                ),
                LinearKnowledgeStream.AUTHORS: "Workspace users referenced by current documents.",
                LinearKnowledgeStream.ATTACHMENTS: (
                    "Images referenced by the latest Linear document content."
                ),
            }[stream_key],
            canonical_entity=entity,
            change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
            depends_on=frozenset(
                set(_RELATIONSHIP_TARGETS.get(stream_key, {}).values())
            ),
            relationship_targets=SorRelationshipTargets(
                by_role=_RELATIONSHIP_TARGETS.get(stream_key, {}),
            ),
        )
        for stream_key, entity in _STREAM_ENTITY.items()
    ),
    readable_entities=frozenset(_STREAM_ENTITY.values()),
    writable_entities=frozenset(),
    readable_tools=_READ_TOOLS,
    writable_tools=frozenset(),
    change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
    required_scopes={stream_key: (READ_SCOPE,) for stream_key in _STREAM_ENTITY},
    tool_streams={
        tool.value: frozenset(stream.value for stream in streams)
        for tool, streams in _TOOL_STREAMS.items()
    },
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
    data_type: SorFieldDataType,
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
    LinearKnowledgeStream.DOCUMENTS: (
        _field("title", "Title", SorFieldDataType.TEXT, nullable=False),
        _field("path", "Location", SorFieldDataType.STRING_ARRAY, nullable=False),
        _field("normalized_text", "Content", SorFieldDataType.TEXT, nullable=False),
        _field("source_format", "Source format", SorFieldDataType.TEXT, nullable=False),
        _field("source_body", "Source body", SorFieldDataType.BOUNDED_JSON),
        _field("content_hash", "Content hash", SorFieldDataType.TEXT, nullable=False),
        _field("version", "Content revision", SorFieldDataType.TEXT),
        _field("lifecycle_state", "State", SorFieldDataType.TEXT),
        _field("author_external_id", "Creator ID", SorFieldDataType.REFERENCE),
        _field("source_created_at", "Created", SorFieldDataType.TIMESTAMP),
        _field("source_updated_at", "Updated", SorFieldDataType.TIMESTAMP),
        _field("custom_fields", "Linear context", SorFieldDataType.BOUNDED_JSON),
    ),
    LinearKnowledgeStream.AUTHORS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("primary_email", "Email", SorFieldDataType.TEXT),
        _field("kind", "Kind", SorFieldDataType.TEXT),
        _field("avatar_url", "Avatar URL", SorFieldDataType.LINK),
    ),
    LinearKnowledgeStream.ATTACHMENTS: (
        _field("document_external_id", "Document ID", SorFieldDataType.REFERENCE, nullable=False),
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("media_type", "Media type", SorFieldDataType.TEXT),
        _field("size_bytes", "Size", SorFieldDataType.INTEGER),
        _field("source_url", "Source URL", SorFieldDataType.LINK, nullable=False),
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
    LinearKnowledgeStream.DOCUMENTS: f"""
      query EyloLinearDocuments(
        $first: Int!, $after: String, $filter: DocumentFilter
      ) {{
        documents(first: $first, after: $after, filter: $filter, orderBy: updatedAt) {{
          nodes {{{_DOCUMENT_FIELDS}}}
          pageInfo {{ hasNextPage endCursor }}
        }}
      }}
    """,
    LinearKnowledgeStream.AUTHORS: """
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


class _LinearCursor(BaseModel):
    """Validated continuation state; the encoder owns the durable wire format."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    floor: AwareDatetime | None
    after: str | None
    high: AwareDatetime | None
    started_at: AwareDatetime


class _LinearCursorWire(BaseModel):
    """Versioned JSON contract persisted between Linear document pages."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: int
    floor: str | None = None
    after: str | None = None
    high: str | None = None
    started_at: str


class _LinearAttachmentCursor(BaseModel):
    """Resume within one document's attachments without losing page progress."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    floor: AwareDatetime | None
    page_after: str | None
    document_index: int = Field(ge=0)
    attachment_index: int = Field(ge=0)
    high: AwareDatetime | None
    started_at: AwareDatetime


class _LinearAttachmentCursorWire(BaseModel):
    """Versioned JSON contract persisted within one attachment page."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: int
    floor: str | None = None
    page_after: str | None = None
    document_index: int = Field(ge=0)
    attachment_index: int = Field(ge=0)
    high: str | None = None
    started_at: str


class _LinearAttachment(BaseModel):
    """One upload reference extracted after validating its document and origin."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

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
        organization = _parse_native(data, LinearWorkspaceResult).organization
        return SorConnectionVerification(
            account_external_id=organization.id,
            account_display_name=(
                _optional_string(organization.name) or "Linear workspace"
            ),
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=LINEAR_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        selected_streams = tuple(
            _require_stream(key, selected=self._context.selected_objects)
            for key in self._context.selected_objects
        )
        streams = {stream.key: stream for stream in LINEAR_KNOWLEDGE_MANIFEST.streams}
        objects = tuple(
            SorDiscoveredObject(
                key=stream_key,
                label=streams[stream_key].label,
                fields=_SCHEMA_FIELDS[stream_key],
            )
            for stream_key in selected_streams
        )
        if not objects:
            raise SorVendorOperationError(
                SorVendorErrorCode.SOURCE_SELECTION_EMPTY,
                "The Linear Documents source selects no streams.",
                recovery=SorRecoveryPolicy.TERMINAL,
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
        if stream_key == LinearKnowledgeStream.ATTACHMENTS:
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
        singular = (
            "document" if stream_key == LinearKnowledgeStream.DOCUMENTS else "user"
        )
        selection = (
            _DOCUMENT_FIELDS
            if stream_key == LinearKnowledgeStream.DOCUMENTS
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
            LinearRecordVariables(id=record_id),
            operation="read Linear knowledge record",
        )
        record = (
            _parse_native(data, LinearDocumentResult).document
            if stream_key == LinearKnowledgeStream.DOCUMENTS
            else _parse_native(data, LinearUserResult).user
        )
        if record is None:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        archived_at = record.archived_datetime
        if archived_at is not None:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
                deleted_at=archived_at,
                reason="Archived in Linear",
            )
        return self._external_record(record)

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

    def normalize_space(
        self,
        record: SorExternalRecord,
        payload: KnowledgeSpacePayload,
    ) -> KnowledgeSpace:
        raise _normalization_unavailable("space")

    def normalize_document(
        self,
        record: SorExternalRecord,
        payload: KnowledgeDocumentPayload,
    ) -> KnowledgeDocument:
        return KnowledgeDocument(
            external_id=record.external_id,
            title=payload.title,
            space_external_id=payload.space_external_id,
            parent_external_id=payload.parent_external_id,
            path=payload.path,
            source_format=payload.source_format,
            normalized_text=payload.normalized_text,
            source_body=payload.source_body,
            content_hash=payload.content_hash,
            version=payload.version,
            lifecycle_state=payload.lifecycle_state,
            author_external_id=payload.author_external_id,
            label_external_ids=payload.label_external_ids,
            unsupported_blocks=payload.unsupported_blocks,
            source_created_at=payload.source_created_at or record.source_created_at,
            source_updated_at=payload.source_updated_at or record.source_updated_at,
            source_url=record.source_url,
            custom_fields=payload.custom_fields,
        )

    def normalize_block(
        self,
        record: SorExternalRecord,
        payload: KnowledgeBlockPayload,
    ) -> KnowledgeBlock:
        raise _normalization_unavailable("block")

    def normalize_version(
        self,
        record: SorExternalRecord,
        payload: KnowledgeVersionPayload,
    ) -> KnowledgeVersion:
        raise _normalization_unavailable("version")

    def normalize_property(
        self,
        record: SorExternalRecord,
        payload: KnowledgePropertyPayload,
    ) -> KnowledgeProperty:
        raise _normalization_unavailable("property")

    def normalize_attachment(
        self,
        record: SorExternalRecord,
        payload: KnowledgeAttachmentPayload,
    ) -> KnowledgeAttachment:
        return KnowledgeAttachment(
            external_id=record.external_id,
            document_external_id=payload.document_external_id,
            name=payload.name,
            media_type=payload.media_type,
            size_bytes=payload.size_bytes,
            source_url=_safe_upload_url(payload.source_url),
            source_url_expires_at=payload.source_url_expires_at,
        )

    def normalize_author(
        self,
        record: SorExternalRecord,
        payload: KnowledgeAuthorPayload,
    ) -> KnowledgeAuthor:
        return KnowledgeAuthor(
            external_id=record.external_id,
            name=payload.name,
            primary_email=payload.primary_email,
            kind=payload.kind,
            avatar_url=payload.avatar_url,
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
                vendor_object_key=LinearKnowledgeStream.ATTACHMENTS,
                external_id=attachment_id,
            )
        parsed = urlsplit(attachment.source_url)
        response = await self._uploads_client.request_binary(
            parsed.path,
            query=dict(parse_qsl(parsed.query, keep_blank_values=True)),
            response_body_limit=maximum_bytes,
        )
        if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
            raise SorExternalRecordNotFound(
                vendor_object_key=LinearKnowledgeStream.ATTACHMENTS,
                external_id=attachment_id,
            )
        if not 200 <= response.status_code < 300:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_REQUEST_REJECTED,
                "Linear did not return the requested document image.",
                recovery=(
                    SorRecoveryPolicy.RETRY
                    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
                    else SorRecoveryPolicy.TERMINAL
                ),
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
        if isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE_RECORDS:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_PAGE_INVALID,
                "Linear page limit must be between 1 and 200.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if stream_key == LinearKnowledgeStream.ATTACHMENTS:
            return await self._read_attachment_page(cursor=cursor, limit=limit)
        selected_fields = self._selected_fields(stream_key)
        checkpoint = _decode_cursor(cursor)
        variables = _page_variables(
            limit=limit, after=checkpoint.after, floor=checkpoint.floor
        )
        data, _response = await self._graphql(
            _PAGE_QUERIES[stream_key],
            variables,
            operation=f"list Linear {stream_key}",
        )
        connection = (
            _parse_native(data, LinearDocumentsResult).documents
            if stream_key == LinearKnowledgeStream.DOCUMENTS
            else _parse_native(data, LinearUsersResult).users
        )
        rows = connection.nodes
        if len(rows) > limit:
            raise _invalid_response("Linear returned more records than requested.")
        has_more = connection.page_info.has_next_page
        end_cursor = _optional_string(connection.page_info.end_cursor)
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
                    row,
                    selected_fields=selected_fields,
                )
                for row in rows
                if row.archived_at is None
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
        selected_fields = self._selected_fields(LinearKnowledgeStream.ATTACHMENTS)
        checkpoint = _decode_attachment_cursor(cursor)
        data, _response = await self._graphql(
            _PAGE_QUERIES[LinearKnowledgeStream.DOCUMENTS],
            _page_variables(
                limit=min(limit, _ATTACHMENT_DOCUMENT_PAGE_SIZE),
                after=checkpoint.page_after,
                floor=checkpoint.floor,
            ),
            operation="list Linear document images",
        )
        connection = _parse_native(data, LinearDocumentsResult).documents
        documents = connection.nodes
        page_has_more = connection.page_info.has_next_page
        end_cursor = _optional_string(connection.page_info.end_cursor)

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

    def _selected_fields(self, stream_key: LinearKnowledgeStream) -> tuple[str, ...]:
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
                SorVendorErrorCode.SOURCE_MAPPING_INVALID,
                f"The Linear mapping selects unknown {stream_key} fields.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if not fields:
            raise SorVendorOperationError(
                SorVendorErrorCode.SOURCE_MAPPING_EMPTY,
                f"The active mapping selects no {stream_key} fields.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        return fields

    def _external_record(
        self,
        row: LinearDocument | LinearUser,
        *,
        selected_fields: tuple[str, ...] | None = None,
    ) -> SorExternalRecord:
        stream_key = (
            LinearKnowledgeStream.DOCUMENTS
            if isinstance(row, LinearDocument)
            else LinearKnowledgeStream.AUTHORS
        )
        selected = selected_fields or self._selected_fields(stream_key)
        values = _linear_payload(row)
        payload = {field: values.get(field) for field in selected}
        updated_at = row.updated_datetime
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=row.id,
            payload=payload,
            source_created_at=row.created_datetime,
            source_updated_at=updated_at,
            source_revision=updated_at.isoformat(),
            source_url=_safe_linear_url(row.url),
        )

    def _external_attachment(
        self,
        document: LinearDocument,
        attachment: _LinearAttachment,
        *,
        selected_fields: tuple[str, ...] | None = None,
    ) -> SorExternalRecord:
        selected = selected_fields or self._selected_fields(
            LinearKnowledgeStream.ATTACHMENTS
        )
        values: dict[str, object | None] = {
            "document_external_id": document.id,
            "name": attachment.name,
            "media_type": attachment.media_type,
            "size_bytes": None,
            "source_url": attachment.source_url,
        }
        payload = {field: values.get(field) for field in selected}
        updated_at = document.updated_datetime
        return SorExternalRecord(
            vendor_object_key=LinearKnowledgeStream.ATTACHMENTS,
            external_id=attachment.external_id,
            payload=payload,
            source_created_at=document.created_datetime,
            source_updated_at=updated_at,
            source_revision=f"{updated_at.isoformat()}:{attachment.external_id}",
            source_url=attachment.source_url,
        )

    async def _fetch_document(self, document_id: str) -> LinearDocument:
        data, _response = await self._graphql(
            f"""
              query EyloLinearDocument($id: String!) {{
                document(id: $id) {{ {_DOCUMENT_FIELDS} }}
              }}
            """,
            LinearRecordVariables(id=document_id),
            operation="read Linear document",
        )
        row = _parse_native(data, LinearDocumentResult).document
        if row is None:
            raise SorExternalRecordNotFound(
                vendor_object_key=LinearKnowledgeStream.DOCUMENTS,
                external_id=document_id,
            )
        return row

    async def _graphql(
        self,
        document: str,
        variables: LinearPageVariables | LinearRecordVariables | None = None,
        *,
        operation: str,
    ) -> tuple[JsonObject, SorJsonResponse]:
        response = await self._client.request(
            LINEAR_GRAPHQL_PATH,
            method="POST",
            payload={
                "query": document,
                "variables": variables.model_dump(by_alias=True)
                if variables is not None
                else {},
            },
        )
        return linear_graphql_data(response, operation=operation), response


def create_linear_knowledge_adapter(
    context: SorAdapterContext,
) -> LinearKnowledgeAdapter:
    """Construct the explicit Linear Knowledge adapter."""
    return LinearKnowledgeAdapter(context)


def _linear_payload(
    row: LinearDocument | LinearUser,
) -> dict[str, object | None]:
    if isinstance(row, LinearUser):
        return {
            "name": row.display_name or row.name,
            "primary_email": row.email,
            "kind": _AuthorKind.USER if row.active else _AuthorKind.INACTIVE_USER,
            "avatar_url": row.avatar_url,
        }
    content = row.content or ""
    title = _optional_string(row.title) or "Untitled document"
    parent_type, parent_id, parent_label = _document_parent(row)
    return {
        "title": title,
        "normalized_text": content,
        "source_format": KnowledgeSourceFormat.LINEAR_MARKDOWN,
        "source_body": knowledge_source_body(
            KnowledgeBodyRepresentation.MARKDOWN,
            content,
        ),
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "version": row.document_content_id,
        "lifecycle_state": _document_lifecycle(row),
        "author_external_id": row.creator.id if row.creator is not None else None,
        "source_created_at": row.created_at,
        "source_updated_at": row.updated_at,
        "custom_fields": {
            "document_content_id": row.document_content_id,
            "slug_id": row.slug_id,
            "icon": row.icon,
            "color": row.color,
            "parent_type": parent_type,
            "parent_external_id": parent_id,
            "parent_label": parent_label,
            "owner_external_id": row.owner.id if row.owner is not None else None,
            "updated_by_external_id": row.updated_by.id
            if row.updated_by is not None
            else None,
        },
        "path": [parent_label, title] if parent_label else [title],
    }


def _document_parent(
    row: LinearDocument,
) -> tuple[_DocumentParentKind | None, str | None, str | None]:
    for parent_type, parent in (
        (_DocumentParentKind.INITIATIVE, row.initiative),
        (_DocumentParentKind.ISSUE, row.issue),
        (_DocumentParentKind.PROJECT, row.project),
        (_DocumentParentKind.RELEASE, row.release),
    ):
        if parent is None:
            continue
        label = (
            _optional_string(parent.identifier) or _optional_string(parent.title)
            if isinstance(parent, LinearIssueReference)
            else _optional_string(parent.name)
        )
        return parent_type, parent.id, label
    return None, None, None


def _document_lifecycle(row: LinearDocument) -> _DocumentLifecycle:
    if row.trashed is True:
        return _DocumentLifecycle.TRASHED
    if row.archived_at is not None:
        return _DocumentLifecycle.ARCHIVED
    if row.hidden_at is not None:
        return _DocumentLifecycle.HIDDEN
    return _DocumentLifecycle.ACTIVE


def _normalization_unavailable(entity: str) -> SorCapabilityUnavailable:
    return SorCapabilityUnavailable(
        f"Linear Documents does not project {entity} records in this adapter revision."
    )


def _decode_cursor(value: str | None) -> _LinearCursor:
    now = datetime.now(timezone.utc)
    if value is None:
        return _LinearCursor(floor=None, after=None, high=None, started_at=now)
    try:
        payload = _LinearCursorWire.model_validate_json(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CURSOR_INVALID,
            "Linear cursor is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
    if payload.version != LINEAR_CURSOR_VERSION:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CURSOR_INVALID,
            "Linear cursor version is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return _LinearCursor(
        floor=_optional_datetime(payload.floor),
        after=_optional_string(payload.after),
        high=_optional_datetime(payload.high),
        started_at=_required_datetime(
            payload.started_at, field="Linear cursor start"
        ),
    )


def _encode_cursor(cursor: _LinearCursor) -> str:
    payload = _LinearCursorWire(
        version=LINEAR_CURSOR_VERSION,
        floor=_linear_datetime(cursor.floor),
        after=cursor.after,
        high=_linear_datetime(cursor.high),
        started_at=_linear_datetime(cursor.started_at),
    )
    return json.dumps(
        payload.model_dump(mode="json"),
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
        payload = _LinearAttachmentCursorWire.model_validate_json(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CURSOR_INVALID,
            "Linear attachment cursor is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
    if payload.version != LINEAR_CURSOR_VERSION:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CURSOR_INVALID,
            "Linear attachment cursor version is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return _LinearAttachmentCursor(
        floor=_optional_datetime(payload.floor),
        page_after=_optional_string(payload.page_after),
        document_index=payload.document_index,
        attachment_index=payload.attachment_index,
        high=_optional_datetime(payload.high),
        started_at=_required_datetime(
            payload.started_at, field="Linear attachment cursor start"
        ),
    )


def _encode_attachment_cursor(cursor: _LinearAttachmentCursor) -> str:
    payload = _LinearAttachmentCursorWire(
        version=LINEAR_CURSOR_VERSION,
        floor=_linear_datetime(cursor.floor),
        page_after=cursor.page_after,
        document_index=cursor.document_index,
        attachment_index=cursor.attachment_index,
        high=_linear_datetime(cursor.high),
        started_at=_linear_datetime(cursor.started_at),
    )
    return json.dumps(
        payload.model_dump(mode="json"),
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
    rows: Sequence[LinearRecord],
    *,
    current: datetime | None,
) -> datetime | None:
    result = current
    for row in rows:
        value = row.updated_datetime
        if result is None or value > result:
            result = value
    return result


@overload
def _linear_datetime(value: None) -> None: ...


@overload
def _linear_datetime(value: datetime) -> str: ...


def _linear_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _page_variables(
    *, limit: int, after: str | None, floor: datetime | None
) -> LinearPageVariables:
    timestamp = _linear_datetime(floor)
    return LinearPageVariables(
        first=limit,
        after=after,
        filter=(
            LinearUpdatedFilter(updatedAt=LinearDateComparator(gte=timestamp))
            if timestamp is not None
            else None
        ),
    )


def _credential(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Linear credential {key} is missing.")
    return value.strip()


def _require_stream(
    value: str, *, selected: tuple[str, ...]
) -> LinearKnowledgeStream:
    if value not in _STREAM_ENTITY or value not in selected:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNSUPPORTED,
            "The requested Linear Documents stream is not selected.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return LinearKnowledgeStream(value)


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
        raise _invalid_response(
            "Linear returned invalid structured content."
        ) from error


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
    document: LinearDocument,
) -> tuple[_LinearAttachment, ...]:
    document_id = document.id
    content = document.content or ""
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
        SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _parse_native[ModelT: LinearNativeModel](
    value: object, model: type[ModelT]
) -> ModelT:
    try:
        return model.model_validate(value)
    except ValidationError:
        raise _invalid_response(
            "Linear returned an invalid knowledge response."
        ) from None


__all__ = [
    "LINEAR_KNOWLEDGE_MANIFEST",
    "LinearKnowledgeAdapter",
    "create_linear_knowledge_adapter",
]
