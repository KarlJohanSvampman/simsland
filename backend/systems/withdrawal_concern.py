"""
systems/withdrawal_concern.py

Sustained, unusually-high time-at-home (systems/home_presence.py) is a
real source of social drama: household members who notice it escalate
from mild curiosity, through disbelieving reassurance, to actively
pushing the withdrawn person to go out -- and, if that keeps failing
and the person has real depression symptoms (systems/
mental_health_effects.py), toward therapy and eventually medication.

Each push is a real roll, not guaranteed, with success chance rising
the longer this has gone on and weighted by the withdrawn person's own
trait polarity balance and self-esteem (systems/self_image.py) --
someone already running low on both is realistically harder to
convince, not easier.

No new activities/actions are built for the five intention types this
fires (check_in_on/express_concern/invite_out_concerned/
suggest_therapy/suggest_medication) -- they surface into context via
the existing active-intentions narration and let the LLM roleplay
actually bringing it up, the same way this session's other "social"-
category intentions (apologize, inquire_about_contract, ...) already
work.
"""

import random

HIGH_HOME_THRESHOLD = 0.85   # a "mostly stayed home" day

NOTICE_DAYS = 3       # sustained high-home days before anyone says anything
DISBELIEF_DAYS = 6    # before reassurances stop being taken at face value
PUSH_DAYS = 8         # before an active "get them to go out" intention fires
THERAPY_PUSH_DAYS = 14
MEDICATION_PUSH_DAYS = 21

_STAGE_ORDER = ["noticing", "disbelief", "push_activity", "push_therapy", "push_medication"]

BASE_PERSUASION_CHANCE = 0.15
PERSUASION_CHANCE_PER_EXTRA_DAY = 0.03
MAX_PERSUASION_CHANCE = 0.75


def persuasion_chance(subject, world, days_persisted):
    """Higher for someone with more positive-polarity traits (optimists
    included, not singled out beyond being one such trait) and higher
    self-esteem -- someone already running low on both is realistically
    harder to talk into anything, not easier. Rises with how long this
    has persisted regardless."""
    from systems.self_image import trait_polarity_balance, overall_self_esteem
    _, _, net = trait_polarity_balance(subject, world.get("definitions", {}))
    esteem = overall_self_esteem(subject)

    chance = BASE_PERSUASION_CHANCE + PERSUASION_CHANCE_PER_EXTRA_DAY * days_persisted
    chance += net * 0.08
    chance += (esteem - 0.5) * 0.3
    return max(0.03, min(MAX_PERSUASION_CHANCE, chance))


def _stage_for_days(days_persisted):
    if days_persisted >= MEDICATION_PUSH_DAYS:
        return "push_medication"
    if days_persisted >= THERAPY_PUSH_DAYS:
        return "push_therapy"
    if days_persisted >= PUSH_DAYS:
        return "push_activity"
    if days_persisted >= DISBELIEF_DAYS:
        return "disbelief"
    return "noticing"


def maybe_notice_withdrawal(observer, world):
    """Called once per real calendar day per character (see sim_loop.py)
    -- observer scans their OWN household for a member showing a
    sustained high-home pattern. Household-scoped rather than all
    contacts -- these are the people who'd actually witness the pattern
    day to day."""
    from systems.home_presence import consecutive_high_home_days

    household = world.get("households", {}).get(observer.get("household_id"))
    if not household:
        return
    chars = world.get("characters", {})
    for member_id in household.get("members", []):
        if member_id == observer.get("id"):
            continue
        subject = chars.get(member_id)
        if not subject or not subject.get("alive", True):
            continue
        days = consecutive_high_home_days(subject, HIGH_HOME_THRESHOLD)
        if days < NOTICE_DAYS:
            continue
        _escalate_concern(observer, subject, world, days)


def _escalate_concern(observer, subject, world, days_persisted):
    concern = observer.setdefault("_withdrawal_concern", {})
    state = concern.setdefault(subject["id"], {"stage": "noticing", "push_attempts": 0})

    target_stage = _stage_for_days(days_persisted)
    if _STAGE_ORDER.index(target_stage) > _STAGE_ORDER.index(state["stage"]):
        state["stage"] = target_stage

    from brain.intentions import add_intention

    if state["stage"] == "noticing":
        add_intention(observer, {
            "type": "check_in_on", "category": "social", "priority": 30,
            "target_id": subject["id"],
            "reason": f"{subject.get('name', 'they')} has barely left the house lately -- you're a little worried",
        })
        return

    if state["stage"] == "disbelief":
        add_intention(observer, {
            "type": "express_concern", "category": "social", "priority": 40,
            "target_id": subject["id"],
            "reason": f"something feels off about {subject.get('name', 'them')} -- their reassurances don't add up anymore",
        })
        return

    # push_activity / push_therapy / push_medication -- a real persuasion
    # roll, capped at once per real day so this doesn't re-roll every
    # time the daily cadence calls in.
    cal = world.get("calendar", {})
    today = (cal.get("year"), cal.get("month"), cal.get("day"))
    if state.get("_last_push_day") == today:
        return
    state["_last_push_day"] = today
    state["push_attempts"] += 1

    action_type, verb = {
        "push_activity":   ("invite_out_concerned", "go out"),
        "push_therapy":    ("suggest_therapy", "see someone"),
        "push_medication": ("suggest_medication", "consider medication"),
    }[state["stage"]]

    chance = persuasion_chance(subject, world, days_persisted)
    add_intention(observer, {
        "type": action_type, "category": "social", "priority": 50,
        "target_id": subject["id"],
        "reason": f"you're determined to get {subject.get('name', 'them')} to {verb}",
        "persuasion_chance": round(chance, 3),
    })

    if random.random() < chance:
        _apply_successful_push(subject, state["stage"], world)


def _apply_successful_push(subject, stage, world):
    if stage == "push_activity":
        # Doesn't force an immediate trip -- this codebase's own trip/
        # event decision code stays the real decision-maker. Recorded so
        # a future round could soften home_leaving_multiplier further
        # right after a successful push if that turns out to matter.
        subject["_withdrawal_pushed_out_tick"] = world.get("tick", 0)
    elif stage == "push_therapy":
        subject.setdefault("mental_health_treatment", {}).setdefault("depression", {})["in_therapy"] = True
    elif stage == "push_medication":
        subject.setdefault("mental_health_treatment", {}).setdefault("depression", {})["on_medication"] = True
