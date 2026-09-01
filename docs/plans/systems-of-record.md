# Systems of Record: canonical runtime and audit console plan

Status: approved and in progress. Catalog entries remain planning metadata until
an executable adapter factory is registered and its end-to-end acceptance path
passes.

## End goal

Eylo exposes one stable, domain-native Agent surface for each System of Record
(SOR) profile while vendors remain replaceable adapters:

- CRM: contacts, companies, deals, activities, pipelines.
- Ticketing: issues, projects, workflows, cycles, comments.
- Customer support: tickets/conversations, customers, replies, notes, queues.
- External knowledge: spaces, documents, blocks, current revisions, attachments.

Agents read and mutate the authoritative vendor through explicit domain tools.
Eylo maintains an organization-scoped canonical projection for fast Agent reads
and a read-only operator console where humans can audit exactly what Agents can
perceive. Background work keeps the projection current without creating a
two-master database or a synchronization loop.

The first release is complete when two materially different vendors implement
each profile contract end to end. A contract implemented by one vendor alone is
not yet proven canonical.

## Implementation snapshot

- Shared persistence, source lifecycle, durable sync/command runtime, Agent
  grants, audit APIs, the Eylo-owned grid contract, post-commit lifecycle
  events, and organization-visible action events are implemented.
- HubSpot, Salesforce, Jira Cloud, Linear, GitHub Issues, Zendesk, Intercom, and
  Freshdesk have recorded-transport and real-PostgreSQL proofs; live vendor
  acceptance remains pending.
- Freshdesk proves API-key onboarding with pre-persistence verification and an
  encrypted organization-owned external connection.
- Confluence, Notion, and Linear Documents have registered adapters,
  recorded-transport proofs, canonical Documents reads/tools, and the
  two-column audit console. Linear document authorization, current document
  reads, and author reads passed against an operator-owned Linear workspace;
  current-image delivery remains recorded-transport proven because that sample
  contained no document images. SharePoint and the remaining third-vendor
  hardening remain deferred.
- Connection revocation now commits the credential revocation, source fence,
  safe event, and active-work snapshot atomically. Exact durable tasks are
  cancelled after commit; periodic recovery closes the process-crash gap; and
  unbound recovery cannot respawn work for a fenced source. Disposable
  PostgreSQL probes cover running-command terminalization and stranded-webhook
  recovery. Live-provider cancellation remains part of each vendor's acceptance.
- A current-checkout disposable deployment imports the complete app and runs the
  API plus durable worker. Public probes expose four profiles, ten executable
  vendors, 54 globally unique SOR Agent tools, and 37 SOR OpenAPI paths. The
  authenticated catalog and `sor-grid-v1` contract work through both API and
  CLI, and a second organization receives 404 for the first organization's
  source collection. No live vendor account is implied by these internal proofs.

## Settled product decisions

1. Vendor system is authoritative. Eylo is a canonical projection and command
   runtime, not a second source of truth.
2. Operator data pages are read-only in V1. Configuration pages can still
   connect sources, select data, publish mappings, and grant Agent access.
3. Agents mutate through explicit tools. The console does not create, edit, or
   delete source records in V1.
4. Inbound projection and outbound command execution are separate paths.
   Projecting a source record can never enqueue a source mutation.
5. SOR code is owned by top-level `server/eylo/sor/`, not `modules/`.
   `modules/` remains the core Agent-runtime definition.
6. Tools are profile-native, not vendor-native. Names use a short domain
   namespace and an expressive action, for example `crm_find_customer`,
   `issue_transition`, `support_reply`, and `docs_get`.
7. There is no default vendor, source, connection, field mapping, or tool grant.
8. Source identities are not merged across vendors in V1. A HubSpot contact and
   Salesforce contact remain separate records even if their emails match.
9. Grid and document views are V1. Canvas is deferred.
10. Vendor webhooks are hints, not the sole correctness mechanism. Every source
    has periodic reconciliation.
11. Eylo owns the collection and grid contract: query, filters, sorting,
    grouping, columns, selection, and row actions. A third-party grid is a
    replaceable renderer adapter and cannot define product or API semantics.

## Boundary and package layout

Proposed ownership:

```text
server/eylo/sor/
  shared/
    contracts.py          # shared value objects and adapter capabilities
    models.py             # source, mapping, record, sync, receipt, command
    repositories.py
    services.py           # domain policy; no vendor HTTP
    routes.py
    events.py
    tools.py              # shared tool authorization and dispatch
  crm/
    models.py
    schemas.py
    services.py
    repositories.py
    tools.py
    vendors/
      hubspot.py
      salesforce.py
      dataverse.py
  ticketing/
    models.py
    schemas.py
    services.py
    repositories.py
    tools.py
    vendors/
      jira.py
      linear.py
      github.py
  support/
    models.py
    schemas.py
    services.py
    repositories.py
    tools.py
    vendors/
      zendesk.py
      intercom.py
      freshdesk.py
  knowledge/
    models.py
    schemas.py
    services.py
    repositories.py
    tools.py
    vendors/
      confluence.py
      notion.py
      sharepoint.py
  runtime/
    jobs.py               # Absurd task definitions and handlers
    sync.py               # bootstrap, incremental, reconciliation
    webhooks.py           # public ingress and vendor verification
    commands.py           # source mutations and read-after-write projection
    registry.py           # explicit profile/vendor factory
```

Rules:

- Profile services own canonical policy and normalization rules.
- Vendor adapters implement profile ports and contain API-specific types,
  pagination, rate limits, authentication placement, and error translation.
- Routes translate HTTP only. They never normalize vendor payloads or call a
  vendor directly.
- Absurd is the sole durable execution authority for sync and mutation work.
- `pipelines/` may compose SOR tools into the Agent runtime, but the tool
  contract and execution handler remain owned by `sor/`.
- Existing Integration V2 curated tools do not become the SOR abstraction.
  Their OAuth, guarded HTTP, origin pinning, and mutation-receipt patterns are
  implementation references, not shared ownership.

## Connection and credential prerequisite

The current `connections` model is named generically but is constrained by a
foreign key to an Integration V2 installation. Reusing that row for SOR would
silently make SOR depend on Integration V2.

Before the first SOR vendor, extract a source-neutral external-account boundary
inside the core connections module:

### `external_connections`

