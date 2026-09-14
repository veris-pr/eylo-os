"""Application-owned MCP failures, separate from adapter protocol failures."""

from enum import StrEnum


class MCPFailureCode(StrEnum):
    """Stable application failure vocabulary for tool and outbound receipts."""

    CONFIGURATION_UNAVAILABLE = "configuration_unavailable"
    MCP_CONFIGURATION_INVALID = "mcp_configuration_invalid"
    MCP_EFFECT_UNSUPPORTED = "mcp_effect_unsupported"
    MCP_INPUT_INVALID = "mcp_input_invalid"
    DURABLE_EXECUTION_REQUIRED = "durable_execution_required"
    MCP_TOOL_ERROR = "mcp_tool_error"
    MCP_EXECUTION_UNAVAILABLE = "mcp_execution_unavailable"
    MCP_HANDSHAKE_UNAVAILABLE = "mcp_handshake_unavailable"
    MCP_HANDSHAKE_REJECTED = "mcp_handshake_rejected"
    MCP_EGRESS_UNAVAILABLE = "mcp_egress_unavailable"
    MCP_EGRESS_REJECTED = "mcp_egress_rejected"
    MCP_OUTCOME_UNCONFIRMED = "mcp_outcome_unconfirmed"
    MCP_PROVIDER_RETRYABLE = "mcp_provider_retryable"
    MCP_PROVIDER_REJECTED = "mcp_provider_rejected"
    MCP_RPC_REJECTED = "mcp_rpc_rejected"
