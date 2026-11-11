// src/vrConversations.js -- VR "Conversations": a floating timeline (vrFloat.js frame: move, resize, lock, minimise)
// of a character's conversations, most recent first (/admin/convtrace/{id}, backend/api/conversation_trace.py).
//
// One row per conversation. Each conversation has its own symbol and colour: where it began and ended are marked
// in that colour, and every line of dialogue said in it (each speech bubble) in a brighter shade of the same, with
// the same symbol. One still going on runs on to "now". Point at a mark to read it (who said what, the speech act,
// when; for the begin / end marks: with whom, how, the subject, why it ended); trigger pins it. Right stick while
// pointing: ←/→ pan back in time, ↑/↓ zoom. ▲ / ▼ page through older conversations; LIVE follows now.
//
// The director's notes (backend/systems/dialogue_feedback.py): pin a line and 👍 Like / 👎 Dislike it, say why, or
// suggest a line that would have fit the character better -- by dictation or the pointer keyboard (vrKeyboard.js).
// A line with a note gets a 👍 / 👎 badge on the timeline.

import * as THREE from "three";

const PX_W = 1100, PX_H = 760;
const W_M = 1.05;
const POLL_S = 3;
const ROWS = 8;
const L = { left: 290, right: 1075, top: 74, rowH: 44, detailTop: 470 };
const SYMBOLS = ["circle", "square", "diamond", "triangle", "star", "hexagon", "cross"];
const fmtSpan = (s) => (s < 120 ? `${Math.round(s)} s` : s < 7200 ? `${Math.round(s / 60)} min` : s < 172800 ? `${(s / 3600).toFixed(1)} h` : `${Math.round(s / 86400)} days`);

function hash(s) { let h = 2166136261; for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
function styleOf(id) {
  const h = hash(id);
  const hue = (h % 360);
  return { symbol: SYMBOLS[(h >>> 9) % SYMBOLS.length], base: `hsl(${hue}, 70%, 46%)`, bright: `hsl(${hue}, 85%, 72%)` };
}
function symbol(c, kind, x, y, r) {
  c.beginPath();
  if (kind === "circle") c.arc(x, y, r, 0, Math.PI * 2);
  else if (kind === "square") c.rect(x - r * 0.85, y - r * 0.85, r * 1.7, r * 1.7);
  else if (kind === "diamond") { c.moveTo(x, y - r * 1.15); c.lineTo(x + r * 1.15, y); c.lineTo(x, y + r * 1.15); c.lineTo(x - r * 1.15, y); }
  else if (kind === "triangle") { c.moveTo(x, y - r * 1.2); c.lineTo(x + r * 1.1, y + r * 0.8); c.lineTo(x - r * 1.1, y + r * 0.8); }
  else if (kind === "star") for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * 0.5 : r * 1.25; c[i ? "lineTo" : "moveTo"](x + Math.cos(a) * rr, y + Math.sin(a) * rr); }
  else if (kind === "hexagon") for (let i = 0; i < 6; i++) { const a = i * Math.PI / 3; c[i ? "lineTo" : "moveTo"](x + Math.cos(a) * r * 1.1, y + Math.sin(a) * r * 1.1); }
  else { const t = r * 0.38; c.moveTo(x - t, y - r); c.lineTo(x + t, y - r); c.lineTo(x + t, y - t); c.lineTo(x + r, y - t); c.lineTo(x + r, y + t); c.lineTo(x + t, y + t);
         c.lineTo(x + t, y + r); c.lineTo(x - t, y + r); c.lineTo(x - t, y + t); c.lineTo(x - r, y + t); c.lineTo(x - r, y - t); c.lineTo(x - t, y - t); }
  c.closePath();
}

