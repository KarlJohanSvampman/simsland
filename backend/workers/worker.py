import asyncio

from core.redis_queue import (
    dequeue_batch
)

from db import (
    load_character,
    save_character_safe,
    load_world
)

from brain.agent_loop import (
    update_agent
)


MAX_BATCH = 10
MAX_CONCURRENCY = 5

sem = asyncio.Semaphore(
    MAX_CONCURRENCY
)


# =========================================================
# PROCESS AGENT
# =========================================================

async def process_agent(

    c,

    world
):

    # =====================================
    # SKIP INVALID
    # =====================================

    if not c:
        return

    if c.get("off_grid"):
        return

    legal = c.get(
        "legal",
        {}
    )

    if legal.get(
        "status"
    ) == "jailed":

        return

    # =====================================
    # MAIN UPDATE
    # =====================================

    update_agent(

        c,

        world
    )


# =========================================================
# PROCESS JOB
# =========================================================

async def process_job(job):

    sim_id = job.get(
        "simulation_id",
        "default"
    )

    cid = job.get(
        "character_id"
    )

    if not cid:
        return

    # =====================================
    # LOAD CHARACTER
    # =====================================

    c = load_character(
        cid,
        sim_id
    )

    if not c:
        return

    # =====================================
    # LOAD WORLD
    # =====================================

    world = load_world(
        sim_id
    )

    if not world:
        return

    # =====================================
    # PROCESS
    # =====================================

    await process_agent(

        c,

        world
    )

    # =====================================
    # SAVE
    # =====================================

    save_character_safe(

        c,

        sim_id
    )


# =========================================================
# WRAPPER
# =========================================================

async def process_agent_job(job):

    async with sem:

        try:

            await process_job(job)

        except Exception as e:

            print(
                "\n[WORKER ERROR]",
                e,
                "\n"
            )


# =========================================================
# WORKER LOOP
# =========================================================

async def worker_loop():

    print(
        "[WORKER] batching enabled"
    )

    while True:

        jobs = dequeue_batch(
            MAX_BATCH
        )

        if not jobs:

            await asyncio.sleep(
                0.05
            )

            continue

        tasks = [

            process_agent_job(job)

            for job in jobs
        ]

        await asyncio.gather(

            *tasks,

            return_exceptions=True
        )


# =========================================================
# ENTRYPOINT
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        worker_loop()
    )