"""Shared pipeline for the Postgres-backed knowledgebase vendors.

pgvector and full-text search differ in how they *retrieve*, not in how they
receive a document — both take text, split it, and store rows against a scope.
That shared work lives here.

**Inside `vendors/`, deliberately, not in the socket.** What pgvector and a
hosted RAG vendor have in common is the protocol; what pgvector and FTS have in
common is a database. Putting this in the ABC would push a chunking strategy
onto vendors that own their own.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from sqlalchemy import text as sql
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sockets.knowledgebase.chunking import ChunkingStrategy
from eylo.sockets.knowledgebase.schemas import (
    KnowledgeDocument,
    KnowledgeResult,
    KnowledgeScope,
    KnowledgebaseError,
)

type KnowledgeSessionFactory = Callable[[], AsyncSession]

_METADATA = TypeAdapter(dict[str, JsonValue])


class PostgresKnowledgebaseAuthority(BaseModel):
    """The exact tenant partition one Postgres adapter may access."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    knowledgebase_id: UUID
    scope: KnowledgeScope
    scope_id: str = Field(min_length=1, max_length=64)

    def accepts_document(self, document: KnowledgeDocument) -> bool:
        return document.scope is self.scope and document.scope_id == self.scope_id

    def is_requested(self, scopes: dict[KnowledgeScope, str]) -> bool:
        return scopes.get(self.scope) == self.scope_id

    async def lock_live(self, session: AsyncSession) -> None:
        """Hold deletion behind an in-flight replacement transaction."""
        live = await session.scalar(
            sql(
                """
                SELECT id
                FROM knowledgebases
                WHERE id = :knowledgebase_id
                  AND organization_id = :organization_id
                  AND deleted IS FALSE
                FOR SHARE
                """
            ),
            self.parameters,
        )
        if live is None:
            raise KnowledgebaseError("Knowledgebase is no longer available.")

    @property
    def parameters(self) -> dict[str, object]:
        authority = type(self).model_validate(self)
        return {
            "organization_id": authority.organization_id,
            "knowledgebase_id": authority.knowledgebase_id,
            "scope": authority.scope.value,
            "scope_id": authority.scope_id,
        }


class PostgresKnowledgeRecord(BaseModel):
    """Validate consumed SQL columns before they become retrieval results."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        from_attributes=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    document_id: UUID
    content: str = Field(repr=False)
    scope: KnowledgeScope
    scope_id: str = Field(min_length=1, max_length=64)
    title: str | None
    source_uri: str | None
    meta: dict[str, JsonValue] | None = Field(repr=False)

    @field_validator("scope", mode="before")
    @classmethod
    def _scope(cls, value: object) -> KnowledgeScope:
        if not isinstance(value, str):
            raise ValueError("Stored knowledge scope must be a string.")
        return KnowledgeScope(value)

    def to_result(self, *, score: float) -> KnowledgeResult:
        return KnowledgeResult(
            document_id=str(self.document_id),
            content=self.content,
            score=score,
            scope=self.scope,
            scope_id=self.scope_id,
            title=self.title,
            source_uri=self.source_uri,
            metadata=self.meta if self.meta is not None else {},
        )


class PostgresKeywordResult(PostgresKnowledgeRecord):
    score: FiniteFloat

    @classmethod
    def from_row(cls, row: object) -> KnowledgeResult:
        try:
            record = cls.model_validate(row)
        except ValidationError:
            raise KnowledgebaseError(
                "Stored keyword search result is invalid."
            ) from None
        return record.to_result(score=record.score)


class PostgresVectorResult(PostgresKnowledgeRecord):
    distance: FiniteFloat

    @classmethod
    def from_row(cls, row: object) -> KnowledgeResult:
        try:
            record = cls.model_validate(row)
        except ValidationError:
            raise KnowledgebaseError(
                "Stored vector search result is invalid."
            ) from None
        return record.to_result(score=1.0 - record.distance)


def deletion_changed_rows(result: object) -> bool:
    """Unknown DML counts are failures, never a successful deletion receipt."""
    if not isinstance(result, CursorResult) or result.rowcount < 0:
        raise KnowledgebaseError("Knowledgebase deletion count is unavailable.")
    return result.rowcount > 0


def metadata_json(value: object) -> str:
    """Reject non-JSON material before opening the replacement transaction."""
    try:
        metadata = _METADATA.validate_python(value, strict=True)
        return json.dumps(metadata, allow_nan=False)
    except (ValidationError, ValueError):
        raise KnowledgebaseError("Knowledge document metadata is invalid.") from None


def validated_document(document: KnowledgeDocument) -> KnowledgeDocument:
    """Take a private validated snapshot before chunking, embedding or DB work."""
    try:
        return KnowledgeDocument.model_validate(document)
    except ValidationError:
        raise KnowledgebaseError("Knowledge document is invalid.") from None


def chunk(text: str, strategy: ChunkingStrategy | None = None) -> list[str]:
    """Split a document using the knowledgebase's chosen strategy.

    Kept as a function so existing callers do not change, but the behaviour is
    now a choice: `strategy` is a `ChunkingStrategy` built from the
    knowledgebase's config. Passing None gives paragraph packing, which is what
    this always did.

    See `sockets/knowledgebase/chunking/` for why there are three strategies
    and why they live beside the Postgres vendors rather than in the ABC.
    """
    from eylo.sockets.knowledgebase.chunking import build_chunker

    return (strategy or build_chunker()).chunk(text)
