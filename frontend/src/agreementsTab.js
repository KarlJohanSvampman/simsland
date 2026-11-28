// =========================================================
// SOCIAL TAB -- every agreement (social contract) a character is in, or everyone's: what was agreed, between whom,
// whether it's in force and how it's going. Click one for the details window: what was agreed, who's involved, and for
// each of them their responsibilities, what's expected of them right now (the expectations on their schedule), their
// rights and any breaches. Data: backend/api/social.py (/admin/social/...), fetched when the tab is shown, when another
// character is selected, and at most every REFRESH_MS while it stays open.
// =========================================================

const REFRESH_MS = 10000;
let _scope = "mine";            // "mine" | "all"
let _lastFetch = { id: null, scope: null, at: 0 };
let _rows = [];

const STATE_COLOR = { active: "#3fb950", accepted: "#3fb950", violated: "#f85149", disputed: "#d29922",
                      renegotiating: "#d29922", proposed: "#8b949e", negotiated: "#8b949e",
                      fulfilled: "#58a6ff", expired: "#8b949e", terminated: "#8b949e" };
const STATUS_COLOR = { kept: "#3fb950", done: "#3fb950", satisfied: "#3fb950", pending: "#d29922",
                       missed: "#f85149", violated: "#f85149", lapsed: "#8b949e", "not due": "#8b949e" };

function badge(text, color, esc) {
  return `<span style="color:${color || "#8b949e"}">${esc(text || "")}</span>`;
}

