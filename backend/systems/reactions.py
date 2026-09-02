import random

# =========================================================
# REACTION ANIMATIONS
# Maps reaction type → list of animation clip stems.
# These are played on the upper body only (LoopOnce) as an
# interrupt over whatever the character is currently doing.
#
# Clip names must match GLB action names exactly (lowercase).
# Multiple variants in a list are chosen at random.
# =========================================================

REACTION_ANIMATIONS = {
    # ── Surprise family ──
    "surprise":     ["react_surprise", "react_gasp"],
    "startled":     ["react_startled"],
    "shocked":      ["react_shocked", "react_gasp"],

    # ── Negative ──
    "disgust":      ["react_disgust", "react_recoil"],
    "fear":         ["react_fear", "react_cower"],
    "angry_react":  ["react_angry", "react_fist"],

    # ── Positive ──
    "laugh":        ["react_laugh", "react_chuckle", "react_laugh_big"],
    "happy_react":  ["react_happy", "react_clap"],

    # ── Social / conversational ──
    "nod":          ["react_nod", "react_nod_slow"],
    "shake_head":   ["react_shake_head"],
    "confused":     ["react_confused", "react_scratch_head"],
    "interested":   ["react_interested", "react_lean"],
    "shrug":        ["react_shrug"],

    # ── Environmental ──
    "look_around":        ["react_look_around"],

    # ── Hostile actions (systems/hostile_actions.py) ──
    "dodge":        ["react_dodge"],
    "block":        ["react_block"],

    # ── Symptoms (systems/health.py::tick_symptom_reactions) ──
    "cough":        ["react_cough"],
    "sweating":     ["react_sweating", "react_wipe_brow"],
    "breathless":   ["react_breathless"],
    "dizzy":        ["react_dizzy", "react_stumble"],
    "vomit":        ["react_vomit"],

    # ── Pain/discomfort reactions ──
    "wince":        ["react_wince"],
    "cry_out":      ["react_cry_out", "react_wince"],

    # ── Nudity / sexual ──
    "saw_nudity":          ["react_shocked",      "react_gasp",       "react_look_away"],
    "walked_in_on_sex":    ["react_shocked",      "react_gasp",       "react_back_away"],
    "heard_sex_sounds":    ["react_startled",     "react_look_around"],
    "look_away":           ["react_look_away"],
    "embarrassed":         ["react_embarrassed"],
    "aroused_react":       ["react_interested",   "react_stare"],

    # ── Embarrassment / blushing ──
    "blush":               ["react_blush"],
    "blush_heavy":         ["react_blush_heavy"],
    "flustered":           ["react_flustered", "react_blush"],

    # ── Person being walked in on ──
    "horrified_scream":    ["react_horrified_scream"],        # female walked in on by stranger
    "embarrassed_scream":  ["react_embarrassed_scream"],      # female moderate shame
    "cover_up_gasp":       ["react_cover_up",  "react_gasp"], # topless / bath
    "cover_up":            ["react_cover_up"],                 # mild cover-up

    # ── Involuntary sounds (see REACTION_SOUNDS / trigger_reaction below) ──
    "sneeze":       ["react_sneeze"],
    "gas_release":  ["react_gas"],
    "moan_pain":    ["react_wince"],       # shares wince's clip -- no dedicated one authored
    "moan_pleasure": ["react_interested"],  # shares interested's clip -- no dedicated one authored

    # ── Physical impact (systems/hostile_actions.py shove outcomes) ──
    "stagger":      ["react_stumble"],
    "fall_down":    ["react_fall"],
    "avoid_hit":    ["react_dodge"],

    # ── Verbal/emotional (no dedicated clip authored -- shares the
    # nearest existing family, matches this file's own precedent of
    # sharing clips across related types, e.g. moan_pain/wince above) ──
    "scared_verbal":   ["react_fear", "react_cower"],
    "angry_verbal":    ["react_angry", "react_fist"],
    "confused_verbal": ["react_confused", "react_scratch_head"],
    "threat":          ["react_angry"],
    "impressed":       ["react_happy", "react_clap"],
    "disapproving":    ["react_shake_head", "react_disgust"],

    # ── Sneaking (systems/stealth.py) ──
    "sneak_noise":     ["react_startled"],

    # ── Psychosis / hallucination (systems/psychosis.py) ──
    "hallucinating":   ["react_shocked", "react_fear", "react_look_around"],
}


# =========================================================
# PRIORITY TABLE
# Higher number = interrupts lower-priority reactions in queue.
# 3 = always plays (fear, startled)
# 2 = social/emotional
# 1 = subtle / ambient
# =========================================================

