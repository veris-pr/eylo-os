"""Authenticate SOR webhook deliveries and persist deduplicated receipts."""

from __future__ import annotations

import logging
from uuid import UUID

from eylo.common.database import start_transaction
from eylo.sor.crm.vendors.hubspot import (
    parse_hubspot_app_webhook,
    verify_hubspot_app_webhook,
)
from eylo.sor.knowledge.vendors.notion import (
    notion_verification_token,
    parse_notion_app_webhook,
    verify_notion_app_webhook,
)
from eylo.sor.runtime.adapters import acquire_source_adapter
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.runtime.webhook_processing import spawn_sor_webhook_receipt
from eylo.sor.shared.services import SorConfigurationError
from eylo.sor.shared.webhook_services import (
    SOR_WEBHOOK_MAX_BODY_BYTES,
    SorWebhookService,
)
from eylo.sor.support.vendors.intercom import (
    parse_intercom_app_webhook,
    verify_intercom_app_webhook,
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
    request_uri: str,
    registry: SorRegistry | None = None,
) -> tuple[tuple[UUID, ...], int]:
    """Verify one connector-level delivery and fan it out to selected sources."""
    if len(body) > SOR_WEBHOOK_MAX_BODY_BYTES:
        raise SorConfigurationError("SOR webhook body is too large.")
    if (
        vendor_key == "notion"
        and (verification_token := notion_verification_token(body=body)) is not None
    ):
        async with start_transaction() as session:
            await SorWebhookService(
                session,
                registry=registry,
            ).record_notion_verification_token(
                endpoint_key=endpoint_key,
                verification_token=verification_token,
            )
        return (), 0
    async with start_transaction(ro=True) as session:
        authority = await SorWebhookService(
            session,
            registry=registry,
        ).resolve_app_endpoint(
            vendor_key=vendor_key,
            endpoint_key=endpoint_key,
        )
    if vendor_key == "linear":
        verify_linear_app_webhook(
            headers=headers,
            body=body,
            signing_secret=authority.signing_secret,
        )
        linear_delivery = parse_linear_app_webhook(headers=headers, body=body)
        organization_external_id = linear_delivery.organization_external_id
        signals = (linear_delivery.signal,)
    elif vendor_key == "hubspot":
        verify_hubspot_app_webhook(
            headers=headers,
            body=body,
            client_secret=authority.signing_secret,
            request_uri=request_uri,
        )
        hubspot_delivery = parse_hubspot_app_webhook(body=body)
        organization_external_id = hubspot_delivery.organization_external_id
        signals = hubspot_delivery.signals
    elif vendor_key == "intercom":
        verify_intercom_app_webhook(
            headers=headers,
            body=body,
            client_secret=authority.signing_secret,
        )
        intercom_delivery = parse_intercom_app_webhook(body=body)
        organization_external_id = intercom_delivery.organization_external_id
        signals = (intercom_delivery.signal,)
    elif vendor_key == "notion":
        verify_notion_app_webhook(
            headers=headers,
            body=body,
            verification_token=authority.signing_secret,
        )
        notion_delivery = parse_notion_app_webhook(body=body)
        organization_external_id = notion_delivery.organization_external_id
        signals = (notion_delivery.signal,)
    else:
        raise SorConfigurationError("This app webhook vendor is not supported.")
    if (
        authority.vendor_account_external_id is not None
        and organization_external_id != authority.vendor_account_external_id
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
            and current.vendor_account_external_id != organization_external_id
        ):
            raise SorConfigurationError(
                "Webhook workspace does not match the authorized connector."
            )
        await service.bind_app_webhook_account(
            endpoint_key=endpoint_key,
            organization_external_id=organization_external_id,
        )
        for source in current.sources:
            source_signals = tuple(
                signal
                for signal in signals
                if signal.vendor_object_key is None
                or signal.vendor_object_key in source.selected_objects
            )
            if not source_signals:
                continue
            receipt, created = await service.record_verified_delivery(
                source=source,
                body=body,
                signals=source_signals,
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
