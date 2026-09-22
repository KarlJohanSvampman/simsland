# =========================================================
# IMPORTS
# =========================================================

import random

from brain.context_builder import (
    build_context
)

from systems.activities import (
    execute_activity,
    start_activity
)

from brain.intentions import (
    clean_intentions,
    sort_intentions
)
from systems.body import (
    update_body_needs,
    ensure_body,
)

from systems.body_intentions import (
    generate_body_intentions
)
from brain.self_model import (
    consolidate_identity
)

from systems.cooking_process import (
        update_cooking_process
)


from systems.strategy import (
    resolve_strategy
)

from brain.narratives import (

    consolidate_relationship_narratives,

    consolidate_life_narratives
)

from systems.persistent_desires import (
    update_desires
)

from systems.expectations import (
    update_expectations
)

from systems.convenience import (
    update_convenience
)

from brain.llm_brain import (
    think
)

from brain.cognition_scheduler import (
    should_think,
    note_think,
)

from brain.memory import (
    decay_memories,
    store_memory
)

from brain.emotion import (
    update_emotion
)

from systems.habits import (
    decay_habits
)

from systems.activities import (
    execute_activity
)

from systems.scheduling import (
    update_schedule_runtime
)

from systems.travel import (
    update_travel,
    TRAVEL_FROZEN_STATES,
    TRAVEL_WALKING_STATES,
)

from systems.offgrid import (
    maybe_go_offgrid,
    maybe_schedule_doctor_visit,
    resolve_due_appointments,
    process_return
)

from systems.validation import (
    maybe_seek_validation_from_queue,
    check_validation_refresh,
)

from systems.social_intentions import (
    update_social_intentions
)

from systems.jobs import (
    maybe_fire,
    apply_for_job,
    advance_job_application
)

from systems.health import (
    process_health
)

from systems.mail import (
    attempt_pay_bills,
    sort_household_mail,
    respond_to_mail
)

from systems.story import (
    update_story_arc
)

# systems.movement's update_character_movement is no longer called from
# here -- see the two former call sites' comments below (this function's
# activity branch, and the MOVEMENT section further down): it now runs
# once, up front, for every is_moving character directly in
# sim_loop.py's main tick(), before any per-character dispatch.

from systems.action_router import (
    clear_expired_speech
)

from systems.posture import (
    promote_pending_posture
)

from systems.activity_queue import (
    process_activity_queue,
    suspend_activity_queue,
)

from systems.item_knowledge import (
    update_item_knowledge,
)

# =========================================================
# URGENT NEED THRESHOLDS — beyond these, interrupt a hobby
# Only activities flagged "interruptible" can be suspended.
# =========================================================
# body thresholds that trigger interruption (0-100 scale)
_BODY_INTERRUPT_THRESHOLDS = {
    "bladder":  88,
    "hunger":   82,
    "fatigue":  90,
    "hydration": 25,   # below this triggers (inverted: low hydration = urgent)
}

def _check_urgent_interruption(c):
    """Return a reason string if a body need is critical, else None."""
    body = c.get("body", {})
    if body.get("bladder", 0) >= _BODY_INTERRUPT_THRESHOLDS["bladder"]:
        return "urgent_bladder"
    if body.get("bowels", 0) >= 88:
        return "urgent_bowels"
    if body.get("hunger", 0) >= _BODY_INTERRUPT_THRESHOLDS["hunger"]:
        return "urgent_hunger"
    if body.get("fatigue", 0) >= _BODY_INTERRUPT_THRESHOLDS["fatigue"]:
        return "urgent_fatigue"
    if body.get("hydration", 100) <= _BODY_INTERRUPT_THRESHOLDS["hydration"]:
        return "urgent_thirst"
    return None


# =========================================================
# INTERNAL STATE UPDATE
# =========================================================

