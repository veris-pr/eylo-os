"""Admission policy for remote WebRTC ICE candidates."""

from __future__ import annotations

import ipaddress
from enum import IntEnum, StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eylo.pipelines.webrtc.errors import IceCandidateCode


class IceDeploymentMode(StrEnum):
    """Network targets a deployment permits remote peers to nominate."""

    PUBLIC = "public"
    LOCAL = "local"


class IceCandidateError(ValueError):
    """A remote candidate is malformed or targets a forbidden network."""

    def __init__(self, code: IceCandidateCode) -> None:
        super().__init__(code.value)
        self.code = code


class IceComponent(IntEnum):
    RTP = 1
    RTCP = 2


class IceProtocol(StrEnum):
    TCP = "tcp"
    UDP = "udp"


class IceCandidateType(StrEnum):
    HOST = "host"
    SERVER_REFLEXIVE = "srflx"
    PEER_REFLEXIVE = "prflx"
    RELAY = "relay"


class IceTcpType(StrEnum):
    ACTIVE = "active"
    PASSIVE = "passive"
    SIMULTANEOUS_OPEN = "so"


class _CandidateField(IntEnum):
    FOUNDATION = 0
    COMPONENT = 1
    PROTOCOL = 2
    PRIORITY = 3
    ADDRESS = 4
    PORT = 5
    TYPE_MARKER = 6
    TYPE = 7


MAX_REMOTE_CANDIDATES = 128
MAX_CANDIDATE_LENGTH = 2048
_CANDIDATE_REQUIRED_FIELDS = 8
_EXTENSION_PAIR_WIDTH = 2
_CANDIDATE_PREFIX = "candidate:"
_SDP_ATTRIBUTE_PREFIX = "a="
_SDP_CANDIDATE_PREFIX = _SDP_ATTRIBUTE_PREFIX + _CANDIDATE_PREFIX
_TYPE_MARKER = "typ"
_MDNS_SUFFIX = ".local"
_METADATA_ADDRESS = ipaddress.ip_address("169.254.169.254")
_MIN_PORT = 1
_MAX_PORT = 65535
type IcePort = Annotated[int, Field(ge=_MIN_PORT, le=_MAX_PORT)]


class _IceExtensions(BaseModel):
    """Consume supported extension pairs; ignore unknown vendor extensions."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    related_address: str | None = Field(default=None, alias="raddr")
    related_port: IcePort | None = Field(default=None, alias="rport")
    tcp_type: IceTcpType | None = Field(default=None, alias="tcptype")

    @field_validator("related_port", mode="before")
    @classmethod
    def _port(cls, value: str) -> int:
        return int(value)

    @field_validator("tcp_type", mode="before")
    @classmethod
    def _tcp_type(cls, value: str) -> IceTcpType:
        return IceTcpType(value)


class RemoteIceCandidate(BaseModel):
    """Parsed native values; network admission belongs to parse_remote_candidate."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    foundation: str = Field(min_length=1)
    component: IceComponent
    protocol: IceProtocol
    priority: int = Field(ge=0)
    address: str
    port: IcePort
    candidate_type: IceCandidateType
    related_address: str | None = None
    related_port: IcePort | None = None
    tcp_type: IceTcpType | None = None

    @model_validator(mode="after")
    def _tcp_mode(self) -> Self:
        if self.protocol is IceProtocol.TCP and self.tcp_type is None:
            raise ValueError("TCP candidates require a TCP mode.")
        return self


_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "fc00::/7",
        "::1/128",
    )
)


