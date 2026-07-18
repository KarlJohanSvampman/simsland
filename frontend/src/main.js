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

// =========================================================
// ANIMBANK  (per-character stance/transition template mapping)
// =========================================================
// animBank[modelKey].stances = { standing: {idle,walk,run}, sitting_seat:
// {idle}, ... } and .transitions = [{from,to,template}, ...] — map each
// stance's idle/movement slot, and each authored stance-pair transition,
// to an animbank TEMPLATE id (animbank.html's Templates tab), not a raw
// clip, so this reuses the same reusable chain/variant abstraction as
// every other animation in the bank. Keyed the same way as meshbank (by
// the character's `model` field), since animbank derives its source key
// from the same GLB filename convention. See resolveLocomotionMap() below
// for the flattening into a single state->clip lookup, and animbank.js's
// STANCES config / backend/systems/posture.py for the matching key names.

let animBank = {};

async function loadAnimBank() {
  try {
    const res = await fetch('/api/animbank');
    animBank = await res.json();
  } catch (e) {
    console.warn('Animbank unavailable', e);
  }
}

// Canonical stance -> animation_state key. Hardcoded fallback only — once
// world["definitions"]["stance_templates"] arrives (every full WS
// snapshot, see _applyState()), _rebuildStanceMaps() below overwrites
// these from that shared vocabulary (the same data posture.py's
// _idle_key() and animbank.js's Stances panel read), so adding a new
// stance/locomotion slot is a data edit in the Definitions editor, not a
// change in three separate files.
let _STANCE_IDLE_KEY = {
  standing: "idle", sitting_seat: "sit_idle", sitting_floor: "sit_idle_floor",
  lying: "lie_idle", crouching: "crouch_idle", crawling: "crawl_idle",
  fallen_front: "fallen_front_idle", fallen_back: "fallen_back_idle",
  leaning_wall: "leaning_idle", carry: "carry_idle",
  unconscious: "unconscious_idle", dead: "dead_idle", intoxicated: "intoxicated_idle",
  // dragging/pushing are NOT real c["posture"] values on the backend (see
  // posture.py's _IDLE_KEY, which deliberately excludes them, same as
  // carry) — movement.py drives their animation_state directly from the
  // dragged/pushed prop's own template fields. These entries exist purely
  // so an animbank-authored template can override the hardcoded
  // ANIM_LAYERS["drag_idle"/"pushing"] fallback, same mechanism as carry.
  dragging: "drag_idle", pushing: "pushing",
};
let _STANCE_MOVE_KEY = {
  standing_walk: "walk", standing_run: "run",
  crouching_move: "crouch_walk", crawling_move: "crawl",
  carry_move: "carry_walk",
  intoxicated_walk: "drunk_walk", intoxicated_run: "drunk_run",
  dragging_move: "drag_move",
};

// Rebuilds _STANCE_IDLE_KEY/_STANCE_MOVE_KEY from stance_templates, and
// adds an ANIM_LAYERS fallback for any stance-derived key that doesn't
// already have one hand-tuned — e.g. carry_walk deliberately mixes "walk"
// legs with a "carry_idle" upper body, never overwrite an existing entry.
function _rebuildStanceMaps(defs) {
  const stances = defs && defs.stance_templates;
  if (!stances || !Object.keys(stances).length) return;   // keep hardcoded fallback

  const idleKey = {};
  const moveKey = {};
  for (const entry of Object.values(stances)) {
    if (!entry.idle_key) continue;
    idleKey[entry.key] = entry.idle_key;
    if (!(entry.idle_key in ANIM_LAYERS)) {
      ANIM_LAYERS[entry.idle_key] = { lower: entry.idle_key, upper: entry.idle_key };
    }
    for (const m of (entry.moves || [])) {
      if (!m.key) continue;
      moveKey[`${entry.key}_${m.slot}`] = m.key;
      if (!(m.key in ANIM_LAYERS)) {
        ANIM_LAYERS[m.key] = { lower: m.key, upper: m.key };
      }
    }
  }
  _STANCE_IDLE_KEY = idleKey;
  _STANCE_MOVE_KEY = moveKey;
}

