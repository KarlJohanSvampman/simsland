# =========================================================
# WAITING FOR A REASON
# Distinguishes "waiting for something specific to happen" (a person,
# a business, a delivery) from the plain "wait" activity's generic
# idle/nothing-better-to-do fallback (see action_router.py::_route_wait).
# A waiting-for-a-reason character has a patience timer -- shorter when
# stressed, longer when patient -- and accrues stress from their own
# backlog (systems/backlog.py) while blocked. When the timer runs out,
# the character is woken to reconsider (check in on the person, contact
# the business, etc.) rather than silently continuing to sit still.
# =========================================================

from systems.backlog import apply_waiting_stress
from brain.cognition_scheduler import wake_character

# 1 tick == 1 nominal sim-second (brain/memory.py's own SECONDS_PER_DAY
# comment). Per the user's explicit spec: a character should start
# complaining (bang on the door) somewhere between 10 and 20 real
# sim-minutes in, and give up entirely by 30 minutes at the absolute
# latest, regardless of how patient they are.
BASE_PATIENCE_TICKS = 900  # 15 min baseline before trait/stress modifiers

PATIENT_MODIFIER   = 1.3   # ~19.5 min
IMPATIENT_MODIFIER = 0.7   # ~10.5 min

# How many ticks of patience a maxed-out (100) current stress level
# removes -- current stress shortens the timer (more stressed = follows
# up sooner), scaled linearly down to 0 removed at 0 stress.
STRESS_PATIENCE_PENALTY_TICKS = 300  # up to 5 min sooner at max stress

MIN_PATIENCE_TICKS = 300  # never complains sooner than 5 min in

# Hard ceiling on TOTAL time spent waiting for the same occupied
# appliance, measured from when the wait actually started (not from the
# most recent bang) -- "at most they will wait 30 min before giving up,"
# regardless of patience trait or how the bang-escalation cycles land.
MAX_TOTAL_WAIT_TICKS = 1800  # 30 min

# How often the "banging on the door" escalation repeats after the first
# complaint, while still under the 30-min hard cap above.
REARM_TICKS = 300  # 5 min

# After giving up, how long this character avoids re-queuing at the SAME
# occupied anchor -- without this, their still-unmet need (bladder, ...)
# would just re-trigger the identical queue on the very next tick,
# silently undoing the give-up (see interactions.py::begin_interaction's
# avoidance check).
GIVE_UP_AVOID_TICKS = 600  # 10 min

# Per the user's ask (2026-11-01): waiting for a PERSON -- someone to come to the door, someone
# to show up -- lasts at most 10 minutes; then the character gives up, and gives up on what they
# wanted from that person too (the intention aimed at them is dropped), instead of standing there
# with an ever more "overdue" intention.
PERSON_WAIT_MAX_TICKS = 600   # 10 min
DOOR_ANSWER_DISTANCE = 3      # someone from the household this close to the visitor = the door was answered


def _patience_modifier(c):
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    if "patient" in traits:
        return PATIENT_MODIFIER
    if "impatient" in traits:
        return IMPATIENT_MODIFIER
    return 1.0


def _stress_penalty_ticks(c):
    stress = max(0, min(100, c.get("stress", 0)))
    return STRESS_PATIENCE_PENALTY_TICKS * (stress / 100)


def start_waiting_for(c, world, kind, ref):
    """Arm a patience timer on the character's current (already-scaffolded
    'wait') activity. Call right after _route_wait() sets c["activity"]."""
    act = c.get("activity")
    if not act:
        return

    timer = BASE_PATIENCE_TICKS * _patience_modifier(c) - _stress_penalty_ticks(c)
    timer = max(MIN_PATIENCE_TICKS, round(timer))
    if kind == "person":
        timer = min(timer, PERSON_WAIT_MAX_TICKS)

    act.setdefault("state", {})["waiting_for"] = {
        "kind": kind,          # "person" | "business" | "delivery"
        "ref": ref,             # char_id / business key / free text
        "started_at_tick": world.get("tick", 0),
        "expires_at_tick": world.get("tick", 0) + timer,
        "timed_out": False,
    }


