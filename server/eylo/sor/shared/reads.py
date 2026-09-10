"""Tenant-scoped SOR audit queries and renderer-independent grid projection."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, InstanceOf, model_validator
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy import (
    String,
    and_,
    asc,
    desc,
    func,
    not_,
    or_,
    select,
    tuple_,
)
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, aliased, load_only
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from eylo.sor.shared.contracts import (
    SorCanonicalRelationKind,
    SorCustomFieldType,
    SorFieldMappingDirection,
    SorFieldMappingState,
    SorProfile,
    SorRelationshipDirection,
    SorRelationshipRole,
)
from eylo.sor.shared.models import (
    SorCustomFieldDefinitionModel,
    SorCustomFieldValueModel,
    SorFieldMappingModel,
    SorProfileRecordModel,
    SorRecordModel,
    SorRecordRelationModel,
    SorSourceModel,
    SorSourceStreamModel,
)
from eylo.sor.shared.query import (
    SorCollectionQuery,
    SorFilterCondition,
    SorFilterGroup,
    SorFilterOperator,
    SorGridColumn,
    SorGridColumnImportance,
    SorGridColumnKind,
    SorGridContract,
    SorNullPlacement,
    SorSortDirection,
)
from eylo.sor.shared.schemas import (
    SorCollectionPageResponse,
    SorCollectionRowResponse,
    SorCustomFieldValueResponse,
    SorFilterOptionResponse,
    SorFilterOptionsResponse,
    SorFreshnessResponse,
    SorRecordDetailResponse,
    SorRecordRelationResponse,
    SorSourceListResponse,
    SorSourceResponse,
)

_CURSOR_VERSION = 1
_COMMON_GRID_COLUMN_KEYS = frozenset({"source", "source_updated_at", "projected_at"})
_FILTER_OPTION_KINDS = frozenset(
    {
        SorGridColumnKind.ENUM,
        SorGridColumnKind.BOOLEAN,
        SorGridColumnKind.REFERENCE,
        SorGridColumnKind.STRING_ARRAY,
    }
)


class SorReadError(Exception):
    """Base safe SOR read failure."""


class SorReadNotFoundError(SorReadError):
    """Requested source, entity, or record is unavailable in this tenant."""


class SorReadQueryError(SorReadError):
    """Collection query does not satisfy its field contract."""


class SorReadInvariantError(SorReadError):
    """Persisted shared and profile projections disagree."""


async def read_record_relations(
    session: AsyncSession,
    *,
    organization_id: UUID,
    record_ids: Sequence[UUID],
) -> dict[UUID, tuple[SorRecordRelationResponse, ...]]:
    """Read live same-source edges for exact tenant-owned record identities.

    Both endpoints must still be live. This keeps an active edge from exposing
    the identity of a record that a later sync tombstoned without relying on
    every caller to reconstruct the relation lifecycle correctly.
    """
    selected_ids = tuple(dict.fromkeys(record_ids))
    if not selected_ids:
        return {}

    from_record = aliased(SorRecordModel)
    to_record = aliased(SorRecordModel)
    rows = (
        await session.execute(
            select(
                SorRecordRelationModel,
                from_record.id,
                from_record.canonical_entity_kind,
                from_record.human_external_key,
                from_record.source_url,
                to_record.id,
                to_record.canonical_entity_kind,
                to_record.human_external_key,
                to_record.source_url,
            )
            .join(
                from_record,
                and_(
                    from_record.id == SorRecordRelationModel.from_record_id,
                    from_record.source_id == SorRecordRelationModel.source_id,
                    from_record.organization_id
                    == SorRecordRelationModel.organization_id,
                ),
            )
            .join(
                to_record,
                and_(
                    to_record.id == SorRecordRelationModel.to_record_id,
                    to_record.source_id == SorRecordRelationModel.source_id,
                    to_record.organization_id == SorRecordRelationModel.organization_id,
                ),
            )
            .where(
                SorRecordRelationModel.organization_id == organization_id,
                or_(
                    SorRecordRelationModel.from_record_id.in_(selected_ids),
                    SorRecordRelationModel.to_record_id.in_(selected_ids),
                ),
                SorRecordRelationModel.tombstoned_at.is_(None),
                SorRecordRelationModel.deleted.is_(False),
                from_record.tombstoned_at.is_(None),
                from_record.deleted.is_(False),
                to_record.tombstoned_at.is_(None),
                to_record.deleted.is_(False),
            )
            .order_by(
                SorRecordRelationModel.canonical_relation_kind.asc(),
                SorRecordRelationModel.relationship_role.asc(),
                SorRecordRelationModel.id.asc(),
            )
        )
    ).all()
    selected = set(selected_ids)
    grouped: dict[UUID, list[SorRecordRelationResponse]] = {
        record_id: [] for record_id in selected_ids
    }
    for (
        row,
        from_record_id,
        from_entity,
        from_key,
        from_url,
        to_record_id,
        to_entity,
        to_key,
        to_url,
    ) in rows:
        if row.from_record_id in selected:
            grouped[row.from_record_id].append(
                SorRecordRelationResponse(
                    kind=SorCanonicalRelationKind(row.canonical_relation_kind),
                    role=SorRelationshipRole(row.relationship_role),
                    vendor_kind=row.vendor_relation_kind or None,
                    direction=SorRelationshipDirection.OUTGOING,
                    record_id=to_record_id,
                    record_entity=to_entity,
                    record_key=to_key,
                    source_url=to_url,
                )
            )
        if row.to_record_id in selected:
            grouped[row.to_record_id].append(
                SorRecordRelationResponse(
                    kind=SorCanonicalRelationKind(row.canonical_relation_kind),
                    role=SorRelationshipRole(row.relationship_role),
                    vendor_kind=row.vendor_relation_kind or None,
                    direction=SorRelationshipDirection.INCOMING,
                    record_id=from_record_id,
                    record_entity=from_entity,
                    record_key=from_key,
                    source_url=from_url,
                )
            )
    return {record_id: tuple(relations) for record_id, relations in grouped.items()}


def _custom_field_key(definition_id: UUID) -> str:
    """Return the stable, renderer-independent key for one custom field."""
    return f"custom.{definition_id}"


def _custom_column_labels(
    rows: Sequence[
        tuple[
            SorCustomFieldDefinitionModel,
            SorFieldMappingModel,
            SorSourceModel,
        ]
    ],
) -> dict[UUID, str]:
    """Make source-owned field labels unambiguous in a combined grid."""
    labels = Counter(definition.label.strip().casefold() for definition, _, _ in rows)
    labels_by_source = Counter(
        (definition.label.strip().casefold(), source.id)
        for definition, _, source in rows
    )
    labels_by_source_name = Counter(
        (definition.label.strip().casefold(), source.name.strip().casefold())
        for definition, _, source in rows
    )
    labels_by_vendor = Counter(
        (
            definition.label.strip().casefold(),
            source.name.strip().casefold(),
            source.vendor_key.casefold(),
        )
        for definition, _, source in rows
    )

    result: dict[UUID, str] = {}
    for definition, _, source in rows:
        label = definition.label.strip() or definition.vendor_field_key
        normalized = label.casefold()
        qualifier: str | None = None
        if labels[normalized] > 1:
            if labels_by_source[(normalized, source.id)] > 1:
                qualifier = f"{source.name} · {definition.vendor_field_key}"
            elif (
                labels_by_source_name[(normalized, source.name.strip().casefold())] == 1
            ):
                qualifier = source.name
            elif (
                labels_by_vendor[
                    (
                        normalized,
                        source.name.strip().casefold(),
                        source.vendor_key.casefold(),
                    )
                ]
                == 1
            ):
                qualifier = f"{source.name} · {source.vendor_key}"
            else:
                qualifier = (
                    f"{source.name} · {source.vendor_key} · {str(source.id)[:8]}"
                )
        result[definition.id] = _bounded_grid_label(label, qualifier=qualifier)
    return result


def _bounded_grid_label(label: str, *, qualifier: str | None = None) -> str:
    """Preserve the useful ends of a custom label inside the API contract."""
    limit = 120
    if qualifier is None:
        return _truncate_grid_label(label, limit)
    bounded_qualifier = _truncate_grid_label(qualifier, 48)
    separator = " · "
    bounded_label = _truncate_grid_label(
        label,
        limit - len(separator) - len(bounded_qualifier),
    )
    return f"{bounded_label}{separator}{bounded_qualifier}"


def _truncate_grid_label(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1].rstrip()}…"


class SorReadFieldSpec(BaseModel):
    """One canonical field exposed to filters, grids, and response values."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    key: str
    label: str
    kind: SorGridColumnKind
    importance: SorGridColumnImportance
    expression: SkipJsonSchema[
        InstanceOf[QueryableAttribute[Any]] | InstanceOf[ColumnElement[Any]]
    ] = Field(exclude=True, repr=False)
    read_value: SkipJsonSchema[
        Callable[[SorRecordModel, SorProfileRecordModel | None, SorSourceModel], object]
    ] = Field(exclude=True, repr=False)
    default_visible: bool = True
    filterable: bool = True
    sortable: bool = True
    groupable: bool = False
    wraps: bool = False
    reference_entity: str | None = None
    value_key: str | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        """Keep human-reference metadata attached only to reference-shaped fields."""
        if self.reference_entity is None:
            return self
        if self.kind not in {
            SorGridColumnKind.REFERENCE,
            SorGridColumnKind.STRING_ARRAY,
        }:
            raise ValueError(
                f"SOR field '{self.key}' cannot resolve a non-reference value."
            )
        if not self.reference_entity.strip():
            raise ValueError(f"SOR field '{self.key}' reference entity is empty.")
        if self.value_key is None or not self.value_key.strip():
            raise ValueError(f"SOR field '{self.key}' reference value key is empty.")
        return self

    @property
    def orm_attribute(self) -> QueryableAttribute[Any]:
        """Selective ORM loading accepts mapped attributes, never computed SQL."""
        if not isinstance(self.expression, QueryableAttribute):
            raise ValueError(f"SOR field '{self.key}' is not a mapped ORM attribute.")
        return self.expression

    @property
    def sql_expression(self) -> ColumnElement[Any]:
        """Keep custom-dataset expressions intact and translate mapped attributes."""
        if isinstance(self.expression, QueryableAttribute):
            return self.expression.__clause_element__()
        return self.expression

    def grid_column(self) -> SorGridColumn:
        return SorGridColumn(
            key=self.key,
            label=self.label,
            kind=self.kind,
            importance=self.importance,
            default_visible=self.default_visible,
            filterable=self.filterable,
            sortable=self.sortable,
            groupable=self.groupable,
            wraps=self.wraps,
        )


