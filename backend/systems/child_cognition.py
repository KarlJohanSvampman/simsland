"""
systems/child_cognition.py

How a young child decides who to believe, and what they do when they
don't understand something. Deliberately small and derived:

  * source credibility is COMPUTED live from relationship data that
    already exists (kin labels, time together, trust, job title) -- nothing
    is stored per source, so it can't drift out of sync with the
    relationship it came from;
  * naivety is computed from age, minus how many distinct grown-ups have
    already answered one of this child's questions;
  * the only stored state is c["child_cognition"]: open questions, and the
    answers (accounts) they've received.

A child who watches grown-ups argue doesn't understand why, so they form a
question ("why are X and Y fighting?") and want to ask someone they trust.
If the answer came from a source they only half-believe, the question stays
open -- they want a second opinion from someone more credible. Settling
requires one highly credible source or two different ones.

When a second person answers the same question, the two answers are compared
(an LLM agree/conflict judgement run through systems/bg_llm so the result
isn't lost to the per-tick world reload). Agreement settles the question and
raises both sources; a conflict reopens it, lowers whichever source the child
trusts less, and makes the child less naive -- they've now seen grown-ups
disagree. Learned adjustments are the only per-source state stored.

c["child_cognition"] = {
    "open_questions": [{"id","text","scene_key","created_tick",
                        "asked_of":[ids], "accounts":[{"source_id","tick","text"}],
                        "settled": bool, "contested": bool, "pending_compare": bool,
                        "conflict_sources": [ids]}],
    "answered_by":    [source ids, distinct],
    "awaiting":       {"source_id","question_id","tick"} | None,
    "scene_seen":     {scene_key: tick},
    "source_adjust":  {source_id: -0.25..+0.25},   # learned from agreement/conflict
    "conflicts_heard": int,
    "comparisons":    [{"key","q_id","q_text","a_id","a_name","a_text","b_id","b_name","b_text"}],
    "_last_scan":     tick,
}
"""

import uuid

# What a child assumes about someone, by how they're related to the child.
# Reads rel["labels"] AND rel["kinship"]: generation writes kin into labels
# (kinship is None for most live characters), family sync writes kinship.
KIN_CREDIBILITY = {
    "parent":          1.0,
    "guardian":        0.95,
    "adoptive_parent": 0.95,
    "step_parent":     0.85,
    "grandparent":     0.85,
    "aunt_uncle":      0.65,
    "sibling":         0.45,
    "half_sibling":    0.40,
    "cousin":          0.35,
}
# Fallback when there's no kin label: by how grown-up the person is.
STRANGER_CREDIBILITY = {"adult": 0.30, "elderly": 0.30, "teen": 0.25, "child": 0.15}

AUTHORITY_TITLE_BONUS = 0.20     # teacher, doctor, police, ... (domestic_control.AUTHORITY_JOBS)
TIME_BONUS_MAX        = 0.20     # a full ~140h/week together
TIME_BONUS_HOURS      = 140.0
TRUST_BONUS_MAX       = 0.10

SETTLE_CREDIBILITY    = 0.70     # a lone answer from someone this credible settles a question

SOURCE_ADJUST_CAP     = 0.25     # most a learned adjustment can move a source either way
REAFFIRM_GAIN         = 0.06     # two answers agreeing: each source gains this
CONTRADICTED_LOSS     = 0.08     # the less-trusted source of two that conflict loses this
EVEN_CONFLICT_LOSS    = 0.03     # ...or each loses this when the child trusts them equally
NAIVETY_PER_CONFLICT  = 0.04     # every time grown-ups visibly disagree

# Another child as a source. Naive children barely credit one; as naivety falls,
# an impressive peer starts to count.
PEER_TRUST_SCALE      = 0.45
TELLING_ACTS          = ("gossip", "brag")   # how a child passes on what they found out
FELT_TELLING_GAIN     = 0.03     # proud, and nobody challenged them
FELT_DISPUTE_WIN      = 0.04
FELT_DISPUTE_LOSS     = 0.06
FELT_RECONFIRMED_GAIN = 0.10     # lost an argument, checked with their source, were right: surer than ever
PROUD_WINDOW_TICKS    = 10800    # how long a fresh discovery stays burning to be told

