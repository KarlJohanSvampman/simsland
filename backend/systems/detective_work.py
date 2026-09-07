"""
systems/detective_work.py

A generic "figure out what's actually going on" engine: a problem or
anomaly (unsettling mail, a witnessed domestic disturbance, a suspected
affair, a missing item, a worrying behavior change...) becomes a
detective_story, divided into chapters (a problem statement + a main
question each), progressed by an LLM-generated plan+outcome per chapter,
and spread to other characters who get told about it -- each of whom
runs their OWN independent copy (mirrors systems/stories.py's chain-
spread design exactly: everyone who adopts it gets their own entry, not
a shared pointer, and may tell/not-tell/drop it independently).

Per the user's own framing: a new chapter opens whenever the previous
one either (a) successfully answered its main question, or (b) surfaced
new questions/clues/suspects -- i.e. any real forward progress. A
chapter that produces no progress at all just stalls; enough stalls (or
running out the story's own expiration) ends it as a cold case rather
than a triumphant resolution.

Involvement is tracked at three tiers per the user's own distinction:
  - involved_ids   -- confirmed, by the story's own chapters' findings
  - suspect_ids     -- suspected but not confirmed (can later be cleared)
  - cleared_ids     -- was a suspect, ruled out

A character's ROLE (involved/witness/detective/temp_detective) and GOAL
(resolve/protect/gossip) are personal and independent of the "objective"
facts above -- two people working the same mystery can want different
things from it, exactly as the user described.

Children route straight to an adult rather than telling other children
first (see start_detective_story's age_group check) -- a deliberate,
explicit design choice, not a general rule for who gets told what.
"""

import copy as _copy
import random
import uuid

from brain.memory import store_memory

# ── Tag taxonomy ──────────────────────────────────────────────────────────
# Every tag the user named, defined so it's ready to be triggered from
# anywhere -- only a representative subset (see the "hooked" note on each)
# actually has a real detector wired up this round; the rest are real,
# usable tags a future round can start calling start_detective_story()
# with directly, no schema changes needed.

PROBLEM_TAGS = {
    "threats_violence":       {"label": "Threats & Violence", "importance": 0.8},
    "property_damage":        {"label": "Property Damage / Vandalism", "importance": 0.5},
    "stalker_sociopath":      {"label": "Stalker / Sociopath", "importance": 0.85},
    "job_loss":                {"label": "Lost Their Job", "importance": 0.6},
    "aggressive_neighbor":    {"label": "Aggressive Neighbor", "importance": 0.5},
    "aggressive_partner":     {"label": "Aggressive Partner / Ex", "importance": 0.75},
    "medical_diagnosis":      {"label": "Medical Diagnosis", "importance": 0.6},
    "substance_abuse":        {"label": "Substance / Alcohol Abuse", "importance": 0.7},
    "bullying":                {"label": "Bullying", "importance": 0.6},
    "teen_pregnancy":         {"label": "Teen Pregnancy", "importance": 0.75},
    "behavior_change":        {"label": "Worrying Behavior Change", "importance": 0.55},
    "missing_item":           {"label": "Something's Missing", "importance": 0.3},
    "mysterious_appearance":  {"label": "Something Appeared / Misdelivered", "importance": 0.3},
    "suspected_affair":       {"label": "Suspected Affair", "importance": 0.65},
    "economic_concern":       {"label": "Economic Concern", "importance": 0.5},
    "gambling":                {"label": "Gambling", "importance": 0.6},
    "porn_addiction":         {"label": "Obsessive / Compulsive Behavior", "importance": 0.5},
    "domestic_abuse":         {"label": "Domestic Abuse / Disturbance", "importance": 0.85},
    "unsettling_contact":     {"label": "Unsettling Mail or Messages", "importance": 0.6},
}

# ── Timing ──────────────────────────────────────────────────────────────

TICKS_PER_HOUR = 3600
TICKS_PER_DAY = TICKS_PER_HOUR * 24

MIN_STORY_DAYS = 3
MAX_STORY_DAYS = 14
CHAPTER_BASE_HOURS = 4
MAX_STALLS_BEFORE_COLD_CASE = 2

