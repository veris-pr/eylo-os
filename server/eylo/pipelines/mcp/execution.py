"""Exact MCP tool execution with declared effect and durable mutation policy."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from eylo.common.outbound import (
    OutboundAttemptIdentity,
    OutboundAttemptSpec,
    OutboundAttemptState,
    OutboundOwnerKind,
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendRetryable,
    OutboundSendSucceeded,
    OutboundSendTerminal,
    OutboundSendUnknown,
    OutboundTransportKind,
    fingerprint_outbound_input,
)
from eylo.modules.mcp_servers.config import ResolvedMCPServerConfig
from eylo.modules.tools.schemas.executors.mcp import (
    MCPToolEffect,
    MCPToolExecutorConfig,
)
from eylo.pipelines.outbound.durable_execution import (
    CommandStepContext,
    OutboundExecutionReceipt,
    execute_outbound_attempt,
)
from eylo.sockets.http.transport import SafeHttpTransport
from eylo.sockets.mcp.client import (
    MCPClient,
    MCPDeliveryState,
    MCPError,
    MCPErrorCode,
    MCPHttpTransport,
    MCPMethod,
    MCPToolResult,
)

from .errors import MCPFailureCode

_TERMINAL_RPC_CODES = frozenset({-32700, -32600, -32601, -32602})
_COMPLETED_RESULT_ERRORS = frozenset(
    {
        MCPErrorCode.STRUCTURED_RESULT_UNSUPPORTED,
        MCPErrorCode.TOOL_CONTENT_INVALID,
        MCPErrorCode.TOOL_CONTENT_UNSUPPORTED,
        MCPErrorCode.TOOL_ERROR_FLAG_INVALID,
        MCPErrorCode.TOOL_RESULT_EXCEEDED,
    }
)


class MCPToolExecutionOutcome(BaseModel):
    """Agent-facing result plus optional durable external-effect receipt."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    effect: MCPToolEffect
    result: MCPToolResult | None = Field(default=None, repr=False, exclude=True)
    receipt: OutboundExecutionReceipt | None = None
    failure_code: MCPFailureCode | MCPErrorCode | None = None

    @property
    def is_error(self) -> bool:
        if self.result is not None and self.result.is_error:
            return True
        if self.failure_code is not None:
            return True
        return (
            self.receipt is not None
            and self.receipt.state is not OutboundAttemptState.SUCCEEDED
        )

    @property
    def content(self) -> str | dict[str, JsonValue]:
        if self.result is not None:
            if self.result.is_error:
                return {
                    "kind": MCPFailureCode.MCP_TOOL_ERROR,
                    "error": self.result.text or "MCP tool reported an error.",
                }
            return self.result.text
        if self.receipt is not None:
            return _receipt_value(self.receipt, self.failure_code)
        return {
            "kind": "integration_error",
            "error": self.failure_code or MCPFailureCode.MCP_EXECUTION_UNAVAILABLE,
        }

    @property
    def metadata(self) -> dict[str, JsonValue]:
        values: dict[str, JsonValue] = {
            "mcp_execution": True,
            "mcp_effect": self.effect.value,
        }
        if self.receipt is not None:
            values.update(
                {
                    "outbound_attempt_id": str(self.receipt.attempt_id),
                    "outbound_state": self.receipt.state.value,
                    "outbound_send_count": self.receipt.send_count,
                    "outbound_failure_code": self.receipt.failure_code,
                }
            )
        if self.failure_code is not None:
            values["mcp_failure_code"] = self.failure_code
        return values


async def execute_mcp_operation(
    *,
    config: ResolvedMCPServerConfig,
    executor: MCPToolExecutorConfig,
    arguments: Mapping[str, JsonValue],
    organization_id: UUID | None = None,
    tool_use_message_id: UUID | None = None,
    tool_id: UUID | None = None,
    tool_revision: int | None = None,
    server_id: UUID | None = None,
    server_revision: int | None = None,
    durable_context: CommandStepContext | None = None,
    transport: MCPHttpTransport | None = None,
) -> MCPToolExecutionOutcome:
    """Execute reads once; execute idempotent mutations in an Absurd step."""
    if executor.effect is MCPToolEffect.UNSUPPORTED:
        return MCPToolExecutionOutcome(
            effect=executor.effect,
            failure_code=MCPFailureCode.MCP_EFFECT_UNSUPPORTED,
        )
    wire_transport = transport or SafeHttpTransport()
    if executor.effect is MCPToolEffect.READ_ONLY:
        return await _execute_read(
            config=config,
            executor=executor,
            arguments=arguments,
            transport=wire_transport,
        )

    if (
        organization_id is None
        or tool_use_message_id is None
        or tool_id is None
        or tool_revision is None
        or server_id is None
        or server_revision is None
        or durable_context is None
    ):
        return MCPToolExecutionOutcome(
            effect=executor.effect,
            failure_code=MCPFailureCode.DURABLE_EXECUTION_REQUIRED,
        )

    return await _execute_mutation(
        config=config,
        executor=executor,
        arguments=arguments,
        organization_id=organization_id,
        tool_use_message_id=tool_use_message_id,
        tool_id=tool_id,
        tool_revision=tool_revision,
        server_id=server_id,
        server_revision=server_revision,
        durable_context=durable_context,
        transport=wire_transport,
    )


async def _execute_read(
    *,
    config: ResolvedMCPServerConfig,
    executor: MCPToolExecutorConfig,
    arguments: Mapping[str, JsonValue],
    transport: MCPHttpTransport,
) -> MCPToolExecutionOutcome:
    try:
        result = await _call_once(
            config=config,
            executor=executor,
            arguments=arguments,
            transport=transport,
        )
    except MCPError as error:
        return MCPToolExecutionOutcome(
            effect=executor.effect,
            failure_code=error.code,
        )
    return MCPToolExecutionOutcome(effect=executor.effect, result=result)


