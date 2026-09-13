"""Consumed Confluence v2 wire contracts, separate from canonical documents."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
)

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)
from eylo.sor.shared.json_values import SorJsonValue

MAX_TEXT_CHARS = 1_000_000
MAX_CURSOR_CHARS = 4_096
MAX_PAGE_SIZE = 100


def identifier(value: object) -> str:
    """Retain integer IDs and account-ID colons, never URL delimiters."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise ValueError("Invalid Confluence identifier type.")
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._~:-]{1,512}", normalized):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_IDENTIFIER_INVALID,
            "A Confluence source identifier is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return normalized


def optional_identifier(value: object) -> str | None:
    return None if value is None or value == "" else identifier(value)


def optional_text(value: object) -> str | None:
    """Preserve the existing optional-text normalization without coercion."""
    return value if isinstance(value, str) and value else None


def optional_datetime(value: object) -> datetime | None:
    """Unavailable/malformed optional timestamps do not invent a source date."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


ConfluenceId = Annotated[str, BeforeValidator(identifier)]
OptionalId = Annotated[str | None, BeforeValidator(optional_identifier)]
OptionalText = Annotated[str | None, BeforeValidator(optional_text)]
OptionalDate = Annotated[datetime | None, BeforeValidator(optional_datetime)]
NonnegativeInteger = Annotated[int, Field(ge=0)]
RequiredText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS)]


class ConfluenceResponse(BaseModel):
    """Validate consumed fields while tolerating unrelated vendor additions."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )


class ConfluenceLinks(ConfluenceResponse):
    next: OptionalText = None
    webui: OptionalText = None
    download: OptionalText = Field(default=None, repr=False)


class ConfluenceErrorResponse(ConfluenceResponse):
    """Consumed error envelope used for Atlassian scope-mismatch recovery."""

    message: OptionalText = None


class ConfluenceCollection[T: ConfluenceResponse](ConfluenceResponse):
    results: list[T]
    links: ConfluenceLinks = Field(default_factory=ConfluenceLinks, alias="_links")


class ConfluenceSite(ConfluenceResponse):
    id: OptionalId = None
    url: OptionalText = None
    name: OptionalText = None
    scopes: list[str] = Field(default_factory=list)


class ConfluenceSites(RootModel[list[ConfluenceSite]]):
    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)


class ConfluenceVersion(ConfluenceResponse):
    number: NonnegativeInteger | None = None
    createdAt: OptionalDate = None
    authorId: OptionalId = None
    message: OptionalText = None


class ConfluencePageIdentity(ConfluenceResponse):
    id: ConfluenceId
    version: ConfluenceVersion = Field(default_factory=ConfluenceVersion)
    authorId: OptionalId = None
    links: ConfluenceLinks = Field(default_factory=ConfluenceLinks, alias="_links")


class ConfluenceStorage(ConfluenceResponse):
    value: str = Field(repr=False)


class ConfluenceBody(ConfluenceResponse):
    storage: ConfluenceStorage


class ConfluencePage(ConfluencePageIdentity):
    title: RequiredText
    spaceId: OptionalId = None
    parentId: OptionalId = None
    parentType: OptionalText = None
    status: OptionalText = None
    createdAt: OptionalDate = None
    body: ConfluenceBody = Field(repr=False)


class ConfluenceSpace(ConfluenceResponse):
    id: ConfluenceId
    name: RequiredText
    type: OptionalText = None
    links: ConfluenceLinks = Field(default_factory=ConfluenceLinks, alias="_links")


class ConfluenceProfilePicture(ConfluenceResponse):
    path: OptionalText = None


class ConfluenceUser(ConfluenceResponse):
    accountId: ConfluenceId
    displayName: OptionalText = None
    publicName: OptionalText = None
    email: OptionalText = Field(default=None, repr=False)
    accountType: OptionalText = None
    profilePicture: ConfluenceProfilePicture = Field(
        default_factory=ConfluenceProfilePicture
    )


class ConfluenceProperty(ConfluenceResponse):
    id: ConfluenceId
    key: RequiredText
    value: SorJsonValue = Field(default=None, repr=False)
    version: ConfluenceVersion = Field(default_factory=ConfluenceVersion)


class ConfluenceAttachment(ConfluenceResponse):
    id: ConfluenceId
    title: RequiredText
    pageId: OptionalId = None
    mediaType: OptionalText = None
    fileSize: NonnegativeInteger | None = None
    createdAt: OptionalDate = None
    downloadLink: OptionalText = Field(default=None, repr=False)
    version: ConfluenceVersion = Field(default_factory=ConfluenceVersion)
    links: ConfluenceLinks = Field(default_factory=ConfluenceLinks, alias="_links")


class ConfluenceParentType(StrEnum):
    PAGE = "page"


class ConfluenceStatus(StrEnum):
    CURRENT = "current"


class ConfluenceBodyFormat(StrEnum):
    STORAGE = "storage"


class ConfluenceRequest(BaseModel):
    """Outbound construction rejects misspelled keys before vendor I/O."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        populate_by_name=True,
    )


class ConfluenceReadQuery(ConfluenceRequest):
    limit: int | None = Field(default=None, gt=0, le=MAX_PAGE_SIZE)
    cursor: str | None = Field(default=None, min_length=1, max_length=MAX_CURSOR_CHARS)
    body_format: ConfluenceBodyFormat | None = Field(
        default=None, serialization_alias="body-format"
    )
    status: ConfluenceStatus | None = None


class ConfluenceUsersQuery(ConfluenceRequest):
    accountIds: list[ConfluenceId]


class ConfluenceWriteBody(ConfluenceRequest):
    representation: ConfluenceBodyFormat = ConfluenceBodyFormat.STORAGE
    value: str = Field(repr=False)


class ConfluenceCreatePage(ConfluenceRequest):
    spaceId: ConfluenceId
    status: ConfluenceStatus = ConfluenceStatus.CURRENT
    title: RequiredText
    body: ConfluenceWriteBody = Field(repr=False)
    parentId: ConfluenceId | None = None


class ConfluenceWriteVersion(ConfluenceRequest):
    number: NonnegativeInteger


class ConfluenceUpdatePage(ConfluenceRequest):
    id: ConfluenceId
    status: ConfluenceStatus = ConfluenceStatus.CURRENT
    title: RequiredText
    body: ConfluenceWriteBody = Field(repr=False)
    version: ConfluenceWriteVersion


def parse_response[T: BaseModel](model: type[T], value: object) -> T:
    """Expose a typed terminal vendor failure without leaking response content."""
    try:
        return model.model_validate(value)
    except ValidationError:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Confluence returned an invalid response.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from None
