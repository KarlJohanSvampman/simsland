"""
systems/worry_relief.py -- what worry does to what a character can do, and how they get relief.

(docs/worry_system_plan.md, step 3. Case files and the focus budget: systems/worry_cases.py; what opens
cases: systems/worry_producers.py.)

  Required focus.  Demanding activities (study, a work shift, writing, paying bills, ...) carry a
      required_focus percentage (definitions.json -> activity_required_focus; DEFAULT_REQUIRED_FOCUS is the
      fallback). While the character is doing one, every ROLL_EVERY_TICKS (3 simulated minutes) there is a
      chance they give up on it: the SHORTFALL, required - available focus (0 when they have enough). The
      activity is interrupted, a memory "I couldn't concentrate on X" is stored, the intention that drove it
      is dropped as a recorded failure and held back for a while, and a mitigation intention appears.
      Below OVERWHELMED_BELOW percent focus a demanding activity can't even be started (start_activity asks
      blocks_start); trivial ones (no requirement, or <= TRIVIAL_MAX) and survival/health ones always can.

  Mitigation.  When focus is down to COMFORT_FOCUS or less (or after an abort) the character raises a
      `relieve_worry` intention aimed at their heaviest case. The MODE is chosen from the case, their traits,
      age and what is possible:
          inform     talk it over, read the news -- shortens THAT case
          distract   music, TV, a jog, a walk, company -- eases every case a little
          transcend  reflect, journal, meditate, cry; adults may have a drink (LLM-chosen) -- the biggest cut
      resolve_strategy turns the intention into a concrete activity (trying the candidates in order until one
      can start). When the activity completes, its entry in definitions.json -> worry_relief (DEFAULT_RELIEF)
      is applied: the remaining time and the severity of the targeted cases shrink by reduce_pct, and a case
      that falls below the registration threshold is closed as eased.
"""

import random

from core.event_bus import subscribe
from systems import worry_cases as wc
from systems.worry_cases import HOUR

COMFORT_FOCUS = 50                 # at or below this they start looking for relief
COMFORT_RECOVERED = 62             # a mitigation intention is dropped once focus is back above this
OVERWHELMED_BELOW = 25             # below this demanding activities can't be started
TRIVIAL_MAX = 15                   # a required_focus at or below this counts as trivial
ROLL_EVERY_TICKS = 180             # 3 simulated minutes
ABORT_SUPPRESS_TICKS = 1800        # the intention that drove an aborted activity stays away this long
RELIEF_COOLDOWN_TICKS = HOUR       # no new mitigation intention for this long after relief
EASED_FOR_TICKS = 3 * HOUR         # a case eased by relief is not pushed back up by the next scan for this long
TRIED_RESET_TICKS = 1800
MITIGATION_PRIORITY = 60
RECENT_ABORT_TICKS = 2 * HOUR
_VITAL = {"survival", "health"}

DEFAULT_REQUIRED_FOCUS = {
    "study": 70, "work_shift": 60, "write": 60, "practice_skill": 55, "pay_bills": 55, "fill_form": 50,
    "apply_job": 50, "cook_recipe": 50, "paint": 50, "read_book": 45, "respond_to_mail": 40, "look_for_job": 40,
    "make_drawing": 40, "sort_mail": 25, "jog": 15, "exercise": 15,
}

BASE_REDUCE = {"inform": 25, "distract": 10, "transcend": 30}
# activity -> {mode, reduce_pct (optional), area_tags (inform: which cases it helps), min_age (optional)}
DEFAULT_RELIEF = {
    "browse_news":         {"mode": "inform", "reduce_pct": 25, "area_tags": ["news", "media", "politics", "neighbourhood", "crime", "finances", "health"]},
    "read_newspaper":      {"mode": "inform", "reduce_pct": 25, "area_tags": ["news", "media", "politics", "neighbourhood", "crime", "finances"]},
    "call_person":         {"mode": "inform", "reduce_pct": 25},
    "phone_call":          {"mode": "inform", "reduce_pct": 25},
    "visit_person":        {"mode": "inform", "reduce_pct": 30},
    "text_person":         {"mode": "inform", "reduce_pct": 15},
    "watch_tv":            {"mode": "distract", "reduce_pct": 10},
    "listen_to_music":     {"mode": "distract", "reduce_pct": 10},
    "jog":                 {"mode": "distract", "reduce_pct": 12},
    "exercise":            {"mode": "distract", "reduce_pct": 12},
    "walk_neighborhood":   {"mode": "distract", "reduce_pct": 10},
    "sit_in_park":         {"mode": "distract", "reduce_pct": 10},
    "sit_and_relax":       {"mode": "distract", "reduce_pct": 8},
    "hangout":             {"mode": "distract", "reduce_pct": 12},
    "watch_movie_together": {"mode": "distract", "reduce_pct": 10},
    "daydream":            {"mode": "distract", "reduce_pct": 8},
    "reflect":             {"mode": "transcend", "reduce_pct": 25},
    "journal":             {"mode": "transcend", "reduce_pct": 30},
    "meditate":            {"mode": "transcend", "reduce_pct": 35},
    "cry":                 {"mode": "transcend", "reduce_pct": 15},
    "drink_alcohol":       {"mode": "transcend", "reduce_pct": 30, "min_age": 21},
    "have_drink":          {"mode": "transcend", "reduce_pct": 30, "min_age": 21},
}

