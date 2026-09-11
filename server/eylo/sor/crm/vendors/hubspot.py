"""HubSpot CRM adapter using the pinned 2026-03 API surface."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from html.parser import HTMLParser
from http import HTTPMethod, HTTPStatus
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

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
from eylo.sor.runtime.http import (
    SorHttpTransport,
    SorJsonHttpClient,
    SorJsonResponse,
)
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterContext,
    SorCapabilityUnavailable,
    SorChangeMode,
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
    SorWebhookPayloadError,
    SorWebhookSignal,
    SorWebhookSubscription,
    SorWebhookVerificationError,
)
from eylo.sor.shared.json_values import SorJsonValue, to_json_value

from .hubspot_wire import (
    MAX_PAGE_SIZE,
    HubSpotAccount,
    HubSpotAssociationError,
    HubSpotAssociationErrorCategory,
    HubSpotAssociationErrorSubcategory,
    HubSpotAssociationInput,
    HubSpotAssociationRead,
    HubSpotAssociations,
    HubSpotFieldType,
    HubSpotPageQuery,
    HubSpotProperties,
    HubSpotProperty,
    HubSpotPropertyType,
    HubSpotReadQuery,
    HubSpotRecord,
    HubSpotRecordIdentity,
    HubSpotRecords,
    HubSpotWrite,
    parse_response,
)

HUBSPOT_ORIGIN = "https://api.hubapi.com"
HUBSPOT_API_VERSION = "2026-03"

CONTACTS_READ = "crm.objects.contacts.read"
CONTACTS_WRITE = "crm.objects.contacts.write"
COMPANIES_READ = "crm.objects.companies.read"
COMPANIES_WRITE = "crm.objects.companies.write"
DEALS_READ = "crm.objects.deals.read"
DEALS_WRITE = "crm.objects.deals.write"
NOTES_READ = CONTACTS_READ


class HubSpotStream(StrEnum):
    """Closed vendor stream vocabulary owned by this adapter."""

    CONTACTS = "contacts"
    COMPANIES = "companies"
    DEALS = "deals"
    NOTES = "notes"


_STREAM_ENTITY = {
    HubSpotStream.CONTACTS: CrmEntityKind.CONTACT,
    HubSpotStream.COMPANIES: CrmEntityKind.COMPANY,
    HubSpotStream.DEALS: CrmEntityKind.DEAL,
    HubSpotStream.NOTES: CrmEntityKind.ACTIVITY,
}
_RELATIONSHIP_TARGETS = {
    HubSpotStream.DEALS: {
        SorRelationshipRole.CONTACT: HubSpotStream.CONTACTS,
        SorRelationshipRole.COMPANY: HubSpotStream.COMPANIES,
    },
    HubSpotStream.NOTES: {
        SorRelationshipRole.CONTACT: HubSpotStream.CONTACTS,
        SorRelationshipRole.COMPANY: HubSpotStream.COMPANIES,
        SorRelationshipRole.DEAL: HubSpotStream.DEALS,
    },
}
_ASSOCIATION_FIELDS = {
    HubSpotStream.DEALS: {
        "eylo_associated_contact_ids": (
            HubSpotStream.CONTACTS,
            "hubspot.association.contacts",
            "Associated contacts",
        ),
        "eylo_associated_company_ids": (
            HubSpotStream.COMPANIES,
            "hubspot.association.companies",
            "Associated companies",
        ),
    },
    HubSpotStream.NOTES: {
        "eylo_associated_contact_ids": (
            HubSpotStream.CONTACTS,
            "hubspot.association.contacts",
            "Associated contacts",
        ),
        "eylo_associated_company_ids": (
            HubSpotStream.COMPANIES,
            "hubspot.association.companies",
            "Associated companies",
        ),
        "eylo_associated_deal_ids": (
            HubSpotStream.DEALS,
            "hubspot.association.deals",
            "Associated deals",
        ),
    },
}
_MAX_ASSOCIATIONS_PER_RECORD = 10_000
_MAX_ASSOCIATION_PAGES = 100
_WEBHOOK_STREAMS = {
    "company": HubSpotStream.COMPANIES,
    "contact": HubSpotStream.CONTACTS,
    "deal": HubSpotStream.DEALS,
    "0-1": HubSpotStream.CONTACTS,
    "0-2": HubSpotStream.COMPANIES,
    "0-3": HubSpotStream.DEALS,
}
_WEBHOOK_MAX_EVENTS = 100
_WEBHOOK_MAX_AGE_MILLISECONDS = 300_000
_SIGNATURE_URI_DECODES = {
    "%3A": ":",
    "%2F": "/",
    "%3F": "?",
    "%40": "@",
    "%21": "!",
    "%24": "$",
    "%27": "'",
    "%28": "(",
    "%29": ")",
    "%2A": "*",
    "%2C": ",",
    "%3B": ";",
}
_PERCENT_ESCAPE = re.compile(r"%[0-9a-fA-F]{2}")
_TOOL_STREAM = {
    CrmToolName.CREATE_CONTACT: (HubSpotStream.CONTACTS, SorMutationOperation.CREATE),
    CrmToolName.UPDATE_CONTACT: (HubSpotStream.CONTACTS, SorMutationOperation.UPDATE),
    CrmToolName.CREATE_COMPANY: (HubSpotStream.COMPANIES, SorMutationOperation.CREATE),
    CrmToolName.UPDATE_COMPANY: (HubSpotStream.COMPANIES, SorMutationOperation.UPDATE),
    CrmToolName.CREATE_DEAL: (HubSpotStream.DEALS, SorMutationOperation.CREATE),
    CrmToolName.UPDATE_DEAL: (HubSpotStream.DEALS, SorMutationOperation.UPDATE),
    CrmToolName.MOVE_DEAL: (HubSpotStream.DEALS, SorMutationOperation.UPDATE),
}
_WRITE_SCOPES = {
    CrmToolName.CREATE_CONTACT: (CONTACTS_WRITE,),
    CrmToolName.UPDATE_CONTACT: (CONTACTS_WRITE,),
    CrmToolName.CREATE_COMPANY: (COMPANIES_WRITE,),
    CrmToolName.UPDATE_COMPANY: (COMPANIES_WRITE,),
    CrmToolName.CREATE_DEAL: (DEALS_WRITE,),
    CrmToolName.UPDATE_DEAL: (DEALS_WRITE,),
    CrmToolName.MOVE_DEAL: (DEALS_WRITE,),
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
        {HubSpotStream.CONTACTS, HubSpotStream.COMPANIES}
    ),
    CrmToolName.GET_CUSTOMER: frozenset(
        {HubSpotStream.CONTACTS, HubSpotStream.COMPANIES}
    ),
    CrmToolName.LIST_DEALS: frozenset({HubSpotStream.DEALS}),
    CrmToolName.GET_DEAL: frozenset({HubSpotStream.DEALS}),
    CrmToolName.DESCRIBE_CUSTOMER_FIELDS: frozenset(
        {HubSpotStream.CONTACTS, HubSpotStream.COMPANIES}
    ),
    CrmToolName.DESCRIBE_DEAL_FIELDS: frozenset({HubSpotStream.DEALS}),
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
            key=HubSpotStream.CONTACTS,
            label="Contacts",
            description="People and their selected standard or custom properties.",
            canonical_entity="contact",
            change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
        ),
        SorVendorStreamSpec(
            key=HubSpotStream.COMPANIES,
            label="Companies",
            description="Companies and their selected standard or custom properties.",
            canonical_entity="company",
            change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
        ),
        SorVendorStreamSpec(
            key=HubSpotStream.DEALS,
            label="Deals",
            description="Deals and their selected standard or custom properties.",
            canonical_entity="deal",
            change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
            depends_on=frozenset({HubSpotStream.CONTACTS, HubSpotStream.COMPANIES}),
            relationship_targets=SorRelationshipTargets(
                by_role=_RELATIONSHIP_TARGETS[HubSpotStream.DEALS],
            ),
        ),
        SorVendorStreamSpec(
            key=HubSpotStream.NOTES,
            label="Notes",
            description="CRM timeline notes and their record associations.",
            canonical_entity="activity",
            change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
            depends_on=frozenset(
                {HubSpotStream.CONTACTS, HubSpotStream.COMPANIES, HubSpotStream.DEALS}
            ),
            relationship_targets=SorRelationshipTargets(
                by_role=_RELATIONSHIP_TARGETS[HubSpotStream.NOTES],
            ),
        ),
    ),
    readable_entities=frozenset(_STREAM_ENTITY.values()),
    writable_entities=frozenset(
        _STREAM_ENTITY[stream_key] for stream_key, _creates in _TOOL_STREAM.values()
    ),
    readable_tools=_READ_TOOLS,
    writable_tools=frozenset(_TOOL_STREAM),
    change_strategies=frozenset({SorChangeStrategy.FULL_RECONCILE}),
    required_scopes={
        HubSpotStream.CONTACTS: (CONTACTS_READ,),
        HubSpotStream.COMPANIES: (COMPANIES_READ,),
        HubSpotStream.DEALS: (DEALS_READ,),
        HubSpotStream.NOTES: (NOTES_READ,),
    },
    tool_required_scopes={tool.value: scopes for tool, scopes in _WRITE_SCOPES.items()},
    tool_streams={
        tool.value: frozenset(stream.value for stream in streams)
        for tool, streams in _TOOL_STREAMS.items()
    },
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
    change_mode=SorChangeMode.APP_WEBHOOK,
    supports_custom_fields=True,
)


class _HubSpotWebhookSignal(BaseModel):
    """A normalized vendor hint with a required timestamp for deduplication."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    event_type: str
    vendor_object_key: HubSpotStream
    external_id: str
    occurred_at: datetime

    def to_platform_signal(self) -> SorWebhookSignal:
        return SorWebhookSignal(
            delivery_id=None,
            event_type=self.event_type,
            vendor_object_key=self.vendor_object_key.value,
            external_id=self.external_id,
            occurred_at=self.occurred_at,
        )


