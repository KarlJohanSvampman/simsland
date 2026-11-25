"""
systems/wardrobe.py -- clothes to wear, to change into, and to wash.

Live (2026-11-24): every character was nude, all the time. Clothes only existed for characters made in the Character
Creator with an outfit; generated ones started with a pair of socks, and getting dressed (systems/dressing.py) needs a
wardrobe prop -- none of the houses has one. Now:

  - Everyone owns a starter wardrobe: underwear, socks, three tops, two bottoms, shoes, a jacket, pyjamas, and a smart
    set for working adults -- real items (definitions.json item_templates), picked to suit their body model, kept in
    c["closet"] (their part of the house's storage -- there are no wardrobe props yet). Items with no 3D model are
    simply invisible but still worn; adult men get "boot_jeans", which has one.
  - They dress: in pyjamas for sleep, in day clothes when they get up and after a shower or bath, and whenever they are
    found nude while awake (not in an intimate moment, and not shortly after taking their clothes off on purpose).
  - Worn clothes get dirty over time (systems/clothing.py::tick_clothing_dirty). Dirty clothes go back into the closet
    as laundry. When a household's pile reaches LAUNDRY_PILE, or someone has run out of clean clothes in a slot, an
    adult at home gets a "do_laundry" chore -> the washing machine (do_laundry_fill, systems/task_process.py's laundry
    process), which washes what's in everyone's closet too.

c["closet"] = [item, ...]   clean and dirty ("dirty": True) clothes not being worn
"""

import random

OWNER = "wardrobe"

# slot -> template choices
_TOPS = ["tshirt_white", "tshirt_black", "shirt_flannel"]
_TOPS_YOUNG_F = ["top_crop"]
_BOTTOMS = ["jeans_blue", "jeans_black", "sweatpants", "shorts_casual"]
_SHOES = ["sneakers_white", "shoes_casual"]
_OUTER = ["jacket_hoodie", "jacket_denim"]
_DAY_SLOTS = ("underwear", "socks", "torso", "legs", "feet")
_SLEEP_TAG = "sleep"

LAUNDRY_PILE = 8
CHECK_EVERY = 600                 # sim seconds between sweeps (nude while awake, laundry pile)
UNDRESSED_ON_PURPOSE_TICKS = 1800
_ASLEEP = {"sleep", "nap", "take_nap"}
_BARE = {"take_shower", "take_bath", "shower", "bath", "swim", "masturbate_in_bed", "intercourse", "sex", "skinny_dip"}


def _templates(world):
    return (world.get("definitions") or {}).get("item_templates") or {}


def _fits(world, c, tid):
    from systems.clothing import is_body_compatible
    tpl = _templates(world).get(tid)
    return bool(tpl) and is_body_compatible(tpl, c.get("model"))


def _make(world, c, tid):
    from systems.personal_items import make_item
    try:
        return make_item(tid, world=world, owner_id=c.get("id"))
    except ValueError:
        return None


def starter_kit(world, c):
    """The template ids of a starter wardrobe for c (seeded by id, so the same each time)."""
    rng = random.Random(f"wardrobe:{c.get('id')}")
    age, sex = c.get("age") or 30, c.get("sex") or "male"
    male = sex == "male"
    kit = ["underwear_basic"] * 2 + (["boxer_shorts"] if male else ["underwear_basic"])
    kit += ["socks_white", "socks_white", "socks_ankle"]
    tops = list(_TOPS) + (_TOPS_YOUNG_F if (not male and 14 <= age <= 35) else [])
    kit += rng.sample(tops, 3)
    if male and age >= 18 and _fits(world, c, "boot_jeans"):
        kit += ["boot_jeans", rng.choice(["jeans_black", "sweatpants"])]
    else:
        bottoms = list(_BOTTOMS) + (["dress_casual"] if not male and age >= 12 else [])
        kit += rng.sample(bottoms, 2)
    kit += [rng.choice(_SHOES), rng.choice(_OUTER), "pyjama_bottoms"]
    if 22 <= age < 65 and c.get("occupation") not in (None, "", "none"):
        kit += ["shirt_dress", "suit_trousers" if male else rng.choice(["suit_trousers", "dress_casual"]), "shoes_dress"]
    return [t for t in kit if _fits(world, c, t)]


