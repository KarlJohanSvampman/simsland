"""
systems/relationship_recovery.py -- feelings about someone heal with time, and a line only counts as hurtful when it is.

Live (2026-11-27): every relationship between the nine family members and neighbours was "enemy" -- spouses at trust
-80, hostility and resentment 100; Rachel and her own daughter enemies. Two causes:

  1. Nothing ever recovered. brain/relationships.py::decay_relationships() was never called (and measured wall-clock
     time against sim ticks), so every slight stayed forever and they only added up.
  2. Ordinary lines were booked as insults. The reply format's INTENT line ("hurt | help | deceive") was marked "hurt"
     on worried or serious lines -- "We need to check on the kids, I'm getting really worried.", "I really need to
     go." -- and every "hurt" is an insult: respect, friendship and trust down, resentment and hostility up, for the
     listener and (smaller) for everyone who heard it. 936 of 1,149 recorded impacts were "insults".

So:

  * recover(): hostility, resentment and fear fade toward 0 (halving every RECOVER_NEGATIVE_DAYS); trust, friendship,
    respect and comfort climb back toward their resting level -- what living together implies for family
    (systems/household_bonds.py), 0 for others -- halving the gap every RECOVER_POSITIVE_DAYS. Feelings above the resting
    level aren't touched: good ones don't fade here. Lazy, by sim time; run hourly for everyone.
  * hurt_is_plausible(): an INTENT "hurt" stands when the line reads hostile, or the speaker is heated and isn't asking,
    praising, suggesting, requesting, compromising, negotiating or flirting (systems/conversation_acts.py); otherwise
    it's treated as neutral (systems/action_router.py::apply_speech).
  * repair_preview() / repair(): the same recovery, N days' worth at once, for relationships worn down by the above
    (POST /admin/relationships/recover -- a dry run unless asked).
"""

import re

from core import scheduler as _scheduler

DAY = 86400
RECOVER_NEGATIVE_DAYS = 2.0       # hostility / resentment / fear halve every two sim days
RECOVER_POSITIVE_DAYS = 4.0       # trust / friendship / respect / comfort close half the gap to their resting level
NEGATIVE = ("hostility", "resentment", "fear")
POSITIVE = ("trust", "friendship", "respect", "comfort")
OWNER = "relationship_recovery"


def resting_level(c, oid, rel, world):
    """Where the positive feelings settle on their own: the household bond for family who live together, a little
    for other kin, 0 for everyone else."""
    try:
        from systems.household_bonds import FLOORS, OTHER_KIN
    except Exception:                                     # noqa: BLE001
        FLOORS, OTHER_KIN = {}, {}
    kin = rel.get("kinship")
    other = (world.get("characters") or {}).get(oid) or {}
    together = c.get("household_id") and c.get("household_id") == other.get("household_id")
    if not kin and together:
        kin = _household_kin(c, other)       # live: Rebecca's links to her own sons carried no kinship, only Anthony's
    if not kin or kin == "ex_spouse":
        return {k: 0.0 for k in POSITIVE}
    base = dict(FLOORS.get(kin) or OTHER_KIN) if together else {k: v / 2 for k, v in OTHER_KIN.items()}
    out = {k: float(base.get(k, 0)) for k in POSITIVE}
    out["respect"] = max(out.get("respect", 0.0), 0.5 * out.get("trust", 0.0))      # family: some respect by default
    return out


_YOUNG = {"infant", "toddler", "child", "teen"}


def _household_kin(c, other):
    """Family by the household, when the kinship label is missing: an adult and a child at home are parent and
    child, two children siblings."""
    a, b = c.get("age_group") in _YOUNG, other.get("age_group") in _YOUNG
    if a and b:
        return "sibling"
    if not a and b:
        return "parent"
    if a and not b:
        return "child"
    return None


def _heal(value, rest, dt, half_life_days, upward_only):
    if upward_only and value >= rest:
        return value
    return rest + (value - rest) * 0.5 ** (dt / (half_life_days * DAY))


def recover_relationship(c, oid, rel, world, dt):
    """`dt` sim seconds of healing on one relationship; True if anything moved."""
    if dt <= 0:
        return False
    moved = False
    for k in NEGATIVE:
        v = float(rel.get(k, 0) or 0)
        if v > 0:
            nv = round(_heal(v, 0.0, dt, RECOVER_NEGATIVE_DAYS, upward_only=False), 3)
            moved |= nv != v
            rel[k] = nv
    rest = resting_level(c, oid, rel, world)
    for k in POSITIVE:
        v = float(rel.get(k, 0) or 0)
        nv = round(_heal(v, rest[k], dt, RECOVER_POSITIVE_DAYS, upward_only=True), 3)
        moved |= nv != v
        rel[k] = nv
    return moved


