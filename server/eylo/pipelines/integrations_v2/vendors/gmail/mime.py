"""Bounded Gmail MIME selection, strict decoding and safe RFC message construction."""

import base64
import binascii
import re
from email.message import EmailMessage, Message
from email.utils import getaddresses
from urllib.parse import quote

from bs4 import BeautifulSoup
from pydantic import Field, TypeAdapter

from ...contracts import VendorToolContext, VendorToolError
from .schemas import (
    MAX_BODY_FETCHES,
    MAX_MIME_PARTS,
    ME,
    AttachmentView,
    BodyFormat,
    BodyState,
    DecodedBody,
    GmailErrorCode,
    GmailModel,
    Header,
    HeaderName,
    MailHeaders,
    MimePart,
    MimeType,
    PartBody,
    address,
    header,
    invalid_response,
    parse_response,
)

_MESSAGES_PATH = f"{ME}/messages"
_PART_BODY = TypeAdapter(PartBody)
_FOLD = re.compile(r"\r?\n[ \t]+")
_ATTACHMENT = "attachment"


def values(entries: list[Header], name: HeaderName) -> list[str]:
    return [
        entry.value for entry in entries if entry.name.casefold() == name.casefold()
    ]


def single(entries: list[Header], name: HeaderName) -> str | None:
    found = values(entries, name)
    if len(found) > 1:
        invalid_response()
    return found[0] if found else None


def headers(entries: list[Header]) -> MailHeaders:
    return MailHeaders(
        sender=single(entries, HeaderName.FROM),
        to=", ".join(values(entries, HeaderName.TO)) or None,
        cc=", ".join(values(entries, HeaderName.CC)) or None,
        subject=single(entries, HeaderName.SUBJECT),
        date=single(entries, HeaderName.DATE),
        reply_to=single(entries, HeaderName.REPLY_TO),
        message_id=single(entries, HeaderName.MESSAGE_ID),
        references=single(entries, HeaderName.REFERENCES),
    )


def addresses(*entries: str | None) -> list[str]:
    try:
        pairs = getaddresses(
            [header(_FOLD.sub(" ", value)) for value in entries if value]
        )
        if not pairs or any(not value for _, value in pairs):
            raise ValueError("No valid mailbox.")
        return list(dict.fromkeys(address(value).casefold() for _, value in pairs))
    except (ValueError, TypeError):
        raise VendorToolError(
            GmailErrorCode.REPLY_TARGET_UNKNOWN,
            "The message does not identify valid reply recipients.",
        ) from None


def threading_headers(parent: MailHeaders) -> tuple[str, str, str]:
    """Preserve subject and RFC references; do not invent a thread from only its ID."""
    message_id = parent.message_id
    if not message_id or parent.subject is None:
        raise VendorToolError(
            GmailErrorCode.THREAD_HEADERS_MISSING,
            "The parent message lacks a subject or Message-ID needed for reliable threading.",
        )
    try:
        message_id = header(_FOLD.sub(" ", message_id)).strip()
        if not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", message_id):
            raise ValueError("Invalid Message-ID.")
        references = header(_FOLD.sub(" ", parent.references or "")).strip()
        tokens = references.split()
        if any(not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", token) for token in tokens):
            raise ValueError("Invalid References.")
        if message_id not in tokens:
            tokens.append(message_id)
        return header(_FOLD.sub(" ", parent.subject)), message_id, " ".join(tokens)
    except ValueError:
        raise VendorToolError(
            GmailErrorCode.THREAD_HEADERS_MISSING,
            "The parent message has invalid threading headers.",
        ) from None


class MimeSelection(GmailModel):
    parts: list[MimePart] = Field(default_factory=list)
    attachments: list[AttachmentView] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)