async def _execute_mutation(
    *,
    config: ResolvedMCPServerConfig,
    executor: MCPToolExecutorConfig,
    arguments: Mapping[str, JsonValue],
    organization_id: UUID,
    tool_use_message_id: UUID,
    tool_id: UUID,
    tool_revision: int,
    server_id: UUID,
    server_revision: int,
    durable_context: CommandStepContext,
    transport: MCPHttpTransport,
) -> MCPToolExecutionOutcome:
    identity = OutboundAttemptIdentity(
        organization_id=organization_id,
        owner_kind=OutboundOwnerKind.TOOL_CALL,
        owner_id=tool_use_message_id,
        operation_key=f"integration.mcp.{tool_id.hex}",
    )
    spec = OutboundAttemptSpec(
        identity=identity,
        provider_operation=f"integration.mcp.{tool_id.hex}",
        transport_kind=OutboundTransportKind.HTTP,
        destination_origin=str(config.origin),
        request_fingerprint=fingerprint_outbound_input(
            {
                "arguments": dict(arguments),
                "effect": executor.effect.value,
                "mcp_server_id": str(server_id),
                "mcp_server_revision": server_revision,
                "mcp_tool_name": executor.mcp_tool_name,
                "protocol_version": executor.protocol_version,
                "tool_id": str(tool_id),
                "tool_revision": tool_revision,
            }
        ),
    )
    result_holder: list[MCPToolResult] = []
    projection_failure: list[MCPErrorCode] = []

    async def send(
        authorization: OutboundSendAuthorization,
    ) -> OutboundSendOutcome:
        if authorization.attempt_id != identity.attempt_id:
            raise ValueError("MCP send authorization belongs to another attempt.")
        if authorization.provider_idempotency_key != identity.provider_idempotency_key:
            raise ValueError("MCP send authorization idempotency key changed.")
        try:
            result = await _call_once(
                config=config,
                executor=executor,
                arguments=arguments,
                transport=transport,
            )
        except MCPError as error:
            if error.code in _COMPLETED_RESULT_ERRORS:
                projection_failure.append(error.code)
                return OutboundSendSucceeded(status_code=200)
            return _mutation_failure_outcome(error)
        result_holder.append(result)
        if result.is_error:
            return OutboundSendTerminal(
                failure_code=MCPFailureCode.MCP_TOOL_ERROR,
                status_code=200,
            )
        return OutboundSendSucceeded(status_code=200)

    receipt = await execute_outbound_attempt(
        spec=spec,
        context=durable_context,
        sender=send,
    )
    return MCPToolExecutionOutcome(
        effect=executor.effect,
        result=result_holder[-1] if result_holder else None,
        receipt=receipt,
        failure_code=projection_failure[-1] if projection_failure else None,
    )


async def _call_once(
    *,
    config: ResolvedMCPServerConfig,
    executor: MCPToolExecutorConfig,
    arguments: Mapping[str, JsonValue],
    transport: MCPHttpTransport,
) -> MCPToolResult:
    return await MCPClient(
        url=config.url,
        origin_headers=config.origin_headers,
        transport=transport,
    ).call_tool(executor.mcp_tool_name, arguments)


def _mutation_failure_outcome(error: MCPError) -> OutboundSendOutcome:
    if error.method != MCPMethod.CALL_TOOL:
        if error.retryable:
            return OutboundSendRetryable(
                failure_code=MCPFailureCode.MCP_HANDSHAKE_UNAVAILABLE
            )
        return OutboundSendTerminal(failure_code=MCPFailureCode.MCP_HANDSHAKE_REJECTED)
    if error.delivery is MCPDeliveryState.NOT_SENT:
        if error.retryable:
            return OutboundSendRetryable(
                failure_code=MCPFailureCode.MCP_EGRESS_UNAVAILABLE
            )
        return OutboundSendTerminal(failure_code=MCPFailureCode.MCP_EGRESS_REJECTED)
    if error.delivery is MCPDeliveryState.UNKNOWN:
        return OutboundSendUnknown(failure_code=MCPFailureCode.MCP_OUTCOME_UNCONFIRMED)
    if error.status_code is not None:
        if error.retryable:
            return OutboundSendRetryable(
                failure_code=MCPFailureCode.MCP_PROVIDER_RETRYABLE,
                status_code=error.status_code,
            )
        return OutboundSendTerminal(
            failure_code=MCPFailureCode.MCP_PROVIDER_REJECTED,
            status_code=error.status_code,
        )
    if error.rpc_code in _TERMINAL_RPC_CODES:
        return OutboundSendTerminal(failure_code=MCPFailureCode.MCP_RPC_REJECTED)
    return OutboundSendUnknown(failure_code=MCPFailureCode.MCP_OUTCOME_UNCONFIRMED)


def _receipt_value(
    receipt: OutboundExecutionReceipt,
    projection_failure: MCPFailureCode | MCPErrorCode | None,
) -> dict[str, JsonValue]:
    if receipt.state is OutboundAttemptState.SUCCEEDED:
        return {
            "kind": "outbound_succeeded",
            "attempt_id": str(receipt.attempt_id),
            "projection_error": projection_failure,
        }
    return {
        "kind": "outbound_outcome",
        "attempt_id": str(receipt.attempt_id),
        "state": receipt.state.value,
        "failure_code": receipt.failure_code,
    }


__all__ = [
    "MCPToolExecutionOutcome",
    "execute_mcp_operation",
]
