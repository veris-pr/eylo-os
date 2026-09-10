"""Google Drive v3 selected wire fields and curated tool projections."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from ...contracts import VendorResponse, VendorToolError

FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_FIELDS = (
    "id,name,mimeType,modifiedTime,createdTime,size,webViewLink,parents,"
    "owners(emailAddress,displayName),trashed"
)
LIST_FIELDS = f"kind,files({FILE_FIELDS}),nextPageToken,incompleteSearch"
FOLDER_LIST_FIELDS = "kind,files(id,name,mimeType),nextPageToken,incompleteSearch"
PERMISSION_FIELDS = "id,type,role,emailAddress,allowFileDiscovery"
TRASH_FIELDS = "id,name,trashed"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
FOLDER_MATCH_LIMIT = 2
MAX_FOLDER_LOOKUP_PAGES = 5
TRASH_RETENTION_DAYS = 30
ROOT_FOLDER_ID = "root"
ROOT_FOLDER_NAMES = frozenset({ROOT_FOLDER_ID, "my drive", "mydrive"})
ACTIVE_FILES_CLAUSE = "trashed = false"
SHARED_FILES_CLAUSE = "sharedWithMe = true"


class DriveFileType(StrEnum):
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    FORM = "form"
    FOLDER = "folder"
    PDF = "pdf"
    IMAGE = "image"
    VIDEO = "video"


TYPE_CLAUSES = {
    DriveFileType.DOCUMENT: "mimeType = 'application/vnd.google-apps.document'",
    DriveFileType.SPREADSHEET: "mimeType = 'application/vnd.google-apps.spreadsheet'",
    DriveFileType.PRESENTATION: "mimeType = 'application/vnd.google-apps.presentation'",
    DriveFileType.FORM: "mimeType = 'application/vnd.google-apps.form'",
    DriveFileType.FOLDER: f"mimeType = '{FOLDER_MIME}'",
    DriveFileType.PDF: "mimeType = 'application/pdf'",
    DriveFileType.IMAGE: "mimeType contains 'image/'",
    DriveFileType.VIDEO: "mimeType contains 'video/'",
}


class DriveRole(StrEnum):
    READER = "reader"
    COMMENTER = "commenter"
    WRITER = "writer"


class DrivePermissionType(StrEnum):
    USER = "user"
    ANYONE = "anyone"
    GROUP = "group"
    DOMAIN = "domain"


class DrivePermissionRole(StrEnum):
    """Native response roles; broader than the curated tool's assignable roles."""

    READER = "reader"
    COMMENTER = "commenter"
    WRITER = "writer"
    OWNER = "owner"
    ORGANIZER = "organizer"
    FILE_ORGANIZER = "fileOrganizer"


class DriveErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    RECIPIENT_MISSING = "recipient_missing"
    FOLDER_MISSING = "folder_missing"
    FOLDER_NOT_FOUND = "folder_not_found"
    FOLDER_AMBIGUOUS = "folder_ambiguous"
    FOLDER_LOOKUP_INCOMPLETE = "folder_lookup_incomplete"


class DriveModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class DriveRequest(DriveModel):
    model_config = ConfigDict(extra="forbid")


class DriveOwner(DriveModel):
    emailAddress: str | None = Field(default=None, repr=False)
    displayName: str | None = None


class DriveResource(DriveModel):
    id: str = Field(min_length=1)
    name: str


class DriveFile(DriveResource):
    mimeType: str = Field(min_length=1)
    size: Annotated[str, Field(pattern=r"^[0-9]+$")] | None = None
    modifiedTime: str | None = None
    createdTime: str | None = None
    webViewLink: str | None = None
    parents: list[str] = Field(default_factory=list)
    owners: list[DriveOwner] = Field(default_factory=list)
    trashed: bool = False


class DriveFileList(DriveModel):
    # Explicitly requested so a missing files field is a valid empty list,
    # while a bare {} or unrelated response cannot masquerade as one.
    kind: Literal["drive#fileList"]
    files: list[DriveFile] = Field(default_factory=list)
    nextPageToken: str | None = None
    incompleteSearch: bool = False


