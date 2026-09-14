"""Bounded MCP 2025-06-18 client over the shared HTTPS egress contract.

This adapter implements only the protocol surface Eylo uses: Streamable HTTP,
initialization, paginated tool discovery, and text-only tool calls. It performs
one wire attempt per request. Durable retry and ambiguous-delivery decisions
belong to the pipeline because only that layer knows the tool's declared effect.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from eylo.common.http_egress import (
    HttpDestinationPolicy,
    HttpEgressErrorCode,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpEgressResponse,
    HttpMethod,
    HttpRoutePolicy,
    OriginBoundHeaders,
    parse_https_target,
)

from .schemas import (
    CLIENT_VERSION,
    MAX_CURSOR_LENGTH,
    PROTOCOL_VERSION,
    MCPCallToolParams,
    MCPCallToolRequest,
    MCPCallToolResult,
    MCPImplementation,
    MCPInitializeParams,
    MCPInitializeRequest,
    MCPInitializeResult,
    MCPInitializedNotification,
    MCPListToolsParams,
    MCPListToolsRequest,
    MCPMethod,
    MCPRequest,
    MCPRpcResponse,
    MCPToolsPage,
    MCPWireTool,
)

DEFAULT_TIMEOUT_SECONDS = 30.0

MAX_DISCOVERY_RESPONSE_BYTES = 524_288
MAX_TOOL_RESULT_BYTES = 65_536
MAX_INITIALIZE_RESPONSE_BYTES = 131_072
MAX_TOOL_PAGES = 20
MAX_TOOLS = 200
MAX_SESSION_ID_LENGTH = 1_024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20_000
MAX_JSON_STRING_BYTES = 524_288
_JSON = TypeAdapter(JsonValue)

_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_PRE_WIRE_RETRYABLE_ERRORS = frozenset(
    {
        HttpEgressErrorCode.DNS_RESOLUTION_EMPTY,
        HttpEgressErrorCode.DNS_RESOLUTION_FAILED,
    }
)
_POST_WIRE_POLICY_ERRORS = frozenset(
    {
        HttpEgressErrorCode.RESPONSE_BODY_TOO_LARGE,
        HttpEgressErrorCode.RESPONSE_HEADERS_TOO_LARGE,
    }
)


class MCPHttpTransport(Protocol):
    """Execute one request through the platform's bounded HTTP boundary."""

    async def send(self, request: HttpEgressRequest) -> HttpEgressResponse: ...


class MCPDeliveryState(StrEnum):
    """What the client can prove about one failed request's delivery."""

    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"
    SENT = "sent"


class MCPErrorCode(StrEnum):
    """Safe adapter-owned failures; persisted spellings remain stable."""

    CONTENT_TYPE_INVALID = "content_type_invalid"
    CONTENT_TYPE_UNSUPPORTED = "content_type_unsupported"
    EGRESS_OUTCOME_UNCONFIRMED = "egress_outcome_unconfirmed"
    EGRESS_POLICY_REJECTED = "egress_policy_rejected"
    EGRESS_UNAVAILABLE = "egress_unavailable"
    HTTP_STATUS_ERROR = "http_status_error"
    MCP_RPC_ERROR = "mcp_rpc_error"
    NOTIFICATION_REJECTED = "notification_rejected"
    PAGINATION_CURSOR_INVALID = "pagination_cursor_invalid"
    PAGINATION_CURSOR_REPEATED = "pagination_cursor_repeated"
    PAGINATION_LIMIT_EXCEEDED = "pagination_limit_exceeded"
    PROTOCOL_VERSION_UNSUPPORTED = "protocol_version_unsupported"
    REQUEST_JSON_INVALID = "request_json_invalid"
    RESPONSE_ENVELOPE_INVALID = "response_envelope_invalid"
    RESPONSE_JSON_INVALID = "response_json_invalid"
    RESPONSE_MATCH_INVALID = "response_match_invalid"
    RESPONSE_NUMBER_INVALID = "response_number_invalid"
    RESPONSE_RESULT_INVALID = "response_result_invalid"
    RESPONSE_SSE_EMPTY = "response_sse_empty"
    RESPONSE_SSE_INVALID = "response_sse_invalid"
    RESPONSE_STRING_EXCEEDED = "response_string_exceeded"
    RESPONSE_STRUCTURE_EXCEEDED = "response_structure_exceeded"
    SERVER_INFO_INVALID = "server_info_invalid"
    SERVER_REQUEST_UNSUPPORTED = "server_request_unsupported"
    SESSION_ID_INVALID = "session_id_invalid"
    STRUCTURED_RESULT_UNSUPPORTED = "structured_result_unsupported"
    TOOL_ARGUMENTS_INVALID = "tool_arguments_invalid"
    TOOL_CONTENT_INVALID = "tool_content_invalid"
    TOOL_CONTENT_UNSUPPORTED = "tool_content_unsupported"
    TOOL_COUNT_EXCEEDED = "tool_count_exceeded"
    TOOL_DEFINITION_INVALID = "tool_definition_invalid"
    TOOL_ERROR_FLAG_INVALID = "tool_error_flag_invalid"
    TOOL_NAME_DUPLICATE = "tool_name_duplicate"
    TOOL_NAME_INVALID = "tool_name_invalid"
    TOOL_RESULT_EXCEEDED = "tool_result_exceeded"
    TOOLS_CAPABILITY_MISSING = "tools_capability_missing"
    TOOLS_LIST_INVALID = "tools_list_invalid"


