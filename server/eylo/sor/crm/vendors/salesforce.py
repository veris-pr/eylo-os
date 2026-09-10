"""Salesforce CRM adapter using a pinned REST API and keyset checkpoints."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import format_datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.crm.contracts import (
    CrmActivity,
    CrmActivityPayload,
    CrmCompany,
    CrmCompanyPayload,
    CrmContact,
    CrmContactPayload,
    CrmDeal,
    CrmDealPayload,
    CrmDealState,
    CrmEntityKind,
    CrmMappedFieldsCommandPayload,
    CrmMoveDealCommandPayload,
    CrmToolName,
)
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
    SorFieldDataType,
    SorMutationOperation,
    SorOAuthSpec,
    SorProfile,
    SorRecordPage,
    SorRecoveryPolicy,
    SorRelationshipRole,
    SorRelationshipTargets,
    SorVendorErrorCode,
    SorVendorOperationError,
    SorVendorStreamSpec,
    SorWebhookSignal,
    SorWebhookSubscription,
)

SALESFORCE_API_VERSION = "67.0"
SALESFORCE_API_PREFIX = f"/services/data/v{SALESFORCE_API_VERSION}"

API_SCOPE = "api"
REFRESH_SCOPE = "refresh_token"


class SalesforceStream(StrEnum):
    """Closed vendor stream vocabulary owned by this adapter."""

    CONTACT = "Contact"
    ACCOUNT = "Account"
    OPPORTUNITY = "Opportunity"
    TASK = "Task"


_STREAM_ENTITY = {
    SalesforceStream.CONTACT: CrmEntityKind.CONTACT,
    SalesforceStream.ACCOUNT: CrmEntityKind.COMPANY,
    SalesforceStream.OPPORTUNITY: CrmEntityKind.DEAL,
    SalesforceStream.TASK: CrmEntityKind.ACTIVITY,
}
_RELATIONSHIP_TARGETS = {
    SalesforceStream.OPPORTUNITY: {
        SorRelationshipRole.CONTACT: SalesforceStream.CONTACT,
        SorRelationshipRole.COMPANY: SalesforceStream.ACCOUNT,
    },
}
_TOOL_STREAM = {
    CrmToolName.CREATE_CONTACT: (SalesforceStream.CONTACT, SorMutationOperation.CREATE),
    CrmToolName.UPDATE_CONTACT: (SalesforceStream.CONTACT, SorMutationOperation.UPDATE),
    CrmToolName.CREATE_COMPANY: (SalesforceStream.ACCOUNT, SorMutationOperation.CREATE),
    CrmToolName.UPDATE_COMPANY: (SalesforceStream.ACCOUNT, SorMutationOperation.UPDATE),
    CrmToolName.CREATE_DEAL: (
        SalesforceStream.OPPORTUNITY,
        SorMutationOperation.CREATE,
    ),
    CrmToolName.UPDATE_DEAL: (
        SalesforceStream.OPPORTUNITY,
        SorMutationOperation.UPDATE,
    ),
    CrmToolName.MOVE_DEAL: (SalesforceStream.OPPORTUNITY, SorMutationOperation.UPDATE),
    CrmToolName.LOG_ACTIVITY: (SalesforceStream.TASK, SorMutationOperation.CREATE),
}
_READ_TOOLS = frozenset(
    {
        CrmToolName.FIND_CUSTOMER,
        CrmToolName.GET_CUSTOMER,
        CrmToolName.LIST_DEALS,
        CrmToolName.GET_DEAL,
        CrmToolName.DESCRIBE_CUSTOMER_FIELDS,
        CrmToolName.DESCRIBE_DEAL_FIELDS,
    }
)
_TOOL_STREAMS = {
    CrmToolName.FIND_CUSTOMER: frozenset(
        {SalesforceStream.CONTACT, SalesforceStream.ACCOUNT}
    ),
    CrmToolName.GET_CUSTOMER: frozenset(
        {SalesforceStream.CONTACT, SalesforceStream.ACCOUNT}
    ),
    CrmToolName.LIST_DEALS: frozenset({SalesforceStream.OPPORTUNITY}),
    CrmToolName.GET_DEAL: frozenset({SalesforceStream.OPPORTUNITY}),
    CrmToolName.DESCRIBE_CUSTOMER_FIELDS: frozenset(
        {SalesforceStream.CONTACT, SalesforceStream.ACCOUNT}
    ),
    CrmToolName.DESCRIBE_DEAL_FIELDS: frozenset({SalesforceStream.OPPORTUNITY}),
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
            key=SalesforceStream.CONTACT,
            label="Contacts",
            description="Salesforce contacts and selected custom fields.",
            canonical_entity="contact",
            change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
        ),
        SorVendorStreamSpec(
            key=SalesforceStream.ACCOUNT,
            label="Accounts",
            description="Salesforce accounts and selected custom fields.",
            canonical_entity="company",
            change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
        ),
        SorVendorStreamSpec(
            key=SalesforceStream.OPPORTUNITY,
            label="Opportunities",
            description="Salesforce opportunities and pipeline stages.",
            canonical_entity="deal",
            change_strategies=frozenset({SorChangeStrategy.UPDATED_AT}),
            depends_on=frozenset({SalesforceStream.CONTACT, SalesforceStream.ACCOUNT}),
            relationship_targets=SorRelationshipTargets(
                _RELATIONSHIP_TARGETS[SalesforceStream.OPPORTUNITY]
            ),
        ),
        SorVendorStreamSpec(
            key=SalesforceStream.TASK,
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
    tool_streams={
        tool.value: frozenset(stream.value for stream in streams)
        for tool, streams in _TOOL_STREAMS.items()
    },
    mutation_result_streams={
        tool_name: stream_key
        for tool_name, (stream_key, _creates) in _TOOL_STREAM.items()
    },
    oauth=SorOAuthSpec(
        authorization_url=("https://login.salesforce.com/services/oauth2/authorize"),
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
                SorVendorErrorCode.VENDOR_STREAM_UNAVAILABLE,
                "Salesforce does not permit the selected CRM objects.",
                recovery=SorRecoveryPolicy.TERMINAL,
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
        if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
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
            tool_name = CrmToolName(command.tool_name)
            stream_key, operation = _TOOL_STREAM[tool_name]
        except (ValueError, KeyError) as error:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_TOOL_UNSUPPORTED,
                "This Salesforce adapter does not execute the requested CRM action.",
                recovery=SorRecoveryPolicy.TERMINAL,
            ) from error
        _require_stream(stream_key, selected=self._context.selected_objects)
        if (
            operation is SorMutationOperation.CREATE
            and command.target_external_id is not None
        ):
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_COMMAND_INVALID,
                "A CRM create action cannot target an existing record.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if (
            operation is SorMutationOperation.UPDATE
            and command.target_external_id is None
        ):
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_COMMAND_INVALID,
                "A CRM update action requires an existing record.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if tool_name is CrmToolName.MOVE_DEAL:
            if not isinstance(command.payload, CrmMoveDealCommandPayload):
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_COMMAND_INVALID,
                    "Moving a deal requires a typed stage selection.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                )
            field_values: Mapping[str, object] = command.payload.to_wire()
        elif isinstance(command.payload, CrmMappedFieldsCommandPayload):
            field_values = command.payload.fields
        else:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_COMMAND_INVALID,
                "The CRM action has an invalid command payload.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        values = self._write_fields(stream_key, field_values)
        path = f"{SALESFORCE_API_PREFIX}/sobjects/{stream_key}"
        method = "POST"
        record_id: str | None = None
        if operation is SorMutationOperation.UPDATE:
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
                    None
                    if operation is SorMutationOperation.CREATE
                    else command.expected_source_revision
                ),
            )
            _expect_mutation(response, operation=operation)
        except SorVendorOperationError as error:
            if operation is SorMutationOperation.CREATE and error.code in {
                SorVendorErrorCode.VENDOR_TIMEOUT,
                SorVendorErrorCode.VENDOR_TRANSPORT_FAILED,
                SorVendorErrorCode.VENDOR_SERVER_FAILED,
            }:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_MUTATION_OUTCOME_UNKNOWN,
                    "Salesforce may have created the record; reconcile before retrying.",
                    recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
                ) from error
            raise
        if operation is SorMutationOperation.CREATE:
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

    def normalize_contact(
        self,
        record: SorExternalRecord,
        payload: CrmContactPayload,
    ) -> CrmContact:
        name = _optional_string(payload.name)
        if name is None:
            name = (
                " ".join(
                    value
                    for value in (
                        _optional_string(payload.first_name),
                        _optional_string(payload.last_name),
                    )
                    if value
                )
                or None
            )
        return CrmContact(
            external_id=record.external_id,
            name=name,
            primary_email=_optional_string(payload.primary_email),
            primary_phone=_optional_string(payload.primary_phone),
            job_title=_optional_string(payload.job_title),
            lifecycle_stage=_optional_string(payload.lifecycle_stage),
            owner_external_id=_optional_string(payload.owner_external_id),
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
        )

    def normalize_company(
        self,
        record: SorExternalRecord,
        payload: CrmCompanyPayload,
    ) -> CrmCompany:
        return CrmCompany(
            external_id=record.external_id,
            name=_optional_string(payload.name),
            domain=_optional_string(payload.domain),
            industry=_optional_string(payload.industry),
            owner_external_id=_optional_string(payload.owner_external_id),
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
        )

    def normalize_deal(
        self,
        record: SorExternalRecord,
        payload: CrmDealPayload,
    ) -> CrmDeal:
        return CrmDeal(
            external_id=record.external_id,
            title=_required_string(payload.title, field="CRM deal title"),
            pipeline_external_id=_optional_string(payload.pipeline_external_id),
            stage_external_id=_optional_string(payload.stage_external_id),
            native_stage=_optional_string(payload.native_stage),
            normalized_state=payload.normalized_state,
            amount=payload.amount,
            currency=_optional_string(payload.currency),
            probability=payload.probability,
            expected_close_date=payload.expected_close_date,
            owner_external_id=_optional_string(payload.owner_external_id),
            contact_external_ids=payload.contact_external_ids,
            company_external_ids=payload.company_external_ids,
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
        )

    def normalize_activity(
        self,
        record: SorExternalRecord,
        payload: CrmActivityPayload,
    ) -> CrmActivity:
        return CrmActivity(
            external_id=record.external_id,
            kind=_optional_string(payload.kind) or "task",
            subject=_optional_string(payload.subject),
            normalized_text=_optional_string(payload.normalized_text),
            occurred_at=_required_datetime(
                payload.occurred_at,
                field="CRM activity occurred_at",
            ),
            actor_external_id=_optional_string(payload.actor_external_id),
            participant_external_ids=payload.participant_external_ids,
            related_external_ids=payload.related_external_ids,
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
                SorVendorErrorCode.VENDOR_SCHEMA_EMPTY,
                f"Salesforce returned no fields for {object_key}.",
                recovery=SorRecoveryPolicy.TERMINAL,
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
                SorVendorErrorCode.VENDOR_PAGE_INVALID,
                "Salesforce page limit must be positive.",
                recovery=SorRecoveryPolicy.TERMINAL,
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
                SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
                "Salesforce returned more rows than the requested page limit.",
                recovery=SorRecoveryPolicy.TERMINAL,
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
                SorVendorErrorCode.SOURCE_MAPPING_EMPTY,
                f"The active mapping selects no {stream_key} fields.",
                recovery=SorRecoveryPolicy.TERMINAL,
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
                SorVendorErrorCode.VENDOR_COMMAND_INVALID,
                "A CRM mutation requires at least one mapped field.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        unknown = set(payload) - set(writable)
        if unknown:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_FIELD_NOT_WRITABLE,
                "The CRM mutation contains fields absent from the writable mapping.",
                recovery=SorRecoveryPolicy.TERMINAL,
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
            SorVendorErrorCode.VENDOR_ORIGIN_INVALID,
            "Salesforce instance origin is unavailable.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_ORIGIN_INVALID,
            "Salesforce instance origin is invalid.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
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
            SorVendorErrorCode.VENDOR_ORIGIN_INVALID,
            "Salesforce instance origin must be an HTTPS salesforce.com origin.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    return f"https://{host}"


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 16_384:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CREDENTIALS_INVALID,
            "Salesforce OAuth credentials are unavailable.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    return value.strip()


def _require_stream(stream_key: str, *, selected: tuple[str, ...]) -> str:
    object_key = _identifier(stream_key)
    if object_key not in selected:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNAVAILABLE,
            "The Salesforce stream is not selected for this source.",
            recovery=SorRecoveryPolicy.TERMINAL,
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
            SorVendorErrorCode.VENDOR_CUSTOM_OBJECT_LIMIT_EXCEEDED,
            "Salesforce exposes more custom objects than this source revision can "
            f"discover safely ({_CUSTOM_OBJECT_LIMIT}).",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return keys


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.ok:
        return response.data
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_ACCESS_TOKEN_EXPIRED,
            "Salesforce rejected the current access token.",
            recovery=SorRecoveryPolicy.REFRESH_AND_RETRY,
        )
    if response.status_code == HTTPStatus.FORBIDDEN:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_REAUTHORIZATION_REQUIRED,
            "Salesforce authorization no longer permits this operation.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RATE_LIMITED,
            "Salesforce rate-limited the operation.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SERVER_FAILED,
            f"Salesforce could not {operation}.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    raise SorVendorOperationError(
        SorVendorErrorCode.VENDOR_REQUEST_REJECTED,
        f"Salesforce rejected the request to {operation}.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _expect_mutation(
    response: SorJsonResponse,
    *,
    operation: SorMutationOperation,
) -> None:
    expected = {201} if operation is SorMutationOperation.CREATE else {200, 204}
    if response.status_code in expected:
        return
    if response.status_code in {HTTPStatus.CONFLICT, HTTPStatus.PRECONDITION_FAILED}:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CONFLICT,
            "Salesforce rejected a stale or conflicting record update.",
            recovery=SorRecoveryPolicy.TERMINAL,
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


def _field_type(value: object) -> SorFieldDataType:
    field_type = (_optional_string(value) or "").casefold()
    if field_type == "boolean":
        return SorFieldDataType.BOOLEAN
    if field_type == "date":
        return SorFieldDataType.DATE
    if field_type == "datetime":
        return SorFieldDataType.TIMESTAMP
    if field_type in {"currency", "double", "int", "long", "percent"}:
        return SorFieldDataType.DECIMAL
    if field_type == "multipicklist":
        return SorFieldDataType.STRING_ARRAY
    if field_type in {"combobox", "picklist"}:
        return SorFieldDataType.ENUM
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
        return SorFieldDataType.TEXT
    return SorFieldDataType.BOUNDED_JSON


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
        SorVendorErrorCode.VENDOR_CURSOR_INVALID,
        "The Salesforce stream cursor is invalid.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _soql_datetime(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SCHEMA_INVALID,
            "Salesforce returned an invalid schema identifier.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return value


def _required_record_id(value: object) -> str:
    normalized = _required_string(value, field="Salesforce record ID")
    if not _RECORD_ID.fullmatch(normalized):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Salesforce record ID is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return normalized


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Salesforce returned an invalid object.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return value


def _object_list(value: object, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 20_000:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            f"{field} have an invalid shape.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return [_object(item) for item in value]


def _required_string(value: object, *, field: str) -> str:
    normalized = _optional_string(value)
    if normalized is None:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            f"{field} is unavailable.",
            recovery=SorRecoveryPolicy.TERMINAL,
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
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            f"{field} is unavailable.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = _optional_string(value)
        if normalized is None:
            return None
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as error:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
                "Salesforce returned an invalid timestamp.",
                recovery=SorRecoveryPolicy.TERMINAL,
            ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Salesforce returned a timestamp without a timezone.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return parsed.astimezone(timezone.utc)


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Salesforce returned an invalid decimal value.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error


def _from_salesforce_value(
    *,
    stream_key: str,
    vendor_field_key: str,
    value: object,
) -> object:
    """Convert documented vendor units before canonical mapping."""
    if stream_key != SalesforceStream.OPPORTUNITY or vendor_field_key != "Probability":
        return value
    probability = _optional_decimal(value)
    if probability is None:
        return None
    if not Decimal("0") <= probability <= Decimal("100"):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Salesforce returned an Opportunity probability outside 0 through 100.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return float(probability / Decimal("100"))


def _to_salesforce_value(
    *,
    stream_key: str,
    vendor_field_key: str,
    value: object,
) -> object:
    """Convert canonical fractions back to Salesforce percentage units."""
    if stream_key != SalesforceStream.OPPORTUNITY or vendor_field_key != "Probability":
        return value
    try:
        probability = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "CRM deal probability must be a number between 0 and 1.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
    if not Decimal("0") <= probability <= Decimal("1"):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "CRM deal probability must be between 0 and 1.",
            recovery=SorRecoveryPolicy.TERMINAL,
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
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Salesforce returned an invalid date value.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Salesforce returned an invalid relationship list.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    values = tuple(
        normalized
        for item in value
        if (normalized := _optional_string(item)) is not None
    )
    if len(values) > 10_000:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Salesforce returned too many relationships.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return values


__all__ = [
    "SALESFORCE_API_PREFIX",
    "SALESFORCE_API_VERSION",
    "SALESFORCE_MANIFEST",
    "SalesforceCrmAdapter",
    "create_salesforce_adapter",
]
