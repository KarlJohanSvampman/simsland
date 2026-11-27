"""
systems/conversation_acts.py -- what a character is going for when they talk to someone: one act, picked from the
situation, and the AI writes the conversation inside it (the user, 2026-11-27: "I want them to pick one type in the
end based on situation and have the AI generate conversation within that context").

The acts:

    request     ask for something -- help, an item, a lift, time
    inquiry     ask to know -- their day, plans, how they are, what they think
    criticism   point out what they did wrong and what you expect instead
    debate      disagree about an idea, an opinion or a decision
    praise      praise / encourage -- thank, compliment, cheer them on
    discipline  discipline / discourage -- set a limit, correct, warn off a bad plan
    flirt       show romantic or playful interest
    rage        blow up -- yell, accuse, threaten
    suggest     propose an idea, an activity, a plan
    compromise  offer a middle ground
    negotiate   bargain -- trade favours, set terms

Each act is scored for one partner from the drivers in the user's table:

    intention / plans    what they're trying to get done (and whether it needs this person), what they plan next
    standing             trust, friendship, respect, hostility and resentment toward them; kinship; authority
    my mood              emotion and temperature (brain/emotion.py)
    their mood           how the other seems -- weighed by empathy (traits): an empathetic person holds back a
                         criticism when the other is down, and encourages instead
    stress               their stress
    things in common     shared hobbies, home, work, school
    what's open          grievances against them, open issues between them, a request they turned down

and by traits (hot-tempered, flirtatious, diplomatic, judgmental, conformist, validation-seeking, ...). The highest
score wins -- one act, with a topic and a few words on how -- shown in the character's prompt
(brain/context_builder.py, section "conversation_act") for:

  * the person they're in a conversation with (their reply follows what the other just did: a criticism is met with
    debate, a compromise or -- if hot -- rage; a request with negotiation; a flirt with a flirt, or a polite no);
  * someone who just spoke to them;
  * otherwise, up to two people close by, when something is strong enough to say.

The pick is remembered (c["_conv_acts"][other_id]); when they then speak to that person the line carries the act
(systems/action_router.py::apply_speech -> history "conv_act", and the speech act the older tone / relationship
analysis reacts to: praise -> compliment, rage -> insult, criticism -> accuse, ...).
"""

import random

ACTS = ("request", "inquiry", "criticism", "debate", "praise", "discipline", "flirt", "rage", "suggest",
        "compromise", "negotiate")

LABEL = {"request": "REQUEST", "inquiry": "INQUIRY", "criticism": "CRITICISM", "debate": "DEBATE",
         "praise": "PRAISE / ENCOURAGE", "discipline": "DISCIPLINE / DISCOURAGE", "flirt": "FLIRT", "rage": "RAGE",
         "suggest": "SUGGEST", "compromise": "COMPROMISE", "negotiate": "NEGOTIATE"}

# what the line is, for the older systems that react to a speech act (systems/conversation_analysis.py, CPL purposes)
SPEECH_ACT = {"request": "request", "inquiry": "question", "criticism": "accuse", "debate": "argue",
              "praise": "compliment", "discipline": "challenge", "flirt": "flirt", "rage": "insult",
              "suggest": "suggest", "compromise": "compromise", "negotiate": "argue"}

# how to say it (the prompt)
HOW = {
    "request": "Ask for it plainly and say why you need it.",
    "inquiry": "Ask, and actually want the answer -- one real question, not small talk filler.",
    "criticism": "Say what they did and what you expect instead. Stick to the one thing.",
    "debate": "Say what you think and why; take on their point instead of repeating yours.",
    "praise": "Say what they did well, or that you believe they can do it -- specifically.",
    "discipline": "Set the limit or warn them off clearly, and give the reason.",
    "flirt": "Light and playful -- a compliment, a tease or an invitation; let them answer.",
    "rage": "You've had enough and it comes out -- angry, blunt, maybe loud. Say what it's about.",
    "suggest": "Propose something concrete -- what, when, where.",
    "compromise": "Offer a middle ground both of you can live with.",
    "negotiate": "Make an offer: what you'll give for what you want.",
}

