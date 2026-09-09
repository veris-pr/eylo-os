"""Session-local raw voice data that must never become a durable checkpoint."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    model_validator,
)

from eylo.common.contracts.voice import VoiceRuntimeMode, VoiceSpeechOutcome
from eylo.pipelines.voice.request_state import VoiceRequestSource

_MAX_BUFFER_BYTES = 16 * 1024 * 1024
_MAX_BUFFER_ITEMS = 10_000


class LiveVoiceItemKind(StrEnum):
    """Raw item kinds retained only for the lifetime of one voice session."""

    USER_TRANSCRIPT = "user_transcript"
    ASSISTANT_TRANSCRIPT = "assistant_transcript"
    SYSTEM_SPEECH = "system_speech"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    DTMF = "dtmf"


class LiveVoiceBufferFailure(StrEnum):
    """Why a post-call projection cannot claim a complete source capture."""

    CAPACITY_EXCEEDED = "capacity_exceeded"
    INVALID_PAYLOAD = "invalid_payload"


class LiveVoiceBufferIdentity(BaseModel):
    """Content-free authority for one in-memory call buffer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: UUID
    conversation_id: UUID
    session_id: str
    voice_session_id: UUID | None
    runtime_mode: VoiceRuntimeMode
    canonical_storage_requested: StrictBool
    contact_id: UUID | None = None
    contact_participant_id: UUID | None = None
    agent_participant_id: UUID | None = None


class LiveVoiceDraft(BaseModel):
    """One not-yet-sequenced raw item supplied by a live runtime."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    kind: LiveVoiceItemKind
    payload: str | dict[str, JsonValue] = Field(repr=False, exclude=True)
    turn_index: StrictInt | None = Field(default=None, ge=0)
    participant_id: UUID | None = None
    request_id: UUID | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: StrictBool | None = None
    speech_outcome: VoiceSpeechOutcome | None = None
    policy_source: VoiceRequestSource | None = None
    occurred_at: AwareDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @model_validator(mode="after")
    def validate_payload_kind(self) -> Self:
        if self.kind is LiveVoiceItemKind.TOOL_CALL:
            if not isinstance(self.payload, dict):
                raise ValueError("Voice tool-call capture requires an argument object.")
        elif self.kind is not LiveVoiceItemKind.TOOL_RESULT:
            if not isinstance(self.payload, str):
                raise ValueError("Voice speech capture requires text.")
        return self


class LiveVoiceItem(LiveVoiceDraft):
    """One raw item with an immutable session-local sequence."""

    sequence: StrictInt = Field(ge=1)


class LiveVoiceBufferSnapshot(BaseModel):
    """Raw post-call input; consumers must redact before any durable write."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: LiveVoiceBufferIdentity
    items: tuple[LiveVoiceItem, ...] = Field(repr=False, exclude=True)
    complete: StrictBool
    failure: LiveVoiceBufferFailure | None
    captured_bytes: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_completeness(self) -> Self:
        if self.complete != (self.failure is None):
            raise ValueError("Voice capture completeness disagrees with its failure.")
        return self