# The internet: a source that isn't a person. A naive child barely credits it; as
# they stop taking things at face value they lean on it more, and eventually
# prefer it to asking grown-ups.
INTERNET_ID           = "internet"
INTERNET_BASE         = 0.20
INTERNET_SCALE        = 0.45
INTERNET_MIN_AGE      = 7
LOOKUP_NAIVETY_MAX    = 0.60     # below this a child thinks of looking it up
PREFERS_ONLINE_BELOW  = 0.40     # below this they'd rather look it up than ask
RIDICULE_CHANCE       = 0.25     # asking something sensitive online can go badly
FELT_RIDICULED        = -0.08
INTERNET_RIDICULE_ADJUST = -0.05
_INTERNET = {"id": INTERNET_ID, "name": "the internet", "age_group": "internet"}

# Stems a lookup is matched against (so "argue", "arguing" and "argument" all
# count), and the plain phrase a child would actually type -- by the kind of
# scene that raised the question.
_SCENE_KEYWORDS = {
    "tense":     ["argu", "fight", "disagree", "anger", "angry", "yell", "conflict", "marriage"],
    "emotional": ["sad", "cry", "upset", "feeling", "emotion"],
}
_SCENE_SEARCH = {"tense": "why grown-ups argue", "emotional": "why people feel sad"}
# Worries a child predictably has next, once the surface question is answered:
# (question, match stems, what they'd type).
_FOLLOWUPS = {
    "tense":     [("Is it because of me?", ["blame", "guilt", "parent", "family", "my fault"],
                   "are kids to blame when parents argue"),
                  ("Are they going to split up?", ["divorce", "separat", "split", "parent", "family"],
                   "why parents split up")],
    "emotional": [("Is everything going to be okay?", ["worry", "anxi", "okay", "feeling"],
                   "what to do when you feel worried")],
}

SCAN_INTERVAL_TICKS   = 20
SCENE_COOLDOWN_TICKS  = 7200     # don't re-ask about the same pair within 2h
MAX_OPEN_QUESTIONS    = 3
AWAITING_TIMEOUT      = 900      # ticks to wait for an answer after asking
ACCOUNT_TEXT_CAP      = 160

_KIN_WORDS = {
    "parent": "your parent", "guardian": "your guardian",
    "adoptive_parent": "your parent", "step_parent": "your step-parent",
    "grandparent": "your grandparent", "aunt_uncle": "your aunt or uncle",
    "sibling": "your brother or sister", "half_sibling": "your half-sibling",
    "cousin": "your cousin",
}


def is_child(c):
    return c.get("age_group") == "child"


def _cap(text):
    return text[:1].upper() + text[1:]


def _person(chars, source_id):
    """A character, or the internet pseudo-source."""
    return _INTERNET if source_id == INTERNET_ID else chars.get(source_id)


def _state(c):
    cog = c.setdefault("child_cognition", {})
    cog.setdefault("open_questions", [])
    cog.setdefault("answered_by", [])
    cog.setdefault("awaiting", None)
    cog.setdefault("scene_seen", {})
    cog.setdefault("source_adjust", {})
    cog.setdefault("conflicts_heard", 0)
    cog.setdefault("comparisons", [])
    return cog


def _kin_label(rel, other, child=None):
    """Best kin label this child has for `other`, or None. A child's own
    'child'/'grandchild' labels are the other direction of the relation and
    never make someone more believable, and a child can't be a parent.

    Generation stamps a caregiver as "parent" even when the family graph says
    otherwise (a 63-year-old raising his 6-year-old grandson is labelled
    parent), so c["family_role"] gets the last word where it's unambiguous."""
    names = set(rel.get("labels") or [])
    if rel.get("kinship"):
        names.add(rel["kinship"])
    best, best_score = None, 0.0
    for name in names:
        score = KIN_CREDIBILITY.get(name)
        if score is None:
            continue
        if name in ("parent", "guardian", "adoptive_parent", "step_parent", "grandparent",
                    "aunt_uncle") and other.get("age_group") == "child":
            continue
        if score > best_score:
            best, best_score = name, score
    if (best == "parent" and child is not None
            and other.get("family_role") == "grandparent"
            and child.get("family_role") == "grandchild"):
        best = "grandparent"
    return best


