# Agent execution

An Agent is a revisioned definition. An Agent run is one durable attempt to
achieve a goal under explicit provider, tool, budget, and principal authority.

## Publication bindings

Shared exact references, definition headers and published-revision availability
are frozen Pydantic values in `common/revisions.py`. Owning services decode ORM
lifecycle strings into enums before construction. Transitions construct validated
values; they do not mutate a snapshot or use an unchecked model copy. Withdrawal
blocks new selection while emergency revocation also blocks pinned execution.
The header's `draft_dirty` remains an intrinsic changed-since-publication
predicate, separate from the lifecycle enum.

Agent and swarm API projections use the same lifecycle/availability enums rather
than unconstrained strings. Draft patches retain field presence: omitted values
do not overwrite stored settings, while explicitly null provider/template
bindings remove those references. The service copies the validated mutable patch
before resolving binding revisions; the repository assigns typed ORM attributes
explicitly rather than unpacking a generic dictionary. Existing scalar-null and
LLM-override replacement semantics remain unchanged. The compatibility `prompt`
field holds only finite JSON on the draft; executable instructions come from the
pinned instruction template, not that field.

Publication resolves each explicitly selected provider in the Agent's organization
and keeps its config ID and positive revision together in a typed binding. Missing
optional providers stay absent; publication does not select a fallback. The stable
Agent header and immutable revision receive the same resolved references.

Voice configuration remains a typed object until its final JSON storage projection.
Only provider selections with resolved revisions become executable voice references.
For example, a realtime configuration may retain inactive STT/TTS selections for
editing without granting runtime access to those providers.

Tool grants retain their existing two forms: a platform/MCP tool ID plus exact
revision, or a curated tool ID whose definition lives in code. Publication and
revision readback reject incomplete or mixed references rather than passing nullable
IDs into runtime assembly. These checks supplement the DB's exactly-one constraints;
they do not replace organization-scoped grant queries or runtime availability checks.

Runtime assembly projects the immutable Agent revision into its typed execution
schema, including validated LLM overrides. A template reference must contain both
its ID and a positive revision, or neither for a code-owned background Agent.
Incomplete references are refused before rendering; runtime never substitutes the
template's latest revision or the Agent's current draft.

The template compiler, provenance segments and rendered result also use frozen
Pydantic values. Compiled variable declarations remain an independently owned,
read-only mapping. Native restoration revalidates the interpolation program;
rendered text must agree with its instruction/runtime-data segments. Services
bind a render to either a draft version or an exact template reference through
validated construction. Campaign rendering uses this same compiler to select
declared contact variables and rejects incomplete template ID/revision pairs.
The renderer still treats Agent substitutions as untrusted runtime data and
escapes them; campaign messages retain plain interpolation.

Executable Agent, swarm member/topology and swarm-worker carriers use frozen
Pydantic models. Their validators enforce exact Agent identity/revision and
nonempty, unique, same-organization topology membership. Runtime resolvers translate
model validation failures into Agent/swarm domain errors without including stored
payloads. The worker rebuilds and validates its tool-filtered projection rather than
using an unchecked copy. Published voice settings use `VoiceConfigSnapshot`,
which reuses the owning `VoiceConfig` schema and validates stored JSON when an
exact Agent revision is resolved. Browser and telephony consumers obtain a
validated, independent configuration through `for_call()`; changes to one call's
nested plans cannot alter another call's settings. The snapshot is top-level
frozen, not recursively immutable. Provider IDs/revisions remain pinned, and the
primary Agent's voice configuration still applies throughout swarm handoffs.

## Conversational run

1. A contact sends a message through the widget/WebSocket path.
2. The conversation module persists the canonical message and request state.
3. The Agent-run module creates a queued run with the conversation/message
   origin and pinned Agent revision.
4. Post-commit work binds the run to Absurd.
5. The worker reloads the run, Agent revision, conversation context, provider
   mappings, tools, knowledge grants, memory config, and execution budget.
