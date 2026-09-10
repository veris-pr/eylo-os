"""Socket-owned credential request and ICE response contracts.

Unknown response metadata is ignored; malformed consumed fields fail closed.
Credentials are private in normal representations and exported only for HTTP
authentication or the authorized browser/native peer projection.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eylo.sockets.stun_turn.config import TurnixConfig


class IceScheme(StrEnum):
    STUN = "stun:"
    STUN_TLS = "stuns:"
    TURN = "turn:"
    TURN_TLS = "turns:"


class IceServer(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    urls: tuple[str, ...] = Field(min_length=1)
    username: str | None = None
    credential: str | None = Field(default=None, repr=False, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _mapping(cls, value: object) -> object:
        return dict(value) if isinstance(value, Mapping) else value

    @field_validator("urls", mode="before")
    @classmethod
    def _urls(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, list) and all(isinstance(url, str) for url in value):
            return tuple(value)
        raise ValueError("ICE urls must be a string or string list.")

    @field_validator("urls")
    @classmethod
    def _schemes(cls, urls: tuple[str, ...]) -> tuple[str, ...]:
        if not all(url.startswith(tuple(IceScheme)) for url in urls):
            raise ValueError("ICE URL scheme is unsupported.")
        return urls

    @property
    def has_turn(self) -> bool:
        return any(
            url.startswith((IceScheme.TURN, IceScheme.TURN_TLS)) for url in self.urls
        )


class IceCredentials(BaseModel):
    """Common ICE envelope; plain-list vendor responses are wrapped at ingress."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    ice_servers: tuple[IceServer, ...] = Field(alias="iceServers", min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _payload(cls, value: object) -> object:
        if isinstance(value, list):
            return {"iceServers": value}
        return dict(value) if isinstance(value, Mapping) else value

    @field_validator("ice_servers", mode="before")
    @classmethod
    def _servers(cls, value: object) -> tuple[object, ...]:
        if not isinstance(value, list):
            raise ValueError("ICE servers must be a list.")
        return tuple(value)

    @model_validator(mode="after")
    def _requires_turn(self) -> Self:
        if not any(server.has_turn for server in self.ice_servers):
            raise ValueError("ICE credentials must contain a TURN server.")
        return self


class MeteredCredentialQuery(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    api_key: str = Field(min_length=1, repr=False, exclude=True)

    def http_parameters(self) -> dict[str, str]:
        """Explicit credential export for the fixed Metered credential endpoint."""
        return {"apiKey": self.api_key}


class TurnixCredentialRequest(BaseModel):
    """Only native body fields; auth and client IP belong in HTTP headers."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    initiator_client: str | None = None
    receiver_client: str | None = None
    room: str | None = None
    ttl: int | None = None
    preferred_region: str | None = None
    fixed_region: str | None = None

    @classmethod
    def from_config(cls, config: TurnixConfig) -> Self:
        return cls(
            initiator_client=config.initiator_client,
            receiver_client=config.receiver_client,
            room=config.room,
            ttl=config.ttl,
            preferred_region=config.preferred_region,
            fixed_region=config.fixed_region,
        )
