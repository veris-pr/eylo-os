"""Curated Intercom tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field, JsonValue, StrictBool, StrictInt, field_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import vendor
from .schemas import (
    CONTACT_LOOKUP_LIMIT,
    CONTACT_SEARCH_PATH,
    CONVERSATION_SEARCH_PATH,
    DEFAULT_SEARCH_LIMIT,
    MAX_BODY_CHARS,
    MAX_PARTS,
    MAX_SEARCH_LIMIT,
    SEARCH_METHOD,
    IntercomContact,
    IntercomContactSearch,
    IntercomContactView,
    IntercomConversation,
    IntercomConversationDetail,
    IntercomConversationDetailView,
    IntercomConversationQuery,
    IntercomConversationSearch,
    IntercomConversationState,
    IntercomConversationView,
    IntercomFilter,
    IntercomFilterGroup,
    IntercomMessageType,
    IntercomMessageView,
    IntercomMissingContact,
    IntercomPagination,
    IntercomReply,
    IntercomReplyRequest,
    IntercomReplyResult,
    IntercomSearchField,
    IntercomSearchRequest,
    IntercomSearchResult,
    IntercomToolErrorCode,
    parse_response,
    require_conversation_identity,
)


class FindContactInput(BaseModel):
    email: str = Field(min_length=1, description="Contact's email address.")


class SearchConversationsInput(BaseModel):
    contact_email: str | None = Field(
        default=None, description="Only this person's conversations."
    )
    state: IntercomConversationState | None = Field(
        default=None, description="Only conversations with this native state."
    )
    limit: StrictInt = Field(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT)

    @field_validator("state", mode="before")
    @classmethod
    def empty_filter_is_absent(cls, value: object) -> object:
        """Preserve empty-string omission without accepting whitespace-only input."""
        return None if value == "" else value


class GetConversationInput(BaseModel):
    conversation_id: str = Field(min_length=1)


class ReplyToConversationInput(BaseModel):
    conversation_id: str = Field(min_length=1)
    body: str = Field(min_length=1, description="Reply text. HTML is accepted.")
    visible_to_customer: StrictBool = Field(
        description=(
            "Required. True sends the reply to the customer; false leaves an "
            "internal note. There is no default because a message sent to a "
            "customer cannot be recalled."
        )
    )
    admin_id: str = Field(
        min_length=1, description="Id of the teammate the reply is sent as."
    )


class AddNoteInput(BaseModel):
    conversation_id: str = Field(min_length=1)
    body: str = Field(min_length=1)
    admin_id: str = Field(min_length=1, description="Teammate the note is from.")


@curated_tool(
    vendor=vendor.vendor,
    name="find_contact",
    display_name="Find Intercom Contact",
    description=(
        "Look a person up by email. Returns their Intercom id, name, when they "
        "were last seen, and returned company count — the id is what every other "
        "conversation lookup needs."
    ),
    input_model=FindContactInput,
    effect=ToolEffect.READ,
)
async def find_contact(
    payload: FindContactInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    contact = await _contact_by_email(ctx, payload.email)
    if contact is None:
        return IntercomMissingContact(email=payload.email).model_dump(mode="json")
    return _contact_view(contact).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="search_conversations",
    display_name="Search Intercom Conversations",
    description=(
        "Find conversations, optionally only a given person's — name them by "
        "email and the contact lookup happens here. Each result reports its "
        "state, who it is assigned to, and when it was last updated."
    ),
    input_model=SearchConversationsInput,
    effect=ToolEffect.READ,
)
async def search_conversations(
    payload: SearchConversationsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    filters: list[IntercomFilter] = []
    if payload.contact_email:
        contact = await _contact_by_email(ctx, payload.contact_email)
        if contact is None:
            return IntercomSearchResult(
                conversations=[], count=0, contact_found=False
            ).model_dump(mode="json", exclude_unset=True)
        filters.append(
            IntercomFilter(field=IntercomSearchField.CONTACT_IDS, value=contact.id)
        )
    if payload.state:
        filters.append(
            IntercomFilter(field=IntercomSearchField.STATE, value=payload.state.value)
        )
    if not filters:
        raise VendorToolError(
            IntercomToolErrorCode.SEARCH_UNBOUNDED,
            "Give a contact email or a state to search by.",
        )

    response = await ctx.read(
        CONVERSATION_SEARCH_PATH,
        method=SEARCH_METHOD,
        json=IntercomSearchRequest(
            query=(
                filters[0]
                if len(filters) == 1
                else IntercomFilterGroup(value=filters)
            ),
            pagination=IntercomPagination(per_page=payload.limit),
        ).model_dump(mode="json"),
    )
    body = parse_response(response, IntercomConversationSearch)
    return IntercomSearchResult(
        conversations=[_conversation_view(item) for item in body.conversations],
        count=len(body.conversations),
        total_matches=body.total_count,
    ).model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="get_conversation",
    display_name="Get Intercom Conversation",
    description=(
        "Read a conversation's opening message and speech from the first 50 "
        "returned parts in vendor order, clipped to 6,000 characters per body. "
        "This is a bounded history, not a complete export. "
        "Intercom stores the opening message separately from later replies and "
        "mixes state changes in with them; this returns just what was said, "
        "each message labelled by author and by whether the customer saw it."
    ),
    input_model=GetConversationInput,
    effect=ToolEffect.READ,
)
async def get_conversation(
    payload: GetConversationInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    conversation = parse_response(
        await ctx.read(
            f"/conversations/{payload.conversation_id}",
            query=IntercomConversationQuery().model_dump(mode="json"),
        ),
        IntercomConversationDetail,
    )
    require_conversation_identity(conversation.id, payload.conversation_id)
    view = _conversation_view(conversation)
    messages = [
        IntercomMessageView(
            author=conversation.source.author,
            body=_clip(conversation.source.body),
            visible_to_customer=True,
            created_at=conversation.created_at,
            is_opening_message=True,
        )
    ]
    for part in conversation.conversation_parts.conversation_parts[:MAX_PARTS]:
        if part.part_type not in IntercomMessageType:
            # Assignments, closes and opens are state, not conversation.
            continue
        messages.append(
            IntercomMessageView(
                author=part.author,
                body=_clip(part.body),
                visible_to_customer=part.part_type == IntercomMessageType.COMMENT,
                created_at=part.created_at,
                is_opening_message=False,
            )
        )

    return IntercomConversationDetailView(
        id=view.id,
        title=view.title,
        state=view.state,
        open=view.open,
        read=view.read,
        priority=view.priority,
        assignee_id=view.assignee_id,
        contact_ids=view.contact_ids,
        created_at=view.created_at,
        updated_at=view.updated_at,
        messages=messages,
        message_count=len(messages),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="reply_to_conversation",
    display_name="Reply to Intercom Conversation",
    description=(
        "Reply to a conversation as a teammate. Set visible_to_customer to "
        "true to send the message to the customer, or false to leave an "
        "internal note. The argument is required because the two are one field "
        "apart in the API and only one of them is recoverable."
    ),
    input_model=ReplyToConversationInput,
    effect=ToolEffect.MUTATION,
)
async def reply_to_conversation(
    payload: ReplyToConversationInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    return await _reply(
        ctx,
        conversation_id=payload.conversation_id,
        body=payload.body,
        admin_id=payload.admin_id,
        message_type=(
            IntercomMessageType.COMMENT
            if payload.visible_to_customer
            else IntercomMessageType.NOTE
        ),
    )


@curated_tool(
    vendor=vendor.vendor,
    name="add_note",
    display_name="Add Intercom Internal Note",
    description=(
        "Leave an internal note on a conversation. The customer never sees it. "
        "This is the safe way to record context; use reply_to_conversation "
        "when the customer should actually be answered."
    ),
    input_model=AddNoteInput,
    effect=ToolEffect.MUTATION,
)
async def add_note(payload: AddNoteInput, ctx: VendorToolContext) -> dict[str, JsonValue]:
    return await _reply(
        ctx,
        conversation_id=payload.conversation_id,
        body=payload.body,
        admin_id=payload.admin_id,
        message_type=IntercomMessageType.NOTE,
    )


async def _reply(
    ctx: VendorToolContext,
    *,
    conversation_id: str,
    body: str,
    admin_id: str,
    message_type: IntercomMessageType,
) -> dict[str, JsonValue]:
    response = await ctx.mutate(
        f"/conversations/{conversation_id}/reply",
        json=IntercomReplyRequest(
            admin_id=admin_id, message_type=message_type, body=body
        ).model_dump(mode="json"),
    )
    replied = parse_response(response, IntercomReply)
    require_conversation_identity(replied.id, conversation_id)
    return IntercomReplyResult(
        conversation_id=replied.id,
        message_type=message_type,
        visible_to_customer=message_type is IntercomMessageType.COMMENT,
        state=replied.state,
    ).model_dump(mode="json")


async def _contact_by_email(
    ctx: VendorToolContext, email: str
) -> IntercomContact | None:
    response = await ctx.read(
        CONTACT_SEARCH_PATH,
        method=SEARCH_METHOD,
        json=IntercomSearchRequest(
            query=IntercomFilter(field=IntercomSearchField.EMAIL, value=email.strip()),
            pagination=IntercomPagination(per_page=CONTACT_LOOKUP_LIMIT),
        ).model_dump(mode="json"),
    )
    results = parse_response(response, IntercomContactSearch).data
    return results[0] if results else None


def _contact_view(contact: IntercomContact) -> IntercomContactView:
    return IntercomContactView(
        id=contact.id,
        name=contact.name,
        email=contact.email,
        phone=contact.phone,
        role=contact.role,
        last_seen_at=contact.last_seen_at,
        created_at=contact.created_at,
        company_count=len(contact.companies.data) if contact.companies else 0,
    )


def _conversation_view(conversation: IntercomConversation) -> IntercomConversationView:
    return IntercomConversationView(
        id=conversation.id,
        title=conversation.title,
        state=conversation.state,
        open=conversation.open,
        read=conversation.read,
        priority=conversation.priority,
        assignee_id=conversation.admin_assignee_id,
        contact_ids=[contact.id for contact in conversation.contacts.contacts],
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _clip(value: str | None) -> str | None:
    return value[:MAX_BODY_CHARS] if value is not None else None


__all__ = [
    "add_note",
    "find_contact",
    "get_conversation",
    "reply_to_conversation",
    "search_conversations",
]
