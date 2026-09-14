"""SessionContextHydrator — builds SessionContext at each interface boundary.

Stateless factory: no dependencies, pure construction logic.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from eylo.common.contracts.session_state import (
    TelephonySessionStatePort,
    WebRTCSessionStatePort,
    WebSocketSessionStatePort,
)
from eylo.modules.auth.schemas import AuthSessionInDb
from eylo.modules.session_context.schemas import (
    SessionChannel,
    SessionContext,
)


class SessionContextHydrator:
    """Builds SessionContext at each interface boundary.

    Stateless — no dependencies, pure construction logic.
    """

    @staticmethod
    def for_http(
        organization_id: UUID,
        session_id: str,
        contact_id: UUID,
        authorized_agent_id: Optional[UUID] = None,
        authorized_agent_revision: Optional[int] = None,
        authorized_conversation_id: Optional[UUID] = None,
        auth_session: Optional[AuthSessionInDb] = None,
        voice_session_id: Optional[UUID] = None,
    ) -> SessionContext:
        """Build SessionContext for HTTP widget API requests.

        Called from: get_session_context() FastAPI dependency.
        Hydrates: auth + identity fields only (no WS/call/webrtc).
        """
        return SessionContext(
            channel=SessionChannel.HTTP,
            organization_id=organization_id,
            session_id=session_id,
            user_session_id=None,
            contact_id=contact_id,
            voice_session_id=voice_session_id,
            authorized_agent_id=authorized_agent_id,
            authorized_agent_revision=authorized_agent_revision,
            authorized_conversation_id=authorized_conversation_id,
            auth=auth_session,
        )

    @staticmethod
    def for_websocket(
        auth_session: AuthSessionInDb,
        ws_state: WebSocketSessionStatePort,
        authorized_agent_id: Optional[UUID] = None,
        authorized_agent_revision: Optional[int] = None,
        authorized_conversation_id: Optional[UUID] = None,
        voice_session_id: Optional[UUID] = None,
    ) -> SessionContext:
        """Build SessionContext for browser WebSocket connections.

        Called from: WebSocketController.handle_connection(), after
        validate_session_token() + S_ws_manager.connect().

        Hydrates: auth + ws.
        """
        return SessionContext(
            channel=SessionChannel.WEBSOCKET,
            organization_id=auth_session.organization_id,
            session_id=ws_state.session_id,
            user_session_id=ws_state.user_session_id,
            contact_id=ws_state.contact_id,
            voice_session_id=voice_session_id or ws_state.voice_session_id,
            authorized_agent_id=authorized_agent_id,
            authorized_agent_revision=authorized_agent_revision,
            authorized_conversation_id=authorized_conversation_id,
            auth=auth_session,
            ws=ws_state,
        )

    @staticmethod
    def for_telephony(
        auth_session: AuthSessionInDb,
        ws_state: WebSocketSessionStatePort,
        call_session: TelephonySessionStatePort,
        voice_session_id: Optional[UUID] = None,
    ) -> SessionContext:
        """Compose already-authorized auth, WebSocket and call state.

        Explicit voice identity takes precedence over call and WebSocket facts.
        Construction does not acquire, authenticate or close any resource.
        """
        return SessionContext(
            channel=SessionChannel.TELEPHONY,
            organization_id=auth_session.organization_id,
            session_id=ws_state.session_id,
            user_session_id=(call_session.user_session_id or ws_state.user_session_id),
            contact_id=ws_state.contact_id,
            voice_session_id=(
                voice_session_id
                or call_session.voice_session_id
                or ws_state.voice_session_id
            ),
            auth=auth_session,
            ws=ws_state,
            call=call_session,
        )

    @staticmethod
    def for_webrtc(
        existing_ctx: SessionContext,
        webrtc_session: WebRTCSessionStatePort,
    ) -> SessionContext:
        """Add an already-authorized peer without changing inherited authority.

        Reconstruct through validation, preserving live object identity. Do not
        use model_copy(update=...) or serialize runtime resources to rebuild.
        The caller owns peer authorization and resource lifetime.
        """
        return SessionContext(
            channel=SessionChannel.WEBRTC,
            organization_id=existing_ctx.organization_id,
            session_id=existing_ctx.session_id,
            user_session_id=existing_ctx.user_session_id,
            contact_id=existing_ctx.contact_id,
            voice_session_id=existing_ctx.voice_session_id,
            authorized_agent_id=existing_ctx.authorized_agent_id,
            authorized_agent_revision=existing_ctx.authorized_agent_revision,
            authorized_conversation_id=existing_ctx.authorized_conversation_id,
            auth=existing_ctx.auth,
            ws=existing_ctx.ws,
            call=existing_ctx.call,
            webrtc=webrtc_session,
        )
