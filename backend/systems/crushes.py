"""
systems/crushes.py
──────────────────
Manages a character's crushes, infatuations, and sexual/romantic fantasies.

Crush object schema
───────────────────
{
    "character_id":   str | None,   # null for celebrities / imagined people
    "name":           str,
    "relation_label": str,          # "neighbour", "teacher", "idol", "actor" …
    "attraction_type": "sexual" | "romantic" | "both" | "idol",
    "intensity":      float,        # 0–1
    "is_secret":      bool,
    "is_celebrity":   bool,         # True for public figures / pop stars / athletes
    "celebrity_id":   str | None,   # key into definitions["celebrity_registry"]
    "style_influence": bool,        # whether they copy this person's style
    "fantasy_count":  int,
    "last_fantasy_tick": int,
}

Blushing
────────
blush_score is raised whenever a character:
  - Is in conversation and the topic turns sexual/romantic
  - Is directly flirted with
  - Sees or thinks about their crush
  - Experiences a sexually embarrassing moment

blush_score decays per tick. Frontend reads `is_blushing` to play the blush
reaction animation and tint the character's cheeks.

Thought bubbles
───────────────
When a character fantasises about a crush, or forms a strong intention, the
thought_bubble field is populated. Frontend polls this and renders an overlay
with the subject's portrait_url + caption text. Expires after BUBBLE_DURATION ticks.
"""

import random

TICKS_PER_HOUR  = 60
TICKS_PER_DAY   = TICKS_PER_HOUR * 24

# Blushing
BLUSH_DECAY_PER_TICK = 0.002          # 0→full fade in ~8 game-minutes
BLUSH_THRESHOLD      = 0.35           # above this → is_blushing = True

# Topic embarrassment scores (0–1). Blush raise = topic_score × sensitivity
TOPIC_BLUSH = {
    "sex":            1.00,
    "masturbation":   1.00,
    "nudity":         0.90,
    "sexual_advance": 0.85,
    "romance":        0.55,
    "flirting":       0.60,
    "crush":          0.70,
    "pregnancy":      0.50,
    "bodily_function":0.40,
    "embarrassing_moment": 0.65,
    "general_awkward":0.25,
}

# How often (ticks) a character can fantasise about the same crush
FANTASY_COOLDOWN = TICKS_PER_HOUR * 3

# Thought bubble duration
BUBBLE_DURATION = TICKS_PER_HOUR // 2    # 30 game-minutes

# Daydream chance per tick for characters with crushes (base)
DAYDREAM_CHANCE_PER_TICK = 0.0002        # ≈ once every ~83 hours at base


# ── Public API ────────────────────────────────────────────────────────────────

def add_crush(c, target_id, name, relation_label, attraction_type="both",
              intensity=0.50, is_secret=True,
              is_celebrity=False, celebrity_id=None, style_influence=False):
    """
    Add or update a crush entry on a character.
    If a crush for target_id already exists, intensity is blended upward.
    For celebrities: target_id may be None; use celebrity_id as unique key.
    """
    crushes = c.setdefault("crushes", [])

    # Unique key: celebrity_id for celebrities, character_id for real people
    uid = celebrity_id if is_celebrity else target_id

    existing = next((
        x for x in crushes
        if (is_celebrity and x.get("celebrity_id") == celebrity_id) or
           (not is_celebrity and x.get("character_id") == target_id)
    ), None)
    if existing:
        existing["intensity"] = min(1.0, (existing["intensity"] + intensity) / 1.8)
        return existing

    crush = {
        "character_id":      target_id,
        "name":              name,
        "relation_label":    relation_label,
        "attraction_type":   attraction_type,
        "intensity":         round(min(1.0, intensity), 2),
        "is_secret":         is_secret,
        "is_celebrity":      is_celebrity,
        "celebrity_id":      celebrity_id,
        "style_influence":   style_influence,
        "fantasy_count":     0,
        "last_fantasy_tick": 0,
    }
    crushes.append(crush)

    # Apply style influence immediately if flagged
    if style_influence and is_celebrity and celebrity_id:
        _apply_celebrity_style(c, celebrity_id, {})  # world not available here

    return crush


