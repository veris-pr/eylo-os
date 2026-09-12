# Curated integration catalog

The curated registry is the executable catalog. Vendor and tool contracts live
in Python; installation rows store organization choices, connections, tool
policy, and Agent grants rather than duplicate tool schemas.

## Vendors and tools

The current registry carries 29 vendors and 148 tools.

| Vendor | Auth | Tools |
| --- | --- | ---: |
| Airtable | API key | 5 |
| Asana | API key | 6 |
| Calendly | OAuth 2, API key | 5 |
| Confluence | Basic, OAuth 2 | 5 |
| Dropbox | OAuth 2 | 6 |
| Freshdesk | Basic | 6 |
| GitHub | OAuth 2, API key | 7 |
| GitLab | API key | 6 |
| Gmail | OAuth 2 | 8 |
| Google Calendar | OAuth 2 | 6 |
| Google Docs | OAuth 2 | 4 |
| Google Drive | OAuth 2 | 6 |
| Google Sheets | OAuth 2 | 6 |
| Google Tasks | OAuth 2 | 5 |
| HubSpot | OAuth 2 | 6 |
| Intercom | OAuth 2, API key | 5 |
| Jira | Basic, OAuth 2 | 4 |
| Linear | OAuth 2, API key | 3 |
| Notion | OAuth 2, API key | 5 |
| Outlook | OAuth 2 | 4 |
| PagerDuty | API key | 4 |
| Pipedrive | API key | 5 |
| Sentry | OAuth 2, API key | 4 |
| Shopify | API key | 5 |
| Slack | OAuth 2 | 4 |
| Stripe | API key | 5 |
| Typeform | OAuth 2, API key | 3 |
| Zendesk | Basic | 6 |
| Zoom | OAuth 2 | 4 |

Exact names, descriptions, Pydantic inputs, effects, and scopes are returned by
the curated-vendor API and defined under
`eylo/pipelines/integrations_v2/vendors/`.

## Registry contract

- `CuratedVendorSpec`: identity, categories, fixed or installation-specific
  origin, auth kinds, API-key placement, OAuth metadata, scopes, and static
  non-secret headers. JSON-only `accept_media_type` carries vendor media
  versioning through the executor to the transport; arbitrary `Accept`,
  credential and framing headers remain forbidden in `static_headers`.
- `CuratedToolSpec`: stable `vendor.name` wire ID, display text, effect, input
  model, required scopes, and Python handler.
- `VendorToolContext`: connection identity plus origin-bound `read()` and
  durable `mutate()` methods.
- `ToolExecutionMode`: `auto`, `requires_approval`, or `disabled`, read live at
  execution.

Registration binds each input model to its specific Python handler using generic
types. The decorator returns the original function, preserving direct-call input
and result types. The registry's invocation adapter refuses a different model
before entering vendor code; input schema and invocation come from the same
binding. Duplicate registrations compare original implementation identity.
Bindings exclude functions and model classes from snapshots. The executor still
validates results at the JSON boundary rather than trusting a return annotation.

Invocation arguments must be JSON values, then satisfy the registered vendor
input model. Its existing normalization rules still apply. Handler results must
also be JSON-safe: non-finite numbers, cycles, or arbitrary Python objects return
`tool_result_invalid`, without retrying a potentially completed mutation.
Disabled tools return `tool_execution_blocked`; only an approval-policy refusal
sets the `approval_required` result metadata flag. This flag alone is not a
durable approval wait.

## HTTP payload contracts

Vendor query parameters are flat scalar values or scalar lists/tuples that
repeat a key. Null values are omitted. Nested objects, non-string keys and
non-finite numbers are refused before sending. Existing boolean encoding is
preserved: a scalar becomes `true`/`false`, while repeated boolean values retain
their legacy `True`/`False` spelling.

Request bodies and decoded replies must contain finite JSON values. Invalid
request bodies fail before an outbound receipt or vendor request is created;
invalid replies fail without echoing their contents. Vendor-owned response
models still validate the resource shape after this transport-level check.
Valid request bytes, fingerprints, mutation sequence identities and retry
classification are unchanged. Transport failures use transport-owned error
codes; vendor error vocabularies remain in their adapters.

## Console and widget contracts

The API projects registry metadata and module-owned installation/tool values;
vendor wire objects and encrypted credentials are not part of those responses.
Widget capability groups are resolved against published Agent grants and the
authenticated contact. `connectionKind` is `ORGANIZATION` or `CONTACT`; curated
tools carry `kind: CURATED` and their integration carries `source: curated`.
These are constrained schema values, not free-form labels. A disconnected group
does not grant access: starting authorization still requires the contact-owned
conversation and its pinned Agent's tool grant.

## Typed tool choices

### Stripe billing reads