# answering what the other just did: how much each act fits as a reply
RESPONSES = {
    "request":    {"negotiate": 2.0, "inquiry": 1.0, "compromise": 1.0, "suggest": 1.0, "criticism": 0.5},
    "inquiry":    {"suggest": 1.0, "inquiry": 0.8, "praise": 0.6, "debate": 0.6, "request": 0.4},
    "criticism":  {"debate": 2.0, "compromise": 1.5, "criticism": 1.0, "rage": 0.8, "negotiate": 0.6},
    "debate":     {"debate": 2.0, "compromise": 1.5, "criticism": 0.6, "negotiate": 0.6},
    "praise":     {"praise": 1.5, "inquiry": 1.0, "flirt": 0.6, "suggest": 0.6},
    "discipline": {"debate": 1.5, "negotiate": 1.5, "compromise": 1.0, "rage": 0.6},
    "flirt":      {"flirt": 2.0, "inquiry": 0.6, "discipline": 0.6},
    "rage":       {"rage": 1.5, "compromise": 1.0, "discipline": 1.0, "criticism": 1.0},
    "suggest":    {"negotiate": 1.0, "compromise": 1.0, "suggest": 1.0, "inquiry": 0.6, "praise": 0.4},
    "compromise": {"compromise": 1.5, "praise": 1.0, "negotiate": 1.0},
    "negotiate":  {"negotiate": 2.0, "compromise": 2.0},
}

EMPATHIC = {"empathetic", "compassionate", "supportive", "thoughtful", "selfless", "perceptive", "protective", "fair"}
UNFEELING = {"cruel", "selfish", "inconsiderate", "apathetic", "ruthless", "egotistical", "spiteful", "vindictive"}
UPSET = {"sad", "anxious", "angry", "furious", "annoyed", "irritable", "fearful", "lonely", "agony", "melancholy"}
GOOD_MOOD = {"cheerful", "content", "calm", "excited", "euphoric", "ecstatic", "warm", "playful", "focused"}

ACT_TTL_S = 15 * 60          # how long a pick stays the act for that person (then it's worked out again)
MIN_UNPROMPTED = 3.0         # an act strong enough to bring up with someone nearby, unprompted


# ── reading the situation ────────────────────────────────────────────────────────────────────────────────────────────

def _traits(c):
    try:
        from systems.personality_profile import effective_traits
        return set(effective_traits(c))
    except Exception:                                     # noqa: BLE001
        return set(c.get("traits") or [])


def _first(c):
    return (c.get("name") or "them").split(" ")[0]


def _temp(c):
    return float(c.get("emotional_temperature", 30) or 30)


def _rel(c, oid):
    return (c.get("relationships") or {}).get(oid) or {}


def _n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def empathy(c):
    t = _traits(c)
    return max(-1.0, min(1.0, 0.3 * len(t & EMPATHIC) - 0.4 * len(t & UNFEELING)))


def _is_kin(rel):
    return bool(rel.get("kinship")) and rel.get("kinship") != "spouse"


def _authority(c, other, rel):
    """c has a say over other: their parent / grandparent, or an adult over a child or teen at home."""
    if rel.get("kinship") in ("parent", "grandparent"):
        return True
    young = {"child", "toddler", "infant", "teen"}
    return (c.get("age_group") in ("adult", "elderly") and other.get("age_group") in young
            and c.get("household_id") and c.get("household_id") == other.get("household_id"))


def _adult(c):
    return c.get("age_group") in ("adult", "elderly", "young_adult") or (c.get("age") or 0) >= 18


def _grievance(c, oid, world):
    """The heaviest grievance c holds against oid: (weight, phrase)."""
    gs = [g for g in c.get("grievances") or [] if g.get("caused_by") == oid]
    if not gs:
        return 0.0, None
    g = max(gs, key=lambda g: _n(g.get("weight")))
    try:
        from systems.fights import ISSUE_PHRASES
        what = ISSUE_PHRASES.get(g.get("event_type")) or str(g.get("event_type") or "what they did").replace("_", " ")
    except Exception:                                     # noqa: BLE001
        what = str(g.get("event_type") or "what they did").replace("_", " ")
    return sum(_n(x.get("weight")) for x in gs), what


