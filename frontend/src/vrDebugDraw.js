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
//   (Line of sight draws the sight-line tests the last look REALLY made -- green to whoever was seen, red to the wall /
//    door / prop it stopped at, both with distances; nothing tested = nobody in range. Vision and Hearing show their
//    range as bands fading with distance: recognise -> a figure -> a shape; whisper / talking / yelling.)
// Conversations
//   Within sight + earshot?   a line to everyone they're talking with in person: green face to face, red when they're
//                             in different rooms, a wall is between them or they're out of earshot (says which)
//   Incidents (everyone)      the latest in-person lines said to someone who couldn't have heard / seen it (arcs,
//                             backend/systems/conversation_reach.py logs them all the time)
// Social
//   Reputation of people nearby   above everyone within their detection range: public score and standing,
//                             community standing, notoriety, and how this character regards them
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
  { id: "talk", label: "Conversations", parent: true },
  { id: "talk.reach", label: "Within sight + earshot?" },
  { id: "talk.incidents", label: "Incidents (everyone)" },
  { id: "social", label: "Social", parent: true },
  { id: "social.reputation", label: "Reputation of people nearby" },
];
const VOLUME_SHADE = { low: 0.2, medium: 0.45, high: 0.7, loud: 0.85, intense: 1.0 };
const VOICE_NAME = { low: "whisper", medium: "talking", high: "yelling" };
const INCIDENTS_POLL_S = 2;
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

function dashed(points, color, opacity = 0.6) {
  const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineDashedMaterial({ color, transparent: true, opacity, depthTest: false, dashSize: 0.25, gapSize: 0.18 }));
  l.computeLineDistances();
  l.renderOrder = 996;
  return l;
}

