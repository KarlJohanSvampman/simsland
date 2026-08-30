"""
Physical item templates.

Fields:
  name             str    display name
  category         str    hygiene / food / dishware / drink / linen / clothing / misc
  base_price       float  base market price (absent = not sold individually)
  stackable        bool   identical clean instances share a quantity counter
  max_stack        int    max per stack (default 99)
  dirty            bool   starts clean; tracks cleanliness at runtime
  consumable       bool   disappears when used
  uses             int    uses before consumed

  resource_type    str    if set, bulk purchase deposits this resource into household storage
  storage_container str   which storage bin receives the resource (fridge/pantry/bathroom/storage)
  quantity         int    units of resource per purchase (for bulk buys)
  nutrition        float  hunger restore (food)
  hunger_restore   int    hunger points restored
  hydration_restore int   hydration points restored
  energy_restore   int    energy points restored
  alcohol          bool   contains alcohol
  alcohol_units    float  standard units
  caffeine         bool   contains caffeine

Clothing-only:
  slot             str    body slot (see CLOTHING_SLOTS in clothing.py)
  bone             str    Three.js skeleton bone name
  model            str    .glb path; presence = renderable on body
  style            float  0-1 style rating
  warmth           float  0-1 warmth rating
  bilateral        bool   rendered on both feet/hands
"""

