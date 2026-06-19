import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls }
from "three/examples/jsm/controls/OrbitControls.js";
import { clone }
from "three/examples/jsm/utils/SkeletonUtils.js";
import { CSS2DRenderer, CSS2DObject }
from "three/examples/jsm/renderers/CSS2DRenderer.js";
import {

  getPropTemplate,

  getCharacterTemplate,

  getFloorplanTemplate,

  resolveProp,

  resolveCharacter,

  getMaterialTemplate

} from "./templates";
const selectable = [];
const canvas = document.getElementById("c");
const raycaster =
  new THREE.Raycaster();
const modelCache = {};
const mouse =
  new THREE.Vector2();

// =========================================================
// MESHBANK  (resolve model ID → actual GLB path)
// =========================================================

let meshbank = {};

async function loadMeshbank() {
  try {
    const res = await fetch('/api/meshbank');
    meshbank = await res.json();
  } catch (e) {
    console.warn('Meshbank unavailable', e);
  }
}

function resolveModel(modelRef) {
  if (!modelRef) return null;
  // If it's a meshbank key, return the mesh path
  const asset = meshbank[modelRef];
  if (asset?.mesh) return asset.mesh;
  // Backward compat: raw paths pass through
  return modelRef;
}
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x20242a);

const loadingProps = {};
const loadingCharacters = {};
const floorRegistry = {};
const wallRegistry = {};
const buildingRegistry = {};
const WALL_HEIGHT = 2.8;
const WALL_THICKNESS = 0.08;
const textureLoader =
  new THREE.TextureLoader();

const materialCache = {};

const camera = new THREE.OrthographicCamera(
  -20,
  20,
  12,
  -12,
  0.1,
  1000
);

camera.position.set(20, 20, 20);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true
});

renderer.setSize(window.innerWidth, window.innerHeight);

// =========================================================
// CSS2D RENDERER  (speech bubbles)
// =========================================================

const cssRenderer = new CSS2DRenderer();
cssRenderer.setSize(window.innerWidth, window.innerHeight);
cssRenderer.domElement.style.position = "absolute";
cssRenderer.domElement.style.top = "0";
cssRenderer.domElement.style.pointerEvents = "none";
document.body.appendChild(cssRenderer.domElement);

const controls = new OrbitControls(
  camera,
  renderer.domElement
);

controls.enableDamping = true;

window.addEventListener("resize", ()=>{

  renderer.setSize(
    window.innerWidth,
    window.innerHeight
  );

  cssRenderer.setSize(
    window.innerWidth,
    window.innerHeight
  );

  const aspect =
    window.innerWidth /
    window.innerHeight;

  camera.left = -20 * aspect;
  camera.right = 20 * aspect;

  camera.top = 12;
  camera.bottom = -12;

  camera.updateProjectionMatrix();
});

scene.add(
  new THREE.AmbientLight(0xffffff, 0.6)
);

const light = new THREE.DirectionalLight(
  0xffffff,
  1
);

light.position.set(10,20,10);

scene.add(light);

scene.add(
  new THREE.GridHelper(100,100)
);

const loader = new GLTFLoader();

const characterAnimations = {};
const sims = {};
const characterAttachments = {};
const speechBubbles = {};   // id → { cssObject, div }
const props = {};
const tiles = {};

