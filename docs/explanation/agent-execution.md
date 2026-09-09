# Agent execution

An Agent is a revisioned definition. An Agent run is one durable attempt to
achieve a goal under explicit provider, tool, budget, and principal authority.

## Publication bindings

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

A tool may finish a turn with an already-persisted widget instead of new text.
Terminal persistence loads that exact message through the message service and
checks its conversation/request ownership and content kind before associating
it with the AgentRun. It does not search the older model-input history: that
snapshot deliberately excludes artifacts created during tool execution.

## Tool availability

Tool assignment and tool availability are different facts.

- Assignment: the published Agent revision contains the tool relation.
- Availability: current org provider readiness, Agent capability mapping, and
  runtime facts satisfy the tool's requirements.

For example, `place_call` needs ready telephony, an Agent telephony mapping,
and durable execution. `dial_keypad` needs an active call. `end_call` needs an
active voice session and works for widget/realtime voice as well as telephony.

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
