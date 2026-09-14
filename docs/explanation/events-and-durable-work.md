# Events and durable work

Events say that something happened. Durable work says that an effect must be
attempted until it reaches a terminal state. Eylo keeps those responsibilities
distinct even when one starts the other.

## Commit before reaction

A canonical write happens in the owning transaction. An event that describes
that write is emitted or filed only when its source can no longer roll back.
This prevents listeners and workers from observing state that never committed.

For durable events, the outbox envelope is written in the source transaction.
Post-commit binding creates/wakes Absurd work for each required delivery.

## Ephemeral events

Local events are useful when every consumer is best-effort: broadcast a new
message, update connection state, or observe knowledge/memory lifecycle. They
execute concurrently without ordering or replay.

An ephemeral listener must not be the only owner of a required durable effect.

Message-created notifications contain only typed conversation/message IDs and
the message kind. They never copy message bodies into the bounded event envelope.
The presentation listener reloads the exact live message in that conversation
after commit, resolves recipients, and releases its read transaction before
publishing the full API message. Deleted or mismatched records are skipped. Tool
and system messages remain available in the operator transcript, not widget
message broadcasts. The notification remains best-effort, with no replay guarantee.

## Durable events

Durable events are user-visible organization facts that may also require
consumers. Each consumer has independent state and an exact inbox receipt.
Dead-letter state is visible to operators.

The event record is not the whole audit system: it intentionally carries a
bounded, privacy-safe payload rather than copying arbitrary domain or provider
data.

Consumer identity, filing results, delivery attempts and health snapshots use
strict Pydantic contracts. Registry keys stay hashable; manifest and health order
are explicit rather than relying on dataclass ordering. Delivery task parameters
share one UUID contract between post-commit binding and worker parsing. Absurd
receives the same JSON keys and returns the same state/attempt-count receipt.

The attempt state determines whether to consume. The delivery failure enum owns
the existing retry classification: missing or rejecting consumers are permanent;
execution failure remains retryable until its attempt budget is exhausted.
There is no independently supplied permanent/retry flag. Attempt snapshots omit
the event envelope; consumers still receive the explicit, validated fact. Filing,
delivery and inbox writes retain their existing transaction boundaries.

## Durable jobs

Ingestion, formation, reindexing, recording upload, deletion, campaign attempts,
and Agent runs own product job rows. Queue messages are not canonical status.
Absurd claims the exact persisted work, applies retries/cancellation/waits, and
updates product state through the owning service.

This makes DB rows explainable even if a queue delivery is duplicated or a
worker restarts.

The shared product-job service preserves each caller's concrete ORM row type.
Its structural row protocol defines required fields without registering tables
or importing product modules. Completion accepts a synchronous, typed product
projection instead of an arbitrary field-name dictionary. The service locks the
owned row and invokes that projection only while running; terminal rows remain
unchanged. Product assignments and the lifecycle transition share the caller's
transaction. Projections must not perform external I/O or change lifecycle state.
Exceptions propagate to that transaction rather than committing partial results.

Lifecycle callers select `DurableWorkLock.NONE` or `UPDATE` when reading work.
Every lifecycle mutation still acquires the update lock. Product error
classification supplies `DurableFailureRecovery.RETRY` or `TERMINAL`; a retry
choice cannot exceed the persisted attempt budget. These are internal operation
contracts, not new database states or vendor recovery policies. Knowledge and
memory provider errors retain their own recovery vocabulary and are translated
by their product pipelines. Failure summaries and unbound scan batches retain
their existing bounds as named constants.

Producer binding accepts the product's typed task identity, not a caller-selected
JSON key. Knowledge, memory, campaign and recording producers encode the same
contracts their workers decode. The organization and work-row IDs come from that
one object; validation precedes the read transaction. Only IDs cross the queue,
including when a recording receipt is used as an identity. Existing workflow
names, idempotency keys, retries and post-commit binding remain unchanged.

Schedules carry finite JSON task inputs from request validation through immutable
definition revisions and occurrence snapshots. These inputs remain extensible:
the scheduler does not interpret vendor payloads or execute a registered action
handler instead of the Agent. It files the exact Agent revision and occurrence;
the Agent decides how to achieve the task using its allowed capabilities.
Payload validation precedes persistence, retains the encoded-byte bound, and
does not stringify arbitrary Python objects. Run readback uses the AgentRun's
canonical result and lifecycle rather than a second scheduler execution state.

The action catalog's callable contract is separate from scheduled-Agent execution.
Its registered conversation and telephony handlers validate their own payload
fields with Pydantic before starting a transaction or a provider effect. Unrelated
metadata remains extensible; call provenance is retained, but exact Agent and run
authority comes from the action context. Handler callables never enter snapshots.
Non-conversation Agent runs persist model/tool exchanges in private replay history;
an empty public step list does not mean no tools executed.

Runtime configuration and task-registration values are frozen Pydantic contracts;
connection strings and live handlers are excluded from generic snapshots. Eylo's
typed cancellation policy keeps explicit null limits when passed to Absurd:
automatic engine deadlines must not terminate an indefinite product-owned wait.
The SDK boundary translates the validated policy into its native representation.
Absurd 0.5.0 supports these nulls at runtime although its Python annotation omits
them; that compatibility cast is local to the policy translation.

The runtime validates finite JSON objects before enqueue and event publication,
and on both sides of each registered workflow handler. This detaches wire values
without coercing arbitrary objects or non-finite numbers. Product-specific
identity and authorization checks still belong to the workflow; a JSON object is
not proof of authority. `DurablePayloadError` omits payload values and field paths
because SDK failure diagnostics may be persisted. Cancellation, suspension and
handler failures propagate unchanged through the registration wrapper. Completion
validation does not roll back prior effects: each workflow must retain its own
durable checkpoints and idempotency guarantees.

## Ordinary tasks

Periodic scans, recovery nudges, and cleanup calls do not own product
lifecycle. Taskiq schedules each action independently, stores delivery in an
acknowledged Redis Stream, and runs it in the separate `task-worker` service.
Each action returns to PostgreSQL for canonical state and idempotency.

The 21 action names and four cadences are enums in the explicit periodic catalog.
Catalog entries are frozen Pydantic values that exclude their live callable from
snapshots. Taskiq labels explicitly serialize enum values to the existing action
names and cron strings, preserving queued-message compatibility. Action return
values are deliberately ignored; the callable contract therefore returns an
awaitable object, not an untyped payload. Retired Absurd ticks retain their
finite-JSON compatibility response and never rearm themselves.

The split is intentional: Absurd remains the durable workflow authority for
Agent runs and product jobs; Taskiq supplies scalable execution for ordinary
maintenance. Taskiq failure never makes its Redis message the product status.
