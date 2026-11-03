// Inspector "Movement" tab: how far the selected character moved every 15 sim-seconds while on the move, with each
// activity's start / end / timeout marked on the same time axis -- the record of how often, and where, they get stuck.
// Data: c.move_log from backend/systems/movement_log.py.

const W = 560, H = 190, PAD_L = 34, PAD_R = 8, PAD_T = 10, PAD_B = 22;
const EVENT_COLORS = { start: "#3fb950", end: "#8b949e", timeout: "#f85149" };
const STUCK_DISTANCE = 0.5;

function esc(s) {
  return String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
}

function clock(tick, nowTick) {
  const mins = Math.round((nowTick - tick) / 60);
  return mins <= 0 ? "now" : `${mins}m ago`;
}

export function renderMovementTab(c, nowTick) {
  const el = document.getElementById("viewerMovementTab");
  if (!el) return;
  const log = c.move_log || {};
  const samples = log.samples || [];
  const events = log.events || [];
  if (!samples.length && !events.length) {
    el.innerHTML = `<div class="viewerEmpty">No movement recorded yet -- samples are taken every 15 seconds while ` +
                   `${esc(c.name || "they")} is on the move.</div>` + renderPathPlans(c, nowTick);
    return;
  }
  const now = nowTick ?? Math.max(...samples.map(s => s[0]), ...events.map(e => e[0]));
  const t0 = Math.min(...samples.map(s => s[0]), ...events.map(e => e[0]));
  const span = Math.max(60, now - t0);
  const maxD = Math.max(1, ...samples.map(s => s[1]));
  const x = t => PAD_L + (t - t0) / span * (W - PAD_L - PAD_R);
  const y = d => PAD_T + (1 - d / maxD) * (H - PAD_T - PAD_B);

  const parts = [];
  // axes + stuck threshold
  parts.push(`<line x1="${PAD_L}" y1="${H - PAD_B}" x2="${W - PAD_R}" y2="${H - PAD_B}" stroke="#555"/>`);
  parts.push(`<line x1="${PAD_L}" y1="${PAD_T}" x2="${PAD_L}" y2="${H - PAD_B}" stroke="#555"/>`);
  parts.push(`<line x1="${PAD_L}" y1="${y(STUCK_DISTANCE)}" x2="${W - PAD_R}" y2="${y(STUCK_DISTANCE)}" stroke="#f85149" stroke-dasharray="3 3" opacity="0.5"><title>stuck below ${STUCK_DISTANCE} tiles per 15 s</title></line>`);
  parts.push(`<text x="${PAD_L - 4}" y="${PAD_T + 8}" fill="#aaa" font-size="10" text-anchor="end">${maxD.toFixed(1)}</text>`);
  parts.push(`<text x="${PAD_L - 4}" y="${H - PAD_B}" fill="#aaa" font-size="10" text-anchor="end">0</text>`);
  parts.push(`<text x="${PAD_L}" y="${H - 6}" fill="#aaa" font-size="10">${clock(t0, now)}</text>`);
  parts.push(`<text x="${W - PAD_R}" y="${H - 6}" fill="#aaa" font-size="10" text-anchor="end">now</text>`);
  // event markers
  for (const [t, kind, label] of events) {
    if (t < t0) continue;
    const col = EVENT_COLORS[kind] || "#888";
    parts.push(`<line x1="${x(t)}" y1="${PAD_T}" x2="${x(t)}" y2="${H - PAD_B}" stroke="${col}" stroke-width="${kind === "timeout" ? 2 : 1}" opacity="0.8"><title>${esc(kind)}: ${esc(label)} (${clock(t, now)})</title></line>`);
  }
  // the distance line, broken where they weren't on the move
  let path = "", pen = false;
  for (const [t, d, moving] of samples) {
    if (!moving) { pen = false; continue; }
    path += `${pen ? "L" : "M"}${x(t).toFixed(1)},${y(d).toFixed(1)} `;
    pen = true;
  }
  if (path) parts.push(`<path d="${path}" fill="none" stroke="#58a6ff" stroke-width="1.5"/>`);
  for (const [t, d, moving] of samples) {
    if (!moving) continue;
    const stuck = d < STUCK_DISTANCE;
    parts.push(`<circle cx="${x(t).toFixed(1)}" cy="${y(d).toFixed(1)}" r="${stuck ? 2.6 : 1.6}" fill="${stuck ? "#f85149" : "#58a6ff"}"><title>${d} tiles in 15 s (${clock(t, now)})${stuck ? " -- stuck" : ""}</title></circle>`);
  }

  const moving = log.moving_samples || 0, stuck = log.stuck_samples || 0;
  const pct = moving ? Math.round(100 * stuck / moving) : 0;
  const timeouts = events.filter(e => e[1] === "timeout").length;
  const recent = events.slice(-8).reverse().map(([t, kind, label]) =>
    `<div class="viewerCard"><span style="color:${EVENT_COLORS[kind] || "#888"}">${esc(kind)}</span> ${esc(label)} ` +
    `<span style="opacity:.6">${clock(t, now)}</span></div>`).join("");

  el.innerHTML =
    `<div class="viewerSection"><div class="viewerSectionTitle">Distance moved per 15 s</div>` +
    `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:rgba(255,255,255,0.03)">${parts.join("")}</svg>` +
    `<div style="font-size:11px;opacity:.8;margin-top:4px">` +
    `<span style="color:#58a6ff">●</span> moving &nbsp; <span style="color:#f85149">●</span> stuck (&lt; ${STUCK_DISTANCE} tiles) &nbsp; ` +
    `<span style="color:${EVENT_COLORS.start}">|</span> start &nbsp; <span style="color:${EVENT_COLORS.end}">|</span> end &nbsp; ` +
    `<span style="color:${EVENT_COLORS.timeout}">|</span> timeout</div></div>` +
    `<div class="viewerSection"><div class="viewerSectionTitle">Stuck: ${stuck} of ${moving} samples on the move (${pct}%), ${timeouts} timeouts</div>` +
    `${recent || '<div class="viewerEmpty">No activity events yet.</div>'}</div>` +
    renderPathPlans(c, now);
}