def add_celebrity_idol(c, celebrity_id, world, intensity=None):
    """
    Assign a celebrity idol to a character (typically called during character gen
    for teens/young adults). Picks style_influence=True ~60% of the time.
    """
    defs    = world.get("definitions", {}) if world else {}
    celeb   = defs.get("celebrity_registry", {}).get(celebrity_id, {})
    if not celeb:
        return None

    name    = celeb.get("name", celebrity_id)
    age     = c.get("age", 18)

    if intensity is None:
        # Teens are more intense fans
        base = 0.80 if age < 18 else 0.55
        intensity = round(base - (age - 13) * 0.01, 2) if age < 25 else 0.40
        intensity = max(0.20, min(1.0, intensity))

    style_inf = random.random() < 0.60

    crush = add_crush(
        c, target_id=None, name=name,
        relation_label=celeb.get("category", "celebrity").replace("_", " "),
        attraction_type="idol",
        intensity=intensity,
        is_secret=False,       # having an idol is usually public
        is_celebrity=True,
        celebrity_id=celebrity_id,
        style_influence=style_inf,
    )

    if style_inf:
        _apply_celebrity_style(c, celebrity_id, defs)

    return crush


# ── Real interpersonal crushes (previously dead: add_crush(target_id=...)
# for a REAL character_id was only ever exercised by tests, never called
# by any live system -- every actual crush in the simulation was a
# celebrity idol) ──────────────────────────────────────────────────────

CRUSH_ATTRACTION_THRESHOLD    = 45   # rel["attraction"], 0-100 scale
CRUSH_ROMANTIC_THRESHOLD      = 20   # rel["romantic_interest"], 0-100 scale
CRUSH_DAILY_CHANCE            = 0.05
CRUSH_SECRET_CHANCE           = 0.65  # most real-life crushes start secret


def maybe_form_crush(c, world):
    """Daily-cadence check (sim_loop.py): a real, sustained mutual-enough
    attraction to someone c isn't already committed to has a small daily
    chance of becoming a genuine crush -- the actual gap this closes is
    that NPC-on-NPC crushes never formed at all before this; only
    celebrity idols (add_celebrity_idol, generation-time only) did."""
    chars = world.get("characters", {})
    existing_ids = {x.get("character_id") for x in c.get("crushes", []) if not x.get("is_celebrity")}

    for other_id, rel in c.get("relationships", {}).items():
        if other_id in existing_ids or other_id == c.get("id"):
            continue
        if any(l in rel.get("labels", []) for l in ("partner", "spouse")):
            continue  # already a real relationship, not a crush
        attraction = rel.get("attraction", 0)
        romantic   = rel.get("romantic_interest", 0)
        if attraction < CRUSH_ATTRACTION_THRESHOLD and romantic < CRUSH_ROMANTIC_THRESHOLD:
            continue
        other = chars.get(other_id)
        if not other or not other.get("alive", True):
            continue
        if random.random() >= CRUSH_DAILY_CHANCE:
            continue

        relation_label = "coworker" if rel.get("designation") in ("friend", "close_friend", "best_friend") else "acquaintance"
        add_crush(
            c, target_id=other_id, name=other.get("name", "them"),
            relation_label=relation_label, attraction_type="both",
            intensity=round(min(1.0, attraction / 100.0), 2),
            is_secret=random.random() < CRUSH_SECRET_CHANCE,
        )


def remove_crush(c, target_id):
    c["crushes"] = [x for x in c.get("crushes", []) if x.get("character_id") != target_id]


def tick_crushes(world):
    """
    Per-tick: decay blush, expire thought bubbles, randomly trigger daydreams.
    """
    tick = world.get("tick", 0)
    for c in world.get("characters", {}).values():
        _tick_blush(c, tick)
        _tick_thought_bubble(c, tick)
        _maybe_daydream(c, tick, world)


