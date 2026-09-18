import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls }
from "three/examples/jsm/controls/OrbitControls.js";
import { clone }
from "three/examples/jsm/utils/SkeletonUtils.js";
import { CSS2DRenderer, CSS2DObject }
from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { VRButton } from "three/examples/jsm/webxr/VRButton.js";
import { XRControllerModelFactory }
from "three/examples/jsm/webxr/XRControllerModelFactory.js";
import {

  getPropTemplate,

  getCharacterTemplate,

  getFloorplanTemplate,

  resolveProp,

  resolveCharacter,

  resolveItem,

  getTemplate,

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

// Per-character-template override, one tier more specific than
// resolveLocomotionMap()'s per-shared-model one — authored in the
// Character Creator's Animation Mapping tab (animbank.json's
// _character_overrides bucket), keyed by c["template"] (the
// character_templates id a character was spawned from), not by the
// shared model/mesh key. Unlike resolveLocomotionMap, each key's
// lower/upper are resolved independently so a character can override
// just the upper body (e.g. "eat") without forcing its lower body away
// from whatever ANIM_LAYERS/locomotionMap would otherwise pick (many
// interaction states are asymmetric, e.g. sit_eat's sit_idle legs).
function resolveCharacterOverrideMap(templateId) {
  const src = animBank._character_overrides?.[templateId];
  if (!src) return null;

  const templates = animBank._templates || {};
  const clipOf = (id) => templates[id]?.chain?.[0]?.clip;
  const resolved = {};

  for (const [key, slots] of Object.entries(src)) {
    const lower = slots.lower && clipOf(slots.lower);
    const upper = slots.upper && clipOf(slots.upper);
    if (lower || upper) resolved[key] = { lower, upper };
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

// Confirmed live bug: meshbank.html's editor lets you set a per-asset
// Scale X/Y/Z and saves it into meshbank[key].transform.scale, but the
// live game viewer only ever read `asset.mesh` (resolveModel() above) --
// it never looked at `asset.transform` at all, so a scale change made
// and saved in the mesh bank had zero effect on how the model actually
// renders in-game. This returns that saved scale (default 1/1/1, same
// as meshbank.js's own ensureTransform() default) for a caller to apply
// to the loaded THREE object.
function resolveModelScale(modelRef) {
  let asset = meshbank[modelRef];
  if (!asset) {
    // Confirmed live bug: a prop_templates entry can store the .glb
    // PATH directly (e.g. stove_andf_oven's "/resources/props/
    // stove_and_oven.glb") instead of a meshbank key -- resolveModel()
    // above already tolerates both forms when picking which file to
    // LOAD ("backward compat: raw paths pass through"), but this only
    // ever looked the ref up as a meshbank KEY, so a raw-path prop's
    // saved scale was silently never found (always fell back to 1/1/1,
    // no matter what was set and saved in the mesh bank editor). Fall
    // back to matching by the asset's own .mesh path instead.
    asset = Object.values(meshbank).find(a => a.mesh === modelRef);
  }
  const scale = asset?.transform?.scale;
  return {
    x: scale?.x ?? 1,
    y: scale?.y ?? 1,
    z: scale?.z ?? 1,
  };
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
// WEBXR (VR director-mode -- see frontend/src/operator_view.js)
// =========================================================
// The desktop `camera` above is Orthographic, isometric -- WebXR's
// stereoscopic rendering requires a real PerspectiveCamera (confirmed via
// research: an orthographic camera cannot drive a headset). Rather than
// replacing the desktop view, this adds a genuinely separate render path
// alongside it: a PerspectiveCamera parented inside `xrDolly` (the
// player's rig -- moving the dolly moves the player through the world;
// the headset's own head-tracking rides on top of that, same as any
// standard three.js WebXR "room + locomotion" setup). `animate()` below
// picks whichever camera is active each frame based on
// renderer.xr.isPresenting.
renderer.xr.enabled = true;

const xrCamera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.05, 1000);
const xrDolly = new THREE.Group();
xrDolly.add(xrCamera);
xrDolly.position.set(0, 1.6, 8);   // start a few tiles back from map origin, eye height
scene.add(xrDolly);

const xrControllerModelFactory = new XRControllerModelFactory();
const xrControllers = [0, 1].map(i => {
  const controller = renderer.xr.getController(i);
  controller.userData.inputSource = null;
  controller.addEventListener("connected", (event) => {
    controller.userData.inputSource = event.data;
  });
  controller.addEventListener("disconnected", () => {
    controller.userData.inputSource = null;
  });

  // Laser pointer -- a simple line from the controller into the scene,
  // used both to show where it's aimed and as the raycast direction for
  // character selection (see updateXRFrame() below).
  const rayGeometry = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, 0, -5),
  ]);
  const ray = new THREE.Line(rayGeometry, new THREE.LineBasicMaterial({ color: 0xffe066 }));
  ray.name = "ray";
  ray.scale.z = 1;
  controller.add(ray);

  const grip = renderer.xr.getControllerGrip(i);
  grip.add(xrControllerModelFactory.createControllerModel(grip));
  xrDolly.add(controller);
  xrDolly.add(grip);

  return controller;
});

// The character (if any) each controller is currently pointed at --
// operator_view.js reads this on a trigger/squeeze press rather than
// re-raycasting itself, since updateXRFrame() below already does it once
// per controller per frame.
const xrHover = { 0: null, 1: null };

// Whether VR director-mode is currently toggled on (see
// operator_view.js's squeeze-hold handler) -- purely a render-time cue
// (ray tint) since this file has no other concept of "director mode" of
// its own; operator_view.js owns the actual state and gesture logic.
let _xrDirectorModeActive = false;
window.setDirectorModeActive = (active) => { _xrDirectorModeActive = !!active; };

function updateXRFrame(){
  if (!renderer.xr.isPresenting) return;

  // Thumbstick locomotion -- standard Quest/Touch axes layout (axes[2]/
  // axes[3] on the primary/left stick; axes[0]/axes[1] are the touchpad
  // on older profiles and unused here). Moves the dolly along the
  // horizontal plane, oriented to the *camera's* current facing so
  // "forward" always means "the way you're looking."
  const raycaster = new THREE.Raycaster();
  const tmpMatrix = new THREE.Matrix4();
  const forward = new THREE.Vector3();
  xrCamera.getWorldDirection(forward);
  forward.y = 0;
  forward.normalize();
  const right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0));

  xrControllers.forEach((controller, i) => {
    const gamepad = controller.userData.inputSource?.gamepad;
    if (gamepad && gamepad.axes.length >= 4) {
      const [, , stickX, stickY] = gamepad.axes;
      const DEAD_ZONE = 0.15;
      const SPEED = 0.06;
      if (Math.abs(stickX) > DEAD_ZONE || Math.abs(stickY) > DEAD_ZONE) {
        xrDolly.position.addScaledVector(right, stickX * SPEED);
        xrDolly.position.addScaledVector(forward, -stickY * SPEED);
      }
    }

    // Raycast from this controller's pointing direction against the
    // character models (sims{}) so operator_view.js knows what a
    // trigger/squeeze press should act on.
    tmpMatrix.identity().extractRotation(controller.matrixWorld);
    raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld);
    raycaster.ray.direction.set(0, 0, -1).applyMatrix4(tmpMatrix);

    const hits = raycaster.intersectObjects(Object.values(sims), true)
      .filter(h => !h.object.userData?.ignoreRaycast);
    let hitCharId = null;
    if (hits.length) {
      let obj = hits[0].object;
      while (obj && !obj.userData?.type) obj = obj.parent;
      if (obj?.userData?.type === "character") hitCharId = obj.userData.id;
    }
    xrHover[i] = hitCharId;
    const rayColor = hitCharId ? 0x66ff99 : (_xrDirectorModeActive ? 0xff6644 : 0xffe066);
    controller.getObjectByName("ray").material.color.set(rayColor);
  });
}

// Read-only hooks for frontend/src/operator_view.js -- it has no other
// way to reach this module's private renderer/scene/dolly/controller
// state (this file's established convention is window.* getters, not ES
// exports -- see window.getSelectedCharacterId above this session).
window.getXRContext = () => ({
  renderer, dolly: xrDolly, controllers: xrControllers, hover: xrHover, sims,
});
window.setSelectedCharacterId = (id) => {
  selectedCharacterId = id;
  if (id) renderCharacterInspector(id);
};

// VR entry is operator_view.html-only (director-mode's own surface, see
// frontend/src/operator_view.js) -- the plain game viewer (index.html)
// doesn't load operator_view.js and has no #directorPanel element, so
// this button simply never appears there.
if (document.getElementById("directorPanel")) {
  const vrButton = VRButton.createButton(renderer);
  vrButton.style.zIndex = "9999";
  document.body.appendChild(vrButton);
}

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
// Floor for how far out the camera can scroll -- with no minZoom, a user
// could zoom out indefinitely while the server's viewport window stayed
// capped at its widest tier's radius (see main.py::_view_radius()), leaving
// everything past that ring unloaded/black instead of streaming more in.
// Set just below the tier-0 threshold in _updateViewport() below so the
// widest radius tier is always reachable but nothing goes further than it
// actually covers.
controls.minZoom = 0.15;

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

// =========================================================
// CLOCK PANEL -- date/weekday above a round analog clock face, the
// current time_scale multiplier below it. Neither world["calendar"] nor
// time_scale are part of the WS snapshot/delta payload (api/view.py
// doesn't carry either), so this polls the existing /admin/state
// endpoint directly on a plain interval rather than needing a new field
// threaded through the whole delta-broadcast path for something that
// only needs to refresh a couple times a minute. Built entirely in JS
// (not static HTML in index.html/operator_view.html) since it's shared,
// generic UI with no page-specific behavior -- one function call here
// covers both pages with nothing to keep in sync between two HTML files.
// =========================================================

// Shared with renderCharacterInspector()'s sleep-wake-time display below
// (module scope, not inside the IIFE, so both can read/write it) -- the
// most recently fetched calendar plus the world tick it corresponds to,
// used to project "wake up at <tick>" into a real date/time-of-day.
let _lastCalendar = null;
let _lastCalendarWorldTick = null;

