"""Live credential verification through official async provider SDKs.

API patterns follow current official SDK references:
- Anthropic and Bedrock: https://github.com/anthropics/anthropic-sdk-python
- Bedrock example: https://github.com/anthropics/anthropic-sdk-python/blob/main/examples/bedrock.py
- Cerebras: https://github.com/Cerebras/cerebras-cloud-sdk-python#async-usage
- Gemini: https://github.com/googleapis/python-genai#client-context-managers
- Groq: https://github.com/groq/groq-python#async-usage
- OpenAI: https://github.com/openai/openai-python#async-usage
- Sarvam: https://pypi.org/project/sarvamai/0.1.28/
"""

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

import httpx
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock
from cerebras.cloud.sdk import AsyncCerebras, AsyncStream
from google import genai
from google.genai import types
from groq import AsyncGroq
from openai import AsyncOpenAI
from sarvamai import AsyncSarvamAI

from eylo.common.contracts.llm_catalog import LLMProviders
from eylo.common.contracts.llm_verification import (
    LLMProviderVerification,
    LLMVerificationError,
    LLMVerificationInput,
)
from eylo.sockets.llm.vendors.anthropic_responses import message_response
from eylo.sockets.llm.vendors.cerebras_responses import (
    completion_response as cerebras_response,
)
from eylo.sockets.llm.vendors.gemini_responses import (
    completion_response as gemini_response,
)
from eylo.sockets.llm.vendors.groq_responses import completion_response as groq_response
from eylo.sockets.llm.vendors.openai_chat_responses import (
    completion_response as openai_response,
)
from eylo.sockets.llm.vendors.openai_response_events import response_to_platform
from eylo.sockets.llm.vendors.sarvam_responses import (
    completion_response as sarvam_response,
)

_VERIFICATION_PROMPT = "Reply OK."
_VERIFICATION_TIMEOUT_SECONDS = 20.0

_MIN_VERIFICATION_TOKENS = 1
_OPENAI_RESPONSES_MIN_OUTPUT_TOKENS = 16
_VERIFICATION_RETRIES = 0
_Response = TypeVar("_Response")


