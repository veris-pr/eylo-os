"""Orchestrate current source-image reads outside DB transactions."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eylo.common.database import start_transaction
from eylo.sor.knowledge.contracts import KnowledgeAttachmentReader
from eylo.sor.knowledge.media import read_attachment_authority
from eylo.sor.runtime.adapters import acquire_source_adapter

MAX_SOURCE_IMAGE_BYTES = 8_388_608


class KnowledgeImageUnavailableError(Exception):
    """The attachment cannot be exposed as a safe raster image."""


class KnowledgeDocumentImage(BaseModel):
    """Validated current image bytes ready for an authenticated response."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    content: bytes = Field(repr=False, exclude=True)
    media_type: str


async def read_knowledge_document_image(
    *,
    organization_id: UUID,
    document_record_id: UUID,
    attachment_record_id: UUID,
) -> KnowledgeDocumentImage:
    """Authorize in a short DB read, then perform vendor I/O after it closes."""
    async with start_transaction(ro=True) as session:
        authority = await read_attachment_authority(
            session,
            organization_id=organization_id,
            document_record_id=document_record_id,
            attachment_record_id=attachment_record_id,
        )
    if (
        authority.declared_size_bytes is not None
        and authority.declared_size_bytes > MAX_SOURCE_IMAGE_BYTES
    ):
        raise KnowledgeImageUnavailableError("The source image is too large.")
    _require_supported_declared_media_type(authority.declared_media_type)

    async with acquire_source_adapter(
        organization_id=organization_id,
        source_id=authority.source_id,
        invocation_budget_seconds=30.0,
    ) as adapter:
        if not isinstance(adapter, KnowledgeAttachmentReader):
            raise KnowledgeImageUnavailableError(
                "The source does not support attachment content reads."
            )
        result = await adapter.read_attachment_content(
            document_external_id=authority.document_external_id,
            attachment_external_id=authority.attachment_external_id,
            maximum_bytes=MAX_SOURCE_IMAGE_BYTES,
        )
    media_type = _raster_media_type(result.content)
    _require_compatible_media_type(
        actual=media_type,
        declared=authority.declared_media_type,
    )
    _require_compatible_media_type(actual=media_type, declared=result.media_type)
    return KnowledgeDocumentImage(content=result.content, media_type=media_type)


def _raster_media_type(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if (
        len(content) >= 12
        and content[4:8] == b"ftyp"
        and content[8:12] in {b"avif", b"avis"}
    ):
        return "image/avif"
    raise KnowledgeImageUnavailableError(
        "The source attachment is not a supported raster image."
    )


def _require_compatible_media_type(*, actual: str, declared: str | None) -> None:
    if declared is None:
        return
    normalized = declared.split(";", 1)[0].strip().casefold()
    aliases = {
        "image/jpg": "image/jpeg",
        "image/pjpeg": "image/jpeg",
        "application/octet-stream": actual,
    }
    if aliases.get(normalized, normalized) != actual:
        raise KnowledgeImageUnavailableError(
            "The source image type does not match its content."
        )


def _require_supported_declared_media_type(declared: str | None) -> None:
    if declared is None:
        return
    normalized = declared.split(";", 1)[0].strip().casefold()
    supported = {
        "application/octet-stream",
        "image/avif",
        "image/gif",
        "image/jpeg",
        "image/jpg",
        "image/pjpeg",
        "image/png",
        "image/webp",
    }
    if normalized not in supported:
        raise KnowledgeImageUnavailableError(
            "The source attachment is not a supported raster image."
        )


__all__ = [
    "KnowledgeDocumentImage",
    "KnowledgeImageUnavailableError",
    "MAX_SOURCE_IMAGE_BYTES",
    "read_knowledge_document_image",
]