(function setupClockPanel(){
  const ADMIN_BASE = `http://${location.hostname}:8000/admin`;

  const toggleBtn = document.createElement("button");
  toggleBtn.id = "clockToggleBtn";
  toggleBtn.title = "Toggle clock";
  toggleBtn.textContent = "🕓";
  Object.assign(toggleBtn.style, {
    position: "fixed", top: "10px", left: "54px", zIndex: 9999,
    width: "34px", height: "34px", background: "rgba(0,0,0,0.85)",
    color: "white", border: "1px solid #444", borderRadius: "6px",
    fontSize: "16px", cursor: "pointer",
  });
  document.body.appendChild(toggleBtn);

  // Bottom-left, floating over the 3D viewport itself rather than
  // docked in the top chrome row -- that row (icon buttons + the event
  // timeline) and the left column (outliner, full viewport height once
  // expanded) already fill essentially all available space at this
  // window size; a game-HUD-style corner widget over the 3D view avoids
  // fighting either for room. Clear of the Director Panel, which docks
  // bottom-RIGHT on operator_view.html.
  const panel = document.createElement("div");
  panel.id = "clockPanel";
  Object.assign(panel.style, {
    position: "fixed", bottom: "10px", left: "270px", zIndex: 9000,
    width: "150px", background: "rgba(0,0,0,0.82)", border: "1px solid #444",
    borderRadius: "6px", color: "white", fontFamily: "monospace",
    boxSizing: "border-box", padding: "8px", textAlign: "center",
  });
  panel.innerHTML = `
    <div id="clockDateLine" style="font-size:12px; margin-bottom:4px;">--</div>
    <svg id="clockFace" viewBox="0 0 100 100" width="110" height="110" style="display:block; margin:0 auto;">
      <circle cx="50" cy="50" r="47" fill="#1a1a1a" stroke="#666" stroke-width="2"/>
      ${Array.from({length: 12}, (_, i) => {
        const angle = (i / 12) * Math.PI * 2;
        const x1 = 50 + Math.sin(angle) * 41, y1 = 50 - Math.cos(angle) * 41;
        const x2 = 50 + Math.sin(angle) * 46, y2 = 50 - Math.cos(angle) * 46;
        return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#888" stroke-width="1.5"/>`;
      }).join("")}
      <text id="clockDayNightIcon" x="50" y="70" text-anchor="middle" font-size="12">☀️</text>
      <line id="clockHourHand" x1="50" y1="50" x2="50" y2="28" stroke="#eee" stroke-width="3.5" stroke-linecap="round"/>
      <line id="clockMinuteHand" x1="50" y1="50" x2="50" y2="16" stroke="#9cf" stroke-width="2.5" stroke-linecap="round"/>
      <circle cx="50" cy="50" r="2.5" fill="#f66"/>
    </svg>
    <div id="clockScaleLine" style="font-size:11px; margin-top:6px; opacity:.8;">--</div>
  `;
  document.body.appendChild(panel);

  toggleBtn.addEventListener("click", () => {
    panel.style.display = panel.style.display === "none" ? "" : "none";
  });

  const WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  async function refreshClock(){
    let data;
    try {
      const res = await fetch(`${ADMIN_BASE}/state`);
      data = await res.json();
    } catch {
      return;   // best-effort -- keep the last-known display rather than blanking it
    }
    const cal = data.calendar || {};
    const hour = cal.hour ?? 0, minute = cal.minute ?? 0;
    _lastCalendar = cal;
    _lastCalendarWorldTick = _worldState.tick ?? null;

    document.getElementById("clockDateLine").textContent =
      `${(cal.weekday || WEEKDAY_ORDER[0]).slice(0, 3)}, ${MONTH_NAMES[(cal.month || 1) - 1]} ${cal.day ?? "?"}, ${cal.year ?? "?"}`;

    // Daytime taken as 6am-8pm, matching this project's own dusk/dawn
    // framing elsewhere (e.g. streetlight/lighting logic) rather than a
    // strict sunrise/sunset calc -- there's no real seasonal daylight
    // model to compute an exact boundary from.
    const isDaytime = hour >= 6 && hour < 20;
    document.getElementById("clockDayNightIcon").textContent = isDaytime ? "☀️" : "🌙";

    const hourAngle = ((hour % 12) / 12) * 360 + (minute / 60) * 30;
    const minuteAngle = (minute / 60) * 360;
    document.getElementById("clockHourHand").setAttribute(
      "transform", `rotate(${hourAngle} 50 50)`);
    document.getElementById("clockMinuteHand").setAttribute(
      "transform", `rotate(${minuteAngle} 50 50)`);

    document.getElementById("clockScaleLine").textContent = `${data.time_scale ?? 1}x speed`;
  }

  refreshClock();
  setInterval(refreshClock, 3000);
})();

const _WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const _MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Projects the most recently fetched calendar (see _lastCalendar above)
// forward by a number of seconds (1 tick == 1 sim-second, this project's
// established convention) -- used to turn "wakes up in N ticks" into a
// real date + time-of-day rather than a bare tick count. Standard
// Gregorian month/leap-year math via a real Date object (the sim's own
// calendar values look like an ordinary real calendar, e.g.
// {year:2026,month:8,day:26,...}); weekday is advanced from the
// calendar's OWN weekday field by whole days elapsed rather than trusting
// JS Date's day-of-week, in case the sim's own convention ever drifts
// from real-world Gregorian weekdays.
function _projectCalendarForward(cal, seconds){
  if(!cal || cal.year == null) return null;
  const base = new Date(Date.UTC(cal.year, (cal.month || 1) - 1, cal.day || 1, cal.hour || 0, cal.minute || 0, cal.second || 0));
  const daysBefore = Math.floor(base.getTime() / 86400000);
  base.setUTCSeconds(base.getUTCSeconds() + seconds);
  const daysAfter = Math.floor(base.getTime() / 86400000);
  const daysElapsed = daysAfter - daysBefore;

  const startIdx = _WEEKDAY_ORDER.indexOf(cal.weekday);
  const weekday = startIdx >= 0
    ? _WEEKDAY_ORDER[((startIdx + daysElapsed) % 7 + 7) % 7]
    : null;

  return {
    year: base.getUTCFullYear(), month: base.getUTCMonth() + 1, day: base.getUTCDate(),
    hour: base.getUTCHours(), minute: base.getUTCMinutes(), weekday,
  };
}

function _formatProjectedTime(proj){
  if(!proj) return null;
  const ampmHour = ((proj.hour % 12) || 12);
  const ampm = proj.hour < 12 ? "AM" : "PM";
  const weekdayLabel = proj.weekday ? `${proj.weekday.slice(0, 3)}, ` : "";
  return `${weekdayLabel}${_MONTH_NAMES[proj.month - 1]} ${proj.day} at ${ampmHour}:${String(proj.minute).padStart(2, "0")} ${ampm}`;
}

// Per the user's explicit ask: "Recent Memories" must show WHEN each one
// was committed. tick == a real in-game second (sim_loop.py's own
// convention), so a memory's own tick projects against the last-fetched
// live calendar exactly like the "Wakes up: ..." display above does --
// this works for a PAST tick too (a negative seconds delta), not just a
// future one.
function _formatMemoryTimestamp(tick){
  if(!_lastCalendar || _lastCalendarWorldTick == null || tick == null) return null;
  const proj = _projectCalendarForward(_lastCalendar, tick - _lastCalendarWorldTick);
  return _formatProjectedTime(proj);
}

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
const thoughtBubbles = {};  // id → { cssObject, div }  -- debug-only, see DEBUG OVERLAY SETTINGS
const badges = {};          // id → { cssObject, div }  -- debug-only, see DEBUG OVERLAY SETTINGS
const debugEventBubbles = {}; // id → { cssObject, div } -- debug-only, action/activity/reaction/violation

// Currently selected character (perception debug overlay -- vision/hearing
// rings + LOS lines, only ever shown for this one character). Nothing else
// in this file previously tracked "who is selected" as real state -- the
// inspector panel is otherwise transient DOM writes with no backing variable.
let selectedCharacterId = null;
// Per the user's explicit ask: nothing selected -> Inspector hidden
// entirely, and a click while something IS selected always deselects
// first (never jumps straight to a different selection) -- see the
// pointerdown handler below and _applyInspectorVisibility().
let _somethingSelected = false;
// Ground-ring highlight that follows whichever character is currently
// selected -- created lazily on first use, re-parented onto the newly
// selected character's own model (sims[id]) so it moves/rotates with them
// for free instead of needing its own per-frame position sync against
// world coordinates. See updateSelectionOverlay(), called from animate().
let _selectionRing = null;
let _selectionRingParent = null;
const props = {};
const propNodes = {};        // prop.id → { anchors, targets, ikHands } Maps of named Object3Ds
const propAnimations = {};   // prop.id → { mixer, actions, currentState }
const placedItems = {};      // item.id → THREE object (dropped/delivered items, e.g. a newspaper)
const loadingPlacedItems = {};
const worldObjects = {};     // world_object.id → THREE object (service-worker-spawned props, e.g. mail bundles)
const loadingWorldObjects = {};
const responders = {};       // responder.id → THREE object (police/medical/fire, en route or just arrived)
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
  // jog_to/sneak_to (see systems/movement.py's jog_speed/sneak_speed) --
  // no dedicated clips exist yet, so these reuse the closest existing gait
  // as a placeholder (walk for jog, the crouched crouch_walk for sneak's
  // "trying not to be noticed" read) until real ones are authored. Same
  // "not yet authored, falls back gracefully" pattern as phone_screen
  // above -- per-character overrides in animbank.html still win over this.
  jog:           { lower: "walk",        upper: "walk"        },
  sneak:         { lower: "crouch_walk", upper: "crouch_walk" },

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

// A character standing around with nothing to do (activity type "wait")
// or truly idle (no activity at all, not moving) visually shifts weight/
// paces a little instead of standing perfectly still. Purely a render-
// layer position offset on top of the server's real x/y -- never touches
// c.x/c.y, so it can't affect pathfinding, anchor reservation, or
// occupancy. Per-character phase (hashed from id) keeps a room full of
// idling characters from swaying in unison.
function _idlePaceOffset(id, c, isMoving) {
  if (isMoving) return null;
  const activityType = c.activity?.type;
  const isWaiting = activityType === "wait";
  const isTrulyIdle = !activityType;
  if (!isWaiting && !isTrulyIdle) return null;

  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) | 0;
  const phase = ((hash % 1000) / 1000) * Math.PI * 2;

  const t = performance.now() / 1000;
  // Waiting on something reads a bit more restless than plain idling.
  const period = isWaiting ? 3.2 : 5.5;
  const amplitude = isWaiting ? 0.18 : 0.10;
  const angle = (t / period) * Math.PI * 2 + phase;
  return {
    dx: Math.sin(angle) * amplitude,
    dz: Math.sin(angle * 0.6) * amplitude * 0.5,
  };
}

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

// Resolves one layer (lower/upper) of a state key through three tiers,
// most to least specific: 1) this character's own animbank override
// (animData.characterMap, per character_template — can set just one of
// lower/upper), 2) this character's shared body-model override
// (animData.locomotionMap — a single clip applied to both layers, same
// as before), 3) the global ANIM_LAYERS default for this layer.
function _resolveAnimLayer(animData, key, slot) {
  const charSlot = animData.characterMap?.[key]?.[slot];
  if (charSlot) return charSlot.toLowerCase();
  const modelOverride = animData.locomotionMap?.[key];
  if (modelOverride) return modelOverride.toLowerCase();
  return ANIM_LAYERS[key]?.[slot];
}

function playLayeredAnim(animData, animState) {
  const key = (animState || "idle").toLowerCase();

  const lower = _resolveAnimLayer(animData, key, "lower");
  const upper = _resolveAnimLayer(animData, key, "upper");

  if (!lower && !upper) {
    // Unknown state — fall back to full-body single action
    _playSingleAction(animData, key);
    return;
  }

  _setLayer(animData, "lower", lower);
  _setLayer(animData, "upper", upper);
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


function _normalizeBoneName(name){
    // Real rigs disagree on "mixamorig:Head" vs "mixamorigHead" (colon or
    // not) and casing -- strip everything but alphanumerics and lowercase
    // so CLOTHING_SLOT_BONES/attachItemToBone callers match regardless of
    // which convention a given .glb export used.
    return (name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function findBone(root, boneName){

    let found = null;
    const target = _normalizeBoneName(boneName);

    root.traverse(node=>{

        if(node.isBone &&
           _normalizeBoneName(node.name) === target){

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

// Mirrors backend/systems/clothing.py's CLOTHING_SLOTS bone assignments
// (the real, populated 14-slot vocabulary c["worn"]/item_templates use) --
// prefixed for this rig's actual bone names and expanded to bone pairs for
// the slots clothing.py flags "bilateral" (mirrored left/right pieces).
// Replaces the old hat/upper_layer1/.../gloves mapping, which was for
// c["equipped"] -- a separate, always-empty 6-slot dict nothing in the
// backend ever actually writes to (see equipAllClothing below).
const CLOTHING_SLOT_BONES = {
    head:        ["mixamorigHead"],
    hair:        ["mixamorigHead"],
    neck:        ["mixamorigNeck"],
    outerwear:   ["mixamorigSpine2"],
    torso:       ["mixamorigSpine1"],
    undershirt:  ["mixamorigSpine1"],
    legs:        ["mixamorigHips"],
    underwear:   ["mixamorigHips"],
    socks:       ["mixamorigLeftFoot",     "mixamorigRightFoot"],
    feet:        ["mixamorigLeftFoot",     "mixamorigRightFoot"],
    hands:       ["mixamorigLeftHand",     "mixamorigRightHand"],
    wrist_l:     ["mixamorigLeftForeArm"],
    wrist_r:     ["mixamorigRightForeArm"],
    accessory:   ["mixamorigSpine2"],
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

    const boneNames = CLOTHING_SLOT_BONES[slot] || [];
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
// Called on character load and again whenever worn changes.
// Stores attached meshes in characterAttachments[id].clothing
// so they can be removed/replaced without reloading the character.
//
// Reads c["worn"] (systems/clothing.py's CLOTHING_SLOTS vocabulary --
// what Character Creator's Outfit tab and the live game's actual
// dressing/undressing actions both populate) against
// definitions.item_templates, not c["equipped"]/definitions.
// clothing_templates -- that pairing looked equivalent but nothing in
// the backend ever writes to c["equipped"] (always all-null) and
// clothing_templates has no entries at all, so it silently rendered
// nothing regardless of what a character was actually wearing.
// =========================================================

async function equipAllClothing(id, characterModel, characterRoot, worn, definitions) {
    const itemTemplates = definitions?.item_templates || {};

    // Remove any previously attached clothing
    const prev = (characterAttachments[id] || {}).clothing || {};
    for (const meshes of Object.values(prev)) {
        for (const m of meshes) m.parent?.remove(m);
    }

    if (!characterAttachments[id]) characterAttachments[id] = {};
    characterAttachments[id].clothing = {};

    for (const [slot, item] of Object.entries(worn || {})) {
        const templateId = item?.template_id;
        if (!templateId) continue;
        const tpl = itemTemplates[templateId];
        if (!tpl) { console.warn("Item template not found:", templateId); continue; }
        // Items without a .model (every clothing item_templates entry,
        // today -- no clothing mesh assets exist in this project yet)
        // are silently skipped by attachClothing()'s own guard; this
        // wiring just makes them start rendering automatically the
        // moment real meshes are added, no further code change needed.

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
  applyWallSideTransform(mesh, prop, resolveProp(definitions, prop));
  mesh.userData = {

    type: "prop",

    id: prop.id,

    template: prop.template
  };

  mesh.visible = !prop.hidden;

  selectable.push(mesh);
  scene.add(mesh);

  return mesh;
}

// Per the user's explicit ask: a wall_mounted prop instance carrying a
// real wall_side ("north"|"south"|"east"|"west") renders flush against
// that tile edge and facing outward, instead of centered like a normal
// floor prop -- no backend collision change needed (wall_mounted
// already fully exempts margin, see systems/prop_placement.py). No
// north/south/east/west -> world-direction convention existed
// anywhere else in this codebase to inherit (confirmed: nothing reads
// floorplan tiles' own per-edge wall data), so this establishes one --
// standard map convention, north = -y/-z (up), matching this file's
// existing world->scene offset (x-10, y-7). Exact rotation.y per side
// is a first-approximation default; this codebase doesn't apply
// prop.rotation to any mesh anywhere today (confirmed via grep), so
// there's no existing per-model "forward" convention to match against --
// may need per-asset tuning once real wall-decor GLBs are previewed.
const WALL_SIDE_EDGE_OFFSET = { north: [0, -0.45], south: [0, 0.45], east: [0.45, 0], west: [-0.45, 0] };
const WALL_SIDE_ROTATION_Y  = { north: 0, east: Math.PI / 2, south: Math.PI, west: -Math.PI / 2 };

function applyWallSideTransform(mesh, prop, resolved){
  const side = resolved?.wall_mounted && prop.wall_side;
  const edge = side && WALL_SIDE_EDGE_OFFSET[side];
  if(!edge) return false;
  mesh.position.x += edge[0];
  mesh.position.z += edge[1];
  mesh.rotation.y = WALL_SIDE_ROTATION_Y[side];
  return true;
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
      applyWallSideTransform(props[prop.id], prop, resolveProp(definitions, prop));

      // Off-grid physical travel: server sets prop.hidden explicitly
      // (garage/car/bus while mid-trip or off-map) -- see systems/travel.py
      // and systems/transit.py.
      props[prop.id].visible = !prop.hidden;

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
  applyWallSideTransform(model, prop, resolved);

  const propScale = resolveModelScale(resolved?.model);
  model.scale.set(propScale.x, propScale.y, propScale.z);

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
// PLACED ITEMS  (dropped/delivered personal items, e.g. a newspaper)
// WORLD OBJECTS (service-worker-spawned props, e.g. a mail bundle)
// Same shape as updateProps() above: update-in-place, loading guard,
// fallback placeholder (the PRIMARY render path today -- no book/
// newspaper/magazine/dvd/music_disc .glb assets exist yet), and
// stale-entry cleanup. Note: unlike props/characters, an entry fully
// disappearing from world state (e.g. an item picked back up) is only
// guaranteed to be cleaned up on the next FULL snapshot, not the next
// delta -- the delta channel only ever carries *changed* entries, the
// same limitation every other entity type in this game already has
// (nothing in this codebase signals "this id was removed" through a
// delta; props/characters never hit this because nothing ever actually
// deletes them from world state, only hides/moves them).
// =========================================================

function createFallbackPlacedItem(item){

  // Amber placeholder, distinct from props' blue-grey and characters'
  // cyan -- reads as "a document/media item" at a glance.
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(0.3, 0.05, 0.4),
    new THREE.MeshStandardMaterial({ color: 0xd9a441, roughness: 0.8 })
  );

  mesh.position.set(item.x - 10, 0.05, item.y - 7);
  mesh.userData = { type: "placed_item", id: item.id, template: item.template_id };

  selectable.push(mesh);
  scene.add(mesh);

  return mesh;
}

function createFallbackWorldObject(obj){

  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(0.4, 0.3, 0.3),
    new THREE.MeshStandardMaterial({ color: 0xd9a441, roughness: 0.8 })
  );

  mesh.position.set(obj.x - 10, 0.15, obj.y - 7);
  mesh.userData = { type: "world_object", id: obj.id, objType: obj.type };

  selectable.push(mesh);
  scene.add(mesh);

  return mesh;
}

async function updatePlacedItems(state){

  const active = new Set();

  for(const [id, item] of Object.entries(state.placed_items || {})){

    active.add(id);

    if(placedItems[id]){
      placedItems[id].position.set(item.x - 10, 0.05, item.y - 7);
      continue;
    }

    if(loadingPlacedItems[id]) continue;
    loadingPlacedItems[id] = true;

    const resolved = resolveItem(definitions, item);
    const modelPath = resolveModel(resolved?.model);

    if(!modelPath){
      placedItems[id] = createFallbackPlacedItem(item);
      delete loadingPlacedItems[id];
      continue;
    }

    try {
      const loaded = await loadModelCached(modelPath);
      const model = loaded.scene;

      model.position.set(item.x - 10, 0.05, item.y - 7);
      model.userData = { type: "placed_item", id: item.id, template: item.template_id };

      model.traverse((o) => {
        if(o.isMesh){
          o.castShadow = true;
          o.receiveShadow = true;
        }
      });

      selectable.push(model);
      scene.add(model);
      placedItems[id] = model;
    } catch(err){
      console.error("Failed to load placed item:", resolved?.model, err);
      placedItems[id] = createFallbackPlacedItem(item);
    }

    delete loadingPlacedItems[id];
  }

  for(const id in placedItems){
    if(active.has(id)) continue;
    scene.remove(placedItems[id]);
    removeSelectable(placedItems[id]);
    delete placedItems[id];
  }
}

async function updateWorldObjects(state){

  const active = new Set();

  for(const obj of state.world_objects || []){

    if(!obj.id) continue;   // can't track without a stable id -- skip
    active.add(obj.id);

    if(worldObjects[obj.id]){
      worldObjects[obj.id].position.set(obj.x - 10, 0.15, obj.y - 7);
      continue;
    }

    if(loadingWorldObjects[obj.id]) continue;
    loadingWorldObjects[obj.id] = true;

    // world_objects carry a bare "model" key (not a template id) -- see
    // service_worker_runtime.py's deposit_mail()/drop_package(). Try it
    // through the same meshbank-or-raw-path resolution as everything else.
    const modelPath = resolveModel(obj.model);

    if(!modelPath){
      worldObjects[obj.id] = createFallbackWorldObject(obj);
      delete loadingWorldObjects[obj.id];
      continue;
    }

    try {
      const loaded = await loadModelCached(modelPath);
      const model = loaded.scene;

      model.position.set(obj.x - 10, 0.15, obj.y - 7);
      model.userData = { type: "world_object", id: obj.id, objType: obj.type };

      model.traverse((o) => {
        if(o.isMesh){
          o.castShadow = true;
          o.receiveShadow = true;
        }
      });

      selectable.push(model);
      scene.add(model);
      worldObjects[obj.id] = model;
    } catch(err){
      console.error("Failed to load world object:", obj.model, err);
      worldObjects[obj.id] = createFallbackWorldObject(obj);
    }

    delete loadingWorldObjects[obj.id];
  }

  for(const id in worldObjects){
    if(active.has(id)) continue;
    scene.remove(worldObjects[id]);
    removeSelectable(worldObjects[id]);
    delete worldObjects[id];
  }
}

// =========================================================
// RESPONDERS (police/medical/fire, en route or just arrived)
// =========================================================
// No dedicated vehicle model exists yet for any of these, so this is a
// permanent (not "until a real model arrives") tagged-primitive marker,
// same spirit as createFallbackProp but color-coded per service so an
// ambulance/cruiser/engine reads as a distinct thing at a glance.
const _RESPONDER_COLORS = {
  police:  0x2255cc,   // blue
  medical: 0xdd2222,   // red (ambulance)
  fire:    0xff7a1a,   // orange
};

function createResponderMarker(r){
  const color = _RESPONDER_COLORS[r.type] || 0x999999;

  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(0.6, 0.5, 1.1),
    new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.35, roughness: 0.5 })
  );

  mesh.position.set(r.location.x - 10, 0.4, r.location.y - 7);
  mesh.userData = { type: "responder", id: r.id, responderType: r.type };

  selectable.push(mesh);
  scene.add(mesh);
  return mesh;
}

function updateResponders(state){

  const active = new Set();

  for(const r of state.responders || []){

    if(!r.id || !r.location) continue;
    active.add(r.id);

    if(responders[r.id]){
      responders[r.id].position.set(r.location.x - 10, 0.4, r.location.y - 7);
      continue;
    }

    responders[r.id] = createResponderMarker(r);
  }

  for(const id in responders){
    if(active.has(id)) continue;
    scene.remove(responders[id]);
    removeSelectable(responders[id]);
    delete responders[id];
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

    if(utterance){
      // Confirmed live bug: a page reload resets this tracker to empty,
      // so the very next update treated whatever OLD, unchanged
      // current_speech a character already had (from long before the
      // reload) as brand-new -- re-logging a real player-reported stale
      // decision with a freshly-current timestamp made it look like it
      // had just happened again, when nothing new had occurred at all.
      // Seed silently on first sight of a character instead of logging
      // it as an event; only a genuine SUBSEQUENT change gets logged.
      const seenBefore = Object.prototype.hasOwnProperty.call(_lastLoggedSpeech, id);
      if(utterance !== _lastLoggedSpeech[id]){
        _lastLoggedSpeech[id] = utterance;
        if(seenBefore) terminalLog("said", c.name || id, utterance);
      }
    }

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

// =========================================================
// ORGASM METER (systems/intercourse_session.py) -- a small bar above a
// character's head while c.orgasm_meter > 0, same CSS2DObject-per-
// character pattern as the speech bubble above it, just parked a little
// higher so the two never overlap.
// =========================================================

const orgasmMeters = {};   // id → { cssObject, div, fill }

function getOrCreateOrgasmMeter(id){
  if(orgasmMeters[id]) return orgasmMeters[id];

  const div = document.createElement("div");
  div.style.cssText = `
    width: 46px;
    height: 6px;
    background: rgba(0,0,0,0.5);
    border: 1px solid rgba(255,255,255,0.6);
    border-radius: 3px;
    overflow: hidden;
    pointer-events: none;
    display: none;
  `;
  const fill = document.createElement("div");
  fill.style.cssText = `
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, #ff5fa8, #ff2f7c);
  `;
  div.appendChild(fill);

  const cssObject = new CSS2DObject(div);
  cssObject.position.set(0, 3.1, 0);   // above the speech bubble
  orgasmMeters[id] = { cssObject, div, fill };
  return orgasmMeters[id];
}

function updateOrgasmMeters(state){
  const active = new Set();

  for(const [id, c] of Object.entries(state.characters || {})){
    const model = sims[id];
    if(!model) continue;

    const meter = c.orgasm_meter || 0;
    if(meter <= 0){
      if(orgasmMeters[id]) orgasmMeters[id].cssObject.visible = false;
      continue;
    }

    active.add(id);
    const { cssObject, div, fill } = getOrCreateOrgasmMeter(id);
    if(!model.getObjectById(cssObject.id)) model.add(cssObject);

    div.style.display = "block";
    cssObject.visible = true;
    fill.style.width = `${Math.max(0, Math.min(100, meter))}%`;
    // Climbs toward a hotter color the closer to climax.
    fill.style.background = meter >= 80
      ? "linear-gradient(90deg, #ff2f7c, #ff2020)"
      : "linear-gradient(90deg, #ff5fa8, #ff2f7c)";
  }

  for(const id in orgasmMeters){
    if(active.has(id)) continue;
    const { cssObject } = orgasmMeters[id];
    const model = sims[id];
    if(model) model.remove(cssObject);
    delete orgasmMeters[id];
  }
}

// =========================================================
// DEBUG OVERLAY SETTINGS (localStorage-backed, per client)
// =========================================================
// New pattern for this file -- localStorage is otherwise unused
// anywhere in the frontend. Versioned + merged with defaults on read
// (not trusted outright) so a channel added later doesn't read as
// undefined for a client with an older saved blob.

const DEBUG_SETTINGS_KEY = "holosims_debug_settings";
const DEBUG_SETTINGS_DEFAULTS = {
  version: 1,
  showThoughtBubbles: true,   // on by default -- distinguishes real speech (white bubble) from internal thought/reflection (blue bubble)
  showBadges: true,            // the whole point of this feature is seeing these work
  // Per the user's explicit ask: colored debug bubbles for action/
  // activity execution (green), reactions (red), and violent/illegal
  // actions (purple) -- default OFF, this is a debugging aid, not
  // something to clutter the normal viewing experience.
  showDebugEventBubbles: false,
  thoughtChannels: { thought: true, reflection: true, current_intention: false },
  badgeChannels:   { worries: true, current_intention: true },
  // Gated behind a deliberate character selection first (unlike the two
  // above, which apply ambiently to every character). Default off --
  // this is debug data, not something to clutter the normal viewing
  // experience by default.
  perceptionOverlays: { visionRange: false, hearingRange: false, lineOfSight: false },
};

function _loadDebugSettings(){
  try{
    const stored = JSON.parse(localStorage.getItem(DEBUG_SETTINGS_KEY) || "{}");
    return {
      ...DEBUG_SETTINGS_DEFAULTS,
      ...stored,
      thoughtChannels:    { ...DEBUG_SETTINGS_DEFAULTS.thoughtChannels,    ...(stored.thoughtChannels    || {}) },
      badgeChannels:      { ...DEBUG_SETTINGS_DEFAULTS.badgeChannels,      ...(stored.badgeChannels      || {}) },
      perceptionOverlays: { ...DEBUG_SETTINGS_DEFAULTS.perceptionOverlays, ...(stored.perceptionOverlays || {}) },
    };
  } catch(e){
    return { ...DEBUG_SETTINGS_DEFAULTS };
  }
}

function _saveDebugSettings(){
  localStorage.setItem(DEBUG_SETTINGS_KEY, JSON.stringify(_debugSettings));
}

let _debugSettings = _loadDebugSettings();

// =========================================================
// DEBUG OVERLAY CHANNELS
// =========================================================
// Plain descriptor arrays -- adding a new debug data source later is a
// one-line addition here, the settings modal renders checkboxes from
// these arrays automatically (see openDebugSettingsModal below), no
// new UI code needed per channel.

function _formatIntention(c){
  const i = c.current_intention;
  if(!i) return null;
  return `${i.type}${i.reason ? ": " + i.reason : ""}`;
}

// last_thought/last_reflection are genuinely one-shot LLM output
// (agent_loop.py writes them unconditionally every think() call) --
// current_intention is offered here too (off by default) for anyone
// who wants the transient/log framing instead of (or alongside) the
// persistent badge version below.
const THOUGHT_CHANNELS = [
  { id: "thought",            label: "Thought",           extract: c => c.last_thought },
  { id: "reflection",         label: "Reflection",        extract: c => c.last_reflection },
  { id: "current_intention",  label: "Current intention", extract: _formatIntention },
];

function _highestWorry(c){
  const worries = c.worries || {};
  let best = null;
  for(const [subjectId, w] of Object.entries(worries)){
    if((w.suspicion_level || 0) <= 0.1) continue;   // matches worries.py's ACTIVE_THRESHOLD
    if(!best || w.suspicion_level > best.suspicion_level) best = { subjectId, ...w };
  }
  return best;
}

// worries is a dict keyed by subject_id (not a list) -- systems/worries.py.
// current_intention persists across many ticks by nature, so it's the
// natural badge candidate (stays indicated as long as it's in effect),
// unlike the thought-bubble version above which times out on no change.
const BADGE_CHANNELS = [
  {
    id: "worries", label: "Suspicion", icon: "\u{1F441}️", color: "#f87171",
    active: c => !!_highestWorry(c),
    detail: c => {
      const w = _highestWorry(c);
      return w ? `Suspicious of ${w.subjectId}` : "";
    },
  },
  {
    id: "current_intention", label: "Intention", icon: "\u{1F3AF}", color: "#60a5fa",
    active: c => !!c.current_intention,
    detail: c => _formatIntention(c) || "",
  },
];

// =========================================================
// THOUGHT BUBBLES
// =========================================================
// Shows internal LLM state (thought/reflection, not spoken aloud) as a
// transient blue bubble above the character's head, distinct from real
// speech bubbles (updateSpeechBubbles() above, white background --
// never touched or gated by this). White = actually uttered out loud;
// blue = everything else (internal thought/reflection). Still toggleable
// off via the debug settings modal for anyone who only wants to see
// what's actually said.

const _lastThoughtContent = {};   // id -> last shown combined string
const _thoughtHideTimers  = {};   // id -> setTimeout handle
const THOUGHT_BUBBLE_HIDE_MS = 6000;

function getOrCreateThoughtBubble(id){
  if(thoughtBubbles[id]) return thoughtBubbles[id];

  const div = document.createElement("div");
  div.className = "thought-bubble-debug";
  div.style.cssText = `
    background: rgba(59,110,207,0.92);
    color: #f0f4ff;
    padding: 4px 8px;
    border-radius: 8px;
    border: 1px solid #82a6f5;
    font-size: 11px;
    font-family: monospace;
    max-width: 200px;
    text-align: center;
    white-space: normal;
    pointer-events: none;
    box-shadow: 0 2px 6px rgba(0,0,0,0.35);
    display: none;
  `;

  const cssObject = new CSS2DObject(div);
  cssObject.position.set(0, 3.2, 0);   // above the speech bubble (2.6)
  thoughtBubbles[id] = { cssObject, div };
  return thoughtBubbles[id];
}

function updateThoughtBubbles(state){
  const active = new Set(Object.keys(state.characters || {}));

  if(!_debugSettings.showThoughtBubbles){
    for(const id in thoughtBubbles){
      thoughtBubbles[id].cssObject.visible = false;
    }
    return;
  }

  for(const [id, c] of Object.entries(state.characters || {})){
    const model = sims[id];
    if(!model) continue;

    const { cssObject, div } = getOrCreateThoughtBubble(id);
    if(!model.getObjectById(cssObject.id)) model.add(cssObject);

    const enabledChannels = THOUGHT_CHANNELS.filter(
      ch => _debugSettings.thoughtChannels[ch.id]
    );
    const combined = enabledChannels
      .map(ch => ch.extract(c))
      .filter(Boolean)
      .join(" | ");

    // Confirmed live bug (player report: "current_intention" bubble
    // shows right after a page reload then disappears in a few seconds,
    // even though the intention itself has been active for hours) --
    // exactly the same class of bug already fixed for speech bubbles'
    // _lastLoggedSpeech: a reload resets this tracker to empty, so the
    // very next update sees undefined !== combined and treats whatever
    // OLD, unchanged content a character already had as brand new.
    // Seed silently on first sight instead; only a genuine SUBSEQUENT
    // change re-triggers the visible bubble + hide timer.
    const seenBefore = Object.prototype.hasOwnProperty.call(_lastThoughtContent, id);
    if(combined && combined !== _lastThoughtContent[id]){
      _lastThoughtContent[id] = combined;
      if(seenBefore){
        div.textContent = combined;
        cssObject.visible = true;

        clearTimeout(_thoughtHideTimers[id]);
        _thoughtHideTimers[id] = setTimeout(() => {
          cssObject.visible = false;
        }, THOUGHT_BUBBLE_HIDE_MS);
      }
    }
  }

  for(const id in thoughtBubbles){
    if(active.has(id)) continue;
    const { cssObject } = thoughtBubbles[id];
    const model = sims[id];
    if(model) model.remove(cssObject);
    clearTimeout(_thoughtHideTimers[id]);
    delete _thoughtHideTimers[id];
    // Confirmed live bug (real player report + screenshot): deleting
    // this on every out-of-view cleanup (which fires constantly --
    // server-side viewport filtering, not just a character actually
    // leaving for good) meant the moment they came back into view,
    // whatever content they already had -- however old -- was treated
    // as brand new and popped the bubble right back up. Their content
    // hasn't changed just because the client briefly lost track of
    // them; leave the memory of it alone so only a genuine change
    // re-triggers the bubble.
    delete thoughtBubbles[id];
  }
}

// =========================================================
// DEBUG EVENT BUBBLES (systems/debug_log.py) -- action/activity execution
// (green), reactions (red), violent/illegal actions (purple). Default OFF
// (_debugSettings.showDebugEventBubbles) -- a debugging aid, not part of
// the normal viewing experience. Parked above the thought bubble (3.2) so
// the two never overlap.
// =========================================================

const _DEBUG_EVENT_COLORS = {
  action:    "rgba(46,160,67,0.92)",
  activity:  "rgba(46,160,67,0.92)",
  reaction:  "rgba(220,53,69,0.92)",
  violation: "rgba(147,51,234,0.92)",
};

function getOrCreateDebugEventBubble(id){
  if(debugEventBubbles[id]) return debugEventBubbles[id];

  const div = document.createElement("div");
  div.className = "debug-event-bubble";
  div.style.cssText = `
    color: #fff;
    padding: 3px 7px;
    border-radius: 6px;
    font-size: 10px;
    font-family: monospace;
    max-width: 220px;
    text-align: center;
    white-space: normal;
    pointer-events: none;
    box-shadow: 0 2px 6px rgba(0,0,0,0.35);
    display: none;
  `;

  const cssObject = new CSS2DObject(div);
  cssObject.position.set(0, 3.8, 0);
  debugEventBubbles[id] = { cssObject, div };
  return debugEventBubbles[id];
}

function updateDebugEventBubbles(state){
  const active = new Set(Object.keys(state.characters || {}));

  if(!_debugSettings.showDebugEventBubbles){
    for(const id in debugEventBubbles){
      debugEventBubbles[id].cssObject.visible = false;
    }
    return;
  }

  const tick = state.tick || 0;

  for(const [id, c] of Object.entries(state.characters || {})){
    const model = sims[id];
    if(!model) continue;

    const { cssObject, div } = getOrCreateDebugEventBubble(id);
    if(!model.getObjectById(cssObject.id)) model.add(cssObject);

    const ev = c.current_debug_event;
    const live = ev && ev.text && tick <= (ev.expires_at_tick || 0);
    if(live){
      div.textContent = ev.text;
      div.style.background = _DEBUG_EVENT_COLORS[ev.category] || _DEBUG_EVENT_COLORS.action;
      cssObject.visible = true;
    } else {
      cssObject.visible = false;
    }
  }

  for(const id in debugEventBubbles){
    if(active.has(id)) continue;
    const { cssObject } = debugEventBubbles[id];
    const model = sims[id];
    if(model) model.remove(cssObject);
    delete debugEventBubbles[id];
  }
}

// =========================================================
// DEBUG OVERLAY: BADGES
// =========================================================
// Debug-only -- persistent icons for "ongoing" conditions, visible for
// as long as the underlying state is true. No timer/decay (unlike
// thought bubbles above) -- just mirrors current backend state every
// update. This is what actually shows worries/suspicion working
// in-world.

function getOrCreateBadge(id){
  if(badges[id]) return badges[id];

  const div = document.createElement("div");
  div.className = "debug-badge-row";
  div.style.cssText = `
    display: flex;
    flex-direction: row;
    gap: 3px;
    pointer-events: none;
  `;

  const cssObject = new CSS2DObject(div);
  cssObject.position.set(0, 2.1, 0);   // below speech bubbles
  badges[id] = { cssObject, div };
  return badges[id];
}

function updateBadges(state){
  const active = new Set(Object.keys(state.characters || {}));

  if(!_debugSettings.showBadges){
    for(const id in badges){
      badges[id].cssObject.visible = false;
    }
    return;
  }

  for(const [id, c] of Object.entries(state.characters || {})){
    const model = sims[id];
    if(!model) continue;

    const { cssObject, div } = getOrCreateBadge(id);
    if(!model.getObjectById(cssObject.id)) model.add(cssObject);

    const activeChannels = BADGE_CHANNELS.filter(
      ch => _debugSettings.badgeChannels[ch.id] && ch.active(c)
    );

    if(activeChannels.length === 0){
      cssObject.visible = false;
      continue;
    }

    div.innerHTML = "";
    for(const ch of activeChannels){
      const span = document.createElement("span");
      span.title = ch.detail(c) || ch.label;
      span.style.cssText = `
        background: rgba(30,34,41,0.9);
        border: 1.5px solid ${ch.color};
        border-radius: 50%;
        width: 18px;
        height: 18px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
      `;
      span.textContent = ch.icon;
      div.appendChild(span);
    }
    cssObject.visible = true;
  }

  for(const id in badges){
    if(active.has(id)) continue;
    const { cssObject } = badges[id];
    const model = sims[id];
    if(model) model.remove(cssObject);
    delete badges[id];
  }
}

// =========================================================
// DEBUG OVERLAY: PERCEPTION (vision/hearing/LOS, selected character only)
// =========================================================
// World-space geometry (ground-flat circles + lines), not CSS2D -- real
// THREE.Line scene geometry, shown only for selectedCharacterId, unlike
// thought bubbles/badges which apply to every character at once.
// Materials built once and reused; only geometry is rebuilt+disposed per
// update, mirroring censorBars.js's disposal idiom (the ported ring
// technique's original home, definitions.js's _ixUpdateRadiusRing, is an
// editor-only, low-frequency function that gets away without disposing --
// not safe to copy here, where this runs every network tick for a whole
// live viewer session).

const PERCEPTION_OVERLAY_CHANNELS = [
  { id: "visionRange",  label: "Vision range" },
  { id: "hearingRange", label: "Hearing range" },
  { id: "lineOfSight",  label: "Line of sight" },
];

let _perceptionRanges = null;         // { visual_range, hearing_range } | null
let _lastSelectedBuildingId = undefined;
let perceptionOverlay = { visionRing: null, hearingRing: null, losLines: [] };

const _visionRingMaterial  = new THREE.LineBasicMaterial({ color: 0xf5c518 });
const _hearingRingMaterial = new THREE.LineBasicMaterial({ color: 0x5ac8fa });
const _losLineMaterial     = new THREE.LineBasicMaterial({ color: 0xff5a5a });

function _buildRingGeometry(cx, cz, radius, segs = 48){
  const pts = [];
  for(let i = 0; i <= segs; i++){
    const a = (i / segs) * Math.PI * 2;
    pts.push(new THREE.Vector3(cx + Math.cos(a) * radius, 0.02, cz + Math.sin(a) * radius));
  }
  return new THREE.BufferGeometry().setFromPoints(pts);
}

function _disposeRing(ring){
  if(!ring) return;
  scene.remove(ring);
  ring.geometry.dispose();
}

function _disposeLosLines(){
  for(const line of perceptionOverlay.losLines){
    scene.remove(line);
    line.geometry.dispose();
  }
  perceptionOverlay.losLines = [];
}

// visual_range()/hearing_range() (brain/perception.py) are pure functions,
// never persisted onto the character dict -- fetched from a small server
// endpoint rather than replicated in JS, to avoid a two-language drift
// bug between the Python formula and a client-side copy.
async function fetchPerceptionRanges(id){
  try{
    // Relative path, proxied same-origin -- matches the established
    // pattern every other HTTP endpoint in this app already uses
    // (/api, /resources, /debug are all proxied through nginx in
    // production and vite's dev-server proxy locally; /view is added
    // alongside them in both nginx.conf and vite.config.js for this).
    // The WS connection is the one deliberate exception (an absolute
    // host:8000 URL) -- not a pattern to extend to plain fetches.
    const resp = await fetch(`/view/perception-range/${encodeURIComponent(id)}?sim_id=default`);
    if(!resp.ok) return;
    const data = await resp.json();
    if(selectedCharacterId === id) _perceptionRanges = data;
  } catch(e){
    // Network hiccup -- leave any previously-fetched ranges in place
    // rather than blanking the overlay for one bad request.
  }
}

// Coarse fallback poll, purely to catch a day/night threshold crossing
// while a character stays selected across a day/night cycle -- NOT a
// substitute for the building_id-diff immediate refetch below.
// Deliberately infrequent: this value changes at most twice a day, and
// event-triggering precisely on the hour cutoff would mean replicating
// that threshold in JS too, the exact drift risk this endpoint exists
// to avoid.
setInterval(() => {
  if(selectedCharacterId) fetchPerceptionRanges(selectedCharacterId);
}, 45000);

function updatePerceptionOverlay(state){
  const settings = _debugSettings.perceptionOverlays;
  const anyOn = settings.visionRange || settings.hearingRange || settings.lineOfSight;

  if(!selectedCharacterId || !anyOn){
    _disposeRing(perceptionOverlay.visionRing);
    _disposeRing(perceptionOverlay.hearingRing);
    _disposeLosLines();
    perceptionOverlay.visionRing = null;
    perceptionOverlay.hearingRing = null;
    _lastSelectedBuildingId = undefined;
    return;
  }

  const c = state.characters?.[selectedCharacterId];
  const model = sims[selectedCharacterId];
  if(!c || !model) return;

  // Immediate refetch on building_id change -- zero drift risk, just a
  // string diff, not reimplementing the night/indoor formula client-side.
  if(c.building_id !== _lastSelectedBuildingId){
    _lastSelectedBuildingId = c.building_id;
    fetchPerceptionRanges(selectedCharacterId);
  }

  if(!_perceptionRanges) return;   // first fetch hasn't resolved yet

  const cx = model.position.x;
  const cz = model.position.z;

  _disposeRing(perceptionOverlay.visionRing);
  perceptionOverlay.visionRing = null;
  if(settings.visionRange && _perceptionRanges.visual_range != null){
    const geom = _buildRingGeometry(cx, cz, _perceptionRanges.visual_range);
    perceptionOverlay.visionRing = new THREE.Line(geom, _visionRingMaterial);
    scene.add(perceptionOverlay.visionRing);
  }

  _disposeRing(perceptionOverlay.hearingRing);
  perceptionOverlay.hearingRing = null;
  if(settings.hearingRange && _perceptionRanges.hearing_range != null){
    const geom = _buildRingGeometry(cx, cz, _perceptionRanges.hearing_range);
    perceptionOverlay.hearingRing = new THREE.Line(geom, _hearingRingMaterial);
    scene.add(perceptionOverlay.hearingRing);
  }

  // c.perception.visible_people (brain/perception.py::perceive_people) is
  // already gated by BOTH within-visual_range AND a real line_of_sight
  // check before an entry appears there -- zero new backend work needed
  // to know who to draw LOS lines to.
  _disposeLosLines();
  if(settings.lineOfSight){
    const visiblePeople = c.perception?.visible_people || [];
    for(const p of visiblePeople){
      const otherModel = sims[p.id];
      if(!otherModel) continue;
      const geom = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(cx, 0.02, cz),
        new THREE.Vector3(otherModel.position.x, 0.02, otherModel.position.z),
      ]);
      const line = new THREE.Line(geom, _losLineMaterial);
      scene.add(line);
      perceptionOverlay.losLines.push(line);
    }
  }
}

// =========================================================
// DEBUG OVERLAY SETTINGS MODAL
// =========================================================

function _renderChannelCheckboxes(channels, enabledMap, groupKey){
  return channels.map(ch => `
    <div class="modal-row">
      <label style="cursor:pointer; flex:1;">
        <input type="checkbox" data-group="${groupKey}" data-channel="${ch.id}"
               ${enabledMap[ch.id] ? "checked" : ""} />
        ${ch.label}
      </label>
    </div>
  `).join("");
}

function renderDebugSettingsModal(){
  const body = document.getElementById("debugSettingsModalBody");
  if(!body) return;

  body.innerHTML = `
    <div class="modal-row">
      <label style="cursor:pointer; flex:1;">
        <input type="checkbox" id="dbgShowThoughtBubbles" ${_debugSettings.showThoughtBubbles ? "checked" : ""} />
        Show thought bubbles
      </label>
    </div>
    <div class="modal-row">
      <label style="cursor:pointer; flex:1;">
        <input type="checkbox" id="dbgShowBadges" ${_debugSettings.showBadges ? "checked" : ""} />
        Show badges
      </label>
    </div>
    <div class="modal-row">
      <label style="cursor:pointer; flex:1;">
        <input type="checkbox" id="dbgShowDebugEventBubbles" ${_debugSettings.showDebugEventBubbles ? "checked" : ""} />
        Show action/activity/reaction debug bubbles (green/red/purple)
      </label>
    </div>
    <h4>Thought bubble sources</h4>
    ${_renderChannelCheckboxes(THOUGHT_CHANNELS, _debugSettings.thoughtChannels, "thoughtChannels")}
    <h4>Badge sources</h4>
    ${_renderChannelCheckboxes(BADGE_CHANNELS, _debugSettings.badgeChannels, "badgeChannels")}
    <h4>Perception overlays (selected character only)</h4>
    ${_renderChannelCheckboxes(PERCEPTION_OVERLAY_CHANNELS, _debugSettings.perceptionOverlays, "perceptionOverlays")}
  `;

  document.getElementById("dbgShowThoughtBubbles").addEventListener("change", (e) => {
    _debugSettings.showThoughtBubbles = e.target.checked;
    _saveDebugSettings();
  });
  document.getElementById("dbgShowBadges").addEventListener("change", (e) => {
    _debugSettings.showBadges = e.target.checked;
    _saveDebugSettings();
  });
  document.getElementById("dbgShowDebugEventBubbles").addEventListener("change", (e) => {
    _debugSettings.showDebugEventBubbles = e.target.checked;
    _saveDebugSettings();
  });
  body.querySelectorAll("input[data-group]").forEach(input => {
    input.addEventListener("change", (e) => {
      const group = e.target.dataset.group;
      const channel = e.target.dataset.channel;
      _debugSettings[group][channel] = e.target.checked;
      _saveDebugSettings();
    });
  });
}

function openDebugSettingsModal(){
  renderDebugSettingsModal();
  openModal("modal-debug-settings");
}

// Off-grid physical travel: hidden while riding in/on a car or bus
// (walking to/from the garage or bus stop stays visible) -- see
// systems/travel.py and systems/transit.py. travel_hidden only covers
// that brief ride, though -- it's cleared back to false the moment the
// character arrives at their off-grid destination, well before c.off_grid
// itself clears (that stays true for the whole stay, e.g. a multi-hour
// hospital visit), so check both. Factored out of updateCharacters()'s
// "ALREADY EXISTS" branch so the two mesh-CREATION sites below can apply
// the same check immediately -- previously they defaulted to
// THREE.js's visible=true and only got corrected the next time that
// character happened to appear in a dirty WS delta, which could be a
// long time (or never) for a stationary off-grid character, leaving a
// stale fully-visible mesh for anyone who connected while they were
// already away.
function _isCharacterHidden(c){
  return !!(c.travel_hidden || c.off_grid);
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

  mesh.visible = !_isCharacterHidden(c);
  mesh.userData.ignoreRaycast = _isCharacterHidden(c);

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

        // Re-equip clothing if what's worn changed (diffed by template id
        // per slot, not deep-equal, so per-item substate like quantity
        // doesn't trigger a needless re-attach).
        const wornTemplateIds = (worn) => Object.fromEntries(
          Object.entries(worn || {}).map(([slot, item]) => [slot, item?.template_id || null])
        );
        const prevWorn = JSON.stringify(wornTemplateIds(prev?.worn));
        const nextWorn = JSON.stringify(wornTemplateIds(c.worn));
        if (prevWorn !== nextWorn) {
          equipAllClothing(id, sims[id], sims[id], c.worn || {}, definitions);
        }

        updateStackAttachment(id, sims[id], c.held_stack, definitions?.item_templates || {});
        updateHeldItemAttachment(id, sims[id], c.inventory, definitions?.item_templates || {});
      }

      // Sync position from server unless the IK system has already taken
      // over fine-alignment (isAnchored flag set by updateIK once close).
      if (!characterAnimations[id]?.isAnchored) {
        const newX = c.x - 10;
        const newZ = c.y - 7;
        // Compared against the last known SERVER (base) position, not the
        // rendered mesh position -- the idle/wait pacing sway below adds a
        // small offset directly to the mesh, and comparing against that
        // would make the facing logic misread its own cosmetic wobble as
        // real movement and spin the model back and forth every frame.
        const animRec = characterAnimations[id];
        const lastBase = animRec?.lastBasePos;
        const dx = lastBase ? newX - lastBase.x : 0;
        const dz = lastBase ? newZ - lastBase.z : 0;
        // Face the direction of actual movement -- updateIK()'s existing
        // facing logic only fires while there's a specific interaction
        // target to look at (activity.target_id); plain point-to-point
        // walking (to the bus stop, home, wandering, ...) never rotated
        // the model at all otherwise, since this position sync just set
        // x/y/z with no corresponding turn. updateIK() still takes
        // priority once a real target exists -- it runs every frame and
        // overwrites rotation.y unconditionally when viewTargetId is set,
        // this only matters on the (majority of) ticks where it isn't.
        if (Math.abs(dx) > 0.01 || Math.abs(dz) > 0.01) {
          sims[id].rotation.y = Math.atan2(dx, dz);
        }
        if (animRec) animRec.lastBasePos = { x: newX, z: newZ };

        const pace = _idlePaceOffset(id, c, !!c.is_moving);
        sims[id].position.set(newX + (pace?.dx || 0), 0, newZ + (pace?.dz || 0));
      }

      // See _isCharacterHidden()'s own comment (above createFallbackCharacter)
      // for why both travel_hidden and off_grid are checked here.
      const isHidden = _isCharacterHidden(c);
      sims[id].visible = !isHidden;
      // Being invisible didn't stop the raycaster from hitting the mesh --
      // THREE.js raycasting ignores .visible entirely, it's a render-only
      // flag -- so a hidden character stayed clickable/selectable. Reuses
      // the same userData.ignoreRaycast flag the click handler already
      // filters on (see the mailbox dblclick / character selection code).
      sims[id].userData.ignoreRaycast = isHidden;

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

  model.visible = !_isCharacterHidden(c);
  model.userData.ignoreRaycast = _isCharacterHidden(c);

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
    c.worn || {},
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
    // Per-character-TEMPLATE override (finer-grained than locomotionMap
    // above, which is shared by every character using the same body
    // model) — see resolveCharacterOverrideMap().
    characterMap: resolveCharacterOverrideMap(c?.template),
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
    // Same orphaned-DOM-node risk applies to the debug overlay registries.
    if(thoughtBubbles[id]){
      mesh.remove(thoughtBubbles[id].cssObject);
      clearTimeout(_thoughtHideTimers[id]);
      delete _thoughtHideTimers[id];
      delete _lastThoughtContent[id];
      delete thoughtBubbles[id];
    }
    if(badges[id]){
      mesh.remove(badges[id].cssObject);
      delete badges[id];
    }
    if(debugEventBubbles[id]){
      mesh.remove(debugEventBubbles[id].cssObject);
      delete debugEventBubbles[id];
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


// Confirmed live bug (player report: characters spinning a full 360°
// every few seconds while walking toward an interaction target):
// THREE.MathUtils.lerp() interpolates its two numbers literally, with no
// awareness that an angle wraps -- lerping from a facing near +π toward
// a target angle near -π (the same real direction, just expressed on
// the other side of the wrap) sweeps the LONG way around through 0
// instead of the short way across the seam, visibly spinning the model
// through nearly a full circle before it "catches up." Reused by every
// rotation.y lerp below (body facing + head-look yaw) since both feed a
// raw atan2() angle straight into a lerp the same way.
function lerpAngle(from, to, t) {
  const twoPi = Math.PI * 2;
  let diff = ((to - from) % twoPi + twoPi + Math.PI) % twoPi - Math.PI;
  return from + diff * t;
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
        model.rotation.y = lerpAngle(
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

    headBone.rotation.y = lerpAngle(
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

    // Per the user's explicit ask: a click while something is already
    // selected ALWAYS deselects first, regardless of what it hit --
    // never jumps straight from one selection to a different one. This
    // is also the strongest possible fix for the recurring "still sort
    // of selected" report: a genuine full clear runs before ANY new
    // selection can ever be made.
    if(_somethingSelected){
      selectedCharacterId = null;
      _syncOutlinerHighlight();
      _clearInspector();
      return;
    }

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

    // Per the user's explicit ask: ctrl+click a character standing on a
    // prop/item/tile selects THAT instead -- the ray from the camera
    // through the click point already passes through everything at that
    // screen position in depth order (the character, then whatever's on
    // the ground under them), so this just looks further down the same
    // hit list rather than only ever taking the frontmost (character)
    // hit. Props/items are preferred over a bare tile, per spec; only
    // hits close to the character's own hit point count as "the same
    // square", not some unrelated object the ray happened to also pass
    // through.
    if(event.ctrlKey && hits.length > 1){
      let topObj = hits[0].object;
      while(topObj && !topObj.userData?.type) topObj = topObj.parent;
      if(topObj?.userData?.type === "character"){
        const charPoint = hits[0].point;
        const resolved = hits.slice(1).map(h => {
          let o = h.object;
          while(o && !o.userData?.type) o = o.parent;
          return o ? { obj: o, point: h.point } : null;
        }).filter(h => h && h.point.distanceTo(charPoint) < 1.0);
        const chosen =
          resolved.find(h => ["prop", "placed_item", "world_object"].includes(h.obj.userData.type))
          || resolved.find(h => h.obj.userData.type === "tile");
        if(chosen) hits.unshift({ object: chosen.obj, point: chosen.point });
      }
    }

    if(!hits.length){

      selectedCharacterId = null;
      _syncOutlinerHighlight();
      _clearInspector();

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

    // The raycast .filter() above only checks the actual leaf mesh that
    // was hit, not the ancestor this loop just walked up to -- a hidden
    // character's top-level model carries ignoreRaycast (see where
    // sims[id].visible is set), but a ray can still land on one of its
    // child meshes first, which doesn't have that flag itself. Check
    // here too, now that obj is the resolved top-level character.
    if(obj.userData?.ignoreRaycast){
      selectedCharacterId = null;
      _syncOutlinerHighlight();
      _clearInspector();
      return;
    }

    const d = obj.userData;

    const inspector = document.getElementById("viewerInspector");
    inspector.classList.toggle("expanded", d.type === "character");

    if(d.type === "character" && d.id){
      // A new character selection -- clear any cached radii from a
      // previous selection so the perception overlay doesn't briefly
      // show stale numbers before the fresh fetch resolves.
      if(selectedCharacterId !== d.id) _perceptionRanges = null;
      selectedCharacterId = d.id;
      _somethingSelected = true;
      _applyInspectorVisibility();
      _setNonStatusTabsVisible(true);
      renderCharacterInspector(d.id);
      showCharacterLLMLog(d.id);
      _syncOutlinerHighlight();
    } else {
      // Selecting a prop/tile while a character was selected must also
      // clear selectedCharacterId -- otherwise the perception rings stay
      // anchored to the stale previous character while the inspector
      // shows unrelated prop info. Also wipe every character-specific
      // tab (Body/Relations/Mind/Memory/Life/Plans) -- a prop has none
      // of that, and leaving the previous character's data sitting there
      // was the exact "still sort of selected" bug reported live.
      selectedCharacterId = null;
      _syncOutlinerHighlight();
      _clearInspector();
      _somethingSelected = true;
      _applyInspectorVisibility();
      _setNonStatusTabsVisible(false);

      // Confirmed live bug (real player report: "props that do not
      // resolve to anything in inspector"): a prop's userData only ever
      // carried {type, id, template} (see updateProps() -- no "name"
      // field is ever set on it), so this always rendered as a bare
      // "prop" heading + a raw uuid with nothing useful underneath.
      // Resolve the real template (prop_templates/item_templates
      // depending on type) for a proper name/category, same lookup
      // resolveProp()/resolveItem() already use elsewhere in this file.
      let resolvedName = d.name;
      let resolvedCategory = null;
      if(!resolvedName && d.template && definitions){
        const templatePool =
          d.type === "placed_item" ? definitions.item_templates
          : definitions.prop_templates;
        const tpl = templatePool?.[d.template];
        if(tpl){
          resolvedName = tpl.name || d.template;
          resolvedCategory = tpl.category || null;
        }
      }

      const selectedNameEl = document.getElementById("viewerSelectedName");
      if(selectedNameEl) selectedNameEl.textContent = resolvedName || d.template || d.type || "(unknown)";

      document
        .getElementById(
          "viewerSelection"
        ).innerHTML = `
          <b>${d.type}</b><br>
          ${d.tileType ? `Type: ${d.tileType}<br>` : ""}
          ${resolvedCategory ? `Category: ${resolvedCategory}<br>` : ""}
          <span style="opacity:.6; font-size: 11px;">${d.id || ""}</span>
        `;
    }
  }
);

// Re-centers the orbit camera on a world (x,y) point at a fixed default
// framing -- same angle every time (the initial-load offset, camera.position
// .set(20,20,20) looking at (0,0,0)), not whatever pan the user left the
// camera at. Note camera.zoom, not position distance, controls apparent
// size for an OrthographicCamera -- position distance from target is
// basically invisible in orthographic projection, so "closer" has to come
// from raising zoom (matches the zoom tiers OrbitControls' scroll wheel
// already drives -- see the `camera.zoom > 1.8 ? 3 : ...` mapping in
// _updateViewport()). controls.update() dispatches its own "change" event,
// which the existing debounced listener in connectWS() picks up to resync
// the viewport with the server -- no separate network call needed here.
const _DEFAULT_CAMERA_OFFSET = new THREE.Vector3(20, 20, 20);
// Confirmed live bug (real player report: "takes forever before I get
// to see the characters"): zoom 3 maps to main.py::_view_radius()'s
// SMALLEST tier (12 tiles) -- jumping to a selection at this zoom means
// even a slightly-stale target (the outliner's x/y is polled every 5s,
// see fetchOutliner()) or a character still mid-walk can land just
// outside the server's filtered viewport, and nothing else proactively
// re-jumps from there (the soft camera-follow added alongside this only
// tracks someone once their position is ALREADY being received -- a
// catch-22 if the first jump missed). A wider starting radius gives a
// lot more slack to still land inside the loaded window on the first try.
const _DEFAULT_CAMERA_ZOOM = 1;

function focusCameraOn(x, y){
  // World (x,y) -> scene (x,z) uses the same (-10,-7) map-centering offset
  // every mesh placement in this file applies (tile/prop/character
  // .position.set(x - 10, 0, y - 7)) -- without it the camera centers on
  // raw world coordinates instead of where the character's mesh actually
  // sits on screen.
  controls.target.set(x - 10, 0, y - 7);
  camera.position.copy(controls.target).add(_DEFAULT_CAMERA_OFFSET);
  camera.zoom = _DEFAULT_CAMERA_ZOOM;
  camera.updateProjectionMatrix();
  controls.update();
}

// Comprehensive current-state dump for a selected character, pulled from
// _worldState.characters[id] -- the raw per-tick character dict the server
// sends (get_view()/​_build_delta() forward it unfiltered), not just the
// sparse activity/mood fields userData carries from load time. Re-invoked
// on every subsequent state/delta apply while this character stays
// selected (see the updateSelectionInspector() hook in _applyState), so
// the panel tracks the character live rather than freezing at click time.
// Mirrors backend/systems/schema_defaults.py's COGNITION_CORE_TRAITS and
// this session's description-flavor mapping (Balanced->balanced,
// Logical->positive, Self-Aware->negative -- see the cognition/trait
// learning plan). Kept in sync manually; there are only 3 entries.
const COGNITION_CORE_IDS = {
  cognition_logical:   "logical",
  cognition_balanced:  "balanced",
  cognition_selfaware: "self_aware",
};
const COGNITION_FLAVOR = { logical: "positive", balanced: "balanced", self_aware: "negative" };

function _cognitionInfo(traits){
  for(const t of traits || []){
    if(COGNITION_CORE_IDS[t]) return { key: COGNITION_CORE_IDS[t], id: t };
  }
  return { key: "balanced", id: null };
}

function _templateDescription(tmpl, flavorKey){
  if(!tmpl) return null;
  return (tmpl.descriptions && tmpl.descriptions[flavorKey]) || tmpl.description || null;
}

// Vertical health-bar-style meters for the Inspector's Status tab, one per
// systems/body.py need + c.stress.
//
// Confirmed live bug (player report: "I got a full bladder bar at 7%"):
// an earlier version of this kept the bar's HEIGHT on an inverted
// "satisfaction" score (tall bar = doing fine) while changing only the
// TOOLTIP text to show the raw "% full" number -- so a nearly-empty
// bladder (7% full, great) rendered as a TALL bar, directly contradicting
// its own tooltip. Bar height now always equals the RAW body.py value
// directly, with zero inversion, for every meter -- what you see is
// exactly what the tooltip says, full stop. `badWhenHigh` only controls
// which direction triggers the critical (pulsing) highlight, since some
// needs are bad when full (bladder/hunger/fatigue/stress) and others are
// bad when empty (hydration/energy/hygiene).
const _NEED_METERS = [
  { key: "hydration", label: "Thirst",  color: "#3aa0ff", badWhenHigh: false, display: v => `${Math.round(v)}% hydrated` },
  { key: "bladder",   label: "Bladder", color: "#e6c200", badWhenHigh: true,  display: v => `${Math.round(v)}% full` },
  { key: "hunger",    label: "Hunger",  color: "#e64545", badWhenHigh: true,  display: v => `${Math.round(v)}% hungry` },
  { key: "energy",    label: "Energy",  color: "#3ecf5e", badWhenHigh: false, display: v => `${Math.round(v)}% energized` },
  { key: "fatigue",   label: "Fatigue", color: "#9b5de5", badWhenHigh: true,  display: v => `${Math.round(v)}% fatigued` },
  // Confirmed live bug (player report: "stress is at 65% on hover yet
  // the bar looks all empty"): #1a1a1a (near-black) is virtually
  // invisible against this panel's own dark background/track regardless
  // of fill height -- not a height/percentage bug at all, just a fill
  // color nobody could actually see. Orange reads clearly here and
  // isn't already used by another meter.
  { key: "_stress",   label: "Stress",  color: "#ff8c42", badWhenHigh: true,  display: v => `${Math.round(v)}% stressed` },
  { key: "hygiene",   label: "Hygiene", color: "#d9c79e", badWhenHigh: false, display: v => `${Math.round(v)}% clean` },
];

// Horizontal progress bar for the Inspector's current activity/action --
// "Doing: use_toilet" gave no sense of how far along it was. Two sources
// of progress, since they mean different things: a normal activity's
// elapsed/duration (phase "using" only -- still walking there has no
// progress yet), or a "wait" activity's elapsed-since-started against
// systems/waiting.py's 30-min give-up ceiling (that activity's own
// "duration" field is a no-op placeholder now -- see activities.py's
// dedicated wait branch -- so it means nothing here).
const WAIT_GIVE_UP_TICKS = 1800; // mirrors backend/systems/waiting.py::MAX_TOTAL_WAIT_TICKS

function _activityProgressPct(c){
  const act = c.activity;
  if(!act) return null;
  const tick = _worldState.tick || 0;

  if(act.type === "wait"){
    const started = act.state?.waiting_for?.started_at_tick;
    if(started == null) return null;
    return { pct: Math.max(0, Math.min(100, ((tick - started) / WAIT_GIVE_UP_TICKS) * 100)), urgency: true };
  }

  if(act.phase === "using" && act.duration && act.phase_started_tick != null){
    return { pct: Math.max(0, Math.min(100, ((tick - act.phase_started_tick) / act.duration) * 100)), urgency: false };
  }

  return null;
}

function _renderActivityProgress(c){
  const result = _activityProgressPct(c);
  if(result == null) return "";
  const { pct, urgency } = result;
  // A normal activity finishing up is neutral-to-good -- stays a calm
  // blue throughout. A "wait" closing in on the 30-min give-up ceiling is
  // the opposite (rising impatience), so THAT one ramps green->yellow->red
  // the same way needMeterCritical signals a need going bad.
  const color = urgency
    ? (pct > 80 ? "#e64545" : pct > 50 ? "#e6c200" : "#3ecf5e")
    : "#3aa0ff";
  return `
    <div class="activityBarTrack" title="${Math.round(pct)}%">
      <div class="activityBarFill" style="width:${pct}%; background:${color};"></div>
    </div>`;
}

function _renderNeedsMeters(body, stress){
  const bars = _NEED_METERS.map(({ key, label, color, badWhenHigh, display }) => {
    const raw = key === "_stress" ? stress : body?.[key];
    if (raw == null) return "";
    const pct = Math.max(0, Math.min(100, raw));
    const critical = badWhenHigh ? pct > 80 : pct < 20;
    return `
      <div class="needMeter" title="${label}: ${display(pct)}">
        <div class="needMeterTrack">
          <div class="needMeterFill${critical ? " needMeterCritical" : ""}"
               style="height:${pct}%; background:${color};"></div>
        </div>
        <div class="needMeterLabel">${label[0]}</div>
      </div>`;
  }).filter(Boolean);

  return bars.length ? `<div class="needMeters">${bars.join("")}</div>` : "";
}

// Confirmed live bug (player report: deselecting left a character "sort
// of selected" -- the Status tab correctly went blank, but Body/
// Relations/Mind/Memory/Life/Plans kept showing that character's last-
// rendered content forever, since only viewerSelection's innerHTML and
// the name header were ever reset on deselect, and even the name header
// was missed at some of the three deselection call sites). One shared
// helper, called from all of them, resets EVERY tab panel + the header
// back to a genuine "nothing selected" state.
// Per the user's explicit ask: a non-character selection (prop/tile/
// building/...) has nothing for Body/Relations/Mind/Memory/Life/Plans/
// Work/Habits to show, so only the Status tab button stays visible --
// forced active/visible too, since its own content is what actually
// carries the prop/tile info (see the raycast click handler's "else"
// branch below). A character selection restores every tab button.
function _setNonStatusTabsVisible(visible){
  document.querySelectorAll(".viewerTabBtn").forEach(btn => {
    if(btn.dataset.tab !== "status") btn.classList.toggle("hidden", !visible);
  });
  if(!visible){
    document.querySelectorAll(".viewerTabBtn").forEach(b => b.classList.toggle("active", b.dataset.tab === "status"));
    for(const panelId of Object.values(VIEWER_TAB_PANELS)){
      document.getElementById(panelId)?.classList.toggle("hidden", panelId !== "viewerSelection");
    }
  }
}

function _clearInspector(){
  const nameEl = document.getElementById("viewerSelectedName");
  if(nameEl) nameEl.textContent = "";
  const empty = _empty("Nothing selected.");
  const panelIds = [
    "viewerSelection", "viewerRelationshipsTab", "viewerMindTab",
    "viewerMemoryTab", "viewerLifeTab", "viewerPlansTab", "viewerWorkTab",
    "viewerHabitsTab", "viewerSkillsTab",
  ];
  for(const id of panelIds){
    const el = document.getElementById(id);
    if(el) el.innerHTML = empty;
  }
  const bodyAppearance = document.getElementById("bodyTabAppearance");
  const bodySummary = document.getElementById("bodyTabSummary");
  const bodyRows = document.getElementById("bodyTabRows");
  const bodyDisease = document.getElementById("bodyTabDiseases");
  if(bodyAppearance) bodyAppearance.innerHTML = "";
  if(bodySummary) bodySummary.innerHTML = empty;
  if(bodyRows) bodyRows.innerHTML = "";
  if(bodyDisease) bodyDisease.innerHTML = "";
  for(const part of _BODY_PART_NAMES){
    const shape = document.getElementById(`bodypart-${part}`);
    if(shape) shape.setAttribute("fill", _SEVERITY_COLORS[null]);
  }
  // Per the user's explicit ask: hide the whole panel, not just its
  // content, whenever nothing is selected.
  _somethingSelected = false;
  _applyInspectorVisibility();
}

function renderCharacterInspector(id){
  const el = document.getElementById("viewerSelection");
  if(!el) return;
  const nameEl = document.getElementById("viewerSelectedName");
  const c = _worldState.characters?.[id];
  if(!c){
    if(nameEl) nameEl.textContent = id;
    el.innerHTML = `(out of view)`;
    return;
  }

  // Per the user's explicit ask: the selected entity's name now lives
  // in its own header above the tabs (#viewerSelectedName), not buried
  // inside the Status tab's own content below them.
  if(nameEl) nameEl.textContent = c.name || c.id;

  const rows = [];

  if(c.alive === false){
    rows.push(`<span style="color:#f66">DEAD</span>`);
  }

  if(c.posture) rows.push(`Posture: ${c.posture}`);
  // Per the user's explicit ask: make it clear a character is still on
  // their way to an activity (the "walking" phase, before they've
  // actually reached whatever prop/anchor it needs) rather than reading
  // as if they're already doing it -- "Doing: drink" while still
  // walking across the map read as if they'd already started.
  const activityLabel = c.activity?.type
    ? (c.activity.phase === "walking"
        ? `Heading to: ${c.activity.type.replace(/_/g, " ")}`
        : `Doing: ${c.activity.type}`)
    : `State: ${c.animation_state || "idle"}`;
  rows.push(activityLabel);

  // The generic "wait" activity (systems/interactions.py's queueing path,
  // systems/waiting.py's patience/give-up timer) carried no detail of its
  // own here -- "Doing: wait" told you nothing about what for. Surface
  // the same waiting_for the backend already tracks.
  if(c.activity?.type === "wait"){
    const wf = c.activity.state?.waiting_for;
    if(wf){
      let target = wf.ref || "something";
      if(wf.kind === "prop" && typeof wf.ref === "string"){
        const propId = wf.ref.split(":")[0];
        const prop = _findProp(propId);
        if(prop?.template) target = prop.template.replace(/_/g, " ");
      }
      const bangs = wf.bang_count || 0;
      const mood = bangs >= 3 ? " — furious" : bangs >= 1 ? " — getting impatient" : "";
      rows.push(`<span style="opacity:.85">Waiting for: ${target}${mood}</span>`);
    }
  }

  const activityProgress = _renderActivityProgress(c);
  if(activityProgress) rows.push(activityProgress);

  // Wake-up date/time-of-day, while actually asleep -- systems/
  // activities.py only tracks this as a raw tick count (phase_started_tick
  // + duration), reported live as not useful on its own. Projects it
  // through the last-fetched real calendar (see _lastCalendar/
  // _projectCalendarForward above) instead of showing bare ticks.
  if(c.activity?.type === "sleep" && c.activity.phase === "using" && _lastCalendar && _lastCalendarWorldTick != null){
    const wakeTick = (c.activity.phase_started_tick || 0) + (c.activity.duration || 0);
    const proj = _projectCalendarForward(_lastCalendar, wakeTick - _lastCalendarWorldTick);
    const formatted = _formatProjectedTime(proj);
    if(formatted) rows.push(`<span style="opacity:.75">Wakes up: ${formatted}</span>`);
  }

  if(c.emotion) rows.push(`Mood: ${c.emotion}`);

  if(c.off_grid){
    const tick = _worldState.tick || 0;
    const remain = (c.return_tick || tick) - tick;
    const backIn = remain > 0 ? `~${Math.max(1, Math.round(remain / 60))}m` : "due now";
    rows.push(`<span style="color:#fc6">Off-grid: ${(c.off_grid_reason || "?").replace(/_/g, " ")} — back in ${backIn}</span>`);
  } else if(c.travel_state){
    // Human-readable gloss per systems/travel.py + systems/transit.py's
    // state machine.
    const TRAVEL_STATE_LABELS = {
      to_garage:            "walking to the garage",
      to_bus_stop:          "walking to the bus stop",
      driving_out:          "driving out",
      waiting_for_bus:      "waiting for the bus",
      on_bus_departing:     "riding the bus",
      driving_back:         "driving back",
      awaiting_bus_arrival: "waiting at the bus stop",
      on_bus_returning:     "riding the bus home",
      walking_home:         "walking home",
    };
    const label = TRAVEL_STATE_LABELS[c.travel_state] || c.travel_state;
    // Per the user's ask: while waiting for a bus/driving out, nothing
    // said what the trip was actually FOR -- backend/systems/travel.py
    // stashes the real reason in c._pending_offgrid from the moment the
    // trip starts until it actually goes off-grid (spanning every one
    // of these intermediate travel_state values), so it's already
    // available here, just never displayed.
    const pendingReason = c._pending_offgrid?.reason;
    const destination = pendingReason
      ? ` — heading to ${pendingReason.replace(/_/g, " ")}`
      : "";
    rows.push(`<span style="color:#6cf">Traveling: ${label}${destination}</span>`);
  }

  // c.body is the real, live 0-100 needs simulation (systems/body.py) --
  // c.health is a dead legacy dict that schema_defaults only ever
  // defaults to 0.0 and nothing since updates, which made every one of
  // these always read as ~0% regardless of the character's actual state.
  const b = c.body || {};
  const needsMeters = _renderNeedsMeters(b, c.stress);
  if(needsMeters) rows.push(needsMeters);
  if(b.sickness > 30) rows.push(`<span style="color:#fc6">Sick</span>`);

  const hs = c.health_state || {};
  if(hs.severity_index) rows.push(`Severity: ${hs.severity_index.toFixed(2)}`);
  const emergencies = Object.keys(hs.active_emergencies || {});
  if(emergencies.length) rows.push(`<span style="color:#f66">Emergency: ${emergencies.join(", ")}</span>`);

  // Traits/beliefs -- flavored by the character's cognition-core trait
  // (Logical/Balanced/Self-Aware, see backend/systems/schema_defaults.py's
  // COGNITION_CORE_TRAITS): each trait_templates/belief_templates entry
  // carries 3 description flavors, one per cognition type.
  const traitTemplates = definitions.trait_templates || {};
  const beliefTemplates = definitions.belief_templates || {};
  const allTraits = [...(c.traits || []), ...(c.personality_traits || [])];
  const cogInfo = _cognitionInfo(allTraits);
  const cogTmpl = traitTemplates[cogInfo.id];
  if(cogTmpl) rows.push(`Cognition: <b>${cogTmpl.name}</b>`);

  const otherTraits = allTraits.filter(t => !COGNITION_CORE_IDS[t]);
  if(otherTraits.length){
    const traitLines = otherTraits.map(tid => {
      const tmpl = traitTemplates[tid];
      const label = tmpl?.name || tid;
      const desc = _templateDescription(tmpl, COGNITION_FLAVOR[cogInfo.key]);
      return desc ? `${label} <span style="opacity:.65">— ${desc}</span>` : label;
    });
    rows.push(`Traits:<br>&nbsp;&nbsp;${traitLines.join("<br>&nbsp;&nbsp;")}`);
  }

  const heldBeliefs = c.held_beliefs || [];
  if(heldBeliefs.length){
    const beliefLines = heldBeliefs.map(bid => {
      const tmpl = beliefTemplates[bid];
      const label = tmpl?.name || bid;
      const desc = _templateDescription(tmpl, COGNITION_FLAVOR[cogInfo.key]);
      return desc ? `${label} <span style="opacity:.65">— ${desc}</span>` : label;
    });
    rows.push(`Beliefs:<br>&nbsp;&nbsp;${beliefLines.join("<br>&nbsp;&nbsp;")}`);
  }

  // Reputation (c.reputation -- the real, actively-read global/community/
  // notoriety dict; NOT c.status.reputation, a separate write-only field
  // law.py's arrest penalty decrements but nothing ever reads) / popularity
  // (c.popularity, an unbounded accumulate-and-decay validation score) /
  // addictions (c.addictions, only entries actually used at least once).
  const rep = c.reputation || {};
  const repBits = [];
  if(rep.global != null) repBits.push(`global ${Math.round(rep.global * 100)}%`);
  if(rep.community != null) repBits.push(`community ${Math.round(rep.community * 100)}%`);
  if(rep.notoriety) repBits.push(`notoriety ${Math.round(rep.notoriety * 100)}%`);
  if(repBits.length) rows.push(`Reputation: ${repBits.join(" · ")}`);

  if(c.popularity) rows.push(`Popularity: ${c.popularity.toFixed(1)}`);

  const addictionTemplates = definitions.addiction_templates || {};
  const addictionEntries = Object.entries(c.addictions || {}).filter(([, a]) => a?.usages > 0);
  if(addictionEntries.length){
    const lines = addictionEntries.map(([key, a]) => {
      const tmpl = addictionTemplates[key];
      const label = tmpl?.name || key;
      const threshold = tmpl?.threshold || 5;
      const craving = Math.min(1.0, a.usages / (threshold * 2));
      return `${label} <span style="opacity:.65">— ${a.usages} uses, ${Math.round(craving * 100)}% craving</span>`;
    });
    rows.push(`Addictions:<br>&nbsp;&nbsp;${lines.join("<br>&nbsp;&nbsp;")}`);
  }

  el.innerHTML = rows.join("<br>");

  renderEffectIconRow(c);
  renderBodyTab(c);
  renderRelationshipsTab(c);
  renderMindTab(c);
  renderMemoryTab(c);
  renderLifeTab(c);
  renderPlansTab(c);
  renderWorkTab(c);
  renderHabitsTab(c);
  renderSkillsTab(c);
}

// =========================================================
// Small shared helpers for the new category tabs below.
// =========================================================

function _charName(id){
  if(!id) return null;
  return _worldState.characters?.[id]?.name || id;
}

function _section(title, innerHTML){
  return `<div class="viewerSection"><div class="viewerSectionTitle">${title}</div>${innerHTML}</div>`;
}

function _empty(text){
  return `<div class="viewerEmpty">${text}</div>`;
}

function _signed(n, digits = 0){
  const v = Number(n) || 0;
  const cls = v > 0 ? "viewerPos" : (v < 0 ? "viewerNeg" : "");
  const text = v.toFixed(digits);
  return cls ? `<span class="${cls}">${v > 0 ? "+" : ""}${text}</span>` : text;
}

// =========================================================
// RELATIONSHIPS TAB -- every c.relationships[otherId] entry (brain/
// relationships.py::ensure_relationship's full shape). Sorted by how
// "notable" the relationship is (sum of absolute values across the
// dramatic stats) so the most eventful relationships surface first
// instead of alphabetically -- with dozens of background contacts this
// is the difference between useful and unreadable.
// =========================================================

const _REL_NOTABLE_FIELDS = [
  "trust", "friendship", "attraction", "romantic_interest", "comfort",
  "resentment", "hostility", "fear", "rivalry", "jealousy", "creeped_out",
  "favor_frustration",
];

function renderRelationshipsTab(c){
  const el = document.getElementById("viewerRelationshipsTab");
  if(!el) return;

  const rels = c.relationships || {};
  const entries = Object.entries(rels);
  if(!entries.length){
    el.innerHTML = _section("Relationships", _empty("No relationships yet."));
    return;
  }

  entries.sort((a, b) => {
    const score = r => _REL_NOTABLE_FIELDS.reduce((s, f) => s + Math.abs(r[f] || 0), 0);
    return score(b[1]) - score(a[1]);
  });

  const cards = entries.map(([otherId, rel]) => {
    const name = _charName(otherId);
    const labels = (rel.labels || []).join(", ");
    const designation = rel.designation && rel.designation !== "stranger" ? rel.designation : null;

    const stats = [];
    const pushStat = (label, val, digits = 0) => {
      if(!val) return;
      stats.push(`${label} ${_signed(val, digits)}`);
    };
    pushStat("trust", rel.trust);
    pushStat("friendship", rel.friendship);
    pushStat("attraction", rel.attraction);
    pushStat("romantic", rel.romantic_interest);
    pushStat("comfort", rel.comfort);
    pushStat("resentment", rel.resentment);
    pushStat("hostility", rel.hostility);
    pushStat("fear", rel.fear);
    pushStat("rivalry", rel.rivalry);
    pushStat("jealousy", rel.jealousy);
    pushStat("creeped out", rel.creeped_out);
    pushStat("favor frustration", rel.favor_frustration);

    const knownAs = rel.known_as && rel.known_as !== name
      ? `<div class="viewerWarn">Known to them as: ${rel.known_as}</div>` : "";

    return `
      <div class="viewerCard">
        <div class="viewerCardTitle">${name || otherId}</div>
        ${labels || designation ? `<div style="opacity:.7">${[designation, labels].filter(Boolean).join(" · ")}</div>` : ""}
        ${stats.length ? `<div class="viewerStatRow">${stats.join(" · ")}</div>` : ""}
        ${knownAs}
      </div>`;
  });

  el.innerHTML = _section(`Relationships (${entries.length})`, cards.join(""));
}

// =========================================================
// MIND TAB -- self-image/self-esteem, mental & behavioral health,
// addictions, suspicion of others (worries.py), and what the character
// currently wants/intends to do (persistent_desires.py / active
// intentions). Everything here drives behavior but was previously only
// visible by reading the raw world-state JSON.
// =========================================================

// Backing array for the Mind tab's clickable intention cards -- see the
// "Active intentions" section below and openIntentionModal().
let _lastRenderedIntentions = [];

function renderMindTab(c){
  const el = document.getElementById("viewerMindTab");
  if(!el) return;

  const sections = [];

  // -- Self-image / self-esteem --
  const selfLines = [];
  if(c.self_confidence != null) selfLines.push(`psychological ${Math.round(c.self_confidence * 100)}%`);
  if(c.body_confidence != null) selfLines.push(`physical ${Math.round(c.body_confidence * 100)}%`);
  if(c.masculinity_confidence != null) selfLines.push(`masculinity ${Math.round(c.masculinity_confidence * 100)}%`);
  sections.push(_section("Self-Esteem", selfLines.length
    ? `<div class="viewerStatRow">${selfLines.join(" · ")}</div>` : _empty("Not generated yet.")));

  // -- Mental & physical health conditions --
  const mentalHealthTemplates = definitions.mental_health_templates || {};
  const physicalHealthTemplates = definitions.physical_health_templates || {};
  const conditionLines = [];
  for(const key of (c.mental_health || [])){
    const tmpl = mentalHealthTemplates[key];
    const treatment = (c.mental_health_treatment || {})[key];
    const treatLabel = treatment
      ? ` <span class="viewerPos">(${[treatment.in_therapy && "therapy", treatment.on_medication && "medicated"].filter(Boolean).join(", ") || "in treatment"})</span>`
      : "";
    conditionLines.push(`${tmpl?.name || key}${treatLabel}`);
  }
  for(const key of (c.physical_health || [])){
    const tmpl = physicalHealthTemplates[key];
    conditionLines.push(tmpl?.name || key);
  }
  if(conditionLines.length){
    sections.push(_section("Health Conditions", conditionLines.map(l => `<div class="viewerCard">${l}</div>`).join("")));
  }

  // -- Addictions --
  const addictionTemplates = definitions.addiction_templates || {};
  const addictionEntries = Object.entries(c.addictions || {}).filter(([, e]) => (e.usages || 0) > 0);
  if(addictionEntries.length){
    const lines = addictionEntries.map(([key, e]) => {
      const tmpl = addictionTemplates[key];
      const threshold = tmpl?.threshold;
      const label = tmpl?.name || key;
      return `<div class="viewerCard">${label}: ${e.usages}${threshold ? ` / ${threshold}` : ""} uses</div>`;
    });
    sections.push(_section("Addictions", lines.join("")));
  }

  // -- Suspicion of others (worries.py) --
  const worries = Object.entries(c.worries || {}).filter(([, w]) => (w.suspicion_level || 0) > 0.05);
  if(worries.length){
    worries.sort((a, b) => (b[1].suspicion_level || 0) - (a[1].suspicion_level || 0));
    const lines = worries.map(([subjectId, w]) => {
      const lastTrigger = (w.triggers || [])[w.triggers.length - 1];
      return `
        <div class="viewerCard">
          <div class="viewerCardTitle">${_charName(subjectId) || subjectId}</div>
          <div>Suspicion: <span class="viewerWarn">${Math.round((w.suspicion_level || 0) * 100)}%</span></div>
          ${lastTrigger ? `<div style="opacity:.7">${lastTrigger.note || lastTrigger.kind}</div>` : ""}
        </div>`;
    });
    sections.push(_section("Suspicious Of", lines.join("")));
  }

  // -- Active intentions --
  // Cards are clickable -- an intention can carry fields the compact card
  // has no room for (subscribe_service's service_id, a target_id, an
  // expectation's full priority math, ...), reported live as confusing
  // when they're silently dropped. Rather than hand-picking which extra
  // field each intention TYPE deserves, every field is shown, resolved
  // against real names/labels where recognizable (see openIntentionModal).
  // el.innerHTML gets reassigned wholesale below (this function builds one
  // big string and sets it once), so listeners can't be attached inline
  // while building the string -- _lastRenderedIntentions stores the same
  // array this render used, and a delegated click handler (registered
  // once, outside this function) reads back data-intent-index to look the
  // clicked card's original object back up.
  const intentions = c.active_intentions || [];
  _lastRenderedIntentions = intentions;
  if(intentions.length){
    const lines = intentions.map((i, idx) => {
      const outcome = _intentionOutcome(c, i);
      return `
      <div class="viewerCard viewerCardClickable" data-intent-index="${idx}">
        <div class="viewerCardTitle">
          <span class="intentionStatusDot" style="background:${outcome.color};" title="${outcome.label}"></span>
          ${(i.type || "").replace(/_/g, " ")}
          <span style="opacity:.45; font-size:10px; float:right;">${i.category || ""} · ${i.priority ?? 0}</span>
        </div>
        ${i.reason ? `<div style="opacity:.7">${i.reason}</div>` : ""}
      </div>`;
    });
    sections.push(_section(`Intentions (${intentions.length}) — sorted by category, then priority`, lines.join("")));
  }

  // -- Persistent desires --
  const desires = (c.persistent_desires || []).filter(d => d.active && !d.resolved);
  if(desires.length){
    const memoriesById = {};
    (c.memories || []).forEach(m => { if(m.id) memoriesById[m.id] = m; });
    const lines = desires.map(d => {
      // A desire's `target` is usually a memory id (see systems/
      // persistent_desires.py::add_desire / confiding.py) -- surface the
      // triggering memory's own text as the reason this specific desire
      // exists, so e.g. two "confide in someone" entries with the same
      // importance/frustration read as two distinct real events, not an
      // unexplained duplicate.
      const targetMem = d.target ? memoriesById[d.target] : null;
      const reason = targetMem?.text || d.reason;
      return `
      <div class="viewerCard">
        ${(d.type || "").replace(/_/g, " ")}
        <div class="viewerStatRow">importance ${(d.importance ?? 0).toFixed(2)}, frustration ${(d.frustration ?? 0).toFixed(2)}</div>
        ${reason ? `<div style="opacity:.7">"${reason}"</div>` : ""}
      </div>`;
    });
    sections.push(_section(`Desires (${desires.length})`, lines.join("")));
  }

  el.innerHTML = sections.join("");
}

// Per the user's explicit ask: can we tell whether an intention actually
// got achieved? "expectation:<id>" intentions already carry a real,
// backend-tracked outcome (systems/expectations.py's own satisfied/
// pending/missed status, streak, missed_count) -- surfaced directly here
// rather than inventing a new tracking system on top of it. Every other
// intention type has no such explicit lifecycle, so its "outcome" is
// approximated from how long it's been sitting active without getting
// resolved (a real signal: an intention that's been true for a long time
// without anything addressing it really is stalled) -- green/yellow/red
// per the user's own spec (success / still in progress / timed out).
const STALE_INTENTION_TICKS = 1800;   // 30 min with no resolution reads as "stalled"

function _intentionOutcome(c, intention){
  const type = intention.type || "";
  if(type.startsWith("expectation:")){
    const templateId = type.slice("expectation:".length);
    const exp = (c.expectations || {})[templateId];
    if(exp?.status === "satisfied") return { color: "#3ecf5e", label: `Satisfied (streak ${exp.streak ?? 0})` };
    if(exp?.status === "missed") return { color: "#e64545", label: `Missed (${exp.missed_count ?? 0} times)` };
    return { color: "#e6c200", label: "Still pending this period" };
  }
  const age = (_worldState.tick || 0) - (intention.created_at || 0);
  if(age > STALE_INTENTION_TICKS){
    return { color: "#e64545", label: `Stalled -- unresolved for ${_ticksAgoLabel(age)}` };
  }
  return { color: "#e6c200", label: "In progress" };
}

// Delegated click handler for the Mind tab's intention cards (registered
// once here, not per-render -- renderMindTab() reassigns el.innerHTML
// wholesale on every call, which would silently drop any listener
// attached directly to a card element).
document.getElementById("viewerMindTab")?.addEventListener("click", (e) => {
  const card = e.target.closest(".viewerCardClickable");
  if(!card) return;
  const intention = _lastRenderedIntentions[Number(card.dataset.intentIndex)];
  if(intention) openIntentionModal(intention);
});

// Fields that already read naturally as part of the card/title and don't
// need repeating in the detail view.
const _INTENTION_HIDDEN_FIELDS = new Set(["type", "reason"]);

// Field names that hold a character id -- resolved to a real name rather
// than shown as a bare char_xxxxx string.
const _INTENTION_CHAR_ID_FIELDS = new Set(["target_id", "char_id"]);

function _formatIntentionFieldLabel(key){
  return key.replace(/_/g, " ").replace(/\b\w/g, ch => ch.toUpperCase());
}

function _formatIntentionFieldValue(key, value){
  if(value == null || value === "") return "(none)";
  if(key === "created_at"){
    const nowTick = _worldState.tick || 0;
    return `${_ticksAgoLabel(Math.max(0, nowTick - value))} (tick ${value})`;
  }
  if(key === "service_id"){
    const tmpl = (definitions.service_templates || {})[value];
    return tmpl?.name ? `${tmpl.name} (${value})` : String(value);
  }
  if(_INTENTION_CHAR_ID_FIELDS.has(key)){
    const name = _charName(value);
    return name ? `${name} (${value})` : String(value);
  }
  if(key === "context" && typeof value === "object"){
    return Object.entries(value)
      .map(([k, v]) => `${_formatIntentionFieldLabel(k)}: ${_formatIntentionFieldValue(k, v)}`)
      .join(", ");
  }
  if(typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// Full-detail popup for one intention -- every field it carries, not just
// the compact card's type+reason, since some intentions (subscribe_service's
// service_id, anything with a target_id) had real information nowhere else
// visible in the UI. Reuses the shared modal-overlay/openModal infrastructure
// (see the mailbox household modal / event modal) via a new #modal-intention
// container rather than inventing a second popup mechanism.
function openIntentionModal(intention){
  const titleEl = document.getElementById("intentionModalTitle");
  if(titleEl) titleEl.textContent = (intention.type || "Intention").replace(/_/g, " ");

  const body = document.getElementById("intentionModalBody");
  if(!body) return;
  body.innerHTML = "";

  const outcomeChar = selectedCharacterId ? _worldState.characters?.[selectedCharacterId] : null;
  if(outcomeChar){
    const outcome = _intentionOutcome(outcomeChar, intention);
    const outcomeRow = document.createElement("div");
    outcomeRow.className = "eventModalRow";
    outcomeRow.innerHTML = `
      <div class="eventModalRowMeta">Outcome</div>
      <div><span class="intentionStatusDot" style="background:${outcome.color};"></span>${outcome.label}</div>
    `;
    body.appendChild(outcomeRow);
  }

  if(intention.reason){
    const reason = document.createElement("div");
    reason.className = "eventModalRowSummary";
    reason.textContent = intention.reason;
    body.appendChild(reason);
  }

  for(const [key, value] of Object.entries(intention)){
    if(_INTENTION_HIDDEN_FIELDS.has(key)) continue;
    const row = document.createElement("div");
    row.className = "eventModalRow";
    const label = document.createElement("div");
    label.className = "eventModalRowMeta";
    label.textContent = _formatIntentionFieldLabel(key);
    const val = document.createElement("div");
    val.textContent = _formatIntentionFieldValue(key, value);
    row.appendChild(label);
    row.appendChild(val);
    body.appendChild(row);
  }

  openModal("modal-intention");
}

// =========================================================
// MEMORY TAB -- recent memories, notable/tellable stories, and the
// generalized secret-keeping system (secrets.py / secret_keeping.py):
// what's being hidden, from whom, why, and the consistent cover lie.
// A dev/debug view, so secrets are shown plainly rather than obscured --
// same spirit as the LLM request/response log already exposed here.
// =========================================================

// Per-character pagination state for the two memory lists below -- reset
// whenever the selected character changes, same pattern as the Plans
// tab's own _plansLastCharId/_plansDrilldownDay.
let _memoryLastCharId = null;
let _shortTermMemoryPage = 0;
let _longTermMemoryPage = 0;
const SHORT_TERM_MEMORY_PAGE_SIZE = 10;
const LONG_TERM_MEMORY_PAGE_SIZE  = 5;

function _renderMemoryList(title, allItems, page, pageSize, listKey){
  const total = allItems.length;
  if(!total) return _section(title + " (0)", _empty("Nothing yet."));

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const clampedPage = Math.min(page, totalPages - 1);
  const pageItems = allItems.slice(clampedPage * pageSize, (clampedPage + 1) * pageSize);

  const lines = pageItems.map(m => {
    const stamp = _formatMemoryTimestamp(m.tick);
    return `
    <div class="viewerCard">
      ${stamp ? `<div style="opacity:.6">${stamp}</div>` : ""}
      ${m.text}
      ${m.tags?.length ? `<div style="opacity:.6">${m.tags.join(", ")}</div>` : ""}
    </div>`;
  }).join("");

  const pager = totalPages > 1 ? `
    <div class="viewerStatRow" style="justify-content:space-between; align-items:center;">
      <button class="memoryPageBtn" data-memory-list="${listKey}" data-memory-dir="-1" ${clampedPage <= 0 ? "disabled" : ""}>← Newer</button>
      <span style="opacity:.6;">Page ${clampedPage + 1} of ${totalPages}</span>
      <button class="memoryPageBtn" data-memory-list="${listKey}" data-memory-dir="1" ${clampedPage >= totalPages - 1 ? "disabled" : ""}>Older →</button>
    </div>` : "";

  return _section(`${title} (${total})`, lines + pager);
}

// Delegated once, not per-render (renderMemoryTab() reassigns el.innerHTML
// wholesale every call, which would silently drop a listener attached
// directly to a button element).
document.getElementById("viewerMemoryTab")?.addEventListener("click", (e) => {
  const btn = e.target.closest(".memoryPageBtn");
  if(!btn || btn.disabled) return;
  const dir = Number(btn.dataset.memoryDir);
  if(btn.dataset.memoryList === "short"){
    _shortTermMemoryPage = Math.max(0, _shortTermMemoryPage + dir);
  } else {
    _longTermMemoryPage = Math.max(0, _longTermMemoryPage + dir);
  }
  const c = _worldState.characters?.[_memoryLastCharId];
  if(c) renderMemoryTab(c);
});

function renderMemoryTab(c){
  const el = document.getElementById("viewerMemoryTab");
  if(!el) return;

  if(_memoryLastCharId !== c.id){
    _memoryLastCharId = c.id;
    _shortTermMemoryPage = 0;
    _longTermMemoryPage = 0;
  }

  const sections = [];

  const shortTerm = [...(c.memories || [])].sort((a, b) => (b.tick || 0) - (a.tick || 0));
  sections.push(_renderMemoryList("Short-Term Memory", shortTerm, _shortTermMemoryPage, SHORT_TERM_MEMORY_PAGE_SIZE, "short"));

  const longTerm = [...(c.long_term_memory || [])].sort((a, b) => (b.tick || 0) - (a.tick || 0));
  sections.push(_renderMemoryList("Long-Term Memory", longTerm, _longTermMemoryPage, LONG_TERM_MEMORY_PAGE_SIZE, "long"));

  // -- Conversation topics -- pure client-side aggregation of the
  // already-real `topic` field stamped on memories by work-shift/
  // shared-event narration (llm/work_shift_narration.py,
  // llm/shared_event_narration.py), no backend change needed.
  const topicCounts = {};
  for(const m of (c.memories || [])){
    if(!m.topic) continue;
    topicCounts[m.topic] = (topicCounts[m.topic] || 0) + 1;
  }
  const topicEntries = Object.entries(topicCounts).sort((a, b) => b[1] - a[1]);
  if(topicEntries.length){
    const lines = topicEntries.map(([topic, count]) =>
      `<div class="viewerStatRow" style="justify-content:space-between;"><span>${topic}</span><span style="opacity:.7">${count}×</span></div>`
    );
    sections.push(_section(`Conversation Topics (${topicEntries.length})`, lines.join("")));
  }

  // -- Notable stories --
  const stories = c.notable_stories || [];
  if(stories.length){
    const lines = stories.map(s => {
      const stamp = _formatMemoryTimestamp(s.created_tick);
      return `
      <div class="viewerCard">
        ${stamp ? `<div style="opacity:.6">${stamp}</div>` : ""}
        ${s.summary || s.text || ""}
        <div style="opacity:.6">${s.category || ""}${s.value != null ? ` · value ${s.value.toFixed(1)}` : ""}</div>
      </div>`;
    });
    sections.push(_section(`Events (${stories.length})`, lines.join("")));
  }

  // -- Secrets --
  const secrets = c.secrets || [];
  if(secrets.length){
    const lines = secrets.map(s => {
      const targets = Object.keys(s.deception_targets || {}).map(_charName).filter(Boolean);
      return `
        <div class="viewerCard">
          <div class="viewerCardTitle">${s.label || s.content || s.category}</div>
          <div style="opacity:.7">${s.category || ""}${s.severity != null ? ` · severity ${s.severity}` : ""}</div>
          ${s.reason ? `<div>Reason: <i>${s.reason}</i></div>` : ""}
          ${s.preferred_lie ? `<div>Cover story: <i>"${s.preferred_lie}"</i></div>` : ""}
          ${targets.length ? `<div>Hidden from: ${targets.join(", ")}</div>` : ""}
        </div>`;
    });
    sections.push(_section(`Secrets (${secrets.length})`, lines.join("")));
  }

  // -- Active lies --
  const lies = (c.active_lies || []).filter(l => !l.detected);
  if(lies.length){
    const lines = lies.map(l => `
      <div class="viewerCard">
        "${l.lie_text}" <span style="opacity:.6">(${l.question_type})</span>
        <div style="opacity:.6">told to: ${(l.told_to || []).map(_charName).filter(Boolean).join(", ")}</div>
      </div>`);
    sections.push(_section(`Active Lies (${lies.length})`, lines.join("")));
  }

  el.innerHTML = sections.join("");
}

// =========================================================
// LIFE TAB -- career, household/family, finances (moved here from the
// Status tab so Status stays focused on real-time vitals), grievances,
// and household-owned vehicles.
// =========================================================

// =========================================================
// PLANS TAB -- systems/scheduling.py's c["schedule"]["week"], a 7-day
// week grid with drill-down into a single day's detail. Own module-level
// state (which day, if any, is currently drilled into) so switching
// characters or getting a fresh state update doesn't fight the user's
// current view -- reset only when the SELECTED character actually
// changes, not on every routine re-render.
// =========================================================

const SCHEDULE_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const SCHEDULE_DAY_LABELS = { monday: "Mon", tuesday: "Tue", wednesday: "Wed", thursday: "Thu", friday: "Fri", saturday: "Sat", sunday: "Sun" };
const SCHEDULE_ACTIVITY_COLORS = {
  sleep:    "#5b6ee1",
  work:     "#e0a640",
  eat:      "#5ec97a",
  meal:     "#5ec97a",
  leisure:  "#c95ec9",
  hygiene:  "#5ecbc9",
  chore:    "#a0a0a0",
};
const SCHEDULE_DEFAULT_COLOR = "#888";

let _plansDrilldownDay = null;
let _plansLastCharId = null;

function _scheduleColorFor(activity){
  return SCHEDULE_ACTIVITY_COLORS[activity] || SCHEDULE_DEFAULT_COLOR;
}

function _scheduleMinutes(hhmm){
  const [h, m] = (hhmm || "00:00").split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
}

function _scheduleBarSegments(blocks){
  return (blocks || []).map(b => {
    const startMin = _scheduleMinutes(b.start);
    let endMin = _scheduleMinutes(b.end);
    if(endMin <= startMin) endMin += 24 * 60;   // wraps past midnight
    const left = Math.max(0, (startMin / 1440) * 100);
    const width = Math.min(100 - left, ((endMin - startMin) / 1440) * 100);
    return { ...b, left, width };
  });
}

function renderPlansTab(c){
  const el = document.getElementById("viewerPlansTab");
  if(!el) return;

  if(_plansLastCharId !== c.id){
    _plansLastCharId = c.id;
    _plansDrilldownDay = null;
  }

  const week = c.schedule?.week;
  if(!week){
    el.innerHTML = _section("Plans", _empty("No schedule generated for this character yet."));
    return;
  }

  if(_plansDrilldownDay && week[_plansDrilldownDay]){
    el.innerHTML = _renderScheduleDayDetail(_plansDrilldownDay, week[_plansDrilldownDay]);
  } else {
    el.innerHTML = _renderScheduleWeek(week);
  }

  el.querySelectorAll("[data-schedule-day]").forEach(row => {
    row.addEventListener("click", () => {
      _plansDrilldownDay = row.dataset.scheduleDay;
      renderPlansTab(c);
    });
  });
  el.querySelector(".scheduleBackBtn")?.addEventListener("click", () => {
    _plansDrilldownDay = null;
    renderPlansTab(c);
  });
}

function _renderScheduleWeek(week){
  const rows = SCHEDULE_WEEKDAYS.map(day => {
    const segments = _scheduleBarSegments(week[day]);
    const bar = segments.map(seg => `
      <div class="scheduleBlock" title="${seg.activity} ${seg.start}-${seg.end}"
           style="left:${seg.left}%; width:${seg.width}%; background:${_scheduleColorFor(seg.activity)};"></div>
    `).join("");
    return `
      <div class="scheduleDayRow" data-schedule-day="${day}">
        <div class="scheduleDayLabel">${SCHEDULE_DAY_LABELS[day]}</div>
        <div class="scheduleBar">${bar}</div>
      </div>
    `;
  }).join("");

  return _section("Plans — this week (click a day for details)", `
    <div class="scheduleHourAxis"><span>12am</span><span>6am</span><span>12pm</span><span>6pm</span><span>12am</span></div>
    ${rows}
  `);
}

function _renderScheduleDayDetail(day, blocks){
  const segments = _scheduleBarSegments(blocks);
  const bar = segments.map(seg => `
    <div class="scheduleBlock" title="${seg.activity} ${seg.start}-${seg.end}"
         style="left:${seg.left}%; width:${seg.width}%; background:${_scheduleColorFor(seg.activity)};"></div>
  `).join("");

  // Per the user's explicit ask: a block that's already passed today
  // gets a plain checkmark next to it -- no color changes, colors stay
  // exactly as they are. Only meaningful when viewing TODAY's own day
  // (an arbitrary other day in the week has no "current time" to
  // compare against).
  const isToday = _lastCalendar && day === (_lastCalendar.weekday || "").toLowerCase();
  const nowMinutes = isToday && _lastCalendarWorldTick != null && _worldState.tick != null
    ? (() => {
        const proj = _projectCalendarForward(_lastCalendar, _worldState.tick - _lastCalendarWorldTick);
        return proj ? proj.hour * 60 + proj.minute : null;
      })()
    : null;

  const sorted = [...(blocks || [])].sort((a, b) => _scheduleMinutes(a.start) - _scheduleMinutes(b.start));
  const detailRows = sorted.map(b => {
    const completed = nowMinutes != null && _scheduleMinutes(b.end) <= nowMinutes;
    return `
    <div class="scheduleDetailRow">
      <div class="scheduleDetailSwatch" style="background:${_scheduleColorFor(b.activity)};"></div>
      <div class="scheduleDetailTime">${b.start}–${b.end}</div>
      <div>${(b.activity || "").replace(/_/g, " ")}${b.source ? ` <span style="opacity:.5">(${b.source})</span>` : ""}${completed ? ' <span title="Already happened today">✓</span>' : ""}</div>
    </div>
  `;
  }).join("") || _empty("No blocks scheduled this day.");

  return `
    <div class="viewerSection">
      <div class="scheduleDayDetailHeader">
        <div class="viewerSectionTitle" style="margin:0;">${SCHEDULE_DAY_LABELS[day]} — full day</div>
        <button class="scheduleBackBtn">← Week</button>
      </div>
      <div class="scheduleHourAxis"><span>12am</span><span>6am</span><span>12pm</span><span>6pm</span><span>12am</span></div>
      <div class="scheduleBar scheduleBarLarge" style="margin-bottom:10px;">${bar}</div>
      ${detailRows}
    </div>
  `;
}

// GET /api/finances/{id} -- bank balance / total debt / weekly debt cost,
// none of which is part of the WS snapshot/delta payload (see api/
// finances.py's own docstring for why). renderLifeTab() can be re-invoked
// on every WS update while the Life tab is open, so results are cached
// per character for a few seconds rather than re-fetched on every call.
const _financesCache = {};   // characterId -> { data, fetchedAt }
const FINANCES_CACHE_MS = 5000;

async function _fetchCharacterFinances(characterId){
  const cached = _financesCache[characterId];
  const now = Date.now();
  if(cached && now - cached.fetchedAt < FINANCES_CACHE_MS){
    return cached.data;
  }
  try{
    const res = await fetch(`/api/finances/${encodeURIComponent(characterId)}?sim_id=default`);
    const data = await res.json();
    if(data.ok){
      _financesCache[characterId] = { data, fetchedAt: now };
      return data;
    }
  } catch(e){ /* network hiccup -- fall through to stale cache below */ }
  return cached?.data || null;
}

// GET /api/dependents/{id} -- each real c.dependents entry resolved into
// a real whereabouts summary (see api/dependents.py's own docstring).
// Same cached-fetch-and-patch shape as _fetchCharacterFinances above.
const _dependentsCache = {};   // characterId -> { data, fetchedAt }
const DEPENDENTS_CACHE_MS = 5000;

async function _fetchCharacterDependents(characterId){
  const cached = _dependentsCache[characterId];
  const now = Date.now();
  if(cached && now - cached.fetchedAt < DEPENDENTS_CACHE_MS){
    return cached.data;
  }
  try{
    const res = await fetch(`/api/dependents/${encodeURIComponent(characterId)}?sim_id=default`);
    const data = await res.json();
    if(data.ok){
      _dependentsCache[characterId] = { data, fetchedAt: now };
      return data;
    }
  } catch(e){ /* network hiccup -- fall through to stale cache below */ }
  return cached?.data || null;
}

function renderLifeTab(c){
  const el = document.getElementById("viewerLifeTab");
  if(!el) return;

  const sections = [];

  // -- Career --
  const jobTemplates = definitions.job_templates || {};
  const jobTmpl = jobTemplates[c.job_template_id];
  const careerLines = [];
  const jobLabel = jobTmpl?.name || c.profession || c.occupation;
  if(jobLabel) careerLines.push(`${jobLabel}${jobTmpl?.illegal ? " <span class=\"viewerWarn\">(illegal)</span>" : ""}`);
  else careerLines.push("Unemployed");
  if(c.hourly_wage != null) careerLines.push(`$${c.hourly_wage}/hr`);
  if(c.criminal_standing > 0) careerLines.push(`criminal standing ${c.criminal_standing.toFixed(1)}`);
  if(c.corruption > 0) careerLines.push(`corruption ${c.corruption.toFixed(1)}`);
  sections.push(_section("Career", `<div class="viewerStatRow">${careerLines.join(" · ")}</div>`));

  // -- Education --
  const eduLabels = {
    none: "No formal education", none_completed: "No formal education",
    preschool: "Preschool", primary: "Primary school", middle_school: "Middle school",
    high_school: "High school", trade_school: "Trade school", certificate: "Certificate",
    associate: "Associate degree", bachelor: "Bachelor's degree", master: "Master's degree",
    doctorate: "Doctorate", professional: "Professional degree (JD/MD/...)",
  };
  if(c.education){
    const eduLines = [eduLabels[c.education] || c.education];
    if(c.field_of_study) eduLines.push(`in ${c.field_of_study}`);
    if(c.current_school) eduLines.push(`currently attending ${c.current_school}`);
    sections.push(_section("Education", `<div class="viewerStatRow">${eduLines.join(" · ")}</div>`));
  }

  // -- Work history --
  const workHistory = c.work_history || [];
  if(workHistory.length){
    const lines = workHistory.map(w => {
      const years = w.years != null ? `${w.years}y` : "";
      const reason = w.reason_left ? w.reason_left.replace(/_/g, " ") : "";
      return `<div class="viewerCard">${w.title || w.job_template_id}${w.industry ? ` — ${w.industry}` : ""}
        <div style="opacity:.7">${[years, reason].filter(Boolean).join(" · ")}</div></div>`;
    });
    sections.push(_section(`Work History (${workHistory.length})`, lines.join("")));
  }
  const industryExp = Object.entries(c.industry_experience || {});
  if(industryExp.length){
    // industry_experience ticks use jobs.py's own internal "years of
    // experience" convention (TICKS_PER_YEAR = 365*24 = 8760) -- a
    // separate, smaller unit than the sim's real tick-per-second clock,
    // not real elapsed simulation ticks.
    const lines = industryExp
      .sort((a, b) => b[1] - a[1])
      .map(([industry, ticks]) => `${industry} (${(ticks / 8760).toFixed(1)}y)`);
    sections.push(_section("Industry Experience", `<div class="viewerStatRow">${lines.join(" · ")}</div>`));
  }
  if(c.job_search_attempts > 0){
    sections.push(_section("Job Search", `<div class="viewerStatRow">${c.job_search_attempts} application${c.job_search_attempts===1?"":"s"} sent without an interview yet</div>`));
  }

  const factions = c.faction_memberships || [];
  if(factions.length){
    const lines = factions.map(f => `<div class="viewerCard">${f.role || "member"} — ${f.faction_id || f.id || ""}</div>`);
    sections.push(_section("Factions", lines.join("")));
  }

  // -- Finances (moved from Status) --
  // Bank balance / total debt / weekly debt cost live in world["banks"]
  // and household["loans"] -- neither is part of the WS snapshot/delta
  // payload (both non-spatial, not viewport data) -- so those three
  // fields are fetched separately via GET /api/finances/{id} and patched
  // into #lifeFinancesExtra once they arrive, rather than blocking this
  // synchronous render. Everything already present on the character
  // (wallet cash, credit score, credit card debt, tax debt) still renders
  // immediately below, unchanged.
  const wallet = (c.inventory || []).find(i => i.object_type === "wallet");
  const financeLines = [];
  const cash = wallet?.states?.cash ?? wallet?.cash;
  if(cash != null) financeLines.push(`$${Math.round(cash)} cash`);
  if(c.credit_score != null) financeLines.push(`credit score ${c.credit_score}`);
  if(c.government_debt > 0) financeLines.push(`<span class="viewerWarn">$${Math.round(c.government_debt)} owed in taxes</span>`);
  const walletItems = wallet?.items || [];
  const creditCards = walletItems.filter(i => i.object_type === "credit_card");
  for(const card of creditCards){
    financeLines.push(`${card.provider} credit card: $${Math.round(card.current_debt || 0)} / $${Math.round(card.max_credit || 0)}`);
  }
  sections.push(_section("Finances", `
    ${financeLines.length ? `<div class="viewerStatRow">${financeLines.join(" · ")}</div>` : _empty("No financial data.")}
    <div id="lifeFinancesExtra" data-character-id="${c.id}">${_empty("Loading bank/debt details...")}</div>
  `));
  _fetchCharacterFinances(c.id).then(data => {
    const extraEl = document.getElementById("lifeFinancesExtra");
    // Guard against a fetch resolving after the tab moved to a different
    // character (or closed) -- only patch in data for whoever's still
    // actually shown.
    if(!extraEl || extraEl.dataset.characterId !== c.id) return;
    if(!data){ extraEl.innerHTML = ""; return; }
    const lines = [];
    for(const acct of data.bank_accounts || []){
      if(acct.balance != null) lines.push(`${acct.bank}: $${Math.round(acct.balance)}`);
    }
    for(const loan of data.loans || []){
      lines.push(`${(loan.kind || "loan").replace(/_/g, " ")} (${loan.provider || ""}): $${Math.round(loan.balance)} balance · ${loan.rate_pct}% APR`);
      lines.push(`&nbsp;&nbsp;$${loan.weekly_principal.toFixed(2)}/week principal + $${loan.weekly_interest.toFixed(2)}/week interest = $${loan.weekly_payment.toFixed(2)}/week`);
    }
    if(data.total_debt > 0) lines.push(`<span class="viewerWarn">Total debt: $${Math.round(data.total_debt)}</span>`);
    if(data.weekly_debt_cost > 0) lines.push(`$${data.weekly_debt_cost.toFixed(2)}/week household debt cost`);
    extraEl.innerHTML = lines.length ? lines.join("<br>") : "";
  });

  // -- Household / family --
  const householdLines = [];
  if(c.household_id) householdLines.push(`Household: ${c.household_id}`);
  if(c.family_role) householdLines.push(`Family role: ${c.family_role}`);
  sections.push(_section("Household", householdLines.length ? householdLines.join("<br>") : _empty("No household.")));

  // -- Dependents --
  // c.dependents (systems/child_care.py::_sync_dependents) is a real,
  // priority-ordered (youngest/least-capable first) list of ids already
  // on the character over the WS snapshot -- but the resolved whereabouts
  // summary (last contact, current caretaker, expected activity, ...)
  // needs cross-character lookups the frontend shouldn't re-derive, so
  // it's fetched separately via GET /api/dependents/{id} and patched in,
  // same shape as the Finances section above.
  if((c.dependents || []).length){
    sections.push(_section(`Dependents (${c.dependents.length})`, `
      <div id="lifeDependentsExtra" data-character-id="${c.id}">${_empty("Loading dependents...")}</div>
    `));
    _fetchCharacterDependents(c.id).then(data => {
      const extraEl = document.getElementById("lifeDependentsExtra");
      if(!extraEl || extraEl.dataset.characterId !== c.id) return;
      const deps = data?.dependents || [];
      if(!deps.length){ extraEl.innerHTML = _empty("No dependents."); return; }

      const cards = deps.map(d => {
        const loc = d.last_known_location || {};
        const locLine = loc.status === "away"
          ? `Away — ${(loc.reason || "unknown").replace(/_/g, " ")}`
          : `At (${Math.round(loc.x)}, ${Math.round(loc.y)})`;

        const contactLine = d.last_contact
          ? `Last contact: ${d.last_contact.medium.replace(/_/g, " ")} at tick ${d.last_contact.tick}`
          : `Last contact: none on record`;

        const lines = [locLine, contactLine];
        if(d.expected_activity) lines.push(`Expected: ${d.expected_activity.replace(/_/g, " ")}`);
        if(d.current_caretaker) lines.push(`Currently with: ${d.current_caretaker}`);
        if(d.announced_departure === false) lines.push(`<span class="viewerWarn">Left without announcing departure</span>`);
        if(!d.expected_home_today) lines.push(`<span class="viewerWarn">Not expected home today</span>`);
        else if(d.expected_return_tick != null) lines.push(`Expected back around tick ${d.expected_return_tick}`);

        return `
          <div class="viewerCard">
            <div class="viewerCardTitle">${d.name}${d.age != null ? ` (${d.age})` : ""}</div>
            <div style="opacity:.7">${lines.join("<br>")}</div>
          </div>`;
      });
      extraEl.innerHTML = cards.join("");
    });
  }

  const expectationTemplates = definitions.expectation_templates || {};
  const expectations = Object.values(c.expectations || {});
  if(expectations.length){
    const lines = expectations.map(e => {
      const tmpl = expectationTemplates[e.template_id];
      const status = e.status === "missed"
        ? `<span class="viewerNeg">missed ${e.missed_count || 0}x</span>`
        : `<span class="viewerPos">streak ${e.streak || 0}</span>`;
      return `<div class="viewerCard">${tmpl?.label || e.template_id} — ${status}</div>`;
    });
    sections.push(_section("Expectations", lines.join("")));
  }

  // -- Household vehicles --
  const vehicles = (_worldState.props || []).filter(p => p.vehicle_class && p.household_id === c.household_id);
  if(vehicles.length){
    const lines = vehicles.map(v => {
      const owner = v.owner_id ? _charName(v.owner_id) : null;
      return `
        <div class="viewerCard">
          <div class="viewerCardTitle">${v.name}${v.model_name ? ` (${v.model_name})` : ""}</div>
          <div style="opacity:.7">${v.condition}${owner ? ` · owned by ${owner}` : ""}${!v.is_legal ? ` · <span class="viewerNeg">unregistered</span>` : ""}</div>
        </div>`;
    });
    sections.push(_section(`Vehicles (${vehicles.length})`, lines.join("")));
  }

  // -- Grievances --
  const grievances = c.grievances || [];
  if(grievances.length){
    const byTarget = {};
    for(const g of grievances){
      byTarget[g.caused_by] = (byTarget[g.caused_by] || 0) + (g.weight || 0);
    }
    const lines = Object.entries(byTarget).map(([targetId, weight]) => `
      <div class="viewerCard">
        Against ${_charName(targetId) || targetId}: <span class="viewerNeg">${weight.toFixed(1)}</span>
      </div>`);
    sections.push(_section(`Grievances (${grievances.length})`, lines.join("")));
  }

  el.innerHTML = sections.join("");
}

// =========================================================
// WORK TAB -- work-shift summaries (kind==="work_beat" memories),
// workplace contacts/reputation, hire date, boss/recruiter, full
// contract details, and the chosen career-ladder path. Blurred/
// unclickable in #viewerTabs when the character has no job (see the
// tab-disable pass inside this function and the click-handler guard
// below).
// =========================================================

let _workSummaryCount = 2;

function renderWorkTab(c){
  const btn = document.getElementById("viewerWorkTabBtn");
  const el = document.getElementById("viewerWorkTab");
  if(!el) return;

  const contract = c.employment_contract;
  const employed = !!(c.employed && contract);

  if(btn){
    btn.classList.toggle("disabled", !employed);
    // If the currently-employed tab just became unemployed while it was
    // the active one, fall back to Status rather than leaving a blurred,
    // unclickable panel showing.
    if(!employed && btn.classList.contains("active")){
      btn.classList.remove("active");
      document.querySelector('.viewerTabBtn[data-tab="status"]')?.classList.add("active");
      document.getElementById("viewerWorkTab")?.classList.add("hidden");
      document.getElementById("viewerSelection")?.classList.remove("hidden");
    }
  }

  if(!employed){
    el.innerHTML = _empty("Not currently employed.");
    return;
  }

  const sections = [];
  const tick = _worldState.tick || 0;

  // -- Recent work-shift summaries --
  const workBeats = (c.memories || [])
    .filter(m => m.kind === "work_beat")
    .sort((a, b) => (b.tick || 0) - (a.tick || 0));
  const countControl = `
    <div class="viewerStatRow" style="justify-content:flex-end; gap:6px; align-items:center;">
      <span style="opacity:.6;">Show</span>
      <input type="number" id="workSummaryCountInput" min="1" max="50" value="${_workSummaryCount}" style="width:48px;">
      <span style="opacity:.6;">summaries</span>
    </div>`;
  const beatLines = workBeats.slice(0, _workSummaryCount).map(m => {
    const stamp = _formatMemoryTimestamp(m.tick);
    return `
      <div class="viewerCard">
        ${stamp ? `<div style="opacity:.6">${stamp}</div>` : ""}
        ${m.text || m.detail || ""}
      </div>`;
  }).join("") || _empty("No work-shift summaries yet.");
  sections.push(_section(`Recent Work Summaries (${workBeats.length})`, countControl + beatLines));

  // -- Workplace contacts / reputation --
  const contactIds = c.workplace_contact_ids || [];
  if(contactIds.length){
    const rows = contactIds.map(id => {
      const contact = _worldState.characters?.[id];
      const rel = (c.relationships || {})[id] || {};
      const name = contact?.name || id;
      const role = contact?.role || "colleague";
      const rep = rel.workplace_reputation != null ? _signed(rel.workplace_reputation, 0) : "0";
      const dep = rel.workplace_dependency != null ? rel.workplace_dependency.toFixed(0) : "0";
      return `<div class="viewerCard">${name} <span style="opacity:.6">(${role})</span>
        <div style="opacity:.7">reputation ${rep} · dependency ${dep}</div></div>`;
    });
    sections.push(_section(`Workplace Contacts (${contactIds.length})`, rows.join("")));
  }

  // -- Hire date / boss / recruiter --
  const hireLines = [];
  const hireStamp = _formatMemoryTimestamp(contract.signed_tick);
  if(hireStamp) hireLines.push(`Hired: ${hireStamp}`);
  if(contract.signed_tick != null){
    const daysSince = Math.max(0, Math.floor((tick - contract.signed_tick) / 86400));
    hireLines.push(`${daysSince} day${daysSince === 1 ? "" : "s"} since hire`);
  }
  const company = _worldState.companies?.[contract.company_id] || {};
  const bossName = company.boss_id ? _charName(company.boss_id) : null;
  if(bossName) hireLines.push(`Boss: ${bossName}`);
  const recruiterName = contract.recruiter_id ? _charName(contract.recruiter_id) : null;
  if(recruiterName) hireLines.push(`Hired by (recruiter): ${recruiterName}`);
  sections.push(_section("Hiring", hireLines.length ? hireLines.join("<br>") : _empty("No hiring data.")));

  // -- Contract details --
  const contractLines = [];
  if(contract.hourly_wage != null) contractLines.push(`$${contract.hourly_wage}/hr`);
  if(contract.salary != null) contractLines.push(`$${Math.round(contract.salary)}/yr salary`);
  if(contract.projected_raise_per_year_pct != null) contractLines.push(`~${contract.projected_raise_per_year_pct}%/yr projected raise`);
  if(contract.hours_per_week != null) contractLines.push(`${contract.hours_per_week} hrs/week`);
  if(contract.work_hours) contractLines.push(`Hours: ${contract.work_hours[0]}:00 – ${contract.work_hours[1]}:00`);
  if(contract.work_days) contractLines.push(`Days: ${contract.work_days.map(d => SCHEDULE_DAY_LABELS[SCHEDULE_WEEKDAYS[d - 1]] || d).join(", ")}`);

  const respLines = [];
  for(const r of contract.employee_responsibilities || []){
    respLines.push(`<div class="viewerCard">You: ${r.label} <span style="opacity:.6">(${r.cadence})</span></div>`);
  }
  for(const r of contract.employer_responsibilities || []){
    respLines.push(`<div class="viewerCard">Employer: ${r.label} <span style="opacity:.6">(${r.cadence})</span></div>`);
  }

  const clauseLines = Object.entries(contract.conditional_clauses || {}).map(([id, cl]) => `
    <div class="viewerCard">
      <div class="viewerCardTitle">${(cl.description || id)}</div>
      <div style="opacity:.7">${cl.trigger_mode || ""}${cl.triggered ? " · <span class=\"viewerNeg\">triggered</span>" : ""}</div>
    </div>`);

  sections.push(_section("Contract Details", `
    ${contractLines.length ? `<div class="viewerStatRow">${contractLines.join(" · ")}</div>` : ""}
    ${respLines.join("")}
    ${clauseLines.join("")}
  `));

  // -- Career path --
  const progress = c.career_progress;
  if(progress && progress.title){
    const companyLadder = (_worldState.companies?.[progress.company_id] || {}).career_ladder || {};
    const levelData = (companyLadder[progress.title] || {})[progress.ambition] || {};
    const required = levelData.hours_required;
    const worked = progress.hours_worked || 0;
    const progressLine = required
      ? `${worked.toFixed(1)} / ${required} hours toward ${progress.title} (${progress.ambition} ambition)`
      : `${worked.toFixed(1)} hours toward ${progress.title} (${progress.ambition} ambition)`;
    sections.push(_section("Career Path", `<div class="viewerStatRow">${progressLine}</div>`));
  } else {
    sections.push(_section("Career Path", _empty("No active career goal.")));
  }

  el.innerHTML = sections.join("");
}

document.getElementById("viewerWorkTab")?.addEventListener("change", (e) => {
  if(e.target.id !== "workSummaryCountInput") return;
  const val = Math.max(1, Math.min(50, Number(e.target.value) || 2));
  _workSummaryCount = val;
  const c = _worldState.characters?.[selectedCharacterId];
  if(c) renderWorkTab(c);
});

// =========================================================
// HABITS TAB -- interests (c.values, the 12 VALUE_CATEGORIES importance/
// conform weights) and hobbies (c.hobbies, resolved against definitions.
// hobby_templates), plus supported sports teams as a natural hobby
// extension. All real, already-generated data with no Inspector display
// anywhere before this tab.
// =========================================================

const VALUE_CATEGORY_LABELS = {
  family: "Family", friends: "Friends", work: "Work", leisure: "Leisure",
  education: "Education", romance: "Romance", children: "Children",
  religion: "Religion", politics: "Politics", community: "Community",
  solidarity: "Solidarity", traditions: "Traditions",
};

function renderHabitsTab(c){
  const el = document.getElementById("viewerHabitsTab");
  if(!el) return;

  const sections = [];

  // -- Interests (c.values) --
  const values = c.values || {};
  const valueEntries = Object.entries(values)
    .map(([cat, v]) => ({ cat, importance: v?.importance ?? 0, conform: v?.conform }))
    .sort((a, b) => b.importance - a.importance);
  if(valueEntries.length){
    const lines = valueEntries.map(({ cat, importance, conform }) => {
      const pct = Math.round(importance * 100);
      const label = VALUE_CATEGORY_LABELS[cat] || cat;
      const conformNote = conform === true ? "mainstream view"
        : conform === false ? "non-conformist view" : "";
      return `
        <div class="viewerStatRow" style="justify-content:space-between; gap:8px;">
          <span>${label}</span>
          <span style="opacity:.75">${pct}%${conformNote ? ` · ${conformNote}` : ""}</span>
        </div>`;
    });
    sections.push(_section("Interests", lines.join("")));
  } else {
    sections.push(_section("Interests", _empty("No interest data.")));
  }

  // -- Hobbies (c.hobbies -> definitions.hobby_templates) --
  const hobbyTemplates = definitions.hobby_templates || {};
  const hobbies = c.hobbies || [];
  if(hobbies.length){
    const lines = hobbies.map(hid => {
      const tmpl = hobbyTemplates[hid];
      const name = tmpl?.name || hid;
      const category = tmpl?.category ? ` <span style="opacity:.6">(${tmpl.category})</span>` : "";
      return `<div class="viewerCard">${name}${category}</div>`;
    });
    sections.push(_section(`Hobbies (${hobbies.length})`, lines.join("")));
  } else {
    sections.push(_section("Hobbies", _empty("No hobbies picked up yet.")));
  }

  // -- Sports fandom (supported pro teams) --
  const sportsTeams = definitions.sports_teams || {};
  const supported = Object.entries(c.supported_teams || {});
  if(supported.length){
    const lines = supported.map(([sport, teamId]) => {
      const team = sportsTeams[teamId];
      const teamName = team ? `${team.city ? team.city + " " : ""}${team.name || teamId}` : teamId;
      return `<div class="viewerStatRow">${sport}: supports the ${teamName}</div>`;
    });
    sections.push(_section("Sports Fandom", lines.join("")));
  }

  el.innerHTML = sections.join("");
}

// =========================================================
// SKILLS TAB -- c.skills (flat list, skill_templates registry -- empty
// content today, confirmed via a live defs check, so this reliably
// shows "none" rather than being broken), c.natural_talents (flat list,
// natural_talents_registry), and c.abilities (the real D100 skill-check
// engine's per-character progress, systems/abilities.py -- level/
// successes/attempts per ability, resolved against ability_templates
// for a display title and next-level threshold).
// =========================================================

function renderSkillsTab(c){
  const el = document.getElementById("viewerSkillsTab");
  if(!el) return;

  const sections = [];

  const skills = c.skills || [];
  const skillLines = skills.map(s => `<div class="viewerCard">${String(s).replace(/_/g, " ")}</div>`);
  sections.push(_section(`Skills (${skills.length})`, skillLines.join("") || _empty("No skills yet.")));

  const talents = c.natural_talents || [];
  const talentLines = talents.map(t => `<div class="viewerCard">${String(t).replace(/_/g, " ")}</div>`);
  sections.push(_section(`Natural Talents (${talents.length})`, talentLines.join("") || _empty("No natural talents.")));

  const abilityTemplates = definitions.ability_templates || {};
  const abilities = Object.entries(c.abilities || {});
  if(abilities.length){
    const lines = abilities.map(([id, entry]) => {
      const tmpl = abilityTemplates[id];
      const name = tmpl?.name || id;
      const levels = tmpl?.proficiency_levels || [];
      const levelIdx = levels.findIndex(l => l.level === entry.level);
      const levelInfo = levels[levelIdx];
      const title = levelInfo?.title || entry.level || "";
      const nextInfo = levels[levelIdx + 1];
      const progress = levelInfo?.successes_to_next != null
        ? ` — ${entry.successes || 0} / ${levelInfo.successes_to_next} to ${nextInfo ? nextInfo.title : "next level"}`
        : " — max level";
      return `<div class="viewerCard">${name}: <b>${title}</b>${progress}
        <div style="opacity:.6">${entry.attempts || 0} attempts</div></div>`;
    });
    sections.push(_section(`Abilities (${abilities.length})`, lines.join("")));
  } else {
    sections.push(_section("Abilities", _empty("No ability progress yet.")));
  }

  el.innerHTML = sections.join("");
}

// Effect-icon row (disease-schema-overhaul round, frontend Round 7) --
// always visible under #viewerTabs regardless of active tab, per spec.
// One icon per active disease (definitions.icon_templates via physical_
// health_templates[key].icon) plus one per active hazard instance that
// carries expires_tick (health_state.body_parts[*].hazards / systemic_
// hazards, mirrored at onset by health.py::_tick_disease_symptom).
// Tooltips reuse the native title= pattern BADGE_CHANNELS already
// established (main.js's only tooltip mechanism) -- no new hover component.
function renderEffectIconRow(c){
  const rowEl = document.getElementById("viewerEffectIcons");
  if(!rowEl) return;

  const iconTemplates = definitions.icon_templates || {};
  const phTemplates = definitions.physical_health_templates || {};
  const hazardTemplates = definitions.health_hazard_templates || {};
  const tick = _worldState.tick || 0;

  const icons = [];

  for(const condKey of (c?.physical_health || [])){
    const tmpl = phTemplates[condKey];
    if(!tmpl) continue;
    const icon = iconTemplates[tmpl.icon];
    const emoji = icon?.emoji || "❓";
    const title = tmpl.description ? `${tmpl.name}: ${tmpl.description}` : (tmpl.name || condKey);
    icons.push({ emoji, title });
  }

  const hs = c?.health_state || {};
  const hazardInstances = [];
  for(const bp of Object.values(hs.body_parts || {})){
    for(const [key, hz] of Object.entries(bp?.hazards || {})){
      hazardInstances.push([key, hz]);
    }
  }
  for(const [key, hz] of Object.entries(hs.systemic_hazards || {})){
    hazardInstances.push([key, hz]);
  }

  for(const [key, hz] of hazardInstances){
    const tmpl = hazardTemplates[key];
    if(!tmpl) continue;
    const icon = iconTemplates[tmpl.icon];
    const emoji = icon?.emoji || "⚠️";
    let title = tmpl.description ? `${tmpl.name}: ${tmpl.description}` : (tmpl.name || key);
    if(hz.expires_tick != null){
      const remain = hz.expires_tick - tick;
      title += remain > 0 ? ` (${Math.max(1, Math.round(remain / 60))}m remaining)` : " (resolving)";
    }
    icons.push({ emoji, title });
  }

  rowEl.innerHTML = icons
    .map(({ emoji, title }) => `<span class="effectIcon" title="${title.replace(/"/g, "&quot;")}">${emoji}</span>`)
    .join("");
}

