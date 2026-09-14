"""Stored webhook signal contract shared by ingestion and durable replay."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from eylo.sor.shared.contracts import SorWebhookSignal

SOR_WEBHOOK_EVENT_TYPE_MAX_LENGTH = 256
SOR_WEBHOOK_IDENTIFIER_MAX_LENGTH = 512
SOR_WEBHOOK_OBJECT_KEY_MAX_LENGTH = 160
SOR_WEBHOOK_SIGNAL_SET_MAX_BYTES = 262_144


class SorStoredWebhookSignal(BaseModel):
    """Exact persisted JSON shape; preserve timestamp text for delivery fingerprints."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    delivery_id: str | None = Field(min_length=1)
    event_type: str = Field(min_length=1)
    vendor_object_key: str | None = Field(min_length=1)
    external_id: str | None = Field(min_length=1)
    occurred_at: str | None

    def to_signal(self) -> SorWebhookSignal:
        """Replay converts timestamp text only after the stored shape validates."""
        return SorWebhookSignal(
            delivery_id=self.delivery_id,
            event_type=self.event_type,
            vendor_object_key=self.vendor_object_key,
            external_id=self.external_id,
            occurred_at=datetime.fromisoformat(self.occurred_at)
            if self.occurred_at is not None
            else None,
        )