// Resolves a character's stance/transition state->template mapping down to
// state->clip, using each template's first chain step (the loopable clip)
// — the live game only plays one continuous clip per stance/transition
// state, not a full template chain/notify sequence.
function resolveLocomotionMap(modelKey) {
  const src = animBank[modelKey];
  if (!src) return null;

  const templates = animBank._templates || {};
  const clipOf = (templateId) => templates[templateId]?.chain?.[0]?.clip;
  const resolved = {};

  for (const [stance, slots] of Object.entries(src.stances || {})) {
    for (const [slot, templateId] of Object.entries(slots || {})) {
      const clip = clipOf(templateId);
      if (!clip) continue;
      const key = slot === "idle" ? _STANCE_IDLE_KEY[stance] : _STANCE_MOVE_KEY[`${stance}_${slot}`];
      if (key) resolved[key] = clip;
    }
  }

  for (const t of (src.transitions || [])) {
    const clip = clipOf(t.template);
    if (clip) resolved[`${t.from}_to_${t.to}`] = clip;
  }

  // Legacy fallback — sources not yet migrated by animbank.js (e.g. an
  // animbank.json saved before this change and never reopened in the
  // authoring tool) still work via the old flat locomotion map.
  for (const [state, templateId] of Object.entries(src.locomotion || {})) {
    if (resolved[state]) continue;
    const clip = clipOf(templateId);
    if (clip) resolved[state] = clip;
  }

  return Object.keys(resolved).length ? resolved : null;
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

const loader = new GLTFLoader();

const characterAnimations = {};
const sims = {};
const characterAttachments = {};
const speechBubbles = {};   // id → { cssObject, div }
const props = {};
const propNodes = {};        // prop.id → { anchors, targets, ikHands } Maps of named Object3Ds
const propAnimations = {};   // prop.id → { mixer, actions, currentState }
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
      map:         texture,
      transparent: true,
      opacity:     1
    });
  }

  // No texture asset — fall back to the material's flat color (e.g. paint
  // swatches) before resorting to the generic wall/door/window defaults.
  const materialTemplate =
    getMaterialTemplate(
      definitions,
      wallData.material
    );

  if(materialTemplate?.color){

    return new THREE.MeshStandardMaterial({
      color:       parseInt(materialTemplate.color.replace("#", ""), 16),
      transparent: true,
      opacity:     1
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
    color,
    transparent: true,
    opacity:     1
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

  // Fill the gap between lower and upper exactly, so the "hollow" center
  // is seamless (no accidental unrendered slivers above/below the glass).
  const lowerHeight = 0.9;
  const upperHeight = 0.7;
  const glassHeight = WALL_HEIGHT - lowerHeight - upperHeight;
  const glassCenterY = (lowerHeight - upperHeight) / 2; // midpoint between the two solid pieces

  const glassGeo =
    horizontal
    ? new THREE.BoxGeometry(
        0.85,
        glassHeight,
        WALL_THICKNESS / 2
      )
    : new THREE.BoxGeometry(
        WALL_THICKNESS / 2,
        glassHeight,
        0.85
      );

  const lower = new THREE.Mesh(lowerGeo, mat);
  const upper = new THREE.Mesh(upperGeo, mat);
  const glass = new THREE.Mesh(glassGeo, glassMat);

  lower.position.y = -0.95;
  upper.position.y = 1.05;
  glass.position.y = glassCenterY;

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

// Walls/doors/windows come from the backend already fully resolved to world
// coordinates (building_manager.py's instantiate_floorplan projects each
// floorplan-local tile through local_to_world before it's sent), so each
// tile is positioned the same way every other entity in this file is —
// world coords minus the (10, 7) scene origin offset — no per-building
// local-space group/transform needed.
function updateFloorplanWalls(state){

  const active = new Set();

  const runtimeTiles =
    Array.isArray(state.tiles)
    ? state.tiles
    : Object.values(state.tiles || {});

  for(const tile of runtimeTiles){

    const walls =
      tile.walls || {};

    const x = tile.x - 10;
    const y = tile.y - 7;

    for(const side in walls){

      const wallData = walls[side];

      if(!wallData) continue;

      const wallKey =
        `${tile.x}_${tile.y}_${side}`;

      active.add(wallKey);

      if(wallRegistry[wallKey]){
        continue;
      }

      let mesh = null;

      if(wallData.type === "wall"){

        mesh = createWallMesh(
          x,
          y,
          side,
          wallData
        );
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

        scene.add(mesh);

        wallRegistry[
          wallKey
        ] = mesh;
      }
    }
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
  // These 5 states can be overridden per-character via animData.locomotionMap
  // (set in animbank.html) — see playLayeredAnim(), which checks that map
  // before falling back to these literal clip-name defaults.
  idle:          { lower: "idle",        upper: "idle"        },
  walk:          { lower: "walk",        upper: "walk"        },
  run:           { lower: "run",         upper: "run"         },
  crouch_idle:   { lower: "crouch_idle", upper: "crouch_idle" },
  crouch_walk:   { lower: "crouch_walk", upper: "crouch_walk" },

  // ── Standing interactions (idle legs + active upper) ──
  talk:          { lower: "idle",        upper: "talk"        },
  eat:           { lower: "idle",        upper: "eat"         },
  cook:          { lower: "idle",        upper: "cook"        },
  work:          { lower: "idle",        upper: "work"        },
  phone:         { lower: "idle",        upper: "phone"       },
  // Screen-tap/read loop — texting/checking/reading on the phone,
  // distinct from the ear-hold "phone" state above (calls/answering).
  // New stem: no exported clip yet, falls back gracefully per this
  // file's own documented ANIM_VARIANTS behavior until one is authored.
  phone_screen:  { lower: "idle",        upper: "phone_screen" },
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

  // ── Item stack (hand actions, orthogonal to body posture) ──
  add_to_stack:    { lower: "idle", upper: "add_to_stack"    },
  put_down_stack:  { lower: "idle", upper: "put_down_stack"  },
  search_stack:    { lower: "idle", upper: "search_stack"    },
  take_from_stack: { lower: "idle", upper: "take_from_stack" },

  // ── Carry (different upper depending on whether moving) ──
  carry_idle:    { lower: "idle",        upper: "carry_idle"  },
  carry_walk:    { lower: "walk",        upper: "carry_idle"  },

  // ── Movable props (drag/push) — full-body, unlike the upper-body-only
  // item-action states above, since dragging/pushing engages the whole
  // body, not just the arms. ──
  drag_idle:      { lower: "drag_idle",      upper: "drag_idle"      },
  drag_move:      { lower: "drag_move",      upper: "drag_move"      },
  start_dragging: { lower: "start_dragging", upper: "start_dragging" },
  let_go:         { lower: "let_go",         upper: "let_go"         },
  pushing:        { lower: "pushing",        upper: "pushing"        },

  // ── Seated (sit_idle lower folds legs; upper does activity) ──
  sit_idle:      { lower: "sit_idle",    upper: "sit_idle"    },
  sit_watch:     { lower: "sit_idle",    upper: "sit_watch"   },
  sit_eat:       { lower: "sit_idle",    upper: "eat"         },
  sit_talk:      { lower: "sit_idle",    upper: "talk"        },
  sit_phone:     { lower: "sit_idle",    upper: "phone"       },
  sit_phone_screen: { lower: "sit_idle", upper: "phone_screen" },
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

  // Phone screen — texting/checking/reading (falls back gracefully if
  // no dedicated "phone_type" clip is exported yet, same as any other
  // variant pool entry with a missing clip)
  phone_screen:  ["phone_screen", "phone_type"],

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

  // A character's animbank stance/transition mapping (see animbank.html's
  // Stances/Transitions panels) can override any state key, not just a
  // fixed allowlist — any stance idle/move slot or any authored
  // {from}_to_{to} transition pair resolves through here the same way.
  // Each maps to a single clip used for both lower and upper layers (no
  // separate upper-body variant for these, unlike interaction states).
  const override = animData.locomotionMap?.[key];
  const layers = override
    ? { lower: override.toLowerCase(), upper: override.toLowerCase() }
    : ANIM_LAYERS[key];

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
  action.loop = THREE.LoopOnce;
  action.clampWhenFinished = false;
  action.setEffectiveWeight(1);
  action.fadeIn(FADE_TIME);
  action.play();

  animData.reactionCurrent = clipName;
}

/**
 * Called when a reaction clip finishes. Re-enters the activity
 * upper layer (respecting variants if applicable).
 */
function _resumeUpperAfterReaction(animData) {
  if (!animData.upperStem) return;

  const pool = ANIM_VARIANTS[animData.upperStem];
  if (pool && pool.length > 1) {
    // Re-enter the variant cycle
    const chosen = _pickVariant(pool, animData.upperVariantLast);
    animData.upperVariantLast = chosen;
    _crossFadeLayerOnce(animData, "upperCurrent", chosen + "_upper");
  } else {
    // Single-clip upper — resume with LoopRepeat
    const clip = (pool ? pool[0] : animData.upperStem) + "_upper";
    _crossFadeLayer(animData, "upperCurrent", clip);
  }
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

// =========================================================
// HELD ITEM / STACK ATTACHMENT
// Simplified visual: only the topmost held_stack item (left hand) and any
// location==="held" inventory item (right hand, the "free hand") ever get
// a mesh — no literal multi-item 3D stacking. Diffed by item id, not
// deep-equal, since item dicts are heavier than the small `equipped` dict
// the clothing diff above compares.
// =========================================================

async function updateStackAttachment(id, characterModel, heldStack, itemTemplates) {
    const prev = (characterAttachments[id] || {}).stackItem || null;
    const top = heldStack && heldStack.length ? heldStack[heldStack.length - 1] : null;
    if ((prev?.itemId || null) === (top?.id || null)) return;

    if (prev?.mesh) prev.mesh.parent?.remove(prev.mesh);
    if (!characterAttachments[id]) characterAttachments[id] = {};

    if (!top) { characterAttachments[id].stackItem = null; return; }
    const tpl = itemTemplates?.[top.template_id];
    if (!tpl?.model) { characterAttachments[id].stackItem = null; return; }
    const mesh = await attachItemToBone(characterModel, "mixamorigLeftHand", tpl);
    characterAttachments[id].stackItem = { itemId: top.id, mesh };
}

async function updateHeldItemAttachment(id, characterModel, inventory, itemTemplates) {
    const prev = (characterAttachments[id] || {}).heldItem || null;
    const held = (inventory || []).find(i => i.location === "held") || null;
    if ((prev?.itemId || null) === (held?.id || null)) return;

    if (prev?.mesh) prev.mesh.parent?.remove(prev.mesh);
    if (!characterAttachments[id]) characterAttachments[id] = {};

    if (!held) { characterAttachments[id].heldItem = null; return; }
    const tpl = itemTemplates?.[held.template_id];
    if (!tpl?.model) { characterAttachments[id].heldItem = null; return; }
    const mesh = await attachItemToBone(characterModel, "mixamorigRightHand", tpl);
    characterAttachments[id].heldItem = { itemId: held.id, mesh };
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

  const runtimeTiles =
    Array.isArray(state.tiles)
    ? state.tiles
    : Object.values(state.tiles || {});

  for(const tile of runtimeTiles){

    if(!tile.floor) continue;

    const worldKey =
      `${tile.x}_${tile.y}`;

    active.add(worldKey);

    if(!floorRegistry[worldKey]){

      const mesh =
        createFloorMesh(
          tile.x - 10,
          tile.y - 7,
          tile.floor
        );

      scene.add(mesh);

      floorRegistry[worldKey] = mesh;
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
}


// Matches the World Editor's TILE_COLORS palette (editor-main.js) so
// outdoor tiles look consistent between the editor and the live game.
const _TILE_TYPE_COLORS = {
  grass:    0x3f7a3f,
  road:     0x333333,
  sidewalk: 0xaaaaaa,
  park:     0x55aa55,
  water:    0x3377cc,
};

function createTile(tile){

  const mesh = new THREE.Mesh(

    new THREE.PlaneGeometry(1,1),

    new THREE.MeshStandardMaterial({

      color:
        _TILE_TYPE_COLORS[tile.type]
        ?? (tile.walkable ? 0x557799 : 0xaa3333),

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
  y: tile.y,
  tileType: tile.type
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

    // Floorplan-interior tiles (runtime_tiles, injected into this same
    // array alongside outdoor ground) are rendered separately by
    // updateFloorplanFloors()/createFloorMesh — this generic ground
    // renderer is for outdoor tiles only. Interior tiles have no
    // `walkable` field, so createTile's fallback treated them as
    // "blocked" and rendered a solid red box on top of the real floor.
    if(tile.interior){
      continue;
    }

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

  // Cylinder placeholder — blue-grey, easy to spot, clearly "not a real model"
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(0.38, 0.38, 1.0, 16),
    new THREE.MeshStandardMaterial({ color: 0x6688aa, roughness: 0.7 })
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

      // ── Prop animation state sync ──
      // If the server changed anim_state, cross-fade to the new clip.
      const pa = propAnimations[prop.id];
      if (pa && prop.anim_state && prop.anim_state !== pa.currentState) {
        const clipName = prop.anim_state.toLowerCase();
        const action   = pa.actions[clipName];
        if (action) {
          // Stop all currently playing actions with a short fade
          for (const a of Object.values(pa.actions)) {
            if (a.isRunning()) a.fadeOut(0.15);
          }
          action.reset().fadeIn(0.15).play();
        }
        pa.currentState = prop.anim_state;
      }

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

  // loadModelCached returns { scene, animations } — use .scene
  const loaded =
    await loadModelCached(
      propModelPath
    );

  const model = loaded.scene;

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

  // Scan anchor_* / target_* / ik_* nodes
  const pn = { anchors: new Map(), targets: new Map(), ikHands: new Map() };
  model.traverse(scanPropNode.bind(null, pn));
  propNodes[prop.id] = pn;

  // Build animation system for props that have clips (doors, drawers, etc.)
  if (loaded.animations && loaded.animations.length > 0) {
    const mixer   = new THREE.AnimationMixer(model);
    const actions = {};
    for (const clip of loaded.animations) {
      const name = clip.name.toLowerCase();
      const action = mixer.clipAction(clip);
      action.loop = THREE.LoopOnce;
      action.clampWhenFinished = true;  // hold last frame (e.g., door stays open)
      actions[name] = action;
    }
    propAnimations[prop.id] = { mixer, actions, currentState: null };
  }
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
    delete propNodes[id];
    delete propAnimations[id];
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
    // .trim() guards against a whitespace-only utterance slipping through
    // some server-side code path — truthy but visually blank, which would
    // otherwise show as an empty bubble box.
    const utterance = speech?.utterance?.trim();

    // Toggle visibility via cssObject.visible, not div.style.display —
    // CSS2DRenderer.render() unconditionally overwrites element.style.display
    // ('' or 'none') every frame based on frustum visibility alone, so a
    // manually-set "none" here gets clobbered on the very next frame and the
    // bubble reappears as an empty white box. .visible is the one flag the
    // renderer actually checks before doing that.
    if(utterance){
      div.textContent = utterance;
      cssObject.visible = true;
    } else {
      cssObject.visible = false;
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

      // Store latest server state so IK can read it every frame
      if (characterAnimations[id]) {
        const prev = characterAnimations[id].state;
        characterAnimations[id].state = c;

        // Re-equip clothing if equipped dict changed
        const prevEquipped = JSON.stringify(prev?.equipped || {});
        const nextEquipped = JSON.stringify(c.equipped   || {});
        if (prevEquipped !== nextEquipped) {
          equipAllClothing(id, sims[id], sims[id], c.equipped || {}, definitions);
        }

        updateStackAttachment(id, sims[id], c.held_stack, definitions?.item_templates || {});
        updateHeldItemAttachment(id, sims[id], c.inventory, definitions?.item_templates || {});
      }

      // Sync position from server unless the IK system has already taken
      // over fine-alignment (isAnchored flag set by updateIK once close).
      if (!characterAnimations[id]?.isAnchored) {
        sims[id].position.set(
          c.x - 10,
          0,
          c.y - 7
        );
      }

            // =========================
      // ANIMATION STATE
      // =========================

      const animState =
        c.animation_state || "idle";

      const animData =
        characterAnimations[id];

      if(animData){
        // ── Reaction interrupt ──
        // Check for a new reaction pushed by the server this tick.
        // We compare against lastReactionTick so we only fire it once.
        const reaction = c.animation_reaction;
        if (reaction && reaction.tick != null) {
          if (animData.lastReactionTick == null ||
              reaction.tick > animData.lastReactionTick) {
            animData.lastReactionTick = reaction.tick;
            playReaction(animData, reaction.type);
          }
        }

        // ── Activity / locomotion layer ──
        playLayeredAnim(animData, animState);
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

  // Without this, Three.js frustum-culls a SkinnedMesh using its
  // bind-pose (T-pose) bounding sphere, so a moving character can skip
  // GPU bone-matrix uploads for a frame and render a stale pose
  // overlapping the current one — visible as the model appearing to
  // render "twice". Same fix already used in meshbank.js/animbank.js.
  model.traverse(o => {
    if (!o.isMesh) return;
    o.frustumCulled = false;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    mats.forEach(m => {
      if (!m) return;
      m.side       = THREE.DoubleSide;
      m.depthWrite = true;
    });
  });
  model.traverse(o => {
    if (o.isSkinnedMesh && o.skeleton) o.skeleton.pose();
  });

  // Some exported rigs (seen on Mixamo-derived character GLBs) bake a
  // cm-to-meters scale correction onto BOTH the top-level object node and
  // the skeleton's own root bone, instead of just once — the two 0.01
  // factors compound to 0.0001 on the skeleton while the mesh geometry
  // only inherits the single 0.01, so skinning renders the character at
  // ~1% of its intended size. Same fix as meshbank.js/animbank.js: detect
  // the mismatch and correct the skeleton root's own scale to match the
  // mesh's world scale again.
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

  // Some exported rigs also bake an erroneous rotation (seen: 90° about X)
  // onto the shared parent of the mesh and skeleton root, tipping/
  // contorting skinned characters instead of standing them upright. The
  // mesh's own geometry has no compensating rotation to cancel this back
  // out, so the fix is to zero out the skeleton root's WORLD rotation
  // entirely (not match it to the mesh's, which carries the same tilt).
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

    // =========================
    // ANIMATION SETUP
    // =========================

    let mixer = null;

    const actions = {};

    if(model.animations?.length){

      mixer = new THREE.AnimationMixer(model);

      // Build lower + upper filtered variants of every clip,
      // plus keep the full clip under its original name.
      for(const clip of model.animations){
        const name = clip.name.toLowerCase();

        // Full-body action (fallback)
        actions[name] = mixer.clipAction(clip);

        // Lower-body filtered clip
        const lowerClip = makeLayerClip(clip, "lower");
        if(lowerClip.tracks.length){
          actions[name + "_lower"] = mixer.clipAction(lowerClip);
        }

        // Upper-body filtered clip
        const upperClip = makeLayerClip(clip, "upper");
        if(upperClip.tracks.length){
          actions[name + "_upper"] = mixer.clipAction(upperClip);
        }
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

  // Clicking the thin/gappy skinned-mesh geometry directly (limbs, gaps
  // between them, etc.) is an unreliable click target, especially at the
  // isometric zoom levels this game plays at — add a simple invisible
  // cylinder covering the character's full silhouette so any click within
  // roughly their outline selects them, not just a click that happens to
  // land exactly on a rendered triangle.
  const selectionHitbox = new THREE.Mesh(
    new THREE.CylinderGeometry(0.4, 0.4, 1.8, 8),
    new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
  );
  selectionHitbox.name = "_selectionHitbox";
  selectionHitbox.position.y = 0.9;
  selectionHitbox.castShadow = false;
  selectionHitbox.receiveShadow = false;
  model.add(selectionHitbox);

  selectable.push(model);

  scene.add(model);

  sims[id] = model;
 // =========================
// BONE SCANNING
// =========================

  const bones = {};
  model.traverse(node => {
    if (node.isBone || node.isObject3D) {
      bones[node.name.toLowerCase()] = node;
    }
  });

 // =========================
// EQUIPMENT
// =========================

characterAttachments[id] = {};

await equipAllClothing(
    id,
    model,
    model,
    c.equipped || {},
    definitions
);

await updateStackAttachment(id, model, c.held_stack, definitions?.item_templates || {});
await updateHeldItemAttachment(id, model, c.inventory, definitions?.item_templates || {});

  const animData = {
    mixer,
    actions,
    // Per-character override for locomotion states (idle/walk/run/
    // crouch_idle/crouch_walk), authored as animbank templates and
    // resolved to concrete clip names here — see resolveLocomotionMap().
    locomotionMap: resolveLocomotionMap(character?.model),
    // Two-layer tracking — current clip names (with _lower / _upper suffix)
    lowerCurrent:     null,
    upperCurrent:     null,
    // Stem tracking — the ANIM_LAYERS stem name (without suffix)
    lowerStem:        null,
    upperStem:        null,
    // Variant re-roll — last chosen stem per layer (to avoid repeating)
    lowerVariantLast: null,
    upperVariantLast: null,
    // Reaction layer — upper-body interrupt clip
    reactionCurrent:  null,
    lastReactionTick: null,
    // Legacy single-layer fallback
    current:          null,
    bones,
    state: c,
  };

  setupVariantReroll(animData);

  characterAnimations[id] = animData;
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

    // Speech bubbles are CSS2DObject children of the character mesh —
    // scene.remove(mesh) drops them from the Three.js scene graph but
    // doesn't tell speechBubbles/CSS2DRenderer to clean up, leaving an
    // orphaned DOM element behind (visible as a stray empty bubble) if
    // this character ever comes back (e.g. after going off-grid), since
    // getOrCreateBubble would otherwise still find the stale entry.
    if(speechBubbles[id]){
      mesh.remove(speechBubbles[id].cssObject);
      delete speechBubbles[id];
    }

    scene.remove(mesh);

    removeSelectable(mesh);
    delete characterAnimations[id];
    delete sims[id];
  }
}
// =========================================================
// NODE SCANNING HELPERS
// =========================================================

function scanPropNode(pn, node) {
  const ln = node.name.toLowerCase();
  if (ln.startsWith("anchor_"))  pn.anchors.set(ln, node);
  if (ln.startsWith("target_"))  pn.targets.set(ln, node);
  // Hand IK reach points: ik_hand_r, ik_hand_l, ik_finger_r, ik_finger_l
  if (ln.startsWith("ik_"))      pn.ikHands.set(ln, node);
}

// =========================================================
// TWO-BONE IK SOLVER
// =========================================================
// Rotates `upper` (shoulder/upperArm) and `lower` (forearm) bones
// so that `tip` (hand/wrist) reaches `targetWS` (world Vector3).
// `poleWS` hints which direction the elbow bends.
// `weight` [0..1] blends between the animation pose and the IK result.
//
// Prop GLB convention for hand targets:
//   ik_hand_r  — right hand reach point
//   ik_hand_l  — left hand reach point
//   ik_finger_r / ik_finger_l — fingertip for buttons (finger IK only)
//
// Mixamo arm chain bone names (lowercase):
//   upper: mixamorigrightarm / mixamorigleftarm
//   lower: mixamorigrightforearm / mixamorigleftforearm
//   tip:   mixamiorigrighthand / mixamoriglefthand
// =========================================================

// Right-arm default pole direction (elbow bends outward + slightly down)
const _POLE_RIGHT = new THREE.Vector3( 1, -0.5, 0).normalize();
const _POLE_LEFT  = new THREE.Vector3(-1, -0.5, 0).normalize();

// Pre-allocated scratch vectors / quaternions (no GC in hot path)
const _ikRoot = new THREE.Vector3();
const _ikMid  = new THREE.Vector3();
const _ikTip  = new THREE.Vector3();
const _ikTgt  = new THREE.Vector3();
const _ikDir  = new THREE.Vector3();
const _ikElbow = new THREE.Vector3();
const _ikQa   = new THREE.Quaternion();
const _ikQb   = new THREE.Quaternion();
const _ikQpar = new THREE.Quaternion();

function solveTwoBoneIK(upper, lower, tip, targetWS, poleWS, weight) {
  if (weight < 0.001) return;

  upper.getWorldPosition(_ikRoot);
  lower.getWorldPosition(_ikMid);
  tip.getWorldPosition(_ikTip);

  const lenU = _ikRoot.distanceTo(_ikMid);
  const lenL = _ikMid.distanceTo(_ikTip);
  const maxR = (lenU + lenL) * 0.9999;

  // Direction root → target, clamped to chain length
  _ikDir.subVectors(targetWS, _ikRoot);
  const dist = Math.min(_ikDir.length(), maxR);
  if (dist < 0.0001) return;
  _ikDir.normalize();
  _ikTgt.copy(_ikRoot).addScaledVector(_ikDir, dist);

  // Law of cosines → shoulder bend angle
  const u = lenU, l = lenL, d = dist;
  const cosA = THREE.MathUtils.clamp((u*u + d*d - l*l) / (2*u*d), -1, 1);
  const angA  = Math.acos(cosA);

  // Build orthonormal frame in the IK plane
  const xAxis = _ikDir;                                               // root → target
  const pole  = poleWS || new THREE.Vector3(0, -1, 0);
  const zAxis = new THREE.Vector3().crossVectors(xAxis, pole).normalize();
  if (zAxis.lengthSq() < 0.0001) zAxis.set(0, 0, 1);
  const yAxis = new THREE.Vector3().crossVectors(zAxis, xAxis);       // elbow-bend axis

  // Desired upper-arm direction: rotate xAxis by -angA around zAxis
  const ca = Math.cos(-angA), sa = Math.sin(-angA);
  const desiredUpper = new THREE.Vector3(
    xAxis.x * ca + yAxis.x * sa,
    xAxis.y * ca + yAxis.y * sa,
    xAxis.z * ca + yAxis.z * sa,
  ).normalize();

  // ── Rotate upper bone ──
  const currUpper = new THREE.Vector3().subVectors(_ikMid, _ikRoot).normalize();
  if (currUpper.dot(desiredUpper) < 0.9999) {
    _ikQa.setFromUnitVectors(currUpper, desiredUpper);
    _applyWorldDeltaQ(upper, _ikQa, weight);
    upper.updateWorldMatrix(false, true);
  }

  // Re-read positions after upper moved
  lower.getWorldPosition(_ikMid);
  tip.getWorldPosition(_ikTip);

  // ── Rotate lower bone ──
  const currLower = new THREE.Vector3().subVectors(_ikTip, _ikMid).normalize();
  const wantLower = new THREE.Vector3().subVectors(_ikTgt, _ikMid).normalize();
  if (currLower.dot(wantLower) < 0.9999) {
    _ikQa.setFromUnitVectors(currLower, wantLower);
    _applyWorldDeltaQ(lower, _ikQa, weight);
    lower.updateWorldMatrix(false, true);
  }
}

/**
 * Apply a world-space rotation delta on top of a bone's current local rotation.
 * Converts worldDeltaQ into the bone's local space via the parent world quaternion,
 * then slerp-blends by `weight` before applying (so weight=1 is full IK).
 */
function _applyWorldDeltaQ(bone, worldDeltaQ, weight) {
  if (bone.parent) {
    bone.parent.getWorldQuaternion(_ikQpar);
  } else {
    _ikQpar.identity();
  }
  // localDelta = inv(parentWorldQ) * worldDeltaQ * parentWorldQ
  _ikQb.copy(_ikQpar).invert()
       .premultiply(worldDeltaQ)  // = worldDeltaQ * _ikQpar^-1  ... hmm
  // Correct formula: localDelta = inv(parent) * worldDelta * parent
  _ikQb.copy(_ikQpar).invert();
  _ikQb.multiply(worldDeltaQ).multiply(_ikQpar);

  // Blend identity → localDelta by weight
  _ikQa.identity().slerp(_ikQb, weight);
  bone.quaternion.premultiply(_ikQa);
  bone.updateMatrix();
}


// =========================================================
// IK + PROCEDURAL INTERACTIONS  (called every frame)
// =========================================================

function updateIK(id) {
  const data = characterAnimations[id];
  const model = sims[id];
  if (!data || !model || !data.state) return;

  const c = data.state;

  // ---- Anchor snap & target facing ------------------------------------
  // When seated (seat_prop_id set), the SEAT drives position snapping
  // while the activity target prop drives the facing direction.
  // Without a seat, both come from the activity target as before.
  const actTargetId  = c.activity?.target_id;
  const seatPropId   = c.seat_prop_id;
  const viewTargetId = c.view_target_id ?? actTargetId;

  // ── Position: walk normally until close to anchor, then fine-align ──
  // ANCHOR_SNAP_DIST: how close (world units ≈ tiles) the character must
  // be before IK lerp takes over from the server grid position.
  const ANCHOR_SNAP_DIST = 1.2;

  const anchorSourceId = seatPropId ?? actTargetId;
  if (anchorSourceId) {
    const pn = propNodes[anchorSourceId];
    if (pn) {
      const interaction = seatPropId ? "sit" : c.activity?.interaction;
      const anchorKey   = `anchor_${interaction}`;
      const anchorNode  = pn.anchors.get(anchorKey) || pn.anchors.values().next().value;
      if (anchorNode) {
        anchorNode.getWorldPosition(_ikA);
        const distToAnchor = model.position.distanceTo(_ikA);

        if (distToAnchor < ANCHOR_SNAP_DIST) {
          // Close enough — IK takes over position; lerp into exact spot
          data.isAnchored = true;
          model.position.lerp(_ikA, 0.15);
        } else {
          // Still walking — release IK lock so server pos syncs normally
          data.isAnchored = false;
        }
      } else {
        data.isAnchored = false;
      }
    } else {
      data.isAnchored = false;
    }
  } else {
    // No anchor target — always track server position
    data.isAnchored = false;
  }

  // ── Facing: always toward the view target (desk/computer/etc.) ──────
  if (viewTargetId) {
    const pn = propNodes[viewTargetId];
    if (pn) {
      const interaction = c.activity?.interaction;
      const targetKey   = `target_${interaction}`;
      const targetNode  = pn.targets.get(targetKey) || pn.targets.values().next().value;
      if (targetNode) {
        targetNode.getWorldPosition(_ikB);
      } else if (pn.root) {
        // No target_ node on this prop — face its world origin
        pn.root.getWorldPosition(_ikB);
      } else {
        _ikB.set(-1e9, 0, -1e9); // sentinel — skip rotation
      }
      const dx = _ikB.x - model.position.x;
      const dz = _ikB.z - model.position.z;
      if (Math.abs(dx) > 0.01 || Math.abs(dz) > 0.01) {
        model.rotation.y = THREE.MathUtils.lerp(
          model.rotation.y, Math.atan2(dx, dz), 0.10
        );
      }
    }
  }

  // ---- Head look IK ---------------------------------------------------
  // Rotate the head/neck bone to glance toward look_target (2D grid coord).
  // We apply a clamped Y-rotation in the bone's local space so it blends
  // naturally with whatever animation is playing.
  const headBone = data.bones?.head || data.bones?.neck;
  const lookTarget = c.look_target;

  if (headBone) {
    let desiredYaw = 0; // neutral

    if (lookTarget) {
      // look_target is a 2D grid position {x, y}
      const tx = (lookTarget.x ?? 0) - 10;
      const tz = (lookTarget.y ?? 0) - 7;
      const yawToTarget = Math.atan2(tx - model.position.x, tz - model.position.z);
      // Relative to character body yaw, clamped to ±75°
      desiredYaw = THREE.MathUtils.clamp(
        yawToTarget - model.rotation.y,
        -Math.PI * 0.42,
        Math.PI * 0.42
      );
    }

    headBone.rotation.y = THREE.MathUtils.lerp(
      headBone.rotation.y,
      desiredYaw,
      lookTarget ? 0.08 : 0.04   // snap faster when looking, drift back slower
    );
  }

  // ---- Hand IK ----------------------------------------------------------
  // When a character is in the "using" phase and the prop has ik_hand_r /
  // ik_hand_l nodes, pull the arm chain toward that point procedurally.
  // The IK weight blends in when the using phase begins and out when it ends.
  // -----------------------------------------------------------------------
  const phase = c.activity?.phase;
  const inUse = (phase === "using");

  // Smooth weight in/out (lerp toward 1 when active, 0 otherwise)
  data.handIkWeight = THREE.MathUtils.lerp(
    data.handIkWeight ?? 0,
    inUse ? 1 : 0,
    0.08                           // ~12 frames to fully blend
  );
  const ikW = data.handIkWeight;

  if (ikW > 0.01 && actTargetId) {
    const pn = propNodes[actTargetId];
    if (pn) {
      const bones = data.bones;

      // ── Right hand ──
      const ikHandR = pn.ikHands.get("ik_hand_r") || pn.ikHands.get("ik_finger_r");
      if (ikHandR) {
        const shoulder = bones["mixamorigrightarm"];
        const forearm  = bones["mixamorigrightforearm"];
        const hand     = bones["mixamiorigrighthand"] || bones["mixamorigrighthand"];
        if (shoulder && forearm && hand) {
          const targetWS = new THREE.Vector3();
          ikHandR.getWorldPosition(targetWS);
          solveTwoBoneIK(shoulder, forearm, hand, targetWS, _POLE_RIGHT, ikW);
        }
      }

      // ── Left hand ──
      const ikHandL = pn.ikHands.get("ik_hand_l") || pn.ikHands.get("ik_finger_l");
      if (ikHandL) {
        const shoulder = bones["mixamorigleftarm"];
        const forearm  = bones["mixamorigleftforearm"];
        const hand     = bones["mixamoriglefthand"];
        if (shoulder && forearm && hand) {
          const targetWS = new THREE.Vector3();
          ikHandL.getWorldPosition(targetWS);
          solveTwoBoneIK(shoulder, forearm, hand, targetWS, _POLE_LEFT, ikW);
        }
      }
    }
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

    const inspector = document.getElementById("viewerInspector");
    inspector.classList.toggle("expanded", d.type === "character");

    // Activity/animation state come from the last server tick's character
    // payload (cached on characterAnimations[id].state), not userData —
    // userData is set once at load time and never carries live sim state.
    const liveState = d.type === "character"
      ? characterAnimations[d.id]?.state
      : null;
    const activityLabel = liveState
      ? (liveState.activity?.type
          ? `Doing: ${liveState.activity.type}`
          : `State: ${liveState.animation_state || "idle"}`)
      : "";

    document
      .getElementById(
        "viewerSelection"
      ).innerHTML = `
        <b>${d.type}</b><br>
        ${d.tileType ? `Type: ${d.tileType}<br>` : ""}
        ${d.id || ""}<br>
        ${d.name || ""}<br>
        ${activityLabel}
      `;

    if(d.type === "character" && d.id){
      showCharacterLLMLog(d.id);
    }
  }
);

// =========================================================
// HOUSEHOLD ADMIN MODAL (mailbox double-click)
// =========================================================
// The viewer's inspector above is otherwise strictly read-only — this is
// the one deliberate exception, for administering a mailbox's household
// (family name, owned floorplans, member characters). Modal CSS/markup
// ported from editor.html/editor-main.js, the only place this pattern
// existed before (the live viewer had no modal infrastructure at all).

window.closeModal = function(id) {
  document.getElementById(id).classList.remove("open");
};

function openModal(id) {
  document.getElementById(id).classList.add("open");
}

document.querySelectorAll(".modal-overlay").forEach(overlay => {
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.classList.remove("open");
  });
});

renderer.domElement.addEventListener("dblclick", (event) => {
  mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
  mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);

  const hits = raycaster
    .intersectObjects(selectable, true)
    .filter(h => !h.object.userData?.ignoreRaycast);
  if (!hits.length) return;

  let obj = hits[0].object;
  while (obj && !obj.userData?.type) obj = obj.parent;
  if (!obj) return;

  const d = obj.userData;
  if (d.type === "prop" && d.template === "mailbox") {
    openHouseholdModal(d.id);
  }
});

function _findProp(propId) {
  return _worldState._propsMap?.[propId]
    ?? (_worldState.props || []).find(p => p.id === propId);
}

// Guards a modal refresh against a slower, earlier fetch overwriting the
// panel after the user has since closed it or double-clicked a different
// mailbox — same idiom as _llmLogSelectionToken below.
let _householdModalToken = 0;

async function openHouseholdModal(propId) {
  const token = ++_householdModalToken;
  openModal("modal-household");

  const householdId = _findProp(propId)?.household_id ?? null;
  if (!householdId) {
    _renderCreateHouseholdForm(propId);
    return;
  }

  document.getElementById("householdModalTitle").textContent = "Household";
  document.getElementById("householdModalBody").innerHTML = "<i>Loading…</i>";

  let detail = null;
  try {
    const res = await fetch(`/api/household/${encodeURIComponent(householdId)}/admin?sim_id=default`);
    const data = await res.json();
    detail = data.ok ? data.household : null;
  } catch { /* detail stays null, handled below */ }

  if (token !== _householdModalToken) return;
  if (!detail) {
    document.getElementById("householdModalBody").innerHTML =
      `<div class="modal-empty">Household not found.</div>`;
    return;
  }
  _renderHouseholdAdminPanel(detail, propId);
}

function _renderCreateHouseholdForm(propId) {
  document.getElementById("householdModalTitle").textContent = "New Household";
  const body = document.getElementById("householdModalBody");
  body.innerHTML = "";

  const p = document.createElement("p");
  p.textContent = "This mailbox isn't linked to a household yet.";
  body.appendChild(p);

  const nameInput = document.createElement("input");
  nameInput.placeholder = "Family name";
  nameInput.style.width = "100%";
  nameInput.style.marginBottom = "8px";
  body.appendChild(nameInput);

  const createBtn = document.createElement("button");
  createBtn.textContent = "Create Household";
  createBtn.addEventListener("click", async () => {
    const res = await fetch("/api/household/create?sim_id=default", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: nameInput.value || null, mailbox_prop_id: propId }),
    });
    const data = await res.json();
    if (data.ok) {
      // Reflect the new link locally so re-opening this mailbox before
      // the next WS snapshot/delta arrives still sees it.
      const prop = _findProp(propId);
      if (prop) prop.household_id = data.household.id;
      openHouseholdModal(propId);
    }
  });
  body.appendChild(createBtn);
}

function _renderHouseholdAdminPanel(h, mailboxPropId) {
  document.getElementById("householdModalTitle").textContent = h.name || "Household";
  const body = document.getElementById("householdModalBody");
  body.innerHTML = "";

  const refresh = () => openHouseholdModal(mailboxPropId);

  // --- Family name ---
  const nameRow = document.createElement("div");
  nameRow.className = "modal-row";
  const nameInput = document.createElement("input");
  nameInput.value = h.name || "";
  nameInput.placeholder = "Family name";
  const nameSaveBtn = document.createElement("button");
  nameSaveBtn.textContent = "Save";
  nameSaveBtn.addEventListener("click", async () => {
    await fetch("/api/household/set_name?sim_id=default", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ household_id: h.id, name: nameInput.value }),
    });
    refresh();
  });
  nameRow.appendChild(nameInput);
  nameRow.appendChild(nameSaveBtn);
  body.appendChild(nameRow);

  // --- Members ---
  const memH = document.createElement("h4");
  memH.textContent = "Members";
  body.appendChild(memH);

  if (!h.members.length) {
    const empty = document.createElement("div");
    empty.className = "modal-empty";
    empty.textContent = "No characters assigned.";
    body.appendChild(empty);
  }
  for (const m of h.members) {
    const row = document.createElement("div");
    row.className = "modal-row";
    const label = document.createElement("span");
    label.textContent = m.name || m.id;
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", async () => {
      await fetch("/api/household/remove_member?sim_id=default", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character_id: m.id }),
      });
      refresh();
    });
    row.appendChild(label);
    row.appendChild(removeBtn);
    body.appendChild(row);
  }

  const addMemberRow = document.createElement("div");
  addMemberRow.className = "modal-row";
  const memberSelect = document.createElement("select");
  const addMemberBtn = document.createElement("button");
  addMemberBtn.textContent = "Add";
  addMemberRow.appendChild(memberSelect);
  addMemberRow.appendChild(addMemberBtn);
  body.appendChild(addMemberRow);

  fetch("/api/household/characters?sim_id=default")
    .then(r => r.json())
    .then(data => {
      if (!data.ok) return;
      memberSelect.innerHTML = "";
      for (const c of data.characters) {
        const opt = document.createElement("option");
        opt.value = c.id;
        // Current membership shown inline rather than filtered out —
        // assigning someone already in another household silently moves
        // them (household_id is a single scalar read by many systems),
        // so make that visible instead of hiding it.
        const current = c.household_id === h.id
          ? " (this household)"
          : c.household_id ? " (in another household)" : "";
        opt.textContent = `${c.name || c.id}${current}`;
        memberSelect.appendChild(opt);
      }
    });

  addMemberBtn.addEventListener("click", async () => {
    if (!memberSelect.value) return;
    await fetch("/api/household/add_member?sim_id=default", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ household_id: h.id, character_id: memberSelect.value }),
    });
    refresh();
  });

  // --- Floorplans ---
  const bldH = document.createElement("h4");
  bldH.textContent = "Floorplans";
  body.appendChild(bldH);

  if (!h.buildings.length) {
    const empty = document.createElement("div");
    empty.className = "modal-empty";
    empty.textContent = "No floorplans assigned.";
    body.appendChild(empty);
  }
  for (const b of h.buildings) {
    const row = document.createElement("div");
    row.className = "modal-row";
    const label = document.createElement("span");
    label.textContent = `${b.template} (${b.x}, ${b.y})`;
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "Unassign";
    removeBtn.addEventListener("click", async () => {
      await fetch("/api/household/unassign_building?sim_id=default", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ building_id: b.id }),
      });
      refresh();
    });
    row.appendChild(label);
    row.appendChild(removeBtn);
    body.appendChild(row);
  }

  const addBuildingRow = document.createElement("div");
  addBuildingRow.className = "modal-row";
  const buildingSelect = document.createElement("select");
  const addBuildingBtn = document.createElement("button");
  addBuildingBtn.textContent = "Assign";
  addBuildingRow.appendChild(buildingSelect);
  addBuildingRow.appendChild(addBuildingBtn);
  body.appendChild(addBuildingRow);

  fetch("/api/household/available_buildings?sim_id=default")
    .then(r => r.json())
    .then(data => {
      if (!data.ok) return;
      buildingSelect.innerHTML = "";
      if (!data.buildings.length) {
        const opt = document.createElement("option");
        opt.textContent = "No available floorplans";
        opt.disabled = true;
        buildingSelect.appendChild(opt);
        addBuildingBtn.disabled = true;
        return;
      }
      for (const b of data.buildings) {
        const opt = document.createElement("option");
        opt.value = b.id;
        opt.textContent = `${b.template} (${b.x}, ${b.y})`;
        buildingSelect.appendChild(opt);
      }
    });

  addBuildingBtn.addEventListener("click", async () => {
    if (!buildingSelect.value) return;
    await fetch("/api/household/assign_building?sim_id=default", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ household_id: h.id, building_id: buildingSelect.value }),
    });
    refresh();
  });
}

