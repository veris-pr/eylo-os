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

On execution, HubSpot validates shared stream/tool identifiers against its own
enum and the active source selection before constructing HTTP requests. Custom
property names remain dynamic mapping data. Its webhook normalizer retains the
vendor's required timestamp in a frozen Pydantic hint while deduplicating, then
translates to the shared signal contract. Other vendors are not forced to supply
a timestamp merely because HubSpot requires one.

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

## Source lifecycle

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
