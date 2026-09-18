"""
systems/document_search.py

Finding a specific document is a real, live query over actual data --
NOT a separately-maintained index that could drift out of sync. This
module IS "the complete set associated with the household and the
individual" the user asked for: computed on demand from the character's
own inventory, their household's real document_piles, and a document's
own "has_digital_copy" flag (stamped at creation for anything a company
would plausibly keep its own record of -- a contract, a receipt, an
insurance policy; NOT a hand-drawn "drawing").

Deliberately independent of the confirmed-broken retrieve_item/
return_item/search_room system (activities.py references functions
that don't exist anywhere) -- this is new, from scratch.
"""

_TIME_PERIOD_BUCKET_TICKS = 30 * 86400  # ~1 month per bucket

# Same numeric-modifier-by-trait-name style as systems/item_knowledge.py
# / systems/alarm_habits.py -- computer-search success chance for a
# document with no physical copy locatable.
COMPUTER_SEARCH_BASE_CHANCE = 0.55
_ORGANIZATION_MODIFIERS = {
    "organized":     0.25,
    "meticulous":    0.20,
    "tidy":          0.15,
    "pragmatic":     0.10,
    "disorganized": -0.25,
}
SEARCH_DURATION_TICKS_RANGE = (60, 300)   # 1-5 minutes


def computer_search_chance(c):
    chance = COMPUTER_SEARCH_BASE_CHANCE
    traits = set(c.get("traits", [])) | set(c.get("physical_traits", []))
    for trait, mod in _ORGANIZATION_MODIFIERS.items():
        if trait in traits:
            chance += mod
    return max(0.05, min(0.95, chance))


def _document_time_period(doc):
    tick = doc.get("signed_tick") or doc.get("purchase_tick")
    if tick is None:
        start_date = doc.get("start_date")
        if isinstance(start_date, dict):
            return f"{start_date.get('year')}-{start_date.get('month')}"
        return None
    return f"bucket_{tick // _TIME_PERIOD_BUCKET_TICKS}"


def _matches(doc, query):
    if not query:
        return True
    category = query.get("category")
    if category and doc.get("document_type") != category:
        return False
    person_or_company = query.get("person_or_company")
    if person_or_company:
        content = doc.get("content") or {}
        haystack = " ".join(str(v) for v in (
            content.get("sender"), content.get("company_id"), doc.get("company_id"),
        ) if v).lower()
        if person_or_company.lower() not in haystack:
            return False
    title = query.get("title")
    if title:
        content = doc.get("content") or {}
        doc_title = str(content.get("title") or doc.get("document_type") or "").lower()
        if title.lower() not in doc_title:
            return False
    time_period = query.get("time_period")
    if time_period and _document_time_period(doc) != time_period:
        return False
    return True


def register_digital_copy(c, world, doc):
    """Call right after creating+adding a document whose content sets
    has_digital_copy=True (a company plausibly keeping its own record --
    an employment contract, a receipt, an insurance policy; NOT a
    hand-drawn "drawing"). Snapshots it into the household's real
    digital_document_records so it stays findable via a computer search
    even after the physical copy is lost, given away, or mailed off
    (systems/jobs.py's contract is the first real caller; future
    receipt/insurance creation should call this the same way)."""
    if not (doc.get("content") or {}).get("has_digital_copy"):
        return
    household = world.get("households", {}).get(c.get("household_id"))
    if household is None:
        return
    household.setdefault("digital_document_records", {})[doc["id"]] = dict(doc)


def _all_household_documents(c, world):
    """Every real document this character's household could plausibly
    locate -- their own inventory, every item stashed in a household
    pile (systems/action_router.py::_route_organize_items()), and every
    persisted digital record (register_digital_copy()) -- the last of
    which can outlive its own physical copy."""
    from systems.personal_items import get_inventory

    docs = []
    for item in get_inventory(c):
        if item.get("template_id") in ("document", "drawing"):
            docs.append((item, "inventory", None))

    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return docs

    stored = household.get("stored_items", {})
    for pile_id, pile in household.get("document_piles", {}).items():
        for item_id in pile.get("item_ids", []):
            item = stored.get(item_id)
            if item and item.get("template_id") in ("document", "drawing"):
                docs.append((item, "pile", pile_id))

    for item in household.get("digital_document_records", {}).values():
        docs.append((item, "digital_record", None))
    return docs


def find_document(c, world, query):
    """Returns {"found": True, "location": "inventory"|"pile"|"digital"|
    "none", "item": <doc dict or None>, "pile_id": <id or None>}.

    Anything currently in the character's own inventory or a real
    household pile is a deterministic physical find (in hand, or known
    exactly where it is). The digital fallback only matters once a
    document can outlive its physical copy (e.g. Phase D's mail-in
    claim flow removing the item after it's mailed away) -- a matching
    document with a real has_digital_copy flag stays findable via a
    computer search even after the physical copy is gone."""
    all_docs = _all_household_documents(c, world)

    for item, location, pile_id in all_docs:
        if location in ("inventory", "pile") and _matches(item, query):
            return {"found": True, "location": location, "item": item, "pile_id": pile_id}

    for item, location, _pile_id in all_docs:
        if location == "digital_record" and _matches(item, query):
            return {"found": True, "location": "digital", "item": item, "pile_id": None}

    return {"found": False, "location": "none", "item": None, "pile_id": None}
