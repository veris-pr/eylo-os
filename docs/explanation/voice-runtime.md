# Voice runtime

Eylo's voice value is the humane interaction layer around provider audio: turn
state, interruption, silence, call control, transcripts, recordings, and
cleanup. Provider packets alone do not define that experience.

## Two provider paths

The decomposed path uses STT for user audio, an LLM for reasoning/tools, and TTS
for assistant audio. The realtime path delegates audio generation and
understanding to one realtime provider while Eylo retains session, tool, policy,
and artifact ownership.

Browser voice adds WebRTC signalling/media. Telephony adds carrier webhooks and
a bidirectional media stream. All paths converge on canonical conversation,
message, user-session, voice-session, and transcript records.

Live voice owners pass their pinned `VoiceRuntimeMode` into conversation-context
construction, including after handoffs. The first live turn cannot infer voice
from stored messages: transcripts may still be buffered until post-call
processing. Callers outside live voice retain channel/message-history inference;
context construction never depends on a process-local WebSocket registry.

Closing a WebRTC peer projects the existing disconnected event, not a failed
connection. Genuine native failures still project failure; terminal callbacks
retain the original reason and are suppressed during owner-initiated cleanup.

## Voice config is platform policy

A voice config selects provider configs and defines interruption, silence,
duration, recording, end-call, and interaction settings. The primary Agent's
voice config is fixed when the conversation starts and does not change during a
swarm handoff.

Provider capability projection tells operators which features are native. A
pipeline may implement a platform feature even when the provider does not.

The compatibility API exposes a `kind`-discriminated union of STT, TTS and
realtime capability models. Each pairs a provider identity with its own typed
native fields. Sockets own adapter declarations; the pipeline explicitly
translates them into console-owned models rather than exposing SDK objects or
an untyped dictionary. Support remains boolean in JSON for the existing console,
with explicit support enums in Python. Reading this projection constructs the
selected adapter but does not connect to the vendor; it is not verification or
proof of a successful voice session.

Polly translates the shared synthesis carrier into a private, frozen native
config and an explicit request model before opening its SDK client. Its PCM
request remains mono signed 16-bit audio at 8 or 16 kHz; encoding conversion is
still owned by the pipeline. The adapter validates response bodies and binary
chunks, closes each body after draining or interruption, and releases the client
when verification fails or is cancelled. The SDK's proxied streaming body is
wrapped locally; no SDK resource enters the platform model.

