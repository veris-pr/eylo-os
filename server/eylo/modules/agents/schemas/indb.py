"""Data contracts for the `agents` domain."""

from enum import StrEnum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from eylo.common.contracts.json_values import JsonObject
from eylo.common.revisions import DefinitionLifecycle
from eylo.common.schemas import (
    EyloBaseModelSchema,
    EyloBaseSchema,
    EyloOrganizationModelSchema,
)
from eylo.modules.agents.models import AgentKind, AgentStatus
from eylo.modules.llm_configs.schemas import LLMOverridesSchema


class AgentBase(EyloOrganizationModelSchema):
    name: str = Field(..., max_length=100)
    slug: str = Field(..., max_length=100)
    llm_provider_config_id: UUID | None = None
    llm_provider_config_revision: int | None = Field(default=None, gt=0)
    email_provider_config_id: UUID | None = None
    email_provider_config_revision: int | None = Field(default=None, gt=0)
    webrtc_provider_config_id: UUID | None = None
    webrtc_provider_config_revision: int | None = Field(default=None, gt=0)
    voice_config_id: UUID | None = None
    voice_config_revision: int | None = Field(default=None, gt=0)
    llm_overrides: LLMOverridesSchema = Field(default_factory=LLMOverridesSchema)
    reranking_provider_config_id: UUID | None = None
    reranking_provider_config_revision: int | None = Field(default=None, gt=0)
    memory_provider_config_id: UUID | None = None
    memory_provider_config_revision: int | None = Field(default=None, gt=0)
    allow_file_uploads: bool = False
    file_upload_embedding_provider_config_id: UUID | None = None
    file_upload_embedding_provider_config_revision: int | None = Field(
        default=None, gt=0
    )
    instruction_template_id: UUID | None = None
    description: Optional[str] = None
    webhook: Optional[str] = None
    status: AgentStatus = Field(AgentStatus.DRAFT, description="Status of the agent.")
    kind: AgentKind = Field(
        AgentKind.CONVERSATIONAL, description="Conversational or background agent."
    )
    implementation: Optional[str] = Field(
        None,
        description=(
            "Registry slug naming first-party code for a background agent. "
            "Null means prompt-only."
        ),
    )
    organization_id: UUID = Field(..., description="Organization ID for the agent.")
    prompt: JsonObject | None = Field(
        None, description="Prompt configuration for the agent."
    )
    lifecycle: DefinitionLifecycle = DefinitionLifecycle.DRAFT
    published_revision: int | None = Field(default=None, gt=0)
    draft_version: int = Field(default=1, gt=0)
    draft_dirty: bool = True


class AgentCreate(EyloBaseSchema):
    organization_id: UUID
    kind: AgentKind = AgentKind.CONVERSATIONAL
    implementation: Optional[str] = None
    llm_provider_config_id: UUID | None = None
    email_provider_config_id: UUID | None = None
    webrtc_provider_config_id: UUID | None = None
    voice_config_id: UUID | None = None
    voice_config_revision: int | None = Field(default=None, gt=0)
    llm_overrides: LLMOverridesSchema = Field(default_factory=LLMOverridesSchema)
    reranking_provider_config_id: UUID | None = None
    memory_provider_config_id: UUID | None = None
    allow_file_uploads: bool = False
    file_upload_embedding_provider_config_id: UUID | None = None
    instruction_template_id: UUID | None = None
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    prompt: JsonObject | None = None