// Per-bodypart damage diagram (per-bodypart damage/health/disease rework,
// Round 7) -- colors the inline SVG humanoid in index.html by each part's
// severity_level, then lists hazards/functional-status per part below it,
// plus active diseases + whatever symptom is currently felt
// (health_state.body_parts / c.physical_health, both forwarded unfiltered
// by the server same as every other character field). Called from
// renderCharacterInspector() so it stays live on every WS delta exactly
// like the rest of the Inspector, regardless of whether the Body tab is
// the one currently visible.
const _BODY_PART_NAMES = [
  "head", "neck", "chest", "abdomen", "pelvis",
  "left_arm", "right_arm", "left_leg", "right_leg",
];
const _SEVERITY_COLORS = {
  null:     "#2e5", // no damage
  low:      "#dd4",
  medium:   "#e80",
  severe:   "#d33",
};

// Physical appearance (c.body_features -- the real, populated source;
// c.appearance is a separate, confirmed-dead field, always initialized
// to null and never actually written anywhere) + demographics. Neither
// had anywhere to show before this.
const BUILD_LABELS = {
  slim: "Slim", average: "Average", athletic: "Athletic",
  stocky: "Stocky", heavy: "Heavy",
};

function renderAppearanceBlock(c){
  const el = document.getElementById("bodyTabAppearance");
  if(!el) return;

  const bf = c.body_features || {};
  const appearanceBits = [];
  if(bf.height_cm != null) appearanceBits.push(`${bf.height_cm} cm`);
  if(bf.build) appearanceBits.push(BUILD_LABELS[bf.build] || bf.build);
  if(c.current_hairstyle) appearanceBits.push(`${c.current_hairstyle.replace(/_/g, " ")} hair`);
  // Fertility-signal fields (female/intersex only) -- real data, just
  // narrower in scope than a general appearance model.
  for(const field of ["breast_size", "hip_ratio", "thigh_build"]){
    if(bf[field]) appearanceBits.push(bf[field].replace(/_/g, " "));
  }
  // hair_color/eye_color/clothing_style (c.appearance) are always null
  // today -- nothing in the backend ever assigns them -- so they're
  // deliberately left out rather than always showing "not set".

  const demographicsBits = [];
  if(c.gender_identity) demographicsBits.push(c.gender_identity.replace(/_/g, " "));
  if(c.sexual_orientation) demographicsBits.push(c.sexual_orientation.replace(/_/g, " "));
  if(c.ssn) demographicsBits.push(`SSN ${c.ssn}`);

  const lines = [];
  if(appearanceBits.length) lines.push(`<div class="viewerStatRow">${appearanceBits.join(" · ")}</div>`);
  if(demographicsBits.length) lines.push(`<div class="viewerStatRow" style="opacity:.8">${demographicsBits.join(" · ")}</div>`);
  el.innerHTML = lines.join("") || "";
}

