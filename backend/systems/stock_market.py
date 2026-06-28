import random
import math
from data.stocks import STOCK_CATALOG, STOCKS_BY_TICKER

# =========================================================
# SECTOR ↔ NEWS TAG MAPPING
# News items have tags; these determine which sectors react
# =========================================================

SECTOR_TAGS = {
    "tech":       ["technology", "ai", "regulation", "cyber", "innovation", "trade"],
    "energy":     ["energy", "environment", "climate", "infrastructure", "oil"],
    "health":     ["health", "pharma", "biotech", "regulation"],
    "finance":    ["finance", "economy", "tax", "banking", "corruption"],
    "retail":     ["consumer", "economy", "trade", "labor"],
    "consumer":   ["consumer", "entertainment", "auto", "trade", "labor"],
    "media":      ["media", "free_press", "censorship", "technology", "regulation"],
    "industrial": ["infrastructure", "construction", "labor", "environment", "trade"],
}

# Slow sector trend: small persistent drift per update, reverting to 0
SECTOR_TREND_VOLATILITY = 0.0005
SECTOR_TREND_MAX        = 0.003
SECTOR_TREND_REVERSION  = 0.1   # how fast trend decays back to 0


# =========================================================
# INIT STOCKS
# Populates world["stocks"] from catalog
# =========================================================

def init_stocks(world):
    stocks = world.setdefault("stocks", {})
    sector_trends = world.setdefault("stock_sector_trends", {})

    for s in STOCK_CATALOG:
        ticker = s["ticker"]
        if ticker not in stocks:
            stocks[ticker] = {
                "name":             s["name"],
                "sector":           s["sector"],
                "price":            float(s["base_price"]),
                "base_price":       float(s["base_price"]),
                "open_price":       float(s["base_price"]),
                "history":          [],
                "volatility":       s["volatility"],
                "market_cap":       s["market_cap"],
                "news_sensitivity": s["news_sensitivity"],
                "description":      s["description"],
                "change_pct":       0.0,
            }

    for sector in SECTOR_TAGS:
        sector_trends.setdefault(sector, 0.0)


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
    for sector in SECTOR_TAGS:
        sector_trends.setdefault(sector, 0.0)

    # 1. Evolve sector trends (slow random walk with reversion to 0)
    for sector in SECTOR_TAGS:
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

        # History: keep last 60 entries
        stock["history"].append(round(new_price, 2))
        if len(stock["history"]) > 60:
            stock["history"] = stock["history"][-60:]


def _calc_news_effect(stock, recent_news):
    """Sum news effects from recent items that match this stock's sector."""
    sector     = stock["sector"]
    sensitivity = stock["news_sensitivity"]
    relevant_tags = set(SECTOR_TAGS.get(sector, []))
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
