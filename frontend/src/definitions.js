import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';


function resolveMeshAsset(assetId){

  if(!assetId){
    return null;
  }

  return meshbank[
    assetId
  ] || null;
}

function resolveModelPath(template){

  const modelId =
    template?.model;

  if(!modelId){
    return null;
  }

  const asset =
    resolveMeshAsset(
      modelId
    );

  if(!asset){
    return null;
  }

  return asset.mesh;
}
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

let assets = {
  props: [],
  characters: [],
  items: []
};

let meshbank = {};

let currentTab = 'prop_templates';
let currentTemplateId = null;

// =====================================================
// UI ELEMENTS
// =====================================================

const tabsEl = document.getElementById('tabs');
const templateListEl = document.getElementById('templateList');
const jsonEditor = document.getElementById('jsonEditor');
const editorTitle = document.getElementById('editorTitle');
const assetBrowser = document.getElementById('assetBrowser');
const animationList = document.getElementById('animationList');
const statusBar = document.getElementById('statusBar');

// =====================================================
// THREE PREVIEW
// =====================================================

const previewScene = new THREE.Scene();
previewScene.background = new THREE.Color(0x20242a);

const previewCamera = new THREE.PerspectiveCamera(
  60,
  1,
  0.1,
  1000
);

previewCamera.position.set(2,2,2);
previewCamera.lookAt(0,0,0);

const previewRenderer = new THREE.WebGLRenderer({
  antialias: true
});

previewRenderer.setSize(420,420);

document
  .getElementById('modelPreview')
  .appendChild(previewRenderer.domElement);

previewScene.add(
  new THREE.AmbientLight(0xffffff,1.2)
);

const dir = new THREE.DirectionalLight(
  0xffffff,
  2
);

dir.position.set(5,10,5);
previewScene.add(dir);

previewScene.add(
  new THREE.GridHelper(10,10)
);

const previewLoader = new GLTFLoader();

let previewModel = null;
let previewMixer = null;
let previewBones = [];


function extractBones(root){

  const bones = [];

  root.traverse(node=>{

    if(node.isBone){

      bones.push(
        node.name
      );
    }
  });

  return bones.sort();
}

const STANDARD_BONE_SLOTS = [

  "head",

  "neck",

  "right_hand",

  "left_hand",

  "spine",

  "pelvis",

  "right_foot",

  "left_foot"
];

function renderBoneSlotEditor(){

  const container =
    document.getElementById(
      "boneSlotEditor"
    );

  container.innerHTML = "";

  if(
    currentTab !==
    "character_templates"
  ){
    return;
  }

  if(!currentTemplateId){
    return;
  }

  let template;

  try{

    template =
      JSON.parse(
        jsonEditor.value
      );

  }catch{

    return;
  }

  template.bone_slots ||= {};

  STANDARD_BONE_SLOTS.forEach(slot=>{

    const row =
      document.createElement("div");

    row.className =
      "boneSlotRow";

    const label =
      document.createElement("label");

    label.textContent =
      slot;

    const select =
      document.createElement("select");

    const empty =
      document.createElement("option");

    empty.value = "";
    empty.textContent = "--";


const modelId =
  template.model;

const asset =
  meshbank[
    modelId
  ];

const bones =
  Object.keys(
    asset?.bones || {}
  );
  console.log(
  "Model:",
  template.model
);

console.log(
  "Asset:",
  asset
);

console.log(
  "Bones:",
  bones
);

select.appendChild(
      empty
    );
bones.forEach(bone=>{

      const option =
        document.createElement(
          "option"
        );

      option.value =
        bone;

      option.textContent =
        bone;

      if(
        template
        .bone_slots?.[slot]
        === bone
      ){
        option.selected = true;
      }

      select.appendChild(
        option
      );
    });

    select.onchange = ()=>{

      template.bone_slots ||= {};

      template
      .bone_slots[slot] =
        select.value;

      jsonEditor.value =
        JSON.stringify(
          template,
          null,
          2
        );
    };

    row.appendChild(label);
    row.appendChild(select);

    container.appendChild(row);
  });
}

async function loadMeshbank(){

    const response =
        await fetch(
            "/api/meshbank"
        );

    meshbank =
        await response.json();

    console.log(
        "MeshBank loaded",
        meshbank
    );
}
// =====================================================
// LOAD DEFINITIONS
// =====================================================

async function loadDefinitions(){

  try {

    const res = await fetch(
      '/api/editor/definitions?sim_id=default'
    );

    definitions = await res.json();

  } catch(err){

    console.warn(err);
  }

  renderTabs();
  renderTemplateList();
}

// =====================================================
// LOAD ASSETS
// =====================================================

async function loadAssets(){

  try {

    const res = await fetch('/api/assets');

    assets = await res.json();

  } catch(err){

    console.warn(err);
  }

  renderAssets();
}

// =====================================================
// TABS
// =====================================================

function renderTabs(){

  tabsEl.innerHTML = '';

  tabs.forEach(tab=>{

    const el = document.createElement('div');

    el.className = 'tab';

    if(tab === currentTab){
      el.classList.add('active');
    }

    el.textContent = tab;

    el.onclick = ()=>{

      currentTab = tab;
      currentTemplateId = null;

      renderTabs();
      renderTemplateList();
    };

    tabsEl.appendChild(el);
  });
}

// =====================================================
// TEMPLATE LIST
// =====================================================

function renderTemplateList(){

  templateListEl.innerHTML = '';

  const bucket = definitions[currentTab] || {};

  Object.entries(bucket).forEach(([id,data])=>{

    const row = document.createElement('div');

    row.className = 'templateRow';
    if(id === currentTemplateId){
    row.classList.add("active");
    }
    row.textContent = id;

    row.onclick = ()=>{
      openTemplate(id);
    };

    templateListEl.appendChild(row);
  });
}

// =====================================================
// OPEN TEMPLATE
// =====================================================

function openTemplate(id){

  currentTemplateId = id;

  const data = definitions[currentTab][id];

  jsonEditor.value = JSON.stringify(
    data,
    null,
    2
  );

  editorTitle.textContent = id;
renderBoneSlotEditor();
const path =
  resolveModelPath(
    data
  );

console.log(
  "Resolved model path:",
  path
);

if(path){

  loadPreviewModel(
    path
  );
}

}

// =====================================================
// CREATE TEMPLATE
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

