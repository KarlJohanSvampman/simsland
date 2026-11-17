# Conversation Protocol Layer (CPL) — implementation plan

Status: plan, nothing built yet. It answers section 20 of the CPL specification ("produce an implementation design
before coding") and is written against the code as it is on 2026-11-13 (`master` @ `2ea9f8e`).

The short version: Simsland already has most of what the specification describes. It's spread across about 15
modules that grew one live bug at a time. CPL should **pull those modules together behind a single owner and a
single protocol**, not sit alongside them as a second conversation system. Most of the work is moving
responsibilities into one place and replacing per-tick polling with timers. Very little is new behaviour.

---

## 1. What exists today (architecture mapping)

### 1.1 The current conversation pipeline

```
 character decision (brain/llm_brain.think, on a cognition worker)
   └─ decision["speech"] = {target, speech_act, topic, utterance, subject, conversation_type, social, intent, ...}
        │  returns as a `decision_ready` event (brain/cognition_actor.py), re-validated on the tick thread
        ▼
 systems/action_router.py::apply_speech()              ← the de-facto "intent processor + router", ~400 lines
   ├─ expressions (one-way remarks)                      systems/expressions.py
   ├─ repeat filter                                      systems/speech_repeat.py
   ├─ floor discipline (don't talk over the holder)      systems/conversation_floor.py::blocks
   ├─ volume                                             conversation_floor.repeat_volume, confrontations
   ├─ earshot / walls                                    systems/conversation_reach.py
   ├─ phone reachability → voicemail                     systems/personal_items, systems/inbox.py
   ├─ NEW conversation → listener interest (LLM call)    systems/conversation_interest.py  (decline = no conv at all)
   ├─ get_or_create_conversation / add_message           brain/conversations.py  (world["conversations"])
   ├─ per-participant goals (LLM pick)                   systems/conversation_goals.py
   ├─ side effects per line: ledger impact, memories, reactions, relationship, analysis, reflections, opinions
   └─ emit heard_speech → wake listener                  core/event_handlers.py → cognition_scheduler
 brain/conversations.py::add_message
   ├─ conversation_floor.on_message   (who holds the "ball", reply windows, unnoticed/unanswered)
   ├─ conversation_outcome.on_message (purpose = first question; yes/no/later; MAX_LINES=6, MAX_TICKS=240)
   ├─ conversation_reach.on_line, tone/dynamics, blush, observations
   └─ emit conversation.message
 ending: conversation_floor._end / conversation_outcome.end / idle timer (IDLE_TIMEOUT_SECONDS=120)
   └─ emit conversation.ended → systems/conversation_archive.py
        └─ bg_llm: llm/conversation_tags.py reads the whole transcript
             └─ social/discourse.py applies it → issues, confrontations, contracts, initiative, standing, rumours
```

Other entry points: `apply_speech_to_group` (3+ people), `systems/scripted_conversations.py` (pre-written calls
and texts), `systems/incidental_speech.py` (announce / inquiry / micro-request with no conversation), phone texts and
email through `systems/inbox.py`, and the standalone `middleware/simsland_mw` service. That service gives every
conversation back to the built-in brain because its Phase 1 can't speak yet.

### 1.2 Spec component → existing code

| CPL component | Today | Gap |
|---|---|---|
| Intent Processor | `apply_speech()` + the `speech` part of the decision envelope | Takes **dialogue**, not intent. No `conversation.initiate` without an utterance. |
| Conversation Manager | `brain/conversations.py` (`world["conversations"]`), `conversation_archive.py` | State is a loose dict (`active`, `floor`, `outcome`, `history`). No explicit state machine, no PENDING/PAUSED. |
| Participant Manager | `conversation_reach`, `phone_is_usable`, `_work_busy_until_tick`, `conversation_interest`, `LISTENING_ACTIVITIES` | Availability checks are scattered and inline. A declined invitation leaves no record. |
| Message Router | Inline in `apply_speech` (in person / call / voicemail); `inbox.py` for texts | One path per medium, written separately. |
| Protocol Processor | `speech_act` (20 values, `SPEECH_ACTS`), `conversation_floor.classify`, `conversation_outcome.read_answer` (regex yes/no/later) | Meaning is **guessed from text after the fact**. No references (`response_to`), no request ids. |
| Context Manager | `context_builder.build_active_conversations` (full history), `compress_conversation_memory` | Each turn re-renders the whole conversation inside the **full decision prompt**. |
| Resolution Manager | `conversation_floor` (ignored/unanswered), `conversation_outcome` (resolved/timed_out), idle timer | Three modules can end a conversation, each with its own reasons and caps. Hard caps of 6 lines / 4 sim-minutes. |
| World Event Adapter | `core/event_bus` events: `speech_spoken`, `social_line`, `heard_speech`, `conversation.message`, `conversation.ended` | Events are fine-grained but untyped. No request/commitment events. |
| Memory Adapter | `dialogue_memory.remember_dialogue`, `store_conversation_memory`, `conversation_archive._rewrite_memories` | Every line becomes a memory, with no epistemic status. |
| Requests & commitments | `social/contracts.py` (proposed → accepted → active → fulfilled/violated …), `_play_plans`, intentions | Contracts are only made **after** the conversation ends, from AI tags. No per-request lifecycle during the conversation. |
| Knowledge propagation | `social/rumours.py` (claims about people with `information_status`, per-listener confidence), `brain/opinions.py` | Rumours already model "heard ≠ believed" well, but only for claims about third parties and only after the conversation. |
| Contact network | `systems/contacts.py` (`c["contacts"]`), `brain/relationships.py`, `systems/phone.py` | Fine. CPL reads from these and doesn't duplicate them. |
| Scheduling | `core/scheduler.py` (durable sim-time timers on the world) | `conversation_floor.tick` still runs **every tick** (`sim_loop.py:525`). |
| Async model calls | `core/work_queue.py` (Redis Streams), `workers/cognition.py`, `workers/bg_llm.py`, `llm/llm_gate.py` priorities | Fine. CPL reuses these. |

### 1.3 Where CPL sits

CPL is a new package, `backend/cpl/`, that runs **in the simulation core process** (`SIM_ROLE=core`/`all`) under the
world lock, the same as `cognition_actor`. It must run there because conversation state has to change in step with
positions, activities and phone state, and the core owns all of that. The API gateways only reach CPL through
`core/commands.py` (debug and admin routes).

```
 cognition worker ──decision_ready──▶ cpl.intents ──▶ cpl.conversations (state machine, store)
                                            │                 │
                                            ▼                 ├─▶ cpl.router ──▶ delivery: perception/earshot, phone, inbox
                                     cpl.participants         │                     └─▶ wake recipient (turn request)
                                     (availability,           ├─▶ cpl.resolution ◀── core.scheduler timers
                                      contacts, channel)      ├─▶ cpl.context (incremental context object)
                                                              └─▶ cpl.adapters ──▶ event_bus: cpl.* events
                                                                                    ├─ existing per-line side effects
                                                                                    ├─ social/contracts, rumours, discourse
                                                                                    └─ memory, relationships, archive
```

---

## 2. Conflicts between the specification and Simsland (decide before coding)

These are the points where following the spec literally would clash with how Simsland works. Each has a
recommendation.

**C1. Persistence: relational tables vs. the world blob.** The spec asks for six Postgres tables as the
authoritative store. Simsland's authoritative state is the in-memory world dict. A background thread writes it to
Postgres every `PERSIST_EVERY_TICKS = 15` ticks (`core/world_state.py`), and `docs/distributed_architecture_plan.md`
Step 4 will later replace that with per-entity records. Writing conversations to tables transactionally while the
rest of the world is snapshotted causes **split-brain after a crash**. For example, the world comes back 15 ticks
old, but the tables still hold a commitment to buy groceries, made in a conversation the restored characters were
never in.
*Recommendation:* the authoritative CPL state lives on the world (`world["cpl"]`) behind a `ConversationStore`
interface, so it is snapshotted together with everything it refers to. The interface is the seam for Step 4.
Finished conversations and their messages also go to **append-only Postgres tables** (the spec's schema). Those
rows are written idempotently, keyed on `message_id`/`conversation_id`, and are used for history, debugging and
metrics. They are never read back as live state. "Survives a restart" then means "comes back consistent with the
world", which is the guarantee every other system in Simsland has.

**C2. "No global tick".** CPL itself polls nothing. Every deadline is a `core.scheduler` timer, owned by
`cpl:<conversation_id>` and keyed by purpose (`reply`, `invite`, `idle`, `pause`). The existing per-tick
`conversation_floor.tick` and `conversation_outcome.tick` are removed when their logic moves into timers (Phase 2).
This is Step 1 of the distributed plan, applied to conversations.

**C3. Structured output vs. the model we actually run.** Simsland runs `llama3.1` 8B through Ollama, and
`llm_brain` already falls back to a compact line-based envelope (`_parse_compact_envelope`) because full JSON from
that model is unreliable. Asking it for the spec's nested envelope (`payload.semantic.subject/predicate/object`,
`response_to`, emotional vectors) on every line would make things worse.
*Recommendation:* the model emits a **small set of fields**: act, which pending item it answers, the answer
(accept / reject / defer / counter / …), stance, emotion + intensity, the line, and next step (continue / leave / pause).
CPL builds the full protocol envelope. `message_id`, `sequence_number`, `response_to`, `request_id` and timestamps are
never generated by the model. The model never sees ids, only short labels ("Q1", "R1") that CPL maps back.

**C4. Who decides whether to accept a conversation.** Today a separate LLM call
(`conversation_interest.check_conversation_interest`) runs **before** any conversation exists, and a decline leaves
no record at all. The spec says invitation ≠ acceptance and that a decline still resolves a conversation.
*Recommendation:* create the conversation in `PENDING` first, then ask. The interest check becomes the recipient's
**invitation decision** (Mode B, same prompt, new output contract). Decline → `RESOLVED/REQUEST_REJECTED` with an
outcome. No answer → `EXPIRED`. Any reply, including "What do you want?" or "No.", → `ACTIVE` (invariant 7).

**C5. One sitting = one conversation.** `conversation_archive.py` deliberately never resumes a conversation later.
The next talk between the same people is a new conversation. The spec's PAUSED/resume fits inside that rule:
a pause is a gap **within** a sitting (a phone rings, a child calls out). It has a pause deadline from the timeout
policy. If the pause outlives it, the conversation resolves `INTERRUPTED`, and any unresolved requests carry over to
the next conversation through the request store (C7). Keep the archive's rule.

**C6. Hard caps.** `conversation_outcome.MAX_LINES = 6` and `MAX_TICKS = 240` exist because conversations used to
run forever. The spec wants purpose-dependent policies. These caps become **per-purpose, per-channel defaults** in
`cpl/policies.py` (casual chat might allow 8 lines / 5 minutes, negotiation 20 lines / 15 minutes, emergency gets a short
reply window). They are applied as a "wind-down" nudge (`RESOLVING`) before a hard stop, so conversations still
always end (invariant 15).

**C7. Commitments vs. social contracts.** `social/contracts.py` already has a commitment lifecycle with
`origin_conversation_id`, revisions and disputed violations. A second commitment store would duplicate it.
*Recommendation:* CPL owns **requests and proposals only while they are being negotiated**
(`world["cpl"]["requests"]`). They can outlive a conversation as `open`/`deferred`, which satisfies invariant 9. When
one is accepted, CPL emits `cpl.commitment_created`. A handler in `social/contracts.py` turns that into a contract
with one term (`responsible_party`, `obligation`, `deadline`, `conditions`), and `brain/intentions` gives the
responsible character the intention. Completion and failure stay with contracts and the action systems, which
already check terms. CPL's `commitment_id` *is* the `contract_id`.

**C8. Knowledge and belief.** `social/rumours.py` already models "heard ≠ believed" for claims about people (status,
per-listener confidence, transmission chain). CPL should not create a second belief store. It records the
**epistemic event** on the message (asserted / acknowledged / confirmed / disputed / rejected, plus the listener's
own stance once they reply) and publishes `cpl.information_shared`. Rumours handles claims about third parties.
`brain/memory` stores the rest as source-attributed memories ("Ana told me the bill is due Monday") and not as
facts. This brings forward, for structured lines, what is currently only worked out after the conversation from AI
tags.

**C9. Post-conversation AI tagging.** `conversation_archive` + `llm/conversation_tags.py` read every finished transcript
with the model, and `social/discourse.py` turns the result into issues, confrontations, contracts and rumours, with "no
programmatic fallback". That keeps working unchanged through Phases 1–4. CPL's structured record goes into the tag
prompt as ground truth (who asked what and what was answered). In Phase 5 the tag call can be **skipped** for
conversations whose structure already covers everything it would add (purely structured exchanges, no third
parties, no conflict).

**C10. The standalone middleware service (`middleware/simsland_mw`).** It is a *decision* middleware (one character,
pick an option). CPL is a *conversation* middleware between characters. They don't overlap. Today simsland_mw gives
conversations back to the built-in brain (`README`, "Safety valves"). Once CPL exists, its turn contract (section 6)
is the interface simsland_mw implements to get conversations back (its Phase 2). No change to simsland_mw is needed
for CPL Phases 1–4.

**C11. Concurrency is easier than the spec assumes.** Since `cognition_actor` (distributed plan Step 3), every
decision is applied on the tick thread under the world lock, and API mutations are serialized as commands to the
core. CPL state changes therefore already run one at a time. The spec's optimistic concurrency is not needed now.
Sequence numbers are assigned under the lock. The **idempotency** requirement is still real: `work_queue` delivers at
least once (`claim_idle_ms`), and a cognition result can arrive twice. Section 9 covers this.

**C12. Rewriting `apply_speech()`.** It holds years of live fixes (addressee resolution, unheard lines, voicemail,
repeat filter, the "answering" exemption). CPL must not lose any of them. These checks move into
`cpl.participants`/`cpl.router` **one at a time, in shadow mode first**, each with the test that pinned the original
bug (`tests/test_talking.py`, `test_unheard_speech.py`, `test_speech_repeat.py`, `test_conversation_outcome.py`, …).
The per-line side effects (ledger, memories, reactions, analysis, reflections) don't move. They become subscribers to
`cpl.message_delivered`.

---

## 3. Module and directory structure

```
backend/cpl/
  __init__.py            public API: submit_intent(), submit_turn(), interrupt(), leave(), get(), CPL_MODE
  config.py              CPL_MODE = off | shadow | on (env + world["cpl"]["mode"]), protocol version
  protocol/
    envelope.py          Envelope, MessageType, ControlType (pydantic v2, model_dump() → plain JSON for the world)
    payloads.py          Statement, Question, Request, Proposal, Response, Argument, EmotionalStatement, Leave, Interrupt
    intents.py           InitiateIntent, TurnDecision (the AI-facing contracts, section 6)
    codec.py             compact model output <-> TurnDecision; label maps (Q1/R1 <-> ids)
  model/
    conversation.py      Conversation, Participant, ContextObject, Outcome (dataclasses over dicts)
    requests.py          TrackedRequest, Proposal lifecycle
    enums.py             ConvState, ResolutionReason, Purpose, Channel, GenerationMode, EpistemicStatus
  state_machine.py       transition table + transition(conv, event) -> (new_state, effects); pure, no world access
  store.py               ConversationStore protocol; WorldStore (world["cpl"]); ArchiveSink (Postgres, append-only)
  intents.py             Intent Processor: validate, resolve recipients, create/reuse conversation
  participants.py        availability(world, char, channel, urgency) -> Availability; contact/channel access
  router.py              deliver(envelope) per channel: in person (reach/perception), call, text/email (inbox)
  processor.py           validate a TurnDecision against the conversation: references, allowed acts per state
  context.py             incremental ContextObject updates; summary refresh policy
  resolution.py          progress assessment, resolution reasons, timer handlers
  policies.py            timeout / length / wind-down policy table by purpose × channel × urgency
  generation.py          generation mode selection (A/B/C); Mode A templates (reuse systems/incidental_speech lines)
  turns.py               builds the compact turn request for the cognition queue; applies the result
  adapters/
    legacy.py            mirrors CPL state <-> world["conversations"] while old readers still exist
    events.py            World Event Adapter: cpl.* events on core.event_bus (typed, section 7)
    memory.py            dialogue_memory / store_memory with epistemic status
    knowledge.py         rumours / opinions bridge
    contracts.py         commitment_created -> social/contracts
  metrics.py             counters: llm calls, tokens, mode mix, latency, end reasons (exposed on /admin)
backend/api/cpl.py       read-only debug routes (+ @command admin actions: force-resolve, inject interrupt)
backend/tests/test_cpl_*.py
scripts/migrations/cpl_001_archive.sql
```

Each component takes its collaborators as arguments (store, clock, scheduler, availability, publisher). The state
machine, processor, context and policies are pure functions over plain data, so they can be tested without a world.
This matches the spec's "independently testable" requirement and the in-process bus + virtual clock testing model
in the distributed plan.

---

## 4. Data models

Storage is plain JSON on the world. Pydantic is used at the boundaries (validating model output and API input) and
for typing. Everything stored is `model_dump(mode="json")`.

```python
# cpl/model/enums.py
class ConvState(str, Enum):
    CREATED = "created"; PENDING = "pending"; ACTIVE = "active"; PAUSED = "paused"
    RESOLVING = "resolving"; RESOLVED = "resolved"; EXPIRED = "expired"
    # INTERRUPTED is a flag on ACTIVE (conv.interruption), per the spec's own preference

class ResolutionReason(str, Enum):
    MUTUAL_AGREEMENT = "mutual_agreement"; REQUEST_FULFILLED = "request_fulfilled"
    REQUEST_REJECTED = "request_rejected"; QUESTION_ANSWERED = "question_answered"
    TOPIC_EXHAUSTED = "topic_exhausted"; PARTICIPANT_LEFT = "participant_left"
    ANGRY_WITHDRAWAL = "angry_withdrawal"; INTERRUPTED = "interrupted"; TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"; CONFLICT_ESCALATION = "conflict_escalation"; ABANDONED = "abandoned"
    DECLINED = "declined"            # invitation answered "no" (spec: RESOLVED with an outcome)
    NO_ANSWER = "no_answer"          # invitation never answered (-> EXPIRED)

class Channel(str, Enum):
    IN_PERSON = "in_person"; CALL = "call"; TEXT = "text"; EMAIL = "email"; SOCIAL = "social"

class Purpose(str, Enum):
    INFORMATIVE, QUESTION, REQUEST, PRAGMATIC, NEGOTIATION, SOCIAL, EMOTIONAL, CONFLICT,
    PERSUASION, COORDINATION, GOSSIP, SUPPORT, ROMANTIC

class EpistemicStatus(str, Enum):
    ASSERTED, REPORTED_CLAIM, ACKNOWLEDGED, CONFIRMED, DISPUTED, REJECTED, UNANSWERED

class GenerationMode(str, Enum):
    STRUCTURED = "A"; NATURAL = "B"; REASONING = "C"
```

```python
# cpl/protocol/envelope.py
class Envelope(BaseModel):
    protocol_version: Literal["1.0"] = "1.0"
    message_id: str                       # "msg_" + uuid7, or derived (section 9)
    conversation_id: str
    sender_id: str
    recipient_ids: list[str]
    message_type: MessageType             # statement|question|request|proposal|response|argument|
                                          # emotional_statement|control
    control: ControlType | None = None    # accept|decline|leave|interrupt|pause|resume|transfer|close
    world_ts: float                       # core/clock.now_ts() (sim seconds)
    server_ts: float                      # time.time(), for watchdogs and metrics only
    sequence_number: int                  # assigned by the store, under the world lock
    payload: dict                         # one of payloads.* (validated by message_type)
    content: str | None = None            # the rendered line, if any (Mode B/C, or a Mode A template)
    emotion: Emotion | None = None        # {primary, secondary, intensity, communicative_intent, stance}
    audience: Audience                    # {addressed: [...], overheard_by: [...], private: bool}
    metadata: Metadata                    # {priority, requires_response, generation_mode, source_decision_id,
                                          #  causation_id, legacy_speech_act}
```

Payload models follow spec §4.2. The additions: every `Question`, `Request` and `Proposal` gets an id
(`q_`, `req_`, `prop_`) when it is persisted. `Response.response_to` points at that id and never at a raw message id
the model would have to copy. `Response.response_type` is the spec's list plus `answer` (spec §10.3 uses it) and
`ignore`.

Mapping from today's `speech_act` (kept as `metadata.legacy_speech_act` so the existing analysis, ledger and tone code
still works without changes):

