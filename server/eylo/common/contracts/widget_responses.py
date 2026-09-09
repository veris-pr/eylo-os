"""Typed widget submissions; generated parent data owns offered-value authority."""

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Final, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictStr, model_validator

from eylo.common.contracts.widgets import CompoundComponentKind

WIDGET_RESPONSE_TYPE: Final = "widget_response"
WIDGET_RESPONSE_DATA_MAX_BYTES: Final = 64 * 1024


class WidgetInteractionAction(StrEnum):
    SUBMIT = "submit"
    CANCEL = "cancel"
    SELECT = "select"


class WidgetSubmissionModel(BaseModel):
    """Accept only declared fields and finite JSON values without scalar coercion."""

    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, serialize_by_alias=True
    )


class WidgetButtonSelection(WidgetSubmissionModel):
    value: StrictStr
    label: StrictStr


class WidgetCardSelection(WidgetSubmissionModel):
    selected_ids: list[StrictStr] = Field(alias="selectedIds", min_length=1)

    @model_validator(mode="after")
    def require_unique_ids(self) -> "WidgetCardSelection":
        if len(self.selected_ids) != len(set(self.selected_ids)):
            raise ValueError("Card response IDs must be unique.")
        return self


SubmissionT = TypeVar(
    "SubmissionT",
    bound=Mapping[str, JsonValue] | WidgetButtonSelection | WidgetCardSelection,
)


class WidgetResponseEnvelope(WidgetSubmissionModel, Generic[SubmissionT]):
    """Shared identity and byte ceiling; subclasses own component-specific data."""

    type: Literal["widget_response"] = WIDGET_RESPONSE_TYPE
    widget_message_id: UUID
    data: SubmissionT

    def submitted_data(self) -> dict[str, JsonValue]:
        data: Mapping[str, JsonValue] | WidgetButtonSelection | WidgetCardSelection = (
            self.data
        )
        if isinstance(data, Mapping):
            return dict(data)
        return data.model_dump(mode="json")

    @model_validator(mode="after")
    def validate_data_size(self) -> "WidgetResponseEnvelope[SubmissionT]":
        raw = json.dumps(self.submitted_data(), allow_nan=False)
        if len(raw.encode("utf-8")) > WIDGET_RESPONSE_DATA_MAX_BYTES:
            raise ValueError("widget response data exceeds maximum allowed size")
        return self


class WidgetFormResponse(WidgetResponseEnvelope[dict[str, JsonValue]]):
    component: Literal[CompoundComponentKind.FORM]
    action: Literal[WidgetInteractionAction.SUBMIT, WidgetInteractionAction.CANCEL]
    # Field names come from the generated form, not a platform-wide catalog.
    data: dict[str, JsonValue] = Field(default_factory=dict)


class WidgetButtonGroupResponse(WidgetResponseEnvelope[WidgetButtonSelection]):
    component: Literal[CompoundComponentKind.BUTTON_GROUP]
    action: Literal[WidgetInteractionAction.SELECT]
    data: WidgetButtonSelection


class WidgetCardListResponse(WidgetResponseEnvelope[WidgetCardSelection]):
    component: Literal[CompoundComponentKind.CARD_LIST]
    action: Literal[WidgetInteractionAction.SUBMIT]
    data: WidgetCardSelection


class WidgetDatePickerResponse(WidgetResponseEnvelope[dict[str, StrictStr]]):
    component: Literal[CompoundComponentKind.DATE_PICKER]
    action: Literal[WidgetInteractionAction.SUBMIT]
    # The generated date picker owns the one field name and date/time mode.
    data: dict[str, StrictStr]


WidgetResponseData = Annotated[
    WidgetFormResponse
    | WidgetButtonGroupResponse
    | WidgetCardListResponse
    | WidgetDatePickerResponse,
    Field(discriminator="component"),
]
