"""
core/flow.py -- what sets each background job off. One table; the flow map (tools/flow_map/) is drawn from it and
sim_loop.py installs it, so the map and the code cannot disagree.

Every job is one of three kinds:

  EVENT    something relevant changed: it runs when one of its `on` events is emitted (core/event_bus.py), for the
           character(s) the event is about where it can. `settle` (sim seconds) coalesces a burst -- a person walking
           emits "character.moved" every step; perception needs one look per few seconds, not one per step.
  CLOCK    calendar time: "daily" at a time of day, "hourly" at a minute past the hour (core/scheduler.py
           register_daily / register_hourly -- a timestamp, never a tick count).
  PROCESS  a process that runs continuously because time passes (decay, drain, growth, a fire burning): every
           `every` sim seconds. The interval is the one it has always had, now written in clock units, so the rates
           tuned against it are unchanged.

A job's `run` is the name of a function in sim_loop.py taking (world, entry) -- entry is the timer for CLOCK/PROCESS
jobs and {"event": name, "data": data, "ids": [...]} for EVENT jobs.

Events marked NEW in their comment are emitted for this table (see where in core/flow.py::EMITTED_AT).
"""

from core.clock import SECOND, MINUTE, HOUR, DAY


def EVENT(name, run, on, why, settle=0, also=None):
    return {"name": name, "run": run, "kind": "event", "on": list(on), "settle": settle, "why": why, "also": also}


def CLOCK(name, run, why, daily=None, hourly=None):
    return {"name": name, "run": run, "kind": "clock", "daily": daily, "hourly": hourly, "why": why}


def DUTY(name, run, every, why, active):
    """A job that is continuous only while something is going on (a fire burning, a delivery under way): it runs every
    `every` sim seconds (anchored to multiples of it, as a PROCESS would) for as long as `active(world)` -- a cheap
    world-level check -- is true, and has no timer at all otherwise. Whatever starts its work calls
    wake_duty(world, name); a loaded world arms the active ones, and an hourly safety check arms (and reports) any that
    is active with no timer."""
    return {"name": name, "run": run, "kind": "duty", "every": every, "active": active, "why": why}


def PERCHAR(name, run, every, why, active):
    """A character's own periodic work (step 5a): run(c, world) for each character it concerns, on the old PROCESS's
    timer (same interval, same offset -- same place in the step), but only over its MEMBERS: the characters for whom
    active(c, world) -- a cheap check of the character itself -- is true, or returns a sim time from which it will be
    (a member skipped until then: the job needs no wake of its own). A character's own update (and a deferred
    character's) adds it as a member or drops it (run_perchar); the timer drops anyone no longer active. Nobody else
    is looked at. Replaces a PROCESS that swept every character."""
    return {"name": name, "run": run, "kind": "perchar", "every": every, "active": active, "why": why}


def PROCESS(name, run, every, why, offset=0):
    return {"name": name, "run": run, "kind": "process", "every": every, "offset": offset, "why": why}


# Where the events this table relies on are emitted (for the map; "existing" = was already emitted before this table).
EMITTED_AT = {
    "character.moved":       "NEW: systems/movement.py -- a character stepped onto a new tile",
    "character.room_changed": "NEW: systems/room_assignment.py::refresh_character_room -- into another room or building",
    "character.building_changed": "NEW: systems/room_assignment.py::refresh_character_room -- into or out of a building",
    "character.offgrid":     "NEW: systems/offgrid.py -- went off the map (work, school, a trip)",
    "character.returned":    "NEW: systems/offgrid.py::process_return -- back on the map",
    "character.added":       "NEW: sim_loop.py::_announce_new_characters -- a character appeared (spawn, birth, move-in); a set difference per tick until every creating path says so itself",
    "activity_started":      "existing: systems/activities.py::start_activity",
    "activity_finished":     "existing: systems/activities.py::finish_activity",
    "person_entered_view":   "existing: brain/perception.py::perceive",
    "expression_made":       "existing: systems/expressions.py::express",
    "hostile_action_resolved": "existing: systems/action_router.py (a punch, shove, ...)",
    "speech_spoken":         "existing: systems/action_router.py::apply_speech",
    "perception.updated":    "NEW: sim_loop.py::_job_perception -- a character's view was refreshed",
    "guest.visit_started":   "NEW: systems/guests.py::_start_visit",
    "conversation.message":  "NEW: brain/conversations.py::add_message",
    "conversation.ended":    "NEW: systems/conversation_floor.py::_end",
    "finance.day_settled":   "NEW: sim_loop.py::_job_daily_finance -- the day's bills and income are booked",
    "world.loaded":          "NEW: sim_loop.py::_announce_new_characters -- the first tick after a load",
    "time.hour":             "existing: core/clock.py",
    "time.day":              "existing: core/clock.py",
}