| speech_act | message_type | notes |
|---|---|---|
| question / ask | question | `expects_reply` from conversation_floor becomes `requires_response` |
| (request phrasing, micro_request) | request | today guessed from text; Phase 1 adds an explicit act |
| smalltalk, joke, compliment, flirt, brag, comfort, supportive | statement | purpose `social` / `romantic` / `support` |
| insult, challenge, defensive, dismissive | emotional_statement | stance `opposed`; purpose may flip to `conflict` |
| vulnerable, confession, apology | emotional_statement | |
| gossip, urgent_report | statement + `information` block | `epistemic_status = reported_claim`, subject = third party |
| lie | statement | `metadata.deceptive = true`; visible only to the speaker's own records (invariant 17) |
| argue | argument | existing `{topic, stance, move, target_argument_id}` fits `Argument` |
| awkward_silence | control `none` / acknowledge | no generation |

```python
# cpl/model/conversation.py  (stored at world["cpl"]["conversations"][conversation_id])
@dataclass
class Participant:
    character_id: str
    role: Literal["initiator", "participant", "moderator"]
    status: Literal["invited", "active", "paused", "left", "unavailable"]
    joined_at: float | None; left_at: float | None
    left_reason: str | None              # excuse | angry_withdrawal | unavailable | ...
    last_seen_seq: int                   # what they've been delivered (knowledge boundary)
    joined_at_seq: int                   # a late joiner only gets the summary up to here, not the earlier lines

@dataclass
class Conversation:
    id: str; channel: Channel; initiator_id: str
    state: ConvState; state_version: int  # bumped on every transition (stale timers check it)
    purpose: Purpose; secondary_purposes: list[Purpose]
    topic: str; active_topics: list[str]
    participants: dict[str, Participant]
    floor: Floor                          # holder, expects_reply, deadline_ts, attempts (conversation_floor's data)
    interruption: Interruption | None     # {by, kind, priority, can_resume, since}
    context: ContextObject                # section 10 of the spec, updated incrementally
    open_items: OpenItems                 # question ids, request ids, proposal ids still unanswered
    outcome: Outcome | None               # {reason, settled: {req_id: status}, agreements, disagreements, ended_by}
    created_at, started_at, last_activity_at, resolved_at: float | None
    policy_key: str                       # which policies.py row governs timeouts
    seq: int                              # last assigned sequence number
    legacy_id: str | None                 # the world["conversations"] id while the mirror is on
```

