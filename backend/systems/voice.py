"""
systems/voice.py

How a character talks, rolled once and kept: how much they say, how casual, how direct, how warm, what kind of humour,
and one verbal habit. Goes into every prompt (brain/context_builder.py::_sec_identity) together with the lines they
said lately, which they are told not to reuse.

Why (live, 2026-11-23): across 419 distinct conversation lines "what's going on" came up 66 times, "we need to talk"
and "I think we need to" were everywhere, and most lines opened with the listener's name and "I understand" / "calm
down". Everyone spoke as the same calm counsellor. The prompt gave the model nothing to tell voices apart: traits went
in as raw ids ("cognition_selfaware, power_gatekeeper") and only 15% of characters had a speech_style.

c["voice"] = {"length": i, "register": i, "directness": i, "warmth": i, "humor": i, "habit": "..."}
Rolled lazily the first time a prompt needs it, so a running sim gets voices without a reset. The roll is seeded by
the character id, so it comes out the same if it ever has to be rolled again, and leans on the character's traits.
"""

import random

AXES = {
    "length": [
        "you say a few words at a time and rarely finish a full sentence",
        "short, plain sentences",
        "a sentence or two, no more",
        "you go on -- long sentences, asides, explaining yourself",
    ],
    "register": [
        "casual and loose",
        "plain everyday words",
        "careful, proper wording",
        "lots of slang",
    ],
    "directness": [
        "blunt -- the point comes first",
        "straight, but polite about it",
        "roundabout -- you hint before you get to it",
        "guarded -- you give little away",
    ],
    "warmth": [
        "warm and affectionate",
        "friendly enough",
        "cool and matter-of-fact",
        "prickly, quick to snap",
    ],
    "humor": [
        "serious, little humour",
        "dry humour",
        "goofy",
        "teasing",
    ],
}

BASE_WEIGHTS = {
    "length": [2, 4, 4, 2],
    "register": [4, 4, 2, 1],
    "directness": [3, 4, 2, 2],
    "warmth": [3, 4, 3, 1],
    "humor": [4, 3, 1, 2],
}

# trait -> {axis: option index it pushes toward}
TRAIT_LEAN = {
    "aggressive": {"warmth": 3, "directness": 0},
    "controlling": {"directness": 0},
    "cynical": {"humor": 1, "warmth": 2},
    "cheerful": {"warmth": 0, "humor": 2},
    "tactful": {"directness": 1},
    "polite": {"register": 2, "directness": 1},
    "charismatic": {"length": 3, "humor": 3},
    "dishonest": {"directness": 2},
    "shy": {"length": 0, "directness": 3},
    "introverted": {"length": 1, "directness": 3},
    "extroverted": {"length": 3, "warmth": 0},
    "disciplined": {"length": 1},
    "grumpy": {"warmth": 3, "humor": 1},
    "kind": {"warmth": 0},
    "playful": {"humor": 2},
    "sarcastic": {"humor": 1},
    "anxious": {"directness": 2},
    "confident": {"directness": 0},
    "power_gatekeeper": {"warmth": 2, "directness": 3},
    "cognition_logical": {"register": 2},
}

# speech_style_registry ids that already say how long/direct they are
STYLE_LEAN = {
    "terse_clipped": {"length": 0},
    "verbose_rambler": {"length": 3},
    "folksy_slang": {"register": 3},
    "formal_archaic": {"register": 2},
    "blunt_no_filter": {"directness": 0},
    "overly_polite": {"directness": 2, "warmth": 0},
    "sarcastic_deadpan": {"humor": 1},
}

HABITS = [
    "you start a lot of sentences with \"Look,\" or \"Okay so\"",
    "you answer questions with a question",
    "you hardly ever use people's names",
    "you trail off with \"...\" when unsure",
    "you say \"honestly\" or \"to be fair\" a lot",
    "you change the subject to something you care about",
    "you exaggerate (\"a million times\", \"the worst ever\")",
    "you use pet names (\"hon\", \"buddy\", \"pal\")",
    "you mutter half your thoughts out loud",
    "you make little jokes when things get tense",
    "you complain a bit before agreeing to anything",
    "you get to the practical part fast: who, what, when",
    "you mention food, money or the weather out of nowhere",
    "you repeat the other person's last word back as a question",
    "you swear mildly when annoyed",
    "you bring up something from the past (\"like that time...\")",
]

CHILD_HABITS = [
    "you ask \"why?\" a lot",
    "you mix up words a little",
    "you get excited and talk fast, lots of \"and then\"",
    "you go quiet and give one-word answers when upset",
    "you tell on people (\"Mom, he...\")",
    "you bring up toys, games or snacks out of nowhere",
    "you exaggerate (\"a million times\", \"forever\")",
    "you whine a bit when you don't get your way",
]

# lines nobody should reach for by default
STOCK_PHRASES = ("what's going on", "we need to talk", "I understand", "calm down",
                 "let's take a step back", "I'm here for you", "I appreciate")


def _weighted(rng, weights):
    total = sum(weights)
    r = rng.random() * total
    for i, w in enumerate(weights):
        r -= w
        if r <= 0:
            return i
    return len(weights) - 1


def _is_child(c):
    age = c.get("age")
    return (age is not None and age < 13) or c.get("age_group") in ("baby", "toddler", "child")


def roll(c):
    """A fresh voice for c, seeded by its id and leaning on its traits and speech_style."""
    rng = random.Random(f"voice:{c.get('id') or c.get('name')}")
    leans = {}
    for t in list(c.get("traits") or []) + list(c.get("personality_traits") or []):
        for axis, idx in TRAIT_LEAN.get(t, {}).items():
            leans.setdefault(axis, []).append(idx)
    for axis, idx in STYLE_LEAN.get(c.get("speech_style") or "", {}).items():
        leans.setdefault(axis, []).extend([idx, idx])          # the style is explicit, it counts double
    voice = {}
    for axis, base in BASE_WEIGHTS.items():
        w = list(base)
        for idx in leans.get(axis, []):
            w[idx] += 5
        if _is_child(c) and axis == "register":
            w[2] = 0                                           # no child talks in careful, proper wording
        voice[axis] = _weighted(rng, w)
    voice["habit"] = rng.choice(CHILD_HABITS if _is_child(c) else HABITS)
    return voice


def ensure(c):
    v = c.get("voice")
    if not isinstance(v, dict) or not all(isinstance(v.get(a), int) for a in AXES):
        v = roll(c)
        c["voice"] = v
    return v


def describe(c):
    v = ensure(c)
    parts = []
    for axis, options in AXES.items():
        i = v.get(axis)
        if isinstance(i, int) and 0 <= i < len(options):
            parts.append(options[i])
    line = "How you talk: " + "; ".join(parts) + "."
    if v.get("habit"):
        line += f" A habit of yours: {v['habit']}."
    return line


def recent_lines(c, n=5):
    """The last few distinct things c said, newest last (c["speech_log"], systems/speech_repeat.py)."""
    out = []
    for e in reversed(c.get("speech_log") or []):
        t = (e.get("utterance") or "").strip()
        if t and t.lower() not in (x.lower() for x in out):
            out.append(t if len(t) <= 140 else t[:137] + "...")
        if len(out) >= n:
            break
    return list(reversed(out))


def prompt_lines(c):
    lines = [describe(c)]
    said = recent_lines(c)
    if said:
        lines.append("Things you said lately -- don't reuse these words or openings, say something new in your own way: "
                     + " / ".join(f'"{s}"' for s in said))
    return lines
