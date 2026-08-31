"""
systems/excuses.py

Explanation, excuse, and lie engine.

Characters prefer to avoid lying when they can achieve privacy through
vagueness instead. The decision tree is:

  1. Can I give a vague-but-true answer?  → do that first
  2. Is the follow-up question crossing my privacy threshold?
     - No concern about the detail → disclose truthfully
     - Yes → try "strategic omission" ("just a friend", "somewhere nearby")
  3. If authority presses AND the detail would cause real trouble:
     - Honest character: refuses / deflects ("I'd rather not say")
     - Deceptive character: lies

Lies are stored on the character as active_lies[] so:
  - Inconsistent stories can be detected later
  - Authority suspicion rises with vagueness + repeat pattern
  - Caught lying → conditioning event (shame + resentment + trust damage)

Announcement methods (any one satisfies announce_departure contract):
  verbal    — tell an authorized_recipient face-to-face
  sibling   — tell any authorized sibling / trusted household member
  note      — leave a written note on a prop tagged "message_surface"
  text      — send SMS to any authorized_recipient
  call      — phone call to any authorized_recipient
"""

import random
import uuid

# ── Privacy threshold ─────────────────────────────────────────────────────

def _privacy_score(c):
    """0-1: how much this character guards personal info."""
    base  = 0.40
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    if "private" in traits or "reserved" in traits:
        base += 0.25
    if "introverted" in traits:
        base += 0.10
    if "open" in traits or "extroverted" in traits:
        base -= 0.15
    if "secretive" in traits:
        base += 0.30
    return max(0.0, min(1.0, base))


def _honesty_score(c):
    """0-1: how much this character prefers truth over lies."""
    base  = 0.60
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    if "honest" in traits or "sincere" in traits:
        base += 0.25
    if "deceptive" in traits or "manipulative" in traits:
        base -= 0.35
    if "easily_embarrassed" in traits:
        base += 0.10   # shame from lying > shame from truth
    return max(0.0, min(1.0, base))


def _detail_is_sensitive(detail_type, c, world, authority=None):
    """
    True if revealing this detail would cause unwanted friction with authority.

    Two independent reasons to treat a detail as sensitive:
      A. It involves something genuinely secret (hidden affair, secret plan)
      B. The authority is known/believed to disapprove of the person or place
         — even if they couldn't actually stop it, the character wants to
           avoid the lecture, the look, the drama.

    The character doesn't need a rule to be broken — just anticipating
    a bad reaction is enough to trigger vagueness or a lie.
    """
    chars     = world.get("characters", {})
    auth_id   = (authority["id"] if isinstance(authority, dict) else authority) if authority else None
    auth_char = chars.get(auth_id) if auth_id else None

    # ── A: Genuinely secret content ──────────────────────────────────────
    for s in c.get("secrets", []):
        if s.get("status", "hidden") == "hidden":
            if detail_type in ("who", "where"):
                return True
    # Romantic meeting with someone hidden
    if detail_type == "who":
        for cid, rel in c.get("relationships", {}).items():
            if any(lbl in rel.get("labels", [])
                   for lbl in ("affair", "secret_crush", "forbidden_attraction")):
                return True

    # ── B: Authority's known disapproval ─────────────────────────────────
    if not auth_char:
        return False

    target_id = c.get("move_target", {}).get("target_id")

    if detail_type == "who":
        if target_id:
            if _authority_disapproves_of_person(auth_char, target_id, world):
                return True
        return False

    if detail_type == "what":
        # Check the explicit activity
        activity_type = c.get("activity", {}).get("type", "")
        if activity_type and _authority_disapproves_of_activity(auth_char, activity_type, world):
            return True
        # Check implied activity from company (associative risk)
        if target_id:
            implied = _infer_activity_from_company(c, target_id, world)
            if implied and _authority_disapproves_of_activity(auth_char, implied, world):
                return True
        return False

    if detail_type == "where":
        dest   = c.get("move_target", {})
        loc_id = dest.get("target_id") if dest else None
        if loc_id:
            return _authority_disapproves_of_place(auth_char, loc_id, world)
        return False

    return False


# Known risky behavior tags — if a person has these habits,
# authority who knows them will object to them as company
RISKY_BEHAVIOR_TAGS = {
    "heavy_drinker", "drug_user", "party_animal", "troublemaker",
    "criminal_record", "gang_affiliated", "reckless", "violent_history",
    "drops_out", "bad_influence",
}

