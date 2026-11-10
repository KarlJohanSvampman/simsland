// src/personaTab.js -- the inspector's Persona tab: what a director sets by hand on a live character, and the record of
// how their personality has changed (backend: systems/personality_profile.py, api/persona.py).
//
//   traits                  their personality tags (editable; a change here is logged as "set by hand")
//   personality_traits      tags they picked up later from people around them (shown, changed by the sim)
//   speech_quirks           how they talk
//   insecurities            what they are insecure about
//   confidence_sources      what their self-confidence rests on
//   mood_traits             per mood: traits that show only while they are in it
//   trait_log               every change to either trait list: when, what, why
//
// Loaded when the tab opens or the selected character changes -- not on every world update, which would wipe what is
// being typed.

const STYLE = `
.persona { font-size: 12px; line-height: 1.4; }
.persona h4 { margin: 12px 0 4px; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; opacity: .75; }
.persona .hint { opacity: .6; font-size: 11px; margin: 0 0 4px; }
.persona .chips { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; min-height: 24px; }
.persona .chip { background: rgba(255,255,255,.1); border-radius: 999px; padding: 1px 4px 1px 9px; display: inline-flex; gap: 4px; align-items: center; }
.persona .chip.fixed { padding-right: 9px; opacity: .8; }
.persona .chip button { background: none; border: none; color: inherit; cursor: pointer; opacity: .6; padding: 0 3px; font-size: 13px; }
.persona .chip button:hover { opacity: 1; }
.persona input.add { background: transparent; border: 1px dashed rgba(255,255,255,.3); border-radius: 999px; color: inherit; padding: 2px 9px; width: 100%; max-width: 160px; box-sizing: border-box; font: inherit; }
.persona input.add:focus { outline: none; border-color: #58a6ff; }
.persona table { width: 100%; border-collapse: collapse; }
.persona td { padding: 4px 4px; border-bottom: 1px solid rgba(255,255,255,.08); vertical-align: top; }
.persona td.mood { white-space: nowrap; width: 1%; padding-right: 10px; }
.persona tr.now td.mood { color: #58a6ff; font-weight: 600; }
.persona .pos { color: #3fb950; } .persona .neg { color: #f85149; }
.persona .bar { display: flex; gap: 8px; align-items: center; margin: 0 0 4px; position: sticky; top: 0; padding: 6px 0; z-index: 2;
  background: var(--panel-bg, rgba(16,18,24,.97)); }
.persona .moodrow { padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,.08); }
.persona .moodrow.now .name { color: #58a6ff; font-weight: 600; }
.persona .moodrow .name { margin-bottom: 3px; }
.persona .bar button { background: #1f6feb; color: #fff; border: none; border-radius: 6px; padding: 4px 12px; cursor: pointer; font: inherit; }
.persona .bar button:disabled { opacity: .45; cursor: default; }
.persona .bar .msg { opacity: .7; }
.persona .log td { font-size: 11px; }
`;

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

let state = { charId: null, data: null, dirty: false, el: null };

function ensureCss() {
  if (document.getElementById("personaTabCss")) return;
  const st = document.createElement("style");
  st.id = "personaTabCss";
  st.textContent = STYLE;
  document.head.appendChild(st);
}

function chipEditor(key, tags, placeholder) {
  const chips = (tags || []).map((t, i) =>
    `<span class="chip">${esc(t)}<button data-del="${esc(key)}" data-i="${i}" title="Remove">×</button></span>`).join("");
  return `<div class="chips">${chips}<input class="add" data-add="${esc(key)}" placeholder="${esc(placeholder)}"></div>`;
}

function get(key) {
  const d = state.data;
  if (key.startsWith("mood:")) return (d.mood_traits[key.slice(5)] ||= []);
  return (d[key] ||= []);
}

