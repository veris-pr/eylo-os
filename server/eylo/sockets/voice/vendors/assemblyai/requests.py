"""Consumed AssemblyAI v3 connection parameters and outbound control frames."""

import json
from enum import StrEnum
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict


class AssemblyAIControlKind(StrEnum):
    FORCE_ENDPOINT = "ForceEndpoint"
    TERMINATE = "Terminate"


class AssemblyAIControl(BaseModel):
    """A native control, ordered with audio by the stream's sender."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: AssemblyAIControlKind


class AssemblyAIConnectionQuery(BaseModel):
    """Transport projection of validated native settings; credentials stay in headers."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    speech_model: str
    sample_rate: int
    encoding: str
    end_of_turn_confidence_threshold: float
    min_turn_silence: int
    max_turn_silence: int
    format_turns: bool
    keyterms_prompt: tuple[str, ...] | None

    def query_string(self) -> str:
        """List-valued keyterms use JSON, not an ambiguous comma-joined value."""
        fields = self.model_dump(exclude_none=True)
        fields["format_turns"] = json.dumps(self.format_turns)
        if self.keyterms_prompt is not None:
            fields["keyterms_prompt"] = json.dumps(self.keyterms_prompt)
        return urlencode(fields)
