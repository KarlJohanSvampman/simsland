"""
systems/grudges.py -- what a registered insult leaves behind (docs/relationship_impact_plan.md, section 7).

The relationship ledger (systems/relationship_ledger.py) decides what REGISTERED with someone. This keeps what that
costs afterwards: a grudge, held by the one who was hurt, against the one who did it.

    c["grudges"][offender_id] = {
        id, offender, status,               # open | resolved | faded
        origin: {kind, value, text, entry},  # what started it
        created, last_refreshed, refreshes,
        short_term_until,                   # until then they are actively cross
        retention, retention_at_creation,   # 0-1: how firmly they keep it; fades once the short term is over
        priority,                           # 1-10: how much it occupies them
        jabbed, escalated, nudged, aware,   # what has been done about it so far
    }

  Opens when one registered negative act is weighty enough (OPEN_VALUE) or several within PRESSURE_WINDOW add up
  (PRESSURE_VALUE). Only acts aimed at them count; a witness's or an assumption's entry does not.
  Refreshes when another negative act from the same person registers: the short term is extended, the retention
  and the priority go up.
  The holder expects an apology (their prompt says so). While it is open they are cold towards the offender
  and, by temperament, jab at them (hurtful remark), mutter or sigh when they are near -- one-way expressions, so
  the ledger sees them and a quarrel can start; at high priority they want a confrontation (the existing
  `confrontation_desired` event). After a while the offender, if they are not too proud, is nudged towards
  apologising.
  Resolution: an apology from the offender that registers clears the short term and halves the retention; a
  kind act, a concession or a favour shortens it by a fraction of its value; at no retention it is closed.
  Closing leaves one aggregated memory (how it began, how it ended) and adds a score to the pair's engagement:
  ceil(hours open x retention at creation).
"""

import math
import random

from core.event_bus import emit

HOUR = 3600
OPEN_VALUE = 8.0                       # one registered negative act this heavy opens a grudge
PRESSURE_VALUE = 12.0                  # ... or several together within PRESSURE_WINDOW
PRESSURE_WINDOW = 2 * HOUR
SHORT_TERM_TICKS = 2 * HOUR
REFRESH_SHORT_TERM_TICKS = HOUR
MAX_SHORT_TERM_TICKS = 12 * HOUR
LONG_TERM_TICKS = 48 * HOUR            # a grudge at retention 1.0 takes this long to fade by itself (after the short term)
RESOLVED_BELOW = 0.05
JAB_COOLDOWN_TICKS = 20 * 60
NUDGE_AFTER_TICKS = 30 * 60
ESCALATE_PRIORITY = 6
KEEP_CLOSED = 5
APOLOGY_RETENTION_FACTOR = 0.5
KINDNESS_KINDS = {"concession", "altruism", "solidarity", "compliment", "favor", "generosity", "encouragement", "pride",
                  "love", "kindness", "congratulation", "personal_acknowledgement"}

GRUDGY_TRAITS = {"petty": 1.4, "vindictive": 1.5, "spiteful": 1.4, "stubborn": 1.2, "controlling": 1.1, "overcritical": 1.1,
                 "sensitive": 1.2}
FORGIVING_TRAITS = {"forgiving": 0.6, "compassionate": 0.8, "patient": 0.85, "calm": 0.9, "humble": 0.9}
HOT_TRAITS = {"hot_tempered", "short_tempered", "aggressive", "spiteful", "vindictive", "impulsive"}
PROUD_TRAITS = {"arrogant", "stubborn", "vindictive", "egotistical", "entitled", "narcissistic"}

_JABS = ["Don't think I've forgotten what you did.", "Look who it is.", "You've got some nerve showing your face.",
         "I haven't forgotten, you know."]
_MUTTERS = ["I'm still not over what {name} did...", "{name} still hasn't said sorry...", "I can't believe {name}..."]
_SIGHS = ["Hmph.", "Some people.", "Not a word of apology..."]
_KID_MUTTERS = ["I'm still mad at {name}.", "{name} was mean to me.", "{name} didn't say sorry."]
_KID_SIGHS = ["Hmph!", "I'm not talking to you.", "Humph."]


