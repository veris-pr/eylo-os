"""Curated Gmail workflows with native contracts, MIME handling and receipt-owned writes."""

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

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import GMAIL_COMPOSE, GMAIL_MODIFY, GMAIL_SEND, vendor
from .mime import addresses, build_message, headers, read_body, threading_headers
from .schemas import (
    ACK,
    DEFAULT_PAGE_SIZE,
    DRAFT,
    LABEL,
    LABELS,
    MAX_BODY_CHARS,
    MAX_INPUT_CHARS,
    MAX_LABEL_CHANGES,
    MAX_PAGE_SIZE,
    MAX_RECIPIENTS,
    MAX_THREAD_PAGE_SIZE,
    ME,
    MESSAGE,
    MESSAGE_PAGE,
    METADATA,
    PROFILE,
    THREAD,
    DraftRequest,
    DraftView,
    Email,
    FullMessage,
    FullMessageView,
    GmailErrorCode,
    HeaderName,
    HeaderText,
    Identifier,
    LabelCreate,
    LabelName,
    LabelSelection,
    LabelType,
    LabelsRequest,
    MailOutcome,
    MailboxRange,
    MessageAck,
    MessageFormat,
    MessageView,
    MetadataMessage,
    MissingLabels,
    MutationView,
    RawMessage,
    ReadQuery,
    ReplyRecipients,
    ReplyView,
    SearchQuery,
    SearchView,
    SystemLabel,
    Thread,
    ThreadView,
    invalid_response,
    parse_response,
)

_METADATA_HEADERS = [
    HeaderName.FROM,
    HeaderName.TO,
    HeaderName.CC,
    HeaderName.SUBJECT,
    HeaderName.DATE,
]
_NON_EDITABLE_LABELS = {SystemLabel.DRAFT, SystemLabel.SENT, SystemLabel.CHAT}


class MailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchMessagesInput(MailInput):
    query: str | None = Field(
        default=None,
        max_length=MAX_INPUT_CHARS,
        description="Native Gmail search expression.",
    )
    limit: StrictInt = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="One metadata lookup per returned message.",
    )
    mailbox_range: MailboxRange | None = None
    include_spam_trash: StrictBool | None = Field(
        default=None, deprecated=True, description="Legacy input. Use mailbox_range."
    )
    page_token: Identifier | None = Field(
        default=None, description="Use next_page_token with the same search options."
    )

    @model_validator(mode="after")
    def one_range(self) -> Self:
        if self.mailbox_range is not None and self.include_spam_trash is not None:
            raise ValueError(
                "Use mailbox_range or legacy include_spam_trash, not both."
            )
        return self

    @property
    def selected_range(self) -> MailboxRange:
        return self.mailbox_range or (
            MailboxRange.INCLUDE_SPAM_TRASH
            if self.include_spam_trash
            else MailboxRange.STANDARD
        )


class ReadMessageInput(MailInput):
    message_id: Identifier
    body_offset: StrictInt = Field(
        default=0,
        ge=0,
        description="Character offset; use next_body_offset to continue a long body.",
    )


class ReadThreadInput(MailInput):
    thread_id: Identifier
    max_messages: StrictInt = Field(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_THREAD_PAGE_SIZE
    )
    before_message_id: Identifier | None = Field(
        default=None,
        description="Use next_before_message_id to read earlier messages in the same thread.",
    )


class SendMessageInput(MailInput):
    to: list[Email] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    subject: HeaderText = Field(min_length=1)
    body: str = Field(max_length=MAX_INPUT_CHARS)
    cc: list[Email] | None = Field(default=None, max_length=MAX_RECIPIENTS)
    bcc: list[Email] | None = Field(default=None, max_length=MAX_RECIPIENTS)
    html_body: str | None = Field(default=None, max_length=MAX_INPUT_CHARS)

    @model_validator(mode="after")
    def recipient_budget(self) -> Self:
        if len(self.to) + len(self.cc or []) + len(self.bcc or []) > MAX_RECIPIENTS:
            raise ValueError("Too many combined recipients.")
        return self


class ReplyToThreadInput(MailInput):
    thread_id: Identifier
    body: str = Field(max_length=MAX_INPUT_CHARS)
    recipients: ReplyRecipients | None = None
    reply_all: StrictBool | None = Field(
        default=None, deprecated=True, description="Legacy input. Use recipients."
    )
    html_body: str | None = Field(default=None, max_length=MAX_INPUT_CHARS)

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