CRITICAL_THINKING_GAIN = 0.03
TEAM_PRIDE_GAIN = 0.05


def _story_duration_ticks(importance):
    days = MIN_STORY_DAYS + (MAX_STORY_DAYS - MIN_STORY_DAYS) * max(0.0, min(1.0, importance))
    return int(days * TICKS_PER_DAY)


def _chapter_resolve_delay_ticks(story):
    complexity = 1.0 + len(story.get("clues", [])) * 0.15 + len(story.get("suspect_ids", [])) * 0.2
    importance = max(0.2, story.get("importance", 0.5))
    return int((CHAPTER_BASE_HOURS * TICKS_PER_HOUR) * complexity / importance)


# ── Starting a story ───────────────────────────────────────────────────────

def start_detective_story(c, world, tags, problem_statement, main_question=None,
                           involved_ids=None, suspect_ids=None, importance=None,
                           role="involved", goal="resolve", context=None):
    """Creates a new detective_story on c. If c is a child, immediately
    routes it to a real adult in their household per the kid-bypass rule
    (the child still keeps their own copy too -- they noticed it)."""
    if importance is None:
        importance = max((PROBLEM_TAGS.get(t, {}).get("importance", 0.5) for t in tags), default=0.5)

    now = world.get("tick", 0)
    story_id = f"story_{uuid.uuid4().hex[:8]}"
    story = {
        "id": story_id,
        "origin_id": story_id,
        "tags": list(tags),
        "problem_statement": problem_statement,
        "role": role,
        "goal": goal,
        "importance": round(importance, 2),
        "involved_ids": list(involved_ids or []),
        "suspect_ids": list(suspect_ids or []),
        "cleared_ids": [],
        "clues": [],
        "started_tick": now,
        "expires_tick": now + _story_duration_ticks(importance),
        "chapters": [],
        "current_chapter": 0,
        "told_to": [],
        "resolved": False,
        "final_outcome": None,
        "resolution": None,
        "stall_count": 0,
        "context": context or {},
        "team_credit_given": False,
    }
    story["chapters"].append({
        "id": f"ch_{uuid.uuid4().hex[:6]}",
        "index": 0,
        "problem_statement": problem_statement,
        "main_question": main_question or "What's actually going on here?",
        "status": "open",
        "plan": None,
        "outcome_type": None,
        "answer_summary": None,
        "opened_tick": now,
        "resolve_at_tick": now + _chapter_resolve_delay_ticks(story),
        "closed_tick": None,
    })

    c.setdefault("detective_stories", {})[story_id] = story

    if c.get("age_group") == "child":
        adult = _find_household_adult(c, world)
        if adult:
            share_detective_story(c, adult, story_id, world, forced=True)

    return story


def _find_household_adult(c, world):
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return None
    chars = world.get("characters", {})
    for member_id in household.get("members", []):
        if member_id == c.get("id"):
            continue
        member = chars.get(member_id)
        if member and member.get("alive", True) and member.get("age_group") not in ("child", "teen"):
            return member
    return None


# ── Sharing / chain-spread (mirrors systems/stories.py::tell_story) ───────

def _candidate_roster(c, world, cap=8):
    chars = world.get("characters", {})
    candidates = []
    household = world.get("households", {}).get(c.get("household_id"))
    if household:
        for mid in household.get("members", []):
            if mid == c.get("id"):
                continue
            m = chars.get(mid)
            if m:
                candidates.append({"id": mid, "name": m.get("name", mid)})

    rels = sorted(
        c.get("relationships", {}).items(),
        key=lambda kv: (kv[1].get("trust", 0) + kv[1].get("friendship", 0)),
        reverse=True,
    )
    for oid, rel in rels:
        if len(candidates) >= cap:
            break
        if any(cand["id"] == oid for cand in candidates):
            continue
        other = chars.get(oid)
        if other:
            candidates.append({"id": oid, "name": other.get("name", oid)})

    return candidates[:cap]


_GOAL_TRAITS = {
    "protect": {"protective", "compassionate", "selfless"},
    "gossip":  {"gossipy", "chatty", "extroverted"},
    "resolve": {"curious", "analytical", "perceptive", "logical"},
}


