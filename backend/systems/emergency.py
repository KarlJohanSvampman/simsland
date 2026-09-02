import uuid, random
from brain.memory import store_memory
from core.event_bus import emit


# Single source of truth for "which service responds to this incident type,
# what does the caller say, and how likely is a bystander to report it
# unprompted" -- previously duplicated (and drifted) between this module's
# auto_report_incidents() and action_router.py's now-removed
# _INCIDENT_CALL_TYPE. action_router.py::_route_call_911 imports this same
# dict rather than keeping its own copy. Only incident types something in
# the codebase actually creates are listed (dead "injury"/"crime" entries
# from the old duplicate dict are dropped -- nothing ever creates an
# incident of either type).
INCIDENT_CALL_TYPE = {
    "domestic_disturbance": ("police",  "There is a serious disturbance.",       .2),
    "assault":              ("police",  "Someone was just physically attacked.", .35),
    "property_damage":      ("police",  "Someone is destroying property.",       .15),
    "burglary":             ("police",  "Someone just broke into my house!",     .3),
    "medical_emergency":    ("medical", "Someone needs urgent medical help.",    .6),
    "fire":                 ("fire",    "There's a fire!",                       .6),
}


def create_911_call(world, caller, emergency_type, report, incident_id=None):
    call = {
        "id":          f"call_{uuid.uuid4().hex[:6]}",
        "type":        emergency_type,
        "caller":      caller["id"],
        "location":    {"x": caller["x"], "y": caller["y"]},
        "report":      report,
        "status":      "pending",
        "tick":        world["tick"],
        "incident_id": incident_id,
    }
    world.setdefault("calls", []).append(call)
    store_memory(caller, f"Called 911: {report}", .8, ["911", emergency_type], "emergency", world["tick"])
    emit("emergency_call_created", {"call_id": call["id"], "type": emergency_type})
    return call


def report_assault_incident(world, offender, victim=None):
    """
    Create a real, deterministic incident for a physical altercation
    (see core/event_handlers.py::_on_fight_physical, and
    systems/hostile_actions.py::resolve_hostile_action for the individual
    punch/kick/shove/... case). Unlike trigger_incident()'s dice-roll
    incidents (domestic_disturbance/injury, gated on unrelated conditions
    like emotional_temperature), this always fires — a physical fight is
    not a "maybe."

    victim is optional (the conflict_pipeline call site only has one
    character handy) — when known, both offender and victim are recorded
    as participants so either one (or a bystander, via the existing
    Manhattan-4 proximity check in context_builder.py::
    _build_incident_context) can reach this incident with call_911.
    offender_id is recorded explicitly (distinct from participants) so
    later code can tell who to blame without guessing from list order.
    """
    participants = [offender["id"]]
    if victim and victim["id"] not in participants:
        participants.append(victim["id"])
    inc = {
        "id":           f"inc_{uuid.uuid4().hex[:6]}",
        "type":         "assault",
        "offender_id":  offender["id"],
        "participants": participants,
        "location":     {"x": offender["x"], "y": offender["y"]},
        "reported":     False,
        "tick":         world["tick"],
    }
    world.setdefault("incidents", []).append(inc)
    emit("incident_created", {"incident_id": inc["id"], "type": inc["type"]})
    return inc


def report_property_damage_incident(world, offender, prop):
    """
    Create a real incident for a deliberate "destroy" action (see
    activities.py's trash/destroy completion handler) -- mirrors
    report_assault_incident's shape, just no victim. offender_is_minor is
    set directly here (rather than by the caller, like hostile_actions.py
    does for assault) since there's only one call site for this one.
    Reused as-is by action_router.py::_route_call_parent and
    context_builder.py::build_available_actions -- both key off the
    generic offender_is_minor/victim_injured fields, not anything
    assault-specific, so a property-damage incident needs no changes to
    either.
    """
    inc = {
        "id":           f"inc_{uuid.uuid4().hex[:6]}",
        "type":         "property_damage",
        "offender_id":  offender["id"],
        "participants": [offender["id"]],
        "location":     {"x": offender["x"], "y": offender["y"]},
        "reported":     False,
        "tick":         world["tick"],
    }
    if offender.get("age_group") == "child":
        inc["offender_is_minor"] = True
    world.setdefault("incidents", []).append(inc)
    emit("incident_created", {"incident_id": inc["id"], "type": inc["type"]})
    return inc


