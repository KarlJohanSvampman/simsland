import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// =====================================================
// STATE
// =====================================================
// character_templates is a bucket inside the same whole-blob definitions
// object every other editor page (definitions.html/animbank.html/
// meshbank.html) already loads/saves via GET/POST /api/editor/definitions
// -- no new backend endpoint for this round. Round 1 deliberately
// enriches existing character_templates entries with a fuller preset
// shape (name/age/sex/height/weight/traits/physical_traits) rather than
// replacing whatever thinner fields (bone_slots etc.) already exist on
// them -- only the fields this page's tabs manage are touched on save.

let definitions = { character_templates: {}, trait_templates: {}, physical_trait_templates: {}, item_templates: {} };
let meshbank = {};
let currentTemplateId = null;
let working = null;   // in-memory working copy of the open template

const AGE_GROUP_THRESHOLDS = [
  { max: 13, group: "child" },
  { max: 18, group: "teen" },
  { max: 60, group: "adult" },
];
// Mirrors backend/systems/character_gen.py::_age_group() exactly --
// <13 child, <18 teen, <60 adult, else elderly.
function deriveAgeGroup(age) {
  for (const t of AGE_GROUP_THRESHOLDS) {
    if (age < t.max) return t.group;
  }
  return "elderly";
}

// Mirrors backend/systems/clothing.py::CLOTHING_SLOTS's 14 keys exactly.
// Grouped purely for display -- item_templates' own `slot` field (shared
// by category:"clothing" and category:"hair" entries) is the only source
// of truth for which items fill which slot.
const CLOTHING_SLOT_GROUPS = [
  { title: 'Head', slots: ['head', 'hair', 'neck'] },
  { title: 'Torso', slots: ['torso', 'undershirt', 'outerwear'] },
  { title: 'Lower body', slots: ['legs', 'underwear', 'socks', 'feet'] },
  { title: 'Hands / Accessories', slots: ['hands', 'wrist_l', 'wrist_r', 'accessory'] },
];
const CLOTHING_SLOTS = CLOTHING_SLOT_GROUPS.flatMap(g => g.slots);

// Non-clothing item_templates categories plausible as "starting equipment
// a character carries" -- excludes household-placed categories
// (kitchenware/dishware/food/cleaning/etc.) and "clothing"/"hair" (those
// are handled by the Worn slots above, not carried loose in inventory).
const INVENTORY_CATEGORIES = new Set([
  'electronics', 'documents', 'hobby_supplies', 'tools', 'office_supplies',
  'books_media', 'games', 'art_supplies', 'music_instrument', 'misc',
]);

// =====================================================
// UI ELEMENTS
// =====================================================

const templateListEl = document.getElementById('templateList');
const statusBar       = document.getElementById('statusBar');

function setStatus(msg) { statusBar.textContent = msg; }

// =====================================================
// LOAD / SAVE  (same whole-blob contract as definitions.js)
// =====================================================

async function loadDefinitions() {
  try {
    const res = await fetch('/api/editor/definitions?sim_id=default');
    definitions = await res.json();
    definitions.character_templates = definitions.character_templates || {};
  } catch (err) {
    console.warn(err);
    setStatus('Failed to load definitions');
  }
  renderTemplateList();
}

async function loadMeshbank() {
  try {
    const res = await fetch('/api/meshbank');
    meshbank = await res.json();
  } catch (err) {
    console.warn('Meshbank load failed', err);
  }
}

window.saveTemplate = async function () {
  if (!currentTemplateId || !working) {
    setStatus('Nothing to save');
    return;
  }
  definitions.character_templates[currentTemplateId] = working;
  try {
    await fetch('/api/editor/definitions?sim_id=default', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(definitions),
    });
    setStatus('Saved');
  } catch (err) {
    console.error(err);
    setStatus('Save failed');
  }
};

// =====================================================
// TEMPLATE LIST (sidebar)
// =====================================================

