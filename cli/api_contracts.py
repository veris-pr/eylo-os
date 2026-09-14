"""CLI-owned OpenAPI discovery and finite JSON request contracts."""

from __future__ import annotations

from enum import StrEnum
from http import HTTPMethod
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter


class CliValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


JSON_VALUE = TypeAdapter(JsonValue, config=ConfigDict(strict=True, allow_inf_nan=False))
JSON_OBJECT = TypeAdapter(
    dict[str, JsonValue], config=ConfigDict(strict=True, allow_inf_nan=False)
)


class ParameterLocation(StrEnum):
    QUERY = "query"
    HEADER = "header"
    PATH = "path"
    COOKIE = "cookie"


class ApiAuthentication(StrEnum):
    REQUIRED = "required"
    ANONYMOUS = "anonymous"


class OpenApiValue(BaseModel):
    """Project only CLI-consumed specification fields; extensions stay vendor-owned."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        validate_by_name=True,
        hide_input_in_errors=True,
    )


class OpenApiSchema(OpenApiValue):
    reference: str | None = Field(default=None, alias="$ref")
    all_of: list[OpenApiSchema] = Field(default_factory=list, alias="allOf")
    properties: dict[str, OpenApiSchema] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class OpenApiParameter(OpenApiValue):
    name: str | None = None
    location: ParameterLocation | None = Field(default=None, alias="in")
    required: Annotated[bool, Field(strict=True)] = False
    reference: str | None = Field(default=None, alias="$ref")


class OpenApiMedia(OpenApiValue):
    body_schema: OpenApiSchema = Field(default_factory=OpenApiSchema, alias="schema")


class OpenApiRequestBody(OpenApiValue):
    required: Annotated[bool, Field(strict=True)] = False
    content: dict[str, OpenApiMedia] = Field(default_factory=dict)


class OpenApiOperation(OpenApiValue):
    operation_id: str | None = Field(default=None, alias="operationId")
    summary: str | None = None
    parameters: list[OpenApiParameter] = Field(default_factory=list)
    request_body: OpenApiRequestBody | None = Field(default=None, alias="requestBody")
    security: list[dict[str, list[str]]] = Field(default_factory=list)


class OpenApiPathItem(OpenApiValue):
    parameters: list[OpenApiParameter] = Field(default_factory=list)
    get: OpenApiOperation | None = None
    post: OpenApiOperation | None = None
    put: OpenApiOperation | None = None
    patch: OpenApiOperation | None = None
    delete: OpenApiOperation | None = None

    def operations(self) -> tuple[tuple[HTTPMethod, OpenApiOperation], ...]:
        return tuple(
            (method, operation)
            for method, operation in (
                (HTTPMethod.GET, self.get),
                (HTTPMethod.POST, self.post),
                (HTTPMethod.PUT, self.put),
                (HTTPMethod.PATCH, self.patch),
                (HTTPMethod.DELETE, self.delete),
            )
            if operation is not None
        )


class OpenApiComponents(OpenApiValue):
    schemas: dict[str, OpenApiSchema] = Field(default_factory=dict)


class OpenApiDocument(OpenApiValue):
    paths: dict[str, OpenApiPathItem] = Field(default_factory=dict)
    components: OpenApiComponents = Field(default_factory=OpenApiComponents)


class OperationDefinition(CliValue):
    resource: str
    handler_name: str
    operation_id: str
    method: HTTPMethod
    path: str
    summary: str
    parameters: tuple[OpenApiParameter, ...]
    request_body: OpenApiRequestBody | None
    security: tuple[dict[str, list[str]], ...]
    required_inputs: tuple[str, ...]


class ApiRequestOptions(CliValue):
    """Explicit request handoff; private content is not a diagnostic snapshot."""

    query: dict[str, JsonValue] | None = Field(repr=False, exclude=True)
    headers: dict[str, str] | None = Field(repr=False, exclude=True)
    json_body: JsonValue = Field(repr=False, exclude=True)
    form: dict[str, JsonValue] | None = Field(repr=False, exclude=True)
    uploads: dict[str, Path] | None = Field(repr=False, exclude=True)
    authentication: ApiAuthentication