class HubSpotAppWebhookDelivery(BaseModel):
    """One verified HubSpot account batch before source-selection filtering."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_external_id: str
    signals: tuple[SorWebhookSignal, ...]


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
        data = parse_response(
            HubSpotAccount, _expect(response, operation="verify HubSpot account")
        )
        portal_id = data.portalId
        account_type = data.accountType
        display_name = f"HubSpot {account_type}" if account_type else "HubSpot account"
        return SorConnectionVerification(
            account_external_id=portal_id,
            account_display_name=display_name,
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=HUBSPOT_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        objects: list[SorDiscoveredObject] = []
        for object_key in self._context.selected_objects:
            stream_key = _require_stream(
                object_key, selected=self._context.selected_objects
            )
            response = await self._client.request(
                f"/crm/properties/{HUBSPOT_API_VERSION}/{stream_key}"
            )
            payload = parse_response(
                HubSpotProperties,
                _expect(response, operation="discover HubSpot schema"),
            )
            fields = [
                _discovered_field(row) for row in payload.results if not row.archived
            ]
            fields.extend(_association_discovered_fields(stream_key))
            fields = tuple(
                sorted(
                    fields,
                    key=lambda field: (field.group or "", field.label, field.key),
                )
            )
            if not fields:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_SCHEMA_EMPTY,
                    f"HubSpot returned no fields for {stream_key}.",
                    recovery=SorRecoveryPolicy.TERMINAL,
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
        stream_key = _require_stream(
            vendor_object_key, selected=self._context.selected_objects
        )
        record_id = _required_id(external_id, field="HubSpot record ID")
        fields = self._selected_fields(stream_key)
        property_fields = _property_fields(stream_key, fields)
        query = HubSpotReadQuery(properties=",".join(property_fields) or None)
        response = await self._client.request(
            f"/crm/objects/{HUBSPOT_API_VERSION}/{stream_key}/{record_id}",
            query=query.model_dump(mode="json", exclude_none=True),
        )
        if response.status_code == HTTPStatus.NOT_FOUND:
            raise SorExternalRecordNotFound(
                vendor_object_key=vendor_object_key,
                external_id=record_id,
            )
        data = parse_response(
            HubSpotRecord, _expect(response, operation="read HubSpot record")
        )
        associations = await self._association_values(
            stream_key=stream_key,
            selected_fields=fields,
            record_ids=(record_id,),
        )
        return _external_record(
            stream_key,
            data,
            selected_fields=fields,
            association_values=associations[record_id],
        )

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
            tool_name = CrmToolName(command.tool_name)
            stream_key, operation = _TOOL_STREAM[tool_name]
        except (ValueError, KeyError) as error:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_TOOL_UNSUPPORTED,
                "This HubSpot adapter does not execute the requested CRM action.",
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
        properties = self._write_properties(stream_key, field_values)
        path = f"/crm/objects/{HUBSPOT_API_VERSION}/{stream_key}"
        method = HTTPMethod.POST
        if operation is SorMutationOperation.UPDATE:
            record_id = _required_id(
                command.target_external_id,
                field="HubSpot record ID",
            )
            path = f"{path}/{record_id}"
            method = HTTPMethod.PATCH
        try:
            response = await self._client.request(
                path,
                method=method,
                payload=HubSpotWrite(properties=properties).model_dump(mode="json"),
                idempotency_key=command.idempotency_key,
            )
            data = parse_response(
                HubSpotRecordIdentity, _expect_mutation(response, operation=operation)
            )
        except SorVendorOperationError as error:
            if operation is SorMutationOperation.CREATE and error.code in {
                SorVendorErrorCode.VENDOR_TIMEOUT,
                SorVendorErrorCode.VENDOR_TRANSPORT_FAILED,
                SorVendorErrorCode.VENDOR_SERVER_FAILED,
            }:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_MUTATION_OUTCOME_UNKNOWN,
                    "HubSpot may have created the record; reconcile before retrying.",
                    recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
                ) from error
            raise
        external_id = data.id
        request_ids = response.header_values("x-hubspot-correlation-id")
        return SorCommandResult(
            vendor_object_key=stream_key,
            external_id=external_id,
            external_request_id=request_ids[0] if request_ids else None,
            source_revision=data.updatedAt,
            source_url=_safe_source_url(data.url),
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
        contacts = payload.contact_external_ids
        companies = payload.company_external_ids
        deals = payload.deal_external_ids
        participants = payload.participant_external_ids
        related = payload.related_external_ids
        return CrmActivity(
            external_id=record.external_id,
            kind="note",
            subject=_optional_string(payload.subject),
            normalized_text=_activity_text(payload.normalized_text),
            occurred_at=_required_datetime(
                payload.occurred_at or record.source_created_at,
                field="HubSpot note timestamp",
            ),
            actor_external_id=_optional_string(payload.actor_external_id),
            participant_external_ids=tuple(dict.fromkeys((*participants, *contacts))),
            related_external_ids=tuple(dict.fromkeys((*related, *companies, *deals))),
            source_url=record.source_url,
            contact_external_ids=contacts,
            company_external_ids=companies,
            deal_external_ids=deals,
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
        stream_key = _require_stream(
            stream_key, selected=self._context.selected_objects
        )
        if limit <= 0:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_PAGE_INVALID,
                "HubSpot page limit must be positive.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        fields = self._selected_fields(stream_key)
        property_fields = _property_fields(stream_key, fields)
        query = HubSpotPageQuery(
            limit=min(limit, MAX_PAGE_SIZE),
            properties=",".join(property_fields) or None,
            after=cursor,
        )
        response = await self._client.request(
            f"/crm/objects/{HUBSPOT_API_VERSION}/{stream_key}",
            query=query.model_dump(mode="json", exclude_none=True),
        )
        data = parse_response(
            HubSpotRecords, _expect(response, operation="read HubSpot records")
        )
        rows = data.results
        record_ids = tuple(row.id for row in rows)
        if len(set(record_ids)) != len(record_ids):
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
                "HubSpot returned duplicate record IDs in one page.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        associations = await self._association_values(
            stream_key=stream_key,
            selected_fields=fields,
            record_ids=record_ids,
        )
        next_cursor = data.paging.cursor if data.paging is not None else None
        return SorRecordPage(
            records=tuple(
                _external_record(
                    stream_key,
                    row,
                    selected_fields=fields,
                    association_values=associations[record_id],
                )
                for row, record_id in zip(rows, record_ids, strict=True)
            ),
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )

    def _selected_fields(self, stream_key: HubSpotStream) -> tuple[str, ...]:
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
                SorVendorErrorCode.SOURCE_MAPPING_EMPTY,
                f"The active mapping selects no {stream_key} fields.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        return fields

    async def _association_values(
        self,
        *,
        stream_key: HubSpotStream,
        selected_fields: tuple[str, ...],
        record_ids: tuple[str, ...],
    ) -> dict[str, dict[str, tuple[str, ...]]]:
        values = {record_id: {} for record_id in record_ids}
        association_fields = _ASSOCIATION_FIELDS.get(stream_key, {})
        if not association_fields or not record_ids:
            return values
        for field_key in selected_fields:
            association = association_fields.get(field_key)
            if association is None:
                continue
            target_stream, _vendor_type, _label = association
            targets = await self._read_associations(
                from_stream=stream_key,
                to_stream=target_stream,
                record_ids=record_ids,
            )
            for record_id in record_ids:
                values[record_id][field_key] = targets[record_id]
        return values

    async def _read_associations(
        self,
        *,
        from_stream: HubSpotStream,
        to_stream: HubSpotStream,
        record_ids: tuple[str, ...],
    ) -> dict[str, tuple[str, ...]]:
        collected = {record_id: [] for record_id in record_ids}
        pending: dict[str, str | None] = {record_id: None for record_id in record_ids}
        for _page_number in range(_MAX_ASSOCIATION_PAGES):
            request = HubSpotAssociationRead(
                inputs=[
                    HubSpotAssociationInput(id=record_id, after=after or None)
                    for record_id, after in pending.items()
                ]
            )
            response = await self._client.request(
                (
                    f"/crm/associations/{HUBSPOT_API_VERSION}/"
                    f"{from_stream}/{to_stream}/batch/read"
                ),
                method=HTTPMethod.POST,
                payload=request.model_dump(mode="json", exclude_none=True),
                retry_transport_failures=True,
            )
            data = parse_response(
                HubSpotAssociations,
                _expect(response, operation="read HubSpot record associations"),
            )
            no_association_ids = _no_association_ids(
                data.errors,
                pending_ids=frozenset(pending),
                from_stream=from_stream,
                to_stream=to_stream,
            )
            rows = data.results
            seen: set[str] = set()
            next_pending: dict[str, str | None] = {}
            for row in rows:
                source_id = row.source.id
                if source_id not in pending or source_id in seen:
                    raise SorVendorOperationError(
                        SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
                        "HubSpot returned mismatched association results.",
                        recovery=SorRecoveryPolicy.TERMINAL,
                    )
                seen.add(source_id)
                for target in row.to:
                    collected[source_id].append(target.toObjectId)
                if len(collected[source_id]) > _MAX_ASSOCIATIONS_PER_RECORD:
                    raise SorVendorOperationError(
                        SorVendorErrorCode.VENDOR_RELATIONSHIP_LIMIT_EXCEEDED,
                        "A HubSpot record has too many associations to synchronize safely.",
                        recovery=SorRecoveryPolicy.TERMINAL,
                    )
                after = row.paging.cursor if row.paging is not None else None
                if after is not None:
                    next_pending[source_id] = after
            if seen & no_association_ids or seen | no_association_ids != set(pending):
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
                    "HubSpot omitted records from an association batch.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                )
            if not next_pending:
                return {
                    record_id: tuple(dict.fromkeys(targets))
                    for record_id, targets in collected.items()
                }
            pending = next_pending
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RELATIONSHIP_LIMIT_EXCEEDED,
            "HubSpot association pagination exceeded the synchronization limit.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )

    def _write_properties(
        self,
        stream_key: HubSpotStream,
        payload: Mapping[str, object],
    ) -> dict[str, SorJsonValue]:
        writable = {
            field.agent_key: field.vendor_field_key
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
        return {writable[key]: to_json_value(value) for key, value in payload.items()}


def verify_hubspot_app_webhook(
    *,
    headers: Mapping[str, str],
    body: bytes,
    client_secret: str,
    request_uri: str,
    now: datetime | None = None,
) -> None:
    """Authenticate one HubSpot v3 delivery against its exact public URI."""
    signature = _header(headers, "x-hubspot-signature-v3")
    timestamp = _header(headers, "x-hubspot-request-timestamp")
    if signature is None or timestamp is None:
        raise SorWebhookVerificationError("HubSpot webhook signature is missing.")
    try:
        timestamp_milliseconds = int(timestamp)
    except ValueError as error:
        raise SorWebhookVerificationError(
            "HubSpot webhook timestamp is invalid."
        ) from error
    current_milliseconds = int(
        (now or datetime.now(timezone.utc)).astimezone(timezone.utc).timestamp() * 1000
    )
    if (
        timestamp_milliseconds <= 0
        or abs(current_milliseconds - timestamp_milliseconds)
        > _WEBHOOK_MAX_AGE_MILLISECONDS
    ):
        raise SorWebhookVerificationError("HubSpot webhook timestamp is stale.")
    try:
        provided = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError) as error:
        raise SorWebhookVerificationError(
            "HubSpot webhook signature is invalid."
        ) from error
    signed = (
        b"POST"
        + _decode_signature_uri(request_uri).encode("utf-8")
        + body
        + timestamp.encode("ascii")
    )
    expected = hmac.new(
        client_secret.encode("utf-8"),
        signed,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(provided, expected):
        raise SorWebhookVerificationError("HubSpot webhook signature is invalid.")


def parse_hubspot_app_webhook(*, body: bytes) -> HubSpotAppWebhookDelivery:
    """Normalize supported HubSpot CRM events without trusting their record data."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SorWebhookPayloadError(
            "HubSpot webhook body is not valid JSON."
        ) from error
    if (
        not isinstance(payload, list)
        or not payload
        or len(payload) > _WEBHOOK_MAX_EVENTS
    ):
        raise SorWebhookPayloadError(
            "HubSpot webhook body must contain one bounded event batch."
        )
    portal_ids: set[str] = set()
    signals: dict[tuple[HubSpotStream, str], _HubSpotWebhookSignal] = {}
    for raw in payload:
        if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
            raise SorWebhookPayloadError("HubSpot webhook event is invalid.")
        portal_ids.add(_webhook_id(raw.get("portalId"), field="portalId"))
        event_type = _hubspot_webhook_event_type(raw)
        object_type = event_type.split(".", 1)[0]
        if object_type == "object":
            object_type = _webhook_id(raw.get("objectTypeId"), field="objectTypeId")
        stream_key = _WEBHOOK_STREAMS.get(object_type)
        if stream_key is None:
            continue
        external_id = _webhook_id(
            raw.get("objectId", raw.get("fromObjectId")),
            field="objectId",
        )
        signal = _HubSpotWebhookSignal(
            event_type=event_type,
            vendor_object_key=stream_key,
            external_id=external_id,
            occurred_at=_webhook_datetime(raw.get("occurredAt")),
        )
        key = (stream_key, external_id)
        previous = signals.get(key)
        if previous is None or signal.occurred_at > previous.occurred_at:
            signals[key] = signal
    if len(portal_ids) != 1:
        raise SorWebhookPayloadError(
            "HubSpot webhook events disagree on their account identity."
        )
    return HubSpotAppWebhookDelivery(
        organization_external_id=next(iter(portal_ids)),
        signals=tuple(signal.to_platform_signal() for signal in signals.values()),
    )