- `id`
- `organization_id`
- `contact_id` (nullable; retained for existing Integration use)
- `owner_kind`: `ORGANIZATION | CONTACT`
- `vendor_key`
- `auth_kind`
- `instance_origin` (normalized, origin-pinned; nullable for fixed origins)
- `granted_scopes`
- encrypted `credentials`
- `credentials_expires_at`
- `revision`
- `status`: `INITIATED | ACTIVE | DEGRADED | REAUTH_REQUIRED | REVOKED`
- refresh-attempt and last-success/failure metadata

Domain tables reference this row with real foreign keys:

- Integration V2 uses an installation-to-connection link.
- `sor_sources.external_connection_id` references it directly.
- OAuth state references the initiated external connection, not a polymorphic
  domain object.

This keeps credential lifecycle generic without adding a weak
`subject_type/subject_id` relationship. SOR V1 accepts organization-owned
connections only. Contact-owned/private SOR data is deferred because Eylo has
organization membership but no row-level RBAC or source-ACL projection.

Credential invariants:

- OAuth authorization code flow uses one-time state, PKCE where supported, and
  consumes state in a committed transaction before token exchange.
- API-key source creation verifies a catalog-bound candidate before persistence.
  A successful request stores the encrypted credential and source draft in one
  transaction; plaintext secrets never enter resumable browser state or an API
  response.
- Tokens and API secrets stay encrypted outside the adapter invocation.
- Redirect, token, API, and webhook origins are catalog-owned and pinned.
- A revoked or expired connection stops new syncs, resumed syncs, and commands.
- Required scopes derive from the enabled streams and tools. Adding scope
  requirements forces reauthorization; it never silently widens access.
- Verification uses the cheapest bounded real call and closes all resources on
  success, failure, timeout, and cancellation.

## Shared canonical persistence

Profile tables hold stable business fields. Shared tables hold source identity,
provenance, custom data, and execution state.

### Configuration and schema

#### `sor_sources`

One configured source for one organization and profile.

- identity: `id`, `organization_id`, human name, onboarding-attempt ID
- selection: `profile`, `vendor_key`, `external_connection_id`
- config: required vendor settings, selected datasets/objects, config revision
- state: `DRAFT | VERIFYING | DISCOVERING | BOOTSTRAPPING | ACTIVE |
  DEGRADED | REAUTH_REQUIRED | DISABLED`
- active schema and mapping revision IDs
- webhook endpoint token hash, subscription ID, status, and expiry
- freshness target and required sync interval
- verification, last successful sync, last reconciliation, and last error

There is no unique constraint on organization plus profile or vendor. One
organization may connect several Salesforce orgs, Jira sites, or Notion
workspaces. Names disambiguate them in the UI.

The onboarding-attempt ID is generated by the console and is unique within the
organization. Retrying one saved/new-source flow returns the same source. A
different payload with the same attempt ID fails with a conflict, while
**Start new** creates a fresh attempt ID. This idempotency key does not limit
how many sources an organization may configure. Each source onboarding flow
owns its external connection and OAuth connector. The same saved OAuth app is
never offered to another source. **Start new** deletes an unfinished source or
connector before resetting the browser draft.

#### `sor_schema_revisions`

Immutable normalized snapshots from vendor discovery:

- source and monotonically increasing revision
- schema hash
- discovered object, field, relationship, enum, and capability metadata
- vendor/API version
- discovered timestamp and discovery run ID

The active schema changes only after the complete discovery transaction commits.

#### `sor_mapping_revisions`

Immutable, publishable mapping configuration:

- source, revision, source schema revision
- `DRAFT | ACTIVE | STALE | INVALID | SUPERSEDED`
- creator/publisher and timestamps
- projection version

Publishing a mapping is explicit. New source fields never silently widen the
data Eylo stores or exposes to Agents.

#### `sor_field_mappings`

Rows within a mapping revision:

- vendor object key and stable vendor field key
- source label and source data type
- canonical target path, or custom-field identity
- transform kind and bounded transform config
- direction: `READ_ONLY | READ_WRITE | IGNORE`
- Agent visibility and UI default-column flags
- nullable, enum choices, sensitivity label, and writable capability
- mapping state and incompatibility reason

Transforms are code-owned named operations such as timestamp normalization,
money plus currency, rich-text-to-plain-text, enum mapping, identity reference,
and array normalization. This is not a user-authored expression language.

### Records and relationships

#### `sor_records`

One source-scoped identity row for every projected object:

- `id`, `organization_id`, `source_id`
- profile and canonical entity kind
- vendor object key, external ID, and optional human external key
- source-created and source-updated timestamps
- source revision/ETag/version where available
- selected raw payload and payload hash
- active mapping/projection revision
- projected timestamp and last successful sync run
- tombstone timestamp and deletion reason
- source URL

Unique identity is `(organization_id, source_id, vendor_object_key,
external_id)`. Every profile extension table references both record ID and
organization ID so cross-tenant relationships fail at the database boundary.

`selected_raw_payload` contains only fields approved by the active mapping. It
does not become a second unbounded data lake and never stores credentials.

#### `sor_record_relations`

- source-scoped `from_record_id` and `to_record_id`
- canonical relation kind and native relation kind
- external relation ID when supplied
- source revision and tombstone state

This represents contact-to-company, deal-to-contact, issue parent/blocker,
ticket requester, document parent, and comparable source relationships.

#### `sor_relation_intents`

One vendor-normalized relationship claim is persisted before both endpoints
need to exist:

- source-scoped origin record and stable external relation identity;
- exact from/to vendor object keys and external IDs;
- canonical and vendor-native relation kinds;
- `PENDING | RESOLVED | TOMBSTONED` state, attempt metadata, and safe error code.

Resolution looks up both endpoints by organization, source, vendor object, and
external ID. It never asks a vendor adapter to interpret platform identity.
Endpoint arrival retries touched intents immediately; stream completion retries
the source backlog; a throttled worker sweep repairs process-crash gaps.

### Custom fields

#### `sor_custom_field_definitions`

Stable field identity independent of a display-name change:

- source, vendor object key, stable vendor field key
- current label, description, type, choices, and source group
- read/write capability and sensitivity classification
- first seen, last seen, and removed timestamps

#### `sor_custom_field_values`

Typed values reference `sor_records` and a field definition. Exactly one typed
column is populated per non-null value:

- text
- decimal
- boolean
- date
- timestamp
- string/identity array
- reference to another `sor_record`
- bounded JSON for a vendor structure with no safe scalar representation

