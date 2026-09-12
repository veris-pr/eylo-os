"""Vendor-neutral embedding types.

Embeddings are their own capability, not a corner of the LLM one. That was a
real defect before this existed: the embedder took whichever LLM provider was
default, read its API key, and called OpenAI's embeddings endpoint — so an
organization on Anthropic sent an Anthropic key to OpenAI, for an API Anthropic
does not offer at all. The same held for Groq, Cerebras, Sarvam and Bedrock.

A conversation model and an embedding model are different products from
different vendors with different keys. Treating them as one was the mistake.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from eylo.common.contracts.embedding_records import (
    EmbeddingRecord,
    SourceEmbeddingRecord,
    TargetEmbeddingRecord,
)
from eylo.common.contracts.json_values import JsonObject

type DocumentEmbedder = Callable[[list[str]], Awaitable[list[list[float]]]]
type QueryEmbedder = Callable[[str], Awaitable[list[float]]]


class EmbeddingInput(StrEnum):
    """What a batch of text is *for*.

    OpenAI ignores this; Voyage and Cohere do not. Asymmetric embedding — where
    a query and a document are embedded differently — measurably improves
    retrieval on the vendors that support it, and a protocol that could not
    express it would quietly give up that gain.
    """

    DOCUMENT = "document"
    QUERY = "query"


class EmbeddingCapabilities(BaseModel):
    """What a vendor actually does, stated rather than discovered."""

    model_config = ConfigDict(frozen=True)

    asymmetric: bool = False
    max_batch: int = 96
    dimensions: int | None = None


class EmbeddingErrorCode(StrEnum):
    """Capability-owned failure categories, independent of vendor error names."""

    PROVIDER_ERROR = "provider_error"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    RATE_LIMITED = "rate_limited"
    TRANSPORT = "transport"
    INVALID_RESPONSE = "invalid_response"
    DIMENSION_MISMATCH = "dimension_mismatch"


class EmbeddingError(Exception):
    """An embedding call failed."""

    def __init__(
        self,
        message: str,
        *,
        vendor: str | None = None,
        code: EmbeddingErrorCode = EmbeddingErrorCode.PROVIDER_ERROR,
        retryable: bool = False,
    ) -> None:
        if not isinstance(code, EmbeddingErrorCode):
            raise TypeError("Embedding failure requires an EmbeddingErrorCode.")
        super().__init__(message)
        self.vendor = vendor
        self.code = code
        self.retryable = retryable


class EmbeddingConfig(BaseModel):
    """What a vendor needs to run.

    No defaults for `model`. Everything already stored was embedded with one,
    and a model that silently changed would make retrieval return nonsense
    rather than an error — the vectors would still compare, just meaninglessly.
    """

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    api_key: str = Field(min_length=1, repr=False)
    base_url: str | None = None


class EmbeddingSpace(BaseModel):
    """Execution provenance plus one verified vector coordinate space."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always"
    )

    organization_id: UUID
    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    provider: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    model: str = Field(min_length=1)
    dimensions: int = Field(gt=0)
    semantic_options: JsonObject = Field(default_factory=dict)

    @property
    def id(self) -> str:
        # Provider-config authority answers which executable revision produced
        # a vector. It does not answer whether two vectors are comparable.
        # Only tenant isolation plus coordinate-affecting semantics belong in
        # this hash; credentials and display metadata therefore cannot split a
        # compatible store.
        canonical = json.dumps(
            {
                "organization_id": str(self.organization_id),
                "provider": self.provider,
                "endpoint": self.endpoint,
                "model": self.model,
                "dimensions": self.dimensions,
                "semantic_options": self.semantic_options,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def to_active_record(self) -> EmbeddingRecord:
        """Project complete active identity to its explicitly named persistence fields."""
        space = type(self).model_validate(self, strict=True)
        return EmbeddingRecord(
            organization_id=space.organization_id,
            embedding_provider_config_id=space.provider_config_id,
            embedding_provider_config_revision=space.provider_config_revision,
            embedding_provider=space.provider,
            embedding_endpoint=space.endpoint,
            embedding_model=space.model,
            embedding_dimensions=space.dimensions,
            embedding_semantic_options=space.semantic_options,
            embedding_space_id=space.id,
        )

    def to_target_record(self) -> TargetEmbeddingRecord:
        """Project complete target identity to its explicitly named persistence fields."""
        space = type(self).model_validate(self, strict=True)
        return TargetEmbeddingRecord(
            organization_id=space.organization_id,
            target_embedding_provider_config_id=space.provider_config_id,
            target_embedding_provider_config_revision=space.provider_config_revision,
            target_embedding_provider=space.provider,
            target_embedding_endpoint=space.endpoint,
            target_embedding_model=space.model,
            target_embedding_dimensions=space.dimensions,
            target_embedding_semantic_options=space.semantic_options,
            target_embedding_space_id=space.id,
        )

    def to_source_record(self) -> SourceEmbeddingRecord:
        """Project complete source identity to its explicitly named persistence fields."""
        space = type(self).model_validate(self, strict=True)
        return SourceEmbeddingRecord(
            organization_id=space.organization_id,
            source_embedding_provider_config_id=space.provider_config_id,
            source_embedding_provider_config_revision=space.provider_config_revision,
            source_embedding_provider=space.provider,
            source_embedding_endpoint=space.endpoint,
            source_embedding_model=space.model,
            source_embedding_dimensions=space.dimensions,
            source_embedding_semantic_options=space.semantic_options,
            source_embedding_space_id=space.id,
        )

    def is_compatible_with(self, other: "EmbeddingSpace") -> bool:
        """Return whether vectors from both authorities may be compared."""
        return self.id == other.id


def embedding_space_from_record(record: object) -> EmbeddingSpace | None:
    """Rebuild and verify authority stamped on a durable vector owner/job."""
    record = EmbeddingRecord.model_validate(record)
    if record.embedding_provider_config_id is None:
        return None
    return _restore_embedding_space(
        organization_id=record.organization_id,
        provider_config_id=record.embedding_provider_config_id,
        provider_config_revision=record.embedding_provider_config_revision,
        provider=record.embedding_provider,
        endpoint=record.embedding_endpoint,
        model=record.embedding_model,
        dimensions=record.embedding_dimensions,
        semantic_options=record.embedding_semantic_options,
        space_id=record.embedding_space_id,
    )


def target_embedding_space_from_record(
    record: object,
) -> EmbeddingSpace | None:
    """Rebuild a staged target authority without changing the active space."""
    record = TargetEmbeddingRecord.model_validate(record)
    if record.target_embedding_provider_config_id is None:
        return None
    return _restore_embedding_space(
        organization_id=record.organization_id,
        provider_config_id=record.target_embedding_provider_config_id,
        provider_config_revision=record.target_embedding_provider_config_revision,
        provider=record.target_embedding_provider,
        endpoint=record.target_embedding_endpoint,
        model=record.target_embedding_model,
        dimensions=record.target_embedding_dimensions,
        semantic_options=record.target_embedding_semantic_options,
        space_id=record.target_embedding_space_id,
    )


def source_embedding_space_from_record(
    record: object,
) -> EmbeddingSpace | None:
    """Rebuild the immutable source authority stamped on transition work."""
    record = SourceEmbeddingRecord.model_validate(record)
    if record.source_embedding_provider_config_id is None:
        return None
    return _restore_embedding_space(
        organization_id=record.organization_id,
        provider_config_id=record.source_embedding_provider_config_id,
        provider_config_revision=record.source_embedding_provider_config_revision,
        provider=record.source_embedding_provider,
        endpoint=record.source_embedding_endpoint,
        model=record.source_embedding_model,
        dimensions=record.source_embedding_dimensions,
        semantic_options=record.source_embedding_semantic_options,
        space_id=record.source_embedding_space_id,
    )


def _restore_embedding_space(
    *,
    organization_id: UUID,
    provider_config_id: UUID,
    provider_config_revision: int | None,
    provider: str | None,
    endpoint: str | None,
    model: str | None,
    dimensions: int | None,
    semantic_options: Mapping[str, JsonValue] | None,
    space_id: str | None,
) -> EmbeddingSpace:
    """Nullable DB columns must form a complete space when a config is present."""
    space = EmbeddingSpace.model_validate(
        {
            "organization_id": organization_id,
            "provider_config_id": provider_config_id,
            "provider_config_revision": provider_config_revision,
            "provider": provider,
            "endpoint": endpoint,
            "model": model,
            "dimensions": dimensions,
            "semantic_options": semantic_options,
        },
        strict=True,
    )
    if space.id != space_id:
        raise ValueError("Persisted embedding authority has an invalid space ID.")
    return space
