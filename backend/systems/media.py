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
