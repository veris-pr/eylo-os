"""Typed email effect projections and agent-visible outcomes."""

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from eylo.common.outbound import OutboundAttemptState
from eylo.modules.email_configs.catalog import EmailProviders
from eylo.pipelines.outbound.durable_execution import OutboundExecutionReceipt


class EmailDeliveryStatus(StrEnum):
    """Provider acceptance is not confirmed delivery to the recipient."""

    ACCEPTED = "accepted"
    UNKNOWN = "unknown"
    FAILED = "failed"


class EmailToolError(StrEnum):
    INPUT_INVALID = "email_input_invalid"
    CONFIG_UNAVAILABLE = "email_config_unavailable"
    DELIVERY_UNSUPPORTED = "email_delivery_unsupported"
    DELIVERY_CONFLICT = "email_delivery_conflict"
    DELIVERY_UNKNOWN = "email_delivery_unknown"
    DELIVERY_REJECTED = "email_delivery_rejected"


class EmailToolContentKind(StrEnum):
    ERROR = "email_error"


class _EmailResult(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )


class EmailDeliveryResult(_EmailResult):
    """Safe product projection of the already validated outbound receipt."""

    attempt_id: UUID
    state: OutboundAttemptState
    vendor: EmailProviders
    provider_reference: str | None
    failure_code: str | None

    @property
    def status(self) -> EmailDeliveryStatus:
        if self.state is OutboundAttemptState.SUCCEEDED:
            return EmailDeliveryStatus.ACCEPTED
        if self.state is OutboundAttemptState.UNKNOWN:
            return EmailDeliveryStatus.UNKNOWN
        return EmailDeliveryStatus.FAILED

    @property
    def tracking_id(self) -> str:
        return self.provider_reference or str(self.attempt_id)

    @classmethod
    def from_receipt(
        cls, receipt: OutboundExecutionReceipt, *, vendor: EmailProviders | str
    ) -> Self:
        return cls(
            attempt_id=receipt.attempt_id,
            state=receipt.state,
            vendor=EmailProviders(vendor),
            provider_reference=receipt.provider_reference,
            failure_code=receipt.failure_code,
        )


class EmailAcceptedContent(_EmailResult):
    status: Literal[EmailDeliveryStatus.ACCEPTED] = EmailDeliveryStatus.ACCEPTED
    message_id: str = Field(min_length=1)


class EmailErrorContent(_EmailResult):
    kind: Literal[EmailToolContentKind.ERROR] = EmailToolContentKind.ERROR
    error: EmailToolError


class EmailDeliveryMetadata(_EmailResult):
    """Exact provider binding and outbound effect identity, without message content."""

    email_delivery: Literal[True] = True
    email_delivery_status: EmailDeliveryStatus
    outbound_attempt_id: UUID
    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)


class EmailToolExecutionOutcome(_EmailResult):
    """Derive error state and JSON views from one coherent delivery outcome."""

    result: EmailAcceptedContent | EmailErrorContent
    delivery: EmailDeliveryMetadata | None = None

    @model_validator(mode="after")
    def validate_delivery_status(self) -> Self:
        if isinstance(self.result, EmailAcceptedContent):
            expected = EmailDeliveryStatus.ACCEPTED
        elif self.result.error is EmailToolError.DELIVERY_UNKNOWN:
            expected = EmailDeliveryStatus.UNKNOWN
        elif self.result.error is EmailToolError.DELIVERY_REJECTED:
            expected = EmailDeliveryStatus.FAILED
        else:
            if self.delivery is not None:
                raise ValueError(
                    "Preflight email errors cannot carry a delivery receipt."
                )
            return self
        if self.delivery is None or self.delivery.email_delivery_status is not expected:
            raise ValueError("Email content and delivery metadata disagree.")
        return self

    @property
    def is_error(self) -> bool:
        return isinstance(self.result, EmailErrorContent)

    @property
    def content(self) -> dict[str, JsonValue]:
        return self.result.model_dump(mode="json")

    @property
    def metadata(self) -> dict[str, JsonValue]:
        return {} if self.delivery is None else self.delivery.model_dump(mode="json")
