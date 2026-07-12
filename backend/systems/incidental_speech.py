"""
systems/incidental_speech.py

Non-blocking speech acts that fire as speech bubbles without interrupting
a character's current activity or movement.

Types:
  announce      — "I'm heading to the store, back by 6."
  inquiry       — "Where are you going?"
  micro_request — "Can you hand me those keys?"
  micro_accept  — "Sure, here you go."
  micro_decline — "Sorry, can't right now."
  inform        — "Just so you know, dinner's at 7."
  reminder      — "Remember, you're due home by 10."

These fire through the existing apply_speech() / speech bubble pipeline.
They do NOT set c["activity"].

Departure protocol:
  On each tick, scan for characters whose location changed (_departed_this_tick).
  - If they have an announce_departure contract → fire announce.
  - If an authority figure is co-located and no announcement came → fire inquiry.
"""

import random

# How many ticks before the same incidental speech can repeat between same pair
INCIDENTAL_COOLDOWN = 30

# Probability a "responsible" character spontaneously announces departure
# (even without a contract, e.g. adults with family/partner)
SPONTANEOUS_ANNOUNCE_PROB = {
    "parent":          0.80,
    "spouse":          0.75,
    "partner":         0.65,
    "roommate":        0.30,
    "family":          0.40,
    "friend_close":    0.20,
}

# Probability an authority notices and inquires if no announcement was made
INQUIRY_PROB = {
    "parent":          0.85,
    "spouse":          0.55,
    "guardian":        0.90,
}


# ── Core speech firing ────────────────────────────────────────────────────

def fire_incidental(character, speech_type, text, world, target_id=None):
    """
    Set a speech bubble on character without touching their activity.
    Uses the same current_speech field as apply_speech() but is called
    directly here so we don't import action_router (circular).
    """
    text = (text or "").strip()
    if not text:
        return

    tick = world.get("tick", 0)
    character["current_speech"] = {
        "utterance":       text,
        "speech_act":      speech_type,
        "topic":           "incidental",
        "target":          target_id,
        "expires_at_tick": tick + 6,
        "incidental":      True,
    }
    character.setdefault("speech_log", []).append({
        "tick":      tick,
        "utterance": text,
        "target":    target_id,
        "type":      speech_type,
    })
    character["speech_log"] = character["speech_log"][-20:]


def _on_cooldown(c, other_id, world):
    tick = world.get("tick", 0)
    last = c.get("_incidental_last", {}).get(other_id, -999)
    return tick - last < INCIDENTAL_COOLDOWN


def _mark_cooldown(c, other_id, world):
    c.setdefault("_incidental_last", {})[other_id] = world.get("tick", 0)


# ── Departure observation ─────────────────────────────────────────────────

def _get_announcement_text(char, world):
    """Generate a contextual departure announcement."""
    name     = char.get("name", "I")
    cal      = world.get("calendar", {})
    hour     = cal.get("hour", 12)
    dest_loc = char.get("current_location", "")
    locations = world.get("locations", {})
    loc_name  = locations.get(dest_loc, {}).get("name", "out")

    phrases = [
        f"Heading out to {loc_name}.",
        f"Just leaving for {loc_name}.",
        f"Going to {loc_name}, back later.",
    ]
    if hour < 12:
        phrases.append(f"Off to {loc_name} this morning.")
    elif hour < 17:
        phrases.append(f"Popping out to {loc_name}.")
    else:
        phrases.append(f"Out for the evening — going to {loc_name}.")

    return random.choice(phrases)


def _get_inquiry_text(observer, departing, world):
    """Generate a contextual inquiry about departure."""
    dep_name = departing.get("name", "you")
    phrases  = [
        f"Where are you off to, {dep_name}?",
        f"Where are you going?",
        f"Hey — where are you headed?",
        f"Are you going somewhere?",
    ]
    return random.choice(phrases)


def _get_curfew_reminder_text(authority, subject, contract, world):
    """Generate a curfew reminder when subject is leaving."""
    params    = {}
    for term in contract.get("terms", []):
        if term.get("check_type") == "curfew":
            params = term.get("params", {})
    deadline  = params.get("deadline_hour", 22)
    sub_name  = subject.get("name", "you")
    return random.choice([
        f"Be home by {deadline}:00, okay?",
        f"Remember — {deadline}:00, {sub_name}.",
        f"Don't be late. Home by {deadline}.",
    ])


