"""Internal binary-frame contract; raw audio never enters a JSON event payload."""

from typing import Literal

from pydantic import ConfigDict, Field, StrictBytes

from eylo.common.contracts.websocket import WsEvent, WsEventAction


class WsBinaryAudioRequest(WsEvent):
    """One received binary frame, dispatched under the existing contact gate."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", hide_input_in_errors=True,
        revalidate_instances="always", allow_inf_nan=False,
    )

    kind: Literal[WsEventAction.AUDIO_DATA] = WsEventAction.AUDIO_DATA
    audio_data: StrictBytes = Field(repr=False, exclude=True)