// a flat band from r0 to r1 around the origin, fading from opacity a0 (inside) to a1 (outside)
function band(r0, r1, color, a0, a1, h = Y - 0.02, steps = 6) {
  const g = new THREE.Group();
  for (let i = 0; i < steps; i++) {
    const ra = r0 + (r1 - r0) * (i / steps), rb = r0 + (r1 - r0) * ((i + 1) / steps);
    const m = new THREE.Mesh(new THREE.RingGeometry(Math.max(0.001, ra), rb, 64, 1),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: a0 + (a1 - a0) * ((i + 0.5) / steps), depthTest: false,
                                    depthWrite: false, side: THREE.DoubleSide }));
    m.rotation.x = -Math.PI / 2;
    m.position.y = h;
    m.renderOrder = 990;
    g.add(m);
  }
  return g;
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
  const incidents = { list: [], tick: 0, polled: -1e9, fetching: false, group: new THREE.Group() };
  overlay.add(incidents.group);
  async function pollIncidents() {
    if (incidents.fetching) return;
    incidents.fetching = true;
    try {
      const r = await fetch("/admin/debugdraw/talk-reach/log?limit=20");
      if (r.ok) { const j = await r.json(); incidents.list = j.incidents || []; incidents.tick = j.tick; drawIncidents(); }
    } catch (_) { /* next time */ }
    incidents.fetching = false;
  }
  function drawIncidents() {
    for (const ch of [...incidents.group.children]) { incidents.group.remove(ch); disposeTree(ch); }
    if (![...active.values()].some((e) => e.on.has("talk.incidents"))) return;
    for (const inc of incidents.list) {
      const age = Math.max(0, incidents.tick - inc.tick);
      const fade = Math.max(0.25, 1 - age / 1800);
      const a = toScene(inc.from[0], inc.from[1], 1.5), b = toScene(inc.to[0], inc.to[1], 1.5);
      const mid = a.clone().lerp(b, 0.5); mid.y += 0.6 + a.distanceTo(b) * 0.15;
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      incidents.group.add(line(curve.getPoints(16), C.blocked, 0.85 * fade));
      if (inc.hit) { const h = toScene(inc.hit[0], inc.hit[1], 0.2); incidents.group.add(ring(h.x, h.z, 0.2, C.blocked, fade, 0.2)); }
      const l = label(`✘ ${inc.speaker_name} → ${inc.listener_name}, ${fmtS(age)} ago\n${inc.issues.join(" · ")}\n“${String(inc.line || "").slice(0, 48)}”`, "#ff9c90", 0.2);
      l.material.opacity = fade;
      l.position.copy(mid.clone().setY(mid.y + 0.25));
      incidents.group.add(l);
    }
  }

  const entry = (id) => {
    if (!active.has(id)) {
      const group = new THREE.Group();
      group.userData.ignoreRaycast = true;
      const live = new THREE.Group();              // halos that follow characters, rebuilt every frame
      const bands = new THREE.Group();             // range rings and fading bands, built round 0,0 and moved with them
      overlay.add(group, live, bands);
      active.set(id, { on: new Set(), data: null, group, live, bands, flashes: new Map(), fetching: false, polled: -1e9, seenBefore: new Set() });
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
    if (!e.on.size) { disposeTree(e.group); disposeTree(e.live); disposeTree(e.bands); overlay.remove(e.group, e.live, e.bands); active.delete(id); }
    else { e.polled = -1e9; rebuild(id); }
    incidents.polled = -1e9;
    drawIncidents();
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
    const checks = p.los?.checks || [];
    out.push(checks.length ? `Sight tests last look: ${checks.filter((c) => c.ok).length} seen, ${checks.filter((c) => !c.ok).length} failed`
                           : "No sight test last look (nobody in range)");
    const bad = (d.conversations || []).filter((t) => !t.now?.ok);
    if (d.conversations?.length) out.push(`Talking with ${d.conversations.map((t) => t.name).join(", ")}` + (bad.length ? ` — ✘ ${bad[0].now.issues.join(", ")}` : " — face to face"));
    if (incidents.list.length) out.push(`Talk-reach incidents (everyone): ${incidents.list.length}, latest: ${incidents.list[0].speaker_name} → ${incidents.list[0].listener_name}`);
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
    // range bands: how well they make people out / hear a voice, fading with distance (moved with them every frame)
    for (const ch of [...e.bands.children]) { e.bands.remove(ch); disposeTree(ch); }
    if (isOn(id, "per.vision") && per.vision_bands) {
      const vb = per.vision_bands;
      e.bands.add(band(0, vb.recognized, C.vision, 0.2, 0.06));                        // recognise: well, then less so
      if (vb.figure > vb.recognized) e.bands.add(band(vb.recognized, vb.figure, C.detect, 0.08, 0.04, Y - 0.02, 3));   // a figure
      if (vb.silhouette > vb.figure) e.bands.add(band(vb.figure, vb.silhouette, C.detect, 0.04, 0.01, Y - 0.02, 3));   // a shape
      e.bands.add(ring(0, 0, vb.recognized, C.vision, 0.8), ring(0, 0, vb.silhouette, C.detect, 0.6));
      const lv = label(`recognise ≤ ${Math.round(vb.recognized)} · a figure ≤ ${Math.round(vb.figure)} · a shape ≤ ${Math.round(vb.silhouette)} tiles`, "#9ff0b0", 0.22);
      lv.position.set(0, 0.4, -vb.recognized);
      e.bands.add(lv);
    }
    if (isOn(id, "per.hearing") && per.voice_ranges) {
      const vr = per.voice_ranges;
      e.bands.add(band(0, vr.medium, C.hearing, 0.18, 0.02));                           // a talking voice, clearer when close
      for (const v of ["low", "medium", "high"]) {
        if (!vr[v]) continue;
        e.bands.add(ring(0, 0, vr[v], C.hearing, v === "medium" ? 0.85 : 0.45));
        const lh = label(`${VOICE_NAME[v]} ≤ ${vr[v]}`, "#a9c8ff", 0.18);
        lh.position.set(vr[v] * 0.707, 0.3, vr[v] * 0.707);
        e.bands.add(lh);
      }
    }
    if (isOn(id, "per.los")) {
      // the sight-line tests the last look really made: green = seen (to them), red = not (to where it stopped)
      const checks = per.los?.checks || [];
      const eye = me.clone().setY(1.5);
      for (const c of checks) {
        const to = toScene(c.to[0], c.to[1], 1.5);
        if (c.ok) {
          g.add(line([eye, to], C.vision, 0.95));
          const l = label(`✔ SAW ${c.name}${c.purpose === "glimpse" ? " (a shape)" : ""} · ${c.distance} tiles` +
                          (c.believed ? `\nthinks it's ${c.believed}` : ""), c.believed ? "#ffc070" : "#8cff9e", 0.22);
          l.position.copy(to.clone().setY(2.0));
          g.add(l);
        } else {
          const hit = c.hit ? toScene(c.hit[0], c.hit[1], 1.5) : to;
          g.add(line([eye, hit], C.blocked, 0.95));
          g.add(dashed([hit, to], 0x888888, 0.45));
          g.add(ring(hit.x, hit.z, 0.15, C.blocked, 1, 1.5));
          const l = label(`✘ DIDN'T SEE ${c.name} — ${c.by || "blocked"}\nstopped at ${c.hit_distance ?? "?"} tiles (they're ${c.distance} away)`, "#ff8a7a", 0.22);
          l.position.copy(hit.clone().setY(2.0));
          g.add(l);
        }
      }
      if (!checks.length) {
        const l = label("no sight test this look — nobody in range", "#bbbbbb", 0.2);
        l.position.copy(me.clone().setY(2.4));
        g.add(l);
      }
    }
    if (isOn(id, "per.vision")) for (const s of per.seen || []) if (s.thinks) {
      const l = label(`takes ${s.name} for ${s.thinks}`, "#ffc070", 0.22);
      l.position.copy(toScene(s.x, s.y, 2.5)); g.add(l);
    }
    if (isOn(id, "per.hearing")) for (const h of per.heard || []) if (h.x != null) {
      const l = label(`hears ${h.what}` + (h.thinks ? ` — thinks it's ${h.thinks}` : "") + ` (${h.volume}, ${Math.round((h.clarity || 0) * 100)}% clear)`,
                      h.thinks ? "#ffc070" : "#a9c8ff", 0.18);
      l.position.copy(toScene(h.x, h.y, 2.15)); g.add(l);
    }
    if (isOn(id, "talk.reach")) {
      for (const t of d.conversations || []) {
        const r = t.now || {};
        const a = me.clone().setY(1.3), b = toScene(t.x, t.y, 1.3);
        if (r.ok) g.add(line([a, b], C.vision, 0.95));
        else {
          const hit = r.hit ? toScene(r.hit[0], r.hit[1], 1.3) : b;
          g.add(line([a, hit], C.blocked, 0.95));
          if (r.hit) { g.add(dashed([hit, b], C.blocked, 0.5)); g.add(ring(hit.x, hit.z, 0.15, C.blocked, 1, 1.3)); }
        }
        const lastBad = t.last_line && !t.last_line.ok ? `\nlast line: ✘ ${t.last_line.issues.join(", ")}` : "";
        const l = label((r.ok ? `✔ talking with ${t.name} face to face · ${r.distance} tiles`
                              : `✘ talking with ${t.name}: ${(r.issues || []).join(", ")}\n${r.distance} tiles apart`) + lastBad,
                        r.ok && !lastBad ? "#8cff9e" : "#ff8a7a", 0.22);
        l.position.copy(a.clone().lerp(b, 0.5).setY(1.9));
        g.add(l);
      }
    }
    if (isOn(id, "social.reputation")) {
      for (const r of d.social?.reputation || []) {
        const col = r.global >= 0.55 ? "#8cff9e" : r.global >= 0.45 ? "#e6e6e6" : r.global >= 0.2 ? "#ffb070" : "#ff7a6a";
        const view = r.their_view && Object.keys(r.their_view).length
          ? `\n${d.name}'s view: ` + Object.entries(r.their_view).map(([k, v]) => `${k} ${v}`).join(" · ") : "";
        const l = label(`${r.name}: ${r.global.toFixed(2)} ${r.standing.toUpperCase()}\ncommunity ${r.community.toFixed(2)} ${r.community_standing}` +
                        (r.notoriety > 0.05 ? ` · notoriety ${r.notoriety_label}` : "") + view, col, 0.2);
        l.userData.follow = r.id;                 // kept above their head as they move
        l.userData.followY = 2.75;
        l.position.copy(toScene(r.x, r.y, 2.75));
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
      e.bands.position.set(me.x, 0, me.z);                       // range bands follow them as they walk
      for (const o of e.group.children) {
        if (!o.userData.follow) continue;
        const p = charPos(o.userData.follow, null);
        if (p) o.position.set(p.x, p.y + o.userData.followY, p.z);
      }
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
    }
    if ([...active.values()].some((e) => e.on.has("talk.incidents")) && clock - incidents.polled > INCIDENTS_POLL_S) {
      incidents.polled = clock; pollIncidents();
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