function renderBodyTab(c){
  const svgRoot = document.querySelector("#viewerBodyTab svg");
  const summaryEl = document.getElementById("bodyTabSummary");
  const rowsEl = document.getElementById("bodyTabRows");
  const diseaseEl = document.getElementById("bodyTabDiseases");
  if(!svgRoot || !summaryEl || !rowsEl || !diseaseEl) return;

  renderAppearanceBlock(c);

  const hs = c?.health_state || {};
  const bodyParts = hs.body_parts || {};

  for(const part of _BODY_PART_NAMES){
    const shape = document.getElementById(`bodypart-${part}`);
    if(!shape) continue;
    const bp = bodyParts[part];
    const color = _SEVERITY_COLORS[bp?.severity_level] || _SEVERITY_COLORS[null];
    shape.setAttribute("fill", color);
  }

  const summaryBits = [];
  const untreatedCount = Object.values(bodyParts).reduce(
    (n, bp) => n + Object.values(bp.hazards || {}).filter(h => !h.treated).length, 0
  );
  if(untreatedCount) summaryBits.push(`Untreated hazards: ${untreatedCount}`);
  summaryEl.innerHTML = summaryBits.join("<br>") || "No injuries.";

  const rows = [];
  for(const part of _BODY_PART_NAMES){
    const bp = bodyParts[part];
    if(!bp || (!bp.severity_level && !Object.keys(bp.hazards || {}).length)) continue;
    const hazardNames = Object.entries(bp.hazards || {})
      .map(([key, hz]) => `${key.replace(/_/g, " ")}${hz.treated ? " (treated)" : ""}`)
      .join(", ") || "none";
    const status = bp.functional_status || "normal";
    const statusColor = status === "unusable" ? "#d33" : status === "impaired" ? "#e80" : "#8c8";
    rows.push(`
      <div class="bodyPartRow">
        <span class="partName">${part.replace(/_/g, " ")}</span>
        (${bp.severity_level || "none"}) —
        <span style="color:${statusColor}">${status}</span><br>
        Hazards: ${hazardNames}
      </div>
    `);
  }
  rowsEl.innerHTML = rows.join("") || `<div class="bodyPartRow">No injuries.</div>`;

  const conditions = c?.physical_health || [];
  if(conditions.length){
    const conditionState = c?.condition_state || {};
    const lines = conditions.map(key => {
      const symptom = conditionState[key]?.current_symptom;
      return symptom ? `${key.replace(/_/g, " ")} (${symptom.replace(/_/g, " ")})` : key.replace(/_/g, " ");
    });
    diseaseEl.innerHTML = `<b>Diseases:</b> ${lines.join(", ")}`;
  } else {
    diseaseEl.innerHTML = "";
  }
}

