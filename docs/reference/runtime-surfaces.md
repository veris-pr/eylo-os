# Runtime surfaces

## API

`server/eylo/app.py` constructs FastAPI and mounts three router planes below
`/api`: member-private, public, and contact/widget. It also serves static
playground assets and exposes `/health`.

The running OpenAPI document is the request/response reference. Do not maintain
a second handwritten endpoint catalog.

### Internal query and result contracts

Agent, contact and member collection queries are frozen, strict Pydantic values.
HTTP routes parse strings into domain enums and UUIDs before constructing them;
services receive organization authority and pagination separately. Agent search
keeps its existing whitespace normalization; contact/member search is unchanged.

Conversation-file upload authority holds exact published Agent and embedding
config revisions. Curated vendor offers validate the registry-to-domain handoff
without importing the registry into domain policy. Voice transcript rollups
validate nonnegative counts and durations; an unknown duration remains `None`.

Internal snapshots are not automatically replayable or public responses. Memory
reindex inspection preserves ORM row identity but excludes those rows from
snapshots. Widget development bootstrap excludes the session token from internal
representations and snapshots; its explicit authenticated-session response still
supplies the token needed by the widget. These values do not own DB transactions,
provider connections or task lifetimes.

Session timeline definitions use the existing category and severity enums;
technical visibility is derived from the technical category. Event names, detail
allowlists and public response spelling are unchanged. Contact-erasure context
preserves locked ORM row identity and excludes the entire graph from snapshots.
Memory-erasure results contain exact UUID sets; owner predicates use explicit ORM
columns for agent, contact and conversation partitions. These contracts do not
change deletion ownership, transaction boundaries or graph-change refusal.

## Durable worker

`python -m eylo.agent_run_worker` registers model metadata, pipeline tools,
listeners, Agent-run executors, every durable workflow, required event
consumers, and one transition handler for already-persisted legacy periodic
ticks before polling. The API process does not perform durable jobs in the
background as an alternative execution owner.

## Ordinary task worker and scheduler

`taskiq worker eylo.taskiq_runtime:broker` consumes acknowledged messages from
the `eylo-ordinary-tasks-v1` Redis Stream. Each cron action is an independent
message, so one failure does not suppress other due actions. Per-action Redis
locks prevent two workers from executing the same catalog action concurrently;
execution, lock, redelivery, and stream-retention bounds are explicit in
`eylo.periodic_work` and `eylo.taskiq_runtime`.

`taskiq scheduler eylo.taskiq_runtime:scheduler --skip-first-run` is the one
allowed scheduler process. It sends due messages but does not execute tasks.
Task workers may scale horizontally; scheduler replicas must remain one.

## Outbound HTTP boundary

`common/http_egress.py` owns destination policies and the `HttpEgressErrorCode`
enum. `sockets/http/transport.py` resolves public addresses, pins the connection
while retaining Host/TLS authority, bounds responses, and limits redirects.
Origin-bound credentials are attached only to their declared origin.

Origins, routes, destination policies, credential envelopes, requests, responses
and resolved targets are frozen Pydantic values. HTTP methods and initial/redirect
target phases use boundary-owned enums. Request construction normalizes supported
method strings; fixed-method producers use the enum directly. Scalar validation
does not coerce booleans into ports, limits or timeouts. An omitted HTTPS port
means 443; an explicit zero port is rejected.

Header/query mappings are copied into immutable views. Request URLs, credentials,
raw headers and bodies are excluded from representations and serialized snapshots;
these snapshots are diagnostic projections, not replayable wire requests.
Direct constructors retain safe `HttpEgressPolicyError` failures. The newly
available Pydantic `model_validate`/`model_validate_json` APIs use standard
`ValidationError` semantics. DNS resolvers, HTTP clients and resource owners remain
behavioral interfaces/classes, not data models.

`HttpEgressPolicyError` requires an enum member, not an arbitrary string. SOR,
MCP and email translate that transport category into their own retry and delivery
outcomes. A transport failure after a possible send must not become proof that
the effect did not happen. Timeout and cancellation remain distinct from policy
refusal. This enum does not replace vendor-specific error contracts or alter the
existing domain retry policies.

