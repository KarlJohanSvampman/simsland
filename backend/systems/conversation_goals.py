"""
systems/conversation_goals.py

Each conversation participant privately forms their own goal for talking
to this specific other person -- genuine interest in the topic, hoping to
ask a favor, trying to make a good impression, staying cordial/tactical
with someone low-stakes (a coworker you might need later), or (family/
close friends only) just not being interested in this particular
conversation right now. Reuses systems/choice.py::choose() exactly like
every other in-character decision in this codebase (outfits, meals,
jobs) -- one LLM-backed pick from a relationship-appropriate, occasion-
filtered option pool, not a hardcoded rule.

conv["goals"][char_id] = {"type", "label"} -- assigned once, lazily, the
first time that character speaks in the conversation (see
action_router.py::apply_speech()). Deliberately per-participant, not a
single conv-level field: two people in the same conversation can (and
often should) want very different things from it.
"""

_FAVOR_TAGS = {"neutral", "acquaintance", "close", "romantic", "coworker"}

# How many consecutive off-goal turns a "not_interested" participant
# tolerates before disengaging without spending a real LLM turn on it --
# the plan's "early exit, same fast-path principle as Phase 5" clause.
DISENGAGE_STREAK = 3


def _has_favor_motive(c):
    """True if c has a real unresolved want on the books (see
    systems/persistent_desires.py, and systems/expectation_planner.py's
    hard-blocker fallback which also lands here) -- not just flavor,
    an actual open desire this conversation could plausibly resolve."""
    return bool(c.get("persistent_desires"))


def _occasion_for(c, other, world):
    rel = c.get("relationships", {}).get(other["id"], {})
    if (rel.get("romantic_interest", 0) or rel.get("attraction", 0)) > 40:
        return "romantic"
    if rel.get("kinship") or rel.get("state") == "close_friend":
        return "close"
    if c.get("company_id") and c.get("company_id") == other.get("company_id"):
        return "coworker"
    if rel.get("state") == "acquaintance":
        return "acquaintance"
    return "neutral"


def assign_conversation_goal(c, world, conv, other_id):
    """Lazily assigns and returns c's goal for this conversation with
    other_id. Idempotent -- a second call for the same pair just returns
    what was already decided, since a goal is set once per conversation,
    not re-rolled every turn."""
    goals = conv.setdefault("goals", {})
    if other_id in goals:
        return goals[other_id]

    other = world.get("characters", {}).get(other_id)
    if not other:
        return None

    occasion = _occasion_for(c, other, world)

    options = [
        {"id": "topic_interest", "tags": ["neutral", "close", "acquaintance", "coworker", "romantic"],
         "label": "genuinely interested in the subject"},
        {"id": "cordial_tactical", "tags": ["neutral", "acquaintance", "coworker"],
         "label": "keeping things pleasant and useful — might need them later"},
    ]
    if occasion == "romantic":
        options.append({"id": "impress", "tags": ["romantic"],
                         "label": "trying to make a good impression"})
    if _has_favor_motive(c):
        options.append({"id": "favor", "tags": list(_FAVOR_TAGS),
                         "label": "hoping to find an opening to ask them for something"})
    if occasion == "close":
        options.append({"id": "not_interested", "tags": ["close"],
                         "label": "not really interested in this particular conversation right now"})

    from systems.choice import choose
    picked = choose(c, world, "conversation goal", options, occasion=occasion)
    goal = {"type": picked["id"], "label": picked["label"]} if picked else \
           {"type": "topic_interest", "label": "genuinely interested in the subject"}
    goals[other_id] = goal
    return goal


def _on_goal(goal, topic, conv):
    """No-LLM-call heuristic for whether THIS message trended toward
    the listener's own goal -- deliberately coarse (topic/goal-type
    matching only), since the point is a cheap streak signal, not real
    language understanding."""
    if goal["type"] == "not_interested":
        return False  # nothing to trend toward -- see check_goal_trending
    if goal["type"] == "topic_interest":
        return topic == conv.get("topic")
    if goal["type"] == "favor":
        return topic == "favor" or (topic or "").startswith("ask_")
    return True  # impress / cordial_tactical: any real engagement counts


def check_goal_trending(conv, listener, topic):
    """Call from action_router.py::apply_speech() after analyze_message().
    Tracks a per-listener off-goal streak on the conversation; once a
    "not_interested" participant's streak crosses DISENGAGE_STREAK, retires
    the conversation for them without spending a real LLM turn on it --
    same fast-path principle as social_events.py's hard-conflict
    auto-decline. Returns the updated streak count (mainly for tests)."""
    goal = conv.get("goals", {}).get(listener["id"])
    if not goal:
        return 0

    streak_map = conv.setdefault("_off_goal_streak", {})
    if _on_goal(goal, topic, conv):
        streak_map[listener["id"]] = 0
        return 0

    streak = streak_map.get(listener["id"], 0) + 1
    streak_map[listener["id"]] = streak

    if goal["type"] == "not_interested" and streak >= DISENGAGE_STREAK:
        conv["active"] = False

    return streak
