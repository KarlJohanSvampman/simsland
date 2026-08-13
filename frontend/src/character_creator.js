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

let definitions = { character_templates: {}, trait_templates: {}, physical_trait_templates: {}, item_templates: {}, job_templates: {}, school_templates: {}, hobby_templates: {} };
let meshbank = {};
let animBank = { _templates: {} };
let households = [];   // live world["households"], not definitions.json -- see loadHouseholds()
let availableBuildings = []; // live world["buildings"] with no owner_household_id -- see loadAvailableBuildings()
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

// Mirrors backend/systems/character_gen.py's _EDU_RANK vocabulary (post
// Round-4 fix) -- the same vocabulary job_templates.degree_required and
// school_templates.education_level already use. "none"/"none_completed"
// omitted from the picker -- _attained_education() never produces them.
const EDUCATION_LEVELS = [
  'preschool', 'primary', 'middle_school', 'high_school', 'trade_school',
  'certificate', 'associate', 'bachelor', 'master', 'doctorate', 'professional',
];

const RETIRED_JOB = {
  id: 'retired', title: 'Retired', industry: null, average_salary: 0,
  hourly_wage: 0, salary: 0, work_mode: 'none', income_class: 'Low',
};

// Mirrors _assign_job()'s dict-building exactly (character_gen.py:173-187).
function jobDictFromTemplate(jid, t) {
  return {
    id: jid,
    title: t.name || jid,
    industry: t.industry ?? null,
    income_class: t.income_class ?? null,
    average_salary: t.average_salary ?? 0,
    hourly_wage: t.hourly_wage ?? 0,
    salary: t.salary ?? 0,
    work_mode: t.work_mode || 'On-site',
    physical_demand: t.physical_demand ?? 50,
    social_demand: t.social_demand ?? 50,
    hazard_level: t.hazard_level || 'Low',
    illegal: t.illegal || false,
    adult_industry: t.adult_industry || false,
  };
}

// Mirrors frontend/src/main.js's ANIM_LAYERS keys exactly (47 total),
// grouped the same way as that file's own comment sections. This is the
// complete, authoritative vocabulary of animation_state keys the game
// ever sets on a character -- locomotion AND interaction keys share one
// flat namespace there, so no separate reconciliation against the
// backend's INTERACTION_ANIMATIONS is needed.
const ANIM_STATE_GROUPS = [
  { title: 'Locomotion', keys: ['idle', 'walk', 'run', 'crouch_idle', 'crouch_walk'] },
  { title: 'Standing interactions', keys: [
    'talk', 'eat', 'cook', 'work', 'phone', 'phone_screen', 'examine', 'search',
    'wipe', 'mop', 'scrub', 'wash_dishes', 'window_wipe', 'clean_generic',
    'pick_up', 'put_down', 'throw', 'smash',
  ] },
  { title: 'Item stack', keys: ['add_to_stack', 'put_down_stack', 'search_stack', 'take_from_stack'] },
  { title: 'Carry', keys: ['carry_idle', 'carry_walk'] },
  { title: 'Movable props', keys: ['drag_idle', 'drag_move', 'start_dragging', 'let_go', 'pushing'] },
  { title: 'Seated', keys: [
    'sit_idle', 'sit_watch', 'sit_eat', 'sit_talk', 'sit_phone', 'sit_phone_screen', 'sit_work', 'read',
  ] },
  { title: 'Lying / sleep', keys: ['lie_idle', 'sleep_idle', 'wake_up'] },
  { title: 'Transitions', keys: ['stand_up', 'shower'] },
];

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

async function loadAnimBank() {
  try {
    const res = await fetch('/api/animbank');
    animBank = await res.json();
    animBank._templates = animBank._templates || {};
    animBank._character_overrides = animBank._character_overrides || {};
  } catch (err) {
    console.warn('Animbank load failed', err);
  }
}

// Households are live world objects, not definitions.json data -- no
// design-time household_templates bucket exists (nothing to author
// ahead of time, only assign to what already exists in the running sim).
async function loadHouseholds() {
  try {
    const res = await fetch('/api/household/list?sim_id=default');
    const data = await res.json();
    households = data.ok ? data.households : [];
  } catch (err) {
    console.warn('Household list load failed', err);
    households = [];
  }
}

async function loadAvailableBuildings() {
  try {
    const res = await fetch('/api/household/available_buildings?sim_id=default');
    const data = await res.json();
    availableBuildings = data.ok ? data.buildings : [];
  } catch (err) {
    console.warn('Available buildings load failed', err);
    availableBuildings = [];
  }
}

