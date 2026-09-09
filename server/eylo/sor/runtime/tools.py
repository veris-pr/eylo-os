"""Schema-backed declarations for the stable profile-native SOR tool surface."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from eylo.sor.knowledge.contracts import KnowledgeToolName
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.command_payloads import command_payload_type
from eylo.sor.shared.contracts import (
    SorCommandPayload,
    SorProfile,
    SorToolEffect,
    SorToolSpec,
)
from eylo.sor.shared.query import SorAgentSortField, SorSortDirection


class SorReadSelectionInput(BaseModel):
    """Agent-safe selectors shared by fixed-target and polymorphic SOR reads."""

    model_config = ConfigDict(extra="forbid")

    source_ids: tuple[UUID, ...] = Field(
        default=(),
        max_length=50,
        description=(
            "Optional exact source IDs from a prior tool result. Omit to search all "
            "sources granted to this Agent revision."
        ),
    )
    record_id: UUID | None = Field(
        default=None,
        description="Optional Eylo canonical record ID from a prior tool result.",
    )
    external_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=320,
        description="Optional human-readable source key from a prior tool result.",
    )
    search: str = Field(
        default="",
        max_length=1_000,
        description="Optional lexical search over Agent-visible mapped fields.",
    )
    limit: int = Field(default=25, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2_048)
    sort_by: SorAgentSortField = Field(
        default=SorAgentSortField.PROJECTED_AT,
        description=(
            "Sort by Eylo projection time or the source system's update time."
        ),
    )
    sort_direction: SorSortDirection = Field(
        default=SorSortDirection.DESC,
        description="Sort ascending or descending; null timestamps remain last.",
    )

    @model_validator(mode="after")
    def validate_identity(self) -> "SorReadSelectionInput":
        if self.record_id is not None and self.external_key is not None:
            raise ValueError("Select a record by ID or external key, not both.")
        return self


class SorReadToolInput(SorReadSelectionInput):
    """Runtime read contract; declaration schemas narrow the target per tool."""

    entity: str | None = Field(
        default=None,
        min_length=1,
        max_length=96,
        pattern=r"^[a-z][a-z0-9_]*$",
        description=(
            "Canonical target entity. Supply this only when the tool declaration "
            "lists more than one selectable target."
        ),
    )


class SorDocumentGetInput(SorReadSelectionInput):
    """Bounded current-content window for one external document."""

    content_offset: int = Field(
        default=0,
        ge=0,
        le=1_000_000,
        description="Character offset into the normalized current document content.",
    )
    content_limit_chars: int = Field(
        default=20_000,
        ge=1,
        le=50_000,
        description=(
            "Maximum normalized content characters to return. Continue with the "
            "next offset when the response reports more content."
        ),
    )


class SorMutationToolInput(BaseModel):
    """Common identity fields extended by each tool's typed payload model."""

    model_config = ConfigDict(extra="forbid")

    payload: SorCommandPayload
    source_id: UUID | None = Field(
        default=None,
        description=(
            "Writable source ID from a prior tool result. Omit only when exactly one "
            "authorized source can execute this action."
        ),
    )
    target_record_id: UUID | None = Field(
        default=None,
        description=(
            "Canonical target record ID for updates. Omit only for create actions."
        ),
    )


@dataclass(frozen=True, slots=True)
class SorToolDeclaration:
    """One unique model-visible tool and the schema used to materialize it."""

    profile: SorProfile
    spec: SorToolSpec
    function: Callable[..., Any]


@lru_cache(maxsize=1)
def iter_sor_tool_declarations() -> tuple[SorToolDeclaration, ...]:
    """Build deterministic declarations from the validated profile registry."""
    declarations: list[SorToolDeclaration] = []
    for profile in get_sor_registry().list_profiles():
        for spec in profile.tools:
            declarations.append(
                SorToolDeclaration(
                    profile=profile.profile,
                    spec=spec,
                    function=_declaration_function(profile.profile, spec),
                )
            )
    return tuple(declarations)


def resolve_sor_tool(tool_name: str) -> tuple[SorProfile, SorToolSpec] | None:
    """Resolve one globally unique SOR tool name without accepting aliases."""
    for declaration in iter_sor_tool_declarations():
        if declaration.spec.name == tool_name:
            return declaration.profile, declaration.spec
    return None


def _declaration_function(
    profile: SorProfile,
    spec: SorToolSpec,
) -> Callable[..., Any]:
    async def execute_through_sor_pipeline(**_kwargs: Any) -> dict[str, object]:
        raise RuntimeError("SOR tools require platform SOR dispatch.")

    execute_through_sor_pipeline.__name__ = spec.name
    execute_through_sor_pipeline.__doc__ = _tool_description(spec)
    execute_through_sor_pipeline.__eylo_schema_model__ = (  # type: ignore[attr-defined]
        read_tool_input_model(spec)
        if spec.effect is SorToolEffect.READ
        else mutation_tool_input_model(profile=profile, spec=spec)
    )
    return execute_through_sor_pipeline


def read_tool_input_model(spec: SorToolSpec) -> type[SorReadSelectionInput]:
    """Expose entity choice only when one read genuinely has several targets."""
    if spec.name == KnowledgeToolName.GET:
        return SorDocumentGetInput
    targets = tuple(sorted(spec.target_entities))
    if len(targets) == 1:
        return SorReadSelectionInput
    return create_model(
        f"{''.join(part.title() for part in spec.name.split('_'))}Input",
        __base__=SorReadSelectionInput,
        entity=(
            str,
            Field(
                description=(
                    "Canonical target entity for this read. Choose exactly one of: "
                    f"{', '.join(targets)}."
                ),
                json_schema_extra={"enum": list(targets)},
            ),
        ),
    )


@lru_cache(maxsize=None)
def mutation_tool_input_model(
    *,
    profile: SorProfile,
    spec: SorToolSpec,
) -> type[SorMutationToolInput]:
    """Expose the profile-owned command object instead of an untyped JSON bag."""
    payload_model = command_payload_type(profile=profile, tool_name=spec.name)
    return create_model(
        f"{''.join(part.title() for part in spec.name.split('_'))}Input",
        __base__=SorMutationToolInput,
        payload=(
            payload_model,
            Field(
                description=(
                    "Typed domain data for this action. Mapped create/update fields "
                    "must use keys returned by the matching describe-fields tool."
                )
            ),
        ),
    )


def _tool_description(spec: SorToolSpec) -> str:
    targets = tuple(sorted(spec.target_entities))
    related = tuple(sorted(spec.entities - spec.target_entities))
    target_guidance = (
        f"Target entity: {targets[0]}."
        if len(targets) == 1
        else f"Select one target entity: {', '.join(targets)}."
    )
    related_guidance = f" Related data scope: {', '.join(related)}." if related else ""
    freshness = (
        "Reads Eylo's synchronized canonical projection and returns source, mapping, "
        "and freshness provenance."
        if spec.effect is SorToolEffect.READ
        else "Files one durable source command and returns only its terminal receipt."
    )
    return f"{spec.description} {freshness} {target_guidance}{related_guidance}"


__all__ = [
    "SorMutationToolInput",
    "SorDocumentGetInput",
    "SorReadSelectionInput",
    "SorReadToolInput",
    "SorToolDeclaration",
    "iter_sor_tool_declarations",
    "mutation_tool_input_model",
    "read_tool_input_model",
    "resolve_sor_tool",
]