function updateSelectionInspector(state){
  if(!selectedCharacterId) return;
  renderCharacterInspector(selectedCharacterId);
}

// Generalized tab switcher -- one delegated handler + a name->panel-id
// map, replacing the old pair of hardcoded Status/Body handlers so adding
// a new Inspector tab is just one map entry + one button, not a new
// hand-copied click handler each time.
const VIEWER_TAB_PANELS = {
  status:        "viewerSelection",
  body:          "viewerBodyTab",
  relationships: "viewerRelationshipsTab",
  mind:          "viewerMindTab",
  memory:        "viewerMemoryTab",
  life:          "viewerLifeTab",
  plans:         "viewerPlansTab",
  work:          "viewerWorkTab",
  habits:        "viewerHabitsTab",
  skills:        "viewerSkillsTab",
};

document.getElementById("viewerTabs")?.addEventListener("click", (e) => {
  const btn = e.target.closest(".viewerTabBtn");
  if(!btn || btn.classList.contains("disabled")) return;
  const tab = btn.dataset.tab;
  document.querySelectorAll(".viewerTabBtn").forEach(b => b.classList.toggle("active", b === btn));
  for(const [name, panelId] of Object.entries(VIEWER_TAB_PANELS)){
    document.getElementById(panelId)?.classList.toggle("hidden", name !== tab);
  }
});

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
// type="module" scripts don't leak top-level function names to global
// scope -- closeModal was already exposed this way for its inline
// onclick="closeModal(...)" consumers; openModal needs the same
// treatment or any HTML-side caller throws "openModal is not defined".
window.openModal = openModal;

