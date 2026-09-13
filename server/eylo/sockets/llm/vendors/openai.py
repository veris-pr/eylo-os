"""OpenAI adapter for the `llm` socket."""

import json
import logging
from collections.abc import Sequence
from typing import AsyncGenerator, List, Tuple

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionContentPartParam,
    ChatCompletionMessageFunctionToolCallParam,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from openai.types.chat.completion_create_params import (
    CompletionCreateParamsBase,
    CompletionCreateParamsNonStreaming,
    CompletionCreateParamsStreaming,
)

from eylo.common.contracts.llm_runtime import LLMInferenceConfig
from eylo.common.contracts.messages import (
    MessageInDb,
    MessageKind,
)
from eylo.common.contracts.tool_record import ToolRecord
from eylo.sockets.llm.base import LLMVendorAdapter
from eylo.sockets.llm.config import require_model
from eylo.sockets.llm.schemas import LLMResponse
from eylo.sockets.llm.tool_content import serialize_tool_content
from eylo.sockets.llm.vendors.openai_chat_responses import (
    OpenAIChatStream,
    completion_response,
)
from eylo.sockets.llm.vendors.openai_utils import (
    create_openai_client,
    extract_openai_function_declarations,
)

logger = logging.getLogger(__name__)


class OpenAIAdapter(LLMVendorAdapter):
    """OpenAI/GPT LLM vendor adapter.

    Encapsulates all OpenAI-specific logic for message transformation,
    tool formatting, and response parsing.

    Key Differences from Anthropic:
    - System prompt is a message with role="system" (not separate parameter)
    - Tool calls are in message.tool_calls array
    - Tool results are messages with role="tool"
    - Response structure uses choices[0].message
    """

    vendor_name = "openai"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_client(self) -> AsyncOpenAI:
        """Get authenticated OpenAI client."""
        return create_openai_client(self._api_key)

    def transform_messages_to_vendor(
        self, messages: List[MessageInDb], system_prompt: str
    ) -> Tuple[str, List[ChatCompletionMessageParam]]:
        """Transform Eylo messages to OpenAI format.

        OpenAI expects:
        - Messages with role: "system" | "user" | "assistant" | "tool"
        - System message should be first in the array
        - Content can be string or list of content blocks
        - Tool calls are in message.tool_calls array
        - Tool results are separate messages with role="tool"

        Returns:
            Tuple of (system_prompt, vendor_messages)
            Note: system_prompt is returned for consistency with base class,
                  but OpenAI includes it in the messages array.

        """
        # Validate message sequence
        messages = self._validate_message_sequence(messages)

        # Use typed list internally for better type checking
        vendor_messages: List[ChatCompletionMessageParam] = []

        # Add system message first if we have a system prompt
        if system_prompt:
            vendor_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.kind == MessageKind.USER:
                # User messages
                content = self._format_user_content(msg.content)
                vendor_messages.append({"role": "user", "content": content})

            elif msg.kind == MessageKind.ASSISTANT:
                # Assistant messages (text responses)
                assistant_content = self._format_assistant_content(msg.content)
                vendor_messages.append(
                    {"role": "assistant", "content": assistant_content}
                )

            elif msg.kind == MessageKind.TOOL_USE:
                # Tool use messages - OpenAI puts these as assistant messages with tool_calls
                tool_calls = self._format_tool_use_content(msg.content)
                vendor_messages.append(
                    {"role": "assistant", "content": None, "tool_calls": tool_calls}
                )

            elif msg.kind == MessageKind.TOOL_RESULT:
                # Tool result messages - OpenAI uses role="tool"
                tool_result_messages = self._format_tool_result_content(msg.content)
                vendor_messages.extend(tool_result_messages)

        return (system_prompt, vendor_messages)

    def _format_user_content(
        self, content: object
    ) -> str | list[ChatCompletionContentPartParam]:
        """Format one typed user message for OpenAI."""
        from eylo.common.contracts.message_content import (
            TextContent,
            UserMessageContent,
            WidgetResponseMessageContent,
        )

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
            return parts
        if isinstance(content, WidgetResponseMessageContent):
            return content.get_text_content()
        raise TypeError(f"Unsupported typed user content: {type(content).__name__}")

    def _format_assistant_content(self, content: object) -> str:
        """Format assistant message content for OpenAI.

        Handles:
        - AssistantMessageContent: {"role": "assistant", "content": TextContent | dict}
        - ToolUseMessageContent: {"role": "tool_use", "content": ToolUseContent}
        """
        from eylo.common.contracts.message_content import (
            AssistantMessageContent,
            WidgetMessageContent,
        )

        if isinstance(content, AssistantMessageContent):
            return content.get_text_content()
        if isinstance(content, WidgetMessageContent):
            return content.get_text_content()
        raise TypeError(
            f"Unsupported typed assistant content: {type(content).__name__}"
        )

    def _format_tool_use_content(
        self, content: object
    ) -> list[ChatCompletionMessageFunctionToolCallParam]:
        """Format tool use content for OpenAI.

        OpenAI tool calls format:
        [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "Paris"}'
                }
            }
        ]

        """
        from eylo.common.contracts.message_content import ToolUseMessageContent

        if not isinstance(content, ToolUseMessageContent):
            raise TypeError(
                f"Unsupported typed tool-use content: {type(content).__name__}"
            )
        tool_use = content.content
        return [
            {
                "id": tool_use.id,
                "type": "function",
                "function": {
                    "name": tool_use.name,
                    "arguments": json.dumps(tool_use.input),
                },
            }
        ]

    def _format_tool_result_content(
        self, content: object
    ) -> List[ChatCompletionMessageParam]:
        """Format tool result content for OpenAI.

        OpenAI tool result format:
        {
            "role": "tool",
            "tool_call_id": "call_abc123",
            "content": "The weather in Paris is 72°F"
        }
        """
        from eylo.common.contracts.message_content import ToolResultMessageContent

        if not isinstance(content, ToolResultMessageContent):
            raise TypeError(
                f"Unsupported typed tool-result content: {type(content).__name__}"
            )
        return [
            {
                "role": "tool",
                "tool_call_id": result.tool_use_id,
                "content": serialize_tool_content(result.content),
            }
            for result in content.content
        ]

    def transform_tools_to_vendor(
        self, tools: Sequence[ToolRecord]
    ) -> List[ChatCompletionToolParam]:
        """Transform platform-native tools to OpenAI Chat Completions format.

        Delegates extraction to ``extract_openai_function_declarations``
        and wraps each declaration in the nested
        ``{"type": "function", "function": {..., "strict": True}}``
        structure required by the Chat Completions API.
        """
        declarations = extract_openai_function_declarations(tools)
        vendor_tools: List[ChatCompletionToolParam] = [
            {
                "type": "function",
                "function": {
                    **d,
                    "strict": True,
                },
            }
            for d in declarations
        ]
        return vendor_tools

    def _apply_request_settings(
        self,
        params: CompletionCreateParamsBase,
        tools: list[ChatCompletionToolParam] | None,
        config: LLMInferenceConfig,
    ) -> None:
        """Project configured values into the installed SDK's wire contract."""
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
            params["tools"] = tools
            params["tool_choice"] = "auto"

    async def run_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> LLMResponse:
        """Validate input before allocating a client; invocation owns its resources."""
        _, vendor_messages = self.transform_messages_to_vendor(messages, system_prompt)
        vendor_tools = self.transform_tools_to_vendor(tools) if tools else None
        params: CompletionCreateParamsNonStreaming = {
            "model": require_model(llm_config),
            "messages": vendor_messages,
            "stream": False,
        }
        self._apply_request_settings(params, vendor_tools, llm_config)
        async with self.get_client() as client:
            response = await client.chat.completions.create(**params)
            return self.transform_response_to_platform(response)

    async def run_streaming_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> AsyncGenerator[LLMResponse, None]:
        """Stream text early; expose tool completions only after validation and close."""
        _, vendor_messages = self.transform_messages_to_vendor(messages, system_prompt)
        vendor_tools = self.transform_tools_to_vendor(tools) if tools else None
        params: CompletionCreateParamsStreaming = {
            "model": require_model(llm_config),
            "messages": vendor_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._apply_request_settings(params, vendor_tools, llm_config)
        state = OpenAIChatStream()
        async with self.get_client() as client:
            stream = await client.chat.completions.create(**params)
            async with stream:
                async for chunk in stream:
                    partial = state.accept(chunk)
                    if partial is not None:
                        yield partial
                final = state.complete()
        for completion in state.tool_completions(final):
            yield completion
        yield final

    def transform_response_to_platform(
        self, vendor_response: ChatCompletion
    ) -> LLMResponse:
        return completion_response(vendor_response)
