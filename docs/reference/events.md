# Events and delivery contracts

Eylo has two event mechanisms with different guarantees.

## Ephemeral local events

Pyventus listeners are registered from one explicit manifest in API and worker
processes.

Each immutable Pydantic registration binds an event class to a handler accepting
that class. A checked dispatch method is the registry's common interface: it
rejects a different model before invoking the handler, even if its class name
collides. Duplicate checks retain the original callable identity/equality,
including bound methods. Process-local emitter initialization is lazy and resets
on PID changes; registration health validates exact subscriber membership.

- Delivery: concurrent, unordered, best effort, in process.
- Storage: none.
- Use: live UI deltas, transport/call state broadcasts, and module
  observability.
- Failure: contained by the emitter/listener path; no retry or replay contract.

The manifest currently covers:

- Agent inference, processing, tool execution, and response completion;
- message, conversation, and participant changes;
- WebRTC, STT, and TTS state;
- call lifecycle and integration-connection state;
- knowledgebase lifecycle, grant, ingestion, corpus, query, and reindex facts;
- memory fact, formation, reconciliation, reindex, and recall facts.

Knowledge and memory events are intentionally ephemeral in V1.

Agent lifecycle listeners build a frozen `AgentLifecycleDelta` using the six
`AgentLifecycleStatus` values understood by the widget. The payload retains
conversation/request/run IDs, run start time, a positive sequence, terminal
predicate and optional outcome/message. An absent message ID remains explicit
null; absent optional presentation fields stay omitted. Run timestamps retain
their existing ISO offset spelling. Tool arguments and results are not included.
Redis delivery retains explicit organization, contact and conversation authority;
the receiving process validates `ContactDelivery` before selecting local sockets.
These contracts do not add ordering, durability or delivery guarantees.

The lifecycle payload's `run_id` identifies an ephemeral presentation stream,
not the persisted Agent run. Use the message's `agentRunId` (Python
`agent_run_id`) when querying the Agent-run API; use lifecycle IDs and sequence
only to correlate UI status updates.

## Durable events

Durable events are organization-visible facts and required-consumer triggers.
They are not a replacement for audit logs.

| Table | Contract |
| --- | --- |
| `event_outbox` | immutable bounded event envelope |
| `event_deliveries` | independent state per required consumer |
| `event_inbox_receipts` | exactly one receipt for a committed consumer transition |

Delivery lifecycle: `pending` → `running` → `succeeded` or `dead_letter`.
Events are filed in the source transaction. After commit, Absurd executes each
required delivery. A consumer receipt prevents the same event/consumer pair
from committing twice.

Current required consumers derive campaign call outcomes and canonical voice
segments from durable voice facts.

## User-session timeline facts

The session UI projects an allowlisted subset of durable events. The correlation
ID is the user-session ID; a conversation may appear in multiple sessions and a
session may observe multiple conversations.

Categories:

- session;
- conversation;
- message;
- Agent;
- tool;
- file;
- voice;
- telephony;
- technical transport/provider state.

Payload keys are allowlisted per event type. Display projections exclude
message text, contact identifiers, credentials, provider payloads, transcript
content, and other unbounded PII.

`SessionTimelineEvent` in `common/contracts/session_timeline.py` owns the closed
event-name vocabulary shared by producers and the timeline catalog. Persisted
and public names remain strings. The session module owns presentation and
payload privacy policy; unrecognized names or payload keys are refused before
filing. Lifecycle producers serialize typed facts without changing omitted
fields into explicit nulls.

Conversation producers retain UUIDs and message/status/channel enums in the
conversation-owned timeline schemas until serialization. Message creation and
request transitions preserve explicit nulls, including an absent request ID or
previous status; content and tool arguments are not fields on these contracts.
Browser and telephony provider facts share `ProviderTimelineFact` and the
connection observations in `ProviderTimelineState`. Browser facts omit an absent
vendor; telephony facts retain an explicitly provided null. Runtime filing remains
best-effort and does not swallow cancellation.

Agent-run producers use the run-owned fact contracts in
`modules/agent_runs/timeline.py`: input-request identity/kind, terminal outcome,
and safe startup refusal reason. The filing helper adds the pinned Agent identity;
it accepts those contracts rather than arbitrary payload keys. Questions,
responses, continuations and result content remain outside timeline facts.

Durable tool waits file `agent.run.waiting_for_tool` and `agent.run.resumed`
with the operation's `tool_owner_kind` and `tool_owner_id`. Only these two run
events allow those details. Run state, capacity changes and the timeline fact
share the caller's transaction: a filing failure rolls back the whole transition.

## Ordering

Neither mechanism promises global event ordering. Durable envelopes retain
`occurred_at`, `recorded_at`, correlation, and causation so a projection can
build an explanatory timeline without treating insertion order as business
truth.
