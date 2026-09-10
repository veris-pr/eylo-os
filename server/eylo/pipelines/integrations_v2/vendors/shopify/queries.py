"""Reviewed Shopify 2026-07 GraphQL documents; caller values stay in variables."""

PRODUCT_FIELDS = """
  id title status
  variants(first: $variantsFirst) {
    nodes { id title sku price inventoryQuantity inventoryPolicy inventoryItem { tracked } }
    pageInfo { hasNextPage endCursor }
  }
"""

PRODUCTS = (
    """
query EyloProducts($first: Int!, $after: String, $variantsFirst: Int!) {
  shop { currencyCode }
  products(first: $first, after: $after) {
    nodes { """
    + PRODUCT_FIELDS
    + """ }
    pageInfo { hasNextPage endCursor }
  }
}
"""
)

PRODUCT = """
query EyloProduct($id: ID!, $first: Int!, $after: String) {
  shop { currencyCode }
  product(id: $id) {
    id title status
    variants(first: $first, after: $after) {
      nodes { id title sku price inventoryQuantity inventoryPolicy inventoryItem { tracked } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

ORDER_UPDATE = """
mutation EyloOrderUpdate($id: ID!, $tags: [String!]!, $input: OrderInput!, $addTags: Boolean!, $setNote: Boolean!) {
  tagsAdd(id: $id, tags: $tags) @include(if: $addTags) {
    node { id ... on Order { tags } }
    userErrors { message }
  }
  orderUpdate(input: $input) @include(if: $setNote) {
    order { id note }
    userErrors { message }
  }
}
"""

CUSTOMERS = """
query EyloCustomers($query: String!, $first: Int!, $after: String) {
  customers(query: $query, first: $first, after: $after) {
    nodes {
      id displayName createdAt numberOfOrders
      defaultEmailAddress { emailAddress }
      defaultPhoneNumber { phoneNumber }
      amountSpent { amount currencyCode }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

ORDERS = """
query EyloOrders($query: String!, $first: Int!, $after: String) {
  orders(query: $query, first: $first, after: $after, sortKey: CREATED_AT) {
    nodes {
      id name createdAt cancelledAt tags
      customer { id }
      totalPriceSet { shopMoney { amount currencyCode } }
      displayFinancialStatus displayFulfillmentStatus
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

ORDER_DETAIL = """
query EyloOrder($id: ID!, $first: Int!, $after: String) {
  order(id: $id) {
    id name createdAt cancelledAt tags note email
    totalPriceSet { shopMoney { amount currencyCode } }
    displayFinancialStatus displayFulfillmentStatus
    lineItems(first: $first, after: $after) {
      nodes {
        id title variantTitle sku quantity
        originalUnitPriceSet { shopMoney { amount currencyCode } }
      }
      pageInfo { hasNextPage endCursor }
    }
    shippingAddress { name city province country zip }
    fulfillments {
      id status createdAt
      trackingInfo { company number url }
    }
  }
}
"""
