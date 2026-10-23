"""One deterministic simulation run in a fresh process (so no module state leaks between runs).

    python tests/run_det.py --ticks 1500 --start 2026-11-04T13:00:00 --out /tmp/a.json
Writes {"world": <normalised world>, "errors": {...}, "checkpoints": [[tick, state], ...], "stats": {...}}.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

ap = argparse.ArgumentParser()
ap.add_argument("--ticks", type=int, default=1500)
ap.add_argument("--start", default="2026-11-01T23:50:00")
ap.add_argument("--seed", type=int, default=1234)
ap.add_argument("--every", type=int, default=250)
ap.add_argument("--out", required=True)
args = ap.parse_args()

from tests.determinism import run_sim, norm


def snapshot_state(w):
    out = {}
    for cid, c in w["characters"].items():
        if c.get("is_workplace_npc"):
            continue
        out[cid] = {
            "expectations": c.get("expectations"),
            "intentions": sorted((i.get("type"), i.get("priority"), i.get("reason")) for i in c.get("active_intentions", [])),
        }
    return out


w, errs, cps = run_sim(args.ticks, start=args.start, seed=args.seed, checkpoint_every=args.every, checkpoint_fn=snapshot_state)
json.dump({"world": norm(w), "errors": dict(errs), "checkpoints": cps,
           "stats": {}},
          open(args.out, "w"), default=str)
