"""
systems/dependent_tracking.py

A parent-readable "where's my kid" summary for each entry in a parent's
real, priority-ordered c["dependents"] list (systems/child_care.py::
_sync_dependents) -- last known location, last real contact (phone or
face-to-face, sourced from brain/conversations.py's own medium field),
and an expected activity derived from the child's own generated week
schedule (systems/scheduling.py) plus whether they've satisfied their
real announce_departure authority contract (systems/social_contracts.py)
if currently away from home. Read-only, computed on demand -- nothing
here is stored, so it can't drift out of sync with the real underlying
data.

Also runs a real, age-scaled periodic "check on my kid" background
behavior (tick_dependent_checks) -- a younger child gets checked far
more often and far more reliably than an older one, who's more likely
to have the check silently skipped this cycle. A check that finds the
child unaccounted for raises a real intention to follow up: call the
child directly once they're old enough to plausibly carry/answer a
phone (age >= 10), otherwise call whoever's currently responsible for
them (get_child_whereabouts_summary's own current_caretaker).
"""

import random


def _current_day_key(world):
    cal = world.get("calendar", {})
    return cal.get("day_of_week") or cal.get("weekday")


def _current_time_str(world):
    cal = world.get("calendar", {})
    return f"{cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}"


def _expected_activity(child, world):
    """Reads the child's own real generated week schedule for whatever
    block covers right now -- a real, small "where do we think they
    are" derived from actual data, not a guess."""
    schedule = child.get("schedule") or {}
    week = schedule.get("week") or {}
    day_key = _current_day_key(world)
    blocks = week.get(day_key) or []
    now = _current_time_str(world)
    for block in blocks:
        if block.get("start", "00:00") <= now < block.get("end", "23:59"):
            return block.get("activity")
    return None


def _last_contact(parent, child, world):
    """Most recent real conversation (any medium) between parent and
    child, per brain/conversations.py's own medium field -- "in_person"
    | "call" | "text" | "email"."""
    best = None
    for conv in world.get("conversations", {}).values():
        participants = conv.get("participants", [])
        if parent["id"] not in participants or child["id"] not in participants:
            continue
        history = conv.get("history", [])
        last_tick = history[-1].get("tick") if history else None
        if last_tick is None:
            continue
        if best is None or last_tick > best["tick"]:
            best = {"medium": conv.get("medium", "in_person"), "tick": last_tick}
    return best


# Off-grid reasons long/uncertain enough that a child isn't expected home
# today at all -- mirrors offgrid.py's own _UNCAPPED_DURATION_REASONS,
# the real signal for "not just a normal school day."
_NOT_HOME_TODAY_REASONS = {"jail", "held_pending_trial", "cps_care", "hospital",
                           "hospital_treatment", "surgery", "temporary_separation"}


def _current_caretaker_char(parent, child, world):
    """Who's actually responsible for this child RIGHT NOW, if not this
    parent -- CPS (no real character, id None), a placement relative, or
    another present adult in the child's current household/building.
    Real, if deliberately shallow: no live shared-custody calendar exists
    yet (flagged, not built this round) -- this reads only the CURRENT,
    already-real state (off-grid reason, current household/building), not
    a scheduled rotation. Returns (id_or_None, name_or_None)."""
    if child.get("off_grid_reason") == "cps_care":
        return None, "Child Protective Services"

    chars = world.get("characters", {})
    if child.get("household_id") and child.get("household_id") != parent.get("household_id"):
        household = world.get("households", {}).get(child["household_id"], {})
        for mid in household.get("members", []):
            other = chars.get(mid)
            if other and other["id"] != child["id"] and other.get("age_group") in ("adult", "elderly") \
                    and other.get("alive") is not False:
                return other["id"], other.get("name", mid)

    if not child.get("off_grid") and child.get("building_id") and child.get("building_id") != parent.get("building_id"):
        for other in chars.values():
            if other["id"] == child["id"] or other["id"] == parent["id"]:
                continue
            if other.get("building_id") == child.get("building_id") and other.get("age_group") in ("adult", "elderly") \
                    and other.get("alive") is not False:
                return other["id"], other.get("name", other["id"])

    return None, None


def get_child_whereabouts_summary(parent, child, world):
    """One real, computed summary per dependent -- consumed by anything
    that wants to reason about a parent's actual knowledge of a child's
    whereabouts (child_welfare.py's own checks, a future Inspector
    panel, etc.)."""
    if child.get("off_grid"):
        last_known = {"status": "away", "reason": child.get("off_grid_reason")}
    else:
        last_known = {
            "x": child.get("x"), "y": child.get("y"),
            "building_id": child.get("building_id"), "tick": world.get("tick", 0),
        }

    announced = None
    if child.get("_departed_this_tick"):
        announced = bool(child.get("_announced_departure") or child.get("_left_note_this_tick"))

    reason = child.get("off_grid_reason")
    expected_home_today = not (child.get("off_grid") and reason in _NOT_HOME_TODAY_REASONS)
    caretaker_id, caretaker_name = _current_caretaker_char(parent, child, world)

    return {
        "child_id":             child["id"],
        "last_known_location":  last_known,
        "last_contact":         _last_contact(parent, child, world),
        "expected_activity":    _expected_activity(child, world),
        "announced_departure":  announced,
        # Who's actually responsible for them right now, if not this
        # parent (CPS, a placement relative, a present adult wherever
        # they currently are) -- None means "with/near this parent."
        "current_caretaker":    caretaker_name,
        "current_caretaker_id": caretaker_id,
        # A real, raw return_tick (when off-grid) for a consumer to
        # format/project into a real date -- same convention Phase F's
        # sidebar display already uses for long off-grid stays, rather
        # than pre-formatting a string here.
        "expected_return_tick": child.get("return_tick") if child.get("off_grid") else None,
        "expected_home_today":  expected_home_today,
    }