6. The provider-neutral framework asks the pipeline-supplied model adapter for
   the next turn.
7. Tool calls return through platform, MCP, or curated execution boundaries.
8. The pipeline persists transcript items, usage, request-state transitions,
   and the canonical assistant message.
9. Ephemeral events project live changes to connected widget sessions.
10. The run reaches a terminal outcome or yields on durable input/approval.

Conversation metadata remains an integrator-owned, extensible JSON object.
The create/read/update schemas, ORM annotation and aggregate API share its finite
JSON contract; they do not impose a closed set of custom keys. Conversation start
still sanitizes context before storage. Initial text/image messages use the
canonical message-content models and independent copies of nested image values;
the caller cannot mutate already-prepared persistence input. Starting without an
initial message is valid, but invoking the message-write path without content
fails explicitly before persistence.

Widget campaign context has a typed producer. Replay validates only its exact
textual campaign, campaign-contact and attempt IDs; a display name or unrelated
integrator field cannot change replay identity. Contact erasure detaches only
matching campaign references. Invalid nonempty context or collection-valued
reference IDs fail before detachment rather than being silently skipped.

WebSocket text ingress validates finite JSON through `WsRequestEvent`; each
action handler then validates its own fields. Binary microphone frames use the
transport-owned `WsBinaryAudioRequest`, not a dictionary inside the JSON envelope.
Raw bytes are excluded from its representation and snapshots. Both paths retain
the contact gate in event dispatch. Text rate limiting, audio silence/readiness
checks and realtime/decomposed routing remain separate concerns. Audio setup
passes the validated conversation UUID to the participant service.

Outbound envelopes use `WsResponse` with finite JSON object/collection data and
an integer status. Its projection boundary explicitly converts UUIDs, datetimes
and enum values from already-selected public fields; it does not serialize
arbitrary ORM/SDK/model objects or trust a `.value` attribute. The transport
revalidates copied/mutated responses before sending, retaining aliases and the
existing ISO timestamp representation. An empty object is emitted as `{}`.
Binary outbound audio still follows the session's carrier/browser framing path.

Conversation handlers decode small typed routing projections from successful
creation responses; they do not regenerate message HTML to recover an owner ID.
Contact read receipts are constructed after commit and retain the existing
snake-case fields and ISO timestamp format. Malformed references cannot trigger
session association or read broadcasts. Controller contact/conversation checks
remain the authorization boundary; a response reference does not grant access.

Redis contact delivery uses the same `ContactDelivery` contract on publication
and consumption. Its payload is finite JSON; conversation-scoped events require
a conversation ID before publication. Selected public fields retain the existing
Redis UUID/date/enum encoding. Unscoped contact events may carry a null conversation
ID in this internal envelope; the widget's public event shape is unchanged.

Curated connection notifications use integration-owned Pydantic projections
before Redis publication. Connection status and expiry notices remain contact-wide;
a tool's authorization request retains its conversation identity. Auth modes use
the integration domain enum, while vendor IDs remain registry identifiers. The
existing snake-case fields, nullable values and widget actions are unchanged.
These notifications describe connection state; they do not grant tool access.

WebSocket initialization projects one user-session start outcome into the existing
`created` and `reconnected` wire predicates. The positive connection sequence and
session UUID come from the authoritative session result. The connection controller
owns setup and teardown; process startup/shutdown only starts and stops the shared
manager. There is no separate session-context wrapper or implicit STT startup.

Conversation, message and participant presentation listeners finish their DB reads
before publishing to Redis. Erased contact placeholders remain in participant
history but are excluded from contact selection; they are not deliverable UUIDs.
Agent participant creation validates the complete ID/revision pair even when
optional fields are omitted, rather than relying on a field validator that only
runs when the revision is supplied.

