# Domain module catalog

`server/eylo/modules/` contains bounded contexts. A module owns its records and
rules; another module reaches it through a service, aggregate projection,
event, or pipeline rather than taking over its tables.

## Standard submodule meanings

| Name | Responsibility |
| --- | --- |
| `domain.py` | enums, value objects, invariants, lifecycle transitions, and typed errors |
| `models.py` or `models/` | SQLAlchemy persistence shape |
| `schemas.py` or `schemas/` | API, event, and persistence boundary shapes |
| `repositories.py` or `repositories/` | organization-scoped persistence queries |
| `services.py` or `services/` | use-case orchestration and transaction-local behavior |
| `controllers.py` or `controllers/` | transport input/output translation |
| `routes.py` or `routes/` | FastAPI endpoint registration only |
| `catalog.py` | deterministic code-owned choices exposed to operators |
| `resolver.py` | turn an explicit ID/revision into effective runtime authority |
| `verification.py` | bounded real-provider credential/resource check |
| `wiring.py` | build module services from the active or supplied transaction |
| `tasks.py`, `jobs.py` | persisted work records or task entrypoints; durable execution stays in pipelines |
| `events.py` | module-owned event filing or emission contracts |

Not every context needs every layer. Simple read models remain direct queries;
business invariants remain in domain/services rather than being invented to
make folder shapes symmetrical.

## Identity, tenancy, and interaction

| Module | Owns | Important submodules and contracts |
| --- | --- | --- |
| `organizations` | organization identity and creation | models, repository, schemas, service; organization creation seeds required organization-owned definitions |
| `members` | organization members and member list/detail projections | listing query, models, repository, services; no roles or RBAC |
| `auth` | member registration/login, bearer/API-key auth, password reset, invitations, public/widget sessions | `dependencies/`, `routes/`, `controllers/`, `services/`, widget invitations |
| `contacts` | end-user identity, identifier precedence, deduplication, lifecycle, and contact APIs | member and WebSocket controllers, list query, repository, service; no implicit contact merging |
| `connections` | organization- or contact-owned external connection state | domain constants, models, repositories, services, refresh task; credential consumers remain outside projections |
| `session_context` | channel-neutral request/session context passed into runtime | dependency, schema, and service boundary; supports HTTP, WebSocket, telephony, and WebRTC |
| `user_sessions` | an end-user visit/call plus conversations observed during it | lifecycle service, durable fact filing, list query, and timeline projection |
| `conversations` | conversations, participants, canonical messages, request status, runtime queue state, and member aggregates | private/public/WS controllers and routes, message/participant repositories, prompts, scheduled actions, tasks |

Canonical tool-use arguments and tool results accept finite JSON values, not
arbitrary Python objects. Message ORM annotations reflect the stored string and
JSON columns; neutral schemas validate enum and content meaning before history
conversion. Internal `MessageUpdate` patches allow only run identity, request
status, feedback and metadata. Omitted fields preserve existing values; explicit
null remains distinct. This contract does not bypass service authorization,
request-state transitions or post-commit event ownership.

## Agents, tools, and execution

| Module | Owns | Important submodules and contracts |
| --- | --- | --- |
| `agents` | Agent drafts, immutable published revisions, provider/tool relations, swarms, and background-Agent attachments | revision services, kind invariants, runner hooks, list projections, swarm schemas |
| `agent_runs` | durable run lifecycle, steps, waits, results, cancellation, metering, and per-org execution budgets | Absurd binding, executor router, workflow, budget reservations, transcript items |
| `parallel_agents` | persisted definitions and service entrypoints for attached parallel work | durable execution is composed in `pipelines/parallel_agents/` |
| `tools` | platform tool definitions/revisions, system-tool catalog, MCP/local/curated kinds, execution policy, and schema contracts | executor schemas, register/discovery services, system-tool implementations |
| `mcp_servers` | organization-owned MCP server definitions and immutable revisions | registration, discovery, withdrawal, and revision revocation |
| `templates` | revisioned authored templates and rendering contracts | Agent-instruction and campaign-message templates; preview/publish/render/revoke |
| `interfaces` | validated structured interface schemas exposed by Agents | schema validation and interface service boundary |

