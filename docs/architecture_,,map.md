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
- `stomach_discomfort` — 0-100; raised by overeating, illness
- `pain` — 0-100
- `sickness` — 0-100

Urgency rules (body_intentions.py):
- bladder > 85 -> interrupt at priority 97 (abort current activity)
- fatigue > 90 -> interrupt at priority 98
- bowels > 80 -> interrupt at priority 95
- hydration < 30 -> priority 85
- hygiene shower threshold: lazy=18, vain/disciplined=50, default=30

Helper functions for 0-1 normalised consumers:
- `body_energy(c)` — 1 - fatigue/100
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

Each drive has `frustration` (0-1). Frustration accrues when neglected >1 week, proportional to point weight. Cleared by `satisfy_lt_need()`. Acts as a weight that biases AI intention generation — never triggers hard interrupts.

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

## Emotional temperature (0-100)
Continuous float. 15 labelled bands: furious (90), angry (78), annoyed (65), anxious (55), irritable (45), content (35), calm (22), etc.

Factors:
- lerps toward trait baseline each tick (volatility-weighted)
- stress > 40 pushes temperature up
- sleep_debt > 25 pushes temperature up
- pinned to active mood's `emotional_temperature_range` while a mood is active

## Persistent moods
Defined in `definitions.json -> mood_templates`. Each mood has:
- `name`, `description`, `polarity` (positive / neutral / negative)
- `emotional_temperature_range` — pins the temperature band while active
- `triggers` — conditions evaluated each tick (stress, body fields, lt_need frustration, life event flags)
- `duration_ticks` — how long the mood persists
- `behavior_flags` — hints for LLM (e.g. "avoid_conflict", "seek_comfort")
- `need_modifiers` — shifts lt_need frustration while active (keys: "social"->socialize, "fun"->play)

15 built-in moods: content, cheerful, playful, focused, romantic, restless, lonely, anxious, irritable, sad, grieving, depressed, furious, embarrassed, energized.

Life event flags (set via `set_mood_event(c, key)`):
- `_recent_positive_event`, `_negative_life_event`, `_major_loss`, `_social_failure`

---

# INTENTIONS

Authoritative: `c["active_intentions"]` list

Sources:
- `body.py` / `body_intentions.py` — urgency-based physical interrupts
- `social_intentions.py` — relationship-weighted social drives
- `lt_needs` — frustration biases intention priority
- `systems/hobbies.py` — generates `plan_hobby_session` intentions when hobby lt_need frustration rises
- `systems/social_events.py` / `systems/calendar_events.py` — event-driven intentions (RSVP, attend, prep)
- schedules, emotions

Interruption: when a body field exceeds its threshold, the character aborts their current activity, handles the need (toilet, drink, sleep, etc.), then resumes.

---

# ACTIVITIES

Authoritative: `systems/activities.py`

Phases: start -> walking -> arriving -> using -> finishing -> complete

Each activity is defined as a template in `definitions.json -> activity_templates` with ordered `steps`. Each step references an `interaction` id, `target_tags` (prop tags to resolve against), and `duration_minutes`. Steps chain via `requires` — a step won't start until its dependency completes.

141 activity templates across two groups:
- 52 generic — daily routines (hygiene, food, rest, social, work, transport, chores, finance, romance)
- 89 hobby — one per hobby, keyed `hobby_<id>`, linked via `hobby_id` field

Completion handlers in `body.py`:
- `on_sleep_complete(c, duration_minutes)`
- `on_shower_complete(c)` / `on_bath_complete(c)`
- `on_brush_teeth_complete(c)` / `on_wash_hands_complete(c)`
- `on_eat_complete(c, nutrition)` / `on_drink_complete(c)`
- `on_toilet_complete(c)`

---

# INTERACTIONS

Authoritative: `definitions.json -> interaction_templates`

107 interaction templates. Each defines:
- `name`, `description`, `category`
- `duration_ticks` — how long the interaction runs
- `requires_prop_tags` — list of prop tags; runtime resolves the nearest matching prop
- `requires_item_category` — optional; character must hold an item of this category
- `off_grid` — if true, no in-world prop is needed (activity happens at an off-map location)
- `body_effects` — dict of body field deltas applied on completion
- `stress_delta` — applied to emotional temperature
- `satisfies_lt_needs` — list of lt_need keys cleared/reduced on completion
- `handler` — string key looked up in `action_router.py`
- `animations` — `{ start: [], loop: [], stop: [] }` animation clip names

Categories: basic, hygiene, food, rest, computer, phone, transport, social, art, music, performing_arts, entertainment, media, nature, exercise, collections, sports, history, gambling, games, culinary, literary, electronics.