function setup(ctx) {
  const { renderer, scene, controllers } = ctx;
  const open = new Map();
  const raycaster = new THREE.Raycaster();
  const tmpM = new THREE.Matrix4();
  const hoverMine = [null, null];
  let clock = 0, lastT = performance.now();

  function make(charId) {
    const canvas = document.createElement("canvas");
    canvas.width = PX_W; canvas.height = PX_H;
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false }));
    mesh.renderOrder = 997; mesh.userData.ignoreRaycast = true; mesh.visible = false;
    scene.add(mesh);
    return { charId, canvas, ctx: canvas.getContext("2d"), tex, mesh, convs: [], tick: 0, live: true, end: null, span: null,
             page: 0, polled: -1e9, fetching: false, pinned: null, hotMark: null, hot: null, dirty: true, marks: [], btns: [] };
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
      const r = await fetch(`/admin/convtrace/${encodeURIComponent(p.charId)}?limit=60`);
      if (r.ok) {
        const j = await r.json();
        p.tick = j.tick; p.name = j.name; p.convs = j.conversations || [];
        if (p.span == null) {                 // first look: fit the three most recent (ten minutes at least, a day at most)
          const first = Math.min(...p.convs.slice(0, 3).map((c) => c.started_tick ?? c.lines[0]?.tick ?? p.tick), p.tick);
          p.span = Math.max(600, Math.min(86400, (p.tick - first) * 1.1));
        }
        // keep a pinned mark pinned across refreshes
        if (p.pinned) {
          const conv = p.convs.find((c) => c.id === p.pinned.conv.id);
          p.pinned = conv ? { ...p.pinned, conv, line: p.pinned.line && conv.lines.find((l) => l.tick === p.pinned.line.tick && l.utterance === p.pinned.line.utterance) } : null;
        }
        p.dirty = true;
      }
    } catch (_) { /* next time */ }
    p.fetching = false;
  }

  const t0 = (p) => (p.live ? p.tick : p.end) - p.span;
  const xOf = (p, t) => L.left + (t - t0(p)) / p.span * (L.right - L.left);

  function button(p, id, label, x, w, on) {
    const c = p.ctx, b = { id, x, y: 14, w, h: 42 };
    c.fillStyle = on ? "#238636" : (p.hot === id ? "#1f6feb" : "rgba(255,255,255,0.12)");
    c.beginPath(); c.roundRect(b.x, b.y, b.w, b.h, 10); c.fill();
    c.fillStyle = "#fff"; c.font = "bold 22px system-ui, sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(label, b.x + b.w / 2, b.y + b.h / 2); c.textAlign = "left";
    p.btns.push(b);
  }

  function draw(p) {
    const c = p.ctx;
    p.btns = []; p.marks = [];
    c.clearRect(0, 0, PX_W, PX_H);
    c.fillStyle = "rgba(14,17,24,0.95)"; c.fillRect(0, 0, PX_W, PX_H);
    c.textBaseline = "middle";
    const pages = Math.max(1, Math.ceil(p.convs.length / ROWS));
    c.fillStyle = "#c9d1d9"; c.font = "bold 26px system-ui, sans-serif";
    c.fillText(`${p.convs.length} conversation${p.convs.length === 1 ? "" : "s"} · ${p.page + 1}/${pages} · last ${fmtSpan(p.span || 3600)}`, 18, 35);
    button(p, "newer", "▲ newer", PX_W - 380, 110, false);
    button(p, "older", "▼ older", PX_W - 260, 110, false);
    button(p, "live", p.live ? "● LIVE" : "LIVE ▶", PX_W - 140, 120, p.live);
    if (p.span == null) { p.tex.needsUpdate = true; p.dirty = false; return; }
    const rows = p.convs.slice(p.page * ROWS, p.page * ROWS + ROWS);
    const start = t0(p), end = start + p.span;
    rows.forEach((cv, i) => {
      const y = L.top + i * L.rowH + L.rowH / 2;
      const st = styleOf(cv.id);
      c.fillStyle = i % 2 ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.06)"; c.fillRect(8, y - L.rowH / 2, PX_W - 16, L.rowH);
      // label: the symbol, with whom, how
      c.fillStyle = st.base; symbol(c, st.symbol, 26, y, 10); c.fill();
      const bad = cv.reach_now && Object.values(cv.reach_now).some((r) => !r.ok);
      c.fillStyle = bad ? "#ff8a7a" : cv.active ? "#ffffff" : "#c9d1d9"; c.font = `${cv.active ? "bold " : ""}20px system-ui, sans-serif`;
      let label = `${cv.active ? "● " : ""}${(cv.with || []).join(", ") || "?"}${cv.medium && cv.medium !== "in_person" ? ` · ${cv.medium}` : ""}`;
      while (c.measureText(label).width > L.left - 60 && label.length > 6) label = label.slice(0, -2);
      c.fillText(label, 44, y);
      // the span of the conversation
      const s = cv.started_tick ?? cv.lines[0]?.tick, e = cv.ended_tick ?? (cv.active ? p.tick : cv.lines[cv.lines.length - 1]?.tick);
      if (s == null) return;
      if (e < start || s > end) {                      // out of view: a hint which way it is
        c.fillStyle = "#8b98ad"; c.font = "18px system-ui, sans-serif";
        if (e < start) c.fillText(`◀ ${fmtSpan(p.tick - e)} ago`, L.left + 4, y);
        else { c.textAlign = "right"; c.fillText("later ▶", L.right - 4, y); c.textAlign = "left"; }
        return;
      }
      // begin / end and the bar between them in the lower half of the row, the lines said in the upper half (so the
      // first line, said the moment it began, isn't hidden under the begin mark)
      const yb = y + 8, yl = y - 9;
      const xs = Math.max(L.left, xOf(p, s)), xe = Math.min(L.right, xOf(p, e));
      c.strokeStyle = st.base; c.globalAlpha = 0.6; c.lineWidth = 4; c.beginPath(); c.moveTo(xs, yb); c.lineTo(xe, yb); c.stroke(); c.globalAlpha = 1;
      if (cv.active && xe >= L.right - 2) { c.fillStyle = st.base; c.beginPath(); c.moveTo(L.right, yb); c.lineTo(L.right - 12, yb - 8); c.lineTo(L.right - 12, yb + 8); c.fill(); }
      const mark = (kind, t, line, r, fill) => {
        if (t < start || t > end) return;
        const x = xOf(p, t), y = kind === "line" ? yl : yb;
        const on = (p.hotMark && p.hotMark.conv.id === cv.id && p.hotMark.kind === kind && p.hotMark.line === line) ||
                   (p.pinned && p.pinned.conv.id === cv.id && p.pinned.kind === kind && (p.pinned.line === line));
        c.fillStyle = fill; symbol(c, st.symbol, x, y, on ? r + 4 : r); c.fill();
        c.strokeStyle = on ? "#ffffff" : "rgba(0,0,0,0.6)"; c.lineWidth = on ? 3 : 1.5; c.stroke();
        p.marks.push({ conv: cv, kind, line, x, y, r: r + 6 });
      };
      for (const ln of cv.lines) {
        mark("line", ln.tick, ln, 7, st.bright);
        const fb = ln.feedback;
        if (fb && ln.tick >= start && ln.tick <= end) {           // the director's note on it: a badge above the mark
          const x = xOf(p, ln.tick), yy = y - 26;
          c.fillStyle = fb.verdict === "like" ? "#2ea043" : fb.verdict === "dislike" ? "#da3633" : "#8b98ad";
          c.beginPath();
          if (fb.verdict === "dislike") { c.moveTo(x - 6, yy - 4); c.lineTo(x + 6, yy - 4); c.lineTo(x, yy + 5); }
          else if (fb.verdict === "like") { c.moveTo(x - 6, yy + 4); c.lineTo(x + 6, yy + 4); c.lineTo(x, yy - 5); }
          else c.arc(x, yy, 4, 0, Math.PI * 2);
          c.fill();
          if (fb.comment || fb.suggestion) { c.fillStyle = "#ffd33d"; c.beginPath(); c.arc(x + 9, yy - 3, 3, 0, Math.PI * 2); c.fill(); }
        }
      }
      mark("start", s, null, 10, st.base);
      if (!cv.active && cv.ended_tick != null) mark("end", cv.ended_tick, null, 10, st.base);
    });
    // time axis
    const axisY = L.top + ROWS * L.rowH + 8;
    c.strokeStyle = "rgba(255,255,255,0.25)"; c.lineWidth = 2; c.beginPath(); c.moveTo(L.left, axisY); c.lineTo(L.right, axisY); c.stroke();
    c.fillStyle = "#8b98ad"; c.font = "18px system-ui, sans-serif"; c.textAlign = "center";
    for (let i = 0; i <= 4; i++) {
      const back = p.span * (1 - i / 4) + (p.live ? 0 : p.tick - p.end);
      c.fillText(back < 1 ? "now" : `−${fmtSpan(back)}`, L.left + i * (L.right - L.left) / 4, axisY + 18);
    }
    c.textAlign = "left";
    // details
    const d = p.hotMark || p.pinned;
    c.fillStyle = "rgba(255,255,255,0.05)"; c.fillRect(12, L.detailTop, PX_W - 24, PX_H - L.detailTop - 12);
    const out = [];
    if (!d) out.push(["Point at a mark to read it; trigger pins it. Right stick: ←/→ pan, ↑/↓ zoom.", "#8b98ad", "21px"]);
    else {
      const cv = d.conv, st = styleOf(cv.id);
      const pin = p.pinned && p.pinned.conv.id === cv.id && p.pinned.kind === d.kind && p.pinned.line === d.line ? "  📌" : "";
      if (d.kind === "line") {
        out.push([`${d.line.speaker_name} · ${d.line.speech_act || "?"} · ${fmtSpan(Math.max(0, p.tick - d.line.tick))} ago${pin}`, st.bright, "bold 22px"]);
        out.push([`“${d.line.utterance}”`, "#ffffff", "23px"]);
        out.push([`in the conversation with ${(cv.with || []).join(", ")}${cv.subject ? ` about ${cv.subject}` : ""}`, "#8b98ad", "19px"]);
        const fb = d.line.feedback;
        if (fb) {
          out.push([`${fb.verdict === "like" ? "👍 liked" : fb.verdict === "dislike" ? "👎 disliked" : "note"}${fb.comment ? ` — ${fb.comment}` : ""}`,
                    fb.verdict === "dislike" ? "#ff8a7a" : fb.verdict === "like" ? "#7ee787" : "#c9d1d9", "20px"]);
          if (fb.suggestion) out.push([`💡 would fit better: “${fb.suggestion}”`, "#ffd33d", "20px"]);
        }
        if (!pin) out.push(["Pull the trigger on it to pin it -- then like / dislike it, say why, or suggest a better line.", "#8b98ad", "18px"]);
      } else {
        const when = d.kind === "start" ? cv.started_tick : cv.ended_tick;
        out.push([`${d.kind === "start" ? "BEGAN" : "ENDED"} · ${fmtSpan(Math.max(0, p.tick - (when ?? p.tick)))} ago · with ${(cv.with || []).join(", ")} · ${cv.medium || "in person"}${pin}`, st.base, "bold 22px"]);
        const meta = [cv.subject && `subject: ${cv.subject}`, cv.topic && cv.topic !== "general" && `topic: ${cv.topic}`, cv.tone && `tone: ${cv.tone}`,
                      cv.type && `kind: ${cv.type}`, d.kind === "end" && cv.end_reason && `why it ended: ${cv.end_reason}`,
                      `${cv.lines.length} line${cv.lines.length === 1 ? "" : "s"}`,
                      cv.started_tick != null && cv.ended_tick != null && `lasted ${fmtSpan(cv.ended_tick - cv.started_tick)}`].filter(Boolean).join(" · ");
        out.push([meta, "#c9d1d9", "20px"]);
        if (cv.reach_now) for (const [who, r] of Object.entries(cv.reach_now))
          out.push([r.ok ? `✔ ${who} is within sight and earshot (${r.distance} tiles)` : `✘ ${who}: ${r.issues.join(", ")}`, r.ok ? "#7ee787" : "#ff8a7a", "20px"]);
        const first = cv.lines[0];
        if (first) out.push([`first line: ${first.speaker_name}: “${first.utterance}”`, "#c9d1d9", "19px"]);
      }
    }
    const pinnedLine = p.pinned?.kind === "line" && (!p.hotMark || (p.hotMark.kind === "line" && p.hotMark.line === p.pinned.line)) ? p.pinned : null;
    const textBottom = pinnedLine ? PX_H - 80 : PX_H - 22;
    let y = L.detailTop + 24;
    for (const [text, col, font] of out) {
      c.fillStyle = col; c.font = `${font} system-ui, sans-serif`;
      for (const piece of wrap(c, text, PX_W - 60)) { if (y > textBottom) break; c.fillText(piece, 26, y); y += 28; }
    }
    if (pinnedLine) {                                   // the director's note on the pinned line
      const fb = pinnedLine.line.feedback || {};
      const by = PX_H - 68, defs = [["fb:like", fb.verdict === "like" ? "👍 Liked" : "👍 Like", fb.verdict === "like"],
        ["fb:dislike", fb.verdict === "dislike" ? "👎 Disliked" : "👎 Dislike", fb.verdict === "dislike"],
        ["fb:comment", fb.comment ? "✎ Edit why" : "✎ Why…", false], ["fb:suggest", fb.suggestion ? "💡 Edit line" : "💡 Suggest a line…", false],
        ["fb:clear", "Clear note", false]];
      const bw = (PX_W - 24 - 4 * 10) / 5;
      defs.forEach(([id, label, on], i) => {
        const b = { id, x: 12 + i * (bw + 10), y: by, w: bw, h: 52 };
        c.fillStyle = on ? (id === "fb:like" ? "#238636" : "#a40e26") : (p.hot === id ? "#1f6feb" : "rgba(255,255,255,0.12)");
        c.beginPath(); c.roundRect(b.x, b.y, b.w, b.h, 10); c.fill();
        c.fillStyle = "#fff"; c.font = "bold 22px system-ui, sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
        c.fillText(label, b.x + b.w / 2, b.y + b.h / 2); c.textAlign = "left";
        p.btns.push(b);
      });
      if (p.saving) { c.fillStyle = "#8b98ad"; c.font = "18px system-ui, sans-serif"; c.fillText(p.saving, 26, by - 14); }
    }
    p.tex.needsUpdate = true;
    p.dirty = false;
  }
  function wrap(c, text, maxW) {
    const out = []; let cur = "";
    for (const w of String(text).split(/\s+/)) { const t = cur ? cur + " " + w : w; if (c.measureText(t).width > maxW && cur) { out.push(cur); cur = w; } else cur = t; }
    if (cur) out.push(cur);
    return out;
  }

  // ---- the director's notes (backend/systems/dialogue_feedback.py) ----
  async function send(p, line, conv, change) {
    p.saving = "saving…"; p.dirty = true;
    try {
      const r = await fetch(`/admin/feedback/${encodeURIComponent(line.speaker)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conv_id: conv.id, tick: line.tick, utterance: line.utterance, ...change }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      line.feedback = j.note ? { id: j.note.id, verdict: j.note.verdict, comment: j.note.comment, suggestion: j.note.suggestion } : undefined;
      p.saving = null;
    } catch (err) { p.saving = `couldn't save: ${err.message}`; }
    p.dirty = true;
  }
  function feedback(p, what) {
    const { line, conv } = p.pinned;
    const fb = line.feedback || {};
    if (what === "like" || what === "dislike") return send(p, line, conv, { verdict: fb.verdict === what ? null : what });
    if (what === "clear") return send(p, line, conv, { verdict: null, comment: "", suggestion: "" });
    const who = line.speaker_name || "them";
    window.vrKeyboard?.open(what === "comment"
      ? { title: "Why?", prompt: `${who}: “${line.utterance}” — what's right or wrong about it for ${who}?`, text: fb.comment || "",
          onDone: (text) => send(p, line, conv, { comment: text }) }
      : { title: "A line that would fit better", prompt: `Instead of “${line.utterance}”, what would ${who} have said?`, text: fb.suggestion || "",
          onDone: (text) => send(p, line, conv, { suggestion: text }) });
  }

  function pointAt() {
    controllers.forEach((controller, i) => {
      hoverMine[i] = null;
      if (!renderer.xr.isPresenting || window.vrFloat?.hovering(i) || window.vrKeyboard?.isOpen()) return;
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
      let hotMark = null, hot = null;
      if (h) {
        hot = p.btns.find((b) => h.x >= b.x && h.x <= b.x + b.w && h.y >= b.y && h.y <= b.y + b.h)?.id || null;
        let bestD = 1e9;
        for (const m of p.marks) {
          const dd = Math.hypot(m.x - h.x, m.y - h.y);
          if (dd < m.r && dd < bestD) { bestD = dd; hotMark = m; }
        }
      }
      const same = (a, b) => (a && b ? a.conv.id === b.conv.id && a.kind === b.kind && a.line === b.line : a === b);
      if (!same(hotMark, p.hotMark) || hot !== p.hot) { p.hotMark = hotMark && { conv: hotMark.conv, kind: hotMark.kind, line: hotMark.line }; p.hot = hot; p.dirty = true; }
    }
  }

  function stick() {
    controllers.forEach((controller, i) => {
      const h = hoverMine[i];
      if (!h) return;
      const src = controller.userData.inputSource;
      const g = src?.handedness === "right" ? src.gamepad : null;
      if (!g || g.axes.length < 4) return;
      const [, , x, y] = g.axes;
      const p = open.get(h.charId);
      if (!p || p.span == null) return;
      if (Math.abs(x) > 0.2) {
        if (p.live) { p.live = false; p.end = p.tick; }
        p.end = Math.min(p.tick, p.end + x * p.span * 0.02);
        if (p.end >= p.tick - 1 && x > 0) p.live = true;
        p.dirty = true;
      }
      if (Math.abs(y) > 0.2) {
        const frac = Math.max(0, Math.min(1, (h.x - L.left) / (L.right - L.left)));
        const anchor = t0(p) + frac * p.span;
        const span = Math.max(60, Math.min(30 * 86400, p.span * (1 + y * 0.04)));
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
      const pages = Math.max(1, Math.ceil(p.convs.length / ROWS));
      if (p.hot === "live") { p.live = true; p.dirty = true; return; }
      if (p.hot?.startsWith("fb:") && p.pinned?.kind === "line") return feedback(p, p.hot.slice(3));
      if (p.hot === "newer") { p.page = Math.max(0, p.page - 1); p.dirty = true; return; }
      if (p.hot === "older") { p.page = Math.min(pages - 1, p.page + 1); p.dirty = true; return; }
      const m = p.hotMark;
      const same = m && p.pinned && p.pinned.conv.id === m.conv.id && p.pinned.kind === m.kind && p.pinned.line === m.line;
      p.pinned = m && !same ? m : null;
      p.dirty = true;
    });
  });

  (window.vrHoverOwners ||= []).push((i) => !!hoverMine[i]);
  window.xrFrameHooks.push(() => {
    const t = performance.now(); clock += (t - lastT) / 1000; lastT = t;
    for (const p of open.values()) {
      if (clock - p.polled > POLL_S) { p.polled = clock; poll(p); }
      if (p.dirty || (p.live && Math.floor(clock) !== p.lastLiveDraw)) { p.lastLiveDraw = Math.floor(clock); draw(p); }
      const name = p.name || window.getWorldCharacter?.(p.charId)?.name || p.charId;
      window.vrFloat?.show(`conv|${p.charId}`, { charId: p.charId, title: `Conversations — ${name}`, icon: "💬", mesh: p.mesh,
                                                  widthM: W_M, heightM: W_M * PX_H / PX_W, onClose: () => close(p.charId) });
    }
    pointAt();
    stick();
  });
  window.vrConversations = {
    toggle, isOpen: (id) => open.has(id),
    state: (id) => { const p = open.get(id); return p && { convs: p.convs.length, page: p.page, live: p.live, span: p.span,
      hot: p.hotMark && { kind: p.hotMark.kind, conv: p.hotMark.conv.id, line: p.hotMark.line?.utterance },
      pinned: p.pinned && { kind: p.pinned.kind, conv: p.pinned.conv.id },
      marks: p.marks.map((m) => ({ kind: m.kind, conv: m.conv.id, world: p.mesh.localToWorld(new THREE.Vector3(m.x / PX_W - 0.5, 0.5 - m.y / PX_H, 0)).toArray() })),
      buttons: Object.fromEntries(p.btns.map((b) => [b.id, p.mesh.localToWorld(new THREE.Vector3((b.x + b.w / 2) / PX_W - 0.5, 0.5 - (b.y + b.h / 2) / PX_H, 0)).toArray()])) }; },
  };
}

(function waitForXR(attempts = 50) {
  const ctx = window.getXRContext?.();
  if (ctx && window.xrFrameHooks) return setup(ctx);
  if (attempts > 0) setTimeout(() => waitForXR(attempts - 1), 100);
})();
