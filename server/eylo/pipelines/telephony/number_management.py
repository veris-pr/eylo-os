"""Controller for searching and purchasing phone numbers from providers."""

import logging
from collections.abc import Awaitable, Callable
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException

from eylo.common.database import start_transaction
from eylo.common.outbound import (
    OutboundAttemptConflict,
    OutboundAttemptIdentity,
    OutboundAttemptSpec,
    OutboundAttemptState,
    OutboundOwnerKind,
    OutboundSendAuthorization,
    OutboundSendOutcome,
    fingerprint_outbound_input,
)
from eylo.modules.telephony.constants import (
    NUMBER_PURCHASE_IDEMPOTENCY_KEY_MAX_LENGTH,
    NUMBER_PURCHASE_OPERATION,
    NUMBER_PURCHASE_RETRY_AFTER_SECONDS,
)
from eylo.modules.telephony.provider_config_domain import (
    ResolvedTelephony,
    TelephonyOperation,
    supports_telephony_operation,
)
from eylo.modules.telephony.schemas import (
    AvailableNumberSchema,
    AvailableNumbersResponseSchema,
    NumberPurchaseRequest,
    NumberSearchParams,
    NumberType,
    PhoneNumberApiResponseSchema,
    PhoneNumberInDb,
    TelephonyProviderType,
)
from eylo.modules.telephony.services import (
    PhoneNumberProvisioningConflict,
    PhoneNumberService,
)
from eylo.modules.telephony.wiring import build_telephony_config_resolver
from eylo.pipelines.outbound.durable_execution import (
    CommandStepContext,
    OutboundExecutionReceipt,
    OutboundRetryRequested,
    execute_outbound_attempt,
)
from eylo.pipelines.telephony.config import build_telephony_runtime_config
from eylo.pipelines.telephony.twilio_rest import TwilioRestClient
from eylo.sockets.telephony.config import (
    ExotelSettings,
    PlivoSettings,
    TwilioSettings,
    VonageSettings,
)
from eylo.sockets.telephony.exotel.number_contracts import (
    NumberType as ExotelNumberType,
)
from eylo.sockets.telephony.number_clients import (
    ExotelNumberClient,
    PlivoNumberClient,
    VonageNumberClient,
)
from eylo.sockets.telephony.number_purchase import NumberPurchaseClient
from eylo.sockets.telephony.plivo.number_contracts import NumberType as PlivoNumberType
from eylo.sockets.telephony.twilio.number_contracts import (
    NumberType as TwilioNumberType,
)
from eylo.sockets.telephony.vonage.number_contracts import (
    NumberType as VonageNumberType,
)

logger = logging.getLogger(__name__)

_PLIVO_NUMBER_TYPES = {
    NumberType.LOCAL: PlivoNumberType.LOCAL,
    NumberType.TOLL_FREE: PlivoNumberType.TOLL_FREE,
    NumberType.MOBILE: PlivoNumberType.MOBILE,
}
_VONAGE_NUMBER_TYPES = {
    NumberType.LOCAL: VonageNumberType.LANDLINE,
    NumberType.TOLL_FREE: VonageNumberType.TOLL_FREE,
    NumberType.MOBILE: VonageNumberType.MOBILE,
}
_EXOTEL_NUMBER_TYPES = {
    NumberType.LOCAL: ExotelNumberType.LANDLINE,
    NumberType.TOLL_FREE: ExotelNumberType.TOLL_FREE,
    NumberType.MOBILE: ExotelNumberType.MOBILE,
}


class _InlineDurableContext:
    """DB-fenced send for an HTTP request with a stable purchase identity."""

    async def step[Result](
        self,
        *,
        key: str,
        version: int,
        operation: Callable[[], Awaitable[Result]],
    ) -> Result:
        del key, version
        return await operation()


