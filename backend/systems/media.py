import random, uuid
from data.public_figures import PUBLIC_FIGURES
def generate_news(world):
    media = world.get(
        "media",
        []
    )

    if not media:
        return

    outlet = random.choice(
        media
    )
    pf=random.choices(PUBLIC_FIGURES, weights=[p.get("importance",.5) for p in PUBLIC_FIGURES], k=1)[0]; tag=random.choice(pf.get("tags",["society"]))
    sentiment="negative" if outlet.get("bias")=="anti_tax" and "tax" in tag else "positive" if outlet.get("bias")=="pro_tax" and "tax" in tag else random.choice(["positive","negative","neutral"])
    world.setdefault("news",[]).append({"id":f"news_{uuid.uuid4().hex[:6]}","type":"news","headline":f"{pf['name']} addresses {tag}","summary":f"{outlet['name']} reports on {pf['role']} {pf['name']} and {tag}.","sentiment":sentiment,"intensity":pf.get("importance",.5),"tags":[tag],"related_entities":[pf["id"]],"source":outlet["id"],"tick":world["tick"]})
    world["news"]=world["news"][-50:]
def generate_biased_news(world, event=None): generate_news(world)
