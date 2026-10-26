# Bedtime and spawn-time settling

## Why nobody went to bed
The schedule has always had a 23:00-07:00 sleep block, but nothing acted on it. The only things that sent a character to bed
were fatigue above 75 at night (about 36 hours awake) or the LLM choosing to. A household that was not already worn out stayed
up all night, work or school the next morning or not; some started an 8-hour "work" session at home at midnight, and others
went out for "leisure" or a driving lesson at 1 a.m.

## The rule (`systems/bedtime.py`)
`wants_bed(c, world)`: it is their sleep time (the current schedule block is `sleep`; with no schedule yet, the clock 23:00-07:00),
they are not already asleep / off the grid / travelling, and the morning the night leads into has a daytime obligation:
a `work` block starting between 05:00 and 15:00 in their schedule for that day, or, for a child with a school, a weekday.
Without a schedule for that day a weekday counts if they have a job. So Sunday night and Monday-Thursday nights send people to
bed; Friday and Saturday nights do not by themselves. The morning is tomorrow's from 23:00 to midnight and today's after.

Effects
- `generate_body_intentions` adds a `sleep` intention (reason `bedtime`, priority 72) unless a fatigue-driven one is already there
  (exhaustion keeps its higher priority).
- `brain/agent_loop.py`: a running discretionary activity (not sleep/toilet/eat/shower/teeth/nap) is interrupted for it, at most
  once per 10 sim-minutes.
- `systems/offgrid.py::maybe_go_offgrid`: no outings or errands at bedtime.

## Spawn-time settling (`systems/spawn_setup.py`)
`settle_new_character(world, c)` runs on every editor spawn (after the household, neighbour ties and family are in place) and on
demand through `POST /admin/settle_characters {"character_ids": [...]}` (default everyone but workplace NPCs):
1. places them in the building/room they stand in
2. generates their week schedule now, staggered against housemates, and works out the current block
3. sets the body clock to the time of day: hours awake since their schedule's wake-up and the fatigue that goes with it (never lowered)
4. runs the body intentions once so bedtime is picked up immediately

## Known limits
- The starter house has two single beds; a family of three or four means adults sleep on the floor of the dining room or kitchen.
- Children have no school blocks in their schedule at all (and nothing sends them to school); the bedtime rule uses
  "child with a school on a weekday" instead.
- A discretionary activity that LLM-chosen "work" at home at night is only interrupted at bedtime, it is not prevented.

Tests: `tests/test_bedtime.py`.

## Beds for everyone (`systems/household_beds.py`)
`ensure_household_beds` adds single beds until the home has a sleep anchor per member (the starter house has two). It runs when
someone joins a household and in the settle step. A bed goes on the first free 2x2 block that keeps the furniture clearance, in
a bedroom, living room, dining room, laundry or corridor, in that order; with no clear block a cramped one is used, and with
no block at all the household is left short (`household["beds_short"]`). Tests: `tests/test_household_beds.py`.

## School (`systems/age_rules.py::school_hours`, `systems/scheduling.py`, `systems/offgrid.py`, `brain/agent_loop.py`)
- Schedule: a child with a school gets a `school` block Monday to Friday: preschool 09-12, primary and middle 08-15, high school
  08-16. A school block also counts as the daytime obligation for bedtime.
- The bell: from the start of the block to an hour after it (never in its last half hour), a child who has not been sent today is
  got up (a sleeping child too; only the toilet and breakfast are kept) and sent off-grid with reason `school` until the block
  ends. `_school_day` is stamped so it happens once a day, and their parents' "get the kids to school" expectation is satisfied.
- The return: a plain "spent the day at <school> in <grade>" story (no private events or cover stories), a school day costs 35%
  of the fatigue a work shift does, and it satisfies the need to learn.
- Not done: no holidays or sick days, no classmates, no homework or grades, and school is an off-grid trip (the child is not
  shown walking there).
Tests: `tests/test_school.py` (the last section runs the simulation across the bell).

## Conversation log
A character's `conversation_log` now has ONE object per set of people (a running thread) instead of one per conversation:
`brain/conversations.py::add_to_conversation_log` folds a finished conversation into the thread with the same people, keeps the
ids in `conv_ids`, tags each line with its `conv_id`, lists all `mediums`, and shows the same line said again as one line with
`repeats`. Lines are stripped of the quote marks the model wraps them in (`systems/text_clean.py`; the same line retried came back
with another pair each time). Entries written earlier are folded together the first time it runs (and by settle). The timeline's
"details" lookup finds a conversation through `conv_ids`. Tests: `tests/test_conversation_log.py`.

## Parents stay home (school run, young children)
- `systems/offgrid.py::school_run_pending`: from two hours before the bell until the late window closes, a grown-up of a household
  with a school child who has not yet left does not go out for shopping, leisure, a coffee or a workout.
- `send_to_school` only credits ("get the kids to school") parents who are actually at home.
- `systems/temporary_separation.py`: a child never moves out after a fight, and a grown-up who is the only one at home with a child
  under 14 does not either (`would_leave_children_alone`; a parent already staying elsewhere does not count as home). One
  conflict used to send both parents away for three days and leave the children alone.
- `POST /admin/recall_characters {"character_ids": [...], "reason": "temporary_separation"}` brings away characters home now (their
  return is due this tick and the normal return handling runs). Tests: `tests/test_parents_home.py`.
