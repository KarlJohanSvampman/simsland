"""
Investment system — sims buy/sell stocks via computer or phone.

Portfolio structure on character:
  c["portfolio"] = {
      "NXVT": {"shares": 10, "avg_buy_price": 142.50}
  }
  c["watched_stocks"]   = ["NXVT", "CYLX"]   # tickers they follow
  c["last_stock_check"] = 0                   # world tick of last check
"""

import random
from systems.stock_market import (
    get_stock_price,
    get_stock_change,
)
from systems.company_valuation import INDUSTRY_NEWS_TAGS

# =========================================================
# CONFIG
# =========================================================

# Minimum spare wealth before a sim considers investing
MIN_INVESTABLE_WEALTH  = 500
# Max fraction of wealth to spend in one buy
MAX_BUY_FRACTION       = 0.15
# Profit % that triggers "maybe sell"
TAKE_PROFIT_THRESHOLD  = 0.25
# Loss % that triggers panic sell
STOP_LOSS_THRESHOLD    = -0.18
# News-triggered re-check probability per bad news item
NEWS_RECHECK_PROB      = 0.40
# Base prob of checking portfolio each SLOW tick (if they own stocks)
BASE_CHECK_PROB        = 0.30
# Max stocks in a watched list
MAX_WATCHED            = 6

# Share supply: below this shares_available/num_shares ratio, the next
# purchase pays a real premium -- what makes a thin-float company genuinely
# hard to accumulate more than a few shares of.
SCARCITY_FLOAT_THRESHOLD = 0.15
SCARCITY_PREMIUM_PER_PCT = 0.02   # extra price % per 1pt the float sits below threshold


# =========================================================
# ACCESS CHECK — does this character have a computer/phone?
# =========================================================

def _has_trading_device(c, world):
    hid = c.get("household_id")
    if not hid:
        return False
    h = world.get("households", {}).get(hid, {})
    for resource in h.get("storage", {}).get("resources", []):
        rt = resource.get("resource_type", "")
        if rt in ("COMPUTER", "PHONE", "SMARTPHONE", "LAPTOP"):
            return True
        obj = resource.get("object_type", "")
        if obj in ("computer", "phone", "smartphone", "laptop"):
            return True
    return False


# =========================================================
# BUY STOCK
# =========================================================

def _apply_scarcity_pricing(stock):
    """Below SCARCITY_FLOAT_THRESHOLD float, the NEXT purchase pays a real
    premium -- this is what actually makes a thin float hard to accumulate
    more than a few shares of, on top of the buy being capped outright."""
    num_shares = stock.get("num_shares", 0)
    if not num_shares:
        return
    float_ratio = stock.get("shares_available", 0) / num_shares
    if float_ratio >= SCARCITY_FLOAT_THRESHOLD:
        return
    shortfall_pct = (SCARCITY_FLOAT_THRESHOLD - float_ratio) * 100
    premium = 1 + shortfall_pct * SCARCITY_PREMIUM_PER_PCT
    stock["price"] = round(stock["price"] * premium, 2)