The five tools are read-only and pin `Stripe-Version: 2026-08-26.dahlia`.
Customer email matching is exact and case-sensitive. `find_customer` returns a
page of matches, not one arbitrarily selected account. Other customer tools accept
either an unambiguous `customer_email` or an explicit `customer_id`. Continue lists
with `starting_after` from `next_starting_after`, retaining the same customer and
filters. [Customer filtering](https://docs.stripe.com/api/customers/list).

Amounts expose precise decimal strings, currency, original minor units and their
availability. Unknown/missing currencies never become USD. ISK and UGX use
Stripe's compatibility representation. `paid` can include an authorization;
inspect `amount_captured` before claiming capture.
[Currency representation](https://docs.stripe.com/currencies),
[charge fields](https://docs.stripe.com/api/charges/object).

Subscriptions retain multiple price items and each item's billing period. Use
`subscription_id` and `items_starting_after` to continue an item's page, preserving
the customer selector. `status=all` includes canceled subscriptions; the ordinary
list excludes canceled subscriptions. Unit prices are not final invoice totals,
particularly for metered or tiered billing.
[Subscription listing](https://docs.stripe.com/api/subscriptions/list).

`get_payment` reads a charge or PaymentIntent and separately queries refunds.
Continue with `refunds_starting_after`; partial pages and unavailable refund status
cannot establish a fully refunded PaymentIntent. Pending or failed refunds are
not successful refunds. The result is a set of live reads, not an atomic financial
snapshot or proof of bank settlement.
[Refund listing](https://docs.stripe.com/api/refunds/list).

Local contracts, official examples and substituted guarded-executor checks passed.
The development deployment loads these schemas; native Stripe account acceptance
remains unverified.

### Shopify commerce contracts

All five curated tools use Admin GraphQL API `2026-07`, with the existing
store-specific token connection and `X-Shopify-Access-Token` credential placement.
The old `2025-01` pin was retired; Shopify falls forward for unsupported pins.
The adapter no longer uses the legacy REST product/variant operations.
[Versioning](https://shopify.dev/docs/api/usage/versioning),
[GraphQL reference](https://shopify.dev/docs/api/admin-graphql/latest).

Customer and order lists expose `cursor`/`next_cursor`; retain the same filters
when continuing. Customer email/phone values are quoted as search data, not
interpreted as operators. Order email resolution refuses multiple matches or an
inexact email rather than choosing the first account; use `find_customer` and an
explicit `customer_id` to disambiguate. The result's `customer_resolution`
distinguishes matched, not found, explicit ID and no customer filter. Returned
orders must belong to the selected customer. Monetary amounts, resource IDs and
uint64 order counts remain decimal strings, avoiding floating-point loss.
[Customer search](https://shopify.dev/docs/api/admin-graphql/latest/queries/customers),
[order search](https://shopify.dev/docs/api/admin-graphql/latest/queries/orders).

`get_order` accepts numeric IDs, numeric strings or Order GIDs, not display order
numbers. Follow `next_line_items_cursor` using `line_items_cursor`; each page has
at most 50 items. Fulfillments retain status/tracking and their `created_at`, not
an invented shipment timestamp. Access to orders older than 60 days requires
Shopify approval and `read_all_orders`; inaccessible is not proof of absence.
[Order access](https://shopify.dev/docs/api/admin-graphql/latest/queries/order).

`check_product_stock` scans up to 25 products per call and filters their titles
locally by case-insensitive substring. This preserves actual substring semantics
instead of substituting Shopify's token search. A page may have no matches and
still have `next_cursor`. Each product exposes up to 10 variants; continue with
its `product_id` and `next_variants_cursor` as `variants_cursor`. Product and
variant cursors cannot be mixed. A product's `total_in_stock` is present only for
a complete tracked variant set. Partial, unavailable and untracked quantities
are explicit; negative inventory remains negative. `inventory_policy` separately
indicates whether the vendor permits overselling. This is not a location-level
inventory export or a snapshot spanning pages.
[Variant inventory](https://shopify.dev/docs/api/admin-graphql/latest/objects/ProductVariant).

`tag_order` uses atomic `tagsAdd`, preserving existing/concurrent tags. The
optional note uses `orderUpdate`; empty text clears it. When both are supplied,
one guarded HTTP request contains two independent operations—not a vendor
transaction. Inspect `tags_outcome`, `note_outcome` and overall `outcome`, which
can be `partial`. Raw vendor errors are not echoed. Contradictory/missing native
acknowledgements return outcome-unknown; receipt replay does not resend them.
The tool bounds requests to 250 tags, 255 characters per tag and 5,000 note
characters; these are adapter input limits, not claims of every vendor limit.
[Atomic tag addition](https://shopify.dev/docs/api/admin-graphql/latest/mutations/tagsAdd),
[order update](https://shopify.dev/docs/api/admin-graphql/latest/mutations/orderUpdate).

Configure token access for `read_customers`, `read_orders`, `read_products` and
`write_orders` as needed by the selected tools; protected customer data may
require Shopify approval. Local typed/executor checks passed and the development
deployment loads these schemas; native account acceptance remains unverified.

### Notion page and block writes

The adapter remains pinned to `Notion-Version: 2022-06-28`; it has not migrated
to the newer data-source API. `create_page` and `append_to_page` use native
request and acknowledgement models. Search, page/block reading and database
querying are also typed as described below. Local contract verification is not
a claim of live Notion account acceptance.

Use `parent_kind=page` or `database`. The deprecated strict boolean
`parent_is_database` remains accepted, but supplying both selectors is refused.
IDs must be UUIDs or HTTPS Notion page URLs. Page titles use the stable `title`
property ID, so a renamed database title column does not require a lookup.

Writes preserve empty lines and split long lines into rich-text runs of at most
2,000 characters. More than 100 paragraph lines, input beyond 100,000 characters,
or a serialized request over 500 KB is refused before sending. Content is never
silently truncated. Split oversized text across separate tool calls.

Acknowledgements distinguish `identity_only`, `page_metadata_verified`, and
`block_text_verified`. Notion's response contract permits partial resources,
including for integrations without read access; a valid ID-only response is not
mistaken for an empty or malformed response. Full create responses must match
the requested parent and title. Append validates count, unique block IDs and any
returned parent/text. `body_blocks_submitted` describes the create request, not
a separate body readback. An uncertain acknowledgement is an error; durable
mutation receipts prevent automatic resend of a possibly completed write.

Sources: [version-matched SDK contracts](https://github.com/makenotion/notion-sdk-js/blob/v2.2.15/src/api-endpoints.ts),
[request limits](https://developers.notion.com/reference/request-limits),
[property identities](https://developers.notion.com/reference/page-property-values).

### Notion database query contracts

`query_database` accepts `property_name` with exactly one of `equals` or
`contains`, or no filter. Text properties support both operators; select/status
require equals, multi-select requires contains, and checkbox/number require
equals. Checkbox text must be true/false; numbers must be finite. Unsupported
operator/type pairs are refused, not translated into a different comparison.
The schema read resolves the property's name to its native ID. A query POST is
a read operation and does not create a mutation receipt.

Pass `start_cursor` with the same query to continue. Results expose `next_cursor`;
an empty valid result is distinct from missing or malformed vendor data. Schema
and returned row database identities are checked. Property projections preserve
false, zero, empty text, date ranges and user IDs. `property_extents` distinguishes
inline values, incomplete relations, possible reference limits, and types not
projected by this tool. This query is not a full property-item export: pagination
of long individual properties and full rollup/file projections are not implemented.

[Version-pinned database filters](https://developers.notion.com/reference/post-database-query-filter),
[property response limits](https://developers.notion.com/reference/page-property-values).

### Notion search and page reading

Search matches shared page/database titles, not body text. `only` accepts page
or database; repeat the same query with `start_cursor` to continue. Responses
retain `next_cursor` and distinguish an empty title from unavailable metadata.

`read_page` paginates block children and walks structural containers, with at
most 20 child-list requests and three nested levels per call. `state=partial`
and `omitted` identify request/depth limits, unsupported block types and unavailable
metadata. Each omission includes its block ID and any continuation cursor.
Use the same page ID plus an ordinary descendant `block_id`/`start_cursor` to
read another subtree. A bounded ancestor check prevents another page's subtree
being mislabeled. Synced containers accept the native source-parent identity;
transcluded children are not physical descendants of the containing page, so
resume those from the accessible synced container rather than directly by child ID.

Rendered text is capped at 20,000 characters per result. Repeat the same inputs
with `next_text_offset` as `text_offset` for the remainder of that traversal
window. These are live reads: edits between calls can change offsets or cursors.
Headings, lists, checkboxes, code text, table rows and named child pages are
projected. Images/files/other unsupported block bodies are reported as omissions;
the tool does not download assets or promise exact visual rendering.

[Block pagination](https://developers.notion.com/reference/get-block-children),
[version-matched block and search contracts](https://github.com/makenotion/notion-sdk-js/blob/v2.2.15/src/api-endpoints.ts).

### Zoom meeting contracts

The four tools use native meeting/settings/occurrence models, strict IDs and
typed requests/results. Meeting numbers are int64 in vendor JSON but strings in
tool results, separate from instance UUIDs. Lists expose cursor or page-number
continuation and mark provider-truncated agendas; `get_meeting` returns full
details and available recurring occurrence IDs. The list is not an exhaustive
past-meeting archive. Host start URLs are not projected into results.

Scheduling requires an offset or explicit IANA timezone. Aware timestamps retain
their instant even with a named timezone; the request sends UTC. Ambiguous or
nonexistent DST local times require an offset. Past starts are rejected before
sending because Zoom would replace them with the current time. Creation requires
a 201 response matching the requested topic, instant, type and duration. Returned
waiting-room settings reflect account policy; the requested mode is separate.

Cancellation first reads the meeting. A recurring meeting requires a known
available occurrence or explicit `scope=series`; omission cannot silently delete
a whole series. Active, instant and personal meetings are refused by this
scheduled-meeting tool. Successful deletion requires 204 with an empty parsed
body. Notification choices request host emails, registrant emails, both or neither;
they do not confirm delivery or claim a live call has ended. The preflight is not
an atomic lock on remote state.

The catalog uses Zoom's accepted **legacy user-level** `meeting:read` and
`meeting:write` scopes, not granular scopes. Cancellation now declares read access
for its preflight; list no longer requires unrelated `user:read`, which was also
removed from future consent requests. Existing credentials were not changed.
[Current meeting reference](https://developers.zoom.us/docs/api/meetings/),
[vendor OpenAPI contract](https://developers.zoom.us/api-hub/meetings/methods/endpoints.json).

### Gmail message, MIME and label contracts

All eight tools use Gmail-native resource/request models and typed result views.
IDs remain opaque strings escaped below the connected mailbox route. Missing
message/draft identities and mismatched acknowledgements are errors, not successful
null-filled results. Empty repeated collections may be omitted by Google's JSON
encoding; that is distinct from a missing individual message.

Search returns `next_page_token` and a result-size **estimate**. Thread reads return
messages ordered by internal timestamp with `next_before_message_id` for older
pages. Body excerpts retain the existing 8,000-character bound but now expose
`next_body_offset` through `read_message`; long bodies are not irretrievably cut
off. Each search result needs one bounded metadata lookup; thread reads use the
thread resource instead. [Listing](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list),
[thread retrieval](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads/get).

The MIME reader distinguishes body parts from named/attachment-disposition
subtrees. Alternatives prefer text, including intentionally empty text. It
honors the declared charset and rejects corrupt base64 or inconsistent sizes.
Externally stored body parts can be fetched, with limits of 256 MIME nodes and
10 body-part fetches per message. Named attachments remain metadata only.
Unsupported MIME types are explicit; HTML-only bodies retain their format,
while mixed text/HTML parts use a basic flattened text projection.
[Part body contract](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments).

Replies/drafts preserve the latest non-draft parent's subject and threading
headers. Threaded drafts reject a different subject instead of merely attaching
`threadId`. The draft tool now requires both `gmail.compose` and `gmail.modify`
because its parent lookup needs read access. Both scopes already belong to the
vendor OAuth catalog, but a partial grant may need renewed consent. Reply-all
excludes the primary address returned by the account profile; send-as aliases
are not enumerated. A successful send reports `submitted`, not delivery.
[Threading requirements](https://developers.google.com/workspace/gmail/api/guides/threads).

Label resolution uses one catalog read, refuses ambiguous names and conflicting
resolved IDs, and preflights removals before creating anything. Optional label
creation and message modification are separate receipt-backed effects, not one
atomic vendor transaction; partial failures can leave created labels. Modified
labels and Trash acknowledgements are checked against the requested message.
Trash does not promise a fixed recovery period or perform permanent deletion.
`mailbox_range`, `recipients` and `missing_labels` are enum choices; their legacy
boolean inputs remain deprecated and mutually exclusive with the new fields.

### Outlook mailbox contracts

The four Graph mail tools validate native message and recipient envelopes instead
of treating missing data as empty success. Message IDs remain opaque strings;
they are escaped as path segments under the shared egress policy.

`search_messages` returns one page, its ordering and `next_page_url`. Repeat the
same search options when continuing, including after an empty filtered page.
Free-text searches retain sender/read predicates by applying them to each returned
page; Graph's search limit remains 1,000 results. Filter-only requests omit ordering
that would cause Graph's `InefficientFilter` error. Continuation is restricted to
the same Graph mailbox route and query; the returned query is preserved, not a
reconstructed skip token. [Graph message listing](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0),
[search semantics](https://learn.microsoft.com/en-us/graph/search-query-parameter).

`get_message` requests text bodies. Literal angle brackets, newlines and empty
text remain unchanged. If Graph returns HTML instead, a basic flattened text
fallback applies; this is not a layout renderer or attachment downloader.
[Graph message read](https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0).

Send/reply require **202 Accepted** with an empty parsed body. Their result is
`state=accepted`, not delivery confirmation; no message ID is invented. Existing
outbound receipts prevent resending an uncertain accepted mutation on replay.
Blank/invalid recipients are rejected before sending rather than silently removed.
`read_state`, `sent_copy` and `recipients` are enum choices. Their legacy boolean
inputs remain deprecated compatibility inputs; supplying both forms is rejected.
[Sending](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0),
[replying](https://learn.microsoft.com/en-us/graph/api/message-reply?view=graph-rest-1.0).

### Slack channel, message and directory contracts

The four curated Slack tools use vendor-owned requests, strict success envelopes
and typed result projections. HTTP success alone is insufficient: `ok` must be a
JSON boolean and the operation's required collection or acknowledgement must be
present. Errors do not echo arbitrary Slack response text. Wire methods and
platform-owned failure categories are enums; extensible native warning/subtype
tags remain strings and do not drive a platform lifecycle.

`list_channels` returns one public-channel page with `next_cursor`. Name filtering
applies to that page, so an empty match set may still have a continuation. Automatic
channel-name resolution follows up to ten pages; exhausting that budget requires
a channel ID rather than claiming the channel does not exist. Repeated lookup
cursors are refused. [Slack channel pagination](https://docs.slack.dev/reference/methods/conversations.list/).

`read_channel` preserves returned message order and exposes `next_cursor`, or an
exclusive `next_latest` boundary when only time pagination is available. Slack may
return fewer items than requested; history limits depend on the app's distribution
category. The adapter does not assume the higher internal/Marketplace quota or
automatically loop over history pages. Author names use bounded directory pages,
not one request per message; unresolved IDs are disclosed. Bot identity, attachment
text and file metadata are retained. Block types are identified as unrendered;
file bytes and thread replies are not fetched by this tool.
[Slack history](https://docs.slack.dev/reference/methods/conversations.history/),
[Slack directory](https://docs.slack.dev/reference/methods/users.list/).

`post_message` accepts at most 40,000 characters and verifies the acknowledged
channel, timestamp and requested thread. It returns Slack's actual text because
Slack may normalize it; warnings remain visible. The existing durable outbound
receipt owns the mutation. An accepted but malformed response is not permission
to resend it. `permalink_hint` remains a channel/timestamp hint, not a fetched URL
or delivery/read confirmation. The tool does not join channels or add scopes.
[Slack posting](https://docs.slack.dev/reference/methods/chat.postMessage/).

Email lookup retains native user identity and reported account flags; absent
flags remain unknown rather than becoming an active account. Returned email, when
present, must match the lookup. Live Slack acceptance is still separate from the
local contract/executor checks.
[Slack email lookup](https://docs.slack.dev/reference/methods/users.lookupByEmail/).

### Confluence page and search contracts

The five curated tools use v2 page/space models and v1 search models, distinct
from the Confluence SOR adapter. Missing envelopes do not become successful empty
lists or pages. Numeric page identities, versions, content states and space types
are validated. Simple CQL filters escape quotes and backslashes; raw CQL remains
an explicit override and must select pages.

Space lists and search expose `cursor`/`next_cursor`. The optional space query
filters each returned page locally, so zero matches with a continuation token
does not mean no matching space exists. Pagination tokens are extracted from
body/Link metadata; conflicting or repeated tokens are refused. Subsequent
requests rebuild the known endpoint and original filters, never follow the
returned URL. Search now includes the source link it previously advertised but
omitted. [Search reference](https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-search/),
[spaces reference](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-space/).

Page reads request storage format. Missing requested content is an error; empty
content is an empty string. Text extraction is a flattened reading aid, not a
macro/layout renderer or attachment fetcher. Creates require an unambiguous exact
space key and validate the acknowledged title, space and explicit parent. Updates
only edit currently published pages and verify the acknowledged identity, space,
title and incremented version. They never silently restore/publish another state
or retry a conflict with a newly fetched version. Both writes retain one durable
outbound receipt. [Page operations](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/).

The catalog now declares **granular** scopes: `read:page:confluence`,
`write:page:confluence`, `read:space:confluence`, and search's granular alternative
`read:content-details:confluence`. Existing OAuth authorizations may need new
consent. Basic API-token connections do not use the OAuth scope check.

Curated Jira/Confluence OAuth binds the configured site to a cloud ID through
`accessible-resources` after code exchange. Matching requires the exact site and
requested product scopes; absent or ambiguous matches fail instead of selecting
the first resource. The typed binding stays inside the existing encrypted
connection credentials. Tool calls use the pinned
`api.atlassian.com/ex/{product}/{cloudid}` gateway with the registry's API suffix.
Basic auth continues to use the configured site directly. Legacy OAuth credentials
without this binding require reconnection; no site is assigned automatically.
Local checks cover routing, encryption, refusal and refresh; live account
acceptance remains pending.
[Atlassian 3LO routing](https://developer.atlassian.com/cloud/oauth/getting-started/making-calls-to-api/).

### Airtable record and schema contracts

All five tools validate native response envelopes before returning results.
Bases and records expose `offset`/`next_offset`; continue with the same record
filter and view. `limit` bounds one page, not the entire collection. Missing
collections, duplicate IDs and repeated cursors fail visibly.
[Base pagination](https://airtable.com/developers/web/api/list-bases),
[record pagination](https://airtable.com/developers/web/api/list-records).

Records return `id`, `created_at`, `fields` and optional `details`. Custom cells
remain under `fields` so a user column named `id` cannot replace record identity.
Cell names and values are user-defined finite JSON; envelope fields and native
field-type enums are vendor-owned contracts. Tables expose field and view IDs
alongside names. The tools do not fetch attachment URLs.
[Native cell types](https://airtable.com/developers/web/api/field-model).

Filtering accepts a field name or ID plus exactly one of `equals` or `contains`.
Table names are URL encoded without trimming. Names containing path separators
or dot-segments resolve through the base schema to table IDs; field names with
formula delimiters resolve to field IDs. Those lookups require
`schema.bases:read`. Passing IDs avoids them. Ordinary record reads/writes retain
their `data.records:read`/`data.records:write` requirements; no new OAuth mode or
automatic scope grant is introduced.
[Base schema and scope](https://airtable.com/developers/web/api/get-base-schema).

Writes retain Airtable's existing best-effort `typecast` behavior; updates use
PATCH, never destructive PUT. The acknowledgement must include a valid record;
updates also require its ID to match the request. Native partial-attachment
outcomes are returned in `details`, not hidden as unconditional success. Because
type conversion and omission of empty cells are vendor behavior, the returned
fields describe the actual acknowledgement rather than an invented exact-value
verification. Each mutation still uses one durable outbound receipt.
[Create records](https://airtable.com/developers/web/api/create-records),
[update record](https://airtable.com/developers/web/api/update-record).

### Typeform form and submission contracts

All three read tools validate native payloads before projecting agent results.
`list_forms` exposes `page`/`next_page`; `list_responses` exposes
`before`/`next_before` tokens. Keep filters unchanged while continuing. A full
response page can require one final empty request; the tool does not silently
declare that a capped collection is complete. See the vendor's
[form listing](https://www.typeform.com/developers/create/reference/retrieve-forms/)
and [response pagination](https://www.typeform.com/developers/responses/walkthroughs/).

Response selection uses `response_type`: `completed`, `partial`, or `started`.
The deprecated `completed_only` input remains compatible (`true` selects
completed; `false` selects started), but cannot be combined with the enum.
The native request uses the supported enum parameter rather than the deprecated
boolean. The selected filter, checked against any returned native state, owns
completion—not the truthiness of Typeform's legacy year-one timestamp.
[Responses reference](https://www.typeform.com/developers/responses/reference/retrieve-responses/).

Nested form fields are flattened in document order with `parent_id`; answer IDs
are joined to that complete question map. A removed question retains its field
ID and answer with an explicit unresolved label. Tagged answer models cover text,
contact/link values, dates, numbers, booleans, choices, payments, media and
signatures. Unknown or malformed variants fail visibly, not as empty answers.
Media/file URLs remain references; the tools do not download them. Hidden fields
remain a string map because their names belong to the form author. Payment fields
follow the vendor's native type declaration; no financial outcome is inferred.
[Answer contracts](https://www.typeform.com/developers/responses/JSON-response-explanation/),
[vendor types](https://github.com/Typeform/js-api-client/blob/main/src/typeform-types.ts).

The configured origin remains `api.typeform.com`; separate EU stacks are not
added by this contract pass. Native account acceptance remains unverified.

### PagerDuty and Sentry operations

PagerDuty's four read-only tools validate native incidents, notes, services and
on-call entries against vendor-owned models. The catalog pins REST v2 through
`application/vnd.pagerduty+json;version=2`. Incident searches explicitly cover
all dates rather than silently inheriting the API's default date window.

- Incident, service and on-call lists expose `next_offset`; counts describe
  the returned page. On-call continuation also requires the returned `as_of`
  so pagination keeps the same time window.
- Service lookup scans at most ten 100-item pages. It refuses an incomplete
  catalog or ambiguous name, gives an exact ID priority over a name match, and
  never chooses the first similarly named service.
- Incident detail confirms the returned ID or incident number before reading
  notes. Separate on-call policies/shifts for one person remain separate;
  missing email is not inferred from a display name.
- Missing collections, invalid pagination and malformed references fail as
  tool errors, not empty successful results.

These contracts follow the maintained
[PagerDuty REST v2 OpenAPI](https://github.com/PagerDuty/api-schema/blob/main/reference/REST/openapiv3.json).

Sentry's four tools validate issues, event exception entries, stack frames and
status-change acknowledgements. Decimal event counts become integers; source
context becomes structured line/text pairs, capped at 4,000 text characters per
frame. Unknown non-exception entry bodies are discarded, but malformed exception
entries cannot bypass validation as an unknown entry.

- Lists expose `next_cursor` from the
  [Sentry pagination Link header](https://docs.sentry.io/api/pagination/).
  Only Link metadata crosses the private response boundary; cookies and other
  headers do not. Pagination URLs are never followed. The adapter validates the
  origin/path and forwards only the cursor to its fixed route.
- Resolve/ignore confirm the returned issue ID and status. A null body, wrong
  ID or unchanged status is a failure. Results no longer assert future reopening,
  notification or retention behavior that the acknowledgement cannot prove.
- All four tools use explicit organization-scoped routes. `list_issues` sends a
  required project slug to the
  [organization issues endpoint](https://docs.sentry.io/api/events/list-an-organizations-issues/),
  replacing the deprecated project issue-list route. Missing/mismatched response
  project identities are refused; the all-projects sentinel is not accepted.
  `groupStatsPeriod=14d` selects chart statistics, not a 14-day issue-age filter.
  Detail, resolve and ignore now require `organization` alongside `issue_id`;
  old ID-only inputs fail validation before credential resolution or any send.
  Results carry the organization for follow-up calls. Tool names and bindings
  remain unchanged; no organization is guessed and no DB migration is needed.
  Native issue/event shapes and organization-scoped routes follow the
  [issue](https://docs.sentry.io/api/events/retrieve-an-issue/) and
  [event](https://docs.sentry.io/api/events/retrieve-an-issue-event/) references;
  [update route](https://docs.sentry.io/api/events/update-an-issue/) changes only
  the requested status. API-key authorization uses exactly one Bearer separator.

PagerDuty status/urgency and Sentry state inputs retain case/whitespace
normalization. Limits and offsets require integers rather than booleans.
These changes do not add grants, vendor writes or alternate receipt ownership.
Response-validation failure does not authorize a repeated mutation.

API-key prefixes are exact vendor-owned wire fragments. `ApiKeyPlacement` uses
`Bearer `, `Token token=`, or an empty prefix; the credential builder appends the
key without inserting a separator. This preserves
[PagerDuty's documented header](https://github.com/PagerDuty/api-schema/blob/main/reference/REST/openapiv3.json)
and produces one space for Bearer declarations. Multiple Bearer spaces are allowed
by [RFC 6750](https://www.rfc-editor.org/rfc/rfc6750#section-2.1); normalization is
not evidence that a vendor previously rejected the token. Origin-bound placement,
secret exclusion from snapshots, and malformed credential refusal remain enforced.

### Existing typed choices

GitHub issue search and pull-request listing expose `open`, `closed`, and `all`
as enum choices. `all` is a query option, not an issue or pull-request state.
Freshdesk ticket search/create/update expose built-in status and priority names
as enums; the vendor handler translates them to
[Freshdesk's documented integer codes](https://developers.freshdesk.com/api/#tickets).
These types belong to their curated vendor implementations, not the platform's
canonical ticketing/support domains.

GitLab issue search exposes `opened`, `closed`, and `all`; merge-request listing
also exposes `merged`. The query enums remain separate so an issue cannot accept
`merged`. These retain the existing curated subset of the
[GitLab issue](https://docs.gitlab.com/api/issues/#list-project-issues) and
[merge-request](https://docs.gitlab.com/api/merge_requests/#list-project-merge-requests)
filters; the vendor's additional `locked` MR filter is not exposed yet.

Intercom conversation search exposes `open`, `closed`, and `snoozed`. Its internal
reply path uses a vendor message-type enum for `comment` versus `note`, matching
the pinned [Intercom 2.11 contract](https://developers.intercom.com/docs/references/2.11/rest-api/api.intercom.io/conversations/replyconversation.md).
The public `reply_to_conversation` tool still requires `visible_to_customer`,
without a default; `add_note` always selects an internal note.

These four vendors retain case-insensitive, whitespace-tolerant valid inputs. Invalid
choices return `tool_input_invalid` before credential resolution or vendor I/O.
Freshdesk optional search/update choices retain empty-string omission; an update
with no changes still returns `no_change_requested`. Unknown native status or
priority values in responses remain available rather than being discarded.
Intercom also retains optional empty-string omission. A search without a contact
email or state returns `search_unbounded`. Invalid state is now refused before
the contact lookup, including when that lookup would have returned no contact.

### Freshdesk request and response contracts

All six Freshdesk tools validate vendor responses before projecting agent
results. Request, response, and result models remain inside the Freshdesk adapter;
they are not the platform's canonical customer-support entities. Request fields
are closed; unrelated vendor response fields are ignored, not passed to agents.

- Ticket list/detail request `include=requester` and read the nested requester's
  email. Search-index and mutation responses may not include it; those results
  return `null`, without inventing an email or making per-ticket contact calls.
- Requester email uses the ticket-list query parameter, not the search-index
  query language. Combined status/priority filters apply to that requester list.
  List-based queries retain Freshdesk's recent-ticket window (past 30 days).
- Reads paginate within a bounded budget: at most ten pages, up to 100 results.
  `coverage` distinguishes `exhausted`, `result_limit`, and `scan_limit` within
  the chosen query. The status/priority search index can lag changes.
- Ticket detail includes the first 30 conversation entries when requested.
  Incoming messages and public notes are not labelled outgoing customer replies.
- HTTP failures, malformed records, mismatched IDs, and unconfirmed private-note
  visibility fail as tool errors. Raw vendor error text is not returned.

These wire shapes follow the [Freshdesk v2 API](https://developers.freshdesk.com/api/).
Mutations retain their existing request-body bytes and outbound-attempt owner.
A response-validation failure does not authorize a repeat send. Replaying an
existing outbound receipt still cannot reconstruct its response body; the shared
client returns `vendor_outcome_unknown` without sending again.

### Zendesk request and response contracts

All six curated Zendesk tools use vendor-owned nested request, response and
result models. The separate Zendesk SOR implementation is not reused here.
Ticket status and priority inputs expose named enums; case/whitespace normalization
and optional empty-string omission remain supported. IDs and limits require JSON
integers, not booleans; the existing `public` and `include_comments` arguments
require JSON booleans. `public` remains required, without a default.

- Search reads one page, at most 100 tickets. Detail optionally reads the first
  30 comments, not the complete conversation. User lookup reads one search page.
  These operations do not follow returned pagination URLs or add per-record I/O.
- Comments prefer `plain_body`, falling back to `body`, clipped to 6,000 characters.
  Dates keep their native spelling. Unknown native status, priority, role and
  channel values remain readable; unrelated extensions are not projected.
- Missing lists, malformed records and mismatched ticket IDs fail rather than
  becoming empty/successful results. Error diagnostics are not echoed to agents.
- Mutation bodies preserve omission/null behavior and empty-tag replacement.
  Response validation happens after the existing durable outbound owner; an
  invalid reply does not authorize a resend.

Native authorities: [tickets](https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/),
[comments](https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_comments/),
[search](https://developer.zendesk.com/api-reference/ticketing/ticket-management/search/),
and [users](https://developer.zendesk.com/api-reference/ticketing/users/users/).
Local contract/guarded-client probes are not live Zendesk verification.

Existing result caveat: `add_comment.emailed_customer` reflects the requested
`public` flag, not confirmed email delivery. Do not interpret it as a delivery
receipt; notification behavior depends on Zendesk configuration. Correcting that
legacy result contract remains tracked in the typing plan.

### Intercom request and response contracts

All five curated Intercom tools validate consumed native fields and use
vendor-owned request and result models, separate from SOR entities. The adapter
retains `Intercom-Version: 2.11`; this work does not migrate the app's API version.

- Contact lookup sends one exact-email search with `per_page=1`. A valid empty
  list means not found; a missing/malformed list means tool failure. The company
  count is the number of embedded company references, not an exhaustive total.
- Conversation search requires a contact email or state. It reads one page,
  capped at 50 results; multiple filters use AND. POST searches remain read-only
  operations, not durable mutations.
- Detail requests plain text and retains the opening message plus comment/note
  entries from the first 50 returned parts, in vendor order. Bodies are clipped
  to 6,000 characters. This is not a complete history export: Intercom also caps
  native retrieval at its 500 most recent parts.
- Reply visibility remains an explicit required JSON boolean. An internal note
  sends `message_type=note`; a customer reply sends `comment`. Malformed or
  mismatched response IDs fail rather than borrowing the requested ID as proof
  of success. Validation failure never authorizes a repeat send.
- Known request choices use enums; native response extensions remain readable.
  Explicit null fields stay present in projections. Vendor error text is not
  echoed to the agent. No additional per-record I/O or retry loop is introduced.

Version-matched authorities: [contact search](https://developers.intercom.com/docs/references/2.11/rest-api/api.intercom.io/contacts/searchcontacts),
[conversation search](https://developers.intercom.com/docs/references/2.11/rest-api/api.intercom.io/conversations/searchconversations),
[retrieval](https://developers.intercom.com/docs/references/2.11/rest-api/api.intercom.io/conversations/retrieveconversation),
and [replies](https://developers.intercom.com/docs/references/2.11/rest-api/api.intercom.io/conversations/replyconversation).
Local contract and guarded-client checks do not prove live Intercom acceptance.

### GitHub request and response contracts

All seven curated GitHub tools use vendor-owned request, response and result
models. SOR types do not enter this boundary. Responses validate consumed fields;
unrelated additions and native open vocabulary remain compatible.

- Search/list operations read one page, at most 50 records. Issue detail reads
  the first 20 comments; pull request detail reads the first 50 files and first
  20 reviews. Bodies are clipped to 6,000 characters. These are bounded views,
  not exhaustive histories. Search does not currently project GitHub's
  `incomplete_results` indicator; its total is not proof of exhaustive coverage.
- The existing `approved` result means an approval appears in the returned
  review page. It does not evaluate the latest review per reviewer, branch
  protection, required checks or whether merging is permitted.
- Native label names are preserved for both string and object label forms.
  Nullable users remain null authors; absent optional pages remain absent.
  Explicit null dates/body/mergeability remain visible. Dates are not rewritten.
- Missing/malformed lists or identities fail instead of becoming empty results
  or null-filled successes. Requested issue/pull numbers must match the reply.
  Fixed error codes/text replace raw vendor diagnostics. A malformed mutation
  reply never authorizes a repeat send.
- Request field order, omission, single-write authority and public defaults are
  unchanged. IDs/limits require JSON integers; existing boolean arguments require
  JSON booleans. The legacy create-PR `base_branch=main` default remains; this is
  not automatic repository-default-branch discovery.

The current adapter sends no API-version header. GitHub's documented unversioned
default is `2022-11-28`; the consumed contracts were checked against its
[version-specific OpenAPI schema](https://github.com/github/rest-api-description/blob/main/descriptions/api.github.com/api.github.com.2022-11-28.json).
No upgrade to `2026-03-10` was performed. An explicit pin/version migration remains
separate work; see [GitHub API versioning](https://docs.github.com/en/rest/about-the-rest-api/api-versions).
Local contract/guarded-client probes and public examples are not live acceptance
with an organization's configured GitHub installation.

### GitLab request and response contracts

The six curated GitLab tools use vendor-owned REST v4 models, separate from SOR
types. Consumed nested records, lists, resource IDs and predicates are validated;
raw vendor diagnostics are not echoed. The instance URL supplies the origin and
`/api` root. REST operations use `/v4`; a fixed `/graphql` read resolves named
projects. No self-managed GitLab release is inferred or pinned.

Use a positive numeric ID or literal `group/subgroup/project` path, not a full
URL or pre-encoded value. Names resolve once per invocation via
`project(fullPath: ...)`, then REST operations use the validated numeric ID.
Numeric inputs skip this lookup. Missing/inaccessible projects produce
`project_unavailable`, not a successful empty list. Tokens need `read_api` for
reads or `api` for writes. PRIVATE-TOKEN placement is unchanged.
[GraphQL identity/access](https://docs.gitlab.com/api/graphql/),
[token headers](https://docs.gitlab.com/user/profile/personal_access_tokens/).

- Issue creation resolves up to 20 supplied usernames through exact username
  lookup before writing. Repeated names resolve once, case-insensitively. Missing,
  ambiguous or malformed lookup results refuse creation; no partial assignment
  or fallback unassigned issue is sent. This is an Eylo lookup bound, not a
  vendor tier limit. A single assignee uses `assignee_id`; multiple use
  `assignee_ids` and require the vendor's corresponding tier support.
- Search sends its optional assignee as the documented array query parameter.
  Issue/MR lists remain one page, at most 100 records. Issue detail filters system
  activity from the first 20 notes ordered oldest-first; it does not fetch the
  complete conversation. Descriptions/comment bodies retain the 6,000-character
  clipping bound. Dates and explicit nulls are preserved.
- Detail replies must match the requested IID and resolved project ID, including
  named inputs. Lists and creation replies also check the project ID.
  A created comment uses its returned issue identity after checking
  it, rather than treating the requested IID as confirmation of success.
  Missing change lists fail; they do not become zero-change summaries.
- Merge-request detail retains the existing v4 `/changes` endpoint, deprecated
  in GitLab 15.7 and planned for removal in v5. No migration to paginated `/diffs`
  is implied. The existing result does not project native `overflow`; file count
  reflects the returned changes, not proof of exhaustive diff coverage. Merge
  status/conflict data is not an approval or merge-permission decision.
- Creation without assignees and comment writes preserve their existing body
  ordering/omission and single durable write. Username resolution deliberately
  replaces the unsupported create-body `assignee_usernames` field. Validation of
  a bad post-write response never authorizes a second send.

Authorities: [issues](https://docs.gitlab.com/api/issues/),
[users](https://docs.gitlab.com/api/users/), [notes](https://docs.gitlab.com/api/notes/),
[merge requests](https://docs.gitlab.com/api/merge_requests/), and
[v4 deprecations](https://docs.gitlab.com/api/rest/deprecations/).
All six executor paths passed with substituted HTTP/auth/receipt storage. Four
read tools also passed against a public GitLab project through real guarded HTTPS,
including named-project lookup. Authenticated installation and native mutation
acceptance remain open; public reads do not establish token permissions.

### Jira request and response contracts

All four curated Jira tools use vendor-owned Cloud REST v3 models. They retain
the instance-specific `/rest/api/3` route and existing auth configuration; this
does not establish Data Center compatibility or live OAuth acceptance.

- Search uses one enhanced `/search/jql` POST page, up to 100 requested records.
  `count` counts returned records, not all matches; continuation is not exposed.
  Simple-filter values escape quotes/backslashes; explicit raw JQL stays explicit.
- Project/type resolution and optional user lookup precede one create write.
  User search is prefix-based across attributes, so assignment now requires one
  exact visible email match in the returned page. Hidden/missing/ambiguous email
  refuses creation, without guessing or falling back to an unassigned issue.
  Lookup retains the vendor-default 50-result page; it does not scan every user.
- Consumed fields validate before projection. Missing optional selected fields
  and privacy-hidden email remain null. Resource IDs and mutation acknowledgements
  cannot silently disappear. HTTP failures and field-keyed errors are failures,
  not empty success. Invalid post-write replies do not cause a second send.
- Plain-text writes use typed ADF paragraphs. Reads flatten text and paragraph
  breaks; this is not a full document/media renderer. Existing plain-string
  descriptions are accepted. Published issue examples contain integer `updated`
  values; those remain integers, without inventing a timestamp unit.
- Existing request ordering, omission and result shapes are preserved for valid
  inputs. Issue/project path values are encoded as components. Historical issue
  keys may resolve to a new key, so returned keys are not compared for equality.

Authorities: [enhanced search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/#api-rest-api-3-search-jql-post),
[issues](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/),
[projects](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-projects/),
[user search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-user-search/#api-rest-api-3-user-search-get),
[comments](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-comments/),
and the [published v3 schema](https://dac-static.atlassian.com/cloud/jira/platform/swagger-v3.v3.json).
The create tool declares classic `read:jira-user` for its lookup; that scope was
already part of the vendor OAuth configuration. Local contract checks are not
native Jira, persisted-receipt or widget acceptance.

### Asana request and response contracts

All six curated tools use Asana-owned API 1.0 requests, native `data` envelopes,
nested task/project/story models and result projections. PAT/Bearer transport
remains unchanged; this does not add OAuth support.

- Task and project lists remain one page, at most 100 requested records. Project
  name lookup checks the first 100 projects in the first visible workspace;
  duplicate names require a gid. The existing optional workspace behavior still
  selects the first returned workspace. No cross-workspace search is implied.
- Project plus assignee filters now work together. One additional read obtains
  that project's workspace, because the native assignee filter requires it.
  A mismatched project response refuses the query; no workspace is guessed.
- Task detail uses the returned story page, filters `type=comment` and clips
  notes/comment text at 6,000 characters. This is not complete comment history.
  Notification delivery after adding a comment is not confirmed by the receipt.
- Bad HTTP statuses, missing native envelopes, malformed records and nested
  values fail rather than becoming empty success. Completion requires a matching
  task gid and a true completion flag. No invalid response triggers a resend.
- Existing valid request omission, ordering and projections are retained, except
  the deliberately corrected combined filter. Public predicates/limits are now
  strict: string booleans and boolean-as-integer limits are rejected.

Authorities: [task queries](https://developers.asana.com/reference/gettasks),
[task creation](https://developers.asana.com/reference/createtask),
[task models](https://developers.asana.com/reference/tasks),
[project reads](https://developers.asana.com/reference/getproject),
[stories](https://developers.asana.com/reference/stories), and the
[official OpenAPI](https://raw.githubusercontent.com/Asana/openapi/master/defs/asana_oas.yaml).
Local transport/contract probes do not prove native acceptance or durable DB recovery.

### Google Docs request and response contracts

All four tools use Google Docs v1 request, response and result models. Reads
request `includeTabsContent=true`, traverse nested tabs in display order, and
return tab IDs alongside body text. An optional `tab_id` selects one tab. Heading,
table and table-of-contents text is preserved; non-text paragraph elements receive
a visible marker. This is not a rich-document renderer: headers, footers,
footnotes and image content are not read. Output is bounded to 20,000 characters,
with the full extracted character count and a truncation flag.

Append targets the first tab unless one is selected. It uses the final native
UTF-16 index, not Python string length, and sends `requiredRevisionId` so a
concurrent edit refuses the write instead of silently shifting its position.
Replace retains Google's all-tabs behavior unless a tab is selected. Its reply
must contain the matching operation; an omitted zero occurrence count within
that operation is valid, but an absent reply is not.

Creation with content is two separately receipted writes, not atomic. A body
write failure can leave an empty document. Every successful mutation validates
its document ID and corresponding reply slot before reporting success. Invalid
acknowledgements never authorize a resend; durable replay still reports
`vendor_outcome_unknown` when the shared receipt cannot reconstruct the response.

Authorities: [document tabs](https://developers.google.com/workspace/docs/api/how-tos/tabs),
[native requests](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request)
and [batch updates and revision control](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate).

### Google Drive request and response contracts

All six tools use selected Drive v3 fields and typed projections. Search returns
one page, a continuation token and Google's incomplete-search flag; it does not
claim exhaustive results. The explicit `drive#fileList` discriminator distinguishes
a valid empty page from an unrelated empty object. File size retains the native
numeric-string representation; privacy-hidden owner email remains null.

Folder-name resolution follows at most five pages, rejects ambiguous or partial
results, and validates ID fallbacks as active folders. The `root` alias resolves
to Google's actual folder ID before parent comparisons. Create, move and trash
validate the returned identity/type/parent or trash state as applicable. A move
already at its destination performs no write.

Sharing retains the existing curated reader/commenter/writer choices. Explicit
public-link sharing always requests read-only, non-discoverable access. Native
permission type/role and recipient presence are validated before reporting success;
the returned email is retained because Google can resolve an alias to its account
address. This does not add group/domain/ownership-grant tools. Requests still use
the origin-bound credential and durable outbound-attempt boundary.

Authorities: [file listing](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list),
[file updates](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update)
and [permission fields](https://developers.google.com/workspace/drive/api/reference/rest/v3/permissions).
Docs/Drive function and guarded-client checks use substituted HTTP and receipt
persistence. They do not prove native account acceptance or crash recovery.

### Google Tasks request and response contracts

All five tools use vendor-owned Tasks v1 request, response and result models.
List lookup follows at most three pages of 1,000 lists, rejects repeated cursors
and duplicate IDs, and refuses ambiguous names before a mutation. Exact IDs take
precedence over names; omitting the list retains the existing first-list behavior.
This bounded lookup is not an unbounded account export.

Task listing returns one page and `next_page_token`; use `page_token` with the
same list and filters to continue. Valid empty pages have Google's resource-kind
discriminator; malformed pages cannot become empty results. Date inputs require
`YYYY-MM-DD`. Title and notes follow native length limits. Creation validates the
returned content, parent and status; completion validates identity and completed
status. Deletion requires a successful empty response. Deleting an assigned task
also deletes its original task in Docs or Chat Spaces; completion preserves it.

Authorities: [task fields](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks),
[list catalog](https://developers.google.com/workspace/tasks/reference/rest/v1/tasklists/list),
[task pagination](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/list)
and [deletion](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/delete).

### Dropbox request and response contracts

All six tools validate API v2 tagged metadata, operation responses and projections.
Folder creation consumes untagged folder metadata; file/folder/deleted unions
remain distinct elsewhere. Listing and search expose `next_cursor`; pass it as
`cursor` to continue the original query. Cursor requests use the vendor's original
filters, not newly supplied filters. Folder limits are approximate; search indexing
can lag and repeat or omit matches. These are not exhaustive filesystem snapshots.

Root maps to empty text only for reads. Mutations refuse root; native `id:` and
`ns:` identifiers are preserved. Creation and movement retain autorename behavior.
Deleted results no longer invent a 30-day retention guarantee:
`recoverable_for_days` is null because this tool does not read account policy.

Sharing now declares `sharing.read` alongside `sharing.write`. Existing connections
missing the read scope need reauthorization before using this tool. The tool checks
direct links first, reuses one without changing permissions, or creates a link with
Dropbox's defaults. Results expose actual visibility, audience and access when
available; they never promise public access against team/folder policy. Incomplete
empty lookup refuses creation. A concurrent creation may still conflict; this is
not an atomic get-or-create operation. No error-message substring matching or
automatic mutation resend is used.

Authorities: Dropbox's maintained API v2 [file schemas](https://github.com/dropbox/dropbox-api-spec/blob/main/files.stone)
and [sharing schemas](https://github.com/dropbox/dropbox-api-spec/blob/main/sharing.stone).
Google Tasks and Dropbox function checks cover all eleven tools; guarded-client
checks cover all seven mutation handlers. HTTP and receipt persistence are
substituted, so these checks do not prove live account acceptance or DB recovery.

## HubSpot request and response contracts

All six curated HubSpot tools validate selected CRM v3 fields at the vendor
boundary. Missing IDs, malformed collections, HTTP failures and mismatched update
identities are errors, not empty results or successful writes. Unknown CRM
properties remain vendor-owned; selected nullable property values are preserved.
An empty string still clears a supplied contact property, while omitted properties
are not written. Stage names are scoped by pipeline, separate from pipeline names.

Note creation includes the required `hs_timestamp` and its contact association
in one request. The curated executor checkpoints an invocation timestamp per
tool-use message before mutations; retries reuse it, keeping timestamp-bearing
request fingerprints stable. Invalid mutation responses do not trigger a resend.
Contact resolution requires an exact email match. Note tools declare contact-read
as well as contact-write scope. Deal creation resolves display labels before the
write and declares its existing deal-read requirement explicitly.

Lists remain bounded to the requested first page. Associated deals currently
require one detail read per returned association (at most 50); this work does not
claim batch-read optimization or exhaustive history. Local checks cover all six
tools, invalid replies, native payloads, timestamp checkpoint reuse and the guarded
mutation boundary. Live HubSpot curated-tool acceptance remains pending.

Authorities: HubSpot CRM v3 [notes](https://developers.hubspot.com/docs/api-reference/legacy/crm/activities/notes/guide),
[deals](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/deals/guide)
and [contact search](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/contacts/search/search-contacts).

## Pipedrive request and response contracts

The five curated tools use API v2 for deals, person search/detail, batched person
names and stages. Notes remain on the supported `/v1/notes` endpoint. The registered
base is the same pinned `api.pipedrive.com` origin; the API token remains in its
origin-bound query credential bucket. Existing connections need no schema change.
Deal updates use PATCH. The public `all_not_deleted` filter omits the native v2
status parameter, as documented by Pipedrive; the other statuses remain explicit.

Search and detail person responses have separate contracts. `find_person` reads
details with the requested deal counters; search alone cannot provide those
counters. Duplicate exact-email matches refuse an ambiguous target. Deal lists
resolve distinct person IDs in one batch, retaining the ID when a name is not
visible. Stage lookup follows cursors with a ten-page, 500-items-per-page bound;
an incomplete or repeating cursor fails before selecting a stage. Duplicate stage
names across pipelines are refused rather than selecting the first match.

HTTP failure, false or malformed `success`, missing IDs and malformed nested
values cannot become empty success. Updates validate deal identity and stage;
notes validate their owning deal/person. Display-label reads precede mutations.
No invalid response retries a potentially accepted write. Note text retains the
existing 6,000-character bound. Deal lists remain one requested page and do not
claim archived-deal history. Mutation results retain a numeric person ID when
no person name was already resolved.

Eight literal response examples from the vendor's published schemas pass local
validation. Focused tool and guarded-client probes also pass. These checks do not
prove live Pipedrive credentials, account-specific data or persisted DB recovery.

Authorities: [migration guide](https://pipedrive.readme.io/docs/pipedrive-api-v2-migration-guide),
[v2 OpenAPI](https://developers.pipedrive.com/docs/api/v1/openapi-v2.yaml),
[v1 OpenAPI](https://developers.pipedrive.com/docs/api/v1/openapi.yaml),
[deals](https://developers.pipedrive.com/docs/api/v1/Deals) and
[notes](https://developers.pipedrive.com/docs/api/v1/Notes).

## Security boundary

Curated tools receive neither credentials nor DB access. They address relative
paths only. The transport pins the configured credential to the registered or
installation-specific origin, rejects redirects, bounds replies, and separates
read calls from durable mutations.

## Google Calendar scheduling contracts

The six tools validate Calendar v3 responses before reporting results. Calendar
name lookup reads a bounded complete catalog, rejects ambiguous names and resolves
multiple names from one catalog. Event lists expose `next_page_token`; continue
with the same calendar and filters. Google's lower time bound applies to an
event's **end**, while the upper bound applies to its **start**.

Availability requires a valid response for every requested calendar and the same
time window. Missing calendars, per-calendar errors or malformed busy intervals
never become free slots. Calendar groups are not a supported input.

Creation and rescheduling operate on timed events. Supply a timestamp offset or
an explicit IANA timezone; ambiguous/nonexistent local DST times require an offset.
Rescheduling preserves elapsed duration, including seconds, unless explicitly
changed. It refuses all-day/cancelled events and validates returned identity and
times. The read followed by patch is not atomic. Cancellation confirms an empty
successful deletion acknowledgement, not email delivery; no new notification
policy is imposed by this typing change.

Authorities: Google's [events resource](https://developers.google.com/workspace/calendar/api/v3/reference/events),
[event list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list),
[free/busy query](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query)
and [event deletion](https://developers.google.com/workspace/calendar/api/v3/reference/events/delete).

## Calendly scheduling contracts

The five tools validate native account, event-type, scheduled-event, invitee and
cancellation responses. List tools expose `next_page_token`; keep filters unchanged
when continuing. Counts describe the returned page. Meeting window filters are
timezone-qualified and sent in UTC. Event arguments accept a bare identifier or
the corresponding `api.calendly.com/scheduled_events/…` URI, not arbitrary links.

Cancellation requires HTTP 201 and a valid cancellation resource. The returned
`invitee_notified` is `null`: this acknowledgement does not prove email delivery.
Malformed acknowledgements fail visibly without retrying an accepted mutation.

OAuth requests `users:read`, `event_types:read`, `scheduled_events:read` and
`scheduled_events:write`, matching the tools and their identity lookups. Personal
access tokens must have the applicable permissions as well. Calendly's documented
write-to-read implications are applied only to Calendly during auth resolution;
read access never implies write access. Existing connections without recorded
required scopes must reauthorize; the platform does not infer an unrecorded grant.

Authorities: Calendly's [authorization scopes](https://developer.calendly.com/docs/authentication/scopes),
[scheduled events](https://developer.calendly.com/api-docs/calendly-api/scheduled-events/list-scheduled-events),
[invitees](https://developer.calendly.com/api-docs/calendly-api/scheduled-events/list-event-invitees)
and [cancellation](https://developer.calendly.com/api-docs/calendly-api/scheduled-events/create-scheduled-event-cancellation).

## OAuth token contracts

Initial authorization and refresh share a validated token-response object; each
flow translates failures into its own named codes. Authorization requests have
explicit private fields and serialize only at the pinned HTTP boundary. Callback
completion returns a named connection/vendor receipt rather than a positional
tuple. Public callback HTML and redirect response fields are unchanged.

Expiry is a nonnegative JSON integer in seconds, and unknown response extensions
are ignored, following [OAuth 2 token-response semantics](https://www.rfc-editor.org/rfc/rfc6749.html#section-5.1).
The existing compatibility allowance for an omitted `token_type` remains; this
is not a claim of strict protocol conformance for every vendor. Missing expiry
does not invent a default lifetime.

OAuth state creation validates UUID owners, positive optional revisions,
timezone-aware expiry and the existing DB column length bounds. Expired-state
cleanup returns validated receipts; source-owned deletion counts returned IDs.
These changes do not modify the database schema or authorization scopes.

The callback spends a recognized state in a short committed transaction before
reporting a missing installation or exchanging a code. Declined consent and
missing-code callbacks also spend state and notify the contact with platform-owned
failure text; vendor error text is not echoed. Unknown, consumed, and wrong-route
states are refused. A connection revision that changed since consent began cannot
be activated by that old attempt.

Scope fallback comes from that consent attempt's stored scopes, not the current
catalog; an explicitly empty token scope is not treated as an omitted scope.
Atlassian token exchange and refresh use the catalog's JSON encoding. Consent
includes `offline_access` for rotating refresh tokens. Other registrations retain
their declared form encoding. Token exchange and resource discovery refuse an
ambient DB transaction; vendor latency must not extend an operator transaction.
[Atlassian authorization](https://developer.atlassian.com/cloud/oauth/getting-started/implementing-oauth-3lo/),
[Atlassian refresh](https://developer.atlassian.com/cloud/oauth/getting-started/refresh-tokens/).

Expired and rejected attempts discard only the matching, still-initiated connection
revision. They never revoke an already-active or newer connection. The callback
controller closes its installation lookup transaction before token exchange.
Expiry cleanup includes consumed attempts: a failed or cancelled exchange may
leave an initiated connection even though its state was already spent. Ownership
receipts come from `DELETE RETURNING`, not a separate pre-delete snapshot.

## OAuth credential refresh

The refresh pipeline reads due connections in a short transaction, closes it
before vendor HTTP, then persists renewed credentials with the expected connection
revision. A concurrent credential change skips the stale write. Cancellation
propagates; it is not recorded as an ordinary credential failure.

Refresh request, token response and renewal receipts use validated Pydantic
contracts. Connection organization identity is required. Token expiry is an
optional nonnegative integer in seconds; malformed expiry or datetime overflow
fails visibly rather than accepting a boolean/string or inventing a lifetime.
Omitted token-rotation fields preserve the previous values. Receipt dumps and
representations exclude plaintext secrets.

The shared refresh path posts the catalog-declared encoding to a pinned origin.
Atlassian refresh validates the stored site binding before exchanging the token,
then preserves that binding with the rotated credential. It does not rediscover
or reassign a site after rotation: a secondary discovery failure must not discard
the newly issued refresh token. This validates local identity, not a fresh remote
resource listing; the vendor still enforces current access on each API call.
Returned scopes may narrow, never widen, the stored grant; omission preserves it.
Its existing policy
treats HTTP 400 as reauthorization required; other HTTP failures are retried until
the attempt limit. Named failure codes preserve the stored diagnostic spelling.
These shared contracts do not prove every vendor's authentication format or live
refresh behavior; vendor-specific compatibility must be verified separately.

## Persistence relationships

- installation: one organization's decision to configure a vendor;
- connection: one organization or contact credential authority;
- installed-tool policy: execution mode for a registered tool;
- Agent grant: exact Agent-to-tool relation, copied into published revisions;
- OAuth state: short-lived authorization transaction;
- outbound receipt: durable proof for each mutation attempt.

Installing a vendor does not grant its tools to an Agent. Connecting an end
user does not expose that credential to another contact or organization.
