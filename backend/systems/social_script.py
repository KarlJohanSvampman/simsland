"""
systems/social_script.py -- what you're supposed to be and do, and what it costs to fall behind.

Every character carries society's script by default (asked for 2026-11-24): get through school and get educated,
find decent work, find love, get a driver's license, a home of your own, start a family, have children and in time
grandchildren. Parents, the state, friends, colleagues and classmates all expect it, and what the people around you
have already got is the yardstick. Falling behind breeds hopelessness -- most of all about love, which so much of the
rest hangs on -- and everyone fears ending up isolated. People expect others (and themselves) to be selfish, jealous
or spiteful at times; grumbling together about a third party is one way people bond.

Three traits shape it (definitions.json trait_templates):
  conformist          fears shame and isolation more, does what grown-ups are supposed to do -- no more, no less --
                      practical and logical rather than creative or philosophical, and uses shame to keep others in
                      line (quirks, choices, the way they talk or walk). Shame hurts them most. ~3 in 10.
  nonconformist       objects to shame as a means of control and blames the state and institutions for boxing people
                      in; being shamed (or seeing someone shamed for being different) makes them MORE determined.
                      ~1 in 10.
  validation_seeking  needs praise; makes a plan to go beyond what their parents expect, whatever they want
                      themselves. ~1 in 4.
Rolled once per character, seeded by the character's id (so a running sim gets them without a reset): the existing
"conforming" trait counts as conformist, "independent" leans non-conformist.

c["social_script"] = {
    "milestones": {key: "done" | "not_yet" | "on_track" | "behind" | "far_behind"},   (refreshed hourly)
    "hopelessness": 0..1,     drifts toward what being behind warrants; shame pushes it up, progress pulls it down
    "low_since": tick | None, hopelessness has been high since then (feeds depression after a while)
    "shamed": [{tick, by, line}],   the last few times someone shamed them
    "defiant_until": tick,    a non-conformist made more determined by shame
    "crisis": None | {"stage": "dark" | "crisis", "since": tick, "incident_id": ...},
    "ambition_plan": str,     validation_seeking only
}

The darkest end is a crisis, never fatal (the user's choice): hopelessness at its height, after repeated shaming,
becomes a dark period and then a crisis others can see and step in on -- kind words ease it, and if nobody does, the
character gets help (a crisis line, a doctor) by themselves after a while. Modelled as states and prompt lines only:
nothing in here describes how anyone would harm themselves.
"""

import random
import re

OWNER = "social_script"

# milestone, how it's put to the character, on-track window (age), weight (love counts most)
MILESTONES = [
    ("driver_license", "a driver's license", 18, 20, 1.0),
    ("education", "an education", 18, 24, 1.0),
    ("work", "decent work", 22, 26, 1.0),
    ("partner", "someone to love", 22, 28, 2.0),
    ("home", "a home of your own", 25, 32, 1.0),
    ("children", "children", 27, 35, 1.5),
    ("grandchildren", "grandchildren", 55, 65, 1.0),
]
FAR_BEHIND_YEARS = 5
_LABEL = {k: label for k, label, *_ in MILESTONES}
_EDUCATED = {"certificate", "associate", "bachelor", "master", "doctorate", "professional"}
_PARTNER_LABELS = {"partner", "spouse", "fiance", "fiancee", "girlfriend", "boyfriend", "husband", "wife"}

CONFORMIST_SHARE = 0.30
NONCONFORMIST_SHARE = 0.10
VALIDATION_SHARE = 0.25

HOPE_UP_PER_HOUR = 0.02
HOPE_DOWN_PER_HOUR = 0.03
LOW_HOPELESSNESS = 0.75             # above this for DEPRESSION_AFTER_TICKS -> depression
DEPRESSION_AFTER_TICKS = 3 * 86400
SHAME_WINDOW_TICKS = 7 * 86400
BULLIED_AFTER = 5                   # shamed this many times in SHAME_WINDOW_TICKS
DARK_AT = 0.85
CRISIS_AT = 0.95
CRISIS_SELF_HELP_TICKS = 6 * 3600   # nobody stepped in: they get help themselves
CALM_PER_KIND_LINE = 0.08
DEFIANT_TICKS = 6 * 3600


