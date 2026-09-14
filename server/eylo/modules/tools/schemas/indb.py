"""Data contracts for the `tools` domain."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from eylo.common.revisions import DefinitionLifecycle
from eylo.common.schemas import EyloBaseOrganizationModelSchema
from eylo.modules.tools.models import ToolExecutionMode, ToolKind
from eylo.modules.tools.schemas.platform import PlatformTool, PlatformToolInputSchema


class ToolDefinitionFields(BaseModel):
    """Shared definition fields, without transport-specific tool schemas or ownership."""

    model_config = ConfigDict(allow_inf_nan=False)

    name: str = Field(..., description="Tool name")
    kind: ToolKind = Field(..., description="Tool execution boundary")
    display_name: str = Field(..., description="Tool display name")
    description: str = Field(..., description="Tool description")
    mcp_server_id: Optional[UUID] = Field(None, description="MCP server ID")
    wire_id: Optional[str] = None
    execution_mode: ToolExecutionMode = ToolExecutionMode.AUTO
    executor_config: Optional[dict[str, JsonValue]] = Field(
        default_factory=dict, description="Executor schema for the tool"
    )
    output_schema: Optional[dict[str, JsonValue]] = None


class ToolHeaderFields(ToolDefinitionFields):
    """Revision metadata shared by persisted definitions and operator responses."""

    slug: str = Field(..., description="Tool slug")
    mcp_server_revision: Optional[int] = None
    lifecycle: DefinitionLifecycle = DefinitionLifecycle.DRAFT
    published_revision: Optional[int] = None
    draft_version: int = 1
    draft_dirty: bool = True


class ToolRevisionPayload(BaseModel):
    """Storage snapshot preserving authored JSON Schema, including extension keywords.

    Code-owned executable schemas replace the stored schema on runtime reads.
    Do not require an obsolete stored system/local schema to validate first.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True, allow_inf_nan=False)

    name: str
    slug: str
    kind: ToolKind
    display_name: str | None
    description: str | None
    llm_config: dict[str, JsonValue] | None
    executor_config: dict[str, JsonValue] | None
    output_schema: dict[str, JsonValue] | None
    execution_mode: ToolExecutionMode
    wire_id: str | None
    mcp_server_id: UUID | None


class ToolModelSchema(ToolHeaderFields, EyloBaseOrganizationModelSchema):
    llm_config: PlatformTool = Field(
        ...,
        description="LLM schema for the tool - platform-native format",
    )

    @field_validator("llm_config", mode="before")
    @classmethod
    def validate_llm_config(cls, v: object) -> object:
        """Convert dict to PlatformTool automatically.

        This ensures database values (dicts) are always converted to
        proper Pydantic schemas on load, maintaining type safety.
        """
        if v is None or v == {}:
            # Return a minimal valid PlatformTool for empty/None values
            return PlatformTool(
                name="",
                description="",
                input_schema=PlatformToolInputSchema(
                    type="object", additional_properties=None
                ),
            )
        if isinstance(v, dict):
            return PlatformTool.model_validate(v)
        return v


class ToolCreateSchema(ToolDefinitionFields):
    llm_config: PlatformTool = Field(
        ..., description="LLM schema for the tool - platform-native format"
    )

    organization_id: UUID = Field(..., description="Organization ID for the tool")

    @field_validator("llm_config", mode="before")
    @classmethod
    def validate_llm_config(cls, v: object) -> object:
        """Convert dict to PlatformTool automatically."""
        if v is None or v == {}:
            return PlatformTool(
                name="",
                description="",
                input_schema=PlatformToolInputSchema(
                    type="object", additional_properties=None
                ),
            )
        if isinstance(v, dict):
            return PlatformTool.model_validate(v)
        return v


class ToolUpdateFields(BaseModel):
    """Patch metadata; omitted fields must remain distinct from explicit nulls."""

    model_config = ConfigDict(allow_inf_nan=False)

    expected_draft_version: int
    name: Optional[str] = Field(None, description="Tool name")
    display_name: Optional[str] = Field(None, description="Tool display name")
    description: Optional[str] = Field(None, description="Tool description")

    executor_config: Optional[dict[str, JsonValue]] = Field(
        None, description="Executor schema for the tool"
    )
    output_schema: Optional[dict[str, JsonValue]] = None
    execution_mode: Optional[ToolExecutionMode] = None


class ToolUpdateSchema(ToolUpdateFields):
    llm_config: Optional[PlatformTool] = Field(
        None, description="LLM schema for the tool - platform-native format"
    )

    @field_validator("llm_config", mode="before")
    @classmethod
    def validate_llm_config(cls, v: object) -> object:
        """Convert dict to PlatformTool automatically."""
        if v is None or v == {}:
            return None
        if isinstance(v, dict):
            return PlatformTool.model_validate(v)
        return v


class ToolInDb(ToolModelSchema):
    model_config = ConfigDict(from_attributes=True)

    def get_input_schema(self) -> dict[str, JsonValue]:
        """Get the tool's input schema as a dictionary.

        Returns:
            dict: The input schema from llm_config.input_schema

        Example:
            >>> tool = ToolInDb(...)
            >>> schema = tool.get_input_schema()
            >>> print(schema['properties'])

        """
        return self.llm_config.input_schema.to_json_schema()

    def get_llm_tool_dict(self) -> dict[str, JsonValue]:
        """Get the complete LLM tool configuration as a dictionary.

        Useful for token counting and vendor transformations.

        Returns:
            dict: Complete tool definition with name, description, and input_schema

        Example:
            >>> tool = ToolInDb(...)
            >>> tool_dict = tool.get_llm_tool_dict()
            >>> # {'name': 'get_weather', 'description': '...', 'input_schema': {...}}

        """
        return self.llm_config.model_dump(by_alias=True, exclude_none=True)
