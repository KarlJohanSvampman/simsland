"""
systems/guests.py

Being a guest in someone else's home -- and being told to go.

Before this, nothing knew who was a guest: anyone could walk into another family's house and stay there for as long as
they liked, and "please leave" was just words (live, 2026-11-02: Donna Moreau and Carol Lindqvist staying on at the
Okafors', Stephanie and Kathleen Okafor at the Lindqvists', with the people who live there plainly against it).

A character inside a home that isn't their household's is a guest (c["guest_visit"]), with a status:

  welcome         let in at the door (systems/waiting.py marks it), told to come in / make themselves at home, or family
                  or a close friend of someone who lives there -- welcome for a while (WELCOME_TICKS, shorter late
                  in the evening);
  uninvited       walked in without anyone letting them in;
  asked_to_leave  someone who lives there told them to go.

Both sides are told where they stand, in their prompt (context_lines): the people who live there see who is in their
home and how they got in; the guest sees whose home it is and, once asked, that staying means ignoring them.

What makes it happen (all timeout events through core/scheduler.py, owner "guest:<id>" -- nothing polls):

  - a line said in a conversation (brain/conversations.add_message -> on_line): "please leave", "go home", "get out"
    from someone who lives there asks the guest to leave; "come in", "make yourself at home" welcomes an uninvited one;
    the guest saying "I should head home" sets them off home;
  - asked to leave, the guest goes home or doesn't -- personality, age and how firmly they were asked decide
    (_compliance); going means walking home (systems/travel.py's walk home);
  - not gone ESCALATE_TICKS later, it escalates, a step at a time:
      1. the host asks again, firmly; trust and warmth drop, the host holds a grudge;
      2. a last warning; the host tells people about it (reputation, the social_transgression_gossip handler);
      3. an adult is reported to the police, who come and escort them out (a warning on their record);
         a child's parents are called and the child is sent home;
  - limits on a visit: the welcome runs out (the host says it's time to go); a child guest is sent home for dinner
    and at bedtime; when everyone who lives there is asleep or gone, guests leave.
"""

import random
import re

from core import scheduler

OWNER = "guest"

ESCALATE_TICKS = 300            # 5 sim-minutes between "please leave" and the next, firmer step
DEPART_DELAY_TICKS = 30         # the moment between agreeing to go and setting off
CHECK_EVERY_TICKS = 600         # how often a visit checks whether anyone who lives there is still up
LET_IN_VALID_TICKS = 1800       # a door answered this long ago still counts as having been let in
SENT_AWAY_MEMORY_TICKS = 7200   # someone sent away who comes back within this long isn't welcome

WELCOME_TICKS = {"family": 4 * 3600, "close": 3 * 3600, "friend": 2 * 3600, "other": 3600}
CHILD_DINNER_MINUTE = 18 * 60
CHILD_BEDTIME_MINUTE = 20 * 60 + 30
ADULT_LATE_MINUTE = 23 * 60
MORNING_MINUTE = 7 * 60

_FAMILY_LABELS = {"parent", "child", "sibling", "grandparent", "grandchild", "spouse", "partner", "aunt", "uncle",
                  "cousin", "niece", "nephew", "family"}
_CLOSE = {"close_friend", "best_friend"}

_AGREEABLE = {"agreeable", "polite", "considerate", "shy", "obedient", "kind", "respectful", "naive", "timid",
              "people_pleaser", "conscientious", "gentle", "humble"}
_DEFIANT = {"stubborn", "rebellious", "defiant", "hostile", "aggressive", "arrogant", "entitled", "rude",
            "manipulative", "confrontational", "hot_headed", "impulsive", "narcissistic"}

_LEAVE = re.compile(
    r"\b(get out|leave (my|our|this) (house|home|place)|out of (my|our) (house|home)"
    r"|(you|you'll|you will) (need|have|got) to (go|leave|head home|go home)"
    r"|(you should|you better|you'd better|you need to|you have to|time to|time for you to|please|could you|can you"
    r"|would you|i want you to|i'd like you to|i need you to) (please )?(go home|leave|head home|go now|get going|be going)"
    r"|go home|head home|not welcome|aren't welcome|are not welcome|outta here|scram)\b", re.I)
