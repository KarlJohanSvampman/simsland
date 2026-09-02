# SIMSLAND ARCHITECTURE MAP

For step-by-step guides (using the GUI tools, adding templates, the
Blender→.glb pipeline, anchors/animations), see `docs/wiki/README.md`
instead — this document is a technical reference for how the simulation's
systems work, not a how-to.

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

# HEALTH & INJURY

Authoritative: `systems/health.py`

## c["health_state"] — per-bodypart damage/disease engine
Separate from `c["body"]` above. Tracks 9 body parts (`head`, `neck`, `chest`,
`abdomen`, `pelvis`, `left_arm`, `right_arm`, `left_leg`, `right_leg`), each
with `hazards` (a dict of active `health_hazard_templates` instances, each
`{treated, hazard_template, current_stage, ...}`), `severity_level`
(`None`/`low`/`medium`/`severe`), and `functional_status`
(`normal`/`impaired`/`unusable`). Non-bodypart-localized hazards live in
`health_state["systemic_hazards"]`. Also tracks `active_emergencies` (e.g.
`bleeding`, `unconscious`, `coma`, `severe_trauma`), `total_blood_lost`, and
`doctor_visits_needed`.

**There is no unified "pain" field or mechanic.** It existed as
`health_state["pain"]` (0-100, fed by violence/disease/neglect) through one
prior round and was fully removed — see DEPRECATED.

## Injury & hazard pipeline
- `apply_injury(char, world, injury_template_key, cause, tick)` — the single
  entry point for a real wound. Rolls `injury_templates[key]`'s
  `possible_body_parts`/`possible_hazards`, writes the target body part.
- `treat_body_part(char, world, body_part, method)` — first_aid/hospital/
  ambulance treatment; marks matching-`treatable_by` hazards `treated`
  (halves future escalation, does not instantly cure).
- `tick_health_hazards(char, world)` — untreated, non-superficial hazards
  accumulate `escalation_per_tick` and step `severity_level` up a tier
  (`low → medium → severe`) every 100 points accumulated; can roll a death
  check once the character's overall tier is `critical`.
- `_tick_disease_symptom` / `tick_hazard_manifestations` — daily symptom
  selection + finer-grained periodic manifestations (gestures, contagion
  bursts, locomotion restriction) for `physical_health_templates` conditions.

## compute_severity(char) → (score, tier)
Aggregates several independent signals (active_emergencies severity,
per-bodypart severity_level + hazard treated-state, hazard `current_stage`,
condition `severity_index`, `total_blood_lost`) into one 0-100 score via a
worst-signal-weighted blend, bucketed into 5 tiers: `healthy`, `mild`,
`moderate`, `severe`, `critical` (`dead` if not alive).