function renderTemplateList() {
  templateListEl.innerHTML = '';
  const ids = Object.keys(definitions.character_templates || {}).sort();
  for (const id of ids) {
    const row = document.createElement('div');
    row.className = 'templateRow' + (id === currentTemplateId ? ' active' : '');
    row.textContent = definitions.character_templates[id]?.name || id;
    row.onclick = () => openTemplate(id);
    templateListEl.appendChild(row);
  }
}

function openTemplate(id) {
  currentTemplateId = id;
  // Shallow-clone so edits don't mutate `definitions` until Save --
  // matches definitions.js's textarea-buffers-until-save behavior.
  const raw = definitions.character_templates[id] || {};
  working = {
    ...raw,
    name: raw.name || id,
    age: raw.age ?? 25,
    sex: raw.sex || "male",
    body_features: { ...(raw.body_features || {}) },
    body_composition: { ...(raw.body_composition || {}) },
    traits: [...(raw.traits || [])],
    physical_traits: [...(raw.physical_traits || [])],
    worn: { ...(raw.worn || {}) },
    starting_inventory: [...(raw.starting_inventory || [])],
  };
  if (working.body_features.height_cm == null) working.body_features.height_cm = 170;
  if (working.body_composition.body_fat_level == null) working.body_composition.body_fat_level = 0.35;

  renderTemplateList();
  renderBasicTab();
  renderPersonalityTab();
  renderPhysicalTab();
  renderOutfitTab();
  updatePreview();
  setStatus(`Editing ${id}`);
}

window.createTemplate = function () {
  let id = 'new_character';
  let n = 1;
  while (definitions.character_templates[id]) { id = `new_character_${n++}`; }
  definitions.character_templates[id] = { name: id, age: 25, sex: "male" };
  openTemplate(id);
};

window.deleteTemplate = function () {
  if (!currentTemplateId) return;
  delete definitions.character_templates[currentTemplateId];
  currentTemplateId = null;
  working = null;
  renderTemplateList();
  setStatus('Deleted (not yet saved)');
};

// =====================================================
// TAB SWITCHING  (ported from animbank.js's .sideTab/.hidden pattern)
// =====================================================

document.querySelectorAll('.sideTab').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.sideTab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-basic').classList.toggle('hidden', tab !== 'basic');
    document.getElementById('tab-personality').classList.toggle('hidden', tab !== 'personality');
    document.getElementById('tab-physical').classList.toggle('hidden', tab !== 'physical');
    document.getElementById('tab-outfit').classList.toggle('hidden', tab !== 'outfit');
  });
});

// =====================================================
// MODEL PREVIEW  (same THREE setup pattern as definitions.js)
// =====================================================

const previewScene = new THREE.Scene();
previewScene.background = new THREE.Color(0x1a1e24);

const previewCamera = new THREE.PerspectiveCamera(50, 420 / 350, 0.1, 1000);
previewCamera.position.set(2.2, 2.2, 2.2);

const previewRenderer = new THREE.WebGLRenderer({ antialias: true });
previewRenderer.setSize(420, 350);
document.getElementById('modelPreview').appendChild(previewRenderer.domElement);

previewScene.add(new THREE.AmbientLight(0xffffff, 1.2));
const previewSun = new THREE.DirectionalLight(0xffffff, 2);
previewSun.position.set(5, 10, 5);
previewScene.add(previewSun);
previewScene.add(new THREE.GridHelper(6, 6));

const previewControls = new OrbitControls(previewCamera, previewRenderer.domElement);
previewControls.enableDamping = true;
previewControls.target.set(0, 1, 0);
previewControls.update();

const previewLoader = new GLTFLoader();
let previewModel = null;

function clearPreviewModel() {
  if (previewModel) {
    previewScene.remove(previewModel);
    previewModel = null;
  }
}

