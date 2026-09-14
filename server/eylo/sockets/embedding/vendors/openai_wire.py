"""OpenAI embedding request material and validated SDK response projection."""

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

MAX_BATCH = 256


class OpenAIEmbeddingRequest(BaseModel):
    """Text-only SDK input; token-array requests are not a platform capability."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    model: str
    input: list[str] = Field(
        min_length=1, max_length=MAX_BATCH, repr=False, exclude=True
    )


class OpenAIEmbeddingItem(BaseModel):
    """Validate SDK values even when the SDK constructed them without validation."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        from_attributes=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    index: int = Field(ge=0)
    embedding: list[FiniteFloat] = Field(min_length=1, repr=False, exclude=True)


class OpenAIEmbeddingResponse(BaseModel):
    """Only consumed fields are required, including on compatible endpoints."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        from_attributes=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    data: list[OpenAIEmbeddingItem] = Field(repr=False, exclude=True)
