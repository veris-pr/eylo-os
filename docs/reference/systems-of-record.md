# System of Record contracts

This page describes the current executable SOR surface. The runtime registry,
public OpenAPI document, SQLAlchemy models, and Alembic baseline are
authoritative.

## Profiles

| Profile key | Console label | Canonical scope | Tool namespace |
| --- | --- | --- | --- |
| `crm` | CRM | contacts, companies, deals, activities, owners, pipelines, stages | `crm_*` |
| `ticketing` | Issues | issues, projects, workflow states, users, labels, cycles, comments, attachments, relations | `issue_*` |
| `support` | Support | tickets, customers, source agents, queues, inboxes, messages, tags, SLA metrics, attachments | `support_*` |
| `knowledge` | Documents | spaces, documents, blocks, current revisions, properties, attachments, authors | `docs_*` |

The catalog defines all four domain contracts. A profile becomes executable
only through a registered adapter and an active source.

## Current vendors

| Profile | Vendor | Status | Auth | Objects | Sync and capabilities |
| --- | --- | --- | --- | --- | --- |
| CRM | HubSpot | Implemented; live acceptance pending | OAuth 2.0 | contacts, companies, deals | full reconciliation; custom fields; reads and mapped writes |
| CRM | Salesforce | Implemented; live acceptance pending | OAuth 2.0 with PKCE | Contact, Account, Opportunity, Task | updated-at cursor; custom fields and objects; conditional writes |
| CRM | Microsoft Dataverse | Planned | — | — | no registered adapter |
| Issues | Jira Cloud | Implemented; webhook live acceptance pending | OAuth 2.0 | issues, projects, workflow states, users, labels, sprints, comments, relations | enhanced-JQL issue sync; managed dynamic webhooks; 30-day renewal; Sprint-field cycle discovery; full reconciliation; custom fields; mapped writes |
| Issues | Linear | Implemented; live acceptance pending | OAuth 2.0 with PKCE | issues, teams, projects, workflow states, users, labels, cycles, comments, relations | updated-at sync; signed app-managed webhooks; mapped writes |
| Issues | GitHub Issues | Implemented; live acceptance pending | OAuth 2.0 | repositories, issues, workflow states, users, labels, milestones, comments | REST updated-at sync with bounded GraphQL PR classification; full reconciliation; signed operator-managed webhooks; mapped writes; pull requests and issue relations excluded |
| Support | Zendesk | Implemented; live acceptance pending | OAuth 2.0 | tickets, customers, agents, groups, brands, comments, tags, ticket metrics, attachments | cursor incremental export; signed webhook refetch; custom ticket fields; public replies/private notes; safe mapped writes |
| Support | Intercom | Implemented; live acceptance pending | OAuth 2.0 | conversations, contacts, admins, teams, conversation parts, tags, attachments | updated-at search plus full reconciliation; regional API pinning; signed app-managed webhooks; conversation attributes; public replies/private notes; mapped writes |
| Support | Freshdesk | Implemented; live acceptance pending | API key | tickets, contacts, agents, groups, email inboxes, conversations, tags, SLA targets, attachments; companies and Freshdesk custom objects as custom datasets | updated-at polling plus full reconciliation; custom fields and objects; public replies/private notes; mapped writes; no API-key webhook support |
| Documents | Confluence Cloud | Implemented; live acceptance pending | OAuth 2.0 with REST v2 granular scopes | spaces, pages, page bodies, current revisions, properties, attachments, authors | full reconciliation; loss-aware HTML normalization; current revision and author reads; authenticated current-image previews; mapped create/update/append |
| Documents | Notion | Implemented; live acceptance pending | OAuth 2.0 or API key | data sources, pages, recursive blocks, properties, attachments, authors | full reconciliation; completed paginated relation/rollup properties; unsupported-block disclosure; mapped create/update/append/comment |
| Documents | Linear Documents | Implemented; live read acceptance complete; live image acceptance pending | OAuth 2.0 with PKCE; may reuse the active Linear connector | documents, authors, document images | updated-at sync; signed connector webhook; latest Markdown content; authenticated current-image previews; read-only |
| Documents | SharePoint | Planned | — | — | no registered adapter |

“Planned” means catalog visibility only. It does not mean credentials can be
configured or any vendor request can execute.

“Implemented; live acceptance pending” means the adapter registry, recorded
vendor transport, real PostgreSQL projection, command, audit, and tenant paths
have passed locally. It does not count as live vendor support until the complete
acceptance matrix is exercised against an operator-owned account.