def _grudges(c):
    return c.setdefault("grudges", {})


def open_grudges(c):
    return [g for g in (c.get("grudges") or {}).values() if g.get("status") == "open"]


def open_grudges_against(world, offender_id):
    """Everyone holding a grudge against `offender_id` (for a standing penalty and the like)."""
    out = []
    for c in world.get("characters", {}).values():
        g = (c.get("grudges") or {}).get(offender_id)
        if g and g.get("status") == "open":
            out.append(g)
    return out


def _temperament(c):
    traits = set(c.get("traits") or [])
    f = 1.0
    for t in traits:
        f *= GRUDGY_TRAITS.get(t, 1.0) * FORGIVING_TRAITS.get(t, 1.0)
    return f


# ---------------------------------------------------------------------------
# from the ledger
# ---------------------------------------------------------------------------

def on_perceived(world, holder, source_id, intent, entry, value):
    """Called by the ledger after a perceived entry is written on `holder` (the one it was aimed at)."""
    if entry.get("witnessed") or entry.get("misattributed"):
        return                                         # only what was done to them
    if intent["polarity"] < 0:
        _on_negative(world, holder, source_id, intent, entry, value)
    else:
        _on_positive(world, holder, source_id, intent["kind"], value)


def _on_negative(world, holder, offender_id, intent, entry, value):
    tick = world.get("tick", 0)
    existing = _grudges(holder).get(offender_id)
    if existing and existing.get("status") == "open":
        _refresh(existing, value, tick)
        return
    pressure = [(t, v) for t, v in (holder.setdefault("_grudge_pressure", {}).get(offender_id) or []) if tick - t <= PRESSURE_WINDOW]
    pressure.append((tick, value))
    holder["_grudge_pressure"][offender_id] = pressure[-12:]
    if value >= OPEN_VALUE or sum(v for _, v in pressure) >= PRESSURE_VALUE:
        _open(world, holder, offender_id, intent, entry, max(value, sum(v for _, v in pressure) / 2.0))
        holder["_grudge_pressure"].pop(offender_id, None)


def _open(world, holder, offender_id, intent, entry, value):
    tick = world.get("tick", 0)
    retention = max(0.2, min(1.0, (0.3 + value / 30.0) * _temperament(holder)))
    g = {
        "id": f"grudge_{tick}_{offender_id[-4:]}", "offender": offender_id, "status": "open",
        "origin": {"kind": intent["kind"], "value": round(value, 2), "text": intent.get("text"), "entry": entry.get("id")},
        "created": tick, "last_refreshed": tick, "refreshes": 0,
        "short_term_until": tick + SHORT_TERM_TICKS,
        "retention": round(retention, 3), "retention_at_creation": round(retention, 3),
        "priority": max(1, min(10, math.ceil(value * 0.6))),
        "jabbed": -10 ** 9, "escalated": False, "nudged": False, "aware": False,
    }
    _grudges(holder)[offender_id] = g
    _prune(holder)
    try:
        from brain.memory import store_memory
        name = (world.get("characters", {}).get(offender_id) or {}).get("name", "them")
        store_memory(holder, f"{name} hurt me ({intent['kind'].replace('_', ' ')}). I'm not going to forget it, and I'm waiting "
                             f"for an apology.", importance=min(0.9, 0.4 + value / 20.0),
                     tags=["grudge", "conflict"], people=[offender_id], tick=tick, source="internal")
    except Exception:
        pass


def _refresh(g, value, tick):
    g["refreshes"] += 1
    g["last_refreshed"] = tick
    g["short_term_until"] = min(g["short_term_until"] + REFRESH_SHORT_TERM_TICKS, tick + MAX_SHORT_TERM_TICKS)
    g["retention"] = round(min(1.0, g["retention"] + 0.1 + value / 60.0), 3)
    g["priority"] = min(10, g["priority"] + 1)


