// src/vrDebug.js -- the VR debugging interface: move around the map as a disembodied game master, point at a character
// and open a context menu (inspect them, their persona, follow them). Loaded by operator_view.html after main.js;
// everything goes through main.js's window.getXRContext() / window.xrFrameHooks, so main.js stays the owner of the
// renderer, scene and controllers.
//
// Getting around (no avatar):
//   left stick            glide, the way you're looking (main.js), faster the bigger you are
//   right stick ←/→       turn in 30° steps
//   right stick ↑/↓       fly up / down
//   one grip held         grab the world and drag it
//   both grips held       pull apart / together to shrink / grow yourself (human size ... a giant over a tabletop map),
//                         twist to turn the world
//   B / Y                 back to human size, where you are
//
// Characters:
//   trigger on a character    a context menu, about a metre in front of you towards them (readable at any distance),
//                             with a line to them: Inspect, Persona, Follow, Show on desktop, Close
//   trigger on a menu button  that option; trigger on empty space closes the menu
//
// Debug panels (widgets made in the panel designer, panels.html; src/panels/):
//   Show panels               a character's enabled panels (and on-demand ones with something to show) float beside them
//   pointing at a panel       trigger clicks rows, data points and page buttons; right stick ←/→ pans its timeline,
//                             ↑/↓ zooms it (instead of turning / flying)
//   Debug Draw                a list of things to draw into the world for them (routes, targets, senses...):
//                             src/vrDebugDraw.js
//   Manage panels             each panel's state (enabled / on demand / disabled), add a panel to just this one, switch
//                             the active layout (a list, like a dropdown), save, save as a new layout (up to 6)
// While director mode is on (operator_view.js: hold a grip still for a second), the trigger is director mode's.
//
// HTML doesn't render inside a headset, so the panels are drawn on a canvas and shown as a texture on a plane.

import * as THREE from "three";
import * as panelApi from "./panels/api.js";
import { renderPanel, clickPanel, hitAt, panTimeline, zoomTimeline, hasContent } from "./panels/render.js";

// ---- a panel: a canvas texture on a plane, with buttons you can point at --------------------------------------------

const PX_PER_M = 1400;               // canvas pixels per metre of panel (at human scale)
const PANEL_W_M = 0.62;

class VRPanel {
  constructor() {
    this.canvas = document.createElement("canvas");
    this.canvas.width = Math.round(PANEL_W_M * PX_PER_M);
    this.canvas.height = 400;
    this.ctx = this.canvas.getContext("2d");
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1),
      new THREE.MeshBasicMaterial({ map: this.texture, transparent: true, depthTest: false }));
    this.mesh.renderOrder = 999;
    this.mesh.userData.ignoreRaycast = true;        // main.js's character raycast skips it
    this.buttons = [];                               // [{id, x, y, w, h}] in canvas pixels
    this.hover = null;
    this.spec = null;
  }

  _wrap(text, maxW) {
    const words = String(text ?? "").split(/\s+/);
    const lines = [];
    let cur = "";
    for (const w of words) {
      const t = cur ? cur + " " + w : w;
      if (this.ctx.measureText(t).width > maxW && cur) { lines.push(cur); cur = w; } else cur = t;
    }
    if (cur) lines.push(cur);
    return lines;
  }

  // spec: {title, subtitle, lines: [string | {text, color, bar: 0..1}], buttons: [{id, label}]}
  draw(spec) {
    this.spec = spec;
    const c = this.ctx, W = this.canvas.width, PAD = 36;
    // measure first (the height depends on the wrapped text)
    c.font = "34px system-ui, sans-serif";
    const body = [];
    for (const ln of spec.lines || []) {
      const o = typeof ln === "string" ? { text: ln } : ln;
      if (o.bar != null) body.push({ ...o, h: 52 });
      else for (const piece of this._wrap(o.text, W - 2 * PAD)) body.push({ ...o, text: piece, h: 46 });
    }
    const BTN_H = 84, GAP = 14;
    const H = PAD + 70 + (spec.subtitle ? 44 : 0) + 16 + body.reduce((a, b) => a + b.h, 0) + 20
      + (spec.buttons || []).length * (BTN_H + GAP) + PAD;
    if (this.canvas.height !== H) this.canvas.height = H;

    c.clearRect(0, 0, W, H);
    c.fillStyle = "rgba(14,17,24,0.94)";
    c.strokeStyle = "rgba(120,170,255,0.55)";
    c.lineWidth = 4;
    c.beginPath(); c.roundRect(2, 2, W - 4, H - 4, 28); c.fill(); c.stroke();

    let y = PAD;
    c.fillStyle = "#e8eef8"; c.font = "bold 52px system-ui, sans-serif"; c.textBaseline = "top";
    c.fillText(spec.title || "", PAD, y); y += 70;
    if (spec.subtitle) { c.fillStyle = "#8b98ad"; c.font = "32px system-ui, sans-serif"; c.fillText(spec.subtitle, PAD, y); y += 44; }
    y += 16;
    for (const o of body) {
      if (o.bar != null) {
        c.fillStyle = "#c9d1d9"; c.font = "32px system-ui, sans-serif";
        c.fillText(o.text, PAD, y + 8);
        const bx = PAD + 300, bw = W - PAD - bx;
        c.fillStyle = "rgba(255,255,255,0.12)"; c.fillRect(bx, y + 12, bw, 28);
        c.fillStyle = o.color || (o.bar > 0.75 ? "#f85149" : o.bar > 0.5 ? "#d29922" : "#3fb950");
        c.fillRect(bx, y + 12, bw * Math.max(0, Math.min(1, o.bar)), 28);
      } else {
        c.fillStyle = o.color || "#c9d1d9"; c.font = "34px system-ui, sans-serif";
        c.fillText(o.text, PAD, y);
      }
      y += o.h;
    }
    y += 20;
    this.buttons = [];
    for (const b of spec.buttons || []) {
      const r = { id: b.id, x: PAD, y, w: W - 2 * PAD, h: BTN_H };
      this.buttons.push(r);
      c.fillStyle = this.hover === b.id ? "#1f6feb" : "rgba(255,255,255,0.08)";
      c.beginPath(); c.roundRect(r.x, r.y, r.w, r.h, 18); c.fill();
      c.fillStyle = "#ffffff"; c.font = "bold 38px system-ui, sans-serif"; c.textBaseline = "middle";
      c.fillText(b.label, r.x + 28, r.y + r.h / 2);
      c.textBaseline = "top";
      y += BTN_H + GAP;
    }
    if (this._size && this._size !== `${W}x${H}`) this.texture.dispose();   // a new size needs new GPU storage (see vrBuilder.js)
    this._size = `${W}x${H}`;
    this.texture.needsUpdate = true;
    this.baseW = PANEL_W_M;                          // metres at human scale; placeMenu grows it with the viewer
    this.baseH = PANEL_W_M * H / W;
  }

  setHover(id) {
    if (id === this.hover) return;
    this.hover = id;
    if (this.spec) this.draw(this.spec);
  }

  buttonAt(uv) {                                     // uv of a ray hit on the plane -> button id
    const x = uv.x * this.canvas.width, y = (1 - uv.y) * this.canvas.height;
    const b = this.buttons.find((r) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
    return b ? b.id : null;
  }
}

