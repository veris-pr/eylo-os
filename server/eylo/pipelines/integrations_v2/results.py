"""Curated execution projections at the platform-to-framework JSON boundary."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect


class CuratedContentKind(StrEnum):
    RESULT = "curated_result"
    ERROR = "curated_error"
    AUTH_REQUIRED = "auth_required"


class CuratedFailureAction(StrEnum):
    NONE = "none"
    CONNECT = "connect"
    APPROVE = "approve"


class CuratedExecutionErrorCode(StrEnum):
    BINDING_UNAVAILABLE = "tool_binding_unavailable"
    INPUT_INVALID = "tool_input_invalid"
    INVOCATION_INVALID = "tool_invocation_invalid"
    RESULT_INVALID = "tool_result_invalid"
    DURABLE_EXECUTION_REQUIRED = "durable_execution_required"


class _Projection(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class CuratedResultContent(_Projection):
    """Only the vendor's intentional result payload remains dynamic JSON."""

    kind: Literal[CuratedContentKind.RESULT] = CuratedContentKind.RESULT
    data: JsonValue = Field(repr=False)


class CuratedErrorContent(_Projection):
    kind: Literal[CuratedContentKind.ERROR, CuratedContentKind.AUTH_REQUIRED] = (
        CuratedContentKind.ERROR
    )
    error: str


class CuratedInvocationMetadata(_Projection):
    """Existing wire marker, including the pre-dispatch durable-context refusal."""

    curated_execution: Literal[True] = True


class CuratedResultMetadata(CuratedInvocationMetadata):
    vendor: str
    wire_id: str
    effect: ToolEffect


class CuratedErrorMetadata(CuratedInvocationMetadata):
    """Wire predicates describe a refusal; internal action selection is an enum."""

    auth_required: bool
    approval_required: bool
    error_code: str
    vendor: str | None = None


class CuratedToolExecutionOutcome(_Projection):
    """Keep content, failure state and metadata consistent before serialization."""

    content: CuratedResultContent | CuratedErrorContent = Field(
        discriminator="kind", repr=False
    )
    is_error: bool
    metadata: CuratedResultMetadata | CuratedErrorMetadata

    @model_validator(mode="after")
    def consistent_result(self) -> CuratedToolExecutionOutcome:
        if isinstance(self.content, CuratedResultContent):
            if self.is_error or not isinstance(self.metadata, CuratedResultMetadata):
                raise ValueError("Curated success requires success metadata.")
            return self
        if not self.is_error or not isinstance(self.metadata, CuratedErrorMetadata):
            raise ValueError("Curated failure requires error metadata.")
        if self.content.error != self.metadata.error_code:
            raise ValueError("Curated error codes must agree.")
        needs_auth = self.content.kind is CuratedContentKind.AUTH_REQUIRED
        if self.metadata.auth_required != needs_auth or (
            self.metadata.auth_required and self.metadata.approval_required
        ):
            raise ValueError("Curated failure action must agree with its content.")
        return self


def error_outcome(
    code: str,
    *,
    action: CuratedFailureAction = CuratedFailureAction.NONE,
    vendor: str | None = None,
) -> CuratedToolExecutionOutcome:
    """Preserve the public refusal envelope without retrying a vendor effect."""
    return CuratedToolExecutionOutcome(
        content=CuratedErrorContent(
            kind=(
                CuratedContentKind.AUTH_REQUIRED
                if action is CuratedFailureAction.CONNECT
                else CuratedContentKind.ERROR
            ),
            error=code,
        ),
        is_error=True,
        metadata=CuratedErrorMetadata(
            auth_required=action is CuratedFailureAction.CONNECT,
            approval_required=action is CuratedFailureAction.APPROVE,
            error_code=code,
            vendor=vendor,
        ),
    )
