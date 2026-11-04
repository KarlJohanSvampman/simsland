"""
systems/rifts.py

Falling out with someone you live with -- and what you do about it.

A fight used to have a flat chance of sending either party off to stay with friends or family straight away
(core/event_handlers.py, systems/temporary_separation.py). Leaving should come last, not first, and it should be for
something. Now a fight that ends badly between two people in the same household -- or simply standing with them
having sunk below STANDING_BAD -- opens a rift (c["rifts"][other id]), about something: the fight's topic, or the
grievance between them.

While a rift is open, once a day (timeout event "rift:<id>", key "try:<other id>"), the character recalls what led
to it -- the fights and grievances, with when -- and is woken wanting to find a way forward (c["wants_to_repair"],
shown in their prompt by social/context.py). The ways forward are theirs to choose and to say:

  step_down    give in on it and apologise;
  agreement    sit down and work out terms -- an agreement becomes a social contract (social/contracts.py);
  trade        offer something for it (taking over a chore, a favour);
  third_party  ask someone both of them trust to put in a word (that someone joins as a mediator).

Whatever they say to the other person while a rift is open is a reconciliation confrontation (social/confrontations.py)
and the AI reading the conversation says how it went. An understanding closes the rift; anything else is one try
down. Standing here is social/standing.py's (-100..100).

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

STANDING_BAD = -30              # below this, things are bad between them
STANDING_VERY_BAD = -70         # beyond repair, as far as they can tell
MAX_ATTEMPTS = 3
STAY_DAYS = 7
DAY = 86400
FIRST_TRY_TICKS = 4 * 3600      # a few hours to cool off before the first try
NOTICE_DAYS = (2, 3)            # leaving is announced this many days ahead
POSTPONE_GAP = 20 * 3600        # an attempt to mend things holds it off a day, at most once a day
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
    """How c regards other (social/standing.py)."""
    from social.standing import score
    return score(c, other_id)


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
    """A confrontation between two people who live together that ended badly opens a rift for both (instead of a
    chance of moving out on the spot); one that was a try at making peace counts as a try (or closes the rift)."""
    chars = world.get("characters") or {}
    parties = [chars[p] for p in data.get("parties", []) if p in chars]
    if len(parties) != 2:
        return
    a, b = parties
    from social.confrontations import lookup
    conflict = lookup(world, data.get("conflict_id")) or {}
    outcome = data.get("outcome")
    reconciling = conflict.get("reconciliation")
    if reconciling:
        c = chars.get(conflict.get("initiator"))
        other = b if c is a else a
        success = outcome in ("agreement", "de_escalated")
        if c is not None and not ((c.get("rifts") or {}).get(other["id"]) or {}).get("status") == "open" \
                and ((other.get("rifts") or {}).get(c["id"]) or {}).get("status") == "open":
            # the one who had the rift (and maybe a notice) is the other: the attempt came to them
            if success:
                _close(other, world, c, f"{c.get('name')} came to me and we worked it out")
            return
        if c is not None:
            how = (conflict.get("resolution") or {}).get("outcome")
            _attempt_result(c, world, other, _approach_of(conflict), success=outcome in ("agreement", "de_escalated"),
                            outcome=how or outcome, by=_mediator_in(world, conflict))
        return
    if a.get("household_id") != b.get("household_id") or outcome not in _BAD_OUTCOMES:
        return
    from systems import fights
    topic = conflict.get("topic") or fights.topic_of(conflict.get("issues"))
    for c, other in ((a, b), (b, a)):
        # what the confrontation cost them was applied by social/confrontations.py; a rift is whether it's bad now
        if standing(c, other["id"]) >= STANDING_BAD and outcome != "physical_resolved":
            continue
        rift = open_rift(c, world, other["id"], topic, physical=outcome == "physical_resolved")
        if rift:
            rift["history"].append({"tick": world.get("tick", 0), "what": f"fight about {topic}", "outcome": outcome})


def _approach_of(conflict):
    t = conflict.get("confrontation_type")
    hist = " ".join(str(h.get("why", "")) for h in conflict.get("escalation_history") or []).lower()
    if any(p.get("role") == "mediator" for p in (conflict.get("participants") or {}).values()):
        return "third_party"
    if "sorry" in hist or "apolog" in hist:
        return "step_down"
    if t == "contract_proposal" or "if you" in hist or "i'll " in hist:
        return "trade" if "i'll " in hist else "agreement"
    return "agreement"


def _mediator_in(world, conflict):
    for pid, p in (conflict.get("participants") or {}).items():
        if p.get("role") == "mediator":
            return (world.get("characters") or {}).get(pid)
    return None


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


def try_once(c, world, other):
    """Another day of it: recall what led here and be woken wanting to find a way forward. What they do about it
    -- and how the other takes it -- is theirs (their AI turns, and the AI's reading of the conversation)."""
    rift = (c.get("rifts") or {}).get(other["id"])
    if not rift or rift.get("status") not in ("open",):
        return None
    recalled = _recall(c, world, other, rift)
    topic = rift["topics"][-1]
    m = _mediator(c, world, other)
    c.setdefault("wants_to_repair", {})[other["id"]] = {
        "since": world.get("tick", 0), "topic": topic, "recalled": recalled,
        "tried": list(rift.get("tried") or []), "go_between": (m or {}).get("id"),
        "ways": ["step_down", "agreement", "trade", "third_party"],
    }
    from brain.cognition_scheduler import wake_character
    wake_character(c, world, "wants_to_repair", {"target_id": other["id"], "target_name": other.get("name"),
                                                 "topic": topic})
    return "woken"


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
    rift["tried"].append(approach)
    (c.get("wants_to_repair") or {}).pop(other["id"], None)
    rift["history"].append({"tick": world.get("tick", 0), "what": approach, "outcome": "understanding" if success
                            else (outcome or "no understanding")})
    if success:
        _close(c, world, other, said + " -- and we came to an understanding")
        return
    rift["attempts"] += 1
    _mem(c, world, f"{said}, but we got nowhere ({rift['attempts']} of {MAX_ATTEMPTS} tries).", people=[other["id"]])


def _repair(c, world, other_id):
    """An understanding: the line is crossed back."""
    from social import standing as S, frustration
    gap = STANDING_BAD + 25 - standing(c, other_id)
    S.change(c, other_id, world, "reconciliation", delta=max(8, gap) if gap > 0 else None,
             cause="we came to an understanding")
    frustration.calm(c, other_id, world, 30, kind="acknowledged")


def _close(c, world, other, how):
    from social.issues import resolve_between
    resolve_between(world, c["id"], other["id"], how)
    for a, b in ((c, other), (other, c)):
        rift = (a.get("rifts") or {}).get(b["id"])
        _repair(a, world, b["id"])
        (a.get("wants_to_repair") or {}).pop(b["id"], None)
        if rift and rift.get("notice"):
            rift.pop("notice", None)
            scheduler.cancel(world, _owner(a), f"leave:{b['id']}")
        if rift:
            rift.pop("may_leave", None)
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
    """It has come to this (MAX_ATTEMPTS tries, or STAY_DAYS days): leaving is now theirs to decide. Nothing is
    rolled -- they're woken with it on their mind, and announce_leaving / staying is their choice."""
    if not _can_leave(c, world) or rift.get("notice"):
        return False
    if not rift.get("may_leave"):
        rift["may_leave"] = world.get("tick", 0)
        days = (world.get("tick", 0) - rift["since"]) // DAY
        _mem(c, world, f"I've started to think about leaving for a while because of how things are with "
                       f"{other.get('name')} ({days} days now).", people=[other["id"]])
    from brain.cognition_scheduler import wake_character
    wake_character(c, world, "considering_leaving", {"target_id": other["id"], "target_name": other.get("name")})
    return False


def _rift_by_name(c, world, about):
    rifts = {oid: r for oid, r in (c.get("rifts") or {}).items() if r.get("status") == "open"}
    if about in rifts:
        return about, rifts[about]
    from social.core import id_by_name
    oid = id_by_name(world, about, among=list(rifts)) if about else None
    if oid:
        return oid, rifts[oid]
    if len(rifts) == 1:
        return next(iter(rifts.items()))
    return None, None


def announce(world, data):
    """They've decided: they're leaving in 2-3 days (systems/action_router.py "announce_leaving")."""
    chars = world.get("characters") or {}
    c = chars.get(data.get("character_id"))
    if not c:
        return
    oid, rift = _rift_by_name(c, world, data.get("about"))
    other = chars.get(oid)
    if not rift or not other or rift.get("notice") or not _can_leave(c, world):
        return
    try:
        days = int(data.get("days") or NOTICE_DAYS[0])
    except (TypeError, ValueError):
        days = NOTICE_DAYS[0]
    days = max(NOTICE_DAYS[0], min(NOTICE_DAYS[1], days))
    purpose = data.get("purpose") if data.get("purpose") in ("time_away", "moving_out") else None
    tick = world.get("tick", 0)
    rift["notice"] = {"announced": tick, "leave_tick": tick + days * DAY, "days": days, "purpose": purpose,
                      "why": str(data.get("reason") or "")[:200], "postponed": 0, "last_postponed": None,
                      "attempts_seen": []}
    scheduler.schedule(world, _owner(c), f"leave:{oid}", tick + days * DAY)
    what = "for good" if purpose == "moving_out" else "for a while"
    _mem(c, world, f"I told them I'm leaving {what} in {days} days because of how things are with "
                   f"{other.get('name')}" + (f": {rift['notice']['why']}" if rift['notice']['why'] else "") + ".",
         0.7, people=[oid], tags=("rift", "notice"))
    for m in _housemates(c, world):
        if m["id"] == oid:
            _mem(m, world, f"{c.get('name')} says they're leaving {what} in {days} days because of me -- "
                           f"unless things change between us.", 0.75, people=[c["id"]], tags=("rift", "notice"))
            from brain.cognition_scheduler import wake_character
            wake_character(m, world, "housemate_leaving", {"target_id": c["id"], "target_name": c.get("name")})
        else:
            _mem(m, world, f"{c.get('name')} says they're leaving {what} in {days} days, because of "
                           f"{other.get('name')}.", 0.6, people=[c["id"], oid], tags=("rift", "notice"))


def call_off(world, data):
    """They've changed their mind and are staying."""
    chars = world.get("characters") or {}
    c = chars.get(data.get("character_id"))
    if not c:
        return
    oid, rift = _rift_by_name(c, world, data.get("about"))
    if not rift or not rift.get("notice"):
        return
    _cancel_notice(c, world, oid, rift, f"I've decided to stay after all" +
                   (f": {data['reason']}" if data.get("reason") else "."))


def _cancel_notice(c, world, oid, rift, line):
    rift.pop("notice", None)
    scheduler.cancel(world, _owner(c), f"leave:{oid}")
    _mem(c, world, line, 0.6, people=[oid], tags=("rift", "notice"))
    for m in _housemates(c, world):
        _mem(m, world, f"{c.get('name')} isn't leaving after all.", 0.55, people=[c["id"]], tags=("rift", "notice"))


def note_attempt(world, attempter_id, noticer_id):
    """attempter is trying to mend things with someone who has said they're leaving because of them: that's worth
    holding off a day for (at most once a day). If they stop trying, the notice runs out and they go."""
    chars = world.get("characters") or {}
    c, other = chars.get(noticer_id), chars.get(attempter_id)
    rift = ((c or {}).get("rifts") or {}).get(attempter_id) if c else None
    n = (rift or {}).get("notice")
    if not n or not other:
        return False
    tick = world.get("tick", 0)
    n["attempts_seen"].append(tick)
    del n["attempts_seen"][:-10]
    if n.get("last_postponed") is not None and tick - n["last_postponed"] < POSTPONE_GAP:
        return False
    # at least a day left from now: one more day to see whether they mean it
    n["leave_tick"] = max(n["leave_tick"], tick) + DAY if n["leave_tick"] - tick < DAY else n["leave_tick"] + DAY
    n["postponed"] += 1
    n["last_postponed"] = tick
    scheduler.cancel(world, _owner(c), f"leave:{attempter_id}")
    scheduler.schedule(world, _owner(c), f"leave:{attempter_id}", n["leave_tick"])
    _mem(c, world, f"{other.get('name')} is trying to make things right. I'll hold off leaving another day "
                   f"and see whether they mean it.", 0.6, people=[attempter_id], tags=("rift", "notice"))
    return True


def _leave_now(c, world, other, rift):
    """The notice has run out with no one meeting them halfway: they go."""
    n = rift.pop("notice", None) or {}
    if not _can_leave(c, world):
        scheduler.schedule_in(world, _owner(c), f"leave:{other['id']}", 6 * 3600)
        rift["notice"] = n
        return False
    purpose, host = _purpose(c, world, other, rift)
    if n.get("purpose") == "moving_out" and host:
        purpose = "moving_out"
    elif n.get("purpose") == "time_away" and purpose == "moving_out":
        purpose = "time_away"
    tick = world.get("tick", 0)
    days = (tick - rift["since"]) // DAY
    why = n.get("why") or (f"{rift['attempts']} tries at making it right with {other.get('name')} got nowhere"
                           if rift["attempts"] >= MAX_ATTEMPTS else f"{days} days of bad blood with {other.get('name')}")
    if n.get("postponed"):
        why += f" (held off {n['postponed']} day{'s' if n['postponed'] != 1 else ''} while they tried, then they stopped)"
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
    rift.pop("may_leave", None)
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
            consider_leaving(c, world, other, rift)
        if c.get("off_grid") or c.get("travel_state") or (c.get("activity") or {}).get("type") == "sleep":
            scheduler.schedule_in(world, _owner(c), f"try:{other_id}", 2 * 3600)   # not now: in a couple of hours
            return
        try_once(c, world, other)
        if rift.get("status") == "open":
            scheduler.schedule_in(world, _owner(c), f"try:{other_id}", DAY)
    elif kind == "leave" and rift.get("status") == "open" and rift.get("notice"):
        if world.get("tick", 0) >= rift["notice"]["leave_tick"]:
            _leave_now(c, world, other, rift)
    elif kind == "return" and rift.get("status") == "away":
        _come_back(c, world, other, rift)
    elif kind == "pickup" and rift.get("status") == "moving_out":
        _pickup(c, world, other, rift)


scheduler.register(OWNER, on_timer)

from core.event_bus import subscribe as _subscribe   # noqa: E402
_subscribe("leaving_announced", lambda data, world: announce(world, data))
_subscribe("leaving_called_off", lambda data, world: call_off(world, data))
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
            want = (c.get("wants_to_repair") or {}).get(oid) or {}
            go = _name(world, want["go_between"]) if want.get("go_between") else None
            tried = ", ".join(t.replace("_", " ") for t in rift.get("tried") or []) or "nothing yet"
            n = rift.get("notice")
            if n:
                left = max(0, n["leave_tick"] - tick)
                when = f"in {round(left / DAY, 1)} days" if left >= DAY else f"in {max(1, round(left / 3600))} hours"
                lines.append(f"You've told the household you're leaving {'for good' if n.get('purpose') == 'moving_out' else 'for a while'} "
                             f"{when}, because of {name}. Each day {name.split(' ')[0]} genuinely tries to meet you halfway, "
                             f"you hold off another day"
                             + (f" (you've held off {n['postponed']} so far)" if n.get("postponed") else "")
                             + ". You can also call it off and stay.")
                continue
            if rift.get("may_leave"):
                lines.append(f"It has come to the point where you're thinking about leaving home for a while -- or for "
                             f"good -- because of {name}. If you decide to, you'd tell the others 2 or 3 days ahead "
                             f"(announce_leaving). Or you stay and keep trying. It's your call.")
            lines.append(f"Things are bad between you and {name} (over {topic}, {days} day{'s' if days != 1 else ''}). "
                         f"You've tried {rift.get('attempts', 0)} time{'s' if rift.get('attempts', 0) != 1 else ''} "
                         f"to make it right ({tried}). Ways forward: give in and apologise, sit down and agree "
                         f"how it'll be from now on, offer something in return"
                         + (f", or ask {go} -- someone you both trust -- to put in a word" if go else "")
                         + ". Or leave it for now; it's up to you.")
        elif status == "away":
            lines.append(f"You're away from home, {_PURPOSE_WORDS.get(rift.get('purpose'), 'for a while').format(name=name)}.")
        else:
            lines.append(f"You've left home for good because of {name}; you go back now and then for your things.")
    # someone else in the house has said they're leaving: because of you, or not
    for m in _housemates(c, world):
        for oid, rift in (m.get("rifts") or {}).items():
            n = rift.get("notice")
            if not n or rift.get("status") != "open":
                continue
            left = max(0, n["leave_tick"] - tick)
            when = f"in about {round(left / DAY, 1)} days" if left >= DAY else "within hours"
            if oid == c["id"]:
                lines.append(f"{m.get('name')} has said they're leaving {when} because of how things are with you. "
                             f"Each day you genuinely try to make it right -- meet them halfway -- they hold off a day; "
                             f"stop trying and they go.")
            else:
                lines.append(f"{m.get('name')} has said they're leaving {when}, because of {_name(world, oid)}.")
    return lines
