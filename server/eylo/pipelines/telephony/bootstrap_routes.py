"""Public carrier answer requests authorized by Eylo's outbound media token."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from eylo.common.config import settings
from eylo.pipelines.telephony.outbound_stream import OutboundMediaRouting
from eylo.sockets.telephony.plivo.bootstrap import render_stream_xml
from eylo.sockets.telephony.stream_parameters import StreamParameters

router = APIRouter()


class CarrierXmlResponse(PlainTextResponse):
    """Keep the runtime and generated API response media types aligned."""

    media_type = "application/xml"


@router.get("/voice/plivo/answer", response_class=CarrierXmlResponse)
@router.post("/voice/plivo/answer", response_class=CarrierXmlResponse)
async def plivo_answer(ws_url: str) -> CarrierXmlResponse:
    """Validate signature and our configured target without consuming the media claim."""
    server_domain = settings.SERVER_DOMAIN
    if not server_domain:
        raise HTTPException(
            status_code=503, detail="Carrier media endpoint is not configured."
        )
    try:
        routing = OutboundMediaRouting.from_plivo_answer_url(
            ws_url, server_domain=server_domain
        )
    except ValueError as error:
        raise HTTPException(
            status_code=403, detail="Carrier media authorization failed."
        ) from error
    xml = render_stream_xml(
        routing.websocket_url(server_domain), StreamParameters(values={})
    )
    return CarrierXmlResponse(content=xml, headers={"Cache-Control": "no-store"})