def update_internal_state(

    c,

    world
):
    # Confirmed live bug (real player report + screenshot): travel_hidden
    # is set/cleared at many separate points scattered across travel.py's
    # different trip-leg transitions (driving_out/driving_back/bus legs/
    # walking home/etc.), each responsible for its own matching reset --
    # any one gap (an interrupted trip, an edge case one specific leg's
    # reset branch didn't cover) leaves it stuck True forever after,
    # which main.js::_isCharacterHidden() reads directly -- the character
    # renders permanently invisible despite being genuinely home and
    # active (confirmed live: off_grid=False, travel_state=None,
    # mid-sleep, yet travel_hidden=True). Rather than chase every
    # individual transition site for the one that missed a reset, this is
    # a general safety-net invariant, checked every tick for every
    # character: not off-grid and not mid-trip means NOT travel_hidden,
    # full stop -- self-heals within one tick regardless of which
    # specific code path caused the staleness.
    if c.get("travel_hidden") and not c.get("off_grid") and not c.get("travel_state"):
        c["travel_hidden"] = False
        from sim_loop import _mark_dirty
        _mark_dirty(world, char_ids={c["id"]})

    ensure_body(c)           # migrate old characters; no-op on new ones
    update_body_needs(c, world=world)
    update_emotion(
        c,
        world
    )
    # Ensure lt_needs distributed (idempotent — no-op if already set)
    from systems.lt_needs import distribute_lt_needs
    distribute_lt_needs(c, world=world)

    clear_expired_speech(c, world)

    promote_pending_posture(c, world)

    decay_memories(c)

    decay_habits(c)

    process_health(
        c,
        world
    )

    from systems.waiting import tick_waiting
    tick_waiting(c, world)

    from systems.curiosity import tick_curiosity
    tick_curiosity(c, world)

    consolidate_relationship_narratives(c)

    consolidate_life_narratives(c)

    consolidate_identity(c)
    generate_body_intentions(c, world)

# =========================================================
# ECONOMY
# =========================================================

def update_economy(

    c,

    world
):

    # maybe_fire()/process_interview() are NOT called here -- sim_loop.py's
    # dedicated job_market cadence block already calls both, once per 60
    # ticks, for every character. This function used to also call them on
    # every single tick (no cadence gate at all), inflating maybe_fire's
    # per-check chance into an effective per-tick chance -- roughly a 60x
    # amplification that produced jobs lasting under a minute and dozens of
    # hire/fire cycles in a character's own memory log. apply_for_job() is
    # correctly per-tick here (it's self-guarding: `if c.get("employed") or
    # c.get("interview"): return`), matching its own docstring's "automatic
    # per-economy-tick path" framing.

    apply_for_job(
        c,
        world
    )

    attempt_pay_bills(
        c,
        world
    )

    # Per the user's explicit ask: a character with real slack in their
    # bank balance should try to pay off debt sooner, not just let it
    # carry along at minimum forever. Self-gated to once per calendar day.
    from systems.loans import maybe_prepay_debt
    maybe_prepay_debt(c, world)

    # Per the user's explicit ask: an elderly character past retirement
    # age stops working (and stops being expected to) instead of working
    # indefinitely. Self-gated on c["retired"], cheap no-op afterward.
    from systems.retirement import maybe_retire, maybe_retire_disabled
    maybe_retire(c, world)
    maybe_retire_disabled(c, world)

    # Per the user's explicit ask: hourly memory consolidation into a
    # separate long-term store, plus periodic random forgetting of the
    # raw short-term log. Both self-gate on their own tick interval.
    from systems.memory_consolidation import maybe_consolidate_memories, maybe_forget_short_term
    maybe_consolidate_memories(c, world)
    maybe_forget_short_term(c, world)


# =========================================================
# OFFGRID
# =========================================================

