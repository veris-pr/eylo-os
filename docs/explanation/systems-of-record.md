# Systems of Record

Eylo's System of Record layer gives Agents a stable domain vocabulary while an
organization keeps its existing CRM, issue tracker, support system, or document
platform as the source of truth.

It is not a generic integration wrapper. Curated integrations expose
vendor-specific tools. SOR profiles instead define canonical entities and
actions, then require each adapter to prove which parts it can execute. An
Agent can use `crm_find_customer` without learning whether the backing source
is HubSpot or Salesforce.

## Ownership boundary

`server/eylo/sor/` is a top-level product boundary. It owns:

- canonical profile contracts and tool names;
- vendor adapter capability manifests;
- sources, discovered schemas, mappings, streams, projections, and commands;
- source grants copied into published Agent revisions;
- audit read and grid contracts.

The shared `connections` module owns encrypted external-account credentials.
`pipelines/sor/` connects Agent-run waits and tool execution to the SOR runtime.
Vendor HTTP remains inside explicit SOR adapters. Core `modules/` do not absorb
vendor records, and generic integrations do not define SOR policy.

Vendor implementations retain their own stream enums and each profile's tool
enums. At registration, manifests expose validated string identifiers to shared
catalog, OAuth and command consumers; shared code does not import a vendor's
enum. Manifests and stream specifications are frozen Pydantic values. Scope,
tool-stream and mutation-result mappings are copied and frozen so changing a
vendor's source dictionary cannot change an already registered capability.
Factory callables retain their identity and never enter catalog snapshots.

Shared catalog entries, mapping/stream drafts and relationship intents are also
strict Pydantic values. API parsing converts wire enums before constructing
internal drafts; transformation settings admit only finite JSON. Relationship
roles use platform enums internally and explicit wire conversion at serialization
boundaries. Projection outcomes preserve the profile payload's concrete type and
identity, while excluding its content from generic diagnostic snapshots. These
contracts do not move mapping or relationship policy out of domain services.

Vendor cursor and snapshot values are validated Pydantic objects inside their
adapters; vendor codecs still own durable cursor formats, version compatibility
and malformed-cursor errors. Connector projections hold live ORM instances, not
copies, and omit those rows from generic snapshots. Explicit read projections
remain responsible for the public response. Media values similarly omit raw bytes
and document content from diagnostics while retaining direct runtime access.