class SorEntityReadSpec(BaseModel):
    """Explicit profile-owned query contract for one canonical entity."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    profile: SorProfile
    entity: str
    model: SkipJsonSchema[type[SorProfileRecordModel] | None] = Field(
        exclude=True, repr=False
    )
    fields: tuple[SorReadFieldSpec, ...]
    vendor_object_key: str | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        """Reject ambiguous profile contracts before an API request reaches them."""
        field_keys = tuple(field.key for field in self.fields)
        if len(field_keys) != len(set(field_keys)):
            raise ValueError(
                f"SOR {self.profile.value}/{self.entity} read field keys must be unique."
            )
        conflicts = sorted(set(field_keys) & _COMMON_GRID_COLUMN_KEYS)
        if conflicts:
            raise ValueError(
                f"SOR {self.profile.value}/{self.entity} cannot redefine shared grid "
                "columns: " + ", ".join(conflicts) + "."
            )
        if self.model is not None:
            for field in self.fields:
                field.orm_attribute
        return self


class _CustomColumn(BaseModel):
    """Runtime custom-column context; ORM and SQL dependencies are not snapshots."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    key: str
    definition: SkipJsonSchema[InstanceOf[SorCustomFieldDefinitionModel]] = Field(
        exclude=True, repr=False
    )
    field_mapping: SkipJsonSchema[InstanceOf[SorFieldMappingModel]] = Field(
        exclude=True, repr=False
    )
    expression: SkipJsonSchema[InstanceOf[ColumnElement[Any]]] = Field(
        exclude=True, repr=False
    )
    grid_column: SorGridColumn


class _FieldContract(BaseModel):
    """Filter semantics with identity-preserved SQL and optional custom authority."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    expression: SkipJsonSchema[InstanceOf[ColumnElement[Any]]] = Field(
        exclude=True, repr=False
    )
    grid_column: SorGridColumn
    custom_definition: SkipJsonSchema[InstanceOf[SorCustomFieldDefinitionModel] | None] = (
        Field(default=None, exclude=True, repr=False)
    )
    reference_entity: str | None = None


class _OrderTerm(BaseModel):
    """Validated ordering semantics; SQL expressions remain runtime-only."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    expression: SkipJsonSchema[InstanceOf[ColumnElement[Any]]] = Field(
        exclude=True, repr=False
    )
    direction: SorSortDirection
    nulls: SorNullPlacement


type _CursorScalar = str | int | float | bool | Decimal | datetime | date | UUID | None


class _Cursor(BaseModel):
    """Decoded keyset values after wire validation and query binding."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    values: tuple[_CursorScalar, ...]
    record_id: UUID


class _ReadRow(BaseModel):
    """Transaction-owned projection rows, not serializable API response values."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    record: SkipJsonSchema[InstanceOf[SorRecordModel]] = Field(exclude=True, repr=False)
    extension: SkipJsonSchema[InstanceOf[SorProfileRecordModel] | None] = Field(
        exclude=True, repr=False
    )
    source: SkipJsonSchema[InstanceOf[SorSourceModel]] = Field(exclude=True, repr=False)
    sort_values: tuple[object, ...] = Field(exclude=True, repr=False)


async def resolve_reference_labels(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reference_keys: Sequence[tuple[UUID, str, str]],
) -> dict[tuple[UUID, str, str], str]:
    """Resolve unambiguous same-source canonical identities to human labels."""
    selected_keys = tuple(
        sorted(set(reference_keys), key=lambda item: tuple(map(str, item)))
    )
    if not selected_keys:
        return {}
    rows = (
        await session.scalars(
            select(SorRecordModel)
            .where(
                SorRecordModel.organization_id == organization_id,
                tuple_(
                    SorRecordModel.source_id,
                    SorRecordModel.canonical_entity_kind,
                    SorRecordModel.vendor_external_id,
                ).in_(selected_keys),
                SorRecordModel.tombstoned_at.is_(None),
                SorRecordModel.deleted.is_(False),
            )
            .options(
                load_only(
                    SorRecordModel.source_id,
                    SorRecordModel.canonical_entity_kind,
                    SorRecordModel.vendor_external_id,
                    SorRecordModel.human_external_key,
                )
            )
        )
    ).all()
    labels: dict[tuple[UUID, str, str], str] = {}
    ambiguous: set[tuple[UUID, str, str]] = set()
    for row in rows:
        key = (
            row.source_id,
            row.canonical_entity_kind,
            row.vendor_external_id,
        )
        label = row.human_external_key.strip() if row.human_external_key else ""
        if not label:
            continue
        if key in labels:
            ambiguous.add(key)
        else:
            labels[key] = label
    for key in ambiguous:
        labels.pop(key, None)
    return labels


