"""Certificate-validating authenticated SMTP adapter."""

from __future__ import annotations

import asyncio
import base64
import logging
import socket
import ssl
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from email.message import EmailMessage as MIMEMessage
from email.utils import formataddr
from enum import Enum, StrEnum
from ipaddress import ip_address
from typing import Literal
from uuid import UUID

import aiosmtplib
from aiosmtplib.errors import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPConnectResponseError,
    SMTPNotSupported,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPTimeoutError,
)
from pydantic import JsonValue

from eylo.common.http_egress import MAX_REQUEST_BODY_BYTES
from eylo.common.outbound import (
    OUTBOUND_STATUS_CODE_MAX,
    OUTBOUND_STATUS_CODE_MIN,
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
from eylo.sockets.email.exceptions import (
    EmailConfigurationError,
    EmailVendorError,
)
from eylo.sockets.email.schemas import (
    EmailMessage,
    EmailPriority,
    EmailResponse,
    EmailStatus,
    EmailWebhookEvent,
    SMTPConfig,
)

logger = logging.getLogger(__name__)
_DELIVERY_CAPABILITIES = EmailDeliveryCapabilities(
    idempotent_send=EmailCapabilitySupport.UNSUPPORTED,
    reconciliation=EmailCapabilitySupport.UNSUPPORTED,
)
_SMTP_TEMPORARY_RESPONSE_MIN = 400
_SMTP_TEMPORARY_RESPONSE_MAX = 499
_SMTP_SEND_OPERATION = "email.send.smtp"


class SMTPFailureCode(StrEnum):
    """Adapter-owned safe categories; never expose native reply text."""

    TEMPORARY_REJECTION = "smtp_temporary_rejection"
    PERMANENT_REJECTION = "smtp_permanent_rejection"
    PARTIAL_ACCEPTANCE = "smtp_partial_acceptance"
    OPERATION_UNSUPPORTED = "smtp_operation_unsupported"
    DELIVERY_UNCONFIRMED = "smtp_delivery_unconfirmed"
    AUTHENTICATION_REJECTED = "smtp_authentication_rejected"
    CONFIGURATION_REJECTED = "smtp_configuration_rejected"
    CONNECTION_UNAVAILABLE = "smtp_connection_unavailable"
    PREFLIGHT_FAILED = "smtp_preflight_failed"
    DNS_UNAVAILABLE = "smtp_dns_unavailable"
    DESTINATION_REJECTED = "smtp_destination_rejected"


class SMTPDeliveryPhase(Enum):
    PREFLIGHT = "preflight"
    SENDING = "sending"


class _SMTPPrewireError(Exception):
    """Safe category for a failure known to precede MAIL/RCPT/DATA."""

    def __init__(
        self,
        code: Literal[
            SMTPFailureCode.DNS_UNAVAILABLE,
            SMTPFailureCode.DESTINATION_REJECTED,
            SMTPFailureCode.CONNECTION_UNAVAILABLE,
        ],
    ) -> None:
        self.code = code
        super().__init__(code.value)


class SMTPAdapter(EmailVendorAdapter):
    def __init__(self, config: SMTPConfig) -> None:
        self.config = config

    def plan_delivery(
        self,
        message: EmailMessage,
        *,
        attempt_id: UUID,
    ) -> PlannedEmailDelivery:
        mime_message = _to_mime_message(message, attempt_id=attempt_id)
        if len(mime_message.as_bytes()) > MAX_REQUEST_BODY_BYTES:
            raise EmailConfigurationError(
                "Serialized email exceeds the outbound delivery limit."
            )
        recipients = [
            str(address)
            for address in [*message.to, *(message.cc or []), *(message.bcc or [])]
        ]
        return PlannedEmailDelivery(
            attempt_id=attempt_id,
            provider_operation=_SMTP_SEND_OPERATION,
            transport_kind=OutboundTransportKind.PROVIDER_SDK,
            destination_origin=(
                f"smtp+{self.config.smtp_security}://"
                f"{self.config.smtp_host}:{self.config.smtp_port}"
            ),
            capabilities=_DELIVERY_CAPABILITIES,
            sender=lambda authorization: self._send_delivery(
                mime_message,
                recipients,
                envelope_sender=str(message.from_email),
                authorization=authorization,
            ),
        )

    async def _send_delivery(
        self,
        mime_message: MIMEMessage,
        recipients: list[str],
        *,
        envelope_sender: str,
        authorization: OutboundSendAuthorization,
    ) -> OutboundSendOutcome:
        del authorization
        outcome: OutboundSendOutcome | None = None
        phase = SMTPDeliveryPhase.PREFLIGHT
        try:
            async with asyncio.timeout(self.config.timeout):
                async with _authenticated_client(self.config) as client:
                    phase = SMTPDeliveryPhase.SENDING
                    outcome = await _send_connected(
                        client,
                        mime_message,
                        recipients,
                        envelope_sender=envelope_sender,
                    )
        except Exception as error:
            if outcome is not None:
                return outcome
            _log_failure("send", error)
            if phase is SMTPDeliveryPhase.SENDING:
                return OutboundSendUnknown(
                    failure_code=SMTPFailureCode.DELIVERY_UNCONFIRMED
                )
            return _prewire_outcome(error)
        assert outcome is not None
        return outcome

    async def verify_credentials(self) -> None:
        try:
            async with asyncio.timeout(self.config.timeout):
                async with _authenticated_client(self.config):
                    pass
        except Exception as error:
            _log_failure("verify", error)
            raise EmailVendorError("SMTP credential verification failed.") from None

    def transform_to_platform_response(
        self,
        vendor_response: object,
        original_message: EmailMessage,
    ) -> EmailResponse:
        if not isinstance(vendor_response, str):
            raise EmailVendorError("SMTP response must be a message reference.")
        return EmailResponse(
            message_id=vendor_response,
            status=EmailStatus.SENT,
            vendor="smtp",
            to=original_message.to,
            subject=original_message.subject,
        )

    async def process_webhook(
        self, payload: Mapping[str, JsonValue]
    ) -> EmailWebhookEvent:
        raise EmailVendorError("SMTP adapter does not support webhooks.")


def _to_mime_message(
    message: EmailMessage,
    *,
    attempt_id: UUID,
) -> MIMEMessage:
    mime_message = MIMEMessage()
    mime_message["Message-ID"] = _message_id(attempt_id)
    mime_message["Subject"] = message.subject
    mime_message["From"] = formataddr((message.from_name, str(message.from_email)))
    mime_message["To"] = ", ".join(str(address) for address in message.to)
    if message.cc:
        mime_message["Cc"] = ", ".join(str(address) for address in message.cc)
    if message.reply_to:
        mime_message["Reply-To"] = str(message.reply_to)
    for name, value in (message.headers or {}).items():
        mime_message[name] = value
    priority_header = _priority_header(message.priority)
    if priority_header is not None:
        mime_message["X-Priority"] = priority_header

    if message.text_content:
        mime_message.set_content(message.text_content)
        if message.html_content:
            mime_message.add_alternative(message.html_content, subtype="html")
    else:
        assert message.html_content is not None
        mime_message.set_content(message.html_content, subtype="html")

    for attachment in message.attachments or []:
        try:
            content = base64.b64decode(attachment.content, validate=True)
        except ValueError:
            raise EmailConfigurationError(
                f"Attachment {attachment.filename} is not valid base64."
            ) from None
        main_type, sub_type = attachment.content_type.split("/", maxsplit=1)
        mime_message.add_attachment(
            content,
            maintype=main_type,
            subtype=sub_type,
            filename=attachment.filename,
        )
    return mime_message


async def _send_connected(
    client: aiosmtplib.SMTP,
    mime_message: MIMEMessage,
    recipients: list[str],
    *,
    envelope_sender: str,
) -> OutboundSendOutcome:
    try:
        refused, _ = await client.send_message(
            mime_message,
            sender=envelope_sender,
            recipients=recipients,
        )
        if refused:
            # The SDK returns normally when at least one recipient accepted DATA.
            # Replaying the whole envelope would duplicate the accepted recipients.
            return OutboundSendUnknown(failure_code=SMTPFailureCode.PARTIAL_ACCEPTANCE)
    except SMTPRecipientsRefused as error:
        codes = [recipient.code for recipient in error.recipients]
        if codes and all(_is_temporary_response(code) for code in codes):
            return OutboundSendRetryable(
                failure_code=SMTPFailureCode.TEMPORARY_REJECTION
            )
        return OutboundSendTerminal(failure_code=SMTPFailureCode.PERMANENT_REJECTION)
    except SMTPResponseException as error:
        return _smtp_response_outcome(error.code)
    except SMTPNotSupported:
        return OutboundSendTerminal(failure_code=SMTPFailureCode.OPERATION_UNSUPPORTED)
    except Exception:
        return OutboundSendUnknown(failure_code=SMTPFailureCode.DELIVERY_UNCONFIRMED)
    return OutboundSendSucceeded(provider_reference=str(mime_message["Message-ID"]))


def _prewire_outcome(error: Exception) -> OutboundSendOutcome:
    if isinstance(error, _SMTPPrewireError):
        if error.code is SMTPFailureCode.DESTINATION_REJECTED:
            return OutboundSendTerminal(failure_code=error.code)
        return OutboundSendRetryable(failure_code=error.code)
    if isinstance(error, SMTPAuthenticationError):
        return OutboundSendTerminal(
            failure_code=SMTPFailureCode.AUTHENTICATION_REJECTED
        )
    if isinstance(error, SMTPConnectResponseError):
        return _smtp_response_outcome(error.code)
    if isinstance(error, (SMTPNotSupported, ssl.SSLError, ValueError)):
        return OutboundSendTerminal(failure_code=SMTPFailureCode.CONFIGURATION_REJECTED)
    if isinstance(
        error,
        (SMTPConnectError, SMTPTimeoutError, TimeoutError, ConnectionError, OSError),
    ):
        return OutboundSendRetryable(
            failure_code=SMTPFailureCode.CONNECTION_UNAVAILABLE
        )
    return OutboundSendRetryable(failure_code=SMTPFailureCode.PREFLIGHT_FAILED)


def _is_temporary_response(code: int) -> bool:
    return _SMTP_TEMPORARY_RESPONSE_MIN <= code <= _SMTP_TEMPORARY_RESPONSE_MAX


def _smtp_response_outcome(code: int) -> OutboundSendOutcome:
    if _is_temporary_response(code):
        return OutboundSendRetryable(
            failure_code=SMTPFailureCode.TEMPORARY_REJECTION,
            status_code=code,
        )
    return OutboundSendTerminal(
        failure_code=SMTPFailureCode.PERMANENT_REJECTION,
        status_code=code
        if OUTBOUND_STATUS_CODE_MIN <= code <= OUTBOUND_STATUS_CODE_MAX
        else None,
    )


def _message_id(attempt_id: UUID) -> str:
    return f"<eylo.{attempt_id.hex}@id.eylo.ai>"


@asynccontextmanager
async def _authenticated_client(config: SMTPConfig) -> AsyncIterator[aiosmtplib.SMTP]:
    connected_socket = await _connect_public_socket(
        config.smtp_host,
        config.smtp_port,
    )
    implicit_tls = config.smtp_security == "implicit_tls"
    client: aiosmtplib.SMTP | None = None
    try:
        client = aiosmtplib.SMTP(
            hostname=config.smtp_host,
            sock=connected_socket,
            timeout=config.timeout,
            use_tls=implicit_tls,
            start_tls=not implicit_tls,
            validate_certs=True,
        )
        async with client:
            await client.login(
                config.smtp_username,
                config.smtp_password.get_secret_value(),
            )
            yield client
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            connected_socket.close()


async def _connect_public_socket(host: str, port: int) -> socket.socket:
    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        raise _SMTPPrewireError(SMTPFailureCode.DNS_UNAVAILABLE) from None
    resolved = {ip_address(address[4][0]) for address in addresses}
    if not resolved or any(not address.is_global for address in resolved):
        raise _SMTPPrewireError(SMTPFailureCode.DESTINATION_REJECTED)

    for family, socket_type, protocol, _, socket_address in addresses:
        connected_socket = socket.socket(family, socket_type, protocol)
        try:
            connected_socket.setblocking(False)
            await loop.sock_connect(connected_socket, socket_address)
        except OSError:
            connected_socket.close()
            continue
        except BaseException:
            connected_socket.close()
            raise
        return connected_socket
    raise _SMTPPrewireError(SMTPFailureCode.CONNECTION_UNAVAILABLE)


def _priority_header(priority: EmailPriority) -> str | None:
    return {
        EmailPriority.HIGH: "1",
        EmailPriority.NORMAL: None,
        EmailPriority.LOW: "5",
    }[priority]


def _log_failure(operation: str, error: Exception) -> None:
    logger.warning(
        "SMTP request failed operation=%s category=%s",
        operation,
        type(error).__name__,
    )
