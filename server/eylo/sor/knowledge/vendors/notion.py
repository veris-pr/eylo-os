"""Notion adapter for Eylo's canonical Documents profile."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from http import HTTPMethod, HTTPStatus
from typing import Annotated, Literal, Self
from urllib.parse import quote, quote_from_bytes, unquote_to_bytes, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.knowledge.contracts import (
    KnowledgeAttachment,
    KnowledgeAttachmentPayload,
    KnowledgeAuthor,
    KnowledgeAuthorPayload,
    KnowledgeBlock,
    KnowledgeBlockPayload,
    KnowledgeCreateCommandPayload,
    KnowledgeDocument,
    KnowledgeDocumentPayload,
    KnowledgeEntityKind,
    KnowledgeProperty,
    KnowledgePropertyPayload,
    KnowledgeSourceBody,
    KnowledgeSourceFormat,
    KnowledgeSpace,
    KnowledgeSpacePayload,
    KnowledgeTextCommandPayload,
    KnowledgeToolName,
    KnowledgeUpdateCommandPayload,
    KnowledgeVersion,
    KnowledgeVersionPayload,
)
from eylo.sor.knowledge.vendors import notion_wire as native
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
    SorOAuthClientAuthMethod,
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
    SorWebhookPayloadError,
    SorWebhookSignal,
    SorWebhookSubscription,
    SorWebhookVerificationError,
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


class NotionStream(StrEnum):
    """Closed vendor stream vocabulary owned by this adapter."""

    DATA_SOURCES = "data_sources"
    PAGES = "pages"
    BLOCKS = "blocks"
    PROPERTIES = "properties"
    ATTACHMENTS = "attachments"
    AUTHORS = "authors"


_STREAM_ENTITY = {
    NotionStream.DATA_SOURCES: KnowledgeEntityKind.SPACE,
    NotionStream.PAGES: KnowledgeEntityKind.DOCUMENT,
    NotionStream.BLOCKS: KnowledgeEntityKind.BLOCK,
    NotionStream.PROPERTIES: KnowledgeEntityKind.PROPERTY,
    NotionStream.ATTACHMENTS: KnowledgeEntityKind.ATTACHMENT,
    NotionStream.AUTHORS: KnowledgeEntityKind.AUTHOR,
}
_RELATIONSHIP_TARGETS = {
    NotionStream.PAGES: {
        SorRelationshipRole.SPACE: NotionStream.DATA_SOURCES,
        SorRelationshipRole.PARENT: NotionStream.PAGES,
        SorRelationshipRole.AUTHOR: NotionStream.AUTHORS,
    },
    NotionStream.BLOCKS: {
        SorRelationshipRole.DOCUMENT: NotionStream.PAGES,
        SorRelationshipRole.PARENT: NotionStream.BLOCKS,
    },
    NotionStream.PROPERTIES: {SorRelationshipRole.DOCUMENT: NotionStream.PAGES},
    NotionStream.ATTACHMENTS: {SorRelationshipRole.DOCUMENT: NotionStream.PAGES},
}
_READ_TOOLS = frozenset(
    {
        KnowledgeToolName.SEARCH,
        KnowledgeToolName.GET,
        KnowledgeToolName.LIST_CHILDREN,
        KnowledgeToolName.DESCRIBE_FIELDS,
    }
)
_WRITE_TOOLS = frozenset(
    {
        KnowledgeToolName.CREATE,
        KnowledgeToolName.UPDATE,
        KnowledgeToolName.APPEND,
        KnowledgeToolName.COMMENT,
    }
)
_TOOL_STREAMS = {
    KnowledgeToolName.SEARCH: frozenset({NotionStream.PAGES}),
    KnowledgeToolName.GET: frozenset(
        {
            NotionStream.PAGES,
            NotionStream.BLOCKS,
            NotionStream.PROPERTIES,
            NotionStream.ATTACHMENTS,
        }
    ),
    KnowledgeToolName.LIST_CHILDREN: frozenset({NotionStream.PAGES}),
    KnowledgeToolName.DESCRIBE_FIELDS: frozenset(
        {NotionStream.PAGES, NotionStream.PROPERTIES}
    ),
    KnowledgeToolName.CREATE: frozenset(
        {NotionStream.DATA_SOURCES, NotionStream.PAGES}
    ),
    KnowledgeToolName.UPDATE: frozenset({NotionStream.PAGES}),
    KnowledgeToolName.APPEND: frozenset({NotionStream.PAGES, NotionStream.BLOCKS}),
    KnowledgeToolName.COMMENT: frozenset({NotionStream.PAGES}),
}
_MUTATION_RESULT_STREAMS = {tool: NotionStream.PAGES for tool in _WRITE_TOOLS}

_SUPPORTED_BLOCK_TYPES = frozenset(native.BlockType)
_FILE_BLOCK_TYPES = frozenset(
    {
        native.BlockType.AUDIO,
        native.BlockType.FILE,
        native.BlockType.IMAGE,
        native.BlockType.PDF,
        native.BlockType.VIDEO,
    }
)


NOTION_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.KNOWLEDGE,
    vendor_key="notion",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                NotionStream.DATA_SOURCES: "Data sources",
                NotionStream.PAGES: "Pages",
                NotionStream.BLOCKS: "Page blocks",
                NotionStream.PROPERTIES: "Page properties",
                NotionStream.ATTACHMENTS: "Page files",
                NotionStream.AUTHORS: "Workspace users",
            }[stream_key],
            description={
                NotionStream.DATA_SOURCES: "Data sources shared with the Notion connection.",
                NotionStream.PAGES: "Pages with enhanced Markdown and source provenance.",
                NotionStream.BLOCKS: "Recursive structured blocks retained for loss-aware audit.",
                NotionStream.PROPERTIES: "Page properties, including completed relation and rollup values.",
                NotionStream.ATTACHMENTS: "File metadata from page properties and file blocks.",
                NotionStream.AUTHORS: "Users visible to the Notion connection.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
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
    writable_entities=frozenset({"document"}),
    readable_tools=_READ_TOOLS,
    writable_tools=_WRITE_TOOLS,
    change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
    tool_streams={
        tool.value: frozenset(stream.value for stream in streams)
        for tool, streams in _TOOL_STREAMS.items()
    },
    mutation_result_streams={
        tool.value: stream.value for tool, stream in _MUTATION_RESULT_STREAMS.items()
    },
    oauth=SorOAuthSpec(
        authorization_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        send_authorization_scope=False,
        token_request_format=SorOAuthTokenRequestFormat.JSON,
        token_client_auth_method=SorOAuthClientAuthMethod.BASIC,
    ),
    fixed_origin=NOTION_API_ORIGIN,
    change_mode=SorChangeMode.APP_WEBHOOK,
    supports_custom_fields=True,
    supports_comments=True,
    supports_attachments=True,
    supports_structured_documents=True,
)


class NotionAppWebhookDelivery(BaseModel):
    """One signed workspace event before source-selection filtering."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_external_id: str
    signal: SorWebhookSignal


_NOTION_WEBHOOK_TOKEN_MAX_BYTES = 4096
_NOTION_SIGNATURE_HEADER = "x-notion-signature"
_NOTION_SIGNATURE_PREFIX = "sha256="


class NotionWebhookEntityType(StrEnum):
    """Native entity routing names; unknown kinds still produce a broad hint."""

    PAGE = "page"
    DATA_SOURCE = "data_source"
    DATABASE = "database"
    BLOCK = "block"