def tick_incidental_speech(world):
    """
    Per-tick: scan for departure events and fire incidental speech.
    Called from sim_loop after movement is processed.
    """
    chars  = world.get("characters", {})
    tick   = world.get("tick", 0)

    # Build location-to-occupants map for quick lookup
    loc_map = {}
    for cid, c in chars.items():
        loc = c.get("current_location")
        if loc:
            loc_map.setdefault(loc, []).append(cid)

    # 1. Process characters who departed this tick
    for cid, c in chars.items():
        if not c.get("_departed_this_tick"):
            continue

        prev_loc = c.get("_previous_location")
        cur_loc  = c.get("current_location")

        # Who was at the previous location and is still there?
        former_cohabitants = [
            chars[oid] for oid in loc_map.get(prev_loc, [])
            if oid != cid and oid in chars
        ]

        has_authority_contract = _has_announce_contract(c, world)
        already_announced      = c.get("_announced_departure", False)

        # A: Contract obligation to announce
        if has_authority_contract and not already_announced:
            _perform_departure_announcement(c, former_cohabitants, world)

        # B: Spontaneous announcement (responsible adult — no contract needed)
        elif not already_announced and former_cohabitants:
            announce_prob = _spontaneous_announce_probability(c, former_cohabitants)
            if random.random() < announce_prob:
                _perform_departure_announcement(c, former_cohabitants, world)

        # C: No announcement made → authorities may inquire
        if not c.get("_announced_departure"):
            for obs in former_cohabitants:
                rel = c.get("relationships", {}).get(obs["id"], {})
                labels = rel.get("labels", [])
                for label, prob in INQUIRY_PROB.items():
                    if label in labels and random.random() < prob:
                        if not _on_cooldown(obs, cid, world):
                            text = _get_inquiry_text(obs, c, world)
                            fire_incidental(obs, "inquiry", text, world, target_id=cid)
                            _mark_cooldown(obs, cid, world)
                        break

    # 2. Process pending micro-request queue
    _tick_micro_requests(chars, world)


def _perform_departure_announcement(c, former_cohabitants, world):
    """
    Choose the best available announcement method and execute it.
    Priority: verbal to authority → verbal to sibling/authorized →
              leave note → text → call
    """
    try:
        from systems.excuses import choose_announcement_method, generate_announcement, leave_note
        method = choose_announcement_method(c, world)
    except Exception:
        method = "verbal"

    chars = world.get("characters", {})

    if method in ("verbal", "sibling"):
        # Find the best recipient present
        try:
            from systems.excuses import get_authorized_recipients
            authorized = set(get_authorized_recipients(c, world))
        except Exception:
            authorized = set()

        target = None
        # Prefer primary authority (parent/guardian/spouse) if verbal
        if method == "verbal":
            for obs in former_cohabitants:
                rel = c.get("relationships", {}).get(obs["id"], {})
                if any(lbl in rel.get("labels", [])
                       for lbl in ("parent", "guardian", "spouse")):
                    target = obs
                    break
        # Fall back to any authorized recipient present
        if not target:
            for obs in former_cohabitants:
                if obs["id"] in authorized:
                    target = obs
                    break
        if not target and former_cohabitants:
            target = former_cohabitants[0]

        try:
            from systems.excuses import generate_announcement
            result = generate_announcement(c, world, method=method,
                                          audience_id=target["id"] if target else None)
            text = result["text"]
        except Exception:
            text = _get_announcement_text(c, world)

        target_id = target["id"] if target else None
        fire_incidental(c, "announce", text, world, target_id=target_id)
        c["_announced_departure"] = True

        # Curfew reminder back from authority
        if target and not _on_cooldown(target, c["id"], world):
            curfew_c = _get_curfew_contract(c, target, world)
            if curfew_c:
                remind = _get_curfew_reminder_text(target, c, curfew_c, world)
                fire_incidental(target, "reminder", remind, world, target_id=c["id"])
                _mark_cooldown(target, c["id"], world)

    elif method == "note":
        try:
            from systems.excuses import leave_note, generate_announcement
            result = generate_announcement(c, world, method="note")
            leave_note(c, world, text=result["text"])
        except Exception:
            c["_announced_departure"] = True

    elif method in ("text", "call"):
        # Queue phone action in intention_queue — executed by action_router next tick
        try:
            from systems.excuses import get_authorized_recipients, generate_announcement
            recipients = get_authorized_recipients(c, world)
            if recipients:
                result = generate_announcement(c, world, method=method)
                c.setdefault("intention_queue", []).append({
                    "type":      "phone_send_text" if method == "text" else "phone_call",
                    "target_id": recipients[0],
                    "message":   result["text"],
                    "reason":    "departure_announcement",
                    "priority":  7,
                    "tick":      world.get("tick", 0),
                })
                c["_announced_departure"] = True
        except Exception:
            pass


