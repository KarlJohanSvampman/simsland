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
                    r"thursday|friday)|once a week|alternat\w*)\b", re.I)


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
                    "kind": kind, "cadence": cadence, "activities": acts,
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
                e["label"] = f"{a['obligation']} (agreed with {', '.join(_names(world, a['with'])) or 'them'})"
                e["agreement"] = {"contract_id": a["contract_id"], "term_id": a["term_id"]}
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