def _open_issue(c, oid, world):
    """The liveliest open issue between them: (heat 0-1, subject)."""
    best, subject = 0.0, None
    for iss in (world.get("social_issues") or {}).values():
        if iss.get("status") != "open":
            continue
        involved = set(iss.get("involved_parties") or []) | set(iss.get("affected_parties") or []) | set(
            (iss.get("positions") or {}).keys()) | {iss.get("created_by")}
        if c.get("id") not in involved or oid not in involved:
            continue
        heat = 0.3 + 0.7 * min(1.0, len(iss.get("events") or []) / 6)
        if heat > best:
            best, subject = heat, iss.get("subject")
    return best, subject


def _turned_down(c, oid, world):
    """A request c made to oid that was refused lately: its subject."""
    for r in (world.get("cpl_requests") or {}).values():
        if r.get("from") == c.get("id") and r.get("to") == oid and r.get("status") in ("rejected", "declined"):
            return r.get("summary") or r.get("subject") or r.get("text") or "what you asked for"
    return None


def _plan_with(c, other):
    """An intention of c's that involves the other person (or needs a hand): its words, or None."""
    name = (other.get("name") or "").split(" ")[0].lower()
    for i in c.get("active_intentions") or []:
        if i.get("target_id") == other.get("id") or (name and name in str(i.get("reason") or "").lower()):
            return str(i.get("reason") or i.get("type") or "").replace("_", " ")[:80]
    return None


def _needs_hand(c):
    """Something on c's plate they could use help with (a chore or errand), when stressed or busy."""
    for i in c.get("active_intentions") or []:
        if i.get("category") in ("chores", "errand", "errands", "household"):
            return str(i.get("type") or "").replace("_", " ")
    return None


def _common(c, other):
    """Things in common: shared hobbies first, then home / work / school."""
    out = []
    shared = sorted(set(c.get("hobbies") or []) & set(other.get("hobbies") or []))
    out += [h.replace("_", " ") for h in shared]
    if c.get("household_id") and c.get("household_id") == other.get("household_id"):
        out.append("home")
    cj, oj = (c.get("job") or {}), (other.get("job") or {})
    if isinstance(cj, dict) and isinstance(oj, dict) and cj.get("industry") and cj.get("industry") == oj.get("industry"):
        out.append(f"work in {cj['industry'].lower()}")
    if c.get("school_id") and c.get("school_id") == other.get("school_id"):
        out.append("school")
    return out


def _opinion_clash(c, other):
    """A topic they see differently (brain/opinions): the topic, or None."""
    def stance(x, topic):
        hist = (x.get("opinions") or {}).get(topic)
        if isinstance(hist, list) and hist:
            return _n(hist[-1].get("stance"))
        return None
    for topic in (c.get("opinions") or {}):
        a, b = stance(c, topic), stance(other, topic)
        if a is not None and b is not None and abs(a - b) >= 1.0:
            return str(topic).replace("_", " ")
    return None


