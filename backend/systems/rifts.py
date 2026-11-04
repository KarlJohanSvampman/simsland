"""
systems/rifts.py

Falling out with someone you live with -- and what you do about it.

A fight used to have a flat chance of sending either party off to stay with friends or family straight away
(core/event_handlers.py, systems/temporary_separation.py). Leaving should come last, not first, and it should be for
something. Now a fight that ends badly between two people in the same household -- or simply standing with them
having sunk below STANDING_BAD -- opens a rift (c["rifts"][other id]), about something: the fight's topic, or the
grievance between them.

While a rift is open, once a day (timeout event "rift:<id>", key "try:<other id>"), the character recalls what led
to it -- the fights and grievances, with when -- and tries to find a way forward, one of:

  step_down    give in on it and apologise;
  agreement    sit down and work out terms -- the existing negotiation (systems/conflict_pipeline.py), which can end
               in an agreement and a social contract, or in another fight;
  trade        offer something for it (taking over a chore, a favour) -- if accepted, they owe it;
  third_party  ask someone both of them trust to plead their case.

Which one depends on who they are and what has already failed. An understanding closes the rift (both sides'
resentment and hostility toward each other come down so their standing is back above the line).

After MAX_ATTEMPTS failed attempts, or STAY_DAYS days of bad standing, they consider leaving for a while -- and
leaving has a purpose:

  time_away         to get away from the other person for a few days, staying with family or a close friend, and
                    come back to try to make peace (another attempt as soon as they're back);
  change_of_scenery the same, off-grid somewhere, when there's nobody to stay with;
  moving_out        when it's beyond repair (it got physical, standing is very bad, or it keeps failing): they stay
                    away, and every few days come back to pick up some of their things -- which is how the household
                    finds out, until the last of their things is gone.

Children never leave, and nobody leaves a young child alone at home (systems/temporary_separation.py).
"""

import random

from core import scheduler

STANDING_BAD = -50              # below this, things are bad between them
STANDING_VERY_BAD = -150        # beyond repair, as far as they can tell
MAX_ATTEMPTS = 3
STAY_DAYS = 7
DAY = 86400
FIRST_TRY_TICKS = 4 * 3600      # a few hours to cool off before the first try
LEAVE_CHANCE = 0.6              # once it's come to that, per daily consideration
AWAY_DAYS = (2, 5)
PICKUP_DAYS = (2, 4)
PICKUPS = 3
SCAN_EVERY = 3600

OWNER = "rift"
# what a fight that ends badly costs in standing (resentment), on top of conflict_pipeline's own small adjustments
FIGHT_RESENTMENT = {"suppressed": 30, "cold_shoulder": 50, "storm_off": 60, "physical_resolved": 90}
_BAD_OUTCOMES = {"storm_off", "cold_shoulder", "physical_resolved", "suppressed"}

_YIELDING = {"agreeable", "empathetic", "conflict_averse", "forgiving", "kind", "people_pleaser", "humble", "shy"}
_PROUD = {"stubborn", "proud", "hot_headed", "arrogant", "vindictive", "aggressive", "narcissistic"}
_TRADERS = {"pragmatic", "rational", "calculating", "materialistic", "ambitious", "frugal"}


# =========================================================
# STANDING
# =========================================================

def standing(c, other_id):
    """How c feels about other, in one number: liking and trust against resentment and hostility."""
    rel = (c.get("relationships") or {}).get(other_id) or {}
    return ((rel.get("friendship") or 0) + 0.5 * (rel.get("trust") or 0) + 0.5 * (rel.get("respect") or 0)
            + 0.3 * (rel.get("warmth") or 0) - (rel.get("resentment") or 0) - (rel.get("hostility") or 0))


def _housemates(c, world):
    hh = (world.get("households") or {}).get(c.get("household_id")) or {}
    chars = world.get("characters") or {}
    return [chars[m] for m in hh.get("members") or [] if m in chars and m != c["id"]
            and chars[m].get("alive") is not False]


def _is_child(c):
    return (c.get("age") or 99) < 18


def _traits(c):
    return set((c.get("traits") or []) + (c.get("personality_traits") or []))


def _name(world, cid):
    return ((world.get("characters") or {}).get(cid) or {}).get("name", "someone")


def _owner(c):
    return f"{OWNER}:{c['id']}"