Typed rows make custom columns filterable and sortable without casting arbitrary
JSON for every query. Null values are represented by no value row plus the
field definition, not by several nullable value columns being set.

### Custom objects and datasets

Custom fields on a canonical entity are first-class. Arbitrary custom objects
are different: their meaning cannot be inferred safely from a vendor schema.

V1 behavior:

1. Discovery lists custom objects/tables/data sources.
2. A member explicitly enables an object and its fields.
3. Eylo syncs it as an audit-only custom dataset using `sor_records`, typed
   custom fields, and relations.
4. The console renders it with the shared grid and detail drawer.
5. The object gets no generic Agent mutation tool.
6. To make it Agent-operable, map it to a canonical entity or add a curated
   profile extension and explicit tools in a later revision.

This prevents the SOR layer from degenerating into the same noisy generic API
surface that Integration V2 replaced.

### Schema drift

- Stable vendor field IDs, not labels, anchor mappings.
- Added fields and objects appear as pending schema differences. They are not
  synced until a new mapping revision is published.
- Renamed fields retain identity and update their label.
- Removed fields retain historical values, become unavailable for new reads,
  and are never written.
- Type changes mark the mapping incompatible and disable writes immediately.
- Publishing a compatible mapping can enqueue durable reprojection from the
  selected raw payload. A transform that needs missing source data enqueues a
  source refetch instead.
- Every projected record exposes schema and mapping revision, so the console
  can explain exactly which interpretation the Agent saw.

## Profile adapter factory

There is no single giant universal adapter. Shared lifecycle protocols are
small; each profile has a typed business protocol.

### Shared lifecycle port

Every adapter implements:

- `verify_connection()`
- `discover_schema()`
- `bootstrap_stream()`
- `pull_changes()` when supported
- `fetch_record()`
- `fetch_deleted()` when supported
- `subscribe_webhook()`, `renew_webhook()`, and `remove_webhook()` when supported
- `verify_webhook()` and `parse_webhook_signal()`
- `execute_command()`
- `close()`

### Profile ports

Examples:

- `CrmAdapter.normalize_contact/company/deal/activity()`
- `TicketingAdapter.normalize_issue/comment/project/workflow()`
- `SupportAdapter.normalize_ticket/message/customer/group()`
- `KnowledgeAdapter.normalize_space/document/block/attachment()`

### Capability manifest

The code-owned vendor spec declares executable facts:

- auth modes and required scopes
- fixed or instance origin
- readable/writable entities
- webhooks and their verification scheme
- delta/cursor/updated-at/full-reconcile support
- deletion signals
- custom fields and custom objects
- conditional writes/source revisions
- history, comments, attachments, structured document formats
- rate-limit hints and subscription renewal requirements

The explicit factory resolves `(profile, vendor_key)` to one adapter. It has no
reflection, scanning, fallback vendor, or default source. Catalog presence does
not claim support; live verification, sync, cleanup, tool dispatch, UI
projection, and tenant isolation are all acceptance requirements.

## Durable work and synchronization

### Operational tables

#### `sor_source_streams`

One row per enabled source object/stream:

- source and vendor object key
- canonical entity kind
- code-owned `depends_on` stream keys and relationship-target stream mapping
- strategy: `DELTA | CURSOR | UPDATED_AT | FULL_RECONCILE`
- opaque cursor/checkpoint
- overlap/lookback window where applicable
- cursor version and last committed source boundary
- schedule, state, last success/failure, and record counts

Opaque vendor cursors are never parsed or fabricated. Cursor updates and the
records they cover commit in the same owned transaction.

#### `sor_sync_generations`

One source-level DAG execution:

- source and one generation-wide kind;
- `PENDING | RUNNING | SUCCEEDED | FAILED | CANCELLED` state;
- start/end timestamps and safe terminal error.

Every selected stream gets one run in the generation. Roots start as
`PENDING`; dependent runs start as `WAITING`. A child becomes runnable only
after every selected parent succeeds. Parent failure terminalizes descendants
with `DEPENDENCY_FAILED`. The generation and every run commit before any root
is bound to Absurd.

#### `sor_sync_runs`

- source, generation, stream, kind (`SCHEMA | BOOTSTRAP | INCREMENTAL |
  WEBHOOK_REFETCH | RECONCILIATION | REPROJECTION`)
- `PENDING | RUNNING | WAITING | SUCCEEDED | FAILED | CANCELLED`
- Absurd task ID and attempts
- start/end/checkpoint and safe error summary
- added/updated/tombstoned/unchanged/rejected counts

#### `sor_webhook_receipts`

- source, vendor delivery ID or normalized fingerprint
- event type, entity key/ID, vendor event time
- payload hash, signature result, replay result, and processing state
- bounded encrypted raw body retained only until processing/diagnosis TTL

Unique `(source_id, vendor_delivery_id)` prevents duplicate delivery. Vendors
without a delivery ID use a stable fingerprint over source, event type, entity,
event timestamp, and payload hash.

#### `sor_commands`

The command row is also the one durable mutation receipt:

- organization, source, profile tool, Agent/run/tool-call IDs
- idempotency key and request hash
- target canonical record and expected source revision
- `PENDING | RUNNING | SUCCEEDED | FAILED | CONFLICT | CANCELLED`
- safe normalized result, external request ID, source revision after write
- attempts, timestamps, and error category

One tool call creates one command row. Retry reuses it; it never creates a
second source mutation receipt.

Interactive execution does not create a second non-durable fast path. The tool
runner persists and enqueues the same command, then waits for its durable state.
If the bounded interactive window expires, the Agent run releases runtime
capacity and waits durably for command completion. Completion resumes the same
tool call and message-linked Agent run. Failure returns one typed tool error;
partial command results are never exposed as success.

### Tasks

- `sor.discover_schema`
- `sor.bootstrap_source`
- `sor.sync_stream`
- `sor.process_webhook_receipt`
- `sor.reconcile_source`
- `sor.reproject_mapping`
- `sor.execute_command`
- `sor.renew_webhook`
- `sor.refresh_connection`
- `sor.prune_transient_receipts`

The scheduler only enqueues due infrastructure work. It does not decide Agent
intent. Stream claims serialize cursor mutation per `(source, stream)` while
different streams may run concurrently. This is a cursor integrity rule, not an
ordering guarantee for Pyventus events.

### Initial and ongoing sync

