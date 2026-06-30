import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// =====================================================
// STATE
// =====================================================

let definitions = {
  prop_templates: {},
  item_templates: {},
  character_templates: {},
  interaction_templates: {},
  activity_templates: {},
  tile_templates: {},
  floorplan_templates: {},
  material_templates: {},
  recipe_templates: {},
  vehicle_templates: {},
  service_templates: {},
  need_templates: {},
  mood_templates: {},
  trait_templates: {},
  job_templates: {},
  company_templates: {}
};

const tabs = [
  "prop_templates",
  "item_templates",
  "character_templates",
  "trait_templates",
  "need_templates",
  "mood_templates",
  "activity_templates",
  "interaction_templates",
  "recipe_templates",
  "service_templates",
  "job_templates",
  "company_templates",
  "vehicle_templates",
  "floorplan_templates",
  "tile_templates",
  "material_templates",
];

let meshbank = {};
let currentTab = 'prop_templates';
let currentTemplateId = null;

// =====================================================
// UI ELEMENTS
// =====================================================

const tabsEl          = document.getElementById('tabs');
const templateListEl  = document.getElementById('templateList');
const jsonEditor      = document.getElementById('jsonEditor');
const editorTitle     = document.getElementById('editorTitle');
const animationList   = document.getElementById('animationList');
const statusBar       = document.getElementById('statusBar');
const assetBrowser    = document.getElementById('assetBrowser');
const assetSearch     = document.getElementById('assetSearch');
const currentModelEl  = document.getElementById('currentModelLabel');

// =====================================================
// THREE PREVIEW  (with OrbitControls, like meshbank)
// =====================================================

const previewScene = new THREE.Scene();
previewScene.background = new THREE.Color(0x1a1e24);

const previewCamera = new THREE.PerspectiveCamera(50, 1, 0.1, 1000);
previewCamera.position.set(3, 3, 3);
previewCamera.lookAt(0, 0, 0);

const previewRenderer = new THREE.WebGLRenderer({ antialias: true });
previewRenderer.setSize(420, 420);

const previewMount = document.getElementById('modelPreview');
previewMount.appendChild(previewRenderer.domElement);

previewScene.add(new THREE.AmbientLight(0xffffff, 1.2));

const previewSun = new THREE.DirectionalLight(0xffffff, 2);
previewSun.position.set(5, 10, 5);
previewScene.add(previewSun);

previewScene.add(new THREE.GridHelper(10, 10));

const previewControls = new OrbitControls(previewCamera, previewRenderer.domElement);
previewControls.enableDamping = true;
previewControls.screenSpacePanning = true;
previewControls.target.set(0, 1, 0);
previewControls.update();

const previewLoader = new GLTFLoader();
const previewTexLoader = new THREE.TextureLoader();

let previewModel = null;
let previewMixer = null;
let previewBones = [];
let previewMesh = null;   // for tile / material previews

// =====================================================
// MODEL RESOLUTION  (meshbank ID → actual mesh path)
// =====================================================

function resolveModelPath(template) {

  const modelRef = template?.model;
  if (!modelRef) return null;

  // Try meshbank ID first
  const asset = meshbank[modelRef];
  if (asset?.mesh) return asset.mesh;

  // Fallback: treat as raw path (backward compat)
  if (modelRef.startsWith('/') || modelRef.includes('.glb')) {
    return modelRef;
  }

  return null;
}

function getMeshbankAsset(modelRef) {
  if (!modelRef) return null;
  return meshbank[modelRef] || null;
}

// =====================================================
// BONE EXTRACTION
// =====================================================

function extractBones(root) {

  const bones = [];

  root.traverse(node => {
    if (node.isBone) {
      bones.push(node.name);
    }
  });

  return bones.sort();
}

// =====================================================
// AUTO FRAME
// =====================================================

function framePreviewCamera(model) {

  const box    = new THREE.Box3().setFromObject(model);
  const size   = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);

  previewCamera.position.set(
    center.x + maxDim * 1.6,
    center.y + maxDim * 1.0,
    center.z + maxDim * 1.6
  );

  previewControls.target.copy(center);
  previewControls.update();
}

// =====================================================
// BONE SLOT EDITOR
// =====================================================

const STANDARD_BONE_SLOTS = [
  "head", "neck", "right_hand", "left_hand",
  "spine", "pelvis", "right_foot", "left_foot"
];

