# Product data-flow atlas

Products compose several domain modules and pipelines into a complete
operator/contact outcome. This page contains one section per executable package
under `server/eylo/products/`. The current open-source tree has one product:
Campaigns.

The [pipeline data-flow atlas](pipeline-data-flows.md) documents the reusable
execution boundaries a product calls. Product diagrams instead show who owns
the definition, lifecycle, audience, and final result.

## Campaigns

### Definition, audience, and start

A Campaign is an organization-owned, revisioned outreach definition. Each
revision pins the Agent, template, channel config, scheduling policy, retry
policy, and concurrency limit. Campaign contacts reference organization
contacts; they do not take ownership of those contacts.

Sources: [`campaign_service.py`](../../server/eylo/products/campaigns/services/campaign_service.py),
[`preparation.py`](../../server/eylo/products/campaigns/preparation.py), and
[`controllers.py`](../../server/eylo/products/campaigns/controllers.py).

```mermaid
flowchart LR
    member["Organization member"]
    definition["Campaign name, Agent, channel, template, schedule, retry policy"]
    dependencies["Resolve published Agent, template, and channel config revisions"]
    draft[("Campaign draft and immutable revision")]
    audience["Select or upload organization contacts"]
    contacts[("Campaign-contact plan referencing contacts")]
    prepare["Preparation service"]
    warnings["Warnings: visible, start allowed"]
    blockers["Blockers: start refused"]
    start["Start Campaign"]
    running[("Running published Campaign revision")]
    lifecycle["Pause, resume, cancel, revoke, or complete"]
    history[("Revision, contact, attempt, and analytics history")]

    member --> definition --> dependencies --> draft
    member --> audience --> contacts
    draft --> prepare
    contacts --> prepare
    prepare --> warnings --> start
    prepare --> blockers
    start --> running --> lifecycle --> history
```

The start transition refuses deletion-pending contacts and other blockers.
Preparation warnings remain visible but do not implement conditional outreach
in V1.

### Per-contact execution and outcome

Periodic work files bounded per-contact attempts from a running Campaign.
Channel adapters compose the existing email, telephony, or conversation
pipelines. Each attempt has a stable identity so recovery can inspect a prior
effect before deciding whether another send is safe.

Sources: [`execution_service.py`](../../server/eylo/products/campaigns/services/execution_service.py),
[`channels`](../../server/eylo/products/campaigns/channels/),
[`outcomes.py`](../../server/eylo/products/campaigns/outcomes.py), and the
[`Campaign attempt pipeline`](pipeline-data-flows.md#campaign-attempt-pipeline).

```mermaid
flowchart LR
    running[("Running Campaign and pinned revision")]
    due["Schedule, retry time, and concurrency selection"]
    attempt[("Unique contact attempt")]
    durable["Durable Campaign-attempt workflow"]
    render["Render pinned initial-message template"]
    channel{"Published channel"}
    email["Email pipeline and outbound receipt"]
    voice["Telephony pipeline and call facts"]
    widget["Idempotent conversation and opener"]
    outcome["Canonical channel outcome"]
    retry{"Retry policy"}
    retry_at[("Contact queued for next retry_at")]
    terminal[("Contact completed, failed, skipped, or cancelled")]
    campaign[("Campaign counters, terminal state, and analytics")]
    contact[("Independently owned organization contact")]

    running --> due --> attempt --> durable --> render --> channel
    channel --> email --> outcome
    channel --> voice --> outcome
    channel --> widget --> outcome
    outcome --> retry
    retry --> retry_at --> due
    retry --> terminal --> campaign
    contact --> due
    terminal -. "does not delete" .-> contact
```

Voice completion may arrive later through a durable call-outcome consumer.
Email and widget produce immediate canonical acceptance/outcome records. A
Campaign or call deletion never deletes the organization contact.
