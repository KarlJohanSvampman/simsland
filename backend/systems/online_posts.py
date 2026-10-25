"""
systems/online_posts.py -- what is posted ABOUT someone online (docs/relationship_impact_plan.md, section 6: "Online").

A post that names other characters and carries a rumor/gossip/praise/lie is the written version of a remark about a third
person (systems/rumors.py). It is public, so it works in two directions:

  1. READERS weigh it. Whoever reads the post (not its author, not the person it is about) goes through the same
     credibility step as a spoken remark -- trust in the author, fondness for the subject -- and, if they believe it, their
     own feelings about the subject shift a little, they remember "X posted about Y", and they become believers of the
     rumor (so they may mention it to the subject themselves, systems/rumors.py).
  2. The SUBJECT learns of it when they read it. Then it is delivered straight to them on the `post` channel: the ordinary
     evaluation ladder runs for them and, if it registers, it is written on the (author, subject) pair -- which is where a
     grudge can open against the author. Each subject gets it once.

What a post is: `post["remark"] = {"kinds": {subject_id: kind}}` set when it is created. The kind per subject comes from
what the author declared (`intent.valence`: hurt -> meanness, deceive -> slander, help -> compliment) or, for a post tagged
"rumor"/"gossip", from the author's own standing opinion of that person (fond -> a compliment, otherwise meanness). A post
that merely mentions someone, with no such sign, is not a remark and is left to systems/social_media.py as before.

Reading happens when a character finishes browsing social media (`browse`: a few unread posts, the ones about them first,
then those by people they know), when they like or comment on a post, and by chance: a subject who has not seen a post
about them comes across it at DISCOVER_CHANCE per check (someone sends them the link, they see it in passing).
"""

import random

from core.event_bus import emit, subscribe

HOUR = 3600
POST_LIFETIME_TICKS = 72 * HOUR
DISCOVER_CHANCE = 0.02          # per check (every 5 sim-minutes), per undelivered subject, while the post is fresh
BROWSE_COUNT = 4
BROWSE_ACTIVITIES = {"computer_social_media"}
SCAN_LAST = 100                 # posts looked at by the discovery check
GOSSIP_TAGS = {"rumor", "gossip"}


def _kind_for(post, author, subject_id):
    """The impact kind of this post as it concerns `subject_id`, or None."""
    from systems.rumors import remark_kind
    intent = post.get("intent")
    kind = remark_kind(None, intent) if isinstance(intent, dict) else None
    if kind:
        return kind
    if GOSSIP_TAGS & set(post.get("tags") or []):
        from brain.opinions import get_current_opinion
        opinion = get_current_opinion(author, f"person:{subject_id}")
        return "compliment" if opinion is not None and opinion.get("stance", 0) >= 0 else "meanness"
    return None


def tag_remark(post, author, world):
    """Called when a post is created: note which of the people it names it is a remark about, and of what kind."""
    kinds = {}
    for sid in post.get("about_character_ids") or []:
        if sid == author["id"]:
            continue
        kind = _kind_for(post, author, sid)
        if kind:
            kinds[sid] = kind
    if kinds:
        post["remark"] = {"kinds": kinds, "delivered": []}
    return kinds


def on_read(reader, world, post):
    """Called the first time `reader` views `post`."""
    remark = post.get("remark")
    if not remark or reader["id"] == post.get("author_id"):
        return
    chars = world.get("characters", {})
    author = chars.get(post["author_id"])
    if not author:
        return
    text = (post.get("text") or "")[:160]
    ref = {"type": "post", "id": post["id"]}
    for sid, kind in remark["kinds"].items():
        if sid == reader["id"]:
            if sid in remark["delivered"]:
                continue
            remark["delivered"].append(sid)
            _deliver_to_subject(world, post, author, reader, kind, text, ref)
        elif sid in chars:
            from systems.rumors import emit_remark
            emit_remark(author, reader, sid, kind, text=text, discretion=0.1, ref=ref, via="post")


def _deliver_to_subject(world, post, author, subject, kind, text, ref):
    emit("impact_intent", {
        "source_id": author["id"], "target_id": subject["id"], "kind": kind, "magnitude": None,
        "discretion": 0.1, "channel": "post", "audience": "targets", "volume": "low",
        "text": text, "ref": ref, "mentions": [], "victim_id": None, "memory_refs": [],
    })
    try:
        from brain.memory import store_memory
        what = "said nice things about" if kind == "compliment" else "posted about"
        store_memory(subject, f"I read a post where {author['name']} {what} me: \"{text}\".", importance=0.55,
                     tags=["post", "heard_about_me"], people=[author["id"]], tick=world.get("tick", 0), source="heard")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def browse(reader, world, count=BROWSE_COUNT):
    """The reader scrolls the feed: a few unread recent posts -- those about them first, then by people they know, then
    the newest."""
    from systems.social_media import view_post
    tick = world.get("tick", 0)
    rels = reader.get("relationships") or {}

    def rank(p):
        about = reader["id"] in (p.get("about_character_ids") or [])
        known = (rels.get(p["author_id"]) or {}).get("familiarity", 0) or 0
        return (not about, -known, -p.get("tick", 0))

    unread = [p for p in world.get("social_posts", [])
              if p["author_id"] != reader["id"] and reader["id"] not in p.get("views", [])
              and tick - p.get("tick", 0) <= POST_LIFETIME_TICKS]
    read = sorted(unread, key=rank)[:count]
    for p in read:
        view_post(reader, world, p["id"])
    return read


def _on_activity_completed(data, world):
    if data.get("activity_type") not in BROWSE_ACTIVITIES:
        return
    c = world.get("characters", {}).get(data.get("character_id"))
    if c:
        browse(c, world)


def tick_post_discovery(world):
    """Scheduled job: a subject who has not seen a fresh post about them may come across it."""
    from systems.social_media import view_post
    tick = world.get("tick", 0)
    chars = world.get("characters", {})
    for post in world.get("social_posts", [])[-SCAN_LAST:]:
        remark = post.get("remark")
        if not remark or tick - post.get("tick", 0) > POST_LIFETIME_TICKS:
            continue
        for sid in remark["kinds"]:
            subject = chars.get(sid)
            if (not subject or sid in remark["delivered"] or subject.get("alive") is False or subject.get("off_grid")
                    or (subject.get("activity") or {}).get("type") == "sleep"):
                continue
            if random.random() < DISCOVER_CHANCE:
                view_post(subject, world, post["id"])


subscribe("activity_completed", _on_activity_completed)
