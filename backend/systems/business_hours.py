# =========================================================
# BUSINESS HOURS
# Whether a company_templates entry is currently open on a given
# channel -- "storefront" (opening_hours) or "phone" (phone_hours).
# Both fields share the same {"open": H, "close": H} daily-window shape
# already in use across company_templates (see definitions.json);
# absent/empty means that channel doesn't exist for this business (e.g.
# a presence:"online" business with no storefront).
# =========================================================

_CHANNEL_FIELD = {
    "storefront": "opening_hours",
    "phone":      "phone_hours",
}


def is_open(business, world, channel):
    field = _CHANNEL_FIELD.get(channel)
    if not field:
        return False

    window = business.get(field)
    if not window:
        return False

    hour = world.get("calendar", {}).get("hour", 0)
    open_h, close_h = window.get("open", 0), window.get("close", 24)

    # {open:0, close:24} (e.g. hospital) already reads as always-open here.
    if open_h <= close_h:
        return open_h <= hour < close_h
    return hour >= open_h or hour < close_h  # overnight window