def update_offgrid(

    c,

    world
):

    process_return(
        c,
        world
    )

    update_travel(
        c,
        world
    )

    maybe_go_offgrid(
        c,
        world
    )

    maybe_schedule_doctor_visit(
        c,
        world
    )

    resolve_due_appointments(
        c,
        world
    )

    maybe_seek_validation_from_queue(
        c,
        world
    )

    check_validation_refresh(
        c,
        world
    )


# =========================================================
# STORE INTENTION
# =========================================================

def store_intention(

    c,

    intention
):

    if not intention:
        return

    # intention comes straight from parsed LLM JSON (see llm_brain.py's
    # decision schema) — clamp priority into the same 0-100 scale every
    # hardcoded intention (body_intentions.py etc.) uses. Without this, a
    # hallucinated numeric token (seen in practice: values in the
    # 10^31 range) makes final_priority() = category_score*1000 + priority
    # dwarf every other intention's score, permanently locking the
    # character onto whatever this intention is and starving all others
    # (sleep, eat, going outside, ...) forever.
    try:
        priority = float(intention.get("priority", 0))
    except (TypeError, ValueError):
        priority = 0

    intention["priority"] = max(0, min(100, priority))

    # Dedup by type (brain/intentions.py::add_intention(), the same
    # mechanism every other intention producer in this codebase already
    # uses) instead of a blind append -- confirmed live bug: a plain
    # append here let every LLM turn's "then" intention pile up as its
    # own permanent slot (nothing about a repeated real type, e.g.
    # "sleep" every tick, ever collapsed into one entry), and the old
    # last-10-by-insertion-order cap could silently evict a genuinely
    # important, still-unresolved intention (drink, an expectation, ...)
    # just because enough LLM turns had happened since it was added.
    from brain.intentions import add_intention, final_priority
    add_intention(c, intention)

    # Defensive cap, independent of the dedup fix above -- keeps the
    # MOST IMPORTANT intentions if the list still grows large from many
    # genuinely distinct sources, rather than the most RECENT ones.
    intentions = c.get("active_intentions", [])
    if len(intentions) > 20:
        intentions.sort(key=lambda i: final_priority(i, c), reverse=True)
        c["active_intentions"] = intentions[:20]


# =========================================================
# PROCESS AI DECISION
# =========================================================

