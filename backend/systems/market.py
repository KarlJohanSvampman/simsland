def update_market(world):
    for item in world.get("market",{}).values():
        item["price"] *= 1.03 if item["demand"]>item["supply"] else .985
        item["price"]=round(max(1,item["price"]),2); item["demand"]*=.98; item["supply"]*=.995
    world["environment"]["cost_of_living_index"]=max(.5,min(2,world["market"]["food"]["price"]/10))
def produce(world):
    world["market"]["food"]["supply"]+=4; world["market"]["medicine"]["supply"]+=1
def consume_households(world):
    for h in world.get("households",{}).values():
        h["wealth"]-=world["market"]["food"]["price"]*.1*len(h.get("members",[])); world["market"]["food"]["demand"]+=len(h.get("members",[]))*.5
