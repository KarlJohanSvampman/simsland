"""
Service catalog.

Legitimate services bill the household via mailbox at end of week.
Illicit services require cash on hiring (deducted immediately).

price_mode:
  "per_tile"  — quantity = number of tiles; labor_rate per tile + material from market
  "per_wall"  — quantity = number of wall segments; labor_rate + material_rate per segment
  "per_unit"  — quantity = number of items/openings; labor_rate + material_rate per unit
  "hourly"    — fixed duration_hours; hourly_rate total

worker_trait sets the name pool and animation used by the spawned NPC.
"""

TICKS_PER_HOUR = 3600

SERVICE_CATALOG = {

    # ── RECONSTRUCTION ───────────────────────────────────────────────────────
    "reconstruction": {
        "name":    "Renovation Firm",
        "illicit": False,
        "subtypes": {

            "floor_tiling": {
                "name":              "Floor Tiling",
                "price_mode":        "per_tile",
                "labor_rate":        8.0,      # per tile; material added from market catalog
                "duration_per_unit": 1800,     # 30 sim-min per tile
                "worker_trait":      "contractor",
            },

            "paint_wall": {
                "name":              "Wall Painting / Wallpaper",
                "price_mode":        "per_wall",
                "labor_rate":        25.0,
                "material_rate":     15.0,     # paint / wallpaper included
                "duration_per_unit": 3600,
                "worker_trait":      "contractor",
            },

            "build_wall": {
                "name":              "Wall Construction",
                "price_mode":        "per_wall",
                "labor_rate":        120.0,
                "material_rate":     60.0,
                "duration_per_unit": 7200,
                "worker_trait":      "contractor",
            },

            "remove_wall": {
                "name":              "Wall Removal / Demolition",
                "price_mode":        "per_wall",
                "labor_rate":        80.0,
                "material_rate":     0.0,
                "duration_per_unit": 5400,
                "worker_trait":      "contractor",
            },

            "insert_door": {
                "name":              "Door Installation",
                "price_mode":        "per_unit",
                "labor_rate":        150.0,
                "material_rate":     80.0,
                "duration_per_unit": 10800,
                "worker_trait":      "contractor",
            },

            "insert_window": {
                "name":              "Window Installation",
                "price_mode":        "per_unit",
                "labor_rate":        130.0,
                "material_rate":     90.0,
                "duration_per_unit": 10800,
                "worker_trait":      "contractor",
            },
        },
    },

    # ── REPAIR ───────────────────────────────────────────────────────────────
    "repair": {
        "name":    "Repair Service",
        "illicit": False,
        "subtypes": {

            "appliance_repair": {
                "name":              "Appliance / Prop Repair",
                "price_mode":        "per_unit",
                "labor_rate":        65.0,
                "material_rate":     30.0,     # parts estimate
                "duration_per_unit": 5400,
                "worker_trait":      "repairman",
            },
        },
    },

    # ── GARDENING ────────────────────────────────────────────────────────────
    "gardening": {
        "name":    "Gardening Service",
        "illicit": False,
        "subtypes": {

            "garden_maintenance": {
                "name":           "Garden Maintenance",
                "price_mode":     "hourly",
                "hourly_rate":    20.0,
                "duration_hours": 4,
                "worker_trait":   "gardener",
            },
        },
    },

    # ── BABYSITTING ───────────────────────────────────────────────────────────
    "babysitting": {
        "name":    "Babysitting",
        "illicit": False,
        "subtypes": {

            "childcare": {
                "name":           "Childcare",
                "price_mode":     "hourly",
                "hourly_rate":    15.0,
                "duration_hours": 8,
                "worker_trait":   "caregiver",
            },
        },
    },

    # ── DRUG DEALER ──────────────────────────────────────────────────────────
    "drug_dealer": {
        "name":    "Street Dealer",
        "illicit": True,
        "subtypes": {

            "cannabis": {
                "name":              "Cannabis",
                "price_mode":        "per_unit",
                "unit_price":        20.0,
                "duration_per_unit": 300,
                "worker_trait":      "dealer",
                "item_effects": {"fun": 0.4, "stress": -0.3, "hygiene": -0.05},
            },

            "stimulants": {
                "name":              "Stimulants",
                "price_mode":        "per_unit",
                "unit_price":        45.0,
                "duration_per_unit": 300,
                "worker_trait":      "dealer",
                "item_effects": {"energy": 0.6, "fun": 0.3, "stress": 0.2},
            },

            "downers": {
                "name":              "Downers",
                "price_mode":        "per_unit",
                "unit_price":        35.0,
                "duration_per_unit": 300,
                "worker_trait":      "dealer",
                "item_effects": {"stress": -0.5, "energy": -0.2, "fun": 0.2},
            },
        },
    },

    # ── ESCORT ───────────────────────────────────────────────────────────────
    "escort": {
        "name":    "Escort",
        "illicit": True,
        "subtypes": {

            "companionship": {
                "name":           "Companionship",
                "price_mode":     "hourly",
                "hourly_rate":    120.0,
                "duration_hours": 1,
                "worker_trait":   "escort",
                "item_effects":   {"fun": 0.5, "social": 0.4, "stress": -0.3},
            },
        },
    },
}

# ── Worker name pools per role ────────────────────────────────────────────────
WORKER_NAMES = {
    "contractor": ["Mike", "Dave", "Carlos", "Ivan", "Tom", "Raj", "Luca"],
    "repairman":  ["Bob", "Terry", "Phil", "Ed", "Gary"],
    "gardener":   ["Rosa", "Alan", "Kim", "Pete", "Sofia"],
    "caregiver":  ["Sarah", "Amy", "Lisa", "Jan", "Priya"],
    "dealer":     ["Sal", "Rico", "Manny", "Dex", "Vince"],
    "escort":     ["Jade", "Remy", "Lena", "Marco", "Nico"],
}

# ── Minimum cash required before illicit service is reachable ─────────────────
ILLICIT_MIN_CASH = {
    "cannabis":     20.0,
    "stimulants":   45.0,
    "downers":      35.0,
    "companionship": 120.0,
}