def situation(c, other, world):
    """Everything the scoring reads, for c toward other."""
    oid = other.get("id")
    rel = _rel(c, oid)
    g_weight, g_what = _grievance(c, oid, world)
    issue_heat, issue = _open_issue(c, oid, world)
    standing = _n((rel.get("standing") or {}).get("score")) if isinstance(rel.get("standing"), dict) else 0.0
    warmth = (_n(rel.get("friendship")) + _n(rel.get("trust")) + _n(rel.get("respect"))) / 300.0      # -1..1
    hostility = (_n(rel.get("hostility")) + _n(rel.get("resentment"))) / 200.0                          # 0..1
    return {
        "rel": rel, "kin": _is_kin(rel), "spouse": rel.get("kinship") == "spouse" or "spouse" in (rel.get("labels") or []),
        "authority": _authority(c, other, rel), "standing": standing / 100.0, "warmth": warmth, "hostility": hostility,
        "attraction": max(_n(rel.get("attraction")), _n(rel.get("romantic_interest")), _n(rel.get("chemistry")) * 3) / 100.0,
        "grievance": min(1.0, g_weight / 20.0), "grievance_what": g_what,
        "issue_heat": issue_heat, "issue": issue, "turned_down": _turned_down(c, oid, world),
        "my_temp": _temp(c), "my_emotion": c.get("emotion") or "calm",
        "their_emotion": other.get("emotion") or "calm", "their_upset": (other.get("emotion") or "") in UPSET,
        "their_good": (other.get("emotion") or "") in GOOD_MOOD,
        "empathy": empathy(c), "stress": _n(c.get("stress")) / 100.0, "their_stress": _n(other.get("stress")) / 100.0,
        "plan": _plan_with(c, other), "needs_hand": _needs_hand(c), "common": _common(c, other),
        "clash": _opinion_clash(c, other), "traits": _traits(c),
        "adults": _adult(c) and _adult(other),
        "checkin": _checkin(c, other, world),
    }


