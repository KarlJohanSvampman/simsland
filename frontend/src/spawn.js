// spawn.js — Spawn tab: a table of character instances (existing + new
// draft rows) on the left, a draggable/pannable/zoomable SVG family-tree
// view of whichever row is selected on the right.
//
// Everything here is STAGED: adding a table row does not spawn a
// character, and dragging a tree connection does not touch the live
// relation graph, until "Save" is clicked. This mirrors neither
// Character Creator (which saves template edits immediately) nor the
// World Editor (which edits a client-side buffer and posts it back in
// one shot) — it's closer to the World Editor's model, just scoped to
// characters/relations instead of tiles/props.
//
// Relation vocabulary matches systems/family.py::INVERSE exactly (see
// backend/api/editor.py's new /family_relation endpoints, added
// alongside this page) — "a_to_b" semantics: relation_type is A's
// relation TO B (e.g. "parent" means A is B's parent).

const SIM_ID = "default";

const RELATION_TYPES = [
  { value: "parent",          label: "Parent of" },
  { value: "child",           label: "Child of" },
  { value: "sibling",         label: "Sibling of" },
  { value: "half_sibling",    label: "Half-sibling of" },
  { value: "spouse",          label: "Spouse of" },
  { value: "ex_spouse",       label: "Ex-spouse of" },
  { value: "grandparent",     label: "Grandparent of" },
  { value: "grandchild",      label: "Grandchild of" },
  { value: "aunt_uncle",      label: "Aunt/Uncle of" },
  { value: "niece_nephew",    label: "Niece/Nephew of" },
  { value: "cousin",          label: "Cousin of" },
  { value: "step_parent",     label: "Step-parent of" },
  { value: "step_child",      label: "Step-child of" },
  { value: "adoptive_parent", label: "Adoptive parent of" },
  { value: "adoptive_child",  label: "Adoptive child of" },
  { value: "guardian",        label: "Guardian of" },
  { value: "ward",            label: "Ward of" },
];

// A's generation relative to B, for relation "A is <relation> of B" —
// drives the tree's initial top-down layout (negative = above/older).
const GEN_DELTA = {
  parent: -1, child: 1,
  grandparent: -2, grandchild: 2,
  aunt_uncle: -1, niece_nephew: 1,
  step_parent: -1, step_child: 1,
  adoptive_parent: -1, adoptive_child: 1,
  guardian: -1, ward: 1,
  sibling: 0, half_sibling: 0, spouse: 0, ex_spouse: 0, cousin: 0,
};

const state = {
  templates: {},
  households: [],
  liveCharacters: [],  // [{id,name,sex,age,age_group,household_id,family_id,template}]
  liveEdges: [],       // [{a,b,relation}]
  draftRows: [],       // [{localId,template,name,household_id}]
  pendingOps: [],       // [{id,op:'add'|'remove',a,b,relation,sourceRowSeed?}]
  selected: null,       // node id (real char id, or "draft:<localId>")
  nodePos: {},          // nodeId -> {x,y}  (session-only layout, survives redraws)
  view: { x: 0, y: 0, scale: 1 },
  householdFilter: null, // household id, or "__none__" for unassigned characters
};

const NO_HOUSEHOLD = "__none__";

let _localIdSeed = 1;

// =========================================================
// DATA LOADING
// =========================================================

async function loadAll() {
  setStatus("Loading...");
  const [defsRes, householdsRes, graphRes] = await Promise.all([
    fetch(`/api/editor/definitions?sim_id=${SIM_ID}`),
    fetch(`/api/household/list?sim_id=${SIM_ID}`),
    fetch(`/api/editor/family_graph?sim_id=${SIM_ID}`),
  ]);
  const defs = await defsRes.json();
  const householdsData = await householdsRes.json();
  const graph = await graphRes.json();

  state.templates = defs.character_templates || {};
  state.households = householdsData.households || [];
  state.liveCharacters = graph.characters || [];
  state.liveEdges = graph.edges || [];

  if (state.householdFilter === null) {
    state.householdFilter = state.households.length ? state.households[0].id : NO_HOUSEHOLD;
  }

  renderHouseholdFilter();
  renderTable();
  renderTree();
  setStatus("Ready");
}