// Selection token guards against a slower, earlier fetch overwriting the
// panel after the user has already clicked a different character/tile.
let _llmLogSelectionToken = 0;

async function showCharacterLLMLog(charId){
  const token = ++_llmLogSelectionToken;
  const container = document.getElementById("viewerSelection");

  container.innerHTML += `<hr><i>Loading last LLM request/response…</i>`;

  let entries;
  try {
    const res = await fetch(`/debug/prompt-log/${encodeURIComponent(charId)}`);
    ({ entries } = await res.json());
  } catch (e) {
    if(token !== _llmLogSelectionToken) return;
    container.innerHTML += `<br><span style="color:#f88">Failed to load: ${e.message}</span>`;
    return;
  }

  if(token !== _llmLogSelectionToken) return;

  if(!entries || !entries.length){
    container.innerHTML += `<br><i>No LLM calls logged yet for this character.</i>`;
    return;
  }

  const latest = entries[0];
  const prompt = latest.messages?.find(m => m.role === "user")?.content ?? "";
  const system = latest.messages?.find(m => m.role === "system")?.content ?? "";

  // Prompts are compact single-line JSON (no whitespace, to save tokens) —
  // pretty-print for readability here since this is a debug view, not the
  // actual LLM-facing payload.
  const prettyPrompt = _tryPrettyJSON(prompt);
  const prettyResponse = _tryPrettyJSON(latest.response);

  const ts = latest.ts ? new Date(latest.ts * 1000).toLocaleTimeString() : "?";

  container.innerHTML += `
    <hr>
    <b>Last LLM call</b><br>
    ${ts} · ${latest.elapsed_s ?? "?"}s ${latest.cached ? "(cached)" : ""}<br>
    ${system ? `<details><summary>System prompt</summary><pre>${_escapeHTML(system)}</pre></details>` : ""}
    <details open><summary>Request</summary><pre>${_escapeHTML(prettyPrompt)}</pre></details>
    <details open><summary>Response</summary><pre>${_escapeHTML(prettyResponse)}</pre></details>
  `;
}

