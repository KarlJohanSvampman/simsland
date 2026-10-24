# Meeting people through people (third-person relationship formation)

Before this, two characters only became acquainted by being near each other (`first_impression`, +5 familiarity) or by the
neighbour seeding. Now a friend can bring two people together, and a good word about someone makes them a name.

## Introductions (`systems/introductions.py`, job `introductions`, every 300 ticks)

For each character M who can see at least two people, a pair (A, B) qualifies when:

- both are children, or both are grown-ups; both awake and on the grid; not family; and they have not really met (at most one
  interaction, friendship under 8, never introduced);
- M's friendship with each is at least 15 (10 if M is a child), no hostility (>= 10) either way, no open grudge between M and
  either; each of A and B has at least 10 friendship for M (they take M's word);
- M is awake and on the grid.

One pair per introducer per check, with probability 0.25 (x1.5 for outgoing traits, x0.4 for shy/reserved ones). The pair is
tied mutually (`neighbours._tie`: familiarity 6-12, friendship 2-7, trust 2-7, comfort 0-2, scaled by how much they trust M, label
`introduced`, `introduced_by` = M on both sides), all three get a memory, and the pair is recorded in `world["introductions"]`
(at most 500) so it happens once. Kids use it too, which is how a child meets a friend's friend.

## Hearsay (`systems/rumors.py`)

A believed compliment about someone the listener hasn't met gives them familiarity 2 with the subject (`HEARD_OF_FAMILIARITY`),
so a name they have heard good things about isn't a total stranger. Believed gossip/slander already moved friendship, respect and
trust (rumors step 4); it never touches familiarity.

## Tuning and tests

`INTRO_CHANCE`, `MIN_FRIENDSHIP`, `KID_MIN_FRIENDSHIP`, `MIN_VOUCH`, `MAX_STRANGER_*`, `INTRO_SCALE`, `OUTGOING`, `RESERVED` in
the module. `tests/test_introductions.py`.

**Not done.** Nobody can ask to be introduced, and the introducer doesn't say anything out loud; it is state plus memories. A
child and a grown-up are never introduced across the age bands (a parent introducing a child to an adult friend would need its
own rules).
