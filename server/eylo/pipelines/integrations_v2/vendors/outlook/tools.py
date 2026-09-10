"""Typed mailbox reads and receipt-backed mail acceptance over Microsoft Graph."""

import html
import json
import re
from typing import Self
from urllib.parse import quote

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    model_validator,
)

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext
from ...registry import curated_tool
from .definition import MAIL_READ, MAIL_SEND, vendor
from .schemas import (
    DEFAULT_PAGE_SIZE,
    MAX_NEXT_LINK_CHARS,
    MAX_PAGE_SIZE,
    MAX_RECIPIENTS,
    MAX_TEXT_CHARS,
    MESSAGE,
    MESSAGES_PATH,
    PAGES,
    BodyFormat,
    Email,
    EmailAddress,
    FullMessageView,
    ItemBody,
    MessageId,
    MessageOrder,
    MessageSummary,
    MessageView,
    MessageWrite,
    MessagesQuery,
    MessagesView,
    ReadState,
    Recipient,
    ReplyAction,
    ReplyRecipients,
    ReplyRequest,
    ReplyView,
    SendRequest,
    SendView,
    SentCopy,
    continuation_path,
    invalid_response,
    parse_response,
    require_accepted,
)

_TAG = re.compile(r"<[^>]+>")
_RECEIVED_DESCENDING = "receivedDateTime desc"
_SEND_PATH = "/me/sendMail"


class MailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchMessagesInput(MailInput):
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_TEXT_CHARS,
        description="Graph mailbox search expression, across sender, subject and body by default.",
    )
    from_address: Email | None = None
    read_state: ReadState | None = None
    unread_only: StrictBool | None = Field(
        default=None,
        deprecated=True,
        description="Legacy input. Use read_state instead.",
    )
    limit: StrictInt = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    next_page_url: str | None = Field(
        default=None,
        max_length=MAX_NEXT_LINK_CHARS,
        description="Returned continuation URL. Repeat the same search, sender, read state and limit.",
    )

    @model_validator(mode="after")
    def one_read_mode(self) -> Self:
        if self.read_state is not None and self.unread_only is not None:
            raise ValueError("Use read_state or legacy unread_only, not both.")
        return self

    @property
    def selected_read_state(self) -> ReadState:
        return self.read_state or (
            ReadState.UNREAD if self.unread_only else ReadState.ALL
        )


class GetMessageInput(MailInput):
    message_id: MessageId


class SendMessageInput(MailInput):
    to: list[Email] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    subject: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    body: str = Field(
        min_length=1, max_length=MAX_TEXT_CHARS, description="Plain text, not HTML."
    )
    cc: list[Email] | None = Field(default=None, max_length=MAX_RECIPIENTS)
    sent_copy: SentCopy | None = None
    save_to_sent_items: StrictBool | None = Field(
        default=None,
        deprecated=True,
        description="Legacy input. Use sent_copy instead.",
    )

    @model_validator(mode="after")
    def validate_delivery_options(self) -> Self:
        if len(self.to) + len(self.cc or []) > MAX_RECIPIENTS:
            raise ValueError("Too many combined recipients.")
        if self.sent_copy is not None and self.save_to_sent_items is not None:
            raise ValueError("Use sent_copy or legacy save_to_sent_items, not both.")
        return self

    @property
    def selected_sent_copy(self) -> SentCopy:
        return self.sent_copy or (
            SentCopy.OMIT if self.save_to_sent_items is False else SentCopy.KEEP
        )


class ReplyToMessageInput(GetMessageInput):
    body: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    recipients: ReplyRecipients | None = None
    reply_all: StrictBool | None = Field(
        default=None,
        deprecated=True,
        description="Legacy input. Use recipients instead.",
    )

    @model_validator(mode="after")
    def one_reply_mode(self) -> Self:
        if self.recipients is not None and self.reply_all is not None:
            raise ValueError("Use recipients or legacy reply_all, not both.")
        return self

    @property
    def selected_recipients(self) -> ReplyRecipients:
        return self.recipients or (
            ReplyRecipients.ALL if self.reply_all else ReplyRecipients.SENDER
        )


def _query(payload: SearchMessagesInput) -> tuple[MessagesQuery, MessageOrder]:
    filters: list[str] = []
    if payload.from_address:
        sender = payload.from_address.replace("'", "''")
        filters.append(f"from/emailAddress/address eq '{sender}'")
    if payload.selected_read_state != ReadState.ALL:
        filters.append(
            "isRead eq true"
            if payload.selected_read_state == ReadState.READ
            else "isRead eq false"
        )
    if payload.query:
        # Search and OData filters do not compose reliably. Preserve sender/read
        # predicates locally on every page rather than silently dropping them.
        return MessagesQuery(
            top=payload.limit, search=json.dumps(payload.query, ensure_ascii=False)
        ), MessageOrder.SEARCH_SENT_TIME
    if filters:
        # Adding orderby requires matching leading filter properties, otherwise
        # Graph rejects valid sender/read filters as InefficientFilter.
        return MessagesQuery(
            top=payload.limit, filter=" and ".join(filters)
        ), MessageOrder.VENDOR
    return MessagesQuery(
        top=payload.limit, order_by=_RECEIVED_DESCENDING
    ), MessageOrder.RECEIVED_DESCENDING