function renderBoneSlotEditor() {

  const container = document.getElementById('boneSlotEditor');
  container.innerHTML = '';

  if (currentTab !== 'character_templates') return;
  if (!currentTemplateId) return;

  let template;
  try {
    template = JSON.parse(jsonEditor.value);
  } catch {
    return;
  }

  template.bone_slots ||= {};

  // Get bones from meshbank first, then fall back to live-extracted bones
  const asset    = getMeshbankAsset(template.model);
  const boneKeys = asset?.bones
    ? Object.keys(asset.bones)
    : previewBones;

  STANDARD_BONE_SLOTS.forEach(slot => {

    const row = document.createElement('div');
    row.className = 'boneSlotRow';

    const label = document.createElement('label');
    label.textContent = slot;

    const select = document.createElement('select');

    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = '--';
    select.appendChild(empty);

    boneKeys.forEach(bone => {
      const option = document.createElement('option');
      option.value = bone;
      option.textContent = bone;
      if (template.bone_slots[slot] === bone) option.selected = true;
      select.appendChild(option);
    });

    select.onchange = () => {
      template.bone_slots[slot] = select.value;
      jsonEditor.value = JSON.stringify(template, null, 2);
    };

    row.appendChild(label);
    row.appendChild(select);
    container.appendChild(row);
  });
}

// =====================================================
// LOAD MESHBANK
// =====================================================

async function loadMeshbank() {

  try {
    const res = await fetch('/api/meshbank');
    meshbank = await res.json();
  } catch (err) {
    console.warn('Meshbank load failed', err);
  }

  renderAssetBrowser();
}

// =====================================================
// LOAD DEFINITIONS
// =====================================================

async function loadDefinitions() {

  try {
    const res = await fetch('/api/editor/definitions?sim_id=default');
    definitions = await res.json();
  } catch (err) {
    console.warn(err);
  }

  renderTabs();
  renderTemplateList();
}

// =====================================================
// TABS
// =====================================================

function renderTabs() {

  tabsEl.innerHTML = '';

  tabs.forEach(tab => {

    const el = document.createElement('div');
    el.className = 'tab';
    if (tab === currentTab) el.classList.add('active');

    // Show just the prefix (e.g. "prop" from "prop_templates")
    el.textContent = tab.replace('_templates', '');

    el.onclick = () => {
      currentTab = tab;
      currentTemplateId = null;
      renderTabs();
      renderTemplateList();
      document.getElementById('boneSlotEditor').innerHTML = '';
    };

    tabsEl.appendChild(el);
  });
}

// =====================================================
// TEMPLATE LIST
// =====================================================

function renderTemplateList() {

  templateListEl.innerHTML = '';

  const bucket = definitions[currentTab] || {};

  Object.entries(bucket).forEach(([id, data]) => {

    const row = document.createElement('div');
    row.className = 'templateRow';
    if (id === currentTemplateId) row.classList.add('active');

    row.textContent = id;

    row.onclick = () => openTemplate(id);

    templateListEl.appendChild(row);
  });
}

// =====================================================
// OPEN TEMPLATE
// =====================================================

function openTemplate(id) {

  currentTemplateId = id;

  const data = definitions[currentTab][id];

  jsonEditor.value = JSON.stringify(data, null, 2);
  editorTitle.textContent = `${currentTab} / ${id}`;

  // Show current model label
  const modelRef = data?.model;
  if (currentModelEl) {
    if (modelRef) {
      const asset = getMeshbankAsset(modelRef);
      const label = asset?.display_name || modelRef;
      currentModelEl.textContent = `Model: ${label}`;
      currentModelEl.style.color = asset ? '#7fc97f' : '#f0a060';
    } else {
      currentModelEl.textContent = 'No model set';
      currentModelEl.style.color = '#888';
    }
  }

  renderBoneSlotEditor();

  // Choose preview type based on tab
  if (currentTab === 'activity_templates') {
    loadActivityTimeline(data);
  } else if (currentTab === 'material_templates') {
    loadMaterialPreview(data);
  } else if (currentTab === 'tile_templates') {
    loadTilePreview(data);
  } else {
    const path = resolveModelPath(data);
    if (path) {
      loadPreviewModel(path);
    } else {
      clearPreviewModel();
    }
  }

  renderTemplateList();
}

// =====================================================
// MATERIAL / TILE PREVIEW
// =====================================================

function clearPreviewMesh() {
  if (previewMesh) {
    previewScene.remove(previewMesh);
    previewMesh = null;
  }
}

