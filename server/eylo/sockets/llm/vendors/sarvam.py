"""Sarvam-native text requests and explicitly owned HTTP and stream resources."""

import json
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Literal, Required, TypedDict

import httpx
from pydantic import JsonValue, TypeAdapter, ValidationError
from sarvamai import AsyncSarvamAI
from sarvamai.requests.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCallParams as ToolCall,
)
from sarvamai.requests.chat_completion_request_message import (
    ChatCompletionRequestMessageParams,
)
from sarvamai.requests.chat_completion_request_message import (
    ChatCompletionRequestMessage_AssistantParams as AssistantMessage,
)
from sarvamai.requests.chat_completion_request_message import (
    ChatCompletionRequestMessage_SystemParams as SystemMessage,
)
from sarvamai.requests.chat_completion_request_message import (
    ChatCompletionRequestMessage_ToolParams as ToolMessage,
)
from sarvamai.requests.chat_completion_request_message import (
    ChatCompletionRequestMessage_UserParams as UserMessage,
)
from sarvamai.requests.chat_completion_tool import ChatCompletionToolParams as Tool
from sarvamai.requests.function_call import FunctionCallParams as ToolFunctionCall
from sarvamai.requests.function_definition import (
    FunctionDefinitionParams as ToolFunction,
)
from sarvamai.types.create_chat_completion_response import CreateChatCompletionResponse

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
from eylo.sockets.llm.vendors.sarvam_responses import (
    SARVAM_VENDOR,
    SarvamResponseError,
    SarvamResponseErrorKind,
    SarvamStream,
    completion_response,
)

# Match the pinned SDK's existing default while owning the client explicitly.
_REQUEST_TIMEOUT_SECONDS = 60.0
_SCHEMA = TypeAdapter(dict[str, JsonValue])


class SarvamRequest(TypedDict, total=False):
    """Only configured, currently consumed native kwargs; omission stays omission."""

    model: Required[str]
    messages: Required[list[ChatCompletionRequestMessageParams]]
    max_tokens: int
    temperature: float
    top_p: float
    stop: list[str]
    tools: list[Tool]
    tool_choice: Literal["auto"]


class SarvamAdapter(LLMVendorAdapter):
    """The SDK has no public close method, so this adapter owns its HTTP client."""

    vendor_name = SARVAM_VENDOR

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @asynccontextmanager
    async def get_client(self) -> AsyncGenerator[AsyncSarvamAI, None]:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT_SECONDS, follow_redirects=True
        ) as http:
            yield AsyncSarvamAI(api_subscription_key=self._api_key, httpx_client=http)

    def transform_messages_to_vendor(
        self, messages: list[MessageInDb], system_prompt: str
    ) -> tuple[str, list[ChatCompletionRequestMessageParams]]:
        vendor_messages: list[ChatCompletionRequestMessageParams] = []
        if system_prompt:
            vendor_messages.append(SystemMessage(role="system", content=system_prompt))
        for message in self._validate_message_sequence(messages):
            content = message.content
            if message.kind == MessageKind.USER:
                if isinstance(content, UserMessageContent):
                    parts: list[str] = []
                    for block in content.content:
                        if not isinstance(block, TextContent):
                            raise TypeError(
                                "Sarvam chat requires text-only user content"
                            )
                        parts.append(block.text)
                    vendor_messages.append(
                        UserMessage(role="user", content="\n".join(parts))
                    )
                elif isinstance(content, WidgetResponseMessageContent):
                    vendor_messages.append(
                        UserMessage(role="user", content=content.get_text_content())
                    )
                else:
                    raise TypeError("Sarvam requires typed user content")
            elif message.kind == MessageKind.ASSISTANT:
                if not isinstance(
                    content, (AssistantMessageContent, WidgetMessageContent)
                ):
                    raise TypeError("Sarvam requires typed assistant content")
                vendor_messages.append(
                    AssistantMessage(
                        role="assistant", content=content.get_text_content()
                    )
                )
            elif message.kind == MessageKind.TOOL_USE:
                if not isinstance(content, ToolUseMessageContent):
                    raise TypeError("Sarvam requires typed tool-use content")
                call = content.content
                vendor_messages.append(
                    AssistantMessage(
                        role="assistant",
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
                    raise TypeError("Sarvam requires typed tool-result content")
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
        return [
            Tool(
                type="function",
                function=ToolFunction(
                    name=tool.llm_config.name,
                    description=tool.llm_config.description,
                    parameters=_SCHEMA.validate_python(
                        tool.llm_config.input_schema.to_json_schema(), strict=True
                    ),
                ),
            )
            for tool in tools
        ]

    def _request(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        config: LLMInferenceConfig,
    ) -> SarvamRequest:
        _, vendor_messages = self.transform_messages_to_vendor(messages, system_prompt)
        params: SarvamRequest = {
            "model": require_model(config),
            "messages": vendor_messages,
        }
        generation = config.generation
        if generation.max_tokens is not None:
            params["max_tokens"] = generation.max_tokens
        if generation.temperature is not None:
            params["temperature"] = generation.temperature
        if generation.top_p is not None:
            params["top_p"] = generation.top_p
        if generation.stop_sequences is not None:
            params["stop"] = list(generation.stop_sequences)
        if tools:
            params["tools"] = self.transform_tools_to_vendor(tools)
            params["tool_choice"] = "auto"
        return params

    def transform_response_to_platform(
        self, response: CreateChatCompletionResponse
    ) -> LLMResponse:
        return completion_response(response)

    async def run_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> LLMResponse:
        params = self._request(messages, system_prompt, tools, llm_config)
        async with self.get_client() as client:
            try:
                response = await client.chat.completions(**params, stream=False)
            except ValidationError:
                raise SarvamResponseError(
                    SarvamResponseErrorKind.INVALID_RESPONSE
                ) from None
            return self.transform_response_to_platform(response)

    async def run_streaming_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> AsyncGenerator[LLMResponse, None]:
        params = self._request(messages, system_prompt, tools, llm_config)
        state = SarvamStream()
        async with self.get_client() as client:
            stream = await client.chat.completions(**params, stream=True)
            try:
                async for chunk in stream:
                    partial = state.accept(chunk)
                    if partial is not None:
                        yield partial
                final = state.complete()
            except ValidationError:
                raise SarvamResponseError(
                    SarvamResponseErrorKind.INVALID_RESPONSE
                ) from None
            finally:
                # SDK 0.1.28 returns an async generator behind AsyncIterator.
                # Close it before its owning HTTP client on every exit.
                if isinstance(stream, AsyncGenerator):
                    await stream.aclose()
        yield final