def _checkin(c, other, world):
    """A check-in is due with them (systems/catch_up.py): why, or None."""
    try:
        from systems.catch_up import checkin_due
        return checkin_due(c, other, world)
    except Exception:                                     # noqa: BLE001
        return None


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def score(c, other, world, replying_to=None, s=None):
    """{act: (score, topic, why)} for c toward other. `replying_to`: the act the other just used on c."""
    s = s or situation(c, other, world)
    t = s["traits"]
    name = _first(other)
    hot = s["my_temp"] >= 65
    furious = s["my_temp"] >= 85
    held_back = s["their_upset"] and s["empathy"] > 0          # empathy: not now, they're down
    out = {}

    def put(act, value, topic, why):
        out[act] = (round(max(0.0, value), 2), topic, why)

    # request: a plan needs them, or a hand while stressed
    v, topic = 0.0, None
    if s["plan"]:
        v, topic = 2.5, s["plan"]
    elif s["needs_hand"] and (s["stress"] > 0.3 or "home" in s["common"]):
        v, topic = 1.5 + 2 * s["stress"], f"a hand with {s['needs_hand']}"
    if topic:
        v += 0.8 * max(0.0, s["warmth"]) - 1.5 * s["hostility"] - (1.0 if held_back else 0) - (2.0 if furious else 0)
        put("request", v, topic, "you need something from them")

    # inquiry: checking on them, curiosity, a gap in a plan
    v = 0.8 + (1.5 if "curious" in t else 0) + 0.5 * max(0.0, s["warmth"])
    topic = "what they've been up to"
    if s["their_upset"] and s["empathy"] >= 0:
        v += 1.5 + s["empathy"] * 1.5
        topic = f"how they're doing -- they seem {s['their_emotion']}"
    elif s["common"]:
        topic = f"{s['common'][0]} -- something you both care about"
    v -= 1.5 * s["hostility"] + (1.5 if furious else 0)
    why = "you want to know"
    if s["checkin"] and not furious and not (s["their_upset"] and s["empathy"] < 0):
        # first time today / a few hours apart: check in -- how they are, plans, yesterday / the weekend, and news on
        # something from before (systems/catch_up.py)
        from systems.catch_up import checkin_topic
        v += 4.0 - 2.0 * s["hostility"] - 3.0 * s["grievance"]      # a real grievance gets raised instead
        topic, why = checkin_topic(c, other, world), f"you haven't caught up with them -- {s['checkin']}"
        if s["their_upset"] and s["empathy"] >= 0:
            topic = f"{topic} (they seem {s['their_emotion']})"
    put("inquiry", v, topic, why)

    # criticism: a grievance or an open issue
    if s["grievance"] or s["issue_heat"]:
        v = 1.5 + 3 * s["grievance"] + 2 * s["issue_heat"] + (1.0 if hot else 0) + 1.5 * s["stress"]
        v += (1.0 if t & {"judgmental", "overcritical", "conformist", "controlling"} else 0)
        v -= (1.5 + s["empathy"]) if held_back else 0
        v -= 1.0 if t & {"diplomatic", "tactful", "passive"} else 0
        put("criticism", v, s["grievance_what"] or s["issue"], "something they did is bothering you")

    # debate: a decision or opinion they see differently
    if s["clash"] or s["issue"]:
        v = 1.2 + (1.0 if s["clash"] else 0) + 1.0 * s["issue_heat"] + (1.0 if t & {"stubborn", "competitive", "nonconformist", "rational", "cognition_logical"} else 0)
        v += 0.5 * max(0.0, s["warmth"])                       # people who respect each other argue
        v -= (1.0 if held_back else 0) + (1.0 if s["stress"] > 0.7 else 0)
        put("debate", v, s["clash"] or s["issue"], "you see it differently")

    # praise / encourage
    v = 0.6 + 1.5 * max(0.0, s["warmth"]) + (0.8 if s["my_emotion"] in GOOD_MOOD else 0)
    topic = "something they did well"
    if s["their_upset"] and s["empathy"] > 0:
        v += 1.5 + s["empathy"]
        topic = f"cheering them up -- they seem {s['their_emotion']}"
    v += 1.0 if t & {"supportive", "generous", "cheerful", "optimistic"} else 0
    v += 0.8 if "validation_seeking" in t else 0               # praising others, hoping for the same back
    v -= 2.0 * s["hostility"] + (2.0 if hot else 0)
    put("praise", v, topic, "they deserve to hear it")

    # discipline / discourage
    if s["authority"] or (s["warmth"] > 0.5 and s["issue"]):
        v = 1.0 + (1.5 if s["authority"] else 0) + 2.5 * s["grievance"] + 1.0 * s["issue_heat"] + (1.0 if hot else 0)
        v += 1.0 if t & {"disciplined", "strict", "controlling", "conformist", "protective", "responsible"} else 0
        v -= 0.8 if held_back else 0
        topic = s["grievance_what"] or s["issue"] or "how they've been behaving"
        put("discipline", v if (s["grievance"] or s["issue"] or s["authority"]) else 0, topic,
            "you have to set a limit")

    # flirt: adults, attraction, never family
    if s["adults"] and not s["kin"] and (s["attraction"] > 0.2 or s["spouse"]):
        v = 1.0 + 3 * s["attraction"] + (1.0 if s["spouse"] and s["warmth"] > 0 else 0)
        v += 1.5 if t & {"flirtatious", "romantic", "playful", "charismatic"} else 0
        v -= 3.0 * s["hostility"] + (2.5 if s["their_upset"] else 0) + (2.5 if hot else 0)
        topic = f"{s['common'][0]} as an opening" if s["common"] and s["common"][0] != "home" else "a compliment or an invitation"
        put("flirt", v, topic, "you're drawn to them")

    # rage: only when furious, and at someone it's about
    if furious and (s["grievance"] or s["issue_heat"] or s["hostility"] > 0.3):
        v = 2.0 + 3 * s["grievance"] + 2 * s["hostility"] + (s["my_temp"] - 85) / 5
        v += 1.5 if t & {"hot_tempered", "short_tempered", "aggressive", "impulsive", "low_self_control"} else 0
        v -= 1.5 if t & {"calm", "patient", "high_self_control", "diplomatic"} else 0
        try:
            from brain.emotion import explain
            about = explain(c, world)
        except Exception:                                 # noqa: BLE001
            about = ""
        put("rage", v, s["grievance_what"] or s["issue"] or about or "everything they've done", "you've had enough")

    # suggest: something to do together, or a fix for their problem
    v = 0.7 + (1.5 if s["common"] else 0) + (0.8 if s["my_emotion"] in GOOD_MOOD else 0) + 0.5 * max(0.0, s["warmth"])
    if s["common"] and s["common"][0] != "home":
        topic = f"doing some {s['common'][0]} together"
    elif s["their_upset"] and s["empathy"] > 0:
        topic, v = "something that would take their mind off it", v + 1.0
    else:
        topic = "something to do together"
    v -= 1.5 * s["hostility"] + (1.5 if hot else 0)
    put("suggest", v, topic, "you have an idea")

    # compromise: a clash in progress, and the relationship matters
    if s["issue_heat"] or s["grievance"] or replying_to in ("criticism", "debate", "negotiate", "rage", "discipline"):
        v = 1.0 + 1.5 * s["issue_heat"] + 1.0 * max(0.0, s["warmth"] + 0.3) + (1.0 if s["their_upset"] and s["empathy"] > 0 else 0)
        v += 1.2 if t & {"cooperative", "diplomatic", "fair", "forgiving", "tactful"} else 0
        v -= (1.5 if furious else 0) + (1.0 if t & {"stubborn", "competitive"} else 0)
        put("compromise", v, s["issue"] or s["grievance_what"] or "where you both stand", "you'd rather settle it")

    # negotiate: a no to a request, competing needs
    if s["turned_down"] or s["issue"] or replying_to in ("request", "discipline", "suggest"):
        v = 1.0 + (2.0 if s["turned_down"] else 0) + 1.0 * s["issue_heat"]
        v += 1.0 if t & {"practical", "resourceful", "ambitious", "manipulative", "rational"} else 0
        v -= 1.5 if furious else 0
        put("negotiate", v, s["turned_down"] or s["issue"] or "what each of you gets", "you want a deal")

    if replying_to in RESPONSES:                           # a reply follows what they just did
        for act, w in RESPONSES[replying_to].items():
            sc, topic, why = out.get(act, (0.0, None, ""))
            out[act] = (round(sc + 2.0 * w, 2), topic or "what they just said", why or "answering them")
    return out


