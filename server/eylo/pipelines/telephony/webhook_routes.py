"""Authenticated provider status callback composition."""

from __future__ import annotations

from json import JSONDecodeError
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from eylo.common.database import start_transaction
from eylo.modules.telephony.models import TelephonyCallModel
from eylo.modules.telephony.provider_config_domain import TelephonyProvider
from eylo.modules.telephony.services import TelephonyCallService
from eylo.modules.telephony.wiring import build_telephony_config_resolver
from eylo.pipelines.telephony.call_control import (
    reconcile_outbound_call_acceptance,
)
from eylo.pipelines.telephony.status_callbacks import StatusCallbackHandler
from eylo.sockets.telephony.exotel.status_contracts import ExotelCallbackIdentity
from eylo.sockets.telephony.plivo.status_contracts import (
    PlivoCallbackIdentity,
    PlivoStatusCallback,
)
from eylo.sockets.telephony.status_contracts import CallbackIdentity, StatusCallback
from eylo.sockets.telephony.twilio.status_contracts import (
    TwilioCallbackIdentity,
    TwilioStatusCallback,
)
from eylo.sockets.telephony.vonage.status_contracts import (
    VonageCallbackIdentity,
    VonageStatusCallback,
)
from eylo.sockets.telephony.webhook_signatures import verify_status_callback

router = APIRouter(
    prefix="/telephony/webhooks",
    tags=["Telephony Webhooks"],
)

_IDENTITY_MODELS: dict[TelephonyProvider, type[CallbackIdentity]] = {
    TelephonyProvider.TWILIO: TwilioCallbackIdentity,
    TelephonyProvider.PLIVO: PlivoCallbackIdentity,
    TelephonyProvider.VONAGE: VonageCallbackIdentity,
    TelephonyProvider.EXOTEL: ExotelCallbackIdentity,
}
_JSON_OBJECT = TypeAdapter(dict[str, object])


@router.post("/{provider}/status")
async def status_callback(
    provider: Literal[
        TelephonyProvider.TWILIO,
        TelephonyProvider.PLIVO,
        TelephonyProvider.VONAGE,
        TelephonyProvider.EXOTEL,
    ],
    request: Request,
) -> Response:
    payload = await _payload(provider, request)
    try:
        call_sid = _IDENTITY_MODELS[provider].model_validate(payload).call_sid
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider call ID is required.",
        ) from None
    if provider is TelephonyProvider.EXOTEL:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Authenticated Exotel status callbacks are not supported.",
        )

    raw_call_id = request.query_params.get("call_id")
    try:
        call_id = UUID(raw_call_id) if raw_call_id else None
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from None

    async with start_transaction(ro=True) as db:
        if call_id is None:
            call = await TelephonyCallService(db=db).get_by_call_sid(call_sid)
        else:
            row = await db.scalar(
                select(TelephonyCallModel).where(
                    TelephonyCallModel.id == call_id,
                    TelephonyCallModel.deleted.is_(False),
                )
            )
            call = (
                TelephonyCallService(db=db).orm_to_schema(row)
                if row is not None
                else None
            )
        if call is None or call.provider != provider:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        resolved = await build_telephony_config_resolver(db).resolve_pinned(
            call.organization_id,
            provider_config_id=call.provider_config_id,
            revision=call.provider_config_revision,
        )

    provider_config = resolved.as_provider_config()
    public_url = (
        f"{provider_config.material.settings.webhook_base_url}"
        f"/telephony/webhooks/{provider.value}/status"
    )
    if request.url.query:
        public_url = f"{public_url}?{request.url.query}"
    if not verify_status_callback(
        provider=provider.value,
        config=provider_config.settings_values(),
        secrets=provider_config.secret_values(),
        method=request.method,
        public_url=public_url,
        headers=request.headers,
        params=payload,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    callback = _status(provider, payload)
    if call_id is not None:
        await reconcile_outbound_call_acceptance(
            call_id=call_id,
            organization_id=call.organization_id,
            provider_reference=call_sid,
        )

    await StatusCallbackHandler().handle(callback, provider)
    return Response(status_code=status.HTTP_200_OK)


async def _payload(provider: TelephonyProvider, request: Request) -> dict[str, object]:
    """Preserve signed fields; reject invalid containers without echoing input."""
    if provider is TelephonyProvider.VONAGE:
        try:
            value: object = await request.json()
            return _JSON_OBJECT.validate_python(value, strict=True)
        except (JSONDecodeError, UnicodeDecodeError, ValidationError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider callback payload must be an object.",
            ) from None
    async with request.form() as form:
        if any(not isinstance(value, str) for value in form.values()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider callback fields must be text.",
            )
        return dict(form)


def _status(provider: TelephonyProvider, payload: dict[str, object]) -> StatusCallback:
    """Translate only supported, authenticated carrier observations."""
    try:
        if provider is TelephonyProvider.TWILIO:
            return TwilioStatusCallback.model_validate(payload).to_status()
        if provider is TelephonyProvider.PLIVO:
            return PlivoStatusCallback.model_validate(payload).to_status()
        if provider is TelephonyProvider.VONAGE:
            return VonageStatusCallback.model_validate(payload).to_status()
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider callback status fields are invalid.",
        ) from None
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