function applyTextureToMat(mat, texturePath) {
  if (!texturePath) return;
  previewTexLoader.load(texturePath, (tex) => {
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(2, 2);
    mat.map = tex;
    mat.needsUpdate = true;
  });
}

function loadMaterialPreview(data) {
  clearPreviewModel();
  clearPreviewMesh();
  animationList.innerHTML = '';

  const mat = new THREE.MeshStandardMaterial({
    color: data.color ? new THREE.Color(data.color) : 0xcccccc,
    roughness: data.roughness ?? 0.7,
    metalness: data.metalness ?? 0.0,
  });

  if (data.texture) applyTextureToMat(mat, data.texture);

  previewMesh = new THREE.Mesh(new THREE.SphereGeometry(1.2, 64, 64), mat);
  previewMesh.position.set(0, 1.2, 0);
  previewScene.add(previewMesh);

  // Frame camera on sphere
  previewCamera.position.set(3, 2.5, 3);
  previewControls.target.set(0, 1.2, 0);
  previewControls.update();

  setStatus(data.texture ? `Material: ${data.texture}` : 'Material preview (no texture)');
}

function loadTilePreview(data) {
  clearPreviewModel();
  clearPreviewMesh();
  animationList.innerHTML = '';

  const mat = new THREE.MeshStandardMaterial({
    color: 0xdddddd,
    roughness: 0.9,
  });

  // Try to find matching material template by tile id similarity
  const matTemplates = definitions.material_templates || {};
  const tileId = currentTemplateId || '';
  const matchKey = Object.keys(matTemplates).find(k =>
    k.startsWith(tileId) || tileId.startsWith(k.split('_01')[0])
  );
  const matchedMat = matchKey ? matTemplates[matchKey] : null;

  if (matchedMat?.texture) {
    applyTextureToMat(mat, matchedMat.texture);
    setStatus(`Tile preview — texture: ${matchedMat.texture}`);
  } else {
    setStatus('Tile preview (no matching material texture)');
  }

  // 4x4 tile plane viewed at an angle
  const geo = new THREE.PlaneGeometry(4, 4);
  geo.rotateX(-Math.PI / 2);
  previewMesh = new THREE.Mesh(geo, mat);
  previewScene.add(previewMesh);

  previewCamera.position.set(3, 4, 4);
  previewControls.target.set(0, 0, 0);
  previewControls.update();
}

// =====================================================
// CLEAR PREVIEW
// =====================================================

function clearPreviewModel() {

  clearPreviewMesh();

  if (previewModel) {
    previewScene.remove(previewModel);
    previewModel = null;
  }
  previewMixer = null;
  previewBones = [];
  animationList.innerHTML = '';
}

// =====================================================
// LOAD PREVIEW MODEL
// =====================================================

function loadPreviewModel(path) {

  clearPreviewModel();

  setStatus(`Loading ${path}...`);

  previewLoader.load(path, (gltf) => {

    previewModel = gltf.scene;
    previewBones = extractBones(previewModel);

    previewScene.add(previewModel);

    // Auto-frame camera
    framePreviewCamera(previewModel);

    // Animations
    animationList.innerHTML = '';

    if (gltf.animations.length) {
      previewMixer = new THREE.AnimationMixer(previewModel);

      gltf.animations.forEach(clip => {
        const btn = document.createElement('button');
        btn.className = 'animButton';
        btn.textContent = clip.name;

        btn.onclick = () => {
          previewMixer.stopAllAction();
          const action = previewMixer.clipAction(clip);
          action.reset();
          action.fadeIn(0.2);
          action.play();
        };

        animationList.appendChild(btn);
      });
    }

    // Highlight anchor nodes
    previewModel.traverse(o => {
      if (o.name.toLowerCase().startsWith('anchor_')) {
        const sphere = new THREE.Mesh(
          new THREE.SphereGeometry(0.05),
          new THREE.MeshBasicMaterial({ color: 0xff4444 })
        );
        o.add(sphere);
      }
    });

    renderBoneSlotEditor();

    setStatus(`Loaded: ${path}`);

  }, undefined, (err) => {
    console.error(err);
    setStatus('Model load failed');
  });
}

// =====================================================
// SET MODEL FROM MESHBANK ASSET
// =====================================================

