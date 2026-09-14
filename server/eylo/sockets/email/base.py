"""Interface implemented by concrete email provider adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, JsonValue, ValidationError
from pydantic.json_schema import SkipJsonSchema

from eylo.common.outbound import (
    OUTBOUND_DESTINATION_ORIGIN_MAX_LENGTH,
    OUTBOUND_OPERATION_MAX_LENGTH,
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundTransportKind,
)
from eylo.sockets.email.schemas import EmailMessage, EmailResponse, EmailWebhookEvent

EmailDeliverySender = Callable[
    [OutboundSendAuthorization],
    Awaitable[OutboundSendOutcome],
]


class EmailCapabilitySupport(Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class _EmailPlanValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )


class EmailDeliveryCapabilities(_EmailPlanValue):
    """Provider guarantees relevant to safe retry and reconciliation."""

    idempotent_send: EmailCapabilitySupport
    reconciliation: EmailCapabilitySupport


class PlannedEmailDelivery(_EmailPlanValue):
    """One fully validated provider operation, ready for the durable boundary."""

    attempt_id: UUID
    provider_operation: str = Field(
        min_length=1, max_length=OUTBOUND_OPERATION_MAX_LENGTH
    )
    transport_kind: OutboundTransportKind
    destination_origin: str = Field(
        min_length=1, max_length=OUTBOUND_DESTINATION_ORIGIN_MAX_LENGTH
    )
    capabilities: EmailDeliveryCapabilities
    sender: SkipJsonSchema[EmailDeliverySender] = Field(repr=False, exclude=True)

    async def send(
        self,
        authorization: OutboundSendAuthorization,
    ) -> OutboundSendOutcome:
        if authorization.attempt_id != self.attempt_id:
            raise ValueError("Email delivery authorization belongs to another attempt.")
        return await self.sender(authorization)


class EmailVendorAdapter(ABC):
    @abstractmethod
    def plan_delivery(
        self,
        message: EmailMessage,
        *,
        attempt_id: UUID,
    ) -> PlannedEmailDelivery:
        """Validate and construct one bounded delivery before any network send."""

    @abstractmethod
    async def verify_credentials(self) -> None:
        """Authenticate without sending a message or mutating provider state."""

    @abstractmethod
    def transform_to_platform_response(
        self,
        vendor_response: object,
        original_message: EmailMessage,
    ) -> EmailResponse: ...

    @abstractmethod
    async def process_webhook(
        self, payload: Mapping[str, JsonValue]
    ) -> EmailWebhookEvent:
        """Parse one pre-authenticated event; this does not expose an HTTP endpoint."""

    async def verify_email(self, email: str) -> str | None:
        class EmailValidator(BaseModel):
            email: EmailStr

        try:
            return str(EmailValidator(email=email).email).lower()
        except ValidationError:
            return None

    async def close(self) -> None:
        """Release adapter resources; stateless adapters have none."""


__all__ = [
    "EmailCapabilitySupport",
    "EmailDeliveryCapabilities",
    "EmailDeliverySender",
    "EmailVendorAdapter",
    "PlannedEmailDelivery",
]
