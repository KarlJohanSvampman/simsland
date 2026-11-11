"""
systems/choice_tags.py -- which of a character's tags mattered for each choice the model made.

Traits are only tags; the model interprets them. So every decision reply ends with a TAGS line
(brain/llm_brain.py::_ENVELOPE_FORMAT): the one trait that most decided the choice, up to 3 if several clearly did,
no explanation. Here, when the decision lands (brain/cognition_actor.py::on_decision_ready), those are checked
against the tags the character really has (systems/personality_profile.effective_traits: their traits plus what
their current mood brings out) and recorded, newest last, in c["choice_log"]:

    {tick, chosen: {type, target}, options: [the action types offered], tags_on_character, significant (theirs,
     at most MAX_SIGNIFICANT), not_theirs (named but not a tag of theirs), said: whether the reply had a TAGS line}

Read by VR "Choices & tags" (frontend/src/vrLLM.js) through /admin/llm/{id}/choices.
"""

import re

MAX_SIGNIFICANT = 3
KEPT = 60


def _norm(t):
    return re.sub(r"[\s_\-]+", " ", str(t or "").strip().lower())


def record(c, world, decision, available_actions=None):
    if not decision:
        return None
    from systems.personality_profile import effective_traits
    theirs = effective_traits(c)
    by_norm = {_norm(t): t for t in theirs}
    raw = decision.get("choice_tags")
    significant, not_theirs = [], []
    for t in raw or []:
        hit = by_norm.get(_norm(t))
        if hit is None:                                   # "very curious" for "curious", "impulsiveness" for "impulsive"
            n = _norm(t)
            hit = next((v for k, v in by_norm.items() if k and (k in n or n in k)), None)
        if hit is not None:
            if hit not in significant and len(significant) < MAX_SIGNIFICANT:
                significant.append(hit)
        elif t not in not_theirs:
            not_theirs.append(t)
    act = decision.get("action") or {}
    entry = {
        "tick": world.get("tick", 0),
        "chosen": {"type": act.get("type"), "target": act.get("target_description") or act.get("target") or act.get("interaction")},
        "options": list((available_actions or {}).get("action_types") or [])[:60],
        "tags_on_character": theirs,
        "significant": significant,
        "not_theirs": not_theirs,
        "said": raw is not None,
        "fallback": bool(act.get("fallback")),
    }
    log = c.setdefault("choice_log", [])
    log.append(entry)
    del log[:-KEPT]
    return entry
