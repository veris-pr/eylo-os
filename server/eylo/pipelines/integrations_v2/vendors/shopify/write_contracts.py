"""Order mutations preserve per-operation outcomes and never infer an acknowledgement."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, Field, TypeAdapter, model_validator

from .schemas import (
    GraphQLResponse,
    InputOrderId,
    OrderId,
    ShopifyModel,
    ShopifyRequest,
    search_text,
)

MAX_TAGS_PER_REQUEST = 250
MAX_NOTE_CHARS = 5000
MAX_TAG_CHARS = 255


class OperationOutcome(StrEnum):
    NOT_REQUESTED = "not_requested"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class UpdateOutcome(StrEnum):
    CONFIRMED = "confirmed"
    PARTIAL = "partial"
    REJECTED = "rejected"


def tag_text(value: str) -> str:
    tag = search_text(value)
    if "," in tag:
        raise ValueError("Supply separate tags rather than a comma-separated tag.")
    return tag


TagText = Annotated[str, Field(max_length=MAX_TAG_CHARS), AfterValidator(tag_text)]


class TagOrderInput(ShopifyRequest):
    order_id: InputOrderId
    add_tags: list[TagText] | None = Field(
        default=None, min_length=1, max_length=MAX_TAGS_PER_REQUEST
    )
    note: str | None = Field(
        default=None,
        max_length=MAX_NOTE_CHARS,
        description="Replaces the internal note. Empty string clears it.",
    )

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.add_tags is None and self.note is None:
            raise ValueError("Give tags to add or a note to set.")
        return self


class OrderNoteInput(ShopifyRequest):
    id: OrderId
    note: str | None


class OrderUpdateVariables(ShopifyRequest):
    id: OrderId
    tags: list[str]
    input: OrderNoteInput
    addTags: bool
    setNote: bool


class UserError(ShopifyModel):
    message: str


class TaggedOrder(ShopifyModel):
    id: OrderId
    tags: list[str]


class NotedOrder(ShopifyModel):
    id: OrderId
    note: str | None


class TagsAdded(ShopifyModel):
    node: TaggedOrder | None
    userErrors: list[UserError]


class NoteUpdated(ShopifyModel):
    order: NotedOrder | None
    userErrors: list[UserError]


class OrderUpdateData(ShopifyModel):
    tagsAdd: TagsAdded | None = None
    orderUpdate: NoteUpdated | None = None


class OrderUpdateView(ShopifyModel):
    order_id: str
    outcome: UpdateOutcome
    tags_outcome: OperationOutcome
    note_outcome: OperationOutcome
    tags: list[str] | None
    note: str | None
    rejected_tags_errors: int
    rejected_note_errors: int


ORDER_UPDATE_DATA = TypeAdapter(GraphQLResponse[OrderUpdateData])
