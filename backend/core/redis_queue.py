import redis
import json
import os

REDIS_HOST = os.getenv("REDIS_HOST", "redis")

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

QUEUE_NAME = "sim_jobs"


def enqueue(job: dict):
    r.lpush(QUEUE_NAME, json.dumps(job))


def dequeue():
    _, job = r.brpop(QUEUE_NAME)
    return json.loads(job)

def dequeue_batch(batch_size=10):
    jobs = []

    for _ in range(batch_size):
        job = r.rpop(QUEUE_NAME)  # non-blocking
        if not job:
            break
        jobs.append(json.loads(job))

    return jobs