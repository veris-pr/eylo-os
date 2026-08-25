"""Durable work definition for verified SOR webhook receipts."""

from eylo.sor.runtime.work import SorWorkContract
from eylo.sor.shared.contracts import SorSourceState, SorWebhookReceiptState
from eylo.sor.shared.models import SorWebhookReceiptModel

SOR_WEBHOOK_WORKFLOW = "eylo.sor.process-webhook.v1"
SOR_WEBHOOK_SOURCE_STATES = frozenset(
    {SorSourceState.ACTIVE, SorSourceState.DEGRADED}
)
SOR_WEBHOOK_WORK = SorWorkContract(
    model=SorWebhookReceiptModel,
    pending=SorWebhookReceiptState.PENDING,
    running=SorWebhookReceiptState.PROCESSING,
    succeeded=SorWebhookReceiptState.SUCCEEDED,
    failed=SorWebhookReceiptState.FAILED,
    terminal=frozenset(
        {
            SorWebhookReceiptState.SUCCEEDED,
            SorWebhookReceiptState.FAILED,
            SorWebhookReceiptState.EXPIRED,
        }
    ),
    error_code_field="safe_error_code",
)

__all__ = [
    "SOR_WEBHOOK_SOURCE_STATES",
    "SOR_WEBHOOK_WORK",
    "SOR_WEBHOOK_WORKFLOW",
]