def reference_external_ids(value: object) -> tuple[str, ...]:
    """Return stable scalar or list identities from one reference-shaped value."""
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def reference_display_value(
    value: object,
    *,
    source_id: UUID,
    entity: str,
    labels: Mapping[tuple[UUID, str, str], str],
) -> object | None:
    """Return a readable mirror only when at least one identity resolves."""
    if isinstance(value, str):
        return labels.get((source_id, entity, value))
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return None
    changed = False
    display: list[object] = []
    for item in value:
        if isinstance(item, str):
            label = labels.get((source_id, entity, item))
            if label is not None:
                display.append(label)
                changed = True
                continue
        display.append(item)
    return display if changed else None


class SorSourceReadService:
    """Project tenant-owned source headers without resolving credentials."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, *, organization_id: UUID) -> SorSourceListResponse:
        rows = (
            await self.session.scalars(
                select(SorSourceModel)
                .where(
                    SorSourceModel.organization_id == organization_id,
                    SorSourceModel.deleted.is_(False),
                )
                .order_by(SorSourceModel.name.asc(), SorSourceModel.id.asc())
            )
        ).all()
        return SorSourceListResponse(
            items=tuple(SorSourceResponse.model_validate(row) for row in rows)
        )

    async def get(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
    ) -> SorSourceResponse:
        row = await self.session.scalar(
            select(SorSourceModel).where(
                SorSourceModel.organization_id == organization_id,
                SorSourceModel.id == source_id,
                SorSourceModel.deleted.is_(False),
            )
        )
        if row is None:
            raise SorReadNotFoundError("SOR source not found.")
        return SorSourceResponse.model_validate(row)


class SorCollectionReadService:
    """Execute one Eylo-owned collection contract over a profile extension."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def query(
        self,
        *,
        organization_id: UUID,
        spec: SorEntityReadSpec,
        query: SorCollectionQuery,
    ) -> SorCollectionPageResponse:
        source_ids = await self._resolve_source_ids(
            organization_id=organization_id,
            profile=spec.profile,
            requested=query.source_ids,
        )
        custom_columns = await self._custom_columns(
            organization_id=organization_id,
            spec=spec,
            source_ids=source_ids,
        )
        field_contract = self._field_contract(spec, custom_columns)
        grid = self._grid(spec, custom_columns)
        self._validate_query(query, field_contract=field_contract, grid=grid)
        cursor = _decode_cursor(query.cursor, fingerprint=_query_fingerprint(query))
        selected_columns = frozenset(query.columns) if query.columns else None

        predicates: list[ColumnElement[bool]] = [
            SorRecordModel.organization_id == organization_id,
            SorRecordModel.profile == spec.profile,
            SorRecordModel.canonical_entity_kind == spec.entity,
            SorRecordModel.tombstoned_at.is_(None),
            SorRecordModel.deleted.is_(False),
            SorSourceModel.deleted.is_(False),
        ]
        if spec.model is not None:
            predicates.append(spec.model.deleted.is_(False))
        if spec.vendor_object_key is not None:
            predicates.append(
                SorRecordModel.vendor_object_key == spec.vendor_object_key
            )
        if query.source_ids:
            predicates.append(SorRecordModel.source_id.in_(source_ids))
        if query.search:
            predicates.append(
                SorRecordModel.search_vector.op("@@")(
                    func.websearch_to_tsquery("simple", query.search)
                )
            )
        filter_expression = _compile_filter_group(
            query.filters,
            field_contract=field_contract,
        )
        if filter_expression is not None:
            predicates.append(filter_expression)

        order_terms = _compile_order_terms(query, field_contract=field_contract)
        if cursor is not None:
            predicates.append(_seek_after(cursor, order_terms=order_terms))
        selected: list[Any] = [SorRecordModel]
        if spec.model is not None:
            selected.append(spec.model)
        selected.extend([SorSourceModel, *(term.expression for term in order_terms)])
        statement = select(*selected)
        if spec.model is not None:
            statement = statement.join(
                spec.model,
                spec.model.record_id == SorRecordModel.id,
            )
        statement = (
            statement.join(
                SorSourceModel,
                SorSourceModel.id == SorRecordModel.source_id,
            )
            .where(*predicates)
            .order_by(*_order_expressions(order_terms))
            .limit(query.limit + 1)
        )
        record_attributes = (
            SorRecordModel.id,
            SorRecordModel.source_id,
            SorRecordModel.vendor_external_id,
            SorRecordModel.human_external_key,
            SorRecordModel.source_url,
            SorRecordModel.source_created_at,
            SorRecordModel.source_updated_at,
            SorRecordModel.projected_at,
        )
        source_attributes = (
            SorSourceModel.id,
            SorSourceModel.name,
            SorSourceModel.vendor_key,
            SorSourceModel.last_successful_sync_at,
            SorSourceModel.freshness_target_seconds,
        )
        load_options = [
            load_only(*record_attributes),
            load_only(*source_attributes),
        ]
        if spec.model is not None:
            selected_fields = (
                spec.fields
                if selected_columns is None
                else tuple(
                    field for field in spec.fields if field.key in selected_columns
                )
            )
            load_options.append(
                load_only(
                    spec.model.record_id,
                    *(field.orm_attribute for field in selected_fields),
                )
            )
        statement = statement.options(*load_options)
        raw_rows = (await self.session.execute(statement)).all()
        has_more = len(raw_rows) > query.limit
        page_rows = tuple(
            self._read_row(spec=spec, row=row) for row in raw_rows[: query.limit]
        )
        record_ids = [row.record.id for row in page_rows]
        selected_custom_definition_ids = (
            {
                column.definition.id
                for column in custom_columns
                if column.key in selected_columns
            }
            if selected_columns is not None
            else None
        )
        custom_values = await self._custom_values(
            organization_id=organization_id,
            record_ids=record_ids,
            field_definition_ids=selected_custom_definition_ids,
        )
        display_values = await self._display_values(
            organization_id=organization_id,
            spec=spec,
            rows=page_rows,
            selected_columns=selected_columns,
        )
        items = tuple(
            self._row_response(
                spec=spec,
                record=row.record,
                extension=row.extension,
                source=row.source,
                custom_values=custom_values.get(row.record.id, ()),
                display_values=display_values.get(row.record.id, {}),
                selected_columns=selected_columns,
            )
            for row in page_rows
        )
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = _encode_cursor(
                values=last.sort_values,
                record_id=last.record.id,
                fingerprint=_query_fingerprint(query),
            )
        return SorCollectionPageResponse(
            query=query,
            grid=grid,
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def detail(
        self,
        *,
        organization_id: UUID,
        spec: SorEntityReadSpec,
        record_id: UUID,
    ) -> SorRecordDetailResponse:
        selected: list[Any] = [SorRecordModel]
        if spec.model is not None:
            selected.append(spec.model)
        selected.append(SorSourceModel)
        statement = select(*selected)
        if spec.model is not None:
            statement = statement.join(
                spec.model,
                spec.model.record_id == SorRecordModel.id,
            )
        predicates: list[ColumnElement[bool]] = [
            SorRecordModel.id == record_id,
            SorRecordModel.organization_id == organization_id,
            SorRecordModel.profile == spec.profile,
            SorRecordModel.canonical_entity_kind == spec.entity,
            SorRecordModel.tombstoned_at.is_(None),
            SorRecordModel.deleted.is_(False),
            SorSourceModel.deleted.is_(False),
        ]
        if spec.model is not None:
            predicates.append(spec.model.deleted.is_(False))
        if spec.vendor_object_key is not None:
            predicates.append(
                SorRecordModel.vendor_object_key == spec.vendor_object_key
            )
        statement = statement.join(
            SorSourceModel,
            SorSourceModel.id == SorRecordModel.source_id,
        ).where(*predicates)
        raw_row = (await self.session.execute(statement)).one_or_none()
        if raw_row is None:
            raise SorReadNotFoundError("SOR record not found.")
        row = self._read_row(spec=spec, row=raw_row)
        record, extension, source = row.record, row.extension, row.source
        custom_values = await self._custom_values(
            organization_id=organization_id,
            record_ids=[record.id],
        )
        display_values = await self._display_values(
            organization_id=organization_id,
            spec=spec,
            rows=(row,),
        )
        relations = await self._relations(
            organization_id=organization_id,
            record=record,
        )
        return SorRecordDetailResponse(
            record=self._row_response(
                spec=spec,
                record=record,
                extension=extension,
                source=source,
                custom_values=custom_values.get(record.id, ()),
                display_values=display_values.get(record.id, {}),
            ),
            selected_source_payload=_json_mapping(record.selected_raw_payload),
            source_revision=record.source_revision,
            mapping_revision_id=record.mapping_revision_id,
            mapping_projection_version=record.mapping_projection_version,
            relations=relations,
        )

    @staticmethod
    def _read_row(*, spec: SorEntityReadSpec, row: Sequence[object]) -> _ReadRow:
        """Normalize SQL rows so all collection modes share one query engine."""
        record = row[0]
        if not isinstance(record, SorRecordModel):
            raise SorReadInvariantError("SOR query did not return a shared record.")
        if spec.model is None:
            extension = None
            source = row[1]
            sort_values = tuple(row[2:])
        else:
            extension = row[1]
            source = row[2]
            sort_values = tuple(row[3:])
            if not isinstance(extension, spec.model):
                raise SorReadInvariantError(
                    "SOR query did not return its profile extension."
                )
        if not isinstance(source, SorSourceModel):
            raise SorReadInvariantError("SOR query did not return its source.")
        return _ReadRow(
            record=record,
            extension=extension,
            source=source,
            sort_values=sort_values,
        )

    async def grid(
        self,
        *,
        organization_id: UUID,
        spec: SorEntityReadSpec,
        source_ids: Sequence[UUID],
    ) -> SorGridContract:
        resolved = await self._resolve_source_ids(
            organization_id=organization_id,
            profile=spec.profile,
            requested=source_ids,
        )
        return self._grid(
            spec,
            await self._custom_columns(
                organization_id=organization_id,
                spec=spec,
                source_ids=resolved,
            ),
        )

    async def filter_options(
        self,
        *,
        organization_id: UUID,
        spec: SorEntityReadSpec,
        source_ids: Sequence[UUID],
        field: str,
        search: str,
        limit: int,
    ) -> SorFilterOptionsResponse:
        """Read stable values from the collection scope, never its current page."""
        resolved_source_ids = await self._resolve_source_ids(
            organization_id=organization_id,
            profile=spec.profile,
            requested=source_ids,
        )
        custom_columns = await self._custom_columns(
            organization_id=organization_id,
            spec=spec,
            source_ids=resolved_source_ids,
        )
        contract = self._field_contract(spec, custom_columns).get(field)
        if contract is None or not contract.grid_column.filterable:
            raise SorReadQueryError(f"SOR field '{field}' is not filterable.")
        if contract.grid_column.kind not in _FILTER_OPTION_KINDS:
            raise SorReadQueryError(
                f"SOR field '{field}' does not provide selectable values."
            )

        value_expression: ColumnElement[Any] = contract.expression
        if contract.grid_column.kind is SorGridColumnKind.STRING_ARRAY:
            value_expression = func.unnest(value_expression)

        predicates: list[ColumnElement[bool]] = [
            SorRecordModel.organization_id == organization_id,
            SorRecordModel.profile == spec.profile,
            SorRecordModel.canonical_entity_kind == spec.entity,
            SorRecordModel.tombstoned_at.is_(None),
            SorRecordModel.deleted.is_(False),
            SorSourceModel.deleted.is_(False),
        ]
        if spec.model is not None:
            predicates.append(spec.model.deleted.is_(False))
        if spec.vendor_object_key is not None:
            predicates.append(
                SorRecordModel.vendor_object_key == spec.vendor_object_key
            )
        if source_ids:
            predicates.append(SorRecordModel.source_id.in_(resolved_source_ids))

        raw_values = select(
            SorRecordModel.source_id.label("source_id"),
            value_expression.label("value"),
        )
        if spec.model is not None:
            raw_values = raw_values.join(
                spec.model,
                spec.model.record_id == SorRecordModel.id,
            )
        raw_values = (
            raw_values.join(
                SorSourceModel,
                SorSourceModel.id == SorRecordModel.source_id,
            )
            .where(*predicates)
            .subquery()
        )

        label_expression: ColumnElement[str] = sql_cast(raw_values.c.value, String)
        target_record = aliased(SorRecordModel)
        target_condition: ColumnElement[bool] | None = None
        if contract.reference_entity is not None:
            target_condition = and_(
                target_record.organization_id == organization_id,
                target_record.source_id == raw_values.c.source_id,
                target_record.canonical_entity_kind == contract.reference_entity,
                target_record.vendor_external_id
                == sql_cast(raw_values.c.value, String),
                target_record.tombstoned_at.is_(None),
                target_record.deleted.is_(False),
            )
            label_expression = func.coalesce(
                func.nullif(func.btrim(target_record.human_external_key), ""),
                sql_cast(raw_values.c.value, String),
            )
        elif (
            contract.custom_definition is not None
            and contract.custom_definition.data_type is SorCustomFieldType.REFERENCE
        ):
            target_condition = and_(
                target_record.organization_id == organization_id,
                target_record.id == raw_values.c.value,
                target_record.tombstoned_at.is_(None),
                target_record.deleted.is_(False),
            )
            label_expression = func.coalesce(
                func.nullif(func.btrim(target_record.human_external_key), ""),
                sql_cast(raw_values.c.value, String),
            )

        statement = select(
            raw_values.c.value,
            label_expression.label("label"),
        ).select_from(raw_values)
        if target_condition is not None:
            statement = statement.outerjoin(target_record, target_condition)
        statement = statement.where(raw_values.c.value.is_not(None))
        if search:
            statement = statement.where(
                label_expression.ilike(_contains_pattern(search), escape="\\")
            )
        rows = (
            await self.session.execute(
                statement.distinct()
                .order_by(label_expression.asc())
                .limit((limit * 4) + 1)
            )
        ).all()
        options: list[SorFilterOptionResponse] = []
        seen: set[str] = set()
        for raw_value, raw_label in rows:
            value = _filter_option_string(raw_value)
            if value in seen:
                continue
            seen.add(value)
            options.append(
                SorFilterOptionResponse(
                    value=value,
                    label=str(raw_label).strip() or value,
                )
            )
            if len(options) == limit:
                break
        return SorFilterOptionsResponse(field=field, items=tuple(options))

    async def _resolve_source_ids(
        self,
        *,
        organization_id: UUID,
        profile: SorProfile,
        requested: Sequence[UUID],
    ) -> tuple[UUID, ...]:
        statement = select(SorSourceModel.id).where(
            SorSourceModel.organization_id == organization_id,
            SorSourceModel.profile == profile,
            SorSourceModel.deleted.is_(False),
        )
        if requested:
            statement = statement.where(SorSourceModel.id.in_(requested))
        resolved = tuple((await self.session.scalars(statement)).all())
        if requested and set(resolved) != set(requested):
            raise SorReadNotFoundError("SOR source not found.")
        return resolved

    async def _custom_columns(
        self,
        *,
        organization_id: UUID,
        spec: SorEntityReadSpec,
        source_ids: Sequence[UUID],
    ) -> tuple[_CustomColumn, ...]:
        if not source_ids:
            return ()
        predicates: list[ColumnElement[bool]] = [
            SorCustomFieldDefinitionModel.organization_id == organization_id,
            SorCustomFieldDefinitionModel.source_id.in_(source_ids),
            SorSourceStreamModel.canonical_entity_kind == spec.entity,
            SorSourceStreamModel.deleted.is_(False),
            SorCustomFieldDefinitionModel.removed_at.is_(None),
            SorCustomFieldDefinitionModel.deleted.is_(False),
            SorFieldMappingModel.state == SorFieldMappingState.ACTIVE,
            SorFieldMappingModel.deleted.is_(False),
        ]
        if spec.vendor_object_key is not None:
            predicates.append(
                SorCustomFieldDefinitionModel.vendor_object_key
                == spec.vendor_object_key
            )
        raw_rows = (
            await self.session.execute(
                select(
                    SorCustomFieldDefinitionModel,
                    SorFieldMappingModel,
                    SorSourceModel,
                )
                .join(
                    SorSourceModel,
                    and_(
                        SorSourceModel.id == SorCustomFieldDefinitionModel.source_id,
                        SorSourceModel.organization_id
                        == SorCustomFieldDefinitionModel.organization_id,
                    ),
                )
                .join(
                    SorFieldMappingModel,
                    and_(
                        SorFieldMappingModel.custom_field_definition_id
                        == SorCustomFieldDefinitionModel.id,
                        SorFieldMappingModel.source_id
                        == SorCustomFieldDefinitionModel.source_id,
                        SorFieldMappingModel.organization_id
                        == SorCustomFieldDefinitionModel.organization_id,
                        SorFieldMappingModel.mapping_revision_id
                        == SorSourceModel.active_mapping_revision_id,
                    ),
                )
                .join(
                    SorSourceStreamModel,
                    and_(
                        SorSourceStreamModel.source_id
                        == SorCustomFieldDefinitionModel.source_id,
                        SorSourceStreamModel.organization_id
                        == SorCustomFieldDefinitionModel.organization_id,
                        SorSourceStreamModel.vendor_object_key
                        == SorCustomFieldDefinitionModel.vendor_object_key,
                    ),
                )
                .where(*predicates)
                .order_by(
                    SorCustomFieldDefinitionModel.label.asc(),
                    SorCustomFieldDefinitionModel.id.asc(),
                )
            )
        ).all()
        rows = tuple(
            (definition, field_mapping, source)
            for definition, field_mapping, source in raw_rows
        )
        labels = _custom_column_labels(rows)
        show_source_defaults = len(source_ids) == 1
        columns: list[_CustomColumn] = []
        for definition, field_mapping, _source in rows:
            kind = _custom_grid_kind(definition.data_type)
            key = _custom_field_key(definition.id)
            columns.append(
                _CustomColumn(
                    key=key,
                    definition=definition,
                    field_mapping=field_mapping,
                    expression=_custom_scalar_expression(definition),
                    grid_column=SorGridColumn(
                        key=key,
                        label=labels[definition.id],
                        kind=kind,
                        importance=SorGridColumnImportance.SECONDARY,
                        default_visible=(
                            field_mapping.ui_default_column and show_source_defaults
                        ),
                        filterable=kind is not SorGridColumnKind.LONG_TEXT,
                        sortable=kind
                        not in {
                            SorGridColumnKind.LONG_TEXT,
                            SorGridColumnKind.STRING_ARRAY,
                        },
                        groupable=kind
                        in {
                            SorGridColumnKind.ENUM,
                            SorGridColumnKind.BOOLEAN,
                            SorGridColumnKind.REFERENCE,
                        },
                        wraps=kind
                        in {
                            SorGridColumnKind.LONG_TEXT,
                            SorGridColumnKind.STRING_ARRAY,
                        },
                        custom=True,
                    ),
                )
            )
        return tuple(columns)

    async def _custom_values(
        self,
        *,
        organization_id: UUID,
        record_ids: Sequence[UUID],
        field_definition_ids: set[UUID] | None = None,
    ) -> dict[UUID, tuple[SorCustomFieldValueResponse, ...]]:
        if not record_ids or (
            field_definition_ids is not None and not field_definition_ids
        ):
            return {}
        predicates: list[ColumnElement[bool]] = [
            SorCustomFieldValueModel.organization_id == organization_id,
            SorCustomFieldValueModel.record_id.in_(record_ids),
            SorCustomFieldValueModel.deleted.is_(False),
            SorCustomFieldDefinitionModel.deleted.is_(False),
            SorFieldMappingModel.deleted.is_(False),
        ]
        if field_definition_ids is not None:
            predicates.append(
                SorCustomFieldValueModel.field_definition_id.in_(field_definition_ids)
            )
        rows = (
            await self.session.execute(
                select(
                    SorCustomFieldValueModel,
                    SorCustomFieldDefinitionModel,
                    SorFieldMappingModel,
                )
                .join(
                    SorCustomFieldDefinitionModel,
                    and_(
                        SorCustomFieldDefinitionModel.id
                        == SorCustomFieldValueModel.field_definition_id,
                        SorCustomFieldDefinitionModel.source_id
                        == SorCustomFieldValueModel.source_id,
                        SorCustomFieldDefinitionModel.organization_id
                        == SorCustomFieldValueModel.organization_id,
                    ),
                )
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == SorCustomFieldValueModel.record_id,
                        SorRecordModel.source_id == SorCustomFieldValueModel.source_id,
                        SorRecordModel.organization_id
                        == SorCustomFieldValueModel.organization_id,
                    ),
                )
                .join(
                    SorFieldMappingModel,
                    and_(
                        SorFieldMappingModel.mapping_revision_id
                        == SorRecordModel.mapping_revision_id,
                        SorFieldMappingModel.custom_field_definition_id
                        == SorCustomFieldDefinitionModel.id,
                        SorFieldMappingModel.source_id
                        == SorCustomFieldDefinitionModel.source_id,
                        SorFieldMappingModel.organization_id
                        == SorCustomFieldDefinitionModel.organization_id,
                    ),
                )
                .options(
                    load_only(
                        SorCustomFieldValueModel.record_id,
                        SorCustomFieldValueModel.value_type,
                        SorCustomFieldValueModel.text_value,
                        SorCustomFieldValueModel.decimal_value,
                        SorCustomFieldValueModel.boolean_value,
                        SorCustomFieldValueModel.date_value,
                        SorCustomFieldValueModel.timestamp_value,
                        SorCustomFieldValueModel.string_array_value,
                        SorCustomFieldValueModel.reference_record_id,
                        SorCustomFieldValueModel.json_value,
                    ),
                    load_only(
                        SorCustomFieldDefinitionModel.id,
                        SorCustomFieldDefinitionModel.label,
                        SorCustomFieldDefinitionModel.data_type,
                        SorCustomFieldDefinitionModel.sensitivity,
                        SorCustomFieldDefinitionModel.writable,
                    ),
                    load_only(
                        SorFieldMappingModel.agent_visible,
                        SorFieldMappingModel.direction,
                    ),
                )
                .where(*predicates)
                .order_by(
                    SorCustomFieldValueModel.record_id.asc(),
                    SorCustomFieldDefinitionModel.label.asc(),
                )
            )
        ).all()
        grouped: dict[UUID, list[SorCustomFieldValueResponse]] = {}
        for value, definition, field_mapping in rows:
            grouped.setdefault(value.record_id, []).append(
                SorCustomFieldValueResponse(
                    key=_custom_field_key(definition.id),
                    label=definition.label,
                    data_type=definition.data_type,
                    value=_typed_custom_value(value),
                    sensitivity=definition.sensitivity,
                    agent_visible=field_mapping.agent_visible,
                    writable=(
                        definition.writable
                        and field_mapping.direction
                        is SorFieldMappingDirection.READ_WRITE
                    ),
                )
            )
        return {record_id: tuple(values) for record_id, values in grouped.items()}

    async def _relations(
        self,
        *,
        organization_id: UUID,
        record: SorRecordModel,
    ) -> tuple[SorRecordRelationResponse, ...]:
        grouped = await read_record_relations(
            self.session,
            organization_id=organization_id,
            record_ids=(record.id,),
        )
        return grouped.get(record.id, ())

    async def _display_values(
        self,
        *,
        organization_id: UUID,
        spec: SorEntityReadSpec,
        rows: Sequence[_ReadRow],
        selected_columns: frozenset[str] | None = None,
    ) -> dict[UUID, dict[str, object]]:
        """Resolve page references in one query while preserving raw identities."""
        fields = tuple(
            field
            for field in spec.fields
            if field.reference_entity is not None
            and (selected_columns is None or field.key in selected_columns)
        )
        if not rows or not fields:
            return {}

        raw_by_record: dict[UUID, dict[str, object]] = {}
        reference_keys: set[tuple[UUID, str, str]] = set()
        for row in rows:
            values: dict[str, object] = {}
            for field in fields:
                raw = field.read_value(row.record, row.extension, row.source)
                values[field.key] = raw
                for external_id in reference_external_ids(raw):
                    reference_keys.add(
                        (
                            row.record.source_id,
                            field.reference_entity or "",
                            external_id,
                        )
                    )
            raw_by_record[row.record.id] = values

        labels = await resolve_reference_labels(
            self.session,
            organization_id=organization_id,
            reference_keys=tuple(reference_keys),
        )
        result: dict[UUID, dict[str, object]] = {}
        for row in rows:
            projected: dict[str, object] = {}
            for field in fields:
                raw = raw_by_record[row.record.id][field.key]
                display = reference_display_value(
                    raw,
                    source_id=row.record.source_id,
                    entity=field.reference_entity or "",
                    labels=labels,
                )
                if display is not None:
                    projected[field.key] = display
            if projected:
                result[row.record.id] = projected
        return result

    def _field_contract(
        self,
        spec: SorEntityReadSpec,
        custom_columns: Sequence[_CustomColumn],
    ) -> dict[str, _FieldContract]:
        contract: dict[str, _FieldContract] = {
            field.key: _FieldContract(
                expression=field.sql_expression,
                grid_column=field.grid_column(),
                reference_entity=field.reference_entity,
            )
            for field in spec.fields
        }
        contract.update(
            {
                "source": _FieldContract(
                    expression=SorSourceModel.name.__clause_element__(),
                    grid_column=SorGridColumn(
                        key="source",
                        label="Source",
                        kind=SorGridColumnKind.REFERENCE,
                        importance=SorGridColumnImportance.METADATA,
                        groupable=True,
                    ),
                ),
                "source_updated_at": _FieldContract(
                    expression=SorRecordModel.source_updated_at.__clause_element__(),
                    grid_column=SorGridColumn(
                        key="source_updated_at",
                        label="Updated in source",
                        kind=SorGridColumnKind.DATETIME,
                        importance=SorGridColumnImportance.METADATA,
                        default_visible=True,
                        groupable=False,
                    ),
                ),
                "projected_at": _FieldContract(
                    expression=SorRecordModel.projected_at.__clause_element__(),
                    grid_column=SorGridColumn(
                        key="projected_at",
                        label="Synced",
                        kind=SorGridColumnKind.DATETIME,
                        importance=SorGridColumnImportance.METADATA,
                        default_visible=False,
                        groupable=False,
                    ),
                ),
            }
        )
        contract.update(
            {
                custom.key: _FieldContract(
                    expression=custom.expression,
                    grid_column=custom.grid_column,
                    custom_definition=custom.definition,
                )
                for custom in custom_columns
            }
        )
        return contract

    def _grid(
        self,
        spec: SorEntityReadSpec,
        custom_columns: Sequence[_CustomColumn],
    ) -> SorGridContract:
        common = self._field_contract(spec, custom_columns)
        ordered = [field.grid_column() for field in spec.fields]
        ordered.extend(custom.grid_column for custom in custom_columns)
        ordered.extend(
            common[key].grid_column
            for key in ("source", "source_updated_at", "projected_at")
        )
        return SorGridContract(
            profile=spec.profile,
            entity=spec.entity,
            columns=tuple(ordered),
        )

    def _validate_query(
        self,
        query: SorCollectionQuery,
        *,
        field_contract: Mapping[str, _FieldContract],
        grid: SorGridContract,
    ) -> None:
        known_columns = {column.key for column in grid.columns}
        unknown_columns = set(query.columns) - known_columns
        if unknown_columns:
            raise SorReadQueryError(
                "Unknown SOR columns: " + ", ".join(sorted(unknown_columns)) + "."
            )
        for term in query.sort:
            field = field_contract.get(term.field)
            if field is None or not field.grid_column.sortable:
                raise SorReadQueryError(f"SOR field '{term.field}' is not sortable.")
        for term in query.group:
            field = field_contract.get(term.field)
            if field is None or not field.grid_column.groupable:
                raise SorReadQueryError(f"SOR field '{term.field}' is not groupable.")

    def _row_response(
        self,
        *,
        spec: SorEntityReadSpec,
        record: SorRecordModel,
        extension: SorProfileRecordModel | None,
        source: SorSourceModel,
        custom_values: Sequence[SorCustomFieldValueResponse],
        display_values: Mapping[str, object] | None = None,
        selected_columns: frozenset[str] | None = None,
    ) -> SorCollectionRowResponse:
        values = {
            field.key: _json_value(field.read_value(record, extension, source))
            for field in spec.fields
            if selected_columns is None or field.key in selected_columns
        }
        common_values = {
            "source": source.name,
            "source_updated_at": _json_value(record.source_updated_at),
            "projected_at": _json_value(record.projected_at),
        }
        values.update(
            {
                key: value
                for key, value in common_values.items()
                if selected_columns is None or key in selected_columns
            }
        )
        values.update({field.key: field.value for field in custom_values})
        as_of = source.last_successful_sync_at or record.projected_at
        age_seconds = max(
            0.0,
            (datetime.now(timezone.utc) - as_of).total_seconds(),
        )
        return SorCollectionRowResponse(
            id=record.id,
            source_id=source.id,
            source_name=source.name,
            vendor_key=source.vendor_key,
            profile=spec.profile,
            entity=spec.entity,
            human_external_key=record.human_external_key,
            values=values,
            display_values={
                key: _json_value(value) for key, value in (display_values or {}).items()
            },
            custom_fields=tuple(custom_values),
            source_url=record.source_url,
            source_created_at=record.source_created_at,
            source_updated_at=record.source_updated_at,
            projected_at=record.projected_at,
            freshness=SorFreshnessResponse(
                as_of=as_of,
                target_seconds=source.freshness_target_seconds,
                stale=age_seconds > source.freshness_target_seconds,
            ),
        )


