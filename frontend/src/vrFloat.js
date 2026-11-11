// src/vrFloat.js -- floating panels for anything shown beside a character in VR (the debug panels from "Show panels",
// the memory timeline, ...). Owners keep drawing their own content (a canvas texture on a plane); this module adds the
// frame around it and places it:
//
//   title bar       drag it (trigger held) to move the panel anywhere; buttons on the right: — minimise, × close,
//                   and furthest right a lock checkbox: ☑ locked = the panel keeps its place RELATIVE TO THE
//                   CHARACTER (moves with them), ☐ = it stays where you put it in the world
//   corner handle   drag the bottom-right corner to resize
//   minimised       a small icon in a row above the character's head; trigger on it to bring the panel back
//   layout          panels nobody has moved line up in columns to the right of their character, facing you
//
// Owner API (call every frame for each panel that should show; stop calling and it goes away):
//   vrFloat.show(key, {charId, title, icon, mesh, widthM, heightM, onClose})
//     mesh            the owner's content plane (PlaneGeometry(1, 1)); this sets its position, scale, visibility
//     widthM/heightM  its size at human scale (your own scale and the user's resize are applied on top)
//   vrFloat.hovering(i)   whether controller i points at a frame part (owners then leave the trigger alone)
//   vrFloat.isMinimized(key)

import * as THREE from "three";

const TITLE_PX_W = 900, TITLE_PX_H = 84;
const HANDLE_M = 0.05;
const ICON_M = 0.16;
const COL_GAP_M = 0.05, ROW_GAP_M = 0.04;
const STORE_KEY = "vrFloat.v1";
const loadStore = () => { try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}") || {}; } catch (_) { return {}; } };
const saveStore = (s) => { try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (_) { /* private window */ } };

