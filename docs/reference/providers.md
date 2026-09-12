# Provider and socket catalog

Provider configuration is code-catalogued, organization-owned, encrypted,
revisioned, verified, and explicitly bound. The authenticated onboarding
catalog at `/api/provider-onboarding/catalog` is the exact form contract used by
the console.

## Capability vendors

| Capability | Current vendor identifiers | Socket boundary |
| --- | --- | --- |
| LLM | Anthropic, AWS Bedrock, Cerebras, Google Gemini, Groq, OpenAI, OpenAI Responses, Sarvam | `eylo/sockets/llm/` |
| STT | Amazon Transcribe, Deepgram, Deepgram Flux, Sarvam, AssemblyAI, Cartesia, Google Cloud, Gladia, Rev AI, Speechmatics | `eylo/sockets/stt/` and shared voice contracts |
| TTS | Amazon Polly, ElevenLabs, Cartesia, Sarvam, OpenAI, Deepgram, Groq, Rime, Smallest AI, Hume, Murf | `eylo/sockets/tts/` and shared voice contracts |
| Realtime | AWS Amazon Nova 2 Sonic, Google Gemini Live, OpenAI Realtime | `eylo/sockets/realtime/` and `eylo/sockets/voice/vendors/` |
| WebRTC | Metered, Turnix | `eylo/sockets/stun_turn/` |
| Telephony | Twilio, Plivo, Vonage, Exotel | `eylo/sockets/telephony/` |
| Email | SMTP, SendGrid | `eylo/sockets/email/` |
| Storage | Amazon S3, Local filesystem | `eylo/sockets/storage/` |
| Embedding | AWS Bedrock, OpenAI-compatible, Voyage AI | `eylo/sockets/embedding/` |
| Reranking | AWS Bedrock, Cohere, Voyage AI | `eylo/sockets/reranking/` |
| Memory | PostgreSQL + pgvector | `eylo/sockets/memory/` |
| Sandbox | Docker | `eylo/sockets/sandbox/` |

Catalog membership means the implementation carries a configuration and
adapter path. It does not mean every vendor has been live-tested in the current
deployment. Verification state is per organization configuration.

### Telephony runtime contracts

Carrier config and call routing use assignment-validated Pydantic models: routing
is enriched after authentication, and Vonage applies its media format during
adapter initialization. Media frames, operation profiles and control outcomes are
frozen values. SDK clients and transport managers remain ordinary resource owners.
Resolved credentials, raw audio, opener text and session tokens are excluded from
their enclosing runtime snapshots; adapters still access them directly to execute.

Call direction, stream-token requirements, operation support and control failures
have socket-owned enums. Platform call/event enums are translated at the pipeline
boundary. These declarations do not change grants or signed-routing enforcement.

Outbound media routing is a pipeline-owned value with explicit identity and
revision fields. Adapters receive a scalar `StreamParameters` envelope; encoding
revalidates its values rather than implicitly stringifying arbitrary objects.
The parameter envelope and routing snapshots omit tokens and opener content.
Existing custom key casing and Exotel packing are preserved.