class NotionWebhookModel(BaseModel):
    """Consumed metadata only; page content and author data are not retained."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class NotionWebhookChallenge(NotionWebhookModel):
    """Unsigned initial challenge, never an authenticated change event."""

    verification_token: str = Field(repr=False, exclude=True)

    @field_validator("verification_token")
    @classmethod
    def bound_token(cls, value: str) -> str:
        if not 1 <= len(value.encode("utf-8")) <= _NOTION_WEBHOOK_TOKEN_MAX_BYTES:
            raise ValueError("Notion verification token size is invalid.")
        return value


class NotionWebhookEntity(NotionWebhookModel):
    """Native page/database/block identity before platform stream translation."""

    id: str
    type: str

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: object) -> str:
        return _notion_id(value, field="webhook entity ID")

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, value: object) -> str:
        return _required_string(value, field="webhook entity type")


class NotionWebhookPayload(NotionWebhookModel):
    """Workspace authority and event metadata; malformed optional dates stay absent."""

    workspace_id: str
    type: str
    entity: NotionWebhookEntity
    id: str | None = None
    timestamp: datetime | None = None

    @field_validator("workspace_id", mode="before")
    @classmethod
    def normalize_workspace(cls, value: object) -> str:
        return _notion_id(value, field="webhook workspace ID")

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, value: object) -> str:
        return _required_string(value, field="webhook event type")

    @field_validator("id", mode="before")
    @classmethod
    def normalize_delivery(cls, value: object) -> str | None:
        return _optional_string(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def normalize_time(cls, value: object) -> datetime | None:
        return _optional_datetime(value)


def notion_verification_token(*, body: bytes) -> str | None:
    """Return Notion's initial endpoint challenge without accepting an event."""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    try:
        return NotionWebhookChallenge.model_validate(payload).verification_token
    except ValidationError:
        return None


