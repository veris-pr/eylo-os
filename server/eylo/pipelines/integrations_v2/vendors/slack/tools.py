"""Typed Slack reads and receipt-backed posting with bounded name resolution."""

import re

from pydantic import Field, JsonValue, TypeAdapter, field_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import (
    CHANNELS_HISTORY,
    CHANNELS_READ,
    CHAT_WRITE,
    USERS_READ,
    USERS_READ_EMAIL,
    vendor,
)
from .schemas import (
    CHANNELS,
    CHANNEL_ID_PATTERN,
    DEFAULT_CHANNEL_LIMIT,
    DEFAULT_HISTORY_LIMIT,
    HISTORY,
    MAX_LOOKUP_PAGES,
    MAX_MESSAGE_CHARS,
    MAX_PAGE_SIZE,
    POST,
    USER,
    USERS,
    ChannelView,
    ChannelsQuery,
    ChannelsView,
    Cursor,
    EmailQuery,
    HistoryQuery,
    HistoryView,
    MessageView,
    PageQuery,
    PostRequest,
    PostView,
    SlackErrorCode,
    SlackMethod,
    SlackRequest,
    Timestamp,
    UserView,
    invalid_response,
    next_cursor,
    parse_response,
)


class ChannelInput(SlackRequest):
    channel: str = Field(
        min_length=1,
        max_length=255,
        description="Public channel name, with optional #, or channel ID. Access still requires the bot's scopes and membership.",
    )

    @field_validator("channel")
    @classmethod
    def normalize_channel(cls, value: str) -> str:
        value = value.strip().removeprefix("#")
        if not value:
            raise ValueError("Channel name or ID is required.")
        return value


class PostMessageInput(ChannelInput):
    text: str = Field(
        min_length=1,
        max_length=MAX_MESSAGE_CHARS,
        description="Slack mrkdwn text. Longer messages are rejected, not silently truncated.",
    )
    thread_ts: Timestamp | None = Field(
        default=None,
        description="Parent message timestamp for a thread reply; retain it as a string.",
    )


class ReadChannelInput(ChannelInput):
    limit: int = Field(
        default=DEFAULT_HISTORY_LIMIT,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Requested page size; Slack may return fewer messages under its app-specific limits.",
    )
    cursor: Cursor | None = None
    latest: Timestamp | None = Field(
        default=None,
        description="Exclusive upper time boundary; use next_latest when no next_cursor is returned.",
    )


class ListChannelsInput(SlackRequest):
    query: str | None = Field(
        default=None,
        description="Case-insensitive name filter on the current page; continue with next_cursor, including after an empty page.",
    )
    limit: int = Field(default=DEFAULT_CHANNEL_LIMIT, ge=1, le=MAX_PAGE_SIZE)
    cursor: Cursor | None = None


class FindUserInput(EmailQuery):
    """Lookup is by the workspace email; it is not a directory substring search."""


async def _call[T](
    ctx: VendorToolContext,
    method: SlackMethod,
    payload: SlackRequest,
    schema: TypeAdapter[T],
) -> T:
    body = payload.model_dump(mode="json", exclude_none=True)
    if method is SlackMethod.POST_MESSAGE:
        response = await ctx.mutate(f"/{method.value}", json=body)
    else:
        response = await ctx.read(f"/{method.value}", query=body)
    return parse_response(response, schema)


