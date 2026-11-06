// Behaviour definitions admin (frontend/behaviour.html): drives, intentions, plans, requirements and variables
// (simulations/<sim>/behaviour.json through backend/api/behaviour.py), and a flow editor for one plan at a time.
//
// A plan is a graph: nodes (gate, decision, step, action, wait, plan, end) wired output -> node, plus named entry
// points that may carry variables. The editor draws each node's NAMED OUTPUTS as ports (a gate's yes / no, a step's
// done / failed, a decision's own options); a wire can set variables as it passes ({"set": {...}}) and a sidetrack wire
// can name the entry point it goes into. Every change is checked on the server (brain/plans/checker.py) as you go.

const API = "/admin/behaviour";
const KIND_LABEL = { drives: "drive", intentions: "intention", plans: "plan", requirements: "requirement", variables: "variable" };
const NODE_KINDS = {
  entry: { title: "Entry point", hint: "where the plan starts; can carry variables", color: "#3fb950" },
  gate: { title: "Gate", hint: "checks one requirement: yes / no", color: "#58a6ff" },
  decision: { title: "Decision", hint: "weighs variables: one output per option", color: "#bc8cff" },
  step: { title: "Step", hint: "starts an activity: done / failed", color: "#d29922" },
  action: { title: "Action", hint: "calls a function (order takeout): done / failed", color: "#db6d28" },
  wait: { title: "Wait", hint: "until a requirement is true: ready / timed_out", color: "#a5d6ff" },
  plan: { title: "Plan (sidetrack)", hint: "runs another plan and comes back: done / blocked", color: "#f778ba" },
  end: { title: "End", hint: "satisfied, fallback, done or blocked", color: "#8b949e" },
};

let D = null;          // {drives, intentions, requirements, plans, variables}
let CAT = null;        // catalogue: activities, actions, resolvers
let PROBLEMS = [];
const sel = {};        // selected id per kind

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = (o) => JSON.parse(JSON.stringify(o));

function toast(text, bad) {
  const t = $("#toast");
  t.textContent = text;
  t.style.borderColor = bad ? "var(--bad)" : "var(--border)";
  t.style.display = "block";
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.style.display = "none"), bad ? 6000 : 2500);
}

async function api(method, path, body) {
  const r = await fetch(API + path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = j.detail || {};
    const probs = (d.problems || []).map((p) => `${p.where}: ${p.text}`).join("\n");
    throw new Error((d.text || d || `the server answered ${r.status}`) + (probs ? "\n" + probs : ""));
  }
  return j;
}

async function load() {
  const j = await api("GET", "");
  D = j.data; CAT = j.catalogue; PROBLEMS = j.problems || [];
  renderAll();
}

function problemsFor(prefix) {
  return PROBLEMS.filter((p) => p.where === prefix || p.where.startsWith(prefix + "/") || p.where.startsWith(prefix + "#"));
}

function renderBadge() {
  const errs = PROBLEMS.filter((p) => p.level === "error").length, warns = PROBLEMS.length - errs;
  const b = $("#probBadge");
  b.className = "badge " + (errs ? "err" : "ok");
  b.textContent = errs ? `${errs} errors, ${warns} warnings` : warns ? `no errors, ${warns} warnings` : "all paths check out";
}

function renderAll() {
  renderBadge();
  renderOverview();
  for (const k of Object.keys(KIND_LABEL)) renderList(k);
  for (const k of Object.keys(KIND_LABEL)) renderForm(k);
  renderFlowPlans();
}

// ── overview: the full list of intentions ────────────────────────────────────────────────────────────────────────
function renderOverview() {
  const drives = Object.fromEntries(D.drives.map((d) => [d.id, d]));
  const groups = [["need", "Needs"], ["want", "Wants"], ["expectation", "Expectations and duties"]];
  let html = `<h2 style="font-size:15px;margin:0 0 4px">All intentions (${D.intentions.length})</h2>
    <div class="hint">One intention per drive. Live intentions are run by their action plans; planned ones still use the old path until they are switched on.</div>`;
  for (const [kind, title] of groups) {
    const rows = D.intentions.filter((i) => (drives[i.drive] || {}).kind === kind);
    if (!rows.length) continue;
    html += `<h3>${title} (${rows.length})</h3><table><thead><tr><th>Intention</th><th>Drive</th><th>Status</th><th>Plans</th><th>Replaces today</th><th>Problems</th></tr></thead><tbody>`;
    for (const i of rows) {
      const probs = problemsFor("intention:" + i.id).length + (i.plans || []).reduce((n, p) => n + problemsFor("plan:" + p).filter((x) => x.level === "error").length, 0);
      html += `<tr><td><a href="#" data-goto="intentions:${esc(i.id)}" style="color:var(--accent)">${esc(i.name || i.id)}</a></td>
        <td>${esc((drives[i.drive] || {}).name || i.drive)} <small class="hint">${esc((drives[i.drive] || {}).source || "")}</small></td>
        <td><span class="status ${esc(i.status || "planned")}">${esc(i.status || "planned")}</span></td>
        <td>${(i.plans || []).map((p) => `<a href="#" data-goto="flow:${esc(p)}" class="chip" style="text-decoration:none;color:var(--text)">${esc(p)}</a>`).join(" ") || '<span class="hint">none yet</span>'}</td>
        <td><small class="hint">${esc((i.replaces || []).join(", "))}</small></td>
        <td>${probs ? `<span class="badge err">${probs}</span>` : ""}</td></tr>`;
    }
    html += "</tbody></table>";
  }
  $("#overview").innerHTML = html;
}

