"""
core/cognition_queue.py

The wire for character decisions: a core.work_queue.WorkQueue named "cognition"
(streams cognition:req / cognition:res, heartbeat keys cognition:worker:<id>). See work_queue.py.
Module-level names are the queue's methods, so callers say `cognition_queue.enqueue(...)`.
"""

from core.work_queue import WorkQueue, new_worker_id  # noqa: F401

queue = WorkQueue("cognition")

workers_alive = queue.workers_alive
forget_alive_cache = queue.forget_alive_cache
enqueue = queue.enqueue
latest_result_id = queue.latest_result_id
read_results = queue.read_results
start_reader = queue.start_reader
ensure_group = queue.ensure_group
heartbeat = queue.heartbeat
goodbye = queue.goodbye
claim = queue.claim
complete = queue.complete
