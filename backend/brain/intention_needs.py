"""
brain/intention_needs.py

What satisfies an intention: the prop interactions that would help with it, best first.

    SATISFIED_BY[intention type] = [interaction, ...]

The interactions are the real ones prop templates offer on their anchors (definitions.json -> prop_templates ->
anchors[].interaction): a fridge offers "open_fridge", a kitchen counter "prepare_food", a toilet "use_toilet". So
"hungry" leads to the fridge in your kitchen because eat_food says open_fridge helps -- not because the words happen
to match -- and the order ranks them: for dinner the stove comes before the microwave.

Used by systems/spotted.py to bring to mind the known things that would help with what a character has to see to.
An intention type that isn't listed brings nothing to mind; add it here when a new kind of intention should.
"expectation:<id>" intentions are looked up by <id>.
"""

SATISFIED_BY = {
    # --- body ---------------------------------------------------------------------------------------------------------
    "eat_food":              ["open_fridge", "grab_food", "use_microwave", "prepare_food", "cook", "grill_food", "eat"],
    "drink":                 ["drink", "use_tap", "open_fridge", "grab_drink", "make_coffee"],
    "seek_caffeine_or_rest": ["make_coffee", "lie_down", "lie", "sit_down_seat"],
    "use_toilet":            ["use_toilet"],
    "take_shower":           ["shower", "bathe"],
    "brush_teeth":           ["brush_teeth"],
    "wash_hands":            ["wash_hands", "use_tap"],
    "sleep":                 ["sleep"],
    "take_nap":              ["lie_down", "sleep", "lie"],
    "seek_warmer_clothes":   ["change_clothes", "grab_coat"],

    # --- household ----------------------------------------------------------------------------------------------------
    "cook_dinner":           ["cook", "prepare_food", "open_fridge", "use_microwave", "grill_food"],
    "make_dinner":           ["cook", "prepare_food", "open_fridge", "use_microwave", "grill_food"],
    "feed_child_kid":        ["open_fridge", "prepare_food", "use_microwave", "cook", "eat"],
    "family_dinner_together": ["eat", "cook", "prepare_food"],
    "do_laundry":            ["do_laundry", "add_laundry", "dry_laundry", "iron_clothes"],
    "wash_dishes":           ["wash_dishes", "load_dishwasher"],
    "take_out_trash":        ["take_out_trash", "dispose_trash"],
    "check_mail":            ["check_mail"],
    "water_plants":          ["garden", "use_tap"],
    "weed_plants":           ["garden"],
    "harvest_plants":        ["garden"],
    "file_taxes":            ["file_document", "use_computer", "computer_use"],

    # --- leisure and the rest -------------------------------------------------------------------------------------------
    "exercise":              ["run_treadmill", "cycle", "lift_weights", "row", "exercise", "do_yoga", "punch_bag",
                              "do_pull_ups"],
    "play":                  ["play_with_toys", "play_games", "jump_trampoline"],
    "play_with_friend":      ["play_with_toys", "play_games", "jump_trampoline"],
    "creative_outlet":       ["paint", "sketch", "play_piano", "play_keyboard", "play_drums", "practice_instrument",
                              "sing_karaoke"],
    "learn_something":       ["browse", "use_computer", "computer_use"],
    "relax":                 ["lie", "sit_down_seat", "watch_movie", "listen_to_music", "use_hot_tub", "sit_by_fire"],
    "relax_with_someone":    ["sit_down_seat", "watch_movie", "listen_to_music", "sit_by_fire"],
    "spend_time_alone":      ["lie", "listen_to_music", "browse", "sit_by_fire"],
    "seek_solitude":         ["lie", "listen_to_music", "browse"],
    "work":                  ["work", "computer_use", "use_computer"],
}


def satisfied_by(intention_type):
    """[interaction, ...] that would help with this intention, best first; [] if it isn't one a thing helps with."""
    t = str(intention_type or "")
    if t.startswith("expectation:"):
        t = t.split(":", 1)[1]
    if t in SATISFIED_BY:
        return SATISFIED_BY[t]
    for known, interactions in SATISFIED_BY.items():     # e.g. "eat_food_snack" -> eat_food
        if t.startswith(known + "_"):
            return interactions
    return []
