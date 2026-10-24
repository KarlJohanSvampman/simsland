"""
API gateway split: which routes may run on the gateway (tools/route_audit.py).

Run inside the backend container:   python tests/test_route_audit.py
(needs frontend/nginx.conf mounted at /frontend/nginx.conf, see docker-compose.yml)
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

os.environ["SIM_ROLE"] = "all"
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from tools import route_audit as ra

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ---- the real app ------------------------------------------------------------------------------------
import main

rows = ra.audit(main.app)
bad = [r for r in rows if r["problems"]]
for r in bad:
    print(f"   {r['path']} {r['methods']} ({r['endpoint']})")
    for p in r["problems"][:4]:
        print("      " + p)
check("no route reaches core-only state or mutates the world without being marked", not bad,
      f"{len(bad)} routes: " + ", ".join(r["path"] for r in bad[:5]))

gateway = [r for r in rows if r["gateway"]]
core_only = [r for r in rows if r["mark"] == "core_only"]
commands = [r for r in rows if r["mark"] == "command"]
print(f"   {len(rows)} routes: {len(gateway)} on the gateway, {len(commands)} commands, {len(core_only)} core-only")
check("a meaningful number of routes are on the gateway", len(gateway) >= 25, str(len(gateway)))
check("no core-only route is sent to the gateway", not [r for r in gateway if r["mark"] == "core_only"])
check("the websocket is on the gateway", any(r["path"] == "/ws" and r["gateway"] for r in rows))
for must_stay in ("/admin/cognition", "/admin/tick_profile", "/debug/prompt-log/{char_id}", "/api/llm/logs"):
    row = next((r for r in rows if r["path"] == must_stay), None)
    check(f"{must_stay} is core-only and not on the gateway", row and row["mark"] == "core_only" and not row["gateway"])

gw_commands = [r for r in commands if r["gateway"]]
check("there are mutations on the gateway, and they are all commands", len(gw_commands) >= 8)

# ---- nginx location matching ----------------------------------------------------------------------------
nginx = ra.Nginx(Path("/frontend/nginx.conf").read_text(encoding="utf-8"))
expect = {
    "/ws": True, "/api/state": True, "/api/household/list": True, "/api/household/abc/admin": True,
    "/api/overview/stocks": True, "/api/finances/c1": True, "/api/dependents/c1": True, "/api/events": True,
    "/api/conversation/c1": True, "/view": True, "/view/perception-range/c1": True, "/director/log": True,
    "/api/editor/world": False, "/api/editor/definitions": False, "/admin/state": False, "/admin/cognition": False,
    "/debug/prompt-log/c1": False, "/api/meshbank": False, "/resources/x.glb": False, "/api/prop/create": False,
    "/index.html": False,
}
wrong = {p: nginx.to_gateway(p) for p, want in expect.items() if bool(nginx.to_gateway(p)) != want}
check("nginx location matching agrees with the config", not wrong, str(wrong))

# ---- the analyzer itself, on synthetic code -------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
for d in ("core", "systems", "api"):
    (tmp / d).mkdir()
    (tmp / d / "__init__.py").write_text("")
(tmp / "core" / "tick_profile.py").write_text("def report():\n    return 1\n")
(tmp / "db.py").write_text("def world_lock():\n    pass\ndef save_world(a, b):\n    pass\ndef load_world(a):\n    return {}\n")
(tmp / "systems" / "helper.py").write_text(textwrap.dedent("""
    def deep():
        from core import tick_profile
        return tick_profile.report()
    def middle():
        return deep()
    def writer(sim):
        import db
        with db.world_lock():
            db.save_world(sim, {})
    def pure(x):
        return x + 1
    def loop_a():
        return loop_b()
    def loop_b():
        return loop_a()
"""))
(tmp / "api" / "routes.py").write_text(textwrap.dedent("""
    import core.tick_profile as tp
    from core import tick_profile
    from systems.helper import middle, writer, pure
    from systems import helper
    from db import load_world

    def alias_import():
        return tp.report()
    def from_import():
        return tick_profile.report()
    def through_chain():
        return middle()
    def through_module_attr():
        return helper.middle()
    def mutates():
        return writer("x")
    def clean():
        return pure(load_world("x"))
    def local_import():
        from core.tick_profile import report
        return report()
    def cycle():
        from systems.helper import loop_a
        return loop_a()
"""))
idx = ra.Index(tmp)
expect = {"alias_import": {"CORE-ONLY"}, "from_import": {"CORE-ONLY"}, "through_chain": {"CORE-ONLY"},
          "through_module_attr": {"CORE-ONLY"}, "mutates": {"MUTATION"}, "clean": set(), "local_import": {"CORE-ONLY"},
          "cycle": set()}
for fn, kinds in expect.items():
    got = {k for k, _ in idx.findings("api.routes", fn)}
    check(f"analyzer: {fn} -> {sorted(kinds) or 'nothing'}", got == kinds, str(got))
chain = idx.findings("api.routes", "through_chain")
check("analyzer reports the path", any("systems.helper.middle" in " ".join(c) and "systems.helper.deep" in " ".join(c) for c in chain.values()))

# ---- in a gateway process the marks are enforced -----------------------------------------------------------------
code = textwrap.dedent("""
    import json, inspect
    import main
    from fastapi import HTTPException
    from tools import route_audit as ra
    out = {"core_only": 0, "core_only_503": 0, "core_only_bad": [], "commands": 0, "commands_stubs": 0}
    for path, methods, ep in ra.routes(main.app):
        mark, fn = ra.endpoint_marks(ep)
        if mark == "core_only":
            out["core_only"] += 1
            try:
                ep(**{p: None for p in inspect.signature(ep).parameters})
                out["core_only_bad"].append(path)
            except HTTPException as exc:
                if exc.status_code == 503:
                    out["core_only_503"] += 1
                else:
                    out["core_only_bad"].append(path)
            except Exception as exc:
                out["core_only_bad"].append(path + " " + repr(exc)[:60])
        elif mark == "command":
            out["commands"] += 1
            out["commands_stubs"] += 1 if hasattr(ep, "__wrapped__") else 0
    print("RESULT" + json.dumps(out))
""")
res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd="/app", env=dict(os.environ, SIM_ROLE="api"))
line = next((l for l in res.stdout.splitlines() if l.startswith("RESULT")), None)
data = json.loads(line[6:]) if line else {"error": res.stderr[-400:]}
check("in a gateway every core-only route answers 503", data.get("core_only") == len(core_only) == data.get("core_only_503") and not data.get("core_only_bad"), str(data)[:400])
check("in a gateway every command is a stub", data.get("commands") == len(commands) == data.get("commands_stubs"), str(data)[:400])

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
