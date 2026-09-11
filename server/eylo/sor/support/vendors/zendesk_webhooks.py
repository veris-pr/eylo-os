"""Zendesk Webhooks API request/response metadata; secrets never enter snapshots."""

import json
from enum import StrEnum
from http import HTTPMethod

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)

ZENDESK_WEBHOOK_PAGE_SIZE = 100
ZENDESK_WEBHOOK_SIGNATURE_HEADER = "x-zendesk-webhook-signature"
ZENDESK_WEBHOOK_TIMESTAMP_HEADER = "x-zendesk-webhook-signature-timestamp"
ZENDESK_WEBHOOK_DELIVERY_HEADER = "x-zendesk-webhook-invocation-id"
ZENDESK_WEBHOOK_TICKET_SUBJECT_PREFIX = "zen:ticket:"
ZENDESK_WEBHOOK_UNSPECIFIED_EVENT = "zendesk.ticket.changed"


class ZendeskWebhookEvent(StrEnum):
    """Exact native event names requested by the current support adapter."""

    AGENT_ASSIGNMENT_CHANGED = "zen:event-type:ticket.agent_assignment_changed"
    BRAND_CHANGED = "zen:event-type:ticket.brand_changed"
    CREATED = "zen:event-type:ticket.created"
    CUSTOM_FIELD_CHANGED = "zen:event-type:ticket.custom_field_changed"
    CUSTOM_STATUS_CHANGED = "zen:event-type:ticket.custom_status_changed"
    DESCRIPTION_CHANGED = "zen:event-type:ticket.description_changed"
    EXTERNAL_ID_CHANGED = "zen:event-type:ticket.external_id_changed"
    FORM_CHANGED = "zen:event-type:ticket.form_changed"
    GROUP_ASSIGNMENT_CHANGED = "zen:event-type:ticket.group_assignment_changed"
    MARKED_AS_SPAM = "zen:event-type:ticket.marked_as_spam"
    MERGED = "zen:event-type:ticket.merged"
    ORGANIZATION_CHANGED = "zen:event-type:ticket.organization_changed"
    PERMANENTLY_DELETED = "zen:event-type:ticket.permanently_deleted"
    PRIORITY_CHANGED = "zen:event-type:ticket.priority_changed"
    PROBLEM_LINK_CHANGED = "zen:event-type:ticket.problem_link_changed"
    REQUESTER_CHANGED = "zen:event-type:ticket.requester_changed"
    SOFT_DELETED = "zen:event-type:ticket.soft_deleted"
    STATUS_CHANGED = "zen:event-type:ticket.status_changed"
    SUBJECT_CHANGED = "zen:event-type:ticket.subject_changed"
    SUBMITTER_CHANGED = "zen:event-type:ticket.submitter_changed"
    TAGS_CHANGED = "zen:event-type:ticket.tags_changed"
    TASK_DUE_AT_CHANGED = "zen:event-type:ticket.task_due_at_changed"
    TYPE_CHANGED = "zen:event-type:ticket.type_changed"
    UNDELETED = "zen:event-type:ticket.undeleted"
    COMMENT_ADDED = "zen:event-type:ticket.comment_added"
    COMMENT_MADE_PRIVATE = "zen:event-type:ticket.comment_made_private"
    COMMENT_REDACTED = "zen:event-type:ticket.comment_redacted"
    ATTACHMENT_LINKED_TO_COMMENT = "zen:event-type:ticket.attachment_linked_to_comment"
    ATTACHMENT_REDACTED_FROM_COMMENT = (
        "zen:event-type:ticket.attachment_redacted_from_comment"
    )
    NEXT_SLA_BREACH_CHANGED = "zen:event-type:ticket.next_sla_breach_changed"
    SCHEDULE_CHANGED = "zen:event-type:ticket.schedule_changed"
    SLA_POLICY_CHANGED = "zen:event-type:ticket.sla_policy_changed"


class ZendeskWebhookStatus(StrEnum):
    ACTIVE = "active"


class ZendeskWebhookRequestFormat(StrEnum):
    JSON = "json"


class ZendeskWebhookSigningAlgorithm(StrEnum):
    SHA256 = "SHA256"


class ZendeskWebhookWire(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


class ZendeskWebhookRecordReference(ZendeskWebhookWire):
    id: str | int | None = None


class ZendeskWebhookComment(ZendeskWebhookRecordReference):
    attachment: ZendeskWebhookRecordReference | None = None


class ZendeskWebhookEventData(ZendeskWebhookWire):
    comment: ZendeskWebhookComment | None = None


class ZendeskWebhookDelivery(ZendeskWebhookWire):
    """Native routing metadata, excluding comment text, attachments and customer PII."""

    id: str | None = None
    type: str | None = None
    subject: str | None = None
    time: str | None = None
    detail: ZendeskWebhookRecordReference | None = None
    event: ZendeskWebhookEventData | None = None


def parse_zendesk_webhook_body(body: bytes) -> ZendeskWebhookDelivery:
    """Authentication consumes original bytes first; decoding does not authorize a source."""
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_WEBHOOK_INVALID,
            "Zendesk webhook body is not valid JSON.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
    return parse_zendesk_webhook_response(value, ZendeskWebhookDelivery)


class ZendeskWebhookDetails(ZendeskWebhookWire):
    endpoint: str
    name: str
    subscriptions: tuple[ZendeskWebhookEvent, ...]
    http_method: HTTPMethod = HTTPMethod.POST
    request_format: ZendeskWebhookRequestFormat = ZendeskWebhookRequestFormat.JSON
    status: ZendeskWebhookStatus = ZendeskWebhookStatus.ACTIVE


class ZendeskWebhookCreateRequest(ZendeskWebhookWire):
    webhook: ZendeskWebhookDetails


class ZendeskWebhookListQuery(ZendeskWebhookWire):
    name_contains: str = Field(
        validation_alias=AliasChoices("name_contains", "filter[name_contains]"),
        serialization_alias="filter[name_contains]",
    )
    page_size: int = Field(
        default=ZENDESK_WEBHOOK_PAGE_SIZE,
        validation_alias=AliasChoices("page_size", "page[size]"),
        serialization_alias="page[size]",
    )


class ZendeskWebhookRecord(ZendeskWebhookWire):
    id: str | int | None = None
    name: str | None = None
    endpoint: str | None = None
    http_method: str | None = None
    request_format: str | None = None
    status: str | None = None
    subscriptions: list[str] | None = None


class ZendeskWebhookCreateResponse(ZendeskWebhookWire):
    webhook: ZendeskWebhookRecord


class ZendeskWebhookPagination(ZendeskWebhookWire):
    # Vendor pagination is an intrinsic predicate, not a platform state mode.
    has_more: bool | None = None


class ZendeskWebhookListResponse(ZendeskWebhookWire):
    webhooks: list[ZendeskWebhookRecord]
    meta: ZendeskWebhookPagination


class ZendeskWebhookSigningSecret(ZendeskWebhookWire):
    algorithm: str
    secret: str = Field(repr=False, exclude=True)


class ZendeskWebhookSigningResponse(ZendeskWebhookWire):
    signing_secret: ZendeskWebhookSigningSecret


def parse_zendesk_webhook_response[Model: ZendeskWebhookWire](
    value: object, model: type[Model]
) -> Model:
    """Keep remote response contents out of public errors and diagnostic summaries."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Zendesk webhook response metadata is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