# ── traits ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _traits(c):
    return set(c.get("traits") or []) | set(c.get("personality_traits") or [])


def ensure_traits(c):
    """Roll conformist / nonconformist / validation_seeking once (seeded by id). Returns the conformity: -1, 0 or 1."""
    st = c.setdefault("social_script", {})
    if not st.get("_rolled"):
        rng = random.Random(f"social_script:{c.get('id')}")
        have = _traits(c)
        if "conformist" not in have and "nonconformist" not in have:
            r = rng.random()
            non = NONCONFORMIST_SHARE * (3 if "independent" in have else 1)
            if "conforming" in have or r < CONFORMIST_SHARE:
                c.setdefault("traits", []).append("conformist")
            elif r < CONFORMIST_SHARE + non:
                c.setdefault("traits", []).append("nonconformist")
        if "validation_seeking" not in have and rng.random() < VALIDATION_SHARE:
            c.setdefault("traits", []).append("validation_seeking")
        st["_rolled"] = True
    return conformity(c)


def conformity(c):
    t = _traits(c)
    return 1 if "conformist" in t else (-1 if "nonconformist" in t else 0)


# ── milestones ────────────────────────────────────────────────────────────────────────────────────────────────────

def _family(world, c):
    return (world.get("families") or {}).get(c.get("family_id")) or {}


def children_of(world, c):
    fam, cid = _family(world, c), c.get("id")
    out = [k.split(":", 1)[1] for k, v in (fam.get("relations") or {}).items() if v == "parent" and k.startswith(cid + ":")]
    for fid, f in (world.get("families") or {}).items():          # a child may sit in another family record
        if f is fam:
            continue
        out += [k.split(":", 1)[1] for k, v in (f.get("relations") or {}).items()
                if v == "parent" and k.startswith(cid + ":")]
    return list(dict.fromkeys(out))


def parents_of(world, c):
    fam, cid = _family(world, c), c.get("id")
    return [k.split(":", 1)[0] for k, v in (fam.get("relations") or {}).items() if v == "parent" and k.endswith(":" + cid)]


def achieved(world, c, key):
    if key == "driver_license":
        try:
            from systems.personal_items import has_valid_license
            return has_valid_license(c)
        except Exception:
            return False
    if key == "education":
        return str(c.get("education") or "") in _EDUCATED
    if key == "work":
        occ = c.get("occupation")
        return bool(c.get("job")) or (occ not in (None, "", "none")) or (c.get("age") or 0) >= 65
    if key == "partner":
        return any(_PARTNER_LABELS & set(r.get("labels") or []) for r in (c.get("relationships") or {}).values())
    if key == "home":
        if not c.get("household_id") or (c.get("age") or 0) < 18:
            return False
        chars = world.get("characters") or {}
        return not any((chars.get(p) or {}).get("household_id") == c["household_id"] for p in parents_of(world, c))
    if key == "children":
        return bool(children_of(world, c))
    if key == "grandchildren":
        chars = world.get("characters") or {}
        return any(children_of(world, chars[k]) for k in children_of(world, c) if k in chars)
    return False


def milestone_status(world, c):
    age = c.get("age") or 0
    out = {}
    for key, _label, start, end, _w in MILESTONES:
        if achieved(world, c, key):
            out[key] = "done"
        elif age < start:
            out[key] = "not_yet"
        elif age <= end:
            out[key] = "on_track"
        elif age <= end + FAR_BEHIND_YEARS:
            out[key] = "behind"
        else:
            out[key] = "far_behind"
    if out.get("partner") in ("behind", "far_behind") and out.get("children") == "done":
        # They found love once -- a family to show for it (a widower, a single parent): the script presses less.
        # Live (2026-11-24): Daniel, 68 with children and grandchildren, came out "far behind" on love.
        out["partner"] = "done" if age >= 55 else "behind"
    return out