// household.py's admin_detail endpoint resolves the household's assigned
// building(s) -- used here just to read the first one's address, since a
// household's own /list entry doesn't carry building_ids.
async function fetchHouseholdAddress(householdId) {
  if (!householdId) return null;
  try {
    const res = await fetch(`/api/household/${householdId}/admin?sim_id=default`);
    const data = await res.json();
    if (!data.ok) return null;
    const buildings = data.household.buildings || [];
    return buildings[0] || null;
  } catch (err) {
    console.warn('Household admin fetch failed', err);
    return null;
  }
}

window.saveTemplate = async function () {
  if (!currentTemplateId || !working) {
    setStatus('Nothing to save');
    return;
  }
  // _animOverrides is an in-memory-only convenience field on `working`
  // (read by renderAnimMappingTab) -- it must NOT be written into
  // definitions.json's character_templates, since that data belongs
  // solely in animbank.json's _character_overrides bucket below.
  const { _animOverrides, ...templateData } = working;
  definitions.character_templates[currentTemplateId] = templateData;
  // Animation overrides live in animbank.json's _character_overrides
  // bucket (keyed by this same template id), not in definitions.json --
  // see main.js's resolveCharacterOverrideMap(). Prune empty entries so
  // untouched templates don't accumulate stray {} keys.
  if (_animOverrides && Object.keys(_animOverrides).length) {
    animBank._character_overrides[currentTemplateId] = _animOverrides;
  } else {
    delete animBank._character_overrides[currentTemplateId];
  }
  try {
    await Promise.all([
      fetch('/api/editor/definitions?sim_id=default', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definitions),
      }),
      fetch('/api/animbank', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(animBank),
      }),
    ]);
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
    first_name: raw.first_name || '',
    family_name: raw.family_name || '',
    ssn: raw.ssn || '',
    age: raw.age ?? 25,
    sex: raw.sex || "male",
    body_features: { ...(raw.body_features || {}) },
    body_composition: { ...(raw.body_composition || {}) },
    // Preserved verbatim except the locomotion speed fields this tab
    // edits directly -- instance also carries health_state/immune_score/
    // current_hairstyle/etc. (see api/editor.py::_spawn_character_locked,
    // which copies this whole dict onto a newly spawned character).
    instance: { ...(raw.instance || {}) },
    traits: [...(raw.traits || [])],
    physical_traits: [...(raw.physical_traits || [])],
    hobbies: [...(raw.hobbies || [])],
    worn: { ...(raw.worn || {}) },
    starting_inventory: [...(raw.starting_inventory || [])],
    // Animation overrides live in animbank.json, not definitions.json --
    // see saveTemplate()/main.js's resolveCharacterOverrideMap(). Deep
    // clone the per-key {lower, upper} objects so edits don't mutate
    // animBank until Save.
    _animOverrides: Object.fromEntries(
      Object.entries(animBank._character_overrides?.[id] || {}).map(([k, v]) => [k, { ...v }])
    ),
    bio: raw.bio || '',
    job: raw.job ? { ...raw.job } : null,
    education: raw.education || '',
    current_school: raw.current_school || '',
    work_history: (raw.work_history || []).map(e => ({ ...e })),
    legal: { status: 'free', jail_until: null, record: [], ...(raw.legal || {}) },
    household_id: raw.household_id || '',
  };
  working.legal.record = working.legal.record.map(e => ({ ...e }));
  if (working.body_features.height_cm == null) working.body_features.height_cm = 170;
  if (working.body_composition.body_fat_level == null) working.body_composition.body_fat_level = 0.35;

  renderTemplateList();
  renderBasicTab();
  renderPersonalityTab();
  renderPhysicalTab();
  renderOutfitTab();
  renderAnimMappingTab();
  renderJobsTab();
  renderLegalTab();
  renderHobbiesTab();
  renderHouseholdTab();
  renderDebugTab();
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

window.generateRelative = async function () {
  if (!currentTemplateId) {
    setStatus('Select a template first');
    return;
  }
  const relationType = document.getElementById('fldRelationType').value;
  setStatus('Generating relative...');
  try {
    const res = await fetch(`/api/editor/character_templates/${currentTemplateId}/generate_relative?sim_id=default`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sim_id: 'default', relation_type: relationType }),
    });
    const data = await res.json();
    if (!data.ok) {
      setStatus('Generate relative failed');
      return;
    }
    definitions.character_templates[data.template_id] = data.template;
    renderTemplateList();
    openTemplate(data.template_id);
    setStatus(`Generated ${data.template_id} (not yet saved)`);
  } catch (err) {
    console.error(err);
    setStatus('Generate relative failed');
  }
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
    document.getElementById('tab-animations').classList.toggle('hidden', tab !== 'animations');
    document.getElementById('tab-jobs').classList.toggle('hidden', tab !== 'jobs');
    document.getElementById('tab-legal').classList.toggle('hidden', tab !== 'legal');
    document.getElementById('tab-hobbies').classList.toggle('hidden', tab !== 'hobbies');
    document.getElementById('tab-household').classList.toggle('hidden', tab !== 'household');
    document.getElementById('tab-llmconfig').classList.toggle('hidden', tab !== 'llmconfig');
    document.getElementById('tab-debugterminal').classList.toggle('hidden', tab !== 'debugterminal');
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

