"""Data contracts for the `tools` domain."""

from datetime import datetime
from typing import Annotated, Any, Optional, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from eylo.common.revisions import RevisionAvailability
from eylo.common.schemas import EyloBaseApiSchema, EyloBaseOrganizationModelSchema
from eylo.modules.tools.models import ToolKind
from eylo.modules.tools.schemas.platform import PlatformTool, PlatformToolInputSchema
from eylo.modules.tools.services.tool_register import get_local_tool_config

from .indb import (
    ToolCreateSchema,
    ToolDefinitionFields,
    ToolHeaderFields,
    ToolUpdateFields,
    ToolUpdateSchema,
)


class ToolFilterSchema(EyloBaseApiSchema):
    tool_ids: Annotated[Optional[list[UUID]], Field(None, max_length=100)] = None


class PlatformToolInputApiSchema(PlatformToolInputSchema, EyloBaseApiSchema):
    """Platform tool input schema with camelCase aliases for API."""

    pass


class PlatformToolApiSchema(EyloBaseApiSchema):
    """Platform-native tool schema for API requests/responses."""

    name: str = Field(..., description="Unique tool name for the LLM to reference")
    description: str = Field(
        ..., description="Clear description of what the tool does for the LLM"
    )
    input_schema: PlatformToolInputApiSchema = Field(
        ..., description="JSON Schema defining the tool's input parameters"
    )

    def to_platform(self) -> PlatformTool:
        """Preserve JSON Schema keywords; API casing must not enter the domain."""
        return PlatformTool(
            name=self.name,
            description=self.description,
            input_schema=PlatformToolInputSchema.model_validate(
                self.input_schema.to_json_schema()
            ),
        )


class ToolCreateRequestSchema(ToolDefinitionFields, EyloBaseApiSchema):
    organization_id: SkipJsonSchema[UUID | None] = Field(default=None, exclude=True)
    llm_config: Optional[PlatformToolApiSchema] = Field(
        None, description="LLM schema for the tool"
    )
    executor_config: Optional[dict[str, Any]] = Field(
        default_factory=dict, description="Executor schema for the tool"
    )

    @field_validator("llm_config", mode="before")
    @classmethod
    def validate_llm_config(cls, v: object) -> object:
        """Accept empty create input before replacing it with the registered schema."""
        if v is None or v == {}:
            return PlatformToolApiSchema(
                name="",
                description="",
                input_schema=PlatformToolInputApiSchema(
                    type="object", additional_properties=None
                ),
            )
        if isinstance(v, dict):
            return PlatformToolApiSchema.model_validate(v)
        return v

    @model_validator(mode="after")
    def validate_config_tool_kind(self) -> Self:
        config = get_local_tool_config(self.name)
        self.llm_config = PlatformToolApiSchema.model_validate(
            config.model_dump(by_alias=True, exclude_none=True)
        )
        self.executor_config = {}
        return self

    def to_domain(self, organization_id: UUID) -> ToolCreateSchema:
        """Organization authority comes from the route, not the submitted payload."""
        if self.llm_config is None:
            raise ValueError("Registered local tool schema is missing.")
        return ToolCreateSchema.model_validate(
            {
                **self.model_dump(exclude={"organization_id", "llm_config"}),
                "organization_id": organization_id,
                "llm_config": self.llm_config.to_platform(),
            }
        )

    @field_validator("kind", mode="after")
    def require_operator_managed_kind(cls, v: ToolKind) -> ToolKind:
        if v is not ToolKind.LOCAL:
            raise ValueError(
                "Only registered local tools can be created through this endpoint."
            )
        return v


class ToolUpdateRequestSchema(ToolUpdateFields, EyloBaseApiSchema):
    llm_config: Optional[PlatformToolApiSchema] = Field(
        None, description="LLM schema for the tool"
    )
    executor_config: Optional[dict[str, Any]] = Field(
        None, description="Executor schema for the tool"
    )

    @field_validator("llm_config", mode="before")
    @classmethod
    def validate_llm_config(cls, v: object) -> object:
        """An explicitly empty patch schema retains the existing null semantics."""
        if v is None or v == {}:
            return None
        if isinstance(v, dict):
            return PlatformToolApiSchema.model_validate(v)
        return v

    def to_domain(self) -> ToolUpdateSchema:
        """Keep absent patch fields absent while translating the nested schema."""
        values = self.model_dump(exclude_unset=True, exclude={"llm_config"})
        if "llm_config" in self.model_fields_set:
            values["llm_config"] = (
                self.llm_config.to_platform() if self.llm_config is not None else None
            )
        return ToolUpdateSchema.model_validate(values)


class ToolResponseSchema(
    ToolHeaderFields, EyloBaseOrganizationModelSchema, EyloBaseApiSchema
):
    llm_config: Optional[PlatformToolApiSchema] = Field(
        None, description="LLM schema for the tool"
    )
    executor_config: Optional[dict[str, Any]] = Field(
        None, description="Executor schema for the tool"
    )

    @field_validator("llm_config", mode="before")
    @classmethod
    def validate_llm_config(cls, value: object) -> object:
        if isinstance(value, PlatformTool):
            value = value.model_dump(by_alias=True, exclude_none=True)
        if isinstance(value, dict):
            return PlatformToolApiSchema.model_validate(value)
        return value


class ToolListResponseSchema(EyloBaseApiSchema):
    items: list[ToolResponseSchema]


class ToolPublishRequestSchema(EyloBaseApiSchema):
    expected_draft_version: int = Field(..., gt=0)


class ToolRevokeRequestSchema(EyloBaseApiSchema):
    reason: str = Field(..., min_length=1, max_length=2_000)


class ToolRevisionResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tool_id: UUID
    revision: int
    availability: RevisionAvailability
    published_at: datetime
    published_by: UUID | None
    revoked_at: datetime | None
    revoked_by: UUID | None
    revocation_reason: str | None
    cancellation_requested_at: datetime | None
