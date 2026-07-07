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
  "school_templates",
  "vehicle_templates",
  "floorplan_templates",
  "tile_templates",
  "material_templates",
  "hobby_templates",
  "socioeconomics",
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

// ── Interaction preview state ─────────────────────────────────────────────────
let _ixActive = false;
let _ixCharKey = null;
let _ixPropKey = null;           // currently previewed prop template key
let _ixPropMesh = null;          // Three.Object3D for prop in scene
let _ixItemMesh = null;          // Three.Object3D for item in scene
let _ixClips = [];
let _ixPhases = {};
let _ixHeldMeshes = {};          // slot -> Three.Mesh
let _ixCheckedItems = new Map();  // slot ('right_hand'/'left_hand') -> itemId
let _ixPhase = null;             // current active phase name
let _ixPlayTimeout = null;
// ── Second character (char-on-char interactions) ──────────────────────────────
let _ixTargetCharKey = null;
let _ixTargetModel   = null;     // Three.Object3D in scene
let _ixTargetMixer   = null;     // AnimationMixer
let _ixTargetClips   = [];       // animation clips
let _ixTargetPhases  = {};       // data.target_animations from template
let _ixTargetRegionMarkers = [];  // spheres placed on target bones (may be multiple)
let _ixVarDefs       = {};       // data.variables definitions
let _ixVarValues     = {};       // current variable values for this interaction
// ── Prop drag + radius ring ───────────────────────────────────────────────────
let _ixRadiusRing    = null;     // THREE.Line circle showing interaction reach
let _ixDragging      = false;
let _ixDragOffset    = new THREE.Vector3();
let _ixInteractDist  = 1.2;     // metres — read from anchor.distance or default
const _ixDragPlaneY  = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
const _ixDragRay     = new THREE.Raycaster();

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
    const label = tab === 'socioeconomics' ? 'Socioeconomics' : tab.replace('_templates', '');
    el.textContent = label;

    el.onclick = () => {
      currentTab = tab;
      currentTemplateId = null;
      renderTabs();
      if (tab === 'socioeconomics') {
        renderSocioeconomicsPanel();
      } else {
        renderTemplateList();
        document.getElementById('boneSlotEditor').innerHTML = '';
      }
    };

    tabsEl.appendChild(el);
  });
}

// =====================================================
// TEMPLATE LIST
// =====================================================

function renderTemplateList() {
  // Restore JSON editor if switching away from Socioeconomics
  const _jsonEd = document.getElementById('jsonEditor');
  const _socioP = document.getElementById('socioPanel');
  if (_jsonEd)  _jsonEd.style.display  = '';
  if (_socioP) _socioP.style.display = 'none';

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
  _ixActive = false;  // deactivate interaction preview whenever we switch away
  if (_ixPropMesh)    { previewScene.remove(_ixPropMesh); _ixPropMesh = null; }
  if (_ixItemMesh)    { previewScene.remove(_ixItemMesh); _ixItemMesh = null; }
  if (_ixRadiusRing)  { previewScene.remove(_ixRadiusRing); _ixRadiusRing = null; }
  _ixDragging = false;
  if (_ixTargetModel) { previewScene.remove(_ixTargetModel); _ixTargetModel = null; }
  if (_ixTargetMixer) { _ixTargetMixer.stopAllAction(); _ixTargetMixer = null; }
  _ixTargetRegionMarkers.forEach(m => { if (m.parent) m.parent.remove(m); });
  _ixTargetRegionMarkers = [];
  _ixTargetClips = [];
  if (currentTab === 'activity_templates') {
    loadActivityTimeline(data);
  } else if (currentTab === 'interaction_templates') {
    loadInteractionPreview(data);
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
      showPlaceholderMesh(currentTab);
      const modelRef = data?.model;
      if (modelRef) {
        setStatus(`No GLB for meshbank ID "${modelRef}" — add it via Mesh Bank`);
      } else {
        setStatus('No model assigned — use the asset browser to link one');
      }
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

function showPlaceholderMesh(tab) {
  clearPreviewMesh();

  let geo, color, yPos;

  if (tab === 'prop_templates') {
    geo   = new THREE.CylinderGeometry(0.38, 0.38, 1.0, 24);
    color = 0x6688aa;   // steel blue cylinder
    yPos  = 0.5;
  } else if (tab === 'item_templates') {
    geo   = new THREE.BoxGeometry(0.35, 0.35, 0.35);
    color = 0xcc9944;   // amber cube
    yPos  = 0.175;
  } else if (tab === 'character_templates') {
    geo   = new THREE.CapsuleGeometry(0.35, 0.8, 8, 16);
    color = 0x88bb88;   // soft green capsule
    yPos  = 0.75;
  } else {
    return;
  }

  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.65, metalness: 0.1 });
  previewMesh = new THREE.Mesh(geo, mat);
  previewMesh.position.set(0, yPos, 0);
  previewScene.add(previewMesh);

  // Frame camera tightly on the placeholder
  framePreviewCamera(previewMesh);
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
// PLACEHOLDER MESH (shown when a model file is missing)
// =====================================================

function showPreviewPlaceholder(label) {
  clearPreviewModel();
  // Orange semi-transparent humanoid box + wireframe overlay
  const geo  = new THREE.BoxGeometry(0.7, 1.7, 0.45);
  const mat  = new THREE.MeshStandardMaterial({ color:0xff6600, opacity:0.45, transparent:true });
  const mesh = new THREE.Mesh(geo, mat);
  const wire = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color:0xff9900, wireframe:true }));
  mesh.add(wire);
  mesh.position.set(0, 0.85, 0);
  // Question-mark sphere on top
  const headGeo = new THREE.SphereGeometry(0.22, 10, 8);
  const headMat = new THREE.MeshStandardMaterial({ color:0xff6600, opacity:0.45, transparent:true });
  const head = new THREE.Mesh(headGeo, headMat);
  head.add(new THREE.Mesh(headGeo, new THREE.MeshBasicMaterial({ color:0xff9900, wireframe:true })));
  head.position.set(0, 1.85, 0);
  const grp = new THREE.Group();
  grp.add(mesh);
  grp.add(head);
  previewModel = grp;
  previewScene.add(previewModel);
  framePreviewCamera(previewModel);
  setStatus('⚠ ' + (label || 'Model file not found — placeholder shown'));
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
    showPreviewPlaceholder('Model not found: ' + path.split('/').pop());
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
  if (previewMixer)       previewMixer.update(delta);
  if (_ixTargetMixer)     _ixTargetMixer.update(delta);
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

// =====================================================
// BODY REGION MAP  (readable name → candidate bone names)
// =====================================================

// BODY_REGION_MAP: string[] = single-group (first match wins)
//                  string[][] = bilateral group (one match per sub-array → multiple markers)
const BODY_REGION_MAP = {
  // ── broad areas ──────────────────────────────────────────────────────────
  head:        ['Head','head','mixamorigHead'],
  face:        ['Head','head','Face','face'],
  neck:        ['Neck','neck','mixamorigNeck'],
  chest:       ['Chest','chest','Spine2','mixamorigSpine2'],
  torso:       ['Spine2','Spine1','Spine','chest','mixamorigSpine2'],
  upper_body:  ['Spine2','Chest','Spine1','mixamorigSpine2'],
  lower_body:  ['Hips','hips','pelvis','Pelvis','mixamorigHips'],
  back:        ['Spine1','Spine2','mixamorigSpine1'],
  groin:       ['Hips','pelvis','mixamorigHips'],
  // ── bilateral (nested array → one marker per side) ────────────────────────
  arms:        [['RightArm','UpperArm_R','mixamorigRightArm'],
                ['LeftArm','UpperArm_L','mixamorigLeftArm']],
  legs:        [['RightUpLeg','Thigh_R','mixamorigRightUpLeg'],
                ['LeftUpLeg','Thigh_L','mixamorigLeftUpLeg']],
  hands:       [['RightHand','hand_r','Hand_R','mixamorigRightHand'],
                ['LeftHand','hand_l','Hand_L','mixamorigLeftHand']],
  feet:        [['RightFoot','foot_r','Foot_R','mixamorigRightFoot'],
                ['LeftFoot','foot_l','Foot_L','mixamorigLeftFoot']],
  shoulders:   [['RightShoulder','Shoulder_R','mixamorigRightShoulder'],
                ['LeftShoulder','Shoulder_L','mixamorigLeftShoulder']],
  // ── single sides ─────────────────────────────────────────────────────────
  right_arm:       ['RightArm','UpperArm_R','mixamorigRightArm'],
  left_arm:        ['LeftArm','UpperArm_L','mixamorigLeftArm'],
  right_hand:      ['RightHand','hand_r','Hand_R','mixamorigRightHand'],
  left_hand:       ['LeftHand','hand_l','Hand_L','mixamorigLeftHand'],
  right_leg:       ['RightUpLeg','Thigh_R','mixamorigRightUpLeg'],
  left_leg:        ['LeftUpLeg','Thigh_L','mixamorigLeftUpLeg'],
  right_foot:      ['RightFoot','foot_r','Foot_R','mixamorigRightFoot'],
  left_foot:       ['LeftFoot','foot_l','Foot_L','mixamorigLeftFoot'],
  right_shoulder:  ['RightShoulder','Shoulder_R','mixamorigRightShoulder'],
  left_shoulder:   ['LeftShoulder','Shoulder_L','mixamorigLeftShoulder'],
};

