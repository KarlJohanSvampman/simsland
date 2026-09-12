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
        else:
            waiting_for["timed_out"] = True
            wake_character(c, world, "waiting_timed_out", {
                "kind": kind,
                "ref":  waiting_for["ref"],
            })
