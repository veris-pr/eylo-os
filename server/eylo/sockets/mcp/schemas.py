"""MCP 2025-06-18 wire contracts for Eylo's existing text-tool client.

Unknown response metadata is ignored, not interpreted as platform policy. These
models describe only the operations implemented by this adapter; they do not
advertise sampling, resources or structured-result support.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

PROTOCOL_VERSION = "2025-06-18"
CLIENT_VERSION = "0.1.0"
MAX_CURSOR_LENGTH = 1_024


class MCPMethod(StrEnum):
    """Protocol methods implemented by this adapter, not platform tool names."""

    INITIALIZE = "initialize"
    INITIALIZED = "notifications/initialized"
    LIST_TOOLS = "tools/list"
    CALL_TOOL = "tools/call"


class _WireValue(BaseModel):
    """Validate native values without coercion; tolerate extension metadata."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )


class MCPImplementation(_WireValue):
    """Implementation identity exchanged during initialization."""

    name: str
    version: str


class MCPInitializeParams(_WireValue):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["2025-06-18"] = Field(
        default=PROTOCOL_VERSION, alias="protocolVersion"
    )
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)
    client_info: MCPImplementation = Field(alias="clientInfo")


class MCPListToolsParams(_WireValue):
    model_config = ConfigDict(extra="forbid")

    cursor: str | None = Field(default=None, min_length=1, max_length=MAX_CURSOR_LENGTH)


class MCPCallToolParams(_WireValue):
    """Explicit wire serialization includes arguments; diagnostic repr does not."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    arguments: dict[str, JsonValue] = Field(repr=False)


class _Request(_WireValue):
    """Outbound request fields are closed; the client owns integer IDs."""

    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"
    id: int


class MCPInitializeRequest(_Request):
    method: Literal[MCPMethod.INITIALIZE] = MCPMethod.INITIALIZE
    params: MCPInitializeParams


class MCPListToolsRequest(_Request):
    method: Literal[MCPMethod.LIST_TOOLS] = MCPMethod.LIST_TOOLS
    params: MCPListToolsParams = Field(default_factory=MCPListToolsParams)


class MCPCallToolRequest(_Request):
    method: Literal[MCPMethod.CALL_TOOL] = MCPMethod.CALL_TOOL
    params: MCPCallToolParams = Field(repr=False)


class MCPInitializedNotification(_WireValue):
    """Notifications cannot carry a request ID."""

    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"
    method: Literal[MCPMethod.INITIALIZED] = MCPMethod.INITIALIZED


type MCPRequest = MCPInitializeRequest | MCPListToolsRequest | MCPCallToolRequest


class MCPRpcError(_WireValue):
    """Provider error text is parsed but never used as the public failure."""

    code: int
    message: str = Field(repr=False, exclude=True)
    data: JsonValue = Field(default=None, repr=False, exclude=True)


class MCPRpcResponse(_WireValue):
    """A matching response has exactly one non-null result or error."""

    jsonrpc: Literal["2.0"]
    id: int | str
    result: dict[str, JsonValue] | None = Field(default=None, repr=False, exclude=True)
    error: MCPRpcError | None = None

    @model_validator(mode="after")
    def require_outcome(self) -> Self:
        present = self.model_fields_set & {"result", "error"}
        if len(present) != 1 or (self.result is None and self.error is None):
            raise ValueError("MCP response requires exactly one result or error.")
        return self


class MCPServerCapabilities(_WireValue):
    tools: dict[str, JsonValue] | None = None


class MCPInitializeResult(_WireValue):
    protocol_version: str = Field(alias="protocolVersion")
    capabilities: MCPServerCapabilities
    server_info: MCPImplementation = Field(alias="serverInfo")


class MCPWireTool(_WireValue):
    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, JsonValue] = Field(alias="inputSchema")
    output_schema: dict[str, JsonValue] | None = Field(
        default=None, alias="outputSchema"
    )
    annotations: dict[str, JsonValue] = Field(default_factory=dict)


class MCPToolsPage(_WireValue):
    tools: list[MCPWireTool]
    next_cursor: str | None = Field(
        default=None, alias="nextCursor", min_length=1, max_length=MAX_CURSOR_LENGTH
    )


class MCPTextContent(_WireValue):
    type: Literal["text"]
    text: str = Field(repr=False, exclude=True)


class MCPCallToolResult(_WireValue):
    """Text-only response projection; other content remains explicitly unsupported."""

    content: list[MCPTextContent] = Field(repr=False, exclude=True)
    is_error: bool = Field(default=False, alias="isError")
