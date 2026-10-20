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
- **Next** — step 3: character actors (replace the agent pool / per-tick `update_agent`), then the
  per-entity state store.