def _on_positive(world, holder, source_id, kind, value):
    g = (holder.get("grudges") or {}).get(source_id)
    if not g or g.get("status") != "open":
        return
    tick = world.get("tick", 0)
    if kind == "apology":
        g["short_term_until"] = min(g["short_term_until"], tick)
        g["retention"] = round(g["retention"] * APOLOGY_RETENTION_FACTOR, 3)
        g["apologised"] = tick
    elif kind in KINDNESS_KINDS:
        g["retention"] = round(g["retention"] * (1.0 - min(0.3, value / 50.0)), 3)
    else:
        return
    if g["retention"] < RESOLVED_BELOW or (kind == "apology" and g["retention"] < 0.15):
        close(world, holder, g, "resolved", "they apologised" if kind == "apology" else "they made up for it")


def close(world, holder, g, status, how):
    """Resolve or fade a grudge: leave one memory, add the pair's engagement score."""
    tick = world.get("tick", 0)
    g["status"] = status
    g["closed"] = tick
    g["closed_how"] = how
    hours = max(0.0, (tick - g["created"]) / HOUR)
    g["score"] = math.ceil(hours * g["retention_at_creation"])
    offender = world.get("characters", {}).get(g["offender"])
    if offender:                                       # nothing left to apologise for
        offender["active_intentions"] = [i for i in offender.get("active_intentions", [])
                                         if not (i.get("type") == "apologize_to" and i.get("target_id") == holder["id"])]
    try:
        from systems.relationship_ledger import get_ledger
        led = get_ledger(world, holder["id"], g["offender"], create=False)
        if led:
            led["summary"]["engagement"] = round(led["summary"]["engagement"] + g["score"], 2)
    except Exception:
        pass
    try:
        from brain.memory import store_memory
        name = (world.get("characters", {}).get(g["offender"]) or {}).get("name", "them")
        origin = g["origin"]["kind"].replace("_", " ")
        store_memory(holder, f"I was upset with {name} for a while after the {origin}. "
                             f"It {'faded on its own' if status == 'faded' else 'ended because ' + how}, "
                             f"about {max(1, round(hours))} hour{'s' if round(hours) != 1 else ''} later.",
                     importance=0.4, tags=["grudge", status], people=[g["offender"]], tick=tick, source="internal")
    except Exception:
        pass


def _prune(holder):
    closed = sorted((g for g in holder["grudges"].values() if g.get("status") != "open"), key=lambda g: g.get("closed", 0))
    for g in closed[:max(0, len(closed) - KEEP_CLOSED)]:
        holder["grudges"].pop(g["offender"], None)


# ---------------------------------------------------------------------------
# over time
# ---------------------------------------------------------------------------

def _visible(holder, offender_id):
    return any(p.get("id") == offender_id for p in (holder.get("perception") or {}).get("visible_people", []))


def tick_grudges(world):
    """Scheduled job (every sim-minute): fade, behave, escalate, nudge."""
    tick = world.get("tick", 0)
    chars = world.get("characters", {})
    for holder in chars.values():
        if not holder.get("grudges") or holder.get("alive") is False or holder.get("off_grid"):
            continue
        for g in open_grudges(holder):
            offender = chars.get(g["offender"])
            if not offender or offender.get("alive") is False:
                close(world, holder, g, "faded", "they are gone")
                continue
            _decay(world, holder, g, tick)
            if g["status"] != "open":
                continue
            _behave(world, holder, offender, g, tick)
            _nudge(world, holder, offender, g, tick)
            _escalate(world, holder, offender, g, tick)


def _decay(world, holder, g, tick):
    last = g.get("_decayed", max(g["last_refreshed"], g["short_term_until"]))
    if tick <= g["short_term_until"]:
        g["_decayed"] = g["short_term_until"]
        return
    elapsed = tick - max(last, g["short_term_until"])
    g["_decayed"] = tick
    g["retention"] = round(max(0.0, g["retention"] - g["retention_at_creation"] * elapsed / LONG_TERM_TICKS), 4)
    if g["retention"] < RESOLVED_BELOW:
        close(world, holder, g, "faded", "time passed")


