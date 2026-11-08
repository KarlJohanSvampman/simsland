"""
systems/life_comparison.py

Characters compare themselves (and, via belongings/household net worth,
their household) against real contacts across several dimensions --
belongings, spouse-vs-my-ideal, children-vs-my-ideal, appearance, work,
intelligence, social life, expectations-fulfillment, and personality-
vs-admired-traits. Jealousy (rel["jealousy"]) only ever accumulates on
dimensions where the OTHER scores better -- never the observer's own
wins -- and decays otherwise, same shape as every other relationship-
stat tracker built this session (grievances, favor_frustration,
creeped_out).

Deliberately NOT a rewrite of attraction.py::check_envy_events() --
that stays scoped to romantic/status envy exactly as it already is;
this is a separate, broader "how does their life stack up" comparison.
"""

import random

from systems.attraction import compute_ideal_match

_EDU_RANK = {
    "none": 0, "none_completed": 0, "preschool": 0, "primary": 0,
    "middle_school": 0, "high_school": 1, "trade_school": 2, "certificate": 2,
    "associate": 3, "bachelor": 4, "master": 5, "doctorate": 6, "professional": 6,
}

JEALOUSY_GAIN_PER_DIMENSION = 1.5
JEALOUSY_DECAY_RATE         = 0.97   # per day, mirrors grievances.py's DECAY_RATE shape
JEALOUSY_GRIEVANCE_THRESHOLD = 60.0
MAX_ENVY_GRIEVANCES_PER_PERSON = 5   # a pile of hundreds of small envy grievances against one person helps no one
COMPARISON_SAMPLE_SIZE      = 4      # bounded scan, mirrors check_envy_events' contact scope


def _kin_ids(c, kinship):
    return [oid for oid, rel in c.get("relationships", {}).items() if rel.get("kinship") == kinship]


def _spouse_of(c, world):
    chars = world.get("characters", {})
    for oid in _kin_ids(c, "spouse"):
        if oid in chars:
            return chars[oid]
    return None


def _children_of(c, world):
    chars = world.get("characters", {})
    return [chars[oid] for oid in _kin_ids(c, "child") if oid in chars]


def _avg_ideal_match(c, people, ideal_key):
    if not people:
        return None
    scores = [compute_ideal_match(c, p, ideal_key=ideal_key) for p in people]
    return sum((s["trait"] + s["physical"]) / 2.0 for s in scores) / len(scores)


def _expectations_ratio(c):
    exps = c.get("expectations", {})
    if not exps:
        return None
    streak = sum(e.get("streak", 0) for e in exps.values())
    missed = sum(e.get("missed_count", 0) for e in exps.values())
    return streak / (streak + missed + 1)


def _dimension_closeness_multiplier(self_val, other_val):
    """"The more equal circumstances the more interesting" -- a narrow gap
    (near-equal standing) scales jealousy gain UP toward 1.5x, a wide gap
    scales it DOWN toward 0.5x. Losing badly to someone in a completely
    different league stings less than narrowly losing to a near-peer."""
    try:
        self_val = float(self_val)
        other_val = float(other_val)
    except (TypeError, ValueError):
        return 1.0
    denom = max(abs(self_val), abs(other_val), 1e-6)
    relative_gap = abs(other_val - self_val) / denom
    return max(0.5, min(1.5, 1.5 - relative_gap))


def _worst_dimension(favorable_dims):
    """The single most-unfavorable dimension (biggest relative gap) among
    the ones that favor the other person -- what a crossed-threshold Want
    intention (see _apply_comparison) actually names."""
    best_key, best_gap = None, -1.0
    for k, d in favorable_dims.items():
        try:
            self_val, other_val = float(d["self"]), float(d["other"])
            gap = abs(other_val - self_val) / max(abs(self_val), abs(other_val), 1e-6)
        except (TypeError, ValueError):
            gap = 0.5
        if gap > best_gap:
            best_gap, best_key = gap, k
    return best_key


def _admired_traits_score(c, other):
    ideal = c.get("ideal_partner")
    if not ideal:
        return None
    desired = set(ideal.get("desired_traits", []))
    undesired = set(ideal.get("undesired_traits", []))
    total = len(desired) + len(undesired)
    if not total:
        return None
    other_traits = set(other.get("traits", []) + other.get("personality_traits", []))
    hits = len(other_traits & desired) - len(other_traits & undesired)
    return 0.5 + 0.5 * (hits / total)