LLM context uses an explicit TOON value projection. UUIDs become strings and enums
become their values before encoding; dates and existing finite JSON formatting
are preserved. Unsupported objects, nonfinite numbers and cyclic collections are
refused instead of silently becoming `null`. Pydantic models are recognized by
their actual base class, not an arbitrary `model_dump` attribute or a vendor SDK
import. This is a presentation contract, not a replacement for context authority.

Conversation and decomposed-voice lifecycle callbacks receive the framework's
`RunContext`; the realtime hook path retains its platform `HookContext`. That
mutable Pydantic carrier preserves live conversation/message identity and keeps
their content out of snapshots. The shared lifecycle emitter constructs explicit
event fields from a typed request/run correlation value. One request retains its
run ID, timestamp and increasing sequence; a new request resets the sequence.
Only contact identities and correlation metadata reach the widget event, not the
conversation body. These types do not change hook failure isolation or resource
cleanup ownership.

Conversation runner entrypoints return `RunResult`. Model, tool-result and terminal
metadata producers return the platform's validated `MessageMeta` before message
creation. Producer-owned provenance is serialized once into that persistence
envelope; pause filtering and resume selection consume the envelope directly.
The existing stored metadata, message identities and lifecycle transitions remain
unchanged.

Cross-process conversation draining uses `ConversationRuntimeStatusService` with
the concrete async Redis client. The conversation module owns the Redis codec:
flat bytes/text hashes become typed status values, and Lua ownership/drain replies
must match their declared integer codes and claim tuple shape. Invalid replies
raise validation errors rather than being interpreted by truthiness. The existing
Lua scripts, keys, lease/heartbeat durations, wake handling and owner-token checks
remain authoritative; Redis does not replace durable DB request/run state.

Curated execution keeps its result content and metadata in typed platform
projections until `PlatformToolExecutor` serializes them for the framework.
Success, authorization requests and errors have explicit content kinds; the
validator refuses contradictory error flags, codes or metadata. Only vendor
result data remains dynamic finite JSON. Connection and approval actions use an
internal enum while preserving the existing wire predicates consumed by clients.
Result validation never retries the handler: an invalid result can follow an
already accepted external mutation.

Message, scheduled and objective filing results use frozen Pydantic values with
an exact run ID and an intrinsic created-versus-existing predicate. The message
filing result retains the live validated message for its caller, but excludes
its body from generic snapshots. Filing still owns its existing transaction,
idempotency lock and budget reservation; changing the value contracts does not
introduce another execution authority.

Execution context is serialized by its owning product: conversation routing,
parallel task identity, scheduled occurrence, or objective bounds. The generic
AgentRun module validates only a finite JSON object; it does not import or
interpret those product schemas. Workers restore the owning Pydantic model
before using context fields, then perform the existing organization, origin and
published-revision checks against canonical rows. Context is not a substitute
for current authority. Timestamp serializers preserve the original ISO offsets
so this validation does not change persisted idempotency digests. Malformed
objective bounds are refused before opening the filing transaction.

Scheduled, objective and parallel-task conclusions use typed result projections
before the generic terminal write. The AgentRun module copies and validates the
result as finite JSON before acquiring the terminal row lock. An objective that
exhausts its bounds before a framework turn exists stores the existing minimal
result, without inventing a framework ID or usage. Parallel results bind their
newly persisted task-result message through validated reconstruction.

Parallel workers return immutable `WorkerResult` values. Their persisted
`TASK_RESULT` content uses `TaskResultMetadata` for the model name and nonnegative
iteration count; absent metadata remains valid for historical results. The
orchestrator adds the worker-kind enum to the message's provenance, then projects
it into the generic message metadata envelope. LLM history reads the same result
content model. Result creation, origin completion and AgentRun completion remain
one transaction; no second completion or retry authority is introduced.

Ordinary connection cleanup and conversation expiry return typed completion or
`MaintenanceFailure` values, not arbitrary dictionaries. Their historical JSON
fields are unchanged. The periodic runner awaits these actions but does not
interpret their result as durable job state. Existing task-local error handling
and cancellation propagation remain unchanged; these contracts do not add retries.