def pick(c, other, world, replying_to=None, rng=None):
    """The one act for c toward other now: {act, label, topic, why, how, score, replying_to} -- or None."""
    scored = score(c, other, world, replying_to)
    if not scored:
        return None
    best = max(v[0] for v in scored.values())
    if best <= 0:
        return None
    # near-ties (within 10%) are a matter of the moment, not always the same one
    close = sorted(a for a, v in scored.items() if v[0] >= best * 0.9)
    rng = rng or random.Random(f"{c.get('id')}:{other.get('id')}:{int(world.get('tick', 0)) // 600}")
    act = rng.choice(close)
    sc, topic, why = scored[act]
    try:
        from systems.catch_up import recent_topics
        recent = recent_topics(c, other.get("id"))
    except Exception:                                     # noqa: BLE001
        recent = []
    return {"act": act, "label": LABEL[act], "topic": topic or "", "why": why, "how": HOW[act], "score": sc,
            "replying_to": replying_to, "with": other.get("id"), "recent": recent}


# ── the prompt, and the line that follows ────────────────────────────────────────────────────────────────────────────

def _now(world):
    try:
        from core.clock import now_ts
        return now_ts(world)
    except Exception:                                     # noqa: BLE001
        return float(world.get("tick", 0))


def _last_line_to(c, oid, world):
    """The other's last line in an active conversation with c: (conv_act, utterance) or (None, None)."""
    for conv in (world.get("conversations") or {}).values():
        if not conv.get("active") or c.get("id") not in (conv.get("participants") or []) or oid not in (conv.get("participants") or []):
            continue
        for h in reversed(conv.get("history") or []):
            if h.get("speaker") == oid:
                return h.get("conv_act"), h.get("utterance")
            if h.get("speaker") == c.get("id"):
                return None, None                         # they spoke since; nothing to answer
    return None, None


