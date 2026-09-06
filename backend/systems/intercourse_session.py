"""
systems/intercourse_session.py

Turns a single accepted sexual_acts act (systems/intimacy.py::execute_act)
into a real multi-beat scene instead of a one-shot roll:

    foreplay -> main -> afterglow (cuddle) -> "go again?" -> (loop) or end

- foreplay: a real act happens (striptease/dry_humping/lapdance/handjob/
  blowjob/naked_caressing/masturbation), scored by a timing roll -- the
  better the roll, the higher session["foreplay_quality"], which feeds
  every main-phase roll afterward ("the more organic it feels").
- main: position acts (missionary/69/doggystyle/riding/spanking) build
  each partner's own orgasm meter (0-100). Every character has two
  private "climax_acts" (sexual_preferences.climax_acts, rolled at
  generation) -- their meter is capped at 80 until their PRIMARY act has
  been used on them this session, and capped just under 100 until their
  SECONDARY act has too. A partner only learns someone's climax_acts
  once told mid-scene (rel["known_climax_acts"]).
- afterglow: a real 10-minute cuddle, then a real roll for another round
  (more likely if either partner didn't finish; likelihood climbs with
  each round survived). A repeat round skips foreplay, extends the
  scene's allowed main-phase acts by 50%, and starts each partner's
  meter at 50 instead of 0.
- Ends with a scored memory for both partners (systems/stories.py-style
  "how it went," not just relationship-stat deltas).

Session state lives in world["intercourse_sessions"][id] -- one shared
object both participants point to via active_intercourse_session_id --
rather than duplicated across both relationship dicts, so phase/round/
points bookkeeping can't desync between the two sides.

Started by intimacy.py::execute_act() the moment two characters with no
existing session complete ANY sexual_acts act between them. Advanced
autonomously afterward by tick_intercourse_sessions() (sim_loop.py, a
frequent cadence), the same "started once, plays out over real time on
its own" shape systems/offgrid.py trips already use -- systems/
sexual_release.py's one-shot cascade only ever needs to kick the FIRST
act off.
"""

import random
import uuid

TICKS_PER_MINUTE = 60  # 1 tick == 1 nominal game-second

CUDDLE_MINUTES = 10
BASE_MAIN_ACTS_ALLOWED = 8
MAIN_ACTS_ALLOWED_GROWTH = 1.5

BASE_REROLL_CHANCE = 0.20
REROLL_CHANCE_PER_ROUND = 0.12
REROLL_UNFINISHED_BONUS = 0.30
MAX_REROLL_CHANCE = 0.85

MOAN_COOLDOWN_TICKS = 20


def generate_climax_acts(c, defs):
    """Called once at character generation. Picks two DISTINCT main-phase
    acts (climax_candidate: true in sexual_acts) as this character's own
    private "what actually gets me there" -- primary (needed to cross 80%
    on their orgasm meter this session) and secondary (needed to reach
    100%). A partner only learns these once told mid-scene (see
    _maybe_suggest_climax_act below), not from this generation-time
    roll itself."""
    acts_registry = (defs or {}).get("sexual_acts", {})
    candidates = [aid for aid, act in acts_registry.items() if act.get("climax_candidate")]
    if len(candidates) < 2:
        c.setdefault("sexual_preferences", {})["climax_acts"] = None
        return
    primary, secondary = random.sample(candidates, 2)
    c.setdefault("sexual_preferences", {})["climax_acts"] = {"primary": primary, "secondary": secondary}


def _sessions(world):
    return world.setdefault("intercourse_sessions", {})