function _tryPrettyJSON(text){
  if(typeof text !== "string") return JSON.stringify(text, null, 2);
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function _escapeHTML(str){
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// =========================================================
// WEBSOCKET + STATE APPLICATION
// =========================================================

// Load meshbank once at startup so model references resolve
loadMeshbank();

// Load animbank once at startup so per-character locomotion mapping resolves
loadAnimBank();

// Cached last-known full world state so delta patches have something to merge into
let _worldState = {};

// Camera viewport in world-tile space — sent to server so it broadcasts
// only the slice this client is actually looking at.
let _viewport = { cx: 0, cy: 0, zoom: 2 };

function _sendViewport(ws) {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "viewport", ..._viewport }));
  }
}

// Recompute viewport center from camera and notify server.
// Call whenever the camera moves significantly.
function _updateViewport(ws) {
  // Center on controls.target (the ground point the camera orbits/looks
  // at), not camera.position — the isometric camera sits at a constant
  // offset from its target (e.g. (20,20,20) looking at (0,0,0)), so using
  // position instead left every query centered ~28 units away from what
  // was actually on screen.
  const target = controls.target ?? new THREE.Vector3();
  const cx = Math.round(target.x);
  const cy = Math.round(target.z);
  // Map zoom level from the OrthographicCamera's own .zoom (magnification)
  // — OrbitControls' mouse-wheel zoom scales this directly and leaves
  // camera.position untouched for orthographic cameras, so distance-to-
  // target (the old metric here) never changed when the user scrolled.
  const zoom = camera.zoom > 1.8 ? 3 : camera.zoom > 0.9 ? 2 : 1;
  if (cx !== _viewport.cx || cy !== _viewport.cy || zoom !== _viewport.zoom) {
    _viewport = { cx, cy, zoom };
    _sendViewport(ws);
  }
}