1. Member creates a source and connection.
2. Verification succeeds.
3. Schema discovery creates an immutable schema revision.
4. Member reviews and publishes a mapping revision.
5. The product commits one bootstrap generation, every stream run, and their
   dependency states before any root run is enqueued.
6. Root streams run concurrently. Successful parents release their dependent
   streams; every page projects records and checkpoints atomically.
7. Webhooks enqueue targeted refetches where possible.
8. Incremental pulls close webhook gaps.
9. Periodic reconciliation detects missed updates and deletions.
10. Relationship intents resolve optimistically during projection and retry
    after stream completion when an endpoint arrived later in the DAG.
11. A complete full-scan reconciliation may tombstone unseen records only after
    the scan succeeds. A partial or failed scan never infers deletion.

### Loop prevention: mandatory algorithm

Eylo does not implement generic two-way replication. It implements two
unidirectional paths with distinct authorities.

#### Inbound path

`vendor change -> webhook/poll -> fetch current source record -> normalize ->
canonical projection`

Projection code has no dependency on the outbound command service. After commit
it may emit a projection event, but no projection event has an outbound writer
listener.

#### Outbound path

`Agent tool -> authorize -> persist command -> vendor mutation -> read response
or refetch -> canonical projection -> auditable domain event`

Required guards:

- command idempotency key is stable for the Agent tool call;
- expected source revision/ETag is used when the vendor supports it;
- revision conflict rejects the write and asks the Agent to reread;
- vendors without revisions use read-before-write plus read-after-write and a
  request receipt;
- the command response may project immediately, but this projection does not
  enqueue another command;
- the later webhook echo upserts the same source identity and revision/hash,
  becoming an unchanged no-op;
- webhook delivery ID and source revision protect against duplicates and
  out-of-order delivery;
- no database trigger or ORM callback turns a local projection update into an
  external request.

The strongest loop-prevention proof is structural: there is no “sync local row
back to vendor” listener. Only an authorized Agent command can enter the
outbound gateway.

## Webhook ingress

Public route shape:

`/api/sor/webhooks/{vendor_key}/{opaque_endpoint_token}`

The random endpoint token resolves the source. Organization/source identity is
never accepted from the payload. The route then:

1. enforces method, content type, and bounded body size;
2. handles vendor endpoint-validation protocols;
3. verifies the signature/JWT/HMAC against the raw body and timestamp;
4. rejects stale/replayed requests;
5. commits a deduplicated receipt and normalized signal;
6. returns the vendor-required success response quickly;
7. lets Absurd refetch and project outside the request transaction.

Payload data is not trusted as the complete record unless the adapter contract
explicitly proves that event type is a versioned full snapshot. Default behavior
is refetch-by-ID. Subscription expiry and renewal are persisted and visible.

## Events

### Ephemeral post-commit events

Used for internal cache invalidation and listeners. No ordering guarantee:

- `sor.source.activated`
- `sor.source.degraded`
- `sor.schema.changed`
- `sor.mapping.published`
- `sor.record.projected`
- `sor.record.tombstoned`
- `sor.sync.completed`

Payloads contain organization, source, canonical record/entity, revision, and
safe status only. They never contain an entire CRM contact, support message, or
document body.

### Durable organization-visible events

Durable events represent human-useful Agent actions, not every synchronized
record. Initial set:

- `sor.connection.connected`, `sor.connection.reauth_required`,
  `sor.connection.revoked`
- `crm.contact.created`, `crm.contact.updated`
- `crm.deal.created`, `crm.deal.updated`, `crm.deal.stage_changed`
- `issue.created`, `issue.updated`, `issue.transitioned`, `issue.commented`
- `support.ticket.opened`, `support.ticket.updated`,
  `support.ticket.assigned`, `support.ticket.replied`,
  `support.ticket.noted`, `support.ticket.closed`
- `docs.document.created`, `docs.document.updated`, `docs.document.appended`

Event payloads include canonical record ID, source/vendor, action, Agent/run and
tool-call IDs, command receipt ID, timestamp, and safe result. They omit message
bodies, document content, email, phone, and arbitrary custom values. Sync run
tables, not durable events, provide operational sync history.

## Agent authorization and tools

Two explicit grants are required:

1. Agent-to-tool mapping controls what action the Agent may request.
2. `sor_source_grants` controls which source the Agent may read/write.

A configured organization source does not implicitly grant any Agent access.
The runtime requires an active published Agent revision, active source, active
external connection, compatible mapping revision, mapped tool, and source grant.

Source grants are configured against the Agent and snapshotted into the
published Agent revision, like tools. Runtime also rechecks the referenced live
grant before fresh execution and durable resume. Revocation therefore stops an
in-flight or resumed run immediately; recreating a grant does not silently add
it to an already published revision.

Source grants contain `READ | READ_WRITE`; write permission is further narrowed
by tool mapping, adapter capability, and field mapping. Multiple sources are
allowed. Read tools can search all granted sources and return source identity.
A create command must resolve exactly one writable source; if several qualify,
the tool returns the choices instead of guessing. If exactly one qualifies,
using it is deterministic resolution, not a configured default.

Read tools query the local canonical projection and always return source,
`as_of`, mapping revision, and freshness state. They do not hide a vendor HTTP
request or claim stale data is current. Data beyond its configured freshness
target is returned with an explicit stale warning so the Agent can explain the
limitation. Mutations always refetch the target revision before writing; a stale
local target is never used as an unconditional write base.

### Custom data in Agent tools

- Read results include Agent-visible mapped custom fields.
- `*_describe_fields` tools expose only the active source schema and mappings
  available to that Agent.
- Mutation tools accept custom values by stable field key, validate type and
  enum choices, and reject stale, read-only, or unmapped fields.
- Audit-only custom objects receive no Agent tools in V1.
- Tools never accept a vendor URL, organization ID, final storage path, or raw
  API request from model output.

### Search indexes

Canonical names, keys, titles, descriptions, and normalized message/document
text use PostgreSQL full-text and appropriate scalar indexes. Custom fields use
their typed value indexes. `docs_search` is lexical in SOR V1 and returns source
document/version citations. Semantic retrieval remains the responsibility of
an explicitly populated Eylo Knowledgebase; SOR does not create a hidden second
embedding index.

## CRM profile

### Canonical entities

#### Contact

- names, emails, phones, job title
- lifecycle/native status
- owner
- company and deal relations
- source and activity timestamps
- custom fields

#### Company

- name, domains, industry, employee range
- addresses and phones
- owner
- contact and deal relations
- custom fields

