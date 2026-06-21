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

// =========================================================
// ANIMATION VARIANTS
// Maps a clip stem to a pool of alternatives. When ANIM_LAYERS
// resolves an upper (or lower) to a stem listed here, a random
// variant from the pool is chosen on each state entry. The
// finished event re-rolls to the next variant so the character
// continuously cycles through the pool without ever repeating
// the same clip twice in a row.
//
// These are STEM names — the layer suffix (_upper / _lower) is
// appended automatically. Every stem in the pool must have a
// corresponding named clip exported from Blender. If a variant
// clip isn't found in the GLB the system gracefully falls back
// to the next available one.
// =========================================================

const ANIM_VARIANTS = {
  // Conversation — cycle gesture animations while talking
  talk:          ["talk", "talk_gesture_a", "talk_gesture_b", "talk_nod", "talk_think"],

  // Phone call — alternate gestures
  phone:         ["phone", "phone_gesture"],

  // Standing idle — subtle fidgets
  idle:          ["idle", "idle_look", "idle_shift"],

  // Seated idle — seated fidgets
  sit_idle:      ["sit_idle", "sit_fidget", "sit_look"],

  // Working at a desk
  work:          ["work", "work_type", "work_read"],

  // Examining objects
  examine:       ["examine", "examine_crouch"],
};


// =========================================================
// VARIANT HELPERS
// =========================================================

/** Pick a random variant from the pool, avoiding the last played. */
function _pickVariant(pool, last) {
  if (pool.length === 1) return pool[0];
  const filtered = last ? pool.filter(v => v !== last) : pool;
  return filtered[Math.floor(Math.random() * filtered.length)];
}

/**
 * Cross-fade to a new clip on the given layer (upper or lower).
 * Handles both variant (LoopOnce + re-roll) and looping (LoopRepeat) modes.
 *
 * @param {object}  animData  - character's animation tracking object
 * @param {string}  layer     - "upper" or "lower"
 * @param {string}  newStem   - target stem from ANIM_LAYERS (e.g. "talk")
 */
function _setLayer(animData, layer, newStem) {
  const stemKey     = layer + "Stem";        // e.g. "upperStem"
  const currentKey  = layer + "Current";     // e.g. "upperCurrent"
  const lastKey     = layer + "VariantLast"; // e.g. "upperVariantLast"
  const suffix      = "_" + layer;           // "_upper" or "_lower"

  const pool = ANIM_VARIANTS[newStem];

  if (pool && pool.length > 1) {
    // ── Variant pool mode ──
    // If we're already in this pool, do nothing — let the current clip play
    // to completion; the finished listener will re-roll automatically.
    if (animData[stemKey] === newStem) return;

    // Entering a new variant state — pick first clip
    const chosen = _pickVariant(pool, null);
    animData[stemKey]    = newStem;
    animData[lastKey]    = chosen;
    _crossFadeLayerOnce(animData, currentKey, chosen + suffix);

  } else {
    // ── Single clip / loop mode ──
    const clip = (pool ? pool[0] : newStem) + suffix;
    if (animData[stemKey] === newStem && animData[currentKey] === clip) return;
    animData[stemKey] = newStem;
    _crossFadeLayer(animData, currentKey, clip);
  }
}


// =========================================================
// PLAY LAYERED ANIMATION
// =========================================================

function playLayeredAnim(animData, animState) {
  const key = (animState || "idle").toLowerCase();
  const layers = ANIM_LAYERS[key];

  if (!layers) {
    // Unknown state — fall back to full-body single action
    _playSingleAction(animData, key);
    return;
  }

  _setLayer(animData, "lower", layers.lower);
  _setLayer(animData, "upper", layers.upper);
}


// =========================================================
// CROSS-FADE HELPERS
// =========================================================

/** Standard looping cross-fade. */
function _crossFadeLayer(animData, trackingKey, wantName) {
  const prev       = animData[trackingKey];
  const prevAction = prev ? animData.actions[prev] : null;
  const nextAction = animData.actions[wantName];

  if (!nextAction) return;  // clip unavailable — leave current running

  if (prevAction && prevAction !== nextAction) {
    prevAction.fadeOut(FADE_TIME);
  }

  nextAction.reset();
  nextAction.loop = THREE.LoopRepeat;
  nextAction.setEffectiveWeight(1);
  nextAction.fadeIn(FADE_TIME);
  nextAction.play();

  animData[trackingKey] = wantName;
}

/** LoopOnce cross-fade used for variant clips. Emits 'finished' so the
 *  re-roll listener can pick the next variant in the pool. */