class NumberManagementController:
    """Orchestrates available-number search and purchase across providers."""

    async def search_available_numbers(
        self,
        organization_id: UUID,
        provider_config_id: UUID,
        params: NumberSearchParams,
    ) -> AvailableNumbersResponseSchema:
        """Search using one explicit ready carrier-account config."""
        resolved = await self.resolve_config(organization_id, provider_config_id)
        provider = resolved.provider.value
        credentials = build_telephony_runtime_config(
            resolved.as_provider_config()
        ).settings
        self._require_operation(resolved, TelephonyOperation.SEARCH_NUMBERS)

        if isinstance(credentials, TwilioSettings):
            return await self._search_twilio(credentials, params, provider)
        if isinstance(credentials, PlivoSettings):
            return await self._search_plivo(credentials, params, provider)
        if isinstance(credentials, VonageSettings):
            return await self._search_vonage(credentials, params, provider)
        if isinstance(credentials, ExotelSettings):
            return await self._search_exotel(credentials, params, provider)
        raise HTTPException(501, f"Search not implemented for {provider}")

    async def resolve_config(
        self,
        organization_id: UUID,
        provider_config_id: UUID,
    ) -> ResolvedTelephony:
        async with start_transaction(ro=True) as db:
            return await build_telephony_config_resolver(db).resolve(
                organization_id,
                provider_config_id=provider_config_id,
            )

    async def purchase_number(
        self,
        *,
        organization_id: UUID,
        provider_config_id: UUID,
        request: NumberPurchaseRequest,
        idempotency_key: str,
        durable_context: CommandStepContext | None = None,
    ) -> PhoneNumberApiResponseSchema:
        """Persist intent, execute one charged effect, then project its outcome."""
        phone_number_id = self.purchase_identity(
            organization_id=organization_id,
            idempotency_key=idempotency_key,
        )
        try:
            resolved = await self._prepare_purchase(
                phone_number_id=phone_number_id,
                organization_id=organization_id,
                provider_config_id=provider_config_id,
                request=request,
            )
        except PhoneNumberProvisioningConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        client = self._purchase_client(resolved)
        profile = client.purchase_profile()
        spec = OutboundAttemptSpec(
            identity=OutboundAttemptIdentity(
                organization_id=organization_id,
                owner_kind=OutboundOwnerKind.PHONE_NUMBER,
                owner_id=phone_number_id,
                operation_key=NUMBER_PURCHASE_OPERATION,
            ),
            provider_operation=profile.provider_operation,
            transport_kind=profile.transport_kind,
            destination_origin=profile.destination_origin,
            request_fingerprint=fingerprint_outbound_input(
                {
                    "phone_number_id": str(phone_number_id),
                    "phone_number": request.phone_number,
                    "label": request.label,
                    "country_code": request.country_code,
                    "provider": resolved.provider.value,
                    "provider_config_id": str(resolved.provider_config_id),
                    "provider_config_revision": resolved.provider_config_revision,
                }
            ),
        )

        async def send(authorization: OutboundSendAuthorization) -> OutboundSendOutcome:
            return await client.purchase_number(
                request.phone_number,
                authorization=authorization,
                country=request.country_code,
            )

        try:
            receipt = await execute_outbound_attempt(
                spec=spec,
                context=durable_context or _InlineDurableContext(),
                sender=send,
            )
        except OutboundRetryRequested as error:
            await self._project_purchase(
                phone_number_id, organization_id, error.receipt
            )
            raise HTTPException(
                status_code=503,
                detail="Carrier asked Eylo to retry this purchase.",
                headers={"Retry-After": str(NUMBER_PURCHASE_RETRY_AFTER_SECONDS)},
            ) from error
        except OutboundAttemptConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        phone_number = await self._project_purchase(
            phone_number_id,
            organization_id,
            receipt,
        )
        if receipt.state is OutboundAttemptState.SUCCEEDED:
            return PhoneNumberApiResponseSchema.model_validate(phone_number)
        if receipt.state is OutboundAttemptState.UNKNOWN:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Carrier purchase outcome is unconfirmed; reconciliation is "
                    "required before another purchase attempt."
                ),
            )
        if receipt.state is OutboundAttemptState.TERMINAL:
            raise HTTPException(
                status_code=502,
                detail="Carrier rejected the phone-number purchase.",
            )
        raise HTTPException(
            status_code=409, detail="Phone-number purchase is not active."
        )

    async def _prepare_purchase(
        self,
        *,
        phone_number_id: UUID,
        organization_id: UUID,
        provider_config_id: UUID,
        request: NumberPurchaseRequest,
    ) -> ResolvedTelephony:
        async with start_transaction() as db:
            service = PhoneNumberService(db=db)
            existing = await service.get_by_id_in_organization(
                phone_number_id=phone_number_id,
                organization_id=organization_id,
            )
            resolver = build_telephony_config_resolver(db)
            if existing is None:
                resolved = await resolver.resolve(
                    organization_id,
                    provider_config_id=provider_config_id,
                )
                self._require_operation(
                    resolved,
                    TelephonyOperation.PURCHASE_NUMBER,
                )
                self._require_provider_purchase_input(resolved, request)
                await service.prepare_provisioning(
                    phone_number_id=phone_number_id,
                    organization_id=organization_id,
                    number=request.phone_number,
                    label=request.label,
                    provider=resolved.provider,
                    provider_config_id=resolved.provider_config_id,
                    provider_config_revision=resolved.provider_config_revision,
                )
                return resolved

            if existing.provider_config_id != provider_config_id:
                raise PhoneNumberProvisioningConflict(
                    "Idempotency-Key was already used with a different carrier config."
                )
            resolved = await resolver.resolve_pinned(
                organization_id,
                provider_config_id=existing.provider_config_id,
                revision=existing.provider_config_revision,
            )
            self._require_operation(resolved, TelephonyOperation.PURCHASE_NUMBER)
            self._require_provider_purchase_input(resolved, request)
            await service.prepare_provisioning(
                phone_number_id=phone_number_id,
                organization_id=organization_id,
                number=request.phone_number,
                label=request.label,
                provider=resolved.provider,
                provider_config_id=resolved.provider_config_id,
                provider_config_revision=resolved.provider_config_revision,
            )
            return resolved

    async def _project_purchase(
        self,
        phone_number_id: UUID,
        organization_id: UUID,
        receipt: OutboundExecutionReceipt,
    ) -> PhoneNumberInDb:
        async with start_transaction() as db:
            return await PhoneNumberService(db=db).apply_provisioning_outcome(
                phone_number_id=phone_number_id,
                organization_id=organization_id,
                state=receipt.state,
                provider_reference=receipt.provider_reference,
                failure_code=receipt.failure_code,
            )

    @staticmethod
    def purchase_identity(*, organization_id: UUID, idempotency_key: str) -> UUID:
        normalized_key = idempotency_key.strip()
        if (
            not normalized_key
            or len(normalized_key) > NUMBER_PURCHASE_IDEMPOTENCY_KEY_MAX_LENGTH
        ):
            raise HTTPException(
                status_code=400,
                detail="A bounded Idempotency-Key header is required.",
            )
        return uuid5(
            NAMESPACE_URL,
            f"eylo:phone-number-purchase:v1:{organization_id}:{normalized_key}",
        )

    # --- Twilio ---

    async def _search_twilio(
        self,
        credentials: TwilioSettings,
        params: NumberSearchParams,
        provider: str,
    ) -> AvailableNumbersResponseSchema:
        client = TwilioRestClient(
            account_sid=credentials.account_sid,
            auth_token=credentials.auth_token,
        )
        raw = await client.search_available_numbers(
            country=params.country,
            number_type=TwilioNumberType(params.number_type.value),
            area_code=params.area_code,
            contains=params.contains,
            limit=params.limit,
        )
        numbers = [
            AvailableNumberSchema(
                phone_number=n.phone_number,
                friendly_name=n.friendly_name,
                locality=n.locality,
                region=n.region,
                country=n.iso_country,
                capabilities={
                    k: v for k, v in (n.capabilities or {}).items() if v is True
                },
            )
            for n in raw
        ]
        return AvailableNumbersResponseSchema(
            provider=provider, country=params.country, numbers=numbers
        )

    # --- Plivo ---

    async def _search_plivo(
        self,
        credentials: PlivoSettings,
        params: NumberSearchParams,
        provider: str,
    ) -> AvailableNumbersResponseSchema:
        client = PlivoNumberClient(
            auth_id=credentials.auth_id,
            auth_token=credentials.auth_token,
        )
        raw = await client.search_available_numbers(
            country=params.country,
            number_type=_PLIVO_NUMBER_TYPES[params.number_type],
            pattern=params.area_code or params.contains,
            limit=params.limit,
        )
        numbers = [
            AvailableNumberSchema(
                phone_number=f"+{n.number}",
                friendly_name=n.number,
                locality=n.city,
                region=n.region,
                country=n.country,
                capabilities=n.enabled_capabilities,
            )
            for n in raw
        ]
        return AvailableNumbersResponseSchema(
            provider=provider, country=params.country, numbers=numbers
        )

    # --- Vonage ---

    async def _search_vonage(
        self,
        credentials: VonageSettings,
        params: NumberSearchParams,
        provider: str,
    ) -> AvailableNumbersResponseSchema:
        client = VonageNumberClient(
            api_key=credentials.api_key,
            api_secret=credentials.api_secret,
        )
        raw = await client.search_available_numbers(
            country=params.country,
            number_type=_VONAGE_NUMBER_TYPES[params.number_type],
            pattern=params.area_code or params.contains,
            limit=params.limit,
        )
        numbers = [
            AvailableNumberSchema(
                phone_number=f"+{n.msisdn}",
                friendly_name=n.msisdn,
                locality=None,
                region=None,
                country=n.country,
                capabilities=n.enabled_capabilities,
            )
            for n in raw
        ]
        return AvailableNumbersResponseSchema(
            provider=provider, country=params.country, numbers=numbers
        )

    # --- Exotel ---

    async def _search_exotel(
        self,
        credentials: ExotelSettings,
        params: NumberSearchParams,
        provider: str,
    ) -> AvailableNumbersResponseSchema:
        client = ExotelNumberClient(
            api_key=credentials.api_key,
            api_token=credentials.api_token,
            account_sid=credentials.account_sid,
            subdomain=credentials.api_host,
        )
        raw = await client.search_available_numbers(
            country=params.country,
            number_type=_EXOTEL_NUMBER_TYPES[params.number_type],
            pattern=params.area_code or params.contains,
            limit=params.limit,
        )
        numbers = [
            AvailableNumberSchema(
                phone_number=n.phone_number,
                friendly_name=n.friendly_name,
                locality=None,
                region=n.region,
                country=n.country,
                capabilities=n.enabled_capabilities,
            )
            for n in raw
        ]
        return AvailableNumbersResponseSchema(
            provider=provider,
            country=params.country,
            numbers=numbers,
        )

    @staticmethod
    def _purchase_client(resolved: ResolvedTelephony) -> NumberPurchaseClient:
        credentials = build_telephony_runtime_config(
            resolved.as_provider_config()
        ).settings
        if isinstance(credentials, TwilioSettings):
            return TwilioRestClient(
                account_sid=credentials.account_sid,
                auth_token=credentials.auth_token,
            )
        if isinstance(credentials, PlivoSettings):
            return PlivoNumberClient(
                auth_id=credentials.auth_id,
                auth_token=credentials.auth_token,
            )
        if isinstance(credentials, VonageSettings):
            return VonageNumberClient(
                api_key=credentials.api_key,
                api_secret=credentials.api_secret,
            )
        if isinstance(credentials, ExotelSettings):
            return ExotelNumberClient(
                api_key=credentials.api_key,
                api_token=credentials.api_token,
                account_sid=credentials.account_sid,
                subdomain=credentials.api_host,
            )
        raise HTTPException(
            status_code=501,
            detail=f"Purchase not implemented for {resolved.provider.value}.",
        )

    @staticmethod
    def _require_provider_purchase_input(
        resolved: ResolvedTelephony,
        request: NumberPurchaseRequest,
    ) -> None:
        if (
            resolved.provider is TelephonyProviderType.VONAGE
            and request.country_code is None
        ):
            raise HTTPException(
                status_code=422,
                detail="country_code is required for Vonage number purchase.",
            )

    @staticmethod
    def _require_operation(
        resolved: ResolvedTelephony,
        operation: TelephonyOperation,
    ) -> None:
        if supports_telephony_operation(resolved.provider, operation):
            return
        raise HTTPException(
            status_code=501,
            detail={
                "code": "UNSUPPORTED",
                "operation": operation.value,
                "provider": resolved.provider.value,
            },
        )
