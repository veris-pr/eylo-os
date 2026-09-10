# Provider architecture

Eylo is a bring-your-own-provider platform. A provider configuration supplies
organization authority; a socket supplies protocol behavior; a pipeline
connects that adapter to product work.

## Why provider config is separate from adapters

An adapter should be reusable for many organizations and configurations. It
must not know which organization owns a credential or how that secret is
stored. The provider-config domain therefore owns:

- organization and capability identity;
- encrypted secrets;
- public non-secret settings;
- current revision and verification metadata;
- enabled/deleted/readiness state.

The pipeline resolves that aggregate to an immutable in-memory effective
config. Only then does a factory construct the socket adapter.

LLM callers preserve the resolved generation object through `LLMInferenceConfig`.
Its frozen `LLMGenerationConfig` model is owned by the common contract;
provider-specific validation remains in the configuration domain. Conversations, background prompts,
swarm workers, and memory extraction no longer serialize configuration to a
storage dictionary on the way to inference. `LLMPromptCaching` expresses the
runtime cache policy; existing public boolean fields are translated at the
pipeline boundary without changing their API/storage shape.

The shared LLM adapter contract exposes normalized inference and streaming
results. SDK clients and request/response transformations are adapter details,
not platform-wide methods returning `Any`. OpenAI Chat Completions preserves the
installed SDK's message, function, request, completion, and stream types.
Wire literals already defined by those SDK contracts remain vendor-owned. This
does not yet mean every vendor's response/stream implementation is fully typed;
remaining work and verification limits are tracked in the
[typing plan](../plans/python-typing.md).

OpenAI Chat/Responses, Anthropic/Bedrock, Groq, Cerebras, and Sarvam own their native SDK messages,
requests, responses, and stream state. Groq, Cerebras, and Sarvam do not inherit
an OpenAI client or response contract.
SDK-parsed output is
validated before normalization. Tool calls require stable IDs/names, finite JSON
object arguments, and a matching terminal reason. A malformed member rejects the
entire batch rather than exposing an executable prefix. Text can stream before
completion; incomplete tool arguments never become an empty executable request.
The neutral tool-call buffer owns JSON and identity checks, while each vendor
owns its terminal reasons, stream variants, schema rules, and usage projection.
OpenAI Chat preserves tool-progress envelopes, but emits them only after the
whole terminal batch is validated. Refusals use the existing human-readable
`[Refusal]` text representation; they cannot authorize tools.

Responses uses its complete terminal response as the authority for output, not
reconstructed tool-argument fragments. Its native output-item ID and function
call ID are distinct; only the call ID becomes the platform tool-use ID. Typed
events track text progress and stream identity. Missing terminal output, failed
responses, inconsistent item identity, and malformed batches cannot authorize
tools. Text-only incomplete responses preserve the vendor's token-limit or
content-filter reason; refusals remain visible. Hosted tool/audio outputs are
not supported by this function-tool adapter.

Anthropic and Bedrock share the Claude Messages protocol, not an OpenAI-shaped
fallback. Bedrock owns SigV4 credentials, region, and binary event-stream decoding
through its native SDK client. The adapter validates raw native events and tracks
block lifecycles; a tool block's initial empty input is only a placeholder.
Executable calls require complete JSON, closed blocks, a matching stop reason,
and `message_stop`. No executable prefix escapes before the whole batch validates.
Text/thinking progress remains separate from tools. Opaque redacted thinking is
not rendered as text; hosted tools and their pause/resume flow are unsupported.
This does not implement signed extended-thinking history round trips.

Claude cache annotations preserve the existing system/last-tool/last-two-user
breakpoints without mutating canonical history or caching empty text blocks.
Cumulative tail usage updates input, output, and cache counts. Native image
contracts distinguish remote HTTP(S) URLs from inline base64 data: Claude accepts
both; Bedrock accepts only base64. The adapter does not fetch URLs or local files.
Byte encoding and declared MIME are validated, not image contents or dimensions.

Canonical response content is a discriminated union: text and thinking carry
text payloads; tool use carries a named call and finite JSON arguments. The
discriminator cannot be changed after validation, and an optional outer tool ID
must match the call ID. Native adapters construct concrete variants; callers read
typed fields without guessing whether content is a string, dictionary, or SDK
object. The serialized `type`/`content`/`id` envelope is unchanged. Image input is
a separate message contract, not an executable canonical output variant.

Response metadata has typed text, thinking, and tool-completion deltas. The shared
contract interprets existing stream flags as a response-phase enum; only text
progress enters speech delivery. Vendor finish/status enums, timing, safety, and
replay schemas stay adapter-owned and cross the socket as validated JSON, never
SDK objects. Omitted fields and explicit vendor nulls survive serialization.
Framework conversion passes neutral JSON metadata. Framework metadata fields
preserve owner-declared subclass fields through nested run/message/tool snapshots;
owner-declared exclusions and secret masking still apply. Runtime dependencies in
`RunContext.local_context` are excluded from snapshots, including explicit includes.
Remaining caller typing and the pinned serializer's partial-selection limitation are tracked in
the [typing plan](../plans/python-typing.md).

The framework receives application operations through `RunCallbacks`, passed as
`FrameworkRunner(callbacks=...)`, not callback keys mixed into `local_context`. The typed
`after_model_response`, `before_tool_call`, `after_tool_result`, and
`after_tool_results` callbacks preserve persistence order, await completion, and
stop the run on failure; cancellation propagates. The last callback returns the
next `RunInput`, including refreshed agent tools after a handoff. `RunHooks` are
separate best-effort lifecycle notifications. Runtime state remains owned by the
application; callback signatures contain only framework contracts. Custom
framework callers must pass callbacks through the constructor, not the old dict
keys. No fallback dict-based callback dispatch remains.

Platform callers use `PlatformRunState` for hydrated context, exact command IDs,
and execution authority. `ConversationRunState` additionally retains persisted
message rows and the last-message ID needed for reply-parent links. Scheduled and
objective runs use a typed in-memory `AgentExecutionContext`; its scope does not
create or impersonate a conversation DB row. Handoff refresh replaces the context
on the same state object, so the model and tool executor observe the same agent.
These are pipeline-owned types; the standalone framework does not import them.

Execution scope and participant identities are frozen Pydantic models. Execution
context and run state remain mutable, with validation on field assignment.
Command/workflow ports and lifecycle hooks retain their actual runtime instances;
they are not decoded from JSON, copied into prompts, or included in model dumps.
Conversation content and in-flight message references are also excluded from
run-state serialization. These runtime-state models are not replay envelopes:
durable replay uses the separately owned IDs, manifests and transcript contracts.

Pydantic is the default for platform-owned data contracts, including internal
execution values, so validation and serialization follow one convention. An
internal-only type does not by itself justify a dataclass. Retaining one requires
a documented requirement, such as SDK interoperability or a measured constraint;
SDK-owned types remain native inside adapters. Classes that own connections,
queues, and task lifetimes may remain ordinary classes: lifecycle management is
not a data schema. Frozen models prevent field reassignment, not mutation of
nested lists or dictionaries; use immutable containers where that invariant is
required. Assignment validation likewise does not validate in-place collection
mutations.

