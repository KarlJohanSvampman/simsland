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
const propNodes = {};        // prop.id → { anchors: Map<name, Object3D>, targets: Map<name, Object3D> }
const tiles = {};

// Reusable vectors for IK (avoid GC pressure)
const _ikA = new THREE.Vector3();
const _ikB = new THREE.Vector3();

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

// =========================================================
// ANIMATION LAYER SYSTEM
// =========================================================

// Mixamo bone names that belong to each layer.
// Lower: hips + both legs. Upper: everything from spine up.
// Hips are lower-only so locomotion controls the root motion;
// sit/lie poses author a separate sit_lower clip that repositions
// the hips and folds the legs.

const LOWER_BONES = new Set([
  "mixamorighips",
  "mixamorigleftupleg",  "mixamorigrightupleg",
  "mixamorigleftleg",    "mixamorigrightleg",
  "mixamorigleftfoot",   "mixamorigrightfoot",
  "mixamoriglefttoebase","mixamorigrighttoebase",
]);

// Upper body = everything NOT in LOWER_BONES.
// We derive it dynamically from clip tracks so we never need a hard list.

function makeLayerClip(clip, layer) {
  const tracks = clip.tracks.filter(track => {
    // track.name format: "BoneName.property" (Three.js GLB loader)
    const boneName = track.name.split(".")[0].toLowerCase()
      .replace(/\s/g, "");
    const isLower = LOWER_BONES.has(boneName);
    return layer === "lower" ? isLower : !isLower;
  });
  return new THREE.AnimationClip(
    `${clip.name}_${layer}`,
    clip.duration,
    tracks
  );
}

// Maps animation_state → { lower, upper }
// lower: which _lower clip to play (locomotion layer)
// upper: which _upper clip to play (interaction layer), null = keep lower-layer upper
//
// Convention for clip names (must match GLB action names, lowercased):
//   walk, run, idle                   — locomotion, authored full-body
//   sit_idle, lie_idle, sleep_idle    — full seated/lying pose (full-body)
//   eat, cook, work, phone, examine   — standing interaction (full-body)
//   talk, wave, carry_idle, carry_walk— standing gestures (full-body)
//
// Three.js splits every full-body clip into _lower and _upper at load time.
// We then play the right combination per layer.

const ANIM_LAYERS = {
  // ── Locomotion (lower drives legs, upper comes from same clip) ──
  idle:          { lower: "idle",        upper: "idle"        },
  walk:          { lower: "walk",        upper: "walk"        },
  run:           { lower: "run",         upper: "run"         },

  // ── Standing interactions (idle legs + active upper) ──
  talk:          { lower: "idle",        upper: "talk"        },
  eat:           { lower: "idle",        upper: "eat"         },
  cook:          { lower: "idle",        upper: "cook"        },
  work:          { lower: "idle",        upper: "work"        },
  phone:         { lower: "idle",        upper: "phone"       },
  examine:       { lower: "idle",        upper: "examine"     },
  search:        { lower: "idle",        upper: "search"      },
  wipe:          { lower: "idle",        upper: "wipe"        },
  mop:           { lower: "walk",        upper: "mop"         },
  scrub:         { lower: "idle",        upper: "scrub"       },
  wash_dishes:   { lower: "idle",        upper: "wash_dishes" },
  window_wipe:   { lower: "idle",        upper: "window_wipe" },
  clean_generic: { lower: "idle",        upper: "clean_generic"},
  pick_up:       { lower: "idle",        upper: "pick_up"     },
  put_down:      { lower: "idle",        upper: "put_down"    },
  throw:         { lower: "idle",        upper: "throw"       },
  smash:         { lower: "idle",        upper: "smash"       },

  // ── Carry (different upper depending on whether moving) ──
  carry_idle:    { lower: "idle",        upper: "carry_idle"  },
  carry_walk:    { lower: "walk",        upper: "carry_idle"  },

  // ── Seated (sit_idle lower folds legs; upper does activity) ──
  sit_idle:      { lower: "sit_idle",    upper: "sit_idle"    },
  sit_watch:     { lower: "sit_idle",    upper: "sit_watch"   },
  sit_eat:       { lower: "sit_idle",    upper: "eat"         },
  sit_talk:      { lower: "sit_idle",    upper: "talk"        },
  sit_phone:     { lower: "sit_idle",    upper: "phone"       },
  sit_work:      { lower: "sit_idle",    upper: "work"        },
  read:          { lower: "sit_idle",    upper: "read"        },

  // ── Lying / sleep ──
  lie_idle:      { lower: "lie_idle",    upper: "lie_idle"    },
  sleep_idle:    { lower: "lie_idle",    upper: "sleep_idle"  },
  wake_up:       { lower: "lie_idle",    upper: "wake_up"     },

  // ── Transitions ──
  stand_up:      { lower: "stand_up",    upper: "stand_up"    },
  shower:        { lower: "idle",        upper: "shower"      },
};

const FADE_TIME = 0.2;  // seconds

function playLayeredAnim(animData, animState) {
  const key = (animState || "idle").toLowerCase();
  const layers = ANIM_LAYERS[key];

  if (!layers) {
    // Unknown state — fall back to full-body single action
    _playSingleAction(animData, key);
    return;
  }

  const wantLower = layers.lower + "_lower";
  const wantUpper = layers.upper + "_upper";

  // ── Lower layer ──
  if (animData.lowerCurrent !== wantLower) {
    _crossFadeLayer(animData, "lowerCurrent", wantLower);
  }

  // ── Upper layer ──
  if (animData.upperCurrent !== wantUpper) {
    _crossFadeLayer(animData, "upperCurrent", wantUpper);
  }
}

