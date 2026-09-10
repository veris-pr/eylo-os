"""Bounded, revision-safe verification of Docker sandbox authority."""

from __future__ import annotations

import asyncio
import uuid
from uuid import UUID

from eylo.common.contracts.sandbox import SandboxManifest
from eylo.common.database import start_transaction
from eylo.modules.sandbox_configs.catalog import SandboxProviders
from eylo.modules.sandbox_configs.domain import (
    SandboxNetworkMode,
    SandboxProviderConfig,
    SandboxVerificationMetadata,
    SandboxWorkspaceStorage,
)
from eylo.modules.sandbox_configs.verification import (
    SandboxProviderVerifier,
    SandboxVerificationError,
    SandboxVerificationEvidence,
    SandboxVerificationResult,
)
from eylo.modules.sandbox_configs.wiring import build_sandbox_config_service
from eylo.sockets.sandbox.vendors.docker import DockerSandboxAdapter

_VERIFICATION_TIMEOUT_SECONDS = 120.0


class SandboxRuntimeVerifier:
    """Exercise the exact Docker image and execution boundary used by live work."""

    async def verify(
        self,
        *,
        config: SandboxProviderConfig,
    ) -> SandboxVerificationEvidence:
        if config.provider is not SandboxProviders.DOCKER:
            raise SandboxVerificationError("Unsupported sandbox provider.")
        adapter = DockerSandboxAdapter(config.config.endpoint)
        try:
            async with asyncio.timeout(_VERIFICATION_TIMEOUT_SECONDS):
                image_id, server_version = await adapter.resolve_image(
                    config.config.image
                )
                manifest = _verification_manifest(config, image_id=image_id)
                await adapter.verify_runtime(manifest)
                await adapter.verify_limits(manifest)
        except Exception as error:
            raise SandboxVerificationError(
                "Sandbox provider verification failed."
            ) from error
        return SandboxVerificationEvidence(
            verified_image_id=image_id,
            docker_server_version=server_version,
        )


class SandboxConfigVerificationUseCase:
    """Verify outside a DB transaction, then CAS the unchanged revision."""

    def __init__(self, verifier: SandboxProviderVerifier) -> None:
        self._verifier = verifier

    async def verify(
        self,
        *,
        organization_id: UUID,
        config_id: UUID,
    ) -> SandboxVerificationResult:
        async with start_transaction():
            stored = await build_sandbox_config_service().get(
                organization_id=organization_id,
                config_id=config_id,
            )
            config = SandboxProviderConfig.from_config(
                provider=stored.provider,
                config=stored.config,
                secrets=stored.secrets,
            )
            expected_revision = stored.revision

        evidence = await self._verifier.verify(config=config)
        metadata = SandboxVerificationMetadata(
            endpoint=config.config.endpoint,
            configured_image=config.config.image,
            verified_image_id=evidence.verified_image_id,
            docker_server_version=evidence.docker_server_version,
            network_mode=SandboxNetworkMode.NONE,
            workspace_storage=SandboxWorkspaceStorage.TMPFS,
        )
        async with start_transaction():
            verified = await build_sandbox_config_service().mark_verified(
                organization_id=organization_id,
                config_id=config_id,
                expected_revision=expected_revision,
                verification_metadata=metadata.model_dump(mode="json"),
            )
        assert verified.verified_at is not None
        return SandboxVerificationResult(
            provider=SandboxProviders(verified.provider),
            revision=verified.revision,
            verified_at=verified.verified_at,
        )


def _verification_manifest(
    config: SandboxProviderConfig,
    *,
    image_id: str,
) -> SandboxManifest:
    return config.config.manifest(
        session_id=uuid.uuid4(),
        image=image_id,
    )
