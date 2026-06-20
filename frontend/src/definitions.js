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
  product_templates: {},
  appliance_templates: {},
  vehicle_templates: {},
  service_templates: {},
  storage_templates: {},
  social_templates: {},
  need_templates: {},
  trait_templates: {},
  job_templates: {},
  company_templates: {}
};

const tabs = [
  "prop_templates",
  "character_templates",
  "floorplan_templates",
  "interaction_templates",
  "activity_templates",
  "recipe_templates",
  "product_templates",
  "appliance_templates",
  "vehicle_templates",
  "service_templates",
  "storage_templates",
  "material_templates",
  "tile_templates",
  "item_templates",
  "social_templates",
  "need_templates",
  "trait_templates",
  "job_templates",
  "company_templates"
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
  if (currentTab === 'material_templates') {
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

  activity_templates: {
    name: "New Activity",
    priority: 50,
    conditions: {
      hour_range: [0, 24]
    },
    steps: []
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

  recipe_templat