def create_hubspot_adapter(context: SorAdapterContext) -> HubSpotCrmAdapter:
    """Construct the production HubSpot adapter for the explicit registry."""
    return HubSpotCrmAdapter(context)


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 16_384:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CREDENTIALS_INVALID,
            "HubSpot OAuth credentials are unavailable.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    return value.strip()


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    for key, value in headers.items():
        if key.casefold() == expected:
            normalized = value.strip()
            return normalized or None
    return None


def _decode_signature_uri(value: str) -> str:
    """Decode only the URI escapes HubSpot defines for v3 signatures."""
    return _PERCENT_ESCAPE.sub(
        lambda match: _SIGNATURE_URI_DECODES.get(
            match.group(0).upper(), match.group(0)
        ),
        value,
    )


def _hubspot_webhook_event_type(event: Mapping[str, object]) -> str:
    subscription_type = _optional_string(event.get("subscriptionType"))
    event_type = _optional_string(event.get("eventType"))
    if subscription_type is not None and event_type is not None:
        if subscription_type != event_type:
            raise SorWebhookPayloadError("HubSpot webhook event types disagree.")
    value = subscription_type or event_type
    if value is None or value.count(".") != 1 or len(value) > 128:
        raise SorWebhookPayloadError("HubSpot webhook event type is invalid.")
    return value


