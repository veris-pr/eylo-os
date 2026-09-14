"""Pipeline-backed system tool for issuing a one-time visitor chat link."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
)

from eylo.modules.auth.schemas.widget_invitations import WidgetInvitationIssueRequest
from eylo.modules.auth.widget_invitations import (
    MAX_WIDGET_INVITATION_LIFETIME,
    WidgetInvitationIssuerKind,
)
from eylo.modules.tools.services.executors.system_tools import logger
from eylo.pipelines.agent_execution_context import PlatformExecutionContext
from eylo.pipelines.widget_invitations import issue_widget_invitation

_MIN_EXPIRY_MINUTES = 1
_MAX_EXPIRY_MINUTES = MAX_WIDGET_INVITATION_LIFETIME // timedelta(minutes=1)


class ChatInvitationFailure(StrEnum):
    EMAIL_REQUIRED = "A visitor email is required."
    EXPIRY_INVALID = f"expires_in_minutes must be between {_MIN_EXPIRY_MINUTES} and {_MAX_EXPIRY_MINUTES}."
    CONTEXT_UNAVAILABLE = "Conversation authority is unavailable."
    AGENT_REVISION_UNAVAILABLE = "Primary agent has no exact published revision."
    ISSUANCE_FAILED = "Could not issue the chat invitation."


class ChatInvitationRefused(BaseModel):
    """Existing tool refusal shape; no internal exception content is exposed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: Literal[False] = False
    error: ChatInvitationFailure


class ChatInvitationIssued(BaseModel):
    """Explicit agent-visible projection; bearer URL stays out of repr/errors."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    success: Literal[True] = True
    visitor_chat_link: str = Field(repr=False)
    expires_at: AwareDatetime
    warning_codes: list[str]

    @field_serializer("expires_at")
    def expiry_on_wire(self, value: datetime) -> str:
        """Preserve the existing offset format, including +00:00 rather than Z."""
        return value.isoformat()


async def issue_chat_link(
    visitor_email: str,
    visitor_name: str,
    initial_message: str,
    expires_in_minutes: int,
    *args: object,
    ctx: PlatformExecutionContext | None = None,
    **kwargs: object,
) -> dict[str, JsonValue]:
    """Issue a one-time invitation; exchange creates the guest chat state."""
    del args, kwargs
    if not visitor_email:
        return ChatInvitationRefused(
            error=ChatInvitationFailure.EMAIL_REQUIRED
        ).model_dump(mode="json")
    if not isinstance(expires_in_minutes, int) or not (
        _MIN_EXPIRY_MINUTES <= expires_in_minutes <= _MAX_EXPIRY_MINUTES
    ):
        return ChatInvitationRefused(
            error=ChatInvitationFailure.EXPIRY_INVALID
        ).model_dump(mode="json")
    if not ctx or not ctx.conversation or not ctx.primary_agent:
        return ChatInvitationRefused(
            error=ChatInvitationFailure.CONTEXT_UNAVAILABLE
        ).model_dump(mode="json")
    agent_participant = ctx.get_primary_agent()
    if (
        agent_participant is None
        or agent_participant.agent_id is None
        or agent_participant.agent_revision is None
    ):
        return ChatInvitationRefused(
            error=ChatInvitationFailure.AGENT_REVISION_UNAVAILABLE
        ).model_dump(mode="json")
    organization_id = ctx.primary_agent.organization_id

    try:
        issued = await issue_widget_invitation(
            organization_id=organization_id,
            request=WidgetInvitationIssueRequest(
                agent_id=agent_participant.agent_id,
                external_id=visitor_email,
                primary_email=visitor_email,
                name=visitor_name,
                opener=initial_message,
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=expires_in_minutes),
            ),
            issued_by_kind=WidgetInvitationIssuerKind.AGENT,
            issued_by_id=agent_participant.agent_id,
            pinned_agent_revision=agent_participant.agent_revision,
        )
    except Exception as error:  # noqa: BLE001 - tool returns one safe failure shape
        logger.error(
            "Guest-chat invitation issuance failed error_type=%s",
            type(error).__name__,
        )
        return ChatInvitationRefused(
            error=ChatInvitationFailure.ISSUANCE_FAILED
        ).model_dump(mode="json")
    return ChatInvitationIssued(
        visitor_chat_link=issued.invitation_url,
        expires_at=issued.invitation.expires_at,
        warning_codes=list(issued.warning_codes),
    ).model_dump(mode="json")


__all__ = ["issue_chat_link"]