Messages are stored in `world["cpl"]["messages"][conversation_id]` as a list, capped like today
(`CONVERSATION_LOG_CAP`). Once the conversation resolves, the full list goes to the archive sink.
`world["cpl"]["requests"][request_id]` holds `TrackedRequest {id, conversation_id, source_message_id, requester_id,
recipient_id, action, target, deadline, status: open|accepted|conditional|rejected|deferred|negotiating|cancelled|
fulfilled, conditions, history[]}`. Requests are kept after their conversation resolves while their status is open,
deferred or accepted-but-not-yet-a-contract. `world["cpl"]["dedupe"]` is a bounded map of recently applied
decision/message ids (section 9).

---

## 5. Database migration (archive only, see C1)

`scripts/migrations/cpl_001_archive.sql`. The tables follow the spec's schema with these changes: `payload` and
`context_summary` are `jsonb`, primary keys are natural ids so writes are `INSERT … ON CONFLICT DO NOTHING`, and every
table carries `sim_id` (one database holds several simulations).

```sql
create table cpl_conversations (
  sim_id text not null, conversation_id text not null, channel text not null,
  primary_purpose text, current_topic text, status text not null, resolution_reason text,
  initiator_id text not null, created_at double precision, started_at double precision,
  last_activity_at double precision, resolved_at double precision, context_summary jsonb,
  outcome jsonb, archived_at timestamptz default now(),
  primary key (sim_id, conversation_id));
create index on cpl_conversations (sim_id, initiator_id, resolved_at desc);
create index on cpl_conversations (sim_id, resolution_reason);

create table cpl_participants (
  sim_id text, conversation_id text, character_id text, role text, participation_status text,
  joined_at double precision, left_at double precision, left_reason text, last_message_sequence int,
  primary key (sim_id, conversation_id, character_id));
create index on cpl_participants (sim_id, character_id, joined_at desc);

create table cpl_messages (
  sim_id text, message_id text, conversation_id text not null, sequence_number int not null,
  sender_id text not null, message_type text not null, payload jsonb not null, content text,
  world_ts double precision, delivery_status text,
  primary key (sim_id, message_id),
  unique (sim_id, conversation_id, sequence_number));

create table cpl_requests (
  sim_id text, request_id text, conversation_id text, source_message_id text, requester_id text,
  recipient_id text, request_type text, request_status text, deadline double precision, history jsonb,
  primary key (sim_id, request_id));
create index on cpl_requests (sim_id, recipient_id, request_status);

create table cpl_events (
  sim_id text, event_id text, conversation_id text, event_type text, payload jsonb, world_ts double precision,
  primary key (sim_id, event_id));
create index on cpl_events (sim_id, conversation_id, world_ts);
```

