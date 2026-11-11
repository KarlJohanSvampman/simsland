// src/vrKeyboard.js -- typing in the headset: a panel in front of you with a text box, dictation and a keyboard you
// point at.
//
//   🎤 Dictate    speak; what you say is written in (Web Speech API: grey while it's still listening, black once it's
//                 settled). Trigger again to stop. Not every browser has it -- the panel says so, and the keyboard works
//                 anyway.
//   keys          point and pull the trigger; ⇧ for capitals (once), ⌫ deletes, Clear empties it
//   Done / Cancel what you typed goes back to whoever asked (or nothing does)
//   a real keyboard (desktop, or one paired with the headset) types into it too: Enter = Done, Esc = Cancel
//
//   window.vrKeyboard.open({title, prompt, text, onDone(text), onCancel()})

import * as THREE from "three";

const PX_W = 1200, PX_H = 780;
const W_M = 0.9;
const ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "⌫"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "'", "("],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l", ".", ",", ")"],
  ["⇧", "z", "x", "c", "v", "b", "n", "m", "?", "!", "\"", ":"],
];
const BOTTOM = [["🎤", "🎤 Dictate", 2.2], ["space", "space", 4.4], ["clear", "Clear", 1.6], ["cancel", "Cancel", 1.6], ["done", "Done", 2.2]];
const K = { top: 330, keyH: 74, gap: 10, left: 30 };