let definitions = {};
function createWallMaterial(wallData){

  const texture =
    getMaterialTexture(
      wallData.material
    );

  if(texture){

    return new THREE.MeshStandardMaterial({
      map: texture
    });
  }

  let color = 0xdddddd;

  if(wallData.type === "door"){
    color = 0x996633;
  }

  if(wallData.type === "window"){
    color = 0x66ccff;
  }

  return new THREE.MeshStandardMaterial({
    color
  });
}
function createWallMesh(
  x,
  y,
  side,
  wallData
){

  const horizontal =
    side === "north"
    || side === "south";

  const width =
    horizontal
    ? 1
    : WALL_THICKNESS;

  const depth =
    horizontal
    ? WALL_THICKNESS
    : 1;

  const geo =
    new THREE.BoxGeometry(
      width,
      WALL_HEIGHT,
      depth
    );

  const mat =
    createWallMaterial(wallData);

  const mesh =
    new THREE.Mesh(geo, mat);

  // =========================
  // POSITION
  // =========================

  let px = x;
  let pz = y;

  if(side === "north"){
    pz -= 0.5;
  }

  if(side === "south"){
    pz += 0.5;
  }

  if(side === "west"){
    px -= 0.5;
  }

  if(side === "east"){
    px += 0.5;
  }

  mesh.position.set(
    px,
    WALL_HEIGHT / 2,
    pz
  );

  mesh.castShadow = true;
  mesh.receiveShadow = true;

  return mesh;
}
function createDoorSegment(
  x,
  y,
  side,
  wallData
){

  const group = new THREE.Group();

  const horizontal =
    side === "north"
    || side === "south";

  const frameThickness = 0.12;
  const doorWidth = 0.55;

  const leftWidth =
    (1 - doorWidth) / 2;

  const sideGeo =
    horizontal
    ? new THREE.BoxGeometry(
        leftWidth,
        WALL_HEIGHT,
        WALL_THICKNESS
      )
    : new THREE.BoxGeometry(
        WALL_THICKNESS,
        WALL_HEIGHT,
        leftWidth
      );

  const topGeo =
    horizontal
    ? new THREE.BoxGeometry(
        doorWidth,
        0.45,
        WALL_THICKNESS
      )
    : new THREE.BoxGeometry(
        WALL_THICKNESS,
        0.45,
        doorWidth
      );

  const mat =
    createWallMaterial(wallData);

  const left = new THREE.Mesh(sideGeo, mat);
  const right = new THREE.Mesh(sideGeo, mat);
  const top = new THREE.Mesh(topGeo, mat);

  if(horizontal){

    left.position.x =
      -0.5 + leftWidth / 2;

    right.position.x =
      0.5 - leftWidth / 2;

    top.position.y =
      WALL_HEIGHT / 2 - 0.225;
  }

  else {

    left.position.z =
      -0.5 + leftWidth / 2;

    right.position.z =
      0.5 - leftWidth / 2;

    top.position.y =
      WALL_HEIGHT / 2 - 0.225;
  }

  group.add(left);
  group.add(right);
  group.add(top);

  let px = x;
  let pz = y;

  if(side === "north") pz -= 0.5;
  if(side === "south") pz += 0.5;
  if(side === "west") px -= 0.5;
  if(side === "east") px += 0.5;

  group.position.set(
    px,
    WALL_HEIGHT / 2,
    pz
  );

  return group;
}

function createWindowSegment(
  x,
  y,
  side,
  wallData
){

  const group = new THREE.Group();

  const horizontal =
    side === "north"
    || side === "south";

  const mat =
    createWallMaterial(wallData);

  const glassMat =
    new THREE.MeshStandardMaterial({
      color: 0x88ccff,
      transparent: true,
      opacity: 0.35
    });

  const lowerGeo =
    horizontal
    ? new THREE.BoxGeometry(
        1,
        0.9,
        WALL_THICKNESS
      )
    : new THREE.BoxGeometry(
        WALL_THICKNESS,
        0.9,
        1
      );

  const upperGeo =
    horizontal
    ? new THREE.BoxGeometry(
        1,
        0.7,
        WALL_THICKNESS
      )
    : new THREE.BoxGeometry(
        WALL_THICKNESS,
        0.7,
        1
      );

  const glassGeo =
    horizontal
    ? new THREE.BoxGeometry(
        0.85,
        0.9,
        WALL_THICKNESS / 2
      )
    : new THREE.BoxGeometry(
        WALL_THICKNESS / 2,
        0.9,
        0.85
      );

  const lower = new THREE.Mesh(lowerGeo, mat);
  const upper = new THREE.Mesh(upperGeo, mat);
  const glass = new THREE.Mesh(glassGeo, glassMat);

  lower.position.y = -0.95;
  upper.position.y = 1.05;

  group.add(lower);
  group.add(upper);
  group.add(glass);

  let px = x;
  let pz = y;

  if(side === "north") pz -= 0.5;
  if(side === "south") pz += 0.5;
  if(side === "west") px -= 0.5;
  if(side === "east") px += 0.5;

  group.position.set(
    px,
    WALL_HEIGHT / 2,
    pz
  );

  return group;
}