There is no `cpl_commitments` table. Commitments are contracts (C7), and contracts persist with the world. The
writer is a background thread fed by a queue, like `core/event_log.py`'s Redis writer. The tick never waits on
Postgres.

---

## 6. API contracts between character AI and CPL

### 6.1 What the character AI says (out)

Two shapes, both validated by `cpl/protocol/intents.py`.

**Initiate** is chosen from the normal decision prompt. It replaces "SAY to someone who isn't in a conversation
with me":

```
TALK_TO: Ana
PURPOSE: request            # one of the purposes; the prompt lists 6 common ones, others are accepted
ABOUT: borrow the car tonight
APPROACH: friendly          # friendly | direct | careful | urgent | hostile
FEELING: anxious 0.4
SAY: Hey, got a minute? Could I borrow your car tonight?   # optional; omitted -> Mode A opener or the
                                                         # recipient just sees "X wants to ask you something"
```

This is turned into `InitiateIntent` (spec §3.2 fields). A `CHANNEL` line is only added when the character isn't
co-present (call/text). `participants.py` picks a default from the contact network.

**Turn** is used when the character is in an active conversation and holds the floor. It is answered from the
**compact turn prompt** (6.2), not the full decision prompt:

```
ANSWERS: R1 conditional     # optional: <label> accept|reject|counter|conditional|defer|clarify|partial|
                            #           acknowledge|answer|cant_answer
ACT: statement              # statement|question|request|proposal|argument|feeling
STANCE: reluctant           # optional
FEELING: tired 0.3
SAY: You can take it, but have it back before midnight.
CONDITION: back before midnight          # only with conditional/counter
NEXT: continue              # continue | wrap_up | leave:<excuse|angry|busy> | pause | let_join:<name>
```

The codec turns this into `TurnDecision {conversation_id, character_id, decision, message, next_action,
emotional_expression}` (spec §11.2). Unknown labels, an answer to a closed item, or `ACT: request` with no content
become a validation error. The fix is one corrective retry, as `llm_brain` already does. If that fails too, the
fallback is `NEXT: continue` with the rendered line as a plain statement. CPL never invents an accept or a reject
(invariant 16).

The AI never changes state directly (spec §11.3). `NEXT: leave:angry` is a *request* to leave. `processor.py`
checks it against the conversation and `state_machine.py` carries it out.

### 6.2 What CPL sends the AI (in): the compact turn prompt

Built by `cpl/turns.py` and sent through the existing cognition queue as a new request kind
(`kind: "conversation_turn"`) with priority `PRIORITY_URGENT`, which `llm_gate` already gives to mid-conversation
characters:

```
You are Ana Moreau. [persona card: 3–5 lines from context_builder's persona/mood sections]
Right now: preparing for work, tired, a little short-tempered.
You're talking face to face with Theo (your brother; you trust him, he still owes you 40).
What this conversation is about: Theo wants to borrow your car tonight.
Still open: R1 Theo asks to borrow your car tonight (needs your answer).
So far: [ContextObject.summary — at most ~5 lines, plus the last 2 lines verbatim]
Theo just said (anxious): "Hey, got a minute? Could I borrow your car tonight?"
Answer in this format: ...
```

This replaces re-rendering the whole decision context (`context_builder.py`, ~4.4k lines of sections) on every
conversational turn. That is the main token saving (spec §10). The character's full context is used for Mode C turns
and whenever the turn says `NEXT: leave` or `pause` (the character may be leaving to *do* something, which needs the
action menu). In that case CPL runs a normal decision with a "you just left the conversation with Theo" line.

### 6.3 Intents from outside the AI

`cpl.interrupt(world, conversation_id, by, kind, priority, can_resume)` is called by systems that interrupt people:
`doorbell`, `phone` incoming call, work shift start (`work_shift`), `child_care` emergencies, `director_mode` STOP.
`cpl.notify_unavailable(world, char_id, reason)` is called on sleep, arrest, death, leaving the building or going
off-grid (existing events: `character_arrested` and the like). These are the only ways other systems change a
conversation.

---

## 7. Event contracts (CPL → Simsland)

Published on `core.event_bus` (so they land in `core/event_log` and the replay harness), all with
`{event_id, conversation_id, world_ts, causation_id}` plus the following:

| event | payload | consumed by |
|---|---|---|
| `cpl.conversation_started` | participants, channel, purpose | `conversation_seating`, relationships (contact `last_contact`) |
| `cpl.message_delivered` | envelope (recipient view: audience-filtered), recipient_id, overheard | **every existing per-line side effect** moves here: relationship_ledger `emit_impact`, `dialogue_memory`, `push_conversation_reaction`, `apply_interaction`, `analyze_message`, pattern_concern, memory_acknowledgement, reflections/opinions; `heard_speech` wake becomes a CPL turn request |
| `cpl.request_created` / `_accepted` / `_rejected` / `_deferred` / `_countered` | request | intentions (requester follow-up), `social/initiative` |
| `cpl.commitment_created` | request + conditions + deadline | `social/contracts` (creates contract), `brain/intentions` |
| `cpl.information_shared` | claim, subject_id, source, epistemic_status, confidence | `social/rumours` (third-party claims), `adapters/memory` |
| `cpl.information_acknowledged` / `_disputed` | message ref, listener stance | rumours (confidence), opinions |
| `cpl.argument` | claim, stance, move, target | `brain/opinions` (`make_argument` today) |
| `cpl.emotional_conflict` | intensity, stances, escalation step | `social/confrontations`, `conflict_pipeline` |
| `cpl.participant_joined` / `_left` | who, reason (excuse / angry / unavailable) | relationships, memories ("she stormed off") |
| `cpl.conversation_paused` / `_resumed` | interruption | debug/VR |
| `cpl.conversation_ended` | outcome (reason, settled items, agreements, disagreements) | `conversation_archive` → tags → `social/discourse` (unchanged); `conversation.ended` is still emitted for current subscribers |

Routine lines produce only `cpl.message_delivered`. The "meaningful event" filter (spec §13) lives in
`adapters/events.py`: commitments, information about third parties, conflict above a threshold, departures.

---

## 8. Conversation state machine

`state_machine.py` is a pure transition table: `transition(conv_snapshot, event) -> Result(new_state, effects[])`.
Effects are data (`schedule_timer`, `cancel_timer`, `deliver`, `publish`, `request_turn`, `set_floor`), and
`cpl/conversations.py` carries them out. This makes the table testable exhaustively without a world.

