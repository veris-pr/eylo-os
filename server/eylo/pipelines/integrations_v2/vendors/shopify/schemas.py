"""Shopify GraphQL resources, precise identifiers and typed operation envelopes."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, NoReturn, Self

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

GRAPHQL_PATH = "/graphql.json"
MAX_LINE_ITEMS = 50
MAX_UINT64 = 2**64 - 1
MAX_PAGE_SIZE = 50
CUSTOMER_IDENTITY_PAGE_SIZE = 2


class ShopifyErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    NOT_FOUND = "order_not_found"
    IDENTITY_MISMATCH = "vendor_identity_mismatch"
    PAGINATION_INVALID = "vendor_pagination_invalid"
    CUSTOMER_AMBIGUOUS = "customer_ambiguous"
    OUTCOME_UNKNOWN = "vendor_outcome_unknown"
    PRODUCT_NOT_FOUND = "product_not_found"


class ResourceKind(StrEnum):
    ORDER = "Order"
    LINE_ITEM = "LineItem"
    FULFILLMENT = "Fulfillment"
    CUSTOMER = "Customer"


class OrderStatus(StrEnum):
    ANY = "any"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class CustomerResolution(StrEnum):
    NOT_REQUESTED = "not_requested"
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    EXPLICIT_ID = "explicit_id"


class SearchField(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    CUSTOMER_ID = "customer_id"
    CREATED_AT = "created_at"
    STATUS = "status"


class FinancialStatus(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    EXPIRED = "EXPIRED"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    PENDING = "PENDING"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class OrderFulfillmentStatus(StrEnum):
    FULFILLED = "FULFILLED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    OPEN = "OPEN"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    PENDING_FULFILLMENT = "PENDING_FULFILLMENT"
    REQUEST_DECLINED = "REQUEST_DECLINED"
    RESTOCKED = "RESTOCKED"
    SCHEDULED = "SCHEDULED"
    UNFULFILLED = "UNFULFILLED"


class FulfillmentStatus(StrEnum):
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"
    FAILURE = "FAILURE"
    OPEN = "OPEN"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"


def numeric_id(value: str) -> str:
    if (
        len(value) > 20
        or not value.isascii()
        or not value.isdecimal()
        or not 0 < int(value) <= MAX_UINT64
    ):
        raise ValueError("Shopify IDs must be positive uint64 integers.")
    return str(int(value))


def native_id(value: str, kind: ResourceKind) -> str:
    prefix = f"gid://shopify/{kind.value}/"
    if not value.startswith(prefix):
        raise ValueError(f"Expected a Shopify {kind.value} ID.")
    suffix = value[len(prefix) :]
    if numeric_id(suffix) != suffix:
        raise ValueError("Noncanonical Shopify identity.")
    return value


def order_id(value: str | int) -> str:
    text = str(value).strip()
    if text.startswith("gid:"):
        return native_id(text, ResourceKind.ORDER)
    return f"gid://shopify/Order/{numeric_id(text)}"


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("An offset-bearing timestamp is required.")
    return value


def money(value: str) -> str:
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("Expected a decimal amount.") from None
    if not amount.is_finite():
        raise ValueError("Money must be finite.")
    return value


def uint64(value: str) -> str:
    if (
        len(value) > 20
        or not value.isascii()
        or not value.isdecimal()
        or int(value) > MAX_UINT64
    ):
        raise ValueError("Expected a uint64 decimal string.")
    return value


def search_text(value: str) -> str:
    text = value.strip()
    if not text or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(
            "A nonempty search value without control characters is required."
        )
    return text


def search_phrase(value: str) -> str:
    """Quote user data so Shopify's search grammar cannot interpret operators."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def customer_id(value: str | int) -> str:
    text = str(value).strip()
    if text.startswith("gid:"):
        return native_id(text, ResourceKind.CUSTOMER)
    return f"gid://shopify/Customer/{numeric_id(text)}"


