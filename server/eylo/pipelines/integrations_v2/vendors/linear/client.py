"""Linear GraphQL helpers shared by curated Linear tools.

Linear answers a failed operation with HTTP 200 and a populated `errors` array,
so success has to be read out of the body rather than the status line. Doing it
once here is the reason curated tools can stay about business meaning.
"""

from __future__ import annotations

from pydantic import ValidationError

from ...contracts import VendorToolContext, VendorToolError
from .definition import GRAPHQL_PATH
from .schemas import (
    MAX_ERROR_MESSAGE_CHARS,
    LinearEnvelope,
    LinearModel,
    LinearRequest,
    LinearToolErrorCode,
)


async def query[ResultT: LinearModel](
    ctx: VendorToolContext,
    document: str,
    variables: LinearRequest,
    *,
    response_model: type[ResultT],
) -> ResultT:
    """Run a read, validating its operation-specific selection before use."""
    response = await ctx.read(
        GRAPHQL_PATH,
        method="POST",
        json={
            "query": document,
            "variables": variables.model_dump(mode="json", by_alias=True),
        },
    )
    return _data(response.status_code, response.data, response_model)


async def mutate[ResultT: LinearModel](
    ctx: VendorToolContext,
    document: str,
    variables: LinearRequest,
    *,
    response_model: type[ResultT],
) -> ResultT:
    """Run a mutating GraphQL document through the durable outbound owner."""
    response = await ctx.mutate(
        GRAPHQL_PATH,
        method="POST",
        json={
            "query": document,
            "variables": variables.model_dump(mode="json", by_alias=True),
        },
    )
    return _data(response.status_code, response.data, response_model)


def _data[ResultT: LinearModel](
    status_code: int, payload: object, response_model: type[ResultT]
) -> ResultT:
    """No parser failure may trigger another send after the outbound receipt."""
    try:
        envelope = LinearEnvelope.model_validate(payload)
    except ValidationError:
        raise VendorToolError(
            LinearToolErrorCode.RESPONSE_INVALID,
            "Linear returned an invalid response envelope.",
        ) from None
    if envelope.errors:
        message = envelope.errors[0].message.strip()[:MAX_ERROR_MESSAGE_CHARS]
        raise VendorToolError(
            LinearToolErrorCode.REJECTED, message or "Linear rejected the request."
        )
    if not 200 <= status_code < 300:
        raise VendorToolError(
            LinearToolErrorCode.REJECTED,
            f"Linear rejected the request with HTTP {status_code}.",
        )
    try:
        return response_model.model_validate(envelope.data)
    except ValidationError:
        raise VendorToolError(
            LinearToolErrorCode.RESPONSE_INVALID,
            "Linear returned an invalid result for the operation.",
        ) from None


__all__ = ["mutate", "query"]
