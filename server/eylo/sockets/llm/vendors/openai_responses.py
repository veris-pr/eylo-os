"""Map canonical LLM inputs to native OpenAI Responses requests and own their I/O."""

import json
from collections.abc import AsyncGenerator, Sequence

from openai import AsyncOpenAI
from openai.types.responses import (
    FunctionToolParam,
    Response,
    ResponseFunctionToolCallParam,
    ResponseInputContentParam,
    ResponseInputParam,
)
from openai.types.responses.response_create_params import (
    ResponseCreateParamsBase,
    ResponseCreateParamsNonStreaming,
    ResponseCreateParamsStreaming,
)
from openai.types.responses.response_input_item_param import FunctionCallOutput

from eylo.common.contracts.llm_runtime import LLMInferenceConfig
from eylo.common.contracts.message_content import (
    AssistantMessageContent,
    ImageUrlContent,
    TextContent,
    TextMessageContentBlock,
    ToolResultMessageContent,
    ToolUseMessageContent,
    UserMessageContent,
    WidgetMessageContent,
    WidgetResponseMessageContent,
)
from eylo.common.contracts.messages import MessageContentType, MessageInDb, MessageKind
from eylo.common.contracts.tool_record import ToolRecord
from eylo.sockets.llm.base import LLMVendorAdapter
from eylo.sockets.llm.config import require_model
from eylo.sockets.llm.schemas import LLMResponse
from eylo.sockets.llm.tool_content import serialize_tool_content
from eylo.sockets.llm.vendors.openai_response_events import (
    OpenAIResponseStream,
    response_to_platform,
    tool_completions,
)
from eylo.sockets.llm.vendors.openai_utils import (
    create_openai_client,
    extract_openai_function_declarations,
)


class OpenAIResponsesAdapter(LLMVendorAdapter):
    """Keep native Responses types at the socket boundary, never in platform callers."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_client(self) -> AsyncOpenAI:
        return create_openai_client(self._api_key)

    def transform_messages_to_vendor(
        self, messages: list[MessageInDb], system_prompt: str
    ) -> tuple[str, ResponseInputParam]:
        messages = self._validate_message_sequence(messages)
        items: ResponseInputParam = []
        for message in messages:
            if message.kind == MessageKind.USER:
                items.append(
                    {
                        "role": "user",
                        "content": self._format_user_content(message.content),
                    }
                )
            elif message.kind == MessageKind.ASSISTANT:
                content = self._format_assistant_content(message.content)
                if content:
                    # EasyInputMessage accepts prior assistant text without inventing
                    # the vendor output ID/status required by ResponseOutputMessage.
                    items.append({"role": "assistant", "content": content})
            elif message.kind == MessageKind.TOOL_USE:
                items.extend(self._format_tool_use_as_function_calls(message.content))
            elif message.kind == MessageKind.TOOL_RESULT:
                items.extend(self._format_tool_result_as_outputs(message.content))
        return system_prompt, items

    def _format_user_content(
        self, content: MessageContentType | None
    ) -> list[ResponseInputContentParam]:
        if isinstance(content, UserMessageContent):
            return [self._format_user_content_block(block) for block in content.content]
        if isinstance(content, WidgetResponseMessageContent):
            return [{"type": "input_text", "text": content.get_text_content()}]
        raise TypeError(f"Unsupported typed user content: {type(content).__name__}")

    def _format_user_content_block(
        self, block: TextMessageContentBlock
    ) -> ResponseInputContentParam:
        if isinstance(block, TextContent):
            return {"type": "input_text", "text": block.text}
        if isinstance(block, ImageUrlContent):
            # The SDK requires detail; auto preserves the API's implicit behavior.
            return {
                "type": "input_image",
                "image_url": block.image_url.url,
                "detail": "auto",
            }
        raise TypeError(f"Unsupported typed user content block: {type(block).__name__}")

    def _format_assistant_content(self, content: MessageContentType | None) -> str:
        if isinstance(content, AssistantMessageContent | WidgetMessageContent):
            return content.get_text_content()
        raise TypeError(
            f"Unsupported typed assistant content: {type(content).__name__}"
        )

    def _format_tool_use_as_function_calls(
        self, content: MessageContentType | None
    ) -> list[ResponseFunctionToolCallParam]:
        if not isinstance(content, ToolUseMessageContent):
            raise TypeError(
                f"Unsupported typed tool-use content: {type(content).__name__}"
            )
        tool = content.content
        return [
            {
                "type": "function_call",
                "call_id": tool.id,
                "name": tool.name,
                "arguments": json.dumps(tool.input),
            }
        ]

    def _format_tool_result_as_outputs(
        self, content: MessageContentType | None
    ) -> list[FunctionCallOutput]:
        if not isinstance(content, ToolResultMessageContent):
            raise TypeError(
                f"Unsupported typed tool-result content: {type(content).__name__}"
            )
        return [
            {
                "type": "function_call_output",
                "call_id": result.tool_use_id,
                "output": serialize_tool_content(result.content),
            }
            for result in content.content
        ]

    def transform_tools_to_vendor(
        self, tools: Sequence[ToolRecord]
    ) -> list[FunctionToolParam]:
        return [
            {
                "type": "function",
                "name": declaration["name"],
                "description": declaration.get("description"),
                "parameters": declaration.get("parameters"),
                "strict": True,
            }
            for declaration in extract_openai_function_declarations(tools)
        ]

    def _apply_request_settings(
        self,
        request: ResponseCreateParamsBase,
        config: LLMInferenceConfig,
        tools: Sequence[ToolRecord],
    ) -> None:
        generation = config.generation
        if generation.max_tokens is not None:
            request["max_output_tokens"] = generation.max_tokens
        if generation.temperature is not None:
            request["temperature"] = generation.temperature
        if generation.top_p is not None:
            request["top_p"] = generation.top_p
        if tools:
            request["tools"] = self.transform_tools_to_vendor(tools)

    async def run_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> LLMResponse:
        instructions, items = self.transform_messages_to_vendor(messages, system_prompt)
        request: ResponseCreateParamsNonStreaming = {
            "model": require_model(llm_config),
            "input": items,
        }
        if instructions:
            request["instructions"] = instructions
        self._apply_request_settings(request, llm_config, tools)
        async with self.get_client() as client:
            response = await client.responses.create(**request)
            return response_to_platform(response)

    async def run_streaming_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> AsyncGenerator[LLMResponse, None]:
        instructions, items = self.transform_messages_to_vendor(messages, system_prompt)
        request: ResponseCreateParamsStreaming = {
            "model": require_model(llm_config),
            "input": items,
            "stream": True,
        }
        if instructions:
            request["instructions"] = instructions
        self._apply_request_settings(request, llm_config, tools)
        state = OpenAIResponseStream()
        async with self.get_client() as client:
            stream = await client.responses.create(**request)
            async with stream:
                async for event in stream:
                    partial = state.accept(event)
                    if partial is not None:
                        yield partial
                final = state.complete()
        for progress in tool_completions(final):
            yield progress
        yield final

    def transform_response_to_platform(self, response: Response) -> LLMResponse:
        return response_to_platform(response)
