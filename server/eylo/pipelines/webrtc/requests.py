"""Validated browser signaling inputs, before negotiation or peer acquisition."""

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from eylo.common.contracts.websocket import WEBRTC_SIGNALING_VERSION
from eylo.pipelines.webrtc.agent_peer import SessionDescriptionType
from eylo.pipelines.webrtc.errors import (
    IceCandidateCode,
    WebRTCSignalingCode,
    WebRTCSignalingError,
)


class _Request(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    @classmethod
    def from_payload(cls, data: Mapping[str, object]) -> Self:
        try:
            return cls.model_validate(dict(data))
        except ValidationError as error:
            location = error.errors(include_input=False, include_context=False)[0][
                "loc"
            ]
            field = location[0] if location else None
            if field == "protocol_version":
                code = WebRTCSignalingCode.UNSUPPORTED_PROTOCOL_VERSION
            elif field == "negotiation_id":
                code = WebRTCSignalingCode.MISSING_NEGOTIATION_ID
            elif field == "sdp":
                code = WebRTCSignalingCode.MISSING_SDP
            elif field == "type":
                code = WebRTCSignalingCode.INVALID_OFFER_TYPE
            else:
                raise WebRTCSignalingError(
                    IceCandidateCode.MALFORMED_CANDIDATE
                ) from None
            raise WebRTCSignalingError(code) from None


class WebRTCPrepareRequest(_Request):
    protocol_version: int

    @field_validator("protocol_version")
    @classmethod
    def _version(cls, value: int) -> int:
        if value != WEBRTC_SIGNALING_VERSION:
            raise ValueError("Unsupported WebRTC protocol version.")
        return value


class WebRTCOfferRequest(WebRTCPrepareRequest):
    negotiation_id: str = Field(min_length=1)
    sdp: str = Field(min_length=1)
    type: Literal[SessionDescriptionType.OFFER] = SessionDescriptionType.OFFER


class WebRTCCandidateInput(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    candidate: str
    sdp_mid: str | None = Field(default=None, alias="sdpMid")
    sdp_mline_index: int | None = Field(default=None, alias="sdpMLineIndex", ge=0)


class WebRTCCandidateRequest(WebRTCPrepareRequest):
    negotiation_id: str = Field(min_length=1)
    candidate: WebRTCCandidateInput | None = None

    @field_validator("candidate", mode="before")
    @classmethod
    def _nested_candidate(cls, value: object) -> object:
        """Accept the existing direct and one-level nested browser envelopes."""
        if isinstance(value, dict) and isinstance(value.get("candidate"), dict):
            return value["candidate"]
        return value