_NOT_LEAVE = re.compile(r"\b(don't|do not|no need to|doesn't have to|don't have to|not have to|never) (\w+ ){0,2}"
                        r"(go|leave|head)\b|\bbefore you (go|leave)\b", re.I)
_WELCOME = re.compile(
    r"\b(come (on )?in|make yourself at home|you('re| are) (always )?welcome( here)?|stay for (dinner|lunch|a while|a bit)"
    r"|you can stay|feel free to stay|glad you came|happy to have you|please stay|stay as long)\b", re.I)
_GUEST_GOING = re.compile(
    r"\b(i('ll| will| should| better|'d better| have to| need to|'m going to| gotta| must) (go|head|get going|be going"
    r"|leave|go home|head home|head out|get home)|i('m| am) (heading|going) (home|out|now)|time for me to (go|leave|head)"
    r"|i('ll| will) leave you (be|alone))\b", re.I)


# =========================================================
# WHO LIVES WHERE
# =========================================================

def _host_household(world, building_id):
    if not building_id:
        return None
    for hh in (world.get("households") or {}).values():
        if hh.get("home_id") == building_id or building_id in (hh.get("building_ids") or []):
            return hh
    return None


def _chars(world):
    return world.get("characters") or {}


def _is_child(c):
    return (c.get("age") or 99) < 18 or c.get("age_group") in ("child", "teen", "toddler", "baby")


def _asleep(c):
    return (c.get("activity") or {}).get("type") == "sleep"


def residents_here(world, visit, awake=True, adults=None):
    """The people who live in the visited home and are in it now."""
    hh = (world.get("households") or {}).get(visit["household_id"]) or {}
    out = []
    for mid in hh.get("members") or []:
        m = _chars(world).get(mid)
        if not m or m.get("off_grid") or m.get("alive") is False:
            continue
        if m.get("_in_building", m.get("building_id")) != visit["building_id"]:
            continue
        if awake and _asleep(m):
            continue
        if adults is not None and _is_child(m) == adults:
            continue
        out.append(m)
    return out


def _speaker(world, visit):
    """Who speaks for the home: whoever asked, if they're here and up; else an adult who lives there; else anyone."""
    asked = _chars(world).get(visit.get("asked_by"))
    if asked and asked in residents_here(world, visit):
        return asked
    adults = residents_here(world, visit, adults=True)
    if adults:
        return adults[0]
    anyone = residents_here(world, visit)
    return anyone[0] if anyone else None


def _relation(c, hh, world):
    best = "other"
    for mid in hh.get("members") or []:
        rel = (c.get("relationships") or {}).get(mid) or {}
        if _FAMILY_LABELS & set(rel.get("labels") or []):
            return "family"
        if rel.get("designation") in _CLOSE:
            best = "close"
        elif best == "other" and (rel.get("designation") == "friend" or "friend" in (rel.get("labels") or [])):
            best = "friend"
    return best


def _minute_of_day(world):
    return (world.get("calendar") or {}).get("minute_of_day")


def _ticks_until_minute(world, minute):
    now = _minute_of_day(world)
    if now is None:
        return None
    return max(0, (minute - now) * 60)


def _owner(c):
    return f"{OWNER}:{c['id']}"


def _family_name(world, hh):
    name = hh.get("name") or ""
    m = re.match(r"the (\w+) household", name, re.I)
    return f"the {m.group(1)}s'" if m else (f"{name}'s" if name else "someone else's")


# =========================================================
# ARRIVING AND LEAVING
# =========================================================

def track(c, world):
    """Start or end c's visit when c has stepped into or out of another household's home. Cheap: compares one id."""
    if c.get("off_grid") or c.get("is_workplace_npc") or c.get("alive") is False:
        return
    bid = c.get("_in_building")
    visit = c.get("guest_visit")
    if visit and visit.get("building_id") == bid:
        return
    if visit:
        _end_visit(c, world, visit)
    hh = _host_household(world, bid)
    if not hh or hh.get("id") == c.get("household_id"):
        return
    residence = c.get("temporary_residence") or {}
    if residence.get("host_id") in (hh.get("members") or []):
        return                                       # staying with them for now -- not a visit
    _start_visit(c, world, bid, hh)


