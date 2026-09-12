"""Exotel callback identity parsing; authenticated status processing is unsupported."""

from pydantic import Field

from eylo.sockets.telephony.status_contracts import CallbackIdentity


class ExotelCallbackIdentity(CallbackIdentity):
    call_sid: str = Field(alias="CallSid", min_length=1)