JOBS = [
    # ── seeing and noticing ─────────────────────────────────────────────────────────────────────────────────────────
    EVENT("perception", "_job_perception", ["character.moved", "character.room_changed", "activity_started",
                                            "activity_finished", "character.returned", "speech_spoken",
                                            "expression_made", "hostile_action_resolved", "world.loaded",
                                            "time.hour"],
          "what a character can see changes when someone near them moves, changes room, starts or stops doing "
          "something, comes back, says something or lashes out (a witness must look then), or the light changes "
          "(hourly); the people near the change look again", settle=5 * SECOND),
    EVENT("attention", "_job_attention", ["perception.updated"],
          "attention follows what was just seen"),
    EVENT("introductions", "_job_introductions", ["person_entered_view"],
          "a friend may introduce two strangers when they come into view of each other"),
    EVENT("life_comparison", "_job_life_comparison", ["person_entered_view", "speech_spoken", "guest.visit_started"],
          "envy over how the other one lives comes up when that person is seen, mentioned, or visited -- with what "
          "brought it up recorded; at most once per pair per REMINDER_COOLDOWN (systems/life_comparison.py)"),
    EVENT("incidental_speech", "_job_incidental_speech", ["character.building_changed"],
          "a goodbye/hello when someone leaves or arrives"),
    EVENT("phone_behavior", "_job_phone_behavior", ["character.building_changed", "activity_started"],
          "a phone is set down when someone settles into something and forgotten when they leave the building"),
    EVENT("social_availability", "_job_social_availability", ["activity_started", "character.offgrid"],
          "chatting with someone who has just fallen asleep or left stops then"),
    EVENT("conversation_seating", "_job_conversation_seating", ["conversation.message"],
          "suggesting to sit down happens as a conversation goes on"),
    EVENT("conversation_cleanup", "_job_conversation_cleanup", ["conversation.ended", "time.hour"],
          "a finished conversation is archived when it ends; a quiet one ends on its own idle timer (re-armed by each "
          "line, brain/conversations.py); the hourly pass only catches conversations from saves made before the timer"),
    EVENT("duties", "systems.duties:on_world_loaded", ["world.loaded"],
          "a loaded world: every DUTY that has work is armed, every parcel in transit is timed"),
    CLOCK("duty_safety", "core.flow:check_duties",
          "hourly safety net: a DUTY with work but no timer is armed and reported (a start site is missing wake_duty)",
          hourly=30 * MINUTE),
    EVENT("plants", "systems.plants:_on_world_loaded", ["world.loaded"],
          "each plant on its own timer: the next moisture/weed threshold or growth stage, or every 30 s while it needs "
          "attention (a loaded world arms them all)"),
    EVENT("batteries", "systems.power:sync_all_batteries", ["world.loaded", "character.added"],
          "devices drain and charge on their own clock (a timer at the next moment that matters: off, usable, full)"),
    EVENT("baby_needs", "systems.baby:_on_babies_appear", ["world.loaded", "character.added"],
          "a baby's needs fall on their own clock (a timer at the next crying point); a loaded world or a birth sets it"),
    EVENT("neighbours", "_job_neighbours", ["character.added", "time.day"],
          "a new arrival gets their street"),
    EVENT("bedroom_assignment", "_job_bedroom_assignment", ["character.added", "time.day"],
          "rooms are reassigned when someone joins the household (and as children grow, daily)"),
    EVENT("evictions", "_job_evictions", ["finance.day_settled"],
          "eviction is decided when the day's bills have been booked"),

    # ── the calendar ────────────────────────────────────────────────────────────────────────────────────────────────
    CLOCK("daily_finance", "_job_daily_finance", "bills, wages, data plans and subscriptions: once a day", daily=0),
    CLOCK("value_influence", "_job_value_influence", "today's value influence settles once a day", daily=13),
    CLOCK("socioeconomics", "_job_socioeconomics", "community stats drift, reputation, secrets, envy, trauma: daily",
          daily=19),
    CLOCK("daily_life", "_job_police_feed", "the daily bundle: police feed, crime careers, gang wars, sports fixtures, "
          "diaries, stories fading, birthdays, baby routines, life comparison bookkeeping", daily=21),
    CLOCK("food_aging", "_job_food_aging", "food gets a day older", daily=40),
    CLOCK("body_composition", "_job_body_composition", "weight and fitness move a day's worth", daily=41),
    CLOCK("home_presence", "_job_home_presence", "the hourly 'are they home' sample", hourly=46),

    # ── processes: time passing ────────────────────────────────────────────────────────────────────────────────────
    PROCESS("relationships", "_job_relationships", 15 * SECOND, "time spent near each other builds familiarity"),
    PROCESS("child_care", "_job_child_care", 15 * SECOND, "children's needs and who is looking after them"),
    PROCESS("conflicts", "_job_conflicts", 5 * SECOND, "an argument or fight in progress moves on"),
    DUTY("grapples", "_job_grapples", 5 * SECOND, "a grapple in progress moves on", "systems.duties:grapples_active"),
    DUTY("sports_watching", "_job_reading_2", 5 * SECOND, "games kick off (from each fixture's timer)", "systems.sports:kickoff_pending"),
    CLOCK("agent_hourly_wake", "brain.agent_wake:_hourly",
          "top of the hour: every character's update runs (hour-grained plans, habits, daily checks)", hourly=0),
    *[CLOCK(f"bus_slot_{m:02d}", "systems.transit:_bus_slot",
            "a bus departure is due: the bus joins its active loop (core/active_loops.py) until the trip is over",
            hourly=m * MINUTE) for m in (0, 15, 30, 45)],
        PROCESS("movement_sweep", "systems.movement:safety_sweep", 30 * SECOND,
            "safety net: anyone set walking without start_moving() joins the movement loop (and is reported)"),
    DUTY("scripted_conversations", "_job_reading_3", 5 * SECOND, "scripted scenes play out", "systems.duties:scripted_active"),
    DUTY("household_processes", "_job_cooking_2", 10 * SECOND, "laundry, dishes, cooking stages advance", "systems.duties:household_processes_active"),
    DUTY("deliveries", "_job_deliveries", 10 * SECOND, "messages travel (parcels: a timer at their arrival, systems/duties.py)", "systems.duties:messages_active"),
    PROCESS("service_workers", "_job_service_workers", 10 * SECOND, "service workers do their rounds"),
    PROCESS("store_staffing", "_job_service_workers_2", 10 * SECOND, "shop staffing follows opening hours"),
    DUTY("service_vehicles", "_job_service_workers_3", 10 * SECOND, "service vans drive", "systems.duties:service_vehicles_active"),
    DUTY("rideshare", "_job_service_workers_4", 10 * SECOND, "rideshare cars drive", "systems.duties:rideshare_active"),
    PROCESS("services", "_job_service_workers_5", 10 * SECOND, "booked services progress"),
    DUTY("fires", "_job_fires", 10 * SECOND, "a fire burns", "systems.duties:fires_active"),
    DUTY("intercourse_sessions", "_job_intercourse_sessions", 10 * SECOND, "a scene in progress", "systems.duties:intercourse_active"),
    PROCESS("household_monitoring", "_job_household_monitoring", 20 * SECOND, "who watches the children, babysitting asks"),
    PROCESS("market", "_job_market", 20 * SECOND, "prices, stocks, production and consumption"),
    PERCHAR("social_odor", "systems.social_odor:apply_odor_social_pressure", 20 * SECOND,
            "a smell bothers the people near it", "systems.social_odor:odor_active"),
    PROCESS("domestic_control", "_job_domestic_control", 24 * SECOND, "controlling partners' tactics, quid pro quo, "
            "emotional control (their own medium cadence)"),
    PERCHAR("libido", "systems.libido:libido_for", 24 * SECOND, "libido moves", "systems.libido:libido_active"),
    PROCESS("mentality_compilation", "_job_mentality_compilation", 25 * SECOND, "mentalities compile in the background"),
    PROCESS("influence_exposure", "_job_influence_exposure", 30 * SECOND, "being around opinions wears on you"),
    PERCHAR("psychosis", "systems.psychosis:tick_psychosis", 30 * SECOND, "psychosis episodes (while the mechanic is on)",
            "systems.psychosis:psychosis_possible"),
    PROCESS("traffic", "_job_traffic", 30 * SECOND, "ambient traffic"),
    PROCESS("postal", "_job_postal", 30 * SECOND, "the post goes round"),
    PROCESS("newspapers", "_job_postal_2", 30 * SECOND, "the paper is delivered"),
    PROCESS("business_support", "_job_business_support", 30 * SECOND, "businesses answer their inboxes"),
    PERCHAR("lt_needs", "systems.lt_needs:lt_needs_tick", 30 * SECOND, "long-term needs grow more pressing",
            "systems.lt_needs:lt_needs_active"),
    PROCESS("cleanliness", "_job_cleanliness", 30 * SECOND, "rooms and clothes get dirty"),
    PERCHAR("addictions", "systems.addictions:addictions_for", HOUR, "cravings, hourly",
            "systems.addictions:addictions_active"),
    PROCESS("cookware", "_job_cookware", 30 * SECOND, "dinner planning and who cooks"),
    PROCESS("emergencies", "_job_arrests", 30 * SECOND, "incidents happen, are reported, responders arrive, arrests"),
    PROCESS("weather", "_job_weather", MINUTE, "the weather changes"),
    PROCESS("focus_check", "_job_focus_check", MINUTE, "worry leaves less focus for what they are doing"),
    PROCESS("worry_poll", "_job_worry_poll", MINUTE, "each character's worries are re-read against new evidence about "
            "once an hour, staggered (candidate: feed it memory.stored instead)"),
    PROCESS("grudges", "_job_grudges", MINUTE, "grudges fade or escalate"),
    PERCHAR("exhaustion", "systems.exhaustion:exhaustion_for", MINUTE, "strain builds; offers to take over",
            "systems.exhaustion:exhaustion_active"),
    PROCESS("appliance_degradation", "_job_appliance_degradation", MINUTE, "appliances wear out"),
    PROCESS("job_market", "_job_job_market", MINUTE, "applications and interviews progress"),
    PROCESS("investments", "_job_job_market_2", MINUTE, "investing"),
    PROCESS("crisis", "_job_crisis", MINUTE, "community crises"),
    PROCESS("news", "_job_news", MINUTE, "news is written"),
    PROCESS("social_projects", "_job_social_projects", MINUTE, "projects start and expire; hobby sessions"),
    PROCESS("detective_work", "_job_detective_work", MINUTE, "a detective story moves on"),
    PROCESS("contract_checks", "_job_contract_checks", MINUTE, "contract terms are checked; worries fade"),
    PROCESS("contagion", "_job_contagion", 15 * SECOND, "disease spreads between people who are together (time together)"),
    PERCHAR("claustrophobia", "systems.claustrophobia:claustrophobia_for", 30 * SECOND,
            "panic builds while someone is somewhere too small", "systems.claustrophobia:claustrophobia_active"),
    PROCESS("calendar_events", "_job_calendar_events", MINUTE, "reminders come due at their time; clauses, payouts, "
            "insurance (day-gated inside)"),
    PROCESS("trials", "_job_trials", MINUTE, "court dates, jail releases; prison reporting and check-ins (day-gated)"),
    PROCESS("rumors", "_job_rumors", 5 * MINUTE, "posts are discovered; old talk forgotten"),
    PROCESS("election", "_job_election", 5 * MINUTE, "elections and legislation"),
    PROCESS("faction", "_job_faction", 5 * MINUTE, "faction, public-figure and social influence nudge beliefs"),
    PROCESS("hierarchy", "_job_hierarchy", 5 * MINUTE, "standing in groups"),
    PROCESS("migration", "_job_migration", 5 * MINUTE, "households weigh moving away"),
    PROCESS("persona_expectations", "_job_persona_expectations", 5 * MINUTE, "what close kin expect of each other"),
    PROCESS("kids_play", "_job_kids_play", 10 * MINUTE, "urges to play end; agreed play starts"),

    # ── jobs that live in their own modules ────────────────────────────────────────────────────────────────────────
    CLOCK("feelingsday", "systems.feelings:_daily", "the daily standing snapshot", daily=6 * HOUR),
    CLOCK("post_engagement", "systems.calendar_handlers:_post_engagement", "likes and comments on posts", hourly=0),
    PROCESS("popularity_decay", "systems.calendar_handlers:_popularity_decay", MINUTE, "popularity fades"),
    PROCESS("orphan_props", "systems.calendar_handlers:_orphan_props", 30 * SECOND, "props left nowhere are tidied",
            offset=5),
    DUTY("background_services", "systems.calendar_handlers:_background_services", 5 * SECOND,
         "background-LLM work is submitted and collected while any is waiting (systems/bg_work.py)", "systems.bg_work:active"),
    PROCESS("movelog", "systems.movement_log:_job", 15 * SECOND, "the movement log samples where people are"),
    DUTY("convtags", "systems.conversation_archive:_service", 5 * SECOND, "archived conversations get their AI tags", "systems.duties:convtags_active"),
    PROCESS("riftscan", "systems.rifts:on_timer", HOUR, "standing between housemates is re-read", offset=1234),
]


