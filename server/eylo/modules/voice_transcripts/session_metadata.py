"""Content-free session policy snapshots and validation at their owning use sites."""

from pydantic import BaseModel, ConfigDict, StrictBool, TypeAdapter, model_validator

from eylo.common.contracts.json_values import JsonObject

_JSON_OBJECT = TypeAdapter(JsonObject)


class TranscriptStoragePolicy(BaseModel):
    """Read only transcript controls; absent/null historical predicates stay falsey.

    Boolean fields retain the existing persisted configuration contract. They
    are not a new mode or lifecycle. Unrelated session metadata is ignored.
    """

    model_config = ConfigDict(frozen=True, strict=True, hide_input_in_errors=True)

    store_raw_vendor_payloads: StrictBool | None = False
    allow_sensitive_metadata: StrictBool | None = False
    redact_pii_in_transcripts: StrictBool | None = False


class CanonicalStorageRequest(BaseModel):
    """Require an explicit boolean decision; the projection owner handles refusal."""

    model_config = ConfigDict(frozen=True, strict=True, hide_input_in_errors=True)

    canonical_storage_requested: StrictBool


class VoiceSessionMetadata(TranscriptStoragePolicy):
    """Validate new writes while retaining the existing flat JSON and extensions."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="allow",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    recording_consent_required: StrictBool | None = None
    canonical_storage_requested: StrictBool | None = None
    recording_upload_error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def finite_context(cls, value: object) -> JsonObject:
        if isinstance(value, cls):
            value = value.model_dump(
                mode="python", exclude_unset=True, warnings=False
            )
        return _JSON_OBJECT.validate_python(value)

    def as_payload(self) -> JsonObject:
        """Do not insert defaults/nulls; revalidate nested extensions before writing."""
        payload = _JSON_OBJECT.validate_python(
            # Strict validation below owns refusal; serializer warnings would
            # otherwise print an unchecked copied field's raw value first.
            self.model_dump(mode="python", exclude_unset=True, warnings=False)
        )
        type(self).model_validate(payload)
        return payload

    @classmethod
    def merge_upload_error(cls, existing: JsonObject | None, error: str) -> JsonObject:
        """Validate this observation, not unrelated historical policy controls.

        Returning a new flat value makes the JSONB assignment observable to the
        ORM. Policy validation remains owned by the relevant projection reader.
        """
        observation = cls(recording_upload_error=error)
        return {
            **_JSON_OBJECT.validate_python(existing or {}),
            **observation.as_payload(),
        }