function _crossFadeLayerOnce(animData, trackingKey, wantName) {
  // If the clip doesn't exist, try to fall back to any available variant
  let resolvedName = wantName;
  if (!animData.actions[wantName]) {
    // Attempt other clips in the pool before giving up
    const suffix = wantName.endsWith("_upper") ? "_upper" : "_lower";
    const layer  = suffix === "_upper" ? "upper" : "lower";
    const pool   = ANIM_VARIANTS[animData[layer + "Stem"]] || [];
    for (const stem of pool) {
      const alt = stem + suffix;
      if (animData.actions[alt]) { resolvedName = alt; break; }
    }
    if (!animData.actions[resolvedName]) return; // nothing available
  }

  const prev       = animData[trackingKey];
  const prevAction = prev ? animData.actions[prev] : null;
  const nextAction = animData.actions[resolvedName];

  if (prevAction && prevAction !== nextAction) {
    prevAction.fadeOut(FADE_TIME);
  }

  nextAction.reset();
  nextAction.loop = THREE.LoopOnce;
  nextAction.clampWhenFinished = false;
  nextAction.setEffectiveWeight(1);
  nextAction.fadeIn(FADE_TIME);
  nextAction.play();

  animData[trackingKey] = resolvedName;
}

/**
 * Attach a 'finished' listener to the mixer. Handles both reaction clip
 * completion (restores the activity upper layer) and variant re-rolls.
 * Call once per character at creation time.
 */
function setupVariantReroll(animData) {
  animData.mixer.addEventListener('finished', (e) => {
    const action = e.action;

    // ── Reaction finished → restore activity upper layer ──
    if (animData.reactionCurrent &&
        action === animData.actions[animData.reactionCurrent]) {
      animData.reactionCurrent = null;
      _resumeUpperAfterReaction(animData);
      return;
    }

    // ── Suppress variant re-rolls while a reaction is playing ──
    if (animData.reactionCurrent) return;

    // ── Re-roll upper variant ──
    if (animData.upperStem && ANIM_VARIANTS[animData.upperStem]) {
      const pool = ANIM_VARIANTS[animData.upperStem];
      if (pool.length > 1 && action === animData.actions[animData.upperCurrent]) {
        const chosen = _pickVariant(pool, animData.upperVariantLast);
        animData.upperVariantLast = chosen;
        _crossFadeLayerOnce(animData, "upperCurrent", chosen + "_upper");
      }
    }

    // ── Re-roll lower variant (rare, supported) ──
    if (animData.lowerStem && ANIM_VARIANTS[animData.lowerStem]) {
      const pool = ANIM_VARIANTS[animData.lowerStem];
      if (pool.length > 1 && action === animData.actions[animData.lowerCurrent]) {
        const chosen = _pickVariant(pool, animData.lowerVariantLast);
        animData.lowerVariantLast = chosen;
        _crossFadeLayerOnce(animData, "lowerCurrent", chosen + "_lower");
      }
    }
  });
}


// =========================================================
// REACTION ANIMATIONS
// =========================================================

// Maps reaction type → pool of upper-body clip stems.
// These are played as LoopOnce interrupts over the current
// upper layer, then the activity animation resumes.
// Stems must match GLB action names (with _upper suffix appended).
const REACTION_ANIMATIONS = {
  // Surprise family
  surprise:     ["react_surprise", "react_gasp"],
  startled:     ["react_startled"],
  shocked:      ["react_shocked", "react_gasp"],

  // Negative
  disgust:      ["react_disgust", "react_recoil"],
  fear:         ["react_fear", "react_cower"],
  angry_react:  ["react_angry", "react_fist"],

  // Positive
  laugh:        ["react_laugh", "react_chuckle", "react_laugh_big"],
  happy_react:  ["react_happy", "react_clap"],

  // Social / conversational
  nod:          ["react_nod", "react_nod_slow"],
  shake_head:   ["react_shake_head"],
  confused:     ["react_confused", "react_scratch_head"],
  interested:   ["react_interested", "react_lean"],
  shrug:        ["react_shrug"],

  // Environmental
  look_around:  ["react_look_around"],
};

/**
 * Play a reaction animation as a LoopOnce upper-body interrupt.
 * Fades out the current upper activity layer, plays the reaction,
 * then the finished listener restores the activity layer.
 */
function playReaction(animData, type) {
  const pool = REACTION_ANIMATIONS[type];
  if (!pool || !pool.length) return;

  // Pick a random variant, find one that exists in the GLB
  const shuffled = [...pool].sort(() => Math.random() - 0.5);
  let clipName = null;
  for (const stem of shuffled) {
    if (animData.actions[stem + "_upper"]) {
      clipName = stem + "_upper";
      break;
    }
  }
  if (!clipName) return; // none of the clips available yet

  // Fade out the current upper activity
  const prevAction = animData.upperCurrent
    ? animData.actions[animData.upperCurrent]
    : null;
  if (prevAction) prevAction.fadeOut(FADE_TIME);

  // Play reaction LoopOnce
  const action = animData.actions[clipName];
  action.reset();
  action.loop 