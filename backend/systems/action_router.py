# =========================================================
# ACTION ROUTER
# Translates LLM action + speech output into world state
# changes. Called from agent_loop.process_decision.
# =========================================================

import time

from systems.activities import get_phase_animation, get_clean_animation


# =========================================================
# SPEECH BUBBLE DURATION (sim ticks)
# =========================================================

SPEECH_BUBBLE_TICKS = 8   # how many ticks the bubble stays visible


# =========================================================
# ANIMATION STATE MAP
# Maps action type → animation_state string used by frontend
# =========================================================

_ACTION_ANIMATION = {
    "interact":   "interact",
    "eat":        "eat",
    "sleep":      "sleep",
    "work":       "work",
    "socialize":  "talk",
    "speak":      "talk",
    "move":       "walk",
    "wait":       "idle",
    "call":       "phone",
    "text":       "phone",
}


# =========================================================
# APPLY SPEECH
# Stores utterance on the character so the frontend can
# display it as a speech bubble.
# =========================================================

def apply_speech(c, world, speech):
    """
    speech = {
        "target":      str | None,
        "speech_act":  str,   e.g. "greet", "ask", "declare"
        "topic":       str,
        "utterance":   str    -- the actual text to display
    }
    """
    if not speech:
        return

    utterance = speech.get("utterance", "").strip()
    if not utterance:
        return

    tick = world.get("tick", 0)

    c["current_speech"] = {
        "utterance":      utterance,
        "speech_act":     speech.get("speech_act", "speak"),
        "topic":          speech.get("topic", ""),
        "target":         speech.get("target"),
        "expires_at_tick": tick + SPEECH_BUBBLE_TICKS,
    }

    # Store in conversation log too
    c.setdefault("speech_log", [])
    c["speech_log"].append({
        "tick":      tick,
        "utterance": utterance,
        "target":    speech.get("target"),
    })
    c["speech_log"] = c["speech_log"][-20:]   # keep last 20


# =========================================================
# CLEAR EXPIRED SPEECH
# Call each tick to expire speech bubbles.
# =========================================================

def clear_expired_speech(c, world):
    tick = world.get("tick", 0)
    speech = c.get("current_speech")
    if speech and tick >= speech.get("expires_at_tick", 0):
        c["current_speech"] = None


# =========================================================
# ROUTE MOVE
# =========================================================

def _route_move(c, world, action):
    target_id = action.get("target")
    if not target_id:
        return

    # Find target position from characters or props
    chars = world.get("characters", {})
    if target_id in chars:
        t = chars[target_id]
        c["move_target"] = {
            "x": t.get("x", 0),
            "y": t.get("y", 0),
            "target_id": target_id,
            "target_type": "character",
        }
        return

    props = world.get("props", {})
    if target_id in props:
        p = props[target_id]
        c["move_target"] = {
            "x": p.get("x", 0),
            "y": p.get("y", 0),
            "target_id": target_id,
            "target_type": "prop",
        }
        return


# =========================================================
# SCAFFOLD ACTIVITY
# Wraps a bare activity dict in the phase/duration/tick
# fields that execute_activity() requires.
# =========================================================

_INTERACTION_DURATIONS = {
    "sit":        1800,
    "sleep":      28800,
    "eat":        720,
    "cook":       1200,
    "work":       28800,
    "interact":   600,
    "wait":       120,
}

def _scaffold(c, world, activity_type, target_id=None,
              interaction=None, duration=None):
    """Return a fully scaffolded activity dict."""
    if duration is None:
        duration = _INTERACTION_DURATIONS.get(
            interaction or activity_type,
            600
        )

    act = {
        "type":               activity_type,
        "phase":              "using",      # router actions start at 'using' (already at target)
        "phase_started_tick": world.get("tick", 0),
        "duration":           duration,
        "state":              {},
    }

    if target_id:
        act["target_id"] = target_id

    if interaction:
        act["interaction"] = interaction

    return act


# =========================================================
# ROUTE INTERACT
# =========================================================

