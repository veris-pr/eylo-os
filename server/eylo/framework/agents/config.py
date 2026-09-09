"""Immutable run configuration for the framework path."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Final, NoReturn

from pydantic import BeforeValidator, ConfigDict, Field, JsonValue, ValidationInfo

from .common import FrozenFrameworkModel

DEFAULT_MAX_TURNS: Final = 15
DEFAULT_REQUEST_TIMEOUT_SECONDS: Final = 120.0
DEFAULT_MAX_HANDOFFS: Final = 3
DEFAULT_HANDOFF_LOOKBACK_WINDOW: Final = 10


class _RunMode(Enum):
    """Named choices whose existing JSON representation is a boolean.

    A disabled enum is still truthy in Python by default. Refuse implicit truth
    tests so a missed boolean caller cannot silently enable an execution mode.
    """

    def __bool__(self) -> NoReturn:
        raise TypeError("Compare framework modes with their explicit enum member.")


class RunStreaming(_RunMode):
    """Pipeline model delivery selection; the loop itself consumes full responses."""

    DISABLED = False
    ENABLED = True


class RunPromptCaching(_RunMode):
    """Framework cache request, translated to provider policy by the pipeline."""

    DISABLED = False
    ENABLED = True


class RunTracing(_RunMode):
    """Reserved tracing choice; currently does not control lifecycle hooks."""

    DISABLED = False
    ENABLED = True


def validate_mode_snapshot(value: object, info: ValidationInfo) -> object:
    """Accept boolean JSON snapshots, not numeric aliases such as 0 and 1.

    Python callers must supply the field's own enum; strict enum validation
    enforces that after this check. Enum values here may be validated defaults.
    """
    if info.mode == "json" and not isinstance(value, (bool, _RunMode)):
        raise ValueError("Framework mode snapshots require JSON booleans.")
    return value


class RunConfig(FrozenFrameworkModel):
    """Per-run settings, revalidated before execution even after an unchecked copy.

    Limits are finite numbers, never boolean flags or coerced text. Metadata is
    transportable annotation only; live dependencies belong in the run context.
    """

    model_config = ConfigDict(
        strict=True,
        allow_inf_nan=False,
        revalidate_instances="always",
        validate_default=True,
        hide_input_in_errors=True,
    )

    max_turns: int = Field(default=DEFAULT_MAX_TURNS, gt=0)
    request_timeout_seconds: float = Field(
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS, gt=0
    )
    stream: Annotated[RunStreaming, BeforeValidator(validate_mode_snapshot)] = (
        RunStreaming.DISABLED
    )
    prompt_caching: Annotated[
        RunPromptCaching, BeforeValidator(validate_mode_snapshot)
    ] = RunPromptCaching.DISABLED
    max_handoffs: int = Field(
        default=DEFAULT_MAX_HANDOFFS,
        ge=0,
        description="EXPERIMENTAL — not enforced by the framework loop. Does not authorize or prevent handoffs.",
        json_schema_extra={"experimental": True},
    )
    handoff_lookback_window: int = Field(
        default=DEFAULT_HANDOFF_LOOKBACK_WINDOW,
        gt=0,
        description="EXPERIMENTAL — not consumed by the framework loop. Does not change handoff history.",
        json_schema_extra={"experimental": True},
    )
    tracing_enabled: Annotated[RunTracing, BeforeValidator(validate_mode_snapshot)] = (
        Field(
            default=RunTracing.ENABLED,
            description="EXPERIMENTAL — not consumed by the framework loop. Lifecycle hooks run independently of this setting.",
            json_schema_extra={"experimental": True},
        )
    )
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