function selectMeshbankAsset(assetId) {

  const asset = meshbank[assetId];
  if (!asset) return;

  // Insert meshbank ID (not path) into the template
  try {
    const data = JSON.parse(jsonEditor.value || '{}');
    data.model = assetId;
    jsonEditor.value = JSON.stringify(data, null, 2);
  } catch {
    // editor might be empty, that's ok
  }

  // Update model label
  if (currentModelEl) {
    currentModelEl.textContent = `Model: ${asset.display_name || assetId}`;
    currentModelEl.style.color = '#7fc97f';
  }

  // Load preview
  if (asset.mesh) {
    loadPreviewModel(asset.mesh);
  }

  setStatus(`Selected: ${asset.display_name || assetId}`);
}

// =====================================================
// ASSET BROWSER  (meshbank entries grouped by category)
// =====================================================

function renderAssetBrowser(filter) {

  assetBrowser.innerHTML = '';

  // Group by category
  const byCategory = {};

  for (const [id, asset] of Object.entries(meshbank)) {

    const name  = asset.display_name || id;
    const query = (filter || '').toLowerCase();

    if (query && !name.toLowerCase().includes(query) && !id.toLowerCase().includes(query)) {
      continue;
    }

    const cat = asset.category || 'misc';
    byCategory[cat] ||= [];
    byCategory[cat].push({ id, asset });
  }

  if (Object.keys(byCategory).length === 0) {
    const empty = document.createElement('div');
    empty.style.cssText = 'color:#888;padding:10px;font-size:12px;';
    empty.textContent = filter ? 'No matches' : 'No meshbank assets loaded';
    assetBrowser.appendChild(empty);
    return;
  }

  for (const [cat, entries] of Object.entries(byCategory)) {

    const title = document.createElement('div');
    title.className = 'assetCategory';
    title.textContent = cat;
    assetBrowser.appendChild(title);

    entries.forEach(({ id, asset }) => {

      const row = document.createElement('div');
      row.className = 'assetRow';

      const name = document.createElement('div');
      name.className = 'assetName';
      name.textContent = asset.display_name || id;

      const sub = document.createElement('div');
      sub.className = 'assetId';
      sub.textContent = id;

      row.appendChild(name);
      row.appendChild(sub);

      row.onclick = () => selectMeshbankAsset(id);

      assetBrowser.appendChild(row);
    });
  }
}

// =====================================================
// =====================================================
// DEFAULT TEMPLATES  — one skeleton per category so
// the user can see all the available fields.
// =====================================================

