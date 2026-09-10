# Python typing and literal-removal plan

## Remaining-work checklist — current checkpoint

This is the short completion tracker. The chronological evidence below is not a
percentage-complete claim; local contracts and live product acceptance are separate.

- [ ] Finish curated native contracts: 20/29 vendors, 103/148 tools locally covered
  (Asana, Freshdesk, Zendesk, Intercom, GitHub, GitLab, Jira, Linear, Google Sheets,
  HubSpot, Pipedrive, Google Docs, Google Drive, Google Tasks, Dropbox,
  Google Calendar, Calendly, PagerDuty, Sentry, Typeform).
  Next: remaining document/file, communication and operational vendors. Close
  GitLab named-project transport refusal without weakening shared egress policy.
  Plan Sentry's deprecated project-list/ID-only route migration explicitly rather
  than guessing an organization in existing tool inputs.
  Pipedrive now uses supported v2 CRM operations and v1 notes; live acceptance
  remains pending, alongside the other curated vendors.
- [ ] Reconcile all 11 SOR profile/vendor registrations against sync, commands,
  OAuth and webhook operation coverage; finish missing native contracts.
- [ ] Close remaining voice lifecycle/config gaps, Smallest protocol compatibility
  and Murf native acceptance. Local native STT/TTS checks are not live call QA.
- [ ] Finish MCP, durable checkpoint and cross-module readback/output omissions;
  reconcile every provider factory and consumer against F0–F10 below.
- [ ] Fix outstanding product findings: generated-card text presentation and SOR
  duplicate field descriptors; verify other recorded findings remain applicable.
- [ ] Repeat deployment/acceptance after the remaining implementation without
  resetting operator data. A current-build text/retrieval checkpoint passed on
  2026-09-10 (below); full voice, upload, vendor and recovery acceptance stays open.
- [ ] Run final backend/frontend/widget/docs gates; publish a bounded acceptance
  summary identifying any vendor-specific missing credentials or human QA.

Completed foundation: all eight LLM native branches, shared execution/config/
identity contracts, and substantial retrieval, storage, voice, email, telephony,
campaign and session typing. The detailed evidence remains below. No entire flow
is closed merely because its enums, config or type checker pass.

Typeform slice (2026-09-10): all three read handlers now use native form,
submission, tagged-answer and request/result models. Page continuation, nested
question joins, explicit response selection, stable response tokens, and strict
malformed-data refusals replace dictionary decoding. The old boolean input is
deprecated but remains compatible; no provider installation or DB change is
required. Official response examples include the year-one unsubmitted timestamp
that the old truthiness check incorrectly treated as completed.

Verified locally: 102 function assertions, two literal official JSON examples
(eight submissions), and all three real executor/guarded-client paths using
substituted HTTP/grant/auth boundaries. Invalid input sends nothing; wrong form
identity cannot become a successful tool result. Native account acceptance and
deployment of this Typeform slice remain pending. The earlier retrieval browser
checkpoint below does not validate these new Typeform changes.

Full backend lint and Pyrefly passed (two existing suppressions and two unrelated
SOR redundant-cast warnings); documentation verification and diff whitespace
checks passed. Typeform was added to the curated-contract local hook. No source
schema, migration, dependency, runtime credential, or external vendor data changed.

Operations batch (2026-09-10): PagerDuty four tools and Sentry four tools now use
native request/response and result contracts. Missing collections no longer
become empty success; Sentry mutations confirm the returned identity and status.
PagerDuty exposes offset/time-window continuation and preserves policy/shift
identity. Sentry exposes validated Link cursors and structured source context.
JSON-only media negotiation is catalog-owned and carried through the executor;
arbitrary static credential/framing headers remain forbidden. Native vendor
enums stay in the owning vendor, not the canonical SOR domain.

Local evidence: 141 function assertions; five literal current vendor examples
(three PagerDuty OpenAPI, Sentry issue and event); two real guarded-client
mutation/replay checks; actual executor-to-PagerDuty media negotiation and
Sentry transport-to-result cursor checks. HTTP, grants/auth lookup and receipt
persistence were substituted. Scheduling's 196 function assertions, Calendly
scope-resolution checks and 18 earlier guarded mutation-handler probes also
passed again. No live PagerDuty/Sentry account acceptance or DB recovery is
claimed by these probes.

One batch review covered boundaries, architecture fit, data flow, plan alignment
and readability. It preserved case/whitespace normalization and the source-text
budget. Full lint and Pyrefly passed (two existing suppressions/two unrelated
SOR cast warnings), the expanded curated pre-commit hook passed, and all
29 vendors/148 input schemas still generate. Documentation verification passed.
Deployment checkpoint (2026-09-10): the API, durable worker, ordinary task
worker and scheduler now run image `0c53fb6b523e`, including the accumulated
scheduling and operations batches. Existing operator DB/provider data was
preserved. Image identities were rechecked after deployment.

Real widget/console acceptance in Eylo Development used conversation
`01a08b8f-bc37-7601-b585-6403cf032f69`: memory recall returned the saved color;
KB retrieval returned the release codename with citation; a no-tool follow-up
retained both values without further tool calls. All 19 persisted messages,
including three background-observer tasks/results, reached completed states.
The first KB rerank hit the pipeline's three-second timeout and truthfully
recorded `degraded/provider_timeout`; one repeat of the identical query returned
`applied`, no reason, and a comparable Bedrock score. Memory reranking also
succeeded. This proves both persisted outcomes, not the underlying cause of
the first latency spike or sustained provider reliability. Bounded logs for
the QA window contained no matching error/timeout lines; they do not establish
a vendor-side RCA. No timeout/config change was made to hide the degradation.
Native Calendar/Calendly/PagerDuty/Sentry account acceptance and full voice,
upload and recovery QA remain open; this retrieval smoke is not their proof.

Scheduling batch (2026-09-10): Google Calendar six tools and Calendly five tools
now have native request/response and result contracts. Calendar availability
refuses missing/error-bearing calendars; rescheduling preserves exact duration
and refuses implicit all-day conversion. Calendly cancellation requires a valid
acknowledgement and no longer asserts email delivery. Both expose pagination;
calendar names resolve from one bounded catalog. Calendly OAuth scopes now follow
current vendor documentation, including vendor-local write-to-read implications.
Local evidence: 196 function assertions across all eleven handlers, four real
guarded-client mutation/replay checks, and auth-resolution checks with real grant
and connection schemas. HTTP, credential lookup/decryption and receipt persistence
were substituted. Native scheduling account acceptance, browser use of these tools
and DB crash recovery are not claimed. No operator data or DB schema changed.
This batch is not yet in the running application image.

Scheduling milestone gates: full backend lint passed; full Pyrefly reported zero
errors with two existing suppressed diagnostics and two unrelated SOR cast warnings.
The expanded curated pre-commit hook passed. All 29 vendors/148 tool input schemas
still register and generate. Documentation verification passed (46 pages, 288 links,
1239 Python modules, 47 diagrams). Review checked domain/vendor boundaries, shared
grant and receipt ownership, request/result transformations, plan alignment and
readability once for the batch. Frontend builds and live vendor calls were not rerun
for this backend-only batch; deployment/acceptance remains a separate open gate.

Latest Google batch (2026-09-10): Google Docs four tools and Google Drive six
tools now use native request/response and result models. Docs traverses tabs,
uses native UTF-16/revision-checked append and validates update reply slots.
Drive validates list discrimination, continuation, folder identity and mutation
acknowledgements. Local evidence: 243 function assertions across all ten tools;
real guarded-client checks across all seven mutation handlers, including two
distinct receipts for document creation plus content, and no resend after an
accepted malformed acknowledgement. HTTP and receipt persistence were substituted;
live Google account acceptance remains pending.

Tasks/Dropbox batch (2026-09-10): eleven tools now use native request/response
and projection models. Reproduced and fixed null-filled successful mutations,
first-page-only list lookup and duplicate-name selection. Pagination is explicit;
Google task acknowledgements validate content/identity/status. Dropbox preserves
native IDs, uses direct-link preflight with declared read scope, reports actual
sharing visibility and stops asserting a fixed retention period. Local evidence:
319 function assertions; real guarded-client checks for seven mutation handlers
confirm one receipt per mutation and no resend after an invalid accepted response.
HTTP and receipt persistence were substituted; live account acceptance and DB
recovery are not claimed. This batch is not yet in the running application image.
Milestone review: vendor types stay at their owning adapter boundary; registry
still exposes 29 vendors/148 tools; existing grant/origin/outbound ownership is
unchanged. Pagination, omission and typed acknowledgements were traced from tool
input to request to result. Review corrected empty extension-filter omission and
refused an asynchronous deletion acknowledgement. Backend lint, full Pyrefly
(two pre-existing suppressed diagnostics), expanded curated hook and documentation
verification passed. No DB, migration, frontend or dependency changes were needed.

Current-build browser checkpoint (2026-09-10, 17:56–18:00 IST): rebuilt and
recreated only the four application services; DB/Redis volumes and operator
configuration preserved, Alembic remained `eylo0012`. Source fingerprints for
the execution/Google contracts matched in every application container. Console
lint/type/build and both widget builds passed (console bundle-size warning).
Using the existing Eylo Development org, the real widget created conversation
`01a08b48-b7f1-7c92-8f2e-efc322ab64ad`: memory recall and knowledge query succeeded,
`top_k=2` was persisted, Bedrock ranking was applied, and K1 identified Cedar
Lantern. The console showed the actual tool arguments/results and terminal
message states; a second widget turn retained that result without another query.
Groq conversation `01a08b4b-54f4-7f03-ac70-cbac4a5b427d` returned 493 for 29 × 17;
both messages were Completed in the console. The widget history listed both new
conversations. These are live text/retrieval proofs, not voice or vendor mutation
acceptance. Configured integrations is empty in this org, so no curated Google
account calls were attempted. Login succeeded despite a trapped Passlib/bcrypt
version-introspection warning; no password dependency change was made. Follow-up:
verify why the chooser offers the named background observer as a Start conversation
option before treating it as a confirmed eligibility bug.

CRM batch (2026-09-10): HubSpot six tools and Pipedrive five tools now use
native request/response and result models. HubSpot notes carry a durable,
retry-stable invocation timestamp. Pipedrive uses v2 CRM and v1 notes, separate
search/detail person shapes, batched person-name resolution and bounded stage
pagination. Local evidence: 154 HubSpot and 191 Pipedrive function assertions,
eight literal Pipedrive OpenAPI responses, guarded-client write/no-replay checks,
and actual executor-to-HubSpot timestamp propagation. Transport, auth lookup and
receipt persistence were substituted in those probes; native account acceptance,
DB crash recovery and current-build browser QA remain open. Backend lint,
Pyrefly, the curated-contract hook and documentation verification pass.

Status: implementation started; existing-enum cleanup, browser voice termination,
recording disclosure, telephony opener/transfer typing, and four curated vendors'
closed tool-input choices implemented. All eight LLM branches now have locally
verified native request/response paths. Canonical response content and progress
metadata have validated contracts; framework metadata serialization and critical
callback contracts, shared run state, conversation/approval resume identity, MCP
mutation authority, and durable-agent heartbeat ownership are locally verified.
Objective completion and scheduled/objective call capture now use owned contracts.
Telephony config resolution, explicit factories, and four carriers' credential
consumers are locally verified; the voice caller import regression is fixed.
Memory completion, embedding injection, and verification ports now have checked
contracts through formation and reconciliation callers; broader memory storage
and durable-job typing remains pending.
Widget responses and conversation prompt projections now have typed contracts
through SDK submission, DB filing/readback, memory-query selection and framework
input. Persisted interaction facts, finite message extensions and client-context
validation, voice duration and terminal speech outcomes now have typed boundaries;
session composition now validates construction and assignments without unrestricted
enrichment. Live voice capture and post-call projection now use validated models;
canonical failure codes retain their enum through DB readback and API output.
Framework tool observations now retain typed payloads through voice history and
durable replay; exact result correlation and private item serialization are
locally verified. Framework model blocks now retain typed text/reasoning/tool
variants through execution and replay; JSON history snapshots and same-response
tool-exchange ordering are locally verified through all eight LLM history formats.
Active message/input/approval observations and their pause continuations now have
typed contracts through runner output, durable filing/readback and voice capture.
Callback references use frozen Pydantic models and remain excluded from snapshots.
Reserved observation kinds without active producers remain finite JSON envelopes.
Product wait readback, approval decisions and all three resume continuation
projections now retain validated objects; pending/null answer semantics and
refusal before capacity reacquisition are locally verified.
Durable task locators, principal/claim snapshots, terminal receipts and human-input
wake notifications now use validated models. The real Absurd/PostgreSQL path was
verified through input suspension, an answer while the worker was stopped, and
graceful worker restart/resumption; general checkpoint payload typing remains open.
Reported usage, numeric model settings and budget meter inputs now have strict
contracts. SDK-to-budget and terminal message DB readback are locally verified;
missing usage remains distinct from a reported zero. Vendor stream assemblers,
shared tool buffers and Gemini replay now use validated Pydantic contracts; all
eight native SDK branches have repeated response and teardown checks. Effective
LLM generation, overrides, provider material and pinned runtime config now use
validated Pydantic contracts; encrypted persistence and revision readback are
locally verified. LLM verification now uses detached typed input/receipts,
native response validation, and short revision-checked DB transactions; all eight
SDK paths and authenticated API/DB outcomes are locally verified. Framework run
limits, copied settings, mutable context assignments and failure metadata now have
checked contracts. Framework control modes and their pipeline translations now use
owned enums; inactive settings carry explicit schema warnings. Ordered LLM-to-voice
segments and correlation now have validated Pydantic contracts. Platform agent/tool
identity metadata, conversation request correlation, and tool-message payloads are
validated through approval, live history, refresh and replay projections.
Generated next-turn tool history and scheduled/objective resumed exchanges now use
shared owned models, with private annotations excluded and native history format
parity verified. Terminal tool decisions, conversation completion/pause projections,
and objective completion/readback now have typed contracts with controlled-path
verification. Handoff outcomes, reference agreement and transcript attribution now
have validated contracts. Normalized realtime events and callbacks are locally
verified, including Gemini SDK translation. Realtime session snapshots and native
capability projections now use validated models and owned enums through browser
setup, verification and all three adapters. Effective realtime material now has
typed inference settings and credential variants, with shared session construction
and org/config identity agreement. STT/TTS material now has typed inference and
credential variants, shared verification/runtime composition and transport-only
media overrides. Requested config/revision agreement is checked for all three
voice capabilities. The stored voice carrier now has typed Pydantic settings,
private immutable secrets and explicit storage serialization; all 24 providers'
CRUD handoff/resolution contracts are locally verified. Remaining native STT/TTS factory
options remain open. ElevenLabs TTS now has native Pydantic wire contracts,
per-turn stream ownership and verified failure propagation through the TTS queue
runtime. Cartesia TTS now has native Pydantic contracts, context-scoped output
filtering, explicit finalization/cancellation and configured speed forwarding.
TTS factory dispatch uses its owned provider enum and returns the shared adapter
contract. Flat/nested TTS settings now normalize deterministically, and the seven
previously plain native config classes use frozen Pydantic models. The voice
runner carries the normalized object into factory construction. Hume now has
native request/output contracts, explicit end-input and per-turn stream ownership;
its fixed 48 kHz output is verified through the TTS queue path. Browser playback
and recording now share an explicit 16 kHz consumer contract, with native-format
conversion, resampler finalization and interruption reset locally verified.
Carrier conversion now shares TTS completion ownership; realtime output pins
actual turn format, flushes completion and discards interrupted/shutdown tails.
The carrier handoff is a Pydantic model with excluded live handles. Local audio,
setup and carrier-serialization checks pass; live provider/browser QA, reconnect
continuity and broader response correlation remain pending.
Call sessions now use validated Pydantic handles, immutable registry identity,
typed product metadata and explicit lifecycle modes. Stale removal, cancellation,
setup rollback and all four carriers' audio regressions are locally verified.
Canonical STT outcomes now remain validated objects through factory/runtime queues,
debounce and transcript handling. DTMF controls have a separate pipeline-owned
contract; batches retain segment identities and timing. Backpressure, terminal
child failures, cancellation and partial-startup cleanup are locally verified.
Native response contracts have replaced the intermediate adapter dict envelope;
the unused bridge is removed. Native configuration and lifecycle work remain open.
AssemblyAI, Cartesia, Speechmatics and Deepgram Listen v1 STT now have native
Pydantic request/response contracts;
acknowledgements, finality, errors, credentials and terminal iteration have
controlled-path checks. Cartesia deltas retain their spacing through factory,
debounce, the live transcript buffer and the agent callback. PCM encoding aliases
are translated at the vendor boundary, not passed through as vendor wire values.
Shared STT config, retry settings, capabilities and metrics now use Pydantic.
Factory/runtime configuration retains enum identity, strict values, native-option
privacy and retry settings across construction. Capabilities use adapter-owned
declarations. Vendor input codec is no longer confused with incoming transport
encoding. Retry settings now control bounded connection/readiness attempts and
explicit reconnect establishment, with cleanup before another attempt. Active
stream recovery and uncertain audio replay remain open. Eight WebSocket-based
adapters now translate HTTP/network establishment failures into socket-owned
failure kinds. AWS now has validated native options, exact SDK stream types,
owned partial-startup/cleanup tasks, observed early SDK failures, and typed native
error/EOF translation. Request/session IDs no longer masquerade as segment IDs.
AWS physical transport disposal now uses an owned HTTP/2 connection and has passed
local SDK/CRT socket checks. Signed input EOF now preserves final output through
factory/runtime forwarding, debounce and a live telephony rollback consumer.
Failed-start rollback keeps that consumer alive and attempts both provider closes.
Google STT now uses a frozen Pydantic config and the actual async SDK request and
response types. Local native TLS/gRPC checks cover readiness, EOF-only final
output, error propagation, verification, backpressure and cancellation. Factory
supervision preserves terminal reader failures instead of restarting a reader on
the same failed RPC. Canonical post-call persistence, live AWS/Google acceptance
and remaining native protocol failure classification remain open; these slices
do not establish complete voice lifecycle correctness.
Other generic provider envelopes and remaining native STT/TTS request/response/lifecycle
contracts still need completion.
Shared voice-task supervision now uses bound coroutine factories and typed task
registries; restart vetoes, child cancellation, acknowledgement-only queue drain
and STT parent cancellation are locally verified. Speech text/finalize requests,
Redis routing and queue consumption now retain validated Pydantic contracts;
policy capture, turn replacement and complete-response finalization are locally
verified. Native adapter cleanup and broader concurrent lifecycle contracts remain open.
OpenAI realtime now uses native request/event models
through frame validation, tool correlation and normalized manager capture. Nova
now has owned JSON wire/state contracts inside native SDK streams, including
content/tool correlation, EOF and cancellation-safe cleanup. Other producer
metadata, native STT/TTS requests/events and caller payloads remain open.
Budget task scopes and outstanding-capacity snapshots now use validated Pydantic
models; nesting, task isolation and cancellation restoration are locally verified.
Remaining known producer extension schemas and provider flows are open.
Remaining caller payloads and other platform flows are still pending. Scoped gates
are not whole-platform completion, and native transport fixtures are not live vendor QA.

Reviewed on 2026-09-07 against `5ab44c09`. This is a maintainer work plan, not a
claim that every proposed contract is already implemented. The progress section
below distinguishes completed slices from the original review findings.

## End goal

Closed domain choices remain typed from their producer to their consumer.
Named limits explain their purpose and units. Platform-owned payloads and known
vendor request/response shapes have explicit fields instead of requiring callers
to remember dictionary keys. This includes every provider and vendor in the
platform, not just SOR or curated integrations.

Acceptance criteria:

- Closed states, modes, outcomes, and failure categories use their owner's enum.
- Internal callers retain enum/object types; serialization happens at boundaries.
- Meaningful limits have one named owner. Equal numbers do not imply shared policy.
- Persisted and public values retain their existing spelling and meaning.
- Refactored paths pass type checking and source-to-sink verification.
- Dynamic customer/vendor fields remain supported. No new default provider/model.
- Types respect platform, product/profile, vendor, and standalone-framework
  boundaries; fewer duplicate literals must not mean tighter cross-domain coupling.
- Every executable vendor operation has a checked request, response/event, error,
  and consumer contract, including authentication, verification, discovery,
  pagination, callbacks, streaming, and durable readback where applicable.
- Existing SDK types retain their precision inside adapters. A typed config,
  agent input, or final canonical object alone does not satisfy this requirement.
- Work is selected by complete data flows and their dependencies. Literal/`Any`
  searches are secondary omission checks, never the implementation sequence.

### Browser QA completion gate

User requirement: after implementation and documentation updates, run the real
product through the widget and operator console, not only adapter probes.

1. Check/start the existing console and widget services; verify the API and
   workers are healthy. Identify the deployed build before attributing results
   to pending source changes.
2. Use the existing **Eylo Development** test organization and its configured
   providers. Read local login details from
   `test_organisation_credentials.txt__private` when needed; never copy secrets
   into documentation, screenshots, or retained QA artifacts. Do not reset or
   replace the organization or its provider configurations.
3. Navigate the widget's agent and conversation lists. Run fresh, uniquely
   identified conversations against agents with the relevant configured provider
   and tool bindings. Exercise the affected product flows, including tool
   results, citations, generated interactions, and history navigation where
   applicable. Prefer read-only external operations; use only explicitly
   authorized disposable targets for mutation checks.
4. Open each tested conversation in the console. Compare the widget outcome
   against persisted messages, tool inputs/results, terminal states, and errors.
   A plausible agent answer alone does not prove a tool executed successfully.
5. Record the tested build, conversation references, outcomes, and untested
   boundaries. Report missing configuration or human-only interaction separately
   from product failures. Browser smoke checks on an older running build do not
   close acceptance for undeployed implementation changes.

Readiness smoke check (2026-09-10): console `5173` and widget `5174` were already
running; the API health endpoint returned `200`, with the API, durable worker,
ordinary-task worker, and scheduler running. The existing authenticated console
session and widget contact session remained usable; no login credentials or
provider configuration needed changing. Running backend image:
`8c5c17de9edf78aaa260e387e4ef842f712bc7711cdfd764c966141aee82e243`.

The fresh widget prompt `QA_BROWSER_ACCEPTANCE_20260910` in conversation
`01a08910-4ce5-70a1-87bb-e09de648cb7c` invoked `memory_recall` and
`kb_query(top_k=2)`. Console readback showed three memories and one knowledge
result with citation `K1`; both returned successful Bedrock ranking metadata.
The widget displayed the matching Cedar Lantern answer. Console readback showed
43 persisted messages, including the new tool calls/results and final response
in Completed state. The configured background observer also completed; its
summary reported memory updates, so this is not a claim of a wholly write-free
run. Widget back-navigation returned to the conversation list; loading older
conversations expanded it from 10 to 15 entries, and the tested conversation
could be reopened. This check does not exercise pending Murf/Zendesk source changes, fresh
login, voice/media, uploads, or every configured vendor/tool.

## Evidence and limits

The following is the pre-implementation review baseline. See implementation
progress for subsequent checks.

- AST inventory: **1,212 first-party Python files** under `server/eylo`, `cli`,
  and `server/scripts`; dependencies, hidden directories, and build/cache output
  excluded. Candidate patterns include string comparisons, open dictionaries,
  boolean annotations, literal annotations, and numeric policy arguments.
- Targeted manual traces cover voice, telephony, campaigns, provider factories,
  curated integrations, retrieval, events, SOR, sandbox, scheduling, aggregate
  responses, and the local verification hooks.
- Existing Pyrefly project check: **1,172 diagnostics, 19 suppressed**. The largest
  reported categories were argument types (430), missing attributes (338), and
  overload matching (67). This is not a count of confirmed runtime bugs or of
  issues attributable to literals. Environment/stub issues require separate triage.
- A focused check of five candidate files reported two diagnostics, both in
  `pipelines/knowledgebase/query.py`: the boolean scope-parse sentinel and the
  `BaseException` result of `asyncio.gather(return_exceptions=True)` are not fully
  narrowed before consumption.
- This is broad static coverage plus selected full-path inspection, not a manual
  review of every function. No live vendor, worker-crash, DB, or browser QA was run.
- Review-artifact checks: documentation verification passed (46 pages, 252 local
  links); `git diff --check` passed. Only this plan and its documentation-index
  link were added; Python behavior and runtime state were not changed.

Commands executed from `server/`, through the repository's `rtk` wrapper:

```bash
rtk proxy .venv/bin/pyrefly check --output-format omit-errors --count-errors=10 --summary
rtk proxy .venv/bin/pyrefly check --output-format min-text \
  eylo/pipelines/telephony/sessions.py \
  eylo/modules/conversations/schemas/aggregates.py \
  eylo/pipelines/integrations_v2/vendors/github/tools.py \
  eylo/pipelines/knowledgebase/query.py \
  eylo/sockets/stt/factory.py
```

The broad scan also found substantial existing typed contracts. In particular,
the framework, AgentRun lifecycle, outbound effect outcomes, memory results, and
SOR canonical/command payloads are foundations to reuse, not replace.

## Choose the right replacement

| Meaning | Replacement | Boundary rule |
| --- | --- | --- |
| Closed state, mode, operation, policy | Owner-defined `StrEnum`/existing string enum | Validate incoming string once; use enum internally. |
| Vendor-defined integer code with a closed known set | Vendor-owned `IntEnum` | Translate at the adapter; define an explicit unknown-value policy. |
| Timeout, byte cap, batch size, queue capacity | Descriptive `Final` constant or existing effective config | Include units; name the policy, not the number. |
| Fixed payload with known fields | Pydantic model, frozen for immutable values | Validate on ingress/readback; serialize on egress. Internal placement alone does not justify a dataclass. |
| Action-dependent fields | Discriminated union of action-specific objects | Keep `Literal[Enum.MEMBER]` tags where useful. |
| Dictionary required by an SDK/API | Existing SDK type or `TypedDict` | Convert at the gateway; a `TypedDict` alone does not validate input. |
| Custom fields, schema-defined mappings, user text, arbitrary model IDs | Bounded JSON/string with appropriate validation | Do not invent an enum for an open value space. |
| Intrinsic predicate | `bool` | Keep predicates such as `is_empty`; do not encode a mode in flags. |

User clarification (2026-09-08): Pydantic is already part of the platform. Prefer
it for internal data contracts as well as ingress/egress models; retain dataclasses
only for a specific documented requirement. Preserve ownership, mutability,
live-resource identity and snapshot exclusion during conversion. Previously
verified dataclass increments are not exempt: revisit them along their data flows,
without treating a blanket decorator replacement as correctness evidence.

Constants alone do not improve type safety. `STATUS_FAILED = "failed"` passed
through `status: str` still permits any other string. Likewise,
`class StateKey(Enum): STATUS = "status"` does not make `dict[str, Any]` a typed
result. Prefer `result.status: ResultStatus`.

Do not create a platform-wide `constants.py` containing unrelated vocabularies.
Domain enums belong to the owning module/product. Genuine module/socket
contracts belong in `common/contracts`; vendor wire vocabulary belongs to its
adapter. `framework/` keeps its own types and zero `eylo.*` imports. Integration
and SOR adapters must not import each other's domain enums just because both
implement the same vendor.

### Required ownership boundary

User clarification: platform and vendor types must respect their separate
boundaries. This requirement governs every finding and implementation slice.

| Owner | Owns | Does not export inward |
| --- | --- | --- |
| Platform domain | Canonical lifecycle, outcomes, policies, events, and domain value objects | Dependencies on vendor enums, SDK models, or vendor error semantics. |
| Shared capability contract | Vendor-neutral inputs/results and protocols genuinely used across module/socket boundaries | A union of every vendor's private payload or options. |
| Product or SOR profile | Its canonical entities, relationships, tools, and workflow semantics | Assumptions that one vendor's entity/state vocabulary is universal. |
| Vendor adapter | Wire enums/codes, request/response models, SDK types, endpoint/scope constants, and vendor limits | SDK objects or vendor-specific state types in canonical domain signatures. |
| Pipeline | Config resolution, orchestration, and explicit translation between platform contexts | Vendor protocol logic or a new competing definition of domain state. |
| Standalone framework | Its own runtime and tool contracts | Imports from `eylo.*`; platform translation stays outside it. |

Required translation paths:

- Inbound: vendor payload → vendor validation → adapter mapping → canonical
  capability/profile object → platform policy and persistence.
- Outbound: canonical command → adapter mapping → vendor request object → wire.
- Failures: vendor code/exception → adapter classification → canonical failure
  contract → platform retry/recovery policy. Preserve original vendor detail in
  an explicit, safe diagnostic field when needed.

Equal spellings do not make types interchangeable. Two enums named `Status` may
represent different lifecycles; map them explicitly rather than aliasing them or
casting one to the other. Unknown vendor values need an explicit handling policy,
not a fabricated canonical state or silently successful fallback.

Curated integrations are deliberately vendor-specific: their public tool input
contracts may expose vendor choices owned by that integration. This does not
authorize those types to leak into neutral SOR tools or the core agent runtime.
Vendor configuration DTOs can likewise expose supported options without exposing
SDK classes or making platform policy depend on vendor-private types.

Platform budgets and vendor limits retain separate constants/config ownership,
even when numerically equal. An adapter translates or reports an unsupported
capability; it does not redefine the platform's voice, retry, or data policy.

## Findings and recommended changes

Priority means refactor order, not incident severity. The risks below describe
what weak contracts allow; they are not claims that each risk has occurred.

### A1. Voice termination and recording disclosure lose their types

Evidence:
[lifecycle policy](../../server/eylo/pipelines/voice/lifecycle_policy.py),
[browser pipeline](../../server/eylo/pipelines/voice/browser.py),
[realtime pipeline](../../server/eylo/pipelines/voice/realtime.py),
[WebSocket state](../../server/eylo/pipelines/websocket/schemas.py), and
[telephony session](../../server/eylo/pipelines/telephony/sessions.py).

- `browser_voice_session_status(reason: str | None)` classifies a raw-string set
  of normal endings. Producers use strings such as `silence_timeout`,
  `max_duration`, and `realtime_transport_ended`. An unrecognized spelling takes
  the failed-session branch.
- WebSocket recording disclosure is a `Literal`, while `CallSession` stores a
  plain string; [consent handling](../../server/eylo/pipelines/voice/consent.py)
  compares and assigns those strings across both runtime shapes.
- Session callbacks, runtime mode, direction, and provider identity also lose
  specific types. `CallSession.voice_config` and several collaborators use `Any`.

Plan: a shared voice termination vocabulary and disclosure-state enum across
the browser/carrier session boundary; reuse `VoiceRuntimeMode`. Retain the
existing [telephony end-reason contract](../../server/eylo/common/contracts/telephony.py)
and explicitly map voice reasons to it rather than silently renaming persisted
telephony outcomes. Use narrow session protocols for shared operations.

Verify: every current termination producer has a deliberate classification;
normal hangup, timeout, provider failure, interruption, and disclosure still
produce the same session/API/widget outcomes. Disclosure must not block recording.

### A2. Call lifecycle and campaign dispatch use string/dictionary protocols

Evidence: [call model](../../server/eylo/modules/telephony/models.py),
[lifecycle writers](../../server/eylo/modules/telephony/lifecycle.py),
[campaign voice adapter](../../server/eylo/products/campaigns/channels/voice.py),
and [scheduled call actions](../../server/eylo/pipelines/telephony/scheduled_actions.py).

- `opener_delivery_status` has a closed DB check constraint but a `Mapped[str]`
  annotation. `transfer_status` is also a string; lifecycle functions repeat its
  accepted values in transition guards.
- Campaign recovery checks `provider_status == "initiation-unknown"`; dispatch
  reads `response["status"]` and compares `unknown`/`succeeded`.
- The platform already has typed
  [outbound outcomes and attempt states](../../server/eylo/common/outbound.py).

Plan: owner-defined opener/transfer state enums; a typed call-initiation outcome
consumed by campaign and scheduled dispatch. Preserve the distinction between
canonical call state, outbound effect outcome, and raw provider-native status.
Do not force arbitrary vendor status/error text into a closed platform enum.

Verify: accepted, rejected, retryable, unknown, transferred, and cancelled flows;
especially that an unknown external effect is not accidentally retried. Read
historical rows before tightening persistence validation.

### A3. Agent tool choices are sometimes prose rather than schema constraints

Evidence: curated
[GitHub](../../server/eylo/pipelines/integrations_v2/vendors/github/tools.py),
[Freshdesk](../../server/eylo/pipelines/integrations_v2/vendors/freshdesk/tools.py),
[GitLab](../../server/eylo/pipelines/integrations_v2/vendors/gitlab/tools.py), and
[Intercom](../../server/eylo/pipelines/integrations_v2/vendors/intercom/tools.py) inputs.

- GitHub `SearchIssuesInput.state` and `ListPullRequestsInput.state` are `str`;
  their descriptions list `open, closed, or all`. `_state()` validates later.
  The input schema cannot provide an enum from this annotation.
- Freshdesk repeats string status/priority names and integer wire-code mappings.
- Other curated tools contain similar manually validated query choices.

Plan: vendor-owned input enums, distinguishing a query filter's `all` from an
entity's actual lifecycle states; integer wire-code enums where appropriate.
Keep user-defined Jira workflow names, IDs, labels, and custom properties open.
Also cover typed vendor requests, response envelopes/nested entities, errors,
and curated results for every registered vendor. Define output objects rather
than constants for JSON keys. The four completed input-enum slices below are
partial A3 work, not completed vendor typing. Follow the flow schedule below.

Verify: tool JSON Schema advertises exactly the supported choices; invalid input
is rejected before vendor I/O; preserve current normalization of accepted input.
Compare request serialization and mutation receipts. Consult current official
vendor docs before changing supported value sets, scopes, or request shapes.

### A4. Error categories and retry decisions need owner-defined contracts

Evidence: [event delivery service](../../server/eylo/events/durable/service.py),
[event workflow](../../server/eylo/events/durable/workflow.py),
[reranking errors](../../server/eylo/common/contracts/reranking.py), and
[storage errors](../../server/eylo/sockets/storage/base.py).

- `EventDeliveryService.record_failure(error_code: str, permanent: bool)` validates
  a fixed three-string set which its workflow also repeats.
- Socket exceptions commonly combine an untyped `code` with a retry-policy flag.

Plan: begin with `EventDeliveryFailureCode` and a named retry disposition at that
boundary. Extend the pattern to provider errors by capability, not one global
error enum. Keep user-facing explanation and original vendor code separate from
the platform failure category. Reuse existing exception subclasses when they
already express the distinction.

Verify: transient/terminal/unknown outcomes retain their retry, dead-letter, and
operator-message behavior. Do not reinterpret cancellation as retryable failure.

### A5. Durable job inputs and saved results need typed readback

Evidence: [event workflow](../../server/eylo/events/durable/workflow.py),
[scheduled run result](../../server/eylo/pipelines/scheduler/durable_execution.py),
[sandbox execution](../../server/eylo/pipelines/sandbox/tool_execution.py), and
[AgentRun persistence](../../server/eylo/modules/agent_runs/models.py).

- Event workflow parameters are a dictionary manually parsed into two UUIDs.
- `_run_result()` builds a bare dictionary with a `scheduled_agent` discriminator.
- `SandboxToolAction` already has an enum but mixes optional exec/read/write
  fields. Its outcomes still expose open `content`/`metadata` dictionaries.
- Typed AgentRun lifecycle fields coexist with open artifact/owner-kind fields.

Plan: per-workflow input/result objects and validated persistence decoders;
action-specific sandbox input variants. Type only platform-owned receipt fields;
keep genuinely arbitrary model output in an explicit bounded JSON field.

The existing [DB JSON serializer](../../server/eylo/common/database.py) can encode
Pydantic-compatible objects. It does **not** reconstruct those objects when JSONB
is read, validate historical dictionaries, or cover external SDK serialization.
Both directions need an explicit contract. Preserve checkpoint keys, fingerprints,
task names, versions, and already-enqueued payload compatibility.

Verify: enqueue → claim → serialize → load → resume → public result, including old
payloads, malformed payload refusal, cancellation, retry, and output-size limits.

### B1. Provider identity and effective config lose existing enum types

Evidence: [STT schemas](../../server/eylo/sockets/stt/schemas.py),
[STT factory](../../server/eylo/sockets/stt/factory.py),
[embedding factory](../../server/eylo/sockets/embedding/factory.py), and
[reranking factory](../../server/eylo/sockets/reranking/factory.py).

- `STTProvider`, `STTEncoding`, `STTTurnDetection`, and `STTEndpointingMode` exist,
  but `STTConfig` stores those choices as strings, often defaulting to `.value`.
- Factories dispatch on strings and reconstruct dictionaries from effective config.

Plan: carry existing enums through the effective config and factory; use typed
vendor-option objects for known fields. Preserve an explicit validated extension
map only where custom options are supported. Continue through each adapter's
request builders, SDK/HTTP responses, streaming messages, error mapping, and
consumer: stopping at the factory leaves the important wire boundary untyped.
Apply this to all capability vendors in the scope ledger below. Existing typed
SDK models should be retained rather than wrapped in redundant local copies.

Verify: configure → verify → bind → resolve → construct → execute → close for each
changed adapter. Keep credentials inside the adapter boundary and preserve config
revision/fingerprint semantics. Do not turn arbitrary model or voice IDs into a
closed enum, or replace an explicit factory with reflective registration.

### B2. Retrieval results and observations need typed fields

Evidence: [KB query](../../server/eylo/pipelines/knowledgebase/query.py),
[memory application](../../server/eylo/pipelines/memory/application.py), and
[ranking metadata](../../server/eylo/common/contracts/reranking.py).

- `_Search` annotates knowledgebase, adapter, and scopes as `Any`.
- KB results are dictionaries carrying a temporary `_local_observation` object
  which the outer wrapper removes. `_parse_scopes()` returns a list, `None`, or
  a boolean sentinel; the annotation admits `True` although only `False` is emitted.
- `RankingState` is typed, but shared reason codes and domain failure codes are not.

Plan: typed search context, query hits/result, and a separate internal result plus
observation object. Use explicit valid/invalid parsing or a local parsing exception
converted to the existing public refusal result. Use owner-defined ranking reason
codes where the set is closed. Keep KB/memory ownership and grants separate.

Verify: invalid scope does not widen access; top-k, citations, partial provider
failure, reranking fallback, and observation emission remain equivalent. Resolve
the two observed narrowing diagnostics without swallowing `CancelledError`.

### B3. Event vocabulary is repeated between emitters and timeline projection

Evidence: [session publisher](../../server/eylo/modules/user_sessions/service.py),
[timeline catalog](../../server/eylo/modules/user_sessions/timeline.py), and
[agent lifecycle listener](../../server/eylo/listeners/py_events/agent_lifecycle.py).

Plan: owner-defined event names and typed payloads shared by emitters and catalog
registration. Stop manually reconstructing closed lifecycle names in consumer
loops. Preserve existing event strings, legacy payload readability, and the
distinction between durable delivery and ephemeral notification.

Verify: each registered producer has a timeline definition; old and new payloads
render the same category/label/status. A typed name must not change ordering,
transaction, or durability guarantees.

### B4. Aggregate/API schemas erase domain types before client generation

Evidence: [conversation aggregates](../../server/eylo/modules/conversations/schemas/aggregates.py)
declare `AgentSummary.status: str` and `MessageSummary.kind: str` while other fields
already use domain enums.

Plan: carry the owning enum into aggregate DTOs. Repeat for provider, connection,
session, and job projections after locating the owning type. Keep serializer
values unchanged and regenerate the console/CLI contract when schemas change.

Verify: enum appears in OpenAPI and generated client types; real list/detail
responses validate; UI labels/casing remain presentation concerns.

### B5. Onboarding form vocabulary and policy flags

Evidence: [field schema](../../server/eylo/modules/provider_onboarding/schemas.py)
uses typed `Literal` choices for `kind` and `target`, but
[catalog helpers](../../server/eylo/modules/provider_onboarding/catalog.py) accept
plain strings. The schema also validates duplicated `target`/`secret` information.

Plan: shared field-kind/target enums through builders and consumers; avoid
weakening existing `Literal` validation. Review flags individually: modes,
capabilities, and retry policies merit enums; intrinsic field predicates such as
`required` and `multiline` do not automatically need a lifecycle enum. Derive
redundant internal properties where possible while retaining the API shape.

Verify: catalog-to-schema parity, conditional fields, secret placement, and the
existing provider form behavior. Public or stored boolean-to-enum migrations
require a separately specified compatibility change, not an incidental cleanup.

### B6. Finish SOR boundary cleanup without undoing typed canonical data

Evidence: [command payload validation](../../server/eylo/sor/runtime/command_payloads.py),
[Confluence adapter](../../server/eylo/sor/knowledge/vendors/confluence.py), and
[HubSpot adapter](../../server/eylo/sor/crm/vendors/hubspot.py).

The prior SOR work is present: canonical/command objects and explicit validation.
Remaining candidates include adapter vendor-key comparisons, response limits,
fixed wire vocabulary, and lifecycle strings. Discovered fields and mapping paths
are intentionally data-driven; the remaining dictionary count is not evidence
that canonical payload typing failed.

Plan: preserve typed registries and canonical/command payloads; type known vendor
request/response fields before their source-record mapping as well as remaining
closed choices. Include discovery, sync pages, exact-record fetch, mutations,
webhook registration/delivery, OAuth, and cursor/checkpoint readback. Keep raw
vendor JSON localized to parsing and an explicit bounded extension map for
custom fields, configured mapping paths, or forward-compatible provenance.
Do not generate a key enum for every discovered field or import curated tool
schemas into SOR canonical contracts.

Verify: catalog/payload parity, cursor round trips, custom mappings, canonical
projection, relation intents/resolution, command serialization, and agent tools.

### C1. Name operational limits and units

| Current location/value | Proposed ownership |
| --- | --- |
| `common/database.py`: `pool_recycle=3600` | Named DB pool recycle seconds, or existing DB settings owner if operator-configurable. |
| `modules/auth/services/session_service.py`: `timedelta(days=7)` | Named auth-session lifetime; preserve current duration. |
| `events/durable/workflow.py`: `heartbeat(seconds=120)` | Reuse the durable claim timeout if it is the same lease policy; otherwise name the event-specific policy. |
| `jobs/sor.py`: six recovery calls with `limit=100` | Named per-scan recovery batch policy, not an implied global concurrency cap. |
| `pipelines/scheduler/durable_execution.py`: `65536` result bytes | `MAX_SCHEDULED_AGENT_RESULT_BYTES`, shared with its validator/error description. |
| Integration OAuth exchange and refresh: `response_body_limit=262_144` | One OAuth response byte limit owned by that HTTP boundary. |
| Confluence: `response_body_limit=8_388_608` | Vendor-specific response byte cap. |
| STT/TTS queues, polling, frame timing, sample rates | Named queue/pacing policies and typed audio formats; do not unify vendor-specific rates merely because values match. |

Already-good examples: `DURABLE_CLAIM_TIMEOUT_SECONDS`,
`DURABLE_HEARTBEAT_INTERVAL_SECONDS`, outbound field-length limits,
`MAX_RERANK_CANDIDATES_PER_KNOWLEDGEBASE`, and sandbox byte/path/time limits.
Retain mathematical constants, indexing `0`/`1`, regex syntax, and fixed SDK
wire keys when naming would not add meaning. Prefer standard HTTP status types
over creating a second private HTTP code vocabulary.

Verify: exact old values and units; boundary-minus-one/at/plus-one checks;
unchanged retry/timeout behavior. Naming a limit does not authorize changing it.

### C2. Use existing enum members directly and enforce the types

Examples already have the right enum but compare serialized text:

- [Conversation runner](../../server/eylo/pipelines/conversation/conversation_runner.py):
  `result.status.value == "timed_out"` / `"max_turns_exceeded"`.
- [Agent lifecycle listener](../../server/eylo/listeners/py_events/agent_lifecycle.py):
  `event.outcome.value == "failed"`.
- [Memory pgvector adapter](../../server/eylo/sockets/memory/vendors/pgvector.py):
  `message.role.value == "user"`.

These are small, low-risk slices: compare enum members and keep `.value` at the
wire boundary. Do not cast a plain DB string and pretend it became an enum.

The project already pins Pyrefly in
[pyproject.toml](../../server/pyproject.toml), but
[local hooks](../../.pre-commit-config.yaml) run Python lint/import checks rather
than a Python type-check gate. Add scoped checks after each slice is clean;
expand toward the full project. Do not suppress all 1,172 diagnostics or claim a
clean baseline from a reduced error count alone. `Any`-heavy code may pass while
remaining weakly typed, so review producer/consumer annotations too.

## Review conclusions by axis

1. **DDD boundaries:** vocabularies need a clear owner. Reusing common contracts
   is useful; importing a domain module into a socket to reuse its enum is not.
2. **Architecture fit:** extend existing explicit factories, Pydantic contracts,
   dataclasses, and DTO projections. No generic schema engine or global enum registry.
3. **Data flow:** the biggest gaps are early serialization, unvalidated readback,
   duplicate state dictionaries, and policy represented by open strings/flags.
4. **Plan alignment:** SOR established the desired canonical-object approach. This
   request extends it platform-wide; it does not authorize new product behavior,
   replacing integrations, or changing persistence history.
5. **Maintainability:** reducing literal count is not the success metric. A reader
   should discover allowed values and required fields from a type, and a checker
   should catch an invalid caller before execution.

Security/performance constraints: preserve tenant/grant filters, refusal behavior,
secret redaction, and short transactions. Validate at boundaries, not on every
audio frame or repeatedly inside large SOR record loops. Enum/object conversion
must not add vendor I/O or turn bounded JSON into unrestricted payloads.

## Ordered implementation backlog

### Scope clarification: every vendor request and response

On 2026-09-07 the user clarified that request/response type definitions apply to
**all vendors and providers in the platform**. Plan the work sequentially through
product data flows, not by searching for random literals. This schedule supersedes
the earlier enum-first order; completed A1/A2 and partial A3 work is retained.
A4/A5 and B1–B6 are worked at each flow's boundary, not postponed until all enums
have been converted.

The gap is not simply missing annotations. For example,
[Freshdesk `_ticket_view`](../../server/eylo/pipelines/integrations_v2/vendors/freshdesk/tools.py)
looks up a root-level `email` after testing `requester_id`, while `get_ticket`
does not request requester embedding. Freshdesk documents requester email as
additional requester data, not part of the default ticket response
([official reference](https://developers.freshdesk.com/api/#view_a_ticket)).
Typing an invented optional `email` field would preserve the mistake. Each field
needs documented provenance and an operation that actually retrieves it.

### Inspection evidence and limits for this expansion

The planning pass followed the conversation runner and capability resolvers into
explicit factories, then examined representative adapter and sink paths:

- `FrameworkConversationRunner`/model adapter → LLM resolution → `LLMFactory` →
  native message transformation → `LLMResponse` → framework response/messages.
  [OpenAI](../../server/eylo/sockets/llm/vendors/openai.py) already imports SDK
  request/response types, but its message transformation exposes a broad
  dictionary return type and usage normalization takes `Any`.
- Curated registry → `execute_curated_tool` → input validation → auth →
  `GuardedVendorClient` → vendor handler → curated output/attempt receipt.
  Freshdesk inputs are typed; its wire bodies and response projections are not.
- KB/memory resolver → embedding/reranking adapter → retrieval result. The
  [Bedrock embedding adapter](../../server/eylo/sockets/embedding/vendors/bedrock.py)
  has typed config and vector validation but builds/reads native JSON dictionaries.
- Pinned voice config → STT/TTS factories or realtime factory → adapter events →
  voice manager. SDK-typed Gemini Live events already map to neutral events;
  [Deepgram TTS](../../server/eylo/sockets/tts/adapters/deepgram_adapter.py) still
  parses JSON control messages with dictionary keys. Binary audio is a different
  contract from those control messages.
- SOR registry → `SorSyncWorkflow._fetch_page` → adapter → encoded page →
  `_decode_page` → `_commit_page` → canonical projection/relationships. Vendor
  downloading and DB commit are separate. Freshdesk SOR's `_external_record`
  consumes raw mappings before typed canonical normalization. Existing canonical
  typing does not prove native response typing.
- Webhook ingestion verifies raw request bytes, parses vendor delivery, commits
  receipt/signals, then spawns work. Email delivery and MCP mutations use the
  outbound receipt authority. Storage/sandbox resolvers already expose useful
  typed interfaces; their SDK/protocol responses still need operation-level review.

The scope ledger below is verified against executable factory/registry wiring,
not a claim that every vendor method was manually reviewed. This expansion is
planning-only: no live provider calls, DB changes, dependency upgrades, or runtime
code edits. Latest vendor/SDK documentation and field-by-field verification remain
mandatory before implementing each vendor slice. Existing protocol versions must
be checked against their matching official docs; using current docs does not
authorize silently upgrading the protocol.

### Scope ledger: nothing implicitly excluded

Provider identity below names an implementation/configuration path, not live QA
coverage. A completed config or enum slice leaves request/response work pending.
Inspect all actual factory branches, including compatibility adapters and SDK
wrappers reached through them; do not declare a provider done from its catalog row.

| Capability | All current provider paths in scope | Executable authority |
| --- | --- | --- |
| LLM | Anthropic; Bedrock; Cerebras; Gemini; Groq; OpenAI; OpenAI Responses; Sarvam | [LLM factory](../../server/eylo/sockets/llm/factory.py) |
| STT | Amazon Transcribe; AssemblyAI; Cartesia; Deepgram; Deepgram Flux; Gladia; Google; Rev AI; Sarvam; Speechmatics | [STT factory](../../server/eylo/sockets/stt/factory.py) |
| TTS | Amazon Polly; Cartesia; Deepgram; ElevenLabs; Groq; Hume; Murf; OpenAI; Rime; Sarvam; Smallest AI | [TTS factory](../../server/eylo/sockets/tts/factory.py) |
| Realtime | Amazon Nova Sonic; Gemini Live; OpenAI Realtime | [Realtime factory](../../server/eylo/sockets/realtime/factory.py) |
| WebRTC credentials | Metered; Turnix | [STUN/TURN factory](../../server/eylo/sockets/stun_turn/factory.py) |
| Telephony | Twilio; Plivo; Vonage; Exotel | [Telephony factory](../../server/eylo/sockets/telephony/factory.py) |
| Email | SMTP; SendGrid | [Email factory](../../server/eylo/sockets/email/factory.py) |
| Storage | S3; local filesystem | [Storage factory](../../server/eylo/sockets/storage/factory.py) |
| Embedding | Bedrock; OpenAI-compatible; Voyage | [Embedding factory](../../server/eylo/sockets/embedding/factory.py) |
| Reranking | Bedrock; Cohere; Voyage | [Reranking factory](../../server/eylo/sockets/reranking/factory.py) |
| Memory | PostgreSQL/pgvector, including its configured LLM and embedding dependencies | [Memory resolver](../../server/eylo/pipelines/memory/resolver.py) |
| Sandbox | Docker | [Sandbox resolver](../../server/eylo/pipelines/sandbox/resolver.py) |

Additional adapter surfaces are equally in scope:

- **Curated integrations:** all 29 entries in
  [`_VENDOR_MODULES`](../../server/eylo/pipelines/integrations_v2/registry.py):
  Airtable, Asana, Calendly, Confluence, Dropbox, Freshdesk, GitHub, GitLab, Gmail,
  Google Calendar, Google Docs, Google Drive, Google Sheets, Google Tasks,
  HubSpot, Intercom, Jira, Linear, Notion, Outlook, PagerDuty, Pipedrive, Sentry,
  Shopify, Slack, Stripe, Typeform, Zendesk, Zoom. Include every registered tool,
  not only the four vendors already receiving input enums.
- **SOR:** all 11 executable profile/vendor registrations in
  [`get_sor_registry`](../../server/eylo/sor/runtime/catalog.py): CRM—HubSpot,
  Salesforce; ticketing—Jira, Linear, GitHub; support—Zendesk, Intercom, Freshdesk;
  knowledge—Confluence, Notion, Linear Documents. Linear's two profiles and the
  curated/SOR implementations of the same vendor require distinct consumer proofs.
- **KB storage:** PostgreSQL FTS and pgvector through the
  [KB resolver](../../server/eylo/pipelines/knowledgebase/resolver.py). These are
  not the SOR knowledge profile and must not be conflated with it.
- **MCP:** initialize, tool discovery/pagination, call results/errors, and session
  lifecycle through [MCP execution](../../server/eylo/pipelines/mcp/execution.py)
  and the [client](../../server/eylo/sockets/mcp/client.py). Dynamic server tool
  arguments/results follow their advertised schemas; don't invent static classes
  for unknown tools. The known MCP protocol envelope remains typed.
- **Cross-cutting protocol paths:** provider verification/discovery and credential
  resolution; integration/SOR OAuth exchange, refresh, revocation where implemented;
  webhook registration, renewal, verification, ingress, and delivery; HTTP, SDK,
  streaming, binary/media, XML/form, and local/DB responses as applicable.
- **Future/planned vendors:** the same definition of done applies when they become
  executable. This work does not implement roadmap-only SOR/messaging vendors or
  assert support merely because a candidate exists in a catalog.

### Repeatable vertical slice for one vendor operation

Complete these steps in order, then move to the next operation/vendor. Known
contracts may be reused, but a shared SDK does not prove all vendors using it
have identical fields, error bodies, usage, or stream semantics.

1. **Trace:** name the public/tool/job entrypoint, authority resolver, adapter
   method, transport, parser, mapper, consumer, and persistence/event/API sinks.
   Follow calls in both directions; include verification/background callers.
2. **Document:** record the implemented API/SDK version, official operation docs,
   request/response examples, field provenance, and current compatibility behavior.
   Cover path/query/header/body, success, pagination, error, and callback shapes.
3. **Define:** reuse the neutral domain result and existing precise SDK type;
   add a vendor-owned request/response schema only where one is missing. Model
   nested objects and tagged variants, not a dictionary with enum keys. Keep
   request and response models distinct where the vendor distinguishes them.
4. **Translate outbound:** construct typed requests from validated domain inputs;
   serialize at SDK/HTTP dispatch with intentional aliases, omission/null behavior,
   ordering, bytes, and numeric values. Preserve request fingerprints and receipts.
5. **Translate inbound:** validate raw responses once before mapping, or use the
   SDK's already validated result. Keep required, optional, nullable, and absent
   fields distinct. Translate native failures before platform retry decisions.
6. **Carry through:** retain types into the actual consumer, events, and stored
   result. Explicitly decode DB JSON/checkpoints on readback; the DB serializer
   only solves writing. Keep historical payload compatibility deliberate.
7. **Prove:** run function-level request/parse/map/round-trip checks plus scoped
   type checking; inspect the runnable product path and its sinks. Record live
   QA separately from substituted transports. Remove temporary probes before commit.

For each operation, record a compact evidence row in this plan as it is completed:
`entrypoint; provider/method; version/docs; request type; response/event type;
error type; canonical consumer; saved/public result; checks; unexercised branches`.
Until that row is supported, its status is **pending**, even if its config or
input enum is complete. This is a documentation ledger, not a new runtime registry.

Contract rules for all slices:

- Raw JSON belongs only at decoding/encoding and explicit bounded extension
  fields. Open model IDs, discovered custom fields, GraphQL selections, and user
  content are not closed enums. Known consumed fields use attributes.
- Request validation must reject programmer mistakes without silently dropping
  fields. Response parsing tolerates documented extension fields without making
  required fields optional or inventing a successful default. Specify unknown
  event/status handling per vendor; don't reject valid custom status values merely
  because input tools expose a smaller built-in set.
- Preserve precise SDK request/response types where available. For dict-based SDK
  arguments, `TypedDict` can express the SDK call; it is not runtime validation of
  network JSON. Do not weaken a model back to `Any` at the next function.
- Use vendor-local tagged models for structured stream control/events. Binary
  audio/files stay bytes/streams with format/size metadata; don't wrap or repeatedly
  validate every audio frame with a JSON model. Bound parsing and allocation cost.
- Validate signatures against original webhook bytes before conversion. Keep
  secrets, provider-controlled error bodies, and sensitive data out of model reprs,
  validation-error logs, and public projections. Preserve origin and path policy.
- A malformed response after a mutation may follow an accepted external effect.
  Record/classify that result through the existing outbound authority; never let a
  new schema exception trigger a duplicate send or hide the effect's known state.
- Typed nested data does not authorize extra lookups. Any enrichment—such as
  requester email—must identify the documented retrieval path, bounds, additional
  API cost, and missing/forbidden-data behavior. Avoid N+1 and vendor I/O in DB
  transactions. Semantic corrections are separate from exact-parity refactors.
- Compare before/after request count, page/batch size, parser allocation/time,
  response size, and transaction duration for the affected flow. For voice, also
  compare event throughput and buffering/teardown latency with representative
  binary streams. Preserve existing bounds; don't invent a platform-wide numeric
  performance target or claim live latency from an in-process substitute.

### Flow-based execution schedule

Each row is a milestone containing operation-sized slices, **not** one large
refactor. Define a slice's contracts before changing its producers and consumers.
Repeat its entire path for every provider in the scope ledger; reuse already
proven contracts without repeating unrelated reviews.

| Order | Flow, starting point, and dependency | Complete path / first slice | Acceptance and QA gate |
| --- | --- | --- | --- |
| F0 | Per-flow setup and field provenance; start now | Onboarding/config or installation/source authority → verification/auth → effective config. Start with Freshdesk's existing tool entrypoint and declared auth; B5/B1 work follows each provider. | Explicit operation/type inventory; matching-version docs; no inferred provider or widened grant. |
| F1 | Freshdesk curated vertical slice; depends on F0 | `execute_curated_tool` → Freshdesk `get_ticket` → typed ticket/requester/conversation response → curated result. Then search, create, update, reply, private note, errors, and receipts. | Documented requester provenance, absent/null behavior, no hidden N+1; serialized request parity; no replay after an accepted mutation. |
| F2 | Text agent inference; after the pilot contract pattern | Conversation `generate` → pinned LLM resolver → factory → messages/tools/request → SDK response or stream → `LLMResponse` → framework messages/tool calls/usage. Start with OpenAI SDK type preservation, then every LLM branch, including background prompt callers. | Text and tool turns, stream assembly/final response, refusal/error/usage, history/cache compatibility, cancellation and closed clients. No vendor types in the framework. |
| F3 | Agent external tools; depends on F2 for live agent QA | Curated `PlatformToolExecutor` dispatch → grant/auth → remaining vendor handlers → response/results → durable receipt → agent continuation. Resolve the recorded GitLab path-policy finding before its named-project QA. MCP is a separate protocol slice in the same tool flow. | Every registered tool inventoried; OAuth/refresh and pagination included; isolation, error/output serialization, approval/effect safety, and real conversation projection. |
| F4 | File/object I/O; before KB uploads and recording completion | [Storage runtime](../../server/eylo/pipelines/storage/runtime.py) → S3/local adapter → write/read/stat/delete/signing outcomes → `StorageLocator`/owner projection. Start with one upload and readback. | Byte/stream integrity, root/org/resource namespace, response/error validation, exact pinned location, cleanup, no signed URL/credential leakage. |
| F5 | Retrieval and learning; depends on F2/F4 where used | Embedding request → indexed vectors; reranking request → ranked indices; KB ingestion/query/reindex and memory remember/recall/refresh/forget/formation/reconciliation → grants/owners → results, citations, observations and durable readback. Start with Bedrock embedding → KB ingestion/query. | Every embedding/reranker and both KB stores covered; count/dimension/index validation, finite numbers, top-k/citation/source identity, config-revision parity, memory expiry/conflicts, cancellation and fail-closed grants. |
| F6 | SOR native-to-canonical loop; reuse established HTTP/storage seams | Source auth/discovery → sync page or exact fetch → vendor response model → `SorExternalRecord` → canonical object/relations → grid/detail/agent read; agent command → vendor request/result → receipt → resync. Start with Freshdesk support, then the other registered profile/vendors. | Every selected stream and command covered; custom mapping and links survive; pagination/checkpoint/restart, dependency DAG and eventual relation resolution; no extra I/O or long transactions. |
| F6a | SOR change ingress; follows each F6 vendor, not an afterthought | Register/renew webhook or existing poll-only path → raw signature verification → typed vendor delivery → signal/receipt → exact fetch or stream sync → same projection. Include OAuth exchange/refresh and reauth outcomes for that source. | Event identity/account routing, deduplication, delete vs update, stale/reordered events, malformed delivery, expired credentials, no sync feedback loop. Don't invent webhook support for poll-only vendors. |
| F7 | Browser voice; depends on F2/F4 | WebRTC credential fetch/SDP/ICE → pinned voice config → STT request/events → transcript → LLM → TTS request/audio/control events → playback. Start with one complete decomposed pipeline, then every STT/TTS branch. | Typed session/config/event queues; live transcript, completion vs playback drain, interruptions, silence timing, disconnect, and recording result; browser and server projections agree. |
| F7a | Realtime voice; shares F7 transport/sinks | Realtime factory → session setup/audio/tools/update → native stream variants → `RealtimeEvent` → manager/tool dispatcher/playback/transcript/teardown. One complete vendor at a time. | All three realtime vendors; tool-call IDs, audio formats, turn completion, interruption/resumption, usage/errors, teardown; primary voice config remains fixed across handoff. |
| F8 | Carrier and message delivery products; uses F7 voice/F4 storage | Telephony initiation/callback/media/control → call lifecycle/recordings/campaign and scheduled outcomes; email `send_organization_email` → SMTP/SendGrid request/result → receipt → tool/campaign result. First preserve typed call initiation through a carrier response. | All four carriers and both email providers; callback auth/form/XML/JSON mapping, accepted vs delivered vs unknown, cancellation/transfer, short transactions, no accidental resend. |
| F9 | Durable agent sandbox work; depends on F2/F3/F4 | Agent/tool/job → sandbox authority → Docker create/exec/read/write/export/restore/destroy → typed results/checkpoint/artifacts → release/wait/resume. Follow scheduler, AgentRun and outbound task payloads at the same time. | Vendor response/session identity, bounded binary/exit results, grant recheck, checkpoint compatibility, cancellation/restart/lease loss, cleanup; waiting releases runtime capacity. |
| F10 | Cross-flow completeness and gates; not deferred consumer implementation | Reconcile every factory/registry operation against the evidence ledger; inspect remaining event/aggregate/job projections and policy limits (B3/B4/C1). | Every branch has evidence or an explicit blocker; no config-only completion; documentation/type/client checks, no new suppressions, all affected product sinks exercised when runnable. |

Suggested order within remaining curated vendors: complete the support family
(Zendesk, Intercom after Freshdesk), issue/project family (GitHub, GitLab, Jira,
Linear, Asana), CRM (HubSpot, Pipedrive), documents/files/tables (Confluence,
Notion, Dropbox, Google Drive/Docs/Sheets, Airtable), communication/scheduling
(Gmail, Outlook, Slack, Google Calendar/Tasks, Calendly, Zoom), then operational/
commerce/forms (PagerDuty, Sentry, Shopify, Stripe, Typeform). All remain pending
for full request/response coverage. Grouping aids review, not shared vendor models.

For SOR, finish each profile's read/sync/write/webhook cycle before moving on:
support → ticketing → CRM → knowledge. Use existing configured Jira, Confluence,
Linear, HubSpot, and Zendesk for bounded live QA when still available; configuration
presence must be rechecked, and a vendor without credentials is not live-verified.

Do not freeze independent work when one vendor's live QA lacks credentials.
Record that vendor's exact missing proof and continue the next complete slice.
Do not convert this schedule into a platform-wide rewrite before exercising the
first vendor path.

Likely scope: local enum comparisons are small; each state/result/factory slice
is medium and may cross several files. The whole-platform effort is deliberately
not one refactor or one review. Run the five-axis review at major runtime/tool/
retrieval milestones; ordinary slices need focused verification, not repeated
full-platform reviews.

### Approval and external-input boundaries

- The user approved beginning implementation after the review and clarified that
  platform/vendor type ownership is mandatory. Only the completed slices below
  have been applied; this is not completion of the whole-platform backlog.
- The latest request authorizes this all-vendor plan expansion. It does not by
  itself authorize live external mutations, provider configuration changes, a
  protocol upgrade, stricter historical-data rejection, or a deployment.
- No credentials are needed for the inventory, typing baseline, or serialization
  probes. Live provider QA later uses the existing configured development org.
- Any real external mutation or user media/OAuth interaction needs the appropriate
  QA authority/input; don't manufacture provider coverage from mocks.
- Historical unexpected DB/job values need a deliberate compatibility decision
  before stricter validation is deployed.
- A storage-shape change needs a new incremental migration. No migration reset,
  DB reset, history compression, dependency upgrade, or deployment is implied.

### Definition of done for each slice

- [ ] Each new type/constant has a declared owner; imports respect that boundary.
- [ ] Every used operation/variant is in the evidence ledger, with matching-version
  vendor documentation and actual field provenance, not only a config/input model.
- [ ] Request body/query/path/header and response/error/event types cover the
  operation; SDK types are reused without leaking or being erased at the next call.
- [ ] Adapter mappings cover known vendor values and an explicit unknown-value
  path; domain signatures do not depend on vendor SDK/private types.
- [ ] Producer, transformations, consumer, DB/job readback, and public projection traced.
- [ ] Existing values preserved, including casing, JSON keys, omission/null semantics,
  hashes, config revisions, and task/checkpoint identities.
- [ ] Invalid/unknown input handling specified at the appropriate boundary.
- [ ] Scoped type check passes; no broad `Any`, casts, ignores, or magic-key constants
  added to make errors disappear.
- [ ] Exact changed branch verified with real domain types and boundary-sized probes.
- [ ] Public/runtime path exercised when runnable; missing live QA explicitly recorded.
- [ ] Temporary function checks cover valid, missing, nullable, malformed, and
  extension fields plus serialization/readback. Product behavior changes receive
  human review before new behavioral assertions are authored; prior review may
  cover unchanged behavior. Neither mock QA nor type checking counts as live proof.
- [ ] Relevant lint/docs/client checks pass; temporary probes removed before commit.
- [ ] No new cross-layer dependency, transaction extension, or per-frame validation cost.

The initial completed sequence was direct enum reuse, voice termination, and
telephony outcomes. The F0–F10 flow schedule now governs remaining work; the
following progress entries retain the evidence and limitations of earlier slices.

## Implementation progress

### Completed: direct enum reuse

- Conversation terminal responses compare `RunStatus` members and accept a typed
  `RunResult`; the standalone framework remains independent.
- Agent completion listeners compare `AgentLifecycleOutcome` directly.
- Memory query selection compares the shared `MemoryMessageRole`, without adding
  a module import to the pgvector adapter.
- Executed QA: all eight run statuses, both lifecycle outcomes, latest-user query
  selection, assistant-only fallback, and empty-exchange refusal.

### Completed: browser termination contract, first part of A1

- Added `BrowserVoiceTerminationReason` with the 28 existing terminal observations.
- Updated WebSocket runtime state and its shared structural port, browser and
  realtime callbacks, WebRTC peer/signaling translation, client hangup, disconnect,
  and the browser end-call tool path.
- Kept telephony's `CallEndedReason` separate. No vendor SDK/private types were
  added to common contracts; native peer/ICE strings remain inside their mapping.
- Replaced dynamic STT/TTS failure strings with an explicit capability-to-reason
  map. Signaling and transcript sinks still receive the exact existing strings.
- Added a local pre-commit/pre-push type-check gate for the two shared contracts
  and lifecycle policy. This gate does not claim the larger pipelines are clean.

Executed QA used the real session models and termination orchestration with
in-process substitutes for signaling, provider notification, and persistence sinks:

- All 28 reasons retain their serialized value and previous status classification.
- Each reason reaches signaling and transcript sinks; recorder finalization and
  terminal persistence occur once; repeated termination preserves the first reason.
- Cancellation of an awaiting caller does not cancel the session-owned teardown;
  a second caller joins it without duplicate cleanup.
- STT/TTS task failure callbacks receive typed reasons; peer terminal delivery is
  idempotent; unknown internal enum input is rejected by the session schema.
- Native peer/ICE mappings preserve known values and do not invent a mapping for
  an unknown state.

Verification: repository Python lint passed. Shared contracts, lifecycle policy,
and the completion listener have zero scoped Pyrefly diagnostics. The broader
voice file group went from 158 pre-existing diagnostics to 147 after declaring
termination fields on the shared session port. The runner/listener/memory file
group remains at its pre-existing 65 diagnostics. No suppressions were added.

Final project check: 1,161 diagnostics, down from 1,172; the existing 19
suppressions are unchanged. Documentation verification passed (46 pages, 252
links), `git diff --check` passed, and pre-commit configuration validation plus
the new voice-contract hook passed when triggered by a browser pipeline change.

Milestone review:

1. DDD boundaries: framework types stay independent; the memory socket imports
   its neutral contract; browser and telephony termination types remain separate.
2. Architecture fit: the existing session owner still owns teardown. The shared
   structural port declares its existing fields; no new runtime authority exists.
3. Data flow: producer-to-callback-to-session-to-signaling/transcript paths retain
   old values, first-reason selection, cancellation, and single-finalization behavior.
4. Plan alignment: only enum reuse and the browser termination part of A1 are
   complete. Recording disclosure, telephony states, and later slices remain open.
5. Clean code: explicit mappings replace string construction; no casts, new
   suppressions, dependencies, DB operations, or per-audio-frame validation were added.

Not exercised: live provider sessions, microphone/WebRTC media, real DB writes,
or worker/restart QA. No deployment, migration, DB reset, or commit was performed.

### Existing policy finding, not changed by this refactor

`agent_ended_call` is produced by the browser end-call tool but is absent from the
classifier's normal-ending set. It therefore records `VoiceSessionStatus.FAILED`.
The enum parity probe confirms this is pre-existing behavior. Resolving that
classification is a separate behavior change, not part of the value-preserving
typing slice; do not accidentally change it while extracting enums.

### Next slices

1. A2 is complete for the planned opener, transfer, and call-initiation contracts.
   A3 now covers GitHub, Freshdesk, GitLab, and Intercom's identified closed
   choices, not their full vendor request/response contracts. F1's Freshdesk
   curated-tool contracts are now implemented and locally verified below;
   live Freshdesk QA remains unavailable without a configured installation.
2. Follow F2–F10 for the rest of the platform. Carry A4/A5 errors/durable readback
   and B1–B6 config/retrieval/event/SOR work with each affected flow. The recorded
   GitLab named-project transport finding remains open and gates that QA path.
3. A1's termination/disclosure contracts are complete, not every session field
   or provider event. Widen local typing gates only as each owner/consumer slice
   passes; preserve the earlier baseline rather than claiming global completion.

### F1: Freshdesk curated-tool contracts implemented; live QA pending

Scope: six curated tools in
`server/eylo/pipelines/integrations_v2/vendors/freshdesk/`. This does not mark
the separate Freshdesk SOR adapter, remaining curated vendors, or the rest of
the provider plane complete.

**RCA and corrected data flow**

- The earlier enum-only work validated agent choices but left vendor payloads
  untyped. Its synthetic replies did not prove which endpoint actually provided
  a field. `requester_id and email` lost documented nested requester email;
  requester email was also interpolated into an undocumented search-index field.
- Baseline probes reproduced both defects and a third: HTTP 404 with `{}` was
  projected as a successful ticket with a null ID. Malformed list members were
  silently dropped. These are runtime defects, not annotation-only findings.
- `schemas.py` now owns consumed Freshdesk v2 requests, responses, nested
  requester/conversation objects, error envelopes, enums, limits, and results.
  Request construction rejects unknown fields; response parsing tolerates
  unrelated vendor fields but rejects malformed consumed fields. Existing
  status/priority normalization and unknown native numeric response codes remain.
- Agent input → typed vendor request → existing guarded HTTP client → typed
  vendor response → typed projection → JSON tool result. SDK/platform contracts
  do not import these Freshdesk types. No SDK replacement or new dependency.
- List/detail request requester embedding and use `requester.email`, checking
  its ID against `requester_id`. Index/mutation responses lacking embedding return
  null email. No speculative root-email fallback, contact N+1, or enrichment
  read after a mutation.
- Email filters use the documented list endpoint; status/priority filters use
  the index when email is absent. Combined requester filters scan at most ten
  list pages. Indexed reads paginate in 30-item pages up to the requested limit.
  Results expose coverage; tool guidance states the recent-ticket window and
  index lag. This is a deliberate correction beyond behavior-preserving typing.
- Conversation mapping uses private/incoming/source fields rather than treating
  every non-private entry as an outgoing reply. Private-note responses must
  confirm private visibility. Read/update/conversation IDs are checked against
  the requested ticket. Errors are sanitized and never interpreted as success.
- Mutation JSON field order, numeric enum encoding, empty-tag omission, null
  omission, operation sequencing, and fingerprint construction remain unchanged.
  Parsing occurs after the outbound owner records its send outcome; it does not
  introduce a retry authority or move provider I/O inside a transaction.

**Verification and limits**

- Freshdesk v2 primary API documentation checked for embedding, ticket listing,
  search supported fields/page limits, mutations, conversations, and errors.
  Installed Pydantic is 2.11.10. Wire booleans retain their vendor meaning;
  existing public boolean inputs/outputs were not replaced incompatibly.
- 113 executor/contract checks passed across six tools, 12 registry/agent/Bedrock
  schema projections, and 61 mutation dispatches with fingerprint assertions.
  Includes malformed/missing/null data, unknown codes, combined/paged filters,
  scan bounds, source/requester mismatches, private/public/incoming messages,
  sanitized failures, disabled grants, invalid inputs, and cancellation.
- Four mutation types passed an additional checkpoint replay probe: four sends,
  four replays, zero duplicate sends. The actual outbound execution/readback
  functions ran; DB persistence and checkpoint storage were substituted.
  Existing limitation: the shared client does not persist the vendor response
  body, so replay returns `vendor_outcome_unknown`, not a reconstructed success.
  That remains a shared F3/A5 readback concern, not a new regression.
- The initial QA probe incorrectly looked for credentials in public headers;
  source inspection confirmed they stay in origin-bound headers until transport
  attachment. The probe was corrected; no credential-boundary change was made.
- Focused review, sequentially: DDD ownership → architecture fit → complete
  data flow → plan/behavior drift → readability, security, and bounds. The review
  added private-note visibility confirmation; no new cross-domain coupling.
- Scoped Pyrefly and full server/CLI Ruff checks passed. The local curated-tool
  typing hook now covers the entire Freshdesk adapter folder.
- Read-only development DB check found **zero active Freshdesk installations**.
  Vendor HTTP, grant resolution, and persistence were substituted in local QA;
  this is not live Freshdesk, widget/LLM conversation, or DB durability proof.
  Human product review and live account QA remain pending. No operator data,
  credentials, migrations, Git history, or running services were changed.

### F3 progress: Zendesk curated native contracts

2026-09-10: completed the request/response typing slice for all six curated
Zendesk tools. This is separate from Zendesk SOR and does not close F3 or F10.

Authority: current Zendesk Ticketing v2 references for
[tickets](https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/),
[comments](https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_comments/),
[search](https://developer.zendesk.com/api-reference/ticketing/ticket-management/search/)
and [users](https://developer.zendesk.com/api-reference/ticketing/users/users/).
The large ticket/user pages exceeded browser-fetch limits; targeted official
search excerpts supplied the relevant operation and field definitions. No SDK,
credential, scope, API version or provider configuration changed.

Flow: registered input → `execute_curated_tool` → installation/tool grant and
connection resolution → `VendorToolContext` → `GuardedVendorClient` → relative
native request → typed envelope/entity → curated result JSON → conversation tool
result. Native models remain under `vendors/zendesk/schemas.py`, not module or
SOR canonical contracts. No DB transaction or per-record request was added.

| Tool | Request and response authority | Consumer/result and I/O bound |
| --- | --- | --- |
| `search_tickets` | `ZendeskSearchQuery` → `ZendeskTicketSearch` | Typed ticket views; one search page, configured limit ≤100 |
| `get_ticket` | Integer ticket path + `ZendeskCommentsQuery` → ticket/comments envelopes | Typed detail; one ticket read plus optional first 30 comments |
| `find_user` | `ZendeskUserQuery` → `ZendeskUsers` | Typed found/missing variant; one page, case-insensitive exact email match |
| `create_ticket` | `ZendeskCreateRequest`, nested requester/comment → ticket envelope | Typed ticket view; one durable mutation, no requester lookup |
| `update_ticket` | `ZendeskUpdateRequest` → ticket envelope | Optional one user read, one durable mutation; empty tags replace |
| `add_comment` | `ZendeskAddCommentRequest` → ticket envelope | Typed comment outcome; one durable mutation, explicit public predicate |

All paths share named error codes. Invalid native payloads produce
`vendor_response_invalid`; HTTP/vendor rejections produce `vendor_rejected`
without raw diagnostics. Ticket responses must match the requested identity.
Baseline probes reproduced missing comment lists becoming empty and absent
mutation ticket receipts becoming successful null-status results. Both now fail
explicitly. Known consumed fields use attributes; no `Any` or `.get()` remains
in this curated vendor's tool implementation.

Input schema change: status/priority are named enums with prior case/whitespace
normalization and empty-string omission. IDs/limits reject boolean coercion.
Existing `public` and `include_comments` tool keys are retained as strict JSON
predicates; no silent migration to renamed visibility options. Unknown native
status/priority/role/channel strings remain readable. Outbound fields are closed;
native extensions are ignored. Nullable values, clipping and request ordering
remain deliberate.

Verification on installed Pydantic 2.11.10: 76 assertions, including 12 valid
before/after scenarios comparing request bodies, counts and result values;
malformed/null/list/member/ID/visibility/enum/error cases exercise typed refusals.
A local parsing sample took 13.23 ms for 100 repetitions of a 100-ticket response;
this is parser-only timing, not native latency or a product-throughput benchmark.
Guarded-client probes use real egress request construction and parsing,
with substituted transport and receipt persistence: malformed successful mutation
reply produces a tool error after one recorded send; replay does not send again;
read authority refuses mutation. This is not a real DB crash-recovery proof.
Added the vendor to the local curated type hook. No retained tests or CI added.
Full Python lint, Pyrefly, the curated type hook, documentation verification and
`git diff --check` pass. Pyrefly retains two existing suppressions and two existing
redundant-cast warnings in `sor/runtime/agent_reads.py`; none were added here.

Remaining live QA: active curated Zendesk Basic-auth installation, published tool
binding, deployed changed code, widget invocation and console result inspection.
Existing SOR OAuth credentials do not prove that separate curated connection is
configured. No native writes were sent by these probes.

Existing semantic limitation: `emailed_customer` is derived from requested public
visibility, not notification delivery evidence. Retained for result-shape parity;
do not claim delivery correctness. Also retained: one-page search/user lookup and
first-page comments. Exhaustive pagination and explicit coverage are not silently
added by this typing slice.

### F3 progress: Intercom curated native contracts

All five curated tools now pass through vendor-owned Pydantic wire models and
explicit projections. This does not close the shared OAuth lifecycle, Intercom
SOR paths, or the remaining curated vendor inventory. The API remains pinned to
2.11; native authorities were checked against that version's official reference
and downloadable OpenAPI definition, not the site's current default version.

Flow: published tool/grant preparation → validated tool input → resolved
connection → origin-bound client → typed Intercom request → native response
validation → typed result → existing curated execution outcome. No platform/SOR
entity imports, DB calls, or independent mutation authority were added inside the
vendor implementation. Search POSTs remain reads; reply POSTs retain the existing
durable outbound-attempt owner and one mutation per invocation.

RCA reproduced: missing contact lists became not-found results; empty reply
responses became successful-looking results with the input conversation ID and
null state. Root cause was dict fallback rather than validation of the native
response. Both now return `vendor_response_invalid`. Detail/reply identity
mismatches, malformed nested authors/contacts/parts, invalid field types, and HTTP
or native error envelopes fail explicitly. Vendor diagnostics remain private.

Preserved contracts: exact-email lookup uses one result; conversation search uses
one page, up to 50 results; contact and state filters combine with AND. Retrieval
keeps the opening message and speech from the first 50 returned parts, clipping
bodies to 6,000 characters. The inaccurate whole-history description is removed:
Intercom itself returns at most 500 recent parts. Native dates, explicit nulls,
unknown response vocabulary, request field order and omission remain unchanged.
`visible_to_customer` remains a required strict JSON boolean; search limits reject
booleans. No new UI setting or public tool argument was introduced.

Verification: **116 function assertions**, including **13 before/after scenarios**
comparing serialized request bodies, request counts and result values. Error
cases cover missing/null/non-object lists and members, missing/mismatched IDs,
invalid predicates, invalid state input, unbounded search, and private vendor
diagnostics. The parity check caught a temporary serialization regression where
`exclude_none` removed nested explicit nulls; `exclude_unset` preserves them.
Guarded-client checks exercise real request construction, origin-bound OAuth
placement, JSON response parsing and mutation identity, with substituted native
transport and receipt persistence. A malformed successful mutation response is
recorded once, then refused; replay returns `vendor_outcome_unknown` without a
second send. Read authority refuses mutation. This is not a real DB crash or
native-vendor acceptance test.

Full Ruff and Pyrefly pass; two existing redundant-cast warnings and two existing
suppressed diagnostics remain outside this slice. The local curated type hook
now includes the whole Intercom directory. No retained probes, test suite, CI,
credentials, deployment, database changes or external mutations were added.

Browser check on 2026-09-10: **Eylo Development → Configured integrations**
loaded successfully and showed **No integrations configured yet**, with no search
or filters applied. There is no configured curated Intercom installation to use
for live acceptance in this org; separate SOR sources do not supply that binding.

Remaining acceptance: configure a curated Intercom installation and
published agent binding, deploy the changed code, run the configured widget agent,
then verify persisted calls/results in the console. General browser KB/memory QA
on the older image does not establish Intercom acceptance. Exhaustive history,
company pagination and explicit coverage metadata are not silently added here.

### F3 in progress: GitHub curated native contracts — 2026-09-10

**Implemented and locally verified; native acceptance pending.** All seven
curated GitHub tools now carry typed request/query, consumed native response and
agent result models. Vendor schemas stay in the curated vendor directory; no
SOR/platform entities, DB access or second mutation authority enter this layer.
Input → grant/resolver → pinned client → native parser → result → existing tool
outcome is the inspected flow. Read/detail calls keep their existing bounded
requests; mutations retain the same request ordering and omission/fingerprint.

Reproduced RCA: HTTP 201 with `{}` reported a created issue with null number and
link; search with `{}` reported no matches. Dict defaults bypassed meaningful
validation. Missing/malformed records, nested fields and identity mismatches now
return coded failures. HTTP/native error diagnostics are not echoed. String
labels allowed by GitHub's schema were previously discarded; their names are now
preserved. This is an explicit projection repair, not a parity claim for that bug.

Function evidence: **148 assertions, 16 before/after parity scenarios** covering
all seven tools, exact serialized requests/counts, omission versus empty pages,
explicit nulls, clipping, query normalization, native open vocabulary, nested
invalid payloads, strict IDs/limits/predicates, read-only mutation refusal and
single-write counts. Guarded-client probe uses real HTTP construction, pinned
OAuth placement and parsing, but substitutes native transport and receipt
persistence. A malformed accepted mutation is recorded once; replay returns
`vendor_outcome_unknown` without a second send. It is not a real DB crash test.

Source authority: GitHub's official `2022-11-28` OpenAPI and versioning guide.
The adapter remains unversioned, whose documented current default is that
version; no automatic upgrade/pin was introduced. Public examples are validation
fixtures, not successful configured-vendor calls. **11 public examples across
10 endpoint/method contracts pass**. One literal `items: ["..."]` documentation
placeholder is excluded; nested example references are resolved. No parser
relaxation was needed for those documentation representations.

Limits remain explicit: first 20 comments/reviews, 50 files, one search/list page.
`approved` still describes any approval in that review page, not current merge
eligibility. Tool descriptions now state that boundary. Full pagination,
`incomplete_results` projection, current-review reduction and replacement of the
legacy `main` target-branch default remain separate accepted-contract work.

The type hook includes the entire GitHub directory. No retained test suite, CI,
credentials, provider configuration, DB migration or deployment is added. The
earlier browser check found no curated installations in Eylo Development; SOR
sources do not supply them. Live GitHub tool acceptance remains pending a
configured installation and published binding on the changed runtime. The final
widget → agent → persisted console conversation gate remains required.

Browser recheck in this slice: both existing servers respond; the console session
is authenticated. Widget back-navigation shows 15 loaded conversations. Opening
the existing mixed-agent conversation in the console shows 43/43 persisted
messages, including completed `memory_recall` and `kb_query` calls/results and
the cited final reply from the earlier 15:46–15:47 run. This is fresh navigation
over earlier data on the old runtime, not a new agent run or GitHub acceptance.
Full Ruff, full Pyrefly, scoped curated type hook, docs verification and diff
whitespace checks pass; pre-existing type warnings/suppressions remain.

### F3 in progress: GitLab curated native contracts — 2026-09-10

**Six tools typed; local evidence only, named-project transport still open.**
The flow now carries explicit input/query/request → native response → result
models through issue search/detail/create, comments and MR list/detail. Vendor
models stay inside the curated GitLab package. Existing origin-bound PAT
placement, grant resolution and durable write authority are unchanged.

Reproduced RCA: create sent `assignee_usernames`, which is not a supported v4
create field, and accepted `{}` as an issue with null IID/link. New lookup models
resolve exact usernames before the single mutation. Missing/ambiguous/invalid
users refuse the operation before any write. Case-insensitive repeated names
resolve once. Input is bounded at 20 supplied usernames to bound lookup I/O;
there is no truncation. One resolved user sends `assignee_id`; multiple send
`assignee_ids`, subject to GitLab tier support. Query `assignee_username` is now
encoded as the documented array parameter. These are deliberate wire repairs,
not before/after parity claims for the old bugs.

Native success validation rejects malformed nested authors, IDs, note system
flags, lists and changes. Detail IID and numeric-project identity mismatches are
refused. Created notes validate returned issue identity before reporting it.
HTTP and native error envelopes use stable codes and private diagnostics.

Evidence: **185 function assertions, 15 before/after parity scenarios** cover
every tool, exact request order/JSON and result values where preserved, explicit
nulls, omitted versus empty sections, clipping, query normalization and native
open vocabulary. Additional assertions prove the repaired assignment/search
wire, bounded and duplicate lookup behavior, no writes after failed resolution,
malformed payload refusal and strict IDs/predicates. Guarded-client checks use
real request building, PAT origin binding and response parsing with substituted
transport/receipt persistence: numeric-ID read succeeds, array query survives
serialization, malformed accepted mutation is recorded once, replay does not
send, and read authority refuses mutation. Named project input still reproduces
`vendor_request_invalid` before network I/O. This is not a real DB crash test.

Source authority is the current official GitLab REST v4 issue/user/note/MR and
deprecation documentation. Three directly parseable public examples (issue
creation, note list, user list) validate. MR documentation blocks are not valid
JSON as published; they were inspected but not counted as executable fixtures.
No native GitLab installation was configured or called. Self-managed version
compatibility and tier-specific assignment acceptance remain unverified.

Preserved/deferred: lists read one page up to 100; notes scan the first 20 and
exclude system entries; body clipping remains 6,000 characters. `/changes` is
retained for existing v4 behavior, not silently upgraded to `/diffs`. Pagination,
native overflow projection and merge-eligibility/approval evaluation remain
explicit limitations. The shared encoded-separator control is not weakened;
the separate transport repair and adversarial path checks remain required before
named-project GitLab acceptance can close. The final widget → agent → persisted
console QA gate remains required on a deployed changed runtime.

The local type hook now covers the full GitLab directory. No retained probes,
test suite, CI, credentials, provider changes, DB migration or deployment added.

### F3 progress: Jira curated native contracts — 2026-09-10

Four tools now use Jira-owned Cloud v3 request, nested response/ADF, error and
result models. Scope is curated Jira, not SOR. Reproduced HTTP-404 empty-search
success, empty comment acknowledgement success and first-user misassignment;
fixed by status/shape validation and one exact visible-email match before write.
Unknown/missing private email refuses assignment. The create scope list now
includes the existing classic `read:jira-user` requirement. Simple JQL filters
escape quotes/backslashes; path values are encoded. One-page limits and single
mutation authority remain unchanged. No API/SDK upgrade or configuration edits.

Evidence: 165 assertions across 12 valid before/after cases; malformed/error,
privacy, ambiguous identity and no-write cases; six official OpenAPI response
examples across search/detail/create/comment/project/user operations. The
published numeric `updated: 1` example is explicitly preserved, not converted
to a guessed date. Full source authority and operation limits are in
[integration reference](../reference/integrations.md#jira-request-and-response-contracts).

The actual guarded client verifies POST-as-read, ADF serialization and origin
pinning; a malformed accepted comment produces one receipt and replay does not
send again. Transport and receipt persistence are substituted, so this is not
native acceptance, durable DB recovery or widget QA. Jira native installation
QA and the final changed-build browser matrix remain open. No retained probes,
operator DB changes or deployment were introduced.

### F3 progress: Asana curated native contracts — 2026-09-10

Six tools now retain Asana API 1.0 request/envelope/nested result contracts.
Reproduced failed search becoming empty success and malformed task completion
returning unknown state. HTTP/error envelopes, required data/identity and consumed
fields now validate; completion requires the same task and `completed: true`.
Malformed accepted writes never authorize a second send.

The old project-plus-assignee query discarded the assignee. Asana requires the
workspace with an assignee filter: that combination now adds exactly one project
workspace read, checks project identity and sends both filters. Other valid
paths preserve request counts, byte ordering and projections. First-workspace
selection, first-page limits and 6,000-character clipping remain explicit
compatibility behavior; no implicit OAuth support was introduced.

Evidence: 136 assertions, 13 before/after valid cases; mixed-filter regression,
strict predicates/limits, malformed/error envelopes, ambiguous project lookup,
identity/completion failures and read-only refusal. Actual guarded-client task
reads and story writes verify serialization, one accepted receipt and no replay
resend; final transport and persistence are substituted. Native selected fields
are grounded in the official current API/OpenAPI, not live vendor execution.
See [integration reference](../reference/integrations.md#asana-request-and-response-contracts).
No retained probes, operator data changes or deployment. Native Asana and final
changed-build widget/console acceptance remain pending.

### F2 in progress: typed inference config and OpenAI request boundary

**Connected changes; not completion of F2**

- Resolver output was already immutable and typed, but all four callers converted
  `generation` to a storage dictionary before inference. `LLMGenerationConfig`
  now describes the read-only domain value; `LLMInferenceConfig` carries that
  exact value and an enum cache policy. The domain still owns validation; common
  contracts and sockets do not import module or framework types.
- Conversation generation (including streaming/fallback), background prompt
  helpers, swarm workers, and memory extraction pass the typed value. Every one
  of the eight factory branches accepts it. Persistence/API schemas, provider
  revision checks, model choices, configured defaults, and metering are unchanged.
- Base inference is an awaited `LLMResponse`; streaming returns an async generator
  whose owner must close it.
  SDK-client/transform methods no longer impose `Any`/dictionary contracts on all
  vendors. Read-only tool collections use `Sequence[ToolRecord]`, avoiding list
  invariance at the swarm boundary. The optional streaming fallback handles an
  unsupported call at iterator creation as well as first iteration.
- OpenAI Chat Completions builds native message/content/function-call/tool and
  streaming/non-streaming request parameter types. Platform image MIME metadata
  is no longer forwarded as an undocumented field inside `image_url`. The
  shared OpenAI-family declaration projection returns SDK `FunctionDefinition`;
  Responses and realtime retain their existing API-specific envelope.
- Gemini constructs `GenerateContentConfig` from named attributes instead of
  untyped keyword expansion. Groq/Cerebras retain their existing model-specific
  behavior. Dead dictionary overrides for reasoning flags and Gemini safety
  were not publicly configurable: the domain's allowed field set never admitted
  them. No new native setting, model default, safety policy, or provider fallback
  was introduced. A later native-options feature needs an explicit domain/UI
  contract, not hidden dictionary keys.

**Evidence**

- Installed dependencies inspected: OpenAI 2.14.0, Anthropic 0.75.0,
  google-genai 1.56.0, Groq 1.1.1, Cerebras SDK 1.67.0, Sarvam 0.1.28.
  [Official OpenAI function-calling documentation](https://developers.openai.com/api/docs/guides/function-calling)
  and installed generated SDK definitions ground the request types. No dependency
  upgrade or model migration was performed.
- 94 config/wire checks passed across all eight factories. Seven used real SDK
  clients and HTTP transports with substituted responses, including Bedrock's
  signed request path; Gemini checked native config construction. Explicit limits,
  omitted values, zero temperature, readonly settings, tool request construction,
  and text/usage normalization were exercised. Missing mandatory max tokens fail.
- 17 additional checks passed through six real OpenAI SDK HTTP operations:
  streaming text plus fragmented tool arguments, call identity, usage-only tail,
  cache/reasoning counters, and complete/delta projections; background prompt,
  memory completion, swarm worker, conversation generator, and non-streaming
  fallback callers. Image request shape excludes platform-only MIME metadata.
- Caller QA substituted resolution/context/agent loading where DB state would be
  needed. This is function/adapter data-flow evidence, not widget, live-provider,
  full durable-run, or persistence proof. Test-owned HTTP clients were closed;
  that does not prove production adapter cleanup, which remains pending below.
- Scoped Pyrefly passes for runtime contracts/config, OpenAI request/utility,
  pipeline adapter construction, and background prompt caller. A local pre-commit
  gate covers that proven scope, not all of F2. Full server/CLI Ruff passes.

**Native Groq slice: implementation and local verification**

- RCA reproduced with the installed SDK: streamed tool arguments containing only
  `{` became an executable tool call with `{}` input; the HTTP client remained
  open. JSON fallback and dictionary-based accumulation had erased the distinction
  between incomplete output and a valid no-argument call. Inheriting OpenAI's
  client/response contract also hid a different vendor SDK behind incompatible
  override annotations.
- Groq now inherits only the neutral adapter. Requests, message parts, tools,
  completions, usage, and chunks use Groq 1.1.1's native SDK contracts. Named
  generation fields and existing GPT-OSS/Qwen behavior remain unchanged. Optional
  tool arguments are not rewritten to OpenAI strict-mode requirements.
- `groq_responses.py` owns typed failure/finish enums and stream/tool accumulators.
  SDK-parsed values are validated before normalization; SDK-supported coercion
  occurs before that check. Function input must be a finite JSON object, with
  stable/nonempty identity and a matching terminal reason. EOF, malformed input,
  duplicate IDs, conflicting deltas, and `x_groq.error` cannot authorize a tool
  call. The entire batch is validated before exposure. Diagnostics omit payloads.
- The invocation owns the SDK client and stream with async context managers.
  The conversation runner closes its async generator in `finally`, including
  failures/cancellation between yielded chunks. The shared base and concrete
  streaming annotations now express that closeable contract. Final Groq output
  is yielded only after resources close. The neutral history validator's existing
  duplicate-call guard applies; its consecutive-user merge uses the message's
  null-safe text accessor. No OpenAI-specific history override is copied.
- String tool output moved into neutral `sockets/llm/tool_content.py`; OpenAI,
  Responses, and Groq reuse its unchanged text/TOON behavior without importing
  another vendor's SDK.
- Evidence: **301 local assertions** pass with real Groq SDK clients and
  substituted HTTP transports. These cover text and tool responses, interleaved
  argument fragments, usage-only tails, canonical image/tool-result history,
  optional schema fields, malformed/native error variants, finite numbers,
  cancellation before/after the first response, timeout, early generator close,
  and listener failure/cancellation. All four actual caller functions were
  exercised with resolution/context/DB loading substituted; each client's close
  was observed. A malformed streamed call does not trigger a second non-stream
  request. Existing 94 configuration and 17 OpenAI/caller checks also pass.
- Source: [Groq local tool calling](https://console.groq.com/docs/tool-use/local-tool-calling),
  [Groq API reference](https://console.groq.com/docs/api-reference), and the installed
  SDK's generated request/response models, client overloads, and async stream
  context manager. No SDK upgrade was needed. Its request `TypedDict` permits an
  optional stream flag whereas the union overload requires a boolean; the adapter
  passes named typed fields and an explicit operation flag without a cast.
- The local type hook now includes the native Groq files and neutral serializer.
  Scoped Pyrefly and full server/CLI Ruff pass. The broader LLM/caller check still
  reports **84 diagnostics, one suppression**; this is not whole-F2 completion.
  No live vendor, widget, operator DB, durable sink, or worker QA is claimed.

**Native Cerebras and Sarvam slices: implementation and local verification**

- Cerebras RCA reproduced before the fix: a property named `minItems` disappeared
  during schema cleanup, incomplete arguments became `{}`, and the native HTTP
  client remained open. OpenAI inheritance plus dictionary traversal hid both
  vendor response differences and schema-node boundaries.
- Cerebras now uses SDK 1.67.0 request types and native completion/chunk/error
  unions. Adapter-owned enums and validation handle terminal reasons, optional
  chunk deltas, tool indexes, usage, and error variants. Its documented reasoning
  token extension is narrowly modeled because the pinned SDK's usage-details
  declaration omits that field. Schema cleanup preserves property/definition
  names, annotation values, and the original required/optional distinction.
  Existing GLM settings and the outer 429 retry policy remain; Retry-After accepts
  bounded seconds or HTTP dates. SDK retries remain a separate existing layer.
- A real SDK probe revealed another issue: `AsyncCerebras.__init__` creates a
  synchronous client for TCP warming by default. Profiling traced the blocked
  time to that client's HTTP retries, not the apparent async header lookup.
  The adapter sets the public `warm_tcp_connection=False` option. A guard probe
  proves the synchronous constructor is not called. No SDK upgrade was needed.
- Verification correction: earlier Cerebras HTTP substitutes did not intercept
  that hidden warmup. They used dummy keys, not operator credentials. All
  Cerebras probes were rerun with warmup disabled; native response fixtures now
  include the SDK-required fingerprint and timing fields. The all-eight-provider
  request probe also passed again. Those results, not the earlier apparently
  isolated run, are the current evidence.
- Sarvam RCA: its SDK's user message is text, but the OpenAI proxy passed a
  content-block array. Its native async iterator and client ownership were also
  hidden behind `Any`. The adapter now builds native request TypedDicts, projects
  text/tool-result history, and explicitly rejects image content before opening
  a client. Native completion/chunk models are validated; SDK aliases admitting
  `Any` for finish reasons are narrowed to a vendor enum. SDK validation failures
  are translated without including raw payloads in diagnostics.
- Sarvam 0.1.28 has no public client close method. The adapter owns the supplied
  HTTP client and closes the SDK's async generator before that client. Groq and
  Cerebras use native async context managers. All three emit final results only
  after cleanup. Their shared neutral `ToolCallBuffer` validates stable/nonempty
  IDs/names, finite object arguments, and the whole batch; vendor terminal-state
  checks remain local. No vendor enum or SDK type moved into domains/framework.
- Evidence: **291 Cerebras native-path checks**, **55 Cerebras schema/retry
  checks**, and **353 Sarvam native-path checks** passed. Native probes exercised
  actual SDK serialization/parsing, canonical history, stream fragments, usage,
  invalid/unknown states, malformed tools, all four caller functions, cancellation
  before/after the first chunk, timeout, early close, and caller/listener failure.
  HTTP/provider responses and DB-dependent caller loading were substituted.
  Groq's **301**, configuration's **94**, and OpenAI/caller's **17** checks passed
  again after the shared-buffer extraction. No temporary probe files are shipped.
- Sources: [Cerebras tool use](https://inference-docs.cerebras.ai/capabilities/tool-use),
  [structured outputs](https://inference-docs.cerebras.ai/capabilities/structured-outputs),
  [chat API](https://inference-docs.cerebras.ai/api-reference/chat-completions),
  [Sarvam chat API](https://docs.sarvam.ai/api-reference/chat/chat-completions),
  and the pinned SDK request, response, client-construction, and streaming source.
  Current Sarvam documentation differs from the pinned SDK/catalog's model set;
  model availability needs the planned catalog/live-verification pass. This
  typing slice does not silently migrate models or claim current live coverage.
- The local type gate now includes both native adapters/response modules. The
  expanded scoped check passes; the broader LLM/caller check still reports
  **82 diagnostics**, down from 84. Remaining files are not considered typed
  merely because a narrow gate passes. This is not F2 or platform completion.
  The exact configured hook command, full server/CLI Ruff, documentation/link/
  diagram verification, and whitespace checks also pass.
- No live vendor, widget, durable sink, worker, or operator DB QA is claimed.
  No deployed service, provider config, dependency version, migration, Git
  history, or configured vendor state was changed.

**Native OpenAI Chat slice: implementation and local verification**

- RCA reproduced through SDK 2.14.0: missing arguments and missing terminal
  events exposed executable `{}` calls; a malformed sibling was skipped after
  a valid call had already been exposed. Clients remained open. The shared strict
  schema converter also mutated nested input properties and missed definitions
  and union branches. Dictionary accumulation and shallow copying hid these
  contract violations.
- Chat Completions now uses native completion/chunk/usage types, an adapter-owned
  finish/error enum, and a typed stream accumulator. Native function/custom-tool
  variants, deprecated function calls, refusal output, stable identities, terminal
  reasons, and usage-only tails are handled explicitly. The neutral tool buffer
  validates the entire batch before any tool is exposed. Refusals use the existing
  Responses adapter's `[Refusal]` text representation and cannot authorize tools.
- Invocation-scoped async context managers close the SDK client and stream on
  success, failure, timeout, cancellation, and early generator close. Existing
  tool-progress envelopes are retained after terminal batch validation and resource
  cleanup; their content lists do not alias later progress. The final response's
  `streaming: false` shape remains unchanged. All four real caller functions were
  exercised with DB/context resolution substituted.
- The shared OpenAI function-schema converter accepts typed JSON, descends only
  schema nodes, and covers definitions, unions, nullable objects, and nested
  arrays. It does not mutate canonical input schemas, annotation data, or property
  names. Existing all-properties-required strict behavior remains; it preserves
  declared nullability rather than inventing nullable platform fields. Native SDK
  request types own the final `parameters` projection. No SDK/model upgrade or
  API/storage contract change was made.
- Evidence: **353 native Chat checks** passed across 65 SDK HTTP operations,
  seven cleanup paths, and four actual callers. **37 shared-schema checks** passed
  through actual Chat/Responses SDK requests and realtime session-update sending.
  The **94 all-provider config checks** and **18 OpenAI/caller checks** also passed.
  Caller fixtures now allocate one HTTP client per invocation, matching production
  ownership. HTTP responses, WebSocket sending, and DB-dependent loading were
  substituted; this is not live-provider, widget, voice, durable-sink, or DB QA.
- Sources: pinned SDK 2.14.0 generated request/response/stream classes,
  [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling),
  and [Chat Completions reference](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create).
  These checks verify schema projection, not universal support for every JSON
  Schema keyword or current live model availability.
- The local type gate includes `openai_chat_responses.py`. This is a scoped slice,
  not completion of F2 or platform-wide typing. Remaining response and caller
  contracts still need the ordered work below.

**Native OpenAI Responses slice: implementation and local verification**

- Baseline SDK reproduction confirmed that malformed function JSON became `{}`,
  a failed response could expose tools, and streams without a terminal response
  still exposed calls. An ordinary streamed function call was duplicated under
  its separate output-item and call IDs. Clients remained open. Reflection and
  fallback dictionaries concealed the API's native event and identity contracts.
- Native request TypedDicts now cover instructions, user/image input, prior
  assistant text, function calls/results, function declarations, generation
  settings, and streaming. Prior assistant text uses `EasyInputMessage` rather
  than a partial output message missing its required vendor ID/status. Image
  detail explicitly uses the SDK/API's existing `auto` behavior; platform MIME
  metadata is not sent. No configured model or generation value is invented.
- `openai_response_events.py` owns typed native event validation, lifecycle/error
  enums, item identity, terminal output normalization, and progress projection.
  A discriminated native SDK event union validates the boundary; no `Any`,
  reflection, unchecked cast, or diagnostic suppression is needed in these files.
  SDK parsing can coerce values before this validation, as with the other adapters.
- The complete terminal response is the sole tool-output authority. Function
  argument deltas are advisory progress, not another executable accumulator.
  Output indexes/item IDs and function call IDs stay distinct and stable. The
  entire final batch is validated before exposure. A failed, incomplete, refused,
  malformed, or unsupported tool result cannot execute. Text-only incomplete
  responses retain the native max-token/content-filter distinction; native
  reasoning output stays hidden while its token usage is accounted.
- Async ownership covers the SDK client and stream, including cancellation during
  request creation and between caller yields. Existing tool-progress envelopes
  and final metadata remain, emitted after full validation and cleanup. The
  duplicated history override was removed in favor of the shared validator and
  its existing duplicate-call guard. Config, provider resolution, grants, and
  framework tool-execution policy retain their original owners.
- Evidence: **452 native SDK assertions**, 85 SDK HTTP operations, seven cleanup
  paths, and all four caller functions passed. Coverage includes interleaved
  item/call IDs, terminal-only tool authority, malformed/unknown output, refusals,
  usage, incomplete reasons, history serialization, resource closure, and no
  non-stream fallback on invalid output. Chat's **353**, shared-schema's **37**,
  all-provider config's **94**, and OpenAI/caller's **18** checks passed again.
  Provider responses and DB-dependent resolution/loading were substituted.
- Sources: pinned OpenAI SDK 2.14.0 request/event/response models,
  [Responses API reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create),
  and [streaming Responses](https://developers.openai.com/api/docs/guides/streaming-responses).
  Current documentation includes newer models/features than the pinned SDK;
  this slice does not upgrade either the dependency or model catalog.
- Focused milestone review followed DDD boundaries, architectural fit, data flow,
  plan adherence, then readability/security/performance. SDK types remain in
  adapters; there are no new DB/network paths or authorization shortcuts. Existing
  framework/canonical-response typing gaps are not hidden by this scoped gate.
  The broader LLM/caller baseline is **77 diagnostics**, down from 82; F2 remains
  in progress. Native enum/SDK support is not a claim of live-provider support.
- The expanded local type hook passes with **zero errors**. Full server/CLI Ruff,
  documentation/link/diagram verification, and whitespace checks pass. Performance
  review was source inspection, not a load benchmark. No temporary probes are
  included in the repository.
- No live vendor, widget, voice, durable sink, operator DB, or deployed-service
  QA was run. Human product review and live agent QA remain milestone gates;
  the ephemeral checks above establish function/adapter contracts only.

**Native Anthropic/Bedrock slice: implementation and local verification**

- Reproduced through pinned Anthropic SDK **0.75.0**, including Bedrock's real
  SigV4 signing and binary event decoder: missing/truncated tool arguments and
  missing terminal events exposed executable calls, clients remained open, and
  prompt caching mutated nested caller input. The old enriched-stream accumulator
  treated a stopped block as a completed executable call, before validating the
  message or other calls.
- Native request contracts now cover messages, tools, images, and generation
  settings. Required config is checked before opening a client. Bedrock retains
  its native transport and credentials while sharing the actual Claude Messages
  protocol. There are no cross-vendor OpenAI types, unchecked casts, suppression
  directives, or first-party `Any` annotations in the three changed adapter files.
- A discriminated native event union and vendor-owned stream/stop/error enums
  replace open accumulator dictionaries. Raw input fragments remain distinct from
  the initial empty tool placeholder. Every block must close and the message must
  reach `message_stop` with a compatible reason before any tool is exposed.
  Finite JSON and duplicate-ID validation cover the whole batch. Incomplete,
  refused, malformed, or unsupported tool batches cannot execute.
- Text/thinking progress snapshots exclude tools. Existing tool-completion
  envelopes use independent prefix lists after full validation and resource
  cleanup. Text-only refusal/token-limit/stop-sequence outcomes remain visible.
  Redacted thinking is opaque and omitted from text; signatures are not rendered.
  Hosted tools and `pause_turn` are not supported. Signed extended-thinking
  persistence/replay is not implemented or claimed by this slice.
- Async client/stream ownership covers success, vendor errors, timeout, cancellation
  before response creation, cancellation during reads/caller handling, and early
  close. Cumulative usage updates all available input/output/cache counts without
  mutating prior progress. Prompt caching preserves its existing four-breakpoint
  policy and no longer mutates inputs or marks empty text.
- Native image inputs distinguish HTTP(S) URLs and base64 data URLs. Direct Claude
  supports both; Bedrock rejects remote URLs before client allocation. Inline data
  is translated to the native MIME/base64 source shape. This adds no URL fetch,
  filesystem read, MIME sniffing, image-content validation, or resizing behavior.
- Evidence: **1,392 assertions**, **189 SDK HTTP operations**, seven cleanup paths
  per vendor, and eight additional operations through the four real caller
  functions (conversation, background prompt, memory completer, swarm worker).
  All **94 provider-config checks** also passed. Responses/streams and DB-dependent
  context/loading were substituted; native SDK clients and binary decoding were
  exercised. SDK parsing may coerce input before strict revalidation; static types
  and these probes do not establish raw-wire strictness or live-provider support.
- Sources: installed SDK request models, response/event classes, stream accumulator
  and Bedrock decoder; [Claude streaming](https://platform.claude.com/docs/en/build-with-claude/streaming),
  [tool-input accumulation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming),
  [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
  [Claude images](https://platform.claude.com/docs/en/build-with-claude/vision), and
  [Bedrock request/response](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages-request-response.html).
  Current vendor docs contain newer features than SDK 0.75.0; no dependency/model
  catalog upgrade or new optional feature was inferred from them.
- Milestone review ran sequentially: DDD ownership, architectural fit, source-to-sink
  data flow, plan adherence, then readability/security/performance. No module,
  framework, authorization, retry-policy, DB, or deployment ownership moved.
  Review removed full-batch aliasing from progress lists. Performance inspection
  confirmed bounded index handling rather than scanning up to an external index;
  no load benchmark was run.
- The broader LLM/caller type baseline is **63 diagnostics**, down from 77.
  The expanded scoped hook checks Anthropic, Bedrock, and their response helper;
  it is not a platform-wide passing gate. The hook passed with zero errors;
  full server/CLI Ruff, documentation validation (46 pages, 275 local links,
  47 diagrams), and whitespace checks passed. No probes are added to the repository.

**Shared batched tool-result history: implemented and locally verified**

- The old validator tracked one identity per row; Anthropic/Bedrock and Gemini
  serialized only the first result. Conversation-to-framework conversion also
  selected `parsed.content[0]`. Reproduced independently at both boundaries:
  two vendor call IDs yielded one result; three persisted results yielded one
  framework result. The earlier one-result-per-row assumption was narrower than
  the canonical `ToolResultMessageContent` contract.
- Shared identity access uses canonical message accessors, not `hasattr` or dict
  key guessing. A batch is accepted atomically only when every nonblank, unique
  ID matches a pending call. A bad sibling consumes none of the pending set.
  Cleanup retains completed pairs and removes unresolved calls in a linear pass.
  The newest pending group no longer bypasses validation, and normalization
  copies caller-owned messages before text merging. Completeness reports are
  immutable typed objects and count identities, not rows.
- The conversation bridge preserves batched results in typed pipeline-owned
  metadata and reconstructs the original result row. Existing singular metadata
  remains supported for framework-generated/live results. The context-refresh
  check examines every result ID before deciding whether transient replay is
  needed. No SDK type moved into framework/domain contracts, and no DB schema
  changed. Common message grouping now imports the common canonical schema
  directly instead of passing through the conversation-module re-export.
- Anthropic/Bedrock emit all result blocks. Gemini emits native function call/
  response parts with separate IDs/names, using the matching call as the name
  authority. JSON-encoded arrays/scalars are wrapped in an object; they no longer
  drop the whole result batch. Native serialization failures abort preparation
  rather than silently removing half a pair. Target: pinned/installed
  `google-genai==1.56.0`; fields verified in its native `FunctionCall` and
  `FunctionResponse` models and the
  [Gemini API schema](https://ai.google.dev/api/caching#FunctionResponse).
- Function evidence: **2,563 history assertions across eight adapters**,
  **88 conversation-bridge assertions**, and **64 SDK/caller assertions**
  (eight direct SDK operations and six operations through the conversation
  caller and two-iteration swarm worker). Coverage includes result permutations
  and partitions, completed/failed/pending states, atomic rejection, late results,
  request exclusion, input ownership, compaction, explicit metadata decoding,
  duplicate-replay prevention, prompt caching, and streaming/nonstreaming input.
  SDK HTTP/Bedrock binary transports, DB context, and tool execution were
  substituted. These are not live-provider or persisted-product QA claims.
- The seven completed native-adapter regression suites pass **3,142 assertions**:
  OpenAI Chat 353, Responses 452, Groq 301, Cerebras 291, Sarvam 353, and
  Anthropic/Bedrock 1,392. These include all four actual caller functions with
  substituted transport/context. Provider-config wire checks pass **94**.
  Shared base, grouping, and bridge files join the scoped pre-commit type gate.
  That expanded check passes with zero errors. The broader LLM/caller probe
  remains non-passing at **57 diagnostics**, down from 63; it is not a
  platform-wide passing type gate.
- Full server/CLI Ruff, documentation validation (46 pages, 275 local links,
  47 diagrams), and whitespace checks pass. No frontend API or UI contract changed.
- Milestone review ran in order: DDD boundaries, architectural fit, data flow,
  plan adherence, readability/security/performance. It caught the upstream
  conversation truncation and Gemini scalar-response loss; both are corrected.
  Local function probes are temporary, with no committed test suite.

**Framework metadata serialization follow-up: reproduced, not fixed here**

- `RunMessage.metadata` is annotated as `FrameworkMetadata`. Default Pydantic
  `RunMessage.model_dump_json()` drops fields declared by a metadata subclass.
  A round-trip probe lost both tool-call and result metadata. In-memory bridging
  and explicit decoding of the owning metadata schema pass; those are distinct
  claims. No actual persisted `RunInput` consumer was established in this slice.
- Trace all framework metadata producers, serialization/checkpoint consumers,
  subtype preservation, and intentional secret exclusions before changing the
  shared serialization contract. This remains assigned to the F2 framework/
  caller-contract work; do not paper over it with unchecked casts or broadly
  enabling arbitrary serialization without checking the data boundary.
- Live vendor, widget, voice, durable-sink, and operator-DB QA remain unrun.
  No configured accounts, DB data, migrations, dependency pins, Git history, or
  deployed services changed. F2 and the platform-wide goal remain active.

**Next ordered F2 slices**

1. Gemini native response/stream assembly and per-part replay are now implemented
   and locally verified in the milestone below. Together with OpenAI
   Chat/Responses, Anthropic/Bedrock, Groq, Cerebras, and Sarvam, this covers the
   eight factory branches. Keep SDK-specific variants out of shared contracts;
   configured-account QA remains separate from these native transport proofs.
2. Preserve native SDK response/stream variants and typed accumulators throughout
   each adapter. Remove remaining `Any`, reflection-based field access, and
   suppressions on these known shapes; validate malformed/incomplete tool inputs
   and stream terminal/refusal/error outcomes without authorizing a tool call.
3. Retain invocation ownership proven for Chat/Responses/Anthropic/Bedrock/Groq/Cerebras/Sarvam
   and Gemini while replacing the remaining response handling;
   close each client/stream on success,
   failure, timeout, early iterator close, and cancellation. Retain existing
   retry/usage authority; test slow or abrupt disconnects with SDK transports.
4. Type canonical `LLMResponse` content and metadata with their producers and
   framework/tool/usage consumers, preserving vendor-owned SDK contracts. Broad
   LLM/caller type checks
   still have unresolved errors; the scoped gate is not global completion.
5. Run the milestone review and configured-org live agent/widget QA after the
   connected native paths are implemented. Continue other independent work when
   a vendor account is unavailable; don't invent live coverage.

The platform-wide typing goal remains active. No operator data, credentials,
migrations, Git history, running services, or external vendor state changed.

**Gemini request/lifecycle slice: implemented and locally verified**

- Target remains declared, locked, and installed `google-genai==1.56.0`.
  Native request types replace dictionary-built content, roles, parts, tool
  declarations, and generation config. Tool schemas use the SDK's JSON Schema
  field without stripping constraints or silently skipping conversion failures.
  No SDK type crosses into framework/module policy.
- The async entrypoint previously invoked the synchronous SDK; a native HTTP
  probe confirmed a sync request and no explicit client close. Both inference
  paths now prepare/validate first and scope the SDK's two transports and stream
  generators. Nonstreaming normalization runs after resource cleanup. The
  hardcoded `ThinkingLevel.MINIMAL` request was removed; no replacement default
  or model-specific policy was invented. Automatic tool execution stays disabled.
- Sources: installed `google.genai.client`, `models`, `_api_client`, and `types`;
  [native SDK lifecycle and tool declarations](https://googleapis.github.io/python-genai/)
  and [ProtoJSON field-name rules](https://protobuf.dev/programming-guides/json/#field-names-as-json-keys).
  SDK 1.56.0 emits `parameters_json_schema` in Developer API declarations; the
  probe validates the actual native wire shape, not a guessed camel-case field.
  Current Gemini thinking docs chiefly describe Interactions, a different API;
  this slice does not migrate APIs or upgrade packages.
- Evidence: **93 request/lifecycle assertions**, **36 caller assertions** across
  background prompt, memory completer, swarm, and conversation (both inference
  modes); **16 assertions over six real loopback TCP connections**. HTTPX and
  aiohttp both close sockets on early iterator close, cancellation while reading,
  and cancellation before the response. Vendor HTTP errors, malformed JSON,
  timeout, failed normalization, and caller/listener failure also release owned
  transports. SDK-managed transports were exercised; externally injected clients
  intentionally remain the injector's responsibility in the SDK.
- **2,563 shared history assertions** and **94 provider-config wire checks** pass
  again. Caller context, token delivery, and vendor responses were substituted;
  loopback is a protocol fixture, not a live Google service. No operator DB,
  published-agent, widget, voice, durable-sink, or external tool-effect QA is claimed.
- Scope split followed the data-flow trace: thought signatures also cross the
  platform/framework message envelope. Do not declare Gemini complete based on
  request typing or resource cleanup. A native chunk probe still reproduces
  two tool chunks replacing each other at part index zero, premature executable
  progress, and a content-less terminal chunk losing both finish state and usage.
  Nonstreaming native IDs and per-part signature retention also remain to fix.
  Next slice must update producers, replay consumers, and all affected callers
  together, without replaying filtered-out calls from saved metadata.
- The existing scoped LLM hook remains the gate for completed native adapters;
  Gemini is not added yet. The current broader LLM/caller probe reports
  **55 diagnostics**, including one in Gemini's old response metadata path.
  Zero scoped diagnostics is not a platform-wide passing type check.
- The scoped hook, full server/CLI Ruff, documentation validation (46 pages,
  276 local links, 47 diagrams), and whitespace checks pass. This is an
  independently verified slice, not the full Gemini milestone review. No
  committed probes, dependencies, migrations, deployed services, or operator
  data were changed.

**Gemini response/replay milestone: implemented and locally verified**

Confirmed causes and connected fixes:

- Chunk-local part indexes restarted at zero. Two function-call chunks replaced
  each other; executable progress could precede complete argument validation.
  The new native `GeminiStream` accumulates parts in arrival order and validates
  the entire tool batch after terminal completion and transport cleanup. Missing
  termination, duplicate IDs, malformed/non-finite input, truncated calls, and
  unsupported native content do not expose a valid prefix for execution.
- Content-less terminal/usage chunks were skipped. Native response ID, model
  version, terminal state, safety ratings, cache/reasoning counts, and final usage
  now survive normalization. Progress snapshots do not mutate prior usage.
- A global signature was attached to regenerated parts; nonstreaming responses
  and transient swarm rows lost signatures. `GeminiReplay` retains original native
  parts with opaque signature bytes, serialized by pinned SDK 1.56.0. Canonical
  call IDs are stable; generated internal IDs are not injected into original
  native calls that did not have an ID.
- A response can contain parallel calls separated by text, while framework rows
  interleave calls/results. Every produced text/tool row now carries its original
  response-block index. Gemini groups retained calls before their results within
  that response, keeps text/thinking parts separate, and checks replay against
  the actual canonical row. Repeated equal text does not select the wrong signed
  part. The shared validator's incomplete-pair cleanup is retained; Gemini's
  overrides allow text between pending calls only for the same saved response.
- `response_messages` now accepts the complete `LLMResponse`; its actual swarm
  caller passes it through. Conversation persistence and framework continuation
  both preserve block indexes. Final message metadata retains the last model
  response only when a successful, tool-free response exactly matches final text.
  Error, transformed, and tool-generated outcomes cannot borrow unrelated replay.

Authoritative scope:

- Installed native SDK models and serialization were checked alongside the
  [GenerateContent API](https://ai.google.dev/api/generate-content),
  [GenerateContent function calling](https://ai.google.dev/gemini-api/docs/generate-content/function-calling),
  [GenerateContent thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking),
  and [thought-signature ordering](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thought-signatures).
  Vertex-only partial argument fields are explicitly refused by this Developer
  API adapter; no SDK/API/model/credential change was bundled into the repair.
- No fake signature or bypass marker is generated. Historical rows that never
  stored original signed parts cannot be repaired by guessing. Live Gemini
  acceptance of retained/reduced histories still needs configured-account QA.

Executed evidence:

1. **175 native response/replay assertions**: nonstreaming/streaming SDK HTTP
   fixtures, parallel batches, JSON byte round trips, exact request-body parts,
   persisted framework metadata, filtered calls, repeated text, text between calls,
   changed/tampered replay, refusals, negative usage, and malformed streams.
   Non-finite arguments were also tested directly on native SDK objects, because
   Pydantic's JSON serializer turns those synthetic values into null before HTTP.
2. **42 two-turn caller assertions / six SDK calls**: the actual swarm loop and
   both conversation inference modes retain signatures, execute the expected
   substituted tools, send both calls together, and produce final text/usage.
3. Previous request/lifecycle **93**, caller lifecycle **36**, shared history
   **2,563** across eight adapters, framework bridge **88**, native SDK/caller
   history **64**, and provider-config wire **94** checks pass again.
4. Real local TCP cleanup: **16 assertions / six connections**, native HTTPX and
   aiohttp, covering early exit, cancellation during reads, and cancellation
   before a response. Every fixture observed the socket close.

Milestone review, in required order:

1. DDD boundaries: native Parts and replay schema stay in the Gemini adapter;
   framework metadata carries only neutral response/block identity. No forbidden
   module/socket or framework/platform import was added.
2. Architecture: existing message metadata transports replay; no new table,
   cache, coordinator, default model, or automatic tool executor was introduced.
3. Data flow: native response → canonical blocks → framework/transient/persisted
   metadata → retained history → actual SDK request is exercised. The additional
   interleaved-text cleanup bug was reproduced and corrected during this trace.
4. Plan adherence: finishes the locally runnable Gemini slice; F2 still includes
   canonical response unions, framework serialization, and caller contracts.
   F3–F10 remain active work, not claims inferred from adapter coverage.
5. Maintainability/security/performance: dictionary accumulators and reflection
   on known SDK fields are gone. No raw vendor payload enters error messages;
   malformed/filtered records cannot restore hidden tool calls. No DB or network
   operation was added to history conversion. Large-history benchmarking was not
   performed; retaining full response metadata follows the existing persistence
   envelope and is not claimed as a memory optimization.

The expanded local type hook includes Gemini and the transient message helper
with **zero diagnostics**. Broader LLM/caller checking is **54 diagnostics**, down
from 55; the remaining caller/serialization errors stay in F2. Ruff, documentation
validation, and whitespace checks pass. All vendor bodies, tool effects, context
resolution, and delivery sinks were substitutes except the local TCP transports.
No live Google account, operator DB, published-agent/widget/voice session, durable
sink, or external mutation was exercised. No deployment, migration, dependency,
commit, or operator-data change; probes remain ephemeral.

**Canonical LLM content: implemented and locally verified**

- Cause: `LLMContentBlock.content: Any` let the discriminator disagree with its
  payload. Callers compensated with string/dictionary/reflection fallbacks;
  annotations alone did not guarantee which content was safe to display or execute.
- `LLMContentBlock` is now a discriminated union of `LLMTextContent`,
  `LLMThinkingContent`, and `LLMToolContent`. Producers construct concrete variants;
  parsing a saved response validates the same union. The JSON envelope retains
  `type`, `content`, and `id`; the Python union itself is no longer a constructor.
- Text and thinking carry `LLMTextBlock`. Tool content carries `LLMToolUseBlock`
  with nonblank identity, matching optional outer ID, and finite JSON arguments.
  Arbitrary Python objects, mislabeled payloads, and unknown fields are rejected.
  Envelope fields are frozen; nested tool-argument dictionaries are not claimed
  to be deeply immutable.
- Removed the unused image-output enum value: none of the eight current adapters
  produces it. This does not change user image inputs, their separate message
  contracts, or existing native-adapter refusals of unsupported output.
- All native producers, transient swarm messages, conversation/framework
  conversions, background-prompt extraction, tool-batch extraction, and the module
  message writer use concrete payload fields. Shared tool-batch validation still
  happens before executable output is exposed; no second tool authority was added.

Executed evidence:

- **49 canonical contract assertions**: union discrimination, JSON readback,
  frozen tags, malformed/non-finite arguments, identity mismatch, caller text/tool
  extraction, framework-kind translation, and original replay-block indexes.
- Native SDK transport regressions: Anthropic/Bedrock **1,392**, OpenAI Chat
  **353**, Responses **452**, Groq **301**, Cerebras **291**, Sarvam **353**, and
  Gemini response/replay **175** plus two-turn callers **42**. Fixtures use pinned
  SDKs, not live vendor accounts. Earlier probe invocations using the obsolete
  `response_content` argument were corrected to the current complete-response
  signature without changing expected outcomes.
- Shared history **2,563** assertions across eight adapters, framework bridge
  **88**, and native SDK/caller history **64** pass with concrete union fixtures.
- No production `LLMContentBlock(...)` constructor or image-output enum reference
  remains. The expanded LLM type hook includes the canonical response file and
  passes; the broader LLM/caller baseline remains **54 diagnostics**, not zero.

This is an internal contract slice, not live product QA. No operator DB, worker,
widget, external tool mutation, migration, dependency, deployment, or commit was
changed. Response metadata was not covered by the content-union slice; the
following increment addresses that separate boundary.

**Canonical LLM metadata: implemented and locally verified**

- Shared `LLMResponseMetadata` owns validated stream flags and a discriminated
  text/thinking/tool-completion delta. Callers use `LLMResponsePhase` rather than
  interpreting raw dictionaries. Existing `streaming`/`final` wire predicates and
  their terminal interpretation remain compatible; the derived phase is not an
  extra persisted field or a second execution authority.
- Vendor completion DTOs own finish reasons, status, fingerprint, timing, safety,
  and signed Gemini replay. SDK types stay in adapters; the common metadata
  boundary accepts only JSON extensions, rejects non-finite values, and does not
  expose a generic dictionary-style `.get` compatibility API.
- Every native producer constructs the typed envelope. Conversation/voice
  streaming reads typed text deltas only; thinking and tool notifications do not
  become speech. The framework conversion explicitly serializes neutral JSON.
  Whole-batch tool validation, transport cleanup, and replay identity are unchanged.
- Serialization preserves omitted flags, vendor nulls, and nested include/exclude
  selections. This uses the pinned **Pydantic 2.11.10** environment and its
  [documented serialization hooks](https://docs.pydantic.dev/2.11/concepts/serialization/)
  plus runtime validation of [extra fields](https://docs.pydantic.dev/2.11/api/config/#pydantic.config.ConfigDict.extra).
  No dependency version or global duck-typing serialization setting changed.

Executed: **97 metadata assertions**, **49 content assertions**, all eight native
adapter regressions from the preceding milestone, Gemini two-turn callers **42**,
and native SDK/caller history **64**. The scoped type gate passes; the broader
LLM/caller probe remains **54 diagnostics**. Full server/CLI Ruff also passes.
No live vendor account, operator DB, worker, widget, or external mutation was used.

Dependency limitation: requesting only part of a nested discriminated union with
`include` emits serialization warnings in Pydantic 2.11.10. A minimal plain model
without Eylo code reproduces it. The metadata probe records **12 warnings** for
six partial-selection cases and verifies their exact output; full dumps and
exclusions are warning-free. No production warning filter was added. The normal
adapter/replay flows do not use this partial-selection operation.

**Framework metadata and critical callback boundary: implemented, locally verified**

- Reproduced metadata loss through an actual `RunInput` containing message and
  tool metadata subclasses: direct owner dumps retained fields; nested framework
  dumps serialized only the base schema. This is a default snapshot contract
  defect, not evidence that existing DB rows lost data.
- All ten explicit framework metadata fields use scoped `SerializeAsAny`.
  Owner exclusions, `SecretStr` masking, and caller include/exclude remain effective.
  Unrelated nested model fields retain normal declared-schema serialization; no
  global duck-typing override was added. Runtime-only `RunContext.local_context`
  stays accessible during execution and is excluded from all snapshots.
- `RunCallbacks` owns four typed critical operations, independent of mutable
  `local_context`. Conversation, background, scheduled, sandbox/objective, and live
  voice producers now bind operations on `FrameworkRunner`. Callback failures still
  stop the run; cancellation escapes; `RunHooks` remain best-effort observers. No
  new execution lane, persistence authority, or framework-to-platform import.
- Actual conversation callback and durable transcript-bridge signatures now name
  `RunContext` and `RunInput`. Callback wiring is immutable and shared safely across
  runner invocations; each invocation retains its own runtime context.
- Executed **106 metadata assertions**, **299 callback assertions**, conversation
  bridge regressions **88**, native SDK/caller history **64**, and Gemini two-turn
  callers **42**. Callback QA covers every callback failure/cancellation position,
  ordered durable command/result recording, streamed entrypoints, invalid refresh
  results, observer failures, approval/disabled-tool policy, terminal tool output,
  and eight concurrent runs. Provider/DB effects are
  substituted; these checks do not establish live vendor or worker recovery health.

The callback-path type baseline improved from **51 to 48 diagnostics**. The full
framework-directory probe still reports **14** pre-existing diagnostics in
guardrail/session protocol stubs and sandbox runtime fields; the scoped hook does
not conceal or certify those files.

Milestone review followed DDD boundaries, architecture fit, source-to-sink flow,
plan adherence, then readability/security/performance. No new blocking finding in
this slice. Framework imports independently of the platform; the expanded local
type hook and server/CLI Ruff pass. Runtime state typing remains explicit debt,
not a dictionary compatibility shim hidden behind the callback contract.

**Run-state boundary and SOR wait: implemented, locally verified**

- `PlatformRunState` owns command IDs, a typed execution context, and separate
  command-step/durable-wait authority. `ConversationRunState` alone holds full
  tool-use rows, active user message, persistence cursor, and last-message ID.
  `AgentRunToolCommandRef` and `LiveVoiceToolCommandRef` are removed; callers
  pass actual UUID command identities instead of message-shaped stand-ins.
- Conversation run/resume, background, scheduled, objective, live voice, and
  realtime tool dispatch use the same typed state boundary. Scheduled/objective
  scope and participant objects replace `SimpleNamespace`; no DB row or default
  provider is fabricated. Shared model/gateway annotations recognize both actual
  conversation and non-conversation contexts. Handoffs require a real conversation.
- `execute_exact_tool` forwards generic caller-owned context unchanged; it does
  not inspect that context or import pipeline types. The dynamic registered-tool
  callable registry and its per-tool context requirements still need their own
  typed contract pass. This generic pass-through is not certification of that registry.
- Reproduced a real SOR caller/API mismatch: `execute_sor_mutation_tool` passed
  raw Absurd `step_name`/`timeout` arguments to `AgentRunWorkflowContext.await_event`,
  which requires keyword-only `event_name`/`key`/`version`. The pending-command
  branch raised `TypeError` before reaching the engine wait. Fixed the caller and
  protocol; the workflow wrapper retains versioned checkpoint IDs and indefinite
  waits. No DB transaction spans that wait. This is an executed local reproduction,
  not a claim of a newly observed failure in the operator DB.
- `CommandStepContext` is the step-only port for email, telephony, MCP,
  integrations, sandbox commands, and recording effects. Live voice never acquires
  event-wait authority. SOR and sandbox dispatch require a durable run separately.
- SOR tool-schema factories return their actual base types with typed payload
  fields. All **54 catalog tool JSON schemas** match their pre-change form.
- Local QA: **78 run-state assertions**, **52 actual resume-path assertions**,
  **284 SOR schema/wait-flow assertions**, and **299 callback regressions**.
  Covers ordered persisted message links, cursor progression, context replacement,
  command-map isolation, already-recorded resume results, approved/rejected/missing
  command cases, exact tenant/run/source receipts, early/foreign receipts,
  indefinite waits outside transactions, and cancellation. Fixtures use actual
  domain models; DB/provider effects are substituted. Initial fixture failures
  were corrected against the real enum, constructor, pinning, and external-ID
  contracts; product validation was not relaxed.
- Re-ran all eight native LLM branches (**3,317 assertions**), metadata roundtrip
  **106**, conversation bridge **88**, native SDK/caller history **64**, and
  Gemini two-turn callers **42**. These are local native-transport checks, not
  live provider, worker-crash, or real-DB recovery QA.
- Expanded local LLM/framework/caller gate: **47 files**, no unsuppressed errors.
  One pre-existing suppression remains on dynamic SOR declaration-function
  metadata; no new suppression was introduced. The expanded touched-caller probe
  still reports **23** diagnostics in MCP optional authority narrowing, objective
  outcome/heartbeat helpers, scheduled heartbeat helpers, and telephony credential
  factories. These files remain explicit debt, not certified by the scoped gate.
- Milestone review: DDD ownership, architecture fit, source-to-sink flow, plan
  adherence, then readability/security/performance. No new blocking finding in
  this slice. No external I/O, transaction expansion, schema migration, or vendor
  policy change was added by the run-state refactor.

**Durable caller contracts: implemented, locally verified**

- MCP mutation dispatch now narrows each required authority field explicitly.
  The previous combined `any(...)` guard already refused missing authority at
  runtime, but did not preserve its type for the mutation executor. Read-only
  dispatch still needs no mutation receipt; no authorization policy was widened.
- Reproduced two defects in all four copied Agent-run heartbeat helpers:
  `create_task` rejected a `Future` although the signature promised `Awaitable`;
  simultaneous heartbeat/child failure left the child exception uncollected.
  `pipelines/agent_run_heartbeat.py` now owns the operation for conversation,
  schedule, objective, and parallel-task executors. It accepts the declared
  awaitable, retains the 120-second claim extension and 30-second check interval,
  caps waits to the remaining active-time budget, and retrieves the child outcome
  on every exit. Cleanup failure does not mask the authoritative heartbeat error.
  The runtime's outer claim-renewal loop remains distinct from this budget check.
- `AgentRunToolCapture` replaces transient last-response dictionaries in scheduled
  and objective runs. Removed the unused captured response field; tool-call IDs
  remain correlated with the framework pause/completion before persistence.
- `ObjectiveCompletion` validates outcome/result/reason through one shared
  parser, used by both the control-tool response and canonical-result projection.
  Neither string coercion nor unchecked casts conceal malformed reasons. The two
  agent-visible control-tool schemas and continuation envelopes are unchanged.
- Parallel task origins explicitly refuse absent text before calling the typed
  JSON parser. The same domain refusal is retained, before any repository access.
- Local QA: **28 heartbeat assertions**, **27 MCP authority/receipt assertions**,
  **45 objective/capture assertions**, and the missing parallel-task payload probe.
  Includes actual framework completion/input pause and actual workflow-context
  budget/claim calls; DB/outbound/provider operations are substituted. Re-ran
  **78 run-state**, **52 resume**, and **299 callback** assertions.
- Local hook now checks **54 files**, zero unsuppressed diagnostics. The existing
  dynamic SOR declaration metadata suppression remains; no suppression was added.
  The same expanded caller probe fell from **23 to 11** diagnostics, all in
  telephony provider/credential construction. That is scoped progress, not a
  whole-platform type-check result.
- Verification gates: full server/CLI Ruff, pre-commit config validation, and
  `git diff --check` passed. Documentation verification passed: **46 pages,
  277 links, 89 packages, 1,128 Python modules, 5,839 docstrings, 47 diagrams**.
- Milestone review, in order: DDD boundaries, architecture fit, source-to-sink
  flow, plan adherence, then readability/security/performance. No new blocker in
  this slice. No new dependencies, worker lane, DB transaction, external effect,
  or persistence migration. Live provider/DB, worker-crash, and browser QA were
  not run; this does not certify those paths.

**Telephony execution config and caller imports: implemented, locally verified**

- One pipeline translation carries the validated organization config into four
  immutable socket-owned settings models. Required fields retain exact types;
  missing, blank, malformed, extra, and wrong-carrier settings are refused before
  client use. Secret values are absent from config representations and validation
  error text. No module/socket import boundary or provider-enum ownership changed.
- Replaced reflective factory selection and the `extra_config` dictionary with
  explicit service branches. Migrated verification, call control, number search/
  purchase client construction, and authenticated media activation. Exotel uses
  canonical `application_id` and `api_host`; stored/API fields are unchanged.
- Narrowed nullable Plivo/Vonage clients and aligned Vonage `end_call`/`send_dtmf`
  keyword parameters with the base service contract. Media query enrichment keeps
  the same result for every tested query subset and pre-populated metadata case.
- **Confirmed regression found during caller QA:** `LiveVoiceModelFactory`
  evaluated `ConversationContext` at import time while its import was under
  `TYPE_CHECKING`. Importing the telephony media route failed with `NameError`.
  Static checks and config-only probes did not exercise that boundary. The type
  now has a runtime import; the exact failing import passes. Added a local runtime
  import hook rather than treating a clean type check as sufficient evidence.
- Local function/contract QA: **271 config/factory assertions** across all four
  carriers, **1,097 caller assertions** including 1,024 metadata parity cases,
  and **78 assertions** across 12 Exotel/Vonage create/end/DTMF success/cancellation
  invocations. Real classes, client constructors, JWT signing, and request builders
  ran; provider HTTP/SDK effects and config resolution I/O were substituted.
  HTTP sessions closed on tested success/failure/cancellation paths. This does not
  claim live carrier operation, provider-account cleanup, or durable DB execution.
- Expanded caller verification: **81 modules import successfully**; the same
  **81-file type check has zero unsuppressed diagnostics**, with one pre-existing
  SOR declaration-metadata suppression. The prior 11 telephony diagnostics are
  resolved. The telephony hook expands from seven to **22 files**; other existing
  scoped hooks remain in place. Whole-platform typing is still incomplete.
- Milestone review, in order: DDD boundaries; architecture fit; config-to-client/
  request and authenticated-media data flow; plan adherence; readability,
  security, and performance. The import defect above is fixed. No new query,
  external effect, long transaction, dependency, provider default, migration,
  deployment, or API schema change was introduced by this slice.
- Remaining telephony work includes native request/response, error, number-search
  result, and media-event contracts. Typed settings are not a substitute for them.
  Live vendor, worker-crash, DB, browser, and real call QA were not run.
- Final gates passed: all four scoped type-hook commands, the new runtime import
  hook, full server/CLI Ruff, pre-commit configuration validation, and
  `git diff --check`. Documentation verification passed: **46 pages, 278 links,
  89 packages, 1,129 Python modules, 5,840 docstrings, 47 diagrams**. No console,
  widget, or static API schema change in this slice; their builds were not rerun.

**Background built-ins and one-shot worker: implemented, locally verified**

- Followed `BackgroundAgentWorker._run_implementation` through the implementation
  registry, title/summary generators, resolved provider, actual native SDK request,
  result normalization, and message/result projection. Kept platform prompts and
  task outcomes separate from vendor envelopes and durable lifecycle states.
- **Confirmed pre-existing defect:** the token counter returned components plus a
  total; its consumer summed all values, doubling estimates. A typed component
  breakdown now exposes one derived total. The reproduced 30-token input formerly
  returned 60; it now returns 30. Character-estimate fallback also handles nullable
  extracted text.
- **Confirmed pre-existing authority defect:** the worker resolved an exact
  background agent, then discarded it when entering the built-in implementation.
  The generator used the conversation's primary agent instead. The executing agent
  now travels through the registry to generation. Summary window accounting still
  uses the conversation model; the generator's config is resolved only after work
  is selected. Missing summary contact/agent context skips before inference.
- Typed generation overrides, prompt inputs, compaction triggers, worker outcomes,
  and persisted summary metadata replace positional/dictionary interpretation.
  Existing prompt instructions, thresholds, output caps, complete recent-group
  preservation, cumulative cursor keys, and outcome wire values are retained.
  No API or database schema change is required.
- **Regression caught before completion:** the one-shot worker imports the prompt
  runner through `pipelines/llm/runtime.py`; it still passed the old keywords and
  raised `TypeError`. Migrated that caller and the re-export. A stale summary
  package `__all__` entry also named the removed trigger helper; it is corrected.
  Both callers and declared exports now participate in local gates.
- Function/contract QA: **253 assertions** across 19 built-in implementation
  scenarios; **182 assertions** for threshold/config/metadata contracts plus ten
  one-shot worker cases; **72 assertions** across six completion-projection cases.
  Total: **507 assertions**. Tests use actual schemas, worker functions, SDK
  request/response handling, client closure, and cursor readback. HTTP, resolver,
  Redis mutex, metering, and DB I/O are substituted where stated. Success,
  empty output, missing authority, provider failure, cancellation, and persistence
  failure paths were exercised. These probes do not establish real DB rollback,
  distributed mutex safety, live vendor behavior, or human product acceptance.
- Expanded checks: **94 modules import**, including declared exports; the same
  **94-file type scope reports zero unsuppressed diagnostics**, with one
  pre-existing SOR suppression. Full server/CLI Ruff passes. Added all changed
  background callers to the existing LLM type hook, preserving the eight native
  adapter branches. Whole-platform typing remains incomplete.
- Milestone review order: DDD ownership; architecture fit; producer-to-native-to-
  message data flow; plan adherence; readability, security, performance. The
  consumer/export regressions above are fixed. Existing long-running coordination
  findings below prevent claiming the whole background subsystem complete.
- Next background slices, before closing F2:
  1. `BackgroundAgentWorker._run_prompt_agent` still wraps replay, model/tool
     execution, and callbacks in one transaction and carries its session into
     model construction. Type that complete caller flow, shorten transaction
     ownership, and verify tools/transcript/wait recovery.
  2. `ConversationLock` uses a 60-second value-`1` Redis mutex without renewal
     or token-checked release. An expired owner can delete a successor's lock.
     Resolve ownership/lifetime semantics and test actual Redis expiry/cancellation;
     mocked lock-scope QA above does not prove this safe.
  3. `get_max_tokens_for_model` retains a partial model table and a blanket
     200,000-token fallback for other catalog models. Verify capacities against
     authoritative vendor definitions before changing that policy.
  4. Continue task-result metadata, memory and swarm caller contracts, then the
     remaining provider request/response flows F3–F10. Do not infer native wire
     completeness from typed settings or a narrow passing check.
- No operator DB, provider configuration, service, migration, Git history, or
  deployment changed. Live agent/browser QA and human product review remain unrun.
- Final gates passed: all five local type/import hook commands, pre-commit config
  validation, full server/CLI Ruff, formatting of the 17 changed Python files,
  and `git diff --check`. Three source-parity checks confirm the title, summary,
  and one-shot instruction literals are unchanged. Documentation validation:
  **46 pages, 279 links, 89 packages, 1,130 Python modules, 5,845 docstrings,
  47 diagrams**. No UI surface changed in this slice; console/widget builds were
  not rerun.

**Prompt-only background worker and private replay: implemented, locally verified**

- Traced `BackgroundAgentWorker.run` through exact revision resolution,
  conversation snapshot, `FrameworkRunner`, `AgentRunTranscriptBridge`,
  `ExistingConversationModel`, the native SDK, and `WorkerResult`. Worker inputs,
  executable agent, model construction, result extraction, and task metadata now
  use their actual contracts. Handoffs remain disabled; no provider is inferred.
- Private transcript envelopes are typed as assistant text, tool call, or tool
  result. The row-kind enum belongs to `modules/agent_runs/domain.py`; the
  pipeline owns framework/persistence translation. Nested tool arguments/results
  remain dynamic at their declared boundary. No discriminator, column, enum type,
  migration, or stored JSON shape is added. Invalid owned envelopes fail closed;
  private validation inputs are excluded from formatted exception chains.
- **Confirmed pre-existing replay defect:** `_message_from_row` restored tool
  history without `request_id`; `with_replay_messages` appended it unchanged.
  Native history grouping rejected completed-call replay with `missing request_id`
  before HTTP. Fresh transient tool messages already carried that identity, so
  fresh-run-only checks missed the restore path. Reproduced using the HEAD parser
  and join functions against the same worker/native fixture, then verified the
  fix. The join now applies the current input's validated request ID, preserving
  original conversation messages, row IDs, and durable command IDs.
- Function/contract QA: **157 assertions** for typed rows, JSON round trips,
  byte bounds, malformed payloads, request correlation, command persistence,
  callbacks, result lookup, and safe errors; **210 assertions** across eight
  actual worker/framework/native-SDK cases; **22 assertions** through the actual
  scheduled/objective input constructors and native message projection.
  Total: **389 assertions**. Cases include fresh text/tool use, pending and
  completed replay, provider refusal, model/tool cancellation, and invalid replay.
  Completed replay made one native request and no tool invocation; pending replay
  made one native request after one invocation with the original command ID.
- Verification substitutes HTTP, DB I/O, resolver, and tool effects. It uses real
  domain/ORM/Pydantic objects, actual framework control flow and callbacks, and the
  installed native SDK. It does **not** establish real DB concurrency/rollback,
  worker-crash recovery, live provider behavior, or human product acceptance.
- Milestone review sequence: DDD ownership; architecture fit; persisted/private
  history to native request data flow; plan adherence; readability/security/
  performance. Fixed the replay identity defect and validation-error disclosure
  identified above. No new query per replay row, external effect, dependency,
  runtime authority, deployment, or operator-data change was introduced.
- **Transaction correction remains required; initial slice scope was too narrow.**
  Removing only the worker's outer `start_transaction` would break shared
  collaborators that call `get_transaction()` or retain its resolver. Resolve
  these prerequisites coherently, before removing the caller's session:
  1. `ExistingConversationModel.generate` / LLM config wiring: stop capturing a
     resolver session. The callable boundary below is implemented; its own read
     scope ends before inference when there is no caller transaction. Existing
     outer transactions are still reused until prerequisites 2–4 are completed.
  2. `AgentRunTranscript`: separate owned replay/read/write transactions and
     preserve commit-before-effect command identity, including scheduled/objective
     consumers. Existing explicit commits do not guarantee subsequent reads stay
     outside a transaction.
  3. System-tool availability and each owning tool pipeline: hydrate authority in
     short transactions; release them before vendor calls or durable waits.
     Curated/MCP execution and registered tools still use the ambient session.
     Wrapping an entire vendor operation in a smaller-looking transaction is not
     the fix.
  4. Remove the outer worker transaction after those boundaries are independently
     runnable, then verify real DB transaction lifetime and cancellation/recovery.
- Continue the Redis mutex lifetime, model-capacity catalog, task-result metadata,
  memory completer, and swarm caller work listed above. The passing scoped type
  checks do not mean platform-wide hardening or the background subsystem is done.
- Final local checks passed: **95 modules imported** with declared exports;
  **95-file type scope** reports zero unsuppressed diagnostics (one pre-existing
  SOR suppression); all five local type/import hook commands; full server/CLI
  Ruff; formatting of the five changed Python files; pre-commit config validation;
  and `git diff --check`. The Agent-run domain vocabulary joins the existing LLM
  type gate, without introducing CI.
- Existing native-adapter probes passed **3,317 assertions** across eight branches;
  run-state, resume, and callback probes passed **429 assertions**. The native
  harnesses initially still used the old background-prompt keywords; only their
  inputs were updated to the current `BackgroundPrompt` contract, preserving
  assertions. These are local substituted-transport checks, not live vendor QA.
  Documentation validation passed: **46 pages, 279 links, 89 packages, 1,130 Python
  modules, 5,857 docstrings, 47 diagrams**. Console/widget builds were not rerun:
  this slice changes no UI or public API schema.

#### Shared LLM model construction and pinned reads — verified local slice

- Updated all five default construction paths: conversation, live voice,
  prompt-only background, scheduled, and objective runners. The model accepts
  the domain-owned `ResolvePinnedLLM` callable, not a concrete resolver holding
  a session. Each invocation resolves current context and exact config ID/revision.
  Explicit resolver and model-factory injection remain supported.
- Removed the unused second generation-override dictionary. Framework
  `ModelSettings` translates directly to `LLMOverrides`; invalid models retain
  the sanitized `NotConfiguredError` contract. Caching uses
  `LLMPromptCaching`, streaming uses the pipeline-owned `LLMInferenceMode`.
  Framework settings, provider schemas, and persisted JSON remain unchanged.
- **Corrected the draft's transaction strategy before completion.** Unconditionally
  opening a second session while a runner holds its outer connection could
  exhaust the pool under concurrent load. `resolve_pinned_llm` now reuses an
  active caller-owned session without committing, rolling back, or closing it.
  When no caller session exists, it owns a short read-only scope, closes it on
  success/failure/cancellation, and returns an immutable `ResolvedLLM`.
  `current_transaction` is the non-allocating common DB accessor.
- This is a prerequisite, **not completion of the long-transaction correction**.
  Existing outer runner transactions still span native/tool work. Do not infer
  that a scoped config helper releases a transaction owned by someone else.
- Function QA: **259 assertions**, **14 native SDK requests over recorded HTTP**.
  Real transaction-context management, config wiring/resolver/domain translation,
  model generation, and scheduled/objective default runners are exercised.
  Checks cover one-slot session allocation, caller ownership, read-only cleanup,
  cancellation, exact authority forwarding, immutable secret-bearing values,
  caching precedence, both inference modes, and preserved injection seams.
  DB selection, HTTP, and durable persistence effects are substituted; no claim
  of real PostgreSQL pool/load/concurrency or live vendor QA.
- Existing local regressions passed: **389** private transcript/worker/replay
  assertions, **3,317** native-adapter assertions across eight branches, and
  **429** run-state/resume/callback assertions. Harness inputs were updated to
  the callable resolver contract; existing product expectations were retained.
- Sequential milestone review: DDD ownership; architecture fit; caller →
  framework settings → pinned config → native request/response flow; plan drift;
  clean code/security/performance. The nested-session risk above changed the
  draft. No new vendor default, authorization grant, database migration, UI/API
  schema, permanent test suite, or deployment is introduced.
- Expanded the local LLM gate to config domain/wiring: **97 scoped files**, zero
  unsuppressed diagnostics (one existing SOR suppression). **98 modules** import
  with declared exports. A separate check of `common/database.py` reports two
  pre-existing errors: synchronous `sessionmaker` with an async engine, and
  raw-string `AsyncSession.execute` for the application name. Those source
  expressions match HEAD; no new suppression was added. Resolve them with the
  shared transaction/session hardening, not by hiding them in this gate.
- Next: give private transcript reads/writes owned short transactions, preserve
  commit-before-effect and replay identity across all consumers; then untangle
  tool availability/effects and remove the remaining outer runner transactions.
  Continue the remaining caller and provider-native DTO flows in the full plan.
- Final checks: all five local type/import hook commands, full server/CLI Ruff,
  formatting for the nine changed Python files, pre-commit config validation,
  and `git diff --check` passed. Documentation validation: **46 pages, 279 links,
  89 packages, 1,130 Python modules, 5,862 docstrings, 47 diagrams**. No UI build,
  API regeneration, live provider call, DB migration, deployment, or commit ran.

#### Shared DB session contracts and post-commit ownership — verified slice

This prerequisite precedes independently scoped transcript operations. The
previous slice identified the async factory and raw SQL diagnostics; tracing the
real session lifecycle exposed related correctness defects rather than merely
annotation gaps.

- Replaced synchronous `sessionmaker` plus an untyped forwarding wrapper with
  native `async_sessionmaker[AsyncSession]`. The context manager and FastAPI
  dependency yield a real session; `with_transaction` preserves arguments/results
  through `ParamSpec` and `Awaitable`. The unused fallback generator was removed.
- Native transaction events own typed `BaseModel` notification batches. Before
  the fix, manual rollback left queued events available to a later commit;
  savepoint boundaries bypassed the wrapper. Successful savepoints now transfer
  their batch to the parent, and rollback discards only abandoned batches.
  Explicit outer commits publish once. Listeners inherit neither writer session
  nor writer event queue. In-process delivery remains best-effort, not durable.
- Final commit previously suppressed `PendingRollbackError`, making a failed
  transaction appear successful. Commit failures now propagate. Nested cleanup
  restores both context variables even if session close fails. This does not
  claim that repeated cancellation or rollback transport failures can never mask
  another exception; those fault combinations were not part of this proof.
- Application names now use bound, transaction-local PostgreSQL `set_config`;
  the previous raw string was rejected by SQLAlchemy before execution. Read-only
  transactions use explicit SQL text. Connection settings do not leak through
  the pool. SQL logging retains shapes/counts without parameter values.
- Source evidence: installed SQLAlchemy **2.0.45** matched the lockfile and QA
  image. Its native transaction hooks and async-session integration were checked
  against [SQLAlchemy's async event documentation](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-events-with-the-asyncio-extension).
  Bound transaction-local settings follow [PostgreSQL 17 configuration functions](https://www.postgresql.org/docs/17/functions-admin.html#FUNCTIONS-ADMIN-SET).
  No dependency upgrade or schema change.

Executed PostgreSQL/asyncpg QA: **194 assertions**, **39 committed rows**, **40
observed events**, and **30 concurrent writers** using a two-connection pool.
The runner imported current checkout source, not the image's baked source.
The database was disposable, network-isolated, memory-backed, and used dummy
credentials; no configured organization/provider data was touched.

1. Root and nested-savepoint commit/rollback, ancestor rollback, separate owned
   nested sessions, explicit transaction-object commits, registration before SQL,
   and no duplicate publication.
2. Actual deferred-constraint commit failure, body failure, in-flight SQL
   cancellation, simulated pending-rollback and session-close failures.
3. Read-only write rejection, quoted application-name binding, pooled setting
   isolation, wrapped callable signature, and per-task context isolation.
4. Event callbacks opened independent read scopes and observed committed rows.
   Final stored rows matched successful writes; rolled-back/error/cancelled rows
   were absent and zero connections remained checked out.

An additional **12 assertions** used the actual Eylo/Pyventus emitter with a
probe subscriber. It opened an independent read scope and saw the committed row;
an actual duplicate ORM flush followed by final commit raised
`PendingRollbackError`. No failed/rolled-back event reached the subscriber.
Source inspection confirms that conversation/message/participant DB listeners
already own read scopes; SOR/knowledge/memory observers log bounded facts without
DB access. Real product subscribers over WebSockets, live vendor calls, full HTTP
routes, worker crashes, and distributed delivery were not exercised here.

Existing regressions passed **4,394 assertions**: 259 shared model/resolver,
389 private transcript/worker/replay, 429 run-state/callback, and 3,317 native
adapter assertions. The scoped model harness now supplies a native `AsyncSession`
subclass with substituted DB selection; no product expectation was relaxed to
retain the removed wrapper. Combined with PostgreSQL/Pyventus checks, this slice
executed **4,600 assertions**. These counts describe the probe scope, not full
platform or live-provider coverage.

Sequential milestone review:

1. DDD: sessions and transactions remain infrastructure-owned; product payloads
   are accepted as `BaseModel` without importing their owning modules.
2. Architecture: preserves the context manager/decorator entrypoints, explicit
   transaction ownership, and best-effort local event authority. No new event
   service, outbox, dependency, or alternate session fallback.
3. Data flow: write → native transaction outcome → event batch → detached
   listener read was exercised on real PostgreSQL; rollback/savepoint/commit
   identity was checked independently from vendor transport fixtures.
4. Plan: this prerequisite fixes demonstrated lifecycle bugs exposed by the
   typing work. It does not complete transcript/tool scoping, shorten the outer
   agent-run transactions, or establish platform-wide type completeness.
5. Maintainability/security/performance: no DB-module casts or suppressions;
   two instance-owned hooks are removed on close. Queues are transaction-local,
   names are bound, log values stay private, and the pool is returned after
   concurrency/cancellation. No extra query is added to ordinary unnamed scopes.

Final local checks passed: all five type/import hooks, **98 scoped Python files**
with zero unsuppressed diagnostics (one existing SOR suppression), **98 module
imports**, full server/CLI Ruff, formatting, and `git diff --check`. Documentation
validation passed: 46 pages, 279 links, 89 packages, 1,130 Python modules, 5,861
docstrings, 47 diagrams. No permanent test suite, migration, deployment, UI/API
change, or commit. Console/widget builds were not repeated because their sources
and public schemas did not change.

#### Memory completion and dependency ports — verified slice

This completes the memory LLM-caller contract within F2, not the whole F5 memory
data flow. Formation, reconciliation, and config verification share
`MemoryTextCompleter`: keyword-only `system`/`user` inputs and an awaited text
result. Document and query embedding callables have separate signatures. The
pgvector adapter receives a native `AsyncSession` factory; verification owns a
structural embedding port and uses domain-owned `ResolvedLLM` authority. SDK
requests, responses, and credentials remain inside the selected LLM adapter.

- Current versus pinned dependency resolution uses a private enum; persisted
  values, public schemas, revision selection, and policy are unchanged.
- Local imports alias the existing `MemoryError` as `MemoryProviderError`.
  A reduced Pyrefly 0.38.2 reproduction incorrectly treated raised `MemoryError`
  construction as Python's builtin exception. The alias resolves that diagnostic
  without renaming the domain class, changing exception identity, suppressing a
  check, or upgrading a dependency.
- Native session typing exposed three generic SQL result consumers. Formation
  persistence, expiry, and deletion now narrow to `CursorResult` before using
  row count; the existing ambiguous/conflicting-write refusals remain intact.
  Operation application also narrows an already-required target ID before lookup.
  Remaining raw SQL rows, extractor JSON, and untyped durable helpers stay in F5.
- Six-file baseline: 32 diagnostics; adding the reconciliation consumer exposed
  three more. All seven files now pass the scoped check. This is not evidence
  that every helper in those files has been fully typed.

Executed contract/function QA: **98 assertions**, including **10 native OpenAI
SDK HTTP requests** through recorded transports. It exercised keyword-only
invocation, generation limits, prompt formation, selected vendor error identity,
empty/tool-bearing response refusal, usage accounting, budget failure, timeout,
cancellation, and client cleanup. Real formation/reconciliation parsers mapped
model indices to platform identities. Resolver current/pinned authority and the
actual verifier's embedding/completion/read path were exercised. Native SQLite
`CursorResult` fixtures checked accepted/rejected row counts and session cleanup.
DB selection/persistence, embedding I/O, and durable steps were substituted;
this was not live-provider or PostgreSQL memory-persistence QA.

Static contract probes accepted real runtime/verifier/session composition and
rejected eight diagnostics across invalid result types, keyword names, missing
arguments, positional invocation, and swapped document/query inputs. One runtime
probe initially assumed a provider string instead of the real enum value; the
probe was corrected to the selected provider authority, with no product change.

Existing regression probes passed **4,394 assertions**, including **3,317 native
adapter assertions across all eight factory branches**. Combined with the new
probe: **4,492 runtime assertions**. All five local type/import hooks, full
server/CLI Ruff, seven-file formatting, pre-commit config validation, and
`git diff --check` passed. The LLM hook now includes these seven memory files;
it reports zero errors and retains one pre-existing SOR suppression.
The expanded milestone import probe loaded **105 modules** and checked their
declared exports. Documentation validation passed: 46 pages, 279 links, 89
packages, 1,130 Python modules, 5,863 docstrings, and 47 diagrams. The three
temporary static probe files and their empty temporary directory were removed.

Sequential milestone review:

1. DDD: callable contracts are vendor-neutral; memory verification owns its
   dependency port. No socket/module imports cross their boundary.
2. Architecture: existing factory, revision authority, parser, and durable task
   paths remain the execution authorities; no second memory runtime or fallback.
3. Data flow: selected config → native SDK → metering → validated text → typed
   operation/proposal is exercised with real types. Provider calls and parser
   failures are not mistaken for committed DB effects.
4. Plan: this is F2 caller hardening. Native embedding/reranking requests,
   persisted memory rows, and durable lifecycle contracts remain in F5.
5. Maintainability/security/performance: no casts, broad callable arguments,
   ignored diagnostics, new dependencies, new DB queries, or expanded privileges.
   Types supplement—not replace—runtime authority and response checks.

The transcript prerequisite remains open. Source tracing found that
`resume_agent_run_in_transaction` holds the AgentRun row lock while scheduled
and objective runners execute. Moving transcript writes alone to another session
could wait on that same lock. Resume, transcript, and tool transaction ownership
must change together; no temporary borrowed-session mode was introduced then.
At that milestone, the transcript's duplicate-correlation lookup also preceded
its run lock. The later transcript/tool-preparation slice below reproduces and
fixes that race; caller transaction ownership remains open. Neither issue was
fixed by this memory work.

No operator DB changes, live vendor calls, worker recovery QA, UI/API changes,
migrations, deployments, or commits ran. Temporary probes are local working
tools, not a shipped test suite.

#### Swarm caller authority — actor binding verified; shared dispatch pending

The F2 trace reached `SwarmAgentWorker._load_agent_and_tools` → `_execute_tool` →
`_get_conversation_context` → `kb_query`. Before this fix, the model used the
task's exact topology member and tools, but tool context was rebuilt from the
conversation's primary participant. `kb_query` took `ctx.primary_agent` as its
grant authority. The cached context was not bound to the selected worker member.

A local reproduction passed **11 diagnostic assertions** through the real worker,
exact system-tool dispatcher, knowledge tool, and memory actor validator. The
knowledge-query I/O and conversation lookup/build were substituted. It observed
the parent agent at the query boundary while the task targeted another member.
This proves incorrect authority propagation, not observed disclosure from a live
KB or a cross-organization bypass. Parent grants could be used instead of the
target's grants. The original author's reasoning is not established by source.

Replacing only `ctx.primary_agent` was also checked: memory's actual actor guard
rejects the unchanged primary participant with `Memory agent provenance is
unavailable.` The prompt background worker performed that replacement too,
so both callers belong in this identity review. Do not invent participant IDs,
change the live conversation's primary agent, or weaken the memory provenance
check to satisfy a type annotation.

TODO/status for this coupled caller slice:

1. **Done:** Define the exact task execution authority independently of conversation
   presentation: selected agent/revision, explicit tools, permitted contact/
   conversation context, and valid actor/provenance.
2. **Actor binding done:** Resolve the actual participant authority for task tools;
   keep selection and runtime provenance consistent without borrowing the
   parent's grants. Preserve pinned voice policy and primary-participant state.
3. **Done:** Type the loader result, cached context, tool arguments, and result
   boundary. The initial six-file check had 37 diagnostics: one cache assignment
   and 36 downstream errors from an ORM class annotated as an instance.
4. **Open:** Reuse the shared tool execution paths where applicable. The current direct
   dispatcher executes only system/local tools, while the advertised set can
   include other kinds; approvals, durable receipts, and recovery must retain
   their existing authorities rather than receive a second implementation.
5. **Verified within the bounds below:** Parent-only versus target-only KB grants,
   actual memory actor/scope validation, blocked/unmapped tools, cancellation,
   pinned revisions, and unchanged persisted primary conversation state. Full
   memory write/reconciliation and live widget/vendor QA remain unrun here.

Implemented actor slice:

- `SwarmWorkerRuntime` holds one exact executable agent and resolved LLM. Tool
  input/results use JSON value contracts; invalid runtime outputs become the
  existing safe tool failure. Cancellation still propagates.
- `ConversationParticipantService.ensure_agent_actor` reuses or creates an actual
  participant for the exact agent/revision. The conversation lock serializes
  this path with handoff. Creation is non-primary and emits the existing event
  only after commit; rollback does not publish it.
- `AgentTaskConversationContext` validates the actor against the selected agent,
  organization, conversation, and participant list. Its task-local actor getter
  does not rewrite persisted flags. Both task workers use this DB-only builder;
  no parent model, memory provider, or voice config is resolved then relabelled.
- The existing transient result formatter now accepts a read-only `Sequence`,
  matching its actual use and allowing typed result collections without casts.

QA: **186 assertions** passed against an isolated PostgreSQL 17 instance migrated
through real Alembic `eylo0012`. Twenty-four concurrent context builds with a
two-connection pool reused one actor row. Actor/handoff concurrency, transaction
rollback, cancellation while waiting for a lock, invalid identity/revision,
foreign-org rejection, and post-commit event registration passed. Native OpenAI
SDK → real system-tool dispatch → real PostgreSQL grants/FTS → correlated native
tool result returned only the target's content. The parent's separate query
returned only its own content. Topology/config resolution and metering were
substituted at typed ports; HTTP used recorded transport. Memory's real scope
and actor guards ran, but memory persistence and live provider calls did not.

The QA runner initially selected source baked into its image instead of the
read-only checkout mount. Setting its working directory and asserting the loaded
package path fixed the harness; the passing run used current source. Another
setup attempt used ORM `create_all`, which omits a migration-owned enum; real
Alembic migrations replaced that setup. Neither issue required product changes.

Prompt background regression coverage passed **234 assertions**, including
pending/completed replay, tool cancellation, HTTP failure, and unchanged source
context. The native-adapter probes were updated from old tuple loader stubs to
real `SwarmWorkerRuntime` objects without weakening response expectations:
**3,317 assertions** passed across eight factory branches. Other caller/runtime
probes passed **965 assertions**. Combined executed runtime assertions: **4,702**.
The expanded import probe loaded **109 modules** and checked declared exports.
All five type/import hooks and full server/CLI Ruff passed; the six actor files
have zero type errors. The LLM hook retains one pre-existing SOR suppression.

Sequential milestone review: DDD keeps participant persistence in its module and
task composition in pipelines; SDK types do not cross into domain services.
Data flow preserves explicit tool grants and actor provenance. Lock ownership is
DB-only; native model/query boundaries observed no checked-out actor-build DB
connection. The participant listener and widget consumer were inspected: they
publish/store participant data rather than perform a handoff. Browser delivery
was not exercised. The actor slice meets its scope, not the full caller plan.

The synthetic DB was removed after QA. No operator DB changes, source migrations,
deployments, live vendor calls, or commits ran. Shared swarm dispatch and the
resume/transcript transaction ownership remain required follow-ups, not accepted
release exceptions or work completed by this actor fix.

#### Transcript and tool preparation — verified prerequisite, not runner completion

The F2 shared-dispatch trace reached two implicit dependencies: availability and
MCP preparation required a caller-owned transaction; transcript writes checked
duplicate identity before acquiring the run lock. Removing the outer runner
transaction without resolving these dependencies would break execution.

Completed in this slice:

1. `AgentRunTranscript._append` now locks the organization-owned run before
   correlation lookup. The real-PostgreSQL baseline synchronized two misses and
   reproduced one `IntegrityError`. After the fix, 24 simultaneous identical
   writers reuse one row; 24 distinct writes get contiguous sequence numbers.
   Different content under one identity remains an error. Wrong/deleted owners,
   rollback, cancellation while waiting for the lock, and pool release passed.
2. Transcript JSON validation now checks the original Python representation for
   non-finite numbers. Pydantic 2.11.10 matches the lockfile and installed runtime;
   its documented [non-finite serialization default](https://docs.pydantic.dev/2.11/api/config/#pydantic.config.ConfigDict.ser_json_inf_nan)
   changed NaN/infinity to null before the existing guard. A parent serialization
   setting alone did not fix independently serialized framework metadata. The
   final guard checks original arguments, results, and metadata without changing
   valid JSON encoding. Circular payload failures use the same safe domain error.
3. Tool availability now consumes typed scope/agent contracts. Direct email and
   memory fields replace constructed `getattr` keys. Existing partial overrides
   and exact revision semantics are preserved. Explicit session wins over ambient;
   without either, the function owns a read-only scope and publishes facts after
   it exits. Failure/cancellation preserve the previous facts. Borrowed sessions
   are neither committed nor closed.
4. MCP preparation validates a `Mapping[str, object]` into JSON values before
   config lookup or network work; no framework-wide cast or SDK type was added.
   It resolves the encrypted exact server revision in an owned read-only scope
   when there is no ambient session, then invokes the native MCP client outside
   that owned scope. Borrowed-session behavior remains explicit. Missing/revoked/
   foreign revisions and unsupported effects fail closed; mutations still require
   the existing durable command context.

Executed function/contract QA:

- Isolated PostgreSQL 17, real migrations through `eylo0012`, two-connection pool:
  **21 transcript**, **32 availability**, and **65 MCP** assertions. Configs and
  secrets were synthetic; actual persistence, decryption, revision lookup, native
  MCP request/response handling and egress models ran. MCP HTTP transport was
  recorded, not live. Both owned and borrowed DB lifetimes were observed at send.
- **44** non-finite/finite payload assertions plus a circular-input refusal probe.
  **157** existing transcript, **22** scheduled/objective replay, and **299** typed
  callback assertions passed. The transcript mock's lookup order was updated to
  owner-first; expected replay/content/commit outcomes were not weakened.
- **3,317** native LLM adapter regression assertions passed across eight factory
  branches, using recorded transports. These are not new live-vendor results.
- Both availability files are now included in the existing local LLM contract
  hook. All five type/import hooks pass; the LLM hook retains its existing one
  SOR suppression. Full server/CLI Ruff and four-file formatting pass.
  The 109-module import probe, pre-commit config validation, and whitespace check
  passed. Documentation verification passed: 46 pages, 280 links, 89 packages,
  1,131 Python modules, 5,873 docstrings, and 47 diagrams.

Milestone review, sequentially: DDD keeps config/grant data in modules and
composition in pipelines; framework types remain vendor-neutral. Existing
transactions, factories and receipt authorities are reused. Data-flow checks
cover persisted identity and actual encrypted config → native protocol → typed
result. No new migration, vendor behavior, grant, fallback, dependency, or public
API was introduced. Validation adds a pre-DB traversal; no extra provider call
was introduced. Locks still belong to the caller transaction.

Remaining dependencies, in order:

1. Trace curated grant/auth preparation and remaining registered system tools;
   make their DB-only preparation independent of long-running outer transactions.
2. Coordinate resume lifecycle, transcript persistence, and runner result writes;
   do not move transcript writes into another session while resume holds the
   same run lock. Scheduled/objective/background outer scopes are still open work.
3. Route swarm execution through the shared framework/tool dispatcher, preserving
   task actor identity, approval waits, durable receipts and replay. Then finish
   F2 caller coverage and continue F3–F10 in the agreed provider data-flow order.

These probes do not establish live widget behavior, vendor interoperability,
durable crash/restart recovery, or human-reviewed product acceptance. No operator
DB changes, source migrations, deployments, or commits were made. The isolated
synthetic QA DB/container was removed; absence was verified. No probe files or
shipped test suite were added.

#### Curated-tool preparation — verified F2 prerequisite

Trace: `PlatformToolExecutor` → `execute_curated_tool` → module policy grant →
scoped external connection → decrypted origin-bound auth → registered vendor
handler → guarded HTTP request → outbound receipt/result. This follows the
agreed data-flow order; it does not mark the full F2/F3 contract work complete.

Baseline findings and fixes:

1. Both policy and connection lookup implicitly required an outer transaction.
   The no-session baseline reproduced `TransactionContextError` before dispatch.
   Each DB-only preparation step now owns a read-only transaction when no service
   or ambient session is supplied. Explicit services are used for both lookups;
   borrowed sessions are never committed or closed. Module services still own
   policy and return DTOs, not ORM rows. Vendor I/O follows owned-scope exit.
2. `execution_mode` and installation `auth_kind` were annotated enums but used
   plain string ORM columns. The service also assigned `.value` to enum-typed
   attributes. Non-native SQLAlchemy enums now preserve the existing VARCHAR(32)
   representation, values and check constraints while returning enum members on
   fresh readback. Service writes use enum members. No migration was required.
3. Disabled-tool refusals incorrectly set `approval_required=True`. The baseline
   reproduced this metadata defect; no evidence showed that this flag itself
   starts a durable wait. Only `ToolApprovalRequiredError` now sets it. Disabled
   tools retain `tool_execution_blocked`, with no vendor call.
4. Arguments/results used broad `Any` at the executor boundary. Arguments now
   enter as `Mapping[str, object]`, validate as finite JSON, then use each vendor
   input model's existing normalization. Results/metadata carry JSON values;
   non-JSON handler output returns safe `tool_result_invalid` without retrying a
   possibly completed effect. Credential mapping values are `object`, narrowed
   by the existing wire-auth validation, rather than unchecked `Any`.
5. Credential resolution verifies connection organization against the grant
   before decryption and uses the authoritative grant organization in its cipher
   context. Existing vendor/auth/instance/scope/expiry checks remain. The old
   docstring incorrectly claimed inline refresh; this function refuses expiring
   credentials and performs no refresh HTTP operation.

Executed function/contract QA:

- **91 assertions** against isolated PostgreSQL 17 with real migrations through
  `eylo0012`, synthetic encrypted credentials, real repositories/services, and
  the actual registered GitHub search handler and guarded HTTP request model.
  Recorded transport observed no owned DB checkout at vendor send. Checks covered
  exact organization/contact auth headers, personal-account preference, missing/
  foreign/deleted tools and installations, revoked-account fallback, expiry,
  scopes, malformed module DTOs, injected services without an ambient context,
  caller rollback, input/result refusal, cancellation and egress/timeout errors.
- A synthetic mutation handler used the real outbound DB path: one succeeded
  receipt, `send_count=1`, followed by invalid result reporting. Replaying its
  command checkpoint did not resend; the existing response-reconstruction limit
  returned `vendor_outcome_unknown`. This is not an Absurd crash/restart test.
- **84 assertions** covered all wire-auth kinds, both API-key placements, invalid
  credentials, finite JSON, arbitrary Python objects and cycles. **299** existing
  callback regression assertions passed. The **109-module** import probe passed.
- All five local type/import hooks pass; the curated hook now includes these five
  preparation/model/service files. The LLM hook retains its existing one SOR
  suppression. Full server/CLI Ruff, five-file formatting, pre-commit config and
  whitespace validation passed. Documentation validation passed: 46 pages,
  280 links, 89 packages, 1,131 modules, 5,873 docstrings and 47 diagrams.
- Isolated `alembic check`: no new upgrade operations. Existing FK-cycle and
  unrecognized vector-type comparison warnings remain; this is not a claim that
  Alembic exhaustively validates those unrelated objects. The first fixture run
  passed a UUID to string-typed `ParticipantInDb.entity_id`; correcting the probe
  to the actual contract required no product change.

Sequential milestone review:

1. DDD boundaries: module policy and DTOs remain authoritative; credential
   translation and execution orchestration stay in pipelines.
2. Architecture fit: existing transactions, enum persistence pattern, registry,
   egress and receipt authorities are reused; no new execution lane or catalog.
3. Data flow: preparation, exact auth, denial/error/cancellation, actual request
   construction and receipt sinks were exercised, not only a handler stub.
4. Plan alignment: this removes curated preparation's dependency on an outer
   transaction, not the outer runner transactions themselves. All F0–F10 work
   remains in scope; broader vendor request/response models are not completed by
   the JSON envelope validation.
5. Maintainability/security/performance: no casts, suppression, dependency,
   permission or retry was added. JSON validation adds bounded-by-input traversal;
   it is not a new payload-size budget. DB query selection and vendor request
   count are unchanged. No extra provider lookup/refresh or secret output.

Next: finish remaining registered system-tool preparation, then coordinate
resume locks, transcript/result writes and shared swarm dispatch. Full curated
vendor schemas, error-code enums and registry callable typing remain in F3;
continue through F10 in the established order. Live vendor/widget QA and human
product review were not performed in this slice. No operator DB, source migration,
deployment or commit changed. The isolated tmpfs QA DB/container was removed and
absence verified; no temporary probe files were added to the repository.

#### Parallel-task filing — verified F2 prerequisite

Trace: exact registered system tool / conversation background attachment →
published topology and agent refs → task content and manifest → message filing,
budget reservation and AgentRun → Absurd binding → worker-origin validation →
task-result message and terminal AgentRun projection.

Completed this slice:

1. Corrected the initial diagnosis: `TaskDispatcher` construction does not acquire
   a DB session. The no-session baseline fails during actual filing's user-session
   lookup in `BaseORMRepository.db_session`. Filing now owns a short transaction
   when none exists; topology and attachment resolution own read-only scopes.
   Existing caller sessions are reused. Filing preserves the legacy explicit
   commit-before-spawn contract, not a claim that borrowed writes never commit.
2. `ParallelTaskKind` derives from the already validated task references.
   `TaskDispatchStatus`, `ParallelTaskManifest` and `ParallelTaskMetadata` replace
   independent string/dictionary inputs. Existing JSON keys, enum spellings,
   optional-key omission and independent request lifecycles are preserved.
3. Worker readback validates the persisted manifest's shape and matches its
   conversation, task kind and source revision against the immutable task.
   The registered tool explicitly refuses non-conversation execution scopes.
4. Real DB QA exposed an existing retry defect: a stable background filing key
   was paired with a freshly supplied request UUID. The service correctly refused
   that changed input. The dispatcher now leaves ID allocation to the filing
   service. Task status is mutable execution output and no longer prevents reuse
   of an otherwise identical PENDING task filing. Other message kinds retain
   their status comparison; changed content and authority still conflict.
5. Background dispatch counts only successful filings, not `None` results.
   The message service's existing organization refusal now explicitly narrows
   `None`; its retry comparator consumes the real `MessagesModel` type.

Executed verification:

- **164 assertions** using isolated PostgreSQL 17, actual migrations through
  `eylo0012`, synthetic organizations/config revisions/budgets/published agents,
  real topology/attachment resolution, message services/repositories and native
  Absurd spawn/binding. All three task arms passed manifest readback. Exact tool
  dispatch covered invalid inputs, disabled policy and non-conversation refusal.
- Sequential and concurrent retries produced one message/run/task binding.
  Processing/completed status did not prevent retry reuse; changed instructions
  still conflicted. Cross-organization context was refused. Owned scope failures
  and cancellation rolled back both product rows and pending events. Spawn
  failure retained the unbound run; subsequent native spawn bound it once.
- Terminal persistence used real product claim acquisition and recorded worker
  outputs for all three arms. Result messages retained conversation/parent/run
  links and worker kind; runs completed. These are not live LLM executions or
  worker-process crash/restart tests.
- All five existing local type/import hooks pass; task dispatch, background
  dispatch and message services were added to the LLM hook. Direct checking of
  `spawn_task_fnf.py` still reports its two pre-existing dynamic callable-metadata
  assignments. No suppression was added; registry callable contracts remain open.
  The callback regression probe passed **299 assertions**. Full server/CLI Ruff
  and changed-file formatting passed.
- Initial probe errors were corrected without weakening product validation:
  missing conversation title, omitted synthetic execution budget, and incorrect
  probe UUID/principal-field references. Successful results above come from the
  corrected full probe, not those incomplete runs.

Sequential milestone review:

1. DDD: shared task routing stays in common contracts, task-owned persistence
   envelopes in the parallel-agent module, orchestration in pipelines. The
   framework and vendors acquire no platform imports.
2. Architecture: existing message/AgentRun budget/Absurd authorities are reused.
   No new scheduler, default config, table, migration or execution lane.
3. Data flow: actual DB filing, exact refs, retries, transaction exit, native
   binding and terminal sinks were exercised. The retry fix is backed by the
   reproduced conflict; a constructor assumption was explicitly rejected.
4. Plan: this is prerequisite preparation work, not completed F2 or F0–F10.
   Handoff and generated-widget persistence, coordinated outer-runner transaction
   removal, shared swarm dispatch and remaining vendor schemas stay in scope.
5. Maintainability/security/performance: derived routing avoids a second flag;
   typed manifest comparisons preserve tenant/source/target authority. No new
   dependency, cast, ignore, vendor request or secret output. Borrowed session
   commit semantics remain explicit until outer-runner work is coordinated.

Live widget/vendor QA and human product review remain pending. No operator DB,
migration history, deployment, commit or persistent probe file was changed.
The 109-module import probe and documentation validation passed (46 pages,
280 links, 89 packages, 1,131 modules, 5,879 docstrings and 47 diagrams). The
isolated tmpfs QA DB/container was removed; absence was verified.

#### Handoff contracts and caller refresh — verified F2 prerequisite

Trace: generated handoff declaration → framework/native call → pinned swarm
resolution → expected-primary participant switch → typed outcome → complete
context rebuild → native prompt/tools update and attributed transcript.

Completed:

1. `HandoffInput` validates optional continuation text. `HandoffState` replaces
   independently stored success/error/loop flags; compatibility flags derive
   from one outcome. Successful outcomes require a matching target agent and
   participant revision. Existing history and per-turn limits have named
   constants; non-text input is refused, absent/null/empty text remains accepted.
2. `execute_handoff` owns a short DB-only transaction when needed and explicitly
   passes its session to topology and participant services. Borrowed sessions
   are neither committed nor closed. No participant/primary-agent mutation is
   applied to the caller's context; both callers rebuild it after persistence.
3. Caller QA exposed a missing generated-tool arm in the stricter metadata
   projection: handoff declarations were unrevisioned `LOCAL` tools. The
   conversation-owned `HandoffTool` and pipeline-owned handoff metadata now
   identify the target agent revision. Ordinary unrevisioned local tools remain
   refused. No tool row, fake tool revision or prefix-based exemption was added.
4. Realtime's failed-rebuild fallback relied on the removed partial mutation.
   It now uses the existing `REALTIME_HANDOFF_FAILED` teardown, like native
   session-update failure, rather than continuing with mixed authority.
5. Realtime dispatch returned dictionaries/lists where `_ToolInteraction` and
   the adapter contract require text. Structured results now become JSON text
   once at dispatch; existing text and the list-content envelope are preserved.

Executed function/data-flow verification:

- **236 assertions** on isolated PostgreSQL 17 with real migrations through
  `eylo0012`, synthetic published agents, instruction templates, provider refs
  and a pinned swarm. Real services/repositories and both text/realtime callers
  exercised persistence and full context rebuilding. Native I/O was recorded,
  not sent to a live provider.
- Refusals cover missing topology, foreign organization, nonmember/same-agent
  targets, wrong source revision, malformed text, and handoff limits/loops.
  A stale context cannot replace the selected primary. Concurrent stale
  requests produce one successful switch and one refusal/error, not two
  primaries. Owned failure, cancellation and failed commit roll back writes and
  pending events. Borrowed changes stay invisible until their owner commits.
- Text metadata and realtime buffering preserve the initiating participant.
  Successful rebuild updates agent/dispatcher/participant context; the provider
  receives only new prompt/tools, never a replacement voice. Rebuild and native
  update failures execute real teardown against recorded provider I/O and do
  not send a continuation result. Structured Unicode/dict/list/empty results
  reach both the buffer and adapter as text.
- Generated declarations carry agent authority; ordinary local tools still
  require a published tool revision. Invalid generated revisions are refused.
  **299 callback assertions**, **109 module imports**, all five local type/import
  hooks, full server/CLI Ruff, and changed-file formatting pass. The existing
  LLM type hook now also checks batch execution and realtime dispatch; no new
  suppression was added.
- Direct checks still report two pre-existing diagnostics in `realtime.py`
  (event-handler variance and Awaitable/create_task) and two in conversation
  schemas (required-org override and message reconstruction). These remain
  open; no full-file/full-platform typing-complete claim is made.
- Early fixture runs omitted authored instructions and then the explicit
  template variable schema. Both were corrected in synthetic data; product
  validation was not weakened. The generated-tool failure was a real caller
  defect, fixed before the successful complete run.

Sequential milestone review:

1. DDD: generated handoff identity belongs to conversations; outcome and
   framework translation belong to pipelines. Vendor and framework imports
   retain their boundaries.
2. Architecture: existing topology, locks, transaction/events, context rebuild
   and voice teardown remain authoritative. No new execution lane or DB schema.
3. Data flow: actual caller construction caught the missing generated-tool arm;
   real rollback/concurrency/context and transcript paths were verified, not
   only an isolated dispatch stub.
4. Plan: completes another F2 prerequisite, not all F2 or F0–F10. Generated-widget
   persistence, coordinated outer-runner scopes and remaining provider contracts
   remain open in dependency order.
5. Maintainability/security/performance: named states and explicit projections
   replace flag combinations and revision assumptions. Existing tenant/revision
   checks and query bounds remain. JSON output adds one serialization, not a
   provider lookup or retry. No cast, suppression, dependency or secret output.

No operator DB, migration history, deployment or commit changed. Live widget/
vendor QA and human product review remain pending; these probes do not establish
worker-process recovery or spoken-audio quality. No probe files were added to
the repository. The disposable QA DB/container was removed; absence was verified.
Documentation validation passed: 46 pages, 280 links, 89 packages, 1,131 Python
modules, 5,885 docstrings and 47 diagrams. `git diff --check` also passed.

#### Generated-widget input and transaction contracts — verified F2 increment

Trace: registry schema → exact model-visible tool dispatch → widget validation →
conversation message service → PostgreSQL and post-commit event → typed terminal
artifact and interactive-response readback.

Completed:

1. The interfaces domain now owns `CompoundComponentKind`, strict tool input
   models and `WidgetDeliveryReceipt`. The catalog's existing 12 component names
   derive from that enum. Nested unknown input fields are refused rather than
   silently dropped; JSON-string props and unambiguous-root inference remain.
   Tables remain Markdown, not a widget component.
2. Cross-domain widget orchestration moved from the tools module into
   `pipelines/system_tools/compound_render_widget.py`. Explicit registration
   preserves the public slug, deterministic tool identity and widget-only
   requirement. No compatibility shim or second registration remains.
3. Validation precedes persistence. The pipeline owns a short DB-only transaction
   when none exists, or borrows the caller's session without committing/closing
   it. It no longer appends an uncommitted message to caller-owned history.
   Conversation services retain event ownership and parent/request attribution.
4. Framework terminal-artifact handling validates the receipt's status, UUID,
   root and permitted fields. The function's return annotation now admits its
   actual JSON receipt, not only its plain-text fallback.
5. A reproduced validator-cache defect returned shared mutable objects: changing
   one result changed later validation results for the original input. Entries
   and returned hits are now detached copies. Hashing rejects unsupported
   non-JSON objects and non-finite numbers instead of coercing them with `str`.

Executed function/data-flow verification:

- **182 assertions** with isolated PostgreSQL 17, existing migrations through
  `eylo0012`, and synthetic published-agent/provider/template data. Real registry,
  message service/repository, transaction/event handling, framework execution and
  interactive-response resolver were exercised. No vendor HTTP was invoked.
- All 12 component payloads survived registry → persistence → message readback.
  All four interactive families resolved back to their typed response contracts.
  Parent/request/sender IDs, compatibility metadata and terminal-artifact IDs
  match the stored message. Invalid receipts cannot declare a terminal response.
- Owned and borrowed commit, rollback, cancellation, failed commit, two concurrent
  invocations, unavailable widgets, absent agent participant, malformed payloads
  and non-conversation execution were covered. Rollback/failure leaves no row or
  event; borrowed events remain deferred until commit. Caller history stays a
  snapshot throughout these paths.
- **27 local contract assertions** cover schema/catalog parity, strict fields,
  unsupported components, receipt validation, mutable-cache isolation and
  non-JSON input refusal. **299 callback regression assertions**, **109 module
  imports**, all five local type/import hooks, full server/CLI Ruff and formatting
  pass. The existing LLM hook now covers widget schemas, validator and pipeline.
  No new diagnostic suppression was added.
- Initial fixture runs omitted provider-revision verification/config data,
  passed a slug instead of the enriched model-visible name, and assumed every
  component had a catalog example. These were probe mistakes: corrected using
  actual models/catalogs without weakening product checks. The successful full
  run includes explicit text/image/progress samples alongside catalog examples.

Sequential milestone review:

1. DDD: interfaces owns input/result schemas; conversations owns persistence;
   pipelines owns orchestration and framework translation. Framework/vendor
   imports retain their boundaries.
2. Architecture: existing registration, transaction and event authorities are
   reused. No new API, vendor, scheduler, table, migration or execution lane.
3. Data flow: actual DB and caller paths verify persistence/readback and failure
   semantics. This is not a claim of live browser delivery or provider QA.
4. Plan: this completes an F2 increment, not F2 or F0–F10. Remaining work includes
   typed canonical component props/message metadata, generated-widget durable
   run/transcript linkage, coordinated outer-runner transaction scopes, shared
   swarm dispatch, and F3–F10 vendor request/response flows. Existing dictionary
   shapes inside stored widget payloads are not declared fully hardened.
5. Maintainability/security/performance: one explicit pipeline replaces hidden
   cross-module persistence. Existing tree depth/component limits and safe-URL
   checks remain. Cache copy cost is bounded by the existing payload/cache
   limits; no benchmark claim is made. Function metadata uses the registry's
   existing validated extension, not a callable wrapper or type suppression.

No operator DB, migration history, deployment or commit changed. No probe files
were added. Live browser/vendor QA and human product review remain pending.
The disposable tmpfs QA DB/container was removed; absence was verified.
Documentation validation passed: 46 pages, 280 links, 89 packages, 1,132 Python
modules, 5,886 docstrings and 47 diagrams. `git diff --check` passed.


#### Canonical widget content — verified F2 increment

Trace: tool JSON-string props → shared discriminated component contract →
conversation message/metadata serialization → PostgreSQL → message history →
interactive parent authorization → SDK parser and generated console types.

RCA and correction:

- The former validator parsed props into a component model but discarded that
  model, retaining the original dictionary. Reproduced an image width remaining
  a string after the image schema had validated it as an integer.
- The stored-message contracts independently declared arbitrary dictionaries,
  losing component-specific types again at persistence/readback.
- `common/contracts/widgets.py` now owns provider-neutral component kinds,
  props and single/compound payloads. Each compound node is discriminated by
  its component kind. Interfaces reexports the existing public names and owns
  catalog/tool input/receipt contracts; no common-to-module import was added.
  This supersedes the previous increment's placement of the component enum.
- Existing closed widget choices are named enums with unchanged wire values.
  Component payloads retain the typed props model through validation, persistence
  and readback. The extra per-node parse-and-discard validator was removed.
- Nested serialization preserves SDK aliases such as `submitLabel`,
  `defaultValue` and `currentStep`. Canonical output includes model defaults
  and optional nulls; the actual SDK parser accepts them. Tables remain unsupported.
- The generated OpenAPI/console contract now exposes the component unions and
  per-component props instead of unstructured stored-widget dictionaries.

Executed verification:

- **222 isolated PostgreSQL assertions**: all 12 component families, real
  registration/dispatch, message service/repository, nested JSON serialization,
  post-commit events, terminal artifacts, owned/borrowed transactions, rollback,
  failed commit, cancellation and concurrent writes. The four interactive
  families also exercised persisted-parent authorization, valid submissions,
  missing/wrong parents, wrong conversations, wrong components/actions and
  invalid response values.
- **89 canonical function assertions**: single/compound round-trips, retained
  model types, numeric normalization, JSON-string/object parity, nested
  non-finite data refusal, invalid props/components/tree references, and all
  three existing tool-description variants.
- **30 actual SDK parser assertions**: serialized output for all 12 components
  plus a nested layout; single-component validation and malformed-input refusal.
  The existing SDK catalog and validation code ran without replacement.
- The previous **27 widget input/cache/receipt checks**, **299 callback
  regression checks**, **109 module imports**, all five local type/import hooks,
  full server/CLI Ruff and changed-file formatting pass. The shared widget
  contracts and response consumer were added to the local type gate; no new
  suppression was introduced.
- API types regenerated from the current app on an ephemeral loopback server
  with lifespan disabled. Console lint/typecheck/build and SDK/Preact builds
  pass. The console build reports its large-chunk warning; this slice does not
  establish bundle-size or runtime-rendering performance.

Sequential milestone review:

1. DDD: common owns neutral content, interfaces owns its catalog and tools,
   conversations owns persistence, pipelines owns orchestration/authorization.
   Vendor SDKs and framework remain outside these common contracts.
2. Architecture: one content contract serves creation and readback; aliases,
   explicit registry, tree limits and transaction/event authorities are reused.
3. Data flow: real DB and SDK parsing demonstrate matching producer/consumer
   shapes. Valid supported historic wire shapes are covered by serialization
   probes, not by an audit of operator data.
4. Plan: another F2 increment only. User-response dictionaries, compatibility
   metadata, durable generated-widget linkage, outer-runner transaction scopes
   and the remaining F3–F10 vendor flows are not declared complete.
5. Maintainability/security/performance: removed duplicate loose envelopes and
   throwaway prop parsing. Component fields are locally navigable; no extra DB
   query or vendor call was added. Historical malformed/unsupported widget rows
   previously accepted by loose message schemas now fail strict readback.
   A read-only compatibility preflight and explicit repair/fallback decision are
   required before deployment; no operator data was silently rewritten.

No live vendor, browser interaction, operator DB mutation, deployment, migration
history rewrite or commit is claimed. The exact disposable tmpfs QA container was
removed and absence verified. The temporary schema server was stopped after
generation; existing services are unchanged. Documentation validation passed:
46 pages, 280 links, 89 packages, 1,133 Python modules, 5,896 docstrings and
47 diagrams. Changed-file formatting and `git diff --check` pass.



#### Pydantic execution contexts — verified F2 design correction

User clarification: Pydantic is the platform default for internal data contracts
as well as transport boundaries. The earlier automatic “internal → dataclass”
rule was a design choice, not a required capability. The replacement table and
`AGENTS.md` now record the corrected rule; prior dataclass increments remain
subject to flow-by-flow reassessment.

Completed:

1. `AgentExecutionScope` and `AgentExecutionParticipant` are frozen Pydantic
   models with explicit fields and unknown-field refusal. UUID/field validation
   now runs at construction; frozen does not imply deep immutability of JSON.
2. `AgentExecutionContext` and generic `PlatformRunState` are mutable Pydantic
   models with assignment validation. `ConversationRunState` was converted in
   the same slice because it inherits the shared run state.
3. Real command/workflow ports remain behavioral protocols. Runtime-checkable
   protocols plus Pydantic `InstanceOf` retain their actual objects and reject
   values lacking the appropriate port. A command-only live voice context is
   not accepted as the stronger durable event-wait context.
4. Live workflow/command objects and hooks are excluded from schema/dump output.
   Hydrated conversation content and in-flight message references are excluded
   from run-state dumps; framework `RunContext.local_context` remains excluded
   entirely. Durable replay still uses its own explicit persistence contracts.
5. Concrete schema imports replace type-checking-only names where Pydantic needs
   runtime field definitions. Four fresh-process import orders and the actual
   application import verify that this did not introduce an import cycle.
   No cross-layer model registry or broad arbitrary-types exemption was added.

Executed function/data-flow evidence:

- **341 isolated PostgreSQL/context assertions**, including the previous 222
  widget persistence/authorization checks and 119 context-specific checks.
  Typed construction/readback, frozen identities, mutable assignments, invalid
  fields, generic specialization, object identity, schema/dump exclusion,
  command/durable step precedence, exact workflow wrapper execution, and
  exception/cancellation propagation passed.
- **236 handoff/voice** and **164 parallel task-dispatch** PostgreSQL assertions
  passed on separate synthetic organization data in the same disposable DB.
  Existing migrations were applied only to that isolated tmpfs database.
- **299 callback regression assertions**, **109 imports**, all five local
  type/import hooks, full server/CLI Ruff and affected-file formatting pass.
  Live-voice identity construction and shallow copies preserve the same object.
  Runtime-only context models do not appear in the current public OpenAPI schema.
- The first expanded probe failed because a local import shadowed an earlier
  `PlatformRunState` reference. The probe import was corrected; product code and
  assertions were not weakened. An exploratory `InstanceOf` around a generic
  union was rejected by Pydantic at class construction; the actual context field
  uses the correctly bounded model generic, while `InstanceOf` applies only to
  concrete runtime ports/hooks.
- Full-project Pyrefly remains **889 errors, 7 suppressed**. This is current
  incomplete-platform evidence, not a claim of a newly green project or a
  before/after count attributable to this slice. Existing scoped hooks retain
  their prior suppression; this conversion introduces none.

Sequential milestone review:

1. DDD ownership: identity/context/run state remain pipeline-owned; behavioral
   ports stay at their existing outbound execution boundary. The framework has
   no platform import.
2. Architecture: shared state and its conversation subclass use one model
   mechanism. Live-resource ports are not serializable request/response models.
3. Data flow: checked real persisted messages, dispatch, handoff, voice callers
   and runtime-instance preservation. Assignment validation does not intercept
   in-place mutations inside a list/dict; static item types still apply.
4. Plan alignment: this implements the user's Pydantic-first correction for the
   execution-context flow only. Other dataclasses, response/metadata contracts,
   durable linkage, outer-runner transactions and F3–F10 remain open.
5. Maintainability/security/performance: no ad-hoc dict or `Any` replacement,
   synthetic provider, authorization expansion, new query, or dependency upgrade.
   Type/schema validation is additional work; no performance improvement is
   claimed. Frozen identity and mutable runtime semantics remain distinct.

Target/runtime evidence: installed Pydantic **2.11.10**, checked against
[2.11 instance validation](https://docs.pydantic.dev/2.11/api/functional_validators/#pydantic.functional_validators.InstanceOf)
and [field exclusion](https://docs.pydantic.dev/2.11/concepts/serialization/#model-and-field-level-include-and-exclude).
No live vendor/browser, worker-process crash recovery, operator DB mutation,
deployment, migration-history rewrite or commit is claimed. Console/widget
sources and public endpoint schemas are unchanged; their builds were not repeated
for this runtime-only slice. The exact disposable QA container/data were removed;
absence was verified. Documentation validation passed: 46 pages, 280 links,
89 packages, 1,133 Python modules, 5,896 docstrings and 47 diagrams.


#### Widget responses and conversation prompt projection — verified F2 continuation

This continues the original F0–F10 scope, including the Pydantic-first clarification;
it does not redefine completion around the widget or a scoped type gate.

Response contracts and filing:

1. `common/contracts/widget_responses.py` owns the four interactive response
   variants, component/action enums, UUID parent identity, fixed button/card
   shapes and a 64 KiB serialized-data ceiling. Generated form/date field names
   remain dynamic. Unknown fields, non-finite numbers and non-JSON objects are
   rejected; no scalar coercion is used for fixed string selections.
2. `WsMessageEvent` normalizes flat/wrapped submissions into the same canonical
   object. `MessageWsController` passes it through conversation/parent authorization
   and atomic message/run filing. Compatibility metadata stores canonical content,
   not an additional unvalidated client copy. Invalid request parsing returns a
   safe 422; unrelated internal validation errors still use the server-error path.
3. The parent-locked pipeline retains offered-value checks, required fields,
   selection cardinality and date/pattern validation. A valid schema does not
   confer authority. Published-agent, organization, contact and user-session
   checks, budget reservation, post-commit dispatch and replay ownership remain.
4. Agent history round-trips the typed response through framework snapshots and
   back to platform content. No extra search tool, component or DB column was added.

The next consumer exposed a real data-flow defect: `_latest_user_text` treated
every user content body as a text-block list. A stored date-picker submission
produced a **zero-length recall query**, although its canonical text was 170
characters. A conversation with older text could recall against that older input
instead. The helper now narrows `UserMessageContent`/`WidgetResponseMessageContent`
and uses their canonical text methods. No unchecked `getattr` or cast remains.

`pipelines/conversation/prompt_context.py` owns frozen Pydantic projections for
agent details, independent interaction facts, recalled facts, conflict pairs and
the final runtime context. Memory levels/UUIDs remain typed until serialization;
the exact two unresolved claims and recall order are retained. Only documented
prompt fields are projected: no source scope owners, provenance, arbitrary vendor
metadata or credentials. Customer context remains finite JSON. The authored
instructions, untrusted-context delimiter, HTML escaping, ISO UTC offset and
optional-memory failure/cancellation behavior remain unchanged.

Verification executed against current source on 2026-09-08:

- **291 response function checks:** flat/wrapped inputs, required tags, invalid
  component/action pairs, all form field kinds/date modes, finite JSON, byte
  boundaries, canonical serialization and malformed-input rejection before DB IO.
- **595 PostgreSQL checks**, rerun on the isolated `response_typeqa` database:
  published-agent/widget production, response authorization, atomic message/run
  filing, commit failure, cancellation, post-commit dispatch, replay/concurrent
  deduplication and canonical readback/history. Expected error paths were injected;
  durable worker publication was observed through a controlled port, not a worker.
- **70 SDK checks:** actual `MessageService` submission/decoding of ten canonical
  DB payloads. The resulting native SDK frames then passed the real controller,
  ORM persistence, context hydration and `RunInput` projection in **111 checks**.
  Memory recall used a controlled port returning actual `MemoryRecall` instances;
  its query now matches the latest structured submission. No browser/network or
  live embedding/reranking/LLM operation is inferred from this probe.
- **154 prompt function checks:** three memory levels, empty/fact-only/conflict-only
  recalls, conflict-pair preservation, explicit field projection, all interaction
  fact combinations, timestamp/JSON/unknown-field refusal, escaping, current-message
  selection, missing capability, optional failure and cancellation propagation.
- All **five local typed/import hooks** pass. `context.py` and `prompt_context.py`
  are included in the existing LLM/caller gate. Full server/CLI Ruff passes.
  Full Pyrefly is **882 errors, 7 suppressed**, down from 883 before the prompt
  change (889 before the response change). No suppression was added.
- Console lint, TypeScript and production build pass; SDK and Preact builds pass.
  The console retains its existing >500 kB chunk warnings. Documentation validation
  passes: 46 pages, 280 links, 89 packages, 1,135 Python modules, 5,904 docstrings
  and 47 diagrams. `git diff --check` passes.

One milestone review covered DDD ownership, architecture fit, source-to-sink
semantics, plan alignment, readability, security and performance. The verified
recall defect was fixed at the content boundary. New projections issue no DB
queries or provider calls and preserve the existing recall limit. No performance
improvement is claimed; validation and projection allocate typed objects.

Compatibility/release limits:

- Actions are now required; malformed historical response rows (missing actions,
  display-only components, extra fields or invalid JSON values) need a read-only
  compatibility preflight before deployment. No operator data repair is authorized
  or claimed. Valid current SDK flat/wrapped payloads retain their wire shape.
- Prompt projections reject non-JSON context and non-boolean interaction facts.
  Full persisted `MessageMeta`, request-context sanitization and voice-origin
  metadata typing remain follow-up boundaries, not complete merely because the
  final prompt model is typed. Memory's existing query limits still apply; this
  change does not truncate oversized inputs or claim all large forms can be recalled.
- Human review of the updated recall behavior, live browser/provider QA and
  worker-process crash recovery remain unrun. No deployment, operator DB change,
  schema/history rewrite, dependency upgrade or commit occurred.

The exact disposable QA container and its synthetic tmpfs database were removed;
container absence was verified. The temporary loopback-only OpenAPI server was
stopped and its listener absence verified. No operator service was stopped.

#### Persisted interaction metadata and transcript facts — verified F2 continuation

The original F0–F10 objective remains open. This slice follows session facts and
client context through request parsing, message filing/readback, runtime selection,
LLM history enrichment and voice-segment projection.

Implemented contracts:

- `MessageInteraction` is a frozen Pydantic model. `SessionChannel` is owned by
  the neutral session contract and re-exported by session schemas. The WebSocket
  controller stamps channel/voice facts from server context, not customer JSON.
- `MessageMeta` validates interaction/audio facts, finite JSON context/extensions,
  nonnegative integer `duration_ms`, and the existing `VoiceSpeechOutcome` enum.
  Absent fields remain absent during serialization; explicit null remains null.
  Compatibility dictionary access emits JSON while typed consumers use attributes.
- Conversation/message request schemas require finite JSON object context. The
  sanitizer retains existing valid-JSON output, depth and size policies, removes
  implicit Python-object stringification and stops logging customer keys/paths.
  HTML stripping is not a prompt-injection defense; context remains untrusted.
- Required message enums reject null and unknown values before the permissive
  shared enum base can invent a member. Optional status/feedback still accept null.
- Transcript projection reads typed duration/outcome fields and matches terminal
  `RequestStatus` members without string conversion. Missing explicit outcomes
  retain the existing status fallback. The session-start fact writer uses the
  validated creation authority rather than an optional field on the generic DTO.

Confirmed failures and causes:

1. Untyped `interaction.is_voice="false"` and `is_audio="false"` selected voice;
   an interaction list reached an attribute error. Validation now precedes selection.
2. `MessageCreate(kind=None)` produced a synthetic `MessageKind.None`. The required
   validator no longer bypasses enum-membership validation for null.
3. Transcript `int(raw_duration)` crashed on a list/dict and converted `True` or
   `1.9` to `1 ms`. The metadata boundary now refuses those values. A local enum-key
   lookup attempted during this fix failed because `CaseInSensitiveEnum` is
   unhashable; explicit matching fixes the consumer without changing that base.

Executed evidence on 2026-09-08:

- **763 metadata/context function checks:** exact valid sanitizer parity,
  absent/null fields, JSON serialization, channel/voice combinations, invalid
  values, required/optional enums, history enrichment and invalid WS input refusal
  before a transaction or durable publication.
- **211 duration/outcome checks:** integer boundaries, malformed values, assignment
  refusal, every request status × explicit speech outcome, incomplete assistant
  refusal and existing source classification. **120 voice-producer checks** verify
  live and post-call message shapes across three runtime modes and all outcomes.
- **453 isolated PostgreSQL checks:** 42 channel/metadata combinations through
  actual messages and published-agent context construction, malformed historical
  JSON refusal, 24 voice-message/segment projections, idempotent projection and
  exact persisted duration/outcome readback. **5 additional checks** exercise the
  real user-session fact writer and its organization/subject authority.
- **595 existing PostgreSQL widget regressions** pass: atomic message/run filing,
  authorization, budget refusal, commit failure, cancellation, post-commit dispatch,
  replay and concurrent deduplication. All DB data is synthetic in an isolated
  tmpfs container. Memory/provider calls and durable publication use controlled
  ports where specified; these checks do not prove live vendors or worker recovery.
- The five local typed/import hooks pass; the voice hook now checks the transcript
  service and triggers for transcript changes. Full Pyrefly reports **873 errors,
  7 suppressed**. No suppression was added. The whole platform is not type-clean.

One sequential milestone review covered DDD ownership, architecture fit,
source-to-sink semantics, plan alignment, readability, security and performance.
No new DB query, vendor call, transport policy or dependency was introduced.
Validation allocates typed objects; no throughput improvement is claimed.

Compatibility and remaining work:

- Malformed historical metadata (including numeric-string/fractional/boolean
  durations) requires read-only preflight and an explicit repair decision before
  deployment. No operator data was read or rewritten, and no deployment is claimed.
- Generic extension JSON is not a substitute for producer-owned schemas. Voice
  identity/provenance, framework/parallel metadata and tool payloads remain open.
  Pydantic assignment validation does not intercept in-place dictionary/list edits.
- `SessionContext.enrich(**kwargs)` bypassed validation through `model_copy`;
  the following continuation resolves that upstream composition boundary.
  The remaining provider data flows, live QA and F3–F10 stay in scope.

#### Session hydration and generated metadata schemas — verified F2 continuation

The full platform objective remains active. This continuation also closes two
metadata verification findings left by the preceding slice.

Confirmed causes and changes:

1. `SessionContext.enrich` accepted invalid channel/UUID values and a negative
   authorized Agent revision. Its untyped keyword dictionary went directly to
   `model_copy`, bypassing validators. The sole caller, `for_webrtc`, now constructs
   every field explicitly and validates it; the unrestricted helper is removed.
   Inherited scope and restriction values are preserved, not recomputed from a peer.
2. Direct session-field assignment also bypassed validation. `SessionContext` now
   forbids unknown fields and validates assignments. It stays mutable because the
   browser runtime assigns its durable voice session ID after creation.
3. Runtime ports use `InstanceOf` instead of a model-wide arbitrary-type allowance.
   Auth/WebSocket/call/peer references are excluded from dump/repr/schema output,
   without serializing or copying their live resources. Protocol checks establish
   interface presence, not deep validation of mutable implementation fields.
4. The metadata wrap serializer's dictionary return annotation erased named fields
   from output JSON Schema. The Pydantic JSON-schema hook copies the model schema
   without the serializer override and retains finite-JSON extension semantics.
   Runtime serialization still preserves absence versus explicit null.
5. An after-validator refused a non-JSON metadata extension assignment only after
   it had mutated the object. Validation now precedes assignment; rejection leaves
   the old value intact. This does not intercept in-place list/dict mutation.

No auth policy, DB schema, routing channel, query, vendor call, worker lifecycle,
or dependency version changed. Pydantic remains pinned at 2.11.10. The schema hook
uses its documented extension point, not a generated-client patch:
[Pydantic JSON Schema customization](https://docs.pydantic.dev/2.11/concepts/json_schema/#implementing-__get_pydantic_json_schema__).

Executed function and integration evidence:

- **176 session-hydration checks** use actual `AuthSessionInDb`, `WSSessionState`,
  `CallSession` and `WebRTCSession` classes: construction, HTTP dependency injection,
  identity retention, channel/voice predicates, restriction preservation, explicit
  voice-ID precedence, malformed assignment/construction refusal, dump/schema
  exclusions, and rejected enrichment of an already-corrupt scalar context.
- **58 metadata schema/assignment checks** cover validation/output schemas, nested
  message and application OpenAPI projections, omission semantics and rejection
  without partial extension mutation. Generated console types now name interaction,
  audio, duration, speech outcome and context fields while retaining extensions.
- Re-ran **763 metadata/context**, **211 duration/outcome**, and **120 producer**
  function checks after the schema/assignment changes.
- Re-ran **453 PostgreSQL metadata/transcript checks** and the **595 existing
  widget filing regressions** against the exact isolated synthetic database.
  A further **597 checks** replace the test's direct context construction with
  the real WebSocket hydrator, auth DTO and live WebSocket state, then execute
  the same message/run filing and refusal paths.
  Controlled provider, memory and publication ports remain as previously described;
  this is not live vendor, browser audio or worker-crash verification.
- All five scoped Python type/import hooks pass. The session service and HTTP
  dependency join the existing LLM/runtime gate. Full-project Pyrefly remains
  **873 errors, 7 suppressed**; none were hidden to pass this slice. The schema and
  hydration defects reproduced even when their scoped static gate was green.
- Console API types were regenerated from a temporary loopback-only server with
  dummy settings and lifespan startup disabled. Console lint, TypeScript and Vite
  build pass; the existing large-chunk warning remains.
- SDK and Preact builds pass. Full Python lint, changed-source formatting,
  documentation validation (46 pages, 280 links, 47 diagrams), and diff whitespace
  checks pass. No test/probe files were added to the repository.

Milestone review, in repository order:

1. **DDD boundaries:** session composition owns validation; neutral ports retain
   live resources without importing pipeline implementations into modules.
2. **Architecture fit:** existing factories and Pydantic contracts remain the
   authorities. No replacement session lifecycle or generic update engine is added.
3. **Data flow:** authenticated context → explicit hydration → message facts → DB
   readback → runtime/transcript/API projection. Identity, null/absence semantics
   and restrictions survive the changed boundaries. Serializing runtime ports is
   intentionally unsupported; these models are not public DTOs.
4. **Plan alignment:** completes the identified F2 hydration/schema increment,
   not F2 or F0–F10. Corrected stale comments claiming telephony/WebRTC helpers had
   production callers; only HTTP and WebSocket hydrators are currently wired.
5. **Maintainability/security/performance:** no unrestricted application update
   helper, extra DB reads, frame-loop validation or resource cloning. Auth and live
   resource references are not exported. Validation does not establish authorization,
   and context scalar fields still must not be published as a public response.

Remaining work follows the same full data-flow plan: producer-owned metadata and
tool payloads, background identity/memory/swarm caller gaps, then F3–F10's native
provider operations and session implementations. Historical-data preflight and live
QA remain release requirements, not claims established by synthetic fixtures.
The exact synthetic tmpfs DB container was removed and its absence verified.
The temporary schema process exited and its listener is absent. No operator DB,
provider config, service, migration, deployment or Git history was changed.

#### Voice-message provenance and durable fact readback — verified F2 continuation

This continues the full F0–F10 goal. It does not complete F2 or the separate
voice-buffer/native-provider work in F7.

Evidence and RCA:

- Before this change, a `MessageInDb` with `voice_session_row_id="not-a-uuid"`,
  an unknown runtime mode and a boolean source sequence passed construction and
  qualified for a voice fact. Known platform fields were treated as arbitrary
  JSON; the consumer deferred UUID parsing until after filing. This was a
  synthetic reproduction, not a claim about a production call.
- `MessageMeta` now owns optional transport-local session text, durable session
  UUID, `VoiceRuntimeMode`, positive integer sequence/redaction revision, strict
  transient flag and source text. Missing fields and explicit nulls remain
  distinct. Transport-local session IDs are deliberately not UUID-constrained.
- `VoiceRuntimeMode` now lives in the neutral voice contract and is re-exported
  as the same class from the transcript module. Existing DB/wire values remain
  unchanged; there is no competing runtime-mode enum.
- Live/post-call producers construct typed metadata directly. The fact filer
  accepts `MessageInDb`; request-status transitions validate ORM readback before
  filing. The consumer uses typed session identity and retains its exact
  organization/conversation/session lookup and row lock.
- Consumer validation failures have safe fixed messages. The durable workflow
  already stores generic failure codes; this does not claim a demonstrated
  sensitive-data leak in its persisted delivery errors.
- Python-mode UUID output exposed a real mismatch in the metadata serializer's
  JSON-only return annotation. Its return type now includes UUID; JSON output
  still contains strings. A warning-as-error regression verifies both modes.
- The initial new QA probe incorrectly expected individual canonical-message
  creation to deduplicate. That API makes no such promise. The corrected probe
  tests fact/consumer idempotency and whole-call replay at their actual owners;
  no production behavior was changed to satisfy the mistaken expectation.

Executed evidence on the current checkout:

- 1,009 provenance validation, assignment, final-class selection, timestamp and
  schema checks; 120 existing live/post-call producer checks; two missing-session
  producer guards; UUID Python/JSON serialization with warnings treated as errors.
- Existing metadata regressions: 763 input/output checks, 211 duration/outcome
  checks (including the 45 duration cases), and 58 generated-schema checks.
- A new, isolated PostgreSQL 17/pgvector tmpfs database upgraded through
  `eylo0012`. No operator database or real provider was used.
- 595 existing real-model DB regressions; 221 new fact/receipt/segment checks
  covering all three runtime modes, terminal status changes, replay, safe malformed
  readback, foreign organization, wrong conversation, absent session and rollback.
- 104 full live-buffer → post-call projection checks cover browser-decomposed,
  browser-realtime and telephony modes, storage/no-storage, ephemeral live deltas,
  canonical message/segment counts and whole-call replay. Delivery was captured at
  the existing async broadcast seam; these are not human/browser voice-call tests.
- Console types regenerated from a temporary current-code API with lifespan off.
  Console lint/TypeScript/Vite and SDK/Preact builds passed. Vite retains its existing
  large-chunk warning. Python lint and documentation verification passed.
- All five configured type/import hooks passed. The voice hook now covers the
  changed producers, fact filer, status service and consumer. Whole-platform
  Pyrefly reports **870 errors, seven suppressed**, down from 873; no suppression
  was added. A green scoped gate is not whole-platform completion.
- `alembic check` found no new operations. Existing mutually dependent FK and
  unrecognized vector introspection warnings limit that comparison; no migration
  file was modified or generated.

Milestone review, in order:

1. **DDD boundaries:** neutral contracts own shared vocabulary; domain services
   own filing/status rules; pipelines retain cross-domain session authorization.
2. **Architecture fit:** existing outbox, message API and projection state machine
   remain the authorities. No second replay mechanism or lifecycle was introduced.
3. **Data flow:** typed producer → existing JSON layout → ORM readback → immutable
   fact → exact session lookup → segment. Raw live presentation remains ephemeral;
   durable filing uses canonical post-call content. Types do not prove ownership.
4. **Plan alignment:** advances producer metadata in F2 without excluding the
   remaining vendor/provider flows or the Pydantic-first correction.
5. **Maintainability/security/performance:** removed duck-typed metadata parsing
   and magic-key access in this flow; no extra queries, vendor calls, resource
   cloning or transaction expansion. Invalid history is refused, not repaired
   silently. Nested container mutation remains outside assignment validation.

Remaining: raw live-buffer/snapshot payloads and dataclasses, post-call result and
error contracts, other producer metadata, tool-content unions, and all outstanding
F0–F10 flows. The legacy `MessageStore` context helper has no discovered production
callers and was not represented as a verified runtime path. Historical operator
data preflight, live vendor QA and human voice interaction remain unexecuted here.
The exact disposable QA container was stopped and removed; its absence was
verified. The temporary API process exited and its loopback listener is absent.
Only synthetic QA data was discarded. No operator data, configured providers,
running development services, migration files or Git history were changed.

#### Live capture and canonical projection — verified F2 continuation

The active worktree already contained the live-buffer Pydantic conversion. This
continuation completed its post-call consumer and verification rather than
assuming that changing the producer alone completed the flow.

Reproduced defect: a valid `VoiceSpeechOutcome.DRAINED` reached `_speech_outcome`,
which called `str(enum)` and attempted to parse the qualified enum name as its
wire value. A valid assistant item therefore failed canonical projection. The
earlier dataclass consumer had relied on string input; the producer conversion
exposed that assumption. The fix preserves the enum through the consumer.

Implemented and verified:

1. Live capture identity, draft, item and snapshot contracts validate UUIDs,
   outcomes, aware timestamps, counts, JSON payloads and completeness. Captured
   payloads are detached from caller-owned containers; append results and
   snapshots cannot mutate the buffer. Raw fields are excluded from generic
   dumps and repr output, including explicit dump includes.
2. Decomposed and realtime producers mark malformed capture incomplete without
   converting secondary capture validation into call teardown. Realtime policy
   speech retains its existing system-only transcript semantics. The shared
   draft formatter no longer fabricates an item with sequence zero.
3. `_CanonicalItem`, `_ParticipantAuthority` and `VoiceProjectionResult` use
   Pydantic. Redacted payloads retain validated JSON types and terminal speech
   outcomes. `_message_content` returns the existing canonical content union;
   participant resolution has an explicit `AsyncSession` contract.
4. `VoiceCanonicalFailureCode` belongs to the voice-transcript module. All 17
   existing code spellings are preserved through build errors, terminal writes,
   internal readback and API schemas. Persistence remains the existing string
   column; no migration is required. Unknown saved codes now fail validation.
5. The console contract was regenerated from a temporary running API; the
   existing camel-case `canonicalFailureCode` property references the enum.
   The local voice type hook now includes the capture, projection and schema
   files. No new type suppression was added.

Executed evidence:

- 192 buffer/projection function checks: all runtime/outcome combinations,
  malformed/non-finite values, container isolation, capacities, concurrent
  append ordering, latest-request speech updates, seal/discard and typed failures.
- 120 existing live/post-call producer checks; 24 actual `RealtimeManager`
  capture checks with delivery substituted. Invalid argument/metadata capture
  leaves the manager open with no teardown tasks. No provider connection opened.
- Disposable PostgreSQL: existing 595 conversation/widget checks, 221 voice-fact
  checks and 104 projection/replay checks passed. A further 397 sink checks cover
  12 runtime/outcome combinations, redaction of speech/tool input, system-only
  policy segments, eight failure paths per runtime, rollback without partial
  messages/segments, API projection and exact owner refusals.
- Existing migrations applied through `eylo0012` to the disposable DB.
  `alembic check` detected no new operations. Existing FK-cycle and pgvector
  reflection warnings limit that introspection; no model/DDL change was made.
- All five local typed/import hooks, full Python lint, documentation checks,
  console lint/type/build, SDK build and Preact build passed. The console retains
  its large-chunk build warning. Full-project Pyrefly remains **870 errors,
  seven suppressed**, unchanged from this continuation's baseline.

Probe corrections: the first hook invocation used the server cwd while its
harness expects the repository root; it was rerun from the correct cwd. The
first OpenAPI assertion assumed snake-case; inspecting the schema's declared
serialization alias confirmed camel-case and the corrected assertion passed.
Neither failure required a production-code workaround.

Milestone review, in order:

1. DDD ownership: capture remains pipeline-local; persisted canonical failure
   vocabulary belongs to the transcript domain; shared speech enums stay neutral.
2. Architecture fit: existing buffers, post-call transaction and durable-fact
   authority remain; no raw payload is added to checkpoints or event storage.
3. Data flow: terminal enum → capture → redaction → message/segment → API/replay
   is exercised with real models and PostgreSQL. Failed projection rolls back
   before recording its content-free failure state.
4. Plan alignment: this finishes the live-capture/projection increment, not F2
   or the platform-wide goal. Known framework/tool payloads and F3–F10 remain.
5. Maintainability/security/performance: duplicated dataclass fields and string
   error dispatch are removed. Validation runs per captured item/turn, not audio
   frame. Existing item/byte limits remain; no vendor I/O or query was added.

Limits: no live provider, human voice interaction, operator-history preflight,
worker-crash test or full realtime event-dispatch proof. Two baseline diagnostics
remain in realtime handler/callback dispatch and are not suppressed. Framework
tool-item parsing still contains guessed IDs/default dictionaries and must be
replaced at its producer/consumer boundary; the buffer cannot establish that
upstream contract. Session metadata, realtime resources and remaining provider
flows are still open. No deployment, operator DB change, migration rewrite,
commit or history reset was performed.

Cleanup: `eylo-typeqa-voice-capture-20260908-b74d` was stopped and removed;
its absence was verified. Its data lived only in tmpfs. The temporary API exited
and port 53988 no longer has a listener. No probe files were added to the repo.

#### Tool observations and durable replay — verified F2 continuation

This continues the full F0–F10 goal, not a replacement completion target.

Trace: normalized model blocks → `ToolCall` → `FrameworkRunner` → tool executor
→ `ToolResult` → typed `RunItem` → voice capture/history. The parallel durable
path is callback → `AgentRunTranscriptBridge` → transcript rows → replayed
framework messages/pending calls. Both paths reuse the framework's own tool
contracts; neither imports vendor models into the framework.

Reproduced defects before editing:

- An empty tool-call item became `tool_call_id="unknown"`,
  `tool_name="unknown"`, and empty arguments in live voice history.
- `SYSTEM_SPEECH` fell through to tool-result construction. The next model could
  receive a policy check as an orphan tool result with an invented ID.
- The framework accepted a result whose `tool_call_id` differed from its call.
  The durable writer similarly correlated by the call while storing the result's
  different ID. Typed outer objects alone did not protect that relationship.

Changes:

- `framework/agents/items.py`: discriminated call/result/non-tool variants reuse
  `ToolCall` and `ToolResult`. The emitted JSON fields remain unchanged; private
  tool metadata is removed before the serializer sees it. Tool payloads are
  excluded from repr, and copied/decoded items are revalidated.
- `framework/agents/tool.py`: nonblank string identities, finite JSON arguments
  and results, and strict error predicates. Dynamic JSON fields remain supported.
- `framework/agents/runner.py`: validates executor output before completion
  callbacks. Malformed/foreign results take the existing execution-failure path
  with a paired error for the real call, not an orphan or false completion.
  `ToolExecutionOutcome` is now a frozen Pydantic model.
- `pipelines/voice/live_runner.py`: consumes typed payloads, refuses orphan
  results, and omits platform speech from model history while retaining it in
  raw capture. Capture validation failures keep the existing secondary-failure
  handling and do not close the call.
- `pipelines/agent_run_transcript.py`: Pydantic call capture/replay models;
  mismatch refusal; a same-run/org persisted call is required before recording
  completion; kind/payload/correlation are checked on readback.
- The sandbox argv reader accepts a read-only mapping, preserving its existing
  input validation while accepting the newly precise argument value type.

Verification on the current checkout:

- **195 function checks** cover malformed identities/JSON/predicates, item union tags,
  serialization include/exclude behavior, private metadata containing runtime
  objects, copied-instance revalidation, normal multi-tool runs, disabled and
  approval-gated tools, failed output pairing, voice policy exclusion, typed
  capture assignment, and durable row correlation validation.
- **56 PostgreSQL checks:** an isolated container was migrated from empty through `eylo0012`.
  Real framework callbacks/ORM/services filed and read back transcript rows.
  Checks covered execution with persisted command IDs, JSON round-trip,
  capture/history projection, eight concurrent duplicate response writers,
  eight duplicate result writers, pending-call recovery across sessions, result
  mismatch/orphan refusal, payload ceilings, rollback of corrupted readback,
  orphaned stored-result refusal in both read paths, malformed-output pending
  recovery, and cross-org read/write isolation. Synthetic model/tool outputs only; no
  vendor calls or operator configuration changes.
- **120 existing voice-message producer checks** passed. All five local typed/import
  hooks passed; the LLM hook retains one pre-existing suppression. The whole
  project remains at 870 diagnostics with seven suppressions, matching the prior
  baseline. These are not 870 confirmed runtime bugs.
- App import and OpenAPI generation passed. Changed private framework/transcript
  models are not public API components; no generated-client or migration change
  is needed for this increment.

Milestone review, in repository-required order:

1. DDD boundaries: framework owns tool contracts/item tags; AgentRun owns persisted
   row kinds; the pipeline validates/translates the relationship. No new framework
   dependency on platform or vendor modules.
2. Architecture fit: existing callbacks, transcript authority, capture buffer,
   and replay path remain in use. No second persistence/execution lane.
3. Data flow: construction, execution failure, capture, serialization, persistence,
   idempotent concurrent retries, and readback exercised with actual types.
4. Plan alignment: advances F2 without excluding non-tool signals or F3–F10.
   New runtime-value models use Pydantic under the user's explicit preference.
5. Clean code/security/performance: no string-key parsing of tool run items;
   no invented IDs; no private metadata serialization/repr; no per-row replay
   query. The added completion lookup is DB-only. Inherited caller-owned
   transaction lifetimes are separate debt, not remediated by this increment.

Cleanup: `eylo-typeqa-tool-replay-20260908-c91f` and its tmpfs-only synthetic DB
were stopped/removed; absence was verified. Existing Eylo services remained
running with their prior uptime. No probe files were written into the repository.

Limits: not live-provider, human voice/widget, worker-crash, or historical
operator-transcript QA. Generic non-tool observations, framework extension
metadata, remaining model-block payloads, and the remaining provider flows are
not complete. No hosted CI or permanent test suite was added.

#### Model blocks and provider-bound history — verified F2 continuation

The full F0–F10 scope remains unchanged. This increment traces canonical LLM
responses → framework blocks → tool execution → conversation/durable persistence
→ readback and next-turn history → the eight existing LLM adapter formats.

Reproduced findings:

- `ModelOutputBlock.content: str | dict` erased the discriminated canonical
  contract. Malformed text was dropped by the framework but stringified by
  persistence. Duplicate tool IDs could alias command/result maps.
- Framework history snapshots used Python-mode `model_dump()`. Their block
  tuples failed the stricter JSON-only `MessageMeta` contract when the next model
  call rebuilt transient messages. Keeping the final DTO strict exposed a
  producer serialization error; weakening the DTO would hide it.
- Persisted text following a tool block was filed before tool execution. The
  common history state machine treated that text as an abandoned tool sequence,
  removing the call and then rejecting its actual result. Transient history
  already paired calls/results, so checking that path alone missed this defect.

Implementation:

- `framework/agents/model.py`: frozen, revalidated text/reasoning/tool variants;
  exact `ToolCall` payloads; unique command identities per response; private
  annotations excluded from tool-block snapshots and repr.
- `framework/agents/runner.py`: validate model returns before callbacks/effects;
  consume typed block payloads; JSON-mode snapshots for next-turn history.
- Conversation persistence, terminal replay, durable pending-call replay, and
  background result extraction consume those concrete contracts directly.
  The old permissive text coercion and repeated tool dictionary parsing are gone.
- `sockets/llm/history.py`: socket-owned, typed subset projection of the existing
  response identity. Same-response text is deferred until pending results in
  provider history only, scoped to conversation/request/speaker. It never changes
  stored messages or weakens orphan/incomplete/duplicate handling. The existing
  state machine remains the final sequence validator.
- `ToolCallCompleteness` now uses Pydantic with immutable sets and strict,
  nonnegative counts. The local LLM typing hook includes the new history module.

Verification:

- 117 model-block function checks: discriminators, malformed input, duplicate
  IDs, copied-instance validation, JSON round-trip, private metadata, callback
  refusal, tool/text ordering, reasoning exclusion, terminal replay and background
  extraction. The existing 195 tool-observation checks also passed.
- 105 history/count function checks: sequential/parallel and batched results,
  response/request/conversation/speaker isolation, missing or malformed identity,
  interruption boundaries, no mutation, repeatability, incomplete/orphan refusal,
  and Pydantic count validation.
- 165 checks against an empty disposable PostgreSQL DB migrated through
  `eylo0012`: real message services/callbacks, ordered writes and command IDs,
  conversation/API DTO readback, next-turn reconstruction, durable replay,
  concurrent idempotency and tenant isolation. Both transient and persisted
  histories passed all eight local adapters: Anthropic, Bedrock, OpenAI Chat,
  OpenAI Responses, Gemini, Groq, Cerebras, and Sarvam. Vendor network clients
  were forbidden in these formatter checks; these are not live API claims.
- A probe initially confused raw SQLAlchemy Text/JSONB values with parsed
  `MessageInDb` fields. Correcting the probe to use the real DTO exposed the two
  actual history defects above. No production schema was altered to fit a probe.
- All five local typed/import hooks, Ruff, documentation verification and
  `git diff --check` passed. App import/OpenAPI generation passed; the changed
  private models are absent from public components, so no API-client or DB
  migration change was needed. No frontend files changed in this increment.

Cleanup: `eylo-typeqa-model-blocks-20260908-d42a` was verified to have no persistent
mounts or host ports, then stopped and removed. Its tmpfs-only synthetic DB was
discarded; absence was verified. Existing Eylo services retained their prior
uptime. No operator data, credentials, migrations, Git history or deployment was
changed; no permanent probes/test suite were added.

Review in required order:

1. DDD: framework owns block/call types; pipelines translate canonical output;
   the socket owns its history projection. No framework imports from `eylo.*`,
   no module/socket cross-imports, and no vendor SDK types in framework contracts.
2. Architecture: existing callbacks, persistence authority and history validator
   remain in place. No duplicate execution or new durable work lane.
3. Data flow: valid content reaches the same stored wire fields and all eight
   history formats; malformed model returns do not execute tools or file messages.
4. Plan: continues F2 and honors the Pydantic preference. It does not remove
   non-tool signal schemas, callback/runtime dataclass revisits, or F3–F10.
5. Clean code/security/performance: no content key guessing; typed identity
   projections explicitly ignore unrelated snapshot fields. History ordering is
   linear in rows/result entries and performs no DB/network work. Private call
   annotations are omitted before serialization. No new policy defaults.

Limits: no live-vendor, human widget/voice, worker-crash or historical operator-data
QA. The whole-platform baseline remains 870 diagnostics with seven suppressions;
these are not 870 confirmed runtime defects. Model settings/usage, generic signal
payloads, remaining metadata producers, runtime dataclasses and the remaining
vendor/provider flows still need their own source-to-sink increments.

#### Active run signals and pause continuations — verified F2 continuation

Trace: model text / stored tool policy / objective input / sandbox approval →
framework items and result → conversation, objective and scheduled pause
projections → product request and message JSON → readback, answer and resume.
The framework has active producers for message, input-request and approval-request
items only. No payload fields were invented for reserved handoff, progress, token,
artifact or error observations without producers.

Implemented:

1. `RunMessageItem`, `RunInputRequestItem` and `RunApprovalRequestItem` replace the
   generic dictionary branch for active observations. Message content is strict
   text; request kinds cannot be interchanged through the generic fallback.
2. `InputRequestDetails` shares question/schema fields with the existing durable
   `InputRequest` without inventing a persisted ID at tool execution time.
   `ApprovalRequest` remains the canonical approval contract. Its redacted payload
   and metadata, plus input response schemas, accept finite JSON only.
3. Framework-owned `ToolContinuationKind` and typed continuations preserve the
   existing `tool_input` / `tool_approval` wire tags and exact nonblank call ID.
   `RunInputInterruption` / `RunApprovalInterruption` retain these objects through
   runner outcomes. Pause status and request kind are validated together.
4. `RunResult` validates pause metadata on construction and JSON readback. Missing,
   mismatched and unknown fields fail closed. Existing metadata objects are
   inspected as field maps rather than via attribute parsing that could silently
   discard unknown fields. No live workflow port belongs in a pause snapshot.
5. Objective and sandbox producers retain typed request objects. Conversation,
   objective and scheduled pipelines consume named fields and serialize at the
   product persistence boundary. Terminal message metadata explicitly uses JSON
   serialization, including nested request and continuation values. Existing
   prompt fallback text and exact captured-call checks are preserved.
6. `RunCallbacks` is a frozen Pydantic model; callback identities remain unchanged
   and are excluded from repr, dumps and JSON Schema. Callback errors still fail
   the run; cancellation still propagates. Runtime callable validation does not
   prove callable signatures; static gates and actual invocation checks do.
7. `SandboxProvider` protocol methods now have explicit stub bodies. This resolves
   six existing missing-return type diagnostics without altering vendor execution.
   The local LLM/framework hook now covers approval, durable, interruption and
   sandbox-runtime contracts as well.

Executed verification:

- **166** new signal/callback function assertions: all active branches, strict
  values, JSON round-trips, unknown fields, kind/status mismatch, copied-instance
  validation, callback identity/exclusion, four callback phases, failure and
  cancellation. Objective and scheduled projections reject foreign call captures.
- **195** prior tool-item, **117** model-block and **105** history assertions pass.
  Signal fixtures now construct concrete typed variants; their original voice
  output assertions remain intact.
- **324** disposable PostgreSQL assertions: prior **165** ORM/replay/all-eight-LLM
  history-format checks plus **159** assertions over nine pause cases. Input,
  stored-policy approval and sandbox approval each pass all three product pause
  projections, real request filing, message/API serialization, tenant refusal,
  answer and resume. Reservations use the real budget service; external wake-event
  publication is replaced by a recorder. This is not an actual worker restart.
- Probe-only defects were corrected: missing response ID, obsolete signal
  constructors, missing imports and missing budget reservation setup. Runtime
  validation was not loosened to accommodate incomplete fixtures.
- All five local typed/import hooks pass. Whole-project Pyrefly reports **862**
  diagnostics / seven suppressions across **1,229** modules, down from 870; this
  remains an incomplete global typing baseline, not a runtime defect count.
- Application import/OpenAPI generation passes with **564** components; private
  signal and callback models are not public API components. No migration or
  generated console-schema update is required by this increment.

Milestone review, in repository order:

1. DDD boundaries: framework contracts import no platform modules or sockets;
   product request ownership and budget authority remain outside the framework.
2. Architecture fit: observations and continuation state are data models;
   callback and provider behavior remains callable/protocol-owned, not serialized.
3. Data flow: producers, JSON sinks, readback and resume were exercised with real
   ORM/Pydantic objects; unknown metadata refusal was tightened during review.
4. Plan adherence: this closes active signal dictionaries and one callback
   dataclass flow only. It does not complete F2, F3–F10 or platform type hardening.
5. Readability/security/performance: no guessed payload schemas, new defaults,
   network operations, schema resets or per-item DB queries were introduced.
   Pause validation is bounded by existing request/persistence limits, not applied
   to every audio packet. Live callback objects remain outside generic snapshots.

Limits and next work: no live vendor, human widget/voice, worker-crash or operator
historical-data QA. The next increment below covers product `AgentRunWaitState`,
answer/approval and resume continuations. Remaining framework metadata, model
settings/usage and F3–F10 provider flows remain pending. Reserved observation
envelopes remain finite JSON until their actual producers define the contract.
The full original goal stays open.

#### Human answers and product continuations — verified F2 continuation

Trace: framework pause → product request JSON → answer command → DB readback →
capacity reacquisition → conversation/objective/scheduled resume → tool result
and transcript replay. The implementation retains existing wire tags and fields;
it does not change request ownership, approval policy or indefinite-wait behavior.

Implemented:

- `AgentApprovalDecision` belongs to the AgentRun domain, separate from framework
  approval vocabulary. `AgentApprovalResponse` validates its closed decision and
  optional text comment; internal consumers no longer parse dictionary keys.
- The wait dataclass is replaced by a discriminated Pydantic `AgentRunWaitState`
  union. Input answers remain dynamic JSON; approvals retain their response model.
  Pending and answered states are checked, including answered JSON null.
- Service readback validates snapshots and returns `AgentRunConflict` for invalid
  data. Resume validates before changing lifecycle or reacquiring capacity. All
  three resume consumers refuse pending snapshots before effects.
- Pipeline-owned `RunContinuation`, `ObjectiveRunContinuation` and
  `ScheduledRunContinuation` replace the three ad-hoc continuation readers.
  Request kind, framework pause kind and captured tool IDs must agree; unknown
  fields, missing state and mixed product snapshots are rejected. The module owns
  JSON persistence without importing framework contracts.
- Negative checks exposed a Pydantic 2.11.10 schema-reuse difference: direct model
  validation rejected non-finite JSON numbers while the wait union parser accepted
  them. An explicit finite-JSON validator now covers both continuation and answer
  fields. This was a new-slice defect found and fixed before completion.
- Response-schema validation uses the supported `jsonschema.validate` entrypoint
  with `Draft202012Validator` explicitly selected. It rechecks the persisted schema
  as well as the answer, resolving an existing generated-validator/protocol typing
  diagnostic without a cast or suppression. See the version-matched
  [jsonschema 4.26.0 contract](https://python-jsonschema.readthedocs.io/en/v4.26.0/validate/).
- The local typed hook includes the wait models, AgentRun service and continuation
  pipeline. No migration, dependency upgrade or public response-schema change.

Executed verification:

- **148** wait/answer function assertions, **118** continuation assertions and
  **166** previous signal/callback assertions pass. Coverage includes discriminated
  JSON readback, null/pending distinctions, copied invalid instances, finite JSON,
  unknown fields, schema mismatch, exact IDs and frozen field reassignment.
- **563** disposable PostgreSQL assertions pass: previous **165** replay/history
  checks plus twelve pause/resume cases (input, JSON-null input, approved policy,
  rejected sandbox approval across all three product projections). Real request,
  message, public DTO, budget and transcript paths were exercised. Repeat answers,
  cross-org refusal and malformed approval refusal before capacity reacquisition
  were checked. Controlled tool and checkpoint ports replace external execution;
  this is not live vendor or worker-restart QA.
- All five local typed/import hooks pass. Whole-project Pyrefly: **861** diagnostics,
  seven suppressions, **1,231** modules; down from 862, not a clean global check.
- One continuation probe initially omitted required approval fixture fields; the
  fixture was corrected, without loosening the production schema.
- Previous **195** tool-item, **117** model-block and **105** history assertions
  also pass. Total function assertions for this increment: **849**.
- Final Ruff, seven-file formatting check and `git diff --check` pass.
  Application import/OpenAPI generation passes with **564** components; the new
  private models are not public components. Documentation verification passes:
  46 pages, 280 links, 90 packages, 1,139 modules, 5,962 docstrings and 47 diagrams.
  The verifier caught the missing pipeline-catalog entry; it was added and rechecked.
- Disposable container `eylo-typeqa-run-signals-20260908-e31b` was verified as
  tmpfs-only with no published DB port or persistent volume, then stopped and
  removed after the final 563-check run. Absence was verified. Synthetic data is
  discarded and reproducible from the probes; no operator data was touched.
  Probes ran through stdin and are not retained as repository test files.

Milestone review, in repository order:

1. DDD: module contracts own answers; pipeline contracts translate framework pauses.
   No new module/socket coupling or framework import of platform code.
2. Architecture fit: no second persistence authority, table or resume mechanism.
   Continuation-specific semantics stay outside the AgentRun module.
3. Data flow: original JSON spellings are retained through filing and readback;
   no queries or external work were added inside transactions. Capacity, request
   and transcript effects were checked against real PostgreSQL.
4. Plan adherence: this advances F2, not the full F0–F10 objective. Live vendor,
   worker and remaining provider/metadata contracts are explicitly open.
5. Clean code and safety: named objects replace remembered keys; generic schemas
   and answers remain dynamic only where allowed. Approval comment/rejection
   semantics remain; malformed approval errors use one safe domain message.

This is implementation/function-QA evidence, not new human product acceptance or
whole-platform completion.

Next: durable workflow claim/receipt and wake-event payload contracts, remaining
framework metadata/settings/usage, then the existing F3–F10 provider-flow sequence.
Operator historical data, live vendor, widget/voice and worker-crash QA remain
unrun in this increment. No deployment, commit or operator DB mutation occurred.

#### Durable claims, receipts and wake events — verified F2 continuation

Contract-first trace: `AgentRunAbsurdAdapter.spawn_run` → IDs-only engine payload →
`AgentRunWorkflow.execute` → authoritative PostgreSQL claim → product executor →
terminal receipt. The second path is committed `answer_input_request` → typed wake
notification → conversation/objective/scheduled resume → DB answer and capacity.

Implemented:

- `AgentRunTaskParams` validates the closed organization/run locator; unknown
  fields and malformed identifiers fail before a claim. Valid wire keys, UUID
  strings, workflow name, idempotency key and receipt format are unchanged.
- `InitiatingPrincipalRef`, `AgentRunExecutionClaim`, `AgentRunWorkflowReceipt`,
  `AgentRunRegistrationHealth` and `AgentRunTaskBinding` are Pydantic data contracts.
  Claims validate revision types and finite manifest JSON. Product-specific
  manifest interpretation stays in pipelines; this is not a universal manifest
  schema. Receipts reuse the domain lifecycle/outcome rules and cannot represent
  a nonterminal result. Registration/binding booleans remain intrinsic predicates,
  not newly invented modes.
- `AgentRunInputEvent` owns the three-ID wake payload. The answer producer passes
  the object; the Absurd adapter serializes it. All three resume validators reuse
  its exact matching rule, including rejection of extra fields, foreign IDs,
  UUID objects or alternate UUID spellings on the wire. Human answers never enter
  the engine event. Product-specific refusal classes/messages are preserved.
- General `AgentRunWorkflowContext.await_event` returns `object`, not `Any` or a
  falsely universal input-event type. SOR command waits retain their own receipt
  readback path. The SDK's generic checkpoint/replay result contract is unchanged
  and remains part of the subsequent durable-runtime review.
- Existing local typed hooks now include workflow and adapter contracts.

Executed verification:

- **231 function assertions**: task parsing, frozen models, nested principal
  revalidation, manifest isolation/finite JSON, all lifecycle/outcome combinations,
  three-product wake matching, spawn/binding idempotency, publication cleanup,
  terminal workflow replay, budget failure and invalid-input refusal.
- **596 PostgreSQL/SDK assertions**: 563 existing answer/resume, transcript and
  provider-history checks plus 33 claim/queue checks. Actual claim functions verify
  published revision identity, current principal, cross-org refusal, premature
  binding refusal, cancellation, terminal replay and released capacity.
- Actual Absurd **0.5.0** executed the registered workflow with two configured
  worker lanes. A synthetic executor persisted an input wait, suspended, released
  capacity, accepted a committed answer while the worker was stopped, then resumed
  after worker restart and persisted the expected terminal product/engine results.
  Only product model/tool behavior was substituted. This proves graceful worker
  stop/restart, not process-kill recovery or concurrent workload fairness.
- The first SDK probe failed because the temporary harness called
  `current_transaction.get()` instead of the actual `current_transaction()` API.
  The error was reproduced and localized to the probe; no production workaround
  was added. Its exact task was cancelled in the disposable DB before retrying.
  The corrected readiness check requires a persisted input request as well as
  engine `sleeping` state, distinguishing a wait from retry backoff.
- Five local typed/import hooks pass. Whole-project Pyrefly remains at **861
  diagnostics, seven suppressed**; this is not a clean-platform claim. Python
  lint passes. Six prior function probes pass again: 148 wait, 118 continuation,
  166 signal/callback, 195 tool-item, 117 model-block and 105 history assertions.
  Together with the new 231 assertions, this is **1,080 function assertions**.
- App import/OpenAPI passes with 564 components; private workflow models do not
  enter the public schema. Eight changed Python files pass formatting; diff
  whitespace checks pass. Documentation validation passes: 46 pages, 280 links,
  90 packages, 1,139 modules, 5,966 docstrings and 47 diagrams.
- Removed the verified tmpfs-only database container
  `eylo-typeqa-workflow-20260908-c74a` after QA; it had no host ports or persistent
  volume. No operator database or configured development service was changed.

Milestone review, in order:

1. DDD: AgentRun owns execution/wake vocabulary; product manifests stay in
   pipelines. No vendor type or framework dependency moved into a domain contract.
2. Architecture fit: data snapshots use Pydantic; the live workflow/context and
   SDK resource owners remain behavior classes. No parallel execution authority.
3. Data flow: unchanged queue wire format, actual DB authority reload, committed
   answer before publication and canonical terminal output outside engine receipts.
4. Plan alignment: advances the original F2 flow and Pydantic-first clarification;
   does not complete F2 or omit F3–F10. Public API and provider contracts are unchanged.
5. Maintainability/security/performance: shared wake validation replaces three
   remembered dict contracts; safe error messages hide malformed payload content.
   No additional DB query, external call inside a transaction, retry policy or
   migration. Manifest validation operates on the existing DB-bounded snapshot.

Next: remaining framework metadata/settings/usage and durable runtime/step payloads,
then the existing F3–F10 provider-flow sequence. Live vendor, widget/voice, operator
historical data and process-crash QA were not run for this increment. No deployment,
operator DB mutation, commit or retained test suite.

#### Usage accounting and numeric settings — verified F2 continuation

Trace: configured `ModelSettings` → pinned organization provider resolution →
native response/usage → `LLMUsageInfo` → budget meter → framework `ModelUsage` →
terminal message metadata → `MessageService` → PostgreSQL → typed readback.
Memory formation/reconciliation use their own domain reservation identities.

RCA and changes:

- `LLMUsageInfo` previously defaulted missing primary counts to zero and accepted
  coercible values. Both primary fields are now required strict nonnegative
  integers; optional detail counts have the same numeric constraint. A legitimate
  zero report remains valid. Revalidation catches malformed copy-built instances.
- All eight executable LLM branches use the checked normalizers; Bedrock shares
  the Anthropic normalizer. Invalid usage maps to each adapter's existing typed
  response error without embedding the native payload in the exception.
- Cerebras no longer manufactures primary zeros for partial reports. Present
  consumed counters are checked even when another primary counter is missing.
  Gemini retains native partial updates and produces canonical usage only once
  both primary counts are known. Cumulative updates replace counts, not add them.
- `ModelUsage` validates all five counters and preserves zero initialization for
  accumulators and synthetic replay. `FrameworkTerminalMessageMeta.usage` retains
  that object until JSON serialization rather than accepting arbitrary count keys.
- `ModelSettings` validates configured revision/token/top-k integers and bounded
  temperature/top-p values. `ExistingConversationModel.generate` revalidates before
  credential resolution, including copy-built settings. No model/provider default
  or new configuration policy was introduced.
- `ExecutionTokenUsage` belongs to the AgentRun domain. Agent and memory meters
  validate it before acquiring a transaction. Reservation locks, cross-org checks,
  cumulative memory replay, pricing and commit-before-budget-refusal are unchanged.
  The local LLM/framework type hook now includes `budgets.py`.
- The three remaining accounting dataclasses are frozen Pydantic contracts:
  `_ExecutionBudgetScope`, `_MemoryExecutionBudgetScope` and `_ActiveCapacity`.
  Scope IDs and memory kind must have their domain types before ContextVar binding;
  capacity values are strict nonnegative integers. Context managers have explicit
  iterator contracts. No scope precedence, lifetime or capacity formula changed.

Executed verification:

- **521 function assertions** cover strict counts/settings, required versus absent
  usage, optional details, JSON round trips, frozen/copy-built values, all native
  normalizers, Gemini cumulative updates, terminal metadata and refusal before
  transaction acquisition or credential resolution.
- **157 PostgreSQL/SDK assertions** cover actual pinned config resolution, OpenAI
  SDK request/response parsing in streaming and single-response modes, background
  prompt consumption, budget storage, eight concurrent increments, foreign-org
  refusal and memory formation/reconciliation replay. Vendor transport asserts no
  active DB transaction. Known, zero, missing, malformed and over-budget reports
  exercise their distinct outcomes; SDK clients close on success and refusal.
- Successful outputs pass through the terminal metadata producer and actual
  `MessageService` into PostgreSQL, then `MessageInDb` and the metadata owner's
  model on readback. This is function/integration evidence, not a complete widget
  or worker-driven conversation QA run. No actual vendor was contacted.
- **91 scope/capacity assertions** cover construction, frozen fields, invalid
  identity refusal before binding, capacity measurement, nested run/memory routing,
  task isolation and restoration after exceptions/cancellation. The 157-check DB
  flow passed again after converting these contracts.
- **222 prior function assertions** pass again: 117 model-block and 105 history
  assertions. Together with this increment's checks: **834 function assertions**.
- Five local typed/import hooks pass; the LLM hook retains one existing
  suppression. Focused usage/settings checks have zero errors. Whole-project
  Pyrefly remains **861 diagnostics, seven suppressed**. Python lint passes.
- Temporary probe mistakes were corrected against the real contracts: missing
  request ID, wrong `MemoryLevel` import, omitted required retry limit, and an
  assumption that assistant content was a single block. No product workaround
  was added for these errors. Cerebras SDK construction itself can coerce values;
  malformed-instance checks use copied native objects. These checks cannot recover
  raw wire distinctions already erased by an SDK's parser.
- App import/OpenAPI passes with 564 components; accounting contracts remain
  private. No generated API contract update is required. Removed the verified
  tmpfs-only `eylo-typeqa-usage-20260908-d92f` database container and its synthetic
  data, then confirmed the container absent. It had no host ports or persistent
  mounts; no operator data was changed.

Milestone review, in order:

1. DDD: native usage remains vendor-owned; shared normalized usage, standalone
   framework totals and domain accounting each retain their own contract.
2. Architecture fit: no SDK, socket or framework dependency was added to budget
   domain types; no additional execution authority, migration or dependency.
3. Data flow: primary counts no longer silently change missing → zero. Existing
   output refusal, explicit zero, replay totals and JSON field names are preserved.
4. Plan alignment: advances F2 and Pydantic-first requirements; not whole-platform
   completion. Non-numeric settings, metadata and F3–F10 remain in scope.
5. Maintainability/security/performance: bounded numeric checks replace implicit
   coercion; exceptions exclude malformed input. No new DB query or external I/O
   inside a transaction; detail counters do not change the existing cost formula.

At that checkpoint, vendor stream-state dataclasses, other framework settings/
metadata, general durable step payloads and the original F3–F10 flows remained.
The following increment addresses stream state. Live provider, operator
historical-data, widget/voice and process-crash QA were not run here.

#### Native stream state — verified F2 continuation

Trace: native SDK response/event → vendor-owned assembler → complete canonical
response/tool batch → existing framework consumers. Gemini retained message
metadata also passes through its verified replay object before native history.

Changes:

- Seven stream assemblers now use Pydantic instead of dataclasses: OpenAI Chat,
  OpenAI Responses, Groq, Sarvam, Cerebras, Anthropic and Gemini. Bedrock shares
  the Anthropic assembler. Strict construction, forbidden extras and assignment
  validation retain the existing mutable lifecycle and per-instance collections.
- `ToolCallBuffer` uses the same internal contract policy; argument text is
  excluded from repr. Empty partial fields remain valid during assembly, not as
  executable calls. Finite JSON, complete identity and whole-batch duplicate
  checks still run before tool exposure.
- `GeminiMessageReplay` is a frozen Pydantic value. All 22 constructor sites for
  these nine contracts use named arguments, including retained replay. Native
  `Part` types and signatures stay inside the Gemini boundary.
- Removed unnecessary empty-string fallbacks from the pending Cerebras
  completion conversion. The installed SDK requires completed-call ID, name
  and arguments; optional streaming fragments are a different contract. Missing
  completed fields are rejected rather than normalized.
- No SDK client, task, connection or callback owner was converted. No common
  vendor state machine or new persistence representation was introduced.

Executed verification:

- **201 function assertions** cover strict construction/assignment, unknown
  fields, per-instance collection isolation, frozen replay, fragmented tools,
  finite JSON, duplicate/mismatched IDs, every assembler's terminal output,
  early EOF, malformed batches, cumulative usage and Gemini signature replay.
- **275 native SDK/transport assertions**, across **56 scenarios**: each of the
  eight branches executes single-response, complete stream, malformed output,
  early EOF, consumer close, task cancellation and transport interruption.
  These call the real adapters and installed SDKs with controlled HTTP responses;
  Bedrock uses AWS event-stream framing through its native decoder and signer.
  Tool output is not exposed before resource cleanup; unfinished paths expose
  no executable tool batch. They are not live-vendor or full-agent QA.
- Gemini's supplied-client versus owned-client cleanup differs by SDK contract.
  The transport fixture uses SDK-owned clients. Its nested response iterator
  does not immediately mark the mock wire closed on consumer close; the owned
  clients do close. A separate loopback HTTP server verified actual connection
  EOF on both consumer disconnect and task cancellation, using the SDK's normal
  transport selection. No production workaround was needed for the mock flag.
- Previous usage (521), framework block (117) and history (105) assertions pass
  again: **1,219 function/transport assertions** including this increment's
  201 and 275. The two real-connection cases are additional. No DB probe was
  repeated because this increment changes only transient vendor assembly and
  replay construction; earlier DB evidence is recorded separately above.
- Nine-model/22-caller AST checks confirm keyword construction and no new
  module/framework imports at the vendor boundary. Eight changed files pass
  focused Pyrefly and formatting. Five local typed/import hooks and full Python
  lint pass. Whole-project Pyrefly remains **861 errors, seven suppressed**.
  App/OpenAPI generation passes with 564 components; these models remain private.
  Documentation verification passes: 46 pages, 280 links and 47 diagrams;
  `git diff --check` passes.
- A local current-code timing sample of 1,000 native text chunks per assembler
  measured OpenAI Chat 13.86 ms, Groq 13.20 ms, Sarvam 19.60 ms and Cerebras
  14.10 ms on Python 3.13.2/Pydantic 2.11.10. This excludes transport and is not
  a before/after regression comparison or a provider-latency claim.
- Probe corrections followed installed SDK/source evidence: Cerebras fingerprint
  and completed-field requirements, premature fixture `[DONE]`, Gemini client
  ownership and existing timestamp enrichment. No product fallback was added
  to accommodate an invalid fixture. No test files were added to the repo.

Milestone review, in order:

1. DDD: native events and stream state remain vendor-owned; the shared buffer
   handles only common tool assembly. Framework and module boundaries are intact.
2. Architecture fit: internal data contracts use Pydantic; resource ownership
   stays with adapters. No new dependency, DB model, public schema or workflow.
3. Data flow: text may stream early, but terminal validation owns execution.
   Native signatures, usage and response identities survive the conversion.
   Container mutation still relies on ingress/final validation, not a false
   claim of deep validation from `validate_assignment` or `frozen`.
4. Plan alignment: advances F2 and the explicit Pydantic-first clarification.
   Does not complete F2 or substitute a dataclass sweep for the F3–F10 flows.
5. Maintainability/security/performance: named construction removes positional
   ambiguity; typed failures retain safe messages. No new I/O, query, retry,
   parser pass over the complete accumulated history or execution authority.
   Broader throughput and baseline comparison remain outside this measurement.

At that checkpoint, effective LLM config/overrides, other framework settings/
metadata, general durable step payloads, and the original F3–F10 flows remained.
The following increment addresses effective LLM config. No deployment, operator
DB change, live vendor invocation, widget QA, migration or commit occurred.

#### Effective LLM config — verified F2 continuation

Trace: API-owned config fields → LLM config service → encrypted revision storage
→ latest/pinned resolver → generation overrides → neutral inference config →
native adapter request → usage/message persistence. Readiness and organization
authority still come from the existing provider-config service.

Changes:

- Replaced `LLMInferenceConfig`, `LLMGenerationSettings`, `LLMOverrides`,
  `LLMProviderConfig` and `ResolvedLLM` dataclasses with frozen Pydantic models.
  The old structural generation protocol is now a concrete neutral model.
  Common scalar fields validate shape; provider/model compatibility and
  supported overrides remain domain policy. No socket imports a module.
- Shared config values use strict validation, forbidden extras and instance
  revalidation. Applying overrides constructs a validated result rather than
  using unchecked `model_copy(update=...)`. Previously created/copied nested
  models cannot bypass scalar or provider validation at these boundaries.
- Renamed the stored-config entrypoint to `LLMProviderConfig.from_storage` and
  updated all four service callers. This avoids overriding Pydantic's deprecated
  `validate` method. Config storage keys, provider spelling, model IDs, optional
  settings, supported override selection and explicit-model policy are unchanged.
- Credentials retain copied read-only mappings and are excluded from repr and
  both Python/JSON model dumps, including nested resolved models. Dumps are not
  credential restore formats. Revision/UUID/authority fields remain strict;
  intrinsic readiness/grant booleans keep their existing meaning.
- Structural validation failures become safe `InvalidLLMConfig` errors, so
  existing service/resolver/controller translation still applies. A milestone
  probe also found that invalid model strings appeared in chained enum errors;
  model/provider rejection now suppresses that input-bearing cause without
  changing the public domain message. No actual credential exposure was observed.
- Added service/resolver files to the existing local LLM type gate. No SDK client,
  connection, DB aggregate, verifier result, public API schema or migration changed.

Executed verification:

- **100 before/after function assertions** across all eight providers have
  identical stored/configured/override output. Explicit edge cases retain empty
  override behavior, list-to-tuple stops, numeric limits, unknown-field refusal,
  secret-copy isolation and ignored unsupported overrides.
- **349 hardening/service/resolver assertions** cover malformed and unchecked
  nested models, immutable fields/secrets, dump/schema exclusion, safe exception
  chains, UUID/revision/flag types, invalid input refused before persistence,
  latest/pinned resolver failures, all eight factories and generation parameters.
  Service persistence collaborators in this set are controlled fixtures.
- Repeated **201 assembler** and **275 native SDK/transport assertions**, covering
  all eight branches' single/complete/malformed/incomplete/close/cancel/error
  cases. This is **925 function/transport assertions**, not live vendor QA.
- **269 real PostgreSQL assertions**: eight providers' real service create/update,
  encrypted credential readback, masked public projection, old/new pinned
  revisions, exact tenant ownership and rejected updates producing no revision.
  The same probe exercises real agent/background request construction through
  a native OpenAI SDK with synthetic HTTP responses, budget effects, terminal
  message filing/readback and memory usage replay. Vendor calls run without an
  active DB transaction. This is service-level DB QA, not HTTP/login/widget QA.
- Existing migrations upgraded an isolated tmpfs DB to `eylo0012`. It exposed no
  host port and mounted no operator data. The QA container and its synthetic
  data were removed; absence was checked. No operator DB/service was changed.
- Focused Pyrefly, five typed/import hooks, full Python lint, app/OpenAPI and
  caller imports pass. OpenAPI remains 564 components with config values private.
  Whole-project Pyrefly remains **861 errors, seven suppressed**; this is not a
  platform-wide clean-typecheck claim.
- A same-process median over five batches of 1,000 config-create/resolve calls
  measured **16.50 ms before** and **32.45 ms after**, using the exact prior
  dataclass source and current Pydantic source. This measures local validation
  overhead only, roughly 16 microseconds added per call, not DB/vendor latency.

Milestone review, in order:

1. DDD: neutral scalar contracts remain shared; provider policy stays in the LLM
   config module. Behavioral factory/resolver ports remain protocols.
2. Architecture fit: one validated config path serves conversation, background,
   parallel-agent and memory callers. No new credentials, default model, transport
   layer, migration or execution authority.
3. Data flow: normalized storage and pinned revision meaning survive round-trip;
   invalid copies are refused, credentials remain inaccessible to generic dumps,
   and external request execution remains outside owned DB transactions.
4. Plan alignment: advances the Pydantic-first F2 correction, not whole-platform
   completion. Verification result dataclasses, general provider aggregates,
   remaining framework metadata/settings and F3–F10 are still in scope.
5. Maintainability/security/performance: field validation is shared instead of
   manually repeated post-init assignments. Safe errors retain domain translation.
   No new queries or I/O; measured local validation overhead is reported above.

Target: installed and locked Pydantic **2.11.10**. Relevant contracts:
[instance revalidation](https://docs.pydantic.dev/2.11/api/config/#pydantic.config.ConfigDict.revalidate_instances),
[frozen models](https://docs.pydantic.dev/2.11/concepts/models/#faux-immutability),
and [field serialization exclusion](https://docs.pydantic.dev/2.11/concepts/serialization/#model-and-field-level-include-and-exclude).
Private dataclass equality/hash behavior is not a cache API; no consumer relies
on these values as cache keys. No persistent test suite or fixture was added.

#### LLM verification — verified F2 boundary completion

The previous verifier discarded native SDK responses: an OpenAI HTTP 200 with
`{}` was reproduced as a successful verification. Its module-owned SDK calls
also ran under the route's request-scoped DB transaction. This was not a claim
about a live vendor outage; the response defect was reproduced with the real
installed OpenAI SDK and controlled HTTP transport.

Completed contract and ownership corrections:

1. `common/contracts/llm_verification.py` owns frozen, validated detached input
   and provider/model receipts. Secret maps are copied, read-only, and excluded
   from representation and serialization. The module's revisioned result uses
   a strict positive revision and timezone-aware verification timestamp.
2. `sockets/llm/verification.py` owns native SDK creation, request/response types,
   cleanup and safe error translation. The generic timeout helper preserves its
   awaited response type. Every branch runs its existing native inference
   response validator before returning a receipt. Valid token-limited responses
   remain acceptable without requiring literal “OK” output.
3. `pipelines/llm/config_verification.py` resolves detached config in a read
   transaction, closes it before vendor I/O, then conditionally marks the same
   revision in a short write transaction. It refuses an enclosing transaction,
   malformed receipts and receipts for a different provider/model. A concurrent
   edit cannot mark the new revision verified; deletion cannot be resurrected.
4. The config module exposes the verification use-case protocol. The HTTP verify
   route has a separate non-transactional controller dependency; CRUD retains
   its owned transaction. Public provider/model spelling and camelCase
   `verifiedAt` are unchanged. The existing bearer-auth resolver is exercised,
   not replaced by an authentication stub in the DB/API probe.
5. Gemini uses its documented explicit async and sync close operations. This
   removes the installed SDK's invalid async context-manager annotation from
   the path without suppressing it or changing dependencies. Cerebras explicitly
   requests non-streaming output and closes/refuses an unexpected native stream.

Executed evidence:

- **440 assertions / 56 native SDK scenarios** across OpenAI Chat, Responses,
  Anthropic, Bedrock, Groq, Cerebras, Gemini and Sarvam: success, token-limit
  completion, empty malformed response, auth error, transport failure, timeout
  and cancellation. Request model/token limits, safe errors and owned client
  closure are checked. These are controlled transports, not live vendor QA.
- **16 boundary assertions:** forged input revalidation before SDK construction,
  absent credentials and the native Cerebras stream/result union refusal.
- **223 authenticated API/PostgreSQL assertions:** all eight providers pass
  create → bearer auth → config resolution → actual native SDK → verified
  revision write → readback. Checks cover encrypted storage, stable API aliases,
  foreign-org 404, unauthenticated refusal, invalid IDs, malformed/error/timeout/
  cancellation outcomes, concurrent edit and deletion, two simultaneous probes,
  forged receipts and an enclosing transaction. The connection pool has zero
  checked-out DB connections at single-probe vendor request entry.
- Existing **349 effective-config**, **201 stream-state**, and **275 native
  inference transport** assertions pass. All five local typed/import hooks pass;
  no new suppression is introduced. Full-project Pyrefly remains **860 errors,
  7 suppressed**, versus the preceding 861-error checkpoint; this is not a
  whole-platform green check. Server/CLI Ruff and six-file formatting pass.
- The application imports and produces OpenAPI with **564 components**. No
  public schema or frontend source changed for this slice.
- Documentation verification passes: 46 pages, 282 links, 90 packages, 1,142
  Python modules, 5,986 docstrings and 47 diagrams. `alembic check` reports no
  new upgrade operations on the disposable DB; existing FK-cycle and vector-type
  introspection warnings limit that schema comparison, so it is not proof of
  complete constraint/vector parity.

Probe corrections and additional findings:

- Early probes omitted required `max_tokens`, seeded a password-less member,
  used snake_case API keys, reused a unique config name and injected an externally
  owned Gemini HTTP client. They were corrected against real contracts; no
  product assertions or response validation were weakened. Gemini teardown is
  checked with SDK-owned transports, matching the production construction path.
- **Open F0/F10 auth-schema follow-up:** `MemberModel.password` is nullable but
  `MemberModelSchema.password` is annotated as `str`. A real null-password row
  fails read-schema validation (`password`, `string_type`); bearer auth translates
  that into 401. Trace invitation/password-setup/login and member projections
  before fixing nullability and its consumers together. The API probe uses
  complete password-based members and does not claim this mismatch is fixed.
- The existing Passlib/bcrypt version-introspection warning occurs while hashing
  synthetic member passwords; hashing and bearer auth still complete. No auth
  dependency upgrade is included in this LLM flow.

Sequential milestone review:

1. DDD boundaries: SDKs stay in sockets; config/revision policy stays in modules;
   the pipeline composes them. Shared values contain no SDK or ORM types.
2. Architecture fit: one verification use-case port, no additional task authority,
   vendor defaults, retries, persistence tables or transport implementation.
3. Data flow: detached encrypted-config readback → SDK-native validation → typed
   receipt → revision-checked write → unchanged HTTP projection. Invalid and
   cancelled probes do not persist a success; genuine revision races fail closed.
4. Plan alignment: completes verification within F2, not F2 as a whole or F3–F10.
   General provider aggregates, remaining framework settings/metadata and every
   outstanding vendor operation remain in scope.
5. Readability/security/performance: explicit fields replace result dataclasses;
   existing validators avoid parallel wire schemas; secrets and response text
   stay out of receipts. Vendor latency no longer holds a checked-out DB
   connection. No provider latency or throughput improvement is claimed.

Target: Pydantic 2.11.10, OpenAI 2.14.0, Anthropic 0.75.0, Google GenAI 1.56.0,
Groq 1.1.1, Cerebras 1.67.0 and Sarvam 0.1.28, verified from the installed
environment. Gemini close semantics were checked against its
[versioned SDK source](https://github.com/googleapis/python-genai/blob/v1.56.0/google/genai/client.py).
Existing migrations through `eylo0012` were applied only to a disposable tmpfs
database with no host ports or mounts. That QA container and its synthetic data
were removed after verification, and container absence was checked. Operator data, live vendor credentials,
containers and migration history were not changed. Human browser/product review
and live vendor verification are not claimed; no persistent test suite was added.

#### Framework run settings and failures — verified F2 continuation

Trace: run config / agent spec → conversation run or resume wrapper → framework
context → model/tool loop and handoff assignments → typed failure result → JSON
readback and terminal-message projection. Framework contracts remain independent
of platform/provider imports.

RCA and implementation:

- `RunConfig` accepted boolean/text counts, an infinite timeout, and opaque values
  in its JSON annotation field. A copied config with `max_turns=True` completed a
  model call; a copied agent containing `max_tokens=True` also reached the model.
  Initial Pydantic construction alone did not validate later unchecked copies.
- Limits now use strict finite numbers, named existing defaults and instance
  revalidation. Metadata and reasoning extensions retain dynamic vendor keys but
  require finite JSON values. Framework model/vendor names remain open strings;
  platform-owned provider catalogs are not imported into the framework.
- Conversation run/resume validates config before hydration or resumed effects.
  The framework uses the validated context config, not the caller's original
  object. `AgentSpec` revalidates settings; `RunContext` validates assignments and
  records the validated agent on handoff. Live dependency identity/exclusion and
  mutable run progress are preserved. Background config overrides validate the
  caller's settings before applying the existing no-handoff value.
- `RunFailureCode` / `RunFailureMetadata` replace the runner's fixed failure dict.
  Existing wire keys/values remain unchanged; status/category disagreements are
  refused. Historical annotations without an owned failure code still round-trip.
- Milestone review caught a new exclusion regression: flattening a metadata
  subclass into the base model turned excluded fields into serializable extras.
  Revalidation now preserves typed subclasses; promoting a generic envelope uses
  its serialization exclusions. Private sentinel probes prove exclusion through
  result output and the actual terminal-message projection. This was fixed before
  completion; no deployment or real private data was involved.
- Six pre-existing protocol diagnostics were docstring-only method bodies in
  `Guardrail` and `Session`; explicit interface stubs now match their contracts.
  The local LLM type hook checks the entire framework-agent package rather than
  an incomplete list of individual files.

Executed verification:

- **259 function assertions**: strict/bounded values, unchanged defaults, JSON
  readback, copied/constructed instances, assignment rollback, nested annotation
  detachment, live dependency identity, background overrides, model/tool turns,
  valid/invalid handoffs, guardrail failures, exact turn-limit effects, timeout,
  cancellation cleanup, approval replay and wrapper refusal before DB hydration.
- Failure checks cover enum restoration, safe exception classification, status
  mismatch, copied results, extra public annotations, private subclass fields and
  a subclass that disables ordinary instance revalidation.
- Existing checks passed: 349 effective-config, 117 model-block, 201 stream-state,
  and 275 native SDK transport assertions across 56 scenarios / eight adapters.
  Transports are controlled fixtures, not live vendor operations.
- Full framework package plus changed callers: zero Pyrefly diagnostics. All five
  local type/import gates passed. Full project: **854 diagnostics, 7 suppressed**
  (previously 860); full-platform type hardening is not complete.
- Full server/CLI Ruff and app OpenAPI generation passed (564 schemas).
  Local `RunContext` construction medians were 8.95 / 11.39 / 28.54 microseconds
  with 0 / 100 / 1,000 tool specs (five repeats of 1,000 constructions). This is
  synthetic construction timing, not provider latency or product throughput.

Pydantic 2.11.10's frozen-assignment error is created outside its configured
validator and can still show the assigned value. The initial probe incorrectly
assumed `hide_input_in_errors` covered that path; its source was inspected and the
frozen-mutation check now asserts refusal separately. This is not a promise that
arbitrary Pydantic errors are safe to expose; framework failures serialize only
safe classification. No dependency change or blanket exception suppression.

Review completed in the required order: DDD ownership, architecture fit,
source-to-sink flow, plan alignment, then maintainability/security/performance.
No additional DB query or provider call was introduced. This slice does not prove
historical operator-data compatibility, live vendor behavior, browser/voice UX or
worker recovery; no DB, provider config, deployment, migration or Git history was
changed. No retained test suite or hosted automation was added.

At this checkpoint, framework mode booleans and unsupported-setting disclosure
remained open. The continuation below resolves those contracts; it does not
implement the reserved features. Other producer metadata and caller payloads
remain in F2, followed by the existing F3–F10 sequence.

#### Framework modes and ordered speech contracts — verified F2 continuation

Trace: process settings → conversation/scheduled/objective run config → framework
model settings → pipeline translation → single/streaming inference → ordered
speech segments → org/conversation-scoped transport delivery. Live-voice terminal
prompts share the same delivery contract.

- `RunStreaming`, `RunPromptCaching`, and reserved `RunTracing` are distinct
  framework enums. Python callers cannot substitute booleans, another enum family,
  or truthiness. Existing boolean JSON snapshots still round-trip. Numeric aliases
  such as JSON `1` are rejected; Pydantic's native enum parsing alone accepted them.
- Pipeline translations exhaust the owning enum. No platform import entered the
  standalone framework, no vendor fallback was added, and cache override precedence
  is unchanged. Scheduled/objective runs remain non-streaming; conversation process
  settings and live-voice streaming retain their previous behavior.
- `max_handoffs`, `handoff_lookback_window`, and `tracing_enabled` now have explicit
  experimental schema descriptions. They do not enforce handoff limits/history or
  tracing policy. Background config documentation no longer implies that the
  unused handoff count itself prevents handoffs.
- The next source-to-sink trace reproduced integer speech text and string
  `"false"` completion being accepted by a dataclass, plus opaque request objects
  being stringified into IDs. `pipelines/llm/voice_text.py` now owns frozen Pydantic
  correlation/segment models and `VoiceTextPhase`. Delivery revalidates copy-built
  inputs before side effects. UUIDs remain typed until the existing transport
  string boundary; null correlation remains supported. The framework still does
  not import platform speech contracts.
- Streaming, terminal message and live prompt producers use the same objects.
  Text-before-finalize, whitespace handling, final text plus completion, secondary
  state-failure isolation, cancellation and transport error behavior are preserved.
  Filler/session state policy and WebSocket payload typing beyond this delivery
  boundary remain part of the later voice flow.

Executed verification:

- 271 framework settings/failure assertions rerun successfully.
- 352 mode/producer assertions: enum-family refusal, boolean JSON compatibility,
  numeric-alias refusal, schema markers, hooks independent of tracing, real
  conversation-model translation/projection, cache override matrix, stream closure,
  live model construction, actual scheduled/objective framework turns, and the
  conversation durable executor's four environment-setting combinations.
- 127 speech-contract assertions: strict fields, JSON readback, copied-value
  refusal before effects, null correlation, exact scoped text/finalize payloads,
  three producer paths, repeated final response, secondary state failure and
  cancellation and transport-failure propagation. I/O ports were substituted;
  no microphone, TTS vendor or browser
  playback was exercised. Probe fixture omissions were corrected against actual
  participant/agent/result schemas, not by relaxing production validation.
- Existing 349 effective-config, 117 model-block, 201 stream-state, and 275 native
  transport assertions passed across all eight LLM adapters / 56 scenarios.
- All five local type/import gates and full Python lint passed. The LLM gate now
  includes speech correlation and routing. Whole-project Pyrefly remains at
  854 diagnostics, 7 suppressed: unchanged, not whole-platform completion.
- Documentation verification passed (46 pages, 282 links, 1,143 Python modules,
  5,999 docstrings, 47 diagrams). App import/OpenAPI generation passed with
  564 schemas; AST inspection found no platform imports in the framework.
  Eleven-file formatting and `git diff --check` passed.

Milestone review, in order: (1) framework/pipeline/vendor ownership is preserved;
(2) existing factories and direct ordered delivery remain the composition points;
(3) the verified contracts reach actual model response and transport projections;
(4) the changes follow F2 and the Pydantic-first clarification, without claiming
F3–F10 complete; (5) no extra I/O, retry, queue, suppression or dependency was added.
Segments are validated per delivery unit, not per binary audio frame. Model
validation is not proof of live provider or distributed delivery behavior.

No operator DB, provider config, migration, deployment or Git history was changed.
No retained tests or hosted CI were added. The following continuation addresses
the next agent/tool/run metadata projection path; F2 remains open before F3–F10.

#### Agent/tool identity and message metadata — verified F2 continuation

The producer/consumer trace confirmed five gaps: arbitrary agent-status text,
boolean revisions coerced to integers, malformed explicit tool IDs silently
replaced by generated IDs, UUID tool IDs omitted from approval output, and opaque
request/payload objects accepted until later stringification or serialization.

Implemented:

- `conversation/domain.py`: platform-owned `AgentStatus`, UUID tool/MCP/request/
  conversation identities, strict positive tool/target-agent revisions, nonblank
  deployed definition keys, and explicit platform-to-framework enum mappings.
  The four existing tool boundaries and three execution modes retain their wire
  values. Handoffs remain distinct from persisted tool revisions.
- `run_input_from_context` now accepts the request identity directly and includes
  organization identity from its owning context. Conversation/live-voice callers
  no longer overwrite typed metadata with JSON strings using unchecked copies.
- Known tool-call metadata uses the existing framework `ToolIdentity` contract
  and finite JSON arguments. Result metadata uses strict error predicates and
  finite JSON, including valid scalars/nulls and ordered batches. Invalid or
  copy-corrupted calls/results are refused before model-message projection.
- `conversation_runner.py`: Pydantic framework-only tool records; explicit IDs
  are validated while genuinely absent IDs still receive deterministic org-scoped
  UUIDs. Request IDs are parsed without invoking arbitrary object stringification.
  Handoff refresh validates counts, preserves UUIDs/extensions and excludes private
  fields. Error text does not echo invalid supplied identities.
- Framework approval output handles native UUIDs and restored string snapshots,
  preserving exact revisions and redacted argument names/counts. Booleans cannot
  masquerade as approval revisions. The framework imports no platform types.
- Live-voice filters now accept typed framework/platform tool collections and
  preserve the input element type and identity. Private replay associates UUID
  request identity without changing command IDs or transcript ownership.

Executed evidence:

- 414 focused function assertions: 213 identity/policy checks, 187 request/message/
  replay checks, 14 refresh/error-privacy checks. Includes the actual framework
  loop for AUTO/DISABLED/REQUIRES_APPROVAL before and after snapshot restoration,
  handoff/code-defined/MCP projections, batched result round-trips, live-voice
  drafts, private replay to model-facing DTOs, and the actual refresh callback.
  The model, DB/context-service and delivery ports were controlled. No vendor
  mutation, operator DB write, actual microphone call, or worker crash was run.
- Existing 352 framework-mode/producer and 127 ordered-speech assertions passed.
  Existing 349 effective-config, 117 model-block, 201 stream-state, and 275 native
  SDK transport assertions passed (eight adapters, 56 transport scenarios).
- All five local type/import gates, full server/CLI Ruff, six-file formatting,
  app import/OpenAPI (564 schemas), and `git diff --check` passed. Whole-project
  Pyrefly remains at 854 diagnostics, 7 suppressed; it is not a passing global gate.
- Probe fixture errors were corrected against actual schemas: `MessageInDb`
  exposes conversation linkage rather than an organization field; replay requires
  explicit pending-call/command collections; framework-generated result metadata
  is decoded via its real consumer. Production models were not weakened.

Milestone review, performed sequentially:

1. DDD: platform identity/policy translation remains in the pipeline. Framework
   metadata stays extensible without importing platform or vendor vocabulary.
2. Architecture: existing published-tool projections, approval gates, conversation
   hydration and transcript mechanisms remain authoritative; no new registry or
   persistence layer was added.
3. Data flow: native and JSON-restored identities reach approval and message
   projections intact. Tool arguments/results reject opaque/nonfinite data.
   Refresh keeps request correlation and excluded-field privacy. Real DB effects
   and live provider operation were not exercised by these controlled-port probes.
4. Plan alignment: this advances the original F2 flow and Pydantic-first decision;
   it does not complete F2 or exclude F3–F10 from the objective.
5. Maintainability/security/performance: explicit enums replace coercive object
   adapters; schemas replace an identity dictionary and one dataclass. No added
   DB/vendor call, retry, queue, dependency, type suppression, or hosted CI.
   JSON validation occurs at metadata/message boundaries, not binary audio frames.

Next F2 path at that checkpoint: framework-generated `_append_tool_messages` metadata and scheduled/
objective resumed exchanges → conversation/durable consumers → persisted/public
projections. Remaining generic metadata envelopes, canonical tool-content DTOs,
framework-only control outputs and caller payloads still need owner-defined types.
Then continue the unchanged F3–F10 provider data-flow sequence. No migration,
operator configuration, deployment, commit or Git history change occurred.

#### Generated and resumed tool history — verified F2 continuation

The last conversational turn confirmed the existing Pydantic execution-context
correction without editing code. This continuation resumed the unfinished history
contract; the full F0–F10 objective remains unchanged.

Source-to-sink changes:

1. `framework/agents/history.py` owns generated text/call/result metadata,
   named public tool-result data, response provenance and the exact exchange
   builder. The runner retains block order, skips calls without completed results,
   and updates the same transient-message count on the original metadata subtype.
2. Model provenance has one `ModelResponse` authority. Serialization regenerates
   the legacy flattened and duplicate response fields. Explicit provenance
   readback validates `model_response`; compatibility copies cannot replace it.
   Existing generic message envelopes remain extensible and are not claimed to
   reconstruct every producer-specific metadata type automatically.
3. `agent_run_transcript.append_resumed_tool_exchange` replaces duplicate
   scheduled/objective helpers. It does not change transcript persistence or
   transient ownership. Normal-loop structured result text remains key-sorted;
   resumed result text preserves insertion order, matching the prior paths.
4. Invocation history drops executor metadata in memory and serialization.
   Objective resume previously serialized the whole call, unlike the normal and
   scheduled paths. Only invocation fields now cross that boundary. Result
   provenance still excludes terminal-only output and owner-excluded fields.
5. Conversation consumers explicitly translate the named framework result and
   validate typed provenance before producing `MessageInDb`. Message content
   parameters use the existing content union. The ignored `organization_id`
   constructor argument was removed: it is not a `MessageInDb` field. This does
   not remove an authorization check; organization scope belongs to the owning
   conversation/context and persistence operations, not that ignored DTO keyword.
6. Framework request correlation accepts caller-owned strings/UUIDs; it does not
   import platform identity policy. Scheduled/objective and conversation consumers
   enforce platform UUID correlation. Invalid opaque objects are not stringified
   into apparently valid identities.

Executed evidence (installed Pydantic 2.11.10):

- **557 history assertions:** compare the actual pre-slice functions against the
  new functions; mixed text/reasoning/two-tool responses, complete/incomplete
  batches, native/JSON-restored inputs, correlation, content/readback, serializer
  include/exclude behavior, private fields, malformed copied models and mismatched
  results. Objective parity excludes only its intentionally removed call metadata.
- **40 native-format/loop assertions:** all eight real LLM history formatters
  receive identical pre/post-refactor messages; the real two-turn framework loop
  executes both commands once and reaches those formatters through its callback.
  Approval still stops before execution. Vendor generation and tool effects use
  controlled dependencies; no live vendor request was sent.
- **18 boundary/constructor assertions:** malformed copied provenance and result
  bodies are refused; owned metadata JSON projections round-trip; all generated
  message constructor keywords exist in the real `MessageInDb` schema.
- Regression probes: **414** identity/message/refresh assertions, **117** model
  block assertions, **352** framework mode/producer assertions and **127** ordered
  voice-text assertions pass. Two model-block assertions were updated to inspect
  typed attributes rather than the removed internal dictionary representation;
  their call/result ordering expectations are unchanged.
- A local seven-message construction plus JSON projection probe (median of five
  runs of 100 iterations) measured **0.186 ms before / 0.429 ms after** per turn.
  This measures local validation/projection overhead only, not service latency.
- Five local type/import hooks and focused checking of all seven changed Python
  files pass. Full Python lint and `git diff --check` pass. Full-project Pyrefly
  remains **854 errors, 7 suppressed**; these are still open, not a clean baseline
  redefinition.

Probe corrections: one initial assertion incorrectly expected excluded private
metadata to survive JSON round-trip; the actual contract preserves only its
public projection. A fixture initially inserted a string through unchecked copy
into a UUID-owned model; it now uses validated construction. Neither correction
relaxed production validation or changed a public expectation.

Milestone review, in order:

1. DDD: framework owns invocation/history data; pipelines own UUID authority,
   conversation translation and durable replay. No inward platform/vendor imports.
2. Architecture: reused existing runner, transcript, metadata and message contracts;
   no new execution lane, persistence table, dependency or serializer registry.
3. Data flow: all three producers reach their real message consumers and all eight
   native formatters. Order, correlation and public snapshots are verified. DB
   writes, worker crashes and live provider execution were not exercised here.
4. Plan alignment: closes this generated/resumed-history increment only. Broader
   metadata readback, canonical tool-content DTOs, terminal/control payloads,
   caller schemas and the F3–F10 provider sequence remain in scope and open.
5. Maintainability/security/performance: duplicated builders and response-meta
   classes were removed; private annotations are excluded; constructor fields are
   real. No extra DB/vendor calls, retries, locks or per-audio-frame validation.

Next F2 flow at that checkpoint: terminal tool output and `FrameworkTerminalMessageMeta` → run
completion/pause projections → durable and conversation readback → LLM history.
Then remaining canonical tool-content and caller contracts, followed by the
unchanged F3–F10 provider sequence. No DB mutation, migration, deployment, commit,
Git-history change or permanent probe file was made.

#### Terminal tool control and persisted completion — verified F2 continuation

Trace: widget/handoff/objective executor → framework `ToolResult` → loop decision
→ `RunResult` → conversation message or objective summary → typed JSON readback.

RCA reproduced before editing: `terminal_response="false"`, `1`, or a nonempty
object all ended a run because the loop tested metadata truthiness. Final-message
controls were also appended to a dictionary after its model had been validated.
This was a controlled reproduction, not evidence that a live vendor emitted those
malformed controls.

Implemented contracts:

1. Framework-owned completion enums accept native members or exact legacy boolean
   snapshots. Typed executor metadata validates control/output/artifact fields
   before result callbacks. Completed-run metadata requires the exact command ID
   and completion status; failure and pause controls cannot masquerade as success.
2. Widgets retain the existing receipt and reuse the already-delivered message.
   The framework owns only an opaque artifact reference. Conversation code owns
   UUID validation and the existing conversation, request, message-kind, presence,
   and Agent-run binding checks. Handoff circuit-breaker outcomes retain their
   behavior; their other metadata fields and `HandoffOutcome` remain a next slice.
3. `pipelines/conversation/completion.py` owns final-message and durable-summary
   projections. Canonical run metadata is typed; legacy top-level controls are
   generated only from its serialized public fields. Private subtype exclusions,
   nested field selection, null handling and replay eligibility remain intact.
4. Objective completion and framework turns replace their dataclasses with frozen
   Pydantic models. Captured invocation identity still selects the completion
   command. Reason whitespace and the existing unachievable-reason requirement
   are preserved. Persisted output is finite JSON, bounded by the existing exact
   65,536-byte UTF-8 result limit.

Executed evidence:

- **312 contract assertions:** strict controls, invalid aliases and copied models,
  native/JSON restoration, all run statuses, private fields, before/after final
  metadata parity, replay null handling, nested include/exclude and summaries.
- **80 producer/runner assertions:** actual platform widget producer and receipts,
  all five handoff outcomes, real framework completion/continue branches, safe
  malformed-result callbacks, objective control execution, pauses, delegation,
  cancellation and artifact authority. Vendor/effect dependencies were controlled.
- **160 persistence-projection assertions:** all run statuses with and without a
  durable run, real message DTOs with controlled service/transaction ports,
  pause/finish calls, widget reuse, foreign Agent-run refusal, cancellation,
  typed summary readback and exact encoded-size boundaries. No real DB write.
- Existing regression probes pass: **615** generated/resumed-history assertions
  including all eight native history formatters, **414** identity/message/refresh,
  **117** model blocks, **352** framework modes/producers and **127** voice-text.
  These are function/regression checks, not new human-approved behavioral coverage.
- Seven changed Python files typecheck cleanly. All five type/import hooks, full
  server/CLI Ruff, formatting, app import/OpenAPI (564 schemas) and diff checks
  pass. Whole-project Pyrefly remains **854 errors, 7 suppressed**, still open.

Review corrections: a replay parity gap added null model fields; the field
serializer now preserves the old replay shape without stripping canonical
metadata nulls. Nested compatibility-mirror selections now use Pydantic's normal
selection behavior. Probe fixtures were corrected to the actual `Model.generate`
signature and registered/qualified widget-tool identity; production availability
and validation were not bypassed or weakened.

Milestone review, in order:

1. DDD: framework control remains vendor/platform-neutral; conversation identity
   and objective lifecycle projections remain at their existing pipeline owners.
2. Architecture: no new persistence lane, provider, registry or resource owner.
3. Data flow: command decisions reach typed sinks/readback with existing wire
   shapes and authorization checks; malformed values fail before result callbacks.
4. Plan: closes this F2 increment only. Remaining tool-content DTOs, handoff and
   caller metadata, followed by the F3–F10 provider sequence, are still open.
5. Maintainability/security/performance: named controls and models replace raw
   keys/tuples/dataclasses; private fields stay excluded. No additional DB/vendor
   calls, locks or retries. No service-latency claim is made from these probes.

No deployment, live vendor request, worker-crash QA, microphone/UI QA, migration,
operator data change, commit, history rewrite or permanent probe was performed.

#### Handoff and normalized realtime boundaries — verified continuation

Trace: pinned handoff execution → typed outcome → tool result → text refresh or
live-voice capture. Realtime continuation: native vendor event → normalized
discriminated union → manager dispatch → playback, transcript, tool or teardown.

Corrections and contracts:

- `HandoffOutcome` and `HandoffResult` now validate the outcome, target Agent,
  participant and matching published revision. Dispatch still owns authorization.
  `HandoffToolMetadata` generates the existing snapshot flags from a typed outcome;
  mismatched flags, result status and target mirrors are rejected before refresh.
- Decomposed capture previously attributed the whole turn to its initial Agent.
  Capture now advances attribution after each validated successful handoff, while
  retaining the source for that handoff's invocation/result. Missing switch identity
  is an explicit capture error, not permission to guess. Public snapshots that omit
  private tool metadata are not a substitute for native live capture.
- All ten normalized realtime events have exact discriminators and strict fields.
  The manager revalidates native/copied events before dispatch; arbitrary objects,
  nonfinite tool arguments, and mismatched tags cannot drive effects. Unsupported
  audio rates cannot enter the fixed 24→16 kHz converter.
- Interaction callbacks are frozen Pydantic values excluded from serialization.
  End-call scheduling now accepts its declared Awaitable contract, including a
  Future or Task; completion, failure and cancellation are consumed by its owner.
- Gemini translation uses `google-genai` 1.56.0 native response fields. The old
  nonexistent `time_left_ms` lookup is replaced by `time_left` seconds-to-ms
  conversion. Transcript fragments remain append-only: SDK `finished` must not
  become the normalized replacement-text flag. Optional SDK lists are handled.

Executed evidence: **348 handoff assertions** (164 contracts, 138 producer/capture
paths, 46 pinned-dispatch/framework-loop checks); **362 realtime assertions**
(all ten variants, native Gemini messages, recorded OpenAI/Nova transports,
dispatch, transcript fragments, interruption/audio effects and callback cleanup).
Existing terminal/history/metadata/mode/model-block/voice-text regressions passed
**2,177 assertions**. These use controlled service, transaction and transport
ports; they do not prove live DB commits, vendor calls or microphone behavior.

All five existing local type/import gates passed. Whole-project Pyrefly decreased
from **854 to 850 errors**, with **7 suppressed**; the goal remains open. App
import/OpenAPI passed with 564 schemas. Local per-event cost, median of five
100,000-iteration samples with 960-byte PCM: construction 0.605 microseconds,
native revalidation 1.147 microseconds. This is not a service-latency benchmark.

Milestone review, performed in order:

1. DDD: handoff product identity stays in pipelines; normalized events stay in
   sockets; SDK objects stay in the Gemini adapter. Framework imports stay neutral.
2. Architecture: existing dispatch, pinned voice authority and resource ownership
   remain; no second state machine, persistence lane or credential authority.
3. Data flow: exact wire parity, malformed-result refusal, actor transitions,
   duration units, fragment accumulation, audio rates and teardown were checked.
4. Plan: advances F2 and the connected F7a boundary. Canonical tool-content,
   realtime session/provider material and the remaining F3–F10 flows stay open.
5. Maintainability/security/performance: explicit variants replace generic handlers;
   callback failures log types only. No additional DB/vendor calls, dependency
   change, casts or type suppressions. Hot-path validation cost is measured above.

No live provider/DB mutation, deployment, migration, UI QA, commit, history rewrite
or permanent probe file. Next: realtime session/capability contracts, then each
vendor's remaining request/response flow and its effective provider material.

#### Realtime session and capability contracts — verified F7a continuation

Trace: configured provider → browser/verification/capability builder → normalized
session snapshot → explicit factory → adapter setup/update → public capability
projection. This continues the connected realtime flow, not a dataclass sweep.

Baseline reproduction established three defects: `max_tokens=True` became `1`,
post-construction assignments escaped validation, and an OpenAI update changed the
prompt before rejecting its unsupported temperature. Gemini also disconnected
before validating a proposed replacement. No live incident is inferred from these
controlled inputs.

- Session config is frozen Pydantic with strict finite numeric settings, positive
  counts/durations and explicit vendor, endpointing and compression choices.
  `updated()` validates a complete replacement; original snapshots stay unchanged.
  Factory, manager and adapter construction revalidate copied snapshots. Tool
  records retain their live identity through an explicit instance-checked port.
- All three adapters validate updates before mutation/disconnect/send. OpenAI
  commits local replacement only after send succeeds; this is not a vendor
  acknowledgement or distributed-transaction guarantee. Gemini/Nova retain the
  existing reconnect lifecycle, with invalid replacements refused before closing.
- Capabilities use a frozen Pydantic model, support enums and a session-update enum.
  Native callers compare enum members; public projections retain exact existing
  booleans, mode strings and rate arrays. STT's separate representation is unchanged.
- Nova setup reads named typed fields directly, removing reflective getters.
  Required settings are checked before sending; endpointing serializes its native
  value, not the Python enum name. Provider-specific catalog/range policy remains
  with the existing module/adapter owners.

Executed: **417 config/adapter/projection assertions**, plus **30 browser setup
assertions** using actual session state, context, manager, factory and adapter
constructors for all three vendors. DB context/fact services and connection I/O
were substituted. **363 normalized-event assertions** and **348 handoff assertions**
passed again. The extra event assertion checks direct config mutation is now refused.
All five expanded local type/import hooks pass; full Pyrefly remains **850 errors,
7 suppressed**. Browser orchestration contributes 133 known diagnostics and is not
claimed clean; no diagnostic points at the changed realtime contracts.

Continuation review checked (1) module-to-socket enum translation, (2) preserved
factory/resource ownership, (3) all setup/update/projection consumers and failure
effects, (4) F7a alignment with the full F0–F10 goal, and (5) local readability and
wire compatibility without new dependencies, casts, suppressions or network work.
Frozen models are shallow: tool objects remain live references and do not become
persisted or authorized merely by passing config validation.

Final gates: full server/CLI Ruff, selected formatting and `git diff --check`
passed. App/OpenAPI: 564 schemas. Documentation verification: 46 pages, 282 links,
90 packages, 1,146 Python modules, 6,046 docstrings and 47 diagrams.

Still open: effective realtime provider settings/credentials, native OpenAI/Nova
request/response schemas and state, broader browser-session typing, then the
remaining F2 caller and F3–F10 flows. No live vendor/DB operation, UI QA, deployment,
migration, commit, history rewrite or permanent probe was performed.

#### Effective realtime provider material — verified F7a continuation

Trace: voice-config create/read → effective current/pinned provider record →
`ResolvedRealtime` → browser/verification/capability session builder → explicit
factory → selected adapter. All three realtime branches use the same field-based
projection; this is not a broad dataclass or string-replacement sweep.

Baseline constructor probes reproduced two defects: a frozen resolved dataclass
still allowed its settings dict to mutate, and `from_provider_config()` accepted
caller org/config IDs that disagreed with its effective record. Evidence is local
constructor behavior, not a demonstrated live tenant leak. Resolution now rejects
those mismatches, including a non-realtime capability, before returning material.

- `RealtimeInferenceConfig` owns strict finite scalar settings and the existing
  endpointing/compression enums. Session config inherits these fields rather than
  maintaining another copy. Provider-specific catalog/range policy stays in the
  voice-config module; module/socket provider enums remain separate.
- `ResolvedRealtime` is frozen Pydantic with strict IDs, revision and predicates;
  nested settings and credentials revalidate copied instances. Credentials use
  explicit API-key/AWS models and are excluded from repr and serialization.
  The factory reads typed credential fields, never guessed secret keys.
- Runtime hydration translates the persisted compression name once. Stored
  settings/secret JSON remains unchanged, including optional values and normalized
  AWS region behavior. The generic `VoiceProviderConfig` storage carrier remains a
  mapping-based dataclass pending its connected STT/TTS work; hydration revalidates
  it rather than assuming its earlier validation still holds.
- One pipeline-owned `build_realtime_session_config()` replaces the three repeated
  dictionary projections. It checks org agreement and preserves the configured
  model, voice, generation and turn-detection fields. Browser initialization now
  explicitly refuses a missing agent identity before allocating session resources.
- Current/pinned resolver error translation, grant/ready predicates, feature gate,
  factory selection, verification timeout and teardown ownership remain unchanged.

Executed: **360 resolved-contract/flow assertions**, **417 existing realtime
config/adapter assertions**, **363 event/control assertions**, and **39 browser
initialization assertions** — **1,179** total. Fixtures use real domain, service,
resolver, session, manager and adapter constructors; persistence and network ports
are substituted. Coverage includes stored-field parity, pinned revision forwarding,
malformed values, identity mismatches, copied-invalid credentials, secret exclusion,
and verification success/failure/cancellation cleanup. Function-contract checks are
not live-provider, database, microphone or human product QA.

One milestone review checked, in order: (1) DDD import boundaries, (2) shared
inference ownership and pipeline composition, (3) all producers/consumers and
secret/error projections, (4) F7a alignment without narrowing the F0–F10 goal, and
(5) readability, removed mapping access and bounded startup-only validation.
No SDK, dependency, DB operation or per-audio-packet work was added.

Five expanded type/import hooks pass. Whole-project Pyrefly remains **850 errors,
7 suppressed**; broader browser/session work remains open. App/OpenAPI imports
with **564 schemas**. No casts or diagnostic suppressions were added.
Full server/CLI Ruff and `git diff --check` pass. Eight selected files pass format
checking; `browser.py` retains two verified pre-existing formatting differences
outside this increment and its **133** baseline diagnostics. Documentation checks:
46 pages, 282 links, 90 packages, 1,146 Python modules, 6,052 docstrings, 47 diagrams.

Next at that checkpoint: native realtime OpenAI/Nova request/response schemas and state, then remaining
F7 provider and F2 caller flows in the established F0–F10 plan. No deployment,
migration, DB mutation, commit, history rewrite or permanent probe file.

#### Native OpenAI realtime wire contracts — verified F7a continuation

Trace: configured session/tools/audio → native SDK client event → WebSocket JSON →
validated native server event → adapter stream correlation → normalized realtime
event → manager dispatch → transcript capture, audio playback/recording or tool
execution scheduling. The same parser validates credential-verification acks.

Target: installed and pinned OpenAI **2.14.0**, Pydantic **2.11.10**. Inspected SDK
request/event classes and the current [official function-calling flow](https://developers.openai.com/api/docs/guides/realtime-conversations#function-calling).
No model, dependency, provider setting, public schema or DB contract was upgraded.

Baseline probes reproduced malformed function JSON being replaced with an
executable empty argument object, and a valid `code: null` vendor error failing
normalized-event construction. Those were unchecked wire-read assumptions, not
required fallback behavior. They are now refused/preserved respectively.

- `openai_wire.py` reuses SDK event models in an explicit discriminated union.
  The adapter-owned session notification adds the server ID absent from the SDK's
  shared request type. Terminal notifications require an ID, terminal status and
  output collection; an empty response object is not completion evidence.
- Unknown/unused event types remain ignorable. The three existing legacy audio
  labels normalize once at ingress. Known events require their native fields;
  missing transcripts, IDs and acknowledgements are not synthesized.
- JSON parsing rejects non-object inputs, non-finite constants and overflowing
  exponents before SDK/model consumption. A probe caught Pydantic JSON adapter
  configuration not rejecting `NaN`; relying on a later normalized-model failure
  would have left the boundary inconsistent. Base64 is validated too.
- Requests use native SDK objects, including session/VAD/audio settings, partial
  updates, flat function declarations and tool-result continuation. They are
  revalidated before serialization. Omission, empty instructions and empty tool
  lists preserve their previous meaning; failed sends retain the old config.
  The configured model is URL-encoded as one query parameter, not interpolated
  into query syntax.
- Pending tool state uses Pydantic identities tied to response and item IDs.
  Argument completion must match that identity before dispatch. Consumed or
  terminal-response identities are released; output-item completion does not
  reinsert already-consumed calls. Disconnect clears state even when close raises.

Executed: **267 native wire/function assertions**, plus **12 additional
native-to-manager capture assertions** (the latter harness also reruns 269 base
contract assertions). Recorded transport input reaches the real manager, live
transcript buffer, resampler, playback queue and recording tap. The tool executor,
transcript publication and fatal teardown effects are controlled ports; actual
dispatch/task ownership is exercised. Invalid arguments cause fatal teardown and
never invoke the tool executor. Existing **417 config** and **363 event/control**
assertions also pass; native fixtures now include required vendor fields instead
of private minimal dictionaries. Output expectations were retained.

Performance probe: JSON parse plus audio-event normalization for a 960-byte PCM
frame, median of five runs of 10,000 iterations, measured **7.755 μs before** and
**15.573 μs after** on the local environment. This measures validation overhead,
not provider latency, microphone quality or production throughput.

One milestone review, in order: (1) vendor/platform/framework import boundaries,
(2) native schema ownership within the existing socket, (3) request/event/tool
and error paths through manager sinks, (4) F7a alignment without narrowing F0–F10,
(5) readability, nullable/error handling, state lifetime and measured hot-path
cost. No casts, `Any`, diagnostic suppressions, new task lane or DB work added.
Five type/import hooks pass; the new parser is included in the voice hook.
Whole-project Pyrefly remains **850 errors, 7 suppressed**; scoped gates do not
prove whole-platform completion. App/OpenAPI import retains **564 schemas**.
Full server/CLI lint and changed-source format checks pass.
Documentation verification passes: 46 pages, 282 links, 90 packages, 1,147 Python
modules, 6,061 docstrings and 47 diagrams. `git diff --check` passes.

Remaining: native Nova wire schemas/state, connected STT/TTS provider material,
other F2 producers/callers and F3–F10 flows. This is recorded-transport function
verification, not live OpenAI/microphone/UI QA or human acceptance. No deployment,
migration, operator DB mutation, commit, history rewrite or persistent probe.

#### Native Nova Sonic wire and stream contracts — verified F7a continuation

Trace: configured inference/voice/tools → typed JSON input events → native SDK
input chunks → SDK output/error union → validated Nova event → content/tool
identity → normalized event → real manager dispatch → transcript, audio and tool
sinks. Reconnect history and cancellation cleanup are part of this same flow.

Target checked on 2026-09-08: pinned/installed AWS Bedrock Runtime **0.7.0**,
Smithy Core **0.6.0**, Pydantic **2.11.10**. Inspected the installed duplex stream,
receiver EOF contract and output variant definitions alongside AWS's
[input events](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-input-events.html)
and [output events](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-output-events.html).
No dependency, model, provider configuration, API schema or DB change.

Baseline function probes reproduced three defects despite the adapter's previous
zero-error scoped type check: malformed JSON became an executable empty argument
object; SDK EOF `None` caused another receive; cancellation during preamble setup
left the opened stream attached and unclosed. Loose dictionaries, `Any` and
reflection obscured the actual SDK contracts. These were implementation gaps,
not product-approved fallback or lifecycle behavior.

- `amazon_nova_sonic_wire.py` owns explicit request, response, nested metadata,
  usage and protocol-failure contracts. Vendor enums stay inside the socket.
  Tool JSON Schema/argument contents remain legitimately dynamic JSON objects.
  Known responses require native identifiers and fields; unknown event names are
  ignored. A wrapper containing multiple events is rejected, not partially read.
- Native SDK generic stream/result types replace `Any`. SDK error variants use
  explicit type branches, not class-name parsing or reflective attribute access.
  Public normalized errors retain safe codes, without raw vendor message data.
- Content state retains validated start metadata. Prompt/session/completion and
  content type must agree before audio, text or tools are consumed. Requested
  output rate remains 24 kHz. Malformed base64 follows the existing recoverable
  audio-error path; malformed tool JSON is fatal and cannot execute a tool.
  Non-object, non-finite and overflowing numeric tool arguments are refused.
- Actual `completionStart`/usage notifications provide session identity. No
  fabricated `sessionStart` output or invented JSON error event is needed.
  Final versus speculative text, policy-input suppression and first-user replay
  preserve their existing semantics. Tool results require a pending call, retain
  the existing JSON result envelope and use one ordered content batch.
- EOF returns to the manager's existing transport-ended lifecycle. Late reads
  after disconnect/generation replacement cannot produce effects.
  Output acquisition, receives and close operations each retain their real
  result type. Cancellation does not reach AWS CRT response futures.
  Failed setup also closes a subsequently acquired output receiver.
  Caller close wait is bounded at ten seconds; a stalled SDK close remains
  tracked, shielded and reported as unfinished background cleanup, not success.

Executed: **696 native contract/function assertions**, plus **14 additional
native-to-manager assertions** (the manager harness also runs 269 base contract
assertions). Real SDK chunk/stream classes and the actual manager, live buffer,
resampler, playback queue, recording tap and tool task scheduling are exercised.
Network, tool execution, transcript publication and terminal owner effects are
controlled ports. EOF also runs through the real manager event loop to its
transport-ended teardown call. Late output acquisition and caller cancellation
tests confirm eventual receiver close without cancelling SDK futures.

Existing **417 config**, **363 event/control**, **360 resolved-material** and
**267 OpenAI-native** checks pass. Nova fixtures now contain the documented
identities/content metadata and actual SDK error variants; normalized output
expectations are preserved. No permanent test suite or temporary probe file.

Performance: parsing/normalizing a 960-byte PCM frame, median of five runs of
10,000 iterations, measured **6.055 μs before**, **14.441 μs after** locally.
This includes strict validation/content correlation, not network, microphone,
production load or end-to-end latency.

One milestone review followed the required order: (1) DDD/vendor/framework
boundaries, (2) fit within the existing socket/manager, (3) source-to-sink data and
cleanup ownership, (4) F7a alignment and Pydantic-first correction without
narrowing F0–F10, (5) readability, safe errors, state lifetime and measured
hot-path cost. Its late-receiver cleanup finding was fixed and rechecked.
No casts, new `Any`, suppressions, DB transactions or task lane were added.

Five expanded type/import hooks pass; the new wire module is in the voice hook.
Whole-project Pyrefly remains **850 errors, 7 suppressed**. App/OpenAPI imports
with **564 schemas**. Full server/CLI lint and changed-source formatting pass.
Documentation verification passes: 46 pages, 282 links, 90 packages, 1,148 Python
modules, 6,071 docstrings and 47 diagrams. Changed-source format checks and
`git diff --check` pass.
This is local recorded-transport verification, not live AWS, microphone/UI QA or
new human product acceptance. The whole-platform goal remains active.

Next: connected STT/TTS provider material and native provider flows, remaining
F2 producer/caller contracts, and the rest of F3–F10. No deployment, migration,
operator DB mutation, commit, history rewrite or dependency upgrade.

### F4 progress: Bedrock embedding native boundary

2026-09-09: followed verification and runtime resolution through the embedding
factory, Titan V2 invocation, stream decoding, vector validation and the shared
Knowledge/Memory embedding runtime. Native contracts now live in
`sockets/embedding/vendors/bedrock_wire.py`; vendor errors translate to the neutral
`EmbeddingErrorCode`. OpenAI/Voyage error producers and the runtime dimensional
guard also retain this enum, preserving public strings and retry decisions.

Evidence ledger:

| Operation | Authority and contracts | Consumer/proof | Still unverified |
| --- | --- | --- | --- |
| Titan V2 `InvokeModel` | Installed aioboto3 15.5.0, aiobotocore 2.25.1, botocore 1.40.59; [V2 JSON](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html), [InvokeModel](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html); `TitanEmbeddingRequest`, `BedrockInvocationResponse`, `TitanEmbeddingResponse`, `BedrockErrorResponse` | Factory → SDK operation → actual `StreamingBody` → vector → `EmbeddingRuntime`; real verification caller exercises both intents | Live AWS invocation, configured-org KB/Memory ingestion and DB index readback |

94 temporary function assertions pass: request spelling and privacy, copied invalid
requests, supported dimensions, missing/malformed native fields, non-finite vectors,
typed error/retry classification, sequential input correspondence, empty batch,
cancellation and client exit, runtime and verification formation. The actual SDK
Stubber validates operation parameters without issuing an AWS request. Neutral
error regressions cover the OpenAI and Voyage classifiers; they do not establish
those vendors' native request/response completion. The existing one-request-per-text
behavior, semantic options and coordinate-space identity remain unchanged.

The embedding socket/shared-contract/runtime type gate passes without suppressions.
At this point verification still had two diagnostics from a dataclass declaring
`provider` as enum-or-string while construction replaced it with an enum. The
following authority slice resolves these without casts. Native OpenAI/Voyage
embedding bodies, reranking, durable index readback and changed-image product QA
remain open. No dependencies, DB, configured providers or running services changed.

### F4 progress: embedding material, identity and verification handoffs

2026-09-09: embedding settings and credentials now use provider-owned Pydantic
objects through validation, service creation, effective config resolution and
socket construction. `from_input` replaces the old dataclass `validate` factory;
all consumers use it. Scalar `config`/`secrets` mappings remain explicit projections
for the shared persistence service, preserving stored field names and omissions.
Credential objects and the live adapter are excluded from dumps/representations.

Endpoint policy, resolved authority, runtime handles and verification receipts
are also Pydantic models. Provider identity stays an enum. Known verification
metadata uses attributes; JSON extensions remain supported with read-only mapping
bindings. Metadata and settings are copied on validation, not recursively frozen.
Resolved snapshots check organization, config ID and capability agreement with
`EffectiveProviderConfig`; runtime construction revalidates copied snapshots.
Verification rejects invalid/mismatched provider receipts before the write while
keeping provider I/O outside transactions.

86 function assertions pass across OpenAI, Voyage and Bedrock material: mapping
projections, normalization, secrets, invalid/cross-provider copies, strict revisions
and flags, wrong authority identity, allowlisted custom endpoints, runtime handles,
metadata and verification guards. Actual lifecycle/verification services are used
with DB/provider effects substituted. The 94 native Bedrock regression assertions
remain passing, including its actual SDK Stubber path. No live AWS or index DB
readback proof is implied.

The probe exposed the exact foundation input shape: `MappingProxyType`. Strict
Pydantic models reject that directly; field parsing now makes a plain mapping
copy before validating typed settings/credentials. The first probe also omitted
the required foundation capability field; that fixture was corrected separately.
The expanded gate covers the complete embedding config module, native socket
directory, runtime resolution, translation and verification, with no suppressions.
Broader embedding deletion-reference typing remains outside this gate. Native
OpenAI/Voyage bodies are addressed below; retrieval persistence and full F0–F10
completion remain open.

### F4 progress: OpenAI and Voyage embedding HTTP boundaries

2026-09-09: traced config → adapter batch → actual SDK/HTTP request → indexed vector
validation. Vendor-owned request and consumed-response models now live in
`openai_wire.py` and `voyage_wire.py`. Voyage no longer selects response dictionary
keys or drops non-object entries. OpenAI revalidates SDK model attributes rather
than relying on the SDK's permissive object construction. SDK types remain inside
the adapter; the runtime still receives the neutral vector contract.

Authority: installed/pinned OpenAI 2.14.0, installed HTTPX 0.28.1 and Pydantic
2.11.10; [OpenAI create embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create),
[Voyage text embeddings](https://docs.voyageai.com/reference/embeddings-api).
The installed SDK source confirms its implicit base64 request and decoding step;
that behavior is retained, as are existing batch sizes, exact endpoint selection,
Voyage intent/no-truncation policy and semantic identity. Unused response metadata
is not required merely because the native vendor documents it.

229 temporary function assertions pass using the actual OpenAI SDK over HTTPX
MockTransport and Voyage's actual HTTP client path. Coverage includes exact request
payloads, batch boundaries/order, missing/duplicate/boolean/string indices,
non-numeric and empty vectors, inconsistent dimensions, malformed/empty payloads,
copied invalid models, private snapshots, base64 decoding, HTTP failure categories,
transport failures and cancellation/client closure. No vendor calls or DB writes.

The probe found an SDK pre-validation path: malformed list entries raise an
attribute error in OpenAI's base64 post-parser before Eylo sees the response.
Decoding errors are now normalized at that SDK invocation boundary as retryable
`invalid_response`, not generic non-retryable provider errors. The regression failed
for this exact case before the fix. A separate fixture mistake supplied a nonexistent
`vendor` field to `EmbeddingConfig`; the fixture was corrected without changing
that public contract. Response validation and status classification retain typed
error codes; HTTP status comparisons use `HTTPStatus`.

The complete embedding type gate passes without suppression. All eight local
typed/import hooks pass (the LLM hook retains its existing one suppression).
Native Bedrock's 94 assertions and material/verification's 86 assertions pass
alongside this slice. Full backend lint and documentation validation pass: 46
pages, 284 links, 90 packages, 1,176 Python modules, 6,181 docstrings, 47 diagrams.
Live vendor calls,
Knowledge/Memory persisted index readback, remaining F4 ownership contracts and
changed-image product QA are still required. No dependencies, migrations, operator
configuration, deployment or Git history changed.

### F4 progress: persisted embedding identity projections

2026-09-09: traced active/source/target identity reads through Knowledge ingestion,
runtime resolution, reindexing and Memory formation/reconciliation/reindexing.
`embedding_records.py` now declares Pydantic row projections with the exact
persisted fields. The three readers validate ORM input at that boundary, then
read typed attributes. The old arbitrary prefix and interpolated `getattr` names
are gone. Semantic-options columns in Knowledge/Memory models now declare
`dict[str, JsonValue]`; their explicit JSONB types, nullability and DDL are unchanged.

The restoration boundary validates complete configured identity with strict scalar
types, then verifies the existing hash. A complete nullable projection with no config
still returns no space. Missing fields, boolean/string revisions or dimensions,
wrong field families and corrupt hashes fail validation. Config/revision remain
execution identity and are not added to coordinate-space hash inputs. No database
queries/writes, lazy relationship traversal, or new migration is introduced.

An initial read-only Protocol design failed against SQLAlchemy descriptors in the
installed Pyrefly checker (`organization_id` descriptor mismatch). It was replaced,
not cast or suppressed: untrusted ORM input is validated once into a detached
Pydantic projection. Typed domain code does not receive an unchecked object.

276 temporary function assertions pass across 14 real ORM/prefix combinations:
registered SQLAlchemy mappers, actual column existence/JSONB types, active/source/
target projections, nullable state, invalid scalar types, missing authority,
cross-org/hash mismatches, copied-model revalidation and isolation from mutable
source mappings. These are real model/transform proofs, not DB round trips or live
index readback. Native Bedrock and material/verification regression probes are
also rerun. The local embedding hook includes the new projection and Knowledge/
Memory owner model files; the Knowledge job file retains four pre-existing
storage-authority diagnostics and is not advertised as type-clean.

The broader Knowledge/Memory module and pipeline check has 67 diagnostics before
and after this change; normalized comparison shows no added/removed diagnostic.
Those remaining caller, repository, storage-authority and durable execution issues
remain part of the full hardening objective. Typed persistence producers, DB
readback, reranking and changed-image QA remain open. No operator data, provider
config, migration, dependency, deployment or Git history changed.

### F4 progress: embedding identity writers and cutover

2026-09-09: Knowledge ingestion/reindex and Memory reindex writers now construct
active/source/target records through explicit `EmbeddingSpace` projection methods.
`to_columns()` is the serialization boundary for ORM constructor and SQL-update
kwargs, excluding the tenant column that remains owned by the service. It is not
a new dynamic domain dictionary. Input space instances are revalidated before
projection; incorrect values introduced with `model_copy` cannot bypass that guard.

Both reindex services no longer generate column names from a prefix or mutate
records using `setattr`. Staging, active assignment and clearing name actual model
attributes. Memory's assignment helpers do not own lifecycle policy; existing
service branches still decide required/active state, recovery and emitted events.
The existing transaction scope, flushes, cutover SQL and failure classes remain.

348 temporary function assertions pass, including the prior 276 read checks.
New coverage proves projection → actual ORM → restored-space round trips, exact
PostgreSQL UPDATE parameter names, UUID preservation, detached JSON, invalid
copied input refusal before assignments, complete target clearing, stage/cutover,
and the actual Memory `record_verified_space` branches with DB/event effects
substituted. Empty Knowledge ingestion projection remains empty. Source/target job
payloads preserve all existing column names and values.

Two probe assumptions were corrected from source evidence: SQLAlchemy adds the
existing `updated_at` on-update binding; missing reindex targets raise the existing
Knowledge/Memory domain errors rather than `ValueError`. Neither required a product
change. The 86 material/verification and 94 native Bedrock regression assertions
pass. All eight local typed/import hooks and full backend lint pass. The broader
Knowledge/Memory check still has the same 67 diagnostics after normalizing line
offsets, with none added or removed by this slice.

This does not prove a live worker cutover or persisted pgvector readback. Remaining
Knowledge/Memory diagnostics, further persistence producers, reranking and
changed-image end-to-end QA remain in F4/full-platform scope. No dependency,
migration, deployment, operator DB/provider data or Git history changed.

### F4 progress: Knowledge storage-authority restoration

2026-09-09: The shared corpus/upload-job restoration helper now explicitly
narrows nullable storage fields before constructing `StorageAuthority`. Inline
text jobs intentionally have no storage authority and are refused with the
existing `InvalidStorageLocator` family. Valid rows retain the canonical UUID,
revision, provider, location and key validation. The two JSONB authority columns
now declare `dict[str, str]`; column types and nullability are unchanged.

49 temporary function assertions pass with actual corpus/job ORM instances:
complete authority, absent fields, malformed UUID/revision/provider/location,
detached location mappings, locator identity and invalid object keys. The probe's
initial model-registration import was corrected to `eylo.common.models` from the
existing verified harness; no application import path changed.

The Knowledge jobs file is now included in the local embedding type gate. All
eight typed/import hooks and full backend lint pass. The broader Knowledge/Memory
check drops from 67 to 63 diagnostics. This slice does not prove a live object
download or DB readback; remaining diagnostics and changed-build QA are pending.
No migration, operator data, provider config or deployment changed.

Browser smoke QA used the existing Eylo Development org and its configured
`QA Core Mixed Agent`. The widget issued `memory_recall` and displayed the answer;
the console conversation `01a084d2-ce00-77d1-9be8-ca04ff4a0908` shows the completed
tool call/result, Bedrock reranking applied, and completed background task/result
(seven persisted messages). Console session expiry redirected to login; signing
in restored the conversation-list destination. Only a QA conversation/messages
were added. This exercises the already-running image, not the edited backend.

### F4 progress: Memory recovery contracts

2026-09-09: `MemoryError` now accepts `MemoryRecoveryPolicy` rather than a
retry-policy boolean. `TERMINAL` retains the existing default; explicit transient
paths use `RETRY`. All Memory constructors in pgvector, dependency resolution,
recall, reconciliation and formation were migrated. The read-only `.retryable`
projection preserves existing worker classification. Embedding-to-Memory policy
translation remains at the pipeline boundary; neither capability imports the
other's policy. No retry timing, attempts, transaction or persistence schema
changed.

The formation/reindex/recall pipeline imports now use the established
`MemoryProviderError` alias. This removes a Pyrefly collision with the Python
built-in `MemoryError`, not a runtime import bug: probes establish the alias is
the canonical domain class and allocation errors remain internal failures.

73 temporary function assertions pass with actual exception contracts, embedding
runtime, ORM rows and worker functions. Coverage includes enum refusal,
terminal/retry classification, stale reconciliation classification, document and
query embedding translation, safe messages, cancellation propagation, and failure
recording/reservation release/transaction exit before a worker retry is raised.
DB/service/provider effects were substituted; this is not live retry/restart QA.

A new local type hook covers the Memory contract, socket exports, resolver and
reindex worker. All nine typed/import hooks and full backend lint pass. The broad
Knowledge/Memory region has 58 remaining diagnostics, down from 63. Remaining
worker watermark types, optional index authority, cursor-result contracts,
provider payload work and rebuilt-image QA still belong to the full objective.

### F4 progress: required Memory index authority and typed reindex facts

2026-09-09: The Memory reindex service separates `_find_index` (optional) from
`_require_index` (returns an index or raises the existing domain error). Required
callers no longer inherit a nullable return type from a boolean flag. A private
`_IndexLock` enum replaces independent shared/exclusive booleans; tenant/config
filters and transaction ownership remain unchanged.

`ReindexFact` is now a strict frozen Pydantic object, not a dataclass. DB rows are
validated directly; copied objects are revalidated before vector writes. UUIDs,
text and positive state revisions retain their meaning rather than being coerced.
Content is excluded from repr. SQL staging requires a `CursorResult` with a zero
or one affected-row count; cutover requires a reported count equal to source
facts. Unknown result/count shapes refuse activation, including an unknown count
for an empty source.

134 temporary function checks pass: actual ORM models, PostgreSQL query
compilation, SQLite-produced SQLAlchemy rows/results, optional/required lookup,
all lock modes, invalid lock refusal, copied fact refusal before DB calls, and
staging/cutover outcomes with service DB effects substituted. The existing writer
probe was updated to substitute `_find_index` rather than the removed `_index`;
its 348 assertions still pass. No production test suite was added.

The complete reindex service is now part of the Memory type hook. All nine local
typed/import hooks pass. Knowledge/Memory diagnostics drop from 58 to 39. Live
PostgreSQL reindex/cutover remains unproven by these function checks; operator
data, providers, migrations and deployment were untouched.

### F4 progress: formation watermark contracts

2026-09-09: Formation message positions and cancellation results are frozen
Pydantic objects rather than dataclasses. Positions require timezone-aware
timestamps and UUIDs; their explicit order key preserves timestamp/UUID ordering.
Requested/processed selection uses `_CursorWatermark` instead of a boolean.

Python restoration now matches the existing DB pair invariant: both absent means
empty; a half-present timestamp/ID pair is refused. Previously the cursor helper
treated either missing field as an empty watermark. Requested-position assignment
revalidates copied objects. Job range loading validates its bounds before opening
a read transaction. SQL tuple bounds use `literal()` parameters with unchanged
exclusive-start/inclusive-end semantics. No ordering guarantee for platform
events was added; this concerns only deterministic DB message pagination.

65 temporary function assertions pass against actual ORM models, Pydantic values
and PostgreSQL query compilation. Coverage includes timestamp/UUID tie-breaks,
timezone equivalence, incomplete pair refusal, invalid selection, copied object
refusal, cursor advancement fences, range limits and refusal before DB reads.
Query execution was substituted; live worker replay is not proven by this probe.

The formation worker is included in the Memory type gate. The broad
Knowledge/Memory check drops from 39 to 29 diagnostics. Full backend lint passes.
Remaining query/return contracts and provider payload work stay open under the
platform-wide objective. No migrations, operator data or deployment changed.

### F4 progress: operator Memory query contracts

2026-09-09: The operator service uses an explicit `AsyncSession` and boolean SQL
expression list. Its internal `list` method is named `list_memories` so it no
longer shadows the built-in collection type in later annotations. The route
calls the renamed method; public paths, filters, pagination and responses are
unchanged. Both files are included in the Memory type gate.

64 temporary function assertions pass: resolved annotations, tenant-scoped SQL,
lifecycle/recall/content/integrity filters, wildcard escaping, all sort/direction
pairs and empty-page projections. PostgreSQL query compilation uses real models;
DB execution and integrity lookup are substituted. This is not live DB evidence.
The broad Knowledge/Memory check drops from 29 to 22 diagnostics; remaining
reconciliation, Knowledge query and result contracts are still open.

The existing console and widget were reachable with the Eylo Development session.
Memory list navigation loaded the saved facts. A read-only widget query with
QA Core Mixed Agent called `kb_query`, returned the configured Knowledge result
with Bedrock reranking and citation `K1`, and did not substitute a remembered
fact for absent document evidence. Conversation
`01a084d2-ce00-77d1-9be8-ca04ff4a0908` displayed all 14 persisted messages in
completed states, including the tool and background-task results. This is a
baseline check of the running image, which predates the current backend edits;
it does not prove deployment of the operator-contract change. No provider
configuration or source data was changed by the QA request.

### F4 progress: reconciliation positions and effect contracts

2026-09-09: Reconciliation positions and counts are frozen Pydantic models.
Positions preserve timestamp/UUID ordering through an explicit order key;
requested/processed cursor selection is an enum. Job ranges reject incomplete
pairs and non-advancing bounds before reading changes. SQL tuple bounds use
typed `literal()` parameters. Partition helpers have explicit cursor/job types
and ORM owner-column selection, replacing dynamic attribute lookup.

Related-fact revision objects remove nullable identity/revision values from
effect-set and revision-fence consumers. Batches, candidates, inputs, settlements,
decisions and proposals revalidate copied model instances at persistence and
application boundaries. Valid wire/persisted JSON remains unchanged. This does
not add a vendor type, migration, reconciliation policy or event ordering promise.

149 temporary assertions pass against actual Pydantic/ORM objects and compiled
PostgreSQL queries. They cover malformed/copied contracts, exclusive/inclusive
bounds, all owner scopes, partition filters, stale/repeated revisions, all four
decision outcomes through `apply`, expiry direction, relationship endpoints,
cursor advancement and completed-job replay. DB execution, work receipts and
event delivery are substituted; live worker/DB application remains unverified.
The existing 73 Memory recovery assertions also pass.

The reconciliation contract/service join the local Memory gate. The broader
Knowledge/Memory check drops from 22 to 8 diagnostics, all in Knowledge paths:
worksheet typing, DML row counts, storage-key narrowing and query-result handling.
Zero Memory diagnostics is not a claim that every Memory payload boundary or
the platform-wide typing objective is complete.

### F4 progress: Knowledge query, extraction and DML contracts

2026-09-09: The eight remaining diagnostics in the Knowledge/Memory module and
pipeline check are resolved. Knowledge searches snapshot ID/name into typed
Pydantic work objects rather than retaining ORM rows after the configuration
transaction. Query observation and deletion/reindex result dataclasses are also
Pydantic models. Invalid scope filters raise a local parse error instead of
returning a boolean sentinel; public error payloads and empty-scope semantics
remain unchanged.

A function probe reproduced a cancelled adapter search becoming `TypeError`:
the gather-result loop excluded only `Exception`, then tried to iterate the
returned `CancelledError`. Non-ordinary exceptions now propagate; ordinary
provider errors still produce the established unavailable/degraded result.

Storage fetch/extraction uses the validated locator key. OpenPyXL read-only
worksheets reuse `Worksheet` methods without subclassing it, so extraction uses
a small runtime-checked public value interface instead of suppressing the
incompatible inferred self type. Reindex chunks validate actual SQLAlchemy rows
and copied objects before staging. Staging requires a cursor result with count
zero or one; deletion requires known nonnegative counts before its event.

66 query/extraction/storage assertions pass, covering exact cancellation,
ordinary failures, empty/invalid scopes, citations, real in-memory XLSX parsing,
workbook closure, storage bytes and missing-key refusal. 45 DML assertions use
actual SQLAlchemy rows/cursors produced by disposable in-memory SQLite plus
PostgreSQL query compilation. Service DB/vendor effects are substituted; these
are not live PostgreSQL deletion, cutover or vendor-query proofs. The 348
embedding writer/read regression assertions also pass. All ten typed/import
hooks, full backend lint and the documentation verifier pass.

The full Knowledge module/pipeline check joins a local pre-commit/pre-push gate.
The broader Knowledge/Memory module/pipeline check reports zero diagnostics.
This is a diagnostic milestone, not full F4 completion: loosely typed query
payloads, socket dependencies and remaining config/vendor contracts still need
data-flow hardening and current-image integration QA. No schema, deployment or
operator configuration changed.

### F4 progress: typed Knowledge result and citation flow

2026-09-09: `pipelines/knowledgebase/query_contracts.py` now owns frozen Pydantic
candidate, citation, result, observation and response objects. Adapter output
is converted before interleaving/reranking; granting KB identity remains the
authority for each result. Final citation labels follow result ordering, and
reranking records the original retrieval score without mutating candidates.
The public query wrapper serializes once at the agent-tool boundary and emits
the separately typed observation. No new vendor/platform dependency was added.

112 temporary assertions pass: the prior 66 query/extraction/storage checks plus
46 typed result checks covering round-robin ordering, top-k, reranked order,
retrieval provenance, citation labels, exact optional-field omissions, private
content representation, copied-model refusal, finite scores and observation
exclusion. Invalid adapter scores follow the existing per-KB unavailable path;
observation failure cannot fail retrieval. Probes use real models and functions
with DB, provider and event delivery I/O substituted. They are not current-image
live vendor evidence. Existing public field names and values remain unchanged.
All ten local typed/import hooks, full backend lint and documentation validation
pass. The Knowledge/Memory module/pipeline check remains at zero diagnostics.

Remaining F4 work includes socket dependencies and reranking/config/vendor
contracts. Zero diagnostics in Knowledge/Memory does not establish platform-wide
completion. Current-image browser QA remains an acceptance requirement; the
attempt following this slice was blocked by the locked Mac. No DB, migration,
provider configuration or deployment was changed by this slice.

### F5 progress: reranking result and recovery contracts

2026-09-09: traced shared reranking results through Bedrock/Cohere/Voyage adapters,
the bounded stage, Knowledge citations and Memory selection. The original
`RerankResult` accepted boolean/numeric-string inputs and negative indices;
its score could be mutated to NaN after construction. Existing native response
guards reject these raw responses, but the shared stage did not revalidate the
canonical score. This was a local contract gap, not evidence of live corruption.

Results and ranking metadata are now strict frozen Pydantic models, including
revalidation of copied instances. The bounded result dataclass is a Pydantic
model, and its stage validates the entire selection list before dereferencing
candidate indices. Invalid lists, counts, indices or scores retain explicit
degraded retrieval fallback. Ordinary unexpected implementation errors are not
blanket-swallowed. Cancellation still propagates.

Normalized adapter error codes, recovery policies, truncation policies and safe
ranking reasons are separate named enums. Bedrock native error classification
stays vendor-owned; no module/provider catalog leaks into sockets. Public
status/reason strings are unchanged, with read-only `retryable` and `truncates`
predicates for compatibility. Recovery policy does not add inline retries.

211 temporary function assertions pass: strict/copy/frozen result guards, every
normalized error/recovery mapping, HTTP and Bedrock error classification, exact
ranking metadata, candidate/content budgets, malformed response degradation,
real asyncio deadline and external cancellation, Memory fallback consumers, and
all three adapters' closure paths. HTTP/AWS, DB and provider I/O are substituted;
this does not establish live vendor or deployed-image operation. All 112 typed
Knowledge checks and 73 Memory recovery checks also pass.

The new reranking local hook covers common result/recovery contracts, socket
adapters, the bounded stage and Knowledge/Memory consumers. All eleven typed/import
hooks and full backend lint pass. The broader reranking config-region check has
the same four pre-existing provider-union diagnostics. Next: typed config and
resolved authority, then native request/response schemas and current-image QA.
No DB, migration, provider configuration or deployment changed in this slice.

### F5 progress: typed reranking config and resolved authority

2026-09-09: reranking settings, API-key/AWS credentials, endpoint policy,
verification metadata/results and resolved runtime authority now use frozen
Pydantic models. Provider choice has an exact enum type; constructors no longer
leave validated `enum | str` declarations behind. Builders consume typed fields
instead of string-key secret/config lookups. Flat persistence projections retain
the prior normalized shape, including omitted optional fields.

The resolver compares effective organization/config/capability against the
request, and checks a requested pinned revision. The pipeline independently
checks returned identity and observed endpoint/model before building the adapter.
Invalid copied material is revalidated. Credential fields and adapter objects
are omitted from ordinary nested dumps and representations; explicit secret
projection remains available only for the existing encrypted persistence path.
No endpoint allowlist or historical pinned-revision lifecycle rule was relaxed.

310 temporary assertions pass for baseline config-shape parity across all current
Bedrock model/region pairs, Cohere hosted/compatible endpoints and Voyage; strict
settings/credential separation; invalid/mixed/copied input; credential omission;
create/update refusal before persistence; endpoint/key replacement; owner/config/
capability/revision mismatch before adapter construction; typed verification and
public projections; provider I/O outside transactions; verification revision races
and cancellation. Actual functions and types execute with DB/provider I/O
substituted. They do not prove live provider acceptance or deployed behavior.

The 211 reranking result/recovery checks and 112 Knowledge regressions also pass.
The entire reranking config/pipeline/socket region now reports zero diagnostics,
down from four; the local gate covers that full region. All eleven typed/import
hooks and full backend lint pass. Next: native reranking request/response contracts
and remaining F5 retrieval adapters, followed by current-image product QA. No DB,
migration, configured provider or deployment changed in this slice.

### F7 progress: resolved STT/TTS material and shared construction

`common/contracts/speech_runtime.py` defines frozen Pydantic inference settings,
explicit option policies preserving existing JSON booleans, private credential
variants and a transport-only media contract. Provider-specific field membership,
requirements and overlapping native field types stay in `voice_configs/domain.py`.
`ResolvedSTT`/`ResolvedTTS` are validated models, not mutable mapping carriers.
Their secrets are excluded from nested representations/dumps and serialized only
at the existing adapter handoff. Stored settings retain their existing shape.

Resolution checks effective org/config/capability agreement and the requested
pinned revision. The same config/revision guard now covers realtime resolution.
Verification, capability inspection and browser/carrier construction share the
pipeline builders. Media overrides cannot replace credentials, model or language.
Runtime identity retains the owning provider enums and refuses mixed-org pairs.

Baseline function probes reproduced internal mismatched material acceptance and
unrestricted transport replacement of model/API key. Milestone review additionally
reproduced provider-incompatible `style`/`pitch` values reaching native constructors,
unnormalized copied AWS settings reaching runtime and a mismatched realtime pin
being accepted. These are internal contract weaknesses, not a demonstrated public
authorization bypass. Fixes reject those values before persistence/composition.
Provider typing follows [ElevenLabs settings](https://elevenlabs.io/docs/api-reference/voices/settings/get)
and [Murf customization](https://murf.ai/api/docs/capabilities/text-to-speech/speech-customization);
no vendor feature, model default or dependency was added.

Function QA: **1,245 material checks**, **21 real adapter constructors**,
**380 verification/capability/carrier checks**, and the existing **360 realtime
resolution checks** pass. Google construction uses a generated local service
account fixture and closes its transport; no token exchange or vendor request.
DB/service and connection ports are substituted. One initial realtime fixture
omitted required Nova settings; correcting the fixture exercised the intended
pin guard without weakening production validation.

One milestone review proceeded through DDD ownership, architecture fit, complete
material data flow, plan/Pydantic alignment, then maintainability/security/cost.
Validation is at config construction, not per audio packet; no DB transaction or
network call was added. Focused type checking and full server/CLI lint pass.
The generic stored carrier, native STT/TTS options/wire/events and remaining
F0–F10 requirements are still open. No DB mutation, migration, deployment,
dependency upgrade, commit, permanent probe or history rewrite.

### F7 progress: provider-config encryption and persistence

2026-09-09: the full `provider_configs` package and external-credential envelope
functions pass the expanded local type gate. `EncryptionContext` is frozen and
revalidated, with strict UUIDs, a caller-owned purpose label and positive revision.
Cipher payloads return finite JSON; provider secret validation remains at provider
readback. ORM config/metadata columns retain JSONB storage with precise value types.
Repository writes revalidate aggregates and use `UPDATE RETURNING` to verify the
affected identity, without changing their transaction ownership or lock predicates.

Two function-boundary defects were reproduced during this slice:

- Direct `JsonValue` JSON parsing accepted NaN/Infinity despite `allow_inf_nan=False`.
  Decrypted JSON and config snapshot imports now run Python-side finite validation.
- `decrypt_field()` decoded UTF-8 outside its error boundary. Authenticated malformed
  bytes now raise value-free `SecretDecryptionError`; text encryption also rejects
  invalid input types/encoding through its established error class.

Verification:

- 212 cipher/boundary assertions: independent legacy/new AES-GCM interoperability
  for all 12 capabilities plus MCP/external-connection purposes; real MCP and
  external-account composition callers; cross-owner/revision rejection; malformed
  envelopes/JSON/UTF-8; JSON snapshot and ORM validation; no-write invalid copies.
- Existing 76 provider lifecycle assertions pass.
- 19 PostgreSQL assertions execute the current source in an isolated process using
  session-private tables cloned from the active schema. Create, verify, rename,
  update/revision readback, current/pinned resolution, disable/delete and no-match
  update handling pass. Tables are confirmed temporary before writes and absent
  after rollback. No public operator rows, schema, services or credentials changed.
- The initial isolated DB probe omitted `register_models()` and failed before
  insertion; using the required runtime registration resolved the probe setup.

The follow-on OAuth refresh slice below resolves the 26 caller diagnostics in
MCP header narrowing and refresh ownership/error metadata/expiry parsing. Audit
other direct `JsonValue` JSON import paths for the reproduced finite-number gap.
Full changed-build browser acceptance and the F0–F10 goal remain open.

### F7 progress: Integration V2 OAuth refresh contracts

2026-09-09: refresh now carries frozen Pydantic request, response, failure and
renewal receipts. Required connection organization identity follows the existing
non-null ORM owner. Failure codes and retry/reauthorize disposition are enums;
HTTP status remains separate, preserving existing persisted diagnostic strings.
Scheduled-task output keeps its JSON shape through a discriminated TypedDict.
MCP header values narrow explicitly before entering the transport contract.

Token expiry accepts a nonnegative integer, not a boolean, float or numeric
string. Invalid response material and datetime overflow produce value-free
refresh failures. Secrets are excluded from receipt snapshots and repr; explicit
form/encryption boundaries still receive the required plaintext. Optional token
rotation fields preserve existing credentials when absent or empty.

Verification: 96 function assertions cover actual registry and wire DTOs,
malformed responses, private projections, stale revisions, retry/reauthorization,
guarded persistence, cancellation and HTTP outside transactions. DB services and
HTTP transport are substituted; this is not a live token-rotation proof. Scoped
type checking, including the scheduled task and affected SOR/MCP consumers,
reports zero errors. A local pre-commit/pre-push gate retains that scope.

The scheduled-task JSON success/failure projections and cancellation propagation
also pass a focused caller probe. The 212-assertion cipher/MCP/external-connection
regression probe passes. All seven configured type/import gates, backend Ruff and
documentation validation pass; the existing LLM gate retains its one suppression.

Browser baseline QA on the older running image: logged back into the existing
Eylo Development organization after session expiry; resumed QA SOR Audit Agent
in the widget; a new `issue_search` call for VER-50 completed. Console conversation
`01a0842c-908d-7b70-b9f0-21154013c441` displays all nine persisted messages,
including the new completed user/call/result/agent exchange. Widget back-navigation
shows the updated conversation preview. This is not changed-build acceptance.
QA Minimal Groq Agent also retained earlier conversation context in a widget
follow-up; the console list shows the updated four-message conversation. No
provider configuration, source record or credential was changed for these cases.
Its detail page also loads all four messages with completed states. A baseline
UX issue remains: list/detail initially show an empty result message while their
API request is still loading, then replace it with the actual rows/messages.
This observation needs a separate UI data-loading investigation, not a refresh
pipeline fix.

This slice preserves the existing form request and HTTP failure classification;
it does not establish every vendor's refresh protocol compatibility. Vendor-specific
authentication formats and callback failure lifecycle remain separate work; the
next slice below types the shared initial exchange.
Final acceptance must use the existing test organization in the widget, followed
by console inspection of the same conversation and tool calls, against a runtime
that actually contains the changed source. Preserve configured providers and data.

Final browser acceptance checklist (user-requested):

1. Start the widget and operator console; verify backend and worker build identity
   before treating results as changed-source evidence.
2. Read the private test-organization credential file locally, sign in, and use
   Eylo Development. Never copy credentials into this plan or QA output.
3. Navigate the real widget and converse with published agents using their
   configured providers and tools. Cover each affected capability with an
   appropriate agent; record unavailable bindings rather than invent defaults.
4. Open the same conversations in the console. Check message ordering, terminal
   states, tool arguments/results, and the relevant persisted product outcomes.
5. Record conversation links, tested build, configured-provider coverage, failures,
   and unrun cases. Keep fixture checks separate from live-vendor evidence; request
   user involvement only for consent or interactions that cannot be automated.

### F7 progress: initial OAuth exchange and state receipts

2026-09-09: initial exchange and refresh now share `OAuthTokenResponse` at their
wire boundary, with private fields, strict expiry, ignored extensions and safe
parse failures. Each pipeline translates those failures into its own enum codes.
Authorization-code requests serialize explicitly to the existing pinned form
request. Consent redirects and callback completion use frozen Pydantic receipts;
the public callback still emits the same fields. No vendor scopes or request
authentication format changed.

`OAuthStateCreateSchema` validates the actual UUID/revision/aware-expiry contract
and existing DB string bounds. Repository creation revalidates copied input.
`ExpiredOAuthState` is a frozen Pydantic receipt. Owner-scoped deletion uses
`DELETE RETURNING` IDs instead of an untyped cursor row count.

Evidence:

- 104 function assertions through real registry, ORM state and wire models:
  PKCE formation, consent/state agreement, exchange errors, strict expiry,
  activation input, callback event identity, private projections and cancellation.
  DB/HTTP effects are substituted, so this is not live OAuth consent acceptance.
- 96 refresh regressions pass after replacing the duplicate token-response model.
- 14 real PostgreSQL assertions exercise current repository source against a
  session-private clone of `connection_oauth_states`: create/read, consume once,
  expired-state receipts, cross-org deletion isolation, exact deletion count and
  invalid-copy refusal. Temporary-table identity is checked before writes;
  rollback removes it. No public rows, schema or running services change.
- The initial function probe omitted required `refresh_attempts` in its fixture;
  correcting the fixture resolved that setup failure.
- Scoped type checking includes callbacks, widget initiation, shared state cleanup
  and the SOR OAuth consumer. The expanded local type gate retains that scope.

### F7 progress: callback rejection and transaction lifecycle

2026-09-09: reproduced missing-installation consumption rollback using the actual
pipeline with a transaction-rollback substitute. The public controller's declined
callback also bypassed state handling. The direct completion controller helper
(not currently routed) held its own transaction over the token-exchange pipeline.

Repairs:

- Missing-installation and linkage failures are raised after state consumption
  commits; an old state cannot become reusable because failure rolls it back.
- Declined/missing-code callbacks use a named `AuthorizationRejection`, consume
  state, perform guarded cleanup and emit the contact failure after commit.
  Arbitrary provider error strings are not shown to the user.
- Expiry/rejection share the connection domain's renamed
  `revoke_pending_authorization_attempt` guard. Only a matching initiated revision
  is revoked; active, reauthorization-required and newer connections survive.
- Activation refuses a revision that changed since consent began. The controller
  releases its lookup transaction before invoking token exchange.
- Reproduced cleanup dropping consumed expired states without returning their
  connection ownership receipts. Cleanup now uses one `DELETE RETURNING` for all
  expired attempts, including consumed states left by failed/cancelled exchanges;
  the domain guard still preserves active/newer connections.

Evidence: 97 function assertions cover actual controllers/domain guards, state
replay, wrong callback route, missing installation, cancellation, expiry, revision
conflicts and post-commit event timing. DB/HTTP effects are substituted. The earlier
104 initial-exchange assertions still pass. A separate real PostgreSQL probe runs
24 assertions with current source in a session-private state table: committed
missing-installation/declined/missing-code consumption remains spent after failure.
Consumed expired attempts now produce cleanup receipts before removal.
The outer transaction is rolled back and temporary-table removal is verified;
no public rows, configured credentials, schema or running services are changed.

These checks do not prove concurrent callbacks across separate PostgreSQL sessions,
every vendor's token authentication format, or changed-build browser acceptance.
The running image remains older than this source. Full F0–F10 completion is open.

Additional browser baseline: existing console/widget sessions remained logged in
to Eylo Development. Started QA Dynamic Widget Agent through the widget picker;
the real agent rendered a required-text feedback form via
`compound_render_widget__cc8d3cbb`. Submitted a QA marker; the form became disabled
and the agent acknowledged the exact submitted value. Console conversation
`01a0849a-fac4-7c72-9e60-92f2efec9a58` shows seven completed entries: user request,
assistant text, tool call, widget, tool result, widget response and final assistant
message. Back-navigation updated its preview; loading older conversations appended
two entries (eight to ten loaded). This is running-image behavior, not verification
of the OAuth source patch, all providers, voice audio or live OAuth consent.

### F5 progress: Memory material and verified dependency authority

2026-09-09: replaced Memory config, resolved authority, verification facts/results
and runtime composition dataclasses with Pydantic contracts. Settings expose UUID
fields; the shared provider-config persistence boundary still receives the same
string-valued config JSON. Memory's empty credential contract rejects supplied
keys without echoing their values. The existing boolean authority predicates,
provider spelling and dependency observation casing remain unchanged.

Verification and runtime readback now reuse one `MemoryDependencyAuthority`.
Known fields are typed, extra JSON metadata survives round trips, and resolved
settings must match verified dependency IDs. The service takes that typed
authority and serializes only when calling shared persistence. Runtime LLM
comparison uses fields rather than a string-key dictionary. Reindex callers use
the same new material entrypoint; no transaction, SDK request or index-lifecycle
change was made. A wrong-capability effective config is rejected explicitly.

An import probe caught an in-progress conversion defect that type checks missed:
Pydantic could not inspect the static-only completion protocol. Made that protocol
runtime-checkable without weakening its static keyword/async signature, and added
Memory verification/resolution imports to the existing runtime gate. Live handles
are excluded from runtime model serialization and reprs.

Verification: 214 assertions (166 material/legacy-projection and 48 composition)
cover service creation, current/pinned resolution, dependency refusal, metadata
write/readback, adapter/callable exclusion, transaction boundaries, verification
failure and cancellation. Persistence, dependency runtime calls and transaction
contexts are controlled substitutes; these are not live provider or PostgreSQL
concurrency proofs. All 11 scoped typing/import gates, backend Ruff and changed
file formatting pass. Documentation validation also passes. The scoped baseline's
two provider-type errors are gone.

Next at this checkpoint: type the Memory public API settings/projections and
remaining Memory operator payloads; then reconcile the remaining full F0–F10 ledger. Final
changed-build widget/admin acceptance is still required. No DB reset, operator
config edit, migration, deployment, commit or history change in this slice.

### F5 progress: Memory public config API and console contract

2026-09-09: Memory create/read/verification schemas now expose `MemoryProviders`;
create/read/update settings use the same `MemorySettings` UUID contract as the
domain. Controllers serialize at the shared provider persistence boundary and
validate stored settings before projecting responses. PATCH still replaces a
complete settings object, preserves omitted config and the existing nullable
secret-patch map, and rejects explicit top-level null. Provider normalization,
masked secrets, response aliases and successful JSON values remain unchanged.

Expanded the existing Memory type hook to schemas, controllers and routes. This
exposed a pre-existing reindex route return mismatch: it promised an API schema
but returned an ORM row and relied on FastAPI conversion. The route now explicitly
projects through `MemoryReindexJobRead.model_validate`; no reindex scheduling,
job state, transaction or authorization behavior changed.

Executed 94 HTTP/contract assertions with the real router, controllers, config
service, domain aggregates and exception handler. Checks cover create/read/list,
legacy JSON parity, revision/enable behavior, complete settings replacement,
malformed inputs, masked/no-credential refusal, null secret patches, cross-org
refusal, unavailable-credential projection, verification, reindex ORM projection
and OpenAPI settings shape. Auth, foundation persistence, transactions and
verification/reindex use cases were substituted. These do not prove live DB,
provider calls, worker completion or browser acceptance of this source build.
The preceding 214 material/composition assertions also pass unchanged. All 11
scoped typing/import gates, backend Ruff and changed-file formatting pass.

Regenerated the console client from a temporary changed-source app with lifecycle
startup disabled. Console lint, TypeScript and production build pass; Vite retains
its existing large-chunk warning. No console/widget behavior was changed. The
remaining Memory operator payloads and full F0–F10 ledger remain open; final
changed-build widget/admin acceptance is not replaced by the earlier old-image
browser smoke. No operator config edit, DB reset, migration, deployment or commit.

### F5 progress: Memory metadata, recall audit and operator projections

2026-09-09: traced metadata through `MemoryVendorAdapter.add`, PgVector formation/
reactivation writes, fact/recall contracts, ORM annotations and operator reads.
These boundaries now use `dict[str, JsonValue]`, not untyped maps or `Any` values.
The adapter copies/validates input before provider or DB work, including formation
replay dispatch. No fixed custom-field schema was invented. Opaque objects,
non-string keys and non-finite values are refused with a content-free terminal
Memory error; valid JSON and stored-null-to-empty-object projection are preserved.
Fact/recall models reject non-finite numbers and omit metadata from reprs while
retaining explicit JSON output. Reindex API semantic options are typed JSON too.

Recall auditing now requires `AsyncSession` and checks `CursorResult` before the
existing exact row-count invariant. Owner lookup uses `MemoryLevel` members.
Subject-label queries unpack typed selected tuples instead of dynamic row fields;
they retain the same bounded three-query batching, tenant filters and fallback
order. No schema, SQL predicate, ownership policy, transaction or scheduler change.

Executed 113 assertions: metadata copies/serialization/refusals; all three owner
levels; recall update PostgreSQL SQL parity against the previous implementation;
real SQLAlchemy CursorResult/rollback/filter behavior on disposable in-memory
SQLite; selected-column label queries with actual SQLAlchemy types/results; adapter
ingress before substituted provider effects; and real FastAPI operator routes with
controlled ORM/auth/integrity dependencies. HTTP checks include list/detail,
metadata/provenance JSON, missing/cross-org refusal and invalid stored metadata.
The HTTP fixture initially guessed `MemoryIntegrityState.CLEAR`; source defines
`HEALTHY`. Corrected the fixture, not production. SQLite is not a PostgreSQL
concurrency or schema-migration proof. The async DB driver is not exercised there.

The previous 214 material/composition and 94 config-API assertions also pass.
All 11 scoped typing/import hooks pass; the Memory hook now includes service,
operator schemas, adapter base and PgVector implementation. Existing unrelated
dynamic/raw-SQL/durable helpers remain open rather than being hidden by the gate.
Regenerated the client from changed-source OpenAPI and verified schema parity
after the final validation change. Console lint, TypeScript and build pass, with
the existing chunk-size warning. `JsonValue` deliberately has an open Pydantic
schema, so generated TypeScript values remain `unknown`; no generator override or
hand-edited client hides that boundary. No operator data or running product image
was changed. Changed-build widget/admin acceptance remains pending.

Next: Memory raw SQL row/formation/reconciliation/durable envelope contracts, then
reconcile full F0–F10 remaining work. This completes the inspected operator
metadata/label/audit slice, not Memory or platform-wide typing as a whole.

### F5 progress: PgVector Memory row and mutation snapshots

2026-09-09: added adapter-owned `pgvector_records.py` contracts for fact, search,
locked fact, history, target, duplicate/snapshot and returned history timestamp
projections. Replaced `_FactSnapshot` dataclasses and dynamic consumed row fields
with Pydantic values; the common Memory API contracts and module ORM ownership
remain separate. SQL enum strings are explicitly parsed; UUIDs, aware timestamps,
finite distances, positive revisions, nullable metadata and exact owner columns
are validated before downstream use. Unconsumed extra selected columns are ignored.
Malformed rows become safe terminal Memory errors without fact/provenance detail.

Search/list/history and correction results keep the same public JSON and ordering.
Target/duplicate snapshots retain hash and state-revision meaning. Correction
`RETURNING` projection now occurs before history recording and commit rather than
after commit: malformed output cannot become a committed success followed by a
decoding failure. The history insert timestamp is likewise validated before the
reconciliation cursor update. Typed `AsyncSession` helpers use `CursorResult`
guards for affected row counts. Valid SQL, scope/index/revision guards, callback
sequence and transaction ownership stay unchanged.

Executed 234 contract assertions with real SQLAlchemy Row/Result objects and the
installed asyncpg UUID class, controlled session/provider I/O and a captured
pre-slice adapter. Proved valid JSON/SQL/effect-trace parity for all owner levels,
retrieval, locked reads, correction no-op/race paths, new/duplicate/reactivated
facts, targeted updates/deletes, expiry, history insertion and cursor timestamp
propagation. Malformed fields, owner combinations, non-finite distances, revisions,
timestamps and SQL result objects are refused before downstream effects where
applicable. A probe initially compared two distinct mocked session identities in
history call arguments; corrected the comparison to the operation arguments.
These are not live PostgreSQL execution/concurrency or provider-completion proofs.

The preceding 113 operator, 214 material/composition and 94 config-API assertions
also pass. The new row module is covered by the existing Memory type hook. No
public schema, frontend source, migration, configured provider or running product
image changed. Changed-build widget/admin acceptance remains pending. Remaining
Memory formation plan/outcome rows and durable/reconciliation envelopes still
need typed contracts; full F0–F10 completion remains open.

### F5 progress: Memory formation operations and committed outcomes

2026-09-09: traced formation planning through persisted operations, embedding,
locked effect selection, atomic application, durable-step replay and outcome
recovery. Added shared `MemoryOperationBatch` and `MemoryFormationOutcomes`
Pydantic contracts. The adapter and recovery pipeline now share operation/count
validation instead of independently interpreting dictionary keys. ORM JSON fields
retain their storage shape with explicit `JsonValue` annotations. Job counter
assignment uses concrete attributes instead of string-driven `setattr`.

The adapter-owned effect row requires outcomes and an aware completion timestamp
together. Malformed or partially completed effects fail safely rather than being
replayed or treated as new work. Plan policy remains separate from outcome shape:
a committed ADD has a target ID that an unexecuted ADD plan must not contain.
Wrapper reprs omit fact content without changing explicit JSON serialization.
No SQL, table, job state, provider selection or transaction ownership changed.

Executed 218 assertions against captured pre-slice implementations using real
Pydantic/ORM/SQLAlchemy Row and Result types with controlled session/provider I/O.
Checks cover list/outcome JSON parity, malformed payloads, count mismatch,
partial-completion refusal, job counter projection, stored-plan reuse, competing
insert winner readback, early/raced completion, stopped jobs, missing effects,
commit guard failure and cancellation. Provider planning/embedding are asserted
outside the controlled DB transaction; valid SQL/effect traces match the previous
implementation. These are not live PostgreSQL concurrency or worker proofs.

The previous 234 row/mutation, 113 operator, 214 material/composition and 94
config-API assertions pass unchanged: 873 assertions including this slice.
All 11 scoped typing/import hooks, backend Ruff and documentation verification
pass; the shared formation contract joins the Memory hook.
One pre-existing LLM suppression remains unchanged. No migration, operator data,
provider configuration or running image changed. Changed-build widget/admin
acceptance remains pending. Durable parameter/receipt and remaining reconciliation
envelopes are still open, as is the full F0–F10 ledger.

### F5 progress: Memory durable inputs, receipts and formation query types

2026-09-09: traced all three Memory workflow entrypoints from `spawn_bound_work`
ID payloads through task execution and terminal/failure receipts. Added
pipeline-owned `work_contracts.py`: shared ID-only parameters, workflow-kind enum,
typed formation/reconciliation/reindex receipts and the existing smaller reindex
failure receipt. The parser preserves valid UUID/wire-string inputs and safe
workflow-specific diagnostics; arbitrary objects are no longer stringified into
UUIDs. Receipts reuse canonical formation/reconciliation count types and validate
nonnegative counters. Existing successful JSON fields and terminal state values
remain unchanged.

Moved the existing message watermark value into that contract home for reuse in
formation ranges. Its serializer preserves ISO offsets rather than changing UTC
`+00:00` to `Z`. Formation eligibility now takes/returns a typed SQLAlchemy Select
instead of variadic `Any` columns. Selected timestamp/ID and ORM-pair consumers
unpack typed tuples. Session helpers, runtime authority comparisons, reconciliation
batch building and candidate enrichment now have concrete inputs. Formation text
extraction narrows user/assistant content types instead of using `getattr`; SQL
already restricts this path to those learnable roles. Non-learnable content is
explicitly refused at the extractor boundary too.

Executed 294 assertions using actual ORM models, SQLAlchemy results, Pydantic and
the installed asyncpg UUID type, with controlled transactions/services and captured
pre-slice implementations. Checks cover task-shape/UUID refusals, receipt JSON for
all durable states and timezone offsets, invalid counters, terminal workflow
replay, retry-after-transaction behavior, SDK cancellation cleanup, PostgreSQL
query/parameter parity, message watermark windows and text/provenance projection.
No live PostgreSQL execution, provider call, worker restart or browser claim is
made by these probes. Provider checkpoint decoding remains a separate boundary:
reconciliation text has an existing parser; reindex vector replay still relies on
downstream batch/dimension checks and needs explicit finite-vector decoding.

The preceding 873 formation, row/mutation, operator, material/composition and
config-API assertions pass unchanged: 1,167 checks including this slice. All 11
scoped typing/import hooks, backend Ruff, changed-file formatting and docs
verification pass. Existing test-client deprecation warnings and the single LLM
type suppression remain unchanged.

The full `pipelines/memory/` directory passes Pyrefly and now belongs to the Memory
hook, replacing partial file coverage. Full platform F0–F10 completion and final
changed-build widget/admin QA remain open. No task names, checkpoint keys, SQL,
migrations, operator config, deployment or Git history were changed.

### F5 progress: finite embedding results and reindex checkpoint replay

2026-09-09: traced live embedding output and cached durable vectors into both
Knowledge and Memory staging. Existing adapter validation ran only on a fresh
provider call. Reindex replay checked count/dimensions downstream, then converted
components with `float()` while constructing SQL parameters. A controlled probe
confirmed that the previous paths passed `[nan,0.0]` to the staging statement.
This is evidence of a missing pre-write guard, not proof PostgreSQL accepted or
stored the vector. Replaying a bad checkpoint cannot repair its contents.

Added vendor-neutral `EmbeddingVectorBatch` with strict nested list structure,
finite numeric components, copied/revalidated values and private reprs. Live
embedding runtime now validates full count and dimensions as well as component
values, including query cardinality before indexing its first result. Both reindex
workers validate fresh/replayed batches against their pinned target before opening
the staging transaction. Invalid checkpoints translate to terminal product errors;
vendor transport errors retain their original retry decision. Checkpoint keys and
list shape, valid vectors, SQL/revision/tenant fences and cutover ownership stay
unchanged. No adapter protocol or provider configuration changed.

Executed 420 function assertions covering list/copy/finite-number contracts,
complete counts, dimension errors, live document/query forwarding, fresh versus
cached reindex steps, refusal before staging, exact valid SQL/effect traces,
retry propagation, SDK cancellation and asyncio cancellation. The workflow probes
use actual ORM jobs, embedding runtime, detached source items and both real staging
methods, with controlled session/provider/worker services. They are not live
PostgreSQL, provider or restart-recovery proof. The first harness run omitted
`register_models()` and failed at ORM construction; corrected the harness to use
the app's explicit bootstrap, not production schemas or import-order side effects.

The preceding 1,167 Memory contract assertions pass unchanged: 1,587 across these
executed checks. The new contract is in the embedding gate and triggers embedding,
Knowledge and Memory checks. All 11 scoped type/import hooks, backend Ruff,
formatting and docs verification pass, with the existing LLM suppression unchanged.

A fresh full-project Pyrefly audit reports 624 errors and four suppressions.
This is a current inventory, not a claimed reduction from a comparable baseline.
Largest remaining groups include voice pipelines (143), event listeners (41),
Agents (39), WebRTC (25), audio downsampling (23), sandbox pipelines (23) and SOR
runtime/support (22 each). Scope-wide gates are therefore not platform completion.
Next: follow published-agent definition and tool/provider binding assembly,
including repository/service type boundaries and their actual consumers, before
continuing the remaining F0–F10 operation inventory. The type-error count is only
one signal; unchecked dictionaries, wire shapes and missing live QA still matter.
Rebuilt-product browser acceptance remains open. No operator DB, configuration,
migration, deployment or Git history was changed.

### F2 progress: typed Agent publication bindings

2026-09-09: followed draft choices through provider resolution, publication,
immutable tool grants, revision readback, and service projections.

RCA: provider references were a string-keyed dictionary of nullable tuples;
publication assembled ORM attributes with `getattr`/`setattr`. Typed Voice Configs
were serialized to JSON and parsed back to recover executable provider IDs.
Tool readers relied on SQL filters and DB check constraints without narrowing the
nullable ORM fields into the exact reference promised by their return types.
This was a maintainability/type-boundary gap, not evidence of a live cross-tenant
grant or an incorrect provider selected in an operator run.

Implemented:

- `modules/agents/publication_bindings.py` owns frozen Pydantic provider references
  and explicit publication bindings. An exact reference requires a UUID and a
  positive integer revision; unresolved optional choices remain absent. Native
  UUID compatibility is retained without accepting arbitrary stringifiable objects.
- Publication resolves the same providers, in the same order and organization.
  Header/revision column assignments are explicit. Voice provider references come
  from typed fields; the complete JSON snapshot is created only for storage.
  Inactive STT/TTS choices in realtime mode remain in that snapshot, not in the
  executable provider columns.
- Draft/published tool readers validate their selected row's existing exactly-one
  binding invariant before passing a non-null reference downstream. Curated tools
  remain unrevisioned. Queries, tenant filters, constraints and grant authority
  are unchanged.
- Agent service schema properties correctly return schema classes. Draft editing
  retains its already-validated optimistic version across payload reconstruction.
  Published availability is explicitly translated into its existing owned enum.

Function evidence: 1,499 assertions, including 96 provider/voice combinations
executed against both pre-change and current publication functions. Real ORM
models, Pydantic config/tool schemas, lifecycle objects and SQLAlchemy result
objects are used; DB sessions, template lookup and external service I/O are
controlled. Published/header projections, exact tool grants, query SQL/parameters,
resolver calls and failure effects match. Coverage includes missing capability
dependencies, stale draft versions, revoked revisions, voice binding failures,
native UUIDs, malformed references, service draft readback, and cancellation.
The first probe omitted the required `PlatformTool.input_schema`; corrected the
fixture, not the production contract. These are function/data-flow checks, not
live PostgreSQL publication, provider use or rebuilt-widget acceptance.

The new local Agent-publication type hook and the preceding 11 type/import hooks
pass. Backend Ruff, documentation verification and changed-file formatting pass.
The comparable full-project Pyrefly audit moves from 624 to 613 errors, with four
existing suppressions unchanged; Agent errors move from 39 to 28. This is scoped
progress, not completion of F2 or F0–F10. No API/DB schema, operator configuration,
migration, deployment or Git history changed.

Next: finish the actual Agent/swarm schema and service/repository boundaries,
then runtime assembly consumers. Shared schema-class/ORM conversion signatures
remain open; this slice did not change a global generic service to silence them.
The legacy `AgentToolService.get_by_tool_id_and_agent_id` also discards its fetched
row and passes a UUID into schema projection; trace its callers and reproduce the
publicly reachable path before deciding the follow-up correction/removal.
Voice/provider response streams, other F0–F10 work, and rebuilt admin/widget
acceptance against the configured QA organization remain open.

### F2 progress: swarm lookup and schema ownership boundaries

2026-09-09: the remaining 28 Agents-module diagnostics are resolved without
changing API/DB schemas or tenant/lifecycle rules.

- Swarm header lookup now separates optional `_find_header` from required
  `_get_header`. The previous boolean `required` mode made every successful
  required lookup statically nullable. Absence still raises `SwarmNotFoundError`
  before mutation, with the same organization/deleted filters and lock selection.
- `EyloOrganizationModelSchema` describes records with a required organization.
  Agent and swarm draft/membership schemas use it instead of narrowing a mutable
  optional-owner field inherited from the legacy base. All six affected model
  JSON schemas match their pre-change versions. Other optional-owner consumers
  were not silently tightened.
- Swarm revision availability is translated explicitly to `RevisionAvailability`.
  Membership uses its existing `AgentKind` rather than a dynamic attribute helper.
  The nullable membership description now has a nullable ORM annotation; its
  existing nullable DB column is unchanged.
- Repository membership deletion narrows the actual SQLAlchemy `CursorResult`
  before using its affected-row count. An unexpected non-DML result fails rather
  than supplying invented deletion success.

Executed 96 function/data-flow assertions. These use actual swarm ORM tables,
repositories, services and lifecycle objects against disposable in-memory SQLite,
with agent resolution substituted and FK enforcement not claimed. They cover
optional/required/foreign/deleted lookup, draft editing, optimistic conflicts,
membership, immutable publication/readback, withdrawal, revocation, draft deletion,
empty/oversized/background/missing-agent refusal, and real DML affected-row counts.
The existing HTTP transaction adapter still maps absence to 404 and conflicts to
409. Schema checks include native UUID compatibility and exact JSON-schema parity.

Fixture corrections were not production fixes: SQLite stored the PostgreSQL
boolean server default `"false"` as text, so active-row queries missed it. The
fixture supplies the equivalent native `False` during insertion. Independently
generated external UUIDs are validated as UUIDs rather than compared for literal
equality across two separate runs. Production defaults and identifier generation
remain untouched. SQLite checks do not prove PostgreSQL FK enforcement, row locks,
concurrent publication, restart recovery or live product operation.

The local Agent hook now checks the entire `modules/agents/` directory. All 12
scoped type/import hooks and backend Ruff pass. The comparable full-project audit
moves from 613 to 585 errors, with four existing suppressions unchanged. Shared
`CaseInSensitiveEnum` class-subscript diagnostics still exist in `common/schemas.py`;
the new required-owner base does not hide or fix them. Likewise a clean Agents
type gate does not prove remaining unannotated/dictionary/runtime boundaries are
complete. F0–F10 and rebuilt admin/widget QA remain active.

Next: shared service/repository conversion contracts and runtime Agent/swarm
assembly, including the already-noted tool lookup projection. No operator DB,
provider configuration, migration, deployment or Git history was changed.

### F2 progress: shared full-row repositories and schema conversion

2026-09-09: traced all 23 concrete generic repositories and the schema-conversion
callers in auth, contacts, conversations, tools and OAuth state persistence.
Every repository model inherits `EyloBaseModel`; the generic now carries that
UUID-identity contract instead of the wider SQLAlchemy declarative base.

- Full-row reads retain their exact model type and nullability. Collection
  helpers return lists, matching their signatures. The unused `columns` mode
  and its builders were removed: they conflicted with ORM-row return contracts.
  No active caller selected columns through these helpers. Specialized aggregate
  and projection queries are unchanged; tenant/lifecycle filters remain owned
  by callers, not inferred by the generic repository.
- `count_([])` previously emitted a table-less `SELECT count(*)`, returning one
  regardless of table contents. It now explicitly selects from the model table.
  Filtered counts retain their existing predicates. This fixes the helper's
  contract; it is not evidence of an observed incorrect production count.
- `map_schema_to_model` no longer calls Pydantic's nonexistent `model_dump(only=)`.
  Explicit target fields use `include`, including inherited model fields, and
  validation precedes ORM construction. Exact schema-type comparison also
  projects subclass-only fields out instead of treating a subclass as the target
  representation. Same-schema conversion preserves Python UUID/enum/date values.
- Service conversion parameters now describe schema classes rather than schema
  instances; list conversion correctly advertises ORM rows. OrganizationService's
  schema property likewise returns a schema class. These annotation repairs do
  not yet bind the generic service to its concrete model type.

Executed 132 function assertions across nine real schema/ORM pairs and actual
SQLAlchemy queries against disposable in-memory SQLite. Cases include same-schema
conversion parity, narrower target projection, inherited fields, refusal before
ORM construction, full-row lookup/filter/order/pagination, absent rows, empty bulk
input, and empty/one/three-row table counts. Query SQL and parameters match the
pre-change implementation outside the deliberate count repair. SQLite fixtures
use UUID values with hexadecimal letters because its numeric affinity coerces
all-digit UUIDs; this was a fixture limitation, not a production UUID change.

Agent publication's 1,499 and swarm boundaries' 96 earlier assertions also pass:
1,727 assertions total for this slice and its regressions. These execute real
models/services/query construction with controlled provider and transaction ports;
they do not prove live PostgreSQL concurrency, providers or rebuilt-widget use.
All 13 local type/import hooks and backend Ruff pass. The repository/conversion
hook is new; changes to shared repository/services also trigger the Agent hook.
The full audit reports 566 errors with four existing suppressions, down from 585.
No public API schema, migration, operator DB, provider config or deployment changed.

Next service slice: carry both schema and ORM types through `EyloBaseService` and
its 19 concrete subclasses. The shared service's `ModelClass` is currently unbound
to its repository; a clean file-level gate does not fix that semantic gap. Its
unused generic `delete_` passes a response schema into repository persistence,
while `hard_delete_` needlessly reconstructs a row. Neither has active service
callers in the inspected tree; lifecycle-specific deletion paths must retain their
existing authority when deciding whether to remove these helpers. The separate
Agent-tool lookup projection finding remains open. F0–F10 and changed-build
admin/widget/real-agent acceptance remain required before goal completion.

### F2 progress: concrete service schema and ORM pairings

2026-09-09: `EyloBaseService` now carries two type parameters: the response schema
and the repository's `EyloBaseModel` subtype. All 19 concrete services declare
their actual pair; AgentService's custom row projection also accepts its exact
`AgentsModel`. List conversion accepts iterables without losing the element type,
and identity lookup requires a UUID rather than `Any`. An explicitly supplied
conversion schema may still be a create schema, not only the response schema.

The stricter contract exposed and resolved three representation mistakes:

- Removed unused `AgentToolService.get_by_tool_id_and_agent_id`: it discarded
  the queried row and passed the tool UUID to schema conversion. The active
  `get_by_agent_and_tool` remains unchanged, including optional absence.
- `MessageService._persist` returns its already-validated `MessageInDb`. It no
  longer passes that schema back through an ORM-only conversion helper. Row
  insertion, conversation timestamp update, voice/session facts and post-commit
  message event registration remain in their existing order.
- OrganizationService inherits the base required lookup instead of validating
  `None` as an organization. Missing identity now raises `EntityNotFound` rather
  than Pydantic `ValidationError`; existing rows retain their exact projection.

Removed the base service's unused `delete_` and `hard_delete_` helpers. The former
passed a response schema into SQLAlchemy persistence; the latter reconstructed
a row only to delete by ID. Source and call-site checks found no active callers.
All active module-specific deletion paths remain unchanged; no row, API route or
operator data was deleted. This removes a misleading shared mutation API rather
than bypassing domain lifecycle or ownership policy.

Executed 132 service assertions cover all 19 generic/schema/repository pairings, actual
shared reads and conversion against in-memory SQLite, exact query/output parity,
missing/empty lookup, and actual MessageRepository construction/persistence calls
through a controlled session port. Message filing checks both absent and present
user-session identity and verifies the same typed message reaches voice facts and
post-commit events. Provider I/O, real PostgreSQL locks and event delivery are not
proven by these probes. The retained generic best-effort `get_by_` exception
handling is unchanged, not a claim of complete error-boundary hardening.
The removed helpers' failures were reproduced against the pre-change service:
UUID projection raises Pydantic `ValidationError`, and schema persistence raises
SQLAlchemy `UnmappedInstanceError` without changing the original ORM row.

Agent publication's 1,499 assertions and swarm boundaries' 96 assertions pass
again using a separately loaded pre-change base service for the legacy side;
the old single-parameter generic is not silently evaluated against the new base.
The preceding repository/conversion probe's 132 assertions also pass, for 1,859
function/data-flow assertions including this slice and its regressions.
All 13 local type/import hooks, backend Ruff and application/OpenAPI construction
(245 paths) pass. The full audit remains at 566 errors/four suppressions with no
new diagnostic headings: this slice closes a generic-contract blind spot rather
than merely reducing a counter. F0–F10 remains open, including unannotated/native
vendor boundaries, runtime Agent/swarm assembly and changed-build browser QA.

### F2 progress: exact Agent runtime revision projection

2026-09-09: `ExecutableAgentResolver._to_agent` now consumes the actual
`AgentRevisionModel`. Persisted LLM overrides cross explicitly through
`LLMOverridesSchema`; published lifecycle uses the owning enum. Valid output is
unchanged. No schema migration or provider-config rewrite is involved.

Template resolution now rejects an incomplete ID/revision pair, or a nonpositive
revision, with `InvalidAgentDefinitionError` before invoking the renderer or tool
lookups. A missing pair remains valid for code-owned background Agents. The prior
resolver forwarded a missing/nonpositive revision when an ID existed, or silently
ignored an orphan revision. Publication already intends exact paired references;
this is a runtime guard, not a fallback to the current template.

Executed 264 function/data-flow assertions use actual revision/schema/template
types with substituted persistence/service I/O: projection parity for both Agent
kinds, uploads and generation overrides; invalid overrides; new-work and exact
assembly across five supported Agent consumers; empty instruction pairs; malformed
pairs; and unchanged refusal of unavailable exact tool grants. These are not live
DB/vendor or browser acceptance tests. The initial probe incorrectly included the
separate campaign-message consumer; it was corrected without changing production
template policy.

The Agent type hook now covers runtime Agent/swarm resolvers and the swarm worker.
All 13 type/import hooks, backend Ruff, documentation verification and app/OpenAPI
construction (245 paths) pass. The full audit reports 565 errors/four existing
suppressions; diagnostic-heading comparison removes only this resolver's nullable
template-revision error and adds none.

Admin (5173) and widget (5174) were confirmed running and authenticated/connected
to the existing Eylo Development QA environment. The browser displays the prior
23-message conversation, completed KB/memory tool calls, citations and Bedrock
reranking results. This is readiness/old-image evidence, not new changed-build QA:
the Docker services have not been recreated with the current typing work. No
operator data, provider settings, migrations, deployment or credentials changed.

Broader dataclass migration, structured voice snapshots and F0–F10 remain open.
Do not convert these carriers mechanically: their existing invariant exceptions,
replacement semantics and nested mutable configuration require consumer-level QA.

### F2 progress: Pydantic executable Agent and swarm carriers

2026-09-09: `ResolvedExecutableAgent`, `ResolvedSwarmMember`,
`ResolvedSwarmTopology` and `SwarmWorkerRuntime` now use strict, frozen Pydantic
models with forbidden extra fields and carrier-instance revalidation. They are
runtime values, not live socket/task owners; no dataclass-only requirement was
found. Existing `DefinitionRef` and template segment types remain owned by their
existing modules and are not duplicated here.

Exact Agent identity/revision and nonempty, unique, same-org swarm membership
remain model invariants. Pydantic wraps those validation failures; the runtime
resolvers retain `InvalidAgentDefinitionError`/`InvalidSwarmDefinitionError` as their
public refusal classes, with value-free runtime/member/topology error messages.
Direct model construction now has Pydantic's standard `ValidationError` behavior.
The worker's `with_tools` reconstruction validates known fields; it does not use
unchecked `model_copy(update=...)` or `dataclasses.replace` on a Pydantic model.

Voice configuration narrows from arbitrary object values to JSON values, retains
its top-level read-only mapping and serializes explicitly. Existing browser and
telephony consumers still parse the same values through `VoiceConfig`. This does
not claim recursive immutability or complete structured voice-snapshot work.
Nested provider credentials retain their existing exclusion from serialization
and repr. No vendor SDK types, secrets or runtime handles were moved into an API.

Dependency evidence: installed Pydantic 2.11.10;
[model validators](https://docs.pydantic.dev/2.11/concepts/validators/#model-validators)
and [model copies](https://docs.pydantic.dev/2.11/concepts/models/#model-copy).
The first runtime import caught an incorrect field-serializer signature that
static checking did not detect. The signature was corrected against the installed
implementation; full app/OpenAPI construction now passes (245 paths).

Executed function/data-flow checks:

- 120 carrier, voice mapping/serialization, frozen-field, malformed-field,
  unchecked-copy, topology/refusal and real worker-loading assertions.
- 114 worker-loop assertions: text, empty response, tool continuation, iteration
  cap, cancellation propagation, exact tool selection and credential preservation
  without serialization disclosure. Compared with the pre-change worker/carriers.
- 264 prior resolver assertions plus eight runtime validation/domain-error checks.
  Combined: 506 assertions. DB/service/provider I/O is substituted; no live
  request, DB mutation, deployment, migration or persisted probe file.

All 13 existing type/import hooks, backend Ruff, documentation verification and
diff checks pass. The full type audit remains at 565 errors/four existing
suppressions; this carrier conversion adds no diagnostic headings. This closes
four runtime dataclass carriers, not the platform-wide F0–F10 goal. Remaining nested API schemas, typed
voice snapshots, native vendor operations and rebuilt-product browser acceptance
remain in scope.

### F2/F7 progress: published voice snapshot boundary

2026-09-09: `VoiceConfigSnapshot` replaces the executable Agent's JSON mapping.
It reuses `VoiceConfig` rather than duplicating policy fields. Exact-revision
resolution validates stored settings; browser and telephony consumers use
`for_call()` to detach nested plans and collections. The publication carrier is
also a frozen Pydantic model with a positive configuration revision.

Provider selection, pinned revisions, editable API shape and stored DB values
are unchanged. Partial legacy JSON receives existing schema defaults earlier;
its effective per-call configuration remains equivalent. A snapshot is only
top-level frozen. Per-call reconstruction, not recursive freezing, isolates
mutable nested plans. Missing provider configuration still fails at its owned
runtime resolver; this adds no provider fallback.

Executed 159 publication/snapshot assertions covering both voice modes, optional
storage, pinned provider resolution, invalid references, partial stored JSON and
per-call isolation. Re-ran 1,499 Agent publication/service assertions, 272
resolver/refusal assertions and 234 carrier/worker-loop assertions. These probes
substitute service/provider I/O; they do not establish live voice acceptance.
Browser audio, carrier media and changed-build product QA remain pending.

An additional 15 assertions exercised the actual telephony initialization path
through its provider-resolution boundary, including independent per-call plans
and foreign-organization refusal. Focused Pyrefly, backend Ruff, documentation
verification and diff checks pass.

Browser baseline (existing Docker image, not this refactor): signed into Eylo
Development, sent `QA_BROWSER_BASELINE_20260909` through QA Core Mixed Agent in
the widget, then inspected conversation
`01a084d2-ce00-77d1-9be8-ca04ff4a0908` in the console. Fresh `kb_query` and
`memory_recall` calls completed with Bedrock reranking applied, citation K1 and
separate memory provenance. The transcript contained 32 persisted messages,
including completed tool results and the attached background Agent result.
The expired console session returned to the same conversation after sign-in.
No provider configuration, source data or credentials were changed. This proves
the existing QA setup is usable; it does not close changed-build acceptance.

This supersedes the preceding slice's temporary JSON-mapping representation.
Full F0–F10 coverage, remaining native vendor contracts and the platform-wide
type audit remain open.

### F7 progress: typed Voice Config section editing and field metadata

2026-09-09: the section-edit route, controller, orchestration and service use
`VoiceConfigSection` and JSON-bounded request data. The section validator returns
the concrete policy-model union or hook list instead of `Any`. Reconstructing and
validating `VoiceConfig` replaces dynamic attribute assignment. Existing section
replacement/default behavior, optimistic revisions, provider-reference checks
and bound-draft advancement remain intact; published revisions are unchanged.

`experimental()` now returns `FieldInfo` for `Annotated` fields, with explicit
numeric-bound parameters. Defaults, required fields and factories remain visible
at their declarations. This removes arbitrary keyword forwarding and its two
pre-existing type errors. The approach follows installed Pydantic 2.11.10 and
its [documented annotated-field pattern](https://docs.pydantic.dev/2.11/concepts/fields/#the-annotated-pattern).

Executed 690 assertions: all 13 section values/defaults against the pre-change
validator; actual HTTP route → controller → pipeline → domain/repository calls
with substituted DB I/O; stale revisions, invalid values and cross-org refusal;
bound-draft updates; OpenAPI enum/body projection; identical JSON Schema for all
25 pre-existing API models, including all 27 experimental fields; required-field,
range and mutable-default isolation checks. One probe initially assumed the
request alias must be a named OpenAPI component; inspection confirmed FastAPI
correctly inlines it, so the assertion now checks the actual object/list contract.

Generated the console API types from a temporary localhost backend using the
current source, placeholder credentials and disabled startup hooks. This does
not update the operator DB or deploy the changed build. Extended the local voice
type hook to cover the complete API/section-edit path. Real DB-backed editing,
voice media and rebuilt-product acceptance remain pending.

Final checks for this slice: 690 section/schema assertions plus 159 existing
publication/snapshot assertions passed. All 13 local type/import hooks, backend
Ruff, documentation/link/diagram verification, console lint/typecheck/Vite build
and diff checks passed. Vite retains its large-chunk warning. The full Python
audit decreased from 565 to 562 errors, with four existing suppressions. The
temporary schema server was stopped; the operator deployment was not replaced.
Remaining voice work includes typed native-capability projections, policy modes
and complete provider/media acceptance. None of these gates establishes full
platform completion.

### F7 progress: native voice capability projections

2026-09-09: the compatibility response now uses a `kind`-discriminated union
with typed STT, TTS and realtime provider identities and native fields. Console
projections belong to the Voice module; socket capability models remain in the
sockets. The pipeline translates support, encoding and session-update enums
explicitly. Removed the generic `dict[str, Any]` response and duplicate realtime
config parsing. Platform features use named identifiers; platform policy does
not depend on native capability support. Existing JSON keys and values remain
unchanged.

Verified all 24 configured factory branches (10 STT, 11 TTS, 3 realtime) against
the pre-change projection. The probe uses real config validation, factories and
adapter construction, synthetic credentials and blocked network connections.
It covers typed response round-trips, invalid support/rate/provider/kind values,
unknown fields, secret-free output, organization/config forwarding and unchanged
platform policy. Google requires a structurally valid service account, so the
probe generates an in-memory test key; Hume uses a synthetic saved-voice ID,
and Nova uses the actual catalog values. No live provider requests occur.

The real HTTP route/controller/service path also exercises all 24 projections
with substituted read-only DB/config ports and cross-org refusal. OpenAPI now
describes the tagged alternatives instead of arbitrary native JSON. Console
types were regenerated from current source using a temporary local backend with
startup hooks disabled. Live media, current-build Docker/widget acceptance and
the remaining policy/vendor contracts are still pending; this slice does not
establish platform completion.

Checks: 1,516 capability/HTTP assertions and 440 section-edit regression
assertions pass. All 13 local type/import hooks, backend Ruff, console
lint/typecheck/Vite build and diff checks pass. The full Python audit remains
562 errors with four existing suppressions; no new suppression was added.
Vite retains its existing large-chunk warning. No DB migration, operator-data
mutation, deployment, commit or persistent probe file was introduced.

### F7 progress: Polly native config, SDK response and cancellation boundary

2026-09-09: traced shared TTS config → factory → Polly construction → verification
and synthesis → SDK body → ordered audio queue → manager completion/teardown.
Polly still consumed option dictionaries and returned untyped SDK responses.
A baseline function probe also confirmed cancellation during verification left
the client context open: `CancelledError` bypassed its `Exception` handler.

Added vendor-owned `PollyConfig`, engine/sample-rate enums and
`PollySynthesisRequest`. Private credentials are excluded from serialization and
the base audio contract no longer retains them. Exact SDK method arguments use
the request model; generated client values and response bodies are narrowed
inside the socket. Malformed/non-binary output fails explicitly. Rejected bodies
with a usable close method are released; cancellation closes the verification
body and client. Finished worker tasks are awaited rather than abandoned.

Source authority: installed/locked aioboto3 15.5.0, aiobotocore 2.25.1 and
botocore 1.40.59, plus AWS's
[SynthesizeSpeech reference](https://docs.aws.amazon.com/polly/latest/APIReference/API_SynthesizeSpeech.html).
The existing PCM-only request and explicit engine/voice/language selection remain
unchanged. No SDK upgrade, fallback or new vendor capability was introduced.

The first real-SDK probe exposed a refactor issue: runtime protocol checks do
not recognize `close()` forwarded by aiobotocore's `StreamingBody` proxy. A small
concrete-SDK wrapper now exposes its methods to the response contract. This is
why structural mocks alone were insufficient. Subsequent checks use the actual
generated SDK client and actual streaming-body class, with AioStubber responses
and controlled body I/O rather than live AWS requests.

Executed 153 function assertions for all four engines/two PCM rates, optional
tokens, exact request serialization, private values, invalid/copied configs,
ordered fragments, drain/completion, cancellation, interruption/next-turn
isolation, malformed response/byte refusal, safe provider failures, rejected
client/body cleanup and the real SDK proxy. The existing 1,516 all-provider
capability/HTTP checks also pass. Added all three Polly files to the local voice
type hook. Shared TTS carrier typing, Sarvam's native flow, further lifecycle
policy enums and changed-build/live-provider acceptance remain pending. The
complete F0–F10 goal stays active.

Final gates: all 13 local type/import hooks, backend Ruff, documentation
verification and diff checks pass. The full Python audit remains 562 errors
with four existing suppressions. No public API or frontend contract changed in
this Polly slice; no DB, migration, deployment or operator configuration changed.

### F7 progress: Sarvam TTS wire and stream ownership

2026-09-09: traced resolved config → actual TTS factory → WebSocket setup/text/
flush → native audio/final → manager response queue → consumer/recording tap →
playback completion and teardown. The pre-change probe reproduced two defects:
documented `event` / `final` was ignored, and cancellation during configuration
left the socket open and reported connected. Source/document comparison also
found `target_language_code` instead of the streaming field `language_code`, and
no explicit codec despite declaring PCM to downstream playback. The documented
vendor default is MP3; this was not a live-vendor codec reproduction.

Added frozen vendor configuration, model/language/rate/state enums, typed tuning,
request models and a discriminated response union. Unconfigured tuning remains
omitted; model-inapplicable pitch/loudness/temperature settings remain reported
and omitted. Audio uses strict base64 decoding. Native errors are translated
without their payloads. The resolved canonical sample rate is now requested
explicitly; a conflicting legacy `speech_sample_rate` is refused. An implicit
common rate of 24 kHz is therefore requested as 24 kHz even for Bulbul v2, instead
of silently labelling vendor-default media. No provider, model, voice or language
fallback was added.

Setup publishes readiness only after configuration is sent. Failed/cancelled
acquisitions close their sockets. Completed and interrupted streams are detached;
the next text opens a fresh stream. Stale frames and stale EOF cannot change the
new turn. Sends cancelled mid-frame retire the stream; polling cancellation of
`recv()` does not. Close tasks remain owned if their caller is cancelled.

Source authority: Sarvam's current
[WebSocket reference](https://docs.sarvam.ai/api-reference/text-to-speech/stream),
[streaming lifecycle guide](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/web-socket)
and [audio-format guide](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/how-to/set-audio-format-for-output).
The implementation uses the existing websockets dependency, with no upgrade.

Executed 134 function assertions for config/request/response contracts, private
fields, model-conditional tuning, rate and text bounds, final state, malformed
audio/errors, setup/send cancellation, receive polling, late output and repeated
cleanup. A real loopback WebSocket plus the actual `TTSRealtime` manager passed
38 further assertions: framing, four stream lifetimes, successive turns,
interruption/resumption, playback queues, recording bytes, turn outcomes and
shutdown. The probe's initial outcome-enum import was corrected to its actual
common-contract owner; no product code changed for that probe error.

These are function/transport checks with controlled vendor messages. They do not
prove live Sarvam synthesis, human audio quality, or changed-build browser QA.
The existing test organization and configured providers must be preserved for
the final widget → agent/tools → admin conversation inspection. Full F0–F10
completion remains open; no migration or operator-data change is required here.

Regression gates: all 1,516 existing factory/capability/HTTP assertions, all 13
local type/import hooks, backend Ruff, documentation verification and diff checks
pass. Full-project Pyrefly remains at 562 errors with four existing suppressions;
the two Sarvam TTS files have no type diagnostics or suppressions. No frontend
or public API schema changed in this slice. The shared base config also excludes
the native credential after construction.

### F7 progress: Deepgram Aura TTS contracts and owned receiving

2026-09-09: traced the existing factory/config adapter, verification connection,
native receive/control path, manager queues, recording tap, completion and
interruption. Baseline function probes confirmed `Flushed` never completed a
turn, EOF left `is_connected` true, interruption and keepalive both sent `Flush`,
and cancelled acquisition leaked the separately created aiohttp session.

The adapter now uses the existing websockets 15.0.1 transport with manager-owned
receiving. There is no adapter audio queue or detached receive task to drop data
or swallow failures. Native config uses codec/rate enums and validates supported
pairs before I/O. `DeepgramTTSConfig` remains importable from its original adapter
module. Typed Speak/Flush/Clear requests and a discriminated control union replace
dict-key parsing. Metadata UUIDs and sequence integers are validated; warnings
remain nonterminal and do not fabricate completion. Unknown/malformed controls,
premature EOF and send failures become safe TTS failures.

`Flushed` retires the completed stream. Interruption detaches the old stream
before sending `Clear`, then closes it; a new reply opens a new connection.
Untagged late audio cannot affect the next turn, even while Clear's send awaits
I/O. The deliberate cost is one native handshake per utterance; persistent
cross-turn context support is not claimed. Keepalive uses WebSocket ping/pong,
not the rate-limited synthesis Flush command. Close tasks remain owned during
caller cancellation. This fixes the real stream lifecycle rather than only
annotating the old untyped queue and background task.

Authoritative sources: Deepgram's current
[Aura v1 stream API](https://developers.deepgram.com/reference/text-to-speech/speak-streaming),
[Flush](https://developers.deepgram.com/docs/tts-ws-flush),
[Clear](https://developers.deepgram.com/docs/tts-ws-clear), and
[media combinations](https://developers.deepgram.com/docs/tts-media-output-settings).
No migration to Flux TTS v2, SDK upgrade, default model or provider fallback.
The installed dependencies were aiohttp 3.14.3, websockets 15.0.1 and Pydantic
2.11.10; the existing websocket dependency replaces this adapter's HTTP session.

Milestone review, in the required order:

1. Boundaries: native schemas/state remain in the TTS socket; no module/DB access.
2. Architecture: the factory interface remains stable; the existing TTS manager
   owns receive scheduling, playback queues, recording and completion drain.
3. Data flow: 194 function assertions cover accepted/refused media pairs,
   private config projection, query encoding, controls, final/EOF/errors,
   interrupted and late output, cancellation and repeated cleanup. A real local
   WebSocket through `TTSRealtime` passed 38 further playback/recording/turn-outcome
   assertions across four stream lifetimes. A stalled real handshake cancelled
   cleanly and the loopback server observed TCP EOF.
4. Plan alignment: advances F7's native provider path, not full-platform
   completion. Changed-build widget/admin and live-provider QA remain required.
5. Readability/security/performance: enums, frozen config, ordinary control
   branches and typed frames replace dictionaries, manual query concatenation,
   the hidden queue and swallowed receive errors. The review found that the
   selected websocket library forwards additional headers across redirects.
   A provider-local redirect refusal now prevents that additional request; a
   two-listener loopback check confirmed zero requests at the redirect target.
   This uses the pinned library's inspected `process_redirect` hook, following
   the existing Gladia adapter precedent. Other header-bearing WebSocket adapters
   still need the same explicit redirect audit; no platform-wide security claim.

These checks use controlled vendor messages and placeholder credentials, not
live Deepgram synthesis or human audio acceptance. No operator config, DB,
migration, public API schema or frontend source changed in the adapter slice.

Regression gates passed: 1,516 factory/capability/HTTP assertions, all 13 local
type/import hooks, backend Ruff, documentation verification and diff checks.
Full-project Pyrefly reports 561 errors and four existing suppressions; neither
Deepgram file has diagnostics or suppressions. Deployment and browser evidence
follow below; they do not prove live Deepgram audio.

### Changed-build browser checkpoint and background tool-name correction

2026-09-09: rebuilt the local Eylo image and recreated only the API and three
worker/scheduler services. Preserved PostgreSQL/Redis volumes, the existing Eylo
Development org and configured providers. Retained the previous image under
`eylo-server:pre-type-hardening-20260909`. Existing console/widget processes serve
this checkout on ports 5173/5174; the initial restricted-network connection test
incorrectly suggested they were off. Duplicate startup attempts exited on occupied
ports; the existing processes were reused.

Logged into the console with the private development account and used the real
widget to create conversation `01a086a6-efbc-7980-ba97-78c09c245f4b` with QA Core
Mixed Agent. Fresh KB and memory calls returned the expected citation K1 and QA
color; both persisted results show successful Bedrock reranking. The console
shows completed user/assistant/tool exchanges. A separate QA Minimal Groq Agent
conversation returned the correct arithmetic result through the configured LLM.

The background result exposed a pre-existing dispatch mismatch, not a failed
memory credential: the exact published background revision advertised raw names
`memory_remember` and `memory_recall`, while context dispatch resolved suffixed
names. A read-only fixture from the real QA actor confirmed both names and its
valid memory binding. The background worker now builds its AgentSpec from the
same task context as dispatch, after resolving durable execution facts. Exact-name
refusal and per-call capability rechecks remain unchanged; no alias fallback.

A focused probe with that real actor fixture passed advertised/dispatched name
parity, repeated projection, exact actor identity, dispatch forwarding, raw-name
refusal and revocation refusal. External execution and availability refresh were
substituted in that probe. Subsequent live background runs completed, but did not
request tools: they do not prove live background tool dispatch. The changed worker
passes Pyrefly with zero errors. Broader F0–F10 completion and human/live voice
acceptance remain open.

The next widget test called `memory_remember` for a synthetic conversation
checkpoint, followed by recall. Dispatch succeeded but extraction returned no
changes and recall did not find the marker. Source tracing found that all levels
used a personal, year-long fact policy that explicitly rejects temporary task
context. This contradicts the agreed conversation working-memory purpose.
Extraction now selects criteria with the authenticated `MemoryScope.level`:
unchanged user policy, reusable Agent learnings, or conversation working context.
Prompt provenance advances to `memory-extraction-v3`; ownership, vector identity,
source-index validation and atomic application are unchanged. Existing facts do
not require reindexing. A focused function probe checks byte-for-byte user prompt
parity, all three scope selections through the real `_plan`, source provenance,
invalid owner refusal and no write-session acquisition during planning. Both
affected memory files pass Pyrefly with zero errors.

After rebuilding and recreating the four application services again, repeated
the same conversation-memory request through the widget. `memory_remember`
returned an `add` for the synthetic checkpoint "amber telescope", memory ID
`a24f40a5-a783-4e3d-8198-3865746ffaf2`. The subsequent `memory_recall` returned that
same ID/content at conversation level with Bedrock reranking applied. The widget
displayed both results live; the console showed the actual arguments, successful
results and completed messages. This is a verified write/read, not an inferred
success from assistant prose or a successful no-op.

A separate live QA SOR Audit Agent conversation,
`01a086b7-29a7-7d81-a6bd-75c5349283ec`, called `issue_search__ee9fc353` for `VER-50`.
The persisted result returned the Linear issue title, Done/COMPLETED status and
resolved assignee, reporter, team and cycle display values. Widget and console
agreed; all five persisted messages were completed. This exercises the authorized
SOR read projection, not a fresh vendor download or webhook delivery. No external
records were mutated.

All 13 local type/import hooks, backend Ruff, documentation verification and diff
checks passed after both corrections. Full-project Pyrefly remains at 561 errors
and four suppressions. The API is healthy; durable worker, ordinary-task worker
and scheduler run the rebuilt image. Existing DB, Redis and provider configs were
preserved. Console and widget remain running and logged in for continued QA.

Remaining browser findings and verification limits:

- Background participants hydrated from conversation aggregates enter the widget
  agent cache and can appear in the new-conversation chooser. Conversation summary
  conversion loses kind/selectability; the chooser uses the complete cache. Keep
  eligible selectable agents distinct from hydrated participant entities. No
  backend authorization bypass was tested or established.
- Console Refresh briefly clears the visible transcript during loading. Preserve
  existing data while background refresh runs; no persisted data loss was observed.
- Live background tool invocation, voice/audio, uploads, every vendor and external
  mutation/recovery paths were not exercised in this browser checkpoint. These
  results do not close platform-wide typing or product acceptance.

### F5 progress: Groq native synthesis contracts and ordered HTTP ownership

2026-09-09: followed configuration → factory → native HTTP request → WAV response
→ TTS manager → playback/recording. Added `groq_tts_wire.py` with owned model,
format and turn-state enums, frozen request/config models, private credentials,
named native limits and validated RIFF/PCM metadata. Shared TTS re-normalization
now preserves which fields were actually supplied: an implicit envelope sample
rate must not become an explicit native selection on a second normalization.
Groq uses its existing 48 kHz output contract when no native rate was supplied;
explicit incompatible rates now fail instead of being silently ignored.

The adapter's existing HTTP 503 path was reproduced before editing: it incremented
the failure counter twice, swallowed the first request failure and reported a
completed turn with no audio. The new worker preserves failure as failure. Source
inspection also found unordered concurrent requests, full-queue audio dropping,
a fixed 44-byte header assumption, and missing cancellation cleanup during
verification. Ordered requests, awaited bounded queue writes, chunk-aware WAV
parsing and owned cleanup replace those paths. No text is automatically replayed
after an uncertain external failure. Interruption discards its generation; a new
turn starts cleanly. Reconnect waits for retained cleanup even if the original
disconnect caller was cancelled.

Source evidence: installed aiohttp 3.14.3 and Pydantic 2.11.10; Groq's
[Orpheus reference](https://console.groq.com/docs/text-to-speech/orpheus) for the
four request fields, WAV output and per-request text bound; Microsoft's
[RIFF reference](https://learn.microsoft.com/en-us/windows/win32/xaudio2/resource-interchange-file-format--riff-)
for chunk sizes and word padding. Groq's generic API reference still contains a
PlayAI example and extra format/speed options absent from its Orpheus guide.
This change does not infer Orpheus support for those options. The 32 MiB response
bound is an Eylo adapter resource limit, not a claimed vendor limit. The existing
48 kHz PCM contract is now checked against the actual WAV header, not established
as a universal vendor guarantee by these sources.

Verification:

- 137 function assertions cover exact requests, secret exclusion, explicit rate
  refusal, raw/typed/repeated config normalization, fragmented RIFF headers,
  metadata and padding, malformed/truncated/wrong-format output, HTTP failures,
  ordered synthesis, finalization, backpressure, interruption, verification
  cancellation, retained cleanup and reconnect. Real `TTSRealtime` conversion
  produces identical 16 kHz playback/recording bytes from the 48 kHz source.
- 27 assertions through a real localhost aiohttp server cover streamed bodies,
  ordered output, non-success status, malformed audio, refusal to follow redirects,
  interruption, reuse after interruption, verification timeout and session close.
  Placeholder credentials only; the temporary server was closed.
- The existing 1,516 capability/factory/HTTP assertions pass for all 24 voice
  providers. All 13 type/import hooks and backend Ruff pass. Both Groq files are
  included in the voice hook and have zero Pyrefly diagnostics. Full-project
  Pyrefly remains at 559 errors and four suppressions.

A read-only lookup found no Groq TTS configuration in Eylo Development. Live
Groq synthesis, voice quality and complete-call acceptance remain unverified.
This slice is not deployed; the running console/widget and application services
remain on the preceding QA checkpoint. No operator configuration, DB or migration
was changed. OpenAI, Rime, Smallest and Murf native TTS work, other provider flows,
and full F0–F10 acceptance remain open.

### F5 progress: OpenAI speech contracts and shared HTTP lifecycle

2026-09-09: the OpenAI adapter reproduced the same swallowed HTTP 503 as the
previous Groq implementation: one failure incremented its counter twice, left
no completion error, and appeared as a successful empty turn. Independent tasks
also allowed request-order races, and a full audio queue dropped speech.

The verified ordered HTTP lifecycle now has one socket-owned implementation in
`sockets/tts/http_synthesis.py`. OpenAI and Groq supply their own Pydantic request
and audio decoder. No vendor types cross into platform modules. The generic
owner closes the surrounding response on errors/interruption, serializes text,
retains cleanup through repeated cancellation, waits before reconnecting, and
fails the current turn on HTTP errors. The removed Groq lifecycle enum and text
splitter now have a single owner rather than dead vendor copies.

OpenAI's request contract contains model, voice, input, speed and PCM format.
Model/voice IDs remain open strings intentionally: the API accepts operator IDs
and dated model aliases. Known wire format and numeric bounds are vendor-owned.
Verification now includes the configured speed, not a different request shape.
The raw PCM decoder preserves sample alignment across HTTP chunks and rejects
empty, dangling-byte or locally oversized responses; it cannot validate speech
quality. No new model, credential, SSE mode or custom voice-object support was
invented. Native 24 kHz output remains converted at the existing pipeline boundary.

Source evidence: the current OpenAI
[speech API](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)
specifies 4,096 input characters and speed 0.25–4; the
[TTS guide](https://developers.openai.com/api/docs/guides/text-to-speech#supported-output-formats)
specifies raw 24 kHz signed little-endian PCM16. Installed aiohttp/Pydantic are
unchanged. No provider or database configuration was modified.

Verification:

- OpenAI native/contract probe: **129 assertions**, including factory and repeated
  normalization, requests, speed bounds, secret exclusion, arbitrary PCM chunk
  boundaries, errors, ordering, cancellation and reconnection. The real
  `TTSRealtime` publication path delivered identical playback/recording bytes at
  the requested 16 kHz consumer rate.
- OpenAI real localhost HTTP streaming: **37 assertions**, including request
  parity, ordered audio, HTTP 503, redirect refusal, invalid PCM, interruption,
  verification timeout and resource closure. Synthetic audio/placeholder key;
  this is not live-provider acceptance.
- Groq regression: **137 native assertions** and **27 real localhost HTTP
  assertions** pass after extraction. No expected behavior was weakened.
- Changed shared/OpenAI files have zero Pyrefly diagnostics; full-project count
  decreased from **559 to 552 errors**, with four existing suppressions. This
  does not make platform-wide typing complete. Rime, Smallest, Murf, remaining
  provider flows and broader F0–F10 acceptance are still open.

### F5 progress: Rime native WebSocket contracts

2026-09-09: traced config → factory → native WebSocket → TTS manager → playback/
recording. The old adapter ignored the documented `chunk.data` audio event,
had a no-op flush, never signaled completion, and only drained a local queue on
interruption. The baseline probe reproduced dropped documented audio and absent
flush/completion. Its 500-frame queue also dropped overflow. These were native
protocol mismatches, not merely the nullable-socket Pyrefly error.

Contract-first correction:

1. Rime-owned Pydantic query/text/EOS models and discriminated chunk/timestamp/
   done/error events replace manual JSON keys. Closed protocol choices and
   numeric bounds have named owners. Operator model/voice IDs remain strings,
   secrets stay private, and query values are URL encoded.
2. Use the current documented `users-ws.rime.ai/ws3` JSON endpoint. It supports
   Mist and newer model families; the old `users.rime.ai/ws2` URL was not the
   documented JSON host. No operator model or voice is silently replaced.
3. Only raw PCM and mu-law are accepted by this adapter. Mist v1/v2 rates have
   their documented bounds; PCM sample alignment survives split frames. The
   existing pipeline still owns conversion to the consumer's media contract.
4. Receive directly through the manager and bounded native transport. EOS ends
   input; a batch `done` is not a final-turn fence. Completion requires valid
   audio and the normal close after EOS. A going-away code 1001 is not accepted
   as success despite belonging to `ConnectionClosedOK` in websockets 15.0.1.
5. Failed/cancelled sends and interruption retire the socket. Reconnect waits
   for retained cleanup, including cancellation of the disconnect caller.
   Receive-poll cancellation preserves the stream. Credential-bearing redirects
   are refused through the installed client's redirect hook, matching the
   established Deepgram adapter pattern.
6. Removed the false speed-control declaration. Timestamp messages are validated
   but not projected as aligned transcript support. No capability is inferred
   merely because the vendor can offer it.

Evidence: installed websockets **15.0.1**, Pydantic **2.11.10**; Rime's
[WebSocket overview](https://docs.rime.ai/docs/websockets),
[Mist JSON schema](https://docs.rime.ai/api-reference/mistv2/websockets-json), and
[current Coda JSON schema](https://docs.rime.ai/api-reference/coda/websockets-json).
Current Arcana documentation redirects to Coda. Existing model/voice catalog
aliases were not rewritten or proven live in this slice.

Executed verification:

- Native contracts/lifecycle: **128 assertions**, including invalid inputs,
  exact query/text serialization, bounded and malformed events, strict base64,
  timestamp validation, EOS, stale-stream refusal, cancellation and cleanup.
- Real localhost WebSockets: **35 assertions**, nine synthesis connections
  closed, 600-frame backpressure case with exact audio, error/EOF handling,
  interruption, consecutive turns, and no redirected credential handshake.
- Real factory/normalization/TTS publication code: **30 assertions**. PCM and
  mu-law, across raw and typed config forms, produce identical playback and
  recording bytes at the requested 24 kHz output rate.
- Scoped Pyrefly: zero errors. Full-project Pyrefly: **551 errors**, four
  existing suppressions. Backend lint passes. The local voice hook now includes
  both Rime files.
- The expanded voice type hook and **1,516 capability/API contract assertions**
  across 24 provider branches passed. Persistence/auth were substituted for
  these projection checks; no native provider connection was made. Documentation
  validation and `git diff --check` passed.

Focused review, in order: vendor protocol stays socket-owned; the existing
factory/manager remains the execution path; completion and audio units were
traced through sinks; protocol corrections are explicit plan additions from
source-backed failures; hidden queues, dropped frames and loose payload access
were removed. No remaining blocker found in the exercised function scope.
The close-code and redirect cases were added during this review, then rerun.

No live Rime credential/provider operation, UI change, deployment, migration or
commit in this slice. Local fixtures use placeholder credentials. Native vendor
acceptance and human voice QA remain unverified; the development services still
run the previous successfully tested build. Smallest/Murf and the rest of the
platform-wide F0–F10 work remain open.

### Local event registration and dispatch contracts

2026-09-09: the current full-project baseline was 551 Pyrefly errors. Forty-one
listener bindings declared every callback as accepting any `BaseModel`, erasing
the relationship between the registered event class and its handler. The emitter
also used an untyped attribute-forwarding proxy with an unused callable path,
although installed Pyventus 0.7.2 exposes `EventEmitter.emit`, not a callable
emitter. This was a static contract defect; no observed production emitter outage
is attributed to the unused callable path.

- `ListenerRegistration[Event]` and `ListenerManifestHealth` are now immutable
  Pydantic models. Registration construction checks metadata; `_entry` statically
  binds the event class to the callback's argument type. No broad callback cast
  or suppressed diagnostic is used.
- The heterogeneous manifest exposes a `LocalRegistration` protocol with checked
  `dispatch`. Because Pyventus routes by class name, dispatch refuses an unrelated
  model, including same-name collisions, before invoking the callback. Exceptions
  and cancellation pass to the existing subscriber failure boundary.
- Duplicate binding checks compare the original callable, preserving bound-method
  equality. The comparison-only `HandlerIdentity` accepts `Never`; callers cannot
  use that erased view to invoke a handler with an arbitrary event.
- Emission calls the typed PID-aware factory directly. Payload limits, best-effort
  failure returns, unordered concurrent delivery and per-process setup remain
  unchanged. No new event, persistence authority or vendor behavior is introduced.

Evidence: installed Pyventus 0.7.2 method signatures/source, checked against the
[official event workflow](https://mdapena.github.io/pyventus/latest/), and Pydantic
2.11.10. A temporary negative typing probe accepted the valid binding and rejected
an unrelated event/handler pairing. The probe was removed after execution.

Executed **53 function/runtime assertions** using real Pyventus: all 41 manifest
registrations and health projection, repeated setup, wrong-model/same-name
refusal, duplicate functions and bound methods, concurrent callbacks, exception
and cancellation propagation, PID-change recreation, oversized/unserializable
payload refusal and scheduling failure. A real Knowledgebase lifecycle event
passed through the full manifest/emitter/dispatch path to its existing bounded
logging projection. Synthetic callbacks covered concurrency; no product DB
listener or live WebSocket broadcast was invoked in this slice.

Focused review, in order: listener composition remains outside modules/sockets;
the existing emitter and manifest stay authoritative; class-to-handler dispatch
is checked without changing payloads; Pydantic conversion and proxy removal match
the typing plan; callable equality and PID recovery retain their existing
semantics. No remaining issue found in the exercised contract scope.

Full-project Pyrefly now reports **509 errors**, four existing suppressions,
down 42. The new local pre-commit/pre-push event-contract gate passes. Remaining
platform errors and native provider work are not complete. No deployment,
migration, provider reconfiguration, database mutation or commit in this slice.

### Browser voice session boundary contracts

2026-09-09: browser voice had 131 type errors, primarily because it accessed
pipeline resources through the deliberately narrow module-owned
`WebSocketSessionStatePort`. The runtime producer already supplies concrete
`WSSessionState`; extending the common port with every provider field would
erase the ownership boundary instead of correcting the consumer.

- Pipeline-owned resolution checks the concrete holder and preserves object
  identity. Optional cleanup remains a no-op without state; required startup
  reports the existing initialization error. An incompatible port is rejected
  before resource access, with no cast or type suppression.
- Cleanup, termination, silence policy and initialization retain that checked
  holder. A missing STT transcript queue now fails initialization through its
  rollback path instead of starting a detached consumer with `None`.
- Provider-failure dispatch captures a non-null callback before asynchronous
  event reporting. Ready signals use the context's transport identity. Voice
  state task callbacks now match the sender's boolean result type.
- The interaction-config protocol acknowledges that background-audio mappings
  are absent before configuration. It still writes the same canonical values;
  conversion of those remaining mappings into model objects is separate work.

Executed 48 function/runtime assertions: real `SessionContext`/`WSSessionState`
identity, narrow-port refusal, missing-state startup/cleanup, duplicate audio
initialization, config projection, real queue draining and child cancellation,
repeat cleanup, concurrent termination ownership, shielded caller cancellation,
provider-failure callback capture and ready-signal routing. External signaling
and event persistence were substituted. These checks do not prove native voice,
recording upload, or the full DB-backed startup path.

The expanded voice pre-commit/pre-push gate and backend Ruff pass. Full-project
Pyrefly is **377 errors**, four existing suppressions, down 132 from 509; the
browser file and interaction-config file are clean. The extra resolved error
was the shared interaction-config protocol at its telephony call site.

Both running UIs returned HTTP 200. Existing Eylo Development login and
conversation details remained usable; the widget navigated to its 15-entry
conversation list and reopened the existing mixed-agent exchange. The admin
still displayed its 28 persisted messages and actual completed tool results.
This is a navigation check of the previous build, not deployment or live proof
of this slice. No new agent turn, DB reset, migration, provider reconfiguration,
or commit. Remaining platform types and native provider work stay open.

### Browser audio ingestion and playback contracts

2026-09-09: followed browser binary ingestion through WebRTC media,
downsampling, STT forwarding, recording and outgoing playback. The shared
WebSocket pipeline resolver now serves browser lifecycle and audio ingestion;
the module-owned session port remains narrow. Session queues carry bytes and
the recorder field holds `AudioRecorder` explicitly.

- `AudioDownsampler` uses `DownsamplingMethod`, PCM16 arrays and immutable
  Pydantic buffer diagnostics. Its CPU JIT boundary validates native output;
  the SciPy bridge describes only the consumed public functions. No private SDK
  imports, unchecked casts or new suppressions were added.
- Reproduced a baseline division by zero when non-integer resampling produces
  one output sample. Mono and stereo kernels now select the first input
  position for that case.
- Reproduced incorrect planar stereo flattening before channel mixing. Media
  ingestion now interleaves planar PCM16 and validates frames/formats before
  recorder or provider effects. Packed PCM retains its previous result.
- Typed outgoing frames, queue access and buffer results preserve padding,
  interruption and playback-completion timing. Invalid ambient amplitude
  values, including infinity, use the existing bounded fallback.

Executed **150 function/runtime assertions**, including numerical parity for
24 method/rate/channel combinations, baseline regression reproduction, real
PyAV frames, real session holders/queues, exact recorder PCM bytes, actual STT
forwarder acknowledgement, rejected frame types, playback padding/timestamps,
interruption and a single post-drain completion callback. Only external
provider sending was substituted. The existing drop-oldest STT queue behavior
was exercised, not redesigned. The browser lifecycle probe remains separate.

A warmed local 5,000-iteration check measured approximately 1.12 microseconds
per 20 ms input frame before the JIT wrapper and 1.45 after; this is bounded
local overhead evidence, not a latency benchmark or speech-quality evaluation.
Installed numerical/media versions inspected: Numba 0.62.1, SciPy 1.16.3,
NumPy 2.3.4, PyAV 16.0.1 and aiortc 1.15.0.

The affected files have zero Pyrefly errors. Full-project errors are **328**,
four existing suppressions, down 49 from 377. Platform-wide hardening is still
open. This slice does not prove native microphone/ICE/vendor sessions,
recording upload or DB-backed startup; it has not been deployed. Chunk-boundary
resampler behavior and remaining loose interaction settings are follow-up work.

Post-slice checks: 48 browser-session assertions passed again; the expanded
voice type hook, backend Ruff, formatting and documentation/link/diagram checks
passed. Both existing UI servers returned HTTP 200. Browser navigation could
not run because the Mac was locked and automatic unlock failed. No fresh live
agent/provider result is claimed for this slice.

### WebRTC peer and negotiation ownership contracts

2026-09-09: followed audio tracks back through peer acquisition, signaling,
cached-answer replay and termination. Eight peer type errors came from resource
fields inferred as `None` and an awaitable callback passed to `create_task`.

- Reproduced `TypeError: a coroutine was expected` with a permitted Future-returning
  terminal callback. A retained coroutine now awaits the callback; completion
  observes failures and releases the reference without self-await during cleanup.
- The additional-track path passed a raw string to cleanup that reads
  `reason.value`. Added `BrowserVoiceTerminationReason.ADDITIONAL_AUDIO_TRACK`,
  retaining its existing wire value, and stopped the extra native track.
- Inspected installed aiortc 1.15.0: it emits track/state events, not the
  registered browser-style `icecandidate` / `icecandidateerror` callbacks;
  `RTCIceCandidate` has no `.candidate` field. Removed the dead callbacks and
  retained gathering/completed-SDP delivery. Native states, SDP kinds and Eylo
  commands remain separate enums. Close callbacks capture their original peer.
- Replaced negotiation/key dataclasses with Pydantic objects. Task handles are
  `Task[None]`; resource fields validate instances and are excluded from dumps.
  Immutable typed answers replace cached dictionaries; replay serializes a new
  projection. The manager supplies a validated `WebRTCOffer`, not arbitrary JSON.
- Normal owned ICE shutdown no longer logs a misleading relay failure warning.

Function/runtime QA: **46 peer assertions** and **50 negotiation assertions**.
Two actual local aiortc peers exchanged offers/answers and audio without any
external STUN/TURN server. Checked gathered candidate SDP, received Opus/PCM
frames, extra-track termination, task/track/peer cleanup and absence of late
callback errors. Manager checks covered simultaneous prepare, one config
resolution, tenant keys, preserved live identity, validated assignments,
resource-excluding serialization, immutable answer replay, no second peer,
candidate deduplication and one concurrent cleanup owner. External provider/DB
resolution, timeline writes and WebSocket delivery were substituted. This is
not native-vendor, microphone or UI proof.

Full-project Pyrefly is **320 errors**, four existing suppressions, down eight.
Peer, session models and signaling manager pass the expanded voice type hook.
Two inspected errors remain in WebRTC config/verification: the dataclass declares
`provider: str` but replaces it with an enum in `__post_init__`. This is static
contract drift, not proof that current provider verification fails. Next slice:
type the complete config-resolution/verification path and its remaining value
objects; keep provider HTTP outside the DB transaction. Full platform hardening,
deployment and operator browser QA remain open.

Final reruns passed: 46 peer + 50 negotiation + 48 browser-session + 150 media
assertions. Backend Ruff, formatting, hook configuration and documentation
validation passed. Focused review followed boundaries, architectural ownership,
source-to-sink flow, plan adherence and readability in that order: no module
imports SDK/pipeline types, candidate policy still precedes peer acquisition,
cached replay remains tenant-bound, live resources retain identity and no new
DB/network work enters the audio hot path. Public request/candidate/cleanup
envelopes still contain older dictionary/string contracts; their hardening is
not implied by the typed answer or zero-error peer files. No deployment or
operator configuration change in this slice.

### WebRTC material, verification and browser ICE contracts

2026-09-09: replaced WebRTC config/resolution and verification dataclasses with
frozen Pydantic values. Provider type remains an enum from validation through
verification; settings and credentials have separate owned models. Pipeline
composition explicitly exports secrets to sockets and projects native ICE
objects into browser-only models. No module imports a socket or SDK type.

Runtime probes caught and repaired two implementation errors before deployment:

- An undiscriminated settings union tried Metered first for Turnix. Domain-error
  conversion aborted union branch fallback. Explicit tags now select the matching
  validator; the provider/settings agreement check still rejects mismatches.
- Shared provider snapshots hold mapping proxies. Strict model validation rejected
  those despite accepting plain-dict fixtures. Explicit mapping copies now cover
  the real pinned-config input and credential shapes.

Executed: 42 config/serialization assertions and 34 authority/transaction
assertions. Both vendors compose to their actual socket configs; omitted settings,
normalization, finite bounds, malformed inputs, private serialization, browser
TURN output, org/config/capability mismatch refusal, detached verification and
stale-revision propagation passed. Transaction and service I/O were substituted;
these are not encrypted DB round-trip or live TURN-provider proofs.
The existing local aiortc negotiation probe also passed all 50 assertions after
the final edits, including concurrent prepare, cached replay and cleanup.

Focused milestone review, in order: domain models remain module-owned; pipeline
composition is the only bridge to socket configs; mapping-proxy inputs and browser
serialization are exercised end to end within the local contract; the plan's
native wire-model work remains explicitly open; named value objects replace
post-construction type mutation without adding persistence or transport machinery.
Existing nullable transport overrides retain their previous validation boundary;
this slice does not silently reinterpret explicit null as an omitted default.

The WebRTC config module, pipeline and STUN/TURN socket paths are type-clean and
included in the existing local voice hook. Full-project Pyrefly is **313 errors**
with four existing suppressions, down seven. Native vendor request/response
dictionary contracts and remaining signaling envelopes remain pending; a clean
type check does not claim those dictionaries have been replaced.

Live UI QA used the existing deployed build and existing Eylo Development org:
signed into the console, sent `QA_CONFIG_FLOW_20260909` through the widget, then
inspected the conversation detail. `kb_query(top_k=1)` returned Cedar Lantern
with citation K1 and Bedrock reranking; `memory_recall` returned amber observatory.
All eight new persisted messages, including both tool calls/results and the
background observer completion, were completed (36 total messages). The expired
admin login returned to the original conversation after signing in. No provider
configuration was changed. This browser result does not validate the undeployed
WebRTC changes or live microphone/provider cleanup.

Widget navigation returned to the 15-conversation list and reopened the configured
Groq conversation. `QA_GROQ_NAV_20260909` correctly recalled the earlier 17 × 23
calculation and 391 result without tools. Console search (`q=Groq`) returned four
conversations; opening the latest showed all four messages completed, including
the new request/response. Both UI tabs remain open for the operator.

Next at this checkpoint: finish native STUN/TURN wire contracts and signaling envelopes; rerun
local peer/negotiation checks, then deploy a coherent milestone and repeat
provider/voice QA. No schema migration or Git operation is part of this slice.

### STUN/TURN native credential wire contracts

2026-09-09: continued the WebRTC data flow through the fixed Metered and Turnix
HTTP endpoints. Installed Pydantic 2.11.10, HTTPX 0.28.1 and aiortc 1.15.0 were
used for validation. No dependency changed.

- `MeteredCredentialQuery` owns explicit API-key query export.
- `TurnixCredentialRequest` replaces the reflective field-name/getattr dictionary
  with six explicit fields selected from the validated native config. Client IP
  and bearer auth remain headers, not body fields.
- `IceCredentials` and `IceServer` validate consumed response data before native
  construction. Both prior list/envelope shapes remain accepted, including
  mapping proxies; supported URL schemes are a socket-owned enum. Unknown vendor
  metadata remains ignored. Native peer values and browser output remain unchanged.
- Config and response credentials are excluded from ordinary dumps. Retry count,
  delay, endpoint pinning and Metered's existing TLS exception are unchanged.

Sources: [Metered GET credential](https://www.metered.ca/docs/turn-rest-api/get-credential/)
and [Turnix POST ICE credentials](https://turnix.io/docs/api-ice-credentials).
Turnix's parameter table and Dart/Java examples use `preferred_region`; some
other examples misspell it `preffered_region`. The implementation retains the
documented parameter-table spelling rather than adopting the inconsistent typo.

Executed function QA: **66 assertions** through actual config models, factory,
adapters, HTTPX request construction, parser and native ICE outputs. HTTPX
MockTransport substituted vendor I/O. Checked root/envelope/mapping inputs,
unsupported/malformed consumed fields, empty/STUN-only refusal, optional null
credentials, metadata tolerance, secret-excluding dumps, exact query/body/header
placement, transient 503 recovery, malformed-response retry exhaustion and
cancellation during an in-flight request. All created clients closed; cancellation
made one request and did not retry. These are not live vendor or TLS proofs.

Native wire models now complete this part of F7; signaling envelopes and broader
platform contracts remain open. This slice adds runtime contracts to files that
were already statically clean, so it is not a claim of further type-error reduction.
Final checks passed: the existing 42 config and 34 authority/transaction assertions,
backend Ruff, the expanded local voice type hook, formatting and documentation
validation. Full-project Pyrefly remains at 313 errors with four suppressions.
No DB, migration, provider config, deployment or Git operation changed.

### WebRTC signaling request, response and failure contracts

2026-09-09: extended the same flow through authenticated WebSocket handlers.
`requests.py` validates prepare, offer and candidate input before negotiation
lookup. `schemas.py` owns immutable response values; `errors.py` owns signaling
and ICE-policy failure enums. Cleanup reasons and steps are named enums. Handler
serialization preserves the existing widget protocol, including its distinct
accepted `candidate` and rejected `ice_candidate` command names.

Deliberate tightening: booleans, floats and strings no longer masquerade as
integer protocol versions. Consumed candidate metadata is validated even for a
replayed candidate. When several input fields are invalid, validation reports
the first contract field rather than the previous hand-written check order.
Direct/nested/null candidate shapes and unknown-field tolerance remain supported.

Executed handler/input/output QA: **66 assertions** using real Pydantic models,
session context and WebSocket envelopes, with manager I/O substituted. Covered
malformed inputs, exact browser ICE serialization, omitted auth/null expiry,
request correlation, not-configured responses, safe generic failures, candidate
and offer rejection codes, and idempotent hangup output. Two initial probe fixture
errors (list instead of immutable ICE URL tuple, non-API configuration path) were
corrected against the actual contracts; they were not product failures.

The local voice typing hook now explicitly includes the new request/error files,
ICE policy and WebRTC handlers. At this checkpoint candidate parsing still used
a dataclass and native protocol literals; the following slice closes that gap.
Whole-platform typing remains in progress. No DB, migration, provider config or
Git history changes are required.

Final checks: 50 actual local aiortc negotiation assertions passed, alongside
the 66 signaling assertions, expanded voice type hook, backend Ruff and docs
validation. External services were substituted for the loopback negotiation;
this is not live provider or browser audio QA. Changes remain undeployed pending
the next coherent runtime/browser QA milestone.

### ICE candidate values and admission boundary

2026-09-09: replaced `RemoteIceCandidate` with a frozen Pydantic model. ICE
component, transport, candidate kind and TCP mode are owned enums. Supported
extension pairs become a typed model at parsing; unknown extensions remain
ignored. Candidate syntax, numeric bounds and the shared admission cap now have
named constants. The manager explicitly exports primitive enum values to aiortc.

Network policy is unchanged: public addresses are permitted, local ranges and
mDNS require local mode, and unspecified/multicast/metadata targets are refused
in both modes. No DNS resolution or DB/provider I/O was added. Known TCP modes
remain valid on UDP candidates, but unknown `tcptype` values are now rejected
there too instead of passing an unchecked value into the peer library.

Executed **242 function assertions** covering all enum combinations, normalized
input, numeric bounds, optional/duplicate/unknown extensions, invalid input,
both deployment modes, immutable values, JSON representation and SDP filtering
at the candidate cap. **50 real local aiortc negotiation assertions** also
passed; external services were substituted. This does not prove live browser
audio, TURN-provider operation or whole-platform typing completion.

### Telephony prepared intent and persisted owner

2026-09-09: continued from browser transport into the telephony lifecycle.
`prepare_outbound_call` now compares immutable typed intent projections, then
passes explicit typed arguments to call creation instead of unpacking a mixed
dictionary. The module-owned provider/direction enums validate the projection;
UUID normalization reuses `EyloBaseSchema`. Invalid stored intent becomes a
`CallLifecycleConflict`; mismatched fields retain the conflict outcome with a
single generic message rather than reflective field-name diagnostics.

`CallLifecycleStatusResult` is a frozen Pydantic value. `TelephonyCallInDb` now
uses the existing required-organization schema, matching its non-null DB column.
No migration or transaction/locking behavior changed. Transfer metadata, status
history and other telephony provider contracts remain separate unfinished work.

Executed **84 function assertions** through the real lifecycle, creation service,
ORM model and Pydantic result, substituting DB transaction/repository I/O. Checked
explicit persisted fields, replay without another save, every intent-field
conflict, invalid stored provider, absent/null owner refusal, immutable result
and retained nested result identity. These are not carrier, database concurrency
or live callback proofs. Added lifecycle to the existing telephony type hook.

Both affected type hooks and backend Ruff pass. Full-project Pyrefly is now
**291 errors (four suppressions)**, down from 313; required call ownership also
resolves downstream optional-owner diagnostics. The overall hardening goal is
still incomplete.

### Telephony carrier material and verification contracts

2026-09-10: replaced the telephony config/resolved dataclasses with immutable
Pydantic material. A provider-discriminated union pairs each carrier's settings
and credentials. Mapping input is accepted only at `from_payload`; persistence
uses explicit `settings_values()` and `secret_values()` exports. Runtime socket
construction passes typed attributes, preserving the module/socket enum boundary.
The status callback still uses its existing signature adapter's mapping contract,
fed by these explicit exports. Webhook signing policy was not changed.

Resolved material now checks the effective snapshot's organization and telephony
capability, retaining the exact config identity/revision. Credentials are excluded
from normal model dumps and repr. Existing HTTPS, Exotel-host, PEM and required
field checks remain; malformed shapes produce safe domain errors rather than
Pydantic diagnostics containing input. Carrier verification results, fingerprint
metadata and the socket probe result are typed immutable values too. Account
references are excluded from ordinary probe-result serialization.

Runtime QA caught an initial import failure: inheriting the shared wildcard
before-validator conflicts with a field-discriminated union. Carrier values now
use a plain Pydantic base; only resolved UUID fields apply shared normalization.
This was an implementation regression caught before deployment, not a live
carrier failure. The Plivo probe fixture was also corrected to its installed
SDK's syntactic account-ID format before asserting successful client creation.

Executed **244 function assertions** for all four carrier models, native factory
construction/cleanup, normalized persistence exports, secret exclusion, invalid
fields, foreign model subclasses and authority mismatches. Another **21 boundary
assertions** exercised config creation and revision-safe verification using the
real service/use-case/result models with persistence and network probes replaced.
No external carrier calls or operator config changes were made. Expanded the
telephony hook to include config service, verification contracts and status routes.
Native request/response bodies, signature-adapter dictionaries and remaining
telephony status/transfer contracts still need subsequent flow-based hardening.

### Telephony canonical callback status and scheduled agent identity

2026-09-10: preserved `CallStatus` and module-owned `TelephonyProvider` from
callback mapping through controller dispatch. Removed the mixed `Any` keyword
dictionary at the lifecycle call; canonical status, terminal reason, duration
and timestamp now cross that boundary as explicit arguments. Retry limits have
names without changing their values. Native callback dictionaries/status maps
remain an unfinished vendor boundary; this slice does not claim they are typed.

Executed **133 function assertions** through actual callback controller, call
lifecycle, status service and ORM/schema projections, with transactions,
repositories, durable filing and event delivery substituted. All four existing
provider callback mappings reached the expected canonical completion. Repeated
terminal callbacks and stale ringing updates did not file another terminal fact
or emit another terminal event; terminal reason, duration, provider mismatch and
post-transaction emission were checked. Exotel's direct controller function was
covered, not its public route: authenticated Exotel callbacks remain unsupported.

The scheduled-call tool now validates its participant's string agent identifier
as a UUID before calling the scheduler. Removed six write-only private-helper
`__eylo_hidden__` assignments (five telephony helpers and one scheduler helper);
the explicit registration manifest, not those attributes, owns tool visibility.
**20 function assertions** checked scheduler input, invalid-ID refusal, actual
registration and exclusion of all six helpers. Tool docstrings and public slugs
were not changed. Added callback/controller and telephony tools to the existing
telephony typing hook. No operator schedules, calls or provider state changed.

Full-project Pyrefly is **283 errors (three suppressions)**, down from 291.
The telephony type hook, runtime-import hook, backend Ruff and documentation
validation pass. Live callback delivery, DB concurrency and browser QA remain
unverified for these undeployed changes.

### Telephony silence lifetime and completion metrics

2026-09-10: reproduced three Pyrefly errors in the silence monitor's reminder
closure. Startup validated nullable call fields, but the closure reread them.
Teardown already cancels and awaits policy tasks before discarding the live
buffer; this was not a reproduced production disconnect failure. The monitor now
retains the narrowed TTS, buffer, conversation and registered WS state references
for its lifetime. Missing setup still returns, a missing registered session still
raises, ordinary reminder failure releases the activity gate, and cancellation
still propagates.

The same completion flow now retains objects instead of assembling an untyped
metrics dictionary. STT factory and runtime expose detached snapshots; the
runtime model owns its factory-counter projection. `CarrierAudioMetrics` and
`CallAudioMetrics` belong to the telephony pipeline, not the transcript module or
vendor sockets. The pipeline adds the terminal-reason enum and serializes only
for logs and canonical persistence. Existing stored keys, absent branches and
nested null measurements remain unchanged. `VoiceSessionCompletionResult` is a
frozen Pydantic model; its `changed` field remains an intrinsic strict boolean.
The completion command explicitly accepts a JSON-valued metrics dictionary at
the persistence boundary, without importing socket or pipeline models.

Executed **90 function assertions**: 34 through the silence-monitor callbacks,
real policy-speech capture/TTS queue and cancellation/drain path; 56 for metric
snapshots, storage-shape parity, detached counters, validation and actual call
finalizer → voice completion → ORM assignment. DB sessions, durable event filing
and nudges were substituted. Both normal metrics and metrics-collection failure
completed the ORM transition; injected nudge failure remained nonfatal. No live
vendor request, operator data or database schema changed.

Full-project Pyrefly reports **280 errors (three suppressions)**, down from 283.
Added telephony voice/metrics and voice completion to the telephony contract hook.
Live provider, real DB concurrency and changed-build browser checks remain open;
these function checks do not establish those outcomes.

### Recording upload work and cancellation contracts

2026-09-10: replaced the worker's conditionally initialized scalar locals with
`RecordingUploadStaged | RecordingUploadFinished`. DB loading now returns a
detached snapshot or receipt; success projection also returns a receipt rather
than an ORM row outside its transaction. Raw audio fields are excluded from
snapshot serialization. Queue inputs remain organization/recording IDs only,
validated without stringifying arbitrary objects. Receipt wire keys and state
values are unchanged; `deleted` remains a missing-row outcome, not a DB state.

Recording-owned track/effect/retention enums replace free-form track strings and
the staged-retention selector. Transcript track roles remain separately owned.
Upload/cancellation results now use frozen Pydantic models and the Absurd step
adapter preserves its operation's generic result type. Provider resolution, PUT,
canonical projection and post-commit delivery nudging retain separate phases.
The shared outbound receipt and authorization/outcome models were addressed in
the following slices. Generic durable-service return types and open-ended
recording metadata remain broader hardening work; this slice does not claim
those boundaries are finished.

QA exposed a control-flow defect: `CancelledTask` is an `Exception`; generic
upload failure handling caught it. On the last allowed attempt, failure handling
returned a normal failed receipt, bypassing cancellation fencing. A function
regression reproduced this before the fix. Load/resolution/upload cancellation
now propagates directly to the existing cancellation owner. Ordinary retry and
terminal-error behavior remains unchanged. This is a supported runtime cause,
not an inference from the original unbound-local diagnostics.

Executed **338 function assertions** through real worker methods, durable-work
services, ORM objects, storage runtime/factory and filesystem PUT/inspection/
streaming. DB sessions, outbound ledger execution and event delivery were
controlled. Checked synthetic track bytes/digests, successful/cached receipts,
stable per-track operation names, missing config/audio/key, unbound/deleted work,
uncertain uploads, last-attempt cancellation, accepted/unsent/uncertain fencing,
fencing failure and process-task cancellation. Snapshot privacy, invalid IDs,
enum identity, frozen results and generic step results were also checked.

Live S3, real DB locking, process crashes and changed-build browser QA remain
unrun. No operator recording, provider configuration, migration or deployed image
was changed. Added the recording contracts and worker to the existing local
voice type gate.

Full-project Pyrefly reports **269 errors (three suppressions)**, down from 280.

### Shared outbound receipt and checkpoint contract

2026-09-10: `OutboundExecutionReceipt` now uses frozen, strict Pydantic validation
instead of a dataclass and separate manual checkpoint parser. DB projection,
direct construction and checkpoint replay share the lifecycle rules. Typed JSON
serialization preserves all seven keys and explicit nulls. UUID/state strings
are decoded explicitly; arbitrary stringifiable objects, numeric coercion and
unknown checkpoint fields are refused. Existing checkpoints produced by Eylo
remain compatible; no migration or checkpoint-version change is needed.

The outbound outcome union is narrowed explicitly instead of probing for
`failure_code` with `getattr`. Shared owner/state vocabulary remains in
`common/outbound.py`; this pipeline-owned receipt does not cross into sockets or
modules. Sender execution remains outside the ledger's short DB transactions.

Executed **608 function assertions** covering lifecycle combinations, strict
types, bounds, frozen instances, required fields, JSON parity, UUID library
conversion, wrong-attempt replay, all send outcomes, retry without checkpoint,
replay without resend, preflight failure and cancellation. Checks use actual
outbound services and ORM models with controlled DB sessions and senders; they
do not prove real locking or remote effects. Re-ran **338 recording-worker
assertions**, including actual temporary filesystem uploads and readback.

The receipt and its recording/email/MCP/number-management consumers pass targeted
Pyrefly. Added the shared bridge to the existing local voice type gate. Broader
typing work and changed-build browser/provider QA remain open.

### Shared outbound inputs and provider outcomes

2026-09-10: converted outbound identity, attempt specification, authorization and
the four provider outcome variants from dataclasses to frozen, strict Pydantic
contracts. Normalized operation/failure identifiers, stable UUID seeds,
idempotency keys, destination normalization and fingerprint values are retained.
The owner boundary accepts actual stdlib/uuid-utils UUID objects; arbitrary
objects and plain strings cannot masquerade as typed owner identities. Nested
identity instances are revalidated. Provider/owner enums remain common-owned;
native failure categories remain adapter-owned.

SMTP and SendGrid positional outcome constructors, including SMTP's dynamically
selected failure class, now use explicit `failure_code` keywords. No native
request, retry classification, credential placement or connection policy changed.
Shared status limits are named constants used by both outcomes and receipts.

Executed **357 new function assertions** for identity/hash/fingerprint parity,
normalization, strict types, immutable/nested contracts, and real SMTP/SendGrid
planning/outcome code using controlled transports. The SendGrid path also ran
through the actual outbound service and ORM projection with controlled DB
sessions. Re-ran **608 outbound receipt** and **338 recording-worker assertions**.
These checks do not establish live email delivery or real DB concurrency.

All **20 constructor/consumer files** pass targeted Pyrefly. The new local
`python-typed-outbound-contracts` hook covers them explicitly; receipt checking
moved out of the voice-only gate into this shared gate. Full-project Pyrefly
remains **269 errors (three suppressions)**. Broader checks still report existing
deletion-query/campaign-owner issues and two email config annotation errors.
Email's config dataclass declares `provider: str` but replaces it with an enum
at runtime; this is an annotation/contract mismatch, not evidence that native
verification failed. The following slice addresses email config validation →
provider resolution → socket construction → verification/delivery.

No operator config, schema, deployed image or remote provider state changed.
Changed-build widget/admin QA remains pending the unlocked Mac and rebuild.

### Email configuration, resolution and verification material

2026-09-10: replaced `EmailProviderConfig`/`ResolvedEmail` dataclasses and mutable
settings/credential mappings with frozen Pydantic material variants. Module-owned
SendGrid/SMTP settings and credentials remain separate from socket schemas.
`SMTPSecurity` replaces free-form in-process security mode; public values are
unchanged. `from_payload` validates the existing persistence/API shape and exports
typed JSON settings or explicit plaintext secrets only at those boundaries.

The pipeline constructs socket settings explicitly from typed fields. Resolution
passes material directly rather than round-tripping through dictionaries, and
checks organization/capability/config identity plus positive revision. Credentials
retain their exact bytes, including intentional whitespace; repr/normal model
serialization excludes them. Missing/unknown fields, invalid types and non-finite
timeouts fail early. The existing SMTP public-host and secret-replacement rules
remain in their owning domain/service.

Verification receipts now carry an email-provider enum and a positive revision /
aware timestamp. The verifier closes its factory on success, failure and task
cancellation; the use case rejects a mismatched provider receipt before marking
the config verified. DB read → external verification → expected-revision update
remains split into short transactions. This strengthens the contract; it is not
a claim that existing stateless adapters leaked live connections.

Executed **251 function assertions** covering normalization and socket parity,
private output, immutable exports, encryption/decryption round trip, malformed
settings/secrets, both SMTP security modes, resolved identity, public response
masking, service updates, pinned revisions, stale verification, mismatched
receipts and cleanup. Ran config creation → shared provider service → resolution
→ actual SendGrid planning → actual outbound service/ORM receipt → delivery
result with controlled repositories, DB sessions and HTTP transport. Wrong-org
resolution did not send. No real provider request or operator data was changed.

The complete email module/pipeline/socket paths pass targeted Pyrefly; the local
`python-typed-email-contracts` hook now covers them. Full-project Pyrefly reports
**265 errors (three suppressions)**, down from 269. Socket-native webhook/response
payloads, email tool/delivery result dataclasses and campaign caller ownership
remain subsequent data-flow work; a passing type gate does not close those gaps.
Changed-build browser QA remains pending. No migration or deployment occurred.

### Email delivery and agent-tool outcomes

2026-09-10: replaced delivery/tool result dataclasses with frozen Pydantic
contracts in `pipelines/email/contracts.py`. Named enums own delivery status and
tool errors. Success/error content and receipt metadata are validated together;
the error flag and existing JSON views are derived at the framework boundary.
The tool reads typed agent bindings directly, retaining the committed TOOL_USE
owner ID, exact config revision, cancellation and retry propagation.

Campaign and campaign-contact persisted DTOs now require `organization_id`, as
their ORM columns already do. This is a schema-contract correction, not a DB
migration. The expanded email type gate covers the conversation tool dispatcher
and campaign email/voice consumers.

Executed **171 function assertions** for delivery projections, immutable values,
invalid/contradictory outcomes, JSON parity through framework `ToolResult`,
required campaign ownership, conversation/background context dispatch, missing
bindings, malformed input, exception classification and cancellation propagation.
The sender was controlled: no email was sent. Re-ran the existing **251 email
config/delivery assertions**, including actual service/resolver/SendGrid planning
and outbound receipt code with controlled repositories and transport.

Full-project Pyrefly now reports **256 errors (three suppressions)**, down from
265. Native email webhook/response payloads and broader campaign config typing
remain pending; passing this slice does not complete platform-wide hardening.
No operator data, migration or deployment changed. Changed-build browser QA
remains required below.

### SendGrid native request, response and event contracts

2026-09-10: traced email socket callbacks before extending typing. No email
webhook route, campaign consumer or call site currently uses `process_webhook` or
`transform_to_platform_response`. Kept these adapter contracts, but did not build
or claim a webhook delivery-status pipeline.

`sockets/email/sendgrid_wire.py` now owns the executable v3 mail request subset:
addresses, envelopes, content, attachments and Eylo's custom attempt argument.
The adapter constructs objects, then serializes the native keys once. Scope
verification validates a native response model before checking the required
scope. Unrelated response fields and unneeded scope names do not need platform
enums. Known event names use a vendor enum; consumed webhook fields are typed,
extension fields are validated JSON, and malformed/unknown events fail rather
than being stringified or given an epoch-zero timestamp. The original batch
authentication/ingress feature remains absent, not implicitly enabled.

Removed `Any` from email adapter response and callback interfaces. Concrete
response translators narrow actual HTTP responses or SMTP reference strings;
arbitrary objects no longer become string message IDs. Neutral response/event
metadata is finite JSON. This is an adapter contract correction, with no DB/API
schema change or new public endpoint.

Verified against current official SendGrid v3 references (linked in provider
architecture) and local Pydantic 2.11.10 / HTTPX 0.28.1. **142 function assertions**
cover full/minimal native payloads, a native JSON round trip, omission of absent fields, priorities,
attachments, scope validation, 11 event kinds, metadata, malformed inputs and
real verification-client construction using a controlled HTTPX transport.
Re-ran **251 email config/delivery** and **357 outbound** assertions: all passed.
No email or webhook was sent to a vendor; no operator configuration was changed.

The native `from` field uses Pydantic's documented
[annotated alias pattern](https://docs.pydantic.dev/2.11/concepts/fields/#field-aliases),
so Python construction uses `sender` while validation/serialization accepts the
native name without casts or type-checker suppression. Full-project Pyrefly is
unchanged at **256 errors (three suppressions)**; replacing previously permissive
`Any` boundaries adds runtime coverage that the error count alone cannot measure.

Next email slice: delivery-plan/capability dataclasses and SMTP native result/error
categories. Broader platform typing and changed-build browser QA remain open.

### Email delivery plans and SMTP result/cleanup contracts

2026-09-10: replaced the remaining email delivery-plan/capability dataclasses with
strict frozen Pydantic values. `EmailCapabilitySupport` replaces capability
booleans; current SMTP and SendGrid both declare unsupported idempotency and
reconciliation. The sender is runtime-only, excluded from JSON/schema/repr.
Attempt identity and bounded operation/origin fields are checked before use.
`SMTPFailureCode` replaces free-form failure categories, and a named delivery
phase distinguishes preflight from sending. Native SDK result types stay in the
adapter; no duplicate framework-owned SMTP response type was introduced.

Tracing the actual aiosmtplib 5.1.1 API (manifest, lock and installed source agree)
exposed three defects, reproduced before edits:

- A normal `send_message` return could contain rejected recipients, but the result
  was discarded and reported as success. It now becomes `UNKNOWN` with
  `smtp_partial_acceptance`; the durable ledger prevents replay of the whole
  envelope. No per-recipient retry or partial-success product mode was added.
- Cancellation during `sock_connect` skipped socket close. Cleanup now covers
  cancellation and other exceptions, propagating them after close.
- SMTP client construction occurred before the cleanup region. Construction now
  happens inside it; final cleanup also closes the client transport if QUIT or
  async context teardown fails.

The old function probe returned `None` from its SMTP fake and used invented
prewire error strings. That did not model the SDK's real result shape. Updated
the fixture to the actual `(refused_recipients, response_text)` tuple and current
error enums without weakening the existing expected lifecycle outcomes.

Executed **191 function assertions** covering plan validation/serialization,
exact attempt authorization, both TLS modes, lifecycle cleanup, DNS/address
rejection, connect retry/cancellation, SMTP response classification and the real
SDK's `send_message` path with a controlled `sendmail` result. A separate
**273-assertion receipt/SMTP probe** ran the native result through actual outbound
service/ORM/receipt code, using controlled DB sessions: a partial send persisted
UNKNOWN, then checkpoint replay and DB-only replay both avoided a second send.
Re-ran **251 email configuration/delivery** and **357 outbound** assertions.

This verifies local contracts, not a live SMTP delivery, TLS handshake or real
PostgreSQL concurrency run. No operator data, deployment or schema changed.
Full-project Pyrefly remains **256 errors (three suppressions)**. Next: finish
campaign configuration and dispatch contracts into their remaining type errors.
Browser QA remains open.

SendGrid follow-up: adapter-owned failure codes now use `SendGridFailureCode`;
HTTP classifications use `HTTPStatus`, and the response-body limit, operation
name and shared provider-reference bound are named constants. Persisted failure
values and delivery classifications are unchanged. The common egress error
vocabulary remains common-owned rather than being duplicated as a vendor enum.
The 357-assertion outbound contract probe and repository Python lint pass again.

### Shared revision contracts and campaign consumer follow-through

2026-09-10: following campaign publication and dispatch exposed common revision
values still implemented as dataclasses. `DefinitionRef`,
`DefinitionHeaderState` and `PublishedRevisionState` now use strict frozen
Pydantic models. Owning services explicitly decode persisted lifecycle and
availability strings to their enums. UUID library normalization remains local;
positive revisions, revocation metadata and timezone checks remain enforced.
Header transitions and revocation construct validated values, not unchecked
`model_copy(update=...)` projections. The intrinsic `draft_dirty` predicate is
unchanged; it does not replace the lifecycle enum.

Native constructors now reject wrong primitive types and extra fields with
Pydantic validation errors. Existing valid transitions and domain-invariant
errors retain their outcomes. JSON round trips use Pydantic's explicit JSON
boundary; arbitrary native UUID strings are not silently accepted. No persisted
enum values, columns or publication policy changed.

Verification:

- Earlier function matrix: **895 assertions**, including real ORM translation
  helpers for agents, swarms, templates, MCP servers and tools.
- Current recheck: **768 assertions**, including lifecycle comparison against
  the pinned pre-conversion `fbb877f1`, strictness, JSON round trips, all revocation
  metadata presence combinations, and campaign/MCP exact revision reads. The
  latter exercise actual repositories and query construction with controlled DB
  responses: organization, resource, exact revision and deletion scope remain
  present. They do not prove live DB isolation or commit behavior.
- Full type checking found a positional `DefinitionRef` call in swarm handoff.
  Converted it to named arguments; **10 assertions** execute that branch with
  real context/agent/ref models and a controlled downstream handoff, covering
  borrowed-session and owned-transaction routing without committing or closing
  borrowed resources. This is not live handoff execution.
- Expanded the local publication type hook to include common revision values
  and the handoff dispatcher. It passes, as does Python lint.
- Full-project Pyrefly: **244 errors, three suppressions**, down from 256 before
  this revision slice. No remaining diagnostics reference these revision types.

The checkout advanced to `5ed452db` during continuation, incorporating the
revision-model edits. A temporary parity probe initially compared against this
new `HEAD`; it was corrected to the verified pre-conversion commit, not by
weakening assertions. No commit was created by this continuation.

Remaining campaign work: nullable exact template references, typed channel and
outcome contracts, contact selection/preparation and repository projections.
The broad plan also still requires remaining dataclass/value conversions,
vendor request/response contracts and changed-build product QA. Passing this
slice does not establish platform-wide completion.

### Template values and exact campaign message references

2026-09-10: converted `CompiledTemplate`, `TemplateSegment` and
`RenderedTemplate` from dataclasses to strict frozen Pydantic values. Compiled
variables retain independently owned read-only mapping semantics, with explicit
serialization. Program validation also runs on native/JSON restoration. Render
validators check segment/text agreement, declared variables, renderer version
and draft-versus-exact source identity. Preview and exact rendering use validated
source binding rather than `dataclasses.replace` or unchecked model copying.

Campaign start/render now resolves optional template ID/revision columns through
`campaign_message_template_ref`. Both absent means no template; incomplete pairs
fail instead of silently treating an orphan revision as absent. Valid references
retain the filed revision, never a latest-revision fallback. Campaign rendering
uses compiler-owned variable declarations rather than reading raw stored keys;
unrelated contact fields remain excluded. Service inputs use read-only `Mapping`
contracts, fixing the API schema-to-service variance mismatch without casts.

Executed **1,061 function/contract assertions**:

- Compare all four variable types and all six consumer kinds against the pinned
  `5ed452db` renderer, including repeated placeholders, HTML escaping, limits,
  nonfinite values, malformed schemas and missing/unknown variables.
- Check frozen variable maps, Pydantic JSON round trips, program/provenance
  refusals and draft/exact source disagreement.
- Run actual template services/repositories/models for create, edit, publish,
  preview and exact rendering with controlled DB responses. Exercise campaign
  rendering through the actual template service, including two scoped exact
  reads, unrelated contact fields, missing reference pairs and revoked renders.
- Confirm response projection and no service-owned commit. No live DB,
  provider call, worker or browser was exercised; no persisted test suite added.

Focused milestone review, in order:

1. DDD: template invariants remain in the template domain; campaign pair decoding
   remains campaign-owned and reuses the common exact reference.
2. Architecture: API and stored JSON remain boundary representations; neither
   sockets nor framework acquire module dependencies.
3. Data flow: valid output and failure classification match the prior renderer;
   restored internal values and incomplete campaign references now fail early.
4. Plan: implements the user's Pydantic preference and follows campaign rendering
   into templates. Other campaign config/outcome contracts remain open.
5. Maintainability/performance: no casts, suppression or new dependency; immutable
   variables remain readable through a typed mapping. Query counts are unchanged
   in the probes. Added validation is bounded by existing program limits; no
   live latency or throughput claim is made.

Expanded the local publication type gate to cover the template module; it passes.
Python lint passes. Full Pyrefly: **239 errors, three suppressions**, down from
244. An unrelated `pipelines/agents/config_deletion.py` diagnostic remains when
checking the entire agents pipeline directory; it is not hidden by this gate.
Campaign service's remaining nullable-delete diagnostic is still open.

### Campaign preparation summary contracts

2026-09-10: converted `CampaignPreparationIssue` and `CampaignPreparation` to
frozen, strict Pydantic values. Counts are nonnegative integers; booleans and
coerced strings are rejected. Nested issues are revalidated. Warning facts may
exceed the audience count because one contact can contribute several facts.

The existing preparation flow still validates every address and counts every
audience row, including rows without a resolved organization contact. An explicit
missing-ID guard precedes the optional contact lookup; it does not filter the
audience or turn preference/address warnings into blockers. Contact resolution
remains bulk, once per page, with organization authority passed explicitly.

Verification: **80 function-contract assertions passed**, including all issue
codes/levels, immutable and JSON-restored values, invalid counts, a 501-row
paginated audience, repeated/missing/unbound contacts, empty audience, and the
actual API response projection. Repository/contact reads were controlled; this
does not prove live campaign dispatch or database execution. No messages were
sent by the probe. Python lint and touched-file formatting pass; full Pyrefly
now reports **238 errors, three suppressions**. Campaign outcome tracking,
retry/config dictionaries and the other previously listed gaps remain open.

### Campaign outcome projection and remaining static diagnostics

2026-09-10: traced terminal telephony state through the durable consumer, exact
campaign attempt/revision lookups, retry selection, contact/campaign counters
and status aggregates. Converted `CampaignOutreachOutcome` to frozen, strict
Pydantic: normalized UUID-library identities, `CampaignChannel`, bounded opaque
channel outcome codes, optional tracking ID and finite nonnegative duration.
`connected` remains an intrinsic predicate. Channel-owned provider rejection
codes are not converted into campaign lifecycle states or a closed voice enum.

Added immutable `CampaignRetryPolicy` for runtime projection. Existing partial
policies keep zero/empty defaults and legacy `retry_on: null` becomes an empty
tuple. Strings/booleans are not coerced to counts. Relevant policy validation
happens before any outcome/counter mutation. Already-terminal contacts, replayed
attempts, connected outcomes and non-running campaigns retain their existing
branches; they do not begin evaluating an irrelevant retry policy. The durable
consumer translates malformed canonical outcome/policy values into a permanent
failure. No retry formula, connected-outcome classification or transaction owner
was changed.

Closed the remaining static campaign diagnostics along this flow:

- Aggregate repositories consume SQLAlchemy tuple results explicitly; the
  outcome projection narrows nullable reason values consistently with its SQL
  non-null predicate.
- Contact-selection input keeps its scalar-or-list wire contract but normalizes
  to an internally typed list before field validation. Its validation JSON schema
  is identical to the prior schema; no generated client change is needed.
- Campaign deletion checks and passes one resolved ORM row, preserving the
  missing-entity error category and draft/canceled eligibility, without a second
  nullable row lookup. This does not add a new concurrency/locking guarantee.

Verification: **827 assertions**: 763 outcome/policy checks (180 baseline
projection cases plus invalid boundaries and the actual durable-consumer path),
12 aggregate checks with real SQLAlchemy result objects, 34 scalar/list request
and input-schema checks, and 18 deletion guards. DB reads/writes were controlled
in these function probes; no live campaign was dispatched or deleted. An initial
probe fixture evaluated an invalid string count before reaching product code;
that fixture was corrected and the unchanged rejection assertions passed.

The complete campaign product and pipeline directories pass Pyrefly and are now
included in the local publication contract gate. Python lint and touched-file
format checks pass. Full Pyrefly reports **233 errors, three suppressions**, down
from 238 at the start of this slice. Documentation verification and whitespace
checks pass. Remaining semantic typing scope includes campaign API/ORM
retry, schedule and channel-config dictionaries; a green directory check does
not establish their conversion. Changed-build live QA remains open below.

### Campaign retry configuration: API to pinned execution

Completed the next vertical slice without changing DB columns or retry timing:

- API create/update and internal schemas accept `CampaignRetryPolicy`; services
  consume that value, repositories serialize its explicit JSONB keys, revision
  snapshots validate it, and attempt preparation validates the pinned definition.
- Create preserves omitted/null/empty channel policy. Explicit update `{}` clears
  retries; omitted update leaves it unchanged. Explicit update null is rejected
  before writes and is not advertised as valid in OpenAPI.
- Removed the unused dictionary policy catalog. Replaced unchecked runtime
  `model_copy(update=...)` with validated construction from pinned definition
  fields and current progress fields. A newer header cannot substitute its retry
  configuration for an existing attempt's revision.
- Regenerated console API types from a temporary running schema-only server.
  Campaign form builders now return the generated policy type. No UI layout,
  provider configuration, migration or operator data changed.

Verification: **241 API/service/repository/revision assertions** preserve prior
channel policies and JSON shape, plus **10 pinned-attempt assertions** cover
header/revision divergence and invalid pinned policy. Re-ran **763 outcome** and
**80 preparation** assertions. These use real product models/functions with
controlled DB dependencies, not live provider dispatch. Campaign directories
have zero Pyrefly errors; full-project baseline remains **233 errors, three
suppressions**. Console lint, TypeScript and production build pass; the build
still warns about large chunks.

Milestone review, in order: (1) policy remains campaign-owned, neutral call
reasons remain common contracts; (2) existing JSONB and revision architecture
remain unchanged; (3) create/update/snapshot/attempt/outcome paths are covered;
(4) this closes retry configuration, not schedule/channel dictionaries or the
broader platform backlog; (5) no cast, suppression, new dependency, extra DB
query or new retry authority was introduced. Changed-build product QA remains
required below; function probes do not replace it.

### Campaign reserved schedule contract

The next scheduling trace found no executable time-window consumer. Source
search plus `file_due_attempts`, attempt preparation and dispatch inspection show
that schedule config is stored/copied only; preparation already warns local-time
policy is not enforced. This slice therefore hardens the actual storage contract
and marks it inert, rather than introducing unrequested scheduling behavior.

- `CampaignScheduleConfig` replaces schedule dictionaries in API and internal
  schemas, service inputs and pinned attempt views. The three optional fields
  are strings; clock/timezone semantics remain uninterpreted in V1. Unknown keys
  and non-string field values now fail validation instead of entering JSONB.
- Create retains historical omitted/null/empty settings. Storage preserves
  partial keys and explicit field nulls. Update omission preserves data, `{}`
  clears it, and a null config is rejected before a non-null DB column write.
- The existing `experimental()` field metadata now lives in a neutral common
  utility used by voice and campaigns. API descriptions explicitly say schedule
  settings have no effect; existing voice metadata and limits are unchanged.
- Regenerated console API types; the form's return contract explicitly omits
  schedule settings because there is no schedule editor. The generated stricter
  update contract exposed the previous broad return annotation; no cast or
  invented default was added to bypass it.

Function verification: **132 assertions** across API/service/repository/revision
transforms and experimental metadata, **15 pinned-attempt assertions**, and
**241 retry-flow regression assertions**. DB dependencies are controlled; these
do not prove live campaign dispatch. An initial pinned fixture omitted required
retry data; correcting that fixture preserved the production validation guard.
Existing campaign and voice local type gates include the shared metadata module.
Schedule enforcement remains unimplemented by design; channel-config dictionaries
and the broader platform typing backlog remain open.

### Campaign channel config: binding through email dispatch

Closed the campaign configuration dictionary path with product-owned models:

- `CampaignChannelFields` couples the channel enum to a validated config in
  complete API/internal projections. Empty voice/widget settings and email's
  four known settings have separate frozen contracts; partial update input is
  checked against the resulting channel by the service/repository.
- Draft email config may omit required operational settings. Valid UUIDs and
  positive integer revisions are typed, unknown keys rejected. Incomplete drafts
  remain distinguishable from ready-to-dispatch campaigns.
- The service still resolves organization-owned email authority and overwrites
  caller-supplied revisions. JSONB stores primitive values only. Unrelated edits
  preserve existing pins; explicit clearing removes them. Exact attempt revision
  preparation validates its config before asking the provider pipeline for access.
- Email adapter consumes attributes rather than raw key lookups and `str(...)`
  coercion. Missing/null templates cannot become a literal `"None"` email body.
  Existing outbound ownership, idempotency and unknown-outcome handling remain.
- Generated console types now describe channel and config. Response config is
  required because the service always supplies it. Form builders use those types,
  refuse a missing channel without a cast, and never submit a provider revision.

Executed: **115 API/service/repository/revision/email-dispatch assertions**,
**11 pinned-attempt assertions**, **19 actual TypeScript form assertions**,
**241 retry-flow**, **10 pinned-retry**, and **132 schedule-flow** regressions.
DB/resolver/provider I/O are controlled; native product models and actual
transforms are used. A probe initially used nonexistent outbound state `FAILED`;
it was corrected to the source-defined `TERMINAL` before claiming dispatch proof.

Milestone review, sequentially:

1. DDD: channel settings remain campaign-owned; provider material/secrets remain
   in email configuration/pipeline ownership. No vendor SDK type moved outward.
2. Architecture fit: existing JSONB columns, resolver, revision authority and
   channel factory remain; no migration, queue or alternate binding registry.
3. Data flow: create → pin → JSONB → revision → exact attempt → email dispatch
   and the form/API projection are exercised. Malformed values fail before
   provider access; caller revisions cannot replace resolver authority.
4. Plan alignment: campaign retry/schedule/channel dictionaries are now typed;
   schedule enforcement is still intentionally absent. Contact variable payloads,
   dispatch-state contracts and broader platform diagnostics remain separate work.
5. Maintainability/performance: removed duplicate raw provider parsers, preserved
   existing query/transaction boundaries, no extra provider request or new runtime
   dependency. Config validation traverses a fixed small field set. No throughput
   claim is inferred from controlled-I/O probes.

Changed-build product QA and human review remain open; this milestone does not
establish live campaign delivery or full platform readiness.

### Campaign dispatch outcomes and replay policy

Reproduced a recovery defect in the actual worker branch with controlled I/O:
both an unknown receipt and a rejected receipt containing a tracking ID called
`_complete_dispatch`. The branch tested identity presence and ignored outcome.
This affects recovery-only execution of previously started effects; current
adapters declare replay safety, so the probe does not establish a live incident.

- `ChannelDispatchState` makes accepted/rejected/unknown explicit. The frozen
  result validates identity/error coherence; unknown/rejected can retain a
  tracking identity without being treated as accepted.
- All three adapters construct explicit states. Worker recovery completes only
  accepted results, rejects rejected results, and fences unknown/missing results.
  Normal dispatch validates checkpoint data instead of coercing dictionary values.
- `ChannelReplayPolicy` replaces the adapter flag. The start-effect boundary
  requires affirmative historical and current replay permission. Existing DB
  booleans remain translated at that boundary; no migration was introduced.
- An explicit private checkpoint model retains the existing v1 JSON fields and
  step name. New serialization remains readable by old workers; old valid
  checkpoints decode to current typed results. Malformed values fail validation
  and follow the existing replay-safe retry versus recover-only fencing rule.
- Removed six now-unnecessary protocol/factory type-ignore comments. Actual
  adapters satisfy the protocol under the scoped type check.

Verified **152 worker/checkpoint/effect-start assertions**, **45 voice/widget
outcome and replay assertions**, and **115 email/config flow regressions**.
These execute real models, adapters and worker branches with DB/provider I/O
controlled; no live call/email was sent and no worker crash was injected.

Milestone review: (1) result/replay vocabulary stays campaign-owned; (2) existing
outbound, DB and Absurd authorities remain; (3) adapter → saved step → worker
projection and recovered receipts are checked, including missing/invalid data;
(4) dispatch params, receipts, preparation tuples and projection dictionaries
remain further typing work; (5) no new query, dependency, retry engine or resource
lifetime was introduced. Current type/lint gates pass; full-project baseline
remains 233 errors with three suppressions. Changed-build QA remains required.

### Campaign worker input and internal control-flow contracts

Replaced the worker's ID tuple parser, preparation tuple, recovery dictionary
sentinel and untyped receipts with pipeline-owned Pydantic contracts and
`CampaignEffectAction`. The producer's ID-only payload, task name, idempotency
key, dispatch step name and receipt JSON fields are unchanged. UUID input accepts
UUIDs or valid strings, not arbitrary objects coerced through `str()`; invalid
input is rejected before product work and hides raw values in exception text.

`PreparedCampaignDispatch` preserves the validated adapter's identity and carries
detached campaign/contact values. Adapter and raw contact/message content are
excluded from snapshots and repr. The adapter remains a behavioral protocol,
runtime-checkable for model admission and statically checked for signatures; it
was not replaced by a data model. Worker helpers now return typed receipts and
declare their transaction session dependency. Only the public worker boundary
serializes receipts. The existing receipt ambiguity Boolean is compatibility
data, not a new runtime decision flag.

Verified **99 producer/input/receipt/preflight assertions**, **152 dispatch and
recovery regressions**, and **12 pinned-config/prepared-context assertions**.
These use actual worker/producer functions and real models with controlled DB
and provider I/O. They verify terminal preflight does not dispatch, invalid IDs
do not enter execution, ID-only spawn compatibility, binding-pending propagation,
all durable receipt states, snapshot exclusions and pinned provider authority.
No live delivery, worker crash or DB concurrency is claimed. Campaign type gates
and Ruff pass; full-project baseline remains **233 errors (3 suppressed)**.

Remaining campaign typing includes contact variable payloads, projection values
and failure vocabulary; shared durable infrastructure and broader provider flows
remain part of the platform goal. No migration or operator data changed.

### Campaign contact variables across upload, storage and rendering

`CampaignVariables` is a validated custom-key JSON object, not an invented fixed
schema. Contact upload and readback models, internal contact schemas and the ORM
field no longer use `Any` for variable values. Validation rejects non-string
keys, non-finite numbers and Python-only objects, including nested values, while
preserving all valid JSON types. Independent copies prevent caller mutation from
changing an already-parsed payload. Repository validation also catches mutation
after model construction before INSERT; service batch revalidation runs before
contact resolution. JSONB storage and schema history are unchanged.

Simple email rendering accepts a read-only JSON mapping and preserves the
existing missing-placeholder and text-conversion behavior. Published template
rendering remains governed by its pinned declaration, not a new variable policy.
The console upload type now derives from `ContactUploadRow` in generated OpenAPI,
including the address parser, instead of duplicating an unconstrained record.

Verified **108 API/service/INSERT/readback/render assertions**, including nested
JSON, copied payloads, independent empty defaults, invalid values and post-parse
mutation, upload deduplication and count updates. DB operations were controlled;
this is not live campaign sending or product acceptance. The actual console
address parser passes **19 assertions**; **115 email/config** and **152 dispatch**
regression assertions also pass. OpenAPI was regenerated from a temporary
current-code loopback server with lifespan disabled, then TypeScript, lint and
Vite build passed (existing large-chunk warning remains). Campaign typing, Ruff
and documentation verification pass. The temporary server was stopped; operator
data/config and deployed services were untouched. Broader failure/outcome
vocabulary and platform typing remain open.

### Sandbox config, verification and acquisition typing

The current diagnostic cluster was traced from provider config resolution through
verification manifests and session acquisition. Immutable dataclasses carried
`Mapping[str, object]` settings, forcing runtime casts for every numeric limit.
Fresh and restored acquisition used correlated `if checkpoint is None` branches,
which left adapter/config/policy initialization unproven to the checker.

- Replaced config/resolved-authority and verification data contracts with frozen
  Pydantic models. Provider values are enums; verification's network/workspace
  vocabulary is module-owned. Additional metadata is validated JSON, not an
  unchecked private-field override. No secret is included in config snapshots.
- `SandboxExecutionSettings` applies the existing policy validator and exposes
  typed fields. Both verification and live execution use its manifest conversion;
  no caller can override ceilings or network policy. All stored settings and
  verification metadata keys remain compatible. No migration was introduced.
- The provider constructor is `from_config`, avoiding a collision with Pydantic's
  existing `validate` method. Service writes explicitly serialize settings;
  invalid resolved metadata still maps to `NotConfiguredError`.
- Acquisition now has exhaustive fresh-versus-checkpoint branches. Current grant
  checks, checkpoint identity/policy comparison, quota checking, reservation commit
  and failure cleanup remain in their existing ownership/transaction boundaries.
- Added a local pre-commit/pre-push gate for sandbox config and pipelines. Docker
  SDK result typing remains outside that passing scope and is still unfinished.

Verified **98 config/service/verification assertions** and **151 config plus
acquisition assertions** (the latter intentionally includes shared config cases).
The actual acquisition function covers direct/agent creation, reuse, restore,
missing/mismatched grants, altered policy, digest failure, create/restore/activation
failures and staged-file replacement refusal. Provider creation is checked after
reservation commit; verification probes occur outside DB scopes and CAS the read
revision. Tests use real models with controlled DB/Docker I/O, not live containers,
real concurrent locks or abrupt process cancellation. These are function proofs,
not full sandbox product QA.

Sandbox config/pipeline typing passes; full-project diagnostics are now **200
errors (3 suppressed)**, down from 233. Remaining sandbox diagnostics are Docker
SDK values and three system-tool context signatures. Workspace checkpoint payloads,
vendor request/response typing and broader platform semantic typing remain open.

### Docker sandbox SDK boundary typing

Followed config → session → Docker exec/file/verification data flow against the
locked and installed Docker SDK 7.2.0. SDK collection methods expose broad
inferred return unions; the adapter previously trusted generic model/dictionary
values as containers, images, exec IDs and execution status.

- Native Docker clients/resources remain inside `sockets/sandbox/vendors/`.
  Explicit resource narrowing replaces generic model assumptions; detached
  creation must return a container, image resolution must return one image.
- Added frozen vendor-local response projections in `docker_contracts.py` for
  exec creation/inspection, host isolation, container state and server version.
  Consumed fields are strict, additional vendor fields are tolerated. Invalid
  evidence is refused without publishing raw response contents.
- Parsed binary output frames before buffering. SDK streams are closed on
  normal and exceptional consumer exits. File-write/restore channels now have
  explicit lifetime ownership; previously they were opened without a close path.
- Sandbox tool context signatures now explicitly permit their existing `None`
  default. Public generated tool schemas still omit injected `ctx`; direct calls
  still refuse execution outside the durable AgentRun path.
- Expanded the local sandbox pre-commit/pre-push gate to cover sockets and the
  three system-tool entrypoints as well as config/session pipelines.

Verification: **92 adapter contract assertions**, **14 lifecycle assertions**,
plus the previous **98 config** and **151 config/acquisition** probes rerun.
Native SDK resources/streams and real Unix socket pairs exercise frame parsing,
stdin half-close, write/restore channel cleanup, command timeout/cancellation,
and cancellation during container creation. Docker HTTP I/O is controlled;
these are not live container, daemon-isolation, DB-concurrency or process-crash
proofs. Fixture failures (class-spec mocks missing instance `api`, a manifest
below the existing minimum disk limit) were corrected in temporary probes, not
by weakening runtime contracts.

Sandbox scoped typing and Ruff pass. Full-project diagnostics are **184 errors
(3 suppressed)**, down from 200. Checkpoint/workspace payload semantics and
remaining platform/vendor typing still need work. No dependencies, migrations,
operator data or deployed services were changed. Changed-build browser/provider
QA remains open below.

### Widget invitation persistence and authority typing

Traced issuance → locked exchange → contact session/conversation creation →
same-request replay → authenticated session authority → primary Agent authority.
The reported errors came from unannotated SQLAlchemy columns and nullable Agent
references carried through a filtered list; they did not establish a live auth
bypass. Required identity/revision fields are now checked data contracts rather
than immutable containers holding unchecked values.

- `AuthSessionModel`, `WidgetInvitationModel` and `ApiKeyModel` now use
  `Mapped`/`mapped_column` with the existing column types, nullability and
  constraints. Compiled PostgreSQL table/index DDL matches the pre-change
  baseline exactly. No migration or operator DB write was needed.
- `WidgetSessionAuthority` and `WidgetConversationAuthority` are strict frozen
  Pydantic values with positive pinned revisions. Conversation ownership is
  checked first; eligible primary participants are converted into authorities
  while their required references are narrowed. Zero/multiple authorities still
  produce the existing not-found outcome.
- Issued/exchanged pipeline results are frozen Pydantic values. Issued ORM row
  identity is preserved, but the row, bearer URL and session token are excluded
  from incidental dumps/repr. Explicit public response projection retains the
  existing token/URL response contract. `_load_existing_exchange` receives a
  typed `AsyncSession`.
- A local pre-commit/pre-push gate covers these persistence, service, pipeline
  and invitation route/schema files. Other auth flows remain outside this passing
  gate until their typing work is complete.

Verification: **95 authority/service/pipeline assertions** and **11 route
projection assertions** using real ORM/schema/result types and controlled
transaction/cross-module I/O. Cases include expiry ceilings, token hashing,
`FOR UPDATE`/tenant query predicates, consumption fields, same-request replay,
different-request refusal, expired/deleted/wrong-org sessions, filtered/ambiguous
primary Agents and secret-safe snapshots. The actual public route functions
retain explicit response fields and the unavailable-invitation 404. No live DB
row-lock race, HTTP transport, browser bootstrap or provider call is claimed.

Scoped typing, Ruff and documentation checks pass. Full-project diagnostics are
**171 errors (3 suppressed)**, down from 184. Next auth data flows: member
registration/projection, password-reset nullable persistence and session-initiation
response/contracts. Changed-build widget/admin QA remains open below.

### Member registration, reset and signed-action contracts

Followed public registration → auth controller/service → organization/member
creation, then reset-token decoding → member persistence and member-token
resolution. The previous registration DTOs were structurally similar but not
the same contract; a registration request was also passed where member creation
required its newly created organization identity. The reset path read the same
member twice and dereferenced a missing second ORM row. A controlled reproduction
confirmed `AttributeError` rather than the intended invalid-reset outcome.

- `RegistrationRequestSchema` now owns route/controller/service input. Removed
  the unused duplicate `MemberRegisterSchema`. Password hashing happens once in
  the auth service, without mutating API input; persistence receives an explicit
  `MemberCreateSchema` with organization, email and hash.
- Member schemas use the existing required-organization base. Password nullability
  matches the DB; password verification explicitly refuses a missing hash.
  Public member projection still omits passwords. Principal and resolved member
  values no longer overwrite the same differently typed controller variable.
- Reset performs one guarded ORM lookup and saves that row. Absence raises the
  already handled `MemberNotFound`. No token policy, signing key, password hash
  algorithm or DB schema was changed.
- Session initiation now declares its required-data envelope directly instead
  of overriding a mutable optional generic field. Its complete generated JSON
  schema matches the previous public shape, including required data.
- Invite/reset decoders return frozen typed claims with enum-owned purpose,
  UUID identity, email and aware expiry. Exact legacy issuer payloads still
  decode. Correctly signed payloads missing claims or carrying invalid IDs were
  reproduced as previously accepted; they now take the existing `JWTError` path.
- Installed PyJWT 2.13.0 raises `TypeError` for `exp: null`; this was reproduced
  in the malformed-token matrix and normalized narrowly at decoding. Member
  token handling uses the same protection, outside the member lookup, so a
  repository `TypeError` is not disguised as an invalid token.

Verification: **32 member/auth assertions**, **56 action-token assertions** and
**14 member-token authority assertions**. These use actual claim models, signed
JWTs and the configured password library; DB I/O is controlled. Cases include
one hash without input mutation, duplicate refusal, public projection, null-hash
login refusal, missing reset rows, malformed/expired/wrong-purpose/wrong-signature
tokens and exact existing token-wire compatibility. Passlib 1.7.4 emitted its
existing bcrypt 4.3.0 version-reporting warning; actual hash/match/mismatch checks
passed. No dependency upgrade or warning suppression was introduced.

The local auth gate now checks both full auth/members modules plus widget
invitation/authority pipelines. Scoped types and Ruff pass; full-project count
is **163 errors (3 suppressed)**, down from 171. Passing auth diagnostics does
not establish live login, concurrent-reset, browser or provider QA.

### Contact resolution and widget session results

Converted `ContactIdentity`, `ContactResolution` and `AuthSessionInitiation`
from dataclasses to frozen, strict Pydantic values. Existing optional outcomes
remain valid: no match has no contact; a new contact has no matched identifier.
The `created` predicate still means this call created a contact, not a lifecycle
mode. Normalization, identifier priority, ambiguity warnings, the deletion fence
and savepoint-based concurrent insert recovery remain service-owned.

External identifiers, email, phone, contact details and session tokens are
excluded from their containing internal model snapshots/representations. Typed
nested model instances retain identity. Public session output still explicitly
includes its token and safe warning codes; no public schema or DB change.

Verification: **60 focused assertions** exercised actual resolution, create/retry,
session service and controller functions with controlled DB I/O. They cover
priority and conflicts, normalization, no merging, unresolved insert failures,
deletion/invalid-identity refusals, session owner fields, safe snapshots and public
token projection. No live concurrency or browser coverage is claimed. The
expanded local auth/contact/widget gate and Ruff pass. Full-project count remains
**163 errors (3 suppressed)**; this slice removes unchecked runtime contracts.

### Conversation aggregate read contracts

Replaced repository-to-service dictionaries with explicit Pydantic
`ConversationAggregateRows` and `AggregateParticipant` working values. They are
deliberately mutable during batch assembly, validate assignments, preserve ORM
identity and exclude attached rows/content from incidental snapshots. No public
response fields, DB schema or tenant predicates changed. The organization lookup
now declares its actual non-null return-or-`ConversationNotFound` contract.

The existing ranked message query now selects an ORM alias of its subquery
instead of passing raw SQL rows to consumers. This follows the
[SQLAlchemy 2.0 entity-from-subquery contract](https://docs.sqlalchemy.org/en/20/orm/queryguide/select.html#selecting-entities-from-subqueries),
checked against installed SQLAlchemy **2.0.45**. The same per-conversation window,
timestamp/ID tie break, filters and bounds remain in SQL. Sender lookup uses a
single validated participant map rather than scanning participants per message.

Verification: **547 assertions** compare the previous and changed service outputs
across **48** combinations of body/participant inclusion, kind filters, limits
and offsets. Actual SQLAlchemy queries execute against disposable in-memory
SQLite tables mirroring relevant columns, with JSONB represented as SQLite JSON;
this is **not** PostgreSQL schema/migration or production QA. Both implementations
produce identical public output, exclude another org's conversation and deleted
messages, preserve counts/order and use at most six batch queries. Projection
adds no lazy SQL. PostgreSQL compilation separately confirms window/bound syntax.

The probe caught a first-pass regression: Text-backed participant kinds return
strings even though the ORM annotation says enum. Direct assignment bypassed
Pydantic validation and emitted serializer warnings. Sender labels now come from
validated participant summaries; the full matrix passes with Pydantic warnings
treated as errors. A probe fixture also used the wrong Agent status value;
it was corrected to the source-defined `AgentStatus.ACTIVE`, not a DB change.

The dedicated aggregate type gate and Ruff pass. Full-project diagnostics are
**156 errors (3 suppressed)**, down from 163. Changed-build browser and live
PostgreSQL/provider acceptance remain open. Next read-path slice: operator list
result/predicate contracts and remaining conversation schema typing.

### Conversation list and history projection contracts

Converted the operator `ConversationListResult` to a frozen Pydantic result with
a nonnegative count; incidental snapshots omit conversation data. Predicate
output is a read-only `Sequence[ColumnElement[bool]]` and sorting returns a typed
SQL column expression. Using `Sequence` also avoids the class's `list` method
shadowing the builtin in annotations. No query, sorting or pagination behavior
changed. `ConversationBase` now uses the existing required-organization base;
complete JSON schemas for it, `ConversationInDb` and `ConversationApiResponseSchema`
are byte-equivalent to their pre-change definitions.

The context enrichment helper no longer bypasses validation with
`MessageInDb.model_construct`. Widget-response projection builds a validated copy,
including enum content kind and typed metadata. Removed the unreachable
string-content branch: canonical `UserMessageContent` normalizes strings to
content blocks. Ordinary text/image messages still take the existing unchanged
path. Corrected the helper docstring's unsupported timestamp claim; this does
not add a timestamp feature or change enrichment policy.

Verification: **2,422 list assertions** execute old/new query functions against
disposable SQLite mirror tables across **480** filter/sort/pagination combinations.
Public item output and totals match, each list call makes two queries, search
wildcards stay literal, duplicate Agent participants do not duplicate rows, and
the direct private route rejects another org before DB access. This is not live
PostgreSQL, HTTP-authentication or browser coverage.

**181 enrichment assertions** cover context flags, no-op paths, non-mutating
copies, typed metadata/identity preservation, `get_messages()` and downstream
`run_message_from_indb()`. No vendor is called. The expanded local conversation
type gate covers aggregate/list/context contracts. Full-project diagnostics are
**153 errors (3 suppressed)**, down from 156; full-platform work and changed-build
acceptance remain open.

### Conversation-start authority contracts

Typed the contact resolver result and conversation-start pipeline return. The
domain service now narrows the required Agent ID explicitly before swarm lookup
and constructs `ConversationCreate` directly instead of building an unchecked
keyword dictionary. Canonical widget ingress validates its modified request
instead of using an unchecked `model_copy(update=...)`. Channel, context
sanitization, participant roles and exact revision binding remain unchanged.

The optional WebSocket diagnostic exposed a real ordering defect: a context
without `ws` completed its mocked conversation creation and session fact, then
returned 500 on `ctx.ws.agent_id`. Reproduced with one transaction, one start and
one fact. The handler now requires and retains WebSocket state before DB work;
the same input returns 404 with zero transactions, starts or facts. The successful
path still updates the selected Agent only after the transaction succeeds.

Verification: **151 assertions** use actual request, session, executable-Agent
and swarm models through widget controller, resolver pipeline and domain service;
DB writes/resolver I/O are controlled. Cases include inbound/outbound starts,
context sanitization, exact swarm/Agent refs, revision/org mismatches, missing
runtime state, bounded sessions, wrong contact and invalid widget direction.
No live DB commit, WebSocket connection or vendor call is claimed.

The expanded conversation gate and Ruff pass. Full-project diagnostics are
**151 errors (3 suppressed)**, down from 153. Remaining conversation diagnostics
are prompt composition and message-update row counts; broader transport contracts
and changed-build acceptance remain open.

### Prompt utility and message-result contracts

The structured prompt utility now names render/context modes with enums and
shares an explicit content type. Rendering accepts a read-only nested sequence,
so recursive traversal retains its actual types without widening mutable lists.
JSON input is validated into sections before merging by title. Section titles
are derived after kind validation without modifying the caller's dictionary.

Two local defects were reproduced: a string kind with an omitted title raised
`AttributeError`, and appending to a string context split the previous text into
individual characters. Both are corrected. Valid section rendering and the
utility's conversational prompt output retain baseline parity. Malformed imports
are now rejected before any section is replaced. This utility has no callers
outside its own module in the current checkout; these fixes are not evidence
of a changed live-agent prompt pipeline.

Message persistence now narrows the SQLAlchemy DML result to `CursorResult`
before reading its row count. The update SQL, filters, transaction owner and
repeat-update semantics are unchanged. An unexpected non-cursor result is an
internal contract failure rather than a fabricated zero-row success. The two
message/run authority values are frozen, strict Pydantic models; typed tuple
results feed their UUID fields. Existing no-owner refusals remain intact, and
background run output can still have no user session.

Executed function checks:

- **1,485 prompt assertions**: heading modes, nested descriptions/context/examples,
  baseline rendering/payload parity, JSON round trips, enum values, append and
  replace behavior, omitted titles, invalid input, input preservation and atomic
  invalid-import refusal.
- **571 message-result assertions**: actual SQLAlchemy ORM statements and cursor
  results against disposable in-memory SQLite table mirrors. Checks cover all
  request statuses, counts, repeat updates, deleted rows, different requests and
  conversations, authority lookups, missing/deleted/inactive owner cases, null
  run sessions and Pydantic validation. PostgreSQL compilation preserves the
  same update statement; PostgreSQL execution/constraints were not tested here.
  The async DB seam delegates to a real synchronous SQLAlchemy session; it is
  not an async-driver or concurrency proof. An initially omitted `updated_at`
  column in the disposable fixture was corrected; no product schema changed.

The expanded conversation type gate and Ruff pass. Full-project diagnostics are
**148 errors (3 suppressed)**, down from 151. No operator data, provider config,
migration or running service changed. Live widget/admin acceptance remains open.

### WebSocket ingress and delivery contracts

Decoded text now passes the existing activity/rate-limit check before validation
into `WsRequestEvent`. The dispatcher accepts that model, not a raw dictionary;
binary frames construct the same envelope while preserving the original bytes.
Invalid JSON remains a safe 400 response; invalid event/model input now produces
a safe 400 instead of a generic 500 or a silent falsey-input skip. Private event
dispatch still requires the authenticated contact, not IDs supplied in a frame.
The separate binary path retains its existing text-rate-limit exemption.

The route now supplies its actual WebSocket as an `HTTPConnection` for existing
client-info extraction. Installed FastAPI dependency resolution injects HTTP
`Request` only for HTTP requests, so the former optional route parameter was
always absent on WebSockets. No new authentication source was added; connection
headers remain descriptive metadata, never organization/contact authority.

Pubsub ingress validates a frozen `ContactDelivery` with UUID owners, an event
enum and JSON payload. Required conversation authority stays mandatory; malformed
messages are rejected without killing the listener. Both encoded bytes and
decoded JSON strings are accepted. The producer's wire dictionary remains
unchanged, and the real publisher serializer is covered by the probe. This does
not finish the remaining per-event body or vendor media-frame contracts.

`send_response()` previously cleaned up after `WebSocketDisconnect` or
`RuntimeError` but returned `None`. Reproduced both cases with one cleanup call.
Both now return `False`; success, socket-identity fencing and cancellation
propagation are unchanged. Misleading priority/metrics documentation was removed.

Executed verification:

- **530 manager assertions** cover every event kind, validation/rate ordering,
  payload preservation, missing conversation authority, malformed pubsub input,
  listener continuation, producer serialization, contact/org routing, browser
  versus conversation-bound telephony delivery, media frame formats, failed
  sends, socket replacement fences and cancellation. Redis and network sends are
  controlled; this is not live Redis/provider or concurrency QA.
- **46 ASGI route assertions** exercise the actual FastAPI route, controller,
  event dispatcher, ping handler and WebSocket frame transport with TestClient.
  They cover initialization, client metadata, malformed frames, safe errors,
  correlation IDs, authoritative org/session output, binary dispatch, explicit
  session end and cross-org refusal. Auth/session persistence, audio handling
  and close effects are controlled; no real provider or DB is touched.
- The first route probe incorrectly expected snake-case envelope keys. The
  public schema's actual aliases are `organizationId`, `sessionId` and
  `requestId`; the probe was corrected, not the API. The installed TestClient
  emits an httpx deprecation warning; no dependency change was made.

The new local WebSocket type gate passes. Full-project diagnostics are
**144 errors (3 suppressed)**, down from 148. Updated-build deployment and real
widget/admin/provider acceptance remain open. No operator data or running
service changed.

### User-session lifecycle and list contracts

`UserSessionStartResult` is now a frozen Pydantic value with one
`UserSessionStartOutcome`, replacing the mutually exclusive stored boolean pair.
Read-only `created` and `reconnected` properties preserve the widget's existing
response contract. The attached ORM row retains identity and remains mutable
inside its owning transaction; snapshots/repr exclude it. Both constructors now
use explicit outcome values and keyword arguments. No lifecycle policy changed.

`UserSessionListQuery` is a frozen, strict model with domain enum options and
typed tuples. It excludes private search text from snapshots without changing
the executed search. List predicates return a read-only sequence of SQL boolean
expressions instead of the method-shadowed bare `list` annotation. Aggregate
projections unpack typed result tuples; their SQL and query counts are unchanged.
The count helper accepts the common mapped base and a SQL boolean predicate.
`touch()` requires a DML cursor before interpreting its affected-row count.

Verification: **848 function assertions** execute lifecycle methods and actual
SQLAlchemy queries against disposable in-memory SQLite table mirrors. They cover
create/reconnect/terminal refusal, immutable outcomes, live row identity, snapshot
exclusion, stale connection fences, owner/contact/channel matching, activity
updates, first/repeated/restored conversation links, link authority, list/filter/
sort/page parity, detail counts and timeline projection. The 176 list combinations
compare old and new output and assert two queries per list call. Detail remains
two queries; foreign/deleted detail refusal stops after ownership lookup.
PostgreSQL compilation retains row locking and the named conflict target.

The first mirror lacked `deleted = false`; it was corrected after the unchanged
baseline refused its newly inserted row. The baseline sort probe also needed
its original enum class for identity comparisons. Neither issue required a
product-code fix. SQLAlchemy's actual `ScalarSelect` export path was checked by
the installed checker. No PostgreSQL constraints, concurrent locks, event-outbox
persistence or external providers were exercised by these function probes.

The existing **46-assertion ASGI widget-route probe** passes with the new outcome
model and unchanged response booleans. A new local hook covers the session module
and WebSocket/telephony consumers. Full-project diagnostics are **142 errors
(3 suppressed)**, down from 144. Operator data and deployed services are unchanged;
changed-build browser/vendor acceptance remains open.

### Tool definition API and persistence contracts

Tool create, update and response contracts now share metadata fields without
overriding native `PlatformTool` fields with incompatible API types. Explicit
API-to-domain conversion preserves route-owned organization identity, omitted
patch fields and JSON Schema keywords. Camel-case request validation no longer
rewrites the caller's input dictionary. Required fields, aliases and public
schema definitions remain equivalent; required-field ordering is immaterial.

Two defects were reproduced before repair:

- Creating a registered local tool failed because the system registry's
  missing-tool lookup raises; the API used it as a membership predicate. The
  registry now exposes membership separately, and the local-tool policy returns
  a validated `PlatformTool`. Unknown names and system-tool names remain refused.
- Create/update serialization used Python field names for nested input schemas.
  Loading dropped `$defs`, `oneOf` and `additionalProperties`. Writes now use
  canonical JSON Schema aliases. Read compatibility accepts old Python-keyed
  input schemas without DB rewriting; it cannot recover fields already discarded
  from persisted data. The canonical input model also honors explicit Python
  keyword construction, rather than silently ignoring those arguments.

Verification: **422 function assertions** cover registration/refusal, code-owned
schema replacement, route organization authority, controller translation, null/
empty/omitted patch semantics, 24 schema/casing combinations, input preservation,
actual ORM construction, JSON-column serialization, service revision increments,
old-row read compatibility, public responses and Anthropic tool projection.
Persistence save/flush and transaction seams are controlled: this is not a live
DB commit, vendor call, widget test or approval-lifecycle proof. The initial
probe referenced a nonexistent adapter class; inspection corrected it to the
actual `AnthropicAdapter`. Product code was not changed for that fixture error.

The dynamic Pydantic field-definition dictionary is explicitly SDK-owned `Any`:
values contain runtime annotations and defaults, validated by `create_model`.
It is not a platform payload escape or a reason to broaden tool data contracts.
The local hook covers definitions, persistence, controllers and Agent response
consumers. Full-project Pyrefly reports **134 errors (3 suppressed)**, down from
142. Broader system-tool executor typing remains pending. No migration,
operator data change, deployment or provider configuration change was performed.

### Scheduled-tool context and action registration contracts

`ActionContext` and `ActionSpec` are frozen, strict Pydantic values. The handler
reference retains identity but is excluded from dumps, repr and JSON Schema.
`AgentSchedulingAccess` replaces the registry's access-policy boolean; both
current registrations explicitly retain their prior access. Action names and
context keys remain extensible registry contracts, not a cross-domain enum.
Conversation action/key constants are owned by the conversation module.

Schedule tools consume an `AgentScheduleContext` behavioral protocol rather than
pretending every caller is a `ConversationContext`. The protocol exposes only
the agent authority needed by listing/cancellation. Real conversation identity
requires a validated conversation context; missing optional action metadata is
refused before dereference or persistence. The reserved `list` command remains
separate from executable action names.

Reproduced defects and fixes:

- Non-conversation `AgentExecutionContext.conversation.id` was filed as a real
  conversation ID by `schedule_create`. The tool now refuses that re-engagement
  before calling the schedule service. It does not consult a model-supplied ID.
- The reminder tool dereferenced a missing primary contact before its missing-
  context guard, producing `AttributeError` and the generic retry response. The
  guard now checks the real conversation, agent and contact first. Its existing
  missing-context response is reachable, with no schedule write.
- UTC conversion's optional format annotation now permits its actual `None`
  default. Registered input validation consequently accepts explicit null; all
  existing non-null conversion behavior remains unchanged.

Executed **196 function assertions**: frozen model validation, handler identity/
snapshot exclusion, action registration/access, controlled dispatch, 16 valid
schedule input combinations with baseline output/registration parity, real
recurrence/service validation, route-independent org/agent/revision ownership,
spoofed IDs, unavailable contexts, malformed dates/rules, reminder semantics,
registered-tool dispatch, disabled policy, list/cancel behavior in both context
types, and UTC conversion. The schedule adapter and list/cancel I/O are controlled;
no operator DB, provider, delayed live execution or browser was exercised.

The current due worker creates scheduled AgentRuns; it does not call `dispatch`
from the older action-handler registry. The registry-dispatch probe is only a
function proof, not evidence of delivered reminders. Full scheduled-agent
delivery, remaining action payload/result contracts and changed-build QA remain
open. No schedule, migration, provider config or running service was changed.
The new local scheduling hook passes; full-project diagnostics are **126 errors
(3 suppressed)**, down from 134.

### Provider references and call-owned erasure contracts

The next deletion-flow slice removes ambiguous class-union inference from
provider reference queries. All 16 existing embedding queries constructed before
the change; this was not evidence of nonexistent runtime columns. Explicit
model/column pairs preserve lookup order, early return, organization scope and
soft-deletion predicates. `MemoryChangeModel` retains its actual distinct ORM
base rather than being forced into a different inheritance hierarchy.

Call erasure now shares a typed candidate-child predicate: organization AND
(call ID OR a present conversation ID). A null conversation never selects other
null-conversation rows. Candidate selection does not establish exclusive
ownership: the existing call/session/recording graph guard remains authoritative
before DB erasure. Detached work/recording receipts are frozen Pydantic models;
campaign count projection consumes SQLAlchemy's typed tuple result interface.
No deletion policy, transaction lifetime, migration or public API changed.

Executed **319 function assertions**: old/new PostgreSQL query compilation and
query-order parity; real EXISTS/predicate execution against an in-memory SQLite
column mirror; all 16 embedding references, three agent-bound capabilities,
cross-org and deleted-reference refusal, null scopes, exclusive ownership and
session-token checks, immutable receipt round-trips, service refusal without
reference authority, and campaign count projection. Loader probes verify
storage-locator resolution occurs after the read transaction closes.

These are contract proofs with controlled service/transaction/storage ports,
not live PostgreSQL locking, concurrent deletion, worker recovery or provider
object-deletion proofs. No operator DB row or storage object was deleted.
Changed-build browser QA remains open below. The local deletion-contract type
hook, Python lint, documentation validator and diff whitespace checks pass.
Full-project Pyrefly reports **117 errors (3 suppressed)**, down from 126.

### SOR transport failure and terminal-task recovery contracts

The recovery trace follows periodic `nudge_sor_work` through engine inspection,
the locked product receipt, source failure projection and DAG advancement.
Baseline execution passed 496 assertions: the reported possibly-uninitialized
error variable was a narrowing diagnostic, not a reproduced runtime exception.
The cancellation branch already exited before failure projection.

Recovery now uses detached Pydantic candidate identities, named mutable counters,
an explicit terminal engine-value enum and a frozen failure object. The failure
object carries `SorRecoveryPolicy`, replacing positional permanence/reauth
booleans. Existing product-state and task-binding race guards remain unchanged;
public scheduler counters retain their existing dictionary shape. Adapter error
codes remain strings at the existing `SorAdapterUnavailableError` boundary;
typing that boundary and the broader sync attempt/page/receipt payloads remains
open, not hidden by this slice.

Confirmed adjacent defect: shared SOR HTTP guards still constructed
`SorVendorOperationError` with string codes after its constructor became
enum-only. Invalid query input raised `TypeError`, then sync classified it as
`SYNC_PROVIDER_FAILED` / `RETRY`. Seven missing enum members and all 15 affected
constructor sites now preserve the intended terminal error. No path, origin,
credential, redirect, permission or request-shape policy changed.

Verification: **496 recovery assertions** pass before/after with actual ORM and
`SorBoundWorkService` code, controlled DB/engine ports. **1,191 failure assertions**
cover every vendor error/recovery combination, HTTP guard branches, valid
cross-origin binary redirect credential stripping, and actual sync failure
handling through work-state mutation and post-transaction projection. Probe
fixtures were corrected for the existing same-origin double-slash path behavior
and the required sync-run kind; product code was not changed to fit them. Six
additional assertions validate detached candidates from actual SQLAlchemy Row
objects, immutable values and JSON round-trips with present/null task IDs.

These checks do not establish live PostgreSQL lock/race behavior, worker-crash
recovery, vendor connectivity or changed-build browser behavior. The focused
runtime type check and Python lint pass. Full-project diagnostics are **100
errors (3 suppressed)**, down from 117. No operator DB or vendor was mutated.

### SOR manifest, registry and vendor identifier boundaries

All 11 executable vendor registrations now explicitly project enum-keyed
tool/stream maps into the shared manifest's string-keyed contract. Vendor-local
maps retain their owning enums; shared consumers still accept code-owned
identifiers without importing every vendor enum. This resolves mapping-key
variance without casts, `Any`, a catch-all enum or a parallel registry.

`SorVendorStreamSpec`, `SorAdapterCapabilityManifest`, `SorVendorRegistration`
and the private factory registration are frozen Pydantic contracts. Manifest
scope/result/tool maps are copied and frozen, including omitted empty maps.
Relationship-target serialization retains its existing `by_role` shape while
making manifest JSON snapshots serializable. The factory stays callable and
identity-preserved, excluded from JSON, schema and representation.

Executed **1,974 function assertions** across the full executable catalog:
manifest and registration JSON round-trips; nested immutability and source-map
alias isolation; unavailable vendor and invalid declaration refusals; every
single/pair/all-stream OAuth scope selection for both source access modes;
all writable tools' scope and result-stream mapping checks; org/source/mapping
identity passed to controlled repositories; and factory snapshot exclusion.
The canonical public catalog JSON is identical to a baseline using the prior
dataclass definitions. Raw JSON hashing initially differed due to unordered map
iteration across processes, not a semantic catalog change.

Focused registry/catalog type checks and Python lint pass. Full-project Pyrefly
reports **79 errors (3 suppressed)**, down from 100. The hook covers registry and
catalog projection files, not a claim that all vendor files are type-clean.
This work does not prove live authorization, agent tool dispatch against a
vendor, or deployed browser behavior. No credentials, data or services changed.

Remaining in this flow: vendor dispatch must narrow shared identifiers back to
the owning enum; remaining discovery/request/response payload contracts and
shared dataclasses need conversion. Existing manifest capability booleans and
their public projections need the planned explicit-policy enum treatment; they
were not silently redefined in this compatibility-preserving slice.

### HubSpot discovery, synchronization and mutation identifier boundaries

HubSpot now narrows shared stream strings to its `HubSpotStream` enum after
checking source selection. Discovery, page/refetch requests, mapped properties,
association pagination and record projection carry that enum internally. Command
dispatch similarly validates `CrmToolName` before selecting one of the seven
existing executable mutations. Unsupported or unselected identifiers retain the
same terminal refusal before HTTP I/O. Dynamic custom property names remain
mapping-owned strings rather than an invented static vocabulary.

Webhook deduplication now uses a frozen vendor-owned Pydantic hint with a required
timestamp and stream enum. Only the completed deduplicated batch is translated
to the shared signal, whose timestamp is optional for other vendors. Latest-event
selection, first-seen ordering and equal-timestamp behavior are unchanged; no
timestamp fallback or type suppression was added. Pagination retains its explicit
optional initial cursor through subsequent batches.

Executed **176 function assertions** through the actual adapter, HTTP request
model, property selection, association pagination and mutation response/error
handling, with the final transport substituted. Four streams and all seven
mutations are covered. The 161 pre-existing-path assertions passed before and
after the edit with identical canonical request/result snapshots; 15 additional
assertions cover enum identity, strict/frozen Pydantic hints, JSON round-trips and
generic object-type webhook translation. Checks include invalid/unselected
streams, unsupported tools, mismatched association batches, uncertain create
outcomes, webhook timestamp/account refusal and equal-time deduplication.

The initial probe incorrectly indexed `SorSourcePayload` as a dict. It was
corrected to call the existing accessor; no product contract was loosened to
accommodate the probe. The focused HubSpot type check passes. Its local hook
covers this adapter, not all vendors. Python lint, documentation verification and
`git diff --check` pass. Full-project Pyrefly reports **70 errors (3 suppressed)**,
down from 79. Remaining vendor request/response envelopes,
shared SOR dataclasses and broader platform typing are still open. These are
controlled contract checks, not live HubSpot, DB persistence or browser QA.

### Salesforce CRM command dispatch boundary

Salesforce validates the shared tool identifier as `CrmToolName` before its
eight-mutation dispatch map. Unknown tools and known but unsupported profile
tools retain the existing terminal refusal before HTTP. Move-deal payload
selection uses enum identity. Unlike HubSpot's fixed stream set, Salesforce
custom-object discovery/read identifiers remain dynamic validated strings; they
were not narrowed into the closed standard-object enum.

Executed **177 function assertions** before and after this change with identical
canonical requests and receipts. Checks use the actual adapter and HTTP request
model with a substituted final transport: eight mutations with enum/string input,
mapped custom fields, conditional-update headers, invalid targets/tools/mappings,
unselected objects, authentication/rate-limit/conflict/server responses, uncertain
create outcomes, probability unit conversion and custom-object discovery/readback.
The local vendor hook now covers both CRM adapters and passes. No live Salesforce
call, operator data mutation or browser acceptance is claimed.

### Confluence discovery, nested reads and page-update contracts

Confluence now validates selected strings into `ConfluenceStream` before schema
lookup and carries the enum through nested property/attachment reads. The private
page updater uses `_PageUpdateMode`, not an append boolean. It retains the typed
append/update payload through storage-body construction rather than combining
required append text and optional update text in a nullable local variable.

The nullable-text diagnostic was a static loss of correlation, not a reproduced
null append: `KnowledgeTextCommandPayload` already requires text. No empty-string
fallback or cast was introduced. Title-only updates preserve existing storage
markup; explicit empty text still replaces it with an empty paragraph. Source
revision comparison and next-version writes remain unchanged.

Executed **92 function assertions** before and after the edit with identical
canonical request/result snapshots. Coverage: all seven discovery streams;
invalid/empty selection; pages, bodies and latest-version projections; nested
properties and attachments through page scanning; append escaping, title-only,
text replacement and empty replacement; invalid payload refusal and version
conflict without a write. The final transport is substituted, while site
resolution, request construction, body projection and mutation dispatch are real.
The focused Confluence type check passes and joins the local vendor hook. These
checks do not prove live Confluence synchronization, persisted relationship
resolution or deployed document rendering. Broader native envelopes, remaining
policy booleans and shared SOR dataclasses remain open.

Combined checkpoint: all **445 assertions** across HubSpot, Salesforce and
Confluence pass against the final checkout. The expanded local vendor hook,
Python lint, documentation verification (46 pages, 285 links) and diff whitespace
check pass. Full-project Pyrefly reports **66 errors (3 suppressed)**, down from
79 at the start of these slices; a clean focused hook is not full-platform
completion. No service rebuild, DB change, live vendor call, browser QA, commit
or retained probe file occurred in these slices.

### Linear Knowledge and Ticketing read-path contracts

Both Linear adapters validate selected identifiers into their own stream enum
before discovery, query selection, mapped-field lookup and record projection.
Knowledge and Ticketing enums remain separate; the platform does not import a
combined vendor vocabulary. Valid requests and field projections retain their
existing shapes.

Two reproduced failures were resolved in this flow:

- Invalid discovery selection raised `RuntimeError: generator raised
  StopIteration`, with zero HTTP calls. Catalog label lookup assumed a known
  string before validating it. Both adapters now use their existing terminal
  `VENDOR_STREAM_UNSUPPORTED` refusal before catalog lookup. Empty selection
  retains `SOURCE_SELECTION_EMPTY`.
- `TicketingWorkflowStatePayload.order` accepts integer, Decimal or missing
  values, but Linear called `to_integral_value()` on every non-null value.
  Integer `1` raised `AttributeError`; Decimal `1` and `None` passed. Fractional
  validation now applies only to Decimal values, preserving the integer-only
  projected result and existing fractional refusal. This proves the accepted
  payload/normalizer contract, not that a configured live sync hit this branch.

Four internal values are now frozen, strict, extra-forbidden Pydantic models:
the two read cursors, Knowledge's attachment cursor and extracted attachment
reference. Cursor timestamps must be aware; attachment indexes must be
non-negative integers. Existing decode normalization and explicit durable
encoders remain in place, including the distinct Knowledge `version` and
Ticketing `v` cursor keys. No stored cursor rewrite or DB migration is needed.

Executed **397 function assertions** against the final checkout:

- Knowledge: 68 assertions covering three discovery streams, document/author
  pagination and refetch, attachment discovery/refetch, mapping/selection
  refusals, archived/not-found records and enum identity. Valid-path snapshots
  match the pre-edit baseline.
- Ticketing: 235 assertions across all nine discovery/read/refetch streams,
  full-reconciliation versus filtered query variables, mapped field projections,
  not-found/selection failures, integer/Decimal/missing workflow positions and
  canonical payload JSON readback. Valid-path snapshots match the baseline;
  the previously failing integer/discovery branches have explicit regressions.
- Cursors and attachment values: 94 assertions covering continuation encodings,
  overlap floors, attachment offsets, strict construction, timezone awareness,
  immutability, identity preservation and JSON round-trips. The existing cursor
  wire snapshots match their baseline.

The probes use real adapter/request/payload/normalizer functions with the final
HTTP transport substituted. They do not prove live Linear access, persisted
projection or relationship resolution, worker recovery or deployed browser
behavior. The local vendor hook now checks both Linear adapters alongside the
two CRM adapters and Confluence. Native GraphQL envelopes/record models, remaining
vendor payload contracts, shared SOR dataclasses and broader platform typing
remain open; eliminating these checker errors is not the full objective.

Checkpoint: full-project Pyrefly reports **56 errors (3 suppressed)**, down from
66. The five-adapter local hook, Python lint, documentation verification
(46 pages, 285 links) and diff whitespace checks pass. No operator DB changes,
live vendor operations, deployment, migration, commit or retained probe files.
The changed-build widget/admin acceptance gate remains open.

### Linear GraphQL envelope and rate-limit classification

The Knowledge and Ticketing adapters now share Linear-native Pydantic response,
error and extension contracts in `sor/shared/linear.py`, following the existing
shared vendor-protocol placement used by Atlassian. Known native codes use
`LinearGraphQLErrorCode`; unknown string codes remain terminal vendor errors,
not new platform enum members. Selected GraphQL data is still an operation-owned
mapping: document/user/issue response schemas remain open work.

RCA: both adapters rejected every non-success HTTP response before inspecting
GraphQL errors. A literal HTTP-400 `RATELIMITED` response produced
`VENDOR_REQUEST_REJECTED` / `TERMINAL`; the identical body at HTTP 200 or 429
produced `VENDOR_RATE_LIMITED` / `RETRY`. This contradicts Linear's current
[rate-limit documentation](https://linear.app/developers/rate-limiting).
The fix recognizes that HTTP-400 response before generic rejection. It does not
add adapter retries or change the runtime's mutation/idempotency authority.

Compatibility: successful data, first-error precedence, HTTP 401/403/429/5xx
handling, unknown error codes and bounded error text retain their prior
contracts. Partial data plus errors is rejected, as required by the existing
adapter behavior and [Linear's GraphQL guidance](https://linear.app/developers/graphql).
Malformed native shapes (including boolean `errors` or numeric error codes) now
fail typed validation; raw validation inputs are not placed in the resulting
platform exception. Additional vendor fields are ignored by the narrow envelope.

Executed checks:

- 576 function assertions: old/new classification matrix across both adapters,
  HTTP-400 regression, malformed envelopes, unknown codes, partial results,
  safe model representations and actual adapter → HTTP request → parser paths.
- Re-ran 397 prior Linear read/projection/cursor assertions. All three valid-path
  snapshot hashes remain unchanged.
- Expanded local type hook passes for the five adapters and shared envelope.
  Python lint, documentation validation (46 pages, 285 links) and diff checks
  pass. Full-project Pyrefly remains at 56 errors (3 suppressed); no new
  diagnostics were introduced by this slice.
- Final HTTP transport was substituted. No live throttling was induced and no
  operator source was changed. These checks do not prove deployed worker retries
  or browser behavior. The changed-build acceptance gate below remains open.

The operation-specific Linear Knowledge continuation is recorded below. Remaining
vendor flows still need native contracts; a clean checker alone does not complete
the platform-wide contract work.

### Linear Knowledge native request and response contracts

`knowledge/vendors/linear_contracts.py` now owns the consumed Linear GraphQL
document/user/reference fields, result wrappers, pagination and read variables.
The field types and nullability were checked against Linear's current official
[GraphQL schema](https://raw.githubusercontent.com/linear/linear/master/packages/sdk/src/schema.graphql).
These are operation projections, not a claim to model the entire Linear API.
The source uses the unversioned hosted GraphQL API; no SDK upgrade, new query,
scope or capability was introduced.

The adapter keeps models through pagination, archive checks, attachment
discovery/download and source projection. Dynamic mapped field selection remains
at `SorSourcePayload`, with canonical Knowledge payloads on the other side; the
core does not import vendor models. Record type determines the source stream,
removing the possibility of a separate record/stream pair disagreeing internally.
Known document parent/lifecycle and author labels use local enums; source format
uses the existing `KnowledgeSourceFormat` enum.

Contract refinements:

- Required native fields and nested reference IDs are validated. Nullable
  content/references remain optional. Unknown additional fields are ignored.
- Every page node validates before any record projection; malformed response
  data raises terminal `VENDOR_RESPONSE_INVALID`, without raw validation inputs.
- Explicit null document/user results mean not found. Missing result fields are
  malformed responses, no longer silently treated as deletion/not-found.
- Typed read variables retain the existing JSON names, nulls, bounds, filters
  and cursors. Boolean page limits are refused as `VENDOR_PAGE_INVALID` before
  HTTP work rather than entering the integer request path.
- Validated timestamp strings retain their original source-payload spelling.
  Cursor/source metadata conversion preserves the existing UTC interpretation
  of offset-free timestamps. Canonical `KnowledgeDocumentPayload` still accepts
  naive datetime values: the probe confirmed its existing normalizer prefers
  those payload dates over aware source metadata. Review this in the shared
  canonical timestamp pass; this slice did not silently alter that contract.

Executed function checks:

- 953 native-contract assertions: parent/lifecycle/date combinations compared
  with pre-edit projection functions, canonical document/author conversion,
  required/nullable/malformed fields, full-page refusal, model immutability and
  JSON round-trips, query variables, and real adapter/request/parser execution.
- 29 image-path assertions: current document lookup, attachment identity,
  bounded download request and origin-scoped headers, content result, 404/410,
  mismatched attachment and malformed/missing document refusal before download.
- 68 existing Knowledge flow assertions with complete vendor-shaped fixtures.
  Baseline captured before changing adapter consumption and final snapshot hash
  both equal `4eea7cf8dc179c70c1f3a09e3dbb558994569ad6122b3d8838aaba79e64a608c`.
  Fixtures now include required slug/user metadata fields; the earlier sparse
  fixtures were not used to weaken the vendor contract.

Final vendor send was substituted; these are not live Linear, persisted sync,
worker recovery, or browser claims. No operator data changes, migrations,
deployments, commits or retained test files. Next: native Linear Ticketing
read/mutation contracts, followed by remaining vendor/provider flows and the
shared canonical model cleanup. The product QA gate remains open.

Checkpoint: 1,955 function assertions passed including the existing envelope,
Ticketing and cursor checks. The expanded vendor type hook and full Python lint
pass. Full-project Pyrefly remains at 56 errors (3 suppressed), with no errors in
the changed native contract path. Documentation and diff checks pass.

### Linear Ticketing native request and response contracts

`ticketing/vendors/linear_contracts.py` owns the nine native record projections,
selected references, page metadata, query variables and mutation inputs/replies.
Types and required/nullable fields were checked against Linear's current official
[GraphQL schema](https://raw.githubusercontent.com/linear/linear/master/packages/sdk/src/schema.graphql),
including the input definitions and relation enum. This is the consumed API
surface, not a generated copy of the entire vendor schema. Knowledge and
Ticketing keep separate native contracts; canonical SOR types do not import them.

Read flow: HTTP/GraphQL envelope → typed connection/record → source-field mapping
→ existing canonical normalizers. All page nodes validate before projection.
Missing result fields are malformed responses; explicit null or archived records
remain not found. Native numeric and timestamp spelling is preserved in mapped
payloads. Source metadata uses timezone-aware parsed timestamps. Known native
state/priority/relation vocabularies and label actions have named enums; unknown
state categories still map to the existing canonical unknown state.

Mutation flow: canonical command → typed vendor input → alias-aware JSON at HTTP
boundary → typed mutation identity/revision → existing receipt. Omission and
explicit null remain distinct. No query, scope, tool name or idempotency-header
change. Persisted command hashes are computed from canonical intent before vendor
translation, not from HTTP body bytes.

Two request defects were reproduced before correction:

- A fractional estimate was sent to GraphQL despite `IssueCreateInput` and
  `IssueUpdateInput` declaring `Int`. Integral values now serialize as integers;
  fractional or out-of-range values are refused before HTTP.
- A present-but-null create team passed the mapping check despite Linear's
  required `teamId`. Typed create input now rejects it before HTTP.

Validation preserves the adapter's existing terminal rejection conventions.
Required mutation result shapes validate before success/receipt processing;
malformed replies are not accepted merely because a success flag is present.
Create/comment/relation transport uncertainty retains reconciliation-required
outcomes and sends no second request. Legacy dynamic-field helpers still use
mixed command/request/response error classifications for malformed local fields;
normalizing those diagnostics belongs in the command-boundary follow-up, not a
claim that all vendor error contracts are now uniform.

Executed function checks:

- 235 existing read/discovery/projection/cursor assertions using complete
  vendor-shaped fixtures. Pre-edit and post-edit source snapshots both hash to
  `c9b77e8e7c6de0dc5f1416dc17a8925fe765cc415f550a634a2c505faff13c5a`.
- 388 mutation assertions across 47 cases: compare pre-edit and typed adapter
  results, request semantics, idempotency headers, update omission/null behavior,
  all eight tool paths, rejected inputs, provider refusals and uncertain outcomes.
- 2,422 native-boundary assertions: registry coverage, required/malformed fields,
  full-page refusal, frozen models, JSON round-trips, extra vendor fields,
  numeric representation, archive/null/missing handling, paging bounds and safe
  error/representation output.

The final vendor transport was substituted. No live mutation, persisted sync,
worker recovery or changed-build browser coverage is claimed here. No operator
data, migration, deployment or Git history changes. The local vendor type hook
includes both Linear native contract files. Remaining vendors/providers and the
shared canonical cleanup still precede the final product acceptance gate.

Checkpoint: all 3,045 assertions re-ran successfully after formatting. The actual
expanded vendor hook reports zero errors; full Python lint and diff checks pass.
Documentation validation reports 46 pages, 285 links, 1,218 Python modules,
6,592 docstrings and 47 diagrams. Full-project Pyrefly remains at 56 errors
(3 suppressed), with no diagnostics in this changed native contract path.

### Curated Linear integration native contracts

The three curated Linear tools now use integration-owned models in
`pipelines/integrations_v2/vendors/linear/schemas.py`: selected issues, labels,
teams/users, result wrappers, filters, mutation variables, GraphQL envelope and
flat tool results. Native field types/nullability and filter/create/update input
shapes were checked against the current official
[Linear schema](https://raw.githubusercontent.com/linear/linear/master/packages/sdk/src/schema.graphql).
The hosted GraphQL API is unversioned; no package/API upgrade or scope change.
These contracts do not import SOR models. The shared curated context still owns
credential placement, the read/mutation split and durable outbound execution.

Reproduced defects, then repaired at native validation:

- `issues.nodes = [null]` previously returned an empty successful issue list.
  The permissive connection helper silently dropped malformed nodes.
- A retained label without an ID became `"None"` inside the replacement
  `labelIds` mutation input. A full selected issue/label set now validates before
  label removal can send anything.
- A mutation `success = "false"` was truthy and returned a successful issue.
  Success now requires a native boolean; false is rejected and true still needs
  an actual issue. Null issue reads retain not-found behavior; missing selections
  are malformed replies.

The underlying mistake was treating dictionaries as validated responses and
using best-effort extraction at an authoritative read/write boundary. The change
does not infer an author's intent or claim live incidents from these probes.
Known error/tool/priority values and query bounds now have owned enums/constants.
Additional vendor response fields and unknown native state categories remain
forward-compatible. Registered tool names, input schemas, descriptions, valid
flat output shapes and query documents remain unchanged.

Executed function checks:

- 478 assertions, including 56 pre-edit/current valid tool cases: input-schema
  parity, exact request structures/serialization, null assignees, all priorities,
  team/email resolution, case-insensitive label removal, malformed nested fields,
  whole-selection rejection, GraphQL errors and frozen/round-trip models.
- 108 guarded-HTTP assertions: real `GuardedVendorClient`, credential builder,
  request objects, response parser and mutation-owner handoff. Old/new raw body
  bytes, fingerprints, idempotency keys and attempt identities match. Reads
  bypass mutation ownership; writes without an owner or read-declared writes
  are refused. Timeout and malformed mutation replies cause no second send.

Final network transport and DB-backed outbound execution were substituted.
Therefore this verifies boundary wiring, not persisted receipts, deployed
recovery, vendor compatibility or browser behavior. The expanded local curated
type hook includes the full Linear integration directory. Shared curated
dataclass/context conversion and other vendor flows remain future slices of
the same platform-wide goal; final changed-build product QA is still required.

Checkpoint: all 586 assertions pass after final edits. The actual expanded
curated-tool type hook reports zero errors. Full Python lint, documentation
validation and diff checks pass. Full-project Pyrefly decreased from 56 to 52
errors (3 suppressed); the four resolved diagnostics were in Linear's untyped
nested result projection. No deployment, DB changes, commits or retained probes.

### Shared curated catalog and invocation contracts

Converted the eight dataclasses in
`pipelines/integrations_v2/contracts.py` to frozen, strict Pydantic values:
`VendorResponse`, `VendorAccount`, `VendorToolContext`, `ApiKeyPlacement`,
`InstanceUrlRequirement`, `VendorOAuthConfig`, `CuratedVendorSpec` and
`CuratedToolSpec`. Existing origin/auth/header and tool-metadata invariants moved
from `__post_init__` to after-validation rules. Wrong types, unknown fields,
string enums in Python constructors and coercible boolean strings are refused.
JSON round-trips for pure catalog values remain supported.

Live-resource boundary:

- `VendorHttpClient` remains a runtime-checkable behavioral protocol. An
  `InstanceOf` field validates structural membership without copying the client.
- HTTP clients, handler callables and input-model classes are excluded from
  snapshots and JSON Schema. They remain required execution dependencies,
  preserving identity; a metadata snapshot is not a runnable tool/context.
- `VendorResponse.data` is now `object` rather than `Any`: parsed data remains
  untrusted until a vendor-specific schema validates it. The raw object retains
  identity and is excluded from representations and generic serialization.
- The heterogeneous registry callable's input/result type erasure remains at
  its existing boundary: registered input models validate arguments, and
  execution validates returned JSON. This conversion does not claim every
  vendor's native fields have been modeled.

Verification:

- Pre/post catalog, input-schema and LLM projection snapshots cover all
  29 vendors and 148 tools. Both hashes are
  `ea680dd7633ee04a2056b670d8a4a6ebec44bbe128bde824a6b0c23fea009c3a`.
- 1,147 function assertions: pre-existing invariant failures, catalog JSON
  round-trips, hash/equality and duplicate-registration behavior, wrong-type
  refusals, frozen state, HTTP/account/handler/model identity, snapshot exclusion,
  exact context forwarding and read-declared mutation refusal.
- Re-ran the 586 curated Linear tool/guarded-HTTP assertions successfully with
  the converted shared values. The complete application imports with the dummy
  configuration; no lifecycle or live provider calls were started by this probe.
- Full-project Pyrefly remains at 52 errors (3 suppressed), with no additional
  diagnostics from changing the raw response annotation to `object`.

No operator data, migration, deployment or Git-history changes. Auth policy and
the existing PKCE option were not redesigned. Remaining provider/vendor schemas,
other platform values and the changed-build product QA gate remain open.

### Curated credential resolution, mutation owner and execution outcome

Replaced the remaining four dataclasses along the shared curated invocation path:
`VendorWireAuth`, `ResolvedVendorAuth`, `DurableMutationOwner` and
`CuratedToolExecutionOutcome`. The owner files remain `credentials.py`,
`resolution.py`, `http_client.py` and `execution.py`; no parallel contract layer.

The frozen Pydantic values preserve existing resource ownership. Origin-bound
header/query instances use `InstanceOf`, avoiding recursive conversion of their
immutable credential containers. They are excluded from snapshots/JSON Schema.
Resolved auth excludes credentials and serializes the safe origin as a string.
The durable owner requires a `CommandStepContext` instance, preserves it, and
excludes it while retaining the committed UUIDs. These snapshots are not a way
to recreate runnable authorization or live task contexts.

The execution outcome is different: its content is deliberately serializable
JSON. It validates JSON values, excludes content from repr, copies caller-owned
data and preserves the existing read-only metadata mapping. A field serializer
converts that mapping to ordinary JSON rather than leaking a `mappingproxy`.
No new auth policy, inline refresh, retry authority or network work inside a DB
transaction was introduced.

Executed checks:

- 174 function assertions with real grant/connection schemas, synthetic
  encrypted credentials, the actual decrypt/resolver/credential builder and
  guarded request builder. OAuth, Basic, header/query API keys and no-auth paths
  work. Organization/vendor/auth-kind/instance/scope/expiry/credential mismatches
  retain `auth_required`; service lookups retain scoped arguments.
- Identity, frozen-state, unknown/wrong-type refusal and snapshot checks cover
  credentials, origins and live step owners. Outcome tests cover safe error
  projections, JSON round-trips, read-only metadata, caller-data isolation and
  refusal of non-JSON/non-finite values.
- The 1,733 shared-catalog and Linear tool/guarded-HTTP assertions also pass with
  the new resolver/owner values. They continue to verify exact request bytes,
  fingerprints, attempt IDs and no parser-triggered second mutation.

Injected service reads replaced the DB; network and durable persistence remained
substituted. No live credentials, vendor calls, operator data or deployments
changed. Full changed-build product QA remains open.

Checkpoint: 1,907 function assertions passed across this path and the shared
curated/Linear regressions. The expanded local type hook, full Python lint,
documentation validation, diff checks and complete app import pass. Full-project
Pyrefly remains at 52 errors (3 suppressed); this conversion adds no diagnostics.

### F5 curated Google Sheets native contracts

2026-09-10: continued through the six existing Sheets tools, from registered
inputs through metadata/header reads, scalar cell mapping, guarded HTTP requests
and mutation receipts. Native schemas belong under
`pipelines/integrations_v2/vendors/googlesheets/`, not SOR or platform modules.

Reproduced before editing:

- A malformed row object became an empty successful read.
- An empty add-sheet reply became success with a null sheet ID.
- Spreadsheet creation followed by a rejected header write still returned
  `headers_written: true`.

RCA: dictionary shape checks silently discarded malformed values; the second
mutation response was not inspected. Native request/response Pydantic models
now validate the consumed data. Named tool/error/option enums remain vendor
owned. HTTP/envelope failures and malformed operation replies are coded tool
errors. No parser retries, new durable authority or DB transaction changes were
introduced. Mutations also check the receipt's spreadsheet identity.

Compatibility: the four non-cell input schemas are unchanged. Append/update
cell inputs intentionally narrow from arbitrary Python/JSON objects to Google's
supported scalars, including finite numbers and null skips. Valid request field
order, method, URL/query, JSON bytes, result keys, header lookup and row limits
are retained. Empty ranges may omit values; object sheets may omit dimensions;
sheet ID zero is accepted. Missing write counters remain unknown. Missing sheet
names no longer become the invented target `Sheet1`.

Executed checks:

- 339 native contract assertions, including 54 before/after valid cases,
  malformed responses, scalar type preservation, empty/no-op inputs, frozen
  models, JSON round-trips and unchanged non-cell input schemas.
- 1,555 assertions through the actual guarded HTTP client, origin-bound auth,
  request builder and outbound sender callback. The same 54 cases preserve
  exact request bytes, fingerprints and attempt identities. Reads produce no
  mutation attempt; the two creation writes use distinct sequence identities.
- Missing mutation authority refuses before send. A timeout, rejected or
  malformed second write fails without a third send. A malformed HTTP-success
  receipt can follow successful transport acceptance; it is not automatically
  permission to repeat the external effect.

Total: 1,894 function assertions. Network and durable persistence were
substituted; no live Sheets call or operator-data change occurred. The expanded
curated-tools type hook reports zero errors; full Python lint passes.
Full-project Pyrefly is 50 errors (3 suppressed), down from 52. Changed-build
browser/provider QA remains the final acceptance gate below, not covered by
these local probes.

The 1,907 earlier shared-catalog, credential-resolution and curated Linear
assertions also pass after the Sheets conversion: 3,801 combined assertions.
Complete app import, documentation validation and diff checks pass. No services
were rebuilt or restarted in this slice; no changed-build browser claim is made.

### F5 SOR discovery and selected-stream enum propagation

2026-09-10: followed discovery into field catalogs and downstream point/list
reads for Freshdesk, Intercom, Zendesk, Jira, GitHub and Notion. Eighteen checker
diagnostics came from retaining `str` after selected-stream validation, returning
literal strings from platform field-type mappings, or indexing native numeric
code dictionaries without converting to their owning enums.

The existing paths often worked through string/integer enum equality; these were
contract gaps, not evidence that live discovery was failing. The implementation
now preserves native stream enums after the existing selection/refusal checks.
Freshdesk keeps dynamic custom keys open and converts only fixed-catalog lookups.
Jira, Intercom and Freshdesk custom-field translations return `SorFieldDataType`.
Freshdesk status/priority/source readers convert recognized codes to native enums
and retain unknown read values; write conversions still refuse unknown codes.
No scopes, endpoints, retries, transactions, mappings or DB schemas changed.

Executed checks:

- 2,038 function assertions across 60 discovery selections, using actual adapter
  constructors, resolved context types and the origin-pinned HTTP client with
  a controlled transport. Every native stream, reversed selections and Freshdesk
  company/custom-object selection retain identical schema JSON and requests.
  Empty/unknown/unselected refusals retain their error and recovery codes.
- Custom-field type translations, numeric code/name inputs, unknown values,
  invalid booleans/types and Jira's special Sprint field retain their wire
  results; the successful internal values now have their owning enum types.
- 282 assertions across 51 public bootstrap/change-read/point-read cases for
  the affected support adapters retain request URLs, methods, credentials'
  origin binding, empty-page results/cursors and not-found identities. A fixed
  probe clock made cursor comparison deterministic; production clocks did not
  change.

Total: 2,320 local assertions. No live vendor or DB calls, operator changes or
deployments were performed. The SOR vendor pre-commit/pre-push hook now includes
these six adapters and triggers for support vendor edits; it reports zero errors.
Configured full Python lint, complete app import, documentation validation and
diff checks pass. Full-project Pyrefly is 32 errors (3
suppressed), down from 50. Full native payload typing across the platform and
the changed-build product QA gate remain open.

### SOR action events and detached recovery identities

Trace: successful command or connection lifecycle write → SOR-owned typed
payload → generic durable envelope → committed delivery → detached recovery
identity → Absurd spawn/bind. Revocation separately fences sources and captures
work in the caller's transaction, then cancels after commit.

Completed:

- Replaced SOR action/connection payload dictionaries with explicit frozen,
  strict Pydantic values. Event names and projection dispositions use their
  owning enums; OAuth, refresh, API-key onboarding, command projection and
  revocation callers now pass the typed values.
- Converted delivery batches, revocation plans and stop results from dataclasses
  to Pydantic. Recovery scans construct named organization/work identities from
  SQLAlchemy rows before releasing the read transaction.
- Preserved wire event names, deterministic IDs, payload keys, unknown-action
  skipping, batch failure isolation, existing durable idempotency authority and
  cancellation ordering. No new event persistence or scheduling lane.
- Expanded the local SOR recovery type hook to include these producers,
  consumers and durable event binding.

Verification: **899 assertions** across two ephemeral probes. Real ORM
constructors, SQLAlchemy result rows and public function paths were used with
controlled transaction/services/runtime I/O. **480 captured event envelopes**
match the prior implementation across action tools, projection dispositions,
target selection, connection events, profiles, optional source/connector IDs and
timezones. Checks cover strict/frozen snapshots, excluded extra data, missing
finish times, sequence bounds, detached ownership, scoped SQL, source fencing,
post-commit cancellation, existing task binding, terminal-state refusal,
partial failures, parent cancellation and runtime closure.

The expanded hook and configured Ruff pass. Full-project Pyrefly decreases
from **32 to 26 errors**; three suppressions remain. This is not live DB locking,
worker-crash/restart, provider or browser proof. No operator data, provider
configuration, schema, deployment or Git history changed in this slice.

### SOR onboarding, generation and selective-read contracts

Trace: source selection and schema revision → atomic mapping/stream publication
→ generation plan → DAG advancement → page context/counters → canonical grid
query. This slice completes the four remaining SOR type errors without casts or
new suppressions.

- Onboarding explicitly checks the schema ID before repository lookup.
- DAG advancement keeps the validated stream association alongside run keys.
  Dependency release, failure propagation and lock order remain unchanged.
- Five onboarding/sync dataclasses become frozen, strict Pydantic contracts.
  Live ORM fields use instance validation and are excluded from repr/JSON/schema;
  identity is preserved. Counter values reject booleans, strings, fractional
  values and negatives instead of permitting malformed internal state.
- SOR generation failure reasons use a domain enum, not vendor error types;
  existing attempt and batch bounds have named constants.
- Canonical grid fields and all four profile factories require mapped ORM
  attributes. SQL expressions are derived at the filter-contract boundary;
  custom-field computed expressions remain separate.
- Removed the unnecessary override of Pydantic's internal extra-field storage.
  Mapped commands retain their existing strict JSON before-validator, nonempty
  requirement, field access and wire payloads. Runtime-discovered keys remain
  dynamic by design.

Verification: **16,394 assertions** in three temporary probes. These include
**867 before/after DAG comparisons**, real ORM instance identity/snapshot
checks, counters, nested mapped JSON, missing-schema refusal, expansion and
publication-result construction, plus **372 generated PostgreSQL query
comparisons across 28 entity specs**. Query comparisons cover combined search,
filter, group, sort, source scoping and selected-column loading. Query parameters,
SQL and empty-page/grid outputs remain unchanged.

Expanded the local SOR catalog type hook to include the changed domain/read
contracts and their profile factories. The hook and configured Ruff pass.
SOR-wide Pyrefly reports **0 errors, 1 existing suppression**; full-project
Pyrefly decreases **26 → 22 errors, 3 existing suppressions**. This does not mean
every remaining SOR dataclass or vendor payload is migrated. The complete
platform typing and changed-build product QA gates remain open.

Controlled repository/runtime I/O was used; no live transaction locking,
vendor synchronization, worker crash/restart or browser behavior is claimed.
No operator data, migrations, credentials or deployment changed in this slice.

### SOR read values and custom-dataset expression contracts

Trace: canonical profile factory or runtime custom dataset → read spec → filter,
ordering and selective loading → ORM result rows → grid/page response and cursor.

Eight read/custom-dataset dataclasses now use frozen, strict Pydantic contracts.
SQL expressions, read callbacks, ORM model classes and row instances remain
runtime dependencies, excluded from repr/JSON/schema. Decoded cursor values use
an explicit union of supported native scalar types; the existing wire codec and
query fingerprint remain authoritative.

The custom-dataset trace exposed a limitation in the previous slice's
ORM-attribute-only annotation: the existing coalesced record label is a computed
SQL expression. The current runtime path still worked; blindly enforcing that
annotation through Pydantic would have broken it. Read fields therefore accept
either mapped attributes or computed expressions. Canonical entity validation
requires mapped attributes for selective loading; custom datasets preserve the
computed SQL identity. No cast or fallback bypasses this distinction.

Verification:

- **4,848 assertions** covering resource identity, strict/frozen values,
  excluded dependencies, reference/field validation, cursor encoding and
  restored native types, plus **39 populated-page SQL/response comparisons**.
  These include 28 canonical entities, the custom-dataset record label, every
  custom field type and combined custom-dataset filter/sort/search.
- Existing **4,120 assertions / 372 query configurations** continue to pass.
- The custom probe originally omitted the required source profile; corrected
  its ORM fixture, not the production validation.
- Local SOR catalog hook now covers custom dataset services/factories alongside
  canonical reads. Configured Ruff and SOR-wide type checks pass, with the
  existing SOR suppression unchanged.

These are controlled-I/O function/SQL checks, not actual DB query execution,
browser rendering, vendor synchronization, or changed-build product QA.
No operator data, schemas, credentials, services or Git history changed.
Remaining platform types, vendor contracts and final product QA stay open.

### Analytics query, aggregate and public response contracts

Trace: authenticated route and enum/date parsing → analytics service → bound
PostgreSQL query → validated detached aggregate → typed public count points.

- Analytics owns entity/time-unit enums and frozen, strict Pydantic query and
  result contracts. The time unit is a SQL bind parameter, not interpolation.
- Repository results are named validated values, not positional SQLAlchemy
  rows returned under a bare `list` annotation. The repository owns the read
  transaction; the redundant surrounding route transaction was removed.
- Public `count`, `date` and `agentId` wire names, inclusive date bounds,
  default daily buckets, joins/counting rules and authorization are preserved.
  OpenAPI and regenerated console types now describe the response shapes.
- Added a focused local analytics type-check hook; no hosted CI was added.

Verification: **479 assertions / 48 query executions** using real SQLAlchemy
row types and the actual FastAPI router with controlled auth/transaction I/O.
Coverage includes all entities/time units, populated/empty results, before/after
SQL and output parity, invalid values, cross-org refusal, strict/frozen models,
OpenAPI, and transaction closure on failure/cancellation. SQL comparisons do
not claim execution against PostgreSQL or the operator DB. Console types were
generated from a temporary loopback-only current-code app with dummy config and
startup jobs disabled, not from the older development image.

Analytics Pyrefly has **0 errors**; full-project errors decrease **22 → 19**,
with three existing suppressions unchanged. Remaining platform/provider typing
and changed-build end-to-end QA remain open. No operator data, migrations,
provider configuration or Git history changed in this slice.

### Deployment-value and HTTP exception-handler contracts

Trace: process environment → config fallback → app composition → registered
provider failure → framework dispatch → existing safe HTTP response.

The environment helper now declares its fallback-dependent return type through
overloads; absent/empty environment values still return the supplied fallback,
including object identity. No deployment defaults, credential resolution or
connection URLs changed. Provider HTTP handlers accept `Exception`, then narrow
to the registered family before reading domain fields. Unexpected exception
families are re-raised. Existing handled response bodies/statuses are unchanged.

Inspected installed Starlette **1.3.1** handler signatures and class-MRO dispatch,
alongside its [exception-handling reference](https://starlette.dev/exceptions/).
The 422 constant uses the nondeprecated name for the same numeric status.
Corrected the cipher-handler docstring: its log contains the exception type,
not key material, ciphertext or the underlying exception message.

Verification: **247 assertions / 21 actual ASGI responses** cover the helper's
fallback cases, every capability, handled error subclasses, public status/body
parity, unrelated exception identity, secret-safe logs and the actual app's
registered handlers. External providers, DB access and app lifespan services
were not exercised. Added a focused local bootstrap type-check hook. Full-project
Pyrefly decreases **19 → 14 errors**, with three suppressions unchanged.

### Voice receiver, recording and numeric contracts

Trace: connected TTS WebSocket → receiver task → byte queue; recording capture
refusal → existing failure-filing path; authenticated recording download → audio
stream; optional SciPy audio utility → native numeric kernels → PCM frames.

- Murf/Smallest receivers take the connection captured at task creation rather
  than reading an optional mutable field on startup. Queue/task generics now
  describe bytes and `None`. Native request/response JSON coverage is still a
  separate pending vendor-contract task.
- `RecordingCaptureFailure` names the existing unsupported-encoding and
  inconsistent-owner reasons. Filing receives the same string values. This is
  platform policy, not a vendor enum.
- Removed the WAV-only response subclass. The route supplies the content type
  to ordinary `StreamingResponse` and explicitly declares the unchanged WAV
  OpenAPI response. Starlette 1.3.1's inherited attribute is inferred as `None`;
  adding `str | None` to the subclass did not resolve mutable-override variance.
  No type suppression or patched dependency was introduced.
- The SciPy utility uses PCM16 array contracts, named bounds/buffer size, and a
  checked protocol for its two public lazy exports. Existing filtering,
  buffering, rounding and channel algorithms remain unchanged. Inspected
  SciPy 1.16.3 and the 1.16 references for
  [FFT resampling](https://docs.scipy.org/doc/scipy-1.16.0/reference/generated/scipy.signal.resample.html)
  and [polyphase resampling](https://docs.scipy.org/doc/scipy-1.16.0/reference/generated/scipy.signal.resample_poly.html).
  This utility has no production constructor call site in the current checkout;
  these checks do not substitute for the active SoXR playback pipeline.

Verification: **417 assertions / 120 frame cases** compare PCM bytes, metadata
and flush behavior against the prior implementation using installed SciPy and
real audio frames. Recording checks cover normal capture, encoding refusal,
owner mismatch, single filing, cleanup and the unchanged OpenAPI/header shape;
DB/storage filing was controlled, not live. One temporary fixture used the wrong
method name; corrected it to the inspected `set_user_audio_format` API without
changing production code to fit the probe.

**46 assertions / six real loopback WebSocket connections** verify Murf PCM/WAV,
Smallest binary/base64 audio, malformed JSON, provider-error termination,
cancellation and connection closure. Dummy credentials were used; no hosted
vendor endpoint was contacted. Expanded the local voice type gate. All five
changed paths type-check without errors or new suppressions. Changed-build
browser/provider QA and remaining platform contracts stay open.

### Shared enum, cache and tool declaration contracts

Verified locally on 2026-09-10. Full-project Pyrefly now reports **0 errors,
2 existing suppressions**; this is a static milestone, not completion of the
all-vendor contract work or live product acceptance.

- `CaseInSensitiveEnum` resolves member names through `__members__`; matching,
  alias handling and existing unknown-value behavior are unchanged.
- The async Redis cache preserves callable parameters and declares JSON-valued
  results. Its existing `v` envelope is validated on read; malformed entries
  remain misses. Key encoding, TTL, Redis-error fallback and cancellation remain
  unchanged. Removed the unused test-only `cache_key_fn` function attribute;
  no first-party consumer or production decorator call site was found.
- `ToolFunctionMetadata` replaces scattered private schema/feature/visibility
  attributes. All first-party producers and registry consumers use the typed
  accessor; native functions remain native functions. Input-schema classes
  retain identity but are excluded from snapshots and JSON schema generation.
- Removed the duplicate Claude result `type` annotation while preserving its
  existing effective `str` contract and field order. This unused model is not
  evidence of native Anthropic response validation.

Executed checks: all 80 registered tool schema/docstring fingerprints and
identity metadata match the pre-change snapshot; metadata rejects invalid
values, stays frozen, and preserves feature/visibility gating. Before/after
cache probes cover 26 value cases, cache corruption, ignored context parameters,
TTL, unavailable Redis, function failure and cancellation. Eleven enum inputs
match before/after. An initial probe incorrectly repeated the enum's existing
`str` base; correcting the probe resolved its MRO error without changing code.
Redis I/O was controlled; no live vendor or database persistence is claimed.

Architecture remains common declaration contracts → owning registry/pipeline
consumers. No runtime execution policy, provider authority, database schema,
operator configuration or worker topology changed. Remaining vendor payload
contracts and changed-build browser/provider QA remain open below.

### Changed-build product QA acceptance gate

#### 2026-09-10 Murf native-message slice

Target: installed Pydantic 2.11.10 / websockets 15.0.1; existing Murf WebSocket
adapter and configured values. Native request/response schemas now live in
`sockets/tts/adapters/murf_wire.py`; SDK/vendor shapes do not enter modules or
framework contracts. Initialization, text, clear and audio parsing use those
models, with strict payload fields, bounded input and private diagnostics.
The initial slice validated audio/final alternatives without repairing lifecycle.
The follow-up below now consumes final/context identity and fails malformed turns.
This is not a completed native Murf runtime acceptance claim.

Source-backed request correction: buffering values were URL query parameters
(`max_buffer_delay_ms`), but the
[Murf AsyncAPI](https://murf.ai/api/docs/api-reference/text-to-speech/stream-input)
defines a WebSocket settings message using `max_buffer_delay_in_ms`. Initialization
now sends configured buffering explicitly. Its documented bounds and variation
bounds are enforced before opening the connection. Query values are escaped;
keys containing query delimiters no longer change the handshake structure.

Compatibility caveat: the generated schema uses `voice_id`/`api_key`, whereas
the [quickstart](https://murf.ai/api/docs/text-to-speech/web-sockets) uses
`voiceId`/`api-key`. Retained the established quickstart spellings and endpoint;
did not silently switch to a newer model or edit stored configs.

Verification: 113 new function assertions cover native serialization, field
constraints, strict audio/final parsing, malformed encodings, credential escaping,
private snapshots and a real local WebSocket exchange through the adapter.
The previous 46 assertions across six Murf/Smallest loopback connections pass
unchanged. Full Python lint and Pyrefly pass (zero errors, two existing
suppressions; two existing redundant-cast warnings). Added the wire module to
the local voice type hook. No native Murf provider, deployed-image or human
audio-quality claim; no migration, provider reconfiguration or retained tests.

Lifecycle follow-up: the old adapter reproduced two contexts for two chunks of
one turn, no completion after final, and connected state after socket EOF. The
receiver forwarded bytes without owning the native turn lifecycle. The adapter
now uses an explicit stream-state enum, one context per turn, exactly one flush
marker, and matching final completion. Interruption invalidates identity before
clear. Direct socket consumption removes the adapter's dropping queue; this does
not claim that all downstream voice queues have non-dropping backpressure.

An incremental private-state decoder validates mono PCM16/WAV framing, configured
sample rate and bounded headers, retaining incomplete samples across frames.
Malformed messages/media and unexpected EOF report terminal synthesis errors.
Connection initialization/send/close are bounded; close tasks retain ownership
through cancellation. Empty synthesis returns without waiting for native output.

Executed 632 assertions: all two-way WAV splits, bytewise WAV/PCM, streaming WAV
lengths, malformed/truncated audio, snapshot exclusion, concurrent connect,
same-context chunks, idempotent flush, cancellation-safe receive polls, late
interrupted output, 600-frame delivery, provider errors, absent context, binary
frames, invalid base64 and EOF across eight real local WebSocket connections.
These intentionally replace old private receiver/queue expectations; the earlier
113/46 assertion counts above describe the wire-only checkpoint, not a rerun of
those old lifecycle expectations against this replacement.

Additional checks passed: initialization failure/cancellation, send cancellation,
and caller cancellation during close (retained cleanup owner, exactly one close,
zero unhandled tasks). The real `TTSFactory` and `TTSRealtime` request/consumer
queues ran against a local WebSocket peer: matching final produced `DRAINED`,
exact PCM bytes reached the consumer, and unexpected EOF produced `FAILED` plus
an unsuccessful flush. Event emission was captured locally; these probes do not
exercise browser playback or the native vendor. Full Python lint and Pyrefly
pass (zero type errors, two existing suppressions and redundant-cast warnings).

Remaining: native verification and widget/console voice QA. Legacy model/endpoint
compatibility must be resolved explicitly, not inferred from a green type check.
This lifecycle follow-up is not in the deployed image below.

Browser smoke follow-up: console and widget were already running on ports 5173
and 5174. After the console session expired, signed in using the existing private
test-account file; the original conversation deep link was restored. In the
existing mixed-agent conversation `01a08910-4ce5-70a1-87bb-e09de648cb7c`, marker
`QA_BROWSER_20260910_RECHECK` triggered fresh `memory_recall` and `kb_query`
(`top_k=2`) calls. Widget showed Cedar Lantern with citation K1; console showed
35/35 completed persisted messages, three recalled memories, one KB result and
Bedrock ranking applied. The configured background observer also completed and
reported memory consolidation; this is not a claim that the entire run made no
writes. No provider reconfiguration or database reset occurred.

#### 2026-09-10 rebuilt-backend browser checkpoint

Rebuilt image `8c5c17de9edf` and recreated only the development API, Absurd
worker, Taskiq worker and scheduler. PostgreSQL/Redis containers and volumes
were left intact; existing and checkout migration heads were both `eylo0012`.
Console/widget use the existing Eylo Development org and configured providers.
No provider reconfiguration, migration change, Git commit or push occurred.

Executed through the actual widget and verified in console conversation details:

- Groq continuation: conversation `01a086a8-7d86-77e0-95c0-a11ba8655406`,
  marker `QA_TYPED_20260910_GROQ`, returned `397`; eight persisted messages
  displayed with completed user/agent exchanges.
- Mixed agent: conversation `01a08910-4ce5-70a1-87bb-e09de648cb7c`, marker
  `QA_TYPED_20260910_MIXED`, made fresh `memory_recall`, `kb_query` and
  `compound_render_widget` calls. The KB input requested `top_k=2`; one matching
  result returned with citation `K1` and Bedrock ranking state `applied`.
  The generated summary card appeared in the widget. All 27 persisted messages
  loaded after the configured background continuation completed. That background
  observer reports memory writes, so the overall run is not a no-write proof.
- New SOR conversation `01a08a9f-bfbc-7ae0-b5bd-6f5ca21ecd2c`, marker
  `QA_TYPED_20260910_SOR`, executed `issue_search`, `issue_get` and
  `issue_list_projects`. Ten persisted messages completed; issue, assignee and
  team names were present in tool results and the widget answer. This reads the
  synchronized projection; it does not prove fresh upstream vendor sync.
- Console pagination and direct transcript navigation worked; widget agent
  selection, new conversation, back navigation and loading older conversations
  worked. A visual console check confirmed readable, wrapped transcript content
  at the active browser width. No exhaustive responsive or accessibility claim.
- Follow-on form QA at 15:00–15:03 local time: existing `QA Dynamic Widget Agent`
  conversation `01a0849a-fac4-7c72-9e60-92f2efec9a58` rendered a fresh form through
  `compound_render_widget`. Empty submission displayed `Result is required.`;
  valid submission `QA_BROWSER_20260910_FORM_OK` became read-only and reached the
  configured Bedrock agent. Leaving and reopening the conversation retained the
  submitted value and disabled input. Console showed 14 of 14 completed messages,
  including the new tool arguments, delivered result, widget message and linked
  widget response. No provider, organization or external source was changed.

Follow-up observation from the SOR transcript: `issue_list_projects` returned
duplicate field descriptors for `name`, `description` and `key` within the same
source. The returned record was usable, but descriptor aggregation needs a
focused diagnosis; this browser check does not establish its root cause.

The old widget dev-server process exited during this session. The offline UI
and failed history retries coincided with port 5174 no longer listening, which
also removed its WebSocket proxy. Restarting Vite restored HTTP 200 and a fresh
widget tab connected successfully. Cause of the dev-process exit was not
established; this is not proof of a backend reconnect defect or a successful
automatic reconnect test. The stale browser error tab also required a fresh tab.

Checks: Python lint/type checks, expanded local shared-contract type hook,
documentation verifier, web lint/type/build and widget SDK/Preact builds pass.
The web build retains the existing large-chunk warnings. The inspected bounded
API/worker log window had no error/validation traceback matches. Remaining
all-vendor contracts, native voice, uploads, external mutations, cancellation
and crash/restart-recovery acceptance are still open; these three conversations
do not certify the entire platform.

2026-09-10 user requirement: after implementation, run the real widget and
operator console against the existing Eylo Development organization. Reuse its
configured providers and agents; read credentials only from the private local
credentials file. Do not create a replacement organization or expose secrets.

Ordered acceptance checklist:

- [ ] Finish the current implementation scope and required local checks.
- [ ] Rebuild/recreate the development backend and workers; verify that the
  deployed files match the changed checkout before claiming coverage.
- [x] Confirm console `/login` on port 5173, widget on port 5174 and API `/health`
  on port 8000 respond. All returned HTTP 200 on 2026-09-10; existing servers
  did not need another start. API, PostgreSQL and Redis reported healthy.
- [x] Log in through the browser and confirm the existing organization.
- [ ] Converse with configured agents through the widget: ordinary conversation,
  knowledge retrieval/citations, memory and configured read-only integration/SOR
  tools. Exercise conversation navigation, reopening and message pagination.
- [ ] Inspect the same conversations in the console: visible messages, terminal
  message states, tool arguments/results and correspondence with widget output.
- [ ] Exercise affected voice setup/teardown paths where media access permits;
  distinguish automated checks from human audio-quality validation.
- [ ] Record exact exercised agents/conversations, failures and unrun cases.

Earlier readiness checks were blocked by a native Mac-lock error. On the latest
2026-09-10 attempt, the in-app browser remained usable despite that inventory
warning. Login succeeded in the existing Eylo Development organization; neither
frontend needed another server process. The API and workers were already up;
the API container has no checkout mount, so this smoke check does not cover the
unrebuilt local edits. No provider configuration or deployment was changed.

Latest readiness refresh after analytics/bootstrap checks: the console process
was no longer listening, so it was restarted on `127.0.0.1:5173` with strict-port
selection. The existing widget process on 5174 remained available. Signed in
using the private test credentials; the existing organization and conversation
detail loaded, including all 15 messages and tool exchanges. Navigating back
loaded the 20-row first page of 28 conversations. The widget retained its
existing Groq conversation. This checks current console readiness against the
older backend, not the pending rebuilt-backend acceptance gate.

Deployed-build browser evidence:

- `QA Core Mixed Agent`, conversation
  `01a08910-4ce5-70a1-87bb-e09de648cb7c`: actual `memory_recall` and `kb_query`
  calls returned one result each. Both result envelopes reported Bedrock ranking
  applied; the knowledge result included citation `K1`. The response used that
  label. `compound_render_widget` subsequently returned `delivered`, and the
  widget displayed the requested title, subtitle and sections.
- The same console conversation displayed **15 of 15 persisted messages**, all
  in completed states, including tool arguments/results, widget output and both
  background task/result pairs. Background results reported the configured
  Claude Haiku model; no external mutation was requested.
- Widget back-navigation and loading older conversations worked: the loaded
  list grew from six to ten. Reopened the existing `QA Minimal Groq Agent`
  conversation, asked it to subtract one from the prior multiplication result,
  and received `390`, correctly using its stored `391` context.
- UI finding: generated card text displayed literal Markdown markers from the
  model's `text` props. Delivery succeeded; presentation-contract diagnosis and
  remediation remain pending. No claim that the full UI is polished.

Changed-build QA, additional providers, SOR/integration tools, file ingestion,
message-page boundaries and voice/media quality remain unrun in this checkpoint.
The widget and signed-in console tabs were retained for continued QA. This
updates the former blanket browser blocker; it does not close the release gate.

### F5 next slice: Smallest protocol evidence gap

2026-09-09: source tracing found the Smallest adapter hardwired to Lightning v2,
regardless of configured model, with loose JSON parsing, a dropping audio queue
and no turn-completion override. These are inspected findings, not reproduced
native-provider failures. No Smallest implementation or operator config changed.

The current [native WebSocket reference](https://docs.smallest.ai/models/api-reference/text-to-speech/tts)
defines `/waves/v1/tts/live`, explicit v3.1 model selection and nested
`status`/`data.audio` events. The [vendor deprecation notice](https://docs.smallest.ai/models/changelog/lightning-v-3-1/2026/5/2)
marks v2 as legacy; its old Markdown schema now returns Page Not Found. Do not
infer v2 compatibility from the current schema or silently replace operator
models. Next: establish the legacy compatibility contract or a deliberate model
migration, then implement typed messages and prove completion, backpressure,
interruption, and cleanup through the actual TTS manager.

### Live browser recheck after the terminal-artifact fix

2026-09-09, 22:02–22:04 local time: both existing UI servers returned HTTP 200;
the existing authenticated Eylo Development session was reused. No restart,
provider reconfiguration or organization switch was needed. API and all three
workers remained up; Postgres and Redis remained healthy.

In conversation `01a086e4-f8ce-7883-8cad-1eee68c5e15e`:

- Reopened the submitted form: its value remained visible and read-only.
- Sent a new read-only request through the widget. `memory_recall` returned the
  same conversation memory ID `1bd73f8f-9eaa-4213-ba5e-05d1e5aa1454` and fact,
  with Bedrock reranking applied. Admin showed the actual call/result Completed.
- Requested `kb_query` with `top_k=1`. Admin confirmed one result, Bedrock
  reranking applied, and citation K1. The assistant correctly distinguished
  the incident escalation phrase from the release codename using source data.
- The admin transcript reached 28 persisted messages; new user, tool,
  assistant and background-result messages were Completed. Background results
  alone still do not prove background-agent tool execution.
- Widget Load older conversations expanded the list from 12 to 15 entries.
  Admin Refresh still briefly clears the transcript; this known UI issue remains.

These checks exercise the running build, not the undeployed Rime slice or a
native Smallest connection. No external mutation, migration or DB reset.

### Live QA correction: committed widget terminal artifacts

2026-09-09: rebuilt API/workers with the typed TTS changes, preserving the
existing environment, Tailscale API URL, credentials, Postgres and Redis. Alembic
remained at `eylo0012`. Both UIs stayed available; the widget reconnected and
loaded older conversations. Deepgram's existing TTS configuration passed live
verification through the console. The QA org has no OpenAI or Groq TTS config,
so their native vendor acceptance remains unverified.

Mixed-agent conversation `01a086db-4e9a-7fa3-8b07-a2063ba38823` exposed a separate
terminal-artifact failure. The first `memory_remember` saved conversation fact
`1270ee67-c328-4216-885b-eb4e7e55b92a`; `memory_recall` returned that same fact with
Bedrock reranking. `compound_render_widget` persisted its form. Nevertheless,
`_terminal_artifact_message` searched only the pre-tool context's message list.
Absurd recorded **Terminal artifact message was not persisted by this run.**
Three attempts replayed the turn, generated three forms, and eventually marked
the request and previously successful exchanges Failed. Later repeated memory
writes returned unavailable; those are not evidence that the first write failed.

The terminal resolver now loads the exact artifact through `MessageService`,
then validates ID, conversation, request, assistant kind and widget content kind.
It does not append uncommitted data or reload the full history. The existing
AgentRun association validation remains in terminal persistence. A function
probe with real Pydantic models covers stale snapshots, exactly one lookup, six
authority refusals and a non-artifact result that performs no I/O. Focused
Pyrefly and backend Ruff pass. Original failed QA records are retained as
evidence. The corrected image was rebuilt and all four application services
recreated without changing the QA organization, credentials or databases.

The same browser pass also confirmed an unset form default rendered the string
`null`. `WidgetForm` treated JSON null as an explicit value, then called
`String(null)` for ordinary inputs. Null and omitted defaults now produce empty
text/unchecked checkbox values; explicit zero, false, true and strings survive.
Eight function-input cases pass against the actual TypeScript initializer;
the prior null-string behavior was reproduced. SDK and Preact lint/type/build
commands pass.

Fresh browser acceptance: conversation `01a086e4-f8ce-7883-8cad-1eee68c5e15e`
used the configured QA Core Mixed Agent and real Bedrock providers:

1. `memory_remember` saved `1bd73f8f-9eaa-4213-ba5e-05d1e5aa1454` with the
   conversation fact "The deployment checkpoint is amber observatory."
   `memory_recall` returned the same identity with Bedrock reranking applied.
2. One form was persisted as `01a086e5-4c52-7190-a2c3-189e5e2c5aec`; its required
   text field started blank. Submitting blank displayed the required-field
   error and focused the field. Submitting `amber observatory` succeeded.
3. The widget received the assistant acknowledgment. Navigating to the list and
   reopening the conversation retained the submitted value in a read-only form.
   The admin conversation detail showed Completed messages and tool results,
   including the background follow-up outcomes. This does not establish a
   background agent's own tool dispatch; that was not observed in these turns.
4. Console lint, TypeScript and production build passed, with the existing
   large-chunk warning. Documentation verification passed. API and all workers
   remained running; the API health check passed. Since the successful run,
   worker logs showed no error, traceback or stale terminal-artifact failure.
   The API logged a trapped Passlib/bcrypt version-introspection traceback at
   login; login still succeeded. That dependency compatibility warning remains
   open, rather than being suppressed or mistaken for a failed agent run.

Focused milestone review, performed in order:

1. DDD boundaries: message persistence stays in the conversation service;
   orchestration resolves its committed artifact. Form default rendering stays
   in Preact rather than changing the SDK or domain schema.
2. Architectural fit: the existing tool-result commit and terminal-message path
   remain authoritative. No duplicate persistence lane, context cache mutation
   or new dependency was introduced.
3. Data flow: committed widget ID → exact service lookup → conversation/request/
   kind validation → existing AgentRun guard → terminal completion. Null form
   defaults → empty controls → required validation → persisted submission.
4. Plan alignment: these two runtime/UI corrections were added because the
   requested real-agent QA exposed them. They do not imply completion of the
   platform-wide typing plan or native OpenAI/Groq voice acceptance.
5. Clean code/security/performance: one bounded message lookup replaces the
   stale snapshot search; foreign identities are refused before use. Existing
   meaningful form values are preserved without a second schema or conversion
   system. No new blocker found in this focused review.

Human review of the resulting experience remains available through the recorded
conversation. Existing background-agent chooser hydration and admin refresh
flicker remain separate UI findings. No commit, migration, database reset or
external vendor mutation was performed for this QA correction.

### F5 progress: embedding/reranking API settings and projections

2026-09-09: both API families now expose owned provider enums and typed settings.
Create/read selectors reuse domain parsing; PATCH uses a typed editable-field
object because its provider comes from the stored configuration. Explicit nulls
survive PATCH serialization for service validation. Endpoint trust, secret
replacement, revision behavior and masked response values remain in their existing
owners. Embedding response dimensions now come from typed verification metadata.

Function/HTTP checks caught and resolved three in-progress refactor errors before
deployment: a dict-returning serializer erased concrete OpenAPI types; FastAPI's
`from_attributes=True` let an untagged union run Bedrock validation on an OpenAI
settings object; and a callable tagged union emitted an invalid `oneOf` for
overlapping model-only JSON shapes. Provider-selected runtime tags, typed PATCH
fields, unset-field response exclusion and an `anyOf` wire schema address the
actual boundaries. No new tag key, vendor default, endpoint or dependency upgrade.
The discriminator API was checked against installed Pydantic 2.11.10 and its
[versioned documentation](https://docs.pydantic.dev/2.11/concepts/unions/#discriminated-unions-with-callable-discriminator).

Executed 212 route/controller/service contract assertions across all six provider
branches, with static/session AWS credentials and compatible endpoints; 80 JSON
Schema/runtime-union assertions; 86 embedding material regressions; and 310
reranking authority/projection regressions. Total: 688. The reranking probe now
checks the typed config's serialized projection instead of equality to a dict;
its expected JSON is unchanged. Auth and foundation persistence were substituted;
no operator data, provider request, deployed image or migration was changed.

All 11 scoped typing/import gates, backend Ruff, changed-file formatting and
documentation validation passed. Regenerated the console client from the
changed-source schema-only API, then stopped that temporary server. Console lint,
TypeScript and Vite build passed; the existing large-chunk warning remains. Widget
SDK and Preact production builds also passed.

Browser smoke checkpoint (existing image, not changed-build acceptance): signed
into the configured Eylo Development org, navigated the widget conversation list,
and sent `QA_RETRIEVAL_SMOKE_20260909` to QA Core Mixed Agent. KB query returned
the release codename with citation K1; memory recall returned the QA color. Both
tool results reported successful Bedrock reranking. The console showed the same
exchange, completed tool calls/results, and the background task result. No
provider settings or source records were changed. The backend schema file hash
differs from this checkout and the container has no source mount, so this result
cannot validate the new Python contracts.

Observed follow-ups, not diagnosed by this smoke check: console Refresh briefly
replaces the transcript with a loading view; background-agent prose claims the
conversation is closed although authoritative conversation status remains Active.
Do not treat generated prose as lifecycle evidence.

Final acceptance must use the completed changed backend build with the existing
configured org: login/navigation, representative provider/tool combinations,
widget exchanges, and matching persisted console tool arguments/results/states.
Retain configured providers; no DB reset or replacement org is needed.

Full F0–F10 and final changed-build widget/admin acceptance remain open.

### F4 progress: Storage API settings and reference-result contracts

2026-09-09: Storage create/update/read/verification schemas now expose the owning
provider enum and reuse domain S3/filesystem settings instead of arbitrary config
objects. Controller serialization retains the existing nested JSON names and
masked-secret response. Provider normalization is shared with domain input;
config normalization now happens at API entry. Provider/settings mismatches are
rejected, while the stored provider remains authoritative for PATCH. Secret patch
maps deliberately preserve omission, null removal and complete replacement rules;
credential variants still validate in the domain before persistence.

Regenerated `web/src/api/generated/schema.d.ts` from the changed-source localhost
API with lifecycle startup disabled, then checked its diff: only Storage schemas
changed. This temporary schema server does not establish product/worker readiness.

- 112 function/HTTP-contract assertions passed through real routes, schemas,
  controller, Storage service and error handler. Member auth and provider-config
  persistence were substituted. Checks include all three credential cases,
  legacy response JSON parity, masking, PATCH/null behavior, wrong-org refusal,
  and listing valid settings when credentials cannot be decrypted.
- 57 reference/deletion assertions passed using the actual SQLAlchemy EXISTS
  expressions against disposable in-memory SQLite tables whose checked column
  types come from the five owner models. Empty result sets now raise rather than
  count as no references. This proves those query/function contracts, not
  PostgreSQL concurrency or a live operator deletion.
- The prior 144 domain/resolution/verification assertions pass unchanged.
  Console lint, TypeScript and Vite build pass; Vite still warns about large
  chunks. No DB migration, provider edit, external vendor mutation or deployment.

Full F0–F10 and changed-build widget/admin QA remain open. This closes the inspected
Storage API settings and reference-result gaps, not all lifecycle/concurrency
claims or broader recording/outbound contracts.

### F4 progress: typed S3 SDK reads and bounded verification cleanup

2026-09-09: completed the inspected SDK client → request → GET body → bounded
download/stream → recording/Knowledge consumer seam. Target evidence is the
installed aioboto3 15.5.0, aiobotocore 2.25.1, Botocore 1.40.59 and Pydantic 2.11.10,
plus AWS GetObject documentation. No dependency upgrade was made.

- `s3_sdk.py` declares only the consumed generated/injected methods and narrows
  client/paginator instances locally without unchecked casts. Native SDK types
  remain inside the storage socket.
- Bucket/object/GET requests validate before serialization. The GET response
  validates the actual SDK body type, excludes it from generic serialization and
  reads only bytes. Both ordinary and checksum SDK bodies were exercised. Full
  reads now close the body explicitly, as streaming already required.
- S3 ranges preserve the extra-byte size probe. Full/stream cancellation and
  checksum failure retain typed errors and close the response/client. Shared size
  validation now rejects invalid filesystem limits before file I/O as S3 does.
- Reproduced verification cancellation after one acknowledged upload with zero
  deletion calls. `CancelledError` bypassed the `Exception` handler. Verification
  now tracks whether the unique probe may exist and performs bounded best-effort
  cleanup in `finally`; the same probe produces one deletion call after the fix.
  Cleanup is capped at five seconds, preserves cancellation, starts no detached
  task and does not misreport an uncertain external upload as definitely removed.

Executed 71 SDK-boundary assertions use the actual generated client, service-model
validation, paginator, presigner, upload helper and ordinary/checksum streaming
bodies. `AioStubber` intercepts AWS calls; no bucket/provider credentials are used.
These include the reproduced body-close failure masking cancellation: primary
read errors/cancellation now survive failing synchronous or asynchronous closure;
a close failure after a successful read becomes `download_cleanup_failed`.
Another 65 assertions cover cleanup success/failure/deadlines, first/repeated
cancellation, unconfirmed deletion, invalid limits and non-callable SDK handles.
The configured default aiohttp SDK transport is covered, not an alternative
HTTPX SDK transport or live S3 service behavior.

The existing 711 storage-error/recording, 144 config, 223 authority, 58 S3
observation, 49 Knowledge storage, 153 corpus/reindex and 149 ingestion assertions
also pass: 1,623 across the affected probes. All 11 typed/import gates, backend
Ruff, formatting and documentation checks pass. The old recording-stream test
double now uses the real SDK `StreamingBody` wrapper; its assertions are retained.

Full F0–F10 remains open. F4 completion still requires its remaining public JSON
and reference/deletion boundaries to be reconciled with the scope ledger, plus
changed-build product acceptance. Broader recording/outbound payloads remain on
the F8/F9 path; their dataclasses are not claimed complete by these stream checks.

### F4 progress: storage failures, capabilities and recording stream projection

2026-09-09: traced S3/filesystem failure producers → normalized exception →
recording outbound retry decision and recording download projection. Storage now
owns `StorageOperation`, `StorageFailure` and `StorageRecovery`; exception inputs
reject arbitrary strings and booleans. Existing diagnostic strings derive from
these enums. Intrinsic capability predicates use a strict frozen Pydantic object.
Shared listing, expiry, stream-chunk and digest-chunk bounds are named constants.

S3 validates consumed native error fields in `s3_wire.py`, using the documented
`Error.Code`/`ResponseMetadata.HTTPStatusCode` shape and the installed Botocore
`ClientError` implementation. Known AWS classification codes remain vendor-owned;
unknown codes are accepted as native strings, not added to a platform enum.
Malformed native errors are terminal typed failures. No provider message/header
content is copied into normalized diagnostics. Valid status/code classification
and the existing missing-object semantics are unchanged.

Both adapter constructors revalidate their Pydantic runtime config. Socket secret
fields are excluded from generic dumps/repr; pipeline translation explicitly wraps
plaintext invocation material in `SecretStr`. The expanded type gate caught three
producer mismatches after the strict config change; the explicit translation
resolves them without casts or weaker types. `RecordingObjectStream` is now a
strict frozen Pydantic local value with nonnegative size and an excluded iterator.
Its producer validates object metadata before exposing size to the HTTP consumer.

Executed 711 function assertions cover old/new error classification parity,
malformed/copy-poisoned payloads, capability types, validation bounds, SDK-client
and response-body closure on normal/early/cancel/error streaming paths, actual
filesystem writes/readback/temporary-file cleanup, recording stream projection,
and the real recording sender's retry-vs-terminal decision. SDK operations,
configuration resolution and durable writes are substituted; filesystem work is
confined to a disposable directory. This is not live AWS or changed-build UI QA.

Regression completion: the 144 Storage config, 223 authority/runtime/recording,
58 S3 observation, 49 Knowledge storage, 153 corpus/reindex and 149 ingestion
assertions also pass: 1,487 across the executed probes. All 11 typed/import gates,
backend Ruff, formatting, documentation and whitespace checks pass. Temporary
function probes remain outside the repository; no test suite or hosted CI was added.

Next Storage work: the dynamically typed SDK client/download payload seam,
stream-byte validation and complete verification cleanup/cancellation. Remaining
platform flows, docs completion and changed-build widget/admin acceptance still
belong to the full F0–F10 goal; clean type gates alone do not satisfy it.

### F4 progress: storage configuration, resolution and verification contracts

2026-09-09: followed create/update → shared provider snapshot → current/pinned
resolution → typed socket config → bounded verification → revision CAS → public
projection. The prior dataclass annotated `provider` as `str` but replaced it with
an enum; four domain/pipeline type diagnostics resulted.

- Replaced Storage config/resolved dataclasses with frozen, strict, revalidated
  Pydantic values. S3 settings, static/session credentials and filesystem settings
  are distinct objects. Existing config/secrets JSON, normalization, credential
  replacement policy and platform-generated namespaces are preserved.
- Private credentials and local adapter handles are excluded from generic dumps
  and representations. Runtime construction revalidates copied material.
- Resolution compares returned organization/config/capability against the request,
  not against the returned identity itself. Pinned resolution verifies revision.
- Verification receipts validate provider identity and intrinsic capability
  predicates before CAS. The provider operation remains outside transactions.
- The full-flow probe exposed strict model validation rejecting read-only
  `MappingProxyType` provider material. The fix copies a checked mapping to a
  dictionary at this boundary; malformed non-mappings remain rejected.
- The local type gate now covers all Storage config modules and pipelines,
  including the explicitly typed controller projection.

Executed evidence: 144 assertions cover pre-change valid-output parity, settings
and credential refusals, copied-model revalidation, safe serialization, service
updates, requested authority/revision checks, verification rejection before CAS,
revision conflicts and transaction depth. The actual filesystem verifier uploads,
downloads, lists and deletes a probe in a disposable directory. DB/service and
S3 calls in this probe are substituted; no operator configuration is changed.
Existing 223 authority/runtime/job/recording assertions pass. Full F0–F10 remains
open, including Storage error/streaming contracts and changed-build browser QA.

Regression completion: 153 corpus/reindex, 49 Knowledge storage, 58 S3 observation
and 149 ingestion assertions also pass, for 776 assertions across this slice and
its affected consumers. All 11 typed/import hooks, backend Ruff, formatting,
documentation verification and whitespace checks pass. S3 transport checks use
substituted SDK responses; they do not prove live AWS access on the changed build.

### F4 progress: pinned storage authority and locator contracts

2026-09-09: traced config resolution → authority → locator → Knowledge job and
voice-recording reconstruction. Reproduced the old dictionary parser accepting
`True` as provider revision `1` and converting a numeric object key to a string.

`StorageAuthority` and `StorageLocator` are now frozen/revalidated Pydantic values.
Location maps remain immutable snapshots with explicit serialization. UUID strings
decode intentionally; revisions and keys no longer use broad numeric/string
coercion. The existing flat persisted representation, normalized provider names,
location fingerprints and URI encoding remain unchanged for valid input.

Historical runtime resolution validates authority before any config resolver
access, then preserves exact organization/config/revision/provider/location checks.
Knowledge row reconstruction and the locator helper keep their existing sanitized
`InvalidStorageLocator` exception boundary. Direct Pydantic construction exposes
sanitized validation errors; helper callers need not depend on Pydantic internals.
The local gate explicitly covers the shared authority module and runtime resolver.

Executed evidence:

- 223 assertions compare valid current output with the pre-change implementation,
  test malformed revisions/keys/UUIDs, immutable snapshots, copied-model refusal
  before resolver access, current/pinned S3 and filesystem resolution, mismatched
  authority refusal before adapter creation, and actual Knowledge/recording ORM
  reconstruction. No live DB, provider, credential or object was changed.
- Existing 153 corpus/reindex, 49 Knowledge storage, 58 S3 and 149 ingestion
  assertions pass: 632 assertions across these suites.
- All 11 typed/import gates and backend Ruff pass.

Broader Storage domain/pipeline checking exposes four existing diagnostics:
`StorageProviderConfig.provider` is annotated as a string but mutated to an enum,
then consumed as an enum by service, verification and runtime config translation.
The next slice must convert the domain config and resolved runtime dataclasses
with explicit settings/credential contracts; merely changing an annotation would
not satisfy the requested end state. Storage error/streaming contracts and the
other F0–F10 flows remain open. Browser acceptance still requires the changed
build and an unlocked Mac.

### F4/F5 progress: corpus, reindex and storage observation contracts

2026-09-09: followed storage listing → corpus screening → child ingestion filing,
plus reindex configuration → checkpoint embedding → staged writes → cutover.

- Moved `StoredObject` into a neutral shared contract, preserving its socket
  re-export. It is now frozen/revalidated Pydantic: keys are strings, byte sizes
  are strict nonnegative integers and optional content digests retain their format.
  Modules do not import sockets to screen an observation.
- Corpus screening returns a typed result instead of tuple/list/dict containers.
  Skip texts, order, null empty summary and the existing 50-entry summary limit
  are unchanged. Malformed observations are refused before child filing. The
  ORM JSON annotation is precise; storage remains the same JSONB column.
- Ingestion and reindex use `KnowledgeJobParams`; corpus uses its separate
  `KnowledgeCorpusParams`. No `job_id`/`import_id` substitution or arbitrary
  `str()` coercion is accepted. Typed full/failure receipts preserve their keys;
  counters reject malformed types. Reindex inspection is Pydantic, retaining
  typed local ORM handles but excluding them from generic dumps.
- S3 list/head responses now validate native consumed fields rather than coercing
  sizes with `int()` or inventing zero for absent sizes. Upload options have a
  typed SDK serialization boundary. Checked AWS ListObjectsV2/HeadObject docs,
  installed Botocore response shapes and S3Transfer upload argument names.
  Unknown unused response fields remain vendor-owned. No new AWS permission.
- Extended the Knowledge gate across all Storage sockets and the shared object
  contract. A pre-existing mixed upload-options dictionary diagnostic is resolved
  by the typed options object. Storage socket checking now reports zero errors.

Executed evidence:

- 153 assertions cover object/screening/receipt contracts, actual temporary
  filesystem upload/list/inspect/delete, corpus duplicate-child handling,
  cancellation during listing, terminal replay, malformed listing rejection,
  post-commit spawning and retained outbox behavior on spawn failure. Reindex
  workflow checks cover fresh embedding, checkpoint replay, terminal work and
  catch-up refusal, with transaction-depth assertions.
- 58 S3 assertions cover consumed SDK shapes, malformed/missing/boolean sizes,
  copied-model revalidation, exact upload arguments, object namespace filtering,
  cancellation propagation and client closure. SDK transport is substituted;
  these are not live AWS tests. An initial copied-listing assertion exposed alias
  fields resetting to their defaults during model revalidation; enabling canonical
  field-name validation preserves the listing and rejects invalid nested copies.
- Existing 149 ingestion lifecycle, 348 embedding-writer and 45 Knowledge DML
  assertions pass: 753 assertions across these suites.
- All 11 typed/import gates and full backend Ruff pass.

No configured provider data, DB schema or deployed image changed. Browser QA is
still pending due to the locked Mac; these tests do not prove the running image.
Full F0–F10 remains open, including remaining storage authority/config/error and
streaming contracts and the other planned vendor/platform flows.

### F5 progress: Knowledge catalog and durable ingestion contracts

2026-09-09: replaced the catalog dataclass with a frozen Pydantic specification
and module-owned `KnowledgeVendor` enum. The persisted vendor strings and unknown
vendor refusal remain unchanged; creation, adapter selection and reindex guards
now reference the same enum. Socket identifiers stay adapter-owned. Removed the
unused required-metadata extension and stale comments suggesting an embedding
model override was supported. The intrinsic embedding-required predicate remains
a strict boolean. Null metadata retains its established defaults; malformed
falsey values no longer silently become an empty configuration.

Added pipeline-owned `ingestion_contracts.py`: UUID-only task inputs, typed
receipts, named failure/event values and bounded timeline payloads. The worker
validates inputs before DB access and no longer converts arbitrary Python objects
to UUIDs through `str()`. Valid UUID/string inputs, terminal receipts and the
smaller failure receipt retain their existing serialized forms. Timeline payloads
carry only KB/document identity and optional failure code. No new persistence,
retry authority, event category, transaction or migration was introduced.

Executed evidence:

- 149 function assertions cover catalog validation, wire compatibility, malformed
  task rejection before DB access, exact timeline keys, retry rethrow, permanent
  failure receipt, terminal replay, checkpoint replay and mismatched document
  refusal. Actual ORM/Pydantic types are used; DB and Absurd/provider effects are
  substituted. Instrumented workflow calls verify ingestion outside transactions
  and product success inside an owned transaction.
- Existing 92 document/tool-authority, 112 query/extraction/storage, 126 adapter,
  36 resolver and 45 DML assertions pass (560 assertions including the new slice).
- All 11 typed/import hooks and full backend Ruff pass.

The Mac remains locked, preventing browser interaction. The running backend
image predates these source changes; no changed-build browser or live-provider
acceptance is claimed. No configured organization/provider data was changed.
F0–F10 remains open; this closes the catalog and single-document ingestion
contract slice, not the remaining corpus/reindex workflows or platform flows.

### F5 progress: Knowledge document and recovery contracts

2026-09-09: reproduced `KnowledgeDocument` accepting arbitrary Python objects in
metadata and permitting content mutation, plus `KnowledgeResult` accepting the
string `NaN` as a numeric score. Both contracts now use frozen, revalidated
Pydantic values, typed JSON metadata and private content representations. Result
scores are strict and finite. Valid JSON/payload shapes and document identity
remain unchanged; arbitrary metadata keys remain supported.

Ingestion services and adapters revalidate copied documents before side effects.
The validated snapshot copies nested metadata before asynchronous work. Operator
ingestion translates invalid document construction to a safe 400 response. Stored
job reconstruction no longer normalizes malformed falsey metadata into an empty
object; it reports a sanitized `IngestionError`. The worker previously omitted
that deterministic error from permanent classification. It now stops invalid
document work instead of retrying it as an infrastructure failure.

`KnowledgeRecovery` replaces the mutable retry-policy boolean. The existing
`retryable` predicate remains read-only for consumers. Provider retry decisions
and embedding-space-change recovery are preserved; the new enum introduces no
retry loop. Capability predicates remain strict intrinsic booleans.

The three Knowledge system tools now use explicit optional platform execution
context, typed context access and JSON return values. Dispatcher tracing confirmed
both `ConversationContext` and `AgentExecutionContext` reach these tools. Only the
former supplies a persisted conversation ID; a background execution ID no longer
stands in for conversation authority. Organization/agent grants remain usable.
Their complete agent-visible schemas
were captured before editing and compare equal afterward; injected context was
and remains hidden. The Knowledge type gate now checks these tools and triggers
on their changes. No tool-selection docstrings were changed.

Executed evidence:

- 92 function assertions cover strict/copy validation, JSON round trips, stable
  document identity, private representations, nested snapshot isolation, named
  recovery and permanent worker classification, actual ORM job reconstruction,
  safe operator rejection and all three tool-schema projections. The final ten
  use actual background context and grant models: conversation-scoped destinations
  and writes are refused, while organization writes enqueue and spawn normally.
- 112 Knowledge query/extraction/storage, 126 storage-adapter and 36 resolver
  assertions pass. The adapter count decreased by one because malformed metadata
  is now rejected before invoking its instrumented embedding callback.
- All 11 typed/import gates and full backend Ruff pass.
- Existing 348 embedding-writer and 45 Knowledge DML assertions also pass.

DB/network effects in these probes are substituted; no changed-build browser or
live-provider acceptance is claimed. Full F0–F10 remains open, including the
Knowledge catalog and durable lifecycle payloads, then other planned flows.

### F5 progress: Knowledge storage adapters and resolver wiring

2026-09-09: extended the Knowledge type gate to include its complete socket
directory, not only domain and pipeline code. Baseline: two parameter-name
override errors. Both adapters accepted `text_query` while the ABC promised
`text`; reproduced a valid keyword invocation raising `TypeError` before lookup.
Both now implement the advertised signature; existing positional callers remain
compatible.

Contract changes:

- Typed session factories, chunkers, document/query embedding callbacks and
  resolver inputs/outputs. No socket imports domain models. The pipeline owns
  the translation from actual Knowledgebase/ingestion-job ORM rows.
- Frozen, revalidated Pydantic Postgres authority replaces an unchecked
  dataclass. Invalid/copied UUIDs, scopes and partition identifiers fail before
  adapter work. Existing namespace filters, live-owner locks and vector-space
  revision checks remain intact.
- Native SQL projections validate document UUID, scope, JSON metadata and finite
  rank/distance before canonical result construction. No arbitrary `str()` or
  `float()` coercion turns malformed row values into valid-looking results.
- Metadata and finite-vector serialization complete before opening the write
  transaction. Replacement remains delete/insert/commit under one owner; embedding
  I/O remains outside it. Typed chunking metadata stays an object until persistence.
- Document deletion checks the actual `CursorResult` before commit. An unknown
  negative count no longer becomes success via `bool(rowcount)`. Zero-row deletion
  still returns false; positive counts return true. Cancellation propagates.

Executed evidence:

- 127 storage-adapter assertions using real SQLAlchemy SQLite rows and DML results,
  plus substituted async session effects: strict/copy authority, row projections,
  malformed scores/metadata, vector refusal, keyword query calls, empty scopes,
  namespace filters, ingestion handoffs, deletion outcomes and cancellation cleanup.
- 36 resolver assertions with actual ORM/Pydantic contracts: all three chunking
  settings, FTS versus vector construction, current versus pinned embedding
  resolution, tenant refusal, incompatible spaces and translated provider failures.
- Existing 112 Knowledge query/extraction/storage and 348 embedding-writer
  assertions pass. Full backend Ruff and all 11 typed/import gates pass; the
  expanded Knowledge gate reports zero diagnostics.

These are source/function checks, not live PostgreSQL search-plan or provider
acceptance. Configured operator data and deployment are unchanged. The full
F0–F10 goal remains open; remaining Knowledge document/error/catalog contracts,
durable lifecycle payloads and changed-build browser QA still require completion.

### F5 progress: native reranking wire contracts

2026-09-09: Bedrock, Cohere and Voyage now validate vendor-local request/response
objects before translating into platform-owned ranked indices. No vendor schema
crosses into the capability domain or Knowledge/Memory consumers. Requests retain
the existing endpoints, authentication, model selection and truncation behavior.

RCA: Bedrock's old response loop filtered out non-dictionary entries. Reproduced
one valid result plus a malformed entry being accepted as a complete top-one
ranking. Typed page validation now rejects the whole response, preserving the
shared stage's degraded fallback rather than presenting a partial success.
Continuation tokens are validated, cycles rejected, excess results refused and
pagination bounded to 1,000 pages. The page bound is platform policy, not a vendor
API limit; the existing outer deadline remains authoritative for elapsed work.

Source evidence: current primary vendor references linked in
[providers](../reference/providers.md#reranking-results-and-recovery), plus installed
Botocore 1.40.59's Bedrock Agent Runtime `2023-07-26` operation schema. Cohere and
Voyage use HTTP; no installed vendor SDK was assumed. Native document echoes,
diagnostic metadata and provider error messages are not retained. Private query,
document and continuation material is serialized only for dispatch.

Executed checks:

- 150 native-wire function assertions: exact HTTP/SDK request parity, installed
  Botocore input validation, malformed/unknown fields, finite scores, private
  serialization, copy revalidation, multi-page/empty-page/cyclic responses,
  page bounds, invalid-request refusal before I/O and client closure.
- Existing 211 reranking result/recovery, 310 config/authority and 112 Knowledge
  query/extraction/storage assertions pass. The shared validator's valid fixture
  now uses canonical result objects; native response validation remains covered
  through the real adapters. Vendor/network effects are substituted.
- All 11 local typed/import gates and full backend Ruff pass.

Console and widget processes still listen on ports 5173/5174. Browser automation
is currently blocked by the Mac lock screen. The running backend image predates
these edits: no changed-build live vendor or browser acceptance is claimed.
No DB, credentials, migrations or deployment changed. Full F0–F10 remains open.

### F7 progress: shared provider-config aggregate and snapshot

`ProviderConfig` and `EffectiveProviderConfig` now use frozen, revalidated Pydantic
models. The foundation owns the finite JSON envelope, strict identifiers,
revisions, predicate flags and timezone-aware verification timestamps; individual
capability modules still own settings meaning and vendor selection. Existing
predicates remain booleans; no new mode or state machine was introduced.

Lifecycle reconstruction validates both the original and changed material.
Credentials remain explicit inputs to encryption, excluded from model dumps and
representations. Outer mappings are read-only; validation copies nested JSON but
does not recursively freeze it. Native JSON arrays remain arrays. The LLM update
service explicitly widens incoming patch data only before its existing domain
validator, rather than treating an unparsed patch as validated stored settings.

Locally verified:

- 76 function assertions: create, rename, update/secret patch, verification,
  disable/delete, stale revisions, current/pinned resolution and refusal paths.
- Real repository formation, ORM models and AES-GCM encryption/readback, including
  mismatched org/revision rejection. Session I/O was substituted; no DB writes.
- Private serialization, nested input isolation, JSON round-trips, strict flags,
  invalid nested values and unsafe-copy revalidation without serialization warnings.
- The existing 363-check voice carrier matrix passes through all 24 providers.
- A dedicated local type gate covers the foundation aggregate and resolution
  service; the five existing type/import gates and backend Ruff also pass.

No operator data, DB schema or deployment changed. Repository-wide and encryption
context typing were completed in the follow-on slice above. Browser navigation was
initially blocked by the Mac lock screen; the later baseline QA above supersedes
that observation but still does not exercise the changed backend image.
Full F0–F10 completion remains open.

### F7 progress: typed stored voice carrier

2026-09-09: `VoiceProviderConfig` no longer uses a dataclass with mutable setting
dictionaries. It retains an STT/TTS inference model or module-owned realtime
settings object. The latter separates transport region from model inference;
vendor wire types still belong to sockets. Plaintext secrets use an immutable
mapping excluded from repr/dumps. Copied settings are revalidated before any
serialization, so invalid copied values fail without serializer warnings exposing
their contents.

`from_storage()` owns stored-shape validation and normalization. The old factory
name `validate()` conflicted with Pydantic's inherited signature; the type gate
caught that mismatch, and every first-party caller was renamed rather than adding
a suppression. Runtime resolution keeps typed settings. Create/update serialize
only at `to_storage_config()`, preserving existing JSON keys and explicit values.
An update now persists the validated normalized projection when settings change;
a name-only update does not rewrite settings. No migration or operator-data write
was performed for this change.

Executed verification:

- **363 function assertions**, covering all 10 STT, 11 TTS and 3 realtime providers:
  stored round-trip parity, immutable settings/secrets, independent serialization,
  secret-free dumps, kind agreement, invalid numeric/key/secret inputs, copied
  model rejection, exact CRUD service handoffs and runtime resolution. Private
  credentials must be supplied separately when restoring a JSON snapshot; all
  24 setting variants pass that round-trip. Snapshot serialization omits unset
  cross-provider fields instead of introducing unsupported explicit nulls.
- **24 native capability projections** through the actual inspection function;
  config retrieval is substituted, not adapter construction or serialization.
- Existing **1,245 speech-material assertions**, **21 native constructors**, and
  **142 shared STT data-flow assertions** pass with the renamed storage entrypoint.
- The realtime fixtures were corrected to meet the existing domain contract
  (required Nova settings, OpenAI transcription model, no OpenAI temperature).
  These fixture mistakes were not changes to provider policy.

These checks execute functions with controlled persistence/provider boundaries.
They do not prove encrypted DB round-trip or live browser/provider acceptance of
the current source. General provider-config foundation typing and the full F0–F10
goal remain open.

### F7 progress: ElevenLabs TTS native boundary and failure propagation

Completed the connected flow: resolved TTS material → existing factory → immutable
native input/options → typed initialization/text/end-input JSON → validated audio
and final frames → real TTS queues → consumer bytes, recording tap and correlated
speech outcome. Vendor wire types and stream state remain in the socket; platform
policy, org/config lookup and events remain outside it. No SDK dependency added:
verification used installed `websockets` 15.0.1 and Pydantic 2.11.10.

Reproduced and fixed:

- Final frames dropped their audio; truthy strings could complete a turn and
  malformed base64 could become empty audio. Known fields now validate before
  effects; vendor extension fields remain unconsumed.
- Failed initialization left an acquired socket open. Setup/send cancellation,
  failures, final output and interruption now retain explicit cleanup ownership.
- A closed/interrupted single-context stream could not serve the next turn.
  The adapter now finishes native input explicitly and lazily opens the next
  stream with the same configured provider material. Late old frames are ignored.
- The first pending change used a space plus `flush`; source review did not
  establish that buffer flush guarantees a terminal response. That assumption was
  removed. Empty-text end-input follows the vendor's documented stream lifecycle;
  native cross-turn context continuity is consequently not advertised.
- A malformed frame caused the TTS supervisor to repeatedly restart its failed
  reader while playback remained pending. Read/send/keepalive/client failures now
  stop the runtime, emit one correlated failed outcome and propagate to its owner.
  Runtime cancellation also propagates after cleanup; speech is not replayed.
- Shared teardown skipped already-failed tasks, producing uncollected exceptions.
  It now accepts a typed task mapping, cancels children together, collects finished
  failures, skips its caller and preserves caller cancellation.

Sources: [ElevenLabs stream lifecycle](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tts),
[native request implementation](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/realtime_tts.py),
[websockets 15.0.1 receive/close](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/client.html),
and [Python 3.13 task ownership](https://docs.python.org/3.13/library/asyncio-task.html).

Function verification: **167 native/pipeline checks**, **24 real local WebSocket
checks**, **21 running-supervisor failure/cancellation checks**, and **10 shared
teardown checks**. The local listener used an ephemeral loopback port, dummy
credentials and the real `ClientConnection`; it was closed after verification.
Read/send/keepalive failures were also injected into the running queue path,
not only checked through a completion helper. No live vendor, TLS, microphone,
operator UI or DB behavior is claimed. Human voice QA remains required.

Regression checks: **1,245 speech-material checks**, **21 real adapter
constructors**, and **380 verification/capability/carrier checks** pass. The first
pipeline fixture used nested factory credentials; production supplies the shared
builder's serialized shape. The corrected probe uses that builder. The generic
factory's inconsistent nested-options contract remains part of its unfinished
typing work; production validation was not weakened to accept the fixture.

Local parsing/translation measurement: median of five 10,000-frame runs with
960-byte PCM, including fixture JSON generation, was about **9.46 µs/frame**
afterward versus **9.65 µs/frame** before. This does not establish live throughput
or provider latency. Per-turn handshakes are an explicit cost of this supported
single-context path; multi-context synthesis is not implemented here.

Milestone review order: DDD ownership → architecture fit → source-to-sink data
flow and cleanup → plan/Pydantic alignment → readability, security and cost.
The review found the supervisor failure-propagation gap; the real queue probe
reproduced it before correction. No runtime schema suppression or unchecked cast
was added. Voice pre-commit coverage now includes the native adapter/wire/base.

Final gates: all five scoped type/import hooks pass; the existing LLM hook still
reports its one pre-existing suppression. Full server/CLI Ruff, affected-file
format checks, `git diff --check`, documentation verification (46 pages,
282 links, 1,150 Python modules, 6,102 docstrings, 47 diagrams), and app/OpenAPI
generation (564 schemas) pass. Whole-project Pyrefly remains **849 errors and
7 suppressions**; it is not a green platform-wide gate. The TTS manager still has
12 diagnostics and the shared monitor has one error/three suppressions.

Still open: generic STT/TTS factory options, TTS queue payloads and supervisor
types, shared monitor/restart-condition contracts, the remaining provider native
flows and F0–F10 requirements. This milestone does not complete the platform goal.
No migration, deployment, operator-data mutation, dependency upgrade, commit,
history rewrite or permanent test/probe was introduced.

### F7 progress: shared voice-task supervision contracts

The preceding question-only exchange confirmed the Pydantic execution-context
choice without implementation progress. This continuation revalidated the live
worktree and advanced the pending supervisor boundary; the full F0–F10 objective
remains unchanged.

`runtime/tasks.py` now accepts bound zero-argument coroutine factories and
`Task[None]` registries. Restart/ignore policies accept immutable collections
without type suppressions. The separate arbitrary argument dictionaries are
removed; their only caller was WebSocket scaffolding whose six dictionaries were
always empty. Actual task ownership remains in the STT/TTS factory/managers.
All three remaining monitor call sites use the precise factory/task contracts.
The STT debounce timer also retains its real `Task[None] | None` type.

Queue draining uses a behavioral protocol containing only `join()` and `qsize()`.
It can wait for heterogeneous queues without erasing or inspecting their payload
types. The existing per-queue timeout now has a named seconds constant; drain
does not consume, discard or acknowledge work on the producer's behalf. These
are executable resource ports, not data records requiring a Pydantic model.

Reproduced and fixed with actual asyncio tasks:

- A false restart predicate still restarted the failed task: the old loop never
  assigned false to its accumulator. Predicate failures also left restart enabled.
  Each supplied predicate must now permit restart; false or an exception vetoes it.
- A cancelled child raised `CancelledError` out of the monitor because
  `.exception()` ran before `.cancelled()`. Cancelled children now retain their
  identity without cancelling the supervisor or being restarted.
- Full STT caller QA found `_run()` swallowing its own cancellation, so
  `initialize()` completed successfully after its owner cancelled it. Cancellation
  now propagates after the existing cleanup. Debounce timer reset semantics are
  unchanged, and no audio replay or retry category was added.

Target: installed Python **3.13.2**. The distinction between task cancellation and
inspection follows [Python task results](https://docs.python.org/3.13/library/asyncio-task.html#asyncio.Task.exception);
draining follows [queue acknowledgements](https://docs.python.org/3.13/library/asyncio-queue.html#asyncio.Queue.join).

Function verification: **254 monitor/drain checks**, **15 real STT
factory/manager caller checks**, the existing **21 running TTS failure/cancellation
checks**, **10 teardown checks**, and **167 ElevenLabs native/pipeline checks**.
Coverage includes restart/ignore precedence, exception subclasses, veto/error
predicates, cancelled/pending/successful/missing-definition children, replacement
identity, eager task creation, parent cancellation, queue timeout/nonconsumption,
and safe error logging. The STT probe executes actual factory/manager functions,
normalized events, consumer queues and task monitoring with a controlled adapter
port; it is not live vendor, DB, microphone or UI QA.

Milestone review, sequentially: (1) shared runtime ports import only standard
library types; vendor errors remain caller-owned, (2) no new execution lane or
resource owner, (3) real registry replacement, consumer output and cancellation
were checked together, (4) this completes the supervisor slice, not the generic
speech payload/native-provider backlog, (5) simpler branching removes dead
scaffolding and suppressions without new I/O or per-audio-frame work. Factory
registration/cleanup and native response contracts still need their F7 work;
clean scoped type checks do not prove those broad areas are hardened.

Gates: all five scoped type/import hooks pass, with the pre-existing single LLM
hook suppression. The voice hook now includes the shared monitor, STT factory
and STT runtime. Full Python Ruff, affected-file formatting, `git diff --check`,
documentation validation (46 pages, 282 links, 1,150 modules, 6,105 docstrings,
47 diagrams), and app/OpenAPI generation (564 schemas) pass. Whole-project
Pyrefly is **846 errors / 4 suppressed**, down from **849 / 7**. TTS manager's
12 diagnostics and the WebSocket input-union mismatch remain open.

Next: TTS request producers → session routing → typed queue items → supervisor
and consumer/recording; then generic factory options and remaining native speech
request/response flows. No operator data, migration, deployment, dependency,
commit, history or permanent test/probe changes.

### F7 progress: typed speech payloads through routing and playback

The question-only turn verified that execution-context models already use
Pydantic; it did not change the implementation. This continuation finished the
in-progress speech input boundary while retaining the full F0–F10 scope.

- `pipelines/voice/tts_payloads.py` owns immutable text/finalize models and their
  discriminated union, request UUID, opaque turn label, and policy source enum.
  Policy speech requires a request identity. Finalize cannot carry text.
- Redis serialization uses `ConversationTTSRequest`; the listener accepts JSON
  text/bytes, validates before session lookup, and rejects malformed frames
  individually. Subsequent valid frames continue through the same listener.
- Session routing uses resource protocols with actual request-state results and
  collection semantics. The real TTS method's parameter name now agrees with the
  queue protocol. Both org and conversation remain part of routing authority.
- LLM, filler, policy, disclosure and carrier-opener producers construct those
  same objects. Filler uses the actual session/TTS interfaces instead of probing
  a removed private turn field; its task registry retains `Task[None]`.
- TTS requests, audio responses and consumer queues retain their payload types.
  Active/queued correlation uses owned objects, not independent dictionary keys.
  Metrics use the existing `TTSMetricsSnapshot`; snapshot mutation cannot alter
  runtime counters, and delivered-response count is now incremented.

Reproduced fixes:

1. Turn replacement called the full user-interruption path, which discarded the
   new response's already-queued finalize marker. Replacement now interrupts only
   current synthesis/output; explicit user interruption still clears pending input.
2. Non-streamed assistant messages supplied text without finalization. They now
   use the complete `VoiceTextSegment` path, retaining message/request identity.
3. Invalid text could enter the queue. Input is now revalidated before admission;
   a queue-full drop no longer changes the accepted queued request's identity.
4. A union-level `TypeAdapter` error included invalid input despite model-level
   hidden-input config. The outer adapter now hides inputs in its error string too.

Executed function checks: **67 payload/routing/queue assertions**, **23 producer
assertions**, **167 existing ElevenLabs native/pipeline assertions**, and **21
existing manager failure/cancellation assertions**. The routing probe uses the
real Redis serializer/listener, session lookup, `WSSessionState`, request states,
live buffer, native adapter, consumer queue and recording callback. Redis/network
ports are controlled, not live services. Producer checks include persisted-message
schema construction, partial/complete ordering, ignored user messages, filler,
single policy capture, notification state, and the real opener observer with its
DB effect replaced. No microphone, browser, carrier, live vendor or operator DB QA.

Sequential milestone review: (1) speech routing types stay in pipelines and native
types stay in sockets, (2) no new runtime/event authority or provider default,
(3) validation/correlation/capture/audio/terminal outcomes are checked together,
(4) this advances F7 without declaring all native provider flows complete,
(5) no new dependency, I/O, cast or suppression; old string/dict queue compatibility
and private-field fallback are removed. No public endpoint schema change.

Scoped type checking and all five local type/import hooks pass; the voice hook
now includes payloads, routing, TTS manager and filler. Full Ruff, affected-file
formatting and diff checks pass. Documentation validation reports 46 pages,
283 links, 1,151 modules, 6,117 docstrings and 47 diagrams; app/OpenAPI generation
passes with 564 schemas. Whole-project Pyrefly: **827 errors / 4 suppressed**,
previously **846 / 4**.
The two remaining `websocket/manager.py` diagnostics belong to contact-event JSON
decoding and the disconnect return contract, not the now-checked speech route.

Next: native TTS factory/options and remaining STT/TTS request/response branches,
including concurrent interruption/send/receive and cancellation ownership; then
the existing F2/F3–F10 backlog. Queue admission still uses its existing drop policy;
caller-visible admission receipts and complete backpressure/lifecycle semantics
are not proven by these checks. Filler config and live carrier session payloads
also remain in that flow. No migration, DB mutation, deployment, dependency upgrade,
commit, history change or permanent probe file.

### F7 progress: Cartesia native contracts and shared TTS factory interface

The preceding question-only turn verified the existing Pydantic execution-context
correction; it made no implementation progress. This slice continues the full
F0–F10 scope through factory → native Cartesia → TTS queue → audio/outcome sinks.
No dataclass substitution or cross-owner wire union was introduced.

Baseline reproduction with the actual Cartesia adapter and controlled transport:

- Eylo finalization sent a vendor flush without ending the native context.
- Interruption sent final input rather than native cancellation.
- Old-context audio reached the caller after replacement speech started.
- Old-context completion incorrectly completed the replacement turn.

RCA: dictionary payloads hid the distinction between platform finalization and
vendor flushing; the receiver did not validate the context that owned an output.
The capability/config trace also found that exposed speed was never sent.

Implemented:

1. `sockets/tts/adapters/cartesia_wire.py`: frozen native input/options/media,
   generation/cancel requests, response variants, and owned state/kind enums.
   Unknown fields on outbound config are refused; unused inbound extensions are
   discarded. Consumed booleans, finite speed, sample rate, context and base64
   are checked. Native diagnostics never include speech or credentials.
2. `cartesia_contract_adapter.py`: explicit end-of-input; native cancel; fresh
   context per utterance; stale audio/error/done filtering before payload effects.
   Generation settings remain fixed within a context. Speed now reaches
   `generation_config.speed`. This does not guarantee support on every model:
   Cartesia documents Sonic 3.5 speed control as unavailable. No new model default
   or fallback was introduced.
3. Typed native `ClientConnection`, serialized input/lifecycle operations,
   cancellation-safe polling, uncertain-send retirement, detached bounded close
   tasks and safe terminal errors. No await occurs between consuming a frame and
   its identity check/projection, avoiding loss while waiting for a send lock.
4. `sockets/tts/factory.py`: reuse `TTSProvider` instead of a duplicate literal
   union; yield the shared `TTSVendorAdapter` rather than a native handle.
   Invalid vendor types fail before string normalization. The existing serialized
   options carrier and wider factory startup-cleanup semantics remain open.
5. The voice pre-commit/pre-push type gate now includes the factory and both
   Cartesia native modules. The provider architecture reference follows the flow.

Executed function/data-flow QA:

- **202** Cartesia contract/lifecycle/queue assertions: valid/invalid settings,
  strict wire controls, all consumed output variants, unknown extensions, stale
  frames, repeated turns, EOF, send errors/cancellation, receive timeouts, close
  cancellation, and actual `TTSRealtime` playback/recording/failed-outcome sinks.
- **13** native WebSocket loopback assertions: actual installed client/server,
  header credentials, unchanged API version, cancellation, stale frames, repeated
  speech and cleanup on a single socket. The initial sandbox bind denial was an
  environment limit; the same localhost-only probe passed with approved access.
- **69** shared factory assertions across all 11 TTS branches: canonical adapter
  return, normal/error cleanup and bounded retry; native connection operations
  substituted. This caught and corrected the numeric-vendor `AttributeError`.
- **1,245** resolved-material and **380** verification/capability/carrier caller
  assertions, including all 21 actual STT/TTS constructors.
- Existing adjacent probes: **167** ElevenLabs native, **67** speech routing/queue,
  **23** producer and **21** manager-failure assertions passed.

These are function-contract and controlled dependency-path checks, not live
Cartesia QA or human acceptance of voice UX. No operator credentials, DB writes,
UI changes, migration, dependency upgrade, deployment, commit or permanent probe.

Milestone review, performed sequentially:

1. DDD ownership: Cartesia vocabulary stays in its socket; platform request and
   conversation identity remain pipeline-owned. No module/socket import crossing.
2. Architecture fit: existing explicit factory and canonical adapter port retained;
   no new queue, retry authority, generic schema framework or provider default.
3. Data flow: resolved model/voice/media/speed → typed wire → matching-context
   bytes → consumer/recording; malformed/error output → failed speech outcome.
4. Plan alignment: advances F7 and Pydantic-first internal contracts; remaining
   vendors, factory options, F2/F3–F10 and global concurrent playback correlation
   are not waived by this slice.
5. Readability/security/performance: native choices are explicit; raw payloads
   do not leak through errors; native receive buffers/timeouts remain bounded.
   Local valid-frame processing measured **5.68 µs median** over five batches of
   10,000 frames with 960-byte decoded PCM. This excludes network/audio latency.

Five scoped type/import hooks and full Ruff pass. Whole-project Pyrefly:
**825 errors / 4 suppressed**, previously **827 / 4**. Public schema unchanged.

Version evidence: Pydantic **2.11.10**, websockets **15.0.1**; Cartesia API version
remains **2025-04-16**. References: [context finalization/cancellation](https://docs.cartesia.ai/use-the-api/tts-websocket/contexts),
[nonterminal flushing](https://docs.cartesia.ai/use-the-api/tts-websocket/context-flushing-and-flush-i-ds),
[versioned ID-voice wire reference](https://docs.cartesia.ai/2024-06-10/api-reference/tts/websocket),
[generation controls](https://docs.cartesia.ai/build-with-cartesia/capability-guides/volume-speed-emotion),
and [native transport/cancellation contract](https://websockets.readthedocs.io/en/15.0/reference/asyncio/client.html).
The current default Cartesia reference has a newer voice shape; this slice did
not silently upgrade the pinned request protocol. Live acceptance remains unrun.

Next: complete native config/options and remaining TTS/STT adapters in data-flow
order; preserve shared factory/caller gates. Broader interruption/send/receive
correlation, queue admission/backpressure and factory startup cancellation still
need their own connected-path verification. Then continue the full F2/F3–F10 plan.

### F7 progress: deterministic TTS config projection and native config models

Continued the full F0–F10 objective after confirming the execution-context
Pydantic correction remains in the worktree. This is construction-path hardening,
not completion of native speech protocols or platform-wide typing.

Confirmed baseline with actual factories and constructors, without network I/O:

- Cartesia selected a stale nested API key over the factory's explicit replacement.
- OpenAI silently discarded nested `speed` and used its default.
- OpenAI accepted `speed=True` as a native config value.

RCA: normalized config, nested options and a second flattened dictionary were
competing authorities. Seven constructors accepted unvalidated `**kwargs`; their
annotations neither rejected bad values nor protected against misspelled options.

Implemented:

1. Normalize nested/flat values once. Reject conflicting duplicates and nested
   provider/retry fields. Apply explicit API-key replacement to the resulting
   credential. Revalidate copied config/retry objects before serialization; do
   not emit Pydantic serializer warnings containing invalid input values.
2. Preserve explicit nested media settings over implicit defaults, but reject
   conflicts with explicitly supplied media fields. Pin vendor identity to the
   existing socket enum; reject malformed provider identifiers and non-object
   config values. Runtime config errors have a named safe exception.
3. Replace OpenAI, Deepgram, Groq, Rime, Smallest, Hume and Murf config containers
   with adapter-owned frozen Pydantic models. `TTSAdapterConfig` shares only
   native validation/projection mechanics, not vendor fields or factory selection.
   Unknown native options fail; private API keys are excluded from repr/dumps.
4. Replace constructor `getattr` field guessing with explicit typed accesses.
   Voice/speaker aliases derive from one stored value. Hume/Smallest policy flags
   use `SpeechOptionState`, projected to JSON booleans only at native send.
5. Pass the typed normalized config from `TTSRealtime` to its factory. Remove the
   runner's redundant config dictionary. Mapping ingress/egress types use `object`
   at the validation boundary instead of factory `Any`; open carrier fields are
   still pending and are not treated as complete native schemas.
6. Add shared config/schema/error files to the existing local voice type hook.
   No hosted CI, DB/schema changes, dependency upgrades or deployment changes.

Function QA:

- **495 checks:** seven native config models; valid/invalid fields, unknown keys,
  revalidation after unchecked copies, safe errors, private output, enum policies,
  flat/nested parity, conflicting keys, explicit credential replacement, media
  aliases, optional fields, and immutable native snapshots. Actual send methods
  were exercised with controlled HTTP/WebSocket transports and close assertions.
- Existing constructor/hydration probes: **1,245 checks / 21 STT+TTS constructors**.
  Verification/capability caller probes: **380 checks**. All **11** TTS factory
  branches passed **69** construction/connection/cleanup assertions with native
  connection methods substituted.
- Cartesia **202** and ElevenLabs **167** native/queue regression checks passed.
  Shared voice-routing **67**, producer **23**, and failed-runtime **21** checks
  passed again after the final runner change.
- Shared changed config/factory types and all five local type/import hooks pass.
  Whole-project Pyrefly remains **825 errors / 4 suppressed**; the seven native
  adapter files still contain **16** broader stream/payload/lifecycle diagnostics.
  This is not a clean platform or full-native-adapter typecheck.
- Full server/CLI Ruff and documentation verification passed. Documentation
  verifier: 46 pages, 283 links, 1,153 Python modules, 6,139 docstrings, 47 diagrams.
  App import/OpenAPI generation passed: **245 paths / 564 schemas**, with dummy
  local settings and no operator DB or external-provider calls.

Milestone review, in repository order:

1. DDD: platform settings and credential resolution remain outside sockets;
   vendor fields remain in each adapter. No module/socket cross-import added.
2. Architecture: explicit factory branches retained. No reflection-based vendor
   discovery, alternate scheduler, fallback vendor/model or credential source.
3. Data flow: construction → native send → controlled transport/queue and close
   were exercised. Shared-type tightening exposed a dictionary-based provider
   lookup in the voice runner; it now reads the typed enum directly.
4. Plan: advances F7 and the Pydantic-first requirement without closing F2/F3–F10.
   No live vendor, operator DB, human voice/widget or provider-auth QA was run.
5. Readability/security/performance: removed permissive constructors and duplicated
   voice aliases; validation runs at construction, not per audio frame. No new I/O,
   retry behavior, background work or type suppression was added.

Next: complete the open carrier and Polly/Sarvam options, then native request,
response and lifecycle contracts for the remaining TTS/STT adapters. The Hume
compatibility concern raised in this slice was investigated in the following
increment; browser media ownership remains a required downstream correction.
Factory startup cancellation, broader turn correlation and all remaining F0–F10
requirements remain active. Private native models do not prove that every generic
carrier/snapshot is secret-safe.

### F7 progress: Hume native wire and turn contracts

Sources checked on 2026-09-08: Hume's streaming quickstart/reference and Python
SDK commit `84e24b3be3e8e53df94bf23c28d9191aaa1217c0`; installed Pydantic
2.11.10 and websockets 15.0.1. No dependency update or SDK installation.

Confirmed RCA:

1. The adapter sent an HTTP-shaped utterance-list body to a WebSocket expecting
   top-level `PublishTts` fields. It omitted native version/format query options.
2. `flush()` was a no-op. Native `close` forces remaining synthesis and ends the
   stream; a snippet-level `is_last_chunk` is not whole-turn completion.
3. The receiver silently ignored binary/invalid JSON, dropped audio when its
   queue filled, and could swallow send failures or leave failed tasks unseen.
   Interruption emptied only the local queue, not the still-producing stream.
4. The adapter reported configured 24 kHz rather than native fixed 48 kHz.
   The baseline probe exercised the actual sender/finalizer and format property
   without network calls. Vendor rejection was not reproduced with credentials.

Implemented:

- Frozen Pydantic text/voice/end-input and consumed audio/timestamp models; owned
  version, response-kind and lifecycle enums. Strict base64/PCM alignment and
  completion fields; safe named errors, without vendor error bodies.
- Explicit configured-model-to-version mapping; PCM and JSON-only negotiation;
  header authentication, speed and description forwarding. Unknown models,
  invalid voice-design/instant-mode combinations and non-PCM requests fail early.
- One native socket per turn. End-input drains before normal closure is treated
  as completion; incomplete snippets, abnormal/early close and empty output fail.
  No background audio receiver/queue. Socket backpressure replaces dropped chunks.
- Interruption detaches before close; late old-stream output cannot affect a new
  stream. Poll cancellation is harmless; failed/cancelled sends retire the stream.
  Close tasks remain owned through caller cancellation, with bounded native close.
  Pending snippet tracking has a named bound and rejects rather than truncates.
- Actual output and capability sample rates are 48 kHz. No operator data, config
  records, migrations, deployment, credentials or external vendor state changed.
- Hume adapter/wire files added to the local voice type hook. No suppressions.

Executed checks:

- **240 native function assertions:** config, wire fields, privacy, failures,
  multi-snippet completion, repeated turns, stale output, polling/send/close
  cancellation, concurrent acquisition, bounded tracking and real factory branch.
- **18 pipeline assertions:** real resolved material → runtime config → factory
  → native adapter → task/queue manager → PCM consumer/recording callbacks and
  drained outcomes, across three turns. Only the external WebSocket was replaced.
- **9 real WebSocket loopback assertions:** actual client/server handshake,
  header/query placement, PCM output, three turns and native close behavior.
  The temporary localhost listener closed afterward; this is not live Hume QA.
- **495** seven-config checks, **1,245** material/constructor checks across 21
  speech adapters, **380** verification/capability caller checks, and **69**
  all-vendor TTS factory checks pass. Hume probe inputs now use a documented model
  and permitted voice-design mode, rather than the old synthetic `octave` value.
- Both Hume files and all five local type/import hooks pass. Whole-project
  Pyrefly: **822 errors / 4 suppressed**, down from 825; platform completion is
  still unproven. Full server/CLI Ruff and app import/OpenAPI generation pass
  (**245 paths / 564 schemas**). No generated public client changes needed.
- Native validation plus base64 decoding: **6.202 microseconds median/frame**
  over five runs of 10,000 synthetic 1,920-byte PCM frames in the local interpreter.
  This excludes network, synthesis, rendering and end-to-end latency.
- The first pipeline probe incorrectly treated recording bytes as chunk objects;
  its metadata assertion now observes the actual chunk constructor. A subsequent
  fixture byte-escape typo was corrected. Neither required product-code changes.

Sequential milestone review:

1. **DDD boundaries:** native wire, version mapping and resource ownership stay in
   the Hume adapter. No module/socket import or framework dependency added.
2. **Architecture:** the explicit factory and TTS port remain authoritative.
   No alternate queue, default voice/model or replay after an uncertain send.
3. **Data flow:** native and queue paths pass, but source-to-browser tracing found
   an unresolved consumer mismatch. `_get_browser_tts_audio_metadata` returns
   16 kHz for Hume, while the adapter returns 48 kHz. Browser `OutgoingAudioTrack`
   writes raw queue bytes into a fixed 16 kHz buffer. The recorder mismatch was
   reproduced through the real helper and factory; browser playback is source
   evidence, not a performed microphone/browser test. Telephony instead constructs
   its transcoder from `tts.output_audio_format`.
4. **Plan alignment:** Pydantic-first and vendor-owned wire contracts advance F7.
   This is not completion of Hume onboarding, browser voice, or F0–F10.
5. **Readability/security/performance:** removed guessed dictionary responses,
   the error counter and lossy detached receiver. No plaintext key in URL/errors;
   output metadata is explicit. Bounded backpressure/cleanup; no new dependency.

Next required work, before claiming browser voice support:

1. **Implemented below:** give browser playback/recording a typed actual-audio-format contract from the
   adapter, with explicit conversion to transport format. Remove vendor/default
   guessing and verify native output → conversion → playback and recording.
2. Reconcile Hume onboarding: no native language/rate selector; distinguish custom
   versus Hume library voices; reflect version and instant-mode constraints in
   configuration UX without inventing a default voice or silently changing data.
3. Finish remaining native speech adapters, generic carrier and lifecycle/correlation
   contracts, then the rest of the unchanged platform-wide plan. Human voice QA
   and live Hume verification remain pending; no positive browser-release verdict.

### F7 progress: canonical STT events and transcript queue ownership

The complete F0–F10 goal remains active. This slice follows provider-adapter
output through the factory, runtime queue, debounce, live transcript buffer and
voice-policy callbacks. It does not complete native provider wire/config typing.

Confirmed RCA and impact:

- Repeated dictionary translators inferred finality differently and collapsed
  speech/activity/error events into transcript fallbacks. A flattened metadata
  projection could overwrite canonical fields instead of preserving their owner.
- Full queues discarded events upstream of the transcript consumer. Clearing a
  debounce buffer before downstream acceptance could also lose final text.
- The shared task monitor restarts explicitly eligible failures but does not
  propagate every terminal child failure. Neither STT owner observed those
  stopped children, allowing a failed receiver to leave a seemingly live runtime.

Implemented:

1. `STTEvent`, `TimedWord`, `RecognitionUsage` and `STTError` are Pydantic models.
   Provider identity is an enum; finality derives from the event kind. Missing
   confidence/usage remains distinct from zero. Connection acknowledgements do
   not become speech. Vendor metadata cannot replace control fields.
2. The nine dictionary-based adapters validate an explicit intermediate envelope;
   Amazon projects its real SDK result directly. Native word/entity dictionaries
   retained in extension metadata are not claimed as fully typed vendor schemas.
3. `VoiceTranscriptInput` distinguishes recognition, completed DTMF and final
   batches. DTMF completion is an enum; sequence reuse checks the actual live
   buffer's kind, digits and sequence. STT metadata cannot grant that authority.
4. Both queues await downstream acceptance. Debounce retains each complete event,
   clears only after acceptance, and exposes timer failures. Acquired input is
   acknowledged by its processing owner. This is live backpressure, not durable
   delivery across process death.
5. Factory/runtime owners observe terminal children after permitted restarts.
   Connection loops retain the adapter they opened. Startup failure/cancellation
   closes partially acquired resources; teardown joins owned tasks even when
   provider close fails. Bounded final delivery still closes the provider and
   retains an unaccepted batch in memory.

Executed function checks (controlled I/O, no vendor calls or DB writes):

- `STT-TYPED-FLOW-QA-OK`: **449 checks**, all ten real constructors, nine actual
  adapter receive paths, the Amazon SDK result, normalization, invalid inputs,
  metadata, queue backpressure, debounce, live-buffer/DTMF correlation,
  interruption, end-call dispatch and cancellation acknowledgement.
- `STT-LIFECYCLE-QA-OK`: **37 checks** through the actual factory and runtime
  supervisors. Covers full queues, receiver/forwarder/timer failure, normal
  child termination, audio forwarding, cancellation, close failure and partial
  startup cleanup.
- Repeated call-session **88**, carrier audio **64**, browser audio **118** and
  resolved speech-material **1,245** checks pass. Native constructor coverage
  includes ten STT and eleven TTS adapters; it does not establish live operation.
- Full backend Ruff passes. Whole-platform Pyrefly: **790 errors, 4 suppressed**,
  compared with the preceding **810** baseline. Remaining errors are still work;
  an STT-scoped green gate is not platform-wide completion.

Milestone review, in order:

1. **DDD boundaries:** no module/pipeline imports from the STT socket. Vendor
   translation stays in adapters; DTMF authority and voice policy stay in pipelines.
2. **Architecture fit:** existing factory, runtime and transcript owners remain;
   there is no new event store, duplicate execution authority or second UI state.
3. **Data flow:** exact event meanings, optional metadata and final segments
   survive the reviewed path; failure/cancellation is observed by the owner.
4. **Plan alignment:** native provider schemas, generic config and remaining
   platform flows are explicitly unfinished. Public spellings are not rewritten.
5. **Clean code/security/performance:** canonical control fields are separate
   from vendor metadata, typed queues expose mismatches, logs use event kinds and
   lengths, and bounded queues apply backpressure. No new DB transactions,
   external effects, dependencies or persistent probes were introduced.

The following native slices replace the intermediate envelope for AssemblyAI,
Cartesia and Speechmatics. Other adapters still require native-contract
work. Live provider/browser QA remains pending; controlled probes are not a
release verdict.

### F7 progress: native AssemblyAI and Cartesia STT contracts

The full F0–F10 objective remains active. This slice follows configured material
through native wire I/O, canonical events, queue ownership and transcript consumers.
It does not upgrade dependencies, reset operator data or deploy services.

Confirmed findings and fixes:

- AssemblyAI connection acknowledgement previously became speech activity, final
  formatting could produce duplicate turns, and transcript confidence was invented.
  Native Begin/Turn/SpeechStarted/Termination/Error models now keep these meanings
  separate. Connection readiness waits for Begin; configured-model echo must agree.
  Formatting-enabled turns become final only at the formatted result. Native word
  confidence and endpoint confidence remain distinct from absent transcript confidence.
- AssemblyAI request/config models preserve configured keyterms as a JSON array,
  including commas inside a phrase. PCM buffer duration uses actual sample counts.
  ForceEndpoint flushes buffered input. Close retains native final frames and joins
  children; immediate cancellation before worker startup now wakes iteration, and
  repeated reads after EOF remain terminal. A reproduced union-validation error
  exposed malformed transcript content; the TypeAdapter now hides input in errors.
- Cartesia's adapter discarded errors, invented confidence and made flush a no-op.
  Native transcript/flush/done/error models now feed the canonical event directly.
  The typed command enum distinguishes nonterminal `finalize` from terminal `close`.
  Both send buffered PCM first. Finalize leaves the connection usable for another
  turn; close waits within a bound for native final output and acknowledgement.
- Cartesia no longer has an unbounded detached audio-input queue or a second
  adapter response queue. Writes await socket acceptance; one native reader has a
  bounded output queue. Borrowed HTTP sessions remain caller-owned. Credentials
  use the documented header, and query values are URL-encoded without changing
  the pinned `2026-03-01` API version or choosing a new/default model.
- Cartesia final chunks are deltas, not independent sentences. The socket-owned
  `STTTranscriptForm` enum carries that distinction; `FinalTranscriptBatch` joins
  same-provider/same-session deltas exactly, without inserting spaces or stripping
  their edges. Independent segments keep their existing separator behavior.
  Vendor request IDs identify the connection and are not chunk deduplication keys.
- An actual factory probe reproduced loss of an immediate vendor error: native
  socket closure made the factory stop before reading queued output. Adapter
  delivery now remains active through terminal output/EOF consumption. Sender
  failure still invalidates input immediately.
- A runtime-to-factory probe exposed canonical `linear16` reaching APIs that name
  the same PCM representation `pcm_s16le`. Both adapters now explicitly translate
  the canonical alias before native validation; unsupported encodings still fail.

Authoritative protocol references:
[AssemblyAI streaming](https://www.assemblyai.com/docs/streaming/api-spec/streaming-websocket),
[AssemblyAI message sequence](https://www.assemblyai.com/docs/streaming/message-sequence),
and [Cartesia STT 2026-03-01](https://docs.cartesia.ai/2026-03-01/api-reference/stt/websocket).
The latest Cartesia documentation was also checked; its newer API version and
additional models were not silently adopted by this typing change.

Executed evidence, using actual native readers/senders and controlled transports:

- AssemblyAI: **84 function checks**, including typed malformed-input rejection,
  private error strings, Begin readiness, formatting/finality, raw PCM, keyterms,
  failure propagation, repeated EOF and bounded cleanup.
- Cartesia: **89 function checks**. Native connection, PCM/finalize/close, queued errors and exact delta
  text are exercised through the real factory, STT runtime, transcript writer,
  live buffer and agent callback. Public live projection scheduling is replaced
  by a controlled port; this does not claim a DB or browser round trip.
- Shared STT flow: **380 checks**. AssemblyAI and Cartesia now use actual native
  response fixtures, replacing the old impossible generic-envelope fixtures for
  those branches. Their larger native probes are separate, not omitted coverage.
- STT lifecycle: **37 checks**. Speech material/21 native constructors:
  **1,245 checks**. Full Python lint and all five typed/import hooks pass.
- Whole-platform Pyrefly: **768 errors, 4 suppressed**, compared with **790**
  before native STT work and **773** after the first AssemblyAI increment.
  These remain open work, not accepted exceptions or a platform completion claim.

Milestone review, in the required order:

1. **DDD boundaries:** native contracts remain inside vendor sockets; canonical
   transcript form belongs to STT; batching, live capture and agent callbacks stay
   pipeline-owned. An AST import check passed across eight affected native files.
2. **Architecture fit:** existing factory/runtime owners and public adapter methods
   remain. Typed connection acquisition replaces false readiness; no additional
   durable authority, vendor fallback or event store was introduced.
3. **Data flow:** native error-to-factory delivery and exact transcript-to-live-sink
   probes reproduced and verified fixes missed by constructor-only checks.
4. **Plan alignment:** Pydantic replaces native dataclass/open-dict contracts;
   vendor enums do not leak into platform policy. The complete inventory remains
   open, including existing SDK types and unconverted native adapters.
5. **Clean code/security/performance:** native fields are accessed as objects,
   secrets stay outside URLs/representations, malformed consumed data fails at
   ingress, and Cartesia input/output ownership is bounded. No live latency or
   throughput claim follows from controlled function checks.

Speechmatics is addressed by the next milestone below. Remaining work includes
the other STT/TTS adapters; common STT
config/capability/metrics dataclasses and carrier payloads; broader concurrent
connect/disconnect ownership; AssemblyAI native queue bounds; and end-to-end final
delivery during whole-call teardown. Retaining final frames in a native queue does
not prove delivery after upper-level consumers stop. Live provider/browser QA and
human review of changed voice behavior remain pending. All other F0–F10 work stays
in scope.

### F7 progress: native Speechmatics STT contracts

The full F0–F10 objective remains active. No deployment, operator DB changes,
dependency upgrades or live provider calls were performed in this slice.

RCA and changes:

- A local probe reproduced a complete sentence becoming only its first word.
  The old translator selected `results[0].alternatives[0]` instead of the complete
  transcript; speaker lookup also used the wrong nesting level. Native Pydantic
  response objects now project the complete formatted text, all words, real
  word-level speakers and audio-relative timing. Mixed-speaker segments are not
  labelled as one speaker. Native entity forms remain available as metadata.
- Unknown transcript confidence remains unknown. Partial word confidence is not
  meaningful in this protocol and is not promoted to canonical confidence.
  Optional end-of-utterance times remain absent rather than being invented or
  causing rejection. Final text uses the existing delta contract for exact joins.
- Task creation previously masqueraded as connection readiness; audio dequeued
  before acknowledgement could be discarded. Connect now awaits RecognitionStarted.
  Typed PCM/config/vocabulary requests replace the dataclass and open dictionaries.
  Flush uses ForceEndOfUtterance; close sends EndOfStream with the exact count of
  binary chunks sent, including the final partial chunk.
- A single native reader replaces two response queues and silent reconnect loops.
  Binary writes apply socket backpressure; output is bounded. Close drains within
  a deadline, joins the reader and makes repeated EOF terminal. Native final
  output stays readable; owned/borrowed HTTP lifetimes are separate. Concurrent
  adapter connects are serialized. Unsupported audio formats fail before sending.

Reference: [Speechmatics Realtime v2](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket).
The existing language-based provider selection remains; this slice does not add
a default model tier, translation, multichannel audio or another provider option.

Executed evidence:

- **104 native/function-flow checks**, using actual parsers, WebSocket sender and
  reader, adapter, factory, STT runtime, transcript writer, live buffer and agent
  callback. Controlled network ports replace vendor I/O; live projection scheduling
  is substituted. Covers malformed input/privacy, entities, full text, mixed
  speakers, early audio, handshake failure/timeout/cancellation, immediate queued
  errors, explicit finalization, exact close count, abrupt/cancelled close and a
  full queue. Missing optional vendor IDs use local fragment correlation without
  inventing a provider request ID.
- **346 shared STT checks**; Speechmatics now uses native response fixtures rather
  than its former impossible generic envelope. The larger native checks above
  cover the removed intermediate-fixture cases at the actual owning boundary.
- **37 lifecycle checks** and **1,245 material checks / 21 real STT/TTS constructors**.
- AssemblyAI **84** and Cartesia **89** native regression checks pass unchanged.
  App import/OpenAPI remains **245 paths / 564 schemas**; the added word speaker
  field is not an operator API schema. Documentation, formatting and diff checks pass.
- All five scoped type/import hooks and full Python lint pass. Whole-platform
  Pyrefly reports **765 errors, 4 suppressed**, down from the preceding **768**;
  these remaining errors are unresolved work, not accepted exceptions.

Milestone review, sequentially:

1. **DDD boundaries:** native request/response enums stay in the vendor socket;
   `TimedWord.speaker_id` is canonical STT data. Import/AST checks confirm no module
   or pipeline dependencies in the native/adapter files.
2. **Architecture fit:** existing factory, runtime and pipeline remain the owners;
   no new durable authority or retry mechanism was introduced.
3. **Data flow:** full text, connection correlation and speakers survive batching;
   exact text reaches live capture and the agent callback. Review corrected overly
   strict optional EOU/entity fields against the vendor reference.
4. **Plan alignment:** consumed native contracts now use Pydantic, finite enums and
   meaningful constants; unused model/language aliases were removed with no callers.
5. **Clean code/security/performance:** named terminal errors replace silent retry;
   sensitive text is excluded from representations and validation errors, the key
   remains header-only, and output/input ownership is bounded. No throughput or
   live-provider readiness claim follows from these checks.

Remaining: other native STT/TTS paths, shared STT configuration/capability/metrics
dataclasses, broader voice typing, whole-call final-drain delivery, live vendor and
browser QA, and human review of changed voice behavior. Native final frames kept
during close do not prove delivery after upper-level call consumers have stopped.
The rest of F0–F10 remains in scope.

### F7 progress: native Deepgram Listen v1 STT contracts

The complete F0–F10 goal remains active. This slice changes no operator DB rows,
migrations, deployments, dependencies or credentials. Flux v2 remains separate.

RCA and implementation:

- Reproduced discarded `UtteranceEnd.last_word_end`, with the adapter assigning
  zero to the event's wall-clock timestamp instead. Native response models now
  keep audio-relative times distinct; canonical timing uses milliseconds and
  word timing retains seconds. Full segments, native request IDs and real usage
  survive translation. Absent confidence stays absent.
- Configured `endpointing`, `utterance_end_ms` and `vad_events` never reached
  the old native options. Frozen Pydantic query/config models now forward them,
  encode query values and keep the key header-only. Native validation rejects
  invalid PCM, durations and detection combinations. Factory-generated defaults
  no longer add an utterance delay when interim results were explicitly disabled.
- Segment finality is no longer inferred from speech-final alone. Final endpoint
  text uses the existing END_OF_TURN contract; provisional text stays provisional.
  Metadata becomes reported usage rather than being dropped.
- The old stream created tasks before connection acquisition, retried silently,
  had unbounded input/output queues and did not send a functioning Finalize.
  CloseStream was sent after normal socket cleanup. The replacement awaits the
  upgrade, writes PCM with backpressure, bounds the response queue, and uses one
  task group for the reader and JSON KeepAlive. The existing factory owns retry.
- Finalize keeps the stream open; CloseStream precedes bounded terminal metadata
  drain. Timeout, cancellation, failed upgrade, failed KeepAlive and malformed
  responses close resources and join native tasks. EOF is repeatably terminal;
  accepted output remains readable after physical closure. Borrowed HTTP sessions
  stay caller-owned. Unused model/language Literal aliases were removed.

Vendor references: [Listen v1](https://developers.deepgram.com/reference/speech-to-text/listen-streaming),
[endpointing/finality](https://developers.deepgram.com/docs/understand-endpointing-interim-results),
[utterance end](https://developers.deepgram.com/docs/utterance-end),
[Finalize](https://developers.deepgram.com/docs/finalize),
[CloseStream](https://developers.deepgram.com/docs/close-stream), and
[KeepAlive](https://developers.deepgram.com/docs/audio-keep-alive).

Executed evidence:

- **112 native function/data-flow checks**: parser/config, exact transcript and
  timing, zero/absent confidence and usage, provisional/final/end distinctions,
  strict numeric inputs, privacy, PCM chunking, explicit flush/close, readiness,
  failed/timeout/cancelled upgrade, KeepAlive failure, malformed/abrupt closure,
  bounded/full output queues, borrowed sessions and stable terminal output.
  Actual factory, STT runtime, transcript writer, live buffer and agent callback
  execute with controlled transport and substituted live-projection scheduling.
- **Real aiohttp loopback transport** verified encoded query isolation, header
  auth, PCM bytes, Finalize, response parsing and CloseStream/metadata cleanup.
  The initial sandbox denied binding; the authorized localhost-only retry passed.
  This is not a live Deepgram provider or microphone test.
- **321 shared STT checks**, **37 lifecycle checks**, and **1,245 material checks
  through 21 real STT/TTS constructors** pass. The shared probe now provides
  native Deepgram objects, replacing the removed generic private method seam.
  Probe-only missing-method/local-import failures were corrected; no production
  compatibility method was restored to accommodate stale fixtures.
- All five scoped type/import hooks pass. Full Ruff, formatting and diff checks
  pass. Whole-platform Pyrefly reports **757 errors, 4 suppressed**, down from
  **765** before this slice. Outstanding errors remain remediation work.
- Documentation validation passes (**46 pages, 284 links, 47 diagrams**); app
  import/OpenAPI remains **245 paths / 564 schemas**. No operator API schema
  changed and no frontend regeneration was needed.

Sequential milestone review:

1. **DDD:** vendor enums/requests/responses stay in the socket. AST checks confirm
   no module/pipeline imports or Any/Dict/dataclass contracts in the four files.
2. **Architecture:** factory recovery and pipeline voice policy remain unchanged
   owners; no new generic stream framework or durable-work authority was added.
3. **Data flow:** configured material reaches the query; native text, timings and
   request correlation reach debounce/live capture/agent callback. Native close
   output remains readable. Whole-call teardown delivery is still unproven.
4. **Plan:** Pydantic objects replace native dictionary parsing and dataclasses;
   finite native vocabulary is enumerated, operational limits are named. The full
   platform objective has not been reduced to this adapter.
5. **Clean code/security/performance:** strict consumed fields, private repr and
   validation errors, fixed vendor origin, encoded query and bounded resources.
   Review reproduced Literal[1] accepting booleans/floats; an explicit exact-int
   validator now rejects those inputs. No new dependency or throughput claim.

Remaining: other native STT/TTS implementations; shared STT config, capability and
metrics dataclasses; broader voice typing; whole-call final-drain delivery; live
vendor/browser QA and human review. All other F0–F10 work stays in scope.

### F7 progress: shared STT config, capability and metrics contracts

The preceding question-only turn verified the existing Pydantic execution-context
change. This continuation advances the original F0–F10 goal; it does not close F7.

Reproduced before editing with the actual config, factory and runtime constructors:
unchecked boolean/numeric config, numeric vocabulary coerced to text, nested native
options nested a second time, factory/config encoding disagreement, retry values
dropped during runtime handoff, negative byte/invented event metrics, and duplicate
factory capability claims disagreeing with the selected adapter.

Changes:

- `STTConfig` / `RetryOptions` are frozen Pydantic models with strict finite numeric
  fields, validated text, owned provider/media/mode enums, common speech-option
  policies and explicit JSON-only native options. Normal model dumps and reprs
  exclude the private native envelope. Explicit handoff revalidates even copied
  or subsequently mutated inputs and emits safe configuration errors.
- Flat/nested input converges through one normalization path. Duplicate conflicts
  and reserved nested routing/retry fields are refused; resolved credentials remain
  authoritative. The runtime retains `factory.config`, including retry values and
  validated debounce milliseconds, rather than flattening and reconstructing it.
- `STTCapabilities` uses explicit support enums; all ten adapter declarations were
  updated while retaining boolean JSON values. Factory inspection delegates to its
  selected adapter, removing the drifting duplicate table. This constructs but
  does not connect the adapter; it is not live certification of every declaration.
- `STTMetricsSnapshot` validates mutable counts and event kinds. Failed byte-count
  or event-kind validation leaves counters untouched; timestamps are monotonic
  seconds, not human dates. Factory/runtime projections keep their existing keys.
- Data-flow review rejected a generic `input_audio_codec`/`encoding` equivalence
  guard: Sarvam converts incoming mu-law to native PCM, so both values must survive
  independently. A real adapter byte-level check proves that conversion still works.
  Listen utterance delay likewise no longer becomes Flux end-of-turn timeout.

Verification:

- **388 shared contract checks** cover malformed values, direct construction,
  copied/nested input, secrets, round trips, enum JSON, retry preservation, metrics,
  capability parity, provider selection and Sarvam audio conversion.
- **321 shared STT flow**, **37 lifecycle**, **112 Deepgram**, **84 AssemblyAI**,
  **89 Cartesia**, **104 Speechmatics**, and **1,245 material checks / 21 real
  STT/TTS constructors** pass with controlled I/O. Two earlier native probes used
  boolean capability assertions; they now compare enum members with unchanged
  expected support. A Sarvam probe helper name was corrected after checking the
  actual method; no runtime compatibility shim was added.
- All five scoped type/import hooks pass. Whole-platform Pyrefly remains
  **757 errors / four suppressed**; that is neither a new regression nor completion.
- The real aiohttp localhost WebSocket probe passes query encoding, dummy-key
  authorization, PCM/finalize, transcript/metadata and close. It contacts no vendor.
  Full Ruff, affected formatting, diff whitespace and documentation checks pass
  (**46 pages / 284 links / 47 diagrams**). App import/OpenAPI generation passes
  with **245 paths / 564 schemas**, unchanged; no frontend regeneration is needed.
- Reviewed sequentially: DDD ownership, architectural fit, source-to-native data
  flow, original plan/Pydantic alignment, then readability/security/cost. No new
  provider, default model, dependency, DB migration or deployment was introduced.

At that milestone, `RetryOptions` was preserved but not enforced. The next slice
below fixes connection establishment and removes the unused base-adapter copy.
The current STT manager still reconnects once on selected send failures, and the
shared task supervisor owns its existing restart behavior. Resolve those through
the lifecycle flow, rather than claiming that Pydantic validation implements it.
Other native STT/TTS requests/responses and configuration semantics, whole-call
final drain, live vendor/widget acceptance, and remaining F0–F10 work stay open.

### F7 progress: STT connection-attempt ownership and typed cleanup failure

The previous question-only exchange verified the current Pydantic context models.
This continuation implements the next established F7 lifecycle gap; the full
platform-wide F0–F10 goal remains active.

RCA and scope:

- A controlled real-factory probe reproduced ignored `max_retry`: one failing
  connection stopped despite a configured additional attempt. Source inspection
  confirmed that connect/readiness had no factory deadline and reconnect ignored
  cleanup errors before opening another connection.
- Retaining a typed setting without an execution consumer was incomplete contract
  adherence. This slice changes establishment, not permission to replay audio or
  a new general-purpose recovery framework.

Implemented:

- The existing immutable `RetryOptions` now defines additional attempts, per-attempt
  connect/readiness seconds and post-cleanup delay seconds. The factory owns this
  policy for startup and explicit reconnect establishment.
- At this milestone, only `STTConnectionFailed` and `TimeoutError` entered the attempt loop. Other errors
  stop immediately after cleanup. Vendor-native error classification remains
  incomplete; these exception names are not proof of transient vendor failure.
- Every failed attempt awaits cleanup before another connection. Cleanup has a
  separate named ten-second cooperative deadline. `STTConnectionCleanupFailed`
  distinguishes unsafe retry from ordinary establishment failure. Failed close
  retains the factory handle; explicit reconnect no longer ignores close errors.
- Cancellation propagates through connect, readiness, backoff and cleanup, including
  a repeated cancellation. Deadline/cancellation checks prevent a returning adapter
  that swallowed cancellation from being accepted as ready. Coroutines that block
  or never return still require native lifecycle remediation; Python cannot forcibly
  stop them safely.
- Removed the unused base-adapter retry holder and five stale comments asserting
  nonexistent retry helpers. All ten adapters still construct through the existing
  explicit factory. Reader tasks start only after readiness; no audio is sent by
  this retry loop. Connection-body failures do not reenter startup retries.

Verification:

- **84 connection-attempt function/effect checks** cover exact retry limits,
  timeout/readiness, cleanup failure/hang, cancellable delay, repeated cancellation,
  swallowed deadline/caller cancellation, explicit reconnect, safe handle retention
  and no orphaned factory tasks. A review probe reproduced swallowed timeout followed
  by not-ready return; checking the deadline before polling closes that stall.
- **Nine actual runtime/factory checks** cover recovered startup state emission,
  caller cancellation and safe `STTConnectionCleanupFailed` error projection.
  A failed first attempt does not emit a premature ready or fatal error state.
- The real aiohttp localhost WebSocket path passes **timeout → native cleanup →
  second connection → PCM → factory transcript → close**. It uses dummy credentials
  and no vendor. The probe initially assumed a failed handshake had started a reader;
  inspection confirmed `_task` is legitimately `None` before upgrade. Its assertions
  now check closed HTTP resources and optional task completion. Audio assertions
  respect native PCM chunking rather than assuming one network frame per input.
- Existing **388 shared contracts**, **321 STT flow**, **37 lifecycle**, **112
  Deepgram**, **84 AssemblyAI**, **89 Cartesia**, **104 Speechmatics**, and **1,245
  speech material checks / 21 constructors** pass with controlled I/O.
- The four owned STT contract/factory files pass scoped Pyrefly with **zero errors**;
  all five scoped type/import hooks pass. Whole-platform Pyrefly remains **757
  errors / four suppressed**, not completion. AST inspection confirms no new
  module/pipeline imports or `Any`/dataclass carriers in those four files.
- Full Ruff, STT formatting, whitespace and documentation gates pass. App import
  and OpenAPI generation retain **245 paths / 564 schemas**. No public schema,
  frontend, dependency, migration, operator DB or deployment change was needed.

One sequential milestone review:

1. **DDD boundaries:** immutable retry input and typed cleanup error stay socket-owned;
   no domain, credentials lookup or DB policy moved into the factory.
2. **Architecture fit:** reuse the existing factory and adapter protocol, remove the
   unused base copy, and leave product voice policy in the pipeline. No new queue,
   retry framework, default provider or model was introduced.
3. **Data flow:** resolved config → validated factory config → attempt/readiness →
   cleanup/retry → reader → runtime state. Cleanup timeout is not caught as an
   ordinary connection timeout; uncertain closure cannot open another connection.
4. **Plan alignment:** this fixes the previously documented inert retry settings;
   it does not certify active-stream recovery or replace the full F0–F10 objective.
5. **Clean code/security/cost:** named time units and a distinct cleanup exception
   replace magic polling and ignored failures. Logs contain counts/error types,
   not credentials or audio. Attempts are sequential and config-bounded; cooperative
   cleanup has an independent limit. Cancellation is not converted into retry.

Remaining at this milestone, continued by the classification slice below:

1. Translate native connection failures into explicit transient/terminal contracts;
   existing `STTConnectionFailed` wrappers may also include permanent vendor refusal.
2. Resolve one in-flight reconnect owner across runtime sends, factory supervisors
   and native loops (including Flux, Sarvam and Google's stream implementation).
   Recreate/retain readers correctly and serialize concurrent reconnect requests.
3. Replace the runtime's error-text matching and broad connection-error replay with
   a typed not-sent outcome; do not replay uncertain audio writes.
4. Finish native STT/TTS typing and lifecycle cleanup, whole-call terminal drain,
   real vendor/widget acceptance and the remaining full-platform F0–F10 work.

These are working function checks, not new human-accepted behavioral baselines.
No permanent test files were added; live vendor/browser QA remains unrun here.

### F7 progress: typed WebSocket STT establishment failures

The full platform-wide F0–F10 goal remains active. This slice completes the
HTTP/WebSocket establishment translation through eight adapters, not all native
STT lifecycle or response typing.

RCA and contract:

- A controlled native `InvalidStatus(401)` reproduction returned `UNKNOWN` from
  both Flux and Sarvam. Earlier code wrapped all connection exceptions in the same
  failure type; the newly typed factory could not recover transient cases without
  knowing their cause. Other adapters leaked the native handshake exception.
- `STTConnectionFailureKind` now distinguishes transport, timeout, service refusal,
  authentication, authorization, request, rate limit, quota, TLS, protocol and
  unknown causes. Constructor input must be an enum, not a string. The factory
  retries only network/timeout/service-unavailable kinds and its own timeout.
- `connection_errors.py` owns the HTTP/WebSocket representation boundary. Deepgram
  Listen, Flux, Speechmatics, AssemblyAI, Cartesia, Sarvam, Gladia and RevAI use it
  from their real native-connect branches. Six streaming adapters close before
  translation; Flux/Sarvam rely on the WebSocket library's failed-handshake cleanup.
- TLS errors take precedence over network-error base classes. Unknown/mixed errors
  remain terminal; no message matching, class-name matching or arbitrary cause-chain
  unwrapping is used. Only a directly documented handshake EOF cause is recognized.
- Adapter cleanup failures have a separate terminal exception. This closes the
  newly examined case where cleanup itself times out and could otherwise look like
  a retryable connection timeout after a second cleanup call. Cancellation remains
  cancellation, including when cleanup also fails. Existing native implementations
  that swallow cleanup failures still need lifecycle work; this cannot prove a
  close whose owner hides its outcome.
- HTTP 429 is classified but not retried by this fixed-delay loop. Adding a label
  is not an implementation of provider backoff/admission. Retry logs expose only
  bounded counts and the socket-owned failure category.

Verification on 2026-09-08:

- **255 failure-contract/function checks** cover native HTTP/WebSocket types,
  refusal versus transient categories, DNS/OS/TLS distinctions, unknown failures,
  enum enforcement, cancellation identity, every failure kind's factory attempt
  count, all eight adapter entrypoints and cleanup failures in six native streams.
- Real localhost aiohttp tests: 401/403/429 each make one request; 503 makes two,
  then PCM reaches the native stream and a final transcript reaches the factory
  consumer. Captured HTTP sessions/readers close. No remote vendor or operator DB
  was used. The initial local fixture omitted Deepgram terminal metadata; the
  corrected fixture supplies the native terminal message and asserts no successful
  stream failure instead of ignoring the teardown log.
- Existing **84 startup**, **9 runtime/startup**, **388 shared contracts**, **321
  STT flow**, **37 lifecycle**, **112 Deepgram**, **84 AssemblyAI**, **89 Cartesia**,
  **104 Speechmatics**, and **1,245 speech material / 21 constructor** checks pass.
  Two timeout function expectations were deliberately updated from raw TimeoutError
  to `STTConnectionFailed(TIMEOUT)`, asserting the native cause and unchanged cleanup.
  No product acceptance expectations or permanent test files were introduced.
- Seven owned error/factory/native-adapter files pass scoped Pyrefly; all five
  scoped type/import hooks pass. Whole-platform Pyrefly remains **757 errors / four
  suppressed**, so this is progress, not completion. Full Ruff passes.
- All **18 STT files** pass formatting; whitespace and documentation gates pass
  (**46 pages, 284 links, 1,161 Python modules, 6,146 docstrings, 47 diagrams**).
  App import/OpenAPI generation retain **245 paths / 564 schemas**. No dependency,
  public API, migration, frontend, operator DB, commit or deployment change occurred.

Sequential milestone review:

1. **DDD boundaries:** HTTP/library exceptions remain adapter-owned. Failure kinds
   and establishment policy remain socket-owned; no module/DB or product policy
   imports were added.
2. **Architecture fit:** one existing factory chooses bounded attempts. The shared
   adapter helper absorbs classification and cleanup-error precedence without adding
   a retry framework or taking ownership of voice policy.
3. **Data flow:** native refusal → typed failure → cleanup → factory decision;
   successful retry → actual PCM → native response → canonical factory queue. Unknown
   failures, auth and uncertain cleanup cannot authorize another attempt.
4. **Plan alignment:** fixes the established classification gap. The runtime's
   error-text replay, independent reconnect owners and remaining vendor contracts
   are still explicit work, not implicitly certified by scoped checks.
5. **Readability/security/performance:** named HTTP/OS constants, typed callable
   cleanup, no new casts or broad payload objects, safe error messages, sequential
   bounded attempts. Third-party native exception causes stay diagnostic context;
   no response bodies or credentials are copied into the new messages/log fields.

Remaining at this HTTP/WebSocket milestone (continued by the AWS slice below):

1. AWS Transcribe native lifecycle/types. The installed Smithy `DuplexEventStream.close()`
   awaits output again before closing input. The adapter currently clears a partial
   handle on `await_output()` failure and swallows close failure. Fix and test these
   paths before admitting retryable AWS failures. Do not rewrite SDK-owned dataclasses.
2. Google native streaming readiness/errors/cleanup. Its adapter currently marks
   connected when launching the reader, not when the vendor accepts the stream.
3. Unify in-flight recovery across native loops, factory supervisors and runtime
   send paths, with serialized reconnect and reader ownership. Use a typed not-sent
   outcome; never infer replay safety from a connection exception.
4. Finish every remaining native STT/TTS and platform F0–F10 contract, full call
   final drain, then real vendor/widget acceptance. Nothing in this slice claims
   these broader paths complete.

Sources: [websockets 15.0.1 retry classification](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/client.html#websockets.asyncio.client.process_exception),
[Amazon Transcribe streaming errors](https://docs.aws.amazon.com/transcribe/latest/APIReference/API_streaming_StartStreamTranscription.html#API_streaming_StartStreamTranscription_Errors),
and installed aiohttp 3.14.3 / smithy-core 0.6.0 / Transcribe SDK 0.7.0 source.
The current AWS docs describe concurrent-stream quota as a typical limit failure;
the installed modeled exception's older description emphasizes duration. Neither
justifies treating every quota refusal as a generic immediate network retry.

### F7 progress: AWS Transcribe native contracts and owned partial streams

The full F0–F10 end goal remains active. This slice follows resolved settings →
native request/signing → event stream → canonical transcript/factory → cleanup.

Confirmed RCA and impact:

- `Any` config and stream fields obscured the native SDK contract. The adapter
  discarded a stream when `await_output()` failed. A function probe against the
  installed `DuplexEventStream` proves its `close()` rethrows output failure before
  calling input close. Swallowed cleanup exceptions then implied false success.
- smithy-core 0.6.0 starts an internal request task. A pre-transmit failure such as
  a missing identity resolver can finish that task without resolving the future
  awaited by `duplex_stream()`. Startup waited until timeout and the task failure
  was unobserved. The probe now exercises that actual SDK branch without HTTP I/O.
- AWS's extensible enums accept unknown strings. An annotation alone did not
  enforce the request's supported language/stabilization choices.
- `EventReceiver.receive()` returns `None` at EOF, not necessarily
  `StopAsyncIteration`. The old adapter treated EOF as an error, collapsed native
  error variants and could mark disconnected before the factory read a failure.
- `ResultId` identifies a transcript segment, not the HTTP request. The old
  projection used it as `provider_request_id`, omitted word speaker labels and
  attributed mixed-speaker results to the first speaker.

Implemented:

1. `AmazonTranscribeAdapterConfig` validates consumed options, supported sample
   rates, installed SDK language/stabilization choices and explicit speaker policy.
   Secret fields are hidden/excluded; optional shared settings stay outside the
   native request. No new provider/model default or SDK dataclass replacement.
2. `AmazonTranscribeStream` owns exact `DuplexEventStream`, `EventReceiver`, output
   and task types. Its SDK interceptor observes early request-task failure through
   a public hook. The per-call plugin avoids losing observer identity to the SDK's
   config deep copy. There is no global monkey-patch, private SDK attribute access
   or dependency change.
3. Startup, send and receive waits are shielded from caller cancellation. Cleanup
   waits for an outstanding write, closes input, settles startup/reads and closes
   output. Partial/late handles remain owned. Its five-second caller deadline leaves
   late cleanup tracked; failed or incomplete cleanup blocks replacement. Adapter
   connect/disconnect calls serialize one native lifecycle.
4. `STTConnectionRetryUnsafe` distinguishes a known error cause from permission to
   retry. Native AWS establishment errors preserve their diagnostic category but
   do not add service-error retries to the factory. The existing factory-owned
   timeout path still requires successful cleanup and remains a separate policy.
5. Queued transcripts and pending terminal errors remain factory-readable. EOF,
   native modeled exceptions and unknown event variants have distinct handling.
   Request/session IDs come from native output; result/channel IDs use a validated
   metadata object. Word speakers survive translation; ambiguous segment speakers
   stay absent.

Verification on 2026-09-08:

- **107 AWS function/effect checks**: strict config, unknown SDK enum choices,
  secret privacy, real partial-stream close regression, PCM/event types, EOF,
  native modeled errors, late startup, send/read cancellation, timeout retention,
  both-side cleanup failures, concurrent entrypoints and unsafe retry refusal.
- Full installed SDK path with a controlled HTTP transport: actual serialization,
  SigV4 signing, signed PCM input, binary event decoding, canonical factory queue,
  response identities, HTTP 503 and input EOF. The factory consumes terminal quota
  errors as errors, not an unnoticed disconnected state. No real AWS endpoint,
  CRT network callback, browser, operator credentials or operator DB was exercised.
- Existing **255 failure**, **84 startup**, **388 shared contracts**, **321 STT
  flow**, and **1,245 speech material / 21 constructor** checks pass.
- Four changed owner files pass scoped Pyrefly. All five type/import hooks, full
  Ruff, STT formatting, documentation and app import/OpenAPI checks pass.
  Whole-platform Pyrefly remains **757 errors / four suppressed**. These results
  are scoped progress, not platform completion or live vendor acceptance.

Sequential milestone review:

1. **DDD boundaries:** native enums, requests, events and observer stay in the
   adapter. Socket-owned errors control factory retry; no module/DB imports.
2. **Architecture fit:** the stream owner hides an actual SDK ownership gap, not
   a second retry engine. Existing factory and neutral speech-option contracts remain.
3. **Data flow:** real SDK sign/encode/decode and factory delivery are covered;
   review additionally fixed pending terminal-error visibility and request/segment
   identity confusion. Native SDK response types are not replaced with loose JSON.
4. **Plan alignment:** completes this native contract/partial-stream slice, not
   all AWS resource disposal, final drain or overall voice lifecycle.
5. **Clean code/security/performance:** explicit task types, no casts/ignores or
   credential snapshots, safe public errors, one serialized sender/lifecycle and
   bounded caller cleanup. Native operations may remain pending after that bound;
   retention prevents unsafe replacement but is not forced physical disposal.

Next:

1. Resolve physical CRT transport ownership/termination and final transcript drain
   using supported, version-verified APIs. The installed transport exposes no public
   pool `close()`. Do not enable native AWS service-error retries or claim all
   resources close until this is resolved and tested against actual transport.
2. Google request/event types, accepted-stream readiness and native resource ownership.
3. Shared in-flight recovery and typed not-sent outcomes, then remaining STT/TTS and
   F0–F10 flows. Uncertain audio writes still must not be replayed based on exception
   text. Live vendor/widget QA and human product acceptance remain unrun for this slice.

Sources: [AWS streaming request/errors](https://docs.aws.amazon.com/transcribe/latest/APIReference/API_streaming_StartStreamTranscription.html),
[AWS result identity/timing](https://docs.aws.amazon.com/transcribe/latest/APIReference/API_streaming_Result.html),
[SDK operation contract](https://docs.aws.amazon.com/sdk-for-python/v1/reference/clients/transcribe-streaming/operations/start_stream_transcription/),
and installed aws-sdk-transcribe-streaming 0.7.0 / smithy-core 0.6.0 source.
Current online SDK docs differ in client/config naming; implementation and probes
use the installed signatures, not an uninstalled release's close method.

### F7 progress: AWS physical transport ownership

This continues the preceding AWS slice; the complete F0–F10 goal remains active.

Confirmed source/effect findings:

- The SDK's default transport hides its connection pool and has no public close
  method. Its generic CRT async stream has an empty request-body implementation
  in installed awscrt 0.32.2. A direct function probe confirms that method does not
  consume input. Earlier controlled-transport QA bypassed this native body writer;
  those results did not prove PCM reached a socket.
- Native header waiters can remain pending when a connection fails before headers.
  Native chunk EOF can also accompany failed completion. Both need explicit
  completion ownership, not a cast or an optimistic disconnected flag.

Implemented in `amazon_transcribe_transport.py` and `amazon_transcribe_stream.py`:

1. An adapter-owned transport implements the SDK's public transport contract and
   uses `AIOHttp2ClientConnection` / `AIOHttp2ClientStream`. Signing, endpoint
   resolution, request serialization and binary event coding remain SDK-owned.
   A per-call plugin installs the transport after config deepcopy.
2. Exact native connection, request, body, writer and completion types replace
   hidden ownership. Request and close waiters are shielded; late acquisition is
   retained and closed. The public input iterator captures the native writer task
   so its failures are observed without inspecting private task/pool attributes.
3. Event cleanup gets a two-second grace period, then physical shutdown wakes
   outstanding I/O. The five-second caller deadline still reports incomplete
   cleanup and retains its operation. Shutdown's completed future proves disposal;
   a shutdown error reason is not confused with an unclosed connection.
4. HTTPS/certificate verification remain required. Header names/control characters
   are checked before CRT. Repeated headers, signed path/query and body bytes retain
   their meaning. Manual response flow control bounds native buffering.

Verification on 2026-09-08:

- 23 transport function checks: invalid headers/body/scheme, one-attempt ownership,
  idempotent close and the installed generic-body regression reproduction.
- Real local TLS/HTTP2 transport: PCM bytes, repeated headers, path/query, normal
  EOF, hanging peer, cancellation before headers and abrupt peer shutdown.
- Delayed real connection acquisition: cancelling setup and cleanup waiters does
  not discard the late socket; repeated close joins its shutdown, and no request
  is sent after closing begins.
- Full installed SDK → CRT → adapter → factory path: actual SigV4, signed PCM,
  binary transcript decoding and identity projection; normal/hanging close, HTTP
  503, pre-header cancellation and abrupt shutdown. No unobserved task errors.
- Existing 107 AWS, 255 failure, 84 startup, 388 shared-config, 321 STT-flow and
  1,245 speech-material checks pass, including 21 native constructors. The older
  STT-flow probe initially failed because it still expected a segment ID as a
  request ID. Its function assertion now checks the previously corrected contract;
  production identity behavior was not changed to satisfy the stale probe.
- Scoped Pyrefly is clean; whole-platform remains 757 errors / four suppressed.
  Full Ruff, five type/import hooks and documentation checks pass.

Sequential review: DDD boundaries remain inside the socket adapter; architecture
uses the SDK extension point rather than a second signing/retry engine; real socket
data flow now supplements controlled transport checks; plan scope remains full
platform hardening; cleanup/cancellation and bounded buffering were checked as part
of the same milestone. No dependency, DB, migration, operator configuration, API,
UI, deployment or Git history changes.

Still required: final transcript drain/delivery at disconnect, Google native
readiness/ownership, safe in-flight recovery, the remaining F0–F10 contracts and
live vendor/widget QA. Local TLS fixtures use dummy credentials and an ephemeral
CA; they do not establish AWS service acceptance or human product acceptance.

Source evidence: installed aws-sdk-transcribe-streaming 0.7.0, smithy-core 0.6.0,
smithy-http 0.4.3 and awscrt 0.32.2; [CRT shutdown completion](https://awslabs.github.io/aws-crt-python/api/http.html#awscrt.http.HttpClientConnectionBase.shutdown_future).

### F7 progress: typed final-output ownership and startup rollback

This follows the AWS physical-transport slice. The full F0–F10 objective remains
active; this is not a platform-wide completion claim.

Confirmed RCA:

- A real local TLS/HTTP2 peer emitted its only final transcript after the installed
  AWS SDK sent signed input EOF. The old adapter stopped its receiver before EOF:
  factory context exit delivered zero events. Earlier transcripts emitted before
  close did not exercise that boundary.
- Factory/runtime task shutdown could stop forwarding before final provider output
  and debounce were delivered. Keeping separate child references also risked
  reading stale handles after the shared supervisor replaced a failed task.
- Telephony's failed-start `teardown_voice_pipeline_bundle` cancelled the transcript
  writer before STT close. Its function reproduction produced an empty consumer
  sink. An STT cleanup exception also skipped TTS disconnect. This is specifically
  the setup rollback path: normal telephony `_drain_voice_pipeline` and browser
  cleanup already close STT before draining transcript queues. The earlier broad
  suspicion about normal telephony ordering was not supported by caller tracing.

Implemented contracts:

1. AWS `finish_input()` sends EOF once without disposing the readable output.
   Adapter close keeps receiving within a bounded final-result deadline, then
   disposes the native stream even when final output fails. Previously observed
   native errors are not relabelled as newly occurring finalization errors.
2. `STTFinalizationFailed` distinguishes incomplete output from incomplete resource
   cleanup and does not authorize retries. Factory forwarding retains an acquired
   event until queue acceptance, uses a bounded delivery wait and refuses to
   replace undelivered output. Its shutdown reads the supervisor's current task
   registry, not duplicate cached child references.
3. Runtime disconnect drains accepted factory events and final debounce while the
   response writer is alive. Closing rejects new audio/reconnect admission. Owned
   disconnect tasks are shielded and their terminal exceptions observed.
4. Startup rollback stops synthesis work, closes recognition with its consumer
   alive, bounds transcript queue drain, then stops recognition tasks. Nested
   cleanup ensures TTS disconnect is attempted after preceding failure/cancellation.
   Missing consumers do not imply delivery; their queue timeout stays visible.

Verification on 2026-09-08:

- Final-at-EOF reproduction failed before the fix; the same actual SDK/CRT path
  now delivers the final event once through the factory.
- Four actual local SDK/HTTP2 runtime cases pass: immediate output, debounced
  output, bounded blocked downstream with retained batch, and parent cancellation.
  Socket shutdown completion and no unobserved task exceptions are checked.
- 17 factory ownership checks pass, including backpressure, supervisor replacement,
  refusal of reconnect after close and refusal to replace undelivered output.
- Six rollback function cases pass: normal, finalization failure, cancellation,
  resource-close error, absent writer and absent bundle. Actual SDK/CRT EOF also
  reaches a running rollback consumer before its task ends; both provider closes
  are checked. These are function/effect proofs, not live carrier or DB proofs.
- Full Ruff and affected formatting pass; six STT files have zero scoped Pyrefly
  errors. Whole-platform baseline remains 757 errors / four suppressed. Telephony
  voice retains four pre-existing diagnostics: the optional background-config
  protocol mismatch and nullable references captured by the silence callback.
  All five existing typed-contract/import hooks pass.

Milestone review sequence: DDD ownership remains adapter → factory → pipeline;
architecture keeps native SDK data inside the adapter and live handles out of
Pydantic serialization; data-flow review covers EOF, forwarding, cancellation and
rollback consumers; plan alignment preserves all F0–F10 requirements; readability
and resource review keep one task registry, named deadlines, explicit errors and
no new dependencies, DB writes, migrations, credentials or network destinations.

Next dependencies: canonical transcript/post-call sinks and outer cancellation
coverage, Google native readiness/ownership, safe in-flight audio recovery, then
remaining provider/product contracts. No claim of durable final-delivery across
process death, live vendor acceptance or human product acceptance is made.

### F7 progress: Google native STT contracts and terminal failure ownership

Verified locally on 2026-09-09; this is not live vendor or browser acceptance.

RCA:

1. The old implementation passed an async generator as the only argument to
   synchronous `SpeechClient.streaming_recognize`. Installed 2.35.0 requires
   separate config and request arguments. A no-network call reproduced `TypeError`;
   the adapter's background retry loop hid failure behind optimistic readiness.
2. Google output was reduced to dictionaries, losing native type checking and
   treating omitted confidence as a measured zero. Configured word timestamps
   were not forwarded to recognition settings.
3. A real local gRPC authentication refusal exposed a shared factory issue:
   restarting a reader did not recreate the failed RPC, and supervision/cleanup
   could replace its cause with generic task-stop or finalization failures.
4. A full-queue sender probe exposed the complementary boundary: receive errors
   were classified, but a failed sender could leak `GoogleAPICallError` outside
   the adapter. The same socket-owned classification now covers both directions.

Implemented contracts:

- `GoogleSTTConfig` is frozen Pydantic. Model/language remain required, extensible
  vendor identifiers; no replacement defaults. Credentials are excluded, then
  parsed only for the native credential constructor. SDK types remain native.
- `SpeechAsyncClient` owns the RPC/channel for one attempt. Native requests send
  config first, then PCM16 bytes. SDK connection establishment precedes readiness;
  it is not a claim of a transcript or successful vendor authorization.
- Native response conversion retains text spacing, finality, word timing,
  detected language and metadata. Confidence/stability absence is explicit.
- Bounded input/output queues and owned EOF/cleanup tasks retain resource
  ownership. Full-queue senders wake when the RPC ends; caller cancellation does
  not abandon provider cleanup. Channel-close cancellation is stream EOF, not
  cancellation of the parent reader. A real parent cancellation still propagates.
- Factory readers no longer self-restart on terminal provider errors. Original
  typed failures survive forwarding/cleanup; incomplete final output remains
  distinct from failure to prove physical resource disposal.

Executed checks:

- **57 Google function/contract checks:** config, native requests/responses,
  credentials, confidence/timing, status codes and SDK exception classification.
- **Four native TLS/gRPC runtime cases:** normal EOF-only final response, hung
  finalization, authentication refusal and caller cancellation. The final response
  reaches `FinalTranscriptBatch`; native channels reach shutdown.
- **Five native verification cases:** success, three authentication refusals and
  a hang through `VoiceRuntimeVerifier`; failed RPCs never report verified.
- **Four backpressure/startup cases plus the sender error boundary:** RPC EOF,
  RPC failure, cancelled blocked sender and cancelled startup. No second queued
  audio item is accepted after the ended RPC; close tasks are joined.
- Existing **84 startup**, **255 failure**, **37 lifecycle**, **17 finalization**,
  **1,245 speech material** checks and **21 native constructors** pass. The shared
  STT source-to-consumer probe now has **287 checks**: Google's former synthetic
  dictionary cases were replaced by native protobuf checks, supplemented by the
  dedicated Google checks above, not retained as a false native-path proof.
- The four native AWS SDK/CRT final-output regression cases pass after the shared
  factory changes. The Google/native/factory type gate reports zero errors; full
  Ruff and scoped formatting pass. Whole-platform Pyrefly still reports **754
  errors, 4 suppressed**; full F0–F10 completion remains unproven.
- Native cancellation leaves no pending asyncio tasks after local channel/server
  shutdown. All five local typed-contract/import hooks pass; the voice gate now
  includes the native Google package and triggers on its changes.

Milestone review, sequential:

1. **DDD boundaries:** native SDK/credentials remain socket-owned; common and
   pipeline consumers receive canonical events/errors. No module imports added
   to sockets, no ORM or tenant policy moved into the adapter.
2. **Architecture fit:** existing factory and runtime remain the owners; no new
   scheduler, durable lane or implicit reconnect authority.
3. **Data flow:** checked config → native RPC → canonical event → factory/runtime
   batch, plus verifier and shutdown error paths. DB transcript sinks are not
   claimed by these fixtures.
4. **Plan alignment:** follows F7's request/response/error/consumer flow and the
   user's Pydantic preference; removed obsolete private dataclass/SDK-wrapper
   assumptions from probes. The other platform flows remain open.
5. **Clean code/security/performance:** removed unused language/model aliases and
   misleading feature prose; bounded queues, typed options/errors, no blocking
   sync RPC loop or hidden infinite retry. TLS fixtures use a local trusted CA,
   never disabled certificate verification; no real credentials or vendor writes.

Sources: [Speech v1 contracts](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v1),
[async client](https://docs.cloud.google.com/python/docs/reference/speech/latest/google.cloud.speech_v1.services.speech.SpeechAsyncClient),
installed `google-cloud-speech` 2.35.0 native signatures and channel lifecycle.

Still required: live Google/vendor acceptance, full call transcript persistence
and cancellation QA, safe in-flight recovery/replay semantics, remaining native
STT/TTS operations and the rest of F0–F10. No DB, migration, dependency, deployment
or Git-history changes were made for this slice.

### F7 progress: Rev AI native contracts and EOF ownership

Verified locally on 2026-09-09. This advances F7, not full F0–F10 completion.

RCA and changes:

- The old query omitted configured language and concatenated credentials without
  encoding. A no-network probe demonstrated both defects. Frozen vendor config
  now builds the native query explicitly and encodes credential values.
- Native hypotheses were flattened through dictionary events. Partial words lost
  separators and confidence was fabricated. Discriminated Pydantic responses now
  translate directly into canonical events, retaining native timing and job ID.
- Startup reported readiness before the native acknowledgement; teardown sent an
  unsupported `CloseStream` message and cancelled readers. The stream now waits
  for `connected`, sends binary PCM with transport backpressure, then sends `EOS`
  and drains final output before closing. Native close codes become typed errors.
- During this slice, execution caught `model=None` crossing into `STTEvent.model`,
  whose absence convention is an empty string. Corrected the producer rather
  than widening the shared contract. Static checking alone missed this boundary.

Executed evidence:

- 54 config/query/parser/conversion/error contract checks.
- Seven real local TLS/WebSocket factory/runtime cases: normal EOF final output,
  parent cancellation, finalization timeout, authentication refusal, invalid
  acknowledgement, mid-stream refusal and malformed output. Successful output
  reaches `FinalTranscriptBatch`; local teardown leaves no pending asyncio tasks.
- Three actual `VoiceRuntimeVerifier` cases: success, authentication refusal and
  hung finalization. These fixtures do not contact Rev AI.
- 253 shared STT source-to-consumer checks, 259 failure checks, 37 lifecycle checks,
  17 finalization checks, 1,245 speech-material checks and 21 native constructors.
  The shared probe replaces obsolete Rev AI dictionary cases with native models;
  failed-cleanup checks now assert retained failure rather than an implicit retry.
- Full Ruff and scoped formatting pass. The native Rev AI package is included in
  the local voice typing hook. Whole-platform Pyrefly: 753 errors, 4 suppressed;
  unrelated platform work remains open.

Milestone review, in order:

1. DDD: vendor wire types and credentials stay in sockets; pipelines consume the
   existing canonical transcript/error contracts. No new cross-module dependency.
2. Architecture: existing adapter/factory/runtime retain ownership; no new worker,
   retry lane, provider default or product policy.
3. Data flow: query → acknowledged WebSocket → native hypothesis → canonical event
   → runtime batch, plus verification and teardown. DB sinks are not proven here.
4. Plan: follows the accepted request/response typing and Pydantic-first scope.
   Live provider/widget acceptance and remaining F0–F10 work are still required.
5. Readability/security/performance: removes recursive polling and unbounded audio
   queuing; uses explicit native enums, encoded credentials and bounded cleanup.
   TLS fixtures trust a local CA; certificate verification was not disabled.

Browser QA: admin and widget return HTTP 200 on ports 5173 and 5174. Browser
automation is blocked by the locked Mac; login, agent/tool use and admin
conversation inspection remain pending. Existing org/provider data is unchanged.

Sources: [Rev AI requests](https://docs.rev.ai/api/streaming/requests),
[responses](https://docs.rev.ai/api/streaming/responses),
[close codes](https://docs.rev.ai/api/streaming), installed websockets 15.0.1.
No DB, migration, dependency, deployment, commit or Git-history changes.

### F7 progress: Gladia V2 session, audio and native response boundary

2026-09-09: wired into the local adapter and verified with controlled native
HTTPS/WebSocket peers. No deployed image or operator configuration changed.

Source review found the V1 implementation omits configured language, fabricates
absent confidence and cancels readers without a terminal drain. Gladia's current
V2 API uses the language codes already exposed by our catalog, but requires a
session-creation POST before the WebSocket. Its migration guide and current init
reference disagree on model availability: the current reference defines
`solaria-1`, whereas the older guide says to omit model. This slice does not add
or claim a configured model; the request omits it and canonical output leaves
model identity unspecified.

Implemented contracts:

- `gladia/wire.py`: frozen request/session models, native sample-rate and encoding
  enums, typed transcript/lifecycle union and a terminal recording command.
  Request only transcripts, lifecycle and errors; do not enable extra products.
- `gladia/session.py`: actual HTTPX session-creation function, ten-second overall
  deadline, 64 KiB response bound, no redirects or automatic retries. HTTP and
  transport failures become terminal socket categories. Cancellation preserves
  uncertainty about whether the remote POST succeeded.
- `gladia_events.py`: native transcript → canonical STT event, preserving text,
  confidence absence/zero, relative timing, word details, language, session and
  utterance identities. Channel number is not a speaker ID.
- The returned token-bearing URL is excluded from model dumps/repr and restricted
  to the documented `wss://api.gladia.io/v2/live` destination and one token query.
  The WebSocket connection refuses redirects, including same-origin redirects.
- `gladia/stt.py`: one resource-owning class per session attempt. Readiness follows
  the matching `start_session` acknowledgement, not merely socket acquisition.
  PCM writes are awaited; shutdown flushes the buffered tail, sends the typed
  `stop_recording` command and drains final output through `end_session`.
  A cancelled/failed send invalidates the attempt, so cleanup cannot replay audio
  whose acceptance is unknown. No in-stream flush command is invented.
- `gladia_adapter.py`: typed native → canonical conversion and a bounded output
  queue replace the V1 dictionary bridge. Pending output/error survives shutdown;
  an unresolved POST/session outcome refuses replacement, including after a
  factory-owned startup timeout. Physical closure and final-output success are
  distinct; cleanup retains one observed owner task.

Executed locally:

- 61 request/response/conversion checks, 114 config checks and 176 session-function
  checks with real HTTPX and controlled transport: status refusals, malformed and
  oversized responses, deadlines, caller cancellation, one POST and client close.
- Six real local TLS factory/runtime cases: binary PCM and buffered-tail delivery,
  partial/final output, parent cancellation, finalization timeout, auth refusal,
  invalid readiness and missing session-end handling.
- Four native startup cases: POST timeout, acknowledgement timeout, foreign
  session ID and redirect refusal. Each made exactly one session POST; none
  emitted readiness. Four actual config-verifier cases cover normal closure,
  auth refusal, hanging finalization and invalid acknowledgement.
- Cancelled-send regression: simulated acceptance followed by cancellation now
  produces one audio send, not a second send during cleanup. This is a controlled
  send-boundary proof, not a claim of remote receipt.
- Shared flow probe: 221 assertions after replacing the old Gladia generic-dict
  cases with native events; failure probe: 239 assertions for the seven other
  WebSocket adapters. Gladia startup coverage now uses its actual two-step native
  protocol rather than an obsolete one-step stream double.

The complete native package and adapter are in the local voice typing gate.
These proofs do not establish live Gladia account acceptance, canonical DB writes
or widget/browser behavior.

Milestone review, sequentially: (1) vendor wire types stay socket-owned, canonical
STT types cross the pipeline; (2) factories/config verification use the same new
adapter, without DB or module access inside it; (3) settings → POST → native
stream → canonical output → final batch and teardown were exercised; (4) this
advances F7 without closing F0–F10; (5) explicit enums, frozen data, ordinary
resource owners, bounded queues, secret-safe errors and no uncertain replay
replace the old unbounded/dictionary path. Review exposed and the regression
reproduced the cancelled-send replay before the fix above.

Next dependencies, retaining the full F0–F10 objective:

1. Continue the remaining native STT/TTS providers and source-to-sink F7 work;
   do not substitute the canonical event fixture for vendor-specific wire QA.
2. Run configured-org widget/admin QA after the Mac is unlocked; no credential or
   provider data reset is needed.

Sources: [migration](https://docs.gladia.io/chapters/live-stt/migration-from-v1),
[current init contract](https://docs.gladia.io/api-reference/v2/live/init),
[WebSocket messages](https://docs.gladia.io/api-reference/v2/live/websocket).
Target local dependencies: HTTPX 0.28.1, websockets 15.0.1; no dependency changes.

### F7 progress: Sarvam legacy STT config and native messages

2026-09-09: typed config/request/response path wired locally. This is **not** a
complete lifecycle or live-provider acceptance claim and does not close F7.

The actual old parser was exercised with an SDK-shaped response. It stripped
transcript whitespace and discarded native request ID, language and metrics;
an error envelope returned `None`. The adapter also advertised interim results
although its configured `/speech-to-text/ws` endpoint emits final utterances.
The original author's reasoning is unknown; the implementation used a generic
dictionary bridge instead of the vendor envelope contract.

Implemented:

- Frozen `SarvamSTTConfig`, secret-safe key fields, explicit sample-rate/source
  encoding enums and shared speech-option enums with unchanged boolean JSON.
  Invalid encodings no longer fall back silently to PCM. Existing known aliases
  still normalize. The adapter no longer mutates interruption policy; the voice
  pipeline owns that policy. A single speech-state enum replaces overlapping
  speech-active/interrupted booleans.
- Typed connection query; installed SDK `AudioMessage`, `AudioData` and
  `SttFlushSignal` construct outbound messages. No request/model/endpoint upgrade.
- Vendor-local `sarvam_wire.py` validates a discriminated transcript/VAD/error
  union. SDK 0.1.28 has `Any` in message/signal kinds and an untagged data union;
  using that union alone does not enforce envelope/data correspondence.
- `sarvam_events.py` retains native text, ID, language and duration metrics.
  Language probability is not transcript confidence; audio duration is not an
  absolute audio offset. Native `occured_at`/aware timestamp values remain event
  time, not segment positions. Undocumented timestamp/diarization payloads are
  not promoted to supported canonical features.
- Invalid/error responses now raise a safe terminal socket error; provider text
  and validation inputs are not echoed. The legacy endpoint's interim capability
  is marked unsupported. SDK-defined error envelopes remain recognized even
  though the newer endpoint comparison describes legacy errors as close-code-only.

Evidence: 170 config checks, including every µ-law byte against `audioop`;
67 native-message/adapter checks; five actual local TLS WebSocket cases through
resolved provider config and the factory-created adapter. Those cases cover
16 kHz PCM, 8 kHz µ-law conversion, VAD/flush/transcript exchange, vendor errors,
invalid envelopes and malformed JSON. Shared flow probe now has 183 assertions
after replacing obsolete generic Sarvam dict cases; 239 startup-failure checks
and 1,245 speech-material checks/21 native constructors remain passing.
The Sarvam files are included in the local voice typing hook without suppressions.

**Lifecycle continuation, 2026-09-09:** the actual old receiver swallowed
`CancelledError`; a controlled close failure was hidden and cleared `_ws`.
The shared runtime also classified `STTConnectionRetryUnsafe` as retryable because
it accepted every `STTConnectionError` subclass. These were reproduced before
changing the affected branches.

- Removed Sarvam's receive-time recursive reconnect. Cancellation propagates;
  remote close, malformed responses and vendor errors remain terminal.
- Serialized audio/flush sends. Failed or cancelled delivery retains an unsafe
  outcome; later input and implicit replacement are refused.
- One shielded close task survives caller cancellation. Its bounded waiter does
  not cancel ownership. Physical cleanup failure retains the socket and blocks
  replacement; repeated disconnect observes the same outcome.
- The runtime now excludes classified establishment and cleanup errors from
  audio replay. This is not a claim that every remaining generic-error branch
  across other vendors already has an explicit not-sent contract.
- Public flush now emits the SDK-defined frame when enabled. It is a request,
  not a finalization acknowledgement; disconnect still does not guarantee final
  transcript draining.

Verification: 29 lifecycle/error-classification function checks; six additional
real local TLS cases through the adapter/runtime for accepted-then-failed audio,
cancelled audio delivery, receive cancellation, remote close, cancelled close and
cancelled handshake. No pending tasks or unhandled task exceptions remained.
The earlier five native wire cases, 170 config checks, 67 native-message checks,
183 shared-flow checks and 239 startup-failure checks also passed again. All five
local typing/import hooks and full backend Ruff passed. No live vendor, DB sink
or browser conversation is claimed by these fixtures.

Next, before the Sarvam milestone review/acceptance:

1. Complete final-output handling within the documented protocol limit, without
   inventing an EOF acknowledgement or equating a timer with delivery proof.
2. Run verifier/final-output probes, then sequential
   boundary/architecture/data-flow/plan/clean-code review of the complete slice.
3. Run configured-org browser/admin QA after the Mac is unlocked. Local peers do
   not prove live account/model availability or canonical DB delivery.

Sources: [legacy WebSocket reference](https://docs.sarvam.ai/api-reference/legacy/speech-to-text/transcribe/ws),
[streaming guide](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api),
[endpoint comparison](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/which-api-to-use).
Target: installed `sarvamai` 0.1.28 and `websockets` 15.0.1. Current docs list
Saaras v3/v4 and a separate realtime endpoint; the existing Saarika v2.5 config
option is retained, not silently replaced or newly claimed live-compatible.
Model-catalog reconciliation requires its own config/verification evidence.

### F7 progress: Flux native response path

2026-09-09: the actual parser hid vendor errors as `None` and discarded request
identity, audio windows and word data. A broad envelope plus dict conversion
erased those distinctions; the author's original reasoning is unknown.

- `deepgram_flux_wire.py` defines tagged Connected/TurnInfo/Error models, turn
  event/trigger enums, finite numeric fields and optional paired word timestamps.
  The existing CloseStream request now also uses a typed model. No SDK dependency
  was added: this adapter uses the existing `websockets` 15.0.1 transport.
- `deepgram_flux_events.py` directly maps native turn observations. Updates are
  partial, eager outcomes are preflight, and confirmed EndOfTurn is final. Native
  request identity, turn/sequence metadata, words and audio intervals survive;
  no platform request ID or transcript-wide confidence is fabricated.
- The voice pipeline retains interruption policy; the adapter no longer maintains
  overlapping speech/interruption booleans or unreachable eager-final suppression.
  Explicitly disabled interim results suppress partial observations. No eager
  query option or speculative LLM generation was enabled by this change.
- Malformed/error responses now raise safe terminal errors. Flux was the final
  caller of the generic `adapters/events.py` bridge; it was removed after checking
  all repository callers. Historical evidence for that bridge is not current
  native-provider proof.

Verification: 107 wire/conversion/adapter function checks; four real local TLS
cases through resolved config, factory and runtime queues (normal turns, disabled
partials, vendor error, malformed input). Eight additional checks feed seven
native turn events through the actual transcript consumer: only EndOfTurn calls
the final-transcript callback; DB projection is patched, not verified. The
current shared STT probe has 142
checks, replacing obsolete bridge assertions with native Flux fixtures. It fails
if any catalogued provider lacks a native fixture. All five local typing/import
hooks, focused typing, full backend Ruff and diff whitespace checks pass.
No live Deepgram, canonical DB or browser acceptance is claimed here.

2026-09-09 follow-up: the consumed Flux config is now frozen and revalidated at
adapter construction. Its key uses excluded `SecretStr`; model/audio enums,
strict sample rates and finite vendor-bounded EOT parameters form an explicit
raw-audio query serialized with `urlencode`. A pre-change function probe proved
key disclosure in dumps, mutation, boolean-to-rate coercion and query injection
through the model string. Native limits now reject those inputs before I/O.
Existing Eylo threshold/time-out defaults remain unchanged; they are not claimed
to be vendor defaults. Shared PCM encoding maps explicitly to native linear16.
Unused native declarations for language, channels, eager threshold and
interruption policy were removed; shared runtime policy remains outside the query.

Verification: 311 config/query checks (including all 60 native model/encoding/rate
combinations and the shared factory path), 107 wire checks, four local TLS cases,
1,245 shared material checks with 21 real STT/TTS constructors, 142 shared STT
flow checks, 239 startup/failure checks and all five typing/import hooks pass.
No live Flux or canonical DB acceptance is implied. The catalog still advertises
`high_vad_sensitivity` for Flux although this adapter sends no corresponding
native setting; resolve that capability projection before declaring the complete
config path finished. Container-based audio auto-detection and eager mode are not
enabled by this change.

Config sources: [configuration](https://developers.deepgram.com/docs/flux/configuration),
[quickstart](https://developers.deepgram.com/docs/flux/quickstart),
[raw encoding/rate release](https://developers.deepgram.com/changelog/2025/10/16).

Browser checkpoint: console login and the standalone widget worked in the existing
Eylo Development org. A real Groq turn persisted two Completed messages
(`01a0842a-a7e6-72e1-a692-c903afc3e8e8`). A read-only SOR turn found Linear issue
VER-50 through `issue_search__ee9fc353`; the console displayed its actual request,
result and final answer, all five messages Completed
(`01a0842c-908d-7b70-b9f0-21154013c441`). Widget list navigation retained the new
conversation. No source mutation, provider reconfiguration or DB reset was done.
These are deployed-runtime smoke checks only: the API container had no checkout
mount and had been running for four days. Rebuild after implementation, then repeat
the configured-provider matrix before claiming acceptance of current source.

2026-09-09 ownership follow-up: a local reproduction confirmed swallowed receive
cancellation, adapter-owned reconnect after remote EOF, discarded failed-close
handles and further input after an uncertain send. The supported cause was mixed
retry/resource authority and missing terminal state, not the typed wire parser.
The original author's reasoning is unknown.

Flux now serializes establishment and input, propagates receive cancellation,
pins unsafe send/protocol/remote-close failures and removes recursive reconnect.
One shielded close task remains owned across cancelled/timed-out waiters. Cleanup
errors retain the socket; an explicit later disconnect may retry physical disposal
of that same socket without resending application control or opening another
stream. Failed CloseStream delivery is a finalization failure after physical
cleanup, not successful completion. Runtime resource owners remain ordinary
classes; configuration and native data remain Pydantic models.

Verification: 34 ownership function checks; eight real local TLS cases covering
uncertain/cancelled sends through the real runtime, receive cancellation, remote
EOF, cancelled/failed cleanup, concurrent establishment and cancelled handshake.
No pending tasks or unhandled loop errors remained. The existing four native
TLS-to-factory/queue cases, 311 config, 107 wire, 142 shared STT and 239 startup
checks also pass. This does not establish readiness acknowledgement, terminal
buffer draining or live-vendor acceptance.

2026-09-09 readiness follow-up: a function reproduction proved that the adapter
reported ready without reading Connected and then accepted an unbound request ID
and duplicate final. It now retains the latest typed Connected/TurnInfo response
as the stream cursor. A new stream must acknowledge before accepting audio or
publishing readiness; subsequent turns must match its request ID and have an
increasing sequence. This is not an invented contiguous-number requirement.
Duplicate Connected and malformed/error messages are terminal. Disabled interim
output still advances the native cursor, so filtering cannot bypass validation.

Startup rollback shares the owned close path under the lifecycle lock. Timeout,
cancellation and invalid acknowledgement close the attempted socket before control
returns to the factory. Only a fully disposed no-audio timeout can follow the
factory's existing bounded retry policy; protocol failures remain terminal.

Verification: 54 readiness/identity function assertions and nine native local TLS
cases (delayed acknowledgement, invalid type, vendor error, malformed response,
timeout recovery, cancellation, foreign identity, stale sequence and duplicate
acknowledgement). The retry fixture checks the previous client is CLOSED and no
longer owned before replacement; remote handler completion is checked separately,
not assumed to share the client's scheduling order. Eight lifecycle and four
factory/queue TLS cases still pass; 34 ownership, 311 config, 107 wire, 142 shared
flow and 239 startup checks pass. Five typing/import hooks and full backend Ruff
pass. No live Flux or canonical final-transcript acceptance is claimed.

Sources: [native message contract](https://developers.deepgram.com/reference/speech-to-text/listen-flux)
and [Connected readiness example](https://developers.deepgram.com/docs/flux/quickstart).

2026-09-09 final-output follow-up: a native local TLS reproduction proved that
closing the socket immediately after CloseStream discards buffered Updates. The
vendor explicitly emits those Updates then EOF without EndOfTurn. A successful
WebSocket close therefore did not establish transcript completion.

The adapter now owns one reader and a bounded canonical-output queue. Shutdown
sends CloseStream once, waits for the reader within a bounded final-drain window,
then disposes the transport. Requested EOF retains the latest nonempty unfinished
hypothesis as a stream-final observation, with `finalization_reason=CloseStream`;
it does not forge a native EndOfTurn or duplicate an already-final turn. Interim
filtering cannot discard the retained hypothesis. Acquired output remains readable
after closure, including the pending event when bounded queue backpressure is
cancelled. The shared factory remains responsible for downstream delivery.

Verification for this follow-up:

- Eight native TLS cases through resolved config, the real factory and voice
  queues: buffered tail, interim disabled, already-final turn, a second unfinished
  turn, empty text, unexpected EOF, timeout and invalid tail identity. The fixture
  exercises EOF without a WebSocket close-status frame as documented by Flux.
- Seven function cases cover stream-final conversion, pending-output retention
  under queue backpressure, and the actual live transcript consumer. One buffered
  final reaches one callback/live-buffer item; DB projection is substituted.
- Nine native readiness and eight native lifecycle/cancellation regressions pass
  with the documented CloseStream fixture. Four native wire/factory queue cases,
  107 wire assertions and 142 shared STT flow assertions pass. No pending tasks or
  unhandled event-loop errors remained in the native probes. Five typed/import
  hooks pass.

2026-09-09 capability and milestone review:

- Onboarding no longer offers the inert Flux `high_vad_sensitivity` field.
  Validation accepts the old saved shape but strips that field from effective
  config. Six function cases prove input is not mutated, unknown keys still fail,
  the obsolete key never reaches the native query, and Sarvam is unchanged.
- The actual capability read path still called `dataclasses.asdict()` after STT
  capabilities became Pydantic. Reproduced `TypeError`, then corrected the consumer
  to `model_dump(mode="json")`. All 10 STT and 11 TTS native adapters now pass the
  real capability projection function with substituted config retrieval. The
  existing type gate did not detect this runtime-only `asdict` mismatch.
- Sequential review covered DDD boundaries, architectural fit, source-to-sink
  data flow, plan adherence and maintainability. Vendor wire types stay inside
  sockets; modules supply resolved config through the pipeline; the factory owns
  retries/downstream delivery; the adapter owns native reader/transport cleanup.
  No network operation or DB transaction was added to capability inspection.
- Data-flow review found a shutdown race: consuming `_reader_error` could erase
  the notification before close determined its outcome. A controlled function
  reproduction proved false success. Close now checks retained `_stream_failure`.
  The regression and 25 native TLS finalization/readiness/lifecycle cases pass.
- Review confirms bounded native output, serialized writes and no implicit audio
  replay. The remaining model-specific optional native features are not claimed
  or enabled. No dependency, public schema or migration changed in this slice.

The Flux local contract milestone is verified, not live product acceptance. No
live Flux, browser delivery of this source revision, or canonical DB persistence
acceptance is claimed. The running API image predates this source. The full F0–F10
goal remains open; continue generic stored voice carriers and remaining provider
flows. Dynamic Configure/ForceEndTurn are not enabled by this slice.

Sources: [Listen v2 reference](https://developers.deepgram.com/reference/speech-to-text/listen-flux),
[turn state semantics](https://developers.deepgram.com/docs/flux/state),
[CloseStream](https://developers.deepgram.com/docs/flux/close-stream).

### F7 progress: call-session identity and live-resource contracts

The complete F0–F10 end goal remains active. This slice follows carrier setup
through session publication, tool lookup, event projection and teardown.

Confirmed RCA and impact:

- The registry stored an immutable key but accepted a mutable session identity.
  A local probe changed the session's organization, then removal left the old
  entry stranded. Runtime lookup and teardown could disagree about ownership.
- Removal used the key alone. A local probe removed an old session, registered
  a replacement with the same key, then repeated old removal: the replacement
  disappeared. Delayed cleanup could unregister a live call.
- The session dataclass left transport, recorder, runner and voice config as
  `Any`, with open task/queue types and arbitrary string metadata. These fields
  hid consumer-contract errors rather than establishing their validity.

Implemented:

1. `CallSession` and `MediaSessionKey` use Pydantic. Session identity requires
   organization, carrier and call ID, cannot be reassigned, and rejects unknown
   fields. Direction uses the existing call-event enum; media setup translates
   the carrier's direction and socket-provider identity explicitly.
2. Queues carry their actual producer types; task handles use `Task[None]`.
   Services, recorder and buffer use concrete instance contracts. The live voice
   runner supplies teardown's narrow `CallTurnRunner` port, avoiding a circular
   import of orchestration code. Handles and auth tokens never enter snapshots.
   STT queue payloads were still dictionaries at this milestone; the subsequent
   canonical STT milestone above replaces them with `VoiceTranscriptInput`.
3. Active media, termination-request and finalization states use owned enums.
   Predicate properties preserve existing read semantics. Intrinsic observations
   use strict booleans; counters and revisions reject invalid numeric inputs.
4. `CallSessionMetadata` owns campaign UUIDs, transfer destination and provider
   termination failure code. Media setup maps actual schema attributes, not
   `getattr` over string keys. Call creation receives UUIDs directly; event JSON
   retains the previous names/string representations. Transfer writes typed fields.
5. Registry removal checks object identity. Duplicate publication and unscoped
   ambiguity raise named `ValueError` subclasses, preserving existing catch
   compatibility. Finalization remains retryable after cancellation/failure.
6. Terminal reason resolution returns its non-null enum; finalization keeps one
   resolved value through awaited projections. Status mapping returns `CallStatus`.
   Transfer failure filing uses the immutable session org instead of relying on
   a local variable whose initialization was only implied by a boolean latch.

Executed QA:

- `CALL-SESSION-CONTRACT-QA-OK`: **88 assertions**, covering frozen identity,
  invalid/missing-field types, invalid handles/counters/states, excluded runtime
  data, real runner-port compatibility, independent mutable defaults, scoped
  lookup, duplicate/ambiguous refusal, stale removal, metadata/event projection,
  repeated finalization, cancellation, retry, setup rollback and live task drain.
- `CALL-SESSION-START-QA-OK`: **192 assertions** through the real
  `_handle_start_event` and rollback for all four carriers, both directions,
  with/without a canonical call. Real metadata/published-agent/DB-schema objects;
  provider setup deliberately fails. Provider I/O, DB resolution and the failed
  status write are substituted. Typed campaign mapping, opener selection and
  absence of leaked tasks are checked.
- `CALL-SESSION-CONTROL-QA-OK`: **49 assertions** through real termination,
  transfer-tool lookup, transfer completion and call-start projection. Covers
  accepted/rejected/exception/cancelled termination, idempotency and lock release,
  ASGI media close, typed transfer success/failure metadata, exact org filing and
  UUID campaign arguments. Carrier control and DB writes are substituted; real
  conversation/session/event/DB-schema objects are used.
- Existing carrier media **64** and setup **16** assertions pass after fixtures
  supply the now-required provider/direction. No other assertions were loosened.
- Two initial new-probe expectations were corrected against actual contracts:
  read-only properties raise `AttributeError`, not Pydantic `ValidationError`;
  queue teardown waits for acknowledgement and does not consume payloads. The
  task-drain fixture now supplies its owning consumer and acknowledgement.

Milestone review, in order:

1. DDD: live-session ownership remains in the pipeline. Existing domain voice
   config and socket provider types retain their owners. No module/socket imports
   of each other or framework-to-platform dependencies were introduced.
2. Architecture fit: reuses the current registry, locks, voice runner and task
   teardown. No parallel session manager, queue or persistence model added.
3. Data flow: authenticated metadata → typed session → registry/voice handoff →
   event/control fields → instance-owned removal; the changed constructors and
   cancellation branches are exercised with actual types.
4. Plan alignment: Pydantic replaces internal dataclasses without claiming
   whole-platform completion. Native carrier envelopes, browser/WebRTC sessions,
   STT events, remaining vendors and broader F0–F10 work stay open.
5. Readability/security/performance: remove unused `audio_profile`, untyped
   handles and UUID reparsing. No new casts, suppressions or network/DB operations.
   Registry identity is validated at publication/removal, not per audio sample.

Whole-platform Pyrefly: **810 errors / 4 suppressed**, down from 819, with the
existing two warnings. Sessions, finalization and media setup report zero errors;
the larger telephony voice/tool files still have 11 baseline diagnostics. Five
local type/import hooks pass. Full Python lint, documentation validation
(46 pages, 283 links, 1,154 modules, 6,155 docstrings, 47 diagrams), app import/
OpenAPI generation (245 paths, 564 schemas) and `git diff --check` pass.
Local pre-commit/pre-push telephony typing now includes sessions and finalization.
No migration, DB write, live provider call, deployment, commit or persistent test
artifact in this slice. These checks do not prove live voice quality or all
cross-worker lifecycle behavior.

### F7 progress: carrier and realtime audio lifecycle contracts

End goal remains the complete F0–F10 platform hardening scope. This continuation
extends media ownership through the carrier and realtime consumers; it does not
declare STT/TTS, telephony, or the platform complete.

Confirmed baseline:

- A normalized 100 ms realtime turn at 24 kHz emitted only 2,936 of the expected
  3,200 browser PCM bytes. Another 264 bytes remained in the converter after
  `TurnCompleteEvent`; interruption also retained a buffered tail.
- Carrier conversion ran in `tts_producer_task`, downstream of the native TTS
  completion signal. It could process chunks but never finalize the resampler.
- The call handoff was a dataclass holding unparameterized queues/tasks and
  unused plaintext config mappings. Recorder metadata guessed values from
  carrier dictionaries instead of consuming validated media contracts.

Implemented contracts:

1. `RealtimeManager` owns accepting/suppressed/closed output as an enum. The
   first nonempty chunk pins a validated source format for the turn. Supported
   rate, complete PCM samples and same-turn rate agreement are checked before
   conversion. No per-chunk format-model allocation after the first chunk.
2. Realtime completion flushes once before awaiting tool work. Interruption
   discards conversion state; teardown closes output before provider awaits.
   Late dispatch cannot reopen it. Playback accepts bytes before the recording
   tap runs, so rejected or empty output is never filed by that tap.
3. Carrier setup supplies `consumer_audio_format` to `TTSRealtime`; the same
   manager owns native completion, conversion tail and interruption reset.
   Removed the separate carrier converter and its duplicate session pointer.
   Both managers/media validate before initializer tasks are created.
4. The carrier producer sends ready bytes and records after accepted writes.
   Comfort audio uses the same target format. Recorder construction requires
   call identity and checked media instead of guessed defaults.
5. `VoicePipelineBundle` is frozen Pydantic with typed queues/tasks and
   `InstanceOf` runtime handles excluded from serialization/schema/repr.
   Removed unused STT/TTS config copies; TTS construction receives a normalized
   `TTSConfig`. STT's downstream dictionary envelope and the larger call-session
   model still require their own complete producer/consumer pass.

Executed function/data-flow QA:

- `REALTIME-AUDIO-LIFECYCLE-QA-OK`: 52 assertions across repeated 16/24 kHz
  turns, exact output duration, tail flush, no empty chunks, malformed/rate
  refusal, interruption, queue backpressure, recorder failure, delayed provider
  close, tool-completion/shutdown race, late dispatch and task cleanup.
- `CARRIER-AUDIO-LIFECYCLE-QA-OK`: 64 assertions. Real Hume native parser/factory
  and TTS queue manager feed actual Twilio, Plivo, Exotel and Vonage media
  serializers through an ASGI WebSocket. Three turns per carrier preserve
  byte count, recording PCM and duration. Comfort audio, rejected writes and
  resource cleanup are checked. Only native/network transport I/O is substituted.
  Plivo's dummy REST credentials fail its client constructor; no REST operation
  is exercised or claimed by this media-path check.
- `CARRIER-SETUP-CONTRACT-QA-OK`: 16 assertions through `init_voice_pipeline`
  using real published-agent/config/material models, with DB resolution and
  provider initializer I/O substituted. Includes native/consumer formats,
  shared queue identity, JSON/schema exclusion, frozen/invalid-handle refusal
  and invalid-format/cross-org-material rejection before initializer task creation.
- Initial probe fixtures omitted required realtime transcription/buffer fields
  and incorrectly named an agent status. The real models refused them; probes
  were corrected from source without weakening product validation. Silence
  comparison uses a fresh-converter baseline and one-LSB tolerance because the
  installed resampler emits that noise even with no prior audio.

Milestone review, sequentially:

1. DDD boundaries: adapter-native events remain in sockets; media conversion
   and its lifecycle are pipeline-owned. No vendor SDK enters domain contracts.
2. Architecture fit: reuse existing TTS/transcoder ownership; no second turn
   queue, worker, or platform policy is introduced.
3. Data flow: normalized native media → conversion → accepted output → recording
   is exercised, including completion/interrupt/refusal effects and teardown.
4. Plan alignment: adds runtime Pydantic/enum contracts and verifies their real
   consumers. Full F0–F10 scope, all vendors, persistence and live QA stay open.
5. Readability/security/performance: remove duplicate converters/config copies,
   use named state/error/limits, avoid new casts/suppressions, reuse per-turn
   conversion, and preserve recording as a secondary effect.

Whole-platform Pyrefly: **819 errors / 4 suppressed**, two warnings (previously
821 errors / 4 suppressed). Realtime remains clean; telephony setup/lifecycle
still have 13 baseline diagnostics outside the changed media contract. Broader
carrier/session dataclasses, STT dictionary events, realtime reconnect continuity
and response-ID correlation are next work, not hidden behind a green local gate.
No live vendor, audible browser/phone, DB write, deployment, migration, commit or
new persistent test artifact in this continuation.

Regression checks: browser media 118, Hume browser queue 18, TTS drain 9,
ElevenLabs native queue 167 and Cartesia native 202 assertions pass. All five
local type/import hooks, full Python lint, documentation/link/diagram validation,
application import/OpenAPI (245 paths / 564 schemas) and `git diff --check` pass.
No frontend source or public API schema change; frontend builds were not run.

### F7 progress: browser TTS media ownership

Confirmed RCA on 2026-09-08:

- The adapter's actual 48 kHz format and browser recorder's guessed 16 kHz
  metadata disagreed. Browser playback wrote those native bytes into a fixed
  16 kHz track. The helper/factory mismatch was reproduced without credentials.
- The existing SoXR streaming wrapper exposed process/reset but no finalization.
  A 100 ms, 48 kHz fixture converted to 2,936 bytes instead of 3,200 bytes at
  16 kHz because the filter retained the tail. Installed SoXR 1.0.0 and official
  documentation agree on `resample_chunk(..., last=True)` for final output.

Implemented:

- One frozen typed browser output-format value shared by TTS setup, playback,
  realtime output-rate selection and recorder headers. Deleted the vendor/config
  rate-guessing helper and its unused recorder input.
- An explicit optional consumer format on `TTSRealtime`. Native format remains
  separately observable. Browser setup normalizes config into `TTSConfig`; vendor
  identity no longer uses dictionary indexing in that function.
- Native chunk format must agree with the adapter and the converter's pinned
  source. Converted bytes feed both playback and recording. A full playback queue
  fails the runtime rather than silently discarding a converted chunk.
- Streaming resampler/transcoder finalization emits all buffered samples and
  resets for the next utterance. TTS completion waits for tail publication;
  interruption/failure resets without publishing the tail.
- Removed the extra task scheduling boundary between response dequeue and
  conversion. Completion cannot overtake that locally dequeued chunk. Identity
  transcoding now checks PCM alignment rather than bypassing validation.
- Completed native turns wait for queue acknowledgements directly. A resampler
  tail does not require a second provider poll timeout to finish; identity is
  rechecked after waits so an old drain cannot complete a replacement turn.
- Existing voice type hook now covers the transcoder and audio operations.

Executed verification:

- **118 function assertions:** six sample rates, three source codecs, carrier
  output codecs, exact durations, repeated/empty finalization, interruption reset,
  native format disagreement, overload refusal, recording/playback byte parity,
  and WAV header/frame metadata. Temporary recording files were cleaned up.
- **18 running-pipeline assertions:** resolved material → real Hume adapter →
  queue manager → converted consumer bytes and recording callbacks; three turns.
- **8 browser-setup assertions:** real browser initialization, Pydantic config,
  native/consumer format separation, synthesis and recording duration. Only vendor
  transport and unrelated DB/session-fact publication were controlled.
- **9 drain assertions:** final-tail acknowledgement, replacement-turn authority,
  cancellation without detached tasks, and rejection of a changed native format.
  Three converted Hume turns also pass with the normal two-second poll timeout.
- Existing native-output Hume pipeline (**18**), ElevenLabs (**167**), Cartesia
  (**202**), request routing (**67**), producers (**23**) and failure-path (**21**)
  probes pass. One generated conversion probe retained an obsolete unconverted
  fixture assertion; corrected the probe, not production behavior.
- Targeted TTS/transcoder/audio-ops/realtime type checks and all five existing
  type/import hooks pass. Whole-platform Pyrefly: **821 errors / 4 suppressed**
  (two warnings), down from 822. Browser orchestration still has **132** errors;
  WebRTC media has **15**. These modules are not claimed type-clean.
- Full server/CLI Ruff, documentation validation and diff whitespace checks pass.
  App import/OpenAPI generation passes (**245 paths / 564 schemas**). No deployed
  runtime or frontend/browser build was changed by this Python-only slice.

Sequential milestone review:

1. **DDD:** adapters still own native formats; pipelines own media conversion and
   browser format. No module/socket imports or framework dependencies added.
2. **Architecture:** existing factory, queue manager and resampler reused. No new
   vendor default, provider config, dependency or transport protocol.
3. **Data flow:** verified native bytes → conversion → playback buffer/WAV writer.
   Normal completion preserves filter tail; interruption drops it. Carrier and
   realtime finalization, generic adapter EOF and wider in-flight turn correlation
   remain required follow-up work, not established by these browser TTS probes.
4. **Plan:** advances the existing F7 source-to-consumer contract work. Does not
   redefine platform-wide success or claim all browser session types are clean.
5. **Readability/performance:** removed guessing and shared one format value;
   streaming conversion uses existing native SoXR without buffering entire audio.
   No DB, deployment, credentials, external state, or public API changes.

Next: complete carrier/realtime finalization and audio correlation contracts;
then remaining native speech/onboarding and the unchanged F0–F10 requirements.
Human voice acceptance and live Hume QA remain unrun.

Next, in dependency order:

1. **Done:** Replace conversation run-state dictionaries with an owned object. Trace
   `FrameworkConversationRunner.run/resume/_execute_context` through persistence,
   `PlatformToolExecutor`, `AgentRunTranscriptBridge`, and voice/durable producers.
   Type the shared command/message identity separately from persisted content.
2. **Done:** Type `ExistingConversationModel.current_context` and conversation helpers with
   the actual context contract. Preserve raw resume-history semantics: do not
   replace `context.messages` with the enriching/filtering `get_messages()` API.
   Preserve last-message identity updates after resumed tool-result persistence.
3. **Done:** Resolve the 11 telephony provider/credential construction diagnostics
   through module config → pipeline translation → socket factory → call/number
   clients. Expanded caller/import coverage is recorded above; native telephony
   wire schemas remain in the corresponding F3–F10 provider flow.
4. Finish remaining caller payloads and registered-tool context contracts.
   Built-in title/summary and one-shot worker contracts are locally verified above.
   Interaction/context metadata and transcript duration/outcome fields are verified
   above. Session hydration is now verified; next type producer-specific metadata
   and tool content. Validate known fields at their owner, preserving live resource
   identity and existing wire shapes rather than validating only a final projection.
   Finish prompt-only background execution identity, remaining memory storage,
   and swarm caller contracts; preserve all
   eight native adapter gates. Then continue F3–F10's provider data-flow order.

The existing SOR mapped-command extra annotation also has a confirmed Pyrefly
`bad-override` diagnostic; retain it in platform cleanup rather than suppressing it.

### Completed: recording disclosure, remaining contract in A1

- `RecordingDisclosureState` owns the four existing notification values.
  A narrow structural port lets browser and carrier sessions use the same
  notification functions without importing each other's concrete session model.
- Producers, notification transitions, and WebSocket replies retain the existing
  `recording_consent_state` field and string values. Recorder creation still
  precedes disclosure; denial, unavailable delivery, and delivery failure do not
  gate recording. Cancellation still propagates without granting disclosure.
- The browser policy entrypoint now states its existing non-null session
  precondition explicitly; no casts or diagnostic suppressions were introduced.
- QA passed: two real session types, all four states, 14 delivery cases including
  unavailable/failed/cancelled delivery, two WebSocket reply paths, and four
  recorder-initialization paths. Recorder/provider delivery were substituted;
  this is not live audio QA.

### Completed: opener and transfer lifecycle contracts, first part of A2

- Telephony-owned enums retain all four opener states and six transfer states.
  Opener commands now accept `CallOpenerDeliveryOutcome` instead of an `accepted`
  boolean; transfer commands accept `CallTransferOutcome`. All current producers
  and lifecycle writers use the owning enums.
- SQLAlchemy 2.0.45 non-native enum mapping keeps both columns `VARCHAR(32)`.
  Existing defaults, stored values, and the opener check constraint are unchanged;
  no new SQL constraint or PostgreSQL enum is created. ORM validation rejects
  unrecognized state values instead of treating them as a successful outcome.
- Read-only preflight against the active development DB found zero telephony
  call rows. There were no historical state values requiring a conversion there.
  Other deployments still need historical-value preflight before rollout.
- QA passed: 24 string-storage round-trips using the actual SQLAlchemy column
  processors over isolated SQLite storage; PostgreSQL type rendering and Alembic
  type comparison show no type change. This does not replace a full PostgreSQL
  migration/constraint test. No migration was generated or applied.
- Real lifecycle functions and ORM/Pydantic objects passed eight opener and 30
  transfer transitions with repository/transaction I/O substituted. Duplicate
  outcomes remain idempotent, incompatible outcomes are refused, and an unknown
  transfer cannot start another send. Invalid outcome/failure-code combinations
  and missing call authority were also checked.
- All 24 public state combinations serialize to existing values. Console types
  were regenerated from the current application on an isolated loopback server
  with lifespan startup disabled and dummy infrastructure config. Regeneration
  also refreshed the already-existing SOR `from_issue`/`to_issue` enum values; no
  SOR runtime code changed in this slice.
- The local voice type gate now covers disclosure and carrier session contracts;
  a separate local gate covers the clean telephony constants/models/schemas/
  services files. Larger pipeline/lifecycle files still have pre-existing typing
  debt. Full-project Pyrefly remains at 1,161 diagnostics, 19 suppressed.

Continuation checks: both local type hooks passed on their pipeline trigger paths;
full Python lint and documentation validation passed (46 pages, 252 links).
Console lint, TypeScript compilation, and Vite build passed; Vite still reports
its existing large-chunk warning. The isolated OpenAPI server was stopped after
generation. No temporary probe files were added to the repository.

Continuation milestone review: platform/vendor ownership is unchanged; canonical
states survive producer, lifecycle writer, ORM readback, and API projection.
Transaction scope and external-send authority are unchanged. The work follows
the A1/A2 split rather than claiming the remaining initiation/durable-dispatch
work is complete. The enum mappings add no dependencies or audio-frame work.

No carrier call, provider mutation, operator-data write, migration, deployment,
or commit was performed in these slices.

### Completed: call-initiation results, remaining contract in A2

- `OutboundCallResult` is a frozen telephony-owned contract. It retains UUIDs,
  the shared `OutboundAttemptState`, and the platform `TelephonyProvider` enum
  through the call pipeline. No socket-owned enum or SDK object crosses inward.
- All four consumers were updated: HTTP controller, durable agent tool,
  scheduled call action, and campaign voice dispatch. Only the existing HTTP,
  tool metadata, and scheduled result boundaries serialize strings. The public
  response keys, nulls, status values, and identifier formats are unchanged;
  no endpoint schema or generated-client change is required for this slice.
- `CallInitiationMarker` names the four existing interim values written to
  `provider_status`; writers and campaign recovery share those names. The column
  remains unrestricted text for native carrier status. The rejection fallback
  is a telephony-owned constant. No DB validation or stored-value change occurs.
- A sender captures its already-resolved phone number as a string before the
  closure, removing one nullable-closure diagnostic without casts or suppression.
- Retry still raises `OutboundRetryRequested`; it does not become a returned
  acceptance/rejection. Unknown replay and cancellation behavior are unchanged.

Executed QA:

1. All 28 outbound-state/provider combinations retained identical JSON and
   round-tripped into typed results. Frozen result mutation was refused.
2. Thirty consumer cases covered accepted, terminal, and unknown results with
   and without provider references; stable HTTP idempotency identity; exact
   agent revision; campaign attempt identity; scheduler late-occurrence output;
   retry and cancellation propagation through the three durable consumers.
3. Seven producer/durable cases exercised `VoiceService` and the actual outbound
   execution functions: accepted, rejected, unknown, retryable, two unknown
   replays with no new provider send, and cancellation recovery before propagation.
   Provider send occurred outside the config-read transaction. Dependency
   resolvers and DB/provider I/O were substituted; no real carrier was contacted.
4. Actual ORM objects and lifecycle functions passed nine projection/replay
   transitions and five campaign recovery cases. Terminal events were filed and
   nudged once; late acceptance preserved an existing native terminal status.
   Recovery queries retained org, campaign, contact, and attempt filters.
   Repository/transaction I/O was substituted; this is not PostgreSQL crash QA.

Type baseline: this slice reduced full-project Pyrefly from 1,161 to 1,160
diagnostics (19 suppressed, unchanged). The seven-file telephony type gate passes
and now includes HTTP, scheduler, and agent-tool result consumers. Three
pre-existing diagnostics remain in the broader call-control/campaign pair:
`_InlineDurableContext` lacks the unused `await_event` protocol member; the factory
expects vendor-name literals rather than the platform enum value; campaign DTO
organization identity is optional. Keep these visible for their owning protocol,
factory, and product-contract slices; no new ignores were added.

A2 milestone review, in order:

1. DDD ownership: shared outbound state is reused; telephony owns its result and
   interim markers. Native provider values remain adapter-owned/open at storage.
2. Architecture fit: no new services, execution authority, package, or dependency.
3. Data flow: receipt → typed result → four consumers → unchanged wire/persisted
   projections. Intent, transaction, callback, and retry boundaries are unchanged.
4. Plan alignment: completes A2 only. Broader campaign boolean/result contracts
   and tool error payloads remain in the ordered backlog, not silently included.
5. Maintainability/performance: no result-key lookups or status-string comparisons
   remain in initiation consumers; one small model validation per initiation,
   no per-frame work, no extra queries, and no new diagnostic suppressions.

Final checks: full Python lint, both local type hooks, documentation validation
(46 pages, 252 links), and `git diff --check` passed. No UI source or endpoint
schema changed in this continuation, so console/widget builds were not repeated.
No deployment, DB change, outbound call, or commit was performed.

### Completed: GitHub and Freshdesk curated inputs, first part of A3

- GitHub issue search and pull-request listing now use `GitHubQueryState`.
  Its `all` member is a query choice, deliberately separate from entity state.
  Existing case/whitespace normalization, default `open`, and query strings
  are preserved.
- Freshdesk search/create/update use vendor-owned status and priority enums,
  translated through vendor-owned integer code enums. The existing value set
  matches the current official Ticket Properties table. Optional search/update
  empty strings still mean omission; whitespace-only values remain invalid.
  Create defaults and unknown native values in responses are preserved.
- The five changed tool inputs advertise enum choices through the registry,
  Agent tool projection, standalone framework tool specification, and Bedrock
  tool formatting. No platform/SOR enum, SDK type, or new dependency was added.
- Intentional error-boundary change: malformed choices now return the existing
  `tool_input_invalid` result before credential resolution. Previously they
  reached handler validation and returned `state_invalid`, `status_invalid`,
  or `priority_invalid`. Tool names, scopes, effects, successful outputs, and
  wire values are unchanged. The integration reference records the new boundary.

Executed QA used the actual registry, Pydantic models, executor, tool projections,
origin-bound request builder, and mutation sender. Grant/auth resolution, vendor
transport, and durable receipt persistence were substituted:

1. GitHub: 24 valid requests, 16 pre-auth refusals, eight schema projections,
   and both default choices. `all` omits the search state clause but remains
   the PR-list query value.
2. Freshdesk: 192 request combinations across search/create/update, 40 pre-auth
   refusals, 12 schema projections, eight optional-value paths, eight native
   response projections, and create defaults. All status/priority combinations
   retain the exact numeric payload/query values.
3. Freshdesk made 137 durable-attempt dispatches, exactly one per successful
   mutation invocation. Organization/owner operation identity, idempotency
   header, and request fingerprint were checked. Retrying the same tool-use
   owner with normalized-equivalent inputs retained the same attempt spec.
   This validates the dispatch contract, not persisted receipt deduplication or
   worker-crash recovery; those execution authorities were not changed.

A3 milestone review, in order:

1. DDD ownership: query choices and numeric codes belong to each curated vendor;
   canonical platform/SOR states and raw vendor response fields remain separate.
2. Architecture fit: the existing registry/model/handler pattern owns validation;
   no global choice hierarchy, service, schema table, or new execution lane.
3. Data flow: schema → input validation → enum → unchanged request → unchanged
   result. Invalid inputs cannot resolve credentials or dispatch a vendor send.
4. Plan alignment: GitHub and Freshdesk only; GitLab/Intercom remain next. This
   does not claim the wider A3 result-object or A4 error-contract work is done.
5. Maintainability/performance: removed late string-choice helpers and replaced
   numeric magic values with named codes. No additional queries, I/O, retries,
   casts, suppressions, or frame-path work.

Checks: full Python lint, all three scoped local type hooks, documentation
validation (46 pages, 252 links), and `git diff --check` passed. The new local
curated-tool hook covers these two clean vendor files and runs when their shared
integration/tool boundaries change. Full-project Pyrefly is still not clean:
1,158 diagnostics, 19 suppressed (two fewer nullable response-map diagnostics).

No live vendor operation, DB write, deployment, migration, UI source change, or
commit. These are executed function/contract probes, not live-agent QA or new
human-reviewed behavioral coverage. Console/widget builds were not repeated;
the dynamic tool schemas changed, not a static endpoint/client type. No probe
files were added to the repository.

### Completed: GitLab and Intercom closed choices, continuation of A3

- GitLab query inputs now use distinct issue and merge-request enums. Both
  preserve case/whitespace normalization and default `opened`; `all` still
  omits the state query parameter. `merged` cannot enter issue search. Unknown
  vendor response states remain open data rather than being revalidated as
  query choices. The vendor's additional `locked` MR filter remains outside
  the existing curated subset; adding it is not part of this typing refactor.
- Intercom search state is validated before credential resolution and contact
  lookup. Invalid state now yields `tool_input_invalid`, including when a
  missing contact previously short-circuited the late state validation. Empty
  optional input still omits the filter; unconstrained search is still refused.
- Intercom's internal reply function accepts `IntercomMessageType`, not an
  arbitrary string. Reply construction, durable dispatch, returned visibility,
  and transcript speech-part filtering use its comment/note choices. The public
  required `visible_to_customer` boolean and its existing input normalization
  are unchanged. Replacing that public field requires a deliberate compatibility
  change; it was not silently bundled into this slice.
- Vendor choices were checked against official GitLab v4 documentation and the
  pinned Intercom 2.11 reference. No new vendor permission, endpoint, API version,
  response field, or provider capability was introduced.

Executed function/contract QA:

1. GitLab: 28 valid numeric-project requests, two default requests, 22 pre-auth
   refusals, and eight schema projections. Combined text/labels/assignee and
   target-branch options retain their exact query encoding. All accepted state
   forms round-trip through Pydantic JSON to the same enum member.
2. GitLab: 56 named-project variants hit the pre-existing transport refusal
   described below. They are baseline-failure evidence, not successful vendor
   requests. The original HEAD `_project` function and current function produce
   identical paths; the common guard and request builder have no diff.
3. Intercom: 36 state/contact search flows, 19 pre-auth refusals, six omitted/
   null/empty-state paths, and four schema projections. Invalid states never
   dispatch even the first contact lookup. Native unknown response state is
   preserved, and valid missing contacts still return an empty result.
4. Intercom: eight mutation dispatches retain comment/note wire values, explicit
   visibility, author, owner identity, idempotency headers, and request
   fingerprints. The same artificial tool-use identity produces the same request
   fingerprint for an equivalent private reply/note. Two transcript projections
   verify opening/comment/note visibility, ignored state/unknown parts, and the
   existing 50-part bound.

These probes execute actual models, registry, executor, request construction,
sender, and projections with grant/auth, vendor, and durable persistence I/O
substituted. They do not establish live provider operation, persisted receipt
deduplication, crash recovery, or human-reviewed product behavior.

Continuation milestone review, in order:

1. DDD ownership: GitLab query sets are separate; Intercom owns its native state
   and message type. No SOR/framework/platform vocabulary was borrowed or merged.
2. Architecture fit: validation stays in the existing input models; the private
   reply function consumes a precise enum. Public schemas still project from
   the registry rather than a second stored catalog.
3. Data flow: valid values retain request and response semantics; malformed
   states fail at the model boundary. The GitLab name-to-egress mismatch is
   explicitly open rather than hidden behind handler-only mocks.
4. Plan alignment: completes the four initially identified vendors' closed-choice
   inputs. Broader result objects and remaining vendor contracts are still
   backlog. At that milestone A4/A5 were next after the transport issue; the
   later all-vendor clarification now supersedes that order with F0–F10.
5. Maintainability/security/performance: removed late string-state validation;
   reply kind cannot be an arbitrary internal string. No new query, retry,
   resource lifetime, broad enum superclass, cast, or suppression. Per-vendor
   normalization remains local rather than coupling independent vendors.

Checks: Python lint, documentation validation, and the expanded four-vendor
local type hook pass. Full-project Pyrefly remains at 1,158 diagnostics with 19
suppressed; these two vendor files are clean before and after the change.
No DB changes, migration, deployment, external message, commit, or persistent
probe file. Console/widget sources and static endpoint schemas are unchanged.

### Open finding: GitLab named-project requests fail at the HTTP boundary

Priority: P2. This is a pre-existing product-path defect, not an enum regression.

- Source: `vendors/gitlab/tools.py::_project` correctly percent-encodes a project
  path, e.g. `acme/api` → `acme%2Fapi`, for GitLab's project-ID path parameter.
- Rejection: `GuardedVendorClient._build` creates an `HttpEgressRequest`; its
  destination policy reaches `common/http_egress.py::_validated_path`, which
  categorically refuses `%2f` and `%5c`. The executor returns
  `vendor_request_invalid` before transport send. Numeric IDs pass construction.
- Impact: all six GitLab tools share `_project`, so named-project operation is
  blocked at the shared transport boundary. Numeric-ID request construction is
  proven; live GitLab access was not exercised here.
- Why this matters for QA: a handler-only mock accepting the encoded path cannot
  catch the incompatible downstream path policy. Keep the real request model
  in the next fix's function/data-flow probes.

Proposed next slice, separate from typing:

1. Define an explicit encoded-resource-ID contract for the GitLab route. Keep
   origin/base-path authority, traversal refusal, redirect checks, and credential
   pinning intact; do not globally allow encoded separators or double-encode
   paths to sneak through the existing guard.
2. Implement the adapter/HTTP-boundary translation only after the security-sensitive
   contract is agreed. Preserve all other consumers' existing path restrictions.
3. Exercise group/subgroup/numeric IDs across all six tools through the actual
   request model, plus traversal, encoded backslash, double-encoding, foreign
   origin, and credential-boundary refusals. Check mutation fingerprints/replays.
4. Run live read-only GitLab QA if a configured installation is available; real
   mutations need separate authority. Continue with the current F0–F10 schedule;
   A4/A5 contracts accompany each flow rather than forming a disconnected sweep.
