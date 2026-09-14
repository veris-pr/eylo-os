"""Explicit registry for versioned durable event consumers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.events.durable.domain import (
    MAX_EVENT_VERSION,
    DurableEventEnvelope,
    validate_consumer_name,
    validate_event_type,
)

EventConsumer = Callable[
    [AsyncSession, DurableEventEnvelope],
    Awaitable[None],
]


class EventConsumerRegistrationError(Exception):
    """A consumer manifest is invalid or internally ambiguous."""


class EventConsumerNotRegistered(Exception):
    """No exact consumer supports the fact type and schema version."""


class PermanentEventConsumerError(Exception):
    """A consumer rejected a fact that retry cannot make valid."""


class EventConsumerKey(BaseModel):
    """One exact handler identity in the process manifest."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    consumer_name: str
    event_type: str
    event_version: int = Field(ge=1, le=MAX_EVENT_VERSION)

    @field_validator("consumer_name")
    @classmethod
    def valid_consumer(cls, value: str) -> str:
        return validate_consumer_name(value)

    @field_validator("event_type")
    @classmethod
    def valid_event_type(cls, value: str) -> str:
        return validate_event_type(value)

    def sort_key(self) -> tuple[str, str, int]:
        return self.consumer_name, self.event_type, self.event_version


class EventConsumerRegistry:
    """Resolve required consumers by explicit name, fact type and version."""

    def __init__(self) -> None:
        self._handlers: dict[EventConsumerKey, EventConsumer] = {}

    def register(
        self,
        *,
        consumer_name: str,
        event_type: str,
        event_version: int,
        handler: EventConsumer,
    ) -> EventConsumerKey:
        try:
            key = EventConsumerKey(
                consumer_name=consumer_name,
                event_type=event_type,
                event_version=event_version,
            )
        except ValueError as error:
            raise EventConsumerRegistrationError(str(error)) from error
        if not callable(handler):
            raise EventConsumerRegistrationError("Consumer handler must be callable.")

        if key in self._handlers:
            raise EventConsumerRegistrationError(
                "Durable event consumer registration is duplicated: "
                f"{consumer_name}/{event_type}/v{event_version}."
            )
        self._handlers[key] = handler
        return key

    def resolve(
        self,
        *,
        consumer_name: str,
        envelope: DurableEventEnvelope,
    ) -> EventConsumer:
        key = EventConsumerKey(
            consumer_name=consumer_name,
            event_type=envelope.event_type,
            event_version=envelope.event_version,
        )
        handler = self._handlers.get(key)
        if handler is None:
            raise EventConsumerNotRegistered(
                "No durable consumer is registered for "
                f"{consumer_name}/{envelope.event_type}/v{envelope.event_version}."
            )
        return handler

    def manifest(self) -> tuple[EventConsumerKey, ...]:
        return tuple(sorted(self._handlers, key=EventConsumerKey.sort_key))
