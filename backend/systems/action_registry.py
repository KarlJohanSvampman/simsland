"""
systems/action_registry.py

Single source of truth for legal action types — what handler routes them
(action_router.py::route_action), what kind of thing they target, and a
short doc string. Replaces systems/action_validator.py's separately-
maintained VALID_ACTIONS set, which had drifted from action_router.py's
actual dispatch chain: several action types were fully routed (a working
_route_*() handler, dispatched from route_action()) and even offered by
brain/context_builder.py::build_available_actions(), but silently rejected
by validate_type() because nobody had added the string to VALID_ACTIONS —
a live character could see the action offered, choose it, and have it
bounce with zero explanation. audit() below is the tool for catching this
class of bug again in the future.

target values (drives brain/action_resolver.py's Round 6 candidate-pool
selection):
  none              — no target needed (e.g. wait, hire_service, leave_note)
  character         — world["characters"] id
  prop              — world["props"] id
  prop_or_character — either (e.g. interact can target a prop; a few
                       actions accept whichever the model names)
  item              — an inventory/held/worn item id
  building          — world["buildings"] id
  wall              — a wall id (systems/walls.py)
  incident          — world["incidents"] id (call_911)
  proposal          — a proposals.py proposal id
  device            — a placed_items id (snoopable devices, computer/phone)
  any               — target shape not yet pinned down precisely; refined
                       as brain/action_resolver.py (Round 6) actually needs it
"""

