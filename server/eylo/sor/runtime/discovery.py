"""Coordinate source verification and schema discovery outside DB transactions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eylo.common.database import start_transaction
from eylo.sor.runtime.adapters import (
    SorAdapterUnavailableError,
    acquire_source_adapter,
)
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.connector_services import SorConnectorService
from eylo.sor.shared.contracts import (
    SorConnectionVerification,
    SorDiscoveredSchema,
    SorSchemaDifference,
    SorSourceTransition,
    SorVendorOperationError,
)
from eylo.sor.shared.services import (
    SorConflictError,
    SorSchemaService,
    SorSourceService,
)

logger = logging.getLogger(__name__)


class SorDiscoveryPhase(StrEnum):
    """Operation currently owning discovery progress and failure reporting."""

    VERIFICATION = "verification"
    DISCOVERY = "discovery"


class SorDiscoveryFailure(StrEnum):
    """Runtime-owned failure codes; vendor and adapter errors keep their owners."""

    OPERATION_CANCELLED = "OPERATION_CANCELLED"
    OPERATION_TIMEOUT = "OPERATION_TIMEOUT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    DISCOVERY_FAILED = "DISCOVERY_FAILED"


class SorDiscoveryResult(BaseModel):
    """Stable outcome of one complete source verification and discovery."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    verification: SorConnectionVerification
    schema_revision_id: UUID
    schema_revision: int
    schema_hash: str
    difference: SorSchemaDifference