def _has_authority_title(other):
    from systems.domestic_control import AUTHORITY_JOBS
    job = other.get("job") or {}
    candidates = {str(job.get("id") or "").lower(),
                  str(job.get("title") or "").lower().replace(" ", "_"),
                  str(other.get("occupation") or "").lower().replace(" ", "_")}
    return bool(candidates & AUTHORITY_JOBS)


def source_credibility(child, other, world=None):
    """How much `child` believes `other`, 0..1. Closeness of relation sets the
    baseline; an official role, time spent together and trust adjust it."""
    if other.get("id") == INTERNET_ID:
        learned = ((child.get("child_cognition") or {}).get("source_adjust") or {}).get(INTERNET_ID, 0.0)
        return max(0.0, min(0.65, INTERNET_BASE + INTERNET_SCALE * (1.0 - naivety(child, world)) + learned))
    rel = (child.get("relationships") or {}).get(other.get("id")) or {}
    kin = _kin_label(rel, other, child)
    base = KIN_CREDIBILITY[kin] if kin else STRANGER_CREDIBILITY.get(other.get("age_group"), 0.25)

    bonus = 0.0
    if not kin and world is not None and other.get("age_group") in ("child", "teen"):
        # A peer is believed in proportion to how impressive they are and how much
        # the child has stopped taking everything at face value.
        from systems.standing import standing
        bonus += PEER_TRUST_SCALE * (1.0 - naivety(child, world)) * standing(other, child, world)
    if _has_authority_title(other):
        bonus += AUTHORITY_TITLE_BONUS
    bonus += min(TIME_BONUS_MAX, (rel.get("hours_this_week") or 0.0) / TIME_BONUS_HOURS * TIME_BONUS_MAX)
    bonus += max(0.0, min(TRUST_BONUS_MAX, (rel.get("trust") or 0.0) / 100.0 * TRUST_BONUS_MAX))
    learned = ((child.get("child_cognition") or {}).get("source_adjust") or {}).get(other.get("id"), 0.0)
    return max(0.0, min(1.0, base + bonus + learned))


def ranked_sources(child, world, limit=4):
    """Grown-ups this child knows, most believed first: [(char, credibility, kin_label)]."""
    chars = world.get("characters", {})
    out = []
    for oid, rel in (child.get("relationships") or {}).items():
        other = chars.get(oid)
        if not other or other.get("alive") is False or other.get("id") == child.get("id"):
            continue
        if other.get("age_group") not in ("adult", "elderly"):
            continue
        kin = _kin_label(rel, other, child)
        if not kin and (rel.get("familiarity") or 0) < 5:
            continue   # someone they barely know isn't a source yet
        out.append((other, source_credibility(child, other, world), kin))
    out.sort(key=lambda t: t[1], reverse=True)
    return out[:limit]


def naivety(child, world=None):
    """0..1: how readily they take what grown-ups say as simply true. Falls
    with age and with each different person who has answered a question."""
    age = child.get("age")
    base = 0.9 if age is None else max(0.3, min(0.95, 1.0 - 0.06 * (age - 3)))
    cog = child.get("child_cognition") or {}
    answered = len(cog.get("answered_by") or [])
    return max(0.15, base - 0.03 * answered - NAIVETY_PER_CONFLICT * (cog.get("conflicts_heard") or 0))


# ---------------------------------------------------------------------------
# Questions from what they overhear
# ---------------------------------------------------------------------------

def _question_text(names, tone):
    who = " and ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " and " + names[-1]
    if tone == "tense":
        return f"Why are {who} fighting?"
    return f"Why is {who} so upset?"