ACTION_SPECS = {
    # ---- movement / core ----------------------------------------------
    "move":       {"group": "core", "target": "prop_or_character", "doc": "Walk toward a person or prop."},
    "jog_to":     {"group": "core", "target": "prop_or_character", "doc": "Jog toward a person or prop -- faster than walking, use when in a hurry (running late, urgent need)."},
    "sneak_to":   {"group": "core", "target": "prop_or_character", "doc": "Move toward a person or prop slowly and carefully, trying not to be noticed -- e.g. slipping out at night, avoiding someone without confronting them."},
    "speak":      {"group": "core", "target": "character", "doc": "Say something (use the `say` field)."},
    "interact":   {"group": "core", "target": "prop", "doc": "Use/interact with a prop."},
    "wait":       {"group": "core", "target": "none", "doc": "Do nothing this turn. Optionally set waiting_for: {kind: person|business|delivery, ref} if you're blocked on something specific rather than just idling -- arms a patience timer that nudges a follow-up once it runs out."},
    "eat":        {"group": "core", "target": "any", "doc": "Eat available food."},
    "sleep":      {"group": "core", "target": "none", "doc": "Go to sleep."},
    "work":       {"group": "core", "target": "none", "doc": "Work your job."},
    "socialize":  {"group": "core", "target": "character", "doc": "Casually socialize."},

    # ---- examine / search / carry / clean — routed, previously never
    # registered (confirmed via direct audit: route_action() dispatches
    # all four, but build_available_actions() doesn't offer them yet —
    # gating added in this round, see context_builder.py) -------------
    "examine":    {"group": "core", "target": "prop_or_character", "doc": "Take a closer look at something."},
    "search":     {"group": "core", "target": "prop", "doc": "Search a prop/container."},
    "carry":      {"group": "core", "target": "prop", "doc": "Pick up and carry a prop."},
    "clean":      {"group": "core", "target": "prop", "doc": "Clean a prop."},

    # ---- describe (Round 8) — costs no in-world time, only yields more
    # description. target_description omitted -> describes the room by
    # default (see brain/describe_registry.py). "detail" carries the
    # aspect (e.g. "personality", "relationship", "contents", "inventory")
    # — deliberately its own "aspect" field, not "reason", since the
    # adapter always fills "reason" with the narration snippet and the
    # two must not collide.
    "describe":   {"group": "core", "target": "any", "detail": "aspect",
                   "doc": "Look closer / ask for more detail (person, prop, room, yourself, your activity) — no target for the room."},

    # ---- recall (Round 9) — costs no in-world time, pulls up a memory.
    # target deliberately "none": unlike every other target-bearing action,
    # an unresolvable target_description here must NOT fail the action —
    # it should fall back to a raw-text memory search instead of staging a
    # "nothing matches" retry. _route_recall does its own best-effort
    # character-name resolution internally (see action_router.py) rather
    # than going through action_resolver.resolve_and_apply()'s normal
    # resolve-or-fail path.
    "recall":     {"group": "core", "target": "none",
                   "doc": "Pull up a memory — no target for your last thought/intention, or describe what you're trying to remember."},

    # ---- phone / device -------------------------------------------------
    "call":              {"group": "phone", "target": "character", "doc": "Alias for phone_check."},
    "text":              {"group": "phone", "target": "character", "doc": "Alias for phone_check."},
    "phone_call":        {"group": "phone", "target": "character", "doc": "Call a known contact."},
    "phone_answer":      {"group": "phone", "target": "none", "doc": "Answer an incoming call."},
    "phone_send_text":   {"group": "phone", "target": "character", "detail": "message", "doc": "Text a known contact."},
    "phone_check":       {"group": "phone", "target": "none", "doc": "Check your phone."},
    "phone_read_text":   {"group": "phone", "target": "none", "doc": "Read a text you received."},
    "retrieve_phone":    {"group": "phone", "target": "none", "doc": "Go get your phone from where you left it."},
    "charge":            {"group": "phone", "target": "prop", "doc": "Charge a device at an outlet."},
    "browse_news":       {"group": "phone", "target": "none", "doc": "Check the news on your phone -- picks a fresh recent headline every few minutes for as long as you keep at it."},
    "contact_business":  {"group": "phone", "target": "any", "detail": "reason", "doc": "Call or message a business's customer support -- deliveries, complaints, general questions. Target a company_templates key. If they're unreachable (closed, or you're an online-only business's caller and it happened to skip straight to email), your message lands in their inbox and they call/email you back later, during their business hours -- you won't get an answer right away."},
    "book_appointment":  {"group": "phone", "target": "any", "detail": "reason", "doc": "Call a service business (doctor, lawyer, therapist, ...) to book an appointment. Target a company_templates key, and state your reason -- ideally one of that business's reason_options. Only resolves to a confirmed appointment if you call during their phone hours; otherwise it's left as a request for them to get back to you."},

    # ---- computer / online actions --------------------------------------
    "computer_social_media":     {"group": "computer", "target": "none", "doc": "Browse social media."},
    "computer_videos":           {"group": "computer", "target": "none", "doc": "Watch videos online."},
    "computer_game":             {"group": "computer", "target": "none", "doc": "Play an online game."},
    "computer_wiki_research":    {"group": "computer", "target": "none", "doc": "Look something up."},
    "computer_news":             {"group": "computer", "target": "none", "doc": "Catch up on the news."},
    "computer_window_shopping":  {"group": "computer", "target": "none", "doc": "Browse shops online."},
    "computer_dating":           {"group": "computer", "target": "none", "doc": "Use a dating app/site."},
    "computer_job_search":       {"group": "computer", "target": "none", "doc": "Search job listings."},
    "computer_apply_for_job":    {"group": "computer", "target": "any", "doc": "Apply for a job listing."},
    "computer_send_email":       {"group": "computer", "target": "character", "detail": "message", "doc": "Email a known contact."},
    "computer_respond_email":    {"group": "computer", "target": "character", "detail": "message", "doc": "Reply to an email."},
    "computer_check_email":      {"group": "computer", "target": "none", "doc": "Check your email."},
    # Stock trading — routed (action_router.py lines ~2542-2599) but never
    # offered/validated before this round.
    "computer_list_stocks":         {"group": "computer", "target": "none", "doc": "See available stocks and prices."},
    "computer_buy_stock":           {"group": "computer", "target": "any", "doc": "Buy shares of a stock."},
    "computer_sell_stock":          {"group": "computer", "target": "any", "doc": "Sell shares of a stock you own."},
    "computer_check_stock_value":   {"group": "computer", "target": "any", "doc": "Check the value of your stock holdings."},
    # Ordering — same gap.
    "computer_order_item":          {"group": "computer", "target": "any", "doc": "Order an item for delivery."},
    "computer_order_service":       {"group": "computer", "target": "any", "doc": "Order a service."},

    # ---- social events / hobby sessions (systems/social_events.py-style
    # routes) — routed but never offered/validated before this round -----
    "social_browse_events":   {"group": "social_event", "target": "none", "doc": "Browse upcoming social events."},
    "social_event_rsvp":      {"group": "social_event", "target": "any", "doc": "RSVP to an event."},
    "social_event_comment":   {"group": "social_event", "target": "any", "doc": "Comment on an event."},
    "social_event_attend":    {"group": "social_event", "target": "any", "doc": "Attend an event you RSVP'd to."},
    "social_event_plan":      {"group": "social_event", "target": "none", "doc": "Plan/host a new event."},
    "organize_hobby_session": {"group": "social_event", "target": "any", "doc": "Organize a group hobby session."},
    "plan_hobby_session":     {"group": "social_event", "target": "any", "doc": "Plan a future hobby session."},

    # ---- item / stack management -----------------------------------------
    "add_to_stack":     {"group": "item", "target": "item", "doc": "Add a held item to your stack."},
    "put_down_stack":   {"group": "item", "target": "none", "doc": "Set down your whole stack."},
    "search_stack":     {"group": "item", "target": "none", "doc": "Look through what's in your stack."},
    "take_from_stack":  {"group": "item", "target": "item", "doc": "Take one item out of your stack."},
    "pocket_item":      {"group": "item", "target": "item", "doc": "Put your held item away."},
    "wear":             {"group": "item", "target": "item", "doc": "Put on a wearable item."},
    "undress":          {"group": "item", "target": "item", "doc": "Take off a worn item."},
    "wield_item":       {"group": "item", "target": "item", "doc": "Ready a weapon-capable item in hand."},
    "trash":            {"group": "item", "target": "prop", "doc": "Throw a prop away."},
    "destroy":          {"group": "item", "target": "prop", "doc": "Destroy a prop (a real offense — reported)."},
    "read_newspaper":   {"group": "item", "target": "none", "doc": "Read a physical newspaper you're carrying -- picks a fresh recent headline every few minutes for as long as you keep at it."},

    # ---- movable props / assembly / walls ---------------------------------
    "drag_prop":       {"group": "prop", "target": "prop", "doc": "Drag a movable prop."},
    "push_prop":       {"group": "prop", "target": "prop", "doc": "Help push a prop someone else is dragging."},
    "let_go_prop":     {"group": "prop", "target": "none", "doc": "Let go of the prop you're moving."},
    "assemble_prop":   {"group": "prop", "target": "item", "doc": "Assemble a prop from a box in your inventory."},
    "assemble_tile":   {"group": "prop", "target": "item", "doc": "Place flooring/wall tiles from a box."},
    "build_wall":      {"group": "prop", "target": "any", "doc": "Build a wall."},
    "remove_wall":     {"group": "prop", "target": "wall", "doc": "Remove a wall."},
    "paint_wall":      {"group": "prop", "target": "wall", "detail": "item", "doc": "Paint a wall using a paint bucket you're carrying."},
    "hire_service":    {"group": "prop", "target": "none", "doc": "Hire an outside service (repair, cleaning, ...)."},
    "order_taxi_by_phone_call": {"group": "social", "target": "none", "doc": "Call a taxi company to send a car to your current location (optional destination)."},
    "order_taxi_by_phone_app":  {"group": "social", "target": "none", "doc": "Order a taxi through a rideshare app on your smartphone."},
    "order_taxi":      {"group": "household", "target": "none", "doc": "Order a taxi, walk to the pickup spot, and wait for it to arrive -- uses order_taxi_by_phone_call/order_taxi_by_phone_app internally."},

    # ---- posture ------------------------------------------------------
    "sit_down":            {"group": "posture", "target": "prop", "doc": "Sit down on a seatable prop."},
    "stand_up":            {"group": "posture", "target": "none", "doc": "Get back on your feet."},
    "lie_down":            {"group": "posture", "target": "prop", "doc": "Lie down on a sleepable prop."},
    "lean_against_wall":   {"group": "posture", "target": "wall", "doc": "Lean against a nearby wall."},
    "push_off_wall":       {"group": "posture", "target": "none", "doc": "Stop leaning against the wall."},

    # ---- household waits ------------------------------------------------
    "start_microwave":         {"group": "household", "target": "prop", "doc": "Start the microwave."},
    "take_out_of_microwave":   {"group": "household", "target": "none", "doc": "Take your food out of the microwave."},
    "do_laundry_fill":         {"group": "household", "target": "prop", "doc": "Load the washer."},

    # ---- proposals / negotiation ------------------------------------------
    "propose_chore":          {"group": "proposal", "target": "character", "doc": "Propose a shared chore."},
    "respond_chore":          {"group": "proposal", "target": "proposal", "doc": "Respond to a pending chore proposal."},
    "advance_chore_round":    {"group": "proposal", "target": "proposal", "doc": "Push a stalled chore negotiation forward."},
    "propose_recurring":      {"group": "proposal", "target": "character", "doc": "Offer to make a just-finished chore a standing arrangement."},
    "propose_social":         {"group": "proposal", "target": "character", "doc": "Propose a social plan."},
    "respond_social":         {"group": "proposal", "target": "proposal", "doc": "Respond to a pending social proposal."},
    "advance_social_round":   {"group": "proposal", "target": "proposal", "doc": "Push a stalled social negotiation forward."},
    "propose_rule":           {"group": "proposal", "target": "none", "doc": "Set a standing household rule."},
    "add_rule_exception":     {"group": "proposal", "target": "any", "doc": "Grant a one-off exception to a rule."},
    "propose_request":        {"group": "proposal", "target": "character", "doc": "Ask someone for something specific."},
    "respond_request":        {"group": "proposal", "target": "proposal", "doc": "Respond to a pending request."},
    "advance_request_round":  {"group": "proposal", "target": "proposal", "doc": "Push a stalled request negotiation forward."},
    "propose_item_loan":      {"group": "proposal", "target": "character", "detail": "item_id", "doc": "Ask to borrow one of someone's items for a while (duration_days, default 7). Ownership doesn't change -- it's returned automatically when due."},
    "respond_item_loan":      {"group": "proposal", "target": "proposal", "doc": "Respond to a pending item-loan request."},
    "advance_item_loan_round": {"group": "proposal", "target": "proposal", "doc": "Push a stalled item-loan negotiation forward."},
    "propose_item_sale":      {"group": "proposal", "target": "character", "detail": "item_id", "doc": "Ask if someone will sell an item of theirs -- offer_price (omit to invite their asking price) and/or offer_item_id to propose a trade instead of/alongside cash."},
    "respond_item_sale":      {"group": "proposal", "target": "proposal", "doc": "Respond to a pending item-sale/trade offer."},
    "advance_item_sale_round": {"group": "proposal", "target": "proposal", "doc": "Push a stalled item-sale/trade negotiation forward."},

    # ---- social media -------------------------------------------------------
    "post_social_media":       {"group": "social", "target": "none", "doc": "Post to social media (text; media_description optional -- a photo/video isn't actually captured, just described)."},
    "like_social_post":        {"group": "social", "target": "any", "doc": "Like a social media post (post_id)."},
    "unlike_social_post":      {"group": "social", "target": "any", "doc": "Remove your like from a social media post (post_id)."},
    "comment_on_social_post":  {"group": "social", "target": "any", "doc": "Comment on a social media post (post_id, text)."},

    # ---- lies / social contract -------------------------------------------
    "give_excuse":         {"group": "social", "target": "character", "doc": "Give someone an excuse."},
    "leave_note":          {"group": "social", "target": "none", "doc": "Leave a note explaining where you are."},
    "announce_departure":  {"group": "social", "target": "any", "doc": "Tell someone you're heading out."},
    "check_device":        {"group": "social", "target": "device", "doc": "Check a suspicious unattended phone."},
    "check_computer_history": {"group": "social", "target": "none", "doc": "Check the household computer's recent activity history."},
    "form_theory":         {"group": "social", "target": "any", "doc": "Voice a theory about what's going on."},
    "make_argument":       {"group": "social", "target": "character", "detail": "topic", "doc": "Argue your side of a topic you disagree with someone about -- counters their last point, or raises a new one for your own stance. Only offered when there's a real disagreement live (see the values/opinions section of your context). Whoever's listening forms their own reaction based on their own values, not yours."},

    # ---- touch --------------------------------------------------------
    "hug":            {"group": "touch", "target": "character", "doc": "Propose a hug."},
    "kiss":           {"group": "touch", "target": "character", "doc": "Propose a kiss."},
    "kiss_peck":      {"group": "touch", "target": "character", "doc": "Propose a quick kiss."},
    "kiss_deep":      {"group": "touch", "target": "character", "doc": "Propose a deep kiss."},
    "cuddle":         {"group": "touch", "target": "character", "doc": "Propose cuddling."},
    "hold_hands":     {"group": "touch", "target": "character", "doc": "Propose holding hands."},
    "handshake":      {"group": "touch", "target": "character", "doc": "Offer a handshake."},
    "high_five":      {"group": "touch", "target": "character", "doc": "Offer a high five."},
    "respond_touch":  {"group": "touch", "target": "character", "doc": "Respond to a pending touch proposal."},

    # ---- hostile / defensive -------------------------------------------
    "confront":         {"group": "hostile", "target": "character", "doc": "Confront someone over a grievance."},
    "call_911":         {"group": "hostile", "target": "incident", "doc": "Call emergency services about an incident."},
    "call_parent":      {"group": "hostile", "target": "character", "doc": "Call a minor offender's parent instead of 911."},

    # ---- medical (systems/health.py's per-bodypart damage rework) ------
    "administer_first_aid": {"group": "medical", "target": "character", "doc": "Apply first aid to a damaged body part -- your own or someone nearby's. Requires a first aid kit or bandages."},
    "take_painkiller":      {"group": "medical", "target": "none", "doc": "Take pain medication for global pain relief."},
    "grab_offensive":   {"group": "hostile", "target": "character", "doc": "Grab at someone aggressively."},
    "hold":             {"group": "hostile", "target": "character", "doc": "Hold someone down."},
    "punch":            {"group": "hostile", "target": "character", "doc": "Punch someone."},
    "kick":             {"group": "hostile", "target": "character", "doc": "Kick someone."},
    "shove":            {"group": "hostile", "target": "character", "doc": "Shove someone."},
    "threaten":         {"group": "hostile", "target": "character", "doc": "Threaten someone."},
    "stab":             {"group": "hostile", "target": "character", "doc": "Stab someone (requires a sharp weapon in hand)."},
    "knock":            {"group": "hostile", "target": "character", "doc": "Strike someone (requires a blunt weapon in hand)."},
    "dodge":            {"group": "defensive", "target": "none", "doc": "Dodge an incoming attack or struggle free."},
    "block":            {"group": "defensive", "target": "none", "doc": "Block an incoming attack."},
    "turn_and_run":     {"group": "defensive", "target": "none", "doc": "Flee the scene."},
    "wrestle":          {"group": "hostile", "target": "character", "doc": "Try to grapple and hold someone."},
    "release_hold":     {"group": "defensive", "target": "none", "doc": "Let go of whoever you're holding."},

    # ---- baby care (systems/baby.py) — routed but never registered before
    # this round (confirmed via direct audit of action_router.py's dispatch
    # chain: dispatched at lines ~996-1002, absent from both the old
    # VALID_ACTIONS and build_available_actions()) ------------------------
    "breastfeed":            {"group": "child", "target": "character", "doc": "Nurse a baby."},
    "bottle_feed":           {"group": "child", "target": "character", "doc": "Bottle-feed a baby."},
    "hold_baby":             {"group": "child", "target": "character", "doc": "Hold and comfort a baby."},
    "put_baby_in_carriage":  {"group": "child", "target": "character", "detail": "prop_id", "doc": "Put a baby in a pushable carriage."},

    # ---- child care / discipline ------------------------------------------
    "feed_child":          {"group": "child", "target": "character", "doc": "Feed a child who can't feed themselves."},
    "remind_child":        {"group": "child", "target": "character", "doc": "Remind a child to handle a need."},
    "apply_discipline":    {"group": "child", "target": "character", "doc": "Discipline a child."},
    "apply_reward":        {"group": "child", "target": "character", "doc": "Reward a child."},
    "negotiate_contract":  {"group": "child", "target": "character", "doc": "Negotiate a behavior contract with a child."},

    # ---- plants / gardening -----------------------------------------------
    "plant_seed":   {"group": "plant", "target": "prop", "doc": "Plant a seed in an empty pot."},
    "water":        {"group": "plant", "target": "prop", "doc": "Water a plant."},
    "pull_weed":    {"group": "plant", "target": "prop", "doc": "Weed a plant."},
    "harvest":      {"group": "plant", "target": "prop", "doc": "Harvest a mature plant's fruit."},
    "collect":      {"group": "plant", "target": "prop", "doc": "Collect contents from any reachable container."},

    # ---- exercise -----------------------------------------------------
    "jog":            {"group": "exercise", "target": "none", "doc": "Go for a jog."},
    "sit_ups":        {"group": "exercise", "target": "none", "doc": "Do sit-ups."},
    "chin_ups":       {"group": "exercise", "target": "prop", "doc": "Do chin-ups on a bar."},
    "lift_weights":   {"group": "exercise", "target": "prop", "doc": "Lift weights."},
}


def audit(available_action_types=None, router_dispatched_types=None):
    """Cross-reference ACTION_SPECS against build_available_actions()'s
    dynamic output and/or action_router.py's dispatch chain. Returns a dict
    of drift categories, each a list of action-type strings — empty lists
    mean no drift found. Callers (e.g. GET /debug/architecture) pass in
    whatever they have; either argument can be omitted.
    """
    drift = {
        "offered_but_unregistered": [],
        "dispatched_but_unregistered": [],
    }
    if available_action_types is not None:
        drift["offered_but_unregistered"] = sorted(
            set(available_action_types) - set(ACTION_SPECS)
        )
    if router_dispatched_types is not None:
        drift["dispatched_but_unregistered"] = sorted(
            set(router_dispatched_types) - set(ACTION_SPECS)
        )
    return drift
