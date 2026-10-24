# Simsland event-driven architecture — canonical plan

(Replaces "components with their own clocks": a component doesn't have a tick, it has
**handlers, timers, and optionally a temporary active loop**. Revised after an outside review;
the changes are marked "(review)".)

Status: proposal. Nothing here is built. It is a migration plan, not a rewrite-from-scratch:
the 261 `systems/` modules and 21 `brain/` modules hold the actual simulation logic and
should survive almost unchanged; what changes is *what calls them, when, and on what state*.

## 1. What the main tick actually is today

Measured from the code, not assumed:

- `sim_loop.tick(world)` is one ~850-line function (`sim_loop.py:466–1307`) that runs ~60
  sections in sequence, 72 of them gated by `every(world, N)` cadences
  (`core/tick_schedule.py`: 5, 10, 15, 20, 30, 60, 300 ticks...) plus calendar-boundary checks
  (`_is_hour_boundary`, `_is_new_calendar_day`, `_is_monday_midnight`).
- It runs under one global `_world_lock` for its *entire* span, on a single executor thread,
  against one in-memory `world` dict that is re-loaded from Redis, re-validated
  (`ensure_world_defaults`, ~6 `ensure_*` passes) and re-serialised every tick. The state blob is
  ~1.6 MB (characters 590 KB, stocks 390 KB, market 124 KB, ...), none of which is partitioned.
- Every API route that mutates anything takes the same lock, so a slow tick *is* a 503
  ("simulation busy"). The event bus flushes at the *end* of the tick, so every reaction is
  delayed a tick and ordered by tick boundaries, not by cause.
- Character decisions run in a thread pool but the tick waits for them (`AGENT_WAIT_BUDGET_SECONDS`
  = 3s) and abandons slow ones, discarding whatever they mutated. `bg_llm` mailboxes and the
  tick-thread LLM budget are patches over this.
- Most of the work is *polling*: "is any character hungry, any activity finished, any appointment
  due, any plant dry, any conversation stale?" asked of everyone every N ticks, nearly always
  answering no.

The recurring bug class this session — freezes at day rollover, 503s, starving children dusting for
ten hours — all come from one structure: everything shares one clock, one lock and one state blob.

## 2. Principles

1. **No component ticks "to check".** A component runs because an *event* reached it, or
   because a *timer it set for itself* fired. The only things that run on a rate are things that
   are genuinely continuous (movement, and only while something is moving).
2. **Single owner per piece of state.** Each entity (a character, a household, a prop, the
   market, the weather) has exactly one owning component. Others change it only by sending that
   owner an event or command. This is what removes the global lock.
3. **Time is a service, not a loop.** One sim clock publishes time and calendar-boundary events;
   `time_scale` is the clock's concern and nobody else's.
4. **Continuous quantities are lazy.** Hunger, energy, cleanliness, plant moisture become
   `value(t) = v0 + rate·(t − t0)`, read on demand, with a timer set for the moment a threshold
   will be crossed. Nothing decays tick by tick.
5. **Nothing blocks on a model call.** Every LLM call is a request/response event; the caller's
   state machine waits in a "thinking" state (which also gives the `floor_status: thinking` cue
   for free).
6. **Cross-entity effects are eventual and idempotent.** "A insults B" is an event; B's owner
   applies it when it arrives. At-least-once delivery, idempotent handlers.

### Invariants (review)

These are the rules every later decision is checked against.

- **NO global simulation tick; YES global simulation clock.** The clock answers `now()` and
  announces meaningful boundaries. It never iterates over entities or "asks everyone".
- **A component is: event handlers + timers + optionally a temporary active loop.** Never "a tick".
- **The scheduler is infrastructure and stays dumb.** `schedule(owner, key, at, payload)` means
  "deliver this event at that time" — it has no idea what the event means. The meaning of a timer
  belongs to the owner that set it.
- **Single owner per piece of state** (the rule that removes the global lock). Hunger → body;
  intentions and the active activity → the character's agency actor; a household's balance →
  household/economy; relationship A→B → social. Everyone else sends the owner an event or
  command, the owner mutates and emits the resulting event.