| from | event | to | effects |
|---|---|---|---|
| — | `initiate` (valid, recipient reachable) | CREATED → PENDING | deliver invitation; timer `invite` (policy) |
| — | `initiate` (recipient unreachable: no channel, blocked, phone dead) | EXPIRED (`UNAVAILABLE`) | voicemail/inbox if channel allows; tell initiator |
| PENDING | any recipient turn other than decline/ignore (incl. hostile, "No.") | ACTIVE | floor → initiator if reply expects one |
| PENDING | `decline` (control) | RESOLVED (`DECLINED`) | excuse delivered; request (if any) → `rejected` |
| PENDING | `defer` ("later") | RESOLVED (`DECLINED`, outcome `later_at`) | request → `deferred`; `_play_plans`-style follow-up timer for the initiator |
| PENDING | timer `invite` | EXPIRED (`NO_ANSWER`) | initiator notified (unnoticed/ignored cue, as in conversation_floor) |
| ACTIVE | turn `continue` | ACTIVE | context update; floor; timer `reply` re-armed |
| ACTIVE | timer `reply`, holder thinking | ACTIVE | re-arm (no timeout while generating, as today) |
| ACTIVE | timer `reply`, holder busy/didn't notice | ACTIVE (attempt+1) | speaker may repeat louder / follow up once (existing floor rules) |
| ACTIVE | timer `reply`, attempts exhausted | RESOLVING → RESOLVED (`TIMEOUT` or `ABANDONED`) | |
| ACTIVE | `interrupt` | ACTIVE + `interruption` flag | both participants get a short turn: ignore / pause / let join / leave |
| ACTIVE | `pause` (from a participant or accepted interruption) | PAUSED | timer `pause` (policy) |
| PAUSED | `resume` | ACTIVE | summary-only reminder to both |
| PAUSED | timer `pause` / participant left area | RESOLVED (`INTERRUPTED`) | open requests stay open |
| ACTIVE | `leave` by one of 2 | RESOLVED (`PARTICIPANT_LEFT` / `ANGRY_WITHDRAWAL` / `UNAVAILABLE`) | farewell line if given; open items unresolved |
| ACTIVE | `leave` by one of 3+ | ACTIVE | participant `left`; floor reassigned |
| ACTIVE | `wrap_up` by all / all open items settled + policy says done | RESOLVING | one closing line each (CLOSE_GRACE, as conversation_outcome does) |
| ACTIVE | length/time policy reached | RESOLVING | "wrap up" hint in the next turn prompt |
| RESOLVING | closing lines done / timer `close` | RESOLVED (`MUTUAL_AGREEMENT`, `QUESTION_ANSWERED`, `REQUEST_FULFILLED`, `REQUEST_REJECTED`, `TOPIC_EXHAUSTED`) | |
| RESOLVING | new open item raised | ACTIVE | (talk picks up again; counts against the hard cap) |
| any live | `unavailable` (sleep, arrest, death, off-grid, out of earshot for in-person) | RESOLVED (`UNAVAILABLE`) | |
| any live | hard cap (policy × 2) | RESOLVED (`TIMEOUT`) | guarantee of invariant 15 |
| ACTIVE | escalation to violence (`conflict_pipeline` fight stage) | RESOLVED (`CONFLICT_ESCALATION`) | |

Rules enforced by the machine: transitions out of RESOLVED/EXPIRED are rejected. Every transition bumps
`state_version`, and every timer carries the version it was set at, so a stale timer is a no-op. The resolution
reason is picked by `resolution.py` from `open_items` and the last control message, not by the model.

Requests have their own small machine (`open → accepted | conditional | rejected | deferred | negotiating →
fulfilled | cancelled`), independent of the conversation (invariant 9).

---

## 9. Delivery, idempotency and recovery

**Delivery (asynchronous, no waiting).** `submit_turn` persists the message (seq assigned) and runs
`router.deliver`, all synchronously under the lock and in microseconds:

* in person: audience is the addressed participants who pass `conversation_reach.check_pair`, plus overhearers from
  perception (they get `overheard=true` and their knowledge boundary is `overheard`). An addressed participant out
  of earshot → `note_unheard` (existing).
* call: needs both phones usable (existing check). If not, the message goes to the inbox as voicemail, and an
  invitation stays PENDING until the call-back or expiry.
* text/email: always delivered to the inbox, with reading delay from `scripted_conversations.sms_check_delay_minutes`.
  The conversation stays ACTIVE across hours, with a long `reply` policy.

After delivery, CPL either answers right away (Mode A: rendered from a template, no model) or puts a
`conversation_turn` request on the cognition queue for the recipient. The result comes back as `decision_ready` →
`cpl.submit_turn`. Nothing blocks on the model (distributed plan principle 5).

**Idempotency.**
* Every turn request carries `turn_id = hash(conversation_id, recipient_id, triggering message_id, state_version)`.
  The resulting message gets `message_id = "msg_" + turn_id`. A result delivered twice therefore produces the same
  message id, and the store drops the second one (`dedupe` map plus a check against `messages[conv]`).
* A turn result whose `state_version` no longer matches (the conversation moved on while the model thought) is
  **re-validated** rather than dropped: if it still answers an open item it is applied, otherwise it is discarded and
  logged. This mirrors how `process_decision` re-validates against the current world.
* Commitments: `commitment_id = "commit_" + request_id`, and contracts upsert by id, so a commitment is never created twice.
* Archive writes: `ON CONFLICT DO NOTHING`.
* Events carry `event_id = message_id + ":" + kind`. Subscribers that write state check it (the relationship ledger
  already de-dupes by ref).

**Recovery.** Live state is the world (C1). After a restart, `cpl.recover(world)` runs once:
1. `scheduler.install` has already restored all `cpl:*` timers (they live on the world).
2. Any conversation whose floor holder was `thinking` with no live cognition request (the request was lost with the
   old process) is re-asked once, using the same `turn_id` so a late answer from the old request still de-dupes.
3. Conversations whose participants can no longer talk (positions/state restored) are resolved `UNAVAILABLE`.
4. PENDING invitations past their deadline expire.

Worker restart mid-request: `work_queue` already re-claims after `claim_idle_ms`. The duplicate result de-dupes as
above. AI session restart: CPL holds the conversation, so a session only needs the turn prompt, which is built
fresh from the context object every time.

---

## 10. Context management and generation modes

**Context object** (spec §10.1) is updated incrementally by `context.py` on every message, with no model calls:
open items added and removed by reference, agreements and disagreements from response types, active topics from
`topic`/`subject`, and per-participant emotional state from the message's emotion field. The prose `summary` is
refreshed only when the verbatim lines it doesn't cover are more than N=4, or on purpose change, or before a late
joiner's first turn. The refresh is done by a bg_llm job (off the tick, priority low), and the template summary
stays in place until it arrives. Rule from spec §16.19: open items, unresolved disagreements and the emotional
state are **structured fields** next to the summary, never only inside it, so compression can't lose them.

**Generation mode selection** (`generation.py`) chooses per pending turn, before any model call:

| Mode | When | Cost |
|---|---|---|
| A — structured | factual question whose answer CPL can read from the recipient's own state (location, activity, whether they ate, time) **and** no emotional load (recipient mood calm, relationship not strained, no open conflict, the question carries no accusation); acknowledgements; control messages (pause/resume/close when both sides agreed) | 0 model calls; line from a template |
| B — natural | default for social, informative and simple-request turns | 1 compact turn call |
| C — reasoning | negotiation/proposal on the table, persuasion, conflict above a threshold, a request with real cost to the recipient (money, time against an existing plan), emotional purpose | 1 call with the full character context (current decision prompt + conversation block) |

Mode A applies only when *every* condition holds. If anything is uncertain, the turn uses B. This keeps the spec's
warning ("are you home? you were supposed to pick up the kids") safe. The emotional check uses the incoming
message's emotion and the recipient's existing `emotional temperature` and relationship state.

