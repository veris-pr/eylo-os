"""Knowledge index catalog and executable metadata validation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eylo.common.contracts.knowledgebase import (
    DEFAULT_KNOWLEDGE_CHUNKING,
    DEFAULT_KNOWLEDGE_CHUNK_CHARS,
    DEFAULT_KNOWLEDGE_CHUNK_OVERLAP,
    MAX_KNOWLEDGE_CHUNK_CHARS,
    MIN_KNOWLEDGE_CHUNK_CHARS,
    KnowledgeChunkingStrategy,
)


class KnowledgeVendor(StrEnum):
    """Persisted index kinds; socket provider identifiers remain adapter-owned."""

    POSTGRES_FTS = "postgres_fts"
    PGVECTOR = "pgvector"


class VendorSpec(BaseModel):
    """Executable index requirements checked before a KB is created."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )

    name: KnowledgeVendor
    needs_embeddings: bool
    description: str


# Legacy metadata is rejected: embedding authority lives on the provider binding.
EMBEDDING_MODEL_KEY = "embedding_model"


class KnowledgebaseMetadata(BaseModel):
    """Complete, executable knowledgebase behavior configuration."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    chunking: KnowledgeChunkingStrategy = DEFAULT_KNOWLEDGE_CHUNKING
    chunk_size: int = Field(
        default=DEFAULT_KNOWLEDGE_CHUNK_CHARS,
        strict=True,
        ge=MIN_KNOWLEDGE_CHUNK_CHARS,
        le=MAX_KNOWLEDGE_CHUNK_CHARS,
    )
    chunk_overlap: int = Field(
        default=DEFAULT_KNOWLEDGE_CHUNK_OVERLAP,
        strict=True,
        ge=0,
        lt=MAX_KNOWLEDGE_CHUNK_CHARS,
    )

    @model_validator(mode="after")
    def validate_window(self) -> KnowledgebaseMetadata:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


VENDORS: dict[KnowledgeVendor, VendorSpec] = {
    KnowledgeVendor.POSTGRES_FTS: VendorSpec(
        name=KnowledgeVendor.POSTGRES_FTS,
        needs_embeddings=False,
        description="Keyword search over Postgres full-text indexes.",
    ),
    KnowledgeVendor.PGVECTOR: VendorSpec(
        name=KnowledgeVendor.PGVECTOR,
        needs_embeddings=True,
        description="Semantic search over pgvector embeddings.",
    ),
}

KNOWN_VENDORS: tuple[str, ...] = tuple(sorted(vendor.value for vendor in VENDORS))


def _vendor_spec(vendor: str) -> VendorSpec | None:
    try:
        return VENDORS.get(KnowledgeVendor(vendor))
    except ValueError:
        return None


def needs_embeddings(vendor: str) -> bool:
    """Whether this vendor cannot function without an embedding provider."""
    spec = _vendor_spec(vendor)
    return bool(spec and spec.needs_embeddings)


def normalize_metadata(
    metadata: KnowledgebaseMetadata | dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the full persisted config or one stable operator-facing error."""
    return parse_metadata(metadata).model_dump(mode="json")


def parse_metadata(metadata: object) -> KnowledgebaseMetadata:
    """Keep executable settings typed until the persistence boundary."""
    try:
        parsed = KnowledgebaseMetadata.model_validate(
            {} if metadata is None else metadata
        )
    except ValidationError as error:
        first = error.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"]) or "metadata"
        raise ValueError(
            f"Invalid knowledgebase metadata at {location}: {first['msg']}."
        ) from None
    return parsed


def configuration_problem(
    vendor: str,
    metadata: KnowledgebaseMetadata | dict[str, Any] | None,
) -> str | None:
    """Why this configuration cannot work, or None if it can.

    Returns a sentence rather than raising, so the caller decides whether it is
    a 400 on the way in or a refusal at run time — the same check serves both,
    which is the point of it living here.

    This is the check that turns a permanent silent failure into an error an
    operator sees while they still have the form open.
    """
    spec = _vendor_spec(vendor)
    if spec is None:
        return (
            f"Unknown knowledgebase vendor '{vendor}'. "
            f"Available: {', '.join(KNOWN_VENDORS)}."
        )

    present = (
        metadata.model_dump(mode="json")
        if isinstance(metadata, KnowledgebaseMetadata)
        else (metadata or {})
    )
    if EMBEDDING_MODEL_KEY in present:
        return (
            "embedding_model metadata is unsupported. Select an explicit verified "
            "embedding_provider_config_id when creating a pgvector knowledgebase."
        )
    try:
        normalize_metadata(metadata)
    except ValueError as error:
        return str(error)
    return None