Scheduled/objective resume checkpoints contain a typed recorded/error receipt,
not tool output. Both fresh execution and checkpoint replay still reload the
canonical tool result from the transcript. A malformed receipt or missing
transcript result refuses continuation; cancellation before a completed write
does not produce a receipt. These contracts do not add another retry authority.

Direct objectives pass the resolved framework `AgentSpec`, typed execution claim
and tool tuple into initial input and resume construction. The workflow context
retains the same native task owner; neither checkpoint replay nor dependency
wiring reconstructs provider authority from an arbitrary dictionary.

Conversation transcript writes belong to the typed framework-runner callbacks;
there is no parallel legacy `MessageStore` implementation. Terminal fallback
text lives with conversation orchestration and is shared with realtime widget
failure handling. Realtime tool arguments retain their finite JSON contract
from vendor events through validation and dispatch; cancellation still propagates
to the owner of the live call.

Sandbox actions and tool results have separate typed contracts. Durable receipts
identify the exact private workspace checkpoint by revision and digest; replay
requires both to match before restoring the canonical tool result. Raw command
and file content are excluded from generic execution snapshots. Malformed adapter
results follow the failure cleanup path, while cancellation releases compute and
propagates. Output limits reject the complete result rather than truncating it.

Workspace transfers carry typed pinned settings and an explicitly private archive.
The storage boundary preserves the existing flat policy JSON; session limits and
checkpoint comparisons use named fields internally. A current grant ceiling is
resolved at acquisition rather than trusted from an older checkpoint. Invalid
stored export policy follows compute cleanup without attempting an export.
The sandbox module owns the policy shared by runtime execution and session reads.
Operator responses validate that policy, then serialize its existing flat shape
through a named response model so generated clients retain typed fields. Session
responses omit the vendor container identity. Non-durable sandbox tool entrypoints
return typed refusal envelopes; they do not execute commands outside AgentRun.
Sandbox config wiring accepts an explicit DB session or the caller's transaction
and the module-owned reference-check interface. The pipeline resolves current or
pinned config material before creating an adapter; console config projections
consume `ProviderConfig` and mask secrets before serialization.
Step intents and execution evidence are action-specific typed values. Their JSON
projections retain hashes, byte counts and outcome facts without command/file
bodies; optional facts remain absent unless the action actually establishes them.

Agent-run persistence and public responses retain these projections as JSON-safe
objects/lists, not arbitrary Python values. Product-specific models stay with
their product; the Agent-run module does not import sandbox action schemas.
Public step evidence, run results and input schemas reject non-JSON/non-finite
values. Input responses never expose the private continuation snapshot.

A tool may finish a turn with an already-persisted widget instead of new text.
Terminal persistence loads that exact message through the message service and
checks its conversation/request ownership and content kind before associating
it with the AgentRun. It does not search the older model-input history: that
snapshot deliberately excludes artifacts created during tool execution.

The interfaces module owns typed, recursive widget catalog descriptors. Content
controls reuse the shared widget enums; formatters read descriptor attributes
rather than traversing arbitrary dictionaries. Catalog hints such as `optional`
and `any` describe props to the model; they are not injected into the vendor's
input schema. The final tool definition uses `PlatformToolInputSchema`, preserving
the flat component list and JSON-encoded props wire format. Conversation
enrichment takes a deep copy of the cached schema for each tool, so one Agent's
tool processing cannot change another Agent's catalog. Runtime widget payload
and tree validation still use the separate shared component contracts.

## Conversation compaction

The summarizer groups validated messages by request and freezes each completed
group before selecting an older range. It retains complete recent groups and
persists the exact last selected message as the summary cursor. Selection values
preserve live message identity but exclude message bodies from generic snapshots.
Token-count components are nonnegative typed estimates with one derived total;
they are not provider-reported usage. Provider/model estimation and the existing
token/group trigger thresholds remain separate from these value contracts.

