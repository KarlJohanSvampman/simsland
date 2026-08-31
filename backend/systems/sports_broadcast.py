"""
systems/sports_broadcast.py

Live on-grid game watching -- powers the watch_tv activity when it's
carrying a watching_game tag (see systems/sports.py::kickoff_scheduled_
games). Mirrors reading_process.py's shape almost exactly: every
SCORE_PICK_INTERVAL_TICKS, narrate a score update as a non-blocking
speech bubble ("the TV says X", voiced through the watching character
relaying it aloud -- this codebase has no object/character-less speech
concept), with present others reacting.

The running score narrated mid-game is a plausible PREVIEW only
(sports_leagues.py::preview_score) -- the authoritative final result
always comes from sports_leagues.py's own resolution, narrated the
moment it's available (systems/sports.py::resolve_watch_party() handles
the character's own outcome/mood once the activity completes; this
module only handles the periodic in-progress chatter).
"""

import random

SCORE_PICK_INTERVAL_TICKS = 5 * 60  # 5 sim-minutes, matches reading_process.py


def update_game_broadcast(c, world):
    """Called every CADENCE["reading"]-tier tick for every character (see
    sim_loop.py) -- no-ops immediately for anyone not currently watching a
    game, same guard shape as reading_process.py::update_reading_process."""
    activity = c.get("activity")
    if not activity or activity.get("type") != "watch_tv":
        return False
    watching = activity.get("watching_game")
    if not watching:
        return False

    tick = world.get("tick", 0)
    last_pick = activity.get("_last_score_pick_tick", activity.get("phase_started_tick", tick))
    if tick - last_pick < SCORE_PICK_INTERVAL_TICKS:
        return False
    activity["_last_score_pick_tick"] = tick

    from systems.sports_leagues import get_fixture, GAME_DURATION_TICKS, preview_score
    from systems.sports import _team_display_name

    fx = get_fixture(world, watching["sport"], watching["scope"], watching["fixture_id"])
    if not fx:
        return False

    home_name = _team_display_name(world, watching["sport"], watching["scope"], fx["home"])
    away_name = _team_display_name(world, watching["sport"], watching["scope"], fx["away"])

    if fx.get("result") is not None:
        result = fx["result"]
        line = f'"Final score: {home_name} {result["home"]} - {result["away"]} {away_name}."'
    else:
        elapsed = tick - fx["scheduled_tick"]
        frac = max(0.0, min(1.0, elapsed / GAME_DURATION_TICKS))
        preview = preview_score(world, watching["sport"], watching["scope"], fx, frac)
        line = f'"Score update: {home_name} {preview["home"]} - {preview["away"]} {away_name}."'

    from systems.incidental_speech import fire_incidental
    fire_incidental(c, "inform", line, world)

    from systems.action_router import _co_present_characters
    from systems.reactions import push_reaction
    for listener in _co_present_characters(c, world):
        try:
            push_reaction(listener, "interested" if random.random() < 0.5 else "nod", tick)
        except Exception:
            pass

    return True
