"""Authorize widget responses against the exact generated parent message."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from uuid import UUID

from pydantic import JsonValue, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.message_content import (
    CompoundWidgetPayload as StoredCompoundWidgetPayload,
)
from eylo.common.contracts.message_content import (
    WidgetMessageContent,
    WidgetResponseMessageContent,
)
from eylo.common.contracts.widget_responses import (
    WidgetButtonGroupResponse,
    WidgetButtonSelection,
    WidgetCardListResponse,
    WidgetCardSelection,
    WidgetDatePickerResponse,
    WidgetFormResponse,
    WidgetInteractionAction,
    WidgetResponseData,
)
from eylo.common.contracts.widgets import (
    WidgetDateMode,
    WidgetFieldKind,
    WidgetPattern,
    WidgetSelectionMode,
)
from eylo.modules.conversations.repositories.messages import MessageRepository
from eylo.modules.interfaces.schemas.api import (
    INTERACTIVE_COMPONENT_TYPES,
    WidgetButtonGroupPayload,
    WidgetCardListPayload,
    WidgetComponentPayload,
    WidgetDatePickerPayload,
    WidgetFormField,
    WidgetFormPayload,
)
from eylo.modules.interfaces.services.schema_validator import (
    CompoundWidgetSchemaValidatorService,
)


class WidgetResponseRejected(Exception):
    """The response does not belong to, or match, its parent widget."""


_COMPONENT_ADAPTER = TypeAdapter(WidgetComponentPayload)
_NAMED_PATTERNS = {
    WidgetPattern.EMAIL: re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$"),
    WidgetPattern.PHONE: re.compile(r"^\+?[0-9()\-\s]{7,20}$"),
    WidgetPattern.URL: re.compile(r"^https?://.+", re.IGNORECASE),
}


async def require_valid_widget_response(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    parent_message_id: UUID | None,
    response: WidgetResponseMessageContent,
) -> None:
    """Lock and validate the exact widget accepting this user response."""
    if parent_message_id is None:
        raise WidgetResponseRejected("A widget response requires its parent message.")
    if response.content.widget_message_id != parent_message_id:
        raise WidgetResponseRejected("Widget response parent identities do not match.")

    parent = await MessageRepository(session).get_widget_response_parent_for_update(
        parent_message_id=parent_message_id,
        conversation_id=conversation_id,
    )
    if parent is None:
        raise WidgetResponseRejected("The widget message is unavailable.")

    try:
        widget_content = WidgetMessageContent.model_validate(parent.content)
        component = _resolve_interactive_component(widget_content)
    except (TypeError, ValueError, ValidationError) as error:
        raise WidgetResponseRejected("The widget message is invalid.") from error

    if response.content.component != component.component:
        raise WidgetResponseRejected("Widget response component does not match.")

    _validate_response_data(component, response.content)


def _resolve_interactive_component(
    content: WidgetMessageContent,
) -> WidgetComponentPayload:
    payload = content.content
    if isinstance(payload, StoredCompoundWidgetPayload):
        validated = CompoundWidgetSchemaValidatorService().validate_compound_payload(
            payload.model_dump()
        )
        nodes = [
            node
            for node in validated.components
            if node.component in INTERACTIVE_COMPONENT_TYPES
        ]
        if len(nodes) != 1:
            raise WidgetResponseRejected(
                "A responding widget must contain one interactive component."
            )
        raw_component = {
            "component": nodes[0].component,
            "props": nodes[0].props.model_dump(),
        }
    else:
        raw_component = payload.model_dump()

    component = _COMPONENT_ADAPTER.validate_python(raw_component)
    if component.component not in INTERACTIVE_COMPONENT_TYPES:
        raise WidgetResponseRejected("The widget does not accept user input.")
    return component


def _validate_response_data(
    component: WidgetComponentPayload,
    response: WidgetResponseData,
) -> None:
    if isinstance(component, WidgetFormPayload) and isinstance(
        response, WidgetFormResponse
    ):
        _validate_form_data(component, response.action, response.data)
        return
    if isinstance(component, WidgetButtonGroupPayload) and isinstance(
        response, WidgetButtonGroupResponse
    ):
        _validate_button_group_data(component, response.data)
        return
    if isinstance(component, WidgetCardListPayload) and isinstance(
        response, WidgetCardListResponse
    ):
        _validate_card_list_data(component, response.data)
        return
    if isinstance(component, WidgetDatePickerPayload) and isinstance(
        response, WidgetDatePickerResponse
    ):
        _validate_date_picker_data(component, response.data)
        return
    raise WidgetResponseRejected("The widget does not accept user input.")


def _validate_form_data(
    component: WidgetFormPayload,
    action: WidgetInteractionAction,
    data: dict[str, JsonValue],
) -> None:
    fields = {field.name: field for field in component.props.fields}
    if unknown := set(data) - set(fields):
        raise WidgetResponseRejected(
            f"Widget response contains unknown form fields: {sorted(unknown)}"
        )
    if action is WidgetInteractionAction.CANCEL:
        return
    for field in fields.values():
        _validate_form_field(field, data.get(field.name))


def _validate_form_field(field: WidgetFormField, value: JsonValue) -> None:
    blank = value is None or (isinstance(value, str) and not value.strip())
    if field.required and (
        blank or (field.type is WidgetFieldKind.CHECKBOX and value is not True)
    ):
        raise WidgetResponseRejected(f"Required widget field is missing: {field.name}")
    if blank:
        return

    if field.type is WidgetFieldKind.CHECKBOX:
        if not isinstance(value, bool):
            raise WidgetResponseRejected(f"Widget field must be boolean: {field.name}")
        return
    if field.type is WidgetFieldKind.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WidgetResponseRejected(f"Widget field must be numeric: {field.name}")
        validation = field.validation
        if (
            validation is not None
            and validation.min is not None
            and value < validation.min
        ):
            raise WidgetResponseRejected(
                f"Widget field is below its minimum: {field.name}"
            )
        if (
            validation is not None
            and validation.max is not None
            and value > validation.max
        ):
            raise WidgetResponseRejected(
                f"Widget field exceeds its maximum: {field.name}"
            )
        return
    if not isinstance(value, str):
        raise WidgetResponseRejected(f"Widget field must be text: {field.name}")
    if field.options and value not in {option.value for option in field.options}:
        raise WidgetResponseRejected(f"Widget field option is invalid: {field.name}")
    _validate_text_format(field, value)
    if field.validation is not None:
        if (
            field.validation.min_length is not None
            and len(value) < field.validation.min_length
        ):
            raise WidgetResponseRejected(f"Widget field is too short: {field.name}")
        if (
            field.validation.max_length is not None
            and len(value) > field.validation.max_length
        ):
            raise WidgetResponseRejected(f"Widget field is too long: {field.name}")


def _validate_text_format(field: WidgetFormField, value: str) -> None:
    pattern = field.validation.pattern if field.validation is not None else None
    if field.type is WidgetFieldKind.EMAIL:
        pattern = WidgetPattern.EMAIL
    elif field.type is WidgetFieldKind.PHONE:
        pattern = WidgetPattern.PHONE
    if pattern is not None and not _NAMED_PATTERNS[pattern].fullmatch(value):
        raise WidgetResponseRejected(f"Widget field format is invalid: {field.name}")

    try:
        if field.type is WidgetFieldKind.DATE:
            date.fromisoformat(value)
        elif field.type is WidgetFieldKind.TIME:
            time.fromisoformat(value)
        elif field.type is WidgetFieldKind.DATETIME:
            datetime.fromisoformat(value)
    except ValueError as error:
        raise WidgetResponseRejected(
            f"Widget field date or time is invalid: {field.name}"
        ) from error


def _validate_button_group_data(
    component: WidgetButtonGroupPayload,
    data: WidgetButtonSelection,
) -> None:
    if not any(
        button.value == data.value and button.label == data.label
        for button in component.props.buttons
    ):
        raise WidgetResponseRejected(
            "Button response is not one of the offered choices."
        )


def _validate_card_list_data(
    component: WidgetCardListPayload,
    data: WidgetCardSelection,
) -> None:
    selected = data.selected_ids
    available = {card.id for card in component.props.cards}
    if not set(selected).issubset(available):
        raise WidgetResponseRejected("Card response contains an unavailable choice.")
    if (
        component.props.selection_mode is not WidgetSelectionMode.MULTIPLE
        and len(selected) != 1
    ):
        raise WidgetResponseRejected("This card list accepts one choice.")


def _validate_date_picker_data(
    component: WidgetDatePickerPayload,
    data: dict[str, str],
) -> None:
    value = data.get(component.props.name)
    if set(data) != {component.props.name} or not isinstance(value, str):
        raise WidgetResponseRejected(
            "Date response does not match the requested field."
        )
    if component.props.required and not value:
        raise WidgetResponseRejected("A required date response is missing.")
    if value:
        pseudo_field = WidgetFormField(
            type=WidgetFieldKind((component.props.mode or WidgetDateMode.DATE).value),
            name=component.props.name,
            label=component.props.label,
            required=component.props.required,
        )
        _validate_text_format(pseudo_field, value)
