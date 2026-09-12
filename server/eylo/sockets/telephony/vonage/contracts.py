"""Consumed Vonage Voice v1 REST and NCCO contracts, private to this carrier."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

VOICE_ORIGIN = "https://api.nexmo.com"
CALLS_URL = f"{VOICE_ORIGIN}/v1/calls"
REQUEST_TIMEOUT_SECONDS = 20
CREATE_OPERATION = "telephony.vonage.call.create"


class MediaContentType(StrEnum):
    PCM16_16KHZ = "audio/l16;rate=16000"


class EndpointKind(StrEnum):
    PHONE = "phone"
    WEBSOCKET = "websocket"


class ActionKind(StrEnum):
    CONNECT = "connect"
    HANGUP = "hangup"
    TRANSFER = "transfer"


class DestinationKind(StrEnum):
    NCCO = "ncco"


class CreateStatus(StrEnum):
    STARTED = "started"


class CreateFailureCode(StrEnum):
    NOT_CONFIGURED = "call_create_not_configured"
    REJECTED = "call_create_rejected"
    UNCONFIRMED = "call_create_unconfirmed"
    RESPONSE_INVALID = "call_create_response_invalid"


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True,
    )


class PhoneEndpoint(_WireValue):
    type: Literal[EndpointKind.PHONE] = EndpointKind.PHONE
    number: str = Field(repr=False)


class WebSocketEndpoint(_WireValue):
    type: Literal[EndpointKind.WEBSOCKET] = EndpointKind.WEBSOCKET
    uri: str = Field(repr=False)
    content_type: Literal[MediaContentType.PCM16_16KHZ] = Field(
        default=MediaContentType.PCM16_16KHZ, serialization_alias="content-type",
    )
    headers: dict[str, str] = Field(default_factory=dict, repr=False)


type Endpoint = Annotated[PhoneEndpoint | WebSocketEndpoint, Field(discriminator="type")]


class ConnectAction(_WireValue):
    """Only the NCCO action Eylo currently produces, not an unrestricted NCCO DSL."""

    action: Literal[ActionKind.CONNECT] = ActionKind.CONNECT
    endpoint: list[Endpoint]


class CreateCallRequest(_WireValue):
    to: list[PhoneEndpoint]
    from_endpoint: PhoneEndpoint = Field(serialization_alias="from")
    ncco: list[ConnectAction]
    event_url: list[str] | None = Field(default=None, repr=False)


class CreateCallResponse(_WireValue):
    """Only a started response with a usable ID establishes create acceptance."""

    model_config = ConfigDict(extra="ignore")

    uuid: str
    status: Literal[CreateStatus.STARTED]


class HangupRequest(_WireValue):
    action: Literal[ActionKind.HANGUP] = ActionKind.HANGUP


class DtmfRequest(_WireValue):
    digits: str = Field(repr=False)


class NccoDestination(_WireValue):
    type: Literal[DestinationKind.NCCO] = DestinationKind.NCCO
    ncco: list[ConnectAction]


class TransferRequest(_WireValue):
    action: Literal[ActionKind.TRANSFER] = ActionKind.TRANSFER
    destination: NccoDestination