def behind_score(status):
    """0 (on track) .. ~1 (badly behind on much of it)."""
    weights = {k: w for k, _l, _s, _e, w in MILESTONES}
    total = sum(weights.values())
    got = sum(weights[k] * {"behind": 1.0, "far_behind": 2.0}.get(s, 0.0) for k, s in status.items())
    return min(1.0, got / total * 1.6)


def peers_ahead(world, c, status, limit=2):
    """People they know, about their age, who already have what they're behind on: "Your friend X has a partner"."""
    chars = world.get("characters") or {}
    age = c.get("age") or 0
    lacking = [k for k, s in status.items() if s in ("on_track", "behind", "far_behind")]
    out = []
    for oid, rel in (c.get("relationships") or {}).items():
        o = chars.get(oid)
        if not o or o is c or abs((o.get("age") or 0) - age) > 5:
            continue
        for k in lacking:
            if achieved(world, o, k):
                out.append((o.get("name") or oid, k))
                break
        if len(out) >= limit:
            break
    return out


# ── hopelessness ──────────────────────────────────────────────────────────────────────────────────────────────────

def _sensitivity(c):
    return {1: 1.4, 0: 1.0, -1: 0.6}[conformity(c)]


def refresh(world, c):
    """Hourly: milestones, hopelessness drifting toward what being behind warrants, depression, the crisis path."""
    if (c.get("age") or 0) < 13 or c.get("alive") is False:
        return
    ensure_traits(c)
    st = c["social_script"]
    tick = world.get("tick", 0)
    before = st.get("milestones") or {}
    status = st["milestones"] = milestone_status(world, c)
    newly = [k for k, s in status.items() if s == "done" and before.get(k) not in (None, "done")]
    hope = float(st.get("hopelessness") or 0.0)
    if newly:
        hope = max(0.0, hope - 0.2 * len(newly))
        _remember(c, world, f"I finally have {', '.join(_LABEL[k] for k in newly)}. Maybe I'm not falling behind after all.", 0.6)
    target = min(1.0, behind_score(status) * _sensitivity(c) + 0.15 * len(_recent_shame(st, tick)) * _sensitivity(c) / 3)
    if st.get("defiant_until", 0) > tick:
        target *= 0.5
    hope = min(target, hope + HOPE_UP_PER_HOUR) if hope < target else max(target, hope - HOPE_DOWN_PER_HOUR)
    st["hopelessness"] = round(hope, 3)
    if hope >= LOW_HOPELESSNESS:
        st.setdefault("low_since", tick)
        if tick - (st.get("low_since") or tick) >= DEPRESSION_AFTER_TICKS:
            mh = c.setdefault("mental_health", [])
            if "depression" not in mh:
                mh.append("depression")
                _remember(c, world, "Nothing I do seems to get me anywhere. It's all slipping away from me.", 0.8)
    else:
        st["low_since"] = None
    if (c.get("traits") and "validation_seeking" in _traits(c)) and not st.get("ambition_plan"):
        st["ambition_plan"] = ambition_plan(world, c)
    _crisis_step(world, c)


def _recent_shame(st, tick):
    return [s for s in st.get("shamed") or [] if tick - s.get("tick", 0) <= SHAME_WINDOW_TICKS]


def tick_all(world, entry=None):
    for c in (world.get("characters") or {}).values():
        try:
            refresh(world, c)
        except Exception as exc:                       # noqa: BLE001
            print(f"[social_script] {c.get('id')}: {exc!r}")


# ── shame and support (heard in speech) ───────────────────────────────────────────────────────────────────────────

# Aimed at the listener, not about someone else: live (2026-11-24) Daniel's apology to Patrick, which went on about
# Anthony "acting strange", counted as shaming Patrick.
_ADJ = (r"(?:weird|strange|odd|freaky|a freak|embarrassing|an embarrassment|pathetic|a loser|a disgrace|ridiculous|"
        r"childish|immature|abnormal|not normal|shameful|a joke)")
