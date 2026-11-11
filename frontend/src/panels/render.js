// src/panels/render.js -- draws a debug panel (a widget) onto a 2D canvas, for the panel designer's preview and the VR
// debugging interface alike (backend: systems/debug_panels.py).
//
//   renderPanel(ctx, width, template, value, view) -> {height, hits}
//
//   value   the data at the template's source path (any shape: a list of records, an object, a number, ...)
//   view    per-panel state kept by the caller between frames: page, timeline window, selection, tree folds, the history
//           of a live number -- created on first use; pass the same object every time
//   hits    clickable regions [{x, y, w, h, action}] in canvas pixels; hand a click to clickPanel(view, action)
//
// Types (template.type) and their options (template.options):
//   table   columns: [keys] (auto if empty), time_key (auto: tick/time/when/timestamp/ts/at/created_at/date),
//           order: "newest" | "oldest" | "as_is", sort_key, page_size (default 8), timeline: true|false
//           -> with timestamps: a timeline strip on top -- pan / zoom it (panTimeline / zoomTimeline), click a point to
//              jump to its row; the table shows the rows inside the timeline's window, a page at a time
//   line    x_key (auto: the time key), series: [keys] (auto: the numeric ones); a single number (or an object of numbers)
//           becomes a live series of its own, one point per refresh
//   pie     label_key, value_key (sums) -- or counts per label; an object {label: number} is used as it is
//   bar     the same data as pie, as bars
//   tree    the data as a tree; click a branch to open / fold it
//   text    html: rich text with {{path}} placeholders (paths into the source data, "" for the whole of it);
//           font_family, font_size, color

const C = {
  bg: "rgba(14,17,24,0.94)", border: "rgba(120,170,255,0.55)", text: "#c9d1d9", dim: "#8b98ad", title: "#e8eef8",
  accent: "#58a6ff", grid: "rgba(255,255,255,0.08)", sel: "#1f6feb",
  series: ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff", "#39c5cf", "#ff7b72", "#a5d6ff"],
};
const TIME_KEYS = ["tick", "time", "when", "timestamp", "ts", "at", "created_at", "date", "started", "ended"];
const PAD = 22;

// ---- data helpers --------------------------------------------------------------------------------------------------