def compare_lives(c, other, world):
    """Returns {dimension: {"self": x, "other": x, "favors_other": bool}}
    -- only dimensions where BOTH sides have real, comparable data are
    included (a dimension neither side can observe/measure isn't
    silently defaulted into a comparison)."""
    dims = {}

    c_wealth = c.get("wealth", 0) or 0
    o_wealth = other.get("wealth", 0) or 0
    dims["belongings"] = {"self": c_wealth, "other": o_wealth, "favors_other": o_wealth > c_wealth}

    c_hid, o_hid = c.get("household_id"), other.get("household_id")
    if c_hid and o_hid and c_hid != o_hid:
        households = world.get("households", {})
        c_hh_wealth = households.get(c_hid, {}).get("wealth", 0) or 0
        o_hh_wealth = households.get(o_hid, {}).get("wealth", 0) or 0
        dims["household_wealth"] = {
            "self": c_hh_wealth, "other": o_hh_wealth,
            "favors_other": o_hh_wealth > c_hh_wealth,
        }

    c_spouse_match = _avg_ideal_match(c, [_spouse_of(c, world)] if _spouse_of(c, world) else [], "ideal_partner")
    o_spouse_match = _avg_ideal_match(c, [_spouse_of(other, world)] if _spouse_of(other, world) else [], "ideal_partner")
    if c_spouse_match is not None and o_spouse_match is not None:
        dims["spouse"] = {"self": c_spouse_match, "other": o_spouse_match, "favors_other": o_spouse_match > c_spouse_match}

    c_kids, o_kids = _children_of(c, world), _children_of(other, world)
    if c_kids and o_kids:
        c_child_match = _avg_ideal_match(c, c_kids, "ideal_child")
        o_child_match = _avg_ideal_match(c, o_kids, "ideal_child")
        dims["children"] = {"self": c_child_match, "other": o_child_match, "favors_other": o_child_match > c_child_match}

    c_attr, o_attr = c.get("attractiveness"), other.get("attractiveness")
    c_attr = 0.5 if c_attr is None else c_attr
    o_attr = 0.5 if o_attr is None else o_attr
    dims["appearance"] = {"self": c_attr, "other": o_attr, "favors_other": o_attr > c_attr}

    if c.get("employed") and other.get("employed"):
        c_wage, o_wage = c.get("hourly_wage", 0) or 0, other.get("hourly_wage", 0) or 0
        dims["work"] = {"self": c_wage, "other": o_wage, "favors_other": o_wage > c_wage}

    c_edu = _EDU_RANK.get(c.get("education", "none"), 0)
    o_edu = _EDU_RANK.get(other.get("education", "none"), 0)
    dims["intelligence"] = {"self": c_edu, "other": o_edu, "favors_other": o_edu > c_edu}

    c_social, o_social = len(c.get("relationships", {})), len(other.get("relationships", {}))
    dims["social_life"] = {"self": c_social, "other": o_social, "favors_other": o_social > c_social}

    c_exp, o_exp = _expectations_ratio(c), _expectations_ratio(other)
    if c_exp is not None and o_exp is not None:
        dims["expectations_fulfillment"] = {"self": c_exp, "other": o_exp, "favors_other": o_exp > c_exp}

    o_admired = _admired_traits_score(c, other)
    if o_admired is not None:
        # No symmetric "self" score here -- this is c's own admired-
        # traits yardstick applied to `other`, not a two-sided measure.
        dims["personality_vs_admired"] = {"self": 0.5, "other": o_admired, "favors_other": o_admired > 0.5}

    return dims