The implementation uses Pydantic 2.11's
[instance validation](https://docs.pydantic.dev/2.11/api/functional_validators/#pydantic.functional_validators.InstanceOf)
and [field exclusion](https://docs.pydantic.dev/2.11/concepts/serialization/#model-and-field-level-include-and-exclude).
The ports remain typed behavioral protocols; a runtime structural check does not
validate method signatures or grant domain authorization.

Conversation, scheduled, objective, and parallel-task executors share
`run_with_agent_heartbeat`. It checks the Agent-run active-time budget while
renewing the durable claim. The runtime's outer lease-renewal loop does not
replace this product budget check. The helper owns the operation's lifetime:
heartbeat failure or parent cancellation cancels unfinished work and retrieves
the child outcome, including simultaneous child failure. It accepts the declared
`Awaitable` contract rather than only coroutine objects. No extra worker or
durable execution authority is introduced.

Built-in title and summary jobs receive the executing background agent explicitly.
Its pinned provider controls generation; conversation history supplies the input,
not provider authority. Summary thresholds use the conversation agent's model
window, while summary generation uses the background agent's model. Config
resolution and output persistence use separate short transactions; inference runs
between them. One-shot parallel LLM tasks likewise use their persisted config ID
and revision, never an organization default.

Parallel-task dispatch resolves pinned topology and background attachments in
DB-only read scopes. Filing commits the task message, AgentRun and execution
reservation together before attempting Absurd spawn. Without a caller session,
these are short owned transactions; the legacy caller-session path still commits
that session and must not contain unrelated uncommitted work. A failed spawn
leaves the committed run available for recovery.

Task routing, dispatch status, message metadata and the persisted run manifest
have explicit contracts. Workers validate the manifest against the conversation,
source revision and task routing before execution. The filing service allocates
an independent request ID on first creation; retries reuse the same task even
after its status advances. Changed instructions or authority still conflict.
The registered task tool refuses non-conversation execution contexts rather than
treating their scope IDs as persisted conversations.

Handoffs use the conversation's exact swarm revision. Generated handoff tools
carry a target agent revision, not a fabricated persisted tool revision. The
pipeline rechecks the topology and atomically switches the expected primary
participant under one DB-only scope. It owns that scope when no caller session
exists; a borrowed session remains the caller's responsibility to commit or
roll back. Typed outcomes do not partially mutate the runtime context.

Text and realtime callers rebuild the complete context after persistence. If a
realtime context rebuild or native session update fails, the existing handoff
failure path closes the call instead of continuing with mixed agent authority.
The original agent still owns the handoff tool transcript; subsequent messages
use the new participant. The primary agent's voice/provider authority stays
pinned. Realtime dispatch converts structured tool output to JSON text once,
before both transcript buffering and adapter delivery.

Generated-widget execution likewise belongs to the pipeline layer. The interfaces
module owns the strict component input and delivery-receipt contracts; the
conversation service owns message persistence and post-commit notification.
Validation happens before the write scope. Without an active transaction the
pipeline owns a short DB-only transaction; an existing caller retains commit and
rollback ownership. The tool never appends an uncommitted widget to in-memory
history. Text execution returns the persisted message as its terminal artifact,
and later context reads hydrate it from the DB. Validation-cache entries are
copied on storage/read, so mutating one result cannot poison another invocation.

Provider-neutral widget content lives in `common/contracts/widgets.py`. Each
component has a discriminated payload and typed props shared by tool validation,
message persistence, history readback, and user-response validation. The
interfaces module owns the catalog and tool input/receipt, not a second content
schema. SDK field aliases such as `submitLabel` survive nested DB serialization;
validated values are retained rather than replaced with the original dictionary.

User submissions use the companion `common/contracts/widget_responses.py`:
four discriminated response models own component/action combinations, UUID
parent identity and finite, size-bounded data. Buttons and card selections have
fixed fields; forms and date pickers retain their generated field names. The
WebSocket input schema normalizes flat/wrapped inputs once and passes the model
through parent authorization, message/run filing and history serialization.
The pipeline still checks offered values against the locked, conversation-scoped
parent; a valid response schema is not authorization. Only input parsing maps
Pydantic failures to client rejection—internal model failures remain server errors.
Compatibility message metadata carries canonical serialized content, not a second
unvalidated copy of the client input. `MessageMeta` validates persisted interaction
facts and finite JSON extensions. The shared `SessionChannel` enum identifies the
transport; the server stamps it from the session, not customer context. Browser
voice selection reads the latest user's typed `interaction.is_voice` or historical
boolean `is_audio`; phone conversations remain voice. Missing metadata fields stay
absent during serialization so old replay fingerprints are preserved. Optional
`duration_ms` is nonnegative integer milliseconds, never a boolean, string or
fractional value. `speech_turn_outcome` uses the shared voice outcome enum. The
transcript projection consumes these fields directly; historical messages without
an explicit outcome retain the terminal request-status fallback. Voice provenance
also has named fields: transport-local session text, durable session UUID, runtime
mode, positive sequence/redaction revision and strict transient flag. Live deltas
carry these fields without creating durable facts; post-call projection files only
canonical messages. The durable consumer reloads a validated message and still
checks the exact organization/conversation/session relationship. Invalid historical
metadata is refused with a safe error, never guessed or used to widen authority.
Live capture drafts, sequenced items, and snapshots are validated Pydantic models.
Raw payloads are excluded from generic dumps and repr output; returned items and
snapshots do not share mutable payload containers with the owned buffer. Invalid
or non-finite capture marks the buffer incomplete without stopping normal live
turn completion. Post-call projection validates redactor output, keeps terminal
speech outcomes as enums, and persists only the canonical content. Content-free
failure codes use `VoiceCanonicalFailureCode` through projection, DB readback and
API output, retaining their existing stored strings. Unknown historical failure
codes are refused rather than silently reclassified.
Framework responses use a kind-discriminated `ModelOutputBlock` union:
`ModelTextBlock`, `ModelReasoningBlock`, and `ModelToolCallBlock`. Tool blocks
retain the framework-owned `ToolCall`, rather than turning it back into an
untyped dictionary. Readers use `TypeAdapter(ModelOutputBlock)` or the enclosing
`ModelResponse`; producers construct the concrete variant. Returned responses
are revalidated before hooks, persistence callbacks, or execution. Duplicate
command IDs within a response are rejected, and reasoning is not visible text.
Tool block snapshots retain ID/name/arguments without private tool annotations.
Response snapshots embedded in message history are serialized in JSON mode;
Python tuples and enum objects must not leak into JSON-only message extensions.

Reported usage requires both input and output token counts as nonnegative
integers. Missing usage remains absent; it is not a fabricated zero-token report.
Adapters translate malformed counts to their existing typed response errors.
Gemini accumulates partial native usage updates until both primary counts are
known, retaining previously reported details without adding cumulative values
twice. The framework's `ModelUsage` still initializes accumulators and replay at
zero. Numeric `ModelSettings` are validated again before provider resolution.
Budget meters validate counts before opening a transaction; the existing active
budget scope rejects missing usage before returning canonical model output.
Task-local accounting scopes validate organization/run/job identities before
binding; nested scopes restore their previous owner even during cancellation.
Outstanding-capacity snapshots use nonnegative typed values in the budget's units.
Terminal message metadata retains `ModelUsage` until JSON serialization. Cache
and reasoning details remain separate; this does not change vendor pricing or
add those details again to the input/output total.

Vendor stream assemblers and the shared tool-call buffer are Pydantic models
with strict construction, forbidden extra fields and assignment validation.
Gemini's verified replay value is frozen. These are internal data contracts,
not resource owners: adapters still own clients, streams and cancellation.
Partial buffers may contain incomplete arguments, but only a validated terminal
batch becomes executable. Validation at native event ingress and final assembly
remains necessary; assignment validation does not validate mutations inside a
list or dictionary. Native SDK parts remain inside their vendor adapter.

Effective LLM generation, overrides, provider material and resolved run config
use frozen Pydantic contracts. Shared generation fields own scalar validation;
the LLM config domain still owns provider/model compatibility and supported
override selection. Existing instances are revalidated when entering these
contracts, including values produced by unchecked model-copy helpers. The domain
uses `LLMProviderConfig.from_storage` for stored config validation, not Pydantic's
legacy `validate` method. Credentials are copied into a read-only mapping and
excluded from repr and model dumps; a dump is not a credential-bearing restore
format. Durable work continues to resolve credentials by pinned config revision.

The shared LLM history projection recognizes split rows from the same model
response using a typed identity projection scoped to conversation/request/speaker.
Text filed between a command and its result is deferred in provider-bound history
until the pending results are included. Stored transcript rows are unchanged.
Unidentified or unrelated rows keep the existing conservative sequence handling;
missing results, duplicates, and orphaned results are still rejected. This avoids
mistaking a completed tool exchange for an abandoned command merely because the
model emitted text after a tool block. `ToolCallCompleteness` is an immutable
Pydantic result with nonnegative integer counts, not an unvalidated dataclass.

Active framework observations also have concrete variants: `RunMessageItem`,
`RunInputRequestItem`, and `RunApprovalRequestItem`. A message cannot stand in for
a malformed tool exchange or pause. Input and approval pauses retain typed request
objects and kind-specific continuations with the exact tool call ID. `RunResult`
validates these fields again when loading JSON. Product pipelines translate them
into owned request records; question text and response schema do not imply that a
framework tool has created a product request ID. Conversation message metadata is
serialized explicitly so nested request objects cannot leak into JSON-only fields.

Human answers are validated again when the AgentRun module loads a wait snapshot.
`AgentInputWaitState` retains custom JSON, including an answered JSON null;
`AgentApprovalWaitState` retains an `AgentApprovalResponse` and the module-owned
`AgentApprovalDecision`. Pending snapshots cannot be consumed as answers. Malformed
approval answers are refused before execution capacity is reacquired.
The module stores continuation JSON without depending on framework types.
`RunContinuation`, `ObjectiveRunContinuation`, and `ScheduledRunContinuation`
belong to the pipeline boundary: they validate the request kind and exact tool
identity before resume, preserving the existing persisted JSON shape. Non-finite
numbers are explicitly rejected in wait JSON; model configuration alone is not
relied upon across discriminated-union parsing.

Durable task payloads use `AgentRunTaskParams`: organization and run IDs only.
The workflow reloads the published revision and initiating principal before
constructing the validated `AgentRunExecutionClaim`. Its manifest is finite JSON;
each product pipeline owns the manifest's meaning. `AgentRunWorkflowReceipt`
contains only IDs and a valid terminal lifecycle/outcome pair, never product output.
`AgentRunInputEvent` carries the identity of an already-committed answer. All three
human-resume paths validate the same closed payload and retain exact canonical
UUID-string matching; the event contains no answer or execution authority.
General durable waits still return untrusted data for their owning consumer to
validate, since SOR command notifications are not human-input events.

Critical `RunCallbacks` are frozen Pydantic configuration, separate from the data
observations. They retain live callable identity and are excluded from repr,
snapshots and JSON Schema. Errors still stop the run, cancellation still propagates,
and best-effort lifecycle hooks keep their separate failure behavior. Pydantic
checks whether callback values are callable, not whether their signatures are
correct; the local type gates and invocation checks cover that contract.

Framework tool observations retain `ToolCall`/`ToolResult` payloads through a
kind-discriminated `RunItem` union. Producers construct `RunToolCallItem` or
`RunToolResultItem`; active non-tool observations use the concrete variants above.
`RunSignalItem` is reserved for kinds without active producers. Readers use
`TypeAdapter(RunItem)` or the enclosing `RunResult`, rather than constructing a
generic item with an unvalidated tool dictionary. Existing wire payload fields
are retained; private tool metadata is excluded before serialization, and tool
payloads are excluded from repr output. Other signal payloads and producer
extension fields still require their own schemas.
Voice history uses those typed calls/results without inventing identifiers or
empty arguments. Platform policy speech remains in the session-local capture for
audit/projection, but is not sent to the next model as an agent/tool message.
The metadata serializer omits unset fields without changing their declared shape.
Its JSON-schema hook preserves those named fields in generated response types;
extension validation happens before assignment so a refused update cannot leave
an invalid extension attached to the model. In-place edits to nested containers
are not intercepted by assignment validation.
Python-mode metadata retains typed UUIDs; JSON serialization emits their strings.
The serializer's output annotation accounts for both representations.

`SessionContext` is a validated, mutable composition of already-authorized session
facts. Session hydration constructs it explicitly rather than using unrestricted
`model_copy(update=...)`. WebRTC enrichment retains inherited organization, contact,
visit, voice and bounded Agent/conversation identity; it does not authorize a peer.
Auth and live session references retain their identity but are excluded from
model dumps, repr and schemas. Runtime-checkable protocols establish the required
interface, not the validity of every mutable field on the underlying resource.
The context is private runtime state, not a public response or persistence DTO.
HTTP dependency and WebSocket connection hydration are wired; the telephony and
WebRTC composition helpers currently have no production callers. Native session
state and voice resource contracts remain part of the later voice typing flow.

Conversation-start and message request context must be an object containing finite
JSON values. The shared sanitizer preserves its existing depth, string, collection
and serialized-size limits without converting Python objects to strings. Logs
record counts, not customer key names or nested paths. HTML stripping bounds the
presentation surface; it does not make customer instructions trustworthy.

Conversation prompt composition uses pipeline-owned projections for agent details,
interaction facts, recalled memories and unresolved conflict pairs. UUIDs and memory
levels remain typed until the final escaped JSON projection. Memory scope owners,
provenance, provider metadata and credentials are not included; customer-supplied
conversation context remains open JSON and is explicitly labelled untrusted.
Recall queries use each user content type's canonical text method, including
structured widget submissions. A widget response must not be treated as a list of
text blocks or silently replaced by an older user's message. Optional memory
failure still does not interrupt a turn; cancellation still propagates.

These callers use a pipeline-owned `BackgroundPrompt` and domain-owned
`LLMOverrides`. Token estimates keep components separate from a derived total.
Summary metadata is typed until it crosses the message JSON boundary; its exact
cursor and previous-summary link retain the existing storage shape.
`BackgroundTaskOutcome` distinguishes completed work from an intentional skip;
it does not replace the durable Agent-run lifecycle. Prompt-only background
runner transactions and the existing Redis mutex's expiry behavior remain
separate follow-ups in the [typing plan](../plans/python-typing.md).

Conversation, live voice, prompt-only background, scheduled, and objective
models use the domain-owned `ResolvePinnedLLM` callable. Generation overrides
are `LLMOverrides`; pipeline caching and inference mode use explicit enums.
The framework keeps its own `ModelSettings`, with translation at the pipeline
boundary. There is no second generation-override dictionary.

Framework streaming and prompt caching use distinct `RunStreaming` and
`RunPromptCaching` choices. Python callers supply enum members; JSON snapshots
retain their existing boolean values. Pipelines translate into their own LLM
enums rather than testing enum truthiness or importing platform types into the
framework. Explicit run-level caching still takes precedence over model settings.
`max_handoffs`, `handoff_lookback_window`, and `tracing_enabled` remain reserved:
their schemas mark them experimental because the loop does not implement them.
Lifecycle hooks run independently of the reserved tracing choice.

Platform agent/tool metadata retains `AgentStatus`, UUID identities, and positive
integer revisions. The pipeline explicitly translates platform tool kinds and
execution policies into the framework's separate enums. Code-defined tools keep
their deployed definition key; handoffs keep a target-agent revision, not a tool
revision. Approval summaries accept UUID identities and serialize them as strings;
only argument names/counts, never argument values, enter the redacted payload.
A framework-only tool without a supplied identity receives an organization-scoped
deterministic UUID. An invalid supplied identity is rejected, not replaced.

Conversation input and message projections retain UUID request correlation through
live-voice history, handoff refresh, and private durable replay. JSON snapshots
retain string IDs. Known tool-call arguments and result bodies are finite JSON;
result batches retain their ordering and scalar/null payloads. Copied tool metadata
is validated before conversion to provider-bound messages. Metadata extensions
remain open where their owner permits them, and excluded fields are not promoted
to public extras during refresh. These contracts do not replace organization or
published-revision authorization at execution time.

Generated next-turn history uses framework-owned call, result and provenance
models. Scheduled and objective resumes share a pipeline helper that builds the
same call/result pair; the helper does not own persistence, retries or transient
message counts. Invocation history contains only the call ID, name and arguments,
not executor annotations. Terminal-only output and owner-excluded fields stay out
of provenance snapshots. The framework accepts caller-owned string/UUID request
correlation; platform consumers enforce their UUID contract.

Model provenance keeps one typed `ModelResponse`. The existing flattened fields,
`llm_response` and `model_response` remain serialization projections for current
history readers, not independently maintained response dictionaries. Conversation
pipelines translate these models into the existing message metadata envelope;
common message and socket contracts do not import framework-specific types.

Tool completion now has an explicit `ToolCompletionMode`: continue or complete.
The framework accepts exact legacy boolean snapshots, but rejects truthy strings,
numbers and objects. Executor results are validated before result callbacks;
completed runs retain a typed command identity rather than reading control keys
from arbitrary metadata. Widget artifacts stay opaque to the framework. The
conversation pipeline validates their UUID and existing conversation, request,
message-kind and Agent-run ownership before reusing a delivered message.

Final-message metadata has one typed `run_metadata` authority. Existing top-level
pause/completion fields are serialization mirrors, not independent inputs on
readback. Replay responses still omit null model fields; arbitrary JSON nulls and
canonical run-metadata nulls keep their existing meaning. Objective completion,
captured turns and persisted summaries also use Pydantic; objective output stays
finite JSON within the existing 65,536-byte encoded-result limit. These contracts
do not add tables or replace durable execution, budgets or authorization.

Handoff outcomes have typed target and participant references with matching
published revisions. Their existing snapshot flags are checked serialization
mirrors, not independent instructions to switch agents. Text refresh validates
the whole result batch first. Decomposed live capture retains the source actor
for the handoff call/result and attributes subsequent output to the proven target.
These checks establish reference agreement; dispatch still owns authorization.

Realtime adapters emit ten explicit normalized event variants. The manager
revalidates their payload/tag agreement before effects. Audio remains native bytes;
only configured 16/24 kHz paths enter playback. Runtime callbacks are excluded from
snapshots, and their scheduled tasks consume success, failure and cancellation.
Gemini's `time_left` is translated from protobuf duration seconds into milliseconds,
not read from an invented SDK field. Transcript fragments append even when the SDK
marks its stream finished; the normalized final flag means replacement text.
See [Gemini session management](https://ai.google.dev/gemini-api/docs/live-api/session-management)
and [protobuf duration encoding](https://protobuf.dev/programming-guides/json/#representation-of-each-type).

Realtime provider resolution produces frozen Pydantic inference settings and
typed API-key or AWS credentials. Stored JSON field names remain unchanged;
the module translates them at runtime hydration, checks provider policy, and
requires the effective record's org/config IDs and capability to agree. This
does not grant access: revision and grant resolution remain module-owned.
Credentials are excluded from model representations and dumps, then read as
typed fields only for adapter construction. STT/TTS resolution now follows the
same pattern, with typed inference settings, API-key/AWS/Google credential
variants and checks against the requested config ID and pinned revision. Runtime
snapshots must already contain normalized settings. `VoiceProviderConfig` is now
a frozen Pydantic carrier: `from_storage()` validates the stored envelope and
hydrates typed STT, TTS or realtime settings. Realtime keeps transport region
separate from inference. All three runtime hydration paths revalidate the carrier
and keep settings objects rather than reconstructing them from dictionary keys.

`to_storage_config()` is the explicit JSON boundary for create/update. It preserves
existing field names, absent values and false/zero settings; in particular,
`context_compression_enabled` remains the stored spelling. The returned projection
is independent of the immutable settings. Plaintext secret values remain in an
immutable private mapping, excluded from representations and model dumps; existing
provider-specific credential validation still applies. The carrier introduces no
DB schema change, provider defaults or new authority.

The shared `ProviderConfig` aggregate and `EffectiveProviderConfig` snapshot also
use revalidated Pydantic models. Their settings and verification metadata accept
finite JSON values only. This envelope deliberately does not import a capability's
settings model: capability modules validate meaning before persistence and again
when resolving executable material. IDs, revisions and predicate flags are strict;
verification timestamps must be timezone-aware. Existing current/pinned revision
and grant policies are unchanged.

Lifecycle methods reconstruct and validate the aggregate, explicitly retaining
its private credentials. Secrets are excluded from representations and dumps;
the repository still reads them explicitly for context-bound encryption. Config
and metadata mappings are read-only at their outer boundary, with nested JSON
copied during validation. This is not recursive immutability: nested containers
remain JSON lists/maps for existing capability consumers. No schema migration is
required.

The provider-config repository revalidates incoming aggregates before writes and
uses typed JSON columns. Revision/header updates return their affected config ID;
an absent result is a revision conflict. This retains the existing short,
caller-owned transaction and row-lock boundaries.

`EncryptionContext` validates org/resource UUIDs, purpose and positive revision,
including when an existing instance is reused. Its associated-data encoding and
the `v1` AES-GCM envelope remain unchanged. Purpose labels stay caller-owned:
MCP headers and external-account credentials do not become provider capabilities
merely because they share the cipher. The cipher returns finite JSON; provider
readback separately validates its string-secret contract. JSON decoding is followed
by Python-side validation because this Pydantic version's direct `JsonValue` JSON
parser accepts non-finite numbers. Config snapshot imports apply the same guard.
Malformed plaintext and invalid UTF-8 fail with value-free encryption/decryption
errors, rather than exposing decoded credential content.

STT/TTS verification, capability inspection and browser/carrier setup share
pipeline composition. A transport contributes only a typed sample rate and codec;
it cannot replace the selected model or credentials. Provider policy distinguishes
overlapping field names: ElevenLabs `style` is numeric, while Murf `style` is text
and its `pitch` is an integer. See [ElevenLabs voice settings](https://elevenlabs.io/docs/api-reference/voices/settings/get)
and [Murf speech customization](https://murf.ai/api/docs/capabilities/text-to-speech/speech-customization).
The existing STT/TTS factories still receive an explicitly serialized mapping;
their native options, requests and events are a separate adapter boundary, not
implicitly validated by the resolved-material contract.

The TTS factory selects its implementation through the socket-owned `TTSProvider`
enum and yields `TTSVendorAdapter`, not a vendor's WebSocket/client handle. The
remaining mapping-based config carrier is not a substitute for native validation.

TTS normalization accepts flat settings or nested `options`, but rejects
conflicting duplicates and nested provider/retry controls. An explicit API-key
argument replaces the normalized credential before constructing any adapter.
Implicit media defaults do not override explicitly supplied nested media options.
The voice runner passes the normalized object to the factory rather than
serializing it and reading its provider identity back from a dictionary.

OpenAI, Deepgram, Groq, Rime, Smallest, Hume and Murf each own a frozen Pydantic
config model. Their shared `TTSAdapterConfig` removes only canonical envelope
fields during projection; remaining unknown native settings fail validation.
Numbers, strings and policy flags are checked without accepting numeric strings
or booleans as numbers. API keys are absent from native config repr/dumps, copied
models are revalidated, and voice aliases are properties of a single stored
value. Hume instant mode and Smallest WAV-header policy use the shared speech
option enum internally. Hume projects it into a handshake query parameter;
Smallest sends the vendor-required JSON boolean.

Hume's native WebSocket uses top-level text, voice, description and speed fields,
not the HTTP API's utterance-list envelope. Model selection maps explicitly to
the handshake's Octave version; PCM and JSON-only output are requested there.
The API key is a header and never part of the URL. Each turn owns a native stream.
Finalization sends `close: true`, which requests generation of buffered text and
closes the stream after its output is sent. Only a normal close after end-input,
received audio and complete snippets marks the turn drained. A snippet's last
chunk alone cannot finish the turn. Interruption retires the stream before close;
the next turn opens another. See [Hume streaming input](https://dev.hume.ai/docs/text-to-speech-tts/quickstart/typescript)
and the checked [native SDK input contract](https://github.com/HumeAI/hume-python-sdk/blob/84e24b3be3e8e53df94bf23c28d9191aaa1217c0/src/hume/tts/types/publish_tts.py).

Hume audio is validated as base64 PCM and reported as its actual 48 kHz mono
format. Vendor error text and audio are excluded from diagnostics. Polling
cancellation keeps the stream usable; uncertain sends retire it, and bounded
close tasks retain cleanup ownership. See [Hume audio constraints](https://dev.hume.ai/docs/integrations/livekit).
Legacy Hume language/sample-rate inputs are not native selectors. Onboarding
cleanup and library-versus-custom voice selection remain pending. Live vendor
and human browser voice QA are also pending.

Browser playback, realtime output and recording share the pipeline-owned
`BROWSER_OUTPUT_AUDIO_FORMAT`: 16 kHz mono PCM S16LE. Browser setup supplies it
as the TTS manager's consumer format. The manager reads actual native format
from its adapter, validates chunk format agreement, and converts before sending
identical bytes to the playback queue and recording callback. The recorder no
longer guesses native rates from vendor/config dictionaries.

Streaming conversion retains filter state within an utterance. On successful
native completion, the manager emits the resampler tail before reporting that
the producer is drained. Interruption/failure discards that tail. Dequeue and
conversion happen without an intervening task scheduling gap. These rules are
verified locally through the real factory, native Hume adapter, running TTS
manager, browser setup, playback buffer and WAV writer using controlled transport
input; they do not establish live vendor acceptance or audible browser quality.
See the [SoXR final-chunk contract](https://python-soxr.readthedocs.io/en/latest/soxr.html#soxr.ResampleStream.resample_chunk),
also checked against installed SoXR 1.0.0.

Omitting a consumer format retains the native output contract. Telephony supplies
the active carrier's format to this same TTS manager, so native completion and
interruption also own carrier conversion. The carrier producer sends already
converted bytes; it records only accepted carrier writes, including comfort
audio. Recorder metadata comes from the checked input and consumer formats,
not guessed defaults. The Pydantic `VoicePipelineBundle` preserves live queue,
task and service references but excludes them from snapshots and JSON schemas.

`CallSession` validates the handoff's live handles and retains immutable
organization/carrier/call identity. Registry removal is instance-specific: an
old or cancelled session cannot unregister a replacement with the same key.
Unscoped carrier-ID lookup refuses ambiguity across organizations. Active media,
termination request and finalization progress use explicit pipeline-owned enums;
a failed finalization remains retryable. Campaign references stay UUIDs through
call creation and become strings only in event JSON. Auth routing tokens and
runtime handles are excluded from session snapshots and schema projections.
These are process-local contracts, not cross-worker session ownership.

Realtime output pins the normalized event's actual PCM sample rate for each
turn. Completion flushes conversion before awaiting tools/hooks; interruption
discards buffered samples. Output uses an explicit accepting/suppressed/closed
state, and shutdown retires it before awaiting provider close. A completed or
interrupted turn cannot leave filter history in the next turn. Unsupported
rates, incomplete PCM samples and mid-turn rate changes fail at this boundary.
Empty converted output is not queued or recorded; rejected queue writes are
not recorded. These contracts have local normalized-event and four-carrier
media-serialization checks, not live provider/call proof. Broader response-ID
correlation, reconnect continuity, native carrier envelopes and broader browser/
WebRTC session-state contracts remain open.

This validates construction, not every native protocol. The generic `TTSConfig`
carrier still holds open option/format mappings; Polly/Sarvam native options,
remaining provider requests/responses and lifecycle behavior need their own
validation. Controlled transport checks do not establish live vendor acceptance.

Cartesia's TTS adapter uses frozen native config/request/output models. A speech
turn owns a context on the persistent socket; subsequent turns never reuse a
completed context. Eylo finalization sends empty text with `continue: false`,
not a nonterminal vendor flush. Interruption retires the context before sending
native cancellation. Since Cartesia may still emit already-generating audio,
the adapter discards retired-context audio, errors and completion frames before
they can affect the active turn. See [Cartesia contexts and cancellation](https://docs.cartesia.ai/use-the-api/tts-websocket/contexts).
Input settings remain fixed across the turn. Explicit speed is sent through
`generation_config.speed`; support depends on the selected model. Cartesia
currently documents speed as unavailable on Sonic 3.5, while Sonic 3 snapshots
support it. No model is silently substituted. See [Cartesia generation controls](https://docs.cartesia.ai/build-with-cartesia/capability-guides/volume-speed-emotion).
The API version remains pinned in the adapter; the API key is a handshake header,
not part of the URL. Invalid native output fails synthesis without exposing vendor
error bodies. Polling cancellation preserves the connection; uncertain sends
retire it, and bounded close tasks retain cleanup ownership.

The ElevenLabs TTS adapter now validates its native settings, initialization,
text/end-input requests and consumed output frames with frozen Pydantic models.
Only its explicit wire serializer exposes the credential. Invalid base64 and
malformed terminal flags fail the turn rather than becoming silence or completion.
Final frames can contain audio; that audio is delivered before completion is
observed downstream. Native alignment extensions are not consumed by this path.

Each ElevenLabs single-context stream ends with an explicit empty-text command.
After final output or interruption, the next turn opens a new stream with the
same configured model, voice and credentials. This does not preserve native
cross-turn synthesis context. Buffer flushing alone is not treated as proof of
completion. See the [ElevenLabs WebSocket protocol](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tts).
Read polling can be cancelled without closing the socket; acquired sockets and
late close tasks retain cleanup ownership. Failed TTS operations stop the runtime
and report one failed outcome, rather than restarting a reader against a failed
stream or replaying possibly emitted speech. Shared task teardown also collects
already-failed children and propagates caller cancellation.

Speech producers use the pipeline-owned `TTSTextRequest` / `TTSFinalizeRequest`
union. The Redis envelope validates organization, conversation, request and turn
identity before session routing; the queue revalidates copied input before any
playback state change. Text remains absent from model representations and
validation-error strings. Policy speech keeps its source enum through live
capture. Provider adapters receive text, not platform routing envelopes.

Streamed and complete LLM responses both finalize their text. Changing the active
turn stops current synthesis without discarding the next turn's queued segments
or finalize marker. An explicit user interruption also clears pending input.
Finalization must match both turn and request identity; it is not proof that audio
has drained. The audio queue retains `TTSAudioChunk` until projecting bytes into
the existing playback/recording path. Queue metrics use the existing typed snapshot.
Native factory/options, remaining adapters and broader concurrent lifecycle
verification remain work in the [typing plan](../plans/python-typing.md).

Voice supervisors register zero-argument coroutine factories and retain the
replacement tasks in their owning registries. The shared monitor never restarts
cancelled children or treats their cancellation as cancellation of the supervisor.
Only explicitly restartable failures are eligible; every supplied restart
predicate must pass, and predicate errors veto restart. STT runtime cancellation
propagates to its caller after cleanup. Queue teardown waits for acknowledgements
with a per-queue timeout; it does not consume or discard the queued payloads.
The WebSocket controller does not run a second, empty voice-task supervisor.

Recognition stays as a validated `STTEvent` through the STT factory/runtime queues.
Event kind determines finality; connection acknowledgements do not become speech,
and vendor metadata cannot overwrite canonical fields. Debounce batches retain
each final segment's identity and timing. Completed DTMF input is a separate
pipeline-owned contract, correlated against the actual live buffer.

The shared STT configuration is a frozen Pydantic contract. Provider, encoding,
turn detection and endpointing choices retain enums; configured feature policies
reuse the common speech-option enum and serialize to their existing booleans.
The runtime retains the factory's validated config rather than rebuilding it from
an incomplete dictionary. Native options accept validated JSON, remain excluded
from ordinary model dumps/representations, and are exposed only by explicit adapter
handoff. Conflicting flat/nested values are rejected before provider I/O.

Incoming transport `encoding` and vendor `input_audio_codec` are not synonyms:
an adapter may convert between them. Likewise, Listen's `utterance_end_ms` does
not configure Flux's `eot_timeout_ms`. Native request validation belongs in each
adapter. Factory capability inspection uses the selected adapter's declaration,
not a duplicate capability table; support is an explicit enum with boolean JSON.
STT metrics validate counts and event kinds and retain process-monotonic seconds.
The factory consumes `RetryOptions` for connection establishment, including an
explicit reconnect: `max_retry` counts additional attempts, `timeout` covers each
connect/readiness attempt, and `retry_interval` follows successful cleanup. Both
durations are seconds. `STTConnectionFailed` carries a socket-owned failure-kind
enum. Only network, timeout and service-unavailable kinds (plus the owner's own
timeouts) enter that loop; unknown failures and other native/validation errors
stop. Failed-attempt cleanup has a separate
ten-second cooperative deadline. Cleanup failure stops further attempts with
`STTConnectionCleanupFailed`; caller cancellation remains cancellation. A failed
close retains the factory's adapter handle instead of pretending it closed.
`STTConnectionRetryUnsafe` preserves a known cause while refusing another startup
attempt even when that cause is otherwise retryable.

Readers start only after readiness; the connection-attempt loop never sends audio.
Adapter base classes no longer hold a second, unused retry configuration. Active
stream recovery is not yet unified: the runtime still has its send-retry policy,
the task supervisor has restart rules, and some native adapters reconnect
internally. Those paths, serialized reconnect ownership and uncertain-write replay
remain in the typing plan. As with Python's [asyncio timeout contract](https://docs.python.org/3.13/library/asyncio-task.html#timeouts),
deadlines require cooperative coroutines; they cannot forcibly stop blocking code
or a coroutine that never returns after swallowing cancellation.

HTTP/WebSocket establishment errors are translated inside the Deepgram Listen,
Flux, Speechmatics, AssemblyAI, Cartesia, Sarvam, Gladia and RevAI adapters.
Authentication, authorization, TLS, malformed handshakes and rejected requests
stop instead of becoming generic retry signals. HTTP 429 remains a distinct
rate-limit refusal: the fixed-delay establishment loop does not implement the
provider-specific delay/admission policy needed to retry it. Known network failures
and HTTP 500/502/503/504 permit bounded retry after cleanup, following the
[websockets 15.0.1 transport classification](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/client.html#websockets.asyncio.client.process_exception),
with stricter handling for TLS, invalid DNS names and unrelated OS errors.
Unknown exceptions and mixed exception groups are not flattened into retryable
failures. Adapter cleanup errors, including cleanup timeouts, use
`STTConnectionCleanupFailed`, never the connection-timeout category. Retry logs
contain the failure kind, not vendor response text or credentials.

Deepgram Flux uses [Listen v2 messages](https://developers.deepgram.com/reference/speech-to-text/listen-flux),
not the Listen v1 envelope. Vendor-owned tagged models distinguish connection,
turn and error messages. Turn events map directly to canonical observations;
partial/eager text is not final, and disabling interim results suppresses Update
observations. During an open stream, only EndOfTurn produces a final transcript.
Requested stream shutdown has a separate finalization contract below. The pipeline applies
interruption policy. Native request ID, turn/sequence metadata, audio windows and
word timing/confidence survive translation; turn-ending confidence is not speech
recognition confidence. Optional older word timing stays absent. Malformed and
error messages fail visibly without exposing provider diagnostic text.

Readiness requires the native Connected acknowledgement, not only the HTTP upgrade.
The typed stream cursor binds subsequent turns to that request ID and rejects
duplicate/backwards sequence values or another Connected response. It requires
increasing values, not contiguous numbering. Interim-output filtering happens
after cursor validation. Failed/cancelled startup owns cleanup before returning
to the factory; a fully disposed no-audio timeout may use its bounded retry path.

Flux's consumed config is frozen, excludes its secret from dumps and validates
model, raw-audio encoding/rate and vendor EOT limits before I/O. A typed query is
URL-encoded; shared PCM encoding translates to native linear16. Shared runtime
policy is not automatically forwarded as vendor parameters. Existing Eylo EOT
defaults are retained, not replaced with vendor defaults. Container auto-detection,
language hints and eager mode are not enabled by this change.

The unused generic STT dict-event bridge has been removed. Flux has one owned
connection/close operation, one native reader and serialized input. Cancelling a
consumer wait leaves that reader alive. Unexpected EOF and uncertain sends stop
the stream instead of silently reconnecting
or replaying input. Failed cleanup retains the socket; explicit retry disposes
that same resource without repeating the application close signal. Cancelling a
close waiter does not cancel the owned cleanup. Failed close-signal delivery is
reported separately from failed physical disposal.

On [CloseStream](https://developers.deepgram.com/docs/flux/close-stream), Flux
emits buffered Updates then EOF, not another EndOfTurn or a separate completion
acknowledgement. The adapter sends CloseStream once, waits a bounded time for its
reader, then closes the transport. Requested EOF promotes the latest nonempty,
unfinished hypothesis to a canonical final with `finalization_reason=CloseStream`;
it does not fabricate a native EndOfTurn or duplicate an already-final turn.
Disabling interim output does not discard this buffered final.

A bounded output queue and one retained pending event preserve acquired output
under backpressure. The adapter remains readable after physical closure until
queued output/errors are consumed; the shared factory owns downstream delivery.
Timeout, malformed tail or unexpected EOF is a visible failure, not a fabricated
final. The native protocol supplies no stronger close acknowledgement, so EOF
following a successfully sent CloseStream is the available completion signal.
Local TLS, queue and transcript-consumer checks are not live-vendor/browser
acceptance or proof of canonical DB persistence.

Flux no longer advertises the inert `high_vad_sensitivity` field. Validation
accepts older saved configs containing it, then removes it from effective config;
no DB rewrite is required. Sarvam's independently owned option is unchanged.
STT capability projections serialize the adapter's Pydantic model into the public
JSON read model, preserving boolean support values and encoding/rate lists.

Gladia uses its [Live v2 protocol](https://docs.gladia.io/api-reference/v2/live/init):
configured language/audio settings → authenticated session-creation POST → the
returned credential-bearing WebSocket URL → matching session acknowledgement.
Frozen vendor request/response models stay inside the socket boundary. The URL
is excluded from model dumps/representations, pinned to Gladia's documented
destination and cannot redirect. Unlike one-step establishment, an uncertain
session POST cannot safely be repeated: this adapter refuses replacement after
an unresolved attempt, even if the underlying cause is normally retryable.

Binary PCM sends apply backpressure. Normal shutdown flushes the buffered tail,
sends `stop_recording` and keeps the reader alive for final transcripts and
`end_session`, following the [native event contract](https://docs.gladia.io/api-reference/v2/live/websocket).
Cancellation during a send leaves delivery uncertain; the attempt fails and
cleanup does not send those bytes again. Socket closure without final completion
is not success. The canonical event preserves text, missing/zero confidence,
word timing, language and session identity; a channel is not a speaker and no
model identity is fabricated. A returned transcript is distinct from proof that
the platform has persisted it or delivered it to a browser.

Sarvam's existing adapter uses the [legacy streaming endpoint](https://docs.sarvam.ai/api-reference/legacy/speech-to-text/transcribe/ws),
not its newer realtime STT endpoint. Resolved config is frozen; credentials are
excluded from repr/serialization and used only in the handshake header. A typed
query plus the installed SDK's audio/flush models define outgoing messages.
Vendor-local tagged models validate incoming transcript, VAD and error envelopes;
the SDK's permissive untagged response union alone cannot prove their pairing.
Canonical transcripts preserve text, request ID, language and metrics. Language
probability is not recognition confidence, duration is not an audio offset, and
legacy finals are not advertised as partial transcripts. Malformed/error responses
raise a safe terminal error rather than looking like silence. The receiver does
not reconnect or swallow cancellation. Audio and flush sends are serialized;
failed/cancelled writes invalidate the stream instead of authorizing replay.
Shutdown owns a retained, shielded close task: timeout or physical close failure
does not clear the socket reference or permit a replacement. The shared send
retry guard rejects classified establishment failures (including retry-unsafe
failures) and cleanup failures; older generic-error retry paths still require
separate migration to explicit not-sent outcomes.

Sarvam's public `flush()` sends the documented flush frame when enabled. The
legacy protocol does not document a flush-complete acknowledgement, so sending
that frame does not prove all final text was received. Disconnect currently
closes resources, not a guaranteed final-output drain. Finalization and configured
provider/browser acceptance remain open; local transport checks do not close them.

Amazon Transcribe now validates consumed options with a frozen Pydantic model and
keeps AWS request, output and event types inside the adapter. Credentials are
excluded from model dumps and representations. The installed SDK's enums accept
unknown values for response compatibility; outgoing language and stabilization
choices are checked against its declared members.

An attempt owns its SDK startup, sender, receiver and cleanup tasks. Cancelling an
Eylo waiter does not cancel CRT's callback-owned futures. The public interceptor
hook observes request failures that smithy-core 0.6.0 otherwise leaves behind an
unfulfilled startup future. A per-call plugin installs that observer after the
SDK copies its config. The same per-call hook installs an attempt-owned HTTP/2
transport. It uses CRT's HTTP/2-specific stream: in installed CRT 0.32.2, the generic
async stream's request-body method is empty. AWS's SDK still serializes and signs
requests and encodes/decodes events; Eylo owns the connection, native writer and
completion tasks. The transport requires HTTPS, verifies certificates, validates
header characters and replenishes a bounded response flow-control window as data
is consumed.

Partial-stream cleanup closes input before waiting for response setup and pending
reads. After a two-second grace period, physical connection shutdown unblocks
unfinished I/O without cancelling CRT callback futures. Cleanup also shuts down the
connection on a normal finish. A five-second caller deadline reports incomplete
cleanup without cancelling or discarding the cleanup task. Late acquisition remains
owned; further connects cannot replace a stream whose cleanup has not succeeded.
Shutdown completion, not merely `is_open() == False`, establishes disposal, following
the [CRT connection contract](https://awslabs.github.io/aws-crt-python/api/http.html#awscrt.http.HttpClientConnectionBase.shutdown_future).

Native EOF is distinct from failure. Queued transcripts and terminal failures stay
readable by the factory; modeled exceptions retain socket-owned categories. AWS
request/session IDs come from response headers, while result/channel IDs stay in
typed vendor metadata. Word-level speaker labels are retained; mixed-speaker
segments are not attributed to the first speaker.

This does not complete native lifecycle typing. AWS physical connection shutdown
has been exercised through the real SDK and CRT against a local TLS/HTTP2 peer;
the same peer now emits its last transcript only after signed input EOF. That
transcript reaches the factory, runtime debounce batch and a live rollback consumer
before shutdown completes. Live AWS acceptance, browser/carrier interaction and
canonical post-call persistence remain unverified by these local checks.
Native AWS startup failures use `STTConnectionRetryUnsafe`: their diagnostic cause
is preserved without adding service-error retries. The existing factory-owned
timeout policy remains distinct and still requires successful cleanup. Native
protocol refusals after a successful upgrade and the adapters' internal reconnect
loops also remain in scope. HTTP classification is not proof that these paths are
safe to replay or that every native close releases all resources.

Google Speech v1 uses `SpeechAsyncClient` with a native asynchronous request
iterator. The former synchronous client could not consume that iterator with the
supplied signature; a background retry loop hid the resulting `TypeError` behind
a connected flag. A frozen `GoogleSTTConfig` now validates consumed options and
excludes credentials from representations and serialization. Each attempt owns
its async client/channel. The first request contains only recognition settings;
later requests contain PCM16 audio. Readiness waits for SDK connection
establishment, not the first transcript: a silent stream may produce no text.
Transport readiness alone does not prove the service accepted credentials or
settings; verification must also finish the RPC without a terminal error.

Google's native protobuf responses stay inside the adapter until conversion to
`STTEvent`. Finality, leading whitespace, word timing, detected language and
channel/stability metadata retain their meaning. Zero confidence/stability
sentinels remain absent rather than becoming measured zeroes. Alternative
languages are sent only when enabled, within the vendor's three-language limit;
Google documents this feature for voice-command/search use cases, not unrestricted
language detection. See the [Speech v1 RPC contracts](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v1)
and [async client interface](https://docs.cloud.google.com/python/docs/reference/speech/latest/google.cloud.speech_v1.services.speech.SpeechAsyncClient).
The implementation was checked against installed `google-cloud-speech` 2.35.0.

Google shutdown half-closes input while readers remain active, allows two seconds
for final output, then closes the native channel and joins owned tasks. A five-second
caller deadline reports unproven cleanup without discarding its task. SDK errors
from both sending and receiving become socket-owned failure kinds. Restarting a
reader on the same failed RPC is not recovery: factory supervision exposes the
terminal cause, while bounded connection retries remain a separate authority.
Local TLS/gRPC checks exercise native serialization, EOF-only final output,
authentication rejection, hangs, cancellation and the real verification function.
They do not establish live Google acceptance or canonical post-call persistence.

Rev AI Streaming v1 uses frozen vendor-owned query/config models and a
discriminated connected/partial/final response union. The configured language is
sent explicitly; credentials are URL-encoded only at the server-side connection
boundary. Audio admission waits for the vendor's `connected` acknowledgement.
Partial words are space-separated; final punctuation already supplies spacing.
Word timestamps and confidence remain distinct from absent transcript confidence;
an unspecified model uses the canonical empty value, not an invented model name.

Rev AI audio sends await WebSocket backpressure without an extra audio queue.
Shutdown sends the documented `EOS` text frame while the reader remains alive,
allows two seconds for final output, then closes the socket and joins owned work.
Close-code failures retain socket-owned categories and do not authorize replay of
uncertain audio. Failed cleanup remains owned rather than being replaced on the
next connect. See the [native request contract](https://docs.rev.ai/api/streaming/requests)
and [response contract](https://docs.rev.ai/api/streaming/responses).
Local TLS/WebSocket checks exercise the real adapter, factory, runtime final batch
and verifier; live Rev AI acceptance and canonical DB persistence remain unverified.

STT queues await downstream acceptance. Debounce clears its buffer only after
that acceptance; bounded shutdown still closes the provider if final delivery
fails. AWS input completion is separate from physical close: the receiver stays
alive for up to two seconds to collect final output. `STTFinalizationFailed`
means resources closed but output production or forwarding was incomplete; it
does not authorize a connection retry. `STTConnectionCleanupFailed` remains the
distinct failure to establish resource disposal. Factory forwarding has its own
bounded final-delivery wait and retains an acquired event blocked by backpressure.
It refuses replacement while that event is undelivered. Shutdown reads child
tasks from the supervisor's canonical registry, including replacement tasks, and
refuses reconnect/audio admission after closing begins.

Failed telephony startup stops synthesis work, finishes recognition while its
transcript writer remains alive, then bounds queue draining before stopping that
writer. Both providers get a cleanup attempt even when another step fails. If a
writer was never started, unconsumed output remains explicit; a queue drain is
not evidence of canonical transcript persistence. Normal telephony call cleanup
uses its separate lifecycle drain, not this startup-rollback helper.

The factory surfaces a stopped reader's typed failure before its next supervisor
poll; it does not restart a reader against the same failed RPC. Runtime task
supervision retains its separately declared restart policy. Terminal receiver
failures cannot silently leave a healthy-looking runtime. These are live-session
guarantees, not durable delivery across process
death. Native provider wire/config typing remains tracked in the
[typing plan](../plans/python-typing.md).

AssemblyAI and Cartesia validate native response objects before canonical STT
translation. AssemblyAI waits for the vendor's Begin acknowledgement and avoids
emitting a second final transcript for a formatting update. Cartesia distinguishes
`finalize` from `close`; its flush/done acknowledgements are not speech activity.
Native word timing is preserved, and absent transcript confidence stays absent.
Canonical `linear16` is translated to these vendors' `pcm_s16le` wire spelling.

Cartesia final text is a delta. The STT event carries this distinction explicitly,
so debounce concatenates related deltas without introducing whitespace. Connection
identity stays attached through batching and live capture. A native connection
closing does not by itself mean its queued responses have been consumed. Native
close retains final output within a bounded drain, but complete delivery during
whole-call teardown remains a separate end-to-end verification item in the typing
plan. Protocol details stay in the
[AssemblyAI](https://www.assemblyai.com/docs/streaming/api-spec/streaming-websocket)
and [Cartesia](https://docs.cartesia.ai/2026-03-01/api-reference/stt/websocket)
adapters; voice policy remains in the pipeline.

Speechmatics follows the same native-contract boundary. Recognition readiness
waits for `RecognitionStarted`; early audio is not silently consumed. The complete
formatted transcript becomes canonical text, with per-word timings and speakers
kept separately. Multiple speakers in one segment do not become one attributed
speaker. Partials do not supply meaningful confidence. Its `ForceEndOfUtterance`
flush keeps the session open, while `EndOfStream` carries the exact sent-audio
chunk count. One bounded native response queue preserves output until consumption
or the bounded shutdown deadline. The
[Speechmatics v2 protocol](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket)
stays inside the vendor adapter; call policy and whole-call final delivery remain
pipeline responsibilities.

Deepgram Listen v1 validates native configuration, controls and responses before
canonical translation. Configured endpointing, VAD and utterance delay reach the
encoded query; credentials remain in the Authorization header. Segment finality
(`is_final`) is separate from a speech boundary (`speech_final`). Word timing,
request identity and reported usage survive translation. SpeechStarted timestamps
and UtteranceEnd's `last_word_end` are audio-relative seconds, never wall-clock
event timestamps.

Its native reader and JSON KeepAlive task share a task group. Connection readiness
requires the actual WebSocket upgrade; the factory owns recovery rather than a
second silent native reconnect loop. Finalize requests buffered results without
closing. CloseStream precedes a bounded final-result/metadata drain and resource
cleanup. Already-received output remains readable after native closure. These are
native stream guarantees, not proof that stopped upper-level call consumers will
deliver every final frame. See the
[Listen v1 reference](https://developers.deepgram.com/reference/speech-to-text/listen-streaming),
[Finalize](https://developers.deepgram.com/docs/finalize), and
[CloseStream](https://developers.deepgram.com/docs/close-stream).

Realtime session configuration extends those inference settings with session
identity, prompt and tools. Browser setup, credential verification and capability
inspection use one pipeline builder, which checks organization agreement before
adapter construction. Realtime session configuration is a frozen snapshot.
Session updates validate a full replacement before sending or disconnecting; a bad
field cannot partially replace the local prompt or tools. OpenAI retains its old
local snapshot if sending the update fails; successful send is not a server ack.
Gemini and Nova still reconnect for updates. The primary voice pin remains owned
by the conversation pipeline.

OpenAI realtime frames are validated inside its socket before event translation.
Native SDK models describe requests and consumed events; the adapter adds the
server session ID omitted by the pinned SDK's shared request type. Unused/future
event kinds are ignored. Malformed consumed events, invalid base64 and non-finite
or non-object tool arguments follow the existing fatal receive-error path, not
fabricated empty transcripts or tool inputs. Streamed calls must match their
originating response and output-item identity. Pending identities are removed
when arguments are consumed, their response ends, or the adapter disconnects.
The three existing pre-GA audio event labels remain supported at the parser
boundary. These contracts do not change the configured model or voice, grant tool
access, or replace the manager's teardown and transcript ownership. Function
results still become a new conversation item followed by a response request,
matching the [OpenAI realtime function flow](https://developers.openai.com/api/docs/guides/realtime-conversations#function-calling).

Nova Sonic uses adapter-owned Pydantic JSON events inside the Bedrock SDK's
native input/output chunks. Its [input protocol](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-input-events.html)
keeps setup, history, live audio, tool results and shutdown in ordered batches.
The [output protocol](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-output-events.html)
ties content to session, prompt and completion identities. Only final user and
spoken-assistant text enters transcript/replay; speculative speech does not.
Malformed tool arguments cannot become executable empty inputs. Tool results
must match a pending call. Unknown output event names are ignored; SDK error
variants are translated explicitly without exposing provider error text.

SDK EOF ends reception and lets the manager apply its existing transport-ended
lifecycle. Read and close operations are tracked with their actual result types
and shielded from caller cancellation because AWS CRT owns the underlying
response futures. Close also covers a receiver acquired after setup failure.
Caller wait is bounded; if the SDK stalls, cleanup remains tracked in the
background rather than being reported as completed. Reconnection does not allow
late events from the previous stream to reach playback or tool dispatch.

Realtime capability support and update strategy use socket-owned enums. Shared
inference contracts own endpointing and context-compression choices. Existing
API projections retain their boolean/string values;
internal code compares explicit members rather than enum truthiness. Tool records
remain instance-checked live references, not deep-frozen copies. See Pydantic's
[frozen-model semantics](https://docs.pydantic.dev/2.11/concepts/models/#faux-immutability).

The ordered model-to-speech path uses validated `VoiceTurnRef` and
`VoiceTextSegment` contracts. Correlation stays UUID-typed until transport delivery;
`VoiceTextPhase` distinguishes partial text from completion. Copied segments are
revalidated before filler/session/transport effects. The existing transport shape
is unchanged: text precedes finalize, IDs serialize as strings, and optional
uncorrelated delivery retains null IDs. Secondary thinking-state failure does not
block speech; cancellation and transport failures propagate. This direct awaited
path, not a lossy lifecycle event, owns speech order.

Run limits are strict finite values. A boolean or numeric string cannot become
a turn count or timeout. `RunConfig` is revalidated when the framework starts;
conversation run/resume wrappers also validate before hydration or resumed tool
execution. `AgentSpec` revalidates nested settings, including copy-built values.
Mutable `RunContext` checks config, agent and usage replacements on assignment;
live application dependencies retain their identity and stay out of snapshots.
Frozen fields do not make nested collections deeply immutable.

Framework exceptions produce `RunFailureMetadata` with a framework-owned
`RunFailureCode` and the exception class name, not exception text. Existing
`run_failed` / `guardrail_blocked` wire values are restored to typed metadata on
result readback. Failure categories must agree with the result status. Metadata
subclasses keep their field exclusions through validation and terminal-message
serialization; private runtime fields must not become unrestricted extras.

The production resolver does not retain a session. Without a caller transaction,
it owns a short read-only scope and closes it before returning immutable config.
With a caller transaction, it reuses that session without committing or closing
it; opening a nested session here would increase connection-pool pressure.
This does **not** shorten the existing outer runner transactions. Transcript and
tool dependencies must become independently scoped before those outer scopes can
be removed.

The shared DB boundary yields a native SQLAlchemy `AsyncSession` from a typed
`async_sessionmaker`; decorators preserve the wrapped async callable's argument
and result types. Post-commit notifications follow the session's actual
transaction/savepoint lifecycle. Releasing a savepoint transfers its event batch
to the parent; rollback discards it. Only a successful outer commit publishes
the batch. Explicit commits publish immediately, without waiting for the enclosing
scope to finish. Failed commits propagate rather than looking successful.

Publication clears the writer's session/event context while scheduling listeners.
Listeners must acquire their own session and cannot inherit the writer's queue.
These notifications remain best-effort and in-process, not an outbox or a durable
event-delivery guarantee. Session/event context is restored even when closing the
session fails. Each concurrent task still needs its own owned transaction; a
typed session is not safe to share between concurrent tasks.

Prompt-only background runs pass typed executable-agent, input, result, and
task-correlation contracts through the framework. Their private transcript keeps
three owned payloads: assistant text, tool call, and tool result. The row-kind enum
belongs to the Agent-run domain; framework tool contracts remain vendor-neutral.
Existing JSON row shapes are retained, with validation before replay.
Call IDs and names must be nonblank strings; arguments/results must be finite
JSON or the supported text result. The framework validates a returned result
against its call before completion callbacks. An invalid executor result follows
the existing execution-failure path, with a paired error for the actual call;
private durable history keeps that command pending instead of recording a false
completion. Transient call capture and replay snapshots use Pydantic models too.

Transcript appends lock their organization-owned AgentRun before checking a
correlation identity or allocating a sequence. Concurrent retries therefore
reuse one committed item; a repeated identity with different content is refused.
Results require a persisted call in the same run and organization. Replay also
checks that each stored correlation matches the ID in its typed payload; corrupt
history is refused rather than attached to another command. This adds a bounded
call lookup under the existing run lock, not vendor I/O or a per-row replay query.
Non-finite numbers are checked in the original Python payload as well as the
serialized representation, so JSON conversion cannot silently change them to
null. This also covers independently serialized framework metadata.

Tool availability consumes a typed scope and exact agent provider references.
It borrows an explicit/ambient session without committing or closing it; otherwise
it owns a DB-only read scope and publishes facts after that scope exits. MCP tool
preparation similarly resolves/decrypts the exact server revision in a DB-only
scope when there is no caller-owned session. Its validated JSON arguments and
resolved config, not ORM rows, reach the socket. A caller-owned outer transaction
is not implicitly closed: removing those long-running caller scopes remains
separate work in the typing plan.

Curated-tool preparation follows the same ownership rule for live policy and
connection lookups. Without a borrowed session/service, each DB-only scope exits
before vendor I/O; injected services remain caller-owned. The connection must
match the grant's organization, vendor, auth kind, instance and required scopes
before credential decryption. This lookup refuses expiring credentials; it does
not refresh them inline. Arguments and handler results are validated JSON values,
including rejection of non-finite numbers. Invalid results do not authorize a
second send of a mutation whose outbound receipt already succeeded.

Swarm tasks and prompt-only background tasks bind tool context to their exact
executing agent revision, not the conversation's primary agent. The conversation
domain reuses or creates a real, non-primary participant for that revision in a
DB-only transaction. Creation and handoff share the conversation lock. A
pipeline-owned `AgentTaskConversationContext` exposes that participant to the
existing tool actor API; persisted primary flags, contact identity, and pinned
voice policy do not change. Knowledge grants and memory provenance therefore
refer to the same task actor. Built-in title/summary jobs retain their separate
source-history path. Swarm shared-dispatch and transcript transaction work remain
open in the [typing plan](../plans/python-typing.md).

When private history is attached to a background, scheduled, or objective input,
the pipeline supplies that input's request ID to every replayed message. This
keeps restored calls and results in one vendor-history request group. Persisted
row and command IDs do not change: pending calls reuse their command identity;
completed calls remain history rather than being executed again. Missing or
invalid request identity refuses populated replay before inference. Schema errors
do not include private payloads in their rendered exception chain.

Scheduled/objective runs retain the last model's tool calls in an
`AgentRunToolCapture`, separate from durable transcript storage. Pauses correlate
the exact call ID; objective completion uses the same validated
`ObjectiveCompletion` payload for the tool response and canonical result
projection. Model/tool JSON schemas and stored continuation envelopes are unchanged.

A `CommandStepContext` can execute a product-owned command. Only
`DurableStepContext` also exposes Eylo's versioned event-wait API
(`event_name`, `key`, `version`). Live voice supplies the first contract, not the
second. SOR mutations require a durable agent run, file one command, pause in a
short DB transaction, await its terminal event outside that transaction, then
validate the receipt and resume. The underlying Absurd `step_name` and `timeout`
arguments remain behind `AgentRunWorkflowContext`, not in its callers.

Tool-result history is batch-aware. A persisted result row keeps its identity,
content, and ordering when it crosses the conversation/framework boundary. Shared
validation consumes every result ID atomically: empty, duplicate, or orphan-containing
rows consume no pending calls. Unresolved calls are removed before another turn;
completed pairs remain. The newest in-progress request uses the same validator.
Normalization copies caller-owned messages before merging or enriching text.
Anthropic/Bedrock and Gemini preserve all results; Gemini uses the matching
function name separately from the call ID and wraps scalar results in an object.
This is history preparation, not tool authorization or a write to persisted messages.

Gemini request preparation uses the pinned Google SDK's `UserContent`,
`ModelContent`, `Part`, `FunctionDeclaration`, and `GenerateContentConfig` models.
Tool JSON Schema is passed through `parameters_json_schema` rather than reduced
to the SDK's narrower `Schema` type. Omitted generation settings remain omitted;
the adapter no longer forces one thinking level across incompatible models.
Automatic function execution stays disabled: the framework owns tool execution.
Both inference paths are async, validate inputs before allocating a client, and
close the SDK's separate sync/async transports. Streaming generators are scoped
to the caller's lifetime. Native candidate/part/usage objects also drive response
assembly. Tool calls remain private until the complete batch has a successful
terminal reason, passes argument/identity validation, and releases its transports.
Content-less terminal and usage chunks still update the response.

Gemini replay retains the original signed `Part` objects in adapter-owned JSON
metadata, using the SDK's base64 serializer. It never manufactures a signature or
moves one onto regenerated text. Conversation and transient swarm messages carry
their response-block index; unchanged final model text retains the response too.
Replay checks that the saved parts match the retained message, groups a model
turn's calls before their results, and never restores a filtered-out tool call.
Reasoning is separate from spoken/displayed text. Text between calls does not
invalidate pending pairs when it belongs to the same recorded model response.
Older messages without original parts cannot have lost signatures reconstructed.
Configured-account QA and broader canonical/caller typing remain explicit items
in the [typing plan](../plans/python-typing.md).

Cerebras schema cleanup traverses schema nodes, not arbitrary JSON keys; property
names and annotation data cannot be mistaken for unsupported schema keywords.
OpenAI's shared schema projection also traverses definitions and unions without
mutating canonical tool schemas. It retains declared nullable types; it does not
invent nullability for non-nullable platform inputs. Chat, Responses, and realtime
keep their own function wrappers and strict flags.
Sarvam uses its SDK's text-only message shape, not OpenAI content blocks. Image
input is explicitly refused before client allocation, rather than discarded.

Streaming adapters expose an async generator that the conversation caller closes
in `finally`, including cancellation while the caller is handling a yielded
chunk. OpenAI Chat/Responses, Anthropic/Bedrock, Groq, and Cerebras scope both their SDK client and
stream to that generator.
Sarvam owns the HTTP client passed to its SDK, which has no public close method;
it closes the SDK's async generator before the HTTP client. Final results are
handed off after resources close. Cerebras disables SDK 1.67.0's synchronous TCP
warmup during async client construction, avoiding hidden blocking HTTP/retries.
Cleanup inside the remaining vendor implementations is still part of the typing
plan. String tool-result
serialization is vendor-neutral and retains the existing TOON representation.

## Telephony config translation

The telephony module validates the organization-owned config and resolves its
exact revision. `build_telephony_runtime_config` translates that resolved value
into socket-owned `TwilioSettings`, `PlivoSettings`, `VonageSettings`, or
`ExotelSettings`. These immutable models require their known fields, reject extra
fields, and omit credentials from representations. They are execution values,
not persistence or public response models.

Call control, number management, credential verification, and media activation
use this one translation. The factory selects an explicit carrier branch;
each service refuses another carrier's settings. Media activation also checks
that the resolved config matches the authenticated carrier. Module and socket
provider enums retain separate ownership. Exotel uses the stored `application_id`
and `api_host` directly, without duplicate intermediate config aliases.

The local telephony gate checks these producers and consumers. A separate import
gate executes the caller imports because static checking alone does not detect
every eagerly evaluated type-alias failure. These checks do not certify native
request/response schemas or live provider operation; their remaining coverage is
tracked in the [typing plan](../plans/python-typing.md).

## Why verification is a separate action

Saving proves only that the request fits the schema. Verification proves that
the selected vendor credential/resource works. Separating them lets operators
save incomplete work, rotate secrets without pretending they are valid, and
see the exact readiness state.

Verification is capability-specific because “valid” means different things:
list a cheap model/resource, open and close a bounded stream, fetch ICE
credentials, inspect storage access, or execute another vendor-defined probe.

LLM verification uses a detached `LLMVerificationInput` and a typed receipt.
The [verification pipeline](../../server/eylo/pipelines/llm/config_verification.py)
reads the organization-owned config in a short transaction, releases it, then
calls the [socket verifier](../../server/eylo/sockets/llm/verification.py).
The socket uses each vendor's native SDK and the same response validator as
inference. An HTTP success with an invalid response cannot mark a config verified;
a valid token-limited response does not need to contain the literal text “OK”.

After the probe succeeds, a separate short transaction marks only the tested
revision. A concurrent config edit returns a conflict; deletion cannot be undone
by a late probe. Timeout, cancellation, and malformed output do not write a
successful receipt. Native clients close on every exit, and vendor error bodies,
credentials, and generated text are not included in the receipt. The public
verification response retains its existing provider/model spelling and
`verifiedAt` timestamp field.

## Catalog-driven UI

The server projects capabilities, vendors, fields, options, conditions, and
secret/reference types through one onboarding catalog. The console renders the
same form system for every capability.

This avoids frontend/vendor drift. A vendor-specific component is justified
only when a real interaction cannot be represented by the shared schema.

## Platform features versus vendor capabilities

Provider-native features are facts about an adapter. Platform voice, memory,
knowledge, tool, and execution policy remain Eylo contracts. A vendor may offer
native VAD, interruption, caching, or reranking; the pipeline decides how that
maps into platform behavior.

Unsupported native features are visible as compatibility data. They do not
silently disable platform policy or make inert configuration appear effective.

Browser voice termination uses `BrowserVoiceTerminationReason` from the shared
voice contract. WebRTC native states and realtime failure observations are
explicitly mapped before reaching the session owner. Telephony keeps its separate
`CallEndedReason`; equal wire values do not make these types interchangeable.
Signaling and transcript persistence receive the existing string values only at
their boundaries.

Browser and carrier recording notifications share `RecordingDisclosureState`.
The historical `recording_consent_state` field and its wire values are retained;
this state observes notification delivery and caller feedback, never permission
to start or stop the recorder.

Telephony owns `CallOpenerDeliveryStatus` and `CallTransferStatus`. Lifecycle
commands take typed outcomes, while ORM readback converts existing string values
into these enums. Storage remains `VARCHAR(32)`, with unchanged values and
constraints; this uses SQLAlchemy's
[non-native enum mapping](https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Enum).
An accepted transfer is not a completed transfer; an unknown outcome continues
to block another transfer send. Native carrier status remains separate.

Call initiation returns the frozen telephony-owned `OutboundCallResult`, reusing
the shared `OutboundAttemptState` rather than defining another effect lifecycle.
Agent tools, scheduled calls, and campaign dispatch inspect typed fields; HTTP,
tool metadata, and scheduler output serialize IDs and states at their boundaries.
The existing JSON keys and values are preserved. `OutboundRetryRequested` still
propagates from the outbound ledger; an unknown result does not authorize a resend.

The shared external-effect contract lives in `common/outbound.py`: frozen
Pydantic models for owner identity, attempt specification, send authorization and
provider outcomes. Identity keeps the existing deterministic UUID/idempotency
key. Invalid owner/transport values, coercible status values and malformed
fingerprints fail validation before use. Adapters retain ownership of their
failure categories; the common contract validates their bounded format rather
than importing vendor enums. Outcomes stay typed in process; the outbound
pipeline owns the durable receipt and checkpoint representation.

Email config resolution follows the same ownership split. The email module owns
immutable SendGrid/SMTP settings and private credentials; `SMTPSecurity` names
the operator's transport selection. The pipeline explicitly translates those
fields into socket configs rather than spreading a settings dictionary. Secret
exports are explicit for encrypted persistence; normal model serialization and
representations exclude credentials. Resolved material checks organization,
capability, config ID and revision before adapter construction. Verification runs
outside DB transactions, closes its adapter and marks only the expected revision
verified. The public config keys and SMTP/SendGrid wire values are unchanged.

The email pipeline projects the validated outbound receipt into a frozen
`EmailDeliveryResult`. Agent-facing success/error variants and receipt metadata
must agree: an unknown send cannot appear as accepted, and preflight refusals
carry no delivery receipt. The tool's error flag and JSON output are derived
from that typed outcome rather than independently populated dictionaries.
`accepted` means provider acceptance, not confirmed recipient delivery. Campaign
and conversation consumers retain the same JSON values and tracking identities;
persisted campaign DTOs require their organization owner, matching the DB model.

SendGrid's adapter constructs native request objects for envelopes, addresses,
content, attachments and custom arguments; JSON serialization happens once when
planning the HTTP request. The consumed scope response is validated before
checking `mail.send`. These contracts follow the v3
[Mail Send reference](https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send)
and [scope response reference](https://www.twilio.com/docs/sendgrid/api-reference/api-key-permissions/retrieve-a-list-of-scopes-for-which-this-user-has-access).
Provider-neutral metadata accepts JSON values, not arbitrary Python objects.

The existing SendGrid event parser also validates native fields against the
[Event Webhook reference](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/event).
It parses **one event**, not the vendor's HTTP batch envelope. It does not verify
signatures, expose a route, register a webhook or update campaign delivery state.
No platform consumer currently calls it. A future ingress must authenticate the
original request before parsing/dispatch. Unknown event names, missing required
fields and invalid timestamp types are refused; optional vendor/custom fields
are retained as validated JSON. Do not infer webhook product support from the
presence of this parser.

Email delivery plans are frozen Pydantic values. Capability support is explicit
through `EmailCapabilitySupport`, not truthy flags; neither current adapter
claims provider-side idempotency or reconciliation. The live sender callable is
excluded from plan serialization. Organization resolution and the durable ledger
still own send authority; the plan additionally checks the exact attempt ID.

SMTP uses the installed SDK's typed result rather than assuming a normal return
means every recipient accepted. The SDK can return normally with a refused-recipient
map ([SDK reference](https://aiosmtplib.readthedocs.io/en/stable/reference.html#aiosmtplib.SMTP.sendmail)).
Partial acceptance maps to `UNKNOWN` with `smtp_partial_acceptance`: the overall
send is incomplete, but replaying the whole envelope could duplicate delivery to
accepted recipients. This does not implement recipient-level retry. Native reply
text and addresses are not copied into the failure category. `SMTPFailureCode`
owns adapter failures; platform lifecycle states remain vendor-neutral.

The SMTP adapter owns each socket from allocation until transfer or close.
Cancelled/failed connects close the candidate socket. Client construction,
authentication, send and teardown failures close both client transport and socket;
cancellation propagates rather than becoming success or authorizing a retry.

`CallInitiationMarker` names Eylo's interim values in `provider_status`, including
`initiation-unknown`. That column remains open text because carrier callbacks also
write native statuses. These markers are not a new call state machine or schema
constraint.

## Integrations are different

Curated integrations expose Agent tools for an external application. They are
not interchangeable runtime capabilities such as LLM or storage. Their
registry, installations, connections, origin-pinned tool context, and mutation
receipts therefore live in the integrations boundary rather than provider
configs.