// Returns array of matched bone names (1 for single-group, N for bilateral)
function resolveBodyRegionBones(regionName, boneList) {
  const entry = BODY_REGION_MAP[regionName];
  if (!entry) {
    // Fallback: direct bone name
    const direct = boneList.find(b => b.toLowerCase() === regionName.toLowerCase());
    return direct ? [direct] : [];
  }
  if (Array.isArray(entry[0])) {
    // Bilateral: entry is string[][] — resolve one bone per sub-array
    return entry
      .map(group => group.map(c => boneList.find(b => b === c || b.toLowerCase() === c.toLowerCase())).find(Boolean))
      .filter(Boolean);
  }
  // Single group: string[] — first match
  const hit = entry.map(c => boneList.find(b => b === c || b.toLowerCase() === c.toLowerCase())).find(Boolean);
  return hit ? [hit] : [];
}

// Backward-compat alias (returns first bone name or null)
function resolveBodyRegion(regionName, boneList) {
  return resolveBodyRegionBones(regionName, boneList)[0] || null;
}

// =====================================================
// INTERACTION PREVIEW
// =====================================================

const _IX_STYLE = `<style>
#ixWrap{display:flex;flex-direction:column;height:100%;background:#1a1e24;overflow:hidden}
#ixCharBar{display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1d2229;border-bottom:1px solid #333;flex-shrink:0;flex-wrap:wrap}
#ixCharBar label{font-size:11px;color:#888;white-space:nowrap}
#ixCharSelect,#ixPropSelect{background:#2a2f38;color:#fff;border:1px solid #555;padding:3px 6px;font-size:11px;flex:1;min-width:0}
#ixCanvas{flex:1;min-height:0;overflow:hidden;background:#111;position:relative}
#ixPhaseTag{position:absolute;top:8px;right:10px;background:#1a253099;color:#7bf;font-size:11px;font-weight:bold;padding:3px 10px;border-radius:10px;letter-spacing:.08em;pointer-events:none;z-index:10;text-transform:uppercase;transition:color .2s}
#ixPhaseTag.start{color:#6fa}
#ixPhaseTag.loop{color:#ff9}
#ixPhaseTag.stop{color:#f96}
#ixPhaseTag.aborted{color:#f66;background:#2a000099}
#ixPhaseTag.idle{color:#557}
#ixPhaseBar{display:flex;gap:4px;padding:6px 8px;background:#1d2229;border-top:1px solid #333;flex-shrink:0;flex-wrap:wrap;align-items:center}
.ixPhaseBtn{padding:4px 10px;font-size:11px;background:#2a3340;color:#cde;border:none;cursor:pointer;border-radius:2px;transition:background .12s}
.ixPhaseBtn:hover:not(:disabled){background:#3a4f60}
.ixPhaseBtn.active{background:#4a7fa0;color:#fff}
.ixPhaseBtn:disabled{opacity:.35;cursor:default}
.ixPlayAll{background:#2a4a2a !important}.ixPlayAll:hover:not(:disabled){background:#3a6a3a !important}
.ixAbortBtn{background:#4a2020 !important;color:#f88 !important}.ixAbortBtn:hover:not(:disabled){background:#6a2a2a !important}
.ixResetBtn{background:#383020 !important;color:#cc8 !important}.ixResetBtn:hover:not(:disabled){background:#4a4030 !important}
.ixReturnBtn{background:#1e3a1e !important;color:#8d8 !important}.ixReturnBtn:hover:not(:disabled){background:#2a5a2a !important}
#ixIdleBtn{margin-left:auto}
#ixInfoPanel{flex-shrink:0;padding:6px 10px;border-top:1px solid #333;background:#1b1f25;max-height:130px;overflow-y:auto}
.ixSection{margin-bottom:8px}
.ixSectionTitle{font-size:10px;color:#6699cc;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;border-bottom:1px solid #2a3340;padding-bottom:2px}
.ixChips{display:flex;flex-wrap:wrap;gap:4px}
.ixChip{padding:2px 8px;background:#2a3a4a;color:#adc;font-size:11px;border-radius:10px}
.ixChip.missing{background:#4a2a2a;color:#f99}
.ixItemRow{display:flex;align-items:center;gap:5px;padding:3px 0;border-bottom:1px solid #222}
.ixItemRow:last-child{border-bottom:none}
.ixItemCb{width:14px;height:14px;cursor:pointer;accent-color:#4a9a4a;flex-shrink:0}
.ixItemLabel{font-size:11px;color:#ccc;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ixHandTag{min-width:18px;font-size:10px;font-weight:bold;color:#9cf;background:#1a3a5a;border-radius:3px;padding:1px 4px;text-align:center;flex-shrink:0}
.ixCleanupNote{font-size:11px;color:#c9a;background:#2a2530;border-left:2px solid #a88;padding:3px 8px;margin-top:4px;border-radius:2px}
.ixOffGrid{font-size:11px;color:#f0a060;padding:2px 0;margin-bottom:4px}
.ixEmptyNote{font-size:11px;color:#555;padding:4px 0}
#ixLog{flex-shrink:0;max-height:90px;overflow-y:auto;padding:4px 8px;background:#111620;border-top:1px solid #222}
.ixLogEntry{padding:1px 0;border-bottom:1px solid #1a2030;color:#8899bb;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:10px}
.ixLogTs{color:#334455;font-family:monospace;margin-right:5px}
.ixLogPhase{font-weight:bold}.ixLogPhase.start{color:#6fa}.ixLogPhase.loop{color:#ff9}.ixLogPhase.stop{color:#f96}.ixLogPhase.aborted{color:#f66}
.ixVarRow{display:flex;align-items:center;gap:4px;padding:2px 0}
.ixVarKey{font-size:11px;color:#99aacc;min-width:90px;flex-shrink:0}
.ixVarSelect,.ixVarNum,.ixVarText{background:#222c38;color:#dde;border:1px solid #3a4a5a;padding:2px 4px;font-size:10px;flex:1;min-width:0;max-width:130px}
.ixVarBtnRow{display:flex;gap:2px;margin-left:2px}
.ixVarBtn{padding:1px 5px;font-size:11px;background:#223240;border:1px solid #334;color:#aaa;cursor:pointer;border-radius:2px}
.ixVarBtn:hover{background:#334455}
.ixTargetRegion{font-size:11px;color:#f99;background:#2a1a1a;border-left:2px solid #a44;padding:3px 8px;margin-top:4px;border-radius:2px}
.ixModRow{display:flex;justify-content:space-between;padding:1px 0;font-size:10px}
.ixModCond{color:#778;flex:1}
.ixModVal{color:#9c9;font-weight:bold;margin-left:4px}
</style>`;

