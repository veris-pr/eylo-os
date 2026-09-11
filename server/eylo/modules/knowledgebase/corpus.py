"""Typed corpus screening outcomes and their bounded persisted summary."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from eylo.common.contracts.storage_objects import StoredObject

MAX_CORPUS_SKIP_DETAILS = 50
UNSUPPORTED_CORPUS_OBJECT = "unsupported file type"
EMPTY_CORPUS_OBJECT = "empty object"


class SkippedCorpusObject(BaseModel):
    """Human-readable rejection detail; no downloaded content is retained."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    key: str
    reason: str


class CorpusSkipCount(BaseModel):
    """Event projection of stored counts; retain historical integer conversion."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    total: int = 0

    @field_validator("total", mode="before")
    @classmethod
    def parse_total(cls, value: object) -> int:
        if not isinstance(value, (str, int, float)):
            raise ValueError("Corpus skipped total must be numeric.")
        return int(value)


class CorpusSkipSummary(CorpusSkipCount):
    """Bounded details persisted alongside the full skipped-object count."""

    model_config = ConfigDict(extra="forbid")

    entries: list[SkippedCorpusObject] = Field(max_length=MAX_CORPUS_SKIP_DETAILS)


class CorpusScreening(BaseModel):
    """Preserve listing order while separating importable and rejected objects."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    keep: tuple[StoredObject, ...]
    skipped: tuple[SkippedCorpusObject, ...]

    def skipped_summary(self) -> dict[str, JsonValue] | None:
        if not self.skipped:
            return None
        return CorpusSkipSummary(
            entries=list(self.skipped[:MAX_CORPUS_SKIP_DETAILS]),
            total=len(self.skipped),
        ).model_dump(mode="json")
