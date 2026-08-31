"""
systems/sports_leagues.py

Season fixture generation and result resolution for both the 4 real pro
leagues (NFL/NBA/NHL/Premier League, definitions.json's sports_teams) and
each sport's invented local league (world["local_teams"], see sports.py).

Schedules live entirely on the sim's OWN calendar/tick counter, not
real-world dates -- "polling match data" (systems/sports_broadcast.py)
means polling this module's own generated fixtures, not a real API.

Storage shape: world["sports_leagues"][sport]["pro"|"local"] = {
    "schedule": [fixture, ...],
    "standings": {team_id: {"wins", "losses", "draws"}},
}
fixture = {
    "id", "sport", "scope", "home", "away",
    "scheduled_tick", "result": None | {"home", "away"},
}
"""

import random

from systems.sports import SPORTS, ensure_local_league

TICKS_PER_GAME_DAY = 86400          # matches exercise.py's constant (1 tick = 1 sec)
GAME_DURATION_TICKS = 2 * 3600      # a fixture is "in progress" for 2 sim-hours
SEASON_WEEKS = 14

_SCORE_RANGES = {
    "football":   (7, 35),
    "basketball": (85, 125),
    "hockey":     (0, 6),
    "soccer":     (0, 4),
}


def _pro_teams(world, sport):
    defs = world.get("definitions", {})
    teams = defs.get("sports_teams", {})
    return [tid for tid, t in teams.items() if t.get("sport") == sport]


def _local_teams(world, sport):
    league = ensure_local_league(world, sport)
    return list(league.keys())


def _team_strength(world, sport, scope, team_id):
    if scope == "pro":
        return world["definitions"]["sports_teams"][team_id]["strength"]
    return world["local_teams"][sport][team_id]["strength"]


def _fixture_id(sport, scope, week, idx):
    return f"{scope}_{sport}_w{week}_{idx}"


def generate_season_schedule(world, sport, scope):
    """
    Lazily build a season's worth of fixtures for one (sport, scope) pair,
    spread weekly across the sim's own calendar starting a few days out.
    scope is "pro" (real teams) or "local" (invented clubs). Idempotent --
    returns the existing schedule if one was already generated.
    """
    leagues = world.setdefault("sports_leagues", {})
    sport_leagues = leagues.setdefault(sport, {})
    if scope in sport_leagues:
        return sport_leagues[scope]

    team_ids = _pro_teams(world, sport) if scope == "pro" else _local_teams(world, sport)
    standings = {tid: {"wins": 0, "losses": 0, "draws": 0} for tid in team_ids}

    schedule = []
    if len(team_ids) >= 2:
        start_tick = world.get("tick", 0) + 3 * TICKS_PER_GAME_DAY
        for week in range(SEASON_WEEKS):
            pool = team_ids[:]
            random.shuffle(pool)
            week_tick = start_tick + week * 7 * TICKS_PER_GAME_DAY
            for idx in range(len(pool) // 2):
                home, away = pool[2 * idx], pool[2 * idx + 1]
                schedule.append({
                    "id": _fixture_id(sport, scope, week, idx),
                    "sport": sport,
                    "scope": scope,
                    "home": home,
                    "away": away,
                    "scheduled_tick": week_tick,
                    "result": None,
                })

    sport_leagues[scope] = {"schedule": schedule, "standings": standings}
    return sport_leagues[scope]


def get_league(world, sport, scope):
    """Fetch (lazily generating) the schedule/standings for a (sport, scope)."""
    leagues = world.get("sports_leagues", {})
    existing = leagues.get(sport, {}).get(scope)
    if existing is not None:
        return existing
    return generate_season_schedule(world, sport, scope)


def get_fixture(world, sport, scope, fixture_id):
    league = get_league(world, sport, scope)
    for fx in league["schedule"]:
        if fx["id"] == fixture_id:
            return fx
    return None


def simulate_score(world, sport, scope, home_id, away_id):
    """Weighted-random final score from both teams' strength rating."""
    lo, hi = _SCORE_RANGES.get(sport, (0, 10))
    home_str = _team_strength(world, sport, scope, home_id)
    away_str = _team_strength(world, sport, scope, away_id)

    def _roll(strength, opp_strength):
        bias = 1.0 + (strength - opp_strength)
        base = random.uniform(lo, hi) * bias
        return max(lo, min(hi, round(base)))

    home_score = _roll(home_str, away_str)
    away_score = _roll(away_str, home_str)

    if home_score == away_score:
        if sport == "soccer" and random.random() < 0.35:
            pass  # a real draw stands
        else:
            if random.random() < 0.5:
                home_score += 1
            else:
                away_score += 1

    return {"home": home_score, "away": away_score}


def preview_score(world, sport, scope, fixture, frac):
    """A plausible RUNNING score for a still-in-progress fixture, scaled by
    frac (0-1, how far into the scheduled window we are) -- purely for
    on-grid live-broadcast flavor (sports_broadcast.py). The actual result
    everything else (standings, mood, injuries) reacts to always comes from
    simulate_score()/tick_sports_leagues(), never this preview."""
    lo, hi = _SCORE_RANGES.get(sport, (0, 10))
    home_str = _team_strength(world, sport, scope, fixture["home"])
    away_str = _team_strength(world, sport, scope, fixture["away"])

    def _roll(strength, opp_strength):
        bias = 1.0 + (strength - opp_strength)
        return max(0, round(random.uniform(lo, hi) * bias * frac))

    return {"home": _roll(home_str, away_str), "away": _roll(away_str, home_str)}


def _apply_result(league, fixture):
    result = fixture["result"]
    home_standing = league["standings"].setdefault(fixture["home"], {"wins": 0, "losses": 0, "draws": 0})
    away_standing = league["standings"].setdefault(fixture["away"], {"wins": 0, "losses": 0, "draws": 0})

    if result["home"] > result["away"]:
        home_standing["wins"] += 1
        away_standing["losses"] += 1
    elif result["away"] > result["home"]:
        away_standing["wins"] += 1
        home_standing["losses"] += 1
    else:
        home_standing["draws"] += 1
        away_standing["draws"] += 1


def tick_sports_leagues(world):
    """
    Daily-cadence pass: resolve any fixture (pro or local, any sport) whose
    scheduled window has fully closed and doesn't have a result yet. This
    is the single authoritative source of a game's final score -- the
    on-grid live broadcast (sports_broadcast.py) narrates its OWN plausible
    running score during the window for entertainment, but always reports
    THIS result once the window closes.
    """
    tick = world.get("tick", 0)
    leagues = world.get("sports_leagues", {})
    for sport in SPORTS:
        for scope in ("pro", "local"):
            league = leagues.get(sport, {}).get(scope)
            if not league:
                continue
            for fx in league["schedule"]:
                if fx["result"] is not None:
                    continue
                if tick < fx["scheduled_tick"] + GAME_DURATION_TICKS:
                    continue
                fx["result"] = simulate_score(world, sport, scope, fx["home"], fx["away"])
                _apply_result(league, fx)
