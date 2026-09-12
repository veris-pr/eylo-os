"""Validated projections of active and transition embedding columns from DB rows."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eylo.common.contracts.json_values import JsonObject


class _EmbeddingRecord(BaseModel):
    """ORM input ends here; downstream code uses validated, detached values."""

    model_config = ConfigDict(
        from_attributes=True,
        frozen=True,
        strict=True,
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    organization_id: UUID

    def to_columns(self) -> dict[str, object]:
        """Serialize for ORM construction/update; the caller owns the tenant field."""
        validated = type(self).model_validate(self)
        return validated.model_dump(exclude={"organization_id"})


class EmbeddingRecord(_EmbeddingRecord):
    """Active identity on a vector owner, formation job or ingestion job."""

    embedding_provider_config_id: UUID | None
    embedding_provider_config_revision: int | None
    embedding_provider: str | None
    embedding_endpoint: str | None
    embedding_model: str | None
    embedding_dimensions: int | None
    embedding_semantic_options: JsonObject | None
    embedding_space_id: str | None


class TargetEmbeddingRecord(_EmbeddingRecord):
    """Staged destination on an owner or immutable reindex job."""

    target_embedding_provider_config_id: UUID | None
    target_embedding_provider_config_revision: int | None
    target_embedding_provider: str | None
    target_embedding_endpoint: str | None
    target_embedding_model: str | None
    target_embedding_dimensions: int | None
    target_embedding_semantic_options: JsonObject | None
    target_embedding_space_id: str | None


class SourceEmbeddingRecord(_EmbeddingRecord):
    """Original coordinate space pinned to an immutable reindex job."""

    source_embedding_provider_config_id: UUID | None
    source_embedding_provider_config_revision: int | None
    source_embedding_provider: str | None
    source_embedding_endpoint: str | None
    source_embedding_model: str | None
    source_embedding_dimensions: int | None
    source_embedding_semantic_options: JsonObject | None
    source_embedding_space_id: str | None