def select_parts(root: MimePart) -> MimeSelection:
    """Skip attached subtrees; prefer text only within multipart alternatives."""
    visited = 0

    def walk(part: MimePart) -> MimeSelection:
        nonlocal visited
        visited += 1
        if visited > MAX_MIME_PARTS:
            raise VendorToolError(
                GmailErrorCode.BODY_TOO_COMPLEX,
                "Message MIME structure exceeds the bounded reader.",
            )
        native = Message()
        disposition = single(part.headers, HeaderName.CONTENT_DISPOSITION)
        if disposition:
            native[HeaderName.CONTENT_DISPOSITION] = disposition
        if part.filename or native.get_content_disposition() == _ATTACHMENT:
            return MimeSelection(
                attachments=[
                    AttachmentView(
                        filename=part.filename,
                        mime_type=part.mimeType,
                        size_bytes=part.body.size,
                        attachment_id=part.body.attachmentId,
                    )
                ]
            )
        mime = part.mimeType.casefold()
        if mime in (MimeType.TEXT, MimeType.HTML):
            return MimeSelection(parts=[part])
        children = [walk(child) for child in part.parts]
        attachments = [
            attachment for child in children for attachment in child.attachments
        ]
        if mime == MimeType.ALTERNATIVE:
            chosen = next(
                (
                    child
                    for child in children
                    if any(p.mimeType.casefold() == MimeType.TEXT for p in child.parts)
                ),
                None,
            )
            if chosen is None:
                chosen = next((child for child in children if child.parts), None)
            return MimeSelection(
                parts=chosen.parts if chosen else [],
                attachments=attachments,
                unsupported=[]
                if chosen
                else [kind for child in children for kind in child.unsupported],
            )
        if children:
            return MimeSelection(
                parts=[p for child in children for p in child.parts],
                attachments=attachments,
                unsupported=[kind for child in children for kind in child.unsupported],
            )
        if mime.startswith("multipart/"):
            return MimeSelection()
        return MimeSelection(unsupported=[part.mimeType])

    return walk(root)


def decode(body: PartBody, part: MimePart) -> str:
    try:
        data = body.data
        if data is None:
            if body.size:
                raise ValueError("Missing MIME data.")
            data = ""
        if not re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", data):
            raise ValueError("Invalid base64url.")
        raw = base64.b64decode(
            data + "=" * (-len(data) % 4), altchars=b"-_", validate=True
        )
        if len(raw) != body.size:
            raise ValueError("Decoded MIME size differs from declared size.")
        native = Message()
        content_type = single(part.headers, HeaderName.CONTENT_TYPE)
        if content_type:
            native[HeaderName.CONTENT_TYPE] = content_type
        charset = native.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="strict")
    except (ValueError, LookupError, binascii.Error, UnicodeError):
        raise VendorToolError(
            GmailErrorCode.BODY_INVALID,
            "Message body encoding is invalid or its charset is unsupported.",
        ) from None


async def read_body(
    message_id: str, root: MimePart, ctx: VendorToolContext
) -> DecodedBody:
    selection = select_parts(root)
    fetches = sum(part.body.attachmentId is not None for part in selection.parts)
    if fetches > MAX_BODY_FETCHES:
        raise VendorToolError(
            GmailErrorCode.BODY_TOO_COMPLEX,
            "Message body requires too many separate MIME-part fetches.",
        )
    decoded: list[str] = []
    only_html = bool(selection.parts) and all(
        part.mimeType.casefold() == MimeType.HTML for part in selection.parts
    )
    for part in selection.parts:
        body = part.body
        if body.attachmentId:
            response = await ctx.read(
                f"{_MESSAGES_PATH}/{quote(message_id, safe='')}/attachments/{quote(body.attachmentId, safe='')}"
            )
            body = parse_response(response, _PART_BODY)
            if body.attachmentId or body.size != part.body.size:
                invalid_response()
        text = decode(body, part)
        if part.mimeType.casefold() == MimeType.HTML and not only_html:
            soup = BeautifulSoup(text, "html.parser")
            for hidden in soup(["script", "style"]):
                hidden.decompose()
            text = soup.get_text("\n")
        decoded.append(text)
    text = "\n".join(decoded)
    state = (
        BodyState.AVAILABLE
        if text
        else BodyState.UNSUPPORTED
        if selection.unsupported and not selection.parts
        else BodyState.EMPTY
    )
    return DecodedBody(
        text=text,
        format=BodyFormat.HTML
        if only_html
        else BodyFormat.TEXT
        if selection.parts
        else BodyFormat.NONE,
        state=state,
        attachments=selection.attachments,
        unsupported_mime_types=list(dict.fromkeys(selection.unsupported)),
    )


def build_message(
    *,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html_body: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """The stdlib owns RFC serialization; credentials and provider types stay out."""
    message = EmailMessage()
    message[HeaderName.TO] = ", ".join(to)
    message[HeaderName.SUBJECT] = subject
    if cc:
        message[HeaderName.CC] = ", ".join(cc)
    if bcc:
        message[HeaderName.BCC] = ", ".join(bcc)
    if in_reply_to:
        message[HeaderName.IN_REPLY_TO] = in_reply_to
    if references:
        message[HeaderName.REFERENCES] = references
    message.set_content(body)
    if html_body is not None:
        message.add_alternative(html_body, subtype="html")
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