def _infer_goal(c):
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    for goal, wanted in _GOAL_TRAITS.items():
        if traits & wanted:
            return goal
    return "resolve"


def _adoption_chance(listener, story):
    base = 0.15 + story.get("importance", 0.5) * 0.3
    traits = set(listener.get("traits", []) + listener.get("personality_traits", []))
    if traits & {"curious", "gossipy", "nosy"}:
        base += 0.2
    if traits & {"apathetic", "incurious"}:
        base -= 0.2
    return max(0.05, min(0.9, base))


def share_detective_story(c, listener, story_id, world, forced=False):
    """c tells listener about their own copy of story_id. Routes through
    the real conversation pipeline (like stories.py::tell_story) unless
    forced (the kid-bypass path, which doesn't wait for a real
    conversational moment). listener independently decides whether to
    become a temp_detective and keep their own copy -- forced shares
    always land (an adult doesn't get to "not notice" their kid telling
    them something's wrong)."""
    story = c.get("detective_stories", {}).get(story_id)
    if not story:
        return None

    story.setdefault("told_to", [])
    if listener["id"] not in story["told_to"]:
        story["told_to"].append(listener["id"])

    if not forced:
        try:
            from systems.action_router import apply_speech
            apply_speech(c, world, {
                "target": listener["id"], "speech_act": "inform",
                "topic": "detective_story", "utterance": story["problem_statement"],
            })
        except Exception:
            pass

    for s in listener.get("detective_stories", {}).values():
        if s.get("origin_id") == story.get("origin_id"):
            return s  # already has their own copy of this same mystery

    if not forced and random.random() >= _adoption_chance(listener, story):
        return None

    listener_copy = _copy.deepcopy(story)
    listener_copy["id"] = f"story_{uuid.uuid4().hex[:8]}"
    listener_copy["role"] = "temp_detective" if not forced else "involved"
    listener_copy["goal"] = _infer_goal(listener)
    listener_copy["told_to"] = []
    listener_copy["team_credit_given"] = False
    listener.setdefault("detective_stories", {})[listener_copy["id"]] = listener_copy
    return listener_copy


# ── Chapter progression ────────────────────────────────────────────────────

def advance_chapter(c, story, world):
    now = world.get("tick", 0)

    if now >= story.get("expires_tick", now + 1):
        _close_story(c, story, world, "expired")
        return

    chapter = story["chapters"][story["current_chapter"]]
    if chapter["status"] != "open" or now < chapter.get("resolve_at_tick", now):
        return

    from llm.detective_plan import generate_chapter_plan
    candidates = _candidate_roster(c, world)
    result = generate_chapter_plan(c, world, story, chapter, candidates)

    chapter["plan"] = result.get("plan_summary")
    if result.get("new_clue"):
        story.setdefault("clues", []).append(result["new_clue"])
    _apply_suspect_updates(story, candidates, result)

    outcome = result.get("outcome", "no_progress")
    chapter["outcome_type"] = outcome
    chapter["closed_tick"] = now

    if outcome == "no_progress":
        story["stall_count"] = story.get("stall_count", 0) + 1
        if story["stall_count"] >= MAX_STALLS_BEFORE_COLD_CASE:
            chapter["status"] = "stalled"
            _close_story(c, story, world, "cold_case")
        else:
            # Re-open the SAME chapter for another attempt later rather
            # than leaving status="stalled" -- that would permanently
            # block advance_chapter's own "still open" guard from ever
            # revisiting it, so a single no_progress roll would silently
            # freeze the story forever instead of actually giving up
            # after MAX_STALLS_BEFORE_COLD_CASE tries.
            chapter["status"] = "open"
            chapter["resolve_at_tick"] = now + _chapter_resolve_delay_ticks(story)
        return

    chapter["status"] = "answered" if outcome == "answered" else "led_to_more_questions"
    chapter["answer_summary"] = result.get("answer_summary")
    _reward_detective(c, story)

    next_question = result.get("next_question")
    resolution_action = result.get("resolution_action")

    if outcome == "answered" and resolution_action and not next_question:
        story["resolution"] = resolution_action
        _close_story(c, story, world, "resolved")
        return

    if not next_question:
        _close_story(c, story, world, "resolved" if outcome == "answered" else "cold_case")
        return

    _open_next_chapter(story, world, next_question, resolution_action)


