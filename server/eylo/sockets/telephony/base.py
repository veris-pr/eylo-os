"""Base classes and protocols for telephony providers.

This module defines the abstract interfaces that all telephony providers must implement,
enabling a pluggable architecture for different vendors (Twilio, Plivo, Exotel, etc.).
"""

from abc import ABC, abstractmethod
from enum import Enum, StrEnum
from typing import Any, Dict, Literal, Optional, Protocol, Self, TypeAlias
from uuid import UUID

from fastapi import WebSocket
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eylo.common.contracts.speech_runtime import SpeechTransportFormat
from eylo.common.contracts.telephony import CallEndedReason as CallEndedReason
from eylo.common.outbound import (
    OUTBOUND_STATUS_CODE_MAX,
    OUTBOUND_STATUS_CODE_MIN,
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendRetryable,
    OutboundSendTerminal,
    OutboundSendUnknown,
    OutboundTransportKind,
)
from eylo.sockets.telephony.config import SettingsT, TelephonyVendorSettings
from eylo.sockets.telephony.config import TelephonyProvider as TelephonyProvider


class AudioEncoding(str, Enum):
    """Audio encoding formats for telephony."""

    MULAW = "mulaw"
    ALAW = "alaw"
    LINEAR16 = "linear16"  # PCM LINEAR16 (Vonage)
    PCM_S16LE = "pcm_s16le"
    PCM_MULAW = "pcm_mulaw"


TELEPHONY_SAMPLE_RATE = 8000
TELEPHONY_CHANNELS = 1


class _TelephonyValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )


class CarrierAudioContainer(StrEnum):
    RAW = "raw"


class CarrierAudioFormat(_TelephonyValue):
    """Target media for a carrier, not a claim about a TTS vendor's output."""

    container: Literal[CarrierAudioContainer.RAW] = CarrierAudioContainer.RAW
    encoding: Literal[AudioEncoding.PCM_S16LE, AudioEncoding.PCM_MULAW]
    sample_rate: int = Field(gt=0)


class TelephonyConfig(_TelephonyValue):
    """Resolved carrier settings and media format for one adapter instance."""

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    settings: TelephonyVendorSettings = Field(repr=False, exclude=True)
    encoding: AudioEncoding = AudioEncoding.MULAW
    sample_rate: int = Field(default=TELEPHONY_SAMPLE_RATE, gt=0)
    channels: int = Field(default=TELEPHONY_CHANNELS, gt=0)

    @property
    def provider(self) -> TelephonyProvider:
        return self.settings.provider

    def require_settings(self, settings_type: type[SettingsT]) -> SettingsT:
        """Refuse settings for another carrier before constructing its client."""
        if not isinstance(self.settings, settings_type):
            raise ValueError("Telephony settings do not match the carrier service.")
        return self.settings


class TelephonyCallDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class StreamTokenRequirement(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"


class CallMetadata(_TelephonyValue):
    """Parsed routing, enriched in place only by authenticated platform lookups."""

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    call_sid: str
    call_id: Optional[UUID] = None
    stream_sid: Optional[str] = None
    from_number: Optional[str] = Field(default=None, repr=False)
    to_number: Optional[str] = Field(default=None, repr=False)
    organization_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    agent_revision: Optional[int] = Field(default=None, gt=0)
    provider_config_id: Optional[UUID] = None
    provider_config_revision: Optional[int] = Field(default=None, gt=0)
    conversation_id: Optional[UUID] = None
    direction: TelephonyCallDirection = TelephonyCallDirection.INBOUND
    initial_message: Optional[str] = Field(default=None, repr=False, exclude=True)
    media_stream_token: Optional[str] = Field(default=None, repr=False, exclude=True)
    stream_token_requirement: StreamTokenRequirement = (
        StreamTokenRequirement.NOT_REQUIRED
    )

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, value: object) -> TelephonyCallDirection:
        """Routing signatures already compare direction case-insensitively."""
        if isinstance(value, TelephonyCallDirection):
            return value
        if isinstance(value, str):
            return TelephonyCallDirection(value.upper())
        raise ValueError("Call direction must be inbound or outbound.")

    @property
    def requires_media_stream_token(self) -> bool:
        return self.stream_token_requirement is StreamTokenRequirement.REQUIRED


class CarrierMediaEvent(StrEnum):
    MEDIA = "media"
    START = "start"
    DTMF = "dtmf"
    IGNORED = "ignored"


class InboundMediaMessage(_TelephonyValue):
    """Standardized inbound media message from any telephony provider."""

    event: Literal[CarrierMediaEvent.MEDIA] = CarrierMediaEvent.MEDIA
    payload: bytes = Field(repr=False, exclude=True)
    timestamp: str | int
    track: str = "inbound"
    # Carrier ordinals are opaque: Twilio uses strings, Exotel also sends integers.
    sequence_number: str | int | None = None


class OutboundMediaMessage(_TelephonyValue):
    """Standardized outbound media message to any telephony provider."""

    payload: bytes = Field(repr=False, exclude=True)
    stream_sid: str


