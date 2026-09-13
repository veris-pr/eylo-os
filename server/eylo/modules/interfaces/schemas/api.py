"""Interface catalog contracts and exports of the shared widget schema."""

from enum import StrEnum

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


class WidgetCatalogStatus(StrEnum):
    ACTIVE = "active"
    DEFERRED = "deferred"


class WidgetSchemaType(StrEnum):
    """Types used by the widget catalog, not the general JSON Schema dialect."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    NULL = "null"
    ANY = "any"


class WidgetPropertySchema(WidgetSchemaModel):
    """Code-authored widget property description, including its nested fields.

    This is the catalog's existing subset of schema keywords. `any` and
    `optional` are documentation hints, not vendor JSON Schema extensions.
    General tool schemas remain owned by PlatformToolInputSchema.
    """

    type: WidgetSchemaType | list[WidgetSchemaType] | None = None
    optional: bool = False
    enum: list[str] | None = None
    description: str | None = None
    required: list[str] = Field(default_factory=list)
    properties: dict[str, "WidgetPropertySchema"] | None = None
    items: "WidgetPropertySchema | None" = None
    additional_properties: bool | None = Field(
        default=None, alias="additionalProperties"
    )
    min_items: int | None = Field(default=None, alias="minItems")
    max_items: int | None = Field(default=None, alias="maxItems")

    def to_json_schema(self) -> dict[str, JsonValue]:
        """Preserve authored keywords and omission when crossing to tool JSON."""
        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)


class WidgetCatalogEntry(WidgetSchemaModel):
    component: CompoundComponentKind
    version: str
    status: WidgetCatalogStatus
    description: str
    json_schema: WidgetPropertySchema = Field(alias="schema")
    when_to_use: list[str]
    required_props: list[str]
    rules: list[str]
    example_payload: dict[str, JsonValue]

    @property
    def props_schema(self) -> WidgetPropertySchema:
        """Resolve the catalog-owned props descriptor without JSON reparsing."""
        props = (self.json_schema.properties or {}).get("props")
        if props is not None:
            return props
        raise ValueError("Widget catalog requires an object props schema.")
