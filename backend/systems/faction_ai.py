"""
systems/faction_ai.py — faction lifecycle and influence engine

world["factions"] = {
    "fac_abc": {
        "id":          "fac_abc",
        "template_id": "street_gang",
        "name":        "The Westside Boys",
        "type":        "criminal",
        "members":     ["char_1", "char_2"],
        "leaders":     ["char_1"],
        "agenda":      ["territory_control", "drug_trade"],
        "territory":   ["n1"],               # neighborhood ids
        "resources":   {"money": 5000, "influence": 0.3, "manpower": 8},
        "rival_faction_ids":  [],
        "allied_faction_ids": [],
        "reputation": {
            "public":        0.2,
            "among_rivals":  0.5,
            "among_allies":  0.7,
            "notoriety":     0.4,
            "last_updated":  0,
        },
        "public_known": True,
        "legal_status": "criminal",
        "founded_tick": 0,
        "active":       True,
    }
}

Each member also gets:
    c["faction_memberships"] = [{"faction_id": ..., "role": ..., "joined_tick": ...}]
"""

import random
import uuid


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def ensure_faction_defaults(faction):
    faction.setdefault("members",             [])
    faction.setdefault("leaders",             [])
    faction.setdefault("agenda",              [])
    faction.setdefault("territory",           [])
    faction.setdefault("resources",           {"money": 0, "influence": 0.3, "manpower": 0})
    faction.setdefault("rival_faction_ids",   [])
    faction.setdefault("allied_faction_ids",  [])
    faction.setdefault("public_known",        True)
    faction.setdefault("legal_status",        "legal")
    faction.setdefault("active",              True)
    faction.setdefault("founded_tick",        0)
    faction.setdefault("reputation", {
        "public":        0.5,
        "among_rivals":  0.3,
        "among_allies":  0.8,
        "notoriety":     0.0,
        "last_updated":  0,
    })
    return faction


def ensure_member_faction_field(c):
    c.setdefault("faction_memberships", [])


# ---------------------------------------------------------------------------
# Spawn a faction from a template
# ---------------------------------------------------------------------------

def spawn_faction(template_id, defs, world, name=None, neighborhood_id=None):
    """
    Create a live faction instance from a template and insert it into world.
    Returns the faction dict.
    """
    tmpl = defs.get("faction_templates", {}).get(template_id, {})
    fid  = f"fac_{uuid.uuid4().hex[:8]}"

    rep_defaults = tmpl.get("initial_reputation", {
        "public": 0.5, "among_rivals": 0.3, "among_allies": 0.8, "notoriety": 0.0
    })

    faction = {
        "id":               fid,
        "template_id":      template_id,
        "name":             name or f"{tmpl.get('name','Faction')} #{fid[-4:]}",
        "type":             tmpl.get("type", "other"),
        "members":          [],
        "leaders":          [],
        "agenda":           list(tmpl.get("typical_agenda", [])),
        "territory":        [neighborhood_id] if neighborhood_id else [],
        "resources":        {"money": 0, "influence": 0.3, "manpower": 0},
        "rival_faction_ids":  [],
        "allied_faction_ids": [],
        "reputation":       dict(rep_defaults) | {"last_updated": world.get("tick", 0)},
        "public_known":     tmpl.get("public_known", True),
        "legal_status":     tmpl.get("legal_status", "legal"),
        "founded_tick":     world.get("tick", 0),
        "active":           True,
    }

    world.setdefault("factions", {})[fid] = faction
    return faction


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

def join_faction(c, faction, role="member", world=None):
    """Add a character to a faction."""
    ensure_member_faction_field(c)
    cid = c["id"]
    fid = faction["id"]

    # Don't double-add
    for m in c["faction_memberships"]:
        if m["faction_id"] == fid:
            return

    faction["members"].append(cid)
    faction["resources"]["manpower"] = len(faction["members"])
    c["faction_memberships"].append({
        "faction_id":  fid,
        "role":        role,
        "joined_tick": world.get("tick", 0) if world else 0,
    })