// Read-only hooks for src/operator_view.js's Director Panel -- it has no
// other way to know which character the existing click-to-select/Inspector
// mechanism currently has selected, since selectedCharacterId/_worldState
// are plain module-scope variables in this file, not exported (this
// codebase's cross-script convention is window.* globals, matching
// window.openModal/closeModal above, not ES module exports).
window.getSelectedCharacterId = () => selectedCharacterId;
window.getSelectedCharacterName = () => {
  if (!selectedCharacterId) return null;
  return _worldState.characters?.[selectedCharacterId]?.name || selectedCharacterId;
};

document.querySelectorAll(".modal-overlay").forEach(overlay => {
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.classList.remove("open");
  });
});

// Debug overlay settings trigger -- addEventListener, not an inline
// onclick, to avoid the same module-scope pitfall openModal itself had.
const debugSettingsBtn = document.getElementById("debugSettingsBtn");
if(debugSettingsBtn){
  debugSettingsBtn.addEventListener("click", openDebugSettingsModal);
}

// =========================================================
// SOCIETAL OVERVIEW MODALS -- stocks/statistics/crime/politics/budget/
// news. One button + modal + fetch-on-open per api/overview.py endpoint,
// mirroring fetchEvents()'s on-open fetch shape. No charting library --
// the stock sparkline is a small inline SVG built directly from the
// endpoint's own timestamped history, consistent with how this project
// already avoids new frontend dependencies for small visualizations.
// =========================================================

