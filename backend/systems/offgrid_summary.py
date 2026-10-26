"""
systems/offgrid_summary.py -- what a stay off the grid amounted to, written when it ends.

Nothing happens to a character while they are away: no events are raised, no memories written, nobody is arrested. When the
trip is over (systems/offgrid.py::process_return) this builds ONE summary object for it:

    {
      "id", "reason", "label",
      "start_tick", "end_tick", "duration_minutes", "start_clock", "end_clock",
      "description": "<the story of the trip>",
      "key_events": {                       # the course of the stay, in order
          "<what they did>": {"start_tick", "stop_tick", "start", "stop", "note"},
          ...
      },
    }

The key events live on the summary and nowhere else. The same object is carried by the return announcement (the `offgrid_story`
world event, as story["summary_object"]) and listed on the character (c["offgrid_summaries"]) for the inspector's Off-Grid tab.

Where the key events come from: a work shift gives them from the hourly beats the narrator wrote (grouped into blocks of at
most WORK_BLOCK_HOURS); a school day is the lessons, the lunch break and the afternoon; any other trip is divided up by a
short template for its reason (a workout is a warm-up, the workout and a cool-down). Every event lies within the trip.
"""

import uuid

from systems.text_clean import clean_utterance

WORK_BLOCK_HOURS = 3
SUMMARIES_KEPT = 60
DAY = 86400
MIN_SEGMENT_MINUTES = 5

LABELS = {
    "work": "Work", "school": "School", "gym": "Gym", "cafe": "Cafe", "shopping": "Shopping", "leisure": "Leisure outing",
    "doctor": "Doctor's visit", "hospital": "Hospital", "pharmacy": "Pharmacy", "temporary_separation": "Staying away from home",
}

# (title, share of the trip, note) per reason; used for trips with no richer source
TEMPLATES = {
    "gym":      [("Warm-up", 0.15, "Got changed and warmed up."), ("Workout", 0.60, "The main session."), ("Cool-down and shower", 0.25, "Stretched, showered and got dressed.")],
    "cafe":     [("Ordering", 0.12, "Queued and ordered."), ("Sitting with a drink", 0.76, "Took a table and stayed a while."), ("Heading out", 0.12, "Finished up and left.")],
    "shopping": [("Browsing the shops", 0.55, "Wandered through the shops."), ("Picking things out", 0.30, "Decided what to get."), ("Checkout", 0.15, "Paid and packed up.")],
    "leisure":  [("Getting there", 0.15, "Made their way over."), ("Out and about", 0.70, "Spent the time out."), ("Heading home", 0.15, "Wound down and left.")],
    "doctor":   [("Waiting room", 0.45, "Waited to be seen."), ("Consultation", 0.45, "Saw the doctor."), ("Pharmacy and paperwork", 0.10, "Sorted the paperwork.")],
    "hospital": [("Admission", 0.20, "Checked in."), ("Treatment", 0.60, "Seen and treated."), ("Discharge", 0.20, "Discharged.")],
    "pharmacy": [("Queueing", 0.5, "Waited at the counter."), ("Collecting the prescription", 0.5, "Picked up what was needed.")],
}
GENERIC = [("Getting there", 0.2, "Made their way over."), ("The main part of the trip", 0.6, "Took care of what they went for."), ("Heading back", 0.2, "Set off home.")]


