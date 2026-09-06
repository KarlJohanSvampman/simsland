"""
systems/sexual_release.py

What a spiking character (systems/libido.py) actually does about it, in
priority order: spouse/partner first (if one exists and appears
willing, via intimacy.py's real propose_act/recipient_decision
negotiation engine), then a friends-with-benefits/booty-call attempt to
a past intimate contact, and only once both are exhausted/denied does
masturbation -- gated on real privacy -- become the fallback. Each
denied step feeds systems/libido.py::note_denied()'s stress tracking,
which is what Phase D's prostitute-hiring desire eventually watches.

No fantasy-target selection and no persisted "friends with benefits"
label -- FWB eligibility is computed live from intimacy_stage/labels
already tracked by intimacy.py/brain/relationships.py, per this
feature's Confirmed Decisions.
"""

import random

from systems.libido import is_spiking, note_denied, note_released

FWB_MIN_INTIMACY_STAGE = 3
FWB_ATTEMPT_CAP = 2

_MASTURBATE_COMPATIBLE_PROP_KEYWORDS = (
    "bed", "sofa", "armchair", "shower", "toilet", "computer_desk",
)

# Duration: 5-15 min normally, 15-45 min if intoxicated (alcohol+drugs).
MASTURBATE_MINUTES_SOBER = (5, 15)
MASTURBATE_MINUTES_INTOXICATED = (15, 45)
INTOXICATION_THRESHOLD = 0.15


def _masturbate_duration_ticks(c):
    state = c.get("intoxication_state", {})
    intox = min(1.0, state.get("alcohol_level", 0.0) + state.get("drug_level", 0.0))
    lo, hi = MASTURBATE_MINUTES_INTOXICATED if intox > INTOXICATION_THRESHOLD else MASTURBATE_MINUTES_SOBER
    return round(random.uniform(lo, hi) * 60)  # 1 tick == 1 sim-second


def attempt_release(c, world):
    """Call when a spiking character's seek_sexual_release desire is
    being acted on. Returns True if release was achieved this call."""
    if not is_spiking(c):
        return False

    if _try_partner(c, world):
        return True
    if _try_booty_call(c, world):
        return True
    return _try_masturbate(c, world)


# ── 1. Spouse/partner ───────────────────────────────────────────────────

def _find_partner(c, world):
    chars = world.get("characters", {})
    for oid, rel in c.get("relationships", {}).items():
        if oid not in chars:
            continue
        if "partner" in rel.get("labels", []) or "spouse" in rel.get("labels", []):
            return chars[oid]
    return None


def _try_partner(c, world):
    partner = _find_partner(c, world)
    if not partner:
        return False
    return _propose_and_resolve(c, partner, world)


# ── 2. Friends with benefits / booty call ────────────────────────────────

def _fwb_candidates(c, world):
    """Past intimate contacts (real history, not currently exclusive) --
    computed live from intimacy_stage/labels, no stored FWB state."""
    chars = world.get("characters", {})
    scored = []
    for oid, rel in c.get("relationships", {}).items():
        if oid not in chars:
            continue
        labels = rel.get("labels", [])
        if "partner" in labels or "spouse" in labels:
            continue
        if rel.get("intimacy_stage", 0) >= FWB_MIN_INTIMACY_STAGE:
            scored.append((oid, rel.get("attraction", 0)))
    scored.sort(key=lambda pair: -pair[1])
    return [chars[oid] for oid, _ in scored[:FWB_ATTEMPT_CAP]]


def _booty_call_accepted(c, contact, world):
    """Lightweight willingness roll over a text -- same inputs
    intimacy.py::recipient_decision() weighs (attraction/trust/casual_
    reluctance), simplified since there's no act-tier negotiation over a
    text message the way there is once actually together."""
    rel = contact.get("relationships", {}).get(c["id"], {})
    attraction = rel.get("attraction", 0) / 100.0
    trust = rel.get("trust", 0) / 100.0
    profile = contact.get("attraction_profile") or {}
    casual_reluctance = profile.get("casual_reluctance", 0.5)
    willingness = attraction * 0.6 + trust * 0.2 - casual_reluctance * 0.3
    return random.random() < max(0.02, min(0.9, willingness))


