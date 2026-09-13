"""Execute one curated vendor tool from committed product intent.

Policy is resolved live through the module service. The handler is curated
Python that may make several vendor calls rather than one declarative request.

Nothing here decides policy. `resolve_for_execution` already refused a disabled
or approval-gated tool before a client was ever constructed.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from eylo.common.database import current_transaction, start_transaction
from eylo.events.py_events.emitter import emit_ephemeral
from eylo.events.schema.py_events.base import AuthRequiredEvent
from eylo.modules.integrations_v2.domain.enums import ToolEffect
from eylo.modules.integrations_v2.domain.errors import (
    IntegrationErrorCode,
    IntegrationsV2Error,
    ToolApprovalRequiredError,
)
from eylo.modules.integrations_v2.schemas.indb import ToolExecutionGrant
from eylo.modules.integrations_v2.services.installations import (
    CuratedIntegrationService,
)
from eylo.pipelines.outbound.durable_execution import CommandStepContext

from .contracts import VendorToolContext, VendorToolError
from .http_client import DurableMutationOwner, GuardedVendorClient, VendorTransport
from .registry import CuratedRegistry, load_vendors
from .resolution import resolve_vendor_auth
from .results import (
    CuratedExecutionErrorCode,
    CuratedFailureAction,
    CuratedResultContent,
    CuratedResultMetadata,
    CuratedToolExecutionOutcome,
    error_outcome,
)

if TYPE_CHECKING:
    from eylo.pipelines.agent_execution_context import PlatformExecutionContext

_ARGUMENTS = TypeAdapter(dict[str, JsonValue], config=ConfigDict(allow_inf_nan=False))
_RESULT = TypeAdapter(JsonValue, config=ConfigDict(allow_inf_nan=False))
INVOCATION_STAMP_VERSION = 1


class CuratedInvocationStamp(BaseModel):
    """Retry-stable occurrence time for vendor writes requiring a timestamp."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    started_at: AwareDatetime


async def _invocation_started_at(
    context: CommandStepContext, tool_use_message_id: UUID
) -> datetime:
    async def capture() -> str:
        return CuratedInvocationStamp(started_at=datetime.now(UTC)).model_dump_json()

    snapshot = await context.step(
        key=f"curated.invocation.{tool_use_message_id}",
        version=INVOCATION_STAMP_VERSION,
        operation=capture,
    )
    return CuratedInvocationStamp.model_validate_json(snapshot, strict=True).started_at