def _now(world):
    from core.clock import now_ts
    return now_ts(world)


def recover(c, world, now=None):
    """Bring c's feelings about everyone up to date (lazy: by the sim time since the last time)."""
    now = _now(world) if now is None else now
    last = c.get("_rel_recovered_ts")
    c["_rel_recovered_ts"] = now
    if last is None or now <= last:
        return 0
    dt = min(now - last, 30 * DAY)
    n = 0
    from brain.relationships import update_relationship_state
    for oid, rel in list((c.get("relationships") or {}).items()):
        if isinstance(rel, dict) and recover_relationship(c, oid, rel, world, dt):
            n += 1
            try:
                update_relationship_state(c, oid)
            except Exception:                             # noqa: BLE001
                pass
    return n


def sweep(world, entry=None):
    for c in list((world.get("characters") or {}).values()):
        try:
            recover(c, world)
        except Exception as exc:                          # noqa: BLE001
            print(f"[relationship_recovery] {c.get('id')}: {exc!r}")


# ── "hurt" has to be believable ──────────────────────────────────────────────────────────────────────────────────────

_HOSTILE = re.compile(
    r"\b(idiot|stupid|moron|pathetic|useless|worthless|shut up|hate you|disgust\w*|loser|liar|selfish|lazy|ridiculous|"
    r"how dare|screw you|go to hell|damn you|to hell with|f+u+c+k\w*|shit\w*|bitch\w*|bastard|dumb|grow up|get lost|"
    r"leave me alone|you always|you never|sick of you|can'?t stand you|fed up with you|what is wrong with you|"
    r"get out|piss\w*|jerk|coward|disappointment|ashamed of you)\b", re.I)
_FRIENDLY_ACTS = {"inquiry", "praise", "suggest", "request", "compromise", "negotiate", "flirt"}


def hurt_is_plausible(c, utterance, act=None):
    """Does a line marked INTENT "hurt" read as meant to hurt?"""
    if _HOSTILE.search(utterance or ""):
        return True
    if act in _FRIENDLY_ACTS:
        return False
    return float(c.get("emotional_temperature", 30) or 30) >= 65


def check_intent(c, speech, world, target_id=None):
    """An implausible "hurt" on a line is dropped (and the insult it made of the line). True if it was dropped."""
    intent = (speech or {}).get("intent") or {}
    if intent.get("valence") != "hurt":
        return False
    act = (((c.get("_conv_acts") or {}).get(target_id) or {}).get("act")) if target_id else None
    if hurt_is_plausible(c, speech.get("utterance"), act):
        return False
    speech.pop("intent", None)
    if speech.get("speech_act") == "insult":
        speech["speech_act"] = "declare"
    stats = world.setdefault("_intent_check", {"hurt_kept": 0, "hurt_dropped": 0})
    stats["hurt_dropped"] = stats.get("hurt_dropped", 0) + 1
    return True


# ── repairing what the misread lines did ─────────────────────────────────────────────────────────────────────────────

def repair_preview(world, days):
    """What `days` of recovery at once would do: per pair, before -> after, without changing anything."""
    import copy
    rows = []
    for c in (world.get("characters") or {}).values():
        for oid, rel in (c.get("relationships") or {}).items():
            if not isinstance(rel, dict) or oid not in (world.get("characters") or {}):
                continue
            if not any(float(rel.get(k, 0) or 0) > 0 for k in NEGATIVE) and not any(
                    float(rel.get(k, 0) or 0) < resting_level(c, oid, rel, world)[k] for k in POSITIVE):
                continue
            after = copy.deepcopy(rel)
            recover_relationship(c, oid, after, world, days * DAY)
            rows.append({"from": c.get("name"), "to": world["characters"][oid].get("name"),
                         "kinship": rel.get("kinship"), "state": rel.get("state"),
                         "before": {k: round(float(rel.get(k, 0) or 0)) for k in POSITIVE + NEGATIVE},
                         "after": {k: round(float(after.get(k, 0) or 0)) for k in POSITIVE + NEGATIVE}})
    return rows


def repair(world, days):
    """Apply `days` of recovery to every relationship now."""
    from brain.relationships import update_relationship_state
    n = 0
    for c in (world.get("characters") or {}).values():
        for oid, rel in list((c.get("relationships") or {}).items()):
            if isinstance(rel, dict) and recover_relationship(c, oid, rel, world, days * DAY):
                n += 1
                try:
                    update_relationship_state(c, oid)
                except Exception:                         # noqa: BLE001
                    pass
    return n


_scheduler.register_hourly(OWNER, sweep, at=900)
