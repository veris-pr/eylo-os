"""Strict conversion of provider credential payloads into aiortc values."""

from __future__ import annotations

from aiortc import RTCIceServer
from pydantic import ValidationError

from eylo.sockets.stun_turn.exceptions import StunTurnCredentialsFailed
from eylo.sockets.stun_turn.wire import IceCredentials


def parse_ice_servers(payload: object) -> list[RTCIceServer]:
    """Accept provider list/envelope shapes and require at least one TURN URL."""
    try:
        response = IceCredentials.model_validate(payload)
    except ValidationError:
        raise StunTurnCredentialsFailed(
            "TURN provider returned invalid credentials."
        ) from None
    return [
        RTCIceServer(
            urls=list(server.urls),
            username=server.username,
            credential=server.credential,
        )
        for server in response.ice_servers
    ]