def report_medical_emergency_incident(world, c):
    """
    Create a real incident when a character's severity (systems/health.py::
    compute_severity) first crosses into "severe"/"critical" — the 911
    bridge for the health-severity spine, same always-fires shape as
    report_assault_incident() above, just with no offender: this isn't
    caused by another character, so offender_id is None (participants is
    just the affected character, still reachable via call_911's existing
    proximity/awareness gate and _build_incident_context's proximity scan).
    """
    inc = {
        "id":           f"inc_{uuid.uuid4().hex[:6]}",
        "type":         "medical_emergency",
        "offender_id":  None,
        "participants": [c["id"]],
        "location":     {"x": c["x"], "y": c["y"]},
        "reported":     False,
        "tick":         world["tick"],
    }
    world.setdefault("incidents", []).append(inc)
    emit("incident_created", {"incident_id": inc["id"], "type": inc["type"]})
    return inc


def trigger_incident(world, c):
    """Create incidents from character state or random world events."""
    if c is not None:
        if c.get("emotional_temperature", 0) > 92 and random.random() < .02:
            inc = {
                "id":           f"inc_{uuid.uuid4().hex[:6]}",
                "type":         "domestic_disturbance",
                "participants": [c["id"]],
                "location":     {"x": c["x"], "y": c["y"]},
                "reported":     False,
                "tick":         world["tick"],
            }
            world.setdefault("incidents", []).append(inc)
            emit("incident_created", {"incident_id": inc["id"], "type": inc["type"]})
    else:
        # World-level random incidents (no character context)
        if random.random() < .0002:
            world.setdefault("incidents", []).append({
                "id":           f"inc_{uuid.uuid4().hex[:6]}",
                "type":         "random_event",
                "participants": [],
                "location":     {"x": random.randint(0, 20), "y": random.randint(0, 20)},
                "reported":     False,
                "tick":         world["tick"],
            })

        # Fire — only rolled against buildings that currently have someone
        # in them, so it's actually perceivable when it starts. Severity
        # then climbs via tick_fire_incidents() until a "fire" responder
        # extinguishes it (see resolve() below).
        if random.random() < .0004:
            chars = world.get("characters", {})
            occupied = {}
            for ch in chars.values():
                bid = ch.get("building_id")
                if bid:
                    occupied.setdefault(bid, []).append(ch)
            if occupied:
                building_id = random.choice(list(occupied.keys()))
                present = occupied[building_id]
                building = next(
                    (b for b in world.get("buildings", []) if b["id"] == building_id),
                    None,
                )
                anchor = present[0]
                inc = {
                    "id":           f"inc_{uuid.uuid4().hex[:6]}",
                    "type":         "fire",
                    "participants": [p["id"] for p in present],
                    "building_id":  building_id,
                    "room_id":      anchor.get("room_id"),
                    "location":     {
                        "x": building["x"] if building else anchor["x"],
                        "y": building["y"] if building else anchor["y"],
                    },
                    "severity":     15,
                    "extinguished": False,
                    "reported":     False,
                    "tick":         world["tick"],
                }
                world.setdefault("incidents", []).append(inc)
                emit("incident_created", {"incident_id": inc["id"], "type": inc["type"]})

                # Curiosity hook (systems/curiosity.py) -- a smoke alarm
                # is a genuinely piercing, real audible event, unlike the
                # fire itself (which has no live "explosion" trigger yet
                # -- see brain/perception.py's VOLUME_TIERS "intense"
                # tier, deliberately left without a producer for now).
                try:
                    from brain.perception import emit_ambient_sound
                    emit_ambient_sound(world, inc["location"]["x"], inc["location"]["y"], "smoke_alarm", "high")
                except Exception:
                    pass


def auto_report_incidents(world):
    for inc in world.get("incidents", []):
        if inc.get("reported"):
            continue
        participants = inc.get("participants", [])
        if not participants:
            continue
        caller = world["characters"].get(participants[0])
        if not caller:
            continue
        entry = INCIDENT_CALL_TYPE.get(inc["type"])
        if not entry:
            continue
        service, report, chance = entry
        if random.random() < chance:
            create_911_call(world, caller, service, report, incident_id=inc["id"])
            inc["reported"] = True