def _start_visit(c, world, bid, hh):
    tick = world.get("tick", 0)
    let_in = c.get("_let_in") or {}
    sent_away = c.get("_sent_away") or {}
    relation = _relation(c, hh, world)
    if sent_away.get("household_id") == hh["id"] and tick - sent_away.get("tick", -10**9) < SENT_AWAY_MEMORY_TICKS:
        status, how = "uninvited", "came back after being sent home"
    elif let_in.get("household_id") == hh["id"] and tick - let_in.get("tick", -10**9) < LET_IN_VALID_TICKS:
        status, how = "welcome", "let in at the door"
    elif relation in ("family", "close"):
        status, how = "welcome", "family" if relation == "family" else "a close friend"
    else:
        status, how = "uninvited", "walked in without being let in"
    visit = c["guest_visit"] = {"building_id": bid, "household_id": hh["id"], "since": tick, "status": status,
                                "how": how, "relation": relation, "stage": 0}
    from core.event_bus import emit
    emit("guest.visit_started", {"guest_id": c["id"], "household_id": hh["id"], "building_id": bid, "status": status,
                                 "host_ids": [m["id"] for m in residents_here(world, visit)]})
    c.pop("_let_in", None)
    if status == "welcome":
        _welcome(c, world, visit, how)
    scheduler.schedule_in(world, _owner(c), "check", CHECK_EVERY_TICKS, every=CHECK_EVERY_TICKS)
    if _is_child(c):
        _arm_curfew(c, world)
    from brain.cognition_scheduler import wake_character
    for m in residents_here(world, visit):
        wake_character(m, world, "house_guest", {"guest_id": c["id"], "status": status, "message":
                       f"{c.get('name', 'Someone')} has come into your home" +
                       (" -- nobody let them in." if status == "uninvited" else ".")})


def _welcome(c, world, visit, how):
    tick = world.get("tick", 0)
    visit.update(status="welcome", how=how)
    length = WELCOME_TICKS.get(visit.get("relation"), WELCOME_TICKS["other"])
    late = _ticks_until_minute(world, ADULT_LATE_MINUTE)
    if late is not None and not _is_child(c):
        now = _minute_of_day(world)
        if now is not None and now < MORNING_MINUTE:
            late = 0
        length = min(length, max(late, 600))
    visit["welcome_until"] = tick + length
    scheduler.schedule(world, _owner(c), "limit", visit["welcome_until"])


def _arm_curfew(c, world):
    now = _minute_of_day(world)
    if now is None:
        return
    if now < MORNING_MINUTE or now >= CHILD_BEDTIME_MINUTE:
        due, why = 60, "bedtime"
    elif now < CHILD_DINNER_MINUTE:
        due, why = (CHILD_DINNER_MINUTE - now) * 60, "dinner"
    else:
        due, why = (CHILD_BEDTIME_MINUTE - now) * 60, "bedtime"
    scheduler.schedule_in(world, _owner(c), "curfew", max(1, due), {"why": why})


def _end_visit(c, world, visit):
    c.pop("guest_visit", None)
    scheduler.cancel_owner(world, _owner(c))
    if visit.get("status") == "asked_to_leave":
        host = _chars(world).get(visit.get("asked_by"))
        if host:
            from brain.memory import store_memory
            store_memory(host, f"{c.get('name', 'They')} left our home after I asked them to go.", 0.3,
                         ["guest", "asked_to_leave"], "memory", world.get("tick", 0), people=[c["id"]])


