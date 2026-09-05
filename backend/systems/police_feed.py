"""
systems/police_feed.py

Pulls real, live incident reports from the Swedish police's public RSS
feed (polisen.se) and folds them into this game's own news feed
(systems/media.py's world["news"]) plus the crime/traffic community
stats it already tracks as a random-walk drift (systems/
socioeconomics.py). This is a real-world-flavored NUDGE on top of that
existing drift, not a replacement for it -- "at least partly," per the
user's own framing. Real Swedish place names are swapped for a small
pool of fictional local ones before anything reaches a player.

Network access: a single synchronous urllib.request.urlopen() call,
wrapped in try/except -- the same "a slow-cadence external call inside
the sim tick must never crash the loop on a network hiccup" precedent
action_router.py's Wikipedia lookup (_route_computer_wiki_research)
already established. xml.etree.ElementTree (stdlib) parses the feed --
no new dependency.
"""

import random
import re
import urllib.request
import uuid
import xml.etree.ElementTree as ET

# This fetch runs synchronously inside sim_loop.py's own tick, which has
# no background-thread/async infrastructure to offload it to (confirmed
# via research -- the one other external-HTTP precedent,
# action_router.py's Wikipedia lookup, is itself a blocking call, just
# scoped to a single action's request rather than the whole world tick).
# A short timeout bounds the worst case to a brief pause rather than a
# multi-second stall; a slow/unresponsive feed just fails this cadence
# and quietly retries next time (see tick_police_feed's try/except).
FEED_URL = "https://polisen.se/aktuellt/rss/hela-landet/handelser-i-hela-landet/"
FETCH_TIMEOUT_SECONDS = 3
MAX_NEW_ITEMS_PER_FETCH = 5   # avoid a catch-up flood on first run / after downtime
SEEN_GUIDS_CAP = 500

# Fictional local place names this game's own news substitutes for
# whatever real Swedish city/neighborhood the feed names -- no local
# place/street-name generator exists anywhere else in this codebase to
# reuse (confirmed via research), so this is new, small, flavor-only
# content, not tied to any specific in-game building/address.
LOCAL_PLACE_NAMES = [
    "Riverside", "Old Town", "Northgate", "Lakeside", "the Harbor District",
    "Maple Heights", "the East End", "Fairview", "Millbrook", "Downtown",
]

# Swedish event-type string, exactly as it appears in the feed's title
# (lowercased) -> (category, community_stats_config key it nudges (or
# None), per-hit nudge amount). Unrecognized event types are skipped
# outright (see tick_police_feed) rather than guessed at -- the feed's
# own vocabulary isn't documented anywhere, this is built from observed
# samples only (confirmed against ~200 live items while building this).
# Deliberately NOT mapped, and confirmed common in real traffic: "Övrigt"
# (miscellaneous -- too vague to classify), "Djur" (animal-related),
# "Trafikkontroll" (a routine checkpoint, not an incident), "Farligt
# föremål" (a suspicious object report), "Försvunnen person" (a missing-
# person report) -- these fall through resolve_category() and produce no
# news item / stat nudge at all.
EVENT_TYPE_MAP = {
    "trafikolycka":          ("traffic_accident",     "traffic_accident_rate", 0.05),
    "trafikolycka, vilt":    ("traffic_accident",      "traffic_accident_rate", 0.02),
    "trafikbrott":           ("traffic_violation",     "traffic_accident_rate", 0.01),
    "olovlig körning":       ("traffic_violation",     "traffic_accident_rate", 0.01),
    "rattfylleri":           ("dui",                   "nonviolent_crime_rate", 0.03),
    "misshandel":            ("assault",               "violent_crime_rate",    0.03),
    "misshandel, grov":      ("assault",               "violent_crime_rate",    0.06),
    "mord/dråp":             ("homicide",              "violent_crime_rate",    0.10),
    "rån":                   ("robbery",               "violent_crime_rate",    0.05),
    "rån, grovt":            ("robbery",               "violent_crime_rate",    0.08),
    "knivlagen":             ("weapons",               "violent_crime_rate",    0.02),
    "olaga hot":             ("threats",               "violent_crime_rate",    0.02),
    "sexualbrott":           ("sexual_assault",        "violent_crime_rate",    0.05),
    "inbrott":               ("burglary",              "nonviolent_crime_rate", 0.03),
    "inbrott, försök":       ("burglary",              "nonviolent_crime_rate", 0.015),
    "stöld":                 ("theft",                 "nonviolent_crime_rate", 0.02),
    "stöld, grov":           ("theft",                 "nonviolent_crime_rate", 0.04),
    "tillgrepp av fortskaffningsmedel": ("theft",       "nonviolent_crime_rate", 0.02),
    "stöld/inbrott":         ("theft",                 "nonviolent_crime_rate", 0.03),
    "larm inbrott":          ("burglary",              "nonviolent_crime_rate", 0.01),
    "olaga intrång":         ("trespassing",           "nonviolent_crime_rate", 0.01),
    "skadegörelse":          ("vandalism",             "nonviolent_crime_rate", 0.015),
    "narkotikabrott":        ("drug_crime",            "nonviolent_crime_rate", 0.02),
    "bedrägeri":             ("fraud",                 "nonviolent_crime_rate", 0.02),
    "alkohollagen":          ("alcohol_violation",     "nonviolent_crime_rate", 0.01),
    "fylleri":               ("public_intoxication",   None,                    0),
    "brand":                 ("fire",                  None,                    0),
    "anträffad död":         ("found_deceased",        None,                    0),
    "brand, misstänkt anlagd": ("arson",                "violent_crime_rate",    0.03),
}

