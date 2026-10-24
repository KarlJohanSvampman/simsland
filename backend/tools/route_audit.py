"""
tools/route_audit.py -- which routes may run on the API gateway?

A gateway process (SIM_ROLE=api, docs/distributed_architecture_plan.md) holds a read replica of the
world and sends every mutation to the core as a command. That only works for a route that

  * changes the world only through a @command (core/commands.py), and
  * reads no state that exists only inside the core process (cognition and tick statistics, prompt
    logs, the LLM gate, the middleware bridge heartbeat, sandbox worlds, ...).

This tool decides it statically. It indexes every module of the backend, follows what each route
endpoint references (names, attribute chains and calls, resolved through the imports of the module
or the function) through project code, and reports the first path from the route to

    a mutation primitive    db.world_lock / save_world / ...      (MUTATION)
    core-only state         the modules and functions in CORE_ONLY_STATE

A route is fine if it is a @command (it runs in the core, nothing to check), is marked @core_only
(served by the core; the gateway answers 503, nginx retries on the core), or reaches neither.
Also parses frontend/nginx.conf to learn which URL paths are sent to the gateway.

    python tools/route_audit.py            print the report, exit 1 on a violation

tests/test_route_audit.py runs it. When it fails for a new route: if the route really needs
core-only state add @core_only; if it mutates the world make it a @command; if the reference is
a false positive add it to ALLOWED with the reason.
"""

import ast
import fnmatch
import inspect
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"tests", "tools", "frontend", "__pycache__", "data", "backups", "node_modules"}

# (module, name pattern): state that exists only inside the simulation core process.
CORE_ONLY_STATE = [
    ("brain.cognition_scheduler", "*"),        # rolling think statistics, prompt-byte gauge
    ("brain.cognition_actor", "*"),            # in-flight decision requests
    ("brain.external_brain", "*"),             # the middleware bridge's heartbeat
    ("sim_loop", "*"),                         # the tick: pending-agent bookkeeping, job registry
    ("core.tick_profile", "*"),
    ("core.section_registry", "*"),
    ("core.tick_state", "*"),
    ("core.event_log", "*"),
    ("core.event_bus", "*"),                   # handler registry and statistics; handlers run where emit() runs
    ("core.scheduler", "*"),
    ("core.memory_guard", "*"),
    ("core.cognition_queue", "*"),
    ("llm.llm_gate", "*"),                     # the per-process concurrency gate and its queue
    ("llm.llm_client", "call_llm*"),           # a model call: the gateway has no Ollama configuration
    ("llm.llm_client", "*prompt_log*"),        # per-process prompt ring buffer
    ("llm.llm_client", "*stats*"),
    ("systems.bg_llm", "*"),                   # per-process mailbox of background results
    ("core.world_state", "stats"),
    ("core.world_state", "persist*"),
    ("core.world_state", "reset_for_tests"),
]

# (module, name pattern): ways to change the world.
MUTATION = [
    ("db", "world_lock"),
    ("db", "save_world"),
    ("db", "set_world_cache"),
    ("db", "refresh_static_world_cache"),
    ("db", "invalidate_static_world_cache"),
    ("core.world_state", "save"),
]

# route endpoint "module:function" -> {finding id: reason} accepted although the audit reports it.
ALLOWED = {}


# ---------------------------------------------------------------------------
# indexing
# ---------------------------------------------------------------------------

class Module:
    def __init__(self, name, tree):
        self.name = name
        self.tree = tree
        self.funcs = {}                   # "name" or "Class.method" -> ast node
        self.table = {}                   # module-level imports: local name -> (module, attr or None)


