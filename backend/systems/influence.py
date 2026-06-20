from brain.beliefs import update_belief
def record_influence(source,target,amount,world):
    source.setdefault("influence_given",{})[target["id"]]=source.setdefault("influence_given",{}).get(target["id"],0)+amount
    target.setdefault("influence_received",{})[source["id"]]=target.setdefault("influence_received",{}).get(source["id"],0)+amount
    world.setdefault("influence_graph",{}).setdefault(source["id"],{})[target["id"]]=world.setdefault("influence_graph",{}).setdefault(source["id"],{}).get(target["id"],0)+amount
def apply_public_figure_influence(world):
    for news in world.get("news",[])[-3:]:
        for pfid in news.get("related_entities",[]):
            pf=next((p for p in world.get("public_figures",[]) if p["id"]==pfid), None)
            if not pf: continue
            for c in world["characters"].values():
                for tag in pf.get("tags",[])[:2]: update_belief(c,tag,news.get("sentiment","neutral"),news.get("intensity",.3)*pf.get("influence_power",.5),world["tick"])
def apply_social_influence(world):
    for c in world["characters"].values():
        for tid,weight in c.get("influence_given",{}).items():
            if tid in world["characters"]:
                target=world["characters"][tid]
                for topic,b in c.get("beliefs",{}).items(): update_belief(target,topic,"positive" if b.get("value",0)>0 else "negative",min(.3,abs(b.get("value",0))*weight*.05),world["tick"])
