"""Application services for the `tools` domain."""

import asyncio
import logging
import random
from typing import Any

from .mock_responses import MOCK_TOOL_RESPONSES

logger = logging.getLogger(__name__)


class MockToolStatusError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class MockToolServerError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


async def execute_mock_tool(tool_slug: str) -> Any:
    logger.info("Executing mock tool for slug '%s'", tool_slug)
    response = MOCK_TOOL_RESPONSES.get(tool_slug)
    if response is None:
        logger.error("No mock response configured for '%s'", tool_slug)
        raise KeyError(f"Mock response missing for {tool_slug}")

    delay = random.uniform(0.2, 10.0)
    await asyncio.sleep(delay)
    logger.debug("Mock tool '%s' slept for %.2f seconds", tool_slug, delay)

    try:
        # Randomly raise a server error
        if random.random() < 0.2:
            # Randomly raise a status error
            if random.random() < 0.5:
                raise MockToolStatusError(422, "Mock validation failure")
            raise MockToolServerError("Mock upstream timeout")

        logger.info("Returning mock response for '%s'", tool_slug)
        return {"success": True, "data": response}

    except MockToolStatusError as exc:
        logger.warning(
            "Mock status error raised tool=%s error_type=%s",
            tool_slug,
            type(exc).__name__,
        )
        return {
            "type": "status_error",
            "status_code": exc.status_code,
            "message": exc.message,
        }
    except MockToolServerError as exc:
        logger.error(
            "Mock server error raised tool=%s error_type=%s",
            tool_slug,
            type(exc).__name__,
        )
        return {
            "type": "server_error",
            "message": exc.message,
        }
