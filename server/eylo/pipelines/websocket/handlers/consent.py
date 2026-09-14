"""Apply recording-consent events to the active voice session."""

from eylo.common.contracts.websocket import WsRequestEvent, WsResponse
from eylo.modules.session_context.schemas import SessionContext
from eylo.pipelines.voice.consent import handle_recording_consent_event


async def handle_recording_consent(event: WsRequestEvent, ctx: SessionContext) -> WsResponse:
    return await handle_recording_consent_event(event, ctx)
