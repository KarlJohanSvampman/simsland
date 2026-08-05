from brain.beliefs import update_belief
def record_influence(source,target,amount,world):
    source.setdefault("influence_given",{})[target["id"]]=source.setdefault("influence_given",{}).get(target["id"],0)+amount
    target.setdefault("influence_received",{})[source["id"]]=target.setdefault("influence_received",{}).get(source["id"],0)+amount
    world.setdefault("influence_graph",{}).setdefault(source["id"],{})[target["id"]]=world.setdefault("influence_graph",{}).setdefault(source["id"],{}).get(target["id"],0)+amount
def apply_public_figure_influence(world):
    for news in world.get("news",[])[-3:]:
        for pfid in news.get("related_entities",[]):
            pf=next((p for p in world.get("public_figures",[]) if p["id"]==pfid), None)
            if not pf: continue
            for c in world["characters"].values():
                curiosity_scale=c.get("curiosity",50)/100.0
                for tag in pf.get("tags",[])[:2]: update_belief(c,tag,news.get("sentiment","neutral"),news.get("intensity",.3)*pf.get("influence_power",.5)*curiosity_scale,world["tick"])
def apply_social_influence(world):
    for c in world["characters"].values():
        for tid,weight in c.get("influence_given",{}).items():
            if tid in world["characters"]:
                target=world["characters"][tid]
                for topic,b in c.get("beliefs",{}).items(): update_belief(target,topic,"positive" if b.get("value",0)>0 else "negative",min(.3,abs(b.get("value",0))*weight*.05),world["tick"])


# =========================================================
# EXPOSURE-DRIVEN RESOLUTION (trust-gated)
# =========================================================
# Periodic pass over exposure_ticks (brain/perception.py::perceive_people()
# increments these -- who a character is around the most, distinct from
# trust itself). Trust decides direction here, exposure decides
# magnitude/who: trusted (trust>40) exposure feeds positive belief/trait
# influence; distrusted (trust<-40) exposure instead breeds suspicion via
# worries.py. Neither fires in the mid-range -- exposure alone, without a
# trust signal, does nothing.

_MIN_EXPOSURE_TO_RESOLVE = 5
_TRUST_POSITIVE_GATE     = 40
_TRUST_NEGATIVE_GATE     = -40


def resolve_exposure_influence(world):
    from systems.peer_influence import record_positive_exposure
    from systems.worries import bump_suspicion

    chars = world.get("characters", {})
    for c in chars.values():
        for other_id, rel in c.get("relationships", {}).items():
            exposure = rel.get("exposure_ticks", 0)
            if exposure < _MIN_EXPOSURE_TO_RESOLVE:
                continue

            other = chars.get(other_id)
            if not other:
                continue

            trust  = rel.get("trust", 0)
            weight = min(1.0, exposure / 100.0)

            if trust > _TRUST_POSITIVE_GATE:
                record_influence(other, c, weight, world)
                for trait in set(other.get("traits", []) + other.get("personality_traits", [])):
                    record_positive_exposure(c, other, trait, world)
            elif trust < _TRUST_NEGATIVE_GATE:
                bump_suspicion(
                    c, other_id, 0.01 * weight, "prolonged_exposure",
                    f"You've been around {other.get('name', other_id)} a lot lately, "
                    f"and something about it doesn't sit right",
                    world,
                )

            # Halve, don't zero -- influence has memory but doesn't compound unboundedly.
            rel["exposure_ticks"] = exposure // 2


# =========================================================
# DAILY VALUE INFLUENCE (trust+respect+value-similarity weighted)
# =========================================================
# Sibling to resolve_exposure_influence() above, run on a daily cadence
# instead of every 30 ticks (CADENCE["value_influence"], sim_loop.py) --
# "impact over time" aggregated once a day, not resolved continuously.
# Reuses the same exposure_ticks signal (brain/perception.py) this file's
# other resolver already reads, but does NOT halve it itself -- that
# stays resolve_exposure_influence's job (single writer for that decay);
# this function only reads the shared tally. Weighted by trust+respect
# blended (not trust alone) and by per-category value agreement, scaled
# by how much both people actually care about that category.

VALUE_INFLUENCE_MIN_EXPOSURE      = 5
VALUE_IMPORTANCE_STEP             = 0.03   # max daily importance nudge
VALUE_CONFORM_FLIP_THRESHOLD      = 0.70   # mirrors peer_influence.py's TRAIT_CONVERSION_THRESHOLD
VALUE_CONFORM_MIN_REINFORCEMENTS  = 15     # mirrors peer_influence.py's MIN_REINFORCEMENTS
_THIRD_PARTY_BONUS_PER_AGREEING_SOURCE = 0.15


