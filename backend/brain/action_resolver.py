"""
brain/action_resolver.py

Resolves a free-text target description ("the woman in the red dress",
"the fridge") against the real candidate ids build_available_actions()
already computed — deterministic fuzzy string matching, not an LLM call.

Why fuzzy strings and not a real vector search: this codebase's old
similarity module (deleted — it was a SHA-256 hash tiled into floats, not
real semantic vectors, so similarity between two paraphrases of the same
concept was close to random noise) confirmed that route is a dead end
without standing up real vectors, which would mean a new Ollama call per
resolution — a direct violation of this overhaul's
single-LLM-call-per-decision constraint. Fuzzy string matching is a good
fit here anyway: candidate pools are always small (≤8 nearby people, ≤15
known contacts, a handful of props), and target_description is drawn from
vocabulary the prompt itself just handed the model (names, tags,
descriptions already in brain/context_builder.py's output), so token
overlap against those same source strings is close to an oracle — this
isn't the open-vocabulary retrieval problem a real vector search would
solve.

Currently a no-op hook: agent_loop.py::process_decision() only calls
resolve_target() when action.get("target_description") is set and
action.get("target") is not — the pre-Round-7 envelope never sets
target_description, so this round ships fully inert on the live schema
until Round 7 flips the response format. Round 6's own verification
confirms that inertness directly (see plan).
"""

import difflib
import re

ACCEPT_THRESHOLD = 0.55
AMBIGUITY_MARGIN = 0.12

_STOPWORDS = {
    "the", "a", "an", "with", "in", "on", "at", "of", "and", "who", "that",
    "is", "wearing", "standing", "near", "your", "you", "to", "it",
}


def _normalize(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t and t not in _STOPWORDS]
    return " ".join(tokens)


def _token_set_f1(a_tokens, b_tokens):
    a, b = set(a_tokens), set(b_tokens)
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    if overlap == 0:
        return 0.0
    precision = overlap / len(a)
    recall = overlap / len(b)
    return 2 * precision * recall / (precision + recall)


def _score(desc, bag_strings):
    """Score a free-text description against a candidate's text bag
    (list of strings — name, tags, description, etc.). Returns 0..1.
    Exported for reuse: Round 8's describe action aspect matching, Round
    9's recall memory-text matching, interact's `detail` matching against
    a prop's own interactions list.
    """
    norm_desc = _normalize(desc)
    if not norm_desc:
        return 0.0
    desc_tokens = norm_desc.split()

    best = 0.0
    for raw in bag_strings:
        if not raw:
            continue
        norm_bag = _normalize(raw)
        if not norm_bag:
            continue

        # Exact-id match handled by the caller (ids aren't normalized text).
        if norm_desc == norm_bag:
            best = max(best, 0.95)
            continue

        # name as a whole word in the description
        if norm_bag and re.search(rf"\b{re.escape(norm_bag)}\b", norm_desc):
            best = max(best, 0.90)
            continue

        # description as a whole phrase in the bag string
        if norm_desc and re.search(rf"\b{re.escape(norm_desc)}\b", norm_bag):
            best = max(best, 0.85)
            continue

        bag_tokens = norm_bag.split()
        f1 = _token_set_f1(desc_tokens, bag_tokens)
        ratio = difflib.SequenceMatcher(None, norm_desc, norm_bag).ratio()
        combined = min(0.80, 0.6 * f1 + 0.4 * ratio)
        best = max(best, combined)

    return best


def _character_bag(entry):
    bag = [entry.get("name")]
    if entry.get("description"):
        bag.append(entry["description"])
    if entry.get("relationship"):
        bag.append(entry["relationship"])
    if entry.get("activity"):
        bag.append(entry["activity"])
    return [b for b in bag if b]


def _prop_bag(entry):
    bag = [entry.get("template")]
    bag.extend(entry.get("tags") or [])
    bag.extend(entry.get("interactions") or [])
    return [b for b in bag if b]


def _contact_bag(entry):
    bag = [entry.get("name")]
    if entry.get("relationship"):
        bag.append(entry["relationship"])
    return [b for b in bag if b]


def _generic_bag(entry):
    bag = [entry.get("name"), entry.get("kind"), entry.get("slot"), entry.get("topic")]
    return [b for b in bag if b]