def apply_topic_blush(c, topic, world, tick=None):
    """
    Raise blush_score when conversation topic is embarrassing.
    topic: key from TOPIC_BLUSH, or a free string (gets mild default).
    """
    if tick is None:
        tick = world.get("tick", 0)

    base_raise = TOPIC_BLUSH.get(topic, 0.15)
    sensitivity = _blush_sensitivity(c)
    raise_amount = base_raise * sensitivity

    if raise_amount < 0.05:
        return

    c["blush_score"] = min(1.0, c.get("blush_score", 0.0) + raise_amount)

    if c["blush_score"] >= BLUSH_THRESHOLD and not c.get("is_blushing"):
        c["is_blushing"] = True
        _push_blush_reaction(c, tick)
        _emit("character_blushing", {
            "character_id": c.get("id"),
            "topic":        topic,
            "blush_score":  c["blush_score"],
            "tick":         tick,
        }, world)


def trigger_crush_thought(c, crush, world):
    """
    Character thinks about a crush — raises blush, fires thought bubble,
    increments fantasy_count. crush is the crush dict from c["crushes"].
    """
    tick = world.get("tick", 0)
    cooldown = FANTASY_COOLDOWN
    if tick - crush.get("last_fantasy_tick", 0) < cooldown:
        return

    crush["fantasy_count"]     = crush.get("fantasy_count", 0) + 1
    crush["last_fantasy_tick"] = tick

    # Blush if romantic or both
    if crush.get("attraction_type") in ("romantic", "both"):
        apply_topic_blush(c, "crush", world, tick)

    # Build thought bubble
    portrait = _get_portrait(crush.get("character_id"), world)
    caption  = _build_crush_caption(c, crush)
    _set_thought_bubble(c, {
        "active":       True,
        "subject_id":   crush.get("character_id"),
        "subject_name": crush.get("name"),
        "portrait_url": portrait,
        "type":         "daydream" if crush["attraction_type"] == "romantic" else "crush",
        "caption":      caption,
        "tick_expires": tick + BUBBLE_DURATION,
    })

    _emit("crush_fantasy", {
        "character_id":  c.get("id"),
        "target_id":     crush.get("character_id"),
        "target_name":   crush.get("name"),
        "relation_label":crush.get("relation_label"),
        "attraction_type": crush.get("attraction_type"),
        "fantasy_count": crush["fantasy_count"],
        "tick":          tick,
    }, world)


def set_intention_bubble(c, caption, subject_id=None, subject_name=None, world=None):
    """
    Show an intention thought bubble (what the character is about to do).
    Called from agent_loop or action_router when character forms a strong intention.
    """
    tick = (world or {}).get("tick", 0)
    portrait = _get_portrait(subject_id, world) if subject_id else None
    _set_thought_bubble(c, {
        "active":       True,
        "subject_id":   subject_id,
        "subject_name": subject_name or "",
        "portrait_url": portrait,
        "type":         "intention",
        "caption":      caption,
        "tick_expires": tick + BUBBLE_DURATION // 3,
    })


def get_crush_context(c, world):
    """LLM context lines about active crushes."""
    crushes = c.get("crushes", [])
    if not crushes:
        return []
    lines = []
    for crush in sorted(crushes, key=lambda x: -x.get("intensity", 0))[:4]:
        atype     = crush.get("attraction_type", "both")
        label     = crush.get("relation_label", "acquaintance")
        name      = crush.get("name", "someone")
        intensity = crush.get("intensity", 0.5)
        is_celeb  = crush.get("is_celebrity", False)

        if is_celeb:
            lines.append(
                f"Big fan of {name} ({label}), intensity {intensity:.0%}."
                + (" Copies their style." if crush.get("style_influence") else "")
            )
        else:
            atype_str = {
                "sexual":  "sexually attracted to",
                "romantic": "romantically infatuated with",
                "both":    "infatuated with",
            }.get(atype, "attracted to")
            secret = " (keeps this secret)" if crush.get("is_secret") else ""
            lines.append(
                f"{atype_str.capitalize()} their {label} {name} "
                f"(intensity {intensity:.0%}){secret}."
            )

    blush = c.get("blush_score", 0.0)
    if blush > BLUSH_THRESHOLD:
        lines.append(f"Currently blushing (score {blush:.2f}).")
    return lines


# ── Internal helpers ──────────────────────────────────────────────────────────