def ensure_closet(world, c):
    """Stock c's closet once (existing characters too: lazily, the first time anyone looks)."""
    if c.get("_closet_stocked"):
        return c.setdefault("closet", [])
    closet = c.setdefault("closet", [])
    for tid in starter_kit(world, c):
        item = _make(world, c, tid)
        if item:
            item["dirty"] = False
            closet.append(item)
    c["_closet_stocked"] = True
    return closet


# ── dressing ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _is_sleepwear(item):
    return _SLEEP_TAG in (item.get("tags") or []) or item.get("template_id") == "pyjama_bottoms"


def _pick(closet, slot, sleep, rng):
    items = [i for i in closet if i.get("slot") == slot]
    if sleep:
        pref = [i for i in items if _is_sleepwear(i) and not i.get("dirty")] or [i for i in items if _is_sleepwear(i)]
    else:
        pref = [i for i in items if not _is_sleepwear(i) and not i.get("dirty")]
        work = [i for i in pref if "formal" not in (i.get("tags") or [])]
        pref = work or pref
        if not pref:                                         # nothing clean: a worn-once item will have to do
            pref = [i for i in items if not _is_sleepwear(i)]
    return rng.choice(pref) if pref else None


def undress_to_closet(world, c):
    from systems.clothing import ensure_worn, recompute_nudity_state
    ensure_worn(c)
    closet = ensure_closet(world, c)
    for slot, item in list(c["worn"].items()):
        if item and slot not in ("hair",):
            closet.append(item)
            c["worn"][slot] = None
    recompute_nudity_state(c)


def dress(world, c, sleep=False):
    """Put on clothes from the closet: pyjamas (sleep=True) or a day outfit. Returns the names of what they put on."""
    from systems.clothing import ensure_worn, recompute_nudity_state
    ensure_worn(c)
    closet = ensure_closet(world, c)
    rng = random.Random(f"{c.get('id')}:{world.get('tick', 0)}")
    slots = ("underwear", "torso", "legs") if sleep else _DAY_SLOTS
    if not sleep and _outdoor_weather_cold(world):
        slots = slots + ("outerwear",)
    put_on = []
    for slot in slots:
        if c["worn"].get(slot):
            continue
        item = _pick(closet, slot, sleep, rng)
        if not item and sleep and slot in ("torso", "underwear"):
            item = _pick(closet, slot, False, rng)           # an old t-shirt, ordinary underwear, to sleep in
        if item:
            closet.remove(item)
            c["worn"][slot] = item
            put_on.append(item.get("name") or item.get("template_id"))
    recompute_nudity_state(c)
    return put_on


def change(world, c, sleep=False):
    undress_to_closet(world, c)
    return dress(world, c, sleep=sleep)


def _outdoor_weather_cold(world):
    temp = (world.get("weather") or {}).get("temperature_c")
    return isinstance(temp, (int, float)) and temp < 12


def _wearing_sleepwear(c):
    legs = (c.get("worn") or {}).get("legs")
    return bool(legs) and _is_sleepwear(legs)


def _exempt(world, c):
    if c.get("off_grid") or c.get("alive") is False or c.get("active_intercourse_session_id"):
        return True
    act = ((c.get("activity") or {}).get("type") or "")
    if act in _BARE:
        return True
    return world.get("tick", 0) < (c.get("_undressed_on_purpose_until") or 0)


def check(world, c):
    """Dressed for what they're doing: pyjamas asleep, clothes awake."""
    if _exempt(world, c):
        return
    asleep = ((c.get("activity") or {}).get("type") or "") in _ASLEEP
    if asleep and not _wearing_sleepwear(c):
        change(world, c, sleep=True)
    elif not asleep and (c.get("is_nude") or _wearing_sleepwear(c)):
        change(world, c, sleep=False)


# ── laundry ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _members(world, household):
    chars = world.get("characters") or {}
    return [chars[m] for m in household.get("members") or [] if m in chars]


def dirty_count(world, household):
    return sum(1 for m in _members(world, household) for i in (m.get("closet") or []) if i.get("dirty"))


