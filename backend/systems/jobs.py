import random, uuid
from data.professions import PROFESSIONS
from brain.memory import store_memory
def generate_job_listings(world):
    if world.get("job_listings"): return
    count=max(4,int(12*(1-world["environment"].get("unemployment_rate",.1))))
    for _ in range(count):
        p=random.choice(PROFESSIONS); wage=p["hourly_wage"]*world["environment"].get("average_salary_index",1)*random.uniform(.85,1.15)
        world["job_listings"].append({"id":f"job_{uuid.uuid4().hex[:6]}","profession":p["id"],"title":p["title"],"degree_required":p["degree_required"],"hourly_wage":round(wage,2),"open":True,"applicants":[]})
def maybe_fire(c, world):
    if c.get("employed") and random.random()<0.001+world["environment"].get("unemployment_rate",.1)*0.002:
        c["employed"]=False; c["job_searching"]=True; c["job_id"]=None
        store_memory(c,"Got laid off from work.",.85,["job","layoff","stress"],"job",world["tick"])
def apply_for_job(c, world):
    if c.get("employed") or c.get("interview"): return
    generate_job_listings(world)
    eligible=[j for j in world["job_listings"] if j.get("open") and (not j.get("degree_required") or j.get("degree_required")==c.get("degree"))]
    if not eligible: return
    job=max(eligible,key=lambda j:j["hourly_wage"])
    job.setdefault("applicants",[]).append(c["id"]); c["interview"]={"job_id":job["id"],"tick":world["tick"]+random.randint(10,30)}
    store_memory(c,f"Applied for {job['title']} and got an interview.",.55,["job","interview"],"job",world["tick"])
def process_interview(c, world):
    iv=c.get("interview")
    if not iv or world["tick"]<iv["tick"]: return
    job=next((j for j in world["job_listings"] if j["id"]==iv["job_id"]),None)
    if not job or not job.get("open"): c["interview"]=None; return
    success=random.random() < (0.45+c.get("ses",.5)*.25+world["environment"].get("education_quality",.7)*.15-world["environment"].get("unemployment_rate",.1)*.2)
    if success:
        c["employed"]=True; c["job_searching"]=False; c["job_id"]=job["id"]; c["profession"]=job["profession"]; c["hourly_wage"]=job["hourly_wage"]; job["open"]=False
        store_memory(c,f"Got hired as {job['title']}.",.8,["job","success"],"job",world["tick"])
    else: store_memory(c,f"Failed the interview for {job['title']}.",.7,["job","rejection","stress"],"job",world["tick"])
    c["interview"]=None
