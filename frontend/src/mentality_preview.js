// mentality_preview.html's script -- a one-off developer testing tool
// (systems/mentality.py Phase F). Loads real belief_templates from the
// live definitions, lets you pick a combination, and calls
// POST /admin/preview_mentality to see the compiled principles/
// mentality/opinions -- a pure preview, nothing is persisted.

let definitions = null;

// Mirrors backend/systems/schema_defaults.py::EXCLUSIVE_BELIEF_CATEGORIES --
// a real character can hold at most one belief in each of these categories
// (character_gen.py::_random_beliefs() at generation, peer_influence.py::
// _make_room_for_belief() at runtime). The preview tool enforces the same
// rule client-side so it can never preview a combination no real character
// could ever actually hold.
const EXCLUSIVE_BELIEF_CATEGORIES = ["religion", "ideology"];

async function loadDefinitions() {
  const res = await fetch("/api/editor/definitions?sim_id=default");
  definitions = await res.json();
}

function renderBeliefList() {
  const beliefTemplates = definitions.belief_templates || {};
  const byCategory = {};
  for (const [id, tmpl] of Object.entries(beliefTemplates)) {
    const cat = tmpl.category || "other";
    (byCategory[cat] = byCategory[cat] || []).push([id, tmpl]);
  }

  const list = document.getElementById("beliefList");
  list.innerHTML = "";
  const catOrder = ["religion", "ideology", "metaphysical", "conspiracy", "destiny", "prejudice", "other"];
  for (const cat of catOrder) {
    const entries = byCategory[cat];
    if (!entries || !entries.length) continue;
    const heading = document.createElement("div");
    heading.className = "beliefCategory";
    heading.textContent = cat + (EXCLUSIVE_BELIEF_CATEGORIES.includes(cat) ? " (pick at most one)" : "");
    list.appendChild(heading);
    for (const [id, tmpl] of entries) {
      const row = document.createElement("div");
      row.className = "beliefRow";
      row.innerHTML = `
        <input type="checkbox" id="belief_${id}" value="${id}" data-category="${cat}">
        <label for="belief_${id}">
          <div class="beliefName">${tmpl.name || id}</div>
          <div class="beliefIntensity">intensity ${(tmpl.intensity ?? 0).toFixed(2)} -- ${(tmpl.tags || []).join(", ")}</div>
        </label>
      `;
      list.appendChild(row);
    }
  }

  // Delegated listener: checking a belief in an exclusive category
  // unchecks any other currently-checked belief in that SAME category --
  // same "new pick evicts the old one" behavior as a real conversion.
  list.addEventListener("change", (e) => {
    const box = e.target;
    if (box.tagName !== "INPUT" || !box.checked) return;
    const cat = box.dataset.category;
    if (!EXCLUSIVE_BELIEF_CATEGORIES.includes(cat)) return;
    list.querySelectorAll(`input[data-category="${cat}"]`).forEach((other) => {
      if (other !== box) other.checked = false;
    });
  });
}

function selectedBeliefs() {
  return Array.from(document.querySelectorAll("#beliefList input[type=checkbox]:checked")).map(el => el.value);
}

// Phase H.5: society-category chips (max 3, client-side enforced),
// a trait multi-select, and a reasoning-lens 3-way selector -- all
// threaded straight into POST /admin/preview_mentality's payload.
const MAX_CATEGORIES = 3;
let selectedCategories = [];
let selectedTraits = [];

function renderCategoryChips() {
  const categories = definitions.society_categories || {};
  const container = document.getElementById("categoryChips");
  container.innerHTML = "";
  for (const [id, tmpl] of Object.entries(categories)) {
    const chip = document.createElement("div");
    const isSelected = selectedCategories.includes(id);
    chip.className = "pickChip" + (isSelected ? " selected" : "")
      + (!isSelected && selectedCategories.length >= MAX_CATEGORIES ? " disabled" : "");
    chip.textContent = tmpl.name || id;
    chip.dataset.id = id;
    chip.addEventListener("click", () => {
      if (isSelected) {
        selectedCategories = selectedCategories.filter(c => c !== id);
      } else if (selectedCategories.length < MAX_CATEGORIES) {
        selectedCategories.push(id);
      } else {
        return;
      }
      renderCategoryChips();
    });
    container.appendChild(chip);
  }
  document.getElementById("categoryHint").textContent =
    `${selectedCategories.length}/${MAX_CATEGORIES} selected`;
}

function renderTraitChips() {
  const traits = definitions.trait_templates || {};
  const container = document.getElementById("traitChips");
  container.innerHTML = "";
  for (const [id, tmpl] of Object.entries(traits)) {
    if (tmpl.is_cognition_core) continue;
    const chip = document.createElement("div");
    const isSelected = selectedTraits.includes(id);
    chip.className = "pickChip" + (isSelected ? " selected" : "");
    chip.textContent = tmpl.name || id;
    chip.title = tmpl.description || "";
    chip.dataset.id = id;
    chip.addEventListener("click", () => {
      selectedTraits = isSelected
        ? selectedTraits.filter(t => t !== id)
        : [...selectedTraits, id];
      renderTraitChips();
    });
    container.appendChild(chip);
  }
}

