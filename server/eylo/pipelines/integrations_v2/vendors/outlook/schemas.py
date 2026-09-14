"""Microsoft Graph v1 mail contracts and pinned continuation validation."""

from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from eylo.common.http_egress import (
    HttpEgressPolicyError,
    HttpOrigin,
    parse_https_target,
)

from ...contracts import VendorResponse, VendorToolError

GRAPH_ORIGIN = "https://graph.microsoft.com"
API_PREFIX = "/v1.0"
MESSAGES_PATH = "/me/messages"
BODY_PREFERENCE = 'outlook.body-content-type="text"'
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
MAX_RECIPIENTS = 500
MAX_NEXT_LINK_CHARS = 16_384
MAX_TEXT_CHARS = 100_000
MESSAGE_FIELDS = "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,conversationId,webLink,bodyPreview"


class OutlookErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    CONTINUATION_INVALID = "mail_continuation_invalid"


class BodyFormat(StrEnum):
    TEXT = "text"
    HTML = "html"


class ReadState(StrEnum):
    ALL = "all"
    READ = "read"
    UNREAD = "unread"


class SentCopy(StrEnum):
    KEEP = "keep"
    OMIT = "omit"


class ReplyRecipients(StrEnum):
    SENDER = "sender"
    ALL = "all"


class ReplyAction(StrEnum):
    SENDER = "reply"
    ALL = "replyAll"


class SendState(StrEnum):
    ACCEPTED = "accepted"


class MessageOrder(StrEnum):
    RECEIVED_DESCENDING = "received_descending"
    SEARCH_SENT_TIME = "search_sent_time"
    VENDOR = "vendor"


class QueryKey(StrEnum):
    TOP = "$top"
    SELECT = "$select"
    SEARCH = "$search"
    FILTER = "$filter"
    ORDER_BY = "$orderby"
    SKIP = "$skip"
    SKIP_TOKEN = "$skiptoken"


def address(value: str) -> str:
    value = value.strip()
    if not value or any(char in value for char in "\r\n\x00") or "@" not in value:
        raise ValueError("A recipient requires a plain email address.")
    if (
        value.count("@") != 1
        or any(char.isspace() for char in value)
        or any(char in value for char in "<>,;")
    ):
        raise ValueError(
            "Supply one email address, not a display name or address list."
        )
    local, domain = value.rsplit("@", 1)
    if not local or not domain:
        raise ValueError("Email address requires a local part and domain.")
    return value


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.utcoffset() is None:
        raise ValueError("Graph timestamps must include a timezone.")
    return value


Email = Annotated[str, Field(max_length=320), AfterValidator(address)]
MessageId = Annotated[str, Field(min_length=1, max_length=4_096)]
Timestamp = Annotated[str, AfterValidator(timestamp)]
NativeBodyFormat = Annotated[
    BodyFormat,
    BeforeValidator(
        lambda value: BodyFormat(value.casefold()) if isinstance(value, str) else value
    ),
]


class GraphModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )


class GraphRequest(GraphModel):
    model_config = ConfigDict(extra="forbid")


class EmailAddress(GraphModel):
    address: str
    name: str | None = None


class Recipient(GraphModel):
    email_address: EmailAddress = Field(
        validation_alias="emailAddress", serialization_alias="emailAddress"
    )


class ItemBody(GraphModel):
    content_type: NativeBodyFormat = Field(
        validation_alias="contentType", serialization_alias="contentType"
    )
    content: str


class MessageSummary(GraphModel):
    id: MessageId
    subject: str | None
    from_: Recipient | None = Field(
        default=None, validation_alias="from", serialization_alias="from"
    )
    to_recipients: list[Recipient] = Field(
        validation_alias="toRecipients", serialization_alias="toRecipients"
    )
    cc_recipients: list[Recipient] = Field(
        validation_alias="ccRecipients", serialization_alias="ccRecipients"
    )
    received_at: Timestamp | None = Field(
        validation_alias="receivedDateTime", serialization_alias="receivedDateTime"
    )
    is_read: bool = Field(validation_alias="isRead", serialization_alias="isRead")
    has_attachments: bool = Field(
        validation_alias="hasAttachments", serialization_alias="hasAttachments"
    )
    conversation_id: str | None = Field(
        validation_alias="conversationId", serialization_alias="conversationId"
    )
    web_link: str | None = Field(
        validation_alias="webLink", serialization_alias="webLink"
    )
    preview: str | None = Field(
        validation_alias="bodyPreview", serialization_alias="bodyPreview"
    )


class Message(MessageSummary):
    body: ItemBody


class MessagesPage(GraphModel):
    value: list[MessageSummary]
    next_link: str | None = Field(
        default=None,
        validation_alias="@odata.nextLink",
        serialization_alias="@odata.nextLink",
        max_length=MAX_NEXT_LINK_CHARS,
    )


