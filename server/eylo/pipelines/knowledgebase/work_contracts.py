"""Wire contracts for organization-owned Knowledge jobs and corpus sweeps."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from eylo.absurd_work import DurableState


class KnowledgeJobParams(BaseModel):
    """ID-only ingestion/reindex input; decode UUID strings, never other objects."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    job_id: UUID

    @field_validator("organization_id", "job_id", mode="before")
    @classmethod
    def decode_uuid(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @property
    def work_id(self) -> UUID:
        return self.job_id

    def to_task_payload(self) -> dict[str, JsonValue]:
        return KnowledgeJobParams(
            organization_id=self.organization_id, job_id=self.job_id
        ).model_dump(mode="json")


class KnowledgeCorpusParams(BaseModel):
    """Corpus imports use their own identity key, not a child ingestion job ID."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    import_id: UUID

    @field_validator("organization_id", "import_id", mode="before")
    @classmethod
    def decode_uuid(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @property
    def work_id(self) -> UUID:
        return self.import_id

    def to_task_payload(self) -> dict[str, JsonValue]:
        return KnowledgeCorpusParams(
            organization_id=self.organization_id, import_id=self.import_id
        ).model_dump(mode="json")


class KnowledgeReindexReceipt(BaseModel):
    """Preserve the full successful/terminal reindex receipt and its counters."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    organization_id: UUID
    job_id: UUID
    state: DurableState
    source_chunk_count: int = Field(ge=0)
    indexed_chunk_count: int = Field(ge=0)

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


class KnowledgeJobFailureReceipt(BaseModel):
    """The existing minimal reindex failure result; no invented counters."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    job_id: UUID
    state: DurableState

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


class KnowledgeCorpusReceipt(BaseModel):
    """Persisted discovery and queue counts; does not imply children completed."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    organization_id: UUID
    import_id: UUID
    state: DurableState
    discovered: int = Field(ge=0)
    queued: int = Field(ge=0)

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


class KnowledgeCorpusFailureReceipt(BaseModel):
    """Corpus failure has an import ID, not an ingestion or reindex job ID."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    import_id: UUID
    state: DurableState

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


class KnowledgeCorpusFailure(StrEnum):
    """Safe codes filed by the corpus workflow, independent of vendor details."""

    NOT_CONFIGURED = "knowledge_provider_not_configured"
    IMPORT = "knowledge_corpus_import_failed"
