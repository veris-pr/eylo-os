"""Titan V2 JSON and Bedrock SDK envelopes; never exported as domain objects."""

import json
from enum import StrEnum
from typing import Literal

from aiobotocore.response import StreamingBody
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

BEDROCK_RUNTIME_SERVICE = "bedrock-runtime"
JSON_CONTENT_TYPE = "application/json"
MAX_TITAN_DIMENSIONS = 1024


class TitanEmbeddingRequest(BaseModel):
    """Only the configured float-embedding request; input text stays private."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    input_text: str = Field(repr=False, exclude=True)
    dimensions: Literal[256, 512, 1024]
    normalize: bool

    def to_body(self) -> str:
        validated = type(self).model_validate(self)
        return json.dumps(
            {
                "inputText": validated.input_text,
                "dimensions": validated.dimensions,
                "normalize": validated.normalize,
            }
        )


class TitanEmbeddingTypes(BaseModel):
    """Known V2 float/binary fields; this adapter requests float output only."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    float_values: list[FiniteFloat] = Field(
        alias="float",
        min_length=1,
        max_length=MAX_TITAN_DIMENSIONS,
        repr=False,
        exclude=True,
    )
    binary: list[int] | None = Field(default=None, repr=False, exclude=True)


class TitanEmbeddingResponse(BaseModel):
    """Validated V2 response before its vector enters Knowledge or Memory."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    embedding: list[FiniteFloat] = Field(
        min_length=1, max_length=MAX_TITAN_DIMENSIONS, repr=False, exclude=True
    )
    input_text_token_count: int = Field(alias="inputTextTokenCount", ge=0)
    embeddings_by_type: TitanEmbeddingTypes = Field(
        alias="embeddingsByType", repr=False, exclude=True
    )


class BedrockInvocationResponse(BaseModel):
    """The SDK owns this live body; it is not JSON or snapshot material."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        hide_input_in_errors=True,
    )

    body: StreamingBody = Field(repr=False, exclude=True)


class BedrockFailureCode(StrEnum):
    ACCESS_DENIED = "AccessDeniedException"
    EXPIRED_TOKEN = "ExpiredTokenException"
    INVALID_SIGNATURE = "InvalidSignatureException"
    UNRECOGNIZED_CLIENT = "UnrecognizedClientException"
    THROTTLED = "ThrottlingException"
    QUOTA_EXCEEDED = "ServiceQuotaExceededException"
    INTERNAL_SERVER = "InternalServerException"
    MODEL_NOT_READY = "ModelNotReadyException"
    MODEL_TIMEOUT = "ModelTimeoutException"
    SERVICE_UNAVAILABLE = "ServiceUnavailableException"
    UNKNOWN = "unknown"


class BedrockErrorDetail(BaseModel):
    """Retain classified codes, not provider-controlled error messages."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    code: BedrockFailureCode = Field(default=BedrockFailureCode.UNKNOWN, alias="Code")

    @field_validator("code", mode="before")
    @classmethod
    def classify_code(cls, value: object) -> BedrockFailureCode:
        if not isinstance(value, str):
            raise ValueError("Bedrock error code must be a string.")
        try:
            return BedrockFailureCode(value)
        except ValueError:
            return BedrockFailureCode.UNKNOWN


class BedrockResponseMetadata(BaseModel):
    """Only transport status influences classification; diagnostic headers stay out."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    status: int | None = Field(default=None, alias="HTTPStatusCode", ge=100, le=599)


class BedrockErrorResponse(BaseModel):
    """Validate only the SDK fields used for neutral failure classification."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    error: BedrockErrorDetail = Field(default_factory=BedrockErrorDetail, alias="Error")
    metadata: BedrockResponseMetadata = Field(
        default_factory=BedrockResponseMetadata, alias="ResponseMetadata"
    )