function loadInteractionPreview(data) {
  _ixActive = true;
  _ixPhases       = data.animations         || {};
  _ixTargetPhases = data.target_animations  || {};
  _ixVarDefs      = data.variables          || {};
  _ixVarValues    = Object.fromEntries(
    Object.entries(_ixVarDefs).map(([k,v]) => [k, v.default ?? ''])
  );
  _ixHeldMeshes = {};
  if (_ixPlayTimeout) { clearTimeout(_ixPlayTimeout); _ixPlayTimeout = null; }

  const charTemplates = definitions.character_templates || {};
  const charKeys = Object.keys(charTemplates);
  if (!_ixCharKey || !charTemplates[_ixCharKey]) _ixCharKey = charKeys[0] || null;

  const reqProps     = data.requires_prop_tags    || [];
  const reqItemCat   = data.requires_item_category || null;
  const offGrid      = !!data.off_grid;
  const isCharTarget = data.target === 'character'; // char-on-char interaction

  // Target character — default to same type as primary
  if (isCharTarget) {
    if (!_ixTargetCharKey || !charTemplates[_ixTargetCharKey])
      _ixTargetCharKey = _ixCharKey;
  } else {
    // Clean up any previously loaded target
    if (_ixTargetModel) { previewScene.remove(_ixTargetModel); _ixTargetModel = null; }
    if (_ixTargetMixer) { _ixTargetMixer.stopAllAction(); _ixTargetMixer = null; }
    _ixTargetClips = [];
  }

  // All props that satisfy at least one required tag
  const matchingProps = reqProps.length
    ? Object.entries(definitions.prop_templates || {})
        .filter(([, p]) => reqProps.some(tag => (p.tags || []).includes(tag)))
    : [];
  // Keep current prop selection if it still matches, else pick first
  if (!_ixPropKey || !matchingProps.find(([k]) => k === _ixPropKey))
    _ixPropKey = matchingProps[0]?.[0] || null;

  const matchItems = reqItemCat
    ? Object.entries(definitions.item_templates || {})
        .filter(([, v]) => v.category === reqItemCat)
        .slice(0, 10)
    : [];

  const charOptions = charKeys.map(k =>
    `<option value="${k}" ${k === _ixCharKey ? 'selected' : ''}>${k}</option>`
  ).join('') || '<option value="">— no character templates —</option>';

  const targetOptions = charKeys.map(k =>
    `<option value="${k}" ${k === _ixTargetCharKey ? 'selected' : ''}>${k}</option>`
  ).join('') || '<option value="">— no character templates —</option>';

  const propOptions = matchingProps.map(([k, p]) =>
    `<option value="${k}" ${k === _ixPropKey ? 'selected' : ''}>${p.name || k}</option>`
  ).join('');

  const phaseHasClips = phase => (_ixPhases[phase] || []).length > 0;

  const cleanupDef = data.clean_up_post_activity;

  document.getElementById('modelPreview').innerHTML = _IX_STYLE + `
<div id="ixWrap">
  <div id="ixCharBar">
    <label>${isCharTarget ? 'Char A' : 'Character'}</label>
    <select id="ixCharSelect">${charOptions}</select>
    ${isCharTarget ? `
    <label style="color:#fc9">Char B</label>
    <select id="ixTargetCharSelect" style="border-color:#664422">${targetOptions}</select>` : ''}
    ${matchingProps.length ? `
    <label>Prop</label>
    <select id="ixPropSelect">
      <option value="">\u2014 none \u2014</option>
      ${propOptions}
    </select>` : ''}
    ${isCharTarget ? '<span style="font-size:10px;color:#fc9;margin-left:4px">&#x1F465; char&#8209;on&#8209;char</span>' : ''}
  </div>
  <div id="ixCanvas"></div>
  <div id="ixPhaseBar">
    <button class="ixPhaseBtn ixPlayAll" onclick="window._ixPlayAll()" title="Run full sequence">\u25b6 Play All</button>
    <button class="ixPhaseBtn" id="ixBtnStart" onclick="window._ixPlayPhase('start')"
      ${phaseHasClips('start') ? '' : 'disabled'} title="${(_ixPhases.start||[]).join(', ')||'(none)'}">\u25b6 Start</button>
    <button class="ixPhaseBtn" id="ixBtnLoop" onclick="window._ixPlayPhase('loop')"
      ${phaseHasClips('loop') ? '' : 'disabled'} title="${(_ixPhases.loop||[]).join(', ')||'(none)'}">\u21ba Loop</button>
    <button class="ixPhaseBtn" id="ixBtnStop" onclick="window._ixPlayPhase('stop')"
      ${phaseHasClips('stop') ? '' : 'disabled'} title="${(_ixPhases.stop||[]).join(', ')||'(none)'}">\u25a0 Stop</button>
    <button class="ixPhaseBtn" id="ixIdleBtn" onclick="window._ixPlayPhase('idle')">\u2b1c Idle</button>
    <button class="ixPhaseBtn ixAbortBtn" onclick="window._ixAbort()" title="Stop here \u2014 state left as-is">\u26d4 Abort</button>
    <button class="ixPhaseBtn ixResetBtn" onclick="window._ixReset()" title="Stop and return to idle">\u21ba Reset</button>
    <button class="ixPhaseBtn ixReturnBtn" onclick="window._ixReturn()" title="Re-run interaction from start">\u21a9 Return</button>
  </div>
  <div id="ixInfoPanel">
    ${offGrid ? '<div class="ixOffGrid">\u2b1b Off-grid \u2014 no prop needed</div>' : ''}
    ${reqProps.length ? `
    <div class="ixSection">
      <div class="ixSectionTitle">Required prop tags: ${reqProps.map(t => `<span class="ixChip">${t}</span>`).join(' ')}</div>
      ${matchingProps.length === 0 ? '<div class="ixEmptyNote">No matching props found</div>' : ''}
    </div>` : ''}
    ${reqItemCat ? `
    <div class="ixSection">
      <div class="ixSectionTitle">Items \u2014 ${reqItemCat} <span style="color:#556;font-weight:normal;text-transform:none">(check to equip, max 2)</span></div>
      ${matchItems.length ? matchItems.map(([id, item]) => `
      <div class="ixItemRow">
        <input type="checkbox" class="ixItemCb" id="ixCb_${id}" onchange="window._ixToggleItem('${id}')">
        <span class="ixItemLabel" title="${id}">${item.name}</span>
        <span class="ixHandTag" id="ixHand_${id}"></span>
      </div>`).join('') : `<div class="ixEmptyNote">No items for category "${reqItemCat}"</div>`}
    </div>` : (!reqProps.length && !offGrid ? '<div class="ixEmptyNote">No prop or item requirements</div>' : '')}
    ${cleanupDef ? `<div class="ixCleanupNote">\u267b clean_up_post_activity: ${typeof cleanupDef === 'object' ? JSON.stringify(cleanupDef) : cleanupDef}</div>` : ''}
    ${data.target_region ? `<div class="ixTargetRegion">\uD83C\uDFAF Target region: <b>${data.target_region}</b> \u2014 mapped to bone in preview</div>` : ''}
    ${Object.keys(_ixVarDefs).length ? _ixRenderVariables(_ixVarDefs) : ''}
    ${(data.effectiveness_modifiers||[]).length ? _ixRenderModifiers(data.effectiveness_modifiers) : ''}
  </div>
  <div id="ixLog"></div>
</div>`;

  _ixCheckedItems = new Map();
  _ixPhase = null;

  const slot = document.getElementById('ixCanvas');
  previewRenderer.setSize(slot.clientWidth || 400, slot.clientHeight || 240);
  slot.appendChild(previewRenderer.domElement);

  // Phase overlay tag
  const phaseTag = document.createElement('div');
  phaseTag.id = 'ixPhaseTag';
  phaseTag.className = 'idle';
  phaseTag.textContent = 'IDLE';
  slot.appendChild(phaseTag);

  _ixAddLog(`Interaction loaded: ${data.name || '(unnamed)'} — ${(_ixPhases.start||[]).length}×start, ${(_ixPhases.loop||[]).length}×loop, ${(_ixPhases.stop||[]).length}×stop`);

  const ro = new ResizeObserver(entries => {
    const e = entries[0];
    if (!_ixActive) { ro.disconnect(); return; }
    previewRenderer.setSize(e.contentRect.width, e.contentRect.height);
    previewCamera.aspect = e.contentRect.width / (e.contentRect.height || 1);
    previewCamera.updateProjectionMatrix();
  });
  ro.observe(slot);

  const sel = document.getElementById('ixCharSelect');
  if (sel) sel.onchange = e => {
    _ixCharKey = e.target.value;
    _ixClearHeld();
    _ixLoadChar();
  };

  const propSel = document.getElementById('ixPropSelect');
  if (propSel) propSel.onchange = e => {
    _ixPropKey = e.target.value || null;
    _ixLoadProp(_ixPropKey);
  };

  const targetSel = document.getElementById('ixTargetCharSelect');
  if (targetSel) targetSel.onchange = e => {
    _ixTargetCharKey = e.target.value;
    _ixLoadTargetChar();
  };

  _ixLoadChar();
  if (isCharTarget) _ixLoadTargetChar();
  _ixLoadProp(_ixPropKey);
  if (reqItemCat) _ixLoadItem(reqItemCat);
}

function _ixLoadChar() {
  if (!_ixActive) return;
  const tmpl = (definitions.character_templates || {})[_ixCharKey];
  if (!tmpl?.model) { setStatus('Character template has no model path'); return; }
  const charModelPath = resolveModelPath(tmpl);
  if (!charModelPath) { setStatus('Cannot resolve model for ' + _ixCharKey + ' (check meshbank)'); return; }

  if (previewModel) { previewScene.remove(previewModel); previewModel = null; }
  if (previewMixer) { previewMixer.stopAllAction(); previewMixer = null; }
  _ixClips = [];
  _ixClearHeld();

  setStatus('Loading character\u2026');
  previewLoader.load(charModelPath, gltf => {
    if (!_ixActive) return;
    previewModel = gltf.scene;
    previewScene.add(previewModel);
    framePreviewCamera(previewModel);

    _ixClips = gltf.animations || [];
    previewMixer = new THREE.AnimationMixer(previewModel);
    previewBones = [];
    previewModel.traverse(o => { if (o.isBone) previewBones.push(o); });

    const idleClip = _ixFindClip(tmpl.base_animations?.idle || 'idle');
    if (idleClip) previewMixer.clipAction(idleClip).play();

    _ixRefreshPhaseBtns();
    setStatus(`${_ixCharKey} \u2014 ${_ixClips.length} animation clip(s) loaded`);
  }, undefined, err => {
    showPreviewPlaceholder('Character model missing: ' + _ixCharKey);
    setStatus('Character load error: ' + (err.message || err));
  });
}

