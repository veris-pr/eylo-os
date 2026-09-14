"""Internal schemas for voice transcript services."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import ConfigDict, Field, field_serializer, model_validator

from eylo.common.contracts.json_values import JsonObject
from eylo.common.schemas import (
    EyloBaseModelSchema,
    EyloBaseOrganizationModelSchema,
    EyloBaseSchema,
)
from eylo.modules.voice_transcripts.constants import (
    VoiceAudioTrackKind,
    VoiceCanonicalFailureCode,
    VoiceCanonicalState,
    VoiceRedactionState,
    VoiceRuntimeMode,
    VoiceSegmentRole,
    VoiceSegmentSource,
    VoiceSegmentType,
    VoiceSessionStatus,
    VoiceSpeechOutcome,
)
from eylo.modules.voice_transcripts.segment_metadata import VoiceSegmentMetadata
from eylo.modules.voice_transcripts.session_metadata import VoiceSessionMetadata


class VoiceSessionCreate(EyloBaseSchema):
    organization_id: UUID
    conversation_id: UUID
    user_session_id: UUID | None = None
    session_id: str
    runtime_mode: VoiceRuntimeMode
    transport: str
    agent_id: UUID | None = None
    agent_revision: int | None = Field(default=None, gt=0)
    started_at: datetime
    stt_vendor: str | None = None
    stt_model: str | None = None
    tts_vendor: str | None = None
    tts_model: str | None = None
    tts_voice: str | None = None
    realtime_vendor: str | None = None
    realtime_model: str | None = None
    telephony_call_id: UUID | None = None
    provider_call_id: str | None = None
    telephony_provider: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    recording_enabled: bool = True
    recording_consent: str | None = None
    audio_format: str | None = None
    meta: VoiceSessionMetadata | None = None

    @field_serializer("meta")
    def serialize_meta(self, value: VoiceSessionMetadata | None) -> JsonObject | None:
        return value.as_payload() if value is not None else None

    @model_validator(mode="after")
    def exact_agent_ref(self) -> Self:
        if (self.agent_id is None) != (self.agent_revision is None):
            raise ValueError(
                "Voice transcript sessions require a complete exact agent reference."
            )
        return self


class VoiceSessionUpdate(EyloBaseSchema):
    status: VoiceSessionStatus | None = None
    canonical_state: VoiceCanonicalState | None = None
    canonical_redaction_version: int | None = Field(default=None, gt=0)
    canonical_failure_code: VoiceCanonicalFailureCode | None = None
    canonical_source_complete: bool | None = None
    canonical_projected_at: datetime | None = None
    canonical_message_count: int | None = Field(default=None, ge=0)
    ended_at: datetime | None = None
    ended_reason: str | None = Field(default=None, min_length=1, max_length=64)
    duration_ms: int | None = Field(default=None, ge=0)
    user_audio_recording_id: UUID | None = None
    assistant_audio_recording_id: UUID | None = None
    combined_audio_recording_id: UUID | None = None
    user_audio_url: str | None = None
    assistant_audio_url: str | None = None
    combined_audio_url: str | None = None
    audio_format: str | None = None
    segment_count: int | None = None
    partial_segment_count: int | None = None
    user_talk_time_ms: int | None = None
    assistant_talk_time_ms: int | None = None
    silence_time_ms: int | None = None
    interruption_count: int | None = None
    dtmf_count: int | None = None
    transfer_count: int | None = None
    metrics: JsonObject | None = None
    meta: VoiceSessionMetadata | None = None

    @field_serializer("meta")
    def serialize_meta(self, value: VoiceSessionMetadata | None) -> JsonObject | None:
        return value.as_payload() if value is not None else None


class VoiceSegmentCreate(EyloBaseSchema):
    organization_id: UUID
    voice_session_id: UUID
    conversation_id: UUID
    message_id: UUID | None = None
    request_id: UUID | None = None
    provider_request_id: str | None = None
    source_created_at: datetime | None = None
    sequence: int | None = Field(default=None, ge=0)
    role: VoiceSegmentRole
    segment_type: VoiceSegmentType
    source: VoiceSegmentSource
    speech_outcome: VoiceSpeechOutcome | None = None
    text: str | None = None
    is_partial: bool = False
    language: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    words: list[JsonObject] | None = None
    started_at_ms: int | None = Field(default=None, ge=0)
    ended_at_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    audio_track: VoiceAudioTrackKind | None = None
    audio_start_ms: int | None = Field(default=None, ge=0)
    audio_end_ms: int | None = Field(default=None, ge=0)
    audio_start_byte: int | None = Field(default=None, ge=0)
    audio_end_byte: int | None = Field(default=None, ge=0)
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_input: JsonObject | None = None
    tool_output: JsonObject | None = None
    dtmf_digits: str | None = None
    transfer_to: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    redaction_state: VoiceRedactionState = VoiceRedactionState.NONE
    vendor_metadata: JsonObject | None = None
    meta: VoiceSegmentMetadata | None = None

    @field_serializer("meta")
    def serialize_meta(self, value: VoiceSegmentMetadata | None) -> JsonObject | None:
        return value.as_payload() if value is not None else None


class VoiceSessionInDb(EyloBaseOrganizationModelSchema):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: UUID
    user_session_id: UUID | None = None
    agent_id: UUID | None = None
    agent_revision: int | None = Field(default=None, gt=0)
    session_id: str
    runtime_mode: VoiceRuntimeMode
    transport: str
    status: VoiceSessionStatus
    canonical_state: VoiceCanonicalState = VoiceCanonicalState.NOT_RUN
    canonical_redaction_version: int | None = None
    canonical_failure_code: VoiceCanonicalFailureCode | None = None
    canonical_source_complete: bool | None = None
    canonical_projected_at: datetime | None = None
    canonical_message_count: int = 0
    started_at: datetime
    ended_at: datetime | None = None
    ended_reason: str | None = None
    duration_ms: int | None = None
    user_audio_recording_id: UUID | None = None
    assistant_audio_recording_id: UUID | None = None
    combined_audio_recording_id: UUID | None = None
    user_audio_url: str | None = None
    assistant_audio_url: str | None = None
    combined_audio_url: str | None = None
    audio_format: str | None = None
    stt_vendor: str | None = None
    stt_model: str | None = None
    tts_vendor: str | None = None
    tts_model: str | None = None
    tts_voice: str | None = None
    realtime_vendor: str | None = None
    realtime_model: str | None = None
    telephony_call_id: UUID | None = None
    provider_call_id: str | None = None
    telephony_provider: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    recording_enabled: bool = True
    recording_consent: str | None = None
    segment_count: int = 0
    partial_segment_count: int = 0
    user_talk_time_ms: int | None = None
    assistant_talk_time_ms: int | None = None
    silence_time_ms: int | None = None
    interruption_count: int = 0
    dtmf_count: int = 0
    transfer_count: int = 0
    metrics: JsonObject | None = None
    # Validate historical storage decisions at use so failures retain their
    # canonical outcome instead of failing to load unrelated session fields.
    meta: JsonObject | None = None


class VoiceSegmentInDb(EyloBaseModelSchema):
    model_config = ConfigDict(from_attributes=True)

    organization_id: UUID
    voice_session_id: UUID
    conversation_id: UUID
    message_id: UUID | None = None
    request_id: UUID | None = None
    provider_request_id: str | None = None
    source_created_at: datetime | None = None
    sequence: int
    role: VoiceSegmentRole
    segment_type: VoiceSegmentType
    source: VoiceSegmentSource
    speech_outcome: VoiceSpeechOutcome | None = None
    text: str | None = None
    is_partial: bool = False
    language: str | None = None
    confidence: float | None = None
    words: list[JsonObject] | None = None
    started_at_ms: int | None = None
    ended_at_ms: int | None = None
    duration_ms: int | None = None
    audio_track: VoiceAudioTrackKind | None = None
    audio_start_ms: int | None = None
    audio_end_ms: int | None = None
    audio_start_byte: int | None = None
    audio_end_byte: int | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_input: JsonObject | None = None
    tool_output: JsonObject | None = None
    dtmf_digits: str | None = None
    transfer_to: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    redaction_state: VoiceRedactionState = VoiceRedactionState.NONE
    vendor_metadata: JsonObject | None = None
    meta: JsonObject | None = None
