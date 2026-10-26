"""
systems/exhaustion.py -- being worn out in the daytime with something that cannot wait.

Until now a character whose fatigue crossed a threshold simply went to sleep, whatever was open: an adult with a hungry child
napped at midday and the child went unfed (and a house that stayed up all night was worse). That only spirals. Now:

  1. WHILE a responsibility is open (a child to feed, a child to remind -- any intention carrying a `child_id`), fatigue does not put
     an adult or teenager to sleep in the daytime (systems/body_intentions.py asks blocks_daytime_sleep()). A sleeper who is
     needed for such a duty is woken (should_wake_for_duty(), brain/agent_loop.py).
  2. Instead of sleep, fatigue strains them (strain(): from fatigue 65 up to 100, 0..1): stress and anger pressure build, they turn
     annoyed and then angry, and they notice less -- attention_factor() thins what perception picks up (fewer details of people and
     props) and the prompt says so.
  3. The way out is another person: someone who is there (a housemate first) OFFERS to take over the responsibility -- "I'll feed
     the kids, you need to calm down and get some sleep". The strained one snaps at the offer, and a few minutes later, probably,
     gives in: the duty is handed over (the helper gets the intention, they lose it) and they go to sleep. A refusal means the offer
     comes again later and the next one is accepted.

tick_exhaustion() runs every minute (core/tick_schedule.py CADENCE["exhaustion"]).
"""

import random

STRAIN_FROM_FATIGUE = 65.0
OFFER_MIN_STRAIN = 0.35
OFFER_CHANCE_PER_MINUTE = 0.12
OFFER_COOLDOWN = 20 * 60
DECIDE_AFTER = (300, 900)
ACCEPT_FIRST, ACCEPT_AFTER_REFUSAL = 0.65, 1.0
REST_WINDOW = 6 * 3600
WAKE_COOLDOWN = 10 * 60
HELPER_MAX_FATIGUE = 70.0
MIN_AGE = 13

OFFERS = ["Let me take care of {what}. You need to calm down and get some sleep.",
          "I'll see to {what} -- go and lie down, you're exhausted.",
          "Hey, relax. I've got {what}. Go and get some rest."]
RETORTS = ["I'm fine! Don't tell me what to do.", "I can handle it! Stop fussing.", "Don't tell me to calm down!"]
GIVING_IN = ["...Fine. Wake me if anything happens.", "Okay, okay. I'll lie down for a bit.", "You're right. I can't think straight. Thanks."]


def _fatigue(c):
    return (c.get("body") or {}).get("fatigue", 0) or 0


def _asleep(c):
    return (c.get("activity") or {}).get("type") in ("sleep", "nap")


def daytime(c, world):
    from systems.bedtime import in_sleep_time
    return not in_sleep_time(c, world)


def strain(c, world):
    """0 (fine) to 1 (at the end of their tether): fatigue above STRAIN_FROM_FATIGUE, by day, awake, from MIN_AGE."""
    if (c.get("age") or 99) < MIN_AGE or _asleep(c) or c.get("off_grid") or not daytime(c, world):
        return 0.0
    return max(0.0, min(1.0, (_fatigue(c) - STRAIN_FROM_FATIGUE) / (100.0 - STRAIN_FROM_FATIGUE)))


def duties(c):
    """Open responsibilities that someone else could take over: intentions that carry a child to look after."""
    return [i for i in c.get("active_intentions", []) if i.get("child_id") and str(i.get("type", "")).startswith(("feed_child_", "remind_child_", "check_on_child"))]


def rest_accepted(c, world):
    return (c.get("_rest_accepted_until") or 0) > world.get("tick", 0)


def blocks_daytime_sleep(c, world):
    """Does fatigue have to wait: an adult or teenager, in the daytime, with a responsibility open and nobody having taken it over."""
    if (c.get("age") or 99) < MIN_AGE or rest_accepted(c, world) or not daytime(c, world):
        return False
    return bool(duties(c))


def mistake_multiplier(c, world):
    """1.0 rested .. 3.0 at the end of their tether: how much more likely a slip is (accident rolls are scaled by it)."""
    return 1.0 + 2.0 * strain(c, world)