class MCPError(Exception):
    """Safe typed MCP failure with no provider-controlled text."""

    def __init__(
        self,
        code: MCPErrorCode,
        message: str,
        *,
        delivery: MCPDeliveryState,
        retryable: bool = False,
        status_code: int | None = None,
        rpc_code: int | None = None,
        method: MCPMethod | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.delivery = delivery
        self.retryable = retryable
        self.status_code = status_code
        self.rpc_code = rpc_code
        self.method = method


class MCPTool(BaseModel):
    """One server-declared tool contract."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    name: str
    description: str
    input_schema: dict[str, JsonValue] = Field(default_factory=dict)
    output_schema: dict[str, JsonValue] | None = None
    annotations: dict[str, JsonValue] = Field(default_factory=dict)


class MCPToolResult(BaseModel):
    """Text-only result; explicit consumers, not snapshots, receive remote text."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    text: str = Field(repr=False, exclude=True)
    is_error: bool = False


class MCPClient:
    """One org-scoped MCP session over one exact HTTPS endpoint."""

    def __init__(
        self,
        *,
        url: str,
        origin_headers: OriginBoundHeaders,
        transport: MCPHttpTransport,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client_name: str = "eylo",
    ) -> None:
        origin, path = parse_https_target(url)
        if origin_headers.origin != origin:
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.CREDENTIAL_ORIGIN_MISMATCH,
                "MCP credentials do not match the configured server origin.",
            )
        self._url = url
        self._origin = origin
        self._configured_headers = origin_headers
        self._transport = transport
        self._policy = HttpDestinationPolicy(
            primary=HttpRoutePolicy(origin=origin, path_prefix=path),
            max_redirects=0,
        )
        self._timeout = timeout_seconds
        self._client_name = client_name
        self._session_id: str | None = None
        self._initialized = False
        self._next_id = 0

    async def list_tools(self) -> list[MCPTool]:
        """Return the complete bounded tool catalog, following MCP cursors."""
        await self._initialize()
        tools: list[MCPTool] = []
        seen_names: set[str] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None

        for _page in range(MAX_TOOL_PAGES):
            result = await self._call(
                MCPListToolsRequest(
                    id=self._request_id(), params=MCPListToolsParams(cursor=cursor)
                ),
                response_body_limit=MAX_DISCOVERY_RESPONSE_BYTES,
            )
            page = _tools_page_of(result)
            for entry in page.tools:
                tool = _tool_of(entry)
                if tool.name in seen_names:
                    raise _protocol_error(MCPErrorCode.TOOL_NAME_DUPLICATE)
                seen_names.add(tool.name)
                tools.append(tool)
                if len(tools) > MAX_TOOLS:
                    raise _protocol_error(MCPErrorCode.TOOL_COUNT_EXCEEDED)

            cursor = page.next_cursor
            if cursor is None:
                return tools
            if cursor in seen_cursors:
                raise _protocol_error(MCPErrorCode.PAGINATION_CURSOR_REPEATED)
            seen_cursors.add(cursor)

        raise _protocol_error(MCPErrorCode.PAGINATION_LIMIT_EXCEEDED)

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> MCPToolResult:
        """Invoke one tool exactly once after the session handshake."""
        if not isinstance(name, str) or not name:
            raise _request_error(MCPErrorCode.TOOL_NAME_INVALID)
        if not isinstance(arguments, Mapping):
            raise _request_error(MCPErrorCode.TOOL_ARGUMENTS_INVALID)
        try:
            params = MCPCallToolParams(name=name, arguments=dict(arguments))
        except ValidationError:
            raise _request_error(MCPErrorCode.REQUEST_JSON_INVALID) from None
        await self._initialize()
        result = await self._call(
            MCPCallToolRequest(id=self._request_id(), params=params),
            response_body_limit=MAX_TOOL_RESULT_BYTES,
        )
        return _tool_result_of(result)

    async def _initialize(self) -> None:
        if self._initialized:
            return

        try:
            request_id = self._request_id()
            response = await self._post(
                MCPInitializeRequest(
                    id=request_id,
                    params=MCPInitializeParams(
                        clientInfo=MCPImplementation(
                            name=self._client_name, version=CLIENT_VERSION
                        )
                    ),
                ),
                response_body_limit=MAX_INITIALIZE_RESPONSE_BYTES,
            )
            _initialize_result_of(_result_of(_decode_response(response, request_id)))
            self._session_id = _session_id_of(response)
        except MCPError as error:
            error.method = error.method or MCPMethod.INITIALIZE
            raise

        await self._send_initialized_notification()
        self._initialized = True

    async def _send_initialized_notification(self) -> None:
        try:
            response = await self._post(
                MCPInitializedNotification(),
                response_body_limit=1,
            )
            if response.status_code != 202 or response.body:
                raise MCPError(
                    MCPErrorCode.NOTIFICATION_REJECTED,
                    "MCP server did not accept the initialized notification.",
                    delivery=MCPDeliveryState.SENT,
                    status_code=response.status_code,
                )
        except MCPError as error:
            error.method = error.method or MCPMethod.INITIALIZED
            raise

    async def _call(
        self,
        request: MCPListToolsRequest | MCPCallToolRequest,
        *,
        response_body_limit: int,
    ) -> dict[str, JsonValue]:
        try:
            response = await self._post(
                request,
                response_body_limit=response_body_limit,
            )
            return _result_of(_decode_response(response, request.id))
        except MCPError as error:
            error.method = error.method or request.method
            raise

    async def _post(
        self,
        payload: MCPRequest | MCPInitializedNotification,
        *,
        response_body_limit: int,
    ) -> HttpEgressResponse:
        try:
            body = json.dumps(
                payload.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise _request_error(MCPErrorCode.REQUEST_JSON_INVALID) from None

        public_headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._initialized or self._session_id is not None:
            public_headers["MCP-Protocol-Version"] = PROTOCOL_VERSION

        origin_values = dict(self._configured_headers.values)
        if self._session_id is not None:
            origin_values["Mcp-Session-Id"] = self._session_id
        try:
            request = HttpEgressRequest(
                method=HttpMethod.POST,
                url=self._url,
                policy=self._policy,
                headers=public_headers,
                origin_headers=OriginBoundHeaders(
                    origin=self._origin,
                    values=origin_values,
                ),
                body=body,
                response_body_limit=response_body_limit,
                total_timeout_seconds=self._timeout,
            )
            response = await self._transport.send(request)
        except HttpEgressPolicyError as error:
            raise _egress_error(error) from None
        except TimeoutError:
            raise MCPError(
                MCPErrorCode.EGRESS_OUTCOME_UNCONFIRMED,
                "MCP request delivery could not be confirmed.",
                delivery=MCPDeliveryState.UNKNOWN,
                retryable=True,
            ) from None

        if response.status_code != 200 and not isinstance(
            payload, MCPInitializedNotification
        ):
            raise _http_error(response.status_code)
        return response

    def _request_id(self) -> int:
        self._next_id += 1
        return self._next_id


def _decode_response(
    response: HttpEgressResponse,
    request_id: int,
) -> MCPRpcResponse:
    content_types = response.header_values("Content-Type")
    if len(content_types) != 1:
        raise _protocol_error(MCPErrorCode.CONTENT_TYPE_INVALID)
    media_type = content_types[0].partition(";")[0].strip().lower()
    if media_type == "application/json":
        message = _load_json(response.body)
        return _matching_response(message, request_id)
    if media_type == "text/event-stream":
        matches: list[MCPRpcResponse] = []
        for data in _sse_data(response.body):
            message = _load_json(data)
            if _is_server_request(message):
                raise _protocol_error(MCPErrorCode.SERVER_REQUEST_UNSUPPORTED)
            if _has_matching_id(message, request_id):
                matches.append(_matching_response(message, request_id))
        if len(matches) != 1:
            raise _protocol_error(MCPErrorCode.RESPONSE_MATCH_INVALID)
        return matches[0]
    raise _protocol_error(MCPErrorCode.CONTENT_TYPE_UNSUPPORTED)


def _load_json(body: bytes) -> JsonValue:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _protocol_error(MCPErrorCode.RESPONSE_JSON_INVALID) from None
    _validate_json_shape(value)
    return _JSON.validate_python(value, strict=True)


def _validate_json_shape(value: object) -> None:
    nodes = 0
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise _protocol_error(MCPErrorCode.RESPONSE_STRUCTURE_EXCEEDED)
        if isinstance(current, str):
            if len(current.encode("utf-8")) > MAX_JSON_STRING_BYTES:
                raise _protocol_error(MCPErrorCode.RESPONSE_STRING_EXCEEDED)
        elif isinstance(current, float) and not math.isfinite(current):
            raise _protocol_error(MCPErrorCode.RESPONSE_NUMBER_INVALID)
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())