// ---- the debugging interface ---------------------------------------------------------------------------------------

const MENU_DISTANCE_M = 1.0;      // how far in front of you a panel opens (times your scale)
const BODY_HEIGHT_M = 1.8;        // a character, for pointing at: a line from their feet up this far
const PICK_RADIUS_M = 0.35;       // ...within this of the ray up close
const PICK_CONE = Math.tan(THREE.MathUtils.degToRad(2.5));   // ...or within 2.5° of it far away (and when you are giant)
const MIN_SCALE = 1, MAX_SCALE = 60;
const SNAP_TURN = Math.PI / 6;
const REFRESH_SECONDS = 0.5;
const WIDGET_PX = 900;            // panel canvas width
const WIDGET_W_M = 0.6;           // panel width in the world (times your scale)
const WIDGET_REDRAW_S = 0.5;
const LAYOUT_REFRESH_S = 10;      // re-read an entity's panels and layout this often
const STATE_NAME = { enabled: "Enabled", on_demand: "On demand", disabled: "Disabled" };
const NEXT_STATE = { enabled: "on_demand", on_demand: "disabled", disabled: "enabled" };

function setup(ctx) {
  const { renderer, scene, dolly, camera, controllers, hover, sims } = ctx;
  const homeY = dolly.position.y;
  const raycaster = new THREE.Raycaster();
  const tmpM = new THREE.Matrix4();

  const panel = new VRPanel();
  panel.mesh.visible = false;
  scene.add(panel.mesh);
  const tether = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
    new THREE.LineBasicMaterial({ color: 0x78aaff, transparent: true, opacity: 0.6, depthTest: false }));
  tether.renderOrder = 998;
  tether.visible = false;
  tether.userData.ignoreRaycast = true;
  scene.add(tether);

  const state = {
    menu: null,            // {charId, view: "menu" | "inspect" | "persona", persona, refreshed}
    follow: null,          // {charId, offset: Vector3}
    panelHover: [null, null],
    grab: [null, null],    // per hand: {last: Vector3 (dolly-local)} while its grip is held
    pinch: null,           // both grips: {d0, scale0, angle0, yaw0}
    dragged: [false, false],
    turnLatched: [false, false],
    resetLatched: [false, false],
    clock: 0,
    shown: new Set(),      // characters whose panels float beside them
    entityPanels: new Map(),   // charId -> {data: /admin/panels/for result, at}
    widgets: new Map(),    // "charId|templateId" -> {canvas, ctx, texture, mesh, view, hits, height, drawn}
    widgetHover: [null, null],   // per hand: {key, hit} while pointing at a panel widget
    feed: new panelApi.PanelFeed(),
  };
  window.vrDebugShowPanels = (charId) => { state.shown.add(charId); state.entityPanels.delete(charId); };   // vrBuilder: just saved one
  window.xrWasDragged = (i) => !!state.dragged[i];   // operator_view.js: a grip that moved is a drag, not "director mode"
  // read-only, for tests (and a future in-headset debug overlay): what's open, and where a panel button is in the world
  window.getVRDebugState = () => ({
    menu: state.menu && { charId: state.menu.charId, view: state.menu.view, persona: !!state.menu.persona },
    following: state.follow?.charId || null, panelVisible: panel.mesh.visible, panelHover: [...state.panelHover],
    title: panel.spec?.title || null, lines: (panel.spec?.lines || []).map((l) => (typeof l === "string" ? l : l.text)),
    buttons: panel.buttons.map((b) => b.id),
    pick: (i) => pickCharacter(controllers[i]),     // whom controller i is pointing at
    shown: [...state.shown],
    widgets: [...state.widgets.entries()].map(([k, w]) => ({ key: k, visible: w.mesh.visible, page: w.view.page || 0, selected: w.view.selected ?? null,
      timeline: w.view.timeline ? { t0: w.view.timeline.t0, t1: w.view.timeline.t1, user: !!w.view.timeline.user } : null,
      regions: w.hits.map((h) => ({ type: h.action?.type, key: h.action?.key, delta: h.action?.delta, size: h.action?.size, timeline: !!h.timeline,
                                    world: widgetWorld(w, h.x + h.w / 2, h.y + h.h / 2) })) })),
    widgetHover: state.widgetHover.map((h) => h && { key: h.key, type: h.hit?.action?.type }),
    manage: state.menu?.manage ? { active: state.menu.manage.draft.active, layouts: Object.keys(state.menu.manage.draft.layouts),
                                   sub: state.menu.manage.sub || null } : null,
    buttonWorld: (id) => {
      const b = panel.buttons.find((r) => r.id === id);
      if (!b) return null;
      const u = (b.x + b.w / 2) / panel.canvas.width, v = (b.y + b.h / 2) / panel.canvas.height;
      const p = panel.mesh.localToWorld(new THREE.Vector3(u - 0.5, 0.5 - v, 0));
      return [p.x, p.y, p.z];
    },
  });

  const headWorld = () => camera.getWorldPosition(new THREE.Vector3());
  const charHead = (id) => {
    const m = sims[id];
    if (!m) return null;
    const p = m.getWorldPosition(new THREE.Vector3());
    p.y += 1.75;
    return p;
  };

  // ---- panel contents ----
  const name = (c, id) => c?.name || id;
  function menuSpec(id) {
    const c = window.getWorldCharacter(id);
    return {
      title: name(c, id), subtitle: [c?.age ? `${c.age}` : null, c?.emotion, c?.mood?.name].filter(Boolean).join(" · "),
      lines: [], buttons: [
        { id: "inspect", label: "Inspect" }, { id: "persona", label: "Persona" },
        { id: "follow", label: state.follow?.charId === id ? "Stop following" : "Follow" },
        { id: "panels", label: state.shown.has(id) ? "Hide panels" : "Show panels" },
        { id: "manage", label: "Manage panels" },
        { id: "design", label: "Design a panel" },
        { id: "debugdraw", label: window.vrDebugDraw?.activeFor().includes(id) ? "Debug Draw  •" : "Debug Draw" },
        { id: "desktop", label: "Show in desktop inspector" }, { id: "close", label: "Close" },
      ],
    };
  }
  function inspectSpec(id) {
    const c = window.getWorldCharacter(id) || {};
    const b = c.body || {};
    const lines = [];
    const act = c.activity;
    lines.push(`Doing: ${act ? String(act.type).replace(/_/g, " ") + (act.phase ? ` (${act.phase})` : "") : "nothing"}`);
    if (c.current_intention?.type) lines.push(`Intent: ${String(c.current_intention.type).replace(/_/g, " ")}`);
    if (c.floor_status) lines.push({ text: `In conversation: ${c.floor_status.replace(/_/g, " ")}`, color: "#79c0ff" });
    const bar = (label, v, invert) => v == null ? null : { text: label, bar: invert ? 1 - v / 100 : v / 100 };
    for (const l of [bar("Hunger", b.hunger), bar("Tiredness", b.fatigue), bar("Bladder", b.bladder),
                     bar("Dirty", b.hygiene, true), bar("Thirst", b.hydration, true), bar("Stress", c.stress)]) if (l) lines.push(l);
    const ints = (c.active_intentions || []).slice(0, 4);
    if (ints.length) {
      lines.push({ text: "Wants to:", color: "#8b98ad" });
      for (const i of ints) lines.push({ text: `• ${String(i.type).replace(/_/g, " ")}${i.stage ? ` (stage ${i.stage})` : ""}`,
                                         color: i.stage >= 2 ? "#f85149" : i.stage === 1 ? "#d29922" : "#c9d1d9" });
    }
    if (c.last_thought) lines.push({ text: `“${c.last_thought}”`, color: "#d2a8ff" });
    return { title: name(c, id), subtitle: [c.emotion, c.mood?.name].filter(Boolean).join(" · "), lines,
             buttons: [{ id: "back", label: "Back" }, { id: "close", label: "Close" }] };
  }
  function personaSpec(id) {
    const p = state.menu?.persona;
    const c = window.getWorldCharacter(id) || {};
    if (!p) return { title: name(c, id), subtitle: "Persona", lines: ["Loading…"], buttons: [{ id: "back", label: "Back" }] };
    if (p.error) return { title: name(c, id), subtitle: "Persona", lines: [p.error], buttons: [{ id: "back", label: "Back" }] };
    const list = (label, xs) => xs?.length ? [{ text: label, color: "#8b98ad" }, xs.join(", ")] : [];
    const moodNow = p.current_mood && (p.mood_traits || {})[p.current_mood];
    return {
      title: name(c, id), subtitle: `Persona${p.current_mood ? " · mood: " + p.current_mood : ""}`,
      lines: [
        ...list("Traits", [...(p.traits || []), ...(p.personality_traits || [])]),
        ...(moodNow?.length ? [{ text: "Showing in this mood", color: "#8b98ad" }, { text: moodNow.join(", "), color: "#79c0ff" }] : []),
        ...list("Speech quirks", p.speech_quirks), ...list("Insecure about", p.insecurities),
        ...list("Confidence rests on", p.confidence_sources),
        ...(p.trait_log?.length ? [{ text: "Last trait change", color: "#8b98ad" },
            (() => { const e = p.trait_log[p.trait_log.length - 1];
                     return `${(e.added || []).map((t) => "+" + t).join(" ")} ${(e.removed || []).map((t) => "−" + t).join(" ")} — ${e.why}`; })()] : []),
      ],
      buttons: [{ id: "back", label: "Back" }, { id: "close", label: "Close" }],
    };
  }
  // Manage panels: the active layout's panels and their states, adding one, switching layouts, saving
  function drawSpec(id) {                                   // the Debug Draw list (src/vrDebugDraw.js does the drawing)
    const c = window.getWorldCharacter(id) || {};
    const dd = window.vrDebugDraw;
    if (!dd) return { title: name(c, id), subtitle: "Debug Draw", lines: ["Debug Draw isn't loaded."], buttons: [{ id: "back", label: "Back" }] };
    const box = (on) => (on === true ? "☑" : on === "some" ? "◩" : "☐");
    return {
      title: name(c, id), subtitle: "Debug Draw — point and pull the trigger to switch on / off",
      lines: dd.summary(id),
      buttons: [...dd.options(id).map((o) => ({ id: `dd:${o.id}`, label: `${o.parent ? "" : "      "}${box(o.on)}  ${o.label}` })),
                { id: "back", label: "Back" }, { id: "close", label: "Close" }],
    };
  }
  function manageSpec(id) {
    const c = window.getWorldCharacter(id) || {};
    const mg = state.menu.manage;
    if (!mg || mg.loading) return { title: name(c, id), subtitle: "Panels", lines: ["Loading…"], buttons: [{ id: "back", label: "Back" }] };
    if (mg.error) return { title: name(c, id), subtitle: "Panels", lines: [mg.error], buttons: [{ id: "back", label: "Back" }] };
    const dr = mg.draft, lay = dr.layouts[dr.active] ||= { panels: {} };
    const names = Object.keys(dr.layouts);
    if (mg.sub === "layouts") return {
      title: "Switch layout", subtitle: `${name(c, id)} · pick the active one, then Save`, lines: [],
      buttons: [...names.map((n) => ({ id: `lay:${n}`, label: `${n === dr.active ? "● " : "○ "}${n}` })), { id: "manage_back", label: "Back" }] };
    if (mg.sub === "edit") {
      const byId = new Map(mg.all.map((t) => [t.id, t]));
      return { title: "Edit a panel", subtitle: "opens it on the workbench", lines: [],
               buttons: [...mg.panelIds().filter((tid) => byId.has(tid)).map((tid) => ({ id: `edit:${tid}`, label: `${byId.get(tid).name || tid} (${byId.get(tid).type})` })),
                         { id: "manage_back", label: "Back" }] };
    }
    if (mg.sub === "add") {
      const others = mg.all.filter((t) => !mg.panelIds().includes(t.id));
      return { title: "Add a panel", subtitle: `just for ${name(c, id)}`, lines: others.length ? [] : ["Every panel is here already."],
               buttons: [...others.map((t) => ({ id: `add:${t.id}`, label: `${t.name || t.id} (${t.type})` })), { id: "manage_back", label: "Back" }] };
    }
    const byId = new Map(mg.all.map((t) => [t.id, t]));
    return {
      title: `Panels: ${name(c, id)}`, subtitle: `Layout “${dr.active}” · ${names.length} of ${1 + 5}${mg.dirty ? " · unsaved" : ""}`,
      lines: mg.panelIds().length ? [{ text: "Trigger a panel to change its state", color: "#8b98ad" }] : ["No panels yet -- add one, or make some in the panel designer."],
      buttons: [
        { id: "layouts", label: `Layout: ${dr.active}  ▾` },
        ...mg.panelIds().map((tid) => ({ id: `st:${tid}`, label: `${(byId.get(tid) || {}).name || tid}: ${STATE_NAME[mg.stateOf(tid)]}` })),
        { id: "add", label: "Add a panel…" },
        { id: "edit", label: "Edit a panel…" },
        { id: "save", label: mg.dirty ? "Save  •" : "Save" },
        ...(names.length < 6 ? [{ id: "saveas", label: "Save as a new layout" }] : []),
        { id: "back", label: "Back" },
      ],
    };
  }

  async function openManage(id) {
    const m = state.menu;
    m.view = "manage";
    m.manage = { loading: true };
    redraw();
    try {
      const [all, data] = await Promise.all([panelApi.listTemplates(), panelApi.panelsFor("character", id)]);
      if (state.menu !== m) return;
      const draft = { active: data.active, layouts: JSON.parse(JSON.stringify(data.layouts)) };
      const mg = m.manage = { all: all.templates, data, draft, sub: null, dirty: false };
      mg.panelIds = () => {
        const ids = data.templates.map((t) => t.id);
        for (const tid of Object.keys(draft.layouts[draft.active]?.panels || {})) if (!ids.includes(tid)) ids.push(tid);
        return ids;
      };
      mg.stateOf = (tid) => (draft.layouts[draft.active]?.panels || {})[tid]
        || (all.templates.find((t) => t.id === tid) || {}).default_state || "enabled";
    } catch (err) {
      if (state.menu === m) m.manage = { error: `couldn't load the panels: ${err.message}` };
    }
    redraw();
  }

  async function saveManage(asNew) {
    const m = state.menu, mg = m.manage;
    const dr = mg.draft;
    if (asNew) {
      let n = Object.keys(dr.layouts).length + 1, nm = `Layout ${n}`;
      while (dr.layouts[nm]) nm = `Layout ${++n}`;
      dr.layouts[nm] = JSON.parse(JSON.stringify(dr.layouts[dr.active] || { panels: {} }));
      dr.active = nm;
    }
    for (const l of Object.values(dr.layouts)) for (const tid of mg.panelIds()) l.panels[tid] ||= mg.stateOf(tid);
    try {
      mg.data = await panelApi.saveLayouts("character", m.charId, dr);
      mg.dirty = false;
      state.entityPanels.delete(m.charId);                   // shown panels pick up the new layout now
    } catch (err) {
      mg.error = `couldn't save: ${err.message}`;
    }
    redraw();
  }

  function redraw() {
    const m = state.menu;
    if (!m) return;
    panel.draw(m.view === "inspect" ? inspectSpec(m.charId) : m.view === "persona" ? personaSpec(m.charId)
      : m.view === "manage" ? manageSpec(m.charId) : m.view === "draw" ? drawSpec(m.charId) : menuSpec(m.charId));
  }

  function openMenu(id) {
    state.menu = { charId: id, view: "menu", persona: null, refreshed: 0 };
    panel.hover = null;
    redraw();
    panel.mesh.visible = tether.visible = true;
  }
  function closeMenu() {
    state.menu = null;
    panel.mesh.visible = tether.visible = false;
  }
  async function loadPersona(id) {
    try {
      const r = await fetch(`/api/characters/${encodeURIComponent(id)}/persona`);
      const out = await r.json();
      if (state.menu?.charId !== id) return;
      state.menu.persona = out.ok ? out : { error: out.error || "couldn't load" };
    } catch (err) {
      if (state.menu?.charId === id) state.menu.persona = { error: err.message };
    }
    redraw();
  }
  function choose(button) {
    const m = state.menu;
    if (!m) return;
    if (button === "close") return closeMenu();
    if (button === "back") { m.view = "menu"; return redraw(); }
    if (button === "inspect") { m.view = "inspect"; return redraw(); }
    if (button === "persona") { m.view = "persona"; m.persona = null; redraw(); return loadPersona(m.charId); }
    if (button === "desktop") { window.setSelectedCharacterId?.(m.charId); return; }
    if (button === "panels") {
      if (state.shown.has(m.charId)) state.shown.delete(m.charId); else state.shown.add(m.charId);
      return redraw();
    }
    if (button === "manage") return openManage(m.charId);
    if (button === "debugdraw") { m.view = "draw"; return redraw(); }
    if (button.startsWith("dd:")) { window.vrDebugDraw?.toggle(m.charId, button.slice(3)); return redraw(); }
    if (button === "design") { const id = m.charId; closeMenu(); window.vrBuilder?.open(id); return; }
    const mg = m.manage;
    if (mg && !mg.loading && !mg.error) {
      if (button === "layouts") { mg.sub = "layouts"; return redraw(); }
      if (button === "add") { mg.sub = "add"; return redraw(); }
      if (button === "edit") { mg.sub = "edit"; return redraw(); }
      if (button.startsWith("edit:")) {
        const t = mg.all.find((x) => x.id === button.slice(5)), id = m.charId;
        if (t) { closeMenu(); window.vrBuilder?.open(id, t); }
        return;
      }
      if (button === "manage_back") { mg.sub = null; return redraw(); }
      if (button.startsWith("lay:")) { mg.draft.active = button.slice(4); mg.sub = null; mg.dirty = true; return redraw(); }
      if (button.startsWith("add:")) {
        (mg.draft.layouts[mg.draft.active] ||= { panels: {} }).panels[button.slice(4)] = "enabled";
        mg.sub = null; mg.dirty = true; return redraw();
      }
      if (button.startsWith("st:")) {
        const tid = button.slice(3);
        (mg.draft.layouts[mg.draft.active] ||= { panels: {} }).panels[tid] = NEXT_STATE[mg.stateOf(tid)];
        mg.dirty = true; return redraw();
      }
      if (button === "save") return saveManage(false);
      if (button === "saveas") return saveManage(true);
    }
    if (button === "follow") {
      if (state.follow?.charId === m.charId) state.follow = null;
      else {
        const head = charHead(m.charId);
        if (head) state.follow = { charId: m.charId, offset: dolly.position.clone().sub(head) };
      }
      return redraw();
    }
  }

  // ---- trigger ----
  controllers.forEach((controller, i) => {
    controller.addEventListener("selectstart", () => {
      if (!renderer.xr.isPresenting) return;
      if (window.vrBuilder?.isOpen() && window.vrBuilder.hovering(controller)) return;   // the workbench (vrBuilder.js) has it
      if (state.panelHover[i]) return choose(state.panelHover[i]);
      const wh = state.widgetHover[i];
      if (wh) {
        const w = state.widgets.get(wh.key);
        if (w && wh.hit && clickPanel(w.view, wh.hit.action)) w.drawn = -1;   // redraw it now
        return;
      }
      if (window.getDirectorModeActive?.()) return;            // director mode owns the trigger
      if (hover[i]) return openMenu(hover[i]);
      if (state.menu) closeMenu();
    });
  });

  // ---- every frame ----
  const local = (controller) => controller.position.clone();   // controller position in the dolly's own frame
  const toWorldDelta = (v) => v.applyQuaternion(dolly.quaternion).multiplyScalar(dolly.scale.x);
  function rotateDollyAround(pivot, angle) {
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), angle);
    dolly.position.sub(pivot).applyQuaternion(q).add(pivot);
    dolly.quaternion.premultiply(q);
  }

  function navigate() {
    const pads = controllers.map((c) => c.userData.inputSource?.gamepad || null);
    const hands = controllers.map((c) => c.userData.inputSource?.handedness || null);
    const gripping = pads.map((g) => !!g?.buttons?.[1]?.pressed);

    // both grips: scale + turn around the midpoint between the hands
    if (gripping[0] && gripping[1]) {
      const a = local(controllers[0]), b = local(controllers[1]);
      const d = Math.max(0.05, a.distanceTo(b));
      const angle = Math.atan2(b.z - a.z, b.x - a.x);
      if (!state.pinch) state.pinch = { d0: d, scale0: dolly.scale.x, angle0: angle };
      const mid = a.clone().add(b).multiplyScalar(0.5);
      const midWorldBefore = dolly.localToWorld(mid.clone());
      const s = THREE.MathUtils.clamp(state.pinch.scale0 * state.pinch.d0 / d, MIN_SCALE, MAX_SCALE);
      dolly.scale.setScalar(s);
      dolly.updateMatrixWorld();
      const midWorldAfter = dolly.localToWorld(mid.clone());
      dolly.position.add(midWorldBefore.sub(midWorldAfter));         // the point between your hands stays put
      const dAngle = angle - state.pinch.angle0;
      if (Math.abs(dAngle) > 0.002) { rotateDollyAround(dolly.localToWorld(mid.clone()), dAngle); state.pinch.angle0 = angle; }
      state.dragged[0] = state.dragged[1] = true;
      state.grab = [null, null];
      state.follow = null;
      return;
    }
    state.pinch = null;

    // one grip: drag the world
    controllers.forEach((controller, i) => {
      if (!gripping[i]) { state.grab[i] = null; state.dragged[i] = false; return; }
      const now = local(controller);
      if (!state.grab[i]) { state.grab[i] = { last: now, start: now.clone() }; return; }
      const delta = state.grab[i].last.clone().sub(now);
      if (now.distanceTo(state.grab[i].start) > 0.04) state.dragged[i] = true;
      if (state.dragged[i]) { dolly.position.add(toWorldDelta(delta)); state.follow = null; }
      state.grab[i].last = now;
    });

    // right stick: snap turn and fly; B/Y: back to human size
    controllers.forEach((controller, i) => {
      const g = pads[i];
      if (!g) return;
      const isRight = hands[i] === "right";
      const onWidget = state.widgetHover[i];
      if (isRight && g.axes.length >= 4 && onWidget) {
        const [, , x, y] = g.axes;
        const w = state.widgets.get(onWidget.key);
        if (w && (Math.abs(x) > 0.2 || Math.abs(y) > 0.2)) {
          if (Math.abs(x) > 0.2) panTimeline(w.view, x * 0.03);
          if (Math.abs(y) > 0.2) zoomTimeline(w.view, 1 + y * 0.04, onWidget.frac ?? 0.5);
          w.drawn = -1;
        }
      } else if (isRight && g.axes.length >= 4) {
        const [, , x, y] = g.axes;
        if (Math.abs(x) > 0.7 && !state.turnLatched[i]) {
          rotateDollyAround(headWorld(), x > 0 ? -SNAP_TURN : SNAP_TURN);
          state.turnLatched[i] = true;
        } else if (Math.abs(x) < 0.3) state.turnLatched[i] = false;
        if (Math.abs(y) > 0.2) { dolly.position.y = Math.max(homeY - 1, dolly.position.y - y * 0.05 * dolly.scale.x); state.follow = null; }
      }
      const reset = !!g.buttons?.[5]?.pressed;                 // B (right) / Y (left)
      if (reset && !state.resetLatched[i]) {
        const head = headWorld();
        dolly.scale.setScalar(1);
        dolly.updateMatrixWorld();
        const headAfter = headWorld();
        dolly.position.x += head.x - headAfter.x;
        dolly.position.z += head.z - headAfter.z;
        dolly.position.y = homeY;
      }
      state.resetLatched[i] = reset;
    });
  }

  // Pointing at a character doesn't depend on their mesh (whose shape, origin and size vary by model): each is a vertical
  // line from their feet up BODY_HEIGHT_M, and the ray takes the one it passes closest to, within a radius that widens
  // with distance (a cone), so far-away characters -- and everyone, when you are a giant -- are still easy to point at.
  const _seg = [new THREE.Vector3(), new THREE.Vector3()];
  function pickCharacter(controller) {
    tmpM.identity().extractRotation(controller.matrixWorld);
    const ray = new THREE.Ray(new THREE.Vector3().setFromMatrixPosition(controller.matrixWorld),
                              new THREE.Vector3(0, 0, -1).applyMatrix4(tmpM));
    let best = null, bestScore = Infinity;
    const onRay = new THREE.Vector3(), onSeg = new THREE.Vector3();
    for (const [id, m] of Object.entries(sims)) {
      if (!m.visible || m.userData.ignoreRaycast) continue;
      m.getWorldPosition(_seg[0]);
      _seg[1].copy(_seg[0]).y += BODY_HEIGHT_M;
      const d2 = ray.distanceSqToSegment(_seg[0], _seg[1], onRay, onSeg);
      const along = onRay.distanceTo(ray.origin);
      if (along <= 0.05) continue;
      const tol = Math.max(PICK_RADIUS_M * dolly.scale.x, along * PICK_CONE);
      const score = Math.sqrt(Math.max(0, d2)) / tol;          // (d2 can come back a hair below 0: dead-centre aim)
      if (score < 1 && score < bestScore) { bestScore = score; best = id; }
    }
    return best;
  }

  function pointAtCharacters() {
    controllers.forEach((controller, i) => {
      if (state.panelHover[i]) return;                          // the panel (or the workbench) is in front
      const id = pickCharacter(controller);
      hover[i] = id;                                            // main.js / operator_view.js read this too
      if (id) controller.getObjectByName("ray")?.material.color.set(0x66ff99);
    });
  }

  function pointAtPanel() {
    controllers.forEach((controller, i) => {
      state.panelHover[i] = null;
      state.widgetHover[i] = null;
      if (window.vrBuilder?.isOpen() && window.vrBuilder.hovering(controller)) { hover[i] = null; state.panelHover[i] = "builder"; return; }
      tmpM.identity().extractRotation(controller.matrixWorld);
      raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld);
      raycaster.ray.direction.set(0, 0, -1).applyMatrix4(tmpM);
      const menuHit = panel.mesh.visible ? raycaster.intersectObject(panel.mesh, false)[0] : null;
      // the panel widgets beside characters (behind the menu if both are in line)
      let best = null;
      for (const [key, w] of state.widgets) {
        if (!w.mesh.visible) continue;
        const h = raycaster.intersectObject(w.mesh, false)[0];
        if (h && (!best || h.distance < best.h.distance)) best = { key, w, h };
      }
      if (best && (!menuHit || best.h.distance < menuHit.distance)) {
        const x = best.h.uv.x * best.w.canvas.width, y = (1 - best.h.uv.y) * best.w.canvas.height;
        const region = hitAt(best.w.hits, x, y);
        state.widgetHover[i] = { key: best.key, hit: region, frac: region?.timeline ? (x - region.x) / region.w : 0.5 };
        hover[i] = null;
        controller.getObjectByName("ray")?.material.color.set(region ? 0x58a6ff : 0x78aaff);
        return;
      }
      const hit = menuHit;
      if (!hit) return;
      state.panelHover[i] = panel.buttonAt(hit.uv) || "panel";   // "panel": on it, not on a button -- swallow the trigger
      hover[i] = null;                                          // the panel is in front: not pointing at a character
      controller.getObjectByName("ray")?.material.color.set(state.panelHover[i] === "panel" ? 0x78aaff : 0x58a6ff);
    });
    const onButton = state.panelHover.find((h) => h && h !== "panel" && h !== "builder") || null;
    panel.setHover(onButton);
  }

  function placeMenu() {
    const m = state.menu;
    if (!m) return;
    const target = charHead(m.charId);
    if (!target) return closeMenu();                            // they left the map (off-grid)
    const head = headWorld();
    const dir = target.clone().sub(head);
    const dist = dir.length();
    dir.normalize();
    const along = Math.min(MENU_DISTANCE_M * dolly.scale.x, dist * 0.6);
    const pos = head.clone().addScaledVector(dir, along);
    pos.y -= 0.1 * dolly.scale.x;
    panel.mesh.position.copy(pos);
    panel.mesh.lookAt(head);
    panel.mesh.scale.set(panel.baseW * dolly.scale.x, panel.baseH * dolly.scale.x, 1);   // same apparent size at any scale
    const pts = tether.geometry.attributes.position;
    pts.setXYZ(0, pos.x, pos.y - panel.mesh.scale.y / 2, pos.z);
    pts.setXYZ(1, target.x, target.y, target.z);
    pts.needsUpdate = true;
    tether.geometry.computeBoundingSphere();
  }

  // ---- panels beside characters --------------------------------------------------------------------------------------
  function widgetWorld(w, px, py) {                      // a canvas point on a widget -> world coordinates
    const p = w.mesh.localToWorld(new THREE.Vector3(px / w.canvas.width - 0.5, 0.5 - py / w.canvas.height, 0));
    return [p.x, p.y, p.z];
  }
  function makeWidget() {
    const canvas = document.createElement("canvas");
    canvas.width = WIDGET_PX; canvas.height = 200;
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthTest: false }));
    mesh.renderOrder = 997;
    mesh.userData.ignoreRaycast = true;
    scene.add(mesh);
    return { canvas, ctx: canvas.getContext("2d"), texture, mesh, view: {}, hits: [], height: 200, drawn: -1 };
  }
  function entityPanels(charId) {
    let e = state.entityPanels.get(charId);
    if (!e) { e = { data: null, at: -1e9, busy: false }; state.entityPanels.set(charId, e); }
    if (!e.busy && state.clock - e.at > LAYOUT_REFRESH_S) {
      e.busy = true;
      panelApi.panelsFor("character", charId).then((d) => { e.data = d; }).catch(() => {}).finally(() => { e.busy = false; e.at = state.clock; });
    }
    return e.data;
  }
  function updateWidgets() {
    const keep = new Set();
    const head = headWorld();
    for (const charId of state.shown) {
      const target = charHead(charId);
      const d = entityPanels(charId);
      if (!target || !d) continue;
      // what shows: enabled panels, and on-demand ones while their data has something in it
      const visible = d.templates.filter((t) => {
        const st = d.states[t.id];
        if (st === "enabled") return true;
        if (st === "on_demand") return hasContent(state.feed.get("character", charId, t).value);
        return false;
      });
      const toViewer = head.clone().sub(target).setY(0).normalize();
      const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), toViewer).normalize();
      const s = dolly.scale.x;
      const colY = [target.y + 0.35 * s, target.y + 0.35 * s];       // the top of each of two columns
      visible.forEach((t, idx) => {
        const key = `${charId}|${t.id}`;
        keep.add(key);
        let w = state.widgets.get(key);
        if (!w) { w = makeWidget(); state.widgets.set(key, w); }
        const e = state.feed.get("character", charId, t);
        if (state.clock - w.drawn > WIDGET_REDRAW_S) {
          const sub = e.error ? `couldn't read: ${e.error}` : `${(window.getWorldCharacter(charId) || {}).name || charId} · ${t.source?.path || "(all)"}`;
          const out = renderPanel(w.ctx, WIDGET_PX, t, e.value, w.view, sub);
          if (w.uploadedH && w.uploadedH !== out.height) w.texture.dispose();   // a new size needs new GPU storage
          w.uploadedH = out.height;
          w.hits = out.hits; w.height = out.height; w.texture.needsUpdate = true; w.drawn = state.clock;
        }
        const wm = WIDGET_W_M * s, hm = wm * w.height / WIDGET_PX;
        const col = idx % 2;
        const x = (0.55 + col * (WIDGET_W_M + 0.05)) * s;
        const pos = target.clone().addScaledVector(right, x + wm / 2);
        pos.y = colY[col] - hm / 2;
        colY[col] -= hm + 0.04 * s;
        w.mesh.position.copy(pos);
        w.mesh.lookAt(head);
        w.mesh.scale.set(wm, hm, 1);
        w.mesh.visible = true;
      });
    }
    for (const [key, w] of state.widgets) {
      if (keep.has(key)) continue;
      scene.remove(w.mesh); w.texture.dispose(); w.mesh.geometry.dispose(); w.mesh.material.dispose();
      state.widgets.delete(key);
    }
  }

  function followCharacter() {
    if (!state.follow) return;
    const head = charHead(state.follow.charId);
    if (!head) { state.follow = null; return; }
    dolly.position.lerp(head.clone().add(state.follow.offset), 0.15);
  }

  let last = performance.now();
  window.xrFrameHooks.push(() => {
    const now = performance.now();
    state.clock += (now - last) / 1000;
    last = now;
    navigate();
    followCharacter();
    updateWidgets();
    placeMenu();
    pointAtPanel();
    pointAtCharacters();
    if ((state.menu?.view === "inspect" || state.menu?.view === "draw") && state.clock - state.menu.refreshed > REFRESH_SECONDS) {
      state.menu.refreshed = state.clock;
      redraw();
    }
  });
}

(function waitForXR(attempts = 50) {
  const ctx = window.getXRContext?.();
  if (ctx && window.xrFrameHooks) return setup(ctx);
  if (attempts > 0) setTimeout(() => waitForXR(attempts - 1), 100);
})();
