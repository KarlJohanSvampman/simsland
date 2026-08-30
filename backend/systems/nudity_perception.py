"""
systems/nudity_perception.py
─────────────────────────────
Handles three social-perception events:

  1. NUDITY SIGHTING — character sees another character who is nude
         (is_nude=True) or exposed (exposed_chest=True for females).
         Reaction depends on relationship, orientation, personality.

  2. WALKING IN ON SEX — character enters a room where an active
         intimate act (act_stage ≥ 4) is occurring.

  3. HEARING SEX SOUNDS — character is within SOUND_RADIUS of
         a room where climax/intense act is happening, even without
         visual line-of-sight. (Sound bleeds through walls.)

Tick cadence
────────────
  tick_nudity_perception(world)  — call once per game-minute (per tick)

Character fields read / written
────────────────────────────────
  c["is_nude"]                    — set by clothing.py
  c["exposed_chest"]              — set by clothing.py
  c["nudity_witnessed"]           — {observer_id: tick} on the nude character
  c["current_location"]           — room/zone id
  c["pending_reactions"]          — list consumed by frontend reaction renderer
  c["impulse_state"]["anger_pressure"] — raised if partner is nude with stranger
  c["intimacy_avoidance"]         — reduces aroused reaction
  world["active_sex_locations"]   — {location_id: {participants, act_stage, tick}}
                                    written by intimacy.py execute_act()
"""

import random

# ── Tunables ──────────────────────────────────────────────────────────────────
# How often (ticks) the same observer reacts to the same nude character
NUDITY_COOLDOWN_TICKS     = 60 * 20    # 20 game-minutes

# Sound bleeds this many "zones" away (same building assumed if same building_id)
SOUND_RADIUS_SAME_ROOM    = True       # always hears if same room
SOUND_BLEEDS_BUILDING     = True       # hears through walls within same building
SOUND_COOLDOWN_TICKS      = 60 * 10   # 10 min between sound reactions per observer

# Involuntary sounds (moaning etc) -- probabilistic, not "loud whenever
# act_stage>=5" as this used to hard-gate. Applies uniformly to partnered
# sex (by stage) and solo masturbation (treated as stage 4, see
# _build_sex_locations() below) -- checked once per
# tick_nudity_perception() pass per active session.
INVOLUNTARY_SOUND_CHANCE = {4: 0.03, 5: 0.15}
SOLO_SESSION_STAGE = 4  # masturbate/watch_porn have no negotiated act_stage

# Reaction weighting by relationship distance
REL_TYPES_INTIMATE   = {"partner", "spouse", "boyfriend", "girlfriend"}
REL_TYPES_FAMILY     = {"parent", "child", "sibling", "grandparent", "grandchild"}
REL_TYPES_FRIEND     = {"close_friend", "friend"}


# ── Public API ────────────────────────────────────────────────────────────────