function renderHouseholdFilter() {
  const sel = document.getElementById("householdFilter");
  const prev = state.householdFilter;
  sel.innerHTML = "";
  for (const h of state.households) {
    const opt = document.createElement("option");
    opt.value = h.id;
    opt.textContent = h.name;
    sel.appendChild(opt);
  }
  const noneOpt = document.createElement("option");
  noneOpt.value = NO_HOUSEHOLD;
  noneOpt.textContent = "(no household)";
  sel.appendChild(noneOpt);
  sel.value = prev;
}

function templateLabel(templateId) {
  const t = state.templates[templateId];
  return (t && t.name) || templateId || "(no template)";
}

function templateSex(templateId) {
  const t = state.templates[templateId];
  return t ? t.sex : null;
}

// =========================================================
// TABLE
// =========================================================

function addRow() {
  state.draftRows.push({
    localId: _localIdSeed++,
    template: Object.keys(state.templates)[0] || "",
    name: "",
    household_id: state.householdFilter === NO_HOUSEHOLD ? "" : state.householdFilter,
  });
  renderTable();
}

function removeRow(localId) {
  const nodeId = "draft:" + localId;
  state.draftRows = state.draftRows.filter(r => r.localId !== localId);
  state.pendingOps = state.pendingOps.filter(op => op.a !== nodeId && op.b !== nodeId);
  delete state.nodePos[nodeId];
  if (state.selected === nodeId) state.selected = null;
  renderTable();
  renderTree();
}

function setRowSeed(localId, relation, targetId) {
  const nodeId = "draft:" + localId;
  state.pendingOps = state.pendingOps.filter(op => op.sourceRowSeed !== localId);
  if (relation && targetId) {
    state.pendingOps.push({
      id: "seed:" + localId, op: "add", a: nodeId, b: targetId,
      relation, sourceRowSeed: localId,
    });
  }
  renderTree();
  renderPendingEdits();
}

