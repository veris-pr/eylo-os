"""Async cache decorator backed by Redis.

Usage:
    @async_cache_for(timeout=300)
    async def fetch_weather(city: str, date: str) -> dict:
        ...

Cache key is built from the function name + all args/kwargs, hashed
with MD5. If the same function is called with identical parameters
within the TTL window, the cached result is returned.

Designed for the tools layer — tool calls with identical parameters
return cached results instead of re-executing.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, JsonValue

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "eylo:fn_cache"
_DEFAULT_CACHE_TTL_SECONDS = 300


class _CacheEntry(BaseModel):
    """Redis's existing value envelope; malformed entries become cache misses."""

    model_config = ConfigDict(frozen=True, strict=True)

    v: JsonValue


def _build_cache_key(fn_name: str, *args: object, **kwargs: object) -> str:
    """Build a deterministic Redis key from function name + arguments.

    Uses JSON serialization (sorted keys) for consistent ordering,
    falls back to str() for non-serializable objects.
    """
    parts: list[str] = [fn_name]
    for arg in args:
        try:
            parts.append(json.dumps(arg, sort_keys=True, default=str))
        except (TypeError, ValueError):
            parts.append(str(arg))
    for key in sorted(kwargs):
        parts.append(key)
        try:
            parts.append(json.dumps(kwargs[key], sort_keys=True, default=str))
        except (TypeError, ValueError):
            parts.append(str(kwargs[key]))

    digest = hashlib.md5("|".join(parts).encode()).hexdigest()
    return f"{_CACHE_PREFIX}:{fn_name}:{digest}"


def async_cache_for[**Parameters](
    timeout: int = _DEFAULT_CACHE_TTL_SECONDS,
    ignore_params: tuple[str, ...] = (),
) -> Callable[
    [Callable[Parameters, Awaitable[JsonValue]]],
    Callable[Parameters, Awaitable[JsonValue]],
]:
    """Decorator that caches async function results in Redis.

    Args:
        timeout: TTL in seconds (default 300 = 5 minutes).
        ignore_params: Keyword argument names to exclude from the cache key
            (e.g., 'ctx' which changes every call but doesn't affect output).

    """

    def decorator(
        fn: Callable[Parameters, Awaitable[JsonValue]],
    ) -> Callable[Parameters, Awaitable[JsonValue]]:
        @functools.wraps(fn)
        async def wrapper(*args: Parameters.args, **kwargs: Parameters.kwargs) -> JsonValue:
            # Filter out ignored params for key generation
            cache_kwargs = {k: v for k, v in kwargs.items() if k not in ignore_params}
            key = _build_cache_key(
                f"{fn.__module__}.{fn.__qualname__}", *args, **cache_kwargs
            )

            try:
                from eylo.common.redis import get_redis_client

                client = get_redis_client()
                cached = await client.get(key)
                if cached is not None:
                    logger.debug("Cache hit: %s", key)
                    return _CacheEntry.model_validate_json(cached).v
            except Exception:
                # Redis down → skip cache, execute function
                logger.debug("Cache read failed for %s, executing function", key)

            result = await fn(*args, **kwargs)

            try:
                from eylo.common.redis import get_redis_client

                client = get_redis_client()
                await client.set(
                    key, json.dumps({"v": result}, default=str), ex=timeout
                )
            except Exception:
                logger.debug("Cache write failed for %s", key)

            return result

        return wrapper

    return decorator
