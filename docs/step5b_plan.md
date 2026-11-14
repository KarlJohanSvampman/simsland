# Step 5b — separate processes: where we are and the choice to make

Status: plan, for a decision. Written after steps 0–5a and CPL phases 1–5 (branch `ccr-f323b246-sykoxh`).

## Already separate

| process | role | how it talks to the rest |
|---|---|---|
| `backend` (`SIM_ROLE=core`) | the only writer: the simulation, commands, the world replica publisher | owns the resident world |
| `api` (`SIM_ROLE=api`, any number) | HTTP and websocket; reads a replica of the world | commands over Redis streams (`core/commands.py`); replica frames (`core/replication.py`) |
| `cognition` (any number) | model calls for decisions | Redis work queue (`core/work_queue.py`), results come back as `decision_ready` |
| `bg_llm` | background model work (tags, theories, summaries) | Redis work queue |

So the slow, blocking part (the model) and the many-clients part (HTTP) are already out of the core. What is
still one process is the simulation itself: movement and perception, character updates, social and body, world
services.

## What the core costs now

Measured on the 5-character test world, social run, 3,000 ticks:

- **0.54 ms per tick** on average; the slowest tick took 59 ms.
- Time by kind: timers 0.72 s, character steps 0.60 s, continuous work 0.17 s, everything else under 0.1 s.
- The biggest sections are the waiting-activity checks (5 ms when active) and building a character's context
  (1.7 ms per decision).

After 5a, work scales with *activity*, not population × cadence. Roughly: at 50× speed a tick has 20 ms, so the
core saturates somewhere around 150–200 active characters. Below that, splitting the simulation across processes
buys isolation, not speed.

## The choice

**A. One writer, compute moved out (recommended first).** The core stays the single writer and sequencer:
determinism, the entity store, locks and the replica all stay as they are. Pure compute moves to worker processes
that read the replica and send back *proposals* (as commands do today), which the core validates and applies:

1. building a character's decision context (now 1.7 ms each, on the core) → the cognition workers, from the
   replica;
2. perception and the who-is-near model → a perception worker that publishes each character's view;
3. world services (market, job market, news, elections, traffic, post) → a world-services worker whose results
   are applied as commands.

*Gain:* the core does only bookkeeping and applying, maybe 5–10× headroom. Each piece ships alone and is
checked with the determinism harness (a worker run inline must give the same world). *Risk:* low to medium.
Proposals computed on a slightly stale replica must be re-validated, the same way decisions already are.

**B. Partitioned ownership.** Several writers, each owning a set of entities (by household or by area). Writes to
an entity another process owns become messages to it. Per-entity locks (step 4) and command entity declarations
(5a) are the groundwork for this. *Gain:* scales out without a ceiling. *Risk:* high. Cross-partition interactions
(a conversation between two households, a fight, a shared shop) need distributed coordination. The ~325 systems
modules assume they can touch any entity, and the determinism harness can't check a multi-writer run the same way.

**C. Stop here.** Keep the current split (core, api, cognition, bg_llm), and spend the effort on the open CPL
items and the real-model test. Revisit when a world large enough to need it exists.

## Recommendation

A, in the order above (context building first: it is the biggest per-decision cost and has the cleanest boundary
with the cognition worker that already exists). Keep B as the long-term option once A's proposal-and-validate
path is proven.

## Decision (2026-11-14): B, partitioned ownership, designed for tens of characters

### Design

- **Partitions.** Partition 0 is today's core. It owns the world-level keys and services, and the entities no
  household owns: conversations, CPL conversations and requests, public props. Each further partition owns a set of
  households: the households, their members (characters), and the props in their buildings. The owner map lives
  on the world (`world["_owners"]`) and can be rebalanced (`core/ownership.py`).
- **Every process holds the whole world.** Its own entities are authoritative; the rest is a replica, kept by the
  replication frames the other partitions publish (`core/replication.py`, today one publisher; then one per
  partition, each publishing only what it owns).
- **A unit of work runs where its entity lives.** A character's update, its PERCHAR jobs and its timers run in the
  partition that owns the character. World services run in partition 0.
- **Writes to someone else's entity become patches.** The WorldView façade already sees which entities a unit
  reaches. At the end of the unit, for each entity it reached but doesn't own, the change is computed as a
  field-level patch (`core/entity_patch.py`) against the replica copy as it was when the unit started. The patch
  is sent to the owner, applied there in arrival order, and re-validated by the owner where a system asks for it
  (the three-tier consistency model: strong within an entity, causal for direct interactions, eventual for the
  rest). The patched entity then comes back to everyone in the owner's next frame.
- **Conflicts.** A patch touches only the paths that unit changed, so two partitions editing different fields of
  the same entity both land. The same path changed by both: the owner's order decides (the later-arriving patch
  wins), and appends to a list are merged rather than replaced (memories, logs).

### Slices

1. Ownership map + entity patches (diff, apply, merge rules), with tests.
2. Two partitions in one process: two world copies, units routed by owner, patches exchanged inline. Checked
   against the single-writer run with the determinism harness (same outcomes where no two partitions race; where
   they do, the conflict rule is visible in the diff).
3. Real processes: per-partition publisher and feed, patches over Redis streams, `SIM_PARTITION=n` and the
   docker-compose services.
4. Rebalancing: moving a household between partitions (hand over its entities, then the owner map).