// ── lists and forms ──────────────────────────────────────────────────────────────────────────────────────────────
function renderList(kind) {
  const f = ($(`[data-filter="${kind}"]`).value || "").toLowerCase();
  const items = D[kind].filter((o) => !f || (o.id + " " + (o.name || "")).toLowerCase().includes(f));
  $(`[data-items="${kind}"]`).innerHTML = items.map((o) => {
    const bad = problemsFor(`${KIND_LABEL[kind]}:${o.id}`).some((p) => p.level === "error");
    return `<div class="item ${sel[kind] === o.id ? "on" : ""}" data-pick="${kind}:${esc(o.id)}">
      <span>${esc(o.name || o.id)}${bad ? ' <span style="color:var(--bad)">●</span>' : ""}</span>
      <small>${o.status ? esc(o.status) : esc(o.kind || "")}</small></div>`;
  }).join("");
}

const opt = (list, cur, blank = true) => (blank ? '<option value=""></option>' : "") + list.map((v) => {
  const [val, lab] = Array.isArray(v) ? v : [v, v];
  return `<option value="${esc(val)}" ${String(cur ?? "") === String(val) ? "selected" : ""}>${esc(lab)}</option>`;
}).join("");

// one schema per object type: [key, label, input kind, options]
function schema(kind) {
  const ids = (k) => D[k].map((o) => [o.id, `${o.name || o.id} (${o.id})`]);
  return {
    drives: [["id", "Id", "text"], ["name", "Name", "text"], ["kind", "Kind", "select", ["need", "want", "expectation"]],
      ["source", "Measured from", "text"], ["threshold", "Raises its intention at", "text"], ["satisfied_below", "Satisfied below", "number"],
      ["intention", "Its one intention", "select", ids("intentions")], ["notes", "Notes", "area"]],
    intentions: [["id", "Id", "text"], ["name", "Name", "text"], ["drive", "Drive", "select", ids("drives")],
      ["status", "Status", "select", ["planned", "live"]], ["plans", "Plans, in preference order", "orderlist", ids("plans")],
      ["scout_plan", "Scout plan (optional)", "select", ids("plans")], ["satisfied_when.drive_below", "Satisfied when the drive is below", "number"],
      ["replaces", "Old intention types it replaces", "csv"], ["notes", "Notes", "area"]],
    plans: [["id", "Id", "text"], ["name", "Name", "text"], ["intention", "For intention", "select", ids("intentions")],
      ["kind", "Kind", "select", [["", "a way to satisfy the intention"], ["sidetrack", "sidetrack (makes a requirement true)"], ["scout", "scout (finds out first)"]]],
      ["status", "Status", "select", [["", "usable"], ["planned", "planned (not used yet)"]]],
      ["requires", "Entry requirements", "multi", ids("requirements")], ["produces", "Makes true (sidetracks)", "multi", ids("requirements")],
      ["cost.minutes", "Cost: minutes", "number"], ["cost.money", "Cost: money", "number"], ["cost.effort", "Cost: effort (0-5)", "number"],
      ["time_budget_seconds", "Time budget (seconds)", "number"], ["notes", "Notes", "area"]],
    requirements: [["id", "Id", "text"], ["name", "Statement", "text"], ["resolver", "Answered by", "select", CAT.resolvers.map((r) => [r.id, r.id])],
      ["scope", "Scope", "select", ["character", "household", "world"]], ["ttl_seconds", "Belief lasts (seconds; 0 = only at the gate)", "number"],
      ["learn_by", "How a character finds out", "text"]],
    variables: [["id", "Id", "text"], ["name", "Name", "text"], ["source", "Read from", "text"]],
  }[kind];
}

const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
function setPath(o, p, v) {
  const ks = p.split("."); let a = o;
  for (const k of ks.slice(0, -1)) a = a[k] = a[k] || {};
  if (v === "" || v == null) delete a[ks.at(-1)]; else a[ks.at(-1)] = v;
}

