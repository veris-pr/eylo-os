"""Cerebras-native LLM requests, bounded rate-limit retry, and resource ownership."""

import asyncio
import json
import logging
import math
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from cerebras.cloud.sdk import AsyncCerebras, AsyncStream, RateLimitError
from cerebras.cloud.sdk.types.chat.chat_completion import ChatCompletion
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    CompletionCreateParams,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    MessageAssistantMessageRequestToolCallFunctionTyped as ToolFunctionCall,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    MessageAssistantMessageRequestToolCallTyped as ToolCall,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    MessageAssistantMessageRequestTyped as AssistantMessage,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    MessageSystemMessageRequestTyped as SystemMessage,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    MessageToolMessageRequestTyped as ToolMessage,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    MessageUserMessageRequestContentUnionMember1ImageURLContentImageURLTyped as ImageURL,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    MessageUserMessageRequestContentUnionMember1ImageURLContentTyped as UserImage,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    MessageUserMessageRequestContentUnionMember1TextContentTyped as UserText,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    MessageUserMessageRequestTyped as UserMessage,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    ToolFunctionTyped as ToolFunction,
)
from cerebras.cloud.sdk.types.chat.completion_create_params import (
    ToolTyped as Tool,
)
from pydantic import JsonValue, TypeAdapter

from eylo.common.contracts.llm_catalog import LLMModels
from eylo.common.contracts.llm_runtime import LLMInferenceConfig
from eylo.common.contracts.message_content import (
    AssistantMessageContent,
    TextContent,
    ToolResultMessageContent,
    ToolUseMessageContent,
    UserMessageContent,
    WidgetMessageContent,
    WidgetResponseMessageContent,
)
from eylo.common.contracts.messages import MessageInDb, MessageKind
from eylo.common.contracts.tool_record import ToolRecord
from eylo.sockets.llm.base import LLMVendorAdapter
from eylo.sockets.llm.config import require_model
from eylo.sockets.llm.schemas import LLMResponse
from eylo.sockets.llm.tool_content import serialize_tool_content
from eylo.sockets.llm.vendors.cerebras_responses import (
    CEREBRAS_VENDOR,
    CerebrasResponseError,
    CerebrasResponseErrorKind,
    CerebrasStream,
    completion_response,
)