function _sparklineSvg(history, width = 120, height = 28){
  if(!history || history.length < 2) return "";
  const prices = history.map(h => typeof h === "object" ? h.price : h);
  const min = Math.min(...prices), max = Math.max(...prices);
  const range = (max - min) || 1;
  const step = width / (prices.length - 1);
  const points = prices
    .map((p, i) => `${(i * step).toFixed(1)},${(height - ((p - min) / range) * height).toFixed(1)}`)
    .join(" ");
  const color = prices[prices.length - 1] >= prices[0] ? "#7ee787" : "#ff8080";
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
}

async function _fetchOverview(endpoint){
  try{
    const res = await fetch(`/api/overview/${endpoint}?sim_id=default`);
    const data = await res.json();
    return data.ok ? data : null;
  } catch(e){
    return null;
  }
}

const _OVERVIEW_LOADING = `<div class="eventModalRowSummary">Loading…</div>`;
const _OVERVIEW_FAILED  = `<div class="eventModalRowSummary">Failed to load.</div>`;

async function openStocksModal(){
  openModal("modal-stocks");
  const body = document.getElementById("stocksModalBody");
  body.innerHTML = _OVERVIEW_LOADING;
  const data = await _fetchOverview("stocks");
  if(!data){ body.innerHTML = _OVERVIEW_FAILED; return; }
  const rows = data.stocks.map(s => `
    <div class="viewerCard">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
        <div>
          <b>${s.name}</b> <span style="opacity:.6">(${s.ticker})</span><br/>
          <span style="opacity:.6">${s.sector || ""}</span>
        </div>
        <div style="text-align:right">
          $${(s.price ?? 0).toFixed(2)}
          <span class="${s.change_pct >= 0 ? "viewerPos" : "viewerNeg"}">${s.change_pct >= 0 ? "+" : ""}${s.change_pct}%</span><br/>
          ${_sparklineSvg(s.history)}
        </div>
      </div>
      <div style="opacity:.6;font-size:.85em">Shares available: ${s.shares_available ?? "n/a"} / ${s.num_shares ?? "n/a"}</div>
    </div>`).join("");
  body.innerHTML = rows || "<div class=\"eventModalRowSummary\">No stocks.</div>";
}

async function openStatisticsModal(){
  openModal("modal-statistics");
  const body = document.getElementById("statisticsModalBody");
  body.innerHTML = _OVERVIEW_LOADING;
  const data = await _fetchOverview("statistics");
  if(!data){ body.innerHTML = _OVERVIEW_FAILED; return; }
  const rows = data.statistics.map(s => `
    <div class="eventModalRow">
      <div class="eventModalRowMeta">${s.label}</div>
      <div>${s.value}${s.unit ? " " + s.unit : ""}</div>
    </div>`).join("");
  body.innerHTML = rows || "<div class=\"eventModalRowSummary\">No data.</div>";
}

async function openCrimeModal(){
  openModal("modal-crime");
  const body = document.getElementById("crimeModalBody");
  body.innerHTML = _OVERVIEW_LOADING;
  const data = await _fetchOverview("crime");
  if(!data){ body.innerHTML = _OVERVIEW_FAILED; return; }
  const rateRows = Object.entries(data.rates || {}).map(([k, v]) => `
    <div class="eventModalRow">
      <div class="eventModalRowMeta">${_formatIntentionFieldLabel(k)}</div>
      <div>${v}</div>
    </div>`).join("");
  const incidentRows = Object.entries(data.recent_incidents_by_type || {}).map(([k, v]) => `
    <div class="eventModalRow">
      <div class="eventModalRowMeta">${_formatIntentionFieldLabel(k)}</div>
      <div>${v}</div>
    </div>`).join("");
  body.innerHTML = `
    <div class="eventModalRowSummary">Crime rates</div>${rateRows}
    <div class="eventModalRowSummary">Recent incidents (last ${data.recent_incident_count})</div>
    ${incidentRows || "<div class=\"eventModalRowSummary\">None recorded.</div>"}
  `;
}

async function openPoliticsModal(){
  openModal("modal-politics");
  const body = document.getElementById("politicsModalBody");
  body.innerHTML = _OVERVIEW_LOADING;
  const data = await _fetchOverview("politics");
  if(!data){ body.innerHTML = _OVERVIEW_FAILED; return; }
  const factionRows = (data.factions || []).map(f => `
    <div class="eventModalRow">
      <div class="eventModalRowMeta">${f.name}</div>
      <div>${f.member_count} members${f.agenda.length ? " — " + f.agenda.join(", ") : ""}</div>
    </div>`).join("");
  const billRows = (data.legislation || []).map(b => `
    <div class="viewerCard">
      <b>${b.title}</b> <span style="opacity:.6">(${b.status})</span><br/>
      <span style="opacity:.6">Vote at tick ${b.vote_tick}${b.status !== "pending" ? ` — ${b.votes_for} for / ${b.votes_against} against` : ""}</span>
    </div>`).join("");
  const election = data.election || {};
  body.innerHTML = `
    <div class="eventModalRowSummary">Election: ${election.result ? `last winner "${election.result}"` : "in progress"}, next in ${election.days_until_election ?? "?"} days</div>
    <div class="eventModalRowSummary">Factions</div>${factionRows}
    <div class="eventModalRowSummary">Legislation</div>
    ${billRows || "<div class=\"eventModalRowSummary\">No bills queued.</div>"}
  `;
}

async function openBudgetModal(){
  openModal("modal-budget");
  const body = document.getElementById("budgetModalBody");
  body.innerHTML = _OVERVIEW_LOADING;
  const data = await _fetchOverview("budget");
  if(!data){ body.innerHTML = _OVERVIEW_FAILED; return; }
  const rows = Object.entries(data.spending_categories || {}).map(([cat, d]) => `
    <div class="eventModalRow">
      <div class="eventModalRowMeta">${_formatIntentionFieldLabel(cat)}</div>
      <div>${Math.round((d.share || 0) * 100)}% share — $${(d.total_spent || 0).toLocaleString()} spent to date</div>
    </div>`).join("");
  body.innerHTML = `<div class="eventModalRowSummary">Treasury: $${(data.treasury || 0).toLocaleString()}</div>${rows}`;
}

async function openNewsModal(){
  openModal("modal-news");
  const body = document.getElementById("newsModalBody");
  body.innerHTML = _OVERVIEW_LOADING;
  const data = await _fetchOverview("news");
  if(!data){ body.innerHTML = _OVERVIEW_FAILED; return; }
  const rows = (data.news || []).map(n => `
    <div class="viewerCard">
      <b>${n.headline}</b><br/>
      ${n.summary || ""}<br/>
      <span style="opacity:.6">${n.source || ""} · ${n.sentiment || ""}</span>
    </div>`).join("");
  body.innerHTML = rows || "<div class=\"eventModalRowSummary\">No recent news.</div>";
}

[
  ["stocksBtn", openStocksModal],
  ["statisticsBtn", openStatisticsModal],
  ["crimeBtn", openCrimeModal],
  ["politicsBtn", openPoliticsModal],
  ["budgetBtn", openBudgetModal],
  ["newsBtn", openNewsModal],
].forEach(([id, handler]) => {
  const btn = document.getElementById(id);
  if(btn) btn.addEventListener("click", handler);
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
    const cash = m.wallet_cash != null ? `$${m.wallet_cash.toFixed(2)}` : "no wallet";
    const score = m.credit_score != null ? `credit ${m.credit_score}` : "";
    const debt = m.government_debt ? `, $${m.government_debt.toFixed(2)} owed` : "";
    label.textContent = `${m.name || m.id} — ${cash}${score ? ", " + score : ""}${debt}`;
    label.title = (m.credit_cards || []).length
      ? (m.credit_cards || []).map(c => `${c.provider}: $${(c.current_debt || 0).toFixed(2)}/$${(c.max_credit || 0).toFixed(2)}`).join(", ")
      : "";
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

  // --- Finances ---
  const finH = document.createElement("h4");
  finH.textContent = "Finances";
  body.appendChild(finH);

  const potRow = document.createElement("div");
  potRow.className = "modal-row";
  const billsOwed = (h.bills_due || []).reduce((sum, b) => sum + Math.max(0, b.remaining || 0), 0);
  potRow.innerHTML = `<span>Household pot: $${(h.shared_funds || 0).toFixed(2)} · ` +
    `Net worth: $${(h.wealth || 0).toFixed(2)} · ` +
    `Bills owed: $${billsOwed.toFixed(2)}</span>`;
  body.appendChild(potRow);

  const subRow = document.createElement("div");
  subRow.className = "modal-row";
  const subLabel = document.createElement("span");
  subLabel.textContent = "Newspaper subscription: " + (h.newspaper_subscription ? "active" : "none");
  const subBtn = document.createElement("button");
  subBtn.textContent = h.newspaper_subscription ? "Cancel" : "Subscribe";
  subBtn.addEventListener("click", async () => {
    await fetch("/api/household/set_newspaper_subscription?sim_id=default", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ household_id: h.id, subscribed: !h.newspaper_subscription }),
    });
    refresh();
  });
  subRow.appendChild(subLabel);
  subRow.appendChild(subBtn);
  body.appendChild(subRow);

  const loanH = document.createElement("h5");
  loanH.textContent = "Loans";
  loanH.style.margin = "8px 0 4px";
  body.appendChild(loanH);

  if (!h.loans.length) {
    const empty = document.createElement("div");
    empty.className = "modal-empty";
    empty.textContent = "No loans.";
    body.appendChild(empty);
  }
  for (const l of h.loans) {
    const row = document.createElement("div");
    row.className = "modal-row";
    const label = document.createElement("span");
    label.textContent = `${l.provider} (${l.kind}) — $${(l.balance || 0).toFixed(2)} of ` +
      `$${(l.principal || 0).toFixed(2)}, $${(l.monthly_payment || 0).toFixed(2)}/mo · ` +
      `${(l.borrower_names || []).join(", ")}`;
    row.appendChild(label);
    body.appendChild(row);
  }

  // --- Mail ---
  // household["mailbox"]["items"] (systems/mail.py) -- physical mail
  // (bills, formal-request letters), distinct from a character's own
  // c["inbox"] (SMS/call/email/voicemail, systems/inbox.py). Never
  // trimmed server-side, so this doubles as full history.
  const mail = h.mail || { unopened_count: 0, items: [] };
  const mailH = document.createElement("h4");
  mailH.textContent = "Mail" + (mail.unopened_count ? ` — ${mail.unopened_count} not picked up` : "");
  mailH.style.margin = "10px 0 4px";
  body.appendChild(mailH);

  const mailControls = document.createElement("div");
  mailControls.className = "modal-row";
  const mailSearch = document.createElement("input");
  mailSearch.type = "search";
  mailSearch.placeholder = "Search mail (subject, sender)...";
  mailSearch.style.flex = "1";
  const mailTypeSelect = document.createElement("select");
  const mailTypes = [...new Set(mail.items.map(m => m.type).filter(Boolean))].sort();
  mailTypeSelect.innerHTML = `<option value="">All categories</option>` +
    mailTypes.map(t => `<option value="${t}">${t}</option>`).join("");
  mailControls.appendChild(mailSearch);
  mailControls.appendChild(mailTypeSelect);
  body.appendChild(mailControls);

  const mailListEl = document.createElement("div");
  mailListEl.style.maxHeight = "220px";
  mailListEl.style.overflowY = "auto";
  body.appendChild(mailListEl);

  function renderMailList() {
    const q = mailSearch.value.trim().toLowerCase();
    const typeFilter = mailTypeSelect.value;
    // Most recent first -- items arrive in tick order, never reordered/trimmed.
    const filtered = [...mail.items].reverse().filter(m => {
      if (typeFilter && m.type !== typeFilter) return false;
      if (!q) return true;
      const haystack = [m.subject, m.title, m.from, m.sender, m.type, m.subtype]
        .filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(q);
    });

    mailListEl.innerHTML = "";
    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "modal-empty";
      empty.textContent = mail.items.length ? "No mail matches." : "No mail.";
      mailListEl.appendChild(empty);
      return;
    }
    for (const m of filtered) {
      const row = document.createElement("div");
      row.className = "modal-row";
      const subject = m.subject || m.title || "(no subject)";
      const from = m.from || m.sender || "unknown sender";
      const amount = m.amount != null ? ` — $${Number(m.amount).toFixed(2)}` : "";
      const badge = m.subtype ? `${m.type}/${m.subtype}` : m.type || "mail";
      const span = document.createElement("span");
      span.textContent = `[${badge}] ${subject}${amount} — from ${from}`;
      if (!m.opened) span.style.fontWeight = "bold";   // not picked up yet
      row.appendChild(span);
      mailListEl.appendChild(row);
    }
  }
  renderMailList();
  mailSearch.addEventListener("input", renderMailList);
  mailTypeSelect.addEventListener("change", renderMailList);
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
  // Tier 0 (very zoomed out, down to controls.minZoom) maps to the server's
  // widest radius tier so the loaded window actually keeps growing as the
  // camera keeps pulling back, instead of capping out at tier 1's radius.
  const zoom = camera.zoom > 1.8 ? 3 : camera.zoom > 0.9 ? 2 : camera.zoom > 0.35 ? 1 : 0;
  if (cx !== _viewport.cx || cy !== _viewport.cy || zoom !== _viewport.zoom) {
    _viewport = { cx, cy, zoom };
    _sendViewport(ws);
  }
}

// Confirmed live bug report: a character walking away from wherever the
// camera happened to be left (e.g. after clicking them once in the
// outliner -- see focusCameraOn()'s one-shot call site) falls outside
// the server's per-client viewport radius (main.py::_view_radius/
// in_view) and stops receiving updates at all -- reads as "the map
// won't load"/"character walked out of view" even though their
// underlying position is perfectly sane. Rather than widening the
// radius (a real perf cost for every client, all the time), keep the
// camera translated onto whoever's selected every state update -- a
// soft follow that only shifts translation (preserving the user's own
// zoom/angle, unlike focusCameraOn()'s full re-frame) so the character
// -- and the geometry around them -- never leaves the tracked viewport
// in the first place. controls.update() dispatches "change", which
// connectWS()'s existing debounced listener already turns into a
// _updateViewport() call, so the server-side radius re-centers for
// free, no separate network call needed here.
function _followSelectedCharacter(state) {
  if (!selectedCharacterId) return;
  const c = state.characters?.[selectedCharacterId];
  if (!c || c.x == null || c.y == null) return;

  const targetX = c.x - 10;
  const targetZ = c.y - 7;
  const dx = targetX - controls.target.x;
  const dz = targetZ - controls.target.z;
  if (dx === 0 && dz === 0) return;

  controls.target.x += dx;
  controls.target.z += dz;
  camera.position.x += dx;
  camera.position.z += dz;
  controls.update();
}

async function _applyState(state) {
  definitions = state.definitions || definitions;
  _rebuildStanceMaps(state.definitions);
  updateTiles(state);
  await updateProps(state);
  await updatePlacedItems(state);
  await updateWorldObjects(state);
  updateResponders(state);
  updateFloorplanFloors(state);
  updateFloorplanWalls(state);
  await updateCharacters(state);
  updateSpeechBubbles(state);
  _logCharacterEvents(state);
  updateOrgasmMeters(state);
  updateThoughtBubbles(state);
  updateDebugEventBubbles(state);
  updateBadges(state);
  updatePerceptionOverlay(state);
  updateSelectionInspector(state);
  _followSelectedCharacter(state);
}

