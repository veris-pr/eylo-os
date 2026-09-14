"""Widget channel adapter — dispatches campaign outreach as chat messages."""

import logging
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import start_transaction
from eylo.modules.conversations.models.conversations import ConversationsModel
from eylo.products.campaigns.channels.base import (
    CampaignChannelAdapter,
    ChannelDispatchResult,
    ChannelDispatchState,
    ChannelReplayPolicy,
)
from eylo.products.campaigns.constants import CampaignChannel
from eylo.products.campaigns.schemas.indb import CampaignContactInDb, CampaignInDb

logger = logging.getLogger(__name__)

_DISPATCH_CONFLICT_MESSAGE = (
    "Campaign attempt conversation conflicts with its canonical input."
)


class WidgetCampaignIdentity(BaseModel):
    """Replay identity uses exact textual IDs, never display metadata.

    Extra integrator context is ignored on replay; missing or non-string IDs
    cannot authorize reuse. UUID normalization would widen the existing check.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    campaign_id: str
    campaign_contact_id: str
    campaign_attempt_id: str


class WidgetCampaignContext(WidgetCampaignIdentity):
    """Campaign-owned context written when starting its conversation."""

    campaign_name: str | None = None


class WidgetDispatchConflict(Exception):
    """A stable campaign-attempt conversation belongs to different input."""


class WidgetChannelAdapter:
    """Dispatches campaign outreach as widget chat conversations.

    Creates a conversation between the campaign's agent and the contact,
    with the campaign's initial message. The contact sees the message
    when they connect via the widget.
    """

    channel: str = CampaignChannel.WIDGET.value
    replay_policy: ChannelReplayPolicy = ChannelReplayPolicy.REPLAY_SAFE

    async def validate_campaign(self, campaign: CampaignInDb) -> list[str]:
        errors: list[str] = []
        if not campaign.agent_id:
            errors.append("Widget campaigns require an agent.")
        return errors

    async def validate_contact(self, contact: CampaignContactInDb) -> bool:
        return bool(contact.contact_address and contact.contact_address.strip())

    async def recover_dispatch(
        self,
        campaign: CampaignInDb,
        contact: CampaignContactInDb,
        attempt_id: UUID,
    ) -> ChannelDispatchResult | None:
        async with start_transaction(ro=True) as session:
            conversation = await _find_attempt_conversation(
                session,
                organization_id=campaign.organization_id,
                attempt_id=attempt_id,
            )
        if conversation is None:
            return None
        _require_matching_conversation(
            conversation,
            campaign_id=campaign.id,
            contact_id=contact.id,
            attempt_id=attempt_id,
        )
        return ChannelDispatchResult(
            state=ChannelDispatchState.ACCEPTED, tracking_id=str(conversation.id)
        )

    async def dispatch(
        self,
        campaign: CampaignInDb,
        contact: CampaignContactInDb,
        rendered_message: Optional[str],
        attempt_id: UUID,
    ) -> ChannelDispatchResult:
        """Create a conversation and send the initial message from the agent."""
        from eylo.modules.conversations.models.conversations import (
            ConversationChannels,
        )
        from eylo.modules.conversations.schemas.conversations import (
            ConversationInitialMessage,
            ConversationInitialMessageContent,
            ConversationParticipant,
            ConversationStartRequest,
        )
        from eylo.modules.conversations.schemas.participants import ParticipantKind
        from eylo.modules.conversations.services.conversations import (
            ConversationBaseService,
        )

        message_text = rendered_message or "Hello!"

        # Build the conversation start request: agent → contact
        external_id = _attempt_external_id(attempt_id)
        request = ConversationStartRequest.model_validate(
            {
                "from": ConversationParticipant(
                    kind=ParticipantKind.AGENT,
                    id=campaign.agent_id,
                ),
                "to": ConversationParticipant(
                    kind=ParticipantKind.CONTACT,
                    id=contact.contact_id,
                    external_id=contact.contact_address,
                ),
                "channel": ConversationChannels.WIDGET,
                "message": ConversationInitialMessage(
                    content=[
                        ConversationInitialMessageContent(
                            type="text",
                            text=message_text,
                        )
                    ]
                ),
                "context": WidgetCampaignContext(
                    campaign_id=str(campaign.id),
                    campaign_name=campaign.name,
                    campaign_contact_id=str(contact.id),
                    campaign_attempt_id=str(attempt_id),
                ).model_dump(mode="json", exclude_none=True),
                "external_id": external_id,
            }
        )

        try:
            from eylo.modules.templates.domain import TemplateConsumerKind
            from eylo.pipelines.agents import build_executable_agent_resolver

            async with start_transaction() as session:
                await session.execute(
                    text(
                        "SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"
                    ),
                    {
                        "identity": (
                            f"widget-campaign:{campaign.organization_id}:{attempt_id}"
                        )
                    },
                )
                conversation = await _find_attempt_conversation(
                    session,
                    organization_id=campaign.organization_id,
                    attempt_id=attempt_id,
                )
                if conversation is not None:
                    _require_matching_conversation(
                        conversation,
                        campaign_id=campaign.id,
                        contact_id=contact.id,
                        attempt_id=attempt_id,
                    )
                    return ChannelDispatchResult(
                        state=ChannelDispatchState.ACCEPTED,
                        tracking_id=str(conversation.id),
                    )

                conv_service = ConversationBaseService()
                resolved_agent = await build_executable_agent_resolver(
                    session
                ).resolve_exact(
                    organization_id=campaign.organization_id,
                    agent_id=campaign.agent_id,
                    revision=campaign.agent_revision,
                    consumer_kind=TemplateConsumerKind.CONVERSATIONAL_TEXT,
                )
                conversation = await conv_service.start_conversation(
                    organization_id=campaign.organization_id,
                    request=request,
                    resolved_agent=resolved_agent,
                )
            logger.info(
                "Widget campaign dispatched: campaign=%s contact=%s conversation=%s",
                campaign.id,
                contact.id,
                conversation.id,
            )
            return ChannelDispatchResult(
                state=ChannelDispatchState.ACCEPTED, tracking_id=str(conversation.id)
            )
        except WidgetDispatchConflict:
            raise
        except Exception as error:
            logger.error(
                "Widget dispatch failed campaign=%s contact=%s error_type=%s",
                campaign.id,
                contact.id,
                type(error).__name__,
            )
            raise


def _attempt_external_id(attempt_id: UUID) -> str:
    return f"campaign-attempt:{attempt_id}"


async def _find_attempt_conversation(
    session: AsyncSession,
    *,
    organization_id: UUID,
    attempt_id: UUID,
) -> ConversationsModel | None:
    return await session.scalar(
        select(ConversationsModel).where(
            ConversationsModel.organization_id == organization_id,
            ConversationsModel.external_id == _attempt_external_id(attempt_id),
        )
    )


def _require_matching_conversation(
    conversation: ConversationsModel,
    *,
    campaign_id: UUID,
    contact_id: UUID,
    attempt_id: UUID,
) -> None:
    try:
        context = WidgetCampaignIdentity.model_validate(
            (conversation.meta or {}).get("context")
        )
    except ValidationError:
        raise WidgetDispatchConflict(_DISPATCH_CONFLICT_MESSAGE) from None
    if (
        context.campaign_id != str(campaign_id)
        or context.campaign_contact_id != str(contact_id)
        or context.campaign_attempt_id != str(attempt_id)
    ):
        raise WidgetDispatchConflict(_DISPATCH_CONFLICT_MESSAGE)


# Type check
_: CampaignChannelAdapter = WidgetChannelAdapter()