def buy_stock(c, world, ticker, cash_amount):
    """
    Spend up to cash_amount buying shares of ticker.
    Deducts from c["money"]. Returns shares purchased (0 on failure).

    Capped at the stock's real, finite shares_available float -- a request
    for more than what's currently tradeable either partial-fills (buys
    whatever's left) or fails outright if the float is already exhausted.
    """
    stock = world.get("stocks", {}).get(ticker)
    price = get_stock_price(world, ticker)
    if not stock or not price or price <= 0:
        return 0

    affordable = min(cash_amount, c.get("money", 0))
    if affordable < price:
        return 0

    desired_shares = int(affordable // price)
    if desired_shares == 0:
        return 0

    shares_available = stock.get("shares_available", 0)
    shares = min(desired_shares, shares_available)
    if shares == 0:
        return 0

    cost = round(shares * price, 2)
    c["money"] = round(c.get("money", 0) - cost, 2)

    portfolio = c.setdefault("portfolio", {})
    if ticker in portfolio:
        existing_shares = portfolio[ticker]["shares"]
        existing_avg    = portfolio[ticker]["avg_buy_price"]
        total_shares    = existing_shares + shares
        new_avg = (existing_avg * existing_shares + price * shares) / total_shares
        portfolio[ticker]["shares"]        = total_shares
        portfolio[ticker]["avg_buy_price"] = round(new_avg, 2)
    else:
        portfolio[ticker] = {
            "shares":        shares,
            "avg_buy_price": round(price, 2),
        }

    stock["shares_available"] = max(0, shares_available - shares)
    _apply_scarcity_pricing(stock)

    # Add to watched list
    watched = c.setdefault("watched_stocks", [])
    if ticker not in watched:
        watched.append(ticker)
        if len(watched) > MAX_WATCHED:
            watched.pop(0)

    return shares


# =========================================================
# SELL STOCK
# =========================================================

def sell_stock(c, world, ticker, shares=None):
    """
    Sell `shares` of ticker (None = sell all).
    Credits c["money"]. Returns cash received (0 on failure).
    """
    portfolio = c.get("portfolio", {})
    if ticker not in portfolio:
        return 0

    held = portfolio[ticker]["shares"]
    sell_qty = held if shares is None else min(shares, held)
    if sell_qty <= 0:
        return 0

    price  = get_stock_price(world, ticker)
    if not price:
        return 0

    proceeds = round(sell_qty * price, 2)
    c["money"] = round(c.get("money", 0) + proceeds, 2)

    remaining = held - sell_qty
    if remaining <= 0:
        del portfolio[ticker]
    else:
        portfolio[ticker]["shares"] = remaining

    stock = world.get("stocks", {}).get(ticker)
    if stock:
        num_shares = stock.get("num_shares")
        new_available = stock.get("shares_available", 0) + sell_qty
        stock["shares_available"] = min(num_shares, new_available) if num_shares else new_available

    return proceeds


# =========================================================
# PORTFOLIO VALUE
# =========================================================

def portfolio_value(c, world):
    total = 0.0
    for ticker, pos in c.get("portfolio", {}).items():
        price = get_stock_price(world, ticker) or pos["avg_buy_price"]
        total += price * pos["shares"]
    return round(total, 2)


def position_pnl(c, world, ticker):
    """Return (unrealised_gain, pct) for a single position."""
    pos   = c.get("portfolio", {}).get(ticker)
    if not pos:
        return 0.0, 0.0
    price = get_stock_price(world, ticker) or pos["avg_buy_price"]
    gain  = (price - pos["avg_buy_price"]) * pos["shares"]
    pct   = (price - pos["avg_buy_price"]) / pos["avg_buy_price"]
    return round(gain, 2), round(pct, 4)


# =========================================================
# DISCOVER STOCKS FROM NEWS
# Sims pick up ticker interest from news they consume
# =========================================================

def _discover_stocks_from_news(c, world):
    recent_news = world.get("news", [])[-5:]
    tag_to_sector = {}
    for sector, tags in INDUSTRY_NEWS_TAGS.items():
        for t in tags:
            tag_to_sector[t] = sector

    watched = c.setdefault("watched_stocks", [])
    stocks = world.get("stocks", {})
    for news in recent_news:
        for tag in news.get("tags", []):
            sector = tag_to_sector.get(tag)
            if not sector:
                continue
            candidates = [
                ticker for ticker, s in stocks.items()
                if s.get("sector") == sector and ticker not in watched
            ]
            if candidates and random.random() < 0.25:
                pick = random.choice(candidates)
                watched.append(pick)
                if len(watched) > MAX_WATCHED:
                    watched.pop(0)


# =========================================================
# NEWS-TRIGGERED URGENCY CHECK
# =========================================================

def _news_hit_portfolio(c, world):
    """
    Returns True if recent news affects a sector this sim holds stock in.
    """
    portfolio = c.get("portfolio", {})
    if not portfolio:
        return False

    held_sectors = set()
    for ticker in portfolio:
        s = world.get("stocks", {}).get(ticker, {})
        held_sectors.add(s.get("sector", ""))

    recent_news = world.get("news", [])[-5:]
    tag_to_sector = {}
    for sector, tags in INDUSTRY_NEWS_TAGS.items():
        for t in tags:
            tag_to_sector[t] = sector

    for news in recent_news:
        for tag in news.get("tags", []):
            if tag_to_sector.get(tag) in held_sectors:
                return True
    return False


# =========================================================
# SELL DECISIONS
# =========================================================

def _consider_selling(c, world):
    portfolio = c.get("portfolio", {})
    to_sell = []

    for ticker, pos in list(portfolio.items()):
        _, pct = position_pnl(c, world, ticker)
        change = get_stock_change(world, ticker)

        # Take-profit
        if pct >= TAKE_PROFIT_THRESHOLD and random.random() < 0.6:
            to_sell.append((ticker, None, "take_profit"))
        # Stop-loss
        elif pct <= STOP_LOSS_THRESHOLD and random.random() < 0.7:
            to_sell.append((ticker, None, "stop_loss"))
        # Panic sell on big single-tick drop
        elif change <= -5.0 and random.random() < 0.5:
            to_sell.append((ticker, None, "panic"))
        # Partial profit-taking
        elif pct >= 0.12 and random.random() < 0.25:
            partial = max(1, pos["shares"] // 2)
            to_sell.append((ticker, partial, "partial_profit"))

    for ticker, shares, reason in to_sell:
        sell_stock(c, world, ticker, shares)


# =========================================================
# BUY DECISIONS
# =========================================================

def _consider_buying(c, world):
    money = c.get("money", 0)
    if money < MIN_INVESTABLE_WEALTH:
        return

    budget = money * MAX_BUY_FRACTION
    watched = c.get("watched_stocks", [])

    # Also scan top movers for opportunistic buys
    from systems.stock_market import top_movers
    movers = [m["ticker"] for m in top_movers(world, 5)]
    candidates = list(set(watched + movers))
    random.shuffle(candidates)

    for ticker in candidates[:3]:
        stock = world.get("stocks", {}).get(ticker)
        if not stock:
            continue
        change = stock.get("change_pct", 0)
        price  = stock["price"]
        if price > budget:
            continue

        # Buy if trending up or we already hold it and it dipped slightly
        held = ticker in c.get("portfolio", {})
        if change > 1.5 and random.random() < 0.4:
            buy_stock(c, world, ticker, budget * random.uniform(0.4, 1.0))
            break
        elif held and -3 < change < 0 and random.random() < 0.3:
            # Buy the dip
            buy_stock(c, world, ticker, budget * random.uniform(0.3, 0.6))
            break
        elif not held and change > 0.5 and random.random() < 0.2:
            buy_stock(c, world, ticker, budget * random.uniform(0.3, 0.8))
            break


# =========================================================
# MAIN BEHAVIOR TICK — call per-character on SLOW cadence
# =========================================================

def update_investment_behavior(c, world):
    """
    Called on SLOW cadence. Sims with a computer or phone may:
    - Discover stocks from news
    - Check portfolio value
    - Sell positions that hit profit/loss thresholds
    - Buy new positions in watched stocks
    """
    # Require trading device
    if not _has_trading_device(c, world):
        return

    portfolio = c.get("portfolio", {})
    has_news_hit = _news_hit_portfolio(c, world)

    # Decide whether to check at all this tick
    check_prob = BASE_CHECK_PROB
    if portfolio:
        check_prob += 0.20               # more attentive if they own stocks
    if has_news_hit:
        check_prob += NEWS_RECHECK_PROB  # news makes them check sooner

    if random.random() > check_prob:
        return

    c["last_stock_check"] = world.get("tick", 0)

    # Step 1: Discover new stocks from news
    if random.random() < 0.4:
        _discover_stocks_from_news(c, world)

    # Step 2: Evaluate existing positions
    if portfolio:
        _consider_selling(c, world)

    # Step 3: Maybe buy something
    if random.random() < 0.5:
        _consider_buying(c, world)