async function _applyDelta(delta) {
  // Merge changed characters and props into cached world state
  if (delta.tick != null) {
    _worldState.tick = delta.tick;
  }
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
  if (delta.placed_items) {
    _worldState.placed_items = { ...(_worldState.placed_items || {}), ...delta.placed_items };
  }
  if (delta.world_objects) {
    // world_objects is a plain list (matches server shape) -- merge by id.
    if (!_worldState._worldObjectsMap) {
      _worldState._worldObjectsMap = {};
      for (const o of (_worldState.world_objects || [])) if (o.id) _worldState._worldObjectsMap[o.id] = o;
    }
    Object.assign(_worldState._worldObjectsMap, delta.world_objects);
    _worldState.world_objects = Object.values(_worldState._worldObjectsMap);
  }
  if (delta.responders) {
    // Sent as the full current visible set each time (see main.py::
    // _build_delta), not a sparse per-id patch -- replace wholesale so a
    // responder that's no longer active actually disappears.
    _worldState.responders = delta.responders;
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

  // Report viewport when camera moves (throttled, not on every frame of a
  // drag/zoom gesture). This used to be 1000ms, which meant up to a full
  // second where the server kept filtering delta updates against a stale
  // viewport center after the camera had already moved -- newly-visible
  // tiles got no updates in that window, then the eventual resync tore
  // down and rebuilt everything outside the new radius in one synchronous
  // swap (see updateTiles() below). Combined with the server no longer
  // resyncing on trivial drift (see main.py's movement-threshold check),
  // a shorter throttle here keeps that stale window small without
  // spamming the socket on every mouse-move tick.
  let _vpTimer = null;
  controls.addEventListener("change", () => {
    if (_vpTimer) return;
    _vpTimer = setTimeout(() => {
      _vpTimer = null;
      _updateViewport(ws);
    }, 300);
  });

  return ws;
}

connectWS();

// =========================================================
// EVENT TIMELINE
// Plain REST poll against api/events.py -- events aren't tied to a
// viewport radius the way characters/props/tiles are, so this doesn't
// ride the WS snapshot/delta protocol at all.
// =========================================================

const EVENT_TIMELINE_VISIBLE_KEY = "holosims_timeline_visible";
let _timelineVisible = localStorage.getItem(EVENT_TIMELINE_VISIBLE_KEY) !== "0";

const eventTimelineEl          = document.getElementById("eventTimeline");
const timelineToggleBtn        = document.getElementById("timelineToggleBtn");
const eventTimelinePointsEl    = document.getElementById("eventTimelinePoints");
const eventTimelineLabelLeftEl = document.getElementById("eventTimelineLabelLeft");
const eventTimelineTooltipEl   = document.getElementById("eventTimelineTooltip");

function _applyTimelineVisibility(){
  if(eventTimelineEl) eventTimelineEl.style.display = _timelineVisible ? "block" : "none";
}
_applyTimelineVisibility();

if(timelineToggleBtn){
  timelineToggleBtn.addEventListener("click", () => {
    _timelineVisible = !_timelineVisible;
    localStorage.setItem(EVENT_TIMELINE_VISIBLE_KEY, _timelineVisible ? "1" : "0");
    _applyTimelineVisibility();
  });
}

// =========================================================
// TERMINAL LOG
// A scrollable, timestamped history of every speech/thought bubble --
// updateSpeechBubbles()/updateThoughtBubbles() below call terminalLog()
// at the exact point each already decides a bubble is showing NEW
// content, so an entry lands here whenever (and only when) a bubble
// would actually appear. Docked under the event timeline; expandable by
// dragging its resize handle (native CSS `resize: vertical`).
// =========================================================

const TERMINAL_LOG_VISIBLE_KEY = "holosims_terminal_log_visible";
const TERMINAL_LOG_MAX_ENTRIES = 500;
const _lastLoggedSpeech = {};   // id -> last logged utterance, dedup across ticks

let _terminalLogVisible = localStorage.getItem(TERMINAL_LOG_VISIBLE_KEY) === "1";

const terminalLogPanel      = document.getElementById("terminalLogPanel");
const terminalLogToggleBtn  = document.getElementById("terminalLogToggleBtn");

function _applyTerminalLogVisibility(){
  if(terminalLogPanel) terminalLogPanel.classList.toggle("hidden", !_terminalLogVisible);
}
_applyTerminalLogVisibility();

if(terminalLogToggleBtn){
  terminalLogToggleBtn.addEventListener("click", () => {
    _terminalLogVisible = !_terminalLogVisible;
    localStorage.setItem(TERMINAL_LOG_VISIBLE_KEY, _terminalLogVisible ? "1" : "0");
    _applyTerminalLogVisibility();
  });
}

// =========================================================
// INSPECTOR VISIBILITY
// Same show/hide-plus-remember-it pattern as the outliner/timeline/
// terminal log toggles above.
// =========================================================

const INSPECTOR_VISIBLE_KEY = "holosims_inspector_visible";
let _inspectorVisible = localStorage.getItem(INSPECTOR_VISIBLE_KEY) !== "0";

const viewerInspectorEl  = document.getElementById("viewerInspector");
const inspectorToggleBtn = document.getElementById("inspectorToggleBtn");

function _applyInspectorVisibility(){
  // Per the user's explicit ask: hidden whenever nothing is selected,
  // regardless of the manual show/hide toggle's own state -- the manual
  // toggle only matters once something IS actually selected again.
  if(viewerInspectorEl) viewerInspectorEl.classList.toggle("hidden", !_inspectorVisible || !_somethingSelected);
}
_applyInspectorVisibility();

if(inspectorToggleBtn){
  inspectorToggleBtn.addEventListener("click", () => {
    _inspectorVisible = !_inspectorVisible;
    localStorage.setItem(INSPECTOR_VISIBLE_KEY, _inspectorVisible ? "1" : "0");
    _applyInspectorVisibility();
  });
}

function _terminalLogTimeLabel(){
  if(!_lastCalendar || _lastCalendarWorldTick == null || _worldState.tick == null) return "--:--";
  const proj = _projectCalendarForward(_lastCalendar, _worldState.tick - _lastCalendarWorldTick);
  if(!proj) return "--:--";
  const ampmHour = ((proj.hour % 12) || 12);
  const ampm = proj.hour < 12 ? "AM" : "PM";
  return `${ampmHour}:${String(proj.minute).padStart(2, "0")} ${ampm}`;
}

function terminalLog(kind, characterName, text){
  if(!terminalLogPanel || !text) return;

  const wasAtBottom = terminalLogPanel.scrollTop + terminalLogPanel.clientHeight
    >= terminalLogPanel.scrollHeight - 4;

  const entry = document.createElement("div");
  entry.className = `terminalLogEntry ${kind}`;

  const time = document.createElement("span");
  time.className = "terminalLogTime";
  time.textContent = `[${_terminalLogTimeLabel()}]`;
  entry.appendChild(time);

  const name = document.createElement("span");
  name.className = "terminalLogName";
  name.textContent = kind === "thought" ? `${characterName} (thought):` : `${characterName}:`;
  entry.appendChild(name);

  const text_ = document.createElement("span");
  text_.className = "terminalLogText";
  text_.textContent = kind === "said" ? `"${text}"` : text;
  entry.appendChild(text_);

  terminalLogPanel.appendChild(entry);

  while(terminalLogPanel.children.length > TERMINAL_LOG_MAX_ENTRIES){
    terminalLogPanel.removeChild(terminalLogPanel.firstChild);
  }

  // Only auto-scroll if the user was already at (or near) the bottom --
  // otherwise a scroll-up-to-read-history gets yanked back down every
  // time a new line arrives, which this feature explicitly exists to
  // let the user do ("keep history so I can scroll up").
  if(wasAtBottom) terminalLogPanel.scrollTop = terminalLogPanel.scrollHeight;
}

// Deliberately independent of updateThoughtBubbles()'s own dedup/timer
// logic -- that function early-returns entirely when the debug 3D
// thought-bubble overlay is switched off (_debugSettings.showThoughtBubbles),
// but the terminal log is meant to keep a real history regardless of
// whether that debug overlay happens to be on. Own dedup tracker so a
// thought that's still the same across many ticks isn't re-logged.
const _lastLoggedThought = {};   // id -> last logged c.last_thought

function _logCharacterEvents(state){
  for(const [id, c] of Object.entries(state.characters || {})){
    const thought = c.last_thought?.trim?.();
    if(!thought) continue;
    // Same reload-seeds-as-fresh bug as the speech tracker above: seed
    // silently on first sight of a character rather than logging their
    // already-existing (possibly long-stale) last_thought as if it just
    // happened.
    const seenBefore = Object.prototype.hasOwnProperty.call(_lastLoggedThought, id);
    if(thought !== _lastLoggedThought[id]){
      _lastLoggedThought[id] = thought;
      if(seenBefore) terminalLog("thought", c.name || id, thought);
    }
  }
}

function _ticksAgoLabel(ticks){
  // 1 tick == 1 nominal sim-second (see core/tick_schedule.py).
  if(ticks < 60) return `${Math.max(0, Math.round(ticks))}s ago`;
  const mins = ticks / 60;
  if(mins < 60) return `${Math.round(mins)}m ago`;
  const hours = mins / 60;
  if(hours < 24) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

async function fetchEvents(){
  if(!eventTimelineEl) return;
  try{
    const res = await fetch("/api/events?sim_id=default&limit=50");
    const data = await res.json();
    if(data.ok) renderEventTimeline(data);
  } catch(e){
    // Auxiliary panel -- a failed poll just leaves the last render in place.
  }
}

function renderEventTimeline(data){
  const events  = data.events || [];
  const nowTick = data.tick || 0;

  eventTimelinePointsEl.innerHTML = "";

  if(events.length === 0){
    eventTimelineLabelLeftEl.textContent = "no events yet";
    return;
  }

  const minTick = Math.min(...events.map(e => e.tick));
  const span = Math.max(1, nowTick - minTick);

  // Real time-scaled axis: position by actual elapsed ticks, not just
  // "Nth most recent" order. Points landing within ~1.5% of each other
  // (e.g. several events in the same handful of ticks) get bucketed into
  // one cluster marker rather than overlapping illegibly -- hover shows
  // every event in the cluster.
  const positioned = events
    .map(e => ({ event: e, pct: ((e.tick - minTick) / span) * 100 }))
    .sort((a, b) => a.pct - b.pct);

  const clusters = [];
  for(const p of positioned){
    const last = clusters[clusters.length - 1];
    if(last && (p.pct - last.pct) < 1.5){
      last.items.push(p.event);
    } else {
      clusters.push({ pct: p.pct, items: [p.event] });
    }
  }

  for(const cluster of clusters){
    const dot = document.createElement("div");
    dot.className = "eventTimelinePoint" + (cluster.items.length > 1 ? " eventTimelinePointCluster" : "");
    dot.style.left = `${cluster.pct}%`;
    dot.addEventListener("mouseenter", (e) => _showTimelineTooltip(e, cluster.items, nowTick));
    dot.addEventListener("mousemove", _positionTimelineTooltip);
    dot.addEventListener("mouseleave", _hideTimelineTooltip);
    dot.addEventListener("click", () => {
      _hideTimelineTooltip();
      openEventModal(cluster.items, nowTick);
    });
    eventTimelinePointsEl.appendChild(dot);
  }

  eventTimelineLabelLeftEl.textContent = _ticksAgoLabel(nowTick - minTick);
}

function _showTimelineTooltip(e, items, nowTick){
  if(!eventTimelineTooltipEl) return;
  eventTimelineTooltipEl.innerHTML = "";
  for(const ev of items){
    const row = document.createElement("div");
    row.className = "eventTimelineTooltipRow";

    const title = document.createElement("div");
    title.className = "eventTimelineTooltipTitle";
    title.textContent = ev.title || ev.type || "Event";
    row.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "eventTimelineTooltipMeta";
    meta.textContent = _ticksAgoLabel(nowTick - ev.tick);
    row.appendChild(meta);

    const summary = document.createElement("div");
    summary.textContent = ev.summary || "";
    row.appendChild(summary);

    eventTimelineTooltipEl.appendChild(row);
  }
  eventTimelineTooltipEl.style.display = "block";
  _positionTimelineTooltip(e);
}

function _positionTimelineTooltip(e){
  if(!eventTimelineTooltipEl) return;
  eventTimelineTooltipEl.style.left = `${e.clientX + 12}px`;
  eventTimelineTooltipEl.style.top  = `${e.clientY + 12}px`;
}

function _hideTimelineTooltip(){
  if(eventTimelineTooltipEl) eventTimelineTooltipEl.style.display = "none";
}

// Click-through detail view for the hover tooltip above -- same event
// data (title/type/tick/summary from api/events.py), just persistent and
// readable instead of disappearing on mouseleave. Reuses the shared
// modal infrastructure (openModal/closeModal, see the mailbox household
// modal) rather than inventing a second popup mechanism.
function openEventModal(items, nowTick){
  document.getElementById("eventModalTitle").textContent =
    items.length > 1 ? `${items.length} Events` : (items[0].title || items[0].type || "Event");

  const body = document.getElementById("eventModalBody");
  body.innerHTML = "";
  for(const ev of items){
    const row = document.createElement("div");
    row.className = "eventModalRow";

    const title = document.createElement("div");
    title.className = "eventModalRowTitle";
    title.textContent = ev.title || ev.type || "Event";
    row.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "eventModalRowMeta";
    meta.textContent = [ev.type, _ticksAgoLabel(nowTick - ev.tick)].filter(Boolean).join(" · ");
    row.appendChild(meta);

    const summary = document.createElement("div");
    summary.className = "eventModalRowSummary";
    summary.textContent = ev.summary || "(no details)";
    row.appendChild(summary);

    body.appendChild(row);
  }

  openModal("modal-event");
}

fetchEvents();
setInterval(fetchEvents, 5000);

// =========================================================
// OUTLINER SIDEBAR
// Blender-outliner-style collapsible tree: Households -> Characters.
// Joins GET /household/list (id/name/member_count) with the extended
// GET /household/characters (id/name/household_id + off-grid/status
// fields) client-side -- see api/household.py.
// =========================================================

const OUTLINER_VISIBLE_KEY = "holosims_outliner_visible";
let _outlinerVisible = localStorage.getItem(OUTLINER_VISIBLE_KEY) !== "0";
const _outlinerCollapsedGroups = new Set();
let _outlinerSearchTerm = "";

const outlinerSidebarEl    = document.getElementById("outlinerSidebar");
const outlinerToggleBtn    = document.getElementById("outlinerToggleBtn");
const outlinerSearchEl     = document.getElementById("outlinerSearch");
const outlinerTreeEl       = document.getElementById("outlinerTree");

function _applyOutlinerLayout(){
  if(!outlinerSidebarEl) return;
  outlinerSidebarEl.style.display = _outlinerVisible ? "block" : "none";
  // Sits below the top icon row, and below the event timeline bar too
  // when it's showing, so the two panels never overlap.
  outlinerSidebarEl.style.top = (_timelineVisible ? 110 : 54) + "px";
}
_applyOutlinerLayout();

if(outlinerToggleBtn){
  outlinerToggleBtn.addEventListener("click", () => {
    _outlinerVisible = !_outlinerVisible;
    localStorage.setItem(OUTLINER_VISIBLE_KEY, _outlinerVisible ? "1" : "0");
    _applyOutlinerLayout();
  });
}

if(timelineToggleBtn){
  timelineToggleBtn.addEventListener("click", _applyOutlinerLayout);
}

if(outlinerSearchEl){
  outlinerSearchEl.addEventListener("input", () => {
    _outlinerSearchTerm = outlinerSearchEl.value.trim().toLowerCase();
    renderOutliner(_outlinerLastData);
  });
}

// Per the user's explicit ask: selecting a character (by ANY method --
// clicking their 3D model, or the outliner list itself) should highlight
// their row in the outliner. Each row now carries data-character-id
// (see its creation above) so this can find it directly regardless of
// how the selection happened, rather than only the outliner's own click
// handler knowing to toggle its own class.
function _syncOutlinerHighlight(){
  for(const row of document.querySelectorAll(".outlinerRow")){
    row.classList.toggle("selected", row.dataset.characterId === selectedCharacterId);
  }
}

// Mirrors backend/systems/offgrid.py's _UNCAPPED_DURATION_REASONS long-
// stay subset -- a raw minutes countdown reads as meaningless/unreadable
// at day-plus scale, so these show "next update in N days" instead,
// reading the real _next_long_stay_checkin_tick field directly rather
// than re-deriving the 30-day schedule client-side.
const LONG_STAY_REASONS = new Set(["jail", "cps_care", "held_pending_trial", "temporary_separation"]);

function _outlinerStatus(c, tick){
  if(c.alive === false) return { text: "dead", cls: "dead" };
  if(c.off_grid){
    if(LONG_STAY_REASONS.has(c.off_grid_reason)){
      const reason = c.off_grid_reason.replace(/_/g, " ");
      const nextCheckin = c._next_long_stay_checkin_tick;
      const daysLeft = nextCheckin != null ? Math.max(0, Math.ceil((nextCheckin - tick) / 86400)) : null;
      const update = daysLeft != null ? `next update in ${daysLeft}d` : "away";
      return { text: `${reason} — ${update}`, cls: "longstay" };
    }
    const remain = (c.return_tick || tick) - tick;
    const backIn = remain > 0 ? `back in ~${Math.max(1, Math.round(remain / 60))}m` : "due back";
    const reason = c.off_grid_reason ? c.off_grid_reason.replace(/_/g, " ") : "off-grid";
    return { text: `${reason} — ${backIn}`, cls: "offgrid" };
  }
  if(c.travel_state) return { text: "traveling", cls: "traveling" };
  return { text: "home", cls: "" };
}

let _outlinerLastData = null;

async function fetchOutliner(){
  if(!outlinerSidebarEl) return;
  try{
    const [householdsRes, charsRes] = await Promise.all([
      fetch("/api/household/list?sim_id=default"),
      fetch("/api/household/characters?sim_id=default"),
    ]);
    const householdsData = await householdsRes.json();
    const charsData = await charsRes.json();
    if(householdsData.ok && charsData.ok){
      _outlinerLastData = {
        households: householdsData.households || [],
        characters: charsData.characters || [],
        tick: charsData.tick || 0,
      };
      renderOutliner(_outlinerLastData);
    }
  } catch(e){
    // Auxiliary panel -- a failed poll just leaves the last render in place.
  }
}

function renderOutliner(data){
  if(!outlinerTreeEl || !data) return;
  outlinerTreeEl.innerHTML = "";

  const term = _outlinerSearchTerm;
  const groups = new Map();
  for(const h of data.households) groups.set(h.id, { id: h.id, name: h.name, members: [] });
  const noHousehold = { id: null, name: "No Household", members: [] };

  for(const c of data.characters){
    const g = c.household_id ? groups.get(c.household_id) : null;
    (g || noHousehold).members.push(c);
  }

  const allGroups = [...groups.values(), noHousehold].filter(g => g.members.length > 0);

  let anyRendered = false;
  for(const g of allGroups){
    const nameMatches = g.name.toLowerCase().includes(term);
    const filteredMembers = term && !nameMatches
      ? g.members.filter(c => (c.name || "").toLowerCase().includes(term))
      : g.members;
    if(term && filteredMembers.length === 0) continue;

    anyRendered = true;
    const groupEl = document.createElement("div");
    groupEl.className = "outlinerGroup";

    const header = document.createElement("div");
    header.className = "outlinerGroupHeader";
    const collapsed = _outlinerCollapsedGroups.has(g.id) && !term;
    header.textContent = `${collapsed ? "▸" : "▾"} ${g.name} `;
    const count = document.createElement("span");
    count.className = "outlinerGroupCount";
    count.textContent = `(${filteredMembers.length})`;
    header.appendChild(count);
    header.addEventListener("click", () => {
      if(_outlinerCollapsedGroups.has(g.id)) _outlinerCollapsedGroups.delete(g.id);
      else _outlinerCollapsedGroups.add(g.id);
      renderOutliner(_outlinerLastData);
    });
    groupEl.appendChild(header);

    const membersEl = document.createElement("div");
    membersEl.className = "outlinerMembers" + (collapsed ? " collapsed" : "");
    for(const c of filteredMembers){
      const row = document.createElement("div");
      row.className = "outlinerRow";
      row.dataset.characterId = c.id;
      if(c.id === selectedCharacterId) row.classList.add("selected");

      const status = _outlinerStatus(c, data.tick);

      const name = document.createElement("span");
      name.className = "outlinerRowName" + (status.cls === "longstay" ? " outlinerRowNameAway" : "");
      name.textContent = c.name || c.id;
      row.appendChild(name);

      const statusEl = document.createElement("span");
      statusEl.className = "outlinerRowStatus" + (status.cls ? " " + status.cls : "");
      statusEl.textContent = status.text;
      row.appendChild(statusEl);

      row.addEventListener("click", () => {
        // Same selection path a 3D-viewport click takes (see the
        // pointerdown handler above) -- inspector + perception overlay +
        // LLM log all key off selectedCharacterId, not off anything
        // outliner-local.
        if(selectedCharacterId !== c.id) _perceptionRanges = null;
        selectedCharacterId = c.id;
        _somethingSelected = true;
        _applyInspectorVisibility();
        _setNonStatusTabsVisible(true);
        renderCharacterInspector(c.id);
        showCharacterLLMLog(c.id);
        _syncOutlinerHighlight();

        // Off-grid characters have no loaded mesh to frame a camera on --
        // x/y here is still their real last-known world position (from
        // GET /household/characters), so jumping the camera there is
        // still useful: it's where they'll reappear when they return.
        if(c.x != null && c.y != null) focusCameraOn(c.x, c.y);
      });

      membersEl.appendChild(row);
    }
    groupEl.appendChild(membersEl);
    outlinerTreeEl.appendChild(groupEl);
  }

  if(!anyRendered){
    const empty = document.createElement("div");
    empty.className = "outlinerEmpty";
    empty.textContent = term ? "No matches." : "No households or characters yet.";
    outlinerTreeEl.appendChild(empty);
  }
}

fetchOutliner();
setInterval(fetchOutliner, 5000);

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

// Pulsing ground ring under whichever character is currently selected --
// so it's obvious at a glance which one the Inspector/Director panel is
// pointed at, even in a crowd. Re-parents onto sims[selectedCharacterId]
// (rather than tracking world x/y itself) so it automatically follows
// walking/rotation with zero extra bookkeeping here.
function _ensureSelectionRing(){
  if (_selectionRing) return _selectionRing;
  const geo = new THREE.RingGeometry(0.55, 0.75, 32);
  const mat = new THREE.MeshBasicMaterial({
    color: 0xffe066,
    transparent: true,
    opacity: 0.9,
    side: THREE.DoubleSide,
    depthTest: false,   // stays visible even when standing behind a wall/prop
  });
  const ring = new THREE.Mesh(geo, mat);
  ring.rotation.x = -Math.PI / 2;   // lie flat on the ground
  ring.position.y = 0.04;           // just above the floor, avoids z-fighting
  ring.renderOrder = 999;
  ring.userData.ignoreRaycast = true;   // never itself intercept selection clicks
  _selectionRing = ring;
  return ring;
}

function updateSelectionOverlay(elapsedSeconds){
  const ring = _ensureSelectionRing();
  const targetSim = selectedCharacterId ? sims[selectedCharacterId] : null;

  if (!targetSim) {
    if (ring.parent) ring.parent.remove(ring);
    _selectionRingParent = null;
    return;
  }

  if (_selectionRingParent !== targetSim) {
    if (ring.parent) ring.parent.remove(ring);
    targetSim.add(ring);
    _selectionRingParent = targetSim;
  }

  // Gentle pulse so it reads as "selected" rather than a static decal.
  // (No counter-rotation needed against the parent's facing -- the ring's
  // own local X-rotation already lies it flat with its normal along the
  // parent's Y axis, and the parent only ever rotates around that same Y
  // axis to face a direction, which spins a rotationally-symmetric ring
  // around its own normal -- a no-op visually.)
  const pulse = 1 + 0.12 * Math.sin(elapsedSeconds * 3);
  ring.scale.set(pulse, pulse, 1);
}

let _animClockSeconds = 0;

function animate() {
  // renderer.setAnimationLoop() (below) replaces the old
  // requestAnimationFrame(animate) self-scheduling -- required for WebXR
  // (a plain requestAnimationFrame doesn't run at headset framerate or
  // carry XRFrame pose data), and functionally identical to the old
  // rAF-driven loop whenever no XR session is active.
  const presenting = renderer.xr.isPresenting;
  if (!presenting) controls.update();
  const delta = 0.016;
  _animClockSeconds += delta;
  updateSelectionOverlay(_animClockSeconds);
  updateXRFrame();

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

  const activeCamera = presenting ? xrCamera : camera;
  renderer.render(scene, activeCamera);
  // CSS2DRenderer (speech bubbles) is a DOM overlay, not part of WebGL's
  // stereoscopic output -- it can't render correctly into a headset, so
  // it's skipped while presenting rather than drawing garbage over one eye.
  if (!presenting) cssRenderer.render(scene, activeCamera);
}

renderer.setAnimationLoop(animate);