// Mirrors character_gen.py's model resolution exactly -- also used by
// the Animation Mapping tab to scope which animbank templates are
// compatible with this character's body mesh (see resolveWorkingModelKey).
function resolveWorkingModelKey() {
  const ageGroup = deriveAgeGroup(working.age ?? 25);
  const baseModels = definitions.character_base_models || {};
  return working.model || baseModels[working.sex]?.[ageGroup] || `${working.sex}_${ageGroup}_base`;
}

function updatePreview() {
  if (!working) return;
  const modelKey = resolveWorkingModelKey();
  const asset = meshbank[modelKey];

  if (!asset?.mesh) {
    showPlaceholder(`No preview available for ${working.sex}/${deriveAgeGroup(working.age ?? 25)} yet (model key: ${modelKey})`);
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

const fldFirstName = document.getElementById('fldFirstName');
const fldLastName  = document.getElementById('fldLastName');
const fldSsn       = document.getElementById('fldSsn');
const fldAge    = document.getElementById('fldAge');
const fldSex    = document.getElementById('fldSex');
const fldHeight = document.getElementById('fldHeight');
const fldWeight = document.getElementById('fldWeight');
const fldWeightLabel = document.getElementById('fldWeightLabel');
const ageGroupNote = document.getElementById('ageGroupNote');
const fldBio    = document.getElementById('fldBio');

const fldWalkSpeed   = document.getElementById('fldWalkSpeed');
const fldJogSpeed    = document.getElementById('fldJogSpeed');
const fldSprintSpeed = document.getElementById('fldSprintSpeed');
const fldCrawlSpeed  = document.getElementById('fldCrawlSpeed');
const fldSneakSpeed  = document.getElementById('fldSneakSpeed');

// Tiles/tick -- must match backend/systems/movement.py's DEFAULT_*_SPEED
// constants and schema_defaults.py::ensure_character_defaults().
const LOCOMOTION_SPEED_DEFAULTS = {
  walk_speed: 0.05, jog_speed: 0.09, sprint_speed: 0.18,
  crawl_speed: 0.02, sneak_speed: 0.025,
};

function weightLabelFor(bodyFat) {
  if (bodyFat >= 0.70) return 'obese';
  if (bodyFat <= 0.15) return 'underweight';
  return 'average';
}

function renderBasicTab() {
  fldFirstName.value = working.first_name || '';
  fldLastName.value  = working.family_name || '';
  fldSsn.value = working.ssn || '';
  fldAge.value = working.age ?? 25;
  fldSex.value = working.sex || 'male';
  fldHeight.value = working.body_features.height_cm;
  fldWeight.value = working.body_composition.body_fat_level;
  fldWeightLabel.textContent = `${working.body_composition.body_fat_level.toFixed(2)} (${weightLabelFor(working.body_composition.body_fat_level)})`;
  ageGroupNote.textContent = `age group: ${deriveAgeGroup(working.age ?? 25)}`;
  fldBio.value = working.bio || '';

  fldWalkSpeed.value   = working.instance.walk_speed   ?? LOCOMOTION_SPEED_DEFAULTS.walk_speed;
  fldJogSpeed.value    = working.instance.jog_speed    ?? LOCOMOTION_SPEED_DEFAULTS.jog_speed;
  fldSprintSpeed.value = working.instance.sprint_speed ?? LOCOMOTION_SPEED_DEFAULTS.sprint_speed;
  fldCrawlSpeed.value  = working.instance.crawl_speed  ?? LOCOMOTION_SPEED_DEFAULTS.crawl_speed;
  fldSneakSpeed.value  = working.instance.sneak_speed  ?? LOCOMOTION_SPEED_DEFAULTS.sneak_speed;
}

function syncFullName() {
  working.name = [working.first_name, working.family_name].filter(Boolean).join(' ');
}
fldFirstName.addEventListener('input', () => { working.first_name = fldFirstName.value; syncFullName(); });
fldLastName.addEventListener('input', () => { working.family_name = fldLastName.value; syncFullName(); });
fldSsn.addEventListener('input', () => { working.ssn = fldSsn.value; });
fldBio.addEventListener('input', () => { working.bio = fldBio.value; });
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

function bindSpeedField(input, key) {
  input.addEventListener('input', () => {
    const v = parseFloat(input.value);
    working.instance[key] = Number.isFinite(v) && v >= 0 ? v : LOCOMOTION_SPEED_DEFAULTS[key];
  });
}
bindSpeedField(fldWalkSpeed,   'walk_speed');
bindSpeedField(fldJogSpeed,    'jog_speed');
bindSpeedField(fldSprintSpeed, 'sprint_speed');
bindSpeedField(fldCrawlSpeed,  'crawl_speed');
bindSpeedField(fldSneakSpeed,  'sneak_speed');

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
    raw: t,                 // full template -- descriptions/learn_chance/modifiers/conditions
  }));
}