const DEFAULT_TEMPLATES = {

  prop_templates: {
    name: "New Prop",
    category: "furniture",
    model: "",
    tags: [],
    carryable: false,
    interactions: [],
    anchors: []
  },

  item_templates: {
    name: "New Item",
    category: "misc",
    model: "",
    tags: [],
    stackable: true,
    max_stack: 10,
    weight: 0.5,
    value: 1
  },

  character_templates: {
    name: "New Character",
    age_range: [25, 40],
    traits: [],
    model: "adult_male",
    bone_slots: {
      head:        "mixamorigHead",
      neck:        "mixamorigNeck",
      right_hand:  "mixamorigRightHand",
      left_hand:   "mixamorigLeftHand",
      spine:       "mixamorigSpine2",
      pelvis:      "mixamorigHips",
      right_foot:  "mixamorigRightFoot",
      left_foot:   "mixamorigLeftFoot"
    },
    needs: {
      hunger: 100,
      energy: 100,
      hygiene: 100,
      social: 100,
      fun: 100
    },
    skills: {
      cooking: 0,
      cleaning: 0,
      repair: 0,
      social: 0
    },
    employment: {
      job: "",
      salary: 0
    },
    daily_schedule: {
      sleep: [22, 6],
      work: [8, 17]
    },
    starting_inventory: []
  },

  clothing_templates: {
    name: "New Clothing",
    slot: "upper_layer1",
    model: "",
    shared_skeleton: true,
    tags: ["clothing"],
    color: "#ffffff",
    offset: { x: 0, y: 0, z: 0 },
    rotation: { x: 0, y: 0, z: 0 },
    scale: 1.0
  },

  interaction_templates: {
    name: "New Interaction",
    duration: 600,
    required_prop_tags: [],
    need_changes: {
      hunger: 0,
      energy: 0,
      hygiene: 0,
      social: 0,
      fun: 0
    },
    animation: "interact",
    priority: 50
  },

  // Activity = intention the LLM picks; engine runs steps automatically.
  // Each step: find nearest prop matching target_interaction, move there, execute.
  // requires: [] lists step ids that must complete first.
  activity_templates: {
    name: "New Activity",
    category: "misc",
    interruptible: true,
    satisfies_needs: [],
    steps: [
      {
        id: "step_1",
        interaction: "",
        target_interaction: "",
        target_tags: [],
        duration_minutes: 5,
        requires: []
      }
    ]
  },

  tile_templates: {
    name: "New Tile",
    category: "terrain",
    material: "",
    walkable: true,
    vehicle_access: false,
    movement_cost: 1,
    blocks_los: false,
    buildable: true
  },

  material_templates: {
    name: "New Material",
    texture: "/resources/tiles/",
    editor_color: "#888888",
    roughness: 1.0,
    metalness: 0.0,
    normal_map: "",
    repeat: [1, 1]
  },

  floorplan_templates: {
    name: "New Floorplan",
    rooms: [],
    doors: [],
    windows: [],
    walls: []
  },

  recipe_templates: {
    name: "New Recipe",
    ingredients: [],
    result_item: "",
    result_quantity: 1,
    skill_required: "cooking",
    skill_level: 0,
    duration_minutes: 30
  },

  // Service catalog entry — what hired service workers offer
  service_templates: {
    name: "New Service",
    category: "reconstruction",
    base_cost: 100,
    duration_hours: 2,
    worker_trait: "handyman",
    illicit: false,
    description: ""
  },

  job_templates: {
    name: "New Job",
    sector: "services",
    salary: 2000,
    work_hours: [8, 17],
    work_days: [1, 2, 3, 4, 5],
    skill_requirements: {},
    promotion_path: []
  },

  company_templates: {
    name: "New Company",
    sector: "services",
    job_slots: [],
    starting_funds: 10000,
    tags: []
  },

  vehicle_templates: {
    name: "New Vehicle",
    model: "",
    max_speed: 60,
    seats: 4,
    fuel_type: "petrol",
    fuel_capacity: 50,
    tags: []
  },

  // Long-term weekly drives. Characters have 100 points distributed across
  // active needs. 0 points = need doesn't apply to this character.
  need_templates: {
    name: "New Long-term Need",
    description: "",
    category: "social",
    weekly_target: 1,
    satisfying_activities: [],
    decay_per_week: 1
  },

  mood_templates: {
    name: "New Mood",
    description: "",
    polarity: "neutral",
    emotional_temperature_range: [30, 60],
    triggers: {},
    duration_ticks: 3600,
    behavior_flags: [],
    need_modifiers: {}
  },

  trait_templates: {
    name: "New Trait",
    polarity: "positive",
    description: "",
    need_modifiers: {},
    skill_modifiers: {},
    behavior_flags: []
  }
};

function getDefaultTemplate(tab) {
  return JSON.parse(JSON.stringify(DEFAULT_TEMPLATES[tab] || {}));
}

// =====================================================
// TEMPLATE CRUD
// =====================================================

window.createTemplate = function(){

  const id = prompt("Template ID");

  if(!id) return;

  if(!definitions[currentTab]){

    definitions[currentTab] = {};
  }

  definitions[currentTab][id] = getDefaultTemplate(currentTab);

  currentTemplateId = id;

  renderTemplateList();

  openTemplate(id);
};

// =====================================================
// DUPLICATE
// =====================================================

window.duplicateTemplate = function(){

  if(!currentTemplateId) return;

  const id = prompt('Duplicate as');

  if(!id) return;

  definitions[currentTab][id] = JSON.parse(
    JSON.stringify(
      definitions[currentTab][currentTemplateId]
    )
  );

  renderTemplateList();
}

// =====================================================
// DELETE
// =====================================================

window.deleteTemplate = function(){

  if(!currentTemplateId) return;

  delete definitions[currentTab][currentTemplateId];

  currentTemplateId = null;

  jsonEditor.value = '';

  renderTemplateList();
}

// =====================================================
// SAVE
// =====================================================

window.saveDefinitions = async function(){

  try {

    if(currentTemplateId){

      definitions[currentTab][currentTemplateId] =
        JSON.parse(jsonEditor.value);
    }

    await fetch(
      '/api/editor/definitions?sim_id=default',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(definitions)
      }
    );

    setStatus('Saved');

  } catch(err){

    console.error(err);

    setStatus('Save failed');
  }
}


// =====================================================
// STATUS
// =====================================================

function setStatus(text) {
  if (statusBar) statusBar.textContent = text;
}