OrderId = Annotated[
    str, AfterValidator(lambda value: native_id(value, ResourceKind.ORDER))
]
LineItemId = Annotated[
    str, AfterValidator(lambda value: native_id(value, ResourceKind.LINE_ITEM))
]
FulfillmentId = Annotated[
    str, AfterValidator(lambda value: native_id(value, ResourceKind.FULFILLMENT))
]
Timestamp = Annotated[str, AfterValidator(timestamp)]
MoneyAmount = Annotated[str, AfterValidator(money)]
Cursor = Annotated[str, Field(min_length=1, max_length=4096)]
InputOrderId = Annotated[str | int, AfterValidator(order_id)]
InputCustomerId = Annotated[str | int, AfterValidator(customer_id)]
CustomerId = Annotated[
    str, AfterValidator(lambda value: native_id(value, ResourceKind.CUSTOMER))
]
SearchText = Annotated[str, Field(max_length=512), AfterValidator(search_text)]
UnsignedInt64 = Annotated[str, AfterValidator(uint64)]


class ShopifyModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class ShopifyRequest(ShopifyModel):
    model_config = ConfigDict(extra="forbid")


class GetOrderInput(ShopifyRequest):
    order_id: InputOrderId = Field(
        description="Order resource ID: numeric, numeric string, or Shopify Order GID; not its display number."
    )
    line_items_cursor: Cursor | None = None
    line_items_limit: int = Field(default=MAX_LINE_ITEMS, ge=1, le=MAX_LINE_ITEMS)


class FindCustomerInput(ShopifyRequest):
    email: SearchText | None = None
    phone: SearchText | None = None
    name: SearchText | None = Field(default=None, description="Name phrase search.")
    cursor: Cursor | None = None
    limit: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)

    @model_validator(mode="after")
    def require_search(self) -> Self:
        if self.email is None and self.phone is None and self.name is None:
            raise ValueError("Give an email, phone number, or name to search for.")
        return self


class ListOrdersInput(ShopifyRequest):
    customer_email: SearchText | None = None
    customer_id: InputCustomerId | None = Field(
        default=None, description="Explicit Customer resource ID, instead of email."
    )
    status: Annotated[
        OrderStatus,
        BeforeValidator(
            lambda value: OrderStatus(value) if isinstance(value, str) else value
        ),
    ] = OrderStatus.ANY
    created_after: Timestamp | None = None
    cursor: Cursor | None = None
    limit: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)

    @model_validator(mode="after")
    def exclusive_customer_selector(self) -> Self:
        if self.customer_email is not None and self.customer_id is not None:
            raise ValueError("Choose customer_email or customer_id, not both.")
        return self


class SearchVariables(ShopifyRequest):
    query: str
    first: int = Field(ge=1, le=MAX_PAGE_SIZE)
    after: Cursor | None = None


class OrderVariables(ShopifyRequest):
    id: OrderId
    first: int = Field(ge=1, le=MAX_LINE_ITEMS)
    after: Cursor | None = None


class GraphQLRequest[T: BaseModel](ShopifyRequest):
    query: str
    variables: T


class GraphQLError(ShopifyModel):
    message: str


class GraphQLResponse[T](ShopifyModel):
    data: T | None = None
    errors: list[GraphQLError] = Field(default_factory=list)


class PageInfo(ShopifyModel):
    hasNextPage: bool
    endCursor: Cursor | None

    @model_validator(mode="after")
    def next_cursor_required(self) -> Self:
        if self.hasNextPage and self.endCursor is None:
            raise ValueError("A nonterminal page must provide a cursor.")
        return self


class Connection[T](ShopifyModel):
    nodes: list[T]
    pageInfo: PageInfo


class Money(ShopifyModel):
    amount: MoneyAmount
    currencyCode: str = Field(pattern=r"^[A-Z]{3}$")


class MoneyBag(ShopifyModel):
    shopMoney: Money


class CustomerEmail(ShopifyModel):
    emailAddress: str


class CustomerPhone(ShopifyModel):
    phoneNumber: str


class CustomerIdentity(ShopifyModel):
    id: CustomerId


class Customer(CustomerIdentity):
    displayName: str
    defaultEmailAddress: CustomerEmail | None
    defaultPhoneNumber: CustomerPhone | None
    numberOfOrders: UnsignedInt64
    amountSpent: Money
    createdAt: Timestamp


class CustomersData(ShopifyModel):
    customers: Connection[Customer]


class OrderSummary(ShopifyModel):
    id: OrderId
    name: str
    createdAt: Timestamp
    totalPriceSet: MoneyBag
    displayFinancialStatus: (
        Annotated[
            FinancialStatus,
            BeforeValidator(
                lambda value: FinancialStatus(value)
                if isinstance(value, str)
                else value
            ),
        ]
        | None
    )
    displayFulfillmentStatus: Annotated[
        OrderFulfillmentStatus,
        BeforeValidator(
            lambda value: OrderFulfillmentStatus(value)
            if isinstance(value, str)
            else value
        ),
    ]
    cancelledAt: Timestamp | None
    tags: list[str]


