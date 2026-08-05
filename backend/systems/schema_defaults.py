# =========================================================
# WORLD DEFAULTS
# =========================================================

from uuid import uuid4

# 12 fixed personal-value life domains -- see c["values"] default below.
# Shared constant, imported from here by character_gen.py (seeding),
# brain/context_builder.py (narrative surfacing), systems/influence.py
# (daily value-influence resolution), and systems/peer_influence.py
# (child trait-hint mapping) to keep the category list in one place.
VALUE_CATEGORIES = [
    "family", "friends", "work", "leisure", "education", "romance",
    "children", "religion", "politics", "community", "solidarity",
    "traditions",
]


def ensure_world_defaults(world, defs=None):
    # Server-side time-scale control (see api/admin.py) -- 1x is realtime.
    world.setdefault("time_scale", 1)

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
    world.setdefault("social_contracts",        {})
    world.setdefault("pending_contract_proposals", [])
    world.setdefault("micro_request_queue",        [])
    world.setdefault("stocks",             {})
    world.setdefault("stock_sector_trends", {})
    world.setdefault("service_contracts",  [])
    world.setdefault("household_processes", [])
    world.setdefault("proposals", {})
    world.setdefault("walls",              {})


    world.setdefault(
        "events",
        []
    )

    # =====================================================
    # BUILDINGS
    # =====================================================
    # Backfills pre-floorplan-system buildings (missing "template"/"x"/"y")
    # so build_world_geometry() can resolve them instead of silently
    # skipping them every load. Runs before build_world_geometry, so it
    # patches already-persisted world data, not just freshly generated worlds.
    for building in world.get("buildings", []):
        building.setdefault("template", "small_house")
        building.setdefault("x", 0)
        building.setdefault("y", 0)
        building.setdefault("rotation", 0)
        # owner_household_id is read by building_manager.py but nothing
        # wrote it until the household admin feature — safe stub default.
        building.setdefault("owner_household_id", None)
        # Not backend-enforced at creation time (every current source of
        # buildings happens to supply one), but household admin's
        # lookups key on it — backfill defensively so a legacy/hand-edited
        # entry without one doesn't KeyError there.
        building.setdefault("id", str(uuid4()))

    # A mailbox prop is the in-game control point for one household (see
    # systems/household_manager.py) — distinct from a building's
    # owner_household_id, which is the household that owns *that
    # floorplan*. Backfilled here rather than via a generic per-prop
    # metadata field, since none exists in this codebase.
    from systems.props import get_props_by_template
    for mailbox in get_props_by_template(world, "mailbox"):
        mailbox.setdefault("household_id", None)

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

    # setdefault only fills a *missing* key -- if "alive" is present but
    # explicitly None (seen from ad-hoc debug/patch scripts), every
    # `c.get("alive", True)` check across the codebase treats that as
    # falsy and silently excludes the character from the LLM decision
    # loop, health processing, etc. forever, with no error anywhere.
    if c.get("alive") is None:
        c["alive"] = True

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

    # Curiosity — 0-100 (explicit user spec, unlike most scalars on this
    # page which are 0-1), how much this character wants to understand
    # what's going on around them: notices/investigates the out-of-the-
    # ordinary, follows the news, asks personal questions, trades gossip.
    # Distinct from the "curious" personality trait (character_gen.py's
    # trait_templates entry, which only nudges the "learning" lt_need's
    # weight) -- this is the measurable driver behind actual behavior,
    # seeded with a trait-correlated jitter in character_gen.py::
    # _seed_curiosity(). Also distinct from the "solidarity" value
    # category (schema below) -- wanting to know what's going on is not
    # the same axis as in-group vs. universal solidarity.
    c.setdefault("curiosity", 50)

    # Masculinity confidence — separate axis targeted by emasculation tactics
    c.setdefault("masculinity_confidence", 0.65)  # males only; attacks via ridicule/emasculation

    # Sexual dependency — character has been conditioned to need dominant partner style
    c.setdefault("sexual_dependency", {
        "dominant_partner_id": None,   # id of the partner they're conditioned to
        "dependency_score":    0.0,    # 0-1; high = can't climax without that dynamic
    })

    # Intoxication & substance state
    c.setdefault("intoxication_state", {
        "alcohol_level":   0.0,
        "drug_level":      0.0,
        "porn_habit":      0.0,
        "libido_boost":    0.0,
        "sessions_today":  0,
        "last_harass_tick": {},
    })

    # Pregnancy state
    c.setdefault("pregnancy", {
        "status":          "none",    # none | pregnant | postpartum | aborted | adopted_out
        "father_id":       None,
        "conception_tick": 0,
        "discovered_tick": None,
        "decision":        "undecided",
        "decision_tick":   None,
        "weeks":           0,
        "drama_fired":     [],
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

    # Portrait / profile image
    c.setdefault("portrait_url", None)      # path or URL to headshot image

    # Crushes / infatuations — people this character has feelings for
    # Each entry: {
    #   "character_id": str | None,       # null if they don't know who they are yet
    #   "name": str,                       # display name
    #   "relation_label": str,             # "neighbour", "teacher", "cousin", "coworker" etc.
    #   "attraction_type": "sexual"|"romantic"|"both",
    #   "intensity": float,                # 0–1
    #   "is_secret": bool,
    #   "fantasy_count": int,              # times fantasised about this person
    #   "last_fantasy_tick": int,
    # }
    c.setdefault("crushes", [])

    # Thought bubble — what the character is currently visibly thinking about
    # Consumed by frontend to render a thought bubble with portrait + caption
    # {
    #   "active": bool,
    #   "subject_id": str | None,
    #   "subject_name": str,
    #   "portrait_url": str | None,
    #   "type": "crush" | "intention" | "daydream" | "worry",
    #   "caption": str,                    # short text shown in bubble
    #   "tick_expires": int,
    # }
    c.setdefault("thought_bubble", {"active": False})

    # Blushing state
    c.setdefault("blush_score",  0.0)   # 0–1, decays over time
    c.setdefault("is_blushing",  False)

    # Nudity state — recomputed by clothing.py on every dress/undress
    c.setdefault("is_nude",        False)   # lower body exposed
    c.setdefault("exposed_chest",  False)   # female upper body exposed
    c.setdefault("nudity_witnessed", {})    # {observer_id: tick} — who saw this char nude

    # Infant/child fields (only meaningful for age < 6, but stamped on all)
    c.setdefault("age_months",         None)           # float months; set on newborns
    c.setdefault("development_stage",  None)           # newborn/infant/crawler/toddler/child/preschool
    c.setdefault("dev_milestones",     {})             # {milestone_id: tick_achieved}
    c.setdefault("baby_needs",         None)           # {hunger,sleep,comfort,stimulation} — set on infants
    c.setdefault("is_crying",          False)
    c.setdefault("breastfeeding_state", None)          # set on newborns
    c.setdefault("maternity_leave_until", 0)           # tick until which mother is on leave
    c.setdefault("on_maternity_leave",    False)
    c.setdefault("prenatal_prep",      None)           # set during pregnancy
    c.setdefault("school_enrollment",  None)           # school_template id when enrolled

    # Locomotion speeds, tiles/tick -- see movement.py::_current_move_speed()
    # for how these get selected (crawling posture / jog|sprint|sneak
    # animation_state / default walk) and DEFAULT_*_SPEED for the values
    # these must match. c["move_speed"] is deliberately left unset here --
    # it's an override hook baby.py/pregnancy.py write to directly, and
    # movement.py treats its mere presence as "this character's speed is
    # externally managed", which a blanket default here would break.
    c.setdefault("walk_speed",   0.05)
    c.setdefault("jog_speed",    0.09)
    c.setdefault("sprint_speed", 0.18)
    c.setdefault("crawl_speed",  0.02)
    c.setdefault("sneak_speed",  0.025)

    # Pushable prop (baby carriage / lawnmower — separate mechanic from drag/push below)
    c.setdefault("pushed_prop_id",         None)       # prop instance id when pushing carriage/mower etc.
    c.setdefault("_active_locomotion_override", None)  # animation override while pushing

    # Movable props (chairs/sofas/etc. — see systems/prop_movement.py)
    c.setdefault("dragged_prop_id",        None)  # prop this character is the primary dragger of
    c.setdefault("pushing_prop_id",        None)  # prop this character is the second-person pusher of

    # Individual wait activities (microwave, phone hold, ... — see
    # systems/activities.py's start_microwave/take_out_of_microwave and
    # sim_loop.py's character_wait cadence block). Deliberately separate
    # from c["activity"] — see sim_loop.py's comment on why.
    c.setdefault("character_wait",         None)

    # Persistent per-character LLM session (see brain/llm_brain.py::think())
    # — a rolling list of short condensed turn digests (thought/action/
    # speech), NOT raw prompts/responses. Kept deliberately small/condensed
    # so continuity of "what did I just do" doesn't re-embed the full
    # per-tick context every turn.
    c.setdefault("_llm_session", {"history": []})

    # Per-character cognition scheduler state (see
    # brain/cognition_scheduler.py). Governs when this character's next
    # think() call happens — replaces the old "every idle tick" behavior
    # with an idle cadence plus event-driven wakes.
    c.setdefault("cognition", {
        "next_think_tick": 0,
        "last_think_tick": -1,
        "wake_reason": None,
        "wake_payload": None,
        "idle_streak": 0,
        "last_urgent_need": None,
        "turn_budget": 0,
        "staged_knowledge": [],
    })

    # Sense-related physical traits (poor_eyesight, keen_hearing, ...) —
    # see brain/perception.py's SENSE_TRAIT_MODIFIERS. Kept separate from
    # c["traits"] (personality) since build_narrative() describes them
    # completely differently in the prompt.
    c.setdefault("physical_traits", [])

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

    # Personal values -- 12 fixed life-domain categories, each scored by
    # importance (0-1, how much this character cares) and conform (bool:
    # True = thinks this domain should be governed by shared rules/
    # structure, False = thinks it should be left to individual choice).
    # Real per-character seeding (randomized, or nudged toward parents'
    # values for children) happens at generation time in character_gen.py
    # -- this flat neutral default only backfills characters that predate
    # the system. Distinct from family.py's generate_family_values() dict
    # (religious_strictness/sex_negative/homophobic) -- that's a static,
    # family-level structure unrelated to this per-character one.
    c.setdefault("values", {cat: {"importance": 0.5, "conform": True} for cat in VALUE_CATEGORIES})

    # Opinions formed on specific topics/questions, informed by the values
    # above. Keyed by topic, each value a capped history of past-formed-
    # opinion snapshots (mirrors offgrid_category_memory's two-level
    # dict-of-capped-lists shape) -- see brain/opinions.py.
    c.setdefault("opinions", {})

    # Accumulator for the daily trust/respect/exposure/value-similarity
    # weighted influence pass -- see systems/influence.py::resolve_value_influence().
    # Keyed by value category, mirrors influence_profile/conditioning_profile's
    # accumulate-then-threshold-promote shape.
    c.setdefault("value_influence_profile", {})

    # Social conflict system
    c.setdefault("grievances",               [])
    # Standing, unilateral policies this character holds toward others
    # (e.g. "household members may borrow my car"), with per-subject
    # exceptions carved out from precedent. See systems/social_rules.py.
    c.setdefault("social_rules",             [])
    c.setdefault("portfolio",                {})
    c.setdefault("watched_stocks",           [])
    c.setdefault("last_stock_check",         0)
    c.setdefault("inventory",                [])
    # Ordered bottom->top list of item dicts held as a stack in one hand —
    # separate from inventory (items leave inventory while stacked, same as
    # they already leave it when placed on the ground). See systems/item_stack.py.
    c.setdefault("held_stack",               [])
    # Clothing worn on body — populated by clothing.ensure_worn on first use
    if "worn" not in c:
        from systems.clothing import ensure_worn
        ensure_worn(c)
    # Legacy remap — the enum used to be standing|sitting|lying|leaning;
    # widened to the 8-stance vocabulary (see systems/posture.py) so
    # sitting/leaning distinguish seat-vs-floor and wall-vs-none.
    if c.get("posture") == "sitting":
        c["posture"] = "sitting_seat"
    elif c.get("posture") == "leaning":
        c["posture"] = "leaning_wall"
    c.setdefault("posture",                  "standing")
    # standing | sitting_seat | sitting_floor | lying | crouching | crawling |
    # fallen_front | fallen_back | leaning_wall | unconscious | dead | intoxicated
    c.setdefault("leaning_wall_id",          None)        # wall being leaned on (cleared on move)
    c.setdefault("social_contract_ids",      [])
    c.setdefault("conditioning_profile",      [])   # conditioned behaviors
    c.setdefault("active_lies",               [])   # currently maintained lies
    c.setdefault("private_off_grid_history",  [])  # secret events from off-grid trips (not shared)
    c.setdefault("off_grid_trip_day",         None)  # calendar day of last voluntary off-grid trip
    c.setdefault("off_grid_trip_count",       0)      # voluntary trips taken that day -- see offgrid.py MAX_OFFGRID_TRIPS_PER_DAY
    c.setdefault("inbox",                     [])     # shared call/text/email/voicemail log -- see systems/inbox.py
    # Behavior-based suspicion — routine deviation, caught lies, evasive
    # answers, snooped devices. Keyed by subject_id. See systems/worries.py.
    # Replaces the old "suspicion_of" field (was write-only, read by nothing).
    c.setdefault("worries",                   {})
    c.setdefault("forbidden_locations",       [])   # locations this character has banned for subordinates
    c.setdefault("disliked_location_types",   [])   # location types authority dislikes
    c.setdefault("behavior_tags",             [])   # observable behavior habits (e.g. heavy_drinker)
    c.setdefault("objected_activities",       [])   # activities this authority explicitly objects to
    c.setdefault("conditioned_traits",        [])   # promoted conditioning entries
    c.setdefault("discipline_log",            [])   # discipline events received
    c.setdefault("pending_authority_contact", [])   # violation escalation queue
    c.setdefault("intention_queue",           [])   # pending AI intentions
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
        "name",
        None
    )

    h.setdefault(
        "building_ids",
        []
    )

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

