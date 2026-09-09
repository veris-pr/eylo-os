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

### Model and embedding boundaries

Formation, reconciliation, and provider verification share a keyword-only
`MemoryTextCompleter` contract: `system` and `user` text enter, completion text
returns. The pipeline binds the selected LLM authority and bounded generation
settings; the socket does not resolve credentials or import provider modules.
Native SDK requests/responses remain inside the LLM adapter. Usage is metered
before completion text is accepted; unexpected tool calls and empty text are
refused. Formation/reconciliation parsers separately validate the proposed
operations and resolve model-supplied indices to platform-owned identities.

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
