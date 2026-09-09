"""Strict wire contracts for the generated-widget tool and its delivery receipt."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from eylo.modules.interfaces.schemas.api import (
    COMPOUND_MAX_COMPONENTS,
    CompoundComponentKind,
    WidgetSchemaModel,
)


class CompoundComponentInput(WidgetSchemaModel):
    """LLM wire node; props stay serialized for strict vendor tool schemas."""

    id: str = Field(description="Unique identifier for this component.")
    component: CompoundComponentKind = Field(description="Component type.")
    props: str = Field(
        default="{}",
        description="JSON-serialized object of component-specific properties.",
    )
    children: list[str] | None = Field(
        default=None,
        description="Ordered child component IDs (layout components only).",
    )


class CompoundRenderWidgetInput(WidgetSchemaModel):
    components: list[CompoundComponentInput] = Field(
        min_length=1,
        max_length=COMPOUND_MAX_COMPONENTS,
        description="Flat list of component nodes with ID-based relationships.",
    )
    root: str | None = Field(
        default=None,
        description="Root ID; may be omitted for one unambiguous tree root.",
    )


class WidgetDeliveryStatus(StrEnum):
    DELIVERED = "delivered"


class WidgetDeliveryReceipt(WidgetSchemaModel):
    """Message identity returned after persistence, not a second widget payload."""

    status: Literal[WidgetDeliveryStatus.DELIVERED]
    widget_message_id: UUID
    root: str