function framePreviewCamera(model) {
  // Box3.setFromObject() right after a fresh GLTF load can read a
  // stale/zero-size box if world matrices haven't been recomputed yet,
  // or if a mesh's geometry has never had its own bounding box computed
  // (SkinnedMesh geometry in particular) -- force both before measuring.
  model.updateMatrixWorld(true);
  model.traverse(o => {
    if (o.geometry) {
      if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      if (!o.geometry.boundingSphere) o.geometry.computeBoundingSphere();
    }
  });
  const box = new THREE.Box3().setFromObject(model);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);
  // Box3.setFromObject() reads a zero-size box for at least some
  // skinned character GLBs in this pipeline (root cause not fully
  // isolated -- confirmed not a stale-matrix issue, updateMatrixWorld
  // above didn't change it). Rather than point the camera at empty
  // space (0,0,0-sized box collapses maxDim, but a bare `|| 1`
  // fallback here would silently mask exactly this case), fall back
  // to a fixed human-scale framing centered near the origin, which is
  // where GLTFLoader places a freshly-loaded character.
  if (!isFinite(maxDim) || maxDim < 0.05 || maxDim > 50) {
    previewCamera.position.set(2, 2, 2);
    previewControls.target.set(0, 1, 0);
    previewControls.update();
    return;
  }
  previewCamera.position.set(center.x + maxDim * 1.6, center.y + maxDim, center.z + maxDim * 1.6);
  previewControls.target.copy(center);
  previewControls.update();
}

// Shown when the resolved meshbank key has no registered mesh yet
// (confirmed this round: only adult_male/adult_female/elder_male are
// actually registered -- child has no GLB at all, teen isn't wired in).
// Same "orange wireframe humanoid" idea as definitions.js's
// showPreviewPlaceholder(), rebuilt here rather than imported since
// this page has its own standalone preview scene.
function showPlaceholder(label) {
  clearPreviewModel();
  const geo = new THREE.BoxGeometry(0.7, 1.7, 0.45);
  const mat = new THREE.MeshStandardMaterial({ color: 0xff6600, opacity: 0.45, transparent: true });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: 0xff9900, wireframe: true })));
  mesh.position.set(0, 0.85, 0);
  const grp = new THREE.Group();
  grp.add(mesh);
  previewModel = grp;
  previewScene.add(previewModel);
  framePreviewCamera(previewModel);
  setStatus('⚠ ' + label);
}

// Ported from main.js (~2644-2698): some Mixamo-exported character GLBs
// bake a cm->m scale correction onto BOTH the top-level node and the
// skeleton's own root bone (compounding to ~1% size on the skeleton
// while the mesh only inherits it once), and separately bake an
// erroneous 90°-about-X rotation onto the shared parent, tipping the
// character over. Without this fix a preview-loaded character GLB
// renders as an invisible speck or lying on its side -- this page's
// preview loader is a fresh GLTFLoader with none of main.js's/
// meshbank.js's correction applied otherwise.
function fixMixamoSkeletonQuirks(model) {
  model.traverse(o => {
    if (o.isSkinnedMesh && o.skeleton) o.skeleton.pose();
  });

  model.traverse(o => {
    if (!o.isSkinnedMesh || !o.skeleton || !o.skeleton.bones.length) return;
    const rootBone = o.skeleton.bones.find(b => !b.parent?.isBone);
    if (!rootBone) return;

    const meshScale = new THREE.Vector3();
    o.getWorldScale(meshScale);
    const boneScale = new THREE.Vector3();
    rootBone.getWorldScale(boneScale);
    if (boneScale.x === 0) return;

    const correction = meshScale.x / boneScale.x;
    if (Math.abs(correction - 1) > 0.01) {
      rootBone.scale.multiplyScalar(correction);
      rootBone.updateMatrixWorld(true);
    }
  });

  model.traverse(o => {
    if (!o.isSkinnedMesh || !o.skeleton || !o.skeleton.bones.length) return;
    const rootBone = o.skeleton.bones.find(b => !b.parent?.isBone);
    if (!rootBone || !rootBone.parent) return;

    const worldQuat = new THREE.Quaternion();
    rootBone.getWorldQuaternion(worldQuat);
    const angleDeg = 2 * Math.acos(Math.min(1, Math.abs(worldQuat.w))) * 180 / Math.PI;
    if (angleDeg > 5) {
      const parentWorldQuat = new THREE.Quaternion();
      rootBone.parent.getWorldQuaternion(parentWorldQuat);
      rootBone.quaternion.copy(parentWorldQuat.clone().invert());
      rootBone.updateMatrixWorld(true);
    }
  });
}