# activities the mitigation intention can start by itself (the others -- a drink -- are the character's own choice)
AUTOPILOT = {
    "inform": ["call_person", "browse_news", "visit_person", "read_newspaper"],
    "distract": ["listen_to_music", "watch_tv", "jog", "walk_neighborhood", "sit_in_park", "sit_and_relax"],
    "transcend": ["meditate", "reflect", "journal"],
}
# trait -> {activity: weight multiplier}
TRAIT_TASTE = {
    "exercise_consistent": {"jog": 2.5, "exercise": 2.5}, "exercise_overdoer": {"jog": 2.5, "exercise": 2.5},
    "creative": {"journal": 2.0}, "thoughtful": {"journal": 1.6, "reflect": 1.6}, "cognition_selfaware": {"reflect": 1.6, "journal": 1.4},
    "calm": {"meditate": 2.0}, "wise": {"meditate": 1.5, "reflect": 1.5}, "deeply_religious": {"meditate": 2.5, "reflect": 1.5},
    "daydreamer": {"reflect": 1.5}, "playful": {"watch_tv": 1.3, "listen_to_music": 1.3},
}
TRAIT_MODE = {   # trait -> mode weight multipliers
    "empathetic": {"inform": 1.5}, "compassionate": {"inform": 1.3}, "cheerful": {"inform": 1.2, "distract": 1.2},
    "charismatic": {"inform": 1.4}, "codependent": {"inform": 1.8}, "secretive": {"inform": 0.4}, "independent": {"inform": 0.6},
    "distrustful": {"inform": 0.5}, "adventurous": {"distract": 1.4}, "lazy": {"distract": 1.2},
    "thoughtful": {"transcend": 1.5}, "wise": {"transcend": 1.5}, "deeply_religious": {"transcend": 2.0},
    "calm": {"transcend": 1.3}, "daydreamer": {"transcend": 1.3}, "cognition_selfaware": {"transcend": 1.4},
}
DRINKERS = {"addiction_prone", "self_destructive"}


# ---------------------------------------------------------------------------
# the tables
# ---------------------------------------------------------------------------

def required_focus(world, activity_type):
    table = dict(DEFAULT_REQUIRED_FOCUS)
    table.update(((world or {}).get("definitions") or {}).get("activity_required_focus", {}))
    return table.get(activity_type)


def relief_spec(world, activity_type):
    table = dict(DEFAULT_RELIEF)
    table.update(((world or {}).get("definitions") or {}).get("worry_relief", {}))
    return table.get(activity_type)


def _category(activity_type):
    try:
        from systems.activities import ACTIVITIES
        return (ACTIVITIES.get(activity_type) or {}).get("category")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# can they start it?
# ---------------------------------------------------------------------------

def blocks_start(c, world, activity_type):
    """True if worry leaves too little focus to START this activity. Pure; start_activity() asks."""
    if not c.get("worry_cases"):
        return False
    req = required_focus(world, activity_type)
    if not req or req <= TRIVIAL_MAX:
        return False
    if _category(activity_type) in _VITAL:
        return False
    return wc.focus_available(c, world) < OVERWHELMED_BELOW


# ---------------------------------------------------------------------------
# the roll while they work
# ---------------------------------------------------------------------------

def tick_focus_checks(world):
    """Scheduled job (every sim-minute): keep each worried character's mitigation intention in step with their
    focus, and roll for an abort when they are in the middle of something that needs more focus than they have."""
    tick = world.get("tick", 0)
    for c in world.get("characters", {}).values():
        if c.get("is_workplace_npc") or c.get("is_service_worker") or c.get("alive") is False:
            continue
        if not c.get("worry_cases"):
            continue
        avail = wc.focus_available(c, world)
        from systems.worry_breakdown import tick_breakdown, in_breakdown
        tick_breakdown(c, world, avail)                   # starts, steps or ends a breakdown episode
        if in_breakdown(c):
            continue                                       # nothing else applies while they are falling apart
        sync_mitigation(c, world, avail)
        act = c.get("activity")
        if not act or act.get("phase") != "using":
            continue
        req = required_focus(world, act.get("type"))
        if not req:
            continue
        due = act.get("_focus_roll")
        if due is None:
            act["_focus_roll"] = tick + ROLL_EVERY_TICKS
            continue
        if tick < due:
            continue
        act["_focus_roll"] = tick + ROLL_EVERY_TICKS
        shortfall = max(0, min(100, req - avail))
        if shortfall and random.random() * 100.0 < shortfall:
            abort_activity(c, world, act, req, avail)