function _ixLoadTargetChar() {
  if (!_ixActive) return;
  if (_ixTargetModel) { previewScene.remove(_ixTargetModel); _ixTargetModel = null; }
  if (_ixTargetMixer) { _ixTargetMixer.stopAllAction(); _ixTargetMixer = null; }
  _ixTargetClips = [];

  const tmpl = (definitions.character_templates || {})[_ixTargetCharKey];
  if (!tmpl?.model) { _ixAddLog('Target character has no model'); return; }
  const targetModelPath = resolveModelPath(tmpl);
  if (!targetModelPath) { _ixAddLog('Cannot resolve model for target char ' + _ixTargetCharKey); return; }

  previewLoader.load(targetModelPath, gltf => {
    if (!_ixActive) return;
    _ixTargetModel = gltf.scene;
    // Face the primary character — 1.2m away, rotated 180deg
    _ixTargetModel.position.set(0, 0, -1.2);
    _ixTargetModel.rotation.y = Math.PI;
    previewScene.add(_ixTargetModel);

    _ixTargetClips = gltf.animations || [];
    _ixTargetMixer = new THREE.AnimationMixer(_ixTargetModel);

    const idleClip = _ixTargetFindClip(tmpl.base_animations?.idle || 'idle');
    if (idleClip) _ixTargetMixer.clipAction(idleClip).play();

    _ixAddLog('Target char loaded: ' + _ixTargetCharKey + ' (' + _ixTargetClips.length + ' clips)');
    // Place region marker if interaction specifies a target_region
    const curData = (definitions.interaction_templates || {})[currentTemplateId];
    if (curData?.target_region) _ixPlaceTargetRegionMarker(curData.target_region);
  }, undefined, err => _ixAddLog('Target char load error: ' + (err.message || err)));
}

// ── Radius ring ───────────────────────────────────────────────────────────────
function _ixUpdateRadiusRing() {
  if (_ixRadiusRing) { previewScene.remove(_ixRadiusRing); _ixRadiusRing = null; }
  if (!_ixPropMesh) return;
  const cx = _ixPropMesh.position.x, cz = _ixPropMesh.position.z;
  const r  = _ixInteractDist;
  const segs = 64;
  const pts = [];
  for (let i = 0; i <= segs; i++) {
    const a = (i / segs) * Math.PI * 2;
    pts.push(new THREE.Vector3(cx + Math.cos(a) * r, 0.02, cz + Math.sin(a) * r));
  }
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  const mat = new THREE.LineBasicMaterial({ color: 0x44aaff, transparent: true, opacity: 0.55 });
  _ixRadiusRing = new THREE.Line(geo, mat);
  previewScene.add(_ixRadiusRing);
}

// ── Prop drag ─────────────────────────────────────────────────────────────────
function _ixSetupPropDrag(canvas) {
  if (canvas._ixDragBound) return;
  canvas._ixDragBound = true;

  const ndc = e => {
    const r = canvas.getBoundingClientRect();
    return new THREE.Vector2(
      ((e.clientX - r.left) / r.width)  *  2 - 1,
      ((e.clientY - r.top)  / r.height) * -2 + 1
    );
  };

  canvas.addEventListener('mousedown', e => {
    if (!_ixPropMesh || !_ixActive) return;
    _ixDragRay.setFromCamera(ndc(e), previewCamera);
    if (!_ixDragRay.intersectObject(_ixPropMesh, true).length) return;
    e.stopPropagation();
    _ixDragging = true;
    previewControls.enabled = false;
    const hit = new THREE.Vector3();
    _ixDragRay.ray.intersectPlane(_ixDragPlaneY, hit);
    _ixDragOffset.set(_ixPropMesh.position.x - hit.x, 0, _ixPropMesh.position.z - hit.z);
  });

  canvas.addEventListener('mousemove', e => {
    if (!_ixDragging || !_ixPropMesh) return;
    _ixDragRay.setFromCamera(ndc(e), previewCamera);
    const hit = new THREE.Vector3();
    _ixDragRay.ray.intersectPlane(_ixDragPlaneY, hit);
    _ixPropMesh.position.x = hit.x + _ixDragOffset.x;
    _ixPropMesh.position.z = hit.z + _ixDragOffset.z;
    _ixUpdateRadiusRing();
  });

  const end = () => {
    if (!_ixDragging) return;
    _ixDragging = false;
    previewControls.enabled = true;
    if (_ixPropMesh) _ixAddLog('Prop at (' + _ixPropMesh.position.x.toFixed(2) + ', ' + _ixPropMesh.position.z.toFixed(2) + ')');
  };
  canvas.addEventListener('mouseup',    end);
  canvas.addEventListener('mouseleave', end);
}

// ── Load prop (GLB or cylinder placeholder) ───────────────────────────────────
function _ixLoadProp(propKey) {
  if (_ixPropMesh)   { previewScene.remove(_ixPropMesh); _ixPropMesh = null; }
  if (_ixRadiusRing) { previewScene.remove(_ixRadiusRing); _ixRadiusRing = null; }
  if (!propKey) return;

  const tmpl = (definitions.prop_templates || {})[propKey];
  if (!tmpl) return;

  _ixInteractDist = (tmpl.anchors || [])[0]?.distance ?? 1.2;

  const place = obj => {
    _ixPropMesh = obj;
    _ixPropMesh.position.set(0, 0, -1.5);
    previewScene.add(_ixPropMesh);
    _ixUpdateRadiusRing();
    const canvas = document.querySelector('#ixCanvas canvas');
    if (canvas) _ixSetupPropDrag(canvas);
    _ixAddLog('Prop: ' + propKey + ' (reach ' + _ixInteractDist.toFixed(1) + 'm)');
  };

  const mkPlaceholder = () => {
    const geo = new THREE.CylinderGeometry(0.38, 0.38, 1.0, 24);
    const mat = new THREE.MeshStandardMaterial({ color: 0x6688aa, roughness: 0.65 });
    const m = new THREE.Mesh(geo, mat);
    m.position.y = 0.5;
    return m;
  };

  const path = resolveModelPath(tmpl);
  if (path) {
    previewLoader.load(path, gltf => { if (_ixActive) place(gltf.scene); },
      undefined, () => { if (_ixActive) place(mkPlaceholder()); });
  } else {
    place(mkPlaceholder());
  }
}

// ── Load item (GLB or amber cube placeholder) ─────────────────────────────────
function _ixLoadItem(itemCat) {
  if (_ixItemMesh) { previewScene.remove(_ixItemMesh); _ixItemMesh = null; }
  if (!itemCat) return;

  const allItems = definitions.item_templates || {};
  const entry = Object.entries(allItems).find(([, t]) =>
    t.category === itemCat || (Array.isArray(t.categories) && t.categories.includes(itemCat))
  );
  const tmpl = entry?.[1] || null;

  const place = obj => {
    _ixItemMesh = obj;
    _ixItemMesh.position.set(0.5, 1.0, -0.4);
    previewScene.add(_ixItemMesh);
    _ixAddLog('Item: ' + (entry?.[0] || itemCat));
  };

  const mkPlaceholder = () => {
    const geo = new THREE.BoxGeometry(0.25, 0.25, 0.25);
    const mat = new THREE.MeshStandardMaterial({ color: 0xcc9944, roughness: 0.65 });
    return new THREE.Mesh(geo, mat);
  };

  if (tmpl) {
    const path = resolveModelPath(tmpl);
    if (path) {
      previewLoader.load(path, gltf => { if (_ixActive) place(gltf.scene); },
        undefined, () => { if (_ixActive) place(mkPlaceholder()); });
      return;
    }
  }
  place(mkPlaceholder());
}

function _ixTargetFindClip(name) {
  if (!name || !_ixTargetClips.length) return null;
  return _ixTargetClips.find(c => c.name === name)
    || _ixTargetClips.find(c => c.name.toLowerCase() === name.toLowerCase())
    || null;
}

