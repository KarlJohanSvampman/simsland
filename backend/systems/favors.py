"""
systems/favors.py

Favor ledger + reciprocity fatigue. systems/proposals.py already has a
full ask/accept/decline/counter negotiation engine ("social_ask",
"request") -- what it never did is remember that granting one is a real
commitment: it costs the granter something up front (not just on later
failure to reciprocate), and unreciprocated favors should make a
character genuinely more likely to refuse the next ask, not just grumble
about it in flavor text.

rel["favors"] (on the GRANTER's relationship dict, keyed by the asker's
id) is a capped list of recent grants: {"topic", "tick", "reciprocated"}.
rel["favor_frustration"] rises on every new commitment and eases when the
other party does something back -- see on_favor_granted() below, which
is the single entry point (called from proposals.py::_maybe_resolve()
when a social_ask/request proposal is accepted) and handles BOTH
directions: recording a fresh debt, or clearing an existing one, in one
call, since "who owes whom" flips depending on prior history between the
same two people.
"""

FAVOR_COMMIT_FRUSTRATION = 0.08
FAVOR_RECIPROCATE_RELIEF = 0.15
FAVOR_GRIEVANCE_THRESHOLD = 0.7
FAVOR_WORN_OUT_THRESHOLD  = 0.5
FAVOR_LEDGER_CAP = 10


def on_favor_granted(granter, asker, world, topic):
    """Call when `granter` accepts a social_ask/request proposal FROM
    `asker`. If `asker` was already owed a favor by `granter` (asker
    granted one to granter earlier and it's unreciprocated), this act
    counts as reciprocating THAT favor instead of opening a new debt --
    checked first, since "returning a favor" and "asking a fresh one"
    look identical at the proposal layer and only the ledger tells them
    apart."""
    asker_rel = asker.get("relationships", {}).get(granter["id"])
    if asker_rel and any(not f["reciprocated"] for f in asker_rel.get("favors", [])):
        _record_reciprocated(owed=asker, payer=granter)
        return

    _record_granted(granter, asker, world, topic)


def is_favor_worn_out(c, other_id):
    """True if c has built up enough unreciprocated-favor frustration
    toward other_id that they'd realistically start saying no. See
    action_router.py::_route_propose_request's fast-path and
    brain/context_builder.py's proposal-context narration."""
    rel = c.get("relationships", {}).get(other_id)
    return bool(rel) and rel.get("favor_frustration", 0.0) >= FAVOR_WORN_OUT_THRESHOLD


def _record_granted(granter, asker, world, topic):
    rel = granter.setdefault("relationships", {}).setdefault(asker["id"], {})
    ledger = rel.setdefault("favors", [])
    ledger.append({"topic": topic, "tick": world.get("tick", 0), "reciprocated": False})
    del ledger[:-FAVOR_LEDGER_CAP]

    rel["favor_frustration"] = min(1.0, rel.get("favor_frustration", 0.0) + FAVOR_COMMIT_FRUSTRATION)

    if rel["favor_frustration"] >= FAVOR_GRIEVANCE_THRESHOLD:
        from systems.grievances import add_grievance
        unreciprocated = sum(1 for f in ledger if not f["reciprocated"])
        add_grievance(granter, asker["id"], "favor_unreciprocated", world,
                      details={"unreciprocated_count": unreciprocated, "topic": topic})
        rel["favor_frustration"] = 0.0  # vented via the grievance/confrontation pipeline


def _record_reciprocated(owed, payer):
    """`owed` previously granted `payer` a favor (rel lives on `owed`'s
    side, see _record_granted); `payer` just did something back."""
    rel = owed.get("relationships", {}).get(payer["id"])
    if not rel:
        return
    for entry in reversed(rel.get("favors", [])):
        if not entry["reciprocated"]:
            entry["reciprocated"] = True
            break
    rel["favor_frustration"] = max(0.0, rel.get("favor_frustration", 0.0) - FAVOR_RECIPROCATE_RELIEF)