class CarrierStartMessage(_TelephonyValue):
    """Untrusted carrier metadata; the pipeline must resolve and authorize it."""

    event: Literal[CarrierMediaEvent.START] = CarrierMediaEvent.START
    metadata: CallMetadata = Field(repr=False, exclude=True)


class CarrierDtmfMessage(_TelephonyValue):
    event: Literal[CarrierMediaEvent.DTMF] = CarrierMediaEvent.DTMF
    digits: str = Field(min_length=1, repr=False, exclude=True)


class CarrierIgnoredMessage(_TelephonyValue):
    """A control message the current media pipeline does not consume."""

    event: Literal[CarrierMediaEvent.IGNORED] = CarrierMediaEvent.IGNORED


type ParsedCarrierMessage = (
    InboundMediaMessage
    | CarrierStartMessage
    | CarrierDtmfMessage
    | CarrierIgnoredMessage
)


class CarrierMediaStatus(str, Enum):
    """Observed result of a carrier-facing realtime media write."""

    ACCEPTED = "accepted"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class CarrierMediaFailureCode(StrEnum):
    AUDIO_WRITE_FAILED = "carrier_audio_write_failed"
    INTERRUPTION_WRITE_FAILED = "carrier_interruption_write_failed"


class CarrierMediaResult(_TelephonyValue):
    """Safe typed projection of one carrier audio or buffer-control write."""

    status: CarrierMediaStatus
    bytes_count: int = Field(default=0, ge=0)
    failure_code: CarrierMediaFailureCode | None = None

    @property
    def accepted(self) -> bool:
        return self.status is CarrierMediaStatus.ACCEPTED


class TelephonyOperationSupport(StrEnum):
    UNSUPPORTED = "unsupported"
    SUPPORTED = "supported"

    def __bool__(self) -> bool:
        raise TypeError("Compare telephony operation support explicitly.")


class TelephonyOperationCapabilities(_TelephonyValue):
    """Provider guarantees that affect safe charged-operation replay."""

    provider_idempotency: TelephonyOperationSupport
    reconciliation: TelephonyOperationSupport


class TelephonyOperationProfile(_TelephonyValue):
    """Static provider-operation metadata needed before durable send begins."""

    provider_operation: str
    transport_kind: OutboundTransportKind
    destination_origin: str
    capabilities: TelephonyOperationCapabilities

    @model_validator(mode="after")
    def validate_destination(self) -> Self:
        if not self.provider_operation.strip():
            raise ValueError("Telephony provider operation is required.")
        if not self.destination_origin.startswith("https://"):
            raise ValueError("Telephony provider destination must use HTTPS.")
        return self


class TelephonyControlAccepted(_TelephonyValue):
    """The carrier accepted one live call-control operation."""

    status_code: int | None = Field(
        default=None, ge=OUTBOUND_STATUS_CODE_MIN, le=OUTBOUND_STATUS_CODE_MAX
    )


class TelephonyControlOperation(StrEnum):
    END = "call_end"
    TRANSFER = "call_transfer"
    DTMF = "call_dtmf"


class TelephonyControlFailureCode(StrEnum):
    END_REJECTED = "call_end_rejected"
    END_UNCONFIRMED = "call_end_unconfirmed"
    TRANSFER_REJECTED = "call_transfer_rejected"
    TRANSFER_UNCONFIRMED = "call_transfer_unconfirmed"
    TRANSFER_UNSUPPORTED = "call_transfer_unsupported"
    DTMF_REJECTED = "call_dtmf_rejected"
    DTMF_UNCONFIRMED = "call_dtmf_unconfirmed"


class _TelephonyControlFailure(_TelephonyValue):
    failure_code: TelephonyControlFailureCode
    status_code: int | None = Field(
        default=None, ge=OUTBOUND_STATUS_CODE_MIN, le=OUTBOUND_STATUS_CODE_MAX
    )


class TelephonyControlRejected(_TelephonyControlFailure):
    """The carrier explicitly rejected the requested control."""


class TelephonyControlUnknown(_TelephonyControlFailure):
    """The carrier may have applied the control; do not claim success."""


class TelephonyControlUnsupported(_TelephonyControlFailure):
    """The carrier adapter does not implement this control."""


TelephonyControlResult: TypeAlias = (
    TelephonyControlAccepted
    | TelephonyControlRejected
    | TelephonyControlUnknown
    | TelephonyControlUnsupported
)


def classify_provider_failure(
    error: Exception,
    *,
    operation: str,
) -> OutboundSendOutcome:
    """Map provider failures without retaining or exposing vendor error prose."""
    status_code = _provider_status_code(error)
    failure_code = f"{operation}_rejected"
    if status_code == 429:
        return OutboundSendRetryable(
            failure_code=failure_code,
            status_code=status_code,
        )
    if status_code is not None and 400 <= status_code < 500 and status_code != 408:
        return OutboundSendTerminal(
            failure_code=failure_code,
            status_code=status_code,
        )
    return OutboundSendUnknown(
        failure_code=f"{operation}_unconfirmed",
        status_code=status_code,
    )