// =====================================================
// ANIMATE  (OrbitControls damping, no auto-rotation)
// =====================================================

const previewClock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const delta = previewClock.getDelta();
  previewControls.update();
  if (previewMixer) previewMixer.update(delta);
  previewRenderer.render(previewScene, previewCamera);
}

animate();

// =====================================================
// STARTUP
// =====================================================

(async () => {
  await loadMeshbank();
  await loadDefinitions();
})();

// =====================================================
// ACTIVITY STEP TIMELINE  (Three.js per-step mini previews)
// =====================================================

// Each step gets its own WebGLRenderer + scene for independence.
// We reuse a pool so we don't create/destroy renderers on every open.
const _stepRenderers = [];   // pool of {renderer, scene, camera, controls, anim}
const _stepCanvases  = [];   // pool of canvas wrappers

const STEP_SIZE = 160;  // px for each step card canvas

function _getStepRenderer(idx) {
  if (_stepRenderers[idx]) return _stepRenderers[idx];

  const scene    = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1e24);

  const ambLight = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambLight);
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
  dirLight.position.set(3, 5, 3);
  scene.add(dirLight);

  const camera   = new THREE.PerspectiveCamera(45, 1, 0.1, 200);
  camera.position.set(2.5, 2, 2.5);
  camera.lookAt(0, 0.5, 0);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(STEP_SIZE, STEP_SIZE);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.1;
  controls.autoRotate    = true;
  controls.autoRotateSpeed = 1.5;

  let model  = null;
  let mixer  = null;
  let active = false;

  function animLoop() {
    if (!active) return;
    requestAnimationFrame(animLoop);
    controls.update();
    if (mixer) mixer.update(0.016);
    renderer.render(scene, camera);
  }

  const entry = { scene, camera, renderer, controls, model: null, mixer: null, active: false, animLoop };
  _stepRenderers[idx] = entry;
  return entry;
}

function _clearStepRenderer(entry) {
  if (entry.model) {
    entry.scene.remove(entry.model);
    entry.model = null;
  }
  entry.mixer  = null;
  entry.active = false;
}

// Find the first prop_template whose tags overlap the step's target_tags
function _findPropForStep(step) {
  const tags = step.target_tags || [];
  if (!tags.length) return null;
  const props = definitions.prop_templates || {};
  for (const [, prop] of Object.entries(props)) {
    const ptags = prop.tags || [];
    if (tags.some(t => ptags.includes(t)) && prop.model) return prop;
  }
  // Try items too
  const items = definitions.item_templates || {};
  for (const [, item] of Object.entries(items)) {
    if (item.model) {
      const otype = item.object_type || '';
      if (tags.some(t => t === otype || t === 'computer' && otype === 'computer')) return item;
    }
  }
  return null;
}

// Play a named clip on a step renderer entry.
// Phases are tried in order: loop → start → first available
function _playStepClip(entry, clipName) {
  if (!entry.mixer || !entry._clips) return;
  const clip = entry._clips.find(c => c.name === clipName);
  if (!clip) return;
  entry.mixer.stopAllAction();
  const action = entry.mixer.clipAction(clip);
  action.reset().fadeIn(0.15).play();
  entry._currentClip = clipName;
}

function _pickDefaultClip(animations, gltfClips) {
  // Prefer loop[0], then start[0], then first available gltf clip
  const names = [...(animations?.loop || []), ...(animations?.start || [])];
  for (const name of names) {
    if (gltfClips.find(c => c.name === name)) return name;
  }
  return gltfClips[0]?.name || null;
}

function _loadModelIntoStep(entry, modelRef, animations, onDone) {
  const path = (() => {
    const asset = meshbank[modelRef];
    if (asset?.mesh) return asset.mesh;
    if (modelRef?.startsWith('/') || modelRef?.includes('.glb')) return modelRef;
    return null;
  })();

  if (!path) { onDone && onDone(false, []); return; }

  previewLoader.load(path, (gltf) => {
    _clearStepRenderer(entry);
    entry.model  = gltf.scene;
    entry._clips = gltf.animations || [];
    entry._animPhases = animations || {};
    entry._currentClip = null;
    entry.scene.add(entry.model);

    // Auto-frame
    const box  = new THREE.Box3().setFromObject(entry.model);
    const cent = box.getCenter(new THREE.Vector3());
    const maxD = Math.max(...box.getSize(new THREE.Vector3()).toArray());
    const dist = maxD * 1.8;
    entry.camera.position.set(cent.x + dist*0.6, cent.y + dist*0.7, cent.z + dist*0.6);
    entry.controls.target.copy(cent);
    entry.controls.update();

    if (entry._clips.length) {
      entry.mixer = new THREE.AnimationMixer(entry.model);
      const defaultClip = _pickDefaultClip(animations, entry._clips);
      if (defaultClip) _playStepClip(entry, defaultClip);
    }

    entry.active = true;
    entry.animLoop();
    onDone && onDone(true, entry._clips);
  }, undefined, () => { onDone && onDone(false, []); });
}

