"""Twilio's query-free Stream XML and bounded opaque-token transport."""

from collections.abc import Mapping
from typing import Annotated
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from eylo.sockets.telephony.stream_parameters import StreamParameters

PARAMETER_LENGTH_LIMIT = 500
TOKEN_PART_LENGTH = 480
MAX_TOKEN_PARTS = 128
TOKEN_COUNT_KEY = "EyloTokenCount"
TOKEN_PART_PREFIX = "EyloTokenPart"
STREAM_TOKEN_KEY = "stream_token"

type TokenPart = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=TOKEN_PART_LENGTH, pattern=r"^[A-Za-z0-9_.-]+$"
    ),
]


class TokenFragments(BaseModel):
    """A bounded carrier encoding, not token authenticity or platform authority."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )
    parts: tuple[TokenPart, ...] = Field(
        min_length=1, max_length=MAX_TOKEN_PARTS, repr=False, exclude=True
    )

    @classmethod
    def from_token(cls, token: str) -> "TokenFragments":
        if len(token) > TOKEN_PART_LENGTH * MAX_TOKEN_PARTS:
            raise ValueError("Twilio stream token exceeds the transport limit.")
        return cls(
            parts=tuple(
                token[index : index + TOKEN_PART_LENGTH]
                for index in range(0, len(token), TOKEN_PART_LENGTH)
            )
        )

    @classmethod
    def from_wire(cls, values: Mapping[str, object]) -> "TokenFragments | None":
        """Reject incomplete, oversized and ambiguous fragment envelopes."""
        if any(not isinstance(key, str) for key in values):
            raise ValueError("Twilio custom parameter names must be text.")
        names = {key for key in values if key.startswith(TOKEN_PART_PREFIX)}
        if TOKEN_COUNT_KEY not in values:
            if names:
                raise ValueError("Twilio token fragment count is missing.")
            return None
        count = values[TOKEN_COUNT_KEY]
        if (
            not isinstance(count, str)
            or not count.isascii()
            or not count.isdecimal()
            or len(count) > len(str(MAX_TOKEN_PARTS))
        ):
            raise ValueError("Twilio token fragment count is invalid.")
        count_value = int(count)
        if not 1 <= count_value <= MAX_TOKEN_PARTS or str(count_value) != count:
            raise ValueError("Twilio token fragment count is invalid.")
        expected = [f"{TOKEN_PART_PREFIX}{index}" for index in range(count_value)]
        if names != set(expected):
            raise ValueError("Twilio token fragments are incomplete or ambiguous.")
        return cls.model_validate({"parts": tuple(values[name] for name in expected)})

    def token(self) -> str:
        return "".join(self.parts)

    def parameters(self) -> dict[str, str]:
        return {
            TOKEN_COUNT_KEY: str(len(self.parts)),
            **{
                f"{TOKEN_PART_PREFIX}{index}": part
                for index, part in enumerate(self.parts)
            },
        }


def render_stream_xml(ws_url: str, custom_params: StreamParameters) -> str:
    """Preserve opaque token bytes and XML-escape values; no query URL is accepted."""
    url = urlsplit(ws_url)
    if (
        url.scheme != "wss"
        or not url.hostname
        or url.query
        or url.fragment
        or url.username
        or url.password
    ):
        raise ValueError("Twilio requires a query-free WSS stream URL.")
    parameters = custom_params.as_wire()
    token = parameters.get(STREAM_TOKEN_KEY)
    if token is not None:
        if not isinstance(token, str):
            raise ValueError("Twilio stream token must be text.")
        parameters = dict(TokenFragments.from_token(token).parameters())
    root = Element("Response")
    stream = SubElement(SubElement(root, "Connect"), "Stream", url=ws_url)
    for name, value in parameters.items():
        text = str(value)
        if len(name) + len(text) >= PARAMETER_LENGTH_LIMIT:
            raise ValueError("Twilio stream parameter exceeds the vendor limit.")
        SubElement(stream, "Parameter", name=name, value=text)
    return tostring(root, encoding="unicode")
