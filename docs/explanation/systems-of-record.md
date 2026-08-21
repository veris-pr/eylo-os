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
6. Commit bootstrap sync runs, then bind them to Absurd.
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

Documents use the same pattern. The primary column renders canonical text and
parent-first structured blocks; unsupported source blocks stay visible as
retained-but-not-interpreted content. The secondary column resolves space,
author, source properties, version metadata, attachments, relationships,
provenance, freshness, and the selected Agent view. Every related surface says
whether its stream is available, not selected, or unsupported, so absence is
never misreported as an empty document history.

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