- **Commands vs events.** A command asks an owner to do something and can be refused; an event
  says something happened and cannot.
- **Three consistency tiers** (not "everything is eventual"):
  1. *character-local state* — strongly ordered (one owner, in-order inbox);
  2. *direct interactions between entities* (a punch, a handover, a conversation turn) —
     causally ordered: resolved by one owner of the interaction that re-validates its
     preconditions (positions, reach, who is awake) **at resolution time**, with the pair's
     entities locked together in id order for that short step. Stale intent yields "missed"
     or "no longer possible", never a contradictory result;
  3. *side effects across domains and read models* (reputation, news, analytics, the view) —
     eventually consistent and idempotent.

## 3. Target shape

```
                      ┌────────────────────────── event bus (Redis Streams) ──────────────────────────┐
 Sim Clock ──────────▶│  time.tick? no -- time.hour, time.day, time.week, time.month, time_scale_changed │
 Scheduler ◀──────────│  schedule(owner, key, at_sim_time, payload)  →  fires  timer.<owner>.<key>      │
                      └─────────────────────────────────────────────────────────────────────────────────┘
        │                │                   │                 │                │               │
  Character actors   Movement           Perception/      Social           Body/Health     World services
  (1 per character:  (routes, positions; proximity       (conversations,  (lazy needs,    (household, economy,
  activity, intent,  runs only while    (spatial index;  floor, ledger,   injuries,       market, jobs, news,
  memory, decisions) something moves)   emits seen/heard worries,        disease)        weather, police feed,
                                         on movement)    expressions)                    plants, deliveries)
        │                │                   │                 │                │               │
        └───────── entity state store: Redis JSON per entity (versioned), write-behind to Postgres ──┘
                                         │
                                  Read model / view service ──▶ WebSocket + HTTP for the frontend
                                  (subscribes to change events; no whole-world delta building)
```

- **Sim Clock** — the only periodic thing. Emits boundary events (hour/day/week/month) and
  `time_scale_changed`; exposes `now()`. Replaces `advance_calendar`, `_is_*_boundary`,
  `_is_new_calendar_day`, and `time_scale` division scattered through `movement.py`.
- **Scheduler** — `schedule(owner, key, at, payload)`; durable (Redis sorted set), cancellable,
  re-keyed idempotently. Replaces activity-duration polling, intention deadlines, appointment due
  checks, wait timers, patience timers, floor timers, loop-guard assessments, conversation
  cleanup, expectation windows, `every()` polling of "is X due".