def _apply_suspect_updates(story, candidates, result):
    by_index = {i: cand["id"] for i, cand in enumerate(candidates)}
    for i in result.get("new_suspect_indices", []) or []:
        sid = by_index.get(i)
        if sid and sid not in story["suspect_ids"] and sid not in story["involved_ids"]:
            story["suspect_ids"].append(sid)
    for i in result.get("cleared_suspect_indices", []) or []:
        sid = by_index.get(i)
        if sid and sid in story["suspect_ids"]:
            story["suspect_ids"].remove(sid)
            if sid not in story["cleared_ids"]:
                story["cleared_ids"].append(sid)


def _open_next_chapter(story, world, main_question, hint=None):
    now = world.get("tick", 0)
    chapter = {
        "id": f"ch_{uuid.uuid4().hex[:6]}",
        "index": len(story["chapters"]),
        "problem_statement": hint or story["problem_statement"],
        "main_question": main_question,
        "status": "open",
        "plan": None,
        "outcome_type": None,
        "answer_summary": None,
        "opened_tick": now,
        "resolve_at_tick": now + _chapter_resolve_delay_ticks(story),
        "closed_tick": None,
    }
    story["chapters"].append(chapter)
    story["current_chapter"] = chapter["index"]


def _reward_detective(c, story, scale=1.0):
    gain = CRITICAL_THINKING_GAIN * story.get("importance", 0.5) * scale
    c["critical_thinking"] = round(min(1.0, c.get("critical_thinking", 0.5) + gain), 4)
    c["self_confidence"] = round(min(1.0, c.get("self_confidence", 0.6) + gain * 0.3), 4)


_CLOSE_TEXT = {
    "resolved":  "Finally got to the bottom of it: {problem}",
    "cold_case": "Never did figure out what was really going on with: {problem}",
    "expired":   "Gave up trying to figure out: {problem}",
}


def _close_story(c, story, world, outcome):
    story["resolved"] = outcome == "resolved"
    story["final_outcome"] = outcome
    story["closed_tick"] = world.get("tick", 0)

    if outcome == "resolved":
        _maybe_team_credit(c, story, world)

    text = _CLOSE_TEXT.get(outcome, "Closed the books on: {problem}").format(
        problem=story.get("problem_statement", "something strange")
    )
    store_memory(
        c, text, importance=0.4 + story.get("importance", 0.5) * 0.3,
        tags=["detective"] + story.get("tags", []), tick=world.get("tick", 0),
        people=list(set(story.get("involved_ids", []) + story.get("suspect_ids", []))),
        score=len(story.get("chapters", [])),
    )


def _maybe_team_credit(c, story, world):
    """Whoever else in c's household independently resolved their own
    copy of the SAME mystery (same origin_id) gets the household counted
    as having solved it as a team -- a real, if approximate, stand-in for
    "worked it out together" without needing to track literal joint
    investigation sessions."""
    if story.get("team_credit_given"):
        return
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return
    chars = world.get("characters", {})
    teammates = []
    for mid in household.get("members", []):
        if mid == c.get("id"):
            continue
        member = chars.get(mid)
        if not member:
            continue
        for s in member.get("detective_stories", {}).values():
            if s.get("origin_id") == story.get("origin_id") and s.get("resolved"):
                teammates.append(member)
                break
    if teammates:
        story["team_credit_given"] = True
        household["investigative_pride"] = round(
            min(100.0, household.get("investigative_pride", 0.0) + TEAM_PRIDE_GAIN * 100), 2
        )


# ── Flagship detector: unsettling mail addressed to a specific kid ────────
# The user's own worked example: a letter addressed to a child in the
# household, unsettling enough that the recipient identifies it as a real
# problem the moment they read it -- which (per the kid-bypass rule)
# means going straight to a grown-up, not another kid.

UNSETTLING_LETTER_DAILY_CHANCE = 0.004


