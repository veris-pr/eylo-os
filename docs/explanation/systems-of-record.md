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

## Source lifecycle

An organization configures a source in this order:

1. Create or select an OAuth connector, or enter an API-key credential for a
   vendor that declares API-key authentication.
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
source attempt.

## Projection, custom data, and source authority

Each synchronized object has a shared record identity and, when canonical, a
profile-specific extension. Selected vendor fields are stored as typed custom
field values instead of being flattened into unbounded JSON.

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
extended. Jira uses this path because OAuth apps can manage dynamic webhooks.
Confluence 3LO cannot; its adapter truthfully remains polling plus reconciliation
until an installed Atlassian app delivery contract exists.

## Revocation and durable recovery

Connection revocation is a DB authority fence, not only a request to a worker.
One transaction clears the stored credential, marks every dependent source as
requiring reauthorization, files the safe organization-visible event, and
captures active sync, webhook, and command identities. Only after that commit
does Eylo ask Absurd to cancel the exact tasks.

The persisted fence remains authoritative if the API process exits between the
commit and task cancellation. Periodic SOR recovery finds active work under a
fenced source and cancels it, while unbound-work recovery excludes that source
instead of respawning its work.

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
