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

# 3 mandatory "cognition" core personality traits -- every character has
# exactly one (assigned at generation, see character_gen.py::generate_character,
# backfilled below for pre-existing characters). Maps trait id -> the
# learn_chance/cognitive_modifiers key used across trait_templates/
# belief_templates content and consumed by systems/peer_influence.py's
# adoption engine. Exempted from the personality-trait cap (also in
# peer_influence.py) since it's fixed identity, not a learned trait.
COGNITION_CORE_TRAITS = {
    "cognition_logical":   "logical",
    "cognition_balanced":  "balanced",
    "cognition_selfaware": "self_aware",
}


def ensure_prop_template_fields(world, defs):
    """api/props.py::create_prop() never actually copied anchors/storage/
    footprint/category from the template onto the instance until this
    round -- every prop placed before that fix (which is every prop in
    any already-persisted world) is missing them, so
    find_nearest_anchor() (props.py) could never find a match on it
    (eat/drink/sit/shower/... interactions all silently failed to even
    start) and containers.ensure_prop_storage() had nothing to stamp
    from. Separate from ensure_world_defaults() below because `defs`
    isn't available at either of that function's call sites in db.py
    (called before definitions load on cold load; called at all on cache
    hit) -- call this once `defs`/world["definitions"] is actually in
    hand instead."""
    if not defs:
        return
    prop_templates = defs.get("prop_templates", {})
    import copy
    for prop in world.get("props", []):
        template = prop_templates.get(prop.get("template"))
        if not template:
            continue
        if prop.get("anchors") is None:
            prop["anchors"] = copy.deepcopy(template.get("anchors", []))
        else:
            # A template can grow new anchors after a prop was already
            # backfilled once (e.g. kitchen_sink/bathroom_sink gaining a
            # "use_tap" anchor for the plant-watering chore) -- merge any
            # anchor missing by name rather than leaving the instance
            # permanently stuck with whatever the template looked like
            # the first time this ran.
            existing_names = {a.get("name") for a in prop["anchors"]}
            for anchor in template.get("anchors", []):
                if anchor.get("name") not in existing_names:
                    prop["anchors"].append(copy.deepcopy(anchor))
        if prop.get("storage") is None and template.get("storage") is not None:
            prop["storage"] = copy.deepcopy(template.get("storage"))
        prop.setdefault("footprint", template.get("footprint"))
        prop.setdefault("category", template.get("category"))
        if template.get("catalog") is not None:
            prop.setdefault("catalog", template.get("catalog"))


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

    # housing.py's home_id/homes economy (rent/electricity/water/gas/
    # internet billing, plus this round's mortgage/home-insurance
    # origination) used to never actually get populated for a real
    # household (confirmed live -- home_id was never set anywhere),
    # silently defaulting every household's weekly bill to a flat,
    # uninformative placeholder. household_manager.py now sets this up
    # at the two real household-creation call sites; this defense-in-
    # depth backfill (self-healing, safe to re-run every load -- same
    # shape as systems/electrical.py's power-outlet backfill) catches
    # any household built through some other path.
    for _household in world.get("households", {}).values():
        try:
            from systems.household_manager import _ensure_household_housing_setup
            _ensure_household_housing_setup(world, _household)
        except Exception:
            pass

    world.setdefault("conflicts",          {})
    world.setdefault("social_contracts",        {})
    world.setdefault("pending_contract_proposals", [])
    world.setdefault("micro_request_queue",        [])
    world.setdefault("stocks",             {})
    world.setdefault("stock_sector_trends", {})
    world.setdefault("service_contracts",  [])
    world.setdefault("household_processes", [])

    # Per-zone cleanliness (see systems/chores.py) -- keyed by
    # prop["room_id"] where a building actually has real room
    # subdivision, else falling back to the building_id itself (today's
    # reality for most households, which have no rooms[] data at all).
    # 0-100, 100=spotless; decays passively, raised by completing a
    # cleaning chore in that zone.
    world.setdefault("room_cleanliness", {})
    # Per-zone furniture-change tracking (systems/refurnishing.py) --
    # {zone_key: {last_changed_tick, changes_today, day_stamp}}.
    world.setdefault("zone_furniture_changes", {})
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
    for i, building in enumerate(world.get("buildings", [])):
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
        # Address — assigned once per building (setdefault, so an address
        # a user hand-edited via the Household tab is never overwritten on
        # a later load). One town-wide placeholder street; house numbers
        # derived from each building's position in the list so every
        # building gets a distinct one. See building_manager.py:129, which
        # already forwards this into the runtime building dict.
        building.setdefault("address", f"{100 + i * 2} Placeholder Street")

    # A mailbox prop is the in-game control point for one household (see
    # systems/household_manager.py) — distinct from a building's
    # owner_household_id, which is the household that owns *that
    # floorplan*. Backfilled here rather than via a generic per-prop
    # metadata field, since none exists in this codebase.
    from systems.props import get_props_by_template
    for mailbox in get_props_by_template(world, "mailbox"):
        mailbox.setdefault("household_id", None)

    # Every OTHER prop's household_id (see room_assignment.py::
    # assign_prop_room, which sets this at creation time going forward)
    # -- backfilled here for props that existed before that fix, or that
    # were placed through a path that never called it. household_id
    # stays None for props with no building_id (public infrastructure --
    # bus, bus stop -- which already explicitly set it to None) or whose
    # building has no owning household (a vacant/unclaimed home).
    buildings_by_id = {b["id"]: b for b in world.get("buildings", []) if b.get("id")}
    for prop in world.get("props", []):
        if "household_id" in prop:
            continue
        building = buildings_by_id.get(prop.get("building_id"))
        prop["household_id"] = building.get("owner_household_id") if building else None


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
            c, world=world
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

        # Physical mailbox position -- service_vehicles.py's route
        # pathfinding (systems/newspaper_delivery.py, and the separately
        # dormant systems/postal_service.py) needs a real x/y here, but
        # nothing ever set one: mail.py's household.setdefault("mailbox",
        # {...}) only ever gives it has_mail/items/unopened_count (an
        # abstract inbox, unrelated shape) -- this backfill adds x/y
        # alongside whatever mail.py already put there, never overwriting
        # it. A simple fixed offset from the building origin, same
        # pattern as vehicles.py::GARAGE_LOCAL_OFFSET.
        mailbox = h.setdefault("mailbox", {})
        if "x" not in mailbox or "y" not in mailbox:
            building = next(
                (b for b in world.get("buildings", [])
                 if b.get("owner_household_id") == h["id"]),
                None,
            )
            if building:
                from systems.transforms import local_to_world
                mx, my = local_to_world(building, 0, -1)
                mailbox["x"] = mx
                mailbox["y"] = my

        # Convenience/stability tracking (systems/convenience.py) -- when a
        # household already has a home, treat "established" as starting to
        # accrue from now rather than backdating a fake history.
        if "home_since_tick" not in h:
            h["home_since_tick"] = world.get("tick", 0) if h.get("home_id") else None

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

    # Sports leagues (see systems/sports_leagues.py) -- per-sport schedule
    # + standings for the 4 real pro leagues, keyed by sport
    # ("football"/"basketball"/"hockey"/"soccer"). Local (invented) leagues
    # share the same shape under their own sport key once generated.
    world.setdefault("sports_leagues", {})

    # Second-hand furniture marketplace (see systems/marketplace.py) --
    # sims sell/buy household props to/from each other.
    world.setdefault("marketplace_listings", [])

    # Darknet listing board (see systems/darknet.py) -- drugs, stolen
    # data/hacking, fake IDs/counterfeit money, hitman/PI services.
    world.setdefault("darknet_listings", [])
    world.setdefault("pi_assignments", [])
    world.setdefault("surveillance_feeds", [])

    # Invented local sports clubs for THIS simulation only (not real teams --
    # see sports_teams in definitions.json for the real pro rosters). Lazily
    # generated on first "play_*" hobby pickup -- see systems/sports.py.
    world.setdefault("local_teams", {})
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