export function hasContent(value) {
  if (value == null || value === "" || value === false) return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

export function pathGet(obj, dotted) {
  let cur = obj;
  for (const part of String(dotted || "").split(".").filter((p) => p !== "")) {
    if (cur == null) return undefined;
    if (Array.isArray(cur) && /^-?\d+$/.test(part)) { const i = Number(part); cur = cur[i < 0 ? cur.length + i : i]; }
    else cur = cur[part];
  }
  return cur;
}

function fmt(v, max = 60) {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "boolean") return v ? "yes" : "no";
  let s = Array.isArray(v) ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ")
    : typeof v === "object" ? JSON.stringify(v) : String(v);
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function fitText(ctx, text, maxW) {                    // cut to what fits in maxW pixels, with an ellipsis
  let t = String(text);
  if (ctx.measureText(t).width <= maxW) return t;
  while (t.length > 1 && ctx.measureText(t + "…").width > maxW) t = t.slice(0, Math.max(1, Math.floor(t.length * 0.85)));
  while (t.length < String(text).length && ctx.measureText(String(text).slice(0, t.length + 1) + "…").width <= maxW) t = String(text).slice(0, t.length + 1);
  return t + "…";
}

function toTime(v) {
  if (typeof v === "number" && isFinite(v)) return v;
  if (typeof v === "string") {
    if (/^\d+(\.\d+)?$/.test(v)) return Number(v);
    const t = Date.parse(v);
    if (!isNaN(t)) return t / 1000;
  }
  return null;
}

function rowsOf(value) {
  if (Array.isArray(value)) return value.map((r) => (r && typeof r === "object" && !Array.isArray(r) ? r : { value: r }));
  if (value && typeof value === "object") return Object.entries(value).map(([key, v]) => ({ key, value: v }));
  return value == null ? [] : [{ value }];
}

function detectTimeKey(rows, given) {
  if (given) return given;
  const sample = rows.slice(-20);
  return TIME_KEYS.find((k) => sample.length && sample.every((r) => r[k] == null || toTime(r[k]) != null) && sample.some((r) => toTime(r[k]) != null)) || null;
}

function columnsOf(rows, given, timeKey) {
  if (given && given.length) return given;
  const seen = [];
  for (const r of rows.slice(-20)) for (const k of Object.keys(r)) if (!seen.includes(k) && !k.startsWith("_")) seen.push(k);
  const ordered = timeKey ? [timeKey, ...seen.filter((k) => k !== timeKey)] : seen;
  return ordered.slice(0, 6);
}

// ---- view interaction (shared by mouse, VR trigger and stick) --------------------------------------------------------

export function panTimeline(view, fraction) {          // fraction of the visible window; + moves later
  const tl = view.timeline;
  if (!tl || tl.t0 == null) return;
  const span = tl.t1 - tl.t0;
  let t0 = tl.t0 + span * fraction, t1 = tl.t1 + span * fraction;
  if (t0 < tl.min) { t1 += tl.min - t0; t0 = tl.min; }
  if (t1 > tl.max) { t0 -= t1 - tl.max; t1 = tl.max; }
  tl.t0 = Math.max(tl.min, t0); tl.t1 = Math.min(tl.max, t1); tl.user = true; view.page = 0;
}

export function zoomTimeline(view, factor, center = 0.5) {   // factor < 1 zooms in
  const tl = view.timeline;
  if (!tl || tl.t0 == null) return;
  const span = tl.t1 - tl.t0, full = Math.max(1e-9, tl.max - tl.min);
  const newSpan = Math.min(full, Math.max(full / 500, span * factor));
  const c = tl.t0 + span * center;
  tl.t0 = c - newSpan * center; tl.t1 = tl.t0 + newSpan;
  panTimeline(view, 0);
  tl.user = newSpan < full;
}

export function clickPanel(view, action) {
  if (!action) return false;
  if (action.type === "page") { view.page = Math.max(0, Math.min(action.max, (view.page || 0) + action.delta)); return true; }
  if (action.type === "page_size") { view.page_size = action.size; view.page = 0; return true; }
  if (action.type === "select") {
    view.selected = view.selected === action.key ? null : action.key;
    if (action.page != null) view.page = action.page;
    return true;
  }
  if (action.type === "fold") { view.open ||= {}; view.open[action.path] = !view.open[action.path]; return true; }
  if (action.type === "timeline_reset" && view.timeline) { view.timeline.user = false; view.timeline.t0 = view.timeline.min; view.timeline.t1 = view.timeline.max; view.page = 0; return true; }
  if (action.type === "zoom") { zoomTimeline(view, action.factor, 0.5); return true; }
  if (action.type === "pan") { panTimeline(view, action.fraction); return true; }
  return false;
}

// ---- drawing -------------------------------------------------------------------------------------------------------

function frame(ctx, W, H, title, subtitle) {
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = C.bg; ctx.strokeStyle = C.border; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.roundRect(1.5, 1.5, W - 3, H - 3, 18); ctx.fill(); ctx.stroke();
  ctx.textBaseline = "top";
  ctx.fillStyle = C.title; ctx.font = "bold 30px system-ui, sans-serif";
  ctx.fillText(title || "", PAD, PAD);
  if (subtitle) { ctx.fillStyle = C.dim; ctx.font = "20px system-ui, sans-serif"; ctx.fillText(subtitle, PAD, PAD + 38); }
  return PAD + (subtitle ? 70 : 46);
}

function button(ctx, hits, x, y, w, h, label, action, active) {
  ctx.fillStyle = active ? C.sel : "rgba(255,255,255,0.09)";
  ctx.beginPath(); ctx.roundRect(x, y, w, h, 10); ctx.fill();
  ctx.fillStyle = "#fff"; ctx.font = "bold 22px system-ui, sans-serif"; ctx.textBaseline = "middle"; ctx.textAlign = "center";
  ctx.fillText(label, x + w / 2, y + h / 2);
  ctx.textAlign = "left"; ctx.textBaseline = "top";
  hits.push({ x, y, w, h, action });
}

function timeLabel(t, unitHint) {
  if (t == null) return "";
  if (unitHint === "epoch" || t > 1e9) { const d = new Date(t * 1000); return d.toISOString().slice(5, 16).replace("T", " "); }
  return String(Math.round(t));
}

// The timeline strip: every record a dot on its time; drag/zoom handled by the caller via panTimeline/zoomTimeline.
function drawTimeline(ctx, hits, x, y, w, items, view, keyOf, pageOf) {
  const H = 64;
  const ts = items.map((it) => it.t).filter((t) => t != null);
  if (!ts.length) return 0;
  const min = Math.min(...ts), max = Math.max(...ts) === min ? min + 1 : Math.max(...ts);
  const tl = view.timeline ||= { min, max, t0: min, t1: max, user: false };
  tl.min = min; tl.max = max;
  if (!tl.user) { tl.t0 = min; tl.t1 = max; }
  const span = Math.max(1e-9, tl.t1 - tl.t0);
  ctx.fillStyle = "rgba(255,255,255,0.05)"; ctx.fillRect(x, y, w, H);
  ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) { const gx = x + (w * i) / 4; ctx.beginPath(); ctx.moveTo(gx, y); ctx.lineTo(gx, y + H); ctx.stroke(); }
  for (const it of items) {
    if (it.t == null || it.t < tl.t0 || it.t > tl.t1) continue;
    const px = x + ((it.t - tl.t0) / span) * w;
    const k = keyOf(it);
    const sel = view.selected === k;
    ctx.fillStyle = sel ? "#fff" : C.accent;
    ctx.beginPath(); ctx.arc(px, y + H / 2, sel ? 9 : 6, 0, Math.PI * 2); ctx.fill();
    hits.push({ x: px - 12, y: y + 4, w: 24, h: H - 8, action: { type: "select", key: k, page: pageOf ? pageOf(it) : null }, point: true });
  }
  ctx.fillStyle = C.dim; ctx.font = "18px system-ui, sans-serif";
  ctx.fillText(timeLabel(tl.t0), x + 4, y + H + 4);
  const right = timeLabel(tl.t1); ctx.fillText(right, x + w - ctx.measureText(right).width - 4, y + H + 4);
  if (tl.user) {
    const lbl = "show all"; const lw = ctx.measureText(lbl).width + 20;
    button(ctx, hits, x + w / 2 - lw / 2, y + H + 2, lw, 26, lbl, { type: "timeline_reset" });
  }
  hits.push({ x, y, w, h: H, action: { type: "timeline_area" }, timeline: true });   // for pan/zoom by stick or wheel
  return H + 34;
}

