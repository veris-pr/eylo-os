"""Forward WebSocket audio frames into the active voice pipeline."""

from eylo.audio.ops import is_silent
from eylo.modules.session_context.schemas import SessionContext
from eylo.pipelines.voice.browser import handle_audio_config as handle_audio_config
from eylo.pipelines.websocket.audio_frame import WsBinaryAudioRequest
from eylo.pipelines.websocket.handlers.error import handle_error
from eylo.pipelines.websocket.schemas import (
    WsRequestEvent,
    WsResponse,
)
from eylo.pipelines.websocket.session_state import resolve_websocket_state

from .log import logger

MIN_AUDIO_BYTES_PER_RATE = 0.01


async def handle_audio_data(
    event: WsRequestEvent | WsBinaryAudioRequest, ctx: SessionContext
) -> WsResponse | None:
    """Route binary audio through the configured session; never infer a vendor."""
    if not isinstance(event, WsBinaryAudioRequest):
        message = "Expected binary data" if event.data else "No audio data payload"
        return await handle_error(event=event, ctx=ctx, message=message)

    audio_data = event.audio_data
    if not audio_data:
        return await handle_error(
            event=event,
            ctx=ctx,
            message="Expected binary data",
        )

    state = resolve_websocket_state(ctx)
    if state is None:
        return await handle_error(
            event=event, ctx=ctx, message="Voice session is unavailable"
        )

    if state.realtime_mode and state.realtime_manager:
        await state.realtime_manager.send_audio(audio_data)
        return

    # detect if the binary data is all zeros (C-level scan via audio_ops)
    if is_silent(audio_data):
        return
    if len(audio_data) < MIN_AUDIO_BYTES_PER_RATE * state.stt_encoding_info.sample_rate:
        return await handle_error(
            event=event,
            ctx=ctx,
            message="Audio data is too short or silent",
        )

    if not state.stt_started or not state.stt_socket:
        logger.warning(
            "STT not ready, dropping audio packet, stt_started: %s, stt_socket: %s",
            state.stt_started,
            state.stt_socket,
        )
        return

    # Non-blocking recording tap (instant bytearray extend)
    if state.audio_recorder:
        state.audio_recorder.record_user(audio_data)

    await state.stt_socket.send_audio(audio_data)