def _compile_filter_group(
    group: SorFilterGroup,
    *,
    field_contract: Mapping[str, _FieldContract],
) -> ColumnElement[bool] | None:
    expressions: list[ColumnElement[bool]] = []
    for child in group.children:
        if isinstance(child, SorFilterGroup):
            nested = _compile_filter_group(child, field_contract=field_contract)
            if nested is not None:
                expressions.append(nested)
        else:
            expressions.append(_compile_condition(child, field_contract=field_contract))
    if not expressions:
        return None
    if group.op.value == "and":
        return and_(*expressions)
    return or_(*expressions)


def _compile_condition(
    condition: SorFilterCondition,
    *,
    field_contract: Mapping[str, _FieldContract],
) -> ColumnElement[bool]:
    contract = field_contract.get(condition.field)
    if contract is None or not contract.grid_column.filterable:
        raise SorReadQueryError(f"SOR field '{condition.field}' is not filterable.")
    expression = contract.expression
    column = contract.grid_column
    allowed = _allowed_operators(column.kind)
    if condition.operator not in allowed:
        raise SorReadQueryError(
            f"SOR operator '{condition.operator.value}' is invalid for "
            f"'{condition.field}'."
        )
    values = tuple(
        _coerce_filter_value(value, kind=column.kind) for value in condition.values
    )
    operator = condition.operator
    if contract.custom_definition is not None:
        return _compile_custom_condition(
            definition=contract.custom_definition,
            operator=operator,
            values=values,
        )
    if operator is SorFilterOperator.IS:
        return (
            expression.is_(values[0]) if values[0] is None else expression == values[0]
        )
    if operator is SorFilterOperator.IS_NOT:
        return and_(
            *(
                expression.is_not(None)
                if value is None
                else expression.is_distinct_from(value)
                for value in values
            )
        )
    if operator is SorFilterOperator.IS_ANY_OF:
        non_null = tuple(value for value in values if value is not None)
        alternatives: list[ColumnElement[bool]] = []
        if non_null:
            alternatives.append(expression.in_(non_null))
        if None in values:
            alternatives.append(expression.is_(None))
        return or_(*alternatives)
    if operator is SorFilterOperator.INCLUDES_ANY:
        _reject_null_filter_values(values, operator=operator)
        return expression.op("&&")(list(values))
    if operator is SorFilterOperator.INCLUDES_ALL:
        _reject_null_filter_values(values, operator=operator)
        return expression.op("@>")(list(values))
    if operator is SorFilterOperator.INCLUDES_NONE:
        _reject_null_filter_values(values, operator=operator)
        return or_(expression.is_(None), not_(expression.op("&&")(list(values))))
    if operator is SorFilterOperator.BEFORE:
        _reject_null_filter_values(values, operator=operator)
        return expression < values[0]
    if operator is SorFilterOperator.AFTER:
        _reject_null_filter_values(values, operator=operator)
        return expression > values[0]
    raise SorReadQueryError("Unsupported SOR filter operator.")


