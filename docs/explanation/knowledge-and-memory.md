# Knowledge and memory

Knowledge and memory both retrieve relevant text, but they answer different
ownership questions.

## Knowledge is source-owned

A knowledgebase owns files, chunks, grants, embedding authority, and citations.
Ingestion deterministically extracts supported text, chunks it, embeds it, and
replaces the same source identity on retry. Query returns source references so
an Agent can cite where an answer came from.

An organization knowledgebase may be read-only or writable for a given Agent.
A conversation knowledgebase is created lazily from the conversation ID when
the Agent permits file uploads. The contact never selects an internal
destination.

Grant checks and lifecycle publishers consume their owning ORM models. A read
still evaluates one grant at a time, and conversation grants require the exact
active conversation. Widget upload receipts expose the canonical ingestion enum
and safe failure text, never raw provider errors. Corpus screening persists a
typed summary with at most 50 rejection details and the full skipped count;
event publication reads a separate count projection so historical detail fields
cannot break observation. Invalid observation data remains non-fatal to the
canonical transaction.

Knowledge metadata and embedding semantic options remain extensible JSON objects,
not vendor-specific platform schemas. Their shared contract accepts nested JSON
values with string keys and finite numbers, validating both Python and JSON
inputs. It refuses Python objects and non-finite numbers instead of coercing or
silently changing them. Valid metadata, serialized embedding records and vector
space hashes are unchanged. Corpus-import responses expose the same bounded,
typed skip summary written by screening.

## Memory is experience-owned

Memory stores compact facts learned during use. Ownership is typed:

- Agent memory helps the Agent retain reusable learning;
- contact memory helps the Agent serve one person consistently;
- conversation memory supports an extended exchange.

Recall happens before a turn. Formation proposes facts after relevant
conversation work. Reconciliation detects duplicates and conflicts in the
background. Facts retain provenance, status, expiry, relationships, and index
state so operators can understand what was learned and why.

Extraction criteria follow the context-derived owner level. User memory keeps
stable personal facts; Agent memory keeps reusable, evidence-backed learnings;
conversation memory keeps working context, including temporary decisions,
checkpoints and open questions. The model cannot select a different owner or
broaden the lookup scope. All three use the same operation validation and exact
source references. A valid no-change decision is not proof that a requested fact
was saved; inspect returned changes and recall when verifying a write.

Direct objectives run without a persisted conversation or contact. Their recall
tool reads only the executing Agent's own memories, using its published provider
binding. The pipeline validates the execution organization's and Agent
participant's identities before resolving providers. It does not reinterpret a
member ID as a contact or an AgentRun ID as a conversation. Recall observation
events carry exactly one real execution owner: `conversation_id` or `agent_run_id`.

Direct-objective memory writes are not covered by that read path. The current
agent-tool mutation provenance requires a real conversation and source message;
supporting writes from non-conversation work needs explicit run provenance rather
than synthetic conversation records.

The Memory application accepts the platform's typed execution contexts rather
than duck-typed objects. Conversation scope derivation and formation accept only
`ConversationContext`; direct recall handles `AgentExecutionContext` explicitly.
Deliberate writes validate the source message's conversation and participant
before resolving a provider, so a mismatched message cannot become provenance.
Provider IDs and revisions come directly from the validated published Agent.

Agent-facing Memory results have explicit projection models. They expose facts,
levels, scores, conflicts and outcomes without serializing private provenance or
provider metadata. JSON conversion happens at the system-tool return boundary;
unavailable recall remains distinct from a successful empty result.

### Model and embedding boundaries

Formation, reconciliation, and provider verification share a keyword-only
`MemoryTextCompleter` contract: `system` and `user` text enter, completion text
returns. The pipeline binds the selected LLM authority and bounded generation
settings; the socket does not resolve credentials or import provider modules.
Native SDK requests/responses remain inside the LLM adapter. Usage is metered
before completion text is accepted; unexpected tool calls and empty text are
refused. Formation/reconciliation parsers separately validate the proposed
operations and resolve model-supplied indices to platform-owned identities.

Reconciliation prompt and response fields have socket-owned schemas. Facts with
no comparison candidates are deterministically unrelated; only candidate-bearing
facts reach the model. The module recombines both sets into one complete proposal,
then applies the same ownership, revision and relationship checks. Incomplete or
invalid model decisions are never replaced with guessed outcomes.

The durable `propose:v2` step indexes only comparison inputs. An existing
`propose:v1` checkpoint is replayed against its original full batch, never
reindexed. Both model-backed paths require metering before apply; purely
deterministic work does not require a model usage receipt. Terminal failures
remain visible rather than silently reopening an invalid checkpoint.

Extraction prompt evidence is a typed, socket-owned projection of related
`MemoryResult` values and `MemoryInputMessage` values. Only local indices, roles
and content reach the model; persistent identities remain outside the prompt.
The response parser validates untrusted JSON before producing `MemoryOperation`
objects with exact source references. Memory lifecycle publishers accept their
own concrete job/index models, preserving post-commit publication and best-effort
observation behavior.

Document and query embedders have distinct typed call signatures. The memory
socket also receives a factory for fresh native async DB sessions. Verification
depends on a structural embedding port and resolved LLM authority, not a
pipeline implementation or vendor SDK type. Typing these boundaries does not
replace runtime authority, vector-space, response, or concurrency validation.

## Shared retrieval infrastructure

Both systems can use embedding and optional reranking configurations. The
embedding config ID and revision identify executable provider authority. Vector
compatibility is compared using organization, provider, endpoint, model,
dimensions, and semantic options. A coordinate-space change requires reindexing;
config identity alone is not the vector-space hash.

The systems do not merge stores merely because they share an organization,
scope label, or embedding provider. Every chunk/fact query retains its owning
knowledgebase or typed memory owner.

## Why post-call/async formation

Knowledge ingestion and memory formation are secondary to the live product
flow. They persist jobs, execute durably, and expose failure without blocking a
conversation or call. This keeps the Agent responsive and makes retries
idempotent and inspectable.
