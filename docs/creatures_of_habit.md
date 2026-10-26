# Creatures of habit: no dice while something is open

Characters have schedules, expectations and intentions for a reason, so what they do is not decided by a roll while any of those is
open (`systems/unresolved.py::has_unresolved`: an intention not decayed away, or an expectation still pending).

## What was removed
- **Random trips.** `maybe_go_offgrid` rolled 0.4-0.8% per tick for a shopping trip or a leisure/gym/cafe outing (a trip every few
  minutes for everybody), and 25% of the leisure ones were a night out. Gone. A trip now happens because of the schedule (work, school),
  an expectation's or appointment's own pipeline (doctor, interview, licence lessons, events, a stay with relatives after a fight), or one
  real need: a hungry grown-up in a household whose larder cannot feed it goes shopping (`needs_groceries`: the household's first hungry
  grown-up, one at a time, never during the school run or a work block) and comes home with groceries (`household_pantry.restock`).
- **Random doctor booking.** A health need is booked the next morning at 09:00, not on a 0.2%/tick roll.
- **Random practice driving.** A licence pursuer practises when the cooldown (1-3 days) has passed and their lessons allow it (1.5
  sessions per lesson taken), with the closest companion (household first), not a random one.
- **Idle quirks and curiosity.** Wandering the house, checking the door, looking out of the window, and going to investigate something
  noticed, only happen to a character with nothing open.
- Narration flavour (which venue, what happened at the gym) is still chosen at random: it does not decide what anyone does.

## One priority list (`systems/todo.py`)
Intentions already include the expectations (`expectation:*`), so one list covers both. Each item is **pressing** (survival, health and
schedule matters; household, chore and social matters that are important (>= 70) or have gone unanswered through a check-in; worry
relief) or **for when there is time** (leisure, identity, impulse, and the less important rest). Within each tier the order is
`final_priority`.
- The prompt shows it: "What you have to see to, most pressing first: 1. ...; 2. ..." (four at most), then "When you have the time (not
  before the above): ..." or, with nothing pressing, "Nothing pressing right now. You have time for: ...".
- In the agent loop, what is for when there is time does not run by itself (autopilot) while anything pressing is open.

## Trips that repeat
Any trip that is not scheduled or an appointment is refused when it is the same kind as the last trip the character took and that was
today, or the same kind ended less than two hours ago (20 hours for practice driving). Every stay now records when it began and when it
is due back (the inspector shows both clocks), and a separation says why and where.