def ensure_character_defaults(c, world=None):

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

    # law.py's arrest handler does `c["status"]["reputation"] -= .25` --
    # a bare key subtraction that KeyErrors if "reputation" isn't already
    # present, so this needs a real default rather than a `.get()` fallback.
    status = c.setdefault("status", {})
    status.setdefault("reputation", 0.5)

    c.setdefault(
        "wealth",
        100
    )

    c.setdefault(
        "money",
        100
    )

    if c.get("credit_score") is None:
        from systems.credit import initial_credit_score
        c["credit_score"] = initial_credit_score(c.get("age"), c.get("employed", False))

    c.setdefault("government_debt", 0.0)

    if c.get("cleanliness_threshold") is None:
        from systems.character_gen import cleanliness_threshold_for_traits
        c["cleanliness_threshold"] = cleanliness_threshold_for_traits(
            list(c.get("traits", [])) + list(c.get("personality_traits", []))
        )

    if c.get("redecorate_threshold_days") is None:
        from systems.refurnishing import random_redecorate_threshold_days
        c["redecorate_threshold_days"] = random_redecorate_threshold_days()

    c.setdefault("phone_data_gb_remaining", 0)

    if c.get("online_profile") is None and world is not None:
        from systems.subscriptions import generate_online_profile
        c["online_profile"] = generate_online_profile(world.get("definitions", {}))

    # Retrofit -- character_gen.py::generate_character() only grants a
    # starting wallet/ID/bank card/bio to characters generated AFTER the
    # banking round shipped. Any character already saved before that
    # (or created by an older code path that skips generate_character
    # entirely) is missing all four; this backfills them the first time
    # ensure_character_defaults() sees such a character, using the exact
    # same factories/shape as generation-time so it's indistinguishable
    # from a freshly generated character afterward.
    inventory = c.setdefault("inventory", [])
    if not any(i.get("object_type") == "wallet" for i in inventory):
        try:
            import random
            from systems.personal_items import make_wallet, make_id_card, make_bank_card, STARTER_BANKS
            id_card = make_id_card(c["id"], c.get("name", ""), owner_id=c["id"])
            bank_name = random.choice(STARTER_BANKS)
            account_number = None
            if world is not None:
                from systems.banking import bank_key_for_name, open_account
                bank_key = bank_key_for_name(bank_name)
                if bank_key:
                    account_number = open_account(world, bank_key, c["id"], initial_balance=0.0)
            bank_card = make_bank_card(bank=bank_name, account_number=account_number, owner_id=c["id"])
            wallet = make_wallet(cash=100.0, owner_id=c["id"], contents=[id_card, bank_card])
            inventory.append(wallet)
        except Exception:
            pass

    if not c.get("bio"):
        from systems.character_gen import _fallback_bio_for_character
        c["bio"] = _fallback_bio_for_character(c)

    # Validation-seeking (systems/validation.py) -- queue of choices a
    # character might still ask someone's opinion on, plus the
    # popularity/scoring fields that ride on top of it.
    c.setdefault("validation_queue", [])
    c.setdefault("validation_refresh_time", 48)     # hours -- see check_validation_refresh()
    c.setdefault("last_validation_received", 0)     # tick
    c.setdefault("validation_score_24h", [])        # [{"tick","points"}], pruned to a rolling 24h window
    c.setdefault("validation_personal_record", 0.0)  # best single validation-event score ever
    c.setdefault("popularity", 0.0)
    c.setdefault("followers", 0)

    c.setdefault(
        "hourly_wage",
        0
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

    # Standing among criminal contacts/gangs (see systems/crime.py) --
    # rises from committing crimes without getting caught, decays
    # slowly otherwise, gates promotion up a career track's tiers and
    # (for the drug track) real recruitment into a faction.
    c.setdefault("criminal_standing", 0.0)

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

    # Weight (kg) — real-kilograms field driving the BMI band spectrum in
    # systems/nutrition.py (character_gen.py seeds this properly at
    # creation; this is only a migration fallback for older characters).
    if not c.get("weight_kg"):
        height_cm = c.get("body_features", {}).get("height_cm", 170)
        c["weight_kg"] = round(22.0 * (height_cm / 100.0) ** 2, 1)

    # Full name split + SSN (character_gen.py seeds both properly at
    # creation; these are migration fallbacks for older characters, from
    # back before simulations/default/definitions.json had a "names"
    # registry -- see decision #1/#2 of the names/SSN/address round).
    if not c.get("first_name") or not c.get("family_name"):
        parts = (c.get("name") or "Alex Smith").split(" ", 1)
        c.setdefault("first_name",  parts[0])
        c.setdefault("family_name", parts[1] if len(parts) > 1 else "Smith")
    if not c.get("ssn"):
        import random as _random
        c["ssn"] = f"{_random.randint(0, 999):03d}-{_random.randint(0, 99):02d}-{_random.randint(0, 9999):04d}"

    # Cognition core trait (Logical/Balanced/Self-Aware) -- every character
    # gets exactly one, assigned at generation (character_gen.py). Backfill
    # for pre-existing characters that predate this system.
    if not any(t in COGNITION_CORE_TRAITS for t in c.get("traits", [])):
        import random as _random
        c.setdefault("traits", []).append(_random.choice(list(COGNITION_CORE_TRAITS.keys())))

    # Substance-use/craving tracking — see systems/addictions.py.
    # {addiction_key: {"usages": int, "last_used_sim_time": float|None,
    #                   "next_decay_sim_time": float|None}}
    c.setdefault("addictions", {})

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

    # Recurring self-expectations ("checkboxes") -- what this character
    # tries to live up to, at daily/weekly/monthly/yearly/once cadences
    # (definitions.json's expectation_templates). Keyed by template_id.
    # See systems/expectations.py -- calendar-period-anchored (not a
    # rolling next_due_tick), sibling in spirit to lt_needs.py's per-need
    # frustration/satisfy shape (deliberately not merged into it):
    #   {template_id, cadence, category, of_self, requires_others,
    #    current_period_key, satisfied_this_period, last_satisfied_tick,
    #    streak, missed_count, frustration,
    #    status: "pending"|"satisfied"|"missed", last_missed_blame: [char_id,...]}
    c.setdefault("expectations", {})

    # Convenience/stability tracking -- things a character has come to rely
    # on (a steady job, a stable home, personal freedom/autonomy) whose
    # LOSS is a bigger stressor than never having had them. See
    # systems/convenience.py. "autonomy" defaults established=True (a
    # baseline you have unless something takes it away); employment/housing
    # ramp up to established over time (see convenience.py::ESTABLISH_TICKS)
    # rather than starting established, since those are genuinely built up.
    c.setdefault("conveniences", {
        "employment": {"established": False, "disrupted_count": 0, "frustration": 0.0},
        "housing":    {"established": False, "disrupted_count": 0, "frustration": 0.0},
        "autonomy":   {"established": True,  "disrupted_count": 0, "frustration": 0.0},
    })

    # Standalone sexual-release need (see systems/libido.py) -- separate
    # from intimacy.py's relationship-scoped arousal_level. Lazily
    # created there too (ensure_libido_state), this is just the backfill
    # for characters that predate it.
    if "libido_state" not in c:
        from systems.libido import ensure_libido_state
        ensure_libido_state(c)

    # Ranked, capped list of stories worth telling others -- see
    # systems/stories.py. Distinct from c["memories"] (everything a
    # character remembers); this is the tellable subset.
    c.setdefault("notable_stories", [])

    # Behavior-pattern observation (see systems/behavior_patterns.py).
    # _daily_observations is cleared every real calendar day after
    # aggregating into behavior_patterns.
    c.setdefault("_daily_observations", [])
    c.setdefault("behavior_patterns", {})

    # Sports hobbies (see systems/sports.py). supported_teams: sport ->
    # sports_teams id (real pro team, picked when an "X Supporter" hobby is
    # adopted). local_team: sport -> local_teams id (invented local club,
    # picked when a "play_X" hobby is adopted). sports_injury_cooldown:
    # sport -> tick the character is next eligible to risk another playing
    # injury (mirrors exercise.py's injury-cooldown shape).
    c.setdefault("supported_teams", {})
    c.setdefault("local_team", {})
    c.setdefault("sports_injury_cooldown", {})

    # Cover persona (see systems/persona.py) -- None when "being
    # themselves"; a real {name, occupation_label, cover_tags,
    # adopted_tick} dict while playing an assumed identity.
    c.setdefault("active_persona", None)

    # Side-work corruption for eligible legal professionals (lawyer,
    # bank_teller, accountant, mayor, police_officer) -- see
    # systems/crime.py::maybe_offer_corruption().
    c.setdefault("corruption", 0.0)

    # Persistent alternate identities a sociopath maintains across
    # multiple contacts (see systems/sociopathy.py) -- distinct from the
    # single-activity active_persona above.
    c.setdefault("persona_bank", [])

    # Temporary psychosis state (see systems/psychosis.py) -- any
    # character can enter it; schizophrenia raises the baseline rate.
    c.setdefault("psychosis_state", {
        "active": False, "intensity": 0.0, "trigger": None, "started_tick": None,
    })

    # Diary (see systems/diary.py) -- a routine some sims have, gated on
    # the keep_a_diary hobby + owning a real diary item.
    c.setdefault("diary_entries", [])

    # Speech/writing quirk (see speech_style_registry in definitions.json)
    # -- most characters have none; a minority talk/write distinctly
    # differently, narrated into every LLM turn via context_builder.py's
    # _sec_identity and into diary entries via llm/diary_narration.py.
    c.setdefault("speech_style", None)

    # Preliminary plans (steps/requirements/possible-solutions) for active
    # expectations -- see systems/expectation_planner.py, which queues
    # steps onto c["activity_queue"] the same way hobby_planner.py does.
    # Keyed by expectation_id.
    c.setdefault("expectation_plans", {})

    # Opinions formed on specific topics/questions, informed by the values
    # above. Keyed by topic, each value a capped history of past-formed-
    # opinion snapshots (mirrors offgrid_category_memory's two-level
    # dict-of-capped-lists shape) -- see brain/opinions.py.
    c.setdefault("opinions", {})

    # General beliefs adopted from belief_templates (definitions.json) via
    # social exposure -- see systems/peer_influence.py's adoption engine.
    # Deliberately separate from c["beliefs"] (brain/beliefs.py -- narrow,
    # fixed-axis political sentiment scalars consumed by systems/politics.py's
    # elections/factions) and c["opinions"] (free-form, LLM-reasoned). A flat
    # list of belief-template ids, mirroring c["personality_traits"].
    c.setdefault("held_beliefs", [])

    # Per-(source_person_id, belief) accumulator feeding the same
    # dual-threshold promotion shape as c["influence_profile"] (traits) --
    # see systems/peer_influence.py::record_positive_belief_exposure().
    c.setdefault("belief_influence_profile", [])

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
    c.setdefault("off_grid",                  False)  # currently away (work/errand/hospital/jail/...)
    c.setdefault("off_grid_reason",           None)
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
        "story_arc",
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
        "trial_tick",
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

    # =====================================================
    # HEALTH_STATE -- the real per-bodypart damage/health engine
    # (systems/health.py). Registered here so a freshly generated
    # character always has the full shape instead of health.py's
    # functions lazily setdefault()-ing individual fields the first
    # time something touches them.
    # =====================================================

    health_state = c.setdefault(
        "health_state",
        {}
    )

    health_state.setdefault(
        "active_emergencies",
        {}
    )

    body_parts = health_state.setdefault(
        "body_parts",
        {}
    )

    for _part in (
        "head", "neck", "chest", "abdomen", "pelvis",
        "left_arm", "right_arm", "left_leg", "right_leg",
    ):
        body_parts.setdefault(
            _part,
            {
                "hazards": {},
                "damage_type": None,
                "severity_level": None,
                "functional_status": "normal",
                "injury_template": None,
                "cause": None,
                "tick": None,
            }
        )

    health_state.setdefault(
        "total_blood_lost",
        0.0
    )

    health_state.setdefault(
        "doctor_visits_needed",
        0
    )

    health_state.setdefault(
        "medications_taken",
        {}
    )

    health_state.setdefault(
        "systemic_hazards",
        {}
    )

    health_state.setdefault(
        "temporary_traits",
        {}
    )

    health_state.setdefault(
        "treatment_progress",
        {}
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

    h.setdefault("subscriptions", {})

    h.setdefault(
        "newspaper_subscription",
        False
    )

    # See systems/chores.py -- a simple household-wide count, not real
    # per-instance dirty plates/cups (deliberate scope decision, see
    # chore_templates["wash_dishes_manual"]'s _per_item_note).
    h.setdefault(
        "dirty_dishes",
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

