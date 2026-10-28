"""
Ingredients -- the physical food items (docs/food_system.md).

Every one has
  food_group   carb | protein | vegetable | dairy | fruit | bread | none     (spice is its own flag)
  calories     per unit (one item of the stack)
  fat_pct      share of those calories that come from fat, 0..1
  base_price   per unit

Only fruit, bread and the ready-made "none" items are eaten as they are (`ready_to_eat`); the rest are cooked.
Spices carry no nutrition worth counting and only add taste (`spice_taste`).
"""

EAT_AS_IS = {"fruit", "bread", "none"}
DAILY_KCAL = 2000


def _item(name, group, calories, fat_pct, price, stack=8, **extra):
    t = {
        "name": name, "category": "food", "food_group": group, "size": 1, "stackable": True, "max_stack": stack,
        "consumable": True, "uses": 1, "calories": calories, "fat_pct": fat_pct, "base_price": price,
        "ready_to_eat": group in EAT_AS_IS,
        # what the older hunger / daily-nutrition code reads, now derived from the calories (2000 kcal = a day)
        "nutrition": round(calories / DAILY_KCAL, 3), "hunger_restore": round(calories / 8),
    }
    t.update(extra)
    return t


def _spice(name, price, taste):
    return _item(name, "spice", 3, 0.0, price, stack=12, spice=True, spice_taste=taste, ready_to_eat=False)


INGREDIENTS = {
    # carbs
    "potato":        _item("Potato", "carb", 110, 0.01, 0.6),
    "rice":          _item("Rice", "carb", 200, 0.02, 0.5),
    "pasta":         _item("Pasta", "carb", 220, 0.08, 0.6),
    "noodles":       _item("Noodles", "carb", 210, 0.10, 0.7),
    # protein
    "chicken":       _item("Chicken", "protein", 165, 0.20, 2.2),
    "ground_beef":   _item("Ground beef", "protein", 250, 0.65, 2.6),
    "salmon":        _item("Salmon", "protein", 200, 0.50, 3.2),
    "egg":           _item("Egg", "protein", 80, 0.62, 0.4),
    "lentils":       _item("Lentils", "protein", 230, 0.04, 0.7),
    "sausage":       _item("Sausage", "protein", 300, 0.75, 1.6),
    # vegetables
    "carrot":        _item("Carrot", "vegetable", 40, 0.05, 0.3),
    "broccoli":      _item("Broccoli", "vegetable", 35, 0.10, 0.9),
    "tomato":        _item("Tomato", "vegetable", 25, 0.10, 0.5),
    "onion":         _item("Onion", "vegetable", 40, 0.03, 0.3),
    "spinach":       _item("Spinach", "vegetable", 25, 0.10, 0.8),
    "bell_pepper":   _item("Bell pepper", "vegetable", 30, 0.08, 0.9),
    # dairy
    "cheese":        _item("Cheese", "dairy", 110, 0.70, 1.2),
    "milk":          _item("Milk", "dairy", 120, 0.45, 0.4),
    "yogurt":        _item("Yogurt", "dairy", 100, 0.30, 0.6),
    "butter":        _item("Butter", "dairy", 100, 1.00, 0.5),
    # fruit
    "apple":         _item("Apple", "fruit", 95, 0.03, 0.8, stack=6),
    "banana":        _item("Banana", "fruit", 105, 0.03, 0.5, stack=6),
    "orange":        _item("Orange", "fruit", 65, 0.02, 0.7, stack=6),
    "grapes":        _item("Grapes", "fruit", 70, 0.03, 0.9, stack=6),
    # bread (a loaf on the counter takes ingredients and becomes a sandwich)
    "bread_loaf":    _item("Bread", "bread", 150, 0.15, 1.4, stack=4, holds_ingredients=True, capacity=6),
    "bread_roll":    _item("Bread roll", "bread", 120, 0.15, 0.4, stack=6, holds_ingredients=True, capacity=4),
    # ready-made, eaten as they are -- the unhealthy end of the scale
    "bag_of_chips":  _item("Bag of chips", "none", 150, 0.55, 1.2, stack=4),
    "cereal_bowl":   _item("Cereal", "none", 200, 0.12, 0.7, stack=4),
    "chocolate_bar": _item("Chocolate bar", "none", 230, 0.55, 1.0, stack=6),
    # spices: taste only
    "salt":          _spice("Salt", 0.2, 0.03),
    "pepper":        _spice("Pepper", 0.3, 0.03),
    "garlic":        _spice("Garlic", 0.3, 0.05),
    "herbs":         _spice("Herbs", 0.5, 0.05),
    "curry_powder":  _spice("Curry powder", 0.8, 0.06),
}