def _behave(world, holder, offender, g, tick):
    """While the grudge is hot and the offender is near: a jab, a mutter or a sigh."""
    if tick > g["short_term_until"] or not _visible(holder, g["offender"]):
        return
    if (holder.get("activity") or {}).get("type") in ("sleep", "nap") or tick - g["jabbed"] < JAB_COOLDOWN_TICKS:
        return
    if random.random() > 0.35:
        return
    g["jabbed"] = tick
    g["aware"] = True
    from systems.expressions import express
    traits = set(holder.get("traits") or [])
    name = offender.get("name", "them")
    child = (holder.get("age") or 99) < 13
    if child:                           # a child sulks; they do not trade adult insults
        if random.random() < 0.5:
            express(holder, world, {"utterance": random.choice(_KID_MUTTERS).format(name=name.split(" ")[0]), "speech_act": "mutter",
                                    "volume": "low", "target": None, "intent": {"source": "grudge"}})
        else:
            express(holder, world, {"utterance": random.choice(_KID_SIGHS), "speech_act": "sigh", "volume": "low", "target": None,
                                    "intent": {"source": "grudge"}})
        return
    if traits & HOT_TRAITS:
        express(holder, world, {"utterance": random.choice(_JABS), "speech_act": "insult", "volume": "medium",
                                "target": offender["id"], "intent": {"valence": "hurt", "source": "grudge"}})
    elif random.random() < 0.5:
        express(holder, world, {"utterance": random.choice(_MUTTERS).format(name=name), "speech_act": "mutter", "volume": "low",
                                "target": None, "intent": {"source": "grudge"}})
    else:
        express(holder, world, {"utterance": random.choice(_SIGHS), "speech_act": "sigh", "volume": "low", "target": None,
                                "intent": {"source": "grudge"}})


def _nudge(world, holder, offender, g, tick):
    """The offender, if they are not too proud, is moved to make amends."""
    if g["nudged"] or tick - g["created"] < NUDGE_AFTER_TICKS or offender.get("off_grid"):
        return
    g["nudged"] = True
    g["aware"] = True
    if set(offender.get("traits") or []) & PROUD_TRAITS or random.random() > 0.6:
        return
    from brain.intentions import add_intention
    add_intention(offender, {"type": "apologize_to", "category": "social", "priority": 42, "target_id": holder["id"],
                             "reason": f"{holder.get('name', 'Someone')} is still upset with you over what you did "
                                       f"({g['origin']['kind'].replace('_', ' ')}) -- apologise and make it right"})


def _escalate(world, holder, offender, g, tick):
    if g["escalated"] or g["priority"] < ESCALATE_PRIORITY or not _visible(holder, g["offender"]):
        return
    g["escalated"] = True
    g["aware"] = True
    emit("confrontation_desired", {"initiator_id": holder["id"], "target_id": offender["id"], "score": float(g["priority"] * 5)})


# ---------------------------------------------------------------------------
# what they know of it
# ---------------------------------------------------------------------------

def context_lines(c, world):
    lines = []
    chars = world.get("characters", {})
    tick = world.get("tick", 0)
    for g in open_grudges(c):
        name = (chars.get(g["offender"]) or {}).get("name", "them")
        what = g["origin"]["kind"].replace("_", " ")
        state = "still furious" if tick <= g["short_term_until"] and g["priority"] >= 6 else \
            "still upset" if tick <= g["short_term_until"] else "still holding it against them"
        fading = " It is slowly fading." if g["retention"] < 0.3 else ""
        lines.append(f"You are {state} with {name} over what happened ({what}). You are waiting for them to apologise.{fading}")
    for other in chars.values():
        if not other.get("grudges"):
            continue
        g = other["grudges"].get(c.get("id"))
        if g and g.get("status") == "open" and g.get("aware"):
            lines.append(f"{other.get('name', 'Someone')} is upset with you over what happened ({g['origin']['kind'].replace('_', ' ')}). "
                         f"An apology would help.")
    return lines
