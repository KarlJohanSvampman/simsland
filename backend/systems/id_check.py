"""
systems/id_check.py

Age verification for entry into an age-gated venue (bar/nightclub/
adult_entertainment). Those company_templates carry a real minimum_age
field (definitions.json) -- but off-grid leisure trips in this codebase
are abstracted flavor with no real per-instance venue selection to hook
a check onto (confirmed: offgrid.py's _shopping_leisure_details()/
_VENUE_FLAVOR are "deliberately thin, since no venue/participant data
exists for these reasons today"). check_id_for_entry() is therefore
applied at DISPATCH time instead, when maybe_go_offgrid() is about to
send someone on a leisure trip that happens to roll "night out at a
bar"-flavored -- see that call site in offgrid.py::maybe_go_offgrid().
minimum_age's default here is kept in sync by hand with the "bar"/
"nightclub" company_templates' own minimum_age value (21), the same
"kept in sync" convention this project already uses elsewhere (e.g.
main.py/api/view.py's duplicated _view_radius table).
"""

import random

# Real-world bouncer practice: card anyone who looks meaningfully under
# the legal minimum, not just those right at the line -- "if their
# appearance makes them look young" is approximated here by chronological
# age (no apparent-age/perceived-age system exists to model this more
# precisely; inventing one just for this would be a lot of new machinery
# for a cosmetic nuance). Only characters below this threshold are ever
# scrutinized at all -- older characters walk in unchecked.
CARDING_AGE_THRESHOLD = 25
BAR_MINIMUM_AGE = 21


def check_id_for_entry(c, world, minimum_age=BAR_MINIMUM_AGE):
    """Returns True if c is let in."""
    age = c.get("age", 0)
    if age >= CARDING_AGE_THRESHOLD:
        return True

    from systems.personal_items import get_carried_id
    doc = get_carried_id(c)
    if not doc:
        return age >= minimum_age  # no ID at all -- judged on real age alone

    claimed_age = None
    birth_year = doc.get("birth_year")
    if birth_year is not None:
        calendar_year = world.get("calendar", {}).get("year")
        if calendar_year is not None:
            claimed_age = calendar_year - birth_year

    if claimed_age is None:
        claimed_age = age  # document with no usable birthdate -- fall back to real age

    if claimed_age < minimum_age:
        return False  # doesn't even claim to be old enough

    if doc.get("template_id") != "fake_id":
        return True  # a real id_card/driver_license claiming to be old enough is trusted

    # Fake ID: a real detection roll, scaled by how implausible the age
    # gap actually is -- a 24-year-old passing as 21 barely raises an
    # eyebrow (low, near-baseline detection chance), a 15-year-old's
    # fake is obviously a stretch (detection climbs steeply, dominating
    # the roll well before the gap gets that large).
    real_age_gap = max(0, minimum_age - age)
    detection_chance = min(0.92, 0.15 + real_age_gap * 0.12)
    return random.random() > detection_chance
