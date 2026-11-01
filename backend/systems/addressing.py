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


# ---------------------------------------------------------------------------------------------------------------------
# addressee(): who a line is for, BEFORE it is said
# ---------------------------------------------------------------------------------------------------------------------
# A line whose listener the model named in a way the action resolver can't place ("Dad") used to fall back to whoever
# stood nearest: live (2026-11-01), Susan Moreau's "Hi, Dad, I'm really sorry..." went to her friend Kathleen and
# started a conversation with her. addressee() works out who the line is for -- from the named listener first, then the
# opening or closing words of the line -- so action_router/process_decision can give it to them, or call it out to them
# if they aren't there, instead of to the nearest stranger to it.

_KIN_SEX = {"mom": "female", "mommy": "female", "mum": "female", "mummy": "female", "mama": "female", "mother": "female",
            "ma": "female", "grandma": "female", "granny": "female", "nana": "female", "grandmother": "female",
            "aunt": "female", "auntie": "female",
            "dad": "male", "daddy": "male", "papa": "male", "father": "male", "pa": "male", "pops": "male",
            "grandpa": "male", "grandad": "male", "grandfather": "male", "uncle": "male"}


def _vocative_words(text):
    words = [w.lower() for w in _WORD.findall(text or "")]
    lead = next((w for w in words[:OPENING_WORDS] if w not in FILLERS), None)
    return [w for w in (lead, words[-1] if len(words) > 1 else None) if w]


def _by_kinship(world, speaker, term):
    """A real kin of that kind (the speaker's relationship entry says so), of the right sex."""
    label, sex = KIN_TERMS.get(term), _KIN_SEX.get(term)
    chars = world.get("characters", {})
    for rid, rel in (speaker.get("relationships") or {}).items():
        other = chars.get(rid)
        if other and (rel or {}).get("kinship") == label and (not sex or other.get("sex") == sex):
            return rid
    return None


def addressee(world, speaker, text=None, description=None):
    """The character id `text` is spoken to, or None when it doesn't say. `description` (the listener as the model
    named it) is tried first, then the line's own vocative ("Dad, ...", "Hey Kathleen!", "..., Daddy?")."""
    from brain.plans import _named_person
    for source in (description, " ".join(_vocative_words(text))):
        if not source:
            continue
        for w in [w.lower() for w in _WORD.findall(source)]:
            if w in KIN_TERMS:
                kin = _by_kinship(world, speaker, w)
                if kin:
                    return kin
        found = _named_person(speaker, world, source)        # names; for a child also "Dad"/"Mom" in their household
        if found:
            return found
    return None