---

# PROPS

Authoritative: `definitions.json -> prop_templates`

134 prop templates. Each defines:
- `name`, `category`, `model` (null = renders as placeholder cube)
- `footprint` — list of `{dx, dy}` tile offsets the prop occupies
- `anchors` — list of `{name, interaction}` interaction points in local space
- `storage` — `{slots, accepted_categories}` or null; props with storage are containers
- `tags` — string tags used by interaction `requires_prop_tags` resolution
- `default_state` — initial runtime state dict (e.g. `{on: true, brightness: 1.0}` for lights)
- `isSurface` — true if items placed on this prop render on top (tables, desks); storage still applies
- `isDecorative` — true if the prop has no interaction anchors (wall art, plants, room divider, etc.)

Lighting props (`category: "lighting"`) always have `toggle_light` and `adjust_brightness` anchors plus `default_state: {on, brightness}`.

Storage props expose `open_storage` / category-specific grab anchors. Surface props (tables) are containers with `isSurface: true` — the renderer draws items on top rather than hiding them inside.

---

# ITEMS

Authoritative: `definitions.json -> item_templates`

391 item templates across categories: clothing, sports_equipment, kitchenware, electronics, food, hygiene, tools, office_supplies, misc, outdoor_gear, drink, cleaning, dishware, hobby_supplies, music_instrument, decor, art_supplies, linen, games, books_media, documents, appliance, groceries.

Each template:
  name, category, size, base_price, stackable, max_stack, consumable, uses

## Default item interactions
Defined in `definitions.json -> default_item_interactions`. Applied universally to every item instance:

| Interaction          | requires_target | target_type               |
|----------------------|-----------------|---------------------------|
| pick_up              | false           | —                         |
| drop                 | false           | — (places at character tile) |
| put_in               | true            | container (any prop with storage, including isSurface tables) |
| put_in_pocket        | false           | —                         |
| retrieve_from_pocket | false           | —                         |
| give                 | true            | character                 |
| take                 | false           | —                         |
| throw                | true            | position_or_character     |
| destroy              | false           | —                         |

`isSurface` is a renderer hint only — the system routes `put_in` to any prop with storage slots.

## Item instance system
`systems/personal_items.py` — inventory management, item states, placed_items, location tracking.
`make_item()` factory in `systems/procurement.py`.

## Clothing
`systems/clothing.py` — slot system (head, torso, legs, feet, hands), `put_on()`, `take_off()`, dirty state.

## Assembly
`systems/assembly.py` — assemble props from components.

---

# HOBBIES

Authoritative: `systems/hobbies.py`
Templates: `definitions.json -> hobby_templates`

85 hobby templates across 13 categories: art, music, performing_arts, film_media, nature, exercise, collections, sports, history, gambling, games, culinary, literary.

Each hobby template fields:
- `name`, `category`
- `required_props` — prop tags that must exist in the home or off-grid venue
- `required_items` — item categories the character needs in inventory
- `off_grid` — bool; activity takes place at an off-map location
- `overnight` — bool
- `min_days`, `max_days` — session length bounds (null = single session)
- `min_participants`, `max_participants`
- `suggest_to_household` — auto-derived from `min_participants > 1`
- `annual_cost` — billed weekly via economy
- `home_props_any` — prop tags; if household has any, hobby can be done at home

## Hobby economy
`systems/economy.py` `apply_expenses()` — each member's hobbies contribute `annual_cost / 52` weekly. Summed per household, added to `bills_due` as a `hobbies` breakdown line. Runs Monday 00:00.

## Hobby context
`brain/context_builder.py` `_build_hobbies_context()` -> `systems/hobbies.py` `build_hobby_context()`.

---

# SOCIAL EVENTS

Authoritative: `systems/social_events.py`

Event lifecycle: draft -> published -> RSVPs -> active -> completed/cancelled.

Each event: `title`, `category`, `location_type`, `start_ts`/`end_ts`, `organizer`, `co_organizers`, `max_attendees`, `cost_per_person`, `dress_code`, `prep_requirements`, `popularity`, `tags`, `visible_to`.

Action router entries: `social_event_plan`, `social_event_rsvp`, `social_event_attend`, `social_event_comment`, `social_browse_events`.

## Calendar events
`systems/calendar_events.py` — birthdays, holidays, anticipatory intentions.

Birthdays stored on `c["birthday"]`. Calendar system generates anticipatory intentions (buy gift, plan party) in days leading up. Runs weekly cadence.

---

# PHONE

Authoritative: `systems/phone.py`

