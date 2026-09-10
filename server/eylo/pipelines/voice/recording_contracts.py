"""Recording-owned work snapshots and content-free durable receipts."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from eylo.absurd_work import DurableState


class RecordingTrack(StrEnum):
    """Stable recording object names, distinct from transcript speaker roles."""

    USER = "user"
    AGENT = "agent"


class RecordingWorkAvailability(StrEnum):
    """A missing product row, not a persisted durable lifecycle state."""

    DELETED = "deleted"


class RecordingUploadEffect(StrEnum):
    """Bounded upload uncertainty recorded while retaining staged audio."""

    ACCEPTED_OR_UNKNOWN = "accepted_or_unknown"
    UNKNOWN = "unknown"
    TERMINAL = "terminal"
    INCOMPLETE = "incomplete"


class RecordingAudioRetention(StrEnum):
    """Failure handling preserves bytes when an external effect may exist."""

    DISCARD = "discard"
    PRESERVE = "preserve"


class RecordingUploadParams(BaseModel):
    """Only identity crosses the queue; arbitrary objects cannot stringify as IDs."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_id: UUID
    recording_id: UUID

    @field_validator("organization_id", "recording_id", mode="before")
    @classmethod
    def decode_uuid(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value


class RecordingUploadReceipt(RecordingUploadParams):
    """Product state without audio, storage credentials or provider error content."""

    state: DurableState | RecordingWorkAvailability

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


class RecordingUploadFinished(BaseModel):
    """A completed DB attempt and its optional availability fact to nudge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt: RecordingUploadReceipt
    event_id: UUID | None = None


class RecordingUploadStaged(BaseModel):
    """Detached local input; raw tracks must never enter checkpoint serialization.

    Null fields are retained for the worker's existing failure classification.
    Constructing this snapshot does not change an attempt into a valid upload.
    """

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    provider_config_id: UUID | None
    provider_config_revision: int | None
    user_wav: bytes | None = Field(exclude=True, repr=False)
    agent_wav: bytes | None = Field(exclude=True, repr=False)
    user_key: str | None
    agent_key: str | None
