"""
llm/party_policy.py

Generates a real, named policy proposal for a (party, topic) pair a
party has high topic_awareness on but hasn't authored a real POLICIES
entry for yet -- lazily generated once (mirrors systems/sports.py::
ensure_local_league()'s check-then-create shape), cached onto
world["political_parties"][party_id]["generated_policies"][topic], and
registered into the real, existing systems/politics.py::POLICIES dict
so apply_policy()/the legislation pipeline consume it completely
unchanged -- no new effect-application code needed.
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

# The SAME small set of 0-2-scale environment keys the 6 hand-authored
# POLICIES entries already target -- politics.py::apply_policy()'s
# clamp() is hardcoded to [0,2], so any other key (e.g. the 0-100-scale
# socioeconomics.py stats) would be silently destroyed by it. Confirmed
# via the exact same trap politics.py's own housing_investment/
# anti_corruption_reform comment already documents.
SAFE_POLICY_KEYS = [
    "tax_rate", "health_quality", "health_cost_index", "crime_solve_rate",
    "social_tension", "cost_of_living_index", "budget_deficit",
]


async def _generate_policy(party_name, topic, ideology_tags):
    session = {"history": []}
    tags_line = ", ".join(ideology_tags) or "no strong ideology"
    keys_line = ", ".join(SAFE_POLICY_KEYS)

    prompt = f"""
The {party_name} (ideology: {tags_line}) needs a real policy proposal
addressing the issue of "{topic}".

Give it a real, specific name (not just the topic name) and a rough
effect shape using ONLY these environment keys (never invent others):
{keys_line}

Respond with STRICT JSON only:
{{"name": "...", "primary": [["key", delta], ...], "secondary": [["key", delta], ...]}}
delta is a small real number, positive or negative, matching the scale
real policies use (typically -0.08 to 0.08). 1-2 primary effects,
0-2 secondary effects, all keys from the list above.
"""
    messages = [
        {"role": "system", "content": "You write real policy proposals for a political party in a life-simulation game. Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    result = await call_llm_safe(messages, session=session, char_id=None)
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed.get("name"), str) or not parsed["name"].strip():
        return None
    return parsed


def _fallback_policy(party_name, topic):
    """Never leave a (party, topic) pair without a real policy -- adapts
    the closest existing hand-authored POLICIES entry by topic-tag
    overlap rather than ever producing nothing."""
    from systems.politics import POLICIES
    best_id, best_overlap = None, -1
    for pid, p in POLICIES.items():
        overlap = len(set(p.get("tags", [])) & {topic})
        if overlap > best_overlap:
            best_id, best_overlap = pid, overlap
    base = POLICIES.get(best_id, {}) if best_id else {}
    return {
        "name": f"{party_name}'s {topic.replace('_', ' ').title()} Plan",
        "primary": [list(pair) for pair in base.get("primary", [])],
        "secondary": [list(pair) for pair in base.get("secondary", [])],
    }


def _safe_pairs(pairs):
    out = []
    for pair in pairs or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        key, delta = pair
        if key not in SAFE_POLICY_KEYS:
            continue
        try:
            out.append([key, float(delta)])
        except (TypeError, ValueError):
            continue
    return out


def generate_party_policy(world, party_id, topic):
    """Lazy, cached generation -- returns the real POLICIES id
    (f"{party_id}_{topic}") either way, generating and registering it
    into POLICIES the first time, reusing the cached id on every later
    call. Deliberately does NOT mutate the shared, cross-world
    definitions.json content (party_tmpl["agenda"]) -- the generated id
    lives in world["political_parties"] only; systems/politics.py::
    build_factions() merges it into a faction's effective agenda at
    read time."""
    from systems.politics import POLICIES

    parties_runtime = world.setdefault("political_parties", {})
    party_state = parties_runtime.setdefault(party_id, {})
    generated = party_state.setdefault("generated_policies", {})

    if topic in generated:
        return generated[topic]

    defs = world.get("definitions") or {}
    party_tmpl = (defs.get("political_party_templates") or {}).get(party_id, {})
    party_name = party_tmpl.get("name", party_id)
    ideology_tags = party_tmpl.get("ideology_tags", [])

    raw = run_llm_call(
        _generate_policy(party_name, topic, ideology_tags),
        priority=PRIORITY_BACKGROUND,
    )
    if not raw:
        raw = _fallback_policy(party_name, topic)

    primary = _safe_pairs(raw.get("primary"))
    secondary = _safe_pairs(raw.get("secondary"))
    if not primary and not secondary:
        # LLM produced nothing usable within the safe-key allowlist --
        # fall back once more rather than registering an effect-free policy.
        fb = _fallback_policy(party_name, topic)
        primary = _safe_pairs(fb["primary"])
        secondary = _safe_pairs(fb["secondary"])

    policy_id = f"{party_id}_{topic}"
    POLICIES[policy_id] = {
        "name": str(raw.get("name", f"{party_name}'s {topic} plan"))[:80],
        "primary": primary,
        "secondary": secondary,
        "delayed": [],
        "tags": [topic],
    }
    generated[topic] = policy_id
    return policy_id