## Operator console

The authenticated console exposes the repository documentation under
**Resources → Documentation**. The route is organization-scoped so links are
shareable inside the console, while the rendered content remains platform-wide
and comes from `README.md` plus `docs/**/*.md` at build time. Search runs in the
browser; documentation has no DB rows, API controller, or MobX store.

The React console uses public member APIs and generated OpenAPI types.

| Feature folder                                            | Surface                                                                          |
| --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `features/agents`, `features/swarms`                      | Agent drafts/revisions, relations, voice stack, swarm members                    |
| `features/providers`                                      | schema-driven provider catalog, forms, verification, tools, and config lifecycle |
| `features/knowledge`, `features/memory`                   | knowledgebases/jobs/grants and memory inspection                                 |
| `features/integrations`                                   | marketplace, installations, connections, and tool policy                         |
| `features/conversations`, `features/sessions`             | canonical exchanges and cross-conversation user-session timelines                |
| `features/voice`, `features/telephony`                    | voice configs/sessions/recordings, numbers, and calls                            |
| `features/automations`, `features/campaigns`              | schedules and outbound campaign product                                          |
| `features/operations`                                     | Agent runs, event health, voice sessions, and system status                      |
| `features/contacts`, `features/members`, `features/tools` | organization entities and tool catalogs                                          |

MobX stores own canonical client entities and API coordination. The URL owns
shareable list/detail/filter state. Components own transient interaction state.

## Widget SDK

`widget/src/` owns transport and reactive state:

- contact-session consumption after a host bootstrap resolves authority;
- Agent and conversation selection;
- WebSocket protocol and reconnect behavior;
- message, participant, auth, tool, and interface events;
- voice/WebRTC control and media lifecycle;
- conversation-file upload capability.

The SDK does not choose an organization or contact in production. Local-only
fixed identity comes from paired server environment variables.

See the [Widget SDK reference](widget-sdk.md) for its current source API and
distribution status.

## Preact widget UI

`widget/preact-ui/` composes the SDK into the contact journey: Agent list,
conversation list/unread state, message exchange, file upload, connection
authorization signals, and voice controls. The SDK's state machine is
authoritative; the UI does not invent a parallel call lifecycle.

The Preact/host bootstrap exchanges production invitations and starts
local-only development sessions before passing the resulting contact session to
the SDK. See [Use the Widget SDK from Preact](../how-to/use-widget-sdk.md).

## CLI

The CLI reads the live OpenAPI document, discovers resources and actions, and
calls public APIs. It stores base URL, organization ID, and bearer token in its
local config. `--json` preserves machine-readable output; default rendering is
human-oriented.

System of Record operations use the concise `sor` resource. Run
`eylo sor actions` against the target API to see the exact available actions
and required identifiers. Examples include `eylo sor get-catalog`,
`eylo sor list-sources`, and `eylo sor get-grid-contract knowledge document`.
The resource name supplies the namespace, so actions do not repeat `sor`.

The CLI never writes platform tables directly.

CLI-owned Pydantic contracts project the OpenAPI fields used for command
discovery and required-input hints. They are not a second copy of the server's
domain models or a complete OpenAPI validator. HTTP methods and authentication
requirements are explicit enums; the request handoff carries named fields rather
than an untyped keyword dictionary. Runtime-defined API bodies remain JSON, with
non-finite numbers rejected at input and response boundaries. Tokens and request
content are excluded from diagnostic model snapshots; the normal authenticated
request and explicit `--json` output still receive their intended data.

The CLI has its own dependency environment and lockfile. After CLI dependency
changes, synchronize from `cli/` with `uv sync --locked`; a passing server-only
type check does not verify the CLI package or its imports.

The local `deploy-widget` command requires `--bucket` or `AWS_S3_BUCKET`.
Missing bucket configuration is rejected before build cleanup or AWS calls.
Its deployment helper accepts an omitted project root and resolves the checkout
root; this does not select a bucket or provision AWS resources.
