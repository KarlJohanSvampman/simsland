"""
systems/absence_suspicion.py

The mirror image of systems/withdrawal_concern.py: instead of a household
member staying home too much, a PARTNER/SPOUSE being away from home too
much (systems/home_presence.py's consecutive_low_home_days, the inverse
of that round's consecutive_high_home_days) breeds suspicion rather than
concern -- real envy (rel["jealousy"], an existing field) that the
partner might be spending that time with someone else, escalating through
noticing -> growing suspicion -> a real confrontation, routed through the
existing systems/excuses.py lie/excuse engine so the confronted partner's
own honesty/secrets genuinely determine the outcome -- to, if unresolved,
a real grievance (systems/grievances.py) and eventually a real fight
(systems/conflict_pipeline.py), both reused entirely as-is.

Believability of an excuse, and whether a named third party can vouch,
both move suspicion -- a good, truthful, corroborated answer eases it; an
uncaught lie only eases it a little (a partner's gut responds to more
than the words); a lie later CAUGHT by excuses.py's own existing
consistency-check machinery hits much harder, handled directly in
excuses.py::_handle_caught_lying rather than duplicated here.
"""

import random

AWAY_THRESHOLD = 0.35          # a day mostly spent away from home
NOTICE_DAYS = 4
SUSPICIOUS_DAYS = 8
CONFRONT_DAYS = 12

_STAGE_ORDER = ["noticing", "suspicious", "confronting"]

_MIN_SUSPICION_TO_CONFRONT = 0.2


def _stage_for_days(days):
    if days >= CONFRONT_DAYS:
        return "confronting"
    if days >= SUSPICIOUS_DAYS:
        return "suspicious"
    return "noticing"


def maybe_notice_absence(observer, world):
    """Daily entry point (mirrors withdrawal_concern.py::
    maybe_notice_withdrawal). Only romantic partners/spouses watch each
    other's absence this way -- this is jealousy/infidelity-flavored
    drama, not general household concern (that's withdrawal_concern.py's
    job, for the opposite pattern)."""
    from systems.home_presence import consecutive_low_home_days

    chars = world.get("characters", {})
    for other_id, rel in observer.get("relationships", {}).items():
        if not any(l in rel.get("labels", []) for l in ("partner", "spouse")):
            continue
        subject = chars.get(other_id)
        if not subject or not subject.get("alive", True):
            continue
        days = consecutive_low_home_days(subject, AWAY_THRESHOLD)
        if days < NOTICE_DAYS:
            continue
        _escalate_suspicion(observer, subject, world, days)


def _escalate_suspicion(observer, subject, world, days_away):
    from brain.intentions import add_intention
    from systems.worries import bump_suspicion

    rel = observer.setdefault("relationships", {}).setdefault(subject["id"], {})
    state = observer.setdefault("_absence_suspicion", {}).setdefault(
        subject["id"], {"stage": "noticing"}
    )

    target_stage = _stage_for_days(days_away)
    if _STAGE_ORDER.index(target_stage) > _STAGE_ORDER.index(state["stage"]):
        state["stage"] = target_stage

    if state["stage"] == "noticing":
        add_intention(observer, {
            "type": "notice_partner_absence", "category": "social", "priority": 25,
            "target_id": subject["id"],
            "reason": f"{subject.get('name', 'they')} has barely been home lately -- you can't help but notice",
        })
        return

    if state["stage"] == "suspicious":
        rel["jealousy"] = min(100, rel.get("jealousy", 0) + 3)
        bump_suspicion(
            observer, subject["id"], 0.05, "partner_frequently_away",
            f"{subject.get('name', subject['id'])} has been away from home a lot lately", world,
        )
        add_intention(observer, {
            "type": "grow_suspicious_of_partner", "category": "social", "priority": 35,
            "target_id": subject["id"],
            "reason": f"you keep wondering where {subject.get('name', 'they')} really goes, and who with -- maybe it's time to check their phone",
        })
        return

    # confronting
    cal = world.get("calendar", {})
    today = (cal.get("year"), cal.get("month"), cal.get("day"))
    if state.get("_last_confront_day") == today:
        return
    worry = observer.get("worries", {}).get(subject["id"], {})
    if worry.get("suspicion_level", 0) < _MIN_SUSPICION_TO_CONFRONT:
        return
    state["_last_confront_day"] = today
    _confront_about_absence(observer, subject, world)