Sarvam's WebSocket adapter sends typed configuration, text and control messages.
It explicitly requests `linear16` PCM at the resolved sample rate and translates
the platform language into the streaming API's `language_code`. It recognizes
the documented `event` / `final` completion message, not a receive timeout.
Malformed output and vendor errors fail the turn without exposing raw error
payloads. Completed or interrupted streams are retired; the next reply opens a
new configured stream so late output cannot enter another turn. Cancellation
during setup closes the acquired socket, while receive-poll cancellation leaves
the connection intact. These choices follow Sarvam's
[streaming contract](https://docs.sarvam.ai/api-reference/text-to-speech/stream)
and [audio-format guide](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/how-to/set-audio-format-for-output).

Deepgram Aura v1 also receives through the manager rather than a hidden adapter
task/queue. Typed `Flushed` control ends synthesis; metadata, warnings and polling
do not. A premature EOF fails the turn. Interruption sends `Clear` and retires
the connection; subsequent speech opens a fresh stream so untagged old binary
audio cannot cross turns. Completed streams are retired too. This trades another
handshake per turn for explicit stream ownership. Native WebSocket ping/pong
handles transport liveness; keepalive never sends synthesis `Flush` messages.
Codec/rate combinations are validated before connecting, query values are encoded,
and credential-bearing handshakes refuse redirects. See Deepgram's
[Aura streaming reference](https://developers.deepgram.com/reference/text-to-speech/speak-streaming)
and [media combinations](https://developers.deepgram.com/docs/tts-media-output-settings).

Groq Orpheus synthesis uses a typed request and one ordered HTTP worker. Long
text is split without discarding characters at the native request boundary.
The adapter parses RIFF chunks and their padding rather than assuming a 44-byte
WAV header. It accepts only audio matching its declared mono PCM16/48 kHz
contract; malformed, truncated or unsupported audio fails the turn. Bounded
queues apply backpressure instead of dropping speech. Completion requires final
input, completed requests and drained audio; HTTP failures cannot become empty
successful turns. Interruption cancels the active body and queued generation.
Verification cancellation closes its unpublished session, and reconnect waits
for any outstanding cleanup. The adapter does not advertise speed control because
it does not send a speed option. See the
[Orpheus speech contract](https://console.groq.com/docs/text-to-speech/orpheus)
and [RIFF chunk layout](https://learn.microsoft.com/en-us/windows/win32/xaudio2/resource-interchange-file-format--riff-).

OpenAI and Groq share the socket-owned ordered HTTP lifecycle, not vendor wire
schemas. OpenAI requests retain the operator's model/voice IDs, validate speed
within 0.25–4, and use the same request builder for verification and synthesis.
Text is partitioned at 4,096 characters without truncation. OpenAI's headerless
24 kHz PCM16 response is frame-aligned across arbitrary HTTP chunks; empty,
incomplete, or oversized responses fail. These checks validate framing, not
speech intelligibility. Native rates are exposed to the pipeline's existing
resampler, so playback and recording consume the same converted audio. See the
[speech endpoint contract](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)
and [PCM output format](https://developers.openai.com/api/docs/guides/text-to-speech#supported-output-formats).

Rime uses typed JSON requests/events on the documented `/ws3` endpoint. Audio
comes from base64 `chunk.data`; timestamp and batch `done` events are not EOF.
Final input sends EOS, then completion waits for a normal code-1000 close after
valid audio. Empty/truncated audio, malformed events and provider errors fail
the turn. Interruption retires the connection; the next turn cannot consume its
late frames. The manager pulls audio directly with transport backpressure, and
the pipeline converts raw PCM or mu-law for playback/recording. Credentials stay
in the handshake header and redirects are refused. Speed control and timestamp
projection are not advertised because this adapter does not implement them.
See Rime's [WebSocket overview](https://docs.rime.ai/docs/websockets) and
[native event contract](https://docs.rime.ai/api-reference/mistv2/websockets-json).

Section edits use the `VoiceConfigSection` enum and the section's existing
Pydantic model. An edit replaces that section, including its omitted-field
defaults; it is not a recursive merge. The complete reconstructed config is
validated before the optimistic revision update. Bound Agent drafts advance,
but published Agent revisions remain unchanged until republished.

Stored-only settings retain their experimental description and schema marker.
`experimental()` supplies typed field metadata; defaults and factories remain
on the field declarations so static tooling can understand constructor inputs.

## Browser audio boundary

WebRTC material uses frozen Pydantic settings and credential models, not a
dataclass whose declared provider type changes after construction. Metered and
Turnix settings select separate validators. The resolved model checks capability,
organization and config identity against the shared provider snapshot. Read-only
stored mappings are copied at validation; omitted transport settings remain
omitted rather than becoming new persisted defaults.

API keys are excluded from normal model serialization and exported explicitly
only for encrypted persistence or socket invocation. Native ICE objects remain
private to the pipeline. A separate browser projection intentionally includes
short-lived TURN credentials, never the provider API key. Credential fetching
and verification run outside DB transactions; verification still commits against
the checked config revision. Metered's existing TLS-verification exception is
unchanged by this typing work.

Socket-owned request models keep Metered's query credential separate from
Turnix's optional body fields. Provider responses become validated immutable ICE
values before conversion to aiortc: a nonempty server list, supported STUN/TURN
schemes, correctly typed credentials and at least one TURN entry are required.
Unconsumed response metadata is ignored. Normal wire/config dumps exclude secrets;
only the deliberate HTTP and peer projections export them.
The wire formats follow the [Metered credential API](https://www.metered.ca/docs/turn-rest-api/get-credential/)
and [Turnix ICE credentials reference](https://turnix.io/docs/api-ice-credentials).

The signaling manager owns a Pydantic negotiation aggregate keyed by organization
and session. The key is immutable; live peer, queue-task, lock and session
references retain identity and are excluded from serialization. Accepted SDP
answers are immutable values, serialized afresh when an identical offer is
replayed. Replaying does not allocate another peer or resolve credentials again.
Only an offer enters peer acquisition; candidate policy runs before the sanitized
SDP becomes a `WebRTCOffer`.

Prepare, offer and candidate inputs are validated before accessing negotiation
state. Protocol versions must be integers, not booleans or coercible strings;
candidate metadata is checked even on replay. Direct and one-level nested
candidate envelopes remain accepted, and a null candidate still ends gathering.
Owned error enums cross the candidate-policy and signaling boundaries without
reflecting raw input or provider errors. Typed prepare, answer, candidate and
hangup results become JSON only at the WebSocket boundary. Existing command
names, request correlation, nullable expiry fields and idempotent hangup flags
remain compatible with the widget.

Candidate parsing yields immutable values with typed ICE component, transport,
kind and TCP mode. Supported extension pairs are validated before native peer
construction; unknown extension names are ignored. Network admission remains a
separate deployment policy, not a side effect of constructing the value model.
An unrecognized TCP mode is refused even when supplied on a UDP candidate.

Native aiortc state enums stay separate from Eylo event names and termination
reasons. The pinned aiortc 1.15.0 implementation gathers local ICE candidates
during `setLocalDescription`; the completed SDP answer carries those candidates.
Browser-only `icecandidate` callbacks are not registered on the Python peer.
See the [aiortc peer API](https://aiortc.readthedocs.io/en/latest/api.html#aiortc.RTCPeerConnection).

Incoming WebRTC tracks validate `AudioFrame` output before using audio fields.
Signed 16-bit planar samples are interleaved before stereo-to-mono conversion;
packed PCM follows the same downsampling path. Other sample formats are refused
rather than silently truncated. The resulting mono PCM16 bytes feed recording
and the configured STT/realtime path. The STT request queue carries bytes, and
the session holds the actual recorder instance rather than an untyped resource.

Downsampling methods are an enum; buffer diagnostics are immutable Pydantic
models. CPU JIT kernels retain their numerical implementation behind a checked
PCM-array boundary. A non-integer conversion producing exactly one sample uses
the first input position instead of dividing by zero. This does not redesign
the resampler into a continuous streaming filter: chunk-boundary decimation and
the existing bounded STT queue's drop-oldest policy remain unchanged.

Outgoing frames retain the transport playback gate: generating text or draining
the provider alone does not mean the final PCM frame has played. Buffering,
partial-frame padding, interruption and transport-drain reporting remain owned
by the outgoing track.

## Turn and interruption handling

Assistant playback completion, not merely model text completion, determines
when the user-silence timer may begin. User speech can interrupt current Agent
audio. The transcript records speech outcome separately from generated text so
model context, operator review, and playback do not claim unheard content was
spoken.

Silence checks such as “Are you still there?” are policy speech, not normal
Agent content. They must not be inserted into canonical model history as if the
Agent independently chose them.

## Carrier stream contracts

Each carrier adapter validates its consumed WebSocket fields and returns a typed
start, media, keypad or ignored event. The manager decodes each frame once; the
pipeline owns routing enrichment, authorization, config resolution and session
creation. A parsed start is not authenticated authority. Media received before
session initialization is not delivered to the voice pipeline.

Twilio, Plivo and Exotel carry base64 audio in JSON. Vonage carries binary PCM
separately from JSON controls. Carrier timestamp and sequence representations are
preserved rather than coerced into one invented vendor format. Unknown controls
remain ignored; malformed consumed fields fail validation and enter the existing
teardown path. The ASGI transport helper narrows native frame values before they
reach a parser.

Outbound media and clear commands also use carrier-owned models. Serialization
aliases supply native field names without changing Python constructor names.
Plivo emits numeric `sampleRate`; Vonage sends the documented `action: clear`
command instead of treating interruption as unsupported. A successful clear write
means transport acceptance, not a received playback acknowledgement. Outbound wire
serialization deliberately includes audio; these command objects are not audit
snapshots and must not be logged.

Exotel's existing sender still derives sequence and timestamp values from wall
clock time. The typed command preserves that representation; monotonic ordinals,
relative timestamps and chunk sizing require separate protocol validation.

See [Twilio Media Streams](https://www.twilio.com/docs/voice/media-streams/websocket-messages),
[Plivo Audio Streaming](https://www.plivo.com/docs/voice-agents/audio-streaming/concepts/audio-streaming-reference),
[Exotel Stream/Voicebot applets](https://support.exotel.com/support/solutions/articles/3000108630-working-with-the-stream-and-voicebot-applet)
and [Vonage WebSockets](https://developer.vonage.com/en/voice/voice-api/concepts/websockets).
Vonage's native `websocket:dtmf` spelling is recognized alongside existing legacy
keypad variants. Its native connection-handshake metadata initialization remains
an unresolved integration gap; parser coverage alone does not establish native
Vonage call readiness.

Exotel packed custom routing remains explicit compatibility: the adapter handles
direct fields, HTML-escaped JSON keys and packed `CustomField` values without
logging tokens, phone numbers or caller content. Caller-selected routing still
requires the existing pipeline token checks, including when a recognized routing
field was supplied empty or null. New start/media/keypad snapshots exclude raw
metadata, audio and digits.

The pipeline decodes query routing into `MediaStreamRouting`; telephony owns the
separate signed `MediaStreamClaims` body. Query shape validation grants no access.
Recognized routing keys require a token even when their values are empty, and
existing carrier metadata is not overwritten by query values. All supplied known
query fields are validated, including fields that would otherwise be shadowed by
carrier metadata. Malformed IDs, revisions and directions are refused.

Claims preserve the existing canonical JSON bytes used for signing: provider names
are lowercase, direction is uppercase and revisions are integers. Authentication
still checks the signature before validating the body and comparing call, org,
agent and config identities. Malformed bodies and non-ASCII signatures return an
invalid-token result. Claim serialization includes caller text for signature
binding and must not be used as a log snapshot.

## Call termination

The outbound-call HTTP route declares its request and result schemas. Organization
authority comes from the authenticated member; an organization field in the body
does not select another tenant. The bounded idempotency header still determines
the stable call ID. Malformed body fields now receive request-validation errors
before resolution or carrier I/O, rather than generic runtime failures.

Call orchestration parses campaign links into a typed origin value while retaining
the original JSON context for request fingerprinting. Empty optional links remain
absent; valid request fingerprints, stream parameters and callback URLs are
unchanged. Carrier control outcomes become a module-owned accepted-result model
or the existing explicit unsupported/rejected/unknown errors. Module and socket
provider enums remain separate: comparisons use the enum owned by the value being
examined, and the config pipeline translates at the boundary.

Exotel v1 connect-call forms and consumed responses use carrier-owned models.
The form keeps the customer in `From`, the configured ExoPhone in `CallerId`, and
the applet in `Url`; optional packed metadata is not interpreted as platform
routing by the REST adapter. Only a textual call identity establishes acceptance.
Malformed successful responses remain unconfirmed and cannot trigger an automatic
resend. This follows Exotel's
[connect-to-flow contract](https://docs.exotel.com/exotel-agentstream/connect-voice-ai-with-flow-api).
Flat `CallSid`/`sid` parsing remains explicit legacy compatibility, not a claim
that these variants are documented by the current connect API.

Vonage owns separate typed phone/WebSocket endpoints, connect NCCO instructions,
call creation and control requests. Bootstrap and outbound creation share the same
NCCO builder rather than serializing and reparsing intermediate dictionaries.
Only a `started` response with a textual, nonblank identity establishes acceptance;
unknown or malformed responses do not. Hangup, transfer and DTMF retain their
status-based outcome classification and cancellation cleanup. The models cover
the NCCO actions Eylo produces, not all vendor actions. See the
[Voice v1 REST contract](https://developer.vonage.com/en/api/voice) and
[NCCO endpoint reference](https://developer.vonage.com/en/voice/voice-api/ncco-reference).

Twilio call creation and control use typed native forms. Creation requires a
textual, nonblank `sid`; malformed responses remain unconfirmed. See the
[Call resource](https://www.twilio.com/docs/voice/api/call-resource).

Plivo call creation sends one bounded async HTTP request rather than using the
SDK's implicit voice-request retries. Its `request_uuid` identifies acceptance,
not the active call: the outbound receipt can retain that request ID, while
`TelephonyCall.call_sid` stays unset until an authenticated callback supplies the
actual call UUID. If the callback arrives first, its committed success receipt is
preserved; a late create response cannot overwrite it. This follows the
[Plivo Calls API](https://www.plivo.com/docs/voice/api/calls). SDK-based end/DTMF
operations are separate from this create path.

Existing Plivo attempts pinned to the previous SDK transport are not silently
rewritten or resent after this change. Reusing their identity with the new HTTP
transport raises the existing outbound-spec conflict. Old malformed receipt IDs
are not assumed to be valid call UUIDs. Operators must reconcile such historical
attempts before considering a new call; retrying blindly can duplicate a call.

Twilio number search uses vendor-owned request/response models before projecting
into the public available-number schema. The console's existing 30-result cap is
preserved; it is not Twilio's API maximum. Provisioning parses the top-level
IncomingPhoneNumber identity instead of recursively finding arbitrary nested
keys. Invalid identities or a returned number differing from the requested number
remain unconfirmed, without automatic resend. See the
[available-number contract](https://www.twilio.com/docs/phone-numbers/api/availablephonenumberlocal-resource)
and [provisioning resource](https://www.twilio.com/docs/phone-numbers/api/incomingphonenumber-resource).

Plivo, Vonage and Exotel available-number responses are also parsed into their
own carrier models before the pipeline builds the public projection. Canonical
mobile searches translate to Plivo `mobile`, Vonage `mobile-lvn` and Exotel
`Mobile`; vendor spellings do not enter the module's number-type enum.
Plivo provisioning requires a fulfilled single-number result matching the request;
pending or malformed responses remain unconfirmed. Vonage requires an explicit
textual success code, not an empty response. Its old `0` compatibility code is
retained separately from the documented `200`. See the
[Plivo PhoneNumber API](https://www.plivo.com/docs/numbers/phone-numbers),
[Vonage Numbers API](https://developer.vonage.com/en/api/numbers) and
[Exotel available-number API](https://developer.exotel.com/docs/exophones/api-reference/available-numbers).
This typed search coverage does not establish Exotel purchase-response coverage;
that operation still uses the existing compatibility parser.

Outbound telephony preparation compares an immutable call-intent projection
under the existing transaction lock before creating a row. Replaying the same
intent reuses that row; changed or invalid canonical identity is a conflict.
Persisted call schemas require the organization owner, matching the DB constraint.
Lifecycle results are immutable Pydantic values; this does not move carrier I/O
into the preparation transaction.

Carrier configuration also uses immutable provider-specific material. The module
owns settings and credential validation; the pipeline maps typed fields into the
socket's separate contract. Explicit exports supply encrypted persistence and
callback verification without making plaintext credentials part of normal dumps.
Resolved material must match its effective snapshot's org and telephony capability.
Read-only verification runs outside DB transactions and records a typed account
fingerprint against the checked revision, not the raw account reference.

Callback mappings retain the canonical status enum until the lifecycle command.
Only terminal observations supply terminal timestamps, duration and ended reason.
Persisted transition results decide whether to emit a ringing/ended event;
duplicate or stale observations cannot emit another terminal transition. Vendor
signature validation remains ahead of this processing in the public route.

The platform can close an active voice session from silence/max-duration policy,
an end-call phrase, user hangup, transport failure, or the `end_call` system
tool. Telephony-specific carrier cleanup is one adapter effect; browser and
realtime sessions also close through the shared voice-session authority.

The telephony silence monitor retains its validated TTS, live-buffer and session
handles for its lifetime. Call teardown cancels and awaits policy tasks before
discarding the buffer. Reminder failures release the activity gate; cancellation
propagates to the task owner rather than becoming a retryable reminder failure.

Call finalization collects typed STT manager/factory, TTS and carrier-counter
snapshots. It adds the terminal-reason enum, then serializes at the logging and
voice-session persistence boundaries. Unavailable provider branches remain absent;
null measurements inside an available snapshot remain null. A metrics failure
does not prevent completion or misrepresent unavailable measurements as zeros.

Browser finalization also retains typed STT/TTS observations until that boundary.
Disabled metrics do not read provider counters. Its latency projection omits the
TTS first-audio latency field without modifying the snapshot; other counters and
timestamps retain their existing shape. The terminal reason remains present even
when observation collection or serialization fails. Realtime sessions do not
invent STT/TTS observations for providers they did not use.

Browser STT/TTS startup normalizes resolved material into the socket-owned config
models before assembling the live session. Provider-native options and explicit
credentials retain their existing factory handoff; no provider or model fallback
is introduced by the typed browser boundary.

## Recording and post-call work

Recording captures the live flow first. Upload, redaction, canonical transcript
processing, and configured policy controls happen asynchronously after the
call. Secondary failure is visible but does not retroactively fail the call.

Recording upload tasks carry only organization and recording IDs. The worker
loads a detached staged-input model or a completed receipt under a short DB
transaction; raw tracks are excluded from serialization. Storage resolution,
stable-key track uploads and success projection remain separate phases. Track
names use recording-owned `user`/`agent` values, not transcript speaker roles.

Track uploads use the shared outbound receipt contract. The frozen Pydantic
receipt validates lifecycle/count consistency both after DB projection and when
replaying an Absurd checkpoint. Checkpoints retain the seven identity/outcome
fields, including explicit nulls; malformed types and unexpected fields are
rejected. A cached receipt must match the attempt ID before reuse. Unknown sends
remain fenced rather than being repeated automatically.

Absurd cancellation bypasses ordinary upload-error classification, including on
the last permitted attempt. The cancellation handler fences pending sends,
projects confirmed accepted tracks, or retains staged bytes when an effect is
uncertain. It discards staged bytes only when cancellation confirms no external
effect. Process-level task cancellation still propagates for runtime recovery.

Storage adapters receive platform-built keys below an operator root/bucket:
organization → owning conversation/call/session → artifact. Callers never
provide a final object path.

## Resource cleanup

The module-owned `SessionContext` carries a narrow session port, not provider
clients. Browser voice and WebSocket audio ingestion share a pipeline-owned
resolver for `WSSessionState` before accessing live resources. Resolution
preserves the original object;
serializing or rebuilding it would detach cleanup from the actual tasks and
queues. Missing state is allowed during teardown, but startup requires it.
An incompatible holder is a wiring error rather than an unchecked cast.

The WebSocket session validates resource assignments without copying their
instances. STT queues carry audio bytes or transcript inputs; TTS queues carry
typed requests or audio bytes. Session task registries use named task enums.
Handles, callbacks and client request metadata are excluded from snapshots;
queue instance validation does not inspect payloads already inside a queue.
Browser and telephony teardown share a narrow voice-runner drain port instead
of importing each other's runtime implementation.

Ambient-noise and filler settings stay as their owning voice-config models
through playback and filler injection. Each session receives independent copies,
including the phrase list. Configured delays are interpreted in milliseconds;
the existing no-config filler delay remains 600 ms. Browser ambient fallback
and telephony's no-config silence remain distinct. Runtime mode and interaction
callbacks retain their existing enums until the event/persistence boundary.

Peer terminal callbacks accept awaitables, including Futures. A retained
coroutine task awaits that callback; its completion callback observes failures.
Cleanup never waits on the terminal task that invoked it. Extra incoming audio
tracks are stopped and route through the same typed terminal reason as other
peer failures. Registered native event callbacks retain their original peer
reference, so late close events do not resolve a cleared resource property.
Normal ICE close during owned teardown is not logged as relay failure. Python's
[task contract](https://docs.python.org/3.13/library/asyncio-task.html#asyncio.create_task)
requires a coroutine at `create_task`, rather than any arbitrary awaitable.

Each child session owns its tasks, streams, media tracks, provider clients,
timers, and queues. Normal completion, timeout, cancellation, WebSocket loss,
WebRTC failure, carrier hangup, and abrupt browser closure all converge through
idempotent shutdown. Provider cleanup errors are contained and logged without
leaving the product lifecycle active.
