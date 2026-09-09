"""Agent configuration contract for the Eylo framework path."""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict, Field, SerializeAsAny

from .common import FrameworkMetadata, FrozenFrameworkModel, JsonObject
from .guardrail import GuardrailSpec
from .handoff import HandoffSpec
from .model import ModelSettings
from .tool import ToolSpec


class AgentSpec(FrozenFrameworkModel):
    """Pure agent configuration resolved from Eylo domain data."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    id: UUID | None = None
    organization_id: UUID | None = None
    name: str
    instructions: str
    model_settings: ModelSettings
    tools: tuple[ToolSpec, ...] = ()
    handoffs: tuple[HandoffSpec, ...] = ()
    guardrails: tuple[GuardrailSpec, ...] = ()
    output_schema: JsonObject | None = None
    metadata: SerializeAsAny[FrameworkMetadata] = Field(
        default_factory=FrameworkMetadata
    )