def _webhook_id(value: object, *, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SorWebhookPayloadError(f"HubSpot webhook {field} is invalid.")
    normalized = str(value).strip()
    if not 1 <= len(normalized) <= 512 or any(
        character in normalized for character in "/?#"
    ):
        raise SorWebhookPayloadError(f"HubSpot webhook {field} is invalid.")
    return normalized


def _webhook_datetime(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SorWebhookPayloadError("HubSpot webhook occurredAt is invalid.")
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise SorWebhookPayloadError(
            "HubSpot webhook occurredAt is invalid."
        ) from error


def _require_stream(stream_key: str, *, selected: tuple[str, ...]) -> HubSpotStream:
    if stream_key not in _STREAM_ENTITY or stream_key not in selected:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNAVAILABLE,
            "The HubSpot stream is not selected for this source.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return HubSpotStream(stream_key)


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.ok:
        return response.data
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_ACCESS_TOKEN_EXPIRED,
            "HubSpot rejected the current access token.",
            recovery=SorRecoveryPolicy.REFRESH_AND_RETRY,
        )
    if response.status_code == HTTPStatus.FORBIDDEN:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_REAUTHORIZATION_REQUIRED,
            "HubSpot authorization no longer permits this operation.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RATE_LIMITED,
            "HubSpot rate-limited the operation.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SERVER_FAILED,
            f"HubSpot could not {operation}.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    raise SorVendorOperationError(
        SorVendorErrorCode.VENDOR_REQUEST_REJECTED,
        f"HubSpot rejected the request to {operation}.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _expect_mutation(
    response: SorJsonResponse,
    *,
    operation: SorMutationOperation,
) -> object:
    if response.status_code in {HTTPStatus.OK, HTTPStatus.CREATED}:
        return response.data
    if response.status_code in {HTTPStatus.CONFLICT, HTTPStatus.PRECONDITION_FAILED}:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CONFLICT,
            "HubSpot rejected conflicting record data.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    try:
        return _expect(response, operation="apply the CRM action")
    except SorVendorOperationError as error:
        if (
            operation is SorMutationOperation.CREATE
            and error.code == SorVendorErrorCode.VENDOR_SERVER_FAILED
        ):
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_SERVER_FAILED,
                str(error),
                recovery=SorRecoveryPolicy.RETRY,
            ) from error
        raise