// Color coding for cognitive_modifiers/belief_modifiers/trait_modifiers,
// per the cognition/trait-learning plan: 0% = incompatible (grey), 100% =
// automatic (white), positive <100 = boost (green), negative = penalty
// (red).
function _modifierColor(modifier) {
  if (modifier === 0) return '#888';
  if (modifier === 100) return '#eee';
  if (modifier > 0) return '#6c6';
  return '#f66';
}

function _modifierBadges(entry) {
  const raw = entry.raw;
  if (!raw) return null;
  const mods = [
    ...(raw.cognitive_modifiers || []).map(m => ({ target: m.trait, modifier: m.modifier })),
    ...(raw.belief_modifiers || []).map(m => ({ target: m.belief, modifier: m.modifier })),
    ...(raw.trait_modifiers || []).map(m => ({ target: m.trait, modifier: m.modifier })),
  ];
  if (!mods.length) return null;

  const wrap = document.createElement('div');
  wrap.className = 'chipModifiers';
  for (const m of mods) {
    const badge = document.createElement('span');
    badge.className = 'modBadge';
    badge.style.color = _modifierColor(m.modifier);
    badge.style.borderColor = _modifierColor(m.modifier);
    const sign = m.modifier > 0 && m.modifier !== 100 ? '+' : '';
    badge.textContent = `${m.target} ${sign}${m.modifier}%`;
    wrap.appendChild(badge);
  }
  return wrap;
}

function _chipTooltip(entry) {
  const raw = entry.raw;
  if (!raw) return entry.label;
  const desc = (raw.descriptions && raw.descriptions.balanced) || raw.description;
  return desc ? `${entry.label}\n${desc}` : entry.label;
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
    chip.title = _chipTooltip(entry);
    chip.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', entry.id);
    });
    const label = document.createElement('span');
    label.className = 'chipLabel';
    label.textContent = entry.icon ? `${entry.icon} ${entry.label}` : entry.label;
    chip.appendChild(label);
    const badges = _modifierBadges(entry);
    if (badges) chip.appendChild(badges);
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
// TAB: HOBBIES
// =====================================================
// hobby_templates is schema-clean (name + category, no polarity) --
// renderPoolPicker needs no changes for this, exactly as anticipated
// by its own header comment above.