def maybe_send_unsettling_letter(world):
    """Daily-cadence sweep (called once per real day from sim_loop.py's
    existing daily block, matching the other maybe_* triggers this
    session already built): small chance per household with a child of a
    real, LLM-authored unsettling letter arriving addressed to them."""
    chars = world.get("characters", {})
    for household in world.get("households", {}).values():
        if random.random() >= UNSETTLING_LETTER_DAILY_CHANCE:
            continue
        kids = [chars[mid] for mid in household.get("members", [])
                if mid in chars and chars[mid].get("age_group") in ("child", "teen")]
        if not kids:
            continue
        kid = random.choice(kids)
        from llm.unsettling_letter import generate_unsettling_letter
        letter_text = generate_unsettling_letter(kid, world)
        from systems.mail import create_personal_letter
        create_personal_letter(household, world, kid["id"], "unsettling", letter_text)


def check_personal_mail(c, world):
    """Daily-cadence per-character check: any unopened mail addressed
    specifically to c (not the household generically) gets read the next
    time this runs while they're home. An unsettling one becomes a real
    detective_story on the spot -- the moment they read it, per the
    user's own framing."""
    if c.get("off_grid"):
        return
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return
    mailbox = household.get("mailbox", {})
    for mail in mailbox.get("items", []):
        if mail.get("opened") or mail.get("addressed_to") != c["id"]:
            continue
        mail["opened"] = True
        if mail.get("letter_type") == "unsettling":
            start_detective_story(
                c, world, ["unsettling_contact"],
                "Got a letter that doesn't sit right with me.",
                main_question="Who sent this, and should I be worried?",
                context={"mail_id": mail["id"], "letter_text": mail.get("content")},
            )


# ── More detection hooks (called from each host system directly) ─────────
# Each is a small, additive call at a real existing signal this session
# already built or found -- no new detection machinery invented, just a
# real detective_story started at a moment that already meaningfully
# happens. Every one guards against re-firing for the same underlying
# fact via a light "already have a story about this" check.

def _already_has_tagged_story(c, tag, about_id=None):
    for s in c.get("detective_stories", {}).values():
        if tag not in s.get("tags", []):
            continue
        if about_id is None or about_id in s.get("involved_ids", []) or about_id in s.get("suspect_ids", []):
            return True
    return False


def notice_job_loss(c, world):
    """Hooked from core/event_handlers.py's existing character_fired
    subscriber. The fired character themselves, plus a spouse/partner if
    one exists, each get their own copy of the worry."""
    if _already_has_tagged_story(c, "job_loss"):
        return
    story = start_detective_story(
        c, world, ["job_loss"], "Lost my job -- now what?",
        main_question="How do we cover the bills from here?",
        involved_ids=[c["id"]], role="involved", goal="resolve",
    )
    chars = world.get("characters", {})
    for oid, rel in c.get("relationships", {}).items():
        if any(l in rel.get("labels", []) for l in ("partner", "spouse")):
            partner = chars.get(oid)
            if partner:
                share_detective_story(c, partner, story["id"], world, forced=True)


_SUBSTANCE_ABUSE_NOTICE_CHANCE = 0.20


def notice_substance_abuse(c, key, world):
    """Hooked from addictions.py::tick_addictions at the same threshold-
    crossing moment maybe_induce_depression_from_addiction already fires
    on -- a co-resident household member (not the one using) has a real
    chance of noticing and worrying about it."""
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return
    chars = world.get("characters", {})
    for mid in household.get("members", []):
        if mid == c["id"]:
            continue
        member = chars.get(mid)
        if not member or member.get("age_group") == "child":
            continue
        if _already_has_tagged_story(member, "substance_abuse", c["id"]):
            continue
        if random.random() >= _SUBSTANCE_ABUSE_NOTICE_CHANCE:
            continue
        start_detective_story(
            member, world, ["substance_abuse"],
            f"{c.get('name', 'they')} has been drinking/using more than seems okay.",
            main_question="How bad has this actually gotten, and what can I do?",
            suspect_ids=[c["id"]], role="witness", goal="protect",
        )