def _discovered_field(row: HubSpotProperty) -> SorDiscoveredField:
    key = _required_string(row.name, field="HubSpot property name")
    metadata = row.modificationMetadata
    read_only = metadata is not None and metadata.readOnlyValue is True
    choices = tuple(
        option.value
        for option in row.options or ()
        if option.value is not None and option.hidden is not True
    )
    return SorDiscoveredField(
        key=key,
        label=row.label or key,
        data_type=_field_type(row),
        nullable=True,
        writable=not read_only and row.calculated is not True,
        choices=choices,
        description=row.description,
        group=row.groupName,
    )


def _association_discovered_fields(
    stream_key: HubSpotStream,
) -> tuple[SorDiscoveredField, ...]:
    associations = _ASSOCIATION_FIELDS.get(stream_key, {})
    return tuple(
        SorDiscoveredField(
            key=field_key,
            label=label,
            data_type=SorFieldDataType.STRING_ARRAY,
            nullable=True,
            writable=False,
            description=(
                f"HubSpot {target_stream} associated with this {stream_key.rstrip('s')}. "
                "Eylo resolves these IDs into canonical CRM relationships."
            ),
            group="Associations",
            vendor_type=vendor_type,
        )
        for field_key, (
            target_stream,
            vendor_type,
            label,
        ) in associations.items()
    )


