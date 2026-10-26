# Activities: a timeline, one memory, no cut-offs

**Symptom.** "Take out trash" (5 min) never finished: wash dishes, throw away trash, take out trash, sit and relax, take out trash ...
were each cut off at exactly 120 ticks. The model's answer arrives a minute or two after the question; by then autopilot had already
started the chore the intention called for, and the stale answer was applied on top of it.

**Fix** (`systems/activity_guard.py`, wired in `brain/agent_loop.py::process_decision`). An activity with time left that is a chore,
upkeep, food, hygiene, errand or work activity (or flagged not interruptible) is *committed*: a late decision to start something else is
deferred, with a line on the activity's timeline saying what they kept doing. Always let through: an urgent need (an intention flagged
`interrupts`), speech, phone, proposals. Leisure and open-ended activities are never committed.

**Why it ended.** `occupancy.interrupt_activity(c, world, reason=None, outcome="interrupted")` always records a reason: the caller's
own, a reason the decision left in `c["_interrupt_reason"]` ("they chose to sit and relax (...)"), or failing both, the calling module
and function. Natural ends (finishing; sitting down, which is open-ended) are recorded as `completed`.

**Timeline on the activity** (`systems/activity_trace.py`). `act["steps"]` is the plan (walk, use, finish) ticked off with the tick and
clock time each was reached (`set_activity_phase` does the ticking); `act["timeline"]` is what happened in order. When it ends, it is
written as ONE memory (`kind: "activity"`, the whole record in `activity_record`) instead of a memory per step. The inspector shows both
on the live activity's *details* and on the remembered one.

**Never forever.** Every `ACTIVITIES` entry has 1 min .. 8 h (`tests/test_activity_trace.py` audits them and the routed interaction
durations). `activity_watchdog` cancels any phase that overruns (2x, at most two hours over; an activity with no duration gets an
hour; non-using phases 10 min) and records `timed_out` with the phase it was stuck in.

**Posture.** Anything on a seat anchor (`anchor_sit*`: sit in park, sit and relax) sits on arrival and stands when it ends.
