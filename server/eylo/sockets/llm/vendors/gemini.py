"""Google Gemini LLM vendor adapter implementation.

This module provides integration with Google's Gemini language models,
implementing the LLMVendorAdapter interface to handle all Gemini-specific
message transformations, tool formatting, and response parsing.

Architecture Notes:
- Gemini's API differs from Anthropic/OpenAI in several key ways:
  * System messages can be provided via system_instruction parameter
  * Tool calls use function_call format in response parts
  * Responses use candidates[0].content.parts structure
  * Automatic function calling is enabled by default (can be disabled)
  * Supports compositional (sequential) and parallel function calling

References:
- Gemini API: https://ai.google.dev/gemini-api/docs
- Function Calling: https://ai.google.dev/gemini-api/docs/function-calling

"""

import json
import logging
import mimetypes
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import aclosing, asynccontextmanager
from typing import Final, List, Optional
from urllib.parse import urlparse
from uuid import UUID

from google import genai
from google.genai import types
from google.genai.client import AsyncClient

from eylo.common.contracts.llm_runtime import LLMInferenceConfig
from eylo.common.contracts.messages import (
    MessageContentType,
    MessageInDb,
    MessageKind,
)
from eylo.common.contracts.tool_record import ToolRecord
from eylo.sockets.llm.base import LLMVendorAdapter
from eylo.sockets.llm.config import require_model
from eylo.sockets.llm.schemas import LLMResponse
from eylo.sockets.llm.vendors.gemini_responses import (
    GeminiStream,
    completion_response,
    message_replay,
)

logger = logging.getLogger(__name__)

GEMINI_IMAGE_MIME_PREFIX: Final = "image/"
GEMINI_DEFAULT_IMAGE_MIME_TYPE: Final = "image/jpeg"
GEMINI_FILE_URI_PREFIX: Final = "files/"
GEMINI_FILE_URI_HOST: Final = "generativelanguage.googleapis.com"
GEMINI_FILE_URI_PATH_FRAGMENT: Final = "/files/"

# Default safety settings for Gemini API
# BLOCK_ONLY_HIGH allows most content while still blocking extreme cases
DEFAULT_SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
]