function renderTable(ctx, W, t, value, view, hits) {
  const o = t.options || {};
  let rows = rowsOf(value).map((r, i) => ({ r, i }));
  const timeKey = detectTimeKey(rows.map((x) => x.r), o.time_key);
  for (const x of rows) x.t = timeKey ? toTime(x.r[timeKey]) : null;
  const order = o.order || (timeKey ? "newest" : "as_is");
  if (o.sort_key) rows.sort((a, b) => (a.r[o.sort_key] > b.r[o.sort_key] ? 1 : -1));
  if (order === "newest") rows.reverse();
  const cols = columnsOf(rows.map((x) => x.r), o.columns, timeKey);
  const pageSize = view.page_size || o.page_size || 8;
  const inWindow = (x) => !view.timeline?.user || x.t == null || (x.t >= view.timeline.t0 && x.t <= view.timeline.t1);
  // the timeline on top (records with a time), then the rows in its window, a page at a time
  let y = 0;
  const pageOfKey = (x) => Math.floor(rows.filter(inWindow).indexOf(x) / pageSize);
  if (timeKey && o.timeline !== false) y = drawTimeline(ctx, hits, PAD, view._top, W - 2 * PAD, rows, view, (x) => x.i, pageOfKey);
  const shown = rows.filter(inWindow);
  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  view.page = Math.min(view.page || 0, pages - 1);
  const pageRows = shown.slice(view.page * pageSize, (view.page + 1) * pageSize);
  let ty = view._top + y;
  const colW = (W - 2 * PAD) / Math.max(1, cols.length);
  ctx.fillStyle = C.dim; ctx.font = "bold 20px system-ui, sans-serif";
  cols.forEach((c, i) => ctx.fillText(fitText(ctx, String(c).replace(/_/g, " "), colW - 12), PAD + i * colW, ty));
  ty += 30;
  ctx.font = "21px system-ui, sans-serif";
  for (const x of pageRows) {
    const sel = view.selected === x.i;
    if (sel) { ctx.fillStyle = "rgba(31,111,235,0.35)"; ctx.fillRect(PAD - 6, ty - 3, W - 2 * PAD + 12, 30); }
    ctx.fillStyle = C.text;
    cols.forEach((c, i) => {
      const v = c === timeKey ? timeLabel(x.t) : fmt(x.r[c], 200);
      ctx.fillText(fitText(ctx, v, colW - 12), PAD + i * colW, ty);
    });
    hits.push({ x: PAD, y: ty - 3, w: W - 2 * PAD, h: 30, action: { type: "select", key: x.i } });
    ty += 32;
  }
  if (!pageRows.length) { ctx.fillStyle = C.dim; ctx.fillText("nothing here", PAD, ty); ty += 32; }
  ty += 8;
  button(ctx, hits, PAD, ty, 54, 38, "‹", { type: "page", delta: -1, max: pages - 1 });
  ctx.fillStyle = C.text; ctx.font = "20px system-ui, sans-serif"; ctx.textBaseline = "middle";
  ctx.fillText(`${view.page + 1} / ${pages}  (${shown.length})`, PAD + 66, ty + 19);
  ctx.textBaseline = "top";
  button(ctx, hits, PAD + 230, ty, 54, 38, "›", { type: "page", delta: 1, max: pages - 1 });
  const sizes = [5, 8, 15, 30];
  sizes.forEach((s, i) => button(ctx, hits, W - PAD - (sizes.length - i) * 60, ty, 54, 38, String(s), { type: "page_size", size: s }, pageSize === s));
  return ty + 38 + PAD;
}

