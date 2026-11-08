"""
social/migrate.py -- converting a save from before social/ (once per world; world["_social_version"]).

  world["arguments"] (+ c["argument_log"])   -> social issues, with their conversations, fights and history
  conversation archive entries' argument_id  -> issue_ids
  rel["agitation"]                            -> general frustration intensity (social/frustration.py)
  relationship values                         -> a stored standing (social/standing.py), seeded from the old formula
  grievances still weighing on someone        -> evidence on the issue between them, and frustration about it
  the old pipeline's unfinished conflicts      -> closed (they were dice rolls with nobody talking)
  world["rumors"] (old shape)                 -> rumours with transmissions (social/rumours.py)
  social contracts                            -> the design's fields (social/contracts.py)
"""

VERSION = 1

_ARG_CATEGORY = {"provocation": "disrespect", "unmet_expectation": "unmet_expectation", "lying_accusation": "dishonesty",
                 "clash_of_wants": "relationship_problem", "wrong_done": "unfair_treatment"}


def migrate(world):
    if world.get("_social_version", 0) >= VERSION:
        return False
    from social import issues as I, standing, frustration, contracts as K
    chars = world.get("characters") or {}

    # arguments -> issues
    arg_to_issue = {}
    for arg in list((world.get("arguments") or {}).values()):
        parties = [p for p in arg.get("parties") or [] if p in chars]
        if len(parties) < 2:
            continue
        issue = I.open_issue(world, arg.get("subject"), _ARG_CATEGORY.get(arg.get("type"), "other"), parties,
                             created_by=arg.get("initiator"), tick=arg.get("opened_tick"))
        issue["conversation_ids"] = list(arg.get("conversation_ids") or [])
        issue["fight_ids"] = list(arg.get("fight_ids") or [])
        issue["events"] = [{"tick": e.get("tick"), "what": e.get("what"), "detail": e.get("detail"),
                            "ref": e.get("conv_id") or e.get("fight_id")} for e in arg.get("events") or []] + issue["events"]
        if arg.get("status") == "resolved":
            issue["status"] = "resolved"
            issue["resolved_at"] = arg.get("resolved_tick")
            issue["resolution"] = arg.get("resolution")
        arg_to_issue[arg["id"]] = issue["id"]
        I.sync(world, issue)
    for entry in (world.get("conversation_archive") or {}).values():
        aid = entry.pop("argument_id", None)
        if aid in arg_to_issue:
            entry.setdefault("issue_ids", []).append(arg_to_issue[aid])
    world.pop("arguments", None)
    for c in chars.values():
        c.pop("argument_log", None)
        for e in c.get("conversation_log") or []:
            aid = e.pop("argument_id", None)
            if aid in arg_to_issue:
                e.setdefault("issue_ids", []).append(arg_to_issue[aid])

    # relationships: standing stored, agitation -> frustration
    for c in chars.values():
        for oid in list((c.get("relationships") or {}).keys()):
            if oid not in chars:
                continue
            standing.get(c, oid)
            frustration.value(c, oid, world)
            frustration._store(c, oid, world)

    # grievances -> issues (as evidence), and frustration about them
    for c in chars.values():
        for g in c.get("grievances") or []:
            other = g.get("caused_by")
            if other not in chars or other == c["id"] or (g.get("weight") or 0) < 1.0:
                continue
            try:
                from systems.fights import ISSUE_PHRASES
                subject = ISSUE_PHRASES.get(g.get("event_type")) or str(g.get("event_type")).replace("_", " ")
            except Exception:
                subject = str(g.get("event_type")).replace("_", " ")
            issue, _ = I.find_or_open(world, [c["id"], other], subject, I.category_for(g.get("event_type")),
                                      created_by=c["id"], affected=[c["id"]], tick=g.get("tick"))
            I.add_evidence(world, issue, "incident", subject, by=c["id"], ref=g.get("id"))
            f = frustration._store(c, other, world, issue["id"])
            f["score"] = max(f["score"], min(100.0, g["weight"] * 2))

    # the old pipeline's conflicts: none left running
    for conflict in (world.get("conflicts") or {}).values():
        if conflict.get("outcome") is None:
            conflict["outcome"] = "suppressed"
            conflict["tick_ended"] = world.get("tick", 0)

    # rumours: the old shape had a source, a subject, a text and believers
    rumors = world.get("rumors") or {}
    for rid, r in list(rumors.items()):
        if "subject_id" in r:
            continue
        new = {"id": rid, "subject_id": r.get("subject"), "claim": r.get("text") or "", "originating_event_id": None,
               "originator_id": r.get("source"), "information_status": "unverified", "original_context": "",
               "created_at": r.get("tick", 0), "polarity": r.get("polarity", 0), "last_activity": r.get("tick", 0),
               "transmissions": [], "told_to_subject": r.get("told_to_subject", False)}
        for b in r.get("believers") or []:
            if b in chars:
                new["transmissions"].append({"id": f"tx_{rid}_{b}", "rumour_id": rid, "sender_id": r.get("source"),
                                             "receiver_id": b, "timestamp": r.get("tick", 0),
                                             "claim_as_told": new["claim"], "perceived_credibility": 0.6,
                                             "perceived_intent": "gossip", "interpretation": "believes it",
                                             "confidence_after_transmission": 0.6, "conv_id": None})
                chars[b].setdefault("known_rumours", {})[rid] = {"confidence": 0.6, "heard_from": [r.get("source")],
                                                                 "interpretation": "believes it",
                                                                 "first_heard": r.get("tick", 0),
                                                                 "last_heard": r.get("tick", 0)}
        rumors[rid] = new

    for k in (world.get("social_contracts") or {}).values():
        K.normalize(k)

    world["_social_version"] = VERSION
    print(f"[social] converted the save: {len(arg_to_issue)} arguments -> issues, "
          f"{len(world.get('social_issues') or {})} issues in all")
    return True