REACTION_PRIORITIES = {
    "startled":    3,
    "fear":        3,
    "shocked":     2,
    "disgust":     2,
    "angry_react": 2,
    "laugh":       2,
    "happy_react": 2,
    "surprise":    2,
    "nod":         1,
    "shake_head":  1,
    "confused":    1,
    "interested":  1,
    "shrug":       1,
    "look_around": 1,

    "dodge":       3,
    "block":       3,

    "cough":       1,
    "sweating":    1,
    "breathless":  2,
    "dizzy":       2,
    "vomit":       2,

    "wince":       1,
    "cry_out":     2,

    "saw_nudity":       3,
    "walked_in_on_sex": 3,
    "heard_sex_sounds": 2,
    "look_away":        2,
    "embarrassed":      2,
    "aroused_react":    1,

    "blush":           1,
    "blush_heavy":     2,
    "flustered":       2,

    "horrified_scream":   3,
    "embarrassed_scream": 3,
    "cover_up_gasp":      2,
    "cover_up":           2,

    "sneeze":       1,
    "gas_release":  1,
    "moan_pain":    1,
    "moan_pleasure": 1,

    "stagger":      2,
    "fall_down":    3,
    "avoid_hit":    2,

    "scared_verbal":   2,
    "angry_verbal":    2,
    "confused_verbal": 1,
    "threat":          3,
    "impressed":       1,
    "disapproving":    1,

    "sneak_noise":     2,

    "hallucinating":   3,
}


# =========================================================
# INVOLUNTARY SOUNDS
# reaction_type -> (utterance pool, loudness 1-3). loudness>=2 can
# alert someone in an ADJACENT room within the same building -- the
# same "sound bleeds through walls" model systems/nudity_perception.py
# already established for sex sounds, generalized here so any loud
# reaction can carry the same way.
# =========================================================

REACTION_SOUNDS = {
    "cry_out":       (["Ah!", "Ow!", "Argh!"], 2),
    "moan_pain":     (["Ngh...", "Mmh...", "Ohh..."], 1),
    "moan_pleasure": (["Mm...", "Oh...", "Ahh..."], 2),
    "cough":         (["*cough*", "*cough cough*"], 1),
    "sneeze":        (["*achoo!*"], 2),
    "gas_release":   (["*fart*"], 1),
    "startled":      (["Whoa!", "Ah!"], 2),
    "fear":          (["!"], 1),
    "fall_down":     (["Oof!", "Ah!"], 2),
    "threat":        (["Back off!", "Don't push me."], 2),
    "sneak_noise":   (["*creak*", "*bump*", "*rustle*", "*clink*"], 2),
}

# reaction_type -> generic stress nudge, applied alongside the animation
# by trigger_reaction() below -- NOT a replacement for whatever
# domain-specific system already applies its own effects (pain/fear/
# grievances/etc from health.py, impulse.py, grievances.py, ...); this
# is just the small "how does reacting itself feel" bump shared across
# every trigger site so callers don't each reinvent it.
REACTION_MOOD_EFFECTS = {
    "fear":           {"stress": 6},
    "startled":       {"stress": 4},
    "angry_react":    {"stress": 5},
    "cry_out":        {"stress": 4},
    "moan_pain":       {"stress": 2},
    "embarrassed":    {"stress": 3},
    "scared_verbal":  {"stress": 5},
    "angry_verbal":   {"stress": 4},
    "fall_down":      {"stress": 6},
    "stagger":        {"stress": 3},

    # Sports game outcomes (systems/sports.py) -- reuses the existing
    # generic impressed/disapproving pair rather than inventing a
    # win/loss-specific reaction type.
    "impressed":      {"stress": -3},
    "disapproving":   {"stress": 3},

    "hallucinating":  {"stress": 8},
}


# =========================================================
# TRIGGER REACTION (unified entry point)
# animation (push_reaction, unchanged) + an optional generic mood nudge
# + an optional involuntary sound. Every existing push_reaction() call
# site is untouched -- this is an additive, richer entry point new
# trigger sites should prefer when the reaction plausibly makes noise
# or carries an emotional weight of its own.
# =========================================================

def trigger_reaction(c, world, reaction_type, tick=None, sound=True, mood=True):
    tick = tick if tick is not None else world.get("tick", 0)
    push_reaction(c, reaction_type, tick)

    if mood:
        for stat, amount in REACTION_MOOD_EFFECTS.get(reaction_type, {}).items():
            c[stat] = max(0.0, min(100.0, c.get(stat, 0.0) + amount))

    if sound and reaction_type in REACTION_SOUNDS:
        utterances, loudness = REACTION_SOUNDS[reaction_type]
        _make_involuntary_sound(c, world, random.choice(utterances), loudness)


def _make_involuntary_sound(c, world, utterance, loudness):
    try:
        from systems.incidental_speech import fire_incidental
        fire_incidental(c, "exclaim", utterance, world)
    except Exception:
        pass
    if loudness >= 2:
        _alert_nearby(c, world, loudness)