def _apply_comparison(c, other, world, trigger=None):
    rel = c.setdefault("relationships", {}).setdefault(other["id"], {})
    dims = compare_lives(c, other, world)
    favorable = {k: d for k, d in dims.items() if d["favors_other"]}

    if favorable:
        # Trait amplification: reuses envy.py's existing 0.3-2.0 trait-
        # weighted multiplier -- a jealous/greedy/vain/materialistic/
        # ambitious/competitive/envious character reacts far more strongly
        # to losing a comparison than one with none of those traits.
        from systems.envy import _envy_multiplier
        trait_mult = _envy_multiplier(c)
        gain = sum(
            JEALOUSY_GAIN_PER_DIMENSION * trait_mult
            * _dimension_closeness_multiplier(d["self"], d["other"])
            for d in favorable.values()
        )
        rel["jealousy"] = min(100.0, rel.get("jealousy", 0.0) + gain)
    else:
        rel["jealousy"] = max(0.0, rel.get("jealousy", 0.0) * JEALOUSY_DECAY_RATE)

    if rel["jealousy"] >= JEALOUSY_GRIEVANCE_THRESHOLD:
        jealousy_at_threshold = rel["jealousy"]

        from systems.grievances import add_grievance
        if not at_envy_cap(c, other["id"]):
            add_grievance(c, other["id"], "life_envy", world,
                          details={"favorable_dimensions": list(favorable.keys()),
                                   **({"trigger": trigger["detail"], "trigger_kind": trigger["kind"]} if trigger else {})})

        # Losing a comparison doesn't just breed resentment -- it creates a
        # real, acted-on urge to keep up with the single most-unfavorable
        # dimension that tipped it over. Rides the existing active_intentions
        # -> _sec_intentions narration path, no new context_builder wiring.
        worst_dim = _worst_dimension(favorable)
        if worst_dim:
            from brain.intentions import add_intention
            label = worst_dim.replace("_", " ")
            other_name = other.get("name", "someone")
            add_intention(c, {
                "type":      f"keep_up_with:{worst_dim}",
                "category":  "impulse",
                "priority":  int(min(80, 30 + jealousy_at_threshold * 0.5)),
                "target_id": other["id"],
                "reason":    f"You noticed {other_name}'s {label} and it's bugging you -- "
                             f"you want that for yourself.",
                "source":    "life_comparison",
            })

        rel["jealousy"] = 0.0  # vented via the grievance/confrontation pipeline

    return dims


def at_envy_cap(c, other_id):
    return sum(1 for g in c.get("grievances", []) if g.get("caused_by") == other_id and g.get("event_type") == "life_envy") >= MAX_ENVY_GRIEVANCES_PER_PERSON


def trim_envy_grievances(c):
    """Keep only the newest few envy grievances against each person (older worlds had hundreds). Returns how many were dropped."""
    seen, keep, dropped = {}, [], 0
    for g in sorted(c.get("grievances", []), key=lambda g: -g.get("tick", 0)):
        if g.get("event_type") == "life_envy":
            seen[g["caused_by"]] = seen.get(g["caused_by"], 0) + 1
            if seen[g["caused_by"]] > MAX_ENVY_GRIEVANCES_PER_PERSON:
                dropped += 1
                continue
        keep.append(g)
    if dropped:
        c["grievances"] = keep
    return dropped


def tick_life_comparison(world):
    """A sweep over a sample of every character's contacts. NOT scheduled any more: comparing lives happens when
    something brings the other person to mind (on_reminded_event below). Kept for tools and tests that want one pass."""
    characters = world.get("characters", {})
    for c in characters.values():
        # Confirmed live bug (froze the whole simulation): the workplace-NPC
        # skip further down only guarded `other`, never `c` itself -- so the
        # moment a colleague NPC existed (systems/workplace_npc.py: bare
        # shape, no attractiveness/wealth/...), it got picked as the
        # comparing character and compare_lives() crashed on
        # `float > None`, uncaught inside tick(), before anything persisted.
        if (c.get("is_offscreen") or c.get("is_workplace_npc")
                or c.get("age_group") in ("child", "teen")):
            continue
        trim_envy_grievances(c)
        contact_ids = list(c.get("relationships", {}).keys())
        if not contact_ids:
            continue
        sample = random.sample(contact_ids, min(COMPARISON_SAMPLE_SIZE, len(contact_ids)))
        for oid in sample:
            other = characters.get(oid)
            # Workplace NPCs (systems/workplace_npc.py) can be real
            # c["relationships"] entries (a boss/colleague) but are a
            # deliberately bare shape -- no wealth/attractiveness/body/
            # etc. -- so they're not a real candidate for a life
            # comparison, which reads exactly those fields.
            if not other or other.get("id") == c.get("id") or other.get("is_workplace_npc"):
                continue
            _apply_comparison(c, other, world)


