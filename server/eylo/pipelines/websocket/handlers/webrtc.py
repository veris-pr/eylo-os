"""Authenticated WebRTC signaling commands."""

from typing import Optional
from uuid import UUID

from fastapi import status

from eylo.common.contracts.voice import BrowserVoiceTerminationReason
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.modules.session_context.schemas import SessionContext
from eylo.pipelines.voice.browser import terminate_browser_voice
from eylo.pipelines.webrtc.errors import WebRTCFailureCode, WebRTCSignalingCode
from eylo.pipelines.webrtc.requests import WebRTCPrepareRequest
from eylo.pipelines.webrtc.schemas import (
    WebRTCHangupAccepted,
    WebRTCNotConfigured,
    WebRTCRejected,
    WebRTCResponse,
    WebRTCSignalCommand,
)
from eylo.pipelines.webrtc.signaling_manager import (
    WebRTCSignalingError,
)
from eylo.pipelines.webrtc.singleton import S_webrtc_signaling
from eylo.pipelines.websocket.schemas import (
    WsEventAction,
    WsRequestEvent,
    WsResponse,
)

from .log import logger


async def handle_webrtc_prepare(
    event: WsRequestEvent, ctx: SessionContext
) -> Optional[WsResponse]:
    """Prepare exact org ICE config before the browser creates a peer."""
    try:
        WebRTCPrepareRequest.from_payload(event.data or {})
    except WebRTCSignalingError as error:
        return _rejected(
            event,
            ctx,
            WsEventAction.WEBRTC_PREPARE,
            error.code,
        )
    try:
        data = await S_webrtc_signaling.prepare_session(
            ctx.organization_id,
            ctx.session_id,
        )
        return _response(event, ctx, WsEventAction.WEBRTC_PREPARE, data)
    except NotConfiguredError as error:
        return _response(
            event,
            ctx,
            WsEventAction.WEBRTC_PREPARE,
            WebRTCNotConfigured(
                capability=error.capability,
                missing=tuple(error.missing),
                configure_via=error.configure_via,
            ),
            response_status=status.HTTP_409_CONFLICT,
        )
    except WebRTCSignalingError as error:
        return _rejected(event, ctx, WsEventAction.WEBRTC_PREPARE, error.code)
    except Exception as error:
        _log_failure(ctx.organization_id, WebRTCSignalCommand.PREPARE, error)
        return _rejected(
            event,
            ctx,
            WsEventAction.WEBRTC_PREPARE,
            WebRTCSignalingCode.PREPARE_FAILED,
        )


async def handle_webrtc_offer(
    event: WsRequestEvent, ctx: SessionContext
) -> Optional[WsResponse]:
    """Acquire and answer one correlated browser offer."""
    try:
        await S_webrtc_signaling.handle_offer(
            ctx.organization_id,
            ctx.session_id,
            event,
        )
        return None
    except WebRTCSignalingError as error:
        return _rejected(event, ctx, WsEventAction.WEBRTC_ANSWER, error.code)
    except Exception as error:
        _log_failure(ctx.organization_id, WebRTCSignalCommand.OFFER, error)
        return _rejected(
            event,
            ctx,
            WsEventAction.WEBRTC_ANSWER,
            WebRTCSignalingCode.OFFER_FAILED,
        )


async def handle_webrtc_ice_candidate(
    event: WsRequestEvent, ctx: SessionContext
) -> Optional[WsResponse]:
    """Apply one policy-admitted, correlated remote candidate."""
    try:
        data = await S_webrtc_signaling.handle_candidate(
            ctx.organization_id,
            ctx.session_id,
            event,
        )
        return _response(event, ctx, WsEventAction.WEBRTC_ICE_CANDIDATE, data)
    except WebRTCSignalingError as error:
        return _rejected(
            event,
            ctx,
            WsEventAction.WEBRTC_ICE_CANDIDATE,
            error.code,
        )
    except Exception as error:
        _log_failure(ctx.organization_id, WebRTCSignalCommand.CANDIDATE, error)
        return _rejected(
            event,
            ctx,
            WsEventAction.WEBRTC_ICE_CANDIDATE,
            WebRTCSignalingCode.CANDIDATE_FAILED,
        )


async def handle_webrtc_hangup(
    event: WsRequestEvent, ctx: SessionContext
) -> Optional[WsResponse]:
    """Run the one idempotent terminal command for a browser hangup."""
    terminated = await terminate_browser_voice(
        ctx,
        reason=BrowserVoiceTerminationReason.CLIENT_HANGUP,
        notify_client=False,
    )
    return _response(
        event,
        ctx,
        WsEventAction.WEBRTC_HANGUP,
        WebRTCHangupAccepted(already_terminated=not terminated),
    )


def _rejected(
    event: WsRequestEvent,
    ctx: SessionContext,
    kind: WsEventAction,
    code: WebRTCFailureCode,
) -> WsResponse:
    command = _COMMANDS[kind]
    return _response(
        event,
        ctx,
        kind,
        WebRTCRejected(command=command, code=code),
        response_status=status.HTTP_409_CONFLICT,
    )


def _response(
    event: WsRequestEvent,
    ctx: SessionContext,
    kind: WsEventAction,
    data: WebRTCResponse,
    *,
    response_status: int = status.HTTP_200_OK,
) -> WsResponse:
    return WsResponse(
        status=response_status,
        kind=kind,
        organization_id=ctx.organization_id,
        session_id=ctx.session_id,
        request_id=event.request_id,
        data=data.model_dump(mode="json", by_alias=True),
    )


_COMMANDS = {
    WsEventAction.WEBRTC_PREPARE: WebRTCSignalCommand.PREPARE,
    WsEventAction.WEBRTC_ANSWER: WebRTCSignalCommand.ANSWER,
    WsEventAction.WEBRTC_ICE_CANDIDATE: WebRTCSignalCommand.ICE_CANDIDATE,
    WsEventAction.WEBRTC_HANGUP: WebRTCSignalCommand.HANGUP,
}


def _log_failure(
    organization_id: UUID, command: WebRTCSignalCommand, error: Exception
) -> None:
    logger.warning(
        "WebRTC command failed organization_id=%s command=%s category=%s",
        organization_id,
        command,
        type(error).__name__,
    )