def classify_control_failure(
    error: Exception,
    *,
    operation: TelephonyControlOperation,
) -> TelephonyControlRejected | TelephonyControlUnknown:
    """Map a live control failure without leaking provider response content."""
    status_code = _provider_status_code(error)
    if status_code is not None and 400 <= status_code < 500 and status_code != 408:
        return TelephonyControlRejected(
            failure_code=TelephonyControlFailureCode(f"{operation.value}_rejected"),
            status_code=status_code,
        )
    return TelephonyControlUnknown(
        failure_code=TelephonyControlFailureCode(f"{operation.value}_unconfirmed"),
        status_code=status_code,
    )


def _provider_status_code(error: Exception) -> int | None:
    for name in ("status_code", "status"):
        value = getattr(error, name, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value if 100 <= value <= 599 else None
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 100 <= value <= 599 else None
    return None


class TelephonyMessageParser(Protocol):
    """Decode once at the vendor boundary, never returning unvalidated mappings."""

    def parse_message(self, raw_message: str | bytes) -> ParsedCarrierMessage:
        """Return a typed event without I/O or platform authorization effects."""
        ...


class BaseTelephonyService(ABC):
    """Abstract base class for telephony service implementations."""

    websocket: WebSocket | None

    def __init__(self, config: TelephonyConfig) -> None:
        """Initialize the telephony service.

        Args:
            config: Telephony configuration

        """
        self.config = config
        self._is_connected = False

    def set_websocket(self, websocket: WebSocket) -> None:
        """Attach the active provider WebSocket to the service."""
        self.websocket = websocket
        self._is_connected = True

    @property
    def is_connected(self) -> bool:
        """Check if the service is connected."""
        return self._is_connected

    @property
    @abstractmethod
    def provider(self) -> TelephonyProvider:
        """Get the provider identifier."""
        ...

    @abstractmethod
    async def send_media(self, message: OutboundMediaMessage) -> None:
        """Send media (audio) to the provider.

        Args:
            message: Outbound media message

        """
        ...

    @abstractmethod
    async def send_clear(self, stream_sid: str) -> bool:
        """Send clear signal; return false only when the carrier lacks it."""
        ...

    @abstractmethod
    def build_twiml_response(
        self,
        ws_url: str,
        custom_params: Dict[str, Any],
    ) -> str:
        """Build provider-specific XML/response for call control.

        Args:
            ws_url: WebSocket URL for media streaming
            custom_params: Custom parameters to pass

        Returns:
            Provider-specific response (e.g., TwiML for Twilio)

        """
        ...

    @abstractmethod
    def outbound_call_profile(self) -> TelephonyOperationProfile:
        """Describe outbound-call transport and retry guarantees."""
        ...

    @abstractmethod
    async def initiate_outbound_call(
        self,
        to_number: str,
        from_number: str,
        ws_url: str,
        custom_params: Dict[str, Any],
        authorization: OutboundSendAuthorization,
        status_callback_url: Optional[str] = None,
    ) -> OutboundSendOutcome:
        """Initiate an outbound call.

        Args:
            to_number: Destination phone number
            from_number: Source phone number
            ws_url: WebSocket URL for media streaming
            custom_params: Custom parameters
            status_callback_url: URL for call status updates

        Returns:
            Typed provider acceptance, rejection, retry, or ambiguity.

        """
        ...

    @abstractmethod
    def create_message_parser(self) -> TelephonyMessageParser:
        """Create a message parser for this provider.

        Returns:
            Provider-specific message parser

        """
        ...

    @abstractmethod
    def get_config(self) -> SpeechTransportFormat:
        """Return provider-specific base configuration for audio processing."""

    @abstractmethod
    def get_output_format(self) -> CarrierAudioFormat:
        """Return provider-specific TTS output_format metadata."""

    async def end_call(self, call_sid: str) -> TelephonyControlResult:
        """Terminate an active call by its provider call SID.

        Args:
            call_sid: The provider-specific call identifier

        Returns:
            Response data from the provider

        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support end_call"
        )

    async def transfer_call(
        self,
        call_sid: str,
        to_number: str,
    ) -> TelephonyControlResult:
        """Transfer an active call to another number.

        Args:
            call_sid: The provider-specific call identifier
            to_number: Destination phone number in E.164 format

        Returns:
            Response data from the provider

        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support transfer_call"
        )

    async def send_dtmf(
        self,
        call_sid: str,
        digits: str,
    ) -> TelephonyControlResult:
        """Send DTMF tones on an active call.

        Args:
            call_sid: The provider-specific call identifier
            digits: DTMF digits to send (0-9, *, #, w for pause)

        Returns:
            Response data from the provider

        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support send_dtmf"
        )

    async def connect(self) -> None:
        """Connect to the telephony service."""
        self._is_connected = True

    async def disconnect(self) -> None:
        """Disconnect from the telephony service."""
        self._is_connected = False
