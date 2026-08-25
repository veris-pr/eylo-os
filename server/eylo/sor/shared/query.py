"""Eylo-owned collection query and grid metadata contracts."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eylo.sor.shared.contracts import SorProfile

SorFilterValue = str | int | float | bool | None


class SorFilterGroupOperator(str, Enum):
    AND = "and"
    OR = "or"


class SorFilterOperator(str, Enum):
    IS = "is"
    IS_NOT = "is_not"
    IS_ANY_OF = "is_any_of"
    INCLUDES_ANY = "includes_any"
    INCLUDES_ALL = "includes_all"
    INCLUDES_NONE = "includes_none"
    BEFORE = "before"
    AFTER = "after"


class SorSortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class SorNullPlacement(str, Enum):
    FIRST = "first"
    LAST = "last"


class SorFilterCondition(BaseModel):
    """One typed predicate whose field is resolved by an entity contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["condition"] = "condition"
    field: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
    operator: SorFilterOperator
    values: tuple[SorFilterValue, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_value_count(self) -> "SorFilterCondition":
        single_value = {
            SorFilterOperator.IS,
            SorFilterOperator.BEFORE,
            SorFilterOperator.AFTER,
        }
        if self.operator in single_value and len(self.values) != 1:
            raise ValueError(f"Filter operator {self.operator.value} needs one value.")
        return self


class SorFilterGroup(BaseModel):
    """Recursive AND/OR expression; the empty root means no filtering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["group"] = "group"
    op: SorFilterGroupOperator = SorFilterGroupOperator.AND
    children: tuple[SorFilterCondition | SorFilterGroup, ...] = Field(
        default=(),
        max_length=100,
    )


class SorSortTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
    direction: SorSortDirection = SorSortDirection.ASC
    nulls: SorNullPlacement = SorNullPlacement.LAST


class SorGroupTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
    direction: SorSortDirection = SorSortDirection.ASC


class SorCollectionQuery(BaseModel):
    """Renderer-independent server query for any canonical SOR collection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_ids: tuple[UUID, ...] = Field(default=(), max_length=50)
    search: str = Field(default="", max_length=200)
    filters: SorFilterGroup = Field(default_factory=SorFilterGroup)
    sort: tuple[SorSortTerm, ...] = Field(default=(), max_length=5)
    group: tuple[SorGroupTerm, ...] = Field(default=(), max_length=3)
    columns: tuple[str, ...] = Field(default=(), max_length=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("search")
    @classmethod
    def normalize_search(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_query_shape(self) -> "SorCollectionQuery":
        _validate_filter_tree(self.filters)
        _require_unique([str(item) for item in self.source_ids], "source")
        _require_unique([item.field for item in self.sort], "sort field")
        _require_unique([item.field for item in self.group], "group field")
        _require_unique(list(self.columns), "column")
        return self


class SorGridColumnKind(str, Enum):
    TEXT = "TEXT"
    LONG_TEXT = "LONG_TEXT"
    ENUM = "ENUM"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    REFERENCE = "REFERENCE"
    LINK = "LINK"
    STRING_ARRAY = "STRING_ARRAY"


class SorGridColumnImportance(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    METADATA = "METADATA"


class SorGridRowAction(str, Enum):
    VIEW = "VIEW"


class SorGridColumn(BaseModel):
    """Product column semantics consumed by any replaceable grid renderer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
    label: str = Field(min_length=1, max_length=120)
    kind: SorGridColumnKind
    importance: SorGridColumnImportance
    default_visible: bool = True
    filterable: bool = True
    sortable: bool = True
    groupable: bool = False
    wraps: bool = False
    custom: bool = False


class SorGridContract(BaseModel):
    """Versioned Eylo contract; a grid package may only render this model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["sor-grid-v1"] = "sor-grid-v1"
    profile: SorProfile
    entity: str = Field(min_length=1, max_length=128)
    columns: tuple[SorGridColumn, ...] = Field(min_length=1, max_length=200)
    row_actions: tuple[SorGridRowAction, ...] = (SorGridRowAction.VIEW,)

    @model_validator(mode="after")
    def validate_grid(self) -> "SorGridContract":
        _require_unique([column.key for column in self.columns], "grid column")
        _require_unique([action.value for action in self.row_actions], "row action")
        return self


def _validate_filter_tree(root: SorFilterGroup) -> None:
    count = 0

    def visit(group: SorFilterGroup, depth: int) -> None:
        nonlocal count
        if depth > 5:
            raise ValueError("SOR filter groups may be nested at most five levels.")
        for child in group.children:
            count += 1
            if count > 100:
                raise ValueError("SOR filters may contain at most 100 nodes.")
            if isinstance(child, SorFilterGroup):
                visit(child, depth + 1)

    visit(root, 1)


def _require_unique(values: list[str], kind: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"SOR {kind} values must be unique.")


__all__ = [
    "SorCollectionQuery",
    "SorFilterCondition",
    "SorFilterGroup",
    "SorFilterGroupOperator",
    "SorFilterOperator",
    "SorFilterValue",
    "SorGridColumn",
    "SorGridColumnImportance",
    "SorGridColumnKind",
    "SorGridContract",
    "SorGridRowAction",
    "SorGroupTerm",
    "SorNullPlacement",
    "SorSortDirection",
    "SorSortTerm",
]
