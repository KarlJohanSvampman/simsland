import random, uuid
from brain.memory import store_memory


# The standalone, population-wide ambient roll (maybe_generate_shared_
# event, feeding the live event timeline) is argument/conflict ONLY --
# per the user's explicit choice, everyday pleasantries/gossip/neutral
# moments no longer surface there at all; they instead live in the
# richer 5-tier spread below, reused by off-grid trip summaries and
# on-grid hourly household summaries (a much larger real time window
# per roll, so a full spread reads naturally there).
_ENCOUNTER_TIERS = [
    ("argument", 0.5),
    ("conflict", 0.5),
]

# The original 5-tier spread (was _ENCOUNTER_TIERS before the split
# above) -- reused by systems/offgrid.py's trip-return resolution and
# systems/household_summary.py's hourly sweep via maybe_generate_
# summary_linked_event() below. Argument/conflict kept deliberately
# rare (5% each, per the user's explicit ask) since a summary already
# covers a much larger real window than the standalone timeline's
# one-off ambient roll.
_SUMMARY_ENCOUNTER_TIERS = [
    ("neutral",     0.70),
    ("pleasant",    0.10),
    ("unpleasant",  0.10),
    ("argument",    0.05),
    ("conflict",    0.05),
]
_NEGATIVE_TIERS = {"unpleasant", "argument", "conflict"}

# Each negative tier trends toward a higher severity than the last
# (Unpleasant < Argument < Conflict), but all 5 severities stay reachable
# for any of them via the random component below -- a "Minor Conflict"
# and an "Intense Unpleasant" exchange are both real, if less likely,
# outcomes.
_TIER_SEVERITY_BASE = {"unpleasant": 0.0, "argument": 15.0, "conflict": 30.0}

# Real grievance weight applied to BOTH participants once a negative-tier
# encounter resolves -- the actual, lasting consequence ("use the conflict
# pipeline where applicable" per the user's own framing: not the full
# multi-tick conflict object for this one-shot ambient event, but the
# SAME real grievance ledger every other conflict-adjacent system in this
# codebase already writes to and reads from).
_SEVERITY_GRIEVANCE_WEIGHT = {"Minor": 2.0, "Low": 5.0, "Medium": 10.0, "High": 18.0, "Intense": 28.0}
_TIER_GRIEVANCE_EVENT_TYPE = {"unpleasant": "disrespected", "argument": "insulted", "conflict": "threatened"}


def _location_name(world, location_id):
    if not location_id:
        return None
    building = next((b for b in world.get("buildings", []) if b.get("id") == location_id), None)
    return (building or {}).get("name") or (building or {}).get("template")


def _roll_encounter_tier(weights=None):
    weights = weights or _ENCOUNTER_TIERS
    r = random.random()
    upto = 0.0
    for tier, weight in weights:
        upto += weight
        if r <= upto:
            return tier
    return weights[-1][0]


def _roll_severity(a, b, tier):
    """Grounded in the REAL, existing grievance ledger between these two
    (both directions -- either could be the one who feels wronged) --
    real prior history makes a fresh dispute correctly land harder, not
    just a fresh LLM-invented severity disconnected from anything real.
    A real random component still lets a genuinely fresh dispute (no
    prior grievance at all) land anywhere on the scale."""
    from systems.grievances import get_grievance_score
    score = get_grievance_score(a, b["id"]) + get_grievance_score(b, a["id"])
    score += _TIER_SEVERITY_BASE.get(tier, 0.0)
    score += random.uniform(0, 20)
    if score < 5:
        return "Minor"
    if score < 15:
        return "Low"
    if score < 30:
        return "Medium"
    if score < 60:
        return "High"
    return "Intense"


