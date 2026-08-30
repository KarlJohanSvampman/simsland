"""
systems/whereabouts.py

General, not story-specific: whenever a character has an intention or
conversation goal targeting a specific other character and doesn't
currently know where that target is, encountering someone who's a
REGULAR contact of the target (read off the target's OWN relationships
-- high familiarity/interaction_count) usually warrants pausing the
current activity to ask: "have you seen X?" -- and to relay a concrete
reason if one exists (an overdue item loan, an unreciprocated favor),
falling back to a generic "have them get in touch" otherwise.

contact["_pending_relay_messages"] = [{"to", "from", "message", "tick"}]
-- delivered for real the next time that contact actually encounters
the target (deliver_pending_relays()), not resolved instantly.
"""

import random

REGULAR_CONTACT_FAMILIARITY  = 40
REGULAR_CONTACT_INTERACTIONS = 5
ASK_WHEREABOUTS_CHANCE       = 0.7   # "most times" per the user's own framing, not always
RELAY_COOLDOWN_TICKS         = 3600  # don't re-ask the same contact about the same target constantly


def find_regular_contacts_of(target_id, world):
    target = world.get("characters", {}).get(target_id)
    if not target:
        return []
    chars = world.get("characters", {})
    return [
        oid for oid, rel in target.get("relationships", {}).items()
        if oid in chars and (
            rel.get("familiarity", 0) >= REGULAR_CONTACT_FAMILIARITY
            or rel.get("interaction_count", 0) >= REGULAR_CONTACT_INTERACTIONS
        )
    ]


def _pending_target(c, world):
    """First intention/conversation-goal target_id c is actively
    seeking. active_intentions already carries target_id for social
    intentions (flirt/visit_person/...); conversation goals carrying a
    story_id (systems/conversation_goals.py's share_story) resolve to
    whichever character that story's best_audience names first."""
    for intention in c.get("active_intentions", []):
        tid = intention.get("target_id")
        if tid and tid in world.get("characters", {}):
            return tid
    return None


def _reason_for_seeking(c, target, world):
    """Concrete reason for wanting to reach target, if one exists --
    an item c lent them that's now overdue, or a favor they still owe
    (systems/favors.py's ledger) -- otherwise None, which falls back to
    a generic "get in touch" message. No standalone peer-to-peer cash-
    IOU mechanic exists in this codebase beyond those two, so "money
    owed" is covered only insofar as it was tracked as a favor."""
    try:
        from systems.personal_items import get_inventory
        for item in get_inventory(target):
            loan = item.get("loan")
            if (loan and loan.get("owner_id") == c["id"]
                    and loan.get("borrower_id") == target["id"]
                    and world.get("tick", 0) >= loan.get("due_tick", 0)):
                return f"tell them I need my {item.get('name', 'item')} back"
    except Exception:
        pass

    rel = c.get("relationships", {}).get(target["id"], {})
    if any(not f.get("reciprocated") for f in rel.get("favors", [])):
        return "tell them they still owe me one"

    return None


def check_ask_whereabouts(c, world):
    """Perception-tick hook (see agent_loop.py). Returns True if it
    fired (and paused c's current activity to do so)."""
    target_id = _pending_target(c, world)
    if not target_id:
        return False

    visible_ids = {p["id"] for p in (c.get("perception") or {}).get("visible_people", [])}
    if target_id in visible_ids:
        return False  # target is right here -- no need to ask around

    regulars = set(find_regular_contacts_of(target_id, world))
    candidate_id = next((pid for pid in visible_ids if pid in regulars), None)
    if not candidate_id:
        return False

    cooldowns = c.setdefault("_whereabouts_ask_cooldown", {})
    last = cooldowns.get(f"{candidate_id}:{target_id}", 0)
    tick = world.get("tick", 0)
    if tick - last < RELAY_COOLDOWN_TICKS:
        return False
    if random.random() >= ASK_WHEREABOUTS_CHANCE:
        return False

    contact = world.get("characters", {}).get(candidate_id)
    target = world.get("characters", {}).get(target_id)
    if not contact or not target:
        return False

    cooldowns[f"{candidate_id}:{target_id}"] = tick

    # Pausing the current activity takes priority, per the user's own
    # framing ("should most times warrant pausing any current activity").
    c["activity"] = None

    target_name = target.get("name", target_id)
    try:
        from systems.incidental_speech import fire_incidental
        fire_incidental(c, "ask", f"Have you seen {target_name}?", world, target_id=candidate_id)
    except Exception:
        pass

    reason = _reason_for_seeking(c, target, world)
    message = reason if reason else f"{c.get('name', c['id'])} is looking for you -- have them call or text."

    contact.setdefault("_pending_relay_messages", []).append({
        "to":      target_id,
        "from":    c["id"],
        "message": message,
        "tick":    tick,
    })
    return True


def deliver_pending_relays(c, world):
    """Call when c actually perceives someone -- delivers any relay
    message c is carrying FOR that person, for real, not instantly at
    ask-time."""
    relays = c.get("_pending_relay_messages")
    if not relays:
        return
    visible_ids = {p["id"] for p in (c.get("perception") or {}).get("visible_people", [])}
    still_pending = []
    for relay in relays:
        target_id = relay["to"]
        if target_id in visible_ids and target_id in world.get("characters", {}):
            try:
                from systems.incidental_speech import fire_incidental
                fire_incidental(c, "inform", relay["message"], world, target_id=target_id)
            except Exception:
                pass
        else:
            still_pending.append(relay)
    c["_pending_relay_messages"] = still_pending
