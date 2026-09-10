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

## Call termination

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