function numericKeys(rows, exclude) {
  const keys = [];
  for (const r of rows.slice(-20)) for (const [k, v] of Object.entries(r)) if (typeof v === "number" && k !== exclude && !keys.includes(k)) keys.push(k);
  return keys.slice(0, 6);
}

function renderLine(ctx, W, t, value, view, hits) {
  const o = t.options || {};
  let rows, xKey, series;
  const isLive = typeof value === "number" || (value && typeof value === "object" && !Array.isArray(value)
                 && Object.values(value).some((v) => typeof v === "number"));
  if (isLive) {                                          // a live value: keep its history here, one point per refresh
    view.history ||= [];
    const now = Date.now() / 1000;
    const last = view.history[view.history.length - 1];
    if (!last || now - last.t >= 0.5) view.history.push({ t: now, ...(typeof value === "number" ? { value } : value) });
    if (view.history.length > 600) view.history.shift();
    rows = view.history; xKey = "t";
    series = o.series?.length ? o.series : numericKeys(rows, "t");
  } else {
    rows = rowsOf(value);
    xKey = detectTimeKey(rows, o.x_key);
    series = o.series?.length ? o.series : numericKeys(rows, xKey);
  }
  const items = rows.map((r, i) => ({ r, i, t: xKey ? toTime(r[xKey]) : i }));
  let y = view._top;
  y += drawTimeline(ctx, hits, PAD, y, W - 2 * PAD, items, view, (x) => x.i, null) || 0;
  const tl = view.timeline;
  const vis = items.filter((x) => x.t != null && (!tl || (x.t >= tl.t0 && x.t <= tl.t1)));
  const H = 260, X = PAD + 50, Wc = W - X - PAD;
  let lo = Infinity, hi = -Infinity;
  for (const x of vis) for (const s of series) { const v = x.r[s]; if (typeof v === "number") { lo = Math.min(lo, v); hi = Math.max(hi, v); } }
  if (!isFinite(lo)) { ctx.fillStyle = C.dim; ctx.font = "21px system-ui"; ctx.fillText("no numbers to plot", PAD, y); return y + 40 + PAD; }
  if (hi === lo) { hi += 1; lo -= 1; }
  ctx.strokeStyle = C.grid; ctx.fillStyle = C.dim; ctx.font = "17px system-ui";
  for (let i = 0; i <= 4; i++) {
    const gy = y + H - (H * i) / 4; ctx.beginPath(); ctx.moveTo(X, gy); ctx.lineTo(X + Wc, gy); ctx.stroke();
    ctx.fillText(fmt(lo + ((hi - lo) * i) / 4), PAD - 8, gy - 9);
  }
  const t0 = tl ? tl.t0 : vis[0].t, t1 = tl ? tl.t1 : vis[vis.length - 1].t, span = Math.max(1e-9, t1 - t0);
  const px = (tt) => X + ((tt - t0) / span) * Wc, py = (v) => y + H - ((v - lo) / (hi - lo)) * H;
  series.forEach((s, si) => {
    ctx.strokeStyle = C.series[si % C.series.length]; ctx.lineWidth = 3; ctx.beginPath();
    let started = false;
    for (const x of vis) { const v = x.r[s]; if (typeof v !== "number") continue; if (!started) { ctx.moveTo(px(x.t), py(v)); started = true; } else ctx.lineTo(px(x.t), py(v)); }
    ctx.stroke();
    for (const x of vis) {
      const v = x.r[s]; if (typeof v !== "number") continue;
      const k = `${x.i}:${s}`, sel = view.selected === k;
      if (sel || vis.length < 80) { ctx.fillStyle = sel ? "#fff" : ctx.strokeStyle; ctx.beginPath(); ctx.arc(px(x.t), py(v), sel ? 8 : 4, 0, Math.PI * 2); ctx.fill(); }
      hits.push({ x: px(x.t) - 10, y: py(v) - 10, w: 20, h: 20, action: { type: "select", key: k }, point: true });
      if (sel) { ctx.fillStyle = "#fff"; ctx.font = "bold 20px system-ui"; ctx.fillText(`${s}: ${fmt(v)} @ ${timeLabel(x.t)}`, Math.min(px(x.t) + 10, X + Wc - 260), Math.max(y, py(v) - 30)); }
    }
  });
  y += H + 12;
  series.forEach((s, si) => { ctx.fillStyle = C.series[si % C.series.length]; ctx.fillRect(PAD + si * 160, y + 6, 18, 18); ctx.fillStyle = C.text; ctx.font = "19px system-ui"; ctx.fillText(String(s), PAD + si * 160 + 26, y + 4); });
  hits.push({ x: X, y: view._top, w: Wc, h: y - view._top, action: { type: "timeline_area" }, timeline: true });
  return y + 34 + PAD;
}

