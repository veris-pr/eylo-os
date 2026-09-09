"""Typed corpus screening outcomes and their bounded persisted summary."""

from pydantic import BaseModel, ConfigDict, JsonValue

from eylo.common.contracts.storage_objects import StoredObject

MAX_CORPUS_SKIP_DETAILS = 50
UNSUPPORTED_CORPUS_OBJECT = "unsupported file type"
EMPTY_CORPUS_OBJECT = "empty object"


class SkippedCorpusObject(BaseModel):
    """Human-readable rejection detail; no downloaded content is retained."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    key: str
    reason: str


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
        return {
            "entries": [
                entry.model_dump(mode="json")
                for entry in self.skipped[:MAX_CORPUS_SKIP_DETAILS]
            ],
            "total": len(self.skipped),
        }