---

## 11. Rollout and phases

Every phase sits behind `CPL_MODE`:
* `off`: today's code path, untouched.
* `shadow`: CPL runs alongside. It builds envelopes and conversations from `apply_speech` calls and from
  conversation_floor/outcome results, but makes **no decisions** and changes nothing outside `world["cpl"]`. A debug
  route shows where CPL's state or resolution differs from the legacy one. This is how each moved check is proven
  equal before switching.
* `on`: CPL owns the lifecycle. `adapters/legacy.py` keeps `world["conversations"]` mirrored for readers that
  haven't moved yet (context_builder, VR conversations timeline, social_sandbox, debug_draw), until Phase 4 removes
  the mirror.

### Phase 1 — core protocol (two characters, in person + call)

1. `protocol/`, `model/`, `state_machine.py`, `store.py` (WorldStore) with unit tests of the transition table.
2. `intents.py` + `participants.py` + `router.py`, moving out of `apply_speech` (one commit each, each with its
   original regression test): addressee resolution, earshot, phone reachability/voicemail, repeat filter, floor
   blocking.
3. Invitation as PENDING (C4): interest check becomes the recipient's invitation decision. Decline/ignore/later are
   recorded.
4. `adapters/events.py`: `cpl.message_delivered` carries the existing per-line side effects (moved, not rewritten).
5. Codec for the Turn output. For Phase 1 the turn uses the **existing full decision prompt** plus the new
   `ANSWERS/ACT/NEXT` lines. The compact prompt is Phase 5.
6. Acts supported: statement, question, request, response (accept/reject/answer/acknowledge), leave.
7. Shadow first, then `on` in a test world. Archive sink + migration.

Acceptance: spec §17 Phase 1 list. Also: every existing conversation test passes with `CPL_MODE=on`.

### Phase 2 — lifecycle

Timers replace `conversation_floor.tick` and `conversation_outcome.tick` (C2). Policy table replaces the
MAX_LINES/MAX_TICKS caps (C6). Interruption API wired into doorbell, phone, work shift, child care and director STOP.
Pause/resume. Departures with reasons (excuse vs angry, spec §7.4). Unavailability. Recovery routine. The template
context summary, plus the bg_llm summary refresh.
Acceptance: spec §17 Phase 2. A test asserts that no conversation is still live after its policy hard cap, for
a soak run of the determinism harness.

### Phase 3 — semantic protocol

Proposals, counteroffers, conditional accept, structured arguments (`make_argument` folds in), open-question
tracking, tracked requests outliving conversations, `cpl.commitment_created` → contracts (C7), information shared
with epistemic status → rumours/memory (C8), and the structured record fed into the conversation-tags prompt (C9).
Acceptance: spec §17 Phase 3.

### Phase 4 — emotional, social, multi-party

Emotion field on every message (survives summarization as a structured field). Purpose drift into conflict →
`social/confrontations`. Abrupt angry endings. Misunderstanding: the recipient's turn can answer `clarify` or
reject a claim. `apply_speech_to_group` folds into CPL participants. A third party can join or interrupt, and late
joiners get a summary up to `joined_at_seq` only. Overheard vs told knowledge boundaries. Text/email conversations
through CPL (`scripted_conversations` plays its script *through* CPL as pre-decided turns). The legacy mirror is
removed.
Acceptance: spec §17 Phase 4.

### Phase 5 — optimization

Compact turn prompt (6.2). Mode A/B/C selection. Skipping conversation tags for fully structured conversations.
`metrics.py` with the spec's measures (LLM calls and tokens per conversation, latency, % of turns without NL
generation, % of conversations ending in timeout/abandonment), shown on `/admin` and in the VR LLM log. Before/after
comparison on the same seeded world (`tests/determinism.py` + recorded LLM answers).

---

## 12. Test plan

Tests follow the backend's convention: plain scripts `backend/tests/test_cpl_*.py` with `check()`, run in the
backend container (`python tests/test_cpl_lifecycle.py`), `COGNITION_MODE=local`, with a stub LLM that returns
scripted Turn outputs. Pure modules (state machine, codec, policies, context) get fast tests that need no world.

| file | covers (spec §18) |
|---|---|
| `test_cpl_state_machine.py` | every row of the table in section 8; illegal transitions rejected; stale timers no-op |
| `test_cpl_codec.py` | compact output → TurnDecision; bad labels; corrective retry; fallback never fabricates accept/reject |
| `test_cpl_invitation.py` | invitation accepted, declined, ignored → expired, recipient unavailable, "later", hostile first reply → ACTIVE |
| `test_cpl_progression.py` | Q&A, multiple exchanges, topic change, request accept/reject/conditional, argument/counterargument, unresolved disagreement |
| `test_cpl_termination.py` | mutual close, one leaves, angry withdrawal, inactivity timeout, interruption ending it, unavailability, pause → resume, pause → expire |
| `test_cpl_persistence.py` | world save/restore mid-conversation (world_state persist + load), duplicate `decision_ready`, two turns arriving in the same tick, lost cognition request re-asked, archive write idempotent |
| `test_cpl_knowledge.py` | claim shared but disputed; acknowledged ≠ confirmed; commitment → contract kept after the conversation ends and completed later; private line not delivered to overhearer out of earshot; third party gets only what they heard/were told |
| `test_cpl_perf.py` | Mode A answer with zero LLM calls; acknowledgement without generation; summary updated incrementally; 50 simultaneous conversations; no `cpl` work runs on ticks where no timer is due (counter on the job) |
| existing: `test_talking`, `test_unheard_speech`, `test_speech_repeat`, `test_conversation_outcome`, `test_conversation_archive`, `test_conversation_latency`, `test_conversation_log` | run with `CPL_MODE=off` and `on`; must pass in both |
| `tests/determinism.py` soak | seeded world for a sim day under `on`: no live conversation past hard cap, no duplicate messages/commitments, end-reason mix reported |

---

## 13. Open decisions for you

1. **C1 persistence:** keep live state on the world with Postgres as an append-only archive (recommended), or make
   Postgres tables authoritative now and accept the crash-consistency gap until Step 4?
2. **C4:** OK to turn the conversation-interest check into the recipient's invitation decision, so declines become
   recorded conversations?
3. **C6:** what length/time defaults per purpose? I'd start from today's 6 lines / 4 minutes for casual chat and
   loosen it for negotiation, conflict and texts.
4. **C7:** OK that commitments *are* social contracts (one term), not a separate store?
5. **Phase 1 prompt:** add the `ANSWERS/ACT/NEXT` lines to the existing decision prompt first (lower risk), and
   build the compact turn prompt in Phase 5 as planned? Or start with the compact prompt, since that's where most
   of the token savings come from?

---

## Progress log

- **Decisions (2026-11-14).** C1: live state on the world, as entities (`cpl_conversations`, `cpl_requests`), with
  Postgres as an append-only archive. C4: invitations are PENDING conversations, and declines are recorded. C7:
  commitments are social contracts. Phase 1 prompt: extend the existing decision prompt first.
- **Phase 1, step 1 (done).** `backend/cpl/`:
  - `model/enums.py`
  - `protocol/envelope.py`: pydantic. The payload is validated by message type, and the model never writes ids.
  - `policies.py`: purpose × channel × urgency. Today's 6 lines / 4 minutes is the casual default. Reaching it
    winds down; twice it is a hard stop.
  - `state_machine.py`: a pure transition table whose effects are data.
  - `store.py`: entities on the world, ids from a world counter (deterministic), messages capped on their
    conversation, duplicates dropped by message id, requests that outlive their conversation.
  - `conversations.py`: carries out the effects. Timers are `cpl:<id>` on the scheduler, stamped per kind, so a
    replaced or cancelled one is stale.

  `tests/test_cpl_state_machine.py` (50 checks) covers every row of the table and the engine on a bare world.
  Not wired into `apply_speech` yet (`CPL_MODE=off`).
