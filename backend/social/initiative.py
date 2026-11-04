"""
social/initiative.py -- how much a character invests in someone (design section 4).

    rel["initiative"] = {"willingness": 0..100   willing to start an interaction with them
                         "investment": 0..100    how much keeping this relationship matters
                         "repair_desire": 0..100 wants it better than it is
                         "avoidance": 0..100     tends to keep away
                         "recent_initiatives": [{tick, kind, ref}],   what c tried
                         "recent_responses": [{tick, outcome, kind, ref}]}   how oid answered

Every meaningful initiative gets an outcome (OUTCOMES), and outcomes feed back: rejection after rejection wears
willingness down and avoidance up (and frustration with it); warm responses do the opposite. Someone who keeps reaching
out and keeps getting brushed off eventually stops trying -- nothing scripts that, it falls out of these numbers.
"""

from social.core import clamp, emit, now, rel, note

CAP = 20
OUTCOMES = {
    #                        willingness  avoidance  repair  frustration
    "accepted_positively":   (6, -4, -4, 0),
    "accepted_reluctantly":  (1, 0, 0, 0),
    "ignored":               (-6, 4, -2, 4),
    "rejected":              (-8, 5, -3, 6),
    "interrupted":           (-3, 2, 0, 2),
    "hostile":               (-12, 8, -5, 10),
    "counter_proposal":      (2, 0, 0, 0),
    "reconciliation":        (10, -10, -20, 0),
}
INITIATIVE_KINDS = ("approach", "small_talk", "suggestion", "request", "apology", "repair", "complaint", "criticism",
                    "provocation", "negotiation", "invitation", "defence", "gossip", "news")

_CLOSE = {"partner", "spouse", "wife", "husband", "boyfriend", "girlfriend", "parent", "mother", "father", "child",
          "son", "daughter", "sibling", "brother", "sister", "best_friend", "close_friend"}


def get(c, oid, create=True):
    r = rel(c, oid, create=create)
    i = r.get("initiative")
    if not isinstance(i, dict):
        close = str(r.get("designation") or r.get("family_role") or r.get("type") or "").lower() in _CLOSE
        i = {"willingness": round(clamp(45 + 0.3 * (r.get("friendship") or 0) - 0.3 * (r.get("hostility") or 0), 0, 100), 1),
             "investment": 75.0 if close else round(clamp(20 + 0.5 * (r.get("friendship") or 0), 0, 100), 1),
             "repair_desire": 0.0,
             "avoidance": 30.0 if c.get("cold_shoulder_towards") and oid in c["cold_shoulder_towards"] else 0.0,
             "recent_initiatives": [], "recent_responses": []}
        if create:
            r["initiative"] = i
    return i


def took(c, oid, world, kind, ref=None):
    """c reached out to oid (started a conversation, made a suggestion, apologised...)."""
    if not oid or oid == c.get("id"):
        return
    i = get(c, oid)
    i["recent_initiatives"].append({"tick": now(world), "kind": kind, "ref": ref})
    del i["recent_initiatives"][:-CAP]


def answered(c, oid, world, outcome, kind=None, ref=None):
    """How oid answered something c tried. Moves c's own willingness, avoidance and wish to repair."""
    if outcome not in OUTCOMES or not oid or oid == c.get("id"):
        return
    i = get(c, oid)
    w, a, rp, fr = OUTCOMES[outcome]
    i["willingness"] = round(clamp(i["willingness"] + w, 0, 100), 1)
    i["avoidance"] = round(clamp(i["avoidance"] + a, 0, 100), 1)
    i["repair_desire"] = round(clamp(i["repair_desire"] + rp, 0, 100), 1)
    i["recent_responses"].append({"tick": now(world), "outcome": outcome, "kind": kind, "ref": ref})
    del i["recent_responses"][:-CAP]
    if fr:
        from social import frustration
        frustration.raise_(c, oid, world, fr, kind="ignored" if outcome == "ignored" else None)
    emit("RelationshipInitiativeChanged", {"observer_id": c.get("id"), "target_id": oid, "outcome": outcome,
                                           "kind": kind})
    note(c, oid, world, f"{(kind or 'reached out').replace('_', ' ')}: {outcome.replace('_', ' ')}")


def refresh_repair(c, oid, world):
    """Wanting it mended: someone who matters, regarded worse than they'd like."""
    from social import standing
    i = get(c, oid)
    s = standing.score(c, oid)
    want = clamp((i["investment"] - 40) + max(0, 20 - s) * 0.6, 0, 100) if s < 20 else 0
    if want > i["repair_desire"]:
        i["repair_desire"] = round(want, 1)
    return i["repair_desire"]


def rebuffs(c, oid, n=4):
    """How many of the last n responses were a brush-off."""
    rs = get(c, oid, create=False)["recent_responses"][-n:]
    return sum(1 for r in rs if r["outcome"] in ("ignored", "rejected", "hostile"))
