"""
systems/screen_activity.py -- what someone is doing on their phone or computer (the user, 2026-11-27: "when they use
computer or phone I want to know what they are doing on it").

After a phone / computer action is carried out (brain/agent_loop.py, right after route_action), c["screen"] says what
it is, in words, from the action itself and whatever the activity found:

    c["screen"] = {"device": "phone" | "computer", "app": "Messages", "what": 'texting Rebecca: "Running late"',
                   "activity": <activity type>, "since_tick": tick, "in_their_words": <their narration>}

and c["screen_log"] keeps the last SCREEN_LOG_KEPT. The inspector shows it while that activity is going on
(frontend/src/main.js); the last few are listed under it.
"""

SCREEN_LOG_KEPT = 12

# action type -> (device, app)
APPS = {
    "call": ("phone", "Phone"), "phone_call": ("phone", "Phone"), "phone_answer": ("phone", "Phone"),
    "text": ("phone", "Messages"), "phone_send_text": ("phone", "Messages"), "phone_read_text": ("phone", "Messages"),
    "phone_check": ("phone", "Home screen"), "browse_news": ("phone", "News"),
    "set_phone_alarm_clock": ("phone", "Clock"), "contact_business": ("phone", "Phone"),
    "book_appointment": ("phone", "Bookings"), "order_taxi_by_phone_call": ("phone", "Phone"),
    "order_taxi_by_phone_app": ("phone", "Taxi app"), "post_social_media": ("phone", "Social media"),
    "like_social_post": ("phone", "Social media"), "unlike_social_post": ("phone", "Social media"),
    "comment_on_social_post": ("phone", "Social media"), "check_device": ("phone", "Someone else's phone"),
    "computer_social_media": ("computer", "Social media"), "computer_videos": ("computer", "Videos"),
    "computer_game": ("computer", "Games"), "computer_wiki_research": ("computer", "Encyclopedia"),
    "computer_news": ("computer", "News"), "computer_window_shopping": ("computer", "Online shop"),
    "computer_dating": ("computer", "Dating site"), "computer_job_search": ("computer", "Job site"),
    "computer_apply_for_job": ("computer", "Job site"), "write_refine_resume": ("computer", "Word processor"),
    "computer_send_email": ("computer", "Email"), "computer_respond_email": ("computer", "Email"),
    "computer_check_email": ("computer", "Email"), "browse_second_hand_marketplace": ("computer", "Marketplace"),
    "sell_prop_item_second_hand": ("computer", "Marketplace"), "buy_prop_item_second_hand": ("computer", "Marketplace"),
    "estimate_avg_sell_value": ("computer", "Marketplace"), "browse_darknet_market": ("computer", "Darknet market"),
    "order_darknet_listing": ("computer", "Darknet market"), "computer_list_stocks": ("computer", "Stocks"),
    "computer_buy_stock": ("computer", "Stocks"), "computer_sell_stock": ("computer", "Stocks"),
    "computer_check_stock_value": ("computer", "Stocks"), "computer_order_item": ("computer", "Online shop"),
    "computer_order_service": ("computer", "Services"), "check_computer_history": ("computer", "Browser history"),
    "write_diary": ("computer", "Diary"),
}


def _who(world, action):
    chars = world.get("characters") or {}
    t = action.get("target_id") or action.get("target")
    if isinstance(t, str) and t in chars:
        return (chars[t].get("name") or t).split(" ")[0]
    return action.get("target_description") or (t if isinstance(t, str) and not t.startswith("char_") else None)


def _q(text, n=90):
    t = str(text or "").strip().replace("\n", " ")
    return f'"{t[:n]}{"…" if len(t) > n else ""}"' if t else ""


def _first_title(items, *keys):
    for it in items or []:
        if isinstance(it, str):
            return it
        if isinstance(it, dict):
            for k in keys:
                if it.get(k):
                    return str(it[k])
    return None


def _hobby(c):
    h = (c.get("hobbies") or [None])[0]
    return h.replace("_", " ") if h else None


