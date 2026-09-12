"""Plivo answer XML serialization independent of credentials or call effects."""

from urllib.parse import urlencode

from plivo import plivoxml

from eylo.sockets.telephony.plivo.stream_contracts import MULAW_SAMPLE_RATE, ContentType
from eylo.sockets.telephony.stream_parameters import StreamParameters

STREAM_CONTENT_TYPE = f"{ContentType.MULAW.value};rate={MULAW_SAMPLE_RATE}"


def render_stream_xml(ws_url: str, custom_params: StreamParameters) -> str:
    """Encode an approved stream target with native SDK booleans and XML escaping."""
    parameters = custom_params.as_wire()
    final_url = ws_url
    if parameters:
        separator = "&" if "?" in ws_url else "?"
        final_url = f"{ws_url}{separator}{urlencode(parameters)}"
    response = plivoxml.ResponseElement()
    response.add(
        plivoxml.StreamElement(
            final_url,
            bidirectional=True,
            keepCallAlive=True,
            contentType=STREAM_CONTENT_TYPE,
        )
    )
    return response.to_string()
