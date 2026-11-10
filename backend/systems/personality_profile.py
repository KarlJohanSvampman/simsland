"""
systems/personality_profile.py -- the parts of a character's personality a director sets by hand, and the record of how it changes.

    c["traits"]              personality tags (the existing list -- many systems add and remove them)
    c["personality_traits"]  personality tags picked up later (from peers, values, conditioning) -- read together
                             with c["traits"] everywhere
    c["trait_log"]           every change to either list: [{tick, when, list, added, removed, why}], newest last
    c["mood_traits"]         {mood_id: [tags]} -- traits that show only while the character is in that mood
                             (mood ids: definitions["mood_templates"], brain/emotion.py)
    c["speech_quirks"]       [tags] -- how they talk ("says 'like' a lot", "never swears", "trails off")
    c["insecurities"]        [tags] -- what they are insecure about ("their weight", "being smart enough")
    c["confidence_sources"]  [tags] -- what their self-confidence rests on ("their looks", "being a good parent")

All optional. A character template carries the same fields and a new character starts with its template's.

The log: systems that change traits on purpose say why (note_trait_change); anything else that changes the list is
still caught by track(), which compares it with what was last seen, every tick, per character (cheap: two short lists).
"""

LOG_KEPT = 300
TRAIT_LISTS = ("traits", "personality_traits")
TAG_FIELDS = ("speech_quirks", "insecurities", "confidence_sources")


def _when(world):
    cal = (world or {}).get("calendar") or {}
    if not cal:
        return None
    return f"{cal.get('weekday', '')} {cal.get('year', 0):04d}-{cal.get('month', 0):02d}-{cal.get('day', 0):02d} " \
           f"{cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}".strip()


def _clean(tags):
    out = []
    for t in tags or []:
        t = str(t).strip()
        if t and t not in out:
            out.append(t)
    return out


def note_trait_change(c, world, added=(), removed=(), why="", field="traits"):
    """Record a change to c[field] (traits or personality_traits) that has just been made -- call it right after."""
    added, removed = _clean(added), _clean(removed)
    if not added and not removed:
        return
    log = c.setdefault("trait_log", [])
    log.append({"tick": (world or {}).get("tick", 0), "when": _when(world), "list": field, "added": added,
                "removed": removed, "why": why or "changed"})
    del log[:-LOG_KEPT]
    c.setdefault("_traits_seen", {})[field] = list(c.get(field) or [])


def track(c, world):
    """Catch any change to the trait lists made without note_trait_change (called every tick per character)."""
    seen = c.get("_traits_seen")
    if not isinstance(seen, dict):                     # first look at this character: what they start with is no change
        c["_traits_seen"] = {f: list(c.get(f) or []) for f in TRAIT_LISTS}
        return
    for f in TRAIT_LISTS:
        now, was = list(c.get(f) or []), seen.get(f)
        if was is None:
            seen[f] = now
            continue
        if now == was:
            continue
        added = [t for t in now if t not in was]
        removed = [t for t in was if t not in now]
        if added or removed:
            note_trait_change(c, world, added, removed, why="changed (the cause wasn't recorded)", field=f)
        else:
            seen[f] = now                              # only the order changed


def set_traits(c, world, traits, why):
    """Replace c["traits"] and log the difference."""
    old = list(c.get("traits") or [])
    new = _clean(traits)
    c["traits"] = new
    note_trait_change(c, world, [t for t in new if t not in old], [t for t in old if t not in new], why)


def mood_traits_now(c):
    """The traits that show in the character's current mood (none without a mood or a table entry for it)."""
    mood = (c.get("mood") or {}).get("id")
    return _clean((c.get("mood_traits") or {}).get(mood)) if mood else []


def effective_traits(c):
    """Their traits as they are right now: both lists plus those their current mood brings out."""
    out = _clean(list(c.get("traits") or []) + list(c.get("personality_traits") or []))
    for t in mood_traits_now(c):
        if t not in out:
            out.append(t)
    return out


def prompt_lines(c):
    """What the model is told about these (brain/context_builder.py, the identity section)."""
    lines = []
    mt = mood_traits_now(c)
    if mt:
        name = (c.get("mood") or {}).get("name") or (c.get("mood") or {}).get("id")
        lines.append(f"In this {str(name).lower()} mood it shows that you are also: {', '.join(mt)}.")
    q = _clean(c.get("speech_quirks"))
    if q:
        lines.append(f"Quirks in the way you talk (let them show in what you say): {', '.join(q)}.")
    ins = _clean(c.get("insecurities"))
    if ins:
        lines.append(f"You are insecure about: {', '.join(ins)} -- touch on these and it stings.")
    conf = _clean(c.get("confidence_sources"))
    if conf:
        lines.append(f"Your self-confidence rests on: {', '.join(conf)}.")
    return lines


def apply_template(c, template):
    """A new character from a template starts with its persona fields (character generation)."""
    for f in TAG_FIELDS:
        if template.get(f) and not c.get(f):
            c[f] = _clean(template[f])
    if template.get("mood_traits") and not c.get("mood_traits"):
        c["mood_traits"] = {m: _clean(v) for m, v in template["mood_traits"].items() if _clean(v)}


def read(c, world):
    """Everything the persona editor shows."""
    moods = (world.get("definitions") or {}).get("mood_templates") or {}
    return {
        "id": c.get("id"), "name": c.get("name"),
        "traits": list(c.get("traits") or []),
        "personality_traits": list(c.get("personality_traits") or []),
        **{f: _clean(c.get(f)) for f in TAG_FIELDS},
        "mood_traits": {m: _clean(v) for m, v in (c.get("mood_traits") or {}).items()},
        "current_mood": (c.get("mood") or {}).get("id"),
        "moods": [{"id": m, "name": t.get("name", m), "polarity": t.get("polarity"), "description": t.get("description")}
                  for m, t in moods.items()],
        "trait_log": list(c.get("trait_log") or []),
    }


def update(c, world, payload, why="set by hand"):
    """Apply an edit from the persona editor. Only the fields present in `payload` change."""
    if "traits" in payload:
        set_traits(c, world, payload["traits"], why)
    for f in TAG_FIELDS:
        if f in payload:
            c[f] = _clean(payload[f])
    if "mood_traits" in payload:
        c["mood_traits"] = {str(m): _clean(v) for m, v in (payload["mood_traits"] or {}).items() if _clean(v)}
    return read(c, world)
