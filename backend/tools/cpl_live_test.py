"""
tools/cpl_live_test.py -- CPL against the real model (docs/cpl_implementation_plan.md, after phase 5).

The determinism fixture world, everyone in a household standing together so they talk, CPL_MODE=on, and the real
think() calling Ollama (OLLAMA_BASE_URL / OLLAMA_MODEL, as in docker-compose.yml). Afterwards, what only the real model
can show:

    adherence     of the decisions made inside a CPL conversation, how many carried the turn lines (ANSWERS / ACT /
                  NEXT), and the mistakes made in them (answers to items not open, unknown words, ...)
    tracking      questions and requests opened, how they were settled, contracts made, claims and how they were taken
    lifecycle     how conversations ended, how long they ran, what the shadow tally says
    cost          turns by mode (A without a model call / B / C), compact turns, prompt sizes
    transcripts   a few conversations in full, with the record CPL kept of them

Run inside the backend container (needs Postgres, Redis and the model):
    python tools/cpl_live_test.py [ticks=600] [report.json]
    CPL_COMPACT_TURNS=on python tools/cpl_live_test.py ...      # the compact prompt for mode-B turns
"""

import json
import os
import sys
import time
import urllib.request
from collections import Counter

os.environ["CPL_MODE"] = "on"
os.environ["DET_POLICY"] = "real"
os.environ.setdefault("DET_SETUP", "together")
os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TICKS = int(sys.argv[1]) if len(sys.argv) > 1 else 600
OUT = sys.argv[2] if len(sys.argv) > 2 else "cpl_live_report.json"


def preflight():
    base = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.1:latest")
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=8) as r:
            names = [m.get("name") for m in json.load(r).get("models", [])]
    except Exception as exc:
        sys.exit(f"The model server at {base} can't be reached ({exc!r}). Set OLLAMA_BASE_URL to it.")
    if not any(n == model or n.split(":")[0] == model.split(":")[0] for n in names):
        sys.exit(f"{base} is up but has no {model} (it has: {names}). Pull it, or set OLLAMA_MODEL.")
    print(f"model: {model} at {base}")


preflight()

# ── count what the model wrote, and the prompt sizes, as decisions pass through ─────────────────────────────────────
import brain.llm_brain as LB

seen = {"decisions": 0, "in_cpl": 0, "with_lines": 0, "lines": Counter(), "prompt_chars": [], "compact_chars": [],
        "seconds": []}
_think = LB.think


def think(context, char_id=None, session=None, priority=None):
    t0 = time.monotonic()
    out = _think(context, char_id=char_id, session=session, priority=priority)
    seen["seconds"].append(time.monotonic() - t0)
    seen["decisions"] += 1
    if context.get("cpl"):
        seen["in_cpl"] += 1
        cpl_lines = ((out or {}).get("speech") or {}).get("cpl") or ""
        if cpl_lines:
            seen["with_lines"] += 1
            for ln in cpl_lines.splitlines():
                seen["lines"][ln.split(":", 1)[0]] += 1
        (seen["compact_chars"] if context.get("compact_turn") else seen["prompt_chars"]).append(
            len(context.get("compact_turn") or context.get("narrative") or ""))
    return out


LB.think = think

from tests import determinism  # noqa: E402
from cpl import metrics, record, shadow  # noqa: E402

started = time.monotonic()
w, errs, _ = determinism.run_sim(TICKS, start="2026-11-04T09:00:00")
took = time.monotonic() - started

convs = list((w.get("cpl_conversations") or {}).values())
reqs = list((w.get("cpl_requests") or {}).values())
questions = [q for c in convs for q in (c.get("questions") or {}).values()]
claims = [cl for c in convs for cl in (c.get("claims") or {}).values()]
errors = Counter(e for c in convs for t in c.get("turn_errors") or [] for e in t["errors"])


def _avg(v):
    return round(sum(v) / len(v), 1) if v else None


report = {
    "ticks": TICKS, "wall_seconds": round(took), "errors": dict(errs),
    "adherence": {"decisions": seen["decisions"], "in_a_cpl_conversation": seen["in_cpl"],
                  "with_turn_lines": seen["with_lines"],
                  "share_with_lines": round(seen["with_lines"] / seen["in_cpl"], 3) if seen["in_cpl"] else None,
                  "lines_written": dict(seen["lines"]), "mistakes": dict(errors.most_common(10))},
    "tracking": {"questions": dict(Counter(q["status"] for q in questions)),
                 "requests": dict(Counter(r["status"] for r in reqs)),
                 "contracts_made": sum(1 for r in reqs if r.get("contract_id")),
                 "claims": dict(Counter(cl["status"] for cl in claims))},
    "lifecycle": {"conversations_on_world": len(convs), "endings": metrics.report(w)["ended"],
                  "lines_per_conversation": sorted(c.get("lines", 0) for c in convs),
                  "shadow": {k: v for k, v in shadow.compare(w).items() if k not in ("pairs",)}},
    "cost": dict(metrics.report(w), avg_full_prompt_chars=_avg(seen["prompt_chars"]),
                 avg_compact_prompt_chars=_avg(seen["compact_chars"]),
                 avg_seconds_per_decision=_avg(seen["seconds"])),
    "transcripts": [{"id": c["id"], "state": c["state"], "reason": c.get("reason"), "purpose": c.get("purpose"),
                     "lines": [f"{m.get('sender_id')}: {m.get('content')}" for m in c.get("messages") or []],
                     "record": record.lines(w, c)}
                    for c in sorted(convs, key=lambda c: -c.get("lines", 0))[:5]],
}
with open(OUT, "w") as f:
    json.dump(report, f, indent=2, default=str)

a = report["adherence"]
print(f"\n{TICKS} ticks in {report['wall_seconds']} s, errors: {report['errors'] or 'none'}")
print(f"decisions: {a['decisions']}, in a CPL conversation: {a['in_a_cpl_conversation']}, with turn lines: "
      f"{a['with_turn_lines']} ({a['share_with_lines']})")
print(f"lines written: {a['lines_written']}")
print(f"mistakes: {a['mistakes'] or 'none'}")
print(f"tracking: {report['tracking']}")
print(f"endings: {report['lifecycle']['endings']}, lines per conversation: "
      f"{report['lifecycle']['lines_per_conversation']}")
print(f"cost: turns {report['cost']['turns']}, model calls {report['cost']['model_calls']}, "
      f"full prompt ~{report['cost']['avg_full_prompt_chars']} chars, compact ~{report['cost']['avg_compact_prompt_chars']}, "
      f"{report['cost']['avg_seconds_per_decision']} s per decision")
print(f"full report: {OUT}")