def _route_interact(c, world, action, definitions):
    target_id = action.get("target")
    if not target_id:
        return

    props = world.get("props", {})
    # props may be a dict keyed by id or a list
    if isinstance(props, list):
        prop = next((p for p in props if p.get("id") == target_id), None)
    else:
        prop = props.get(target_id)

    if not prop:
        return

    # prefer interaction specified by the LLM, then fall back to definition
    interaction = action.get("interaction")

    if not interaction:
        template_id = prop.get("template")
        tpl = (
            definitions
            .get("prop_templates", {})
            .get(template_id, {})
        )
        for anchor in tpl.get("anchors", []):
            interaction = anchor.get("interaction")
            if interaction:
                break

    c["activity"] = _scaffold(
        c, world, "interact",
        target_id=target_id,
        interaction=interaction,
    )

    # Set per-interaction using-phase animation immediately
    if interaction:
        c["animation_state"] = get_phase_animation(interaction, "using")

    # mark prop occupied
    prop["occupied_by"] = c["id"]


# =========================================================
# ROUTE EAT
# =========================================================

def _route_eat(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "eat",
        target_id=target_id,
        interaction="eat",
    )


# =========================================================
# ROUTE SLEEP
# =========================================================

def _route_sleep(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "sleep",
        target_id=target_id,
        interaction="sleep",
    )


# =========================================================
# ROUTE WAIT
# =========================================================

def _route_wait(c, world, action):
    ticks = action.get("duration", 120)
    c["activity"] = _scaffold(
        c, world, "wait",
        interaction="wait",
        duration=ticks,
    )


# =========================================================
# ROUTE EXAMINE / INSPECT
# =========================================================

def _route_examine(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "examine",
        target_id=target_id,
        interaction="examine",
        duration=180,
    )
    c["animation_state"] = get_phase_animation("examine", "using")


# =========================================================
# ROUTE SEARCH FOR ITEM
# =========================================================

def _route_search(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "search",
        target_id=target_id,
        interaction="search",
        duration=600,
    )
    c["animation_state"] = get_phase_animation("search", "using")


# =========================================================
# ROUTE TRASH / DESTROY
# =========================================================

def _route_trash(c, world, action):
    target_id = action.get("target")
    interaction = "trash" if action.get("type") == "trash" else "destroy"
    c["activity"] = _scaffold(
        c, world, action.get("type", "trash"),
        target_id=target_id,
        interaction=interaction,
        duration=120,
    )
    c["animation_state"] = get_phase_animation(interaction, "using")


# =========================================================
# ROUTE CARRY
# Character picks up target prop and walks it to destination.
# LLM action must include:
#   target:      prop_id to carry
#   destination: { x, y } tile to deliver to
# =========================================================

def _route_carry(c, world, action):
    target_id = action.get("target")
    if not target_id:
        return

    props = world.get("props", {})
    prop = props.get(target_id) if isinstance(props, dict) else next(
        (p for p in props if p.get("id") == target_id), None
    )

    if not prop:
        return

    # Only carry props flagged carryable (or small by default)
    if not prop.get("carryable", True):
        return

    dest = action.get("destination", {})

    act = _scaffold(
        c, world, "carry",
        target_id=target_id,
        interaction="carry",
        duration=0,    # duration not used; phase logic drives carry
    )
    act["phase"] = "walking"           # walk to prop first
    act["destination"] = dest
    act["phase_started_tick"] = world.get("tick", 0)

    # Route character to the prop's current position
    c["move_target"] = {
        "x": prop.get("x", 0),
        "y": prop.get("y", 0),
        "target_id": target_id,
        "target_type": "prop",
    }
    c["is_moving"] = True
    c["activity"] = act
    c["animation_state"] = "walk"


# =========================================================
# ROUTE CLEAN
# Picks the correct animation based on the target prop's tags.
# =========================================================

def _route_clean(c, world, action, definitions):
    target_id = action.get("target")

    props = world.get("props", {})
    prop = props.get(target_id) if isinstance(props, dict) else next(
        (p for p in props if p.get("id") == target_id), None
    )

    c["activity"] = _scaffold(
        c, world, "clean",
        target_id=target_id,
        interaction="clean",
        duration=900,
    )

    # Use prop-aware animation immediately
    c["animation_state"] = get_clean_animation(prop, "using") if prop else "clean_generic"