def _compile_custom_condition(
    *,
    definition: SorCustomFieldDefinitionModel,
    operator: SorFilterOperator,
    values: Sequence[object],
) -> ColumnElement[bool]:
    """Filter custom fields set-wise while preserving missing-value semantics."""
    value_column = _custom_value_column(definition)
    presence = _custom_value_record_ids(definition)
    if operator is SorFilterOperator.IS:
        if values[0] is None:
            return SorRecordModel.id.not_in(presence)
        return SorRecordModel.id.in_(
            _custom_value_record_ids(definition, value_column == values[0])
        )
    if operator is SorFilterOperator.IS_NOT:
        conditions: list[ColumnElement[bool]] = []
        non_null = tuple(value for value in values if value is not None)
        if non_null:
            conditions.append(
                SorRecordModel.id.not_in(
                    _custom_value_record_ids(
                        definition,
                        value_column.in_(non_null),
                    )
                )
            )
        if None in values:
            conditions.append(SorRecordModel.id.in_(presence))
        return and_(*conditions)
    if operator is SorFilterOperator.IS_ANY_OF:
        non_null = tuple(value for value in values if value is not None)
        alternatives: list[ColumnElement[bool]] = []
        if non_null:
            alternatives.append(
                SorRecordModel.id.in_(
                    _custom_value_record_ids(definition, value_column.in_(non_null))
                )
            )
        if None in values:
            alternatives.append(SorRecordModel.id.not_in(presence))
        return or_(*alternatives)
    if operator is SorFilterOperator.INCLUDES_ANY:
        _reject_null_filter_values(values, operator=operator)
        return SorRecordModel.id.in_(
            _custom_value_record_ids(definition, value_column.op("&&")(list(values)))
        )
    if operator is SorFilterOperator.INCLUDES_ALL:
        _reject_null_filter_values(values, operator=operator)
        return SorRecordModel.id.in_(
            _custom_value_record_ids(definition, value_column.op("@>")(list(values)))
        )
    if operator is SorFilterOperator.INCLUDES_NONE:
        _reject_null_filter_values(values, operator=operator)
        return SorRecordModel.id.not_in(
            _custom_value_record_ids(definition, value_column.op("&&")(list(values)))
        )
    if operator is SorFilterOperator.BEFORE:
        _reject_null_filter_values(values, operator=operator)
        return SorRecordModel.id.in_(
            _custom_value_record_ids(definition, value_column < values[0])
        )
    if operator is SorFilterOperator.AFTER:
        _reject_null_filter_values(values, operator=operator)
        return SorRecordModel.id.in_(
            _custom_value_record_ids(definition, value_column > values[0])
        )
    raise SorReadQueryError("Unsupported SOR custom-field filter operator.")


