// src/vrBuilder.js -- design debug panels in VR, by drag and drop (the desktop equivalent is panels.html).
//
// A workbench opens in front of you with four parts:
//   palette      the widget types (table, line, pie, bar, tree, text)
//   data         the character's own data, as a list you browse (tap a folder to open it, ▲ ▼ to page, ↑ to go back)
//   preview      the panel being made, live -- drop things here
//   properties   buttons for what the panel's type has (rows per page, order, timeline, text style, refresh, who it is
//                for, default state, name by voice), Clear, Save, Close
//
// Drag: point at a tile or a field, hold the trigger, move the ray to the preview, let go. A quick tap does the same as
// dropping it. What a drop does depends on what it is and what the panel is:
//   a widget type        makes the panel, or changes its type
//   a list               the panel's data (a table if there is no panel yet)
//   a field of a list's entries   a column (table), a series (line), the label (pie / bar), a value line (text)
//   a number / some text a value line (text panel; a new text panel if there is none), or a live series (line)
//   an object            a tree (or live series of its numbers, on a line graph)
// Save stores the template (for this character, all characters or everything), puts it in the character's active layout,
// enabled, and shows their panels.

import * as THREE from "three";
import * as panelApi from "./panels/api.js";
import { renderPanel, clickPanel, hitAt } from "./panels/render.js";

const PX_PER_M = 1500;
const TYPES = [["table", "Table"], ["line", "Line graph"], ["pie", "Pie chart"], ["bar", "Bar chart"], ["tree", "Tree"], ["text", "Text"]];
const TYPE_NAME = Object.fromEntries(TYPES);
const STATE_CYCLE = { enabled: "on_demand", on_demand: "disabled", disabled: "enabled" };
const STATE_NAME = { enabled: "Enabled", on_demand: "On demand", disabled: "Disabled" };
const FOR_CYCLE = { one: "characters", characters: "all", all: "one" };
const TEXT_STYLES = ["normal", "heading", "big heading", "bold", "red", "small"];
const BROWSE_PAGE = 9;
const TAP_SECONDS = 0.3;

// a canvas on a plane, with regions you can point at
class Surface {
  constructor(widthM, heightPx) {
    this.canvas = document.createElement("canvas");
    this.canvas.width = Math.round(widthM * PX_PER_M);
    this.canvas.height = heightPx || 600;
    this.ctx = this.canvas.getContext("2d");
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: this.texture, transparent: true, depthTest: false }));
    this.mesh.renderOrder = 1000;
    this.mesh.userData.ignoreRaycast = true;
    this.widthM = widthM;
    this.regions = [];
    this.fit();
  }
  fit() { this.mesh.scale.set(this.widthM, this.widthM * this.canvas.height / this.canvas.width, 1); }
  bg(title) {
    const c = this.ctx, W = this.canvas.width, H = this.canvas.height;
    c.clearRect(0, 0, W, H);
    c.fillStyle = "rgba(14,17,24,0.95)"; c.strokeStyle = "rgba(120,170,255,0.55)"; c.lineWidth = 3;
    c.beginPath(); c.roundRect(1.5, 1.5, W - 3, H - 3, 16); c.fill(); c.stroke();
    c.textBaseline = "top";
    if (title) { c.fillStyle = "#8b98ad"; c.font = "bold 24px system-ui, sans-serif"; c.fillText(title.toUpperCase(), 18, 14); }
    return title ? 52 : 14;
  }
  button(x, y, w, h, label, region, opts = {}) {
    const c = this.ctx;
    c.fillStyle = opts.on ? "#1f6feb" : opts.hover ? "rgba(88,166,255,0.35)" : opts.fill || "rgba(255,255,255,0.08)";
    c.beginPath(); c.roundRect(x, y, w, h, 12); c.fill();
    c.fillStyle = opts.color || "#fff"; c.font = `${opts.bold === false ? "" : "bold "}${opts.size || 24}px system-ui, sans-serif`;
    c.textBaseline = "middle";
    const t = String(label);
    c.fillText(t.length > opts.max ? t.slice(0, opts.max - 1) + "…" : t, x + 14, y + h / 2);
    c.textBaseline = "top";
    this.regions.push({ x, y, w, h, ...region });
  }
  regionAt(uv) {
    const x = uv.x * this.canvas.width, y = (1 - uv.y) * this.canvas.height;
    let best = null;
    for (const r of this.regions) if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) best = r;
    return best ? { ...best, px: x, py: y } : null;
  }
  worldOf(r) {
    const u = (r.x + r.w / 2) / this.canvas.width, v = (r.y + r.h / 2) / this.canvas.height;
    const p = this.mesh.localToWorld(new THREE.Vector3(u - 0.5, 0.5 - v, 0));
    return [p.x, p.y, p.z];
  }
  done() {
    // three.js allocates a texture's GPU storage once, at its first size: after the canvas changes size the old storage
    // would keep showing a stale (stretched) picture -- release it so the next upload allocates the new size
    const size = `${this.canvas.width}x${this.canvas.height}`;
    if (this._size && this._size !== size) this.texture.dispose();
    this._size = size;
    this.texture.needsUpdate = true;
  }
}

