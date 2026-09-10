"""Curated Stripe billing reads with explicit identity, pagination and monetary precision."""

from __future__ import annotations

from decimal import Decimal

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from . import schemas as s
from .definition import vendor


@curated_tool(
    vendor=vendor.vendor,
    name="find_customer",
    display_name="Find Stripe Customer",
    description="Find every customer matching an exact, case-sensitive email. Returns a page, not an arbitrarily selected account. Continue using next_starting_after. Choose an explicit customer_id for ambiguous emails. Missing currency never defaults to USD.",
    input_model=s.FindCustomerInput,
    effect=ToolEffect.READ,
)
async def find_customer(
    payload: s.FindCustomerInput, ctx: VendorToolContext
) -> dict[str, object]:
    page = await _customers(ctx, payload.email, payload.limit, payload.starting_after)
    cursor = s.next_cursor(
        page, [item.id for item in page.data], payload.starting_after, payload.limit
    )
    _check_customer_emails(page.data, payload.email)
    return s.CustomerListView(
        customers=[
            s.CustomerView(
                id=item.id,
                name=item.name,
                email=item.email,
                balance=s.money(item.balance, item.currency)
                if item.balance is not None
                else None,
                delinquent=item.delinquent,
                created_at=s.moment(item.created),
            )
            for item in page.data
        ],
        count=len(page.data),
        next_starting_after=cursor,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_payments",
    display_name="List Stripe Payments",
    description="List a customer's charges, most recent first. Select by unambiguous exact email or customer_id. Follow next_starting_after with the same customer. Paid includes authorization; inspect amount_captured before claiming funds were captured. Refund aggregates do not prove bank delivery.",
    input_model=s.ListPaymentsInput,
    effect=ToolEffect.READ,
)
async def list_payments(
    payload: s.ListPaymentsInput, ctx: VendorToolContext
) -> dict[str, object]:
    customer = await _resolve_customer(payload, ctx)
    if customer.id is None:
        return s.PaymentsView(
            payments=[],
            count=0,
            next_starting_after=None,
            customer_id=None,
            customer_resolution=customer.resolution,
        ).model_dump(mode="json")
    query = s.CustomerResourceQuery(
        customer=customer.id, limit=payload.limit, starting_after=payload.starting_after
    )
    page = s.parse_response(
        await ctx.read(
            "/charges", query=query.model_dump(mode="json", exclude_none=True)
        ),
        s.CHARGES,
    )
    cursor = s.next_cursor(
        page, [item.id for item in page.data], payload.starting_after, payload.limit
    )
    for item in page.data:
        _check_owner(item.customer, customer.id)
    return s.PaymentsView(
        payments=[_charge_view(item) for item in page.data],
        count=len(page.data),
        next_starting_after=cursor,
        customer_id=customer.id,
        customer_resolution=customer.resolution,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_invoices",
    display_name="List Stripe Invoices",
    description="List a customer's invoices with precise totals, payment status and source links. Select exact unambiguous email or customer_id. Continue using next_starting_after with the same customer. Source URLs are returned, never downloaded.",
    input_model=s.ListInvoicesInput,
    effect=ToolEffect.READ,
)
async def list_invoices(
    payload: s.ListInvoicesInput, ctx: VendorToolContext
) -> dict[str, object]:
    customer = await _resolve_customer(payload, ctx)
    if customer.id is None:
        return s.InvoicesView(
            invoices=[],
            count=0,
            next_starting_after=None,
            customer_id=None,
            customer_resolution=customer.resolution,
        ).model_dump(mode="json")
    query = s.CustomerResourceQuery(
        customer=customer.id, limit=payload.limit, starting_after=payload.starting_after
    )
    page = s.parse_response(
        await ctx.read(
            "/invoices", query=query.model_dump(mode="json", exclude_none=True)
        ),
        s.INVOICES,
    )
    cursor = s.next_cursor(
        page, [item.id for item in page.data], payload.starting_after, payload.limit
    )
    for item in page.data:
        _check_owner(item.customer, customer.id)
    return s.InvoicesView(
        invoices=[
            s.InvoiceView(
                id=item.id,
                number=item.number,
                status=item.status,
                total=s.money(item.total, item.currency),
                amount_due=s.money(item.amount_due, item.currency),
                amount_paid=s.money(item.amount_paid, item.currency),
                due_at=s.moment(item.due_date),
                created_at=s.moment(item.created),
                hosted_url=item.hosted_invoice_url,
                pdf_url=item.invoice_pdf,
            )
            for item in page.data
        ],
        count=len(page.data),
        next_starting_after=cursor,
        customer_id=customer.id,
        customer_resolution=customer.resolution,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_subscriptions",
    display_name="List Stripe Subscriptions",
    description="List subscriptions and all returned price items, retaining each item's billing period. Prices are unit prices, not final invoice totals; tiered or usage billing cannot be inferred from one unit amount. Continue subscriptions with next_starting_after. Continue a subscription's items using subscription_id and next_items_starting_after, keeping the customer selector. status defaults to not_canceled; use all to include canceled subscriptions.",
    input_model=s.ListSubscriptionsInput,
    effect=ToolEffect.READ,
)
async def list_subscriptions(
    payload: s.ListSubscriptionsInput, ctx: VendorToolContext
) -> dict[str, object]:
    customer = await _resolve_customer(payload, ctx)
    if customer.id is None:
        return s.SubscriptionsView(
            subscriptions=[],
            count=0,
            next_starting_after=None,
            customer_id=None,
            customer_resolution=customer.resolution,
        ).model_dump(mode="json")
    if payload.subscription_id is not None:
        subscription = s.parse_response(
            await ctx.read(f"/subscriptions/{payload.subscription_id}"), s.SUBSCRIPTION
        )
        if subscription.id != payload.subscription_id:
            _wrong_identity()
        _check_owner(subscription.customer, customer.id)
        query = s.SubscriptionItemsQuery(
            subscription=subscription.id,
            limit=payload.limit,
            starting_after=payload.items_starting_after,
        )
        items = s.parse_response(
            await ctx.read(
                "/subscription_items",
                query=query.model_dump(mode="json", exclude_none=True),
            ),
            s.SUBSCRIPTION_ITEMS,
        )
        view = _subscription_view(
            subscription, items, payload.items_starting_after, payload.limit
        )
        return s.SubscriptionsView(
            subscriptions=[view],
            count=1,
            next_starting_after=None,
            customer_id=customer.id,
            customer_resolution=customer.resolution,
        ).model_dump(mode="json")
    query = s.SubscriptionQuery(
        customer=customer.id,
        limit=payload.limit,
        starting_after=payload.starting_after,
        status=None
        if payload.effective_status is s.SubscriptionFilter.NOT_CANCELED
        else payload.effective_status,
    )
    page = s.parse_response(
        await ctx.read(
            "/subscriptions", query=query.model_dump(mode="json", exclude_none=True)
        ),
        s.SUBSCRIPTIONS,
    )
    cursor = s.next_cursor(
        page, [item.id for item in page.data], payload.starting_after, payload.limit
    )
    for item in page.data:
        _check_owner(item.customer, customer.id)
        if (
            payload.effective_status is s.SubscriptionFilter.NOT_CANCELED
            and item.status is s.SubscriptionStatus.CANCELED
        ):
            _wrong_identity()
        if (
            payload.effective_status is s.SubscriptionFilter.ENDED
            and item.status
            not in (
                s.SubscriptionStatus.CANCELED,
                s.SubscriptionStatus.INCOMPLETE_EXPIRED,
            )
        ):
            _wrong_identity()
        if (
            payload.effective_status
            not in (
                s.SubscriptionFilter.ALL,
                s.SubscriptionFilter.ENDED,
                s.SubscriptionFilter.NOT_CANCELED,
            )
            and item.status.value != payload.effective_status.value
        ):
            _wrong_identity()
    return s.SubscriptionsView(
        subscriptions=[
            _subscription_view(item, item.items, None, s.MAX_EMBEDDED_ITEMS)
            for item in page.data
        ],
        count=len(page.data),
        next_starting_after=cursor,
        customer_id=customer.id,
        customer_resolution=customer.resolution,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_payment",
    display_name="Get Stripe Payment",
    description="Read a charge or PaymentIntent, including a real paginated refund lookup. Continue refunds with next_refunds_starting_after and the same payment_id. Pending/failed refunds are not successful refunds. A partial refund page cannot establish a fully refunded PaymentIntent. Results are live reads, not an atomic financial snapshot or proof of bank settlement.",
    input_model=s.GetPaymentInput,
    effect=ToolEffect.READ,
)
async def get_payment(
    payload: s.GetPaymentInput, ctx: VendorToolContext
) -> dict[str, object]:
    charge: s.Charge | None
    if payload.payment_id.startswith("pi_"):
        payment = s.parse_response(
            await ctx.read(
                f"/payment_intents/{payload.payment_id}",
                query={"expand[]": "latest_charge"},
            ),
            s.INTENT,
        )
        if payment.id != payload.payment_id:
            _wrong_identity()
        charge = (
            payment.latest_charge
            if isinstance(payment.latest_charge, s.Charge)
            else None
        )
        if isinstance(payment.latest_charge, str):
            charge = await _read_charge(ctx, payment.latest_charge)
            if charge.id != payment.latest_charge:
                _wrong_identity()
        if charge is not None:
            if (
                charge.payment_intent != payment.id
                or charge.currency != payment.currency
            ):
                _wrong_identity()
            if s.customer_identity(charge.customer) != s.customer_identity(
                payment.customer
            ):
                _wrong_identity()
        query = s.RefundQuery(
            payment_intent=payment.id,
            limit=payload.refunds_limit,
            starting_after=payload.refunds_starting_after,
        )
        page = s.parse_response(
            await ctx.read(
                "/refunds", query=query.model_dump(mode="json", exclude_none=True)
            ),
            s.REFUNDS,
        )
        for refund in page.data:
            if (
                refund.payment_intent != payment.id
                or refund.currency != payment.currency
            ):
                _wrong_identity()
        next_refund = s.next_cursor(
            page,
            [item.id for item in page.data],
            payload.refunds_starting_after,
            payload.refunds_limit,
        )
        extent = _refund_extent(page, payload.refunds_starting_after)
        fully_refunded = None
        if extent is s.Extent.COMPLETE:
            returned = sum(
                item.amount
                for item in page.data
                if item.status is s.RefundStatus.SUCCEEDED
            )
            fully_refunded = (
                payment.amount_received > 0 and returned == payment.amount_received
            )
        return s.PaymentView(
            id=payment.id,
            kind=s.ObjectKind.PAYMENT_INTENT,
            amount=s.money(payment.amount, payment.currency),
            amount_received=s.money(payment.amount_received, payment.currency),
            status=payment.status,
            customer_id=s.customer_identity(payment.customer),
            description=payment.description,
            created_at=s.moment(payment.created),
            failure_reason=payment.last_payment_error.message
            if payment.last_payment_error
            else None,
            receipt_url=charge.receipt_url if charge else None,
            latest_charge_id=charge.id if charge else None,
            refunds=[_refund_view(item) for item in page.data],
            refunds_extent=extent,
            next_refunds_starting_after=next_refund,
            fully_refunded=fully_refunded,
        ).model_dump(mode="json")
    charge = await _read_charge(ctx, payload.payment_id)
    if charge.id != payload.payment_id:
        _wrong_identity()
    query = s.RefundQuery(
        charge=charge.id,
        limit=payload.refunds_limit,
        starting_after=payload.refunds_starting_after,
    )
    page = s.parse_response(
        await ctx.read(
            "/refunds", query=query.model_dump(mode="json", exclude_none=True)
        ),
        s.REFUNDS,
    )
    for refund in page.data:
        if refund.charge != charge.id or refund.currency != charge.currency:
            _wrong_identity()
    cursor = s.next_cursor(
        page,
        [item.id for item in page.data],
        payload.refunds_starting_after,
        payload.refunds_limit,
    )
    return s.PaymentView(
        id=charge.id,
        kind=s.ObjectKind.CHARGE,
        amount=s.money(charge.amount, charge.currency),
        amount_received=s.money(charge.amount_captured, charge.currency),
        status=charge.status,
        customer_id=s.customer_identity(charge.customer),
        description=charge.description,
        created_at=s.moment(charge.created),
        failure_reason=charge.failure_message,
        receipt_url=charge.receipt_url,
        latest_charge_id=charge.id,
        refunds=[_refund_view(item) for item in page.data],
        refunds_extent=_refund_extent(page, payload.refunds_starting_after),
        next_refunds_starting_after=cursor,
        fully_refunded=charge.refunded,
    ).model_dump(mode="json")


