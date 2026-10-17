def update_hierarchy(world):
    chars=list(world["characters"].values())
    if not chars: return
    # .get: a workplace NPC created earlier in this same tick is a bare dict with no
    # household_id key at all (schema defaults only fill it in on the NEXT load).
    chars.sort(key=lambda c: world["households"].get(c.get("household_id"),{}).get("wealth",0)); n=len(chars)
    for i,c in enumerate(chars):
        c.setdefault("status",{})["wealth_rank"]=i/max(1,n-1)
        c["status"]["influence"]=max(0,min(1,c["status"].get("influence",.5)+sum(c.get("influence_given",{}).values())*.0001))
    world["leaders"]=[c["id"] for c in sorted(chars,key=lambda c:c["status"].get("influence",0), reverse=True)[:2]]