## Tool availability

MCP discovery crosses explicit adapter and module contracts. The pipeline maps
the socket's `MCPTool` to the module's `MCPDiscoveredTool`; the service retains
schema budgets, effect validation, publication and tenant policy. Validated
definitions carry `PlatformTool` and `MCPToolExecutorConfig` objects until the
explicit persistence boundary. Dynamic JSON Schema and arguments remain JSON
values, not arbitrary Python objects.

MCP management responses are explicit allowlists for server metadata, discovered
tool facts and revision revocation status. Authentication is a named mode; only
header names are exposed, never encrypted or resolved values. Lifecycle, effect
and execution mode use their owning domain enums. Public UUID fields normalize
the platform's UUID library representation before Pydantic validation; responses
retain the existing UUID text and timestamp offset formats.

Resolved MCP settings and discovery targets use frozen Pydantic models. Discovery
holds no ORM row across vendor I/O: a short transaction snapshots source identity,
header state, published-revision availability and the last discovery timestamp.
The transaction closes before the socket runs. A second transaction locks and
revalidates the source before atomically publishing tools and projecting detached
response models. Concurrent edits, withdrawal, revocation or another completed
discovery invalidate the snapshot and return `409`; retry requires a fresh
discovery. Vendor failure, cancellation and failed publication preserve the
previous catalog. Explicit rediscovery started after withdrawal still retains
the existing ability to publish a new revision.

Validated egress objects retain identity; decrypted headers remain excluded from
generic snapshots. Remote result text is available through explicit result/content
access, not generic snapshots. Adapter protocol failures and pipeline execution
failures have separate owning enums with stable wire values. These contracts
do not add retry authority. The discovery pipeline owns both transactions and
refuses invocation inside a caller-owned transaction.