def abort_activity(c, world, act, req, avail):
    from systems.occupancy import interrupt_activity
    tick = world.get("tick", 0)
    activity = act.get("type")
    what = str(activity).replace("_", " ")
    interrupt_activity(c, world)
    c["is_moving"] = False
    c["move_target"] = None
    intention = c.get("current_intention") or {}
    itype, category = intention.get("type"), intention.get("category")
    c["current_intention"] = None
    if itype:
        from brain.intentions import remove_intention
        remove_intention(c, itype)
        if category not in _VITAL:
            c.setdefault("_intention_suppressed", {})[itype] = tick + ABORT_SUPPRESS_TICKS
    top = _top_case(c)
    why = f" My mind keeps going back to {top['subject'].get('label') or 'what is wrong'}." if top else ""
    thought = f"I couldn't concentrate on {what}.{why}"
    c.setdefault("failed_intentions", []).append({
        "id": f"focus_{tick}", "tick": tick, "kind": "focus", "activity": what, "count": 1, "span_ticks": 0,
        "intention": itype, "category": category, "reason": "couldnt_concentrate", "thought": thought,
        "instead": None, "situation": None, "status": "done",
    })
    del c["failed_intentions"][:-20]
    c["_focus_abort"] = {"tick": tick, "activity": activity, "required": req, "available": avail}
    state = c.setdefault("focus_state", {})
    state["aborts"] = state.get("aborts", 0) + 1
    from systems.worry_breakdown import note_abort
    note_abort(c, world)
    try:
        from brain.memory import store_memory
        store_memory(c, thought, importance=0.45, tags=["worry_case", "concentration"], tick=tick, source="internal")
    except Exception:
        pass
    maybe_raise_mitigation(c, world, force=True)
    try:
        from brain.cognition_scheduler import wake_character
        wake_character(c, world, "worry_overload", {"activity": what})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# mitigation intentions
# ---------------------------------------------------------------------------

def _top_case(c):
    act = wc.active_cases(c)
    return max(act, key=lambda cs: cs["focus_cost"], default=None)


def _has_intention(c):
    return next((i for i in c.get("active_intentions", []) if i.get("type") == "relieve_worry"), None)


def _min_age(activity_type):
    try:
        from systems.action_registry import ACTION_TYPE_MIN_AGE
        return ACTION_TYPE_MIN_AGE.get(activity_type, 0)
    except Exception:
        return 0


def choose_mode(c, world, case):
    """Pick inform / distract / transcend for this character and this worry."""
    age = c.get("age") or 30
    traits = set(c.get("traits") or [])
    weights = {"inform": 1.0, "distract": 1.2, "transcend": 0.8}
    kind = case["subject"]["kind"]
    if kind in ("person", "conflict", "choice"):
        weights["inform"] *= 1.6                       # talk it over with someone
    elif kind == "area":
        weights["inform"] *= 1.3                       # find out more
    if age < 12:
        weights["transcend"] *= 0.5                    # a small child distracts or tells someone
    for t in traits:
        for mode, f in TRAIT_MODE.get(t, {}).items():
            weights[mode] *= f
    if c.get("is_moving") or c.get("off_grid"):
        weights["transcend"] *= 0.5
    return random.choices(list(weights), weights=list(weights.values()))[0]


def _candidates(c, world, mode):
    age = c.get("age") or 30
    traits = set(c.get("traits") or [])
    pool = []
    for a in AUTOPILOT[mode]:
        if age < _min_age(a):
            continue
        w = 1.0
        for t in traits:
            w *= TRAIT_TASTE.get(t, {}).get(a, 1.0)
        pool.append((w, a))
    out = []
    while pool:                                        # a weighted order, not just a first pick
        pick = random.choices(pool, weights=[w for w, _ in pool])[0]
        pool.remove(pick)
        out.append(pick[1])
    return out


def _hint(c, mode, case):
    label = case["subject"].get("label") or "what is on your mind"
    age = c.get("age") or 30
    traits = set(c.get("traits") or [])
    drink = " Or a drink, if that is how you cope." if (age >= 21 and traits & DRINKERS and mode == "transcend") else ""
    return {
        "inform": f"Talk it over with someone or find out more about {label}.",
        "distract": "Do something that takes your mind off it -- music, a walk, some company, anything light.",
        "transcend": f"Sit with it: reflect, write it down, meditate or let it out.{drink}",
    }[mode]


