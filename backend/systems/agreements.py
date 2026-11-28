"""
systems/agreements.py -- what people agreed to actually gets done (or noticed when it isn't), and each character keeps a
list of their agreements.

Live (2026-11-28): two characters negotiated a cleaning schedule, each found a compromise -- and nothing changed. The
agreement was recorded (social/contracts.py: 26 of them, "Household Chores Schedule: Daniel cleans the kitchen, Pamela
the living room", ...) but every term was check_type "manual": nothing turned it into something to do, nothing noticed it
being kept or broken, and the characters only heard about it in a conversation with that same person.

So every term of an agreement in force becomes one of:

    task    a chore or errand ("clean the kitchen", "do the dishes every day", "take out the trash") -> a real
            expectation for the person responsible (systems/expectations.py::synthesize_expectation -- on their to-do
            list, pressing as the day runs out; the id starts with the activity, so the things that help with it come to
            mind -- brain/intention_needs.py). Doing a matching activity keeps it (social/contracts.py::kept); a period
            that passes without it is a violation (the other side is told, a grievance as usual).
    once    a one-off ("make a cleaning schedule", "talk about it with the kids") -> on the to-do list until done; kept
            the next time they talk with the other party about it, or after doing a matching activity.
    rule    a way to behave ("knock before coming in", "let each other know", "no shouting") -> a standing reminder.

    c["agreements"] = [{"contract_id", "term_id", "title", "with": [ids], "mine": bool, "obligation", "kind",
                        "cadence", "activities", "expectation_id", "status", "kept", "missed", "last_kept_tick",
                        "since_tick"}]

in sync with the contracts in force (sweep: every SWEEP_EVERY sim seconds, and at once when one is made). Their own
prompt lists what they agreed to and what others agreed to do for them (section "agreements"); the inspector shows the
list.
"""

import re

from core import scheduler as _scheduler
from core.event_bus import subscribe as _subscribe

OWNER = "agreements"
SWEEP_EVERY = 600

# words in an obligation -> the activities that keep it (first match wins)
TASKS = [
    (r"\bdish(es)?\b|wash(ing)? up|dishwasher", ["wash_dishes", "load_dishwasher"]),
    (r"\bclean(ing)? up|\btid(y|ying) up|clean up after", ["dust_and_wipe", "clean", "wash_dishes", "vacuum"]),   # before "dinner"
    (r"\blaundry|wash(ing)? (the )?clothes|\bironing\b", ["do_laundry_fill", "do_laundry", "dry_laundry"]),
    (r"\btrash|garbage|rubbish|\bbins?\b|recycl", ["take_out_trash", "dispose_trash"]),
    (r"\bcook|dinner|\bmeals?\b|breakfast|lunch", ["cook_recipe", "cook", "prepare_food"]),
    (r"\bvacuum|hoover", ["vacuum"]),
    (r"\bplants?\b|\bgarden|\bweed|\byard|\blawn|outdoor", ["water_plants", "weed_plants"]),
    (r"\bhomework|study|studying", ["do_homework", "study"]),
    (r"\bshopping|groceries|grocery", ["buy_groceries", "go_shopping", "computer_order_item"]),
    (r"\bclean|tidy|tidying|\bmess\b|dust|wipe|kitchen|living room|bathroom|bedroom|\bspaces?\b|\brooms?\b|chores?",
     ["dust_and_wipe", "clean", "vacuum", "wash_dishes"]),
]
RULE = re.compile(r"\b(knock|ask (first|before)|call (first|before)|let (each other|me|them|him|her|us) know|tell "
                  r"(each other|me|them|an? \w+ \w*)|before leaving|announce|respect|boundar|don'?t|do not|never|stop|"
                  r"no more|quiet|keep (it )?down|be (more )?(nice|kind|polite|on time|understanding|patient|supportive|"
                  r"calm|honest|careful)|stay (focused|calm|on)|try (to|not)|patient|apologi[sz]e|listen|honest)\b", re.I)
ONCE = re.compile(r"\b(make|create|draw up|write|set up|come up with|figure out|agree on|plan|talk (to|with|about)|"
                  r"discuss|sit down)\b.*\b(schedule|plan|list|rota|routine|rules|system|chart|it|this|that)\b|"
                  r"\b(make|create) a (schedule|plan|list)\b", re.I)
DAILY = re.compile(r"\b(every ?day|daily|each day|every (morning|evening|night|day)|each (morning|evening|night)|"
                   r"after (dinner|meals|every meal)|after (themselves|ourselves|yourself|myself|himself|herself|self)|"
                   r"same time every|before bed|bedtime|at night)\b", re.I)
