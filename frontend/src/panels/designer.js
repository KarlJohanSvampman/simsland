// src/panels/designer.js -- the panel designer (panels.html): make debug panel templates by type, pick their data,
// style them, say who gets them, and manage any entity's panels and layouts. Previews use the same renderer as VR
// (src/panels/render.js).

import * as api from "./api.js";
import { renderPanel, clickPanel, hitAt, panTimeline, zoomTimeline } from "./render.js";

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const TYPE_LABEL = { table: "Data table", line: "Line graph", pie: "Pie chart", bar: "Bar chart", tree: "Tree", text: "Rich text" };
const STATE_LABEL = { enabled: "Enabled", disabled: "Disabled", on_demand: "On demand" };

let META = { templates: [], types: [], states: [], max_alternatives: 5 };
let current = null;               // the template being edited (a copy)
let view = {};                    // the preview's panel view state
let feed = new api.PanelFeed();
let hits = [];

function toast(msg, bad) {
  const t = $("#toast");
  t.textContent = msg; t.style.display = "block"; t.style.borderColor = bad ? "var(--bad)" : "var(--border)";
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.style.display = "none"), 3500);
}
const kind = () => $("#kindSel").value;
const entity = () => $("#entitySel").value;

// ---- entities --------------------------------------------------------------------------------------------------------
async function loadEntities() {
  const out = await api.listEntities(kind()).catch(() => ({ entities: [] }));
  $("#entitySel").innerHTML = out.entities.map((e) => `<option value="${esc(e.id)}">${esc(e.name)} (${esc(e.id)})</option>`).join("");
  view = {}; feed = new api.PanelFeed();
  renderManage();
}

// ---- template list ----------------------------------------------------------------------------------------------------
async function loadTemplates(selectId) {
  META = await api.listTemplates();
  $("#tplList").innerHTML = META.templates.map((t) =>
    `<div class="item ${current && current.id === t.id ? "on" : ""}" data-id="${esc(t.id)}"><span>${esc(t.name || t.id)}</span><small>${esc(t.type)}</small></div>`).join("")
    || '<p class="hint" style="padding:10px">No panels yet.</p>';
  if (selectId) select(selectId);
}

function select(id) {
  const t = META.templates.find((x) => x.id === id);
  if (!t) return;
  current = JSON.parse(JSON.stringify(t));
  view = {};
  renderForm();
  loadTemplates();
}

function newOfType(type) {
  let n = 1, id = `${type}_${n}`;
  while (META.templates.some((t) => t.id === id)) id = `${type}_${++n}`;
  const defaults = {
    table: { page_size: 8, order: "newest", timeline: true, columns: [] },
    line: { series: [] }, pie: {}, bar: {}, tree: { max_rows: 40 },
    text: { html: "<h2>{{name}}</h2><p>Hunger: <b>{{body.hunger}}</b></p>", font_size: 26 },
  }[type];
  current = { id, name: TYPE_LABEL[type], type, source: { path: type === "text" ? "" : "", refresh_s: 2 }, options: defaults,
              assign: { scope: "kinds", kinds: [kind()], entities: [] }, default_state: "enabled", _new: true };
  view = {};
  renderForm();
}

// ---- the form -------------------------------------------------------------------------------------------------------
function opt(v, label, cur) { return `<option value="${esc(v)}" ${String(cur) === String(v) ? "selected" : ""}>${esc(label)}</option>`; }

