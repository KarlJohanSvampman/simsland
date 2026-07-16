import uuid, random
from brain.memory import store_memory
from core.event_bus import emit


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
        if inc["type"] == "domestic_disturbance" and random.random() < .2:
            create_911_call(world, caller, "police", "There is a serious disturbance.")
            inc["reported"] = True
        elif inc["type"] == "injury" and random.random() < .4:
            create_911_call(world, caller, "medical", "Someone is injured and needs help.")
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
                for c in world["characters"].values():
                    if abs(c["x"] - loc["x"]) + abs(c["y"] - loc["y"]) < 4:
                        c["health"]["treatment"] = "first_response"
            elif r["type"] == "fire":
                inc = next(
                    (i for i in world.get("incidents", [])
                     if i["id"] == r.get("incident_id")),
                    None,
                )
                if inc:
                    inc["severity"] = 0
                    inc["extinguished"] = True
                    building_id = inc.get("building_id")
                    for c in world["characters"].values():
                        if building_id and c.get("building_id") != building_id:
                            continue
                        hs = c.setdefault("health_state", {})
                        hs["injuries"] = [
                            inj for inj in hs.get("injuries", [])
                            if not (inj.get("type") == "burn" and inj.get("incident_id") == inc["id"])
                        ]
            emit("incident_resolved", {"responder_id": r["id"], "type": r["type"]})


def tick_fire_incidents(world):
    """Advance active fire incidents: severity climbs each tick until a
    'fire' responder extinguishes it (see resolve() above); harm applies to
    anyone still in the building at higher severity thresholds. Feeds the
    real health_state pipeline (apply_burn_injury/add_pain) instead of the
    disconnected legacy c["health"]["conditions"] list, so a fire actually
    registers in compute_severity() and can trip the 911 medical-emergency
    bridge like any other injury."""
    from systems.health import apply_burn_injury, add_pain
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
                add_pain(c, 2)
            if inc["severity"] >= 70:
                injuries = c.setdefault("health_state", {}).setdefault("injuries", [])
                if not any(inj.get("type") == "burn" and inj.get("incident_id") == inc["id"]
                           for inj in injuries):
                    burn = apply_burn_injury(c, world, "torso", severity=0.5, tick=world["tick"])
                    burn["incident_id"] = inc["id"]