class AgentUpdateField(StrEnum):
    """Draft patch presence keys; values remain typed on AgentUpdate itself."""

    ID = "id"
    ORGANIZATION_ID = "organization_id"
    NAME = "name"
    LLM_PROVIDER_CONFIG_ID = "llm_provider_config_id"
    LLM_PROVIDER_CONFIG_REVISION = "llm_provider_config_revision"
    EMAIL_PROVIDER_CONFIG_ID = "email_provider_config_id"
    EMAIL_PROVIDER_CONFIG_REVISION = "email_provider_config_revision"
    WEBRTC_PROVIDER_CONFIG_ID = "webrtc_provider_config_id"
    WEBRTC_PROVIDER_CONFIG_REVISION = "webrtc_provider_config_revision"
    VOICE_CONFIG_ID = "voice_config_id"
    VOICE_CONFIG_REVISION = "voice_config_revision"
    LLM_OVERRIDES = "llm_overrides"
    RERANKING_PROVIDER_CONFIG_ID = "reranking_provider_config_id"
    RERANKING_PROVIDER_CONFIG_REVISION = "reranking_provider_config_revision"
    MEMORY_PROVIDER_CONFIG_ID = "memory_provider_config_id"
    MEMORY_PROVIDER_CONFIG_REVISION = "memory_provider_config_revision"
    ALLOW_FILE_UPLOADS = "allow_file_uploads"
    FILE_UPLOAD_EMBEDDING_PROVIDER_CONFIG_ID = (
        "file_upload_embedding_provider_config_id"
    )
    FILE_UPLOAD_EMBEDDING_PROVIDER_CONFIG_REVISION = (
        "file_upload_embedding_provider_config_revision"
    )
    INSTRUCTION_TEMPLATE_ID = "instruction_template_id"
    DESCRIPTION = "description"
    IMPLEMENTATION = "implementation"
    PROMPT = "prompt"
    EXPECTED_DRAFT_VERSION = "expected_draft_version"


class AgentUpdate(EyloBaseSchema):
    id: UUID | None = None
    organization_id: UUID | None = None
    name: Optional[str] = Field(None, max_length=100)
    llm_provider_config_id: UUID | None = None
    llm_provider_config_revision: int | None = Field(default=None, gt=0)
    email_provider_config_id: UUID | None = None
    email_provider_config_revision: int | None = Field(default=None, gt=0)
    webrtc_provider_config_id: UUID | None = None
    webrtc_provider_config_revision: int | None = Field(default=None, gt=0)
    voice_config_id: UUID | None = None
    voice_config_revision: int | None = Field(default=None, gt=0)
    llm_overrides: LLMOverridesSchema | None = None
    reranking_provider_config_id: UUID | None = None
    reranking_provider_config_revision: int | None = Field(default=None, gt=0)
    memory_provider_config_id: UUID | None = None
    memory_provider_config_revision: int | None = Field(default=None, gt=0)
    allow_file_uploads: bool = False
    file_upload_embedding_provider_config_id: UUID | None = None
    file_upload_embedding_provider_config_revision: int | None = Field(
        default=None, gt=0
    )
    instruction_template_id: UUID | None = None
    description: Optional[str] = None
    # `kind` is deliberately absent: flipping it after creation would strand
    # whatever the old kind allowed — swarm memberships for a conversational
    # agent, attachments for a background one — and the validation that
    # rejected those combinations runs at write time, not retroactively.
    implementation: Optional[str] = None
    prompt: JsonObject | None = None
    expected_draft_version: int | None = Field(default=None, gt=0)


class AgentInDb(AgentBase):
    class Config:
        from_attributes = True


class AgentToolBase(EyloBaseModelSchema):
    agent_id: UUID = Field(..., description="Agent ID for the tool.")
    tool_id: UUID = Field(..., description="Tool ID for the agent.")
    tool_revision: int = Field(..., gt=0, description="Exact tool revision.")
    organization_id: UUID = Field(..., description="Shared organization scope.")


class AgentToolCreate(BaseModel):
    agent_id: UUID = Field(..., description="Agent ID for the tool.")
    tool_id: UUID = Field(..., description="Tool ID for the agent.")
    tool_revision: int = Field(..., gt=0, description="Exact tool revision.")
    organization_id: UUID = Field(..., description="Shared organization scope.")


class AgentToolInDb(AgentToolBase):
    class Config:
        from_attributes = True


class AgentBackgroundAgentCreate(BaseModel):
    background_agent_id: UUID = Field(..., description="The background agent.")
    expected_draft_version: int = Field(..., gt=0)


class AgentBackgroundAgentUpdate(BaseModel):
    enabled: bool = Field(..., description="Whether this attachment dispatches.")
    expected_draft_version: int = Field(..., gt=0)


class AgentBackgroundAgentInDb(EyloBaseModelSchema):
    agent_id: UUID
    background_agent_id: UUID
    enabled: bool = False

    class Config:
        from_attributes = True
