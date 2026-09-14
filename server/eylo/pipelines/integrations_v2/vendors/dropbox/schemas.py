"""Dropbox API v2 tagged wire contracts and agent-facing metadata projections."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ...contracts import VendorResponse, VendorToolError

MAX_RESULTS = 100
DEFAULT_FOLDER_RESULTS = 50
DEFAULT_SEARCH_RESULTS = 25
MAX_QUERY_LENGTH = 1000
FILE_ID_PREFIX = "id:"
NAMESPACE_PREFIX = "ns:"


class DropboxErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    PATH_INVALID = "path_invalid"
    LINK_LOOKUP_INCOMPLETE = "share_link_lookup_incomplete"


class EntryKind(StrEnum):
    FILE = "file"
    FOLDER = "folder"
    DELETED = "deleted"


class MetadataKind(StrEnum):
    METADATA = "metadata"


class ResolvedVisibility(StrEnum):
    PUBLIC = "public"
    TEAM_ONLY = "team_only"
    PASSWORD = "password"
    TEAM_AND_PASSWORD = "team_and_password"
    SHARED_FOLDER_ONLY = "shared_folder_only"
    NO_ONE = "no_one"
    ONLY_YOU = "only_you"
    OTHER = "other"


class LinkAudience(StrEnum):
    PUBLIC = "public"
    TEAM = "team"
    NO_ONE = "no_one"
    PASSWORD = "password"
    MEMBERS = "members"
    OTHER = "other"


class LinkAccess(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    OTHER = "other"


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("Dropbox timestamps require a timezone.")
    return value


def https_link(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Dropbox share links must be HTTPS URLs without credentials.")
    return value


Identifier = Annotated[str, Field(min_length=1)]
TimestampText = Annotated[str, AfterValidator(timestamp)]
Revision = Annotated[str, Field(pattern=r"^[0-9a-f]{9,}$")]


class DropboxModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )


class DropboxRequest(DropboxModel):
    model_config = ConfigDict(extra="forbid")


class DropboxMetadata(DropboxModel):
    name: str
    path_lower: str | None = None
    path_display: str | None = None


class DropboxFolder(DropboxMetadata):
    id: Identifier
    tag: Literal[EntryKind.FOLDER] = Field(default=EntryKind.FOLDER, alias=".tag")


class TaggedFolder(DropboxFolder):
    tag: Literal[EntryKind.FOLDER] = Field(alias=".tag")


class DropboxFile(DropboxMetadata):
    tag: Literal[EntryKind.FILE] = Field(alias=".tag")
    id: Identifier
    size: int = Field(ge=0)
    server_modified: TimestampText
    rev: Revision


class DeletedMetadata(DropboxMetadata):
    tag: Literal[EntryKind.DELETED] = Field(alias=".tag")


Metadata = Annotated[
    DropboxFile | TaggedFolder | DeletedMetadata, Field(discriminator="tag")
]


class FolderPage(DropboxModel):
    entries: list[Metadata]
    cursor: Identifier
    has_more: bool


class SearchMetadata(DropboxModel):
    tag: Literal[MetadataKind.METADATA] = Field(alias=".tag")
    metadata: Metadata


class SearchMatch(DropboxModel):
    metadata: SearchMetadata


class SearchPage(DropboxModel):
    matches: list[SearchMatch]
    has_more: bool
    cursor: Identifier | None = None

    @model_validator(mode="after")
    def require_continuation(self) -> "SearchPage":
        if self.has_more and self.cursor is None:
            raise ValueError("More search results require a cursor.")
        return self


class FolderCreated(DropboxModel):
    # The create-folder endpoint returns FolderMetadata, not the tagged union.
    metadata: DropboxFolder


class MetadataResult(DropboxModel):
    metadata: Metadata


class FolderQuery(DropboxRequest):
    path: str
    recursive: bool
    limit: int = Field(ge=1, le=MAX_RESULTS)


class CursorQuery(DropboxRequest):
    cursor: Identifier


class SearchOptions(DropboxRequest):
    path: str
    max_results: int = Field(ge=1, le=MAX_RESULTS)
    filename_only: Literal[True] = True
    file_extensions: list[Identifier] | None = None


class SearchQuery(DropboxRequest):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH, repr=False)
    options: SearchOptions


class PathRequest(DropboxRequest):
    path: Identifier


class FolderCreate(PathRequest):
    autorename: Literal[True] = True


class MoveRequest(DropboxRequest):
    from_path: Identifier
    to_path: Identifier
    autorename: Literal[True] = True


class DirectLinksQuery(PathRequest):
    direct_only: Literal[True] = True


class VisibilityTag(DropboxModel):
    tag: Annotated[
        ResolvedVisibility,
        BeforeValidator(lambda v: ResolvedVisibility(v) if isinstance(v, str) else v),
    ] = Field(alias=".tag")


class AudienceTag(DropboxModel):
    tag: Annotated[
        LinkAudience,
        BeforeValidator(lambda v: LinkAudience(v) if isinstance(v, str) else v),
    ] = Field(alias=".tag")


class AccessTag(DropboxModel):
    tag: Annotated[
        LinkAccess,
        BeforeValidator(lambda v: LinkAccess(v) if isinstance(v, str) else v),
    ] = Field(alias=".tag")


class LinkPermissions(DropboxModel):
    can_revoke: bool
    resolved_visibility: VisibilityTag | None = None
    effective_audience: AudienceTag | None = None
    link_access_level: AccessTag | None = None


class SharedLink(DropboxModel):
    tag: Literal[EntryKind.FILE, EntryKind.FOLDER] = Field(alias=".tag")
    url: Annotated[str, AfterValidator(https_link)] = Field(repr=False)
    name: str
    id: Identifier | None = None
    path_lower: str | None = None
    link_permissions: LinkPermissions


class SharedLinksPage(DropboxModel):
    links: list[SharedLink]
    has_more: bool
    cursor: Identifier | None = None


class DropboxErrorEnvelope(DropboxModel):
    error_summary: str | None = Field(default=None, repr=False)


class EntryView(DropboxModel):
    name: str
    path: str | None
    id: str | None
    is_folder: bool
    size_bytes: int | None
    modified_at: str | None
    revision: str | None
    kind: EntryKind


class FolderView(DropboxModel):
    path: str
    entries: list[EntryView]
    count: int
    more_available: bool
    next_cursor: str | None


class SearchView(DropboxModel):
    results: list[EntryView]
    count: int
    query: str = Field(repr=False)
    more_available: bool
    next_cursor: str | None


class MovedView(EntryView):
    moved_from: str


class DeletedView(EntryView):
    deleted: Literal[True] = True
    recoverable_for_days: None = None


class ShareView(DropboxModel):
    path: str
    url: str = Field(repr=False)
    name: str
    visibility: ResolvedVisibility | None
    audience: LinkAudience | None
    access: LinkAccess | None


FOLDER_RESPONSE = TypeAdapter(FolderPage)
SEARCH_RESPONSE = TypeAdapter(SearchPage)
CREATED_RESPONSE = TypeAdapter(FolderCreated)
METADATA_RESPONSE = TypeAdapter(MetadataResult)
LINKS_RESPONSE = TypeAdapter(SharedLinksPage)
LINK_RESPONSE = TypeAdapter(SharedLink)


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            DropboxErrorCode.REJECTED, "Dropbox rejected the request."
        )
    try:
        if DropboxErrorEnvelope.model_validate(response.data).error_summary:
            raise VendorToolError(
                DropboxErrorCode.REJECTED, "Dropbox rejected the request."
            )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            DropboxErrorCode.RESPONSE_INVALID,
            "Dropbox returned an invalid operation response.",
        ) from None


def entry_view(entry: DropboxFolder | Metadata) -> EntryView:
    return EntryView(
        name=entry.name,
        path=entry.path_display or entry.path_lower,
        id=None if isinstance(entry, DeletedMetadata) else entry.id,
        is_folder=isinstance(entry, DropboxFolder),
        size_bytes=entry.size if isinstance(entry, DropboxFile) else None,
        modified_at=entry.server_modified if isinstance(entry, DropboxFile) else None,
        revision=entry.rev if isinstance(entry, DropboxFile) else None,
        kind=EntryKind.FOLDER if isinstance(entry, DropboxFolder) else entry.tag,
    )


def normalize_path(value: str) -> str:
    """Keep native ID/namespace addressing intact; only root maps to empty text."""
    candidate = value.strip()
    if candidate in {"", "/"}:
        return ""
    if candidate.startswith((FILE_ID_PREFIX, NAMESPACE_PREFIX)):
        if candidate in {FILE_ID_PREFIX, NAMESPACE_PREFIX}:
            raise VendorToolError(
                DropboxErrorCode.PATH_INVALID, "A Dropbox identifier cannot be empty."
            )
        return candidate
    return f"/{candidate.lstrip('/')}".rstrip("/")


def mutation_path(value: str) -> str:
    path = normalize_path(value)
    if not path:
        raise VendorToolError(
            DropboxErrorCode.PATH_INVALID, "Choose a file or folder, not the root."
        )
    return path


def destination_path(value: str) -> str:
    path = mutation_path(value)
    if path.startswith(FILE_ID_PREFIX):
        raise VendorToolError(
            DropboxErrorCode.PATH_INVALID, "A destination requires a path, not an id."
        )
    return path
