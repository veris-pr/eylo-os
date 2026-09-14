"""Shopify inventory pages distinguish partial, untracked and unavailable stock."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    TypeAdapter,
    model_validator,
)

from .schemas import (
    Connection,
    Cursor,
    GraphQLResponse,
    MoneyAmount,
    SearchText,
    ShopifyModel,
    ShopifyRequest,
    numeric_id,
)

MAX_PRODUCT_PAGE_SIZE = 25
MAX_VARIANT_PAGE_SIZE = 10


class ProductStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DRAFT = "DRAFT"
    UNLISTED = "UNLISTED"


class InventoryPolicy(StrEnum):
    DENY = "DENY"
    CONTINUE = "CONTINUE"


class InventoryExtent(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    UNTRACKED = "untracked"


def product_id(value: str | int) -> str:
    text = str(value).strip()
    if text.startswith("gid:"):
        prefix = "gid://shopify/Product/"
        if (
            not text.startswith(prefix)
            or numeric_id(text[len(prefix) :]) != text[len(prefix) :]
        ):
            raise ValueError("Expected a canonical Shopify Product ID.")
        return text
    return f"gid://shopify/Product/{numeric_id(text)}"


def native_product_id(value: str) -> str:
    if product_id(value) != value:
        raise ValueError("Expected a Shopify Product GID.")
    return value


def variant_id(value: str) -> str:
    prefix = "gid://shopify/ProductVariant/"
    if (
        not value.startswith(prefix)
        or numeric_id(value[len(prefix) :]) != value[len(prefix) :]
    ):
        raise ValueError("Expected a canonical Shopify ProductVariant ID.")
    return value


ProductId = Annotated[str, AfterValidator(native_product_id)]
VariantId = Annotated[str, AfterValidator(variant_id)]
InputProductId = Annotated[str | int, AfterValidator(product_id)]


class CheckProductStockInput(ShopifyRequest):
    title_contains: SearchText | None = None
    product_id: InputProductId | None = None
    cursor: Cursor | None = Field(
        default=None,
        description="Continue scanning products with the same title_contains filter.",
    )
    variants_cursor: Cursor | None = Field(
        default=None,
        description="Continue a single product's variants; requires product_id.",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=MAX_PRODUCT_PAGE_SIZE,
        description="Products scanned per page before substring filtering. An empty page can still have next_cursor.",
    )

    @model_validator(mode="after")
    def valid_selection(self) -> Self:
        if (self.title_contains is None) == (self.product_id is None):
            raise ValueError("Choose title_contains or product_id.")
        if self.variants_cursor is not None and self.product_id is None:
            raise ValueError("variants_cursor requires product_id.")
        if self.cursor is not None and self.product_id is not None:
            raise ValueError("A product-list cursor cannot select a single product.")
        return self


class ProductListVariables(ShopifyRequest):
    first: int = Field(ge=1, le=MAX_PRODUCT_PAGE_SIZE)
    after: Cursor | None
    variantsFirst: int = Field(ge=1, le=MAX_VARIANT_PAGE_SIZE)


class ProductVariables(ShopifyRequest):
    id: ProductId
    first: int = Field(ge=1, le=MAX_VARIANT_PAGE_SIZE)
    after: Cursor | None


class InventoryItem(ShopifyModel):
    tracked: bool


class Variant(ShopifyModel):
    id: VariantId
    title: str
    sku: str | None
    price: MoneyAmount
    inventoryQuantity: int | None
    inventoryItem: InventoryItem
    inventoryPolicy: Annotated[
        InventoryPolicy,
        BeforeValidator(
            lambda value: InventoryPolicy(value) if isinstance(value, str) else value
        ),
    ]


class Product(ShopifyModel):
    id: ProductId
    title: str
    status: Annotated[
        ProductStatus,
        BeforeValidator(
            lambda value: ProductStatus(value) if isinstance(value, str) else value
        ),
    ]
    variants: Connection[Variant]


class Shop(ShopifyModel):
    currencyCode: str = Field(pattern=r"^[A-Z]{3}$")


class ProductsData(ShopifyModel):
    products: Connection[Product]
    shop: Shop


class ProductData(ShopifyModel):
    product: Product | None
    shop: Shop


class VariantView(ShopifyModel):
    id: str
    title: str
    sku: str | None
    price: str
    in_stock: int | None
    inventory_extent: InventoryExtent
    inventory_policy: InventoryPolicy


class ProductView(ShopifyModel):
    id: str
    gid: str
    title: str
    status: ProductStatus
    currency: str
    total_in_stock: int | None
    inventory_extent: InventoryExtent
    variants: list[VariantView]
    next_variants_cursor: str | None


class StockView(ShopifyModel):
    products: list[ProductView]
    count: int
    scanned_count: int
    next_cursor: str | None


PRODUCTS_DATA = TypeAdapter(GraphQLResponse[ProductsData])
PRODUCT_DATA = TypeAdapter(GraphQLResponse[ProductData])
