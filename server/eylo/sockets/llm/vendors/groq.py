"""Groq-native message, request, and resource ownership at the LLM boundary."""

import json
from collections.abc import AsyncGenerator, Sequence

from groq import AsyncGroq, AsyncStream, omit
from groq.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionContentPartParam,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from groq.types.chat.completion_create_params import CompletionCreateParams

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
from eylo.sockets.llm.vendors.groq_responses import (
    GROQ_VENDOR,
    GroqResponseError,
    GroqResponseErrorKind,
    GroqStream,
    completion_response,
)

_GPT_OSS_MODELS = frozenset({LLMModels.GROQ_GPT_OSS_120B, LLMModels.GROQ_GPT_OSS_20B})


async def _create_completion(
    client: AsyncGroq, params: CompletionCreateParams, *, stream: bool
) -> ChatCompletion | AsyncStream[ChatCompletionChunk]:
    # SDK 1.1.1's request TypedDict permits stream=None; its overloads require
    # a bool for a union response. Pass the operation explicitly, without casts.
    return await client.chat.completions.create(
        model=params["model"],
        messages=params["messages"],
        max_completion_tokens=params.get("max_completion_tokens", omit),
        temperature=params.get("temperature", omit),
        top_p=params.get("top_p", omit),
        stop=params.get("stop", omit),
        tools=params.get("tools", omit),
        tool_choice=params.get("tool_choice", omit),
        include_reasoning=params.get("include_reasoning", omit),
        reasoning_effort=params.get("reasoning_effort", omit),
        stream=stream,
    )


class GroqAdapter(LLMVendorAdapter):
    """Translate canonical contracts using Groq SDK types, never OpenAI clients."""

    vendor_name = GROQ_VENDOR

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_client(self) -> AsyncGroq:
        return AsyncGroq(api_key=self._api_key)

    def transform_messages_to_vendor(
        self, messages: list[MessageInDb], system_prompt: str
    ) -> tuple[str, list[ChatCompletionMessageParam]]:
        vendor_messages: list[ChatCompletionMessageParam] = []
        if system_prompt:
            vendor_messages.append({"role": "system", "content": system_prompt})
        for message in self._validate_message_sequence(messages):
            content = message.content
            if message.kind == MessageKind.USER:
                if isinstance(content, UserMessageContent):
                    parts: list[ChatCompletionContentPartParam] = []
                    for block in content.content:
                        if isinstance(block, TextContent):
                            parts.append({"type": "text", "text": block.text})
                        else:
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": block.image_url.url},
                                }
                            )
                    vendor_messages.append({"role": "user", "content": parts})
                elif isinstance(content, WidgetResponseMessageContent):
                    vendor_messages.append(
                        {"role": "user", "content": content.get_text_content()}
                    )
                else:
                    raise TypeError("Groq requires typed user content")
            elif message.kind == MessageKind.ASSISTANT:
                if not isinstance(
                    content, (AssistantMessageContent, WidgetMessageContent)
                ):
                    raise TypeError("Groq requires typed assistant content")
                vendor_messages.append(
                    {"role": "assistant", "content": content.get_text_content()}
                )
            elif message.kind == MessageKind.TOOL_USE:
                if not isinstance(content, ToolUseMessageContent):
                    raise TypeError("Groq requires typed tool-use content")
                call = content.content
                vendor_messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(call.input),
                                },
                            }
                        ],
                    }
                )
            elif message.kind == MessageKind.TOOL_RESULT:
                if not isinstance(content, ToolResultMessageContent):
                    raise TypeError("Groq requires typed tool-result content")
                for result in content.content:
                    vendor_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": result.tool_use_id,
                            "content": serialize_tool_content(result.content),
                        }
                    )
        return system_prompt, vendor_messages

    def transform_tools_to_vendor(
        self, tools: Sequence[ToolRecord]
    ) -> list[ChatCompletionToolParam]:
        """Preserve optional arguments; Groq does not use OpenAI strict-mode rewriting."""
        vendor_tools: list[ChatCompletionToolParam] = []
        for tool in tools:
            config = tool.llm_config
            schema = config.input_schema.to_json_schema()
            schema.setdefault("properties", {})
            schema["additionalProperties"] = False
            vendor_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": config.name,
                        "description": config.description,
                        "parameters": schema,
                    },
                }
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
        if generation.model in _GPT_OSS_MODELS:
            params["include_reasoning"] = False
        if generation.model == LLMModels.GROQ_QWEN3_32B:
            params["reasoning_effort"] = "none"
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
        async with self.get_client() as client:
            response = await _create_completion(client, params, stream=False)
            if not isinstance(response, ChatCompletion):
                raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE)
            return self.transform_response_to_platform(response)

    async def run_streaming_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> AsyncGenerator[LLMResponse, None]:
        """The consumer owns this generator; closing it closes the stream and client."""
        params = self._request(messages, system_prompt, tools, llm_config)
        state = GroqStream()
        async with self.get_client() as client:
            stream = await _create_completion(client, params, stream=True)
            if not isinstance(stream, AsyncStream):
                raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE)
            async with stream:
                async for chunk in stream:
                    partial = state.accept(chunk)
                    if partial is not None:
                        yield partial
                final = state.complete()
        # No live vendor resource remains while the platform handles the final result.
        yield final