def _blush_sensitivity(c):
    """0–1 multiplier: how easily this character blushes."""
    traits = set(c.get("traits", []))
    sensitivity = 0.50   # base

    if "easily_embarrassed" in traits:  sensitivity += 0.40
    if "sexually_shy"        in traits:  sensitivity += 0.30
    if "sexually_repressed"  in traits:  sensitivity += 0.25
    if "sexually_brazen"     in traits:  sensitivity -= 0.40
    if "sexually_confident"  in traits:  sensitivity -= 0.25
    if "confident"           in traits:  sensitivity -= 0.15

    # Repression score
    repr_score = c.get("repression_state", {}).get("repression_score", 0.0)
    sensitivity += repr_score * 0.30

    return max(0.0, min(1.5, sensitivity))


def _tick_blush(c, tick):
    score = c.get("blush_score", 0.0)
    if score <= 0:
        return
    c["blush_score"] = max(0.0, score - BLUSH_DECAY_PER_TICK)
    c["is_blushing"] = c["blush_score"] >= BLUSH_THRESHOLD


def _tick_thought_bubble(c, tick):
    tb = c.get("thought_bubble", {})
    if not tb.get("active"):
        return
    if tick >= tb.get("tick_expires", 0):
        c["thought_bubble"] = {"active": False}


def _maybe_daydream(c, tick, world):
    """Randomly trigger a crush thought bubble while idle."""
    crushes = c.get("crushes", [])
    if not crushes:
        return
    if c.get("thought_bubble", {}).get("active"):
        return

    # Higher chance for daydreamer / infatuation_prone traits
    traits = set(c.get("traits", []))
    chance = DAYDREAM_CHANCE_PER_TICK
    if "daydreamer"         in traits: chance *= 3.0
    if "infatuation_prone"  in traits: chance *= 2.0

    if random.random() > chance:
        return

    # Pick a crush weighted by intensity
    weights = [x.get("intensity", 0.5) for x in crushes]
    crush   = random.choices(crushes, weights=weights, k=1)[0]
    trigger_crush_thought(c, crush, world)


def _push_blush_reaction(c, tick):
    score = c.get("blush_score", 0.0)
    rtype = "blush_heavy" if score > 0.70 else "blush"
    try:
        from systems.reactions import REACTION_ANIMATIONS, REACTION_PRIORITIES
        import random as _r
        clips    = REACTION_ANIMATIONS.get(rtype, ["react_blush"])
        clip     = _r.choice(clips)
        priority = REACTION_PRIORITIES.get(rtype, 1)
    except Exception:
        clip, priority = "react_blush", 1

    queue = c.setdefault("pending_reactions", [])
    queue.append({"type": rtype, "clip": clip, "priority": priority, "tick": tick})
    c["pending_reactions"] = queue[-4:]


def _set_thought_bubble(c, bubble_data):
    c["thought_bubble"] = bubble_data


def _get_portrait(character_id, world):
    if not character_id or not world:
        return None
    char = world.get("characters", {}).get(character_id)
    return char.get("portrait_url") if char else None


def _build_crush_caption(c, crush):
    atype = crush.get("attraction_type", "both")
    name  = crush.get("name", "them")
    if atype == "idol":
        templates = [
            f"Thinking about {name}…",
            f"Wishing they could meet {name}.",
            f"Daydreaming about {name}.",
            f"Imagining {name} noticed them.",
        ]
    elif atype == "romantic":
        templates = [
            f"Daydreaming about {name}…",
            f"Imagining a date with {name}.",
            f"Wishing {name} was here.",
        ]
    elif atype == "sexual":
        templates = [
            f"Thinking about {name}.",
            f"Fantasising about {name}.",
        ]
    else:
        templates = [
            f"Thinking about {name}…",
            f"Can't stop thinking about {name}.",
        ]
    return random.choice(templates)


def _apply_celebrity_style(c, celebrity_id, defs):
    """Copy celebrity's style_tags onto character's style_preferences."""
    celeb = defs.get("celebrity_registry", {}).get(celebrity_id, {})
    tags  = celeb.get("style_tags", [])
    if not tags:
        return
    prefs = c.setdefault("style_preferences", [])
    for tag in tags:
        if tag not in prefs:
            prefs.append(tag)


def _emit(event_type, data, world):
    try:
        from core.events import emit
        emit(event_type, data, world)
    except Exception:
        pass