#### Deal

- title, amount, currency, probability
- pipeline, stage, normalized state (`OPEN | WON | LOST`)
- owner, expected/actual close dates
- contact/company relations
- custom fields

#### Activity

- kind (`NOTE | EMAIL | CALL | MEETING | TASK | OTHER`)
- subject, normalized text, occurred timestamp
- actor, participants, direction
- related contacts, companies, and deals

#### Reference entities

- owner/user
- pipeline
- stage, stage order, and normalized state

### Tools

Read:

- `crm_find_customer`
- `crm_get_customer`
- `crm_get_customer_history`
- `crm_list_deals`
- `crm_get_deal`
- `crm_get_deal_history`
- `crm_describe_customer_fields`
- `crm_describe_deal_fields`

Write:

- `crm_create_contact`
- `crm_update_contact`
- `crm_create_company`
- `crm_update_company`
- `crm_create_deal`
- `crm_update_deal`
- `crm_move_deal`
- `crm_add_note`
- `crm_log_activity`

`customer` is a search/result concept over contacts and companies. Storage
keeps them typed; the tool never merges them automatically.

### Vendor plan

| Vendor | Canonical sources | Change strategy | Custom data | Auth |
| --- | --- | --- | --- | --- |
| HubSpot | contacts, companies, deals, activities, owners, pipelines, associations | object/property webhooks -> refetch; updated-time search with overlap reconciliation | properties, association labels, custom objects | OAuth authorization code; private token only for bounded self-hosted use |
| Salesforce | Contact/Lead, Account, Opportunity, Task/Event, users | Change Data Capture/Pub/Sub replay; `SystemModstamp`/Bulk reconciliation | describe metadata, custom fields, custom objects | OAuth external client app |
| Dataverse/Dynamics | contact, account, opportunity, activities, system users | OData change tracking/delta; registered webhooks where configured | table/column metadata and custom tables | Microsoft Entra OAuth/MSAL |

Implementation order: HubSpot plus Salesforce prove the contract. Dataverse is
the third adapter. Pipedrive can follow using the already curated Integration V2
request-shape work as a reference.

Important vendor constraints:

- HubSpot webhook subscriptions are app-level, so receipt routing must resolve
  the installed account/source correctly.
- Salesforce CDC events are retained for a bounded period and replay IDs are
  opaque; reconciliation remains mandatory.
- Salesforce change events contain changed-field metadata, not a license to
  overwrite unchanged fields with empty values.
- Dataverse delta links are opaque and tied to the original query. Mapping or
  selected-field changes start a new stream checkpoint.

### CRM audit UI

Navigation:

- CRM / Customers
- CRM / Companies
- CRM / Deals
- CRM / Activities
- CRM / Custom datasets

Customers may present contacts and companies in one search result, but typed
filters and details remain explicit. Deal detail shows pipeline/stage, related
customers, recent activities, source, freshness, mapping revision, custom
fields, and “Open in source.” No data mutation actions appear.

## Ticketing profile

### Canonical entities

- project/team/workspace
- issue
- workflow/status and normalized status category
- priority
- user/assignee/reporter
- label
- cycle/sprint/milestone
- comment
- attachment/link metadata
- issue relation (`PARENT | CHILD | BLOCKS | BLOCKED_BY | RELATED | DUPLICATE`)

Issue fields include key, title, description, type, normalized and native
status, priority, project/team, assignee, reporter, estimate, labels, parent,
cycle/milestone, due/start/completed/cancelled timestamps, source URL, and
custom fields. Rich vendor documents retain source format and normalized text.

### Tools

Read:

- `issue_search`
- `issue_get`
- `issue_get_history`
- `issue_list_projects`
- `issue_list_workflow_states`
- `issue_describe_fields`

Write:

- `issue_create`
- `issue_update`
- `issue_transition`
- `issue_assign`
- `issue_comment`
- `issue_link`
- `issue_add_label`
- `issue_remove_label`

### Vendor plan

| Vendor | Canonical sources | Change strategy | Custom data | Auth |
| --- | --- | --- | --- | --- |
| Jira Cloud | projects, issues, fields, workflows, users, comments, versions/sprints | signed/dynamic webhooks -> refetch; JQL `updated` overlap scan; webhook renewal | system and custom issue fields, project contexts | OAuth 2.0 3LO; basic token only for local/self-hosted operator use |
| Linear | teams, issues, states, projects, cycles, users, comments, labels | HMAC webhooks with delivery ID/timestamp; GraphQL `updatedAt` reconciliation | labels, relations, project/cycle metadata; capability manifest must not claim arbitrary custom fields | OAuth 2.0 or explicit API key |
| GitHub | repositories, issues, users, comments, labels, milestones; optional Projects V2 metadata | operator-configured signed webhooks -> refetch; REST updated-since reconciliation with bounded GraphQL PR classification for comment pages | issue metadata now; Projects V2 fields remain future work | OAuth 2.0 now; GitHub App installation remains the preferred future least-privilege model |

Implementation order: Jira plus Linear, then GitHub Issues. The current GitHub
adapter excludes pull requests from issue and comment sync because GitHub's REST
issue endpoint returns them together. Future pull-request support must model
them explicitly as linked records; it must not silently reinterpret them as
issues. GitHub issue relations, sub-issues, dependencies, and Projects metadata
also remain outside this first adapter revision.

### Ticketing audit UI

Navigation:

- Issues / Issues
- Issues / Projects
- Issues / Cycles and milestones
- Issues / Custom datasets

Issue drawer shows description, current state, people, project/cycle, labels,
relations, comments, source history where available, custom fields, freshness,
and source link. Unsupported vendor history is shown as unavailable, never as an
empty history claim.

## Customer support profile

### Canonical entities

- support ticket/case (including Intercom conversation-backed cases)
- customer/requester
- Agent/assignee and group/team
- inbox/brand/channel
- public reply and private note
- tag
- SLA/metric summary when supplied
- attachment metadata

Ticket fields include subject, normalized description, requester, assignee,
group, normalized status (`NEW | OPEN | PENDING | HOLD | RESOLVED | CLOSED`),
native status, priority, type/category, channel, tags, first-response and
resolution timestamps, SLA state, source URL, and custom fields.

Messages preserve visibility (`PUBLIC | PRIVATE`), author, direction, body
format, normalized text, attachment metadata, and exact chronology. A private
note can never be normalized into a customer-visible reply.