@curated_tool(
    vendor=vendor.vendor,
    name="list_channels",
    display_name="List Slack Channels",
    description="List one page of public Slack channels. Optional name filtering applies to this page only; use next_cursor to continue, even after zero matches. Posting and reading also accept channel names directly.",
    input_model=ListChannelsInput,
    effect=ToolEffect.READ,
    scopes=(CHANNELS_READ,),
)
async def list_channels(
    payload: ListChannelsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    page = await _call(
        ctx,
        SlackMethod.CHANNELS,
        ChannelsQuery(limit=payload.limit, cursor=payload.cursor),
        CHANNELS,
    )
    if len(page.channels) > payload.limit:
        invalid_response()
    needle = (payload.query or "").strip().casefold()
    channels = [
        ChannelView(
            id=channel.id,
            name=channel.name,
            is_private=channel.is_private,
            member_count=channel.num_members,
            topic=channel.topic.value if channel.topic else None,
        )
        for channel in page.channels
        if not needle or needle in channel.name.casefold()
    ]
    return ChannelsView(
        channels=channels,
        count=len(channels),
        next_cursor=next_cursor(page, payload.cursor),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="post_message",
    display_name="Post Slack Message",
    description="Post Slack mrkdwn to a channel by ID or public channel name. The bot needs channel access; this tool does not join channels. Use thread_ts for a thread reply. Returns Slack's acknowledged message identity and text, not a delivery/read confirmation.",
    input_model=PostMessageInput,
    effect=ToolEffect.MUTATION,
    scopes=(CHAT_WRITE, CHANNELS_READ),
)
async def post_message(
    payload: PostMessageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    channel_id = await _resolve_channel(ctx, payload.channel)
    result = await _call(
        ctx,
        SlackMethod.POST_MESSAGE,
        PostRequest(channel=channel_id, text=payload.text, thread_ts=payload.thread_ts),
        POST,
    )
    if (
        result.channel != channel_id
        or (result.message.ts is not None and result.message.ts != result.ts)
        or result.message.thread_ts != payload.thread_ts
    ):
        invalid_response()
    warnings = list(result.response_metadata.warnings)
    if result.warning:
        warnings.append(result.warning)
    return PostView(
        channel_id=result.channel,
        ts=result.ts,
        permalink_hint=f"{result.channel}/{result.ts}",
        text=result.message.text,
        thread_ts=result.message.thread_ts,
        warnings=warnings,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="read_channel",
    display_name="Read Slack Channel",
    description="Read one page of recent public-channel messages in Slack's newest-first order. Author names are resolved with bounded directory pagination; unresolved_author_ids identifies remaining IDs. Continue with next_cursor or next_latest. This reads top-level history, not thread replies or file contents; unrendered Block Kit types are identified explicitly.",
    input_model=ReadChannelInput,
    effect=ToolEffect.READ,
    scopes=(CHANNELS_HISTORY, CHANNELS_READ, USERS_READ),
)
async def read_channel(
    payload: ReadChannelInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    channel_id = await _resolve_channel(ctx, payload.channel)
    history = await _call(
        ctx,
        SlackMethod.HISTORY,
        HistoryQuery(
            channel=channel_id,
            limit=payload.limit,
            cursor=payload.cursor,
            latest=payload.latest,
        ),
        HISTORY,
    )
    if len(history.messages) > payload.limit:
        invalid_response()
    cursor = next_cursor(history, payload.cursor)
    latest = None
    if history.has_more and cursor is None:
        if not history.messages:
            invalid_response()
        latest = min(
            history.messages, key=lambda message: _timestamp_key(message.ts)
        ).ts
        if payload.latest is not None and _timestamp_key(latest) >= _timestamp_key(
            payload.latest
        ):
            invalid_response()
    user_ids = {message.user for message in history.messages if message.user}
    names = await _display_names(ctx, user_ids)
    messages = [
        MessageView(
            ts=message.ts,
            author=names.get(message.user, message.user)
            if message.user
            else (message.username or message.bot_id),
            author_id=message.user or message.bot_id,
            text=message.text,
            subtype=message.subtype,
            thread_ts=message.thread_ts,
            reply_count=message.reply_count,
            attachments=message.attachments,
            files=message.files,
            unrendered_block_types=[block.type for block in message.blocks],
        )
        for message in history.messages
    ]
    return HistoryView(
        channel_id=channel_id,
        messages=messages,
        count=len(messages),
        next_cursor=cursor,
        next_latest=latest,
        unresolved_author_ids=sorted(user_ids - names.keys()),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="find_user_by_email",
    display_name="Find Slack User By Email",
    description="Find a Slack workspace user by their registered email address. Returns native identity, display name and reported account flags. A successful lookup does not establish channel membership or permission to message them.",
    input_model=FindUserInput,
    effect=ToolEffect.READ,
    scopes=(USERS_READ, USERS_READ_EMAIL),
)
async def find_user_by_email(
    payload: FindUserInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    result = await _call(ctx, SlackMethod.USER_BY_EMAIL, payload, USER)
    user = result.user
    if (
        user.profile.email is not None
        and user.profile.email.casefold() != payload.email.casefold()
    ):
        invalid_response()
    return UserView(
        id=user.id,
        name=user.name,
        real_name=user.profile.real_name or user.real_name,
        display_name=user.display_name,
        email=user.profile.email,
        is_bot=user.is_bot,
        deleted=user.deleted,
    ).model_dump(mode="json")


async def _resolve_channel(ctx: VendorToolContext, channel: str) -> str:
    """Resolve a public name without treating a bounded search as exhaustive."""
    if re.fullmatch(CHANNEL_ID_PATTERN, channel):
        return channel
    cursor = None
    seen: set[str] = set()
    for _ in range(MAX_LOOKUP_PAGES):
        page = await _call(
            ctx,
            SlackMethod.CHANNELS,
            ChannelsQuery(limit=MAX_PAGE_SIZE, cursor=cursor),
            CHANNELS,
        )
        matches = [
            entry
            for entry in page.channels
            if entry.name.casefold() == channel.casefold()
        ]
        if len(matches) > 1:
            raise VendorToolError(
                SlackErrorCode.CHANNEL_AMBIGUOUS,
                "Use a channel ID to disambiguate this Slack channel.",
            )
        if matches:
            return matches[0].id
        cursor = next_cursor(page, cursor)
        if not cursor:
            raise VendorToolError(
                SlackErrorCode.CHANNEL_NOT_FOUND,
                "No matching public channel is visible to this connection.",
            )
        if cursor in seen:
            invalid_response()
        seen.add(cursor)
    raise VendorToolError(
        SlackErrorCode.LOOKUP_INCOMPLETE,
        "Channel lookup reached its page budget. Supply the channel ID instead.",
    )


async def _display_names(ctx: VendorToolContext, user_ids: set[str]) -> dict[str, str]:
    """Page a bounded directory, not one vendor request per message author."""
    names: dict[str, str] = {}
    cursor = None
    seen: set[str] = set()
    for _ in range(MAX_LOOKUP_PAGES):
        if user_ids <= names.keys():
            break
        page = await _call(
            ctx, SlackMethod.USERS, PageQuery(limit=MAX_PAGE_SIZE, cursor=cursor), USERS
        )
        for member in page.members:
            if member.id in user_ids:
                names[member.id] = member.display_name
        cursor = next_cursor(page, cursor)
        if not cursor:
            break
        if cursor in seen:
            invalid_response()
        seen.add(cursor)
    return names


def _timestamp_key(value: str) -> tuple[int, int]:
    seconds, micros = value.split(".")
    return int(seconds), int(micros)


__all__ = ["find_user_by_email", "list_channels", "post_message", "read_channel"]
