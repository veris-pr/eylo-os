"""Bedrock Agent Runtime inline-text rerank requests, pages and error envelopes."""

from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    field_validator,
)

BEDROCK_AGENT_RUNTIME_SERVICE = "bedrock-agent-runtime"
MAX_DOCUMENTS = 1000
MAX_TEXT_CHARACTERS = 32_000
MAX_TOKEN_CHARACTERS = 2048
MAX_MODEL_ARN_CHARACTERS = 2048
# Platform work bound, not a vendor promise about page sizes.
MAX_RESPONSE_PAGES = MAX_DOCUMENTS
BedrockText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARACTERS)]
BedrockNextToken = Annotated[
    str, Field(min_length=1, max_length=MAX_TOKEN_CHARACTERS, pattern=r"^\S+$")
]


class BedrockContentType(StrEnum):
    TEXT = "TEXT"


class BedrockSourceType(StrEnum):
    INLINE = "INLINE"


class BedrockRerankingType(StrEnum):
    MODEL = "BEDROCK_RERANKING_MODEL"


class BedrockRerankRequest(BaseModel):
    """Active inline-TEXT path; SDK nesting is generated only at dispatch."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    query: BedrockText = Field(repr=False, exclude=True)
    documents: tuple[BedrockText, ...] = Field(
        min_length=1, max_length=MAX_DOCUMENTS, repr=False, exclude=True
    )
    model_arn: str = Field(min_length=1, max_length=MAX_MODEL_ARN_CHARACTERS)
    number_of_results: int = Field(ge=1, le=MAX_DOCUMENTS)
    next_token: BedrockNextToken | None = Field(default=None, repr=False, exclude=True)

    def to_payload(self) -> dict[str, JsonValue]:
        request = type(self).model_validate(self)
        payload: dict[str, JsonValue] = {
            "queries": [
                {
                    "type": BedrockContentType.TEXT.value,
                    "textQuery": {"text": request.query},
                }
            ],
            "sources": [
                {
                    "type": BedrockSourceType.INLINE.value,
                    "inlineDocumentSource": {
                        "type": BedrockContentType.TEXT.value,
                        "textDocument": {"text": document},
                    },
                }
                for document in request.documents
            ],
            "rerankingConfiguration": {
                "type": BedrockRerankingType.MODEL.value,
                "bedrockRerankingConfiguration": {
                    "numberOfResults": request.number_of_results,
                    "modelConfiguration": {"modelArn": request.model_arn},
                },
            },
        }
        if request.next_token is not None:
            payload["nextToken"] = request.next_token
        return payload


class _BedrockResponse(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class BedrockRankedDocument(_BedrockResponse):
    """Native indices/scores only; vendor document echoes cannot replace source data."""

    index: int = Field(ge=0)
    relevance_score: FiniteFloat = Field(alias="relevanceScore")


class BedrockRerankResponse(_BedrockResponse):
    results: list[BedrockRankedDocument] = Field(max_length=MAX_DOCUMENTS)
    next_token: BedrockNextToken | None = Field(
        default=None, alias="nextToken", repr=False, exclude=True
    )


class BedrockFailureCode(StrEnum):
    ACCESS_DENIED = "AccessDeniedException"
    EXPIRED_TOKEN = "ExpiredTokenException"
    INVALID_SIGNATURE = "InvalidSignatureException"
    UNRECOGNIZED_CLIENT = "UnrecognizedClientException"
    THROTTLED = "ThrottlingException"
    QUOTA_EXCEEDED = "ServiceQuotaExceededException"
    INTERNAL_SERVER = "InternalServerException"
    MODEL_NOT_READY = "ModelNotReadyException"
    SERVICE_UNAVAILABLE = "ServiceUnavailableException"
    UNKNOWN = "unknown"


class BedrockErrorDetail(_BedrockResponse):
    """Classify codes without retaining provider-controlled error messages."""

    code: BedrockFailureCode = Field(default=BedrockFailureCode.UNKNOWN, alias="Code")

    @field_validator("code", mode="before")
    @classmethod
    def _code(cls, value: object) -> BedrockFailureCode:
        if not isinstance(value, str):
            raise ValueError("Bedrock error code must be a string.")
        try:
            return BedrockFailureCode(value)
        except ValueError:
            return BedrockFailureCode.UNKNOWN


class BedrockResponseMetadata(_BedrockResponse):
    status: int | None = Field(default=None, alias="HTTPStatusCode", ge=100, le=599)


class BedrockErrorResponse(_BedrockResponse):
    error: BedrockErrorDetail = Field(default_factory=BedrockErrorDetail, alias="Error")
    metadata: BedrockResponseMetadata = Field(
        default_factory=BedrockResponseMetadata, alias="ResponseMetadata"
    )