def attention_factor(c, world):
    """1.0 alert .. 0.5 worn out: how much of the details around them they pick up."""
    return 1.0 - 0.5 * strain(c, world)


def should_wake_for_duty(c, world):
    """A daytime sleeper whom a child is waiting for (hungry, or to be reminded) and who has not been relieved of it."""
    if not _asleep(c) or (c.get("age") or 99) < MIN_AGE or rest_accepted(c, world) or not daytime(c, world):
        return False
    if world.get("tick", 0) - (c.get("_duty_wake_tick") or -10 ** 9) < WAKE_COOLDOWN:
        return False
    chars = world.get("characters", {})
    for d in duties(c):
        child = chars.get(d["child_id"])
        if child and not child.get("off_grid") and (child.get("_awaiting_caregiver") or child.get("_awaiting_reminder")) \
                and child.get("building_id") == c.get("building_id"):
            return True
    return False


# ---- what it does to them ------------------------------------------------------------------------------------------------------------

def _apply_strain(c, world, s):
    c["stress"] = min(100, (c.get("stress") or 0) + 1.5 * s)
    from systems.impulse import add_anger_pressure
    add_anger_pressure(c, 0.004 * s, "exhaustion", world)
    if c.get("emotion") in (None, "neutral", "calm", "content", "happy"):
        if s >= 0.7:
            c["emotion"] = "angry"
        elif s >= 0.4:
            c["emotion"] = "annoyed"
    c["_strained_at"] = world.get("tick", 0)


SLIP_CHANCE_PER_MINUTE = 0.03     # at full strain; scaled by it
SLIPS = ["knocked something over", "fumbled and dropped something", "lost track of what they were doing", "got something wrong"]


def _maybe_slip(c, world, s):
    """A small mistake of the kind a worn-out person makes: noted, and it frays them further."""
    if random.random() >= SLIP_CHANCE_PER_MINUTE * s:
        return
    what = random.choice(SLIPS)
    c["stress"] = min(100, (c.get("stress") or 0) + 4)
    from systems.impulse import add_anger_pressure
    add_anger_pressure(c, 0.02, "own_mistake", world)
    c["_last_slip_tick"] = world.get("tick", 0)
    try:
        from brain.memory import store_memory
        store_memory(c, f"I {what} -- I am too tired to do anything properly.", importance=0.25, tags=["mistake", "exhaustion"],
                     tick=world.get("tick", 0), source="internal")
    except Exception:
        pass


def context_lines(c, world):
    s = strain(c, world)
    if s < 0.3:
        return None
    hours = (c.get("body") or {}).get("hours_awake", 0)
    lines = [f"You are worn out ({int(hours)} hours awake): short-tempered, tense, hard to keep your mind on details, and everything is more "
             f"than you can bear. You cannot lie down while "
             + ("a child still needs you." if duties(c) else "there is so much to do.")]
    offer = c.get("_rest_offer")
    if offer:
        by = (world.get("characters", {}).get(offer.get("by")) or {}).get("name", "Someone")
        lines.append(f"{by} has just offered to take over for you so you can calm down and sleep. It irritates you -- you are not thinking straight.")
    return lines


# ---- the way out: somebody else takes over ---------------------------------------------------------------------------------------------

def _helpers(c, world):
    """Adults who are here, awake, rested enough, nearest in the household first."""
    chars = world.get("characters", {})
    out = []
    for o in chars.values():
        if o["id"] == c["id"] or o.get("off_grid") or o.get("is_workplace_npc") or _asleep(o) or (o.get("age") or 0) < 18:
            continue
        if o.get("building_id") != c.get("building_id") or not c.get("building_id") or _fatigue(o) >= HELPER_MAX_FATIGUE:
            continue
        rel = (c.get("relationships") or {}).get(o["id"]) or {}
        score = (50 if o.get("household_id") == c.get("household_id") else 0) + (rel.get("friendship", 0) or 0) + (rel.get("familiarity", 0) or 0) / 4
        out.append((score, o))
    out.sort(key=lambda t: -t[0])
    return [o for _, o in out]