async def execute_curated_tool(
    *,
    tool_id: UUID,
    tool_input: Mapping[str, object],
    conversation_context: PlatformExecutionContext,
    tool_use_message_id: UUID,
    durable_context: CommandStepContext,
    registry: CuratedRegistry | None = None,
    transport: VendorTransport | None = None,
    service: CuratedIntegrationService | None = None,
) -> CuratedToolExecutionOutcome:
    """Authorize and prepare in DB-only scopes, then invoke the vendor handler.

    Borrowed sessions and injected services remain caller-owned. Without them,
    policy and connection lookups each release their owned scope before I/O.
    Invalid results are reported without retrying a possibly committed effect.
    """
    organization_id = UUID(str(conversation_context.conversation.organization_id))
    registry = registry or load_vendors()

    try:
        grant = await _execution_grant(
            organization_id=organization_id,
            tool_id=tool_id,
            service=service,
        )
    except ToolApprovalRequiredError as error:
        return error_outcome(error.code, action=CuratedFailureAction.APPROVE)
    except IntegrationsV2Error as error:
        return error_outcome(error.code)

    spec = registry.tool(grant.wire_id)
    if spec is None:
        return error_outcome(CuratedExecutionErrorCode.BINDING_UNAVAILABLE)

    try:
        arguments = _ARGUMENTS.validate_python(dict(tool_input), strict=True)
        payload = spec.input_model.model_validate(arguments)
    except (TypeError, ValueError):
        return error_outcome(CuratedExecutionErrorCode.INPUT_INVALID)

    contact_id = _primary_contact_id(conversation_context)
    try:
        resolved = await resolve_vendor_auth(
            grant=grant,
            contact_id=contact_id,
            registry=registry,
            required_scopes=spec.scopes,
            connections=service,
        )
    except IntegrationsV2Error as error:
        auth_required = error.code == IntegrationErrorCode.AUTH_REQUIRED
        if auth_required and contact_id is not None:
            emit_ephemeral(
                AuthRequiredEvent(
                    conversation_id=UUID(str(conversation_context.conversation.id)),
                    organization_id=organization_id,
                    integration_id=grant.installation_id,
                    vendor=grant.vendor,
                    auth_kind=grant.auth_kind,
                    integration_name=resolved_vendor_name(registry, grant.vendor),
                    reason="authorization_required",
                    contact_id=contact_id,
                    message=(
                        f"Connect {resolved_vendor_name(registry, grant.vendor)} "
                        "so the Agent can continue."
                    ),
                )
            )
        return error_outcome(
            error.code,
            action=(
                CuratedFailureAction.CONNECT
                if auth_required
                else CuratedFailureAction.NONE
            ),
            vendor=grant.vendor,
        )

    started_at = None
    if spec.effect is ToolEffect.MUTATION:
        try:
            started_at = await _invocation_started_at(
                durable_context, tool_use_message_id
            )
        except ValidationError:
            return error_outcome(
                CuratedExecutionErrorCode.INVOCATION_INVALID, vendor=grant.vendor
            )

    client = GuardedVendorClient(
        base_url=resolved.base_url,
        auth=resolved.auth,
        vendor=resolved.vendor.vendor,
        transport=transport,
        static_headers=dict(resolved.vendor.static_headers),
        accept_media_type=resolved.vendor.accept_media_type,
        owner=DurableMutationOwner(
            organization_id=organization_id,
            tool_use_message_id=tool_use_message_id,
            tool_id=tool_id,
            durable_context=durable_context,
        ),
    )
    context = VendorToolContext(
        http=client,
        account=resolved.account,
        effect=spec.effect,
        started_at=started_at,
    )

    try:
        raw_result = await spec.handler(payload, context)
    except VendorToolError as error:
        return error_outcome(error.code, vendor=grant.vendor)
    try:
        result = _RESULT.validate_python(raw_result, strict=True)
    except ValidationError:
        return error_outcome(
            CuratedExecutionErrorCode.RESULT_INVALID, vendor=grant.vendor
        )

    return CuratedToolExecutionOutcome(
        content=CuratedResultContent(data=result),
        is_error=False,
        metadata=CuratedResultMetadata(
            vendor=grant.vendor,
            wire_id=grant.wire_id,
            effect=spec.effect,
        ),
    )


async def _execution_grant(
    *,
    organization_id: UUID,
    tool_id: UUID,
    service: CuratedIntegrationService | None,
) -> ToolExecutionGrant:
    if service is not None:
        return await service.resolve_for_execution(
            organization_id=organization_id, tool_id=tool_id
        )
    session = current_transaction()
    scope = start_transaction(ro=True) if session is None else nullcontext(session)
    async with scope as db:
        return await CuratedIntegrationService(db).resolve_for_execution(
            organization_id=organization_id, tool_id=tool_id
        )


def _primary_contact_id(conversation_context: PlatformExecutionContext) -> UUID | None:
    participant = conversation_context.get_primary_contact()
    if participant is None:
        return None
    try:
        return UUID(str(participant.entity_id))
    except (TypeError, ValueError):
        return None


def resolved_vendor_name(registry: CuratedRegistry, vendor: str) -> str:
    spec = registry.vendor(vendor)
    return spec.display_name if spec is not None else vendor


__all__ = [
    "CuratedToolExecutionOutcome",
    "execute_curated_tool",
]