async function loadModelCached(path){

  // =========================
  // CACHE HIT
  // =========================

  if(modelCache[path]){

    return {

      scene: clone(
        modelCache[path].scene
      ),

      animations:
        modelCache[path]
        .animations
    };
  }

  // =========================
  // FIRST LOAD
  // =========================

  return new Promise(

    (resolve, reject)=>{

      loader.load(

        path,

        (gltf)=>{

          modelCache[path] = {

            scene: gltf.scene,

            animations:
              gltf.animations
          };

          resolve({

            scene: clone(
              gltf.scene
            ),

            animations:
              gltf.animations
          });
        },

        undefined,

        reject
      );
    }
  );
}

function removeSelectable(obj){

  const i =
    selectable.indexOf(obj);

  if(i !== -1){

    selectable.splice(i, 1);
  }
}

function getBuildingGroup(fp){

  if(buildingRegistry[fp.id]){

    return buildingRegistry[
      fp.id
    ];
  }

  const group =
    new THREE.Group();

  group.position.set(

    fp.x - 10,

    0,

    fp.y - 7
  );

  group.rotation.y =
    THREE.MathUtils.degToRad(
      fp.rotation || 0
    );

  group.userData = {

    type: "building",

    id: fp.id
  };

  selectable.push(group);

  scene.add(group);

  buildingRegistry[
    fp.id
  ] = group;

  return group;
}

function updateFloorplanWalls(state){

  const active = new Set();
  const activeBuildings = new Set();

  const floorplans =
    state.floorplans || [];

  for(const fp of floorplans){
    activeBuildings.add(fp.id);
    const building =
      resolveFloorplan(
        definitions,
        fp.building
      );

    const buildingGroup = getBuildingGroup(fp.id);

    if(!building) continue;

    for(const key in building.tiles){

      const tile = building.tiles[key];

      const walls =
        tile.walls || {};

      const [x,y] = key
        .split(",")
        .map(Number);

      for(const side in walls){

        const wallData = walls[side];

        if(!wallData) continue;

        const wallKey =
          `${building.id}_${x}_${y}_${side}`;

        active.add(wallKey);

        if(wallRegistry[wallKey]){
          continue;
        }

        let mesh = null;

        if(wallData.type === "wall"){

          mesh = createWallMesh(
            x,
            y,)
        }

        else if(wallData.type === "door"){

          mesh = createDoorSegment(
            x,
            y,
            side,
            wallData
          );
        }

        else if(wallData.type === "window"){

          mesh = createWindowSegment(
            x,
            y,
            side,
            wallData
          );
        }

        if(mesh){

          buildingGroup.add(mesh);

          wallRegistry[
            wallKey
          ] = mesh;
        }
      }
    }
    cleanupBuildings(activeBuildings);
  }

  // cleanup
  for(const key in wallRegistry){

    if(active.has(key)) continue;

    scene.remove(
      wallRegistry[key]
    );

    delete wallRegistry[key];
  }
}
function getMaterialTexture(materialId){

  if(materialCache[materialId]){
    return materialCache[materialId];
  }

  const materialTemplate =
    getMaterialTemplate(
      definitions,
      materialId
    );

  if(!materialTemplate?.texture){
    return null;
  }

  const tex = textureLoader.load(
    materialTemplate.texture
  );

  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;

  tex.repeat.set(1,1);

  materialCache[materialId] = tex;

  return tex;
}

function findBone(root, boneName){

    let found = null;

    root.traverse(node=>{

        if(node.isBone &&
           node.name === boneName){

            found = node;
        }
    });

    return found;
}

async function attachItemToBone(

    characterModel,

    boneName,

    itemTemplate
){

    const bone =
        findBone(
            characterModel,
            boneName
        );

    if(!bone){
        return null;
    }

    const loaded =
        await loadModelCached(
            itemTemplate.model
        );

    const item =
        loaded.scene;

    bone.add(item);

    item.position.set(
        0,
        0,
        0
    );

    item.rotation.set(
        0,
        0,
        0
    );

    item.scale.set(
        1,
        1,
        1
    );

    return item;
}