function _ixPlayTargetPhase(phase, targetPhases) {
  if (!_ixTargetMixer || !_ixActive) return;
  const phases = targetPhases && Object.keys(targetPhases).length ? targetPhases : _ixTargetPhases;
  const clipNames = (phases[phase] || []);
  const clip = clipNames.map(n => _ixTargetFindClip(n)).find(Boolean);
  if (!clip) return;
  _ixTargetMixer.stopAllAction();
  const a = _ixTargetMixer.clipAction(clip);
  a.setLoop(phase === 'loop' ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
  a.clampWhenFinished = (phase !== 'loop');
  a.reset().play();
}

function _ixFindClip(name) {
  if (!name || !_ixClips.length) return null;
  return _ixClips.find(c => c.name === name)
    || _ixClips.find(c => c.name.toLowerCase() === name.toLowerCase())
    || null;
}

function _ixRefreshPhaseBtns() {
  ['start', 'loop', 'stop'].forEach(phase => {
    const btn = document.getElementById('ixBtn' + phase.charAt(0).toUpperCase() + phase.slice(1));
    if (!btn) return;
    const clips = (_ixPhases[phase] || []).map(_ixFindClip).filter(Boolean);
    btn.disabled = !clips.length;
    btn.style.opacity = clips.length ? '1' : '';
    btn.title = clips.length ? clips.map(c => c.name).join(', ') : `No matching clips for "${phase}"`;
  });
}

function _ixClearHeld() {
  Object.values(_ixHeldMeshes).forEach(m => { if (m.parent) m.parent.remove(m); });
  _ixHeldMeshes = {};
  _ixCheckedItems = new Map();
  document.querySelectorAll('.ixItemCb').forEach(cb => cb.checked = false);
  document.querySelectorAll('.ixHandTag').forEach(t => { t.textContent = ''; });
}

// ── Phase tag + log ───────────────────────────────────────────────────────────
function _ixSetPhase(name) {
  _ixPhase = name;
  const tag = document.getElementById('ixPhaseTag');
  if (tag) {
    tag.textContent = name ? name.toUpperCase() : 'IDLE';
    tag.className = name || 'idle';
  }
}

function _ixAddLog(msg, phaseClass) {
  const log = document.getElementById('ixLog');
  if (!log) return;
  const now = new Date();
  const ts = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`;
  const entry = document.createElement('div');
  entry.className = 'ixLogEntry';
  const cls = phaseClass ? ` ixLogPhase ${phaseClass}` : '';
  entry.innerHTML = `<span class="ixLogTs">${ts}</span><span class="${cls.trim()}">${msg}</span>`;
  log.insertBefore(entry, log.firstChild);
  while (log.children.length > 40) log.removeChild(log.lastChild);
}

function _ixUpdateHandTags() {
  document.querySelectorAll('.ixHandTag').forEach(t => { t.textContent = ''; });
  for (const [slot, itemId] of _ixCheckedItems) {
    const tag = document.getElementById('ixHand_' + itemId);
    if (tag) tag.textContent = slot === 'right_hand' ? 'R' : 'L';
  }
}


// ── Abort / Reset / Return ────────────────────────────────────────────────────
window._ixAbort = function() {
  if (!_ixActive) return;
  if (_ixPlayTimeout) { clearTimeout(_ixPlayTimeout); _ixPlayTimeout = null; }
  if (previewMixer) previewMixer.stopAllAction();
  if (_ixTargetMixer) _ixTargetMixer.stopAllAction();
  document.querySelectorAll('.ixPhaseBtn').forEach(b => b.classList.remove('active'));
  _ixSetPhase('aborted');
  _ixAddLog('Interaction aborted — state left as-is', 'aborted');
};

window._ixReset = function() {
  if (!_ixActive) return;
  if (_ixPlayTimeout) { clearTimeout(_ixPlayTimeout); _ixPlayTimeout = null; }
  if (previewMixer) previewMixer.stopAllAction();
  if (_ixTargetMixer) _ixTargetMixer.stopAllAction();
  document.querySelectorAll('.ixPhaseBtn').forEach(b => b.classList.remove('active'));
  _ixSetPhase('idle');
  _ixClearHeld();
  const tmpl = (definitions.character_templates || {})[_ixCharKey];
  const clip = _ixFindClip(tmpl?.base_animations?.idle || 'idle');
  if (clip && previewMixer) {
    previewMixer.clipAction(clip).play();
    document.getElementById('ixIdleBtn')?.classList.add('active');
  }
  if (_ixTargetMixer) {
    const tTmpl = (definitions.character_templates || {})[_ixTargetCharKey];
    const tClip = _ixTargetFindClip(tTmpl?.base_animations?.idle || 'idle');
    if (tClip) _ixTargetMixer.clipAction(tClip).play();
  }
  _ixAddLog('Reset — returned to idle');
};

window._ixReturn = function() {
  if (!_ixActive) return;
  _ixAddLog('Returning to start of interaction...');
  window._ixPlayAll();
};

// ── Phase playback ─────────────────────────────────────────────────────────────
window._ixPlayPhase = function(phase) {
  if (!previewMixer || !_ixActive) return;
  previewMixer.stopAllAction();
  document.querySelectorAll('.ixPhaseBtn').forEach(b => b.classList.remove('active'));

  if (phase === 'idle') {
    const tmpl = (definitions.character_templates || {})[_ixCharKey];
    const clip = _ixFindClip(tmpl?.base_animations?.idle || 'idle');
    if (clip) previewMixer.clipAction(clip).play();
    if (_ixTargetMixer) {
      _ixTargetMixer.stopAllAction();
      const tTmpl = (definitions.character_templates || {})[_ixTargetCharKey];
      const tClip = _ixTargetFindClip(tTmpl?.base_animations?.idle || 'idle');
      if (tClip) _ixTargetMixer.clipAction(tClip).play();
    }
    document.getElementById('ixIdleBtn')?.classList.add('active');
    _ixSetPhase('idle');
    _ixAddLog('Idle animation playing');
    return;
  }

  const clips = (_ixPhases[phase] || []).map(_ixFindClip).filter(Boolean);
  if (!clips.length) {
    _ixAddLog('Phase "' + phase + '" — no matching clips found');
    setStatus('No clips found for "' + phase + '" phase');
    return;
  }

  const action = previewMixer.clipAction(clips[0]);
  action.setLoop(phase === 'loop' ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
  action.clampWhenFinished = (phase !== 'loop');
  action.reset().play();

  // Also fire target_animations on the second character
  if (_ixTargetMixer) _ixPlayTargetPhase(phase, _ixPhases._target || {});

  const btnId = 'ixBtn' + phase.charAt(0).toUpperCase() + phase.slice(1);
  document.getElementById(btnId)?.classList.add('active');
  _ixSetPhase(phase);
  _ixAddLog('Phase: ' + phase + ' — clip "' + clips[0].name + '" (' + clips[0].duration.toFixed(2) + 's)', phase);
  setStatus(phase + ': "' + clips[0].name + '"');
};

window._ixPlayAll = function() {
  if (!previewMixer || !_ixActive) return;
  if (_ixPlayTimeout) { clearTimeout(_ixPlayTimeout); _ixPlayTimeout = null; }
  previewMixer.stopAllAction();
  if (_ixTargetMixer) _ixTargetMixer.stopAllAction();
  document.querySelectorAll('.ixPhaseBtn').forEach(b => b.classList.remove('active'));

  const startClips = (_ixPhases.start || []).map(_ixFindClip).filter(Boolean);
  const loopClips  = (_ixPhases.loop  || []).map(_ixFindClip).filter(Boolean);
  const stopClips  = (_ixPhases.stop  || []).map(_ixFindClip).filter(Boolean);
  const targetPhases = _ixPhases._target || {};

  _ixAddLog('Play All — start:' + startClips.length + ' loop:' + loopClips.length + ' stop:' + stopClips.length);

  function playClip(clip, loop) {
    if (!previewMixer) return clip.duration;
    previewMixer.stopAllAction();
    const a = previewMixer.clipAction(clip);
    a.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
    a.clampWhenFinished = !loop;
    a.reset().play();
    return clip.duration;
  }

  let delay = 0;

  if (startClips.length) {
    const dur = playClip(startClips[0], false) * 1000;
    if (_ixTargetMixer) _ixPlayTargetPhase('start', targetPhases);
    document.getElementById('ixBtnStart')?.classList.add('active');
    _ixSetPhase('start');
    _ixAddLog('Phase: start — "' + startClips[0].name + '" (' + startClips[0].duration.toFixed(2) + 's)', 'start');
    delay += dur;
  }

  const afterStart = delay;

  if (loopClips.length) {
    _ixPlayTimeout = setTimeout(() => {
      if (!_ixActive) return;
      document.querySelectorAll('.ixPhaseBtn').forEach(b => b.classList.remove('active'));
      document.getElementById('ixBtnLoop')?.classList.add('active');
      playClip(loopClips[0], true);
      if (_ixTargetMixer) _ixPlayTargetPhase('loop', targetPhases);
      _ixSetPhase('loop');
      _ixAddLog('Phase: loop — "' + loopClips[0].name + '" (3s preview)', 'loop');
      _ixPlayTimeout = setTimeout(() => {
        if (!_ixActive) return;
        document.querySelectorAll('.ixPhaseBtn').forEach(b => b.classList.remove('active'));
        if (stopClips.length) {
          const dur2 = playClip(stopClips[0], false) * 1000;
          if (_ixTargetMixer) _ixPlayTargetPhase('stop', targetPhases);
          document.getElementById('ixBtnStop')?.classList.add('active');
          _ixSetPhase('stop');
          _ixAddLog('Phase: stop — "' + stopClips[0].name + '" (' + stopClips[0].duration.toFixed(2) + 's)', 'stop');
          _ixPlayTimeout = setTimeout(() => {
            if (!_ixActive) return;
            window._ixPlayPhase('idle');
            _ixAddLog('Sequence complete');
          }, dur2);
        } else {
          window._ixPlayPhase('idle');
          _ixAddLog('Sequence complete (no stop phase)');
        }
      }, 3000);
    }, afterStart);
  } else if (stopClips.length) {
    _ixPlayTimeout = setTimeout(() => {
      if (!_ixActive) return;
      document.querySelectorAll('.ixPhaseBtn').forEach(b => b.classList.remove('active'));
      const dur2 = playClip(stopClips[0], false) * 1000;
      if (_ixTargetMixer) _ixPlayTargetPhase('stop', targetPhases);
      document.getElementById('ixBtnStop')?.classList.add('active');
      _ixSetPhase('stop');
      _ixAddLog('Phase: stop — "' + stopClips[0].name + '" (' + stopClips[0].duration.toFixed(2) + 's)', 'stop');
      _ixPlayTimeout = setTimeout(() => {
        if (!_ixActive) return;
        window._ixPlayPhase('idle');
        _ixAddLog('Sequence complete');
      }, dur2);
    }, afterStart);
  } else if (!startClips.length) {
    _ixAddLog('No animation clips defined for any phase');
    setStatus('No animation clips found for any phase');
  }
};

// ── Item checkbox equip ────────────────────────────────────────────────────────
window._ixToggleItem = function(itemId) {
  if (!_ixActive) return;

  let currentSlot = null;
  for (const [slot, id] of _ixCheckedItems) {
    if (id === itemId) { currentSlot = slot; break; }
  }

  const cb = document.getElementById('ixCb_' + itemId);

  if (currentSlot) {
    const mesh = _ixHeldMeshes[currentSlot];
    if (mesh && mesh.parent) mesh.parent.remove(mesh);
    delete _ixHeldMeshes[currentSlot];
    _ixCheckedItems.delete(currentSlot);
    if (cb) cb.checked = false;
    _ixUpdateHandTags();
    _ixAddLog('Unequipped "' + itemId + '" from ' + currentSlot);
    return;
  }

  const freeSlot = !_ixCheckedItems.has('right_hand') ? 'right_hand'
                 : !_ixCheckedItems.has('left_hand')  ? 'left_hand'
                 : null;
  if (!freeSlot) {
    if (cb) cb.checked = false;
    setStatus('Both hands are full — uncheck an item first');
    _ixAddLog('Both hands full — uncheck an item first');
    return;
  }
  if (!previewModel) {
    if (cb) cb.checked = false;
    _ixAddLog('No character loaded — load a character first');
    return;
  }

  const boneName = freeSlot === 'right_hand' ? 'hand_r' : 'hand_l';
  let bone = null;
  previewModel.traverse(o => {
    if (o.isBone && o.name.toLowerCase() === boneName.toLowerCase()) bone = o;
  });

  const geo = new THREE.BoxGeometry(0.12, 0.12, 0.12);
  const mat = new THREE.MeshStandardMaterial({ color: 0xcc9944, roughness: 0.6 });
  const mesh = new THREE.Mesh(geo, mat);

  if (bone) {
    bone.add(mesh);
    _ixAddLog('Equipped "' + itemId + '" in ' + freeSlot + ' (bone: ' + bone.name + ')');
  } else {
    mesh.position.set(freeSlot === 'right_hand' ? 0.55 : -0.55, 1.05, 0.3);
    previewScene.add(mesh);
    _ixAddLog('Equipped "' + itemId + '" in ' + freeSlot + ' (bone "' + boneName + '" not found - floating)');
  }

  _ixHeldMeshes[freeSlot] = mesh;
  _ixCheckedItems.set(freeSlot, itemId);
  if (cb) cb.checked = true;
  _ixUpdateHandTags();
};

// =====================================================
// INTERACTION PREVIEW HELPERS (body region / variables)
// =====================================================

function _ixPlaceTargetRegionMarker(regionName) {
  // Clear existing markers
  _ixTargetRegionMarkers.forEach(m => { if (m.parent) m.parent.remove(m); });
  _ixTargetRegionMarkers = [];
  if (!regionName || !_ixTargetModel) return;

  const boneNames = [];
  _ixTargetModel.traverse(o => { if (o.isBone) boneNames.push(o.name); });

  const matched = resolveBodyRegionBones(regionName, boneNames);
  if (!matched.length) {
    _ixAddLog('Target region "' + regionName + '" - no bones matched (available: ' + boneNames.slice(0,6).join(', ') + '..)');
    return;
  }

  const geo = new THREE.SphereGeometry(0.06, 8, 8);
  const mat = new THREE.MeshBasicMaterial({ color: 0xff3322, transparent: true, opacity: 0.85 });

  matched.forEach(boneName => {
    let bone = null;
    _ixTargetModel.traverse(o => { if (o.isBone && o.name === boneName) bone = o; });
    if (!bone) return;
    const mesh = new THREE.Mesh(geo, mat);
    bone.add(mesh);
    _ixTargetRegionMarkers.push(mesh);
  });

  _ixAddLog('Target region "' + regionName + '" -> ' + matched.join(', ') + ' (' + matched.length + ' marker' + (matched.length > 1 ? 's' : '') + ')');
}

function _ixRenderVariables(vars) {
  if (!vars || !Object.keys(vars).length) return '';
  let html = '<div class="ixSection"><div class="ixSectionTitle">Variables</div>';
  for (const [key, def] of Object.entries(vars)) {
    html += '<div class="ixVarRow">';
    html += '<span class="ixVarKey">' + key + '</span>';
    if (def.type === 'select' && def.options) {
      html += '<select class="ixVarSelect" data-var="' + key + '" onchange="window._ixSetVar(this)">';
      for (const opt of def.options) {
        const sel = opt === (def.default || def.options[0]) ? ' selected' : '';
        html += '<option value="' + opt + '"' + sel + '>' + opt + '</option>';
      }
      html += '</select>';
    } else if (def.type === 'bool') {
      const chk = def.default ? ' checked' : '';
      html += '<input type="checkbox" class="ixVarCheck" data-var="' + key + '" onchange="window._ixSetVar(this)"' + chk + '>';
    } else if (def.type === 'number') {
      const minAttr = (def.min != null) ? ' min="' + def.min + '"' : '';
      const maxAttr = (def.max != null) ? ' max="' + def.max + '"' : '';
      html += '<input type="number" class="ixVarNum" data-var="' + key + '" value="' + (def.default || 0) + '"' + minAttr + maxAttr + ' onchange="window._ixSetVar(this)">';
    } else {
      html += '<input type="text" class="ixVarText" data-var="' + key + '" value="' + (def.default || '') + '" oninput="window._ixSetVar(this)">';
    }
    html += '<span class="ixVarBtnRow">';
    if (def.randomizable) html += '<button class="ixVarBtn" onclick="window._ixRandomizeVar(&quot;' + key + '&quot;)" title="Randomize">&#x1F3B2;</button>';
    if (def.ai_choose)   html += '<button class="ixVarBtn" title="AI will choose at runtime">&#x1F916;</button>';
    html += '</span></div>';
  }
  html += '</div>';
  return html;
}

function _ixRenderModifiers(mods) {
  if (!mods || !mods.length) return '';
  let html = '<div class="ixSection"><div class="ixSectionTitle">Effectiveness Modifiers</div>';
  for (const m of mods) {
    html += '<div class="ixModRow"><span class="ixModCond">' + (m.condition || '') + '</span>';
    if (m.multiplier != null) html += '<span class="ixModVal">x' + m.multiplier + '</span>';
    if (m.outcome)            html += '<span class="ixModVal">' + m.outcome + '</span>';
    html += '</div>';
  }
  html += '</div>';
  return html;
}

window._ixSetVar = function(el) {
  const key = el.dataset.var;
  const val = el.type === 'checkbox' ? el.checked : (el.type === 'number' ? Number(el.value) : el.value);
  _ixVarValues[key] = val;
  _ixAddLog('Var "' + key + '" = ' + JSON.stringify(val));
};

window._ixRandomizeVar = function(key) {
  const def = _ixVarDefs[key];
  if (!def) return;
  let val;
  if (def.type === 'select' && def.options) {
    val = def.options[Math.floor(Math.random() * def.options.length)];
  } else if (def.type === 'number') {
    const lo = def.min || 0, hi = def.max || 10;
    val = Math.floor(Math.random() * (hi - lo + 1)) + lo;
  } else if (def.type === 'bool') {
    val = Math.random() > 0.5;
  } else { return; }
  _ixVarValues[key] = val;
  const el = document.querySelector('[data-var="' + key + '"]');
  if (el) { el.type === 'checkbox' ? (el.checked = val) : (el.value = val); }
  _ixAddLog('Var "' + key + '" randomized = ' + JSON.stringify(val));
};


// =====================================================
// SOCIOECONOMICS TAB
// =====================================================

const FAME_LABELS = ['','Local (neighborhood)','City-wide','Regional','National','International'];
const CATEGORY_LABELS = {
  politician: '🏛 Politician',
  government_official: '🏢 Gov. Official',
  law_enforcement: '🚔 Law Enforcement',
  business_leader: '💼 Business Leader',
  celebrity: '🎬 Celebrity',
  journalist: '📰 Journalist',
  civic_leader: '🤝 Civic Leader',
};

let _socioActiveSub = 'stats'; // 'stats' | 'government' | 'figures'
let _socioActiveFigure = null;

function renderSocioeconomicsPanel() {
  // Hide generic editor, show custom socio panel
  const editorEl = document.getElementById('jsonEditor');
  const titleEl  = document.getElementById('editorTitle');
  let panel = document.getElementById('socioPanel');

  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'socioPanel';
    panel.style.cssText = 'flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;';
    editorEl.parentNode.insertBefore(panel, editorEl);
  }
  editorEl.style.display = 'none';
  panel.style.display    = 'flex';
  titleEl.textContent    = 'Socioeconomics';

  // Sub-nav
  panel.innerHTML = `
    <div style="display:flex;gap:6px;margin-bottom:4px;">
      ${['stats','government','figures'].map(s => `
        <button onclick="window._socioSub('${s}')"
          style="flex:1;padding:6px;font-size:12px;background:${_socioActiveSub===s?'#3a6ea8':'#2e3640'};color:#fff;border:1px solid #555;cursor:pointer;border-radius:3px">
          ${s==='stats'?'📊 Statistics':s==='government'?'🏛 Government':'👤 Public Figures'}
        </button>`).join('')}
    </div>
    <div id="socioContent"></div>`;

  _renderSocioContent();
}

window._socioSub = function(sub) {
  _socioActiveSub = sub;
  _renderSocioContent();
};

function _renderSocioContent() {
  const el = document.getElementById('socioContent');
  if (!el) return;
  if (_socioActiveSub === 'stats')       _renderSocioStats(el);
  else if (_socioActiveSub === 'government') _renderSocioGov(el);
  else _renderSocioFigures(el);
}

// ── Statistics panel ──────────────────────────────────────────────────────
function _renderSocioStats(el) {
  const cfg = definitions.community_stats_config || {};
  let html = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <span style="font-size:12px;color:#aaa;">Configure baseline values and daily ±drift for each statistic.</span>
      <button onclick="window._socioSaveStats()" style="padding:5px 12px;background:#2a6a2a;color:#fff;border:none;cursor:pointer;border-radius:3px">💾 Save Stats</button>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
      <thead>
        <tr style="color:#aaa;border-bottom:1px solid #444;">
          <th style="text-align:left;padding:4px 6px;width:36%">Statistic</th>
          <th style="text-align:right;padding:4px 6px;width:14%">Value</th>
          <th style="text-align:right;padding:4px 6px;width:10%">Min</th>
          <th style="text-align:right;padding:4px 6px;width:10%">Max</th>
          <th style="text-align:right;padding:4px 6px;width:14%">±Drift/day</th>
          <th style="text-align:left;padding:4px 6px;width:16%">Unit</th>
        </tr>
      </thead>
      <tbody>`;

  Object.entries(cfg).forEach(([key, stat]) => {
    html += `
      <tr style="border-bottom:1px solid #2a2f36;" data-stat-key="${key}">
        <td style="padding:4px 6px;color:#ccc;">${stat.label || key}</td>
        <td style="padding:2px 4px;"><input type="number" data-stat="${key}" data-field="value" value="${stat.value}" step="any"
          style="width:80px;background:#1b1f24;color:#fff;border:1px solid #444;padding:2px 4px;text-align:right;font-size:11px;"></td>
        <td style="padding:2px 4px;"><input type="number" data-stat="${key}" data-field="min" value="${stat.min}" step="any"
          style="width:60px;background:#1b1f24;color:#fff;border:1px solid #444;padding:2px 4px;text-align:right;font-size:11px;"></td>
        <td style="padding:2px 4px;"><input type="number" data-stat="${key}" data-field="max" value="${stat.max}" step="any"
          style="width:60px;background:#1b1f24;color:#fff;border:1px solid #444;padding:2px 4px;text-align:right;font-size:11px;"></td>
        <td style="padding:2px 4px;"><input type="number" data-stat="${key}" data-field="drift_range" value="${stat.drift_range}" step="any" min="0"
          style="width:70px;background:#1b1f24;color:#fff;border:1px solid #444;padding:2px 4px;text-align:right;font-size:11px;"></td>
        <td style="padding:4px 6px;color:#888;font-size:11px;">${stat.unit || ''}</td>
      </tr>`;
  });

  html += '</tbody></table>';
  el.innerHTML = html;
}

window._socioSaveStats = function() {
  const inputs = document.querySelectorAll('#socioContent input[data-stat]');
  inputs.forEach(inp => {
    const key   = inp.dataset.stat;
    const field = inp.dataset.field;
    if (!definitions.community_stats_config) definitions.community_stats_config = {};
    if (!definitions.community_stats_config[key]) definitions.community_stats_config[key] = {};
    definitions.community_stats_config[key][field] = parseFloat(inp.value) || 0;
  });
  saveDefinitions();
  document.getElementById('statusBar').textContent = 'Statistics saved.';
};

// ── Government panel ──────────────────────────────────────────────────────
function _renderSocioGov(el) {
  const gov = definitions.government || {};
  const pf  = definitions.public_figures || {};

  const pfOptions = (role) => Object.entries(pf)
    .filter(([,v]) => !role || v.role === role || v.category === role)
    .map(([k,v]) => `<option value="${k}" ${gov[role+'_id']===k||gov.mayor_id===k&&role==='mayor'||gov.police_chief_id===k&&role==='police_chief'?'selected':''}>${v.name} (${v.title})</option>`)
    .join('');

  const allPfOptions = (selected) => Object.entries(pf)
    .map(([k,v]) => `<option value="${k}" ${selected===k?'selected':''}>${v.name}</option>`)
    .join('');

  el.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">City Name</label>
        <input id="gov_city_name" value="${gov.city_name||''}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
        <label style="color:#aaa;font-size:11px;display:block;margin:8px 0 4px;">State / Region</label>
        <input id="gov_state" value="${gov.state||''}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
        <label style="color:#aaa;font-size:11px;display:block;margin:8px 0 4px;">Government Type</label>
        <select id="gov_type" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
          ${['mayor-council','council-manager','commission','strong-mayor'].map(t=>`<option value="${t}" ${gov.government_type===t?'selected':''}>${t}</option>`).join('')}
        </select>
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">Party Majority</label>
        <select id="gov_party" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
          ${['republican','democrat','independent','coalition'].map(p=>`<option value="${p}" ${gov.party_majority===p?'selected':''}>${p.charAt(0).toUpperCase()+p.slice(1)}</option>`).join('')}
        </select>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:8px;">
          <div>
            <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">Rep. Seats</label>
            <input id="gov_rep" type="number" value="${gov.republican_seats||0}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
          </div>
          <div>
            <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">Dem. Seats</label>
            <input id="gov_dem" type="number" value="${gov.democrat_seats||0}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
          </div>
          <div>
            <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">Ind. Seats</label>
            <input id="gov_ind" type="number" value="${gov.independent_seats||0}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
          </div>
        </div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px;">
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">Last Election Date</label>
        <input id="gov_last_elec" type="date" value="${gov.last_election_date||''}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">Next Election Date</label>
        <input id="gov_next_elec" type="date" value="${gov.next_election_date||''}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px;">
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">Mayor</label>
        <select id="gov_mayor" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
          <option value="">— None —</option>
          ${Object.entries(pf).map(([k,v])=>`<option value="${k}" ${gov.mayor_id===k?'selected':''}>${v.name} (${v.title})</option>`).join('')}
        </select>
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">Police Chief</label>
        <select id="gov_chief" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
          <option value="">— None —</option>
          ${Object.entries(pf).map(([k,v])=>`<option value="${k}" ${gov.police_chief_id===k?'selected':''}>${v.name} (${v.title})</option>`).join('')}
        </select>
      </div>
    </div>
    <div style="margin-top:12px;">
      <label style="color:#aaa;font-size:11px;display:block;margin-bottom:4px;">City Budget ($)</label>
      <input id="gov_budget" type="number" value="${gov.city_budget||0}" style="width:220px;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
      <label style="color:#aaa;font-size:11px;display:block;margin:8px 0 4px;">Surplus / Deficit ($)</label>
      <input id="gov_surplus" type="number" value="${gov.budget_surplus_deficit||0}" style="width:220px;background:#1b1f24;color:#fff;border:1px solid #444;padding:5px;">
    </div>
    <button onclick="window._socioSaveGov()" style="margin-top:12px;padding:6px 16px;background:#2a6a2a;color:#fff;border:none;cursor:pointer;border-radius:3px">💾 Save Government</button>
  `;
}

window._socioSaveGov = function() {
  if (!definitions.government) definitions.government = {};
  const g = definitions.government;
  g.city_name              = document.getElementById('gov_city_name').value;
  g.state                  = document.getElementById('gov_state').value;
  g.government_type        = document.getElementById('gov_type').value;
  g.party_majority         = document.getElementById('gov_party').value;
  g.republican_seats       = parseInt(document.getElementById('gov_rep').value)||0;
  g.democrat_seats         = parseInt(document.getElementById('gov_dem').value)||0;
  g.independent_seats      = parseInt(document.getElementById('gov_ind').value)||0;
  g.last_election_date     = document.getElementById('gov_last_elec').value;
  g.next_election_date     = document.getElementById('gov_next_elec').value;
  g.mayor_id               = document.getElementById('gov_mayor').value;
  g.police_chief_id        = document.getElementById('gov_chief').value;
  g.city_budget            = parseInt(document.getElementById('gov_budget').value)||0;
  g.budget_surplus_deficit = parseInt(document.getElementById('gov_surplus').value)||0;
  saveDefinitions();
  document.getElementById('statusBar').textContent = 'Government saved.';
};

// ── Public Figures panel ──────────────────────────────────────────────────
function _renderSocioFigures(el) {
  const pf = definitions.public_figures || {};

  let listHtml = `
    <div style="display:flex;gap:6px;margin-bottom:8px;">
      <button onclick="window._socioNewFigure()" style="padding:5px 10px;background:#2a5a8a;color:#fff;border:none;cursor:pointer;border-radius:3px;font-size:12px;">+ New Figure</button>
      <span style="font-size:11px;color:#888;align-self:center;">${Object.keys(pf).length} public figure(s)</span>
    </div>
    <div style="display:flex;gap:8px;">
      <div style="width:200px;flex-shrink:0;border-right:1px solid #333;padding-right:8px;">`;

  const cats = {};
  Object.entries(pf).forEach(([k,v]) => {
    const cat = v.category || 'other';
    (cats[cat] = cats[cat]||[]).push([k,v]);
  });

  Object.entries(cats).forEach(([cat, items]) => {
    listHtml += `<div style="color:#88aacc;font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:0.5px;margin:6px 0 2px;padding-left:2px;">${CATEGORY_LABELS[cat]||cat}</div>`;
    items.forEach(([k,v]) => {
      const active = _socioActiveFigure === k;
      listHtml += `
        <div onclick="window._socioSelectFigure('${k}')"
          style="padding:5px 7px;cursor:pointer;font-size:12px;border-radius:3px;margin-bottom:2px;
                 background:${active?'#3a5a7a':'#2a2f36'};color:${active?'#fff':'#ccc'};
                 display:flex;justify-content:space-between;align-items:center;">
          <span>${v.name}</span>
          <span style="font-size:10px;color:#888;">★${v.fame_level||1}</span>
        </div>`;
    });
  });

  listHtml += `</div><div style="flex:1;" id="socioFigureDetail">`;

  if (_socioActiveFigure && pf[_socioActiveFigure]) {
    listHtml += _buildFigureForm(_socioActiveFigure, pf[_socioActiveFigure]);
  } else {
    listHtml += `<div style="color:#666;font-size:12px;padding:20px;">Select a figure to edit</div>`;
  }

  listHtml += '</div></div>';
  el.innerHTML = listHtml;
}

function _buildFigureForm(id, fig) {
  const controversies = (fig.controversial_subjects || []).join('\n');
  const tags = (fig.tags || []).join(', ');
  return `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
      <b style="font-size:14px;">${fig.name}</b>
      <button onclick="window._socioDeleteFigure('${id}')" style="padding:3px 8px;background:#6a2a2a;color:#fff;border:none;cursor:pointer;border-radius:3px;font-size:11px;">Delete</button>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px;">
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Full Name</label>
        <input id="fig_name" value="${fig.name||''}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Title / Role Label</label>
        <input id="fig_title" value="${fig.title||''}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Age</label>
        <input id="fig_age" type="number" value="${fig.age||''}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Category</label>
        <select id="fig_cat" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
          ${Object.keys(CATEGORY_LABELS).map(c=>`<option value="${c}" ${fig.category===c?'selected':''}>${CATEGORY_LABELS[c]}</option>`).join('')}
        </select>
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Role ID</label>
        <input id="fig_role" value="${fig.role||''}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Party</label>
        <select id="fig_party" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
          <option value="">None / Independent</option>
          ${['republican','democrat','independent','green','libertarian'].map(p=>`<option value="${p}" ${fig.party===p?'selected':''}>${p.charAt(0).toUpperCase()+p.slice(1)}</option>`).join('')}
        </select>
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Approval Rating (0–1)</label>
        <input id="fig_approval" type="number" step="0.01" min="0" max="1" value="${fig.approval_rating||0.5}"
          style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Fame Level (1–5)</label>
        <select id="fig_fame" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
          ${[1,2,3,4,5].map(n=>`<option value="${n}" ${fig.fame_level===n?'selected':''}>★${n} — ${FAME_LABELS[n]}</option>`).join('')}
        </select>
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Influence Power (0–1)</label>
        <input id="fig_influence" type="number" step="0.01" min="0" max="1" value="${fig.influence_power||0.5}"
          style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
      </div>
      <div>
        <label style="color:#aaa;font-size:11px;display:block;margin-bottom:3px;">Credibility (0–1)</label>
        <input id="fig_cred" type="number" step="0.01" min="0" max="1" value="${fig.credibility||0.5}"
          style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;">
      </div>
    </div>
    <label style="color:#aaa;font-size:11px;display:block;margin:8px 0 3px;">Bio</label>
    <textarea id="fig_bio" rows="4" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;font-size:12px;resize:vertical;">${fig.bio||''}</textarea>
    <label style="color:#aaa;font-size:11px;display:block;margin:8px 0 3px;">Controversial Subjects <span style="color:#666;">(one per line)</span></label>
    <textarea id="fig_controversies" rows="3" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;font-size:12px;resize:vertical;">${controversies}</textarea>
    <label style="color:#aaa;font-size:11px;display:block;margin:8px 0 3px;">Tags <span style="color:#666;">(comma-separated)</span></label>
    <input id="fig_tags" value="${tags}" style="width:100%;background:#1b1f24;color:#fff;border:1px solid #444;padding:4px;font-size:12px;">
    <div style="margin-top:10px;display:flex;gap:8px;">
      <button onclick="window._socioSaveFigure('${id}')"
        style="padding:6px 16px;background:#2a6a2a;color:#fff;border:none;cursor:pointer;border-radius:3px;">💾 Save</button>
    </div>`;
}

window._socioSelectFigure = function(id) {
  _socioActiveFigure = id;
  _renderSocioContent();
};

window._socioSaveFigure = function(id) {
  if (!definitions.public_figures) definitions.public_figures = {};
  const existing = definitions.public_figures[id] || {};
  definitions.public_figures[id] = {
    ...existing,
    id,
    name:                  document.getElementById('fig_name').value,
    title:                 document.getElementById('fig_title').value,
    age:                   parseInt(document.getElementById('fig_age').value)||0,
    category:              document.getElementById('fig_cat').value,
    role:                  document.getElementById('fig_role').value,
    party:                 document.getElementById('fig_party').value || null,
    approval_rating:       parseFloat(document.getElementById('fig_approval').value)||0.5,
    fame_level:            parseInt(document.getElementById('fig_fame').value)||1,
    influence_power:       parseFloat(document.getElementById('fig_influence').value)||0.5,
    credibility:           parseFloat(document.getElementById('fig_cred').value)||0.5,
    bio:                   document.getElementById('fig_bio').value,
    controversial_subjects: document.getElementById('fig_controversies').value
      .split('\n').map(s=>s.trim()).filter(Boolean),
    tags:                  document.getElementById('fig_tags').value
      .split(',').map(s=>s.trim()).filter(Boolean),
  };
  saveDefinitions();
  _renderSocioContent();
  document.getElementById('statusBar').textContent = `Figure "${definitions.public_figures[id].name}" saved.`;
};

window._socioNewFigure = function() {
  const id = 'pf_' + Date.now().toString(36);
  if (!definitions.public_figures) definitions.public_figures = {};
  definitions.public_figures[id] = {
    id, name:'New Figure', title:'', role:'', category:'politician',
    age:40, party:null, bio:'', approval_rating:0.5, fame_level:1,
    influence_power:0.5, credibility:0.5, controversial_subjects:[], tags:[],
    scope:'domestic', importance:0.5,
  };
  _socioActiveFigure = id;
  _renderSocioContent();
};

window._socioDeleteFigure = function(id) {
  if (!confirm('Delete this figure?')) return;
  delete definitions.public_figures[id];
  if (_socioActiveFigure === id) _socioActiveFigure = null;
  saveDefinitions();
  _renderSocioContent();
};

// (renderTemplateList visibility patched inline below)
