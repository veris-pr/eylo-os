"""Apply provider-independent voice behavior to a live session."""

from __future__ import annotations

from typing import Protocol

from eylo.modules.voice.schemas.api import (
    AmbientNoiseConfig,
    BackgroundAudioConfig,
    FillerConfig,
    VoiceConfig,
)


class VoiceInteractionState(Protocol):
    ambient_noise_config: AmbientNoiseConfig | None
    filler_config: FillerConfig | None


def apply_voice_interaction_config(
    session_state: VoiceInteractionState,
    voice_config: VoiceConfig,
) -> None:
    """Copy policy values so live session edits cannot mutate published config."""
    background_audio = resolve_background_audio_config(voice_config)
    session_state.ambient_noise_config = background_audio.ambient_noise.model_copy(
        deep=True
    )
    session_state.filler_config = background_audio.filler.model_copy(deep=True)


def resolve_background_audio_config(
    voice_config: VoiceConfig,
) -> BackgroundAudioConfig:
    """Return the canonical background-audio section."""
    return voice_config.background_audio


__all__ = ["apply_voice_interaction_config", "resolve_background_audio_config"]
