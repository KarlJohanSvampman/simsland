"""
brain/cognition_scheduler.py

Decides, per character per tick, whether update_agent() should actually
call think() (a full LLM decision round-trip) this tick.

Before this module existed, every character with no active activity, no
mid-walk movement, and no resolvable intention called think() on literally
every tick — once per simulated second, with zero throttling beyond the
global Ollama concurrency semaphore (llm/llm_gate.py). That's the dominant
source of LLM call volume and tick latency in this sim.

should_think() replaces that with:
  - an idle cadence (think roughly every IDLE_BASE_TICKS ticks when nothing
    is happening, backing off toward IDLE_MAX_TICKS on repeated "wait"
    decisions)
  - event-driven wakes (wake_character()) fired by perception, activity
    lifecycle, and speech — see core/event_handlers.py for the subscriptions
    that call wake_character()
  - an edge-triggered urgent-body-need check (a bladder/hunger/etc. crossing
    its interrupt threshold wakes the character once, not every tick while
    it stays crossed)

Usage (brain/agent_loop.py::update_agent, immediately before build_context):
    reason = should_think(c, world)
    if not reason:
        return
    ...
    note_think(c, world, decision)   # called even if decision is None/falsy
"""

import os
import threading
import logging

IDLE_BASE_TICKS = int(os.getenv("COGNITION_IDLE_BASE", "45"))
IDLE_MAX_TICKS = int(os.getenv("COGNITION_IDLE_MAX", "300"))
TURN_BUDGET_DEFAULT = int(os.getenv("COGNITION_TURN_BUDGET", "2"))

# Highest-priority wake wins when multiple wakes land on the same character
# before its next think() — e.g. a schedule_block wake pending and then
# heard_speech arrives first; heard_speech should win and fire immediately.
WAKE_PRIORITY = {
    "heard_speech": 100,
    "urgent_need": 90,
    "noticed_commotion": 75,   # systems/curiosity.py -- a curious character just noticed something worth investigating
    "activity_aborted": 80,
    "activity_finished": 70,
    "waiting_timed_out": 68,
    "describe_result": 65,
    "recall_result": 65,
    "resolution_failed": 60,
    "activity_phase_changed": 55,
    "person_entered_view": 50,
    "schedule_block": 40,
    "wait_ready": 35,
    "idle": 0,
}


def _urgent_need(c):
    """Mirrors brain/agent_loop.py::_check_urgent_interruption's thresholds.
    Local copy to avoid a circular import (agent_loop imports this module)."""
    body = c.get("body", {})
    if body.get("bladder", 0) >= 88:
        return "urgent_bladder"
    if body.get("bowels", 0) >= 88:
        return "urgent_bowels"
    if body.get("hunger", 0) >= 82:
        return "urgent_hunger"
    if body.get("fatigue", 0) >= 90:
        return "urgent_fatigue"
    if body.get("hydration", 100) <= 25:
        return "urgent_thirst"
    return None


def _jitter(c, spread):
    """Deterministic per-character offset so the population doesn't
    resync onto the same think tick after every idle interval."""
    if spread <= 0:
        return 0
    return hash(c.get("id", "")) % spread


def should_think(c, world):
    """Return a wake-reason string if update_agent() should call think()
    this tick, else None."""
    cog = c.get("cognition")
    if cog is None:
        # Defensive fallback for a character schema_defaults hasn't touched
        # yet (shouldn't happen in practice — ensure_world_defaults runs
        # schema_defaults on every character before agent_loop sees them).
        return "idle"

    tick = world.get("tick", 0)

    # Edge-triggered urgent-need check — only wakes on a *change*, not
    # every tick the need stays above threshold (that would reproduce the
    # every-tick problem this module exists to fix).
    need = _urgent_need(c)
    if need != cog.get("last_urgent_need"):
        cog["last_urgent_need"] = need
        if need:
            wake_character(c, world, "urgent_need", {"need": need})

    if tick < cog.get("next_think_tick", 0):
        return None

    return cog.get("wake_reason") or "idle"


def wake_character(c, world, reason, payload=None, delay=0):
    """Mark a character as due for a think() call, at or before its current
    schedule. A lower-priority wake never clobbers a pending higher one —
    but it can still pull next_think_tick earlier."""
    cog = c.setdefault("cognition", {})
    tick = world.get("tick", 0)
    target_tick = tick + max(0, delay)

    current = cog.get("wake_reason")
    if current is None or WAKE_PRIORITY.get(reason, 0) >= WAKE_PRIORITY.get(current, 0):
        cog["wake_reason"] = reason
        cog["wake_payload"] = payload or {}

    cog["next_think_tick"] = min(cog.get("next_think_tick", tick), target_tick)