def tick_waiting(c, world):
    """Call once per character per tick (mirrors process_health's spot in
    brain/agent_loop.py::update_internal_state). No-ops unless the
    character is currently waiting-for-a-reason."""
    tick_door_wait(c, world)

    act = c.get("activity")
    if not act or act.get("type") != "wait":
        return
    waiting_for = act.get("state", {}).get("waiting_for")
    if not waiting_for or waiting_for.get("timed_out"):
        return

    apply_waiting_stress(c, world)

    if world.get("tick", 0) >= waiting_for["expires_at_tick"]:
        kind = waiting_for["kind"]

        # Per the user's ask: waiting on an occupied appliance (the only
        # instance of it, per systems/interactions.py::begin_interaction's
        # queueing path) escalates into real banging on the door instead
        # of just quietly re-checking -- a visible, audible cue rather
        # than a silent cognition-only wake, and genuinely repeats (a
        # fresh, shorter patience timer) rather than a one-off event, so
        # persistent occupancy reads as mounting impatience.
        if kind == "prop":
            bang_count = waiting_for.get("bang_count", 0) + 1
            waiting_for["bang_count"] = bang_count
            # setdefault, not get -- a waiting_for created before this
            # field existed (a live character already mid-queue when this
            # fix deployed) must have its start point pinned ONCE here,
            # not recomputed as "now" on every single check. A bare .get()
            # fallback would silently reset the 30-min clock back to zero
            # every time this branch ran, meaning a pre-existing waiter
            # could bang forever and never actually reach the cap
            # (confirmed live: exactly this happened to two characters
            # who were already queued when the previous fix restarted).
            started_at = waiting_for.setdefault("started_at_tick", world.get("tick", 0))

            if world.get("tick", 0) - started_at >= MAX_TOTAL_WAIT_TICKS:
                # Genuinely give up -- per the user's ask, waiting too long
                # should mean the character actually skips it rather than
                # banging on the door forever. Measured from when the wait
                # STARTED (not the most recent bang) so this is a real,
                # absolute 30-minute ceiling regardless of how many bang
                # cycles happened to fit in that window. Leave the queue,
                # clear the wait activity so the next tick's replan picks
                # something else, and avoid re-queuing at this exact anchor
                # for a while so the same unmet need doesn't just
                # re-trigger the identical queue immediately.
                ref = waiting_for["ref"]
                prop_id, _, anchor_name = ref.rpartition(":")
                for p in world.get("props", []):
                    if p.get("id") != prop_id:
                        continue
                    for a in p.get("anchors", []):
                        if a.get("name") == anchor_name and c["id"] in a.get("queue", []):
                            a["queue"].remove(c["id"])
                    break
                c.setdefault("_avoided_anchors", {})[ref] = world.get("tick", 0) + GIVE_UP_AVOID_TICKS
                waiting_for["timed_out"] = True
                c["activity"] = None
                wake_character(c, world, "gave_up_waiting", {
                    "kind": kind,
                    "ref":  ref,
                })
                return

            from systems.incidental_speech import fire_incidental
            text = "Hurry up in there!" if bang_count == 1 else "Come ON, seriously?!"
            fire_incidental(c, "inform", f"*bangs on the door* {text}", world)
            c["stress"] = min(100, c.get("stress", 0) + 4 * bang_count)

            # Re-arm a fixed follow-up timer (still occupied means still
            # banging) -- the 30-min hard cap above is what actually bounds
            # this, not the count of cycles that fit inside it.
            waiting_for["expires_at_tick"] = world.get("tick", 0) + REARM_TICKS
            wake_character(c, world, "waiting_timed_out", {
                "kind": kind,
                "ref":  waiting_for["ref"],
            })
        elif kind == "person":
            # Waited the most they will for someone: stop waiting, and let go of what they wanted from them.
            waiting_for["timed_out"] = True
            c["activity"] = None
            give_up_on_person(c, world, waiting_for.get("ref"), "they never came")
        else:
            waiting_for["timed_out"] = True
            wake_character(c, world, "waiting_timed_out", {
                "kind": kind,
                "ref":  waiting_for["ref"],
            })


