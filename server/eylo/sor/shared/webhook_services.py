"""Public webhook identity, deduplication, and transient-body retention policy."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.registry import SorRegistry

from .contracts import (
    SorChangeMode,
    SorSourceState,
    SorWebhookReceiptState,
    SorWebhookSignal,
    SorWebhookSubscription,
    SorWebhookSubscriptionState,
)
from .models import SorSourceModel, SorWebhookReceiptModel
from .repositories import SorRepository
from .secrets import encrypt_bytes, encrypt_source_webhook_signing_secret
from .services import SorConfigurationError, SorConflictError, SorNotFoundError

SOR_WEBHOOK_MAX_BODY_BYTES = 1_048_576
SOR_WEBHOOK_RAW_RETENTION_HOURS = 24
SOR_WEBHOOK_OPERATION_LEASE = timedelta(minutes=5)
SOR_WEBHOOK_RENEWAL_MARGIN = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class SorWebhookSubscriptionPlan:
    """One claimed vendor operation whose network I/O must run after commit."""

    operation: SorWebhookSubscriptionState
    vendor_key: str
    expected_config_revision: int
    current: SorWebhookSubscription | None = None
    endpoint_token: str | None = None


class SorWebhookService:
    """Resolve opaque endpoints and persist one receipt per verified delivery."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: SorRegistry | None = None,
    ) -> None:
        self.session = session
        self.repository = SorRepository(session)
        self.registry = registry or get_sor_registry()

    async def issue_endpoint_token(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
    ) -> str:
        """Rotate the public endpoint secret and return its plaintext exactly once."""
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        if manifest.change_mode is SorChangeMode.MANAGED_WEBHOOK:
            raise SorConfigurationError(
                "Managed webhook endpoints are owned by the subscription lifecycle."
            )
        if not manifest.change_mode.accepts_webhooks:
            raise SorConfigurationError("Source adapter does not support webhooks.")
        token = secrets.token_urlsafe(32)
        source.webhook_endpoint_token_hash = _sha256_bytes(token.encode("utf-8"))
        source.config_revision += 1
        await self.session.flush()
        return token

    async def prepare_subscription(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        endpoint_token: str,
        now: datetime | None = None,
    ) -> SorWebhookSubscriptionPlan | None:
        """Claim a due managed-subscription operation without vendor I/O."""
        claimed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if not 32 <= len(endpoint_token) <= 256:
            raise SorConfigurationError("Managed webhook endpoint token is invalid.")
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        if manifest.change_mode is not SorChangeMode.MANAGED_WEBHOOK:
            raise SorConfigurationError(
                "Source adapter does not manage vendor webhook subscriptions."
            )
        if source.state not in {SorSourceState.ACTIVE, SorSourceState.DEGRADED}:
            raise SorConfigurationError(
                "Source must be active before a webhook subscription is managed."
            )

        status = _subscription_state(source.webhook_subscription_status)
        operation_is_live = status in {
            SorWebhookSubscriptionState.REGISTERING,
            SorWebhookSubscriptionState.RENEWING,
            SorWebhookSubscriptionState.REMOVING,
        }
        if operation_is_live and source.updated_at > claimed_at - SOR_WEBHOOK_OPERATION_LEASE:
            raise SorConflictError("A webhook subscription operation is in progress.")

        token_hash = _sha256_bytes(endpoint_token.encode("utf-8"))
        endpoint_changed = source.webhook_endpoint_token_hash != token_hash

        if source.webhook_subscription_id is not None:
            expires_at = source.webhook_subscription_expires_at
            if (
                status is SorWebhookSubscriptionState.ACTIVE
                and not endpoint_changed
                and (
                    expires_at is None
                    or expires_at > claimed_at + SOR_WEBHOOK_RENEWAL_MARGIN
                )
            ):
                return None
            if endpoint_changed:
                source.webhook_endpoint_token_hash = token_hash
                source.config_revision += 1
            source.webhook_subscription_status = (
                SorWebhookSubscriptionState.RENEWING.value
            )
            source.updated_at = claimed_at
            await self.session.flush()
            return SorWebhookSubscriptionPlan(
                operation=SorWebhookSubscriptionState.RENEWING,
                vendor_key=source.vendor_key,
                expected_config_revision=source.config_revision,
                current=SorWebhookSubscription(
                    external_id=source.webhook_subscription_id,
                    expires_at=expires_at,
                ),
                endpoint_token=endpoint_token,
            )

        if endpoint_changed:
            source.webhook_endpoint_token_hash = token_hash
            source.config_revision += 1
        source.webhook_subscription_status = (
            SorWebhookSubscriptionState.REGISTERING.value
        )
        source.webhook_subscription_expires_at = None
        # Reclaiming a stale REGISTERING operation must refresh the lease even
        # though its enum state is unchanged.
        source.updated_at = claimed_at
        await self.session.flush()
        return SorWebhookSubscriptionPlan(
            operation=SorWebhookSubscriptionState.REGISTERING,
            vendor_key=source.vendor_key,
            expected_config_revision=source.config_revision,
            endpoint_token=endpoint_token,
        )

    async def complete_subscription(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        plan: SorWebhookSubscriptionPlan,
        subscription: SorWebhookSubscription,
    ) -> SorSourceModel:
        """Commit the exact vendor subscription returned by a claimed operation."""
        if not 1 <= len(subscription.external_id) <= 512:
            raise SorConfigurationError("Vendor webhook subscription ID is invalid.")
        expires_at = subscription.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None or expires_at.utcoffset() is None:
                raise SorConfigurationError(
                    "Vendor webhook subscription expiry must include a timezone."
                )
            expires_at = expires_at.astimezone(timezone.utc)

        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        self._require_claim(source=source, plan=plan)
        source.webhook_subscription_id = subscription.external_id
        source.webhook_subscription_status = SorWebhookSubscriptionState.ACTIVE.value
        source.webhook_subscription_expires_at = expires_at
        await self.session.flush()
        return source

    async def complete_not_applicable(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        plan: SorWebhookSubscriptionPlan,
    ) -> SorSourceModel:
        """Record that selected objects have no vendor webhook event surface."""
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        self._require_claim(source=source, plan=plan)
        source.webhook_endpoint_token_hash = None
        source.webhook_subscription_id = None
        source.webhook_subscription_status = (
            SorWebhookSubscriptionState.NOT_APPLICABLE.value
        )
        source.webhook_subscription_expires_at = None
        await self.session.flush()
        return source

    async def fail_subscription(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        plan: SorWebhookSubscriptionPlan,
    ) -> None:
        """Release a matching claim so scheduled or manual recovery can retry."""
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            return
        if (
            source.config_revision == plan.expected_config_revision
            and _subscription_state(source.webhook_subscription_status)
            is plan.operation
        ):
            failure_state = {
                SorWebhookSubscriptionState.REGISTERING: (
                    SorWebhookSubscriptionState.REGISTRATION_FAILED
                ),
                SorWebhookSubscriptionState.RENEWING: (
                    SorWebhookSubscriptionState.RENEWAL_FAILED
                ),
                SorWebhookSubscriptionState.REMOVING: (
                    SorWebhookSubscriptionState.REMOVAL_FAILED
                ),
            }.get(plan.operation)
            if failure_state is None:
                raise SorConfigurationError(
                    "Webhook subscription operation cannot fail."
                )
            source.webhook_subscription_status = failure_state.value
            await self.session.flush()

    async def prepare_removal(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
    ) -> SorWebhookSubscriptionPlan | None:
        """Claim removal while retaining vendor identity until it succeeds."""
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        subscription_id = source.webhook_subscription_id
        if subscription_id is None:
            source.webhook_endpoint_token_hash = None
            source.webhook_subscription_status = None
            source.webhook_subscription_expires_at = None
            await self.session.flush()
            return None
        source.webhook_subscription_status = SorWebhookSubscriptionState.REMOVING.value
        await self.session.flush()
        return SorWebhookSubscriptionPlan(
            operation=SorWebhookSubscriptionState.REMOVING,
            vendor_key=source.vendor_key,
            expected_config_revision=source.config_revision,
            current=SorWebhookSubscription(
                external_id=subscription_id,
                expires_at=source.webhook_subscription_expires_at,
            ),
        )

    async def complete_removal(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        plan: SorWebhookSubscriptionPlan,
    ) -> SorSourceModel:
        """Remove local ingress authority only after vendor removal succeeds."""
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        self._require_claim(source=source, plan=plan)
        source.webhook_endpoint_token_hash = None
        source.webhook_subscription_id = None
        source.webhook_subscription_status = None
        source.webhook_subscription_expires_at = None
        source.config_revision += 1
        await self.session.flush()
        return source

    @staticmethod
    def _require_claim(
        *,
        source: SorSourceModel,
        plan: SorWebhookSubscriptionPlan,
    ) -> None:
        if (
            source.config_revision != plan.expected_config_revision
            or _subscription_state(source.webhook_subscription_status)
            is not plan.operation
        ):
            raise SorConflictError(
                "Webhook subscription authority changed during vendor I/O."
            )

    async def set_signing_secret(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        signing_secret: str,
        expected_config_revision: int,
    ) -> SorSourceModel:
        """Rotate a tenant-bound signing secret under optimistic config authority."""
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        if source.config_revision != expected_config_revision:
            raise SorConflictError("SOR source configuration changed.")
        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        if not manifest.change_mode.accepts_webhooks:
            raise SorConfigurationError("Source adapter does not support webhooks.")
        secret_revision = source.webhook_signing_secret_revision + 1
        source.webhook_signing_secret = encrypt_source_webhook_signing_secret(
            signing_secret,
            organization_id=organization_id,
            source_id=source_id,
            secret_revision=secret_revision,
        )
        source.webhook_signing_secret_revision = secret_revision
        source.config_revision += 1
        await self.session.flush()
        return source

    async def resolve_endpoint(
        self,
        *,
        vendor_key: str,
        endpoint_token: str,
    ) -> SorSourceModel:
        """Resolve source authority from the URL secret, never request payload data."""
        if not 32 <= len(endpoint_token) <= 256:
            raise SorNotFoundError("SOR webhook endpoint not found.")
        source = await self.repository.get_source_by_webhook_token_hash(
            token_hash=_sha256_bytes(endpoint_token.encode("utf-8")),
        )
        if source is None or source.vendor_key != vendor_key:
            raise SorNotFoundError("SOR webhook endpoint not found.")
        if source.state not in {
            SorSourceState.BOOTSTRAPPING,
            SorSourceState.ACTIVE,
            SorSourceState.DEGRADED,
        }:
            raise SorNotFoundError("SOR webhook endpoint not found.")
        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        if not manifest.change_mode.accepts_webhooks:
            raise SorNotFoundError("SOR webhook endpoint not found.")
        return source

    async def record_verified_delivery(
        self,
        *,
        source: SorSourceModel,
        body: bytes,
        signals: Sequence[SorWebhookSignal],
        now: datetime | None = None,
    ) -> tuple[SorWebhookReceiptModel, bool]:
        """Deduplicate a verified delivery while retaining every normalized signal."""
        if not signals:
            raise SorConfigurationError("Verified webhook contains no source signals.")
        if len(body) > SOR_WEBHOOK_MAX_BODY_BYTES:
            raise SorConfigurationError("SOR webhook body is too large.")
        normalized = _normalize_signals(signals)
        delivery_ids = {
            signal["delivery_id"]
            for signal in normalized
            if signal["delivery_id"] is not None
        }
        if len(delivery_ids) > 1:
            raise SorConfigurationError(
                "Webhook signals disagree on their vendor delivery ID."
            )
        delivery_id = next(iter(delivery_ids), None)
        payload_hash = _sha256_bytes(body)
        fingerprint = _fingerprint(
            source_id=source.id,
            payload_hash=payload_hash,
            signals=normalized,
        )
        existing = await self.repository.get_webhook_receipt_by_identity(
            source_id=source.id,
            vendor_delivery_id=delivery_id,
            fingerprint=fingerprint,
            for_update=True,
        )
        if existing is not None:
            _require_same_delivery(
                existing,
                payload_hash=payload_hash,
                signals=normalized,
            )
            existing.replay_detected = True
            await self.session.flush()
            return existing, False

        receipt_id = uuid.uuid4()
        received_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        first = normalized[0]
        encrypted_body = encrypt_bytes(
            body,
            organization_id=source.organization_id,
            resource_id=receipt_id,
            purpose="webhook-body",
            maximum_bytes=SOR_WEBHOOK_MAX_BODY_BYTES,
        )
        statement = (
            insert(SorWebhookReceiptModel)
            .values(
                id=receipt_id,
                organization_id=source.organization_id,
                source_id=source.id,
                vendor_delivery_id=delivery_id,
                fingerprint=fingerprint,
                event_type=(
                    first["event_type"] if len(normalized) == 1 else "batch"
                ),
                vendor_object_key=first["vendor_object_key"],
                vendor_external_id=first["external_id"],
                vendor_event_at=(
                    datetime.fromisoformat(first["occurred_at"])
                    if first["occurred_at"] is not None
                    else None
                ),
                payload_hash=payload_hash,
                signature_verified=True,
                replay_detected=False,
                signals=normalized,
                state=SorWebhookReceiptState.PENDING,
                encrypted_raw_body=encrypted_body,
                raw_body_expires_at=received_at
                + timedelta(hours=SOR_WEBHOOK_RAW_RETENTION_HOURS),
                attempts=0,
                max_attempts=3,
                deleted=False,
            )
            .on_conflict_do_nothing()
            .returning(SorWebhookReceiptModel.id)
        )
        inserted_id = await self.session.scalar(statement)
        if inserted_id is not None:
            row = await self.repository.get_webhook_receipt(
                organization_id=source.organization_id,
                receipt_id=inserted_id,
            )
            if row is None:
                raise SorConflictError("Webhook receipt insert was not readable.")
            return row, True

        existing = await self.repository.get_webhook_receipt_by_identity(
            source_id=source.id,
            vendor_delivery_id=delivery_id,
            fingerprint=fingerprint,
            for_update=True,
        )
        if existing is None:
            raise SorConflictError("Webhook delivery identity conflicted.")
        _require_same_delivery(
            existing,
            payload_hash=payload_hash,
            signals=normalized,
        )
        existing.replay_detected = True
        await self.session.flush()
        return existing, False

    async def prune_expired_raw_bodies(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        """Erase transient payloads; preserve successful/failed receipt status."""
        cutoff = now or datetime.now(timezone.utc)
        result = await self.session.execute(
            update(SorWebhookReceiptModel)
            .where(
                SorWebhookReceiptModel.raw_body_expires_at.is_not(None),
                SorWebhookReceiptModel.raw_body_expires_at <= cutoff,
                SorWebhookReceiptModel.deleted.is_(False),
            )
            .values(
                encrypted_raw_body=None,
                raw_body_expires_at=None,
                state=case(
                    (
                        SorWebhookReceiptModel.state.in_(
                            (
                                SorWebhookReceiptState.PENDING,
                                SorWebhookReceiptState.PROCESSING,
                            )
                        ),
                        SorWebhookReceiptState.EXPIRED,
                    ),
                    else_=SorWebhookReceiptModel.state,
                ),
                finished_at=case(
                    (
                        SorWebhookReceiptModel.state.in_(
                            (
                                SorWebhookReceiptState.PENDING,
                                SorWebhookReceiptState.PROCESSING,
                            )
                        ),
                        cutoff,
                    ),
                    else_=SorWebhookReceiptModel.finished_at,
                ),
            )
        )
        if not isinstance(result, CursorResult):
            raise SorConflictError("Webhook receipt pruning returned no row count.")
        return int(result.rowcount or 0)


def _normalize_signals(
    signals: Sequence[SorWebhookSignal],
) -> list[dict[str, str | None]]:
    normalized: list[dict[str, str | None]] = []
    for signal in signals:
        event_type = signal.event_type.strip()
        if not 1 <= len(event_type) <= 256:
            raise SorConfigurationError("Webhook event type is invalid.")
        if signal.delivery_id is not None and not 1 <= len(signal.delivery_id) <= 512:
            raise SorConfigurationError("Webhook delivery ID is invalid.")
        if signal.vendor_object_key is not None and not 1 <= len(
            signal.vendor_object_key
        ) <= 160:
            raise SorConfigurationError("Webhook object key is invalid.")
        if signal.external_id is not None and not 1 <= len(signal.external_id) <= 512:
            raise SorConfigurationError("Webhook external ID is invalid.")
        occurred_at = signal.occurred_at
        if occurred_at is not None:
            if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
                raise SorConfigurationError(
                    "Webhook event timestamp must include a timezone."
                )
            occurred_at = occurred_at.astimezone(timezone.utc)
        normalized.append(
            {
                "delivery_id": signal.delivery_id,
                "event_type": event_type,
                "vendor_object_key": signal.vendor_object_key,
                "external_id": signal.external_id,
                "occurred_at": occurred_at.isoformat() if occurred_at else None,
            }
        )
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > 262_144:
        raise SorConfigurationError("Webhook signal set is too large.")
    return normalized


def _subscription_state(value: str | None) -> SorWebhookSubscriptionState | None:
    if value is None:
        return None
    try:
        return SorWebhookSubscriptionState(value)
    except ValueError as error:
        raise SorConfigurationError(
            "Source webhook subscription state is invalid."
        ) from error


def _fingerprint(
    *,
    source_id: UUID,
    payload_hash: str,
    signals: list[dict[str, str | None]],
) -> str:
    encoded = json.dumps(
        {
            "source_id": str(source_id),
            "payload_hash": payload_hash,
            "signals": signals,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _require_same_delivery(
    existing: SorWebhookReceiptModel,
    *,
    payload_hash: str,
    signals: list[dict[str, str | None]],
) -> None:
    if existing.payload_hash != payload_hash or existing.signals != signals:
        raise SorConflictError(
            "Webhook delivery ID was reused for different content."
        )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "SOR_WEBHOOK_MAX_BODY_BYTES",
    "SOR_WEBHOOK_OPERATION_LEASE",
    "SOR_WEBHOOK_RAW_RETENTION_HOURS",
    "SOR_WEBHOOK_RENEWAL_MARGIN",
    "SorWebhookService",
    "SorWebhookSubscriptionPlan",
]
