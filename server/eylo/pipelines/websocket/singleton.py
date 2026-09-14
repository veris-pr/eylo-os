"""Process-local runtime access for the `websocket` pipeline."""

from eylo.pipelines.websocket.manager import WsConnectionManager

S_ws_manager = WsConnectionManager()


async def start_websocket_manager() -> None:
    """Start the WebSocket manager's background tasks."""
    await S_ws_manager.start_background_tasks()


async def stop_websocket_manager() -> None:
    """Stop the WebSocket manager's background tasks."""
    await S_ws_manager.stop_background_tasks()


__all__ = [
    "start_websocket_manager",
    "stop_websocket_manager",
]