def _mem(c, world, text, importance=0.55, people=None, tags=("rift",)):
    from brain.memory import store_memory
    store_memory(c, text, importance=importance, tags=list(tags), tick=world.get("tick", 0), people=people,
                 source="internal")


# =========================================================
# OPENING A RIFT
# =========================================================

def _topic_between(world, c, other_id):
    for f in reversed(world.get("fight_log") or []):
        if c["id"] in f.get("parties", []) and other_id in f.get("parties", []) and f.get("topic"):
            return f["topic"]
    griefs = [g for g in c.get("grievances") or [] if g.get("caused_by") == other_id]
    if griefs:
        return str(max(griefs, key=lambda g: g.get("severity", 0)).get("event_type", "")).replace("_", " ")
    return "how things are between us"


def open_rift(c, world, other_id, topic=None, physical=False):
    if _is_child(c) or other_id == c["id"]:
        return None
    rifts = c.setdefault("rifts", {})
    rift = rifts.get(other_id)
    tick = world.get("tick", 0)
    if rift and rift.get("status") in ("open", "away", "moving_out"):
        rift["physical"] = rift.get("physical") or physical
        if topic and topic not in rift["topics"]:
            rift["topics"].append(topic)
        return rift
    rift = rifts[other_id] = {"with": other_id, "since": tick, "topics": [topic or _topic_between(world, c, other_id)],
                              "attempts": 0, "tried": [], "status": "open", "physical": physical, "history": []}
    scheduler.schedule_in(world, _owner(c), f"try:{other_id}", FIRST_TRY_TICKS)
    return rift


def on_conflict_resolved(world, data):
    """A fight between two people who live together that ended badly opens a rift for both (instead of a chance of
    moving out on the spot); an agreement reached in a reconciliation closes it."""
    chars = world.get("characters") or {}
    parties = [chars[p] for p in data.get("parties", []) if p in chars]
    if len(parties) != 2:
        return
    a, b = parties
    conflict = (world.get("conflicts") or {}).get(data.get("conflict_id")) or {}
    outcome = data.get("outcome")
    reconciling = conflict.get("reconciliation")
    if reconciling:
        c = chars.get(conflict.get("initiator"))
        other = b if c is a else a
        if c is not None:
            _attempt_result(c, world, other, "agreement",
                            success=outcome in ("agreement", "de_escalated"), outcome=outcome)
        return
    if a.get("household_id") != b.get("household_id") or outcome not in _BAD_OUTCOMES:
        return
    from systems import fights
    topic = conflict.get("topic") or fights.topic_of(conflict.get("issues"))
    for c, other in ((a, b), (b, a)):
        # a fight that ends badly costs standing; whether that makes a rift depends on how things stood before
        rel = c.setdefault("relationships", {}).setdefault(other["id"], {})
        rel["resentment"] = min(100, (rel.get("resentment") or 0) + FIGHT_RESENTMENT.get(outcome, 0))
        if outcome == "physical_resolved":
            rel["hostility"] = min(100, (rel.get("hostility") or 0) + 30)
        if standing(c, other["id"]) >= STANDING_BAD:
            continue
        rift = open_rift(c, world, other["id"], topic, physical=outcome == "physical_resolved")
        if rift:
            rift["history"].append({"tick": world.get("tick", 0), "what": f"fight about {topic}", "outcome": outcome})


def scan(world, entry=None):
    """Hourly: anyone whose standing with someone they live with has sunk below the line gets a rift, fight or not;
    a rift whose standing has recovered on its own (time heals) closes."""
    for c in (world.get("characters") or {}).values():
        if c.get("alive") is False or c.get("is_workplace_npc") or _is_child(c):
            continue
        for other in _housemates(c, world):
            rift = (c.get("rifts") or {}).get(other["id"])
            s = standing(c, other["id"])
            if s < STANDING_BAD and not (rift and rift.get("status") in ("open", "away", "moving_out")):
                open_rift(c, world, other["id"])
            elif rift and rift.get("status") == "open" and s >= STANDING_BAD + 20:
                _close(c, world, other, "things settled down between us on their own")


# =========================================================
# TRYING TO FIND A WAY FORWARD
# =========================================================