# =========================================================
# BROUGHT TO MIND -- the only way a comparison happens now
# =========================================================
# Live (2026-11-06): "envy over how the other one lives" was logged against the same person every 10-30 sim-minutes,
# day and night: the comparison ran in a job meant to be daily that ran every 24 s, against a random sample of
# contacts nobody had seen. Now it runs when the other person is actually brought to mind -- seen, mentioned, or a
# visit -- at most once per pair per REMINDER_COOLDOWN_SECONDS, and what brought it up is recorded with it.

from core.clock import HOUR

REMINDER_COOLDOWN_SECONDS = 2 * HOUR
REMINDERS_KEPT = 20


def _can_compare(c):
    return not (c.get("is_offscreen") or c.get("is_workplace_npc") or c.get("is_service_worker")
                or c.get("age_group") in ("child", "teen") or c.get("alive") is False)


def _place(world, c):
    """Where c is, in words, for the record: their room's name, else the building, else 'outside'."""
    room = c.get("room_id")
    if room:
        return str(room).split(":")[-1].rstrip("_0123456789").replace("_", " ").strip() or "inside"
    return "outside" if not c.get("_in_building", c.get("building_id")) else "indoors"


def on_reminded(c, other, world, kind, detail):
    """Something brought `other` to `c`'s mind. Compares their lives unless the pair compared within the cooldown.
    Returns True when a comparison happened."""
    if not c or not other or c is other or not _can_compare(c) or other.get("is_workplace_npc"):
        return False
    if other.get("id") not in (c.get("relationships") or {}):
        return False                                  # a stranger's life is not one they measure themselves against
    tick = world.get("tick", 0)
    last = (c.setdefault("_envy_reminded", {})).get(other["id"])
    if last is not None and tick - last < REMINDER_COOLDOWN_SECONDS:
        return False
    c["_envy_reminded"][other["id"]] = tick
    trigger = {"kind": kind, "detail": detail, "tick": tick}
    rel = c["relationships"][other["id"]]
    rel.setdefault("envy_reminders", []).append(trigger)
    del rel["envy_reminders"][:-REMINDERS_KEPT]
    trim_envy_grievances(c)
    _apply_comparison(c, other, world, trigger=trigger)
    return True


def _mentions(world, text, exclude):
    """Characters named in `text` (full name or first name, whole words), except those in `exclude`."""
    import re
    low = f" {str(text or '').lower()} "
    found = []
    for oid, o in (world.get("characters") or {}).items():
        if oid in exclude or o.get("is_workplace_npc"):
            continue
        for n in (o.get("name"), o.get("first_name")):
            if n and re.search(rf"(?<![a-z]){re.escape(n.lower())}(?![a-z])", low):
                found.append(o)
                break
    return found


def on_reminded_event(world, event, data):
    """core/flow.py: person_entered_view, speech_spoken, guest.visit_started."""
    chars = world.get("characters") or {}
    if event == "person_entered_view":
        c, other = chars.get(data.get("observer_id")), chars.get(data.get("subject_id"))
        if c and other:
            on_reminded(c, other, world, "saw", f"saw {other.get('name', 'them')} ({_place(world, c)})")
    elif event == "speech_spoken":
        speaker, listener = chars.get(data.get("character_id")), chars.get(data.get("target_id"))
        line = str(data.get("utterance") or "")
        quote = line if len(line) <= 90 else line[:87] + "..."
        for m in _mentions(world, line, {data.get("character_id"), data.get("target_id")}):
            for c in (speaker, listener):
                if c:
                    who = "they" if c is speaker else speaker.get("name", "someone") if speaker else "someone"
                    on_reminded(c, m, world, "mentioned", f'{m.get("name")} came up: {who} said "{quote}"')
    elif event == "guest.visit_started":
        guest = chars.get(data.get("guest_id"))
        hosts = [chars[h] for h in data.get("host_ids") or [] if h in chars]
        for h in hosts:
            if guest:
                on_reminded(guest, h, world, "visiting", f"visiting {h.get('name', 'them')}'s home")
                on_reminded(h, guest, world, "visited", f"{guest.get('name', 'someone')} came over")
