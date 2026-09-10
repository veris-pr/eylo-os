"""Gmail-native mail, MIME, label and request contracts; no platform persistence."""

from email.errors import HeaderParseError
from email.headerregistry import Address
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from ...contracts import VendorResponse, VendorToolError

ME = "/users/me"
MAX_PAGE_SIZE = 25
DEFAULT_PAGE_SIZE = 10
MAX_THREAD_PAGE_SIZE = 50
MAX_BODY_CHARS = 8_000
MAX_INPUT_CHARS = 100_000
MAX_RECIPIENTS = 500
MAX_LABEL_CHANGES = 100
MAX_MIME_PARTS = 256
MAX_BODY_FETCHES = 10


class GmailErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    BODY_INVALID = "mail_body_invalid"
    BODY_TOO_COMPLEX = "mail_body_too_complex"
    THREAD_EMPTY = "thread_empty"
    THREAD_MISMATCH = "mail_thread_mismatch"
    REPLY_TARGET_UNKNOWN = "reply_target_unknown"
    THREAD_HEADERS_MISSING = "mail_thread_headers_missing"
    LABEL_NOT_FOUND = "label_not_found"
    LABEL_AMBIGUOUS = "label_ambiguous"
    LABEL_CONFLICT = "label_conflict"
    CONTINUATION_INVALID = "mail_continuation_invalid"


class MailboxRange(StrEnum):
    STANDARD = "standard"
    INCLUDE_SPAM_TRASH = "include_spam_trash"


class ReplyRecipients(StrEnum):
    SENDER = "sender"
    ALL = "all"


class MissingLabels(StrEnum):
    REJECT = "reject"
    CREATE = "create"


class MessageFormat(StrEnum):
    METADATA = "metadata"
    FULL = "full"


class BodyFormat(StrEnum):
    TEXT = "text"
    HTML = "html"
    NONE = "none"


class BodyState(StrEnum):
    AVAILABLE = "available"
    EMPTY = "empty"
    UNSUPPORTED = "unsupported"


class MailOutcome(StrEnum):
    SUBMITTED = "submitted"
    DRAFTED = "drafted"
    LABELS_UPDATED = "labels_updated"
    TRASHED = "trashed"


class HeaderName(StrEnum):
    FROM = "From"
    TO = "To"
    CC = "Cc"
    BCC = "Bcc"
    SUBJECT = "Subject"
    DATE = "Date"
    REPLY_TO = "Reply-To"
    MESSAGE_ID = "Message-ID"
    IN_REPLY_TO = "In-Reply-To"
    REFERENCES = "References"
    CONTENT_TYPE = "Content-Type"
    CONTENT_DISPOSITION = "Content-Disposition"


class MimeType(StrEnum):
    TEXT = "text/plain"
    HTML = "text/html"
    ALTERNATIVE = "multipart/alternative"


class SystemLabel(StrEnum):
    CHAT = "CHAT"
    DRAFT = "DRAFT"
    IMPORTANT = "IMPORTANT"
    INBOX = "INBOX"
    SENT = "SENT"
    SPAM = "SPAM"
    STARRED = "STARRED"
    TRASH = "TRASH"
    UNREAD = "UNREAD"
    CATEGORY_PERSONAL = "CATEGORY_PERSONAL"
    CATEGORY_SOCIAL = "CATEGORY_SOCIAL"
    CATEGORY_PROMOTIONS = "CATEGORY_PROMOTIONS"
    CATEGORY_UPDATES = "CATEGORY_UPDATES"
    CATEGORY_FORUMS = "CATEGORY_FORUMS"


class LabelType(StrEnum):
    USER = "user"
    SYSTEM = "system"


class LabelVisibility(StrEnum):
    SHOW = "labelShow"


class MessageVisibility(StrEnum):
    SHOW = "show"


def address(value: str) -> str:
    value = value.strip()
    if any(char in value for char in "\r\n\x00"):
        raise ValueError("Supply a plain email address.")
    try:
        parsed = Address(addr_spec=value)
    except (HeaderParseError, ValueError):
        raise ValueError("Supply one valid plain email address.") from None
    if not parsed.username or not parsed.domain:
        raise ValueError("Email address requires a local part and domain.")
    return value


def header(value: str) -> str:
    if any(char in value for char in "\r\n\x00"):
        raise ValueError("Mail header values cannot contain newlines or NUL.")
    return value


def label_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Label name or ID is required.")
    return value


Identifier = Annotated[str, Field(min_length=1, max_length=4_096)]
Email = Annotated[str, Field(max_length=320), AfterValidator(address)]
HeaderText = Annotated[str, Field(max_length=MAX_INPUT_CHARS), AfterValidator(header)]
LabelName = Annotated[str, Field(max_length=225), AfterValidator(label_name)]
InternalDate = Annotated[str, Field(pattern=r"^[0-9]+$", max_length=19)]
NativeLabelType = Annotated[
    LabelType,
    BeforeValidator(
        lambda value: LabelType(value) if isinstance(value, str) else value
    ),
]


class GmailModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class GmailRequest(GmailModel):
    model_config = ConfigDict(extra="forbid")


class Header(GmailModel):
    name: str
    value: str