function slicesOf(value, o) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value).filter(([, v]) => typeof v === "number").map(([label, v]) => ({ label, v }));
  }
  const rows = rowsOf(value);
  const acc = new Map();
  const labelKey = o.label_key || (rows[0] && Object.keys(rows[0]).find((k) => typeof rows[0][k] === "string")) || "value";
  for (const r of rows) {
    const raw = r[labelKey];
    const labels = Array.isArray(raw) ? raw : [raw];
    for (const l of labels) {
      const label = l == null ? "—" : String(l);
      acc.set(label, (acc.get(label) || 0) + (o.value_key ? Number(r[o.value_key]) || 0 : 1));
    }
  }
  return [...acc.entries()].map(([label, v]) => ({ label, v })).sort((a, b) => b.v - a.v).slice(0, o.max_slices || 10);
}

function renderPie(ctx, W, t, value, view, hits) {
  const sl = slicesOf(value, t.options || {});
  const total = sl.reduce((a, s) => a + s.v, 0) || 1;
  const y = view._top, R = 130, cx = PAD + R + 10, cy = y + R + 10;
  let a0 = -Math.PI / 2;
  sl.forEach((s, i) => {
    const a1 = a0 + (s.v / total) * Math.PI * 2;
    ctx.fillStyle = C.series[i % C.series.length];
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, view.selected === s.label ? R + 10 : R, a0, a1); ctx.closePath(); ctx.fill();
    a0 = a1;
  });
  let ly = y + 10;
  sl.forEach((s, i) => {
    const lx = cx + R + 40, sel = view.selected === s.label;
    ctx.fillStyle = C.series[i % C.series.length]; ctx.fillRect(lx, ly + 4, 20, 20);
    ctx.fillStyle = sel ? "#fff" : C.text; ctx.font = (sel ? "bold " : "") + "21px system-ui";
    ctx.fillText(`${fmt(s.label, 22)}  ${fmt(s.v)} (${Math.round((s.v / total) * 100)}%)`, lx + 30, ly + 2);
    hits.push({ x: lx, y: ly, w: W - lx - PAD, h: 28, action: { type: "select", key: s.label } });
    ly += 32;
  });
  return Math.max(cy + R + 20, ly) + PAD;
}