def _recall(c, world, other, rift):
    """What led to this, with when -- the fights and the grievances."""
    tick = world.get("tick", 0)
    bits = []
    for f in reversed(world.get("fight_log") or []):
        if c["id"] in f.get("parties", []) and other["id"] in f.get("parties", []):
            days = (tick - f.get("tick", tick)) // DAY
            when = "today" if days == 0 else ("yesterday" if days == 1 else f"{days} days ago")
            bits.append(f"the fight about {f.get('topic')} {when} ({str(f.get('outcome', '')).replace('_', ' ')})")
        if len(bits) >= 3:
            break
    griefs = sorted([g for g in c.get("grievances") or [] if g.get("caused_by") == other["id"]],
                    key=lambda g: -(g.get("severity") or 0))[:2]
    bits += [f"what they did ({str(g.get('event_type')).replace('_', ' ')})" for g in griefs]
    days = (tick - rift["since"]) // DAY
    text = (f"Things have been bad with {other.get('name')} for {days} day{'s' if days != 1 else ''} now"
            + (f": {'; '.join(bits)}." if bits else f", over {rift['topics'][0]}.")
            + " It needs resolving one way or another.")
    _mem(c, world, text, 0.5, people=[other["id"]], tags=("rift", "recalled"))
    return text


def _choose_approach(c, world, other, rift):
    traits = _traits(c)
    tried = rift.get("tried") or []
    order = []
    if traits & _YIELDING:
        order += ["step_down", "agreement"]
    if traits & _TRADERS:
        order += ["trade"]
    if traits & _PROUD:
        order += ["agreement", "third_party", "trade"]
    order += ["agreement", "step_down", "trade", "third_party"]
    if rift.get("physical") or standing(c, other["id"]) < STANDING_VERY_BAD:
        order = ["third_party"] + order               # too raw to face them alone
    for a in order:
        if a not in tried:
            return a
    return random.choice(["agreement", "third_party", "step_down"])


def _mediator(c, world, other):
    chars = world.get("characters") or {}
    best, score = None, -10**9
    for oid in set((c.get("relationships") or {})) | set((other.get("relationships") or {})):
        m = chars.get(oid)
        if not m or oid in (c["id"], other["id"]) or m.get("alive") is False or _is_child(m) or m.get("off_grid"):
            continue
        s = standing(c, oid) + standing(m, other["id"]) + 0.5 * standing(other, oid)
        if s > score:
            best, score = m, s
    return best


def _receptive(other, c_id):
    """How likely the other is to come round: their nature, and how bad it is from their side."""
    traits = _traits(other)
    p = 0.35 + 0.1 * len(traits & _YIELDING) - 0.1 * len(traits & _PROUD)
    p += max(-0.25, min(0.2, standing(other, c_id) / 400.0))
    return max(0.05, min(0.85, p))


def try_once(c, world, other):
    """One attempt at an understanding with `other`."""
    rift = (c.get("rifts") or {}).get(other["id"])
    if not rift or rift.get("status") not in ("open",):
        return None
    _recall(c, world, other, rift)
    approach = _choose_approach(c, world, other, rift)
    rift["tried"].append(approach)
    topic = rift["topics"][-1]
    if approach == "agreement" and not c.get("off_grid") and not other.get("off_grid"):
        from systems.conflict_pipeline import start_conflict
        conflict = start_conflict(c["id"], other["id"], world)
        if conflict:
            conflict["reconciliation"] = True
            conflict["topic"] = topic
            _mem(c, world, f"I asked {other.get('name')} to sit down with me and work out {topic} properly.",
                 people=[other["id"]])
            return "agreement"                     # the outcome comes back through on_conflict_resolved
        approach = "step_down"
    if approach == "agreement":
        approach = "third_party"
    if approach == "third_party":
        m = _mediator(c, world, other)
        if not m:
            approach = "step_down"
        else:
            p = _receptive(other, c["id"]) + max(-0.2, min(0.25, standing(other, m["id"]) / 300.0))
            ok = random.random() < p
            _mem(m, world, f"{c.get('name')} asked me to talk to {other.get('name')} for them about {topic}. "
                           + ("They listened." if ok else "They wouldn't hear it."), 0.45, people=[c["id"], other["id"]])
            _mem(other, world, f"{m.get('name')} came to me on {c.get('name')}'s behalf about {topic}."
                 + (" Maybe they have a point." if ok else " I'm not ready to let it go."), 0.5, people=[c["id"], m["id"]])
            _attempt_result(c, world, other, "third_party", ok, by=m)
            return approach
    if approach == "trade":
        offer = random.choice(["take over the chores for a week", "make it up to them with a favour",
                               "pay for the next dinner out", "give them the space they asked for"])
        ok = random.random() < _receptive(other, c["id"]) + 0.05
        _mem(other, world, f"{c.get('name')} offered to {offer} to put {topic} behind us."
             + (" I took it." if ok else " It's not that simple."), 0.5, people=[c["id"]])
        if ok:
            from brain.intentions import add_intention
            add_intention(c, {"type": "keep_deal", "reason": f"I promised {other.get('name')} to {offer}",
                              "category": "social", "priority": 70, "target_id": other["id"]})
        _attempt_result(c, world, other, "trade", ok, offer=offer)
        return approach
    # step_down
    ok = random.random() < _receptive(other, c["id"]) + 0.1
    _mem(other, world, f"{c.get('name')} came to me, gave in on {topic} and apologised."
         + (" I accepted." if ok else " It's not enough."), 0.5, people=[c["id"]])
    _attempt_result(c, world, other, "step_down", ok)
    return "step_down"