# Activity types that many parents/authorities object to
OBJECTIONABLE_ACTIVITIES = {
    "drink_alcohol", "drink_heavily", "smoke", "use_drugs",
    "illegal_activity", "fight", "gamble", "party_late",
    "street_race", "trespass", "vandalize",
}


def _authority_disapproves_of_person(authority, person_id, world):
    """
    True if authority has a known poor opinion of the person being visited,
    OR if that person is associated with risky activities the authority objects to.
    The chain: authority knows person → person has risky habits →
    meeting person implies risky activity → both "who" and "what" become sensitive.
    """
    chars    = world.get("characters", {})
    person   = chars.get(person_id, {})

    # Authority's direct relationship to that person
    auth_rel   = authority.get("relationships", {}).get(person_id, {})
    warmth     = auth_rel.get("warmth",     50)
    trust_val  = auth_rel.get("trust",      50)
    labels     = auth_rel.get("labels",     [])
    rep_score  = auth_rel.get("reputation", 50)

    if warmth    < 30: return True
    if trust_val < 25: return True
    if rep_score < 30: return True
    if any(lbl in labels for lbl in ("enemy", "disliked", "banned", "dangerous")):
        return True

    # Person's own reputation / known behaviors
    person_rep   = person.get("reputation", {})
    person_tags  = set(person.get("behavior_tags", []) +
                       person.get("traits", []) +
                       person.get("personality_traits", []))

    if person_rep.get("moral_standing",  100) < 35: return True
    if person_rep.get("reliability",     100) < 30: return True
    if person_rep.get("criminal_record", False):     return True

    # Associative risk: does authority know this person tends to get into trouble?
    # Check if authority has observed or heard about this person's risky habits
    known_risky = person_tags & RISKY_BEHAVIOR_TAGS
    if known_risky:
        # Only matters if authority actually knows this person
        familiarity = auth_rel.get("familiarity", 0)
        if familiarity > 15:   # authority knows them enough to have formed an opinion
            return True

    return False


def _authority_disapproves_of_activity(authority, activity_type, world):
    """
    True if the activity itself is something the authority objects to,
    regardless of who else is involved.
    """
    if activity_type in OBJECTIONABLE_ACTIVITIES:
        return True
    # Authority's personal objection list
    objected = set(authority.get("objected_activities", []))
    if activity_type in objected:
        return True
    return False


def _infer_activity_from_company(c, person_id, world):
    """
    If c is going to meet person_id, infer what activity they're likely doing
    based on that person's known habits and their mutual history.
    Returns an activity_type string or None.
    """
    chars  = world.get("characters", {})
    person = chars.get(person_id, {})
    tags   = set(person.get("behavior_tags", []) + person.get("traits", []))

    # Check shared activity history
    rel = c.get("relationships", {}).get(person_id, {})
    common_activities = rel.get("common_activities", [])
    if common_activities:
        return common_activities[-1]   # most recent shared activity

    # Infer from person's tags
    if "heavy_drinker" in tags or "party_animal" in tags:
        return "drink_alcohol"
    if "drug_user" in tags:
        return "use_drugs"
    if "troublemaker" in tags or "gang_affiliated" in tags:
        return "illegal_activity"

    return None


def _authority_disapproves_of_place(authority, location_id, world):
    """
    True if authority is known to dislike or forbid this location.
    """
    forbidden = authority.get("forbidden_locations", [])
    if location_id in forbidden:
        return True
    locations = world.get("locations", {})
    loc = locations.get(location_id, {})
    loc_type = loc.get("type", "")
    # Common places authority might object to
    disliked_types = authority.get("disliked_location_types", [])
    if loc_type in disliked_types:
        return True
    # Default: some location types raise flags regardless
    if loc_type in ("bar", "nightclub", "gambling_den", "adult_venue"):
        age = authority.get("age", 30)
        if age < 18:
            return False  # young authority, less likely to care
        return True
    return False


# ── Announcement content generation ──────────────────────────────────────