def tick_nudity_perception(world):
    """Call every sim tick. Handles all three perception events."""
    tick       = world.get("tick", 0)
    characters = world.get("characters", {})
    by_loc     = world.get("characters_by_location", {})

    # Build index of active sex locations from world state
    sex_locs = world.get("active_sex_locations", {})

    # -- Rebuild active_sex_locations from character activities each tick.
    # Solo masturbate/watch_porn sessions count too (treated as
    # SOLO_SESSION_STAGE, same as partnered act_stage>=4) -- this is what
    # makes walking in on someone masturbating go through the exact same
    # reaction pipeline (shame_level, intrusion_reaction_female/male,
    # gendered escalation) as walking in on partnered sex, no separate
    # logic needed.
    sex_locs = {}
    for cid, c in characters.items():
        act = c.get("activity", {})
        if not act:
            continue
        interaction = act.get("interaction")
        if interaction in ("masturbate", "watch_porn"):
            stage = SOLO_SESSION_STAGE
        else:
            stage = act.get("act_stage", 0)
        if stage >= 4:
            loc = c.get("current_location")
            if loc:
                entry = sex_locs.setdefault(loc, {
                    "participants": [], "act_stage": stage, "tick": tick
                })
                entry["participants"].append(cid)
                entry["act_stage"] = max(entry["act_stage"], stage)
                # Involuntary sound roll -- climax-tier (5) is louder/more
                # frequent than early-stage (4); a hit this pass makes the
                # session audible through walls for THIS tick_nudity_
                # perception() pass (see the hearing check below).
                chance = INVOLUNTARY_SOUND_CHANCE.get(entry["act_stage"], 0.0)
                if random.random() < chance:
                    entry["_sound_this_pass"] = True
                    # The person(s) actually making the sound get their own
                    # reaction too -- previously only the OBSERVER's
                    # "heard it through the wall" reaction fired; the
                    # participant themselves never audibly reacted.
                    _push_reaction(c, "moan_pleasure", tick, world)
    world["active_sex_locations"] = sex_locs

    # Process each location that has occupants
    for loc_id, occupant_ids in by_loc.items():
        if not occupant_ids:
            continue

        occupants = [characters.get(cid) for cid in occupant_ids if characters.get(cid)]
        sex_here  = sex_locs.get(loc_id)

        for observer in occupants:
            o_id = observer.get("id")

            # Skip babies/very young
            if observer.get("age", 99) < 10:
                continue

            # ── 1. Nudity sighting ──────────────────────────────────────────
            for target in occupants:
                if target.get("id") == o_id:
                    continue
                if not (target.get("is_nude") or target.get("exposed_chest")):
                    continue

                # Cooldown check
                witnessed = target.setdefault("nudity_witnessed", {})
                last = witnessed.get(o_id, 0)
                if tick - last < NUDITY_COOLDOWN_TICKS:
                    continue

                witnessed[o_id] = tick
                _react_to_nudity(observer, target, world, tick)

            # ── 2. Walking in on sex ────────────────────────────────────────
            if sex_here:
                participants = sex_here.get("participants", [])
                if o_id not in participants:
                    last_walkin = observer.get("_last_walkin_react", 0)
                    if tick - last_walkin > NUDITY_COOLDOWN_TICKS:
                        observer["_last_walkin_react"] = tick
                        _react_to_walking_in(observer, participants, world, tick)

            # ── 3. Hearing sex sounds (same building, not same room) ─────────
            if SOUND_BLEEDS_BUILDING and not sex_here:
                building_id = observer.get("building_id")
                if building_id:
                    for sloc_id, sdata in sex_locs.items():
                        # Must be different room but same building
                        sloc_building = _get_location_building(sloc_id, world)
                        if sloc_building != building_id:
                            continue
                        if not sdata.get("_sound_this_pass"):   # no involuntary sound this pass
                            continue
                        last_sound = observer.get("_last_sound_react", 0)
                        if tick - last_sound < SOUND_COOLDOWN_TICKS:
                            continue
                        observer["_last_sound_react"] = tick
                        _react_to_sex_sounds(observer, sloc_id, world, tick)
                        break   # one reaction per tick


# ── Reaction handlers ──────────────────────────────────────────────────────────

def _react_to_nudity(observer, target, world, tick):
    """Observer sees target nude/exposed. Reaction depends on relationship."""
    o_id = observer.get("id")
    t_id = target.get("id")
    rel  = _get_rel(observer, t_id)
    rel_type = rel.get("relationship_type", "") if rel else ""

    is_family    = rel_type in REL_TYPES_FAMILY
    is_partner   = rel_type in REL_TYPES_INTIMATE
    is_stranger  = not rel or rel.get("trust", 0) < 0.20
    orientation  = observer.get("sexual_orientation", "heterosexual")
    target_sex   = target.get("sex", "male")
    observer_sex = observer.get("sex", "male")

    # Contextual: nudity expected (bathroom, intimacy history)
    # -- skip reaction if they've already been intimate
    intimacy_hist = observer.get("relationships", {}).get(t_id, {}).get("intimacy_history", [])
    if any(r.get("act_stage", 0) >= 5 for r in intimacy_hist):
        return   # they've had sex — nudity is not shocking

    # Determine reaction type
    if is_family:
        reaction = "shocked"
        _push_reaction(observer, reaction, tick, world)
        _add_shame_trauma_to_observer(observer, "accidental_family_nudity", 0.04, world)
    elif is_stranger:
        # Could be aroused or offended depending on orientation + sexism
        aroused = _would_be_aroused(observer, target)
        if aroused:
            reaction = "aroused_react"
        else:
            reaction = "saw_nudity"
        _push_reaction(observer, reaction, tick, world)
        if not aroused:
            _add_grievance(observer, t_id, "public_nudity", world)
        else:
            _awaken_libido(observer, world)
    else:
        # Friend / acquaintance — embarrassed
        _push_reaction(observer, "embarrassed", tick, world)
        _push_reaction(observer, "look_away", tick, world)

    # Emit event for LLM context
    _emit("nudity_witnessed", {
        "observer_id": o_id,
        "target_id":   t_id,
        "is_nude":     target.get("is_nude"),
        "exposed_chest": target.get("exposed_chest"),
        "reaction":    reaction if "reaction" in dir() else "embarrassed",
        "tick":        tick,
    }, world)

    # Partner jealousy — if observer's partner is nude with someone else
    _check_partner_nudity_jealousy(observer, target, world, tick)