def _alert_nearby(c, world, loudness):
    """Same-room characters already perceive the speech bubble itself --
    this is specifically the "heard through the wall" case, mirroring
    nudity_perception.py's SOUND_BLEEDS_BUILDING model."""
    building_id = c.get("building_id")
    if not building_id:
        return
    tick = world.get("tick", 0)
    for other in world.get("characters", {}).values():
        if other.get("id") == c.get("id"):
            continue
        if other.get("building_id") != building_id:
            continue
        if other.get("room_id") == c.get("room_id"):
            continue  # same room -- hears it directly already
        last = other.get("_last_involuntary_sound_react", 0)
        if tick - last < 300:
            continue
        other["_last_involuntary_sound_react"] = tick
        push_reaction(other, "look_around", tick)
        try:
            from core.event_bus import emit
            emit("heard_sound", {"listener_id": other["id"], "source_id": c["id"], "tick": tick})
        except Exception:
            pass


# =========================================================
# SPEECH ACT → LISTENER REACTION
# What the *listener* physically reacts with when they hear
# a particular speech act from the speaker.
# =========================================================

SPEECH_ACT_REACTIONS = {
    "joke":          "laugh",
    "insult":        "angry_react",
    "challenge":     "shake_head",
    "dismissive":    "shake_head",
    "flirt":         "happy_react",
    "compliment":    "nod",
    "supportive":    "nod",
    "apology":       "nod",
    "comfort":       "nod",
    "confession":    "interested",
    "vulnerable":    "interested",
    "gossip":        "interested",
    "brag":          "shrug",
    "awkward_silence": "look_around",
    "urgent_report": "fear",
    "defensive":     "confused",
}


# =========================================================
# COOLDOWNS (ticks)
# Prevents the same reaction firing every turn.
# =========================================================

_DEFAULT_COOLDOWN = 120   # ~4 seconds at 30 ticks/sec

REACTION_COOLDOWNS = {
    "nod":         60,    # can nod fairly often
    "laugh":       180,   # don't laugh every joke
    "look_around": 240,
}


# =========================================================
# PUSH REACTION
# Adds a reaction to the character's queue, respecting
# per-type cooldowns and deduplication.
# =========================================================

def push_reaction(c, reaction_type, tick, priority=None):
    """Queue a reaction on a character, respecting cooldowns.

    Args:
        c:             character dict
        reaction_type: key from REACTION_ANIMATIONS
        tick:          current world tick (for cooldown tracking)
        priority:      override priority (default from REACTION_PRIORITIES)
    """
    if reaction_type not in REACTION_ANIMATIONS:
        return

    # Cooldown check
    cooldowns = c.setdefault("reaction_cooldowns", {})
    last_tick  = cooldowns.get(reaction_type, -9999)
    cooldown   = REACTION_COOLDOWNS.get(reaction_type, _DEFAULT_COOLDOWN)
    if tick - last_tick < cooldown:
        return

    # Deduplicate — don't queue the same type twice
    queue = c.setdefault("reaction_queue", [])
    if any(r["type"] == reaction_type for r in queue):
        return

    p = priority if priority is not None else REACTION_PRIORITIES.get(reaction_type, 1)
    queue.append({"type": reaction_type, "priority": p})


# =========================================================
# PROCESS QUEUE
# Called once per character per tick. Pops the highest-priority
# pending reaction and writes it to c["animation_reaction"]
# so the frontend can read and play it.
# =========================================================

def process_reaction_queue(c, tick):
    """Pop highest-priority reaction and expose it for the frontend."""
    queue = c.get("reaction_queue")
    if not queue:
        return

    # Sort descending by priority, take the best. .get() with a default --
    # intimacy.py::handle_ignored_rejection pushes an "expel_visitor" entry
    # onto this same queue with no "priority" key, which would otherwise
    # raise KeyError the moment it's present when this runs.
    queue.sort(key=lambda r: r.get("priority", 1), reverse=True)
    reaction = queue.pop(0)
    c["reaction_queue"] = queue

    c["animation_reaction"] = {
        "type": reaction["type"],
        "tick": tick,
    }

    # Record cooldown
    cooldowns = c.setdefault("reaction_cooldowns", {})
    cooldowns[reaction["type"]] = tick


# =========================================================
# PUSH CONVERSATION REACTION
# Convenience: given the speech_act the speaker just used,
# push the appropriate reaction on the listener.
# =========================================================

def push_conversation_reaction(listener, speech_act, tick):
    """Push a reaction on the listener based on what speech act they just heard."""
    reaction_type = SPEECH_ACT_REACTIONS.get(speech_act)
    if reaction_type:
        push_reaction(listener, reaction_type, tick)
