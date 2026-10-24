# Worry system — draft

Status: **build step 1 is done** (see "Progress" at the end); steps 2-5 are not. Sighting notes are
already down to one per person per hour (`social_memory.SIGHTING_OBSERVATION_GAP_TICKS`).

## 1. Idea in one paragraph

A **worry** is a temporary case file about something a character is anxious about.
Each case has a severity, which sets how long it lasts and how much of the
character's **focus** it eats while it lasts. Total focus left after all active
worries decides whether they can do demanding activities, and when it runs low they
drop what they're doing and look for relief — information, distraction or
transcendence — and when it runs out they have a breakdown (impulsive, erratic
behaviour, not freezing). Relief activities shorten the worries; new evidence
refreshes them.

Note: `c["worries"]` already exists (`systems/worries.py`) as person-keyed
*suspicion*. It stays as one producer of cases. Cases live in a new key,
`c["worry_cases"]`, so the two don't collide.

## 2. The case file

```
worry_cases[case_id] = {
  id, status,                         # active | resolved | lapsed
  subject: {kind, ref, label},        # see below
  severity,                           # 1-10, set at registration
  focus_cost,                         # % units taken off max focus while active
  created, expires, last_refreshed, refreshes,
  tags,                               # what counts as evidence for this case
  evidence: [{tick, source, ref, note}],   # capped, newest last
  summary,                            # one line used in prompts
  mitigated_by: [{tick, activity, mode, reduced_ticks}],
}
```

`subject.kind`:

| kind | ref | typical sources |
|---|---|---|
| `self` | — | health scare, erratic-behaviour failure, money trouble, failing at something |
| `person` | character id | `pattern_concern` noticing, suspicion, an open grudge, a loved one ill |
| `event` | event/incident id | witnessed violence, accident, death, a break-in |
| `expectation` | expectation id | a deadline/obligation at risk or missed (`systems/expectations.py`) |
| `choice` | proposal/decision id | job offer, moving, pregnancy, a request awaiting answer |
| `conflict` | conflict/grievance id | an unresolved argument (`conflicts`, `grievances.py`) |
| `area` | area key | vague, generic: `workplace`, `family`, `finances`, `politics`, `media`, `health`, `neighbourhood` |

Areas are defined in `definitions.json → worry_areas` as `{area: {tags: [...]}}` — the
tags are what the poll matches against memories, conversations and news.

## 3. Severity, duration, focus cost

- Reported by whatever registers the worry: `severity = base × closeness × propensity`,
  clamped 1–10. `base` per source (a death 9, a missed deadline 4, a vague headline
  1–2); `closeness` from the relationship (the ledger balance, kinship); `propensity`
  from the character (anxious/stressed/anxiety-disorder up, calm/resilient down; a
  parent up for their children; a small child only worries about self and family).
- Registration threshold: severity below 2 isn't registered. This is the answer to
  "what makes this particular character produce an entry" — the same event is a 6 for
  one person and a 1 for another.
- Generic `area` worries are capped at severity 3.
- `duration = severity × DURATION_PER_SEVERITY` (start at 1 sim-hour per point, areas
  half). `focus_cost = severity × 2` percentage points, capped at 25 per case.
- `focus_available = 100 − min(80, Σ active focus_cost)`.

## 4. Registering and refreshing

`register_worry(c, subject, severity, source, note, world)`:

- Specific subjects (self/person/event/expectation/choice/conflict): one case per
  subject. A repeat registration or fresh evidence **refreshes** it — expiry extended,
  evidence appended, severity nudged up by 1 at most per refresh, capped at the
  reporter's severity + 2.
- Generic areas: created only when the character has **no other active worry**, and
  only *refreshed* by area-tagged evidence newer than the last poll. (I'm reading
  "won't be added to as long as there is one active worry" that way — correct me if
  you meant something else.)

**The poll** — once per sim hour per character (`poll_worries`):

1. memories logged since `last_poll_tick` (tags + `people`) → match against each active
   case's tags/ref and against the area tag lists