def generate_announcement(c, world, method="verbal", audience_id=None):
    """
    Generate an announcement string using the vague-truth strategy.
    Returns {"text": str, "vagueness": float 0-1, "is_lie": False}
    """
    cal       = world.get("calendar", {})
    hour      = cal.get("hour", 12)
    dest      = c.get("move_target", {})
    dest_name = _guess_destination_label(c, dest, world)
    privacy   = _privacy_score(c)

    # Build vague or specific destination phrase
    if privacy > 0.6 or not dest_name:
        dest_phrase = random.choice(["out for a bit", "running an errand", "just stepping out"])
    elif privacy > 0.3:
        dest_phrase = dest_name   # e.g. "the store", "school"
    else:
        dest_phrase = dest_name

    # Time phrase
    if hour < 12:
        time_phrase = "this morning"
    elif hour < 17:
        time_phrase = "this afternoon"
    else:
        time_phrase = "tonight"

    texts = [
        f"Heading out {time_phrase}.",
        f"Going {dest_phrase}.",
        f"Just letting you know I'm going out.",
        f"I'll be {dest_phrase} for a while.",
    ]
    text = random.choice(texts)

    # Add return estimate if low-privacy character
    if privacy < 0.4:
        text += " " + random.choice(["Back soon.", "Won't be long.", "Back by later."])

    return {"text": text, "vagueness": privacy, "is_lie": False}


def generate_excuse(c, authority, question_type, world):
    """
    Called when authority asks a follow-up question ("Which friend?", "Where exactly?").
    Returns {"text": str, "vagueness": float, "is_lie": bool, "lie_detail": dict|None}

    Decision tree:
      1. Is the detail sensitive?
         - No  → give truthful detail
      2. Can I omit / deflect?
         - honesty > 0.5 → try vague deflection first
      3. If forced and detail is sensitive:
         - honesty > 0.7 → refuse: "I'd rather not say"
         - else          → lie
    """
    # Sociopaths are pathological liars with exactly one honesty
    # exception -- the partner they're running the abusive relationship
    # with (systems/sociopathy.py). Bypasses the normal sensitivity/
    # honesty tree entirely rather than just nudging it, but still
    # resolves through the SAME _generate_lie()/_record_lie() pipeline
    # every other lie in this file uses.
    authority_id = authority["id"] if isinstance(authority, dict) else authority
    try:
        from systems.sociopathy import is_sociopath, controlled_partner_id
        if is_sociopath(c) and authority_id != controlled_partner_id(c, world):
            lie_text, lie_truth = _generate_lie(c, question_type, authority, world)
            lie_entry = _record_lie(c, question_type, lie_text, lie_truth, authority_id, world)
            return {"text": lie_text, "vagueness": 0.0, "is_lie": True, "lie_detail": lie_entry}
    except Exception:
        pass

    privacy   = _privacy_score(c)
    honesty   = _honesty_score(c)
    sensitive = _detail_is_sensitive(question_type, c, world, authority=authority)

    # Not sensitive at all — just answer honestly
    if not sensitive:
        detail = _get_true_detail(c, question_type, world)
        return {"text": detail, "vagueness": 0.0, "is_lie": False, "lie_detail": None}

    # Sensitive detail — try vagueness first
    if honesty > 0.45:
        vague_text = _vague_deflection(question_type, c)
        if vague_text:
            return {"text": vague_text, "vagueness": 0.7, "is_lie": False, "lie_detail": None}

    # Authority is pressing and detail is truly sensitive — must choose
    if honesty > 0.70:
        # Refuse outright
        refusals = [
            "I'd rather not say.",
            "Does it matter?",
            "It's just a private thing.",
            "Just a friend, okay?",
        ]
        return {"text": random.choice(refusals), "vagueness": 0.9,
                "is_lie": False, "lie_detail": None}

    # Lie
    lie_text, lie_truth = _generate_lie(c, question_type, authority, world)
    lie_entry = _record_lie(c, question_type, lie_text, lie_truth,
                            authority["id"] if isinstance(authority, dict) else authority,
                            world)
    return {"text": lie_text, "vagueness": 0.0, "is_lie": True, "lie_detail": lie_entry}


def _vague_deflection(question_type, c):
    """Return a vague-but-non-lie deflection for the question type."""
    templates = {
        "who":   ["Just a friend.", "Someone from school.", "You don't know them.", "A mate."],
        "where": ["Just nearby.", "Not far.", "Around the area.", "Doesn't matter."],
        "what":  ["Nothing much.", "Just catching up.", "Hanging out.", "Personal stuff."],
        "when":  ["Not too long.", "Back before late.", "Shouldn't be long."],
    }
    options = templates.get(question_type, [])
    return random.choice(options) if options else None