function updatePreview() {
  if (!working) return;
  const ageGroup = deriveAgeGroup(working.age ?? 25);
  const baseModels = definitions.character_base_models || {};
  const modelKey = working.model || baseModels[working.sex]?.[ageGroup] || `${working.sex}_${ageGroup}_base`;
  const asset = meshbank[modelKey];

  if (!asset?.mesh) {
    showPlaceholder(`No preview available for ${working.sex}/${ageGroup} yet (model key: ${modelKey})`);
    return;
  }

  clearPreviewModel();
  setStatus(`Loading ${modelKey}...`);
  previewLoader.load(asset.mesh, (gltf) => {
    previewModel = gltf.scene;
    fixMixamoSkeletonQuirks(previewModel);
    previewScene.add(previewModel);
    framePreviewCamera(previewModel);
    setStatus(`Preview: ${modelKey}`);
  }, undefined, () => {
    showPlaceholder(`Failed to load ${modelKey}`);
  });
}

(function animatePreview() {
  requestAnimationFrame(animatePreview);
  previewControls.update();
  previewRenderer.render(previewScene, previewCamera);
})();

// =====================================================
// TAB: BASIC PROPERTIES
// =====================================================

const fldName   = document.getElementById('fldName');
const fldAge    = document.getElementById('fldAge');
const fldSex    = document.getElementById('fldSex');
const fldHeight = document.getElementById('fldHeight');
const fldWeight = document.getElementById('fldWeight');
const fldWeightLabel = document.getElementById('fldWeightLabel');
const ageGroupNote = document.getElementById('ageGroupNote');

function weightLabelFor(bodyFat) {
  if (bodyFat >= 0.70) return 'obese';
  if (bodyFat <= 0.15) return 'underweight';
  return 'average';
}

function renderBasicTab() {
  fldName.value = working.name || '';
  fldAge.value = working.age ?? 25;
  fldSex.value = working.sex || 'male';
  fldHeight.value = working.body_features.height_cm;
  fldWeight.value = working.body_composition.body_fat_level;
  fldWeightLabel.textContent = `${working.body_composition.body_fat_level.toFixed(2)} (${weightLabelFor(working.body_composition.body_fat_level)})`;
  ageGroupNote.textContent = `age group: ${deriveAgeGroup(working.age ?? 25)}`;
}

fldName.addEventListener('input', () => { working.name = fldName.value; });
fldAge.addEventListener('input', () => {
  working.age = parseInt(fldAge.value) || 0;
  ageGroupNote.textContent = `age group: ${deriveAgeGroup(working.age)}`;
  updatePreview();
});
fldSex.addEventListener('change', () => { working.sex = fldSex.value; updatePreview(); });
fldHeight.addEventListener('input', () => { working.body_features.height_cm = parseInt(fldHeight.value) || 170; });
fldWeight.addEventListener('input', () => {
  const v = parseFloat(fldWeight.value);
  working.body_composition.body_fat_level = v;
  fldWeightLabel.textContent = `${v.toFixed(2)} (${weightLabelFor(v)})`;
});