WEEKLY = re.compile(r"\b(every week|weekly|each week|weekends?|every (saturday|sunday|monday|tuesday|wednesday|"
                    r"thursday|friday)|(on )?(saturday|sunday|monday|tuesday|wednesday|thursday|friday)s|once a week|"
                    r"alternat\w*)\b", re.I)


# ── when: an agreement with a time in it goes on the schedule, as an expectation with that window ─────────────────────
# (the user, 2026-11-28: "anything that has been agreed upon that has a time component should be added to schedule ...
# as an expectation"). The window is when it's due; past its end without it, it's missed (systems/expectations.py).

_DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
_DAY_RE = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
# a time of day in words -> (start, end) -- first match wins, the more specific first
_PARTS = [
    (r"\bafter (dinner|supper|every meal|meals)\b", ("18:30", "20:30"), "after dinner"),
    (r"\bbefore (dinner|supper)\b", ("16:00", "18:00"), "before dinner"),
    (r"\bafter lunch\b", ("13:00", "14:30"), "after lunch"),
    (r"\bafter breakfast\b", ("08:00", "09:30"), "after breakfast"),
    (r"\bafter school\b", ("15:00", "17:00"), "after school"),
    (r"\bafter work\b", ("17:30", "19:30"), "after work"),
    (r"\b(before bed|bedtime|before (going to )?sleep)\b", ("20:00", "22:00"), "before bed"),
    (r"\b(every|each|in the|this|tomorrow) morning|\bmornings\b", ("07:00", "10:00"), "in the morning"),
    (r"\b(at )?(noon|midday|lunchtime)\b", ("11:30", "13:00"), "around noon"),
    (r"\b(every|each|in the|this|tomorrow) afternoon|\bafternoons\b", ("13:00", "17:00"), "in the afternoon"),
    (r"\b(every|each|in the|this|tomorrow) evening|\bevenings\b|\btonight\b", ("18:00", "21:00"), "in the evening"),
    (r"\b(at|every|each) night\b", ("20:00", "23:00"), "at night"),
]
_CLOCK = re.compile(r"\b(at|by|before|around|from)\s+(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|o'?clock)?"
                    r"(?:\s*(?:-|to|until|till)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?)?", re.I)


def _hhmm(h, m=0):
    return f"{int(h) % 24:02d}:{int(m):02d}"


def _to24(h, m, ampm, hint_pm):
    h, m = int(h), int(m or 0)
    ap = (ampm or "").lower().replace(".", "")
    if ap.startswith("p") and h < 12:
        h += 12
    elif ap.startswith("a") and h == 12:
        h = 0
    elif not ap and hint_pm and 1 <= h <= 7:     # "at 7" for a chore means the evening
        h += 12
    return h, m


def parse_time(obligation, term=None):
    """{"start", "end", "weekdays", "label"} when the agreement says when (a clock time, a part of the day, a day of the
    week -- in the words or the term's own deadline / frequency), else None."""
    text = " ".join(str(x or "") for x in (obligation, (term or {}).get("deadline"), (term or {}).get("frequency")))
    low = text.lower()
    weekdays, day_label = None, None
    if re.search(r"\bweekends?\b", low):
        weekdays, day_label = [5, 6], "weekends"
    elif re.search(r"\bweekdays\b|\bschool (days|nights)\b", low):
        weekdays, day_label = [0, 1, 2, 3, 4], "weekdays"
    else:
        found = re.findall(_DAY_RE + r"(s?)", low)
        if found:
            weekdays = sorted({_DAYS[d] for d, _ in found})
            day_label = " and ".join(d.capitalize() + pl for d, pl in dict.fromkeys(found))
    start = end = part_label = None
    m = _CLOCK.search(text)
    if m and (m.group(4) or m.group(5) or m.group(1).lower() in ("at", "by", "around")) \
            and not re.match(r"\d+\s*(minutes?|hours?|days?|times?|weeks?)", text[m.start(2):], re.I):
        h, mi = _to24(m.group(2), m.group(3), m.group(4), True)
        if h <= 23 and mi <= 59:
            word = m.group(1).lower()
            if m.group(5):
                eh, emi = _to24(m.group(5), m.group(6), m.group(7) or m.group(4), True)
                start, end = _hhmm(h, mi), _hhmm(eh, emi)
            elif word in ("by", "before"):           # a deadline: the couple of hours before it
                start, end = _hhmm(max(0, h - 2), mi), _hhmm(h, mi)
            else:
                start, end = _hhmm(h, mi), _hhmm(min(23, h + 1), mi) if h < 23 else "24:00"
            part_label = f"{word} {_hhmm(h, mi)}"
    if start is None:
        for pat, (a, b), label in _PARTS:
            if re.search(pat, low):
                start, end, part_label = a, b, label
                break
    if start is None and weekdays is None:
        return None
    return {"start": start or "00:00", "end": end or "24:00", "weekdays": weekdays,
            "label": ", ".join(x for x in (day_label, part_label) if x)}


