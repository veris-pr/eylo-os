"""Slack Web API envelopes, native entities, requests and tool projections."""

from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ...contracts import VendorResponse, VendorToolError

MAX_PAGE_SIZE = 200
DEFAULT_CHANNEL_LIMIT = 50
DEFAULT_HISTORY_LIMIT = 20
MAX_LOOKUP_PAGES = 10
MAX_MESSAGE_CHARS = 40_000
MAX_CURSOR_CHARS = 4_096
CHANNEL_ID_PATTERN = r"^[CGD][A-Z0-9]+$"


class SlackMethod(StrEnum):
    CHANNELS = "conversations.list"
    HISTORY = "conversations.history"
    POST_MESSAGE = "chat.postMessage"
    USERS = "users.list"
    USER_BY_EMAIL = "users.lookupByEmail"


class SlackErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    CHANNEL_NOT_FOUND = "channel_not_found"
    CHANNEL_AMBIGUOUS = "channel_ambiguous"
    LOOKUP_INCOMPLETE = "channel_lookup_incomplete"


class ConversationType(StrEnum):
    PUBLIC = "public_channel"


class MessageType(StrEnum):
    MESSAGE = "message"


Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Z][A-Z0-9]+$")]
ChannelId = Annotated[str, Field(pattern=CHANNEL_ID_PATTERN)]
Timestamp = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]{6}$")]
Cursor = Annotated[str, Field(min_length=1, max_length=MAX_CURSOR_CHARS)]


class SlackModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class SlackRequest(SlackModel):
    model_config = ConfigDict(extra="forbid")


class ResponseMetadata(SlackModel):
    next_cursor: str = Field(default="", max_length=MAX_CURSOR_CHARS)
    # Slack may introduce warnings independently of this client's release.
    warnings: list[str] = Field(default_factory=list)


class Envelope(SlackModel):
    ok: bool
    error: str | None = None
    warning: str | None = None
    response_metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)


class Topic(SlackModel):
    value: str


class Channel(SlackModel):
    id: ChannelId
    name: str = Field(min_length=1)
    is_private: bool
    num_members: int | None = Field(default=None, ge=0)
    topic: Topic | None = None


class Profile(SlackModel):
    display_name: str | None = None
    real_name: str | None = None
    email: str | None = None


class User(SlackModel):
    id: Identifier
    name: str | None = None
    real_name: str | None = None
    profile: Profile = Field(default_factory=Profile)
    is_bot: bool | None = None
    deleted: bool | None = None

    @property
    def display_name(self) -> str:
        return (
            self.profile.display_name
            or self.profile.real_name
            or self.real_name
            or self.name
            or self.id
        )


class MessageAttachment(SlackModel):
    text: str | None = None
    fallback: str | None = None
    title: str | None = None


class MessageFile(SlackModel):
    id: Identifier
    name: str | None = None
    title: str | None = None
    mimetype: str | None = None


class MessageBlock(SlackModel):
    """An unrendered Block Kit tag, not a claim of complete block extraction."""

    type: str = Field(min_length=1)


class Message(SlackModel):
    type: Literal[MessageType.MESSAGE]
    ts: Timestamp
    text: str | None = None
    user: Identifier | None = None
    bot_id: Identifier | None = None
    username: str | None = None
    # Native subtypes are extensible; no platform lifecycle is inferred from them.
    subtype: str | None = None
    thread_ts: Timestamp | None = None
    reply_count: int | None = Field(default=None, ge=0)
    attachments: list[MessageAttachment] = Field(default_factory=list)
    files: list[MessageFile] = Field(default_factory=list)
    blocks: list[MessageBlock] = Field(default_factory=list)


class PostedMessage(SlackModel):
    type: Literal[MessageType.MESSAGE]
    text: str
    ts: Timestamp | None = None
    thread_ts: Timestamp | None = None


class ChannelsResponse(Envelope):
    channels: list[Channel]


class HistoryResponse(Envelope):
    messages: list[Message]
    has_more: bool


class UsersResponse(Envelope):
    members: list[User]


class UserResponse(Envelope):
    user: User


class PostResponse(Envelope):
    channel: ChannelId
    ts: Timestamp
    message: PostedMessage


class PageQuery(SlackRequest):
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    cursor: Cursor | None = None


class ChannelsQuery(PageQuery):
    types: Literal[ConversationType.PUBLIC] = ConversationType.PUBLIC
    exclude_archived: Literal[True] = True


class HistoryQuery(PageQuery):
    channel: ChannelId
    latest: Timestamp | None = None


class EmailQuery(SlackRequest):
    email: str = Field(min_length=3, max_length=320)


class PostRequest(SlackRequest):
    channel: ChannelId
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    thread_ts: Timestamp | None = None


class ChannelView(SlackModel):
    id: ChannelId
    name: str
    is_private: bool
    member_count: int | None
    topic: str | None


class ChannelsView(SlackModel):
    channels: list[ChannelView]
    count: int
    next_cursor: Cursor | None


class PostView(SlackModel):
    channel_id: ChannelId
    ts: Timestamp
    permalink_hint: str
    text: str
    thread_ts: Timestamp | None
    warnings: list[str]


class MessageView(SlackModel):
    ts: Timestamp
    author: str | None
    author_id: Identifier | None
    text: str | None
    subtype: str | None
    thread_ts: Timestamp | None
    reply_count: int | None
    attachments: list[MessageAttachment]
    files: list[MessageFile]
    unrendered_block_types: list[str]


class HistoryView(SlackModel):
    channel_id: ChannelId
    messages: list[MessageView]
    count: int
    next_cursor: Cursor | None
    next_latest: Timestamp | None
    unresolved_author_ids: list[Identifier]


class UserView(SlackModel):
    id: Identifier
    name: str | None
    real_name: str | None
    display_name: str
    email: str | None
    is_bot: bool | None
    deleted: bool | None


ENVELOPE = TypeAdapter(Envelope)
CHANNELS = TypeAdapter(ChannelsResponse)
HISTORY = TypeAdapter(HistoryResponse)
USERS = TypeAdapter(UsersResponse)
USER = TypeAdapter(UserResponse)
POST = TypeAdapter(PostResponse)


def invalid_response() -> NoReturn:
    raise VendorToolError(
        SlackErrorCode.RESPONSE_INVALID,
        "Slack returned an invalid response for the requested operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(SlackErrorCode.REJECTED, "Slack rejected the request.")
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        envelope = ENVELOPE.validate_python(response.data, strict=True)
        if not envelope.ok:
            raise VendorToolError(
                SlackErrorCode.REJECTED,
                "Slack rejected the request. Check connection scopes and channel membership.",
            )
        if envelope.error is not None:
            invalid_response()
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()


def next_cursor(envelope: Envelope, requested: str | None) -> str | None:
    cursor = envelope.response_metadata.next_cursor.strip() or None
    if cursor is not None and cursor == requested:
        invalid_response()
    return cursor
