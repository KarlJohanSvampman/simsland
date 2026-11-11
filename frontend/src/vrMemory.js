// src/vrMemory.js -- VR "Memory debug": a floating timeline (vrFloat.js frame: move, resize, lock, minimise) of every
// time a character's memory is touched (backend/systems/memory_trace.py, /admin/memtrace/{id}), one coloured lane per
// kind:
//
//   stored (short-term)      recalled (short-term)     recalled (long-term)
//   committed to long-term   aggregation (hourly)       forgotten
//
// Point at a mark to read it (which memories, who asked, the query, the summary...); trigger pins it. Right stick
// while pointing: ←/→ pan back in time, ↑/↓ zoom. It rolls with "now" (LIVE) until you pan; trigger on LIVE to go back.

import * as THREE from "three";

const PX_W = 1000, PX_H = 600;
const W_M = 0.95;
const POLL_S = 2;
const KEEP = 800;
const LANES = [
  ["stm_write", "stored (short-term)", "#3fb950"],
  ["stm_read", "recalled (short-term)", "#58a6ff"],
  ["ltm_read", "recalled (long-term)", "#bc8cff"],
  ["ltm_commit", "committed to long-term", "#f0883e"],
  ["aggregation", "aggregation", "#f778ba"],
  ["forget", "forgotten", "#8b949e"],
];
const LANE_OF = Object.fromEntries(LANES.map(([k], i) => [k, i]));
const L = { left: 230, right: 980, top: 70, laneH: 44, detailTop: 380 };
const fmtSpan = (s) => (s < 120 ? `${Math.round(s)} s` : s < 7200 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);

