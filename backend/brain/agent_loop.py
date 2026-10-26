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

from core import tick_profile as _prof
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
    _prof.mark("internal:if_L208")
    if c.get("travel_hidden") and not c.get("off_grid") and not c.get("travel_state"):
        c["travel_hidden"] = False
        from sim_loop import _mark_dirty
        _mark_dirty(world, char_ids={c["id"]})

    _prof.mark("internal:ensure_body")
    ensure_body(c)           # migrate old characters; no-op on new ones
    # The needs are lazy values (systems/body_lazy.py): nothing is integrated here per tick.
    # This O(1) check only reacts to a regime flip (sleep started/ended, a stimulant ran out),
    # a meal/shower/toilet that touched the body, or values getting staler than 30 ticks.
    from systems.body_lazy import tick_check as _body_tick_check
    _prof.mark("internal:_body_tick_check")
    _body_tick_check(c, world)
    _prof.mark("internal:update_emotion")
    update_emotion(
        c,
        world
    )
    # Ensure lt_needs distributed (idempotent — no-op if already set)
    from systems.lt_needs import distribute_lt_needs
    _prof.mark("internal:distribute_lt_needs")
    distribute_lt_needs(c, world=world)

    _prof.mark("internal:clear_expired_speech")
    clear_expired_speech(c, world)

    _prof.mark("internal:promote_pending_posture")
    promote_pending_posture(c, world)

    _prof.mark("internal:decay_memories")
    decay_memories(c)

    _prof.mark("internal:decay_habits")
    decay_habits(c)

    _prof.mark("internal:process_health")
    process_health(
        c,
        world
    )

    from systems.waiting import tick_waiting
    _prof.mark("internal:tick_waiting")
    tick_waiting(c, world)

    from systems.curiosity import tick_curiosity
    _prof.mark("internal:tick_curiosity")
    tick_curiosity(c, world)

    _prof.mark("internal:consolidate_relationship_narratives")
    consolidate_relationship_narratives(c)

    _prof.mark("internal:consolidate_life_narratives")
    consolidate_life_narratives(c)

    _prof.mark("internal:consolidate_identity")
    consolidate_identity(c)
    # generate_body_intentions() is no longer polled every tick: it runs when the body-driven
    # intentions would change (forward-probed timer), on a regime flip, or after a meal/
    # shower/toilet -- see systems/body_lazy.py.

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

    _prof.mark("economy:apply_for_job")
    apply_for_job(
        c,
        world
    )

    _prof.mark("economy:attempt_pay_bills")
    attempt_pay_bills(
        c,
        world
    )

    # Per the user's explicit ask: a character with real slack in their
    # bank balance should try to pay off debt sooner, not just let it
    # carry along at minimum forever. Self-gated to once per calendar day.
    from systems.loans import maybe_prepay_debt
    _prof.mark("economy:maybe_prepay_debt")
    maybe_prepay_debt(c, world)

    # Per the user's explicit ask: an elderly character past retirement
    # age stops working (and stops being expected to) instead of working
    # indefinitely. Self-gated on c["retired"], cheap no-op afterward.
    from systems.retirement import maybe_retire, maybe_retire_disabled
    _prof.mark("economy:maybe_retire")
    maybe_retire(c, world)
    _prof.mark("economy:maybe_retire_disabled")
    maybe_retire_disabled(c, world)

    # Per the user's explicit ask: hourly memory consolidation into a
    # separate long-term store, plus periodic random forgetting of the
    # raw short-term log. Both self-gate on their own tick interval.
    from systems.memory_consolidation import maybe_consolidate_memories, maybe_forget_short_term
    _prof.mark("economy:maybe_consolidate_memories")
    maybe_consolidate_memories(c, world)
    _prof.mark("economy:maybe_forget_short_term")
    maybe_forget_short_term(c, world)


# =========================================================
# OFFGRID
# =========================================================

