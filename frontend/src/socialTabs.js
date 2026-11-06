// Inspector "Issues" and "Standing" tabs (backend/social/).
//   Issues: c.issue_log -- the problems between the selected character and others (open first), each with its
//     category, everyone's own position, and its confrontations (c.confrontation_log). A click opens it: positions,
//     evidence, what happened in order, the confrontations (type, problem, stages, sides, outcome) and the
//     conversations filed under it.
//   Standing: one row per person they know -- how they regard them (standing, -100..100), how frustrated they are,
//     and whether they've been reaching out or keeping away. A click opens all of it: standing with its confidence,
//     frustration in general and per issue, initiative, the relationship values, what's outstanding (issues,
//     agreements and expectations, grudges, rifts, rumours heard about them), and a chart of how it changed.
// (The functions keep their old names: main.js wires them to the tab ids viewerArgumentsTab / viewerStandingTab.)

const INTENSITY_DECAY_PER_DAY = 15;      // keep in step with backend/social/frustration.py
const SCORE_DECAY_PER_DAY = 6;
const DAY = 86400;

const SCALE = [[80, "extremely high regard"], [50, "strong positive regard"], [20, "generally favourable"],
  [-19, "neutral or uncertain"], [-49, "negative regard"], [-79, "very poor regard"], [-101, "extreme contempt"]];

function legacyStanding(rel) {
  return (rel.friendship || 0) + 0.5 * (rel.trust || 0) + 0.5 * (rel.respect || 0) + 0.3 * (rel.warmth || 0)
    - (rel.resentment || 0) - (rel.hostility || 0);
}

export function standingOf(rel) {
  rel = rel || {};
  if (rel.standing && typeof rel.standing === "object") return rel.standing.score || 0;
  return Math.max(-100, Math.min(100, legacyStanding(rel)));
}

function standingLabel(v) {
  for (const [floor, t] of SCALE) if (v >= floor) return t;
  return SCALE[SCALE.length - 1][1];
}

function decayed(f, tick) {
  if (!f) return { score: 0, intensity: 0 };
  const days = Math.max(0, (tick - (f.tick || tick)) / DAY);
  return { score: Math.max(0, (f.score || 0) - SCORE_DECAY_PER_DAY * (1 - (f.persistence || 0.1)) * days),
           intensity: Math.max(0, (f.intensity || 0) - INTENSITY_DECAY_PER_DAY * days) };
}

export function frustrationOf(rel, tick, issueId) {
  const fr = (rel || {}).frustration;
  if (!fr) {
    const a = (rel || {}).agitation;
    return { score: 0, intensity: a ? Math.max(0, (a.value || 0) - INTENSITY_DECAY_PER_DAY * Math.max(0, (tick - (a.tick || 0)) / DAY)) : 0 };
  }
  return decayed(issueId ? (fr.issues || {})[issueId] : fr.general, tick);
}

function word(v) {
  return v >= 80 ? "furious" : v >= 60 ? "angry" : v >= 30 ? "irritated" : v >= 10 ? "a little put out" : "calm";
}

function standingColor(v) {
  return v < -50 ? "#f85149" : v < -20 ? "#d29922" : v < 20 ? "#8b949e" : "#3fb950";
}

const pretty = (s) => String(s || "").replace(/_/g, " ");

// ---- Issues ------------------------------------------------------------------------------------------------------------