class DriveFileQuery(DriveRequest):
    fields: str = FILE_FIELDS
    supportsAllDrives: Literal[True] = True


class DriveListQuery(DriveFileQuery):
    q: str = Field(repr=False)
    pageSize: int = Field(ge=1, le=MAX_PAGE_SIZE)
    fields: str = LIST_FIELDS
    orderBy: str | None = None
    pageToken: str | None = None
    includeItemsFromAllDrives: Literal[True] = True


class DriveFolderWrite(DriveRequest):
    name: str = Field(min_length=1)
    mimeType: Literal["application/vnd.google-apps.folder"] = FOLDER_MIME
    parents: list[str] | None = None


class DriveMoveQuery(DriveFileQuery):
    addParents: str | None = None
    removeParents: str | None = None


class DriveUserPermission(DriveRequest):
    type: Literal["user"] = "user"
    role: DriveRole
    emailAddress: str = Field(min_length=1, repr=False)


class DriveLinkPermission(DriveRequest):
    type: Literal["anyone"] = "anyone"
    role: Literal["reader"] = "reader"
    allowFileDiscovery: Literal[False] = False


class DrivePermissionQuery(DriveFileQuery):
    sendNotificationEmail: bool
    fields: str = PERMISSION_FIELDS


class DrivePermission(DriveModel):
    id: str = Field(min_length=1)
    type: DrivePermissionType
    role: DrivePermissionRole
    emailAddress: str | None = Field(default=None, repr=False)
    allowFileDiscovery: bool = False

    @field_validator("type", mode="before")
    @classmethod
    def native_type(cls, value: object) -> object:
        return DrivePermissionType(value) if isinstance(value, str) else value

    @field_validator("role", mode="before")
    @classmethod
    def native_role(cls, value: object) -> object:
        return DrivePermissionRole(value) if isinstance(value, str) else value


class DriveTrashWrite(DriveRequest):
    trashed: Literal[True] = True


class DriveTrashedFile(DriveResource):
    trashed: bool


class DriveApiError(DriveModel):
    code: int | None = None
    message: str | None = Field(default=None, repr=False)


class DriveErrorEnvelope(DriveModel):
    error: DriveApiError | None = None


class DriveFileView(DriveModel):
    id: str
    name: str
    mime_type: str
    is_folder: bool
    size_bytes: str | None
    modified_at: str | None
    created_at: str | None
    web_link: str | None
    parents: list[str]
    owner: str | None = Field(repr=False)


class DriveSearchView(DriveModel):
    files: list[DriveFileView]
    count: int
    query: str = Field(repr=False)
    next_page_token: str | None
    incomplete_search: bool


class DriveShareView(DriveModel):
    file_id: str
    permission_id: str
    granted_to: str = Field(repr=False)
    role: DrivePermissionRole
    public_link: bool


class DriveMovedView(DriveFileView):
    moved_from: list[str]


class DriveTrashView(DriveModel):
    file_id: str
    name: str
    trashed: bool
    recoverable_for_days: int = TRASH_RETENTION_DAYS


FILE_RESPONSE = TypeAdapter(DriveFile)
FILES_RESPONSE = TypeAdapter(DriveFileList)
PERMISSION_RESPONSE = TypeAdapter(DrivePermission)
TRASH_RESPONSE = TypeAdapter(DriveTrashedFile)


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            DriveErrorCode.REJECTED, "Google Drive rejected the request."
        )
    try:
        if DriveErrorEnvelope.model_validate(response.data).error is not None:
            raise VendorToolError(
                DriveErrorCode.REJECTED, "Google Drive rejected the request."
            )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            DriveErrorCode.RESPONSE_INVALID,
            "Google Drive returned an invalid operation response.",
        ) from None


def require_identity(resource: DriveResource, expected_id: str) -> None:
    if resource.id != expected_id:
        raise VendorToolError(
            DriveErrorCode.RESPONSE_INVALID, "Google Drive returned a different file."
        )
