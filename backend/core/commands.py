"""
core/commands.py -- mutations as commands run by the process that owns the world.

    @router.post("/household/set_name")
    @command("household.set_name")
    def set_name(sim_id: str, payload: dict):
        with world_lock():
            ...

Where the process IS the owner (SIM_ROLE all or core, the default), the decorator does nothing: the
function runs right there on the request thread, exactly as before. In a gateway process
(SIM_ROLE=api) the same function is replaced by a stub that sends its arguments to the owner over a
Redis stream and waits for the return value, so the body only ever executes next to the live world:

    api process  call()   -> cmd:req  -> core: serve() threads run the original function
                 <- result <- cmd:res <-

Contract for a command function: synchronous; every argument and the return value are plain JSON
(pydantic models are shipped by class name and rebuilt); an HTTPException raised in it is re-raised
in the caller with the same status. Commands carry a deadline, so a command the caller already gave up
on is dropped instead of run late, and a crashed core never replays one.
"""

import functools
import importlib
import inspect
import json
import os
import threading
import time
import traceback
import uuid

from core.work_queue import WorkQueue

ROLE = os.getenv("SIM_ROLE", "all").lower()           # all | core | api
COMMAND_TIMEOUT_SECONDS = 30.0
SERVE_THREADS = int(os.getenv("COMMAND_THREADS", "4"))

REGISTRY = {}                                         # command name -> the original function
queue = WorkQueue("cmd", claim_idle_ms=COMMAND_TIMEOUT_SECONDS * 1000 * 2)

_waiters = {}                                         # request id -> {"event", "result"}
_waiters_lock = threading.Lock()
_reader = None
_reader_lock = threading.Lock()


# ---------------------------------------------------------------------------
# argument / result encoding
# ---------------------------------------------------------------------------

def _encode(value):
    try:
        from pydantic import BaseModel
    except Exception:                                  # pragma: no cover
        BaseModel = ()
    if BaseModel and isinstance(value, BaseModel):
        cls = type(value)
        return {"__model__": f"{cls.__module__}:{cls.__qualname__}", "data": value.model_dump()}
    return value


def _decode(value):
    if isinstance(value, dict) and set(value) == {"__model__", "data"}:
        module, name = value["__model__"].split(":")
        return getattr(importlib.import_module(module), name)(**value["data"])
    return value


# ---------------------------------------------------------------------------
# the decorator
# ---------------------------------------------------------------------------

def command(name=None):
    def deco(fn):
        if inspect.iscoroutinefunction(fn):
            raise TypeError(f"{fn.__qualname__}: a command must be a plain (sync) function")
        cname = name or f"{fn.__module__}.{fn.__qualname__}"
        if cname in REGISTRY and REGISTRY[cname] is not fn:
            raise ValueError(f"duplicate command name {cname!r}")
        REGISTRY[cname] = fn
        if ROLE != "api":
            return fn
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def stub(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            return call(cname, {k: _encode(v) for k, v in bound.arguments.items()})
        stub.__command__ = cname
        return stub
    return deco


# ---------------------------------------------------------------------------
# gateway side
# ---------------------------------------------------------------------------

def _ensure_reader():
    global _reader
    with _reader_lock:
        if _reader is not None and _reader.is_alive():
            return
        _reader = queue.start_reader(_on_result, label="commands")


def _on_result(res):
    with _waiters_lock:
        waiter = _waiters.get(res.get("id"))
    if waiter:
        waiter["result"] = res
        waiter["event"].set()


def call(name, args, timeout=COMMAND_TIMEOUT_SECONDS):
    """Run command `name` on the owner and return its value (gateway side)."""
    from fastapi import HTTPException
    if queue.workers_alive() == 0:
        raise HTTPException(status_code=503, detail="the simulation core is not running")
    req_id = uuid.uuid4().hex
    waiter = {"event": threading.Event(), "result": None}
    _ensure_reader()                                   # listening before the request exists
    with _waiters_lock:
        _waiters[req_id] = waiter
    try:
        queue.enqueue({"id": req_id, "command": name, "args": args, "deadline": time.time() + timeout})
        if not waiter["event"].wait(timeout):
            raise HTTPException(status_code=504, detail=f"command {name} timed out")
    finally:
        with _waiters_lock:
            _waiters.pop(req_id, None)
    res = waiter["result"]
    if res.get("http"):
        raise HTTPException(status_code=res["http"][0], detail=res["http"][1])
    if res.get("error"):
        raise HTTPException(status_code=500, detail=f"command {name} failed: {res['error']}")
    return res.get("value")


# ---------------------------------------------------------------------------
# owner side
# ---------------------------------------------------------------------------

def execute(req):
    """Run one command request on this process -> result dict. Never raises."""
    from fastapi import HTTPException
    out = {"id": req.get("id")}
    fn = REGISTRY.get(req.get("command"))
    if fn is None:
        out["error"] = f"unknown command {req.get('command')!r}"
        return out
    try:
        value = fn(**{k: _decode(v) for k, v in (req.get("args") or {}).items()})
        json.dumps(value, default=str)
        out["value"] = json.loads(json.dumps(value, default=str))
    except HTTPException as exc:
        out["http"] = [exc.status_code, exc.detail]
    except Exception as exc:
        traceback.print_exc()
        out["error"] = repr(exc)
    return out


_runtime = None


def serve(threads=SERVE_THREADS):
    """Start answering commands (owner side). Idempotent."""
    global _runtime
    if _runtime is not None:
        return _runtime
    from workers.common import Runtime
    _runtime = Runtime("commands", queue, execute, threads, heartbeat_seconds=2.0)
    _runtime.start()
    return _runtime