## apply_severity_consequences(char, world)
The real posture/movement authority. Sets `posture = "incapacitated"` for
unconscious/coma/dead; `"crawling"` when tier is `critical` or both legs are
`functional_status: "unusable"`; reverts to `"standing"` once neither
condition holds. This is the ONLY place posture gets set from health state —
`action_router.py::_movement_blocked()` and `movement.py` both gate on
`posture == "incapacitated"`. A `severe`/`critical` tier auto-reports a
medical-emergency incident (systems/emergency.py's existing 911 bridge).

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

## Cognition core + trait/belief adoption
Every character gets exactly one cognition-core trait at generation
(Logical/Balanced/Self-Aware — `character_gen.py`, exempted from the
learned-trait cap), which biases which OTHER traits/beliefs they're likely
to pick up over time. `systems/peer_influence.py` runs the actual adoption
engine: real co-presence hours (weighted by `rel["designation"]`, a 5-tier
`stranger → acquaintance → friend → close_friend → best_friend` ladder
promoted/demoted weekly) accumulate toward a dual strength/exposure-count
threshold; trait similarity boosts belief adoption and vice versa. Evaluated
monthly for adults, weekly for children/teens, gated by an annual
per-character learning budget. Hard caps: 10 learned personality traits, 5
physical traits, with eviction on overflow. General beliefs
(`belief_templates`, `c["held_beliefs"]`) are a separate system from the
political-only `brain/beliefs.py`.

## Stories & cued recall
`systems/stories.py` — each character keeps a capped, ranked
`c["notable_stories"]` list (category-weighted value that decays daily);
hooks off `store_memory()` for any sufficiently important memory. Eviction
condenses a story into a short permanent memory (`llm/story_condensation.py`).
Telling a story routes through the real `gossip` speech_act
(`tell_story()`), and the listener independently re-scores it — a story can
propagate organically. `predict_best_audience()` biases who a character
brings a story up with first. Separately, `conversation_analysis.py` has a
low-probability "cued recall" hook: a word just heard can trigger
`recall()` against the listener's own memories, queuing a
`pending_reflections` entry ("reminded of X").

## Behavior-pattern observation
`systems/behavior_patterns.py` — characters log what they observe others
doing (`c["_daily_observations"]`, off the same data `brain/perception.py`
already computes); aggregated once per calendar day into recurring
`behavior_patterns[other_id]` entries (activity + hour-range + count). A
NEW pattern gets one LLM-generated theory (`llm/behavior_theory.py`,
classified optimistic/pessimistic — pessimistic feeds
`worries.py::bump_suspicion()`). Recurrence count scales an
`ask_about_pattern` conversational intention; the subject can genuinely
answer (or lie) via `answer_about_pattern`, filling `pattern["answer"]`.

## Life comparison & jealousy
`systems/life_comparison.py` — compares a character against real contacts
across belongings/spouse-match/children-match/appearance/work/intelligence/
social-life/expectations-fulfillment/personality, using the SAME
`compute_ideal_match()`/`ideal_partner` machinery attraction.py already has.
Only dimensions where the OTHER scores better accumulate `rel["jealousy"]`;
crossing a threshold fires a `"life_envy"` grievance.

## Parenting & expectations
`systems/parenting.py` — each spouse gets an independently generated
`ideal_child` persona (mirrors `ideal_partner`) plus loose `life_goals`
(Happiness/Lovelife/Career/Patriot/Legacy/Grandchildren, 0-1 each);
`derive_household_parenting_guidelines()` intersects both spouses' ideals
into `household["parenting_guidelines"]`, read by `persona_expectations.py`
as one more real-child-vs-ideal clash source.
`systems/expectations.py`/`expectation_planner.py` — recurring
daily/weekly/monthly/yearly obligation "checkboxes" per role (parent/
provider/etc.), each with a real dependency-graph plan
(`activity_queue.py`) and a hard-blocker fallback to `add_desire()`. A
missed `requires_others` expectation with an identifiable responsible party
feeds `grievances.py` directly — this is the actual blame → resentment →
confrontation pipeline (`grievances.py`'s existing `confrontation_desired`
threshold → `conflict_pipeline.py::start_conflict()`).

## Diary & speech quirks
`systems/diary.py` — the `keep_a_diary` hobby grants a real `diary` item;
`maybe_write_diary()` is day-key gated, gathers real recent memories
(`DIARY_LOOKBACK_TICKS`), and calls `llm/diary_narration.py` (memory-
grounded, with a deterministic fallback) — a hollow entry with no real
memories behind it is itself a bug signal. `speech_style_registry` (12
entries) is rolled onto ~15% of characters at generation
(`SPEECH_STYLE_CHANCE`), surfaced both in `context_builder.py::
_sec_identity()` ("How you talk and write: ...") and in diary generation.

## Libido & sexual release
`systems/libido.py` — a standalone `c["libido_state"]` need (baseline +
randomized multi-day spikes, weighted by `attraction_profile.libido`),
separate from relationship-scoped `arousal_level`. `systems/
sexual_release.py::attempt_release()` runs a real priority cascade on
spike: spouse/partner (via `intimacy.py`'s real
`propose_act`/`recipient_decision` willingness engine) → a friends-with-
benefits/booty-call text to a past intimate contact
(`intimacy_stage >= 3`, no persisted FWB state) → masturbation (privacy-
gated via `nudity_perception.py`, gendered aid preference, discoverable by
housemates via `intimate_item_discovery.py`) → last-resort prostitute hire
(`services.py` off-grid, or a real on-grid parking-lot NPC pickup via
`rideshare.py::request_pickup()`) for a stressed heterosexual male once
every prior step is exhausted.

## Attraction & ideal partner
`systems/attraction.py` — `generate_ideal_partner()`/`generate_ideal_child()`
(desired/undesired traits + a physical preference window) feed directly
into `compute_attraction()`'s existing scoring (folded into the
personality/appearance weights, not a second parallel score) —
`rel["attraction"]` stays the one subjective-attraction source of truth.

---

# MENTAL & PHYSICAL HEALTH

## Weighted condition assignment
`systems/mental_health_gen.py::assign_conditions()` — one shared
weighted-roll engine (age/sex-gated via each `mental_health_templates`/
`physical_health_templates` entry's `common_age_range`/`common_sex` +
`base_rate`), called at generation for both registries. Real, independent
per-condition rolls (comorbidity is normal, not mutually exclusive).