Agent HTTP handlers declare their result models, including tool lists, swarm
membership and background attachments. Swarm and membership removal return a
typed `detail` acknowledgement; tool/attachment removals retain empty 204 bodies.
These transport contracts do not change draft-version checks or revision policy.

System/local tool registration preserves callable signatures and returns the
canonical `PlatformTool` model; serialization belongs at persistence or vendor
boundaries. Catalog entries are validated `ToolInDb` values, not unchecked model
construction. Exact dispatch owns input validation and the shared conversation/
swarm result contract: text or recursively validated JSON objects/arrays. Scalar
JSON results retain their text encoding. Invalid nested values are rejected
without exposing their contents; cancellation propagates to the callable.

Tool drafts accept partial JSON executor settings; publication applies the
owning executor's contract (including MCP effect and exact tool identity).
`ToolRevisionPayload` is an immutable storage snapshot with DB-accurate
nullability and authored JSON Schema extensions. Runtime reads replace stored
system/local schemas with their registered schemas. JSON schema fields,
arguments, result metadata/extensions, and draft settings accept recursive JSON
values, not arbitrary Python objects or non-finite numbers. ORM string columns
remain strings until domain schemas resolve their enum values. Tool deletion
retains its `success` acknowledgement and non-destructive withdrawal behavior.

## Provider configuration plane

| Module | Owns | Important submodules and contracts |
| --- | --- | --- |
| `provider_configs` | encrypted organization-owned config aggregate, revisions, readiness, masking, and reference-safe deletion | capability registry, crypto, repository, domain, error mapping |
| `provider_onboarding` | deterministic schema used to render provider forms | capability/provider/field definitions and authenticated catalog route |
| `llm_configs` | LLM-specific schema, resolver, service, verification, and wiring | vendors/models come from the neutral LLM catalog |
| `embedding_configs` | embedding config lifecycle and model/dimension catalog | Bedrock, OpenAI, and Voyage |
| `reranking_configs` | reranker config lifecycle and model catalog | Bedrock, Cohere, and Voyage |
| `memory_configs` | memory-backend config lifecycle and dependencies | pgvector plus explicit embedding/LLM references |
| `voice_configs` | STT, TTS, and realtime provider config lifecycle and catalogs | shared voice provider field catalog and three route collections |
| `webrtc_configs` | ICE/TURN provider config lifecycle | Metered and Turnix |
| `email_configs` | outbound email config lifecycle | SMTP and SendGrid |
| `storage_configs` | S3/filesystem config lifecycle and capability projection | trusted filesystem root remains deployment-owned |
| `sandbox_configs` | sandbox execution-provider config lifecycle | Docker V1 contract |
| `telephony` | carrier config plus phone-number and call domain state | provider verification, webhook security, call lifecycle, DTMF, number records |

## Knowledge and memory

| Module | Owns | Important submodules and contracts |
| --- | --- | --- |
| `knowledgebase` | knowledgebases, grants, chunks, ingestion jobs, corpus imports, reindex state, and deterministic extraction | `extraction/`, ingestion/reindex services, widget file-upload route, ephemeral events |
| `memory` | agent/contact/conversation facts, relationships, conflicts, indexes, formation/reconciliation/reindex jobs and effects | scope authority, integrity, operator projection, reconciliation and reindex services |

Knowledge chunks always include knowledgebase identity. Memory ownership is a
typed level plus owner ID. Both pin embedding configuration ID and revision.

Knowledgebase routes declare their actual Python return types separately from
the existing HTTP response schemas. ORM-returning routes remain filtered through
the explicit public schema; ingestion submission and corpus creation return
validated response models after their job is committed. Typing does not move
vendor work into these transactions or change post-commit durable dispatch.

