# SIMSLAND ARCHITECTURE MAP

---

# NEED ARCHITECTURE

There are exactly two need structures on a character. No others.

## c["body"] — Physical simulation (0–100 int per field)

Authoritative: `systems/body.py`

Fields:
- `hunger` — 0=full, 100=starving
- `hydration` — 100=hydrated, 0=dehydrated
- `bladder` — 0=empty, 100=urgent
- `bowels` — 0=empty, 100=urgent
- `fatigue` — 0=rested, 100=exhausted
- `sleep_debt` — cumulative deprivation (raises stress / emotional temperature)
- `hygiene` — 100=clean, 0=filthy
- `odor` — 0=fresh, 100=pungent; lags hygiene with non-linear accumulation
- `mouth_hygiene` — 100=fresh, 0=bad breath; decays, reset by tooth brushing
- `recent_intake` — spikes on eat/drink, decays ~3 hrs; accelerates bladder fill
- `stomach_discomfort` — 0–100; raised by overeating, illness
- `pain` — 0–100
- `sickness` — 0–100

Urgency rules (body_intentions.py):
- bladder > 85 → interrupt at priority 97 (abort current activity)
- fatigue > 90 → interrupt at priority 98
- bowels > 80 → interrupt at priority 95
- hydration < 30 → priority 85
- hygiene shower threshold: lazy=18, vain/disciplined=50, default=30

Helper functions for 0–1 normalised consumers:
- `body_energy(c)` — 1 − fatigue/100
- `body_hunger_norm(c)` — hunger/100
- `body_hygiene_norm(c)` — hygiene/100

`ensure_body(c)` migrates old characters and removes any legacy `c["needs"]` key.

## c["lt_needs"] — Long-term psychological drives

Authoritative: `systems/lt_needs.py`

12 weekly drives distributed via a 100-point trait-adjusted budget:

| Drive        | Default pts | Notes                    |
|--------------|-------------|--------------------------|
| socialize    | 20          | replaces old "social"    |
| exercise     | 15          |                          |
| creative     | 10          |                          |
| nature       | 10          |                          |
| learning     | 8           |                          |
| romance      | 8           |                          |
| intimacy     | 7           |                          |
| solitude     | 7           |                          |
| spirituality | 5           |                          |
| purpose      | 5           |                          |
| adventure    | 3           |                          |
| play         | 2           | replaces old "fun"       |

Each drive has `frustration` (0–1). Frustration accrues when neglected >1 week, proportional to point weight. Cleared by `satisfy_lt_need()`. Acts as a weight that biases AI intention generation — never triggers hard interrupts.

`c["needs"]` does not exist. It has been fully removed.

---

# COGNITION

Authoritative:
- `brain/llm_brain.py`
- `brain/context_builder.py`

Responsibilities:
- subjective reasoning and language generation
- emotional state interpretation
- strategy selection
- conversation decisions
- intention interpretation

NOT responsible for:
- movement, animation, pathfinding, interaction timing

---

# EMOTION & MOOD

Authoritative: `brain/emotion.py`

## Emotional temperature (0–100)
Continuous float. 15 labelled bands: furious (90), angry (78), annoyed (65), anxious (55), irritable (45), content (35), calm (22), etc.

Factors:
- lerps toward trait baseline each tick (volatility-weighted)
- stress > 40 pushes temperature up
- sleep_debt > 25 pushes temperature up
- pinned to active mood's `emotional_temperature_range` while a mood is active

## Persistent moods
Defined in `definitions.json → mood_templates`. Each mood has:
- `name`, `description`, `polarity` (positive / neutral / negative)
- `emotional_temperature_range` — pins the temperature band while active
- `triggers` — conditions evaluated each tick (stress, body fields, lt_need frustration, life event flags)
- `duration_ticks` — how long the mood persists
- `behavior_flags` — hints for LLM (e.g. "avoid_conflict", "seek_comfort")
- `need_modifiers` — shifts lt_need frustration while active (keys: "social"→socialize, "fun"→play)

15 built-in moods: content, cheerful, playful, focused, romantic, restless, lonely, anxious, irritable, sad, grieving, depressed, furious, embarrassed, energized.

Life event flags (set via `set_mood_event(c, key)`):
- `_recent_positive_event`, `_negative_life_event`, `_major_loss`, `_social_failure`

---

# INTENTIONS

Authoritative: `c["active_intentions"]` list

Sources:
- body.py / body_intentions.py — urgency-based physical interrupts
- social_intentions.py — relationship-weighted social drives
- lt_needs — frustration biases intention priority
- schedules, events, emotions

Interruption: when a body field exceeds its threshold, the character aborts their current activity, handles the need (toilet, drink, sleep, etc.), then resumes.

---

# ACTIVITIES

Authoritative: `systems/activities.py`

Phases: start → walking → arriving → using → finishing → complete

Completion handlers in `body.py`:
- `on_sleep_complete(c, duration_minutes)`
- `on_shower_complete(c)` / `on_bath_complete(c)`
- `on_brush_teeth_complete(c)` / `on_wash_hands_complete(c)`
- `on_eat_complete(c, nutrition)` / `on_drink_complete(c)`
- `on_toilet_complete(c)`

---

# SOCIAL

## Relationships
Authoritative: `brain/relationships.py`

Fields per pair: friendship, trust, attraction, hostility, comfort, resentment, familiarity, romantic_interest, dependency, chemistry, state.

## Social intentions
`systems/social_intentions.py` — generates contact/visit/flirt/comfort/avoid/apology/gossip intentions weighted by relationship scores and `socialize` lt_need frustration.