def depart(c, world, line=None, memory=None, escorted=False):
    """Send a guest home now: what they were doing ends, they say a last line, and they walk home."""
    from systems.occupancy import interrupt_activity
    from systems.incidental_speech import fire_incidental
    from brain.memory import store_memory
    visit = c.get("guest_visit") or {}
    tick = world.get("tick", 0)
    if c.get("travel_state") or c.get("off_grid"):
        return
    try:
        from brain.conversations import find_active_conversation_for
        from systems.conversation_outcome import end as end_conversation
        conv = find_active_conversation_for(world, c["id"])
        if conv:
            end_conversation(world, conv, "left")
    except Exception:                                # noqa: BLE001
        pass
    interrupt_activity(c, world, reason="went home" if not escorted else "escorted out")
    if line:
        fire_incidental(c, "announce", line, world)
    if memory:
        store_memory(c, memory, 0.5 if escorted else 0.3, ["guest", "went_home"], "memory", tick)
    if visit.get("status") == "asked_to_leave":
        c["_sent_away"] = {"household_id": visit.get("household_id"), "tick": tick}
    from systems.travel import _begin_walking_home
    from systems.vehicles import household_home_entrance
    _begin_walking_home(c, world)
    if c.get("travel_state") != "walking_home":
        entrance = household_home_entrance(world, c.get("household_id"))
        if entrance:                                 # no way to walk there: just be home
            c["x"], c["y"] = entrance[0], entrance[1]
            c["route"], c["is_moving"] = [], False
    scheduler.cancel(world, _owner(c), "escalate")
    scheduler.cancel(world, _owner(c), "limit")
    scheduler.cancel(world, _owner(c), "curfew")
    scheduler.schedule_in(world, _owner(c), "gone", 1)


# =========================================================
# BEING ASKED TO LEAVE
# =========================================================

def _compliance(guest, host, stage, soft):
    traits = set((guest.get("traits") or []) + (guest.get("personality_traits") or []))
    p = 0.7
    if _is_child(guest) and host is not None and not _is_child(host):
        p = 0.9
    if soft:
        p += 0.1
    p += 0.15 * stage
    p += 0.06 * len(traits & _AGREEABLE) - 0.12 * len(traits & _DEFIANT)
    rel = (guest.get("relationships") or {}).get((host or {}).get("id")) or {}
    p -= (rel.get("resentment") or 0) / 100.0 * 0.3
    return max(0.05, min(0.98, p))


def ask_to_leave(guest, host, world, said=None, soft=False):
    """Someone who lives there asked the guest to go."""
    from brain.memory import store_memory
    from brain.cognition_scheduler import wake_character
    visit = guest.get("guest_visit")
    if not visit:
        return
    tick = world.get("tick", 0)
    first = visit.get("status") != "asked_to_leave"
    visit["status"] = "asked_to_leave"
    if host is not None:
        visit["asked_by"] = host["id"]
    if first:
        visit["asked_tick"] = tick
        visit["stage"] = 0
        scheduler.cancel(world, _owner(guest), "limit")
    host_name = (host or {}).get("name", "Someone who lives here")
    store_memory(guest, f"{host_name} asked me to leave their home" + (f': "{said}"' if said else "."), 0.5,
                 ["guest", "asked_to_leave"], "memory", tick, people=[host["id"]] if host else None)
    if random.random() < _compliance(guest, host, visit.get("stage", 0), soft):
        visit["complying"] = True
        scheduler.schedule_in(world, _owner(guest), "depart", DEPART_DELAY_TICKS)
    else:
        visit["complying"] = False
        wake_character(guest, world, "asked_to_leave", {"host_id": (host or {}).get("id"), "message":
                       f"{host_name} wants you to leave their home."})
        scheduler.schedule_in(world, _owner(guest), "escalate", ESCALATE_TICKS)


def on_line(world, conv, speaker_id, utterance):
    """A line said in a conversation (brain/conversations.add_message): does it ask a guest to go, or welcome one?"""
    if not utterance:
        return
    chars = _chars(world)
    speaker = chars.get(speaker_id)
    if not speaker:
        return
    text = str(utterance)
    # the guest saying they'll head home
    visit = speaker.get("guest_visit")
    if visit and _GUEST_GOING.search(text) and not _NOT_LEAVE.search(text):
        scheduler.schedule_in(world, _owner(speaker), "depart", DEPART_DELAY_TICKS)
        visit["complying"] = True
        return
    for pid in conv.get("participants") or []:
        guest = chars.get(pid)
        gv = (guest or {}).get("guest_visit")
        if not gv or pid == speaker_id or gv.get("household_id") != speaker.get("household_id"):
            continue
        if _LEAVE.search(text) and not _NOT_LEAVE.search(text):
            ask_to_leave(guest, speaker, world, said=text)
        elif _WELCOME.search(text) and gv.get("status") == "uninvited":
            _welcome(guest, world, gv, f"welcomed in by {speaker.get('name', 'someone')}")


# =========================================================
# TIMEOUT EVENTS
# =========================================================