ONCE_LAPSE_TICKS = 2 * 86400     # a one-off not done in two days is let go


def classify(obligation):
    """("task" | "once" | "rule", cadence, [activities]) for a term's words. A task with no activities ("check on
    Christopher before bed", "set aside time each week to talk") is kept by talking with the other party."""
    text = str(obligation or "")
    acts = next((a for pat, a in TASKS if re.search(pat, text, re.I)), [])
    daily, weekly = bool(DAILY.search(text)), bool(WEEKLY.search(text))
    if RULE.search(text) and not acts:
        return "rule", None, []
    if daily or weekly:
        return "task", ("daily" if daily else "weekly"), acts
    if ONCE.search(text):
        return "once", "once", []          # "make a schedule", "talk it over": done by talking it through
    if acts:
        return "task", "daily", acts
    return "once", "once", []


def _cadence_for(kind, cadence, when):
    """A task on more than one day a week (or no day named) is daily; on one or two named days, weekly -- the window
    falls on those days either way."""
    if kind != "task" or not when or not when.get("weekdays"):
        return cadence
    return "weekly" if len(when["weekdays"]) == 1 else "daily"


def _norm(text):
    return re.sub(r"[^a-z ]", "", str(text or "").lower()).strip()


def _expectation_id(term_acts, contract_id, term_id):
    stem = term_acts[0] if term_acts else "agreement"
    return f"{stem}_agreed_{str(contract_id)[-6:]}_{term_id}"


def _names(world, ids):
    chars = world.get("characters") or {}
    return [((chars.get(i) or {}).get("name") or i).split(" ")[0] for i in ids]


def _in_force(world):
    try:
        from social.contracts import IN_FORCE, normalize
    except Exception:                                     # noqa: BLE001
        IN_FORCE, normalize = ("active", "violated", "disputed", "renegotiating", "accepted"), (lambda k: k)
    for k in (world.get("social_contracts") or {}).values():
        if not isinstance(k, dict):
            continue
        normalize(k)
        if (k.get("state") or k.get("status")) in IN_FORCE:
            yield k