### Tools

Read:

- `support_find_customer`
- `support_find_ticket`
- `support_get_ticket`
- `support_get_customer_history`
- `support_list_queues`
- `support_describe_ticket_fields`

Write:

- `support_open_ticket`
- `support_update_ticket`
- `support_assign_ticket`
- `support_reply`
- `support_add_note`
- `support_close_ticket`
- `support_add_tag`
- `support_remove_tag`

### Vendor plan

| Vendor | Canonical sources | Change strategy | Custom data | Auth |
| --- | --- | --- | --- | --- |
| Zendesk | tickets, audits/comments, users, organizations, groups, fields, metrics | cursor incremental export plus signed webhook refetch; deleted records retained in stream | ticket fields in the current adapter; user/org fields and custom objects remain future work | OAuth in the current adapter; API-token mode remains future work |
| Intercom | conversations, contacts, admins, teams, parts, tags, attachments | updated-at search plus full reconciliation; signed operator-managed webhook refetch | conversation attributes in v1; companies, Intercom Tickets, ticket types, and custom objects remain future work | OAuth bearer; exact US/EU/AU API and consent origins |
| Freshdesk | tickets, conversations, contacts, companies, agents/groups, fields | `updated_since` polling/reconciliation; product events only when the required Freshworks app mode is installed | ticket/contact/company fields and custom objects | API key initially; OAuth/app mode when executable |

Implementation order: Zendesk plus Intercom, then Freshdesk. Zendesk's cursor
export is the reference for a true incremental adapter; Intercom proves a
conversation-first model; Freshdesk proves a polling-primary adapter and the
API-key onboarding path. All three are implemented locally; live acceptance is
still required.

### Support audit UI

Navigation:

- Support / Tickets
- Support / Customers
- Support / Queues
- Support / Custom datasets

Ticket detail uses a two-column layout: message/reply chronology on the left,
ticket metadata, SLA, source, mapping, and freshness on the right. Public
replies and private notes use distinct neutral icons and labels; color remains
reserved for danger.

## External knowledge profile

This profile is not Eylo's internal retrieval Knowledgebase. External knowledge
syncs source-authoritative documents for audit and domain tools. Internal
Knowledgebase remains the chunked retrieval/index plane. A later explicit
pipeline may publish selected external documents into an internal Knowledgebase
without collapsing their ownership or revision models.

### Canonical entities

- workspace/site/space/library/data source
- document/page
- hierarchical content block
- version
- label/property
- attachment/file metadata
- author/owner reference

Document fields include title, parent/path, source format, normalized text,
source body, content hash, version, lifecycle state, author/owner, labels,
created/updated timestamps, source URL, custom properties, and unsupported-block
summaries. Files remain metadata records; the console may proxy a bounded,
tenant-authorized current raster attachment for document rendering. OCR, URL
crawling, historical bodies, and general attachment extraction remain out of
scope.

### Tools

The `docs_*` namespace avoids collision with Eylo's existing internal
Knowledgebase tools such as `kb_query` and `kb_write`.

Read:

- `docs_search`
- `docs_get`
- `docs_list_children`
- `docs_describe_fields`

Write:

- `docs_create`
- `docs_update`
- `docs_append`
- `docs_comment` only for vendors with a proven comment contract

### Vendor plan

| Vendor | Canonical sources | Change strategy | Custom data | Auth |
| --- | --- | --- | --- | --- |
| Confluence Cloud | spaces, pages, page bodies, current revisions, properties, attachments | full reconciliation | content properties retained for audit | Atlassian OAuth 2.0 3LO |
| Notion | pages, recursive blocks, data sources, properties, attachments, authors | full reconciliation | page/data-source properties, relations, and rollups | OAuth or explicit internal integration token |
| SharePoint | sites, lists, list items, document libraries, drive items, pages | Microsoft Graph change notifications plus list/drive delta links and subscription renewal | list columns, content types, custom lists | Microsoft Entra OAuth |

Confluence and Notion intentionally advertise only full reconciliation in the
current revision; no webhook capability is claimed. Notion page properties and
page content use separate calls: the adapter recursively retrieves blocks and
separately completes paginated relation and rollup property values. SharePoint
remains next; its notifications will signal change while delta links provide
the authoritative changed/deleted set.

### Knowledge audit UI

Navigation:

- Documents / Documents
- Documents / Spaces and data sources
- Documents / Custom datasets

The grid shows title, space/source, parent, type, version, author, updated time,
freshness, and source. Document view renders sanitized normalized content,
preserves hierarchy, marks unsupported blocks explicitly, shows the source
format/version, and links to the original. It never pretends a partially
translated plugin/block was understood.

## Operator console architecture

### Navigation

Add `Systems of Record` as a top-level group, separate from Platform, Sockets,
Products, and Integrations:

- Overview
- Sources
- CRM
- Issues
- Support
- Documents

Profile submenu items appear only when their routes are functional. Source
configuration remains available even before data pages are populated.

### Shared audit collection template

Every entity list uses the existing URL/MobX/service/component split:

- URL: source, search, filters, sort, group, selected record, visible columns.
- MobX store: canonical entity cache and request lifecycle.
- API service: generated client only.
- components: shared toolbar, filter tree, sorting, table, empty/error/loading
  states, and detail drawer.

The canonical query and grid metadata contracts live in Eylo. They define
stable field keys, typed filters, nested AND/OR groups, sort and grouping terms,
cursor pagination, column priority, wrapping, and the permitted row actions.
The UI translates that model into a renderer's props. LyteNyte, AG Grid, or any
other package remains an implementation adapter with no authority over URLs,
API payloads, MobX state, permissions, or domain behavior.

Layout:

- page title, short profile description, source/freshness summary;
- one row: search left, gap, filter and order right;
- applied filters below, empty by default;
- important canonical columns first;
- selected custom columns next;
- source and human-readable dates near the right;
- final view action column;
- long text wraps; responsive views do not require page-level horizontal
  scrolling. Dense grids may use a contained table scroller only after priority
  columns collapse into the drawer.

There are no New, Edit, Delete, bulk-mutation, or inline-edit actions on data
pages in V1.

### Detail drawer

Tabs/sections:

- Summary
- Relationships
- Custom fields
- Activity/messages/history when relevant
- Source and provenance
- Sync health
- Current document revision and source-history signal where the vendor exposes
  versions; old bodies remain in the source.

### Configuration UI

Source configuration is a categorized resumable form:

