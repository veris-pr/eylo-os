"""Salesforce CRM adapter using a pinned REST API and keyset checkpoints."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import format_datetime
from typing import Any
from urllib.parse import urlsplit

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.crm.contracts import CrmActivity, CrmCompany, CrmContact, CrmDeal
from eylo.sor.runtime.http import SorHttpTransport, SorJsonHttpClient, SorJsonResponse
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

SALESFORCE_API_VERSION = "67.0"
SALESFORCE_API_PREFIX = f"/services/data/v{SALESFORCE_API_VERSION}"

API_SCOPE = "api"
REFRESH_SCOPE = "refresh_token"

_STREAM_ENTITY = {
    "Contact": "contact",
    "Account": "company",
    "Opportunity": "deal",
    "Task": "activity",
}
_RELATIONSHIP_TARGETS = {
    "Opportunity": {"contact": "Contact", "company": "Account"},
}
_TOOL_STREAM = {
    "crm_create_contact": ("Contact", True),
    "crm_update_contact": ("Contact", False),
    "crm_create_company": ("Account", True),
    "crm_update_company": ("Account", False),
    "crm_create_deal": ("Opportunity", True),
    "crm_update_deal": ("Opportunity", False),
    "crm_move_deal": ("Opportunity", False),
    "crm_log_activity": ("Task", True),
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
    "crm_find_customer": frozenset({"Contact", "Account"}),
    "crm_get_customer": frozenset({"Contact", "Account"}),
    "crm_list_deals": frozenset({"Opportunity"}),
    "crm_get_deal": frozenset({"Opportunity"}),
    "crm_describe_customer_fields": frozenset({"Contact", "Account"}),
    "crm_describe_deal_fields": frozenset({"Opportunity"}),
    **{
        tool_name: frozenset({stream_key})
        for tool_name, (stream_key, _creates) in _TOOL_STREAM.items()
    },
}
_SYSTEM_FIELDS = ("Id", "CreatedDate", "LastModifiedDate", "SystemModstamp")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,255}$")
_RECORD_ID = re.compile(r"^[A-Za-z0-9]{15,18}$")
_CUSTOM_OBJECT_LIMIT = 50


SALESFORCE_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.CRM,
    vendor_key="salesforce",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=(
        SorVendorStreamSpec(
            key="Contact",
            label="Contacts",
            description="Salesforce contacts and selected custom fields.",
            canonical_entity="contact",
            change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
        ),
        SorVendorStreamSpec(
            key="Account",
            label="Accounts",
            description="Salesforce accounts and selected custom fields.",
            canonical_entity="company",
            change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
        ),
        SorVendorStreamSpec(
            key="Opportunity",
            label="Opportunities",
            description="Salesforce opportunities and pipeline stages.",
            canonical_entity="deal",
            change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
            depends_on=frozenset({"Contact", "Account"}),
            relationship_targets=_RELATIONSHIP_TARGETS["Opportunity"],
        ),
        SorVendorStreamSpec(
            key="Task",
            label="Tasks",
            description="Salesforce CRM tasks exposed as canonical activities.",
            canonical_entity="activity",
            change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
        ),
    ),
    readable_entities=frozenset(_STREAM_ENTITY.values()),
    writable_entities=frozenset(_STREAM_ENTITY.values()),
    readable_tools=_READ_TOOLS,
    writable_tools=frozenset(_TOOL_STREAM),
    change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
    required_scopes={key: (API_SCOPE,) for key in _STREAM_ENTITY},
    custom_object_required_scopes=(API_SCOPE,),
    custom_object_change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
    tool_required_scopes={key: (API_SCOPE,) for key in _TOOL_STREAM},
    tool_streams=_TOOL_STREAMS,
    mutation_result_streams={
        tool_name: stream_key
        for tool_name, (stream_key, _creates) in _TOOL_STREAM.items()
    },
    oauth=SorOAuthSpec(
        authorization_url=(
            "https://login.salesforce.com/services/oauth2/authorize"
        ),
        token_url="https://login.salesforce.com/services/oauth2/token",
        base_scopes=(REFRESH_SCOPE,),
        pkce=True,
        instance_origin_field="instance_url",
        instance_host_suffixes=("salesforce.com",),
    ),
    requires_instance_origin=True,
    supports_custom_fields=True,
    supports_custom_objects=True,
    supports_conditional_writes=True,
)


class SalesforceCrmAdapter:
    """Translate selected Salesforce sObjects into the canonical CRM profile."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "salesforce":
            raise ValueError("Salesforce adapter requires the salesforce vendor key.")
        if context.auth_kind is not ConnectionAuthKind.OAUTH2:
            raise ValueError("Salesforce SOR requires OAuth 2.0.")
        origin = _salesforce_origin(context.instance_origin)
        token = _credential(context.credentials, "access_token")
        self._context = context
        self._origin = origin
        self._client = SorJsonHttpClient(
            origin=origin,
            authorization=f"Bearer {token}",
            transport=transport,
            response_body_limit=8_388_608,
        )

    async def verify_connection(self) -> SorConnectionVerification:
        response = await self._client.request(f"{SALESFORCE_API_PREFIX}/sobjects/")
        data = _object(_expect(response, operation="verify Salesforce data access"))
        rows = _object_list(data.get("sobjects"), field="Salesforce sObjects")
        available = {
            _optional_string(row.get("name"))
            for row in rows
            if row.get("queryable") is True
        }
        missing = sorted(set(self._context.selected_objects) - available)
        if missing:
            raise SorVendorOperationError(
                "vendor_stream_unavailable",
                "Salesforce does not permit the selected CRM objects.",
                retryable=False,
            )
        return SorConnectionVerification(
            account_display_name="Salesforce organization",
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=SALESFORCE_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        catalog_response = await self._client.request(
            f"{SALESFORCE_API_PREFIX}/sobjects/"
        )
        catalog = _object(
            _expect(catalog_response, operation="list Salesforce objects")
        )
        rows = _object_list(catalog.get("sobjects"), field="Salesforce sObjects")
        custom_objects = _custom_object_keys(rows)
        object_keys = tuple(
            dict.fromkeys(
                (
                    *(
                        key
                        for key in self._context.selected_objects
                        if key in _STREAM_ENTITY
                    ),
                    *custom_objects,
                )
            )
        )
        objects = [
            await self._describe_object(
                stream_key,
                custom=stream_key in custom_objects,
            )
            for stream_key in object_keys
        ]
        return SorDiscoveredSchema(
            objects=tuple(
                sorted(objects, key=lambda item: (item.custom, item.label, item.key))
            ),
            vendor_api_version=SALESFORCE_API_VERSION,
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
        stream_key = _require_stream(
            vendor_object_key,
            selected=self._context.selected_objects,
        )
        record_id = _required_record_id(external_id)
        selected_fields = self._selected_fields(stream_key)
        response = await self._client.request(
            f"{SALESFORCE_API_PREFIX}/sobjects/{stream_key}/{record_id}",
            query={"fields": ",".join(_query_fields(selected_fields))},
        )
        if response.status_code in {404, 410}:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        row = _object(_expect(response, operation="read Salesforce record"))
        return self._external_record(stream_key, row, selected_fields=selected_fields)

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "Salesforce deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Salesforce CDC is not available in this adapter revision."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Salesforce CDC is not available in this adapter revision."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "Salesforce CDC is not available in this adapter revision."
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        raise SorCapabilityUnavailable(
            "Salesforce CDC is not available in this adapter revision."
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        raise SorCapabilityUnavailable(
            "Salesforce CDC is not available in this adapter revision."
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        try:
            stream_key, creates_record = _TOOL_STREAM[command.tool_name]
        except KeyError as error:
            raise SorVendorOperationError(
                "vendor_tool_unsupported",
                "This Salesforce adapter does not execute the requested CRM action.",
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
        values = self._write_fields(stream_key, command.payload)
        path = f"{SALESFORCE_API_PREFIX}/sobjects/{stream_key}"
        method = "POST"
        record_id: str | None = None
        if not creates_record:
            record_id = _required_record_id(command.target_external_id)
            path = f"{path}/{record_id}"
            method = "PATCH"
        try:
            response = await self._client.request(
                path,
                method=method,
                payload=values,
                idempotency_key=command.idempotency_key,
                if_unmodified_since=(
                    None if creates_record else command.expected_source_revision
                ),
            )
            _expect_mutation(response, creates_record=creates_record)
        except SorVendorOperationError as error:
            if creates_record and error.code in {
                "vendor_timeout",
                "vendor_transport_failed",
                "vendor_server_failed",
            }:
                raise SorVendorOperationError(
                    "vendor_mutation_outcome_unknown",
                    "Salesforce may have created the record; reconcile before retrying.",
                    retryable=False,
                ) from error
            raise
        if creates_record:
            body = _object(response.data)
            record_id = _required_record_id(body.get("id"))
        assert record_id is not None
        request_ids = response.header_values("x-request-id")
        return SorCommandResult(
            vendor_object_key=stream_key,
            external_id=record_id,
            external_request_id=request_ids[0] if request_ids else None,
            source_url=self._record_url(stream_key, record_id),
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
        values = record.payload
        return CrmActivity(
            external_id=record.external_id,
            kind=_optional_string(values.get("kind")) or "task",
            subject=_optional_string(values.get("subject")),
            normalized_text=_optional_string(values.get("normalized_text")),
            occurred_at=_required_datetime(
                values.get("occurred_at"),
                field="CRM activity occurred_at",
            ),
            actor_external_id=_optional_string(values.get("actor_external_id")),
            participant_external_ids=_string_tuple(
                values.get("participant_external_ids")
            ),
            related_external_ids=_string_tuple(
                values.get("related_external_ids")
            ),
            source_url=record.source_url,
        )

    async def close(self) -> None:
        return None

    async def _describe_object(
        self,
        stream_key: str,
        *,
        custom: bool,
    ) -> SorDiscoveredObject:
        """Describe one catalog-proven object without widening runtime selection."""
        object_key = _identifier(stream_key)
        response = await self._client.request(
            f"{SALESFORCE_API_PREFIX}/sobjects/{object_key}/describe/"
        )
        payload = _object(_expect(response, operation="describe Salesforce object"))
        fields = tuple(
            sorted(
                (
                    _discovered_field(row)
                    for row in _object_list(
                        payload.get("fields"),
                        field="Salesforce fields",
                    )
                ),
                key=lambda field: (field.group or "", field.label, field.key),
            )
        )
        if not fields:
            raise SorVendorOperationError(
                "vendor_schema_empty",
                f"Salesforce returned no fields for {object_key}.",
                retryable=False,
            )
        return SorDiscoveredObject(
            key=object_key,
            label=(
                _optional_string(payload.get("labelPlural"))
                or _optional_string(payload.get("label"))
                or object_key
            ),
            fields=fields,
            custom=custom,
        )

    async def _read_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        stream_key = _require_stream(
            stream_key,
            selected=self._context.selected_objects,
        )
        if limit <= 0:
            raise SorVendorOperationError(
                "vendor_page_invalid",
                "Salesforce page limit must be positive.",
                retryable=False,
            )
        page_limit = min(limit, 200)
        selected_fields = self._selected_fields(stream_key)
        checkpoint = _decode_cursor(cursor)
        soql = _build_query(
            stream_key=stream_key,
            fields=_query_fields(selected_fields),
            checkpoint=checkpoint,
            limit=page_limit,
        )
        response = await self._client.request(
            f"{SALESFORCE_API_PREFIX}/query/",
            query={"q": soql},
        )
        data = _object(_expect(response, operation="query Salesforce records"))
        rows = _object_list(data.get("records"), field="Salesforce records")
        if len(rows) > page_limit:
            raise SorVendorOperationError(
                "vendor_response_invalid",
                "Salesforce returned more rows than the requested page limit.",
                retryable=False,
            )
        next_cursor = cursor
        if rows:
            next_cursor = _encode_cursor(rows[-1])
        has_more = len(rows) == page_limit
        return SorRecordPage(
            records=tuple(
                self._external_record(
                    stream_key,
                    row,
                    selected_fields=selected_fields,
                )
                for row in rows
            ),
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def _selected_fields(self, stream_key: str) -> tuple[str, ...]:
        fields = tuple(
            sorted(
                {
                    _identifier(field.vendor_field_key)
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

    def _write_fields(
        self,
        stream_key: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        writable = {
            field.agent_key: _identifier(field.vendor_field_key)
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
        values: dict[str, object] = {}
        for agent_key, value in payload.items():
            vendor_key = writable[agent_key]
            values[vendor_key] = _to_salesforce_value(
                stream_key=stream_key,
                vendor_field_key=vendor_key,
                value=value,
            )
        return values

    def _external_record(
        self,
        stream_key: str,
        row: Mapping[str, object],
        *,
        selected_fields: tuple[str, ...],
    ) -> SorExternalRecord:
        record_id = _required_record_id(row.get("Id"))
        updated_at = _optional_datetime(row.get("LastModifiedDate"))
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=record_id,
            payload={
                key: _from_salesforce_value(
                    stream_key=stream_key,
                    vendor_field_key=key,
                    value=row.get(key),
                )
                for key in selected_fields
            },
            source_created_at=_optional_datetime(row.get("CreatedDate")),
            source_updated_at=updated_at,
            source_revision=(
                format_datetime(updated_at, usegmt=True) if updated_at else None
            ),
            source_url=self._record_url(stream_key, record_id),
        )

    def _record_url(self, stream_key: str, record_id: str) -> str:
        return f"{self._origin}/lightning/r/{stream_key}/{record_id}/view"


def create_salesforce_adapter(context: SorAdapterContext) -> SalesforceCrmAdapter:
    """Construct the production Salesforce adapter for the explicit registry."""
    return SalesforceCrmAdapter(context)


def _salesforce_origin(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SorVendorOperationError(
            "vendor_origin_invalid",
            "Salesforce instance origin is unavailable.",
            retryable=False,
            requires_reauthorization=True,
        )
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as error:
        raise SorVendorOperationError(
            "vendor_origin_invalid",
            "Salesforce instance origin is invalid.",
            retryable=False,
            requires_reauthorization=True,
        ) from error
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and port != 443)
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not host.endswith(".salesforce.com")
    ):
        raise SorVendorOperationError(
            "vendor_origin_invalid",
            "Salesforce instance origin must be an HTTPS salesforce.com origin.",
            retryable=False,
            requires_reauthorization=True,
        )
    return f"https://{host}"


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 16_384:
        raise SorVendorOperationError(
            "vendor_credentials_invalid",
            "Salesforce OAuth credentials are unavailable.",
            retryable=False,
            requires_reauthorization=True,
        )
    return value.strip()


def _require_stream(stream_key: str, *, selected: tuple[str, ...]) -> str:
    object_key = _identifier(stream_key)
    if object_key not in selected:
        raise SorVendorOperationError(
            "vendor_stream_unavailable",
            "The Salesforce stream is not selected for this source.",
            retryable=False,
        )
    return object_key


def _custom_object_keys(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    keys = tuple(
        sorted(
            _identifier(name)
            for row in rows
            if row.get("custom") is True
            and row.get("queryable") is True
            and row.get("deprecatedAndHidden") is not True
            if (name := _optional_string(row.get("name"))) is not None
        )
    )
    if len(keys) > _CUSTOM_OBJECT_LIMIT:
        raise SorVendorOperationError(
            "vendor_custom_object_limit_exceeded",
            "Salesforce exposes more custom objects than this source revision can "
            f"discover safely ({_CUSTOM_OBJECT_LIMIT}).",
            retryable=False,
        )
    return keys


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.ok:
        return response.data
    if response.status_code == 401:
        raise SorVendorOperationError(
            "vendor_access_token_expired",
            "Salesforce rejected the current access token.",
            retryable=True,
            requires_reauthorization=True,
            refreshable_authorization=True,
        )
    if response.status_code == 403:
        raise SorVendorOperationError(
            "vendor_reauthorization_required",
            "Salesforce authorization no longer permits this operation.",
            retryable=False,
            requires_reauthorization=True,
        )
    if response.status_code == 429:
        raise SorVendorOperationError(
            "vendor_rate_limited",
            "Salesforce rate-limited the operation.",
            retryable=True,
        )
    if response.status_code >= 500:
        raise SorVendorOperationError(
            "vendor_server_failed",
            f"Salesforce could not {operation}.",
            retryable=True,
        )
    raise SorVendorOperationError(
        "vendor_request_rejected",
        f"Salesforce rejected the request to {operation}.",
        retryable=False,
    )


def _expect_mutation(response: SorJsonResponse, *, creates_record: bool) -> None:
    expected = {201} if creates_record else {200, 204}
    if response.status_code in expected:
        return
    if response.status_code in {409, 412}:
        raise SorVendorOperationError(
            "vendor_conflict",
            "Salesforce rejected a stale or conflicting record update.",
            retryable=False,
        )
    _expect(response, operation="apply the CRM action")


def _discovered_field(row: Mapping[str, object]) -> SorDiscoveredField:
    key = _identifier(_required_string(row.get("name"), field="Salesforce field"))
    values = row.get("picklistValues")
    choices = ()
    if isinstance(values, list):
        choices = tuple(
            value
            for item in values
            if isinstance(item, Mapping) and item.get("active") is True
            if (value := _optional_string(item.get("value"))) is not None
        )
    return SorDiscoveredField(
        key=key,
        label=_optional_string(row.get("label")) or key,
        data_type=_field_type(row.get("type")),
        nullable=row.get("nillable") is True,
        writable=row.get("createable") is True or row.get("updateable") is True,
        choices=choices,
        description=_optional_string(row.get("inlineHelpText")),
        group=_optional_string(row.get("compoundFieldName")),
    )


def _field_type(value: object) -> str:
    field_type = (_optional_string(value) or "").casefold()
    if field_type == "boolean":
        return "boolean"
    if field_type == "date":
        return "date"
    if field_type == "datetime":
        return "timestamp"
    if field_type in {"currency", "double", "int", "long", "percent"}:
        return "decimal"
    if field_type == "multipicklist":
        return "string_array"
    if field_type in {"combobox", "picklist"}:
        return "enum"
    if field_type in {
        "email",
        "encryptedstring",
        "id",
        "phone",
        "reference",
        "string",
        "textarea",
        "time",
        "url",
    }:
        return "text"
    return "bounded_json"


def _query_fields(selected_fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*_SYSTEM_FIELDS, *selected_fields)))


def _build_query(
    *,
    stream_key: str,
    fields: tuple[str, ...],
    checkpoint: tuple[datetime, str] | None,
    limit: int,
) -> str:
    selected = ", ".join(_identifier(field) for field in fields)
    query = f"SELECT {selected} FROM {_identifier(stream_key)}"
    if checkpoint is not None:
        stamp, record_id = checkpoint
        literal = _soql_datetime(stamp)
        query = (
            f"{query} WHERE (SystemModstamp > {literal} OR "
            f"(SystemModstamp = {literal} AND Id > '{record_id}'))"
        )
    return f"{query} ORDER BY SystemModstamp ASC, Id ASC LIMIT {limit}"


def _encode_cursor(row: Mapping[str, object]) -> str:
    stamp = _required_datetime(
        row.get("SystemModstamp"),
        field="Salesforce SystemModstamp",
    )
    record_id = _required_record_id(row.get("Id"))
    return json.dumps(
        {"id": record_id, "stamp": stamp.isoformat(), "v": 1},
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_cursor(value: str | None) -> tuple[datetime, str] | None:
    if value is None:
        return None
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise _invalid_cursor() from error
    if not isinstance(payload, dict) or set(payload) != {"id", "stamp", "v"}:
        raise _invalid_cursor()
    if payload.get("v") != 1:
        raise _invalid_cursor()
    try:
        stamp = _required_datetime(
            payload.get("stamp"),
            field="Salesforce cursor timestamp",
        )
        record_id = _required_record_id(payload.get("id"))
    except SorVendorOperationError as error:
        raise _invalid_cursor() from error
    return stamp, record_id


def _invalid_cursor() -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_cursor_invalid",
        "The Salesforce stream cursor is invalid.",
        retryable=False,
    )


def _soql_datetime(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise SorVendorOperationError(
            "vendor_schema_invalid",
            "Salesforce returned an invalid schema identifier.",
            retryable=False,
        )
    return value


def _required_record_id(value: object) -> str:
    normalized = _required_string(value, field="Salesforce record ID")
    if not _RECORD_ID.fullmatch(normalized):
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "Salesforce record ID is invalid.",
            retryable=False,
        )
    return normalized


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "Salesforce returned an invalid object.",
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


def _required_datetime(value: object, *, field: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            f"{field} is unavailable.",
            retryable=False,
        )
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    normalized = _optional_string(value)
    if normalized is None:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as error:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "Salesforce returned an invalid timestamp.",
            retryable=False,
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "Salesforce returned a timestamp without a timezone.",
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
            "Salesforce returned an invalid decimal value.",
            retryable=False,
        ) from error


def _from_salesforce_value(
    *,
    stream_key: str,
    vendor_field_key: str,
    value: object,
) -> object:
    """Convert documented vendor units before canonical mapping."""
    if stream_key != "Opportunity" or vendor_field_key != "Probability":
        return value
    probability = _optional_decimal(value)
    if probability is None:
        return None
    if not Decimal("0") <= probability <= Decimal("100"):
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "Salesforce returned an Opportunity probability outside 0 through 100.",
            retryable=False,
        )
    return float(probability / Decimal("100"))


def _to_salesforce_value(
    *,
    stream_key: str,
    vendor_field_key: str,
    value: object,
) -> object:
    """Convert canonical fractions back to Salesforce percentage units."""
    if stream_key != "Opportunity" or vendor_field_key != "Probability":
        return value
    try:
        probability = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise SorVendorOperationError(
            "vendor_command_invalid",
            "CRM deal probability must be a number between 0 and 1.",
            retryable=False,
        ) from error
    if not Decimal("0") <= probability <= Decimal("1"):
        raise SorVendorOperationError(
            "vendor_command_invalid",
            "CRM deal probability must be between 0 and 1.",
            retryable=False,
        )
    return float(probability * Decimal("100"))


def _optional_date(value: object) -> date | None:
    normalized = _optional_string(value)
    if normalized is None:
        return None
    try:
        return date.fromisoformat(normalized[:10])
    except ValueError as error:
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "Salesforce returned an invalid date value.",
            retryable=False,
        ) from error


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise SorVendorOperationError(
            "vendor_response_invalid",
            "Salesforce returned an invalid relationship list.",
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
            "Salesforce returned too many relationships.",
            retryable=False,
        )
    return values


__all__ = [
    "SALESFORCE_API_PREFIX",
    "SALESFORCE_API_VERSION",
    "SALESFORCE_MANIFEST",
    "SalesforceCrmAdapter",
    "create_salesforce_adapter",
]
