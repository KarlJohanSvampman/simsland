"""
systems/sports.py

Sports hobbies: pro-team supporters (real NFL/NBA/NHL/Premier League teams,
see sports_teams in definitions.json) and local-league players (invented
per-simulation clubs, see world["local_teams"]).

Team assignment happens the moment a character picks up a matching
hobby_templates entry (one tagged sports_role="supporter"/"player") --
see sync_sports_hobbies(), called from both character_gen.py's initial
hobby pick and hobbies.py::assign_hobbies()'s runtime path.

Game-day scheduling, season simulation, live broadcast, and rival
conflict are separate modules (sports_leagues.py, sports_broadcast.py) --
this module only owns "which team does this character belong to."
"""

import random
import time

SPORTS = ("football", "basketball", "hockey", "soccer")

# How far ahead (in ticks) schedule_game_day_events() looks for upcoming
# fixtures worth turning into a real social_events entry / attendance plan.
LOOKAHEAD_TICKS = 5 * 86400

OFF_GRID_ATTEND_CHANCE = 0.4        # pro supporter: stadium/bar vs. watch from home
SPECTATOR_OFF_GRID_CHANCE_PRO = 0.5 # household/close contact joining a pro supporter
INJURY_CHANCE_PER_MATCH = 0.12
OFFSCREEN_WIN_STRESS = -2.0
OFFSCREEN_LOSS_STRESS = 4.0
RIVAL_FIGHT_BASE_CHANCE = 0.12

_INJURY_POOL = [
    ("bruise", 0.55),
    ("strained_muscle", 0.30),
    ("fall_fracture", 0.12),
    ("shattered_bone", 0.03),
]

# Invented local-league club name pool, per sport -- deliberately NOT real
# teams (those live in definitions.json's sports_teams registry). A small
# fixed roster generated once per simulation on first need.
_LOCAL_TEAM_NAMES = {
    "football": [
        "Ironside Bulldogs", "Millbrook Hawks", "Cedar Creek Miners",
        "Riverside Sharks", "Granite Point Rattlers",
    ],
    "basketball": [
        "Downtown Comets", "Lakeside Thunder", "Old Mill Ballers",
        "Highland Rebels", "Union Square Sixers",
    ],
    "hockey": [
        "Frostbite Wolves", "Harbor Ice Hawks", "North Ridge Blizzard",
        "Cold Spring Storm", "Pinecrest Icemen",
    ],
    "soccer": [
        "Harborview United", "Elmwood City FC", "Southgate Rovers",
        "Maple Ridge Athletic", "Fairview Town",
    ],
}


def _slug(sport, name):
    return f"local_{sport}_" + name.lower().replace(" ", "_").replace("'", "")


def ensure_local_league(world, sport):
    """Lazily generate world['local_teams'][sport] on first need."""
    local_teams = world.setdefault("local_teams", {})
    if sport in local_teams:
        return local_teams[sport]

    names = _LOCAL_TEAM_NAMES.get(sport, [])
    league = {}
    for name in names:
        tid = _slug(sport, name)
        league[tid] = {
            "name": name,
            "sport": sport,
            "strength": round(random.uniform(0.4, 0.7), 2),
            "roster": [],
        }
    local_teams[sport] = league
    return league


def assign_supporter_team(c, sport, world):
    """
    Pick a real pro team from definitions.json's sports_teams registry for
    this sport (uniform-random -- no "hometown" concept exists anywhere in
    this codebase today, a documented scoping decision, not regionally
    biased). Idempotent: does nothing if already assigned.
    """
    if c.get("supported_teams", {}).get(sport):
        return c["supported_teams"][sport]

    defs = world.get("definitions", {})
    teams = defs.get("sports_teams", {})
    pool = [tid for tid, t in teams.items() if t.get("sport") == sport]
    if not pool:
        return None

    chosen = random.choice(pool)
    c.setdefault("supported_teams", {})[sport] = chosen
    return chosen