# =========================================================
# ROUTE WEAR / UNDRESS
# Put on / take off clothing items from the character's personal inventory.
# action = { "type": "wear",    "item_id": "item_tshirt_abc123" }
# action = { "type": "undress", "slot": "torso" }   or omit slot to undress all
# =========================================================

def _route_wear(c, world, action, definitions=None):
    from systems.clothing import put_on_clothing
    item_id = action.get("item_id")
    if not item_id:
        return
    result = put_on_clothing(c, world, item_id)
    if result.get("swapped_off"):
        # Old item already returned to inventory by put_on_clothing
        pass


def _route_undress(c, world, action):
    from systems.clothing import take_off_clothing, undress_all
    slot = action.get("slot")
    if slot:
        take_off_clothing(c, world, slot)
    else:
        undress_all(c, world)



# =========================================================
# ASSEMBLE PROP
# action = { "type": "assemble_prop", "item_id": "item_box_modern_sofa_abc" }
# =========================================================

def _route_assemble_prop(c, world, action):
    from systems.assembly import assemble_prop
    item_id = action.get("item_id")
    if not item_id:
        return
    assemble_prop(c, world, item_id)


# =========================================================
# ASSEMBLE TILE
# action = { "type": "assemble_tile", "item_id": "item_box_wood_floor_01_abc" }
# Places one tile at character's current position; decrements box quantity.
# =========================================================

def _route_assemble_tile(c, world, action):
    from systems.assembly import assemble_tile
    item_id = action.get("item_id")
    if not item_id:
        return
    assemble_tile(c, world, item_id)


# =========================================================
# HIRE SERVICE
# action = {
#   "type":         "hire_service",
#   "service_type": "reconstruction",
#   "subtype":      "floor_tiling",
#   "details":      {"tiles": [{"x":1,"y":2,"material":"wood_floor_01"}, ...]},
#   "quantity":     5
# }
# Legitimate services bill via mailbox; illicit deduct cash immediately.
# =========================================================

def _route_hire_service(c, world, action):
    from systems.services import request_service
    request_service(
        c, world,
        service_type=action.get("service_type"),
        subtype=action.get("subtype"),
        details=action.get("details", {}),
        quantity=action.get("quantity", 1),
    )


# =========================================================
# MAIN ROUTER
# =========================================================

