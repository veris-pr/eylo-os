"""Resolve live transport resources without widening the module-owned port."""

from eylo.modules.session_context.schemas import SessionContext
from eylo.pipelines.websocket.schemas import WSSessionState


def resolve_websocket_state(ctx: SessionContext) -> WSSessionState | None:
    """Preserve the actual resource holder; a foreign port is a wiring error."""
    state = ctx.ws
    if state is None or isinstance(state, WSSessionState):
        return state
    raise TypeError("WebSocket pipeline requires WSSessionState.")


def require_websocket_state(ctx: SessionContext) -> WSSessionState:
    """Startup needs live state; only optional teardown accepts absence."""
    state = resolve_websocket_state(ctx)
    if state is None:
        raise RuntimeError("WebSocket pipeline requires a session.")
    return state
