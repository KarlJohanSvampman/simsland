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