function renderForm(kind) {
  const box = $(`[data-form="${kind}"]`);
  const o = D[kind].find((x) => x.id === sel[kind]);
  if (!o) { box.innerHTML = `<div class="hint">Pick a ${KIND_LABEL[kind]} on the left, or make a new one.</div>`; return; }
  let html = `<h2>${esc(o.name || o.id)} <small class="hint">${KIND_LABEL[kind]}</small></h2>`;
  schema(kind).forEach(([key, label, type, options], n) => {
    const v = getPath(o, key), id = `f-${kind}-${n}`;
    let input;
    if (type === "select") input = `<select id="${id}" data-key="${key}">${opt(options, v)}</select>`;
    else if (type === "area") input = `<textarea id="${id}" data-key="${key}">${esc(v || "")}</textarea>`;
    else if (type === "csv") input = `<input id="${id}" data-key="${key}" data-type="csv" value="${esc((v || []).join(", "))}">`;
    else if (type === "number") input = `<input id="${id}" type="number" step="any" data-key="${key}" data-type="number" value="${esc(v ?? "")}">`;
    else if (type === "multi" || type === "orderlist") {
      const cur = v || [];
      input = `<div data-key="${key}" data-type="${type}" data-value='${esc(JSON.stringify(cur))}'>
        <div class="chips">${cur.map((x, i) => `<span class="chip">${type === "orderlist" ? `${i + 1}. ` : ""}${esc(x)}
          ${type === "orderlist" && i ? `<button title="Move up" data-up="${i}">↑</button>` : ""}<button title="Remove" data-rm="${i}">✕</button></span>`).join("")}</div>
        <div class="row" style="margin-top:6px"><select id="${id}">${opt(options.filter(([x]) => !cur.includes(x)), "")}</select><button class="btn" data-add>Add</button></div></div>`;
    } else input = `<input id="${id}" data-key="${key}" value="${esc(v ?? "")}">`;
    html += `<div class="field"><label for="${id}">${esc(label)}</label>${input}</div>`;
  });
  if (kind === "plans") html += `<div class="field"><label>Graph</label><div class="row"><span class="hint">${(o.nodes || []).length} nodes, ${(o.edges || []).length} wires, ${(o.entries || []).length} entry points</span><button class="btn" data-goto="flow:${esc(o.id)}">Open in the flow editor</button></div></div>`;
  html += `<div class="row" style="margin-top:14px"><button class="btn primary" data-save="${kind}">Save</button><button class="btn danger" data-del="${kind}">Delete</button></div>`;
  const probs = problemsFor(`${KIND_LABEL[kind]}:${o.id}`);
  if (probs.length) html += `<div class="problems">${probs.map((p) => `<div class="prob ${p.level}"><code>${esc(p.where)}</code> ${esc(p.text)}</div>`).join("")}</div>`;
  box.innerHTML = html;
  box.oninput = box.onchange = () => readForm(kind, box, o);
  box.onclick = (e) => {
    const holder = e.target.closest("[data-type=multi],[data-type=orderlist]");
    if (holder) {
      const cur = JSON.parse(holder.dataset.value);
      if (e.target.dataset.rm != null) cur.splice(+e.target.dataset.rm, 1);
      else if (e.target.dataset.up != null) { const i = +e.target.dataset.up; [cur[i - 1], cur[i]] = [cur[i], cur[i - 1]]; }
      else if (e.target.dataset.add != null) { const v = $("select", holder).value; if (v) cur.push(v); }
      else return;
      setPath(o, holder.dataset.key, cur);
      renderForm(kind);
    }
  };
}

function readForm(kind, box, o) {
  for (const el of $$("[data-key]", box)) {
    if (el.dataset.type === "multi" || el.dataset.type === "orderlist") continue;
    let v = el.value;
    if (el.dataset.type === "csv") v = v.split(",").map((s) => s.trim()).filter(Boolean);
    else if (el.dataset.type === "number") v = v === "" ? "" : Number(v);
    setPath(o, el.dataset.key, v);
  }
}

async function save(kind, o, oldId) {
  if (!o.id) return toast("Give it an id first.", true);
  try {
    if (oldId && oldId !== o.id) await api("DELETE", `/${kind}/${encodeURIComponent(oldId)}`).catch(() => {});
    const r = await api("PUT", `/${kind}/${encodeURIComponent(o.id)}`, o);
    PROBLEMS = r.problems || PROBLEMS;
    toast(`Saved ${KIND_LABEL[kind]} ${o.id}.`);
    await load();
  } catch (e) { toast(e.message, true); }
}

async function del(kind, id) {
  const b = $(`[data-del="${kind}"]`);
  if (b.dataset.armed !== "1") { b.dataset.armed = "1"; b.textContent = "Click again to delete"; return; }
  try { await api("DELETE", `/${kind}/${encodeURIComponent(id)}`); sel[kind] = null; toast(`Deleted ${id}.`); await load(); }
  catch (e) { toast(e.message, true); }
}

