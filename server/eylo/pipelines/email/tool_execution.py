"""Durable execution path for the platform send_email agent tool."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, JsonValue, ValidationError

from eylo.common.outbound import (
    OutboundAttemptConflict,
    OutboundAttemptState,
    OutboundOwnerKind,
)
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.pipelines.outbound.durable_execution import CommandStepContext

from .contracts import (
    EmailAcceptedContent,
    EmailDeliveryMetadata,
    EmailErrorContent,
    EmailToolError,
    EmailToolExecutionOutcome,
)
from .delivery import EmailDeliveryUnsupported, send_organization_email

if TYPE_CHECKING:
    from eylo.pipelines.agent_execution_context import PlatformExecutionContext
    from eylo.sockets.email.sendgrid import SendGridHttpTransport

SEND_EMAIL_TOOL_NAME = "send_email"
_EMAIL_SUBJECT_MAX_LENGTH = 998


class _SendEmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    to_email: EmailStr
    subject: str = Field(min_length=1, max_length=_EMAIL_SUBJECT_MAX_LENGTH)
    text_body: str = Field(min_length=1)
    html_body: str | None = None


async def execute_agent_email_tool(
    *,
    tool_input: Mapping[str, JsonValue],
    conversation_context: PlatformExecutionContext,
    tool_use_message_id: UUID,
    durable_context: CommandStepContext,
    sendgrid_transport: SendGridHttpTransport | None = None,
) -> EmailToolExecutionOutcome:
    """Send once under the committed TOOL_USE message and exact agent grant."""
    try:
        requested = _SendEmailInput.model_validate(dict(tool_input))
    except ValidationError:
        return _error(EmailToolError.INPUT_INVALID)

    agent = conversation_context.primary_agent
    if agent is None:
        return _error(EmailToolError.CONFIG_UNAVAILABLE)
    provider_config_id = agent.email_provider_config_id
    provider_config_revision = agent.email_provider_config_revision
    if provider_config_id is None or provider_config_revision is None:
        return _error(EmailToolError.CONFIG_UNAVAILABLE)

    try:
        result = await send_organization_email(
            organization_id=conversation_context.conversation.organization_id,
            owner_kind=OutboundOwnerKind.TOOL_CALL,
            owner_id=tool_use_message_id,
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config_revision,
            to_email=str(requested.to_email),
            subject=requested.subject,
            text_body=requested.text_body,
            html_body=requested.html_body,
            durable_context=durable_context,
            sendgrid_transport=sendgrid_transport,
        )
    except NotConfiguredError:
        return _error(EmailToolError.CONFIG_UNAVAILABLE)
    except EmailDeliveryUnsupported:
        return _error(EmailToolError.DELIVERY_UNSUPPORTED)
    except OutboundAttemptConflict:
        return _error(EmailToolError.DELIVERY_CONFLICT)

    metadata = EmailDeliveryMetadata(
        email_delivery_status=result.status,
        outbound_attempt_id=result.attempt_id,
        provider_config_id=provider_config_id,
        provider_config_revision=provider_config_revision,
    )
    if result.state is OutboundAttemptState.SUCCEEDED:
        return EmailToolExecutionOutcome(
            result=EmailAcceptedContent(message_id=result.tracking_id),
            delivery=metadata,
        )
    code = (
        EmailToolError.DELIVERY_UNKNOWN
        if result.state is OutboundAttemptState.UNKNOWN
        else EmailToolError.DELIVERY_REJECTED
    )
    return _error(code, metadata=metadata)


def _error(
    code: EmailToolError,
    *,
    metadata: EmailDeliveryMetadata | None = None,
) -> EmailToolExecutionOutcome:
    return EmailToolExecutionOutcome(
        result=EmailErrorContent(error=code),
        delivery=metadata,
    )


__all__ = [
    "EmailToolExecutionOutcome",
    "SEND_EMAIL_TOOL_NAME",
    "execute_agent_email_tool",
]
