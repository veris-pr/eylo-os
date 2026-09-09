"""Memory settings and verified dependency authority, detached from persistence."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ModelWrapValidatorHandler,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.modules.memory_configs.catalog import MemoryProviders
from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.domain import (
    EffectiveProviderConfig,
    InvalidProviderConfig,
)

EMBEDDING_PROVIDER_CONFIG_ID_KEY = "embedding_provider_config_id"
LLM_PROVIDER_CONFIG_ID_KEY = "llm_provider_config_id"


class InvalidMemoryConfig(InvalidProviderConfig):
    """A memory provider config violates policy; diagnostics omit supplied values."""


class MemoryConfigValue(BaseModel):
    """Frozen fields with validated, copied JSON; nested JSON is not deeply frozen."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
        populate_by_name=True,
    )

    @model_validator(mode="wrap")
    @classmethod
    def _safe_validation(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidMemoryConfig(
                "Memory configuration contains invalid fields or types."
            ) from None


def parse_memory_provider(value: object) -> MemoryProviders:
    """Normalize only a configured backend, never infer one from settings."""
    if not isinstance(value, str):
        raise InvalidMemoryConfig("Memory provider must be a string.")
    try:
        return MemoryProviders(value.strip().lower())
    except ValueError:
        raise InvalidMemoryConfig("Unknown memory provider.") from None


def _dependency_id(value: object) -> UUID:
    if not isinstance(value, (str, UUID)):
        raise InvalidMemoryConfig("Memory dependency identity must be a UUID.")
    try:
        return UUID(str(value))
    except ValueError:
        raise InvalidMemoryConfig(
            "Memory dependency identity must be a UUID."
        ) from None


class MemorySettings(MemoryConfigValue):
    """Explicit dependencies; each referenced config owns its vendor credentials."""

    embedding_provider_config_id: UUID
    llm_provider_config_id: UUID

    @field_validator(
        "embedding_provider_config_id", "llm_provider_config_id", mode="before"
    )
    @classmethod
    def _identity(cls, value: object) -> UUID:
        return _dependency_id(value)


class MemoryCredentials(MemoryConfigValue):
    """Memory itself accepts no secrets; embedding and LLM configs own them."""


class MemoryProviderConfig(MemoryConfigValue):
    """Typed material with explicit mapping projections for the shared config store."""

    provider: MemoryProviders
    settings: MemorySettings = Field(validation_alias="config")
    credentials: MemoryCredentials = Field(
        validation_alias="secrets", repr=False, exclude=True
    )

    @field_validator("provider", mode="before")
    @classmethod
    def _provider(cls, value: object) -> MemoryProviders:
        return parse_memory_provider(value)

    @field_validator("settings", "credentials", mode="before")
    @classmethod
    def _mapping(cls, value: object) -> object:
        return dict(value) if isinstance(value, Mapping) else value

    @classmethod
    def from_input(
        cls,
        *,
        provider: str,
        config: Mapping[str, object] | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> Self:
        return cls.model_validate(
            {
                "provider": provider,
                "config": {} if config is None else config,
                "secrets": {} if secrets is None else secrets,
            }
        )

    @property
    def config(self) -> Mapping[str, JsonValue]:
        return MappingProxyType(self.settings.model_dump(mode="json"))

    @property
    def secrets(self) -> Mapping[str, str]:
        return MappingProxyType({})

    @property
    def embedding_provider_config_id(self) -> UUID:
        return self.settings.embedding_provider_config_id

    @property
    def llm_provider_config_id(self) -> UUID:
        return self.settings.llm_provider_config_id


class MemoryDependencyAuthority(MemoryConfigValue):
    """Verified facts, shared by the writer and readback; extension metadata survives.

    Provider/model strings are recorded dependency observations, not selectors.
    Executable provider selection belongs to each dependency's owning resolver.
    """

    extensions: dict[str, JsonValue] = Field(default_factory=dict, repr=False)

    embedding_provider_config_id: UUID
    embedding_provider_config_revision: int = Field(gt=0)
    embedding_provider: str
    embedding_endpoint: str
    embedding_model: str
    embedding_dimensions: int = Field(gt=0)
    embedding_semantic_options: dict[str, JsonValue]
    embedding_space_id: str
    llm_provider_config_id: UUID
    llm_provider_config_revision: int = Field(gt=0)
    llm_provider: str
    llm_model: str

    @field_validator(
        "embedding_provider_config_id", "llm_provider_config_id", mode="before"
    )
    @classmethod
    def _identity(cls, value: object) -> UUID:
        return _dependency_id(value)

    @field_validator("embedding_semantic_options", mode="before")
    @classmethod
    def _options(cls, value: object) -> object:
        return dict(value) if isinstance(value, Mapping) else value

    @field_validator(
        "embedding_provider",
        "embedding_endpoint",
        "embedding_model",
        "embedding_space_id",
        "llm_provider",
        "llm_model",
    )
    @classmethod
    def _observation(cls, value: str) -> str:
        if not value.strip():
            raise InvalidMemoryConfig(
                "Verified memory dependency observation is missing."
            )
        return value

    @classmethod
    def from_metadata(cls, value: Mapping[str, object]) -> Self:
        """Preserve unconsumed JSON without mixing it into the typed authority."""
        fields = cls.model_fields.keys() - {"extensions"}
        return cls.model_validate(
            {
                **{key: item for key, item in value.items() if key in fields},
                "extensions": {
                    key: item for key, item in value.items() if key not in fields
                },
            }
        )

    def to_metadata(self) -> dict[str, JsonValue]:
        value = type(self).model_validate(self)
        return value.extensions | value.model_dump(mode="json", exclude={"extensions"})


class ResolvedMemory(MemoryProviderConfig):
    """One memory revision and matching verified dependency identities."""

    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    organization_id: UUID
    dependency_authority: MemoryDependencyAuthority = Field(
        validation_alias="verification_metadata"
    )
    configured: bool
    verified: bool
    ready: bool
    granted: bool

    @field_validator("dependency_authority", mode="before")
    @classmethod
    def _metadata(cls, value: object) -> MemoryDependencyAuthority:
        if isinstance(value, Mapping):
            return MemoryDependencyAuthority.from_metadata(value)
        return MemoryDependencyAuthority.model_validate(value)

    @model_validator(mode="after")
    def _matching_dependencies(self) -> Self:
        if (
            self.dependency_authority.embedding_provider_config_id
            != self.embedding_provider_config_id
            or self.dependency_authority.llm_provider_config_id
            != self.llm_provider_config_id
        ):
            raise InvalidMemoryConfig(
                "Verified memory dependency identity does not match its config."
            )
        return self

    @classmethod
    def from_effective(cls, effective: EffectiveProviderConfig) -> ResolvedMemory:
        effective = EffectiveProviderConfig.model_validate(effective)
        if effective.capability is not Capability.MEMORY:
            raise InvalidMemoryConfig(
                "Resolved configuration is not a memory capability."
            )
        return cls.model_validate(
            {
                "provider_config_id": effective.provider_config_id,
                "provider_config_revision": effective.revision,
                "organization_id": effective.organization_id,
                "provider": effective.provider,
                "config": effective.settings,
                "secrets": effective.secrets,
                "verification_metadata": effective.verification_metadata,
                "configured": effective.configured,
                "verified": effective.verified,
                "ready": effective.ready,
                "granted": effective.granted,
            }
        )

    @property
    def verification_metadata(self) -> Mapping[str, JsonValue]:
        return MappingProxyType(self.dependency_authority.to_metadata())

    @property
    def embedding_provider_config_revision(self) -> int:
        return self.dependency_authority.embedding_provider_config_revision

    @property
    def llm_provider_config_revision(self) -> int:
        return self.dependency_authority.llm_provider_config_revision