function newObject(kind) {
  let n = 1, id;
  do id = `new_${KIND_LABEL[kind]}_${n++}`; while (D[kind].some((o) => o.id === id));
  const o = { id, name: "" };
  if (kind === "plans") Object.assign(o, { nodes: [], edges: [], entries: [], requires: [], cost: { minutes: 10, money: 0, effort: 1 } });
  if (kind === "intentions") Object.assign(o, { status: "planned", plans: [], replaces: [] });
  D[kind].push(o); sel[kind] = id; o._new = true;
  renderList(kind); renderForm(kind);
}

// ── tabs and routing ─────────────────────────────────────────────────────────────────────────────────────────────
function showTab(tab) {
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $$(".pane").forEach((p) => p.classList.toggle("on", p.dataset.pane === tab));
  try { localStorage.setItem("behaviour.tab", tab); } catch (e) { /* storage unavailable */ }
  if (tab === "flow") drawFlow();
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-tab],[data-pick],[data-goto],[data-new],[data-save],[data-del]");
  if (!t) return;
  if (t.dataset.tab) return showTab(t.dataset.tab);
  if (t.dataset.pick) { const [k, id] = t.dataset.pick.split(/:(.*)/s); sel[k] = id; renderList(k); return renderForm(k); }
  if (t.dataset.goto) {
    e.preventDefault();
    const [k, id] = t.dataset.goto.split(/:(.*)/s);
    if (k === "flow") { openFlow(id); return showTab("flow"); }
    sel[k] = id; showTab(k); renderList(k); return renderForm(k);
  }
  if (t.dataset.new) return newObject(t.dataset.new);
  if (t.dataset.save) { const k = t.dataset.save; const o = D[k].find((x) => x.id === sel[k]) || D[k].at(-1); const copy = clone(o); delete copy._new; return save(k, copy, o._new ? null : sel[k]); }
  if (t.dataset.del) { const k = t.dataset.del; return del(k, sel[k]); }
});
for (const k of Object.keys(KIND_LABEL)) $(`[data-filter="${k}"]`).addEventListener("input", () => renderList(k));

// ── flow editor ──────────────────────────────────────────────────────────────────────────────────────────────────
const NW = 190, HEAD = 40, PORT_GAP = 22;
let F = null;          // the plan being edited (a copy): {plan, selNode, selEdge, drag, wire, dirty}

function outputsFor(n) {
  if (n.kind === "entry") return ["go"];
  if (n.kind === "gate") return ["yes", "no"];
  if (n.kind === "decision") return [...new Set([...(n.rules || []).map((r) => r.output).filter(Boolean), n.default].filter(Boolean))];
  if (n.kind === "step" || n.kind === "action") return ["done", "failed"];
  if (n.kind === "wait") return ["ready", "timed_out"];
  if (n.kind === "plan") return ["done", "blocked"];
  return [];
}
const nodeH = (n) => HEAD + Math.max(1, outputsFor(n).length) * PORT_GAP + 6;
function nodeLabel(n) {
  if (n.kind === "entry") return n.id + (n.vars && n.vars.length ? ` (${n.vars.join(", ")})` : "");
  if (n.kind === "gate" || n.kind === "wait") return (n.requirement || "?") + (n.kind === "wait" ? ` · ${Math.round((n.timeout_seconds || 0) / 60)} min` : "");
  if (n.kind === "decision") return (n.rules || []).map((r) => (r.when || []).map((c) => `${c.var}${c.op}${c.value}`).join(" & ") + `→${r.output}`).join("; ") || "no rules";
  return n.activity || n.action || n.plan || n.outcome || "?";
}

function renderFlowPlans() {
  const s = $("#flowPlan");
  const cur = F ? F.plan.id : s.value;
  s.innerHTML = D.plans.map((p) => `<option value="${esc(p.id)}" ${p.id === cur ? "selected" : ""}>${esc(p.name || p.id)} (${esc(p.id)})</option>`).join("");
  if (!F && D.plans.length) openFlow(cur || D.plans[0].id);
}

function openFlow(pid) {
  const p = D.plans.find((x) => x.id === pid);
  if (!p) return;
  const plan = clone(p);
  plan.nodes = plan.nodes || []; plan.edges = plan.edges || [];
  // entry points are drawn as their own nodes, wired by their single output "go"
  const entries = plan.entries && plan.entries.length ? plan.entries : (plan.start ? [{ id: "start", node: plan.start, vars: [] }] : []);
  // entry points get their own column, left of everything else
  const minX = Math.min(...plan.nodes.filter((n) => n.x != null).map((n) => n.x), 40);
  const minY = Math.min(...plan.nodes.filter((n) => n.y != null).map((n) => n.y), 40);
  entries.forEach((e, i) => {
    plan.nodes.push({ id: "@" + e.id, kind: "entry", vars: e.vars || [], x: minX - 260, y: minY + i * 100 });
    if (e.node) plan.edges.push({ from: "@" + e.id, output: "go", to: e.node });
  });
  plan.nodes.forEach((n, i) => { if (n.x == null) { n.x = 60 + (i % 4) * 240; n.y = 40 + Math.floor(i / 4) * 140; } });
  F = { plan, selNode: null, selEdge: null, dirty: false, pan: { x: 260, y: 30 } };
  $("#flowPlan").value = pid;
  drawFlow(); checkDraft();
}