_POOL_KEYS = {
    "prop": ("interactable_props", _prop_bag),
    "character": ("nearby_characters", _character_bag),
    "contact": ("known_contacts", _contact_bag),
    "item": ("held_stack_names", _generic_bag),
    "device": ("snoopable_devices", _generic_bag),
    "proposal": ("open_proposals", _generic_bag),
    "wall": ("nearby_walls", _generic_bag),
}


def _candidate_pool(kind, available_actions):
    """Return [(id, bag_strings)] for one target kind."""
    if kind == "prop_or_character":
        props = _candidate_pool("prop", available_actions)
        chars = _candidate_pool("character", available_actions)
        return props + chars
    if kind == "any":
        pool = []
        for k in ("character", "prop", "contact", "item", "device", "proposal"):
            pool.extend(_candidate_pool(k, available_actions))
        return pool

    spec = _POOL_KEYS.get(kind)
    if not spec:
        return []
    list_key, bag_fn = spec
    entries = available_actions.get(list_key) or []
    out = []
    for entry in entries:
        eid = entry.get("id") or entry.get("item_id") or entry.get("proposal_id") or entry.get("wall_id")
        if not eid:
            continue
        out.append((eid, bag_fn(entry)))
    return out


def resolve_target(c, world, action_type, description, available_actions):
    """Resolve a free-text target description against the real candidate
    ids for this action type (via systems/action_registry.py's target
    spec). Returns:
        {"id": str|None, "score": float, "kind": str,
         "ranked": [(id, score), ...], "ambiguous": bool}
    id is None when nothing clears ACCEPT_THRESHOLD, or when the top two
    candidates are within AMBIGUITY_MARGIN of each other (ambiguous=True).
    """
    from systems.action_registry import ACTION_SPECS

    spec = ACTION_SPECS.get(action_type, {})
    kind = spec.get("target", "any")

    if kind == "none" or not description:
        return {"id": None, "score": 0.0, "kind": kind, "ranked": [], "ambiguous": False}

    pool = _candidate_pool(kind, available_actions)

    ranked = sorted(
        ((cid, _score(description, bag)) for cid, bag in pool),
        key=lambda pair: pair[1],
        reverse=True,
    )

    if not ranked:
        from brain.cognition_scheduler import record_resolver_outcome
        record_resolver_outcome("fail")
        return {"id": None, "score": 0.0, "kind": kind, "ranked": [], "ambiguous": False}

    top_id, top_score = ranked[0]
    ambiguous = (
        len(ranked) > 1
        and top_score - ranked[1][1] < AMBIGUITY_MARGIN
        and top_score >= ACCEPT_THRESHOLD
    )

    from brain.cognition_scheduler import record_resolver_outcome

    if top_score < ACCEPT_THRESHOLD or ambiguous:
        record_resolver_outcome("ambiguous" if ambiguous else "fail")
        return {
            "id": None, "score": top_score, "kind": kind,
            "ranked": ranked[:5], "ambiguous": ambiguous,
        }

    record_resolver_outcome("accept")
    return {
        "id": top_id, "score": top_score, "kind": kind,
        "ranked": ranked[:5], "ambiguous": False,
    }


def resolve_and_apply(c, world, action, available_actions):
    """Mutate action["target"] in place from action["target_description"]
    if present and target isn't already set. On failure, stage a
    corrective description and wake the character for one retry (shares
    Round 10's turn budget) instead of silently wasting the tick — a real
    improvement over the old silent-drop-on-unresolvable-target behavior.
    Returns True if a target was resolved or none was needed, False if the
    action should be treated as failed this tick (staged + rescheduled).
    """
    description = action.get("target_description")
    if not description or action.get("target"):
        return True

    result = resolve_target(c, world, action.get("type", ""), description, available_actions)
    if result["id"] is not None:
        action["target"] = result["id"]
        return True

    if result["kind"] in ("none",):
        return True

    from brain.cognition_scheduler import wake_character
    if result["ambiguous"]:
        options = ", ".join(f'"{cid}"' for cid, _ in result["ranked"][:3])
        text = (
            f"You reach for \"{description}\" but there's more than one thing "
            f"that could match ({options}) — you'll need to be more specific."
        )
    else:
        text = (
            f"You reach for \"{description}\" but there's nothing here matching "
            f"that."
        )
    cog = c.setdefault("cognition", {})
    cog.setdefault("staged_knowledge", []).append(text)
    wake_character(c, world, "resolution_failed")
    return False
