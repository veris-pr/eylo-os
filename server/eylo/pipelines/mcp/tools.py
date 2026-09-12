"""Compose MCP server state, the safe HTTP socket, and tool synchronization."""

from __future__ import annotations

from uuid import UUID

from eylo.common.contracts.provider_config import ProviderConfigError
from eylo.common.database import current_transaction, start_transaction
from eylo.common.revisions import DefinitionLifecycle
from eylo.modules.mcp_servers.config import (
    ResolvedMCPServerConfig,
    resolve_mcp_server_config,
)
from eylo.modules.mcp_servers.schemas import MCPDiscoveredToolRead, MCPDiscoveryRead
from eylo.modules.mcp_servers.service import (
    MCPDiscoveredTool,
    MCPServerError,
    MCPServerService,
)
from eylo.modules.provider_configs.crypto import SecretCipherError
from eylo.modules.tools.models import ToolExecutionMode
from eylo.modules.tools.schemas.executors.mcp import MCPToolExecutorConfig
from eylo.sockets.http.transport import SafeHttpTransport
from eylo.sockets.mcp.client import (
    MCPClient,
    MCPError,
    MCPErrorCode,
    MCPHttpTransport,
)

from .errors import MCPFailureCode


class MCPToolError(Exception):
    """Safe application-level MCP failure."""

    def __init__(
        self,
        code: MCPFailureCode | MCPErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def server_config(
    config: object,
    *,
    organization_id: UUID,
    server_id: UUID,
    revision: int,
) -> ResolvedMCPServerConfig:
    """Decrypt one exact tenant/server/revision-bound MCP config."""
    try:
        return resolve_mcp_server_config(
            config,
            organization_id=organization_id,
            server_id=server_id,
            revision=revision,
        )
    except (ProviderConfigError, SecretCipherError, ValueError):
        raise MCPToolError(
            MCPFailureCode.CONFIGURATION_UNAVAILABLE,
            "MCP server configuration is unavailable.",
        ) from None


async def discover_tools(
    *,
    config: ResolvedMCPServerConfig,
    transport: MCPHttpTransport | None = None,
) -> list[MCPDiscoveredTool]:
    """Return one complete, bounded, successful `tools/list` snapshot."""
    try:
        tools = await MCPClient(
            url=config.url,
            origin_headers=config.origin_headers,
            transport=transport or SafeHttpTransport(),
        ).list_tools()
    except MCPError as error:
        raise MCPToolError(
            error.code,
            "MCP discovery failed.",
            retryable=error.retryable,
        ) from None
    return [
        MCPDiscoveredTool(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            annotations=tool.annotations,
        )
        for tool in tools
    ]


async def discover_mcp_server(
    *,
    organization_id: UUID,
    server_id: UUID,
    actor_id: UUID,
    transport: MCPHttpTransport | None = None,
) -> MCPDiscoveryRead:
    """Own two short transactions separated by remote I/O; return detached data.

    Call without an ambient transaction. Publication rejects a changed source
    snapshot; remote failure or cancellation never publishes a partial catalog.
    """
    if current_transaction() is not None:
        raise MCPServerError("MCP discovery must run outside a caller transaction.")
    async with start_transaction() as db:
        target = await MCPServerService(db).prepare_discovery(
            organization_id=organization_id,
            server_id=server_id,
        )
    try:
        discovered = await discover_tools(
            config=target.config,
            transport=transport,
        )
    except MCPToolError as error:
        raise MCPServerError(str(error)) from None
    async with start_transaction() as db:
        tools = await MCPServerService(db).synchronize_discovery(
            organization_id=organization_id,
            target=target,
            actor_id=actor_id,
            discovered=discovered,
        )
        return MCPDiscoveryRead(
            count=len(tools),
            tools=[
                MCPDiscoveredToolRead(
                    id=tool.id,
                    wire_id=tool.wire_id,
                    slug=tool.slug,
                    name=tool.name,
                    description=tool.description,
                    effect=MCPToolExecutorConfig.model_validate(
                        tool.executor_config
                    ).effect,
                    execution_mode=ToolExecutionMode(tool.execution_mode),
                    lifecycle=DefinitionLifecycle(tool.lifecycle),
                    published_revision=tool.published_revision,
                )
                for tool in tools
            ],
        )


__all__ = [
    "MCPToolError",
    "discover_mcp_server",
    "discover_tools",
    "server_config",
]
