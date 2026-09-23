import random, uuid
from data.public_figures import PUBLIC_FIGURES

# Confirmed live bug (real player report): world["news"] was trimmed to
# a flat last-50 with no notion of source, and police_feed.py's real,
# actively-fetched live items (systems/police_feed.py) were getting
# crowded out entirely by this generator's own more-frequent procedural
# stories -- confirmed live: up to 500 real feed items had been
# processed, zero survived in the visible last-50 window. Reserving a
# real slice of the cap for a given source means it can still be pushed
# out by NEWER items of its own kind, just never by an unrelated source
# simply publishing more often.
NEWS_TOTAL_CAP = 50
NEWS_RESERVED_SOURCE = "police_feed"
NEWS_RESERVED_SLOTS = 15


def trim_news(world):
    news = world.get("news", [])
    reserved = [n for n in news if n.get("source") == NEWS_RESERVED_SOURCE][-NEWS_RESERVED_SLOTS:]
    other = [n for n in news if n.get("source") != NEWS_RESERVED_SOURCE][-(NEWS_TOTAL_CAP - NEWS_RESERVED_SLOTS):]
    merged = reserved + other
    merged.sort(key=lambda n: n.get("tick", 0))
    world["news"] = merged


def generate_news(world):
    media = world.get(
        "media",
        []
    )

    if not media:
        return

    outlet = random.choice(
        media
    )
    pf=random.choices(PUBLIC_FIGURES, weights=[p.get("importance",.5) for p in PUBLIC_FIGURES], k=1)[0]; tag=random.choice(pf.get("tags",["society"]))
    sentiment="negative" if outlet.get("bias")=="anti_tax" and "tax" in tag else "positive" if outlet.get("bias")=="pro_tax" and "tax" in tag else random.choice(["positive","negative","neutral"])
    world.setdefault("news",[]).append({"id":f"news_{uuid.uuid4().hex[:6]}","type":"news","headline":f"{pf['name']} addresses {tag}","summary":f"{outlet['name']} reports on {pf['role']} {pf['name']} and {tag}.","sentiment":sentiment,"intensity":pf.get("importance",.5),"tags":[tag],"related_entities":[pf["id"]],"source":outlet["id"],"tick":world["tick"]})
    trim_news(world)
def generate_biased_news(world, event=None): generate_news(world)


# =========================================================
# PER-CHARACTER SOURCE TRUST
# =========================================================
# world["media"] entries (see systems/schema_defaults.py) have carried
# "credibility"/"sensationalism" fields on every outlet since they were
# first added, but confirmed dead before this: nothing anywhere ever
# read them, so news from a "trustworthy" outlet and a "sensationalist"
# one swayed every character's opinions identically. This gives each
# character their OWN trust in a SPECIFIC outlet, reusing brain/
# opinions.py's exact stance+confidence shape (topic=f"source:{id}")
# instead of a bespoke structure, so it's debuggable/inspectable the
# same way any other opinion already is.

def get_source_trust(c, outlet, world):
    """Character-specific trust in a specific news outlet. Seeds once
    (from the outlet's own base credibility, mildly skewed by the
    character's own generic institutional "media" opinion when they've
    formed one -- see brain/opinions.py's IDEOLOGY_AXES -- a character
    who already distrusts media in general starts more skeptical of any
    specific outlet too, more so for a sensationalist one) and is
    otherwise left for real events (systems/influence.py, fact-checking,
    ...) to nudge over time via the same nudge_opinion() every other
    opinion topic uses. Returns the current opinion snapshot (stance
    -1..1, confidence 0..1)."""
    from brain.opinions import get_current_opinion, update_opinion

    topic = f"source:{outlet.get('id')}"
    existing = get_current_opinion(c, topic)
    if existing is not None:
        return existing

    base_stance = (outlet.get("credibility", 0.5) - 0.5) * 2
    generic_media = get_current_opinion(c, "media")
    if generic_media is not None:
        base_stance += generic_media["stance"] * 0.3
        if generic_media["stance"] < 0:
            base_stance -= outlet.get("sensationalism", 0.3) * 0.2
    base_stance = max(-1.0, min(1.0, base_stance))

    return update_opinion(
        c, topic, base_stance, 0.25,
        f"first impression of {outlet.get('name', outlet.get('id'))}",
        [], world.get("tick", 0),
    )
