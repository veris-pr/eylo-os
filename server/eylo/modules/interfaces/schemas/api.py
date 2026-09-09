"""Interface catalog contracts and exports of the shared widget schema."""

from typing import Literal

from pydantic import Field, JsonValue

from eylo.common.contracts.widgets import (
    ALIGN_VALUES as ALIGN_VALUES,
)
from eylo.common.contracts.widgets import (
    ALL_COMPOUND_COMPONENT_TYPES as ALL_COMPOUND_COMPONENT_TYPES,
)
from eylo.common.contracts.widgets import (
    COMPOUND_MAX_COMPONENTS as COMPOUND_MAX_COMPONENTS,
)
from eylo.common.contracts.widgets import (
    COMPOUND_MAX_DEPTH as COMPOUND_MAX_DEPTH,
)
from eylo.common.contracts.widgets import (
    INTERACTIVE_COMPONENT_TYPES as INTERACTIVE_COMPONENT_TYPES,
)
from eylo.common.contracts.widgets import (
    LAYOUT_COMPONENT_TYPES as LAYOUT_COMPONENT_TYPES,
)
from eylo.common.contracts.widgets import (
    SPACING_VALUES as SPACING_VALUES,
)
from eylo.common.contracts.widgets import (
    CompoundComponentKind as CompoundComponentKind,
)
from eylo.common.contracts.widgets import (
    CompoundWidgetNode as CompoundWidgetNode,
)
from eylo.common.contracts.widgets import (
    CompoundWidgetPayload as CompoundWidgetPayload,
)
from eylo.common.contracts.widgets import (
    WidgetAlertPayload as WidgetAlertPayload,
)
from eylo.common.contracts.widgets import (
    WidgetAlertProps as WidgetAlertProps,
)
from eylo.common.contracts.widgets import (
    WidgetButton as WidgetButton,
)
from eylo.common.contracts.widgets import (
    WidgetButtonGroupPayload as WidgetButtonGroupPayload,
)
from eylo.common.contracts.widgets import (
    WidgetButtonGroupProps as WidgetButtonGroupProps,
)
from eylo.common.contracts.widgets import (
    WidgetCard as WidgetCard,
)
from eylo.common.contracts.widgets import (
    WidgetCardListPayload as WidgetCardListPayload,
)
from eylo.common.contracts.widgets import (
    WidgetCardListProps as WidgetCardListProps,
)
from eylo.common.contracts.widgets import (
    WidgetComponentPayload as WidgetComponentPayload,
)
from eylo.common.contracts.widgets import (
    WidgetDatePickerPayload as WidgetDatePickerPayload,
)
from eylo.common.contracts.widgets import (
    WidgetDatePickerProps as WidgetDatePickerProps,
)
from eylo.common.contracts.widgets import (
    WidgetDatePickerValidation as WidgetDatePickerValidation,
)
from eylo.common.contracts.widgets import (
    WidgetDividerProps as WidgetDividerProps,
)
from eylo.common.contracts.widgets import (
    WidgetFieldValidation as WidgetFieldValidation,
)
from eylo.common.contracts.widgets import (
    WidgetFormField as WidgetFormField,
)
from eylo.common.contracts.widgets import (
    WidgetFormPayload as WidgetFormPayload,
)
from eylo.common.contracts.widgets import (
    WidgetFormProps as WidgetFormProps,
)
from eylo.common.contracts.widgets import (
    WidgetImagePayload as WidgetImagePayload,
)
from eylo.common.contracts.widgets import (
    WidgetImageProps as WidgetImageProps,
)
from eylo.common.contracts.widgets import (
    WidgetOption as WidgetOption,
)
from eylo.common.contracts.widgets import (
    WidgetProgressPayload as WidgetProgressPayload,
)
from eylo.common.contracts.widgets import (
    WidgetProgressProps as WidgetProgressProps,
)
from eylo.common.contracts.widgets import (
    WidgetProgressStep as WidgetProgressStep,
)
from eylo.common.contracts.widgets import (
    WidgetRowProps as WidgetRowProps,
)
from eylo.common.contracts.widgets import (
    WidgetSchemaModel as WidgetSchemaModel,
)
from eylo.common.contracts.widgets import (
    WidgetSectionProps as WidgetSectionProps,
)
from eylo.common.contracts.widgets import (
    WidgetStackProps as WidgetStackProps,
)
from eylo.common.contracts.widgets import (
    WidgetTextPayload as WidgetTextPayload,
)
from eylo.common.contracts.widgets import (
    WidgetTextProps as WidgetTextProps,
)


class WidgetCatalogEntry(WidgetSchemaModel):
    component: str
    version: str
    status: Literal["active", "deferred"]
    description: str
    json_schema: dict[str, JsonValue] = Field(alias="schema")
    when_to_use: list[str]
    required_props: list[str]
    rules: list[str]
    example_payload: dict[str, JsonValue]

    @property
    def props_schema(self) -> dict[str, JsonValue]:
        """Resolve the catalog's object-shaped props schema without loose chaining."""
        properties = self.json_schema.get("properties")
        if isinstance(properties, dict):
            props = properties.get("props")
            if isinstance(props, dict):
                return props
        raise ValueError("Widget catalog requires an object props schema.")
