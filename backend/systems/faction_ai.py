def apply_faction_influence(world):
    for f in world.get("factions",{}).values():
        for cid in f.get("members",[]):
            c=world["characters"].get(cid)
            if not c: continue
            for agenda in f.get("agenda",[]):
                c.setdefault("beliefs",{}).setdefault(agenda,{"value":0,"certainty":0.1})
                c["beliefs"][agenda]["value"]=max(-1,min(1,c["beliefs"][agenda]["value"]+.002))
                c["beliefs"][agenda]["certainty"]=min(1,c["beliefs"][agenda]["certainty"]+.001)