- **Phase 1, step 2a: shadow mode (done).** `cpl/shadow.py` with `CPL_MODE=shadow`. CPL follows the legacy path
  from synchronous hooks: each line (`add_message`), each declined invitation and each voicemail (`apply_speech`),
  and each legacy ending (`conversation_floor._end`). It keeps its own conversation per legacy one, with its own
  timers. When legacy ends one, CPL records where its copy stood and closes it with the legacy reason. The tallies
  are in `world["cpl_shadow"]` (`shadow.compare`). A state-machine event, `force_resolve`, closes from outside (also
  for the planned admin action).
  - Determinism: `CPL_MODE=off` is identical to before. `shadow` vs `off` is identical outside CPL's own state in
    all three runs.
  - First reading (social run, 2,400 ticks): 8 conversations, 15 lines, 1 declined invitation. Legacy ended all 8
    while CPL's copies were still live (4 pending, 3 active, 1 pending at "lapsed"). Legacy stops at 6 lines and
    ends single-line exchanges within a second; CPL's policies are looser on purpose (C6: social allows 8 lines,
    an invitation 60 s). Where to set them is the C6 decision, now with numbers behind it.
  - `tests/test_cpl_shadow.py`.
- **Phase 1, step 2b: participants (done).** `cpl/participants.py` holds the checks that decide whether a line can
  reach someone, moved unchanged out of `apply_speech` (C12): `addressee`, `answering`, `repeat_dropped`,
  `floor_blocks`, `earshot`, `channel_open`. `apply_speech` calls them, so the legacy path and CPL share one
  implementation. Determinism identical. The regression tests that pinned the original bugs pass unchanged: talking,
  unheard speech, speech repeat, conversation outcome, floor, archive, latency, log.
- **Phase 1, step 5: codec (done).** `cpl/protocol/codec.py` parses the compact turn lines (`ANSWERS / ACT / STANCE
  / FEELING / SAY / CONDITION / NEXT`) and the initiate lines (`TALK_TO / PURPOSE / ABOUT / APPROACH / FEELING / SAY
  / CHANNEL`). Open items are shown to the model as labels (Q1, R1, P1) and mapped back to ids. Invalid answers are
  reported for the corrective retry. The fallback keeps the line as a plain statement and never invents an accept
  or a reject. `to_event` turns a decision into its state-machine event. `tests/test_cpl_codec.py` (21 checks).
  Next: invitations as PENDING with CPL deciding (step 3, `CPL_MODE=on`), the `cpl.message_delivered` adapter for
  the per-line side effects (step 4), and these lines added to the decision prompt.
- **C6 decided (2026-11-14): keep the looser defaults** (`cpl/policies.py`).
- **Phase 1, step 3: `CPL_MODE=on` decides when a conversation ends (done).**
  - The legacy path's time and length endings (`timed_out`, `no_response`, `idle`, `lapsed`, `ignored`) are held
    back while CPL has a live copy (`shadow.legacy_end_allowed`, asked first by `conversation_floor._end`).
  - When CPL ends a conversation, the legacy one ends with it, under the legacy reason readers know
    (`shadow.on_cpl_end`).
  - Endings for something that actually happened (settled, someone left or gone) still come from the legacy path,
    and CPL's copy is closed with them.
  - Two new timers make sure a conversation ends even if nobody speaks: `idle` (re-armed by every line, 120 s face
    to face) and `cap` (the hard cap, set when the conversation starts; it also ends a pause).
  - Determinism: `off` and `shadow` are unchanged.
  - Social run under `on`: no errors. Conversations ran to 10–11 lines where legacy cut them at 6, and every one
    ended with a CPL reason (question answered, topic exhausted, no answer; plus 9 declined invitations). 6 legacy
    endings were held back, and CPL ended 4 conversations itself. Nothing was left live past its cap.
  - Known for Phase 2: an initiator still speaks a second line before the invitation is answered (CPL rejects it as
    a turn, but the legacy path lets it through). The memories that come with "ignored" are written before the
    legacy end is held back.
  - `tests/test_cpl_on.py`.
- **Phase 1, step 4: delivery (done).** The per-line side effects at the end of `apply_speech` (subject and social
  line, pattern concern, impact ledger, memory acknowledgement, dialogue memory, reaction and interaction, analysis
  and reflections) moved unchanged into `cpl/adapters/line_effects.py`, as subscribers to a delivered line
  (`cpl/adapters/events.py`).
  - They run synchronously, in their original order: they depend on each other's writes and on the shared random
    stream, so plain event-bus subscribers, run only at the next flush, would change results.
  - `cpl.message_delivered` is then emitted on the bus.
  - `apply_speech` now calls `deliver()`.
  - Determinism identical. The tests covering these effects pass, or fail exactly as before (`test_grudges`,
    `test_memory_acknowledgement`: fixture issues). `tests/test_cpl_delivery.py`.
- **Phase 1, step 5b: the turn lines in the decision prompt (done).**
  - With `CPL_MODE=on`, a character in a live CPL conversation gets a block on their decision context
    (`cpl/turns.py`): who they're talking with, what is still open as labels ("R1 Theo asked for: … (needs your
    answer)"), and whether it is winding down.
  - The system prompt gains `ANSWERS / ACT / CONDITION / NEXT` only then. The reply parser keeps those lines, and
    the speech carries them to `apply_speech`.
  - The line hook applies them:
    - a question or request opens a tracked item (questions on the conversation, requests as `cpl_requests`
      entities);
    - an answer settles it;
    - an accepted request emits `cpl.commitment_created` (`commit_<request id>`; the contracts handler is Phase 3);
    - once everything asked is answered, the conversation winds down;
    - `NEXT leave:angry` ends it as an angry withdrawal.
  - An answer to an item that isn't open answers nothing and is logged on the conversation (`turn_errors`). The
    fallback keeps the line and a valid NEXT, and never invents an accept or reject.
  - A first reply that settles everything goes straight to winding down. Words followed by walking off count as
    started and left, not declined. Only a deliberate wrap-up counts as the speaker's closing line.
  - Determinism: `off` and `shadow` unchanged. `tests/test_cpl_turns.py` (request → accepted → commitment →
    request fulfilled; an angry exit).
  - Phase 1 still to do: the append-only archive tables (item 7).
- **Phase 1, item 7: archive (done).** `scripts/migrations/cpl_001_archive.sql` (the tables are also created on
  first write) and `cpl/archive.py`.
  - On `cpl.conversation_ended`, a copy of the conversation, its participants, messages and requests is queued. A
    background thread writes it (`ON CONFLICT DO NOTHING`, so archiving twice writes once). The step never waits on
    Postgres.
  - An hour later a `gc` timer drops the finished conversation from the world, with its settled requests. Open,
    deferred and negotiating requests stay.
  - `tests/test_cpl_archive.py`. Determinism: `off` and `shadow` unchanged.
  - **Phase 1 is complete.** Next is Phase 2 (lifecycle):
    - interruptions (doorbell, phone, work shift, child care, director STOP);
    - pause and resume;
    - departures with reasons;
    - unavailability (sleep, arrest, off-grid);
    - recovery after a restart;
    - the template summary;
    - closing the two gaps from step 3.
- **Phase 2, part 1: what changes a conversation from outside (done).** `cpl/lifecycle.py`.
  - **Interruptions.** `interrupt()` is called at the doorbell (`systems/doorbell.py`), at an incoming call to
    someone mid-conversation (face-to-face conversations only; the call itself goes on), and at the director's time
    stop.
    - The conversation carries the interruption, and both participants are asked what to do about it.
    - The interrupted person's prompt says so: carry on, `NEXT: pause`, or `leave:excuse`. The next line clears it.
  - **Unavailability.** `notify_unavailable()` is wired to the existing events: `character.offgrid`,
    `character_arrested` / `character_jailed`, and `activity_started` for sleep or a nap. A two-person conversation
    ends (unavailable); a larger one carries on without them.
  - **Recovery.** `recover()` runs on `world.loaded`. It re-asks a turn whose model request was lost, and resolves
    conversations with someone now away.
  - **Waking.** In `on` mode, `cpl.turn_requested` wakes the character for turns nothing else would prompt: a
    follow-up, a closing line, an interruption, a recovered turn.
  - **Pause and resume** through the turn lines; speaking again picks the conversation up.
  - **Template summary**, kept up to date line by line and shown on the prompt ("So far: …").
  - **Both step-3 gaps closed in `on`.** An initiator can't talk over an unanswered invitation
    (`participants.pending_invitation`): 0 rejected turns in the social run, down from 8. A legacy "ignored" (with
    its memory) waits for CPL.
  - Determinism: `off` and `shadow` unchanged. `tests/test_cpl_lifecycle.py` (21 checks).
  - Still in Phase 2: work-shift and child-care interruptions (no clean event to hang them on yet), and a soak run
    asserting the hard cap over a whole sim day.
