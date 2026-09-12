"""Translate canonical LLM inputs into native Claude requests and own SDK resources."""

import base64
import logging
from collections.abc import AsyncGenerator, Sequence
from copy import deepcopy
from urllib.parse import urlsplit

from anthropic import AsyncAnthropic, AsyncAnthropicBedrock
from anthropic.types import (
    Base64ImageSourceParam,
    ImageBlockParam,
    Message,
    MessageParam,
    TextBlockParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
    URLImageSourceParam,
)
from anthropic.types.message_create_params import (
    MessageCreateParamsBase,
)
from pydantic import TypeAdapter

from eylo.common.contracts.llm_runtime import LLMInferenceConfig, LLMPromptCaching
from eylo.common.contracts.message_content import (
    AssistantMessageContent,
    ImageUrlContent,
    ImageUrlPayload,
    TextContent,
    UserMessageContent,
    WidgetMessageContent,
    WidgetResponseMessageContent,
)
from eylo.common.contracts.messages import MessageInDb, MessageKind
from eylo.common.contracts.tool_record import ToolRecord
from eylo.sockets.llm.base import LLMVendorAdapter
from eylo.sockets.llm.config import require_max_tokens, require_model
from eylo.sockets.llm.schemas import LLMResponse
from eylo.sockets.llm.tool_content import serialize_tool_content
from eylo.sockets.llm.vendors.anthropic_responses import (
    AnthropicMessageStream,
    message_response,
)

logger = logging.getLogger(__name__)
_BASE64_IMAGE = TypeAdapter(Base64ImageSourceParam)
_DATA_URL_PREFIX = "data:"
_BASE64_DATA_SEPARATOR = ";base64,"
_REMOTE_IMAGE_SCHEMES = frozenset({"http", "https"})


class AnthropicImageSourceError(ValueError):
    """Image input cannot be represented in the selected Claude transport."""


type AnthropicRequestBlock = (
    TextBlockParam | ImageBlockParam | ToolUseBlockParam | ToolResultBlockParam
)