function createFloorMaterial(tileFloor){

  const texture =
    getMaterialTexture(
      tileFloor.material
    );

  if(texture){

    return new THREE.MeshStandardMaterial({
      map: texture
    });
  }

  let color = 0x777777;

  if(tileFloor.type === "grass"){
    color = 0x447744;
  }

  if(tileFloor.type === "staircase"){
    color = 0xaa8833;
  }

  return new THREE.MeshStandardMaterial({
    color
  });
}

function createFloorMesh(x, y, tileFloor){

  const geo =
    new THREE.PlaneGeometry(1,1);

  const mat =
    createFloorMaterial(tileFloor);

  const mesh =
    new THREE.Mesh(geo, mat);
  mesh.userData.ignoreRaycast = true;
  mesh.rotation.x =
    -Math.PI / 2;

  mesh.position.set(
    x,
    0,
    y
  );

  mesh.receiveShadow = true;

  return mesh;
}

function updateFloorplanFloors(state){

  const active = new Set();
  const activeBuildings = new Set();
  const floorplans =
    state.floorplans || [];

for(const fp of floorplans){
  activeBuildings.add(fp.id);
  const building =
    resolveFloorplan(
      definitions,
      fp.building
    );
    

  const buildingGroup = getBuildingGroup(fp.id);

  if(!building) continue;

  for(const key in building.tiles){

      const tile = building.tiles[key];

      if(!tile.floor) continue;

      const [x,y] = key
        .split(",")
        .map(Number);

      const worldKey =
        `${fp.id}_${x}_${y}`;

      active.add(worldKey);

      if(!floorRegistry[worldKey]){

        const mesh =
          createFloorMesh(
            x,
            y,
            tile.floor
          );

        buildingGroup.add(mesh);

        floorRegistry[worldKey] = mesh;
      }
    }
  }

  // cleanup
  for(const key in floorRegistry){

    if(active.has(key)) continue;

    scene.remove(
      floorRegistry[key]
    );

    delete floorRegistry[key];
  }

  cleanupBuildings(activeBuildings);
}


function createTile(tile){

  const mesh = new THREE.Mesh(

    new THREE.PlaneGeometry(1,1),

    new THREE.MeshStandardMaterial({

      color:
        tile.walkable
        ? 0x557799
        : 0xaa3333,

      side: THREE.DoubleSide
    })
  );

  mesh.rotation.x = -Math.PI / 2;

  mesh.position.set(
    tile.x - 10,
    0.01,
    tile.y - 7
  );
  mesh.userData = {

  type: "tile",

  x: tile.x,
  y: tile.y
};

selectable.push(mesh);
scene.add(mesh);



  return mesh;
}

function updateTiles(state){

  const active = new Set();

  const arr =

    Array.isArray(state.tiles)

    ? state.tiles

    : Object.values(
        state.tiles || {}
      );

  // =========================
  // ACTIVE TILES
  // =========================

  for(const tile of arr){

    const key =
      `${tile.x},${tile.y}`;

    active.add(key);

    // already exists
    if(tiles[key]){
      continue;
    }

    tiles[key] =
      createTile(tile);
  }

  // =========================
  // CLEANUP REMOVED
  // =========================

  for(const key in tiles){

    if(active.has(key)){
      continue;
    }

    const mesh = tiles[key];

    scene.remove(mesh);

    removeSelectable(mesh);

    delete tiles[key];
  }
}

function createFallbackProp(prop){

  const mesh = new THREE.Mesh(

    new THREE.BoxGeometry(1,1,1),

    new THREE.MeshStandardMaterial({
      color: 0xff00ff
    })
  );

  mesh.position.set(
    prop.x - 10,
    0.5,
    prop.y - 7
  );
  mesh.userData = {

    type: "prop",

    id: prop.id,

    template: prop.template
  };

  selectable.push(mesh);
  scene.add(mesh);

  return mesh;
}

