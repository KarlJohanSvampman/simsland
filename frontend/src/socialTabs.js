// Inspector "Arguments" and "Standing" tabs.
//   Arguments: c.argument_log (backend/systems/conversation_archive.py) -- every argument the selected character is or
//     was in; a click opens it: what happened, in order, and the conversations filed under it.
//   Standing: one row per person they have a relationship with -- standing and agitation now
//     (backend/systems/feelings.py; the same standing formula as systems/rifts.py); a click opens how they feel about
//     that person, what's outstanding between them (grievances, grudges, rifts, open arguments), and a line of how
//     it changed over time (rel.standing_log).

const AGITATION_DECAY_PER_DAY = 15;      // keep in step with backend/systems/feelings.py
const DAY = 86400;

export function standingOf(rel) {
  rel = rel || {};
  return (rel.friendship || 0) + 0.5 * (rel.trust || 0) + 0.5 * (rel.respect || 0) + 0.3 * (rel.warmth || 0)
    - (rel.resentment || 0) - (rel.hostility || 0);
}

export function agitationOf(rel, tick) {
  const a = (rel || {}).agitation;
  if (!a) return 0;
  return Math.max(0, (a.value || 0) - AGITATION_DECAY_PER_DAY * Math.max(0, (tick - (a.tick || 0)) / DAY));
}

function agitationWord(v) {
  return v >= 80 ? "furious" : v >= 60 ? "angry" : v >= 30 ? "irritated" : "calm";
}

function standingColor(v) {
  return v < -50 ? "#f85149" : v < 0 ? "#d29922" : v < 40 ? "#8b949e" : "#3fb950";
}

// ---- Arguments ---------------------------------------------------------------------------------------------------------

export function renderArgumentsTab(c, ctx) {
  const el = document.getElementById("viewerArgumentsTab");
  if (!el) return;
  const args = [...(c.argument_log || [])].sort((a, b) =>
    (a.status === "open" ? 0 : 1) - (b.status === "open" ? 0 : 1) || (b.opened_tick || 0) - (a.opened_tick || 0));
  if (!args.length) {
    el.innerHTML = ctx.section("Arguments (0)", ctx.empty("No arguments yet."));
    return;
  }
  const cards = args.map(a => {
    const other = a.parties.find(p => p !== c.id);
    const status = a.status === "open"
      ? `<span style="color:#f85149">open</span>` : `<span style="color:#3fb950">resolved</span>`;
    const started = a.initiator ? (a.initiator === c.id ? "you started it" : `${ctx.esc(ctx.name(a.initiator))} started it`) : "";
    return `<div class="viewerCard viewerCardClickable" data-arg-id="${ctx.esc(a.id)}">
      <div>${status} · <b>${ctx.esc(a.subject)}</b> <span style="opacity:.6">(${ctx.esc((a.type || "").replace(/_/g, " "))})</span></div>
      <div style="opacity:.75">with ${ctx.esc(ctx.name(other))} · ${[started, `${(a.conversation_ids || []).length} conversations`,
        `${(a.fight_ids || []).length} fights`].filter(Boolean).join(" · ")}</div>
      <div style="opacity:.55;font-size:.85em">since ${ctx.fmt(a.opened_tick) || "?"}${a.resolved_tick ? ` · resolved ${ctx.fmt(a.resolved_tick)}` : ""}</div>
    </div>`;
  }).join("");
  const open = args.filter(a => a.status === "open").length;
  el.innerHTML = ctx.section(`Arguments (${open} open, ${args.length - open} resolved)`, cards);
}