function render() {
  const d = state.data, el = state.el;
  if (!el || !d) return;
  const moods = d.moods || [];
  const logRows = (d.trait_log || []).slice().reverse().map((e) => `
    <tr><td style="white-space:nowrap">${esc(e.when || ("tick " + e.tick))}</td>
        <td>${(e.added || []).map((t) => `<span class="pos">+${esc(t)}</span>`).join(" ")}
            ${(e.removed || []).map((t) => `<span class="neg">−${esc(t)}</span>`).join(" ")}
            ${e.list === "personality_traits" ? '<span class="hint">(picked up)</span>' : ""}</td>
        <td>${esc(e.why)}</td></tr>`).join("");
  el.innerHTML = `<div class="persona">
    <div class="bar"><button data-save ${state.dirty ? "" : "disabled"}>Save</button>
      <span class="msg">${state.dirty ? "unsaved changes" : ""}</span></div>

    <h4>Personality traits</h4>
    ${chipEditor("traits", d.traits, "add a trait…")}
    ${(d.personality_traits || []).length ? `<p class="hint" style="margin-top:6px">Picked up later (changed by the simulation):</p>
      <div class="chips">${d.personality_traits.map((t) => `<span class="chip fixed">${esc(t)}</span>`).join("")}</div>` : ""}

    <h4>Speech quirks</h4>
    <p class="hint">How they talk -- "says 'like' a lot", "never swears", "trails off mid-sentence".</p>
    ${chipEditor("speech_quirks", d.speech_quirks, "add a quirk…")}

    <h4>Insecurities</h4>
    <p class="hint">What they are insecure about.</p>
    ${chipEditor("insecurities", d.insecurities, "add an insecurity…")}

    <h4>Self-confidence rests on</h4>
    ${chipEditor("confidence_sources", d.confidence_sources, "add a source…")}

    <h4>Traits that show in a mood</h4>
    <p class="hint">Shown to the model only while they are in that mood${d.current_mood ? ` (now: ${esc(d.current_mood)})` : ""}.</p>
    ${moods.map((m) => `
      <div class="moodrow ${m.id === d.current_mood ? "now" : ""}" title="${esc(m.description || "")}">
        <div class="name"><span class="${m.polarity === "positive" ? "pos" : m.polarity === "negative" ? "neg" : ""}">●</span> ${esc(m.name)}${m.id === d.current_mood ? " (now)" : ""}</div>
        ${chipEditor("mood:" + m.id, (d.mood_traits || {})[m.id], "add a trait…")}</div>`).join("")}

    <h4>Trait changes</h4>
    ${logRows ? `<table class="log">${logRows}</table>` : '<p class="hint">No changes recorded yet.</p>'}
  </div>`;
}

async function save() {
  const d = state.data;
  const body = { traits: d.traits, speech_quirks: d.speech_quirks, insecurities: d.insecurities,
                 confidence_sources: d.confidence_sources, mood_traits: d.mood_traits };
  const msg = state.el.querySelector(".msg");
  if (msg) msg.textContent = "saving…";
  try {
    const r = await fetch(`/api/characters/${encodeURIComponent(state.charId)}/persona`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const out = await r.json();
    if (!out.ok) throw new Error(out.error || r.statusText);
    state.data = out;
    state.dirty = false;
    render();
  } catch (err) {
    if (msg) msg.textContent = `couldn't save: ${err.message}`;
  }
}

function wire(el) {
  if (el.dataset.personaWired) return;
  el.dataset.personaWired = "1";
  el.addEventListener("click", (e) => {
    const del = e.target.closest("[data-del]");
    if (del) {
      get(del.dataset.del).splice(Number(del.dataset.i), 1);
      state.dirty = true;
      render();
      return;
    }
    if (e.target.closest("[data-save]")) save();
  });
  el.addEventListener("keydown", (e) => {
    const inp = e.target.closest("input[data-add]");
    if (!inp || e.key !== "Enter") return;
    const v = inp.value.trim();
    if (!v) return;
    const list = get(inp.dataset.add);
    if (!list.includes(v)) list.push(v);
    state.dirty = true;
    const key = inp.dataset.add;
    render();
    state.el.querySelector(`input[data-add="${window.CSS?.escape ? window.CSS.escape(key) : key}"]`)?.focus();
  });
}

// Show charId's persona in el. Re-fetches only for a different character (or force), so typing isn't wiped.
export async function showPersona(el, charId, force = false) {
  if (!el) return;
  ensureCss();
  wire(el);
  state.el = el;
  if (!charId) { el.innerHTML = '<p class="hint">Select a character.</p>'; return; }
  if (!force && state.charId === charId && state.data) { render(); return; }
  if (state.dirty && state.charId && state.charId !== charId &&
      !confirm("Leave this character's persona without saving?")) return;
  state = { charId, data: null, dirty: false, el };
  el.innerHTML = '<p class="hint">Loading…</p>';
  try {
    const r = await fetch(`/api/characters/${encodeURIComponent(charId)}/persona`);
    const out = await r.json();
    if (state.charId !== charId) return;                 // another character was selected meanwhile
    if (!out.ok) throw new Error(out.error || r.statusText);
    out.mood_traits ||= {};
    state.data = out;
    render();
  } catch (err) {
    el.innerHTML = `<p class="hint">Couldn't load the persona: ${esc(err.message)}</p>`;
  }
}