def _apply_negative_consequence(a, b, world, tier, severity, subcategory=None):
    from systems.grievances import add_grievance
    weight = _SEVERITY_GRIEVANCE_WEIGHT.get(severity, 5.0)

    if subcategory and subcategory.get("subcategory") == "negative_gossip":
        # Asymmetric -- the person gossiped ABOUT resents the gossiper;
        # the gossiper doesn't symmetrically resent their own target.
        focus_id, source_id = subcategory.get("focus_id"), subcategory.get("source_id")
        focus, source = world["characters"].get(focus_id), world["characters"].get(source_id)
        if focus and source:
            add_grievance(focus, source_id, "witnessed_transgression", world, severity=weight)
        return

    event_type = _TIER_GRIEVANCE_EVENT_TYPE.get(tier, "disrespected")
    # Mutual -- an argument/conflict is felt by both sides, not just
    # whichever one a narrower "offender/victim" framing would pick.
    add_grievance(a, b["id"], event_type, world, severity=weight)
    add_grievance(b, a["id"], event_type, world, severity=weight)


# Sub-categories refine WHAT an encounter is about within its already-
# decided tone -- they never change tier/severity, just the real
# narrative content (and, for gossip/sympathy, who plays which role).
# argument/conflict already carry real, specific content (a genuine
# dispute) and don't get a subcategory roll.
_SUBCATEGORY_WEIGHTS = {
    "neutral":    [("gossip_thirdparty", 1.0)],
    "pleasant":   [("praise", 0.5), ("invitation", 0.5)],
    "unpleasant": [("sympathy", 0.5), ("negative_gossip", 0.5)],
}

_SUBCATEGORY_GOODWILL_EVENT_TYPE = {
    "praise": "complimented",
    "invitation": "spent_quality_time",
    "sympathy": "comforted",
}


def _pick_unrelated_third_party(world, a, b):
    candidates = [c for c in world.get("characters", {}).values()
                  if c["id"] not in (a["id"], b["id"])]
    if not candidates:
        return None
    return random.choice(candidates)["id"]


def _pick_close_contact(character, world):
    """A real close contact of `character` -- a family member (via
    relationship labels) or a close_friend/best_friend designation --
    for a negative_gossip subcategory that targets someone's circle
    rather than themselves directly. Falls back to None (about the
    character themselves) when no such contact exists."""
    close = []
    for oid, rel in character.get("relationships", {}).items():
        if oid not in world.get("characters", {}):
            continue
        if rel.get("designation") in ("close_friend", "best_friend"):
            close.append(oid)
        elif any(l in ("partner", "spouse", "parent", "child", "sibling")
                 for l in rel.get("labels", [])):
            close.append(oid)
    return random.choice(close) if close else None


def _roll_subcategory(tier, a, b, world):
    options = _SUBCATEGORY_WEIGHTS.get(tier)
    if not options:
        return None
    sub = random.choices([o[0] for o in options], weights=[o[1] for o in options], k=1)[0]

    if sub == "gossip_thirdparty":
        return {"subcategory": sub, "about_id": _pick_unrelated_third_party(world, a, b)}
    if sub in ("praise", "invitation"):
        focus, source = random.sample([a, b], 2)
        return {"subcategory": sub, "focus_id": focus["id"], "source_id": source["id"]}
    if sub == "sympathy":
        victim, comforter = random.sample([a, b], 2)
        return {"subcategory": sub, "focus_id": victim["id"], "source_id": comforter["id"]}
    if sub == "negative_gossip":
        target, gossiper = random.sample([a, b], 2)
        about_close_contact = random.random() < 0.4
        about_id = (_pick_close_contact(target, world) if about_close_contact else None) or target["id"]
        return {"subcategory": sub, "focus_id": target["id"], "source_id": gossiper["id"], "about_id": about_id}
    return {"subcategory": sub}


def _apply_positive_consequence(a, b, world, subcategory):
    """praise/invitation/sympathy all write to the new positive ledger
    instead of nothing -- closing the gap grievances already closed for
    negative tiers."""
    from systems.goodwill import add_goodwill
    event_type = _SUBCATEGORY_GOODWILL_EVENT_TYPE.get(subcategory.get("subcategory"))
    if not event_type:
        return
    focus_id, source_id = subcategory.get("focus_id"), subcategory.get("source_id")
    focus = world["characters"].get(focus_id)
    if focus and source_id:
        # The one who was praised/invited/comforted feels goodwill
        # toward the one who did it.
        add_goodwill(focus, source_id, event_type, world)


