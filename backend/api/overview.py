"""
api/overview.py

Read-only "societal overview" endpoints -- one per dashboard the frontend
toolbar will open in a modal (stocks/statistics/crime/politics/budget/
news). Mirrors api/events.py's shape exactly: a plain REST poll, not part
of the WS snapshot/delta protocol, since none of this is spatial/per-
viewport data. Each endpoint is a thin read over systems already built
this round (stock_market.py, socioeconomics.py, politics.py,
government_budget.py, media.py) -- no new computation happens here.
"""

from fastapi import APIRouter

from db import load_world
from core.definitions import load_definitions

router = APIRouter()

_STATISTICS_KEYS = [
    "population", "unemployment_rate", "violent_crime_rate",
    "nonviolent_crime_rate", "poverty_rate", "homeless_pct",
    "health_system_capacity", "health_system_load", "inflation_rate",
    "cost_of_living_index", "median_household_income",
    "high_school_graduation", "college_attendance",
    "republican_pct", "democrat_pct", "independent_pct",
]

_CRIME_KEYS = [
    "violent_crime_rate", "nonviolent_crime_rate",
    "incarceration_per_100k", "crime_solve_rate",
]

_STOCK_HISTORY_LIMIT = 30
_NEWS_LIMIT = 30
_INCIDENTS_LIMIT = 50


@router.get("/overview/stocks")
def get_overview_stocks(sim_id: str = "default"):
    world = load_world(sim_id)
    stocks = world.get("stocks", {})
    tickers = []
    for ticker, s in stocks.items():
        tickers.append({
            "ticker":            ticker,
            "name":              s.get("name", ticker),
            "sector":            s.get("sector"),
            "price":             s.get("price"),
            "change_pct":        s.get("change_pct", 0.0),
            "market_cap":        s.get("market_cap"),
            "num_shares":        s.get("num_shares"),
            "shares_available":  s.get("shares_available"),
            "description":       s.get("description", ""),
            "history":           s.get("history", [])[-_STOCK_HISTORY_LIMIT:],
        })
    tickers.sort(key=lambda t: t["ticker"])
    return {"ok": True, "tick": world.get("tick", 0), "stocks": tickers}


@router.get("/overview/statistics")
def get_overview_statistics(sim_id: str = "default"):
    world = load_world(sim_id)
    defs = load_definitions(sim_id)
    cfg = defs.get("community_stats_config", {})
    env = world.get("environment", {})

    stats = []
    for key in _STATISTICS_KEYS:
        if key not in env:
            continue
        meta = cfg.get(key, {})
        stats.append({
            "key":   key,
            "label": meta.get("label", key.replace("_", " ").title()),
            "value": env.get(key),
            "unit":  meta.get("unit", ""),
        })
    return {"ok": True, "tick": world.get("tick", 0), "statistics": stats}


@router.get("/overview/crime")
def get_overview_crime(sim_id: str = "default"):
    world = load_world(sim_id)
    env = world.get("environment", {})
    rates = {k: env.get(k) for k in _CRIME_KEYS if k in env}

    incidents = world.get("incidents", [])[-_INCIDENTS_LIMIT:]
    by_type = {}
    for inc in incidents:
        itype = inc.get("type", "unknown")
        by_type[itype] = by_type.get(itype, 0) + 1

    return {
        "ok": True,
        "tick": world.get("tick", 0),
        "rates": rates,
        "recent_incidents_by_type": by_type,
        "recent_incident_count": len(incidents),
    }


@router.get("/overview/politics")
def get_overview_politics(sim_id: str = "default"):
    world = load_world(sim_id)
    election = world.get("election", {})
    factions = world.get("factions", {})
    faction_standings = [
        {"id": fid, "name": f.get("name", fid), "member_count": len(f.get("members", [])),
         "agenda": f.get("agenda", [])}
        for fid, f in factions.items()
    ]
    legislation = sorted(world.get("legislation", []), key=lambda b: b.get("vote_tick", 0))

    return {
        "ok": True,
        "tick": world.get("tick", 0),
        "election": election,
        "factions": faction_standings,
        "legislation": legislation,
    }


@router.get("/overview/budget")
def get_overview_budget(sim_id: str = "default"):
    world = load_world(sim_id)
    gov = world.get("government", {})
    return {
        "ok": True,
        "tick": world.get("tick", 0),
        "treasury": gov.get("treasury", 0.0),
        "spending_categories": gov.get("spending_categories", {}),
    }


@router.get("/overview/news")
def get_overview_news(sim_id: str = "default", limit: int = _NEWS_LIMIT):
    world = load_world(sim_id)
    news = list(reversed(world.get("news", [])[-limit:]))  # newest-first
    return {"ok": True, "tick": world.get("tick", 0), "news": news}