The socket validates native request/reply envelopes separately from published
tool definitions. It retains MCP 2025-06-18: typed initialization, tool listing,
pagination and text-only tool results. Replies must match the request ID and
contain exactly one result or error; initialization requires the negotiated
version, tools capability and server identity. Unsupported content remains a
refusal. These checks follow the pinned [message contract](https://modelcontextprotocol.io/specification/2025-06-18/basic)
and [lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle),
not a protocol-version upgrade.

Code-owned declaration metadata uses frozen `ToolFunctionMetadata` values:
an optional input-schema class, a feature flag, and catalog visibility. Producers
attach it through `set_tool_metadata`; registration reads it through
`get_tool_metadata`. These helpers retain the original Python function, its
signature and its LLM-facing docstring. The live schema class is excluded from
JSON snapshots and public metadata schemas. Tools without metadata still use
signature inference. These declarations are not grants or provider permissions.

Tool assignment and tool availability are different facts.

Requirements, resolved facts and missing requirements are strict, frozen Pydantic
values with capability and runtime enums. Capability status aggregates independent
configured, verified and ready predicates; it does not confer an Agent binding.
Refreshing an execution replaces its facts rather than mutating the snapshot.

- Assignment: the published Agent revision contains the tool relation.
- Availability: current org provider readiness, Agent capability mapping, and
  runtime facts satisfy the tool's requirements.

For example, `place_call` needs ready telephony, an Agent telephony mapping,
and durable execution. `dial_keypad` needs an active call. `end_call` needs an
active voice session and works for widget/realtime voice as well as telephony.

Call-tool outcomes remain typed until the framework's JSON projection. `place_call`
retains the committed attempt state, call/config UUIDs and config revision; an
accepted result must match that successful attempt. Unknown delivery remains a
refusal, not permission to retry. `end_call` retains the exact voice runtime only
on accepted termination requests. Both use enum-backed failure codes and derive
the error predicate from their content, so an acknowledgement cannot be labelled
as an error independently. Existing transcript JSON, including an unknown/null
provider call ID and omitted metadata on early refusals, is preserved. These
contracts neither grant tool access nor change transport cleanup ownership.

## Scheduling from an agent

The action registry distinguishes operator-only actions from agent-allowed actions
with `AgentSchedulingAccess`. Registry metadata and action-context values are
frozen Pydantic models; handler references are excluded from snapshots and public
schema generation. Action names remain registry-owned strings, not a closed enum
shared between unrelated modules.

Schedule tools use the executing agent's organization and identity. Listing and
cancellation also work for non-conversation agent runs. An action requiring a
conversation ID can obtain it only from a real `ConversationContext`; the scope
ID of a durable/background run is not a conversation. Submitted scope IDs never
override context-owned values. Conversation reminders additionally require the
contact participant to be present.

Reminder responses are built from frozen `ReminderRejected` or
`ReminderScheduled` values. `ReminderAction` names the existing recovery and
completion hints; serialization preserves the tool's `success`, `action_required`
and `_meta` JSON fields. Those hints are model-facing, not a second runtime state
machine. The scheduled payload uses the conversation-owned `ReengagePayload`;
organization, conversation and published Agent revision still come from context.
Time utilities accept the dispatcher context explicitly without inspecting it.
Their model-visible input schemas and descriptions are unchanged.

The due-job path persists an occurrence and creates a scheduled AgentRun from its
action and payload. The model-visible goal includes the immutable scheduled
occurrence and any coalesced misfire count. Relative windows use that occurrence
as their cutoff rather than the worker's current time, so delayed or recovered
runs retain the same meaning. The path does not directly invoke the registry's
older action handler dispatcher. Registration and tool-input checks alone do not
prove that the agent completed the scheduled action or delivered a later message.

## Durable waits

When the Agent needs information or approval, the run persists an input request
and enters a waiting state. Absurd releases execution capacity. A later user
response commits first, then wakes the named wait. The run can wait
indefinitely; a missing answer is not itself a failure.

## Budgets

Per-organization limits cover concurrency, tokens, active time, and cost.
Budget authority is checked before an external side effect or persisted output.
Exhaustion rejects the operation; Eylo does not truncate or publish partial
results as success.

Provider output-token limits are separate from organization budgets. Adapters
normalize their native finish reasons into `LLMStopReason`; the pipeline translates
that value into the standalone framework's `ModelStopReason`. A `max_tokens`
response is accounted for, then rejected before its text becomes a final answer
or its tool calls execute. The framework returns a failed result with
`RunFailureCode.MODEL_OUTPUT_LIMIT`, and conversation persistence records the
failed request with a readable response-limit notice. Earlier completed tool
effects are not rolled back. Streaming text already delivered cannot be recalled;
it does not establish successful completion.

One-shot background prompts and swarm workers apply the same check after metering.
The parallel durable executor records `parallel_task_model_output_limit` as a
terminal failure rather than retrying the same output budget automatically.
Background prompt and result carriers are frozen Pydantic values; prompt text is
excluded from diagnostic representations and generic snapshots.

## Background Agents and swarms

Background Agents enter the same durable run model from an objective or
attachment rather than a live contact turn. Swarm handoff changes which Agent
reasons next, but the conversation, user session, primary voice configuration,
and transport remain stable.

Prompt-only background Agents advertise tools from their exact task context,
after provider and durable-runtime requirements are resolved. This is the same
named, gated tool projection used by dispatch; raw stored tool names are not a
second callable interface. Dispatch rechecks mutable availability before each
call. Background runs retain their own actor and never advertise handoffs.

Swarm editing and publication require an organization-owned, non-deleted header;
optional lookup is used only where absence is a normal result. Draft membership
changes advance the optimistic draft version. Publication pins each member's exact
published Agent revision, so later draft edits do not rewrite an existing topology.
Withdrawal blocks new topology selection; emergency revocation also blocks exact
revision readback. These rules are enforced in the swarm services and existing DB
constraints, not inferred from whether a caller received an optional row.