def _property_fields(
    stream_key: HubSpotStream,
    selected_fields: tuple[str, ...],
) -> tuple[str, ...]:
    associations = _ASSOCIATION_FIELDS.get(stream_key, {})
    return tuple(
        field_key for field_key in selected_fields if field_key not in associations
    )


def _field_type(row: HubSpotProperty) -> SorFieldDataType:
    if row.fieldType in {HubSpotFieldType.CHECKBOX, HubSpotFieldType.MULTI_CHECKBOX}:
        return SorFieldDataType.STRING_ARRAY
    if row.type is None:
        return SorFieldDataType.BOUNDED_JSON
    try:
        property_type = HubSpotPropertyType(row.type)
    except ValueError:
        return SorFieldDataType.BOUNDED_JSON
    return {
        HubSpotPropertyType.BOOLEAN: SorFieldDataType.BOOLEAN,
        HubSpotPropertyType.DATE: SorFieldDataType.DATE,
        HubSpotPropertyType.DATETIME: SorFieldDataType.TIMESTAMP,
        HubSpotPropertyType.ENUMERATION: SorFieldDataType.ENUM,
        HubSpotPropertyType.NUMBER: SorFieldDataType.DECIMAL,
        HubSpotPropertyType.PHONE_NUMBER: SorFieldDataType.TEXT,
        HubSpotPropertyType.STRING: SorFieldDataType.TEXT,
    }[property_type]