function typeOptions(t) {
  const o = t.options ||= {};
  const csv = (a) => (a || []).join(", ");
  if (t.type === "table") return `
    <div class="field"><label>Columns</label><input data-o="columns" data-csv value="${esc(csv(o.columns))}" placeholder="auto (or: tick, added, why)"></div>
    <div class="field"><label>Time field</label><input data-o="time_key" value="${esc(o.time_key || "")}" placeholder="auto (tick, time, when, ...)"></div>
    <div class="field"><label>Order</label><select data-o="order">${opt("newest", "Newest first", o.order)}${opt("oldest", "Oldest first", o.order)}${opt("as_is", "As stored", o.order)}</select></div>
    <div class="field"><label>Sort by field</label><input data-o="sort_key" value="${esc(o.sort_key || "")}" placeholder="(none)"></div>
    <div class="field"><label>Rows per page</label><input data-o="page_size" type="number" min="1" max="100" value="${esc(o.page_size || 8)}"></div>
    <div class="field"><label>Timeline</label><label><input type="checkbox" data-o="timeline" ${o.timeline !== false ? "checked" : ""}> show a timeline when the rows have times</label></div>`;
  if (t.type === "line") return `
    <div class="field"><label>Time / x field</label><input data-o="x_key" value="${esc(o.x_key || "")}" placeholder="auto"></div>
    <div class="field"><label>Series</label><input data-o="series" data-csv value="${esc(csv(o.series))}" placeholder="auto: every number"></div>
    <p class="hint">A single number (like body.hunger) becomes a live series: a point every refresh.</p>`;
  if (t.type === "pie" || t.type === "bar") return `
    <div class="field"><label>Label field</label><input data-o="label_key" value="${esc(o.label_key || "")}" placeholder="auto (first text field)"></div>
    <div class="field"><label>Value field</label><input data-o="value_key" value="${esc(o.value_key || "")}" placeholder="(count the rows)"></div>
    <div class="field"><label>Most slices</label><input data-o="max_slices" type="number" min="2" max="30" value="${esc(o.max_slices || 10)}"></div>
    <p class="hint">An object of numbers ({label: number}) is used as it is.</p>`;
  if (t.type === "tree") return `<div class="field"><label>Most rows</label><input data-o="max_rows" type="number" min="5" max="400" value="${esc(o.max_rows || 40)}"></div>`;
  if (t.type === "text") return `
    <div class="field"><label>Base font</label><select data-o="font_family">${["system-ui, sans-serif", "Georgia, serif", "Consolas, monospace", "Trebuchet MS, sans-serif"].map((f) => opt(f, f.split(",")[0], o.font_family || "system-ui, sans-serif")).join("")}</select></div>
    <div class="field"><label>Base size</label><input data-o="font_size" type="number" min="10" max="80" value="${esc(o.font_size || 26)}"></div>
    <div class="field"><label>Base colour</label><input data-o="color" type="color" value="${esc(o.color || "#c9d1d9")}"></div>
    <div class="toolbar" id="rteBar">
      <button class="btn" data-cmd="bold"><b>B</b></button><button class="btn" data-cmd="italic"><i>I</i></button><button class="btn" data-cmd="underline"><u>U</u></button>
      <select data-block><option value="">Paragraph…</option><option value="h1">Heading 1</option><option value="h2">Heading 2</option><option value="h3">Heading 3</option><option value="p">Normal</option></select>
      <select data-size><option value="">Size…</option>${[12, 14, 16, 20, 24, 32].map((s) => `<option value="${s}">${s}</option>`).join("")}</select>
      <input type="color" data-color title="Text colour" value="#58a6ff">
      <button class="btn" data-insert>Insert value…</button>
    </div>
    <div class="rte" id="rte" contenteditable="true">${o.html || ""}</div>
    <p class="hint">Values are <code>{{path}}</code> into the data source (empty source = the whole entity), e.g. <code>{{body.hunger}}</code>, <code>{{mood.name}}</code>.</p>`;
  return "";
}

