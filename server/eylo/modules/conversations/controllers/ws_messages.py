"""Transport orchestration for the `conversations` domain."""

import logging
from hashlib import sha256
from uuid import UUID

import arrow
import nh3 as bleach
from fastapi import status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.messages import MessageInteraction, MessageMeta
from eylo.common.contracts.session_timeline import SessionTimelineEvent
from eylo.common.contracts.websocket import (
    WsEventAction,
    WsRequestEvent,
    WsResponse,
    build_ws_error_response,
)
from eylo.common.database import start_transaction
from eylo.common.utils.context_sanitizer import sanitize_context
from eylo.modules.agent_runs.absurd import spawn_agent_run
from eylo.modules.agent_runs.domain import (
    ExecutionBudgetNotConfigured,
    ExecutionBudgetUnavailable,
    InitiatingPrincipalKind,
    InitiatingPrincipalRef,
)
from eylo.modules.conversations.exceptions import ConversationNotFound
from eylo.modules.conversations.schemas.message_content import (
    UserMessageContent,
    WidgetResponseMessageContent,
)
from eylo.modules.conversations.schemas.messages import (
    MessageApiResponseSchema,
    MessageContentKind,
    MessageCreate,
    MessageKind,
)
from eylo.modules.conversations.schemas.participants import ParticipantKind
from eylo.modules.conversations.schemas.run_context import ConversationRunContext
from eylo.modules.conversations.schemas.timeline import (
    ConversationParticipationTimelineFact,
)
from eylo.modules.conversations.schemas.websocket import (
    WsMessageEvent,
    WsMessageFeedbackEvent,
    WsMessageQueryEvent,
)
from eylo.modules.conversations.services.conversations import (
    ConversationBaseService,
)
from eylo.modules.conversations.services.messages import MessageService
from eylo.modules.conversations.services.participants import (
    ConversationParticipantService,
)
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.modules.session_context.schemas import SessionContext
from eylo.modules.user_sessions.events import file_user_session_fact
from eylo.modules.user_sessions.service import UserSessionService
from eylo.pipelines.conversation.widget_responses import (
    WidgetResponseRejected,
    require_valid_widget_response,
)

logger = logging.getLogger(__name__)


def _message_idempotency_key(
    *,
    conversation_id: UUID,
    session_id: str,
    request_id: str | None,
    timestamp: float,
) -> str:
    """Derive a stable bounded key without persisting a session credential."""
    request_identity = request_id or str(timestamp)
    digest = sha256(f"{session_id}:{request_identity}".encode()).hexdigest()
    return f"websocket:{conversation_id}:{digest}"


def _not_configured_response(
    error: NotConfiguredError,
    *,
    ctx: SessionContext,
    request_id: str | None,
) -> WsResponse:
    return WsResponse(
        status=status.HTTP_409_CONFLICT,
        kind=WsEventAction.ERROR,
        data={
            "capability": error.capability.value,
            "missing": list(error.missing),
            "configure_via": error.configure_via,
        },
        organization_id=ctx.organization_id,
        session_id=ctx.session_id,
        request_id=request_id,
    )


def _budget_rejection_response(
    _error: ExecutionBudgetNotConfigured | ExecutionBudgetUnavailable,
    *,
    ctx: SessionContext,
    request_id: str | None,
) -> WsResponse:
    return WsResponse(
        status=status.HTTP_409_CONFLICT,
        kind=WsEventAction.ERROR,
        data={
            "capability": "agent_execution",
            "message": "Agent execution is temporarily unavailable.",
        },
        organization_id=ctx.organization_id,
        session_id=ctx.session_id,
        request_id=request_id,
    )


def _invalid_message_response(
    error: ValidationError | WidgetResponseRejected,
    *,
    ctx: SessionContext,
    request_id: str | None,
) -> WsResponse:
    """Reject client input without logging submitted values or validation details."""
    logger.info(
        "Message input rejected request_id=%s error_type=%s",
        request_id,
        type(error).__name__,
    )
    return WsResponse(
        status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        kind=WsEventAction.ERROR,
        data={
            "message": (
                "The submitted message or interaction is invalid. "
                "Check your input and try again."
            )
        },
        organization_id=ctx.organization_id,
        session_id=ctx.session_id,
        request_id=request_id,
    )