function setup(ctx) {
  const { renderer, scene, dolly, camera, controllers, sims } = ctx;
  const raycaster = new THREE.Raycaster();
  const tmpM = new THREE.Matrix4();
  const frames = new Map();          // key -> frame
  const store = loadStore();         // key -> {locked, minimized, scale, rel:[x,y,z] | abs:[x,y,z]} -- remembered per panel
  const hover = [null, null];        // per controller: {key, part: "title"|"min"|"close"|"lock"|"handle"|"icon", point, distance}
  const drag = [null, null];         // per controller: {key, mode: "move"|"resize", ...}
  let stamp = 0;

  const headWorld = () => camera.getWorldPosition(new THREE.Vector3());
  const charHead = (id) => {
    const m = sims[id];
    if (!m) return null;
    const p = m.getWorldPosition(new THREE.Vector3());
    p.y += 1.75;
    return p;
  };
  const remember = (f) => {
    store[f.key] = { locked: f.locked, minimized: f.minimized, scale: f.scale,
                     ...(f.rel ? { rel: f.rel.toArray() } : {}), ...(f.abs ? { abs: f.abs.toArray() } : {}) };
    saveStore(store);
  };

  function plane(renderOrder) {
    const canvas = document.createElement("canvas");
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false }));
    mesh.renderOrder = renderOrder;
    mesh.userData.ignoreRaycast = true;
    scene.add(mesh);
    return { canvas, ctx: canvas.getContext("2d"), tex, mesh };
  }

  function make(key, opts) {
    const s = store[key] || {};
    const f = {
      key, charId: opts.charId, title: opts.title || key, icon: opts.icon || "▣",
      locked: s.locked ?? true, minimized: !!s.minimized, scale: s.scale || 1,
      rel: s.rel ? new THREE.Vector3(...s.rel) : null, abs: s.abs ? new THREE.Vector3(...s.abs) : null,
      title3: plane(998), handle: null, icon3: plane(998), drawnTitle: null, drawnIcon: null, buttons: [], seen: 0,
    };
    const hg = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape([new THREE.Vector2(0.5, -0.5), new THREE.Vector2(0.5, 0.5), new THREE.Vector2(-0.5, -0.5)])),
      new THREE.MeshBasicMaterial({ color: 0x58a6ff, transparent: true, opacity: 0.85, depthTest: false, side: THREE.DoubleSide }));
    hg.renderOrder = 999; hg.userData.ignoreRaycast = true; scene.add(hg);
    f.handle = hg;
    frames.set(key, f);
    return f;
  }

  function drawTitle(f, hoverPart) {
    const sig = [f.title, f.locked, hoverPart].join("|");
    if (f.drawnTitle === sig) return;
    f.drawnTitle = sig;
    const { canvas, ctx } = f.title3;
    if (canvas.width !== TITLE_PX_W) { canvas.width = TITLE_PX_W; canvas.height = TITLE_PX_H; }
    ctx.clearRect(0, 0, TITLE_PX_W, TITLE_PX_H);
    ctx.fillStyle = "rgba(31,48,78,0.96)";
    ctx.beginPath(); ctx.roundRect(0, 0, TITLE_PX_W, TITLE_PX_H, [18, 18, 0, 0]); ctx.fill();
    const B = TITLE_PX_H - 16;
    const btns = [{ id: "lock", label: f.locked ? "☑" : "☐" }, { id: "close", label: "×" }, { id: "min", label: "—" }];   // right to left
    f.buttons = [];
    let x = TITLE_PX_W - 10 - B;
    for (const b of btns) {
      f.buttons.push({ id: b.id, x, y: 8, w: B, h: B });
      ctx.fillStyle = hoverPart === b.id ? "#1f6feb" : "rgba(255,255,255,0.12)";
      ctx.beginPath(); ctx.roundRect(x, 8, B, B, 12); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "bold 46px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(b.label, x + B / 2, 8 + B / 2 + 2);
      x -= B + 10;
    }
    ctx.textAlign = "left"; ctx.fillStyle = hoverPart === "title" ? "#ffffff" : "#dfe8f5"; ctx.font = "bold 40px system-ui, sans-serif";
    let t = f.title;
    while (ctx.measureText(t).width > x - 30 && t.length > 4) t = t.slice(0, -2);
    ctx.fillText(t === f.title ? t : t + "…", 22, TITLE_PX_H / 2 + 2);
    f.title3.tex.needsUpdate = true;
  }

  function drawIcon(f, hot) {
    const sig = [f.icon, hot].join("|");
    if (f.drawnIcon === sig) return;
    f.drawnIcon = sig;
    const { canvas, ctx } = f.icon3;
    if (canvas.width !== 128) { canvas.width = 128; canvas.height = 128; }
    ctx.clearRect(0, 0, 128, 128);
    ctx.fillStyle = hot ? "#1f6feb" : "rgba(31,48,78,0.95)";
    ctx.strokeStyle = "#9cc3ff"; ctx.lineWidth = 6;
    ctx.beginPath(); ctx.roundRect(6, 6, 116, 116, 24); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#fff"; ctx.font = "bold 64px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(f.icon, 64, 68);
    f.icon3.tex.needsUpdate = true;
  }

  // ---- owners call this every frame ----
  const pending = new Map();         // charId -> [ {f, opts} ] in call order, laid out at the end of the frame
  function show(key, opts) {
    const f = frames.get(key) || make(key, opts);
    f.title = opts.title || f.title; f.icon = opts.icon || f.icon; f.charId = opts.charId;
    f.mesh = opts.mesh; f.onClose = opts.onClose; f.wm0 = opts.widthM; f.hm0 = opts.heightM;
    f.seen = stamp;
    (pending.get(opts.charId) || pending.set(opts.charId, []).get(opts.charId)).push(f);
  }

  function layout() {
    const head = headWorld();
    const s = dolly.scale.x;
    for (const [charId, list] of pending) {
      const target = charHead(charId);
      if (!target) { list.forEach((f) => hideAll(f)); continue; }
      const toViewer = head.clone().sub(target).setY(0).normalize();
      const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), toViewer).normalize();
      // minimised: icons in a row above the head
      const mins = list.filter((f) => f.minimized);
      mins.forEach((f, i) => {
        const p = target.clone().addScaledVector(right, (i - (mins.length - 1) / 2) * (ICON_M + 0.03) * s);
        p.y += 0.95 * s;
        f.icon3.mesh.position.copy(p); f.icon3.mesh.lookAt(head); f.icon3.mesh.scale.set(ICON_M * s, ICON_M * s, 1);
        f.icon3.mesh.visible = true;
        drawIcon(f, hover.some((h) => h && h.key === f.key && h.part === "icon"));
        f.mesh.visible = false; f.title3.mesh.visible = false; f.handle.visible = false;
      });
      // open: placed where the user put them, else in columns to the right
      const colY = [target.y + 0.35 * s, target.y + 0.35 * s];
      let idx = 0;
      for (const f of list) {
        if (f.minimized) continue;
        f.icon3.mesh.visible = false;
        const wm = f.wm0 * s * f.scale, hm = f.hm0 * s * f.scale, th = wm * TITLE_PX_H / TITLE_PX_W;
        let center;
        const dragging = drag.find((d) => d && d.key === f.key && d.mode === "move");
        if (dragging) center = dragging.center.clone();
        else if (f.locked && f.rel) center = target.clone().add(f.rel.clone().multiplyScalar(s));
        else if (!f.locked && f.abs) center = f.abs.clone();
        else {
          const col = idx % 2;
          const x = (0.55 + col * (f.wm0 * f.scale + COL_GAP_M)) * s;
          center = target.clone().addScaledVector(right, x + wm / 2);
          center.y = colY[col] - th - hm / 2;
          colY[col] -= hm + th + ROW_GAP_M * s;
          idx++;
        }
        f.center = center;
        f.mesh.position.copy(center); f.mesh.lookAt(head); f.mesh.scale.set(wm, hm, 1); f.mesh.visible = true;
        const up = new THREE.Vector3(0, 1, 0).applyQuaternion(f.mesh.quaternion);
        const rt = new THREE.Vector3(1, 0, 0).applyQuaternion(f.mesh.quaternion);
        f.title3.mesh.position.copy(center).addScaledVector(up, hm / 2 + th / 2);
        f.title3.mesh.quaternion.copy(f.mesh.quaternion); f.title3.mesh.scale.set(wm, th, 1); f.title3.mesh.visible = true;
        const hs = HANDLE_M * s * Math.max(0.6, f.scale);
        f.handle.position.copy(center).addScaledVector(up, -hm / 2 + hs / 2).addScaledVector(rt, wm / 2 - hs / 2);
        f.handle.quaternion.copy(f.mesh.quaternion); f.handle.scale.set(hs, hs, 1); f.handle.visible = true;
        const hp = hover.find((h) => h && h.key === f.key);
        drawTitle(f, hp ? hp.part : null);
        f.handle.material.opacity = hp?.part === "handle" ? 1 : 0.6;
      }
    }
    pending.clear();
    // panels nobody showed this frame go away
    for (const [key, f] of frames) {
      if (f.seen === stamp) continue;
      for (const o of [f.title3, f.icon3]) { scene.remove(o.mesh); o.tex.dispose(); o.mesh.geometry.dispose(); o.mesh.material.dispose(); }
      scene.remove(f.handle); f.handle.geometry.dispose(); f.handle.material.dispose();
      frames.delete(key);
    }
  }
  const hideAll = (f) => { f.mesh.visible = false; f.title3.mesh.visible = false; f.handle.visible = false; f.icon3.mesh.visible = false; };

  // ---- pointing ----
  function ray(controller) {
    tmpM.identity().extractRotation(controller.matrixWorld);
    raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld);
    raycaster.ray.direction.set(0, 0, -1).applyMatrix4(tmpM);
    return raycaster.ray;
  }
  function pointAt() {
    controllers.forEach((controller, i) => {
      hover[i] = null;
      if (!renderer.xr.isPresenting) return;
      ray(controller);
      let best = null;
      const consider = (key, part, obj) => {
        if (!obj.visible) return;
        const h = raycaster.intersectObject(obj, false)[0];
        if (h && (!best || h.distance < best.distance)) best = { key, part, point: h.point, distance: h.distance, uv: h.uv };
      };
      for (const [key, f] of frames) {
        consider(key, "handle", f.handle);
        consider(key, "title", f.title3.mesh);
        consider(key, "icon", f.icon3.mesh);
      }
      if (best && best.part === "title") {
        const f = frames.get(best.key);
        const x = best.uv.x * TITLE_PX_W, y = (1 - best.uv.y) * TITLE_PX_H;
        const b = f.buttons.find((r) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
        if (b) best.part = b.id;
      }
      // the content in front of the frame part wins (owners raycast their own meshes)
      if (best) {
        for (const f of frames.values()) {
          if (!f.mesh?.visible) continue;
          const h = raycaster.intersectObject(f.mesh, false)[0];
          if (h && h.distance < best.distance - 1e-3) { best = null; break; }
        }
      }
      hover[i] = best;
      if (best) controller.getObjectByName("ray")?.material.color.set(best.part === "title" || best.part === "handle" ? 0xa5d6ff : 0x58a6ff);
    });
  }

  controllers.forEach((controller, i) => {
    controller.addEventListener("selectstart", () => {
      const h = hover[i];
      if (!h) return;
      const f = frames.get(h.key);
      if (!f) return;
      if (h.part === "icon") { f.minimized = false; remember(f); return; }
      if (h.part === "min") { f.minimized = true; remember(f); return; }
      if (h.part === "close") { f.onClose?.(); return; }
      if (h.part === "lock") {
        const target = charHead(f.charId), s = dolly.scale.x;
        if (f.center && target) {                       // keep it exactly where it is, now relative to the other frame
          if (f.locked) { f.abs = f.center.clone(); f.rel = null; } else { f.rel = f.center.clone().sub(target).multiplyScalar(1 / s); f.abs = null; }
        }
        f.locked = !f.locked; remember(f); return;
      }
      if (h.part === "title") {
        drag[i] = { key: f.key, mode: "move", dist: h.distance, grab: f.center.clone().sub(h.point), center: f.center.clone() };
      }
      if (h.part === "handle") {
        const n = new THREE.Vector3(0, 0, 1).applyQuaternion(f.mesh.quaternion);
        drag[i] = { key: f.key, mode: "resize", plane: new THREE.Plane().setFromNormalAndCoplanarPoint(n, f.center),
                    center: f.center.clone(), d0: h.point.distanceTo(f.center), scale0: f.scale };
      }
    });
    controller.addEventListener("selectend", () => {
      const d = drag[i];
      drag[i] = null;
      if (!d) return;
      const f = frames.get(d.key);
      if (!f) return;
      if (d.mode === "move") {
        const target = charHead(f.charId), s = dolly.scale.x;
        if (f.locked && target) { f.rel = d.center.clone().sub(target).multiplyScalar(1 / s); f.abs = null; }
        else { f.abs = d.center.clone(); f.rel = null; }
      }
      remember(f);
    });
  });

  function dragging() {
    controllers.forEach((controller, i) => {
      const d = drag[i];
      if (!d) return;
      const f = frames.get(d.key);
      if (!f) { drag[i] = null; return; }
      const r = ray(controller);
      if (d.mode === "move") d.center = r.origin.clone().addScaledVector(r.direction, d.dist).add(d.grab);
      else {
        const p = r.intersectPlane(d.plane, new THREE.Vector3());
        if (p && d.d0 > 1e-4) f.scale = Math.max(0.35, Math.min(4, d.scale0 * p.distanceTo(d.center) / d.d0));
      }
    });
  }

  const hook = () => {
    const hooks = window.xrFrameHooks;            // lay out after every owner has called show() this frame
    if (hooks[hooks.length - 1] !== hook) { hooks.splice(hooks.indexOf(hook), 1); hooks.push(hook); return; }   // runs again at the end
    dragging(); layout(); pointAt(); stamp++;
  };
  window.xrFrameHooks.push(hook);
  window.vrFloat = {
    show, hovering: (i) => !!hover[i] || !!drag[i], isMinimized: (key) => !!frames.get(key)?.minimized,
    // for tests
    state: () => [...frames.values()].map((f) => ({ key: f.key, charId: f.charId, locked: f.locked, minimized: f.minimized, scale: f.scale,
      center: f.center?.toArray(), moved: !!(f.rel || f.abs),
      parts: { title: f.title3.mesh.visible && worldOf(f.title3.mesh, 0.5 - 0.5, 0), handle: f.handle.visible && f.handle.position.toArray(),
               icon: f.icon3.mesh.visible && f.icon3.mesh.position.toArray(),
               buttons: Object.fromEntries(f.buttons.map((b) => [b.id, worldOf(f.title3.mesh, (b.x + b.w / 2) / TITLE_PX_W - 0.5, 0.5 - (b.y + b.h / 2) / TITLE_PX_H)])) } })),
    hover: () => hover.map((h) => h && { key: h.key, part: h.part }),
    reset: () => { for (const k of Object.keys(store)) delete store[k]; saveStore(store); },
  };
  function worldOf(mesh, u, v) { return mesh.localToWorld(new THREE.Vector3(u, v, 0)).toArray(); }
}

(function waitForXR(attempts = 50) {
  const ctx = window.getXRContext?.();
  if (ctx && window.xrFrameHooks) return setup(ctx);
  if (attempts > 0) setTimeout(() => waitForXR(attempts - 1), 100);
})();
