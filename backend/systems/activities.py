import time
import random

ACTIVITIES = {
    "apply_job": {"prop": "computer", "avg_minutes": 6},
    "look_for_job": {"prop": "computer", "avg_minutes": 4},
    "use_toilet": {"prop": "toilet", "avg_minutes": 3},
    "sleep": {"prop": "bed", "avg_minutes": 480}
}


def compute_duration_seconds(c, base_minutes):
    seconds = base_minutes * 60

    emotion = c.get("emotion")

    if emotion == "stressed":
        seconds *= 1.3
    elif emotion == "focused":
        seconds *= 0.8

    if "lazy" in c.get("traits", []):
        seconds *= 1.2

    seconds *= random.uniform(0.85, 1.15)

    return int(seconds)


def start_activity(c, world, name, prop):

    config = ACTIVITIES.get(name)
    if not config:
        return

    duration = compute_duration_seconds(c, config["avg_minutes"])

    c["activity"] = {
        "name": name,
        "prop_id": prop["id"],
        "start_time": world["calendar"]["timestamp"],
        "end_time": world["calendar"]["timestamp"] + duration
    }
    # =====================================
    # ANIMATION STATE
    # =====================================

    c["animation_state"] = name

def update_activity(c, world):

    act = c.get("activity")
    if not act:
        return False

    if world["calendar"]["timestamp"] >= act["end_time"]:
        complete_activity(c, world)
        c["activity"] = None
        return False

    return True


def complete_activity(c, world):

    name = c["activity"]["name"]

    if name == "apply_job":
        from systems.jobs import apply_for_job
        apply_for_job(c, world)

    elif name == "use_toilet":
        c["needs"]["bladder"] = 0

    elif name == "sleep":
        c["needs"]["energy"] = 1.0
    c["animation_state"] = "idle"
    release_anchor(c, world)

def update_interaction_phases(c, world):
    act = c.get("activity")
    if not act:
        return

    phase = act.get("phase")
    start_tick = act.get("phase_started", 0)

    elapsed = world["tick"] - start_tick

    # -----------------
    # START → LOOP
    # -----------------
    if phase == "start" and elapsed > 2:
        act["phase"] = "loop"
        act["phase_started"] = world["tick"]

    # -----------------
    # LOOP → STOP
    # -----------------
    elif phase == "loop" and elapsed > act.get("duration", 20):
        act["phase"] = "stop"
        act["phase_started"] = world["tick"]
        c["animation_state"] = (
            act["name"]
        )

    # -----------------
    # STOP → DONE
    # -----------------
    elif phase == "stop" and elapsed > 2:
        from systems.occupancy import release_anchor, release_reservation
        release_anchor(c, world)
        release_reservation(c, world)
        c["animation_state"] = "idle"
        c["activity"] = None