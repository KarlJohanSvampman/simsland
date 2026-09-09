import random
import math

from systems.company_valuation import (
    derive_stock_profile,
    is_publicly_tradable,
    INDUSTRY_NEWS_TAGS,
)

# Slow sector trend: small persistent drift per update, reverting to 0
SECTOR_TREND_VOLATILITY = 0.0005
SECTOR_TREND_MAX        = 0.003
SECTOR_TREND_REVERSION  = 0.1   # how fast trend decays back to 0

# History entries are now {"tick": int, "price": float} instead of a bare
# float, so the dashboard can plot a real time axis -- window widened from
# 60 since entries can be down-sampled for a sparkline rather than needing
# every single tick.
MAX_HISTORY_ENTRIES = 200

# Per-tick fraction of the gap back toward shares_available_baseline that
# recovers on its own (see update_stocks()) -- see investments.py for the
# buy/sell side of the share-supply mechanic this feeds.
FLOAT_RECOVERY_FRACTION = 0.002


# =========================================================
# INIT STOCKS
# Populates world["stocks"] from the real, already-authored
# company_templates registry (54 of 57 -- the 2 illegal orgs and the
# government revenue office aren't publicly traded corporations) via
# company_valuation.py::derive_stock_profile(), replacing the old
# disconnected 40-fictional-company data/stocks.py catalog.
# =========================================================

def init_stocks(world):
    stocks = world.setdefault("stocks", {})
    sector_trends = world.setdefault("stock_sector_trends", {})

    defs = world.get("definitions")
    if not defs:
        from core.definitions import load_definitions
        defs = load_definitions(world.get("sim_id", "default"))

    for key, tmpl in defs.get("company_templates", {}).items():
        if not is_publicly_tradable(key, tmpl):
            continue
        if key in stocks:
            continue
        profile = derive_stock_profile(key, tmpl)
        stocks[key] = profile
        sector_trends.setdefault(profile["sector"], 0.0)


# =========================================================
# UPDATE STOCKS
# Called each MEDIUM tick (~every 20 seconds sim time)
# =========================================================

def update_stocks(world):
    stocks = world.get("stocks", {})
    if not stocks:
        init_stocks(world)
        stocks = world["stocks"]

    sector_trends = world.setdefault("stock_sector_trends", {})
    # Industries are now real, free-form strings pulled from company_
    # templates rather than a fixed 8-bucket table -- trend for whatever
    # sectors actually exist among the seeded stocks (init_stocks() already
    # setdefaults one entry per real sector as each stock is created).
    for stock in stocks.values():
        sector_trends.setdefault(stock["sector"], 0.0)

    # 1. Evolve sector trends (slow random walk with reversion to 0)
    for sector in list(sector_trends.keys()):
        step = random.gauss(0, SECTOR_TREND_VOLATILITY)
        trend = sector_trends[sector] * (1 - SECTOR_TREND_REVERSION) + step
        sector_trends[sector] = max(-SECTOR_TREND_MAX, min(SECTOR_TREND_MAX, trend))

    # 2. Update each stock
    recent_news = world.get("news", [])[-10:]
    for ticker, stock in stocks.items():
        sector   = stock["sector"]
        vol      = stock["volatility"]
        old_price = stock["price"]

        # Random walk + sector drift
        noise     = random.gauss(0, vol)
        drift     = sector_trends.get(sector, 0.0)
        # Weak mean reversion toward base_price
        base      = stock["base_price"]
        reversion = -0.001 * math.log(max(0.01, old_price / base))

        new_price = old_price * (1 + noise + drift + reversion)

        # News spike: scan recent news for matching sector tags
        news_effect = _calc_news_effect(stock, recent_news)
        new_price *= (1 + news_effect)

        # Floor: can't go below 5% of base
        new_price = max(base * 0.05, new_price)

        stock["open_price"] = old_price
        stock["price"]      = round(new_price, 2)
        stock["change_pct"] = round((new_price - old_price) / old_price * 100, 2)

        # History: real {tick, price} pairs so the dashboard can plot an
        # actual time axis, not just "last N ticks".
        stock["history"].append({"tick": world.get("tick", 0), "price": round(new_price, 2)})
        if len(stock["history"]) > MAX_HISTORY_ENTRIES:
            stock["history"] = stock["history"][-MAX_HISTORY_ENTRIES:]

        # Float recovery: a thin float bought out by investments.py::
        # buy_stock() drifts back up a small fraction of the way toward its
        # starting size each tick -- other holders occasionally deciding to
        # sell -- so it isn't permanently locked at zero once bought out.
        baseline = stock.get("shares_available_baseline")
        if baseline is not None:
            current = stock.get("shares_available", 0)
            if current < baseline:
                stock["shares_available"] = min(baseline, current + (baseline - current) * FLOAT_RECOVERY_FRACTION)


def _calc_news_effect(stock, recent_news):
    """Sum news effects from recent items that match this stock's sector."""
    sector     = stock["sector"]
    sensitivity = stock["news_sensitivity"]
    relevant_tags = set(INDUSTRY_NEWS_TAGS.get(sector, []))
    effect = 0.0
    for news in recent_news:
        overlap = relevant_tags & set(news.get("tags", []))
        if not overlap:
            continue
        sentiment  = news.get("sentiment", "neutral")
        intensity  = float(news.get("intensity", 0.3))
        direction  = 1.0 if sentiment == "positive" else -1.0 if sentiment == "negative" else 0.0
        # Scale: high-sensitivity stock, strong news → bigger spike
        effect += direction * intensity * sensitivity * 0.015
    # Cap per-tick news effect at ±8%
    return max(-0.08, min(0.08, effect))


# =========================================================
# HELPERS
# =========================================================

def get_stock_price(world, ticker):
    return world.get("stocks", {}).get(ticker, {}).get("price")

def get_stock_change(world, ticker):
    return world.get("stocks", {}).get(ticker, {}).get("change_pct", 0.0)

def top_movers(world, n=5):
    """Return n stocks sorted by absolute % change this tick."""
    stocks = world.get("stocks", {})
    return sorted(
        [{"ticker": t, **s} for t, s in stocks.items()],
        key=lambda x: abs(x.get("change_pct", 0)),
        reverse=True
    )[:n]

def sector_performance(world):
    """Average change_pct per sector."""
    from collections import defaultdict
    totals = defaultdict(list)
    for s in world.get("stocks", {}).values():
        totals[s["sector"]].append(s.get("change_pct", 0))
    return {sec: round(sum(v)/len(v), 3) for sec, v in totals.items()}