def _get_or_create_session(a, b, world):
    existing_id = a.get("active_intercourse_session_id")
    sessions = _sessions(world)
    if existing_id and existing_id in sessions:
        sess = sessions[existing_id]
        if set(sess["participants"]) == {a["id"], b["id"]} and not sess.get("ended"):
            return sess

    sid = f"scene_{uuid.uuid4().hex[:8]}"
    sess = {
        "id": sid,
        "participants": [a["id"], b["id"]],
        "phase": "foreplay",
        "round": 1,
        "started_tick": world.get("tick", 0),
        "next_action_tick": 0,
        "foreplay_rolls": [],
        "foreplay_quality": 0.5,
        "orgasm": {a["id"]: 0.0, b["id"]: 0.0},
        "points": {a["id"]: 0, b["id"]: 0},
        "acts_performed_on": {a["id"]: [], b["id"]: []},
        "main_acts_this_round": 0,
        "main_acts_allowed": BASE_MAIN_ACTS_ALLOWED,
        "cuddle_until_tick": None,
        "suggested_climax_act": False,
        "ended": False,
    }
    sessions[sid] = sess
    a["active_intercourse_session_id"] = sid
    b["active_intercourse_session_id"] = sid
    return sess


def _other(sess, char_id):
    return sess["participants"][1] if sess["participants"][0] == char_id else sess["participants"][0]


def _chars(sess, world):
    reg = world.get("characters", {})
    a_id, b_id = sess["participants"]
    return reg.get(a_id), reg.get(b_id)


# ── Called from intimacy.py::execute_act() for every sexual_acts act ──────

def handle_act_execution(initiator, recipient, act_id, act, world):
    sess = _get_or_create_session(initiator, recipient, world)
    phase = act.get("phase", "foreplay")

    if phase == "foreplay":
        _resolve_foreplay(sess, initiator, recipient, act_id, act, world)
    elif phase == "main":
        _resolve_main(sess, initiator, recipient, act_id, act, world)
    elif phase == "afterglow":
        _resolve_afterglow(sess, initiator, recipient, act_id, act, world)

    duration_ticks = int(act.get("duration_minutes", 5) * TICKS_PER_MINUTE)
    sess["next_action_tick"] = world.get("tick", 0) + duration_ticks
    return {"session_id": sess["id"], "phase": sess["phase"], "orgasm": dict(sess["orgasm"]),
            "points": dict(sess["points"])}


def _timing_roll(a, b):
    """0-100. Better mutual attraction/comfort -> more likely to roll
    well ("how well timed partners are")."""
    rel_a = a.get("relationships", {}).get(b["id"], {})
    rel_b = b.get("relationships", {}).get(a["id"], {})
    bonus = (rel_a.get("attraction", 0) + rel_b.get("attraction", 0)) / 400.0 * 20  # up to +20
    return max(0, min(100, random.uniform(20, 90) + bonus))


def _resolve_foreplay(sess, initiator, recipient, act_id, act, world):
    roll = _timing_roll(initiator, recipient)
    sess["foreplay_rolls"].append(roll)
    sess["foreplay_quality"] = sum(sess["foreplay_rolls"]) / len(sess["foreplay_rolls"]) / 100.0

    points = round(act.get("base_score", 5) * (roll / 100.0))
    sess["points"][initiator["id"]] += points
    sess["points"][recipient["id"]] += points

    # One well-rolled foreplay act is enough to move on -- a real but
    # forgiving bar, "the higher the rolls the faster they finish
    # foreplay."
    if roll >= 45 or len(sess["foreplay_rolls"]) >= 3:
        sess["phase"] = "main"


def _climax_cap(sess, c, other_id):
    """80 by default; past that only once this person's PRIMARY act has
    been used on them this session; just under 100 only once their
    SECONDARY act has too."""
    climax_acts = (c.get("sexual_preferences") or {}).get("climax_acts")
    if not climax_acts:
        return 92.0
    performed = sess["acts_performed_on"].get(c["id"], [])
    primary_done = climax_acts.get("primary") in performed
    secondary_done = climax_acts.get("secondary") in performed
    if secondary_done:
        return 100.0
    if primary_done:
        return 99.0
    return 80.0


