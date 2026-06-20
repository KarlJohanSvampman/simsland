def update_hierarchy(world):
    chars=list(world["characters"].values())
    if not chars: return
    chars.sort(key=lambda c: world["households"].get(c["household_id"],{}).get("wealth",0)); n=len(chars)
    for i,c in enumerate(chars):
        c.setdefault("status",{})["wealth_rank"]=i/max(1,n-1)
        c["status"]["influence"]=max(0,min(1,c["status"].get("influence",.5)+sum(c.get("influence_given",{}).values())*.0001))
    world["leaders"]=[c["id"] for c in sorted(chars,key=lambda c:c["status"].get("influence",0), reverse=True)[:2]]