def partners(c, world):
    """Whom the act is for, most pressing first: [(other, why)] -- conversation partner, who just spoke, people close by."""
    chars = world.get("characters") or {}
    out, seen = [], set()
    for conv in (world.get("conversations") or {}).values():
        if conv.get("active") and c.get("id") in (conv.get("participants") or []):
            for pid in conv.get("participants") or []:
                if pid != c.get("id") and pid in chars and pid not in seen:
                    out.append((chars[pid], "conversation")); seen.add(pid)
    st = ((c.get("cognition") or {}).get("spoken_to") or {}).get("payload") or {}
    sid = st.get("speaker_id")
    if sid and sid in chars and sid not in seen:
        out.append((chars[sid], "spoken_to")); seen.add(sid)
    for p in sorted(((c.get("perception") or {}).get("visible_people") or []), key=lambda p: p.get("distance", 99)):
        pid = p.get("id")
        if pid and pid in chars and pid not in seen and pid != c.get("id") and (p.get("distance") or 0) <= 8:
            out.append((chars[pid], "nearby")); seen.add(pid)
    return out


def choose(c, world, limit=2):
    """The acts for this moment, remembered on c (c["_conv_acts"]), most pressing person first."""
    now = _now(world)
    picks = []
    for other, why in partners(c, world):
        if len(picks) >= limit:
            break
        if other.get("alive") is False or other.get("off_grid"):
            continue
        replying_to, said = _last_line_to(c, other.get("id"), world)
        if why == "spoken_to" and not replying_to:
            replying_to = (((other.get("_conv_acts") or {}).get(c.get("id")) or {}).get("act"))
        p = pick(c, other, world, replying_to)
        if not p:
            continue
        if why == "nearby" and p["score"] < MIN_UNPROMPTED:
            continue                                      # nothing worth bringing up with them right now
        p.update(context=why, said=said, ts=now, name=other.get("name") or "them")
        picks.append(p)
    acts = c.setdefault("_conv_acts", {})
    for k in [k for k, v in acts.items() if now - (v.get("ts") or 0) > ACT_TTL_S]:
        acts.pop(k, None)
    for p in picks:
        acts[p["with"]] = {k: p[k] for k in ("act", "topic", "ts", "replying_to")}
    return picks


def prompt_lines(c, world):
    """What the character is going for with whom (the "conversation_act" section)."""
    lines = []
    for p in choose(c, world):
        who = p["name"].split(" ")[0]
        about = f" -- about {p['topic']}" if p.get("topic") else ""
        if p["context"] in ("conversation", "spoken_to") and p.get("replying_to"):
            did = {"request": "asked you for something", "inquiry": "asked you something", "criticism": "criticised you",
                   "debate": "argued a point", "praise": "praised you", "discipline": "told you off",
                   "flirt": "flirted with you", "rage": "blew up at you", "suggest": "suggested something",
                   "compromise": "offered a compromise", "negotiate": "made you an offer"}.get(p["replying_to"], "spoke to you")
            lines.append(f"{who} {did}. Answer what {who} said -- your way of answering: {p['label']}{about}. {p['how']}")
        elif p["context"] in ("conversation", "spoken_to"):
            lines.append(f"Talking with {who}, you're going for: {p['label']}{about}. {p['how']}")
        else:
            lines.append(f"If you talk to {who} now, it would be: {p['label']}{about} ({p['why']}). {p['how']}")
        if p.get("recent"):
            lines.append(f"What you've talked about with {who} before: {'; '.join(p['recent'])}.")
    if lines:
        lines.append("Write what you say inside that -- in your own voice, about the actual thing.")
    return lines


def stamp_speech(c, speech, world, target=None):
    """A line to someone c has an act for carries it: conv_act, and the speech act the older systems react to."""
    target = target or (speech or {}).get("target")
    entry = ((c.get("_conv_acts") or {}).get(target) or {}) if target else {}
    if not entry or _now(world) - (entry.get("ts") or 0) > ACT_TTL_S:
        return None
    speech["conv_act"] = entry["act"]
    if speech.get("speech_act") in (None, "", "declare", "speak"):
        speech["speech_act"] = SPEECH_ACT[entry["act"]]
    if not speech.get("topic") and entry.get("topic"):
        speech["topic"] = entry["topic"]
    return entry["act"]