## Odor social pressure
`systems/social_odor.py` — nearby characters (Manhattan dist ≤ 4) perceive each other's odor via perception snapshots. Generates `suggest_hygiene` intentions at odor > 40 or > 65. Runs every 20 ticks.

## Grievances
`systems/grievances.py` — accumulated slights; decays over time; emits `confrontation_desired`.

## Conflict pipeline
`systems/conflict_pipeline.py` — escalation from grievance → argument → confrontation → resolution.

## Social contracts
`systems/social_contracts.py` — commitments between characters; emits `contract_violated`.

---

# ECONOMY

## Market
`systems/market.py` — unified product catalog with category multipliers and item price lookup. `init_market_catalog()` at world load.

## Procurement
`systems/procurement.py` — buy from catalog, `make_item()` for discrete goods, assembly boxes for props. Uses `body_energy(c)` for fatigue gating.

## Stocks
`data/stocks.py` — 40 fictional companies.
`systems/stock_market.py` — price simulation with news hooks.
`systems/investments.py` — sim trading behavior.

## Services
`systems/services.py` — hired service engine (cleaning, childcare, companionship, etc.).
`data/services.py` — service catalog with pricing.
Companionship satisfies `socialize` and `play` lt_needs via `satisfy_lt_need()`.

---

# ITEMS & CLOTHING

## Items
`data/item_templates.py` — all physical item templates with `base_price`, `resource_type`, `size`.
`systems/personal_items.py` — inventory management.
`make_item()` factory in `systems/procurement.py`.

## Clothing
`systems/clothing.py` — slot system (head, torso, legs, feet, hands), `put_on()`, `take_off()`, dirty state.

## Assembly
`systems/assembly.py` — assemble props from components.

---

# HOUSING

## Households
`systems/households.py` / `household_resources.py` — shared resources, bills, upkeep, domestic economy.

## Walls
`systems/walls.py` — wall entities with `load_bearing`, `paint`, `orientation`. Never remove a load-bearing wall.

## Containers
`systems/containers.py` — generic container + bucket sub-type. Buckets hold paint or water.

---

# WORLD SIMULATION

## Cooking
`systems/cooking_process.py` — multi-stage recipe execution. Every 10 ticks.

## Traffic / postal / deliveries
`systems/traffic.py`, `systems/postal_service.py`, `systems/deliveries.py`.

## Law & order
`systems/law.py` — jail, trials, arrests.
`systems/emergency.py` — incident pipeline (trigger → resolve → arrest).

## Jobs
`systems/jobs.py` — listings, firing, interviews.

## Politics / world events
`systems/politics.py`, `systems/crisis.py`, `systems/faction_ai.py`, `systems/influence.py`, `systems/hierarchy.py`.

---

# MOVEMENT & NAVIGATION

## Movement
`systems/movement.py` — route traversal, interpolation, segment switching, arrival detection. Does NOT choose destinations.

## Navigation
`systems/navigation.py` + `systems/world_pathfinding.py` — route generation, room connectivity, outdoor/multi-building paths.

## Transforms
`systems/transforms.py` — local/world coordinate conversion, rotation, footprint and anchor projection. Single source for all rotation math.

## Anchors
`systems/anchors.py` — local-space in templates, world-space at runtime.

## Occupancy
`systems/occupancy.py` — reservations, queues, occupancy release, interaction ownership.

## Affordances
`systems/affordances.py` — capability discovery, interaction filtering, usable props.

---

# TICK SCHEDULE

Cadence defined in `core/tick_schedule.py`:

| System             | Every N ticks | Notes                         |
|--------------------|---------------|-------------------------------|
| perception         | 5             |                               |
| attention          | 5             |                               |
| conflicts          | 5             |                               |
| cooking            | 10            |                               |
| deliveries         | 10            |                               |
| service_workers    | 10            |                               |
| item_knowledge     | 10            |                               |
| memory_decay       | 15            |                               |
| polarization       | 15            |                               |
| relationships      | 15            |                               |
| grievances         | 15            |                               |
| market             | 20            |                               |
| household_monitor  | 20            |                               |
| social_odor        | 20            | odor pressure scan            |
| health             | 30            |                               |
| lt_needs           | 30            | frustration accrual           |
| traffic            | 30            |                               |
| postal             | 30            |                               |
| arrests            | 30            |                               |
| contract_checks    | 60            |                               |
| appliance_degrad   | 60            |                               |
| job_market         | 60            |                               |
| trials             | 60            |                               |
| news               | 60            |                               |
| evictions          | 120           |                               |
| election           | 300           |                               |
| faction            | 300           |                               |
| hierarchy          | 300           |                               |
| migration          | 300           |                               |
| weekly             | Monday 00:00  | schedules, lt_need distribute |

Body needs (`update_body_needs`) run every tick inside `update_internal_state`.

---

# DEFINITIONS (definitions.json)

All data-driven templates. Editable via the frontend definitions editor.

| Key                | Description                                              |
|--------------------|----------------------------------------------------------|
| prop_templates     | Furniture and interactive objects                        |
| item_templates     | Portable physical items                                  |
| recipe_templates   | Cooking recipes                                          |
| service_templates  | Hired services catalog                                   |
| job_templates      | Employment types                                         |
| company_templates  | Business types                                           |
| need_templates     | Long-term need drive definitions                         |
| activity_templates | Sequences of interactions for structured activities      |
| mood_templates     | 15 persistent mood states with triggers and durations    |

---

# DEPRECATED

Do not use. Will be removed.

- `intention.py` / `intentions.py`
- `activity_runtime.py`
- `planner.py` heuristic planning
- `schedule.py` legacy intention queues
- `c["needs"]` — fully removed; was a legacy `{social, fun}` dict