# =========================================================
# GIVING UP ON SOMEONE
# =========================================================

def _wanted_from(c, intention, person_name):
    kind = intention.get("type", "")
    if kind == "play_with_friend":
        return f"playing with {person_name}"
    return f"{kind.replace('expectation:', '').replace('_', ' ')} with {person_name}"


def give_up_on_person(c, world, person_id, why):
    """Stop waiting for `person_id` and drop the intentions aimed at them -- one memory says so,
    and the character is woken to choose what to do instead (wake reason gave_up_waiting)."""
    from brain.memory import store_memory
    tick = world.get("tick", 0)
    person = (world.get("characters") or {}).get(person_id) or {}
    name = person.get("name") or "them"
    dropped = [i for i in (c.get("active_intentions") or []) if person_id and i.get("target_id") == person_id]
    if dropped:
        c["active_intentions"] = [i for i in c["active_intentions"] if i not in dropped]
    what = ", ".join(_wanted_from(c, i, name) for i in dropped)
    store_memory(c, f"I waited for {name} but {why}, so I gave up" + (f" on {what}." if what else "."),
                 importance=0.4, tags=["gave_up", "waiting"], tick=tick, source="internal", people=[person_id] if person_id else None)
    wake_character(c, world, "gave_up_waiting", {"kind": "person", "ref": person_id})


# =========================================================
# WAITING AT SOMEONE'S DOOR
# =========================================================
# Ringing the doorbell or knocking (systems/doorbell.py) used to leave the visitor standing there
# with nothing to end it: whether anyone came was up to the household's own thinking, and the
# visitor's intention ("go and ask Susan if she can play") kept escalating to "long overdue" while
# they waited. Now the visitor waits at most PERSON_WAIT_MAX_TICKS for someone from the household
# to come to them (or to be talking with them, or for the visitor to be let in); else they give up.

def start_door_wait(c, world, household, target_id=None):
    tick = world.get("tick", 0)
    current = c.get("_door_wait") or {}
    if current.get("household_id") == household.get("id") and tick < current.get("expires_at_tick", 0):
        return                                   # ringing again doesn't make them wait longer
    c["_door_wait"] = {"household_id": household.get("id"), "target_id": target_id,
                       "started_at_tick": tick, "expires_at_tick": tick + PERSON_WAIT_MAX_TICKS}


def _door_answered(c, world, household):
    chars = world.get("characters") or {}
    members = [chars[m] for m in household.get("members") or [] if m in chars]
    if household.get("home_id") and c.get("building_id") == household.get("home_id"):
        return True                              # let in (or walked in)
    cx, cy = c.get("x", 0), c.get("y", 0)
    for m in members:
        if abs(m.get("x", 0) - cx) + abs(m.get("y", 0) - cy) <= DOOR_ANSWER_DISTANCE and not m.get("off_grid"):
            return True
    try:
        from brain.conversations import find_active_conversation_for
        conv = find_active_conversation_for(world, c["id"])
    except Exception:                            # noqa: BLE001
        conv = None
    return bool(conv and any(m["id"] in (conv.get("participants") or []) for m in members))


def tick_door_wait(c, world):
    wait = c.get("_door_wait")
    if not wait:
        return
    household = (world.get("households") or {}).get(wait.get("household_id"))
    if not household or _door_answered(c, world, household):
        c.pop("_door_wait", None)
        return
    if world.get("tick", 0) < wait.get("expires_at_tick", 0):
        return
    c.pop("_door_wait", None)
    act = c.get("activity") or {}
    if act.get("type") in ("ring_doorbell", "knock_on_door", "wait"):
        c["activity"] = None
    target_id = wait.get("target_id")
    if target_id:
        give_up_on_person(c, world, target_id, "nobody came to the door")
    else:
        from brain.memory import store_memory
        store_memory(c, f"Nobody came to the door at {household.get('name', 'their house')}, so I gave up.",
                     importance=0.4, tags=["gave_up", "waiting"], tick=world.get("tick", 0), source="internal")
        wake_character(c, world, "gave_up_waiting", {"kind": "door", "ref": household.get("id")})

