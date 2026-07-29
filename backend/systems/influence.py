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


# =========================================================
# EXPOSURE-DRIVEN RESOLUTION (trust-gated)
# =========================================================
# Periodic pass over exposure_ticks (brain/perception.py::perceive_people()
# increments these -- who a character is around the most, distinct from
# trust itself). Trust decides direction here, exposure decides
# magnitude/who: trusted (trust>40) exposure feeds positive belief/trait
# influence; distrusted (trust<-40) exposure instead breeds suspicion via
# worries.py. Neither fires in the mid-range -- exposure alone, without a
# trust signal, does nothing.

_MIN_EXPOSURE_TO_RESOLVE = 5
_TRUST_POSITIVE_GATE     = 40
_TRUST_NEGATIVE_GATE     = -40


def resolve_exposure_influence(world):
    from systems.peer_influence import record_positive_exposure
    from systems.worries import bump_suspicion

    chars = world.get("characters", {})
    for c in chars.values():
        for other_id, rel in c.get("relationships", {}).items():
            exposure = rel.get("exposure_ticks", 0)
            if exposure < _MIN_EXPOSURE_TO_RESOLVE:
                continue

            other = chars.get(other_id)
            if not other:
                continue

            trust  = rel.get("trust", 0)
            weight = min(1.0, exposure / 100.0)

            if trust > _TRUST_POSITIVE_GATE:
                record_influence(other, c, weight, world)
                for trait in set(other.get("traits", []) + other.get("personality_traits", [])):
                    record_positive_exposure(c, other, trait, world)
            elif trust < _TRUST_NEGATIVE_GATE:
                bump_suspicion(
                    c, other_id, 0.01 * weight, "prolonged_exposure",
                    f"You've been around {other.get('name', other_id)} a lot lately, "
                    f"and something about it doesn't sit right",
                    world,
                )

            # Halve, don't zero -- influence has memory but doesn't compound unboundedly.
            rel["exposure_ticks"] = exposure // 2