def leave_faction(c, faction_id, world=None):
    """Remove a character from a faction."""
    ensure_member_faction_field(c)
    c["faction_memberships"] = [
        m for m in c["faction_memberships"] if m["faction_id"] != faction_id
    ]
    fac = (world or {}).get("factions", {}).get(faction_id)
    if fac and c["id"] in fac.get("members", []):
        fac["members"].remove(c["id"])
        fac["resources"]["manpower"] = len(fac["members"])


# ---------------------------------------------------------------------------
# Belief influence
# ---------------------------------------------------------------------------

def apply_faction_influence(world):
    """
    Nudge member beliefs toward faction agenda each slow tick.
    Also decays rival-faction relationships.
    """
    factions = world.get("factions", {})
    chars    = world.get("characters", {})

    for fac in factions.values():
        if not fac.get("active"):
            continue
        for cid in fac.get("members", []):
            c = chars.get(cid)
            if not c:
                continue
            for agenda_item in fac.get("agenda", []):
                beliefs = c.setdefault("beliefs", {})
                b = beliefs.setdefault(agenda_item, {"value": 0.0, "certainty": 0.1})
                b["value"]     = max(-1, min(1, b["value"]     + 0.002))
                b["certainty"] = min(1,      b["certainty"]    + 0.001)

        # Tick reputation drift toward faction defaults
        rep = fac.get("reputation", {})
        if rep:
            from systems.reputation import _regress
            for key in ("public", "among_rivals", "among_allies"):
                if key in rep:
                    rep[key] = _regress(rep[key], random.uniform(-0.001, 0.001))


# ---------------------------------------------------------------------------
# Rival tension
# ---------------------------------------------------------------------------

def process_rival_tensions(world):
    """
    When two rival factions share territory, escalate tension.
    Can trigger conflict events or reputation hits.
    """
    factions = list(world.get("factions", {}).values())
    for i, f1 in enumerate(factions):
        if not f1.get("active"):
            continue
        for f2 in factions[i+1:]:
            if not f2.get("active"):
                continue
            shared = set(f1.get("territory",[])) & set(f2.get("territory",[]))
            if not shared:
                continue
            are_rivals = (
                f2["id"] in f1.get("rival_faction_ids", []) or
                f1["template_id"] in (
                    (world.get("_defs_cache",{}) or {})
                    .get("faction_templates",{})
                    .get(f2.get("template_id",""),{})
                    .get("rival_types", [])
                )
            )
            if are_rivals and random.random() < 0.01:
                # Small notoriety bump from territory friction
                f1["reputation"]["notoriety"] = min(1, f1["reputation"].get("notoriety",0) + 0.01)
                f2["reputation"]["notoriety"] = min(1, f2["reputation"].get("notoriety",0) + 0.01)


# ---------------------------------------------------------------------------
# Auto-seed factions from criminal company templates
# ---------------------------------------------------------------------------

def seed_factions_from_companies(world, defs):
    """
    Called at world-gen. For each criminal or adult-industry company template
    that has a corresponding faction_template type, spawn one faction instance.
    """
    company_to_faction = {
        "criminal_gang":  "street_gang",
        "crime_family":   "crime_family",
    }
    companies = defs.get("company_templates", {})
    for ckey, ctmpl in companies.items():
        fac_type = company_to_faction.get(ckey)
        if not fac_type:
            continue
        # Only spawn once per company key
        already = any(
            f.get("template_id") == fac_type and f.get("name","").startswith(ctmpl.get("name",""))
            for f in world.get("factions", {}).values()
        )
        if not already:
            spawn_faction(fac_type, defs, world, name=ctmpl.get("name"))


# ---------------------------------------------------------------------------
# Context helper
# ---------------------------------------------------------------------------

def get_faction_context(c, world):
    """Compact faction membership summary for LLM context."""
    ensure_member_faction_field(c)
    factions = world.get("factions", {})
    out = []
    for mem in c.get("faction_memberships", []):
        fac = factions.get(mem["faction_id"])
        if not fac:
            continue
        out.append({
            "name":         fac.get("name"),
            "type":         fac.get("type"),
            "role":         mem.get("role"),
            "agenda":       fac.get("agenda", [])[:3],
            "legal_status": fac.get("legal_status"),
        })
    return out