def sync(world):
    """Bring every character's agreement list (and the expectations behind their tasks) in line with the contracts in
    force: new terms added, ended ones dropped."""
    chars = world.get("characters") or {}
    want = {}                                             # (char id, contract id, term id) -> entry
    for k in _in_force(world):
        parties = [p for p in k.get("parties") or [] if p in chars]
        for t in k.get("terms") or []:
            who = t.get("responsible_party") or t.get("party")
            if who not in chars:
                continue
            ob = t.get("obligation") or t.get("commitment") or ""
            kind, cadence, acts = classify(ob)
            when = parse_time(ob, t) if kind != "rule" else None
            for p in parties:
                mine = p == who
                # the same promise in two agreements (agreed again later): one entry, the newest agreement
                dup = next((key for key, v in want.items() if key[0] == p and v["responsible"] == who
                            and _norm(v["obligation"]) == _norm(ob) and set(v["with"]) == {o for o in parties if o != p}), None)
                if dup:
                    if (k.get("created_tick") or 0) < (want[dup].get("_created") or 0):
                        continue
                    want.pop(dup)
                want[(p, k["id"], t.get("id"))] = {"_created": k.get("created_tick") or 0,
                    "contract_id": k["id"], "term_id": t.get("id"), "title": k.get("title") or "an agreement",
                    "with": [o for o in parties if o != p], "responsible": who, "mine": mine, "obligation": ob[:120],
                    "kind": kind, "cadence": _cadence_for(kind, cadence, when), "activities": acts, "time": when,
                    "expectation_id": _expectation_id(acts, k["id"], t.get("id")) if mine and kind != "rule" else None,
                }
    from systems.expectations import synthesize_expectation
    for cid, c in chars.items():
        have = {(a["contract_id"], a["term_id"]): a for a in c.get("agreements") or []}
        mine_now = {key[1:]: v for key, v in want.items() if key[0] == cid}
        out = []
        for key, spec in mine_now.items():
            spec = {k2: v for k2, v in spec.items() if k2 != "_created"}
            a = have.get(key)
            if a is None:
                a = dict(spec, status="pending", kept=0, missed=0, last_kept_tick=None, since_tick=world.get("tick", 0),
                         _missed_seen=0)
            else:
                old_eid = a.get("expectation_id")
                a.update({k: v for k, v in spec.items() if k not in ("status",)})
                if old_eid and old_eid != a.get("expectation_id"):          # read differently now: the old task goes
                    (c.get("expectations") or {}).pop(old_eid, None)
                    try:
                        from brain.intentions import remove_intention
                        remove_intention(c, f"expectation:{old_eid}")
                    except Exception:                     # noqa: BLE001
                        pass
            eid = a.get("expectation_id")
            if a.get("kind") == "once" and a.get("status") not in ("done", "lapsed") \
                    and world.get("tick", 0) - (a.get("since_tick") or 0) > ONCE_LAPSE_TICKS:
                a["status"] = "lapsed"                    # a one-off left undone for days: let go
            if a.get("status") == "lapsed" and eid:
                (c.get("expectations") or {}).pop(eid, None)
                try:
                    from brain.intentions import remove_intention
                    remove_intention(c, f"expectation:{eid}")
                except Exception:                         # noqa: BLE001
                    pass
            elif eid and eid not in (c.get("expectations") or {}) and a.get("status") != "done":
                e = synthesize_expectation(c, eid, a["cadence"] or "once", "chores", True,
                                           blame_ids=[], grievance_event_type="contract_violated")
                e["agreement"] = {"contract_id": a["contract_id"], "term_id": a["term_id"]}
            e = (c.get("expectations") or {}).get(eid) if eid else None
            if e is not None:                             # on the schedule at the agreed time (time_window)
                when = a.get("time")
                at = when["label"] if when and when.get("label") and when["label"].lower() not in a["obligation"].lower() else ""
                e["label"] = f"{a['obligation']} ({at + ', ' if at else ''}agreed with {', '.join(_names(world, a['with'])) or 'them'})"
                tw = {k2: when[k2] for k2 in ("start", "end", "weekdays")} if when else None
                if e.get("time_window") != tw or e.get("cadence") != (a["cadence"] or "once"):
                    e["time_window"] = tw
                    e["cadence"] = a["cadence"] or "once"
                    e["current_period_key"] = None        # the window is worked out again on the next update
                    e["window_start_tick"] = e["window_end_tick"] = None
            out.append(a)
        for key, a in have.items():                       # ended / renegotiated away: its expectation goes too
            if key not in mine_now and a.get("expectation_id"):
                (c.get("expectations") or {}).pop(a["expectation_id"], None)
                try:
                    from brain.intentions import remove_intention
                    remove_intention(c, f"expectation:{a['expectation_id']}")
                except Exception:                         # noqa: BLE001
                    pass
        if out or c.get("agreements"):
            c["agreements"] = out


def _contract(world, kid):
    return (world.get("social_contracts") or {}).get(kid)


def _keep(world, c, a, how):
    """c kept term a: the expectation met, the contract told, the record updated."""
    tick = world.get("tick", 0)
    if a.get("expectation_id"):
        try:
            from systems.expectations import satisfy_expectation
            satisfy_expectation(c, a["expectation_id"], world)
        except Exception as exc:                          # noqa: BLE001
            print(f"[agreements] satisfy: {exc!r}")
    k = _contract(world, a["contract_id"])
    if k:
        try:
            from social.contracts import kept
            kept(world, k, c["id"], a["term_id"])
        except Exception as exc:                          # noqa: BLE001
            print(f"[agreements] kept: {exc!r}")
    a["kept"] = a.get("kept", 0) + 1
    a["last_kept_tick"] = tick
    a["_kept_key"] = _period_key(world, a)
    a["status"] = "done" if a.get("kind") == "once" else "kept"
    a["how"] = how
    for o in (world.get("characters") or {}).values():   # the other side's copy of the same term
        for b in o.get("agreements") or []:
            if b is not a and b.get("contract_id") == a["contract_id"] and b.get("term_id") == a["term_id"]:
                b.update(status=a["status"], kept=a["kept"], last_kept_tick=tick, how=how)


def on_activity_finished(data, world):
    c = (world.get("characters") or {}).get((data or {}).get("character_id"))
    t = (data or {}).get("activity_type")
    if not c or not t:
        return
    for a in c.get("agreements") or []:
        if a.get("mine") and a.get("kind") in ("task", "once") and t in (a.get("activities") or []):
            if a.get("kind") == "task" and a.get("_kept_key") == _period_key(world, a):
                continue                                  # already kept this period
            _keep(world, c, a, f"did {t.replace('_', ' ')}")