function renderHobbiesTab() {
  const container = document.getElementById('hobbyPicker');
  const pool = poolFromTemplates(definitions.hobby_templates);
  renderPoolPicker(
    container,
    pool,
    () => working.hobbies,
    (ids) => { working.hobbies = ids; },
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

// Category-level icon (disease-schema-overhaul round's icon_templates
// registry, extended to item_templates/prop_templates) -- every template
// carries an `icon` key resolving into definitions.icon_templates.
function iconEmoji(tmpl) {
  return definitions.icon_templates?.[tmpl?.icon]?.emoji || '';
}

function groupItemsBySlot(itemTemplates) {
  const bySlot = {};
  for (const [id, t] of Object.entries(itemTemplates || {})) {
    if (!t.slot) continue;
    const icon = iconEmoji(t);
    (bySlot[t.slot] ||= []).push({ id, label: t.name || id, icon });
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
        opt.textContent = entry.icon ? `${entry.icon} ${entry.label}` : entry.label;
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
    .map(([id, t]) => ({ id, label: t.name || id, icon: iconEmoji(t) }));
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
// TAB: ANIMATION MAPPING
// =====================================================
// Per-character-TEMPLATE override, one tier more specific than the
// existing per-shared-model locomotion mapping (animbank.html's Stances
// panel). Stored in animbank.json's _character_overrides bucket (see
// saveTemplate()), resolved at runtime by main.js's
// resolveCharacterOverrideMap(). Each of the 47 ANIM_STATE_GROUPS keys
// gets independent lower/upper dropdowns so a character can override
// just the upper body (e.g. a unique "eat" clip) without losing the
// correct seated lower-body pose that ANIM_LAYERS/the model default
// would otherwise supply.

function animTemplateOptionsHTML(templates, selected) {
  let html = `<option value=""${selected ? '' : ' selected'}>— Use default —</option>`;
  for (const t of templates) {
    const sel = t.id === selected ? ' selected' : '';
    html += `<option value="${t.id}"${sel}>${t.name || t.id}</option>`;
  }
  return html;
}

function renderAnimMappingTab() {
  if (!working) return;
  const modelKey = resolveWorkingModelKey();
  const templates = Object.values(animBank._templates || {})
    .filter(t => t.source_key === modelKey)
    .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));

  const listEl = document.getElementById('animMapList');
  const searchEl = document.getElementById('animSearch');

  function renderRows() {
    const term = searchEl.value.trim().toLowerCase();
    const filterActive = term.length >= 2;

    listEl.innerHTML = '';
    for (const group of ANIM_STATE_GROUPS) {
      const visibleKeys = group.keys.filter(k => !filterActive || k.includes(term));
      if (!visibleKeys.length) continue;

      const titleEl = document.createElement('div');
      titleEl.className = 'animMapGroupTitle';
      titleEl.textContent = group.title;
      listEl.appendChild(titleEl);

      for (const key of visibleKeys) {
        const row = document.createElement('div');
        row.className = 'animMapRow';

        const keyLabel = document.createElement('div');
        keyLabel.className = 'animMapKey';
        keyLabel.textContent = key;
        row.appendChild(keyLabel);

        for (const slot of ['lower', 'upper']) {
          const slotWrap = document.createElement('div');
          slotWrap.className = 'animMapSlot';
          const label = document.createElement('label');
          label.textContent = slot;
          const select = document.createElement('select');
          select.innerHTML = animTemplateOptionsHTML(templates, working._animOverrides[key]?.[slot] || '');
          select.addEventListener('change', () => {
            const entry = working._animOverrides[key] || {};
            if (select.value) entry[slot] = select.value;
            else delete entry[slot];
            if (Object.keys(entry).length) working._animOverrides[key] = entry;
            else delete working._animOverrides[key];
          });
          slotWrap.append(label, select);
          row.appendChild(slotWrap);
        }

        listEl.appendChild(row);
      }
    }

    if (!listEl.children.length) {
      const hint = document.createElement('div');
      hint.className = 'emptyHint';
      hint.textContent = 'No matches.';
      listEl.appendChild(hint);
    }
  }

  searchEl.oninput = renderRows;
  renderRows();
}

// =====================================================
// GENERALIZED OBJECT-LIST EDITOR (work history / criminal record)
// =====================================================
// Modeled on animbank.js's renderChainList/renderNotifyList pattern: one
// row per list entry with a field-defined input/select per property,
// wired to mutate the entry in place; a remove button per row; an "add"
// button that pushes a fresh blank entry. No existing precedent for this
// in character_creator.js/definitions.js/social_debug.js -- new, but
// deliberately generic so both callers (work_history, legal.record)
// share one implementation.
//
// fieldDefs: [{key, label, type: 'text'|'number'|'select', options?, placeholder?}]
function renderObjectListEditor(container, list, fieldDefs, addLabel) {
  container.innerHTML = '';

  function renderRows() {
    container.innerHTML = '';
    if (!list.length) {
      const hint = document.createElement('div');
      hint.className = 'emptyHint';
      hint.textContent = 'None yet.';
      container.appendChild(hint);
    }
    list.forEach((entry, i) => {
      const row = document.createElement('div');
      row.className = 'objListRow';
      for (const def of fieldDefs) {
        let field;
        if (def.type === 'select') {
          field = document.createElement('select');
          for (const opt of def.options) {
            const o = document.createElement('option');
            o.value = opt.value;
            o.textContent = opt.label;
            if (entry[def.key] === opt.value) o.selected = true;
            field.appendChild(o);
          }
        } else {
          field = document.createElement('input');
          field.type = def.type === 'number' ? 'number' : 'text';
          field.placeholder = def.placeholder || def.label;
          field.value = entry[def.key] ?? '';
          field.style.width = def.type === 'number' ? '80px' : '150px';
        }
        field.addEventListener(def.type === 'select' ? 'change' : 'input', () => {
          entry[def.key] = def.type === 'number' ? (parseInt(field.value) || 0) : field.value;
        });
        row.appendChild(field);
      }
      const rm = document.createElement('button');
      rm.className = 'objListRemove';
      rm.textContent = '✕';
      rm.onclick = () => { list.splice(i, 1); renderRows(); };
      row.appendChild(rm);
      container.appendChild(row);
    });

    const addBtn = document.createElement('button');
    addBtn.textContent = '+ ' + (addLabel || 'Add');
    addBtn.onclick = () => {
      const blank = {};
      for (const def of fieldDefs) blank[def.key] = def.type === 'number' ? 0 : (def.options?.[0]?.value ?? '');
      list.push(blank);
      renderRows();
    };
    container.appendChild(addBtn);
  }

  renderRows();
}

// =====================================================
// TAB: JOBS / EDUCATION
// =====================================================

const fldJob = document.getElementById('fldJob');
const jobSearch = document.getElementById('jobSearch');
const jobInfoNote = document.getElementById('jobInfoNote');
const fldEducation = document.getElementById('fldEducation');
const fldSchool = document.getElementById('fldSchool');

function jobOptionsHTML(term) {
  const filterActive = term.length >= 2;
  let html = '<option value="">— None / Unemployed —</option>';
  html += '<option value="retired">Retired</option>';
  const entries = Object.entries(definitions.job_templates || {})
    .filter(([id, t]) => !filterActive || (t.name || id).toLowerCase().includes(term) || (t.industry || '').toLowerCase().includes(term))
    .sort((a, b) => (a[1].name || a[0]).localeCompare(b[1].name || b[0]));
  for (const [id, t] of entries) {
    html += `<option value="${id}">${t.name || id}</option>`;
  }
  return html;
}

function renderJobInfoNote() {
  const j = working.job;
  jobInfoNote.textContent = j
    ? `${j.industry || '—'} · $${j.hourly_wage || 0}/hr · ${j.income_class || '—'}`
    : 'No current job.';
}

function renderJobsTab() {
  if (!working) return;
  fldJob.innerHTML = jobOptionsHTML(jobSearch.value.trim().toLowerCase());
  fldJob.value = working.job?.id || '';
  renderJobInfoNote();

  fldEducation.innerHTML = '<option value="">— Unset (random) —</option>' +
    EDUCATION_LEVELS.map(e => `<option value="${e}">${e.replace(/_/g, ' ')}</option>`).join('');
  fldEducation.value = working.education || '';

  fldSchool.innerHTML = '<option value="">— None —</option>' +
    Object.entries(definitions.school_templates || {})
      .map(([id, t]) => `<option value="${id}">${t.name || id}</option>`).join('');
  fldSchool.value = working.current_school || '';

  renderObjectListEditor(document.getElementById('workHistoryList'), working.work_history, [
    { key: 'title', label: 'Title', type: 'text', placeholder: 'Title' },
    { key: 'industry', label: 'Industry', type: 'text', placeholder: 'Industry' },
    { key: 'years', label: 'Years', type: 'number' },
    { key: 'reason_left', label: 'Reason left', type: 'select', options: [
      { value: 'quit', label: 'Quit' },
      { value: 'laid_off', label: 'Laid off' },
      { value: 'career_change', label: 'Career change' },
    ] },
  ], 'Add past job');
}

jobSearch.addEventListener('input', () => {
  fldJob.innerHTML = jobOptionsHTML(jobSearch.value.trim().toLowerCase());
  fldJob.value = working.job?.id || '';
});
fldJob.addEventListener('change', () => {
  if (!fldJob.value) working.job = null;
  else if (fldJob.value === 'retired') working.job = { ...RETIRED_JOB };
  else working.job = jobDictFromTemplate(fldJob.value, definitions.job_templates[fldJob.value] || {});
  renderJobInfoNote();
});
fldEducation.addEventListener('change', () => { working.education = fldEducation.value; });
fldSchool.addEventListener('change', () => { working.current_school = fldSchool.value; });

window.randomizeJob = function () {
  if (!working) return;
  const ageGroup = deriveAgeGroup(working.age ?? 25);
  working.education = EDUCATION_LEVELS[Math.floor(Math.random() * EDUCATION_LEVELS.length)];
  if (ageGroup === 'child') {
    working.job = null;
  } else if (ageGroup === 'elderly' && Math.random() < 0.6) {
    working.job = { ...RETIRED_JOB };
  } else {
    const eduRank = EDUCATION_LEVELS.indexOf(working.education);
    // A job with a degree_required not in EDUCATION_LEVELS (e.g. "none" or
    // missing) resolves to indexOf() === -1, which is always <= eduRank --
    // i.e. requires-nothing jobs are always eligible, same as _assign_job()'s
    // _EDU_RANK.get(..., 0) default-to-lowest-rank behavior.
    let candidates = Object.entries(definitions.job_templates || {})
      .filter(([, t]) => EDUCATION_LEVELS.indexOf(t.degree_required) <= eduRank);
    if (ageGroup === 'teen') {
      candidates = candidates.filter(([, t]) => t.service_job || ['none', 'high_school', undefined].includes(t.degree_required));
    }
    if (candidates.length) {
      const [id, t] = candidates[Math.floor(Math.random() * candidates.length)];
      working.job = jobDictFromTemplate(id, t);
    } else {
      working.job = null;
    }
  }
  renderJobsTab();
};

// =====================================================
// TAB: CRIMINAL RECORD
// =====================================================

const fldLegalStatus = document.getElementById('fldLegalStatus');
const fldJailUntil = document.getElementById('fldJailUntil');

function renderLegalTab() {
  if (!working) return;
  fldLegalStatus.value = working.legal.status;
  fldJailUntil.value = working.legal.jail_until ?? '';

  renderObjectListEditor(document.getElementById('legalRecordList'), working.legal.record, [
    { key: 'crime', label: 'Crime', type: 'text', placeholder: 'Crime' },
    { key: 'tick', label: 'Tick', type: 'number' },
  ], 'Add record entry');
}

fldLegalStatus.addEventListener('change', () => { working.legal.status = fldLegalStatus.value; });
fldJailUntil.addEventListener('input', () => {
  working.legal.jail_until = fldJailUntil.value === '' ? null : parseInt(fldJailUntil.value) || 0;
});

// =====================================================
// TAB: HOUSEHOLD
// =====================================================
// Unlike every other tab, this one's picker reflects LIVE world state
// (world["households"]) fetched via loadHouseholds() -- there's no
// design-time household_templates bucket to author ahead of time, only
// existing households in the running default simulation to assign to.

const fldHousehold = document.getElementById('fldHousehold');
const fldAvailableBuildings = document.getElementById('fldAvailableBuildings');
const householdAddressNote = document.getElementById('householdAddressNote');
const householdAddressRow = document.getElementById('householdAddressRow');
const fldHouseAddress = document.getElementById('fldHouseAddress');
const btnSaveAddress = document.getElementById('btnSaveAddress');

// The building currently shown in the address row -- set by
// renderHouseholdAddress(), read by saveHouseAddress() below.
let currentHouseholdBuildingId = null;

async function renderHouseholdTab() {
  if (!working) return;
  fldHousehold.innerHTML = '<option value="">— None —</option>' +
    households.map(h => `<option value="${h.id}">${h.name || '(unnamed)'} (${h.member_count} member${h.member_count === 1 ? '' : 's'})</option>`).join('');
  fldHousehold.value = working.household_id || '';

  fldAvailableBuildings.innerHTML = availableBuildings.map(b =>
    `<option value="${b.id}">${b.address || `(${b.template}, unaddressed)`}</option>`
  ).join('') || '<option value="">— None available —</option>';

  await renderHouseholdAddress();
}

async function renderHouseholdAddress() {
  const building = await fetchHouseholdAddress(working?.household_id);
  currentHouseholdBuildingId = building?.id || null;
  if (!building) {
    householdAddressNote.style.display = '';
    householdAddressNote.textContent = working?.household_id
      ? 'No building assigned to this household yet.'
      : 'Select a household to see its address.';
    householdAddressRow.style.display = 'none';
    btnSaveAddress.style.display = 'none';
    return;
  }
  householdAddressNote.style.display = 'none';
  householdAddressRow.style.display = '';
  btnSaveAddress.style.display = '';
  fldHouseAddress.value = building.address || '';
}

fldHousehold.addEventListener('change', () => {
  working.household_id = fldHousehold.value;
  renderHouseholdAddress();
});

window.assignBuilding = async function () {
  if (!working?.household_id) {
    setStatus('Select a household first');
    return;
  }
  const buildingId = fldAvailableBuildings.value;
  if (!buildingId) {
    setStatus('No available building selected');
    return;
  }
  try {
    const res = await fetch('/api/household/assign_building?sim_id=default', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ household_id: working.household_id, building_id: buildingId }),
    });
    const data = await res.json();
    if (data.ok) {
      await loadAvailableBuildings();
      await loadHouseholds();
      renderHouseholdTab();
      setStatus(`Building assigned (${data.building.address || data.building.id})`);
    } else {
      setStatus('Assign building failed: ' + (data.error || 'unknown error'));
    }
  } catch (err) {
    console.error(err);
    setStatus('Assign building failed');
  }
};

