# Sessions, conversations, and ownership

A user session and a conversation answer different questions.

- User session: one contact visit or call, including reconnects and technical
  transport facts.
- Conversation: one durable exchange of participants and messages that may
  continue across visits.

## Many-to-many over time

A user may resume the same conversation in a later session. A user may also
switch between several conversations during one session. The
`user_session_conversations` relation records first/last observation of each
pair instead of forcing either entity to own the other.

A start operation returns one typed outcome: created or reconnected. The result
keeps its transaction-owned session row by identity but excludes that row from
snapshots. The widget's existing `created` and `reconnected` response fields are
derived from the outcome, so both cannot be true internally. Reconnect increments
the connection sequence; stale disconnect/finish commands cannot end a newer
connection.

## Starting a widget conversation

Widget ingress requires a resolved contact, a user session and WebSocket runtime
state before starting DB work. The server canonicalizes the contact from session
authority and forces the widget channel, validating the resulting request.
It resolves the published Agent or swarm, persists exact revision references,
links the conversation to the user session and records the start fact. Only after
that transaction succeeds does it update the WebSocket's selected Agent.

## Child transport sessions

WebSocket, WebRTC, voice-provider, and telephony sessions are runtime children
of the user session. Each has its own connection/resource lifecycle. They may
fail or reconnect without changing conversation identity.

WebSocket text frames are rate-limited before validation into the event envelope.
Binary audio uses a separate frame path and retains its bytes. The dispatcher
uses the authenticated session/contact context for authority; IDs in a client
frame cannot replace it. Connection headers supply descriptive client metadata
only. Invalid input produces a safe error without reflecting the submitted body.

Redis delivery envelopes validate contact and organization IDs before routing.
Conversation-scoped events also require a conversation ID. Delivery preserves
the existing contact/org boundary and transport-specific conversation selection.
A failed send returns `False` and cleans up only the expected socket; cancellation
propagates to the connection lifecycle owner.

## Canonical messages

Messages belong to conversations. User, assistant, system, tool-use, tool-result,
and widget/interface content remain visible to organization members in the
operator console. Request status tracks whether the Agent work behind an
assistant response is pending, processing, waiting on tools, or terminal.

Only terminal valid message classes enter future model history. This prevents a
failed, interrupted, or still-processing placeholder from poisoning context or
provider caching.

Request-status updates return the DB cursor's affected-row count. An update
excludes deleted messages and rows already at the requested status, so repeating
it does not report another change. The service owns transition policy and uses
that count when deciding whether to file session facts. Repository authority
lookups return validated UUID owners; request timeline facts require a user
session, while background-run output may have none.

## Reading a conversation

Conversation aggregates authorize the requested conversation IDs first, then
batch-load their participants, related contacts/agents and messages. Related
contacts and agents are constrained to the same organization. A larger batch
does not add one query per conversation; omitted participants or message bodies
skip those reads, while message counts remain available.

Message pagination selects a newest-first window separately for each
conversation, using timestamp and ID as a stable order. The selected window is
presented oldest-first for reading. Counts describe all matching messages, not
just that window. Message-kind filters apply to both counts and bodies.

Internal aggregate assembly uses typed, transaction-bound values. Attached rows
and content are excluded from incidental snapshots; the service explicitly
projects the public response. Participant summaries validate persisted kinds
before those kinds are used to label message senders. These reads do not change
message state; member and contact entrypoints retain their distinct access checks.

The console list uses the same predicates for its count and page queries. Search
treats `%`, `_` and backslash as literal characters; sorting has an ID tie break
and places null values last. Its internal page result is validated separately
from the public pagination envelope. Conversation schemas require an organization
owner rather than inheriting an optional-owner contract.

When preparing framework input, widget submissions may be projected to a new text
message with contact context and recent-handoff warnings. The copy is validated,
preserving message identity and typed metadata; persisted history is untouched.
Ordinary text/image blocks retain the existing no-enrichment behavior.

## Timeline

The session timeline correlates allowlisted durable facts by user-session ID.
It is an operational explanation of what the user experienced, not a total
ordering guarantee or a copy of message content.

Session list options are validated internal values. Search text is excluded from
incidental snapshots, while execution retains literal-character search and the
existing filters. Lists use two queries regardless of page size; detail counts
use one combined aggregate query after ownership lookup. Typed row projections
preserve those query boundaries rather than resolving counts per item.