def route_action(c, world, action, speech, definitions=None):
    """
    Dispatch the LLM's action and speech into world state.

    action = {
        "type":   str,
        "target": str | None,
        "reason": str | None,
    }
    speech = {
        "utterance": str,
        ...
    }
    definitions = world["definitions"] (optional, for prop lookups)
    """
    if definitions is None:
        definitions = world.get("definitions", {})

    # Always apply speech first so it displays even if action fails
    if speech:
        apply_speech(c, world, speech)

    if not action:
        return

    action_type = action.get("type", "")

    if action_type == "move":
        _route_move(c, world, action)

    elif action_type == "interact":
        _route_interact(c, world, action, definitions)

    elif action_type in ("speak", "socialize"):
        # Speech was already applied above.
        # Also point character toward target if given.
        target_id = action.get("target")
        if target_id:
            chars = world.get("characters", {})
            if target_id in chars:
                t = chars[target_id]
                c["look_target"] = {
                    "x": t.get("x", 0),
                    "y": t.get("y", 0),
                }

    elif action_type == "eat":
        _route_eat(c, world, action)

    elif action_type == "sleep":
        _route_sleep(c, world, action)

    elif action_type == "wait":
        _route_wait(c, world, action)

    elif action_type == "work":
        c["activity"] = _scaffold(c, world, "work", interaction="work")

    elif action_type == "examine":
        _route_examine(c, world, action)

    elif action_type == "search":
        _route_search(c, world, action)

    elif action_type in ("trash", "destroy"):
        _route_trash(c, world, action)

    elif action_type == "carry":
        _route_carry(c, world, action)

    elif action_type == "clean":
        _route_clean(c, world, action, definitions)

    elif action_type == "wear":
        _route_wear(c, world, action, definitions)

    elif action_type == "undress":
        _route_undress(c, world, action)

    elif action_type == "assemble_prop":
        _route_assemble_prop(c, world, action)

    elif action_type == "assemble_tile":
        _route_assemble_tile(c, world, action)

    elif action_type == "hire_service":
        _route_hire_service(c, world, action)

    elif action_type == "build_wall":
        _route_build_wall(c, world, action)

    elif action_type == "remove_wall":
        _route_remove_wall(c, world, action)

    elif action_type == "paint_wall":
        _route_paint_wall(c, world, action)

    # ── Phone ──────────────────────────────────────────────────────────────────
    elif action_type == "phone_call":
        _route_phone_call(c, world, action)
    elif action_type == "phone_answer":
        _route_phone_answer(c, world, action)
    elif action_type == "phone_send_text":
        _route_phone_send_text(c, world, action)
    elif action_type in ("phone_check", "call", "text"):
        _route_phone_check(c, world, action)
    elif action_type == "phone_read_text":
        _route_phone_read_text(c, world, action)

    # ── Computer ───────────────────────────────────────────────────────────────
    elif action_type == "computer_social_media":
        _route_computer(c, world, action, "computer_social_media")
    elif action_type == "computer_videos":
        _route_computer(c, world, action, "computer_videos")
    elif action_type == "computer_game":
        _route_computer(c, world, action, "computer_game")
    elif action_type == "computer_wiki_research":
        _route_computer_wiki_research(c, world, action)
    elif action_type == "computer_window_shopping":
        _route_computer(c, world, action, "computer_window_shopping")
    elif action_type == "computer_dating":
        _route_computer(c, world, action, "computer_dating")
    elif action_type == "computer_job_search":
        _route_computer_job_search(c, world, action)
    elif action_type == "computer_apply_for_job":
        _route_computer_apply_for_job(c, world, action)
    elif action_type in ("computer_send_email", "computer_respond_email", "computer_check_email"):
        _route_computer_email(c, world, action)
    elif action_type == "computer_list_stocks":
        _route_computer_list_stocks(c, world, action)
    elif action_type == "computer_buy_stock":
        _route_computer_buy_stock(c, world, action)
    elif action_type == "computer_sell_stock":
        _route_computer_sell_stock(c, world, action)
    elif action_type == "computer_check_stock_value":
        _route_computer_check_stock_value(c, world, action)
    elif action_type == "computer_order_item":
        _route_computer_order_item(c, world, action)
    elif action_type == "computer_order_service":
        _route_computer_order_service(c, world, action)
    elif action_type == "social_browse_events":
        _route_social_browse_events(c, world, action)
    elif action_type == "social_event_rsvp":
        _route_social_event_rsvp(c, world, action)
    elif action_type == "social_event_comment":
        _route_social_event_comment(c, world, action)
    elif action_type == "social_event_attend":
        _route_social_event_attend(c, world, action)
    elif action_type == "social_event_plan":
        _route_social_event_plan(c, world, action)
    elif action_type == "organize_hobby_session":
        _route_organize_hobby_session(c, world, action)
    elif action_type == "plan_hobby_session":
        _route_plan_hobby_session(c, world, action)

# =========================================================
# PHONE HANDLERS
# =========================================================

def _require_phone(c):
    """Return phone item if usable, else None."""
    from systems.personal_items import get_phone, phone_is_usable
    phone = get_phone(c)
    if not phone or not phone_is_usable(c):
        return None
    return phone