class Index:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.modules = {}
        for path in sorted(self.root.rglob("*.py")):
            rel = path.relative_to(self.root)
            if set(rel.parts[:-1]) & SKIP_DIRS or rel.name.startswith("tmp_"):
                continue
            name = ".".join(rel.with_suffix("").parts)
            if name.endswith(".__init__"):
                name = name[: -len(".__init__")]
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            mod = Module(name, tree)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    mod.funcs[node.name] = node
                elif isinstance(node, ast.ClassDef):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            mod.funcs[f"{node.name}.{sub.name}"] = sub
            self.modules[name] = mod
        for mod in self.modules.values():               # after all modules are known: `from pkg import module`
            mod.table = self._imports(mod.tree.body, mod.name)
        self._memo = {}

    def _imports(self, nodes, here):
        table = {}
        for top in nodes:
            for node in ast.walk(top):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.asname:
                            table[a.asname] = (a.name, None)
                        else:
                            table[a.name.split(".")[0]] = (a.name.split(".")[0], None)
                elif isinstance(node, ast.ImportFrom):
                    base = node.module or ""
                    if node.level:                         # relative import
                        parts = here.split(".")[: -node.level] if node.level else []
                        base = ".".join(parts + ([node.module] if node.module else []))
                    for a in node.names:
                        full = f"{base}.{a.name}" if base else a.name
                        table[a.asname or a.name] = (full, None) if full in self.modules else (base, a.name)
        return table

    # -- resolution ---------------------------------------------------------------------

    def _resolve(self, parts, table, mod):
        head = parts[0]
        if head in table:
            m, attr = table[head]
            if attr is None:                                 # a module alias
                cur, i = m, 1
                while i < len(parts) and f"{cur}.{parts[i]}" in self.modules:
                    cur = f"{cur}.{parts[i]}"
                    i += 1
                return (cur, parts[i] if i < len(parts) else None)
            return (m, attr)
        if head in mod.funcs:
            return (mod.name, head)
        for q in mod.funcs:                                  # Class.method written as Class.method
            if q.split(".")[0] == head and len(parts) > 1 and f"{head}.{parts[1]}" in mod.funcs:
                return (mod.name, f"{head}.{parts[1]}")
        return None

    def _refs(self, node, mod):
        """Every (module, name) a function body refers to."""
        local = dict(mod.table)
        local.update(self._imports([node], mod.name))
        out = []
        seen_attr_children = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute):
                parts, cur = [], sub
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                    parts.reverse()
                    r = self._resolve(parts, local, mod)
                    if r:
                        out.append(r)
                    seen_attr_children.add(id(sub.value))
            elif isinstance(sub, ast.Name) and id(sub) not in seen_attr_children:
                r = self._resolve([sub.id], local, mod)
                if r:
                    out.append(r)
        return out

    # -- analysis -------------------------------------------------------------------------

    @staticmethod
    def _match(rules, module, name):
        for m, pat in rules:
            if module == m and name and fnmatch.fnmatch(name, pat):
                return True
        return False

    def findings(self, module, name, _stack=None):
        """{finding: chain} for a project function: MUTATION and CORE-ONLY references reachable from it."""
        key = (module, name)
        if key in self._memo:
            return self._memo[key]
        _stack = _stack or set()
        if key in _stack:
            return {}
        mod = self.modules.get(module)
        node = mod.funcs.get(name) if mod else None
        if node is None:
            return {}
        _stack = _stack | {key}
        found = {}
        for r_mod, r_name in self._refs(node, mod):
            if r_name is None:
                continue
            label = f"{r_mod}.{r_name}"
            if self._match(MUTATION, r_mod, r_name):
                found.setdefault(("MUTATION", label), [f"{module}.{name}"])
            elif self._match(CORE_ONLY_STATE, r_mod, r_name):
                found.setdefault(("CORE-ONLY", label), [f"{module}.{name}"])
            elif r_mod in self.modules and (r_mod, r_name) != key:
                for f, chain in self.findings(r_mod, r_name, _stack).items():
                    found.setdefault(f, [f"{module}.{name}"] + chain)
        if not _stack - {key}:
            self._memo[key] = found                          # only cache complete (non-cyclic) results
        return found


# ---------------------------------------------------------------------------
# the app's routes and nginx
# ---------------------------------------------------------------------------