class CreateDraftInput(MailInput):
    to: list[Email] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    subject: HeaderText = Field(min_length=1)
    body: str = Field(max_length=MAX_INPUT_CHARS)
    cc: list[Email] | None = Field(default=None, max_length=MAX_RECIPIENTS)
    thread_id: Identifier | None = None

    @model_validator(mode="after")
    def recipient_budget(self) -> Self:
        if len(self.to) + len(self.cc or []) > MAX_RECIPIENTS:
            raise ValueError("Too many combined recipients.")
        return self


class ModifyLabelsInput(MailInput):
    message_id: Identifier
    add: list[LabelName] | None = Field(default=None, max_length=MAX_LABEL_CHANGES)
    remove: list[LabelName] | None = Field(default=None, max_length=MAX_LABEL_CHANGES)
    missing_labels: MissingLabels | None = None
    create_missing: StrictBool | None = Field(
        default=None, deprecated=True, description="Legacy input. Use missing_labels."
    )

    @model_validator(mode="after")
    def label_change(self) -> Self:
        if not self.add and not self.remove:
            raise ValueError("Give at least one label to add or remove.")
        if self.missing_labels is not None and self.create_missing is not None:
            raise ValueError("Use missing_labels or legacy create_missing, not both.")
        if set(self.add or []) & set(self.remove or []):
            raise ValueError("The same label cannot be added and removed.")
        return self

    @property
    def selected_missing_labels(self) -> MissingLabels:
        return self.missing_labels or (
            MissingLabels.CREATE if self.create_missing else MissingLabels.REJECT
        )


class TrashMessageInput(MailInput):
    message_id: Identifier


def _message_path(identifier: str) -> str:
    return f"{ME}/messages/{quote(identifier, safe='')}"


def _view(message: MetadataMessage | FullMessage) -> MessageView:
    mail = headers(message.payload.headers)
    return MessageView(
        id=message.id,
        thread_id=message.threadId,
        from_=mail.sender,
        to=mail.to,
        cc=mail.cc,
        subject=mail.subject,
        date=mail.date,
        snippet=message.snippet,
        labels=message.labelIds,
        unread=SystemLabel.UNREAD in message.labelIds,
    )


async def _full_view(
    message: FullMessage, ctx: VendorToolContext, offset: int = 0
) -> FullMessageView:
    decoded = await read_body(message.id, message.payload, ctx)
    if offset > len(decoded.text):
        raise VendorToolError(
            GmailErrorCode.CONTINUATION_INVALID,
            "Body offset is beyond the current message body.",
        )
    end = offset + MAX_BODY_CHARS
    return FullMessageView(
        **_view(message).model_dump(),
        body=decoded.text[offset:end],
        body_format=decoded.format,
        body_state=decoded.state,
        body_offset=offset,
        body_total_chars=len(decoded.text),
        next_body_offset=end if end < len(decoded.text) else None,
        body_truncated=offset > 0 or end < len(decoded.text),
        attachments=decoded.attachments,
        unsupported_mime_types=decoded.unsupported_mime_types,
    )


async def _thread(ctx: VendorToolContext, thread_id: str) -> Thread:
    response = await ctx.read(
        f"{ME}/threads/{quote(thread_id, safe='')}",
        query=ReadQuery(format=MessageFormat.FULL).model_dump(
            mode="json", exclude_none=True
        ),
    )
    thread = parse_response(response, THREAD)
    if (
        thread.id != thread_id
        or any(message.threadId != thread_id for message in thread.messages)
        or len({message.id for message in thread.messages}) != len(thread.messages)
    ):
        invalid_response()
    return thread


def _ordered(thread: Thread) -> list[FullMessage]:
    return sorted(thread.messages, key=lambda message: int(message.internalDate))


def _parent(thread: Thread) -> FullMessage:
    messages = [
        message
        for message in _ordered(thread)
        if SystemLabel.DRAFT not in message.labelIds
    ]
    if not messages:
        raise VendorToolError(
            GmailErrorCode.THREAD_EMPTY,
            "That thread has no non-draft message to reply to.",
        )
    return messages[-1]


def _ack_view(message: MessageAck, state: MailOutcome) -> MutationView:
    return MutationView(
        message_id=message.id,
        thread_id=message.threadId,
        labels=message.labelIds,
        state=state,
    )