function renderForm() {
  const t = current;
  if (!t) return;
  const a = t.assign ||= { scope: "all" };
  const kinds = ["character", "prop", "household", "building", "item"];
  $("#form").innerHTML = `
    <div class="row" style="justify-content:space-between"><h2 style="margin:0;font-size:15px">${esc(TYPE_LABEL[t.type] || t.type)}</h2>
      <div class="row"><button class="btn primary" id="saveTpl">Save</button>${t._new ? "" : '<button class="btn danger" id="delTpl">Delete</button>'}</div></div>
    <h3>Panel</h3>
    <div class="field"><label>Id</label><input data-f="id" value="${esc(t.id)}" ${t._new ? "" : "disabled"}></div>
    <div class="field"><label>Name</label><input data-f="name" value="${esc(t.name || "")}"></div>
    <div class="field"><label>Type</label><select data-f="type">${META.types.map((x) => opt(x, TYPE_LABEL[x] || x, t.type)).join("")}</select></div>
    <h3>Data</h3>
    <div class="field"><label>Path</label><div class="row" style="flex-wrap:nowrap"><input data-src="path" value="${esc(t.source?.path || "")}" placeholder="(the whole entity)"><button class="btn" id="browseBtn">Browse</button></div></div>
    <div id="browser" class="browser" style="display:none"></div>
    <div class="field"><label>Refresh every</label><div class="row" style="flex-wrap:nowrap"><input data-src="refresh_s" type="number" min="0.5" step="0.5" value="${esc(t.source?.refresh_s ?? 2)}" style="width:90px"> <span class="hint">seconds</span></div></div>
    <h3>Looks</h3>
    ${typeOptions(t)}
    <h3>Who gets it</h3>
    <div class="field"><label>Assigned to</label><select data-a="scope">${opt("all", "Everything", a.scope)}${opt("kinds", "All of some kinds", a.scope)}${opt("entities", "Specific ones", a.scope)}</select></div>
    <div class="field" style="${a.scope === "kinds" ? "" : "display:none"}"><label>Kinds</label><div class="row">${kinds.map((k) => `<label><input type="checkbox" data-kind="${k}" ${(a.kinds || []).includes(k) ? "checked" : ""}> ${k}</label>`).join("")}</div></div>
    <div class="field" style="${a.scope === "entities" ? "" : "display:none"}"><label>Entities</label><div>
      <div class="hint">${(a.entities || []).map((e) => `<span class="row" style="display:inline-flex">${esc(e)} <button class="btn" data-unassign="${esc(e)}">×</button></span>`).join(" ") || "none yet"}</div>
      <button class="btn" id="assignThis" style="margin-top:4px">+ the one picked at the top</button></div></div>
    <div class="field"><label>By default</label><select data-f="default_state">${META.states.map((s) => opt(s, STATE_LABEL[s], t.default_state)).join("")}</select></div>
    <p class="hint">On demand: shown only while its data has something in it.</p>`;
  wireForm();
  drawPreview(true);
}

function wireForm() {
  const f = $("#form");
  f.oninput = f.onchange = (e) => {
    const el = e.target, t = current;
    if (el.dataset.f) { t[el.dataset.f] = el.value; if (el.dataset.f === "type") { t.options = {}; return renderForm(); } }
    if (el.dataset.src) { t.source ||= {}; t.source[el.dataset.src] = el.type === "number" ? Number(el.value) : el.value; feed = new api.PanelFeed(); }
    if (el.dataset.o) {
      t.options ||= {};
      t.options[el.dataset.o] = el.type === "checkbox" ? el.checked : el.dataset.csv !== undefined
        ? el.value.split(",").map((s) => s.trim()).filter(Boolean) : el.type === "number" ? Number(el.value) : el.value;
    }
    if (el.dataset.a) { t.assign.scope = el.value; return renderForm(); }
    if (el.dataset.kind) { const s = new Set(t.assign.kinds || []); el.checked ? s.add(el.dataset.kind) : s.delete(el.dataset.kind); t.assign.kinds = [...s]; }
    if (el.dataset.block !== undefined && el.value) { document.execCommand("formatBlock", false, el.value); el.value = ""; syncRte(); }
    if (el.dataset.size !== undefined && el.value) { wrapSelection(`font-size:${el.value}px`); el.value = ""; }
    if (el.dataset.color !== undefined && e.type === "change") document.execCommand("foreColor", false, el.value), syncRte();
    view = {};
    drawPreview(true);
  };
  f.onclick = async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.id === "saveTpl") return saveCurrent();
    if (b.id === "delTpl") return deleteCurrent();
    if (b.id === "browseBtn") return toggleBrowser("src");
    if (b.dataset.insert !== undefined) return toggleBrowser("insert");
    if (b.dataset.cmd) { document.execCommand(b.dataset.cmd); syncRte(); }
    if (b.id === "assignThis") { const k = `${kind()}:${entity()}`; current.assign.entities = [...new Set([...(current.assign.entities || []), k])]; renderForm(); }
    if (b.dataset.unassign) { current.assign.entities = (current.assign.entities || []).filter((x) => x !== b.dataset.unassign); renderForm(); }
  };
  const rte = $("#rte");
  if (rte) rte.addEventListener("input", syncRte);
}