def _get_true_detail(c, question_type, world):
    """Return the actual truthful detail for the given question type.

    A character with an active cover persona (systems/persona.py --
    burglary/PI-infiltration/production-front work) answers "who"/"what"
    from that pre-committed cover instead of their real identity/
    activity, so the answer stays consistent every time they're asked --
    it still flows through the SAME generate_excuse()/_record_lie()/
    check_lie_consistency() pipeline below, just with a different
    starting "truth" to lie from."""
    persona = c.get("active_persona")
    if persona:
        if question_type == "who":
            return persona["name"]
        if question_type == "what":
            return persona["occupation_label"]

    chars = world.get("characters", {})
    if question_type == "where":
        dest = c.get("move_target", {})
        return _guess_destination_label(c, dest, world) or "just out"
    if question_type == "who":
        # Return name of first character being visited
        target_id = c.get("move_target", {}).get("target_id")
        if target_id and target_id in chars:
            return chars[target_id].get("name", "a friend")
        return "no one in particular"
    if question_type == "what":
        activity = c.get("activity", {})
        return activity.get("type", "nothing much").replace("_", " ")
    if question_type == "when":
        return "not sure exactly"
    return "I don't know"


def _generate_lie(c, question_type, authority, world):
    """
    Fabricate a lie for the given question type.
    Returns (lie_text, actual_truth).
    """
    actual = _get_true_detail(c, question_type, world)
    chars  = world.get("characters", {})

    if question_type == "who":
        # Pick a plausible cover name — someone they know platonically
        cover = None
        for oid, rel in c.get("relationships", {}).items():
            labels = rel.get("labels", [])
            if any(l in labels for l in ("friend", "classmate", "colleague")):
                other = chars.get(oid)
                if other:
                    cover = other.get("name")
                    break
        lie_name = cover or "Jamie"
        return f"{lie_name}.", actual

    if question_type == "where":
        safe_places = ["the library", "the park", "the mall", "school", "a café"]
        cover_place = random.choice(safe_places)
        return f"{cover_place}.", actual

    if question_type == "what":
        return random.choice(["Just studying.", "Hanging out.", "Getting some air."]), actual

    if question_type == "when":
        return "Not long, I promise.", actual

    return "I'm not sure.", actual


def _record_lie(c, question_type, lie_text, actual_truth, authority_id, world):
    """Store the lie so consistency can be checked later."""
    entry = {
        "id":           f"lie_{uuid.uuid4().hex[:6]}",
        "question_type": question_type,
        "lie_text":     lie_text,
        "actual_truth": actual_truth,
        "told_to":      [authority_id],
        "tick":         world.get("tick", 0),
        "detected":     False,
    }
    c.setdefault("active_lies", []).append(entry)
    c["active_lies"] = c["active_lies"][-20:]
    return entry


def _guess_destination_label(c, dest, world):
    """Try to infer a human-readable label for where the character is going."""
    target_id = dest.get("target_id") if dest else None
    if not target_id:
        return None
    locations = world.get("locations", {})
    if target_id in locations:
        return locations[target_id].get("name")
    chars = world.get("characters", {})
    if target_id in chars:
        return f"to see {chars[target_id].get('name', 'someone')}"
    return None


# ── Lie detection ─────────────────────────────────────────────────────────

def check_visible_lies_for_observer(observer, world):
    """
    The "authority hears a conflicting account (gossip, observation)" hook
    check_lie_consistency()'s own docstring describes, but which nothing
    ever called — lies were recorded in active_lies but never actually
    checked against reality. Built directly on brain/perception.py's
    visible_people: if the observer can literally see someone who told
    them a lie, that's a real, in-perception "observation" moment worth
    checking. Call once per perception cadence tick (sim_loop.py), same
    cadence perceive() already runs on.
    """
    chars = world.get("characters", {})

    for p in observer.get("perception", {}).get("visible_people", []):

        liar = chars.get(p["id"])

        if not liar or not liar.get("active_lies"):
            continue

        if any(observer["id"] in lie.get("told_to", [])
               for lie in liar["active_lies"] if not lie.get("detected")):

            check_lie_consistency(liar, observer, world)


# ── Witnessed hostility ──────────────────────────────────────────────────

_WITNESSED_OFFENSE_WINDOW_TICKS = 15