Linear Documents has additionally verified the saved OAuth connection and read
current documents and authors from an operator-owned workspace. Its current
sample contained no document images, so image delivery remains recorded-
transport proven rather than live accepted.

Salesforce's validated instance origin comes from the OAuth token response and
is pinned to the resulting connection. Operators do not type a mutable request
origin into each source.

## Change notification modes

Every executable adapter declares one `change_mode`; the catalog does not
encode delivery behavior through booleans:

| Mode | Meaning |
| --- | --- |
| `MANAGED_WEBHOOK` | Eylo creates, renews, and removes the vendor subscription. |
| `OPERATOR_WEBHOOK` | An operator configures a source-specific webhook in the vendor. |
| `APP_WEBHOOK` | A vendor app or developer-console subscription forwards events to Eylo. |
| `CHANGE_STREAM` | The adapter consumes a vendor-native change stream rather than HTTP deliveries. |
| `POLL_ONLY` | Scheduled incremental sync and reconciliation are the only change paths. |

Jira uses `MANAGED_WEBHOOK`; GitHub and Zendesk use `OPERATOR_WEBHOOK`; Linear
and Intercom use `APP_WEBHOOK`. Every other current adapter declares
`POLL_ONLY`. A delivery is only a hint to refetch authoritative vendor data.
Periodic reconciliation remains the correctness path, so no separate freshness
state is persisted.

Linear's webhook belongs to the saved OAuth app connector, not to an individual
source or profile. Eylo generates one stable connector callback, stores the
Linear signing secret encrypted, and fans each verified workspace event out
only to Issues and Documents sources whose selected objects include that event
type. The Linear app webhook must be enabled before workspace authorization.
Intercom retains its current Developer Hub, source-configured callback flow
until its connector-owned ingress is implemented.

Jira managed webhooks use the official OAuth dynamic-webhook REST resources.
The source owns one opaque callback endpoint and one vendor subscription ID.
Eylo registers the selected issue, comment, and Sprint events, renews the
30-day subscription seven days before expiry, and removes it when the source is
deleted. Registration first recovers an existing exact callback, making retry
safe across a crash between the vendor response and Eylo's completion write.
Renewal also recreates a callback that was deleted on the vendor side before
extending it.
Registration requires the **classic** `read:jira-work` and
`manage:jira-webhook` scopes. Sprint reads additionally use the explicitly
labelled **granular Jira Software** scopes shown by the catalog. These scope
families are not presented as interchangeable.

Managed callbacks require a public HTTPS `API_BASE_URL`; localhost cannot
receive Atlassian delivery. Confluence's current OAuth 2.0 (3LO) API does not
provide Jira-style dynamic webhook registration. Confluence therefore remains
`POLL_ONLY`; adding event delivery requires a separately installed Atlassian
app/Forge remote contract, not another 3LO consent scope.

