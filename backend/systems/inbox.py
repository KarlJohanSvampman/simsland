# =========================================================
# SHARED INBOX
# One inbox shape for every message kind (call/text/email/voicemail),
# used by both characters (c["inbox"]) and businesses
# (world["businesses"][key]["inbox"]) -- see systems/business_support.py
# for the business-side background processing that drains these.
# =========================================================

MAX_INBOX_ENTRIES = 50


def get_character_inbox(c):
    return c.setdefault("inbox", [])


def get_business_state(world, company_key):
    return world.setdefault("businesses", {}).setdefault(company_key, {"inbox": []})


def get_business_inbox(world, company_key):
    return get_business_state(world, company_key).setdefault("inbox", [])


def add_message(inbox, kind, frm, to, body, tick, metadata=None):
    """Append a message and cap the inbox length. `kind` is what actually
    happened (call/text/email/voicemail), not the medium requested --
    e.g. a failed call attempt lands as kind="voicemail", not "call"."""
    entry = {
        "id":       f"msg_{tick}_{len(inbox)}",
        "kind":     kind,
        "from":     frm,
        "to":       to,
        "body":     body,
        "tick":     tick,
        "read":     False,
        "metadata": metadata or {},
    }
    inbox.append(entry)
    del inbox[:-MAX_INBOX_ENTRIES]
    return entry


def unread_count(inbox, kind=None):
    return sum(
        1 for m in inbox
        if not m.get("read") and (kind is None or m.get("kind") == kind)
    )