The Plivo builder uses native booleans with pinned SDK 4.59.3 and delegates XML
escaping to the SDK. [Plivo's streaming contract](https://www.plivo.com/docs/voice/xml/audio-streaming)
defines those boolean attributes. Public GET/POST `/api/voice/plivo/answer`
accepts only the exact, unexpired, signed outbound URL for the configured server
domain; it does not fetch the URL, resolve credentials or consume a media claim.
It returns non-cacheable XML with an explicit 8 kHz mu-law content type matching
the adapter's STT/output declarations, not an inferred vendor default. The
subsequent WebSocket owns the one-time DB claim.

[Twilio's Stream contract](https://www.twilio.com/docs/voice/twiml/stream) prohibits
query parameters and requires each custom parameter's combined name/value length
to be under 500 characters. Outbound calls therefore use the query-free
`/api/media/stream/twilio` endpoint. The adapter fragments the opaque signed token
into at most 128 parts of 480 characters, without truncation; this is Eylo's
transport bound, not a vendor statement about allowed total parameters. The
native start-frame parser reassembles those parts; only authenticated claims
populate platform routing. Missing, extra, malformed or oversized fragments are
refused. Signatures, expiry, pinned identity, and the existing one-time DB media
claim still govern access. The unsigned start phase has a 30-second deadline
and a 128-KiB frame-size bound (text characters for text frames).

The existing query-based `/api/media/stream` route remains available for other
carrier applets. Function and ASGI checks establish these codecs and authorization
paths, not live carrier acceptance or simultaneous DB-claim behavior. Carrier
catalog membership is not evidence of a working outbound call.

Incoming carrier media uses `SpeechTransportFormat`; outbound targets use the
telephony-owned `CarrierAudioFormat`. The factory and live manager preserve these
objects through the pipeline. The target is converted to `TTSAudioFormat` at the
TTS boundary; it is distinct from the format actually emitted by the TTS vendor.
Twilio and Plivo retain 8 kHz mu-law, Exotel 8 kHz PCM, and Vonage 16 kHz PCM.
Polly's carrier-rate PCM selection and recorder track formats remain unchanged.

Media sequence values retain carrier string/integer representations rather than
assuming one wire type. [Twilio's Media Streams reference](https://www.twilio.com/docs/voice/media-streams/websocket-messages)
shows string sequence numbers. [Exotel's VoiceBot reference](https://docs.exotel.com/exotel-agentstream/voicebot-applet)
shows numeric envelope sequence numbers, while its field table also describes
strings. The Exotel adapter reads the envelope first and retains the older nested
sequence fallback. This metadata does not introduce an ordering policy.

Status callbacks retain raw signed fields for signature verification. Vendor-owned
schemas then translate call references, native status values and optional integer
seconds into a normalized observation. Lifecycle orchestration lives in
`pipelines/telephony/status_callbacks.py`; canonical status values remain shared
with the module's persistence schemas. Unknown status strings are acknowledged
without a lifecycle update. Malformed IDs, status types or durations receive a
safe `400`; authentication failures remain `403`, and unsupported authenticated
Exotel callbacks remain `501`.

[Twilio call-progress callbacks](https://www.twilio.com/docs/voice/api/call-resource)
use `CallDuration` in seconds, not the separately billed `Duration` in minutes.
[Plivo v1 callbacks](https://www.plivo.com/docs/voice/api/calls) use `CallStatus`
values such as `ringing`, `in-progress` and `completed`; those are not the separate
`Event` values. [Plivo's completed-call fields](https://www.plivo.com/docs/voice/xml/overview)
provide optional `Duration` in seconds.
[Vonage Voice callbacks](https://developer.vonage.com/en/voice/voice-api/webhook-reference)
use `uuid`, `status` and optional `duration` in seconds. The handler applies the
existing monotonic lifecycle and emits local ringing/ended events only after a
committed transition, without rebroadcasting duplicate or stale observations.

### Voice configuration and verification contracts

Voice catalog options use frozen Pydantic values. An owning input-mode enum
distinguishes fixed choices from account-specific custom values; the onboarding
API still projects its existing `allow_custom` field. Catalog labels, option
ordering and provider-owned identifiers are unchanged.

Verification receipts retain the voice kind and its provider enum together.
Identical vendor spellings in STT and TTS are decoded using the kind, not whichever
enum happens to match first. Successful persisted receipts require a positive
revision and timezone-aware verification timestamp. External checks remain outside
DB transactions; the final write targets the revision originally checked.

Speechmatics onboarding stores diarization as a toggle. The shared inference
contract retains that boolean JSON through `SpeechOptionState` and also accepts
the named single-stream modes through `SpeechDiarizationMode`. The adapter maps
the toggle explicitly to its own `SpeechmaticsDiarization` enum before building
the native request. Only `none` and `speaker` are supported by this mono-stream
adapter; channel modes require a different transport path. See the current
[Speechmatics Realtime API](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket).

### Shared PCM frame contracts

`sockets/voice/audio/buffer.py` owns frozen Pydantic `AudioFrame` values, not
vendor SDK frames. PCM16 bytes must exactly match the channel/sample dimensions;
rates and channel counts are positive integers, and empty frames have zero
samples. Raw audio and optional JSON metadata are excluded from snapshots.
Geometry is immutable; the metadata sidecar remains separately mutable.

`AudioByteStream` owns mutable buffering with a fixed, positive chunk size.
Transport writes may split a sample across chunks; complete frames preserve the
original bytes. A final flush refuses an incomplete interleaved sample without
clearing the tail, rather than padding or discarding it. Deepgram/Speechmatics
adapters keep frame-validation failures inside their existing send-failure
boundary. Buffer/resampler resource owners remain ordinary classes.

### Murf WebSocket contracts

Murf's adapter uses private typed handshake, voice, buffering, text and clear
messages. Buffer size is 40–160; buffer delay is 0–1000 ms. The configured values
are sent in a WebSocket settings command, not URL parameters. Variation is 0–5;
the voice pipeline accepts PCM/WAV. See the
[native reference](https://murf.ai/api/docs/api-reference/text-to-speech/stream-input).

The existing endpoint and `voiceId` spelling are retained: Murf's
[quickstart](https://murf.ai/api/docs/text-to-speech/web-sockets) uses `voiceId`
while its generated AsyncAPI says `voice_id`. No model migration is implicit.
Each turn keeps one native context until flush; a matching final event completes
the turn. Interruption invalidates that context before sending clear, so late
audio cannot enter the next turn. The manager consumes the bounded WebSocket
buffer directly, without a detached receiver or an adapter-level dropping queue.
Malformed frames, missing active-context identity, invalid PCM16/WAV framing and
unexpected socket closure fail the turn without logging raw content. WAV headers
are parsed incrementally; only mono PCM16 matching the configured rate is accepted.
Local contract probes cover these paths. Native endpoint/model acceptance and
deployed voice QA remain open in the [typing plan](../plans/python-typing.md).

### Typed retrieval configuration

Embedding and reranking API schemas expose their provider enums and existing
domain settings fields. Create/read validation selects the model from the
provider; an overlapping model-only shape cannot silently select another vendor.
PATCH declares known editable fields, then the service validates them against
the stored provider. An explicitly supplied null is preserved for that validation;
omission is not treated as removal. Endpoint allowlists and credential replacement
remain domain/service rules, not schema defaults.

Responses keep the existing JSON field names, masked secrets, required null
metadata, and omission of an unset `base_url`. Runtime settings unions preserve
the selected model with Pydantic 2.11's
[callable discriminator](https://docs.pydantic.dev/2.11/concepts/unions/#discriminated-unions-with-callable-discriminator).
No tag field is added to API JSON. Because model-only wire shapes overlap, their
OpenAPI projection uses `anyOf`; generated console types retain the concrete
settings fields rather than an arbitrary object.

### Bedrock embeddings

The adapter uses the configured Titan Text Embeddings V2 model, dimensions and
normalization. Native request/response objects follow the
[AWS V2 contract](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html):
float vectors, input token count and the typed embedding map are validated before
vectors reach the shared Knowledge/Memory runtime. Binary-only output is not used.
Malformed or non-finite vectors fail rather than entering the index.

SDK error envelopes map to capability-owned `EmbeddingErrorCode` values; public
error spellings and retry classifications are unchanged for valid SDK errors.
Input text, vectors and live response-body handles stay out of diagnostic model
representations/snapshots. This does not change the embedding-space hash, grant,
model selection or verification revision.

Embedding configuration handoffs use typed settings, credentials and verification
metadata. Stored API/config fields retain their existing format; credentials are
projected explicitly for encrypted persistence, never ordinary model snapshots.
Resolved material checks organization, capability and configuration identity.
Verification results must match the requested provider before they can mark its
revision verified. Custom OpenAI-compatible endpoints still require the exact
deployment allowlist and credential replacement when changed.

Knowledge and Memory restore persisted embedding identity through three typed row
projections: active, reindex source and reindex target. Each declares its actual
column names; there is no runtime prefix-based field lookup. A configured identity
must have complete, correctly typed fields and a matching coordinate-space hash.
Config ID/revision remain execution provenance rather than hash inputs; organization,
vendor, endpoint, model, dimensions and semantic options define the space. Restoring
a row copies values into detached Pydantic material and performs no DB writes.

Reindex and ingestion writers use the same named projections for ORM constructor
and SQL-update payloads. Organization identity is excluded from those payloads:
the owning service supplies its validated tenant context. Active/target assignment
and target clearing use explicit model attributes, not generated field names.
Projection creation revalidates copied embedding spaces before any assignment.

Live embedding results and Knowledge/Memory reindex checkpoints pass through
`EmbeddingVectorBatch`: ordered list-of-list vectors with finite numeric values,
the complete input count and verified dimensions. Boolean/string components and
malformed containers are refused. Reindex validates replayed values before opening
its staging transaction; replay does not rely on rerunning the vendor adapter.
Invalid persisted checkpoints become terminal product errors, not transport
retries. Live vendor exceptions retain their existing retry policy. Explicit
checkpoint JSON remains a list; vectors are hidden from diagnostic reprs.

Memory reindex distinguishes optional index discovery from required authority.
Required lookup refuses a missing index before downstream effects. Its private
lock enum selects unlocked, shared or exclusive reads within the caller's
transaction. Reindex batches use frozen Pydantic fact/revision objects, validated
on DB-row restoration and again before vector writes. Staging accepts only
reported zero/one-row outcomes; cutover requires a reported count matching the
source facts before activating the target index.

### OpenAI and Voyage embeddings

Both adapters validate request batches and response entries through vendor-owned
Pydantic contracts. Required indices must correspond to the complete input batch;
vectors must be nonempty, finite and dimensionally consistent within that batch.
Malformed entries are rejected, not skipped. Only consumed response fields are
required, so unused metadata does not constrain OpenAI-compatible endpoints.

The [OpenAI embedding contract](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
is used through the pinned Python SDK, retaining its base64 decoding and configured
endpoint. SDK decoding failures become safe `invalid_response` errors.
[Voyage requests](https://docs.voyageai.com/reference/embeddings-api) retain explicit
query/document intent, float output and disabled truncation. Batch sizes remain
256 for OpenAI and 128 for Voyage; these are Eylo's existing bounds, not claims of
the vendors' maximum capacity. Text and vector fields are omitted from diagnostic
model snapshots; explicit request serialization includes text only for transport.

### Typed Memory dependency authority

Memory settings contain explicit embedding and extraction-LLM configuration IDs.
The Memory config API and domain validate these as UUID fields; JSON projections
convert them to strings. Create/read/verification responses expose the owned
`MemoryProviders` enum, and settings use `MemorySettings` in OpenAPI and the
generated console client. A config PATCH replaces the complete settings object:
both dependency IDs are required. Omitting config leaves dependencies unchanged;
explicit null or unknown settings fields are rejected. Memory accepts no
credentials of its own. Dependency configs continue to own secrets and executable
vendor selection.

Verification writes and runtime readback share `MemoryDependencyAuthority`:
dependency IDs/revisions, embedding coordinate facts and extraction-LLM facts.
Extra JSON metadata is preserved separately from those typed fields. A resolved
Memory config requires matching dependency IDs; runtime composition compares
typed LLM authority before executing. Provider/model observation strings retain
their existing casing rather than silently selecting a different dependency.

Runtime composition excludes adapters and completion callables from dumps and
reprs. Its runtime-checkable completion protocol validates callable presence;
the static signature still owns the keyword arguments and async return type.
Provider verification remains outside DB transactions, followed by revision-safe
metadata persistence and index recording. Failures and cancellation skip that
final write phase.

Memory fact metadata remains open JSON, separate from typed provenance and
dependency authority. Adapter input is copied and validated before model/DB work;
opaque Python objects, non-string keys and non-finite numbers are refused without
echoing metadata. Fact/recall models, ORM annotations and operator projections use
`dict[str, JsonValue]`. Metadata is omitted from model reprs, not from explicit
JSON responses. Stored null metadata retains its empty-object projection. Reindex
semantic options also use JSON values. Pydantic's open `JsonValue` schema remains
`unknown` in the generated TypeScript client; it is not a fixed field catalog.

PgVector fact/search/locked/history rows and mutation targets are validated into
adapter-owned Pydantic projections before their fields are consumed. They require
native UUIDs, aware timestamps, finite distances, positive state revisions and an
exact declared owner. SQL scope and revision filters remain authoritative; the row
contracts do not replace them. Invalid rows produce a content-free terminal
Memory error. Correction `RETURNING` rows are validated before history/commit,
and history's returned timestamp is validated before advancing its cursor.

Formation plans retain their persisted list shape through `MemoryOperationBatch`.
`MemoryFormationOutcomes` owns the committed operation list and checks its counts
against those operations. The adapter and recovery pipeline consume this same
contract; ORM JSON annotations do not replace read-time validation. Plan policy
stays separate: an ADD plan cannot supply a target ID, while its committed outcome
contains the created memory ID. A completed effect requires both outcomes and an
aware completion timestamp. Partial or malformed stored effects are refused, not
treated as a fresh plan. Fact content is excluded from these wrapper reprs but
retained in explicit persistence JSON.

### Memory failure recovery

Memory adapters and pipelines construct `MemoryError` with a
`MemoryRecoveryPolicy`: `TERMINAL` for contract/authority failures or `RETRY` for
existing transient/provider/conflict paths. Constructor values must be enum
members; boolean and raw-string policies are rejected. Worker `.retryable`
checks are read-only projections of that decision.

Embedding failure translation belongs to the Memory composition pipeline, not
either capability's contract. It preserves the embedding retry decision and
vendor identity while replacing exception detail with a safe Memory message.
Formation and reconciliation workers persist failure state and release their
execution reservation before raising a retry request outside the transaction.

Memory formation restores each timestamp/message-ID watermark as a complete,
frozen Pydantic value. Both absent means an empty watermark; a half-present pair
is invalid, matching the DB pair constraints. Ordering remains timestamp then
UUID, with exclusive processed and inclusive requested bounds. Cursor selection
uses an enum, and SQL bounds use typed parameters rather than interpolated values.

Formation, reconciliation and reindex task inputs share `MemoryJobParams`: exactly
the organization and job IDs, decoded from UUIDs or wire strings. Arbitrary Python
objects are not stringified into authority. Each workflow owns a typed receipt
with its existing fields; reindex failure keeps its smaller job-ID/state result.
Formation receipt timestamps preserve ISO offsets, including `+00:00`. Receipt
types validate counters but do not grant authority or replace DB job-state fences.

Formation query construction preserves the selected result types through its
shared eligibility filters. Timestamp/ID queries unpack typed tuples; execution
loads typed message/participant pairs. The extractor accepts user/assistant text
content contracts rather than probing arbitrary content attributes. Tenant,
conversation, deletion, message-window and Memory-tool exclusion filters remain
in the query.

Reconciliation uses the same complete timestamp/UUID invariant for change ranges.
It rejects incomplete or non-advancing ranges before querying changes. Related
fact decisions resolve to a complete positive revision fence before effect
selection. Frozen reconciliation batches and proposals are revalidated at
persistence and application boundaries, including nested copied models; their
existing stored JSON shape is unchanged. Outcome receipts use nonnegative typed
counts. Partition queries select explicit ORM owner columns rather than dynamic
attribute names.

### Knowledge query and ingestion boundaries

Knowledge documents and results are frozen, revalidated Pydantic values with
JSON-only metadata. Result scores must be finite; neither strings nor booleans
stand in for numeric scores. Ingestion takes a fresh validated document snapshot
before side effects, so later mutation of the caller's nested metadata cannot
change the pending write. Invalid operator documents receive a safe error instead
of exposing validation input. Existing document identity and tool payload shapes
are unchanged.

`KnowledgeRecovery` names terminal versus retryable adapter failures. The worker
still owns retry execution; the enum does not add inline retries. Invalid stored
document reconstruction becomes an `IngestionError`, which is terminal rather
than a retryable infrastructure failure. Knowledge tools use typed conversation
context and JSON results; the injected context remains absent from their
agent-visible input schemas. Tools accept both conversation and background-run
context. A background execution ID is not a conversation ID: it cannot activate
a conversation-scoped grant, while organization/agent grants still apply.

The module-owned `KnowledgeVendor` enum preserves the stored `postgres_fts` and
`pgvector` names. Its catalog uses frozen Pydantic specifications; socket provider
identifiers remain adapter-owned. Embedding model overrides in KB metadata remain
unsupported: the explicit provider binding owns that authority. Only omitted or
null metadata receives the existing chunking defaults; malformed falsey values
are rejected.

Durable ingestion validates its ID-only input before loading a product row.
UUID strings decode explicitly; extra fields and arbitrary object coercion are
refused. Typed receipts preserve existing JSON keys and lifecycle values, including
the smaller failure receipt. Timeline payloads contain only KB/document IDs and
an optional named failure code. No content or vendor exception text is added.
Checkpoint replay skips completed ingestion; the returned document ID must still
match the product job before success is recorded. Provider work remains outside
the state-update transactions.

Postgres FTS and pgvector adapters receive typed session factories, chunkers and
embedding functions. Their frozen Pydantic authority fixes the organization,
knowledgebase and scope partition; copied authority is revalidated at construction.
The resolver retains typed chunking settings through adapter construction instead
of reading configuration dictionary keys. Both adapters honor the public
`query(text=..., scopes=...)` signature.

Consumed SQL rows are validated before becoming Knowledge results: document UUID,
scope, finite rank/distance and JSON metadata must have the expected shape. FTS
rank and inverted cosine distance retain their distinct meanings. Invalid rows
fail the search rather than being silently dropped. Metadata and vector literals
are validated before the replacement transaction; vendor I/O remains outside it.
Document deletion requires a known nonnegative affected-row count before commit.

Concurrent Knowledge searches carry resolved adapter work and a snapshot of the
knowledgebase ID/name, not an ORM row beyond the configuration transaction.
Invalid scope selections are rejected; an empty selection still searches
nothing. Cancellation propagates, while ordinary provider errors retain the
existing degraded-result behavior. Retrieved candidates, final citations and
query responses are typed pipeline objects, serialized only at the agent tool
boundary. Reranking preserves the original retrieval score; citation labels
follow the final result order. Non-finite retrieval scores mark that
knowledgebase unavailable. Query observations are local typed metrics, excluded
from the tool payload. Unranked results omit the optional retrieval score, and
invalid requests retain the existing payload without ranking metadata.

Storage ingestion downloads and extracts using the validated locator key.
Pinned storage authority and locators are frozen Pydantic contracts with an
immutable location snapshot. UUID strings decode at restoration; revisions must
be positive integers, and object keys must be strings without traversal. Boolean
revisions and non-string keys are not coerced. Valid persisted JSON, location
fingerprints and storage URIs are unchanged. Historical runtime resolution
revalidates copied authority before reading configuration and checks the exact
organization, config ID, revision, provider and location before creating an
adapter. Persistence helpers retain the sanitized `InvalidStorageLocator` boundary.

Storage config resolution uses typed S3 settings and static/session credentials,
or filesystem settings with no credentials. The public config/secrets JSON shape
is unchanged. Read-only provider mappings are copied at the validation boundary;
ordinary model dumps and representations exclude plaintext credentials. Resolved
material must match the requested organization, config ID and Storage capability;
pinned resolution also checks the requested revision. Local runtime handles are
excluded from serialization. Verification validates the returned provider and
capabilities before marking the tested revision verified. Provider I/O remains
outside DB transactions, with revision compare-and-swap on the final write.

Storage API `config` fields reuse the domain's S3/filesystem settings models;
OpenAPI and generated console types expose their fields and the existing provider
and credential-mode enums. Nested JSON names remain unchanged. Create/response
contracts check provider/settings agreement; updates validate against the stored
provider in the service. Secret patches remain string-keyed values with explicit
omitted/null semantics, followed by provider-specific credential validation.
API responses contain masked secrets only. Reference checks require one `EXISTS`
result per inspected owner before config deletion; an absent query result is an
execution failure, not permission to delete.

Storage failures carry named operation, failure and recovery values. The existing
diagnostic `code` string and read-only `retryable` predicate are derived from those
values. A retry classification does not itself authorize replay: recording PUTs
still require stable-key support before a retryable outbound outcome is recorded.
S3 parses the consumed fields of the documented
[AWS error response](https://docs.aws.amazon.com/boto3/latest/guide/error-handling.html#parsing-error-responses-and-catching-exceptions-from-aws-services)
inside its adapter. Unknown native codes remain valid vendor data; malformed
status/code fields produce a terminal typed error rather than fabricated missing
objects or retry decisions. Provider messages and headers are not retained in the
normalized error. Runtime adapter constructors revalidate config instances;
credential fields are excluded from generic serialization. Recording stream
projections validate byte size and exclude the live iterator from serialization.

The S3 SDK seam narrows the generated client/paginator to the methods Eylo uses.
Bucket/object/read arguments are typed before SDK serialization; successful GET
responses require the installed aiobotocore `StreamingBody` contract, including
its checksum subtype. The body is excluded from serialization. Reads must return
bytes; text, booleans and other values cannot become file contents. Both full
downloads and streams close the body on exit, including cancellation. A cleanup
failure does not replace an existing read error or cancellation; after an otherwise
successful read it raises the typed `download_cleanup_failed` error.
Bounded downloads retain the extra-byte probe using a single
[S3 byte range](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html#API_GetObject_RequestSyntax).
The namespace and size limit are unchanged; S3 and filesystem inputs reject
nonpositive, boolean and non-integer limits consistently.

Verification has a 60-second operation deadline plus at most five seconds for
best-effort probe deletion. Cleanup also runs after cancellation or an upload
with an uncertain outcome and targets only that invocation's unique probe key.
Cleanup failures do not turn verification into success. Cancellation propagates;
no detached cleanup task is created. If a provider finishes an uncertain upload
after cleanup, absence cannot be guaranteed.

Storage observations use a shared strict Pydantic `StoredObject`: byte size must
be a nonnegative integer, not a string or boolean. Corpus screening validates each
observation before child-job creation. Its typed result preserves listing order,
skip reasons and the existing 50-entry rejection-detail limit. The complete
rejection count is retained. Listing remains outside the filing transaction;
child jobs are spawned only after the transaction commits.

Ingestion and reindex share the same ID-only job contract. Corpus imports retain
their distinct `import_id` contract. Full and failure receipts keep their existing
wire shapes; reindex counters must be nonnegative integers. The operator reindex
inspection uses a frozen Pydantic value; its local ORM handles are excluded from
generic serialization, while the API builds the same explicit public projection.

Spreadsheet extraction consumes the public worksheet value interface and closes
the read-only workbook on success and failure. It does not calculate formulas.
Reindex source chunks are immutable validated objects; staging accepts only zero
or one affected row per source chunk. Deletion requires known nonnegative chunk
and grant counts before publishing its lifecycle event; unknown counts are not
reported as a successful zero-row operation.

S3 listing and inspection parse the consumed fields from the native SDK response
before creating shared storage observations. Missing object sizes are not treated
as zero-byte objects; invalid entries fail the listing rather than disappearing.
An empty listing may omit `Contents`. Extra vendor metadata remains outside the
consumed contract. Upload options use typed `ContentType`/`Metadata` serialization.
These shapes follow [AWS ListObjectsV2](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html)
and [AWS HeadObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadObject.html),
checked against the installed Botocore service model. The SDK still owns native
pagination; these schemas add no new AWS endpoint or permission.

### Reranking results and recovery

Vendor-local Pydantic contracts validate the active native request and response:
Cohere uses `top_n`/`results`, Voyage uses `top_k`/`data` with truncation disabled,
and Bedrock uses its nested inline-text request and paginated `results` envelope.
Only the adapter translates native scores into canonical `RerankResult` objects.
Malformed entries reject the entire response; none are silently skipped. Unused
vendor document echoes and diagnostic fields do not enter retrieval results.

Bedrock validates continuation tokens, rejects repeated tokens and excess results,
and bounds one invocation to 1,000 pages. This is an Eylo work bound, not a promise
about vendor page sizes; the shared reranking deadline also bounds elapsed work.
Query/document text and continuation tokens are excluded from ordinary model
representations and dumps; explicit dispatch serialization includes them.

Native contracts follow the [Bedrock Rerank API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Rerank.html),
[Cohere v2 rerank API](https://docs.cohere.com/v2/reference/rerank), and
[Voyage reranker API](https://docs.voyageai.com/reference/reranker-api). Voyage's
`data` envelope is also reflected in its [official response implementation](https://github.com/voyage-ai/voyageai-python/blob/main/voyageai/object/reranking.py).

Reranking config resolution uses provider-owned frozen Pydantic settings and
credential variants. Storage still uses the existing flat config/secret maps;
only the persistence boundary creates those maps. Pipeline builders consume
typed fields and revalidate copied material before creating a socket config.
Ordinary nested dumps/reprs omit credentials and live adapter resources.

Resolution checks the returned snapshot's organization, config, capability and
requested pinned revision. Observed endpoint/model metadata must match before
adapter construction. Verification holds no DB transaction during provider I/O,
then compare-and-swaps the verified revision. Endpoint allowlisting, key
replacement when changing a compatible endpoint, and historical pinned-revision
lifecycle rules remain unchanged.

The shared reranking stage consumes immutable, strictly validated result objects:
each index is a nonnegative integer and each score is finite. It revalidates the
adapter's whole result list before using indices in Knowledge or Memory. Wrong
counts, duplicate/out-of-range indices and malformed or copied-invalid results
produce `degraded` metadata and preserve retrieval order, never a partial ranking.

Adapters translate native failures into `RerankingErrorCode` and a named
`RerankingRecovery` policy. Recovery describes whether a later call could work;
the optional reranking stage does not retry inline. `RankingReason` contains only
safe platform explanations. Timeout falls back; cancellation propagates. Adapter
truncation behavior is declared with `RerankingTruncation`, independently from
the platform candidate/content budgets. Public ranking status/reason strings
remain unchanged.

### Sandbox configuration and verified authority

Sandbox config is parsed into frozen `SandboxExecutionSettings`: endpoint,
image and every resource limit are explicit. Docker V1 accepts only an absolute
Unix socket, no credentials, no network access and a tmpfs workspace no larger
than its memory ceiling. Storage retains the existing config keys.

Verification and live acquisition use the same typed manifest builder. Resolved
work pins the verified image identity, not the operator's mutable image tag.
Verification metadata must match the endpoint, configured image, network mode
and workspace backend. Callers can supply staged files/environment values but
cannot override the manifest's resource or network policy.

Verification runs provider probes outside the DB transaction, then marks only
the unchanged config revision verified. New, reused and restored AgentRun
workspaces require current grant authority; restore also compares pinned config
policy. Reservation commits before container creation. A failed creation,
restore or activation follows the existing cleanup path. These contracts do not
imply that a Docker daemon is installed or reachable on a deployment.

The Docker adapter keeps native SDK `Container`/`Image` resource owners inside
the vendor boundary. Frozen response models validate consumed execution IDs,
exit status, isolation evidence and server version before platform use; unknown
vendor fields are ignored. Demultiplexed output must contain bytes or null per
channel. Socket-based file writes/restores close their channel on every exit;
stream consumers close their SDK stream even when validation or a byte limit
rejects output. This targets the locked/installed Docker SDK 7.2.0 contract:
[detached container returns](https://docker-py.readthedocs.io/en/stable/containers.html#docker.models.containers.ContainerCollection.run)
and [execution sockets](https://docker-py.readthedocs.io/en/stable/api.html#docker.api.exec_api.ExecApiMixin.exec_start).
It does not establish abrupt-process recovery or live daemon readiness.

## Readiness

A provider config is ready when all of these are true:

- credentials are available;
- the current revision has verified successfully;
- the config is enabled;
- it is not deleted;
- the selected revision is the current revision.

An update creates a new revision and clears verification. Runtime resolution
pins organization, capability, config ID, revision, and provider.

## Configuration ownership

| Concern | Authority |
| --- | --- |
| vendor identifiers, model/voice/region options | capability catalog |
| encrypted secret material and revision history | `provider_configs` module |
| provider-specific API/stream behavior | socket adapter |
| organization/config lookup and real verification | capability module plus pipeline |
| operator fields | provider-onboarding catalog |
| Agent access | explicit Agent-provider or Agent-tool relation |

## Provider-enabled tools

`GET /api/{organization_id}/tools/provider-catalog?capability=<capability>`
shows the tools a capability can unlock before it is configured. Runtime
availability combines:

1. organization readiness;
2. the Agent's explicit capability/tool mapping;
3. current runtime facts such as an active call or durable Agent run.

Current capability-backed system tools include:

- memory: `memory_remember`, `memory_recall`, `memory_refresh`, `memory_forget`;
- sandbox: `sandbox_exec`, `sandbox_read`, `sandbox_write`;
- telephony: `dial_keypad`, `place_call`, `schedule_call`, `transfer_call`;
- voice session: `end_call` when a voice session is active.

Telephony tool results retain their JSON status/message fields, serialized from
typed outcomes. Transfer failures preserve the distinction between a provider
rejection and an unconfirmed result. `schedule_call` accepts finite-JSON custom
metadata, but explicit call arguments and authenticated Agent/organization
identity take precedence over colliding metadata keys. Metadata cannot change
the validated destination, opening message, or scheduled time. Phone and keypad
inputs must match the complete expected format, including no trailing newline.
Direct `place_call` remains restricted to the durable execution path.

Transfer lifecycle metadata has typed carrier-outcome time and failure-code
fields plus finite-JSON custom context. The DB representation remains a flat
object: omitted fields stay omitted, explicit nulls remain null, and later
observations replace matching keys without removing unrelated context. Incoming
metadata is validated before the lifecycle transaction; stored context is
validated after the scoped lookup and before row mutation. Transfer-completion
events are broadcast only after persistence succeeds.

Knowledge tools are controlled by knowledgebase grants and conversation scope,
not by choosing a knowledge vendor as an Agent capability.

## Supporting socket packages

Not every socket is an operator-configurable provider. These packages still
belong to the adapter layer and remain domain-independent:

| Package | Responsibility |
| --- | --- |
| `common` | shared provider schema helpers |
| `http` | bounded async HTTP transport primitives |
| `knowledgebase` | PostgreSQL FTS/pgvector search ports, schemas, and chunking contracts |
| `mcp` | MCP client transport |
| `recording` | recording socket namespace; upload orchestration belongs to the voice/storage pipelines |
| `voice` | shared audio frames, buffering, resampling, and streaming voice adapter contracts |

The remaining socket packages map directly to capability rows in the vendor
table above: `email`, `embedding`, `llm`, `memory`, `realtime`, `reranking`,
`sandbox`, `storage`, `stt`, `stun_turn`, `telephony`, and `tts`.

## Vendor addition contract

Use [Add a capability provider vendor](../how-to/add-provider-vendor.md). A
complete addition updates catalog, module config contract, socket adapter,
factory, pipeline verification/resolution, onboarding form projection, tool
requirements when applicable, and current documentation.