@curated_tool(
    vendor=vendor.vendor,
    name="search_messages",
    display_name="Search Gmail",
    description="Search with Gmail's query syntax. Returns one page of sender/recipient/subject metadata and next_page_token; repeat unchanged options to continue. Each returned message requires one bounded metadata lookup. Result size is an estimate, not an exact count.",
    input_model=SearchMessagesInput,
    effect=ToolEffect.READ,
    scopes=(GMAIL_MODIFY,),
)
async def search_messages(
    payload: SearchMessagesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    query = SearchQuery(
        maxResults=payload.limit,
        includeSpamTrash=payload.selected_range == MailboxRange.INCLUDE_SPAM_TRASH,
        q=payload.query,
        pageToken=payload.page_token,
    )
    listing = parse_response(
        await ctx.read(
            f"{ME}/messages", query=query.model_dump(mode="json", exclude_none=True)
        ),
        MESSAGE_PAGE,
    )
    if len(listing.messages) > payload.limit or len(
        {message.id for message in listing.messages}
    ) != len(listing.messages):
        invalid_response()
    if (
        listing.nextPageToken is not None
        and listing.nextPageToken == payload.page_token
    ):
        invalid_response()
    messages: list[MessageView] = []
    for stub in listing.messages:
        query = ReadQuery(
            format=MessageFormat.METADATA, metadataHeaders=list(_METADATA_HEADERS)
        )
        detail = parse_response(
            await ctx.read(
                _message_path(stub.id),
                query=query.model_dump(mode="json", exclude_none=True),
            ),
            METADATA,
        )
        if detail.id != stub.id or detail.threadId != stub.threadId:
            invalid_response()
        messages.append(_view(detail))
    return SearchView(
        messages=messages,
        count=len(messages),
        result_size_estimate=listing.resultSizeEstimate,
        next_page_token=listing.nextPageToken,
    ).model_dump(mode="json", by_alias=True)


@curated_tool(
    vendor=vendor.vendor,
    name="read_message",
    display_name="Read Gmail Message",
    description="Read a message's decoded MIME body and attachment metadata. Body excerpts expose next_body_offset for continuation. Text attachments are not mistaken for body text; named attachments are not downloaded. Externally stored body parts are fetched under a bounded budget. Invalid encoding is an error, not empty content; unsupported MIME types are explicit.",
    input_model=ReadMessageInput,
    effect=ToolEffect.READ,
    scopes=(GMAIL_MODIFY,),
)
async def read_message(
    payload: ReadMessageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    message = parse_response(
        await ctx.read(
            _message_path(payload.message_id),
            query=ReadQuery(format=MessageFormat.FULL).model_dump(
                mode="json", exclude_none=True
            ),
        ),
        MESSAGE,
    )
    if message.id != payload.message_id:
        invalid_response()
    return (await _full_view(message, ctx, payload.body_offset)).model_dump(
        mode="json", by_alias=True
    )


@curated_tool(
    vendor=vendor.vendor,
    name="read_thread",
    display_name="Read Gmail Thread",
    description="Read a page of thread messages ordered by Gmail internal time. Initially returns the latest messages; use next_before_message_id for earlier pages. Each body is a bounded excerpt; read_message continues long bodies. This does not silently claim an excerpt is the whole thread.",
    input_model=ReadThreadInput,
    effect=ToolEffect.READ,
    scopes=(GMAIL_MODIFY,),
)
async def read_thread(
    payload: ReadThreadInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    thread = await _thread(ctx, payload.thread_id)
    messages = _ordered(thread)
    end = len(messages)
    if payload.before_message_id is not None:
        indexes = [
            index
            for index, message in enumerate(messages)
            if message.id == payload.before_message_id
        ]
        if not indexes:
            raise VendorToolError(
                GmailErrorCode.CONTINUATION_INVALID,
                "The continuation message is not in this thread.",
            )
        end = indexes[0]
    start = max(0, end - payload.max_messages)
    selected = messages[start:end]
    views = [await _full_view(message, ctx) for message in selected]
    return ThreadView(
        thread_id=thread.id,
        messages=views,
        count=len(views),
        total_in_thread=len(messages),
        next_before_message_id=selected[0].id if start and selected else None,
    ).model_dump(mode="json", by_alias=True)


@curated_tool(
    vendor=vendor.vendor,
    name="send_message",
    display_name="Send Gmail Message",
    description="Submit a new email from plain recipients and text, optionally an HTML alternative. Returns Gmail message/thread identity, not delivery confirmation. Use reply_to_thread for existing conversations. Do not retry uncertain submissions.",
    input_model=SendMessageInput,
    effect=ToolEffect.MUTATION,
    scopes=(GMAIL_SEND,),
)
async def send_message(
    payload: SendMessageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    raw = build_message(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        cc=payload.cc,
        bcc=payload.bcc,
        html_body=payload.html_body,
    )
    request = RawMessage(raw=raw)
    message = parse_response(
        await ctx.mutate(
            f"{ME}/messages/send",
            json=request.model_dump(mode="json", exclude_none=True),
        ),
        ACK,
    )
    return _ack_view(message, MailOutcome.SUBMITTED).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="reply_to_thread",
    display_name="Reply to Gmail Thread",
    description="Reply to the latest non-draft message, preserving its subject and RFC threading headers. Sender/all controls recipients; the connected account is excluded. Missing/invalid parent headers or recipients refuse sending. Returns submitted message identity, not delivery confirmation.",
    input_model=ReplyToThreadInput,
    effect=ToolEffect.MUTATION,
    scopes=(GMAIL_SEND, GMAIL_MODIFY),
)
async def reply_to_thread(
    payload: ReplyToThreadInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    parent = _parent(await _thread(ctx, payload.thread_id))
    mail = headers(parent.payload.headers)
    subject, in_reply_to, references = threading_headers(mail)
    profile = parse_response(await ctx.read(f"{ME}/profile"), PROFILE)
    own = profile.emailAddress.casefold()
    target = [
        value for value in addresses(mail.reply_to or mail.sender) if value != own
    ]
    if not target:
        target = [value for value in addresses(mail.to) if value != own]
    if not target:
        raise VendorToolError(
            GmailErrorCode.REPLY_TARGET_UNKNOWN,
            "No other participant is available to reply to.",
        )
    copied: list[str] = []
    if payload.selected_recipients == ReplyRecipients.ALL and (mail.to or mail.cc):
        copied = [
            value
            for value in addresses(mail.to, mail.cc)
            if value != own and value not in target
        ]
    if len(target) + len(copied) > MAX_RECIPIENTS:
        raise VendorToolError(
            GmailErrorCode.REPLY_TARGET_UNKNOWN, "Too many reply recipients."
        )
    raw = build_message(
        to=target,
        cc=copied,
        subject=subject,
        body=payload.body,
        html_body=payload.html_body,
        in_reply_to=in_reply_to,
        references=references,
    )
    request = RawMessage(raw=raw, threadId=payload.thread_id)
    message = parse_response(
        await ctx.mutate(
            f"{ME}/messages/send",
            json=request.model_dump(mode="json", exclude_none=True),
        ),
        ACK,
    )
    if message.threadId != payload.thread_id:
        invalid_response()
    return ReplyView(
        **_ack_view(message, MailOutcome.SUBMITTED).model_dump(),
        replied_to=target,
        copied=copied,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_draft",
    display_name="Create Gmail Draft",
    description="Create an unsent draft. For a thread draft, reads the latest non-draft parent, requires its exact subject and includes reference headers. Requires compose and modify scopes so thread reads are authorized. It never sends the draft.",
    input_model=CreateDraftInput,
    effect=ToolEffect.MUTATION,
    scopes=(GMAIL_COMPOSE, GMAIL_MODIFY),
)
async def create_draft(
    payload: CreateDraftInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    in_reply_to: str | None = None
    references: str | None = None
    if payload.thread_id:
        parent = _parent(await _thread(ctx, payload.thread_id))
        subject, in_reply_to, references = threading_headers(
            headers(parent.payload.headers)
        )
        if payload.subject != subject:
            raise VendorToolError(
                GmailErrorCode.THREAD_MISMATCH,
                "A threaded draft must use the parent message's exact subject.",
            )
    raw = build_message(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        cc=payload.cc,
        in_reply_to=in_reply_to,
        references=references,
    )
    request = DraftRequest(message=RawMessage(raw=raw, threadId=payload.thread_id))
    draft = parse_response(
        await ctx.mutate(
            f"{ME}/drafts", json=request.model_dump(mode="json", exclude_none=True)
        ),
        DRAFT,
    )
    if payload.thread_id and draft.message.threadId != payload.thread_id:
        invalid_response()
    return DraftView(
        draft_id=draft.id, message_id=draft.message.id, thread_id=draft.message.threadId
    ).model_dump(mode="json")


async def _label_plan(
    payload: ModifyLabelsInput, ctx: VendorToolContext
) -> tuple[list[LabelSelection], list[LabelSelection]]:
    catalog = parse_response(await ctx.read(f"{ME}/labels"), LABELS)
    if len({label.id for label in catalog.labels}) != len(catalog.labels):
        invalid_response()

    def select(names: list[str], missing: MissingLabels) -> list[LabelSelection]:
        selected: list[LabelSelection] = []
        for name in dict.fromkeys(names):
            if name in _NON_EDITABLE_LABELS:
                raise VendorToolError(
                    GmailErrorCode.LABEL_CONFLICT,
                    "This system label cannot be changed with modify_labels.",
                )
            if name in SystemLabel:
                selected.append(LabelSelection(name=name, id=name))
                continue
            by_id = [label for label in catalog.labels if label.id == name]
            matches = by_id or [
                label
                for label in catalog.labels
                if label.name.casefold() == name.casefold()
            ]
            if len(matches) > 1:
                raise VendorToolError(
                    GmailErrorCode.LABEL_AMBIGUOUS,
                    "Multiple labels match this name. Use the exact label ID.",
                )
            if matches:
                label = matches[0]
                if label.id in _NON_EDITABLE_LABELS:
                    raise VendorToolError(
                        GmailErrorCode.LABEL_CONFLICT,
                        "This system label cannot be changed with modify_labels.",
                    )
                selected.append(LabelSelection(name=label.name, id=label.id))
            elif missing == MissingLabels.CREATE:
                selected.append(LabelSelection(name=name, id=None))
            else:
                raise VendorToolError(
                    GmailErrorCode.LABEL_NOT_FOUND,
                    "A requested label does not exist. Use its exact name or ID.",
                )
        return selected

    # Preflight every removal and ambiguity before any remote label creation.
    remove = select(payload.remove or [], MissingLabels.REJECT)
    add = select(payload.add or [], payload.selected_missing_labels)
    if {item.id for item in add if item.id} & {item.id for item in remove}:
        raise VendorToolError(
            GmailErrorCode.LABEL_CONFLICT,
            "The same resolved label cannot be added and removed.",
        )
    return add, remove


@curated_tool(
    vendor=vendor.vendor,
    name="modify_labels",
    display_name="Change Gmail Labels",
    description="Apply/remove message labels by ID or unambiguous name. Remove UNREAD to mark read, INBOX to archive. Optional missing_labels=create creates missing added labels; each creation and the message change has its own receipt, not one atomic vendor transaction. A partial failure may leave created labels. DRAFT, SENT and CHAT are not editable here.",
    input_model=ModifyLabelsInput,
    effect=ToolEffect.MUTATION,
    scopes=(GMAIL_MODIFY,),
)
async def modify_labels(
    payload: ModifyLabelsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    add, remove = await _label_plan(payload, ctx)
    created_ids: dict[str, str] = {}
    add_ids: list[str] = []
    for selection in add:
        label_id = selection.id or created_ids.get(selection.name.casefold())
        if label_id is None:
            label = parse_response(
                await ctx.mutate(
                    f"{ME}/labels",
                    json=LabelCreate(name=selection.name).model_dump(mode="json"),
                ),
                LABEL,
            )
            if label.name != selection.name or label.type != LabelType.USER:
                invalid_response()
            label_id = label.id
            created_ids[selection.name.casefold()] = label_id
        add_ids.append(label_id)
    remove_ids = [selection.id for selection in remove if selection.id is not None]
    request = LabelsRequest(
        addLabelIds=list(dict.fromkeys(add_ids)),
        removeLabelIds=list(dict.fromkeys(remove_ids)),
    )
    message = parse_response(
        await ctx.mutate(
            f"{_message_path(payload.message_id)}/modify",
            json=request.model_dump(mode="json"),
        ),
        ACK,
    )
    if (
        message.id != payload.message_id
        or not set(request.addLabelIds) <= set(message.labelIds)
        or set(request.removeLabelIds) & set(message.labelIds)
    ):
        invalid_response()
    return _ack_view(message, MailOutcome.LABELS_UPDATED).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="trash_message",
    display_name="Move Gmail Message to Trash",
    description="Move a message to Trash and verify its returned identity/label. This is not permanent deletion. Retention and recovery follow the mailbox's policies; no fixed recovery period is promised.",
    input_model=TrashMessageInput,
    effect=ToolEffect.MUTATION,
    scopes=(GMAIL_MODIFY,),
)
async def trash_message(
    payload: TrashMessageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    message = parse_response(
        await ctx.mutate(f"{_message_path(payload.message_id)}/trash"), ACK
    )
    if message.id != payload.message_id or SystemLabel.TRASH not in message.labelIds:
        invalid_response()
    return _ack_view(message, MailOutcome.TRASHED).model_dump(mode="json")


__all__ = [
    "create_draft",
    "modify_labels",
    "read_message",
    "read_thread",
    "reply_to_thread",
    "search_messages",
    "send_message",
    "trash_message",
]
