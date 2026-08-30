"""
systems/stories.py

A character's own running, capped, ranked list of "stories" worth
telling other people -- distinct from brain/memory.py's own memories
list (everything a character remembers), this is specifically the
subset they'd actually bring up in conversation, scored so the best
ones surface first and get told before they go stale.

c["notable_stories"][i] = {
    "id", "summary", "category", "tags", "value" (0-100, decays daily),
    "created_tick", "about_people" (char ids), "told_to" (char ids),
    "best_audience" (char ids, ranked -- see predict_best_audience()),
    "source_memory_id",
}

evaluate_story_worthiness(c, mem) is called from brain/memory.py::
store_memory() itself (the near-universal call site every notable event
already goes through) -- no new hooks needed at each individual calling
system, with one confirmed exception (nudity_perception.py's walked-in-
on reactions didn't call store_memory at all, fixed there directly).
"""

import random
import uuid

STORY_CAP = 8
STORY_WORTHY_THRESHOLD = 0.55   # same 0-1 scale as mem["importance"]
STORY_DECAY_RATE = 0.97         # per day, mirrors grievances.py's DECAY_RATE shape

STORY_CATEGORIES = (
    "shock", "humor", "informative", "gossip",
    "ridicule", "suspicious_activity", "unusual_behavior",
)

# Per-category keyword weights -- same shape as brain/memory.py::
# score_importance()'s own fixed keyword-bucket check, just split by
# category instead of one flat bonus.
CATEGORY_KEYWORDS = {
    "shock":              {"death", "died", "attack", "fight", "blood", "accident", "shot", "assault", "fire"},
    "humor":               {"laugh", "funny", "joke", "embarrassing", "fell", "tripped", "prank"},
    "informative":         {"job", "opportunity", "warning", "danger", "closed", "opening", "price", "hiring"},
    "gossip":              {"affair", "cheat", "secret", "rumor", "breakup", "divorce", "pregnant", "dating"},
    "ridicule":            {"humiliat", "embarrassed", "caught", "walked in", "rejected", "laughed at"},
    "suspicious_activity": {"suspicious", "sneaking", "lying", "hiding", "stole", "theft", "creepy", "snooping"},
    "unusual_behavior":    {"strange", "odd", "unusual", "bizarre", "weird", "out of character"},
}

CATEGORY_BASE_WEIGHT = {
    "shock": 1.2, "humor": 0.9, "informative": 0.8, "gossip": 1.0,
    "ridicule": 1.0, "suspicious_activity": 1.0, "unusual_behavior": 0.85,
}


def _classify_category(text, explicit=None):
    if explicit in STORY_CATEGORIES:
        return explicit
    lowered = (text or "").lower()
    best_cat, best_hits = None, 0
    for cat, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best_cat, best_hits = cat, hits
    return best_cat


def evaluate_story_worthiness(c, mem, category=None, value_override=None):
    """Call right after a memory is stored (store_memory() does this
    automatically). Classifies + scores + maybe adds to
    c["notable_stories"]. No world needed -- everything comes off mem
    itself; the one thing that DOES need world (best-audience
    prediction) is computed lazily the first time it's actually needed,
    not here."""
    if mem.get("kind") == "story_archive":
        return None  # archive_story()'s own store_memory call -- don't loop

    importance = mem.get("importance", 0.0)
    if importance < STORY_WORTHY_THRESHOLD and value_override is None:
        return None

    cat = _classify_category(mem.get("text", ""), category)
    if not cat:
        return None

    base = value_override if value_override is not None else importance
    value = min(100.0, base * 100 * CATEGORY_BASE_WEIGHT.get(cat, 1.0))
    if value < STORY_WORTHY_THRESHOLD * 100 * 0.8:
        return None

    return add_story(
        c, summary=mem.get("text", ""), category=cat,
        tags=list(mem.get("tags", [])), value=value,
        about_people=list(mem.get("people", [])),
        source_memory_id=mem.get("id"), tick=mem.get("tick", 0),
    )