Vendor authorities: Atlassian's [Jira dynamic webhook REST
API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-webhooks/),
[Jira webhook delivery guide](https://developer.atlassian.com/cloud/jira/software/webhooks/),
and [Confluence webhook guide](https://developer.atlassian.com/cloud/confluence/using-webhooks/).

## Executable CRM tools

Both current adapters implement these reads:

- `crm_find_customer`
- `crm_get_customer`
- `crm_list_deals`
- `crm_get_deal`
- `crm_describe_customer_fields`
- `crm_describe_deal_fields`

Both implement these mapped mutations:

- `crm_create_contact`, `crm_update_contact`
- `crm_create_company`, `crm_update_company`
- `crm_create_deal`, `crm_update_deal`, `crm_move_deal`

Salesforce also implements `crm_log_activity`. A tool appears to a published
Agent only when the Agent has that system tool, a compatible source grant, an
active mapped stream, and the required provider scopes.

## Executable Ticketing tools

Jira Cloud, Linear, and GitHub Issues implement these reads:

- `issue_search`
- `issue_get`
- `issue_list_projects`
- `issue_list_workflow_states`
- `issue_describe_fields`

All three implement these mapped mutations:

- `issue_create`, `issue_update`, `issue_transition`, `issue_assign`
- `issue_add_label`, `issue_remove_label`
- `issue_comment`

Jira Cloud and Linear additionally implement `issue_link`. GitHub issue
relations, sub-issues, dependencies, pull requests, and Projects metadata are
outside the current adapter revision. A GitHub source synchronizes only the
explicit `owner/repository` entries in its non-secret source configuration.
Repository comment pages are ordered by the comments' own revisions. Eylo
classifies their bounded parent-number set in one GraphQL request so edited
issue comments reconcile without importing pull-request comments.

Each mutation declares one authoritative result stream. Most actions return an
issue. `issue_comment` returns a comment; `issue_link` returns an issue
relation. Publication and runtime both require that exact result stream and at
least one active mapping for it before any vendor write can start. Selecting
only the issue stream therefore does not authorize comment or relation writes.

The target entity remains narrower than the related data a tool may inspect.
For example, `issue_get` targets only an issue even though the response can
include related records. A related comment or relation cannot be supplied as
the direct target by exploiting that response scope.

## Executable Documents tools

Confluence Cloud and Notion implement these reads:

- `docs_search`
- `docs_get`
- `docs_list_children`
- `docs_describe_fields`

Both implement `docs_create`, `docs_update`, and `docs_append`; Notion also
implements `docs_comment`. `docs_get` returns the current document projection.
Eylo does not expose a separate historical-version tool. Tool visibility still
requires the published Agent tool, a compatible source grant, selected streams,
active mappings, and required OAuth scopes. Documents are external SOR
projections, not internal Eylo Knowledgebases and not `kb_*` retrieval tools.

Linear Documents implements `docs_search` and `docs_get`. It reuses the same
canonical tools and may reuse the same active Linear OAuth connection as an
Issues source; it does not expose a second vendor-specific Agent namespace.
V1 imports only the latest Markdown content, author identity, parent provenance,
and current `uploads.linear.app` images. Linear remains authoritative for older
revisions and document mutations.

## Executable Support tools

Zendesk, Intercom, and Freshdesk implement these reads:

- `support_find_customer`
- `support_find_ticket`
- `support_get_ticket`
- `support_get_customer_history`
- `support_list_queues`
- `support_describe_ticket_fields`

All three implement these mapped mutations:

- `support_open_ticket`, `support_update_ticket`, `support_assign_ticket`
- `support_reply`, `support_add_note`, `support_close_ticket`
- `support_add_tag`, `support_remove_tag`

`support_get_ticket` returns the canonical ticket plus its bounded canonical
message chronology. `support_get_customer_history` returns the canonical
customer plus bounded related tickets. Related reads remain inside the same
organization and source, require the related stream to be selected, and require
an active Agent-visible mapping. The response distinguishes `AVAILABLE`,
`NOT_SELECTED`, and `NOT_MAPPED`; it never treats unavailable history as an
empty successful result.

Zendesk public replies and private notes are separate commands and remain
separate canonical message visibility values. Ticket updates use Zendesk safe
updates when an expected source revision is supplied. Cursor checkpoints are
opaque, including a terminal cursor returned with `end_of_stream`; Eylo stores
the terminal checkpoint instead of manufacturing or discarding it.

Intercom conversations are canonical Support tickets; Intercom conversation
parts are canonical messages. Its OAuth consent host follows the selected US,
EU, or AU data region while API traffic remains pinned to that exact regional
origin. Permissions are selected in Intercom Developer Hub, so Eylo records
the required permission labels but does not send a `scope` parameter in the
authorization request. Intercom's API returns at most 500 conversation parts.
Eylo rejects a conversation whose complete history cannot be proven instead of
silently presenting a partial transcript. Attachment-only parts remain visible
as messages and preserve their attachment metadata.

Intercom webhooks are configured and removed by the operator in Developer Hub.
Eylo verifies `X-Hub-Signature` with the app client secret, then treats the
event as a refetch signal. Programmatic subscription and renewal are not
claimed. Intercom Tickets, companies, inboxes, per-metric SLA history, and
custom objects are outside this adapter revision.

Freshdesk uses API-key Basic authentication against the source's exact
`https://<site>.freshdesk.com` origin. Ticket and contact pulls use overlapping
updated-at cursors; agents, groups, email inboxes, companies, and discovered
custom objects use full reconciliation. Ticket conversations, tags, SLA target
data, and attachments are expanded into their canonical streams. If a pull
would exceed Freshdesk's 300-page API window, Eylo rejects the run instead of
silently truncating it. Companies and native custom objects remain audit-only
custom datasets in v1. API-key mode claims no webhook, deletion-feed, or
conditional-write capability.

## Source and mapping states

Source states are:

- `DRAFT`
- `VERIFYING`
- `DISCOVERING`
- `BOOTSTRAPPING`
- `ACTIVE`
- `DEGRADED`
- `REAUTH_REQUIRED`
- `DISABLED`

Schema and mapping revisions are immutable. Selected source objects are
validated against the active discovery. A mapped field targets exactly one
canonical or custom field; ignored fields target neither. Read-only sources
cannot publish write mappings.

Revoking an external connection moves dependent sources to
`REAUTH_REQUIRED`. Active work becomes terminal before or during exact Absurd
task cancellation. A command interrupted before a confirmed vendor checkpoint
reports `MUTATION_OUTCOME_UNKNOWN`; one interrupted after that checkpoint
reports `POST_WRITE_CANCELLED`. The periodic `nudge-sor-work` action recovers
stranded cancellations, and durable outbox recovery only spawns work whose
source state permits that work kind.

## Sync graph and relationship states

Adapter stream contracts expose:

- `depends_on`: zero or more stream keys from the same vendor manifest;
- `relationship_targets`: semantic reference key to exact target stream key.

Registry startup rejects unknown nodes, self-dependencies, cycles, blank
relationship keys, unknown relationship targets, and a relationship target not
declared as a stream dependency. Object selection includes the complete
transitive dependency closure; the server rejects an incomplete selection even
if a client omits that UI behavior. A source sync generation has one kind and
contains one run per selected stream. Run states use
`PENDING`, `WAITING`, `RUNNING`, `SUCCEEDED`, `FAILED`, or `CANCELLED`.
Generation state uses the same terminal vocabulary. A selected parent failure
sets waiting descendants to `FAILED` with `DEPENDENCY_FAILED`.

Relationship intents use `PENDING`, `RESOLVED`, or `TOMBSTONED`. Resolution is
same-source and exact on organization, source, vendor object key, and vendor
external ID. Endpoint projection resolves affected intents immediately. The
trusted worker retries older pending intents in bounded batches, at most once
per five-minute window; stream finalization does not absorb that backlog.

Reference columns retain the raw vendor identifier as canonical data and add a
batched `display_values` projection for the operator grid. The display value is
resolved only within the same organization and source. Ambiguous or absent
targets fail closed to the raw identifier; one unresolved target can never
borrow a label from another source. Jira assignee and reporter IDs resolve to
users, project IDs to projects, sprint IDs to cycles, and comment parents and
authors to their canonical issue and user labels. Confluence page and current
revision authors resolve through the selected author stream. Confluence emits
a canonical parent relation only when the REST v2 page declares
`parentType: page`; folder parents remain source-only because v1 does not
import Confluence folders or request the folder-read scope.
Linear document authors resolve through the selected author stream. A Linear
document may belong to an issue, project, initiative, or release owned by a
separate profile source. V1 retains that typed parent ID and human label as
source context; it does not fabricate a same-source canonical relationship.

Vendor refresh, fetch, and download operations execute without an open DB
transaction. Page projection, run finalization, and generation advancement use
separate bounded transactions. The worker reconciles a terminal run whose
generation was not advanced after commit.

Jira Sprint discovery reads the stable Sprint custom-field schema and scans
Sprint-bearing issues through enhanced JQL. It does not infer available cycles
from board enumeration: an authorized user may see issue Sprint values while
the board list is empty. The adapter retains `read:sprint:jira-software` only
for incomplete or conflicting field values. Jira cycles do not claim a project
relationship because a Sprint belongs to a board whose filter may span projects.

Incremental runs inherit the committed stream checkpoint. Bootstrap and
reconciliation runs are complete source scans: each starts from an empty,
run-owned cursor, advances independently of an older stream checkpoint, and
tombstones records not observed after the scan completes. A replacement
mapping therefore cannot become active with records stranded on its previous
mapping revision.

## Grid contract

Every canonical or custom audit collection returns `sor-grid-v1` metadata.
Column kinds are `TEXT`, `LONG_TEXT`, `ENUM`, `NUMBER`, `BOOLEAN`, `DATE`,
`DATETIME`, `REFERENCE`, `LINK`, and `STRING_ARRAY`. Column metadata declares
importance, default visibility, filtering, sorting, grouping, wrapping, and
whether the field is custom.

Eylo owns this contract, its query semantics, row identity, actions, selection,
and URL serialization. A table or virtualized-grid package is only a renderer
of the contract and may be replaced without changing domain or API behavior.

The query contract supports:

- up to 50 source IDs;
- lexical search up to 200 characters;
- nested `and`/`or` filters, at most five levels and 100 nodes;
- up to five sort terms and three group terms;
- up to 100 selected columns;
- an opaque cursor up to 2,048 characters;
- page limits from 1 through 200.

`columns` is also a response-projection boundary. Collection rows include only
the requested canonical and custom values; detail reads remain complete. The
console sends the contract's `default_visible` columns when the URL has no
explicit `column` selection, then sends the user's selected columns. An empty
`columns` list remains a compatibility request for every value, so new clients
should always send their visible set. This keeps large custom-field catalogs
out of ordinary grid payloads without moving query authority into the
renderer.

Allowed filter operators are `is`, `is_not`, `is_any_of`, `includes_any`,
`includes_all`, `includes_none`, `before`, and `after`. The server rejects a
field or operation not declared by the grid contract. `is` remains scalar;
`is_not` accepts one or more values and excludes every selected value;
`is_any_of` accepts multiple alternatives.

Selectable values for enum, boolean, reference, and string-array fields come
from the full organization/profile/entity/source collection scope through the
collection's `filter-options` read. They do not come from the current page and
do not inherit active search, filter, group, sort, or cursor state. Reference
options use the same tenant-scoped canonical label resolution as grid cells.
This keeps labels and available choices stable while the result query changes.

The console serializes the main view into `q`, repeated `source`, `filters`,
`sort`, `group`, repeated `column`, `cursor`, and `record` query parameters.
Copying the URL reproduces the same audit view.

## Public API groups

All organization routes are under `/api/{organization_id}/sor`:

- `/catalog` and `/oauth/configuration`;
- `/connectors` and `/connectors/{connector_id}/authorize`;
- `/sources` and `/sources/api-key`, source verification, discovery, selection,
  mapping, activation, streams, sync runs, webhook endpoint management, and
  managed webhook subscription registration/removal;
- `/sources/{source_id}/operations` for bounded recent generations, stream-run
  receipts, and relationship health;
- `/agents/{agent_id}/source-grants` and the published Agent view;
- `/{profile}/{entity}` grid, filter-options, query, list, and detail reads;
- `/ticketing/issues/{record_id}/audit` for bounded live comments and explicit
  source-history availability;
- `/support/tickets/{record_id}/audit` for bounded message chronology, SLA
  metrics, attachments, and explicit related-stream availability;
- `/knowledge/documents/{record_id}/audit` for bounded structured blocks,
  source properties, current revision metadata, attachments, space, author,
  and explicit related-stream availability;
- `/knowledge/documents/{record_id}/attachments/{attachment_record_id}/content`
  for a tenant-authorized, bounded current raster image. Vendor OAuth remains
  server-side and is never forwarded to a redirected content host;
- `/custom-datasets` grid, filter-options, query, list, and detail reads.

The shared OAuth callback is `/api/sor/oauth/callback`. Exact request and
response schemas belong to the running OpenAPI document at `/docs`.

## Tenancy and authority

Every persisted SOR row carries organization identity. Cross-organization
lookups return 404. Reads intersect the requested source IDs with organization,
profile, mapping, field visibility, published Agent revision, and source grant.
Mutations additionally require a live read-write grant and the exact system
tool in the published Agent revision.

Credentials are encrypted through the external-connection boundary and are
never returned by list, detail, grid, or discovery APIs. API keys exist only in
the open connection form long enough to run bounded verification. A successful
request atomically stores the encrypted key and source draft; the key is not
part of resumable browser state or any API response.

Successful Agent mutations file one organization-visible durable event in the
same transaction as command completion. Current event types are:

- connection: `sor.connection.connected`,
  `sor.connection.reauth_required`, `sor.connection.revoked`;
- CRM: `crm.contact.created`, `crm.contact.updated`, `crm.deal.created`,
  `crm.deal.updated`, `crm.deal.stage_changed`;
- Issues: `issue.created`, `issue.updated`, `issue.transitioned`,
  `issue.commented`;
- Support: `support.ticket.opened`, `support.ticket.updated`,
  `support.ticket.assigned`, `support.ticket.replied`,
  `support.ticket.noted`, `support.ticket.closed`;
- Documents: `docs.document.created`, `docs.document.updated`,
  `docs.document.appended`.

Payloads contain stable IDs, source/vendor identity, action, projection result,
and revision only. Source content, custom values, email, phone, comments,
descriptions, scopes, and credentials are excluded.

Best-effort post-commit events cover `sor.source.activated`,
`sor.source.degraded`, `sor.schema.changed`, `sor.mapping.published`,
`sor.record.projected`, `sor.record.tombstoned`, and `sor.sync.completed`.
These in-process signals may be lost and have no ordering guarantee; persisted
sources, mappings, records, and sync runs remain authoritative.