window.saveHouseAddress = async function () {
  if (!currentHouseholdBuildingId) {
    setStatus('No building to address');
    return;
  }
  try {
    const res = await fetch('/api/household/set_building_address?sim_id=default', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ building_id: currentHouseholdBuildingId, address: fldHouseAddress.value }),
    });
    const data = await res.json();
    if (data.ok) {
      setStatus(`Address saved: ${data.building.address}`);
    } else {
      setStatus('Save address failed: ' + (data.error || 'unknown error'));
    }
  } catch (err) {
    console.error(err);
    setStatus('Save address failed');
  }
};

window.createHousehold = async function () {
  const nameInput = document.getElementById('newHouseholdName');
  const name = nameInput.value.trim();
  try {
    const res = await fetch('/api/household/create?sim_id=default', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name || null }),
    });
    const data = await res.json();
    if (data.ok) {
      await loadHouseholds();
      if (working) working.household_id = data.household.id;
      renderHouseholdTab();
      nameInput.value = '';
      setStatus(`Household "${data.household.name || data.household.id}" created`);
    } else {
      setStatus('Household creation failed: ' + (data.error || 'unknown error'));
    }
  } catch (err) {
    console.error(err);
    setStatus('Household creation failed');
  }
};

// =====================================================
// TAB: DEBUG TERMINAL
// =====================================================
// POST /debug/llm-test (backend/api/debug.py) merges a `character` patch
// onto a fully-defaulted skeleton and a `world` patch onto a skeleton
// world, then runs the REAL build_context() + SYSTEM_PROMPT against it --
// "the format the simulation will send it" per spec, with no live world
// or saved template required. Fully stateless -- no prompt-log/char_id
// concept to wire up, unlike /debug/prompt-send.