export async function showSocial(el, charId, ctx, force = false) {
  if (!el || !charId) return;
  const now = Date.now();
  if (!force && _lastFetch.id === charId && _lastFetch.scope === _scope && now - _lastFetch.at < REFRESH_MS) return;
  _lastFetch = { id: charId, scope: _scope, at: now };
  try {
    const r = await fetch(`/admin/social/contracts?sim_id=default&char_id=${encodeURIComponent(charId)}&scope=${_scope}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    _rows = (await r.json()).contracts || [];
  } catch (err) {
    el.innerHTML = ctx.section("Social", ctx.empty(`Couldn't load the agreements (${ctx.esc(String(err.message || err))}).`));
    return;
  }
  render(el, charId, ctx);
}

function render(el, charId, ctx) {
  const esc = ctx.esc;
  const toggle = `
    <div class="plansViewToggle">
      <button class="plansViewBtn${_scope === "mine" ? " active" : ""}" data-social-scope="mine">This person</button>
      <button class="plansViewBtn${_scope === "all" ? " active" : ""}" data-social-scope="all">Everyone</button>
    </div>`;
  const card = (k) => `
    <div class="viewerCard viewerCardClickable" data-contract-id="${esc(k.id)}">
      <div>${badge(k.state_text, STATE_COLOR[k.state], esc)} · <b>${esc(k.title)}</b></div>
      <div style="opacity:.75">${esc(k.parties.join(", "))} · ${k.terms} term${k.terms === 1 ? "" : "s"}${
        k.breaches ? ` · <span style="color:#f85149">${k.breaches} breach${k.breaches === 1 ? "" : "es"}</span>` : ""}</div>
      ${k.obligations.map(o => `<div style="font-size:.9em;opacity:.85">${esc(o)}</div>`).join("")}
      <div style="opacity:.55;font-size:.85em">made ${esc(k.made || "?")}</div>
    </div>`;
  const live = _rows.filter(k => k.in_force), ended = _rows.filter(k => !k.in_force);
  let html = toggle;
  if (!_rows.length) {
    html += ctx.section("Agreements", ctx.empty(_scope === "all" ? "No agreements anywhere yet." : "No agreements with anyone yet."));
  } else {
    html += ctx.section(`In force (${live.length})`, live.length ? live.map(card).join("") : ctx.empty("None in force."));
    if (ended.length) html += ctx.section(`Ended (${ended.length})`, ended.map(card).join(""));
  }
  el.innerHTML = html;
  el.querySelectorAll("[data-social-scope]").forEach(b => b.addEventListener("click", () => {
    _scope = b.dataset.socialScope;
    showSocial(el, charId, ctx, true);
  }));
  el.querySelectorAll("[data-contract-id]").forEach(c => c.addEventListener("click", () => openContractModal(c.dataset.contractId, ctx)));
}

export async function openContractModal(id, ctx) {
  const esc = ctx.esc;
  let k;
  try {
    const r = await fetch(`/admin/social/contract/${encodeURIComponent(id)}?sim_id=default`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    k = await r.json();
  } catch (err) {
    ctx.modal("Agreement", (body) => { body.innerHTML = ctx.empty(`Couldn't load it (${esc(String(err.message || err))}).`); });
    return;
  }
  const row = (label, value) => value == null || value === "" ? "" :
    `<div class="eventModalRow"><div class="eventModalRowMeta">${esc(label)}</div><div>${value}</div></div>`;
  const h = (t) => `<div style="margin:12px 0 4px;font-weight:600">${esc(t)}</div>`;
  const list = (items, empty) => items.length
    ? `<ul style="margin:2px 0 6px 18px;padding:0">${items.map(i => `<li style="margin:2px 0">${i}</li>`).join("")}</ul>`
    : `<div style="opacity:.55;margin:2px 0 6px">${esc(empty)}</div>`;

  const terms = (k.terms_detail || []).map(t => {
    const bits = [t.kind === "rule" ? "rule" : t.cadence === "once" ? "once" : t.cadence, t.when].filter(Boolean).join(", ");
    const record = t.kind === "rule" ? "" : ` · kept ${t.kept}× · missed ${t.missed}×${t.last_kept ? ` · last ${esc(t.last_kept)}` : ""}`;
    const extra = [t.frequency && `how often: ${esc(t.frequency)}`, t.deadline && `by: ${esc(t.deadline)}`,
                   (t.conditions || []).length && `if: ${esc(t.conditions.join("; "))}`,
                   (t.consequences || []).length && `otherwise: ${esc(t.consequences.join("; "))}`].filter(Boolean);
    return `<b>${esc(t.responsible_name)}</b> ${esc(t.obligation)} <span style="opacity:.6">(${esc(bits)})</span>
      — ${badge(t.status, STATUS_COLOR[t.status], esc)}<span style="opacity:.6;font-size:.9em">${record}</span>
      ${extra.length ? `<div style="opacity:.65;font-size:.85em">${extra.join(" · ")}</div>` : ""}`;
  });

  const people = (k.people || []).map(p => {
    const resp = (p.responsibilities || []).map(t =>
      `${esc(t.obligation)}${t.when ? ` <span style="opacity:.6">(${esc(t.when)})</span>` : ""} — ${badge(t.status, STATUS_COLOR[t.status], esc)}${
        t.kind !== "rule" ? ` <span style="opacity:.6;font-size:.9em">kept ${t.kept}×, missed ${t.missed}×</span>` : ""}${
        (t.consequences || []).length ? `<div style="opacity:.65;font-size:.85em">if not: ${esc(t.consequences.join("; "))}</div>` : ""}`);
    const exp = (p.expectations || []).map(e =>
      `${esc(e.label)} — ${badge(e.status, STATUS_COLOR[e.status], esc)}
       <div style="opacity:.7;font-size:.85em">${[e.agreed_time && `on the schedule ${esc(e.agreed_time)}`,
         e.window && `this time: ${esc(e.window)}`, e.cadence && esc(e.cadence),
         e.streak ? `streak ${e.streak}` : "", e.missed_count ? `missed ${e.missed_count}×` : "",
         e.frustration ? `frustration ${Math.round(e.frustration * 100)}%` : ""].filter(Boolean).join(" · ")}</div>`);
    const breaches = (p.breaches || []).map(b =>
      `${esc(b.what || "broke it")} <span style="opacity:.6">(${esc(b.when || "?")}${b.seen_by ? `, seen by ${esc(b.seen_by)}` : ""}${b.disputed ? ", disputed" : ""})</span>`);
    return `<div class="viewerCard" style="margin:8px 0">
      <div style="font-size:1.05em"><b>${esc(p.name)}</b> <span style="opacity:.6">(${esc(p.role)})</span></div>
      ${h("Responsibilities")}${list(resp, "Nothing to do under this agreement.")}
      ${h("Expected of them now")}${list(exp, "No expectation on their schedule from this.")}
      ${h("Rights")}${list((p.rights || []).map(esc), "None.")}
      ${breaches.length ? h("Breaches") + list(breaches, "") : ""}
    </div>`;
  });

  ctx.modal(`Agreement: ${k.title}`, (body) => {
    body.innerHTML =
      row("State", badge(k.state_text, STATE_COLOR[k.state], esc)) +
      row("Between", esc((k.parties || []).join(", "))) +
      row("In charge", k.authority ? esc(k.authority) : null) +
      row("Kind", k.type ? esc(String(k.type).replace(/_/g, " ")) : null) +
      row("Made", esc(k.made || "?")) +
      row("Expires", k.expires ? esc(k.expires) : null) +
      row("About", k.description ? esc(k.description) : null) +
      row("Conditions", (k.conditions || []).length ? esc(k.conditions.join("; ")) : null) +
      row("Revisions", k.revisions ? String(k.revisions) : null) +
      row("Compliance", k.compliance != null ? `${Math.round(Number(k.compliance) * 100)}%` : null) +
      h("What was agreed") + list(terms, "No terms.") +
      h("Who's involved") + people.join("");
  });
}
