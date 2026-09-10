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

Invocation arguments must be JSON values, then satisfy the registered vendor
input model. Its existing normalization rules still apply. Handler results must
also be JSON-safe: non-finite numbers, cycles, or arbitrary Python objects return
`tool_result_invalid`, without retrying a potentially completed mutation.
Disabled tools return `tool_execution_blocked`; only an approval-policy refusal
sets the `approval_required` result metadata flag. This flag alone is not a
durable approval wait.

## Typed tool choices

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
- Existing ID-only tools retain the currently served legacy issue routes;
  project issue listing is deprecated by Sentry. The
  [current route source](https://github.com/getsentry/sentry/blob/master/src/sentry/api/urls.py)
  still serves these paths. Migrating to organization-scoped inputs is a separate
  compatibility change; this implementation does not guess an organization.
  Native issue/event shapes follow the
  [issue](https://docs.sentry.io/api/events/retrieve-an-issue/) and
  [event](https://docs.sentry.io/api/events/retrieve-an-issue-event/) references;
  the [update handler](https://github.com/getsentry/sentry/blob/master/src/sentry/issues/endpoints/group_details.py)
  returns the updated issue.

PagerDuty status/urgency and Sentry state inputs retain case/whitespace
normalization. Limits and offsets require integers rather than booleans.
These changes do not add grants, vendor writes or alternate receipt ownership.
Response-validation failure does not authorize a repeated mutation.

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