def _has_announce_contract(c, world):
    """Does this character have an active announce_departure contract?"""
    for cid in c.get("social_contract_ids", []):
        contract = world.get("social_contracts", {}).get(cid, {})
        if contract.get("status") != "active":
            continue
        for term in contract.get("terms", []):
            if (term.get("party") == c["id"] and
                    term.get("check_type") == "announce_departure"):
                return True
    return False


def _get_curfew_contract(subject, authority, world):
    """Return active curfew contract between subject and authority, or None."""
    for cid in subject.get("social_contract_ids", []):
        contract = world.get("social_contracts", {}).get(cid, {})
        if contract.get("status") != "active":
            continue
        if authority["id"] not in contract.get("parties", []):
            continue
        for term in contract.get("terms", []):
            if term.get("check_type") == "curfew":
                return contract
    return None


def _find_authority(subject, cohabitants, world):
    """Return first cohabitant who has authority over subject, or None."""
    for obs in cohabitants:
        rel = subject.get("relationships", {}).get(obs["id"], {})
        labels = rel.get("labels", [])
        if any(lbl in labels for lbl in ("parent", "guardian", "spouse")):
            return obs
    return None


def _spontaneous_announce_probability(c, cohabitants):
    """Probability a character spontaneously announces based on relationship labels."""
    max_prob = 0.0
    for obs in cohabitants:
        rel = c.get("relationships", {}).get(obs["id"], {})
        for label in rel.get("labels", []):
            prob = SPONTANEOUS_ANNOUNCE_PROB.get(label, 0.0)
            max_prob = max(max_prob, prob)
    return max_prob


# ── Micro-request engine ──────────────────────────────────────────────────

def queue_micro_request(requester, target_id, request_text, world):
    """Queue a non-blocking request from requester to target."""
    world.setdefault("micro_request_queue", []).append({
        "requester_id": requester["id"],
        "target_id":    target_id,
        "text":         request_text,
        "tick":         world.get("tick", 0),
        "resolved":     False,
    })
    fire_incidental(requester, "micro_request", request_text, world,
                    target_id=target_id)


def _tick_micro_requests(chars, world):
    """Auto-resolve pending micro-requests on the next tick."""
    queue = world.get("micro_request_queue", [])
    tick  = world.get("tick", 0)
    keep  = []
    for req in queue:
        if req.get("resolved"):
            continue
        # Expire after 3 ticks
        if tick - req.get("tick", 0) > 3:
            continue
        target = chars.get(req["target_id"])
        if not target:
            continue
        # Simple acceptance: accept if not sleeping, not in argument
        activity_type = target.get("activity", {}).get("type", "")
        if activity_type in ("sleep", "fight", "flee"):
            reply = random.choice(["Not right now.", "Give me a sec."])
            fire_incidental(target, "micro_decline", reply, world,
                            target_id=req["requester_id"])
        else:
            reply = random.choice(["Sure!", "Here you go.", "Of course."])
            fire_incidental(target, "micro_accept", reply, world,
                            target_id=req["requester_id"])
        req["resolved"] = True
    world["micro_request_queue"] = [r for r in queue if not r.get("resolved")]


# ── Departure flag management (call from movement.py) ─────────────────────

def mark_departure(char, previous_location):
    """Call this when movement.py confirms a location change."""
    char["_departed_this_tick"]  = True
    char["_previous_location"]   = previous_location
    char["_announced_departure"] = False


def clear_departure_flags(world):
    """Call at start of each tick to reset one-tick flags."""
    for c in world.get("characters", {}).values():
        c.pop("_departed_this_tick",  None)
        c.pop("_announced_departure", None)
        c.pop("_previous_location",   None)