function renderBar(ctx, W, t, value, view, hits) {
  const sl = slicesOf(value, t.options || {});
  const y = view._top, H = 260, X = PAD, Wc = W - 2 * PAD;
  const hi = Math.max(1, ...sl.map((s) => s.v));
  const bw = Wc / Math.max(1, sl.length);
  sl.forEach((s, i) => {
    const h = (s.v / hi) * (H - 40), sel = view.selected === s.label;
    ctx.fillStyle = sel ? "#fff" : C.series[i % C.series.length];
    ctx.fillRect(X + i * bw + bw * 0.15, y + H - 40 - h, bw * 0.7, h);
    ctx.fillStyle = C.text; ctx.font = "18px system-ui"; ctx.textAlign = "center";
    ctx.fillText(fmt(s.v), X + i * bw + bw / 2, y + H - 40 - h - 22);
    ctx.fillText(fmt(s.label, Math.max(4, Math.floor(bw / 10))), X + i * bw + bw / 2, y + H - 32);
    ctx.textAlign = "left";
    hits.push({ x: X + i * bw, y, w: bw, h: H, action: { type: "select", key: s.label } });
  });
  return y + H + PAD;
}

function renderTree(ctx, W, t, value, view, hits) {
  view.open ||= { "": true };
  let y = view._top;
  const maxRows = (t.options || {}).max_rows || 40;
  let count = 0;
  ctx.font = "21px system-ui";
  const walk = (v, path, label, depth) => {
    if (count >= maxRows) return;
    const branch = v && typeof v === "object";
    const open = !!view.open[path];
    const x = PAD + depth * 24;
    ctx.fillStyle = branch ? C.accent : C.text;
    const head = branch ? `${open ? "▾" : "▸"} ${label}  ${Array.isArray(v) ? `[${v.length}]` : `{${Object.keys(v).length}}`}`
      : `${label}: ${fmt(v, 70)}`;
    if (label !== null) {
      ctx.fillText(head, x, y);
      if (branch) hits.push({ x, y: y - 2, w: W - x - PAD, h: 28, action: { type: "fold", path } });
      y += 28; count++;
    }
    if (branch && (open || label === null)) {
      const entries = Array.isArray(v) ? v.map((x, i) => [String(i), x]) : Object.entries(v);
      for (const [k, x] of entries.slice(0, 200)) walk(x, path ? `${path}.${k}` : k, k, depth + (label === null ? 0 : 1));
    }
  };
  if (value && typeof value === "object") walk(value, "", null, 0); else { ctx.fillStyle = C.text; ctx.fillText(fmt(value), PAD, y); y += 28; }
  if (count >= maxRows) { ctx.fillStyle = C.dim; ctx.fillText("…", PAD, y); y += 28; }
  return y + PAD;
}