class PartBody(GmailModel):
    size: int = Field(default=0, ge=0)
    data: str | None = None
    attachmentId: Identifier | None = None


class MimePart(GmailModel):
    partId: str = ""
    mimeType: str = Field(min_length=1)
    filename: str = ""
    headers: list[Header] = Field(default_factory=list)
    body: PartBody = Field(default_factory=PartBody)
    parts: list["MimePart"] = Field(default_factory=list)


class MetadataPayload(GmailModel):
    headers: list[Header] = Field(default_factory=list)


class MessageIdentity(GmailModel):
    id: Identifier
    threadId: Identifier


class MessageAck(MessageIdentity):
    labelIds: list[Identifier] = Field(default_factory=list)


class MetadataMessage(MessageAck):
    payload: MetadataPayload
    snippet: str = ""
    internalDate: InternalDate


class FullMessage(MessageAck):
    payload: MimePart
    snippet: str = ""
    internalDate: InternalDate


class MessagePage(GmailModel):
    # Google JSON omits empty repeated fields, unlike an absent single entity.
    messages: list[MessageIdentity] = Field(default_factory=list)
    nextPageToken: Identifier | None = None
    resultSizeEstimate: int = Field(default=0, ge=0)


class Thread(GmailModel):
    id: Identifier
    messages: list[FullMessage] = Field(default_factory=list)


class Draft(GmailModel):
    id: Identifier
    message: MessageAck


class Label(GmailModel):
    id: Identifier
    name: str
    type: NativeLabelType


class Labels(GmailModel):
    labels: list[Label] = Field(default_factory=list)


class Profile(GmailModel):
    emailAddress: Email


class GoogleError(GmailModel):
    code: int
    message: str


class ErrorEnvelope(GmailModel):
    error: GoogleError | None = None


class SearchQuery(GmailRequest):
    maxResults: int
    includeSpamTrash: bool
    q: str | None = None
    pageToken: str | None = None


class ReadQuery(GmailRequest):
    format: MessageFormat
    metadataHeaders: list[str] | None = None


class RawMessage(GmailRequest):
    raw: str
    threadId: str | None = None


class DraftRequest(GmailRequest):
    message: RawMessage


class LabelsRequest(GmailRequest):
    addLabelIds: list[str]
    removeLabelIds: list[str]


class LabelCreate(GmailRequest):
    name: str
    labelListVisibility: LabelVisibility = LabelVisibility.SHOW
    messageListVisibility: MessageVisibility = MessageVisibility.SHOW


class MailHeaders(GmailModel):
    sender: str | None
    to: str | None
    cc: str | None
    subject: str | None
    date: str | None
    reply_to: str | None
    message_id: str | None
    references: str | None


class AttachmentView(GmailModel):
    filename: str
    mime_type: str
    size_bytes: int
    attachment_id: str | None


class DecodedBody(GmailModel):
    text: str
    format: BodyFormat
    state: BodyState
    attachments: list[AttachmentView]
    unsupported_mime_types: list[str]


class MessageView(GmailModel):
    id: str
    thread_id: str
    from_: Annotated[str | None, Field(serialization_alias="from")]
    to: str | None
    cc: str | None
    subject: str | None
    date: str | None
    snippet: str
    labels: list[str]
    unread: bool


class FullMessageView(MessageView):
    body: str
    body_format: BodyFormat
    body_state: BodyState
    body_offset: int
    body_total_chars: int
    next_body_offset: int | None
    body_truncated: bool
    attachments: list[AttachmentView]
    unsupported_mime_types: list[str]


class SearchView(GmailModel):
    messages: list[MessageView]
    count: int
    result_size_estimate: int
    next_page_token: str | None


class ThreadView(GmailModel):
    thread_id: str
    messages: list[FullMessageView]
    count: int
    total_in_thread: int
    next_before_message_id: str | None


class MutationView(GmailModel):
    message_id: str
    thread_id: str
    labels: list[str]
    state: MailOutcome


class ReplyView(MutationView):
    replied_to: list[str]
    copied: list[str]


class DraftView(GmailModel):
    draft_id: str
    message_id: str
    thread_id: str
    state: Literal[MailOutcome.DRAFTED] = MailOutcome.DRAFTED


class LabelSelection(GmailModel):
    name: str
    id: str | None


MESSAGE_PAGE = TypeAdapter(MessagePage)
METADATA = TypeAdapter(MetadataMessage)
MESSAGE = TypeAdapter(FullMessage)
ACK = TypeAdapter(MessageAck)
THREAD = TypeAdapter(Thread)
DRAFT = TypeAdapter(Draft)
LABEL = TypeAdapter(Label)
LABELS = TypeAdapter(Labels)
PROFILE = TypeAdapter(Profile)
ERROR = TypeAdapter(ErrorEnvelope)


def invalid_response() -> NoReturn:
    raise VendorToolError(
        GmailErrorCode.RESPONSE_INVALID,
        "Gmail returned an invalid response for this operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(GmailErrorCode.REJECTED, "Gmail rejected the request.")
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        if ERROR.validate_python(response.data).error is not None:
            raise VendorToolError(
                GmailErrorCode.REJECTED, "Gmail rejected the request."
            )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()