def _bring_together(c, contact, world):
    """No dedicated cross-map walk-to-a-character primitive exists in
    movement.py today (confirmed -- it's per-tile locomotion speed only,
    not a pathfinding API) -- direct relocation, same simplification
    other off-screen NPC placement in this codebase already uses."""
    contact["x"] = c.get("x")
    contact["y"] = c.get("y")
    contact["building_id"] = c.get("building_id")
    contact["room_id"] = c.get("room_id")


def _try_booty_call(c, world):
    for contact in _fwb_candidates(c, world):
        if not _booty_call_accepted(c, contact, world):
            continue
        _bring_together(c, contact, world)
        if _propose_and_resolve(c, contact, world):
            return True
    return False


# ── Shared negotiation resolution (spouse + FWB paths) ───────────────────

def _propose_and_resolve(c, target, world):
    """Kicks off the FIRST act of a scene -- always a foreplay-phase act
    (systems/intercourse_session.py's phased redesign expects a scene to
    always start there), and picked randomly rather than deterministically
    so the same pair doesn't always open the same way. Everything past
    this first act is handled autonomously by
    intercourse_session.py::tick_intercourse_sessions(), not repeat calls
    into this cascade."""
    import random as _random
    from systems.intimacy import get_available_acts, propose_act, recipient_decision, respond_to_proposal, execute_act

    acts = get_available_acts(c, target, world, phase="foreplay")
    if not acts:
        note_denied(c, world)
        return False

    act_id = _random.choice(acts)["id"]
    result = propose_act(c, target, act_id, world)
    if not result.get("ok"):
        note_denied(c, world)
        return False

    decision = recipient_decision(target, c, world) or "reject"
    respond_to_proposal(target, c, decision if decision != "conditional" else "reject", world)

    if decision == "accept":
        # respond_to_proposal only records the negotiation outcome -- an
        # accepted proposal doesn't perform itself. This was a real,
        # pre-existing gap: nothing else in the codebase ever called
        # execute_act() for this cascade, so a spouse/FWB "accept" never
        # actually resulted in anything happening.
        execute_act(c, target, act_id, world)
        note_released(c, world)
        note_released(target, world)
        return True

    note_denied(c, world)
    return False


# ── 3. Masturbation (last resort, gated on real privacy) ────────────────

def _find_masturbate_prop(c, world):
    props = world.get("props", {})
    prop_list = props.values() if isinstance(props, dict) else props
    building_id = c.get("building_id")
    for prop in prop_list:
        if prop.get("occupied_by"):
            continue
        if building_id and prop.get("building_id") != building_id:
            continue
        template = prop.get("template") or ""
        if any(k in template for k in _MASTURBATE_COMPATIBLE_PROP_KEYWORDS):
            return prop
    return None


def _preferred_aid_item(c):
    """Gendered device preference (no fantasy target, per this feature's
    revision) -- male characters prefer an owned fleshlight, female
    characters an owned vibrator, falling back to the existing dildo/
    strapon items either sex could already own. Returns the item dict,
    or None (masturbate works with no item at all)."""
    from systems.personal_items import get_item_by_template
    order = (["fleshlight", "dildo_small", "dildo_medium", "dildo_large", "strapon"]
             if c.get("sex") == "male" else
             ["vibrator", "dildo_small", "dildo_medium", "dildo_large", "strapon"])
    for template_id in order:
        item = get_item_by_template(c, template_id)
        if item:
            return item
    return None


def _try_masturbate(c, world):
    from systems.action_router import _co_present_characters
    if _co_present_characters(c, world):
        # No privacy -- denied, not attempted. See
        # nudity_perception.py for what happens if attempted anyway.
        note_denied(c, world)
        return False

    prop = _find_masturbate_prop(c, world)
    if not prop:
        note_denied(c, world)
        return False

    from systems.action_router import _scaffold
    act = _scaffold(c, world, "interact", target_id=prop.get("id"), interaction="masturbate",
                     duration=_masturbate_duration_ticks(c))
    aid = _preferred_aid_item(c)
    if aid:
        aid["location"] = "held"
        act["state"]["item_id"] = aid.get("id")
    c["activity"] = act
    prop["occupied_by"] = c["id"]
    note_released(c, world)
    return True