def assign_local_team(c, sport, world):
    """
    Assign this player to the local-league club with the smallest current
    roster for this sport (balances participation instead of clumping
    everyone onto one team). Idempotent: does nothing if already assigned.
    """
    if c.get("local_team", {}).get(sport):
        return c["local_team"][sport]

    league = ensure_local_league(world, sport)
    if not league:
        return None

    chosen = min(league.values(), key=lambda t: len(t["roster"]))
    tid = next(tid for tid, t in league.items() if t is chosen)
    chosen["roster"].append(c["id"])
    c.setdefault("local_team", {})[sport] = tid
    return tid


def sync_sports_hobbies(c, world):
    """
    Scan this character's current hobbies for any sports-tagged entry
    (sports_role="supporter"|"player") and assign the matching team if not
    already assigned. Safe to call repeatedly -- both assignment functions
    are idempotent, so this can run on generation AND every time hobbies
    are (re)assigned at runtime without duplicating work.
    """
    defs = world.get("definitions", {})
    hobby_templates = defs.get("hobby_templates", {})
    if not hobby_templates:
        return

    for hid in c.get("hobbies", []):
        tmpl = hobby_templates.get(hid)
        if not tmpl or "sports_role" not in tmpl:
            continue
        sport = tmpl.get("sport")
        if sport not in SPORTS:
            continue
        if tmpl["sports_role"] == "supporter":
            assign_supporter_team(c, sport, world)
        elif tmpl["sports_role"] == "player":
            assign_local_team(c, sport, world)


# ----------------------------------------------------------
# TEAM DISPLAY / CONTACT HELPERS
# ----------------------------------------------------------

def _team_display_name(world, sport, scope, team_id):
    if scope == "pro":
        return world["definitions"]["sports_teams"][team_id]["name"]
    return world["local_teams"][sport][team_id]["name"]


def _household_and_close_contacts(world, char_id):
    """Household members + friendship>50 contacts -- used to find who else
    might tag along to a game day, matching the plan's "household members
    and neighbors" ask without inventing a new social-scan mechanism."""
    c = world.get("characters", {}).get(char_id)
    if not c:
        return []
    out = set()
    hh_id = c.get("household_id")
    if hh_id:
        for other_id, other in world.get("characters", {}).items():
            if other_id != char_id and other.get("household_id") == hh_id:
                out.add(other_id)
    for other_id, rel in c.get("relationships", {}).items():
        if rel.get("friendship", 0) > 50:
            out.add(other_id)
    return list(out)


def _tick_to_ts(world, target_tick):
    """create_event_draft() schedules on real wall-clock epoch seconds, not
    sim ticks -- convert using the same tick-rate/time_scale relationship
    the tick loop itself advances by."""
    delta = target_tick - world.get("tick", 0)
    scale = world.get("time_scale") or 1
    return time.time() + delta / scale


# ----------------------------------------------------------
# GAME-DAY SCHEDULING + ATTENDANCE (Phase D)
# ----------------------------------------------------------

def schedule_game_day_events(world):
    """
    Daily-cadence pass: for every upcoming fixture within LOOKAHEAD_TICKS
    that has real characters caring about it (a supporter or a local-league
    player) and doesn't have an attendance plan yet, build one.
    """
    from systems.sports_leagues import get_league

    tick = world.get("tick", 0)
    leagues = world.get("sports_leagues", {})
    for sport in SPORTS:
        for scope in ("pro", "local"):
            league = leagues.get(sport, {}).get(scope)
            if not league:
                continue
            for fx in league["schedule"]:
                if fx["result"] is not None or "attendees" in fx:
                    continue
                if not (tick <= fx["scheduled_tick"] <= tick + LOOKAHEAD_TICKS):
                    continue
                _plan_fixture_attendance(world, sport, scope, fx)