# A title is sometimes prefixed with "Uppdaterad YYYY-MM-DD HH:MM:SS "
# (a follow-up/correction to an earlier report) before the normal
# "DATE TIME, TYPE[, QUALIFIER], LOCATION" pattern -- confirmed by
# fetching the live feed directly (~20% of a real sample carried this
# prefix). Stripped, not treated as its own field.
_UPDATED_PREFIX_RE = re.compile(r"^\s*Uppdaterad\s+[\d-]+\s+[\d:]+\s+")
_TITLE_RE = re.compile(
    r"^\s*\d{1,2}\s+\S+\s+\d{1,2}[:.]\d{2},\s*(?P<rest>.+)$"
)


def parse_title(title):
    """"4 september 21.59, Trafikolycka, Nyköping" ->
    ("trafikolycka", "Nyköping"). The field(s) between the timestamp and
    the final comma-separated location are the event type (sometimes a
    qualifier too, e.g. "Misshandel, grov" or "Trafikolycka, singel") --
    rejoined with ", " and lowercased to key into EVENT_TYPE_MAP; if
    that full (possibly-qualified) form isn't in the map, falls back to
    just the first part alone (e.g. "trafikolycka" from "trafikolycka,
    singel") -- a qualifier narrows the flavor, not the underlying
    category, and enumerating every real qualifier combination isn't
    feasible from a handful of samples."""
    title = _UPDATED_PREFIX_RE.sub("", title or "")
    m = _TITLE_RE.match(title)
    if not m:
        return None, None
    parts = [p.strip() for p in m.group("rest").split(",")]
    if len(parts) < 2:
        return None, None
    location = parts[-1]
    event_type = ", ".join(parts[:-1]).lower()
    return event_type, location


def resolve_category(event_type):
    """EVENT_TYPE_MAP lookup with the qualifier-fallback described in
    parse_title() -- tries the full string first, then just its first
    comma-part."""
    if not event_type:
        return None, None, 0
    if event_type in EVENT_TYPE_MAP:
        return EVENT_TYPE_MAP[event_type]
    first_part = event_type.split(",")[0].strip()
    return EVENT_TYPE_MAP.get(first_part, (None, None, 0))


def _fetch_feed_items():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    items = []
    for item in root.iter("item"):
        guid = (item.findtext("guid") or "").strip()
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        if guid and title:
            items.append({"guid": guid, "title": title, "description": description})
    return items


def _nudge_stat(world, defs, key, delta):
    if not key:
        return
    cfg = (defs.get("community_stats_config") or {}).get(key, {})
    env = world.setdefault("environment", {})
    lo = cfg.get("min", 0)
    hi = cfg.get("max", 1e9)
    current = env.get(key, cfg.get("value", 0))
    env[key] = round(max(lo, min(hi, current + delta)), 4)


def tick_police_feed(world, defs):
    """Called on a slow cadence (core/tick_schedule.py::CADENCE
    ["police_feed"]). Fetches the feed, skips anything already processed
    (world["_police_feed_seen"], keyed by the feed's own <guid>), and
    folds up to MAX_NEW_ITEMS_PER_FETCH brand-new items into
    world["news"] plus a small nudge to the matching crime/traffic stat.
    Network/parse failures are swallowed entirely -- same "a bad tick
    from an external service must never take down the sim" precedent
    action_router.py's Wikipedia lookup already established."""
    try:
        items = _fetch_feed_items()
    except Exception:
        return

    seen = world.setdefault("_police_feed_seen", [])
    seen_set = set(seen)
    new_items = [it for it in items if it["guid"] not in seen_set]
    if not new_items:
        return

    # Feed lists newest first; walk the new batch oldest-first so the
    # news feed reads in chronological order, capped per fetch.
    for it in list(reversed(new_items))[-MAX_NEW_ITEMS_PER_FETCH:]:
        seen.append(it["guid"])
        event_type, _location = parse_title(it["title"])
        if not event_type:
            continue
        category, stat_key, nudge = resolve_category(event_type)
        if not category:
            continue

        local_place = random.choice(LOCAL_PLACE_NAMES)
        headline = f"{category.replace('_', ' ').title()} reported in {local_place}"

        world.setdefault("news", []).append({
            "id":                f"news_{uuid.uuid4().hex[:6]}",
            "type":              "news",
            "headline":          headline,
            "summary":           it["description"] or headline,
            "sentiment":         "negative",
            "intensity":         0.5,
            "tags":              [category, "crime" if stat_key else "local"],
            "related_entities":  [],
            "source":            "police_feed",
            "tick":              world.get("tick", 0),
        })
        world["news"] = world["news"][-50:]

        _nudge_stat(world, defs, stat_key, nudge)

    world["_police_feed_seen"] = seen[-SEEN_GUIDS_CAP:]
