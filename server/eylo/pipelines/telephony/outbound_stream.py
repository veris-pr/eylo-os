"""Outbound routing identity encoded for the existing carrier bootstrap paths."""

import json
from enum import StrEnum
from typing import Self
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eylo.modules.telephony.provider_config_domain import TelephonyProvider
from eylo.modules.telephony.schemas import CallDirection
from eylo.modules.telephony.webhook_security import authenticated_media_stream_claims
from eylo.pipelines.telephony.stream_routing import RoutingQueryKey
from eylo.sockets.telephony.base import TelephonyCallDirection
from eylo.sockets.telephony.stream_parameters import StreamParameters

MAX_MEDIA_QUERY_FIELDS = 10


class StreamParameterKey(StrEnum):
    PROVIDER = "provider"
    TOKEN = "stream_token"
    DIRECTION = "Direction"
    INITIAL_MESSAGE = "InitialMessage"
    EXOTEL_CUSTOM_FIELD = "CustomField"


class OutboundMediaRouting(BaseModel):
    """Resolved identity, not authority inferred from carrier-supplied fields."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    provider: TelephonyProvider
    organization_id: UUID
    agent_id: UUID
    agent_revision: int = Field(gt=0)
    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    call_id: UUID
    stream_token: str = Field(min_length=1, repr=False, exclude=True)
    initial_message: str | None = Field(default=None, repr=False, exclude=True)

    @classmethod
    def from_signed_token(
        cls,
        token: str | None,
        *,
        provider: TelephonyProvider,
        call_sid: str | None = None,
    ) -> Self:
        """Authenticate before decoding identity; DB claiming remains a separate step."""
        claims = authenticated_media_stream_claims(token)
        if (
            claims is None
            or claims.provider is not provider
            or claims.direction is not CallDirection.OUTBOUND
            or (claims.call_sid and claims.call_sid != call_sid)
            or token is None
        ):
            raise ValueError("Outbound media token is invalid.")
        return cls(
            provider=provider,
            organization_id=UUID(claims.organization_id),
            agent_id=UUID(claims.agent_id),
            agent_revision=claims.agent_revision,
            provider_config_id=UUID(claims.provider_config_id),
            provider_config_revision=claims.provider_config_revision,
            call_id=UUID(claims.call_id),
            stream_token=token,
            initial_message=claims.initial_message,
        )

    @classmethod
    def from_plivo_answer_url(cls, ws_url: str, *, server_domain: str) -> Self:
        """Accept only our exact signed URL, not an arbitrary carrier media target."""
        parsed = urlsplit(ws_url)
        if (
            parsed.scheme != "wss"
            or parsed.netloc != server_domain
            or parsed.path != "/api/media/stream"
            or parsed.fragment
        ):
            raise ValueError("Plivo media URL is invalid.")
        pairs = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=MAX_MEDIA_QUERY_FIELDS,
        )
        query = dict(pairs)
        if len(query) != len(pairs):
            raise ValueError("Plivo media URL is ambiguous.")
        routing = cls.from_signed_token(
            query.get(StreamParameterKey.TOKEN), provider=TelephonyProvider.PLIVO
        )
        if routing.websocket_url(server_domain) != ws_url:
            raise ValueError("Plivo media URL does not match its signed routing.")
        return routing

    def websocket_url(self, server_domain: str) -> str:
        """Twilio carries routing in token fragments, never query parameters."""
        if self.provider is TelephonyProvider.TWILIO:
            return f"wss://{server_domain}/api/media/stream/twilio"
        query: dict[str, str] = {
            StreamParameterKey.PROVIDER: self.provider.value,
            RoutingQueryKey.ORGANIZATION: str(self.organization_id),
            RoutingQueryKey.AGENT: str(self.agent_id),
            RoutingQueryKey.AGENT_REVISION: str(self.agent_revision),
            RoutingQueryKey.PROVIDER_CONFIG: str(self.provider_config_id),
            RoutingQueryKey.PROVIDER_CONFIG_REVISION: str(
                self.provider_config_revision
            ),
            RoutingQueryKey.CALL: str(self.call_id),
            RoutingQueryKey.DIRECTION: TelephonyCallDirection.OUTBOUND.value,
            StreamParameterKey.TOKEN: self.stream_token,
        }
        if self.initial_message:
            query[RoutingQueryKey.INITIAL_MESSAGE] = self.initial_message
        return f"wss://{server_domain}/api/media/stream?{urlencode(query)}"

    def custom_parameters(self) -> StreamParameters:
        """Preserve native key casing and Exotel's pre-opening-message packing."""
        if self.provider is TelephonyProvider.TWILIO:
            return StreamParameters(
                values={StreamParameterKey.TOKEN: self.stream_token}
            )
        parameters: dict[str, str | int] = {
            StreamParameterKey.DIRECTION: TelephonyCallDirection.OUTBOUND.value,
            RoutingQueryKey.AGENT: str(self.agent_id),
            RoutingQueryKey.AGENT_REVISION: self.agent_revision,
            RoutingQueryKey.ORGANIZATION: str(self.organization_id),
            RoutingQueryKey.PROVIDER_CONFIG: str(self.provider_config_id),
            RoutingQueryKey.PROVIDER_CONFIG_REVISION: str(
                self.provider_config_revision
            ),
            RoutingQueryKey.CALL: str(self.call_id),
            StreamParameterKey.TOKEN: self.stream_token,
        }
        if self.provider is TelephonyProvider.EXOTEL:
            parameters[StreamParameterKey.EXOTEL_CUSTOM_FIELD] = json.dumps(
                parameters, separators=(",", ":"), ensure_ascii=False
            )
        if self.initial_message:
            parameters[StreamParameterKey.INITIAL_MESSAGE] = self.initial_message
        return StreamParameters(values=parameters)
