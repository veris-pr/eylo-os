"""Probe detached LLM config without retaining a transaction during vendor I/O."""

from uuid import UUID

from pydantic import ValidationError

from eylo.common.contracts.llm_verification import (
    LLMProviderVerification,
    LLMVerificationError,
    LLMVerificationInput,
)
from eylo.common.database import current_transaction, start_transaction
from eylo.modules.llm_configs.service import to_llm_provider_config
from eylo.modules.llm_configs.verification import LLMVerificationResult
from eylo.modules.llm_configs.wiring import build_llm_config_service
from eylo.sockets.llm.verification import LLMCredentialVerifier


class LLMConfigVerificationService:
    """Own short read/write scopes; a stale successful probe cannot mark a new revision."""

    def __init__(self, verifier: LLMCredentialVerifier) -> None:
        self._verifier = verifier

    async def verify(
        self, *, organization_id: UUID, config_id: UUID
    ) -> LLMVerificationResult:
        if current_transaction() is not None:
            raise LLMVerificationError(
                "LLM verification requires an independent transaction scope."
            )
        async with start_transaction(ro=True) as db:
            stored = await build_llm_config_service(db).get(
                organization_id=organization_id, config_id=config_id
            )
            config = to_llm_provider_config(stored)
        material = LLMVerificationInput(
            provider=config.provider,
            generation=config.generation,
            secrets=config.secrets,
            region=config.region,
        )
        receipt = await self._verifier.verify(material)
        try:
            receipt = LLMProviderVerification.model_validate(receipt)
        except ValidationError:
            raise LLMVerificationError("LLM provider verification failed.") from None
        if (
            receipt.provider is not config.provider
            or receipt.model is not config.generation.model
        ):
            raise LLMVerificationError(
                "LLM verification receipt does not match its config."
            )
        async with start_transaction() as db:
            verified = await build_llm_config_service(db).mark_verified(
                organization_id=organization_id,
                config_id=config_id,
                expected_revision=stored.revision,
            )
            if verified.verified_at is None:
                raise LLMVerificationError("LLM verification timestamp is missing.")
            return LLMVerificationResult(
                provider=receipt.provider,
                model=receipt.model,
                revision=verified.revision,
                verified_at=verified.verified_at,
            )


def build_llm_verification_service() -> LLMConfigVerificationService:
    """Compose native SDK verification without a request-scoped DB session."""
    return LLMConfigVerificationService(LLMCredentialVerifier())