class ListedOrder(OrderSummary):
    customer: CustomerIdentity | None


class OrdersData(ShopifyModel):
    orders: Connection[ListedOrder]


class LineItem(ShopifyModel):
    id: LineItemId
    title: str
    variantTitle: str | None
    sku: str | None
    quantity: int = Field(ge=0)
    originalUnitPriceSet: MoneyBag


class ShippingAddress(ShopifyModel):
    name: str | None
    city: str | None
    province: str | None
    country: str | None
    zip: str | None


class TrackingInfo(ShopifyModel):
    company: str | None
    number: str | None
    url: str | None


class Fulfillment(ShopifyModel):
    id: FulfillmentId
    status: Annotated[
        FulfillmentStatus,
        BeforeValidator(
            lambda value: FulfillmentStatus(value) if isinstance(value, str) else value
        ),
    ]
    trackingInfo: list[TrackingInfo]
    createdAt: Timestamp


class OrderDetail(OrderSummary):
    lineItems: Connection[LineItem]
    shippingAddress: ShippingAddress | None
    fulfillments: list[Fulfillment]
    note: str | None
    email: str | None


class OrderData(ShopifyModel):
    order: OrderDetail | None


class LineItemView(ShopifyModel):
    id: str
    title: str
    variant: str | None
    sku: str | None
    quantity: int
    price: str
    currency: str


class ShipmentView(ShopifyModel):
    id: str
    status: FulfillmentStatus
    tracking: list[TrackingInfo]
    created_at: str


class OrderSummaryView(ShopifyModel):
    id: str
    gid: str
    order_number: str
    created_at: str
    total: str
    currency: str
    financial_status: FinancialStatus | None
    fulfillment_status: OrderFulfillmentStatus
    cancelled_at: str | None
    tags: list[str]


class OrderView(OrderSummaryView):
    line_items: list[LineItemView]
    next_line_items_cursor: str | None
    shipping_address: ShippingAddress | None
    shipments: list[ShipmentView]
    note: str | None
    customer_email: str | None


class CustomerView(ShopifyModel):
    id: str
    gid: str
    name: str
    email: str | None
    phone: str | None
    orders_count: str
    total_spent: str
    currency: str
    created_at: str


class CustomerListView(ShopifyModel):
    customers: list[CustomerView]
    count: int
    next_cursor: str | None


class OrderListView(ShopifyModel):
    orders: list[OrderSummaryView]
    count: int
    next_cursor: str | None
    customer_id: str | None
    customer_resolution: CustomerResolution


ORDER_DATA = TypeAdapter(GraphQLResponse[OrderData])
CUSTOMERS_DATA = TypeAdapter(GraphQLResponse[CustomersData])
ORDERS_DATA = TypeAdapter(GraphQLResponse[OrdersData])


def page_cursor(
    identities: list[str], page: PageInfo, previous: str | None, limit: int
) -> str | None:
    if len(identities) > limit or len(set(identities)) != len(identities):
        invalid_response()
    if not page.hasNextPage:
        return None
    if not identities or page.endCursor == previous:
        raise VendorToolError(
            ShopifyErrorCode.PAGINATION_INVALID,
            "Shopify returned a non-progressing page.",
        )
    return page.endCursor


def invalid_response() -> NoReturn:
    raise VendorToolError(
        ShopifyErrorCode.RESPONSE_INVALID,
        "Shopify returned an invalid response for this operation.",
    )


def graphql_data[T](
    response: VendorResponse, schema: TypeAdapter[GraphQLResponse[T]]
) -> T:
    if not response.ok:
        raise VendorToolError(
            ShopifyErrorCode.REJECTED, "Shopify rejected the request."
        )
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        envelope = schema.validate_python(response.data, strict=True)
    except ValidationError:
        return invalid_response()
    if envelope.errors:
        raise VendorToolError(
            ShopifyErrorCode.REJECTED,
            "Shopify returned GraphQL errors; no complete result is available.",
        )
    data = envelope.data
    if data is None:
        return invalid_response()
    return data
