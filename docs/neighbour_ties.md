# Neighbour ties -- who a character already knows from the street

`backend/systems/neighbours.py`, `backend/tests/test_neighbours.py`.

A new world used to start with every relationship at zero: a six-year-old whose neighbour's child lives two doors down
began as strangers with them. Now a character gets the ties a real street would have given them.

**When.** Right after the editor's Spawn creates a character (`api/editor.py::_spawn_character_locked`), and, for every
other way a character can appear (a generated world, a relative, a reset, characters that already existed), from a cheap
scheduled job (`neighbours`, every 600 sim-ticks) that seeds whoever has not been seeded yet, once (`c["_neighbours_seeded"]`).
A newcomer is tied to the people already there, so the existing residents don't need to be touched.

**Who counts as near.** People of OTHER households whose home building is within 40 tiles (Manhattan distance between the
two households' buildings; a household's home is the building it owns, or the one it names). Workplace NPCs, service workers,
the dead, and people with no household are left out, as is anyone whose home can't be found.

**Children and teenagers (4-17)**: up to 3 friends among the other children within 3 years of their age, chosen by a
score of age closeness, nearness and shared hobbies (+0.12 each). Friendship 10-32, familiarity 14-28, trust 6-16 and
comfort 3-10, scaled by that score; a few past interactions; the label `neighbour`; a small memory ("Mo lives nearby and we
play together sometimes"). A candidate who already has more than three friends is skipped.

**Grown-ups**: up to 5 acquaintances among the nearest other grown-ups (not children): familiarity 6-12, friendship 2-7,
trust 1-5, comfort 0-2 -- they recognise each other and have nodded hello.

**Rules.** Ties are mutual. Nothing existing is lowered (each field only goes up), family is left alone, a pair with real
history (more than five interactions) keeps what it has, a pair already tied is not tied twice, and a partly filled
relationship entry from an older save is completed first. The contact-designation ladder (hours spent together) is left to
run on its own; the relationship `state` is recomputed from the new numbers.

**Tuning.** `NEIGHBOUR_RADIUS`, `KID_AGES`, `MAX_AGE_GAP`, `MAX_KID_FRIENDS`, `MAX_ADULT_ACQUAINTANCES`,
`SHARED_HOBBY_BONUS`, `FRIEND_SCALE` and `ACQUAINTANCE_SCALE` at the top of the module.

**Not done.** Children aren't tied to the adults of the other households (only their parents are tied to each other), and
friends aren't given a shared history beyond the single memory.

The live world has two households with one adult each, who already knew each other (familiarity 7.5, five interactions),
so nothing changes there; the unit tests build streets with children, a far-away house, siblings, cousins and crowds.

## Playing together (`systems/kids_play.py`)

Ties alone leave a child with friends and no way to act on it. Every 600 ticks (`kids_play` job) each child aged 4-17 who is
*free* -- awake, on the grid, no activity running, not in a school/sleep/work schedule block, hunger and thirst not pressing --
and between 09:00 and 19:00 looks at their friends (friendship >= 10, not kin). A friend counts if they are also a child and
also free, and has not been suggested within `PLAY_COOLDOWN` (3 h, `c["_play_log"][friend_id]`). With probability
`PLAY_CHANCE` (0.5) the closest such friend becomes a `play_with_friend` intention (social, priority 48, `target_id` = the
friend) with a reason like "Mo lives close by and you feel like playing together -- go and ask Mo if they can play, or invite
them over." The child's own thinking decides what to do with it (walk over, `socialize`, `invite_over`); nothing is forced.

Tuning: `PLAY_COOLDOWN`, `PLAY_HOURS`, `PLAY_CHANCE`, `PLAY_PRIORITY`, `MAX_NEED_PRESSURE`. Tests: `tests/test_kids_play.py`.

**Not done.** The intention is only a nudge for the LLM; there is no autopilot that walks a child to the friend's door, and a
parent isn't asked for permission.

## Housemates (`systems/household_bonds.py`)

Related people living in the same household used to start with zeroed feelings (only the kinship label was stamped). When
`family.sync_kinship_to_relationships` stamps a pair that shares a household, each side is raised once (never lowered; marked
`bonded` so a re-stamp does not undo a falling-out) to: spouse familiarity 90 / trust 70 / friendship 65 / comfort 60;
parent->child 90/60/60/60; child->parent 90/65/60/65; sibling 90/45/45/50; other kin 60/30/30/25; ex-spouses are skipped.
Tests: `tests/test_household_bonds.py`.