## Psychosis
`systems/psychosis.py` — a temporary STATE (`c["psychosis_state"]`), not a
diagnosis; ANY character can enter it, rolled from stress/sleep-
deprivation (via `body_energy()`)/intoxication. A diagnosed schizophrenia
character has a permanently elevated baseline via the same mechanic, not a
separate one. `trigger_hallucination()` fires a real, observable
`"hallucinating"` reaction — others perceive the character reacting to
nothing, not the hallucination itself.

## Sociopathy
`systems/sociopathy.py` — diagnosing `antisocial_personality` auto-grants
`domestic_abuser`, which starts the already-existing `domestic_control.py`
control-tactics engine running with no other wiring. Sociopaths get a
`persona_bank` (multiple `generate_persona()` identities) and a per-
relationship `known_as` field; honesty floors at 0 toward everyone except
the one controlled partner (`excuses.py`). `maybe_plant_drama()` fabricates
false claims about real third parties through the real gossip pipeline.

---

# CRIME & FACTIONS

Authoritative: `systems/crime.py`

Illegal `job_templates` are excluded from random generation-time hiring
(`character_gen.py::_assign_job`) — entry into crime is opportunity-driven
at runtime (`maybe_recruit_into_crime()`, daily, weighted by financial
desperation/risk traits/having a criminal contact). `c["criminal_standing"]`
accumulates from successful uncaught crimes and promotes a drug-dealer
track up through real `world["factions"]` membership
(`street_gang`/`crime_family`, actually populating `faction["members"]`
for the first time). `CRIME_PROFILES` + `resolve_criminal_shift()` is the
shared per-job-type shift resolution, hooked into `offgrid.py`'s existing
`reason == "work"` branch — feeds real `world["incidents"]` into
`law.py::maybe_arrest_from_incidents()`.

## Darknet & stealth
`systems/darknet.py` — `world["darknet_listings"]` (drugs mail-ordered via
`procurement.py::schedule_delivery_item()`; every other category —
hacking/fraud/hitman/PI — a lightweight contract), reachable from a phone
app and a computer interaction. `systems/stealth.py::attempt_sneak_entry()`
— shared lockpick/glass-cutter infiltration + noise-risk framework used by
both Burglar shifts and Private Investigator surveillance jobs.

## Cover personas
`systems/persona.py::generate_persona()` — a temporary
`c["active_persona"]` adopted for a cover-requiring activity; while set,
`excuses.py::_get_true_detail()` reads the persona's cover instead of the
character's real identity, so a "who are you" question resolves through
the SAME `generate_excuse()` → `check_lie_consistency()` pipeline as any
other lie — a persona is a pre-committed consistent answer, not a new
consequence system.

---

# SPORTS

Authoritative: `systems/sports.py`, `systems/sports_leagues.py`

`sports_teams` (114 entries — real NFL/NBA/NHL/Premier League team
identity content) for 4 supporter hobbies; 4 player hobbies get a
per-simulation invented `world["local_teams"][sport]` roster instead.
`sports_leagues.py::generate_season_schedule()` builds a round-robin
fixture list on the sim's own calendar; `tick_sports_leagues()` resolves
results via a `strength`-weighted roll. Game days become real
`social_events`; off-grid attendance resolves through the normal
`send_offgrid()` trip-summary path, on-grid attendance gets a live
`sports_broadcast.py` score-update loop (mirrors `reading_process.py`'s
periodic-narration shape). Rival-supporter hostility at a shared loss can
escalate into a real fight via the existing
`hostile_actions.py`/`conflict_pipeline.py` machinery.

---

# MARKETPLACE

`systems/marketplace.py` — `world["marketplace_listings"]`, a flat
second-hand furniture board. `estimate_avg_sell_value()` is read-only
(a discount off `market.py::get_price()`); `list_prop_for_sale()` removes
a prop from `world["props"]`; `buy_marketplace_listing()` transfers
payment and delivers the prop via the same placement shape
`procurement.py::_deliver_prop()` uses for new furniture.

---

# FINANCE

Authoritative: `systems/banking.py`, `systems/credit.py`,
`systems/government_debt.py`