_SAID = {
    "step_down": "I gave in on {topic} and apologised to {name}",
    "agreement": "I sat down with {name} to work out {topic}",
    "trade": "I offered {name} to {offer} to put {topic} behind us",
    "third_party": "I asked {by} to talk to {name} for me about {topic}",
}


def _attempt_result(c, world, other, approach, success, by=None, offer=None, outcome=None):
    rift = (c.get("rifts") or {}).get(other["id"])
    if not rift:
        return
    topic = rift["topics"][-1]
    said = _SAID[approach].format(topic=topic, name=other.get("name"), by=(by or {}).get("name", "someone"),
                                  offer=offer or "make it up")
    rift["history"].append({"tick": world.get("tick", 0), "what": approach, "outcome": "understanding" if success
                            else (outcome or "no understanding")})
    if success:
        _close(c, world, other, said + " -- and we came to an understanding")
        return
    rift["attempts"] += 1
    _mem(c, world, f"{said}, but we got nowhere ({rift['attempts']} of {MAX_ATTEMPTS} tries).", people=[other["id"]])


def _repair(c, other_id):
    rel = c.setdefault("relationships", {}).setdefault(other_id, {})
    for key, cut in (("resentment", 40), ("hostility", 30)):
        rel[key] = max(0, (rel.get(key) or 0) - cut)
    rel["trust"] = min(100, (rel.get("trust") or 0) + 10)
    gap = STANDING_BAD + 25 - standing(c, other_id)
    if gap > 0:                                        # an understanding means the line is crossed back
        rel["resentment"] = max(0, (rel.get("resentment") or 0) - gap)
        if standing(c, other_id) < STANDING_BAD + 25:
            rel["hostility"] = 0


def _close(c, world, other, how):
    for a, b in ((c, other), (other, c)):
        rift = (a.get("rifts") or {}).get(b["id"])
        _repair(a, b["id"])
        if rift:
            rift["status"] = "resolved"
            rift["resolved_tick"] = world.get("tick", 0)
        scheduler.cancel(world, _owner(a), f"try:{b['id']}")
    _mem(c, world, f"{how}.", 0.6, people=[other["id"]], tags=("rift", "reconciled"))
    _mem(other, world, f"{c.get('name')} and I came to an understanding about "
                       f"{((c.get('rifts') or {}).get(other['id']) or {}).get('topics', ['it'])[-1]}.", 0.55,
         people=[c["id"]], tags=("rift", "reconciled"))


# =========================================================
# LEAVING -- FOR A WHILE, OR FOR GOOD
# =========================================================

def _can_leave(c, world):
    from systems.temporary_separation import would_leave_children_alone
    return not (_is_child(c) or c.get("off_grid") or c.get("temporary_residence")
                or would_leave_children_alone(c, world))


def _purpose(c, world, other, rift):
    from systems.temporary_separation import _find_separation_host
    host = _find_separation_host(c, world)
    beyond = (rift.get("physical") or standing(c, other["id"]) < STANDING_VERY_BAD
              or rift.get("returns", 0) >= 1 and rift["attempts"] >= MAX_ATTEMPTS)
    if beyond and host:
        return "moving_out", host
    if host:
        return "time_away", host
    return "change_of_scenery", None