def dispatch(world):
    for call in world.get("calls", []):
        if call["status"] == "pending":
            resp = {
                "id":           f"resp_{uuid.uuid4().hex[:6]}",
                "type":         call["type"],
                "call_id":      call["id"],
                "incident_id":  call.get("incident_id"),
                "location":     call["location"],
                "status":       "en_route",
                "arrival_tick": world["tick"] + 8,
            }
            world.setdefault("responders", []).append(resp)
            call["status"] = "dispatched"
            emit("responder_dispatched", {"responder_id": resp["id"], "type": resp["type"]})


def resolve(world):
    for r in world.get("responders", []):
        if r["status"] == "en_route" and world["tick"] >= r["arrival_tick"]:
            r["status"] = "resolved"
            loc = r["location"]
            if r["type"] == "police":
                for c in world["characters"].values():
                    if abs(c["x"] - loc["x"]) + abs(c["y"] - loc["y"]) < 4:
                        c["emotional_temperature"] = max(0, c.get("emotional_temperature", 20) - 20)
            elif r["type"] == "medical":
                # The actual payoff of the health-severity spine reaching all
                # the way to a physical consequence: an ambulance resolving
                # for a medical_emergency incident now sends anyone still
                # severe/critical to the hospital (systems/offgrid.py),
                # instead of writing a health["treatment"] flag nothing ever
                # read. Only the incident's own participants are checked --
                # not everyone in the blast radius -- since this ambulance
                # was dispatched for them specifically.
                inc = next(
                    (i for i in world.get("incidents", [])
                     if i["id"] == r.get("incident_id")),
                    None,
                )
                for cid in (inc.get("participants", []) if inc else []):
                    patient = world["characters"].get(cid)
                    if not patient or patient.get("alive") is False:
                        continue
                    from systems.health import compute_severity, treat_all_by_method
                    # On-scene ambulance clearance (decision #13's new
                    # "ambulance" treatable_by value) -- an indefinite hazard
                    # (one that ignores duration_hours and never self-
                    # resolves) can be cleared right here rather than only
                    # via a first-aid/hospital visit.
                    treat_all_by_method(patient, world, "ambulance")
                    _, tier = compute_severity(patient)
                    if tier in ("severe", "critical") and not patient.get("off_grid"):
                        from systems.offgrid import send_offgrid
                        send_offgrid(patient, world, "hospital", 6 * 60 if tier == "critical" else 3 * 60)
            elif r["type"] == "fire":
                inc = next(
                    (i for i in world.get("incidents", [])
                     if i["id"] == r.get("incident_id")),
                    None,
                )
                if inc:
                    inc["severity"] = 0
                    inc["extinguished"] = True
            emit("incident_resolved", {"responder_id": r["id"], "type": r["type"]})


def tick_fire_incidents(world):
    """Advance active fire incidents: severity climbs each tick until a
    'fire' responder extinguishes it (see resolve() above); harm applies to
    anyone still in the building at higher severity thresholds. Feeds the
    real health_state pipeline (apply_injury) instead of the disconnected
    legacy c["health"]["conditions"] list, so a fire actually registers
    in compute_severity() and can trip the 911 medical-emergency bridge
    like any other injury."""
    from systems.health import apply_injury
    chars = world.get("characters", {})
    for inc in world.get("incidents", []):
        if inc.get("type") != "fire" or inc.get("extinguished"):
            continue
        inc["severity"] = min(100, inc.get("severity", 0) + 3)
        building_id = inc.get("building_id")
        if not building_id:
            continue
        present = [c for c in chars.values() if c.get("building_id") == building_id]
        for c in present:
            if inc["severity"] >= 40:
                smoke_treated = c.setdefault("health_state", {}).setdefault("_treated_fire_smoke", [])
                if inc["id"] not in smoke_treated:
                    apply_injury(c, world, "minor_burn", "fire", tick=world["tick"])
                    smoke_treated.append(inc["id"])
            if inc["severity"] >= 70:
                # Dedup via a small tag list independent of body_parts --
                # the old flat injuries-list dedup pattern (tagging one
                # entry with incident_id) doesn't map onto the new
                # per-bodypart shape, so this is the minimal equivalent.
                # A list (not a set) so this stays JSON-serializable like
                # every other piece of character state.
                treated = c.setdefault("health_state", {}).setdefault("_treated_fire_incidents", [])
                if inc["id"] not in treated:
                    apply_injury(c, world, "severe_burn", "fire", tick=world["tick"])
                    treated.append(inc["id"])
