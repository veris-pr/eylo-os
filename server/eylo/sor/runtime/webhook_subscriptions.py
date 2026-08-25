"""Manage vendor webhook subscriptions without holding DB transactions over I/O."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import or_, select

from eylo.common.config import settings
from eylo.common.database import start_transaction
from eylo.sor.runtime.adapters import (
    SorAdapterUnavailableError,
    acquire_source_adapter,
)
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.shared.contracts import (
    SorCapabilityUnavailable,
    SorChangeMode,
    SorSourceState,
    SorSourceTransition,
    SorVendorOperationError,
    SorWebhookSubscription,
    SorWebhookSubscriptionState,
)
from eylo.sor.shared.models import SorSourceModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import (
    SorConfigurationError,
    SorConflictError,
    SorNotFoundError,
    SorSourceService,
)
from eylo.sor.shared.webhook_services import (
    SOR_WEBHOOK_OPERATION_LEASE,
    SOR_WEBHOOK_RENEWAL_MARGIN,
    SorWebhookService,
    SorWebhookSubscriptionPlan,
)

logger = logging.getLogger(__name__)

_VENDOR_OPERATION_TIMEOUT_SECONDS = 30.0
_FAILED_RETRY_DELAY = timedelta(minutes=15)
_MAINTENANCE_LIMIT = 100


@dataclass(frozen=True, slots=True)
class SorWebhookMaintenanceResult:
    """Bounded scheduler outcome for operational diagnostics."""

    eligible: int
    activated: int
    failed: int
    configuration_unavailable: int = 0


def public_webhook_api_base_url() -> str:
    """Return a public HTTPS API base accepted by Atlassian callbacks."""
    value = settings.API_BASE_URL
    if not isinstance(value, str) or not value.strip():
        raise SorConfigurationError(
            "API_BASE_URL must be configured before managed webhooks are enabled."
        )
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        raise SorConfigurationError(
            "API_BASE_URL must be a public HTTPS API base for managed webhooks."
        )
    hostname = parsed.hostname.casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise SorConfigurationError(
            "API_BASE_URL must be publicly reachable for managed webhooks."
        )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise SorConfigurationError(
                "API_BASE_URL must be publicly reachable for managed webhooks."
            )
    return normalized


async def ensure_sor_webhook_subscription(
    *,
    organization_id: UUID,
    source_id: UUID,
) -> SorWebhookSubscription | None:
    """Register or renew one due subscription through a three-phase boundary."""
    await _require_managed_source(
        organization_id=organization_id,
        source_id=source_id,
    )
    api_base_url = public_webhook_api_base_url()
    endpoint_token = _managed_endpoint_token(
        organization_id=organization_id,
        source_id=source_id,
    )
    async with start_transaction() as session:
        plan = await SorWebhookService(session).prepare_subscription(
            organization_id=organization_id,
            source_id=source_id,
            endpoint_token=endpoint_token,
        )
    if plan is None:
        return await _current_subscription(
            organization_id=organization_id,
            source_id=source_id,
        )

    try:
        subscription = await _execute_subscription_plan(
            organization_id=organization_id,
            source_id=source_id,
            api_base_url=api_base_url,
            plan=plan,
        )
    except SorCapabilityUnavailable:
        async with start_transaction() as session:
            await SorWebhookService(session).complete_not_applicable(
                organization_id=organization_id,
                source_id=source_id,
                plan=plan,
            )
        return None
    except Exception as error:
        await _record_subscription_failure(
            organization_id=organization_id,
            source_id=source_id,
            plan=plan,
            error=error,
        )
        raise

    async with start_transaction() as session:
        await SorWebhookService(session).complete_subscription(
            organization_id=organization_id,
            source_id=source_id,
            plan=plan,
            subscription=subscription,
        )
    return subscription


async def remove_sor_webhook_subscription(
    *,
    organization_id: UUID,
    source_id: UUID,
) -> None:
    """Remove vendor delivery first, then revoke local ingress authority."""
    await _require_managed_source(
        organization_id=organization_id,
        source_id=source_id,
    )
    async with start_transaction() as session:
        plan = await SorWebhookService(session).prepare_removal(
            organization_id=organization_id,
            source_id=source_id,
        )
    if plan is None:
        return
    if plan.current is None:
        raise SorConfigurationError("Webhook removal has no vendor subscription.")

    try:
        async with asyncio.timeout(_VENDOR_OPERATION_TIMEOUT_SECONDS):
            async with acquire_source_adapter(
                organization_id=organization_id,
                source_id=source_id,
                invocation_budget_seconds=_VENDOR_OPERATION_TIMEOUT_SECONDS,
            ) as adapter:
                await adapter.remove_webhook(plan.current)
    except Exception as error:
        await _record_subscription_failure(
            organization_id=organization_id,
            source_id=source_id,
            plan=plan,
            error=error,
        )
        raise

    async with start_transaction() as session:
        await SorWebhookService(session).complete_removal(
            organization_id=organization_id,
            source_id=source_id,
            plan=plan,
        )


async def maintain_sor_webhook_subscriptions() -> SorWebhookMaintenanceResult:
    """Register missing and renew expiring managed webhooks in bounded batches."""
    try:
        public_webhook_api_base_url()
    except SorConfigurationError:
        return SorWebhookMaintenanceResult(
            eligible=0,
            activated=0,
            failed=0,
            configuration_unavailable=1,
        )

    now = datetime.now(timezone.utc)
    source_ids = await _due_source_ids(now=now)
    activated = 0
    failed = 0
    for organization_id, source_id in source_ids:
        try:
            await ensure_sor_webhook_subscription(
                organization_id=organization_id,
                source_id=source_id,
            )
            activated += 1
        except SorConflictError:
            continue
        except Exception as error:  # noqa: BLE001 - sources recover independently
            failed += 1
            logger.error(
                "SOR webhook subscription maintenance failed "
                "organization_id=%s source_id=%s error_type=%s",
                organization_id,
                source_id,
                type(error).__name__,
            )
    return SorWebhookMaintenanceResult(
        eligible=len(source_ids),
        activated=activated,
        failed=failed,
    )


async def _execute_subscription_plan(
    *,
    organization_id: UUID,
    source_id: UUID,
    api_base_url: str,
    plan: SorWebhookSubscriptionPlan,
) -> SorWebhookSubscription:
    if plan.endpoint_token is None:
        raise SorConfigurationError(
            "Webhook subscription operation has no callback authority."
        )
    callback_url = (
        f"{api_base_url}/sor/webhooks/{plan.vendor_key}/"
        f"{plan.endpoint_token}"
    )
    async with asyncio.timeout(_VENDOR_OPERATION_TIMEOUT_SECONDS):
        async with acquire_source_adapter(
            organization_id=organization_id,
            source_id=source_id,
            invocation_budget_seconds=_VENDOR_OPERATION_TIMEOUT_SECONDS,
        ) as adapter:
            if plan.operation is SorWebhookSubscriptionState.REGISTERING:
                return await adapter.subscribe_webhook(callback_url)
            if plan.operation is SorWebhookSubscriptionState.RENEWING:
                if plan.current is None:
                    raise SorConfigurationError(
                        "Webhook renewal has no current subscription."
                    )
                recovered = await adapter.subscribe_webhook(callback_url)
                if recovered.external_id != plan.current.external_id:
                    await adapter.remove_webhook(plan.current)
                return await adapter.renew_webhook(recovered)
    raise SorConfigurationError("Unsupported webhook subscription operation.")


async def _current_subscription(
    *,
    organization_id: UUID,
    source_id: UUID,
) -> SorWebhookSubscription | None:
    async with start_transaction(ro=True) as session:
        source = await SorRepository(session).get_source(
            organization_id=organization_id,
            source_id=source_id,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        if source.webhook_subscription_id is None:
            return None
        return SorWebhookSubscription(
            external_id=source.webhook_subscription_id,
            expires_at=source.webhook_subscription_expires_at,
        )


async def _require_managed_source(
    *,
    organization_id: UUID,
    source_id: UUID,
) -> None:
    """Fail on unsupported adapters before validating deployment callback config."""
    async with start_transaction(ro=True) as session:
        source = await SorRepository(session).get_source(
            organization_id=organization_id,
            source_id=source_id,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        try:
            manifest = get_sor_registry().get_manifest(
                profile=source.profile,
                vendor_key=source.vendor_key,
            )
        except KeyError as error:
            raise SorConfigurationError(
                "Source adapter is unavailable in this deployment."
            ) from error
        if manifest.change_mode is not SorChangeMode.MANAGED_WEBHOOK:
            raise SorConfigurationError(
                "Source adapter does not manage vendor webhook subscriptions."
            )


async def _record_subscription_failure(
    *,
    organization_id: UUID,
    source_id: UUID,
    plan: SorWebhookSubscriptionPlan,
    error: Exception,
) -> None:
    requires_reauthorization = (
        isinstance(error, SorAdapterUnavailableError)
        and error.requires_reauthorization
    ) or (
        isinstance(error, SorVendorOperationError)
        and error.requires_reauthorization
    )
    try:
        async with start_transaction() as session:
            await SorWebhookService(session).fail_subscription(
                organization_id=organization_id,
                source_id=source_id,
                plan=plan,
            )
            if requires_reauthorization:
                source = await SorRepository(session).get_source(
                    organization_id=organization_id,
                    source_id=source_id,
                    for_update=True,
                )
                if source is not None and source.state in {
                    SorSourceState.ACTIVE,
                    SorSourceState.DEGRADED,
                }:
                    await SorSourceService(session).transition(
                        organization_id=organization_id,
                        source_id=source_id,
                        transition=SorSourceTransition.REAUTHORIZATION_REQUIRED,
                        error_code="WEBHOOK_AUTHORIZATION_REQUIRED",
                        error_summary=(
                            "The source must be reauthorized before webhook "
                            "delivery can be enabled."
                        ),
                    )
    except Exception as record_error:  # noqa: BLE001 - preserve original vendor error
        logger.error(
            "SOR webhook failure could not be recorded "
            "organization_id=%s source_id=%s error_type=%s",
            organization_id,
            source_id,
            type(record_error).__name__,
        )


async def _due_source_ids(*, now: datetime) -> tuple[tuple[UUID, UUID], ...]:
    renewal_cutoff = now + SOR_WEBHOOK_RENEWAL_MARGIN
    retry_cutoff = now - _FAILED_RETRY_DELAY
    stale_cutoff = now - SOR_WEBHOOK_OPERATION_LEASE
    retryable_failures = (
        SorWebhookSubscriptionState.REGISTRATION_FAILED.value,
        SorWebhookSubscriptionState.RENEWAL_FAILED.value,
    )
    active_operations = (
        SorWebhookSubscriptionState.REGISTERING.value,
        SorWebhookSubscriptionState.RENEWING.value,
    )
    async with start_transaction(ro=True) as session:
        rows = (
            await session.execute(
                select(
                    SorSourceModel.organization_id,
                    SorSourceModel.id,
                    SorSourceModel.profile,
                    SorSourceModel.vendor_key,
                )
                .where(
                    SorSourceModel.state.in_(
                        (SorSourceState.ACTIVE, SorSourceState.DEGRADED)
                    ),
                    SorSourceModel.deleted.is_(False),
                    or_(
                        SorSourceModel.webhook_subscription_status.is_(None),
                        (
                            SorSourceModel.webhook_subscription_status.in_(
                                retryable_failures
                            )
                            & (SorSourceModel.updated_at <= retry_cutoff)
                        ),
                        (
                            SorSourceModel.webhook_subscription_status.in_(
                                active_operations
                            )
                            & (SorSourceModel.updated_at <= stale_cutoff)
                        ),
                        (
                            SorSourceModel.webhook_subscription_status
                            == SorWebhookSubscriptionState.ACTIVE.value
                        )
                        & SorSourceModel.webhook_subscription_expires_at.is_not(None)
                        & (
                            SorSourceModel.webhook_subscription_expires_at
                            <= renewal_cutoff
                        ),
                    ),
                )
                .order_by(SorSourceModel.updated_at.asc(), SorSourceModel.id.asc())
                .limit(_MAINTENANCE_LIMIT)
            )
        ).all()

    registry = get_sor_registry()
    eligible: list[tuple[UUID, UUID]] = []
    for organization_id, source_id, profile, vendor_key in rows:
        try:
            manifest = registry.get_manifest(profile=profile, vendor_key=vendor_key)
        except KeyError:
            continue
        if manifest.change_mode is SorChangeMode.MANAGED_WEBHOOK:
            eligible.append((organization_id, source_id))
    return tuple(eligible)


def _managed_endpoint_token(*, organization_id: UUID, source_id: UUID) -> str:
    """Derive stable opaque callback authority for crash-safe registration."""
    payload = (
        f"eylo.sor.managed-webhook.v1:{organization_id}:{source_id}"
    ).encode("ascii")
    digest = hmac.new(
        settings.AUTH_SECRET_KEY.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


__all__ = [
    "SorWebhookMaintenanceResult",
    "ensure_sor_webhook_subscription",
    "maintain_sor_webhook_subscriptions",
    "public_webhook_api_base_url",
    "remove_sor_webhook_subscription",
]