export function openArgumentModal(c, argId, ctx) {
  const a = (c.argument_log || []).find(x => x.id === argId);
  if (!a) return;
  const other = a.parties.find(p => p !== c.id);
  ctx.modal(`Argument: ${a.subject}`, (body) => {
    const rows = [
      ["Between", a.parties.map(p => ctx.name(p)).join(" and ")],
      ["Kind", (a.type || "").replace(/_/g, " ")],
      ["Started by", a.initiator ? ctx.name(a.initiator) : "?"],
      ["Status", a.status + (a.resolution ? ` -- ${a.resolution}` : "")],
      ["Since", ctx.fmt(a.opened_tick)],
    ];
    body.innerHTML = rows.map(([k, v]) => `<div class="eventModalRow"><div class="eventModalRowMeta">${ctx.esc(k)}</div><div>${ctx.esc(v || "")}</div></div>`).join("");
    const events = [...(a.events || [])].sort((x, y) => (x.tick || 0) - (y.tick || 0));
    body.innerHTML += `<div class="viewerSectionTitle" style="margin-top:12px">What happened</div>` + (events.map(e =>
      `<div style="margin-bottom:4px"><span style="opacity:.6">${ctx.fmt(e.tick) || ""}</span> <b>${ctx.esc(e.what)}</b> ${ctx.esc(e.detail || "")}</div>`).join("")
      || `<div style="opacity:.6">Nothing recorded yet.</div>`);
    const convs = (c.conversation_log || []).filter(e => (a.conversation_ids || []).includes(e.id || e.conv_id))
      .sort((x, y) => (x.ended_tick || 0) - (y.ended_tick || 0));
    body.innerHTML += `<div class="viewerSectionTitle" style="margin-top:12px">Conversations (${convs.length})</div>` + (convs.map(e => {
      const t = e.tags || {};
      return `<div class="viewerCard viewerCardClickable" data-modal-conv="${ctx.esc(e.id || e.conv_id)}">
        <div style="opacity:.6">${ctx.fmt(e.ended_tick) || ""} · ${ctx.esc(ctx.name(e.initiator))} opened with ${ctx.esc((t.opening || "?").replace(/_/g, " "))}</div>
        <div><b>${ctx.esc(t.subject || "")}</b></div>
        ${(e.lines || []).slice(0, 2).map(l => `<div style="opacity:.8"><span style="opacity:.6">${ctx.clock(l.tick)}</span> ${ctx.esc(ctx.name(l.speaker))}: "${ctx.esc(l.utterance)}"</div>`).join("")}
      </div>`;
    }).join("") || `<div style="opacity:.6">None of ${ctx.esc(c.name)}'s logged conversations with ${ctx.esc(ctx.name(other))} are filed here.</div>`);
    body.onclick = (ev) => {
      const card = ev.target.closest("[data-modal-conv]");
      if (!card) return;
      const entry = (c.conversation_log || []).find(e => (e.id || e.conv_id) === card.dataset.modalConv);
      if (entry) ctx.openConversation(entry);
    };
  });
}

// ---- Standing ----------------------------------------------------------------------------------------------------------

export function renderStandingTab(c, ctx) {
  const el = document.getElementById("viewerStandingTab");
  if (!el) return;
  const tick = ctx.tick();
  const people = Object.entries(c.relationships || {})
    .filter(([id]) => ctx.isCharacter(id))
    .map(([id, rel]) => ({ id, rel, standing: standingOf(rel), agitation: agitationOf(rel, tick) }))
    .sort((a, b) => a.standing - b.standing);
  if (!people.length) {
    el.innerHTML = ctx.section("Standing (0)", ctx.empty("No relationships yet."));
    return;
  }
  const rows = people.map(p => {
    const open = (c.argument_log || []).filter(a => a.status === "open" && a.parties.includes(p.id)).length;
    const ag = Math.round(p.agitation);
    return `<div class="viewerCard viewerCardClickable" data-standing-id="${ctx.esc(p.id)}" style="display:flex;justify-content:space-between;align-items:center">
      <span>${ctx.esc(ctx.name(p.id))}${open ? ` <span style="color:#f85149;font-size:.85em">${open} open</span>` : ""}</span>
      <span><b style="color:${standingColor(p.standing)}">${Math.round(p.standing)}</b>
        ${ag ? `<span style="opacity:.75;font-size:.85em"> · ${agitationWord(ag)} ${ag}</span>` : ""}</span>
    </div>`;
  }).join("");
  el.innerHTML = ctx.section(`Standing with ${people.length} people (worst first)`, rows);
}