1. Profile and vendor
2. Connection/authentication
3. Datasets/objects
4. Canonical and custom field mapping
5. Sync interval and freshness target
6. Webhook status
7. Agent source grants
8. Review and activate

Schema mappings use a dialog/grid because they are relational, not a hundred
controls dumped into one form. Submit clears the local draft. “Start new” first
deletes the unfinished source, local credentials, and OAuth config, then resets
the form. Refresh retains an unfinished draft. Active data remains visible
while a new mapping revision is drafted.

## Public API surface

Read-only audit APIs:

- `GET /api/sor/sources`
- `GET /api/sor/sources/{source_id}`
- `GET /api/sor/sources/{source_id}/sync-runs`
- `GET /api/sor/sources/{source_id}/schema-diff`
- `GET /api/sor/{profile}/{entity}`
- `GET /api/sor/{profile}/{entity}/{record_id}`
- `GET /api/sor/custom-datasets`
- `GET /api/sor/custom-datasets/{dataset_id}/records`

Configuration APIs:

- source create/configure/verify/disable
- API-key source create with bounded verification
- OAuth start/callback and reconnect
- schema discover
- mapping draft/publish
- bootstrap/reconcile/reindex trigger
- Agent source-grant management

There are deliberately no generic `POST /records`, `PATCH /records`, or
`DELETE /records` APIs in V1. Agent mutations enter the same typed command
services as the registered domain tools, never a raw vendor proxy.

List APIs support server-side search, typed filter tree, sort, group, cursor
pagination, source selection, and aggregate display projections. Tenant mismatch
returns 404. Enums remain machine values in the API and badges in the UI; dates
remain typed timestamps and render human-readably.

## Delivery plan

### Phase 0: connection boundary and contracts

- Generalize external connection persistence without weakening foreign keys.
- Define SOR enums, source state machine, adapter capability manifest, and
  profile ports.
- Add catalog-only UI for the four profiles; no false vendor support status.
- Acceptance: Integration V2 still authorizes and executes through the
  generalized connection boundary; revocation is rechecked on resume.

### Phase 1: shared projection and custom data

- Add source, schema, mapping, record, relation, custom-field, stream, sync-run,
  webhook-receipt, command, and source-grant models through the incremental SOR
  migration.
- Implement schema discovery, mapping publication, typed custom values, and
  source-scoped tenant constraints.
- Implement shared read APIs and audit collection/detail templates.
- Acceptance: a synthetic adapter proves canonical plus custom fields, schema
  drift, tombstones, tenant isolation, filter/sort, and Agent-view projection.
  Remove the probe before commit.

### Phase 2: CRM vertical slice

- Implement HubSpot and Salesforce from auth through tools and UI.
- Prove webhook echo does not cause a second write.
- Prove a custom field round trip and a custom object audit grid.
- Run one large milestone review only after both vendors pass.

### Phase 3: Ticketing vertical slice

- Implement Jira and Linear.
- Prove rich description normalization, transitions, comments, relations,
  webhook verification, and reconciliation.
- Add GitHub after the canonical contract survives both vendors.

### Phase 4: Customer support vertical slice

- Implement Zendesk and Intercom.
- Prove public/private message semantics, incremental cursor, custom fields,
  SLA availability, reply/note/close commands, and conversation-first mapping.
- Add Freshdesk polling-primary support.

### Phase 5: External knowledge vertical slice

- Confluence, Notion, and Linear Documents implementation is complete through
  recorded transport, real PostgreSQL projection, canonical tools, hierarchy,
  versions, structured blocks, unsupported-block disclosure, custom properties,
  and document view. Linear current-document and author reads also passed live.
- Run live acceptance against operator-owned Confluence and Notion accounts;
  complete Linear image acceptance with a document containing a current upload.
- Add SharePoint delta/subscription support.
- Add an explicit later pipeline for publishing selected source documents to an
  Eylo internal Knowledgebase; do not hide it inside sync.

### Phase 6: hardening and third vendors

- Dataverse, GitHub Issues, Freshdesk, SharePoint.
- Rate-limit budgets, large-account bootstrap, cancellation, subscription
  renewal, replay windows, cursor corruption recovery, and conflict UX.
- Regenerate API client, reset baseline on a disposable DB, run affected local
  checks, run milestone review, then real-provider QA.

## Acceptance matrix for every vendor

Each adapter must prove the public path with a real provider account:

1. create source;
2. authorize and verify;
3. discover standard and custom schema;
4. publish mapping;
5. bootstrap at least two pages;
6. update a source record externally and observe webhook/poll projection;
7. delete/archive a source record and observe a safe tombstone;
8. read it through a domain Agent tool;
9. mutate it through an allowed domain Agent tool;
10. observe one command receipt and one source mutation;
11. receive the echo webhook and prove no second mutation;
12. revoke the connection and prove fresh, resumed, and in-flight work stops;
13. verify another organization receives 404 and cannot infer record identity;
14. inspect the same data and provenance in the console;
15. cancel/disconnect and prove all HTTP/stream/task resources close.

Record unexercised vendor capabilities honestly. Recorded transports can protect
request shapes but do not count as live vendor support.

### Current acceptance evidence

The implementation has two deliberately separate evidence levels. Internal
proof establishes that Eylo's shared contract is executable; only a live vendor
run can establish that a provider currently accepts the request, permission,
webhook, pagination, and cleanup behavior.

| Acceptance area | Current internal evidence | Remaining live evidence |
| --- | --- | --- |
| source, auth, schema, mapping | public OpenAPI surface, explicit factories, encrypted connection ownership, recorded transports, real PostgreSQL lifecycle | create and authorize each vendor source; discover the operator account's real standard and custom schema |
| bootstrap, projection, tombstone | durable page checkpoints, webhook/poll receipts, source-scoped idempotent projection, real PostgreSQL projection probes | bootstrap two real pages; observe one external update and one delete/archive through webhook or poll |
| Agent reads and commands | 54 unique profile-native tools, Agent source grants, one durable command authority, terminal receipts, echo suppression | read and mutate through a published Agent against each real source; observe one provider mutation and no echo write-back |
| revocation and isolation | atomic connection/source fence, terminalized in-flight work, periodic crash recovery, non-respawn proof, organization-scoped repositories and 404 routes | revoke while a real request is fresh, resumed, and in flight; repeat one record lookup from another organization |
| operator console and grid | Eylo-owned URL/query/grid contract, source/provenance projection, synthetic browser QA | inspect each vendor's real projected record, provenance, custom data, pagination, and shared URL |
| resource cleanup | bounded HTTP clients, adapter close paths, task cancellation, disposable current-source composition import | disconnect/cancel each real vendor path and confirm no leaked HTTP stream, task, or provider session |