def _say(host, guest, world, text):
    from systems.incidental_speech import fire_incidental
    from brain.memory import store_memory
    fire_incidental(host, "inform", text, world, target_id=guest["id"])
    store_memory(guest, f'{host.get("name", "They")} said to me: "{text}"', 0.45, ["guest", "heard"], "memory",
                 world.get("tick", 0), people=[host["id"]])


def _first_name(c):
    return (c.get("first_name") or (c.get("name") or "you").split(" ")[0])


def on_timer(world, entry):
    cid = entry["owner"].split(":", 1)[1]
    c = _chars(world).get(cid)
    if c is None:
        return
    key = entry["key"]
    visit = c.get("guest_visit")
    if key == "gone" or not visit:
        if not visit:
            scheduler.cancel_owner(world, _owner(c))
        return
    if c.get("_in_building") != visit.get("building_id") or c.get("travel_state"):
        return
    hh = (world.get("households") or {}).get(visit["household_id"]) or {}
    home = _family_name(world, hh)
    if key == "depart":
        depart(c, world, line="Alright, I'll head home.", memory=f"I left {home} home and went home.")
    elif key == "limit":
        _on_limit(c, world, visit, home)
    elif key == "curfew":
        _on_curfew(c, world, visit, home, (entry.get("payload") or {}).get("why", "dinner"))
    elif key == "check":
        _on_check(c, world, visit, home)
    elif key == "escalate":
        _escalate(c, world, visit, home)
    elif key == "police":
        _police_arrive(c, world, visit, home, entry.get("payload") or {})


def _on_limit(c, world, visit, home):
    if visit.get("status") != "welcome":
        return
    host = _speaker(world, visit)
    if host is None:
        depart(c, world, memory=f"There was nobody up at {home} any more, so I went home.")
        return
    now = _minute_of_day(world)
    late = now is not None and (now >= 22 * 60 or now < MORNING_MINUTE)
    text = (f"It's getting late, {_first_name(c)} -- time to head home." if late else
            f"It was nice having you, {_first_name(c)}, but we've got things to do now -- maybe another time?")
    _say(host, c, world, text)
    ask_to_leave(c, host, world, said=text, soft=True)


def _on_curfew(c, world, visit, home, why):
    host = _speaker(world, visit)
    text = (f"It's dinner time, {_first_name(c)} -- you should head home, your family will be waiting." if why == "dinner"
            else f"It's bedtime, {_first_name(c)} -- off home with you.")
    if host is None or _is_child(host):
        depart(c, world, line="I have to go home now.",
               memory=f"It was {why} time, so I went home from {home} home.")
        return
    _say(host, c, world, text)
    ask_to_leave(c, host, world, said=text, soft=True)
    if why == "dinner" and c.get("guest_visit"):
        scheduler.schedule_in(world, _owner(c), "curfew", (CHILD_BEDTIME_MINUTE - CHILD_DINNER_MINUTE) * 60,
                              {"why": "bedtime"})


def _on_check(c, world, visit, home):
    if residents_here(world, visit, awake=True):
        return
    if visit.get("status") == "uninvited" and not residents_here(world, visit, awake=False):
        return                                       # alone in an empty house -- nobody to notice
    depart(c, world, memory=f"Everyone at {home} had gone to bed or left, so I went home.")