// ── HTML/CSS for the timeline injected into #modelPreview ──────────────────

const _TIMELINE_STYLE = `
  <style>
    #activityTimeline {
      display: flex; flex-direction: column; height: 100%;
      overflow: hidden; padding: 0;
    }
    #activityTimelineHeader {
      padding: 8px 10px; font-size: 12px; color: #7ab4f5;
      background: #1d2229; border-bottom: 1px solid #444;
      flex-shrink: 0;
    }
    #activityTimelineScroll {
      flex: 1; overflow-x: auto; overflow-y: hidden;
      display: flex; align-items: flex-start;
      padding: 12px 10px; gap: 10px;
    }
    .stepCard {
      flex-shrink: 0; width: ${STEP_SIZE}px;
      background: #252b33; border: 1px solid #444;
      border-radius: 4px; overflow: hidden;
      display: flex; flex-direction: column;
    }
    .stepCard.hasModel { border-color: #4a7fa8; }
    .stepCardCanvas { width: ${STEP_SIZE}px; height: ${STEP_SIZE}px; display: block; }
    .stepCardNoModel {
      width: ${STEP_SIZE}px; height: ${STEP_SIZE}px;
      display: flex; align-items: center; justify-content: center;
      font-size: 28px; color: #445; background: #1a1e24;
    }
    .stepCardBody { padding: 6px 8px; }
    .stepCardNum { font-size: 10px; color: #6699cc; margin-bottom: 2px; }
    .stepCardName { font-size: 12px; color: #ddeeff; font-weight: bold; margin-bottom: 2px; }
    .stepCardDur { font-size: 10px; color: #888; }
    .stepCardTags { font-size: 10px; color: #667; margin-top: 3px; }
    .stepArrow {
      flex-shrink: 0; align-self: center; font-size: 18px; color: #445;
    }
    .stepAnimBar {
      display: flex; flex-wrap: wrap; gap: 3px;
      padding: 4px 6px; border-top: 1px solid #333;
      background: #1a1e24; min-height: 24px;
    }
    .stepAnimBtn {
      padding: 2px 6px; font-size: 10px; background: #2a3340;
      color: #99bbdd; border: 1px solid #3a4555; cursor: pointer;
      border-radius: 2px; white-space: nowrap;
    }
    .stepAnimBtn:hover { background: #3a4e64; }
    .stepAnimBtn.active { background: #1e4a7a; border-color: #5599cc; color: #fff; }
    .stepAnimBtnRaw { color: #7799aa; }
  </style>
`;

let _timelineActive = false;

