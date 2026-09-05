"""
systems/secret_keeping.py

Generalizes systems/secrets.py's already-real (but previously dormant --
nothing ever called add_secret/add_deception_target) secret/deception data
model to ANY kind of thing a character might want to keep from specific
people: a contact/relationship, an activity or hobby, an item or prop, or
a past event -- not just the "hidden affair" case excuses.py already
half-supported via c["secrets"]'s dead status=="hidden" field.

Deciding WHAT needs hiding and FROM WHOM is deterministic, reusing
excuses.py's own existing disapproval-detection (RISKY_BEHAVIOR_TAGS,
OBJECTIONABLE_ACTIVITIES, _authority_disapproves_of_*) rather than asking
an LLM to invent judgment calls a rule can already make correctly. The LLM
(llm/secret_authoring.py) only decides WHY (a one-line private reason) and
WHAT LIE to consistently tell -- generated once, eagerly, when a secret is
marked, and reused every time that same person is asked, which is what
makes a caught inconsistency ("but you said you were at the library --
now you're saying the park?") a meaningful, catchable event instead of a
fresh improvisation every time.

If a secret somehow ends up without a preferred_lie (an old secret, a
partial LLM failure that produced a reason but not a lie), the FIRST time
someone is actually confronted about it, one is improvised on the spot and
stored -- so it becomes the consistent story from then on, exactly as if
it had been authored up front.
"""

import random

from systems import secrets as secrets_engine
from llm.secret_authoring import generate_secret_cover
from llm.llm_gate import run_llm_call

# Which question_type(s) (excuses.py's "who"/"where"/"what"/"when") a given
# subject_type is actually relevant to -- e.g. a secret CONTACT matters for
# "who are you seeing", a secret HOBBY/ACTIVITY matters for "what were you
# doing"/"where were you".
_SUBJECT_TYPE_QUESTIONS = {
    "contact":    {"who", "where"},
    "activity":   {"what", "where"},
    "hobby":      {"what", "where"},
    "interest":   {"what"},
    "item":       {"what"},
    "prop":       {"what"},
    "past_event": {"what", "who"},
}


def mark_secret(c, world, subject_type, label, hidden_from_ids, category="other",
                 severity=None, content=None):
    """Create a new generalized secret on c, hidden from hidden_from_ids
    (a list of character ids), and eagerly generate its reason/preferred_lie.
    subject_type: contact | activity | hobby | interest | item | prop |
    past_event. label: a short human-readable name (e.g. a contact's name,
    an activity's label) used to build the default content string and the
    LLM prompt."""
    if content is None:
        content = f"Keeping {label} secret" if label else f"A secret {subject_type}"

    secret = secrets_engine.add_secret(
        c, content, category=category, severity=severity, subject_ids=[], world=world,
    )
    secret["subject_type"] = subject_type
    secret["label"] = label
    secret["reason"] = None
    secret["preferred_lie"] = None

    for target_id in hidden_from_ids or []:
        secrets_engine.add_deception_target(secret, target_id)

    _ensure_cover_story(c, world, secret)
    return secret


def hide_from(secret, target_id):
    """Add one more person to an existing secret's deception targets
    (e.g. a new household member moves in and also needs kept in the dark)."""
    if target_id not in secret.get("deception_targets", {}):
        secrets_engine.add_deception_target(secret, target_id)


def _ensure_cover_story(c, world, secret):
    """Fills in reason/preferred_lie if either is missing. Real LLM call
    with a deterministic fallback (llm/secret_authoring.py never returns
    empty strings), bridged synchronously the same way reflection.py
    bridges queue_social_reflection -- this runs inside a tick's worker
    thread, no running event loop to attach an asyncio task to."""
    if secret.get("reason") and secret.get("preferred_lie"):
        return
    session = c.setdefault("llm_session", {"history": []})
    try:
        result = run_llm_call(generate_secret_cover(c, world, secret, session))
    except Exception:
        result = None
    if not result:
        category = secret.get("category", "other")
        from llm.secret_authoring import _FALLBACK_REASONS, _FALLBACK_LIES
        result = {
            "reason": _FALLBACK_REASONS.get(category, _FALLBACK_REASONS["other"]),
            "preferred_lie": _FALLBACK_LIES.get(category, _FALLBACK_LIES["other"]),
        }
    secret.setdefault("reason", None)
    secret.setdefault("preferred_lie", None)
    if not secret["reason"]:
        secret["reason"] = result.get("reason")
    if not secret["preferred_lie"]:
        secret["preferred_lie"] = result.get("preferred_lie")


