"""Stripe read contracts pinned to 2026-08-26.dahlia; native data stays vendor-owned."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn, Self, overload

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ...contracts import VendorResponse, VendorToolError

MAX_PAGE_SIZE = 50
IDENTITY_PAGE_SIZE = 2
MAX_EMBEDDED_ITEMS = 100
MAX_TIMESTAMP = 253402300799
DECIMAL_PRECISION = 80


class StripeErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    IDENTITY_MISMATCH = "vendor_identity_mismatch"
    CUSTOMER_AMBIGUOUS = "customer_ambiguous"
    PAGINATION_INVALID = "vendor_pagination_invalid"


class ObjectKind(StrEnum):
    LIST = "list"
    CUSTOMER = "customer"
    CHARGE = "charge"
    PAYMENT_INTENT = "payment_intent"
    REFUND = "refund"
    INVOICE = "invoice"
    SUBSCRIPTION = "subscription"
    SUBSCRIPTION_ITEM = "subscription_item"
    PRICE = "price"
    PRODUCT = "product"


class ChargeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PENDING = "pending"
    FAILED = "failed"


class IntentStatus(StrEnum):
    REQUIRES_PAYMENT_METHOD = "requires_payment_method"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    REQUIRES_ACTION = "requires_action"
    PROCESSING = "processing"
    REQUIRES_CAPTURE = "requires_capture"
    CANCELED = "canceled"
    SUCCEEDED = "succeeded"


class RefundStatus(StrEnum):
    PENDING = "pending"
    REQUIRES_ACTION = "requires_action"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class RefundReason(StrEnum):
    DUPLICATE = "duplicate"
    FRAUDULENT = "fraudulent"
    REQUESTED_BY_CUSTOMER = "requested_by_customer"
    EXPIRED_UNCAPTURED_CHARGE = "expired_uncaptured_charge"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    UNCOLLECTIBLE = "uncollectible"
    VOID = "void"


class SubscriptionStatus(StrEnum):
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    PAUSED = "paused"


class SubscriptionFilter(StrEnum):
    NOT_CANCELED = "not_canceled"
    ALL = "all"
    ENDED = "ended"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    PAUSED = "paused"


class BillingScheme(StrEnum):
    PER_UNIT = "per_unit"
    TIERED = "tiered"


class PriceType(StrEnum):
    ONE_TIME = "one_time"
    RECURRING = "recurring"


class Interval(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class UsageType(StrEnum):
    LICENSED = "licensed"
    METERED = "metered"


class CustomerResolution(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    EXPLICIT_ID = "explicit_id"


class Extent(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


ResourceId = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,254}$")]
CustomerId = Annotated[str, Field(pattern=r"^cus_[A-Za-z0-9]+$")]
ChargeId = Annotated[str, Field(pattern=r"^(ch|py)_[A-Za-z0-9]+$")]
IntentId = Annotated[str, Field(pattern=r"^pi_[A-Za-z0-9]+$")]
PaymentId = Annotated[str, Field(pattern=r"^(ch|py|pi)_[A-Za-z0-9]+$")]
RefundId = Annotated[str, Field(pattern=r"^re_[A-Za-z0-9]+$")]
InvoiceId = Annotated[str, Field(pattern=r"^in_[A-Za-z0-9]+$")]
SubscriptionId = Annotated[str, Field(pattern=r"^sub_[A-Za-z0-9]+$")]
SubscriptionItemId = Annotated[str, Field(pattern=r"^si_[A-Za-z0-9]+$")]
Currency = Annotated[str, Field(pattern=r"^[a-z]{3}$")]
Epoch = Annotated[int, Field(ge=0, le=MAX_TIMESTAMP)]
Amount = Annotated[int, Field(ge=0)]


def email_text(value: str) -> str:
    text = value.strip()
    if not text or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError("Supply a nonempty email without control characters.")
    return text


Email = Annotated[str, Field(max_length=512), AfterValidator(email_text)]


def decimal_text(value: str) -> str:
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("Expected decimal minor units.") from None
    if not number.is_finite() or number < 0:
        raise ValueError("Expected finite nonnegative minor units.")
    return value


DecimalAmount = Annotated[
    str,
    Field(max_length=64, pattern=r"^[0-9]+(?:\.[0-9]{1,12})?$"),
    AfterValidator(decimal_text),
]


class StripeModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class StripeRequest(StripeModel):
    model_config = ConfigDict(extra="forbid")


class FindCustomerInput(StripeRequest):
    email: Email
    starting_after: CustomerId | None = None
    limit: int = Field(default=10, ge=1, le=MAX_PAGE_SIZE)


class CustomerSelection(StripeRequest):
    customer_email: Email | None = None
    customer_id: CustomerId | None = None
    limit: int = Field(default=10, ge=1, le=MAX_PAGE_SIZE)

    @model_validator(mode="after")
    def one_customer(self) -> Self:
        if (self.customer_email is None) == (self.customer_id is None):
            raise ValueError("Choose customer_email or customer_id.")
        return self


class ListPaymentsInput(CustomerSelection):
    starting_after: ChargeId | None = None


class ListInvoicesInput(CustomerSelection):
    starting_after: InvoiceId | None = None


class ListSubscriptionsInput(CustomerSelection):
    starting_after: SubscriptionId | None = None
    status: Annotated[
        SubscriptionFilter, BeforeValidator(lambda value: SubscriptionFilter(value))
    ] = SubscriptionFilter.NOT_CANCELED
    include_cancelled: bool | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated: use status=all or status=not_canceled. Cannot combine with status.",
    )
    subscription_id: SubscriptionId | None = Field(
        default=None,
        description="Read one subscription and continue its items, keeping the customer selector.",
    )
    items_starting_after: SubscriptionItemId | None = None

    @model_validator(mode="after")
    def valid_continuation(self) -> Self:
        if self.include_cancelled is not None and "status" in self.model_fields_set:
            raise ValueError("Choose status or include_cancelled, not both.")
        if self.items_starting_after is not None and self.subscription_id is None:
            raise ValueError("items_starting_after requires subscription_id.")
        if self.subscription_id is not None and (
            self.starting_after is not None
            or "status" in self.model_fields_set
            or self.include_cancelled is not None
        ):
            raise ValueError(
                "Single-subscription continuation cannot use list status/cursor filters."
            )
        return self

    @property
    def effective_status(self) -> SubscriptionFilter:
        return SubscriptionFilter.ALL if self.include_cancelled is True else self.status


class GetPaymentInput(StripeRequest):
    payment_id: PaymentId = Field(
        description="PaymentIntent pi_ ID or charge ch_/py_ ID."
    )
    refunds_starting_after: RefundId | None = None
    refunds_limit: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)


class ListQuery(StripeRequest):
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    starting_after: ResourceId | None = None


class CustomerQuery(ListQuery):
    email: Email


class CustomerResourceQuery(ListQuery):
    customer: CustomerId


class SubscriptionQuery(CustomerResourceQuery):
    status: SubscriptionFilter | None = None


class SubscriptionItemsQuery(ListQuery):
    subscription: SubscriptionId


class RefundQuery(ListQuery):
    charge: ChargeId | None = None
    payment_intent: IntentId | None = None


class CustomerIdentity(StripeModel):
    id: CustomerId
    object: Literal[ObjectKind.CUSTOMER]


CustomerRef = CustomerId | CustomerIdentity


class Customer(CustomerIdentity):
    created: Epoch
    email: str | None = None
    name: str | None = None
    balance: int | None = None
    currency: Currency | None = None
    delinquent: bool | None = None


class Resource(StripeModel):
    id: ResourceId


class StripeList[T](StripeModel):
    object: Literal[ObjectKind.LIST]
    data: list[T]
    has_more: bool
    url: str


class Card(StripeModel):
    last4: str | None = Field(default=None, pattern=r"^[0-9]{4}$")


class PaymentMethodDetails(StripeModel):
    card: Card | None = None


class Charge(Resource):
    id: ChargeId
    object: Literal[ObjectKind.CHARGE]
    amount: Amount
    amount_captured: Amount
    amount_refunded: Amount
    currency: Currency
    created: Epoch
    customer: CustomerRef | None = None
    status: Annotated[ChargeStatus, BeforeValidator(lambda value: ChargeStatus(value))]
    paid: bool
    refunded: bool
    description: str | None = None
    failure_message: str | None = None
    receipt_url: str | None = None
    payment_method_details: PaymentMethodDetails | None = None
    payment_intent: IntentId | None = None


class PaymentError(StripeModel):
    message: str | None = None
    code: str | None = None


class PaymentIntent(Resource):
    id: IntentId
    object: Literal[ObjectKind.PAYMENT_INTENT]
    created: Epoch
    status: Annotated[IntentStatus, BeforeValidator(lambda value: IntentStatus(value))]
    amount: Amount
    amount_received: Amount
    currency: Currency
    customer: CustomerRef | None = None
    description: str | None = None
    last_payment_error: PaymentError | None = None
    latest_charge: ChargeId | Charge | None = None


class Refund(Resource):
    id: RefundId
    object: Literal[ObjectKind.REFUND]
    amount: Amount
    currency: Currency
    created: Epoch
    charge: ChargeId | None = None
    payment_intent: IntentId | None = None
    status: (
        Annotated[RefundStatus, BeforeValidator(lambda value: RefundStatus(value))]
        | None
    ) = None
    reason: (
        Annotated[RefundReason, BeforeValidator(lambda value: RefundReason(value))]
        | None
    ) = None


class Invoice(Resource):
    id: InvoiceId
    object: Literal[ObjectKind.INVOICE]
    customer: CustomerRef
    currency: Currency
    total: int
    amount_due: int
    amount_paid: Amount
    created: Epoch
    number: str | None = None
    status: (
        Annotated[InvoiceStatus, BeforeValidator(lambda value: InvoiceStatus(value))]
        | None
    ) = None
    due_date: Epoch | None = None
    hosted_invoice_url: str | None = None
    invoice_pdf: str | None = None


class Recurring(StripeModel):
    interval: Annotated[Interval, BeforeValidator(lambda value: Interval(value))]
    interval_count: int = Field(ge=1)
    usage_type: Annotated[UsageType, BeforeValidator(lambda value: UsageType(value))]


class ProductIdentity(Resource):
    object: Literal[ObjectKind.PRODUCT]


class Price(Resource):
    object: Literal[ObjectKind.PRICE]
    currency: Currency
    billing_scheme: Annotated[
        BillingScheme, BeforeValidator(lambda value: BillingScheme(value))
    ]
    type: Annotated[PriceType, BeforeValidator(lambda value: PriceType(value))]
    product: ResourceId | ProductIdentity
    nickname: str | None = None
    unit_amount: Amount | None = None
    unit_amount_decimal: DecimalAmount | None = None
    recurring: Recurring | None = None


class SubscriptionItem(Resource):
    id: SubscriptionItemId
    object: Literal[ObjectKind.SUBSCRIPTION_ITEM]
    subscription: SubscriptionId
    price: Price
    quantity: int | None = Field(default=None, ge=0)
    current_period_start: Epoch
    current_period_end: Epoch


class Subscription(Resource):
    id: SubscriptionId
    object: Literal[ObjectKind.SUBSCRIPTION]
    customer: CustomerRef
    status: Annotated[
        SubscriptionStatus, BeforeValidator(lambda value: SubscriptionStatus(value))
    ]
    items: StripeList[SubscriptionItem]
    cancel_at_period_end: bool
    cancel_at: Epoch | None = None
    canceled_at: Epoch | None = None
    trial_end: Epoch | None = None


class CustomerMatch(StripeModel):
    id: str | None
    resolution: CustomerResolution


class MoneyView(StripeModel):
    value: str | None
    currency: str | None
    minor_units: str
    extent: Extent


class CustomerView(StripeModel):
    id: str
    name: str | None
    email: str | None
    balance: MoneyView | None
    delinquent: bool | None
    created_at: str


class CustomerListView(StripeModel):
    customers: list[CustomerView]
    count: int
    next_starting_after: str | None


class ChargeView(StripeModel):
    id: str
    payment_intent_id: str | None
    amount: MoneyView
    amount_captured: MoneyView
    amount_refunded: MoneyView
    status: ChargeStatus
    paid: bool
    refunded: bool
    description: str | None
    failure_message: str | None
    card_last4: str | None
    receipt_url: str | None
    created_at: str


class InvoiceView(StripeModel):
    id: str
    number: str | None
    status: InvoiceStatus | None
    total: MoneyView
    amount_due: MoneyView
    amount_paid: MoneyView
    due_at: str | None
    created_at: str
    hosted_url: str | None
    pdf_url: str | None


class SubscriptionItemView(StripeModel):
    id: str
    price_id: str
    product_id: str
    nickname: str | None
    billing_scheme: BillingScheme
    unit_amount: MoneyView | None
    recurring: Recurring | None
    quantity: int | None
    current_period_start: str
    current_period_end: str


class SubscriptionView(StripeModel):
    id: str
    status: SubscriptionStatus
    items: list[SubscriptionItemView]
    items_extent: Extent
    next_items_starting_after: str | None
    cancel_at_period_end: bool
    cancel_at: str | None
    cancelled_at: str | None
    trial_ends_at: str | None


class CustomerResultPage(StripeModel):
    customer_id: str | None
    customer_resolution: CustomerResolution
    count: int
    next_starting_after: str | None


class PaymentsView(CustomerResultPage):
    payments: list[ChargeView]


class InvoicesView(CustomerResultPage):
    invoices: list[InvoiceView]


class SubscriptionsView(CustomerResultPage):
    subscriptions: list[SubscriptionView]


class RefundView(StripeModel):
    id: str
    amount: MoneyView
    status: RefundStatus | None
    reason: RefundReason | None
    created_at: str


class PaymentView(StripeModel):
    id: str
    kind: ObjectKind
    amount: MoneyView
    amount_received: MoneyView
    status: ChargeStatus | IntentStatus
    customer_id: str | None
    description: str | None
    created_at: str
    failure_reason: str | None
    receipt_url: str | None
    latest_charge_id: str | None
    refunds: list[RefundView]
    refunds_extent: Extent
    next_refunds_starting_after: str | None
    fully_refunded: bool | None


CUSTOMERS = TypeAdapter(StripeList[Customer])
CHARGES = TypeAdapter(StripeList[Charge])
CHARGE = TypeAdapter(Charge)
INTENT = TypeAdapter(PaymentIntent)
REFUNDS = TypeAdapter(StripeList[Refund])
INVOICES = TypeAdapter(StripeList[Invoice])
SUBSCRIPTIONS = TypeAdapter(StripeList[Subscription])
SUBSCRIPTION = TypeAdapter(Subscription)
SUBSCRIPTION_ITEMS = TypeAdapter(StripeList[SubscriptionItem])


def invalid_response() -> NoReturn:
    raise VendorToolError(
        StripeErrorCode.RESPONSE_INVALID,
        "Stripe returned an invalid response for this operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if response.status_code != HTTPStatus.OK:
        raise VendorToolError(
            StripeErrorCode.REJECTED, "Stripe rejected the read request."
        )
    try:
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        return invalid_response()


def next_cursor[T](
    page: StripeList[T], identities: list[str], previous: str | None, limit: int
) -> str | None:
    if (
        len(identities) > limit
        or len(set(identities)) != len(identities)
        or previous in identities
    ):
        invalid_response()
    if page.has_more:
        if not identities:
            raise VendorToolError(
                StripeErrorCode.PAGINATION_INVALID,
                "Stripe returned a non-progressing page.",
            )
        return identities[-1]
    return None


def customer_identity(value: CustomerRef | None) -> str | None:
    return value.id if isinstance(value, CustomerIdentity) else value


@overload
def moment(value: int) -> str: ...


@overload
def moment(value: None) -> None: ...


def moment(value: int | None) -> str | None:
    return (
        datetime.fromtimestamp(value, tz=UTC).isoformat() if value is not None else None
    )


# Stripe's API exponent differs from ISO display precision for ISK and UGX.
ZERO_DECIMAL = frozenset(
    "bif clp djf gnf jpy kmf krw mga pyg rwf vnd vuv xaf xof xpf".split()
)
THREE_DECIMAL = frozenset("bhd jod kwd omr tnd".split())
TWO_DECIMAL = frozenset(
    "usd aed afn all amd ang aoa ars aud awg azn bam bbd bdt bmd bnd bob brl bsd bwp byn bzd cad cdf chf cny cop crc cve czk dkk dop dzd egp etb eur fjd fkp gbp gel gip gmd gtq gyd hkd hnl htg huf idr ils inr isk jmd kes kgs khr kyd kzt lak lbp lkr lrd lsl mad mdl mkd mmk mnt mop mur mvr mwk mxn myr mzn nad ngn nio nok npr nzd pab pen pgk php pkr pln qar ron rsd rub sar sbd scr sek sgd shp sle sll sos srd std stn szl thb tjs top try ttd twd tzs uah ugx uyu uzs wst xcd xcg yer zar zmw".split()
)


def money(amount: int | str, currency: str | None) -> MoneyView:
    exponent = (
        0
        if currency in ZERO_DECIMAL
        else 3
        if currency in THREE_DECIMAL
        else 2
        if currency in TWO_DECIMAL
        else None
    )
    if exponent is None or currency is None:
        return MoneyView(
            value=None,
            currency=currency.upper() if currency else None,
            minor_units=str(amount),
            extent=Extent.UNAVAILABLE,
        )
    with localcontext() as context:
        context.prec = max(DECIMAL_PRECISION, len(str(amount)) + exponent)
        value = Decimal(amount).scaleb(-exponent)
        rendered = format(value, "f")
    return MoneyView(
        value=rendered,
        currency=currency.upper(),
        minor_units=str(amount),
        extent=Extent.COMPLETE,
    )