def describe(c, world, action):
    """What they're doing on the device, in words."""
    t = action.get("type")
    act = c.get("activity") or {}
    who = _who(world, action)
    msg = action.get("message") or action.get("body") or action.get("detail")
    if t in ("phone_send_text", "text"):
        return f"texting {who or 'someone'}" + (f": {_q(msg)}" if msg else "")
    if t in ("phone_call", "call", "contact_business", "order_taxi_by_phone_call"):
        return f"on a call with {who or 'someone'}" + (" (ordering a taxi)" if "taxi" in t else "")
    if t == "phone_answer":
        return f"answering a call{(' from ' + who) if who else ''}"
    if t == "phone_read_text":
        return f"reading messages{(' from ' + who) if who else ''}"
    if t == "phone_check":
        return "checking their phone"
    if t in ("browse_news", "computer_news"):
        h = _first_title(act.get("headlines"), "title", "headline")
        return "reading the news" + (f": {_q(h, 80)}" if h else "")
    if t == "computer_wiki_research":
        kw = act.get("research_keyword") or action.get("keyword")
        return f"looking up {kw}" if kw else "reading up on something"
    if t in ("post_social_media",):
        return "posting" + (f": {_q(action.get('content') or msg)}" if (action.get("content") or msg) else "")
    if t in ("like_social_post", "unlike_social_post", "comment_on_social_post"):
        verb = {"like_social_post": "liking", "unlike_social_post": "unliking", "comment_on_social_post": "commenting on"}[t]
        return f"{verb} {who + chr(39) + 's' if who else 'a'} post" + (f": {_q(msg)}" if t == "comment_on_social_post" and msg else "")
    if t == "computer_social_media":
        return "scrolling social media" + (f" -- {who}'s page" if who else "")
    if t == "computer_videos":
        topic = action.get("detail") or action.get("target_description") or _hobby(c)
        return f"watching videos{(' about ' + topic) if topic else ''}"
    if t == "computer_game":
        g = action.get("detail") or action.get("target_description")
        return f"playing {g}" if g else "playing a game"
    if t == "computer_window_shopping":
        what = action.get("detail") or action.get("target_description")
        return f"browsing an online shop{(' for ' + what) if what else ''}"
    if t == "computer_dating":
        return "on a dating site"
    if t == "computer_job_search":
        first = _first_title(act.get("job_listings"), "title", "job_title")
        n = len(act.get("job_listings") or [])
        return f"looking at job ads{(' -- ' + str(n) + ' found, e.g. ' + first) if first else ''}"
    if t == "computer_apply_for_job":
        return f"applying for {action.get('detail') or action.get('target_description') or 'a job'}"
    if t == "write_refine_resume":
        return "working on their CV"
    if t in ("computer_send_email", "computer_respond_email"):
        subj = action.get("subject")
        return f"writing an email to {who or 'someone'}" + (f" -- {_q(subj, 60)}" if subj else (f": {_q(msg)}" if msg else ""))
    if t == "computer_check_email":
        n = act.get("unread_email_count")
        return f"checking email{(' (' + str(n) + ' unread)') if n is not None else ''}"
    if t in ("computer_buy_stock", "computer_sell_stock", "computer_check_stock_value", "computer_list_stocks"):
        sp = act.get("stock_price") or {}
        tick = sp.get("ticker") or action.get("ticker") or action.get("detail")
        verb = {"computer_buy_stock": "buying", "computer_sell_stock": "selling",
                "computer_check_stock_value": "checking", "computer_list_stocks": "browsing"}[t]
        return f"{verb} stocks{(' -- ' + str(tick)) if tick else ''}" + (f" at {sp['price']}" if sp.get("price") else "")
    if t in ("computer_order_item", "computer_order_service"):
        what = action.get("detail") or action.get("target_description") or (act.get("order_result") or {}).get("template_id")
        return f"ordering {str(what).replace('_', ' ') if what else 'something'} online"
    if t in ("browse_second_hand_marketplace", "browse_darknet_market"):
        first = _first_title(act.get("marketplace_listings") or act.get("darknet_listings"), "title", "name")
        place = "the darknet market" if "darknet" in t else "second-hand listings"
        return f"browsing {place}" + (f" -- e.g. {first}" if first else "")
    if t in ("sell_prop_item_second_hand", "buy_prop_item_second_hand", "order_darknet_listing"):
        return f"{'selling' if 'sell' in t else 'buying'} {action.get('detail') or action.get('target_description') or 'something'}"
    if t == "estimate_avg_sell_value":
        return "checking what something would sell for"
    if t == "check_device":
        return f"going through {who + chr(39) + 's' if who else 'someone else' + chr(39) + 's'} phone"
    if t == "check_computer_history":
        return "looking through the browser history"
    if t == "write_diary":
        return "writing in their diary"
    if t == "set_phone_alarm_clock":
        return f"setting an alarm{(' for ' + str(action.get('detail'))) if action.get('detail') else ''}"
    if t == "book_appointment":
        return f"booking {action.get('detail') or action.get('target_description') or 'an appointment'}"
    if t == "order_taxi_by_phone_app":
        return "ordering a taxi in the app"
    return APPS.get(t, ("", t.replace("_", " ")))[1]


def after_route(c, world, action):
    """Called once a phone / computer action has been carried out."""
    t = (action or {}).get("type")
    if t not in APPS:
        return None
    device, app = APPS[t]
    if device == "computer" and (c.get("activity") or {}).get("device") == "phone":
        device = "phone"                                  # the same apps on a phone
    entry = {"device": device, "app": app, "what": describe(c, world, action), "activity": (c.get("activity") or {}).get("type") or t,
             "since_tick": world.get("tick", 0)}
    reason = str(action.get("reason") or "").strip()
    if reason:
        entry["in_their_words"] = reason[:160]
    c["screen"] = entry
    log = c.setdefault("screen_log", [])
    log.append({k: entry[k] for k in ("device", "app", "what", "since_tick")})
    del log[:-SCREEN_LOG_KEPT]
    return entry


def current(c):
    """What's on their screen right now, or None (the activity has moved on)."""
    s = c.get("screen")
    act = (c.get("activity") or {}).get("type")
    if s and act and act == s.get("activity"):
        return s
    return None
