// src/vrWatch.js -- VR "Watch values": little comic-book boxes floating above a character, each showing one of their
// values live. Opened from the context menu ("Watch values", src/vrDebug.js draws the list panel from spec()/choose()).
//
//   ★ Quick picks      mood, top intention, activity, stress, the next thing due (calendar event or expectation),
//                      reputation (backend/systems/watch_values.py)
//   any other field    every bool / number / short string on the character, grouped by top-level key; strings that take
//                      only a few values across everyone are enums (mostly what you'd watch)
//
// Per watched value: the text colour; whether the box also shows the previous value (and how long ago it changed);
// a warning -- the box flashes between two colours -- when a bool is true / false, an enum is one of the values you
// tick, a number goes above / below a threshold, a string changes. History is kept only here, in the browser, for
// HISTORY_S; the setup is remembered in this browser (localStorage).

import * as THREE from "three";

const POLL_S = 1;
const HISTORY_S = 10 * 60;
const PAGE = 10;
const STORE_KEY = "vrWatch.v1";
const FONT = "Bangers";
const FONT_STACK = `"${FONT}", "Comic Neue", "Comic Sans MS", Impact, sans-serif`;
const COLOURS = [["White", "#ffffff"], ["Yellow", "#ffe14a"], ["Cyan", "#5ee7ff"], ["Green", "#7dff7a"], ["Pink", "#ff7ad9"],
                 ["Orange", "#ffa040"], ["Red", "#ff5050"], ["Violet", "#b98cff"]];
const FLASHES = [["red / yellow", "#ff2a2a", "#ffe14a"], ["red / white", "#ff2a2a", "#ffffff"], ["orange / black", "#ff8c1a", "#111111"],
                 ["blue / white", "#2a6bff", "#ffffff"], ["magenta / cyan", "#ff2ad4", "#2af0ff"]];
const BOX_PX_H = 120;
const BOX_M_H = 0.2;

// the comic font, when the network allows (falls back to Comic Sans / Impact otherwise)
try {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `https://fonts.googleapis.com/css2?family=${FONT}&display=swap`;
  document.head.appendChild(link);
  document.fonts?.load(`64px "${FONT}"`).catch(() => {});
} catch (_) { /* no font, no problem */ }

const load = () => { try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}") || {}; } catch (_) { return {}; } };
const save = (cfg) => { try { localStorage.setItem(STORE_KEY, JSON.stringify(cfg)); } catch (_) { /* private window */ } };
const fmtVal = (v) => (v === null || v === undefined ? "—" : typeof v === "boolean" ? (v ? "YES" : "NO")
  : typeof v === "number" ? String(Math.round(v * 100) / 100) : String(v).replace(/_/g, " "));
const fmtAgo = (s) => (s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);
const shortPath = (p) => p.split(".").slice(-2).join(" ").replace(/_/g, " ");