def verify_notion_app_webhook(
    *,
    headers: Mapping[str, str],
    body: bytes,
    verification_token: str,
) -> None:
    """Authenticate one Notion delivery against the saved verification token."""
    signature = _header(headers, _NOTION_SIGNATURE_HEADER)
    if signature is None or not signature.startswith(_NOTION_SIGNATURE_PREFIX):
        raise SorWebhookVerificationError("Notion webhook signature is missing.")
    expected = (
        _NOTION_SIGNATURE_PREFIX
        + hmac.new(
            verification_token.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(signature, expected):
        raise SorWebhookVerificationError("Notion webhook signature is invalid.")


def parse_notion_app_webhook(*, body: bytes) -> NotionAppWebhookDelivery:
    """Extract the workspace boundary and one current-record refetch signal."""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SorWebhookPayloadError(
            "Notion webhook body is not valid JSON."
        ) from error
    try:
        event = NotionWebhookPayload.model_validate(payload)
        streams: Mapping[str, NotionStream] = {
            NotionWebhookEntityType.PAGE: NotionStream.PAGES,
            NotionWebhookEntityType.DATA_SOURCE: NotionStream.DATA_SOURCES,
            NotionWebhookEntityType.DATABASE: NotionStream.DATA_SOURCES,
            NotionWebhookEntityType.BLOCK: NotionStream.BLOCKS,
        }
        stream_key = streams.get(event.entity.type)
        signal = SorWebhookSignal(
            delivery_id=event.id,
            event_type=event.type,
            vendor_object_key=stream_key,
            external_id=event.entity.id if stream_key is not None else None,
            occurred_at=event.timestamp,
        )
    except SorVendorOperationError as error:
        raise SorWebhookPayloadError(str(error)) from error
    except ValidationError as error:
        raise SorWebhookPayloadError("Notion webhook metadata is invalid.") from error
    return NotionAppWebhookDelivery(
        organization_external_id=event.workspace_id,
        signal=signal,
    )


def _field(
    key: str,
    label: str,
    data_type: SorFieldDataType,
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
    NotionStream.DATA_SOURCES: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("kind", "Kind", SorFieldDataType.TEXT, nullable=False),
        _field("custom_fields", "Property schema", SorFieldDataType.BOUNDED_JSON),
    ),
    NotionStream.PAGES: (
        _field("title", "Title", SorFieldDataType.TEXT, nullable=False, writable=True),
        _field(
            "space_external_id",
            "Data source ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field(
            "parent_external_id",
            "Parent page ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field("path", "Path", SorFieldDataType.STRING_ARRAY),
        _field("source_format", "Source format", SorFieldDataType.TEXT, nullable=False),
        _field("normalized_text", "Content", SorFieldDataType.TEXT, writable=True),
        _field("source_body", "Source body", SorFieldDataType.BOUNDED_JSON),
        _field("content_hash", "Content hash", SorFieldDataType.TEXT, nullable=False),
        _field("version", "Source revision", SorFieldDataType.TEXT),
        _field("lifecycle_state", "State", SorFieldDataType.TEXT),
        _field("author_external_id", "Last editor ID", SorFieldDataType.REFERENCE),
        _field(
            "label_external_ids", "Select option IDs", SorFieldDataType.STRING_ARRAY
        ),
        _field(
            "unsupported_blocks", "Unsupported content", SorFieldDataType.STRING_ARRAY
        ),
        _field("source_created_at", "Created", SorFieldDataType.TIMESTAMP),
        _field("source_updated_at", "Updated", SorFieldDataType.TIMESTAMP),
    ),
    NotionStream.BLOCKS: (
        _field(
            "document_external_id",
            "Document ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("parent_external_id", "Parent block ID", SorFieldDataType.REFERENCE),
        _field("kind", "Kind", SorFieldDataType.TEXT, nullable=False),
        _field("order", "Order", SorFieldDataType.INTEGER, nullable=False),
        _field("normalized_text", "Content", SorFieldDataType.TEXT),
        _field("source_body", "Source body", SorFieldDataType.BOUNDED_JSON),
        _field("supported", "Supported", SorFieldDataType.BOOLEAN, nullable=False),
        _field("source_created_at", "Created", SorFieldDataType.TIMESTAMP),
        _field("source_updated_at", "Updated", SorFieldDataType.TIMESTAMP),
    ),
    NotionStream.PROPERTIES: (
        _field(
            "document_external_id",
            "Document ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("key", "Property ID", SorFieldDataType.TEXT, nullable=False),
        _field("label", "Property name", SorFieldDataType.TEXT, nullable=False),
        _field("value_type", "Value type", SorFieldDataType.TEXT, nullable=False),
        _field("value", "Value", SorFieldDataType.BOUNDED_JSON),
        _field("source_updated_at", "Updated", SorFieldDataType.TIMESTAMP),
    ),
    NotionStream.ATTACHMENTS: (
        _field(
            "document_external_id",
            "Document ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("media_type", "Media type", SorFieldDataType.TEXT),
        _field("size_bytes", "Size", SorFieldDataType.INTEGER),
        _field("source_url", "Source URL", SorFieldDataType.LINK),
        _field("source_url_expires_at", "URL expires", SorFieldDataType.TIMESTAMP),
    ),
    NotionStream.AUTHORS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("primary_email", "Email", SorFieldDataType.TEXT),
        _field("kind", "Kind", SorFieldDataType.TEXT),
        _field("avatar_url", "Avatar URL", SorFieldDataType.LINK),
    ),
}


type _CursorToken = Annotated[
    str, Field(min_length=1, max_length=native.CURSOR_LENGTH_LIMIT)
]


class _MemberCursor(BaseModel):
    """Notion property-page position owned by the vendor cursor codec."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    page_cursor: _CursorToken | None
    current_page_id: str | None
    current_page_is_last: bool
    offset: int = Field(ge=0)

    @field_validator("current_page_id")
    @classmethod
    def normalize_page_id(cls, value: str | None) -> str | None:
        return _optional_notion_id(value)

    @model_validator(mode="after")
    def require_page_position(self) -> Self:
        if self.current_page_id is None and (
            self.offset != 0 or self.current_page_is_last
        ):
            raise ValueError("A property offset requires its page.")
        return self


class _TreeFrame(BaseModel):
    """One Notion child traversal position within a serialized cursor."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    parent_id: str
    parent_external_id: str | None
    child_cursor: _CursorToken | None
    offset: int = Field(ge=0)
    depth: int = Field(ge=0, le=MAX_TREE_DEPTH)

    @field_validator("parent_id", "parent_external_id")
    @classmethod
    def normalize_parent_id(cls, value: str | None) -> str | None:
        return _optional_notion_id(value)


class _TreeCursor(BaseModel):
    """Notion document traversal position owned by the vendor cursor codec."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    page_cursor: _CursorToken | None
    current_page_id: str | None
    current_page_is_last: bool
    page_attachment_offset: int = Field(ge=0)
    page_attachments_done: bool
    frames: tuple[_TreeFrame, ...] = Field(max_length=MAX_TREE_FRAMES)

    @field_validator("current_page_id")
    @classmethod
    def normalize_page_id(cls, value: str | None) -> str | None:
        return _optional_notion_id(value)


class _MemberCursorEnvelope(_MemberCursor):
    v: int = Field(ge=NOTION_CURSOR_VERSION, le=NOTION_CURSOR_VERSION)
    stream: Literal[NotionStream.PROPERTIES]


class _TreeCursorEnvelope(_TreeCursor):
    v: int = Field(ge=NOTION_CURSOR_VERSION, le=NOTION_CURSOR_VERSION)
    stream: Literal[NotionStream.BLOCKS, NotionStream.ATTACHMENTS]

    @model_validator(mode="after")
    def require_page_position(self) -> Self:
        if self.current_page_id is None and (
            self.current_page_is_last
            or self.page_attachment_offset != 0
            or self.frames
            or self.page_attachments_done != (self.stream != NotionStream.ATTACHMENTS)
        ):
            raise ValueError("A traversal position requires its page.")
        return self


class _AttachmentValue(BaseModel):
    """Current Notion attachment metadata before canonical projection."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    external_id: str
    document_external_id: str
    name: str
    media_type: str | None
    source_url: str | None = Field(repr=False, exclude=True)
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
            response_body_limit=native.RESPONSE_BODY_LIMIT,
            default_headers={"Notion-Version": NOTION_API_VERSION},
        )

    async def verify_connection(self) -> SorConnectionVerification:
        response = await self._client.request("/v1/users/me")
        user = native.parse_response(
            native.User, _expect(response, operation="identify the Notion connection")
        )
        bot = user.bot
        if bot is None:
            raise _invalid_response("Notion bot workspace is missing.")
        return SorConnectionVerification(
            account_external_id=_notion_id(
                bot.workspace_id,
                field="workspace ID",
            ),
            account_display_name=(
                _optional_string(bot.workspace_name)
                or _optional_string(user.name)
                or "Notion workspace"
            ),
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=NOTION_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise _invalid_operation(
                SorVendorErrorCode.SOURCE_SELECTION_EMPTY,
                "The Notion source selects no streams.",
            )
        streams = {stream.key: stream for stream in NOTION_MANIFEST.streams}
        objects: list[SorDiscoveredObject] = []
        for selected_key in self._context.selected_objects:
            stream = _require_stream(
                selected_key, selected=self._context.selected_objects
            )
            objects.append(
                SorDiscoveredObject(
                    key=stream,
                    label=streams[stream].label,
                    fields=_SCHEMA_FIELDS[stream],
                )
            )
        return SorDiscoveredSchema(
            objects=tuple(objects),
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
        if stream_key == NotionStream.DATA_SOURCES:
            data_source_id = _notion_id(external_id, field="data source ID")
            response = await self._client.request(
                f"/v1/data_sources/{_path_id(data_source_id)}"
            )
            return self._external_space(
                native.parse_response(
                    native.DataSource,
                    _required_response(response, stream_key, data_source_id),
                )
            )
        if stream_key == NotionStream.PAGES:
            page_id = _notion_id(external_id, field="page ID")
            page, markdown = await self._fetch_page_with_markdown(page_id)
            return self._external_document(page, markdown)
        if stream_key == NotionStream.BLOCKS:
            block_id = _notion_id(external_id, field="block ID")
            response = await self._client.request(f"/v1/blocks/{_path_id(block_id)}")
            block = native.parse_response(
                native.Block, _required_response(response, stream_key, block_id)
            )
            page_id = await self._root_page_id(block)
            parent_id = _block_parent_id(block)
            return self._external_block(
                page_id=page_id,
                parent_external_id=parent_id,
                row=block,
                order=0,
            )
        if stream_key == NotionStream.PROPERTIES:
            page_id, property_id = _decode_property_external_id(external_id)
            page = await self._fetch_page(page_id)
            label, value = _find_page_property(page, property_id)
            return await self._external_property(
                page_id=page_id,
                label=label,
                value=value,
                page=page,
            )
        if stream_key == NotionStream.ATTACHMENTS:
            value = await self._fetch_attachment(external_id)
            return _external_attachment(value)
        author_id = _notion_id(external_id, field="user ID")
        response = await self._client.request(f"/v1/users/{_path_id(author_id)}")
        return self._external_author(
            native.parse_response(
                native.User, _required_response(response, stream_key, author_id)
            )
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
        token = self._context.webhook_signing_secret
        if token is None:
            raise SorCapabilityUnavailable(
                "Notion webhook verification token is unavailable."
            )
        verify_notion_app_webhook(
            headers=headers,
            body=body,
            verification_token=token,
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        return (parse_notion_app_webhook(body=body).signal,)

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise _invalid_operation(
                SorVendorErrorCode.VENDOR_TOOL_UNSUPPORTED,
                "This Notion adapter does not execute the requested document action.",
            )
        if command.tool_name == KnowledgeToolName.CREATE:
            return await self._create_page(command)
        target_id = _required_target(command)
        current = await self._fetch_page(target_id)
        if (
            command.expected_source_revision is not None
            and command.expected_source_revision != _page_revision(current)
        ):
            raise _invalid_operation(
                SorVendorErrorCode.VENDOR_SOURCE_CONFLICT,
                "The Notion page changed after the Agent read it.",
            )
        if command.tool_name == KnowledgeToolName.UPDATE:
            response = await self._update_page(target_id, current, command)
            return _target_command_result(target_id, current, response)
        if command.tool_name == KnowledgeToolName.APPEND:
            response = await self._append_page(target_id, command)
            return _target_command_result(target_id, current, response)
        response = await self._comment_page(target_id, command)
        return _target_command_result(target_id, current, response)

    def normalize_space(
        self,
        record: SorExternalRecord,
        payload: KnowledgeSpacePayload,
    ) -> KnowledgeSpace:
        return KnowledgeSpace(
            external_id=record.external_id,
            name=payload.name,
            kind=payload.kind,
            source_url=record.source_url,
        )

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
        return KnowledgeBlock(
            external_id=record.external_id,
            document_external_id=payload.document_external_id,
            parent_external_id=payload.parent_external_id,
            kind=payload.kind,
            order=payload.order,
            normalized_text=payload.normalized_text,
            source_body=payload.source_body,
            supported=payload.supported,
            source_created_at=payload.source_created_at or record.source_created_at,
            source_updated_at=payload.source_updated_at or record.source_updated_at,
        )

    def normalize_version(
        self,
        record: SorExternalRecord,
        payload: KnowledgeVersionPayload,
    ) -> KnowledgeVersion:
        raise SorCapabilityUnavailable(
            "Notion source versions are not available in this adapter revision."
        )

    def normalize_property(
        self,
        record: SorExternalRecord,
        payload: KnowledgePropertyPayload,
    ) -> KnowledgeProperty:
        return KnowledgeProperty(
            external_id=record.external_id,
            document_external_id=payload.document_external_id,
            key=payload.key,
            label=payload.label,
            value_type=payload.value_type,
            value=payload.value,
            source_updated_at=payload.source_updated_at or record.source_updated_at,
        )

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
            source_url=payload.source_url or record.source_url,
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
            avatar_url=payload.avatar_url or record.source_url,
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
                SorVendorErrorCode.VENDOR_PAGE_INVALID,
                "Notion page limit must be positive.",
            )
        page_limit = min(limit, native.PAGE_LIMIT)
        if stream_key == NotionStream.DATA_SOURCES:
            data, next_cursor = await self._search(
                model=native.DataSource,
                object_kind=native.ObjectKind.DATA_SOURCE,
                cursor=cursor,
                limit=page_limit,
            )
            return SorRecordPage(
                records=tuple(self._external_space(row) for row in data),
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
            )
        if stream_key == NotionStream.PAGES:
            return await self._read_documents(
                cursor=cursor, limit=min(page_limit, native.DOCUMENT_PAGE_LIMIT)
            )
        if stream_key == NotionStream.AUTHORS:
            return await self._read_authors(cursor=cursor, limit=page_limit)
        if stream_key == NotionStream.PROPERTIES:
            return await self._read_properties(cursor=cursor, limit=page_limit)
        return await self._read_tree(
            stream_key=stream_key,
            cursor=cursor,
            limit=page_limit,
        )

    async def _search[T: native.PageIdentity | native.DataSource](
        self,
        *,
        model: type[T],
        object_kind: native.SearchObjectKind,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[T], str | None]:
        payload = native.SearchRequest(
            filter=native.SearchFilter(value=object_kind),
            page_size=limit,
            start_cursor=_vendor_cursor(cursor, stream="search")
            if cursor is not None
            else None,
        )
        response = await self._client.request(
            "/v1/search", method=HTTPMethod.POST, payload=payload.to_wire()
        )
        data = native.parse_response(
            native.ListResponse[native.SearchResult],
            _expect(response, operation=f"search Notion {object_kind}s"),
        )
        for row in data.results:
            if row.object != object_kind:
                raise _invalid_response(
                    "Notion search returned an unexpected object type."
                )
        return [
            native.parse_response(model, row.to_snapshot()) for row in data.results
        ], _next_cursor(data, stream="search")

    async def _read_documents(self, *, cursor: str | None, limit: int) -> SorRecordPage:
        pages, next_cursor = await self._search(
            model=native.Page,
            object_kind=native.ObjectKind.PAGE,
            cursor=cursor,
            limit=limit,
        )
        records: list[SorExternalRecord] = []
        for page in pages:
            page_id = _notion_id(page.id, field="page ID")
            markdown = await self._fetch_markdown(page_id)
            records.append(self._external_document(page, markdown))
        return SorRecordPage(
            records=tuple(records),
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )

    async def _read_authors(self, *, cursor: str | None, limit: int) -> SorRecordPage:
        query = native.ListQuery(
            page_size=limit,
            start_cursor=_vendor_cursor(cursor, stream=NotionStream.AUTHORS)
            if cursor is not None
            else None,
        )
        response = await self._client.request("/v1/users", query=query.to_wire())
        data = native.parse_response(
            native.ListResponse[native.User],
            _expect(response, operation="list Notion users"),
        )
        rows = data.results
        next_cursor = _next_cursor(data, stream=NotionStream.AUTHORS)
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
        while scans < native.EMPTY_SCAN_LIMIT:
            if checkpoint.current_page_id is None:
                page_id, page_cursor, page_is_last = await self._next_page(
                    checkpoint.page_cursor
                )
                if page_id is None:
                    return SorRecordPage(records=(), next_cursor=None, has_more=False)
                checkpoint = _MemberCursor(
                    page_cursor=page_cursor,
                    current_page_id=page_id,
                    current_page_is_last=page_is_last,
                    offset=0,
                )
            assert checkpoint.current_page_id is not None
            page = await self._fetch_page(checkpoint.current_page_id)
            properties = _page_properties(page)
            if checkpoint.offset > len(properties):
                raise _invalid_cursor(NotionStream.PROPERTIES)
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
                    page_cursor=checkpoint.page_cursor,
                    current_page_id=checkpoint.current_page_id,
                    current_page_is_last=checkpoint.current_page_is_last,
                    offset=next_offset,
                )
                return SorRecordPage(
                    records=records,
                    next_cursor=_encode_member_cursor(next_checkpoint),
                    has_more=True,
                )
            if checkpoint.current_page_is_last:
                return SorRecordPage(records=records, next_cursor=None, has_more=False)
            boundary = _MemberCursor(
                page_cursor=checkpoint.page_cursor,
                current_page_id=None,
                current_page_is_last=False,
                offset=0,
            )
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
        while scans < native.EMPTY_SCAN_LIMIT:
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
                    page_attachments_done=stream_key != NotionStream.ATTACHMENTS,
                    frames=(
                        _TreeFrame(
                            parent_id=page_id,
                            parent_external_id=None,
                            child_cursor=None,
                            offset=0,
                            depth=0,
                        ),
                    ),
                )
            current_page_id = checkpoint.current_page_id
            assert current_page_id is not None
            if (
                stream_key == NotionStream.ATTACHMENTS
                and not checkpoint.page_attachments_done
            ):
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
                        records=tuple(
                            _external_attachment(value) for value in selected
                        ),
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
                    page_cursor=checkpoint.page_cursor,
                    current_page_id=None,
                    current_page_is_last=False,
                    page_attachment_offset=0,
                    page_attachments_done=stream_key != NotionStream.ATTACHMENTS,
                    frames=(),
                )
                scans += 1
                continue
            frame = checkpoint.frames[0]
            rows, child_cursor = await self._read_block_children(frame, limit=limit)
            continuation = (
                (
                    _TreeFrame(
                        parent_id=frame.parent_id,
                        parent_external_id=frame.parent_external_id,
                        child_cursor=child_cursor,
                        offset=frame.offset + len(rows),
                        depth=frame.depth,
                    ),
                )
                if child_cursor is not None
                else ()
            )
            if frame.depth >= MAX_TREE_DEPTH and any(
                row.has_children is True for row in rows
            ):
                raise _invalid_response("Notion block hierarchy is too deep.")
            child_frames = tuple(
                _TreeFrame(
                    parent_id=_notion_id(row.id, field="block ID"),
                    parent_external_id=_notion_id(row.id, field="block ID"),
                    child_cursor=None,
                    offset=0,
                    depth=frame.depth + 1,
                )
                for row in rows
                if row.has_children is True
            )
            frames = (*child_frames, *continuation, *checkpoint.frames[1:])
            if len(frames) > MAX_TREE_FRAMES:
                raise _invalid_response("Notion block hierarchy is too broad.")
            records: tuple[SorExternalRecord, ...]
            if stream_key == NotionStream.BLOCKS:
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
                page_cursor=checkpoint.page_cursor,
                current_page_id=checkpoint.current_page_id,
                current_page_is_last=checkpoint.current_page_is_last,
                page_attachment_offset=checkpoint.page_attachment_offset,
                page_attachments_done=checkpoint.page_attachments_done,
                frames=tuple(frames),
            )
            if not frames:
                if checkpoint.current_page_is_last:
                    return SorRecordPage(
                        records=records, next_cursor=None, has_more=False
                    )
                next_checkpoint = _TreeCursor(
                    page_cursor=checkpoint.page_cursor,
                    current_page_id=None,
                    current_page_is_last=False,
                    page_attachment_offset=0,
                    page_attachments_done=stream_key != NotionStream.ATTACHMENTS,
                    frames=(),
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
            model=native.PageIdentity,
            object_kind=native.ObjectKind.PAGE,
            cursor=cursor,
            limit=1,
        )
        if len(rows) > 1 or (not rows and next_cursor is not None):
            raise _invalid_response("Notion returned an invalid page scan.")
        if not rows:
            return None, None, True
        return (
            _notion_id(rows[0].id, field="page ID"),
            next_cursor,
            next_cursor is None,
        )

    async def _read_block_children(
        self,
        frame: _TreeFrame,
        *,
        limit: int,
    ) -> tuple[list[native.Block], str | None]:
        if frame.depth > MAX_TREE_DEPTH:
            raise _invalid_response("Notion block hierarchy is too deep.")
        query = native.ListQuery(page_size=limit, start_cursor=frame.child_cursor)
        response = await self._client.request(
            f"/v1/blocks/{_path_id(frame.parent_id)}/children",
            query=query.to_wire(),
        )
        data = native.parse_response(
            native.ListResponse[native.Block],
            _expect(response, operation="list Notion block children"),
        )
        return data.results, _next_cursor(data, stream=NotionStream.BLOCKS)

    async def _fetch_page(self, page_id: str) -> native.Page:
        response = await self._client.request(f"/v1/pages/{_path_id(page_id)}")
        return native.parse_response(
            native.Page, _required_response(response, NotionStream.PAGES, page_id)
        )

    async def _fetch_markdown(self, page_id: str) -> native.Markdown:
        response = await self._client.request(
            f"/v1/pages/{_path_id(page_id)}/markdown",
            query=native.MarkdownQuery().to_wire(),
        )
        markdown = native.parse_response(
            native.Markdown,
            _expect(response, operation="retrieve Notion page Markdown"),
        )
        if _notion_id(markdown.id, field="Markdown page ID") != page_id:
            raise _invalid_response("Notion Markdown belongs to a different page.")
        _bounded_string(markdown.markdown, field="Markdown content", allow_empty=True)
        _id_tuple(markdown.unknown_block_ids, field="unknown block IDs")
        _bounded_json(markdown.to_snapshot(), field="Markdown source")
        return markdown

    async def _fetch_page_with_markdown(
        self,
        page_id: str,
    ) -> tuple[native.Page, native.Markdown]:
        page = await self._fetch_page(page_id)
        return page, await self._fetch_markdown(page_id)

    async def _root_page_id(self, block: native.Block) -> str:
        current = block
        visited: set[str] = set()
        for _depth in range(MAX_TREE_DEPTH + 1):
            parent = current.parent
            if parent is None:
                raise _invalid_response("Notion block parent is missing.")
            parent_type = _required_string(parent.type, field="block parent type")
            if parent_type == native.ParentType.PAGE:
                return _notion_id(parent.page_id, field="parent page ID")
            if parent_type != native.ParentType.BLOCK:
                raise _invalid_response("Notion block has no owning page.")
            parent_id = _notion_id(parent.block_id, field="parent block ID")
            if parent_id in visited:
                raise _invalid_response("Notion block hierarchy contains a cycle.")
            visited.add(parent_id)
            response = await self._client.request(f"/v1/blocks/{_path_id(parent_id)}")
            current = native.parse_response(
                native.Block,
                _required_response(response, NotionStream.BLOCKS, parent_id),
            )
        raise _invalid_response("Notion block hierarchy is too deep.")

    def _external_space(self, row: native.DataSource) -> SorExternalRecord:
        data_source_id = _notion_id(row.id, field="data source ID")
        properties = {key: value.to_snapshot() for key, value in row.properties.items()}
        return SorExternalRecord(
            vendor_object_key=NotionStream.DATA_SOURCES,
            external_id=data_source_id,
            payload={
                "name": _rich_text(row.title) or "Untitled data source",
                "kind": "data_source",
                "custom_fields": _bounded_json(properties, field="data source schema"),
            },
            source_created_at=_optional_datetime(row.created_time),
            source_updated_at=_optional_datetime(row.last_edited_time),
            source_revision=_optional_string(row.last_edited_time),
            source_url=_safe_url(row.url),
        )

    def _external_document(
        self,
        row: native.Page,
        markdown: native.Markdown,
    ) -> SorExternalRecord:
        page_id = _notion_id(row.id, field="page ID")
        if _notion_id(markdown.id, field="Markdown page ID") != page_id:
            raise _invalid_response("Notion Markdown belongs to a different page.")
        normalized_text = _bounded_string(
            markdown.markdown,
            field="Markdown content",
            allow_empty=True,
        )
        source_body = _bounded_json(
            {"page": row.to_snapshot(), "markdown": markdown.to_snapshot()},
            field="page source body",
        )
        parent = row.parent or native.Parent()
        parent_type = _optional_string(parent.type)
        parent_external_id = None
        space_external_id = None
        if parent_type == native.ParentType.PAGE:
            parent_external_id = _optional_notion_id(parent.page_id)
        elif parent_type == native.ParentType.DATA_SOURCE:
            space_external_id = _optional_notion_id(parent.data_source_id)
        unsupported: list[str] = []
        if markdown.truncated is True:
            unsupported.append("notion_markdown_truncated")
        if _id_tuple(markdown.unknown_block_ids, field="unknown block IDs"):
            unsupported.append("notion_unknown_block")
        created_at = _optional_datetime(row.created_time)
        updated_at = _optional_datetime(row.last_edited_time)
        revision = _page_revision(row)
        return SorExternalRecord(
            vendor_object_key=NotionStream.PAGES,
            external_id=page_id,
            payload={
                "title": _page_title(row),
                "space_external_id": space_external_id,
                "parent_external_id": parent_external_id,
                "path": [],
                "source_format": KnowledgeSourceFormat.NOTION_MARKDOWN,
                "normalized_text": normalized_text,
                "source_body": source_body,
                "content_hash": _content_hash(normalized_text, source_body),
                "version": revision,
                "lifecycle_state": "trashed" if row.in_trash is True else "active",
                "author_external_id": _user_reference(row.last_edited_by),
                "label_external_ids": list(_page_option_ids(row)),
                "unsupported_blocks": unsupported,
                "source_created_at": created_at,
                "source_updated_at": updated_at,
            },
            source_created_at=created_at,
            source_updated_at=updated_at,
            source_revision=revision,
            source_url=_safe_url(row.url),
        )

    def _external_block(
        self,
        *,
        page_id: str,
        parent_external_id: str | None,
        row: native.Block,
        order: int,
    ) -> SorExternalRecord:
        block_id = _notion_id(row.id, field="block ID")
        kind = _required_string(row.type, field="block type")
        created_at = _optional_datetime(row.created_time)
        updated_at = _optional_datetime(row.last_edited_time)
        return SorExternalRecord(
            vendor_object_key=NotionStream.BLOCKS,
            external_id=block_id,
            payload={
                "document_external_id": page_id,
                "parent_external_id": parent_external_id,
                "kind": kind,
                "order": order,
                "normalized_text": _block_text(row),
                "source_body": _bounded_json(
                    row.to_snapshot(), field="block source body"
                ),
                "supported": kind in _SUPPORTED_BLOCK_TYPES,
                "source_created_at": created_at,
                "source_updated_at": updated_at,
            },
            source_created_at=created_at,
            source_updated_at=updated_at,
            source_revision=_optional_string(row.last_edited_time),
        )

    async def _external_property(
        self,
        *,
        page_id: str,
        label: str,
        value: native.Property,
        page: native.Page,
    ) -> SorExternalRecord:
        property_id = _source_key(value.id, field="property ID")
        complete_value = await self._complete_property(page_id, value)
        updated_at = _optional_datetime(page.last_edited_time)
        return SorExternalRecord(
            vendor_object_key=NotionStream.PROPERTIES,
            external_id=_property_external_id(page_id, property_id),
            payload={
                "document_external_id": page_id,
                "key": property_id,
                "label": _bounded_string(
                    label, field="property name", allow_empty=False
                ),
                "value_type": _required_string(value.type, field="property type"),
                "value": complete_value,
                "source_updated_at": updated_at,
            },
            source_updated_at=updated_at,
            source_revision=_page_revision(page),
        )

    def _external_author(self, row: native.User) -> SorExternalRecord:
        author_id = _notion_id(row.id, field="user ID")
        person = row.person
        return SorExternalRecord(
            vendor_object_key=NotionStream.AUTHORS,
            external_id=author_id,
            payload={
                "name": _optional_string(row.name) or "Notion user",
                "primary_email": _optional_string(
                    person.email if person is not None else None
                ),
                "kind": _optional_string(row.type),
                "avatar_url": _safe_url(row.avatar_url),
            },
            source_url=_safe_url(row.avatar_url),
        )

    async def _complete_property(
        self,
        page_id: str,
        value: native.Property,
    ) -> object:
        if not _property_needs_expansion(value):
            return _bounded_json(value.to_snapshot(), field="page property")
        property_id = _source_key(value.id, field="property ID")
        items: list[dict[str, object]] = []
        cursor: str | None = None
        while True:
            query = native.ListQuery(page_size=native.PAGE_LIMIT, start_cursor=cursor)
            response = await self._client.request(
                f"/v1/pages/{_path_id(page_id)}/properties/{_property_path_id(property_id)}",
                query=query.to_wire(),
            )
            data = native.parse_response(
                native.PropertyResult,
                _expect(response, operation="retrieve a complete Notion property"),
            )
            if data.object != native.ObjectKind.LIST:
                return _bounded_json(data.to_snapshot(), field="page property")
            page_items = native.parse_response(native.PropertyItems, data.to_snapshot())
            items.extend(item.to_snapshot() for item in page_items.results)
            if len(items) > MAX_PROPERTY_ITEMS:
                raise _invalid_response("Notion property contains too many values.")
            cursor = _next_cursor(page_items, stream="property")
            if cursor is None:
                break
        return _bounded_json(
            {"summary": value.to_snapshot(), "property_items": items},
            field="page property",
        )

    async def _fetch_attachment(self, external_id: str) -> _AttachmentValue:
        kind, owner_id, property_id, index = _decode_attachment_id(external_id)
        if kind == "block":
            response = await self._client.request(f"/v1/blocks/{_path_id(owner_id)}")
            block = native.parse_response(
                native.Block,
                _required_response(response, NotionStream.ATTACHMENTS, external_id),
            )
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
                vendor_object_key=NotionStream.ATTACHMENTS,
                external_id=external_id,
            ) from error
        if value.external_id != external_id:
            raise SorExternalRecordNotFound(
                vendor_object_key=NotionStream.ATTACHMENTS,
                external_id=external_id,
            )
        return value

    async def _create_page(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command("Creating a Notion page cannot target a record.")
        if not isinstance(command.payload, KnowledgeCreateCommandPayload):
            raise _invalid_command("Notion create payload is invalid.")
        parent_page = command.payload.parent_external_id
        data_source = command.payload.space_external_id
        if (parent_page is None) == (data_source is None):
            raise _invalid_command(
                "Creating a Notion page requires exactly one parent page or data source."
            )
        title = command.payload.title
        parent: native.PageParent | native.DataSourceParent
        if isinstance(parent_page, str):
            parent_page = _notion_id(parent_page, field="parent page ID")
            parent = native.PageParent(page_id=parent_page)
            title_key = "title"
        else:
            assert isinstance(data_source, str)
            data_source = _notion_id(data_source, field="data source ID")
            parent = native.DataSourceParent(data_source_id=data_source)
            response = await self._client.request(
                f"/v1/data_sources/{_path_id(data_source)}"
            )
            schema = native.parse_response(
                native.DataSource,
                _required_response(response, NotionStream.DATA_SOURCES, data_source),
            )
            title_key = _data_source_title_key(schema)
        request = native.CreatePage(
            parent=parent,
            properties={title_key: _title_property(title)},
            markdown=command.payload.normalized_text,
        )
        try:
            response = await self._client.request(
                "/v1/pages",
                method=HTTPMethod.POST,
                payload=request.to_wire(),
                idempotency_key=command.idempotency_key,
            )
            page = native.parse_response(
                native.PageResult,
                _expect_mutation(response, operation="create Notion page"),
            )
        except SorVendorOperationError as error:
            _raise_unknown_mutation(error, "created the page")
            raise
        page_id = _notion_id(page.id, field="page ID")
        return _created_command_result(page_id, page, response)

    async def _update_page(
        self,
        page_id: str,
        current: native.Page,
        command: SorCommandRequest,
    ) -> SorJsonResponse:
        if not isinstance(command.payload, KnowledgeUpdateCommandPayload):
            raise _invalid_command("Notion update payload is invalid.")
        if (command.payload.title is None) == (command.payload.normalized_text is None):
            raise _invalid_command(
                "A Notion update changes either title or content per command."
            )
        if command.payload.title is not None:
            title_key = _page_title_key(current)
            response = await self._client.request(
                f"/v1/pages/{_path_id(page_id)}",
                method=HTTPMethod.PATCH,
                payload=native.UpdateTitle(
                    properties={title_key: _title_property(command.payload.title)}
                ).to_wire(),
                idempotency_key=command.idempotency_key,
            )
        else:
            response = await self._client.request(
                f"/v1/pages/{_path_id(page_id)}/markdown",
                method=HTTPMethod.PATCH,
                payload=native.ReplaceMarkdown(
                    replace_content=native.Replacement(
                        new_str=_replacement_text(command.payload)
                    )
                ).to_wire(),
                idempotency_key=command.idempotency_key,
            )
        value = _expect_mutation(response, operation="update Notion page")
        if command.payload.title is not None:
            native.parse_response(native.PageResult, value)
        else:
            native.parse_response(native.Markdown, value)
        return response

    async def _append_page(
        self,
        page_id: str,
        command: SorCommandRequest,
    ) -> SorJsonResponse:
        if not isinstance(command.payload, KnowledgeTextCommandPayload):
            raise _invalid_command("Notion append payload is invalid.")
        try:
            response = await self._client.request(
                f"/v1/pages/{_path_id(page_id)}/markdown",
                method=HTTPMethod.PATCH,
                payload=native.InsertMarkdown(
                    insert_content=native.Insertion(
                        content=command.payload.normalized_text
                    )
                ).to_wire(),
                idempotency_key=command.idempotency_key,
            )
            native.parse_response(
                native.Markdown,
                _expect_mutation(response, operation="append to Notion page"),
            )
        except SorVendorOperationError as error:
            _raise_unknown_mutation(error, "appended the page content")
            raise
        return response

    async def _comment_page(
        self,
        page_id: str,
        command: SorCommandRequest,
    ) -> SorJsonResponse:
        if not isinstance(command.payload, KnowledgeTextCommandPayload):
            raise _invalid_command("Notion comment payload is invalid.")
        text = command.payload.normalized_text
        if len(text) > MAX_COMMENT_CHARS:
            raise _invalid_command("Notion comment text is invalid.")
        try:
            response = await self._client.request(
                "/v1/comments",
                method=HTTPMethod.POST,
                payload=native.CreateComment(
                    parent=native.CommentParent(page_id=page_id), markdown=text
                ).to_wire(),
                idempotency_key=command.idempotency_key,
            )
            native.parse_response(
                native.CommentResult,
                _expect_mutation(response, operation="comment on Notion page"),
            )
        except SorVendorOperationError as error:
            _raise_unknown_mutation(error, "created the comment")
            raise
        return response


def create_notion_adapter(context: SorAdapterContext) -> NotionKnowledgeAdapter:
    """Construct the production Notion adapter for the explicit registry."""
    return NotionKnowledgeAdapter(context)


def _replacement_text(payload: KnowledgeUpdateCommandPayload) -> str:
    if payload.normalized_text is None:
        raise _invalid_command("Notion replacement content is missing.")
    return payload.normalized_text


def _page_properties(page: native.Page) -> tuple[tuple[str, native.Property], ...]:
    for value in page.properties.values():
        _source_key(value.id, field="property ID")
    return tuple(
        sorted(page.properties.items(), key=lambda item: (item[1].id, item[0]))
    )


def _find_page_property(
    page: native.Page, property_id: str
) -> tuple[str, native.Property]:
    matches = [
        (label, value)
        for label, value in _page_properties(page)
        if value.id == property_id
    ]
    if len(matches) != 1:
        raise SorExternalRecordNotFound(
            vendor_object_key=NotionStream.PROPERTIES,
            external_id=_property_external_id(
                _notion_id(page.id, field="page ID"), property_id
            ),
        )
    return matches[0]


def _page_title(page: native.Page) -> str:
    _key, value = _page_title_property(page)
    return _rich_text(value.title) or "Untitled"


def _page_title_key(page: native.Page) -> str:
    return _page_title_property(page)[0]


def _page_title_property(page: native.Page) -> tuple[str, native.Property]:
    matches = [
        (label, value)
        for label, value in _page_properties(page)
        if value.type == native.PropertyType.TITLE
    ]
    if len(matches) != 1:
        raise _invalid_response("Notion page has no unique title property.")
    return matches[0]


def _data_source_title_key(data_source: native.DataSource) -> str:
    matches = [
        label
        for label, value in data_source.properties.items()
        if value.type == native.PropertyType.TITLE
    ]
    if len(matches) != 1:
        raise _invalid_response("Notion data source has no unique title property.")
    return matches[0]


def _title_property(value: object) -> native.WriteTitle:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TITLE_CHARS:
        raise _invalid_command("Notion title is invalid.")
    return native.WriteTitle(
        title=[native.WriteRichText(text=native.WriteText(content=value.strip()))]
    )


def _page_revision(page: native.Page) -> str:
    value = _required_string(page.last_edited_time, field="page revision")
    if _optional_datetime(value) is None:
        raise _invalid_response("Notion page revision is invalid.")
    return value


def _page_option_ids(page: native.Page) -> tuple[str, ...]:
    values: list[str] = []
    for _label, prop in _page_properties(page):
        if prop.type in {native.PropertyType.SELECT, native.PropertyType.STATUS}:
            option = (
                prop.select if prop.type == native.PropertyType.SELECT else prop.status
            )
            if (
                option is not None
                and (option_id := _optional_string(option.id)) is not None
            ):
                values.append(option_id)
        elif prop.type == native.PropertyType.MULTI_SELECT:
            values.extend(
                option_id
                for option in prop.multi_select or []
                if (option_id := _optional_string(option.id)) is not None
            )
    return tuple(dict.fromkeys(values))


def _property_needs_expansion(value: native.Property) -> bool:
    if value.type == native.PropertyType.RELATION:
        return value.has_more is True
    if value.type == native.PropertyType.ROLLUP:
        return value.rollup is not None and (
            value.has_more is True or value.rollup.type == native.RollupType.ARRAY
        )
    return False


def _page_attachments(page: native.Page) -> tuple[_AttachmentValue, ...]:
    page_id = _notion_id(page.id, field="page ID")
    created_at = _optional_datetime(page.created_time)
    updated_at = _optional_datetime(page.last_edited_time)
    values: list[_AttachmentValue] = []
    for _label, prop in _page_properties(page):
        if prop.type != native.PropertyType.FILES:
            continue
        property_id = _source_key(prop.id, field="property ID")
        if prop.files is None:
            raise _invalid_response("Notion file property is invalid.")
        for index, item in enumerate(prop.files):
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
    *, page_id: str, row: native.Block
) -> tuple[_AttachmentValue, ...]:
    kind = row.type
    if kind not in _FILE_BLOCK_TYPES:
        return ()
    block_id = _notion_id(row.id, field="block ID")
    item = row.content()
    caption = _rich_text(item.caption)
    return (
        _attachment_value(
            external_id=_block_attachment_id(block_id, 0),
            document_external_id=page_id,
            item=item,
            fallback_name=caption or f"Notion {kind}",
            created_at=_optional_datetime(row.created_time),
            updated_at=_optional_datetime(row.last_edited_time),
        ),
    )


def _attachment_value(
    *,
    external_id: str,
    document_external_id: str,
    item: native.File,
    fallback_name: str,
    created_at: datetime | None,
    updated_at: datetime | None,
) -> _AttachmentValue:
    name = _optional_string(item.name) or fallback_name
    file_data = item.location()
    source_url = _safe_url(file_data.url) if file_data is not None else None
    expiry = (
        _optional_datetime(file_data.expiry_time) if file_data is not None else None
    )
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
        vendor_object_key=NotionStream.ATTACHMENTS,
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


def _block_text(row: native.Block) -> str | None:
    value = row.content()
    parts: list[str] = []
    for rich_text in (value.rich_text, value.caption):
        if text := _rich_text(rich_text):
            parts.append(text)
    for value_text in (value.title, value.expression, value.url):
        if text := _optional_string(value_text):
            parts.append(text)
    for cell in value.cells or []:
        if text := _rich_text(cell):
            parts.append(text)
    text = "\n".join(parts)
    if len(text) > MAX_CANONICAL_TEXT_CHARS:
        raise _invalid_response("Notion block content is too large.")
    return text or None


def _rich_text(value: list[native.RichText] | None) -> str:
    parts: list[str] = []
    for item in value or []:
        if item.plain_text is not None:
            parts.append(item.plain_text)
            continue
        nested = None
        if item.type == native.RichTextType.TEXT:
            nested = item.text
        elif item.type == native.RichTextType.EQUATION:
            nested = item.equation
        if nested is not None:
            content = nested.content or nested.expression
            if content is not None:
                parts.append(content)
    text = "".join(parts)
    if len(text) > MAX_CANONICAL_TEXT_CHARS:
        raise _invalid_response("Notion rich text is too large.")
    return text


def _content_hash(normalized_text: str, source_body: object) -> str:
    source_value = (
        source_body.to_wire()
        if isinstance(source_body, KnowledgeSourceBody)
        else source_body
    )
    encoded = json.dumps(
        {"normalized_text": normalized_text, "source_body": source_value},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _created_command_result(
    page_id: str,
    page: native.PageResult,
    response: SorJsonResponse,
) -> SorCommandResult:
    request_ids = response.header_values("x-request-id")
    return SorCommandResult(
        vendor_object_key=NotionStream.PAGES,
        external_id=page_id,
        external_request_id=request_ids[0] if request_ids else None,
        source_revision=_optional_string(page.last_edited_time),
        source_url=_safe_url(page.url),
        response={"status": "accepted"},
    )


def _target_command_result(
    page_id: str,
    current: native.Page,
    response: SorJsonResponse,
) -> SorCommandResult:
    request_ids = response.header_values("x-request-id")
    return SorCommandResult(
        vendor_object_key=NotionStream.PAGES,
        external_id=page_id,
        external_request_id=request_ids[0] if request_ids else None,
        source_url=_safe_url(current.url),
        response={"status": "accepted"},
    )


def _raise_unknown_mutation(error: SorVendorOperationError, action: str) -> None:
    if error.code in {
        SorVendorErrorCode.VENDOR_TIMEOUT,
        SorVendorErrorCode.VENDOR_TRANSPORT_FAILED,
        SorVendorErrorCode.VENDOR_SERVER_FAILED,
    }:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_MUTATION_OUTCOME_UNKNOWN,
            f"Notion may have {action}; reconcile before retrying.",
            recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
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
    if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
        raise SorExternalRecordNotFound(
            vendor_object_key=stream_key,
            external_id=external_id,
        )
    return _object(_expect(response, operation="read Notion record"))


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_AUTHORIZATION_FAILED,
            f"Notion refused authorization while attempting to {operation}.",
            recovery=(
                SorRecoveryPolicy.REFRESH_AND_RETRY
                if response.status_code == HTTPStatus.UNAUTHORIZED
                else SorRecoveryPolicy.REAUTH_REQUIRED
            ),
        )
    if response.status_code == HTTPStatus.CONFLICT:
        raise _invalid_operation(
            SorVendorErrorCode.VENDOR_SOURCE_CONFLICT,
            "The Notion source changed during the operation.",
        )
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RATE_LIMITED,
            "Notion rate limited the operation.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SERVER_FAILED,
            "Notion could not complete the operation.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if not response.ok:
        raise _invalid_operation(
            SorVendorErrorCode.VENDOR_REQUEST_REJECTED,
            f"Notion rejected the request while attempting to {operation}.",
        )
    return response.data


def _expect_mutation(response: SorJsonResponse, *, operation: str) -> object:
    value = _expect(response, operation=operation)
    if response.status_code not in {HTTPStatus.OK, HTTPStatus.CREATED}:
        raise _invalid_response("Notion returned an unexpected mutation status.")
    return value


def _next_cursor(data: native.Pagination, *, stream: str) -> str | None:
    has_more = data.has_more
    next_cursor = data.next_cursor
    if not has_more:
        if next_cursor is not None:
            raise _invalid_response("Notion pagination is inconsistent.")
        return None
    if (
        not isinstance(next_cursor, str)
        or not next_cursor
        or len(next_cursor) > native.CURSOR_LENGTH_LIMIT
    ):
        raise _invalid_cursor(stream)
    return next_cursor


def _vendor_cursor(value: str, *, stream: str) -> str:
    if not value or len(value) > native.CURSOR_LENGTH_LIMIT:
        raise _invalid_cursor(stream)
    return value


def _decode_member_cursor(value: str | None) -> _MemberCursor:
    if value is None:
        return _MemberCursor(
            page_cursor=None, current_page_id=None, current_page_is_last=False, offset=0
        )
    return _decode_cursor(_MemberCursorEnvelope, value, stream=NotionStream.PROPERTIES)


def _encode_member_cursor(cursor: _MemberCursor) -> str:
    payload = _MemberCursorEnvelope(
        v=NOTION_CURSOR_VERSION,
        stream=NotionStream.PROPERTIES,
        page_cursor=cursor.page_cursor,
        current_page_id=cursor.current_page_id,
        current_page_is_last=cursor.current_page_is_last,
        offset=cursor.offset,
    )
    return _encode_cursor(payload)


def _decode_tree_cursor(value: str | None, *, stream_key: str) -> _TreeCursor:
    if value is None:
        return _TreeCursor(
            page_cursor=None,
            current_page_id=None,
            current_page_is_last=False,
            page_attachment_offset=0,
            page_attachments_done=stream_key != NotionStream.ATTACHMENTS,
            frames=(),
        )
    return _decode_cursor(_TreeCursorEnvelope, value, stream=stream_key)


def _encode_tree_cursor(cursor: _TreeCursor, *, stream_key: str) -> str:
    if stream_key not in {NotionStream.BLOCKS, NotionStream.ATTACHMENTS}:
        raise _invalid_cursor(stream_key)
    stream = (
        NotionStream.BLOCKS
        if stream_key == NotionStream.BLOCKS
        else NotionStream.ATTACHMENTS
    )
    payload = _TreeCursorEnvelope(
        v=NOTION_CURSOR_VERSION,
        stream=stream,
        page_cursor=cursor.page_cursor,
        current_page_id=cursor.current_page_id,
        current_page_is_last=cursor.current_page_is_last,
        page_attachment_offset=cursor.page_attachment_offset,
        page_attachments_done=cursor.page_attachments_done,
        frames=cursor.frames,
    )
    return _encode_cursor(payload)


def _decode_cursor[T: _MemberCursorEnvelope | _TreeCursorEnvelope](
    model: type[T],
    value: str,
    *,
    stream: str,
) -> T:
    if not value or len(value) > MAX_CANONICAL_BODY_BYTES:
        raise _invalid_cursor(stream)
    try:
        cursor = model.model_validate_json(value)
    except (ValidationError, SorVendorOperationError) as error:
        raise _invalid_cursor(stream) from error
    if cursor.stream != stream:
        raise _invalid_cursor(stream)
    return cursor


def _encode_cursor(payload: _MemberCursorEnvelope | _TreeCursorEnvelope) -> str:
    value = json.dumps(
        payload.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
    )
    if len(value.encode()) > MAX_CANONICAL_BODY_BYTES:
        raise _invalid_response(f"Notion {payload.stream} cursor is too large.")
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
            SorVendorErrorCode.VENDOR_IDENTIFIER_INVALID,
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
            return (
                "block",
                _notion_id(parts[1], field="attachment block ID"),
                None,
                _index(parts[2]),
            )
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
            SorVendorErrorCode.VENDOR_IDENTIFIER_INVALID,
            "A Notion attachment identity is invalid.",
        ) from error
    raise _invalid_operation(
        SorVendorErrorCode.VENDOR_IDENTIFIER_INVALID,
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


def _block_parent_id(block: native.Block) -> str | None:
    parent = block.parent
    return (
        _optional_notion_id(parent.block_id)
        if parent is not None and parent.type == native.ParentType.BLOCK
        else None
    )


def _user_reference(value: native.Reference | None) -> str | None:
    return _optional_notion_id(value.id) if value is not None else None


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


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid_operation(
            SorVendorErrorCode.VENDOR_CREDENTIALS_INVALID,
            "Notion credentials are unavailable.",
        )
    return value


def _require_stream(value: str, *, selected: tuple[str, ...]) -> NotionStream:
    if value not in _STREAM_ENTITY or value not in selected:
        raise _invalid_operation(
            SorVendorErrorCode.VENDOR_STREAM_UNSUPPORTED,
            "The requested Notion stream is not selected for this source.",
        )
    return NotionStream(value)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    values = [
        value.strip() for key, value in headers.items() if key.casefold() == expected
    ]
    if len(values) != 1 or not values[0] or len(values[0]) > 4_096:
        return None
    return values[0]


def _invalid_cursor(stream: str) -> SorVendorOperationError:
    return _invalid_operation(
        SorVendorErrorCode.VENDOR_CURSOR_INVALID,
        f"The Notion {stream} cursor is invalid.",
    )


def _invalid_command(message: str) -> SorVendorOperationError:
    return _invalid_operation(SorVendorErrorCode.VENDOR_COMMAND_INVALID, message)


def _invalid_response(message: str) -> SorVendorOperationError:
    return _invalid_operation(SorVendorErrorCode.VENDOR_RESPONSE_INVALID, message)


def _invalid_operation(
    code: SorVendorErrorCode,
    message: str,
) -> SorVendorOperationError:
    return SorVendorOperationError(code, message, recovery=SorRecoveryPolicy.TERMINAL)


__all__ = [
    "NOTION_MANIFEST",
    "NotionAppWebhookDelivery",
    "NotionKnowledgeAdapter",
    "create_notion_adapter",
    "notion_verification_token",
    "parse_notion_app_webhook",
    "verify_notion_app_webhook",
]
