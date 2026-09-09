"""Provider-neutral widget components, typed props, and tree invariants."""

import json
from enum import StrEnum
from typing import Annotated, Dict, List, Literal, Optional, Set, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

_ALLOWED_URL_SCHEMES = ("http://", "https://", "/")


class CompoundComponentKind(StrEnum):
    FORM = "form"
    BUTTON_GROUP = "button_group"
    CARD_LIST = "card_list"
    DATE_PICKER = "date_picker"
    ALERT = "alert"
    TEXT = "text"
    IMAGE = "image"
    PROGRESS = "progress"
    DIVIDER = "divider"
    STACK = "stack"
    ROW = "row"
    SECTION = "section"


class WidgetFieldKind(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    PHONE = "phone"
    NUMBER = "number"
    TEXTAREA = "textarea"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"


class WidgetPattern(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"


class WidgetButtonVariant(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    DESTRUCTIVE = "destructive"
    GHOST = "ghost"
    OUTLINE = "outline"
    LINK = "link"


class WidgetButtonLayout(StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class WidgetSelectionMode(StrEnum):
    SINGLE = "single"
    MULTIPLE = "multiple"


class WidgetDateMode(StrEnum):
    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"


class WidgetAlertSeverity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class WidgetTextVariant(StrEnum):
    BODY = "body"
    HEADING = "heading"
    CAPTION = "caption"
    CODE = "code"


class WidgetProgressStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"


class WidgetSpacing(StrEnum):
    XS = "xs"
    SM = "sm"
    MD = "md"
    LG = "lg"
    XL = "xl"


class WidgetAlignment(StrEnum):
    START = "start"
    CENTER = "center"
    END = "end"
    STRETCH = "stretch"


class WidgetSchemaModel(BaseModel):
    """Reject undeclared LLM-generated widget data at every schema depth."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        allow_inf_nan=False,
    )


def _validate_safe_url(url: str) -> str:
    """Reject javascript:, data:, and other unsafe URL schemes."""
    if not any(url.startswith(scheme) for scheme in _ALLOWED_URL_SCHEMES):
        raise ValueError(
            f"URL must start with http://, https://, or /. Got: {url[:40]!r}"
        )
    return url


class WidgetOption(WidgetSchemaModel):
    value: str
    label: str
    description: Optional[str] = None


class WidgetFieldValidation(WidgetSchemaModel):
    min_length: Optional[int] = Field(default=None, alias="minLength")
    max_length: Optional[int] = Field(default=None, alias="maxLength")
    min: Optional[float] = None
    max: Optional[float] = None
    pattern: Optional[WidgetPattern] = None
    message: Optional[str] = None
    min_date: Optional[str] = Field(default=None, alias="minDate")
    max_date: Optional[str] = Field(default=None, alias="maxDate")


class WidgetFormField(WidgetSchemaModel):
    type: WidgetFieldKind
    name: str
    label: str
    placeholder: Optional[str] = None
    required: bool = False
    default_value: JsonValue = Field(default=None, alias="defaultValue")
    options: Optional[List[WidgetOption]] = None
    validation: Optional[WidgetFieldValidation] = None

    @model_validator(mode="after")
    def validate_options(self) -> "WidgetFormField":
        if (
            self.type in {WidgetFieldKind.SELECT, WidgetFieldKind.RADIO}
            and not self.options
        ):
            raise ValueError(f"{self.type} fields require at least one option")
        return self


class WidgetFormProps(WidgetSchemaModel):
    title: str
    description: Optional[str] = None
    fields: List[WidgetFormField] = Field(min_length=1)
    submit_label: Optional[str] = Field(default=None, alias="submitLabel")
    cancel_label: Optional[str] = Field(default=None, alias="cancelLabel")

    @model_validator(mode="after")
    def validate_unique_field_names(self) -> "WidgetFormProps":
        field_names = [field.name for field in self.fields]
        if len(field_names) != len(set(field_names)):
            raise ValueError("form field names must be unique")
        return self


class WidgetButton(WidgetSchemaModel):
    value: str
    label: str
    variant: Optional[WidgetButtonVariant] = None
    icon: Optional[str] = None


class WidgetButtonGroupProps(WidgetSchemaModel):
    question: Optional[str] = None
    layout: Optional[WidgetButtonLayout] = None
    buttons: List[WidgetButton] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_values(self) -> "WidgetButtonGroupProps":
        values = [button.value for button in self.buttons]
        if len(values) != len(set(values)):
            raise ValueError("button values must be unique")
        return self


class WidgetCard(WidgetSchemaModel):
    id: str
    title: str
    description: Optional[str] = None
    image: Optional[str] = None
    price: Optional[str] = None
    badge: Optional[str] = None
    features: Optional[List[str]] = None

    @field_validator("image")
    @classmethod
    def validate_image_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_safe_url(v)
        return v


class WidgetCardListProps(WidgetSchemaModel):
    title: Optional[str] = None
    description: Optional[str] = None
    selection_mode: Optional[WidgetSelectionMode] = Field(
        default=None, alias="selectionMode"
    )
    submit_label: Optional[str] = Field(default=None, alias="submitLabel")
    cards: List[WidgetCard] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "WidgetCardListProps":
        ids = [card.id for card in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError("card ids must be unique")
        return self


class WidgetDatePickerValidation(WidgetSchemaModel):
    min_date: Optional[str] = Field(default=None, alias="minDate")
    max_date: Optional[str] = Field(default=None, alias="maxDate")
    message: Optional[str] = None


class WidgetDatePickerProps(WidgetSchemaModel):
    label: str
    name: str
    description: Optional[str] = None
    mode: Optional[WidgetDateMode] = None
    placeholder: Optional[str] = None
    required: bool = False
    default_value: Optional[str] = Field(default=None, alias="defaultValue")
    submit_label: Optional[str] = Field(default=None, alias="submitLabel")
    validation: Optional[WidgetDatePickerValidation] = None

    @model_validator(mode="after")
    def validate_time_default(self) -> "WidgetDatePickerProps":
        if self.mode is WidgetDateMode.TIME and self.default_value:
            parts = self.default_value.split(":")
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                raise ValueError('time defaultValue must use the "HH:MM" format')
            hours, minutes = int(parts[0]), int(parts[1])
            if not (0 <= hours <= 23 and 0 <= minutes <= 59):
                raise ValueError(
                    "time defaultValue out of range: hours must be 0-23, minutes 0-59"
                )
        return self


class WidgetAlertProps(WidgetSchemaModel):
    title: Optional[str] = None
    message: str
    dismissible: bool = False
    severity: Optional[WidgetAlertSeverity] = None


class WidgetTextProps(WidgetSchemaModel):
    content: str = Field(..., description="Text or markdown content to display.")
    variant: Optional[WidgetTextVariant] = None


class WidgetImageProps(WidgetSchemaModel):
    src: str = Field(..., description="Image URL.")
    alt: str = Field(..., description="Accessible alt text.")
    caption: Optional[str] = None
    width: Optional[int] = Field(default=None, ge=1, le=2048)
    height: Optional[int] = Field(default=None, ge=1, le=2048)

    @field_validator("src")
    @classmethod
    def validate_src_url(cls, v: str) -> str:
        return _validate_safe_url(v)


class WidgetProgressStep(WidgetSchemaModel):
    label: str
    status: WidgetProgressStatus = WidgetProgressStatus.PENDING


class WidgetProgressProps(WidgetSchemaModel):
    current_step: int = Field(..., alias="currentStep", ge=1)
    total_steps: int = Field(..., alias="totalSteps", ge=1)
    label: Optional[str] = None
    steps: Optional[List[WidgetProgressStep]] = None

    @model_validator(mode="after")
    def validate_steps(self) -> "WidgetProgressProps":
        if self.current_step > self.total_steps:
            raise ValueError("currentStep cannot exceed totalSteps")
        if self.steps and len(self.steps) != self.total_steps:
            raise ValueError("steps array length must equal totalSteps")
        return self


class WidgetFormPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.FORM]
    props: WidgetFormProps


class WidgetButtonGroupPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.BUTTON_GROUP]
    props: WidgetButtonGroupProps


class WidgetCardListPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.CARD_LIST]
    props: WidgetCardListProps


class WidgetDatePickerPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.DATE_PICKER]
    props: WidgetDatePickerProps


class WidgetAlertPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.ALERT]
    props: WidgetAlertProps


class WidgetTextPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.TEXT]
    props: WidgetTextProps


class WidgetImagePayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.IMAGE]
    props: WidgetImageProps


class WidgetProgressPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.PROGRESS]
    props: WidgetProgressProps


# Structural-only components for compound widget composition.
# They compose children but produce no interactive submissions.


LAYOUT_COMPONENT_TYPES = frozenset(
    {
        CompoundComponentKind.STACK,
        CompoundComponentKind.ROW,
        CompoundComponentKind.SECTION,
    }
)
INTERACTIVE_COMPONENT_TYPES = frozenset(
    {
        CompoundComponentKind.FORM,
        CompoundComponentKind.BUTTON_GROUP,
        CompoundComponentKind.CARD_LIST,
        CompoundComponentKind.DATE_PICKER,
    }
)

SPACING_VALUES = tuple(value.value for value in WidgetSpacing)
ALIGN_VALUES = tuple(value.value for value in WidgetAlignment)


class WidgetDividerProps(WidgetSchemaModel):
    label: Optional[str] = None


class WidgetStackProps(WidgetSchemaModel):
    spacing: Optional[WidgetSpacing] = None


class WidgetRowProps(WidgetSchemaModel):
    spacing: Optional[WidgetSpacing] = None
    align: Optional[WidgetAlignment] = None


class WidgetSectionProps(WidgetSchemaModel):
    title: Optional[str] = None
    description: Optional[str] = None
    collapsible: bool = False


# Flat adjacency-list model: each component has an ID, layout components
# reference children by ID. Inspired by A2UI (Google).

# All component types recognized in compound payloads.
ALL_COMPOUND_COMPONENT_TYPES = sorted(kind.value for kind in CompoundComponentKind)

COMPOUND_MAX_DEPTH = 3
COMPOUND_MAX_COMPONENTS = 15


class WidgetDividerPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.DIVIDER]
    props: WidgetDividerProps = Field(default_factory=WidgetDividerProps)


class WidgetStackPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.STACK]
    props: WidgetStackProps = Field(default_factory=WidgetStackProps)


class WidgetRowPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.ROW]
    props: WidgetRowProps = Field(default_factory=WidgetRowProps)


class WidgetSectionPayload(WidgetSchemaModel):
    component: Literal[CompoundComponentKind.SECTION]
    props: WidgetSectionProps = Field(default_factory=WidgetSectionProps)


WidgetComponentPayload = Annotated[
    Union[
        WidgetFormPayload,
        WidgetButtonGroupPayload,
        WidgetCardListPayload,
        WidgetDatePickerPayload,
        WidgetAlertPayload,
        WidgetTextPayload,
        WidgetImagePayload,
        WidgetProgressPayload,
        WidgetDividerPayload,
        WidgetStackPayload,
        WidgetRowPayload,
        WidgetSectionPayload,
    ],
    Field(discriminator="component"),
]


class CompoundWidgetNodeFields(WidgetSchemaModel):
    """Adjacency-list identity shared by every typed component variant."""

    id: str = Field(description="Unique component identifier within the widget.")
    children: list[str] | None = Field(
        default=None,
        description="Ordered child IDs; only layout components may have children.",
    )

    @field_validator("props", mode="before", check_fields=False)
    @classmethod
    def parse_props(cls, value: object) -> object:
        """Accept strict-provider JSON strings before the component schema runs."""
        if not isinstance(value, str):
            return value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("props must be a valid JSON object string") from error
        if not isinstance(parsed, dict):
            raise ValueError("props JSON must decode to an object")
        return parsed

    @field_validator("children", mode="before")
    @classmethod
    def normalize_empty_children(cls, value: object) -> object:
        return None if value == [] else value


class CompoundWidgetFormNode(WidgetFormPayload, CompoundWidgetNodeFields):
    """A form component with typed props and tree identity."""


class CompoundWidgetButtonGroupNode(WidgetButtonGroupPayload, CompoundWidgetNodeFields):
    """A button-group component with typed props and tree identity."""


class CompoundWidgetCardListNode(WidgetCardListPayload, CompoundWidgetNodeFields):
    """A card-list component with typed props and tree identity."""


class CompoundWidgetDatePickerNode(WidgetDatePickerPayload, CompoundWidgetNodeFields):
    """A date-picker component with typed props and tree identity."""


class CompoundWidgetAlertNode(WidgetAlertPayload, CompoundWidgetNodeFields):
    """An alert component with typed props and tree identity."""


class CompoundWidgetTextNode(WidgetTextPayload, CompoundWidgetNodeFields):
    """A text component with typed props and tree identity."""


class CompoundWidgetImageNode(WidgetImagePayload, CompoundWidgetNodeFields):
    """An image component with typed props and tree identity."""


class CompoundWidgetProgressNode(WidgetProgressPayload, CompoundWidgetNodeFields):
    """A progress component with typed props and tree identity."""


class CompoundWidgetDividerNode(WidgetDividerPayload, CompoundWidgetNodeFields):
    """A divider component with typed props and tree identity."""


class CompoundWidgetStackNode(WidgetStackPayload, CompoundWidgetNodeFields):
    """A stack component with typed props and tree identity."""


class CompoundWidgetRowNode(WidgetRowPayload, CompoundWidgetNodeFields):
    """A row component with typed props and tree identity."""


class CompoundWidgetSectionNode(WidgetSectionPayload, CompoundWidgetNodeFields):
    """A section component with typed props and tree identity."""


CompoundWidgetNode = Annotated[
    Union[
        CompoundWidgetFormNode,
        CompoundWidgetButtonGroupNode,
        CompoundWidgetCardListNode,
        CompoundWidgetDatePickerNode,
        CompoundWidgetAlertNode,
        CompoundWidgetTextNode,
        CompoundWidgetImageNode,
        CompoundWidgetProgressNode,
        CompoundWidgetDividerNode,
        CompoundWidgetStackNode,
        CompoundWidgetRowNode,
        CompoundWidgetSectionNode,
    ],
    Field(discriminator="component"),
]


class CompoundWidgetPayload(WidgetSchemaModel):
    """Top-level compound widget payload — adjacency-list model."""

    components: List[CompoundWidgetNode] = Field(
        ...,
        min_length=1,
        max_length=COMPOUND_MAX_COMPONENTS,
        description="Flat list of components with ID-based relationships.",
    )
    root: str = Field(
        ...,
        description="ID of the root component that anchors the tree.",
    )

    @model_validator(mode="after")
    def validate_compound_tree(self) -> "CompoundWidgetPayload":
        """Validate structural integrity of the compound widget tree."""
        ids = [node.id for node in self.components]
        id_set = set(ids)

        # Unique IDs
        if len(ids) != len(id_set):
            seen: Set[str] = set()
            dupes: list[str] = []
            for node_id in ids:
                if node_id in seen:
                    dupes.append(node_id)
                seen.add(node_id)
            raise ValueError(f"Duplicate component IDs: {dupes}")

        # Root exists
        if self.root not in id_set:
            raise ValueError(
                f"Root '{self.root}' does not match any component ID. "
                f"Available IDs: {sorted(id_set)}"
            )

        # Build lookup
        node_map = {node.id: node for node in self.components}

        # Only layout components may have children
        for node in self.components:
            if (
                node.children is not None
                and node.component not in LAYOUT_COMPONENT_TYPES
            ):
                raise ValueError(
                    f"Component '{node.id}' (type '{node.component}') "
                    f"cannot have children — only layout components "
                    f"({', '.join(sorted(LAYOUT_COMPONENT_TYPES))}) support children."
                )

        # All child references must point to existing IDs. A compound widget is
        # a tree, not a DAG: one rendered component cannot have two parents.
        parent_by_child: Dict[str, str] = {}
        for node in self.components:
            for child_id in node.children or []:
                if child_id not in id_set:
                    raise ValueError(
                        f"Component '{node.id}' references unknown child '{child_id}'. "
                        f"Available IDs: {sorted(id_set)}"
                    )
                previous_parent = parent_by_child.get(child_id)
                if previous_parent is not None:
                    raise ValueError(
                        f"Component '{child_id}' has multiple parents: "
                        f"'{previous_parent}' and '{node.id}'."
                    )
                parent_by_child[child_id] = node.id

        # Detect cycles via DFS
        visited: Set[str] = set()
        in_stack: Set[str] = set()

        def _dfs(nid: str) -> None:
            if nid in in_stack:
                raise ValueError(f"Cycle detected involving component '{nid}'.")
            if nid in visited:
                return
            in_stack.add(nid)
            for child_id in node_map[nid].children or []:
                _dfs(child_id)
            in_stack.discard(nid)
            visited.add(nid)

        _dfs(self.root)

        # Detect orphans (nodes unreachable from root)
        orphans = id_set - visited
        if orphans:
            raise ValueError(
                f"Orphan components not reachable from root '{self.root}': "
                f"{sorted(orphans)}"
            )

        # Max depth check
        def _depth(nid: str) -> int:
            children = node_map[nid].children or []
            if not children:
                return 1
            return 1 + max(_depth(c) for c in children)

        depth = _depth(self.root)
        if depth > COMPOUND_MAX_DEPTH:
            raise ValueError(
                f"Compound widget tree depth is {depth}, "
                f"exceeds maximum of {COMPOUND_MAX_DEPTH}."
            )

        interactive_nodes = [
            node.id
            for node in self.components
            if node.component in INTERACTIVE_COMPONENT_TYPES
        ]
        if len(interactive_nodes) > 1:
            raise ValueError(
                "Compound widgets support one interactive component per message. "
                f"Found: {interactive_nodes}"
            )

        return self