class _ActivityTextParser(HTMLParser):
    """Project HubSpot activity markup into readable canonical text."""

    _BLOCK_TAGS = frozenset(
        {"blockquote", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p"}
    )
    _IGNORED_TAGS = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and normalized_tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in self._IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif self._ignored_depth == 0 and normalized_tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def _activity_text(value: object) -> str | None:
    source = _optional_string(value)
    if source is None:
        return None
    parser = _ActivityTextParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "HubSpot returned unreadable activity content.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
    lines = (
        re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()
    )
    normalized = "\n".join(line for line in lines if line)
    return normalized or None


def _external_record(
    stream_key: HubSpotStream,
    row: HubSpotRecord,
    *,
    selected_fields: tuple[str, ...],
    association_values: Mapping[str, tuple[str, ...]] | None = None,
) -> SorExternalRecord:
    external_id = row.id
    if row.archived is True:
        raise SorExternalRecordNotFound(
            vendor_object_key=stream_key,
            external_id=external_id,
            reason="Archived in HubSpot",
            deleted_at=_optional_datetime(row.archivedAt),
        )
    properties = row.properties
    if properties is None:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "HubSpot record properties are invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    selected = {
        key: (
            tuple((association_values or {}).get(key, ()))
            if key in _ASSOCIATION_FIELDS.get(stream_key, {})
            else properties.get(key)
        )
        for key in selected_fields
    }
    updated_at = _optional_datetime(row.updatedAt)
    return SorExternalRecord(
        vendor_object_key=stream_key,
        external_id=external_id,
        payload=selected,
        source_created_at=_optional_datetime(row.createdAt),
        source_updated_at=updated_at,
        source_revision=updated_at.isoformat() if updated_at else None,
        source_url=_safe_source_url(row.url),
    )