# ── installing the table ─────────────────────────────────────────────────────────────────────────────────────────

# The keys an event's data names the characters it is about by.
_ID_KEYS = ("character_id", "observer_id", "subject_id", "listener_id", "speaker_id", "speaker", "actor_id", "target_id",
           "guest_id", "id")


def _ids(data):
    out = []
    for k in _ID_KEYS:
        v = (data or {}).get(k)
        if isinstance(v, str) and v not in out:
            out.append(v)
    for v in (data or {}).get("character_ids") or ():
        if v not in out:
            out.append(v)
    return out


def _resolve(module, run):
    if ":" in run:
        import importlib
        mod, fn = run.split(":", 1)
        return getattr(importlib.import_module(mod), fn)
    return getattr(module, run)


def _event_handler(job, fn, event):
    from core import scheduler
    owner = f"flow:{job['name']}"
    settle = int(job.get("settle") or 0)

    def handler(data, world):
        ids = _ids(data)
        if not settle:
            fn(world, {"event": event, "data": data, "ids": ids})
            return
        # One look per `settle` window: the first event opens it, later ones only add who it is about -- a stream of
        # events must not keep pushing the timer back.
        for t in scheduler.pending(world, owner):
            got = t["payload"].setdefault("ids", [])
            got.extend(i for i in ids if i not in got)
            t["payload"].setdefault("events", [])
            if event not in t["payload"]["events"]:
                t["payload"]["events"].append(event)
            return
        scheduler.schedule_in(world, owner, "settle", settle, {"ids": list(ids), "events": [event]})
    handler.__qualname__ = f"flow.{job['name']}<-{event}"
    return handler


