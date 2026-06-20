IDEOLOGY_AXES={"economic":["taxes","economy","cost_of_living","welfare"],"security":["crime","police","safety"],"social":["immigration","homelessness"],"institutional":["justice","government","media"]}
def update_belief(c, topic, sentiment, intensity, tick=0):
    b=c.setdefault("beliefs",{}).setdefault(topic,{"value":0.0,"certainty":0.1,"last_updated":tick})
    delta=0.2*float(intensity)
    delta=-abs(delta) if sentiment in ["negative","anti"] else abs(delta) if sentiment in ["positive","pro"] else delta*0.2
    resistance=1-float(b.get("certainty",0.1)); old=b["value"]
    b["value"]=max(-1,min(1,old+delta*resistance))
    b["certainty"]=min(1,b.get("certainty",0.1)+0.04*abs(intensity)) if (old>=0 and delta>=0) or (old<=0 and delta<=0) else max(0,b.get("certainty",0.1)-0.03*abs(intensity))
    b["last_updated"]=tick
def polarization_drift(c):
    for b in c.get("beliefs",{}).values():
        v=b.get("value",0); cert=b.get("certainty",0)
        if abs(v)>0.2: b["value"]=max(-1,min(1,v+(0.005*cert if v>0 else -0.005*cert)))
def compute_alignment(c):
    axes={}
    for axis,topics in IDEOLOGY_AXES.items():
        vals=[c.get("beliefs",{}).get(t,{}).get("value") for t in topics if t in c.get("beliefs",{})]
        axes[axis]=sum(vals)/len(vals) if vals else 0
    c["political_alignment"]=axes; return axes
def belief_alignment(a,b):
    aa=a.get("political_alignment",{}) or compute_alignment(a); bb=b.get("political_alignment",{}) or compute_alignment(b)
    keys=set(aa)|set(bb)
    return 0.5 if not keys else max(0,1-(sum(abs(aa.get(k,0)-bb.get(k,0)) for k in keys)/len(keys)/2))