class GraphError(GraphModel):
    code: str
    message: str


class GraphErrorEnvelope(GraphModel):
    error: GraphError | None = None


class MessagesQuery(GraphRequest):
    top: int = Field(
        ge=1,
        le=MAX_PAGE_SIZE,
        validation_alias=QueryKey.TOP,
        serialization_alias=QueryKey.TOP,
    )
    select: str = Field(
        default=MESSAGE_FIELDS,
        validation_alias=QueryKey.SELECT,
        serialization_alias=QueryKey.SELECT,
    )
    search: str | None = Field(
        default=None,
        validation_alias=QueryKey.SEARCH,
        serialization_alias=QueryKey.SEARCH,
    )
    filter: str | None = Field(
        default=None,
        validation_alias=QueryKey.FILTER,
        serialization_alias=QueryKey.FILTER,
    )
    order_by: str | None = Field(
        default=None,
        validation_alias=QueryKey.ORDER_BY,
        serialization_alias=QueryKey.ORDER_BY,
    )


class MessageWrite(GraphRequest):
    subject: str
    body: ItemBody
    to_recipients: list[Recipient] = Field(
        validation_alias="toRecipients",
        serialization_alias="toRecipients",
        min_length=1,
        max_length=MAX_RECIPIENTS,
    )
    cc_recipients: list[Recipient] = Field(
        default_factory=list,
        validation_alias="ccRecipients",
        serialization_alias="ccRecipients",
        max_length=MAX_RECIPIENTS,
    )


class SendRequest(GraphRequest):
    message: MessageWrite
    save_to_sent_items: bool = Field(
        validation_alias="saveToSentItems", serialization_alias="saveToSentItems"
    )


class ReplyRequest(GraphRequest):
    comment: str


class MessageView(GraphModel):
    id: MessageId
    subject: str | None
    from_: Annotated[
        str | None, Field(validation_alias="from", serialization_alias="from")
    ]
    to: list[str]
    cc: list[str]
    received_at: str | None
    is_read: bool
    has_attachments: bool
    conversation_id: str | None
    preview: str | None
    web_link: str | None


class FullMessageView(MessageView):
    body: str
    source_body_format: BodyFormat


class MessagesView(GraphModel):
    messages: list[MessageView]
    count: int
    next_page_url: str | None
    ordering: MessageOrder


class SendView(GraphModel):
    state: Literal[SendState.ACCEPTED] = SendState.ACCEPTED
    subject: str
    to: list[str]
    cc: list[str]
    sent_copy: SentCopy


class ReplyView(GraphModel):
    state: Literal[SendState.ACCEPTED] = SendState.ACCEPTED
    message_id: MessageId
    recipients: ReplyRecipients


PAGES = TypeAdapter(MessagesPage)
MESSAGE = TypeAdapter(Message)
ERROR = TypeAdapter(GraphErrorEnvelope)


def invalid_response() -> NoReturn:
    raise VendorToolError(
        OutlookErrorCode.RESPONSE_INVALID,
        "Microsoft Graph returned an invalid response for this operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            OutlookErrorCode.REJECTED, "Microsoft Graph rejected the request."
        )
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        if ERROR.validate_python(response.data).error is not None:
            raise VendorToolError(
                OutlookErrorCode.REJECTED, "Microsoft Graph rejected the request."
            )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()


def require_accepted(response: VendorResponse) -> None:
    """A 202 is acceptance only, not completion or delivery; body must be empty."""
    if not response.ok:
        raise VendorToolError(
            OutlookErrorCode.REJECTED, "Microsoft Graph rejected the mail operation."
        )
    if response.status_code != HTTPStatus.ACCEPTED or response.data is not None:
        invalid_response()


def continuation_path(url: str, query: MessagesQuery) -> str:
    """Validate, then preserve the complete query; never compute a new skip token."""
    try:
        origin, path = parse_https_target(url)
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        values = dict(pairs)
        expected = {
            key: str(value)
            for key, value in query.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ).items()
        }
        continuation_keys = {QueryKey.SKIP, QueryKey.SKIP_TOKEN}
        if (
            len(url) > MAX_NEXT_LINK_CHARS
            or origin != HttpOrigin.parse(GRAPH_ORIGIN)
            or path != API_PREFIX + MESSAGES_PATH
            or parts.fragment
            or len(pairs) != len(values)
            or set(values) - set(expected) - continuation_keys
            or any(values.get(key) != value for key, value in expected.items())
            or not any(values.get(key) for key in continuation_keys)
        ):
            raise ValueError("Unrecognized mailbox continuation.")
    except (ValueError, HttpEgressPolicyError):
        raise VendorToolError(
            OutlookErrorCode.CONTINUATION_INVALID,
            "Continue with the returned mailbox URL and unchanged search options.",
        ) from None
    return f"{MESSAGES_PATH}?{parts.query}"