2. the news stream items since the last poll → area matches (`politics`, `media`, …)
3. conversation lines since the last poll (they're stored as tagged memories already)
4. matches against an active case refresh it; matches against an area with no active
   worry registers one (subject to §3's cap)
5. expire cases past `expires` → `lapsed`; compute `focus_available`; cache it in
   `c["focus_state"]`

Cost is proportional to *new* memories, not the whole store.

**Producers** (each calls `register_worry`; most hooks already exist):
`pattern_concern` noticing; `systems/worries.py` suspicion above a threshold; open
grudge or large negative ledger entry (`relationship_ledger`); missed/at-risk
expectation; unresolved conflict/grievance; health events; money (overdue bills, low
balance); incidents/violence witnessed (`events`); a pending high-stakes
proposal/choice; loop-guard failure (`self`).

## 5. Required focus on activities

Optional `required_focus` (percent) on an activity definition, default none — e.g.
`study 70, work_shift 60, write 60, pay_bills 55, cook_recipe 50, read_book 45, jog 15`.

- Gate at start: if `focus_available < required_focus` the character can still start it
  (they may not know) but is at risk below.
- While performing it, **every 3 minutes (180 ticks at 1×)** roll once. Chance of
  abort = the **shortfall** (`required_focus − focus_available`, clamped 0–100 %).
  *Ambiguity:* your message says "a chance equal to the remaining percentage of
  focus"; read literally that makes more focus more likely to abort, so I've taken it
  as the shortfall. Say if you meant otherwise.
- On abort: the activity is interrupted, a memory "I couldn't concentrate on X" is
  stored, and the intention that drove it is replaced by a **mitigation** intention
  (§6). The abort is recorded like a loop-guard failure so it isn't retried
  immediately.

## 6. Mitigation intentions

The top case (highest `focus_cost`) raises a mitigation intention when
`focus_available` drops under a comfort threshold (say 50%) or after an abort. The
mode is chosen by traits, age, what's possible right now and any substance history:

| mode | examples | effect |
|---|---|---|
| inform | browse news, research online, talk it over (call/visit a person), online discourse | shortens *that* case (e.g. −25% remaining); new bad news instead refreshes it |
| distract | TV, music, exercise/jog, a walk, hobbies, socialising | shortens all active cases a little (−10%) |
| transcend | meditate/reflect/journal; adults: a drink, other substances, intimacy | larger cut (−30%), with the activity's own side effects (hangover, dependence tracking) |

Substances and sexual relations are adult-only and go through the existing
age-gating (`ACTION_TYPE_MIN_AGE`); no new content there. Meditation and "have a drink"
need new activities. A `worry_relief` table in `definitions.json` maps
`activity → {mode, reduce_pct, area_tags?}` so activities opt in without code changes.

## 7. Overload: confusion and breakdown

- `focus_available < 25%`: **overwhelmed** — only trivial activities (no
  `required_focus` or ≤ 15) are started; everything else is replaced by a mitigation
  intention.
- `focus_available ≤ 5%` for 3 sim-minutes, or the abort rolls keep failing: a
  **breakdown episode** (10–30 sim-minutes, then a 6-hour cooldown). The character does
  not freeze. Every 1–3 minutes they pick a **random intention** and pair it with a
  **random activity that doesn't match it** (filtered by age, availability, location),
  and express it — crying, snapping, muttering via the one-way expressions system, and
  for hot-tempered characters a provocation toward whoever is near. Normal intention
  dispatch is suspended; survival activities (toilet, water) still can interrupt.
- On exit: 30% of the worry load is relieved, a memory is stored, observers' `pattern_concern`
  sees erratic behaviour, and a `self` worry may be registered for the episode itself.

## 8. Build order

1. Core: `systems/worry_cases.py` (register / refresh / expire / poll, focus calc),
   `worry_areas` definitions, context line ("part of your focus is taken up by …"),
   tests. Registrations from `pattern_concern` and `systems/worries.py` only.
2. More producers: expectations, conflicts/grievances, ledger, health, money, news,
   events, choices.
3. `required_focus`, the 3-minute abort roll, mitigation intentions, new relief
   activities, `worry_relief` table.
4. Breakdown episodes.
5. UI: worry panel per character, focus gauge.

## 9. Decisions needed

1. The abort chance: shortfall (my reading) or literal remaining focus?
2. The generic-area rule as I read it above?
3. Starting numbers (1 sim-hour per severity point, 2 focus points per severity, max 80%
   total, comfort threshold 50%, breakdown at ≤5%) fine to tune from?
4. Breakdown cooldown of 6 sim-hours and 30% relief?

## 10. Progress

**Step 1 -- the core (built).** `systems/worry_cases.py`, `tests/test_worry_cases.py`.

- Case files in `c["worry_cases"]`, the focus budget in `c["focus_state"]` (`available`, `load`, `top_case`,
  `last_poll`); `register_worry / refresh_case / close_case / update_focus / poll_worries /
  context_lines`. All the numbers are constants at the top of the module.
- The four open questions were not answered, so the readings and numbers above are what is built, to tune
  from: the abort chance (step 3, not built yet) will be the *shortfall*; the generic-area rule is as in
  section 4 (an area only starts when nothing specific is on their mind, and is only refreshed by tagged
  evidence); 1 sim-hour per severity point (areas half), 2 focus points per severity point, load capped at
  80%; breakdown cooldown and relief percentages are step 4.
- A small child (under 8) worries only about themselves and their family; their only generic areas are
  `family` and `health`. A severity-10 case costs 20 focus (the 25-point per-case cap only bites if the
  constants are raised).
- The poll: a scheduled job every sim-minute looks at each character whose hour is up (spread over the hour
  per character) and examines only *new* memories and news since the last poll: a memory/news item that
  mentions the case's person or one of its tags refreshes it (a negative one nudges severity up by one, at
  most once per poll, never above what was reported + 2); a negative item matching a generic area starts an
  area worry if nothing else is active. Memories the worry system writes itself are tagged `worry_case`
  and never count as evidence. Area keywords/tags come from `definitions.json -> worry_areas` (added;
  `DEFAULT_AREAS` in the module is the fallback).
- Producers wired: `pattern_concern` (noticing a repeating pattern: severity 3.5 base, 5.5 when it
  persists after asking; closed as resolved when the pattern stops) and `systems/worries.py` suspicion
  (becomes a case at 0.3). Severity = base x closeness (kin 1.5, friends 1.0-1.3, strangers 0.5) x
  propensity (nervous/paranoid/pessimistic up, calm/resilient/optimistic down, current stress up).
- The prompt: a `worry_cases` context section lists up to three things on their mind and, when focus is
  low, says so.
- In a 9000-tick run of the fixture world, worries do start (a politics area worry from negative news, one
  per person); nothing else changed yet -- focus does not gate anything until step 3.

Next is step 2 (more producers: expectations, conflicts/grievances, the ledger, health, money, events,
choices), then step 3 (`required_focus`, the abort roll, mitigation intentions and relief activities).