async def _customers(
    ctx: VendorToolContext, email: str, limit: int, cursor: str | None
) -> s.StripeList[s.Customer]:
    query = s.CustomerQuery(email=email, limit=limit, starting_after=cursor)
    return s.parse_response(
        await ctx.read(
            "/customers", query=query.model_dump(mode="json", exclude_none=True)
        ),
        s.CUSTOMERS,
    )


def _check_customer_emails(customers: list[s.Customer], email: str) -> None:
    if any(item.email != email for item in customers):
        _wrong_identity()


async def _resolve_customer(
    payload: s.CustomerSelection, ctx: VendorToolContext
) -> s.CustomerMatch:
    if payload.customer_id is not None:
        return s.CustomerMatch(
            id=payload.customer_id, resolution=s.CustomerResolution.EXPLICIT_ID
        )
    email = payload.customer_email
    if email is None:
        raise VendorToolError(
            s.StripeErrorCode.RESPONSE_INVALID, "A customer selector is required."
        )
    page = await _customers(ctx, email, s.IDENTITY_PAGE_SIZE, None)
    s.next_cursor(page, [item.id for item in page.data], None, s.IDENTITY_PAGE_SIZE)
    _check_customer_emails(page.data, email)
    if page.has_more or len(page.data) > 1:
        raise VendorToolError(
            s.StripeErrorCode.CUSTOMER_AMBIGUOUS,
            "Several customers match this email. Use find_customer and choose an explicit customer_id.",
        )
    if not page.data:
        return s.CustomerMatch(id=None, resolution=s.CustomerResolution.NOT_FOUND)
    return s.CustomerMatch(id=page.data[0].id, resolution=s.CustomerResolution.MATCHED)


