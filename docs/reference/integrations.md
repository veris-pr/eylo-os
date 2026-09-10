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
raw vendor diagnostics are not echoed. The instance URL still supplies the
origin and `/api/v4` prefix; no self-managed GitLab release is inferred or pinned.

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
- Detail replies must match the requested IID and, for numeric project inputs,
  project ID. A created comment uses its returned issue identity after checking
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
Local probes and public examples are not live GitLab acceptance. The named-project
transport limitation below remains open.

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
