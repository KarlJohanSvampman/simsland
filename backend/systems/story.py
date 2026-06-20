def update_story_arc(c):
    arc=c.setdefault("story_arc",[])
    for m in c.get("memories",[])[-2:]:
        text=m.get("text")
        if text and (not arc or arc[-1]!=text): arc.append(text)
    c["story_arc"]=arc[-20:]