def find_relevant_secret(c, question_type, authority_id, world):
    """The secret (if any) that excuses.py should treat as governing this
    specific question from this specific authority -- must both target
    authority_id as a deception target AND actually be relevant to the
    kind of question being asked (a secret hobby doesn't get invoked for
    a "who were you with" question)."""
    for secret in c.get("secrets", []):
        if not isinstance(secret, dict):
            continue
        if authority_id not in secret.get("deception_targets", {}):
            continue
        allowed_questions = _SUBJECT_TYPE_QUESTIONS.get(secret.get("subject_type"), {"what", "where", "who"})
        if question_type in allowed_questions:
            return secret
    return None


def get_consistent_lie(c, secret, question_type, authority_id, world):
    """Returns the secret's preferred_lie, improvising and storing one on
    the spot if it's somehow still missing (see module docstring)."""
    if not secret.get("preferred_lie"):
        _ensure_cover_story(c, world, secret)
    record_probe(secret, authority_id, world)
    return secret.get("preferred_lie") or "I'd rather not get into it."


def record_probe(secret, authority_id, world):
    dt = secret.get("deception_targets", {}).get(authority_id)
    if dt:
        dt["last_probed_tick"] = world.get("tick", 0) if world else dt.get("last_probed_tick", 0)


def apply_confrontation_outcome(secret, target_id, believed, world, delta=0.15):
    """Called once a confrontation about a secret-backed lie/detail
    resolves -- believed=True eases suspicion on that specific secret
    (the cover story held), believed=False deepens it (something felt
    off), on top of whatever generic worries.py suspicion movement the
    caller applies separately."""
    if believed:
        secrets_engine.update_suspicion(secret, target_id, -delta)
    else:
        secrets_engine.update_suspicion(secret, target_id, delta)


def maybe_generate_secret(c, world):
    """Periodic (daily-cadence) sweep -- the deterministic "what should be
    kept secret, from whom" decision, reusing excuses.py's existing
    disapproval-detection instead of inventing a parallel one:

    1. Any affair/secret_crush/forbidden_attraction relationship not yet
       backed by a real secret gets one, hidden from the spouse/partner --
       this is the core case systems/absence_suspicion.py's confrontations
       actually bite into.
    2. Any hobby/activity a real household authority (parent/spouse) would
       disapprove of, per excuses.py's own RISKY_BEHAVIOR_TAGS/
       OBJECTIONABLE_ACTIVITIES-adjacent checks, gets hidden from that
       authority if not already covered.
    """
    from systems.excuses import _authority_disapproves_of_activity, OBJECTIONABLE_ACTIVITIES

    existing_contact_secrets = {
        s.get("label") for s in c.get("secrets", []) if s.get("subject_type") == "contact"
    }
    existing_hobby_secrets = {
        s.get("label") for s in c.get("secrets", []) if s.get("subject_type") == "hobby"
    }

    chars = world.get("characters", {})

    # 1. Affair-flavored relationships -> secret from the spouse/partner
    for other_id, rel in c.get("relationships", {}).items():
        labels = rel.get("labels", [])
        if not any(l in labels for l in ("affair", "secret_crush", "forbidden_attraction")):
            continue
        other = chars.get(other_id)
        other_name = other.get("name", "someone") if other else "someone"
        if other_name in existing_contact_secrets:
            continue
        spouse_ids = [
            oid for oid, r in c.get("relationships", {}).items()
            if any(l in r.get("labels", []) for l in ("spouse", "partner")) and oid != other_id
        ]
        if not spouse_ids:
            continue
        mark_secret(
            c, world, "contact", other_name, hidden_from_ids=spouse_ids,
            category="infidelity",
        )

    # 2. Disapproved hobbies -> secret from a real household authority
    household = world.get("households", {}).get(c.get("household_id"))
    authority_ids = []
    if household:
        for member_id in household.get("members", []):
            if member_id == c.get("id"):
                continue
            rel = c.get("relationships", {}).get(member_id, {})
            if any(l in rel.get("labels", []) for l in ("parent", "guardian", "spouse")):
                authority_ids.append(member_id)

    if authority_ids:
        for hobby in c.get("hobbies", []):
            hobby_id = hobby if isinstance(hobby, str) else hobby.get("id")
            if not hobby_id or hobby_id in existing_hobby_secrets:
                continue
            if hobby_id not in OBJECTIONABLE_ACTIVITIES:
                continue
            hiders = [
                aid for aid in authority_ids
                if _authority_disapproves_of_activity(chars.get(aid, {}), hobby_id, world)
            ]
            if hiders:
                mark_secret(
                    c, world, "hobby", hobby_id, hidden_from_ids=hiders,
                    category="other",
                )


def tick_all_secrets(world):
    """Thin wrapper so sim_loop.py has one obvious call site -- the real
    decay logic already exists and was simply never invoked."""
    secrets_engine.tick_secrets(world)