export function renderArgumentsTab(c, ctx) {
  const el = document.getElementById("viewerArgumentsTab");
  if (!el) return;
  const open = (i) => ["open", "reopened"].includes(i.status) ? 0 : i.status === "dormant" ? 1 : 2;
  const list = [...(c.issue_log || [])].sort((a, b) => open(a) - open(b) || (b.last_activity || 0) - (a.last_activity || 0));
  const confs = c.confrontation_log || [];
  if (!list.length) {
    el.innerHTML = ctx.section("Issues (0)", ctx.empty("No issues with anyone."));
    return;
  }
  const color = { open: "#f85149", reopened: "#f85149", dormant: "#d29922", resolved: "#3fb950" };
  const cards = list.map(i => {
    const others = (i.involved_parties || []).filter(p => p !== c.id).map(ctx.name).join(", ") || "nobody";
    const mine = (i.positions || {})[c.id];
    const theirs = Object.entries(i.positions || {}).filter(([p]) => p !== c.id);
    const active = confs.find(x => x.issue_id === i.id && x.status === "active");
    return `<div class="viewerCard viewerCardClickable" data-arg-id="${ctx.esc(i.id)}">
      <div><span style="color:${color[i.status] || "#8b949e"}">${ctx.esc(i.status)}</span> · <b>${ctx.esc(i.subject)}</b>
        <span style="opacity:.6">(${ctx.esc(pretty(i.category))})</span></div>
      <div style="opacity:.75">with ${ctx.esc(others)} · ${(i.conversation_ids || []).length} conversations ·
        ${(i.confrontation_ids || []).length} confrontations · ${(i.fight_ids || []).length} fights · ${(i.evidence || []).length} evidence</div>
      ${mine && mine.position ? `<div style="font-size:.9em">${ctx.esc(c.name.split(" ")[0])}: “${ctx.esc(mine.position)}” <span style="opacity:.55">(${ctx.esc(mine.stance)})</span></div>` : ""}
      ${theirs.map(([p, x]) => x.position ? `<div style="font-size:.9em;opacity:.8">${ctx.esc(ctx.name(p).split(" ")[0])}: “${ctx.esc(x.position)}” <span style="opacity:.55">(${ctx.esc(x.stance)})</span></div>` : "").join("")}
      ${active ? `<div style="color:#f85149;font-size:.85em">confrontation under way: ${ctx.esc(pretty(active.confrontation_type))}, ${ctx.esc(pretty(active.stage))}</div>` : ""}
      <div style="opacity:.55;font-size:.85em">since ${ctx.fmt(i.created_at) || "?"}${i.resolved_at ? ` · resolved ${ctx.fmt(i.resolved_at)}${i.resolution ? ": " + ctx.esc(i.resolution) : ""}` : ""}</div>
    </div>`;
  }).join("");
  const n = list.filter(i => open(i) === 0).length;
  el.innerHTML = ctx.section(`Issues (${n} open, ${list.length - n} quiet or resolved)`, cards);
}

function confrontationBlock(x, ctx) {
  const parts = Object.values(x.participants || {});
  const sides = parts.map(p => `${ctx.esc(ctx.name(p.character_id))} <span style="opacity:.6">(${ctx.esc(p.role)}${
    ["initiator", "target"].includes(p.side) && !["initiator", "target"].includes(p.role) ? ", with " + ctx.esc(ctx.name(p.side === "initiator" ? x.initiator_id : x.primary_target_id).split(" ")[0]) : ""})</span>`).join(", ");
  const res = x.resolution;
  const steps = (x.escalation_history || []).filter(h => ["escalated", "de-escalated", "joined", "storm_off", "intervention", "resolved"].includes(h.what));
  return `<div class="viewerCard" style="margin:6px 0">
    <div><b>${ctx.esc(pretty(x.confrontation_type))}</b>${x.original_type !== x.confrontation_type ? ` <span style="opacity:.6">(began as ${ctx.esc(pretty(x.original_type))})</span>` : ""}
      · ${ctx.esc(ctx.name(x.initiator_id))} → ${ctx.esc(ctx.name(x.primary_target_id))}
      · ${x.status === "active" ? `<span style="color:#f85149">${ctx.esc(pretty(x.stage))}</span>` : `peaked at ${ctx.esc(pretty(x.peak_stage))}`}</div>
    <div style="font-size:.9em">Problem: ${ctx.esc(x.problem_statement || "")}${x.desired_outcome ? ` · wants: ${ctx.esc(x.desired_outcome)}` : ""}</div>
    ${x.initiator_position ? `<div style="font-size:.85em;opacity:.8">${ctx.esc(ctx.name(x.initiator_id).split(" ")[0])}: ${ctx.esc(x.initiator_position)}</div>` : ""}
    ${x.target_position ? `<div style="font-size:.85em;opacity:.8">${ctx.esc(ctx.name(x.primary_target_id).split(" ")[0])}: ${ctx.esc(x.target_position)}</div>` : ""}
    <div style="font-size:.85em">In it: ${sides}</div>
    <div style="font-size:.85em;opacity:.75">intensity ${Math.round(x.emotional_intensity || 0)} · aggression ${Math.round(x.aggression || 0)} · seen by others ${Math.round((x.public_visibility || 0) * 100)}%</div>
    ${steps.map(h => `<div style="font-size:.8em;opacity:.7">${ctx.fmt(h.tick) || ""} ${ctx.esc(h.what)}${h.to && h.what !== "line" ? " → " + ctx.esc(pretty(h.to)) : ""} ${ctx.esc(h.why || "")}</div>`).join("")}
    ${res ? `<div style="font-size:.9em;margin-top:3px"><b>${ctx.esc(pretty(res.outcome))}</b>${res.summary ? ": " + ctx.esc(res.summary) : ""}</div>` : ""}
  </div>`;
}