def _plan_fixture_attendance(world, sport, scope, fx):
    """
    Decide, once per fixture, who's involved and how:
      - local scope: the rostered players always attend (mode "playing"),
        household/close contacts who don't play may tag along as
        spectators -- the user was explicit that local-league games
        "happen off-grid and we only need to generate a summary", so
        EVERYONE here (players and spectators alike) goes off-grid.
      - pro scope: each supporter independently rolls stadium/bar
        (off_grid) vs. watching from a home (on_grid); their household/
        close contacts likewise roll per-person.
    """
    home, away = fx["home"], fx["away"]
    characters = world.get("characters", {})
    key = "supported_teams" if scope == "pro" else "local_team"

    core = [c for c in characters.values() if c.get(key, {}).get(sport) in (home, away)]
    if not core:
        fx["attendees"] = {}
        return

    attendees = {}

    if scope == "local":
        for c in core:
            attendees[c["id"]] = {"mode": "playing", "team": c[key][sport]}
        for c in core:
            for viewer_id in _household_and_close_contacts(world, c["id"]):
                if viewer_id in attendees or viewer_id not in characters:
                    continue
                attendees[viewer_id] = {"mode": "off_grid_spectator", "team": c[key][sport]}
    else:
        for c in core:
            mode = "off_grid" if random.random() < OFF_GRID_ATTEND_CHANCE else "on_grid"
            attendees[c["id"]] = {"mode": mode, "team": c[key][sport]}
        for c in core:
            for viewer_id in _household_and_close_contacts(world, c["id"]):
                if viewer_id in attendees or viewer_id not in characters:
                    continue
                mode = "off_grid" if random.random() < SPECTATOR_OFF_GRID_CHANCE_PRO else "on_grid"
                attendees[viewer_id] = {"mode": mode, "team": c[key][sport]}

    fx["attendees"] = attendees

    off_grid_ids = [cid for cid, a in attendees.items()
                    if a["mode"] in ("playing", "off_grid", "off_grid_spectator")]
    if off_grid_ids:
        from systems.social_events import create_event_draft
        from systems.sports_leagues import GAME_DURATION_TICKS

        home_name = _team_display_name(world, sport, scope, home)
        away_name = _team_display_name(world, sport, scope, away)
        initiator = characters[off_grid_ids[0]]
        evt = create_event_draft(
            initiator, world,
            title=f"{home_name} vs {away_name}",
            category="sports",
            description=f"Game day: {home_name} vs {away_name}.",
            location="stadium" if scope == "pro" else "local sports grounds",
            location_type="stadium" if scope == "pro" else "venue",
            start_ts=_tick_to_ts(world, fx["scheduled_tick"]),
            end_ts=_tick_to_ts(world, fx["scheduled_tick"] + GAME_DURATION_TICKS),
            tags=["game_day", sport, scope, fx["id"], home, away],
        )
        for cid in off_grid_ids[1:]:
            if cid not in evt["invited"]:
                evt["invited"].append(cid)
            evt["attendees"][cid] = "yes"
        fx["event_id"] = evt["id"]


# ----------------------------------------------------------
# KICKOFF (Phase E) -- moves attendees into their game-day mode once the
# fixture's scheduled_tick arrives.
# ----------------------------------------------------------