function setup(ctx) {
  const { renderer, scene, camera, dolly, controllers } = ctx;
  const raycaster = new THREE.Raycaster();
  const tmpM = new THREE.Matrix4();
  const canvas = document.createElement("canvas");
  canvas.width = PX_W; canvas.height = PX_H;
  const c = canvas.getContext("2d");
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false }));
  mesh.renderOrder = 1001; mesh.userData.ignoreRaycast = true; mesh.visible = false;
  scene.add(mesh);
  let cur = null;                    // {title, prompt, text, interim, shift, onDone, onCancel, status}
  let keys = [];
  const hover = [null, null];
  let rec = null;                    // the speech recognizer while listening

  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;

  function place() {
    const head = camera.getWorldPosition(new THREE.Vector3());
    const dir = camera.getWorldDirection(new THREE.Vector3()).setY(0);
    if (dir.lengthSq() < 1e-6) dir.set(0, 0, -1);
    dir.normalize();
    const s = dolly.scale.x;
    const pos = head.clone().addScaledVector(dir, 0.75 * s);
    pos.y -= 0.25 * s;
    mesh.position.copy(pos);
    mesh.lookAt(head);
    mesh.scale.set(W_M * s, W_M * s * PX_H / PX_W, 1);
  }

  function wrap(text, maxW) {
    const out = [];
    for (const para of String(text).split("\n")) {
      let line = "";
      for (const w of para.split(/(\s+)/)) {
        const t = line + w;
        if (c.measureText(t).width > maxW && line.trim()) { out.push(line); line = w.trimStart(); } else line = t;
      }
      out.push(line);
    }
    return out;
  }

  function draw() {
    if (!cur) return;
    keys = [];
    c.clearRect(0, 0, PX_W, PX_H);
    c.fillStyle = "rgba(14,17,24,0.97)"; c.strokeStyle = "rgba(120,170,255,0.7)"; c.lineWidth = 4;
    c.beginPath(); c.roundRect(2, 2, PX_W - 4, PX_H - 4, 26); c.fill(); c.stroke();
    c.textBaseline = "top";
    c.fillStyle = "#e8eef8"; c.font = "bold 40px system-ui, sans-serif"; c.fillText(cur.title || "Type", 30, 22);
    c.fillStyle = "#8b98ad"; c.font = "24px system-ui, sans-serif";
    let py = 72;
    for (const l of wrap(cur.prompt || "", PX_W - 60).slice(0, 2)) { c.fillText(l, 30, py); py += 30; }
    // the text box
    const bx = 24, by = 136, bw = PX_W - 48, bh = 150;
    c.fillStyle = "#f6f8fa"; c.beginPath(); c.roundRect(bx, by, bw, bh, 14); c.fill();
    c.font = "28px system-ui, sans-serif";
    const lines = wrap(cur.text + (cur.interim ? (cur.text && !cur.text.endsWith(" ") ? " " : "") + "\u0001" + cur.interim : "") + "▏", bw - 30);
    const shown = lines.slice(-4);
    let ty = by + 12;
    for (const l of shown) {
      const i = l.indexOf("\u0001");
      if (i < 0) { c.fillStyle = "#111"; c.fillText(l.replace("\u0001", ""), bx + 15, ty); }
      else {
        c.fillStyle = "#111"; c.fillText(l.slice(0, i), bx + 15, ty);
        c.fillStyle = "#8b8f96"; c.fillText(l.slice(i + 1), bx + 15 + c.measureText(l.slice(0, i)).width, ty);
      }
      ty += 34;
    }
    c.fillStyle = cur.statusColor || "#8b98ad"; c.font = "22px system-ui, sans-serif";
    c.fillText(cur.status || (Speech ? "🎤 Dictate to speak it, or type with the keys (or a real keyboard)." : "Dictation isn't available in this browser -- type with the keys (or a real keyboard)."), 30, by + bh + 10);
    // keys
    const unit = (PX_W - 2 * K.left - 11 * K.gap) / 12;
    ROWS.forEach((row, r) => {
      row.forEach((k, i) => {
        const x = K.left + i * (unit + K.gap), y = K.top + r * (K.keyH + K.gap);
        const label = cur.shift && k.length === 1 && /[a-z]/.test(k) ? k.toUpperCase() : k;
        key(k, label, x, y, unit, k === "⇧" && cur.shift);
      });
    });
    const y = K.top + ROWS.length * (K.keyH + K.gap);
    const total = BOTTOM.reduce((a, b) => a + b[2], 0);
    const avail = PX_W - 2 * K.left - (BOTTOM.length - 1) * K.gap;
    let x = K.left;
    for (const [id, label, wgt] of BOTTOM) {
      const w = avail * wgt / total;
      key(id, id === "🎤" && rec ? "■ Stop" : label, x, y, w, id === "🎤" && !!rec, id === "done" ? "#238636" : null);
      x += w + K.gap;
    }
    tex.needsUpdate = true;
  }
  function key(id, label, x, y, w, on, color) {
    const hot = hover.some((h) => h && h.key === id);
    c.fillStyle = on ? "#a40e26" : hot ? "#1f6feb" : color || "rgba(255,255,255,0.10)";
    c.beginPath(); c.roundRect(x, y, w, K.keyH, 12); c.fill();
    c.fillStyle = "#fff"; c.font = `bold ${label.length > 2 ? 28 : 36}px system-ui, sans-serif`; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(label, x + w / 2, y + K.keyH / 2 + 1);
    c.textAlign = "left"; c.textBaseline = "top";
    keys.push({ id, x, y, w, h: K.keyH });
  }

  function type(id) {
    if (!cur) return;
    if (id === "⌫") cur.text = cur.text.slice(0, -1);
    else if (id === "⇧") cur.shift = !cur.shift;
    else if (id === "space") cur.text += " ";
    else if (id === "clear") cur.text = "";
    else if (id === "🎤") return rec ? stopDictation() : startDictation();
    else if (id === "done") return finish(true);
    else if (id === "cancel") return finish(false);
    else if (id.length === 1) {
      cur.text += cur.shift && /[a-z]/.test(id) ? id.toUpperCase() : id;
      cur.shift = false;
    }
    draw();
  }

  function startDictation() {
    if (!Speech) { cur.status = "Dictation isn't available in this browser."; cur.statusColor = "#ffa657"; return draw(); }
    try {
      rec = new Speech();
      rec.continuous = true; rec.interimResults = true; rec.lang = navigator.language || "en-US";
      rec.onresult = (ev) => {
        let interim = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const r = ev.results[i];
          if (r.isFinal) {
            const said = r[0].transcript.trim();
            if (said) cur.text += (cur.text && !/\s$/.test(cur.text) ? " " : "") + said;
          } else interim += r[0].transcript;
        }
        cur.interim = interim.trim();
        draw();
      };
      rec.onerror = (ev) => {
        cur.status = ev.error === "not-allowed" ? "The microphone isn't allowed for this page -- allow it in the browser, or type." :
                     ev.error === "no-speech" ? "Didn't hear anything -- try again." : `Dictation stopped: ${ev.error}`;
        cur.statusColor = "#ffa657";
      };
      rec.onend = () => { rec = null; if (cur) { cur.interim = ""; if (!cur.statusColor) cur.status = null; } draw(); };
      rec.start();
      cur.status = "Listening… speak, then 🎤 Stop (or Done)."; cur.statusColor = "#7ee787";
    } catch (err) {
      rec = null; cur.status = `Dictation couldn't start: ${err.message}`; cur.statusColor = "#ffa657";
    }
    draw();
  }
  function stopDictation() {
    try { rec?.stop(); } catch (_) { /* already stopped */ }
    if (cur) { cur.status = null; cur.statusColor = null; }
    draw();
  }

  function finish(ok) {
    const done = cur;
    if (rec) { try { rec.abort(); } catch (_) { /* fine */ } rec = null; }
    cur = null;
    mesh.visible = false;
    if (!done) return;
    const text = (done.text + (done.interim ? " " + done.interim : "")).trim();
    if (ok) done.onDone?.(text); else done.onCancel?.();
  }

  function open(opts) {
    if (cur) finish(false);
    cur = { title: opts.title, prompt: opts.prompt, text: opts.text || "", interim: "", shift: false,
            onDone: opts.onDone, onCancel: opts.onCancel, status: null };
    place();
    mesh.visible = true;
    draw();
  }

  window.addEventListener("keydown", (ev) => {
    if (!cur) return;
    if (ev.key === "Enter") { ev.preventDefault(); return finish(true); }
    if (ev.key === "Escape") { ev.preventDefault(); return finish(false); }
    if (ev.key === "Backspace") { ev.preventDefault(); cur.text = cur.text.slice(0, -1); return draw(); }
    if (ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey) { ev.preventDefault(); cur.text += ev.key; draw(); }
  }, true);

  function pointAt() {
    controllers.forEach((controller, i) => {
      const before = hover[i]?.key;
      hover[i] = null;
      if (!cur || !renderer.xr.isPresenting) return;
      tmpM.identity().extractRotation(controller.matrixWorld);
      raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld);
      raycaster.ray.direction.set(0, 0, -1).applyMatrix4(tmpM);
      const h = raycaster.intersectObject(mesh, false)[0];
      if (!h) { if (before) draw(); return; }
      const x = h.uv.x * PX_W, y = (1 - h.uv.y) * PX_H;
      const k = keys.find((r) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
      hover[i] = { key: k ? k.id : null };
      controller.getObjectByName("ray")?.material.color.set(k ? 0x58a6ff : 0x78aaff);
      if ((k?.id || null) !== (before || null)) draw();
    });
  }
  controllers.forEach((controller, i) => {
    controller.addEventListener("selectstart", () => { if (hover[i]?.key) type(hover[i].key); });
  });

  // while it's open it takes the trigger wherever you point (nothing behind it opens by accident)
  (window.vrHoverOwners ||= []).push((i) => !!cur && (!!hover[i] || renderer.xr.isPresenting));
  window.xrFrameHooks.push(pointAt);
  window.vrKeyboard = {
    open, isOpen: () => !!cur, close: () => finish(false),
    // for tests
    state: () => cur && { text: cur.text, interim: cur.interim, shift: cur.shift, status: cur.status, dictating: !!rec, speech: !!Speech,
                          keys: Object.fromEntries(keys.map((k) => [k.id, mesh.localToWorld(new THREE.Vector3((k.x + k.w / 2) / PX_W - 0.5, 0.5 - (k.y + k.h / 2) / PX_H, 0)).toArray()])) },
  };
}

(function waitForXR(attempts = 50) {
  const ctx = window.getXRContext?.();
  if (ctx && window.xrFrameHooks) return setup(ctx);
  if (attempts > 0) setTimeout(() => waitForXR(attempts - 1), 100);
})();