function setup(ctx) {
  const { renderer, scene, controllers } = ctx;
  const open = new Map();            // charId -> panel state
  const raycaster = new THREE.Raycaster();
  const tmpM = new THREE.Matrix4();
  const hoverMine = [null, null];    // per controller: {charId, x, y}
  let clock = 0, lastT = performance.now();

  function make(charId) {
    const canvas = document.createElement("canvas");
    canvas.width = PX_W; canvas.height = PX_H;
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false }));
    mesh.renderOrder = 997; mesh.userData.ignoreRaycast = true; mesh.visible = false;
    scene.add(mesh);
    return { charId, canvas, ctx: canvas.getContext("2d"), tex, mesh, events: [], tick: 0, since: null, sizes: {},
             live: true, end: null, span: 2 * 3600, polled: -1e9, fetching: false, pinned: null, hot: null, dirty: true, marks: [] };
  }
  function close(charId) {
    const p = open.get(charId);
    if (!p) return;
    scene.remove(p.mesh); p.tex.dispose(); p.mesh.geometry.dispose(); p.mesh.material.dispose();
    open.delete(charId);
  }
  const toggle = (charId) => (open.has(charId) ? close(charId) : open.set(charId, make(charId)));

  async function poll(p) {
    if (p.fetching) return;
    p.fetching = true;
    try {
      const r = await fetch(`/admin/memtrace/${encodeURIComponent(p.charId)}` + (p.since != null ? `?since=${p.since}` : ""));
      if (r.ok) {
        const j = await r.json();
        p.tick = j.tick; p.sizes = { short: j.short_term, long: j.long_term }; p.name = j.name;
        if (j.events.length) {
          p.events.push(...j.events);
          if (p.events.length > KEEP) p.events.splice(0, p.events.length - KEEP);
          p.since = Math.max(p.since ?? -1, ...j.events.map((e) => e.tick));
          // several events in one tick: the next poll asks for later ticks only, so take the whole tick next time
          p.since -= 1;
          const seen = new Set();
          p.events = p.events.filter((e) => { const k = `${e.tick}|${e.kind}|${(e.ids || []).join(",")}|${e.by}`; if (seen.has(k)) return false; seen.add(k); return true; });
        } else if (p.since == null) p.since = j.tick;
        p.dirty = true;
      }
    } catch (_) { /* next time */ }
    p.fetching = false;
  }

  const x0 = (p) => (p.live ? p.tick : p.end) - p.span;
  const xOf = (p, t) => L.left + (t - x0(p)) / p.span * (L.right - L.left);

  function draw(p) {
    const c = p.ctx;
    c.clearRect(0, 0, PX_W, PX_H);
    c.fillStyle = "rgba(14,17,24,0.95)"; c.fillRect(0, 0, PX_W, PX_H);
    c.textBaseline = "middle";
    c.fillStyle = "#c9d1d9"; c.font = "bold 28px system-ui, sans-serif";
    c.fillText(`short-term ${p.sizes.short ?? "?"} · long-term ${p.sizes.long ?? "?"} · last ${fmtSpan(p.span)}`, 20, 34);
    // LIVE button
    p.liveBtn = { x: PX_W - 130, y: 12, w: 110, h: 44 };
    c.fillStyle = p.live ? "#238636" : (p.hot === "live" ? "#1f6feb" : "rgba(255,255,255,0.12)");
    c.beginPath(); c.roundRect(p.liveBtn.x, p.liveBtn.y, p.liveBtn.w, p.liveBtn.h, 10); c.fill();
    c.fillStyle = "#fff"; c.font = "bold 24px system-ui, sans-serif"; c.textAlign = "center";
    c.fillText(p.live ? "● LIVE" : "LIVE ▶", p.liveBtn.x + p.liveBtn.w / 2, p.liveBtn.y + p.liveBtn.h / 2);
    c.textAlign = "left";
    // lanes
    const counts = {};
    for (const e of p.events) counts[e.kind] = (counts[e.kind] || 0) + 1;
    LANES.forEach(([k, name, col], i) => {
      const y = L.top + i * L.laneH;
      c.fillStyle = i % 2 ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.06)"; c.fillRect(L.left, y, L.right - L.left, L.laneH);
      c.fillStyle = col; c.beginPath(); c.arc(28, y + L.laneH / 2, 9, 0, Math.PI * 2); c.fill();
      c.fillStyle = "#c9d1d9"; c.font = "22px system-ui, sans-serif"; c.fillText(`${name} (${counts[k] || 0})`, 46, y + L.laneH / 2);
    });
    // time axis
    const axisY = L.top + LANES.length * L.laneH + 6;
    c.strokeStyle = "rgba(255,255,255,0.25)"; c.lineWidth = 2; c.beginPath(); c.moveTo(L.left, axisY); c.lineTo(L.right, axisY); c.stroke();
    c.fillStyle = "#8b98ad"; c.font = "18px system-ui, sans-serif"; c.textAlign = "center";
    for (let i = 0; i <= 4; i++) {
      const xx = L.left + i * (L.right - L.left) / 4;
      const back = p.span * (1 - i / 4) + (p.live ? 0 : p.tick - p.end);
      c.fillText(back < 1 ? "now" : `−${fmtSpan(back)}`, xx, axisY + 18);
    }
    c.textAlign = "left";
    // marks
    p.marks = [];
    const start = x0(p), end = start + p.span;
    for (const e of p.events) {
      if (e.tick < start || e.tick > end) continue;
      const lane = LANE_OF[e.kind]; if (lane == null) continue;
      const x = xOf(p, e.tick), y = L.top + lane * L.laneH + L.laneH / 2;
      const r = Math.min(14, 5 + Math.sqrt(e.n || 1) * 2);
      const col = LANES[lane][2];
      const isOn = p.pinned === e || p.hotEvent === e;
      c.fillStyle = col; c.globalAlpha = isOn ? 1 : 0.85;
      c.beginPath(); c.arc(x, y, isOn ? r + 4 : r, 0, Math.PI * 2); c.fill();
      if (e.failed) { c.strokeStyle = "#ff4d4d"; c.lineWidth = 4; c.stroke(); }
      if (isOn) { c.strokeStyle = "#fff"; c.lineWidth = 3; c.stroke(); }
      c.globalAlpha = 1;
      p.marks.push({ e, x, y, r: r + 6 });
    }
    // details of the pointed-at / pinned mark
    const d = p.hotEvent || p.pinned;
    c.fillStyle = "rgba(255,255,255,0.05)"; c.fillRect(12, L.detailTop, PX_W - 24, PX_H - L.detailTop - 12);
    if (!d) {
      c.fillStyle = "#8b98ad"; c.font = "22px system-ui, sans-serif";
      c.fillText("Point at a mark to read it; trigger pins it. Right stick: ←/→ pan, ↑/↓ zoom.", 26, L.detailTop + 30);
    } else {
      const lane = LANES[LANE_OF[d.kind]] || ["", d.kind, "#fff"];
      const lines = [];
      lines.push([`${lane[1].toUpperCase()}${d.failed ? " — FAILED" : ""} · ${fmtSpan(Math.max(0, p.tick - d.tick))} ago · by ${d.by || "?"}${p.pinned === d ? "  📌" : ""}`, lane[2], "bold 22px"]);
      const meta = [d.n != null ? `${d.n} memor${d.n === 1 ? "y" : "ies"}` : null, d.how, d.query ? `query “${d.query}”` : null, d.why,
                    d.importance != null ? `importance ${d.importance}` : null].filter(Boolean).join(" · ");
      if (meta) lines.push([meta, "#c9d1d9", "20px"]);
      if (d.detail) lines.push([d.detail, "#e6edf3", "20px"]);
      if (d.summary) lines.push([`summary: ${d.summary}`, "#f7c1df", "20px"]);
      for (const t of (d.texts || []).slice(0, 4)) lines.push([`• ${t}`, "#c9d1d9", "19px"]);
      let y = L.detailTop + 24;
      for (const [text, col, font] of lines) {
        c.fillStyle = col; c.font = `${font} system-ui, sans-serif`;
        for (const piece of wrap(c, text, PX_W - 60)) {
          if (y > PX_H - 24) break;
          c.fillText(piece, 26, y); y += 27;
        }
      }
    }
    p.tex.needsUpdate = true;
    p.dirty = false;
  }
  function wrap(c, text, maxW) {
    const out = []; let cur = "";
    for (const w of String(text).split(/\s+/)) {
      const t = cur ? cur + " " + w : w;
      if (c.measureText(t).width > maxW && cur) { out.push(cur); cur = w; } else cur = t;
    }
    if (cur) out.push(cur);
    return out;
  }

  // ---- pointing at the content ----
  function pointAt() {
    controllers.forEach((controller, i) => {
      hoverMine[i] = null;
      if (!renderer.xr.isPresenting || window.vrFloat?.hovering(i)) return;
      tmpM.identity().extractRotation(controller.matrixWorld);
      raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld);
      raycaster.ray.direction.set(0, 0, -1).applyMatrix4(tmpM);
      let best = null;
      for (const p of open.values()) {
        if (!p.mesh.visible) continue;
        const h = raycaster.intersectObject(p.mesh, false)[0];
        if (h && (!best || h.distance < best.h.distance)) best = { p, h };
      }
      if (!best) return;
      hoverMine[i] = { charId: best.p.charId, x: best.h.uv.x * PX_W, y: (1 - best.h.uv.y) * PX_H };
      controller.getObjectByName("ray")?.material.color.set(0x58a6ff);
    });
    for (const p of open.values()) {
      const h = hoverMine.find((x) => x && x.charId === p.charId);
      let hotEvent = null, hot = null;
      if (h) {
        const b = p.liveBtn;
        if (b && h.x >= b.x && h.x <= b.x + b.w && h.y >= b.y && h.y <= b.y + b.h) hot = "live";
        let bestD = 1e9;
        for (const m of p.marks) {
          const dd = Math.hypot(m.x - h.x, m.y - h.y);
          if (dd < m.r && dd < bestD) { bestD = dd; hotEvent = m.e; }
        }
      }
      if (hotEvent !== p.hotEvent || hot !== p.hot) { p.hotEvent = hotEvent; p.hot = hot; p.dirty = true; }
    }
  }

  function stick() {
    controllers.forEach((controller, i) => {
      const h = hoverMine[i];
      if (!h) return;
      const src = controller.userData.inputSource;
      const g = src?.handedness === "right" ? src.gamepad : null;      // the right stick, as for the other panels
      if (!g || g.axes.length < 4) return;
      const [, , x, y] = g.axes;
      const p = open.get(h.charId);
      if (!p) return;
      if (Math.abs(x) > 0.2) {
        if (p.live) { p.live = false; p.end = p.tick; }
        p.end = Math.min(p.tick, p.end + x * p.span * 0.02);
        if (p.end >= p.tick - 1 && x > 0) { p.live = true; }
        p.dirty = true;
      }
      if (Math.abs(y) > 0.2) {
        const frac = Math.max(0, Math.min(1, (h.x - L.left) / (L.right - L.left)));
        const anchor = x0(p) + frac * p.span;
        const span = Math.max(60, Math.min(7 * 86400, p.span * (1 + y * 0.04)));
        if (!p.live) p.end = Math.min(p.tick, anchor + (1 - frac) * span);
        p.span = span; p.dirty = true;
      }
    });
  }

  controllers.forEach((controller, i) => {
    controller.addEventListener("selectstart", () => {
      const h = hoverMine[i];
      if (!h) return;
      const p = open.get(h.charId);
      if (!p) return;
      if (p.hot === "live") { p.live = true; p.dirty = true; return; }
      p.pinned = p.hotEvent && p.pinned !== p.hotEvent ? p.hotEvent : null;
      p.dirty = true;
    });
  });

  (window.vrHoverOwners ||= []).push((i) => !!hoverMine[i]);
  window.xrFrameHooks.push(() => {
    const t = performance.now(); clock += (t - lastT) / 1000; lastT = t;
    for (const p of open.values()) {
      if (clock - p.polled > POLL_S) { p.polled = clock; poll(p); }
      if (p.dirty || p.live) {
        if (p.dirty || Math.floor(clock * 2) !== p.lastLiveDraw) { p.lastLiveDraw = Math.floor(clock * 2); draw(p); }
      }
      const name = p.name || window.getWorldCharacter?.(p.charId)?.name || p.charId;
      window.vrFloat?.show(`mem|${p.charId}`, { charId: p.charId, title: `Memory — ${name}`, icon: "🧠", mesh: p.mesh,
                                                 widthM: W_M, heightM: W_M * PX_H / PX_W, onClose: () => close(p.charId) });
    }
    pointAt();
    stick();
  });
  window.vrMemory = {
    toggle, isOpen: (id) => open.has(id),
    state: (id) => { const p = open.get(id); return p && { events: p.events.length, live: p.live, span: p.span, pinned: p.pinned && p.pinned.kind,
      hot: p.hotEvent && p.hotEvent.kind, marks: p.marks.map((m) => ({ kind: m.e.kind, world: p.mesh.localToWorld(new THREE.Vector3(m.x / PX_W - 0.5, 0.5 - m.y / PX_H, 0)).toArray() })) }; },
  };
}

(function waitForXR(attempts = 50) {
  const ctx = window.getXRContext?.();
  if (ctx && window.xrFrameHooks) return setup(ctx);
  if (attempts > 0) setTimeout(() => waitForXR(attempts - 1), 100);
})();
