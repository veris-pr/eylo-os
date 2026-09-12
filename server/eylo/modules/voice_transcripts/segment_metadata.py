"""Platform-owned transcript provenance with finite, extensible stored context."""

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    TypeAdapter,
    field_validator,
    model_validator,
)

from eylo.common.contracts.json_values import JsonObject
from eylo.common.contracts.messages import MessageKind
from eylo.common.contracts.voice import VoiceRequestSource

_JSON_OBJECT = TypeAdapter(JsonObject)


class VoiceSegmentMetadata(BaseModel):
    """Omitted provenance remains omitted; custom context retains its existing keys."""

    model_config = ConfigDict(
        frozen=True, extra="allow", hide_input_in_errors=True,
        revalidate_instances="always",
    )

    message_kind: MessageKind | None = None
    source_sequence: StrictInt | None = Field(default=None, ge=1)
    redaction_version: StrictInt | None = Field(default=None, ge=1)
    policy_source: VoiceRequestSource | None = None

    @field_validator("message_kind")
    @classmethod
    def known_message_kind(cls, value: MessageKind | None) -> MessageKind | None:
        if value is not None and value not in tuple(MessageKind):
            raise ValueError("Transcript provenance requires a known message kind.")
        return value

    @model_validator(mode="before")
    @classmethod
    def finite_context(cls, value: object) -> JsonObject:
        if isinstance(value, cls):
            value = value.model_dump(mode="python", exclude_unset=True, warnings=False)
        return _JSON_OBJECT.validate_python(value)

    def as_payload(self) -> JsonObject:
        """Export enum values without introducing defaults or accepting copied garbage."""
        payload = _JSON_OBJECT.validate_python(
            self.model_dump(mode="python", exclude_unset=True, warnings=False)
        )
        type(self).model_validate(payload)
        return payload