// Mirrors character_gen.py::_gen_body_features()'s height distribution
// (gauss 164±7 female / 177±8 male, clamped 140-210) and a plausible
// uniform body-fat range -- this is a creator tool, not the simulation's
// own randomizer, so a simpler uniform spread for weight is fine.
function gaussianRandom(mean, stdev) {
  const u = 1 - Math.random(), v = Math.random();
  return mean + stdev * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

window.randomizeBasic = function () {
  if (!working) return;
  working.age = Math.floor(Math.random() * (90 - 5 + 1)) + 5;
  working.sex = Math.random() < 0.5 ? 'male' : 'female';
  const heightMean = working.sex === 'female' ? 164 : 177;
  const heightStdev = working.sex === 'female' ? 7 : 8;
  working.body_features.height_cm = Math.max(140, Math.min(210, Math.round(gaussianRandom(heightMean, heightStdev))));
  working.body_composition.body_fat_level = Math.round((0.15 + Math.random() * 0.55) * 100) / 100;
  renderBasicTab();
  updatePreview();
};

// =====================================================
// GENERALIZED TRAIT-POOL PICKER
// =====================================================
// Reusable by any tab needing a "searchable pool -> draggable assigned
// list" UI -- Round 1 uses it for Personality Traits and Physical
// Traits; later rounds (hobbies) reuse it as-is. Generalizes
// definitions.js's _traitPool/_sampleTraits/_randomPickTraits
// (definitions.js:284-311) to operate on an in-memory array (this
// page's working template) instead of a JSON textarea buffer.

function poolFromTemplates(templatesDict) {
  return Object.entries(templatesDict || {}).map(([id, t]) => ({
    id,
    label: t.name || t.label || id,
    polarity: t.polarity,   // undefined for the categoryless-polarity trait_templates entries
  }));
}

function sampleIds(pool, count) {
  const shuffled = pool.slice().sort(() => Math.random() - 0.5);
  return shuffled.slice(0, Math.max(0, count)).map(t => t.id);
}

function randomPickIds(pool, count, positive, negative) {
  if (positive && negative) {
    const posCount = Math.ceil(count / 2);
    const negCount = count - posCount;
    return [
      ...sampleIds(pool.filter(t => t.polarity === 'positive'), posCount),
      ...sampleIds(pool.filter(t => t.polarity === 'negative'), negCount),
    ];
  }
  if (positive) return sampleIds(pool.filter(t => t.polarity === 'positive'), count);
  if (negative) return sampleIds(pool.filter(t => t.polarity === 'negative'), count);
  return sampleIds(pool, count);
}

/**
 * Renders a pool-picker into `container`.
 * pool: [{id, label, polarity}]
 * getAssigned/setAssigned: read/write the working template's array field
 * onChange: called after any mutation, to let the caller re-render if needed
 */
function renderPoolPicker(container, pool, getAssigned, setAssigned, onChange) {
  container.innerHTML = '';

  const picker = document.createElement('div');
  picker.className = 'poolPicker';

  // ── Pool column (searchable) ──────────────────────────────
  const poolCol = document.createElement('div');
  poolCol.className = 'poolColumn';
  const poolHeader = document.createElement('h4');
  poolHeader.textContent = 'Available';
  const search = document.createElement('input');
  search.className = 'poolSearch';
  search.type = 'text';
  search.placeholder = 'Search (min 2 chars)...';
  const poolList = document.createElement('div');
  poolList.className = 'poolList';
  poolCol.append(poolHeader, search, poolList);

  // ── Assigned column ────────────────────────────────────────
  const assignedCol = document.createElement('div');
  assignedCol.className = 'poolColumn';
  const assignedHeader = document.createElement('h4');
  assignedHeader.textContent = 'Assigned';
  const assignedList = document.createElement('div');
  assignedList.className = 'assignedList';
  assignedCol.append(assignedHeader, assignedList);

  picker.append(poolCol, assignedCol);
  container.appendChild(picker);

  function chipFor(entry, { removable }) {
    const chip = document.createElement('div');
    chip.className = 'traitChip' + (entry.polarity ? ` ${entry.polarity}` : '');
    chip.draggable = true;
    chip.dataset.id = entry.id;
    chip.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', entry.id);
    });
    const label = document.createElement('span');
    label.className = 'chipLabel';
    label.textContent = entry.label;
    chip.appendChild(label);
    if (removable) {
      const rm = document.createElement('button');
      rm.className = 'chipRemove';
      rm.textContent = '✕';
      rm.onclick = () => {
        setAssigned(getAssigned().filter(id => id !== entry.id));
        renderBoth();
        onChange?.();
      };
      chip.appendChild(rm);
    } else {
      chip.addEventListener('dblclick', () => {
        const assigned = getAssigned();
        if (!assigned.includes(entry.id)) setAssigned([...assigned, entry.id]);
        renderBoth();
        onChange?.();
      });
    }
    return chip;
  }

  function renderBoth() {
    const assignedIds = getAssigned();
    const term = search.value.trim().toLowerCase();
    const filterActive = term.length >= 2;

    poolList.innerHTML = '';
    const visible = pool.filter(e => !assignedIds.includes(e.id) && (!filterActive || e.label.toLowerCase().includes(term)));
    if (!visible.length) {
      const hint = document.createElement('div');
      hint.className = 'emptyHint';
      hint.textContent = filterActive ? 'No matches.' : 'All assigned, or type to search.';
      poolList.appendChild(hint);
    } else {
      for (const entry of visible) poolList.appendChild(chipFor(entry, { removable: false }));
    }

    assignedList.innerHTML = '';
    if (!assignedIds.length) {
      const hint = document.createElement('div');
      hint.className = 'emptyHint';
      hint.textContent = 'Drag or double-click traits here.';
      assignedList.appendChild(hint);
    } else {
      for (const id of assignedIds) {
        const entry = pool.find(p => p.id === id) || { id, label: id };
        assignedList.appendChild(chipFor(entry, { removable: true }));
      }
    }
  }

  search.addEventListener('input', renderBoth);

  assignedList.addEventListener('dragover', (e) => {
    e.preventDefault();
    assignedList.classList.add('dragOver');
  });
  assignedList.addEventListener('dragleave', () => assignedList.classList.remove('dragOver'));
  assignedList.addEventListener('drop', (e) => {
    e.preventDefault();
    assignedList.classList.remove('dragOver');
    const id = e.dataTransfer.getData('text/plain');
    const assigned = getAssigned();
    if (id && !assigned.includes(id)) setAssigned([...assigned, id]);
    renderBoth();
    onChange?.();
  });
  // Dragging an assigned chip back onto the pool list removes it.
  poolList.addEventListener('dragover', (e) => e.preventDefault());
  poolList.addEventListener('drop', (e) => {
    e.preventDefault();
    const id = e.dataTransfer.getData('text/plain');
    if (id) setAssigned(getAssigned().filter(x => x !== id));
    renderBoth();
    onChange?.();
  });

  // ── Randomize row ─────────────────────────────────────────
  const randRow = document.createElement('div');
  randRow.className = 'randomizeRow';

  const countInput = document.createElement('input');
  countInput.type = 'number'; countInput.min = 0; countInput.value = 3;

  const posCb = document.createElement('input'); posCb.type = 'checkbox';
  const posLbl = document.createElement('label'); posLbl.append(posCb, document.createTextNode(' Positive'));
  const negCb = document.createElement('input'); negCb.type = 'checkbox';
  const negLbl = document.createElement('label'); negLbl.append(negCb, document.createTextNode(' Negative'));

  const randBtn = document.createElement('button');
  randBtn.className = 'randomizeBtn';
  randBtn.textContent = '🎲 Randomize';
  randBtn.onclick = () => {
    setAssigned(randomPickIds(pool, parseInt(countInput.value) || 0, posCb.checked, negCb.checked));
    renderBoth();
    onChange?.();
  };

  randRow.append(document.createTextNode('Count:'), countInput, posLbl, negLbl, randBtn);
  container.appendChild(randRow);

  renderBoth();
}

