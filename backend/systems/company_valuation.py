"""
systems/company_valuation.py

Deterministic (rule-based, not hand-authored) derivation of a stock
profile for a real company_templates entry -- mirrors job_complexity.py
::classify_job()'s shape: read existing, already-authored fields
(max_staff, industry) rather than requiring a big manual content-
authoring pass over all 57 companies.

Market cap scales off max_staff (a real, already-authored size signal;
the handful of subscription-style companies with no staff count --
insurance/ISP/telecom/streaming -- default to a flat mid-size
assumption). Share count is picked from a tier keyed to that same size,
smaller companies getting fewer/pricier shares and larger companies
more/cheaper ones -- price = market_cap / num_shares, so "the less
shares, the more expensive each share is" falls out of one formula
rather than being tuned independently. The tradeable float
(shares_available) is a smaller fraction of num_shares for small,
closely-held companies and a larger fraction for big ones -- a thin
float is what actually makes a small company hard to accumulate more
than a few shares of (see systems/investments.py::buy_stock).
"""

import random

DEFAULT_STAFF_FOR_UNSTAFFED = 30  # insurance/ISP/telecom/streaming-style companies with no max_staff

VALUE_PER_EMPLOYEE = 400_000  # tunable -- a rough "what's this company worth per employee" constant

# Real news tags actually produced by data/public_figures.py (confirmed
# via extraction -- the OLD SECTOR_TAGS table in stock_market.py used a
# tag vocabulary, "technology"/"health"/"finance"/..., that never once
# matched anything actually generated, so the news-effect on stock price
# had never fired for any stock, ever. This table uses the real,
# confirmed-generated tags instead. Industries with no natural mapping
# (technology, healthcare, education, construction, ...) intentionally
# get no tags -- not everything needs to react to political/celebrity
# news, same as real life.
INDUSTRY_NEWS_TAGS = {
    "finance":       ["pro_business", "lowered_taxes", "anti_corruption"],
    "insurance":     ["pro_business", "lowered_taxes"],
    "retail":        ["celebrity", "fashion", "pro_business"],
    "entertainment": ["celebrity", "fashion", "charity"],
    "adult_entertainment": ["celebrity"],
    "security":      ["crime_crackdown", "law_order", "security"],
    "government":    ["politician", "anti_welfare", "pro_business"],
    "personal_services": ["celebrity", "charity"],
    "food_and_drink":    ["charity"],
    "legal":         ["anti_corruption", "investigative", "critical"],
    "criminal":      ["crime_crackdown", "law_order"],
}

_VOLATILE_INDUSTRIES = {"technology", "finance", "entertainment", "adult_entertainment", "criminal"}

# Excluded from public trading entirely -- see crime.py for why illegal
# orgs aren't publicly traded corporations; "government" is a revenue
# office, not a company.
NOT_PUBLICLY_TRADED = {"illegal", "government_office"}


def is_publicly_tradable(template_key, tmpl):
    if tmpl.get("illegal"):
        return False
    if template_key == "government":
        return False
    return True


def derive_stock_profile(template_key, tmpl):
    """Returns a dict ready to seed world["stocks"][template_key]."""
    max_staff = tmpl.get("max_staff") or DEFAULT_STAFF_FOR_UNSTAFFED
    industry = (tmpl.get("industry") or "").lower()

    market_cap = max_staff * VALUE_PER_EMPLOYEE

    if max_staff <= 10:
        num_shares = random.randint(5_000, 50_000)
        float_fraction = random.uniform(0.05, 0.15)
    elif max_staff <= 30:
        num_shares = random.randint(50_000, 500_000)
        float_fraction = random.uniform(0.15, 0.30)
    elif max_staff <= 60:
        num_shares = random.randint(500_000, 3_000_000)
        float_fraction = random.uniform(0.30, 0.45)
    else:
        num_shares = random.randint(3_000_000, 20_000_000)
        float_fraction = random.uniform(0.45, 0.65)

    starting_price = round(max(0.5, market_cap / num_shares), 2)
    shares_available = int(num_shares * float_fraction)

    return {
        "name":             tmpl.get("name", template_key),
        "sector":           industry,
        "price":            starting_price,
        "base_price":       starting_price,
        "open_price":       starting_price,
        "history":          [],
        "volatility":       0.025 if industry in _VOLATILE_INDUSTRIES else 0.012,
        "market_cap":       market_cap,
        "news_sensitivity": 0.8 if industry in INDUSTRY_NEWS_TAGS else 0.2,
        "description":      tmpl.get("description", ""),
        "change_pct":       0.0,
        "num_shares":       num_shares,
        "shares_available": shares_available,
        "shares_available_baseline": shares_available,
    }