def _no_association_ids(
    rows: list[HubSpotAssociationError] | None,
    *,
    pending_ids: frozenset[str],
    from_stream: HubSpotStream,
    to_stream: HubSpotStream,
) -> set[str]:
    """Accept only HubSpot's explicit, identity-matched empty-association result."""
    if rows is None:
        return set()
    result: set[str] = set()
    for row in rows:
        if (
            row.category != HubSpotAssociationErrorCategory.OBJECT_NOT_FOUND
            or row.subCategory != HubSpotAssociationErrorSubcategory.NO_ASSOCIATIONS
        ):
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_BATCH_PARTIAL,
                "HubSpot returned an incomplete association batch.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        context = row.context
        if context is None:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
                "HubSpot omitted association error context.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        source_ids = _context_values(
            context.fromObjectId,
            field="HubSpot association error source IDs",
        )
        from_types = _context_values(
            context.fromObjectType,
            field="HubSpot association error source types",
        )
        to_types = _context_values(
            context.toObjectType,
            field="HubSpot association error target types",
        )
        if (
            not source_ids
            or not source_ids.issubset(pending_ids)
            or not _object_types_match(from_types, from_stream)
            or not _object_types_match(to_types, to_stream)
            or result & source_ids
        ):
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
                "HubSpot returned mismatched association error context.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        result.update(source_ids)
    return result


def _context_values(value: object, *, field: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            f"{field} are invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    values = frozenset(_required_id(item, field=field) for item in value)
    if len(values) != len(value):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            f"{field} contain duplicates.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return values


def _object_types_match(values: frozenset[str], stream: str) -> bool:
    singular = stream.removesuffix("s").casefold()
    normalized = frozenset(value.casefold() for value in values)
    return normalized in {frozenset({singular}), frozenset({stream.casefold()})}


def _required_id(value: object, *, field: str) -> str:
    normalized = _required_string(value, field=field)
    if len(normalized) > 320 or any(character in normalized for character in "/?#"):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            f"{field} is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return normalized


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
                "HubSpot returned an invalid timestamp.",
                recovery=SorRecoveryPolicy.TERMINAL,
            ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "HubSpot returned a timestamp without a timezone.",
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
            "HubSpot returned an invalid decimal value.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error


def _optional_date(value: object) -> date | None:
    normalized = _optional_string(value)
    if normalized is None:
        return None
    try:
        return date.fromisoformat(normalized[:10])
    except ValueError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "HubSpot returned an invalid date value.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "HubSpot returned an invalid relationship list.",
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
            "HubSpot returned too many relationships.",
            recovery=SorRecoveryPolicy.TERMINAL,
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
    "HubSpotAppWebhookDelivery",
    "HubSpotCrmAdapter",
    "create_hubspot_adapter",
    "parse_hubspot_app_webhook",
    "verify_hubspot_app_webhook",
]