def _resolve_main(sess, initiator, recipient, act_id, act, world):
    sess["main_acts_this_round"] += 1
    for p in (initiator, recipient):
        sess["acts_performed_on"].setdefault(p["id"], []).append(act_id)

    roll = _timing_roll(initiator, recipient) * (0.7 + sess["foreplay_quality"] * 0.3)
    points = round(act.get("base_score", 15) * (roll / 100.0))
    sess["points"][initiator["id"]] += points
    sess["points"][recipient["id"]] += points

    _maybe_suggest_climax_act(sess, initiator, recipient, world)

    for p in (initiator, recipient):
        gain = 8.0 + roll / 8.0
        cap = _climax_cap(sess, p, _other(sess, p["id"]))
        current = sess["orgasm"].get(p["id"], 0.0)
        new_meter = min(cap, current + gain)
        sess["orgasm"][p["id"]] = new_meter
        _update_moan_and_climax_animation(p, new_meter, world)

    both_finished = all(v >= 100 for v in sess["orgasm"].values())
    if both_finished or sess["main_acts_this_round"] >= sess["main_acts_allowed"]:
        sess["phase"] = "afterglow"


def _maybe_suggest_climax_act(sess, initiator, recipient, world):
    """Once per session: the woman shares what actually gets her there,
    and the man commits it to memory (per the user's own framing of this
    mechanic) -- falls back to whichever partner has a defined preference
    when there's no female participant (e.g. a same-sex pairing)."""
    if sess.get("suggested_climax_act"):
        return

    pair = (initiator, recipient) if initiator.get("sex") == "female" else (recipient, initiator)
    if pair[0].get("sex") != "female":
        pair = (initiator, recipient)  # no female participant -- just try initiator first

    for owner, partner in (pair, (pair[1], pair[0])):
        climax_acts = (owner.get("sexual_preferences") or {}).get("climax_acts")
        if not climax_acts:
            continue
        rel = partner.setdefault("relationships", {}).setdefault(owner["id"], {})
        if rel.get("known_climax_acts"):
            continue
        rel["known_climax_acts"] = dict(climax_acts)
        sess["suggested_climax_act"] = True
        try:
            from systems.incidental_speech import fire_incidental
            fire_incidental(owner, "inform", "tells their partner what really does it for them", world)
        except Exception:
            pass
        return


_MOAN_LINES = {
    1: "lets out a soft moan",
    2: "moans, breathing faster",
    3: "cries out",
}


def _update_moan_and_climax_animation(c, meter, world):
    c["orgasm_meter"] = round(meter, 1)
    c["moan_intensity"] = round(min(1.0, meter / 100.0), 2)

    prior_stage = c.get("orgasm_stage", 0)
    if meter >= 100 and prior_stage < 3:
        new_stage = 3
    elif meter >= 85 and prior_stage < 2:
        new_stage = 2
    elif meter >= 80 and prior_stage < 1:
        new_stage = 1
    else:
        new_stage = prior_stage

    if new_stage != prior_stage:
        c["orgasm_stage"] = new_stage
        try:
            defs = world.get("definitions", {})
            anim_key = f"phase_{new_stage}"
            anim = defs.get("orgasm_animations", {}).get(anim_key, {}).get(c.get("sex", "male"))
            if anim:
                c["animation_state"] = anim
        except Exception:
            pass

    tick = world.get("tick", 0)
    if tick - c.get("_last_moan_tick", -9999) < MOAN_COOLDOWN_TICKS:
        return
    tier = 3 if meter >= 90 else (2 if meter >= 60 else (1 if meter >= 25 else 0))
    if tier == 0:
        return
    c["_last_moan_tick"] = tick
    try:
        from systems.incidental_speech import fire_incidental
        fire_incidental(c, "moan", _MOAN_LINES[tier], world)
    except Exception:
        pass


def _resolve_afterglow(sess, initiator, recipient, act_id, act, world):
    sess["cuddle_until_tick"] = world.get("tick", 0) + CUDDLE_MINUTES * TICKS_PER_MINUTE
    for p in (initiator, recipient):
        p["orgasm_stage"] = 0
        p["moan_intensity"] = 0.0
        p["orgasm_meter"] = 0.0