def _route_phone_call(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    target_id = action.get("target_id") or action.get("target")
    c["activity"] = _scaffold(c, world, "phone_call",
                               target_id=target_id, interaction="phone_call")


def _route_phone_answer(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    c["activity"] = _scaffold(c, world, "phone_answer", interaction="phone_answer")


def _route_phone_send_text(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    target_id = action.get("target_id") or action.get("target")
    message   = action.get("message", "")
    if target_id and message:
        from systems.social import send_message
        target = world.get("characters", {}).get(target_id)
        if target:
            send_message(c, target, message, world)
    c["activity"] = _scaffold(c, world, "phone_send_text", interaction="phone_send_text")


def _route_phone_check(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    c["activity"] = _scaffold(c, world, "phone_check", interaction="phone_check")
    # Expose missed calls/messages count in activity data
    missed = len(c.get("social", {}).get("missed_calls", []))
    unread = sum(1 for m in world.get("messages", [])
                 if m.get("to_id") == c["id"] and not m.get("read"))
    c["activity"]["phone_check_result"] = {"missed_calls": missed, "unread_messages": unread}


def _route_phone_read_text(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    msg_id = action.get("message_id") or action.get("target")
    if msg_id:
        for m in world.get("messages", []):
            if m.get("id") == msg_id and m.get("to_id") == c["id"]:
                m["read"] = True
    c["activity"] = _scaffold(c, world, "phone_read_text", interaction="phone_read_text")


# =========================================================
# DEVICE CHARGING
# =========================================================

def _route_charge_device(c, world, action):
    """
    Start charging. The phone.charge_phone() is called each tick by phone.py
    while activity interaction == "charge". Requires phone_charger in inventory.
    """
    from systems.personal_items import has_item_template
    if not has_item_template(c, "phone_charger"):
        return
    target_prop_id = action.get("target") or action.get("prop_id")
    c["activity"] = _scaffold(c, world, "charge", target_id=target_prop_id,
                               interaction="charge",
                               duration=_INTERACTION_DURATIONS.get("charge", 60))


# =========================================================
# POSTURE
# =========================================================

def _route_sit_down(c, world, action):
    c["activity"] = _scaffold(c, world, "sit_down_seat",
                               target_id=action.get("target"),
                               interaction="sit_down_seat")
    c["posture"] = "sitting"


def _route_stand_up(c, world, action):
    c["posture"] = "standing"
    act = c.get("activity", {})
    if act.get("interaction") in ("sit_down_seat", "lie_down", "sleep"):
        c["activity"] = None


def _route_lie_down(c, world, action):
    c["activity"] = _scaffold(c, world, "lie_down",
                               target_id=action.get("target"),
                               interaction="lie_down")
    c["posture"] = "lying"


# =========================================================
# TRANSPORT
# =========================================================

def _route_drive_car_to(c, world, action):
    destination = action.get("destination") or action.get("target")
    c["activity"] = _scaffold(c, world, "drive_car_to",
                               target_id=action.get("target"),
                               interaction="drive_car_to",
                               duration=_INTERACTION_DURATIONS.get("drive", 120))
    c["activity"]["destination"] = destination
    # Mark as offgrid so sim_loop can skip position updates
    c["offgrid"] = True
    c["offgrid_destination"] = destination


# =========================================================
# COMPUTER — generic scaffold
# =========================================================

def _route_computer(c, world, action, interaction_id):
    c["activity"] = _scaffold(c, world, interaction_id,
                               target_id=action.get("target"),
                               interaction=interaction_id)


# ─── wikipedia research ───────────────────────────────────────────────────────

def _route_computer_wiki_research(c, world, action):
    keyword = action.get("keyword") or action.get("args", {}).get("keyword", "")
    c["activity"] = _scaffold(c, world, "computer_wiki_research",
                               interaction="computer_wiki_research")
    c["activity"]["research_keyword"] = keyword

    if not keyword:
        return

    # Live Wikipedia API call — store result in character memory
    try:
        import urllib.request, urllib.parse, json as _json
        params  = urllib.parse.urlencode({
            "action": "query", "format": "json", "prop": "extracts",
            "exintro": True, "explaintext": True, "redirects": True,
            "titles": keyword,
        })
        url = f"https://en.wikipedia.org/w/api.php?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Holosims/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read())
        pages = data.get("query", {}).get("pages", {})
        page  = next(iter(pages.values()), {})
        extract = (page.get("extract") or "")[:800]
        if extract:
            c.setdefault("knowledge", []).append({
                "topic":   keyword,
                "summary": extract,
                "tick":    world.get("tick", 0),
            })
            c["knowledge"] = c["knowledge"][-30:]
            c["activity"]["research_result"] = extract[:200]
    except Exception:
        pass   # silently ignore network failures in sim tick


# ─── job search / apply ───────────────────────────────────────────────────────

def _route_computer_job_search(c, world, action):
    listings = world.get("job_listings", [])
    c["activity"] = _scaffold(c, world, "computer_job_search", interaction="computer_job_search")
    c["activity"]["job_listings"] = listings[:10]


def _route_computer_apply_for_job(c, world, action):
    from systems.jobs import apply_for_job
    job_id = action.get("job_id") or action.get("target")
    c["activity"] = _scaffold(c, world, "computer_apply_for_job",
                               interaction="computer_apply_for_job")
    if job_id:
        apply_for_job(c, job_id, world)


# ─── email ────────────────────────────────────────────────────────────────────

def _route_computer_email(c, world, action):
    atype = action.get("type", "computer_check_email")
    c["activity"] = _scaffold(c, world, atype, interaction=atype)
    if atype == "computer_send_email":
        # Queue email as a world message
        to   = action.get("to", "")
        subj = action.get("subject", "")
        body = action.get("body", "")
        world.setdefault("emails", []).append({
            "from_id":  c["id"],
            "to":       to,
            "subject":  subj,
            "body":     body,
            "tick":     world.get("tick", 0),
            "read":     False,
        })


# ─── stocks ───────────────────────────────────────────────────────────────────

def _route_computer_list_stocks(c, world, action):
    portfolio = c.get("portfolio", {})
    from systems.stock_market import get_stock_price
    summary = {}
    for ticker, pos in portfolio.items():
        price = get_stock_price(world, ticker)
        shares = pos.get("shares", 0)
        avg    = pos.get("avg_buy_price", price)
        summary[ticker] = {
            "shares": shares,
            "current_price": price,
            "avg_buy_price": avg,
            "gain_pct": round((price - avg) / avg * 100, 1) if avg else 0,
            "value": round(shares * price, 2),
        }
    c["activity"] = _scaffold(c, world, "computer_list_stocks",
                               interaction="computer_list_stocks")
    c["activity"]["portfolio"] = summary


def _route_computer_buy_stock(c, world, action):
    from systems.investments import buy_stock
    from systems.stock_market import get_stock_price
    ticker     = (action.get("ticker") or action.get("target", "")).upper()
    shares     = int(action.get("shares", 1))
    c["activity"] = _scaffold(c, world, "computer_buy_stock",
                               interaction="computer_buy_stock")
    if ticker:
        price      = get_stock_price(world, ticker)
        cash_amount = shares * price
        result     = buy_stock(c, world, ticker, cash_amount)
        c["activity"]["transaction_result"] = result


def _route_computer_sell_stock(c, world, action):
    from systems.investments import sell_stock
    ticker = (action.get("ticker") or action.get("target", "")).upper()
    shares = int(action.get("shares", 0)) or None
    c["activity"] = _scaffold(c, world, "computer_sell_stock",
                               interaction="computer_sell_stock")
    if ticker:
        result = sell_stock(c, world, ticker, shares)
        c["activity"]["transaction_result"] = result


def _route_computer_check_stock_value(c, world, action):
    from systems.stock_market import get_stock_price
    ticker = (action.get("ticker") or action.get("target", "")).upper()
    c["activity"] = _scaffold(c, world, "computer_check_stock_value",
                               interaction="computer_check_stock_value")
    if ticker:
        price = get_stock_price(world, ticker)
        c["activity"]["stock_price"] = {"ticker": ticker, "price": price}


# ─── order item / service ─────────────────────────────────────────────────────

def _route_computer_order_item(c, world, action):
    template_id = action.get("template_id") or action.get("target", "")
    quantity    = int(action.get("quantity", 1))
    c["activity"] = _scaffold(c, world, "computer_order_item",
                               interaction="computer_order_item")
    if template_id:
        # Use schedule_delivery_item via catalog_id lookup
        from systems.procurement import schedule_delivery_item
        household = world.get("households", {}).get(c.get("household_id"))
        if household:
            try:
                schedule_delivery_item(household, template_id, world)
                c["activity"]["order_result"] = {"success": True, "template_id": template_id}
            except Exception as e:
                c["activity"]["order_result"] = {"success": False, "error": str(e)}


def _route_computer_order_service(c, world, action):
    # service_id maps to service_type; use first subtype by default
    service_type = action.get("service_id") or action.get("service_type") or action.get("target", "")
    c["activity"] = _scaffold(c, world, "computer_order_service",
                               interaction="computer_order_service")
    if service_type:
        from systems.services import request_service
        # request_service(c, world, service_type, subtype, details, quantity=1)
        subtype = action.get("subtype", "")
        details = action.get("details", {})
        try:
            result = request_service(c, world, service_type, subtype, details)
            c["activity"]["service_result"] = result
        except Exception as e:
            c["activity"]["service_result"] = {"success": False, "error": str(e)}


def _route_computer_list_service_options(c, world, action):
    from data.services import SERVICE_CATALOG
    service_type = (action.get("service_type") or action.get("args", {}).get("service_type") or "").lower()
    c["activity"] = _scaffold(c, world, "computer_list_service_options",
                               interaction="computer_list_service_options")
    options = {}
    for sid, svc in SERVICE_CATALOG.items():
        if not service_type or service_type in sid or service_type in svc.get("category","").lower():
            options[sid] = {"name": svc.get("name", sid), "price": svc.get("price_per_hour", 0)}
    c["activity"]["service_options"] = options


# =========================================================
# UNIVERSAL ITEM ACTIONS
# =========================================================

def _route_drop_item(c, world, action):
    """Drop an item at the character's current position."""
    from systems.personal_items import drop_item, get_item_by_id, get_phone
    item_id = action.get("item_id") or action.get("target")
    if not item_id:
        return
    drop_item(c, item_id, world)


def _route_put_down_item(c, world, action):
    """Place an item at a specific position."""
    from systems.personal_items import place_item
    item_id = action.get("item_id") or action.get("target")
    x = int(action.get("x", c.get("x", 0)))
    y = int(action.get("y", c.get("y", 0)))
    if item_id:
        place_item(c, item_id, x, y, world)


def _route_give_item(c, world, action):
    """Give an item to another character."""
    from systems.personal_items import give_item
    item_id   = action.get("item_id") or action.get("item")
    target_id = action.get("target")
    receiver  = world.get("characters", {}).get(target_id)
    if item_id and receiver:
        give_item(c, receiver, item_id, world)


def _route_pick_up_item(c, world, action):
    """Pick up an item that is placed in the world."""
    from systems.personal_items import pick_up_item
    item_id = action.get("item_id") or action.get("target")
    if item_id:
        pick_up_item(c, item_id, world)


def _route_break_item(c, world, action):
    """Destroy an item — removes from inventory or world."""
    from systems.personal_items import break_item
    item_id = action.get("item_id") or action.get("target")
    if item_id:
        break_item(c, item_id, world)


# =========================================================

# =========================================================
# SOCIAL EVENTS
# =========================================================

def _route_social_browse_events(c, world, action):
    """Discover events while browsing social media or scrolling phone."""
    from systems.social_events import maybe_discover_events
    channel = action.get("channel", "social_media")
    found   = maybe_discover_events(c, world, channel=channel)
    if found:
        c["last_discovered_events"] = found


def _route_social_event_rsvp(c, world, action):
    """RSVP to an event: yes / no / maybe."""
    from systems.social_events import rsvp
    event_id  = action.get("event_id") or action.get("args", {}).get("event_id")
    response  = action.get("response") or action.get("args", {}).get("response", "yes")
    decide_ts = action.get("decide_ts") or action.get("args", {}).get("decide_ts")
    if event_id and response in ("yes", "no", "maybe"):
        rsvp(c, world, event_id, response, decide_ts=decide_ts)


def _route_social_event_comment(c, world, action):
    """Comment or react to an event post."""
    from systems.social_events import add_comment, react_comment, get_event
    event_id = action.get("event_id") or action.get("args", {}).get("event_id")
    text     = action.get("text") or action.get("args", {}).get("text", "")
    reaction = action.get("reaction") or action.get("args", {}).get("reaction")
    if not event_id:
        return
    if text:
        add_comment(c, world, event_id, text)
    if reaction in ("like", "dislike"):
        evt = get_event(world, event_id)
        if evt and evt.get("comments"):
            idx = action.get("comment_idx", len(evt["comments"]) - 1)
            react_comment(c, world, event_id, idx, reaction)


def _route_social_event_attend(c, world, action):
    """Character attends an event — goes off-grid for the event duration."""
    import time
    from systems.social_events import get_event, rsvp
    event_id = action.get("event_id") or action.get("args", {}).get("event_id")
    if not event_id:
        return
    evt = get_event(world, event_id)
    if not evt or evt["status"] != "published":
        return
    cost = evt.get("cost_per_person", 0.0)
    if cost > 0:
        for item in c.get("inventory", []):
            if item.get("object_type") == "wallet":
                cash = item.get("cash", 0.0)
                if cash < cost:
                    c.setdefault("notifications", []).append({
                        "type": "event_cant_afford",
                        "event_id": event_id,
                        "title": evt["title"],
                        "cost": cost,
                        "ts": time.time(),
                    })
                    return
                item["cash"] = round(cash - cost, 2)
                break
    rsvp(c, world, event_id, "yes")
    c["off_grid"]       = True
    c["off_grid_reason"] = f"event:{event_id}"
    c["off_grid_until"] = evt.get("end_ts") or (evt.get("start_ts", time.time()) + 3 * 3600)


def _route_social_event_plan(c, world, action):
    """Create a new social event draft."""
    from systems.social_events import create_event_draft
    args = action.get("args") or action
    create_event_draft(
        c, world,
        title           = args.get("title", "My Event"),
        category        = args.get("category", "party"),
        description     = args.get("description", ""),
        location        = args.get("location", ""),
        location_type   = args.get("location_type", "venue"),
        start_ts        = args.get("start_ts"),
        end_ts          = args.get("end_ts"),
        co_organizers   = args.get("co_organizers") or [],
        max_attendees   = args.get("max_attendees"),
        cost_per_person = float(args.get("cost_per_person", 0.0)),
        min_age         = args.get("min_age"),
        max_age         = args.get("max_age"),
        popularity      = int(args.get("popularity", 50)),
        tags            = args.get("tags") or [],
        visible_to      = args.get("visible_to") or [],
    )

def _route_organize_hobby_session(c, world, action):
    """
    Character goes to computer or phone to organise a hobby session.
    Surfaces hobby-compatible contacts so the LLM can decide who to invite.
    This is the 'browsing/outreach' step before plan_hobby_session.
    """
    from systems.hobbies import find_hobby_contacts, inject_organize_intention
    hobby_id = action.get("hobby_id") or action.get("args", {}).get("hobby_id")
    if not hobby_id:
        return
    contacts = find_hobby_contacts(c, world, hobby_id, max_results=8)
    chars    = world.get("characters", {})
    c.setdefault("hobby_contacts_found", {})[hobby_id] = [
        {"id": cid, "name": chars[cid]["name"]}
        for cid in contacts if cid in chars
    ]


def _route_plan_hobby_session(c, world, action):
    """
    Create a social event for a group hobby session.
    Guests who share the hobby are invited first; if location_type==home
    and the event is published, guests will be spawned as temporary NPCs.
    """
    from systems.hobbies import plan_hobby_session
    hobby_id = (
        action.get("hobby_id")
        or action.get("args", {}).get("hobby_id")
    )
    start_offset = int(
        action.get("start_offset_hours")
        or action.get("args", {}).get("start_offset_hours", 48)
    )
    if hobby_id:
        plan_hobby_session(c, world, hobby_id, start_offset_hours=start_offset)