function flowToPlan() {
  const p = clone(F.plan);
  const entries = p.nodes.filter((n) => n.kind === "entry").map((n) => ({
    id: n.id.slice(1), vars: n.vars || [], node: (p.edges.find((e) => e.from === n.id) || {}).to || null }));
  p.nodes = p.nodes.filter((n) => n.kind !== "entry");
  p.edges = p.edges.filter((e) => !e.from.startsWith("@"));
  p.entries = entries;
  p.start = (entries[0] || {}).node || null;
  return p;
}

let checkTimer = null;
function checkDraft() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    const data = clone(D);
    const p = flowToPlan();
    data.plans = data.plans.map((x) => (x.id === p.id ? p : x));
    try { F.problems = (await api("POST", "/check", data)).problems.filter((x) => x.where === "plan:" + p.id || x.where.startsWith("plan:" + p.id + "/") || x.where.startsWith("plan:" + p.id + "#")); }
    catch (e) { F.problems = [{ level: "error", where: "", text: e.message }]; }
    drawFlow();
  }, 300);
}

function portPos(n, out) {
  const i = outputsFor(n).indexOf(out);
  return { x: n.x + NW, y: n.y + HEAD + i * PORT_GAP + 8 };
}
const inPos = (n) => ({ x: n.x, y: n.y + 20 });
const curve = (a, b) => { const dx = Math.max(40, Math.abs(b.x - a.x) / 2); return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`; };

function drawFlow() {
  if (!F) return;
  const svg = $("#canvas");
  const P = F.pan;
  const bad = new Set((F.problems || []).filter((p) => p.level === "error").map((p) => (p.where.split("/")[1] || "")));
  const byId = Object.fromEntries(F.plan.nodes.map((n) => [n.id, n]));
  let h = `<g transform="translate(${P.x},${P.y})">`;
  F.plan.edges.forEach((e, i) => {
    const a = byId[e.from], b = byId[e.to];
    if (!a || !b) return;
    const s = portPos(a, e.output), t = inPos(b);
    const extra = [e.entry ? `→${e.entry}` : "", e.set ? Object.entries(e.set).map(([k, v]) => `${k}=${v}`).join(" ") : ""].filter(Boolean).join(" ");
    h += `<path class="edge ${F.selEdge === i ? "sel" : ""}" data-edge="${i}" d="${curve(s, t)}"/>`;
    if (extra) h += `<text class="edgeLabel" x="${(s.x + t.x) / 2}" y="${(s.y + t.y) / 2 - 6}" text-anchor="middle">${esc(extra)}</text>`;
  });
  if (F.wire) h += `<path class="edge sel" d="${curve(F.wire.from, F.wire.to)}"/>`;
  for (const n of F.plan.nodes) {
    const k = NODE_KINDS[n.kind] || NODE_KINDS.end, outs = outputsFor(n), H = nodeH(n);
    h += `<g class="node ${F.selNode === n.id ? "sel" : ""} ${bad.has(n.id) ? "bad" : ""}" data-node="${esc(n.id)}" transform="translate(${n.x},${n.y})">
      <rect class="body" width="${NW}" height="${H}" rx="8"/><rect width="4" height="${H}" rx="2" fill="${k.color}"/>
      <text class="kind" x="12" y="15">${esc(k.title)}${n.kind === "entry" ? "" : " · " + esc(n.id)}</text>
      <text x="12" y="32">${esc(nodeLabel(n).slice(0, 28))}</text>
      ${n.kind !== "entry" ? `<circle cx="0" cy="20" r="5" fill="${k.color}"/>` : ""}
      ${outs.map((o, i) => `<g class="port" data-port="${esc(n.id)}|${esc(o)}"><circle cx="${NW}" cy="${HEAD + i * PORT_GAP + 8}" r="6" fill="${k.color}"/><text x="${NW - 10}" y="${HEAD + i * PORT_GAP + 12}" text-anchor="end">${esc(o)}</text></g>`).join("")}
    </g>`;
  }
  h += "</g>";
  svg.innerHTML = h;
  drawSide();
}

function drawSide() {
  const s = $("#side");
  const probs = F.problems || [];
  let html = `<h3>${esc(F.plan.name || F.plan.id)}${F.dirty ? ' <span class="badge err">unsaved</span>' : ""}</h3>
    <div class="hint">${F.plan.nodes.length} nodes · ${F.plan.edges.length} wires</div>`;
  const n = F.plan.nodes.find((x) => x.id === F.selNode);
  if (n) html += `<div style="margin-top:12px"><b>${esc(NODE_KINDS[n.kind].title)}</b> <code>${esc(n.id)}</code><div class="hint">${esc(NODE_KINDS[n.kind].hint)}</div>
    <div class="row" style="margin-top:6px"><button class="btn" id="editNode">Edit</button><button class="btn danger" id="delNode">Delete</button></div></div>`;
  if (F.selEdge != null) {
    const e = F.plan.edges[F.selEdge];
    if (e) html += `<div style="margin-top:12px"><b>Wire</b> <code>${esc(e.from)}.${esc(e.output)} → ${esc(e.to)}</code>
      <div class="field" style="grid-template-columns:1fr;margin-top:6px"><label for="edgeSet">Sets variables (name=value, comma-separated)</label>
      <input id="edgeSet" value="${esc(Object.entries(e.set || {}).map(([k, v]) => `${k}=${v}`).join(", "))}"></div>
      <div class="field" style="grid-template-columns:1fr"><label for="edgeEntry">Into entry point (for a plan node)</label><input id="edgeEntry" value="${esc(e.entry || "")}"></div>
      <div class="row"><button class="btn" id="applyEdge">Apply</button><button class="btn danger" id="delEdge">Delete wire</button></div></div>`;
  }
  html += `<div class="problems"><b>Checker</b>${probs.length ? probs.map((p) => `<div class="prob ${p.level}"><code>${esc(p.where.replace("plan:" + F.plan.id, "") || "plan")}</code> ${esc(p.text)}</div>`).join("") : '<div class="hint">Every path checks out.</div>'}</div>`;
  s.innerHTML = html;
  const on = (id, fn) => { const el = $("#" + id); if (el) el.onclick = fn; };
  on("editNode", () => editNode(n));
  on("delNode", () => removeNode(n.id));
  on("delEdge", () => { F.plan.edges.splice(F.selEdge, 1); F.selEdge = null; changed(); });
  on("applyEdge", () => {
    const e = F.plan.edges[F.selEdge];
    const set = Object.fromEntries($("#edgeSet").value.split(",").map((s) => s.split("=").map((x) => x.trim())).filter(([k]) => k));
    if (Object.keys(set).length) e.set = set; else delete e.set;
    const en = $("#edgeEntry").value.trim();
    if (en) e.entry = en; else delete e.entry;
    changed();
  });
}

function changed() { F.dirty = true; drawFlow(); checkDraft(); }

function removeNode(id) {
  F.plan.nodes = F.plan.nodes.filter((n) => n.id !== id);
  F.plan.edges = F.plan.edges.filter((e) => e.from !== id && e.to !== id);
  F.selNode = null; changed();
}

// the palette: drag a kind onto the canvas, then pick its definition
function renderPalette() {
  $("#palette").innerHTML = Object.entries(NODE_KINDS).map(([k, v]) =>
    `<div class="tool" draggable="true" data-kind="${k}" style="border-left:4px solid ${v.color}"><b>${esc(v.title)}</b><small>${esc(v.hint)}</small></div>`).join("");
  $$("#palette .tool").forEach((t) => t.addEventListener("dragstart", (e) => e.dataTransfer.setData("text/kind", t.dataset.kind)));
}

const wrap = $("#canvasWrap");
wrap.addEventListener("dragover", (e) => e.preventDefault());
wrap.addEventListener("drop", async (e) => {
  e.preventDefault();
  const kind = e.dataTransfer.getData("text/kind");
  if (!kind || !F) return;
  const r = wrap.getBoundingClientRect();
  const n = { kind, x: Math.round(e.clientX - r.left - F.pan.x - NW / 2), y: Math.round(e.clientY - r.top - F.pan.y - 20) };
  let i = 1; do n.id = (kind === "entry" ? "@entry" : kind) + (i > 1 ? i : ""); while (F.plan.nodes.some((x) => x.id === n.id) && ++i);
  if (kind === "entry") n.vars = [];
  if (kind === "decision") { n.rules = []; n.default = "otherwise"; }
  const ok = await editNode(n, true);
  if (ok) { F.plan.nodes.push(n); F.selNode = n.id; changed(); }
});

function pickList(kind) {
  if (kind === "gate" || kind === "wait") return D.requirements.map((r) => [r.id, `${r.id}: ${r.name || ""}`]);
  if (kind === "step") return CAT.activities.map((a) => [a.id, `${a.id}${a.interaction ? ` (${a.interaction})` : ""}${a.available ? "" : " ⚠ no prop offers it"}`]);
  if (kind === "action") return CAT.actions.map((a) => [a.id, `${a.id}: ${a.doc}`]);
  if (kind === "plan") return D.plans.filter((p) => p.id !== F.plan.id).map((p) => [p.id, `${p.name || p.id} (${p.id})`]);
  if (kind === "end") return (F.plan.kind === "sidetrack" || F.plan.kind === "scout" ? CAT.end_outcomes.sub : CAT.end_outcomes.intention).map((o) => [o, o]);
  return [];
}

function editNode(n, isNew) {
  const dlg = $("#dlg");
  const field = { gate: "requirement", wait: "requirement", step: "activity", action: "action", plan: "plan", end: "outcome" }[n.kind];
  let body = `<h3 style="margin:0 0 10px">${esc(NODE_KINDS[n.kind].title)}</h3><div class="hint" style="margin-bottom:10px">${esc(NODE_KINDS[n.kind].hint)}</div>
    <div class="field"><label for="dId">Id</label><input id="dId" value="${esc(n.kind === "entry" ? n.id.slice(1) : n.id)}"></div>`;
  if (field) body += `<div class="field"><label for="dRef">${esc(field)}</label><select id="dRef">${opt(pickList(n.kind), n[field])}</select></div>`;
  if (n.kind === "wait") body += `<div class="field"><label for="dTimeout">Gives up after (minutes)</label><input id="dTimeout" type="number" value="${Math.round((n.timeout_seconds || 1800) / 60)}"></div>`;
  if (n.kind === "entry") body += `<div class="field"><label for="dVars">Variables it receives (comma-separated)</label><input id="dVars" value="${esc((n.vars || []).join(", "))}"></div>`;
  if (n.kind === "decision") {
    const vars = D.variables.map((v) => v.id).join(", ");
    body += `<div class="hint">One rule per line: <code>output: var op value [and var op value]</code>, e.g. <code>open: hour >= 10 and hour &lt; 23</code>. Ops: &lt; &lt;= &gt; &gt;= == != in. Variables: ${esc(vars)}, and any a wire or entry point sets.</div>
      <textarea id="dRules" style="min-height:110px">${esc((n.rules || []).map((r) => `${r.output}: ` + (r.when || []).map((c) => `${c.var} ${c.op} ${JSON.stringify(c.value)}`).join(" and ")).join("\n"))}</textarea>
      <div class="field" style="margin-top:8px"><label for="dDefault">Otherwise (default output)</label><input id="dDefault" value="${esc(n.default || "otherwise")}"></div>`;
  }
  body += `<div class="row" style="margin-top:12px;justify-content:flex-end"><button class="btn" value="cancel">Cancel</button><button class="btn primary" value="ok">${isNew ? "Add" : "Apply"}</button></div>`;
  dlg.innerHTML = `<form method="dialog">${body}</form>`;
  dlg.showModal();
  return new Promise((resolve) => {
    dlg.onclose = () => {
      if (dlg.returnValue !== "ok") return resolve(false);
      const newId = $("#dId", dlg).value.trim() || n.id;
      const oldId = n.id;
      n.id = n.kind === "entry" ? "@" + newId.replace(/^@/, "") : newId;
      if (!isNew && oldId !== n.id) F.plan.edges.forEach((e) => { if (e.from === oldId) e.from = n.id; if (e.to === oldId) e.to = n.id; });
      if (field) n[field] = $("#dRef", dlg).value;
      if (n.kind === "wait") n.timeout_seconds = Math.max(1, Number($("#dTimeout", dlg).value || 30)) * 60;
      if (n.kind === "entry") n.vars = $("#dVars", dlg).value.split(",").map((s) => s.trim()).filter(Boolean);
      if (n.kind === "decision") {
        n.rules = $("#dRules", dlg).value.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
          const [out, cond = ""] = line.split(/:(.*)/s);
          return { output: out.trim(), when: cond.split(/\band\b/).map((c) => c.trim()).filter(Boolean).map((c) => {
            const m = c.match(/^(\w+)\s*(<=|>=|==|!=|<|>|in)\s*(.+)$/);
            if (!m) return null;
            let v = m[3].trim(); try { v = JSON.parse(v); } catch (e) { /* a bare word stays a string */ }
            return { var: m[1], op: m[2], value: v };
          }).filter(Boolean) };
        });
        n.default = $("#dDefault", dlg).value.trim() || "otherwise";
        const outs = outputsFor(n);
        F.plan.edges = F.plan.edges.filter((e) => e.from !== n.id || outs.includes(e.output));
      }
      if (!isNew) changed();
      resolve(true);
    };
  });
}

// pointer: move nodes, pan, draw wires
const svgEl = $("#canvas");
svgEl.addEventListener("pointerdown", (e) => {
  if (!F) return;
  const r = wrap.getBoundingClientRect();
  const pt = { x: e.clientX - r.left - F.pan.x, y: e.clientY - r.top - F.pan.y };
  const port = e.target.closest(".port"), node = e.target.closest(".node"), edge = e.target.closest("[data-edge]");
  if (port) {
    const [id, out] = port.dataset.port.split("|");
    const n = F.plan.nodes.find((x) => x.id === id);
    F.wire = { id, out, from: portPos(n, out), to: pt };
  } else if (node) {
    const n = F.plan.nodes.find((x) => x.id === node.dataset.node);
    F.selNode = n.id; F.selEdge = null;
    F.drag = { n, dx: pt.x - n.x, dy: pt.y - n.y, moved: false };
  } else if (edge) {
    F.selEdge = +edge.dataset.edge; F.selNode = null;
  } else {
    F.selNode = null; F.selEdge = null;
    F.panning = { x: e.clientX, y: e.clientY, px: F.pan.x, py: F.pan.y };
  }
  svgEl.setPointerCapture(e.pointerId);
  drawFlow();
});
svgEl.addEventListener("pointermove", (e) => {
  if (!F) return;
  const r = wrap.getBoundingClientRect();
  const pt = { x: e.clientX - r.left - F.pan.x, y: e.clientY - r.top - F.pan.y };
  if (F.wire) { F.wire.to = pt; drawFlow(); }
  else if (F.drag) { F.drag.n.x = Math.round(pt.x - F.drag.dx); F.drag.n.y = Math.round(pt.y - F.drag.dy); F.drag.moved = true; drawFlow(); }
  else if (F.panning) { F.pan.x = F.panning.px + e.clientX - F.panning.x; F.pan.y = F.panning.py + e.clientY - F.panning.y; drawFlow(); }
});
svgEl.addEventListener("pointerup", (e) => {
  if (!F) return;
  if (F.wire) {
    const r = wrap.getBoundingClientRect();
    const pt = { x: e.clientX - r.left - F.pan.x, y: e.clientY - r.top - F.pan.y };
    const target = F.plan.nodes.find((n) => n.kind !== "entry" && pt.x >= n.x && pt.x <= n.x + NW && pt.y >= n.y && pt.y <= n.y + nodeH(n));
    if (target && target.id !== F.wire.id) {
      F.plan.edges = F.plan.edges.filter((x) => !(x.from === F.wire.id && x.output === F.wire.out));   // one wire per output
      F.plan.edges.push({ from: F.wire.id, output: F.wire.out, to: target.id });
      F.wire = null; changed(); return;
    }
    F.wire = null; drawFlow();
  }
  if (F.drag && F.drag.moved) F.dirty = true;
  F.drag = null; F.panning = null;
});
svgEl.addEventListener("dblclick", (e) => {
  const node = e.target.closest(".node");
  if (node && F) editNode(F.plan.nodes.find((x) => x.id === node.dataset.node));
});
document.addEventListener("keydown", (e) => {
  if (!F || !$('[data-pane="flow"]').classList.contains("on") || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (e.key === "Delete" || e.key === "Backspace") {
    if (F.selNode) removeNode(F.selNode);
    else if (F.selEdge != null) { F.plan.edges.splice(F.selEdge, 1); F.selEdge = null; changed(); }
  }
});

$("#flowPlan").addEventListener("change", (e) => openFlow(e.target.value));
$("#flowRevert").addEventListener("click", () => openFlow(F.plan.id));
$("#flowSave").addEventListener("click", async () => {
  const p = flowToPlan();
  try { await api("PUT", `/plans/${encodeURIComponent(p.id)}`, p); toast(`Saved plan ${p.id}.`); F.dirty = false; await load(); openFlow(p.id); }
  catch (e) { toast(e.message, true); }
});
$("#flowTidy").addEventListener("click", () => {
  // columns by distance from the entry points, rows in order of discovery
  const depth = {}, q = F.plan.nodes.filter((n) => n.kind === "entry").map((n) => [n.id, 0]);
  while (q.length) {
    const [id, d] = q.shift();
    if (depth[id] != null) continue;
    depth[id] = d;
    F.plan.edges.filter((e) => e.from === id).forEach((e) => q.push([e.to, d + 1]));
  }
  const rows = {};
  F.plan.nodes.forEach((n) => { const d = depth[n.id] ?? 0; rows[d] = (rows[d] || 0) + 1; n.x = d * 240; n.y = (rows[d] - 1) * 130; });
  changed();
});

renderPalette();
load().then(() => {
  let tab = "overview";
  try { tab = localStorage.getItem("behaviour.tab") || tab; } catch (e) { /* storage unavailable */ }
  showTab(tab);
}).catch((e) => toast("Could not load the definitions: " + e.message, true));
