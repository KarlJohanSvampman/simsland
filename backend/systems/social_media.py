"""
systems/social_media.py

Public social-media posts -- world["social_posts"], a flat broadcast
feed. Distinct from mail.py's household mailbox and inbox.py's business
inbox (both are private, per-recipient); a post is visible to anyone
browsing (action_router.py's computer_social_media / phone social-media
actions), tagged "type": "social_post" to match those systems' own
type-tagging convention even though a post doesn't live inside either
of their per-recipient structures.

media (photo/video) is metadata-only -- {"kind": "photo"|"video",
"description": str, "subjects": [char_id, ...]} -- not an actual
rendered image. The backend tick loop has no renderer (Three.js only
runs in a connected browser), so a REAL screenshot can only ever exist
when a live client happens to be rendering that character at that exact
moment; descriptive media is what makes "posting a photo" work
uniformly whether or not anyone's watching. Wiring an actual Three.js
capture into this metadata when a browser IS connected is a deliberately
separate, later piece.

Every post gets an LLM-projected engagement envelope (post["engagement"])
-- total views/comments/new-followers it'll accumulate and how many
hours it stays active -- via llm/post_engagement.py, applied gradually
by tick_post_engagement() (see systems/validation.py for the scoring
those numbers feed into) rather than all at once at post time. A real
like/comment from an actual simulated character (like_post/
comment_on_post below) is separate and immediate -- both layers add up
for display.
"""

import uuid

DEFAULT_ENGAGEMENT_ACTIVE_HOURS = 24


def create_post(c, world, text, media=None, tags=None):
    """media: optional {"kind": "photo"|"video", "description": str,
    "subjects": [char_id, ...]}."""
    about_ids = _find_mentioned_characters(world, text, exclude_id=c["id"])
    if media:
        about_ids = sorted(set(about_ids) | {
            sid for sid in media.get("subjects", []) if sid != c["id"]
        })

    post = {
        "id": f"post_{uuid.uuid4().hex[:8]}",
        "type": "social_post",
        "author_id": c["id"],
        "text": text,
        "media": media,
        "tags": tags or [],
        "tick": world.get("tick", 0),
        "views": [],      # char_ids who've seen it, deduped
        "likes": [],      # char_ids
        "comments": [],   # [{"id", "author_id", "text", "tick"}]
        "about_character_ids": about_ids,
    }
    world.setdefault("social_posts", []).append(post)
    _project_engagement(c, world, post)
    _notify_mentioned_characters(c, world, post)
    return post


# Per the ChatGPT-proposed social_media.post.about_self situation
# (evaluated against this codebase and adopted where it fit): seeing a
# post ABOUT yourself shouldn't require you to happen to be browsing --
# a person finds out sooner or later regardless, often from someone else
# entirely. Detected by matching another living character's full display
# name in the post text (not just first name, to keep false positives
# low) -- simple, but doesn't require the LLM to correctly supply real
# character ids it may not actually know for a name it's just narrating.
def _find_mentioned_characters(world, text, exclude_id):
    if not text:
        return []
    lowered = text.lower()
    found = []
    for cid, other in world.get("characters", {}).items():
        if cid == exclude_id or not other.get("alive", True):
            continue
        name = other.get("name")
        if name and name.lower() in lowered:
            found.append(cid)
    return found


def _notify_mentioned_characters(c, world, post):
    """Per the proposal's own architectural point: seeing a post is not
    equivalent to knowing its truth -- this only ever surfaces "there's a
    post mentioning you" as a real, scored situation (brain/situations/)
    for the mentioned character to eventually notice and react to in
    their own words; it never writes anything about them being true.
    Uses systems/social_intentions.py's target-scoped add_social_intention
    (dedupes by type+target_id) rather than brain/intentions.py's plain
    add_intention (which only dedupes by type -- would collide across
    different post authors).

    A post tagged "rumor" (see systems/action_registry.py's
    post_social_media doc -- the LLM is told to tag it this way when
    repeating an unverified claim) wakes with "rumor_about_self" instead
    of "post_about_self": a genuinely different, higher-priority
    situation (middleware/simsland_mw/situations/library/reactions.py)
    about managing an unverified claim, not just an ordinary mention."""
    about_ids = post.get("about_character_ids") or []
    if not about_ids:
        return

    from systems.social_intentions import add_social_intention
    from brain.cognition_scheduler import wake_character

    is_rumor = "rumor" in (post.get("tags") or [])
    reason = "rumor_about_self" if is_rumor else "post_about_self"
    tick = world.get("tick", 0)
    for target_id in about_ids:
        target = world.get("characters", {}).get(target_id)
        if not target:
            continue
        add_social_intention(target, {
            "type":        reason,
            "category":    "social",
            "target_id":   c["id"],
            "priority":    75 if is_rumor else 55,
            "reason":      "rumor_about_you_online" if is_rumor else "someone_posted_about_you",
            "created_at":  tick,
            "source":      "social_media",
        })
        wake_character(target, world, reason, {
            "author_name": c.get("name", "someone"),
            "author_id":   c["id"],
            "post_id":     post["id"],
        })