## Automation, lifecycle, and product support

| Module | Owns | Important submodules and contracts |
| --- | --- | --- |
| `scheduler` | schedules, immutable revisions, occurrences, recurrence calculation, action registry, and recovery of stranded claims | PostgreSQL scheduling store and durable Agent-run dispatch pipeline |
| `sandbox` | Agent grants, sessions, workspace checkpoints, and long-running objectives | access checks and session lifecycle; provider execution stays in sockets/pipelines |
| `deletions` | deletion request/job status for call and contact erasure | ownership-aware erasure orchestration lives in pipelines |
| `analytics` | read-only created-count and conversation-per-Agent projections | no write-side aggregate ownership |
| `mappers` | explicit enum translation shared at boundaries | does not own domain state |

## Voice state and artifacts

| Module | Owns | Important submodules and contracts |
| --- | --- | --- |
| `voice` | platform voice configs and recording upload/read models | compatibility projection, section updates, recording access and lifecycle |
| `voice_transcripts` | voice sessions and canonical segments | lifecycle transitions, transcript repository/service, conversation aggregate routes |

`voice_configs` selects vendor connections. `voice` defines platform behavior.
`voice_transcripts` records what happened. Keeping these separate prevents a
vendor's native features from becoming platform policy.

Provider readiness uses separate STT, TTS and WebRTC event contracts. Each owns
its state enum and bounded observation fields; arbitrary dictionaries and live
provider resources cannot enter these events. The WebSocket presentation keeps
Eylo's `state` separate from the peer's `provider_state`, and realtime readiness
retains its `runtime_mode`. Listener delivery remains best-effort and cancellation
propagates. These ephemeral observations do not replace the call interaction
state machine or create persisted transcript messages.

Transcript tool projection consumes the canonical conversation content models
through `TranscriptToolFields`, not dynamic attribute/dictionary lookups.
Tool inputs and result envelopes are finite JSON; their raw values are excluded
from diagnostic representations. This preserves the existing first-result
projection and flat stored fields, including the null envelope for an empty
tool-result message. Session retry checks compare explicit ORM fields against
the requested identity and pinned config; a completed session cannot reopen.

New session metadata writes use `VoiceSessionMetadata`: explicit policy
predicates, canonical-storage intent and recording-failure observations, plus
finite JSON extensions. Serialization preserves omitted fields and explicit
nulls. Historical reads remain finite JSON; `TranscriptStoragePolicy` and
`CanonicalStorageRequest` validate only the controls each operation owns.
This lets post-call processing record the existing missing/invalid-decision
failure instead of failing while loading unrelated session fields. Recording
error annotations merge without revalidating unrelated historical controls.

Segment provenance uses `VoiceSegmentMetadata` for message kind, source sequence,
redaction version and voice-policy source. The shared voice-policy source enum
lives in neutral contracts; the transcript domain does not import pipelines.
Redaction states retain their existing `none`, `clean` and `redacted` wire values
through `VoiceRedactionState`. Metrics, tool payloads, vendor context and word
objects accept finite JSON, not arbitrary Python values. Word objects remain
extensible historical data; this contract does not introduce word-timing capture.
Repository writes revalidate copied or mutated payloads before persistence.

## Curated integrations

`integrations_v2` owns installations, connections, OAuth state, installed-tool
policy, Agent grants, and member/widget API contracts. Executable vendor
definitions and callables live in `pipelines/integrations_v2/`, not this domain
module.

## Product package

The `campaigns` package under `server/eylo/products/` composes contacts, Agents,
channels, scheduling/durable attempts, and outcome analytics. Its submodules
own draft and revision rules, audience preparation, per-contact attempts,
channel adapters, and operator APIs. A campaign never owns or deletes its
contacts or Agent.