def on_speech(data, world):
    """A one-off like "make a schedule" / "talk about it" is done once they talk with the other party again."""
    c = (world.get("characters") or {}).get((data or {}).get("character_id"))
    target = (data or {}).get("target_id")
    if not c or not target:
        return
    tick = world.get("tick", 0)
    for a in c.get("agreements") or []:
        if not (a.get("mine") and not a.get("activities") and target in (a.get("with") or [])):
            continue
        if a.get("kind") == "once" and a.get("status") not in ("done", "lapsed") and tick - (a.get("since_tick") or tick) >= 600:
            _keep(world, c, a, "talked it through")
        elif a.get("kind") == "task" and a.get("_kept_key") != _period_key(world, a):
            _keep(world, c, a, "talked with them")


def _period_key(world, a):
    cal = world.get("calendar") or {}
    if a.get("cadence") == "daily":
        return [cal.get("year"), cal.get("month"), cal.get("day")]
    if a.get("cadence") == "weekly":
        return [cal.get("year"), cal.get("week") or (int(cal.get("day") or 0) // 7)]
    return None


def check_missed(world):
    """A task's period that went by without it (systems/expectations.py counts missed_count): the agreement is broken
    -- reported once per miss (social/contracts.py::violation: the other side is told, a grievance as usual)."""
    for c in (world.get("characters") or {}).values():
        for a in c.get("agreements") or []:
            eid = a.get("expectation_id")
            if not (a.get("mine") and eid and a.get("kind") == "task"):
                continue
            e = (c.get("expectations") or {}).get(eid) or {}
            missed = int(e.get("missed_count") or 0)
            if missed > (a.get("_missed_seen") or 0):
                a["_missed_seen"] = missed
                a["missed"] = missed
                a["status"] = "missed"
                k = _contract(world, a["contract_id"])
                if k:
                    try:
                        from social.contracts import violation
                        violation(world, k, c["id"], a["obligation"], evidence=f"didn't {a['obligation']}")
                    except Exception as exc:              # noqa: BLE001
                        print(f"[agreements] violation: {exc!r}")
            elif e.get("status") == "pending" and a.get("status") == "kept" and not _kept_recently(world, a):
                a["status"] = "pending"                   # a new day / week: due again


def _kept_recently(world, a):
    return a.get("last_kept_tick") is not None and world.get("tick", 0) - a["last_kept_tick"] < (
        86400 if a.get("cadence") == "daily" else 7 * 86400)


def sweep(world, entry=None):
    try:
        sync(world)
        check_missed(world)
    except Exception as exc:                              # noqa: BLE001
        print(f"[agreements] sweep: {exc!r}")


def on_contract_created(data, world):
    sweep(world)


# ── what they're told / what the inspector shows ─────────────────────────────────────────────────────────────────────

_STATUS = {"pending": "not done yet", "kept": "done", "done": "done", "missed": "missed last time", "lapsed": "let go"}


def prompt_lines(c, world):
    mine, theirs, rules = [], [], []
    for a in c.get("agreements") or []:
        who = ", ".join(_names(world, a.get("with") or [])) or "them"
        if a.get("status") == "lapsed":
            continue
        if a.get("kind") == "rule":
            rules.append(f"{a['obligation']} (with {who})")
        elif a.get("mine"):
            when = {"daily": " every day", "weekly": " every week"}.get(a.get("cadence"), "")
            if (a.get("time") or {}).get("label") and a["time"]["label"].lower() not in a["obligation"].lower():
                when += f" ({a['time']['label']})"
            mine.append(f"{a['obligation']}{when} -- agreed with {who}; {_STATUS.get(a.get('status'), a.get('status'))}")
        else:
            by = ", ".join(_names(world, [a.get("responsible")]))
            theirs.append(f"{by}: {a['obligation']} ({_STATUS.get(a.get('status'), a.get('status'))})")
    out = []
    if mine:
        out.append("What you agreed to do: " + "; ".join(mine[:4]) + ".")
    if theirs:
        out.append("What others agreed to do: " + "; ".join(theirs[:4]) + ".")
    if rules:
        out.append("What you agreed on: " + "; ".join(rules[:3]) + ".")
    return out


_scheduler.register_recurring(OWNER, sweep, SWEEP_EVERY, offset=300)
_subscribe("activity_finished", on_activity_finished)
_subscribe("speech_spoken", on_speech)
_subscribe("social_contract_created", on_contract_created)