function syncRte() { const rte = $("#rte"); if (rte && current) { current.options.html = rte.innerHTML; view = {}; drawPreview(true); } }
function wrapSelection(style) {
  const sel = window.getSelection();
  if (!sel.rangeCount || sel.isCollapsed) return;
  const span = document.createElement("span"); span.setAttribute("style", style);
  span.appendChild(sel.getRangeAt(0).extractContents()); sel.getRangeAt(0).insertNode(span); syncRte();
}

// the data browser: click a field to use its path (as the source, or as a {{value}} in the text)
let browserFor = null, savedRange = null;
async function toggleBrowser(mode) {
  const box = $("#browser");
  if (box.style.display !== "none" && browserFor === mode) { box.style.display = "none"; return; }
  browserFor = mode;
  if (mode === "insert") { const s = window.getSelection(); savedRange = s.rangeCount ? s.getRangeAt(0).cloneRange() : null; }
  box.style.display = "block";
  const base = mode === "insert" ? (current.source?.path || "") : "";
  box.innerHTML = '<span class="hint">loading…</span>';
  try {
    const out = await api.fieldsOf(kind(), entity(), base, 3);
    box.innerHTML = `<div class="hint">${mode === "insert" ? "Click a value to insert it" : "Click a field to use it"} (${esc(entity())}):</div>` + outline(out.fields, "");
  } catch (err) { box.innerHTML = `<span class="hint">${esc(err.message)}</span>`; }
  box.onclick = (e) => {
    const row = e.target.closest("[data-path]");
    if (!row) return;
    const p = row.dataset.path;
    if (browserFor === "src") { current.source.path = p; $("[data-src=path]").value = p; feed = new api.PanelFeed(); view = {}; }
    else {
      const rte = $("#rte"); rte.focus();
      if (savedRange) { const s = window.getSelection(); s.removeAllRanges(); s.addRange(savedRange); }
      document.execCommand("insertText", false, `{{${p}}}`); syncRte();
    }
    box.style.display = "none";
    drawPreview(true);
  };
}
function outline(fields, prefix, depth = 0) {
  return Object.entries(fields || {}).map(([k, f]) => {
    const p = prefix ? `${prefix}.${k}` : k;
    const info = f.type === "list" ? `list (${f.size})` : f.type === "object" ? `{${f.size}}` : `${f.type}${f.sample !== undefined ? " = " + esc(String(f.sample)) : ""}`;
    const kids = f.children ? outline(f.children, p, depth + 1) : f.item?.children ? outline(f.item.children, p + ".-1", depth + 1) : "";
    return `<div data-path="${esc(p)}" style="padding-left:${depth * 14 + 4}px">${esc(k)} <small>${info}</small></div>${kids}`;
  }).join("");
}

async function saveCurrent() {
  const t = { ...current }; delete t._new;
  try { await api.saveTemplate(t); toast("Saved."); current._new = false; await loadTemplates(t.id); }
  catch (err) { toast(err.message, true); }
}
async function deleteCurrent() {
  if (!confirm(`Delete the panel "${current.name || current.id}"? It goes from every layout too.`)) return;
  try { await api.deleteTemplate(current.id); current = null; $("#form").innerHTML = ""; toast("Deleted."); await loadTemplates(); }
  catch (err) { toast(err.message, true); }
}

