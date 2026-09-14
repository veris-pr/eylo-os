"""Sandbox provider policy and immutable resolved authority."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.common.contracts.sandbox import SandboxManifest
from eylo.modules.provider_configs.domain import (
    EffectiveProviderConfig,
    InvalidProviderConfig,
)
from eylo.modules.sandbox_configs.catalog import SandboxProviders

__all__ = [
    "InvalidSandboxConfig",
    "ResolvedSandbox",
    "SandboxExecutionSettings",
    "SandboxNetworkMode",
    "SandboxProviderConfig",
    "SandboxVerificationMetadata",
    "SandboxWorkspaceStorage",
]

_CONFIG_FIELDS = (
    "endpoint",
    "image",
    "memory_mb",
    "cpu_cores",
    "disk_mb",
    "pids",
    "ttl_seconds",
    "command_timeout_seconds",
    "max_output_bytes",
    "max_sessions",
    "network",
)
_ALLOWED_CONFIG_FIELDS = {
    SandboxProviders.DOCKER: frozenset(_CONFIG_FIELDS),
}
_REQUIRED_CONFIG_FIELDS = {
    SandboxProviders.DOCKER: _CONFIG_FIELDS,
}
_VERIFICATION_JSON = TypeAdapter(
    dict[str, JsonValue], config=ConfigDict(strict=True, allow_inf_nan=False)
)


class InvalidSandboxConfig(InvalidProviderConfig):
    """A sandbox provider config violates policy."""


class SandboxExecutionSettings(BaseModel):
    """Validated immutable Docker settings; all limits remain explicit."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    endpoint: str
    image: str
    memory_mb: int
    cpu_cores: float
    disk_mb: int
    pids: int
    ttl_seconds: int
    command_timeout_seconds: int
    max_output_bytes: int
    max_sessions: int
    network: Literal[False]

    @model_validator(mode="before")
    @classmethod
    def validate_settings(cls, value: object) -> object:
        if isinstance(value, cls):
            value = value.model_dump()
        return _validate_config(SandboxProviders.DOCKER, value)

    def to_storage(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")

    def manifest(
        self,
        *,
        session_id: UUID,
        image: str,
        files: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> SandboxManifest:
        """Translate trusted policy to execution without caller limit overrides."""
        return SandboxManifest(
            id=session_id,
            image=image,
            files=dict(files or {}),
            env=dict(env or {}),
            network=False,
            memory_mb=self.memory_mb,
            cpu_cores=self.cpu_cores,
            disk_mb=self.disk_mb,
            pids=self.pids,
            ttl_seconds=self.ttl_seconds,
            command_timeout_seconds=self.command_timeout_seconds,
            max_output_bytes=self.max_output_bytes,
        )


class SandboxProviderConfig(BaseModel):
    """Explicit Docker location, image, and hard execution ceilings."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    provider: SandboxProviders
    config: SandboxExecutionSettings
    secrets: Mapping[str, str] = Field(repr=False, exclude=True)

    @field_validator("provider", mode="before")
    @classmethod
    def validate_provider(cls, value: object) -> SandboxProviders:
        return _provider(value)

    @field_validator("secrets", mode="before")
    @classmethod
    def validate_secrets(cls, value: object) -> Mapping[str, str]:
        return MappingProxyType(_validate_secrets(SandboxProviders.DOCKER, value))

    @field_validator("secrets")
    @classmethod
    def freeze_secrets(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(value))

    @classmethod
    def from_config(
        cls,
        *,
        provider: SandboxProviders | str,
        config: Mapping[str, object] | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> SandboxProviderConfig:
        try:
            return cls.model_validate(
                {
                    "provider": provider,
                    "config": {} if config is None else config,
                    "secrets": {} if secrets is None else secrets,
                }
            )
        except ValidationError as error:
            raise InvalidSandboxConfig(
                "Invalid sandbox configuration shape."
            ) from error


class SandboxNetworkMode(StrEnum):
    """Network modes for which the current Docker verifier proves isolation."""

    NONE = "none"


class SandboxWorkspaceStorage(StrEnum):
    """Workspace backends whose capacity is verified by the Docker adapter."""

    TMPFS = "tmpfs"


class SandboxVerificationMetadata(BaseModel):
    """Verifier-issued image/runtime identity; preserve additional JSON evidence."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="allow", revalidate_instances="always"
    )

    endpoint: str
    configured_image: str
    verified_image_id: str
    docker_server_version: str
    network_mode: SandboxNetworkMode
    workspace_storage: SandboxWorkspaceStorage

    @model_validator(mode="before")
    @classmethod
    def validate_evidence(cls, value: object) -> object:
        if isinstance(value, cls):
            value = value.model_dump(mode="json")
        return _VERIFICATION_JSON.validate_python(value)

    @field_validator("network_mode", mode="before")
    @classmethod
    def decode_network_mode(cls, value: object) -> SandboxNetworkMode:
        if not isinstance(value, str):
            raise ValueError("Network mode must be text.")
        return SandboxNetworkMode(value)

    @field_validator("workspace_storage", mode="before")
    @classmethod
    def decode_workspace_storage(cls, value: object) -> SandboxWorkspaceStorage:
        if not isinstance(value, str):
            raise ValueError("Workspace storage must be text.")
        return SandboxWorkspaceStorage(value)

    @field_validator("verified_image_id", "docker_server_version")
    @classmethod
    def require_identity(cls, value: str) -> str:
        _text(value, "verification identity", max_length=512)
        return value


class ResolvedSandbox(BaseModel):
    """One ready sandbox config revision selected for executable work."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    organization_id: UUID
    provider: SandboxProviders
    config: SandboxExecutionSettings
    verification_metadata: SandboxVerificationMetadata
    configured: bool
    verified: bool
    ready: bool
    granted: bool

    @model_validator(mode="after")
    def require_verified_authority(self) -> Self:
        if (
            self.verification_metadata.endpoint != self.config.endpoint
            or self.verification_metadata.configured_image != self.config.image
        ):
            raise InvalidSandboxConfig(
                "Verified sandbox authority does not match its endpoint, image, or policy."
            )
        return self

    @classmethod
    def from_effective(cls, effective: EffectiveProviderConfig) -> ResolvedSandbox:
        validated = SandboxProviderConfig.from_config(
            provider=effective.provider,
            config=effective.settings,
            secrets=effective.secrets,
        )
        return cls(
            provider_config_id=effective.provider_config_id,
            provider_config_revision=effective.revision,
            organization_id=effective.organization_id,
            provider=validated.provider,
            config=validated.config,
            verification_metadata=SandboxVerificationMetadata.model_validate(
                dict(effective.verification_metadata)
            ),
            configured=effective.configured,
            verified=effective.verified,
            ready=effective.ready,
            granted=effective.granted,
        )

    @property
    def endpoint(self) -> str:
        return self.config.endpoint

    @property
    def verified_image_id(self) -> str:
        return self.verification_metadata.verified_image_id

    @property
    def max_sessions(self) -> int:
        return self.config.max_sessions

    def manifest(
        self,
        *,
        session_id: UUID,
        files: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> SandboxManifest:
        """Build a manifest whose ceilings cannot be widened by a caller."""
        return self.config.manifest(
            session_id=session_id,
            image=self.verified_image_id,
            files=files,
            env=env,
        )


def _provider(value: object) -> SandboxProviders:
    try:
        if isinstance(value, SandboxProviders):
            return value
        if isinstance(value, str):
            return SandboxProviders(value.strip().lower())
        raise ValueError("Provider must be text.")
    except (AttributeError, ValueError):
        raise InvalidSandboxConfig(
            f"Unknown sandbox provider: {value}. Available: "
            f"{', '.join(provider.value for provider in SandboxProviders)}."
        ) from None


def _validate_config(
    provider: SandboxProviders,
    config: object,
) -> dict[str, object]:
    if not isinstance(config, Mapping):
        raise InvalidSandboxConfig("Config must be a mapping.")
    if any(not isinstance(key, str) for key in config):
        raise InvalidSandboxConfig("Config fields must have text names.")
    unknown = set(config) - _ALLOWED_CONFIG_FIELDS[provider]
    if unknown:
        raise InvalidSandboxConfig(
            f"Unknown config fields for {provider.value}: {sorted(unknown)}"
        )
    missing = [
        field for field in _REQUIRED_CONFIG_FIELDS[provider] if field not in config
    ]
    if missing:
        raise InvalidSandboxConfig(
            f"{provider.value} sandbox requires explicit {missing}; no endpoint, "
            "image, resource limit, or network posture is defaulted."
        )

    endpoint = _text(config["endpoint"], "endpoint", max_length=512)
    if not endpoint.startswith("unix:///"):
        raise InvalidSandboxConfig(
            "Docker endpoint must be an explicit absolute unix:// socket. "
            "Remote daemon credentials and host environment discovery are unsupported."
        )
    image = _text(config["image"], "image", max_length=512)
    memory_mb = _integer(config["memory_mb"], "memory_mb", 64, 16384)
    disk_mb = _integer(config["disk_mb"], "disk_mb", 64, 16384)
    if disk_mb > memory_mb:
        raise InvalidSandboxConfig(
            "disk_mb cannot exceed memory_mb because Docker V1 enforces the "
            "workspace ceiling with tmpfs."
        )
    network = config["network"]
    if network is not False:
        raise InvalidSandboxConfig(
            "Docker V1 requires network=false. Unrestricted bridge egress cannot "
            "enforce Eylo's destination policy."
        )
    return {
        "endpoint": endpoint,
        "image": image,
        "memory_mb": memory_mb,
        "cpu_cores": _number(config["cpu_cores"], "cpu_cores", 0, 8),
        "disk_mb": disk_mb,
        "pids": _integer(config["pids"], "pids", 8, 4096),
        "ttl_seconds": _integer(config["ttl_seconds"], "ttl_seconds", 60, 86400),
        "command_timeout_seconds": _integer(
            config["command_timeout_seconds"],
            "command_timeout_seconds",
            1,
            3600,
        ),
        "max_output_bytes": _integer(
            config["max_output_bytes"],
            "max_output_bytes",
            1024,
            10 * 1024 * 1024,
        ),
        "max_sessions": _integer(config["max_sessions"], "max_sessions", 1, 100),
        "network": False,
    }


def _text(value: object, field_name: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise InvalidSandboxConfig(f"{field_name} must be text.")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > max_length
        or any(ord(character) < 32 for character in normalized)
    ):
        raise InvalidSandboxConfig(f"{field_name} is invalid.")
    return normalized


def _integer(value: object, field_name: str, low: int, high: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise InvalidSandboxConfig(
            f"{field_name} must be an integer between {low} and {high}; got {value!r}."
        )
    return value


def _number(
    value: object,
    field_name: str,
    low_exclusive: float,
    high: float,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not low_exclusive < value <= high
    ):
        raise InvalidSandboxConfig(
            f"{field_name} must be greater than {low_exclusive} and at most "
            f"{high}; got {value!r}."
        )
    return float(value)


def _validate_secrets(
    provider: SandboxProviders,
    secrets: object,
) -> dict[str, str]:
    if not isinstance(secrets, Mapping):
        raise InvalidSandboxConfig("Secrets must be a mapping.")
    if secrets:
        raise InvalidSandboxConfig(
            f"{provider.value} sandbox takes no secrets. Remote daemon "
            "credentials are unsupported."
        )
    return {}