_installed = set()


def install(module=None):
    """Wire every job in JOBS: clocks and processes onto the scheduler, events onto the bus. Idempotent per job.
    Without `module` (sim_loop, where the "_job_*" functions live), only the jobs that live in their own modules
    ("module:function") are installed -- for tests and tools that import one of those modules on its own."""
    from core import scheduler
    from core.event_bus import subscribe
    for job in JOBS:
        if job["name"] in _installed or (module is None and ":" not in job["run"]):
            continue
        _installed.add(job["name"])
        fn = _resolve(module, job["run"])
        if job["kind"] == "process":
            scheduler.register_recurring(job["name"], fn, every=job["every"], offset=job.get("offset", 0))
        elif job["kind"] == "perchar":
            _perchar_fns[job["name"]] = (fn, _resolve(module, job["active"]), job["every"])
            scheduler.register_recurring(job["name"], _perchar_timer(job["name"]), every=job["every"])
        elif job["kind"] == "duty":
            _duty_fns[job["name"]] = (fn, _resolve(module, job["active"]))
            scheduler.register(_duty_owner(job["name"]), _duty_timer)
        elif job["kind"] == "clock":
            if job.get("daily") is not None:
                scheduler.register_daily(job["name"], fn, at=job["daily"])
            else:
                scheduler.register_hourly(job["name"], fn, at=job.get("hourly") or 0)
        else:
            if job.get("settle"):
                scheduler.register(f"flow:{job['name']}", (lambda f: lambda world, entry: f(world, {
                    "event": (entry.get("payload") or {}).get("events", [None])[0],
                    "events": (entry.get("payload") or {}).get("events", []),
                    "data": {}, "ids": (entry.get("payload") or {}).get("ids", [])}))(fn))
            for ev in job["on"]:
                subscribe(ev, _event_handler(job, fn, ev))