function renderTable() {
  const tbody = document.getElementById("spawnTableBody");
  tbody.innerHTML = "";

  const filterVal = state.householdFilter;
  const matchesFilter = hid => (hid || NO_HOUSEHOLD) === filterVal;

  const visibleCharacters = state.liveCharacters.filter(c => matchesFilter(c.household_id));
  const visibleDraftRows = state.draftRows.filter(r => matchesFilter(r.household_id));

  for (const c of visibleCharacters) {
    const tr = document.createElement("tr");
    tr.className = "spawnRow";
    if (state.selected === c.id) tr.classList.add("selected");
    tr.style.cursor = "pointer";
    const hh = state.households.find(h => h.id === c.household_id);
    tr.innerHTML = `
      <td class="rowSelectDot">${state.selected === c.id ? "●" : "○"}</td>
      <td>${escapeHtml(templateLabel(c.template))}</td>
      <td>${escapeHtml(c.name)}</td>
      <td>${escapeHtml(hh ? hh.name : "—")}</td>
      <td style="color:#778;">existing</td>
      <td></td>
    `;
    tr.addEventListener("click", () => selectNode(c.id));
    tbody.appendChild(tr);
  }

  for (const row of visibleDraftRows) {
    const nodeId = "draft:" + row.localId;
    const tr = document.createElement("tr");
    tr.className = "spawnRow";
    if (state.selected === nodeId) tr.classList.add("selected");

    const tdTemplate = document.createElement("td");
    const templateSel = document.createElement("select");
    for (const tid of Object.keys(state.templates)) {
      const opt = document.createElement("option");
      opt.value = tid;
      opt.textContent = templateLabel(tid);
      if (tid === row.template) opt.selected = true;
      templateSel.appendChild(opt);
    }
    templateSel.addEventListener("click", e => e.stopPropagation());
    templateSel.addEventListener("change", () => { row.template = templateSel.value; renderTree(); });
    tdTemplate.appendChild(templateSel);

    const tdName = document.createElement("td");
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.placeholder = "(optional)";
    nameInput.value = row.name;
    nameInput.addEventListener("click", e => e.stopPropagation());
    nameInput.addEventListener("input", () => { row.name = nameInput.value; renderTree(); });
    tdName.appendChild(nameInput);

    const tdHousehold = document.createElement("td");
    const hhSel = document.createElement("select");
    const noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "— none —";
    hhSel.appendChild(noneOpt);
    for (const h of state.households) {
      const opt = document.createElement("option");
      opt.value = h.id;
      opt.textContent = h.name;
      if (h.id === row.household_id) opt.selected = true;
      hhSel.appendChild(opt);
    }
    hhSel.addEventListener("click", e => e.stopPropagation());
    hhSel.addEventListener("change", () => { row.household_id = hhSel.value; renderTable(); });
    tdHousehold.appendChild(hhSel);

    const tdSeed = document.createElement("td");
    tdSeed.style.display = "flex";
    tdSeed.style.gap = "3px";
    const relSel = document.createElement("select");
    relSel.style.flex = "1";
    const relNone = document.createElement("option");
    relNone.value = "";
    relNone.textContent = "unrelated";
    relSel.appendChild(relNone);
    for (const rt of RELATION_TYPES) {
      const opt = document.createElement("option");
      opt.value = rt.value;
      opt.textContent = rt.label;
      relSel.appendChild(opt);
    }
    const targetSel = document.createElement("select");
    targetSel.style.flex = "1";
    const targetNone = document.createElement("option");
    targetNone.value = "";
    targetNone.textContent = "(who?)";
    targetSel.appendChild(targetNone);
    for (const c of state.liveCharacters) {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name;
      targetSel.appendChild(opt);
    }
    for (const other of state.draftRows) {
      if (other.localId === row.localId) continue;
      const opt = document.createElement("option");
      opt.value = "draft:" + other.localId;
      opt.textContent = "(new) " + (other.name || templateLabel(other.template));
      targetSel.appendChild(opt);
    }
    // Restore whatever seed is already staged for this row -- these
    // selects are rebuilt from scratch on every renderTable() (e.g.
    // after selecting a row via its dot), and the seed itself only
    // lives in state.pendingOps, not on `row`, so without this they'd
    // silently reset to blank while the actual staged relation (visible
    // in the tree) stayed intact.
    const existingSeed = state.pendingOps.find(op => op.sourceRowSeed === row.localId);
    if (existingSeed) {
      relSel.value = existingSeed.relation;
      targetSel.value = existingSeed.b;
    }

    const applySeed = () => setRowSeed(row.localId, relSel.value, targetSel.value);
    relSel.addEventListener("click", e => e.stopPropagation());
    targetSel.addEventListener("click", e => e.stopPropagation());
    relSel.addEventListener("change", applySeed);
    targetSel.addEventListener("change", applySeed);
    tdSeed.appendChild(relSel);
    tdSeed.appendChild(targetSel);

    const tdRemove = document.createElement("td");
    const removeBtn = document.createElement("button");
    removeBtn.className = "rowRemoveBtn";
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", e => { e.stopPropagation(); removeRow(row.localId); });
    tdRemove.appendChild(removeBtn);

    // Every other cell in a draft row is a live form control (stops
    // click propagation so opening a dropdown / focusing the name field
    // doesn't also trigger selectNode() -> renderTable()'s full innerHTML
    // rebuild mid-interaction, which would drop focus/close the
    // dropdown). This dot is the one plain, always-clickable way to
    // select a draft row and view its tree.
    const tdSelect = document.createElement("td");
    tdSelect.className = "rowSelectDot";
    tdSelect.textContent = state.selected === nodeId ? "●" : "○";
    tdSelect.addEventListener("click", () => selectNode(nodeId));

    tr.appendChild(tdSelect);
    tr.appendChild(tdTemplate);
    tr.appendChild(tdName);
    tr.appendChild(tdHousehold);
    tr.appendChild(tdSeed);
    tr.appendChild(tdRemove);
    tbody.appendChild(tr);
  }
}