def get_dependents_summary(parent, world):
    """One summary per entry in c["dependents"], already priority-
    ordered (least-capable/youngest first) by child_care.py's own sync."""
    chars = world.get("characters", {})
    summaries = []
    for cid in parent.get("dependents", []):
        child = chars.get(cid)
        if not child or child.get("alive") is False:
            continue
        summaries.append(get_child_whereabouts_summary(parent, child, world))
    return summaries


# ── Periodic, age-scaled "check on my kid" background behavior ─────────────

_BASE_CHECK_MINUTES = 15.0
_MIN_CHECK_MINUTES = 3.0
_REFERENCE_AGE = 12.0  # the age at which the check settles to the base rate
_MAX_SKIP_CHANCE = 0.5  # skip chance at/above _REFERENCE_AGE
_DIRECT_CALL_AGE = 10  # old enough a parent can plausibly call THEM directly


def _age_scale(age):
    """0 (newborn) .. 1 (at/above _REFERENCE_AGE) -- younger scales the
    interval down (more frequent) and the skip chance down (less likely
    to be skipped), matching "the lower the age the more often" for both."""
    return max(0.0, min(1.0, (age or 0) / _REFERENCE_AGE))


def _roll_next_check_tick(world, age):
    scale = _age_scale(age)
    scaled_minutes = max(_MIN_CHECK_MINUTES, _BASE_CHECK_MINUTES * scale)
    # Fully re-randomized every single time, not just jittered around a
    # fixed base -- per the user's own explicit "randomize 100%."
    minutes = random.uniform(0.5, 1.5) * scaled_minutes
    return world.get("tick", 0) + int(minutes * 60)


def _is_unaccounted_for(child, summary, world):
    """Real, if simple, "does this look wrong" check -- off-grid on a
    long-stay reason is already known/expected (not a surprise the
    parent needs to chase down); otherwise, a child who isn't home
    during a schedule block that isn't itself "home"/"school"/unset,
    with no current caretaker resolved, reads as genuinely unaccounted
    for."""
    if not summary["expected_home_today"]:
        return False  # already a known, ongoing situation (jail/CPS/etc.)
    if child.get("off_grid"):
        return summary["current_caretaker"] is None
    return False


def tick_dependent_checks(parent, world):
    """Called per-parent (see sim_loop.py's wiring) -- walks each real
    dependent, rolling their own independent, age-scaled check timer."""
    from brain.intentions import add_intention

    chars = world.get("characters", {})
    timers = parent.setdefault("_dependent_check_timers", {})

    for cid in parent.get("dependents", []):
        child = chars.get(cid)
        if not child or child.get("alive") is False:
            timers.pop(cid, None)
            continue

        next_tick = timers.get(cid)
        if next_tick is None:
            timers[cid] = _roll_next_check_tick(world, child.get("age"))
            continue
        if world.get("tick", 0) < next_tick:
            continue

        # Every check re-rolls its own next timer regardless of outcome --
        # skip or real check, the cadence keeps going either way.
        timers[cid] = _roll_next_check_tick(world, child.get("age"))

        skip_chance = _MAX_SKIP_CHANCE * _age_scale(child.get("age"))
        if random.random() < skip_chance:
            continue  # this cycle's check is skipped -- timer already reset above

        summary = get_child_whereabouts_summary(parent, child, world)
        _maybe_auto_propagate(parent, child, world)
        if not _is_unaccounted_for(child, summary, world):
            continue

        if (child.get("age") or 0) >= _DIRECT_CALL_AGE:
            reason = f"{child.get('name', 'your child')} isn't where they're supposed to be -- you should call them."
            intention_type = f"check_on_child_{cid}"
            target_id = cid
        else:
            caretaker_name = summary.get("current_caretaker") or "whoever's watching them"
            reason = f"You should check with {caretaker_name} about {child.get('name', 'your child')} -- they're not accounted for."
            intention_type = f"check_on_child_via_caretaker_{cid}"
            target_id = summary.get("current_caretaker_id")

        add_intention(parent, {
            "type":      intention_type,
            "category":  "health",
            "priority":  65,
            "reason":    reason,
            "child_id":  cid,
            "target_id": target_id,
        })


def propagate_from_caretaker_contact(parent, child, world):
    """Called once a parent actually makes contact with the child's
    current caretaker (a real phone/in-person conversation) -- refreshes
    the parent's own stored "last known" snapshot for this child from a
    fresh live summary. This is the concrete meaning of "get this table
    updated by propagating the values from their table": the parent's
    OWN belief about the child only updates on real contact, not just
    because the simulation itself always knows the ground truth."""
    summary = get_child_whereabouts_summary(parent, child, world)
    known = parent.setdefault("_dependent_known_state", {})
    known[child["id"]] = {**summary, "confirmed_tick": world.get("tick", 0)}
    return known[child["id"]]


def _maybe_auto_propagate(parent, child, world):
    """Detects a fresh conversation between the parent and the child's
    CURRENT caretaker (any medium) that hasn't been propagated yet, and
    refreshes the parent's known-state snapshot from it -- the real
    trigger for "whenever we inquire... by calling the current caretaker."""
    caretaker_id, _ = _current_caretaker_char(parent, child, world)
    if not caretaker_id:
        return
    caretaker = world.get("characters", {}).get(caretaker_id)
    if not caretaker:
        return
    contact = _last_contact(parent, caretaker, world)
    if not contact:
        return
    known = parent.get("_dependent_known_state", {}).get(child["id"])
    already_confirmed = known.get("confirmed_tick", -1) if known else -1
    if contact["tick"] > already_confirmed:
        propagate_from_caretaker_contact(parent, child, world)