// ---- preview ---------------------------------------------------------------------------------------------------------
const canvas = $("#preview"), ctx = canvas.getContext("2d");
function drawPreview(force) {
  if (!current || !entity()) return;
  const e = feed.get(kind(), entity(), current);
  const sub = e.error ? `couldn't read ${current.source?.path || "the entity"}: ${e.error}` : `${entity()} · ${current.source?.path || "(whole entity)"}`;
  ({ hits } = renderPanel(ctx, 900, current, e.value, view, sub));
}
setInterval(() => drawPreview(), 500);
const toCanvas = (ev) => { const r = canvas.getBoundingClientRect(); return [(ev.clientX - r.left) * (canvas.width / r.width), (ev.clientY - r.top) * (canvas.height / r.height)]; };
let drag = null;
canvas.addEventListener("mousedown", (ev) => { const [x, y] = toCanvas(ev); const h = hitAt(hits, x, y); drag = h?.timeline ? { x, w: h.w, moved: false } : null; });
canvas.addEventListener("mousemove", (ev) => {
  if (!drag) return;
  const [x] = toCanvas(ev);
  if (Math.abs(x - drag.x) > 3) { panTimeline(view, -(x - drag.x) / drag.w); drag.x = x; drag.moved = true; drawPreview(); }
});
canvas.addEventListener("mouseup", (ev) => {
  const moved = drag?.moved; drag = null;
  if (moved) return;
  const [x, y] = toCanvas(ev);
  if (clickPanel(view, hitAt(hits, x, y)?.action)) drawPreview();
});
canvas.addEventListener("wheel", (ev) => {
  const [x, y] = toCanvas(ev); const h = hitAt(hits, x, y);
  if (!h?.timeline && !h?.point) return;
  ev.preventDefault();
  zoomTimeline(view, ev.deltaY > 0 ? 1.25 : 0.8, Math.max(0, Math.min(1, (x - h.x) / h.w)));
  drawPreview();
}, { passive: false });