def _custom_value_record_ids(
    definition: SorCustomFieldDefinitionModel,
    predicate: ColumnElement[bool] | None = None,
) -> Select[tuple[UUID]]:
    conditions: list[ColumnElement[bool]] = [
        SorCustomFieldValueModel.field_definition_id == definition.id,
        SorCustomFieldValueModel.organization_id == definition.organization_id,
        SorCustomFieldValueModel.source_id == definition.source_id,
        SorCustomFieldValueModel.deleted.is_(False),
    ]
    if predicate is not None:
        conditions.append(predicate)
    return select(SorCustomFieldValueModel.record_id).where(*conditions)


def _compile_order_terms(
    query: SorCollectionQuery,
    *,
    field_contract: Mapping[str, _FieldContract],
) -> tuple[_OrderTerm, ...]:
    ordering: list[_OrderTerm] = []
    seen: set[str] = set()
    terms = [*query.group, *query.sort]
    for term in terms:
        if term.field in seen:
            continue
        seen.add(term.field)
        expression = field_contract[term.field].expression
        nulls = getattr(term, "nulls", SorNullPlacement.LAST)
        ordering.append(
            _OrderTerm(
                expression=expression,
                direction=term.direction,
                nulls=nulls,
            )
        )
    if not ordering:
        ordering.append(
            _OrderTerm(
                expression=SorRecordModel.projected_at.__clause_element__(),
                direction=SorSortDirection.DESC,
                nulls=SorNullPlacement.LAST,
            )
        )
    return tuple(ordering)


