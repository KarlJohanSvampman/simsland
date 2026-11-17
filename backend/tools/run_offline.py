"""
tools/run_offline.py -- run the whole simulation server without a model server (no Ollama).

Character decisions come from the stand-in model of the test harness (tests/determinism.py::_varied_think: uses what
is in reach, walks to things, talks to whoever is near, with a handful of canned lines), and background model work
(theories, summaries, ...) is skipped. Everything else is the real server: the tick, the API and the websocket, Postgres
and Redis. Good for watching the simulation run, the frontend, and anything that doesn't depend on what the model says.

    python tools/run_offline.py [--port 8000] [--seed path/to/world.json] [--policy varied|social|wait]

--seed loads that world into the database first, but only when the database has no world yet (it never overwrites one).
DATABASE_URL and REDIS_HOST as for the backend (defaults: postgres:postgres@localhost/sim, localhost).
"""

import argparse
import json
import os
import random
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8000)
ap.add_argument("--host", default="0.0.0.0")
ap.add_argument("--seed", help="a world JSON to start from when the database has none")
ap.add_argument("--policy", default="varied", choices=("varied", "social", "wait"))
args = ap.parse_args()

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sim")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("SIM_ROLE", "all")
os.environ["COGNITION_MODE"] = "local"            # decisions in this process: there are no cognition workers
os.environ["BG_LLM_MODE"] = "local"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"   # nothing listens there: anything that still calls it fails fast
os.environ["DET_POLICY"] = args.policy
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import brain.llm_brain as lb  # noqa: E402
from tests import determinism  # noqa: E402

_rng = random.Random()


def think(context, char_id=None, session=None, priority=None):
    if args.policy == "wait":
        return {"thought": "ok", "action": {"type": "wait", "reason": "offline"}}
    return determinism._varied_think(context, char_id=char_id, session=session, priority=priority)


determinism._think_calls = iter(_rng.random, None)   # the harness's stand-in, unseeded: a server run need not repeat
lb.think = think
import brain.agent_loop as _al  # noqa: E402
_al.think = think
from systems import bg_llm  # noqa: E402
bg_llm.submit = lambda key, fn, *a: (bg_llm._done.__setitem__(key, None), True)[1]   # background model work: skipped

if args.seed:
    import db
    db.generate_initial_world = lambda: json.load(open(args.seed, encoding="utf-8"))

import uvicorn  # noqa: E402
import main  # noqa: E402

print(f"offline simulation server (stand-in model: {args.policy}) on http://{args.host}:{args.port}")
uvicorn.run(main.app, host=args.host, port=args.port, log_level="warning")
