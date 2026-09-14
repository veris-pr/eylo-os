# Operate durable work

PostgreSQL is the durable source of truth. Absurd owns durable workflow claims,
retries, waits, and cancellation. Taskiq separately executes ordinary periodic
work from an acknowledged Redis Stream.

## Confirm the worker is running

```bash
docker compose \
  -f infra/docker/eylo/docker-compose.yml \
  -f infra/docker/eylo/docker-compose.dev.yml \
  ps
docker compose \
  -f infra/docker/eylo/docker-compose.yml \
  -f infra/docker/eylo/docker-compose.dev.yml \
  logs --since=10m worker task-worker task-scheduler
```

Startup logs should show the Agent-run workflow and queue registration. A
missing Absurd queue relation is a migration/runtime mismatch, not a transient
Agent failure. Taskiq startup should report the catalogued ordinary-action
count on `eylo-ordinary-tasks-v1`.

The process starts four independently polling worker lanes. Each lane owns its
own Absurd client and DB connection and claims one task at a time. A slow
provider operation therefore occupies one configured lane while the remaining
lanes continue claiming work; adding worker processes increases total bounded
capacity.

Eylo's Absurd 0.5.0 runtime wraps every handler in claim renewal. The
120-second claim is renewed at most every 30 seconds, including time between
explicit workflow steps. An `already failed` error followed by a stale
`complete_run` or `extend_claim` means claim renewal stopped long enough for
Absurd to mark that attempt `$ClaimTimeout`; inspect DB connectivity and
event-loop stalls before increasing the timeout.

## Confirm ordinary work is running

`task-scheduler` is a singleton. It sends one message per due action and never
executes the action. `task-worker` runs at most four async actions in its one
child process. Scale `task-worker` replicas for throughput; do not scale
`task-scheduler`, because each scheduler would enqueue the same cron work.

Each action has an eight-minute execution budget and a ten-minute Redis lock,
so another scheduled copy or another worker cannot run the same action at the
same time. A hard-killed task becomes eligible for Redis Stream redelivery
after twelve minutes. Taskiq checks stale claims after subsequent stream
traffic; the minute-level catalog provides that wake-up in this deployment.
The stream retains at most 250,000 recent trigger messages; PostgreSQL, not
retained Taskiq history, is the recovery authority.

If a Taskiq worker is unavailable, the Redis Stream retains scheduled messages
and a worker consumes them after recovery. If the scheduler itself is down, no
new cron message exists for that interval. Minute-level recovery scans catch up
from PostgreSQL on the next tick; hourly/daily cleanup waits for its next cron
unless an operator invokes the underlying action deliberately.

Schedule occurrence recovery waits fifteen minutes before treating a claimed
row as stranded. This keeps recovery behind the ordinary-action execution
budget instead of racing a live dispatcher whose claim is temporarily marked
with `next_at = NULL`.

During the first deployment, the Absurd worker completes any already-filed
`eylo.periodic.tick.v1` task as retired and does not spawn a successor. This
drains the old chain without leaving an unknown task in the durable queue.

## Inspect work from the console

- **Operations → Agent runs**: origin, lifecycle, steps, usage, waits, result.
- **Operations → Events**: durable delivery and dead-letter state.
- **Operations → Voice sessions**: live/canonical transcript and recording.
- **Platform → Knowledge/Memory**: ingestion, formation, reconciliation, and
  reindex state.
- **Platform → Automations** and **Products → Outbound → Campaigns**:
  occurrences and attempts.

## Handle an input wait

An Agent run may enter `waiting_for_input` or `waiting_for_approval`. The run is
durably checkpointed and releases compute. A user response is written first,
then wakes the named durable wait. There is no timeout merely because the user
has not answered.

## Cancel work

Use the owning module's API or console action. Cancellation is persisted before
the durable engine is signalled. Do not delete queue rows or force a lifecycle
state in SQL.

## Diagnose retries

Inspect the product job and Agent run first, then the worker log. Distinguish:

- retryable provider/network failure;
- deterministic validation or extraction failure;
- missing configuration;
- exhausted execution budget;
- cancellation;
- dead-lettered durable event consumer.

The queue is an execution authority, not the product audit projection.