def _what(c, world):
    names = []
    for d in duties(c):
        n = (world.get("characters", {}).get(d["child_id"]) or {}).get("name", "").split(" ")[0]
        if n and n not in names:
            names.append(n)
    if not names:
        return "this"
    return names[0] if len(names) == 1 else "the kids"


def _say(c, world, text, target_id=None, act="remark", intent=None):
    try:
        from systems.expressions import express
        express(c, world, {"utterance": text, "speech_act": act, "volume": "medium", "target": target_id, "intent": intent})
    except Exception:
        pass


def hand_over(giver, taker, world):
    """The taker takes over the giver's open responsibilities (the intentions move)."""
    from brain.intentions import add_intention
    moved = []
    for d in duties(giver):
        giver["active_intentions"] = [i for i in giver["active_intentions"] if i is not d]
        add_intention(taker, {k: v for k, v in d.items() if k not in ("stage", "deadline_tick", "_seq", "checkins", "doing_at_checkin")})
        moved.append(d["type"])
    return moved


def _offer(c, helper, world, count):
    tick = world.get("tick", 0)
    c["_rest_offer"] = {"by": helper["id"], "tick": tick, "count": count, "decide_at": tick + random.randint(*DECIDE_AFTER)}
    _say(helper, world, random.choice(OFFERS).format(what=_what(c, world)), c["id"], act="offer", intent={"valence": "help"})
    _say(c, world, random.choice(RETORTS), helper["id"], act="retort")
    from systems.impulse import add_anger_pressure
    add_anger_pressure(c, 0.05, "told_to_calm_down", world)               # being told to calm down does not calm anyone down
    c["stress"] = min(100, (c.get("stress") or 0) + 4)


def _decide(c, helper, world):
    offer = c.pop("_rest_offer")
    tick = world.get("tick", 0)
    if not helper or helper.get("off_grid") or helper.get("building_id") != c.get("building_id") or _asleep(helper):
        c["_rest_offer_cd"] = tick + OFFER_COOLDOWN                         # the helper has gone: it lapses
        return
    if random.random() < (ACCEPT_FIRST if offer["count"] <= 1 else ACCEPT_AFTER_REFUSAL):
        what = _what(c, world)
        hand_over(c, helper, world)
        c["_rest_accepted_until"] = tick + REST_WINDOW
        _say(c, world, random.choice(GIVING_IN), helper["id"])
        try:
            from brain.memory import store_memory
            store_memory(c, f"{helper['name']} took over {what} so I could rest.", importance=0.4, tags=["rest", "help"], people=[helper["id"]], tick=tick, source="internal")
            store_memory(helper, f"I took over {what} so {c['name']} could get some sleep.", importance=0.3, tags=["rest", "help"], people=[c["id"]], tick=tick, source="internal")
        except Exception:
            pass
    else:
        c["_rest_offer_cd"] = tick + OFFER_COOLDOWN
        c["_rest_refusals"] = offer["count"]


def tick_exhaustion(world):
    """Every minute: strain builds, offers are made, and offers are answered."""
    tick = world.get("tick", 0)
    chars = world.get("characters", {})
    for c in chars.values():
        if c.get("is_workplace_npc") or c.get("is_service_worker") or c.get("alive") is False:
            continue
        offer = c.get("_rest_offer")
        if offer and tick >= offer["decide_at"]:
            _decide(c, chars.get(offer["by"]), world)
            continue
        s = strain(c, world)
        if s <= 0:
            if not offer and (c.get("_rest_refusals") and _fatigue(c) < STRAIN_FROM_FATIGUE):
                c.pop("_rest_refusals", None)
            continue
        _apply_strain(c, world, s)
        _maybe_slip(c, world, s)
        if offer or tick < (c.get("_rest_offer_cd") or 0) or s < OFFER_MIN_STRAIN or not duties(c):
            continue
        if random.random() >= OFFER_CHANCE_PER_MINUTE:
            continue
        helpers = _helpers(c, world)
        if helpers:
            _offer(c, helpers[0], world, (c.get("_rest_refusals") or 0) + 1)
