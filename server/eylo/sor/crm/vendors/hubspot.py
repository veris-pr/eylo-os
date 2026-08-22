"""HubSpot CRM adapter using the pinned 2026-03 API surface."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.crm.contracts import CrmActivity, CrmCompany, CrmContact, CrmDeal
from eylo.sor.runtime.http import (
    SorHttpTransport,
    SorJsonHttpClient,
    SorJsonResponse,
)
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterContext,
    SorCapabilityUnavailable,
    SorChangeStrategy,
    SorCommandRequest,
    SorCommandResult,
    SorConnectionVerification,
    SorDeletedRecord,
    SorDiscoveredField,
    SorDiscoveredObject,
    SorDiscoveredSchema,
    SorExternalRecord,
    SorExternalRecordNotFound,
    SorOAuthSpec,
    SorProfile,
    SorRecordPage,
    SorVendorOperationError,
    SorVendorStreamSpec,
    SorWebhookSignal,
    SorWebhookSubscription,
)

HUBSPOT_ORIGIN = "https://api.hubapi.com"
HUBSPOT_API_VERSION = "2026-03"

CONTACTS_READ = "crm.objects.contacts.read"
CONTACTS_WRITE = "crm.objects.contacts.write"
COMPANIES_READ = "crm.objects.companies.read"
COMPANIES_WRITE = "crm.objects.companies.write"
DEALS_READ = "crm.objects.deals.read"
DEALS_WRITE = "crm.objects.deals.write"

_STREAM_ENTITY = {
    "contacts": "contact",
    "companies": "company",
    "deals": "deal",
}
_RELATIONSHIP_TARGETS = {
    "deals": {"contact": "contacts", "company": "companies"},
}
_TOOL_STREAM = {
    "crm_create_contact": ("contacts", True),
    "crm_update_contact": ("contacts", False),
    "crm_create_company": ("companies", True),
    "crm_update_company": ("companies", False),
    "crm_create_deal": ("deals", True),
    "crm_update_deal": ("deals", False),
    "crm_move_deal": ("deals", False),
}
_WRITE_SCOPES = {
    "crm_create_contact": (CONTACTS_WRITE,),
    "crm_update_contact": (CONTACTS_WRITE,),
    "crm_create_company": (COMPANIES_WRITE,),
    "crm_update_company": (COMPANIES_WRITE,),
    "crm_create_deal": (DEALS_WRITE,),
    "crm_update_deal": (DEALS_WRITE,),
    "crm_move_deal": (DEALS_WRITE,),
}
_READ_TOOLS = frozenset(
    {
        "crm_find_customer",
        "crm_get_customer",
        "crm_list_deals",
        "crm_get_deal",
        "crm_describe_customer_fields",
        "crm_describe_deal_fields",
    }
)
_TOOL_STREAMS = {
    "crm_find_customer": frozenset({"contacts", "companies"}),
    "crm_get_customer": frozenset({"contacts", "companies"}),
    "crm_list_deals": frozenset({"deals"}),
    "crm_get_deal": frozenset({"deals"}),
    "crm_describe_customer_fields": frozenset({"contacts", "companies"}),
    "crm_describe_deal_fields": frozenset({"deals"}),
    **{
        tool_name: frozenset({stream_key})
        for tool_name, (stream_key, _creates) in _TOOL_STREAM.items()
    },
}

HUBSPOT_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.CRM,
    vendor_key="hubspot",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=(
        SorVendorStreamSpec(
            key="contacts",
            label="Contacts",
            description="People and their selected standard or custom properties.",
            canonical_entity="contact",
            change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
        ),
        SorVendorStreamSpec(
            key="companies",
            label="Companies",
            description="Companies and their selected standard or custom properties.",
            canonical_entity="company",
            change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
        ),
        SorVendorStreamSpec(
            key="deals",
            label="Deals",
            description="Deals and their selected standard or custom properties.",
            canonical_entity="deal",
            change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
            depends_on=frozenset({"contacts", "companies"}),
            relationship_targets=_RELATIONSHIP_TARGETS["deals"],
        ),
    ),
    readable_entities=frozenset(_STREAM_ENTITY.values()),
    writable_entities=frozenset(_STREAM_ENTITY.values()),
    readable_tools=_READ_TOOLS,
    writable_tools=frozenset(_TOOL_STREAM),
    change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
    required_scopes={
        "contacts": (CONTACTS_READ,),
        "companies": (COMPANIES_READ,),
        "deals": (DEALS_READ,),
    },
    tool_required_scopes=_WRITE_SCOPES,
    tool_streams=_TOOL_STREAMS,
    mutation_result_streams={
        tool_name: stream_key
        for tool_name, (stream_key, _creates) in _TOOL_STREAM.items()
    },
    oauth=SorOAuthSpec(
        authorization_url="https://app.hubspot.com/oauth/authorize",
        token_url="https://api.hubspot.com/oauth/2026-03/token",
        base_scopes=("oauth",),
    ),
    fixed_origin=HUBSPOT_ORIGIN,
    supports_custom_fields=True,
)


class HubSpotCrmAdapter:
    """Translate mapped HubSpot properties into the canonical CRM profile."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "hubspot":
            raise ValueError("HubSpot adapter requires the hubspot vendor key.")
        if context.auth_kind is not ConnectionAuthKind.OAUTH2:
            raise ValueError("HubSpot SOR currently requires OAuth 2.0.")
        token = _credential(context.credentials, "access_token")
        self._context = context
        self._client = SorJsonHttpClient(
            origin=HUBSPOT_ORIGIN,
            authorization=f"Bearer {token}",
            transport=transport,
            response_body_limit=8_388_608,
        )

    async def verify_connection(self) -> SorConnectionVerification:
        response = await self._client.request(
            f"/account-info/{HUBSPOT_API_VERSION}/details"
        )
        data = _object(_expect(response, operation="verify HubSpot account"))
        portal_id = _required_id(data.get("portalId"), field="HubSpot portal ID")
        account_type = _optional_string(data.get("accountType"))
        display_name = f"HubSpot {account_type}" if account_type else "HubSpot account"
        return SorConnectionVerification(
            account_external_id=portal_id,
            account_display_name=display_name,
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=HUBSPOT_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        objects: list[SorDiscoveredObject] = []
        for stream_key in self._context.selected_objects:
            _require_stream(stream_key, selected=self._context.selected_objects)
            response = await self._client.request(
                f"/crm/properties/{HUBSPOT_API_VERSION}/{stream_key}"
            )
            payload = _object(_expect(response, operation="discover HubSpot schema"))
            rows = _object_list(payload.get("results"), field="HubSpot properties")
            fields = tuple(
                sorted(
                    (_discovered_field(row) for row in rows if not row.get("archived")),
                    key=lambda field: (field.group or "", field.label, field.key),
                )
            )
            if not fields:
                raise SorVendorOperationError(
                    "vendor_schema_empty",
                    f"HubSpot returned no fields for {stream_key}.",
                    retryable=False,
                )
            objects.append(
                SorDiscoveredObject(
                    key=stream_key,
                    label=stream_key.replace("_", " ").title(),
                    fields=fields,
                )
            )
        return SorDiscoveredSchema(
            objects=tuple(objects),
            vendor_api_version=HUBSPOT_API_VERSION,
        )

    async def bootstrap_stream(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        return await self._read_page(stream_key=stream_key, cursor=cursor, limit=limit)

    async def pull_changes(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        return await self._read_page(stream_key=stream_key, cursor=cursor, limit=limit)

    async def fetch_record(
        self,
        *,
        vendor_object_key: str,
        external_id: str,
    ) -> SorExternalRecord:
        _require_stream(vendor_object_key, selected=self._context.selected_objects)
        record_id = _required_id(external_id, field="HubSpot record ID")
        fields = self._selected_fields(vendor_object_key)
        response = await self._client.request(
            f"/crm/objects/{HUBSPOT_API_VERSION}/{vendor_object_key}/{record_id}",
            query={"properties": ",".join(fields), "archived": False},
        )
        if response.status_code == 404:
            raise SorExternalRecordNotFound(
                vendor_object_key=vendor_object_key,
                external_id=record_id,
            )
        data = _object(_expect(response, operation="read HubSpot record"))
        return _external_record(vendor_object_key, data, selected_fields=fields)

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "HubSpot deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "HubSpot webhooks are not available in this adapter revision."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "HubSpot webhooks are not available in this adapter revision."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "HubSpot webhooks are not available in this adapter revision."
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        raise SorCapabilityUnavailable(
            "HubSpot webhooks are not available in this adapter revision."
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        raise SorCapabilityUnavailable(
            "HubSpot webhooks are not available in this adapter revision."
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        try:
            stream_key, creates_record = _TOOL_STREAM[command.tool_name]
        except KeyError as error:
            raise SorVendorOperationError(
                "vendor_tool_unsupported",
                "This HubSpot adapter does not execute the requested CRM action.",
                retryable=False,
            ) from error
        _require_stream(stream_key, selected=self._context.selected_objects)
        if creates_record and command.target_external_id is not None:
            raise SorVendorOperationError(
                "vendor_command_invalid",
                "A CRM create action cannot target an existing record.",
                retryable=False,
            )
        if not creates_record and command.target_external_id is None:
            raise SorVendorOperationError(
                "vendor_command_invalid",
                "A CRM update action requires an existing record.",
                retryable=False,
            )
        if command.tool_name == "crm_move_deal" and set(command.payload) != {
            "stage_external_id"
        }:
            raise SorVendorOperationError(
                "vendor_command_invalid",
                "Moving a deal requires only stage_external_id.",
                retryable=False,
            )
        properties = self._write_properties(stream_key, command.payload)
        path = f"/crm/objects/{HUBSPOT_API_VERSION}/{stream_key}"
        method = "POST"
        if not creates_record:
            record_id = _required_id(
                command.target_external_id,
                field="HubSpot record ID",
            )
            path = f"{path}/{record_id}"
            method = "PATCH"
        try:
            response = await self._client.request(
                path,
                method=method,
                payload={"properties": properties},
                idempotency_key=command.idempotency_key,
            )
            data = _object(_expect_mutation(response, creates_record=creates_record))
        except SorVendorOperationError as error:
            if creates_record and error.code in {
                "vendor_timeout",
                "vendor_transport_failed",
                "vendor_server_failed",
            }:
                raise SorVendorOperationError(
                    "vendor_mutation_outcome_unknown",
                    "HubSpot may have created the record; reconcile before retrying.",
                    retryable=False,
                ) from error
            raise
        external_id = _required_id(data.get("id"), field="HubSpot record ID")
        request_ids = response.header_values("x-hubspot-correlation-id")
        return SorCommandResult(
            vendor_object_key=stream_key,
            external_id=external_id,
            external_request_id=request_ids[0] if request_ids else None,
            source_revision=_optional_string(data.get("updatedAt")),
            source_url=_safe_source_url(data.get("url")),
            response={"status": "accepted"},
        )

    def normalize_contact(self, record: SorExternalRecord) -> CrmContact:
        values = record.payload
        name = _optional_string(values.get("name"))
        if name is None:
            name = " ".join(
                value
                for value in (
                    _optional_string(values.get("first_name")),
                    _optional_string(values.get("last_name")),
                )
                if value
            ) or None
        return CrmContact(
            external_id=record.external_id,
            name=name,
            primary_email=_optional_string(values.get("primary_email")),
            primary_phone=_optional_string(values.get("primary_phone")),
            job_title=_optional_string(values.get("job_title")),
            lifecycle_stage=_optional_string(values.get("lifecycle_stage")),
            owner_external_id=_optional_string(values.get("owner_external_id")),
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
        )

    def normalize_company(self, record: SorExternalRecord) -> CrmCompany:
        values = record.payload
        return CrmCompany(
            external_id=record.external_id,
            name=_optional_string(values.get("name")),
            domain=_optional_string(values.get("domain")),
            industry=_optional_string(values.get("industry")),
            owner_external_id=_optional_string(values.get("owner_external_id")),
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
        )

    def normalize_deal(self, record: SorExternalRecord) -> CrmDeal:
        values = record.payload
        return CrmDeal(
            external_id=record.external_id,
            title=_required_string(values.get("title"), field="CRM deal title"),
            pipeline_external_id=_optional_string(
                values.get("pipeline_external_id")
            ),
            stage_external_id=_optional_string(values.get("stage_external_id")),
            native_stage=_optional_string(values.get("native_stage")),
            normalized_state=_optional_string(values.get("normalized_state")),
            amount=_optional_decimal(values.get("amount")),
            currency=_optional_string(values.get("currency")),
            probability=_optional_decimal(values.get("probability")),
            expected_close_date=_optional_date(values.get("expected_close_date")),
            owner_external_id=_optional_string(values.get("owner_external_id")),
            contact_external_ids=_string_tuple(values.get("contact_external_ids")),
            company_external_ids=_string_tuple(values.get("company_external_ids")),
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
        )

    def normalize_activity(self, record: SorExternalRecord) -> CrmActivity:
        raise SorCapabilityUnavailable(
            "HubSpot activities are not available in this adapter revision."
        )

    async def close(self) -> None:
        return None

    async def _read_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        _require_stream(stream_key, selected=self._context.selected_objects)
        if limit <= 0:
            raise SorVendorOperationError(
                "vendor_page_invalid",
                "HubSpot page limit must be positive.",
                retryable=False,
            )
        fields = self._selected_fields(stream_key)
        query: dict[str, object] = {
            "limit": min(limit, 100),
            "properties": ",".join(fields),
            "archived": False,
        }
        if cursor is not None:
            query["after"] = cursor
        response = await self._client.request(
            f"/crm/objects/{HUBSPOT_API_VERSION}/{stream_key}",
            query=query,
        )
        data = _object(_expect(response, operation="read HubSpot records"))
        rows = _object_list(data.get("results"), field="HubSpot records")
        next_cursor = _next_cursor(data.get("paging"))
        return SorRecordPage(
            records=tuple(
                _external_record(stream_key, row, selected_fields=fields)
                for row in rows
            ),
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )

    def _selected_fields(self, stream_key: str) -> tuple[str, ...]:
        fields = tuple(
            sorted(
                {
                    field.vendor_field_key
                    for field in self._context.fields
                    if field.vendor_object_key == stream_key
                }
            )
        )
        if not fields:
            raise SorVendorOperationError(
                "source_mapping_empty",
                f"The active mapping selects no {stream_key} fields.",
                retryable=False,
            )
        return fields

    def _write_properties(
        self,
        stream_key: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        writable = {
            field.agent_key: field.vendor_field_key
            for field in self._context.fields
            if field.vendor_object_key == stream_key and field.writable
        }
        if not payload:
            raise SorVendorOperationError(
                "vendor_command_invalid",
                "A CRM mutation requires at least one mapped field.",
                retryable=False,
            )
        unknown = set(payload) - set(writable)
        if unknown:
            raise SorVendorOperationError(
                "vendor_field_not_writable",
                "The CRM mutation contains fields absent from the writable mapping.",
                retryable=False,
            )
        return {writable[key]: value for key, value in payload.items()}


def create_hubspot_adapter(context: SorAdapterContext) -> HubSpotCrmAdapter:
    """Construct the production HubSpot adapter for the explicit registry."""
    return HubSpotCrmAdapter(context)


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 16_384:
        raise SorVendorOperationError(
            "vendor_credentials_invalid",
            "HubSpot OAuth credentials are unavailable.",
            retryable=False,
            requires_reauthorization=True,
        )
    return value.strip()


def _require_stream(stream_key: str, *, selected: tuple[str, ...]) -> str:
    if stream_key not in _STREAM_ENTITY or stream_key not in selected:
        raise SorVendorOperationError(
            "vendor_stream_unavailable",
            "The HubSpot stream is not selected for this source.",
            retryable=False,
        )
    return stream_key


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.ok:
        return response.data
    if response.status_code == 401:
        raise SorVendorOperationError(
            "vendor_access_token_expired",
            "HubSpot rejected the current access token.",
            retryable=True,
            requires_reauthorization=True,
            refreshable_authorization=True,
        )
    if response.status_code == 403:
        raise SorVendorOperationError(
            "vendor_reauthorization_required",
            "HubSpot authorization no longer permits this operation.",
            retryable=False,
            requires_reauthorization=True,
        )
    if response.status_code == 429:
        raise SorVendorOperationError(
            "vendor_rate_limited",
            "HubSpot rate-limited the operation.",
            retryable=True,
        )
    if response.status_code >= 500:
        raise SorVendorOperationError(
            "vendor_server_failed",
            f"HubSpot could not {operation}.",
            retryable=True,
        )
    raise SorVendorOperationError(
        "vendor_request_rejected",
        f"HubSpot rejected the request to {operation}.",
        retryable=False,
    )


def _expect_mutation(response: SorJsonResponse, *, creates_record: bool) -> object:
    if response.status_code in {200, 201}:
        return response.data
    if response.status_code in {409, 412}:
        raise SorVendorOperationError(
            "vendor_conflict",
            "HubSpot rejected conflicting record data.",
            retryable=False,
        )
    try:
        return _expect(response, operation="apply the CRM action")
    except SorVendorOperationError as error:
        if creates_record and error.code == "vendor_server_failed":
            raise SorVendorOperationError(
                "vendor_server_failed",
                str(error),
                retryable=True,
            ) from error
        raise


def _discovered_field(row: dict[str, Any]) -> SorDiscoveredField:
    key = _required_string(row.get("name"), field="HubSpot property name")
    metadata = row.get("modificationMetadata")
    read_only = isinstance(metadata, dict) and metadata.get("readOnlyValue") is True
    options = row.get("options")
    choices = tuple(
        value
        for option in options if isinstance(options, list) and isinstance(option, dict)
        if (value := _optional_string(option.get("value"))) is not None
        and option.get("hidden") is not True
    ) if isinstance(options, list) else ()
    return SorDiscoveredField(
        key=key,
        label=_optional_string(row.get("label")) or key,
        data_type=_field_type(row),
        nullable=True,
        writable=not read_only and row.get("calculated") is not True,
        choices=choices,
        description=_optional_string(row.get("description")),
        group=_optional_string(row.get("groupName")),
    )


def _field_type(row: Mapping[str, object]) -> str:
    field_type = _optional_string(row.get("fieldType"))
    if field_type in {"checkbox", "multi_checkbox"}:
        return "string_array"
    return {
        "bool": "boolean",
        "date": "date",
        "datetime": "timestamp",
        "enumeration": "enum",
        "number": "decimal",
        "phone_number": "text",
        "string": "text",
    }.get(_optional_string(row.get("type")) or "", "bounded_json")


def _external_record(
    stream_key: str,
    row: Mapping[str, object],
    *,
    selected_fields: tuple[str, ...],
) -> SorExternalRecord:
    external_id = _required_id(row.get("id"), field="HubSpot record ID")
    if row.get("archived") is True:
        raise SorExternalRecordNotFound(
            vendor_object_key=stream_key,
            external_id=external_id,
            reason="Archived in HubSpot",
            deleted_at=_optional_datetime(row.get("archivedAt")),
        )
    properties = row.get("properties")
    if not isinstance(properties, Mapping) or not all(
        isinstance(key, str) for key in properties
    ):
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "HubSpot record properties are invalid.",
            retryable=False,
        )
    selected = {key: properties.get(key) for key in selected_fields}
    updated_at = _optional_datetime(row.get("updatedAt"))
    return SorExternalRecord(
        vendor_object_key=stream_key,
        external_id=external_id,
        payload=selected,
        source_created_at=_optional_datetime(row.get("createdAt")),
        source_updated_at=updated_at,
        source_revision=updated_at.isoformat() if updated_at else None,
        source_url=_safe_source_url(row.get("url")),
    )


def _next_cursor(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    next_page = value.get("next")
    if not isinstance(next_page, Mapping):
        return None
    return _optional_string(next_page.get("after"))


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "HubSpot returned an invalid object.",
            retryable=False,
        )
    return value


def _object_list(value: object, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 20_000:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            f"{field} have an invalid shape.",
            retryable=False,
        )
    return [_object(item) for item in value]


def _required_id(value: object, *, field: str) -> str:
    normalized = _required_string(value, field=field)
    if len(normalized) > 320 or any(character in normalized for character in "/?#"):
        raise SorVendorOperationError(
            "vendor_response_invalid",
            f"{field} is invalid.",
            retryable=False,
        )
    return normalized


def _required_string(value: object, *, field: str) -> str:
    normalized = _optional_string(value)
    if normalized is None:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            f"{field} is unavailable.",
            retryable=False,
        )
    return normalized


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    normalized = str(value).strip()
    return normalized[:1_000_000] if normalized else None


def _optional_datetime(value: object) -> datetime | None:
    normalized = _optional_string(value)
    if normalized is None:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as error:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "HubSpot returned an invalid timestamp.",
            retryable=False,
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "HubSpot returned a timestamp without a timezone.",
            retryable=False,
        )
    return parsed.astimezone(timezone.utc)


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "HubSpot returned an invalid decimal value.",
            retryable=False,
        ) from error


def _optional_date(value: object) -> date | None:
    normalized = _optional_string(value)
    if normalized is None:
        return None
    try:
        return date.fromisoformat(normalized[:10])
    except ValueError as error:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "HubSpot returned an invalid date value.",
            retryable=False,
        ) from error


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "HubSpot returned an invalid relationship list.",
            retryable=False,
        )
    values = tuple(
        normalized
        for item in value
        if (normalized := _optional_string(item)) is not None
    )
    if len(values) > 10_000:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "HubSpot returned too many relationships.",
            retryable=False,
        )
    return values


def _safe_source_url(value: object) -> str | None:
    normalized = _optional_string(value)
    if normalized is None:
        return None
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or (host != "hubspot.com" and not host.endswith(".hubspot.com"))
    ):
        return None
    return normalized


__all__ = [
    "HUBSPOT_API_VERSION",
    "HUBSPOT_MANIFEST",
    "HUBSPOT_ORIGIN",
    "HubSpotCrmAdapter",
    "create_hubspot_adapter",
]
