"""Authenticate SOR webhook deliveries and persist deduplicated receipts."""

from __future__ import annotations

import logging
from uuid import UUID

from eylo.common.database import start_transaction
from eylo.sor.runtime.adapters import acquire_source_adapter
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.runtime.webhook_processing import spawn_sor_webhook_receipt
from eylo.sor.shared.services import SorConfigurationError
from eylo.sor.shared.webhook_services import (
    SOR_WEBHOOK_MAX_BODY_BYTES,
    SorWebhookService,
)
from eylo.sor.ticketing.vendors.linear import (
    parse_linear_app_webhook,
    verify_linear_app_webhook,
)

logger = logging.getLogger(__name__)


async def accept_sor_webhook(
    *,
    vendor_key: str,
    endpoint_token: str,
    headers: dict[str, str],
    body: bytes,
    registry: SorRegistry | None = None,
) -> tuple[UUID, bool]:
    """Verify raw bytes, commit one receipt, then best-effort spawn processing."""
    if len(body) > SOR_WEBHOOK_MAX_BODY_BYTES:
        raise SorConfigurationError("SOR webhook body is too large.")
    async with start_transaction(ro=True) as session:
        source = await SorWebhookService(session, registry=registry).resolve_endpoint(
            vendor_key=vendor_key,
            endpoint_token=endpoint_token,
        )
        organization_id = source.organization_id
        source_id = source.id

    async with acquire_source_adapter(
        organization_id=organization_id,
        source_id=source_id,
        registry=registry,
        invocation_budget_seconds=15.0,
    ) as adapter:
        await adapter.verify_webhook(headers=headers, body=body)
        signals = await adapter.parse_webhook_signal(headers=headers, body=body)

    async with start_transaction() as session:
        service = SorWebhookService(session, registry=registry)
        current = await service.resolve_endpoint(
            vendor_key=vendor_key,
            endpoint_token=endpoint_token,
        )
        receipt, created = await service.record_verified_delivery(
            source=current,
            body=body,
            signals=signals,
        )
        receipt_id = receipt.id
    if created:
        try:
            await spawn_sor_webhook_receipt(
                organization_id=organization_id,
                receipt_id=receipt_id,
            )
        except Exception as error:  # noqa: BLE001 - DB outbox recovery owns retry
            logger.error(
                "SOR webhook receipt committed; spawn recovery remains pending "
                "receipt_id=%s error_type=%s",
                receipt_id,
                type(error).__name__,
            )
    return receipt_id, created


async def accept_sor_app_webhook(
    *,
    vendor_key: str,
    endpoint_key: UUID,
    headers: dict[str, str],
    body: bytes,
    registry: SorRegistry | None = None,
) -> tuple[tuple[UUID, ...], int]:
    """Verify one connector-level delivery and fan it out to selected sources."""
    if len(body) > SOR_WEBHOOK_MAX_BODY_BYTES:
        raise SorConfigurationError("SOR webhook body is too large.")
    if vendor_key != "linear":
        raise SorConfigurationError("This app webhook vendor is not supported.")
    async with start_transaction(ro=True) as session:
        authority = await SorWebhookService(
            session,
            registry=registry,
        ).resolve_app_endpoint(
            vendor_key=vendor_key,
            endpoint_key=endpoint_key,
        )
    verify_linear_app_webhook(
        headers=headers,
        body=body,
        signing_secret=authority.signing_secret,
    )
    delivery = parse_linear_app_webhook(headers=headers, body=body)
    if (
        authority.vendor_account_external_id is not None
        and delivery.organization_external_id
        != authority.vendor_account_external_id
    ):
        raise SorConfigurationError(
            "Webhook workspace does not match the authorized connector."
        )

    committed: list[tuple[UUID, UUID, bool]] = []
    async with start_transaction() as session:
        service = SorWebhookService(session, registry=registry)
        current = await service.resolve_app_endpoint(
            vendor_key=vendor_key,
            endpoint_key=endpoint_key,
            expected_secret_revision=authority.signing_secret_revision,
        )
        if (
            current.vendor_account_external_id is not None
            and current.vendor_account_external_id
            != delivery.organization_external_id
        ):
            raise SorConfigurationError(
                "Webhook workspace does not match the authorized connector."
            )
        await service.bind_app_webhook_account(
            endpoint_key=endpoint_key,
            organization_external_id=delivery.organization_external_id,
        )
        for source in current.sources:
            stream_key = delivery.signal.vendor_object_key
            if stream_key is not None and stream_key not in source.selected_objects:
                continue
            receipt, created = await service.record_verified_delivery(
                source=source,
                body=body,
                signals=(delivery.signal,),
            )
            committed.append((source.organization_id, receipt.id, created))

    for organization_id, receipt_id, created in committed:
        if not created:
            continue
        try:
            await spawn_sor_webhook_receipt(
                organization_id=organization_id,
                receipt_id=receipt_id,
            )
        except Exception as error:  # noqa: BLE001 - DB outbox recovery owns retry
            logger.error(
                "SOR app webhook receipt committed; spawn recovery remains pending "
                "receipt_id=%s error_type=%s",
                receipt_id,
                type(error).__name__,
            )
    receipt_ids = tuple(receipt_id for _org, receipt_id, _created in committed)
    duplicate_count = sum(1 for _org, _receipt, created in committed if not created)
    return receipt_ids, duplicate_count


__all__ = ["accept_sor_app_webhook", "accept_sor_webhook"]