export function openArgumentModal(c, issueId, ctx) {
  const i = (c.issue_log || []).find(x => x.id === issueId);
  if (!i) return;
  ctx.modal(`Issue: ${i.subject}`, (body) => {
    const rows = [
      ["Between", (i.involved_parties || []).map(ctx.name).join(" and ")],
      ["Kind", pretty(i.category)],
      ["Raised by", i.created_by ? ctx.name(i.created_by) : "?"],
      ["Status", i.status + (i.resolution ? ` -- ${i.resolution}` : "")],
      ["Since", ctx.fmt(i.created_at)],
    ];
    let html = rows.map(([k, v]) => `<div class="eventModalRow"><div class="eventModalRowMeta">${ctx.esc(k)}</div><div>${ctx.esc(v || "")}</div></div>`).join("");
    html += `<div class="viewerSectionTitle" style="margin-top:12px">How each sees it</div>` + (Object.entries(i.positions || {}).map(([p, x]) =>
      `<div style="margin-bottom:5px"><b>${ctx.esc(ctx.name(p))}</b> <span style="opacity:.6">(${ctx.esc(x.stance)}, ${Math.round((x.confidence || 0) * 100)}% sure, ${ctx.esc(x.basis || "")})</span>: ${ctx.esc(x.position || "")}
        ${(x.history || []).length ? `<div style="font-size:.8em;opacity:.6">before: ${(x.history || []).map(h => ctx.esc(h.position)).join(" → ")}</div>` : ""}</div>`).join("")
      || `<div style="opacity:.6">Nobody has said yet.</div>`);
    const infl = Object.entries(i.influences || {});
    if (infl.length) html += `<div class="viewerSectionTitle" style="margin-top:12px">Who's been shaping their view</div>` + infl.map(([obs, list]) =>
      list.map(x => `<div style="font-size:.9em">${ctx.esc(ctx.name(obs))} ← ${ctx.esc(ctx.name(x.source_id))} (${Math.round(x.influence_strength * 100)}%): ${ctx.esc(x.source_position)}</div>`).join("")).join("");
    if ((i.evidence || []).length) html += `<div class="viewerSectionTitle" style="margin-top:12px">Evidence</div>` + evidenceGroups(i.evidence, ctx);
    const confs = (c.confrontation_log || []).filter(x => x.issue_id === i.id);
    if (confs.length) html += `<div class="viewerSectionTitle" style="margin-top:12px">Confrontations (${confs.length})</div>` + confs.map(x => confrontationBlock(x, ctx)).join("");
    html += `<div class="viewerSectionTitle" style="margin-top:12px">What happened</div>` + (collapseRuns([...(i.events || [])].sort((a, b) => (a.tick || 0) - (b.tick || 0)),
      e => `${e.what}|${e.detail || ""}`).map(r => {
        const e = r.first;
        const when = r.n > 1 ? `${ctx.fmt(r.first.tick) || ""} – ${ctx.fmt(r.last.tick) || ""}` : (ctx.fmt(e.tick) || "");
        return `<div style="margin-bottom:3px;font-size:.9em"><span style="opacity:.6">${when}</span> <b>${ctx.esc(e.what)}</b> ${ctx.esc(e.detail || "")}${r.n > 1 ? ` <b>×${r.n}</b>` : ""}</div>`;
      }).join("")
      || `<div style="opacity:.6">Nothing recorded yet.</div>`);
    const convs = (c.conversation_log || []).filter(e => (i.conversation_ids || []).includes(e.id || e.conv_id))
      .sort((x, y) => (x.ended_tick || 0) - (y.ended_tick || 0));
    html += `<div class="viewerSectionTitle" style="margin-top:12px">Conversations (${convs.length})</div>` + (convs.map(e => {
      const t = e.tags || {};
      return `<div class="viewerCard viewerCardClickable" data-modal-conv="${ctx.esc(e.id || e.conv_id)}">
        <div style="opacity:.6">${ctx.fmt(e.ended_tick) || ""} · ${ctx.esc(ctx.name(e.initiator))} opened with ${ctx.esc(pretty(t.opening || "?"))}</div>
        <div><b>${ctx.esc(t.subject || e.subject || "")}</b></div>
        ${(e.lines || []).slice(0, 2).map(l => `<div style="opacity:.8"><span style="opacity:.6">${ctx.clock(l.tick)}</span> ${ctx.esc(ctx.name(l.speaker))}: "${ctx.esc(l.utterance)}"</div>`).join("")}
      </div>`;
    }).join("") || `<div style="opacity:.6">None of ${ctx.esc(c.name)}'s logged conversations are filed here.</div>`);
    body.innerHTML = html;
    body.onclick = (ev) => {
      const card = ev.target.closest("[data-modal-conv]");
      if (!card) return;
      const entry = (c.conversation_log || []).find(e => (e.id || e.conv_id) === card.dataset.modalConv);
      if (entry) ctx.openConversation(entry);
    };
  });
}

