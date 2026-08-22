"""Authenticated Documents audit routes for organization members."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from eylo.common.database import start_transaction
from eylo.modules.auth.schemas import CurrentUserSchema
from eylo.modules.auth.services.auth_service import get_current_user
from eylo.sor.knowledge.audit import KnowledgeDocumentAuditService
from eylo.sor.knowledge.schemas import (
    KnowledgeAuditAvailability,
    KnowledgeDocumentAttachmentResponse,
    KnowledgeDocumentAuditResponse,
    KnowledgeDocumentAuthorResponse,
    KnowledgeDocumentBlockResponse,
    KnowledgeDocumentPropertyResponse,
    KnowledgeDocumentSpaceResponse,
    KnowledgeDocumentVersionResponse,
)
from eylo.sor.runtime.adapters import SorAdapterUnavailableError
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.knowledge_media import (
    KnowledgeImageUnavailableError,
    read_knowledge_document_image,
)
from eylo.sor.shared.contracts import (
    SorExternalRecordNotFound,
    SorVendorOperationError,
)
from eylo.sor.shared.reads import SorReadNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/{organization_id}/sor/knowledge",
    tags=["systems-of-record"],
)


def _availability(
    *,
    entity: str,
    readable_entities: frozenset[str],
    selected_entities: frozenset[str],
) -> KnowledgeAuditAvailability:
    if entity not in readable_entities:
        return KnowledgeAuditAvailability.UNSUPPORTED
    if entity not in selected_entities:
        return KnowledgeAuditAvailability.NOT_SELECTED
    return KnowledgeAuditAvailability.AVAILABLE


@router.get(
    "/documents/{record_id}/audit",
    response_model=KnowledgeDocumentAuditResponse,
)
async def get_knowledge_document_audit(
    organization_id: UUID,
    record_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> KnowledgeDocumentAuditResponse:
    """Return bounded document content context without widening tenant scope."""
    if current_user.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        async with start_transaction(ro=True) as session:
            context = await KnowledgeDocumentAuditService(session).read(
                organization_id=organization_id,
                record_id=record_id,
            )
            manifest = get_sor_registry().get_manifest(
                profile=context.source.profile,
                vendor_key=context.source.vendor_key,
            )
            availability = {
                entity: _availability(
                    entity=entity,
                    readable_entities=manifest.readable_entities,
                    selected_entities=context.selected_entities,
                )
                for entity in (
                    "attachment",
                    "author",
                    "block",
                    "property",
                    "space",
                    "version",
                )
            }
            return KnowledgeDocumentAuditResponse(
                blocks_status=availability["block"],
                blocks_truncated=context.blocks_truncated,
                blocks=tuple(
                    KnowledgeDocumentBlockResponse.model_validate(block)
                    for block in context.blocks
                ),
                versions_status=availability["version"],
                versions_truncated=context.versions_truncated,
                versions=tuple(
                    KnowledgeDocumentVersionResponse.model_validate(version)
                    for version in context.versions
                ),
                properties_status=availability["property"],
                properties_truncated=context.properties_truncated,
                properties=tuple(
                    KnowledgeDocumentPropertyResponse.model_validate(property_value)
                    for property_value in context.properties
                ),
                attachments_status=availability["attachment"],
                attachments_truncated=context.attachments_truncated,
                attachments=tuple(
                    KnowledgeDocumentAttachmentResponse.model_validate(attachment)
                    for attachment in context.attachments
                ),
                space_status=availability["space"],
                space=(
                    KnowledgeDocumentSpaceResponse.model_validate(context.space)
                    if context.space is not None
                    else None
                ),
                author_status=availability["author"],
                author=(
                    KnowledgeDocumentAuthorResponse.model_validate(context.author)
                    if context.author is not None
                    else None
                ),
            )
    except (KeyError, SorReadNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None


@router.get(
    "/documents/{record_id}/attachments/{attachment_record_id}/content",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "content": {
                "image/avif": {},
                "image/gif": {},
                "image/jpeg": {},
                "image/png": {},
                "image/webp": {},
            },
            "description": "Current source image content.",
        },
        status.HTTP_404_NOT_FOUND: {"description": "Image not available."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Source temporarily unavailable."
        },
    },
)
async def get_knowledge_document_attachment_content(
    organization_id: UUID,
    record_id: UUID,
    attachment_record_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> Response:
    """Proxy one current, tenant-owned raster attachment without leaking auth."""
    if current_user.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        image = await read_knowledge_document_image(
            organization_id=organization_id,
            document_record_id=record_id,
            attachment_record_id=attachment_record_id,
        )
    except (
        KeyError,
        KnowledgeImageUnavailableError,
        SorExternalRecordNotFound,
        SorReadNotFoundError,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    except (SorAdapterUnavailableError, SorVendorOperationError) as error:
        logger.warning(
            "SOR document image source unavailable organization_id=%s "
            "document_record_id=%s attachment_record_id=%s error_type=%s",
            organization_id,
            record_id,
            attachment_record_id,
            type(error).__name__,
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from None
    return Response(
        content=image.content,
        media_type=image.media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["router"]