function loadActivityTimeline(data) {
  // Stop any running step renderers
  _stepRenderers.forEach(e => { if (e) e.active = false; });
  _timelineActive = false;

  const steps = data?.steps || [];
  const mount  = document.getElementById('modelPreview');

  mount.innerHTML = _TIMELINE_STYLE + `
    <div id="activityTimeline">
      <div id="activityTimelineHeader">
        ▶ Activity Steps (${steps.length}) — drag to orbit · click phase buttons to preview animations
      </div>
      <div id="activityTimelineScroll"></div>
    </div>
  `;

  const scroll = mount.querySelector('#activityTimelineScroll');
  _timelineActive = true;

  steps.forEach((step, idx) => {
    if (idx > 0) {
      const arrow = document.createElement('div');
      arrow.className = 'stepArrow';
      arrow.textContent = '→';
      scroll.appendChild(arrow);
    }

    const card = document.createElement('div');
    card.className = 'stepCard';

    const prop = _findPropForStep(step);

    // Look up interaction_template to get named animations
    const itpl   = definitions.interaction_templates?.[step.interaction] || {};
    const phases = itpl.animations || {};  // { start:[…], loop:[…], stop:[…] }

    const body = document.createElement('div');
    body.className = 'stepCardBody';
    body.innerHTML = `
      <div class="stepCardNum">Step ${idx + 1}</div>
      <div class="stepCardName">${step.interaction || step.id || '?'}</div>
      <div class="stepCardDur">${step.duration_minutes ?? '?'} min</div>
      ${step.target_tags?.length ? `<div class="stepCardTags">${step.target_tags.join(', ')}</div>` : ''}
    `;

    // Animation phase buttons — built after model loads so we know which clips exist
    const animBar = document.createElement('div');
    animBar.className = 'stepAnimBar';

    function buildAnimButtons(entry, gltfClips) {
      animBar.innerHTML = '';
      if (!gltfClips.length) return;

      // Phase buttons (start / loop / stop) — only phases that have ≥1 matching clip
      const phaseOrder = ['start', 'loop', 'stop'];
      phaseOrder.forEach(phase => {
        const clips = (phases[phase] || []).filter(n => gltfClips.find(c => c.name === n));
        if (!clips.length) return;
        // Cycle through clips in that phase on repeated click
        let ci = 0;
        const btn = document.createElement('button');
        btn.className = 'stepAnimBtn';
        btn.title     = clips.join(' / ');
        btn.textContent = phase;
        btn.onclick = () => {
          const name = clips[ci % clips.length];
          ci++;
          _playStepClip(entry, name);
          // highlight active button
          animBar.querySelectorAll('.stepAnimBtn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
        };
        animBar.appendChild(btn);
      });

      // Also a "•" button per raw GLTF clip not covered by phases
      const coveredNames = new Set(Object.values(phases).flat());
      gltfClips.forEach(clip => {
        if (coveredNames.has(clip.name)) return;
        const btn = document.createElement('button');
        btn.className   = 'stepAnimBtn stepAnimBtnRaw';
        btn.title       = clip.name;
        btn.textContent = clip.name.length > 10 ? clip.name.slice(0,9)+'…' : clip.name;
        btn.onclick = () => {
          _playStepClip(entry, clip.name);
          animBar.querySelectorAll('.stepAnimBtn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
        };
        animBar.appendChild(btn);
      });

      // Mark the currently-playing button
      if (entry._currentClip) {
        animBar.querySelectorAll('.stepAnimBtn').forEach(btn => {
          if (btn.title.split(' / ').includes(entry._currentClip) ||
              btn.title === entry._currentClip) {
            btn.classList.add('active');
          }
        });
      }
    }

    if (prop?.model) {
      card.classList.add('hasModel');

      const entry = _getStepRenderer(idx);
      _clearStepRenderer(entry);

      const canvasSlot = document.createElement('div');
      canvasSlot.style.cssText = `width:${STEP_SIZE}px;height:${STEP_SIZE}px;background:#111;display:flex;align-items:center;justify-content:center;font-size:11px;color:#555`;
      canvasSlot.textContent = 'loading…';

      card.appendChild(canvasSlot);
      card.appendChild(body);
      card.appendChild(animBar);
      scroll.appendChild(card);

      _loadModelIntoStep(entry, prop.model, phases, (ok, gltfClips) => {
        if (!_timelineActive) return;
        if (ok) {
          card.replaceChild(entry.renderer.domElement, canvasSlot);
          entry.renderer.domElement.className = 'stepCardCanvas';
          buildAnimButtons(entry, gltfClips);
        } else {
          canvasSlot.textContent = '(no model)';
        }
      });

    } else {
      const icons = { toilet:'🚽', sit_down_seat:'🪑', lie_down:'🛌', stand_up:'🧍',
        sleep:'😴', eat_meal:'🍽️', use_toilet:'🚽', flush_toilet:'🚽',
        drive_car_to:'🚗', phone_call:'📞', phone_send_text:'💬', phone_check:'📱',
        phone_read_text:'📱', charge:'🔌', computer_social_media:'💻', computer_videos:'▶️',
        computer_game:'🎮', computer_wiki_research:'🔍', computer_order_item:'🛒',
        computer_buy_stock:'📈', computer_send_email:'📧', computer_check_email:'📧',
        computer_job_search:'💼', computer_dating:'❤️',
      };
      const placeholder = document.createElement('div');
      placeholder.className = 'stepCardNoModel';
      placeholder.textContent = icons[step.interaction] || '⬜';
      card.appendChild(placeholder);
      card.appendChild(body);
      scroll.appendChild(card);
    }
  });

  animationList.innerHTML = '';
  document.getElementById('boneSlotEditor').innerHTML = '';
}