def kickoff_scheduled_games(world):
    from systems.sports_leagues import GAME_DURATION_TICKS
    from systems.offgrid import send_offgrid

    tick = world.get("tick", 0)
    leagues = world.get("sports_leagues", {})
    characters = world.get("characters", {})

    for sport in SPORTS:
        for scope in ("pro", "local"):
            league = leagues.get(sport, {}).get(scope)
            if not league:
                continue
            for fx in league["schedule"]:
                attendees = fx.get("attendees")
                if not attendees:
                    continue
                if tick < fx["scheduled_tick"] or tick >= fx["scheduled_tick"] + GAME_DURATION_TICKS:
                    continue

                for cid, info in attendees.items():
                    if info.get("started"):
                        continue
                    c = characters.get(cid)
                    if not c:
                        info["started"] = True
                        continue

                    if info["mode"] in ("off_grid", "off_grid_spectator", "playing"):
                        if c.get("off_grid") or c.get("travel_state") or c.get("conversation"):
                            continue
                        reason = "play_local_match" if info["mode"] == "playing" else "attend_game"
                        minutes = max(1, GAME_DURATION_TICKS // 60)
                        if send_offgrid(c, world, reason, minutes):
                            c["_pending_sports_fixture"] = {
                                "sport": sport, "scope": scope, "fixture_id": fx["id"],
                            }
                            info["started"] = True

                    elif info["mode"] == "on_grid":
                        if c.get("activity") or c.get("off_grid") or c.get("conversation"):
                            continue
                        from systems.activities import start_activity
                        if start_activity(c, world, "watch_tv"):
                            c["activity"]["duration"] = GAME_DURATION_TICKS
                            c["activity"]["watching_game"] = {
                                "sport": sport, "scope": scope, "fixture_id": fx["id"],
                            }
                            info["started"] = True


# ----------------------------------------------------------
# OUTCOME RESOLUTION (Phase E/F -- per attendee) -- shared by both the
# off-grid return path (offgrid.py::process_return) and the on-grid
# watch-party completion path (activities.py::complete_activity).
# ----------------------------------------------------------

def resolve_attendee_return(c, world):
    """Called from offgrid.py::process_return() when reason is
    attend_game/play_local_match. Returns a summary suffix string, or None
    if the fixture hasn't resolved yet (shouldn't normally happen since
    the trip duration matches GAME_DURATION_TICKS)."""
    pending = c.pop("_pending_sports_fixture", None)
    if not pending:
        return None
    return _resolve_outcome_for(c, world, pending["sport"], pending["scope"], pending["fixture_id"])


def resolve_watch_party(c, world, watching):
    """Called from activities.py::complete_activity() when a watch_tv
    activity carrying a watching_game tag finishes. watching is the
    {"sport","scope","fixture_id"} dict stamped on the activity at
    kickoff (see kickoff_scheduled_games)."""
    if not watching:
        return None
    return _resolve_outcome_for(c, world, watching["sport"], watching["scope"], watching["fixture_id"])


def _resolve_outcome_for(c, world, sport, scope, fixture_id):
    from systems.sports_leagues import get_fixture

    fx = get_fixture(world, sport, scope, fixture_id)
    if not fx or fx.get("result") is None:
        return None

    result = fx["result"]
    home, away = fx["home"], fx["away"]
    info = fx.get("attendees", {}).get(c["id"], {})
    my_team = info.get("team") or home
    my_score, opp_score = (result["home"], result["away"]) if my_team == home else (result["away"], result["home"])

    home_name = _team_display_name(world, sport, scope, home)
    away_name = _team_display_name(world, sport, scope, away)

    if my_score > opp_score:
        outcome = "win"
    elif my_score < opp_score:
        outcome = "loss"
    else:
        outcome = "draw"

    try:
        from systems.reactions import trigger_reaction
        trigger_reaction(c, world, "impressed" if outcome == "win"
                          else "disapproving" if outcome == "loss" else "look_around")
    except Exception:
        pass

    summary = f"Final score: {home_name} {result['home']} - {result['away']} {away_name}."
    if outcome == "win":
        summary += " Their team won!"
    elif outcome == "loss":
        summary += " Their team lost."
    else:
        summary += " It ended in a draw."

    if info.get("mode") == "playing":
        injury_note = _maybe_injure_player(c, world, sport)
        if injury_note:
            summary += " " + injury_note

    return summary


def _maybe_injure_player(c, world, sport):
    tick = world.get("tick", 0)
    if tick < c.get("sports_injury_cooldown", {}).get(sport, 0):
        return None
    if random.random() > INJURY_CHANCE_PER_MATCH:
        return None

    roll, acc, chosen = random.random(), 0.0, _INJURY_POOL[0][0]
    for key, weight in _INJURY_POOL:
        acc += weight
        if roll <= acc:
            chosen = key
            break

    from systems.health import apply_injury
    apply_injury(c, world, chosen, f"sports_{sport}", tick=tick)
    c.setdefault("sports_injury_cooldown", {})[sport] = tick + random.randint(3, 10) * 86400
    return f"Came away with a {chosen.replace('_', ' ')} from the game."


# ----------------------------------------------------------
# RESULT-APPLICATION BATCH PASS (Phase G) -- off-screen supporter mood +
# rival-supporter conflict. Runs once per newly-resolved fixture.
# ----------------------------------------------------------

def apply_game_day_outcomes(world):
    leagues = world.get("sports_leagues", {})
    for sport in SPORTS:
        for scope in ("pro", "local"):
            league = leagues.get(sport, {}).get(scope)
            if not league:
                continue
            for fx in league["schedule"]:
                if fx["result"] is None or fx.get("outcomes_applied"):
                    continue
                fx["outcomes_applied"] = True
                _apply_offscreen_mood(world, sport, scope, fx)
                _maybe_rival_conflict(world, sport, scope, fx)


def _apply_offscreen_mood(world, sport, scope, fx):
    result = fx["result"]
    home, away = fx["home"], fx["away"]
    attendee_ids = set(fx.get("attendees", {}).keys())
    key = "supported_teams" if scope == "pro" else "local_team"

    for c in world.get("characters", {}).values():
        if c["id"] in attendee_ids:
            continue  # already handled live via resolve_attendee_return/resolve_watch_party
        my_team = c.get(key, {}).get(sport)
        if my_team not in (home, away):
            continue
        my_score, opp_score = (result["home"], result["away"]) if my_team == home else (result["away"], result["home"])
        delta = OFFSCREEN_WIN_STRESS if my_score > opp_score else OFFSCREEN_LOSS_STRESS if my_score < opp_score else 0.0
        if delta:
            c["stress"] = max(0.0, min(100.0, c.get("stress", 0.0) + delta))


def _maybe_rival_conflict(world, sport, scope, fx):
    """Two off-grid attendees of the same game backing opposing sides can
    come to blows -- more likely on a genuine rivalry matchup and right
    after a loss. Local-league rivalry stays friendly for now; pro
    fandom (with real authored rivals lists) is the flashpoint."""
    if scope != "pro":
        return

    result = fx["result"]
    home, away = fx["home"], fx["away"]
    defs = world.get("definitions", {})
    home_rivals = defs.get("sports_teams", {}).get(home, {}).get("rivals", [])
    is_rival_matchup = away in home_rivals

    attendees = fx.get("attendees", {})
    off_grid_home = [cid for cid, a in attendees.items() if a.get("team") == home and a["mode"] == "off_grid"]
    off_grid_away = [cid for cid, a in attendees.items() if a.get("team") == away and a["mode"] == "off_grid"]
    if not off_grid_home or not off_grid_away:
        return

    someone_lost = result["home"] != result["away"]
    characters = world.get("characters", {})

    for hid in off_grid_home:
        for aid in off_grid_away:
            h, a = characters.get(hid), characters.get(aid)
            if not h or not a:
                continue
            chance = RIVAL_FIGHT_BASE_CHANCE
            if is_rival_matchup:
                chance += 0.15
            if someone_lost:
                chance += 0.10
            h_traits = set(h.get("traits", []) + h.get("personality_traits", []))
            a_traits = set(a.get("traits", []) + a.get("personality_traits", []))
            if h_traits & {"aggressive", "hot_tempered"} or a_traits & {"aggressive", "hot_tempered"}:
                chance += 0.15
            if random.random() < chance:
                _escalate_team_rivalry(h, a, world)
                return  # one altercation per fixture is plenty


def _escalate_team_rivalry(char_a, char_b, world):
    from systems.grievances import add_grievance
    from systems.rival_cascade import _fighting_strength

    tick = world.get("tick", 0)

    add_grievance(char_a, char_b["id"], "team_rivalry", world, details={"context": "sports_rivalry"})
    add_grievance(char_b, char_a["id"], "team_rivalry", world, details={"context": "sports_rivalry"})

    a_str, b_str = _fighting_strength(char_a), _fighting_strength(char_b)
    total = a_str + b_str or 1.0
    winner, loser = (char_a, char_b) if random.random() < (a_str / total) else (char_b, char_a)

    add_grievance(loser, winner["id"], "fight_loss_humiliation", world,
                  severity=12.0, details={"context": "sports_rivalry_fight"})

    if random.random() < 0.45:
        from systems.health import add_pain
        add_pain(loser, 20)

    try:
        from systems.reactions import trigger_reaction
        trigger_reaction(winner, world, "angry_verbal")
        trigger_reaction(loser, world, "scared_verbal")
    except Exception:
        pass

    try:
        from core.event_bus import emit
        emit("fight_physical", {
            "parties": [char_a["id"], char_b["id"]],
            "winner": winner["id"], "loser": loser["id"],
            "context": "sports_rivalry", "tick": tick,
        })
    except Exception:
        pass
