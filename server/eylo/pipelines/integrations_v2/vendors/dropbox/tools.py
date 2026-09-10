"""Curated Dropbox tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field, JsonValue, StrictBool, StrictInt, field_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import FILES_READ, FILES_WRITE, SHARING_READ, SHARING_WRITE, vendor
from .schemas import (
    CREATED_RESPONSE,
    DEFAULT_FOLDER_RESULTS,
    DEFAULT_SEARCH_RESULTS,
    FILE_ID_PREFIX,
    FOLDER_RESPONSE,
    LINKS_RESPONSE,
    LINK_RESPONSE,
    MAX_QUERY_LENGTH,
    MAX_RESULTS,
    METADATA_RESPONSE,
    SEARCH_RESPONSE,
    CursorQuery,
    DeletedMetadata,
    DeletedView,
    DirectLinksQuery,
    DropboxErrorCode,
    FolderCreate,
    FolderQuery,
    FolderView,
    MoveRequest,
    MovedView,
    PathRequest,
    SearchOptions,
    SearchQuery,
    SearchView,
    ShareView,
    SharedLink,
    destination_path,
    entry_view,
    mutation_path,
    normalize_path,
    parse_response,
)


class ListFolderInput(BaseModel):
    path: str = Field(
        default="/", description="Folder path, e.g. /Work. Use / for the root."
    )
    recursive: StrictBool = Field(default=False)
    limit: StrictInt = Field(default=DEFAULT_FOLDER_RESULTS, ge=1, le=MAX_RESULTS)
    cursor: str | None = Field(
        default=None,
        min_length=1,
        description="Continue the previous folder listing; its path and recursive settings are encoded in the cursor.",
    )


class SearchFilesInput(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=MAX_QUERY_LENGTH,
        description="Text to match in file names.",
    )
    path: str = Field(default="/", description="Folder to search within.")
    file_extensions: list[str] | None = Field(
        default=None, description="Limit to these extensions, e.g. ['pdf', 'docx']."
    )
    limit: StrictInt = Field(default=DEFAULT_SEARCH_RESULTS, ge=1, le=MAX_RESULTS)
    cursor: str | None = Field(
        default=None,
        min_length=1,
        description="Continue the previous search; its filters are encoded in the cursor.",
    )

    @field_validator("file_extensions")
    @classmethod
    def normalize_extensions(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        result = [value.strip().lstrip(".").casefold() for value in values]
        if any(not value for value in result):
            raise ValueError("File extensions cannot be empty.")
        return result


class CreateFolderInput(BaseModel):
    path: str = Field(min_length=1, description="Full path of the new folder.")


class MoveInput(BaseModel):
    from_path: str = Field(min_length=1)
    to_path: str = Field(min_length=1, description="Including the new name.")


class ShareInput(BaseModel):
    path: str = Field(min_length=1, description="File or folder to share.")


class DeleteInput(BaseModel):
    path: str = Field(min_length=1)


@curated_tool(
    vendor=vendor.vendor,
    name="list_folder",
    display_name="List Dropbox Folder",
    description=(
        "List what is in a folder. Use / for the root — Dropbox itself needs "
        "an empty string there, which is handled here. Each entry says whether "
        "it is a file or a folder, and files report their size and when they "
        "changed. Return next_cursor as cursor to continue the same listing. "
        "The requested limit is approximate; Dropbox may return slightly more."
    ),
    input_model=ListFolderInput,
    effect=ToolEffect.READ,
    scopes=(FILES_READ,),
)
async def list_folder(
    payload: ListFolderInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    if payload.cursor is not None:
        response = await ctx.read(
            "/files/list_folder/continue",
            method="POST",
            json=CursorQuery(cursor=payload.cursor).model_dump(mode="json"),
        )
    else:
        request = FolderQuery(
            path=normalize_path(payload.path),
            recursive=payload.recursive,
            limit=payload.limit,
        )
        response = await ctx.read(
            "/files/list_folder", method="POST", json=request.model_dump(mode="json")
        )
    page = parse_response(response, FOLDER_RESPONSE)
    return FolderView(
        path=payload.path,
        entries=[entry_view(item) for item in page.entries],
        count=len(page.entries),
        more_available=page.has_more,
        next_cursor=page.cursor if page.has_more else None,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="search_files",
    display_name="Search Dropbox",
    description=(
        "Find files and folders by name, optionally within a folder and "
        "limited to certain extensions. Dropbox buries the real entry two "
        "levels inside each result; this returns them flattened. Return next_cursor "
        "as cursor to continue the same search. Search is eventually indexed; "
        "Dropbox may repeat or omit matches across pages."
    ),
    input_model=SearchFilesInput,
    effect=ToolEffect.READ,
    scopes=(FILES_READ,),
)
async def search_files(
    payload: SearchFilesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    if payload.cursor is not None:
        response = await ctx.read(
            "/files/search/continue_v2",
            method="POST",
            json=CursorQuery(cursor=payload.cursor).model_dump(mode="json"),
        )
    else:
        request = SearchQuery(
            query=payload.query,
            options=SearchOptions(
                path=normalize_path(payload.path),
                max_results=payload.limit,
                file_extensions=payload.file_extensions or None,
            ),
        )
        response = await ctx.read(
            "/files/search_v2",
            method="POST",
            json=request.model_dump(mode="json", exclude_none=True),
        )
    page = parse_response(response, SEARCH_RESPONSE)
    return SearchView(
        results=[entry_view(match.metadata.metadata) for match in page.matches],
        count=len(page.matches),
        query=payload.query,
        more_available=page.has_more,
        next_cursor=page.cursor if page.has_more else None,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_folder",
    display_name="Create Dropbox Folder",
    description=(
        "Create a folder at the given path. Parent folders are created as "
        "needed. If the name is taken, Dropbox is asked to pick a free one "
        "rather than failing."
    ),
    input_model=CreateFolderInput,
    effect=ToolEffect.MUTATION,
    scopes=(FILES_WRITE,),
)
async def create_folder(
    payload: CreateFolderInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    request = FolderCreate(path=destination_path(payload.path))
    response = await ctx.mutate(
        "/files/create_folder_v2", json=request.model_dump(mode="json")
    )
    result = parse_response(response, CREATED_RESPONSE)
    return entry_view(result.metadata).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="move",
    display_name="Move or Rename in Dropbox",
    description=(
        "Move a file or folder to a new path. Renaming is the same operation "
        "with a new final path segment. The destination path must include the "
        "name, not just the folder."
    ),
    input_model=MoveInput,
    effect=ToolEffect.MUTATION,
    scopes=(FILES_WRITE,),
)
async def move(payload: MoveInput, ctx: VendorToolContext) -> dict[str, JsonValue]:
    request = MoveRequest(
        from_path=mutation_path(payload.from_path),
        to_path=destination_path(payload.to_path),
    )
    response = await ctx.mutate("/files/move_v2", json=request.model_dump(mode="json"))
    result = parse_response(response, METADATA_RESPONSE)
    if isinstance(result.metadata, DeletedMetadata):
        raise VendorToolError(
            DropboxErrorCode.RESPONSE_INVALID,
            "Dropbox did not confirm a live moved item.",
        )
    return MovedView(
        **entry_view(result.metadata).model_dump(), moved_from=payload.from_path
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_share_link",
    display_name="Create Dropbox Share Link",
    description=(
        "Get a shareable link for a file or folder. Reuse a direct existing link "
        "without changing its permissions; otherwise create one with Dropbox's "
        "account defaults. Check visibility, audience and access in the result: "
        "team or folder policy may restrict access. Concurrent creation can fail; "
        "do not assume a failed or uncertain write is safe to repeat."
    ),
    input_model=ShareInput,
    effect=ToolEffect.MUTATION,
    scopes=(SHARING_READ, SHARING_WRITE),
)
async def create_share_link(
    payload: ShareInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    path = mutation_path(payload.path)
    query = DirectLinksQuery(path=path)
    response = await ctx.read(
        "/sharing/list_shared_links", method="POST", json=query.model_dump(mode="json")
    )
    page = parse_response(response, LINKS_RESPONSE)
    if page.links:
        return _share_view(path, page.links[0])
    if page.has_more:
        raise VendorToolError(
            DropboxErrorCode.LINK_LOOKUP_INCOMPLETE,
            "Dropbox did not finish direct-link lookup; no new link was created.",
        )
    response = await ctx.mutate(
        "/sharing/create_shared_link_with_settings",
        json=PathRequest(path=path).model_dump(mode="json"),
    )
    return _share_view(path, parse_response(response, LINK_RESPONSE))


@curated_tool(
    vendor=vendor.vendor,
    name="delete",
    display_name="Delete from Dropbox",
    description=(
        "Move a file or folder to Dropbox's deleted items. Recovery depends on "
        "the account's retention policy; this tool does not know its duration. "
        "Permanent deletion is not offered."
    ),
    input_model=DeleteInput,
    effect=ToolEffect.MUTATION,
    scopes=(FILES_WRITE,),
)
async def delete(payload: DeleteInput, ctx: VendorToolContext) -> dict[str, JsonValue]:
    path = mutation_path(payload.path)
    response = await ctx.mutate(
        "/files/delete_v2", json=PathRequest(path=path).model_dump(mode="json")
    )
    result = parse_response(response, METADATA_RESPONSE)
    view = entry_view(result.metadata)
    if path.startswith(FILE_ID_PREFIX):
        if view.id is not None and view.id != path:
            _wrong_resource()
    elif path.startswith("/") and result.metadata.path_lower is not None:
        if result.metadata.path_lower != path.lower():
            _wrong_resource()
    return DeletedView(**view.model_dump()).model_dump(mode="json")


def _share_view(path: str, link: SharedLink) -> dict[str, JsonValue]:
    if path.startswith(FILE_ID_PREFIX) and link.id is not None and link.id != path:
        _wrong_resource()
    if (
        path.startswith("/")
        and link.path_lower is not None
        and link.path_lower != path.lower()
    ):
        _wrong_resource()
    permissions = link.link_permissions
    return ShareView(
        path=path,
        url=link.url,
        name=link.name,
        visibility=permissions.resolved_visibility.tag
        if permissions.resolved_visibility
        else None,
        audience=permissions.effective_audience.tag
        if permissions.effective_audience
        else None,
        access=permissions.link_access_level.tag
        if permissions.link_access_level
        else None,
    ).model_dump(mode="json")


def _wrong_resource() -> None:
    raise VendorToolError(
        DropboxErrorCode.RESPONSE_INVALID, "Dropbox returned a different resource."
    )


__all__ = [
    "create_folder",
    "create_share_link",
    "delete",
    "list_folder",
    "move",
    "search_files",
]