_PURPOSE_WORDS = {
    "time_away": "to get some distance from {name} for a few days and come back to try to make peace",
    "change_of_scenery": "for a change of scenery, away from {name}, and come back to try again",
    "moving_out": "for good -- it's not going to work with {name}",
}


def consider_leaving(c, world, other, rift):
    if not _can_leave(c, world):
        return False
    days = (world.get("tick", 0) - rift["since"]) // DAY
    if random.random() >= LEAVE_CHANCE:
        _mem(c, world, f"I thought about leaving for a while because of how things are with {other.get('name')} "
                       f"({days} days now), but I'm staying for now.", people=[other["id"]])
        return False
    purpose, host = _purpose(c, world, other, rift)
    tick = world.get("tick", 0)
    why = (f"{rift['attempts']} tries at making it right with {other.get('name')} got nowhere"
           if rift["attempts"] >= MAX_ATTEMPTS else f"{days} days of bad blood with {other.get('name')}")
    words = _PURPOSE_WORDS[purpose].format(name=other.get("name"))
    if host:
        h_other, host_household, is_family, _chance = host
        c["temporary_residence"] = {
            "host_type": "family" if is_family else "friend", "host_id": h_other["id"],
            "origin_building_id": (world.get("households") or {}).get(c.get("household_id"), {}).get("home_id")
                                  or c.get("building_id"),
            "started_tick": tick, "purpose": purpose, "away_from": other["id"],
            "kind": "temporary_separation", "why": why,
            "where": f"with {h_other.get('name')} ({'family' if is_family else 'a close friend'})",
            "with_ids": [other["id"]],
        }
        from systems.action_router import _route_move
        _route_move(c, world, {"type": "move", "target": f"building:{host_household.get('home_id')}"})
    else:
        from systems.offgrid import send_offgrid
        away = random.randint(*AWAY_DAYS)
        if not send_offgrid(c, world, "temporary_separation", away * 24 * 60):
            return False
        c.setdefault("off_grid_detail", {}).update({"kind": "temporary_separation", "why": why,
                                                    "where": "away for a while", "purpose": purpose,
                                                    "with_ids": [other["id"]]})
    rift["status"] = "moving_out" if purpose == "moving_out" else "away"
    rift["left_tick"] = tick
    rift["purpose"] = purpose
    rift["returns"] = rift.get("returns", 0)
    scheduler.cancel(world, _owner(c), f"try:{other['id']}")
    _mem(c, world, f"I'm leaving {words}. ({why}.)", 0.75, people=[other["id"]], tags=("rift", "left_home"))
    for m in _housemates(c, world):
        _mem(m, world, f"{c.get('name')} has left" + (" -- for good, by the sound of it." if purpose == "moving_out"
                                                       else " for a while."), 0.6, people=[c["id"]],
             tags=("rift", "left_home"))
    if purpose == "moving_out":
        scheduler.schedule_in(world, _owner(c), f"pickup:{other['id']}", random.randint(*PICKUP_DAYS) * DAY)
    elif host:
        scheduler.schedule_in(world, _owner(c), f"return:{other['id']}", random.randint(*AWAY_DAYS) * DAY)
    else:
        scheduler.schedule_in(world, _owner(c), f"return:{other['id']}", (AWAY_DAYS[1] + 1) * DAY)
    return True


def _come_back(c, world, other, rift):
    """Back after time away: home, and straight away another try at making peace."""
    residence = c.get("temporary_residence") or {}
    if residence:
        c["temporary_residence"] = None
        origin = residence.get("origin_building_id")
        if origin:
            from systems.action_router import _route_move
            _route_move(c, world, {"type": "move", "target": f"building:{origin}"})
    if c.get("off_grid"):                            # still away off-grid: check again tomorrow
        scheduler.schedule_in(world, _owner(c), f"return:{other['id']}", DAY)
        return
    rift["status"] = "open"
    rift["back_tick"] = world.get("tick", 0)
    rift["returns"] = rift.get("returns", 0) + 1
    rift["attempts"] = max(0, MAX_ATTEMPTS - 1)      # one more real try after coming back
    rift["tried"] = []
    _mem(c, world, f"I came back home to try to make peace with {other.get('name')}.", 0.6, people=[other["id"]])
    for m in _housemates(c, world):
        _mem(m, world, f"{c.get('name')} came back home.", 0.5, people=[c["id"]])
    scheduler.schedule_in(world, _owner(c), f"try:{other['id']}", 1800)