def routes(app):
    """[(path, methods, endpoint function)] for every route of a FastAPI app."""
    out = []
    for r in app.routes:
        ep = getattr(r, "endpoint", None)
        if ep is None:
            continue
        out.append((r.path, sorted(getattr(r, "methods", None) or ["WS"]), ep))
    return out


def endpoint_marks(fn):
    """('command'|'core_only'|None, original function) following functools.wraps chains."""
    mark = None
    cur = fn
    while cur is not None:
        if getattr(cur, "__command__", None):
            mark = "command"
        if getattr(cur, "__core_only__", None) and mark is None:
            mark = "core_only"
        cur = getattr(cur, "__wrapped__", None) if hasattr(cur, "__wrapped__") else None
    return mark, inspect.unwrap(fn)


class Nginx:
    """Which URL paths does frontend/nginx.conf send to the gateway? (the subset of nginx's location
    matching this config uses: `=` exact, regex `~` in file order, longest prefix.)"""

    def __init__(self, text):
        self.locations = []                                   # (kind, pattern, to_gateway)
        for m in re.finditer(r"location\s+(=\s+|~\*?\s+|\^~\s+|@)?(\S+)\s*\{(.*?)\n    \}", text, re.S):
            kind = (m.group(1) or "").strip()
            body = m.group(3)
            if kind == "@":
                continue
            self.locations.append((kind or "prefix", m.group(2), "$gateway" in body))

    def to_gateway(self, path):
        for kind, pat, gw in self.locations:
            if kind == "=" and path == pat:
                return gw
        for kind, pat, gw in self.locations:
            if kind == "~" and re.search(pat, path):
                return gw
        best = None
        for kind, pat, gw in self.locations:
            if kind in ("prefix", "^~") and path.startswith(pat) and (best is None or len(pat) > len(best[0])):
                best = (pat, gw)
        return best[1] if best else False


def sample_path(path):
    return re.sub(r"\{[^}]*\}", "x", path)


def audit(app, nginx_text=None, index=None):
    """-> list of row dicts: path, methods, endpoint, mark, gateway (bool), findings, problems."""
    index = index or Index()
    nginx = Nginx(nginx_text if nginx_text is not None else (ROOT.parent / "frontend" / "nginx.conf").read_text(encoding="utf-8"))
    rows = []
    for path, methods, ep in routes(app):
        mark, fn = endpoint_marks(ep)
        module, qual = fn.__module__, fn.__qualname__
        found = {} if mark else index.findings(module, qual)
        allowed = ALLOWED.get(f"{module}:{qual}", {})
        found = {f: c for f, c in found.items() if f"{f[0]}:{f[1]}" not in allowed}
        gw = bool(nginx.to_gateway(sample_path(path)))
        problems = []
        for (kind, label), chain in found.items():
            problems.append(f"{kind} {label}  via {' -> '.join(chain)}")
        if mark == "core_only" and gw:
            problems.append("marked @core_only but nginx sends it to the gateway")
        rows.append({"path": path, "methods": methods, "endpoint": f"{module}:{qual}", "mark": mark,
                     "gateway": gw, "findings": found, "problems": problems})
    return rows


def main():
    os.environ.setdefault("SIM_ROLE", "all")
    sys.path.insert(0, str(ROOT))
    import main as app_module
    rows = audit(app_module.app)
    bad = [r for r in rows if r["problems"]]
    width = max(len(r["path"]) for r in rows)
    for r in sorted(rows, key=lambda r: r["path"]):
        flag = "GATEWAY" if r["gateway"] else "core   "
        print(f"{flag} {r['mark'] or '-':9s} {r['path']:{width}s} {','.join(r['methods'])}")
        for p in r["problems"]:
            print(f"        !! {p}")
    print(f"\n{len(rows)} routes, {sum(1 for r in rows if r['gateway'])} on the gateway, "
          f"{sum(1 for r in rows if r['mark'] == 'command')} commands, "
          f"{sum(1 for r in rows if r['mark'] == 'core_only')} core-only, {len(bad)} with problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