_SHAME_RE = re.compile(
    r"(?i)\byou(?:'re|\s+are|\s+look|\s+sound|\s+seem|\s+act|'re acting|\s+are acting|'re being|\s+are being)\s+"
    r"(?:so\s+|really\s+|such\s+|kind of\s+|a bit\s+|totally\s+)?" + _ADJ + r"\b"
    r"|\byour\s+\w+(?:\s+\w+)?\s+(?:is|are|looks?|sounds?)\s+(?:so\s+|really\s+|totally\s+)?" + _ADJ + r"\b"
    r"|\b(?:shame on you|you should be ashamed|act (?:normal|your age)|grow up|what'?s wrong with you|"
    r"what will people (?:think|say)|people will talk|still single|still no (?:job|girlfriend|boyfriend|wife|husband|kids)|"
    r"at your age|why can'?t you (?:just )?be normal|the way you (?:talk|walk|dress|speak|look)|"
    r"no one will (?:want|marry) you|nobody (?:wants|likes) you)\b")
_SHAME_ACTS = {"insult", "mock", "criticize", "criticise", "ridicule", "belittle", "humiliate"}
_KIND_RE = re.compile(
    r"(?i)\b(i'?m here for you|you'?re not alone|it'?ll be (?:okay|ok|alright)|i care about you|you matter|"
    r"we'?ll get through|talk to me|i'?ve got you|you can tell me|proud of you|you'?re doing (?:fine|well|great))\b")
_KIND_ACTS = {"supportive", "comfort", "reassure", "encourage", "compliment"}


def is_shaming(utterance, speech_act=None):
    return bool(_SHAME_RE.search(utterance or "")) or (speech_act or "").lower() in _SHAME_ACTS


def is_kind(utterance, speech_act=None):
    return bool(_KIND_RE.search(utterance or "")) or (speech_act or "").lower() in _KIND_ACTS


def on_speech(data, world):
    """speech_spoken (systems/action_router.py): shame lands on the person spoken to; witnesses who are non-conformist
    take it as more reason to defy; kind words ease a crisis."""
    chars = world.get("characters") or {}
    speaker, target = chars.get(data.get("character_id")), chars.get(data.get("target_id"))
    if not speaker or not target or target is speaker:
        return
    line, act = data.get("utterance") or "", data.get("speech_act")
    if is_kind(line, act):
        calm(world, target, speaker)
    if not is_shaming(line, act):
        return
    shamed(world, target, speaker, line)
    for o in chars.values():                           # non-conformists who see someone shamed for being different
        if o in (speaker, target) or conformity(o) != -1 or o.get("building_id") != speaker.get("building_id"):
            continue
        if abs((o.get("x") or 0) - (speaker.get("x") or 0)) + abs((o.get("y") or 0) - (speaker.get("y") or 0)) > 8:
            continue
        o.setdefault("social_script", {})["defiant_until"] = world.get("tick", 0) + DEFIANT_TICKS
        _remember(o, world, f"{speaker.get('name')} tried to shame {target.get('name')} for being different. "
                            f"That's exactly what's wrong -- people should be allowed to be who they are.", 0.5)


def shamed(world, c, by, line):
    ensure_traits(c)
    st = c["social_script"]
    tick = world.get("tick", 0)
    st["shamed"] = (_recent_shame(st, tick) + [{"tick": tick, "by": by.get("id"), "line": line[:160]}])[-12:]
    who = by.get("name") or "Someone"
    if conformity(c) == -1:
        st["defiant_until"] = tick + DEFIANT_TICKS
        st["hopelessness"] = round(max(0.0, (st.get("hopelessness") or 0) - 0.02), 3)
        _remember(c, world, f'{who} tried to shame me: "{line[:120]}". It only makes me more determined -- it\'s '
                            f"the system and people like that who won't let anyone just be themselves.", 0.55)
        return
    bump = 0.08 if conformity(c) == 1 else 0.04
    st["hopelessness"] = round(min(1.0, (st.get("hopelessness") or 0) + bump), 3)
    _remember(c, world, f'{who} made me feel ashamed: "{line[:120]}"', 0.6 if conformity(c) == 1 else 0.45)
    _crisis_step(world, c)