def update_child_cognition(c, world):
    """Per-tick hook (brain/agent_loop.py). Cheap no-op for everyone but
    children, and rate-limited. Turns an adult conflict or upset the child
    can see -- a scene they're not part of -- into a question they want
    answered."""
    if not is_child(c):
        return
    tick = world.get("tick", 0)
    cog = _state(c)
    _service_comparisons(c, world)
    from systems.standing import refresh_role_model
    refresh_role_model(c, cog, world)
    if tick - cog.get("_last_scan", -SCAN_INTERVAL_TICKS) < SCAN_INTERVAL_TICKS:
        return
    cog["_last_scan"] = tick

    if len([q for q in cog["open_questions"] if not q["settled"]]) >= MAX_OPEN_QUESTIONS:
        return

    by_name = {ch.get("name"): ch for ch in world.get("characters", {}).values()}
    for scene in (c.get("perception") or {}).get("social_scenes") or []:
        tone = scene.get("tone")
        if tone not in ("tense", "emotional"):
            continue
        names = [n for n in (scene.get("participants") or []) if n]
        if c.get("name") in names or len(names) < 2:
            continue   # their own conversation, or not really a scene
        people = [by_name.get(n) for n in names]
        if not any(p and p.get("age_group") in ("adult", "elderly", "teen") for p in people):
            continue   # kids squabbling isn't a mystery they'd need explained
        key = "|".join(sorted(names))
        if tick - cog["scene_seen"].get(key, -SCENE_COOLDOWN_TICKS) < SCENE_COOLDOWN_TICKS:
            continue
        cog["scene_seen"][key] = tick
        cog["open_questions"].append({
            "id":           f"q_{uuid.uuid4().hex[:8]}",
            "text":         _question_text(names, tone),
            "scene_key":    key,
            "created_tick": tick,
            "asked_of":     [],
            "accounts":     [],
            "settled":      False,
            "contested":    False,
            "pending_compare": False,
            "tone":         tone,
            "keywords":     list(_SCENE_KEYWORDS.get(tone, [])),
            "search":       _SCENE_SEARCH.get(tone),
        })
        break   # one new question per scan is plenty

    # Don't let settled questions pile up.
    cog["open_questions"] = ([q for q in cog["open_questions"] if not q["settled"]]
                             + [q for q in cog["open_questions"] if q["settled"]][-3:])


# ---------------------------------------------------------------------------
# Asking, and being answered
# ---------------------------------------------------------------------------

def _open_questions(cog):
    return [q for q in cog.get("open_questions", []) if not q["settled"]]


def on_conversation_message(world, conv, speaker_id, utterance, speech_act, tick):
    """Called from brain/conversations.py::add_message for every new line.

    A child's `question` to someone, while they have an unsettled one, is
    them asking it. The next thing that person says back is the answer."""
    chars = world.get("characters", {})
    speaker = chars.get(speaker_id)
    if not speaker:
        return
    others = [chars.get(pid) for pid in conv.get("participants", []) if pid != speaker_id]
    others = [o for o in others if o]

    # A child asking.
    if is_child(speaker) and speech_act == "question":
        cog = _state(speaker)
        pending = sorted(_open_questions(cog), key=lambda x: not x.get("contested"))
        listener = next((o for o in others if o.get("age_group") != "child"), None)
        if pending and listener:
            q = pending[0]
            if listener["id"] not in q["asked_of"]:
                q["asked_of"].append(listener["id"])
            cog["awaiting"] = {"source_id": listener["id"], "question_id": q["id"], "tick": tick}
        return

    # A child proudly passing on what they found out.
    if is_child(speaker) and speech_act in TELLING_ACTS:
        _tell_peers(speaker, [o for o in others if is_child(o)], tick, world)
        return

    # Someone answering a child.
    for child in (o for o in others if is_child(o)):
        cog = _state(child)
        waiting = cog.get("awaiting")
        if not waiting or waiting["source_id"] != speaker_id:
            continue
        if tick - waiting["tick"] > AWAITING_TIMEOUT:
            cog["awaiting"] = None
            continue
        q = next((x for x in cog["open_questions"] if x["id"] == waiting["question_id"]), None)
        cog["awaiting"] = None
        if not q or q["settled"]:
            continue
        account = {"source_id": speaker_id, "tick": tick, "text": (utterance or "")[:ACCOUNT_TEXT_CAP]}
        if speech_act in ("dismissive", "awkward_silence"):
            account["brushed_off"] = True
            q["accounts"].append(account)
            continue   # brushed off -- nothing learned, still wondering
        prior = next((a for a in reversed(q["accounts"])
                      if a["source_id"] != speaker_id and not a.get("brushed_off")), None)
        q["accounts"].append(account)
        if speaker_id not in cog["answered_by"]:
            cog["answered_by"].append(speaker_id)
        if prior:
            # A second person has now answered: don't guess whether the two
            # agree -- queue the comparison and decide when it comes back.
            _queue_comparison(cog, q, prior, account, chars)
        elif source_credibility(child, speaker, world) >= SETTLE_CREDIBILITY:
            _settle(child, q)


