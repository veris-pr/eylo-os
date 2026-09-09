"""LLM verification use-case port and the revisioned domain result."""

from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field

from eylo.common.contracts.llm_verification import LLMProviderVerification


class LLMVerificationResult(LLMProviderVerification):
    """Successful probe committed against the exact tested config revision."""

    revision: int = Field(ge=1)
    verified_at: AwareDatetime


class LLMConfigVerifier(Protocol):
    """Verify outside a DB transaction, then conditionally mark the tested revision."""

    async def verify(
        self, *, organization_id: UUID, config_id: UUID
    ) -> LLMVerificationResult: ...