logger = logging.getLogger(__name__)
_MAX_RETRIES = 3
_BASE_DELAY_S = 1.0
_MAX_DELAY_S = 10.0
_SCHEMA = TypeAdapter(dict[str, JsonValue])
_SCHEMA_MAP_KEYWORDS = frozenset(
    {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
)
_SCHEMA_LIST_KEYWORDS = frozenset({"anyOf", "oneOf", "allOf", "prefixItems"})
_SCHEMA_SINGLE_KEYWORDS = frozenset(
    {
        "items",
        "additionalProperties",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
    }
)
_UNSUPPORTED_ARRAY_KEYWORDS = frozenset({"minItems", "maxItems"})
type CerebrasMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage


def _strict_schema(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Transform schema nodes, never property names, examples, defaults, or enum data."""
    result: dict[str, JsonValue] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_ARRAY_KEYWORDS:
            continue
        if key in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            result[key] = {
                name: _strict_schema(child) if isinstance(child, dict) else child
                for name, child in value.items()
            }
        elif key in _SCHEMA_LIST_KEYWORDS and isinstance(value, list):
            result[key] = [
                _strict_schema(child) if isinstance(child, dict) else child
                for child in value
            ]
        elif key in _SCHEMA_SINGLE_KEYWORDS and isinstance(value, dict):
            result[key] = _strict_schema(value)
        else:
            result[key] = value
    schema_type = result.get("type")
    if schema_type == "object" or (
        isinstance(schema_type, list) and "object" in schema_type
    ):
        result["additionalProperties"] = False
        result.setdefault("properties", {})
    return result


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    """Accept seconds or HTTP dates; invalid hints use the existing bounded backoff."""
    fallback = min(_BASE_DELAY_S * (2**attempt), _MAX_DELAY_S)
    if retry_after is None:
        return fallback
    try:
        seconds = float(retry_after)
    except ValueError:
        try:
            date = parsedate_to_datetime(retry_after)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            seconds = (date - datetime.now(UTC)).total_seconds()
        except (ValueError, OverflowError, TypeError):
            return fallback
    if not math.isfinite(seconds) or seconds < 0:
        return fallback
    return min(seconds, _MAX_DELAY_S)


async def _call_with_retry[Result](
    operation: Callable[[], Awaitable[Result]],
) -> Result:
    """Retain the existing 429-only outer retry budget; never replay stream consumption."""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await operation()
        except RateLimitError as error:
            if attempt == _MAX_RETRIES:
                raise
            delay = _retry_delay(error.response.headers.get("retry-after"), attempt)
            logger.warning(
                "Cerebras rate limit attempt=%d max_retries=%d delay_seconds=%.1f",
                attempt + 1,
                _MAX_RETRIES,
                delay,
            )
            await asyncio.sleep(delay)
    raise AssertionError("Retry loop must return or raise")


class CerebrasAdapter(LLMVendorAdapter):
    """Keep native SDK unions and schema rules inside the Cerebras boundary."""

    vendor_name = CEREBRAS_VENDOR

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_client(self) -> AsyncCerebras:
        # SDK 1.67.0 otherwise performs synchronous HTTP/retries in __init__.
        return AsyncCerebras(api_key=self._api_key, warm_tcp_connection=False)

    def transform_messages_to_vendor(
        self, messages: list[MessageInDb], system_prompt: str
    ) -> tuple[str, list[CerebrasMessage]]:
        vendor_messages: list[CerebrasMessage] = []
        if system_prompt:
            vendor_messages.append(SystemMessage(role="system", content=system_prompt))
        for message in self._validate_message_sequence(messages):
            content = message.content
            if message.kind == MessageKind.USER:
                if isinstance(content, UserMessageContent):
                    parts: list[UserText | UserImage] = []
                    for block in content.content:
                        if isinstance(block, TextContent):
                            parts.append(UserText(type="text", text=block.text))
                        else:
                            parts.append(
                                UserImage(
                                    type="image_url",
                                    image_url=ImageURL(url=block.image_url.url),
                                )
                            )
                    vendor_messages.append(UserMessage(role="user", content=parts))
                elif isinstance(content, WidgetResponseMessageContent):
                    vendor_messages.append(
                        UserMessage(role="user", content=content.get_text_content())
                    )
                else:
                    raise TypeError("Cerebras requires typed user content")
            elif message.kind == MessageKind.ASSISTANT:
                if not isinstance(
                    content, (AssistantMessageContent, WidgetMessageContent)
                ):
                    raise TypeError("Cerebras requires typed assistant content")
                vendor_messages.append(
                    AssistantMessage(
                        role="assistant", content=content.get_text_content()
                    )
                )
            elif message.kind == MessageKind.TOOL_USE:
                if not isinstance(content, ToolUseMessageContent):
                    raise TypeError("Cerebras requires typed tool-use content")
                call = content.content
                vendor_messages.append(
                    AssistantMessage(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            ToolCall(
                                id=call.id,
                                type="function",
                                function=ToolFunctionCall(
                                    name=call.name, arguments=json.dumps(call.input)
                                ),
                            )
                        ],
                    )
                )
            elif message.kind == MessageKind.TOOL_RESULT:
                if not isinstance(content, ToolResultMessageContent):
                    raise TypeError("Cerebras requires typed tool-result content")
                for result in content.content:
                    vendor_messages.append(
                        ToolMessage(
                            role="tool",
                            tool_call_id=result.tool_use_id,
                            content=serialize_tool_content(result.content),
                        )
                    )
        return system_prompt, vendor_messages

    def transform_tools_to_vendor(self, tools: Sequence[ToolRecord]) -> list[Tool]:
        """Keep the platform's required/optional distinction in native strict schemas."""
        vendor_tools: list[Tool] = []
        for tool in tools:
            config = tool.llm_config
            schema = _SCHEMA.validate_python(
                config.input_schema.to_json_schema(), strict=True
            )
            vendor_tools.append(
                Tool(
                    type="function",
                    function=ToolFunction(
                        name=config.name,
                        description=config.description,
                        parameters=_strict_schema(schema),
                        strict=True,
                    ),
                )
            )
        return vendor_tools

    def _request(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        config: LLMInferenceConfig,
    ) -> CompletionCreateParams:
        _, vendor_messages = self.transform_messages_to_vendor(messages, system_prompt)
        params: CompletionCreateParams = {
            "model": require_model(config),
            "messages": vendor_messages,
        }
        generation = config.generation
        if generation.max_tokens is not None:
            params["max_completion_tokens"] = generation.max_tokens
        if generation.temperature is not None:
            params["temperature"] = generation.temperature
        if generation.top_p is not None:
            params["top_p"] = generation.top_p
        if generation.stop_sequences is not None:
            params["stop"] = list(generation.stop_sequences)
        if tools:
            params["tools"] = self.transform_tools_to_vendor(tools)
            params["tool_choice"] = "auto"
        if generation.model == LLMModels.CEREBRAS_ZAI_GLM_4_7:
            params["clear_thinking"] = False
            if tools:
                params["parallel_tool_calls"] = True
        return params

    def transform_response_to_platform(self, response: ChatCompletion) -> LLMResponse:
        return completion_response(response)

    async def run_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> LLMResponse:
        params = self._request(messages, system_prompt, tools, llm_config)
        params["stream"] = False
        async with self.get_client() as client:
            response = await _call_with_retry(
                lambda: client.chat.completions.create(**params)
            )
            if isinstance(response, AsyncStream):
                raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
            return self.transform_response_to_platform(response)

    async def run_streaming_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> AsyncGenerator[LLMResponse, None]:
        params = self._request(messages, system_prompt, tools, llm_config)
        params["stream"] = True
        params["stream_options"] = {"include_usage": True}
        state = CerebrasStream()
        async with self.get_client() as client:
            stream = await _call_with_retry(
                lambda: client.chat.completions.create(**params)
            )
            if not isinstance(stream, AsyncStream):
                raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
            async with stream:
                async for chunk in stream:
                    partial = state.accept(chunk)
                    if partial is not None:
                        yield partial
                final = state.complete()
        yield final