Every character gets a wallet ($100 cash), ID card, and a bank card tied
to a real `world["banks"][bank]["accounts"][account_number]` record at one
of 5 starter banks (JPMC, Morgan Stanley, Barclays, TD Bank, Bank of
America) — set up unconditionally in `character_gen.py`, mirroring the
existing unconditional phone-grant block. Credit cards are apply-only
(`apply_for_credit_card()`, gated by `c["credit_score"]`), carrying
`max_credit`/`current_debt` directly on the card item (a credit line, not
a deposit account). Loans (`c["loans"]`) are secured (banks, needs
collateral) or unsecured (loan providers, disbursed straight into a named
bank account) — `systems/loans.py`. `government_debt.py` assesses a
monthly tax bill per employed character from `socioeconomics.py`'s
existing (previously uncharged) `income_tax_rate`; unpaid past a grace
period dings `credit_score` and feeds `law.py`'s fine pipeline.
`mail.py::attempt_pay_bills()` is the one real "pay down what's owed,
priority order, bank balance falling back to wallet cash" function bills/
credit minimums/loan payments all flow through.

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

All data-driven templates, ~73 top-level registries. Only about 25 of
them (the ones marked with a * below) are reachable through the frontend
Definitions Editor's tab row — everything else needs a direct JSON edit +
backend restart. See `docs/wiki/adding-templates.md` for the actual
step-by-step workflow, including that caveat.

| Key                        | Count | Description                                                        |
|-----------------------------|-------|--------------------------------------------------------------------|
| prop_templates *            | 154   | Furniture and interactive objects (anchors, storage, tags)         |
| item_templates *            | 517   | Portable physical items                                            |
| default_item_interactions   | 9     | Universal item actions (pick_up, drop, put_in, give, throw, etc.)  |
| hobby_templates *           | 90    | Hobby definitions (props, items, cost, participants, off_grid)     |
| interaction_templates *     | 168   | Atomic interactions with prop requirements, body effects, anims    |
| activity_templates *        | 141   | Multi-step activity sequences                                      |
| recipe_templates *          | 2     | Cooking recipes                                                    |
| service_templates *         | 13    | Hired services catalog                                             |
| job_templates *             | 577   | Employment types, including ~18 criminal careers                   |
| company_templates *         | 48    | Business types                                                     |
| need_templates *            | 12    | Long-term need drive definitions                                   |
| mood_templates *            | 15    | Persistent mood states with triggers and durations                 |
| trait_templates *           | 143   | Personality traits (learn_chance/cognitive_modifiers/conditions)   |
| belief_templates *          | 21    | General beliefs, separate from the political-only belief system    |
| mental_health_templates     | 14    | Diagnosable conditions, weighted-assigned at generation             |
| physical_health_templates * | 32    | Chronic/acute physical conditions                                   |
| health_hazard_templates     | 25    | Injury/disease hazard instances (pain_flat/escalation/stages)       |
| symptom_templates           | 20    | Legacy per-condition symptom vocabulary                             |
| injury_templates            | 12    | `apply_injury()`'s body-part/hazard roll tables                     |
| physical_trait_templates    | 43    | Physical (not personality) traits                                   |
| sports_teams                | 114   | Real NFL/NBA/NHL/Premier League team identity content                |
| faction_templates *         | 8     | Gang/crime-family/political faction shapes                          |
| speech_style_registry       | 12    | Distinctive talk/write quirks, ~15% of characters                   |
| contact_designations        | 6     | stranger→acquaintance→…→best_friend ladder                          |
| expectation_templates       | 7     | Recurring role-based obligation "checkboxes"                        |
| addiction_templates          | 13    | Substance/behavior addiction tracks                                 |
| floorplan_templates *       | 3     | Room/wall/tile layouts a building instantiates                      |

`*` = has a tab in the Definitions Editor. Everything else needs a direct
`definitions.json` edit.

---

# DEPRECATED

Do not use. Will be removed.

- `intention.py` / `intentions.py`
- `activity_runtime.py`
- `planner.py` heuristic planning
- `schedule.py` legacy intention queues
- `c["needs"]` — fully removed; was a legacy `{social, fun}` dict
- `data/item_templates.py` — superseded by `definitions.json -> item_templates`
- **The unified pain system** — `health_state["pain"]`/`systemic_pain`/
  `painkiller_relief`/`pain_contribution`, `add_pain()`/`add_bodypart_pain()`/
  `apply_painkiller()`, the `"incapacitated_pain"` posture value, the
  `take_painkiller` action, `systems/pain_fatigue.py` and `systems/
  pain_complaints.py` (deleted) — fully removed. Its posture-locking bug
  (a character whose pain crossed 80 never reliably recovered posture)
  was the proximate cause of characters looking permanently stuck.
  `compute_severity()`/`apply_severity_consequences()` (see HEALTH &
  INJURY) still work, driven by the other independent severity signals.
  A replacement discomfort/pain mechanic has not been designed yet.
- `c["body"]["pain"]` / `c["health"]["pain"]` — the two legacy pre-
  unification pain trackers `health.py` itself once described as
  disconnected/dead — also fully removed.