# Plain-format wake-reason templates rendered against cog["wake_payload"] —
# no LLM call. Feeds brain/context_builder.py::build_narrative()'s
# wake_line param so a brief-mode prompt still tells the character *why*
# it's thinking again ("Maria just walked in") without re-telling the
# whole scene.
_WAKE_LINE_TEMPLATES = {
    "person_entered_view": "{subject_name} has just come into view.",
    "heard_speech": '{speaker_name} just said to you: "{utterance}"',
    "activity_phase_changed": "You're finishing up what you were doing.",
    "wait_ready": "What you were waiting on is ready now.",
    "waiting_timed_out": "You've been waiting a while now and your patience is running out.",
    "noticed_commotion": "{summary}",
}


def wake_line(c):
    """Return a formatted wake-reason sentence for this character's
    current pending wake, or None if there isn't one or no template
    applies (e.g. idle — the full narrative speaks for itself there)."""
    cog = c.get("cognition") or {}
    reason = cog.get("wake_reason")
    template = _WAKE_LINE_TEMPLATES.get(reason)
    if not template:
        return None
    payload = cog.get("wake_payload") or {}
    try:
        return template.format(**payload)
    except (KeyError, IndexError):
        return None


def note_think(c, world, decision, wake_reason=None):
    """Call after every think() attempt (even a failed/None one) to clear
    the wake state and schedule the next idle check-in. wake_reason is the
    string should_think() returned for this cycle (agent_loop.py already
    has it in scope) — recorded for the Round 10 observability histogram
    below; falls back to the character's own pending wake_reason (which
    won't distinguish a natural idle-cadence trigger from an unset one,
    hence preferring the explicit param) if the caller doesn't pass it."""
    cog = c.setdefault("cognition", {})
    tick = world.get("tick", 0)

    record_think(world, wake_reason or cog.get("wake_reason") or "idle")

    cog["wake_reason"] = None
    cog["wake_payload"] = None
    cog["staged_knowledge"] = []
    cog["last_think_tick"] = tick

    is_wait = bool(decision) and (
        (decision.get("action") or {}).get("type") in (None, "wait", "character_wait")
    )

    if is_wait:
        cog["idle_streak"] = cog.get("idle_streak", 0) + 1
    else:
        cog["idle_streak"] = 0

    # Back off toward IDLE_MAX_TICKS on repeated waits; snap back to
    # IDLE_BASE_TICKS the moment the character does something real.
    streak = cog.get("idle_streak", 0)
    interval = min(IDLE_BASE_TICKS + streak * IDLE_BASE_TICKS, IDLE_MAX_TICKS) if streak else IDLE_BASE_TICKS
    jitter = _jitter(c, IDLE_BASE_TICKS // 2)

    cog["next_think_tick"] = tick + interval + jitter

    # Refill the describe/recall turn budget on every real think() — see
    # stage_and_wake() below, which spends it. Full Round-10 tuning
    # (env-configurable value, observability counters) builds on this same
    # field; the reset itself has to exist now for Round 8/9's describe/
    # recall actions to be usable at all.
    cog["turn_budget"] = TURN_BUDGET_DEFAULT


def stage_and_wake(c, world, text, reason):
    """Used by describe (Round 8) and recall (Round 9): append staged
    prose to the character's cognition state, spend one unit of turn
    budget, and pull them back to think() again this same tick — no event-
    bus round-trip needed, this always targets the calling character's own
    (same-thread-owned) state, same reasoning as activities.py's self-wake
    calls. Returns False (and does not wake) once the turn budget is
    exhausted, so a character can't spiral into an unbounded describe/
    recall chain within one decision."""
    cog = c.setdefault("cognition", {})
    if cog.get("turn_budget", 0) <= 0:
        cog.setdefault("staged_knowledge", []).append(
            "You've already taken time to look and think — better to act now."
        )
        return False

    cog.setdefault("staged_knowledge", []).append(text)
    cog["turn_budget"] = cog.get("turn_budget", 0) - 1
    cog["next_think_tick"] = world.get("tick", 0)

    current = cog.get("wake_reason")
    if current is None or WAKE_PRIORITY.get(reason, 0) >= WAKE_PRIORITY.get(current, 0):
        cog["wake_reason"] = reason
        cog["wake_payload"] = {}

    return True


# =========================================================
# OBSERVABILITY (Round 10)
#
# In-process rolling counters for GET /admin/cognition, mirroring
# core/event_bus.py's _emit_counts/_handled_counts pattern (a module-level
# dict behind a lock, snapshotted by a stats() reader) — the same need
# applies here: note_think()/record_resolver_outcome()/etc. are called
# from update_agent(), which runs on sim_loop.py's 8-worker per-character
# ThreadPoolExecutor, so plain dict increments would race across threads.
# =========================================================

_stats_lock = threading.Lock()
_STATS_WINDOW_TICKS = 100

_think_ticks: dict[int, int] = {}       # tick -> think() calls that tick, pruned to the window
_wake_reason_counts: dict[str, int] = {}  # cumulative — which reason triggered each think()
_prompt_byte_total = 0
_prompt_byte_count = 0
_resolver_counts = {"accept": 0, "ambiguous": 0, "fail": 0}
_describe_recall_counts = {"describe": 0, "recall": 0}
_last_summary_tick = -1

_logger = logging.getLogger("cognition")


def record_think(world, wake_reason):
    """Called once per note_think() — records which tick it landed on and
    which wake reason triggered it."""
    global _last_summary_tick
    tick = world.get("tick", 0)
    with _stats_lock:
        _think_ticks[tick] = _think_ticks.get(tick, 0) + 1
        _wake_reason_counts[wake_reason] = _wake_reason_counts.get(wake_reason, 0) + 1
        cutoff = tick - _STATS_WINDOW_TICKS
        if cutoff > 0:
            for t in [t for t in _think_ticks if t < cutoff]:
                del _think_ticks[t]
        due_summary = tick - _last_summary_tick >= 60
        if due_summary:
            _last_summary_tick = tick
            snapshot = _snapshot_locked()
    if due_summary:
        _logger.info("cognition stats @ tick %s: %s", tick, snapshot)


def record_prompt_bytes(n):
    """Called from brain/llm_brain.py::think() with the combined system
    + user prompt byte length, for the mean-prompt-bytes gauge."""
    global _prompt_byte_total, _prompt_byte_count
    with _stats_lock:
        _prompt_byte_total += n
        _prompt_byte_count += 1


def record_resolver_outcome(outcome):
    """Called from brain/action_resolver.py::resolve_target() with one of
    'accept'/'ambiguous'/'fail' — skipped entirely for the 'none'/no-op
    short-circuit (target="none" specs, or no target_description at all),
    since that isn't the resolver actually doing anything."""
    with _stats_lock:
        if outcome in _resolver_counts:
            _resolver_counts[outcome] += 1


def record_describe_or_recall(kind):
    """Called from systems/action_router.py's _route_describe/_route_recall."""
    with _stats_lock:
        if kind in _describe_recall_counts:
            _describe_recall_counts[kind] += 1


def _snapshot_locked():
    """Build the stats dict — caller must already hold _stats_lock."""
    per_tick = list(_think_ticks.values())
    mean_prompt_bytes = (
        round(_prompt_byte_total / _prompt_byte_count, 1) if _prompt_byte_count else 0
    )
    resolver_total = sum(_resolver_counts.values())
    return {
        "window_ticks": _STATS_WINDOW_TICKS,
        "thinks_per_tick_mean": round(sum(per_tick) / len(per_tick), 2) if per_tick else 0.0,
        "thinks_per_tick_max": max(per_tick) if per_tick else 0,
        "wake_reason_histogram": dict(_wake_reason_counts),
        "mean_prompt_bytes": mean_prompt_bytes,
        "resolver_counts": dict(_resolver_counts),
        "resolver_rates": {
            k: round(v / resolver_total, 3) if resolver_total else 0.0
            for k, v in _resolver_counts.items()
        },
        "describe_recall_counts": dict(_describe_recall_counts),
    }


def get_stats():
    """Snapshot for GET /admin/cognition — see api/admin.py."""
    with _stats_lock:
        return _snapshot_locked()


def clear_stats():
    """Reset all Round 10 counters (useful in tests)."""
    global _prompt_byte_total, _prompt_byte_count, _last_summary_tick
    with _stats_lock:
        _think_ticks.clear()
        _wake_reason_counts.clear()
        _prompt_byte_total = 0
        _prompt_byte_count = 0
        for k in _resolver_counts:
            _resolver_counts[k] = 0
        for k in _describe_recall_counts:
            _describe_recall_counts[k] = 0
        _last_summary_tick = -1
