# Vision levels and exhaustion

## Vision (`systems/vision.py`)
- Four levels, `Vision.NORMAL / EXCEPTIONAL / IMPAIRED / BLIND`. A character's `vision` is their natural level (without glasses). Nobody is
  generated blind: it is a state for accidents and illness (`POST /admin/set_vision`).
- Each level has a recognition distance in metres: how far away a face can still be told. Out to `detect_factor` times as far (2 by
  default) a person can still be made out at all, with less detail the farther: first a figure (a man, a child, roughly what they are
  doing), then only a shape. Those glimpsed people are never named (`perception["glimpsed"]`, the prompt's "Further off you can make out").
- The distances are simulation settings (`world["settings"]["vision"]`, metres; `GET/POST /admin/vision`): set them in the debug settings
  screen (the gear), section "Vision". The defaults (normal 20, exceptional 40, impaired 6, detect x2, tile 1 m) are placeholders.
  Indoors and at night the ranges are shortened by the factors the old visual range used (indoors x8/14, night x0.55 indoors / x0.35 out).
- Glasses: `c["glasses"] = {"owned": bool}`; an impaired character who wears glasses sees at the normal range; asleep, napping or in the
  shower they are off. Impairment by nature: 6% of children, 10% of under-40s, 40% in their forties, 62% in their fifties, 80% from sixty;
  85% of the impaired own glasses; 4% are exceptional; `poor_eyesight` / `keen_eyesight` set the level directly. Characters from before
  this get a level once (spawn settling / `POST /admin/settle_characters`).
- `visual_range` is now the recognition range and `detection_range` the outer one; the overlay draws both rings. An outburst
  (`systems/impulse.py::within_reach`) reaches only someone the actor could recognise: same room, or the same building within their
  vision, never another building, never a blind actor.

## Exhaustion (`systems/exhaustion.py`)
- By day, while a responsibility is open (an intention with a `child_id`: feed, remind, check on), fatigue does not put an adult or
  teenager to sleep or to nap. A daytime sleeper whom a hungry child is waiting for is woken.
- Instead, fatigue from 65 up strains them (0..1): stress and anger pressure build, the mood turns annoyed then angry, a slip happens
  now and then (a minute-by-minute chance, noted as a memory, more stress), cooking accidents are up to 3x as likely, and they notice
  less (no descriptions of people, fewer props). The prompt says "you are worn out ... you cannot lie down while a child still needs you".
- The way out is someone else: a housemate (or anyone nearby who is rested) offers to take the responsibility over; the worn-out one snaps
  back at once ("Don't tell me to calm down!"), and a few minutes later gives in (65% the first time, always after a refusal): the duty
  moves to the helper, they go to bed for up to six hours.
- A stay of 14 hours or more away (days at a relative's) no longer costs fatigue: they used to return at 100 and drop.
- Temporary separations now say why and where (`off_grid_detail`: "with family or friends somewhere else", "after a fight with X that
  ended in a cold silence"); the inspector shows it under the off-grid line, and the return summary tells it.