class GeminiAdapter(LLMVendorAdapter):
    """Google Gemini LLM vendor adapter.

    Encapsulates all Gemini-specific logic for message transformation,
    tool formatting, and response parsing.

    Key Differences from Anthropic/OpenAI:
    - System instructions are separate from messages
    - Tool calls use function_call format in response parts
    - Responses use candidates[0].content.parts structure
    - Automatic function calling is enabled by default (can be disabled)
    - Supports compositional (sequential) and parallel function calling
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_client(self) -> genai.Client:
        """Get authenticated Gemini client."""
        return genai.Client(api_key=self._api_key)

    @asynccontextmanager
    async def _owned_client(self) -> AsyncIterator[AsyncClient]:
        """The native SDK allocates separate sync and async transports."""
        client = self.get_client()
        try:
            yield client.aio
        finally:
            try:
                await client.aio.aclose()
            finally:
                client.close()

    def _handle_user_transition(
        self,
        stack: list[MessageInDb],
        msg: MessageInDb,
        current_kind: MessageKind,
        pending_tool_calls: dict[str, UUID],
    ) -> None:
        """Keep native user parts intact; same-role text merging loses images."""
        if current_kind == MessageKind.USER:
            stack.append(msg)
        else:
            super()._handle_user_transition(
                stack, msg, current_kind, pending_tool_calls
            )

    def _handle_assistant_transition(
        self,
        stack: list[MessageInDb],
        msg: MessageInDb,
        current_kind: MessageKind,
        pending_tool_calls: dict[str, UUID],
    ) -> None:
        """Signed parts cannot be merged or attached to regenerated assistant text."""
        if current_kind == MessageKind.ASSISTANT:
            if pending_tool_calls and not self._same_pending_response(
                stack, msg, pending_tool_calls
            ):
                self._cleanup_incomplete_tool_sequence(stack, pending_tool_calls)
            stack.append(msg)
        elif current_kind == MessageKind.TOOL_RESULT and pending_tool_calls:
            self._accept_tool_results(stack, msg, pending_tool_calls)
        else:
            super()._handle_assistant_transition(
                stack, msg, current_kind, pending_tool_calls
            )

    @staticmethod
    def _same_pending_response(
        stack: list[MessageInDb],
        msg: MessageInDb,
        pending_tool_calls: dict[str, UUID],
    ) -> bool:
        """Text between native function parts does not end their model turn."""
        replay = message_replay(msg)
        if replay is None:
            return False
        pending_ids = set(pending_tool_calls.values())
        pending = [row for row in stack if row.id in pending_ids]
        return len(pending) == len(pending_ids) and all(
            (call_replay := message_replay(row)) is not None
            and call_replay.response_id == replay.response_id
            for row in pending
        )

    def _handle_tool_use_transition(
        self,
        stack: list[MessageInDb],
        msg: MessageInDb,
        current_kind: MessageKind,
        pending_tool_calls: dict[str, UUID],
    ) -> None:
        if current_kind == MessageKind.ASSISTANT and self._same_pending_response(
            stack, msg, pending_tool_calls
        ):
            stack.append(msg)
        else:
            super()._handle_tool_use_transition(
                stack, msg, current_kind, pending_tool_calls
            )

    def _handle_tool_result_transition(
        self,
        stack: list[MessageInDb],
        msg: MessageInDb,
        current_kind: MessageKind,
        pending_tool_calls: dict[str, UUID],
    ) -> None:
        if (
            current_kind == MessageKind.ASSISTANT
            and pending_tool_calls
            and self._same_pending_response(stack, msg, pending_tool_calls)
        ):
            stack.append(msg)
        else:
            super()._handle_tool_result_transition(
                stack, msg, current_kind, pending_tool_calls
            )

    def transform_messages_to_vendor(
        self,
        messages: List[MessageInDb],
        system_prompt: str,
        model: Optional[str] = None,
    ) -> tuple[str, list[types.Content]]:
        """Group retained calls before their results within the original model turn."""
        messages = self._validate_message_sequence(messages)
        vendor_messages: list[types.Content] = []
        tool_names: dict[str, str] = {}
        native_ids: dict[str, str | None] = {}
        response_id: str | None = None
        model_parts: list[types.Part] = []
        result_parts: list[types.Part] = []

        def flush() -> None:
            if model_parts:
                vendor_messages.append(types.ModelContent(parts=list(model_parts)))
                model_parts.clear()
            if result_parts:
                vendor_messages.append(types.UserContent(parts=list(result_parts)))
                result_parts.clear()

        for msg in messages:
            if msg.kind == MessageKind.USER:
                flush()
                response_id = None
                vendor_messages.append(
                    types.UserContent(parts=self._format_user_parts(msg.content))
                )
            elif msg.kind in (MessageKind.ASSISTANT, MessageKind.TOOL_USE):
                replay = message_replay(msg)
                key = replay.response_id if replay else str(msg.id)
                if key != response_id:
                    flush()
                    response_id = key
                if msg.kind == MessageKind.ASSISTANT:
                    model_parts.extend(
                        replay.parts if replay else self._format_assistant_parts(msg)
                    )
                else:
                    tool_use = msg.get_tool_use_content().content
                    parts = (
                        list(replay.parts)
                        if replay
                        else [
                            types.Part(
                                function_call=types.FunctionCall(
                                    id=tool_use.id,
                                    name=tool_use.name,
                                    args=tool_use.input,
                                )
                            )
                        ]
                    )
                    native_calls = [
                        part.function_call
                        for part in parts
                        if part.function_call is not None
                    ]
                    if len(native_calls) != 1:
                        raise ValueError(
                            "Gemini replay must contain one retained tool call"
                        )
                    tool_names[tool_use.id] = tool_use.name
                    native_ids[tool_use.id] = native_calls[0].id
                    model_parts.extend(parts)
            elif msg.kind == MessageKind.TOOL_RESULT:
                for result in msg.get_tool_result_content().content:
                    result_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=native_ids[result.tool_use_id],
                                name=tool_names[result.tool_use_id],
                                response=self._serialize_tool_content(result.content),
                            )
                        )
                    )
        flush()
        return system_prompt, vendor_messages

    def _format_user_parts(
        self, content: MessageContentType | None
    ) -> list[types.Part]:
        """Format one typed user message as Gemini parts."""
        from eylo.common.contracts.message_content import (
            ImageUrlContent,
            TextContent,
            UserMessageContent,
            WidgetResponseMessageContent,
        )

        if isinstance(content, UserMessageContent):
            parts = []
            for block in content.content:
                if isinstance(block, TextContent):
                    parts.append(types.Part(text=block.text))
                elif isinstance(block, ImageUrlContent):
                    parts.append(
                        self._format_image_url_part(
                            block.image_url.url,
                            block.image_url.mime_type,
                        )
                    )
            return parts
        if isinstance(content, WidgetResponseMessageContent):
            return [types.Part(text=content.get_text_content())]
        raise TypeError(f"Unsupported typed user content: {type(content).__name__}")

    def _format_image_url_part(
        self,
        image_url: str,
        mime_type: Optional[str] = None,
    ) -> types.Part:
        """Format a remote image URL as a Gemini file data part."""
        self._validate_gemini_file_uri(image_url)
        concrete_mime_type = mime_type or self._guess_image_mime_type(image_url)
        return types.Part(
            file_data=types.FileData(file_uri=image_url, mime_type=concrete_mime_type)
        )

    @staticmethod
    def _validate_gemini_file_uri(image_url: str) -> None:
        """Ensure image URL is a Gemini Files API URI before emitting file_data."""
        parsed = urlparse(image_url)
        is_relative_file_uri = image_url.startswith(GEMINI_FILE_URI_PREFIX)
        is_google_file_uri = (
            parsed.scheme in {"http", "https"}
            and parsed.netloc == GEMINI_FILE_URI_HOST
            and GEMINI_FILE_URI_PATH_FRAGMENT in parsed.path
        )
        if is_relative_file_uri or is_google_file_uri:
            return
        raise ValueError(
            "Gemini image_url content requires a Gemini Files API URI; "
            "arbitrary HTTP image URLs are not supported by file_data"
        )

    @staticmethod
    def _guess_image_mime_type(image_url: str) -> str:
        """Infer the concrete Gemini MIME type from an image URL path."""
        mime_type, _ = mimetypes.guess_type(urlparse(image_url).path)
        if mime_type and mime_type.startswith(GEMINI_IMAGE_MIME_PREFIX):
            return mime_type
        return GEMINI_DEFAULT_IMAGE_MIME_TYPE

    def _format_assistant_parts(self, message: MessageInDb) -> list[types.Part]:
        """Keep typed text, file parts, and existing replay metadata together."""
        from eylo.common.contracts.message_content import (
            AssistantMessageContent,
            ImageUrlContent,
            TextContent,
            WidgetMessageContent,
        )

        parts = []

        content = message.content

        if isinstance(content, AssistantMessageContent):
            for block in content.content:
                if isinstance(block, TextContent):
                    part_item = types.Part(text=block.text)
                elif isinstance(block, ImageUrlContent):
                    part_item = self._format_image_url_part(
                        block.image_url.url,
                        block.image_url.mime_type,
                    )
                else:
                    raise TypeError(
                        "Unsupported typed assistant content block: "
                        f"{type(block).__name__}"
                    )

                parts.append(part_item)
            return parts
        if isinstance(content, WidgetMessageContent):
            return [types.Part(text=content.get_text_content())]
        raise TypeError(
            f"Unsupported typed assistant content: {type(content).__name__}"
        )

    def transform_tools_to_vendor(
        self, tools: Sequence[ToolRecord]
    ) -> list[types.Tool]:
        """Preserve declared JSON Schema constraints in native SDK tool objects."""
        declarations = [
            types.FunctionDeclaration(
                name=tool.llm_config.name,
                description=tool.llm_config.description,
                parameters_json_schema=tool.llm_config.input_schema.to_json_schema(),
            )
            for tool in tools
            if tool.llm_config is not None
        ]
        return [types.Tool(function_declarations=declarations)] if declarations else []

    def _serialize_tool_content(self, content: object) -> dict[str, object]:
        """Keep Gemini responses object-shaped, including JSON-encoded scalars."""
        if isinstance(content, str):
            try:
                parsed: object = json.loads(content)
            except json.JSONDecodeError:
                return {"result": content}
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed}
        if isinstance(content, dict):
            return content
        if isinstance(content, list):
            return {"result": content}
        return {"result": str(content)}

    async def run_inference(
        self,
        messages: List[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
        stream: bool = False,
    ) -> LLMResponse:
        """Validate before allocation; release both SDK transports before returning."""
        model, gemini_contents, config, _ = self._prepare_inference_config(
            messages, system_prompt, tools, llm_config
        )
        try:
            async with self._owned_client() as client:
                response = await client.models.generate_content(
                    model=model,
                    contents=list(gemini_contents),
                    config=config,
                )
            return completion_response(response, model)

        except Exception as error:
            logger.error(
                "Gemini API request failed error_type=%s",
                type(error).__name__,
            )
            raise

    async def run_streaming_inference(
        self,
        messages: List[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
    ) -> AsyncGenerator[LLMResponse, None]:
        """Close the native stream and clients before exposing executable tools."""
        model, contents, config, _ = self._prepare_inference_config(
            messages, system_prompt, tools, llm_config
        )
        state = GeminiStream(requested_model=model)
        async with self._owned_client() as client:
            chunks = await client.models.generate_content_stream(
                model=model,
                contents=list(contents),
                config=config,
            )
            if not isinstance(chunks, AsyncGenerator):
                raise TypeError("Gemini SDK stream must be an async generator")
            async with aclosing(chunks):
                async for chunk in chunks:
                    progress = state.accept(chunk)
                    if progress is not None:
                        yield progress
        yield state.complete(streaming=True)

    def transform_response_to_platform(
        self,
        vendor_response: types.GenerateContentResponse,
    ) -> LLMResponse:
        return completion_response(vendor_response)

    def _prepare_inference_config(
        self,
        messages: List[MessageInDb],
        system_prompt: str,
        tools: Sequence[ToolRecord],
        llm_config: LLMInferenceConfig,
        model: Optional[str] = None,
    ) -> tuple[str, list[types.Content], types.GenerateContentConfig, list[types.Tool]]:
        """Build native request objects without adding model-dependent defaults."""
        # Extract model if not provided
        if not model:
            model = require_model(llm_config)

        # Native replay follows saved part identity, never a model-name heuristic.
        system_instruction, vendor_messages = self.transform_messages_to_vendor(
            messages, system_prompt, model
        )
        vendor_tools = self.transform_tools_to_vendor(tools)

        generation = llm_config.generation
        config = types.GenerateContentConfig(
            max_output_tokens=generation.max_tokens,
            temperature=generation.temperature,
            top_p=generation.top_p,
            top_k=generation.top_k,
            stop_sequences=(
                list(generation.stop_sequences)
                if generation.stop_sequences is not None
                else None
            ),
            system_instruction=system_instruction if system_instruction else None,
            safety_settings=DEFAULT_SAFETY_SETTINGS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        # Add tools if available
        if vendor_tools:
            config.tools = list(vendor_tools)

        return model, vendor_messages, config, vendor_tools
