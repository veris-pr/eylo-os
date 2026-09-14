"""Typed published voice settings, isolated from editable and per-call values."""

from pydantic import ConfigDict

from eylo.modules.voice.schemas.api import VoiceConfig


class VoiceConfigSnapshot(VoiceConfig):
    """Reuse the voice schema while refusing replacement of published settings.

    Nested plans are not recursively frozen. Consumers obtain a validated,
    independent configuration before using or modifying per-call policy.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    def for_call(self) -> VoiceConfig:
        """Detach all nested plans and collections; preserve pinned provider refs."""
        return VoiceConfig.model_validate(self.model_dump())