def _matching_response(message: JsonValue, request_id: int) -> MCPRpcResponse:
    if not isinstance(message, dict):
        raise _protocol_error(MCPErrorCode.RESPONSE_ENVELOPE_INVALID)
    if _is_server_request(message):
        raise _protocol_error(MCPErrorCode.SERVER_REQUEST_UNSUPPORTED)
    if message.get("jsonrpc") != "2.0" or not _has_matching_id(message, request_id):
        raise _protocol_error(MCPErrorCode.RESPONSE_ENVELOPE_INVALID)
    try:
        return MCPRpcResponse.model_validate(message)
    except ValidationError:
        raise _protocol_error(MCPErrorCode.RESPONSE_ENVELOPE_INVALID) from None


def _is_server_request(message: JsonValue) -> bool:
    return (
        isinstance(message, dict)
        and isinstance(message.get("method"), str)
        and "id" in message
    )


def _has_matching_id(message: JsonValue, request_id: int) -> bool:
    return (
        isinstance(message, dict)
        and type(message.get("id")) is type(request_id)
        and message.get("id") == request_id
    )


def _result_of(message: MCPRpcResponse) -> dict[str, JsonValue]:
    if message.error is not None:
        raise MCPError(
            MCPErrorCode.MCP_RPC_ERROR,
            "MCP server returned a JSON-RPC error.",
            delivery=MCPDeliveryState.SENT,
            rpc_code=message.error.code,
        )
    if message.result is None:
        raise _protocol_error(MCPErrorCode.RESPONSE_RESULT_INVALID)
    return message.result


