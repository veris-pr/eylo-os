"""Local-only bootstrap for exercising the real widget product flow."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eylo.common.config import Environment, settings
from eylo.common.database import start_transaction
from eylo.modules.auth.services.session_service import AuthSessionService
from eylo.modules.contacts.schemas.indb import ContactRef
from eylo.modules.contacts.service import ContactService


class WidgetDevelopmentSessionUnavailable(Exception):
    """The trusted local widget identity is absent or no longer valid."""


class WidgetDevelopmentSession(BaseModel):
    """Local bootstrap result; only the explicit HTTP response exposes its token."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_id: UUID
    contact_id: UUID
    session_token: str = Field(repr=False, exclude=True, min_length=1)
    session_expires_at: datetime


async def create_widget_development_session(
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> WidgetDevelopmentSession:
    """Mint a normal AuthSession for the operator-fixed local contact."""
    organization_id = settings.WIDGET_DEVELOPMENT_ORGANIZATION_ID
    contact_id = settings.WIDGET_DEVELOPMENT_CONTACT_ID
    if (
        settings.ENV is not Environment.LOCAL
        or organization_id is None
        or contact_id is None
    ):
        raise WidgetDevelopmentSessionUnavailable

    async with start_transaction() as db:
        contact = await ContactService(db).get_by_ref(
            ContactRef(
                organization_id=organization_id,
                contact_id=contact_id,
            )
        )
        if contact is None:
            raise WidgetDevelopmentSessionUnavailable
        session = await AuthSessionService(db).create_session_for_contact(
            contact=contact,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return WidgetDevelopmentSession(
            organization_id=organization_id,
            contact_id=contact_id,
            session_token=session.session_token,
            session_expires_at=session.expires_at,
        )


__all__ = [
    "WidgetDevelopmentSession",
    "WidgetDevelopmentSessionUnavailable",
    "create_widget_development_session",
]