function historyChart(log, ctx) {
  const pts = (log || []).filter(e => e.tick != null);
  if (pts.length < 2) return `<div style="opacity:.6">Not enough history yet -- a point is added each day and whenever something happens.</div>`;
  const W = 560, H = 180, L = 36, R = 8, T = 10, B = 22;
  const t0 = pts[0].tick, t1 = pts[pts.length - 1].tick || t0 + 1;
  const vals = pts.map(p => p.standing).concat([0, 100, -100]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const x = t => L + (t - t0) / Math.max(1, t1 - t0) * (W - L - R);
  const y = v => T + (1 - (v - lo) / Math.max(1, hi - lo)) * (H - T - B);
  const yA = v => T + (1 - v / 100) * (H - T - B);
  const line = (key, Y) => pts.map((p, i) => `${i ? "L" : "M"}${x(p.tick).toFixed(1)},${Y(p[key] || 0).toFixed(1)}`).join(" ");
  const marks = pts.filter(p => p.cause).map(p =>
    `<circle cx="${x(p.tick).toFixed(1)}" cy="${y(p.standing).toFixed(1)}" r="3" fill="#d29922"><title>${ctx.esc(p.cause)} (${ctx.fmt(p.tick) || ""})</title></circle>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:rgba(255,255,255,0.03)">
    <line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="#555" stroke-dasharray="3 3"/>
    <text x="${L - 4}" y="${y(hi) + 8}" fill="#aaa" font-size="10" text-anchor="end">${Math.round(hi)}</text>
    <text x="${L - 4}" y="${y(lo)}" fill="#aaa" font-size="10" text-anchor="end">${Math.round(lo)}</text>
    <path d="${line("agitation", yA)}" fill="none" stroke="#f85149" stroke-width="1" opacity=".7"/>
    <path d="${line("standing", y)}" fill="none" stroke="#58a6ff" stroke-width="1.6"/>
    ${marks}
    <text x="${L}" y="${H - 6}" fill="#aaa" font-size="10">${ctx.esc(ctx.fmt(t0) || "")}</text>
    <text x="${W - R}" y="${H - 6}" fill="#aaa" font-size="10" text-anchor="end">now</text>
  </svg>
  <div style="font-size:11px;opacity:.8;margin-top:4px"><span style="color:#58a6ff">—</span> standing &nbsp;
    <span style="color:#f85149">—</span> agitation (0–100) &nbsp; <span style="color:#d29922">●</span> something happened (hover)</div>`;
}

export function openStandingModal(c, otherId, ctx) {
  const rel = (c.relationships || {})[otherId] || {};
  const tick = ctx.tick();
  const ag = agitationOf(rel, tick);
  ctx.modal(`${c.name} about ${ctx.name(otherId)}`, (body) => {
    const feel = [
      ["Standing", Math.round(standingOf(rel))],
      ["Agitation", `${Math.round(ag)} (${agitationWord(ag)})`],
      ...["trust", "friendship", "respect", "warmth", "resentment", "hostility", "fear", "attraction"]
        .filter(k => rel[k]).map(k => [k[0].toUpperCase() + k.slice(1), Math.round(rel[k])]),
      ["Relationship", rel.state || ""],
    ];
    body.innerHTML = `<div class="viewerSectionTitle">How ${ctx.esc(c.name)} feels</div>` + feel.map(([k, v]) =>
      `<div class="eventModalRow"><div class="eventModalRowMeta">${ctx.esc(k)}</div><div>${ctx.esc(String(v))}</div></div>`).join("");

    const out = [];
    for (const g of (c.grievances || []).filter(g => g.caused_by === otherId))
      out.push([g.tick, `grievance: ${String(g.event_type).replace(/_/g, " ")} (weight ${Math.round(g.weight || g.severity || 0)})`]);
    const grudge = (c.grudges || {})[otherId];
    if (grudge && grudge.status === "open")
      out.push([grudge.created, `grudge: ${grudge.origin?.text || grudge.origin?.kind || "held"}`]);
    const rift = (c.rifts || {})[otherId];
    if (rift && ["open", "away", "moving_out"].includes(rift.status))
      out.push([rift.since, `rift over ${(rift.topics || []).slice(-1)[0] || "it"}: ${rift.status.replace(/_/g, " ")}, ${rift.attempts || 0} tries`]);
    for (const a of (c.argument_log || []).filter(a => a.status === "open" && a.parties.includes(otherId)))
      out.push([a.opened_tick, `open argument: ${a.subject} (${(a.type || "").replace(/_/g, " ")})`]);
    out.sort((a, b) => (b[0] || 0) - (a[0] || 0));
    body.innerHTML += `<div class="viewerSectionTitle" style="margin-top:12px">Outstanding</div>` + (out.map(([t, txt]) =>
      `<div style="margin-bottom:4px"><span style="opacity:.6">${ctx.fmt(t) || ""}</span> ${ctx.esc(txt)}</div>`).join("")
      || `<div style="opacity:.6">Nothing outstanding.</div>`);

    body.innerHTML += `<div class="viewerSectionTitle" style="margin-top:12px">Over time</div>` + historyChart(rel.standing_log, ctx);
    const happened = (rel.standing_log || []).filter(e => e.cause).slice().reverse().slice(0, 30);
    body.innerHTML += happened.map(e =>
      `<div style="margin-bottom:3px"><span style="opacity:.6">${ctx.fmt(e.tick) || ""}</span> ${ctx.esc(e.cause)}
        <span style="opacity:.55">→ ${Math.round(e.standing)}${e.agitation ? `, agitation ${Math.round(e.agitation)}` : ""}</span></div>`).join("");
  });
}
