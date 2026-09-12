"""Serialize validated server envelopes without accepting arbitrary model objects."""

import json
from collections.abc import Mapping

from eylo.common.contracts.websocket import WsResponse
from eylo.common.contracts.websocket_payloads import (
    WsProjectionValue,
    project_ws_object,
)

type WsTextPayload = str | WsResponse | Mapping[str, WsProjectionValue]
type WsOutboundPayload = WsTextPayload | bytes


def serialize_ws_text(payload: WsTextPayload) -> str:
    """Revalidate mutable/copy-built responses; preserve aliases and timestamp encoding."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, WsResponse):
        response = WsResponse.model_validate(payload)
        data = project_ws_object(response.model_dump(mode="python", by_alias=True))
    else:
        data = project_ws_object(payload)
    return json.dumps(data, allow_nan=False)
