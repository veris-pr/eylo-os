"""Constants for the campaigns module."""

from enum import Enum

APP_DB_PREFIX = "campaign_"
APP_TAG = "Campaigns"


class CampaignChannel(str, Enum):
    """Supported campaign outreach channels."""

    VOICE = "voice"
    EMAIL = "email"
    WIDGET = "widget"


class CampaignStatus(str, Enum):
    """Campaign lifecycle states.

    DRAFT → RUNNING → COMPLETED
      ↓        ↓
      ↓      PAUSED → RUNNING (resume)
      ↓        ↓
    CANCELED  CANCELED
    """

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELED = "canceled"


class CampaignContactStatus(str, Enum):
    """Per-contact status within a campaign.

    PENDING → QUEUED → IN_PROGRESS → COMPLETED
                            ↓
                          FAILED → RETRY → QUEUED
                            ↓
                          SKIPPED
    """

    PENDING = "pending"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


# Valid state transitions for campaigns
CAMPAIGN_TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    CampaignStatus.DRAFT: {CampaignStatus.RUNNING, CampaignStatus.CANCELED},
    CampaignStatus.SCHEDULED: {CampaignStatus.RUNNING, CampaignStatus.CANCELED},
    CampaignStatus.RUNNING: {
        CampaignStatus.PAUSED,
        CampaignStatus.COMPLETED,
        CampaignStatus.CANCELED,
    },
    CampaignStatus.PAUSED: {CampaignStatus.RUNNING, CampaignStatus.CANCELED},
    CampaignStatus.COMPLETED: {CampaignStatus.COMPLETED},
    CampaignStatus.CANCELED: {CampaignStatus.CANCELED},
}

# --- Per-channel outcome definitions ---

CHANNEL_CONNECTED_OUTCOMES: dict[str, frozenset[str]] = {
    CampaignChannel.VOICE: frozenset(
        {
            "customer_ended_call",
            "agent_ended_call",
            "exceeded_max_duration",
            "silence_timed_out",
            "agent_transfer",
        }
    ),
    CampaignChannel.EMAIL: frozenset({"delivered", "opened"}),
    CampaignChannel.WIDGET: frozenset({"delivered", "replied"}),
}

# Channels where successful dispatch = delivery (no async callback)
IMMEDIATE_DELIVERY_CHANNELS: frozenset[str] = frozenset(
    {CampaignChannel.WIDGET, CampaignChannel.EMAIL}
)