ITEM_TEMPLATES = {

    # =========================================================
    # HYGIENE
    # =========================================================

    "toilet_paper_roll": {
        "name":               "Toilet Paper Roll",
        "category":           "hygiene",
        "size":      1,
        "base_price":         2.0,
        "stackable":          True,
        "max_stack":          24,
        "consumable":         True,
        "uses":               1,
        "resource_type":      "TOILET_PAPER",
        "storage_container":  "bathroom",
        "quantity":           4,
    },

    "bath_towel": {
        "name":       "Bath Towel",
        "category":   "hygiene",
        "size":      2,
        "base_price": 18.0,
        "stackable":  True,
        "max_stack":  4,
        "dirty":      False,
        "consumable": False,
    },

    "hand_towel": {
        "name":       "Hand Towel",
        "category":   "hygiene",
        "size":      1,
        "base_price": 10.0,
        "stackable":  True,
        "max_stack":  6,
        "dirty":      False,
        "consumable": False,
    },

    "soap_bar": {
        "name":               "Soap Bar",
        "category":           "hygiene",
        "size":      1,
        "base_price":         3.0,
        "stackable":          True,
        "max_stack":          6,
        "consumable":         True,
        "uses":               20,
        "resource_type":      "HYGIENE",
        "storage_container":  "bathroom",
        "quantity":           3,
    },

    # =========================================================
    # LINEN
    # =========================================================

    "bed_sheet": {
        "name":       "Bed Sheet",
        "category":   "linen",
        "size":      2,
        "base_price": 25.0,
        "stackable":  True,
        "max_stack":  4,
        "dirty":      False,
        "consumable": False,
    },

    "pillow": {
        "name":       "Pillow",
        "category":   "linen",
        "size":      2,
        "base_price": 20.0,
        "stackable":  True,
        "max_stack":  4,
        "dirty":      False,
        "consumable": False,
    },

    "duvet": {
        "name":       "Duvet",
        "category":   "linen",
        "size":      3,
        "base_price": 80.0,
        "stackable":  False,
        "dirty":      False,
        "consumable": False,
    },

    # =========================================================
    # CLEANING
    # =========================================================

    "cleaning_spray": {
        "name":               "Cleaning Spray",
        "category":           "cleaning",
        "size":      1,
        "base_price":         5.0,
        "stackable":          True,
        "max_stack":          4,
        "consumable":         True,
        "uses":               10,
        "resource_type":      "CLEANING",
        "storage_container":  "storage",
        "quantity":           5,
    },

    # =========================================================
    # DISHWARE
    # =========================================================

    "plate_ceramic": {
        "name":       "Plate",
        "category":   "dishware",
        "size":      1,
        "base_price": 6.0,
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    "bowl_ceramic": {
        "name":       "Bowl",
        "category":   "dishware",
        "size":      1,
        "base_price": 5.0,
        "stackable":  True,
        "max_stack":  8,
        "dirty":      False,
        "consumable": False,
    },

    "mug_ceramic": {
        "name":       "Mug",
        "category":   "dishware",
        "size":      1,
        "base_price": 8.0,
        "stackable":  True,
        "max_stack":  6,
        "dirty":      False,
        "consumable": False,
    },

    "glass_water": {
        "name":       "Water Glass",
        "category":   "dishware",
        "size":      1,
        "base_price": 5.0,
        "stackable":  True,
        "max_stack":  8,
        "dirty":      False,
        "consumable": False,
    },

    "glass_wine": {
        "name":       "Wine Glass",
        "category":   "dishware",
        "size":      1,
        "base_price": 9.0,
        "stackable":  True,
        "max_stack":  6,
        "dirty":      False,
        "consumable": False,
    },

    "glass_rocks": {
        "name":       "Rocks Glass",
        "category":   "dishware",
        "size":      1,
        "base_price": 7.0,
        "stackable":  True,
        "max_stack":  6,
        "dirty":      False,
        "consumable": False,
    },

    "fork": {
        "name":       "Fork",
        "category":   "dishware",
        "size":      1,
        "base_price": 3.0,
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    "knife_table": {
        "name":       "Table Knife",
        "category":   "dishware",
        "size":      1,
        "base_price": 3.0,
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    "spoon": {
        "name":       "Spoon",
        "category":   "dishware",
        "size":      1,
        "base_price": 3.0,
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    "teaspoon": {
        "name":       "Teaspoon",
        "category":   "dishware",
        "size":      1,
        "base_price": 2.0,
        "stackable":  True,
        "max_stack":  12,
        "dirty":      False,
        "consumable": False,
    },

    # =========================================================
    # FOOD (served / prepared — physical items)
    # =========================================================

    "plate_of_pasta": {
        "name":            "Plate of Pasta",
        "category":        "food",
        "size":      1,
        "stackable":       False,
        "dirty":           False,
        "consumable":      True,
        "uses":            1,
        "nutrition":       0.75,
        "hunger_restore":  60,
    },

    "plate_of_rice": {
        "name":            "Plate of Rice",
        "category":        "food",
        "size":      1,
        "stackable":       False,
        "dirty":           False,
        "consumable":      True,
        "uses":            1,
        "nutrition":       0.6,
        "hunger_restore":  50,
    },

    "bowl_of_cereal": {
        "name":            "Bowl of Cereal",
        "category":        "food",
        "size":      1,
        "stackable":       False,
        "dirty":           False,
        "consumable":      True,
        "uses":            1,
        "nutrition":       0.5,
        "hunger_restore":  35,
    },

    "sandwich": {
        "name":            "Sandwich",
        "category":        "food",
        "size":      1,
        "stackable":       False,
        "consumable":      True,
        "uses":            1,
        "nutrition":       0.55,
        "hunger_restore":  40,
    },

    "slice_of_toast": {
        "name":            "Toast",
        "category":        "food",
        "size":      1,
        "stackable":       True,
        "max_stack":       4,
        "consumable":      True,
        "uses":            1,
        "nutrition":       0.3,
        "hunger_restore":  20,
    },

    "apple": {
        "name":            "Apple",
        "category":        "food",
        "size":      1,
        "base_price":      1.5,
        "stackable":       True,
        "max_stack":       6,
        "consumable":      True,
        "uses":            1,
        "nutrition":       0.65,
        "hunger_restore":  18,
    },

    "banana": {
        "name":            "Banana",
        "category":        "food",
        "size":      1,
        "base_price":      0.8,
        "stackable":       True,
        "max_stack":       6,
        "consumable":      True,
        "uses":            1,
        "nutrition":       0.6,
        "hunger_restore":  22,
    },

    "bag_of_chips_open": {
        "name":            "Bag of Chips",
        "category":        "food",
        "size":      1,
        "base_price":      3.0,
        "stackable":       False,
        "consumable":      True,
        "uses":            3,
        "nutrition":       0.2,
        "hunger_restore":  12,
    },

    # Bulk groceries — go into household storage when bought
    "groceries_basic": {
        "name":               "Groceries (Basic)",
        "category":           "groceries",
        "size":      3,
        "base_price":         40.0,
        "stackable":          False,
        "consumable":         True,
        "uses":               1,
        "resource_type":      "FOOD_CARB",
        "storage_container":  "pantry",
        "quantity":           8,
    },

    "groceries_protein": {
        "name":               "Groceries (Protein)",
        "category":           "groceries",
        "size":      3,
        "base_price":         55.0,
        "stackable":          False,
        "consumable":         True,
        "uses":               1,
        "resource_type":      "FOOD_PROTEIN",
        "storage_container":  "fridge",
        "quantity":           6,
    },

    # =========================================================
    # DRINKS
    # =========================================================

    "cup_of_coffee": {
        "name":               "Cup of Coffee",
        "category":           "drink",
        "size":      1,
        "stackable":          False,
        "dirty":              False,
        "consumable":         True,
        "uses":               1,
        "energy_restore":     20,
        "hydration_restore":  10,
        "caffeine":           True,
    },

    "cup_of_tea": {
        "name":               "Cup of Tea",
        "category":           "drink",
        "size":      1,
        "stackable":          False,
        "dirty":              False,
        "consumable":         True,
        "uses":               1,
        "energy_restore":     10,
        "hydration_restore":  15,
        "caffeine":           True,
    },

    "glass_of_water": {
        "name":               "Glass of Water",
        "category":           "drink",
        "size":      1,
        "stackable":          False,
        "dirty":              False,
        "consumable":         True,
        "uses":               1,
        "hydration_restore":  35,
    },

    "can_of_soda": {
        "name":               "Can of Soda",
        "category":           "drink",
        "size":      1,
        "base_price":         2.5,
        "stackable":          True,
        "max_stack":          6,
        "consumable":         True,
        "uses":               1,
        "hydration_restore":  20,
        "energy_restore":     8,
        "caffeine":           True,
        "resource_type":      "DRINK_SOFT",
        "storage_container":  "pantry",
        "quantity":           6,
    },

    "can_of_energy_drink": {
        "name":               "Energy Drink",
        "category":           "drink",
        "size":      1,
        "base_price":         3.5,
        "stackable":          True,
        "max_stack":          6,
        "consumable":         True,
        "uses":               1,
        "energy_restore":     35,
        "hydration_restore":  5,
        "caffeine":           True,
        "caffeine_strength":  "high",
    },

    "bottle_of_beer": {
        "name":               "Beer",
        "category":           "drink",
        "size":      1,
        "base_price":         3.0,
        "stackable":          True,
        "max_stack":          12,
        "consumable":         True,
        "uses":               1,
        "hydration_restore":  5,
        "alcohol":            True,
        "alcohol_units":      1.0,
        "resource_type":      "DRINK_ALCOHOL",
        "storage_container":  "pantry",
        "quantity":           6,
    },

    "glass_of_red_wine": {
        "name":               "Glass of Red Wine",
        "category":           "drink",
        "size":      1,
        "stackable":          False,
        "dirty":              False,
        "consumable":         True,
        "uses":               1,
        "alcohol":            True,
        "alcohol_units":      1.5,
    },

    "glass_of_white_wine": {
        "name":               "Glass of White Wine",
        "category":           "drink",
        "size":      1,
        "stackable":          False,
        "dirty":              False,
        "consumable":         True,
        "uses":               1,
        "alcohol":            True,
        "alcohol_units":      1.5,
    },

    "glass_of_spirits": {
        "name":               "Glass of Spirits",
        "category":           "drink",
        "size":      1,
        "stackable":          False,
        "dirty":              False,
        "consumable":         True,
        "uses":               1,
        "alcohol":            True,
        "alcohol_units":      2.5,
    },

    "shot_of_spirits": {
        "name":               "Shot",
        "category":           "drink",
        "size":      1,
        "stackable":          False,
        "consumable":         True,
        "uses":               1,
        "alcohol":            True,
        "alcohol_units":      1.0,
    },

    # Bulk drink stock
    "wine_bottle_red": {
        "name":               "Bottle of Red Wine",
        "category":           "drink",
        "size":      1,
        "base_price":         18.0,
        "stackable":          True,
        "max_stack":          6,
        "consumable":         True,
        "uses":               5,
        "alcohol":            True,
        "alcohol_units":      1.5,
    },

    "wine_bottle_white": {
        "name":               "Bottle of White Wine",
        "category":           "drink",
        "size":      1,
        "base_price":         16.0,
        "stackable":          True,
        "max_stack":          6,
        "consumable":         True,
        "uses":               5,
        "alcohol":            True,
        "alcohol_units":      1.5,
    },

    "spirits_bottle": {
        "name":               "Bottle of Spirits",
        "category":           "drink",
        "size":      1,
        "base_price":         32.0,
        "stackable":          True,
        "max_stack":          4,
        "consumable":         True,
        "uses":               20,
        "alcohol":            True,
        "alcohol_units":      1.0,
    },

    # =========================================================
    # CLOTHING
    # =========================================================

    # --- HEAD ---
    "baseball_cap": {
        "name": "Baseball Cap", "category": "clothing",
        "slot": "head", "bone": "Head",
        "model": "/resources/clothing/baseball_cap.glb",
        "base_price": 22.0, "dirty": False,
        "stackable": True, "max_stack": 4, "style": 0.45,
        "size": 1,
    },
    "beanie": {
        "name": "Beanie", "category": "clothing",
        "slot": "head", "bone": "Head",
        "model": "/resources/clothing/beanie.glb",
        "base_price": 18.0, "dirty": False,
        "stackable": True, "max_stack": 4, "style": 0.5,
        "size": 1,
    },

    # --- HAIR ---
    "hair_short_brown": {
        "name": "Short Brown Hair", "category": "clothing",
        "slot": "hair", "bone": "Head",
        "model": "/resources/clothing/hair_short_brown.glb",
        "dirty": False, "stackable": False, "style": 0.6,
        "size": 1,
    },
    "hair_long_black": {
        "name": "Long Black Hair", "category": "clothing",
        "slot": "hair", "bone": "Head",
        "model": "/resources/clothing/hair_long_black.glb",
        "dirty": False, "stackable": False, "style": 0.7,
        "size": 1,
    },

    # --- NECK ---
    "scarf_knit": {
        "name": "Knit Scarf", "category": "clothing",
        "slot": "neck", "bone": "Neck",
        "model": "/resources/clothing/scarf_knit.glb",
        "base_price": 25.0, "dirty": False,
        "stackable": True, "max_stack": 2, "style": 0.55,
        "size": 1,
    },

    # --- OUTERWEAR ---
    "jacket_hoodie": {
        "name": "Hoodie", "category": "clothing",
        "slot": "outerwear", "bone": "Spine2",
        "model": "/resources/clothing/hoodie.glb",
        "base_price": 55.0, "dirty": False,
        "stackable": True, "max_stack": 3, "style": 0.55, "warmth": 0.6,
        "size": 2,
    },
    "jacket_denim": {
        "name": "Denim Jacket", "category": "clothing",
        "slot": "outerwear", "bone": "Spine2",
        "model": "/resources/clothing/jacket_denim.glb",
        "base_price": 90.0, "dirty": False,
        "stackable": True, "max_stack": 2, "style": 0.75, "warmth": 0.5,
        "size": 2,
    },
    "jacket_winter": {
        "name": "Winter Coat", "category": "clothing",
        "slot": "outerwear", "bone": "Spine2",
        "model": "/resources/clothing/jacket_winter.glb",
        "base_price": 180.0, "dirty": False,
        "stackable": False, "style": 0.6, "warmth": 0.95,
        "size": 2,
    },

    # --- TORSO ---
    "tshirt_white": {
        "name": "White T-Shirt", "category": "clothing",
        "slot": "torso", "bone": "Spine1",
        "model": "/resources/clothing/tshirt_white.glb",
        "base_price": 15.0, "dirty": False,
        "stackable": True, "max_stack": 6, "style": 0.4,
        "size": 1,
    },
    "tshirt_black": {
        "name": "Black T-Shirt", "category": "clothing",
        "slot": "torso", "bone": "Spine1",
        "model": "/resources/clothing/tshirt_black.glb",
        "base_price": 15.0, "dirty": False,
        "stackable": True, "max_stack": 6, "style": 0.5,
        "size": 1,
    },
    "shirt_flannel": {
        "name": "Flannel Shirt", "category": "clothing",
        "slot": "torso", "bone": "Spine1",
        "model": "/resources/clothing/shirt_flannel.glb",
        "base_price": 45.0, "dirty": False,
        "stackable": True, "max_stack": 4, "style": 0.55,
        "size": 1,
    },
    "shirt_dress": {
        "name": "Dress Shirt", "category": "clothing",
        "slot": "torso", "bone": "Spine1",
        "model": "/resources/clothing/shirt_dress.glb",
        "base_price": 70.0, "dirty": False,
        "stackable": True, "max_stack": 4, "style": 0.85,
        "size": 1,
    },
    "top_crop": {
        "name": "Crop Top", "category": "clothing",
        "slot": "torso", "bone": "Spine1",
        "model": "/resources/clothing/top_crop.glb",
        "base_price": 30.0, "dirty": False,
        "stackable": True, "max_stack": 4, "style": 0.7,
        "size": 1,
    },

    # --- UNDERSHIRT ---
    "tank_top": {
        "name": "Tank Top", "category": "clothing",
        "slot": "undershirt", "bone": "Spine1",
        "model": "/resources/clothing/tank_top.glb",
        "base_price": 12.0, "dirty": False,
        "stackable": True, "max_stack": 6, "style": 0.35,
        "size": 1,
    },

    # --- LEGS ---
    "jeans_blue": {
        "name": "Blue Jeans", "category": "clothing",
        "slot": "legs", "bone": "Hips",
        "model": "/resources/clothing/jeans_blue.glb",
        "base_price": 65.0, "dirty": False,
        "stackable": True, "max_stack": 3, "style": 0.65,
        "size": 2,
    },
    "jeans_black": {
        "name": "Black Jeans", "category": "clothing",
        "slot": "legs", "bone": "Hips",
        "model": "/resources/clothing/jeans_black.glb",
        "base_price": 65.0, "dirty": False,
        "stackable": True, "max_stack": 3, "style": 0.7,
        "size": 2,
    },
    "sweatpants": {
        "name": "Sweatpants", "category": "clothing",
        "slot": "legs", "bone": "Hips",
        "model": "/resources/clothing/sweatpants.glb",
        "base_price": 35.0, "dirty": False,
        "stackable": True, "max_stack": 3, "style": 0.3,
        "size": 2,
    },
    "shorts_casual": {
        "name": "Casual Shorts", "category": "clothing",
        "slot": "legs", "bone": "Hips",
        "model": "/resources/clothing/shorts_casual.glb",
        "base_price": 28.0, "dirty": False,
        "stackable": True, "max_stack": 4, "style": 0.4,
        "size": 1,
    },
    "dress_casual": {
        "name": "Casual Dress", "category": "clothing",
        "slot": "legs", "bone": "Hips",
        "model": "/resources/clothing/dress_casual.glb",
        "base_price": 85.0, "dirty": False,
        "stackable": False, "style": 0.8,
        "size": 2,
    },
    "suit_trousers": {
        "name": "Suit Trousers", "category": "clothing",
        "slot": "legs", "bone": "Hips",
        "model": "/resources/clothing/suit_trousers.glb",
        "base_price": 120.0, "dirty": False,
        "stackable": True, "max_stack": 2, "style": 0.9,
        "size": 2,
    },
    "pyjama_bottoms": {
        "name": "Pyjama Bottoms", "category": "clothing",
        "slot": "legs", "bone": "Hips",
        "model": "/resources/clothing/pyjama_bottoms.glb",
        "base_price": 22.0, "dirty": False,
        "stackable": True, "max_stack": 3, "style": 0.2,
        "size": 2,
    },

    # --- UNDERWEAR ---
    "underwear_basic": {
        "name": "Underwear", "category": "clothing",
        "slot": "underwear", "bone": "Hips",
        "model": "/resources/clothing/underwear_basic.glb",
        "base_price": 8.0, "dirty": False,
        "stackable": True, "max_stack": 7, "style": 0.3,
        "size": 1,
    },
    "boxer_shorts": {
        "name": "Boxer Shorts", "category": "clothing",
        "slot": "underwear", "bone": "Hips",
        "model": "/resources/clothing/boxer_shorts.glb",
        "base_price": 9.0, "dirty": False,
        "stackable": True, "max_stack": 7, "style": 0.3,
        "size": 1,
    },

    # --- SOCKS ---
    "socks_white": {
        "name": "White Socks", "category": "clothing",
        "slot": "socks", "bone": "LeftFoot",
        "model": "/resources/clothing/socks_white.glb",
        "base_price": 5.0, "dirty": False,
        "stackable": True, "max_stack": 7, "style": 0.25, "bilateral": True,
        "size": 1,
    },
    "socks_ankle": {
        "name": "Ankle Socks", "category": "clothing",
        "slot": "socks", "bone": "LeftFoot",
        "model": "/resources/clothing/socks_ankle.glb",
        "base_price": 5.0, "dirty": False,
        "stackable": True, "max_stack": 7, "style": 0.3, "bilateral": True,
        "size": 1,
    },

    # --- FEET ---
    "sneakers_white": {
        "name": "White Sneakers", "category": "clothing",
        "slot": "feet", "bone": "LeftFoot",
        "model": "/resources/clothing/sneakers_white.glb",
        "base_price": 90.0, "dirty": False,
        "stackable": False, "style": 0.7, "bilateral": True,
        "size": 2,
    },
    "shoes_casual": {
        "name": "Casual Shoes", "category": "clothing",
        "slot": "feet", "bone": "LeftFoot",
        "model": "/resources/clothing/shoes_casual.glb",
        "base_price": 70.0, "dirty": False,
        "stackable": False, "style": 0.6, "bilateral": True,
        "size": 2,
    },
    "shoes_dress": {
        "name": "Dress Shoes", "category": "clothing",
        "slot": "feet", "bone": "LeftFoot",
        "model": "/resources/clothing/shoes_dress.glb",
        "base_price": 160.0, "dirty": False,
        "stackable": False, "style": 0.9, "bilateral": True,
        "size": 2,
    },
    "slippers": {
        "name": "Slippers", "category": "clothing",
        "slot": "feet", "bone": "LeftFoot",
        "model": "/resources/clothing/slippers.glb",
        "base_price": 20.0, "dirty": False,
        "stackable": False, "style": 0.15, "bilateral": True,
        "size": 1,
    },

    # --- HANDS / WRISTS ---
    "gloves_winter": {
        "name": "Winter Gloves", "category": "clothing",
        "slot": "hands", "bone": "LeftHand",
        "model": "/resources/clothing/gloves_winter.glb",
        "base_price": 30.0, "dirty": False,
        "stackable": False, "style": 0.5, "bilateral": True, "warmth": 0.7,
        "size": 1,
    },
    "watch_casual": {
        "name": "Casual Watch", "category": "clothing",
        "slot": "wrist_l", "bone": "LeftForeArm",
        "model": "/resources/clothing/watch_casual.glb",
        "base_price": 80.0, "dirty": False,
        "stackable": False, "style": 0.7,
        "size": 1,
    },

    # --- ACCESSORY ---
    "backpack": {
        "name": "Backpack", "category": "clothing",
        "slot": "accessory", "bone": "Spine2",
        "model": "/resources/clothing/backpack.glb",
        "base_price": 60.0, "dirty": False,
        "stackable": False, "style": 0.5,
        "size": 2,
    },

    # =========================================================
    # ELECTRONICS (discrete purchasable items)
    # =========================================================

    "smartphone_budget": {
        "name":       "Budget Smartphone",
        "category":   "smartphone",
        "size":      3,
        "base_price": 250.0,
        "stackable":  False,
        "consumable": False,
        "object_type":"phone",
        "apps":       ["send_message", "call_contact", "check_stocks", "browse_news",
                       "order_delivery", "open_banking_app", "use_rideshare",
                       "order_taxi_by_phone_app"],
        "battery":    1.0,
    },

    "smartphone_midrange": {
        "name":       "Midrange Smartphone",
        "category":   "smartphone",
        "size":      3,
        "base_price": 500.0,
        "stackable":  False,
        "consumable": False,
        "object_type":"phone",
        "apps":       ["send_message", "call_contact", "check_stocks", "browse_news",
                       "order_delivery", "open_banking_app", "use_rideshare",
                       "order_taxi_by_phone_app"],
        "battery":    1.0,
        "quality":    0.75,
    },

    "smartphone_premium": {
        "name":       "Premium Smartphone",
        "category":   "smartphone",
        "size":      3,
        "base_price": 900.0,
        "stackable":  False,
        "consumable": False,
        "object_type":"phone",
        "apps":       ["send_message", "call_contact", "check_stocks", "browse_news",
                       "order_delivery", "open_banking_app", "use_rideshare",
                       "order_taxi_by_phone_app"],
        "battery":    1.0,
        "quality":    0.95,
    },

    "laptop_basic": {
        "name":       "Basic Laptop",
        "category":   "computer",
        "size":      4,
        "base_price": 700.0,
        "stackable":  False,
        "consumable": False,
        "object_type":"computer",
        "quality":    0.55,
    },

    "laptop_gaming": {
        "name":       "Gaming Laptop",
        "category":   "computer",
        "size":      4,
        "base_price": 1800.0,
        "stackable":  False,
        "consumable": False,
        "object_type":"computer",
        "quality":    0.92,
    },

    "phone_charger": {
        "name":       "Phone Charger",
        "category":   "accessory",
        "size":       1,
        "base_price": 15.0,
        "stackable":  False,
        "consumable": False,
        "object_type":"charger",
    },

    "laptop_charger": {
        "name":       "Laptop Charger",
        "category":   "accessory",
        "size":       1,
        "base_price": 30.0,
        "stackable":  False,
        "consumable": False,
        "object_type":"charger",
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

def sellable_templates():
    """Templates that appear in the market (have a base_price)."""
    return {
        tid: t for tid, t in ITEM_TEMPLATES.items()
        if "base_price" in t
    }