# ---------------------------------------------------------------------------
# The internet
# ---------------------------------------------------------------------------

def _lookup_matches(q, keyword):
    kw = (keyword or "").lower()
    if not kw:
        return False
    if any(k in kw for k in q.get("keywords") or []):
        return True
    return any(w in kw for w in q["text"].lower().replace("?", "").split() if len(w) >= 5)


def on_internet_lookup(c, world, keyword, extract):
    """Called by the computer_wiki_research route. If a child looks something up
    that bears on a question they're carrying, what they read becomes an account
    like any other, to be compared with what the grown-ups said. Sensitive
    questions can get them laughed at."""
    if not is_child(c) or not extract:
        return
    cog = _state(c)
    q = next((x for x in sorted(_open_questions(cog), key=lambda x: not x.get("contested"))
              if _lookup_matches(x, keyword)), None)
    if q is None:
        return
    import random
    from systems.standing import bump_felt
    tick = world.get("tick", 0)

    if q.get("followup") and not q.get("ridiculed") and random.random() < RIDICULE_CHANCE:
        q["ridiculed"] = True
        bump_felt(c, FELT_RIDICULED)
        _adjust(cog, INTERNET_ID, INTERNET_RIDICULE_ADJUST)
        from brain.memory import store_memory
        store_memory(c, f"I asked online about \"{q['text']}\" and people laughed at me.", 0.6,
                     ["internet", "ridiculed"], "memory", tick, emotional_impact=-0.5)
        return

    chars = world.get("characters", {})
    prior = next((a for a in reversed(q["accounts"])
                  if a["source_id"] != INTERNET_ID and not a.get("brushed_off")), None)
    account = {"source_id": INTERNET_ID, "tick": tick, "text": extract[:ACCOUNT_TEXT_CAP], "internet": True}
    q["accounts"].append(account)
    if INTERNET_ID not in cog["answered_by"]:
        cog["answered_by"].append(INTERNET_ID)
    if prior:
        _queue_comparison(cog, q, prior, account, chars)
    elif source_credibility(c, _INTERNET, world) >= SETTLE_CREDIBILITY:
        _settle(c, q)


# ---------------------------------------------------------------------------
# Telling other children
# ---------------------------------------------------------------------------

def _tell_peers(speaker, listeners, tick, world):
    """A child who learned something wants to share it, whether or not they
    understood it. The teller feels good -- nobody has challenged them yet. The
    listener now has an account from a child; if they'd already been told
    something by a grown-up, it gets compared like any other pair of accounts."""
    from systems.standing import bump_felt
    chars = world.get("characters", {})
    cog = _state(speaker)
    fact = next((q for q in reversed(cog["open_questions"])
                 if not q.get("told") and any(not a.get("brushed_off") for a in q["accounts"])), None)
    if not fact or not listeners:
        return
    told = next(a for a in reversed(fact["accounts"]) if not a.get("brushed_off"))
    fact["told"] = True
    bump_felt(speaker, FELT_TELLING_GAIN)

    for listener in listeners:
        lcog = _state(listener)
        lq = next((x for x in lcog["open_questions"] if x["scene_key"] == fact["scene_key"]), None)
        if lq is None:
            lq = {"id": f"q_{uuid.uuid4().hex[:8]}", "text": fact["text"], "scene_key": fact["scene_key"],
                  "created_tick": tick, "asked_of": [], "accounts": [], "settled": False,
                  "contested": False, "pending_compare": False, "from_peer": True,
                  "tone": fact.get("tone"), "keywords": list(fact.get("keywords") or []),
                  "search": fact.get("search")}
            lcog["open_questions"].append(lq)
            lcog["scene_seen"][fact["scene_key"]] = tick     # don't also scan-create a duplicate
        prior = next((a for a in reversed(lq["accounts"])
                      if a["source_id"] != speaker["id"] and not a.get("brushed_off")), None)
        account = {"source_id": speaker["id"], "tick": tick, "text": told["text"], "peer": True}
        lq["accounts"].append(account)
        if speaker["id"] not in lcog["answered_by"]:
            lcog["answered_by"].append(speaker["id"])
        if prior:
            _queue_comparison(lcog, lq, prior, account, chars, peer_teller_id=speaker["id"])
        elif source_credibility(listener, speaker, world) >= SETTLE_CREDIBILITY:
            _settle(listener, lq)


