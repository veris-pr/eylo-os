"""Request-body sanitization middleware."""

import json

import nh3 as bleach
from fastapi import Request
from pydantic import JsonValue
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

_SIGNED_WEBHOOK_PATH_PREFIX = "/api/sor/webhooks/"


class BleachSanitizeBodyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        preserves_signed_body = request.url.path.startswith(
            _SIGNED_WEBHOOK_PATH_PREFIX
        )
        if (
            request.method in ("POST", "PUT", "PATCH")
            and not preserves_signed_body
        ):
            try:
                body: JsonValue = await request.json()
                sanitized = self._sanitize_dict(body)
                # Set sanitized body for downstream usage
                request._body = json.dumps(sanitized).encode("utf-8")
            except Exception:
                # Silent fail for non-JSON or empty bodies
                pass
        response = await call_next(request)
        return response

    def _sanitize_dict(self, data: JsonValue) -> JsonValue:
        if isinstance(data, dict):
            return {k: self._sanitize_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_dict(item) for item in data]
        elif isinstance(data, str):
            return bleach.clean(data)
        else:
            return data
