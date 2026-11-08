# Event-driven, sensory-filtered updates (plan + scaffold)

Goal: stop running poll-for-change jobs against every entity every N ticks.
Instead, an entity mutation emits a change; only characters who can actually
perceive it (vision / hearing range / line of sight) or are directly affected
are notified, and their (possibly LLM-driven) decision is requested.

## Principles
- Headless world stays authoritative; perception is simulated, not rendered.
- Sensory gate = brain.perception: visible_people, hearing_range, line_of_sight.
- Only observers who pass the gate (or are directly affected) get the update.
- One-shot follow-ups use core.scheduler timers, not recurring sweeps.
- Migration is job-by-job; behaviour must stay identical until a job is
  converted and verified with tests/determinism.py.

## Poll jobs -> event/timer targets (from core/tick_schedule.py CADENCE)
Representative conversions (not exhaustive):
- perception (5): emit "perceived_change" when a character's visible set changes;
  observers already in range are notified instead of re-scanning all pairs.
- attention (5): event-driven on perceive/heard.
- relationships (15): recompute on interaction events, not sweep.
- conflicts/grapples (5): already event-ish; keep as events.
- conversation_cleanup (60): timer per conversation (already scheduler-friendly).
- memory_decay, emotion, market, cooking (15-30): timer per entity.
- health, lt_needs, cleanliness, plants, food_aging: lazy value + threshold timer
  (see docs/distributed_architecture_plan.md step 2).
- worry_poll/focus_check (60): per-character timer.
- rumors/introductions/neighbours/kids_play (300-600): event on new arrival / sighting.
- socioeconomics, police_feed, daily_finance (24): calendar daily event.
- home_presence (3600): hourly timer.

## Scaffold
core/sensory_event_dispatcher.py provides:
- register/unregister listeners per change type
- emit_change(world, entity_id, change_type, payload, direct=[...])
- can_perceive(observer_id, source_id, world) sensory gate
- observers_of(world, source_id)
- flush(world) dispatch to perceiving listeners
- schedule(...) one-shot timer helper
- fire_due_timers(...) fallback

## Next steps
1. Convert one low-risk job (e.g. introductions or kids_play) to emit_change.
2. Add a tick-level call to sensory_event_dispatcher.flush(world) and fire_due_timers.
3. Verify with tests/determinism.py (seeded, fake clock) that behaviour is identical.
4. Repeat job-by-job.
PY