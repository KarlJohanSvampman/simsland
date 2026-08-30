import json
from llm.llm_client import call_llm_safe

# =========================================================
# PROJECT POST ENGAGEMENT
# =========================================================
# Narrow-purpose LLM call, modeled on social_interpretation.py's
# generate_social_interpretation() (own bespoke prompt, own session key,
# STRICT JSON out). Given a just-created post, asks the model to judge
# the content and project how it lands: total views/comments/new
# followers it'll accumulate, and how many hours it stays active in
# people's feeds. systems/social_media.py spreads those totals out over
# that many hours rather than applying them all at once.


async def generate_post_engagement(c, world, post):
    session = c.setdefault(
        "post_engagement_sessions", {}
    ).setdefault(post["id"], {"history": []})

    media_note = ""
    if post.get("media"):
        media_note = f"\nMedia: {post['media'].get('description', '')} ({post['media'].get('kind', 'photo')})"

    prompt = f"""
A character just posted on social media.

Author: {c.get("name", "Someone")}
Post text: "{post['text']}"{media_note}
Author's current popularity score: {c.get("popularity", 0.0):.0f}
Author's current followers: {c.get("followers", 0)}

Judge how interesting, relatable, or well-crafted this post is, and
project its eventual engagement over its lifetime. A mundane check-in
post should get modest numbers; a genuinely interesting, funny, or
striking post (especially with real content in the media description)
should get much more. Respond with STRICT JSON only, no other text:
{{"views": <int>, "comments": <int>, "followers_gained": <int>, "active_hours": <int, 1-72>}}
"""

    messages = [
        {
            "role": "system",
            "content": "You estimate social media post engagement based on content quality. Return STRICT JSON only.",
        },
        {"role": "user", "content": prompt},
    ]

    result = await call_llm_safe(messages, session=session, char_id=c.get("id"))

    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return json.loads(text)
    except Exception:
        return None