Source payloads, external records and record pages are frozen Pydantic contracts.
HubSpot also validates its account, property, record and association responses as
vendor-owned models before producing these shared contracts. Known fields are
typed; unknown vendor additions are ignored. Custom properties remain finite JSON
because the source's field mapping, not a static platform schema, owns their names.
Pagination and association identities are explicit fields rather than dictionary
conventions carried through synchronization.
Salesforce separates typed record metadata from custom sObject fields in the same
way. Its keyset checkpoint is an internal value with a stable durable encoding.
Query completion considers both the requested limit and Salesforce's `done`
response field: a short unfinished batch must continue, while an empty unfinished
batch fails instead of repeating a checkpoint indefinitely.
Confluence validates site, collection, page, author, property, attachment and
mutation envelopes before canonical conversion. Typed request models own wire
aliases and body construction; current-version and page-parent policy remain in
the adapter. Content properties retain finite JSON values. Storage markup still
passes through the existing loss-aware renderer and size limits, rather than a
second document representation introduced by the wire contracts.
Notion similarly validates native operation models before source projection.
Page, Markdown and block snapshots preserve unknown fields, explicit nulls and
omissions so typing does not rewrite content hashes or custom properties. Block
discriminators select typed text/file content without discarding the original
block; unsupported kinds remain visible in source data. Property-item pagination
and recursive traversal use typed envelopes and bounded saved positions. Native
[Markdown operations](https://developers.notion.com/reference/update-page-markdown)
keep title replacement, content replacement, append and comments as distinct
requests, with responses validated before an accepted command receipt is returned.
Runtime-discovered fields remain a dynamic mapping; native vendor schemas stay
inside their adapters. Raw payloads are excluded from generic runtime snapshots
and representations. Persistence uses an explicit encoder, not `model_dump()` on
the live record.

The shared SOR HTTP client returns frozen Pydantic JSON/binary response values.
HTTP status and header shapes are strict; JSON is validated as finite before a
vendor parser receives it. Invalid JSON numbers produce the existing terminal
`VENDOR_RESPONSE_INVALID` classification. Raw headers, bodies and attachment
bytes are excluded from generic representations and snapshots; adapters still
read explicit attributes for correlation IDs, pagination and media handling.
This envelope does not replace each vendor's request/response schema. Existing
origin pinning, byte limits, retries and cancellation remain transport-owned.

Canonical CRM, Ticketing, Knowledge and Support records use a shared, strict
Pydantic base at the adapter-to-profile boundary. Native construction preserves
platform enum, decimal, timestamp and relationship-ID types. Unknown fields and
invalid native values fail before a profile write. Custom fields and raw document
or message bodies accept finite JSON values, not arbitrary Python objects.
Fields are top-level frozen; nested JSON is copied and validated, not recursively
immutable. Raw source bodies and attachment bytes are omitted from generic
snapshots and representations. Profile services still persist explicit attributes;
`model_dump()` is not a substitute for that persistence path. Domain services
retain their field budgets, relationship rules and transaction ownership.

Audit and related-record read contexts are also typed Pydantic values. Live ORM
source/record references retain identity and are excluded from snapshots and
generated JSON schemas. The public response models still select the visible
fields explicitly. Support message visibility/direction and SLA state, plus
Knowledge source format, are restored to profile enums when reading stored rows;
their public JSON spelling remains unchanged.

Periodic sync, webhook refetches and command readbacks share the same stored-record
codec in `sor/runtime/serialization.py`. It preserves the existing JSON envelope
and timestamp spelling, validates timezone-aware timestamps and finite JSON
values, and rejects malformed records rather than projecting partial data. Sync
retains ownership of page-count and byte limits. Validation failures are terminal
contract errors with a safe summary; vendor transport failures retain their
existing retry classification. This contract change does not require a DB migration.

Command authority, filings, claims and vendor request/results also use strict
Pydantic values. Validated command subclasses retain identity across the runtime
boundary; raw arguments and responses are excluded from generic snapshots.
`SorStoredCommandResult` explicitly retains response data for durable recovery,
with the existing six-field JSON envelope. Missing, extra or invalid fields are
terminal contract failures. Runtime refusal enums retain existing stored codes;
vendor failures keep their adapter-owned classification. None of these value
contracts grants authority: command execution still rechecks live source, grant,
published revision and run state at the existing transaction boundaries.

`SorCommandIntent` defines the existing idempotency-hash input; its JSON encoding
preserves the previous field names, UUID strings, explicit null target and revision
policy value. `SorStoredCommandRequest` defines the encrypted mutation wrapper.
Filing serializes it for encryption; claim loading validates it before resolving
the profile-owned command payload. Missing legacy nullable target fields remain
supported. Unknown fields, invalid target types and non-finite payload values are
refused with a safe command-payload error. Encryption remains bound to the same
organization, command ID and purpose; neither contract can supply new authority.

Command receipts remain typed through worker execution and Agent-tool resume.
Sync, webhook and command producers select their ID-only task model from the
persisted work type, rather than accepting an arbitrary dictionary key. The same
models validate worker input; command terminal notifications reuse the command
identity model. Existing JSON field names and idempotency keys remain unchanged.
`SorCommandReceipt` carries UUID identity, the command-state enum and finite JSON
result data. Terminal status comes from the existing command state machine.
The Absurd return boundary explicitly encodes that receipt as JSON; internal
callers do not inspect untyped receipt dictionaries. Model-facing SOR outcomes
use a discriminated result union, with error status derived from its kind. A
successful command result requires a succeeded receipt. The conversation tool
executor explicitly serializes content and metadata into the framework contract;
the private outcome snapshot excludes tool content.

Read results also retain `SorAgentViewResponse` through the executor instead of
converting the authorized projection to a dictionary for internal shaping.
Knowledge owns the search/get content modes and content-window models in
`sor/knowledge/read_contracts.py`. Search excerpts and get windows omit raw source
bodies, retain custom fields and provenance, and leave the original projection
unchanged. Related collections omit source bodies too. Only records with normalized
text receive window metadata; other read tools retain their existing response
shape. The result envelope validates finite JSON in primary and related record
values before the framework serializer runs. This changes neither grants nor the
operator API, persisted records, document input limits or database schema.

Adapter configuration and discovery values use typed Pydantic contracts too.
Decrypted credentials and source settings are copied, validated as finite JSON
and sealed at the top level before factory invocation. Credentials and webhook
secrets never enter generic snapshots; adapters still receive the explicit
values needed for vendor requests. Verification and discovered fields/objects
return typed values through the existing schema snapshot and difference logic.
Field data types are platform enums, restored explicitly from persisted snapshots.
Discovery phase/failure enums retain current state transitions and stored codes;
vendor I/O still runs outside the short commit transactions. A verified API-key
candidate carries its secret only to encrypted connection creation, not to a
response or generic snapshot.

OAuth authorization and refresh carry typed immutable context, grant and renewal
values. Client secrets, PKCE verifiers, tokens and authorization URLs are omitted
from generic snapshots and representations; the public authorization response
selects its URL explicitly. Token bodies validate finite JSON before interpretation.
Runtime failure enums preserve existing error codes and retry decisions.
Basic client authentication uses origin-bound headers for the resolved token
endpoint, never public headers. Token requests refuse redirects for both Basic
and body authentication. Vendor I/O remains outside the revision-checked commit
transaction. Native token field schemas remain a separate typing work item.

Webhook signals and subscriptions are typed at the vendor/runtime boundary.
Vendor event names and stream identifiers remain vendor-defined strings there;
subscription lifecycle operations use the shared state enum. App-level authority
preserves live source ORM identity without serializing those rows or its signing
secret. Subscription plans similarly exclude endpoint tokens and nested signing
secrets from generic snapshots. Receipt persistence still explicitly writes the
normalized five-field signal envelope, keeping deduplication and replay separate
from model snapshots.

On execution, HubSpot validates shared stream/tool identifiers against its own
enum and the active source selection before constructing HTTP requests. Custom
property names remain dynamic mapping data. Its webhook normalizer retains the
vendor's required timestamp in a frozen Pydantic hint while deduplicating, then
translates to the shared signal contract. Other vendors are not forced to supply
a timestamp merely because HubSpot requires one.

HubSpot's native batch header and routed record identity are validated separately:
unsupported object events still contribute to the account check without requiring
fields used only by supported records. Native millisecond timestamps survive
serialization; a datetime is exposed at signal projection. Batch deduplication
still keeps the latest event per object, retaining the first event on equal times.
This preserves the existing [v3 delivery contract](https://developers.hubspot.com/docs/api-reference/legacy/webhooks/guide),
not a migration to the separate journal API.

Intercom validates [notification metadata](https://developers.intercom.com/docs/references/webhooks/webhook-models)
and selects the item contract by topic. Direct conversation identity precedes a
nested conversation and then a conversation-typed item; contact notifications do
not inherit conversation-field requirements. Notion has separate
[challenge and signed-event contracts](https://developers.notion.com/reference/webhooks):
challenge tokens are excluded from generic snapshots, while change events carry
typed workspace/entity identities and optional timestamps. These vendor models
discard unconsumed message, document and actor fields; encrypted raw-body retention
continues under the existing webhook service policy.

Linear authenticates the raw request body before validating its timestamp and
routing metadata with vendor-owned Pydantic models. The existing one-minute
replay window and optional timestamp-header agreement follow
[Linear's webhook contract](https://linear.app/developers/webhooks).
Recognized entity/header names use native enums; unknown event and action names
remain open so unrelated vendor events retain their existing routing behavior.
Only identity and event metadata enter these models, not actor or document
content. The runtime still owns workspace checks, source selection, receipt
deduplication and post-commit dispatch. Raw-body retention is unchanged.

Salesforce similarly validates fixed CRM tool names, but its custom-object and
custom-field names remain dynamic source data. Confluence validates its fixed
stream vocabulary before discovery and nested reads. Its page-update mode and
validated command payload distinguish appending required text from updating a
title, replacing content, or preserving content when the update omits it.

Linear's Knowledge and Ticketing adapters validate their separate stream enums
before discovery and reads. Read cursors are frozen Pydantic values with aware
timestamps; attachment offsets are non-negative integers. Explicit encoders keep
the existing durable cursor formats independent of the model representation.
Workflow-state projection accepts the canonical integer or Decimal position,
refusing fractional Decimal values before the integer-only typed projection.

Both Linear adapters share a vendor-owned, typed GraphQL error envelope, separate
from canonical SOR record schemas. Partial data accompanied by errors is never a
successful projection. Linear reports [GraphQL rate limits as HTTP 400 with
`RATELIMITED`](https://linear.app/developers/rate-limiting); Eylo classifies that
response as retryable before the generic client-error rejection. HTTP auth and
server failures retain precedence. The adapter classifies the failure; the SOR
runtime still owns retries.

Linear Knowledge also validates the selected document, author, related-entity
and pagination fields into vendor-owned models before projecting source records.
The same document model supports attachment lookup/download. Null content and
deleted related users remain valid; missing required fields or malformed nodes
fail the page instead of producing partial records. A null record means not
found; a missing result field means a malformed response. Read-query variables
are typed and serialized at the HTTP boundary. Timestamp strings retain their
original spelling in source payloads, avoiding hash churn; cursor comparisons
and source metadata use parsed timestamps. This does not imply equivalent native
record coverage for the other adapters.

Linear Ticketing has its own native projections for all nine selected streams,
plus typed read variables, issue inputs and mutation replies. Native models stay
inside the adapter; selected source fields still cross the dynamic mapping
boundary before canonical Ticketing normalization. Omitted update fields remain
omitted; explicit null assignees still clear assignments. Linear's integer-only
estimate input rejects fractional values before sending a request, while read
estimates preserve the vendor's numeric representation. Create requires a team.
Mutation replies consume identity and revision, not an invented full issue.
Create-like operations with an uncertain transport outcome still require
reconciliation, never a blind adapter retry.

Jira, GitHub, Notion, Zendesk and Intercom return their native stream enums from
the selected-stream guard; discovery and downstream reads keep that validated
type rather than indexing a native catalog with unchecked strings. Freshdesk
also supports dynamic custom-object keys, so it converts only fixed-catalog
lookups to `FreshdeskStream`. This does not narrow custom-object selection.

Custom-field discovery translates vendor type descriptions into the shared
`SorFieldDataType` enum. Vendor field names and unsupported native descriptions
remain source data; existing JSON/text fallback mappings are preserved rather
than inventing new vendor support. Freshdesk's known numeric status, priority
and source codes use native enums, while unknown read-side values remain visible
as text. Writes still require a recognized code.

Freshdesk's existing Support mutation tools use vendor-owned Pydantic inputs and
identity/revision response projections. The writable source mapping is resolved
before constructing these inputs; discovered custom fields remain JSON. Partial
updates serialize only supplied fields, including explicit null text, and private
notes retain Freshdesk's native `private` boolean at the HTTP boundary. Revision
checks and tag read-modify-write use typed preflight projections. Uncertain writes
still require reconciliation rather than blind retries. These contracts cover the
adapter's existing [Freshdesk v2 ticket and conversation operations](https://developers.freshdesk.com/api/),
not every vendor field or write capability.

Freshdesk verification, discovery, list/exact reads and child expansions also
parse native Pydantic responses before projection. Consumed fields have explicit
types; additional source fields must remain valid JSON. Ticket/conversation
ownership is carried by typed expansion values, not hidden keys injected into
vendor dictionaries. Source-body snapshots preserve supplied IDs, timestamp
spelling and extra content; only canonical metadata normalizes those values.
Discovered company/custom-object fields remain open JSON rather than a fixed
platform schema. Pagination queries are typed, and custom continuation links
still pass the source/schema path fence before another request. Malformed known
fields are rejected before returning a page, even where older code ignored them.

Zendesk's Support mutations likewise construct vendor-owned inputs after resolving
writable mappings. Closed ticket choices are native enums; discovered custom
field values remain JSON. The native safe-update flag and timestamp form one
validated pair, preserving [Zendesk's collision protection](https://developer.zendesk.com/documentation/ticketing/managing-tickets/creating-and-updating-tickets/).
Ticket responses supply typed identity/revision evidence. Replies and private
notes instead select exactly one matching [comment audit event](https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_audits/)
before producing their receipt; a successful HTTP status alone is insufficient.
Zendesk verification, discovery, exact reads and all nine sync streams now parse
native response models. Comment and attachment rows carry explicit parent
identity rather than injected dictionary keys. User-role checks apply only to
user records, not tickets, groups or brands. Pagination requests use Python
field names and serialize Zendesk's native query keys at the HTTP boundary.
The [incremental export contract](https://developer.zendesk.com/api-reference/ticketing/ticket-management/incremental_exports/)
distinguishes cursor exports from time-based event exports; child offsets are
retained when an event batch exceeds the requested page size. Known malformed
fields fail validation, while unknown native status values remain available.
An uncertain external write is never considered safe to retry.

Zendesk's saved cursor envelopes are versioned models; valid version-one
checkpoints retain their encoding and stream binding. Its
[ticket metrics](https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_metrics/)
can include reply time in both minutes and seconds. Existing minute identities
retain `reply_time`; seconds use `reply_time_in_seconds`, preventing two units
from overwriting the same record. Exact reads use the same identity vocabulary.
A complete metric reconciliation repairs the projection;
updating code alone does not change previously synchronized rows.

## Source lifecycle

Intercom's v2.16 adapter parses native requests and responses before source-field
mapping. Conversation expansion carries parent IDs in typed adapter values while
retaining the source message snapshot separately. Search watermarks and offsets
use versioned contracts; updates distinguish omitted fields from explicit clears.
The [conversation retrieval limit](https://developers.intercom.com/docs/references/rest-api/api.intercom.io/conversations/retrieveconversation)
still refuses truncated part histories. Native
[attachment objects](https://developers.intercom.com/docs/references/rest-api/api.intercom.io/models/part_attachment)
need not contain an ID, and the opening conversation source can have a null ID.
The adapter preserves native IDs when supplied. Otherwise it identifies the
singleton opening source within its conversation and each attachment by its
position within the message. These are current-snapshot slots, not permanent
file identities: replacing or reordering files updates a slot. Expiring download
URLs never determine identity. List, continuation, exact reads and relationship
projection use the same identifiers; source snapshots retain the original fields.

Intercom's [v2.16 unassigned identity change](https://developers.intercom.com/docs/references/changelog)
returns zero instead of null for an unassigned conversation admin or team.
The vendor wire contract preserves that response, but source-field projection
converts the named unassigned sentinel to null. Zero is not a canonical Agent or
queue identity and must not create a relationship-repair job. Real identities and
explicit outbound unassignment requests are unchanged. Run source reconciliation
after deploying this correction to repair previously projected zero identities.

This does not add deletion reconciliation. Intercom's incremental child streams
can retain projected rows when a source message or attachment disappears. Full
reconciliation tombstones missing rows, but the current incremental stream does
not report parent-scoped removals. That cleanup requires a separate complete-parent
snapshot contract; it must not infer deletion from a partial or failed fetch.

GitHub account verification parses the native viewer response, then checks the
explicit repository list in one GraphQL request. Generated repository aliases
map to typed [repository metadata](https://docs.github.com/en/graphql/reference/repos);
each returned identity must match its configured repository. Sync projects these
fields into the source payload for mapping, not directly into a canonical entity.
Comment sync batches distinct issue numbers through `issueOrPullRequest` and
validates the [Issue/PullRequest union](https://docs.github.com/en/graphql/reference/issues)
before excluding pull-request comments. Missing classifications fail the page;
they are not treated as issues. GraphQL errors are classified before consuming
partial data. Unknown error types retain the generic failure outcome.
REST records and mutation bodies also use native models; update serialization
distinguishes omitted fields from explicit clears. Comment identity is classified
before validating retained bodies, so an excluded PR comment cannot fail the issue
page. Versioned cursor and webhook-identity models preserve valid saved encodings.

Jira resolves the configured site from Atlassian's
[accessible resources](https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/#3-1-get-the-cloudid-for-your-site)
before gateway requests; zero or multiple exact origin matches refuse access.
Site metadata, the viewer response and
[discovered fields](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-fields/)
use vendor-owned typed models. Unknown native custom-field types remain bounded
JSON, while known types map to canonical field kinds. Discovery typing does not
change configured scopes or imply complete Jira record-operation coverage.
Project, status, user and label reads also parse native models before projection.
Jira [comments](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-comments/)
use the same typed record for exact reads and sync. Embedded issue comments can
leave missing ranges; explicit parent identity follows each range into canonical
projection without modifying the vendor response. Pagination fences reject
changed offsets, shrinking totals and empty partial pages rather than silently
skipping comments.

Issue search and exact reads share a native issue model. Fixed reference fields
are typed; discovered custom fields remain validated JSON, including Sprint
fields mapped to cycle identity. Issue update watermarks retain their existing
reconciliation overlap. Native [issue links](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-links/)
carry typed inward/outward endpoints. Sync supplies the containing issue explicitly
when the embedded link omits that endpoint. The same direction rules apply during
post-create lookup: Jira's successful create response alone does not supply the
new link identity. An unresolved identity remains an uncertain outcome requiring
reconciliation, not permission to repeat the write.

Sprint scans validate the selected custom field separately from a full issue
response. Embedded JSON and legacy Sprint values become native objects; missing
or conflicting snapshots use an authoritative
[Agile Sprint read](https://developer.atlassian.com/cloud/jira/software/rest/api-group-sprint/#api-rest-agile-1-0-sprint-sprintid-get).
Dates retain their source representation until canonical normalization. Paging
tracks both the native issue page and the offset within its expanded Sprint list.

Jira [mutation requests](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/)
use native models for fields, transitions, assignment, comments and label actions.
Omitted update fields remain absent; explicit nulls retain their clearing meaning.
Custom mapped fields stay validated JSON at the adapter boundary. Generated
plain-text ADF has a narrow typed contract; it does not constrain arbitrary ADF
received from Jira. Transition selection still checks reachability before writing.

Jira's saved sync positions use versioned, vendor-owned models. Current issue,
comment, relation, Sprint and directory cursors retain their stored field names
and versions. Supported legacy positions keep their existing restart behavior;
obsolete board positions are not treated as issue-search positions. Invalid
timestamps, non-text continuation tokens and non-integer versions fail as
`VENDOR_CURSOR_INVALID`, rather than silently discarding a watermark or token.
Supplied timezone-aware timestamps retain their offset on encoding; saved JSON
timestamps normalize to UTC on decoding. This needs no database migration.

Canonical writable issue fields belong to the ticketing contract; Jira-native
field names and request models belong to its adapter. Configured custom-field
names remain dynamic. Nested native request validation failures become
`VENDOR_COMMAND_INVALID` before any HTTP request, just like final request
validation failures.

An organization configures a source in this order:

1. Create a new OAuth configuration and authorize it, or enter an API-key
   credential for a vendor that declares API-key authentication.
2. Create an unusable source draft with selected source objects.
3. Verify the account and persist one immutable schema discovery.
4. Map discovered fields to canonical fields or typed custom fields.
5. Publish the mapping and streams.
6. Commit one bootstrap generation and all dependency-ordered stream runs,
   then bind only its roots to Absurd.
7. Grant the active source and individual SOR tools to an Agent draft.
8. Publish the Agent so the exact tool and source authority is snapshotted.

Draft or unverified sources are not Agent authority. Organization-level source
configuration alone never exposes records to an Agent.

API-key source creation uses a narrow proof boundary. Eylo first validates the
catalog contract, exact instance origin, and selected objects, then performs a
bounded real vendor request. Only that verified candidate may create the
encrypted external connection and source draft, together in one transaction.
The plaintext key is not persisted in an onboarding draft and is never returned
to the console.

Every new-source flow also carries an organization-scoped onboarding-attempt
ID. Browser retry, popup retry, or a duplicated submit reuses the same source
when the non-secret definition still matches. Reusing that ID for different
input fails closed. **Start new** is the explicit boundary that creates another
source attempt. It first deletes any unfinished source or OAuth configuration,
including locally stored credentials and transient OAuth states. A connection
cannot be claimed by another source.

## Projection, custom data, and source authority

Each synchronized object has a shared record identity and, when canonical, a
profile-specific extension. Selected vendor fields are stored as typed custom
field values instead of being flattened into unbounded JSON.

Projection uses explicit data boundaries:

1. A vendor adapter parses the vendor-owned HTTP body. Its arbitrary and custom
   keys remain isolated inside the adapter.
2. `SorExternalRecord` seals the selected source fields in an immutable
   `SorSourcePayload`. Only the mapping engine may resolve its configured keys.
3. The published mapping converts those fields into the exact profile/entity
   payload class, such as `TicketingIssuePayload` or `CrmDealPayload`.
4. The vendor normalizer receives that typed payload object, not a dictionary,
   and returns the canonical domain object persisted by the profile service.
5. Durable tasks and JSONB columns use explicit object-to-wire conversion at
   their boundaries; the runtime does not pass persistence dictionaries back
   into domain policy.

The profile catalog and payload classes share the same canonical field names.
Relationship roles, field types, source formats, and OAuth encoding modes are
bounded enums. This keeps vendor JSON extensible without making platform-owned
code remember vendor or dictionary keys.

Agent writes follow the same rule in reverse. Each mutation tool declares a
profile-owned Pydantic payload, so orchestration and adapters receive objects
such as `TicketingAssignCommandPayload` rather than inspecting an untyped
dictionary. Create and update tools retain one deliberate dynamic object: the
fields published by that source's active mapping. Only the adapter translates
those mapped field names into vendor request JSON. A command becomes JSON when
its encrypted durable request is stored, then is validated back into the exact
tool payload class before a worker may call the vendor.

Vendor-defined objects that do not fit a canonical profile become custom
datasets. They are visible in operator audit grids, but are not Agent-readable
or writable in v1. This preserves company-specific data without pretending it
has canonical semantics.

The external system remains authoritative. Pulls and read-after-write project
source state into Eylo. Projection never emits a vendor mutation, so an inbound
sync cannot create a source-to-Eylo-to-source loop.

## Dependency-ordered sync and relationship repair

Each executable vendor manifest declares two separate facts per stream:

- `depends_on`: streams that should complete first when both are in one sync
  generation;
- relationship targets: the exact stream that owns each referenced vendor ID.

A relationship target is also a sync dependency. The console expands a user's
selection to its transitive dependency closure, while the domain service
rejects an incomplete selection from any client. This keeps the ordering rule
and the relationship rule in one executable vendor contract instead of relying
on UI convention.

Eylo validates the complete graph when the adapter registry starts. Activation
then persists one generation, one run per selected stream, and every initial
`PENDING` or `WAITING` state before starting durable work. Independent roots
may run together. A dependent run is released only after every selected parent
succeeds; a failed parent marks blocked descendants failed without pretending
they ran.

Vendor refresh and page download run without an open DB transaction. After a
page is available, one bounded transaction locks current source authority,
projects the page, and commits its checkpoint. Run finalization commits before
a separate generation-coordination transaction inspects sibling states and
releases children. The periodic worker repairs a terminal run newer than its
nonterminal generation if the process stops between those commits. Vendor
latency therefore cannot extend a row-lock lifetime, and sibling finalization
does not hold one stream's locks while waiting for another stream.

Recovery reads the exact bound engine task outside the DB transaction, then
rechecks the binding under the product-row lock. A cancelled task cancels the
unfinished receipt; a failed task, or completed task without a committed product
result, fails it. Terminal product rows are not overwritten. Source projection
and generation advancement happen after the receipt transaction commits.

Sync, command and webhook work share lifecycle orchestration, not interchangeable
row schemas. The frozen `SorWorkContract` validates the model's own state enum;
`SorBoundWorkService` retains that model type through reads and transitions.
Successful sync work accepts `SorSyncCounts`, command work accepts
`SorCommandCompletion`, and webhook work has no completion payload. Result fields
are assigned explicitly; callers cannot supply arbitrary ORM attribute names.
Command result JSON is finite and excluded from diagnostic snapshots. Task spawn
and engine cancellation remain outside the short product-row transactions.

Sync and webhook workers parse ID-only task parameters into typed requests. Sync
resume state carries a typed receipt plus stream/cursor context; encrypted cursors
are excluded from snapshots. Internal receipts remain objects until the Absurd
handler return boundary, where their existing JSON shape is serialized. Webhook
receipts retain raw JSON signals so a malformed signal can still be reported in a
failed receipt; only executable signals are decoded into canonical signal objects.
Typed vendor errors retain their code and recovery policy during webhook failure
handling rather than being flattened into a generic retryable exception.

HTTP contract refusals (invalid requests, query values, redirects or response
media) retain typed terminal vendor errors. They must not become generic Python
errors and enter provider retries. Transient transport failures retain their
retry policy; authorization failures retain their separate reauthorization
policy.

Only incremental work inherits a stream's committed cursor. Bootstrap and
reconciliation are complete scans with an empty, run-local cursor. They update
or replace the stream checkpoint only after bounded page commits, then
tombstone records the complete scan did not observe. This matters when a new
mapping revision is published: reusing the old incremental cursor would
reproject only recently changed records and leave a mixed-revision source.

Scheduling chooses one run kind per source generation. If any due stream needs
full reconciliation, that generation reconciles all of its selected due
streams, preserving their DAG instead of splitting parents and children across
different run kinds.

The DAG improves first-pass linking but is not the relationship authority.
Projection always persists a normalized relation intent identified by source,
vendor object, and external ID. It resolves immediately when both canonical
endpoints exist, stays pending otherwise, and retries when either endpoint
arrives. A bounded background sweep covers process interruption without
rewriting every unresolved intent each second or extending sync finalization.
Reconciliation tombstones intents and materialized edges when their origin or
endpoint disappears.

The adapter emits a canonical relation kind, a platform-owned relationship
role, and an optional vendor-native kind. The role selects the dependency
target; the canonical kind explains the business meaning; the vendor kind is
provenance only. Keeping these fields separate prevents a new vendor subtype
from silently becoming runtime routing policy.

Grid reads keep vendor identifiers for stable audit and Agent semantics, then
resolve human labels in one bounded batch per page. Resolution is constrained
to the same organization, source, target entity, and external ID. Missing or
ambiguous targets remain visibly unresolved instead of being guessed. This is
why a Jira issue can retain an account ID internally while the console presents
the assignee's name, project key, sprint name, and comment author.

Vendor discovery must follow the entity's real authority. Jira issues expose
Sprint membership even when the same user cannot enumerate or inspect the
owning boards. Eylo therefore materializes Jira cycles from the
schema-identified Sprint field and uses direct Sprint reads only to complete
partial values. It does not guess that a Sprint belongs to the project of an
arbitrary issue.

## Reads and mutations

Read tools query the synchronized projection. Responses preserve source,
mapping, and freshness provenance while excluding fields not exposed by the
published mapping and source grant.

Mutation tools file one durable command keyed by Agent run and tool call. The
worker:

1. rechecks the published Agent revision, tool, source grant, source state,
   mapping, fields, provider scopes, and exact result stream;
2. optionally checks the direct target's source revision;
3. executes one vendor operation under the durable step identity;
4. verifies the adapter returned the declared result stream before checkpointing;
5. checkpoints the vendor result;
6. reads the authoritative result record from the source;
7. updates the projection and terminal receipt;
8. files one PII-safe organization-visible action event;
9. resumes the waiting Agent run.

The Agent receives no speculative partial result. Ambiguous create outcomes
remain failed for reconciliation instead of being retried into duplicates.

Tool scope has two distinct meanings. `target_entities` is the narrow set an
Agent may address directly. Associated streams are related context the tool may
read or need. Result streams identify the record returned by a mutation. Keeping
these contracts separate prevents a related record from becoming an accidental
target and prevents a vendor write whose authoritative result cannot be
projected.

Action events are durable user-visible facts, not a copy of the source record.
Their deterministic identity is derived from the command. Retrying completion
therefore files the same event, while the payload contains only stable IDs,
action, vendor, projection disposition, and source revision. Comments,
descriptions, custom values, and contact PII stay in their owning projection.

Lossy post-commit events serve a different purpose: local listeners and cache
invalidation. Source activation/degradation, schema drift, mapping publication,
record projection/tombstones, and sync completion emit only after their DB
transaction commits. Losing one does not change canonical state or cause a
vendor action; reconciliation remains the correctness path.

Webhook work follows the same ownership split as the rest of the SOR runtime.
[`webhook_definition.py`](../../server/eylo/sor/runtime/webhook_definition.py)
owns the durable receipt contract,
[`webhook_ingestion.py`](../../server/eylo/sor/runtime/webhook_ingestion.py)
authenticates and deduplicates untrusted deliveries, and
[`webhook_processing.py`](../../server/eylo/sor/runtime/webhook_processing.py)
refetches authoritative records under Absurd. Vendor network work remains
outside DB transactions. The stable
[`webhooks.py`](../../server/eylo/sor/runtime/webhooks.py) module exposes the
small public surface used by routes, workers, jobs, and revocation. A broad
signal files one source-wide dependency generation; an already-active source
generation coalesces the hint until periodic reconciliation runs again.

Vendor subscription lifecycle is a separate boundary in
[`webhook_subscriptions.py`](../../server/eylo/sor/runtime/webhook_subscriptions.py).
It claims registration, renewal, or removal in one short transaction, performs
the vendor request after commit, then records the result in another short
transaction. Managed callback authority is stable and HMAC-derived per source;
Jira lists and recovers an exact prior callback before registering. A process
crash after vendor acceptance therefore does not blindly consume another
dynamic-webhook slot. Renewal rechecks the exact callback first, so a
vendor-deleted subscription is recreated rather than silently treated as
extended. Jira uses this path for its dynamic subscription; GitHub uses the
same three-phase boundary for one hook per selected repository. Confluence 3LO
cannot; its adapter truthfully remains polling plus reconciliation until an
installed Atlassian app delivery contract exists.

Jira, GitHub and Zendesk own their webhook-management wire models beside their
adapters. Registration, list, renewal and signing-secret responses become typed
values before recovery decisions; outbound models serialize only at the HTTP
boundary. Known event names belong to vendor enums, not canonical tool names.
Unknown response properties are ignored. Malformed consumed metadata is rejected
before cleanup, including malformed rows that otherwise would have been skipped.
This is stricter than the former dictionary access; it does not change source
authority, scopes or the subscription state machine.

GitHub recovery reads numbered pages on the selected repository path, up to ten
pages of 100 hooks. A full last allowed page is incomplete, never evidence that
the callback is absent; no registration follows that failure. Duplicate exact
matches are refused even when they span pages. Jira and Zendesk retain their
single-page completeness checks. See the native
[GitHub list contract](https://docs.github.com/en/rest/repos/webhooks?apiVersion=2026-03-10),
[Jira webhook contract](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-webhooks/)
and [Zendesk webhook contract](https://developer.zendesk.com/api-reference/webhooks/webhooks-api/webhooks/).
Signing secrets are excluded from ordinary model dumps and representations;
GitHub has an explicit outbound serializer, while Zendesk secrets pass directly
to the existing encrypted source-storage path.

Incoming Jira, GitHub and Zendesk deliveries also use vendor-owned routing models.
The adapters authenticate the original request before parsing event metadata;
they then emit the existing platform `SorWebhookSignal`. Source/subscription
matching, selected streams and receipt persistence remain platform/adapter policy,
not fields trusted from the request. Unknown event names stay open; unconsumed
issue bodies, customer details and attachment content are excluded from the
metadata models. Declared metadata with an invalid type is rejected even when
the former dictionary path would have skipped it.

Jira keeps its subscription-match IDs and millisecond timestamp handling.
GitHub keeps repository fences and the distinction between an absent
`pull_request` field and an explicitly null field, including after model
serialization. Zendesk preserves ticket/comment/attachment hints and broad sync
hints when an event lacks an exact child identity. These shapes follow the native
[Jira delivery format](https://developer.atlassian.com/cloud/jira/platform/webhooks/#format-of-the-webhook-data-sent-by-jira),
[GitHub event payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
and [Zendesk ticket events](https://developer.zendesk.com/api-reference/webhooks/event-types/ticket-events/).

Ingestion and replay share
[`SorStoredWebhookSignal`](../../server/eylo/sor/shared/webhook_contracts.py).
Ingestion keeps typed values through delivery-ID checks, fingerprinting and receipt
construction; JSON dictionaries exist only at hashing/storage boundaries. The
stored timestamp remains ISO text with the existing UTC offset representation so
fingerprints do not change. The worker validates the same model before converting
it into a live signal. Receipt ORM data remains JSON, rather than eagerly becoming
typed signals: a malformed stored row must still be reportable as failed without
breaking the worker's terminal-result serialization.

## Revocation and durable recovery

Onboarding results, sync-generation plans and locked page contexts use frozen
Pydantic contracts. Their ORM rows remain the exact transaction-owned instances;
those fields are excluded from representations, JSON snapshots and generated
JSON schemas. These results must not be passed to detached work. Sync counters
are separate serializable values and accept only non-negative integers.

DAG advancement retains each validated run-to-stream association while
releasing dependencies, rather than re-reading an optional stream identity.
Generation failure codes belong to the SOR domain, separate from vendor errors.

Connection revocation is a DB authority fence, not only a request to a worker.
One transaction clears the stored credential, marks every dependent source as
requiring reauthorization, files the safe organization-visible event, and
captures active sync, webhook, and command identities. Only after that commit
does Eylo ask Absurd to cancel the exact tasks.

The persisted fence remains authoritative if the API process exits between the
commit and task cancellation. Periodic SOR recovery finds active work under a
fenced source and cancels it, while unbound-work recovery excludes that source
instead of respawning its work.

Recovery converts selected DB rows into frozen Pydantic ownership values while
the read transaction is open. Only organization/work IDs leave that transaction;
SQLAlchemy rows and sessions do not. Cancellation runs afterward, independently
for each captured task. One failure does not hide other outcomes, while caller
cancellation still propagates. Event delivery recovery uses the same detached-ID
boundary before spawning and binding existing durable delivery rows.

SOR action and connection event payloads are explicit frozen Pydantic contracts.
SOR-owned enums describe their event types and projection dispositions; the
generic event subsystem still accepts a JSON envelope. Serialization occurs at
that boundary, preserving the existing event names, deterministic IDs and JSON
fields. The payload allowlist excludes vendor content, credentials, scopes and
arbitrary custom fields. Adding fields to a vendor response or ORM model does
not automatically add them to the user-visible event.

Command cancellation preserves ambiguity honestly:

- pending before a vendor write becomes `CANCELLED`;
- interrupted without a durable write checkpoint becomes
  `FAILED / MUTATION_OUTCOME_UNKNOWN`;
- interrupted after the vendor result checkpoint becomes
  `FAILED / POST_WRITE_CANCELLED`.

Final command projection locks the connection before the source and rechecks
the live connection, source, Agent run, published revision, tool, and exact
grant. Revocation uses the same lock order. Whichever commits first defines the
result; a later projection cannot cross an already committed revocation fence.

## Eylo-owned grid contract

Canonical read fields identify mapped SQLAlchemy attributes, which support
selective ORM loading. Filter and ordering compilation explicitly derives SQL
expressions from those attributes. Runtime-discovered custom fields retain
their separate computed-expression path; this does not widen the fixed entity
schema or load extra columns.

Read specs, custom-column contexts, ordering terms, decoded cursors and query
rows use frozen Pydantic contracts. SQL expressions, callbacks, model classes
and live ORM rows are instance-validated where applicable, retain identity, and
are excluded from snapshots and generated schemas. Only the explicit grid and
row response projections go to the API. A custom dataset has no profile
extension and may use a computed field such as its coalesced record label;
canonical entity specs reject such fields before selective ORM loading.

Pagination envelopes and tagged scalar values are validated Pydantic objects.
Decimal, date, offset-aware datetime and UUID tags retain the existing token
encoding. A token remains bound to its query; organization/source authority is
resolved separately. Boolean cursor comparisons use typed SQL bind values so
PostgreSQL can page grouped boolean fields, including nulls. The SQLAlchemy
`ColumnElement` value parameter remains heterogeneous at the query-builder
boundary; mapped attributes and JSON result conversions have explicit contracts.

Agent pagination has its own frozen query identity and version-two cursor model.
It preserves existing query fingerprints and timestamp offsets. Both initial and
subsequent pages resolve live Agent/source grants; a cursor cannot grant access.
Unknown cursor fields, invalid versions and timezone-naive boundaries are refused.
Source purge helpers accept only source-owned models; work selection pairs each
model with its own lifecycle enum. Their organization/source predicates and FK-safe
purge order remain unchanged, including removal of soft-deleted source-owned rows.

The console grid is an audit surface for the same projection Agents use. Eylo
owns the renderer-independent `sor-grid-v1` contract:

- typed columns, importance, wrapping, and default visibility;
- filter, sort, group, cursor, and source-selection semantics;
- row identity, detail action, and shareable URL state;
- server validation against the entity's field contract.

The current React table is only a renderer. A future virtualized grid may
render the same model and emit the same intents, but it must not own query
semantics, domain state, server policy, or URL serialization. This keeps the
product contract stable while allowing the rendering library to be replaced.
Collection reads project only the requested visible columns, while detail
reads return the complete record. Typed custom-field filters execute as
set-based record selection, and the canonical live-record order is indexed.
Those server guarantees keep renderer work and response size proportional to
the visible page rather than the total custom-field catalog.

Filter values use a separate scoped read because the visible page is an output,
not option authority. If choices were derived from that page, filtering would
remove its own selected label and grouping would expose only the first ordered
group. The filter-options read respects organization, profile, entity, and
selected sources while remaining independent of search, filters, grouping,
ordering, and cursors.

Ticketing issue detail follows the same rule. The drawer asks a bounded audit
projection for chronological live comments. It reports comments or source
history as available, not selected, or unsupported; absence is never presented
as an empty history when the data was not synchronized.

Support ticket detail uses the same renderer-independent contract in a
two-column audit drawer. The primary column shows the bounded canonical message
chronology, including explicit public-reply and private-note visibility. The
secondary column shows ticket metadata, SLA metrics, attachments,
relationships, provenance, and freshness. Missing related streams are reported
as not selected or unsupported rather than being confused with an empty
history.

The source drawer shows the same operational authority used by workers: current
resolved/pending/tombstoned relation totals, recent generations, each stream
run's state, and the stream dependency/relationship-target contracts. It does
not expose checkpoints, vendor payloads, or credentials.

Documents use the same pattern. The primary column renders current canonical
text, parent-first structured blocks, and lazily loaded current raster
attachments; unsupported source blocks stay visible as
retained-but-not-interpreted content. The secondary column resolves space,
author, source properties, attachments, relationships, provenance, and
freshness. A version badge signals when earlier versions exist in the source,
but Eylo does not copy or present the historical bodies. Humans can open the
source document for history or unsupported media.

## Failure and freshness

Sync intent is persisted before durable execution. Failed immediate queue
binding remains recoverable from committed rows. A source can become degraded
or require reauthorization without hiding its last known projection; the UI
shows freshness and source state so members can judge what an Agent perceived.

Schema rediscovery creates a new immutable revision. Existing projections stay
visible until an operator publishes a compatible mapping and re-synchronizes.

See the [SOR reference](../reference/systems-of-record.md) for current vendors,
profiles, API surfaces, and query limits. See
[Configure a System of Record](../how-to/systems-of-record.md) for the operator
workflow.