def _react_to_walking_in(observer, participant_ids, world, tick):
    """
    Observer enters room mid-sex act.
    Two things happen:
      1. Observer reacts (shock, jealousy, trauma).
      2. Participants react to being walked in on — scaled by shame_level
         and gender of the intruder vs the participant.
    """
    o_id        = observer.get("id")
    observer_sex = observer.get("sex", "male")
    characters  = world.get("characters", {})

    # Classify relationship
    is_partner_involved = False
    is_family_involved  = False
    for pid in participant_ids:
        rel = _get_rel(observer, pid)
        rel_type = (rel or {}).get("relationship_type", "")
        if rel_type in REL_TYPES_INTIMATE:
            is_partner_involved = True
        if rel_type in REL_TYPES_FAMILY:
            is_family_involved = True

    # ── Observer reaction ──────────────────────────────────────────────────
    _push_reaction(observer, "walked_in_on_sex", tick, world)

    # This event never called store_memory() at all before -- meaning it
    # was invisible to systems/stories.py's worthiness evaluation
    # (which hooks off store_memory()) no matter how notable it was.
    try:
        from brain.memory import store_memory
        chars = world.get("characters", {})
        names = ", ".join(chars.get(pid, {}).get("name", pid) for pid in participant_ids)
        store_memory(
            observer, f"Walked in on {names}.", importance=0.75,
            tags=["walked_in_on", "caught"], kind="memory", tick=tick,
            people=list(participant_ids),
        )
    except Exception:
        pass

    if is_family_involved:
        _add_shame_trauma_to_observer(observer, "walked_in_on_family_sex", 0.12, world)
    elif is_partner_involved:
        _emit("possible_affair_discovered", {
            "observer_id":     o_id,
            "participant_ids": participant_ids,
            "tick":            tick,
        }, world)
        imp = observer.setdefault("impulse_state", {})
        imp["anger_pressure"] = min(1.0, imp.get("anger_pressure", 0) + 0.50)
    else:
        _push_reaction(observer, "embarrassed", tick, world)

    # ── Participant reactions (person being walked in on) ──────────────────
    # Get shame_level from the active interaction template
    shame_level = _get_active_shame_level(participant_ids, world)

    for pid in participant_ids:
        participant = characters.get(pid)
        if not participant:
            continue
        p_sex = participant.get("sex", "male")

        # Intruder is a man walking in on a woman → most dramatic
        intruder_is_male = observer_sex == "male"
        intruder_is_stranger = not _get_rel(participant, o_id) or             _get_rel(participant, o_id).get("trust", 0) < 0.30

        # Pick reaction from interaction template or default
        act = participant.get("activity", {})
        act_id = act.get("interaction", "")
        defs = world.get("definitions", {})
        tpl  = defs.get("interaction_templates", {}).get(act_id, {})

        if p_sex in ("female", "intersex"):
            base_reaction = tpl.get("intrusion_reaction_female", "embarrassed_scream")
            # Man stranger walking in → most severe
            if intruder_is_male and intruder_is_stranger and shame_level >= 3:
                base_reaction = "horrified_scream"
            elif intruder_is_male and shame_level >= 2:
                base_reaction = "embarrassed_scream"
        else:
            base_reaction = tpl.get("intrusion_reaction_male", "embarrassed")
            if intruder_is_stranger and shame_level >= 4:
                base_reaction = "shocked"

        _push_reaction(participant, base_reaction, tick, world)

        # Shame trauma scaled by shame_level (0–4 → 0–0.10)
        if shame_level >= 2 and intruder_is_stranger:
            severity = 0.02 * shame_level
            _add_shame_trauma_to_observer(participant, "walked_in_on_during_sex", severity, world)

        # Emit for LLM context
        _emit("walked_in_on", {
            "participant_id": pid,
            "observer_id":    o_id,
            "shame_level":    shame_level,
            "observer_sex":   observer_sex,
            "tick":           tick,
        }, world)

    # ── Shared event ──────────────────────────────────────────────────────
    _emit("walked_in_on_sex", {
        "observer_id":      o_id,
        "participant_ids":  participant_ids,
        "is_family":        is_family_involved,
        "is_partner":       is_partner_involved,
        "shame_level":      shame_level,
        "tick":             tick,
    }, world)

    # Observer leaves room
    try:
        from brain.intentions import add_intention
        add_intention(observer, {
            "type":     "leave_location",
            "reason":   "walked_in_on_sex",
            "priority": 90,
        }, world)
    except Exception:
        pass