def process_decision(

    c,

    world,

    decision,

    available_actions=None
):

    from systems.action_validator import (
        validate_action
    )

    from systems.action_router import (
        route_action
    )

    # =====================================
    # THOUGHT
    # =====================================

    c["last_thought"] = (
        decision.get(
            "thought"
        )
    )

    # brain/llm_brain.py::_to_legacy_decision() maps the envelope's
    # "narration" straight into decision["thought"] unchanged -- the plan
    # for the Round 7 envelope called for narration to also land in its
    # own c["last_narration"] (for a future narration-feed UI, distinct
    # from last_thought's other historical readers) but that half of the
    # wiring was never actually added. Same source value today; kept as
    # its own field since the two are conceptually separate.
    c["last_narration"] = c["last_thought"]

    # =====================================
    # EMOTION
    # =====================================

    emotion = decision.get(
        "emotion"
    )

    if emotion:

        c["emotion"] = emotion

    # =====================================
    # REFLECTION
    # =====================================

    c["last_reflection"] = (
        decision.get(
            "reflection"
        )
    )

    # =====================================
    # INTENTION
    # =====================================

    intention = decision.get(
        "intention"
    )

    if intention:

        store_intention(
            c,
            intention
        )

    # =====================================
    # MEMORY
    # =====================================

    if decision.get("thought"):

        store_memory(

            c,

            text=decision[
                "thought"
            ],

            tags=[
                "thought"
            ],

            importance=0.3,

            tick=world.get("tick", 0),

            source="internal"
        )

    # =====================================
    # ACTION + SPEECH  (via action router)
    # =====================================

    action = decision.get("action")
    speech = decision.get("speech")

    if action:

        # Resolve action["target_description"] -> action["target"] against
        # the real candidate ids, if the envelope set one and didn't
        # already supply a target — see brain/action_resolver.py. On
        # failure this clears `action` (falling through to the `elif
        # speech:` below, same as the LLM having given no action at all —
        # a target that couldn't be resolved must not also silently
        # swallow a real utterance).
        if available_actions is not None:
            from brain.action_resolver import resolve_and_apply
            if not resolve_and_apply(c, world, action, available_actions):
                action = None

        # brain/llm_brain.py::_to_legacy_decision() gives speech the same
        # target_description as the action when they're plausibly the
        # same person (speak/socialize/phone_*), rather than resolving it
        # a second time — reuse the action's already-resolved target here.
        if action and speech and not speech.get("target") and speech.get("target_description") and action.get("target"):
            speech["target"] = action["target"]

    # Confirmed live bug: dialogue narrated mid some OTHER activity (the
    # chosen action isn't speak-like at all, e.g. "eat" while chatting)
    # never got a target through the bridge above -- speech["target"]
    # stayed None forever, and action_router.py::apply_speech()'s entire
    # conversation-threading block (a real conversation object, waking
    # the listener specifically, scheduling their reply) is gated on a
    # resolved target. Independently resolve speech's own
    # target_description here (llm_brain.py may have pulled a name
    # straight out of the narration when nothing else supplied one) --
    # apply_speech() itself still falls back further, to whoever's
    # simply nearest, when even this finds nobody real to match.
    if speech and not speech.get("target") and speech.get("target_description") and available_actions is not None:
        from brain.action_resolver import resolve_target
        result = resolve_target(c, world, "speak", speech["target_description"], available_actions)
        if result["id"] is not None:
            speech["target"] = result["id"]

    if action:

        valid = validate_action(
            c,
            world,
            action
        )

        if valid:

            route_action(
                c,
                world,
                action,
                speech,
                definitions=world.get("definitions", {}),
                available_actions=available_actions
            )

            # route_action() above scaffolds c["activity"] for activity-style
            # action types (eat, sleep, work, ...) via _scaffold()/start_activity().
            # Process that scaffolded activity's first tick immediately rather
            # than waiting a full tick — but read it back off c, not the raw
            # LLM `action` dict, which never has the "phase"/"duration"/etc.
            # fields execute_activity() requires and isn't itself an activity.
            # Some action types (hug, confront, propose_chore, ...) don't set
            # c["activity"] at all, hence the truthiness guard.
            if action.get("type") not in (
                "speak", "socialize", "move",
                "interact", "wait", "call", "text",
            ) and c.get("activity"):
                execute_activity(
                    c,
                    world,
                    c["activity"]
                )

        else:

            c["last_invalid_action"] = action

            if speech:
                from systems.action_router import apply_speech
                apply_speech(c, world, speech)

    elif speech:
        # LLM wants to speak but gave no action (or its target failed to
        # resolve, see above)
        from systems.action_router import apply_speech
        apply_speech(c, world, speech)

# =========================================================
# POST UPDATE
# =========================================================

def post_update(

    c,

    world
):

    update_story_arc(c)


# =========================================================
# MAIN AGENT TICK
# =========================================================