class MessageWsController:
    def __init__(self, db: AsyncSession | None = None) -> None:
        self.conversation_base_service = ConversationBaseService(db)
        self.conversation_participant_service = ConversationParticipantService(db)
        self.message_service = MessageService(db)

    async def _conversation_not_found(
        self,
        event: WsRequestEvent,
        ctx: SessionContext,
    ) -> WsResponse:
        return build_ws_error_response(
            event,
            organization_id=ctx.organization_id,
            session_id=ctx.session_id,
            message="Conversation not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    async def handle_message_query(
        self,
        event: WsRequestEvent,
        ctx: SessionContext,
        contact_id: UUID | None,
    ) -> WsResponse:
        try:
            request = WsMessageQueryEvent.model_validate(event.data or {})
            if not request.filters.conversation_ids:
                return await self._conversation_not_found(event, ctx)

            if not contact_id or ctx.user_session_id is None:
                return await self._conversation_not_found(event, ctx)
            if any(
                not ctx.allows_conversation(conversation_id)
                for conversation_id in request.filters.conversation_ids
            ):
                return await self._conversation_not_found(event, ctx)

            async with start_transaction(ro=True):
                try:
                    conversations = await self.conversation_base_service.resolve_by_organization_contact_and_ids(
                        organization_id=ctx.organization_id,
                        contact_id=contact_id,
                        conversation_ids=request.filters.conversation_ids,
                    )
                except ConversationNotFound:
                    return await self._conversation_not_found(event, ctx)
                messages_indb = await self.message_service.list_by_conversations(
                    [conversation.id for conversation in conversations],
                    kind=[MessageKind.USER, MessageKind.ASSISTANT],
                )

            return WsResponse(
                status=status.HTTP_200_OK,
                kind=WsEventAction.MESSAGE_QUERY,
                data=[
                    MessageApiResponseSchema.model_validate(msg).model_dump(
                        by_alias=True
                    )
                    for msg in messages_indb
                ],
                organization_id=ctx.organization_id,
                session_id=ctx.session_id,
                request_id=event.request_id,
            )
        except Exception as error:
            logger.error(
                "Message query failed error_type=%s",
                type(error).__name__,
            )
            return build_ws_error_response(
                event,
                organization_id=ctx.organization_id,
                session_id=ctx.session_id,
            )

    async def handle_message(
        self,
        event: WsRequestEvent,
        ctx: SessionContext,
        contact_id: UUID | None,
    ) -> WsResponse:
        """Handle text and structured widget response message events."""
        try:
            try:
                request = WsMessageEvent.model_validate(event.data or {})
            except ValidationError as error:
                return _invalid_message_response(
                    error, ctx=ctx, request_id=event.request_id
                )
            user_session_id = ctx.user_session_id
            if contact_id is None or user_session_id is None:
                return await self._conversation_not_found(event, ctx)
            if not ctx.allows_conversation(request.conversation_id):
                return await self._conversation_not_found(event, ctx)

            async with start_transaction(ro=True):
                try:
                    conversation_indb = await self.conversation_base_service.get_by_organization_contact_and_id(
                        organization_id=ctx.organization_id,
                        contact_id=contact_id,
                        pk=request.conversation_id,
                    )
                except ConversationNotFound:
                    return await self._conversation_not_found(event, ctx)
                participants = (
                    await self.conversation_participant_service.list_by_conversation(
                        conversation_indb.id
                    )
                )

            logger.info(
                "Message received organization_id=%s conversation_id=%s",
                ctx.organization_id,
                request.conversation_id,
            )

            contact_participant = next(
                (
                    participant
                    for participant in participants
                    if participant.entity_kind == ParticipantKind.CONTACT
                    and participant.entity_id == str(contact_id)
                    and participant.is_active
                ),
                None,
            )
            if not contact_participant:
                return await self._conversation_not_found(event, ctx)
            agent_participant = next(
                (
                    participant
                    for participant in participants
                    if participant.entity_kind == ParticipantKind.AGENT
                    and participant.is_primary
                    and participant.is_active
                    and participant.agent_id is not None
                    and participant.agent_revision is not None
                ),
                None,
            )
            if (
                agent_participant is None
                or agent_participant.agent_id is None
                or agent_participant.agent_revision is None
            ):
                return await self._conversation_not_found(event, ctx)
            message_indb = None
            if (
                request.content_kind == MessageContentKind.TEXT
                and request.text is not None
            ):
                request.text = bleach.clean(request.text.strip())
            async with start_transaction() as db:
                user_sessions = UserSessionService(db)
                await user_sessions.require_contact_session(
                    organization_id=ctx.organization_id,
                    contact_id=contact_id,
                    user_session_id=user_session_id,
                )
                conversation_link_created = await user_sessions.link_conversation(
                    organization_id=ctx.organization_id,
                    user_session_id=user_session_id,
                    conversation_id=conversation_indb.id,
                )
                if conversation_link_created:
                    await file_user_session_fact(
                        db,
                        organization_id=ctx.organization_id,
                        user_session_id=user_session_id,
                        subject_type="conversation",
                        subject_id=conversation_indb.id,
                        event_type=SessionTimelineEvent.CONVERSATION_CONTINUED,
                        payload=ConversationParticipationTimelineFact(
                            channel=conversation_indb.channel,
                            agent_id=agent_participant.agent_id,
                        ).to_payload(),
                    )
                message_content: UserMessageContent | WidgetResponseMessageContent
                if request.content_kind == MessageContentKind.WIDGET_RESPONSE:
                    if request.content is None:
                        raise WidgetResponseRejected(
                            "A widget response requires content."
                        )
                    message_content = request.content
                    await require_valid_widget_response(
                        db,
                        conversation_id=conversation_indb.id,
                        parent_message_id=request.parent_message_id,
                        response=message_content,
                    )
                else:
                    message_content = UserMessageContent(content=request.text or "")

                message = MessageCreate(
                    conversation_id=conversation_indb.id,
                    user_session_id=user_session_id,
                    sender_participant_id=contact_participant.id,
                    kind=MessageKind.USER,
                    content_kind=request.content_kind,
                    content=message_content,
                    parent_message_id=request.parent_message_id,
                    external_id=event.request_id,
                    meta=MessageMeta.model_validate(
                        {
                            "context": sanitize_context(request.context) or {},
                            "role": MessageKind.USER.value.lower(),
                            "message": {
                                "content": (
                                    [{"kind": "TEXT", "value": request.text}]
                                    if request.content_kind == MessageContentKind.TEXT
                                    else [
                                        {
                                            "kind": request.content_kind.value,
                                            "value": message_content.model_dump(
                                                mode="json"
                                            ),
                                        }
                                    ]
                                )
                            },
                            "interaction": MessageInteraction(
                                channel=ctx.channel,
                                is_voice=ctx.is_voice,
                            ),
                        }
                    ),
                    created_at=arrow.utcnow().datetime,
                )
                goal = self.message_service.get_message_content(message.content)
                filing = await self.message_service.create_with_agent_run(
                    message=message,
                    principal=InitiatingPrincipalRef(
                        organization_id=ctx.organization_id,
                        kind=InitiatingPrincipalKind.CONTACT,
                        principal_id=contact_id,
                    ),
                    agent_id=agent_participant.agent_id,
                    agent_revision=agent_participant.agent_revision,
                    context_manifest=ConversationRunContext(
                        conversation_id=conversation_indb.id,
                        channel=ctx.channel,
                        is_voice=ctx.is_voice,
                    ).model_dump(mode="json"),
                    goal=goal or "Handle the submitted conversation message.",
                    idempotency_key=_message_idempotency_key(
                        conversation_id=conversation_indb.id,
                        session_id=ctx.session_id,
                        request_id=event.request_id,
                        timestamp=event.timestamp,
                    ),
                )
                message_indb = filing.message

            try:
                await spawn_agent_run(
                    organization_id=ctx.organization_id,
                    run_id=filing.run_id,
                )
            except Exception as error:  # noqa: BLE001 - PostgreSQL recovery owns retry
                logger.error(
                    "AgentRun %s remains queued after direct spawn failed "
                    "error_type=%s",
                    filing.run_id,
                    type(error).__name__,
                )

            return WsResponse(
                status=status.HTTP_200_OK,
                kind=WsEventAction.MESSAGE_CREATED,
                data=MessageApiResponseSchema.model_validate(message_indb).model_dump(
                    by_alias=True
                ),
                organization_id=ctx.organization_id,
                session_id=ctx.session_id,
                request_id=event.request_id,
            )
        except WidgetResponseRejected as error:
            return _invalid_message_response(
                error, ctx=ctx, request_id=event.request_id
            )
        except NotConfiguredError as error:
            return _not_configured_response(
                error,
                ctx=ctx,
                request_id=event.request_id,
            )
        except (
            ExecutionBudgetNotConfigured,
            ExecutionBudgetUnavailable,
        ) as error:
            return _budget_rejection_response(
                error,
                ctx=ctx,
                request_id=event.request_id,
            )
        except Exception as error:
            logger.error(
                "Message handling failed error_type=%s",
                type(error).__name__,
            )
            return build_ws_error_response(
                event,
                organization_id=ctx.organization_id,
                session_id=ctx.session_id,
            )

    async def handle_message_feedback(
        self,
        event: WsRequestEvent,
        ctx: SessionContext,
        contact_id: UUID | None,
    ) -> WsResponse:
        try:
            request = WsMessageFeedbackEvent.model_validate(event.data or {})
            if not contact_id:
                return await self._conversation_not_found(event, ctx)
            if not ctx.allows_conversation(request.conversation_id):
                return await self._conversation_not_found(event, ctx)

            async with start_transaction():
                updated_message = await self.message_service.update_request_feedback_by_organization_and_contact(
                    organization_id=ctx.organization_id,
                    contact_id=contact_id,
                    conversation_id=request.conversation_id,
                    request_id=request.message_request_id,
                    feedback=request.request_feedback,
                )
            if not updated_message:
                return await self._conversation_not_found(event, ctx)

            return WsResponse(
                status=status.HTTP_200_OK,
                kind=WsEventAction.MESSAGE_FEEDBACK,
                data=MessageApiResponseSchema.model_validate(
                    updated_message
                ).model_dump(by_alias=True),
                organization_id=ctx.organization_id,
                session_id=ctx.session_id,
                request_id=event.request_id,
            )
        except Exception as error:
            logger.error(
                "Message feedback failed error_type=%s",
                type(error).__name__,
            )
            return build_ws_error_response(
                event,
                organization_id=ctx.organization_id,
                session_id=ctx.session_id,
            )
