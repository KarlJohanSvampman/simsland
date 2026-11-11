// src/vrDebugDraw.js -- VR "Debug Draw": lines, rings, markers and labels drawn into the world for a character, picked
// from a list (the context menu's "Debug Draw" option, src/vrDebug.js). Data: GET /admin/debugdraw/{id}
// (backend/api/debug_draw.py), read twice a second while anything is switched on for that character.
//
// Navigation
//   Planned route + time      the route they are walking now (cyan), with the estimate and how long it has taken so far
//   Target                    where the walk ends: a pole and ring, labelled with what it is for (a person, prop, room,
//                             building or spot) and its coordinates
//   Alternatives + scores     the places that were in the running when the target was chosen (yellow = chosen, grey =
//                             passed over, with why), each with its score (distance in tiles: lower is better)
//   Past walks                their last few walks: planned vs how long they really took, and how they ended -- red when
//                             it took much longer than planned, or they got stuck
// Perception
//   Vision                    vision ring (green) and detection ring (dim); everyone they see gets a green halo -- a
//                             flash when first seen, bright when close, darker the further away they were spotted
//   Line of sight             a line to everyone within vision range: green seen, red blocked by a wall, orange in range
//                             with a clear line but not seen (behind them, too dark, ...)
//   Hearing                   hearing ring (blue); every sound they hear pulses blue at its source (speech at the
//                             speaker) -- pale for a whisper, deep for a shout
//   Fade the unnoticed        people inside an enabled sense's range whom they neither see nor hear turn half
//                             transparent (for the last character this was switched on for)
//   Last seen                 where they last saw people who are out of sight now, fading the longer ago it was
//
// Coordinates: world tile (x, y) is scene (x - 10, y - 7), as everywhere in main.js.

import * as THREE from "three";

const POLL_S = 0.5;
const Y = 0.06;                                    // lines just above the floor
const OPTIONS = [
  { id: "nav", label: "Navigation", parent: true },
  { id: "nav.route", label: "Planned route + time" },
  { id: "nav.target", label: "Target" },
  { id: "nav.alternatives", label: "Alternatives + scores" },
  { id: "nav.history", label: "Past walks" },
  { id: "per", label: "Perception", parent: true },
  { id: "per.vision", label: "Vision" },
  { id: "per.los", label: "Line of sight" },
  { id: "per.hearing", label: "Hearing" },
  { id: "per.fade", label: "Fade the unnoticed" },
  { id: "per.lastseen", label: "Last seen" },
];
const VOLUME_SHADE = { low: 0.25, medium: 0.5, high: 0.75, shout: 1.0, loud: 0.75, scream: 1.0 };
const C = {
  route: 0x33e0ff, target: 0xff66cc, chosen: 0xffd84a, passed: 0x8a8f99, past: 0x5fa8ff, late: 0xff5a4a,
  vision: 0x48e06a, detect: 0x2a7a3c, hearing: 0x4a8cff, blocked: 0xff4040, unseen: 0xffa040,
};

const toScene = (x, y, h = Y) => new THREE.Vector3(x - 10, h, y - 7);
const fmtS = (s) => (s == null ? "?" : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);
const fmtXY = (x, y) => `(${Number(x).toFixed(1)}, ${Number(y).toFixed(1)})`;

function label(text, color = "#ffffff", size = 0.32) {
  const lines = String(text).split("\n");
  const cv = document.createElement("canvas");
  const ctx = cv.getContext("2d");
  const fs = 34;
  ctx.font = `600 ${fs}px sans-serif`;
  const w = Math.ceil(Math.max(...lines.map((l) => ctx.measureText(l).width))) + 24;
  cv.width = w; cv.height = lines.length * (fs + 8) + 14;
  ctx.font = `600 ${fs}px sans-serif`;
  ctx.fillStyle = "rgba(10,14,22,0.78)";
  ctx.beginPath(); ctx.roundRect(0, 0, cv.width, cv.height, 12); ctx.fill();
  ctx.fillStyle = color;
  ctx.textBaseline = "top";
  lines.forEach((l, i) => ctx.fillText(l, 12, 8 + i * (fs + 8)));
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  sp.renderOrder = 997;
  sp.userData.base = [size * cv.width / cv.height * lines.length, size * lines.length];
  sp.scale.set(...sp.userData.base);
  sp.userData.isLabel = true;
  return sp;
}

