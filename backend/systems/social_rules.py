"""
Standing, unilateral social rules — one character's own policy about what
they'll allow others to do (e.g. "household members may borrow my car"),
with per-subject exceptions carved out from precedent (e.g. "not Alex,
not for another two weeks — they crashed it").

Not a two-party contract (see systems/social_contracts.py, which is a
negotiated agreement both sides signed onto) — a rule belongs entirely
to its owner, and the other party is simply expected to know it applies
to them. systems/proposals.py's "request" kind is what actually checks
a request against these rules (see propose_request/resolve_request
call site in action_router.py::_route_propose_request).
"""

import uuid


def ensure_social_rules(c):
    c.setdefault("social_rules", [])
    return c["social_rules"]


def create_rule(owner, topic, scope, target_id=None, default="allow",
                 priority=50, reason="", world=None):
    """scope="individual" requires target_id (a character id).
    scope="household" defaults to the owner's own household when no
    target_id is given."""
    if scope == "individual":
        if not target_id:
            return None
        scope_ids = [target_id]
    elif scope == "household":
        scope_ids = [target_id] if target_id else [owner.get("household_id")]
        if not scope_ids[0]:
            return None
    else:
        return None

    rule = {
        "id":         uuid.uuid4().hex,
        "owner_id":   owner["id"],
        "topic":      topic,
        "scope":      scope,
        "scope_ids":  scope_ids,
        "default":    default,
        "priority":   max(0, min(100, priority)),
        "reason":     reason,
        "created_tick": (world or {}).get("tick", 0),
        "exceptions": {},
    }
    ensure_social_rules(owner).append(rule)
    return rule


def find_owned_household_rule(owner, topic):
    """The rule add_exception() attaches onto — always the owner's
    household-scope rule for this topic (an exception on an
    already-individual-scoped rule would be redundant)."""
    topic_l = topic.lower()
    for rule in owner.get("social_rules", []):
        if rule["scope"] == "household" and rule["topic"].lower() == topic_l:
            return rule
    return None


def find_applicable_rule(owner, requester, topic, world=None):
    """Case-insensitive topic match. Individual-scope rules win over
    household-scope rules for the same topic/requester.

    Household membership is checked live against
    world["households"][hid]["members"] (the canonical membership list,
    maintained by household_manager.py) -- NOT requester["household_id"]
    directly, which would be a frozen/incorrect proxy: a household's
    membership list is what actually changes when someone moves out,
    while a stale household_id field could otherwise still match a
    rule for a household the requester no longer belongs to."""
    topic_l = topic.lower()
    requester_id = requester["id"]
    households = (world or {}).get("households", {})

    household_match = None
    for rule in owner.get("social_rules", []):
        if rule["topic"].lower() != topic_l:
            continue
        if rule["scope"] == "individual" and requester_id in rule["scope_ids"]:
            return rule
        if rule["scope"] == "household":
            for hid in rule["scope_ids"]:
                household = households.get(hid)
                if household and requester_id in household.get("members", []):
                    household_match = rule
                    break
    return household_match


def find_applicable_exception(rule, requester_id, world):
    """Live check — the actual correctness path. Independent of
    whether the GC sweep (cleanup_expired_rule_exceptions) has run."""
    exc = rule.get("exceptions", {}).get(requester_id)
    if not exc:
        return None
    expires_tick = exc.get("expires_tick")
    if expires_tick is not None and (world or {}).get("tick", 0) > expires_tick:
        return None
    return exc


def resolve_request(owner, requester, topic, urgency, world):
    """Returns (outcome, reason). outcome is "allow"|"deny"|None --
    None means no rule matches this topic/requester at all, so the
    caller should fall through to normal open-ended negotiation.

    Urgency can only override a "deny" at the EXCEPTION layer, never
    against a bare base-rule deny with no exception history -- a base
    rule is cheap to author and rarely override-proofed on purpose,
    while urgency is self-reported by the requester with no
    plausibility check today. See plan doc for the full rationale.
    """
    rule = find_applicable_rule(owner, requester, topic, world)
    if not rule:
        return None, None

    exception = find_applicable_exception(rule, requester["id"], world)
    if exception:
        outcome = exception["override"]
        if outcome == "deny" and urgency is not None and urgency > exception["priority"]:
            return "allow", f"urgency overrode exception: {exception.get('reason', '')}".strip()
        return outcome, exception.get("reason")

    return rule["default"], rule.get("reason")


def add_exception(owner, topic, target_id, override, priority=70,
                   reason="", duration_ticks=None, world=None):
    """No-ops (returns None) if the owner has no household rule for
    this topic yet -- the base rule must exist before it can be
    excepted. One active exception per subject (overwrite in place)."""
    rule = find_owned_household_rule(owner, topic)
    if not rule:
        return None

    now = (world or {}).get("tick", 0)
    exception = {
        "override":     override,
        "priority":     max(0, min(100, priority)),
        "reason":       reason,
        "created_tick": now,
        "expires_tick": (now + duration_ticks) if duration_ticks else None,
    }
    rule["exceptions"][target_id] = exception
    return exception


def cleanup_expired_rule_exceptions(world):
    """Periodic garbage collection ONLY -- correctness is already
    handled by the live check in find_applicable_exception(). This
    just keeps c["social_rules"] bounded over a long-lived character's
    life by deleting exception entries whose expires_tick has passed."""
    now = world.get("tick", 0)
    for c in world.get("characters", {}).values():
        for rule in c.get("social_rules", []):
            expired = [
                sid for sid, exc in rule.get("exceptions", {}).items()
                if exc.get("expires_tick") is not None and now > exc["expires_tick"]
            ]
            for sid in expired:
                del rule["exceptions"][sid]