class _DiscoveryAuthority(BaseModel):
    """Exact source configuration/mapping revision checked again at commit."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    config_revision: int
    mapping_revision_id: UUID | None


async def verify_and_discover_source(
    *,
    organization_id: UUID,
    source_id: UUID,
    registry: SorRegistry | None = None,
    verification_timeout_seconds: float = 20.0,
    discovery_timeout_seconds: float = 120.0,
) -> SorDiscoveryResult:
    """Commit each lifecycle boundary while vendor I/O holds no DB transaction."""
    _require_timeout(verification_timeout_seconds, field_name="verification timeout")
    _require_timeout(discovery_timeout_seconds, field_name="discovery timeout")

    authority = await _transition(
        organization_id=organization_id,
        source_id=source_id,
        transition=SorSourceTransition.BEGIN_VERIFICATION,
    )
    phase = SorDiscoveryPhase.VERIFICATION
    try:
        async with acquire_source_adapter(
            organization_id=organization_id,
            source_id=source_id,
            invocation_budget_seconds=(
                verification_timeout_seconds + discovery_timeout_seconds
            ),
            registry=registry,
        ) as adapter:
            async with asyncio.timeout(verification_timeout_seconds):
                verification = await adapter.verify_connection()
            verified_at = datetime.now(timezone.utc)

            await _transition(
                organization_id=organization_id,
                source_id=source_id,
                transition=SorSourceTransition.VERIFICATION_SUCCEEDED,
            )
            phase = SorDiscoveryPhase.DISCOVERY
            async with asyncio.timeout(discovery_timeout_seconds):
                schema = await adapter.discover_schema()
        return await _commit_schema(
            organization_id=organization_id,
            source_id=source_id,
            verification=verification,
            schema=schema,
            authority=authority,
            verified_at=verified_at,
        )
    except SorAdapterUnavailableError as error:
        await _mark_failure(
            organization_id=organization_id,
            source_id=source_id,
            phase=phase,
            error_code=error.error_code,
            error_summary=str(error),
            requires_reauthorization=error.requires_reauthorization,
        )
        raise
    except SorVendorOperationError as error:
        await _mark_failure(
            organization_id=organization_id,
            source_id=source_id,
            phase=phase,
            error_code=error.code,
            error_summary=str(error),
            requires_reauthorization=error.requires_reauthorization,
        )
        raise
    except asyncio.CancelledError:
        await _mark_failure(
            organization_id=organization_id,
            source_id=source_id,
            phase=phase,
            error_code=SorDiscoveryFailure.OPERATION_CANCELLED,
            error_summary="The source operation was cancelled before completion.",
        )
        raise
    except TimeoutError:
        await _mark_failure(
            organization_id=organization_id,
            source_id=source_id,
            phase=phase,
            error_code=SorDiscoveryFailure.OPERATION_TIMEOUT,
            error_summary=f"Source {phase} exceeded its time budget.",
        )
        raise
    except Exception as error:
        logger.warning(
            "SOR source operation failed organization_id=%s source_id=%s "
            "phase=%s error_type=%s",
            organization_id,
            source_id,
            phase,
            type(error).__name__,
        )
        await _mark_failure(
            organization_id=organization_id,
            source_id=source_id,
            phase=phase,
            error_code=(
                SorDiscoveryFailure.VERIFICATION_FAILED
                if phase is SorDiscoveryPhase.VERIFICATION
                else SorDiscoveryFailure.DISCOVERY_FAILED
            ),
            error_summary=f"Source {phase} failed.",
        )
        raise


async def rediscover_source_schema(
    *,
    organization_id: UUID,
    source_id: UUID,
    selected_objects: Sequence[str] | None = None,
    registry: SorRegistry | None = None,
    verification_timeout_seconds: float = 20.0,
    discovery_timeout_seconds: float = 120.0,
) -> SorDiscoveryResult:
    """Refresh schema without taking an active projection out of service."""
    _require_timeout(verification_timeout_seconds, field_name="verification timeout")
    _require_timeout(discovery_timeout_seconds, field_name="discovery timeout")
    authority = await _prepare_schema_refresh(
        organization_id=organization_id,
        source_id=source_id,
    )
    phase = SorDiscoveryPhase.VERIFICATION
    try:
        async with acquire_source_adapter(
            organization_id=organization_id,
            source_id=source_id,
            invocation_budget_seconds=(
                verification_timeout_seconds + discovery_timeout_seconds
            ),
            selected_objects=selected_objects,
            registry=registry,
        ) as adapter:
            async with asyncio.timeout(verification_timeout_seconds):
                verification = await adapter.verify_connection()
            verified_at = datetime.now(timezone.utc)
            phase = SorDiscoveryPhase.DISCOVERY
            async with asyncio.timeout(discovery_timeout_seconds):
                schema = await adapter.discover_schema()
        return await _commit_schema(
            organization_id=organization_id,
            source_id=source_id,
            verification=verification,
            schema=schema,
            authority=authority,
            verified_at=verified_at,
        )
    except SorConflictError:
        raise
    except SorAdapterUnavailableError as error:
        if error.requires_reauthorization:
            await _mark_refresh_reauthorization_required(
                organization_id=organization_id,
                source_id=source_id,
                authority=authority,
                error_code=error.error_code,
                error_summary=str(error),
            )
        else:
            await _mark_refresh_failure(
                organization_id=organization_id,
                source_id=source_id,
                authority=authority,
                error_code=error.error_code,
                error_summary=str(error),
            )
        raise
    except SorVendorOperationError as error:
        if error.requires_reauthorization:
            await _mark_refresh_reauthorization_required(
                organization_id=organization_id,
                source_id=source_id,
                authority=authority,
                error_code=error.code,
                error_summary=str(error),
            )
        else:
            await _mark_refresh_failure(
                organization_id=organization_id,
                source_id=source_id,
                authority=authority,
                error_code=error.code,
                error_summary=str(error),
            )
        raise
    except asyncio.CancelledError:
        await _mark_refresh_failure(
            organization_id=organization_id,
            source_id=source_id,
            authority=authority,
            error_code=SorDiscoveryFailure.OPERATION_CANCELLED,
            error_summary="The schema refresh was cancelled before completion.",
        )
        raise
    except TimeoutError:
        await _mark_refresh_failure(
            organization_id=organization_id,
            source_id=source_id,
            authority=authority,
            error_code=SorDiscoveryFailure.OPERATION_TIMEOUT,
            error_summary=f"Source {phase} exceeded its time budget.",
        )
        raise
    except Exception as error:
        logger.warning(
            "SOR schema refresh failed organization_id=%s source_id=%s "
            "phase=%s error_type=%s",
            organization_id,
            source_id,
            phase,
            type(error).__name__,
        )
        await _mark_refresh_failure(
            organization_id=organization_id,
            source_id=source_id,
            authority=authority,
            error_code=(
                SorDiscoveryFailure.VERIFICATION_FAILED
                if phase is SorDiscoveryPhase.VERIFICATION
                else SorDiscoveryFailure.DISCOVERY_FAILED
            ),
            error_summary=f"Source {phase} failed.",
        )
        raise


async def _commit_schema(
    *,
    organization_id: UUID,
    source_id: UUID,
    verification: SorConnectionVerification,
    schema: SorDiscoveredSchema,
    authority: _DiscoveryAuthority,
    verified_at: datetime,
) -> SorDiscoveryResult:
    async with start_transaction() as session:
        row, difference = await SorSchemaService(session).record_discovery(
            organization_id=organization_id,
            source_id=source_id,
            schema=schema,
            expected_config_revision=authority.config_revision,
            expected_mapping_revision_id=authority.mapping_revision_id,
            verified_at=verified_at,
        )
        await SorConnectorService(session).record_verified_account(
            organization_id=organization_id,
            connection_id=(
                await SorSourceService(session).get(
                    organization_id=organization_id,
                    source_id=source_id,
                )
            ).external_connection_id,
            account_external_id=verification.account_external_id,
            account_display_name=verification.account_display_name,
        )
        result = SorDiscoveryResult(
            verification=verification,
            schema_revision_id=row.id,
            schema_revision=row.revision,
            schema_hash=row.schema_hash,
            difference=difference,
        )
    return result


async def _transition(
    *,
    organization_id: UUID,
    source_id: UUID,
    transition: SorSourceTransition,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> _DiscoveryAuthority:
    async with start_transaction() as session:
        source = await SorSourceService(session).transition(
            organization_id=organization_id,
            source_id=source_id,
            transition=transition,
            error_code=error_code,
            error_summary=error_summary,
        )
        return _DiscoveryAuthority(
            config_revision=source.config_revision,
            mapping_revision_id=source.active_mapping_revision_id,
        )


async def _prepare_schema_refresh(
    *,
    organization_id: UUID,
    source_id: UUID,
) -> _DiscoveryAuthority:
    async with start_transaction() as session:
        config_revision, mapping_revision_id = await SorSourceService(
            session
        ).prepare_schema_refresh(
            organization_id=organization_id,
            source_id=source_id,
        )
        return _DiscoveryAuthority(
            config_revision=config_revision,
            mapping_revision_id=mapping_revision_id,
        )


async def _mark_refresh_failure(
    *,
    organization_id: UUID,
    source_id: UUID,
    authority: _DiscoveryAuthority,
    error_code: str,
    error_summary: str,
) -> None:
    if authority.mapping_revision_id is None:
        raise SorConflictError("Schema refresh lost its mapping authority.")
    try:
        async with start_transaction() as session:
            await SorSourceService(session).record_schema_refresh_failure(
                organization_id=organization_id,
                source_id=source_id,
                expected_config_revision=authority.config_revision,
                expected_mapping_revision_id=authority.mapping_revision_id,
                error_code=error_code,
                error_summary=error_summary,
            )
    except Exception as state_error:
        logger.error(
            "SOR schema refresh failure could not be recorded "
            "organization_id=%s source_id=%s error_type=%s",
            organization_id,
            source_id,
            type(state_error).__name__,
        )


async def _mark_refresh_reauthorization_required(
    *,
    organization_id: UUID,
    source_id: UUID,
    authority: _DiscoveryAuthority,
    error_code: str,
    error_summary: str,
) -> None:
    if authority.mapping_revision_id is None:
        raise SorConflictError("Schema refresh lost its mapping authority.")
    try:
        async with start_transaction() as session:
            await SorSourceService(
                session
            ).record_schema_refresh_reauthorization_required(
                organization_id=organization_id,
                source_id=source_id,
                expected_config_revision=authority.config_revision,
                expected_mapping_revision_id=authority.mapping_revision_id,
                error_code=error_code,
                error_summary=error_summary,
            )
    except Exception as state_error:
        logger.error(
            "SOR schema refresh reauthorization could not be recorded "
            "organization_id=%s source_id=%s error_type=%s",
            organization_id,
            source_id,
            type(state_error).__name__,
        )


async def _mark_failure(
    *,
    organization_id: UUID,
    source_id: UUID,
    phase: SorDiscoveryPhase,
    error_code: str,
    error_summary: str,
    requires_reauthorization: bool = False,
) -> None:
    transition = (
        SorSourceTransition.REAUTHORIZATION_REQUIRED
        if requires_reauthorization
        else (
            SorSourceTransition.VERIFICATION_FAILED
            if phase is SorDiscoveryPhase.VERIFICATION
            else SorSourceTransition.DISCOVERY_FAILED
        )
    )
    try:
        await _transition(
            organization_id=organization_id,
            source_id=source_id,
            transition=transition,
            error_code=error_code,
            error_summary=error_summary,
        )
    except Exception as state_error:
        logger.error(
            "SOR source failure state could not be recorded organization_id=%s "
            "source_id=%s transition=%s error_type=%s",
            organization_id,
            source_id,
            transition.value,
            type(state_error).__name__,
        )


def _require_timeout(value: float, *, field_name: str) -> None:
    if not 0 < value <= 300:
        raise ValueError(
            f"{field_name} must be greater than zero and at most 300 seconds."
        )


__all__ = [
    "SorDiscoveryResult",
    "rediscover_source_schema",
    "verify_and_discover_source",
]