The schema-backed catalog now publishes vendor-side setup notes for Jira,
Linear, GitHub, Confluence, and Notion. The shared onboarding page renders those
notes without vendor-specific UI branches, so callback, account visibility,
team/repository selection, optional webhook, and Notion capability requirements
are visible before credentials are entered.

OAuth completion treats the persisted external connection as authority. The
popup message remains an immediate UX signal, while a popup close without a
message now triggers the same connection refresh instead of producing a false
failure after a provider or browser severs `window.opener`.

No vendor is live-accepted yet. The next milestone is the 15-step matrix above
against operator-owned accounts, beginning with the vendors already available
to the user: Jira, Linear, GitHub, Confluence, and Notion.

## Explicit deferrals

- local console mutation of SOR data
- generic arbitrary custom-object Agent tools
- cross-source identity merge/master-data management
- per-user source ACL mirroring
- bidirectional conflict-free replication or last-write-wins
- workflow designer and arbitrary transform DSL
- canvas visualization
- OCR, URL crawling, and binary attachment extraction
- historical version warehouse beyond source-provided history and command
  receipts
- automatic publication of external documents into internal Knowledgebases

## Risks and controls

| Risk | Control |
| --- | --- |
| sync loop | distinct command and projection paths; no projection-to-command listener; idempotent command receipt |
| missed webhook | overlap/delta polling plus periodic reconciliation |
| duplicate/out-of-order webhook | delivery receipt, source revision/hash, refetch-current strategy |
| cursor skips committed data | advance checkpoint in same transaction as projection page |
| schema drift corrupts writes | immutable schema/mapping revisions; disable incompatible writes |
| custom data becomes unqueryable | stable definitions and typed value rows |
| custom object explodes tool catalog | audit-only until explicit canonical extension |
| credential leakage | encrypted core connection boundary; resolved only at adapter invocation |
| private source data exposed to all members | organization-owned shared datasets only in V1; no personal SOR sources |
| frontend disagrees with Agent perception | Agent-view API uses runtime projection and grants |
| vendor-specific concepts leak into core | two-vendor gate before freezing each profile contract |
| source rate limits | per-source budgets, bounded pages, `Retry-After`, durable backoff, and visible degradation |

## External references

Official vendor contracts:

- [HubSpot CRM properties](https://developers.hubspot.com/docs/api-reference/latest/crm/properties/guide),
  [associations](https://developers.hubspot.com/docs/api-reference/latest/crm/associations/overview),
  [webhooks](https://developers.hubspot.com/docs/api-reference/latest/webhooks/guide),
  and [OAuth](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/oauth/oauth-quickstart-guide)
- [Salesforce Pub/Sub durability](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/event-message-durability.html),
  [change event deserialization](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/event-deserialization-considerations.html),
  and [API integration patterns](https://developer.salesforce.com/docs/atlas.en-us.integration_patterns_and_practices.meta/apexcode)
- [Dataverse Web API](https://learn.microsoft.com/en-us/power-apps/developer/data-platform/webapi/overview),
  [change tracking](https://learn.microsoft.com/en-us/power-apps/developer/data-platform/use-change-tracking-synchronize-data-external-systems),
  and [webhooks](https://learn.microsoft.com/en-us/power-apps/developer/data-platform/use-webhooks)
- [Jira issue fields](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-fields/),
  [issue search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/),
  [OAuth](https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/),
  and [webhooks](https://developer.atlassian.com/cloud/jira/software/webhooks/)
- [Linear GraphQL platform](https://linear.app/developers),
  [OAuth](https://linear.app/developers/oauth-2-0-authentication), and
  [webhooks](https://linear.app/developers/webhooks)
- [GitHub Issues REST API](https://docs.github.com/en/rest/issues),
  [webhook best practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks),
  and [webhook payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
- [Zendesk incremental exports](https://developer.zendesk.com/api-reference/ticketing/ticket-management/incremental_exports/),
  [ticket fields](https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_fields/),
  and [webhook verification](https://developer.zendesk.com/documentation/webhooks/verifying/)
- [Intercom data attributes](https://developers.intercom.com/docs/references/rest-api/api.intercom.io/data-attributes),
  [contacts](https://developers.intercom.com/docs/references/2.14/rest-api/api.intercom.io/contacts),
  and [tickets](https://developers.intercom.com/docs/references/rest-api/api.intercom.io/tickets)
- [Freshdesk API](https://developers.freshdesk.com/api/) and
  [Freshworks product events](https://developers.freshworks.com/docs/app-sdk/v3.0/support_agent/serverless-apps/product-events/)
- [Confluence REST v2 pages](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/)
  and [content properties](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-content-properties/)
- [Notion webhooks](https://developers.notion.com/reference/webhooks),
  [event delivery](https://developers.notion.com/reference/webhooks-events-delivery),
  [authorization](https://developers.notion.com/guides/get-started/authorization),
  [API versioning](https://developers.notion.com/reference/versioning),
  [page Markdown](https://developers.notion.com/reference/retrieve-page-markdown),
  [page properties](https://developers.notion.com/reference/page-property-values),
  and [comment capabilities](https://developers.notion.com/reference/create-a-comment)
- [Microsoft Graph change notifications](https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks),
  [delta query](https://learn.microsoft.com/en-us/graph/delta-query-overview), and
  [SharePoint list item delta](https://learn.microsoft.com/en-us/graph/api/listitem-delta)

Open-source implementation references:

- [Airbyte](https://github.com/airbytehq/airbyte) for stream discovery,
  incremental state, cursor checkpoints, overlap windows, deletion behavior,
  and append-plus-deduplicate semantics.
- [Nango](https://github.com/NangoHQ/nango) for multi-tenant OAuth connection
  lifecycle, code-owned sync/action functions, webhook forwarding, cursor-based
  record delivery, and per-connection execution.
- [Singer specification implementations](https://github.com/singer-io) for
  explicit schema, record, and state/bookmark messages.

These projects are references for failure modes and runtime mechanics. Eylo
retains its own DDD boundaries, Absurd durability, explicit Agent grants, and
domain-native tool contracts.