def _sse_data(body: bytes) -> tuple[bytes, ...]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise _protocol_error(MCPErrorCode.RESPONSE_SSE_INVALID) from None
    events: list[bytes] = []
    data_lines: list[str] = []
    for line in text.splitlines():
        if not line:
            if data_lines:
                events.append("\n".join(data_lines).encode("utf-8"))
                data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    if data_lines:
        events.append("\n".join(data_lines).encode("utf-8"))
    if not events:
        raise _protocol_error(MCPErrorCode.RESPONSE_SSE_EMPTY)
    return tuple(events)


def _session_id_of(response: HttpEgressResponse) -> str | None:
    values = response.header_values("Mcp-Session-Id")
    if not values:
        return None
    if len(values) != 1:
        raise _protocol_error(MCPErrorCode.SESSION_ID_INVALID)
    session_id = values[0]
    if (
        not session_id
        or len(session_id) > MAX_SESSION_ID_LENGTH
        or any(
            ord(character) < 0x21 or ord(character) > 0x7E for character in session_id
        )
    ):
        raise _protocol_error(MCPErrorCode.SESSION_ID_INVALID)
    return session_id


def _initialize_result_of(result: dict[str, JsonValue]) -> MCPInitializeResult:
    try:
        initialized = MCPInitializeResult.model_validate(result, by_name=False)
    except ValidationError as error:
        field = error.errors(include_input=False)[0]["loc"][0]
        if field == "protocolVersion":
            code = MCPErrorCode.PROTOCOL_VERSION_UNSUPPORTED
        elif field == "capabilities":
            code = MCPErrorCode.TOOLS_CAPABILITY_MISSING
        else:
            code = MCPErrorCode.SERVER_INFO_INVALID
        raise _protocol_error(code) from None
    if initialized.protocol_version != PROTOCOL_VERSION:
        raise _protocol_error(MCPErrorCode.PROTOCOL_VERSION_UNSUPPORTED)
    if initialized.capabilities.tools is None:
        raise _protocol_error(MCPErrorCode.TOOLS_CAPABILITY_MISSING)
    return initialized