def _pickup(c, world, other, rift):
    """Moving out: every few days they come by for some of their things. The last time, they're gone for good."""
    residence = c.get("temporary_residence") or {}
    origin = residence.get("origin_building_id")
    rift["pickups"] = rift.get("pickups", 0) + 1
    last = rift["pickups"] >= PICKUPS
    if origin and not c.get("off_grid"):
        from systems.action_router import _route_move
        _route_move(c, world, {"type": "move", "target": f"building:{origin}"})
    _mem(c, world, "I went back to pick up " + ("the last of my things. That's it -- I've moved out."
                                                 if last else "some of my things."), 0.6, people=[other["id"]],
         tags=("rift", "moving_out"))
    for m in _housemates(c, world):
        _mem(m, world, f"{c.get('name')} came by and took " + ("the last of their things. They've moved out."
                                                                 if last else "some of their things."),
             0.6 if last else 0.5, people=[c["id"]], tags=("rift", "moving_out"))
    if last:
        rift["status"] = "moved_out"
        residence["moved_out"] = True
        residence["purpose"] = "moved_out"
    else:
        scheduler.schedule_in(world, _owner(c), f"pickup:{other['id']}", random.randint(*PICKUP_DAYS) * DAY)


# =========================================================
# TIMEOUT EVENTS
# =========================================================

def on_timer(world, entry):
    if entry["owner"] == "riftscan":
        scan(world)
        return
    chars = world.get("characters") or {}
    c = chars.get(entry["owner"].split(":", 1)[1])
    kind, _, other_id = str(entry.get("key")).partition(":")
    other = chars.get(other_id)
    if not c or not other or c.get("alive") is False:
        return
    rift = (c.get("rifts") or {}).get(other_id)
    if not rift:
        return
    if kind == "try" and rift.get("status") == "open":
        if standing(c, other_id) >= STANDING_BAD + 20:
            _close(c, world, other, "things settled down between us on their own")
            return
        days = (world.get("tick", 0) - rift.get("back_tick", rift["since"])) // DAY    # since coming back, if they've been away
        if rift["attempts"] >= MAX_ATTEMPTS or days >= STAY_DAYS:
            if consider_leaving(c, world, other, rift):
                return
        if c.get("off_grid") or c.get("travel_state") or (c.get("activity") or {}).get("type") == "sleep":
            scheduler.schedule_in(world, _owner(c), f"try:{other_id}", 2 * 3600)   # not now: in a couple of hours
            return
        try_once(c, world, other)
        if rift.get("status") == "open":
            scheduler.schedule_in(world, _owner(c), f"try:{other_id}", DAY)
    elif kind == "return" and rift.get("status") == "away":
        _come_back(c, world, other, rift)
    elif kind == "pickup" and rift.get("status") == "moving_out":
        _pickup(c, world, other, rift)


scheduler.register(OWNER, on_timer)
scheduler.register_recurring("riftscan", on_timer, SCAN_EVERY, offset=1234)


# =========================================================
# WHAT THEY'RE TOLD
# =========================================================

def context_lines(c, world):
    lines = []
    tick = world.get("tick", 0)
    for oid, rift in (c.get("rifts") or {}).items():
        status = rift.get("status")
        if status not in ("open", "away", "moving_out"):
            continue
        name = _name(world, oid)
        days = (tick - rift.get("since", tick)) // DAY
        topic = (rift.get("topics") or ["it"])[-1]
        if status == "open":
            lines.append(f"Things are bad between you and {name} (over {topic}, {days} day{'s' if days != 1 else ''}). "
                         f"You've tried {rift.get('attempts', 0)} time{'s' if rift.get('attempts', 0) != 1 else ''} "
                         f"to make it right. It needs resolving: one of you giving in, an agreement, a deal -- or "
                         f"someone you both trust putting in a word.")
        elif status == "away":
            lines.append(f"You're away from home, {_PURPOSE_WORDS.get(rift.get('purpose'), 'for a while').format(name=name)}.")
        else:
            lines.append(f"You've left home for good because of {name}; you go back now and then for your things.")
    return lines