# ---------------------------------------------------------------------------
# Comparing what two grown-ups said
# ---------------------------------------------------------------------------

def _queue_comparison(cog, q, first, second, chars, peer_teller_id=None):
    if peer_teller_id is None:
        # A child heard it from another child, and now a grown-up (or the reverse)
        # has said something -- whichever account came from a peer is the one that
        # may turn out to be a lie.
        peer_teller_id = (first["source_id"] if first.get("peer")
                          else second["source_id"] if second.get("peer") else None)
    q["pending_compare"] = True
    n = len(q["accounts"])
    cog["comparisons"].append({
        "peer_teller_id": peer_teller_id,
        "key":    f"cmp:{q['id']}:{n}",
        "q_id":   q["id"],
        "q_text": q["text"],
        "a_id":   first["source_id"],  "a_name": (_person(chars, first["source_id"]) or {}).get("name", "someone"),
        "a_text": first["text"],
        "b_id":   second["source_id"], "b_name": (_person(chars, second["source_id"]) or {}).get("name", "someone"),
        "b_text": second["text"],
    })


def _settle(child, q):
    """Mark a question settled. If they'd been told they were wrong and checked
    with a source they believe, being right again leaves them surer than before."""
    from systems.standing import bump_felt
    q["settled"], q["contested"] = True, False
    _raise_followup(child, q)
    if q.get("reconfirm"):
        q["reconfirm"] = False
        q["accused_by"] = None
        bump_felt(child, FELT_RECONFIRMED_GAIN)


def _raise_followup(child, q):
    """Once the surface question is answered, a child predictably worries about
    the next thing (is it my fault? will they split up?). Once per scene."""
    if q.get("followup") or q.get("followup_raised") or not q.get("tone"):
        return
    options = _FOLLOWUPS.get(q["tone"])
    if not options:
        return
    cog = _state(child)
    if any(x.get("followup_of") == q["id"] for x in cog["open_questions"]):
        return
    text, keywords, search = options[sum(map(ord, q["id"])) % len(options)]
    q["followup_raised"] = True
    cog["open_questions"].append({
        "id": f"q_{uuid.uuid4().hex[:8]}", "text": text, "scene_key": q["scene_key"] + "#followup",
        "created_tick": (q["accounts"][-1]["tick"] if q["accounts"] else q["created_tick"]),
        "asked_of": [], "accounts": [], "settled": False, "contested": False, "pending_compare": False,
        "followup": True, "followup_of": q["id"], "tone": None, "keywords": list(keywords),
        "search": search,
    })


def _adjust(cog, source_id, delta):
    cur = cog["source_adjust"].get(source_id, 0.0)
    cog["source_adjust"][source_id] = max(-SOURCE_ADJUST_CAP, min(SOURCE_ADJUST_CAP, cur + delta))