def _project_engagement(c, world, post):
    projection = None
    try:
        from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND
        from llm.post_engagement import generate_post_engagement
        projection = run_llm_call(generate_post_engagement(c, world, post), priority=PRIORITY_BACKGROUND)
    except Exception:
        projection = None

    if not projection:
        # Deterministic fallback, scaled by the author's existing
        # standing -- an already-popular character's posts land bigger,
        # same real-world dynamic the LLM path judges on content quality
        # for.
        base = 10 + c.get("popularity", 0.0) * 0.5 + c.get("followers", 0) * 0.3
        projection = {
            "views": max(1, round(base)),
            "comments": max(0, round(base * 0.15)),
            "followers_gained": max(0, round(base * 0.05)),
            "active_hours": DEFAULT_ENGAGEMENT_ACTIVE_HOURS,
        }

    try:
        active_hours = max(1, min(168, int(projection.get("active_hours") or DEFAULT_ENGAGEMENT_ACTIVE_HOURS)))
    except (TypeError, ValueError):
        active_hours = DEFAULT_ENGAGEMENT_ACTIVE_HOURS

    from systems.validation import TICKS_PER_HOUR
    post["engagement"] = {
        "projected_views":     max(0, int(projection.get("views") or 0)),
        "projected_comments":  max(0, int(projection.get("comments") or 0)),
        "projected_followers": max(0, int(projection.get("followers_gained") or 0)),
        "active_hours":        active_hours,
        "granted_views":       0.0,
        "granted_comments":    0.0,
        "granted_followers":   0.0,
        "expires_tick":        world.get("tick", 0) + active_hours * TICKS_PER_HOUR,
    }


def tick_post_engagement(world):
    """Called once per sim-hour (see sim_loop.py) -- spreads each active
    post's LLM-projected engagement evenly across its active_hours,
    crediting the author's popularity/validation as it lands instead of
    all at once at post time."""
    from systems.validation import receive_validation
    tick = world.get("tick", 0)
    chars = world.get("characters", {})

    for post in world.get("social_posts", []):
        eng = post.get("engagement")
        if not eng or tick >= eng["expires_tick"]:
            continue
        author = chars.get(post["author_id"])
        if not author:
            continue

        per_hour_views = eng["projected_views"] / eng["active_hours"]
        per_hour_comments = eng["projected_comments"] / eng["active_hours"]
        per_hour_followers = eng["projected_followers"] / eng["active_hours"]

        eng["granted_views"] = min(eng["projected_views"], eng["granted_views"] + per_hour_views)
        eng["granted_comments"] = min(eng["projected_comments"], eng["granted_comments"] + per_hour_comments)

        prior_followers = eng["granted_followers"]
        eng["granted_followers"] = min(eng["projected_followers"], prior_followers + per_hour_followers)
        new_followers = int(eng["granted_followers"]) - int(prior_followers)
        if new_followers > 0:
            author["followers"] = author.get("followers", 0) + new_followers

        points = per_hour_views * 0.1 + per_hour_comments * 1.0 + max(0, new_followers) * 2.0
        if points > 0:
            receive_validation(author, world, points=points, source="social_media_engagement")


def _find_post(world, post_id):
    return next((p for p in world.get("social_posts", []) if p["id"] == post_id), None)


