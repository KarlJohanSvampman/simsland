"""
systems/family_address.py -- what a child calls their parents.

Live (2026-11-28): Christopher and Alexander called their mother "Rebecca" and their father "Anthony", and Christopher
chatted with her about a boutique downtown like a friend her own age. The developmental profile (definitions.json,
developmental_profile_registry) says how a child or teen thinks, but nothing told them what they call their parents.

  * parents(c, world): the people a child or teen is the child of -- either one's relationship entry says so, or
    the spouse of such a parent living with them and nothing labelled otherwise.
  * prompt_lines(c, world): "Your mom is Rebecca -- you call her Mom, not Rebecca ..." for a child or teen.
  * fix_vocative(world, c, target_id, text): a line a child says to a parent that still calls them by their first name
    ("Rebecca, can I ...", "..., Anthony?") is said with "Mom" / "Dad" instead. Only the name used to address them, at
    the start or the end of the line -- "I told Anthony" said to Mom stays as it is.
"""

import re

YOUNG = {"child", "teen"}
_CHILD_KIN = {"child": "", "step_child": "step", "adoptive_child": "", "ward": ""}
_TERM = {"female": "Mom", "male": "Dad"}


def _first(c):
    return ((c or {}).get("name") or "").split(" ")[0]


def is_young(c):
    return (c or {}).get("age_group") in YOUNG


_PARENT_KIN = {"parent": "", "step_parent": "step", "adoptive_parent": "", "guardian": ""}


def parents(c, world):
    """[(id, term, kind)] -- term "Mom" / "Dad" (None when their sex isn't known), kind "" / "step".

    A parent: the child's own entry says so (kinship "child" ...), or the parent's entry about the child does
    ("parent" ...) -- live, the Carter boys' entries named only Anthony, and Rebecca's entries about them carried no
    label at all. So also: the spouse of a parent, living with them, with nothing saying otherwise. Not just any adult
    at home -- Pamela lives with her mother and her grandfather."""
    if not is_young(c):
        return []
    chars = world.get("characters") or {}
    cid = c.get("id")
    found = {}
    for oid, other in chars.items():
        if oid == cid:
            continue
        mine = ((c.get("relationships") or {}).get(oid) or {}).get("kinship")
        theirs = ((other.get("relationships") or {}).get(cid) or {}).get("kinship")
        if mine in _CHILD_KIN:
            found[oid] = _CHILD_KIN[mine]
        elif theirs in _PARENT_KIN:
            found[oid] = _PARENT_KIN[theirs]
    for pid in list(found):
        for sid, rel in ((chars.get(pid) or {}).get("relationships") or {}).items():
            spouse = chars.get(sid)
            if (rel or {}).get("kinship") != "spouse" or not spouse or sid in found or sid == cid:
                continue
            mine = ((c.get("relationships") or {}).get(sid) or {}).get("kinship")
            if mine is None and spouse.get("household_id") and spouse.get("household_id") == c.get("household_id"):
                found[sid] = found[pid]
    return [(oid, _TERM.get(chars[oid].get("sex")), kind) for oid, kind in found.items()]


def prompt_lines(c, world):
    chars = world.get("characters") or {}
    lines = []
    for oid, term, kind in parents(c, world):
        other = chars.get(oid) or {}
        name = _first(other)
        if not term or not name:
            continue
        who = {"Mom": "mom", "Dad": "dad"}[term]
        if kind == "step":
            lines.append(f"{name} is your step{who} -- call {name} whatever feels right to you, the way a kid would.")
        else:
            her = "her" if term == "Mom" else "him"
            lines.append(f"{name} is your {who}: you call {her} {term}, never {name}.")
    if lines:
        lines.append("You're their kid: talk to your parents the way a kid your age talks to their mom and dad -- not "
                     "like a friend, a flatmate or a colleague.")
    return lines


def fix_vocative(world, c, target_id, text):
    """The line with a parent's first name, said to that parent as a name to call them by, replaced by Mom / Dad."""
    if not text or not target_id or not is_young(c):
        return text
    hit = next(((term, kind) for oid, term, kind in parents(c, world) if oid == target_id), None)
    if not hit or not hit[0] or hit[1] == "step":
        return text
    term = hit[0]
    name = _first((world.get("characters") or {}).get(target_id))
    if not name:
        return text
    n = re.escape(name)
    # opening: "Rebecca, ...", "Hey Rebecca, ...", "Hi, Rebecca! ..."
    text = re.sub(rf"^(\W*(?:(?:hey|hi|hello|oh|um|so|okay|ok|well|yeah|sorry)[\s,!]+)*){n}\b(?=[\s,!?.:-])",
                  rf"\g<1>{term}", text, count=1, flags=re.I)
    # closing: "..., Rebecca?" / "... Rebecca."
    text = re.sub(rf",\s*{n}(\W*)$", rf", {term}\g<1>", text, count=1)
    return text