function renderPendingEdits() {
  const list = document.getElementById("pendingEditsList");
  list.innerHTML = "";
  const nonSeedOps = state.pendingOps.filter(op => !op.sourceRowSeed);
  if (!nonSeedOps.length) {
    const empty = document.createElement("div");
    empty.style.cssText = "color:#667;font-size:11px;";
    empty.textContent = "None — drag a connection in the tree to add one.";
    list.appendChild(empty);
    return;
  }
  for (const op of nonSeedOps) {
    const row = document.createElement("div");
    row.className = "pendingEditRow";
    const aName = nodeLabel(op.a);
    const bName = nodeLabel(op.b);
    if (op.op === "add") {
      row.innerHTML = `<span class="pendingAdd">+ ${escapeHtml(aName)} — ${escapeHtml(relationLabel(op.relation))} — ${escapeHtml(bName)}</span>`;
    } else {
      row.innerHTML = `<span class="pendingRemove">✂ cut: ${escapeHtml(aName)} — ${escapeHtml(bName)}</span>`;
    }
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "pendingCancel";
    cancelBtn.textContent = "undo";
    cancelBtn.addEventListener("click", () => {
      state.pendingOps = state.pendingOps.filter(o => o.id !== op.id);
      renderTree();
      renderPendingEdits();
    });
    row.appendChild(cancelBtn);
    list.appendChild(row);
  }
}

function relationLabel(value) {
  const rt = RELATION_TYPES.find(r => r.value === value);
  return rt ? rt.label.replace(/ of$/, "") : value;
}

function nodeLabel(nodeId) {
  if (nodeId.startsWith("draft:")) {
    const localId = parseInt(nodeId.slice(6), 10);
    const row = state.draftRows.find(r => r.localId === localId);
    return row ? "(new) " + (row.name || templateLabel(row.template)) : nodeId;
  }
  const c = state.liveCharacters.find(c => c.id === nodeId);
  return c ? c.name : nodeId;
}

// =========================================================
// SELECTION
// =========================================================

function selectNode(nodeId) {
  state.selected = nodeId;
  renderTable();
  renderTree();
  const title = document.getElementById("treeTitle");
  title.textContent = "Family tree — " + nodeLabel(nodeId);
}

// =========================================================
// TREE: effective graph (live + pending overlaid)
// =========================================================

function effectiveNodes() {
  const nodes = state.liveCharacters.map(c => ({
    id: c.id, name: c.name, sex: c.sex, isDraft: false,
  }));
  for (const row of state.draftRows) {
    nodes.push({
      id: "draft:" + row.localId,
      name: row.name || ("(new) " + templateLabel(row.template)),
      sex: templateSex(row.template),
      isDraft: true,
    });
  }
  return nodes;
}

function effectiveEdges() {
  const removedKeys = new Set(
    state.pendingOps.filter(op => op.op === "remove").map(op => op.a + "|" + op.b)
  );
  const edges = state.liveEdges.map(e => ({
    id: e.a + "|" + e.b, a: e.a, b: e.b, relation: e.relation,
    status: removedKeys.has(e.a + "|" + e.b) ? "pending_remove" : "live",
  }));
  for (const op of state.pendingOps) {
    if (op.op === "add") {
      edges.push({ id: op.id, a: op.a, b: op.b, relation: op.relation, status: "pending_add" });
    }
  }
  return edges;
}

// BFS from state.selected across the effective graph, assigning a
// generation (row) to every reachable node.
function computeVisibleSubgraph() {
  const nodes = effectiveNodes();
  const edges = effectiveEdges();
  const byId = {};
  for (const n of nodes) byId[n.id] = n;

  if (!state.selected || !byId[state.selected]) return { nodes: [], edges: [] };

  const gen = { [state.selected]: 0 };
  const queue = [state.selected];
  const visited = new Set([state.selected]);
  while (queue.length) {
    const cur = queue.shift();
    for (const e of edges) {
      let other = null, delta = 0;
      if (e.a === cur) { other = e.b; delta = GEN_DELTA[e.relation] ?? 0; }
      else if (e.b === cur) { other = e.a; delta = -(GEN_DELTA[e.relation] ?? 0); }
      if (other && !visited.has(other) && byId[other]) {
        visited.add(other);
        gen[other] = gen[cur] + delta;
        queue.push(other);
      }
    }
  }

  const visibleNodes = [...visited].map(id => ({ ...byId[id], gen: gen[id] }));
  const visibleEdges = edges.filter(e => visited.has(e.a) && visited.has(e.b));
  return { nodes: visibleNodes, edges: visibleEdges };
}

function layoutNodes(nodes) {
  const byGen = {};
  for (const n of nodes) {
    (byGen[n.gen] = byGen[n.gen] || []).push(n);
  }
  const SPACING_X = 170, SPACING_Y = 150;
  for (const genKey of Object.keys(byGen)) {
    const row = byGen[genKey];
    row.forEach((n, i) => {
      if (!state.nodePos[n.id]) {
        state.nodePos[n.id] = { x: i * SPACING_X, y: Number(genKey) * SPACING_Y };
      }
    });
  }
}

