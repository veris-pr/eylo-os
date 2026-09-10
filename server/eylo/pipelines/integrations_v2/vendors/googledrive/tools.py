"""Curated Google Drive tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import BaseModel, Field, JsonValue, StrictBool, StrictInt, field_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import DRIVE, vendor
from .schemas import (
    ACTIVE_FILES_CLAUSE,
    DEFAULT_PAGE_SIZE,
    FILES_RESPONSE,
    FILE_FIELDS,
    FILE_RESPONSE,
    FOLDER_LIST_FIELDS,
    FOLDER_MATCH_LIMIT,
    FOLDER_MIME,
    MAX_FOLDER_LOOKUP_PAGES,
    MAX_PAGE_SIZE,
    PERMISSION_RESPONSE,
    ROOT_FOLDER_ID,
    ROOT_FOLDER_NAMES,
    SHARED_FILES_CLAUSE,
    TRASH_FIELDS,
    TRASH_RESPONSE,
    TYPE_CLAUSES,
    DriveErrorCode,
    DriveFile,
    DriveFileQuery,
    DriveFileType,
    DriveFileView,
    DriveFolderWrite,
    DriveLinkPermission,
    DriveListQuery,
    DriveMoveQuery,
    DriveMovedView,
    DrivePermissionQuery,
    DrivePermissionType,
    DriveRole,
    DriveSearchView,
    DriveShareView,
    DriveTrashView,
    DriveTrashWrite,
    DriveUserPermission,
    parse_response,
    require_identity,
)


class SearchFilesInput(BaseModel):
    name_contains: str | None = Field(
        default=None, description="Match files whose name contains this text."
    )
    file_type: DriveFileType | None = Field(
        default=None,
        description=(
            "One of document, spreadsheet, presentation, form, folder, pdf, "
            "image, video. Omit for any type."
        ),
    )
    in_folder: str | None = Field(
        default=None, description="Folder id, or a folder name to resolve."
    )
    modified_after: str | None = Field(
        default=None, description="ISO 8601 timestamp; only newer files match."
    )
    shared_with_me: StrictBool = Field(default=False)
    limit: StrictInt = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    page_token: str | None = Field(
        default=None, description="Continue a previous search with the same filters."
    )

    @field_validator("file_type", mode="before")
    @classmethod
    def normalize_file_type(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


class GetFileInput(BaseModel):
    file_id: str = Field(min_length=1)


class CreateFolderInput(BaseModel):
    name: str = Field(min_length=1)
    parent: str | None = Field(
        default=None, description="Parent folder id or name. Defaults to My Drive."
    )


class ShareFileInput(BaseModel):
    file_id: str = Field(min_length=1)
    email: str | None = Field(
        default=None,
        description="Person to share with. Required unless sharing by link.",
    )
    role: DriveRole = Field(
        default=DriveRole.READER, description="One of reader, commenter, writer."
    )
    anyone_with_link: StrictBool = Field(
        default=False,
        description=(
            "Make the file readable by anyone holding the link. This exposes "
            "it outside the organization, so it defaults to off."
        ),
    )
    notify: StrictBool = Field(
        default=True, description="Send Google's notification email."
    )

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


class MoveFileInput(BaseModel):
    file_id: str = Field(min_length=1)
    destination_folder: str = Field(
        min_length=1, description="Destination folder id or name."
    )


class TrashFileInput(BaseModel):
    file_id: str = Field(min_length=1)


@curated_tool(
    vendor=vendor.vendor,
    name="search_files",
    display_name="Search Google Drive",
    description=(
        "Find files and folders by name, type, containing folder, or "
        "modification date, without writing Drive query syntax. A folder may "
        "be named rather than identified. Results include the web link, owner, "
        "and modification time, so a follow-up lookup is rarely needed. "
        "Trashed files are excluded. Results expose a continuation token and "
        "whether Google's search was incomplete; reuse the filters with the token."
    ),
    input_model=SearchFilesInput,
    effect=ToolEffect.READ,
    scopes=(DRIVE,),
)
async def search_files(
    payload: SearchFilesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    clauses = [ACTIVE_FILES_CLAUSE]
    if payload.name_contains:
        clauses.append(f"name contains '{_escape(payload.name_contains)}'")
    if payload.file_type:
        clauses.append(TYPE_CLAUSES[payload.file_type])
    if payload.in_folder:
        folder_id = await _resolve_folder(ctx, payload.in_folder)
        clauses.append(f"'{_escape(folder_id)}' in parents")
    if payload.modified_after:
        clauses.append(f"modifiedTime > '{_escape(payload.modified_after)}'")
    if payload.shared_with_me:
        clauses.append(SHARED_FILES_CLAUSE)
    query = " and ".join(clauses)
    response = await ctx.read(
        "/files",
        query=DriveListQuery(
            q=query,
            pageSize=payload.limit,
            pageToken=payload.page_token,
            orderBy="modifiedTime desc",
        ).model_dump(mode="json", exclude_none=True),
    )
    page = parse_response(response, FILES_RESPONSE)
    return DriveSearchView(
        files=[_file_view(item) for item in page.files],
        count=len(page.files),
        query=query,
        next_page_token=page.nextPageToken,
        incomplete_search=page.incompleteSearch,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_file",
    display_name="Get Google Drive File",
    description=(
        "Look up one file or folder's details: name, type, size, owner, "
        "parents, and web link. Use the Google Docs or Google Sheets tools to "
        "read what is inside a document."
    ),
    input_model=GetFileInput,
    effect=ToolEffect.READ,
    scopes=(DRIVE,),
)
async def get_file(
    payload: GetFileInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    response = await ctx.read(
        f"/files/{quote(payload.file_id, safe='')}",
        query=DriveFileQuery().model_dump(mode="json"),
    )
    item = parse_response(response, FILE_RESPONSE)
    require_identity(item, payload.file_id)
    return _file_view(item).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_folder",
    display_name="Create Google Drive Folder",
    description=(
        "Create a folder, optionally inside another folder named rather than "
        "identified. Returns the new folder's id and web link."
    ),
    input_model=CreateFolderInput,
    effect=ToolEffect.MUTATION,
    scopes=(DRIVE,),
)
async def create_folder(
    payload: CreateFolderInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    parent_id = await _resolve_folder(ctx, payload.parent) if payload.parent else None
    body = DriveFolderWrite(
        name=payload.name, parents=[parent_id] if parent_id else None
    )
    response = await ctx.mutate(
        "/files",
        json=body.model_dump(mode="json", exclude_none=True),
        query=DriveFileQuery().model_dump(mode="json"),
    )
    folder = parse_response(response, FILE_RESPONSE)
    if folder.mimeType != FOLDER_MIME or (parent_id and folder.parents != [parent_id]):
        raise VendorToolError(
            DriveErrorCode.RESPONSE_INVALID,
            "Google Drive did not confirm the requested folder.",
        )
    return _file_view(folder).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="share_file",
    display_name="Share Google Drive File",
    description=(
        "Grant access to a file or folder. Give an email address and a role of "
        "reader, commenter, or writer. Setting anyone_with_link instead makes "
        "the file readable by anyone who has the link, including people "
        "outside the organization."
    ),
    input_model=ShareFileInput,
    effect=ToolEffect.MUTATION,
    scopes=(DRIVE,),
)
async def share_file(
    payload: ShareFileInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    permission: DriveUserPermission | DriveLinkPermission
    if payload.anyone_with_link:
        permission = DriveLinkPermission()
    elif payload.email and payload.email.strip():
        permission = DriveUserPermission(
            role=payload.role, emailAddress=payload.email.strip()
        )
    else:
        raise VendorToolError(
            DriveErrorCode.RECIPIENT_MISSING,
            "Give an email address, or explicitly request link sharing.",
        )
    response = await ctx.mutate(
        f"/files/{quote(payload.file_id, safe='')}/permissions",
        json=permission.model_dump(mode="json"),
        query=DrivePermissionQuery(
            sendNotificationEmail=payload.notify and not payload.anyone_with_link
        ).model_dump(mode="json"),
    )
    granted = parse_response(response, PERMISSION_RESPONSE)
    if granted.type != permission.type or granted.role != permission.role:
        raise VendorToolError(
            DriveErrorCode.RESPONSE_INVALID,
            "Google Drive did not confirm the requested permission.",
        )
    if isinstance(permission, DriveLinkPermission) and granted.allowFileDiscovery:
        raise VendorToolError(
            DriveErrorCode.RESPONSE_INVALID,
            "Google Drive returned a discoverable public permission.",
        )
    if isinstance(permission, DriveUserPermission) and not granted.emailAddress:
        raise VendorToolError(
            DriveErrorCode.RESPONSE_INVALID,
            "Google Drive omitted the granted recipient.",
        )
    return DriveShareView(
        file_id=payload.file_id,
        permission_id=granted.id,
        granted_to=granted.emailAddress or granted.type,
        role=granted.role,
        public_link=granted.type == DrivePermissionType.ANYONE,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="move_file",
    display_name="Move Google Drive File",
    description=(
        "Move a file or folder into another folder. Drive models this as "
        "editing the file's parent list, so this reads the current parents and "
        "swaps them in one step. The destination may be named rather than "
        "identified."
    ),
    input_model=MoveFileInput,
    effect=ToolEffect.MUTATION,
    scopes=(DRIVE,),
)
async def move_file(
    payload: MoveFileInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    destination = await _resolve_folder(ctx, payload.destination_folder)
    current = parse_response(
        await ctx.read(
            f"/files/{quote(payload.file_id, safe='')}",
            query=DriveFileQuery().model_dump(mode="json"),
        ),
        FILE_RESPONSE,
    )
    require_identity(current, payload.file_id)
    previous = current.parents
    if previous == [destination]:
        return DriveMovedView(
            **_file_view(current).model_dump(), moved_from=previous
        ).model_dump(mode="json")
    response = await ctx.mutate(
        f"/files/{quote(payload.file_id, safe='')}",
        method="PATCH",
        json={},
        query=DriveMoveQuery(
            addParents=destination if destination not in previous else None,
            removeParents=",".join(
                parent for parent in previous if parent != destination
            )
            or None,
        ).model_dump(mode="json", exclude_none=True),
    )
    moved = parse_response(response, FILE_RESPONSE)
    require_identity(moved, payload.file_id)
    if moved.parents != [destination]:
        raise VendorToolError(
            DriveErrorCode.RESPONSE_INVALID,
            "Google Drive did not confirm the destination folder.",
        )
    return DriveMovedView(
        **_file_view(moved).model_dump(), moved_from=previous
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="trash_file",
    display_name="Move Google Drive File to Trash",
    description=(
        "Move a file or folder to Drive's trash, where it stays recoverable "
        "for thirty days. Permanent deletion is not offered."
    ),
    input_model=TrashFileInput,
    effect=ToolEffect.MUTATION,
    scopes=(DRIVE,),
)
async def trash_file(
    payload: TrashFileInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    response = await ctx.mutate(
        f"/files/{quote(payload.file_id, safe='')}",
        method="PATCH",
        json=DriveTrashWrite().model_dump(mode="json"),
        query=DriveFileQuery(fields=TRASH_FIELDS).model_dump(mode="json"),
    )
    trashed = parse_response(response, TRASH_RESPONSE)
    require_identity(trashed, payload.file_id)
    if not trashed.trashed:
        raise VendorToolError(
            DriveErrorCode.RESPONSE_INVALID,
            "Google Drive did not confirm the file was trashed.",
        )
    return DriveTrashView(
        file_id=trashed.id, name=trashed.name, trashed=trashed.trashed
    ).model_dump(mode="json")


async def _resolve_folder(ctx: VendorToolContext, folder: str) -> str:
    """Resolve names without hiding partial searches; validate ID fallbacks as folders."""
    candidate = folder.strip()
    if not candidate:
        raise VendorToolError(
            DriveErrorCode.FOLDER_MISSING, "A folder id or name is required."
        )
    if candidate.casefold() in ROOT_FOLDER_NAMES:
        return await _folder_by_id(ctx, ROOT_FOLDER_ID)
    matches: dict[str, DriveFile] = {}
    token = None
    seen: set[str] = set()
    for _ in range(MAX_FOLDER_LOOKUP_PAGES):
        response = await ctx.read(
            "/files",
            query=DriveListQuery(
                q=f"mimeType = '{FOLDER_MIME}' and trashed = false and name = '{_escape(candidate)}'",
                pageSize=FOLDER_MATCH_LIMIT,
                fields=FOLDER_LIST_FIELDS,
                pageToken=token,
            ).model_dump(mode="json", exclude_none=True),
        )
        page = parse_response(response, FILES_RESPONSE)
        if page.incompleteSearch:
            break
        for item in page.files:
            if item.mimeType != FOLDER_MIME or item.name != candidate or item.trashed:
                raise VendorToolError(
                    DriveErrorCode.RESPONSE_INVALID,
                    "Google Drive returned an unexpected folder match.",
                )
            matches[item.id] = item
        if len(matches) > 1:
            raise VendorToolError(
                DriveErrorCode.FOLDER_AMBIGUOUS,
                "More than one folder has that name; use its ID.",
            )
        token = page.nextPageToken
        if not token:
            if matches:
                return next(iter(matches))
            return await _folder_by_id(ctx, candidate)
        if token in seen:
            break
        seen.add(token)
    raise VendorToolError(
        DriveErrorCode.FOLDER_LOOKUP_INCOMPLETE,
        "Google Drive folder lookup was incomplete; use a folder ID.",
    )


async def _folder_by_id(ctx: VendorToolContext, candidate: str) -> str:
    response = await ctx.read(
        f"/files/{quote(candidate, safe='')}",
        query=DriveFileQuery().model_dump(mode="json"),
    )
    if response.status_code == 404:
        raise VendorToolError(
            DriveErrorCode.FOLDER_NOT_FOUND,
            "No matching Google Drive folder is visible.",
        )
    folder = parse_response(response, FILE_RESPONSE)
    if candidate != ROOT_FOLDER_ID:
        require_identity(folder, candidate)
    if folder.mimeType != FOLDER_MIME or folder.trashed:
        raise VendorToolError(
            DriveErrorCode.FOLDER_NOT_FOUND,
            "The destination is not an active Google Drive folder.",
        )
    return folder.id


def _escape(value: str) -> str:
    """Drive query literals escape backslashes before single quotes."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _file_view(item: DriveFile) -> DriveFileView:
    return DriveFileView(
        id=item.id,
        name=item.name,
        mime_type=item.mimeType,
        is_folder=item.mimeType == FOLDER_MIME,
        size_bytes=item.size,
        modified_at=item.modifiedTime,
        created_at=item.createdTime,
        web_link=item.webViewLink,
        parents=item.parents,
        owner=item.owners[0].emailAddress if item.owners else None,
    )


__all__ = [
    "create_folder",
    "get_file",
    "move_file",
    "search_files",
    "share_file",
    "trash_file",
]