# ── per-character jobs ───────────────────────────────────────────────────────────────────────────────────────────────
_perchar_fns = {}        # name -> (run fn(c, world), active fn(c, world), every)


def _members(world, name):
    """{character id: sim time from which it is due} -- 0 for now."""
    return world.setdefault("_perchar_members", {}).setdefault(name, {})


def _check(active, c, world):
    """active(c, world) is True (work now), False/None (none), or a sim time (work from then on)."""
    on = active(c, world)
    if on is True:
        return 0
    if on is False or on is None:
        return None
    return float(on)


def run_perchar(c, world):
    """Called in a character's update (and for characters the step defers): for each PERCHAR job, is this character
    one it has work for (now, or from a known moment) -- added to its members, or dropped. The work itself runs on
    the job's timer."""
    if not _perchar_fns:
        return
    cid = c.get("id")
    for name, (_fn, active, _every) in _perchar_fns.items():
        try:
            at = _check(active, c, world)
        except Exception as exc:
            print(f"[flow] per-character check {name} failed for {cid}: {exc!r}")
            at = None
        members = _members(world, name)
        if at is None:
            members.pop(cid, None)
        else:
            members[cid] = at


def _perchar_timer(name):
    def handler(world, entry):
        members = (world.get("_perchar_members") or {}).get(name)
        if not members:
            return
        from core.clock import now_ts
        now = now_ts(world)
        due = [cid for cid, at in members.items() if at <= now]
        if not due:
            return
        fn, active, _every = _perchar_fns[name]
        chars = world.get("characters") or {}
        order = {cid: n for n, cid in enumerate(dict.keys(chars))}
        for cid in sorted(due, key=lambda i: order.get(i, 1 << 30)):
            c = chars.get(cid) if cid in order else None
            try:
                at = None if c is None else _check(active, c, world)
                if at is None:
                    members.pop(cid, None)
                    continue
                if at > now:
                    members[cid] = at
                    continue
                fn(c, world)
                after = _check(active, c, world)          # done for now? then due again only from when it says
                if after is None:
                    members.pop(cid, None)
                else:
                    members[cid] = after
            except Exception as exc:
                print(f"[flow] per-character job {name} failed for {cid}: {exc!r}")
    handler.__qualname__ = f"flow.perchar.{name}"
    return handler