def _matches(message: MessageSummary, payload: SearchMessagesInput) -> bool:
    sender = message.from_.email_address.address if message.from_ else None
    if payload.from_address and (
        sender is None or sender.casefold() != payload.from_address.casefold()
    ):
        return False
    state = payload.selected_read_state
    return state == ReadState.ALL or message.is_read == (state == ReadState.READ)


def _message_view(message: MessageSummary) -> MessageView:
    return MessageView(
        id=message.id,
        subject=message.subject,
        from_=message.from_.email_address.address if message.from_ else None,
        to=[recipient.email_address.address for recipient in message.to_recipients],
        cc=[recipient.email_address.address for recipient in message.cc_recipients],
        received_at=message.received_at,
        is_read=message.is_read,
        has_attachments=message.has_attachments,
        conversation_id=message.conversation_id,
        preview=message.preview,
        web_link=message.web_link,
    )


@curated_tool(
    vendor=vendor.vendor,
    name="search_messages",
    display_name="Search Outlook Messages",
    description="Search mailbox messages by text, sender and read state. Returns one page and next_page_url; repeat unchanged options to continue, even after an empty filtered page. With text search, sender/read filters apply to each returned page, and Graph limits search to 1000 results. Ordering is reported explicitly. Fetch a message for its full body.",
    input_model=SearchMessagesInput,
    effect=ToolEffect.READ,
    scopes=(MAIL_READ,),
)
async def search_messages(
    payload: SearchMessagesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    query, ordering = _query(payload)
    if payload.next_page_url:
        response = await ctx.read(continuation_path(payload.next_page_url, query))
    else:
        response = await ctx.read(
            MESSAGES_PATH,
            query=query.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
    page = parse_response(response, PAGES)
    if len(page.value) > payload.limit:
        invalid_response()
    if page.next_link:
        continuation_path(page.next_link, query)
        if page.next_link == payload.next_page_url:
            invalid_response()
    messages = [
        _message_view(message) for message in page.value if _matches(message, payload)
    ]
    return MessagesView(
        messages=messages,
        count=len(messages),
        next_page_url=page.next_link,
        ordering=ordering,
    ).model_dump(mode="json", by_alias=True)


@curated_tool(
    vendor=vendor.vendor,
    name="get_message",
    display_name="Get Outlook Message",
    description="Read one mailbox message in full as text. Plain-text content is preserved; if Graph returns HTML despite the text preference, basic tags are removed. Attachments are not downloaded.",
    input_model=GetMessageInput,
    effect=ToolEffect.READ,
    scopes=(MAIL_READ,),
)
async def get_message(
    payload: GetMessageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    response = await ctx.read(f"{MESSAGES_PATH}/{quote(payload.message_id, safe='')}")
    message = parse_response(response, MESSAGE)
    if message.id != payload.message_id:
        invalid_response()
    body = message.body.content
    if message.body.content_type == BodyFormat.HTML:
        body = re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", body))).strip()
    return FullMessageView(
        **_message_view(message).model_dump(),
        body=body,
        source_body_format=message.body.content_type,
    ).model_dump(mode="json", by_alias=True)


def _recipients(addresses: list[str]) -> list[Recipient]:
    return [Recipient(emailAddress=EmailAddress(address=value)) for value in addresses]


@curated_tool(
    vendor=vendor.vendor,
    name="send_message",
    display_name="Send Outlook Message",
    description="Submit plain-text email to Graph. A successful result means accepted for processing, not delivered. No message ID or delivery confirmation is returned. Do not retry an uncertain submission; it may already have been accepted.",
    input_model=SendMessageInput,
    effect=ToolEffect.MUTATION,
    scopes=(MAIL_SEND,),
)
async def send_message(
    payload: SendMessageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    request = SendRequest(
        message=MessageWrite(
            subject=payload.subject,
            body=ItemBody(contentType=BodyFormat.TEXT, content=payload.body),
            toRecipients=_recipients(payload.to),
            ccRecipients=_recipients(payload.cc or []),
        ),
        saveToSentItems=payload.selected_sent_copy == SentCopy.KEEP,
    )
    response = await ctx.mutate(
        _SEND_PATH,
        method="POST",
        json=request.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
    require_accepted(response)
    return SendView(
        subject=payload.subject,
        to=payload.to,
        cc=payload.cc or [],
        sent_copy=payload.selected_sent_copy,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="reply_to_message",
    display_name="Reply To Outlook Message",
    description="Submit a plain-text reply to the sender or all recipients. Outlook handles threading. Success means accepted, not delivered; do not retry an uncertain submission.",
    input_model=ReplyToMessageInput,
    effect=ToolEffect.MUTATION,
    scopes=(MAIL_SEND, MAIL_READ),
)
async def reply_to_message(
    payload: ReplyToMessageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    action = (
        ReplyAction.ALL
        if payload.selected_recipients == ReplyRecipients.ALL
        else ReplyAction.SENDER
    )
    request = ReplyRequest(comment=payload.body)
    response = await ctx.mutate(
        f"{MESSAGES_PATH}/{quote(payload.message_id, safe='')}/{action}",
        method="POST",
        json=request.model_dump(mode="json"),
    )
    require_accepted(response)
    return ReplyView(
        message_id=payload.message_id, recipients=payload.selected_recipients
    ).model_dump(mode="json")


__all__ = ["get_message", "reply_to_message", "search_messages", "send_message"]