async function _applyState(state) {
  definitions = state.definitions || definitions;
  _rebuildStanceMaps(state.definitions);
  updateTiles(state);
  await updateProps(state);
  updateFloorplanFloors(state);
  updateFloorplanWalls(state);
  await updateCharacters(state);
  updateSpeechBubbles(state);
}

async function _applyDelta(delta) {
  // Merge changed characters and props into cached world state
  if (delta.characters) {
    _worldState.characters = { ...(_worldState.characters || {}), ...delta.characters };
  }
  if (delta.props) {
    // Props may be array or dict on the server; normalise to dict by id
    if (!_worldState._propsMap) {
      _worldState._propsMap = {};
      for (const p of (_worldState.props || [])) _worldState._propsMap[p.id] = p;
    }
    Object.assign(_worldState._propsMap, delta.props);
    _worldState.props = Object.values(_worldState._propsMap);
  }
  await _applyState(_worldState);
}

function connectWS() {
  const ws = new WebSocket(`ws://${location.hostname}:8000/ws`);

  ws.onopen = () => {
    _sendViewport(ws);
  };

  ws.onmessage = async (e) => {
    const msg = JSON.parse(e.data);

    if (msg.type === "snapshot") {
      // Full state for this viewport — store and apply
      _worldState = msg;
      await _applyState(msg);
    } else if (msg.type === "delta") {
      // Partial update — merge and apply
      await _applyDelta(msg);
    } else {
      // Legacy: server sent plain state without a type field
      _worldState = msg;
      await _applyState(msg);
    }
  };

  ws.onclose = () => {
    // Reconnect after 2 s
    setTimeout(connectWS, 2000);
  };

  // Report viewport when camera moves (throttled to once per second)
  let _vpTimer = null;
  controls.addEventListener("change", () => {
    if (_vpTimer) return;
    _vpTimer = setTimeout(() => {
      _vpTimer = null;
      _updateViewport(ws);
    }, 1000);
  });

  return ws;
}