async function updateProps(state){

  const active = new Set();

  for(const prop of state.props || []){

    active.add(prop.id);

    // =========================
    // ALREADY EXISTS
    // =========================

    if(props[prop.id]){

      props[prop.id].position.set(
        prop.x - 10,
        0.5,
        prop.y - 7
      );

      continue;
    }

    // =========================
    // CURRENTLY LOADING
    // =========================

    if(loadingProps[prop.id]){
      continue;
    }

    loadingProps[prop.id] = true;

    // =========================
    // TEMPLATE
    // =========================

    const resolved =
      resolveProp(
        definitions,
        prop
      );

    // =========================
    // FALLBACK
    // =========================

    const propModelPath = resolveModel(resolved?.model);

    if(!propModelPath){

      props[prop.id] =
        createFallbackProp(prop);

      delete loadingProps[prop.id];

      continue;
    }

try {

  const model =
    await loadModelCached(
      propModelPath
    );

  model.position.set(
    prop.x - 10,
    0,
    prop.y - 7
  );

  model.userData = {

    type: "prop",

    id: prop.id,

    template: prop.template
  };

  model.traverse((o)=>{

    if(o.isMesh){

      o.castShadow = true;
      o.receiveShadow = true;
    }
  });

  selectable.push(model);

  scene.add(model);

  props[prop.id] = model;
}

catch(err){

  console.error(
    "Failed to load prop:",
    resolved.model,
    err
  );

  props[prop.id] =
    createFallbackProp(prop);
}

delete loadingProps[prop.id];
  }

  // =========================
  // CLEANUP REMOVED PROPS
  // =========================

  for(const id in props){

    if(active.has(id)) continue;

    const mesh = props[id];

    scene.remove(mesh);

    removeSelectable(mesh);

    delete props[id];
  }
}

function cleanupBuildings(activeIds){

  for(const id in buildingRegistry){

    if(activeIds.has(id)){
      continue;
    }

    const group =
      buildingRegistry[id];

    scene.remove(group);

    removeSelectable(group);

    delete buildingRegistry[id];
  }
}

// =========================================================
// SPEECH BUBBLES
// =========================================================

function getOrCreateBubble(id){

  if(speechBubbles[id]){
    return speechBubbles[id];
  }

  const div = document.createElement("div");
  div.className = "speech-bubble";
  div.style.cssText = `
    background: rgba(255,255,255,0.92);
    color: #111;
    padding: 4px 8px;
    border-radius: 10px;
    font-size: 12px;
    font-family: sans-serif;
    max-width: 160px;
    text-align: center;
    white-space: normal;
    pointer-events: none;
    box-shadow: 0 2px 6px rgba(0,0,0,0.25);
    display: none;
  `;

  const cssObject = new CSS2DObject(div);
  cssObject.position.set(0, 2.6, 0);   // above head
  speechBubbles[id] = { cssObject, div };
  return speechBubbles[id];
}

function updateSpeechBubbles(state){

  const active = new Set(
    Object.keys(state.characters || {})
  );

  for(const [id, c]
    of Object.entries(state.characters || {})
  ){
    const model = sims[id];
    if(!model) continue;

    const { cssObject, div } =
      getOrCreateBubble(id);

    // attach if not already attached
    if(!model.getObjectById(cssObject.id)){
      model.add(cssObject);
    }

    const speech = c.current_speech;

    if(speech && speech.utterance){
      div.textContent = speech.utterance;
      div.style.display = "block";
    } else {
      div.style.display = "none";
    }
  }

  // remove bubbles for characters that left
  for(const id in speechBubbles){

    if(active.has(id)) continue;

    const { cssObject } = speechBubbles[id];
    const model = sims[id];

    if(model) model.remove(cssObject);

    delete speechBubbles[id];
  }
}

function createFallbackCharacter(c){

  const mesh = new THREE.Mesh(

    new THREE.CapsuleGeometry(
      0.35,
      1
    ),

    new THREE.MeshStandardMaterial({
      color: 0x00ffff
    })
  );

  mesh.position.set(
    c.x - 10,
    1,
    c.y - 7
  );
  mesh.userData = {

    type: "character",

    id: c.id,

    name: c.name
  };

  selectable.push(mesh);
  scene.add(mesh);

  return mesh;
}

