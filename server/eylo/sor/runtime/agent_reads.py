"""Agent-safe SOR reads shared by system tools and the operator Agent view."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.knowledge.agent_reads import (
    knowledge_related_entities,
    read_knowledge_related_records,
)
from eylo.sor.runtime.authority import (
    AuthorizedSorSource,
    SorAuthorityError,
    SorAuthorityFailure,
    resolve_agent_sources,
    resolve_profile_tool,
)
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.read_registry import get_sor_read_spec
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.contracts import (
    SorFieldMappingDirection,
    SorFieldMappingState,
    SorProfile,
    SorSourceAccess,
    SorToolEffect,
)
from eylo.sor.shared.models import (
    SorFieldMappingModel,
    SorRecordModel,
    SorSourceModel,
    SorSourceStreamModel,
)
from eylo.sor.shared.query import SorAgentSortField, SorSortDirection
from eylo.sor.shared.reads import (
    read_record_relations,
    reference_display_value,
    reference_external_ids,
    resolve_reference_labels,
)
from eylo.sor.shared.schemas import (
    SorAgentRecordResponse,
    SorAgentRelatedAvailability,
    SorAgentRelatedCollectionResponse,
    SorAgentViewResponse,
    SorAgentVisibleFieldResponse,
    SorFreshnessResponse,
    SorRecordRelationResponse,
)
from eylo.sor.support.agent_reads import read_support_related_records

_CURSOR_VERSION = 2
_MAX_SEARCH_CHARS = 1_000
_MAX_CURSOR_CHARS = 2_048


class SorAgentReadError(Exception):
    """Agent-view input or persisted projection cannot be read safely."""


async def read_agent_view(
    session: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    agent_revision: int,
    profile: SorProfile,
    entity: str,
    search: str = "",
    source_ids: Sequence[UUID] = (),
    record_id: UUID | None = None,
    external_key: str | None = None,
    required_tool: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    sort_by: SorAgentSortField = SorAgentSortField.PROJECTED_AT,
    sort_direction: SorSortDirection = SorSortDirection.DESC,
    include_relations: bool = False,
    registry: SorRegistry | None = None,
) -> SorAgentViewResponse:
    """Read only fields exposed by mappings and sources authorized at runtime."""
    if not 1 <= limit <= 100:
        raise SorAgentReadError("Agent view limit must be between 1 and 100.")
    normalized_search = search.strip()
    if len(normalized_search) > _MAX_SEARCH_CHARS:
        raise SorAgentReadError("Agent view search is too long.")
    normalized_external_key = external_key.strip() if external_key is not None else None
    if normalized_external_key is not None and not normalized_external_key:
        raise SorAgentReadError("Agent view external key cannot be empty.")
    if normalized_external_key is not None and len(normalized_external_key) > 320:
        raise SorAgentReadError("Agent view external key is too long.")
    if record_id is not None and normalized_external_key is not None:
        raise SorAgentReadError("Select a record by ID or external key, not both.")
    requested_sources = tuple(dict.fromkeys(source_ids))
    resolved_registry = registry or get_sor_registry()
    tools, sources = await _resolve_view_sources(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        agent_revision=agent_revision,
        profile=profile,
        entity=entity,
        source_ids=requested_sources,
        required_tool=required_tool,
        registry=resolved_registry,
    )
    source_map = {source.source_id: source for source in sources}
    fields = await _visible_fields(
        session,
        organization_id=organization_id,
        sources=sources,
        entity=entity,
    )
    fingerprint = _fingerprint(
        agent_id=agent_id,
        agent_revision=agent_revision,
        profile=profile,
        entity=entity,
        search=normalized_search,
        source_ids=tuple(source_map),
        record_id=record_id,
        external_key=normalized_external_key,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
    boundary = _decode_cursor(cursor, fingerprint=fingerprint)
    if not source_map:
        return SorAgentViewResponse(
            agent_id=agent_id,
            agent_revision=agent_revision,
            profile=profile,
            entity=entity,
            authorized_tools=tools,
            fields=fields,
            items=(),
            next_cursor=None,
            has_more=False,
        )

    predicates = [
        SorRecordModel.organization_id == organization_id,
        SorRecordModel.source_id.in_(source_map),
        SorRecordModel.profile == profile,
        SorRecordModel.canonical_entity_kind == entity,
        SorRecordModel.tombstoned_at.is_(None),
        SorRecordModel.deleted.is_(False),
    ]
    if normalized_search:
        predicates.append(
            SorRecordModel.agent_search_vector.op("@@")(
                func.websearch_to_tsquery("simple", normalized_search)
            )
        )
    if record_id is not None:
        predicates.append(SorRecordModel.id == record_id)
    if normalized_external_key is not None:
        predicates.append(SorRecordModel.human_external_key == normalized_external_key)
    sort_column = (
        SorRecordModel.source_updated_at
        if sort_by is SorAgentSortField.SOURCE_UPDATED_AT
        else SorRecordModel.projected_at
    )
    if boundary is not None:
        sort_value, boundary_record_id = boundary
        predicates.append(
            _cursor_predicate(
                sort_column=sort_column,
                sort_value=sort_value,
                record_id=boundary_record_id,
                direction=sort_direction,
            )
        )
    order = asc if sort_direction is SorSortDirection.ASC else desc
    rows = list(
        (
            await session.scalars(
                select(SorRecordModel)
                .where(*predicates)
                .order_by(
                    order(sort_column).nullslast(),
                    order(SorRecordModel.id),
                )
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    relations_by_record = (
        await read_record_relations(
            session,
            organization_id=organization_id,
            record_ids=tuple(row.id for row in page),
        )
        if include_relations
        else {}
    )
    display_values_by_record = await _reference_display_values(
        session,
        organization_id=organization_id,
        profile=profile,
        entity=entity,
        records=page,
    )
    items = tuple(
        _record_response(
            row,
            source_map[row.source_id],
            display_values=display_values_by_record.get(row.id, {}),
            relations=relations_by_record.get(row.id, ()),
        )
        for row in page
    )
    related = await _related_collections(
        session,
        organization_id=organization_id,
        profile=profile,
        primary_entity=entity,
        required_tool=required_tool,
        primary_records=tuple(page),
        sources=sources,
        registry=resolved_registry,
    )
    next_cursor = (
        _encode_cursor(
            sort_value=getattr(page[-1], sort_by.value),
            record_id=page[-1].id,
            fingerprint=fingerprint,
        )
        if has_more and page
        else None
    )
    return SorAgentViewResponse(
        agent_id=agent_id,
        agent_revision=agent_revision,
        profile=profile,
        entity=entity,
        authorized_tools=tools,
        fields=fields,
        items=items,
        related=related,
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def _related_collections(
    session: AsyncSession,
    *,
    organization_id: UUID,
    profile: SorProfile,
    primary_entity: str,
    required_tool: str | None,
    primary_records: tuple[SorRecordModel, ...],
    sources: tuple[AuthorizedSorSource, ...],
    registry: SorRegistry,
) -> tuple[SorAgentRelatedCollectionResponse, ...]:
    """Compose only profile-owned related reads promised by the selected tool."""
    if required_tool is None or not primary_records:
        return ()
    tool = resolve_profile_tool(
        registry=registry,
        profile=profile,
        tool_name=required_tool,
        effect=SorToolEffect.READ,
        entity=primary_entity,
    )
    if profile is SorProfile.KNOWLEDGE:
        related_entities = knowledge_related_entities(required_tool)
    elif profile is SorProfile.SUPPORT:
        related_entities = tuple(sorted(tool.entities - tool.target_entities))
    else:
        related_entities = ()
    if not related_entities:
        return ()

    responses: list[SorAgentRelatedCollectionResponse] = []
    for related_entity in related_entities:
        responses.extend(
            await _related_collection(
                session,
                organization_id=organization_id,
                profile=profile,
                tool_name=required_tool,
                related_entity=related_entity,
                primary_records=primary_records,
                sources=sources,
            )
        )
    return tuple(responses)


async def _related_collection(
    session: AsyncSession,
    *,
    organization_id: UUID,
    profile: SorProfile,
    tool_name: str,
    related_entity: str,
    primary_records: tuple[SorRecordModel, ...],
    sources: tuple[AuthorizedSorSource, ...],
) -> tuple[SorAgentRelatedCollectionResponse, ...]:
    """Build one bounded related collection with per-source availability."""
    source_map = {source.source_id: source for source in sources}
    selected_source_ids = set(
        (
            await session.scalars(
                select(SorSourceStreamModel.source_id).where(
                    SorSourceStreamModel.organization_id == organization_id,
                    SorSourceStreamModel.source_id.in_(source_map),
                    SorSourceStreamModel.canonical_entity_kind == related_entity,
                    SorSourceStreamModel.deleted.is_(False),
                )
            )
        ).all()
    )
    related_fields = await _visible_fields(
        session,
        organization_id=organization_id,
        sources=sources,
        entity=related_entity,
    )
    fields_by_source: dict[UUID, list[SorAgentVisibleFieldResponse]] = {}
    for field in related_fields:
        fields_by_source.setdefault(field.source_id, []).append(field)
    readable_parents = tuple(
        record
        for record in primary_records
        if record.source_id in selected_source_ids
        and record.source_id in fields_by_source
    )
    if profile is SorProfile.SUPPORT:
        related_rows = await read_support_related_records(
            session,
            organization_id=organization_id,
            tool_name=tool_name,
            parents=readable_parents,
        )
    elif profile is SorProfile.KNOWLEDGE:
        related_rows = await read_knowledge_related_records(
            session,
            organization_id=organization_id,
            entity=related_entity,
            parents=readable_parents,
        )
    else:
        return ()
    rows_by_parent = {row.parent_record_id: row for row in related_rows}
    related_records = tuple(
        record for related in related_rows for record in related.records
    )
    display_values_by_record = await _reference_display_values(
        session,
        organization_id=organization_id,
        profile=profile,
        entity=related_entity,
        records=related_records,
    )
    responses: list[SorAgentRelatedCollectionResponse] = []
    for parent in primary_records:
        if parent.source_id not in selected_source_ids:
            availability = SorAgentRelatedAvailability.NOT_SELECTED
        elif parent.source_id not in fields_by_source:
            availability = SorAgentRelatedAvailability.NOT_MAPPED
        else:
            availability = SorAgentRelatedAvailability.AVAILABLE
        related = rows_by_parent.get(parent.id)
        related_records = related.records if related is not None else ()
        responses.append(
            SorAgentRelatedCollectionResponse(
                parent_record_id=parent.id,
                entity=related_entity,
                availability=availability,
                fields=tuple(fields_by_source.get(parent.source_id, ())),
                items=tuple(
                    _record_response(
                        record,
                        source_map[record.source_id],
                        display_values=display_values_by_record.get(record.id, {}),
                    )
                    for record in related_records
                ),
                truncated=related.truncated if related is not None else False,
            )
        )
    return tuple(responses)


async def _resolve_view_sources(
    session: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    agent_revision: int,
    profile: SorProfile,
    entity: str,
    source_ids: Sequence[UUID],
    required_tool: str | None,
    registry: SorRegistry,
) -> tuple[tuple[str, ...], tuple[AuthorizedSorSource, ...]]:
    if required_tool is not None:
        tool = resolve_profile_tool(
            registry=registry,
            profile=profile,
            tool_name=required_tool,
            effect=SorToolEffect.READ,
            entity=entity,
        )
        sources = await resolve_agent_sources(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            agent_revision=agent_revision,
            profile=profile,
            tool_name=tool.name,
            requested_source_ids=source_ids,
            effect=SorToolEffect.READ,
            entity=entity,
            registry=registry,
        )
        return (tool.name,), sources

    read_tools = tuple(
        tool
        for tool in registry.get_profile(profile).tools
        if tool.effect is SorToolEffect.READ and entity in tool.target_entities
    )
    if not read_tools:
        raise SorAgentReadError("This SOR entity has no executable read contract.")
    authorized_tools: list[str] = []
    authorized_sources: dict[UUID, AuthorizedSorSource] = {}
    requested_rejected = False
    for tool in read_tools:
        try:
            sources = await resolve_agent_sources(
                session,
                organization_id=organization_id,
                agent_id=agent_id,
                agent_revision=agent_revision,
                profile=profile,
                tool_name=tool.name,
                requested_source_ids=source_ids,
                effect=SorToolEffect.READ,
                entity=entity,
                registry=registry,
            )
        except SorAuthorityError as error:
            if error.code == SorAuthorityFailure.AGENT_REVISION_TOOL_UNAVAILABLE:
                continue
            if error.code == SorAuthorityFailure.SOR_SOURCE_UNAVAILABLE:
                requested_rejected = True
                continue
            raise
        authorized_tools.append(tool.name)
        authorized_sources.update((source.source_id, source) for source in sources)
    if not authorized_tools:
        if requested_rejected:
            raise SorAuthorityError(
                SorAuthorityFailure.SOR_SOURCE_UNAVAILABLE,
                "One or more requested sources are unavailable.",
            )
        raise SorAuthorityError(
            SorAuthorityFailure.AGENT_REVISION_TOOL_UNAVAILABLE,
            "The pinned Agent revision has no read tool for this entity.",
        )
    return tuple(authorized_tools), tuple(authorized_sources.values())


async def _visible_fields(
    session: AsyncSession,
    *,
    organization_id: UUID,
    sources: Sequence[AuthorizedSorSource],
    entity: str,
) -> tuple[SorAgentVisibleFieldResponse, ...]:
    if not sources:
        return ()
    source_access = {source.source_id: source.access for source in sources}
    rows = (
        await session.scalars(
            select(SorFieldMappingModel)
            .join(
                SorSourceStreamModel,
                and_(
                    SorSourceStreamModel.source_id == SorFieldMappingModel.source_id,
                    SorSourceStreamModel.organization_id
                    == SorFieldMappingModel.organization_id,
                    SorSourceStreamModel.vendor_object_key
                    == SorFieldMappingModel.vendor_object_key,
                ),
            )
            .join(
                SorSourceModel,
                and_(
                    SorSourceModel.id == SorFieldMappingModel.source_id,
                    SorSourceModel.organization_id
                    == SorFieldMappingModel.organization_id,
                    SorSourceModel.active_mapping_revision_id
                    == SorFieldMappingModel.mapping_revision_id,
                ),
            )
            .where(
                SorFieldMappingModel.organization_id == organization_id,
                SorFieldMappingModel.source_id.in_(source_access),
                SorSourceStreamModel.canonical_entity_kind == entity,
                SorSourceStreamModel.deleted.is_(False),
                SorFieldMappingModel.agent_visible.is_(True),
                SorFieldMappingModel.state == SorFieldMappingState.ACTIVE,
                SorFieldMappingModel.deleted.is_(False),
            )
            .order_by(
                SorFieldMappingModel.source_id.asc(),
                SorFieldMappingModel.source_label.asc(),
                SorFieldMappingModel.id.asc(),
            )
        )
    ).all()
    return tuple(
        SorAgentVisibleFieldResponse(
            source_id=row.source_id,
            key=(
                row.canonical_target_path
                if row.canonical_target_path is not None
                else f"custom.{row.custom_field_definition_id}"
            ),
            label=row.source_label,
            data_type=row.source_data_type,
            custom=row.custom_field_definition_id is not None,
            writable=(
                source_access[row.source_id] == SorSourceAccess.READ_WRITE
                and row.direction == SorFieldMappingDirection.READ_WRITE
                and row.writable_capability
            ),
            sensitivity=row.sensitivity,
        )
        for row in rows
    )


def _record_response(
    record: SorRecordModel,
    source: AuthorizedSorSource,
    *,
    display_values: dict[str, object] | None = None,
    relations: tuple[SorRecordRelationResponse, ...] = (),
) -> SorAgentRecordResponse:
    as_of = source.last_successful_sync_at or record.projected_at
    stale = (
        datetime.now(timezone.utc) - as_of
    ).total_seconds() > source.freshness_target_seconds
    return SorAgentRecordResponse(
        id=record.id,
        source_id=source.source_id,
        source_name=source.name,
        vendor_key=source.vendor_key,
        profile=record.profile,
        entity=record.canonical_entity_kind,
        human_external_key=record.human_external_key,
        values=dict(record.agent_visible_payload),
        display_values=dict(display_values or {}),
        source_url=record.source_url,
        source_updated_at=record.source_updated_at,
        source_revision=record.source_revision,
        mapping_revision_id=record.mapping_revision_id,
        projected_at=record.projected_at,
        freshness=SorFreshnessResponse(
            as_of=as_of,
            target_seconds=source.freshness_target_seconds,
            stale=stale,
        ),
        relations=relations,
    )


async def _reference_display_values(
    session: AsyncSession,
    *,
    organization_id: UUID,
    profile: SorProfile,
    entity: str,
    records: Sequence[SorRecordModel],
) -> dict[UUID, dict[str, object]]:
    """Resolve page references in one query while preserving raw identities."""
    if not records:
        return {}
    try:
        spec = get_sor_read_spec(profile=profile, entity=entity)
    except KeyError:
        return {}
    references = tuple(
        (
            cast(str, field.value_key),
            cast(str, field.reference_entity),
        )
        for field in spec.fields
        if field.reference_entity is not None and field.value_key is not None
    )
    if not references:
        return {}

    raw_by_record: dict[UUID, dict[str, object]] = {}
    reference_keys: set[tuple[UUID, str, str]] = set()
    for record in records:
        values: dict[str, object] = {}
        for value_key, reference_entity in references:
            raw = record.agent_visible_payload.get(value_key)
            values[value_key] = raw
            for external_id in reference_external_ids(raw):
                reference_keys.add((record.source_id, reference_entity, external_id))
        raw_by_record[record.id] = values

    labels = await resolve_reference_labels(
        session,
        organization_id=organization_id,
        reference_keys=tuple(reference_keys),
    )
    result: dict[UUID, dict[str, object]] = {}
    for record in records:
        display_values: dict[str, object] = {}
        for value_key, reference_entity in references:
            display = reference_display_value(
                raw_by_record[record.id][value_key],
                source_id=record.source_id,
                entity=reference_entity,
                labels=labels,
            )
            if display is not None:
                display_values[value_key] = display
        if display_values:
            result[record.id] = display_values
    return result


def _fingerprint(
    *,
    agent_id: UUID,
    agent_revision: int,
    profile: SorProfile,
    entity: str,
    search: str,
    source_ids: Sequence[UUID],
    record_id: UUID | None,
    external_key: str | None,
    sort_by: SorAgentSortField,
    sort_direction: SorSortDirection,
) -> str:
    payload = json.dumps(
        {
            "agent_id": str(agent_id),
            "agent_revision": agent_revision,
            "profile": profile.value,
            "entity": entity,
            "search": search,
            "source_ids": sorted(str(source_id) for source_id in source_ids),
            "record_id": str(record_id) if record_id is not None else None,
            "external_key": external_key,
            "sort_by": sort_by.value,
            "sort_direction": sort_direction.value,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def _encode_cursor(
    *,
    sort_value: datetime | None,
    record_id: UUID,
    fingerprint: str,
) -> str:
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "f": fingerprint,
            "sort_value": sort_value.isoformat() if sort_value is not None else None,
            "record_id": str(record_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(
    cursor: str | None,
    *,
    fingerprint: str,
) -> tuple[datetime | None, UUID] | None:
    if cursor is None:
        return None
    if not cursor or len(cursor) > _MAX_CURSOR_CHARS:
        raise SorAgentReadError("Agent view cursor is invalid.")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode())
        if (
            not isinstance(value, dict)
            or value.get("v") != _CURSOR_VERSION
            or value.get("f") != fingerprint
        ):
            raise ValueError
        raw_sort_value = value["sort_value"]
        sort_value = (
            datetime.fromisoformat(raw_sort_value)
            if isinstance(raw_sort_value, str)
            else None
        )
        if raw_sort_value is not None and sort_value is None:
            raise ValueError
        record_id = UUID(value["record_id"])
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        raise SorAgentReadError("Agent view cursor is invalid.") from None
    if sort_value is not None and (
        sort_value.tzinfo is None or sort_value.utcoffset() is None
    ):
        raise SorAgentReadError("Agent view cursor is invalid.")
    return sort_value, record_id


def _cursor_predicate(
    *,
    sort_column,
    sort_value: datetime | None,
    record_id: UUID,
    direction: SorSortDirection,
):
    """Select rows after one nulls-last, ID-stabilized cursor boundary."""
    id_after = (
        SorRecordModel.id > record_id
        if direction is SorSortDirection.ASC
        else SorRecordModel.id < record_id
    )
    if sort_value is None:
        return and_(sort_column.is_(None), id_after)
    value_after = (
        sort_column > sort_value
        if direction is SorSortDirection.ASC
        else sort_column < sort_value
    )
    return or_(
        value_after,
        and_(sort_column == sort_value, id_after),
        sort_column.is_(None),
    )


__all__ = ["SorAgentReadError", "read_agent_view"]