class LLMCredentialVerifier:
    """Make one bounded, minimal generation call for a validated config."""

    async def verify(self, config: LLMVerificationInput) -> LLMProviderVerification:
        config = LLMVerificationInput.model_validate(config)
        handlers = {
            LLMProviders.ANTHROPIC: self._verify_anthropic,
            LLMProviders.BEDROCK: self._verify_bedrock,
            LLMProviders.CEREBRAS: self._verify_cerebras,
            LLMProviders.GEMINI: self._verify_gemini,
            LLMProviders.GROQ: self._verify_groq,
            LLMProviders.OPENAI: self._verify_openai,
            LLMProviders.OPENAI_RESPONSES: self._verify_openai_responses,
            LLMProviders.SARVAM: self._verify_sarvam,
        }
        try:
            await handlers[config.provider](config)
        except Exception:
            raise LLMVerificationError("LLM provider verification failed.") from None
        return LLMProviderVerification(
            provider=config.provider,
            model=config.generation.model,
        )

    async def _verify_anthropic(self, config: LLMVerificationInput) -> None:
        async with AsyncAnthropic(
            api_key=_api_key(config),
            timeout=_VERIFICATION_TIMEOUT_SECONDS,
            max_retries=_VERIFICATION_RETRIES,
        ) as client:
            response = await _with_timeout(
                client.messages.create(
                    model=config.generation.model.value,
                    max_tokens=_MIN_VERIFICATION_TOKENS,
                    messages=[{"role": "user", "content": _VERIFICATION_PROMPT}],
                )
            )
            message_response(response)

    async def _verify_bedrock(self, config: LLMVerificationInput) -> None:
        client = AsyncAnthropicBedrock(
            aws_access_key=_required_secret(config, "access_key_id"),
            aws_secret_key=_required_secret(config, "secret_access_key"),
            aws_session_token=config.secrets.get("session_token"),
            aws_region=config.region,
            timeout=_VERIFICATION_TIMEOUT_SECONDS,
            max_retries=_VERIFICATION_RETRIES,
        )
        async with client:
            response = await _with_timeout(
                client.messages.create(
                    model=config.generation.model.value,
                    max_tokens=_MIN_VERIFICATION_TOKENS,
                    messages=[{"role": "user", "content": _VERIFICATION_PROMPT}],
                )
            )
            message_response(response)

    async def _verify_cerebras(self, config: LLMVerificationInput) -> None:
        async with AsyncCerebras(
            api_key=_api_key(config),
            timeout=_VERIFICATION_TIMEOUT_SECONDS,
            max_retries=_VERIFICATION_RETRIES,
        ) as client:
            response = await _with_timeout(
                client.chat.completions.create(
                    model=config.generation.model.value,
                    messages=[{"role": "user", "content": _VERIFICATION_PROMPT}],
                    max_completion_tokens=_MIN_VERIFICATION_TOKENS,
                    stream=False,
                )
            )
            if isinstance(response, AsyncStream):
                await response.close()
                raise LLMVerificationError(
                    "LLM verification requires a complete response."
                )
            cerebras_response(response)

    async def _verify_gemini(self, config: LLMVerificationInput) -> None:
        client = genai.Client(api_key=_api_key(config))
        async_client = client.aio
        try:
            response = await _with_timeout(
                async_client.models.generate_content(
                    model=config.generation.model.value,
                    contents=_VERIFICATION_PROMPT,
                    config=types.GenerateContentConfig(
                        max_output_tokens=_MIN_VERIFICATION_TOKENS
                    ),
                )
            )
            gemini_response(response, model=config.generation.model.value)
        finally:
            try:
                await async_client.aclose()
            finally:
                client.close()

    async def _verify_groq(self, config: LLMVerificationInput) -> None:
        async with AsyncGroq(
            api_key=_api_key(config),
            timeout=_VERIFICATION_TIMEOUT_SECONDS,
            max_retries=_VERIFICATION_RETRIES,
        ) as client:
            response = await _with_timeout(
                client.chat.completions.create(
                    model=config.generation.model.value,
                    messages=[{"role": "user", "content": _VERIFICATION_PROMPT}],
                    max_completion_tokens=_MIN_VERIFICATION_TOKENS,
                )
            )
            groq_response(response)

    async def _verify_openai(self, config: LLMVerificationInput) -> None:
        async with AsyncOpenAI(
            api_key=_api_key(config),
            timeout=_VERIFICATION_TIMEOUT_SECONDS,
            max_retries=_VERIFICATION_RETRIES,
        ) as client:
            response = await _with_timeout(
                client.chat.completions.create(
                    model=config.generation.model.value,
                    messages=[{"role": "user", "content": _VERIFICATION_PROMPT}],
                    max_completion_tokens=_MIN_VERIFICATION_TOKENS,
                )
            )
            openai_response(response)

    async def _verify_openai_responses(self, config: LLMVerificationInput) -> None:
        async with AsyncOpenAI(
            api_key=_api_key(config),
            timeout=_VERIFICATION_TIMEOUT_SECONDS,
            max_retries=_VERIFICATION_RETRIES,
        ) as client:
            response = await _with_timeout(
                client.responses.create(
                    model=config.generation.model.value,
                    input=_VERIFICATION_PROMPT,
                    max_output_tokens=_OPENAI_RESPONSES_MIN_OUTPUT_TOKENS,
                )
            )
            response_to_platform(response)

    async def _verify_sarvam(self, config: LLMVerificationInput) -> None:
        async with httpx.AsyncClient(
            timeout=_VERIFICATION_TIMEOUT_SECONDS
        ) as http_client:
            client = AsyncSarvamAI(
                api_subscription_key=_api_key(config),
                timeout=_VERIFICATION_TIMEOUT_SECONDS,
                httpx_client=http_client,
            )
            response = await _with_timeout(
                client.chat.completions(
                    model=config.generation.model.value,
                    messages=[{"role": "user", "content": _VERIFICATION_PROMPT}],
                    max_tokens=_MIN_VERIFICATION_TOKENS,
                )
            )
            sarvam_response(response)


async def _with_timeout(request: Awaitable[_Response]) -> _Response:
    return await asyncio.wait_for(request, timeout=_VERIFICATION_TIMEOUT_SECONDS)


def _api_key(config: LLMVerificationInput) -> str:
    return _required_secret(config, "api_key")


def _required_secret(config: LLMVerificationInput, name: str) -> str:
    value = config.secrets.get(name)
    if value is None:
        raise LLMVerificationError("LLM provider verification failed.")
    return value
