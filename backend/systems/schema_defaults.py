# =========================================================
# WORLD DEFAULTS
# =========================================================

def ensure_world_defaults(world):

    # =====================================================
    # CORE
    # =====================================================

    world.setdefault(
        "tick",
        0
    )

    world.setdefault(
        "characters",
        {}
    )

    world.setdefault(
        "households",
        {}
    )

    world.setdefault(
        "homes",
        {}
    )

    world.setdefault(
        "vacant_homes",
        []
    )

    world.setdefault(
        "events",
        []
    )

    # =====================================================
    # ENVIRONMENT
    # =====================================================

    env = world.setdefault(
        "environment",
        {}
    )

    env.setdefault(
        "unemployment_rate",
        0.1
    )

    env.setdefault(
        "inflation",
        0.02
    )

    env.setdefault(
        "crime_rate",
        0.05
    )

    env.setdefault(
        "housing_pressure",
        0.3
    )

    env.setdefault(
        "cost_of_living_index",
        1.0
    )

    env.setdefault(
        "tax_rate",
        0.2
    )

    env.setdefault(
        "power_cost_index",
        1.0
    )

    # =====================================================
    # MARKET
    # =====================================================

    market = world.setdefault(
        "market",
        {}
    )

    ensure_market_defaults(
        market
    )

    # =====================================================
    # POLITICS
    # =====================================================

    election = world.setdefault(
        "election",
        {}
    )

    election.setdefault(
        "active",
        False
    )

    election.setdefault(
        "campaign_active",
        False
    )

    election.setdefault(
        "campaign_start_tick",
        420
    )

    election.setdefault(
        "next_tick",
        500
    )

    election.setdefault(
        "days_until_election",
        120
    )

    election.setdefault(
        "candidates",
        []
    )

    election.setdefault(
        "votes",
        {}
    )

    # =====================================================
    # SERVICES
    # =====================================================

    world.setdefault(
        "service_vehicles",
        []
    )

    world.setdefault(
        "deliveries",
        []
    )

    world.setdefault(
        "mail",
        []
    )

    world.setdefault(
        "packages",
        []
    )

    # =====================================================
    # TRAFFIC
    # =====================================================

    world.setdefault(
        "ambient_traffic",
        []
    )

    world.setdefault(
        "traffic_vehicles",
        []
    )

    # =====================================================
    # JOBS
    # =====================================================

    world.setdefault(
        "job_listings",
        []
    )

    world.setdefault(
        "job_applications",
        []
    )

    # =====================================================
    # MAP
    # =====================================================

    world.setdefault(
        "world_tiles",
        []
    )

    world.setdefault(
        "world_tile_lookup",
        {}
    )

    world.setdefault(
        "road_network",
        {}
    )

    world.setdefault(
        "outdoor_navigation",
        {}
    )

    # =====================================================
    # NEIGHBORHOODS
    # =====================================================

    world.setdefault(
        "neighborhoods",
        {
            "n1": {
                "quality": 0.5,
                "cost": 500
            }
        }
    )

    # =====================================================
    # CHARACTERS
    # =====================================================

    for c in world[
        "characters"
    ].values():

        ensure_character_defaults(
            c
        )

    # =====================================================
    # HOUSEHOLDS
    # =====================================================

    for h in world[
        "households"
    ].values():

        ensure_household_defaults(
            h
        )
    # =====================================================
    # MEDIA
    # =====================================================
    world.setdefault(
        "media",
        [
            {
                "id": "daily_times",
                "name": "Daily Times",
                "bias": "centrist",
                "credibility": 0.7,
                "sensationalism": 0.4
            },

            {
                "id": "metro_news",
                "name": "Metro News",
                "bias": "populist",
                "credibility": 0.5,
                "sensationalism": 0.8
            },

            {
                "id": "public_radio",
                "name": "Public Radio",
                "bias": "neutral",
                "credibility": 0.9,
                "sensationalism": 0.1
            }
        ]
    )
    world.setdefault(
        "news_feed",
        []
    )
# =========================================================
# MARKET DEFAULTS
# =========================================================

def ensure_market_defaults(market):

    defaults = {

        "food": 10.0,

        "medicine": 25.0,

        "housing": 1000.0,

        "electronics": 500.0,

        "furniture": 200.0,

        "clothing": 50.0,

        "fuel": 5.0,

        "utilities": 100.0
    }

    for key, price in defaults.items():

        item = market.setdefault(
            key,
            {}
        )

        item.setdefault(
            "price",
            price
        )

        item.setdefault(
            "supply",
            1.0
        )

        item.setdefault(
            "demand",
            1.0
        )


# =========================================================
# CHARACTER DEFAULTS
# =========================================================

def ensure_character_defaults(c):

    c.setdefault(
        "household_id",
        None
    )

    c.setdefault(
        "wealth",
        100
    )

    c.setdefault(
        "money",
        100
    )

    c.setdefault(
        "employed",
        False
    )

    c.setdefault(
        "job_searching",
        False
    )

    c.setdefault(
        "ses",
        0.5
    )

    c.setdefault(
        "mobility_score",
        0
    )

    c.setdefault(
        "relationships",
        {}
    )

    c.setdefault(
        "social_models",
        {}
    )

    c.setdefault(
        "memories",
        []
    )

    c.setdefault(
        "conversation_memory",
        []
    )

    c.setdefault(
        "pending_reflections",
        []
    )

    c.setdefault(
        "recent_perception_memory",
        []
    )

    c.setdefault(
        "intentions",
        []
    )

    c.setdefault(
        "activity",
        None
    )

    legal = c.setdefault(
        "legal",
        {}
    )

    legal.setdefault(
        "status",
        "free"
    )

    legal.setdefault(
        "jail_until",
        None
    )

    legal.setdefault(
        "record",
        []
    )
    # =====================================================
    # HEALTH
    # =====================================================

    health = c.setdefault(
        "health",
        {}
    )

    health.setdefault(
        "conditions",
        []
    )

    health.setdefault(
        "stress",
        0.0
    )

    health.setdefault(
        "energy",
        1.0
    )

    health.setdefault(
        "hunger",
        0.0
    )

    health.setdefault(
        "hydration",
        1.0
    )

    health.setdefault(
        "hygiene",
        1.0
    )

    health.setdefault(
        "bladder",
        0.0
    )

    health.setdefault(
        "fatigue",
        0.0
    )

    health.setdefault(
        "sick",
        False
    )

    health.setdefault(
        "pain",
        0.0
    )

    c.setdefault(
        "attention",
        {
            "focus": None,
            "history": [],
            "salience": {},
            "last_update": 0
        }
    )

# =========================================================
# HOUSEHOLD DEFAULTS
# =========================================================

def ensure_household_defaults(h):

    h.setdefault(
        "members",
        []
    )

    h.setdefault(
        "shared_funds",
        0
    )

    h.setdefault(
        "wealth",
        0
    )

    h.setdefault(
        "bills_due",
        []
    )

    h.setdefault(
        "storage",
        {
            "resources": []
        }
    )

    h.setdefault(
        "owned_objects",
        []
    )

    h.setdefault(
        "cleanliness",
        1.0
    )

    h.setdefault(
        "trash_level",
        0.0
    )

    h.setdefault(
        "home_id",
        None
    )

    h.setdefault(
        "housing_stress",
        0.0
    )

    h.setdefault("mailbox", {
        "has_mail": False,
        "items": [],
        "unopened_count": 0
    })

    h.setdefault("unopened_mail", [])
    h.setdefault("unpaid_bills", [])
    h.setdefault("pending_responses", [])
    h.setdefault("completed_documents", [])