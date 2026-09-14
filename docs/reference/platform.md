# Platform and repository map

## Deployable surfaces

| Path | Runtime responsibility |
| --- | --- |
| `server/` | FastAPI API, domain modules, provider sockets, pipelines, PostgreSQL persistence, Absurd durable work, and Taskiq ordinary tasks |
| `web/` | Member-facing React operator console using MobX, Tailwind CSS, and Base UI |
| `widget/` | Headless TypeScript transport/state SDK plus the Preact contact UI |
| `cli/` | OpenAPI-driven command-line client for public platform APIs |
| `infra/docker/eylo/` | Shared API, worker, pgvector/PostgreSQL, and Redis services with explicit development and production overlays |
| `design-system/` | Design references and component showcases; not a production runtime |

## Backend layers

| Layer | Owns | Dependency rule |
| --- | --- | --- |
| `eylo/framework/` | Provider-neutral Agent loop contracts and execution | imports no `eylo.*` platform package |
| `eylo/modules/` | Bounded-context models, domain rules, services, repositories, schemas, and routes | does not import sockets |
| `eylo/sockets/` | Vendor protocols, SDK clients, stream translation, and normalized adapter contracts | does not import modules |
| `eylo/pipelines/` | Cross-layer composition, durable execution, tool dispatch, and transport orchestration | may coordinate modules and sockets |
| `eylo/events/` | Ephemeral event schemas plus durable event domain and persistence | payloads remain bounded and typed |
| `eylo/listeners/` | Explicit in-process Pyventus listener manifest | unordered, concurrent, best-effort reactions |
| `eylo/jobs/` | Small worker entrypoints and task registration imports | delegates behavior to modules/pipelines |
| `eylo/products/` | Consumer-level composition built from platform capabilities | Campaigns is the current product package |

## API security planes

All routes are mounted below `/api`.

| Router | Principal | Boundary |
| --- | --- | --- |
| Private | authenticated member or API key | requested organization must match the authenticated organization; hidden resources return `404` |
| Public | unauthenticated or state-token-specific caller | registration, public session exchange, OAuth callback, webhooks, and transport establishment apply their own checks |
| Widget | authenticated contact session | organization/contact/session authority comes from the widget dependency, not request-selected ownership |

The console and CLI use the member API. The widget uses public session exchange,
widget routes, WebSocket, and WebRTC rather than member credentials.

Registration uses one auth-owned request contract; the auth service hashes its
password once and explicitly builds the organization-owned member-create value.
The request itself is not overwritten with the hash. Members without a stored
password cannot authenticate by password. Resetting a missing member returns the
existing invalid-reset response rather than dereferencing an absent ORM row.

Signed invitation/reset tokens have separate frozen claim models: purpose,
organization/member ID, email and expiry are required. The existing seven-day
invite and one-hour reset lifetimes remain unchanged. Malformed claims use the
same invalid-token path as failed signature/expiry checks. NumericDate encoding
is retained; ordinary JSON datetime serialization is not used for JWT payloads.
Signature verification alone does not require application claims to exist:
see [PyJWT claim-presence guidance](https://pyjwt.readthedocs.io/en/stable/usage.html#requiring-presence-of-claims).

Provider-config HTTP handlers accept the framework's general exception contract,
then narrow to their registered error family. Missing capabilities retain their
409 response; lifecycle validation retains 404/409/422 responses; unavailable
encrypted credentials retain 503. Cipher errors expose neither secret material
nor the underlying exception message in responses or logs. Unrelated exceptions
are re-raised rather than translated into a provider error.

## Analytics API contracts

Member analytics uses `/{organization_id}/analytics/{entity}/created` for
conversations, contacts, messages and members, plus
`/{organization_id}/analytics/conversations/created-per-agent`. These paths
are below `/api`. Optional `startDate` and `endDate` retain inclusive bounds;
`timeslice` accepts `day`, `week` or `month` and defaults to `day`.

The analytics domain owns these enums and frozen query/result models. SQL binds
the time unit as a parameter and validates named aggregate columns before the
read transaction closes. Responses preserve `count` and `date` (`YYYY-MM-DD`),
with `agentId` on per-agent points. The generated OpenAPI contract now describes
these response fields rather than an untyped list. Existing counting and
organization-authorization behavior is unchanged.

## Runtime processes

- `eylo.app` registers ORM models, pipeline extensions, and API-process
  listeners before constructing FastAPI.
- The API lifespan owns the WebSocket manager, WebRTC signalling service, and
  DB-pool cleanup.
- `eylo.agent_run_worker` registers all durable workflows before four
  independent lanes poll the shared Absurd queue. One lane claims one task, so
  a long external operation cannot stall claim polling in the other lanes.
- `eylo.taskiq_runtime` registers ordinary periodic actions on an acknowledged
  Redis Stream. Scalable task workers execute them; one scheduler sends cron
  messages.
- PostgreSQL is canonical business and durable-work storage.
- Redis supports coordination, live transport state, and the ordinary Taskiq
  queue; it is not canonical business storage.

## Persistence

`server/alembic/versions/eylo0001_initial_schema.py` creates the complete
current schema from an empty PostgreSQL database. It installs pgvector and the
pinned Absurd 0.5.0 schema alongside Eylo-owned tables, indexes, constraints,
and foreign keys. Later revisions are incremental and immutable after they are
applied.
`register_models()` imports every ORM model explicitly so API startup, workers,
Alembic, and standalone verification see the same metadata.

Organization-owned models carry an `organization_id`. Cross-resource foreign
keys include ownership columns when a relationship must not cross tenants.
Soft deletion preserves histories where product ownership requires it.

## Contract authorities

Tool API schemas and native execution schemas share definition metadata, not
mutable inherited fields with incompatible types. HTTP translation converts
camel-case envelopes into `PlatformTool`; organization ownership comes from the
authenticated route. Registered local tools use their code-owned schema. System
tools cannot be created through the local-tool endpoint.

Tool JSON columns retain JSON Schema keywords such as `$defs`, `oneOf` and
`additionalProperties`. Native input schemas also accept Python field names from
older stored rows; projection emits canonical keywords. This read compatibility
does not reconstruct fields already removed from a stored definition. Tool patch
conversion preserves omitted fields separately from explicit nulls.

- Generated OpenAPI: HTTP paths and schemas.
- Catalogs: supported provider identifiers and selectable fields.
- Factories: adapter executability.
- Published definition revisions: Agent, template, MCP, schedule, and campaign
  runtime authority.
- Durable rows: Agent-run, ingestion, memory, deletion, campaign, event, and
  recording state.