def _out_of_clean(c):
    closet = c.get("closet") or []
    for slot in ("underwear", "torso", "legs"):
        if not any(i.get("slot") == slot and not i.get("dirty") and not _is_sleepwear(i) for i in closet):
            return True
    return False


def needs_laundry(world, household):
    return dirty_count(world, household) >= LAUNDRY_PILE or any(_out_of_clean(m) for m in _members(world, household)
                                                                 if m.get("_closet_stocked"))


def _laundry_running(world, household):
    return any(p.get("type") == "laundry" and p.get("household_id") == household.get("id") and not p.get("completed")
               for p in world.get("household_processes") or [])


def raise_laundry(world, household):
    """An adult at home gets the chore (once)."""
    from brain.intentions import add_intention
    members = _members(world, household)
    if any(any(i.get("type") == "do_laundry" for i in m.get("active_intentions") or []) for m in members):
        return None
    home = household.get("home_id")
    adults = [m for m in members if (m.get("age") or 0) >= 14 and not m.get("off_grid")
              and m.get("building_id") == home and ((m.get("activity") or {}).get("type") not in _ASLEEP)]
    if not adults:
        return None
    who = min(adults, key=lambda m: len(m.get("active_intentions") or []))
    add_intention(who, {"type": "do_laundry", "category": "chores", "priority": 50,
                        "reason": f"the laundry's piling up ({dirty_count(world, household)} dirty things)"})
    return who


def launder_closets(world, household):
    """A load is done (systems/task_process.py::_laundry_on_complete): everyone's dirty clothes are clean again."""
    from systems.clothing import launder_item
    from brain.intentions import remove_intention
    for m in _members(world, household):
        for item in m.get("closet") or []:
            if item.get("dirty"):
                launder_item(item)
        try:
            remove_intention(m, "do_laundry")
        except Exception:
            pass


def sweep(world, entry=None):
    for c in (world.get("characters") or {}).values():
        try:
            check(world, c)
        except Exception as exc:                       # noqa: BLE001
            print(f"[wardrobe] {c.get('id')}: {exc!r}")
    for hh in (world.get("households") or {}).values():
        try:
            if needs_laundry(world, hh) and not _laundry_running(world, hh):
                raise_laundry(world, hh)
        except Exception as exc:                       # noqa: BLE001
            print(f"[wardrobe] laundry {hh.get('id')}: {exc!r}")


# ── events ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _on_started(data, world):
    c = (world.get("characters") or {}).get(data.get("character_id"))
    if not c or c.get("off_grid"):
        return
    t = data.get("activity_type")
    if t in _ASLEEP:
        change(world, c, sleep=True)
    elif t in ("take_shower", "take_bath", "shower", "bath"):
        undress_to_closet(world, c)


def _on_ended(data, world):
    c = (world.get("characters") or {}).get(data.get("character_id"))
    if not c or c.get("off_grid"):
        return
    t = data.get("activity_type") or data.get("type")
    if t in _ASLEEP or t in ("take_shower", "take_bath", "shower", "bath"):
        if t in ("take_shower", "take_bath", "shower", "bath"):
            for item in (c.get("worn") or {}).values():          # fresh clothes after a wash
                if item:
                    item["dirty"] = True
        change(world, c, sleep=False)


def prompt_line(world, c):
    """What they're wearing, and whether their clean clothes are running out."""
    worn = [i.get("name") for s, i in (c.get("worn") or {}).items()
            if i and s in ("torso", "legs", "outerwear", "feet")]
    bits = []
    if worn:
        bits.append("You're wearing " + ", ".join(n.lower() for n in worn if n) + ".")
    if c.get("_closet_stocked") and _out_of_clean(c) and (c.get("age") or 0) >= 12:
        bits.append("You're out of clean clothes -- the laundry needs doing.")
    return " ".join(bits)


from core import scheduler as _scheduler        # noqa: E402
from core.event_bus import subscribe as _subscribe   # noqa: E402

_scheduler.register_recurring(OWNER, sweep, CHECK_EVERY, offset=120)
_subscribe("activity_started", _on_started)
_subscribe("activity_finished", _on_ended)
_subscribe("activity_interrupted", _on_ended)