// =====================================================
// TAB: PERSONALITY TRAITS
// =====================================================

function renderPersonalityTab() {
  const container = document.getElementById('personalityPicker');
  const pool = poolFromTemplates(definitions.trait_templates);
  renderPoolPicker(
    container,
    pool,
    () => working.traits,
    (ids) => { working.traits = ids; },
  );
}

// =====================================================
// TAB: PHYSICAL TRAITS
// =====================================================

function renderPhysicalTab() {
  const container = document.getElementById('physicalPicker');
  const pool = poolFromTemplates(definitions.physical_trait_templates);
  renderPoolPicker(
    container,
    pool,
    () => working.physical_traits,
    (ids) => { working.physical_traits = ids; },
  );
}

// =====================================================
// TAB: OUTFIT / EQUIPMENT
// =====================================================
// Two sub-sections: Worn (one dropdown per clothing.py::CLOTHING_SLOTS
// key, modeled on animbank.js's renderStancesPanel dropdown-per-slot
// loop) and Starting Inventory (reuses the generic pool-picker as-is,
// same as Personality/Physical Traits -- it already operates on a flat
// assigned-array field, exactly starting_inventory's shape).
//
// Note: this tab is data-entry only. Clothing has never rendered in 3D
// anywhere in this game (live game or this page's own preview) -- the
// bone-attachment plumbing in main.js reads a different, dead slot
// system (c.equipped + definitions.clothing_templates), not c.worn.
// Wiring that up is a separate visual-rendering project, out of scope
// here; what's assigned on this tab is real (backend-materialized into
// c["worn"]/c["inventory"] at spawn time) but not previewable yet.