def resolve_value_influence(world):
    """For every character, aggregate today's value-influence pressure
    from everyone they were exposed to (weighted by trust/respect, value-
    similarity, and how many of their OTHER trusted relationships also
    agree with that person), then apply it once: a continuous nudge to
    each category's importance, and a threshold-gated flip of conform
    once enough one-directional opposing pressure has built up."""
    from systems.schema_defaults import VALUE_CATEGORIES

    chars = world.get("characters", {})
    tick = world.get("tick", 0)

    for c in chars.values():
        values = c.get("values")
        if not values:
            continue

        pressure = {cat: {"reinforce": 0.0, "oppose": 0.0, "oppose_sources": 0} for cat in VALUE_CATEGORIES}

        for other_id, rel in c.get("relationships", {}).items():
            exposure = rel.get("exposure_ticks", 0)
            if exposure < VALUE_INFLUENCE_MIN_EXPOSURE:
                continue
            other = chars.get(other_id)
            if not other or not other.get("values"):
                continue

            quality = (rel.get("trust", 0) + rel.get("respect", 0)) / 2.0
            if quality <= 0:
                continue  # only positively-regarded relationships push value influence
            time_weight = min(1.0, exposure / 100.0)
            rel_weight = time_weight * (quality / 100.0)

            agreeing_sources = _count_agreeing_trusted_sources(c, other_id, other, chars)

            for cat in VALUE_CATEGORIES:
                mine = values[cat]
                theirs = other["values"].get(cat)
                if not theirs:
                    continue
                shared_importance = min(mine["importance"], theirs["importance"])
                if shared_importance <= 0:
                    continue
                bonus = 1.0 + _THIRD_PARTY_BONUS_PER_AGREEING_SOURCE * agreeing_sources.get(cat, 0)
                signed = rel_weight * shared_importance * bonus
                if mine["conform"] == theirs["conform"]:
                    pressure[cat]["reinforce"] += signed
                else:
                    pressure[cat]["oppose"] += signed
                    # Count distinct opposing sources today (not just their
                    # combined magnitude) -- more agreeing-with-each-other
                    # trusted people pushing the same way should speed up
                    # the day-count side of the flip threshold too, not
                    # just the pressure magnitude side (see
                    # _apply_daily_value_pressure's reinforcement_count).
                    pressure[cat]["oppose_sources"] += 1 + agreeing_sources.get(cat, 0)

        _apply_daily_value_pressure(c, pressure, world)


def _count_agreeing_trusted_sources(c, exclude_id, reference, chars):
    """How many of `c`'s OTHER trusted relationships (trust > the same
    _TRUST_POSITIVE_GATE used above) share `reference`'s conform stance,
    per category -- the "people with similar values reinforce each
    other's influence on a third person" term."""
    from systems.schema_defaults import VALUE_CATEGORIES

    counts = {cat: 0 for cat in VALUE_CATEGORIES}
    for other_id, rel in c.get("relationships", {}).items():
        if other_id == exclude_id or rel.get("trust", 0) <= _TRUST_POSITIVE_GATE:
            continue
        third = chars.get(other_id)
        if not third or not third.get("values"):
            continue
        for cat in VALUE_CATEGORIES:
            ref_v = reference["values"].get(cat)
            third_v = third["values"].get(cat)
            if ref_v and third_v and ref_v["conform"] == third_v["conform"]:
                counts[cat] += 1
    return counts


def _apply_daily_value_pressure(c, pressure, world):
    from systems.schema_defaults import VALUE_CATEGORIES
    from systems.peer_influence import record_value_trait_exposure, CHILD_TRAIT_ACQUISITION_AGE_GROUPS

    tick = world.get("tick", 0)
    profile = c.setdefault("value_influence_profile", {})

    for cat in VALUE_CATEGORIES:
        p = pressure[cat]
        if p["reinforce"] == 0 and p["oppose"] == 0:
            continue  # no exposure signal for this category today

        v = c["values"][cat]
        net = max(-1.0, min(1.0, p["reinforce"] - p["oppose"]))
        v["importance"] = max(0.0, min(1.0, v["importance"] + net * VALUE_IMPORTANCE_STEP))

        # Conform: boolean, only flips once accumulated one-directional
        # OPPOSING pressure crosses a threshold and a minimum
        # reinforcement count -- mirrors peer_influence.py's
        # TRAIT_CONVERSION_THRESHOLD/MIN_REINFORCEMENTS shape exactly.
        entry = profile.setdefault(cat, {"pressure": 0.0, "reinforcement_count": 0, "last_tick": tick})
        if p["oppose"] > p["reinforce"]:
            entry["pressure"] = min(1.0, entry["pressure"] + min(0.1, p["oppose"] - p["reinforce"]))
            # More distinct opposing (and mutually-agreeing) trusted
            # sources today counts as more reinforcement, not just bigger
            # pressure -- this is what actually makes the third-party
            # reinforcement term speed up the flip, not just its
            # magnitude (reinforcement_count is otherwise a flat day
            # counter that would swamp any pressure-only bonus).
            entry["reinforcement_count"] += max(1, p["oppose_sources"])
        else:
            entry["pressure"] = max(0.0, entry["pressure"] - 0.05)
            entry["reinforcement_count"] = max(0, entry["reinforcement_count"] - 1)
        entry["last_tick"] = tick

        if (entry["pressure"] >= VALUE_CONFORM_FLIP_THRESHOLD
                and entry["reinforcement_count"] >= VALUE_CONFORM_MIN_REINFORCEMENTS):
            v["conform"] = not v["conform"]
            entry["pressure"] = 0.0
            entry["reinforcement_count"] = 0

        # Children/teens partly develop new personality traits from the
        # same daily exposure, not just shifted value scores -- see
        # systems/peer_influence.py::record_value_trait_exposure(). The
        # trait mapped reflects whichever direction dominated today: if
        # opposing pressure won, the child is being immersed in people
        # who hold the OPPOSITE conform stance, so that's what they're
        # absorbing; if reinforcing pressure won, it's their own current
        # stance being reinforced.
        if c.get("age_group") in CHILD_TRAIT_ACQUISITION_AGE_GROUPS:
            dominant_conform = v["conform"] if p["reinforce"] >= p["oppose"] else not v["conform"]
            record_value_trait_exposure(c, cat, dominant_conform, world)