const debugCharPatchEl = document.getElementById('debugCharPatch');
const debugWorldPatchEl = document.getElementById('debugWorldPatch');
const debugSystemOverrideEl = document.getElementById('debugSystemOverride');
const debugStatusEl = document.getElementById('debugStatus');
const debugResponseEl = document.getElementById('debugResponse');

function buildDebugCharPatch() {
  return {
    id: 'debug_' + (currentTemplateId || 'preview'),
    name: working.name || 'Debug Sim',
    age: working.age ?? 25,
    sex: working.sex || 'male',
    traits: working.traits || [],
    physical_traits: working.physical_traits || [],
    hobbies: working.hobbies || [],
    occupation: working.job?.title || 'none',
    education: working.education || undefined,
    legal: working.legal || undefined,
  };
}

// Only regenerates the default patch when switching to a genuinely
// different template -- re-opening the same template (or saving it)
// must not clobber a designer's in-progress hand-edits in the textarea.
let debugPatchForTemplate = null;

function renderDebugTab() {
  if (!working) return;
  if (debugPatchForTemplate !== currentTemplateId) {
    debugCharPatchEl.value = JSON.stringify(buildDebugCharPatch(), null, 2);
    debugPatchForTemplate = currentTemplateId;
  }
}

function debugField(title, content, cls) {
  const wrap = document.createElement('div');
  wrap.className = 'debugField';
  const h = document.createElement('h5');
  h.textContent = title;
  const pre = document.createElement('pre');
  if (cls) pre.className = cls;
  pre.textContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
  wrap.append(h, pre);
  return wrap;
}

