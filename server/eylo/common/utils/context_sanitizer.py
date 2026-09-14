"""Bound validated client JSON and strip HTML before model context projection.

HTML stripping is not a prompt-injection defense. The prompt owner must still
present this customer-controlled context as untrusted data, not instructions.
"""

import json
import logging
import math

import nh3
from pydantic import JsonValue

logger = logging.getLogger(__name__)

MAX_CONTEXT_BYTES = 262_144  # 256 KB serialized
MAX_KEYS = 500
MAX_DEPTH = 6
MAX_STRING_VALUE_LENGTH = 1000
MAX_KEY_LENGTH = 100


def sanitize_context(
    context: dict[str, JsonValue] | None,
) -> dict[str, JsonValue] | None:
    """Return bounded context without mutation; invalid JSON values are refused."""
    if not context or not isinstance(context, dict):
        return None

    sanitized = _sanitize_value(context, depth=0)
    if not isinstance(sanitized, dict):
        return None

    # Enforce total serialized size by dropping trailing keys
    serialized = json.dumps(sanitized, allow_nan=False)
    if len(serialized) > MAX_CONTEXT_BYTES:
        original_size = len(serialized)
        keys = list(sanitized.keys())
        dropped_count = 0
        while len(json.dumps(sanitized, allow_nan=False)) > MAX_CONTEXT_BYTES and keys:
            dropped_key = keys.pop()
            sanitized.pop(dropped_key)
            dropped_count += 1
        logger.warning(
            "Context exceeded %d bytes (%d bytes). Dropped %d keys",
            MAX_CONTEXT_BYTES,
            original_size,
            dropped_count,
        )
        if not sanitized:
            return None

    return sanitized


def _sanitize_value(value: JsonValue, depth: int) -> JsonValue:
    """Recursively sanitize a value, enforcing type and depth limits."""
    if depth > MAX_DEPTH:
        logger.debug("Depth limit (%d) reached — truncating nested data", MAX_DEPTH)
        return "[nested data truncated]"

    if value is None or isinstance(value, bool):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Context numbers must be finite.")
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, str):
        cleaned = nh3.clean(value, tags=set())
        if cleaned != value:
            logger.debug("Context HTML tags stripped")
        if len(cleaned) > MAX_STRING_VALUE_LENGTH:
            logger.debug(
                "Context string truncated: %d → %d chars",
                len(cleaned),
                MAX_STRING_VALUE_LENGTH,
            )
            return cleaned[:MAX_STRING_VALUE_LENGTH] + "…"
        return cleaned

    if isinstance(value, dict):
        sanitized: dict[str, JsonValue] = {}
        total_keys = len(value)
        for i, (k, v) in enumerate(value.items()):
            if i >= MAX_KEYS:
                logger.warning(
                    "Key limit (%d) reached — dropped %d keys",
                    MAX_KEYS,
                    total_keys - MAX_KEYS,
                )
                break
            key = k[:MAX_KEY_LENGTH]
            if len(k) > MAX_KEY_LENGTH:
                logger.debug("Context key name truncated")
            sanitized[key] = _sanitize_value(v, depth + 1)
        return sanitized

    if isinstance(value, list):
        total_items = len(value)
        if total_items > MAX_KEYS:
            logger.warning(
                "List limit (%d) reached — dropped %d items",
                MAX_KEYS,
                total_items - MAX_KEYS,
            )
        return [_sanitize_value(item, depth + 1) for item in value[:MAX_KEYS]]

    raise ValueError("Context values must be JSON.")