Battery drains per tick; charges via `wall_socket` prop (tag: `power_outlet`). Low battery triggers a `charge_phone` intention.

Action router entries: `phone_call`, `phone_answer`, `phone_send_text`, `phone_read_text`, `phone_check`.

---

# SOCIAL

## Relationships
Authoritative: `brain/relationships.py`

Fields per pair: friendship, trust, attraction, hostility, comfort, resentment, familiarity, romantic_interest, dependency, chemistry, state.

## Social intentions
`systems/social_intentions.py` — generates contact/visit/flirt/comfort/avoid/apology/gossip intentions weighted by relationship scores and `socialize` lt_need frustration.

## Odor social pressure
`systems/social_odor.py` — nearby characters (Manhattan dist <= 4) perceive each other's odor. Generates `suggest_hygiene` intentions at odor > 40 or > 65. Runs every 20 ticks.

## Grievances
`systems/grievances.py` — accumulated slights; decays over time; emits `confrontation_desired`.

## Conflict pipeline
`systems/conflict_pipeline.py` — escalation: grievance -> argument -> confrontation -> resolution.

## Social contracts
`systems/social_contracts.py` — commitments between characters; emits `contract_violated`.

---

# ECONOMY

## Weekly expenses
`systems/economy.py` `apply_expenses()` — runs Monday 00:00. Issues a `bills_due` entry per household with breakdown:
- `fixed_home` — rent + utilities + gasoline + internet (scaled by `cost_of_living_index`)
- `food` — 80 x n_members x cost_of_living_index
- `hobbies` — sum of each member's hobby `annual_cost / 52`

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
`systems/emergency.py` — incident pipeline (trigger -> resolve -> arrest).

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

| System             | Every N ticks | Notes                                       |
|--------------------|---------------|---------------------------------------------|
| perception         | 5             |                                             |
| attention          | 5             |                                             |
| conflicts          | 5             |                                             |
| cooking            | 10            |                                             |
| deliveries         | 10            |                                             |
| service_workers    | 10            |                                             |
| item_knowledge     | 10            |                                             |
| memory_decay       | 15            |                                             |
| polarization       | 15            |                                             |
| relationships      | 15            |                                             |
| grievances         | 15            |                                             |
| market             | 20            |                                             |
| household_monitor  | 20            |                                             |
| social_odor        | 20            | odor pressure scan                          |
| health             | 30            |                                             |
| lt_needs           | 30            | frustration accrual                         |
| traffic            | 30            |                                             |
| postal             | 30            |                                             |
| arrests            | 30            |                                             |
| contract_checks    | 60            |                                             |
| appliance_degrad   | 60            |                                             |
| job_market         | 60            |                                             |
| trials             | 60            |                                             |
| news               | 60            |                                             |
| evictions          | 120           |                                             |
| election           | 300           |                                             |
| faction            | 300           |                                             |
| hierarchy          | 300           |                                             |
| migration          | 300           |                                             |
| weekly             | Monday 00:00  | schedules, expenses, lt_need distribute, birthdays |

Body needs (`update_body_needs`) run every tick inside `update_internal_state`.

---

# DEFINITIONS (definitions.json)

All data-driven templates. Editable via the frontend definitions editor.

| Key                       | Count | Description                                                        |
|---------------------------|-------|--------------------------------------------------------------------|
| prop_templates            | 134   | Furniture and interactive objects (anchors, storage, tags)         |
| item_templates            | 391   | Portable physical items                                            |
| default_item_interactions | 9     | Universal item actions (pick_up, drop, put_in, give, throw, etc.)  |
| hobby_templates           | 85    | Hobby definitions (props, items, cost, participants, off_grid)     |
| interaction_templates     | 107   | Atomic interactions with prop requirements, body effects, anims    |
| activity_templates        | 141   | Multi-step activity sequences (52 generic + 89 hobby)              |
| recipe_templates          | —     | Cooking recipes                                                    |
| service_templates         | —     | Hired services catalog                                             |
| job_templates             | —     | Employment types                                                   |
| company_templates         | —     | Business types                                                     |
| need_templates            | 12    | Long-term need drive definitions                                   |
| mood_templates            | 15    | Persistent mood states with triggers and durations                 |

---

# DEPRECATED

Do not use. Will be removed.

- `intention.py` / `intentions.py`
- `activity_runtime.py`
- `planner.py` heuristic planning
- `schedule.py` legacy intention queues
- `c["needs"]` — fully removed; was a legacy `{social, fun}` dict
- `data/item_templates.py` — superseded by `definitions.json -> item_templates`
