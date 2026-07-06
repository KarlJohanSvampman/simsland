# =========================================================
# WORLD DEFAULTS
# =========================================================

def ensure_world_defaults(world, defs=None):
    # Init community stats from definitions if provided
    if defs is not None:
        try:
            from systems.socioeconomics import init_community_stats
            init_community_stats(world, defs)
        except Exception:
            pass

    # Init public figures registry
    if defs is not None:
        pf = defs.get("public_figures", {})
        if pf and not world.get("public_figures"):
            world["public_figures"] = list(pf.values())

    # Init government from definitions
    if defs is not None:
        gov = defs.get("government")
        if gov:
            world.setdefault("government", gov.copy())


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
    world.setdefault("conflicts",          {})
    world.setdefault("social_contracts",   {})
    world.setdefault("stocks",             {})
    world.setdefault("stock_sector_trends", {})
    world.setdefault("service_contracts",  [])
    world.setdefault("walls",              {})


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

    traffic = world.setdefault(
        "traffic",
        {}
    )

    traffic.setdefault(
        "entry_points",
        []
    )

    traffic.setdefault(
        "exit_points",
        []
    )

    traffic.setdefault(
        "intersections",
        []
    )

    traffic.setdefault(
        "lanes",
        []
    )

    world.setdefault(
        "road_entry_points",
        []
    )

    world.setdefault(
        "road_exit_points",
        []
    )

    world.setdefault(
        "road_graph",
        {}
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

    world.setdefault("families", {})
    world.setdefault("factions", {})

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
    # Delegate to market.py which owns the full category-multiplier model
    from systems.market import ensure_market_defaults as _ensure
    _ensure(market)


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

    # Work history
    c.setdefault("work_history",            [])
    c.setdefault("current_job_start_tick",  None)
    c.setdefault("company_id",              None)
    c.setdefault("job_template_id",         None)
    c.setdefault("industry_experience",     {})

    # Family tree
    c.setdefault("family_id",   None)
    c.setdefault("family_role", None)

    # Secrets
    c.setdefault("secrets", [])

    # Faction memberships
    c.setdefault("faction_memberships", [])

    # Reputation
    c.setdefault("reputation", {
        "global":       0.5,
        "community":    0.5,
        "by_faction":   {},
        "notoriety":    0.0,
        "last_event":   None,
        "last_updated": 0,
    })

    # Attraction / intimacy profile (generated by attraction.generate_attraction_profile)
    c.setdefault("attraction_profile", None)   # None = not yet generated
    c.setdefault("arousal_level",      0.0)    # global arousal (separate from per-rel)
    c.setdefault("attractiveness",     None)   # None = auto-computed on first use

    # Self-confidence — degraded by negging/manipulation; affects assertiveness
    c.setdefault("self_confidence", 0.60)   # 0-1; 0.60 default healthy baseline

    # Masculinity confidence — separate axis targeted by emasculation tactics
    c.setdefault("masculinity_confidence", 0.65)  # males only; attacks via ridicule/emasculation

    # Sexual dependency — character has been conditioned to need dominant partner style
    c.setdefault("sexual_dependency", {
        "dominant_partner_id": None,   # id of the partner they're conditioned to
        "dependency_score":    0.0,    # 0-1; high = can't climax without that dynamic
    })

    # Religious repression — shame/identity conflict from strict upbringing
    c.setdefault("repression_state", {
        "repression_score":       0.0,   # 0-1 accumulated shame/suppression
        "identity_conflict":      False, # LGBT+ identity vs family values
        "shame_events":           0,
        "addiction_pressure":     0.0,
        "self_destructive_urge":  0.0,
        "intimacy_avoidance":     0.0,
        "porn_shame_flag":        False,
        "last_conflict_tick":     0,
    })

    # Impulse control — anger pressure vs self-control
    c.setdefault("impulse_state", {
        "anger_pressure":   0.0,   # 0-1; accumulates from grievances/frustration
        "self_control":     0.5,   # 0-1; trait-derived, slow to change
        "sexism_level":     0.0,   # 0-1; male chars: raises aggression threshold toward female targets
        "last_outburst_tick": 0,   # cooldown prevents immediate repeat
    })

    # Fitness tracking — exercise sessions, fitness level, injury state
    c.setdefault("fitness_stats", {
        "fitness_level":        0.30,   # 0-1; decays without exercise; drives attractiveness bump
        "cardio_sessions":      0,      # cumulative sessions by type
        "strength_sessions":    0,
        "flexibility_sessions": 0,
        "sessions_this_week":   0,
        "streak_weeks":         0,      # consecutive weeks with ≥1 session
        "injury_cooldown":      0,      # ticks until can exercise again (0 = healthy)
        "last_session_tick":    0,
    })

    # Physical body features — used for fertility appeal scoring
    # Female chars: breast_size, hip_ratio, thigh_build assigned at gen
    # Male chars: build, height_cm assigned at gen
    c.setdefault("body_features", {})

    # Sexual preferences: positions liked/disliked, kinks, partner experience counter
    c.setdefault("sexual_preferences", {
        "positions_liked":    [],   # list of position keys from positions_registry
        "positions_disliked": [],
        "kinks":              [],   # list of kink keys from kinks_registry
        "kinks_hard_no":      [],   # will never do these
        "partner_experience": {},   # {other_id: int} — sessions with that partner
    })

    # Trauma tracking
    c.setdefault("trauma", {
        "score":       0.0,    # 0-1 cumulative
        "events":      [],     # list of trauma event records
        "ptsd_active": False,
        "intimacy_avoidance": 0.0,    # 0-1 reluctance modifier
        "trust_floor": 0.0,           # minimum trust required before any intimacy
    })

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

    # Social conflict system
    c.setdefault("grievances",               [])
    c.setdefault("portfolio",                {})
    c.setdefault("watched_stocks",           [])
    c.setdefault("last_stock_check",         0)
    c.setdefault("inventory",                [])
    # Clothing worn on body — populated by clothing.ensure_worn on first use
    if "worn" not in c:
        from systems.clothing import ensure_worn
        ensure_worn(c)
    c.setdefault("social_contract_ids",      [])
    c.setdefault("cold_shoulder_towards",    [])
    c.setdefault("_confrontation_emitted",   [])
    c.setdefault("recent_behavior_tags",     [])

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

    # Reaction system
    c.setdefault("reaction_queue",     [])
    c.setdefault("reaction_cooldowns", {})
    c.setdefault("animation_reaction", None)

    # Item knowledge — where the character last saw each item type
    c.setdefault("item_knowledge",           {})

    # Ordered activity queue for multi-step hobby preparation
    c.setdefault("activity_queue",           [])

    # Serialised queues saved when an urgent activity interrupted a hobby
    c.setdefault("suspended_hobby_sessions", [])

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

    appearance = c.setdefault(
        "appearance",
        {}
    )

    appearance.setdefault(
        "traits",
        []
    )

    appearance.setdefault(
        "height",
        None
    )

    appearance.setdefault(
        "build",
        None
    )

    appearance.setdefault(
        "hair_color",
        None
    )

    appearance.setdefault(
        "hair_style",
        None
    )

    appearance.setdefault(
        "eye_color",
        None
    )

    appearance.setdefault(
        "clothing_style",
        None
    )

    # Equipped clothing — slot → clothing_template id
    # Slots: hat, upper_layer1, upper_layer2, pants, shoes, gloves, belt, mask, backpack
    c.setdefault(
        "equipped",
        {
            "hat":          None,
            "upper_layer1": None,
            "upper_layer2": None,
            "pants":        None,
            "shoes":        None,
            "gloves":       None,
        }
    )

    job = c.setdefault(
        "job",
        {}
    )

    job.setdefault(
        "title",
        None
    )

    job.setdefault(
        "company",
        None
    )

    job.setdefault(
        "sector",
        None
    )

    job.setdefault(
        "job_template",
        None
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

    h.set