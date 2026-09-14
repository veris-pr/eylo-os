# Lifecycle states

This page summarizes operator-visible state machines. Domain enums and DB
constraints remain authoritative.

## Provider configuration

```text
create/update -> unverified -> verify -> ready
ready --disable--> not ready
ready --update--> new unverified revision
any current revision --delete--> disabled + soft-deleted
```

Readiness also requires credentials to remain available and the revision to be
current.

Deletion is reference-checked before the config is soft-deleted. Agent bindings
include published revisions; embedding references also include Knowledge/Memory
data, pending work, and source/target reindex configurations. Lookups are scoped
to the owning organization and exclude soft-deleted references. An embedding
deletion without its reference-check authority is refused.

## Agent definition

An Agent starts as a draft. Publication creates an immutable usable revision.
Editing changes only the draft. Withdrawal prevents new resolution; revision
revocation targets one published revision. Runtime never executes a draft.

## Agent run

`queued` → `running` → one of:

- `waiting_for_input` → answer → `running`;
- `waiting_for_approval` → approval → `running`;
- `completed`;
- `failed`;
- `cancelled`.

Outcomes are `achieved`, `unachievable`, `failed`, `cancelled`, or `exhausted`.
Steps independently move through pending, running, completed, failed, or
cancelled.

## Message request

```text
PENDING -> PROCESSING -> AWAITING_TOOL_RESULTS -> PROCESSING -> COMPLETED
```

Processing may end as failed, interrupted, or skipped. Invalid transitions are
logged and ignored so they do not roll back unrelated canonical writes.
Interrupted and skipped requests are excluded from future model context.

## User session

`active` → `disconnected` → `active` on reconnect, or `ended`/`failed` as a
terminal state. The connection sequence increases across reconnects. A session
may reference multiple conversations.

## Knowledge and memory indexes

Both expose `active`, `reindex_required`, `reindexing`, and `failed`. A changed
embedding config ID/revision moves the dependent index out of `active` until a
successful reindex publishes the new space.

Knowledge ingestion, corpus import, memory formation, reconciliation, and
reindex jobs persist pending/running/terminal attempts separately from the
resource's index state.

## Voice session and recording

Voice sessions are active, completed, or failed. Canonical transcript state is
`not_run`, `clean`, `redacted`, `failed`, or `no_storage`. Runtime mode is
browser decomposed, browser realtime, or telephony.

Recording upload is secondary durable work: queued/running output becomes
available or failed without interrupting the already completed live call.

## Campaign

Campaigns move through `draft`, `scheduled`, `running`, `paused`, `completed`,
or `canceled`. Per-contact attempts move independently through pending, queued,
in-progress, completed, failed, retry, skipped, or cancelled. Preparation
warnings allow V1 outreach; blockers prevent start.

Call-outcome projection resolves the exact organization, campaign revision,
contact and attempt. A recorded outcome is an idempotent no-op on replay. A
provider tracking ID may be absent when the call was rejected before the provider
assigned one; the campaign attempt remains the authority.

Retry policy uses an immutable `CampaignRetryPolicy` across API input, service
values, revision snapshots and runtime: `max_retries`,
`backoff_seconds`, and `retry_on`. An empty reason list matches any unsuccessful
outcome; the initial attempt is number one. Only a running campaign can schedule
a retry. Relevant stored policy is validated before projection writes; invalid
canonical outcome/policy data is classified as a permanent consumer failure,
not a transient provider error. JSONB retains the same snake-case keys and a JSON
reason list; ORM state does not hold a Pydantic instance.

On create, omitted, null or empty policy preserves the existing channel policy.
Explicit settings use the submitted policy. On update, omission leaves policy
unchanged, an empty object disables retries, and explicit null is rejected.
Attempt execution validates the pinned revision's policy, not a newer campaign
header's policy.

`CampaignScheduleConfig` stores optional `time_window_start`, `time_window_end`
and `timezone` strings. These are **experimental, not enforced**: V1 dispatch
does not use a daily window or timezone to gate outreach. Their text is retained
without interpreting clock or timezone semantics. Create keeps the historical
09:00–18:00/UTC stored value when omitted, null or empty; that value does not
establish an operating window. Partial settings retain only the supplied storage
keys. Update omission preserves settings, `{}` clears them, and null is rejected.
The console form does not expose or overwrite these reserved settings.

Channel config is selected by `CampaignChannel`, not by arbitrary payload keys.
Voice/widget use `EmptyCampaignChannelConfig`; their provider authority comes
from agent mappings. Email uses `EmailCampaignChannelConfig` with optional
`provider_config_id`, `provider_config_revision`, `subject_template` and
`body_template`. Incomplete draft config is allowed. Starting/dispatching email
requires templates and an exact ready provider revision.

Creation or a channel-config update resolves the provider inside the organization
and overwrites any caller-supplied revision. An unrelated update preserves the
existing pin. Clearing config removes that authority. Attempts use their pinned
campaign definition; a newer header cannot replace the email binding. Malformed
identifiers, revision types, template values and unrelated config keys are
rejected rather than coerced or silently ignored. Changing to voice/widget
requires clearing any email-only settings.

Channel dispatch returns `accepted`, `rejected` or `unknown`. A tracking ID is
not proof of acceptance: recovered rejected work remains rejected, and recovered
unknown work stays fenced for reconciliation. Accepted results require a
nonblank tracking ID and cannot carry an error.

Replay policy is `replay_safe` or `recover_only`. Replaying a started effect
requires both the persisted historical permission and the current adapter's
explicit replay-safe policy. V1 DB fields and saved step JSON keep their existing
boolean representation for compatibility; adapters and worker decisions use
enums. The checkpoint decoder validates the wire data before projecting an
outcome, without changing the durable step identity.

The campaign worker validates its organization/attempt ID payload before loading
work. Preparation returns a named detached context or an existing attempt
receipt. The start-effect boundary returns an explicit send/recover decision or
a terminal receipt; neither decision is inferred from dictionary keys. Internal
receipts carry typed IDs and durable state, then serialize to the unchanged v1
task-result fields. Dispatch contexts exclude live adapters and contact/message
content from model snapshots.

Recipient variables keep operator-defined names and JSON values, including
nested objects/lists. Upload, storage and readback validate the same campaign
contract: keys must be strings and numbers must be finite. Python-only objects
are not silently stringified for storage. The upload service validates the full
batch before resolving contacts, and the insert boundary checks mutable values
again. Simple email placeholders retain their existing text substitution;
published message templates still validate their declared variable types.

## Durable event delivery

`pending` → `running` → `succeeded` or `dead_letter`. An inbox receipt proves
the exact consumer transition committed.