def view_post(c, world, post_id):
    post = _find_post(world, post_id)
    if not post:
        return False
    if c["id"] not in post["views"]:
        post["views"].append(c["id"])
        _apply_rumor_exposure(c, world, post)
    return True


def _apply_rumor_exposure(viewer, world, post):
    """Seeing a rumor post is itself a real information-transmission
    event, through the SAME machinery direct gossip uses (brain/
    opinions.py's person:<id> attitude, trust-scaled, source_id-tracked)
    -- belief/opinion spec sections 100-101: "all information sources
    flow through the same epistemic system," not a second, parallel
    social-media-specific rumor structure. Only fires for a genuine
    OBSERVER -- not the rumor's own author (their belief doesn't move
    from reading their own post) and not its subject (their reaction to
    being talked about is the separate rumor_about_self wake in
    _notify_mentioned_characters, a decision, not a passive belief
    update about themselves)."""
    if "rumor" not in (post.get("tags") or []):
        return
    author_id = post.get("author_id")
    if viewer["id"] == author_id:
        return

    from brain.opinions import nudge_opinion, get_current_opinion
    from brain.cognition_scheduler import wake_character

    chars = world.get("characters", {})
    author = chars.get(author_id)
    viewer_trust_in_author = viewer.get(
        "relationships", {}
    ).get(author_id, {}).get("trust", 0)
    credence = max(0.1, min(1.0, 0.35 + viewer_trust_in_author / 250.0))
    tick = world.get("tick", 0)

    for subject_id in post.get("about_character_ids") or []:
        if subject_id == viewer["id"]:
            continue

        # Prefer the AUTHOR's own real, already-formed opinion of the
        # subject (same "pick something real, don't fabricate" rule
        # systems/conversation_analysis.py's gossip handling follows) --
        # only falls back to an assumed-negative default when the author
        # has no formed opinion to draw from, since a rumor severe enough
        # to post publicly skews negative in practice; a real "claim"
        # field on the post recording actual sentiment would let this be
        # precise instead of assumed, and is a reasonable later upgrade.
        author_opinion = get_current_opinion(author, f"person:{subject_id}") if author else None
        sentiment = "negative"
        if author_opinion is not None:
            sentiment = "positive" if author_opinion["stance"] >= 0 else "negative"

        nudge_opinion(
            viewer, f"person:{subject_id}", sentiment, 0.25 * credence, tick,
            reasoning=f"saw a rumor online, posted by {author.get('name', 'someone') if author else 'someone'}",
            source_id=author_id,
        )

        subject = chars.get(subject_id)
        wake_character(viewer, world, "rumor_seen", {
            "post_id":     post["id"],
            "subject_id":  subject_id,
            "subject_name": subject.get("name", "someone") if subject else "someone",
            "author_id":   author_id,
            "author_name": author.get("name", "someone") if author else "someone",
        })


def like_post(c, world, post_id):
    post = _find_post(world, post_id)
    if not post:
        return False
    if c["id"] not in post["likes"]:
        post["likes"].append(c["id"])
        author = world.get("characters", {}).get(post["author_id"])
        if author and author["id"] != c["id"]:
            from systems.validation import receive_validation, BASE_VALIDATION_POINTS
            receive_validation(author, world, points=BASE_VALIDATION_POINTS * 0.5, source="like")
    view_post(c, world, post_id)
    return True


def unlike_post(c, world, post_id):
    post = _find_post(world, post_id)
    if not post:
        return False
    if c["id"] in post["likes"]:
        post["likes"].remove(c["id"])
    return True


def comment_on_post(c, world, post_id, text):
    post = _find_post(world, post_id)
    if not post:
        return None
    comment = {
        "id": f"comment_{uuid.uuid4().hex[:6]}",
        "author_id": c["id"],
        "text": text,
        "tick": world.get("tick", 0),
    }
    post["comments"].append(comment)
    author = world.get("characters", {}).get(post["author_id"])
    if author and author["id"] != c["id"]:
        from systems.validation import receive_validation, BASE_VALIDATION_POINTS
        receive_validation(author, world, points=BASE_VALIDATION_POINTS, source="comment")
    view_post(c, world, post_id)
    return comment


def recent_feed(world, limit=20):
    return sorted(world.get("social_posts", []), key=lambda p: p["tick"], reverse=True)[:limit]
