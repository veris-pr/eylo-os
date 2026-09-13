"""Connection event listeners for WebSocket broadcasting."""

import logging

from eylo.events.schema.py_events.connections import (
    ConnectionExpiredEvent,
    ConnectionFailedEvent,
    ConnectionStartedEvent,
    ConnectionSuccessEvent,
)
from eylo.listeners.py_events.utils import broadcast_to_contact
from eylo.modules.integrations_v2.schemas.websocket import (
    WsConnectionExpired,
    WsConnectionFailed,
    WsConnectionStarted,
    WsConnectionSuccess,
)
from eylo.pipelines.websocket.schemas import WsEventAction

logger = logging.getLogger(__name__)


async def broadcast_connection_started(event: ConnectionStartedEvent) -> None:
    """Broadcast CONNECTION_STARTED event to the contact who initiated OAuth flow.

    This sends a WebSocket event to notify the widget that OAuth flow has begun.
    """
    logger.info(
        "[broadcast_connection_started] OAuth flow started for integration %s "
        "(contact=%s)",
        event.integration_id,
        event.contact_id,
    )

    await broadcast_to_contact(
        contact_id=event.contact_id,
        organization_id=event.organization_id,
        kind=WsEventAction.CONNECTION_STARTED,
        payload=WsConnectionStarted(
            integration_id=event.integration_id,
            vendor=event.vendor,
            contact_id=event.contact_id,
        ).model_dump(mode="json"),
        event_name=WsEventAction.CONNECTION_STARTED.name,
    )


async def broadcast_connection_success(event: ConnectionSuccessEvent) -> None:
    """Broadcast CONNECTION_SUCCESS event to the contact who completed OAuth flow.

    This sends a WebSocket event to notify the widget that connection succeeded.
    """
    logger.info(
        f"[broadcast_connection_success] Connection {event.connection_id} established "
        f"for {event.integration_name} (contact={event.contact_id})"
    )

    payload = WsConnectionSuccess(
        connection_id=event.connection_id,
        integration_id=event.integration_id,
        integration_name=event.integration_name,
        vendor=event.vendor,
    )

    await broadcast_to_contact(
        contact_id=event.contact_id,
        organization_id=event.organization_id,
        kind=WsEventAction.CONNECTION_SUCCESS,
        payload=payload.model_dump(mode="json"),
        event_name=WsEventAction.CONNECTION_SUCCESS.name,
    )


async def broadcast_connection_failed(event: ConnectionFailedEvent) -> None:
    """Broadcast CONNECTION_FAILED event to the contact whose OAuth flow failed.

    This sends a WebSocket event to notify the widget that connection failed.
    """
    logger.info(
        f"[broadcast_connection_failed] Connection failed for {event.integration_name} "
        f"(contact={event.contact_id})"
    )

    payload = WsConnectionFailed(
        error=event.error,
        integration_id=event.integration_id,
        integration_name=event.integration_name,
        vendor=event.vendor,
    )

    await broadcast_to_contact(
        contact_id=event.contact_id,
        organization_id=event.organization_id,
        kind=WsEventAction.CONNECTION_FAILED,
        payload=payload.model_dump(mode="json"),
        event_name=WsEventAction.CONNECTION_FAILED.name,
    )


async def broadcast_connection_expired(event: ConnectionExpiredEvent) -> None:
    """Broadcast connection expired notification to the user.

    When token refresh is exhausted, emit AUTH_REQUIRED to show
    the reconnection panel in the widget UI.

    Args:
        event: ConnectionExpiredEvent with connection details

    """
    logger.info(
        f"Connection expired for connection_id={event.connection_id}, "
        f"reason={event.reason}. Broadcasting AUTH_REQUIRED to contact."
    )

    # Broadcast to the user who needs to reconnect (org-level connections have no contact)
    if not event.contact_id:
        logger.warning(
            "Cannot broadcast AUTH_REQUIRED for org-level connection %s — no contact_id",
            event.connection_id,
        )
        return

    auth_required_payload = WsConnectionExpired(
        connection_id=event.connection_id,
        integration_id=event.integration_id,
        vendor=event.vendor,
        integration_name=event.vendor,
        reason=event.reason,
    )

    await broadcast_to_contact(
        contact_id=event.contact_id,
        organization_id=event.organization_id,
        kind=WsEventAction.AUTH_REQUIRED,
        payload=auth_required_payload.model_dump(mode="json"),
        event_name=WsEventAction.AUTH_REQUIRED.name,
    )

    logger.info(
        f"AUTH_REQUIRED broadcast complete for connection_id={event.connection_id}"
    )