def _check_owner(owner: s.CustomerRef | None, expected: str) -> None:
    if s.customer_identity(owner) != expected:
        _wrong_identity()


def _wrong_identity() -> None:
    raise VendorToolError(
        s.StripeErrorCode.IDENTITY_MISMATCH,
        "Stripe returned a resource outside the requested identity or filter.",
    )


def _charge_view(item: s.Charge) -> s.ChargeView:
    return s.ChargeView(
        id=item.id,
        payment_intent_id=item.payment_intent,
        amount=s.money(item.amount, item.currency),
        amount_captured=s.money(item.amount_captured, item.currency),
        amount_refunded=s.money(item.amount_refunded, item.currency),
        status=item.status,
        paid=item.paid,
        refunded=item.refunded,
        description=item.description,
        failure_message=item.failure_message,
        card_last4=item.payment_method_details.card.last4
        if item.payment_method_details and item.payment_method_details.card
        else None,
        receipt_url=item.receipt_url,
        created_at=s.moment(item.created),
    )


def _subscription_view(
    subscription: s.Subscription,
    items: s.StripeList[s.SubscriptionItem],
    previous: str | None,
    limit: int,
) -> s.SubscriptionView:
    cursor = s.next_cursor(items, [item.id for item in items.data], previous, limit)
    results = []
    for item in items.data:
        if item.subscription != subscription.id:
            _wrong_identity()
        price = item.price
        minor = (
            price.unit_amount_decimal
            if price.unit_amount_decimal is not None
            else price.unit_amount
        )
        if (
            price.unit_amount is not None
            and price.unit_amount_decimal is not None
            and Decimal(price.unit_amount_decimal) != price.unit_amount
        ):
            s.invalid_response()
        results.append(
            s.SubscriptionItemView(
                id=item.id,
                price_id=price.id,
                product_id=price.product.id
                if isinstance(price.product, s.ProductIdentity)
                else price.product,
                nickname=price.nickname,
                billing_scheme=price.billing_scheme,
                unit_amount=s.money(minor, price.currency)
                if minor is not None
                else None,
                recurring=price.recurring,
                quantity=item.quantity,
                current_period_start=s.moment(item.current_period_start),
                current_period_end=s.moment(item.current_period_end),
            )
        )
    return s.SubscriptionView(
        id=subscription.id,
        status=subscription.status,
        items=results,
        items_extent=s.Extent.PARTIAL
        if previous is not None or items.has_more
        else s.Extent.COMPLETE,
        next_items_starting_after=cursor,
        cancel_at_period_end=subscription.cancel_at_period_end,
        cancel_at=s.moment(subscription.cancel_at),
        cancelled_at=s.moment(subscription.canceled_at),
        trial_ends_at=s.moment(subscription.trial_end),
    )


def _refund_view(refund: s.Refund) -> s.RefundView:
    return s.RefundView(
        id=refund.id,
        amount=s.money(refund.amount, refund.currency),
        status=refund.status,
        reason=refund.reason,
        created_at=s.moment(refund.created),
    )


def _refund_extent(page: s.StripeList[s.Refund], previous: str | None) -> s.Extent:
    if page.has_more or previous is not None:
        return s.Extent.PARTIAL
    if any(item.status is None for item in page.data):
        return s.Extent.UNAVAILABLE
    return s.Extent.COMPLETE


async def _read_charge(ctx: VendorToolContext, identity: str) -> s.Charge:
    return s.parse_response(await ctx.read(f"/charges/{identity}"), s.CHARGE)
