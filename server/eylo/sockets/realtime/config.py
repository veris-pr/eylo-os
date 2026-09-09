"""Vendor-agnostic configuration for a realtime voice session.

Built from VoiceConfig + ConversationContext at session start.
Passed to RealtimeFactory and then to the vendor adapter.
"""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import (
    Field,
    InstanceOf,
    StrictStr,
)
from pydantic.json_schema import SkipJsonSchema

from eylo.common.contracts.realtime_runtime import (
    RealtimeContextCompression,
    RealtimeEndpointingSensitivity,
    RealtimeInferenceConfig,
)
from eylo.common.contracts.tool_record import ToolRecord


class RealtimeVendor(str, Enum):
    """Socket selection; module catalogs translate at the pipeline boundary."""

    AMAZON_NOVA_SONIC = "amazon-nova-sonic"
    GEMINI_LIVE = "gemini-live"
    OPENAI_REALTIME = "openai-realtime"


class RealtimeSessionConfig(RealtimeInferenceConfig):
    """Session snapshot; replacements are validated before transport effects."""

    # Identity (from WSSessionState + conversation)
    organization_id: UUID
    conversation_id: UUID
    agent_id: UUID
    session_id: StrictStr = Field(min_length=1, pattern=r"\S")
    voice_session_row_id: UUID | None = None

    # Vendor selection
    vendor: RealtimeVendor

    # LLM config
    system_prompt: StrictStr = ""

    # Tools — platform format, adapter transforms to vendor format
    tools: list[SkipJsonSchema[InstanceOf[ToolRecord]]] = Field(default_factory=list)

    def updated(
        self,
        *,
        system_prompt: str | None = None,
        tools: list[ToolRecord] | None = None,
        voice: str | None = None,
        temperature: float | None = None,
    ) -> RealtimeSessionConfig:
        """Validate the complete replacement; None retains the current setting."""
        return RealtimeSessionConfig.model_validate(
            self.model_copy(
                update={
                    "system_prompt": self.system_prompt
                    if system_prompt is None
                    else system_prompt,
                    "tools": self.tools if tools is None else tools,
                    "voice": self.voice if voice is None else voice,
                    "temperature": self.temperature
                    if temperature is None
                    else temperature,
                }
            )
        )