def notice_teen_pregnancy(female, world):
    """Hooked from pregnancy.py::_on_discovery, teen branch only."""
    adult = _find_household_adult(female, world)
    if not adult or _already_has_tagged_story(adult, "teen_pregnancy", female["id"]):
        return
    start_detective_story(
        adult, world, ["teen_pregnancy"],
        f"{female.get('name', 'they')} is pregnant, and there's a lot to figure out.",
        main_question="What does the family actually do now?",
        involved_ids=[female["id"]], role="involved", goal="protect",
    )


def notice_persona_mismatch(discoverer_a_id, discoverer_b_id, sociopath_id, world):
    """Hooked from sociopathy.py::maybe_discover_persona_mismatch."""
    chars = world.get("characters", {})
    for did in (discoverer_a_id, discoverer_b_id):
        discoverer = chars.get(did)
        if not discoverer or _already_has_tagged_story(discoverer, "stalker_sociopath", sociopath_id):
            continue
        start_detective_story(
            discoverer, world, ["stalker_sociopath"],
            "Someone I know has been lying about who they are.",
            main_question="What else haven't they been honest about?",
            suspect_ids=[sociopath_id], role="witness", goal="resolve",
        )


_PORN_ADDICTION_THRESHOLD = 0.75


def notice_porn_addiction(c, world):
    """Hooked from harassment.py::on_porn_session, once porn_habit
    crosses an obsessive threshold. A real partner notices, if there is
    one -- otherwise no detector fires (nobody's watching)."""
    if _already_has_tagged_story(c, "porn_addiction"):
        return
    chars = world.get("characters", {})
    for oid, rel in c.get("relationships", {}).items():
        if not any(l in rel.get("labels", []) for l in ("partner", "spouse")):
            continue
        partner = chars.get(oid)
        if not partner:
            continue
        start_detective_story(
            partner, world, ["porn_addiction"],
            f"{c.get('name', 'they')}'s porn habit seems to be taking over.",
            main_question="Is this actually a problem, and should I say something?",
            suspect_ids=[c["id"]], role="witness", goal="resolve",
        )
        return


def notice_economic_concern(c, world):
    """Hooked from government_debt.py::apply_debt_consequences, once debt
    crosses the same credit-penalty threshold that system already uses."""
    if _already_has_tagged_story(c, "economic_concern"):
        return
    start_detective_story(
        c, world, ["economic_concern"], "The debt keeps piling up faster than I can pay it down.",
        main_question="Is there a real way out of this hole?",
        involved_ids=[c["id"]], role="involved", goal="resolve",
    )


MISSING_ITEM_DAILY_CHANCE = 0.003


def maybe_report_missing_item(world):
    """Daily-cadence sweep (sim_loop.py): small chance per household with
    real owned props of one going "missing" -- a household member
    notices. Deliberately abstract (no real prop gets removed/relocated;
    the mystery -- and its LLM-decided resolution -- is what's real, not
    a physical object simulation)."""
    chars = world.get("characters", {})
    props = world.get("props", [])
    prop_list = props.values() if isinstance(props, dict) else props
    by_household = {}
    for p in prop_list:
        hid = p.get("household_id")
        if hid:
            by_household.setdefault(hid, []).append(p)

    for hid, household in world.get("households", {}).items():
        if random.random() >= MISSING_ITEM_DAILY_CHANCE:
            continue
        members = [chars[mid] for mid in household.get("members", []) if mid in chars]
        if not members:
            continue
        owned = by_household.get(hid, [])
        item_name = random.choice(owned)["name"] if owned and random.random() < 0.7 else "the missing item"
        noticer = random.choice(members)
        start_detective_story(
            noticer, world, ["missing_item"], f"Can't find {item_name} anywhere.",
            main_question="Did someone move it, or did it actually go missing?",
        )


# ── World-tick sweep ────────────────────────────────────────────────────────

def tick_detective_work(world):
    for c in world.get("characters", {}).values():
        stories = c.get("detective_stories")
        if not stories:
            continue
        for story in list(stories.values()):
            if story.get("resolved") or story.get("final_outcome"):
                continue
            try:
                advance_chapter(c, story, world)
            except Exception:
                pass
