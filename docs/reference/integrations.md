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
  non-secret headers.
- `CuratedToolSpec`: stable `vendor.name` wire ID, display text, effect, input
  model, required scopes, and Python handler.
- `VendorToolContext`: connection identity plus origin-bound `read()` and
  durable `mutate()` methods.
- `ToolExecutionMode`: `auto`, `requires_approval`, or `disabled`, read live at
  execution.

Invocation arguments must be JSON values, then satisfy the registered vendor
input model. Its existing normalization rules still apply. Handler results must
also be JSON-safe: non-finite numbers, cycles, or arbitrary Python objects return
`tool_result_invalid`, without retrying a potentially completed mutation.
Disabled tools return `tool_execution_blocked`; only an approval-policy refusal
sets the `approval_required` result metadata flag. This flag alone is not a
durable approval wait.

## Typed tool choices

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

## Known transport limitation

GitLab project paths such as `group/project` currently fail with
`vendor_request_invalid`: the adapter encodes the slash as GitLab requires, but
the shared HTTP guard refuses encoded path separators. Numeric project IDs pass
that request validation. This affects the existing named-project path across
GitLab tools, not just the new query enums. Until the transport contract is
corrected, use the numeric project ID; do not remove the shared path guard.

## Security boundary

Curated tools receive neither credentials nor DB access. They address relative
paths only. The transport pins the configured credential to the registered or
installation-specific origin, rejects redirects, bounds replies, and separates
read calls from durable mutations.

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

The current shared refresh path posts an origin-pinned form. Its existing policy
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