def create_shared_event(world, participants, tier, location_id=None, severity=None, medium=None):
    """tier: one of _ENCOUNTER_TIERS' real, rolled tone values (neutral/
    pleasant/unpleasant/argument/conflict) -- NOT a location-flavor label
    anymore. severity: one of Minor/Low/Medium/High/Intense, only set for
    a negative tier. medium: None (in-person) | "call" | "text"."""
    characters = world.get("characters", {})
    a = characters.get(participants[0]) if len(participants) == 2 else None
    b = characters.get(participants[1]) if len(participants) == 2 else None
    subcategory = _roll_subcategory(tier, a, b, world) if a and b else None

    event = {
        "id": f"evt_{uuid.uuid4().hex[:8]}", "type": tier, "severity": severity,
        "participants": participants, "location_id": location_id, "tick": world["tick"],
        "medium": medium, "subcategory": subcategory,
    }
    world.setdefault("shared_events", []).append(event)
    events = world.setdefault("events", [])
    events.append(event)
    del events[:-300]  # world["events"] otherwise grows forever

    if medium in ("call", "text") and a and b:
        # A real remote exchange -- generate the whole script once, play
        # it back on realistic timing (systems/scripted_conversations.py),
        # and defer the consequence until it actually concludes, rather
        # than resolving instantly like an in-person encounter.
        from llm.scripted_conversation import generate_conversation_script
        from systems.scripted_conversations import begin_scripted_call, begin_scripted_sms
        script = generate_conversation_script(a, b, tier, world, severity=severity,
                                               medium=medium, subcategory=subcategory)
        if medium == "call":
            begin_scripted_call(world, a, b, script, tier, severity, subcategory)
        else:
            begin_scripted_sms(world, a, b, script, tier, severity, subcategory)
        event["text"] = f"{a['name']} and {b['name']} are exchanging {'a call' if medium == 'call' else 'texts'}."
        event["topic"] = (subcategory or {}).get("subcategory") or tier
        return event

    from llm.shared_event_narration import generate_shared_event_narration
    participant_names = [characters[cid]["name"] for cid in participants if cid in characters]
    narration = generate_shared_event_narration(
        world, event, participant_names, _location_name(world, location_id),
    )
    event["text"] = narration["text"]
    event["topic"] = narration.get("topic")
    # Per the user's explicit ask ("can we get more detail here"): the
    # fuller 2-4 sentence account already exists in narration (this
    # module's own return shape), but only ever got attached to each
    # participant's own memory below -- api/events.py's timeline feed
    # reads straight off this event dict, so it was structurally
    # incapable of ever showing more than the 1-sentence "text", even
    # when narration succeeded. Stamped here too, now that api/events.py
    # actually surfaces it.
    event["detail"] = narration.get("detail")
    event["category"] = narration.get("category")

    for cid in participants:
        c = characters.get(cid)
        if not c:
            continue
        store_memory(
            c, narration["text"], .8,
            ["shared_event", tier] + ([severity.lower()] if severity else []),
            "shared_event", world["tick"], event_id=event["id"],
            detail=narration.get("detail"), topic=narration.get("topic"),
            story_category=narration.get("category"), story_value=.8,
        )

    sub_type = subcategory.get("subcategory") if subcategory else None
    if tier in _NEGATIVE_TIERS:
        if sub_type == "sympathy":
            if a and b:
                _apply_positive_consequence(a, b, world, subcategory)
        elif a and b:
            _apply_negative_consequence(a, b, world, tier, severity, subcategory)
    elif tier == "pleasant" and a and b and subcategory:
        _apply_positive_consequence(a, b, world, subcategory)

    return event


_DESIGNATION_MIN_FOR_NEUTRAL = ("acquaintance", "friend", "close_friend", "best_friend")