def resolve_go_again(sess, world):
    a, b = _chars(sess, world)
    if not a or not b:
        _end_session(sess, world, aborted=True)
        return

    unfinished = any(v < 100 for v in sess["orgasm"].values())
    chance = BASE_REROLL_CHANCE + REROLL_CHANCE_PER_ROUND * sess["round"]
    if unfinished:
        chance += REROLL_UNFINISHED_BONUS
    chance = min(MAX_REROLL_CHANCE, chance)

    if random.random() < chance:
        sess["round"] += 1
        sess["phase"] = "main"          # skip foreplay on a repeat round
        sess["main_acts_this_round"] = 0
        sess["main_acts_allowed"] = round(sess["main_acts_allowed"] * MAIN_ACTS_ALLOWED_GROWTH)
        for cid in sess["orgasm"]:
            sess["orgasm"][cid] = 50.0  # per-round restart point
        for p in (a, b):
            p["orgasm_meter"] = 50.0
        sess["next_action_tick"] = world.get("tick", 0)
        sess["cuddle_until_tick"] = None
    else:
        _end_session(sess, world)


def _end_session(sess, world, aborted=False):
    a, b = _chars(sess, world)
    total_score = sum(sess["points"].values())
    sess["ended"] = True

    for c, other in ((a, b), (b, a)):
        if not c:
            continue
        c["active_intercourse_session_id"] = None
        c["orgasm_stage"] = 0
        c["moan_intensity"] = 0.0
        c["orgasm_meter"] = 0.0
        try:
            from brain.memory import store_memory
            other_name = other.get("name", "them") if other else "them"
            finished = sess["orgasm"].get(c["id"], 0) >= 100
            outcome = "aborted early" if aborted else ("finished" if finished else "didn't quite finish")
            text = (
                f"Slept with {other_name} ({sess['round']} round"
                f"{'s' if sess['round'] > 1 else ''}) -- {outcome}."
            )
            store_memory(
                c, text, importance=0.6, tags=["intimacy", "sex"],
                tick=world.get("tick", 0), people=[other["id"]] if other else [],
                score=sess["points"].get(c["id"], 0),
            )
        except Exception:
            pass


# ── Autonomous scene continuation (sim_loop.py cadence) ───────────────────

def tick_intercourse_sessions(world):
    tick = world.get("tick", 0)
    for sess in list(_sessions(world).values()):
        if sess.get("ended"):
            continue

        a, b = _chars(sess, world)
        if not a or not b:
            _end_session(sess, world, aborted=True)
            continue

        if a.get("building_id") != b.get("building_id") or a.get("off_grid") or b.get("off_grid"):
            _end_session(sess, world, aborted=True)
            continue

        if sess["phase"] == "afterglow":
            if sess.get("cuddle_until_tick") is not None and tick >= sess["cuddle_until_tick"]:
                resolve_go_again(sess, world)
            continue

        if tick < sess.get("next_action_tick", 0):
            continue

        _advance_scene(sess, a, b, world)


def _advance_scene(sess, a, b, world):
    from systems.intimacy import get_available_acts, execute_act

    phase = sess["phase"]
    acts = get_available_acts(a, b, world, phase=phase)
    if not acts:
        _end_session(sess, world, aborted=True)
        return

    if phase == "main":
        # Prefer whichever act unlocks a partner's next climax cap.
        wanted_ids = set()
        for p in (a, b):
            climax_acts = (p.get("sexual_preferences") or {}).get("climax_acts")
            if not climax_acts:
                continue
            performed = sess["acts_performed_on"].get(p["id"], [])
            if climax_acts.get("primary") not in performed:
                wanted_ids.add(climax_acts["primary"])
            elif climax_acts.get("secondary") not in performed:
                wanted_ids.add(climax_acts["secondary"])
        preferred = [act for act in acts if act["id"] in wanted_ids]
        chosen = random.choice(preferred) if preferred else random.choice(acts)
    else:
        chosen = random.choice(acts)

    execute_act(a, b, chosen["id"], world)