// ---- manage: an entity's panels and layouts ----------------------------------------------------------------------------
let manage = null;              // {data: for_entity result, draft: {active, layouts}}
async function renderManage() {
  const el = $("#manage");
  if (!entity()) { el.innerHTML = '<p class="hint">Pick an entity at the top.</p>'; return; }
  try { manage = { data: await api.panelsFor(kind(), entity()) }; }
  catch (err) { el.innerHTML = `<p class="hint">${esc(err.message)}</p>`; return; }
  manage.draft = { active: manage.data.active, layouts: JSON.parse(JSON.stringify(manage.data.layouts)) };
  drawManage();
}
function drawManage() {
  const el = $("#manage"), d = manage.data, dr = manage.draft;
  const lay = dr.layouts[dr.active] ||= { panels: {} };
  const applicable = new Map(d.templates.map((t) => [t.id, t]));
  for (const tid of Object.keys(lay.panels)) { const t = META.templates.find((x) => x.id === tid); if (t) applicable.set(tid, t); }
  const others = META.templates.filter((t) => !applicable.has(t.id));
  const names = Object.keys(dr.layouts);
  el.innerHTML = `
    <h2 style="font-size:15px;margin:0 0 4px">${esc(entity())} <span class="hint">(${esc(kind())})</span></h2>
    <p class="hint">A layout is which panels this one has and whether each is enabled, disabled or on demand. One is active; keep up to ${META.max_alternatives} others to switch to.</p>
    <div class="row" style="margin:12px 0">
      <label class="hint">Active layout</label>
      <select id="layoutSel" style="width:auto">${names.map((n) => opt(n, n, dr.active)).join("")}</select>
      <button class="btn" id="newLayout" ${names.length >= 1 + META.max_alternatives ? "disabled" : ""}>New layout (copy)</button>
      <button class="btn" id="renameLayout">Rename</button>
      <button class="btn danger" id="delLayout" ${names.length <= 1 ? "disabled" : ""}>Delete</button>
      <button class="btn primary" id="saveLayouts">Save</button>
    </div>
    <table><tr><th>Panel</th><th>Type</th><th>State in “${esc(dr.active)}”</th><th></th></tr>
    ${[...applicable.values()].map((t) => {
      const st = lay.panels[t.id] || t.default_state || "enabled";
      const viaRule = d.templates.some((x) => x.id === t.id) && !Object.keys(lay.panels).includes(t.id);
      return `<tr><td>${esc(t.name || t.id)}</td><td class="hint">${esc(TYPE_LABEL[t.type] || t.type)}</td>
        <td><select data-state="${esc(t.id)}" style="width:auto">${META.states.map((s) => opt(s, STATE_LABEL[s], st)).join("")}</select></td>
        <td class="hint">${viaRule ? "assigned by the template" : ""}</td></tr>`;
    }).join("")}
    </table>
    <div class="row" style="margin-top:12px"><label class="hint">Add a panel just for this one</label>
      <select id="addPanel" style="width:auto"><option value="">…</option>${others.map((t) => opt(t.id, t.name || t.id, "")).join("")}</select></div>`;
  el.onchange = (e) => {
    if (e.target.id === "layoutSel") { dr.active = e.target.value; return drawManage(); }
    if (e.target.dataset.state) { lay.panels[e.target.dataset.state] = e.target.value; }
    if (e.target.id === "addPanel" && e.target.value) { lay.panels[e.target.value] = "enabled"; drawManage(); }
  };
  el.onclick = async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.id === "newLayout") {
      let n = names.length + 1, name = `Layout ${n}`; while (dr.layouts[name]) name = `Layout ${++n}`;
      name = prompt("Name of the new layout (a copy of this one):", name); if (!name || dr.layouts[name]) return;
      dr.layouts[name] = JSON.parse(JSON.stringify(lay)); dr.active = name; drawManage();
    }
    if (b.id === "renameLayout") {
      const name = prompt("New name:", dr.active); if (!name || name === dr.active || dr.layouts[name]) return;
      dr.layouts[name] = dr.layouts[dr.active]; delete dr.layouts[dr.active]; dr.active = name; drawManage();
    }
    if (b.id === "delLayout") { if (!confirm(`Delete the layout "${dr.active}"?`)) return; delete dr.layouts[dr.active]; dr.active = Object.keys(dr.layouts)[0]; drawManage(); }
    if (b.id === "saveLayouts") {
      // write every applicable panel's state into the layouts, so what was shown is what gets saved
      for (const l of Object.values(dr.layouts)) for (const t of d.templates) l.panels[t.id] ||= t.default_state || "enabled";
      try { manage.data = await api.saveLayouts(kind(), entity(), dr); toast("Layouts saved."); drawManage(); }
      catch (err) { toast(err.message, true); }
    }
  };
}

// ---- wiring ---------------------------------------------------------------------------------------------------------
$("#tabs").onclick = (e) => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p.dataset.pane === b.dataset.tab));
  if (b.dataset.tab === "manage") renderManage();
};
$("#tplList").onclick = (e) => { const it = e.target.closest(".item"); if (it) select(it.dataset.id); };
$("#newTypes").innerHTML = Object.entries(TYPE_LABEL).map(([k, l]) => `<button class="btn" data-type="${k}">${l}</button>`).join("");
$("#newTypes").onclick = (e) => { const b = e.target.closest("button"); if (b) newOfType(b.dataset.type); };
$("#kindSel").onchange = loadEntities;
$("#entitySel").onchange = () => { view = {}; feed = new api.PanelFeed(); drawPreview(true); renderManage(); };

(async () => {
  await loadTemplates();
  await loadEntities();
  const params = new URLSearchParams(location.search);
  if (params.get("kind")) { $("#kindSel").value = params.get("kind"); await loadEntities(); }
  if (params.get("id")) { $("#entitySel").value = params.get("id"); renderManage(); }
})();