function setup(ctx) {
  const { scene, dolly, sims } = ctx;
  const cfg = load();                     // charId -> [{path, label, type, options, colour, prev, warn, flash}]
  const nav = new Map();                  // charId -> {screen, group, page, path, groups, fields, loading, error}
  const live = new Map();                 // charId -> {values: {path: v}, history: {path: [{v, at}]}, polled, fetching}
  const boxes = new Map();                // "charId|path" -> {canvas, ctx, tex, sprite, drawnKey}
  let clock = 0, lastT = performance.now();
  const redraw = () => window.vrDebugRedraw?.();

  const watched = (id) => cfg[id] || [];
  const findW = (id, path) => watched(id).find((w) => w.path === path);
  const N = (id) => { if (!nav.has(id)) nav.set(id, { screen: "groups", page: 0 }); return nav.get(id); };

  async function fetchFields(id, group) {
    const n = N(id);
    n.loading = true; n.error = null; redraw();
    try {
      const r = await fetch(`/admin/watch/${encodeURIComponent(id)}/fields` + (group ? `?group=${encodeURIComponent(group)}` : ""));
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      n.groups = j.groups; if (group) n.fields = j.fields;
    } catch (err) { n.error = err.message; }
    n.loading = false; redraw();
  }

  function addWatch(id, f) {
    if (findW(id, f.path)) return;
    (cfg[id] ||= []).push({ path: f.path, label: f.label || shortPath(f.path), type: f.type, options: f.options || null,
                            colour: COLOURS[(watched(id).length) % COLOURS.length][1], prev: true, warn: {}, flash: 0 });
    save(cfg);
    const L = live.get(id); if (L) L.polled = -1e9;
  }
  function removeWatch(id, path) {
    cfg[id] = watched(id).filter((w) => w.path !== path);
    if (!cfg[id].length) delete cfg[id];
    save(cfg);
    dropBox(`${id}|${path}`);
  }

  // ---- the list panel (drawn by vrDebug.js) ----
  function spec(id) {
    const c = window.getWorldCharacter?.(id) || {};
    const n = N(id);
    const title = c.name || id;
    const back = { id: "w:back", label: "Back" };
    if (n.loading) return { title, subtitle: "Watch values", lines: ["Loading…"], buttons: [back] };
    if (n.error) return { title, subtitle: "Watch values", lines: [n.error], buttons: [back] };
    const list = watched(id);
    if (n.screen === "groups") {
      if (!n.groups) { fetchFields(id); return { title, subtitle: "Watch values", lines: ["Loading…"], buttons: [back] }; }
      const pages = Math.max(1, Math.ceil(n.groups.length / PAGE));
      const shown = n.groups.slice(n.page * PAGE, n.page * PAGE + PAGE);
      return {
        title, subtitle: "Watch values — pick a group",
        lines: [list.length ? `Watching: ${list.map((w) => w.label).join(", ")}` : "Nothing watched yet."],
        buttons: [...(list.length ? [{ id: "w:watched", label: `Watched (${list.length})…` }] : []),
                  ...shown.map((g) => ({ id: `w:g:${g.group}`, label: `${g.label}  (${g.count})` })),
                  ...(pages > 1 ? [{ id: "w:prev", label: "◀ Prev" }, { id: "w:next", label: `Next ▶  ${n.page + 1}/${pages}` }] : []),
                  back],
      };
    }
    if (n.screen === "watched") {
      return { title, subtitle: "Watch values — being watched", lines: ["Pick one to change how it shows."],
               buttons: [...list.map((w) => ({ id: `w:f:${w.path}`, label: `● ${w.label}` })), { id: "w:groups", label: "Back" }] };
    }
    if (n.screen === "fields") {
      if (!n.fields) return { title, subtitle: n.group, lines: ["Loading…"], buttons: [{ id: "w:groups", label: "Back" }] };
      const pages = Math.max(1, Math.ceil(n.fields.length / PAGE));
      const shown = n.fields.slice(n.page * PAGE, n.page * PAGE + PAGE);
      return {
        title, subtitle: `Watch values — ${n.group === "@" ? "quick picks" : n.group}`,
        lines: ["Pick a value to watch it (● = watched). Enums and bools first."],
        buttons: [...shown.map((f) => ({ id: `w:f:${f.path}`,
                    label: `${findW(id, f.path) ? "●" : "○"} ${f.label}: ${fmtVal(f.value)}`.slice(0, 60) + `  [${f.type}]` })),
                  ...(pages > 1 ? [{ id: "w:prev", label: "◀ Prev" }, { id: "w:next", label: `Next ▶  ${n.page + 1}/${pages}` }] : []),
                  { id: "w:groups", label: "Back" }],
      };
    }
    // a value's settings
    const w = findW(id, n.path);
    const f = (n.fields || []).find((x) => x.path === n.path) || w || { path: n.path, type: "string" };
    if (!w) return { title, subtitle: f.label || n.path, lines: [`Type: ${f.type}`, `Now: ${fmtVal(f.value)}`],
                     buttons: [{ id: "w:add", label: "Watch it" }, { id: "w:fieldsback", label: "Back" }] };
    const cur = live.get(id)?.values?.[w.path];
    const colourName = (COLOURS.find((x) => x[1] === w.colour) || ["?"])[0];
    const btn = [
      { id: "w:colour", label: `Text colour: ${colourName}` },
      { id: "w:prevtoggle", label: `Show previous value: ${w.prev ? "yes" : "no"}` },
      { id: "w:flash", label: `Warning flash: ${FLASHES[w.flash || 0][0]}` },
    ];
    if (w.type === "bool") btn.push({ id: "w:warnbool", label: `Warn when: ${w.warn.when === true ? "YES" : w.warn.when === false ? "NO" : "never"}` });
    if (w.type === "enum") for (const o of (w.options || f.options || []).slice(0, 8))
      btn.push({ id: `w:warnopt:${o}`, label: `${(w.warn.values || []).includes(o) ? "⚠" : "○"} warn on "${fmtVal(o)}"` });
    if (w.type === "number") {
      const step = stepFor(cur);
      btn.push({ id: "w:above-", label: "−" }, { id: "w:above", label: `Warn above: ${w.warn.above ?? "—"}` }, { id: "w:above+", label: "+" });
      btn.push({ id: "w:below-", label: "−" }, { id: "w:below", label: `Warn below: ${w.warn.below ?? "—"}` }, { id: "w:below+", label: "+" });
      w._step = step;
    }
    if (w.type === "string" || w.type === "enum") btn.push({ id: "w:warnchange", label: `Warn when it changes: ${w.warn.change ? "yes" : "no"}` });
    btn.push({ id: "w:remove", label: "Stop watching" }, { id: "w:fieldsback", label: "Back" });
    return { title, subtitle: `Watching ${w.label}`, lines: [`Type: ${w.type} · now: ${fmtVal(cur)}` + (w.type === "number" ? ` · step ${w._step}` : "")],
             buttons: btn };
  }

  function stepFor(v) {
    const a = Math.abs(Number(v) || 0);
    return a <= 1 ? 0.05 : Math.pow(10, Math.floor(Math.log10(a)) - 1);   // 4.8 -> 0.1, 42 -> 1, 350 -> 10
  }

  function choose(id, button) {
    const n = N(id);
    const b = button.slice(2);
    if (b === "back") { nav.delete(id); return "menu"; }
    if (b === "groups") { n.screen = "groups"; n.page = 0; return; }
    if (b === "watched") { n.screen = "watched"; return; }
    if (b === "prev") { n.page = Math.max(0, n.page - 1); return; }
    if (b === "next") {
      const total = (n.screen === "groups" ? n.groups : n.fields)?.length || 0;
      n.page = Math.min(Math.max(0, Math.ceil(total / PAGE) - 1), n.page + 1); return;
    }
    if (b.startsWith("g:")) { n.screen = "fields"; n.group = b.slice(2); n.page = 0; n.fields = null; fetchFields(id, n.group); return; }
    if (b.startsWith("f:")) { n.backTo = n.screen; n.screen = "value"; n.path = b.slice(2); return; }
    if (b === "fieldsback") { n.screen = n.backTo === "watched" ? "watched" : "fields"; return; }
    if (b === "add") { const f = (n.fields || []).find((x) => x.path === n.path); if (f) addWatch(id, f); return; }
    const w = findW(id, n.path);
    if (!w) return;
    if (b === "remove") { removeWatch(id, w.path); n.screen = n.backTo === "watched" ? "watched" : "fields"; return; }
    if (b === "colour") w.colour = COLOURS[(COLOURS.findIndex((x) => x[1] === w.colour) + 1) % COLOURS.length][1];
    if (b === "prevtoggle") w.prev = !w.prev;
    if (b === "flash") w.flash = ((w.flash || 0) + 1) % FLASHES.length;
    if (b === "warnbool") w.warn.when = w.warn.when === undefined ? true : w.warn.when === true ? false : undefined;
    if (b === "warnchange") w.warn.change = !w.warn.change;
    if (b.startsWith("warnopt:")) {
      const o = b.slice(8), vs = new Set(w.warn.values || []);
      vs.has(o) ? vs.delete(o) : vs.add(o); w.warn.values = [...vs];
    }
    const known = live.get(id)?.values?.[w.path] ?? (n.fields || []).find((x) => x.path === w.path)?.value;
    const cur = Number(known) || 0;
    for (const side of ["above", "below"]) {
      if (b === side) w.warn[side] = w.warn[side] == null ? Math.round(cur * 100) / 100 : null;   // set at the current value / clear
      if (b === `${side}+` || b === `${side}-`) {
        const base = w.warn[side] ?? cur;
        w.warn[side] = Math.round((base + (b.endsWith("+") ? 1 : -1) * (w._step || stepFor(cur))) * 1000) / 1000;
      }
    }
    save(cfg);
    const box = boxes.get(`${id}|${w.path}`); if (box) box.drawnKey = null;
  }

  // ---- values ----
  async function poll(id) {
    const L = live.get(id);
    if (!L || L.fetching) return;
    L.fetching = true;
    try {
      const paths = watched(id).map((w) => w.path).join(",");
      const r = await fetch(`/admin/watch/${encodeURIComponent(id)}/values?paths=${encodeURIComponent(paths)}`);
      if (r.ok) {
        const j = await r.json();
        for (const [p, v] of Object.entries(j.values || {})) {
          const h = (L.history[p] ||= []);
          if (!h.length || h[h.length - 1].v !== v) h.push({ v, at: clock });
          while (h.length > 1 && clock - h[1].at > HISTORY_S) h.shift();   // keep the one before the window as "previous"
          L.values[p] = v;
        }
      }
    } catch (_) { /* next poll */ }
    L.fetching = false;
  }

  function warning(w, L) {
    const v = L.values[w.path], h = L.history[w.path] || [];
    const wn = w.warn || {};
    if (w.type === "bool" && wn.when !== undefined && v === wn.when) return true;
    if (w.type === "enum" && (wn.values || []).includes(v)) return true;
    if (w.type === "number" && typeof v === "number" && ((wn.above != null && v > wn.above) || (wn.below != null && v < wn.below))) return true;
    if (wn.change && h.length > 1 && clock - h[h.length - 1].at < 30) return true;       // changed in the last 30 s
    return false;
  }

  // ---- boxes ----
  function makeBox() {
    const canvas = document.createElement("canvas");
    canvas.width = 512; canvas.height = BOX_PX_H;
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
    sprite.renderOrder = 998;
    sprite.userData.ignoreRaycast = true;
    scene.add(sprite);
    return { canvas, ctx: canvas.getContext("2d"), tex, sprite, drawnKey: null };
  }
  function dropBox(key) {
    const b = boxes.get(key);
    if (!b) return;
    scene.remove(b.sprite); b.tex.dispose(); b.sprite.material.dispose();
    boxes.delete(key);
  }
  function drawBox(b, w, L, warnOn, flashPhase) {
    const v = L.values[w.path];
    const h = L.history[w.path] || [];
    const prev = w.prev && h.length > 1 ? h[h.length - 2] : null;
    const changedAgo = h.length ? clock - h[h.length - 1].at : null;
    const fl = FLASHES[w.flash || 0];
    const bg = warnOn ? (flashPhase ? fl[1] : fl[2]) : "#fffbe8";
    const text = warnOn ? (flashPhase ? fl[2] : fl[1]) : w.colour;
    const key = [fmtVal(v), prev ? fmtVal(prev.v) : "", prev ? Math.round(changedAgo / 10) : "", bg, text, w.label].join("|");
    if (b.drawnKey === key) return;
    b.drawnKey = key;
    const ctx = b.ctx;
    const main = `${w.label.toUpperCase()}: ${fmtVal(v).toUpperCase()}`;
    const sub = prev ? `WAS ${fmtVal(prev.v).toUpperCase()} · ${fmtAgo(changedAgo)} AGO` : "";
    ctx.font = `bold 56px ${FONT_STACK}`;
    const wMain = ctx.measureText(main).width;
    ctx.font = `bold 30px ${FONT_STACK}`;
    const wSub = sub ? ctx.measureText(sub).width : 0;
    const W = Math.min(1600, Math.ceil(Math.max(wMain, wSub) + 48));
    const H = sub ? 120 : 84;
    if (b.canvas.width !== W || b.canvas.height !== H) {
      b.canvas.width = W; b.canvas.height = H;
      b.tex.dispose();                                       // a new size needs a new texture (or it stretches)
      b.tex = new THREE.CanvasTexture(b.canvas); b.tex.colorSpace = THREE.SRGBColorSpace;
      b.sprite.material.map = b.tex; b.sprite.material.needsUpdate = true;
    }
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = bg; ctx.strokeStyle = "#111"; ctx.lineWidth = 6;      // a comic-book panel
    ctx.beginPath(); ctx.roundRect(4, 4, W - 8, H - 8, 14); ctx.fill(); ctx.stroke();
    ctx.textBaseline = "top";
    const outlined = (t, x, y, size, fill) => {
      ctx.font = `bold ${size}px ${FONT_STACK}`;
      ctx.lineJoin = "round"; ctx.lineWidth = size / 6; ctx.strokeStyle = "#111"; ctx.strokeText(t, x, y);
      ctx.fillStyle = fill; ctx.fillText(t, x, y);
    };
    outlined(main, 24, 12, 56, text);
    if (sub) outlined(sub, 24, 76, 30, warnOn ? text : "#d9d9d9");
    b.tex.needsUpdate = true;
    b.sprite.userData.aspect = W / H;
    b.sprite.userData.h = H / BOX_PX_H;
  }

  function frame() {
    const t = performance.now();
    clock += (t - lastT) / 1000; lastT = t;
    const scale = Math.max(1, dolly.scale.x);
    const keep = new Set();
    for (const id of Object.keys(cfg)) {
      const list = watched(id);
      if (!list.length) continue;
      let L = live.get(id);
      if (!L) { L = { values: {}, history: {}, polled: -1e9, fetching: false }; live.set(id, L); }
      if (clock - L.polled > POLL_S) { L.polled = clock; poll(id); }
      const m = sims[id];
      if (!m) continue;
      const head = m.getWorldPosition(new THREE.Vector3());
      let y = head.y + 2.15 * Math.max(1, m.scale?.y || 1);
      const flashPhase = Math.floor(clock * 4) % 2 === 0;
      for (const w of list) {
        const key = `${id}|${w.path}`;
        keep.add(key);
        let b = boxes.get(key);
        if (!b) { b = makeBox(); boxes.set(key, b); }
        drawBox(b, w, L, warning(w, L), flashPhase);
        const h = BOX_M_H * (b.sprite.userData.h || 0.7) * scale;
        b.sprite.scale.set(h * (b.sprite.userData.aspect || 4), h, 1);
        b.sprite.position.set(head.x, y + h / 2, head.z);
        y += h + 0.03 * scale;
      }
    }
    for (const key of [...boxes.keys()]) if (!keep.has(key)) dropBox(key);
  }

  window.xrFrameHooks.push(frame);
  window.vrWatch = {
    spec, choose, watching: (id) => watched(id).length,
    // for tests
    state: (id) => ({ watched: watched(id).map((w) => ({ path: w.path, colour: w.colour, prev: w.prev, warn: w.warn, type: w.type })),
                      values: live.get(id)?.values || {}, history: Object.fromEntries(Object.entries(live.get(id)?.history || {}).map(([k, v]) => [k, v.length])),
                      boxes: [...boxes.keys()].filter((k) => k.startsWith(id + "|")),
                      warnings: watched(id).map((w) => warning(w, live.get(id) || { values: {}, history: {} })),
                      screen: N(id).screen }),
  };
}

(function waitForXR(attempts = 50) {
  const ctx = window.getXRContext?.();
  if (ctx && window.xrFrameHooks) return setup(ctx);
  if (attempts > 0) setTimeout(() => waitForXR(attempts - 1), 100);
})();