def _order_expressions(
    order_terms: Sequence[_OrderTerm],
) -> tuple[ColumnElement[Any], ...]:
    ordering: list[ColumnElement[Any]] = []
    for term in order_terms:
        direction = asc if term.direction is SorSortDirection.ASC else desc
        ordered = direction(term.expression)
        ordering.append(
            ordered.nulls_first()
            if term.nulls is SorNullPlacement.FIRST
            else ordered.nulls_last()
        )
    ordering.append(SorRecordModel.id.desc())
    return tuple(ordering)


def _seek_after(
    cursor: _Cursor,
    *,
    order_terms: Sequence[_OrderTerm],
) -> ColumnElement[bool]:
    if len(cursor.values) != len(order_terms):
        raise SorReadQueryError("SOR cursor does not match this ordering.")
    alternatives: list[ColumnElement[bool]] = []
    prefix: list[ColumnElement[bool]] = []
    for term, value in zip(order_terms, cursor.values, strict=True):
        after = _term_after(term, value)
        if after is not None:
            alternatives.append(and_(*prefix, after))
        prefix.append(term.expression.is_not_distinct_from(value))
    alternatives.append(and_(*prefix, SorRecordModel.id < cursor.record_id))
    return or_(*alternatives)


def _term_after(
    term: _OrderTerm,
    value: object,
) -> ColumnElement[bool] | None:
    if value is None:
        if term.nulls is SorNullPlacement.FIRST:
            return term.expression.is_not(None)
        return None
    comparison = (
        term.expression > value
        if term.direction is SorSortDirection.ASC
        else term.expression < value
    )
    if term.nulls is SorNullPlacement.LAST:
        return or_(comparison, term.expression.is_(None))
    return comparison


def _reject_null_filter_values(
    values: Sequence[object],
    *,
    operator: SorFilterOperator,
) -> None:
    if any(value is None for value in values):
        raise SorReadQueryError(
            f"SOR operator '{operator.value}' does not accept null values."
        )


