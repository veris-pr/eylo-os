"""Consumed Intercom v2.16 wire shapes; canonical support policy stays in the adapter."""

from enum import IntEnum, StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)
from eylo.sor.shared.json_values import SorJsonValue, require_json_value

SEARCH_PAGE_LIMIT = 150
EXPANDED_PAGE_LIMIT = 500
RESPONSE_BODY_LIMIT = 8_388_608

type Identifier = str | int
type Timestamp = int | float | str


class AssignmentSentinel(IntEnum):
    """Intercom v2.16's absent conversation admin/team assignment identity."""

    UNASSIGNED = 0


class IntercomResponse(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class IntercomRequest(IntercomResponse):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def to_wire(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class ConversationState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    SNOOZED = "snoozed"


class ActorType(StrEnum):
    CONTACT = "contact"
    LEAD = "lead"
    USER = "user"
    VISITOR = "visitor"
    ADMIN = "admin"
    BOT = "bot"
    TEAM = "team"


class MessageType(StrEnum):
    COMMENT = "comment"
    NOTE = "note"
    ASSIGNMENT = "assignment"
    CLOSE = "close"


class TagAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"


class AttributeType(StrEnum):
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    FLOAT = "float"
    INTEGER = "integer"
    LIST = "list"
    OBJECT = "object"


class Attribute(IntercomResponse):
    name: str | None = None
    full_name: str | None = None
    data_type: str | None = None
    label: str | None = None
    description: str | None = None


class AttributeList(IntercomResponse):
    data: list[Attribute]


class AttributeQuery(IntercomRequest):
    model: Literal[ActorType.CONTACT] = ActorType.CONTACT


class AdminQuery(IntercomRequest):
    display_avatar: bool = True


class ConversationDisplay(StrEnum):
    PLAINTEXT = "plaintext"


class ConversationQuery(IntercomRequest):
    display_as: ConversationDisplay = ConversationDisplay.PLAINTEXT


class Workspace(IntercomResponse):
    id_code: Identifier
    region: str
    name: str | None = None


class Viewer(IntercomResponse):
    id: Identifier
    # /me is also used to resolve the acting admin without workspace verification.
    app: Workspace | None = None


class Record(IntercomResponse):
    id: Identifier
    created_at: Timestamp | None = None
    updated_at: Timestamp | None = None


class Reference(IntercomResponse):
    id: Identifier | None = None


class ContactReferences(IntercomResponse):
    contacts: list[Reference] | None = None


class TagReferences(IntercomResponse):
    tags: list[Reference] | None = None


class CompanyReferences(IntercomResponse):
    data: list[Reference] | None = None


class Contact(Record):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    companies: CompanyReferences | None = None
    custom_attributes: dict[str, SorJsonValue] | None = None


class Avatar(IntercomResponse):
    image_url: str | None = None


class Admin(Record):
    name: str | None = None
    email: str | None = None
    has_inbox_seat: bool | None = None
    avatar: Avatar | None = None


class Team(Record):
    name: str | None = None


class Tag(Record):
    name: str | None = None


class AdminList(IntercomResponse):
    admins: list[Admin]


class TeamList(IntercomResponse):
    teams: list[Team]


class TagList(IntercomResponse):
    data: list[Tag]


class SourceSnapshot(IntercomResponse):
    """Preserve native message fields for source_body without using them as policy."""

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def require_json_snapshot(cls, value: object) -> object:
        if isinstance(value, cls):
            return value
        return require_json_value(value)


class Author(SourceSnapshot):
    id: Identifier | None = None
    type: str | None = None


class Attachment(SourceSnapshot):
    id: Identifier | None = None
    name: str | None = None
    content_type: str | None = None
    filesize: int | None = None
    size: int | None = None
    url: str | None = None


class Message(SourceSnapshot):
    id: Identifier | None = None
    body: str | None = Field(default=None, repr=False)
    author: Author | None = None
    attachments: list[Attachment] | None = None
    created_at: Timestamp | None = None
    updated_at: Timestamp | None = None


class ConversationSource(Message):
    subject: str | None = None
    type: str | None = None
    delivered_as: str | None = None


class PartHeader(SourceSnapshot):
    """Select readable parts before validating fields irrelevant to system actions."""

    part_type: str | None = None


class MessagePart(Message):
    part_type: str | None = None


class ConversationParts(IntercomResponse):
    conversation_parts: list[PartHeader] | None = None
    total_count: int | None = None


class Statistics(IntercomResponse):
    first_admin_reply_at: Timestamp | None = None
    last_close_at: Timestamp | None = None


class AppliedSla(IntercomResponse):
    sla_status: str | None = None


class Conversation(Record):
    title: str | None = None
    source: ConversationSource | None = None
    state: str | None = None
    priority: str | None = None
    admin_assignee_id: Identifier | None = None
    team_assignee_id: Identifier | None = None
    contacts: ContactReferences | None = None
    tags: TagReferences | None = None
    statistics: Statistics | None = None
    sla_applied: AppliedSla | None = None
    custom_attributes: dict[str, SorJsonValue] | None = None
    conversation_parts: ConversationParts | None = None


class NextPage(IntercomResponse):
    starting_after: str


class Pages(IntercomResponse):
    next: NextPage | str | None = None


class ContactPage(IntercomResponse):
    data: list[Contact]
    pages: Pages | None = None


class ConversationPage(IntercomResponse):
    conversations: list[Conversation]
    pages: Pages | None = None


class SearchField(StrEnum):
    UPDATED_AT = "updated_at"


class SearchOperator(StrEnum):
    AFTER = ">"


class SortOrder(StrEnum):
    ASCENDING = "ascending"


class SearchFilter(IntercomRequest):
    field: SearchField = SearchField.UPDATED_AT
    operator: SearchOperator = SearchOperator.AFTER
    value: int = Field(ge=0)


class SearchPagination(IntercomRequest):
    per_page: int = Field(ge=1, le=SEARCH_PAGE_LIMIT)
    starting_after: str | None = None


class SearchSort(IntercomRequest):
    field: SearchField = SearchField.UPDATED_AT
    order: SortOrder = SortOrder.ASCENDING


class SearchRequest(IntercomRequest):
    query: SearchFilter
    pagination: SearchPagination
    sort: SearchSort = Field(default_factory=SearchSort)


class ContactSender(IntercomRequest):
    type: Literal[ActorType.CONTACT] = ActorType.CONTACT
    id: str


class OpenConversation(IntercomRequest):
    sender: ContactSender = Field(serialization_alias="from")
    body: str = Field(repr=False)


class OpenResult(IntercomResponse):
    conversation_id: Identifier


class UpdateConversation(IntercomRequest):
    title: str | None = None
    custom_attributes: dict[str, SorJsonValue] | None = None

    def to_wire(self) -> dict[str, object]:
        """An omitted title is unchanged; an explicitly supplied null is a clear."""
        return self.model_dump(mode="json", exclude_unset=True)


class ConversationResult(Record):
    """Mutation acknowledgement consumes identity and revision, not the full inbox."""


class AssignConversation(IntercomRequest):
    message_type: Literal[MessageType.ASSIGNMENT] = MessageType.ASSIGNMENT
    type: Literal[ActorType.TEAM, ActorType.ADMIN]
    admin_id: str
    assignee_id: str


class Reply(IntercomRequest):
    type: Literal[ActorType.ADMIN] = ActorType.ADMIN
    admin_id: str
    message_type: Literal[MessageType.COMMENT, MessageType.NOTE]
    body: str = Field(repr=False)


class ReplyResult(IntercomResponse):
    updated_at: Timestamp | None = None
    conversation_parts: ConversationParts | None = None


class CloseConversation(IntercomRequest):
    message_type: Literal[MessageType.CLOSE] = MessageType.CLOSE
    type: Literal[ActorType.ADMIN] = ActorType.ADMIN
    admin_id: str
    body: str | None = Field(default=None, repr=False)


class TagMutation(IntercomRequest):
    admin_id: str
    id: str | None = None


def parse_response[T: BaseModel](value: object, model: type[T]) -> T:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Intercom returned an invalid response shape.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error


def parse_request[T: IntercomRequest](value: object, model: type[T]) -> T:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "The Intercom request fields are invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