function line(points, color, opacity = 0.9) {
  const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthTest: false }));
  l.renderOrder = 996;
  return l;
}

function ring(cx, cz, r, color, opacity = 0.8, h = Y, segs = 64) {
  const pts = [];
  for (let i = 0; i <= segs; i++) {
    const a = (i / segs) * Math.PI * 2;
    pts.push(new THREE.Vector3(cx + Math.cos(a) * r, h, cz + Math.sin(a) * r));
  }
  return line(pts, color, opacity);
}

function disposeTree(obj) {
  obj.traverse((o) => {
    o.geometry?.dispose();
    if (o.material) { o.material.map?.dispose(); o.material.dispose(); }
  });
}

function setup(ctx) {
  const { scene, dolly, sims } = ctx;
  const active = new Map();      // charId -> {on: Set, data, group, flashes: Map(key -> {t0, color, kind, x, y, id}), fetching, polled}
  let fadeFor = null;            // whose senses decide who is faded
  const faded = new Map();       // charId -> [{mesh, material}] (originals, to put back)
  const overlay = new THREE.Group();
  overlay.name = "vrDebugDraw";
  overlay.userData.ignoreRaycast = true;
  scene.add(overlay);
  let clock = 0, last = performance.now();

  const entry = (id) => {
    if (!active.has(id)) {
      const group = new THREE.Group();
      group.userData.ignoreRaycast = true;
      const live = new THREE.Group();              // halos that follow characters, rebuilt every frame
      overlay.add(group, live);
      active.set(id, { on: new Set(), data: null, group, live, flashes: new Map(), fetching: false, polled: -1e9, seenBefore: new Set() });
    }
    return active.get(id);
  };
  const isOn = (id, opt) => !!active.get(id)?.on.has(opt);

  function toggle(id, opt) {
    const e = entry(id);
    const o = OPTIONS.find((x) => x.id === opt);
    if (!o) return;
    if (o.parent) {
      const kids = OPTIONS.filter((x) => x.id.startsWith(opt + "."));
      const all = kids.every((k) => e.on.has(k.id));
      kids.forEach((k) => (all ? e.on.delete(k.id) : e.on.add(k.id)));
    } else if (e.on.has(opt)) e.on.delete(opt);
    else e.on.add(opt);
    if ([...e.on].some((k) => k.startsWith("per."))) fadeFor = id;
    else if (fadeFor === id) fadeFor = null;
    if (!e.on.size) { disposeTree(e.group); disposeTree(e.live); overlay.remove(e.group, e.live); active.delete(id); }
    else { e.polled = -1e9; rebuild(id); }
    if (!fadeFor) for (const [cid, e2] of active) if ([...e2.on].some((k) => k.startsWith("per."))) fadeFor = cid;
  }

  function options(id) {
    const e = active.get(id);
    return OPTIONS.map((o) => {
      const kids = o.parent ? OPTIONS.filter((x) => x.id.startsWith(o.id + ".")) : null;
      const n = kids ? kids.filter((k) => e?.on.has(k.id)).length : 0;
      return { id: o.id, label: o.label, parent: !!o.parent,
               on: kids ? (n === kids.length ? true : n ? "some" : false) : !!e?.on.has(o.id) };
    });
  }

  // a few live numbers for the list panel
  function summary(id) {
    const d = active.get(id)?.data;
    if (!d) return [active.has(id) ? "Reading…" : "Nothing switched on."];
    const out = [];
    const now = d.navigation?.now;
    if (now) out.push(`Walking to ${now.target?.label || "?"} ${fmtXY(now.target?.x, now.target?.y)} — about ${fmtS(now.left_s)} left` +
                      (now.eta_s != null ? `, planned ${fmtS(now.eta_s)}, ${fmtS(now.since_s)} so far` : ""));
    else out.push("Not walking.");
    const p = d.perception || {};
    const noticed = new Set([...(p.seen || []).map((x) => x.id), ...(p.heard || []).map((x) => x.id)]);
    const unnoticed = new Set([...(p.in_range_unseen || []), ...(p.in_range_unheard || [])].map((x) => x.id).filter((x) => !noticed.has(x)));
    out.push(`Sees ${p.seen?.length || 0} · hears ${p.heard?.length || 0} · in range but unnoticed: ${unnoticed.size}`);
    out.push(`Ranges (tiles): vision ${p.visual_range ?? "?"}, detection ${p.detection_range ?? "?"}, hearing ${p.hearing_range ?? "?"}`);
    return out;
  }

  async function poll(id) {
    const e = active.get(id);
    if (!e || e.fetching) return;
    e.fetching = true;
    try {
      const r = await fetch(`/admin/debugdraw/${encodeURIComponent(id)}`);
      if (r.ok && active.get(id) === e) {
        e.data = await r.json();
        noteFlashes(e);
        rebuild(id);
      }
    } catch (_) { /* try again next poll */ }
    e.fetching = false;
  }

  // something newly seen or heard flashes; still seen / heard keeps a steady halo
  function noteFlashes(e) {
    const p = e.data.perception || {};
    const keys = new Set();
    for (const s of p.seen || []) {
      const k = `v:${s.id}`; keys.add(k);
      const near = 1 - Math.min(1, (s.distance || 0) / Math.max(1, p.visual_range || 10));
      const f = e.flashes.get(k) || { t0: clock, kind: "vision", id: s.id };
      f.shade = near; f.x = s.x; f.y = s.y; f.last = clock;
      e.flashes.set(k, f);
    }
    for (const h of p.heard || []) {
      const k = h.id ? `h:${h.id}` : `h:${h.what}@${Math.round(h.x)},${Math.round(h.y)}`; keys.add(k);
      const f = e.flashes.get(k) || { t0: clock, kind: "hearing", id: h.id };
      f.shade = VOLUME_SHADE[h.volume] ?? 0.5; f.x = h.x; f.y = h.y; f.last = clock;
      e.flashes.set(k, f);
    }
    for (const k of [...e.flashes.keys()]) if (!keys.has(k)) e.flashes.delete(k);
  }

  function shade(base, t) {                         // 0 = pale/dark, 1 = full
    const c = new THREE.Color(base);
    return t >= 0.5 ? c.lerp(new THREE.Color(0xffffff), (t - 0.5) * 0.6) : c.multiplyScalar(0.35 + t * 1.3);
  }

  // ---- the static part (rebuilt when new data arrives or an option changes) ----
  function rebuild(id) {
    const e = active.get(id);
    if (!e) return;
    for (const ch of [...e.group.children]) { e.group.remove(ch); disposeTree(ch); }
    const d = e.data;
    if (!d) return;
    const g = e.group;
    const nav = d.navigation || {}, per = d.perception || {};
    const me = toScene(d.x, d.y);
    const now = nav.now;
    const lastPlan = (nav.plans || []).slice(-1)[0];

    if (isOn(id, "nav.route") && now?.path?.length > 1) {
      g.add(line(now.path.map(([x, y]) => toScene(x, y, Y + 0.02)), C.route, 1));
      const end = now.path[now.path.length - 1];
      const late = now.eta_s != null && now.since_s > now.eta_s * 1.5;
      const l = label(`about ${fmtS(now.left_s)} left` + (now.eta_s != null ? `\nplanned ${fmtS(now.eta_s)} · ${fmtS(now.since_s)} so far` : ""),
                      late ? "#ff8a7a" : "#9ff3ff");
      l.position.copy(toScene(end[0], end[1], 1.2));
      g.add(l);
    }
    const tgt = now?.target || (lastPlan && !lastPlan.ended ? lastPlan.target : null);
    if (isOn(id, "nav.target") && tgt && tgt.x != null) {
      const p = toScene(tgt.x, tgt.y);
      g.add(ring(p.x, p.z, 0.45, C.target, 1), ring(p.x, p.z, 0.25, C.target, 1));
      g.add(line([p.clone(), p.clone().setY(1.6)], C.target, 1));
      const l = label(`${tgt.kind}: ${tgt.label || tgt.id || "?"}\n${fmtXY(tgt.x, tgt.y)}`, "#ffb3e6");
      l.position.copy(p.clone().setY(1.9));
      g.add(l);
    }
    if (isOn(id, "nav.alternatives") && lastPlan?.candidates?.length) {
      const from = lastPlan.from ? toScene(lastPlan.from[0], lastPlan.from[1]) : me;
      for (const cand of lastPlan.candidates) {
        if (cand.x == null) continue;
        const p = toScene(cand.x, cand.y);
        const col = cand.chosen ? C.chosen : C.passed;
        g.add(line([from.clone().setY(Y + 0.01), p.clone().setY(Y + 0.01)], col, cand.chosen ? 0.95 : 0.5));
        g.add(ring(p.x, p.z, 0.3, col, 0.9));
        const l = label(`${cand.chosen ? "★ " : ""}${cand.label || cand.prop_id} · score ${cand.score}` + (cand.skipped ? `\npassed over: ${cand.skipped}` : ""),
                        cand.chosen ? "#ffe680" : "#b9bec8", 0.24);
        l.position.copy(p.clone().setY(0.9));
        g.add(l);
      }
      if (lastPlan.interaction) {
        const l = label(`choosing a place to: ${String(lastPlan.interaction).replace(/_/g, " ")}`, "#ffe680", 0.26);
        l.position.copy(from.clone().setY(2.3));
        g.add(l);
      }
    }
    if (isOn(id, "nav.history")) {
      for (const pl of (nav.plans || []).filter((x) => x.ended && x.path?.length > 1).slice(-4)) {
        const late = pl.ended === "stuck" || (pl.eta_s && pl.actual_s > pl.eta_s * 1.5);
        g.add(line(pl.path.map(([x, y]) => toScene(x, y, Y + 0.005)), late ? C.late : C.past, 0.45));
        const end = pl.path[pl.path.length - 1];
        const l = label(`${pl.ended}: planned ${fmtS(pl.eta_s)}, took ${fmtS(pl.actual_s)}`, late ? "#ff8a7a" : "#a8ccff", 0.22);
        l.position.copy(toScene(end[0], end[1], 0.6));
        g.add(l);
      }
    }
    if (isOn(id, "per.lastseen")) {
      for (const s of per.last_seen || []) {
        if (s.x == null) continue;
        const fade = Math.max(0.15, 1 - s.ago_s / 3600);
        const p = toScene(s.x, s.y);
        g.add(ring(p.x, p.z, 0.3, 0xcccccc, 0.8 * fade));
        const l = label(`${s.name} last seen ${fmtS(s.ago_s)} ago`, "#dddddd", 0.2);
        l.material.opacity = fade;
        l.position.copy(p.clone().setY(0.5));
        g.add(l);
      }
    }
  }

  // ---- the live part: halos that follow characters, flashes, line of sight ----
  const charPos = (cid, fallback) => {
    const m = sims[cid];
    return m ? m.getWorldPosition(new THREE.Vector3()) : fallback;
  };

  function frame() {
    const t = performance.now();
    clock += (t - last) / 1000;
    last = t;
    for (const [id, e] of active) {
      if (clock - e.polled > POLL_S) { e.polled = clock; poll(id); }
      for (const ch of [...e.live.children]) { e.live.remove(ch); disposeTree(ch); }
      const d = e.data;
      if (!d) continue;
      const per = d.perception || {};
      const me = charPos(id, toScene(d.x, d.y));
      const eye = me.clone().setY(me.y + 1.6);
      if (isOn(id, "per.vision")) {                             // range rings, centred on them as they walk
        if (per.visual_range) e.live.add(ring(me.x, me.z, per.visual_range, C.vision, 0.7));
        if (per.detection_range > 0) e.live.add(ring(me.x, me.z, per.detection_range, C.detect, 0.6));
      }
      if (isOn(id, "per.hearing") && per.hearing_range) e.live.add(ring(me.x, me.z, per.hearing_range, C.hearing, 0.7));
      for (const f of e.flashes.values()) {
        if (f.kind === "vision" ? !isOn(id, "per.vision") : !isOn(id, "per.hearing")) continue;
        const at = f.id ? charPos(f.id, toScene(f.x, f.y)) : toScene(f.x, f.y);
        const age = clock - f.t0;
        const flash = Math.max(0, 1 - age / 1.2);                // a burst when it starts
        const pulse = 0.5 + 0.5 * Math.sin(clock * (f.kind === "hearing" ? 7 : 4));
        const col = shade(f.kind === "vision" ? C.vision : C.hearing, f.shade);
        if (f.kind === "vision") {
          e.live.add(ring(at.x, at.z, 0.42 + flash * 0.5, col, 0.55 + 0.45 * Math.max(flash, pulse * 0.4), at.y + 0.04));
          if (flash > 0) e.live.add(ring(at.x, at.z, 0.2 + flash * 1.2, col, flash, at.y + 0.05));
        } else {
          const grow = (clock * 0.9) % 1;                        // sound: ripples spreading from the source
          e.live.add(ring(at.x, at.z, 0.3 + grow * 1.1, col, (1 - grow) * 0.9, at.y + 0.06));
          e.live.add(ring(at.x, at.z, 0.3 + flash * 1.5, col, Math.max(flash, 0.35), at.y + 0.07));
        }
      }
      if (isOn(id, "per.los")) {
        for (const s of per.seen || []) {
          const p = charPos(s.id, toScene(s.x, s.y));
          e.live.add(line([eye, p.clone().setY(p.y + 1.5)], C.vision, 0.85));
        }
        for (const h of per.in_range_unseen || []) {
          const p = charPos(h.id, toScene(h.x, h.y));
          e.live.add(line([eye, p.clone().setY(p.y + 1.5)], h.blocked ? C.blocked : C.unseen, 0.6));
        }
      }
    }
    applyFade();
    const s = Math.max(1, dolly.scale.x);                       // labels stay readable when you are a giant
    overlay.traverse((o) => { if (o.userData.isLabel) o.scale.set(o.userData.base[0] * s, o.userData.base[1] * s, 1); });
  }

  // people inside an enabled sense's range who are neither seen nor heard: half transparent
  function applyFade() {
    const want = new Set();
    const e = fadeFor && active.get(fadeFor);
    if (e?.data && isOn(fadeFor, "per.fade")) {
      const per = e.data.perception || {};
      const noticed = new Set([...(per.seen || []).map((s) => s.id), ...(per.heard || []).map((h) => h.id).filter(Boolean)]);
      const inRange = [];
      if (isOn(fadeFor, "per.vision") || !isOn(fadeFor, "per.hearing")) inRange.push(...(per.in_range_unseen || []));
      if (isOn(fadeFor, "per.hearing") || !isOn(fadeFor, "per.vision")) inRange.push(...(per.in_range_unheard || []));
      for (const p of inRange) if (!noticed.has(p.id)) want.add(p.id);
    }
    for (const cid of [...faded.keys()]) if (!want.has(cid)) unfade(cid);
    for (const cid of want) if (!faded.has(cid)) fade(cid);
  }
  function fade(cid) {
    const m = sims[cid];
    if (!m) return;
    const kept = [];
    m.traverse((o) => {
      if (!o.isMesh || !o.material || o.userData.ignoreRaycast) return;
      const orig = o.material;
      const mk = (mat) => { const c = mat.clone(); c.transparent = true; c.opacity = 0.35 * (mat.opacity ?? 1); c.depthWrite = false;
                            if (c.color) c.color.lerp(new THREE.Color(0x9aa0a8), 0.5); return c; };
      o.material = Array.isArray(orig) ? orig.map(mk) : mk(orig);
      kept.push({ mesh: o, material: orig, faded: o.material });
    });
    faded.set(cid, kept);
  }
  function unfade(cid) {
    for (const k of faded.get(cid) || []) {
      if (k.mesh.material === k.faded) {                        // unless main.js swapped it meanwhile
        (Array.isArray(k.faded) ? k.faded : [k.faded]).forEach((m) => m.dispose());
        k.mesh.material = k.material;
      }
    }
    faded.delete(cid);
  }

  window.xrFrameHooks.push(frame);
  window.vrDebugDraw = {
    options, toggle, summary,
    activeFor: () => [...active.keys()],
    // read-only, for tests
    state: (id) => {
      const e = active.get(id);
      return e && { on: [...e.on], hasData: !!e.data, objects: e.group.children.length, live: e.live.children.length,
                    labels: e.group.children.filter((o) => o.userData.isLabel).map((o) => o.material.map.image ? true : false).length,
                    flashes: [...e.flashes.entries()].map(([k, f]) => ({ key: k, kind: f.kind, shade: f.shade })),
                    faded: [...faded.keys()], fadeFor };
    },
  };
}

(function waitForXR(attempts = 50) {
  const ctx = window.getXRContext?.();
  if (ctx && window.xrFrameHooks) return setup(ctx);
  if (attempts > 0) setTimeout(() => waitForXR(attempts - 1), 100);
})();
