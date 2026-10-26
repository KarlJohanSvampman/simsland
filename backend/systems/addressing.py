"""
systems/addressing.py -- who a spoken line is really for.

A line is routed to a listener (the nearest person, or the one the action named), but what was said may plainly be meant
for somebody else: "Daddy, can we play?" said near a sibling, "Hey Anna, can we get some warm clothes?" said to a
housemate. If the listener does not answer such a line they have not ignored anyone, and nothing should be written on the
relationship ledger against them (systems/relationship_ledger.py::_on_conversation_ignored).

addressed_elsewhere() looks at the opening words of the line for a vocative:
  - a kin term (mom, daddy, grandma, uncle, ...) is for the listener only if the listener is that kin to the speaker;
  - a first name is for the listener if it is theirs, and for somebody else if it is another character's.
The first match wins; a line with no vocative is taken to be for the listener.
"""

import re

FILLERS = {"hey", "hi", "hello", "hiya", "oh", "um", "uh", "excuse", "me", "please", "ok", "okay", "well", "so", "yo", "psst",
           "good", "morning", "evening", "night", "afternoon", "dear", "sorry", "pardon", "quick", "question"}
OPENING_WORDS = 5

# term -> the kinship label, in the SPEAKER's own relationship entry, that makes the listener that kin
KIN_TERMS = {
    "mom": "child", "mommy": "child", "mum": "child", "mummy": "child", "mama": "child", "mother": "child", "ma": "child",
    "dad": "child", "daddy": "child", "papa": "child", "father": "child", "pa": "child", "pops": "child",
    "grandma": "grandchild", "grandpa": "grandchild", "granny": "grandchild", "grandad": "grandchild", "nana": "grandchild",
    "grandmother": "grandchild", "grandfather": "grandchild",
    "aunt": "niece_nephew", "auntie": "niece_nephew", "uncle": "niece_nephew",
}
_WORD = re.compile(r"[A-Za-z]+")


def _first_name(c):
    return ((c or {}).get("name") or "").split(" ")[0].lower()


def addressed_elsewhere(world, speaker_id, listener_id, text):
    chars = world.get("characters", {})
    speaker, listener = chars.get(speaker_id), chars.get(listener_id)
    if not text or not speaker or not listener:
        return False
    listener_name = _first_name(listener)
    others = {_first_name(c) for cid, c in chars.items() if cid not in (speaker_id, listener_id) and _first_name(c)}
    others.discard(listener_name)
    kin = ((speaker.get("relationships") or {}).get(listener_id) or {}).get("kinship")
    words = [w.lower() for w in _WORD.findall(text)]
    lead = next((w for w in words[:OPENING_WORDS] if w not in FILLERS), None)      # "Hey, Anna, can we ..." -> anna
    vocatives = [lead] + ([words[-1]] if len(words) > 1 else [])                    # "... , Dad?" -> dad
    for w in vocatives:
        if w == listener_name:
            return False
        if w in KIN_TERMS:
            return kin != KIN_TERMS[w]
        if w in others:
            return True
    return False