def _tools_page_of(result: dict[str, JsonValue]) -> MCPToolsPage:
    try:
        page = MCPToolsPage.model_validate(result, by_name=False)
    except ValidationError as error:
        location = error.errors(include_input=False)[0]["loc"]
        if location[0] == "nextCursor":
            code = MCPErrorCode.PAGINATION_CURSOR_INVALID
        elif len(location) > 1:
            code = MCPErrorCode.TOOL_DEFINITION_INVALID
        else:
            code = MCPErrorCode.TOOLS_LIST_INVALID
        raise _protocol_error(code) from None
    if "next_cursor" in page.model_fields_set and page.next_cursor is None:
        raise _protocol_error(MCPErrorCode.PAGINATION_CURSOR_INVALID)
    return page


def _tool_of(tool: MCPWireTool) -> MCPTool:
    return MCPTool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        annotations=tool.annotations,
    )


def _tool_result_of(result: dict[str, JsonValue]) -> MCPToolResult:
    if "structuredContent" in result:
        raise _protocol_error(MCPErrorCode.STRUCTURED_RESULT_UNSUPPORTED)
    try:
        parsed = MCPCallToolResult.model_validate(result, by_name=False)
    except ValidationError as error:
        location = error.errors(include_input=False)[0]["loc"]
        if location[0] == "isError":
            code = MCPErrorCode.TOOL_ERROR_FLAG_INVALID
        elif len(location) == 2 or (len(location) > 2 and location[2] == "type"):
            code = MCPErrorCode.TOOL_CONTENT_UNSUPPORTED
        else:
            code = MCPErrorCode.TOOL_CONTENT_INVALID
        raise _protocol_error(code) from None
    parts: list[str] = []
    size = 0
    for block in parsed.content:
        size += len(block.text.encode("utf-8"))
        if size > MAX_TOOL_RESULT_BYTES:
            raise _protocol_error(MCPErrorCode.TOOL_RESULT_EXCEEDED)
        parts.append(block.text)
    return MCPToolResult(text="\n".join(parts), is_error=parsed.is_error)


def _http_error(status_code: int) -> MCPError:
    return MCPError(
        MCPErrorCode.HTTP_STATUS_ERROR,
        "MCP server rejected the request.",
        delivery=MCPDeliveryState.SENT,
        retryable=status_code in _RETRYABLE_STATUS,
        status_code=status_code,
    )


def _egress_error(error: HttpEgressPolicyError) -> MCPError:
    if error.code in _PRE_WIRE_RETRYABLE_ERRORS:
        return MCPError(
            MCPErrorCode.EGRESS_UNAVAILABLE,
            "MCP server is temporarily unavailable.",
            delivery=MCPDeliveryState.NOT_SENT,
            retryable=True,
        )
    if error.code in _POST_WIRE_POLICY_ERRORS:
        delivery = MCPDeliveryState.SENT
    elif error.code == HttpEgressErrorCode.TRANSPORT_FAILED:
        delivery = MCPDeliveryState.UNKNOWN
    else:
        delivery = MCPDeliveryState.NOT_SENT
    return MCPError(
        MCPErrorCode.EGRESS_POLICY_REJECTED
        if delivery is MCPDeliveryState.NOT_SENT
        else MCPErrorCode.EGRESS_OUTCOME_UNCONFIRMED,
        "MCP request failed at the outbound boundary.",
        delivery=delivery,
        retryable=delivery is not MCPDeliveryState.NOT_SENT,
    )


def _request_error(code: MCPErrorCode) -> MCPError:
    return MCPError(
        code,
        "MCP request is invalid.",
        delivery=MCPDeliveryState.NOT_SENT,
    )


def _protocol_error(code: MCPErrorCode) -> MCPError:
    return MCPError(
        code,
        "MCP server returned an unsupported protocol response.",
        delivery=MCPDeliveryState.SENT,
    )


__all__ = [
    "MCPClient",
    "MCPDeliveryState",
    "MCPError",
    "MCPErrorCode",
    "MCPMethod",
    "MCPHttpTransport",
    "MCPTool",
    "MCPToolResult",
    "PROTOCOL_VERSION",
]