// =========================================================
// SVG RENDERING
// =========================================================

const SVG_NS = "http://www.w3.org/2000/svg";
const BOX_W = 130, BOX_H = 54;

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function boxColor(sex, isDraft) {
  if (sex === "female") return isDraft ? "#a8637f" : "#e58bb0";
  if (sex === "male") return isDraft ? "#4f7ba0" : "#6fa8dc";
  return "#999";
}

function edgeColor(status) {
  if (status === "pending_add") return "#7fd88f";
  if (status === "pending_remove") return "#e88888";
  return "#8899aa";
}

let dragState = null; // {type:'pan'|'node'|'handle'|'cut', ...}

function renderTree() {
  const svg = document.getElementById("treeSvg");
  const viewport = document.getElementById("viewport");
  viewport.innerHTML = "";
  viewport.setAttribute(
    "transform",
    `translate(${state.view.x},${state.view.y}) scale(${state.view.scale})`
  );

  const { nodes, edges } = computeVisibleSubgraph();
  layoutNodes(nodes);
  renderPendingEdits();

  if (!nodes.length) return;

  // Edges first (under the boxes)
  for (const e of edges) {
    const pa = state.nodePos[e.a], pb = state.nodePos[e.b];
    if (!pa || !pb) continue;
    const ax = pa.x + BOX_W / 2, ay = pa.y + BOX_H / 2;
    const bx = pb.x + BOX_W / 2, by = pb.y + BOX_H / 2;

    const line = svgEl("line", {
      x1: ax, y1: ay, x2: bx, y2: by,
      stroke: edgeColor(e.status), "stroke-width": 2,
      "stroke-dasharray": e.status === "live" ? "0" : "6,4",
    });
    viewport.appendChild(line);

    const midx = (ax + bx) / 2, midy = (ay + by) / 2;
    const label = svgEl("text", {
      x: midx, y: midy - 4, fill: "#8899aa", "font-size": "10",
      "text-anchor": "middle", "pointer-events": "none",
    });
    label.textContent = relationLabel(e.relation);
    viewport.appendChild(label);

    // Cut handles, 25% in from each endpoint.
    for (const [hx, hy, endIsA] of [
      [ax + (bx - ax) * 0.25, ay + (by - ay) * 0.25, true],
      [ax + (bx - ax) * 0.75, ay + (by - ay) * 0.75, false],
    ]) {
      const handle = svgEl("circle", {
        cx: hx, cy: hy, r: 5, fill: edgeColor(e.status),
        stroke: "#111", "stroke-width": 1, style: "cursor:pointer;",
      });
      handle.addEventListener("mousedown", ev => startCutDrag(ev, e, endIsA));
      viewport.appendChild(handle);
    }
  }

  // Boxes
  for (const n of nodes) {
    const pos = state.nodePos[n.id];
    const g = svgEl("g", { transform: `translate(${pos.x},${pos.y})`, style: "cursor:pointer;" });

    const rect = svgEl("rect", {
      width: BOX_W, height: BOX_H, rx: 8, ry: 8,
      fill: boxColor(n.sex, n.isDraft),
      stroke: n.id === state.selected ? "#fff" : "#222",
      "stroke-width": n.id === state.selected ? 2.5 : 1,
      "stroke-dasharray": n.isDraft ? "5,3" : "0",
    });
    g.appendChild(rect);

    const text = svgEl("text", {
      x: BOX_W / 2, y: BOX_H / 2 + 4, fill: "#12151a",
      "font-size": "12", "font-weight": "bold",
      "text-anchor": "middle", "pointer-events": "none",
    });
    text.textContent = truncate(n.name, 18);
    g.appendChild(text);

    // Connector handle (bottom-center) — drag out to start a new edge.
    const handle = svgEl("circle", {
      cx: BOX_W / 2, cy: BOX_H, r: 6, fill: "#fff",
      stroke: "#333", "stroke-width": 1, style: "cursor:crosshair;",
    });
    handle.addEventListener("mousedown", ev => startConnectDrag(ev, n.id));
    g.appendChild(handle);

    g.addEventListener("mousedown", ev => startNodeDrag(ev, n.id));
    viewport.appendChild(g);
  }
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function svgPoint(svg, clientX, clientY) {
  const rect = svg.getBoundingClientRect();
  const localX = clientX - rect.left, localY = clientY - rect.top;
  return {
    x: (localX - state.view.x) / state.view.scale,
    y: (localY - state.view.y) / state.view.scale,
  };
}

// ── Panning + zoom ──────────────────────────────────────

function setupCanvasInteractions() {
  const svg = document.getElementById("treeSvg");

  svg.addEventListener("mousedown", ev => {
    if (dragState) return; // a box/handle already claimed this mousedown
    if (ev.target !== svg && ev.target.id !== "viewport") return;
    dragState = { type: "pan", startX: ev.clientX, startY: ev.clientY, origX: state.view.x, origY: state.view.y };
    svg.classList.add("panning");
  });

  window.addEventListener("mousemove", ev => {
    if (!dragState) return;
    if (dragState.type === "pan") {
      state.view.x = dragState.origX + (ev.clientX - dragState.startX);
      state.view.y = dragState.origY + (ev.clientY - dragState.startY);
      applyViewTransform();
    } else if (dragState.type === "node") {
      const p = svgPoint(svg, ev.clientX, ev.clientY);
      state.nodePos[dragState.nodeId] = { x: p.x - BOX_W / 2, y: p.y - BOX_H / 2 };
      dragState.moved = true;
      renderTree();
    } else if (dragState.type === "connect") {
      const p = svgPoint(svg, ev.clientX, ev.clientY);
      updateTempLine(dragState.fromId, p.x, p.y);
    } else if (dragState.type === "cut") {
      const p = svgPoint(svg, ev.clientX, ev.clientY);
      updateTempLine(dragState.fixedNodeId, p.x, p.y);
    }
  });

  window.addEventListener("mouseup", ev => {
    if (!dragState) return;
    svg.classList.remove("panning");

    if (dragState.type === "node") {
      if (!dragState.moved) selectNode(dragState.nodeId);
      removeTempLine();
    } else if (dragState.type === "connect") {
      const p = svgPoint(svg, ev.clientX, ev.clientY);
      const targetId = hitTestNode(p.x, p.y, dragState.fromId);
      removeTempLine();
      if (targetId) openRelationPopup(ev.clientX, ev.clientY, dragState.fromId, targetId);
    } else if (dragState.type === "cut") {
      removeTempLine();
      applyCut(dragState.edge);
    }
    dragState = null;
  });

  svg.addEventListener("wheel", ev => {
    ev.preventDefault();
    const factor = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
    state.view.scale = Math.min(3, Math.max(0.2, state.view.scale * factor));
    applyViewTransform();
  }, { passive: false });

  document.getElementById("btnResetView").addEventListener("click", () => {
    state.view = { x: 0, y: 0, scale: 1 };
    applyViewTransform();
  });
}

function applyViewTransform() {
  document.getElementById("viewport").setAttribute(
    "transform",
    `translate(${state.view.x},${state.view.y}) scale(${state.view.scale})`
  );
}

function startNodeDrag(ev, nodeId) {
  ev.stopPropagation();
  dragState = { type: "node", nodeId, moved: false };
}

function startConnectDrag(ev, fromId) {
  ev.stopPropagation();
  const pos = state.nodePos[fromId];
  dragState = { type: "connect", fromId, startX: pos.x + BOX_W / 2, startY: pos.y + BOX_H };
}

function startCutDrag(ev, edge, endIsA) {
  ev.stopPropagation();
  const fixedId = endIsA ? edge.b : edge.a;
  const pos = state.nodePos[fixedId];
  dragState = {
    type: "cut", edge, fixedNodeId: fixedId,
    startX: pos.x + BOX_W / 2, startY: pos.y + BOX_H / 2,
  };
}

let tempLineEl = null;

function updateTempLine(anchorNodeId, mx, my) {
  const viewport = document.getElementById("viewport");
  const start = dragState.type === "connect"
    ? { x: dragState.startX, y: dragState.startY }
    : { x: dragState.startX, y: dragState.startY };
  if (!tempLineEl) {
    tempLineEl = svgEl("line", { stroke: "#ffd166", "stroke-width": 2, "stroke-dasharray": "4,3" });
    viewport.appendChild(tempLineEl);
  }
  tempLineEl.setAttribute("x1", start.x);
  tempLineEl.setAttribute("y1", start.y);
  tempLineEl.setAttribute("x2", mx);
  tempLineEl.setAttribute("y2", my);
}

function removeTempLine() {
  if (tempLineEl) { tempLineEl.remove(); tempLineEl = null; }
}

function hitTestNode(x, y, excludeId) {
  for (const [id, pos] of Object.entries(state.nodePos)) {
    if (id === excludeId) continue;
    if (x >= pos.x && x <= pos.x + BOX_W && y >= pos.y && y <= pos.y + BOX_H) return id;
  }
  return null;
}

function applyCut(edge) {
  if (edge.status === "pending_add") {
    // Never committed — just drop the staged op (and clear a row's seed
    // if that's where it came from).
    state.pendingOps = state.pendingOps.filter(op => op.id !== edge.id);
  } else {
    state.pendingOps.push({ id: "cut:" + edge.id, op: "remove", a: edge.a, b: edge.b });
  }
  renderTree();
  renderTable();
}

// ── Relation popup (used when a connect-drag lands on a valid target) ──

function openRelationPopup(clientX, clientY, fromId, toId) {
  const popup = document.getElementById("relationPopup");
  const select = document.getElementById("relationPopupSelect");
  select.innerHTML = "";
  for (const rt of RELATION_TYPES) {
    const opt = document.createElement("option");
    opt.value = rt.value;
    opt.textContent = `${nodeLabel(fromId)} is the ${rt.label.replace(/ of$/, "").toLowerCase()} ${nodeLabel(toId)}`;
    select.appendChild(opt);
  }
  popup.style.left = clientX + "px";
  popup.style.top = clientY + "px";
  popup.style.display = "block";

  const confirmBtn = popup.querySelector(".popupConfirm");
  const cancelBtn = popup.querySelector(".popupCancel");
  const close = () => { popup.style.display = "none"; confirmBtn.onclick = null; cancelBtn.onclick = null; };
  confirmBtn.onclick = () => {
    state.pendingOps.push({
      id: "add:" + fromId + ":" + toId + ":" + Date.now(),
      op: "add", a: fromId, b: toId, relation: select.value,
    });
    close();
    renderTree();
    renderTable();
  };
  cancelBtn.onclick = close;
}

// =========================================================
// SAVE
// =========================================================

async function save() {
  const btn = document.getElementById("btnSave");
  btn.disabled = true;
  setStatus("Saving...");

  try {
    const idMap = {};
    for (const row of state.draftRows) {
      const res = await fetch("/api/editor/spawn_character", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sim_id: SIM_ID,
          template: row.template,
          name: row.name || undefined,
          household_id: row.household_id || undefined,
          x: Math.floor(Math.random() * 6), y: Math.floor(Math.random() * 6),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to spawn character");
      idMap["draft:" + row.localId] = data.id;
    }

    const resolve = id => (id.startsWith("draft:") ? idMap[id] : id);

    for (const op of state.pendingOps) {
      const a = resolve(op.a), b = resolve(op.b);
      if (!a || !b) continue;
      if (op.op === "add") {
        const res = await fetch("/api/editor/family_relation", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sim_id: SIM_ID, a_id: a, b_id: b, relation_type: op.relation }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || "Failed to set relation");
      } else {
        const res = await fetch("/api/editor/family_relation/remove", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sim_id: SIM_ID, a_id: a, b_id: b }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || "Failed to cut relation");
      }
    }

    state.draftRows = [];
    state.pendingOps = [];
    state.nodePos = {};
    state.selected = null;
    await loadAll();
    setStatus(`Saved. ${Object.keys(idMap).length} spawned.`);
  } catch (err) {
    setStatus("Error: " + err.message);
  } finally {
    btn.disabled = false;
  }
}

function setStatus(msg) {
  document.getElementById("statusBar").textContent = msg;
}

// =========================================================
// INIT
// =========================================================

document.getElementById("btnAddRow").addEventListener("click", addRow);
document.getElementById("btnSave").addEventListener("click", save);
document.getElementById("householdFilter").addEventListener("change", ev => {
  state.householdFilter = ev.target.value;
  renderTable();
});
setupCanvasInteractions();
loadAll();