function _crossFadeLayer(animData, trackingKey, wantName) {
  const prev = animData[trackingKey];
  const prevAction = prev ? animData.actions[prev] : null;
  const nextAction = animData.actions[wantName];

  if (!nextAction) {
    // Clip not available — leave current layer running
    return;
  }

  if (prevAction && prevAction !== nextAction) {
    prevAction.fadeOut(FADE_TIME);
  }

  nextAction.reset();
  nextAction.setEffectiveWeight(1);
  nextAction.fadeIn(FADE_TIME);
  nextAction.play();

  animData[trackingKey] = wantName;
}

function _playSingleAction(animData, name) {
  // Fallback for states not in ANIM_LAYERS: treat as full-body
  if (animData.current === name) return;

  const prev = animData.current;
  if (prev && animData.actions[prev]) {
    animData.actions[prev].fadeOut(FADE_TIME);
  }

  const action = animData.actions[name];
  if (action) {
    action.reset();
    action.fadeIn(FADE_TIME);
    action.play();
    animData.current = name;
  }
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

// =========================================================
// CLOTHING BONE SLOT MAP
// Maps clothing slot name → one or more bone names to attach to.
// Slots with two entries (shoes, gloves) clone one mesh per bone.
// Slots marked shared_skeleton in the template use SkinnedMesh
// overlay sharing the character's skeleton instead.
// =========================================================

const CLOTHING_BONE_SLOTS = {
    hat:           ["mixamorigHead"],
    upper_layer1:  ["mixamorigSpine2"],
    upper_layer2:  ["mixamorigSpine2"],
    pants:         ["mixamorigHips"],
    shoes:         ["mixamorigRightFoot", "mixamorigLeftFoot"],
    gloves:        ["mixamorigRightHand", "mixamorigLeftHand"],
    belt:          ["mixamorigHips"],
    mask:          ["mixamorigHead"],
    backpack:      ["mixamorigSpine2"],
};

// =========================================================
// ATTACH CLOTHING ITEM
// Attaches a clothing mesh to the character model.
// If template.shared_skeleton === true: adds SkinnedMesh as
//   sibling of the character root, sharing its skeleton.
// Otherwise: rigid bone-child attachment (good for hats/shoes).
// Returns array of attached THREE objects for later removal.
// =========================================================

async function attachClothing(characterModel, slot, clothingTemplate, characterRoot) {
    if (!clothingTemplate || !clothingTemplate.model) return [];

    const boneNames = CLOTHING_BONE_SLOTS[slot] || [];
    const attached  = [];

    const loaded = await loadModelCached(clothingTemplate.model);

    // -- Shared skeleton mode (shirts, pants, jackets) --
    if (clothingTemplate.shared_skeleton) {
        const clothingScene = loaded.scene.clone(true);

        // Collect the character's skeleton
        let skeleton = null;
        characterModel.traverse(n => {
            if (n.isSkinnedMesh && n.skeleton) skeleton = n.skeleton;
        });

        if (skeleton) {
            clothingScene.traverse(n => {
                if (n.isSkinnedMesh) {
                    n.skeleton = skeleton;
                    n.bindMatrix.copy(characterModel.matrixWorld);
                    n.bindMatrixInverse.copy(characterModel.matrixWorld).invert();
                }
            });
        }

        characterRoot.add(clothingScene);
        attached.push(clothingScene);
        return attached;
    }

    // -- Rigid bone-child mode (hats, shoes, accessories) --
    for (const boneName of boneNames) {
        const bone = findBone(characterModel, boneName);
        if (!bone) { console.warn("Clothing: bone not found:", boneName); continue; }

        // Clone scene so left/right get independent transforms
        const piece = loaded.scene.clone(true);

        const offset = clothingTemplate.offset || {};
        piece.position.set(offset.x || 0, offset.y || 0, offset.z || 0);

        const rot = clothingTemplate.rotation || {};
        piece.rotation.set(
            (rot.x || 0) * Math.PI / 180,
            (rot.y || 0) * Math.PI / 180,
            (rot.z || 0) * Math.PI / 180,
        );

        const sc = clothingTemplate.scale || 1;
        piece.scale.setScalar(typeof sc === "number" ? sc : 1);

        // Mirror left-side pieces (shoes left, glove left)
        if (boneName.includes("Left")) {
            piece.scale.x *= -1;
        }

        bone.add(piece);
        attached.push(piece);
    }

    return attached;
}

// =========================================================
// EQUIP ALL CLOTHING FOR A CHARACTER
// Called on character load and again whenever equipped changes.
// Stores attached meshes in characterAttachments[id].clothing
// so they can be removed/replaced without reloading the character.
// =========================================================

async function equipAllClothing(id, characterModel, characterRoot, equipped, definitions) {
    const clothingTemplates = definitions?.clothing_templates || {};

    // Remove any previously attached clothing
    const prev = (characterAttachments[id] || {}).clothing || {};
    for (const meshes of Object.values(prev)) {
        for (const m of meshes) m.parent?.remove(m);
    }

    if (!characterAttachments[id]) characterAttachments[id] = {};
    characterAttachments[id].clothing = {};

    for (const [slot, templateId] of Object.entries(equipped || {})) {
        if (!templateId) continue;
        const tpl = clothingTemplates[templateId];
        if (!tpl) { console.warn("Clothing template not found:", templateId); continue; }

        const meshes = await attachClothing(characterModel, slot, tpl, characterRoot);
        characterAttachments[id].clothing[slot] = meshes;
    }
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