def parse_remote_candidate(
    candidate: str,
    *,
    mode: IceDeploymentMode,
) -> RemoteIceCandidate:
    """Parse one candidate and enforce the deployment network boundary."""
    if len(candidate) > MAX_CANDIDATE_LENGTH:
        raise IceCandidateError(IceCandidateCode.MALFORMED_CANDIDATE)
    normalized = candidate.removeprefix(_SDP_ATTRIBUTE_PREFIX)
    parts = normalized.split()
    if (
        len(parts) < _CANDIDATE_REQUIRED_FIELDS
        or not parts[_CandidateField.FOUNDATION].startswith(_CANDIDATE_PREFIX)
        or parts[_CandidateField.TYPE_MARKER].lower() != _TYPE_MARKER
    ):
        raise IceCandidateError(IceCandidateCode.MALFORMED_CANDIDATE)

    foundation = parts[_CandidateField.FOUNDATION].removeprefix(_CANDIDATE_PREFIX)
    if not foundation:
        raise IceCandidateError(IceCandidateCode.UNSUPPORTED_CANDIDATE)
    try:
        protocol = IceProtocol(parts[_CandidateField.PROTOCOL].lower())
        candidate_type = IceCandidateType(parts[_CandidateField.TYPE].lower())
    except ValueError:
        raise IceCandidateError(IceCandidateCode.UNSUPPORTED_CANDIDATE) from None
    try:
        component = IceComponent(int(parts[_CandidateField.COMPONENT]))
        priority = int(parts[_CandidateField.PRIORITY])
        port = int(parts[_CandidateField.PORT])
    except ValueError:
        raise IceCandidateError(IceCandidateCode.MALFORMED_CANDIDATE) from None
    if priority < 0 or not _MIN_PORT <= port <= _MAX_PORT:
        raise IceCandidateError(IceCandidateCode.MALFORMED_CANDIDATE)

    address = parts[_CandidateField.ADDRESS].lower().rstrip(".")
    _enforce_address(address, mode=mode)
    try:
        extensions = _IceExtensions.model_validate(
            {
                parts[index].lower(): parts[index + 1]
                for index in range(
                    _CANDIDATE_REQUIRED_FIELDS, len(parts) - 1, _EXTENSION_PAIR_WIDTH
                )
            }
        )
        return RemoteIceCandidate(
            foundation=foundation,
            component=component,
            protocol=protocol,
            priority=priority,
            address=address,
            port=port,
            candidate_type=candidate_type,
            related_address=extensions.related_address,
            related_port=extensions.related_port,
            tcp_type=extensions.tcp_type,
        )
    except ValueError:
        raise IceCandidateError(IceCandidateCode.MALFORMED_CANDIDATE) from None


def filter_offer_candidates(
    sdp: str,
    *,
    mode: IceDeploymentMode,
    max_candidates: int = MAX_REMOTE_CANDIDATES,
) -> str:
    """Remove forbidden embedded candidates and reject an unusable offer."""
    kept: list[str] = []
    candidate_count = 0
    accepted_count = 0
    for line in sdp.splitlines():
        if not line.startswith(_SDP_CANDIDATE_PREFIX):
            kept.append(line)
            continue
        candidate_count += 1
        if candidate_count > max_candidates:
            raise IceCandidateError(IceCandidateCode.CANDIDATE_LIMIT_REACHED)
        try:
            parse_remote_candidate(line, mode=mode)
        except IceCandidateError:
            continue
        accepted_count += 1
        kept.append(line)

    if candidate_count and not accepted_count:
        raise IceCandidateError(IceCandidateCode.NO_PERMITTED_CANDIDATES)
    return "\r\n".join(kept) + "\r\n"


def _enforce_address(address: str, *, mode: IceDeploymentMode) -> None:
    if address.endswith(_MDNS_SUFFIX):
        if mode is IceDeploymentMode.LOCAL:
            return
        raise IceCandidateError(IceCandidateCode.NON_PUBLIC_CANDIDATE)

    try:
        target = ipaddress.ip_address(address)
    except ValueError:
        raise IceCandidateError(IceCandidateCode.HOSTNAME_CANDIDATE_REJECTED) from None

    if target.is_unspecified or target.is_multicast:
        raise IceCandidateError(IceCandidateCode.UNSAFE_CANDIDATE)
    if target == _METADATA_ADDRESS:
        raise IceCandidateError(IceCandidateCode.UNSAFE_CANDIDATE)
    if target.is_global:
        return
    if mode is IceDeploymentMode.LOCAL and any(
        target in network for network in _LOCAL_NETWORKS
    ):
        return
    raise IceCandidateError(IceCandidateCode.NON_PUBLIC_CANDIDATE)
