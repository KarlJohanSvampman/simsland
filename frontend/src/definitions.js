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

let previewModel = null;
let previewMixer = null;
let previewBones = [];

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

  const path = resolveModelPath(data);
  if (path) {
    loadPreviewModel(path);
  } else {
    clearPreviewModel();
  }

  renderTemplateList();
}

// =====================================================
// CLEAR PREVIEW
// =====================================================

function clearPreviewModel() {

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
// TEMPLATE CRUD
// =====================================================

window.createTemplate = function(){

  const id = prompt("Template ID");

  if(!id) return;

  if(!definitions[currentTab]){

    definitions[currentTab] = {};
  }

  definitions[currentTab][id] = {};

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
// ASSET BROWSER
// =====================================================

function renderAssets(){

  assetBrowser.innerHTML = '';

  Object.entries(assets).forEach(([type,list])=>{

    const title = document.createElement('h4');
    title.textContent = type;

    assetBrowser.appendChild(title);

    list.forEach(path=>{

      const row = document.createElement('div');

      row.className = 'assetRow';
      row.textContent = path;

      row.onclick = ()=>{

        loadPreviewModel(path);

        insertModelIntoEditor(path);
      };

      assetBrowser.appendChild(row);
    });
  });
}

// =====================================================
// INSERT MODEL PATH
// =====================================================

function insertModelIntoEditor(path){

  try {

    const data = JSON.parse(jsonEditor.value || '{}');

    data.model = path;

    jsonEditor.value = JSON.stringify(
      data,
      null,
      2
    );

  } catch(err){

    console.warn(err);
  }
}

// =====================================================
// PREVIEW MODEL
// =====================================================

async function loadPreviewModel(path){

  if(previewModel){
    previewScene.remove(previewModel);
  }

  animationList.innerHTML = '';
  console.log(
      "Loading preview:",
      path
  );
  previewLoader.load(path,(gltf)=>{

    previewModel = gltf.scene;
    previewBones =
      extractBones(
        previewModel
      );

    renderBoneSlotEditor();
    previewScene.add(previewModel);

    previewMixer = new THREE.AnimationMixer(
      previewModel
    );

    // animations
    gltf.animations.forEach((clip)=>{

      const btn = document.createElement('button');

      btn.className = 'animButton';

      btn.textContent = clip.name;

      btn.onclick = ()=>{

        previewMixer.stopAllAction();

        const action = previewMixer.clipAction(clip);

        action.reset();
        action.fadeIn(0.2);
        action.play();
      };

      animationList.appendChild(btn);
    });

    // anchors
    previewModel.traverse((o)=>{

      if(
        o.name
        .toLowerCase()
        .startsWith('anchor_')
      ){

        const sphere = new THREE.Mesh(
          new THREE.SphereGeometry(0.05),
          new THREE.MeshBasicMaterial({
            color: 0xff0000
          })
        );

        o.add(sphere);
      }
    });

    setStatus(`Loaded ${path}`);

  },undefined,(err)=>{

    console.error(err);

    setStatus('Model load failed');
  });
}

// =====================================================
// STATUS
// =====================================================

function setStatus(text){
  statusBar.textContent = text;
}

// =====================================================
// ANIMATE
// =====================================================

const previewClock = new THREE.Clock();

function animate(){

  requestAnimationFrame(animate);

  const delta = previewClock.getDelta();

  if(previewMixer){
    previewMixer.update(delta);
  }

  if(previewModel){
    previewModel.rotation.y += 0.003;
  }

  previewRenderer.render(
    previewScene,
    previewCamera
  );
}
document
.getElementById(
  "autoMapMixamoBtn"
)
.onclick = ()=>{

  if(
    currentTab !==
    "character_templates"
  ){
    return;
  }

  let template =
    JSON.parse(
      jsonEditor.value
    );

  template.bone_slots = {

    head:
      "mixamorigHead",

    neck:
      "mixamorigNeck",

    right_hand:
      "mixamorigRightHand",

    left_hand:
      "mixamorigLeftHand",

    spine:
      "mixamorigSpine2",

    pelvis:
      "mixamorigHips",

    right_foot:
      "mixamorigRightFoot",

    left_foot:
      "mixamorigLeftFoot"
  };

  jsonEditor.value =
    JSON.stringify(
      template,
      null,
      2
    );

  renderBoneSlotEditor();
};
animate();

// =====================================================
// STARTUP
// =====================================================

loadDefinitions();
loadMeshbank();
loadAssets();