def bullied(c, world):
    return len(_recent_shame(c.get("social_script") or {}, world.get("tick", 0))) >= BULLIED_AFTER


# ── the crisis path (never fatal) ─────────────────────────────────────────────────────────────────────────────────

def _crisis_step(world, c):
    st = c.setdefault("social_script", {})
    hope = st.get("hopelessness") or 0
    tick = world.get("tick", 0)
    cr = st.get("crisis")
    far = sum(1 for s in (st.get("milestones") or {}).values() if s == "far_behind")
    pressed = bullied(c, world) or far >= 2
    if not cr:
        if hope >= DARK_AT and pressed:
            st["crisis"] = {"stage": "dark", "since": tick}
            _remember(c, world, "I feel like a failure. Everyone else manages; I never will.", 0.75)
        return
    if cr["stage"] == "dark":
        if hope < DARK_AT - 0.15:
            st["crisis"] = None
        elif hope >= CRISIS_AT and _recent_shame(st, tick):
            cr.update(stage="crisis", since=tick)
            try:
                from systems.emergency import report_medical_emergency_incident
                inc = report_medical_emergency_incident(world, c)
                inc["type"] = "mental_health_crisis"
                inc["detail"] = "in a mental health crisis -- overwhelmed, hopeless, needs someone"
                cr["incident_id"] = inc.get("id")
            except Exception as exc:                   # noqa: BLE001
                print(f"[social_script] crisis incident for {c.get('id')}: {exc!r}")
            _alert_household(world, c)
        return
    if cr["stage"] == "crisis" and tick - cr.get("since", tick) >= CRISIS_SELF_HELP_TICKS:
        _recover(world, c, "Nobody came, so I called for help myself. Talking to someone helped a little.")


def _alert_household(world, c):
    from brain.cognition_scheduler import wake_character
    for o in (world.get("characters") or {}).values():
        if o is c or o.get("alive") is False:
            continue
        close = o.get("household_id") and o.get("household_id") == c.get("household_id")
        near = o.get("building_id") and o.get("building_id") == c.get("building_id")
        if close or near:
            wake_character(o, world, "someone_in_crisis", {"line": (
                f"{c.get('name')} is in a real crisis -- overwhelmed and hopeless. They need someone with them: go to them, "
                f"listen, tell them they're not alone.")})


def calm(world, c, by):
    st = c.get("social_script") or {}
    cr = st.get("crisis")
    if not cr:
        return False
    st["hopelessness"] = round(max(0.0, (st.get("hopelessness") or 0) - CALM_PER_KIND_LINE), 3)
    if st["hopelessness"] < DARK_AT - 0.15:
        _recover(world, c, f"{by.get('name', 'Someone')} was there for me when I couldn't see a way forward.")
    return True


def _recover(world, c, memory):
    st = c["social_script"]
    cr = st.get("crisis") or {}
    st["crisis"] = None
    st["hopelessness"] = round(min(st.get("hopelessness") or 0, 0.6), 3)
    if cr.get("incident_id"):
        for inc in world.get("incidents") or []:
            if isinstance(inc, dict) and inc.get("id") == cr["incident_id"]:
                inc["status"], inc["resolved"] = "resolved", True
    _remember(c, world, memory, 0.8)


# ── the plan of a validation-seeker ───────────────────────────────────────────────────────────────────────────────

def ambition_plan(world, c):
    chars = world.get("characters") or {}
    parents = [chars[p] for p in parents_of(world, c) if p in chars]
    jobs = [p.get("occupation") for p in parents if p.get("occupation") not in (None, "", "none")]
    edu = [p.get("education") for p in parents if p.get("education")]
    if (c.get("age") or 0) < 18:
        return ("Top marks, the best school, a degree beyond " + (f"your parents' ({edu[0]})" if edu else "your parents'")
                + " -- make them proud, whether or not it's what you'd choose.")
    beyond = f"a better job than {parents[0].get('name', 'your parent').split()[0]}'s ({jobs[0]})" if jobs and parents \
        else "a career people look up to"
    return (f"Go beyond what your parents expect: {beyond}, a partner they'd approve of, a house, children -- the "
            f"whole picture, done better than they did, whatever you yourself might want.")


