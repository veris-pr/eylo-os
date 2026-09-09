"""ID-only workflow input and privacy-safe ingestion receipts and timeline facts."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from eylo.absurd_work import DurableState


class KnowledgeIngestionFailure(StrEnum):
    """Stable failure codes persisted by ingestion, never vendor exception text."""

    NOT_CONFIGURED = "knowledge_provider_not_configured"
    EXTRACTION = "knowledge_document_extraction_failed"
    INVALID = "knowledge_ingestion_invalid"
    PROVIDER = "knowledge_provider_failed"
    INGESTION = "knowledge_ingestion_failed"


class KnowledgeIngestionEvent(StrEnum):
    """Existing user-session events emitted by the ingestion workflow."""

    STARTED = "knowledge.ingestion.started"
    COMPLETED = "knowledge.ingestion.completed"
    FAILED = "knowledge.ingestion.failed"
    CANCELLED = "knowledge.ingestion.cancelled"


KNOWLEDGE_INGESTION_SUBJECT = "knowledge.ingestion"


class KnowledgeIngestionReceipt(BaseModel):
    """Serialize the existing receipt shape, including its failure-only variant."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    job_id: UUID
    state: DurableState
    organization_id: UUID | None = None
    document_id: UUID | None = None

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json", exclude_none=True)


class KnowledgeIngestionFact(BaseModel):
    """Only document identity and a bounded failure code enter the timeline."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    knowledgebase_id: UUID
    document_id: UUID
    failure_code: KnowledgeIngestionFailure | None = None

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json", exclude_none=True)
