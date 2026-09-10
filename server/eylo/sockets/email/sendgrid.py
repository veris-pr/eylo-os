"""Asynchronous SendGrid Web API adapter."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from http import HTTPStatus
from typing import Protocol
from uuid import UUID

import httpx
from pydantic import JsonValue, ValidationError

from eylo.common.http_egress import (
    HttpDestinationPolicy,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpEgressResponse,
    HttpOrigin,
    HttpRoutePolicy,
    OriginBoundHeaders,
)
from eylo.common.outbound import (
    OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH,
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendRetryable,
    OutboundSendSucceeded,
    OutboundSendTerminal,
    OutboundSendUnknown,
    OutboundTransportKind,
)
from eylo.sockets.email.base import (
    EmailCapabilitySupport,
    EmailDeliveryCapabilities,
    EmailVendorAdapter,
    PlannedEmailDelivery,
)
from eylo.sockets.email.exceptions import EmailVendorError
from eylo.sockets.email.schemas import (
    EmailMessage,
    EmailPriority,
    EmailResponse,
    EmailStatus,
    EmailWebhookEvent,
    SendGridConfig,
)
from eylo.sockets.email.sendgrid_wire import (
    SENDGRID_MAIL_SEND_SCOPE,
    SendGridAddress,
    SendGridAttachment,
    SendGridContent,
    SendGridContentType,
    SendGridCustomArguments,
    SendGridEventKind,
    SendGridMailRequest,
    SendGridPersonalization,
    SendGridScopesResponse,
    SendGridWebhookPayload,
)
from eylo.sockets.http import SafeHttpTransport

logger = logging.getLogger(__name__)

_API_BASE = "https://api.sendgrid.com/v3"
_MAIL_SEND_URL = f"{_API_BASE}/mail/send"
_SEND_OPERATION = "email.send.sendgrid"
_RESPONSE_BODY_LIMIT_BYTES = 65_536
_SENDGRID_ORIGIN = HttpOrigin.parse("https://api.sendgrid.com")
_DELIVERY_CAPABILITIES = EmailDeliveryCapabilities(
    idempotent_send=EmailCapabilitySupport.UNSUPPORTED,
    reconciliation=EmailCapabilitySupport.UNSUPPORTED,
)
_DNS_FAILURES = frozenset({"dns_resolution_empty", "dns_resolution_failed"})


class SendGridFailureCode(StrEnum):
    """Safe adapter-owned failure values stored by the outbound ledger."""

    DNS_UNAVAILABLE = "sendgrid_dns_unavailable"
    TRANSPORT_UNCONFIRMED = "sendgrid_transport_unconfirmed"
    RESPONSE_UNCONFIRMED = "sendgrid_response_unconfirmed"
    EGRESS_REJECTED = "sendgrid_egress_rejected"
    TIMEOUT_UNCONFIRMED = "sendgrid_timeout_unconfirmed"
    RATE_LIMITED = "sendgrid_rate_limited"
    REQUEST_REJECTED = "sendgrid_request_rejected"


class SendGridHttpTransport(Protocol):
    async def send(self, request: HttpEgressRequest) -> HttpEgressResponse: ...


class SendGridAdapter(EmailVendorAdapter):
    def __init__(
        self,
        config: SendGridConfig,
        *,
        transport: SendGridHttpTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or SafeHttpTransport()

    def plan_delivery(
        self,
        message: EmailMessage,
        *,
        attempt_id: UUID,
    ) -> PlannedEmailDelivery:
        body = json.dumps(
            _sendgrid_payload(message, attempt_id=attempt_id).model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        request = HttpEgressRequest(
            method="POST",
            url=_MAIL_SEND_URL,
            policy=HttpDestinationPolicy(
                primary=HttpRoutePolicy(
                    origin=_SENDGRID_ORIGIN,
                    path_prefix="/v3/mail/send",
                ),
                max_redirects=0,
            ),
            headers={"Content-Type": "application/json"},
            origin_headers=OriginBoundHeaders(
                origin=_SENDGRID_ORIGIN,
                values={
                    "Authorization": (
                        f"Bearer {self.config.api_key.get_secret_value()}"
                    )
                },
            ),
            body=body,
            response_body_limit=_RESPONSE_BODY_LIMIT_BYTES,
            total_timeout_seconds=self.config.timeout,
        )
        return PlannedEmailDelivery(
            attempt_id=attempt_id,
            provider_operation=_SEND_OPERATION,
            transport_kind=OutboundTransportKind.HTTP,
            destination_origin=str(_SENDGRID_ORIGIN),
            capabilities=_DELIVERY_CAPABILITIES,
            sender=lambda authorization: self._send_delivery(
                request,
                authorization=authorization,
            ),
        )

    async def _send_delivery(
        self,
        request: HttpEgressRequest,
        *,
        authorization: OutboundSendAuthorization,
    ) -> OutboundSendOutcome:
        del authorization
        try:
            response = await self._transport.send(request)
        except HttpEgressPolicyError as error:
            if error.code in _DNS_FAILURES:
                return OutboundSendRetryable(
                    failure_code=SendGridFailureCode.DNS_UNAVAILABLE
                )
            if error.code == "transport_failed":
                return OutboundSendUnknown(
                    failure_code=SendGridFailureCode.TRANSPORT_UNCONFIRMED
                )
            if error.code in {
                "response_body_too_large",
                "response_headers_too_large",
            }:
                return OutboundSendUnknown(
                    failure_code=SendGridFailureCode.RESPONSE_UNCONFIRMED
                )
            return OutboundSendTerminal(
                failure_code=SendGridFailureCode.EGRESS_REJECTED
            )
        except TimeoutError:
            return OutboundSendUnknown(
                failure_code=SendGridFailureCode.TIMEOUT_UNCONFIRMED
            )

        if response.status_code == HTTPStatus.ACCEPTED:
            return OutboundSendSucceeded(
                provider_reference=_message_id(response),
                status_code=response.status_code,
            )
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            return OutboundSendRetryable(
                failure_code=SendGridFailureCode.RATE_LIMITED,
                status_code=response.status_code,
            )
        if (
            response.status_code == HTTPStatus.REQUEST_TIMEOUT
            or response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
        ):
            return OutboundSendUnknown(
                failure_code=SendGridFailureCode.RESPONSE_UNCONFIRMED,
                status_code=response.status_code,
            )
        return OutboundSendTerminal(
            failure_code=SendGridFailureCode.REQUEST_REJECTED,
            status_code=response.status_code,
        )

    async def verify_credentials(self) -> None:
        try:
            async with self._client() as client:
                response = await client.get(f"{_API_BASE}/scopes")
                response.raise_for_status()
                payload = SendGridScopesResponse.model_validate_json(response.content)
            if SENDGRID_MAIL_SEND_SCOPE not in payload.scopes:
                raise EmailVendorError("SendGrid key does not grant mail.send.")
        except Exception as error:
            _log_failure("verify", error)
            raise EmailVendorError("SendGrid credential verification failed.") from None

    def transform_to_platform_response(
        self,
        vendor_response: object,
        original_message: EmailMessage,
    ) -> EmailResponse:
        if not isinstance(vendor_response, (httpx.Response, HttpEgressResponse)):
            raise EmailVendorError("SendGrid response must be an HTTP response.")
        status_code = vendor_response.status_code
        message_id = (
            _message_id(vendor_response)
            if isinstance(vendor_response, HttpEgressResponse)
            else vendor_response.headers.get("X-Message-Id")
        )
        return EmailResponse(
            message_id=message_id or "",
            status=(
                EmailStatus.SENT
                if status_code == HTTPStatus.ACCEPTED
                else EmailStatus.FAILED
            ),
            vendor="sendgrid",
            to=original_message.to,
            subject=original_message.subject,
            metadata={"status_code": status_code},
        )

    async def process_webhook(
        self, payload: Mapping[str, JsonValue]
    ) -> EmailWebhookEvent:
        try:
            event = SendGridWebhookPayload.model_validate(dict(payload))
            return EmailWebhookEvent(
                event_type=_event_status(event.event),
                message_id=event.sg_message_id,
                email=event.email,
                timestamp=datetime.fromtimestamp(
                    event.timestamp,
                    tz=timezone.utc,
                ),
                vendor="sendgrid",
                reason=event.reason,
                metadata=event.model_dump(mode="json", exclude_unset=True),
            )
        except (ValidationError, ValueError, OverflowError, OSError):
            raise EmailVendorError("SendGrid webhook payload is invalid.") from None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout),
            trust_env=False,
            headers={
                "Authorization": (f"Bearer {self.config.api_key.get_secret_value()}"),
                "Content-Type": "application/json",
            },
        )


def _sendgrid_payload(
    message: EmailMessage,
    *,
    attempt_id: UUID,
) -> SendGridMailRequest:
    headers = dict(message.headers or {})
    priority_header = _priority_header(message.priority)
    if priority_header is not None:
        headers["X-Priority"] = priority_header
    personalization = SendGridPersonalization(
        to=tuple(SendGridAddress(email=address) for address in message.to),
        custom_args=SendGridCustomArguments(eylo_attempt_id=attempt_id.hex),
        cc=tuple(SendGridAddress(email=address) for address in message.cc)
        if message.cc
        else None,
        bcc=tuple(SendGridAddress(email=address) for address in message.bcc)
        if message.bcc
        else None,
        headers=headers or None,
    )
    content: list[SendGridContent] = []
    if message.text_content:
        content.append(
            SendGridContent(type=SendGridContentType.TEXT, value=message.text_content)
        )
    if message.html_content:
        content.append(
            SendGridContent(type=SendGridContentType.HTML, value=message.html_content)
        )

    return SendGridMailRequest(
        personalizations=(personalization,),
        sender=SendGridAddress(email=message.from_email, name=message.from_name),
        subject=message.subject,
        content=tuple(content),
        reply_to=SendGridAddress(email=message.reply_to) if message.reply_to else None,
        attachments=tuple(
            SendGridAttachment(
                content=attachment.content,
                filename=attachment.filename,
                type=attachment.content_type,
            )
            for attachment in message.attachments
        )
        if message.attachments
        else None,
    )


def _priority_header(priority: EmailPriority) -> str | None:
    return {
        EmailPriority.HIGH: "1",
        EmailPriority.NORMAL: None,
        EmailPriority.LOW: "5",
    }[priority]


def _event_status(event: SendGridEventKind) -> EmailStatus:
    return {
        SendGridEventKind.DELIVERED: EmailStatus.DELIVERED,
        SendGridEventKind.BOUNCE: EmailStatus.BOUNCED,
        SendGridEventKind.DROPPED: EmailStatus.REJECTED,
        SendGridEventKind.DEFERRED: EmailStatus.PENDING,
        SendGridEventKind.PROCESSED: EmailStatus.SENT,
        SendGridEventKind.OPEN: EmailStatus.OPENED,
        SendGridEventKind.CLICK: EmailStatus.CLICKED,
    }.get(event, EmailStatus.PENDING)


def _message_id(response: HttpEgressResponse) -> str | None:
    values = response.header_values("x-message-id")
    if len(values) != 1:
        return None
    value = values[0].strip()
    return value if 0 < len(value) <= OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH else None


def _log_failure(operation: str, error: Exception) -> None:
    status_code = (
        error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
    )
    logger.warning(
        "SendGrid request failed operation=%s category=%s status=%s",
        operation,
        type(error).__name__,
        status_code,
    )
