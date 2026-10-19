"""
llm/behavior_theory.py

Generates a theory for why a character exhibits a newly-noticed
behavior pattern (systems/behavior_patterns.py) -- modeled on
llm/story_condensation.py's shape (own prompt, own session key,
deterministic fallback). Classified optimistic (normal: work, gym,
errands) or pessimistic (suspicious: crime, an affair) -- a pessimistic
result feeds systems/worries.py's real suspicion tracking, generated
once when the pattern is first created, never re-rolled on repeat
sightings.
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND


def _who(ch, fallback):
    """Name plus age where it matters -- the prompt used to pass bare
    names only, so the model had no way to know a "Justin" was 6."""
    name = ch.get("name", fallback)
    if ch.get("age") is not None and ch.get("age_group") in ("child", "teen"):
        return f"{name} (a {ch['age']}-year-old {ch['age_group']})"
    return name


def _build_prompt(c, other, pattern, world):
    """Returns (prompt, force_optimistic).

    Confirmed live bug: this prompt offered "an affair, criminal activity,
    hiding something" and a work/gym/errands list to EVERYONE, ages never
    mentioned -- Kevin theorizing about a 6-year-old Justin sleeping came
    back as a "4 AM power nap before his early morning novel-writing
    sessions". A pessimistic result also feeds real suspicion tracking and
    a detective story (systems/behavior_patterns.py), so an adult theory
    about a child isn't just flavor text. Children are constrained on both
    sides: a child SUBJECT only gets child-sized explanations, and a child
    OBSERVER guesses like a child (reusing the same developmental_profile_
    registry prose brain/context_builder.py injects into their think()
    prompt) -- neither may produce suspicion, so valence is forced
    optimistic for them by the caller."""
    lo, hi = pattern["hour_range"]
    observer_group = c.get("age_group")
    subject_group = other.get("age_group")
    force_optimistic = observer_group == "child" or subject_group == "child"

    if subject_group == "child":
        explanations = (
            "Come up with a plausible theory for why they do this, in plain "
            "everyday terms for a child (for example they're tired, hungry, "
            "bored, curious, copying someone, or it's just what kids do). "
            "Never work, money, romance, crime, or secrets -- they are a child."
        )
    elif subject_group == "teen":
        explanations = (
            "Come up with a plausible theory for why they do this. It can be "
            "completely mundane (school, friends, a hobby, a part-time job, "
            "a crush, a mood) or something more worrying (upset about "
            "something, hiding something) -- pick whichever feels most fitting "
            "given the behavior itself, not always the dramatic option."
        )
    else:
        explanations = (
            "Come up with a plausible theory for why they do this. It can be "
            "completely mundane (work, gym, errands, a hobby) or something more "
            "suspicious (an affair, criminal activity, hiding something) -- pick "
            "whichever feels most fitting given the behavior itself, not always "
            "the dramatic option."
        )

    perspective = ""
    if observer_group in ("child", "teen"):
        profile = (
            world.get("definitions", {})
            .get("developmental_profile_registry", {})
            .get(observer_group, {})
            .get("description")
        )
        if profile:
            perspective = f"\nThe person guessing: {profile}\n"
        if observer_group == "child":
            perspective += (
                "The theory must be a simple guess a child would actually make: "
                "short, concrete, about feelings and everyday things, in a "
                "child's own words.\n"
            )

    # Raw activity ids ("work_shift", "play_alone") read as game-engine
    # jargon -- a child-voiced guess came back as "likes playing
    # 'work_shift'". Humanized (and unquoted) only for prompts involving a
    # child/teen, so adult-only prompts stay byte-for-byte unchanged.
    activity = pattern["activity"]
    if observer_group in ("child", "teen") or subject_group in ("child", "teen"):
        activity = activity.replace("_", " ")
        behavior = activity
    else:
        behavior = f'"{activity}"'

    prompt = f"""
{_who(c, 'Someone')} has noticed {_who(other, 'someone')} doing
{behavior} repeatedly, usually around {lo}:00-{hi}:00.
{perspective}
{explanations}

Respond with STRICT JSON only: {{"text": <one-sentence theory>, "valence": "optimistic" or "pessimistic"}}
"""
    return prompt, force_optimistic


async def _generate(c, other, pattern, world):
    session = world.setdefault(
        "_behavior_theory_sessions", {}
    ).setdefault(pattern["id"], {"history": []})

    prompt, force_optimistic = _build_prompt(c, other, pattern, world)
    messages = [
        {"role": "system", "content": "You invent plausible in-character theories about why someone in a life-simulation game exhibits a behavior pattern. Keep every theory appropriate to the ages of the people involved. Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    result = await call_llm_safe(messages, session=session, char_id=c.get("id"))
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if force_optimistic or parsed.get("valence") not in ("optimistic", "pessimistic"):
        parsed["valence"] = "optimistic"
    return parsed


async def _generate_from_prompt(prompt, force_optimistic, char_id):
    """The model call for an already-built prompt -- touches no world state, so it
    can run on a systems/bg_llm worker."""
    messages = [
        {"role": "system", "content": "You invent plausible in-character theories about why someone in a life-simulation game exhibits a behavior pattern. Keep every theory appropriate to the ages of the people involved. Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    result = await call_llm_safe(messages, session={"history": []}, char_id=char_id)
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    if force_optimistic or parsed.get("valence") not in ("optimistic", "pessimistic"):
        parsed["valence"] = "optimistic"
    return parsed


def theory_from_prompt(prompt, force_optimistic, char_id):
    """Blocking; call from a bg_llm worker."""
    result = run_llm_call(_generate_from_prompt(prompt, force_optimistic, char_id), priority=PRIORITY_BACKGROUND)
    return result if isinstance(result, dict) else None


def build_theory_prompt(c, other, pattern, world):
    """Main-thread half: reads the world to build the prompt text."""
    return _build_prompt(c, other, pattern, world)


def generate_theory(c, other, pattern, world):
    """Sync entry point -- bridges the async LLM call the same way
    systems/choice.py::choose() already does via run_llm_call()."""
    return run_llm_call(_generate(c, other, pattern, world), priority=PRIORITY_BACKGROUND)