def _confront_about_absence(observer, subject, world):
    """The real confrontation -- routes through excuses.py's actual
    excuse/lie engine so the outcome genuinely depends on the confronted
    partner's honesty, secrets, and privacy. Resolves the observer's
    suspicion up or down based on the answer, and, if suspicion stays
    high, files a real grievance that can eventually cross
    CONFRONT_THRESHOLD into a real fight (grievances.py/
    conflict_pipeline.py, unchanged)."""
    from systems.excuses import generate_excuse
    from systems.worries import bump_suspicion
    from systems.secret_keeping import find_relevant_secret, apply_confrontation_outcome
    from systems.grievances import add_grievance
    from brain.intentions import add_intention
    from systems.confiding import tag_dramatic_memory

    question_type = random.choice(["where", "who"])
    result = generate_excuse(subject, observer, question_type, world)

    believable = _judge_believability(observer, subject, result, world)

    if believable:
        delta = -0.15 if not result["is_lie"] else -0.05
        bump_suspicion(
            observer, subject["id"], delta, "confronted_about_absence",
            f"asked {subject.get('name', subject['id'])} about it -- answer felt believable", world,
        )
    else:
        bump_suspicion(
            observer, subject["id"], 0.08, "confronted_about_absence",
            f"asked {subject.get('name', subject['id'])} about it -- still doesn't sit right", world,
        )
        add_grievance(observer, subject["id"], "absence_unresolved", world)

    secret = find_relevant_secret(subject, question_type, observer["id"], world)
    if secret:
        apply_confrontation_outcome(secret, observer["id"], believed=believable, world=world)

    outcome_phrase = "it seemed to check out" if believable else "something still feels off"
    add_intention(observer, {
        "type": "confronted_partner_about_absence", "category": "social", "priority": 40,
        "target_id": subject["id"],
        "reason": f"you finally asked {subject.get('name', 'them')} where they've been -- {outcome_phrase}",
    })

    tag_dramatic_memory(
        observer, world,
        f"Confronted {subject.get('name', 'my partner')} about being away so much -- {outcome_phrase}.",
        importance=0.55 if believable else 0.7,
        people=[subject["id"]],
    )
    if not believable:
        tag_dramatic_memory(
            subject, world,
            f"{observer.get('name', 'my partner')} confronted me about where I've been -- I don't think they bought it.",
            importance=0.6,
            people=[observer["id"]],
        )


def _judge_believability(observer, subject, excuse_result, world):
    """How convincing subject's answer is to observer -- factors: their
    honesty trait (excuses.py's own scoring), the answer's vagueness,
    existing trust, and whether a named third party could plausibly
    vouch for them."""
    from systems.excuses import _honesty_score

    if excuse_result["is_lie"]:
        base = 0.35
    else:
        base = 0.65 + (0.25 * (1.0 - excuse_result.get("vagueness", 0.0)))

    honesty = _honesty_score(subject)
    base += (honesty - 0.5) * 0.2

    if not excuse_result["is_lie"] and _has_corroborator(observer, subject, world):
        base += 0.2

    trust = observer.get("relationships", {}).get(subject["id"], {}).get("trust", 0)
    base += max(-0.15, min(0.15, trust / 400.0))

    return random.random() < max(0.05, min(0.95, base))


def _has_corroborator(observer, subject, world):
    """True if the person subject actually named (truthfully) is someone
    the observer knows and trusts enough to take their word for it --
    reuses the same target lookup excuses.py's _get_true_detail draws
    from, so this only ever applies to a TRUE answer, never a lie (there's
    no real person to vouch for a fabricated cover)."""
    target_id = subject.get("move_target", {}).get("target_id")
    if not target_id:
        return False
    rel = observer.get("relationships", {}).get(target_id)
    if not rel:
        return False
    return rel.get("trust", 0) > 40 or rel.get("designation") in ("friend", "close_friend", "best_friend")
