"""Durable organization-scoped email delivery through one exact config."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from eylo.common.database import start_transaction
from eylo.common.http_egress import HttpEgressPolicyError
from eylo.common.outbound import (
    OutboundAttemptIdentity,
    OutboundAttemptSpec,
    OutboundOwnerKind,
    fingerprint_outbound_input,
)
from eylo.modules.email_configs.domain import EmailProviderConfig
from eylo.modules.email_configs.wiring import build_email_config_resolver
from eylo.pipelines.email.config import build_email_runtime_config
from eylo.pipelines.email.contracts import EmailDeliveryResult
from eylo.pipelines.outbound.durable_execution import (
    CommandStepContext,
    execute_outbound_attempt,
)
from eylo.sockets.email.exceptions import EmailConfigurationError
from eylo.sockets.email.factory import EmailFactory
from eylo.sockets.email.schemas import EmailMessage

if TYPE_CHECKING:
    from eylo.sockets.email.sendgrid import SendGridHttpTransport

T = TypeVar("T")


class EmailDeliveryUnsupported(ValueError):
    """The requested email cannot enter the provider boundary in V1."""


class _InlineDurableContext:
    """DB-fenced execution for callers already owned by another durable record."""

    async def step(
        self,
        *,
        key: str,
        version: int,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        del key, version
        return await operation()


async def require_organization_email(
    *,
    organization_id: UUID,
    provider_config_id: UUID | None,
    provider_config_revision: int | None = None,
) -> None:
    """Require one ready, explicitly granted email config without sending."""
    await _resolve_provider_config(
        organization_id=organization_id,
        provider_config_id=provider_config_id,
        provider_config_revision=provider_config_revision,
    )


async def send_organization_email(
    *,
    organization_id: UUID,
    owner_kind: OutboundOwnerKind,
    owner_id: UUID,
    provider_config_id: UUID,
    provider_config_revision: int,
    to_email: str,
    subject: str,
    text_body: str | None = None,
    html_body: str | None = None,
    durable_context: CommandStepContext | None = None,
    sendgrid_transport: SendGridHttpTransport | None = None,
) -> EmailDeliveryResult:
    """Deliver one logical email under a stable owner and exact config revision."""
    if provider_config_revision <= 0:
        raise ValueError("Email delivery requires a positive config revision.")
    provider_config = await _resolve_provider_config(
        organization_id=organization_id,
        provider_config_id=provider_config_id,
        provider_config_revision=provider_config_revision,
    )
    runtime_config = build_email_runtime_config(provider_config)
    message = EmailMessage(
        to=[to_email],
        subject=subject,
        text_content=text_body,
        html_content=html_body,
        from_email=runtime_config.default_from_email,
        from_name=runtime_config.default_from_name,
    )
    identity = OutboundAttemptIdentity(
        organization_id=organization_id,
        owner_kind=owner_kind,
        owner_id=owner_id,
        operation_key="email.send",
    )
    factory = EmailFactory(
        runtime_config,
        sendgrid_transport=sendgrid_transport,
    )
    try:
        try:
            plan = factory.get_adapter().plan_delivery(
                message,
                attempt_id=identity.attempt_id,
            )
        except (EmailConfigurationError, HttpEgressPolicyError):
            raise EmailDeliveryUnsupported(
                "Email delivery request is unsupported."
            ) from None
        spec = OutboundAttemptSpec(
            identity=identity,
            provider_operation=plan.provider_operation,
            transport_kind=plan.transport_kind,
            destination_origin=plan.destination_origin,
            request_fingerprint=fingerprint_outbound_input(
                {
                    "message": message.model_dump(mode="json"),
                    "provider_config_id": str(provider_config_id),
                    "provider_config_revision": provider_config_revision,
                    "vendor": runtime_config.vendor,
                }
            ),
        )
        receipt = await execute_outbound_attempt(
            spec=spec,
            context=durable_context or _InlineDurableContext(),
            sender=plan.send,
        )
        return EmailDeliveryResult.from_receipt(
            receipt,
            vendor=runtime_config.vendor,
        )
    finally:
        await factory.close()


async def _resolve_provider_config(
    *,
    organization_id: UUID,
    provider_config_id: UUID | None,
    provider_config_revision: int | None,
) -> EmailProviderConfig:
    async with start_transaction(ro=True):
        resolver = build_email_config_resolver()
        if provider_config_revision is None:
            resolved = await resolver.resolve(
                organization_id,
                provider_config_id=provider_config_id,
            )
        else:
            if provider_config_id is None:
                raise ValueError("Pinned email revision requires a config ID.")
            resolved = await resolver.resolve_pinned(
                organization_id,
                provider_config_id=provider_config_id,
                revision=provider_config_revision,
            )
    return resolved.as_provider_config()


__all__ = [
    "EmailDeliveryResult",
    "EmailDeliveryUnsupported",
    "require_organization_email",
    "send_organization_email",
]
