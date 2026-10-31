"""
systems/fights.py -- what a fight was about, who was in it, and the record of it.

A fight comes out of a conflict (systems/conflict_pipeline.py: the grievances brought to the table are what it is about) or out of a
one-off outburst (impulse, gang war, sports rivalry, romantic rivalry, a revenge attack: `context`). Each leaves an entry in
`world["fight_log"]`:

    {"id", "tick", "conflict_id", "parties", "aggressor", "topic", "issues", "context", "outcome", "peak", "place", "witnesses",
     "intervener", "incident_id", "police_report_id"}

and the memories of the people in it say who and what ("Had a fight with Lena about the dishes; it turned physical"). When a physical
fight is called in, the incident (systems/emergency.py) carries the same topic and parties, and the police report
(systems/police_report.py) is written from them.
"""

import uuid

FIGHT_LOG_CAP = 300

# a grievance's event_type -> how it reads in "a fight about ..."
ISSUE_PHRASES = {
    "insulted": "being insulted", "threatened": "a threat", "betrayed": "a betrayal", "contract_violated": "a broken agreement",
    "ate_my_food": "food being eaten that wasn't theirs", "stole": "something being taken", "loud_at_night": "the noise at night",
    "left_mess": "the mess left lying around", "neglected_plants": "the neglected plants", "flirting_with_partner": "flirting with their partner",
    "excluded": "being left out", "lied": "a lie", "broke_promise": "a broken promise", "disrespected": "feeling disrespected",
    "family_dinner_skipped": "a family dinner that got skipped", "promised_errand_broken": "an errand that was promised and never done",
    "restricted_freedom": "being kept on a short leash", "value_clash": "clashing values", "identity_shame": "feeling shamed for who they are",
    "porn_shame": "feeling shamed over porn", "sexual_curiosity_shame": "feeling shamed over curiosity",
    "favor_unreciprocated": "favours that were never returned", "life_envy": "envy over how the other one lives",
    "team_rivalry": "the rival teams", "gang_violence": "gang trouble", "resource_conflict": "who gets what",
    "ignored_me": "being ignored", "romantic_envy": "jealousy over love", "partner_jealousy": "jealousy over a partner",
    "status_envy": "envy over status", "career_envy": "envy over a career", "social_envy": "envy over friends",
    "opportunity_envy": "envy over an opportunity", "rejected_advance": "a rejected advance",
    "ignored_rejection": "an advance that would not take no for an answer", "witnessed_transgression": "something heard through the grapevine",
    "romantic_rivalry": "a romantic rivalry", "fight_loss_humiliation": "the humiliation of an earlier fight",
    "family_pregnancy_shock": "the pregnancy news", "family_abortion_conflict": "a decision about a pregnancy",
    "family_adoption_grief": "grief over an adoption", "family_pregnancy_obligation": "what is owed because of the pregnancy",
    "family_social_shame": "shame in front of the family", "family_birth_event": "the birth",
    "father_family_blamed": "who the father is to blame", "mother_family_blamed": "who the mother is to blame",
    "sexual_harassment": "harassment", "partner_harassed": "a partner being harassed", "verbal_harassment": "verbal harassment",
    "absence_unresolved": "the unexplained absences", "absence_lie_caught": "a lie about where they had been",
}

# the emitters of "fight_physical" that have no conflict behind them
CONTEXT_PHRASES = {
    "impulsive_assault": "a sudden flare of temper", "gang_war": "gang rivalry", "sports_rivalry": "a sports rivalry",
    "romantic_rivalry": "a romantic rivalry", "domestic_revenge_direct": "years of being pushed around at home",
}

STAGE_WORDS = {"verbal_dispute": "a quarrel", "heated_argument": "a heated argument", "shouting_match": "a shouting match",
               "physical_altercation": "a physical fight"}


def name_of(world, cid):
    return ((world.get("characters") or {}).get(cid) or {}).get("name") or "someone"


def names(world, ids):
    out = [name_of(world, i) for i in ids]
    return out[0] if len(out) == 1 else ", ".join(out[:-1]) + " and " + out[-1] if out else "someone"


def _join(phrases):
    phrases = list(dict.fromkeys(phrases))
    if not phrases:
        return ""
    return phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " and " + phrases[-1]


def topic_of(issues=None, context=None):
    """"the noise at night and the mess left lying around"; falls back on the context, then on 'something that had been building'."""
    phrases = [ISSUE_PHRASES.get(i) or str(i).replace("_", " ") for i in (issues or [])]
    if phrases:
        return _join(phrases[:3])
    if context in CONTEXT_PHRASES:
        return CONTEXT_PHRASES[context]
    return "something that had been building for a while"