def _contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filter_option_string(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _allowed_operators(kind: SorGridColumnKind) -> frozenset[SorFilterOperator]:
    equality = {
        SorFilterOperator.IS,
        SorFilterOperator.IS_NOT,
        SorFilterOperator.IS_ANY_OF,
    }
    if kind in {SorGridColumnKind.DATE, SorGridColumnKind.DATETIME}:
        return frozenset(equality | {SorFilterOperator.BEFORE, SorFilterOperator.AFTER})
    if kind is SorGridColumnKind.STRING_ARRAY:
        return frozenset(
            {
                SorFilterOperator.INCLUDES_ANY,
                SorFilterOperator.INCLUDES_ALL,
                SorFilterOperator.INCLUDES_NONE,
            }
        )
    return frozenset(equality)


def _coerce_filter_value(value: object, *, kind: SorGridColumnKind) -> object:
    if value is None:
        return None
    if kind is SorGridColumnKind.BOOLEAN:
        if not isinstance(value, bool):
            raise SorReadQueryError("Boolean SOR filters require boolean values.")
        return value
    if kind is SorGridColumnKind.NUMBER:
        if isinstance(value, bool):
            raise SorReadQueryError("Numeric SOR filters require numeric values.")
        try:
            return Decimal(str(value))
        except InvalidOperation as error:
            raise SorReadQueryError("Numeric SOR filter value is invalid.") from error
    if kind is SorGridColumnKind.DATE:
        if not isinstance(value, str):
            raise SorReadQueryError("Date SOR filters require ISO date strings.")
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise SorReadQueryError("Date SOR filter value is invalid.") from error
    if kind is SorGridColumnKind.DATETIME:
        if not isinstance(value, str):
            raise SorReadQueryError("Datetime SOR filters require ISO timestamps.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise SorReadQueryError("Datetime SOR filter value is invalid.") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SorReadQueryError("Datetime SOR filters require an offset.")
        return parsed
    if kind is SorGridColumnKind.STRING_ARRAY:
        if not isinstance(value, str):
            raise SorReadQueryError("Multi-value SOR filters require strings.")
        return value
    if not isinstance(value, str):
        raise SorReadQueryError("Text SOR filters require string values.")
    return value


def _custom_scalar_expression(
    definition: SorCustomFieldDefinitionModel,
) -> ColumnElement[Any]:
    value_column = _custom_value_column(definition)
    return (
        select(value_column)
        .where(
            SorCustomFieldValueModel.record_id == SorRecordModel.id,
            SorCustomFieldValueModel.field_definition_id == definition.id,
            SorCustomFieldValueModel.organization_id == definition.organization_id,
            SorCustomFieldValueModel.source_id == definition.source_id,
            SorCustomFieldValueModel.deleted.is_(False),
        )
        .correlate(SorRecordModel)
        .scalar_subquery()
    )


def _custom_value_column(
    definition: SorCustomFieldDefinitionModel,
) -> ColumnElement[Any]:
    return cast(
        ColumnElement[Any],
        {
            SorCustomFieldType.TEXT: SorCustomFieldValueModel.text_value,
            SorCustomFieldType.DECIMAL: SorCustomFieldValueModel.decimal_value,
            SorCustomFieldType.BOOLEAN: SorCustomFieldValueModel.boolean_value,
            SorCustomFieldType.DATE: SorCustomFieldValueModel.date_value,
            SorCustomFieldType.TIMESTAMP: SorCustomFieldValueModel.timestamp_value,
            SorCustomFieldType.STRING_ARRAY: (
                SorCustomFieldValueModel.string_array_value
            ),
            SorCustomFieldType.REFERENCE: (
                SorCustomFieldValueModel.reference_record_id
            ),
            SorCustomFieldType.BOUNDED_JSON: SorCustomFieldValueModel.json_value,
        }[definition.data_type],
    )


def _custom_grid_kind(value_type: SorCustomFieldType) -> SorGridColumnKind:
    return {
        SorCustomFieldType.TEXT: SorGridColumnKind.TEXT,
        SorCustomFieldType.DECIMAL: SorGridColumnKind.NUMBER,
        SorCustomFieldType.BOOLEAN: SorGridColumnKind.BOOLEAN,
        SorCustomFieldType.DATE: SorGridColumnKind.DATE,
        SorCustomFieldType.TIMESTAMP: SorGridColumnKind.DATETIME,
        SorCustomFieldType.STRING_ARRAY: SorGridColumnKind.STRING_ARRAY,
        SorCustomFieldType.REFERENCE: SorGridColumnKind.REFERENCE,
        SorCustomFieldType.BOUNDED_JSON: SorGridColumnKind.LONG_TEXT,
    }[value_type]


def _typed_custom_value(value: SorCustomFieldValueModel) -> object:
    result = {
        SorCustomFieldType.TEXT: value.text_value,
        SorCustomFieldType.DECIMAL: value.decimal_value,
        SorCustomFieldType.BOOLEAN: value.boolean_value,
        SorCustomFieldType.DATE: value.date_value,
        SorCustomFieldType.TIMESTAMP: value.timestamp_value,
        SorCustomFieldType.STRING_ARRAY: value.string_array_value,
        SorCustomFieldType.REFERENCE: value.reference_record_id,
        SorCustomFieldType.BOUNDED_JSON: value.json_value,
    }[value.value_type]
    if result is None:
        raise SorReadInvariantError("Custom field value is incomplete.")
    return _json_value(result)


def _json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise SorReadInvariantError("Projected SOR value is not JSON-compatible.")


def _query_fingerprint(query: SorCollectionQuery) -> str:
    payload = query.model_dump(mode="json", exclude={"cursor"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _encode_cursor(
    *,
    values: Sequence[object],
    record_id: UUID,
    fingerprint: str,
) -> str:
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "values": [_cursor_value(value) for value in values],
            "record_id": str(record_id),
            "query": fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str | None, *, fingerprint: str) -> _Cursor | None:
    if cursor is None:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except (binascii.Error, ValueError, TypeError, json.JSONDecodeError) as error:
        raise SorReadQueryError("SOR cursor is invalid.") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"v", "values", "record_id", "query"}
        or payload["v"] != _CURSOR_VERSION
        or not isinstance(payload["values"], list)
        or payload["query"] != fingerprint
    ):
        raise SorReadQueryError("SOR cursor does not match this query.")
    try:
        return _Cursor(
            values=tuple(_restore_cursor_value(value) for value in payload["values"]),
            record_id=UUID(payload["record_id"]),
        )
    except (InvalidOperation, KeyError, TypeError, ValueError) as error:
        raise SorReadQueryError("SOR cursor is invalid.") from error


def _cursor_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, UUID):
        return {"type": "uuid", "value": str(value)}
    raise SorReadInvariantError("SOR ordering produced an unsupported cursor value.")


def _restore_cursor_value(value: object) -> _CursorScalar:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if not isinstance(value, dict) or set(value) != {"type", "value"}:
        raise ValueError("Cursor value tag is invalid.")
    tag = value["type"]
    raw = value["value"]
    if not isinstance(tag, str) or not isinstance(raw, str):
        raise ValueError("Cursor value tag is invalid.")
    if tag == "decimal":
        return Decimal(raw)
    if tag == "datetime":
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Cursor datetime lacks an offset.")
        return parsed
    if tag == "date":
        return date.fromisoformat(raw)
    if tag == "uuid":
        return UUID(raw)
    raise ValueError("Cursor value tag is unsupported.")


__all__ = [
    "SorCollectionReadService",
    "SorEntityReadSpec",
    "SorReadError",
    "SorReadFieldSpec",
    "SorReadInvariantError",
    "SorReadNotFoundError",
    "SorReadQueryError",
    "SorSourceReadService",
    "reference_display_value",
    "reference_external_ids",
    "read_record_relations",
    "resolve_reference_labels",
]