class LiveVoiceBuffer:
    """Bounded, ordered raw voice state owned by exactly one live call."""

    def __init__(self, identity: LiveVoiceBufferIdentity) -> None:
        self.identity = identity
        self._items: list[LiveVoiceItem] = []
        self._captured_bytes = 0
        self._failure: LiveVoiceBufferFailure | None = None
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def item_count(self) -> int:
        return len(self._items)

    @property
    def captured_bytes(self) -> int:
        return self._captured_bytes

    @property
    def complete(self) -> bool:
        return self._failure is None

    @property
    def closed(self) -> bool:
        return self._closed

    async def append_turn(
        self,
        drafts: list[LiveVoiceDraft],
    ) -> tuple[LiveVoiceItem, ...]:
        """Append one logical batch atomically or mark capture incomplete."""
        if not drafts:
            return ()

        try:
            copied: list[tuple[LiveVoiceDraft, int]] = []
            for draft in drafts:
                validated = LiveVoiceDraft.model_validate(draft)
                copied.append((validated, _payload_bytes(validated.payload)))
        except (RecursionError, TypeError, ValueError):
            async with self._lock:
                if self._closed:
                    raise RuntimeError("Live voice buffer is closed.")
                if self._failure is None:
                    self._failure = LiveVoiceBufferFailure.INVALID_PAYLOAD
            return ()
        async with self._lock:
            if self._closed:
                raise RuntimeError("Live voice buffer is closed.")
            if self._failure is not None:
                return ()
            batch_bytes = sum(size for _, size in copied)
            if (
                len(self._items) + len(copied) > _MAX_BUFFER_ITEMS
                or self._captured_bytes + batch_bytes > _MAX_BUFFER_BYTES
            ):
                self._failure = LiveVoiceBufferFailure.CAPACITY_EXCEEDED
                return ()

            start = len(self._items) + 1
            appended = tuple(
                LiveVoiceItem(
                    sequence=start + offset,
                    kind=draft.kind,
                    payload=draft.payload,
                    turn_index=draft.turn_index,
                    participant_id=draft.participant_id,
                    request_id=draft.request_id,
                    tool_call_id=draft.tool_call_id,
                    tool_name=draft.tool_name,
                    is_error=draft.is_error,
                    speech_outcome=draft.speech_outcome,
                    policy_source=draft.policy_source,
                    occurred_at=draft.occurred_at,
                )
                for offset, (draft, _) in enumerate(copied)
            )
            self._items.extend(appended)
            self._captured_bytes += batch_bytes
            return tuple(item.model_copy(deep=True) for item in appended)

    async def reject_capture(self) -> None:
        """Record invalid producer input without interrupting or reopening a call."""
        async with self._lock:
            if not self._closed and self._failure is None:
                self._failure = LiveVoiceBufferFailure.INVALID_PAYLOAD

    async def snapshot(self) -> LiveVoiceBufferSnapshot:
        """Copy current raw state without closing the live session."""
        async with self._lock:
            return self._snapshot()

    async def seal(self) -> LiveVoiceBufferSnapshot:
        """Close the buffer and transfer its raw state to post-call processing."""
        async with self._lock:
            self._closed = True
            return self._snapshot()

    async def discard(self) -> None:
        """Close and erase raw memory when no post-call consumer owns it."""
        async with self._lock:
            self._closed = True
            self._items.clear()
            self._captured_bytes = 0

    def mark_speech_outcome(
        self,
        request_id: UUID,
        speech_outcome: VoiceSpeechOutcome,
    ) -> bool:
        """Attach a terminal playback result to generated speech.

        TTS completion callbacks are synchronous. This mutation has no await and
        therefore cannot interleave with the mutation section of ``append_turn``
        on the same event loop.
        """
        if self._closed:
            return False
        for index in range(len(self._items) - 1, -1, -1):
            item = self._items[index]
            if (
                item.kind
                in {
                    LiveVoiceItemKind.ASSISTANT_TRANSCRIPT,
                    LiveVoiceItemKind.SYSTEM_SPEECH,
                }
                and item.request_id == request_id
            ):
                self._items[index] = item.model_copy(
                    update={"speech_outcome": VoiceSpeechOutcome(speech_outcome)},
                )
                return True
        return False

    def _snapshot(self) -> LiveVoiceBufferSnapshot:
        return LiveVoiceBufferSnapshot(
            identity=self.identity,
            items=tuple(self._items),
            complete=self.complete,
            failure=self._failure,
            captured_bytes=self._captured_bytes,
        )


def _payload_bytes(payload: str | dict[str, JsonValue]) -> int:
    if isinstance(payload, str):
        return len(payload.encode("utf-8"))
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return len(encoded.encode("utf-8"))


__all__ = [
    "LiveVoiceBuffer",
    "LiveVoiceBufferFailure",
    "LiveVoiceBufferIdentity",
    "LiveVoiceBufferSnapshot",
    "LiveVoiceDraft",
    "LiveVoiceItem",
    "LiveVoiceItemKind",
]