function groupItemsBySlot(itemTemplates) {
  const bySlot = {};
  for (const [id, t] of Object.entries(itemTemplates || {})) {
    if (!t.slot) continue;
    (bySlot[t.slot] ||= []).push({ id, label: t.name || id });
  }
  for (const list of Object.values(bySlot)) list.sort((a, b) => a.label.localeCompare(b.label));
  return bySlot;
}

function renderOutfitTab() {
  if (!working) return;

  // ── Worn slots ──────────────────────────────────────────
  const bySlot = groupItemsBySlot(definitions.item_templates);
  const wornContainer = document.getElementById('wornSlots');
  wornContainer.innerHTML = '';

  for (const group of CLOTHING_SLOT_GROUPS) {
    const groupEl = document.createElement('div');
    groupEl.className = 'slotGroup';
    const heading = document.createElement('h5');
    heading.textContent = group.title;
    groupEl.appendChild(heading);

    for (const slot of group.slots) {
      const row = document.createElement('div');
      row.className = 'slotRow';
      const label = document.createElement('label');
      label.textContent = slot;
      const select = document.createElement('select');

      const noneOpt = document.createElement('option');
      noneOpt.value = '';
      noneOpt.textContent = '— None —';
      select.appendChild(noneOpt);

      for (const entry of bySlot[slot] || []) {
        const opt = document.createElement('option');
        opt.value = entry.id;
        opt.textContent = entry.label;
        select.appendChild(opt);
      }
      select.value = working.worn[slot] || '';
      select.addEventListener('change', () => {
        if (select.value) working.worn[slot] = select.value;
        else delete working.worn[slot];
      });

      row.append(label, select);
      groupEl.appendChild(row);
    }
    wornContainer.appendChild(groupEl);
  }

  // ── Starting inventory ──────────────────────────────────
  const invContainer = document.getElementById('inventoryPicker');
  const invPool = Object.entries(definitions.item_templates || {})
    .filter(([, t]) => INVENTORY_CATEGORIES.has(t.category))
    .map(([id, t]) => ({ id, label: t.name || id }));
  renderPoolPicker(
    invContainer,
    invPool,
    () => working.starting_inventory,
    (ids) => { working.starting_inventory = ids; },
  );
}

window.randomizeOutfit = function () {
  if (!working) return;
  const bySlot = groupItemsBySlot(definitions.item_templates);
  const worn = {};
  for (const slot of CLOTHING_SLOTS) {
    const options = bySlot[slot] || [];
    if (options.length && Math.random() < 0.55) {
      worn[slot] = options[Math.floor(Math.random() * options.length)].id;
    }
  }
  working.worn = worn;

  const invPool = Object.entries(definitions.item_templates || {})
    .filter(([, t]) => INVENTORY_CATEGORIES.has(t.category))
    .map(([id]) => id);
  const count = Math.floor(Math.random() * 4); // 0-3
  working.starting_inventory = sampleIds(invPool.map(id => ({ id })), count);

  renderOutfitTab();
};

// =====================================================
// INIT
// =====================================================

(async function init() {
  await Promise.all([loadDefinitions(), loadMeshbank()]);
})();
