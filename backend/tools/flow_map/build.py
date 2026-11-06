import json, html, re, sys
D = json.load(open(sys.argv[1]))
jobs = D["jobs"]; subs = D["subscribers"]; at = D["emitted_at"]
E = lambda s: html.escape(str(s))
def nid(s): return re.sub(r"[^A-Za-z0-9]", "_", s)

def dur(sec):
    sec = int(sec)
    if sec % 3600 == 0: return f"{sec//3600} h"
    if sec % 60 == 0: return f"{sec//60} min"
    return f"{sec} s"

# ---- event graph (mermaid) ----
ev_jobs = [j for j in jobs if j["kind"] == "event"]
lines = ["flowchart LR"]
lines.append("classDef ev fill:#e9eef8,stroke:#3b5b9a,color:#0f1d33")
lines.append("classDef evnew fill:#fff3d6,stroke:#b07a00,color:#2b1d00")
lines.append("classDef job fill:#e6f4ec,stroke:#2e7d4f,color:#0d2a19")
lines.append("classDef out fill:#f3e9f7,stroke:#7a3f99,color:#2a1036")
events = []
for j in ev_jobs:
    for e in j["on"]:
        if e not in events: events.append(e)
for e in events:
    new = "NEW" in at.get(e, "")
    lines.append(f'  E_{nid(e)}(["{e}"]):::{"evnew" if new else "ev"}')
for j in ev_jobs:
    lab = j["name"] + (f"<br/><small>settle {dur(j['settle'])}</small>" if j.get("settle") else "")
    lines.append(f'  J_{nid(j["name"])}["{lab}"]:::job')
    for e in j["on"]:
        lines.append(f'  E_{nid(e)} --> J_{nid(j["name"])}')
outs = set()
for j in ev_jobs:
    for e in j["emits"]:
        if e not in outs:
            outs.add(e); lines.append(f'  O_{nid(e)}(["{e} · {len(subs.get(e, []))} listeners"]):::out')
        lines.append(f'  J_{nid(j["name"])} -.-> O_{nid(e)}')
EVENT_GRAPH = "\n".join(lines)

# ---- tables ----
def emits_cell(j):
    if not j["emits"]: return '<span class="muted">—</span>'
    return " ".join(f'<code class="chip" title="{len(subs.get(e, []))} listeners">{E(e)}</code>' for e in j["emits"])
def fn_cell(j):
    return "<br>".join(f'<code>{E(f["fn"])}</code> <span class="muted">{E(f["file"])}</span>' for f in j["functions"][:6]) + \
           (f'<br><span class="muted">+{len(j["functions"])-6} more</span>' if len(j["functions"]) > 6 else "")

clock = sorted([j for j in jobs if j["kind"] == "clock"], key=lambda j: (j["daily"] is None, j["daily"] or 0, j["hourly"] or 0))
def when(j):
    if j.get("daily") is not None:
        s = j["daily"]; return f'daily {s//3600:02d}:{(s%3600)//60:02d}' + (f':{s%60:02d}' if s % 60 else "")
    return f'hourly at :{(j["hourly"] or 0)//60:02d}' + (f':{(j["hourly"] or 0)%60:02d}' if (j["hourly"] or 0) % 60 else "")
clock_rows = "".join(f'<tr><td class="nm">{E(j["name"])}</td><td class="num">{when(j)}</td><td>{E(j["why"])}</td><td>{emits_cell(j)}</td><td class="fns">{fn_cell(j)}</td></tr>' for j in clock)

procs = sorted([j for j in jobs if j["kind"] == "process"], key=lambda j: (j["every"], j["name"]))
import math
maxlog = math.log10(3600)
def bar(sec):
    w = max(4, 100 * math.log10(max(1, sec)) / maxlog)
    return f'<span class="bar" style="--w:{w:.0f}%"></span>'
proc_rows = "".join(f'<tr><td class="nm">{E(j["name"])}</td><td class="num">{dur(j["every"])}</td><td class="barcell">{bar(j["every"])}</td><td>{E(j["why"])}</td><td>{emits_cell(j)}</td><td class="fns">{fn_cell(j)}</td></tr>' for j in procs)
ev_rows = "".join(f'<tr><td class="nm">{E(j["name"])}</td><td>{" ".join(f"<code class=chip>{E(e)}</code>" for e in j["on"])}' + (f'<div class="muted">settles {dur(j["settle"])}</div>' if j.get("settle") else "") + f'</td><td>{E(j["why"])}</td><td>{emits_cell(j)}</td><td class="fns">{fn_cell(j)}</td></tr>' for j in ev_jobs)
src_rows = "".join(f'<tr><td><code>{E(e)}</code></td><td>{"<span class=pill-new>new</span>" if "NEW" in w else "<span class=pill-old>exists</span>"}</td><td>{E(w.split(":",1)[1].strip() if ":" in w else w)}</td><td class="num">{len(subs.get(e, []))}</td></tr>' for e, w in at.items())

n_ev, n_cl, n_pr = len(ev_jobs), len(clock), len(procs)
counts = dict(events=n_ev, clocks=n_cl, procs=n_pr, total=len(jobs))
tpl = open(sys.argv[2]).read()
out = (tpl.replace("@@EVENT_GRAPH@@", EVENT_GRAPH).replace("@@EV_ROWS@@", ev_rows).replace("@@CLOCK_ROWS@@", clock_rows)
          .replace("@@PROC_ROWS@@", proc_rows).replace("@@SRC_ROWS@@", src_rows))
for k, v in counts.items(): out = out.replace(f"@@{k.upper()}@@", str(v))
open(sys.argv[3], "w").write(out)
print("written", len(out))
