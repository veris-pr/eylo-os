"""Bounded, revision-safe storage provider verification."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from eylo.common.database import start_transaction
from eylo.modules.storage_configs.domain import StorageProviderConfig
from eylo.modules.storage_configs.verification import (
    StorageProviderVerification,
    StorageProviderVerifier,
    StorageVerificationCapabilities,
    StorageVerificationError,
    StorageVerificationResult,
)
from eylo.modules.storage_configs.wiring import build_storage_config_service
from eylo.pipelines.storage.config import build_storage_runtime_config
from eylo.sockets.storage.base import StorageVendorAdapter
from eylo.sockets.storage.factory import StorageFactory
from eylo.sockets.storage.s3 import S3StorageAdapter

_VERIFICATION_TIMEOUT_SECONDS = 60.0
_VERIFICATION_CLEANUP_TIMEOUT_SECONDS = 5.0
_VERIFICATION_URL_EXPIRY_SECONDS = 60
_VERIFY_CONTENT = b"eylo-storage-verification"
logger = logging.getLogger(__name__)


class VerificationObjectState(StrEnum):
    """A cancelled upload can have an unconfirmed external effect."""

    NOT_STARTED = "not_started"
    MAY_EXIST = "may_exist"
    REMOVED = "removed"


class StorageRuntimeVerifier:
    """Exercise every operation the selected adapter claims to support."""

    async def verify(
        self,
        config: StorageProviderConfig,
        *,
        organization_id: UUID,
        provider_config_id: UUID,
    ) -> StorageProviderVerification:
        runtime_config = build_storage_runtime_config(
            config,
            organization_id=organization_id,
            provider_config_id=provider_config_id,
        )
        adapter = StorageFactory(runtime_config).get_adapter()
        key = f".eylo-verification/{uuid4()}.txt"
        object_state = VerificationObjectState.NOT_STARTED
        try:
            with tempfile.TemporaryDirectory(prefix="eylo-storage-verify-") as tmp:
                path = Path(tmp) / "probe.txt"
                path.write_bytes(_VERIFY_CONTENT)
                async with asyncio.timeout(_VERIFICATION_TIMEOUT_SECONDS):
                    if isinstance(adapter, S3StorageAdapter):
                        await adapter.head_bucket()
                    object_state = VerificationObjectState.MAY_EXIST
                    await adapter.upload_file(
                        path=path,
                        key=key,
                        content_type="text/plain",
                    )
                    downloaded = await adapter.download_object(
                        key,
                        max_bytes=len(_VERIFY_CONTENT),
                    )
                    if downloaded != _VERIFY_CONTENT:
                        raise StorageVerificationError(
                            "Storage verification read different bytes."
                        )
                    listed = await adapter.list_objects(key, limit=1)
                    if not listed or listed[0].key != key:
                        raise StorageVerificationError(
                            "Storage verification object was not listable."
                        )
                    if adapter.capabilities.presigned_download:
                        await adapter.generate_presigned_url(
                            key, expires_in=_VERIFICATION_URL_EXPIRY_SECONDS
                        )
                    if not await adapter.delete_object(key):
                        raise StorageVerificationError(
                            "Storage verification object was not deleted."
                        )
                    object_state = VerificationObjectState.REMOVED
        except Exception:
            raise StorageVerificationError(
                "Storage provider verification failed."
            ) from None
        finally:
            if object_state is VerificationObjectState.MAY_EXIST:
                await _cleanup_verification_object(adapter, key)

        capabilities = adapter.capabilities
        return StorageProviderVerification(
            provider=config.provider,
            capabilities=StorageVerificationCapabilities(
                upload=capabilities.upload,
                list=capabilities.list,
                download=capabilities.download,
                delete=capabilities.delete,
                presigned_download=capabilities.presigned_download,
            ),
        )


async def _cleanup_verification_object(adapter: StorageVendorAdapter, key: str) -> None:
    """Bounded, best-effort deletion; never consume cancellation or report success."""
    try:
        async with asyncio.timeout(_VERIFICATION_CLEANUP_TIMEOUT_SECONDS):
            deleted = await adapter.delete_object(key)
            if not deleted:
                logger.warning("Storage verification object cleanup was not confirmed.")
    except Exception as error:
        logger.warning(
            "Storage verification object cleanup failed error_type=%s",
            type(error).__name__,
        )


class StorageConfigVerificationUseCase:
    """Keep provider I/O outside DB transactions, then CAS the revision."""

    def __init__(self, verifier: StorageProviderVerifier) -> None:
        self._verifier = verifier

    async def verify(
        self,
        *,
        organization_id: UUID,
        config_id: UUID,
    ) -> StorageVerificationResult:
        async with start_transaction():
            stored = await build_storage_config_service().get(
                organization_id=organization_id,
                config_id=config_id,
            )
            provider_config = StorageProviderConfig.from_input(
                provider=stored.provider,
                config=stored.config,
                secrets=stored.secrets,
            )
            expected_revision = stored.revision

        result = await self._verifier.verify(
            provider_config,
            organization_id=organization_id,
            provider_config_id=config_id,
        )
        try:
            result = StorageProviderVerification.model_validate(result)
        except ValidationError:
            raise StorageVerificationError(
                "Storage verification returned invalid capabilities."
            ) from None
        if result.provider is not provider_config.provider:
            raise StorageVerificationError(
                "Storage verification returned a different provider."
            )

        async with start_transaction():
            verified = await build_storage_config_service().mark_verified(
                organization_id=organization_id,
                config_id=config_id,
                expected_revision=expected_revision,
            )
        if verified.verified_at is None:
            raise StorageVerificationError("Storage verification was not persisted.")
        return StorageVerificationResult(
            provider=result.provider,
            revision=verified.revision,
            verified_at=verified.verified_at,
            capabilities=result.capabilities,
        )