def maybe_raise_mitigation(c, world, force=False):
    """Give a character whose focus is low a relieve_worry intention. Returns it, or None."""
    tick = world.get("tick", 0)
    if _has_intention(c) or not wc.active_cases(c):
        return None
    avail = wc.focus_available(c, world)
    if not force and avail > COMFORT_FOCUS:
        return None
    if not force and tick - c.get("_worry_relief_tick", -10 ** 9) < RELIEF_COOLDOWN_TICKS:
        return None
    case = _top_case(c)
    mode = choose_mode(c, world, case)
    from brain.intentions import add_intention
    intention = {
        "type": "relieve_worry", "category": "identity", "priority": MITIGATION_PRIORITY,
        "case_id": case["id"], "mode": mode, "candidates": _candidates(c, world, mode), "tried": [], "tried_tick": tick,
        "reason": f"Worry about {case['subject'].get('label') or 'something'} is taking up so much of your attention "
                  f"({avail}% of your focus is left) that demanding tasks are hard. {_hint(c, mode, case)}",
    }
    add_intention(c, intention)
    return intention


def sync_mitigation(c, world, avail=None):
    """Raise or drop the relieve_worry intention as focus changes."""
    avail = wc.focus_available(c, world) if avail is None else avail
    have = _has_intention(c)
    if have and (avail >= COMFORT_RECOVERED or not wc.active_cases(c)):
        from brain.intentions import remove_intention
        remove_intention(c, "relieve_worry")
    elif not have and avail <= COMFORT_FOCUS:
        maybe_raise_mitigation(c, world)


def strategy_for(c, world, intention):
    """resolve_strategy()'s branch: the next relief activity to try for this intention, or None."""
    tick = world.get("tick", 0)
    tried = intention.setdefault("tried", [])
    if tried and tick - intention.get("tried_tick", tick) > TRIED_RESET_TICKS:
        tried.clear()                                  # everything failed a while ago: try the list again
    age = c.get("age") or 30
    for a in intention.get("candidates", []):
        if a in tried or age < _min_age(a):
            continue
        if not tried:
            intention["tried_tick"] = tick
        tried.append(a)
        return a
    return None


# ---------------------------------------------------------------------------
# relief
# ---------------------------------------------------------------------------

def ease_case(c, case, pct, world, activity, mode):
    tick = world.get("tick", 0)
    f = max(0.0, 1.0 - pct / 100.0)
    case["expires"] = tick + int(max(0, case["expires"] - tick) * f)
    case["severity"] = round(case["severity"] * f, 2)
    case["focus_cost"] = wc._focus_cost(case["severity"])
    case["eased_until"] = tick + EASED_FOR_TICKS
    case.setdefault("mitigated_by", []).append({"tick": tick, "activity": activity, "mode": mode, "reduced_pct": pct})
    case["mitigated_by"] = case["mitigated_by"][-6:]
    if case["severity"] < wc.MIN_SEVERITY:
        wc.close_case(c, case["id"], world, status="resolved", reason="eased")


def apply_relief(c, world, activity_type):
    """Apply the relief an activity gives, if it gives any. Returns the cases it eased."""
    spec = relief_spec(world, activity_type)
    cases = wc.active_cases(c)
    if not spec or not cases:
        return []
    if (c.get("age") or 30) < spec.get("min_age", 0):
        return []
    mode = spec["mode"]
    pct = spec.get("reduce_pct", BASE_REDUCE[mode])
    if mode == "inform":
        tags = {t.lower() for t in spec.get("area_tags", [])}
        hit = [cs for cs in cases if tags and (tags & {t.lower() for t in cs.get("tags", [])} or cs["subject"].get("ref") in tags)]
        targets = hit or [max(cases, key=lambda cs: cs["focus_cost"])]
    else:
        targets = cases
    eased = []
    for case in targets:
        ease_case(c, case, pct, world, activity_type, mode)
        eased.append(case["id"])
    c["_worry_relief_tick"] = world.get("tick", 0)
    wc.update_focus(c, world)
    sync_mitigation(c, world)
    try:
        from brain.memory import store_memory
        store_memory(c, f"I feel a little lighter after {activity_type.replace('_', ' ')}.", importance=0.2,
                     tags=["worry_case", "relief"], tick=world.get("tick", 0), source="internal")
    except Exception:
        pass
    return eased


def on_activity_completed(data, world):
    c = world.get("characters", {}).get(data.get("character_id"))
    if not c:
        return
    try:
        apply_relief(c, world, data.get("activity_type"))
    except Exception as exc:
        print(f"[worry_relief] relief failed: {exc!r}")


subscribe("activity_completed", on_activity_completed)