def check_witnessed_hostility_for_observer(observer, world):
    """
    Same shape as check_visible_lies_for_observer() directly above —
    scans the observer's own perception.visible_people (real, in-perception
    evidence, not omniscient world state) for anyone who just committed a
    hostile action (systems/hostile_actions.py tags
    actor["recent_hostile_acts"] on every punch/kick/shove/grab/hold/
    threaten). Tags the observer's own witnessed_offenses (mirrors
    nudity_perception.py's nudity_witnessed cooldown-dict pattern) so the
    same act doesn't re-tag every tick. Does not create an incident itself
    — resolve_hostile_action() already creates one on every hit/fumble,
    reachable by proximity via context_builder.py::_build_incident_context;
    this function's job is purely the observer's own awareness/narrative
    (fuels build_narrative()'s witnessed-offense line and lets the
    observer's "confront" double as intervening).
    """
    chars = world.get("characters", {})
    tick = world.get("tick", 0)
    witnessed = observer.setdefault("witnessed_offenses", {})

    for p in observer.get("perception", {}).get("visible_people", []):
        offender = chars.get(p["id"])
        if not offender or offender["id"] == observer["id"]:
            continue

        for act in offender.get("recent_hostile_acts", []):
            if tick - act.get("tick", -9999) > _WITNESSED_OFFENSE_WINDOW_TICKS:
                continue
            last_tagged = witnessed.get(offender["id"], -9999)
            if tick - last_tagged <= _WITNESSED_OFFENSE_WINDOW_TICKS:
                continue  # already tagged this same window, don't re-fire
            witnessed[offender["id"]] = tick
            break


def check_lie_consistency(c, authority, world):
    """
    Called when authority hears a conflicting account (gossip, observation).
    If a stored lie is contradicted, fire caught_lying event.
    Returns list of detected lies.
    """
    detected = []
    auth_id  = authority["id"] if isinstance(authority, dict) else authority

    for lie in c.get("active_lies", []):
        if lie.get("detected"):
            continue
        if auth_id not in lie.get("told_to", []):
            continue

        # Simple check: if character's current location contradicts the lie
        if lie["question_type"] == "where":
            cur_loc = c.get("current_location") or c.get("building_id", "")
            lied_dest = lie["lie_text"].lower().rstrip(".")
            if lied_dest and lied_dest not in str(cur_loc).lower():
                # Could be detected — probabilistic
                if random.random() < 0.55:
                    lie["detected"] = True
                    _handle_caught_lying(c, authority, lie, world)
                    detected.append(lie)

    return detected


def _handle_caught_lying(c, authority, lie, world):
    """Consequences when a lie is caught."""
    auth_id = authority["id"] if isinstance(authority, dict) else authority
    chars   = world.get("characters", {})
    auth    = chars.get(auth_id) if isinstance(auth_id, str) else authority

    # Trust damage
    rel = c.setdefault("relationships", {}).setdefault(auth_id, {})
    rel["trust"]      = max(0, rel.get("trust", 50) - 20)
    rel["resentment"] = min(100, rel.get("resentment", 0) + 10)

    # Conditioning — caught lying → shame + resentment
    try:
        from systems.conditioning import apply_reinforcement
        apply_reinforcement(c, "caught_lying", "shame", world,
                            authority_id=auth_id, is_positive=False)
        apply_reinforcement(c, "caught_lying", "resentment_authority", world,
                            authority_id=auth_id, is_positive=False)
    except Exception:
        pass

    # Authority suspicion rises — routed through systems/worries.py
    # (was auth["suspicion_of"], a field nothing else ever read; this
    # is a real, confirmed event so the bump is much bigger than the
    # ambiguous routine-deviation signal in perception.py).
    if auth:
        try:
            from systems.worries import bump_suspicion
            bump_suspicion(
                auth, c["id"], 0.3, "caught_lying",
                f"caught {c.get('name', c['id'])} in a lie: \"{lie.get('lie_text', 'something')}\"",
                world,
            )
        except Exception:
            pass

    # Emit event for grievance system
    try:
        from core.event_bus import emit
        emit("lie_detected", {
            "liar_id":      c["id"],
            "authority_id": auth_id,
            "lie":          lie["lie_text"],
            "truth":        lie["actual_truth"],
            "tick":         world.get("tick", 0),
        })
    except Exception:
        pass


# ── Announcement method router ────────────────────────────────────────────