// Identical lines in a row are one line with a count and a time range ("evidence: envy ... ×73"), not 73 lines.
function collapseRuns(list, keyOf) {
  const out = [];
  for (const e of list) {
    const last = out[out.length - 1];
    if (last && last.key === keyOf(e)) { last.n++; last.last = e; }
    else out.push({ key: keyOf(e), n: 1, first: e, last: e });
  }
  return out;
}

// The same thing coming up again and again is one row: how often, who brought it up, what brought it up each time
// (systems/life_comparison.py records that -- "saw Robert (kitchen)", "Robert came up: Susan said ..."), and a chart of
// how often it came up over time.
function evidenceGroups(evidence, ctx) {
  const groups = new Map();
  for (const e of evidence) {
    const text = String(e.text || "");
    const cut = text.indexOf(": ");
    const base = cut > 0 ? text.slice(0, cut) : text, trigger = cut > 0 ? text.slice(cut + 2) : "";
    const key = `${e.kind}|${base}`;
    if (!groups.has(key)) groups.set(key, { kind: e.kind, base, items: [] });
    groups.get(key).items.push({ ...e, trigger });
  }
  return [...groups.values()].map(g => {
    const items = g.items.sort((a, b) => (a.tick || 0) - (b.tick || 0));
    const by = {};
    for (const x of items) if (x.by) by[x.by] = (by[x.by] || 0) + 1;
    const who = Object.entries(by).sort((a, b) => b[1] - a[1]).map(([id, n]) => `${ctx.esc(ctx.name(id))} ${n}`).join(", ");
    const head = `<div style="font-size:.9em"><b>${ctx.esc(pretty(g.kind))}: ${ctx.esc(g.base)}</b>${items.length > 1 ? ` <b>×${items.length}</b>` : ""}
      <span style="opacity:.6">${items.length > 1 ? `${ctx.fmt(items[0].tick) || ""} – ${ctx.fmt(items[items.length - 1].tick) || ""}` : (ctx.fmt(items[0].tick) || "")}${who ? ` · raised by ${who}` : ""}</span></div>`;
    const triggers = items.filter(x => x.trigger).slice(-6).reverse();
    const why = triggers.length ? `<div style="font-size:.85em;margin:2px 0 4px 10px">${triggers.map(x =>
      `<div><span style="opacity:.6">${ctx.fmt(x.tick) || ""}</span> ${ctx.esc(x.trigger)}</div>`).join("")}</div>`
      : (items.length > 1 ? `<div style="font-size:.8em;opacity:.6;margin-left:10px">Nothing recorded about what brought it up (logged before triggers were kept).</div>` : "");
    return head + (items.length >= 3 ? frequencyChart(items.map(x => x.tick), ctx) : "") + why;
  }).join("");
}

