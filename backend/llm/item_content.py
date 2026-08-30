import json
from llm.llm_client import call_llm_safe

# =========================================================
# ITEM CONTENT GENERATION
# =========================================================
# Narrow-purpose LLM call, modeled on post_engagement.py's
# generate_post_engagement() (own bespoke prompt, own session key,
# STRICT JSON out). Gives a freshly-created book/magazine/dvd/music_disc
# instance real per-instance content (title/author/etc.) so many
# instances of one shared-model item_template read as genuinely distinct
# objects. Newspapers deliberately do NOT go through this -- their
# "content" at read time is a real world["news"] item, not generated
# text (see systems/reading_process.py), so "newspaper" is never passed
# here.

_PROMPTS = {
    "book": (
        "a physical book",
        '{"title": <str>, "author": <str>, "genre": <str>, "blurb": <str, 1-2 sentences>}',
    ),
    "magazine": (
        "a magazine issue",
        '{"title": <str>, "issue_topic": <str>, "cover_line": <str, one punchy sentence>}',
    ),
    "dvd": (
        "a DVD movie",
        '{"title": <str>, "genre": <str>, "synopsis": <str, 1-2 sentences>}',
    ),
    "music_disc": (
        "a music CD",
        '{"album": <str>, "artist": <str>, "genre": <str>, "tracklist": [<str>, ...] (4-8 track titles)}',
    ),
}


async def generate_item_content(c, world, item):
    content_category = item.get("content_category")
    spec = _PROMPTS.get(content_category)
    if not spec:
        return None
    noun, schema = spec

    session = world.setdefault(
        "_item_content_sessions", {}
    ).setdefault(item["id"], {"history": []})

    owner_note = f"\nBeing generated for: {c.get('name', 'someone')}" if c else ""

    prompt = f"""
Invent {noun} for a life-simulation game. Make it feel like a real,
specific, slightly quirky object rather than a generic placeholder --
give it a genuine title and voice.{owner_note}

Respond with STRICT JSON only, no other text: {schema}
"""

    messages = [
        {
            "role": "system",
            "content": f"You invent flavorful, specific content for {noun}s in a life-simulation game. Return STRICT JSON only.",
        },
        {"role": "user", "content": prompt},
    ]

    result = await call_llm_safe(messages, session=session, char_id=c.get("id") if c else None)

    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


# Never-empty fallback content per category -- an item must never end up
# with no content at all, even if the LLM is unreachable or returns
# something unparseable.
_FALLBACK_CONTENT = {
    "book": {"title": "Untitled Novel", "author": "Unknown Author", "genre": "fiction",
              "blurb": "A worn paperback with no dust jacket left to say what it's about."},
    "magazine": {"title": "Weekly Digest", "issue_topic": "general interest",
                  "cover_line": "This week's stories, in brief."},
    "dvd": {"title": "Untitled Feature", "genre": "drama",
             "synopsis": "The case art has faded past readability."},
    "music_disc": {"album": "Untitled", "artist": "Unknown Artist", "genre": "assorted",
                    "tracklist": ["Track 1", "Track 2", "Track 3", "Track 4"]},
}


def fallback_content(content_category):
    return dict(_FALLBACK_CONTENT.get(content_category, {"title": "Untitled"}))