// Rich text: a small HTML subset (h1-h3, p, div, br, li, b/strong, i/em, u, span style="color; font-size; font-family")
// with {{path}} placeholders filled from the data.
function renderText(ctx, W, t, value, view, hits) {
  const o = t.options || {};
  const base = { size: o.font_size || 26, family: o.font_family || "system-ui, sans-serif", color: o.color || C.text, bold: false, italic: false };
  const html = String(o.html || "{{}}").replace(/\{\{\s*([^}]*?)\s*\}\}/g, (_, p) => {
    const v = p === "" ? value : pathGet(value, p);
    return String(fmt(v, 400)).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  });
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const lines = [[]];
  const push = (text, st) => { for (const [i, part] of text.split("\n").entries()) { if (i) lines.push([]); if (part) lines[lines.length - 1].push({ text: part, st }); } };
  const block = (st) => { if (lines[lines.length - 1].length) lines.push([]); lines[lines.length - 1].st = st; };
  const walk = (node, st) => {
    for (const n of node.childNodes) {
      if (n.nodeType === 3) { push(n.textContent.replace(/\s+/g, " "), st); continue; }
      if (n.nodeType !== 1) continue;
      const tag = n.tagName.toLowerCase();
      const s = { ...st };
      if (tag === "b" || tag === "strong") s.bold = true;
      if (tag === "i" || tag === "em") s.italic = true;
      if (tag === "u") s.underline = true;
      if (/^h[1-3]$/.test(tag)) { s.bold = true; s.size = base.size * ({ h1: 1.8, h2: 1.45, h3: 1.2 })[tag]; }
      const style = n.getAttribute("style") || "";
      const color = /color:\s*([^;]+)/i.exec(style), size = /font-size:\s*(\d+)/i.exec(style), fam = /font-family:\s*([^;]+)/i.exec(style);
      if (color) s.color = color[1].trim();
      if (size) s.size = Number(size[1]) * (base.size / 16);
      if (fam) s.family = fam[1].trim();
      if (n.getAttribute("color")) s.color = n.getAttribute("color");
      if (tag === "br") { lines.push([]); continue; }
      const isBlock = /^(p|div|h[1-3]|li|ul|ol)$/.test(tag);
      if (isBlock) block(s);
      if (tag === "li") push("• ", s);
      walk(n, s);
      if (isBlock) lines.push([]);
    }
  };
  walk(doc.body.firstChild, base);
  let y = view._top;
  const maxW = W - 2 * PAD;
  for (const line of lines) {
    if (!line.length) { y += base.size * 0.5; continue; }
    // wrap runs word by word
    let x = PAD, lh = Math.max(...line.map((r) => r.st.size)) * 1.3;
    for (const run of line) {
      const st = run.st;
      ctx.font = `${st.italic ? "italic " : ""}${st.bold ? "bold " : ""}${Math.round(st.size)}px ${st.family}`;
      ctx.fillStyle = st.color;
      for (const word of run.text.split(/(\s+)/)) {
        const w = ctx.measureText(word).width;
        if (x + w > PAD + maxW && x > PAD && word.trim()) { x = PAD; y += lh; }
        ctx.fillText(word, x, y);
        if (st.underline && word.trim()) ctx.fillRect(x, y + st.size * 1.05, w, 2);
        x += w;
      }
    }
    y += lh;
  }
  return y + PAD;
}

const RENDERERS = { table: renderTable, line: renderLine, pie: renderPie, bar: renderBar, tree: renderTree, text: renderText };

// Draw `template` with `value` into ctx (a canvas `width` wide; the canvas height is set to what the panel needs).
export function renderPanel(ctx, width, template, value, view, subtitle) {
  const draw = RENDERERS[template.type] || renderTree;
  // first pass on a scratch canvas to learn the height, then draw for real at that height
  const scratch = renderPanel._scratch ||= document.createElement("canvas").getContext("2d");
  scratch.canvas.width = width; scratch.canvas.height = 4000;
  const measureView = { ...view, timeline: view.timeline && { ...view.timeline }, open: view.open, history: view.history };
  const top = frame(scratch, width, 4000, template.name || template.id, subtitle);
  measureView._top = top;
  const h = Math.ceil(draw(scratch, width, template, value, measureView, []));
  // a live series (line chart on a single value) got its new point in the measuring pass; keep that one array --
  // points closer than half a second apart are skipped, so the real pass below doesn't add it again
  if (measureView.history) view.history = measureView.history;
  const H = Math.max(h, top + 40);
  if (ctx.canvas.height !== H) ctx.canvas.height = H;
  if (ctx.canvas.width !== width) ctx.canvas.width = width;
  const hits = [];
  view._top = frame(ctx, width, H, template.name || template.id, subtitle);
  draw(ctx, width, template, value, view, hits);
  return { height: H, hits };
}

export function hitAt(hits, x, y) {                      // the topmost region under (x, y) (points before areas)
  let best = null;
  for (const h of hits) {
    if (x < h.x || x > h.x + h.w || y < h.y || y > h.y + h.h) continue;
    if (!best || (h.point && !best.point) || (!h.timeline && best.timeline)) best = h;
  }
  return best;
}