def is_reachable(c):
    """Real floor for BOTH in-person and remote pairing -- alive, not
    incapacitated, not asleep, and (if off-grid) has a usable phone.
    Someone unconscious or with a dead phone simply isn't a candidate,
    in person or remotely."""
    if c.get("alive") is False or c.get("posture") == "incapacitated":
        return False
    if c.get("legal", {}).get("status") == "jailed":
        return False
    if (c.get("activity") or {}).get("type") == "sleep":
        return False
    if c.get("off_grid"):
        from systems.personal_items import phone_is_usable
        return phone_is_usable(c)
    return True


def _mutual_grievance_score(a, b):
    from systems.grievances import get_grievance_score
    return get_grievance_score(a, b["id"]) + get_grievance_score(b, a["id"])


def _mutual_goodwill_score(a, b):
    from systems.goodwill import get_goodwill_score
    return get_goodwill_score(a, b["id"]) + get_goodwill_score(b, a["id"])


def _designation(a, b_id):
    rel = a.get("relationships", {}).get(b_id) or {}
    return rel.get("designation", "stranger")


def _real_talkers(a, b):
    """"Do these two characters normally speak" -- reuses
    contact_designation.py's real, hours-based tier ladder as-is rather
    than inventing a second relationship signal."""
    return (_designation(a, b["id"]) in _DESIGNATION_MIN_FOR_NEUTRAL
            or _designation(b, a["id"]) in _DESIGNATION_MIN_FOR_NEUTRAL)


def _find_signal_weighted_pair(world, tier):
    """Tier-first, standing-aware pairing -- replaces pure-proximity-
    random grouping. Every reachable ON-GRID pair is a candidate
    (proximity is no longer required up front; systems/events.py::
    maybe_generate_shared_event derives in-person vs. remote AFTER a
    pair is chosen). Restricted to on-grid characters -- an off-grid
    participant is a different, separate mechanism (a probability-
    driven remote exchange folded into that trip's own summary, not
    this standalone real-time timeline event). Negative tiers weight
    toward real tension (get_grievance_score); pleasant weights toward
    real goodwill; neutral requires only a real, established
    designation (no strangers)."""
    active = [
        c for c in world["characters"].values()
        if is_reachable(c) and not c.get("off_grid")
    ]
    if len(active) < 2:
        return None, None

    if tier in _NEGATIVE_TIERS:
        weight_fn = _mutual_grievance_score
        require_designation = False
    elif tier == "pleasant":
        weight_fn = _mutual_goodwill_score
        require_designation = True
    else:  # neutral
        weight_fn = None
        require_designation = True

    candidates = []
    weights = []
    # Bounded sample of pairs rather than a full O(n^2) scan -- mirrors
    # this session's other population-scale sampling precedents.
    sample = active if len(active) <= 40 else random.sample(active, 40)
    for i, a in enumerate(sample):
        for b in sample[i + 1:]:
            if require_designation and not _real_talkers(a, b):
                continue
            w = weight_fn(a, b) if weight_fn else 1.0
            candidates.append((a, b))
            weights.append(max(w, 0.01))

    if not candidates:
        return None, None
    pair = random.choices(candidates, weights=weights, k=1)[0]
    return pair[0], pair[1]


def maybe_generate_shared_event(world):
    if random.random() > .01:
        return

    # Argument/conflict only (see _ENCOUNTER_TIERS above) -- negative
    # tiers never require a designation, so this only comes up empty
    # when fewer than 2 on-grid characters are reachable at all.
    tier = _roll_encounter_tier()
    a, b = _find_signal_weighted_pair(world, tier)
    if not a:
        return

    severity = _roll_severity(a, b, tier) if tier in _NEGATIVE_TIERS else None
    location_id, medium = _resolve_location_and_medium(a, b, tier)
    create_shared_event(world, [a["id"], b["id"]], tier, location_id, severity, medium=medium)


# ── Summary-linked shared events ────────────────────────────────────────
# A second, separate trigger point (systems/offgrid.py's trip-return
# resolution, systems/household_summary.py's hourly sweep) -- unlike the
# population-wide ambient roll above, this is scoped to ONE character's
# own real contacts (whoever they actually know), using the full 5-tier
# spread (_SUMMARY_ENCOUNTER_TIERS) rather than the argument/conflict-
# only standalone roll. Reuses every real primitive already built above
# (is_reachable, the grievance/goodwill weighting, _resolve_location_and_
# medium, create_shared_event) -- this is a different SOURCE of pairs,
# not a different mechanism.
SUMMARY_EVENT_CHANCE = 0.12


