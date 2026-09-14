"""Public provider callback for SOR OAuth authorization."""

from __future__ import annotations

import html
import json

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from eylo.sor.runtime.oauth import (
    SOR_OAUTH_CALLBACK_PATH,
    SorOAuthError,
    complete_sor_authorization_from_state,
    decline_sor_authorization,
)

router = APIRouter(tags=["systems-of-record"])


@router.get(SOR_OAUTH_CALLBACK_PATH, response_class=HTMLResponse)
async def complete_sor_authorization(
    state: str = Query(min_length=1, max_length=256),
    code: str | None = Query(default=None, max_length=8192),
    error: str | None = Query(default=None, max_length=512),
) -> HTMLResponse:
    """Consume provider state and activate its exact SOR external connection."""
    if error is not None:
        await decline_sor_authorization(state=state)
        return _completion_page(
            ok=False,
            message="Authorization was declined at the provider.",
        )
    if code is None:
        await decline_sor_authorization(state=state)
        return _completion_page(
            ok=False,
            message="The provider returned no authorization code.",
        )
    try:
        result = await complete_sor_authorization_from_state(
            code=code,
            state=state,
        )
    except (KeyError, SorOAuthError) as failure:
        return _completion_page(ok=False, message=str(failure))
    return _completion_page(
        ok=True,
        message=f"{result.vendor_key} is connected.",
        connection_id=str(result.connection_id),
        vendor=result.vendor_key,
    )


def _completion_page(
    *,
    ok: bool,
    message: str,
    connection_id: str | None = None,
    vendor: str | None = None,
) -> HTMLResponse:
    """Return a minimal completion page and notify the operator console."""
    safe_message = html.escape(message)
    status_text = "Connected" if ok else "Not connected"
    post_message = json.dumps(
        {
            "type": "eylo:sor-oauth",
            "ok": ok,
            "connectionId": connection_id,
            "vendor": vendor,
            "error": None if ok else message[:500],
        }
    ).replace("</", "<\\/")
    return HTMLResponse(
        status_code=200 if ok else 400,
        content=(
            "<!doctype html><meta charset='utf-8'>"
            f"<title>{status_text}</title>"
            '<body style="font:16px system-ui;margin:3rem;text-align:center">'
            f"<h1>{status_text}</h1><p>{safe_message}</p>"
            "<p>You can close this window.</p>"
            "<script>if(window.opener){window.opener.postMessage("
            f"{post_message},'*');"
            "setTimeout(function(){window.close()},2000);}</script>"
            "</body>"
        ),
    )


__all__ = ["router"]