connectWS();

// =========================================================
// RENDER LOOP
// =========================================================

// =========================================================
// WALL CAMERA OCCLUSION
// =========================================================
// Fade any wall/door/window segment that sits between the camera and a
// character, so the camera can always see characters inside rooms instead
// of staring at the outside of a wall.

const _occlusionRaycaster = new THREE.Raycaster();
const _occludedWalls      = new Set(); // wallKey currently faded
const WALL_FADE_FACTOR    = 0.15;      // fraction of normal opacity while faded

function _tagBaseOpacity(mesh) {
  if (mesh.material && mesh.material.userData.baseOpacity === undefined) {
    mesh.material.userData.baseOpacity = mesh.material.opacity ?? 1;
  }
}

function _setWallFaded(entry, faded) {
  entry.traverse((obj) => {
    if (obj.isMesh && obj.material && "opacity" in obj.material) {
      _tagBaseOpacity(obj);
      const base = obj.material.userData.baseOpacity;
      obj.material.opacity = faded ? base * WALL_FADE_FACTOR : base;
    }
  });
}

function updateWallOcclusion() {
  const hitKeysThisFrame = new Set();
  const _target = new THREE.Vector3();
  const _dir    = new THREE.Vector3();
  const _origin = new THREE.Vector3();

  // For an OrthographicCamera, view rays are all parallel to the camera's
  // forward direction — they do NOT converge at camera.position the way
  // perspective rays do. Using (target - camera.position) as the ray only
  // matches reality for a target sitting exactly on the camera's optical
  // axis; for anyone off-center it tests a ray that isn't actually what's
  // occluding them on screen, which is why walls were fading in and out
  // seemingly at random. The correct ray for orthographic occlusion is
  // parallel to the camera's constant view direction, offset back from
  // each target individually.
  camera.getWorldDirection(_dir);
  const RAY_BACK_DISTANCE = 50;

  for (const id in sims) {
    sims[id].getWorldPosition(_target);
    _target.y += 1.0; // aim roughly torso/head height, not the feet

    _origin.copy(_dir).multiplyScalar(-RAY_BACK_DISTANCE).add(_target);

    _occlusionRaycaster.set(_origin, _dir);
    _occlusionRaycaster.far = Math.max(RAY_BACK_DISTANCE - 0.15, 0);

    for (const wallKey in wallRegistry) {
      if (hitKeysThisFrame.has(wallKey)) continue;
      const entry = wallRegistry[wallKey];
      if (_occlusionRaycaster.intersectObject(entry, true).length) {
        hitKeysThisFrame.add(wallKey);
      }
    }
  }

  for (const wallKey of hitKeysThisFrame) {
    if (!_occludedWalls.has(wallKey)) {
      const entry = wallRegistry[wallKey];
      if (entry) _setWallFaded(entry, true);
    }
  }

  for (const wallKey of _occludedWalls) {
    if (!hitKeysThisFrame.has(wallKey)) {
      const entry = wallRegistry[wallKey];
      if (entry) _setWallFaded(entry, false);
    }
  }

  _occludedWalls.clear();
  for (const k of hitKeysThisFrame) _occludedWalls.add(k);
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  const delta = 0.016;

  for (const id in characterAnimations) {
    const data = characterAnimations[id];
    if (data.mixer) data.mixer.update(delta);
    // IK runs after the mixer has set bone transforms for this frame
    updateIK(id);
  }

  // Tick prop animation mixers
  for (const id in propAnimations) {
    propAnimations[id].mixer.update(delta);
  }

  updateWallOcclusion();

  renderer.render(scene, camera);
  cssRenderer.render(scene, camera);
}

animate();