def _react_to_sex_sounds(observer, source_loc_id, world, tick):
    """Observer hears sex through the wall."""
    o_id = observer.get("id")

    # Check if any participant is observer's partner
    sex_locs     = world.get("active_sex_locations", {})
    sdata        = sex_locs.get(source_loc_id, {})
    participants = sdata.get("participants", [])

    is_partner_involved = any(
        _get_rel(observer, pid) and
        _get_rel(observer, pid).get("relationship_type", "") in REL_TYPES_INTIMATE
        for pid in participants
    )

    _push_reaction(observer, "heard_sex_sounds", tick, world)

    if is_partner_involved:
        _emit("possible_affair_discovered_sound", {
            "observer_id":     o_id,
            "participant_ids": participants,
            "tick":            tick,
        }, world)
        imp = observer.setdefault("impulse_state", {})
        imp["anger_pressure"] = min(1.0, imp.get("anger_pressure", 0) + 0.30)

    _emit("heard_sex_sounds", {
        "observer_id":  o_id,
        "source_loc":   source_loc_id,
        "is_partner":   is_partner_involved,
        "tick":         tick,
    }, world)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_active_shame_level(participant_ids, world):
    """Return the shame_level of the interaction currently being performed."""
    characters = world.get("characters", {})
    defs       = world.get("definitions", {})
    for pid in participant_ids:
        c   = characters.get(pid)
        if not c:
            continue
        act    = c.get("activity", {})
        act_id = act.get("interaction", "")
        tpl    = defs.get("interaction_templates", {}).get(act_id, {})
        level  = tpl.get("shame_level")
        if level is not None:
            return level
    return 3   # default: high


def _push_reaction(c, reaction_type, tick, world=None):
    """Queue a reaction animation onto the character for the frontend to
    play. Was writing to c["pending_reactions"] -- a dead-end queue the
    frontend never actually reads (confirmed: only c["animation_reaction"],
    written by systems/reactions.py::process_reaction_queue(), is
    consumed by main.js) -- every nudity/walked-in-on/sex-sound reaction
    in this module was therefore invisible to the player until this fix.
    Now delegates to the real, live system; world (when available) also
    gets the involuntary-sound/mood bundle via trigger_reaction()."""
    try:
        if world is not None:
            from systems.reactions import trigger_reaction
            trigger_reaction(c, world, reaction_type, tick=tick)
        else:
            from systems.reactions import push_reaction
            push_reaction(c, reaction_type, tick)
    except Exception:
        pass


def _get_rel(observer, target_id):
    return observer.get("relationships", {}).get(target_id)


def _get_location_building(loc_id, world):
    locs = world.get("locations", {})
    loc  = locs.get(loc_id, {})
    return loc.get("building_id")


def _awaken_libido(observer, world):
    """Unexpectedly seeing someone attractive nude/exposed nudges
    systems/libido.py's standalone need directly, on top of the
    aroused_react animation -- a real, if minor, spike toward "seeking
    release" rather than just a one-off flavor reaction."""
    try:
        from systems.libido import ensure_libido_state
        state = ensure_libido_state(observer)
        state["current"] = min(1.0, state.get("current", 0.0) + 0.15)
    except Exception:
        pass


def _would_be_aroused(observer, target):
    """True if observer would find unexpected nudity arousing rather than offensive."""
    orientation = observer.get("sexual_orientation", "heterosexual")
    o_sex       = observer.get("sex", "male")
    t_sex       = target.get("sex", "male")
    avoidance   = observer.get("intimacy_avoidance", 0.0)
    libido      = (observer.get("attraction_profile") or {}).get("libido", 0.5)

    # Orientation match
    attracted = False
    if orientation == "heterosexual":
        attracted = (o_sex == "male" and t_sex in ("female", "intersex")) or \
                    (o_sex == "female" and t_sex == "male")
    elif orientation == "homosexual":
        attracted = (o_sex == t_sex)
    elif orientation in ("bisexual", "pansexual"):
        attracted = True

    if not attracted:
        return False
    if avoidance > 0.50:
        return False
    return libido > 0.40


def _check_partner_nudity_jealousy(observer, target, world, tick):
    """If observer's partner is nude in front of strangers, spike anger."""
    observer_rels = observer.get("relationships", {})
    t_id = target.get("id")

    for pid, rel in observer_rels.items():
        if rel.get("relationship_type") not in REL_TYPES_INTIMATE:
            continue
        # observer's partner is the nude person
        if pid == t_id:
            t_rels = target.get("relationships", {})
            obs_id = observer.get("id")
            obs_rel = t_rels.get(obs_id, {})
            trust = obs_rel.get("trust", 0.5)
            # Low trust → anger
            if trust < 0.60:
                imp = observer.setdefault("impulse_state", {})
                imp["anger_pressure"] = min(1.0, imp.get("anger_pressure", 0) + 0.25)
            break


def _add_shame_trauma_to_observer(observer, trauma_type, severity, world):
    try:
        from systems.trauma import add_trauma_event
        add_trauma_event(observer, trauma_type, None, world, severity_override=severity)
    except Exception:
        pass


def _add_grievance(observer, target_id, gtype, world):
    try:
        from systems.grievances import add_grievance
        add_grievance(observer, target_id, gtype, world)
    except Exception:
        pass


def _emit(event_type, data, world):
    try:
        from core.events import emit
        emit(event_type, data, world)
    except Exception:
        pass
