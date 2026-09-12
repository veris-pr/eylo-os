"""Transport orchestration for authenticated outbound voice calls."""

import logging
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException

from eylo.common.contracts.provider_config import ProviderConfigError
from eylo.common.revisions import DefinitionRevisionError
from eylo.modules.agents.exceptions import AgentNotFoundError
from eylo.modules.telephony.constants import CALL_IDEMPOTENCY_KEY_MAX_LENGTH
from eylo.modules.telephony.schemas import OutboundCallRequest, OutboundCallResult
from eylo.pipelines.telephony.call_control import VoiceService

logger = logging.getLogger(__name__)


class VoiceController:
    """Controller for generic voice telephony operations.

    This controller handles the HTTP interface for voice operations,
    delegating business logic to the VoiceService.
    """

    def __init__(self) -> None:
        self.service = VoiceService()

    async def outbound_call(
        self,
        body: OutboundCallRequest,
        organization_id: UUID,
        idempotency_key: str,
    ) -> OutboundCallResult:
        """Initiate a call through the agent's organization-owned number."""
        try:
            idempotency_key = idempotency_key.strip()

            if (
                not idempotency_key
                or len(idempotency_key) > CALL_IDEMPOTENCY_KEY_MAX_LENGTH
            ):
                raise HTTPException(
                    status_code=400,
                    detail="A bounded Idempotency-Key header is required.",
                )

            result = await self.service.initiate_outbound_call(
                call_id=uuid5(
                    NAMESPACE_URL,
                    f"eylo:telephony-call:v1:{organization_id}:{idempotency_key}",
                ),
                to_number=body.to_number,
                agent_id=body.agent_id,
                organization_id=organization_id,
                initial_message=body.initial_message,
                context=body.context,
            )
            return result

        except (HTTPException, ProviderConfigError):
            raise
        except AgentNotFoundError:
            raise HTTPException(status_code=404) from None
        except DefinitionRevisionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except Exception as error:
            logger.error(
                "Outbound call request failed error_type=%s",
                type(error).__name__,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to initiate outbound call. Check server logs.",
            ) from None
