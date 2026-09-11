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

Conversation and decomposed-voice lifecycle callbacks receive the framework's
`RunContext`; the realtime hook path retains its platform `HookContext`. That
mutable Pydantic carrier preserves live conversation/message identity and keeps
their content out of snapshots. The shared lifecycle emitter constructs explicit
event fields from a typed request/run correlation value. One request retains its
run ID, timestamp and increasing sequence; a new request resets the sequence.
Only contact identities and correlation metadata reach the widget event, not the
conversation body. These types do not change hook failure isolation or resource
cleanup ownership.

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

Scheduled/objective resume checkpoints contain a typed recorded/error receipt,
not tool output. Both fresh execution and checkpoint replay still reload the
canonical tool result from the transcript. A malformed receipt or missing
transcript result refuses continuation; cancellation before a completed write
does not produce a receipt. These contracts do not add another retry authority.

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
Step intents and execution evidence are action-specific typed values. Their JSON
projections retain hashes, byte counts and outcome facts without command/file
bodies; optional facts remain absent unless the action actually establishes them.

A tool may finish a turn with an already-persisted widget instead of new text.
Terminal persistence loads that exact message through the message service and
checks its conversation/request ownership and content kind before associating
it with the AgentRun. It does not search the older model-input history: that
snapshot deliberately excludes artifacts created during tool execution.

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

Resolved MCP settings and discovery targets use frozen Pydantic models. Existing
validated egress objects and live ORM references retain identity rather than
being copied into reconstructed resources. Decrypted headers and ORM rows are
excluded from generic snapshots. Remote result text is available through explicit
result/content access, not generic snapshots. Adapter protocol failures and
pipeline execution failures have separate owning enums with stable wire values.
These contracts do not add retry authority or alter transaction/session ownership.

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

The due-job path persists an occurrence and creates a scheduled AgentRun from its
action and payload. It does not directly invoke the registry's older action
handler dispatcher. Registration and tool-input checks alone do not prove that
the agent completed the scheduled action or delivered a later message.

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