async function updateCharacters(state){

  const active = new Set();

  for(const [id, c]
    of Object.entries(
      state.characters || {}
    )
  ){

    active.add(id);

    // =========================
    // ALREADY EXISTS
    // =========================

    if(sims[id]){

      sims[id].position.set(
        c.x - 10,
        1,
        c.y - 7
      );

            // =========================
      // ANIMATION STATE
      // =========================

      const animState =
        c.animation_state || "idle";

      const animData =
        characterAnimations[id];

      if(animData){

        if(animData.current !== animState){

          // stop previous
          if(
            animData.current &&
            animData.actions[
              animData.current
            ]
          ){
            animData.actions[
              animData.current
            ].fadeOut(0.2);
          }

          // play new
          const action =
            animData.actions[
              animState.toLowerCase()
            ];

          if(action){

            action.reset();

            action.fadeIn(0.2);

            action.play();

            animData.current =
              animState;
          }
        }
      }

      continue;
    }

    // =========================
    // CURRENTLY LOADING
    // =========================

    if(loadingCharacters[id]){
      continue;
    }

    loadingCharacters[id] = true;

    // =========================
    // TEMPLATE
    // =========================

    const character =
      resolveCharacter(
        definitions,
        c
      );
    // =========================
    // FALLBACK
    // =========================

    const charModelPath = resolveModel(character?.model);

    if(!charModelPath){

      sims[id] =
        createFallbackCharacter(c);

      delete loadingCharacters[id];

      continue;
    }

try {

const loaded =
  await loadModelCached(
    charModelPath
  );

  const model =
  loaded.scene;

  model.animations =
  loaded.animations;

    // =========================
    // ANIMATION SETUP
    // =========================

    let mixer = null;

    const actions = {};

    if(model.animations?.length){

      mixer = new THREE.AnimationMixer(
        model
      );

      for(const clip of model.animations){

        actions[
          clip.name.toLowerCase()
        ] = mixer.clipAction(clip);
      }
    }



  model.position.set(
    c.x - 10,
    0,
    c.y - 7
  );

  model.userData = {

    type: "character",

    id: c.id,

    name: c.name
  };

  model.traverse((o)=>{

    if(o.isMesh){

      o.castShadow = true;
      o.receiveShadow = true;
    }
  });

  selectable.push(model);

  scene.add(model);

  sims[id] = model;
 // =========================
// EQUIPMENT
// =========================

characterAttachments[id] = {};

const equipped =
    c.equipped || {};

for(const slot in equipped){

    const itemId =
        equipped[slot];

    console.log(
        "Equip:",
        slot,
        itemId
    );

    // we'll fill this next
}

  characterAnimations[id] = {

  mixer,

  actions,

  current: null
};
}

catch(err){

  console.error(
    "Failed to load character:",
    character.model,
    err
  );

  sims[id] =
    createFallbackCharacter(c);
}

delete loadingCharacters[id];
  }

  // =========================
  // CLEANUP REMOVED CHARACTERS
  // =========================

  for(const id in sims){

    if(active.has(id)) continue;

    const mesh = sims[id];

    scene.remove(mesh);

    removeSelectable(mesh);
    delete characterAnimations[id];
    delete sims[id];
  }
}
renderer.domElement.addEventListener(

  "pointerdown",

  (event)=>{

    mouse.x =
      (event.clientX /
      window.innerWidth) * 2 - 1;

    mouse.y =
      -(event.clientY /
      window.innerHeight) * 2 + 1;

    raycaster.setFromCamera(
      mouse,
      camera
    );

    const hits =
      raycaster
        .intersectObjects(
          selectable,
          true
        )
        .filter(
          h =>
            !h.object.userData
            ?.ignoreRaycast
        );

    if(!hits.length){

      document
        .getElementById(
          "viewerSelection"
        ).innerHTML =
          "Nothing selected";

      return;
    }

    let obj = hits[0].object;

    while(
      obj &&
      !obj.userData?.type
    ){
      obj = obj.parent;
    }

    if(!obj) return;

    const d = obj.userData;

    document
      .getElementById(
        "viewerSelection"
      ).innerHTML = `

        <b>${d.type}</b><br>

        ${d.id || ""}<br>

        ${d.name || ""