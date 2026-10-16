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
    rel = (child.get("relationships") or {}).get(other.get("id")) or {}
    kin = _kin_label(rel, other, child)
    base = KIN_CREDIBILITY[kin] if kin else STRANGER_CREDIBILITY.get(other.get("age_group"), 0.25)

    bonus = 0.0
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
            q["settled"] = True


# ---------------------------------------------------------------------------
# Comparing what two grown-ups said
# ---------------------------------------------------------------------------

def _queue_comparison(cog, q, first, second, chars):
    q["pending_compare"] = True
    n = len(q["accounts"])
    cog["comparisons"].append({
        "key":    f"cmp:{q['id']}:{n}",
        "q_id":   q["id"],
        "q_text": q["text"],
        "a_id":   first["source_id"],  "a_name": chars.get(first["source_id"], {}).get("name", "someone"),
        "a_text": first["text"],
        "b_id":   second["source_id"], "b_name": chars.get(second["source_id"], {}).get("name", "someone"),
        "b_text": second["text"],
    })


def _adjust(cog, source_id, delta):
    cur = cog["source_adjust"].get(source_id, 0.0)
    cog["source_adjust"][source_id] = max(-SOURCE_ADJUST_CAP, min(SOURCE_ADJUST_CAP, cur + delta))


def _apply_verdict(child, cog, q, cmp_entry, agree, world):
    chars = world.get("characters", {})
    q["pending_compare"] = False
    a, b = chars.get(cmp_entry["a_id"]), chars.get(cmp_entry["b_id"])
    if agree is True:
        _adjust(cog, cmp_entry["a_id"], REAFFIRM_GAIN)
        _adjust(cog, cmp_entry["b_id"], REAFFIRM_GAIN)
        q["settled"], q["contested"] = True, False
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
    else:
        # Couldn't tell: no new information, so fall back to trusting the latest
        # answer only if it came from someone credible.
        later = chars.get(cmp_entry["b_id"])
        if later and source_credibility(child, later, world) >= SETTLE_CREDIBILITY:
            q["settled"] = True


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
        # A question that's been answered two different ways matters most.
        q = next((x for x in open_qs if x.get("contested")), open_qs[0])
        line = f"You keep wondering: \"{q['text']}\""
        top = sources[0][0].get("name") if sources else None
        if q.get("contested") and len(q.get("conflict_sources") or []) == 2:
            a, b = (chars.get(i) or {} for i in q["conflict_sources"])
            favoured = a if source_credibility(c, a, world) >= source_credibility(c, b, world) else b
            other = b if favoured is a else a
            line += (f" {a.get('name', 'Someone')} told you one thing and {b.get('name', 'someone')} told you "
                     f"something different, and now you don't know who to believe. You trust "
                     f"{favoured.get('name', 'one of them')} more, but you want to ask again to be sure -- and if "
                     f"someone says something that doesn't match what {other.get('name', 'the other')} told you, "
                     f"you say so: \"but {other.get('name', 'they')} said...\"")
        elif q["accounts"]:
            told = chars.get(q["accounts"][-1]["source_id"], {}).get("name", "someone")
            line += (f" {told} told you something, but you're not sure that's the whole story"
                     + (f" -- you want to ask {top} too." if top and top != told else "."))
        elif top:
            line += f" You'd like to ask {top} about it."
        parts.append(line)

    return " ".join(parts) if parts else None
