"""Linear Knowledge query projections; native fields never become core SOR types."""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

MAX_DOCUMENT_CHARS = 1_000_000
MAX_PAGE_RECORDS = 200
_MAX_IDENTIFIER_CHARS = 500


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _validate_timestamp(value: str) -> str:
    _timestamp(value)
    return value


LinearIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=_MAX_IDENTIFIER_CHARS
    ),
]
# Retain the vendor's timestamp spelling in source payloads/hashes. Convert only
# for cursor comparisons and canonical metadata, including the existing UTC
# interpretation of offset-free timestamps.
LinearTimestamp = Annotated[str, AfterValidator(_validate_timestamp)]


class LinearNativeModel(BaseModel):
    """Validate consumed vendor fields and tolerate additional GraphQL selections."""

    model_config = ConfigDict(
        extra="ignore", strict=True, frozen=True, hide_input_in_errors=True
    )


class LinearReference(LinearNativeModel):
    """Identity-only selection for a related native entity."""

    id: LinearIdentifier


class LinearNamedReference(LinearReference):
    """Selected label for a document's project, initiative or release."""

    name: str


class LinearIssueReference(LinearReference):
    """Selected issue identity and human-readable label."""

    identifier: str
    title: str


class LinearRecord(LinearReference):
    """Native record metadata shared only within the Linear Knowledge adapter."""

    created_at: LinearTimestamp = Field(alias="createdAt")
    updated_at: LinearTimestamp = Field(alias="updatedAt")
    archived_at: LinearTimestamp | None = Field(default=None, alias="archivedAt")
    url: str

    @property
    def created_datetime(self) -> datetime:
        return _timestamp(self.created_at)

    @property
    def updated_datetime(self) -> datetime:
        return _timestamp(self.updated_at)

    @property
    def archived_datetime(self) -> datetime | None:
        return _timestamp(self.archived_at) if self.archived_at is not None else None


class LinearDocument(LinearRecord):
    """Document fields selected by the document, pagination and image queries."""

    title: str
    content: str | None = Field(default=None, max_length=MAX_DOCUMENT_CHARS, repr=False)
    document_content_id: str | None = Field(default=None, alias="documentContentId")
    slug_id: str = Field(alias="slugId")
    icon: str | None = None
    color: str | None = None
    hidden_at: LinearTimestamp | None = Field(default=None, alias="hiddenAt")
    trashed: bool | None = None
    creator: LinearReference | None = None
    owner: LinearReference | None = None
    updated_by: LinearReference | None = Field(default=None, alias="updatedBy")
    initiative: LinearNamedReference | None = None
    issue: LinearIssueReference | None = None
    project: LinearNamedReference | None = None
    release: LinearNamedReference | None = None


class LinearUser(LinearRecord):
    """User selection for Knowledge authors, not a platform contact or member."""

    name: str
    display_name: str = Field(alias="displayName")
    email: str = Field(repr=False)
    active: bool
    avatar_url: str | None = Field(default=None, alias="avatarUrl")


class LinearPageInfo(LinearNativeModel):
    """A partial forward page must supply a usable continuation cursor."""

    has_next_page: bool = Field(alias="hasNextPage")
    end_cursor: str | None = Field(default=None, alias="endCursor")

    @model_validator(mode="after")
    def require_continuation(self) -> "LinearPageInfo":
        if self.has_next_page and not (self.end_cursor or "").strip():
            raise ValueError("A partial Linear page requires an end cursor.")
        return self


class LinearConnection[RecordT: LinearRecord](LinearNativeModel):
    """Validate every node before projecting any record from a vendor page."""

    nodes: list[RecordT] = Field(repr=False)
    page_info: LinearPageInfo = Field(alias="pageInfo")


class LinearDocumentResult(LinearNativeModel):
    """A missing document field is invalid; an explicit null means not found."""

    document: LinearDocument | None


class LinearUserResult(LinearNativeModel):
    """A missing user field is invalid; an explicit null means not found."""

    user: LinearUser | None


class LinearDocumentsResult(LinearNativeModel):
    """Document connection selected by the sync query."""

    documents: LinearConnection[LinearDocument]


class LinearUsersResult(LinearNativeModel):
    """User connection selected by the author sync query."""

    users: LinearConnection[LinearUser]


class LinearWorkspaceResult(LinearNativeModel):
    """Organization identity consumed by the connection verification query."""

    organization: LinearNamedReference


class LinearRecordVariables(LinearNativeModel):
    """Identity variable for a selected document or user query."""

    id: LinearIdentifier


class LinearDateComparator(LinearNativeModel):
    """Only the lower-bound date comparison used by incremental sync."""

    gte: LinearTimestamp


class LinearUpdatedFilter(LinearNativeModel):
    """Vendor filter for the existing updated-at reconciliation window."""

    updated_at: LinearDateComparator = Field(alias="updatedAt")


class LinearPageVariables(LinearNativeModel):
    """Bounded forward-page request, independent of the platform cursor format."""

    first: int = Field(ge=1, le=MAX_PAGE_RECORDS)
    after: str | None
    filter: LinearUpdatedFilter | None