# ── what the prompt says (brain/context_builder.py) ───────────────────────────────────────────────────────────────

_KIND_TRAITS = {"kind", "compassionate", "empathetic", "warm", "gentle", "forgiving"}


def prompt_lines(world, c):
    age = c.get("age") or 0
    if age < 13:
        return []
    ensure_traits(c)
    st = c["social_script"]
    if "milestones" not in st:
        st["milestones"] = milestone_status(world, c)
    tick = world.get("tick", 0)
    t, conf = _traits(c), conformity(c)
    lines = []
    outlook = ("Like most people, you feel you're supposed to get through school, get an education, find decent work, "
               "find love, get a driver's license and a home, and start a family -- children, one day grandchildren. "
               "Ending up alone and left out is what you fear. You expect people, yourself included, to be selfish, "
               "jealous or spiteful at times")
    outlook += (", though you try not to be." if t & _KIND_TRAITS else
                "; grumbling together about someone else is one way people get closer.")
    if age < 18:
        outlook = ("You feel the pressure to do well at school and turn out the way your parents, teachers and friends "
                   "expect; being left out is what you fear most. Kids can be mean -- you know, and sometimes you are too.")
    lines.append(outlook)
    if conf == 1:
        lines.append("You care a great deal about fitting in and dread shame. You do what grown-ups are supposed to do -- "
                     "no more, no less -- and think practically and logically rather than in creative ideas or "
                     "philosophy. When someone is odd or improper (a quirk, a choice, how they talk, walk or dress, "
                     "being behind in life) you let them know, to bring them in line.")
    elif conf == -1:
        lines.append("You go your own way. Shaming people into line is wrong, and the state and institutions box "
                     "people in instead of letting them be who they are. Being judged only makes you more determined.")
    if "validation_seeking" in t:
        plan = st.get("ambition_plan") or ambition_plan(world, c)
        st["ambition_plan"] = plan
        lines.append(f"You live for praise and approval. Your plan: {plan}")
    status = st.get("milestones") or {}
    if age >= 18:
        done = [_LABEL[k] for k, s in status.items() if s == "done"]
        behind = [_LABEL[k] for k, s in status.items() if s in ("behind", "far_behind")]
        bits = []
        if done:
            bits.append("you have " + ", ".join(done))
        if behind:
            bits.append("you're behind on " + ", ".join(behind))
        if bits:
            lines.append("Where you stand: " + "; ".join(bits) + ".")
        ahead = peers_ahead(world, c, status)
        if ahead and behind:
            lines.append("Meanwhile " + "; ".join(f"{n} already has {_LABEL[k]}" for n, k in ahead) + ".")
    hope = st.get("hopelessness") or 0
    if st.get("defiant_until", 0) > tick:
        lines.append("Being judged has lit a fire under you: you're set on proving them wrong.")
    elif hope >= 0.75:
        lines.append("Lately you feel hopeless about ever getting there; it drains your motivation for everything.")
    elif hope >= 0.45:
        lines.append("You worry you're falling behind, and it nags at you.")
    cr = st.get("crisis")
    if cr and cr.get("stage") == "dark":
        lines.append("You feel like a failure and want to hide from everyone. Part of you knows talking to someone "
                     "would help.")
    elif cr and cr.get("stage") == "crisis":
        lines.append("You're overwhelmed and can't see a way forward right now. You need someone; reaching out, or "
                     "letting someone in, is the one thing that helps.")
    return lines


def _remember(c, world, text, importance):
    try:
        from brain.memory import store_memory
        store_memory(c, text, importance=importance, tags=["social_script"], tick=world.get("tick", 0),
                     source="internal")
    except Exception:
        pass


# ── wiring ────────────────────────────────────────────────────────────────────────────────────────────────────────

from core import scheduler as _scheduler        # noqa: E402
from core.event_bus import subscribe as _subscribe   # noqa: E402

_scheduler.register_hourly(OWNER, tick_all, at=1800)
_subscribe("speech_spoken", on_speech)