def add_story(c, summary, category, tags, value, about_people, source_memory_id=None, tick=0):
    stories = c.setdefault("notable_stories", [])
    entry = {
        "id":               f"story_{uuid.uuid4().hex[:8]}",
        "summary":          summary,
        "category":         category,
        "tags":             tags,
        "value":            round(value, 1),
        "created_tick":     tick,
        "about_people":     about_people,
        "told_to":          [],
        "best_audience":    [],
        "source_memory_id": source_memory_id,
    }
    stories.append(entry)
    stories.sort(key=lambda s: s["value"], reverse=True)
    if len(stories) > STORY_CAP:
        evicted = stories.pop()  # lowest value -- list is sorted descending
        archive_story(c, evicted)
    c["notable_stories"] = stories
    return entry


def decay_stories(c):
    """Daily cadence (see sim_loop.py) -- mirrors grievances.py::
    decay_grievances()'s slow multiplicative shape."""
    for s in c.get("notable_stories", []):
        s["value"] = round(s["value"] * STORY_DECAY_RATE, 2)
    c.get("notable_stories", []).sort(key=lambda s: s["value"], reverse=True)


def archive_story(c, story, world=None):
    """Eviction path -- condenses into a short long-term memory record.
    Real LLM condensation when world is available (llm/
    story_condensation.py); deterministic truncate fallback otherwise --
    same "never leave it blank" rule every other LLM-backed narrator in
    this codebase already follows."""
    condensed = None
    if world is not None:
        try:
            from llm.story_condensation import condense_story
            condensed = condense_story(c, story, world)
        except Exception:
            condensed = None
    if not condensed:
        text = story.get("summary", "")
        condensed = (text[:117] + "...") if len(text) > 120 else text

    from brain.memory import store_memory
    store_memory(
        c, condensed, importance=0.3, tags=story.get("tags", []),
        kind="story_archive", tick=story.get("created_tick", 0),
        people=story.get("about_people", []), category=story.get("category"),
    )


# ── Best-audience prediction (Phase B) ────────────────────────────────────

_CATEGORY_VALUE_MAP = {
    "gossip": "friends", "ridicule": "friends", "shock": "community",
    "suspicious_activity": "community", "informative": "work",
    "humor": "leisure", "unusual_behavior": "community",
}


def _topic_relevance(other, story):
    """0-1 -- crude but real: does this person's own values, or their
    own relationship to the people in the story, make them plausibly
    more interested? Reuses the same "shared vocabulary" idea
    persona_expectations.py/attraction.py already lean on elsewhere,
    rather than inventing a new scoring language."""
    vcat = _CATEGORY_VALUE_MAP.get(story.get("category"))
    base = other.get("values", {}).get(vcat, {}).get("importance", 0.5) if vcat else 0.5

    about = set(story.get("about_people", []))
    knows_bonus = 0.3 if about & set(other.get("relationships", {}).keys()) else 0.0

    return min(1.0, base * 0.7 + knows_bonus)


def predict_best_audience(c, world, story, top_n=3):
    """Ranked char ids c believes would have the most interest in this
    story -- relationship closeness x topic relevance x not-already-
    told. Computed once (cached on story["best_audience"]) -- Confirmed
    Decision #8, not re-scored every tick."""
    if story.get("best_audience"):
        return story["best_audience"]

    chars = world.get("characters", {})
    told = set(story.get("told_to", []))
    scored = []
    for oid, rel in c.get("relationships", {}).items():
        if oid in told:
            continue
        other = chars.get(oid)
        if not other:
            continue
        closeness = (rel.get("friendship", 0) + rel.get("trust", 0)) / 200.0
        relevance = _topic_relevance(other, story)
        scored.append((closeness * 0.5 + relevance * 0.5, oid))
    scored.sort(key=lambda x: -x[0])

    ranked = [oid for _, oid in scored[:top_n]]
    story["best_audience"] = ranked
    return ranked


# ── Telling a story / chain spread (Phase C) ──────────────────────────────

def get_story(c, story_id):
    return next((s for s in c.get("notable_stories", []) if s["id"] == story_id), None)


def tell_story(c, listener, story_id, world):
    """Routes through the real conversation pipeline (gossip speech_act)
    rather than a side channel -- conversation_analysis.py's gossip
    branch is what runs the listener's own re-evaluation (chain
    spread, see _maybe_adopt_story there)."""
    story = get_story(c, story_id)
    if not story:
        return False
    from systems.action_router import apply_speech
    apply_speech(c, world, {
        "target": listener["id"], "speech_act": "gossip",
        "topic": "story", "utterance": story["summary"],
    })
    if listener["id"] not in story["told_to"]:
        story["told_to"].append(listener["id"])
    return True