# ── duties ───────────────────────────────────────────────────────────────────────────────────────────────────────────
_duty_fns = {}           # name -> (run fn, active fn)


def _duty_owner(name):
    return f"duty:{name}"


def wake_duty(world, name):
    """Something started that `name` looks after: armed (at the next multiple of its interval) unless it already is."""
    from core import scheduler
    from core.clock import now_ts
    j = job(name)
    if not j or j.get("kind") != "duty" or world is None:
        return
    owner = _duty_owner(name)
    if scheduler.pending(world, owner):
        return
    now, every = now_ts(world), j["every"]
    scheduler.schedule_at(world, owner, "run", now + ((-now) % every or every))


def _duty_timer(world, entry):
    from core import scheduler
    from core.clock import now_ts
    name = entry["owner"].split(":", 1)[1]
    fn, active = _duty_fns.get(name, (None, None))
    if fn is None:
        return
    fn(world, entry)
    if active(world):
        every = job(name)["every"]
        now = now_ts(world)
        scheduler.schedule_at(world, _duty_owner(name), "run", now + ((-now) % every or every))


def check_duties(world, entry=None):
    """A loaded world, and hourly as a safety net: every duty that has work is armed. One found active with no timer
    (whatever started its work did not call wake_duty) is reported -- that start site needs the call."""
    from core import scheduler
    loaded = (entry or {}).get("event") == "world.loaded"
    for name, (fn, active) in _duty_fns.items():
        try:
            busy = active(world)
        except Exception as exc:
            print(f"[flow] duty {name}: active() failed: {exc!r}")
            continue
        if busy and not scheduler.pending(world, _duty_owner(name)):
            if not loaded:
                print(f"[flow] duty {name} had work but no timer -- a start site is missing wake_duty()")
            wake_duty(world, name)


def job(name):
    return next((j for j in JOBS if j["name"] == name), None)