def _find_partner_for_character(c, world, tier):
    characters = world.get("characters", {})
    candidates = [
        characters[cid] for cid in c.get("relationships", {}).keys()
        if cid in characters and is_reachable(characters[cid])
    ]
    if not candidates:
        return None

    if tier in _NEGATIVE_TIERS:
        weight_fn = lambda other: _mutual_grievance_score(c, other)
        require_designation = False
    elif tier == "pleasant":
        weight_fn = lambda other: _mutual_goodwill_score(c, other)
        require_designation = True
    else:  # neutral / unpleasant
        weight_fn = None
        require_designation = True

    weighted, weights = [], []
    for other in candidates:
        if require_designation and not _real_talkers(c, other):
            continue
        weighted.append(other)
        weights.append(max(weight_fn(other) if weight_fn else 1.0, 0.01))

    if not weighted:
        return None
    return random.choices(weighted, weights=weights, k=1)[0]


def maybe_generate_summary_linked_event(c, world, chance=SUMMARY_EVENT_CHANCE):
    """Called once per off-grid trip resolving, and once per on-grid
    household member present during an hourly summary window -- a real
    chance that character had a real (possibly remote) exchange with
    someone during that window, feeding the same create_shared_event()
    pipeline (including a real scripted call/sms when the pair isn't
    co-located, per _resolve_location_and_medium). Returns the created
    event, or None if nothing fired."""
    if not is_reachable(c) or random.random() > chance:
        return None

    tier = _roll_encounter_tier(_SUMMARY_ENCOUNTER_TIERS)
    partner = _find_partner_for_character(c, world, tier)
    if not partner and tier != "neutral":
        tier = "neutral"
        partner = _find_partner_for_character(c, world, tier)
    if not partner:
        return None

    severity = _roll_severity(c, partner, tier) if tier in _NEGATIVE_TIERS else None
    location_id, medium = _resolve_location_and_medium(c, partner, tier)
    return create_shared_event(world, [c["id"], partner["id"]], tier, location_id, severity, medium=medium)


def _location_key(c):
    return c.get("building_id") or ("outdoors", round(c.get("x", 0) / 4), round(c.get("y", 0) / 4))


# Higher-stakes tiers favor a call (more direct, more consequential);
# lower-stakes tiers favor a text -- a documented weighting, not a hard
# rule (a real remote exchange can still land as either).
_MEDIUM_WEIGHTS = {
    "neutral":    {"text": 0.7, "call": 0.3},
    "pleasant":   {"call": 0.6, "text": 0.4},
    "unpleasant": {"text": 0.6, "call": 0.4},
    "argument":   {"call": 0.6, "text": 0.4},
    "conflict":   {"call": 0.7, "text": 0.3},
}


def _resolve_location_and_medium(a, b, tier):
    """Two characters living in the same household always resolve
    face-to-face -- they'll cross paths at home regardless, and calling
    or texting a housemate over an argument that's about to happen at
    home anyway doesn't read as real. Otherwise, both on-grid and
    actually co-located right now -> in-person (today's original
    behavior). Anything else -- different households, not currently
    near each other -- is a real remote encounter (call or text,
    tier-weighted)."""
    same_household = (
        a.get("household_id") is not None
        and a.get("household_id") == b.get("household_id")
    )
    both_on_grid = not a.get("off_grid") and not b.get("off_grid")
    close_now = both_on_grid and _location_key(a) == _location_key(b)
    if same_household or close_now:
        location_id = a.get("building_id") if not a.get("off_grid") else b.get("building_id")
        return location_id, None
    weights = _MEDIUM_WEIGHTS.get(tier, _MEDIUM_WEIGHTS["neutral"])
    medium = random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]
    return None, medium
