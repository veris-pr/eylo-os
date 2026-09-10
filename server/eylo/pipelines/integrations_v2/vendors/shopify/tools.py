"""Curated Shopify tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from typing import NoReturn

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import vendor
from .queries import CUSTOMERS, ORDERS, ORDER_DETAIL, ORDER_UPDATE, PRODUCT, PRODUCTS
from .schemas import (
    CUSTOMERS_DATA,
    CUSTOMER_IDENTITY_PAGE_SIZE,
    GRAPHQL_PATH,
    ORDERS_DATA,
    ORDER_DATA,
    Connection,
    Customer,
    CustomerListView,
    CustomerResolution,
    CustomerView,
    FindCustomerInput,
    GetOrderInput,
    GraphQLRequest,
    LineItemView,
    ListOrdersInput,
    OrderListView,
    OrderStatus,
    OrderSummary,
    OrderSummaryView,
    OrderVariables,
    OrderView,
    SearchField,
    SearchVariables,
    ShipmentView,
    ShopifyErrorCode,
    customer_id,
    graphql_data,
    order_id,
    page_cursor,
    search_phrase,
)
from .stock_contracts import (
    MAX_VARIANT_PAGE_SIZE,
    PRODUCTS_DATA,
    PRODUCT_DATA,
    CheckProductStockInput,
    InventoryExtent,
    Product,
    ProductListVariables,
    ProductVariables,
    ProductView,
    StockView,
    VariantView,
    product_id,
)
from .write_contracts import (
    ORDER_UPDATE_DATA,
    OperationOutcome,
    OrderNoteInput,
    OrderUpdateVariables,
    OrderUpdateView,
    TagOrderInput,
    UpdateOutcome,
)


@curated_tool(
    vendor=vendor.vendor,
    name="find_customer",
    display_name="Find Shopify Customer",
    description=(
        "Look a customer up by email, phone, or name. Returns their id, "
        "contact details, order count, and lifetime spend, so a follow-up "
        "lookup is rarely needed. Repeat with next_cursor as cursor and the same "
        "filters for further matches. Never assume the first match is the intended customer."
    ),
    input_model=FindCustomerInput,
    effect=ToolEffect.READ,
)
async def find_customer(
    payload: FindCustomerInput, ctx: VendorToolContext
) -> dict[str, object]:
    terms = []
    if payload.email is not None:
        terms.append(f"{SearchField.EMAIL}:{search_phrase(payload.email)}")
    if payload.phone is not None:
        terms.append(f"{SearchField.PHONE}:{search_phrase(payload.phone)}")
    if payload.name is not None:
        terms.append(search_phrase(payload.name))
    page = await _customer_page(ctx, " AND ".join(terms), payload.limit, payload.cursor)
    next_cursor = page_cursor(
        [item.id for item in page.nodes], page.pageInfo, payload.cursor, payload.limit
    )
    return CustomerListView(
        customers=[
            CustomerView(
                id=item.id.rsplit("/", 1)[-1],
                gid=item.id,
                name=item.displayName,
                email=item.defaultEmailAddress.emailAddress
                if item.defaultEmailAddress
                else None,
                phone=item.defaultPhoneNumber.phoneNumber
                if item.defaultPhoneNumber
                else None,
                orders_count=item.numberOfOrders,
                total_spent=item.amountSpent.amount,
                currency=item.amountSpent.currencyCode,
                created_at=item.createdAt,
            )
            for item in page.nodes
        ],
        count=len(page.nodes),
        next_cursor=next_cursor,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_orders",
    display_name="List Shopify Orders",
    description=(
        "List orders, optionally only a given customer's — name them by email "
        "and the customer lookup happens here; ambiguous matches are refused. "
        "Alternatively supply customer_id from find_customer. Each order reports "
        "its number, total, financial status, and fulfillment status. Repeat with "
        "next_cursor and the same filters to continue. Orders older than 60 days "
        "require Shopify-approved read_all_orders access."
    ),
    input_model=ListOrdersInput,
    effect=ToolEffect.READ,
)
async def list_orders(
    payload: ListOrdersInput, ctx: VendorToolContext
) -> dict[str, object]:
    identity = (
        customer_id(payload.customer_id) if payload.customer_id is not None else None
    )
    resolution = (
        CustomerResolution.EXPLICIT_ID if identity else CustomerResolution.NOT_REQUESTED
    )
    if payload.customer_email is not None:
        page = await _customer_page(
            ctx,
            f"{SearchField.EMAIL}:{search_phrase(payload.customer_email)}",
            CUSTOMER_IDENTITY_PAGE_SIZE,
            None,
        )
        next_customer_cursor = page_cursor(
            [item.id for item in page.nodes],
            page.pageInfo,
            None,
            CUSTOMER_IDENTITY_PAGE_SIZE,
        )
        if next_customer_cursor is not None or len(page.nodes) > 1:
            raise VendorToolError(
                ShopifyErrorCode.CUSTOMER_AMBIGUOUS,
                "Customer lookup is ambiguous. Use find_customer and supply an explicit customer_id.",
            )
        if not page.nodes:
            return OrderListView(
                orders=[],
                count=0,
                next_cursor=None,
                customer_id=None,
                customer_resolution=CustomerResolution.NOT_FOUND,
            ).model_dump(mode="json")
        match = page.nodes[0]
        if (
            match.defaultEmailAddress is None
            or match.defaultEmailAddress.emailAddress.casefold()
            != payload.customer_email.casefold()
        ):
            raise VendorToolError(
                ShopifyErrorCode.IDENTITY_MISMATCH,
                "Customer search did not return the requested email. Use an explicit customer_id.",
            )
        identity = match.id
        resolution = CustomerResolution.MATCHED
    terms = []
    if identity is not None:
        terms.append(f"{SearchField.CUSTOMER_ID}:{identity.rsplit('/', 1)[-1]}")
    if payload.status is not OrderStatus.ANY:
        terms.append(f"{SearchField.STATUS}:{payload.status.value}")
    if payload.created_after is not None:
        terms.append(
            f"{SearchField.CREATED_AT}:>{search_phrase(payload.created_after)}"
        )
    body = GraphQLRequest(
        query=ORDERS,
        variables=SearchVariables(
            query=" AND ".join(terms), first=payload.limit, after=payload.cursor
        ),
    )
    page = graphql_data(
        await ctx.read(GRAPHQL_PATH, method="POST", json=body.model_dump(mode="json")),
        ORDERS_DATA,
    ).orders
    next_cursor = page_cursor(
        [item.id for item in page.nodes], page.pageInfo, payload.cursor, payload.limit
    )
    if identity is not None and any(
        item.customer is None or item.customer.id != identity for item in page.nodes
    ):
        raise VendorToolError(
            ShopifyErrorCode.IDENTITY_MISMATCH,
            "Shopify returned another customer's order.",
        )
    return OrderListView(
        orders=[_summary_view(item) for item in page.nodes],
        count=len(page.nodes),
        next_cursor=next_cursor,
        customer_id=identity,
        customer_resolution=resolution,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_order",
    display_name="Get Shopify Order",
    description=(
        "Read an order: what was bought, what it cost, where it is "
        "going, and what has actually shipped. Fulfillment is summarised into "
        "a plain status and tracking numbers rather than the nested shape the "
        "API returns. Repeat with next_line_items_cursor as line_items_cursor "
        "to read more line items. Access to orders older than 60 days requires "
        "Shopify approval/read_all_orders; an inaccessible result is not proof of absence."
    ),
    input_model=GetOrderInput,
    effect=ToolEffect.READ,
)
async def get_order(
    payload: GetOrderInput, ctx: VendorToolContext
) -> dict[str, object]:
    identity = order_id(payload.order_id)
    body = GraphQLRequest(
        query=ORDER_DETAIL,
        variables=OrderVariables(
            id=identity, first=payload.line_items_limit, after=payload.line_items_cursor
        ),
    )
    data = graphql_data(
        await ctx.read(GRAPHQL_PATH, method="POST", json=body.model_dump(mode="json")),
        ORDER_DATA,
    )
    order = data.order
    if order is None:
        raise VendorToolError(
            ShopifyErrorCode.NOT_FOUND,
            "That order is not accessible to this connection.",
        )
    if order.id != identity:
        raise VendorToolError(
            ShopifyErrorCode.IDENTITY_MISMATCH, "Shopify returned a different order."
        )
    page = order.lineItems
    if len({item.id for item in order.fulfillments}) != len(order.fulfillments):
        raise VendorToolError(
            ShopifyErrorCode.RESPONSE_INVALID,
            "Shopify repeated a fulfillment identity.",
        )
    next_cursor = page_cursor(
        [item.id for item in page.nodes],
        page.pageInfo,
        payload.line_items_cursor,
        payload.line_items_limit,
    )
    return OrderView(
        id=order.id.rsplit("/", 1)[-1],
        gid=order.id,
        order_number=order.name,
        created_at=order.createdAt,
        total=order.totalPriceSet.shopMoney.amount,
        currency=order.totalPriceSet.shopMoney.currencyCode,
        financial_status=order.displayFinancialStatus,
        fulfillment_status=order.displayFulfillmentStatus,
        cancelled_at=order.cancelledAt,
        tags=order.tags,
        line_items=[
            LineItemView(
                id=item.id,
                title=item.title,
                variant=item.variantTitle,
                sku=item.sku,
                quantity=item.quantity,
                price=item.originalUnitPriceSet.shopMoney.amount,
                currency=item.originalUnitPriceSet.shopMoney.currencyCode,
            )
            for item in page.nodes
        ],
        next_line_items_cursor=next_cursor,
        shipping_address=order.shippingAddress,
        shipments=[
            ShipmentView(
                id=item.id,
                status=item.status,
                tracking=item.trackingInfo,
                created_at=item.createdAt,
            )
            for item in order.fulfillments
        ],
        note=order.note,
        customer_email=order.email,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="check_product_stock",
    display_name="Check Shopify Product Stock",
    description=(
        "Scan products for a case-insensitive title substring and report variant "
        "inventory. Follow next_cursor even if a scanned page has no matches. "
        "To continue variants, supply product_id and next_variants_cursor as "
        "variants_cursor. Partial, unavailable or untracked stock is not zero; "
        "a product total is reported only for a complete, tracked variant set. "
        "Inventory policy is separate from stock: CONTINUE allows overselling."
    ),
    input_model=CheckProductStockInput,
    effect=ToolEffect.READ,
)
async def check_product_stock(
    payload: CheckProductStockInput, ctx: VendorToolContext
) -> dict[str, object]:
    if payload.product_id is not None:
        identity = product_id(payload.product_id)
        body = GraphQLRequest(
            query=PRODUCT,
            variables=ProductVariables(
                id=identity, first=MAX_VARIANT_PAGE_SIZE, after=payload.variants_cursor
            ),
        )
        data = graphql_data(
            await ctx.read(
                GRAPHQL_PATH, method="POST", json=body.model_dump(mode="json")
            ),
            PRODUCT_DATA,
        )
        product = data.product
        if product is None:
            raise VendorToolError(
                ShopifyErrorCode.PRODUCT_NOT_FOUND,
                "That product is not accessible to this connection.",
            )
        if product.id != identity:
            raise VendorToolError(
                ShopifyErrorCode.IDENTITY_MISMATCH,
                "Shopify returned a different product.",
            )
        return StockView(
            products=[
                _stock_view(product, data.shop.currencyCode, payload.variants_cursor)
            ],
            count=1,
            scanned_count=1,
            next_cursor=None,
        ).model_dump(mode="json")
    body = GraphQLRequest(
        query=PRODUCTS,
        variables=ProductListVariables(
            first=payload.limit,
            after=payload.cursor,
            variantsFirst=MAX_VARIANT_PAGE_SIZE,
        ),
    )
    data = graphql_data(
        await ctx.read(GRAPHQL_PATH, method="POST", json=body.model_dump(mode="json")),
        PRODUCTS_DATA,
    )
    page = data.products
    next_cursor = page_cursor(
        [item.id for item in page.nodes], page.pageInfo, payload.cursor, payload.limit
    )
    # Shopify title search is token-based, not arbitrary substring matching.
    # Filter a bounded catalog page locally; keep its cursor even for no matches.
    needle = payload.title_contains
    if needle is None:
        raise VendorToolError(
            ShopifyErrorCode.RESPONSE_INVALID,
            "Product search requires a title substring.",
        )
    products = [
        _stock_view(item, data.shop.currencyCode, None)
        for item in page.nodes
        if needle.casefold() in item.title.casefold()
    ]
    return StockView(
        products=products,
        count=len(products),
        scanned_count=len(page.nodes),
        next_cursor=next_cursor,
    ).model_dump(mode="json")


def _stock_view(product: Product, currency: str, previous: str | None) -> ProductView:
    page = product.variants
    next_cursor = page_cursor(
        [item.id for item in page.nodes], page.pageInfo, previous, MAX_VARIANT_PAGE_SIZE
    )
    variants = [
        VariantView(
            id=item.id,
            title=item.title,
            sku=item.sku,
            price=item.price,
            in_stock=item.inventoryQuantity if item.inventoryItem.tracked else None,
            inventory_extent=(
                InventoryExtent.UNTRACKED
                if not item.inventoryItem.tracked
                else InventoryExtent.UNAVAILABLE
                if item.inventoryQuantity is None
                else InventoryExtent.COMPLETE
            ),
            inventory_policy=item.inventoryPolicy,
        )
        for item in page.nodes
    ]
    if previous is not None or next_cursor is not None:
        extent = InventoryExtent.PARTIAL
    elif not variants or any(
        item.inventory_extent is InventoryExtent.UNAVAILABLE for item in variants
    ):
        extent = InventoryExtent.UNAVAILABLE
    elif any(item.inventory_extent is InventoryExtent.UNTRACKED for item in variants):
        extent = InventoryExtent.UNTRACKED
    else:
        extent = InventoryExtent.COMPLETE
    total = (
        sum(item.in_stock for item in variants if item.in_stock is not None)
        if extent is InventoryExtent.COMPLETE
        else None
    )
    return ProductView(
        id=product.id.rsplit("/", 1)[-1],
        gid=product.id,
        title=product.title,
        status=product.status,
        currency=currency,
        total_in_stock=total,
        inventory_extent=extent,
        variants=variants,
        next_variants_cursor=next_cursor,
    )


@curated_tool(
    vendor=vendor.vendor,
    name="tag_order",
    display_name="Tag Shopify Order",
    description=(
        "Add tags atomically without replacing existing tags, or replace an order's "
        "internal note. Empty note clears it. When both are requested they are "
        "independent operations in one request: inspect tags_outcome and note_outcome "
        "because one may succeed while the other is rejected. Never retry a confirmed "
        "operation or an unknown outcome automatically."
    ),
    input_model=TagOrderInput,
    effect=ToolEffect.MUTATION,
)
async def tag_order(
    payload: TagOrderInput, ctx: VendorToolContext
) -> dict[str, object]:
    identity = order_id(payload.order_id)
    requested_tags = list(dict.fromkeys(payload.add_tags or []))
    body = GraphQLRequest(
        query=ORDER_UPDATE,
        variables=OrderUpdateVariables(
            id=identity,
            tags=requested_tags,
            input=OrderNoteInput(id=identity, note=payload.note),
            addTags=payload.add_tags is not None,
            setNote=payload.note is not None,
        ),
    )
    response = await ctx.mutate(
        GRAPHQL_PATH, method="POST", json=body.model_dump(mode="json")
    )
    try:
        data = graphql_data(response, ORDER_UPDATE_DATA)
    except VendorToolError:
        # A malformed/partial GraphQL response cannot establish mutation failure.
        raise VendorToolError(
            ShopifyErrorCode.OUTCOME_UNKNOWN,
            "Shopify did not provide a trustworthy mutation acknowledgement. Inspect the order before retrying.",
        ) from None
    tags_outcome = note_outcome = OperationOutcome.NOT_REQUESTED
    tags = None
    note = None
    tags_errors = note_errors = 0
    if payload.add_tags is not None:
        added = data.tagsAdd
        if added is None:
            return _unknown_update()
        tags_errors = len(added.userErrors)
        if tags_errors:
            if added.node is not None:
                return _unknown_update()
            tags_outcome = OperationOutcome.REJECTED
        else:
            if (
                added.node is None
                or added.node.id != identity
                or not set(requested_tags).issubset(added.node.tags)
            ):
                return _unknown_update()
            tags = added.node.tags
            tags_outcome = OperationOutcome.CONFIRMED
    elif data.tagsAdd is not None:
        _unknown_update()
    if payload.note is not None:
        updated = data.orderUpdate
        if updated is None:
            return _unknown_update()
        note_errors = len(updated.userErrors)
        if note_errors:
            if updated.order is not None:
                return _unknown_update()
            note_outcome = OperationOutcome.REJECTED
        else:
            if (
                updated.order is None
                or updated.order.id != identity
                or (updated.order.note or "") != payload.note
            ):
                return _unknown_update()
            note = updated.order.note
            note_outcome = OperationOutcome.CONFIRMED
    elif data.orderUpdate is not None:
        _unknown_update()
    outcomes = (tags_outcome, note_outcome)
    outcome = UpdateOutcome.CONFIRMED
    if OperationOutcome.REJECTED in outcomes:
        outcome = (
            UpdateOutcome.PARTIAL
            if OperationOutcome.CONFIRMED in outcomes
            else UpdateOutcome.REJECTED
        )
    return OrderUpdateView(
        order_id=identity,
        outcome=outcome,
        tags_outcome=tags_outcome,
        note_outcome=note_outcome,
        tags=tags,
        note=note,
        rejected_tags_errors=tags_errors,
        rejected_note_errors=note_errors,
    ).model_dump(mode="json")


def _unknown_update() -> NoReturn:
    raise VendorToolError(
        ShopifyErrorCode.OUTCOME_UNKNOWN,
        "Shopify did not confirm the requested order change. Inspect the order before retrying.",
    )


async def _customer_page(
    ctx: VendorToolContext, query: str, limit: int, cursor: str | None
) -> Connection[Customer]:
    body = GraphQLRequest(
        query=CUSTOMERS,
        variables=SearchVariables(query=query, first=limit, after=cursor),
    )
    return graphql_data(
        await ctx.read(GRAPHQL_PATH, method="POST", json=body.model_dump(mode="json")),
        CUSTOMERS_DATA,
    ).customers


def _summary_view(order: OrderSummary) -> OrderSummaryView:
    return OrderSummaryView(
        id=order.id.rsplit("/", 1)[-1],
        gid=order.id,
        order_number=order.name,
        created_at=order.createdAt,
        total=order.totalPriceSet.shopMoney.amount,
        currency=order.totalPriceSet.shopMoney.currencyCode,
        financial_status=order.displayFinancialStatus,
        fulfillment_status=order.displayFulfillmentStatus,
        cancelled_at=order.cancelledAt,
        tags=order.tags,
    )


__all__ = [
    "check_product_stock",
    "find_customer",
    "get_order",
    "list_orders",
    "tag_order",
]