def update_offgrid(

    c,

    world
):

    _prof.mark("offgrid:process_return")
    process_return(
        c,
        world
    )

    _prof.mark("offgrid:update_travel")
    update_travel(
        c,
        world
    )

    _prof.mark("offgrid:maybe_go_offgrid")
    maybe_go_offgrid(
        c,
        world
    )

    _prof.mark("offgrid:maybe_schedule_doctor_visit")
    maybe_schedule_doctor_visit(
        c,
        world
    )

    _prof.mark("offgrid:resolve_due_appointments")
    resolve_due_appointments(
        c,
        world
    )

    _prof.mark("offgrid:maybe_seek_validation_from_queue")
    maybe_seek_validation_from_queue(
        c,
        world
    )

    _prof.mark("offgrid:check_validation_refresh")
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

    _prof.mark("agent:update_offgrid")
    update_offgrid(

        c,

        world
    )

    _prof.mark("agent:if_L645")
    if c.get("off_grid") and c.get("activity"):
        # Whoever is away can't also be mid-activity at home; nothing else ever
        # progresses or clears it while they're off-grid.
        from systems.occupancy import interrupt_activity
        interrupt_activity(c, world)

    # Needs don't move while off-grid or on a trip: catch the body up under the regime that
    # just ended before this character stops being updated (systems/body_lazy.py).
    from systems.body_lazy import tick_check as _body_tick_check_early
    _prof.mark("agent:_body_tick_check_early")
    _body_tick_check_early(c, world)

    _prof.mark("agent:if_L656")
    if c.get(
        "off_grid"
    ) or c.get(
        "travel_state"
    ) in TRAVEL_FROZEN_STATES:
        return

    from systems.activity_watchdog import check_activity_watchdog
    _prof.mark("agent:check_activity_watchdog")
    check_activity_watchdog(c, world)

    from systems.idle_quirks import advance_idle_quirk
    _prof.mark("agent:advance_idle_quirk")
    advance_idle_quirk(c, world)

    # =====================================
    # INTERNAL STATE
    # =====================================

    _prof.mark("agent:update_internal_state")
    update_internal_state(

        c,

        world
    )

    # =====================================
    # PERSISTENT DESIRES
    # =====================================

    _prof.mark("agent:update_desires")
    update_desires(
    c,
    world
    )

    from brain.intentions import check_intention_deadlines
    _prof.mark("agent:check_intention_deadlines")
    check_intention_deadlines(c, world)

    # =====================================
    # EXPECTATIONS
    # =====================================

    _prof.mark("agent:update_expectations")
    update_expectations(
        c,
        world
    )

    # =====================================
    # CONVENIENCE / STABILITY
    # =====================================

    _prof.mark("agent:update_convenience")
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
    _prof.mark("agent:deliver_pending_relays")
    deliver_pending_relays(c, world)
    _prof.mark("agent:check_ask_whereabouts")
    check_ask_whereabouts(c, world)

    # A child who watched grown-ups argue wants to know why -- see
    # systems/child_cognition.py. No-op for everyone else.
    from systems.child_cognition import update_child_cognition
    _prof.mark("agent:update_child_cognition")
    update_child_cognition(c, world)

    # =====================================
    # COOKING FOOD
    # =====================================

    _prof.mark("agent:get")
    household = world[
        "households"
    ].get(
        c.get("household_id")
    )

    _prof.mark("agent:if_L736")
    if household:

        update_cooking_process(

            c,

            household,

            world
        )

    # =====================================
    # REFLECTIONS
    # =====================================

    _prof.mark("agent:process_reflections")
    process_reflections(

        c,

        world
    )

    # =====================================
    # SOCIAL INTENTIONS
    # =====================================

    _prof.mark("agent:update_social_intentions")
    update_social_intentions(

        c,

        world
    )

    # =====================================
    # ECONOMY
    # =====================================

    _prof.mark("agent:update_economy")
    update_economy(

        c,

        world
    )

    # =====================================
    # SCHEDULES
    # =====================================

    _prof.mark("agent:update_schedule_runtime")
    update_schedule_runtime(

        c,

        world
    )

    # =====================================
    # CLEAN / SORT INTENTIONS
    # =====================================

    _prof.mark("agent:clean_intentions")
    clean_intentions(c)

    # Boost priorities for activities the character habitually does at this hour
    from systems.habits import apply_habit_bias_to_intentions
    _prof.mark("agent:apply_habit_bias_to_intentions")
    apply_habit_bias_to_intentions(c, world)

    _prof.mark("agent:sort_intentions")
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

    # select_situation() is NOT run here any more: its only reader is the prompt built for a
    # decision, so it is computed lazily in brain/context_builder.py::build_context (the
    # moment it is needed). Running it every tick also recorded a "selection" into
    # c["_situation_history"] every tick -- a 40-entry window, so the novelty/cooldown
    # scoring only ever saw the last 40 TICKS and penalised whatever had just been chosen
    # for being chosen. Recorded once per decision it now covers the last 40 decisions,
    # which is what the cooldowns (5-60 minutes) were written for.

    # =====================================
    # ITEM KNOWLEDGE DECAY
    # =====================================

    _prof.mark("agent:update_item_knowledge")
    update_item_knowledge(c, world)

    # =====================================
    # ACTIVE ACTIVITY
    # =====================================

    _prof.mark("agent:if_L829")
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
        _KEPT_AT_BEDTIME = _PROTECTED_FOR_WORK + ("take_shower", "take_bath", "brush_teeth", "wash_hands", "vomit", "nap", "take_nap")
        from systems.bedtime import wants_bed
        from systems.offgrid import school_starting_now
        school_starting = school_starting_now(c, world)
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
        elif school_starting and act_type not in ("use_toilet", "use_toilet_bowels", "eat"):
            # The school bell: a child still asleep (or busy with anything but the bathroom or breakfast) is got up and sent
            # on their way -- the next step of this same tick lets maybe_go_offgrid() dispatch the school day.
            from systems.occupancy import interrupt_activity
            interrupt_activity(c, world)
        elif (act_type not in _KEPT_AT_BEDTIME and world.get("tick", 0) - c.get("_bedtime_interrupt_tick", -10 ** 9) >= 600
              and wants_bed(c, world)):
            # Bedtime before a work or school day (systems/bedtime.py) outranks whatever discretionary thing is running
            # -- an 8-hour "work" session at home at 1 a.m. -- so the "bedtime" sleep intention gets its turn. At most once
            # every 10 minutes, so a different activity that wins instead is not cut short again and again.
            c["_bedtime_interrupt_tick"] = world.get("tick", 0)
            from systems.occupancy import interrupt_activity
            interrupt_activity(c, world)
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
    _prof.mark("agent:if_L1006")
    if (c.get("is_moving") or c.get("pushing_prop_id")
            or c.get("travel_state") in TRAVEL_WALKING_STATES):
        return

    # A breakdown (systems/worry_breakdown.py): their own intentions are suspended and nobody asks their model what
    # to do; only a survival need can still take over. The episode's own beats run from the minute job.
    from systems.worry_breakdown import in_breakdown, survival_only
    if in_breakdown(c):
        survival_only(c, world)
        return

    # =====================================
    # EXECUTE SOCIAL / BODY INTENTIONS
    # =====================================

    # A survival/health need that resolved to something but couldn't actually be
    # started (no food and no way to get any, ...) is BLOCKED, not done: nothing
    # lower down -- chores, leisure -- may autopilot in its place, because that
    # returns before the character ever gets to think and they'd keep doing
    # busywork while starving. Falling through lets their own judgment handle it.
    blocked_urgent = False

    for intention in c.get(
        "active_intentions",
        []
    ):

        if blocked_urgent and intention.get("category") in ("chores", "leisure", "identity"):
            continue

        activity_type = resolve_strategy(
            c,
            world,
            intention
        )

        if not activity_type:
            if intention.get("type") == "eat_food":
                blocked_urgent = True       # nothing to eat and no way to get any: their own judgment, not busywork
            continue

        started = start_activity(
            c,
            world,
            activity_type
        )

        if not started and intention.get("category") in ("survival", "health"):
            blocked_urgent = True

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

    # A decision already with the model (brain/cognition_actor.py): the character carries on
    # living -- everything above this point still ran -- but doesn't ask again.
    from brain.cognition_actor import is_waiting, request_decision
    _prof.mark("agent:if_L1069")
    if is_waiting(c):
        return

    _prof.mark("agent:should_think")
    wake_reason = should_think(c, world)

    _prof.mark("agent:if_L1074")
    if not wake_reason:
        return

    # A genuinely idle moment -- rolled here, before EITHER the middleware or
    # the built-in think() below ever sees it, so roaming/checking the door/
    # pausing at a window is real base behavior, not something either brain
    # has to remember to offer. See systems/idle_quirks.py.
    _prof.mark("agent:if_L1081")
    if wake_reason == "idle":
        from systems.idle_quirks import maybe_delay_or_quirk
        if maybe_delay_or_quirk(c, world):
            return

    # Characters owned by the standalone AI middleware (../middleware) are
    # decided for through api/middleware_bridge.py. brain/external_brain.py's
    # is_external() is only true while the middleware's heartbeat is fresh, so
    # a dead middleware falls straight back to the built-in think() below.
    from brain.external_brain import is_external
    _prof.mark("agent:if_L1091")
    if is_external(c):
        return

    # =====================================
    # BUILD CONTEXT
    # =====================================

    from brain.cognition_scheduler import wake_line as _wake_line
    _prof.mark("agent:build_context")
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
    _prof.mark("agent:get#2")
    top_intentions = c.get("active_intentions", [])
    top_category = max(top_intentions, key=lambda i: final_priority(i, c)).get("category") if top_intentions else None
    llm_priority = (
        PRIORITY_URGENT
        if top_category in ("survival", "health") or c.get("conversation")
        else PRIORITY_NORMAL
    )

    # Ask the model in the background and carry on: the answer comes back as a
    # `decision_ready` event, is noted and processed (re-validated against the world as it is
    # THEN) by brain/cognition_actor.py::on_decision_ready. Nothing here blocks the tick.
    _prof.mark("agent:request_decision")
    request_decision(c, world, context, wake_reason, llm_priority)