def update_agent(

    c,

    world
):

    from systems.reflection import (
        process_reflections
    )

    # =====================================
    # OFFGRID
    # =====================================

    update_offgrid(

        c,

        world
    )

    if c.get("off_grid") and c.get("activity"):
        # Whoever is away can't also be mid-activity at home; nothing else ever
        # progresses or clears it while they're off-grid.
        from systems.occupancy import interrupt_activity
        interrupt_activity(c, world)

    if c.get(
        "off_grid"
    ) or c.get(
        "travel_state"
    ) in TRAVEL_FROZEN_STATES:
        return

    from systems.activity_watchdog import check_activity_watchdog
    check_activity_watchdog(c, world)

    from systems.idle_quirks import advance_idle_quirk
    advance_idle_quirk(c, world)

    # =====================================
    # INTERNAL STATE
    # =====================================

    update_internal_state(

        c,

        world
    )

    # =====================================
    # PERSISTENT DESIRES
    # =====================================

    update_desires(
    c,
    world
    )

    from brain.intentions import check_intention_deadlines
    check_intention_deadlines(c, world)

    # =====================================
    # EXPECTATIONS
    # =====================================

    update_expectations(
        c,
        world
    )

    # =====================================
    # CONVENIENCE / STABILITY
    # =====================================

    update_convenience(
        c,
        world
    )

    # =====================================
    # WHEREABOUTS -- ask a regular contact of whoever c is trying to
    # reach, and deliver any relay message c is carrying (see
    # systems/whereabouts.py). Relies on c["perception"] already being
    # populated this tick (perception runs earlier in this same loop).
    # =====================================

    from systems.whereabouts import check_ask_whereabouts, deliver_pending_relays
    deliver_pending_relays(c, world)
    check_ask_whereabouts(c, world)

    # =====================================
    # COOKING FOOD
    # =====================================

    household = world[
        "households"
    ].get(
        c.get("household_id")
    )

    if household:

        update_cooking_process(

            c,

            household,

            world
        )

    # =====================================
    # REFLECTIONS
    # =====================================

    process_reflections(

        c,

        world
    )

    # =====================================
    # SOCIAL INTENTIONS
    # =====================================

    update_social_intentions(

        c,

        world
    )

    # =====================================
    # ECONOMY
    # =====================================

    update_economy(

        c,

        world
    )

    # =====================================
    # SCHEDULES
    # =====================================

    update_schedule_runtime(

        c,

        world
    )

    # =====================================
    # CLEAN / SORT INTENTIONS
    # =====================================

    clean_intentions(c)

    # Boost priorities for activities the character habitually does at this hour
    from systems.habits import apply_habit_bias_to_intentions
    apply_habit_bias_to_intentions(c, world)

    sort_intentions(c)

    # =====================================
    # SITUATION SELECTION (brain/situations/) -- deterministic, no LLM.
    # Per the user's explicit ask: decide *what deserves attention* as its
    # own cheap, explainable step, separate from the LLM later deciding
    # *what to do about it*. Runs every tick (candidates are just
    # c["active_intentions"], already maintained above) so
    # c["selected_situation"] is always current by the time a real
    # think() call actually happens; context_builder.py reads it to
    # foreground the winning situation(s) in what the LLM is shown,
    # instead of just a flat top-6 priority list with no explicit "this
    # one" framing.
    # =====================================

    from brain.situations.selector import select_situation
    c["selected_situation"] = select_situation(c, world)

    # =====================================
    # ITEM KNOWLEDGE DECAY
    # =====================================

    update_item_knowledge(c, world)

    # =====================================
    # ACTIVE ACTIVITY
    # =====================================

    if c.get("activity"):

        # An activity's own "walking" phase (activities.py::execute_activity)
        # only ever checks is_moving to decide whether the character has
        # arrived -- it never itself advances position. update_character_
        # movement() is what flips is_moving to False on arrival.
        #
        # Confirmed live bug (player report: a character mid-walk to the
        # kitchen frozen in place for well over a minute, moving only in
        # occasional bursts): this used to call update_character_movement()
        # right here -- meaning actual position interpolation, pure CPU-
        # bound math with no LLM/network call involved, only ever
        # happened when THIS character's own update_agent() call (run on
        # sim_loop.py's per-character worker-thread pool, sharing the GIL
        # with however many OTHER characters are mid-LLM-call that same
        # tick) actually got its turn within the pool's bounded per-tick
        # wait budget. A character who was otherwise idle computationally
        # but just happened to share a busy tick with someone else's slow
        # think() call got their walk stalled for no reason connected to
        # their own state at all. Movement is now applied once, up front,
        # for every is_moving character, directly in sim_loop.py's main
        # tick() -- before any per-character dispatch -- so it can never
        # be delayed by another character's unrelated LLM latency. By the
        # time this function runs, is_moving already reflects this same
        # tick's movement, so there is nothing left to do here.

        # Check whether an urgent body need should interrupt a queued hobby.
        # Only activities in queues flagged "interruptible" can be suspended;
        # survival activities (sleep, toilet, eat) always run to completion.
        urgent = _check_urgent_interruption(c)
        act_type = (c["activity"] or {}).get("type", "")

        # Confirmed live bug (real player report): sleep had NO way to be
        # interrupted by anything, including a genuine bathroom emergency
        # -- bladder/bowels intentions are flagged "interrupts": True by
        # body_intentions.py, but that flag was never actually read
        # anywhere in the codebase. Per the user's explicit ask, this is
        # the one real physical-urgency exception to "survival activities
        # always run to completion" above: sleep specifically (not eat/
        # use_toilet themselves -- no need to interrupt a bathroom trip
        # for a bathroom need) yields to a genuinely urgent bladder/bowels
        # need, remembers to resume afterward (see activities.py's
        # use_toilet completion hook), and falls through to this same
        # tick's normal flow so the freshly-highest-priority use_toilet
        # intention gets picked up immediately instead of waiting a tick.
        # Confirmed live bug (real player report): work never actually
        # took priority over anything -- maybe_go_offgrid() (offgrid.py)
        # can only ever fire once c["activity"] is already empty (this
        # whole block returns early otherwise), so a character mid-way
        # through some discretionary activity (a hobby, chores, leisure)
        # when their real scheduled shift started just... didn't go,
        # every time, with no real diagnosis of why beyond a vague
        # end-of-day catch-all. Per the user's explicit ask: work is a
        # real commitment and should interrupt a merely discretionary
        # activity -- but NOT the same protected survival activities
        # sleep already isn't interrupted for (using the toilet, eating,
        # or sleeping itself -- consistent with "only pee/being woken/
        # noise interrupts sleep" from the bathroom-urgency branch below).
        _PROTECTED_FOR_WORK = ("sleep", "use_toilet", "use_toilet_bowels", "eat")
        from systems.offgrid import _work_block_starting_now
        work_starting = c.get("employed") and _work_block_starting_now(c, world)

        # A character's own set_phone_alarm_clock (action_router.py) --
        # the one real way to defend a scheduled commitment against
        # oversleeping, since sleep's own duration (activities.py::
        # compute_duration_ticks) is driven purely by fatigue, never by
        # the clock or the character's schedule. Recurring by design (no
        # disarm) -- a real alarm clock keeps going off at the same time
        # every day until reset to a different time.
        #
        # Per the user's explicit ask: waking to an alarm isn't a sure
        # thing -- a real chance/risk roll (reduced for "deep_sleeper"),
        # rechecked every ~10 minutes with rising odds rather than a
        # single pass/fail, mirrors how a real alarm keeps going off/
        # snoozing rather than ringing exactly once. Bounded to a real
        # cap (ALARM_SNOOZE_MAX_ATTEMPTS) so a persistent failure doesn't
        # recheck forever -- past that, sleep just runs to its own
        # natural end, same as if no alarm had been set at all.
        ALARM_WAKE_BASE_CHANCE = 0.85
        ALARM_WAKE_ATTEMPT_BONUS = 0.15
        ALARM_SNOOZE_RECHECK_MINUTES = 10
        ALARM_SNOOZE_MAX_ATTEMPTS = 8

        alarm = c.get("phone_alarm")
        now_minute = world.get("calendar", {}).get("minute_of_day", -1)
        snooze = c.get("_alarm_snooze")
        alarm_ringing = act_type == "sleep" and alarm and alarm.get("minute_of_day") == now_minute and not snooze
        alarm_rechecking = act_type == "sleep" and snooze and snooze.get("next_check_minute") == now_minute

        if alarm_ringing or alarm_rechecking:
            attempts = snooze.get("attempts", 0) if snooze else 0
            wake_chance = min(1.0, ALARM_WAKE_BASE_CHANCE + attempts * ALARM_WAKE_ATTEMPT_BONUS)
            if "deep_sleeper" in (c.get("physical_traits") or []):
                wake_chance = max(0.05, wake_chance - 0.40)

            if random.random() < wake_chance:
                c.pop("_alarm_snooze", None)
                from systems.occupancy import interrupt_activity
                from systems.reactions import trigger_reaction
                interrupt_activity(c, world)
                try:
                    trigger_reaction(c, world, "surprise", tick=world.get("tick", 0))
                except Exception:
                    pass
            else:
                attempts += 1
                if attempts >= ALARM_SNOOZE_MAX_ATTEMPTS:
                    c.pop("_alarm_snooze", None)  # gives up -- sleeps on naturally
                else:
                    c["_alarm_snooze"] = {
                        "attempts": attempts,
                        "next_check_minute": (now_minute + ALARM_SNOOZE_RECHECK_MINUTES) % 1440,
                    }
        elif act_type == "sleep" and urgent in ("urgent_bladder", "urgent_bowels"):
            # Confirmed live bug (real player report + live data: bowels
            # stuck frozen at exactly 100 forever, phase_started_tick
            # matching "now" on every single check): merely interrupting
            # and falling through to the normal intention-resolution loop
            # was NOT enough -- sleep's own "exhausted" intention (up to
            # priority 98) actually OUTRANKS the bathroom intention
            # (bladder/bowels_urgent, priority 95), both being "survival"
            # category, so the very next selection just picked sleep
            # right back up before the character ever took a single step
            # toward the toilet -- an infinite interrupt/re-sleep loop
            # that never once actually resolved the real need. Directly
            # starting the bathroom trip here, rather than trusting
            # priority ordering to sort it out, is what actually gets
            # them there.
            c["_resume_sleep_after_bathroom"] = True
            from systems.occupancy import interrupt_activity
            interrupt_activity(c, world)
            start_activity(c, world, "use_toilet")
        elif work_starting and act_type not in _PROTECTED_FOR_WORK:
            c.pop("_last_work_miss_reason", None)
            from systems.occupancy import interrupt_activity
            interrupt_activity(c, world)
            # Fall through: no activity now, this same tick's normal flow
            # below will let maybe_go_offgrid() actually dispatch the shift.
        elif work_starting and act_type in _PROTECTED_FOR_WORK:
            # A real, precise reason -- snapshotted at the EXACT tick their
            # shift was due to start, not whatever they happen to be doing
            # at the once-a-day expectation-miss check (see systems/
            # expectations.py::_diagnose_miss_reason(), which now reads
            # this first for a go_to_work miss specifically).
            c["_last_work_miss_reason"] = f"you were {act_type.replace('_', ' ')}"
            execute_activity(c, world, c["activity"])
            return
        elif urgent and c.get("activity_queue"):
            from systems.hobby_requirements import HOBBY_REQUIREMENTS
            hobby_params = c.get("_active_hobby_params", {})
            hobby_name   = hobby_params.get("hobby", "")
            interruptible = HOBBY_REQUIREMENTS.get(hobby_name, {}).get("interruptible", False)
            if interruptible:
                suspend_activity_queue(c, world, reason=urgent)
                # Fall through: no activity now, agent loop will address the urgent need
            else:
                execute_activity(c, world, c["activity"])
                return
        else:
            execute_activity(c, world, c["activity"])
            return

    # =====================================
    # MOVEMENT
    # =====================================
    # If still walking a previously-planned route, let it continue and
    # skip evaluating new intentions / calling the LLM this tick.
    #
    # update_character_movement() itself now runs once, up front, for
    # every is_moving character directly in sim_loop.py's main tick() --
    # see the matching comment on this function's activity branch above
    # for why -- so by this point in the tick, is_moving/pushing_prop_id
    # already reflect the outcome of this tick's movement. A pusher (see
    # update_character_movement's own pushing_prop_id short-circuit)
    # always counts as "still moving" here even though it doesn't drive
    # is_moving itself -- it's attached to the dragger, not walking its
    # own route.
    if (c.get("is_moving") or c.get("pushing_prop_id")
            or c.get("travel_state") in TRAVEL_WALKING_STATES):
        return

    # =====================================
    # EXECUTE SOCIAL / BODY INTENTIONS
    # =====================================

    for intention in c.get(
        "active_intentions",
        []
    ):

        activity_type = resolve_strategy(
            c,
            world,
            intention
        )

        if not activity_type:
            continue

        started = start_activity(
            c,
            world,
            activity_type
        )

        if started:

            c["current_intention"] = (
                intention
            )

            return

    # =====================================
    # COGNITION GATE
    # =====================================
    # Only call the LLM if there's actually something to decide — an idle
    # cadence interval elapsed, an urgent body need just crossed threshold,
    # or an event (perception/activity/speech) woke this character. See
    # brain/cognition_scheduler.py for why this replaced calling think()
    # on every single tick.

    wake_reason = should_think(c, world)

    if not wake_reason:
        return

    # A genuinely idle moment -- rolled here, before EITHER the middleware or
    # the built-in think() below ever sees it, so roaming/checking the door/
    # pausing at a window is real base behavior, not something either brain
    # has to remember to offer. See systems/idle_quirks.py.
    if wake_reason == "idle":
        from systems.idle_quirks import maybe_delay_or_quirk
        if maybe_delay_or_quirk(c, world):
            return

    # Characters owned by the standalone AI middleware (../middleware) are
    # decided for through api/middleware_bridge.py. brain/external_brain.py's
    # is_external() is only true while the middleware's heartbeat is fresh, so
    # a dead middleware falls straight back to the built-in think() below.
    from brain.external_brain import is_external
    if is_external(c):
        return

    # =====================================
    # BUILD CONTEXT
    # =====================================

    from brain.cognition_scheduler import wake_line as _wake_line
    context = build_context(
        c,
        world,
        trigger_reason=wake_reason,
        wake_line=_wake_line(c),
        staged=c.get("cognition", {}).get("staged_knowledge") or (),
    )

    # =====================================
    # THINK
    # =====================================

    # LLM call priority (llm/llm_gate.py's queue) -- reuses the same
    # CATEGORY_PRIORITY weights active_intentions are already sorted by,
    # rather than inventing a second urgency taxonomy. A character whose
    # top intention is survival/health-category, or who's mid-conversation
    # (a stalled reply reads as broken to whoever they're talking to), gets
    # PRIORITY_URGENT; everything else is PRIORITY_NORMAL.
    from brain.intentions import final_priority
    from llm.llm_gate import PRIORITY_URGENT, PRIORITY_NORMAL
    top_intentions = c.get("active_intentions", [])
    top_category = max(top_intentions, key=lambda i: final_priority(i, c)).get("category") if top_intentions else None
    llm_priority = (
        PRIORITY_URGENT
        if top_category in ("survival", "health") or c.get("conversation")
        else PRIORITY_NORMAL
    )

    decision = think(
        context,
        char_id=c["id"],
        session=c.get("_llm_session"),
        priority=llm_priority,
    )

    # Clear the wake state and schedule the next idle check-in regardless
    # of whether the LLM call succeeded — a failed call must not leave the
    # character re-triggering should_think() every tick forever.
    note_think(c, world, decision, wake_reason=wake_reason)

    if not decision:
        return

    # =====================================
    # PROCESS DECISION
    # =====================================

    process_decision(
        c,
        world,
        decision,
        available_actions=context.get("available_actions")
    )

    # =====================================
    # POST
    # =====================================

    post_update(
        c,
        world
    )
    #