"""
Physical item templates.

Each template defines the static properties of an item type.
At runtime, make_item(template_id) produces an instance dict with a unique id.

Template fields:
  name         str   — display name
  category     str   — grouping: hygiene / food / dishware / drink / linen / clothing / misc
  stackable    bool  — identical clean instances can share a quantity counter
  max_stack    int   — max quantity per stack (default 99)
  dirty        bool  — starts clean if False, tracks cleanliness at runtime
  consumable   bool  — disappears when used (toilet paper roll, food, drink)
  uses         int   — how many uses before consumed (None = infinite)

Clothing-only fields:
  slot         str   — which body slot it occupies (see CLOTHING_SLOTS in clothing.py)
  bone         str   — skeleton attachment point for Three.js SkinnedMesh
  model        str   — path to .glb; presence marks item as renderable on body
  color        str   — hex or CSS color (optional, for tinting)
  style        float — 0-1 style rating
"""

ITEM_TEMPLATES = {

    # =========================================================
    # HYGIENE
    # =========================================================

    "toilet_paper_roll": {
        "name":       "Toilet Paper Roll",
        "category":   "hygiene",
        "stackable":  True,
        "max_stack":  24,
        "consumable": True,
        "uses":       1,
    },

    "bath_towel": {
        "name":       "Bath Towel",
        "category":   "hygiene",
        "stackable":  True,
        "max_stack":  4,
        "dirty":      False,
        "consumable": False,
    },

    "hand_towel": {
        "name":       "Hand Towel",
        "category":   "hygiene",
        "stackable":  True,
        "max_stack":  6,
        "dirty":      False,
        "consumable": False,
    },

    # =========================================================
    # LINEN
    # =========================================================

    "bed_sheet": {
        "name":       "Bed Sheet",
        "category":   "linen",
        "stackable":  True,
        "max_stack":  4,
        "dirty":      False,
        "consumable": False,
    },

    "pillow": {
        "name":       "Pillow",
        "category":   "linen",
        "stackable":  True,
        "max_stack":  4,
        "dirty":      False,
        "consumable": False,
    },

    "duvet": {
        "name":       "Duvet",
        "category":   "linen",
        "stackable":  False,
        "dirty":      False,
        "consumable": False,
    },

    # =========================================================
    # DISHWARE
    # =========================================================

    "plate_ceramic": {
        "name":       "Plate",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    "bowl_ceramic": {
        "name":       "Bowl",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  8,
        "dirty":      False,
        "consumable": False,
    },

    "mug_ceramic": {
        "name":       "Mug",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  6,
        "dirty":      False,
        "consumable": False,
    },

    "glass_water": {
        "name":       "Water Glass",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  8,
        "dirty":      False,
        "consumable": False,
    },

    "glass_wine": {
        "name":       "Wine Glass",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  6,
        "dirty":      False,
        "consumable": False,
    },

    "glass_rocks": {
        "name":       "Rocks Glass",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  6,
        "dirty":      False,
        "consumable": False,
    },

    "fork": {
        "name":       "Fork",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    "knife_table": {
        "name":       "Table Knife",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    "spoon": {
        "name":       "Spoon",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    "teaspoon": {
        "name":       "Teaspoon",
        "category":   "dishware",
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    # =========================================================
    # FOOD (served / prepared — physical items, not bulk resources)
    # =========================================================

    "plate_of_pasta": {
        "name":       "Plate of Pasta",
        "category":   "food",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "nutrition":  0.75,
        "hunger_restore": 60,
    },

    "plate_of_rice": {
        "name":       "Plate of Rice",
        "category":   "food",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "nutrition":  0.6,
        "hunger_restore": 50,
    },

    "bowl_of_cereal": {
        "name":       "Bowl of Cereal",
        "category":   "food",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "nutrition":  0.5,
        "hunger_restore": 35,
    },

    "sandwich": {
        "name":       "Sandwich",
        "category":   "food",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "nutrition":  0.55,
        "hunger_restore": 40,
    },

    "frozen_dinner_plated": {
        "name":       "Frozen Dinner (plated)",
        "category":   "food",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "nutrition":  0.35,
        "hunger_restore": 45,
    },

    "slice_of_toast": {
        "name":       "Toast",
        "category":   "food",
        "stackable":  True,
        "max_stack":  4,
        "consumable": True,
        "uses":       1,
        "nutrition":  0.3,
        "hunger_restore": 20,
    },

    "apple": {
        "name":       "Apple",
        "category":   "food",
        "stackable":  True,
        "max_stack":  6,
        "consumable": True,
        "uses":       1,
        "nutrition":  0.65,
        "hunger_restore": 18,
    },

    "banana": {
        "name":       "Banana",
        "category":   "food",
        "stackable":  True,
        "max_stack":  6,
        "consumable": True,
        "uses":       1,
        "nutrition":  0.6,
        "hunger_restore": 22,
    },

    "bag_of_chips_open": {
        "name":       "Bag of Chips",
        "category":   "food",
        "stackable":  False,
        "consumable": True,
        "uses":       3,
        "nutrition":  0.2,
        "hunger_restore": 12,
    },

    # =========================================================
    # DRINKS (beverages held / consumed as items)
    # =========================================================

    "cup_of_coffee": {
        "name":       "Cup of Coffee",
        "category":   "drink",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "energy_restore":  20,
        "hydration_restore": 10,
        "caffeine":   True,
    },

    "cup_of_tea": {
        "name":       "Cup of Tea",
        "category":   "drink",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "energy_restore":  10,
        "hydration_restore": 15,
        "caffeine":   True,
    },

    "glass_of_water": {
        "name":       "Glass of Water",
        "category":   "drink",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "hydration_restore": 35,
    },

    "can_of_soda": {
        "name":       "Can of Soda",
        "category":   "drink",
        "stackable":  True,
        "max_stack":  6,
        "consumable": True,
        "uses":       1,
        "hydration_restore": 20,
        "energy_restore": 8,
        "caffeine":   True,
    },

    "can_of_energy_drink": {
        "name":       "Energy Drink",
        "category":   "drink",
        "stackable":  True,
        "max_stack":  6,
        "consumable": True,
        "uses":       1,
        "energy_restore":  35,
        "hydration_restore": 5,
        "caffeine":   True,
        "caffeine_strength": "high",
    },

    "bottle_of_beer": {
        "name":       "Beer",
        "category":   "drink",
        "stackable":  True,
        "max_stack":  12,
        "consumable": True,
        "uses":       1,
        "hydration_restore": 5,
        "alcohol":    True,
        "alcohol_units": 1.0,
    },

    "glass_of_red_wine": {
        "name":       "Glass of Red Wine",
        "category":   "drink",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "alcohol":    True,
        "alcohol_units": 1.5,
    },

    "glass_of_white_wine": {
        "name":       "Glass of White Wine",
        "category":   "drink",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "alcohol":    True,
        "alcohol_units": 1.5,
    },

    "glass_of_spirits": {
        "name":       "Glass of Spirits",
        "category":   "drink",
        "stackable":  False,
        "dirty":      False,
        "consumable": True,
        "uses":       1,
        "alcohol":    True,
        "alcohol_units": 2.5,
    },

    "shot_of_spirits": {
        "name":       "Shot",
        "category":   "drink",
        "stackable":  False,
        "consumable": True,
        "uses":       1,
        "alcohol":    True,
        "alcohol_units": 1.0,
    },

    # =========================================================
    # CLOTHING
    # Each piece has a slot, a bone attachment, and can be
    # rendered on the character when worn (if model is set).
    # All clothing starts clean (dirty: False) and stackable.
    # =========================================================

    # --- HEAD ---
    "baseball_cap": {
        "name":       "Baseball Cap",
        "category":   "clothing",
        "slot":       "head",
        "bone":       "Head",
        "model":      "/resources/clothing/baseball_cap.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  4,
        "style":      0.45,
    },

    "beanie": {
        "name":       "Beanie",
        "category":   "clothing",
        "slot":       "head",
        "bone":       "Head",
        "model":      "/resources/clothing/beanie.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  4,
        "style":      0.5,
    },

    # --- HAIR (wigs / styled overlays) ---
    "hair_short_brown": {
        "name":       "Short Brown Hair",
        "category":   "clothing",
        "slot":       "hair",
        "bone":       "Head",
        "model":      "/resources/clothing/hair_short_brown.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.6,
    },

    "hair_long_black": {
        "name":       "Long Black Hair",
        "category":   "clothing",
        "slot":       "hair",
        "bone":       "Head",
        "model":      "/resources/clothing/hair_long_black.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.7,
    },

    # --- NECK ---
    "scarf_knit": {
        "name":       "Knit Scarf",
        "category":   "clothing",
        "slot":       "neck",
        "bone":       "Neck",
        "model":      "/resources/clothing/scarf_knit.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  2,
        "style":      0.55,
    },

    # --- OUTERWEAR ---
    "jacket_hoodie": {
        "name":       "Hoodie",
        "category":   "clothing",
        "slot":       "outerwear",
        "bone":       "Spine2",
        "model":      "/resources/clothing/hoodie.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  3,
        "style":      0.55,
        "warmth":     0.6,
    },

    "jacket_denim": {
        "name":       "Denim Jacket",
        "category":   "clothing",
        "slot":       "outerwear",
        "bone":       "Spine2",
        "model":      "/resources/clothing/jacket_denim.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  2,
        "style":      0.75,
        "warmth":     0.5,
    },

    "jacket_winter": {
        "name":       "Winter Coat",
        "category":   "clothing",
        "slot":       "outerwear",
        "bone":       "Spine2",
        "model":      "/resources/clothing/jacket_winter.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.6,
        "warmth":     0.95,
    },

    # --- TORSO ---
    "tshirt_white": {
        "name":       "White T-Shirt",
        "category":   "clothing",
        "slot":       "torso",
        "bone":       "Spine1",
        "model":      "/resources/clothing/tshirt_white.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  6,
        "style":      0.4,
    },

    "tshirt_black": {
        "name":       "Black T-Shirt",
        "category":   "clothing",
        "slot":       "torso",
        "bone":       "Spine1",
        "model":      "/resources/clothing/tshirt_black.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  6,
        "style":      0.5,
    },

    "shirt_flannel": {
        "name":       "Flannel Shirt",
        "category":   "clothing",
        "slot":       "torso",
        "bone":       "Spine1",
        "model":      "/resources/clothing/shirt_flannel.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  4,
        "style":      0.55,
    },

    "shirt_dress": {
        "name":       "Dress Shirt",
        "category":   "clothing",
        "slot":       "torso",
        "bone":       "Spine1",
        "model":      "/resources/clothing/shirt_dress.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  4,
        "style":      0.85,
    },

    "top_crop": {
        "name":       "Crop Top",
        "category":   "clothing",
        "slot":       "torso",
        "bone":       "Spine1",
        "model":      "/resources/clothing/top_crop.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  4,
        "style":      0.7,
    },

    # --- UNDERSHIRT ---
    "tank_top": {
        "name":       "Tank Top",
        "category":   "clothing",
        "slot":       "undershirt",
        "bone":       "Spine1",
        "model":      "/resources/clothing/tank_top.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  6,
        "style":      0.35,
    },

    # --- LEGS ---
    "jeans_blue": {
        "name":       "Blue Jeans",
        "category":   "clothing",
        "slot":       "legs",
        "bone":       "Hips",
        "model":      "/resources/clothing/jeans_blue.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  3,
        "style":      0.65,
    },

    "jeans_black": {
        "name":       "Black Jeans",
        "category":   "clothing",
        "slot":       "legs",
        "bone":       "Hips",
        "model":      "/resources/clothing/jeans_black.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  3,
        "style":      0.7,
    },

    "sweatpants": {
        "name":       "Sweatpants",
        "category":   "clothing",
        "slot":       "legs",
        "bone":       "Hips",
        "model":      "/resources/clothing/sweatpants.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  3,
        "style":      0.3,
    },

    "shorts_casual": {
        "name":       "Casual Shorts",
        "category":   "clothing",
        "slot":       "legs",
        "bone":       "Hips",
        "model":      "/resources/clothing/shorts_casual.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  4,
        "style":      0.4,
    },

    "dress_casual": {
        "name":       "Casual Dress",
        "category":   "clothing",
        "slot":       "legs",
        "bone":       "Hips",
        "model":      "/resources/clothing/dress_casual.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.8,
    },

    "suit_trousers": {
        "name":       "Suit Trousers",
        "category":   "clothing",
        "slot":       "legs",
        "bone":       "Hips",
        "model":      "/resources/clothing/suit_trousers.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  2,
        "style":      0.9,
    },

    "pyjama_bottoms": {
        "name":       "Pyjama Bottoms",
        "category":   "clothing",
        "slot":       "legs",
        "bone":       "Hips",
        "model":      "/resources/clothing/pyjama_bottoms.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  3,
        "style":      0.2,
    },

    # --- UNDERWEAR ---
    "underwear_basic": {
        "name":       "Underwear",
        "category":   "clothing",
        "slot":       "underwear",
        "bone":       "Hips",
        "model":      "/resources/clothing/underwear_basic.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  7,
        "style":      0.3,
    },

    "boxer_shorts": {
        "name":       "Boxer Shorts",
        "category":   "clothing",
        "slot":       "underwear",
        "bone":       "Hips",
        "model":      "/resources/clothing/boxer_shorts.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  7,
        "style":      0.3,
    },

    # --- SOCKS ---
    "socks_white": {
        "name":       "White Socks",
        "category":   "clothing",
        "slot":       "socks",
        "bone":       "LeftFoot",
        "model":      "/resources/clothing/socks_white.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  7,
        "style":      0.25,
        "bilateral":  True,  # rendered on both feet
    },

    "socks_ankle": {
        "name":       "Ankle Socks",
        "category":   "clothing",
        "slot":       "socks",
        "bone":       "LeftFoot",
        "model":      "/resources/clothing/socks_ankle.glb",
        "dirty":      False,
        "stackable":  True,
        "max_stack":  7,
        "style":      0.3,
        "bilateral":  True,
    },

    # --- SHOES / FEET ---
    "sneakers_white": {
        "name":       "White Sneakers",
        "category":   "clothing",
        "slot":       "feet",
        "bone":       "LeftFoot",
        "model":      "/resources/clothing/sneakers_white.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.7,
        "bilateral":  True,
    },

    "shoes_casual": {
        "name":       "Casual Shoes",
        "category":   "clothing",
        "slot":       "feet",
        "bone":       "LeftFoot",
        "model":      "/resources/clothing/shoes_casual.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.6,
        "bilateral":  True,
    },

    "shoes_dress": {
        "name":       "Dress Shoes",
        "category":   "clothing",
        "slot":       "feet",
        "bone":       "LeftFoot",
        "model":      "/resources/clothing/shoes_dress.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.9,
        "bilateral":  True,
    },

    "slippers": {
        "name":       "Slippers",
        "category":   "clothing",
        "slot":       "feet",
        "bone":       "LeftFoot",
        "model":      "/resources/clothing/slippers.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.15,
        "bilateral":  True,
    },

    # --- HANDS / WRISTS ---
    "gloves_winter": {
        "name":       "Winter Gloves",
        "category":   "clothing",
        "slot":       "hands",
        "bone":       "LeftHand",
        "model":      "/resources/clothing/gloves_winter.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.5,
        "bilateral":  True,
        "warmth":     0.7,
    },

    "watch_casual": {
        "name":       "Casual Watch",
        "category":   "clothing",
        "slot":       "wrist_l",
        "bone":       "LeftForeArm",
        "model":      "/resources/clothing/watch_casual.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.7,
    },

    # --- ACCESSORY ---
    "backpack": {
        "name":       "Backpack",
        "category":   "clothing",
        "slot":       "accessory",
        "bone":       "Spine2",
        "model":      "/resources/clothing/backpack.glb",
        "dirty":      False,
        "stackable":  False,
        "style":      0.5,
    },
}


# =========================================================
# LOOKUPS
# =========================================================

def get_template(template_id):
    return ITEM_TEMPLATES.get(template_id)

def templates_by_category(category):
    return {
        tid: t for tid, t in ITEM_TEMPLATES.items()
        if t.get("category") == category
    }

def clothing_templates():
    return templates_by_category("clothing")

def is_clothing(template_id):
    t = get_template(template_id)
    return t is not None and t.get("category") == "clothing"