def _escalate(c, world, visit, home):
    from brain.memory import store_memory
    from brain.cognition_scheduler import wake_character
    from systems.grievances import add_grievance
    if visit.get("status") != "asked_to_leave":
        return
    tick = world.get("tick", 0)
    visit["stage"] = stage = visit.get("stage", 0) + 1
    host = _speaker(world, visit)
    name, first = c.get("name", "They"), _first_name(c)
    minutes = max(1, (tick - visit.get("asked_tick", tick)) // 60)

    if host is None:                                 # nobody up who lives there: they'll deal with it when they are
        scheduler.schedule_in(world, _owner(c), "escalate", ESCALATE_TICKS)
        visit["stage"] = stage - 1
        return

    if stage == 1:
        text = f"{first}, I asked you to leave. Please go now."
        _say(host, c, world, text)
        for m in residents_here(world, visit, awake=True):
            rel = m.setdefault("relationships", {}).setdefault(c["id"], {})
            rel["trust"] = max(0, rel.get("trust", 50) - 10)
            rel["warmth"] = max(0, rel.get("warmth", 50) - 10)
            rel["resentment"] = min(100, rel.get("resentment", 0) + 15)
        add_grievance(host, c["id"], "refused_to_leave", world, severity=8.0,
                      details={"context": "stayed in our home after being asked to leave"})
        store_memory(host, f"{name} is still in our home {minutes} minutes after I asked them to leave.", 0.55,
                     ["guest", "refused_to_leave"], "memory", tick, people=[c["id"]])
        wake_character(host, world, "house_guest", {"guest_id": c["id"], "status": "refusing", "message":
                       f"{name} still hasn't left your home."})
    elif stage == 2:
        threat = "I'm calling your parents" if _is_child(c) else "I'm calling the police"
        text = f"This is the last time, {first}: leave now, or {threat}."
        _say(host, c, world, text)
        from systems.reputation import apply_reputation_event
        apply_reputation_event(c, "refused_to_leave", world, magnitude_override=-0.05)
        try:
            from core.event_bus import emit
            emit("social_transgression_gossip", {"gossiper_id": host["id"], "accused_id": c["id"],
                                                 "transgression": "refused_to_leave_home", "tick": tick,
                                                 "severity": 0.4})
        except Exception:                            # noqa: BLE001
            pass
        for oid, rel in (host.get("relationships") or {}).items():
            listener = _chars(world).get(oid)
            if listener and oid != c["id"] and (rel.get("trust") or 0) >= 50:
                store_memory(listener, f"{host.get('name')} told me {name} wouldn't leave their home even when "
                                       f"asked to.", 0.35, ["gossip", "guest"], "memory", tick, people=[c["id"]])
    else:
        _final_step(c, world, visit, home, host)
        return

    if random.random() < _compliance(c, host, stage, soft=False):
        visit["complying"] = True
        scheduler.schedule_in(world, _owner(c), "depart", DEPART_DELAY_TICKS)
    else:
        wake_character(c, world, "asked_to_leave", {"host_id": host["id"], "message":
                       f"{host.get('name')} is telling you again to leave their home."})
        scheduler.schedule_in(world, _owner(c), "escalate", ESCALATE_TICKS)


def _final_step(c, world, visit, home, host):
    from brain.memory import store_memory
    from brain.cognition_scheduler import wake_character
    tick = world.get("tick", 0)
    name = c.get("name", "They")
    if _is_child(c):
        hh = (world.get("households") or {}).get(c.get("household_id")) or {}
        parents = [p for p in (_chars(world).get(m) for m in hh.get("members") or [])
                   if p and not _is_child(p) and p.get("alive") is not False]
        for p in parents:
            store_memory(p, f"{host.get('name')} called: {name} was at their house and wouldn't leave, so they sent "
                            f"{_first_name(c)} home.", 0.6, ["guest", "phone_call"], "memory", tick,
                         people=[c["id"], host["id"]])
            wake_character(p, world, "house_guest", {"guest_id": c["id"], "status": "child_sent_home", "message":
                           f"{host.get('name')} called about {name}: they wouldn't leave their house and are being "
                           f"sent home."})
        store_memory(host, f"I called {name}'s parents because they wouldn't leave.", 0.5, ["guest"], "memory", tick)
        depart(c, world, line="Okay, okay, I'm going.",
               memory=f"I wouldn't leave {home} home, so they called my parents and sent me home.")
        return
    if _is_child(host):
        adults = [m for m in (_chars(world).get(x) for x in
                              ((world.get("households") or {}).get(visit["household_id"]) or {}).get("members") or [])
                  if m and not _is_child(m)]
        for a in adults:
            store_memory(a, f"{host.get('name')} called me: {name} is in our home and won't leave.", 0.6,
                         ["guest", "phone_call"], "memory", tick, people=[c["id"]])
            wake_character(a, world, "house_guest", {"guest_id": c["id"], "status": "refusing", "message":
                           f"{host.get('name')} called: {name} is in your home and won't leave."})
        visit["stage"] = 2
        scheduler.schedule_in(world, _owner(c), "escalate", ESCALATE_TICKS)
        return
    import uuid
    from systems.emergency import create_911_call
    inc = {"id": f"inc_{uuid.uuid4().hex[:6]}", "type": "trespass", "offender_id": c["id"],
           "participants": [c["id"], host["id"]], "victim_id": host["id"], "building_id": visit["building_id"],
           "location": {"x": c.get("x", 0), "y": c.get("y", 0)}, "reported": True, "tick": tick}
    world.setdefault("incidents", []).append(inc)
    create_911_call(world, host, "police", f"{name} is in my home and won't leave.", incident_id=inc["id"])
    store_memory(c, f"{host.get('name')} called the police on me for not leaving their home.", 0.6,
                 ["guest", "police"], "memory", tick, people=[host["id"]])
    wake_character(c, world, "asked_to_leave", {"host_id": host["id"], "police": True, "message":
                   f"{host.get('name')} has called the police because you won't leave their home."})
    scheduler.schedule_in(world, _owner(c), "police", 120, {"incident_id": inc["id"], "host_id": host["id"]})


def _police_arrive(c, world, visit, home, payload):
    from brain.memory import store_memory
    tick = world.get("tick", 0)
    host = _chars(world).get(payload.get("host_id"))
    c.setdefault("legal", {}).setdefault("warnings", []).append(
        {"for": "trespass", "tick": tick, "incident_id": payload.get("incident_id")})
    if host:
        store_memory(host, f"The police came and escorted {c.get('name')} out of our home.", 0.6, ["guest", "police"],
                     "memory", tick, people=[c["id"]])
    depart(c, world, escorted=True, line="Fine. I'm going.",
           memory=f"The police came and escorted me out of {home} home. I got a warning for trespassing.")


scheduler.register(OWNER, on_timer)


# =========================================================
# WHAT EACH SIDE IS TOLD
# =========================================================

def _ago(world, since):
    minutes = max(0, (world.get("tick", 0) - (since or 0)) // 60)
    if minutes < 1:
        return "just now"
    if minutes < 90:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    return f"{minutes // 60} hours ago"


def context_lines(c, world):
    """Prompt lines about guests: for a guest, whose home this is and where they stand; for someone at home, who is
    in it and how they got in."""
    lines = []
    chars = _chars(world)
    visit = c.get("guest_visit")
    if visit:
        hh = (world.get("households") or {}).get(visit["household_id"]) or {}
        home = _family_name(world, hh)
        status = visit.get("status")
        if status == "welcome":
            lines.append(f"You're a guest in {home} home ({visit.get('how')}, {_ago(world, visit.get('since'))}).")
        elif status == "uninvited":
            lines.append(f"You're in {home} home -- you {visit.get('how')}. It isn't your home; the people who live "
                         f"here may not want you in it.")
        else:
            asker = chars.get(visit.get("asked_by")) or {}
            lines.append(f"{asker.get('name', 'Someone who lives here')} asked you to leave {home} home "
                         f"{_ago(world, visit.get('asked_tick'))}. It's their home, not yours: staying means ignoring "
                         f"them. The decent thing is to go home now (ACTION: move | home).")
            if visit.get("stage", 0) >= 2:
                lines.append("They've warned you this is the last time.")
    bid = c.get("_in_building")
    if bid and _host_household(world, bid) and _host_household(world, bid).get("id") == c.get("household_id"):
        for other in chars.values():
            gv = other.get("guest_visit")
            if not gv or gv.get("building_id") != bid or other["id"] == c["id"] or other.get("off_grid"):
                continue
            name = other.get("name", "Someone")
            status = gv.get("status")
            if status == "welcome":
                lines.append(f"{name} is visiting your home ({gv.get('how')}, {_ago(world, gv.get('since'))}).")
            elif status == "uninvited":
                lines.append(f"{name} is in your home -- they {gv.get('how')}. It's your home: you can welcome them "
                             f"(\"come in\") or tell them to leave.")
            else:
                asker = "You" if gv.get("asked_by") == c["id"] else (chars.get(gv.get("asked_by")) or {}).get("name",
                                                                                                          "Someone")
                lines.append(f"{asker} asked {name} to leave {_ago(world, gv.get('asked_tick'))}, and they're still in "
                             f"your home.")
    return lines
