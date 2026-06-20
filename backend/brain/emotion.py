EMOTION_TEMP={"calm":20,"warm":25,"playful":30,"curious":30,"awkward":40,"suspicious":45,"sad":45,"annoyed":55,"angry":70,"fearful":70,"furious":90,"smug":50}
def apply_emotion_inertia(c, llm_emotion=None):
    current=float(c.get("emotional_temperature",20))
    if llm_emotion:
        target=EMOTION_TEMP.get(llm_emotion,current); volatility=float(c.get("volatility",0.5))
        current=current*(1-0.25*volatility)+target*(0.25*volatility)
    current += max(0,float(c.get("stress",0))-50)*0.01
    c["emotional_temperature"]=max(0,min(100,current*0.995))
def update_emotion(c):
    t=float(c.get("emotional_temperature",20))
    c["emotion"]="furious" if t>=85 else "angry" if t>=70 else "annoyed" if t>=55 else "calm" if t<=25 else c.get("emotion","neutral")
    c["mood"]=c["emotion"]
def get_emotion_label(c): return c.get("emotion","calm")