- **Character agency actor (review)** — one logical actor per character owning that character's
  *agency*: active activity, intentions, subjective memory, decisions. It does **not** own
  everything attached to the character — physiology belongs to Body, finances to
  Household/Economy, relationships and reputation to Social — otherwise it quietly becomes the
  old `world["characters"][id]` blob again. It wakes on events addressed
  to it (heard, seen, hurt, timer) and on its own timers; decides by async LLM request; applies
  the answer when it returns. No pool, no wait budget, no abandoned decisions (the response
  is just another event). The decision path is: event/timer wakes the actor → cognition request
  (the asynchronous context-compiling middleware prepares the prompt) → LLM → a **command**
  back to the actor → the owning domain handler validates and applies it → resulting events. Replaces `_run_agent`, `AGENT_WAIT_BUDGET`, `cognition_scheduler`
  polling (it already has wake reasons — that's the seed of this).
- **Movement** — the one legitimately rate-driven component, but only for entities with a
  route: its own loop at its own rate (e.g. 10 Hz), sleeping when nothing moves. It emits
  `arrived`/`entered_room` events and publishes positions. This also decouples smooth movement
  from the LLM entirely.
- **Perception/Proximity** — a spatial index updated on movement events; emits
  `entered_view`/`audible` events when relationships between positions change, instead of the
  every-5-ticks O(N²) scan.
- **Social, Body, World services** — the remaining `systems/` modules grouped by owner. Each is
  a handler set + its own timers.
- **Read model** — change events update a projection that serves the frontend; the 1.6 MB world
  blob stops being built, diffed and shipped every second.

## 4. How the current tick sections map

Every section of `tick()` falls into one of four kinds. Counting what I could classify from
the section headers and `CADENCE`:

| kind | what replaces the poll | examples (current cadence) |
|---|---|---|
| **continuous** | own loop, only while active | movement (every tick) |
| **threshold** | lazy value + timer at crossing | hunger/energy/bladder/hygiene, `health` (30), `lt_needs` (30), `cleanliness` (30), `plants` (30), `food_aging` (24), `addictions` (30), `body_composition` (24), battery drain (5), arousal decay, impulse pressure (1) |
| **timer** | scheduled at the moment it's decided | activity durations, intention deadlines, appointments, `evictions` (120), `arrests` (30), `trials` (60), `social_projects` (60), `contract_checks` (60), `conversation_cleanup` (60), wait activities, plant "needs water" |
| **calendar** | clock boundary events | hourly household log/summary, daily stats drift, `value_influence` (24), weekly, monthly trait adoption, `election` (300), `faction` (300), `hierarchy` (300), `migration` (300), weather (60), market (20), job_market (60), police feed |
| **event** | already events, or should be | perception (5), attention (5), `conflicts` (5), `grapples` (5), `grievances` (15), `relationships` (15), `child_care` (15), `contagion` (15) → driven by `person_entered_view`, `speech`, `hostile_action`, proximity changes |

The very large majority are *threshold, timer or calendar* — i.e. there is nothing to do on
most ticks. The ones that really are "event" mostly already have an event (`heard_speech`,
`person_entered_view`, `hostile_action_resolved`) that is just flushed late.

## 5. The hard parts (honest list)

1. **`world` is everywhere.** Systems take `world` and reach into any entity (261 modules).
   The migration needs a compatibility façade — `WorldView`, backed by the entity store, that
   behaves like the dict for read paths and routes writes to the owner (or to the owner's inbox
   when the target isn't the handler's own entity). Strangler pattern: old code keeps working
   against the façade while handlers are re-pointed.
2. **Cross-entity writes.** Many functions mutate *two* characters at once (relationships,
   conversations, hostile actions, family sync). Each needs splitting into "my half" +
   an event for the other half. The ledger and floor modules built this session already follow
   that shape (`emit_impact`, `conversation_ignored`).
3. **Ordering and consistency.** Per-entity ordering is guaranteed (single owner, in-order
   inbox); global ordering is not, and shouldn't be relied on. Anything that currently depends
   on "everything this tick" (household summaries, day roll-ups) has to become a snapshot
   request or a calendar event with a defined cut-off.
4. **Debuggability.** Without a tick, "what happened in step N" disappears. Replace it with an
   event log (Redis Streams retains it) and a replay harness: load a snapshot + replay events
   into a component and assert on state. This is a net improvement over the print-debugging
   used this session, but it must be built *first*.
5. **Determinism/testing.** Tests today force cadences and stub the LLM against a world dict.
   They need an equivalent: an in-process bus + virtual clock where tests advance time
   explicitly.
6. **Persistence.** Per-entity writes (write-behind to Postgres, snapshot on interval) replace
   `save_world` of the whole blob every 30 ticks. Migration of the existing saved world is a
   one-off script (split the blob by key).

## 6. Migration path — each step shippable, game keeps running

**Step 0 — instrument (days).** Per-section timing in `tick()`; extract the classification
table above into a machine-readable registry (`section → kind → trigger`). Add the event log
(append every `emit` to a stream) so the old system is already observable. No behaviour change.

**Step 1 — clock + scheduler, in-process (the big enabler).** Introduce `core/clock.py` and
`core/scheduler.py` inside the existing process. Convert every `every(world, N)` section into a
registered handler with an explicit trigger (calendar event, timer or event); convert the
calendar-boundary checks into clock events. `tick()` shrinks to "ask the scheduler what's due"
and then disappears. Everything still runs against `world` under the lock, but **each handler is
now independently scheduled and independently timeable** — and the lock can be taken per handler
instead of per tick, which alone ends the long holds.

**Step 2 — lazy needs and timers.** Convert threshold-kind sections to lazy values + threshold
timers (body/needs, cleanliness, plants, food, batteries). This removes the majority of per-tick
work, and is local to each system.

**Step 3 — character actors + movement loop.** Move agent dispatch to per-character event
handling (wake events already exist). Move movement to its own loop. Agents stop being a pool the
tick waits for; LLM responses arrive as events.

**Step 4 — entity store.** Replace the world blob with versioned per-entity records (Redis JSON,
write-behind to Postgres) behind `WorldView`; per-entity locks replace `_world_lock`; the read
model/view service replaces whole-world deltas.

**Step 5 — separate processes.** Event bus becomes Redis Streams with consumer groups; run
movement/perception, character actors, social/body and world services as separate containers in
`docker-compose.yml`. Because the boundaries already exist in-process after steps 1–4, this is a
deployment change, not a rewrite.

Steps 0–2 are low-risk and deliver most of the practical benefit (no long lock holds, far less
work per second). Steps 3–5 are the architectural goal and carry the real risk.

## 7. Recommendations on the open choices

- **Stay in Python/asyncio.** No framework. Actors are plain objects with an inbox and a state
  dict; the scheduler is a coroutine over a sorted set.
- **Bus: in-process asyncio queues first, Redis Streams at step 5.** Same interface; Redis is
  already in the stack.
- **State: Redis JSON per entity + Postgres write-behind.** Postgres stays the durable store.
- **Granularity of "own tick": per component group, not per module.** ~7 groups (character,
  movement, perception, social, body, world, view), not 261.
- **Keep `world` dict semantics inside a handler** via the façade so the existing systems code
  doesn't need rewriting.

## 8. What you gain

No global lock (and no 503s from it); a slow LLM only delays the one character waiting on it;
movement and cognition independent (smooth movement regardless of model speed); work scales with
*activity*, not with population × cadence; time scale handled once; failures isolated per
component; a replayable event log.

## 9. Decisions needed

1. Agree the target and the order (steps 0–2 first, then 3–5)?
2. In-process first (recommended) or straight to separate processes?
3. OK to introduce the `WorldView` façade so the 261 systems modules keep working while they
   migrate?
4. Is the three-tier consistency model (invariants above) acceptable -- strong inside one
   character, causal and re-validated for direct interactions, eventual for everything else?
   (review: replaces the earlier blanket "eventual".)
5. Do you want the event log/replay harness (step 0) built before anything else? I'd say yes.

## 10. Progress log

- **Step 0 (done, `4f4667e`)** — per-section tick profiling (`/admin/tick_profile`), section registry
  (`core/section_registry.py`), durable event log + handler timing + replay
  (`core/event_log.py`, `tools/replay_events.py`).
- **Step 1 (done, `e5f001d`)** — `core/clock.py` (time.hour/day/week/month), `core/scheduler.py`
  (durable timers), 71 recurring jobs extracted from `tick()` (`_tick_impl` ~850 → ~490 lines).
- **Step 2 (done)** — lazy needs: `systems/body_lazy.py`. The body is integrated on demand under the
  regime that held during the interval (asleep / awake / frozen / stimulant) using the existing
  `update_body_needs(dt=...)`; a per-character timer wakes the character at the moment its
  body-driven intentions would change, found by **forward-probing a copy of the body with the real
  update function and the real intention generator** (chunked, then bisected) — no threshold is
  duplicated. Per tick there is only an O(1) check (regime flip / touched / staler than 30 ticks).
  Equivalence test: `tests/test_body_lazy.py`.
  The same forward-probe technique applies to the other threshold-kind sections (cleanliness,
  plants, food aging, batteries, addictions, lt_needs).
- **Step 3 (done)** — character decisions as requests/responses: `brain/cognition_actor.py`. The agent thread
  pool, the 3-second wait budget and the abandon-and-lose-the-decision machinery are gone.
  `update_agent()` runs on the tick thread (nothing in it waits on a model); when a character has
  something to decide it records `cognition.pending`, builds the context on the tick thread and hands
  the model call to a worker that touches no world state; the answer returns as a `decision_ready`
  event and `process_decision()` re-validates it against the world as it is *then*. Late answers for
  someone who died / went off-grid are dropped; a request with no answer after 240 s is re-asked.
  Tests: `tests/test_cognition_actor.py`.
- **Step 4 (partial; "step 5" in chat)** — the per-character pipeline is now profiled (`agent:*` / `internal:*` /
  `economy:*` / `offgrid:*` marks in `/admin/tick_profile`). Measured on a populated world (4 characters,
  1200 ticks, ~0.6 ms per character-tick in total), the cost is concentrated in four derivations:
  `select_situation` 19%, `update_social_intentions` 16%, `update_expectations` 14%, `sort_intentions` 6%;
  everything else is ≤ 4% each and 95–100% of calls change nothing. Done: **`select_situation` is computed
  when a decision needs it** (in `build_context`), not every tick — this also fixes its history, which
  recorded a selection per *tick* into a 40-entry window, so novelty/cooldown (written for minutes) only ever
  saw the last 40 ticks. Not done, deliberately: the other derivations are pure functions of state that many
  systems write directly (relationships, emotion, lt_needs, expectations, intentions). Gating them exactly
  needs a *change notification* on those writes (dirty flags), otherwise a gate has to guess its inputs and
  silently changes behaviour — that is what the per-entity state store (versions + change events) provides,
  so it comes first; the derivations then become "recompute when my inputs' version changed".
- **State store, stage 1 (done; "step 6" in chat)** — `core/world_state.py`: the authoritative world is a
  resident dict in the tick process. Measured before: ~130 ms of every tick was persistence (23 ms load +
  59 ms validated serialise + 48 ms Postgres `jsonb_set`) and 210 ms every 30 ticks for the durable save —
  and it grows with world size, not with activity. Now: no per-tick load/serialise/DB write. Inside
  `world_lock()` (and the tick) `load_world()` returns the live world, so a route's load → mutate → save
  happens in place; outside it a reader gets a private snapshot copy rendered from JSON at most once per
  tick and only on demand; durable saves are write-behind (every 15 ticks serialised under the lock, written by a
  background thread) plus a synchronous save on shutdown. `/admin/world_state` shows the counters.
  Equivalence: `tools/diff_world_modes.py` runs the same seeded sim both ways (1500 ticks across a week
  boundary: identical except one "once per day" guard that only ever worked in the resident mode — the
  round trip had turned its tuple into a list). 112 s → 4.8 s for those 1500 ticks.
  Caveats: processes other than the server (docker-exec scripts) now read Postgres, which lags by up to 15
  ticks; a route that mutates the world and then errors out before saving now leaves its partial change in the
  live world (the old private copy was discarded).
- **State store, stage 2 (done; "step 7" in chat)** — per-entity versions and patch deltas
  (`core/entity_versions.py`). No proxies and no hooks on the thousands of write sites: a character
  is hashed key by key (JSON of each top-level key), so a changed key is exactly a changed hash;
  `version(kind,id)` and `last_changed(kind,id)` expose it. The few big, slow blobs nobody animates
  (LLM sessions, grievances, memories, ...) are "cold" and re-hashed only every 15 ticks, staggered per
  character (the selected character's are re-hashed every tick). The websocket used to send every
  dirty character whole every tick -- 176 KB/tick for two characters, ~90 KB each, mostly those blobs;
  it now sends a character whole on first sight and afterwards `{"__patch__": true, <changed keys>,
  "__deleted__": [...]}` relative to what *that* client holds (the frontend merges them). Measured live:
  24 deltas in 25 s = 116 KB instead of ~4.2 MB (-97%); 120 simulated ticks 20.8 MB -> 1.1 MB, and a
  client applying only patches ends identical to the server. The versions are also the change signal the
  derived per-character steps need (recompute when the version of the keys you read changed) -- not
  wired into those steps yet.
- **Derived steps, measured (done; "step 8" in chat)** — I tried gating `update_expectations` on its inputs and
  checked it with a differential run (same seeded sim, gate on vs off, fresh process each, diffed): it
  caught a real subtlety (a skipped run no longer re-appends each expectation's intention, which changes the
  order of exactly-tied intentions) and was fixed to be exactly equivalent — but a cheap-enough signature
  (tuple per expectation + household-derived tags + intention presence) cost as much as the step it
  skipped (~0.3 ms per character-tick), so the gate was **reverted**: at 2-100 characters the whole
  per-character pipeline is 0.5 ms per tick, and change-signalling only pays when it is nearly free.
  Kept: the harness (`tests/determinism.py`, `run_det.py`, `test_determinism.py`: seeded, fake clock, counter
  uuids, inline workers, `PYTHONHASHSEED=0`, fresh process per run) — the way to prove a future change
  (a gate, a refactor, a persistence mode) is behaviour-neutral; and a free win from the profile:
  `generate_social_intentions` computed `relationship_score(c, other)` and never read it (a fifth of that
  step, per pair, per tick) — removed, verified identical (0 differences over 1500 ticks).
  Also: REST read endpoints the frontend polls every second (`/api/household/characters|list`,
  `/api/events`) copied the whole world (~20 ms of JSON parsing) to read a few fields; `db.read_world()` lets a
  short read-only route use the live world under the lock without copying: 19 ms → 4 ms per call.
  And an operational fix: only the backend had a restart policy, so every Docker restart left the
  database, Redis and frontend down (the "map is empty" episodes) — all four services now `restart:
  unless-stopped`.
- **Where the time is now** — the per-tick cost is no longer where the architecture hurts: the tick runs
  in a few ms, persistence is write-behind, decisions are asynchronous, the websocket sends patches, and the
  lock is uncontended. What is still *structurally* centralised: one process owns the world, API routes that
  mutate it still run on request threads under the lock (52 call sites), and `update_agent()` still polls
  every step every tick. Remaining options, in order of value: (1) per-process component split (movement /
  cognition workers / API as separate containers) — needs the entity store behind a network boundary;
  (2) mutating routes as commands run by the tick owner (removes the lock; mechanical but touches 52
  sites); (3) turning the polled steps into event/timer handlers one at a time, each proven neutral with the
  determinism harness.
- **Container split, stage 1: cognition workers (done)** — the model round-trip for character decisions now
  runs in its own container(s). `core/cognition_queue.py` is the wire (Redis Streams: `cognition:req` with a
  consumer group, `cognition:res`; a worker's short-lived heartbeat key advertises it), `workers/cognition.py`
  is the worker (`python -m workers.cognition`; N threads, no database, no world state — it gets the
  character's context and recent turns and returns the decision, the prompt-log entries and the prompt
  size), and `brain/cognition_actor.py` chooses where each request runs (`COGNITION_MODE`: `local` /
  `remote` / `auto` = remote while a worker's heartbeat is current, in-process otherwise). A result-reader
  thread in the core turns answers into the same `decision_ready` event as before, so everything after it
  (re-validation against the world as it is now, `process_decision`) is unchanged. Failure behaviour:
  a worker that dies mid-request leaves it unacked and another worker takes it over after 150 s; requests
  carry a deadline and are dropped unanswered once nobody is waiting; if no worker is alive 20 s after a
  request went out the core runs it locally, and whichever answer comes second is ignored by the existing
  pending-id check. Stopping the worker container never stalls the sim. Scale with
  `docker compose up -d --scale cognition=N` (Ollama concurrency applies per worker process). Not yet
  shipped back: the LLM client's call-count/latency gauges stay per process (prompt log and prompt bytes
  are merged). Verified: `tests/test_cognition_split.py` (wire, redelivery, deadline, heartbeat, fallback,
  concurrency, failing model, duplicate result, real contexts strictly JSON-serialisable) and a live
  round trip through the worker container to Ollama. The other tests pin `COGNITION_MODE=local` so a live
  worker can never answer for them.
  Next in the split: background LLM jobs (`systems/bg_llm`) as a second worker type (done, below), then the
  API/gateway process once the 52 mutating routes are commands.
- **Container split, stage 2: background LLM jobs on workers (done)** — `systems/bg_llm.submit(key, fn, *args)`
  keeps its API, so none of the five call sites changed. The queue plumbing was generalised into
  `core/work_queue.py` (a `WorkQueue` per kind of work: streams, consumer group, heartbeat keys, redelivery,
  a result-reader thread) and `workers/common.py` (the shared worker loop); cognition now runs on both. For the
  five functions on `bg_llm.REMOTE_TASKS` (behaviour theories, account comparison, child imagination,
  household-summary narration, self-assessment — all pure model calls, plain JSON in and out) a submission
  goes to the `bg_llm` worker container(s) while one is alive and runs on the core's two pool threads
  otherwise; a function off the list, or arguments that aren't plain JSON, always run locally, and the
  worker refuses any task not on the list. Each submission carries a token: an answer whose token isn't the
  current one (re-submitted, or taken over by the local fallback after 20 s with no worker) is ignored. The
  police-feed RSS fetch also goes through bg_llm but is not a model call, so it stays local. Tested in
  `tests/test_bg_llm_split.py` (fallback, concurrency, allow-list, non-JSON args, failing call, expired
  deadline, stale token, prompt-log merge) and live: a self-assessment went core -> bg_llm container ->
  Ollama -> back in 17 s. `docker compose up -d --scale bg_llm=N`; Ollama concurrency is per worker process.
- **API gateway split, stages 1-2: commands and a read replica (done; websocket moved)** — the gateway is the
  same FastAPI app run with `SIM_ROLE=api` (compose service `api`, direct access on :8001). It runs no tick
  and owns no world; it does two things:
  *Mutations are commands* (`core/commands.py`). A route's body is decorated `@command("name")`; in the
  owner process (role `all`/`core`) the decorator does nothing, in a gateway it is replaced by a stub that
  sends the arguments over a Redis stream and returns the core's result (HTTP errors keep their status,
  pydantic arguments are rebuilt, a command has a 30 s deadline and a late one is never run). 43 routes
  converted — every route that held `world_lock()` or saved the world; the `Request`-bodied editor routes became
  plain dict-bodied sync routes (same URLs, same bodies). In a gateway `world_state.save()` raises, so a
  mutating route that was missed fails loudly instead of changing a copy.
  *Reads come from a replica* (`core/replication.py`). While a gateway's heartbeat is current the core
  publishes, after every tick and under the lock, one frame to a Redis stream: patches of the characters
  that changed (same per-key digests the websocket already used), dirty props/items/objects whole, any
  other top-level key whose digest changed (big slow ones every 10 ticks), and the dirty ids; every 15
  ticks or after a route saved the world everything is re-checked, so something nobody marked dirty is at
  most 15 ticks late. A zlib snapshot (~250 KB for this world) in a key bootstraps a new gateway; every
  operation is idempotent so a snapshot newer than the frames replayed after it is harmless; a gap or a
  new epoch (core restart) makes the gateway bootstrap again; the map (world_tiles) is shipped once per
  epoch and whenever the editor changes it, and definitions.json changes are noticed by mtime. The
  replica is installed as the gateway's resident world, so every existing `load_world()` / `read_world()`
  caller works unchanged, and frames are applied on the event-loop thread so a broadcast never sees the
  world change under it. With no gateway the core pays nothing.
  Measured (3 characters): publishing 16 ms mean per tick on the tick thread (most of it the existing
  per-key hashing of dirty characters, which the websocket used to pay per client), 52 KB mean frame
  (the stocks/market/timers keys dominate), 250 KB snapshot. Verified: `tests/test_commands.py`,
  `tests/test_replication.py` (a seeded 250-tick sim; the replica equals the core at every full pass; gaps,
  restarts, forced passes, add/remove of characters and keys), and live: gateway websocket vs core
  websocket carry the same snapshot and the same per-tick deltas, an `/admin/time_scale` posted to the
  gateway reaches the core and comes back through the replica, and the game renders from the gateway.
  Adopted so far: **only `/ws`** (frontend/nginx.conf sends it to the gateway and falls back to the core if
  the gateway is down; nginx resolves the name per request so it starts either way). REST stays on the core
  until each read route is checked for process-local state it reads (e.g. `/admin/cognition`, prompt logs,
  the tick profile, the middleware bridge's heartbeat, `/api/llm/logs` -- those must stay on the core or
  have their data shipped). Open items: the gateway has no `--reload` (restart `api` after code edits);
  its first boot rebuilds the map's lookup tables (tens of seconds); the selected-character cold keys
  can lag up to 15 ticks (the core used to hash them fresh each tick for that client).
- **API gateway split, stage 3: the safe REST routes moved (done)** — nginx now sends `/api/household/*`,
  `/api/overview/*`, `/api/finances/*`, `/api/dependents/*`, `/api/events`, `/api/conversation/*`, `/api/state`,
  `/view*`, `/director*` and `/ws` to the gateway (POSTs under those prefixes arrive as commands). Chosen by
  reading every route for process-local core state: those that read none were compared against the core
  (same JSON apart from a tick's drift) before being moved. Left on the core: `/admin/*` (cognition,
  tick profile, event log, LLM gate, world_state stats), `/debug/*` (prompt logs, sandbox worlds, LLM
  stats), `/api/editor/*`, the middleware bridge, `/api/llm/logs`, asset/mesh/anim banks, static pages.
  Failure behaviour: 502/503 from the gateway (down, no world yet, core away) retries the request against
  the core, which still serves every route itself; 504 is not retried because a command may have run.
  Read-your-writes: a command's result carries the frame number that will contain its changes, and the
  gateway holds the response until its replica has applied it (`Feed.wait_applied`, 5 s cap), so the
  refetch the UI does right after a save sees it -- checked through nginx (rename a household, list it
  immediately, rename back). Ongoing rule for new routes: a read that touches process-local state, or a
  mutation that isn't a `@command`, must stay on the core.
- **Publish cost cut (done)** — the per-tick cost of feeding gateways on the tick thread went from a 20.8 ms
  mean (14 ms on an ordinary tick, 39 ms on every 15th) to **8.1 ms mean, 6.7 ms median** (3 characters),
  by three changes. (1) `entity_versions._digest`: a scalar is its own digest (tagged with its type) and an
  empty list/dict is a constant, so about three quarters of a character's ~100 keys are no longer
  serialised; the rest use one shared JSON encoder instead of building one per call (the websocket's
  patches get the same speed-up). (2) No more all-at-once "full pass" every 15 ticks: each character's
  rarely-changing keys are re-checked at its own staggered tick, entity lists and big keys likewise, so the
  spike is spread out; a route that saved the world still forces an immediate look at everything, and a
  character not yet known to the replica is picked up at once. Unmarked changes still reach the replica
  within 15 ticks (tested: 13). (3) A changed top-level key's JSON, already produced for the digest, is
  spliced into the frame instead of being serialised a second time. The rest is the hashing of what a
  tick really changed (~1 ms per 100 KB); going lower needs change tracking at the writers.
  Also found by this work: a test that ran the tick function against a throwaway world published it into
  the live channel while a gateway was subscribed, and the gateway followed it into a re-sync loop.
  A channel now has one owner (`<prefix>:owner`, renewed every 2 s, released on shutdown): a second
  publisher stays silent. Remaining known flake (not from this change, seen once in six runs):
  `test_determinism` "ordinary afternoon" diffed one household event's `room_label` (a floorplan cache
  that is filled lazily); worth a look when determinism work resumes.