const slug = (s) => String(s || "panel").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "panel";
const label = (path) => String(path).split(".").filter((p) => p !== "-1").pop()?.replace(/_/g, " ") || "everything";

function setup(ctx) {
  const { renderer, scene, dolly, camera, controllers } = ctx;
  const raycaster = new THREE.Raycaster();
  const tmpM = new THREE.Matrix4();
  const group = new THREE.Group();
  group.visible = false;
  scene.add(group);

  const palette = new Surface(0.26, 700);
  const browser = new Surface(0.38, 860);
  const preview = new Surface(0.6, 400);
  const props = new Surface(0.6, 360);
  palette.mesh.position.set(-0.68, 0.02, 0);
  browser.mesh.position.set(-0.33, 0.0, 0);
  for (const s of [palette, browser, preview, props]) group.add(s.mesh);
  const surfaces = [palette, browser, preview, props];

  // the card that follows the ray while dragging
  const ghost = new Surface(0.2, 70);
  ghost.mesh.renderOrder = 1001;
  ghost.mesh.visible = false;
  scene.add(ghost.mesh);

  const st = {
    open: false, charId: null, draft: null, editing: null, view: {}, feed: new panelApi.PanelFeed(), hits: [],
    browse: { path: "", rows: [], page: 0, loading: false, inList: null },
    press: [null, null],          // per hand: {item, t, surface, region} while the trigger is held on something
    drag: null,                   // {item, hand}
    hover: [null, null],          // per hand: {surface, region}
    forScope: "one", message: "", saving: false, previewDrawn: -1, clock: 0,
  };

  // ---- opening / placing -------------------------------------------------------------------------------------------
  function place() {
    const head = camera.getWorldPosition(new THREE.Vector3());
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.getWorldQuaternion(new THREE.Quaternion())).setY(0).normalize();
    const s = dolly.scale.x;
    group.position.copy(head).addScaledVector(fwd, 1.0 * s);
    group.position.y = head.y - 0.22 * s;
    group.lookAt(head.x, group.position.y, head.z);
    group.scale.setScalar(s);
  }
  function open(charId, template) {
    st.open = true; st.charId = charId; st.view = {}; st.feed = new panelApi.PanelFeed(); st.message = "";
    st.editing = template ? template.id : null;
    st.draft = template ? JSON.parse(JSON.stringify(template)) : null;
    if (st.draft) st.draft._named = true;
    st.forScope = !template ? "one" : (template.assign?.scope === "all" ? "all" : template.assign?.scope === "kinds" ? "characters" : "one");
    st.browse = { path: "", rows: [], page: 0, loading: false, inList: null };
    group.visible = true;
    place();
    browseTo("");
    drawAll();
  }
  function close() { st.open = false; group.visible = false; ghost.mesh.visible = false; st.drag = null; }

  // ---- the data browser --------------------------------------------------------------------------------------------
  async function browseTo(path) {
    st.browse.loading = true; drawBrowser();
    try {
      const out = await panelApi.fieldsOf("character", st.charId, path, 1);
      // inside a list, its fields are the entries' fields (paths "<list>.-1.<key>")
      const listPath = path && (await isList(path)) ? path : null;
      st.browse = { path, page: 0, loading: false, inList: listPath,
        rows: Object.entries(out.fields).map(([k, f]) => ({ key: k, f, path: listPath ? `${listPath}.-1.${k}` : (path ? `${path}.${k}` : k) }))
          .sort((a, b) => (b.f.type === "list") - (a.f.type === "list") || (b.f.type === "object") - (a.f.type === "object") || a.key.localeCompare(b.key)) };
    } catch (err) {
      st.browse = { ...st.browse, loading: false, rows: [], error: err.message };
    }
    drawBrowser();
  }
  const listCache = new Map();
  async function isList(path) {
    if (listCache.has(path)) return listCache.get(path);
    const parent = path.split(".").slice(0, -1).join(".");
    const key = path.split(".").pop();
    try {
      const out = await panelApi.fieldsOf("character", st.charId, parent, 1);
      const yes = out.fields?.[key]?.type === "list";
      listCache.set(path, yes);
      return yes;
    } catch { return false; }
  }

  // ---- drawing -----------------------------------------------------------------------------------------------------
  function hov(surface, id) { return st.hover.some((h) => h && h.surface === surface && h.region?.id === id); }

  function drawPalette() {
    palette.regions = [];
    let y = palette.bg("Widgets");
    for (const [t, name] of TYPES) {
      palette.button(14, y, palette.canvas.width - 28, 92, name, { id: `type:${t}`, drag: { kind: "type", type: t, label: name } },
                     { hover: hov(palette, `type:${t}`), on: st.draft?.type === t, size: 30 });
      y += 104;
    }
    palette.done();
  }

  function drawBrowser() {
    const b = st.browse, W = browser.canvas.width;
    browser.regions = [];
    let y = browser.bg("Data");
    const c = browser.ctx;
    c.fillStyle = "#c9d1d9"; c.font = "22px system-ui"; c.fillText(b.path ? `${(window.getWorldCharacter(st.charId) || {}).name || st.charId} › ${b.path}` : ((window.getWorldCharacter(st.charId) || {}).name || st.charId), 18, y); y += 36;
    if (b.path) { browser.button(14, y, W - 28, 60, "↑  back", { id: "up" }, { hover: hov(browser, "up"), size: 24 }); y += 68; }
    if (b.loading) { c.fillStyle = "#8b98ad"; c.fillText("loading…", 18, y); browser.done(); return; }
    if (b.error) { c.fillStyle = "#f85149"; c.fillText(b.error.slice(0, 40), 18, y); }
    const rows = b.rows.slice(b.page * BROWSE_PAGE, (b.page + 1) * BROWSE_PAGE);
    for (const r of rows) {
      const folder = r.f.type === "list" || r.f.type === "object";
      const info = r.f.type === "list" ? `list · ${r.f.size}` : r.f.type === "object" ? `{${r.f.size}}` : (r.f.sample !== undefined ? String(r.f.sample) : r.f.type);
      browser.button(14, y, W - 28, 62, `${folder ? "▸ " : ""}${r.key}`, { id: `field:${r.path}`, drag: { kind: "field", path: r.path, type: r.f.type, inList: b.inList, key: r.key, label: r.key }, folder },
                     { hover: hov(browser, `field:${r.path}`), size: 24, max: 22 });
      c.fillStyle = "#8b98ad"; c.font = "19px system-ui"; c.textAlign = "right";
      c.fillText(String(info).slice(0, 18), W - 26, y + 22); c.textAlign = "left";
      y += 70;
    }
    const pages = Math.max(1, Math.ceil(b.rows.length / BROWSE_PAGE));
    const by = browser.canvas.height - 74;
    browser.button(14, by, 90, 60, "▲", { id: "pg_up" }, { hover: hov(browser, "pg_up") });
    browser.button(W - 104, by, 90, 60, "▼", { id: "pg_down" }, { hover: hov(browser, "pg_down") });
    c.fillStyle = "#8b98ad"; c.font = "20px system-ui"; c.textAlign = "center"; c.fillText(`${b.page + 1} / ${pages}`, W / 2, by + 20); c.textAlign = "left";
    browser.done();
  }

  function drawPreview() {
    if (!st.draft) {
      preview.regions = [];
      const y = preview.bg("Preview");
      const c = preview.ctx;
      c.fillStyle = "#8b98ad"; c.font = "26px system-ui";
      c.fillText("Drag a widget or a piece of data here", 22, y + 20);
      c.font = "22px system-ui"; c.fillText("(or tap one)", 22, y + 60);
      preview.regions.push({ x: 0, y: 0, w: preview.canvas.width, h: preview.canvas.height, id: "drop" });
      preview.done(); preview.fit();
      return;
    }
    const e = st.feed.get("character", st.charId, st.draft);
    const sub = e.error ? `couldn't read: ${e.error}` : `${st.draft.source?.path || "(everything)"} · ${st.message || "drop more data here"}`;
    const out = renderPanel(preview.ctx, preview.canvas.width, st.draft, e.value, st.view, sub);
    st.hits = out.hits;
    preview.regions = [{ x: 0, y: 0, w: preview.canvas.width, h: preview.canvas.height, id: "drop" }];
    preview.done(); preview.fit();
  }

  function propButtons() {
    const d = st.draft, o = d?.options || {};
    const who = { one: `For: ${(window.getWorldCharacter(st.charId) || {}).name || "this one"} only`, characters: "For: all characters", all: "For: everything" }[st.forScope];
    const out = [];
    if (d) {
      out.push(["type_next", `Type: ${TYPE_NAME[d.type]} ▸`]);
      if (d.type === "table") {
        out.push(["rows_minus", `Rows ${o.page_size || 8}  −`], ["rows_plus", "Rows  +"],
                 ["order", `Order: ${o.order || "newest"} ▸`], ["timeline", `Timeline: ${o.timeline === false ? "off" : "on"} ▸`]);
        if ((o.columns || []).length) out.push(["col_pop", "Remove last column"]);
      }
      if (d.type === "line" && (o.series || []).length) out.push(["series_pop", "Remove last series"]);
      if ((d.type === "pie" || d.type === "bar") && o.label_key) out.push(["label_clear", "Count rows (no label)"]);
      if (d.type === "text" && (o._lines || []).length) {
        const last = o._lines[o._lines.length - 1];
        out.push(["line_style", `Last line: ${last.style} ▸`], ["line_pop", "Remove last line"]);
      }
      out.push(["refresh_minus", `Refresh ${d.source?.refresh_s ?? 2}s  −`], ["refresh_plus", "Refresh  +"],
               ["state", `Shows: ${STATE_NAME[d.default_state || "enabled"]} ▸`], ["for", `${who} ▸`]);
      if (window.SpeechRecognition || window.webkitSpeechRecognition) out.push(["voice", `Name: ${d.name || "…"} 🎤`]);
      out.push(["clear", "Clear"], ["save", st.saving ? "Saving…" : (st.editing ? "Save changes" : "Save panel")]);
    }
    out.push(["recenter", "Bring closer"], ["close", "Close"]);
    return out;
  }

  function drawProps() {
    const btns = propButtons();
    const cols = 3, bh = 62, gap = 10, W = props.canvas.width;
    const rowsN = Math.ceil(btns.length / cols);
    const H = 52 + rowsN * (bh + gap) + 50;
    if (props.canvas.height !== H) { props.canvas.height = H; props.fit(); }
    props.regions = [];
    let y = props.bg(st.draft ? `${st.editing ? "Edit" : "New"} panel: ${st.draft.name || TYPE_NAME[st.draft.type]}` : "Properties");
    const bw = (W - 28 - gap * (cols - 1)) / cols;
    btns.forEach(([id, lab], i) => {
      const x = 14 + (i % cols) * (bw + gap), yy = y + Math.floor(i / cols) * (bh + gap);
      props.button(x, yy, bw, bh, lab, { id }, { hover: hov(props, id), size: 21, max: 26, on: id === "save", fill: id === "close" ? "rgba(248,81,73,0.25)" : undefined });
    });
    const c = props.ctx;
    c.fillStyle = "#8b98ad"; c.font = "20px system-ui";
    c.fillText(st.message || "Hold the trigger on a widget or a field, let go over the preview.", 18, props.canvas.height - 40);
    props.done();
  }

  function layout() {        // preview on the right, the properties under it
    const pw = preview.mesh.scale.y, ph = props.mesh.scale.y;
    preview.mesh.position.set(0.32, 0.25 - pw / 2, 0);
    props.mesh.position.set(0.32, 0.25 - pw - 0.02 - ph / 2, 0);
    palette.mesh.position.set(-0.68, 0.25 - palette.mesh.scale.y / 2, 0);
    browser.mesh.position.set(-0.33, 0.25 - browser.mesh.scale.y / 2, 0);
  }
  function drawAll() { drawPalette(); drawBrowser(); drawPreview(); drawProps(); layout(); }

  // ---- what a drop does ----------------------------------------------------------------------------------------------
  function newDraft(type) {
    const defaults = { table: { page_size: 8, order: "newest", timeline: true, columns: [] }, line: { series: [] }, pie: {}, bar: {},
                       tree: { max_rows: 40 }, text: { _lines: [], font_size: 28, html: "" } }[type];
    return { id: "", name: "", type, source: { path: "", refresh_s: 2 }, options: defaults, default_state: "enabled", assign: { scope: "entities" } };
  }
  function autoName(d) {
    if (d._named) return;
    const o = d.options || {};
    const bits = [label(d.source?.path || "")];
    if (d.type === "table" && o.columns?.length) bits.push(o.columns.join(", "));
    if (d.type === "line" && o.series?.length) bits.push(o.series.join(", "));
    if ((d.type === "pie" || d.type === "bar") && o.label_key) bits.push(`by ${o.label_key}`);
    if (d.type === "text") bits.splice(0, 1, ...(o._lines || []).map((l) => l.label).slice(0, 3));
    const n = bits.filter((x) => x && x !== "everything").join(": ");
    d.name = n ? n[0].toUpperCase() + n.slice(1) : TYPE_NAME[d.type];
  }
  function textHtml(lines) {
    const tag = { heading: "h2", "big heading": "h1" };
    return lines.map((l) => {
      const v = `{{${l.path}}}`;
      if (tag[l.style]) return `<${tag[l.style]}>${l.label}: ${v}</${tag[l.style]}>`;
      if (l.style === "bold") return `<p><b>${l.label}: ${v}</b></p>`;
      if (l.style === "red") return `<p>${l.label}: <b style="color:#f85149">${v}</b></p>`;
      if (l.style === "small") return `<p><span style="font-size:12px">${l.label}: ${v}</span></p>`;
      return `<p>${l.label}: <b>${v}</b></p>`;
    }).join("");
  }
  function addTextLine(d, path, lab) {
    d.options._lines ||= [];
    d.options._lines.push({ path, label: lab, style: "normal" });
    d.options.html = (d.options._html_base || "") + textHtml(d.options._lines);
  }

  function drop(item) {
    let d = st.draft;
    st.message = "";
    if (item.kind === "type") {
      if (!d) d = st.draft = newDraft(item.type);
      else if (d.type !== item.type) {
        const keepSource = d.source;
        const keepName = d._named ? d.name : "";
        d = st.draft = Object.assign(newDraft(item.type), { source: keepSource, name: keepName, _named: !!keepName, id: d.id });
      }
      st.message = `${TYPE_NAME[item.type]} -- now drop data on it`;
    } else if (item.kind === "field") {
      const isNum = item.type === "int" || item.type === "float";
      const parent = item.path.split(".").slice(0, -1).join(".");
      if (item.inList) {                                  // a field of a list's entries
        if (!d) { d = st.draft = newDraft("table"); }
        if (d.type === "text") { addTextLine(d, `${item.inList}.-1.${item.key}`, `latest ${item.key}`); }
        else {
          if (d.source.path !== item.inList) { d.source.path = item.inList; d.options.columns = []; d.options.series = []; }
          if (d.type === "table") d.options.columns = [...new Set([...(d.options.columns || []), item.key])];
          else if (d.type === "line") { if (isNum) d.options.series = [...new Set([...(d.options.series || []), item.key])]; else d.options.x_key = item.key; }
          else if (d.type === "pie" || d.type === "bar") { if (isNum && d.options.label_key) d.options.value_key = item.key; else d.options.label_key = item.key; }
          else if (d.type === "tree") d.source.path = item.path;
        }
      } else if (item.type === "list") {
        if (!d) d = st.draft = newDraft("table");
        if (d.type === "text") addTextLine(d, `${item.path}.-1`, `latest ${item.key}`);
        else { d.source.path = item.path; d.options.columns = []; d.options.series = []; delete d.options.label_key; delete d.options.value_key; }
      } else if (item.type === "object") {
        if (!d) d = st.draft = newDraft("tree");
        if (d.type === "text") addTextLine(d, item.path, item.key);
        else { d.source.path = item.path; d.options.series = []; }
      } else {                                            // a single value
        if (!d) d = st.draft = newDraft(isNum ? "text" : "text");
        if (d.type === "line" && isNum) {
          if (d.source.path !== parent) { d.source.path = parent; d.options.series = []; }
          d.options.series = [...new Set([...(d.options.series || []), item.key])];
        } else if (d.type === "text" || !isNum) {
          if (d.type !== "text") { st.message = "text values go on a Text panel -- drop the Text widget first"; return refresh(); }
          addTextLine(d, item.path, item.key.replace(/_/g, " "));
        } else st.message = "drop a number on a Text or Line panel";
      }
    }
    if (d) autoName(d);
    st.view = {}; st.feed = new panelApi.PanelFeed();
    refresh();
  }

  function act(id) {
    const d = st.draft;
    const o = d?.options;
    switch (id) {
      case "close": return close();
      case "recenter": place(); return;
      case "clear": st.draft = null; st.editing = null; st.message = ""; break;
      case "type_next": { const ts = TYPES.map((t) => t[0]); drop({ kind: "type", type: ts[(ts.indexOf(d.type) + 1) % ts.length] }); return; }
      case "rows_minus": o.page_size = Math.max(3, (o.page_size || 8) - 1); break;
      case "rows_plus": o.page_size = Math.min(40, (o.page_size || 8) + 1); break;
      case "order": o.order = { newest: "oldest", oldest: "as_is", as_is: "newest" }[o.order || "newest"]; break;
      case "timeline": o.timeline = o.timeline === false; break;
      case "col_pop": o.columns = (o.columns || []).slice(0, -1); autoName(d); break;
      case "series_pop": o.series = (o.series || []).slice(0, -1); autoName(d); break;
      case "label_clear": delete o.label_key; delete o.value_key; autoName(d); break;
      case "line_style": { const l = o._lines[o._lines.length - 1]; l.style = TEXT_STYLES[(TEXT_STYLES.indexOf(l.style) + 1) % TEXT_STYLES.length]; o.html = (o._html_base || "") + textHtml(o._lines); break; }
      case "line_pop": o._lines.pop(); o.html = (o._html_base || "") + textHtml(o._lines); autoName(d); break;
      case "refresh_minus": d.source.refresh_s = Math.max(0.5, (d.source.refresh_s ?? 2) - 0.5); st.feed = new panelApi.PanelFeed(); break;
      case "refresh_plus": d.source.refresh_s = Math.min(60, (d.source.refresh_s ?? 2) + (d.source.refresh_s >= 5 ? 5 : 0.5)); st.feed = new panelApi.PanelFeed(); break;
      case "state": d.default_state = STATE_CYCLE[d.default_state || "enabled"]; break;
      case "for": st.forScope = FOR_CYCLE[st.forScope]; break;
      case "voice": return nameByVoice();
      case "save": return save();
      default:
        if (id === "up") { const parts = st.browse.path.split("."); parts.pop(); return browseTo(parts.join(".")); }
        if (id === "pg_up") { st.browse.page = Math.max(0, st.browse.page - 1); return drawBrowser(); }
        if (id === "pg_down") { st.browse.page = Math.min(Math.ceil(st.browse.rows.length / BROWSE_PAGE) - 1, st.browse.page + 1); return drawBrowser(); }
    }
    st.view = { ...st.view, page: 0 };
    refresh();
  }

  function nameByVoice() {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor || !st.draft) return;
    const r = new Ctor();
    r.lang = "en-US"; r.interimResults = false;
    st.message = "Say the panel's name…"; drawProps();
    r.onresult = (e) => { const t = e.results[0][0].transcript.trim(); if (t) { st.draft.name = t[0].toUpperCase() + t.slice(1); st.draft._named = true; } };
    r.onend = () => { st.message = ""; refresh(); };
    r.onerror = () => { st.message = "Didn't catch that"; drawProps(); };
    r.start();
  }

  async function save() {
    const d = st.draft;
    if (!d || st.saving) return;
    st.saving = true; drawProps();
    const t = JSON.parse(JSON.stringify(d));
    delete t._named;
    t.id = st.editing || `${slug(t.name)}_${Math.random().toString(36).slice(2, 6)}`;
    const key = `character:${st.charId}`;
    t.assign = st.forScope === "all" ? { scope: "all" } : st.forScope === "characters" ? { scope: "kinds", kinds: ["character"] }
      : { scope: "entities", entities: [...new Set([...((st.editing && d.assign?.entities) || []), key])] };
    try {
      await panelApi.saveTemplate(t);
      // in the character's active layout, in its default state
      const data = await panelApi.panelsFor("character", st.charId);
      const dr = { active: data.active, layouts: JSON.parse(JSON.stringify(data.layouts)) };
      (dr.layouts[dr.active] ||= { panels: {} }).panels[t.id] = t.default_state || "enabled";
      for (const tt of data.templates) for (const l of Object.values(dr.layouts)) l.panels[tt.id] ||= data.states[tt.id] || tt.default_state || "enabled";
      await panelApi.saveLayouts("character", st.charId, dr);
      st.editing = t.id; st.draft.id = t.id;
      st.message = `Saved “${t.name}” -- it's in the ${dr.active} layout`;
      window.vrDebugShowPanels?.(st.charId);
    } catch (err) {
      st.message = `Couldn't save: ${err.message}`;
    }
    st.saving = false;
    refresh();
  }

  function refresh() { drawPreview(); drawProps(); drawPalette(); layout(); st.previewDrawn = st.clock; }

  // ---- pointing, trigger, dragging ---------------------------------------------------------------------------------
  function rayOf(controller) {
    tmpM.identity().extractRotation(controller.matrixWorld);
    raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld);
    raycaster.ray.direction.set(0, 0, -1).applyMatrix4(tmpM);
    return raycaster;
  }
  function pointedAt(controller) {
    if (!st.open) return null;
    const rc = rayOf(controller);
    let best = null;
    for (const s of surfaces) {
      const h = rc.intersectObject(s.mesh, false)[0];
      if (h && (!best || h.distance < best.h.distance)) best = { s, h };
    }
    if (!best) return null;
    return { surface: best.s, region: best.s.regionAt(best.h.uv), distance: best.h.distance, uv: best.h.uv };
  }

  controllers.forEach((controller, i) => {
    controller.addEventListener("selectstart", () => {
      if (!st.open || !renderer.xr.isPresenting) return;
      const at = pointedAt(controller);
      if (!at) return;
      const r = at.region;
      if (r?.drag) { st.press[i] = { item: r.drag, t: st.clock, surface: at.surface, region: r, folder: r.folder, distance: at.distance }; return; }
      if (at.surface === preview && st.draft) {               // clicks inside the panel (pages, points) work as on a shown panel
        const x = at.uv.x * preview.canvas.width, y = (1 - at.uv.y) * preview.canvas.height;
        if (clickPanel(st.view, hitAt(st.hits, x, y)?.action)) drawPreview();
        return;
      }
      if (r?.id) act(r.id);
    });
    controller.addEventListener("selectend", () => {
      const p = st.press[i];
      st.press[i] = null;
      if (!st.open || !p) return;
      const wasDrag = st.drag && st.drag.hand === i;
      ghost.mesh.visible = false;
      st.drag = null;
      if (!wasDrag) {                                       // a tap: open a folder, or the same as dropping it
        if (p.folder && p.item.kind === "field") {
          return browseTo(p.item.type === "list" ? p.item.path.replace(/\.-1$/, "") : p.item.path);
        }
        return drop(p.item);
      }
      const at = pointedAt(controller);
      if (at?.surface === preview) drop(p.item);
      else { st.message = "Dropped outside the preview -- nothing changed"; drawProps(); }
    });
  });

  function updateDrag() {
    controllers.forEach((controller, i) => {
      const p = st.press[i];
      if (!p) return;
      const at = pointedAt(controller);
      const left = !at || at.region?.id !== p.region.id;
      if (!st.drag && (left || st.clock - p.t > TAP_SECONDS)) {
        st.drag = { item: p.item, hand: i };
        ghost.regions = [];
        ghost.bg();
        ghost.ctx.fillStyle = "#fff"; ghost.ctx.font = "bold 30px system-ui"; ghost.ctx.textBaseline = "middle";
        ghost.ctx.fillText(`${p.item.kind === "type" ? "◼ " : "● "}${p.item.label}`, 16, ghost.canvas.height / 2);
        ghost.done();
        ghost.mesh.visible = true;
      }
      if (st.drag?.hand === i) {
        const rc = rayOf(controller);
        const dist = at ? Math.max(0.1, at.distance - 0.03 * dolly.scale.x) : (p.distance || 0.8 * dolly.scale.x);
        ghost.mesh.position.copy(rc.ray.origin).addScaledVector(rc.ray.direction, dist);
        ghost.mesh.quaternion.copy(group.getWorldQuaternion(new THREE.Quaternion()));
        ghost.mesh.scale.set(ghost.widthM * dolly.scale.x, ghost.widthM * dolly.scale.x * ghost.canvas.height / ghost.canvas.width, 1);
      }
    });
  }

  function updateHover() {
    let changed = false;
    controllers.forEach((controller, i) => {
      const at = pointedAt(controller);
      const prev = st.hover[i];
      st.hover[i] = at && { surface: at.surface, region: at.region };
      if ((prev?.region?.id || null) !== (at?.region?.id || null) || prev?.surface !== at?.surface) changed = true;
      if (at) controller.getObjectByName("ray")?.material.color.set(st.drag?.hand === i ? 0xd29922 : at.region ? 0x58a6ff : 0x78aaff);
    });
    if (changed) { drawPalette(); drawBrowser(); drawProps(); }
  }

  let last = performance.now();
  window.xrFrameHooks.push(() => {
    const now = performance.now();
    st.clock += (now - last) / 1000; last = now;
    if (!st.open) return;
    updateHover();
    updateDrag();
    if (st.clock - st.previewDrawn > 0.5) { drawPreview(); layout(); st.previewDrawn = st.clock; }
  });

  // ---- what vrDebug.js and tests use -----------------------------------------------------------------------------
  window.vrBuilder = {
    open, close,
    isOpen: () => st.open,
    hovering: (controller) => !!pointedAt(controller),        // vrDebug: the workbench is in front, leave this ray alone
  };
  window.getVRBuilderState = () => ({
    open: st.open, charId: st.charId, editing: st.editing, message: st.message,
    draft: st.draft && JSON.parse(JSON.stringify(st.draft)), browsePath: st.browse.path, inList: st.browse.inList,
    dragging: st.drag?.item?.label || null,
    regions: Object.fromEntries([["palette", palette], ["browser", browser], ["preview", preview], ["props", props]]
      .map(([n, s]) => [n, s.regions.filter((r) => r.id).map((r) => ({ id: r.id, world: s.worldOf(r) }))])),
  });
}

(function waitForXR(attempts = 50) {
  const ctx = window.getXRContext?.();
  if (ctx && window.xrFrameHooks) return setup(ctx);
  if (attempts > 0) setTimeout(() => waitForXR(attempts - 1), 100);
})();
