import uuid, random
from brain.memory import store_memory
from core.event_bus import emit


def create_911_call(world, caller, emergency_type, report):
    call = {
        "id":       f"call_{uuid.uuid4().hex[:6]}",
        "type":     emergency_type,
        "caller":   caller["id"],
        "location": {"x": caller["x"], "y": caller["y"]},
        "report":   report,
        "status":   "pending",
        "tick":     world["tick"],
    }
    world.setdefault("calls", []).append(call)
    store_memory(caller, f"Called 911: {report}", .8, ["911", emergency_type], "emergency", world["tick"])
    emit("emergency_call_created", {"call_id": call["id"], "type": emergency_type})
    return call


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

        if random.random() < .0008:
            inc = {
                "id":           f"inc_{uuid.uuid4().hex[:6]}",
                "type":         "injury",
                "participants": [c["id"]],
                "location":     {"x": c["x"], "y": c["y"]},
                "reported":     False,
                "tick":         world["tick"],
            }
            world.setdefault("incidents", []).append(inc)
            c["health"].setdefault("conditions", []).append(
                {"id": "injury", "symptoms": ["pain", "fatigue"], "curable": True, "treated": False}
            )
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
            emit("incident_resolved", {"responder_id": r["id"], "type": r["type"]})