- **Phase 2, part 2 (done; Phase 2 complete).**
  - A hungry child who can't feed themselves interrupts a parent mid-conversation ("your child is calling for
    you").
  - A work shift needs no interruption of its own: leaving for work takes the character off the map, and that ends
    the conversation as unavailable.
  - `tests/test_cpl_soak.py`: a full sim day (86,400 ticks, social, `CPL_MODE=on`, about 90 s) produced 104
    conversations and 637 lines.
    - Nothing was live past its hard cap; no message was stored twice; sequence numbers ran in order.
    - Finished conversations were cleared after the gc delay, with no orphan timers.
    - Only open requests outlived their conversations.
  - Next, Phase 3 (semantics):
    - accepted requests become social contracts (C7);
    - proposals, counteroffers and conditional accepts, carried through;
    - structured arguments;
    - information shared with an epistemic status (asserted, acknowledged, disputed …), passed to rumours and
      memory (C8);
    - the structured record fed into the conversation-tags prompt (C9).
- **Phase 3: semantics (done).**
  - **C7, contracts.** `cpl/adapters/contracts.py`: an accepted or conditionally accepted request becomes a one-term
    social contract (`social/contracts.create`). The recipient is responsible, under the conditions they named. The
    request records the `contract_id` it became, so a commitment delivered twice makes one contract.
    - The agreement reaches both prompts the way every contract does. No separate intention, since nothing would act
      on one.
    - Contracts make their own ids, so the link is the request's `contract_id` rather than commitment id = contract
      id.
  - **Counteroffers.** `ANSWERS: R1 counter` + `CONDITION` puts the request under negotiation and opens a proposal
    back to the requester (P1 on their prompt). Accepting it accepts the request on those terms and makes a contract
    ("mutual agreement"); rejecting it rejects the request.
  - **C8, claims.** A gossip or urgent-report line is a claim, asserted. The listener's next STANCE takes it as
    acknowledged (which is not the same as confirmed) or disputed. `cpl.information_shared` /
    `_acknowledged` / `_disputed` are emitted. Third-party rumours stay with the reader of the finished conversation,
    so nothing is counted twice. An `ACT: argument` emits `cpl.argument`.
  - **C9, the record for the reader.** `cpl/record.py` lists who asked what and how it was answered, agreements,
    claims and how they were taken, and how it ended. With `CPL_MODE=on` it goes into the conversation-tags prompt as
    given (`social/discourse.context_for_reader` → `llm/conversation_tags._ctx_block`). Shadow mode keeps it out.
  - Determinism: `off` and `shadow` unchanged. The soak still passes. `tests/test_cpl_semantics.py` (13 checks).
  - Next, Phase 4: groups (`apply_speech_to_group` into CPL participants), late joiners with a summary up to when
    they joined, overheard vs told, text and email through CPL, and removing the legacy mirror. Then Phase 5: the
    compact turn prompt, Mode A/B/C, and metrics.
- **Phase 4: more than two people, and who knows what (done, except removing the legacy mirror).**
  - **Groups.** Group talk, texts and scripted conversations all go through `add_message`, so CPL already follows
    them: a group conversation has all its participants, one leaving doesn't end it, and a text conversation runs
    under the text policy.
  - **Late joiners.** `NEXT: let_join:<name>` (`cpl/participants.join`): someone nearby joins under way. CPL records
    `joined_at_seq` and the summary so far, and the legacy conversation takes them in (`joined_ticks`). Their prompt
    shows only what was said since they joined, plus "Before you joined: …" (`brain/context_builder.py`).
  - **Overheard vs told.** A line said aloud records who overheard it: in earshot in the same building, awake, not
    in the conversation (read from `core/positions.py`, reaching nobody). A claim keeps who was told apart from who
    only overheard it, and both are in `cpl.information_shared`.
  - `tests/test_cpl_groups.py`. Determinism: `off` and `shadow` unchanged. The soak passes.
  - **Not done: removing the legacy mirror.** As built (safely, step by step), CPL *follows* the legacy conversation
    (`world["conversations"]`) rather than the legacy conversation mirroring CPL. Removing it means moving every
    reader and writer of `world["conversations"]` onto CPL: the context builder, floor, outcome, archive, reach,
    conversation goals, the VR conversations timeline, social_sandbox, debug_draw. That is its own step, and it
    should wait until `CPL_MODE=on` has run with the real model.
- **Phase 5: optimization (done; all five phases built).**
  - **Mode A/B/C** (`cpl/generation.py`). Mode A answers with no model call, and only when every condition holds:
    - the only thing waiting on the character is a factual question answerable from their own state (where they
      are, what they're doing, whether they're home or have eaten);
    - the question has no edge (the spec's "you were supposed to pick up the kids" is B);
    - they aren't upset or stressed, they get on with the asker, and nothing is disputed.

    `brain/agent_loop.py` applies a mode-A decision directly. C is a request or proposal waiting on them, or a
    conflict, persuasion or negotiation. B is everything else.
  - **Compact turn prompt** for B (`cpl/turns.compact_prompt`, opt-in with `CPL_COMPACT_TURNS=on`): who they are,
    their mood and activity, who they're talking to and how they relate, what is open, and the last lines (under
    800 characters), instead of the whole decision context.
  - **Skipping the AI reading** (`cpl/record.skippable`, on only): every line structured, two people, no claims,
    nothing to read between the lines. The structure stands in for the tags call.
  - **Metrics** (`cpl/metrics.py`, `GET /admin/cpl/metrics`): turns by mode, model calls, compact turns, the share
    of turns without a model call, and the endings (with the share by timeout or abandonment). Also
    `GET /admin/cpl/conversations[/{id}]` and `/admin/cpl/shadow`.
  - Determinism: `off` and `shadow` unchanged. Full suite: no new failures (114 pass). `tests/test_cpl_generation.py`.
  - **What only the real model can show:**
    - whether characters write the turn lines well, and how often they answer open items correctly;
    - the compact prompt's quality, which is why it is off by default;
    - actual token savings.

    The stand-in model used by the determinism harness never writes the turn lines, so the `on` path is exercised
    with scripted exchanges. Suggested next: run `CPL_MODE=on` against the real model on a test world, read
    `/admin/cpl/metrics` and the shadow tallies, then decide on the compact prompt and on removing the legacy mirror.
- **Live-test runner (built; the run against the real model is still to do).** `backend/tools/cpl_live_test.py`
  runs the fixture world with everyone together, `CPL_MODE=on`, and the real `think()` (new `DET_POLICY=real` in
  `tests/determinism.py`). It reports adherence (how often characters wrote the turn lines, and their mistakes),
  tracking (questions, requests, contracts, claims), lifecycle (endings, lengths, shadow tallies), cost (turns by
  mode, model calls, prompt sizes, seconds per decision) and sample transcripts.
  - The real Ollama (`192.168.10.176` in docker-compose) is on the user's network, so it can't be reached from the
    cloud session. Model downloads are blocked there too.
  - The plumbing was checked end to end with a scripted stand-in model: the real `think()`, parser, turn lines,
    accepted requests and contracts. That run found and fixed two bugs:
    - a legacy `resolved` ending overrode CPL's own reading (an accepted request was recorded as "question
      answered");
    - a question asked without an `ACT` line, as every opener is, wasn't tracked, so Mode A could never apply.

    Regression checks are in `tests/test_cpl_turns.py`.