class AnthropicAdapter(LLMVendorAdapter):
    """Own the Claude Messages protocol; Bedrock overrides authenticated transport."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_client(self) -> AsyncAnthropic | AsyncAnthropicBedrock:
        return AsyncAnthropic(api_key=self._api_key)

    def transform_messages_to_vendor(
        self, messages: list[MessageInDb], system_prompt: str
    ) -> tuple[str, list[MessageParam]]:
        vendor_messages: list[MessageParam] = []
        for message in self._validate_message_sequence(messages):
            if message.kind == MessageKind.USER:
                vendor_messages.append(
                    MessageParam(
                        role="user", content=self._format_user_content(message.content)
                    )
                )
            elif message.kind == MessageKind.ASSISTANT:
                vendor_messages.append(
                    MessageParam(
                        role="assistant",
                        content=self._format_assistant_content(message.content),
                    )
                )
            elif message.kind == MessageKind.TOOL_USE:
                try:
                    call = message.get_tool_use_content().content
                    vendor_messages.append(
                        MessageParam(
                            role="assistant",
                            content=[
                                ToolUseBlockParam(
                                    type="tool_use",
                                    id=call.id,
                                    name=call.name,
                                    input=dict(call.input),
                                )
                            ],
                        )
                    )
                except ValueError as error:
                    logger.warning(
                        "Invalid tool-use history message=%s error_type=%s",
                        message.id,
                        type(error).__name__,
                    )
            elif message.kind == MessageKind.TOOL_RESULT:
                try:
                    results = message.get_tool_result_content().content
                    if results:
                        vendor_messages.append(
                            MessageParam(
                                role="user",
                                content=[
                                    ToolResultBlockParam(
                                        type="tool_result",
                                        tool_use_id=result.tool_use_id,
                                        content=serialize_tool_content(result.content),
                                        is_error=result.is_error,
                                    )
                                    for result in results
                                ],
                            )
                        )
                except ValueError as error:
                    logger.warning(
                        "Invalid tool-result history message=%s error_type=%s",
                        message.id,
                        type(error).__name__,
                    )
        return system_prompt, vendor_messages

    def _format_user_content(
        self, content: object
    ) -> str | list[AnthropicRequestBlock]:
        if isinstance(content, UserMessageContent):
            return [self._format_user_content_block(block) for block in content.content]
        if isinstance(content, WidgetResponseMessageContent):
            return content.get_text_content()
        raise TypeError(f"Unsupported typed user content: {type(content).__name__}")

    def _format_user_content_block(
        self, block: TextContent | ImageUrlContent
    ) -> TextBlockParam | ImageBlockParam:
        if isinstance(block, TextContent):
            return TextBlockParam(type="text", text=block.text)
        return ImageBlockParam(type="image", source=self._image_source(block.image_url))

    def _image_source(
        self, image: ImageUrlPayload
    ) -> Base64ImageSourceParam | URLImageSourceParam:
        """Translate inline data, or pass a URL to Claude; never fetch local/remote files."""
        if not image.url.startswith(_DATA_URL_PREFIX):
            try:
                parsed = urlsplit(image.url)
                if parsed.scheme not in _REMOTE_IMAGE_SCHEMES or not parsed.hostname:
                    raise ValueError
            except ValueError:
                raise AnthropicImageSourceError(
                    "Claude image URL must use HTTP(S)"
                ) from None
            return URLImageSourceParam(type="url", url=image.url)
        media_type, separator, data = image.url.removeprefix(
            _DATA_URL_PREFIX
        ).partition(_BASE64_DATA_SEPARATOR)
        try:
            if not separator or not data:
                raise ValueError
            if image.mime_type is not None and image.mime_type != media_type:
                raise ValueError
            source = _BASE64_IMAGE.validate_python(
                {"type": "base64", "media_type": media_type, "data": data}, strict=True
            )
            base64.b64decode(data, validate=True)
            return source
        except ValueError:
            raise AnthropicImageSourceError(
                "Claude image requires valid base64 and a supported MIME type"
            ) from None

    def _format_assistant_content(self, content: object) -> list[AnthropicRequestBlock]:
        if isinstance(content, AssistantMessageContent):
            return [self._format_user_content_block(block) for block in content.content]
        if isinstance(content, WidgetMessageContent):
            return [TextBlockParam(type="text", text=content.get_text_content())]
        raise TypeError(
            f"Unsupported typed assistant content: {type(content).__name__}"
        )

    def transform_tools_to_vendor(self, tools: Sequence[ToolRecord]) -> list[ToolParam]:
        declarations: list[ToolParam] = []
        for tool in tools:
            schema: dict[str, object] = {
                key: value
                for key, value in tool.llm_config.input_schema.to_json_schema().items()
            }
            declarations.append(
                ToolParam(
                    name=tool.llm_config.name,
                    description=tool.llm_config.description,
                    input_schema=schema,
                )
            )
        return declarations

    def _apply_prompt_caching(
        self,
        system_prompt: str,
        vendor_messages: list[MessageParam],
        vendor_tools: list[ToolParam],
    ) -> tuple[list[TextBlockParam], list[ToolParam], list[MessageParam]]:
        """Annotate at most four existing breakpoints without mutating input history."""
        system_blocks = (
            [
                TextBlockParam(
                    type="text", text=system_prompt, cache_control={"type": "ephemeral"}
                )
            ]
            if system_prompt
            else []
        )
        cached_tools = deepcopy(vendor_tools)
        if cached_tools:
            cached_tools[-1]["cache_control"] = {"type": "ephemeral"}

        cached_messages = deepcopy(vendor_messages)
        # Preserve the existing last-two-user boundary, including tool results.
        user_indices = [
            index
            for index, message in enumerate(cached_messages)
            if message["role"] == "user"
        ]
        for index in user_indices[-2:]:
            message = cached_messages[index]
            content = message["content"]
            if isinstance(content, str):
                if content:
                    message["content"] = [
                        TextBlockParam(
                            type="text",
                            text=content,
                            cache_control={"type": "ephemeral"},
                        )
                    ]
                continue
            blocks = list(content)
            message["content"] = blocks
            if not blocks:
                continue
            block = blocks[-1]
            # Generated requests use these native params, not SDK response models.
            if isinstance(block, dict):
                if block["type"] == "text":
                    if block["text"]:
                        block["cache_control"] = {"type": "ephemeral"}
                elif block["type"] in ("image", "tool_use", "tool_result"):
                    block["cache_control"] = {"type": "ephemeral"}
        return system_blocks, cached_tools, cached_messages

    def _request(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> MessageCreateParamsBase:
        """Validate required config before opening a client; omit unset settings."""
        model = require_model(llm_config)
        max_tokens = require_max_tokens(llm_config)
        prompt, vendor_messages = self.transform_messages_to_vendor(
            messages, system_prompt
        )
        vendor_tools = self.transform_tools_to_vendor(tools)
        params: MessageCreateParamsBase = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": vendor_messages,
            "system": prompt,
        }
        if llm_config.prompt_caching is LLMPromptCaching.ENABLED:
            system_blocks, vendor_tools, vendor_messages = self._apply_prompt_caching(
                prompt, vendor_messages, vendor_tools
            )
            params["system"] = system_blocks
            params["messages"] = vendor_messages
        if vendor_tools:
            params["tools"] = vendor_tools
        generation = llm_config.generation
        if generation.temperature is not None:
            params["temperature"] = generation.temperature
        if generation.top_p is not None:
            params["top_p"] = generation.top_p
        if generation.top_k is not None:
            params["top_k"] = generation.top_k
        if generation.stop_sequences is not None:
            params["stop_sequences"] = generation.stop_sequences
        return params

    async def run_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> LLMResponse:
        params = self._request(messages, system_prompt, tools, llm_config)
        async with self.get_client() as client:
            response = await client.messages.create(**params, stream=False)
            return self.transform_response_to_platform(response)

    async def run_streaming_inference(
        self,
        messages: list[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> AsyncGenerator[LLMResponse, None]:
        """Stream text early; release executable tools only after validation and cleanup."""
        params = self._request(messages, system_prompt, tools, llm_config)
        accumulator = AnthropicMessageStream()
        async with self.get_client() as client:
            async with await client.messages.create(**params, stream=True) as stream:
                async for event in stream:
                    progress = accumulator.accept(event)
                    if progress is not None:
                        yield progress
        final = accumulator.finish()
        for progress in accumulator.tool_completions(final):
            yield progress
        yield final

    def transform_response_to_platform(self, vendor_response: Message) -> LLMResponse:
        return message_response(vendor_response)