def _clock(world, tick, end_tick):
    """'Mon 08:48' for a tick, from the calendar at the end of the trip."""
    cal = world.get("calendar") or {}
    end_minutes = cal.get("hour", 0) * 60 + cal.get("minute", 0)
    days_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    names = [d[:3].lower() for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")]
    today = str(cal.get("weekday", ""))[:3].lower()
    idx = names.index(today) if today in names else 0
    back_minutes = (end_tick - tick) / 60.0
    total = end_minutes - back_minutes
    day_shift = int(total // 1440)
    minute_of_day = int(total - day_shift * 1440)
    return f"{days_names[(idx + day_shift) % 7]} {minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _event(world, start, stop, end_tick, note):
    return {"start_tick": int(start), "stop_tick": int(stop), "start": _clock(world, start, end_tick)[4:],
            "stop": _clock(world, stop, end_tick)[4:], "note": note}


def _add(events, title, ev):
    key, n = title, 2
    while key in events:
        key = f"{title} ({n})"
        n += 1
    events[key] = ev


def _from_template(world, template, start, end, end_tick, events):
    span = end - start
    cursor = start
    kept = [t for t in template if span * t[1] / 60.0 >= MIN_SEGMENT_MINUTES] or template[1:2] or template[:1]
    total = sum(t[1] for t in kept) or 1.0
    for i, (title, share, note) in enumerate(kept):
        stop = end if i == len(kept) - 1 else cursor + span * share / total
        _add(events, title, _event(world, cursor, stop, end_tick, note))
        cursor = stop


def _school_events(world, c, start, end, end_tick, events):
    """Lessons, a lunch break, lessons -- laid over the real span of the school day."""
    span_h = (end - start) / 3600.0
    if span_h < 4:                                       # a preschool morning or a late arrival
        _from_template(world, [("Lessons", 0.55, "Class time."), ("Play and snack break", 0.2, "Break time outside."), ("More lessons", 0.25, "Back to class.")],
                       start, end, end_tick, events)
        return
    school = ((world.get("definitions") or {}).get("school_templates") or {}).get(c.get("current_school") or "") or {}
    where = school.get("name", "school")
    parts = [("Morning lessons", 0.40, f"Classes at {where}."), ("Lunch break", 0.12, "Ate with the others and had a break."),
             ("Afternoon lessons", 0.40, "More classes."), ("End of day", 0.08, "Packed up and left.")]
    _from_template(world, parts, start, end, end_tick, events)


def _work_events(world, c, start, end, end_tick, beats, events):
    job = (c.get("job") or {}).get("title", "work")
    hours = max(1, round((end - start) / 3600.0))
    block_h = WORK_BLOCK_HOURS
    n_blocks = max(1, -(-hours // block_h))
    span = end - start
    beats = list(beats or [])
    for b in range(n_blocks):
        b_start = start + span * b / n_blocks
        b_stop = start + span * (b + 1) / n_blocks
        chunk = beats[b * block_h:(b + 1) * block_h]
        notable = next((x for x in chunk if x.get("notable")), None) or (chunk[0] if chunk else None)
        text = " ".join((x.get("text") or "").strip() for x in chunk).strip()
        mention = next((n for x in chunk for n in (x.get("mentions_names") or [])), None)
        if notable and notable.get("text"):
            title = clean_utterance(notable["text"]).split(".")[0][:52].strip() or f"Working as a {job}"
        elif mention:
            title = f"Working with {mention}"
        else:
            title = f"Working as a {job.lower()}" if b == 0 else "Carrying on with the work"
        _add(events, title, _event(world, b_start, b_stop, end_tick, text[:240] or f"Worked as a {job.lower()}."))


def build_summary(c, world, reason, description, departed_tick, end_tick, beats=None):
    """The summary object for a trip that ran from `departed_tick` to `end_tick` (see the module docstring)."""
    start = departed_tick if departed_tick is not None else end_tick
    end = max(end_tick, start + 60)
    events = {}
    if reason == "work":
        _work_events(world, c, start, end, end_tick, beats, events)
    elif reason == "school":
        _school_events(world, c, start, end, end_tick, events)
    elif (end - start) > 16 * 3600:                    # a stay of days: one entry per day
        days = int(-(-(end - start) // DAY))
        for d in range(days):
            d_start, d_stop = start + d * DAY, min(end, start + (d + 1) * DAY)
            _add(events, f"Day {d + 1}", _event(world, d_start, d_stop, end_tick, "Away from home." if d else "Settled in away from home."))
    else:
        _from_template(world, TEMPLATES.get(reason, GENERIC), start, end, end_tick, events)
    return {
        "id": f"ogs_{uuid.uuid4().hex[:8]}", "reason": reason, "label": LABELS.get(reason, reason.replace("_", " ").capitalize()),
        "start_tick": int(start), "end_tick": int(end), "duration_minutes": round((end - start) / 60.0),
        "start_clock": _clock(world, start, end_tick), "end_clock": _clock(world, end_tick, end_tick),
        "description": description, "key_events": events,
    }


def keep(c, summary):
    """List the summary on the character, newest last, capped."""
    log = c.setdefault("offgrid_summaries", [])
    log.append(summary)
    del log[:-SUMMARIES_KEPT]
    return summary