// ---- the planned route of the selected character, drawn in the scene ---------------------------------------------------
// c.route = [{type, tiles: [[x, y], ...]}, ...] (backend/systems/navigation.py), walked from route_segment_index /
// path_index; c.path_plans = the recent plans with why one failed (backend/systems/path_debug.py). Scene coordinates
// are the character's (x - 10, y - 7), the same mapping main.js uses for the models.

const ROUTE_Y = 0.06;
let _routeObjects = [];
let _routeKey = null;

function _clearRoute(scene) {
  for (const o of _routeObjects) {
    scene.remove(o);
    o.geometry?.dispose?.();
  }
  _routeObjects = [];
}

export function updateRouteOverlay(THREE, scene, state, selectedId) {
  const c = selectedId ? state.characters?.[selectedId] : null;
  const plans = c?.path_plans || [];
  const lastPlan = plans[plans.length - 1];
  const key = c ? JSON.stringify([c.route, c.route_segment_index, c.path_index, lastPlan?.tick, c.is_moving]) : null;
  if (key === _routeKey) return;
  _routeKey = key;
  _clearRoute(scene);
  if (!c) return;

  const pts = [new THREE.Vector3(c.x - 10, ROUTE_Y, c.y - 7)];
  const route = c.route || [];
  for (let s = c.route_segment_index || 0; s < route.length; s++) {
    const tiles = route[s].tiles || [];
    for (let i = (s === (c.route_segment_index || 0) ? (c.path_index || 0) : 0); i < tiles.length; i++) {
      const t = tiles[i];
      pts.push(new THREE.Vector3(t[0] - 10, ROUTE_Y, t[1] - 7));
    }
  }
  if (pts.length > 1) {
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
                                new THREE.LineBasicMaterial({ color: 0x58a6ff }));
    scene.add(line);
    _routeObjects.push(line);
    const end = new THREE.Mesh(new THREE.RingGeometry(0.18, 0.3, 24),
                               new THREE.MeshBasicMaterial({ color: 0x58a6ff, side: THREE.DoubleSide }));
    end.rotation.x = -Math.PI / 2;
    end.position.copy(pts[pts.length - 1]);
    scene.add(end);
    _routeObjects.push(end);
  }
  // the last plan failed: a red line to where they couldn't get to
  if (lastPlan && !lastPlan.ok && !["already_there"].includes(lastPlan.reason)) {
    const a = new THREE.Vector3(c.x - 10, ROUTE_Y, c.y - 7);
    const b = new THREE.Vector3(lastPlan.to[0] - 10, ROUTE_Y, lastPlan.to[1] - 7);
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]),
                                new THREE.LineDashedMaterial({ color: 0xf85149, dashSize: 0.3, gapSize: 0.2 }));
    line.computeLineDistances();
    scene.add(line);
    _routeObjects.push(line);
  }
}

export function renderPathPlans(c, nowTick) {
  const plans = (c.path_plans || []).slice().reverse();
  if (!plans.length) return "";
  const rows = plans.map(p => {
    const col = p.ok ? (p.reason === "ok" ? "#3fb950" : "#d29922") : (p.reason === "already_there" ? "#8b949e" : "#f85149");
    return `<div class="viewerCard"><span style="color:${col}">${p.ok ? "path" : "NO PATH"}</span> ` +
           `${esc(p.from.join(","))} → ${esc(p.to.join(","))} ` +
           `<span style="opacity:.7">${esc(p.reason.replace(/_/g, " "))}${p.ok ? `, ${p.tiles} tiles (${esc(p.segments.join(" + "))})` : ""}` +
           `${p.target_id ? `, for ${esc(p.target_id)}` : ""}</span> <span style="opacity:.6">${clock(p.tick, nowTick ?? p.tick)}</span></div>`;
  }).join("");
  return `<div class="viewerSection"><div class="viewerSectionTitle">Route plans (the current one is drawn on the map)</div>${rows}</div>`;
}