def get_authorized_recipients(c, world):
    """
    Return list of character IDs that can receive a departure announcement
    for this character, drawn from their announce_departure contracts.
    """
    recipients = set()
    chars = world.get("characters", {})
    for cid in c.get("social_contract_ids", []):
        contract = world.get("social_contracts", {}).get(cid, {})
        if contract.get("status") != "active":
            continue
        for term in contract.get("terms", []):
            if (term.get("party") == c["id"] and
                    term.get("check_type") == "announce_departure"):
                params = term.get("params", {})
                # Primary authority
                auth_id = contract.get("authority_id")
                if auth_id:
                    recipients.add(auth_id)
                # Additional authorized recipients (siblings, etc.)
                for rid in params.get("authorized_recipients", []):
                    recipients.add(rid)
    return list(recipients)


def choose_announcement_method(c, world):
    """
    Decide which announcement method to use based on who's present.
    Returns: "verbal" | "sibling" | "note" | "text" | "call" | None
    Priority: verbal → sibling → note → text/call (if nobody around)
    """
    recipients  = get_authorized_recipients(c, world)
    chars       = world.get("characters", {})
    cur_loc     = c.get("current_location") or c.get("building_id")

    # Check who's present and is an authorized recipient
    present = [
        rid for rid in recipients
        if rid in chars and
        (chars[rid].get("current_location") or chars[rid].get("building_id")) == cur_loc
    ]

    if present:
        # Is any of them a sibling vs. primary authority?
        for rid in present:
            rel = c.get("relationships", {}).get(rid, {})
            labels = rel.get("labels", [])
            if any(l in labels for l in ("parent", "guardian", "spouse")):
                return "verbal"
        # Sibling or other authorized person
        return "sibling"

    # Nobody around — check for note surface prop in location
    if _has_note_surface(cur_loc, world):
        return "note"

    # Fallback: text or call
    phone = c.get("phone", {})
    if phone.get("battery", 0) > 10:
        return "text"   # prefer text; LLM can upgrade to call

    return None   # no method available


def _has_note_surface(location_id, world):
    """True if there is a prop tagged 'message_surface' in this location."""
    for prop in world.get("placed_props", {}).values():
        if prop.get("location_id") == location_id:
            tpl_id = prop.get("template_id", "")
            tpl    = world.get("defs", {}).get("prop_templates", {}).get(tpl_id, {})
            if "message_surface" in tpl.get("tags", []):
                return True
    return False


def leave_note(c, world, text=None):
    """
    Character leaves a physical note in their current location.
    Sets _left_note_this_tick and stores the note in world["notes"].
    """
    if text is None:
        announcement = generate_announcement(c, world, method="note")
        text = announcement["text"]

    cur_loc = c.get("current_location") or c.get("building_id")
    note = {
        "id":          f"note_{uuid.uuid4().hex[:6]}",
        "author_id":   c["id"],
        "location_id": cur_loc,
        "text":        text,
        "tick":        world.get("tick", 0),
        "read_by":     [],
    }
    world.setdefault("notes", []).append(note)
    c["_left_note_this_tick"] = True
    c["_announced_departure"] = True

    # Fire incidental speech bubble showing the action
    try:
        from systems.incidental_speech import fire_incidental
        fire_incidental(c, "announce", f"[leaves a note: \"{text}\"]", world)
    except Exception:
        pass

    return note


# =========================================================
# APPROACH PRETEXT (systems/curiosity.py)
# =========================================================
# "Why am I walking over here" for a curiosity-driven investigation --
# distinct from every other function in this module, which all answer
# "where was I / what was I doing" questions about a character's OWN
# past whereabouts. This is a forward-looking self-justification a
# curious character gives themselves before approaching a commotion,
# same templated-lines shape as _vague_deflection() above.

_APPROACH_PRETEXT_TEMPLATES = {
    "incident": [
        "I should check that's nothing serious.",
        "Just making sure everyone's alright over there.",
        "I'll go see what's going on.",
        "Better take a look, just in case.",
    ],
    "ambient": [
        "What was that?",
        "I should see what that noise was.",
        "Let me take a look outside.",
        "I wonder what's going on out there.",
    ],
}


def generate_approach_pretext(c, world, source_kind, source_label=None):
    """source_kind: "incident" | "ambient" -- picks the matching
    templated line. source_label (e.g. an incident type or sound name)
    is accepted for future flavor but not required by the current
    templates."""
    options = _APPROACH_PRETEXT_TEMPLATES.get(source_kind, _APPROACH_PRETEXT_TEMPLATES["ambient"])
    return random.choice(options)