window.sendDebugPrompt = async function () {
  let character, world;
  try {
    character = JSON.parse(debugCharPatchEl.value || '{}');
  } catch (err) {
    debugStatusEl.textContent = 'Character patch is not valid JSON: ' + err.message;
    return;
  }
  try {
    world = JSON.parse(debugWorldPatchEl.value || '{}');
  } catch (err) {
    debugStatusEl.textContent = 'World patch is not valid JSON: ' + err.message;
    return;
  }

  debugStatusEl.textContent = 'Sending...';
  debugResponseEl.innerHTML = '';

  try {
    const res = await fetch('/debug/llm-test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        character,
        world,
        system_prompt_override: debugSystemOverrideEl.value.trim() || null,
        use_cache: false,
      }),
    });
    const data = await res.json();

    debugStatusEl.textContent = `${data.elapsed_s}s · valid=${data.valid}` +
      (data.parse_error ? ` · ⚠ ${data.parse_error}` : '');

    debugResponseEl.innerHTML = '';
    if (data.context_errors && Object.keys(data.context_errors).length) {
      debugResponseEl.appendChild(debugField('Context Errors', data.context_errors, 'debugError'));
    }
    debugResponseEl.appendChild(debugField('System Prompt', data.system_prompt));
    debugResponseEl.appendChild(debugField('User Prompt (built narrative)', data.user_prompt));
    debugResponseEl.appendChild(debugField('Raw Response', data.raw_response));
    debugResponseEl.appendChild(debugField('Parsed Action', data.parsed_action, data.valid ? 'debugValid' : ''));
  } catch (err) {
    console.error(err);
    debugStatusEl.textContent = 'Send failed: ' + err.message;
  }
};

// =====================================================
// INIT
// =====================================================

(async function init() {
  await Promise.all([loadDefinitions(), loadMeshbank(), loadAnimBank(), loadHouseholds(), loadAvailableBuildings()]);
})();