// Phase I: a principle side is now {"type": "concept"|"adjective", "id"}
// instead of a flat list of concept ids -- look it up in whichever
// registry its type says (concepts vs. adjectives).
function sideLabel(side, concepts, adjectives) {
  if (!side || !side.id) return "?";
  const registry = side.type === "adjective" ? adjectives : concepts;
  return (registry[side.id] && registry[side.id].name) || side.id;
}

const SHAPE_HINTS = {
  concept_adjective: { tag: "belief", cls: "shapeBelief" },
  adjective_concept: { tag: "prejudice", cls: "shapePrejudice" },
  concept_concept:   { tag: "identity", cls: "shapeIdentity" },
};

function renderResults(data) {
  const panel = document.getElementById("resultsPanel");
  const concepts = data.concepts || {};
  const adjectives = data.adjectives || {};

  const principlesHtml = (data.principles || []).map(p => {
    const left = sideLabel(p.left, concepts, adjectives);
    const right = sideLabel(p.right, concepts, adjectives);
    const hint = SHAPE_HINTS[p.shape] || { tag: p.shape || "", cls: "" };
    return `<div class="principleLine ${hint.cls}">
      ${hint.tag ? `<span class="shapeTag">${hint.tag}</span>` : ""}
      <b>${left}</b><span class="op">${p.op}</span><b>${right}</b>
      <div class="reasoning">${p.reasoning || ""}</div>
    </div>`;
  }).join("") || "<div style='color:#666'>(no principles)</div>";

  const mentality = data.mentality || {};
  const tagsHtml = (mentality.tags || []).map(t => `<span class="tagChip">${t}</span>`).join("") || "<span style='color:#666'>(no shared tags)</span>";

  const opinionRows = Object.entries(data.opinions || {}).map(([topic, o]) => {
    const stance = o.stance || 0;
    const pct = ((stance + 1) / 2) * 100;
    const color = stance > 0.15 ? "#5dade2" : stance < -0.15 ? "#e67e73" : "#888";
    return `<tr>
      <td>${topic}</td>
      <td><span class="stanceBar"><span class="fill" style="left:${pct}%;background:${color};"></span></span>${stance.toFixed(2)}</td>
      <td>${(o.confidence || 0).toFixed(2)}</td>
    </tr>`;
  }).join("");

  const suggestions = mentality.trait_coherence_suggestions || [];
  const suggestionsHtml = suggestions.length
    ? suggestions.map(s => `<div class="suggestionLine">
        <span class="tag ${s.suggestion === "add" ? "add" : "remove"}">${s.suggestion}</span>
        <b>${s.trait}</b> -- ${s.reasoning || ""}
      </div>`).join("")
    : "<div style='color:#666'>(no coherence suggestions -- traits look consistent with this mentality)</div>";

  const categoriesLine = (mentality.society_categories || []).join(", ") || "(none)";
  const lensLine = mentality.reasoning_lens || "(default)";

  panel.innerHTML = `
    <div class="resultSection">
      <h3>Mentality</h3>
      <div id="mentalitySummary">${mentality.summary || "(no summary)"}</div>
      <div id="mentalityTags">${tagsHtml}</div>
      <div style="color:#789;font-size:11px;margin-top:6px;">Categories: ${categoriesLine} -- Lens: ${lensLine}</div>
    </div>
    <div class="resultSection">
      <h3>Principles</h3>
      ${principlesHtml}
    </div>
    <div class="resultSection">
      <h3>Trait Coherence Suggestions</h3>
      ${suggestionsHtml}
    </div>
    <div class="resultSection">
      <h3>Opinions (seeded political stances)</h3>
      <table class="opinionsTable">
        <tr><th>Topic</th><th>Stance (-1..1)</th><th>Confidence</th></tr>
        ${opinionRows}
      </table>
    </div>
  `;
}

async function compile() {
  const held_beliefs = selectedBeliefs();
  if (!held_beliefs.length) {
    document.getElementById("resultsPanel").innerHTML = "<div id='placeholder'>Pick at least one belief first.</div>";
    return;
  }
  const btn = document.getElementById("compileBtn");
  btn.disabled = true;
  document.getElementById("resultsPanel").innerHTML = "<div id='loading'>Compiling (this can take a while if the LLM is slow/unreachable -- a deterministic fallback kicks in either way)...</div>";
  const reasoning_lens = document.getElementById("lensSelect").value || undefined;
  try {
    const res = await fetch("/admin/preview_mentality?sim_id=default", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        held_beliefs,
        society_categories: selectedCategories,
        traits: selectedTraits,
        reasoning_lens,
      }),
    });
    const data = await res.json();
    if (data.error) {
      document.getElementById("resultsPanel").innerHTML = `<div id='placeholder'>Error: ${data.error}</div>`;
      return;
    }
    renderResults(data);
  } catch (e) {
    document.getElementById("resultsPanel").innerHTML = `<div id='placeholder'>Request failed: ${e}</div>`;
  } finally {
    btn.disabled = false;
  }
}

async function init() {
  await loadDefinitions();
  renderBeliefList();
  renderCategoryChips();
  renderTraitChips();
  document.getElementById("compileBtn").addEventListener("click", compile);
}

init();