function frequencyChart(ticks, ctx) {
  const ts = ticks.filter(t => t != null).sort((a, b) => a - b);
  if (ts.length < 2) return "";
  const span = ts[ts.length - 1] - ts[0];
  const bucket = span > 2 * 86400 ? 86400 : 3600;                    // daily over more than two days, else hourly
  const start = Math.floor(ts[0] / bucket) * bucket, n = Math.floor((ts[ts.length - 1] - start) / bucket) + 1;
  const counts = new Array(n).fill(0);
  for (const t of ts) counts[Math.floor((t - start) / bucket)]++;
  const W = 560, H = 90, L = 28, R = 8, T = 8, B = 18, max = Math.max(...counts);
  const x = i => L + (n === 1 ? 0.5 : i / (n - 1)) * (W - L - R), y = v => T + (1 - v / max) * (H - T - B);
  const pts = counts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:rgba(255,255,255,0.03);margin:2px 0">
    <polygon points="${x(0).toFixed(1)},${y(0)} ${pts.join(" ")} ${x(n - 1).toFixed(1)},${y(0)}" fill="#d29922" opacity=".18"/>
    <polyline points="${pts.join(" ")}" fill="none" stroke="#d29922" stroke-width="1.5"/>
    <text x="${L - 4}" y="${y(max) + 8}" fill="#aaa" font-size="10" text-anchor="end">${max}</text>
    <text x="${L - 4}" y="${y(0)}" fill="#aaa" font-size="10" text-anchor="end">0</text>
    <text x="${L}" y="${H - 4}" fill="#aaa" font-size="10">${ctx.esc(ctx.fmt(start) || "")}</text>
    <text x="${W - R}" y="${H - 4}" fill="#aaa" font-size="10" text-anchor="end">per ${bucket === 86400 ? "day" : "hour"}</text>
  </svg>`;
}

// ---- Standing ----------------------------------------------------------------------------------------------------------

export function renderStandingTab(c, ctx) {
  const el = document.getElementById("viewerStandingTab");
  if (!el) return;
  const tick = ctx.tick();
  const people = Object.entries(c.relationships || {})
    .filter(([id]) => ctx.isCharacter(id))
    .map(([id, rel]) => ({ id, rel, standing: standingOf(rel), f: frustrationOf(rel, tick), ini: rel.initiative || {} }))
    .sort((a, b) => a.standing - b.standing);
  if (!people.length) {
    el.innerHTML = ctx.section("Standing (0)", ctx.empty("No relationships yet."));
    return;
  }
  const rows = people.map(p => {
    const open = (c.issue_log || []).filter(i => ["open", "reopened"].includes(i.status) && (i.involved_parties || []).includes(p.id)).length;
    const bits = [];
    if (p.f.intensity >= 10) bits.push(`${word(p.f.intensity)} ${Math.round(p.f.intensity)}`);
    if (p.f.score >= 15) bits.push(`frustration ${Math.round(p.f.score)}`);
    if ((p.ini.avoidance || 0) >= 40) bits.push("avoiding");
    if ((p.ini.repair_desire || 0) >= 40) bits.push("wants to mend it");
    return `<div class="viewerCard viewerCardClickable" data-standing-id="${ctx.esc(p.id)}" style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <span>${ctx.esc(ctx.name(p.id))}${open ? ` <span style="color:#f85149;font-size:.85em">${open} open</span>` : ""}
        <div style="font-size:.8em;opacity:.6">${ctx.esc(standingLabel(p.standing))}</div></span>
      <span style="text-align:right"><b style="color:${standingColor(p.standing)}">${Math.round(p.standing)}</b>
        ${bits.length ? `<div style="opacity:.75;font-size:.8em">${ctx.esc(bits.join(" · "))}</div>` : ""}</span>
    </div>`;
  }).join("");
  el.innerHTML = ctx.section(`Standing with ${people.length} people (worst first)`, rows);
}

function historyChart(log, ctx) {
  const pts = (log || []).filter(e => e.tick != null);
  if (pts.length < 2) return `<div style="opacity:.6">Not enough history yet -- a point is added each day and whenever something happens.</div>`;
  const W = 560, H = 180, L = 36, R = 8, T = 10, B = 22;
  const t0 = pts[0].tick, t1 = pts[pts.length - 1].tick || t0 + 1;
  const x = t => L + (t - t0) / Math.max(1, t1 - t0) * (W - L - R);
  const y = v => T + (1 - (v + 100) / 200) * (H - T - B);
  const y100 = v => T + (1 - v / 100) * (H - T - B);
  const line = (key, Y) => pts.map((p, i) => `${i ? "L" : "M"}${x(p.tick).toFixed(1)},${Y(p[key] || 0).toFixed(1)}`).join(" ");
  const marks = pts.filter(p => p.cause).map(p =>
    `<circle cx="${x(p.tick).toFixed(1)}" cy="${y(p.standing).toFixed(1)}" r="3" fill="#d29922"><title>${ctx.esc(p.cause)} (${ctx.fmt(p.tick) || ""})</title></circle>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:rgba(255,255,255,0.03)">
    <line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="#555" stroke-dasharray="3 3"/>
    <text x="${L - 4}" y="${y(100) + 8}" fill="#aaa" font-size="10" text-anchor="end">100</text>
    <text x="${L - 4}" y="${y(0) + 3}" fill="#aaa" font-size="10" text-anchor="end">0</text>
    <text x="${L - 4}" y="${y(-100)}" fill="#aaa" font-size="10" text-anchor="end">-100</text>
    <path d="${line("frustration", y100)}" fill="none" stroke="#d29922" stroke-width="1" opacity=".8"/>
    <path d="${line("agitation", y100)}" fill="none" stroke="#f85149" stroke-width="1" opacity=".7"/>
    <path d="${line("standing", y)}" fill="none" stroke="#58a6ff" stroke-width="1.6"/>
    ${marks}
    <text x="${L}" y="${H - 6}" fill="#aaa" font-size="10">${ctx.esc(ctx.fmt(t0) || "")}</text>
    <text x="${W - R}" y="${H - 6}" fill="#aaa" font-size="10" text-anchor="end">now</text>
  </svg>
  <div style="font-size:11px;opacity:.8;margin-top:4px"><span style="color:#58a6ff">—</span> standing (-100..100) &nbsp;
    <span style="color:#d29922">—</span> frustration &nbsp; <span style="color:#f85149">—</span> how worked up (0–100) &nbsp;
    <span style="color:#d29922">●</span> something happened (hover)</div>`;
}

export function openStandingModal(c, otherId, ctx) {
  const rel = (c.relationships || {})[otherId] || {};
  const tick = ctx.tick();
  const s = standingOf(rel);
  const f = frustrationOf(rel, tick);
  const ini = rel.initiative || {};
  ctx.modal(`${c.name} about ${ctx.name(otherId)}`, (body) => {
    const row = (k, v) => `<div class="eventModalRow"><div class="eventModalRowMeta">${ctx.esc(k)}</div><div>${ctx.esc(String(v))}</div></div>`;
    let html = `<div class="viewerSectionTitle">How ${ctx.esc(c.name.split(" ")[0])} regards them</div>`;
    html += row("Standing", `${Math.round(s)} -- ${standingLabel(s)}${rel.standing ? ` (${Math.round((rel.standing.confidence || 0) * 100)}% settled)` : ""}`);
    html += row("Right now", `${word(f.intensity)} (${Math.round(f.intensity)})`);
    html += row("Frustration built up", Math.round(f.score));
    const byIssue = Object.keys((rel.frustration || {}).issues || {}).map(iid => {
      const fi = frustrationOf(rel, tick, iid);
      const iss = (c.issue_log || []).find(i => i.id === iid);
      return fi.score >= 1 ? `${iss ? iss.subject : iid}: ${Math.round(fi.score)}` : null;
    }).filter(Boolean);
    if (byIssue.length) html += row("... about", byIssue.join("; "));
    if (rel.initiative) {
      html += row("Reaching out", `willing ${Math.round(ini.willingness || 0)} · invested ${Math.round(ini.investment || 0)} · wants to mend ${Math.round(ini.repair_desire || 0)} · avoiding ${Math.round(ini.avoidance || 0)}`);
      const resp = (ini.recent_responses || []).slice(-5).map(r => pretty(r.outcome));
      if (resp.length) html += row("How they've responded lately", resp.join(", "));
    }
    const feel = ["trust", "friendship", "respect", "warmth", "resentment", "hostility", "fear", "attraction"]
      .filter(k => rel[k]).map(k => `${k} ${Math.round(rel[k])}`);
    if (feel.length) html += row("Feelings", feel.join(" · "));
    if (rel.state) html += row("Relationship", rel.state);

    const out = [];
    for (const i of (c.issue_log || []).filter(i => ["open", "reopened", "dormant"].includes(i.status) && (i.involved_parties || []).includes(otherId)))
      out.push([i.created_at, `issue (${i.status}): ${i.subject} -- ${pretty(i.category)}`]);
    const grudge = (c.grudges || {})[otherId];
    if (grudge && grudge.status === "open")
      out.push([grudge.created, `grudge: ${grudge.origin?.text || grudge.origin?.kind || "held"}`]);
    const rift = (c.rifts || {})[otherId];
    if (rift && ["open", "away", "moving_out"].includes(rift.status))
      out.push([rift.since, `rift over ${(rift.topics || []).slice(-1)[0] || "it"}: ${pretty(rift.status)}, ${rift.attempts || 0} tries`]);
    for (const e of ((c.implicit_expectations || {})[otherId] || []))
      out.push([e.since, `expects them to ${e.expectation} (never agreed)`]);
    out.sort((a, b) => (b[0] || 0) - (a[0] || 0));
    html += `<div class="viewerSectionTitle" style="margin-top:12px">Outstanding</div>` + (out.map(([t, txt]) =>
      `<div style="margin-bottom:4px"><span style="opacity:.6">${ctx.fmt(t) || ""}</span> ${ctx.esc(txt)}</div>`).join("")
      || `<div style="opacity:.6">Nothing outstanding.</div>`);

    html += `<div class="viewerSectionTitle" style="margin-top:12px">Over time</div>` + historyChart(rel.standing_log, ctx);
    const happened = (rel.standing_log || []).filter(e => e.cause).slice().reverse().slice(0, 30);
    html += happened.map(e =>
      `<div style="margin-bottom:3px"><span style="opacity:.6">${ctx.fmt(e.tick) || ""}</span> ${ctx.esc(e.cause)}
        <span style="opacity:.55">→ ${Math.round(e.standing)}${e.frustration ? `, frustration ${Math.round(e.frustration)}` : ""}${e.agitation ? `, worked up ${Math.round(e.agitation)}` : ""}</span></div>`).join("");
    body.innerHTML = html;
  });
}