def _apply_verdict(child, cog, q, cmp_entry, agree, world):
    chars = world.get("characters", {})
    q["pending_compare"] = False
    a, b = _person(chars, cmp_entry["a_id"]), _person(chars, cmp_entry["b_id"])
    if agree is True:
        _adjust(cog, cmp_entry["a_id"], REAFFIRM_GAIN)
        _adjust(cog, cmp_entry["b_id"], REAFFIRM_GAIN)
        _settle(child, q)
    elif agree is False:
        cog["conflicts_heard"] += 1
        q["settled"], q["contested"] = False, True
        q["conflict_sources"] = [cmp_entry["a_id"], cmp_entry["b_id"]]
        if a and b:
            ca, cb = source_credibility(child, a, world), source_credibility(child, b, world)
            if abs(ca - cb) < 0.05:
                _adjust(cog, a["id"], -EVEN_CONFLICT_LOSS)
                _adjust(cog, b["id"], -EVEN_CONFLICT_LOSS)
            else:
                _adjust(cog, (a if ca < cb else b)["id"], -CONTRADICTED_LOSS)
            teller_id = cmp_entry.get("peer_teller_id")
            if teller_id:
                _peer_dispute(child, q, teller_id, ca if a and a["id"] == teller_id else cb,
                              cb if a and a["id"] == teller_id else ca, cmp_entry, world)
    else:
        # Couldn't tell: no new information, so fall back to trusting the latest
        # answer only if it came from someone credible.
        later = _person(chars, cmp_entry["b_id"])
        if later and source_credibility(child, later, world) >= SETTLE_CREDIBILITY:
            _settle(child, q)


def _peer_dispute(child, q, teller_id, teller_cred, other_cred, entry, world):
    """A child was told something by another child that contradicts what a grown-up
    told them. If they trust the grown-up more, the other child is wrong -- and
    they say so. Both feel it."""
    chars = world.get("characters", {})
    teller = chars.get(teller_id)
    if not teller or teller_cred >= other_cred:
        return    # they lean toward the peer: ordinary contested question, no accusation
    from systems.standing import bump_felt
    from systems.grievances import add_grievance
    q["dispute_with"] = teller_id
    q["dispute_text"] = entry["a_text"] if entry["a_id"] == teller_id else entry["b_text"]
    add_grievance(child, teller_id, "lied", world,
                  details={"context": "told_something_that_contradicts_a_grown_up"})
    bump_felt(child, FELT_DISPUTE_WIN)
    # The teller is the one who's been called a liar.
    bump_felt(teller, -FELT_DISPUTE_LOSS)
    tcog = _state(teller)
    tq = next((x for x in tcog["open_questions"] if x["scene_key"] == q["scene_key"]), None)
    if tq is not None:
        tq["settled"] = False
        tq["reconfirm"] = True
        tq["accused_by"] = child["id"]


def _service_comparisons(c, world):
    """Submit queued comparisons to the background worker and apply any that
    have come back. Runs every tick for children; cheap when nothing's queued."""
    cog = c.get("child_cognition")
    if not cog or not cog.get("comparisons"):
        return
    from systems import bg_llm
    from llm.account_agreement import accounts_agree
    remaining = []
    for entry in cog["comparisons"]:
        bg_llm.submit(entry["key"], accounts_agree, entry["q_text"], entry["a_name"], entry["a_text"],
                      entry["b_name"], entry["b_text"])
        ready, verdict = bg_llm.take(entry["key"])
        if not ready:
            remaining.append(entry)
            continue
        q = next((x for x in cog["open_questions"] if x["id"] == entry["q_id"]), None)
        if q is not None:
            _apply_verdict(c, cog, q, entry, verdict, world)
    cog["comparisons"] = remaining


# ---------------------------------------------------------------------------
# Prompt context
# ---------------------------------------------------------------------------

def _has_computer(c, world):
    from systems.personal_items import get_computer
    return get_computer(c, world) is not None