def place_of(world, c):
    """Where a character is, in words: 'the kitchen at home' style, from the building and room names."""
    building = next((b for b in world.get("buildings", []) if b.get("id") == c.get("building_id")), None)
    room = c.get("room_id")
    bname = (building or {}).get("name") or (building or {}).get("type") or None
    room_name = None
    for r in (building or {}).get("rooms") or []:
        if isinstance(r, dict) and r.get("id") == room:
            room_name = r.get("name") or r.get("type")
    bits = [b for b in (room_name, bname) if b]
    return " in ".join(bits) if bits else "somewhere"


def witnesses_of(world, party_ids, location=None):
    """Others who were there (same room, else same building), not children small enough to be left out of an interview."""
    chars = world.get("characters") or {}
    here = [chars[p] for p in party_ids if p in chars]
    if not here:
        return []
    rooms = {c.get("room_id") for c in here if c.get("room_id")}
    buildings = {c.get("building_id") for c in here if c.get("building_id")}
    out = []
    for cid, c in chars.items():
        if cid in party_ids or c.get("alive") is False or c.get("off_grid"):
            continue
        if (c.get("age") or 30) < 12:
            continue
        if (c.get("room_id") and c.get("room_id") in rooms) or (not rooms and c.get("building_id") in buildings):
            out.append(cid)
    return out


def peak_stage(conflict):
    """The worst the quarrel got before it ended: from the stage reached (the conflict records the stage it is at)."""
    return conflict.get("peak_stage") or conflict.get("fight_stage")


def log_fight(world, parties, topic, outcome, aggressor=None, context=None, conflict=None, issues=None, incident_id=None, witnesses=None):
    chars = world.get("characters") or {}
    anchor = next((chars[p] for p in parties if p in chars), None)
    entry = {
        "id": f"fight_{uuid.uuid4().hex[:6]}", "tick": world.get("tick", 0), "conflict_id": (conflict or {}).get("id"), "parties": list(parties),
        "aggressor": aggressor, "topic": topic, "issues": list(issues or (conflict or {}).get("issues") or []), "context": context,
        "outcome": outcome, "peak": peak_stage(conflict or {}) if conflict else None,
        "place": place_of(world, anchor) if anchor else "somewhere",
        "witnesses": list(witnesses if witnesses is not None else witnesses_of(world, parties)),
        "intervener": next((e.get("by") for e in (conflict or {}).get("log", []) if e.get("event") == "intervention"), None),
        "incident_id": incident_id, "police_report_id": None,
    }
    log = world.setdefault("fight_log", [])
    log.append(entry)
    del log[:-FIGHT_LOG_CAP]
    return entry


def fight_for_conflict(world, conflict_id):
    return next((f for f in reversed(world.get("fight_log") or []) if conflict_id and f.get("conflict_id") == conflict_id), None)


def memory_line(world, c, others, topic, outcome, conflict=None, aggressor=None):
    """What a character remembers of a fight: with whom, about what, how it went."""
    who = names(world, others)
    peak = STAGE_WORDS.get(peak_stage(conflict or {}) or "", None)
    if outcome == "physical_resolved":
        started = ""
        if aggressor and aggressor != c["id"]:
            started = f" {name_of(world, aggressor)} threw the first punch."
        elif aggressor == c["id"]:
            started = " I lashed out first."
        return f"Had a fight with {who} about {topic} that turned physical.{started}"
    if outcome == "storm_off":
        leaver = next((e.get("by") for e in (conflict or {}).get("log", []) if e.get("event") == "storm_off"), None)
        by = "I stormed off" if leaver == c["id"] else f"{name_of(world, leaver)} stormed off" if leaver else "somebody stormed off"
        return f"Had {peak or 'a fight'} with {who} about {topic}; {by}."
    if outcome == "cold_shoulder":
        return f"Argued with {who} about {topic} and it ended in a cold silence."
    if outcome == "intervention":
        by = next((e.get("by") for e in (conflict or {}).get("log", []) if e.get("event") == "intervention"), None)
        return f"Had {peak or 'a fight'} with {who} about {topic} until {name_of(world, by) if by else 'someone'} stepped in."
    if outcome == "de_escalated":
        return f"Started to argue with {who} about {topic} but we both cooled down."
    if outcome == "agreement":
        return f"Talked {topic} through with {who} and we agreed how to handle it."
    return f"Had a fight with {who} about {topic}."
