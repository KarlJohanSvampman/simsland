import asyncio

from core.redis_queue import dequeue_batch
from db import load_character, save_character_safe, load_world

# 🧠 Brain pipeline
from brain.perception import perceive
from brain.memory import recall_relevant, decay_memories
from brain.monologue import think
from brain.emotion import update_emotion
from brain.agent_loop import select_goal
from brain.agent_loop import generate_plan
from brain.decision_engine import decide_action
from brain.executor import execute
from systems.props import get_prop_category
from db import update_world_tick


MAX_BATCH = 10
MAX_CONCURRENCY = 5

sem = asyncio.Semaphore(MAX_CONCURRENCY)


# =========================
# AGENT PIPELINE
# =========================
async def process_agent(c, world):

    if c.get("off_grid") or c.get("legal", {}).get("status") == "jailed":
        return

    # 🔥 MEMORY DECAY
    decay_memories(c)

    # perception
    perception = perceive(c, world)

    query = f"""
    emotion:{c.get('emotion')}
    goal:{c.get('goal')}
    nearby:{[
    get_prop_category(world, p)
    for p in perception.get("props", [])
]}
    """

    # 🔥 RELEVANT MEMORY
    memories = recall_relevant(c, query, 6)

    # thinking
    c["internal_thought"] = await think(c, perception, memories)

    # emotion
    update_emotion(c)

    # goal
    goal = select_goal(c, world)

    # planning
    if goal and not c.get("plan"):
        c["plan"] = await generate_plan(c, goal, world)

    # decision
    decision = await decide_action(c, world, perception, memories)

    # execute
    execute(c, decision, world)


# =========================
# JOB PROCESSING
# =========================
async def process_job(job):

    sim_id = job.get("simulation_id", "default")
    cid = job["character_id"]

    c = load_character(cid, sim_id)
    if not c:
        return

    world = load_world(sim_id)

    await process_agent(c, world)

    save_character_safe(c, sim_id)


# =========================
# WRAPPER (missing before)
# =========================
async def process_agent_job(job):
    async with sem:
        await process_job(job)


# =========================
# WORKER LOOP
# =========================
async def worker_loop():
    print("[WORKER] batching enabled")

    while True:
        jobs = dequeue_batch(MAX_BATCH)

        if not jobs:
            await asyncio.sleep(0.05)
            continue

        tasks = [process_agent_job(job) for job in jobs]

        await asyncio.gather(*tasks, return_exceptions=True)


# =========================
# ENTRYPOINT
# =========================
if __name__ == "__main__":
    asyncio.run(worker_loop())