def get_child_cognition_context(c, world):
    """Prose for a child's think() prompt, or None for anyone else."""
    if not is_child(c):
        return None
    chars = world.get("characters", {})
    parts = []

    sources = ranked_sources(c, world)
    if sources:
        described = []
        for other, _cred, kin in sources:
            name = other.get("name", "someone")
            if kin:
                described.append(f"{name} ({_KIN_WORDS[kin]})")
            elif _has_authority_title(other):
                described.append(f"{name} (a {(other.get('job') or {}).get('title') or 'grown-up'})")
            else:
                described.append(name)
        parts.append("The grown-ups you believe most, from most to least: " + ", ".join(described) + ".")

    n = naivety(c, world)
    if n >= 0.7:
        parts.append("You mostly believe what grown-ups tell you, especially the ones you trust most.")
    elif n >= 0.4:
        parts.append("You've heard grown-ups say different things before, so you don't swallow everything "
                     "straight away -- you like to check with someone you trust.")
    else:
        parts.append("You've learned that grown-ups don't always agree or tell the whole truth, so you "
                     "check things and argue back when something doesn't match what you heard.")

    cog = c.get("child_cognition") or {}
    open_qs = _open_questions(cog)
    if open_qs:
        # Fights over who's right matter most, then answers that conflict.
        q = next((x for x in open_qs if x.get("dispute_with") or x.get("accused_by")),
                 next((x for x in open_qs if x.get("contested")), open_qs[0]))
        line = f"You keep wondering: \"{q['text']}\""
        top = sources[0][0].get("name") if sources else None
        if q.get("accused_by"):
            acc = chars.get(q["accused_by"], {}).get("name", "another kid")
            line = (f"{acc} says what you found out about \"{q['text']}\" is wrong -- called you a liar, even. "
                    f"You don't want that to be true and it stings. You want to ask "
                    f"{top or 'a grown-up'} to be sure you're right, and if you can't stand it you might tell a grown-up "
                    f"that {acc} lies.")
        elif q.get("dispute_with"):
            tell = chars.get(q["dispute_with"], {}).get("name", "another kid")
            adult_id = next((i for i in (q.get("conflict_sources") or []) if i != q["dispute_with"]), None)
            adult = chars.get(adult_id, {}).get("name", "a grown-up")
            line += (f" {tell} told you \"{q.get('dispute_text', '')}\" -- but that's not what {adult} told you. "
                     f"You think {tell} is making it up, and you're ready to say so to their face.")
        elif q.get("contested") and len(q.get("conflict_sources") or []) == 2:
            a, b = (_person(chars, i) or {} for i in q["conflict_sources"])
            favoured = a if source_credibility(c, a, world) >= source_credibility(c, b, world) else b
            other = b if favoured is a else a
            line += (f" {_cap(a.get('name', 'Someone'))} told you one thing and {b.get('name', 'someone')} told you "
                     f"something different, and now you don't know who to believe. You trust "
                     f"{favoured.get('name', 'one of them')} more, but you want to ask again to be sure -- and if "
                     f"someone says something that doesn't match what {other.get('name', 'the other')} told you, "
                     f"you say so: \"but {other.get('name', 'they')} said...\"")
        elif q["accounts"]:
            told = (_person(chars, q["accounts"][-1]["source_id"]) or {}).get("name", "someone")
            line += (f" {_cap(told)} told you something, but you're not sure that's the whole story"
                     + (f" -- you want to ask {top} too." if top and top != told else "."))
        elif top:
            line += f" You'd like to ask {top} about it."
        if q.get("ridiculed"):
            line += (" You asked about it online and people laughed at you -- you feel embarrassed and don't "
                     "want to ask anyone else about it.")
        elif (not q["settled"] and (c.get("age") or 0) >= INTERNET_MIN_AGE and naivety(c, world) < LOOKUP_NAIVETY_MAX
              and q.get("keywords") and not any(a.get("internet") for a in q["accounts"]) and _has_computer(c, world)):
            line += (f" You could look it up on the computer instead of asking a grown-up (search for something like "
                     f"\"{q.get('search') or q['keywords'][0]}\").")
            if naivety(c, world) < PREFERS_ONLINE_BELOW:
                line += " Honestly you'd rather look it up -- grown-ups just say it's nothing."
        parts.append(line)

    proud = next((x for x in reversed(cog.get("open_questions", []))
                  if x["settled"] and not x.get("told") and x["accounts"]
                  and world.get("tick", 0) - x["accounts"][-1]["tick"] <= PROUD_WINDOW_TICKS), None)
    if proud:
        parts.append(f"You found out the answer to \"{proud['text']}\" and you're proud you know something the "
                     f"other kids might not -- you feel like telling them, even if you only half understood it.")

    from systems.standing import get_standing_context
    parts.extend(get_standing_context(c, world))

    return " ".join(parts) if parts else None
