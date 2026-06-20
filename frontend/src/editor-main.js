import * as THREE from "three";
import { OrbitControls }
from "three/examples/jsm/controls/OrbitControls.js";

const WORLD_SIZE = 80;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x20242a);

const camera =
new THREE.PerspectiveCamera(
  60,
  window.innerWidth /
  window.innerHeight,
  0.1,
  1000
);

camera.position.set(20, 20, 20);

const renderer =
new THREE.WebGLRenderer({
  canvas: document.getElementById("c"),
  antialias: true
});

renderer.setSize(
  window.innerWidth,
  window.innerHeight
);

const controls =
new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.AmbientLight(0xffffff, 1));
scene.add(new THREE.GridHelper(WORLD_SIZE, WORLD_SIZE));

const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

let definitions = {
  tile_templates:      {},
  floorplan_templates: {},
  prop_templates:      {},
  character_templates: {}
};

const worldState = {
  floorplans:   [],
  world_tiles:  [],
  placed_props: []
};

let currentTool          = null;   // "paint_tile" | "place_floorplan" | "place_prop"
let currentWorldTileType = "grass";
let lastClickedTile      = null;   // { x, y } — used for character spawn

const placementState = {
  active:     false,
  mode:       null,       // "floorplan" | "prop"
  templateId: null,
  rotation:   0,
  preview:    null
};

//
// ===================================
// TILE STORAGE
// ===================================
//

const tileData    = new Map();
const tileIndexMap = new Map();

function key(x, y) { return `${x},${y}`; }

//
// ===================================
// GROUND PICKING PLANE
// ===================================
//

const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(WORLD_SIZE, WORLD_SIZE),
  new THREE.MeshBasicMaterial({ visible: false })
);
ground.rotation.x = -Math.PI / 2;
scene.add(ground);

//
// ===================================
// INSTANCED TILE MESH
// ===================================
//

const tileGeometry = new THREE.PlaneGeometry(1, 1);
tileGeometry.rotateX(-Math.PI / 2);

const tileMaterial = new THREE.MeshBasicMaterial({ vertexColors: true });

const TILE_COUNT = WORLD_SIZE * WORLD_SIZE;
const tileMesh   = new THREE.InstancedMesh(tileGeometry, tileMaterial, TILE_COUNT);
scene.add(tileMesh);

const dummy = new THREE.Object3D();
const color = new THREE.Color();

let instance = 0;

for (let x = 0; x < WORLD_SIZE; x++) {
  for (let y = 0; y < WORLD_SIZE; y++) {
    dummy.position.set(
      x + 0.5 - WORLD_SIZE / 2,
      0,
      y + 0.5 - WORLD_SIZE / 2
    );
    dummy.updateMatrix();
    tileMesh.setMatrixAt(instance, dummy.matrix);
    color.setHex(0x557799);
    tileMesh.setColorAt(instance, color);
    tileIndexMap.set(key(x, y), instance);
    instance++;
  }
}

tileMesh.instanceMatrix.needsUpdate = true;
tileMesh.instanceColor.needsUpdate  = true;

//
// ===================================
// SELECTION HIGHLIGHT
// ===================================
//

const selection = new THREE.Mesh(
  new THREE.PlaneGeometry(1.02, 1.02),
  new THREE.MeshBasicMaterial({ color: 0xffff00, wireframe: true })
);
selection.rotation.x = -Math.PI / 2;
selection.visible    = false;
scene.add(selection);

//
// ===================================
// TILE COLORS
// ===================================
//

const TILE_COLORS = {
  grass:    0x3f7a3f,
  road:     0x333333,
  sidewalk: 0xaaaaaa,
  park:     0x55aa55,
  water:    0x3377cc
};

//
// ===================================
// COORDINATE HELPERS
// ===================================
//

function worldToGrid(point) {
  return {
    x: Math.floor(point.x + WORLD_SIZE / 2),
    y: Math.floor(point.z + WORLD_SIZE / 2)
  };
}

function gridToWorld(x, y) {
  return {
    x: x + 0.5 - WORLD_SIZE / 2,
    z: y + 0.5 - WORLD_SIZE / 2
  };
}

//
// ===================================
// PAINT TILE
// ===================================
//

function tileColor(type) {
  const t = (type || "").toLowerCase();
  // 1. Check material_templates for an editor_color (dynamic, from definitions)
  const matBucket = definitions.material_templates || {};
  for (const bucket of Object.values(matBucket)) {
    const inner = bucket[t];
    if (inner && inner.editor_color) {
      return parseInt(inner.editor_color.replace("#", ""), 16);
    }
  }
  // 2. Fall back to hardcoded map
  return TILE_COLORS[t] || 0x557799;
}

function paintTile(x, y, type) {
  const t = (type || "").toLowerCase();
  const index = tileIndexMap.get(key(x, y));
  if (index == null) return;

  color.setHex(tileColor(t));
  tileMesh.setColorAt(index, color);
  tileMesh.instanceColor.needsUpdate = true;

  const existing = worldState.world_tiles.find(t => t.x === x && t.y === y);
  if (existing) {
    existing.type = t;
  } else {
    worldState.world_tiles.push({ x, y, type: t });
  }
}

//
// ===================================
// PICK TILE
// ===================================
//

function pickTile(event) {
  mouse.x =  (event.clientX / window.innerWidth)  * 2 - 1;
  mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  const hit = raycaster.intersectObject(ground)[0];
  if (!hit) return null;

  return worldToGrid(hit.point);
}

//
// ===================================
// POINTER DOWN
// ===================================
//

// Single click — select tile only
renderer.domElement.addEventListener("pointerdown", (event) => {
  const tile = pickTile(event);
  if (!tile) return;

  const world = gridToWorld(tile.x, tile.y);
  lastClickedTile = tile;
  selection.visible = true;
  selection.position.set(world.x, 0.03, world.z);

  document.getElementById("editorSelection").innerHTML = `
    <b>Tile</b><hr>
    Grid: ${tile.x}, ${tile.y}
  `;
});

// Double click — place / paint
renderer.domElement.addEventListener("dblclick", (event) => {
  const tile = pickTile(event);
  if (!tile) return;

  if (currentTool === "paint_tile") {
    paintTile(tile.x, tile.y, currentWorldTileType);
    setStatus(`Painted ${currentWorldTileType} @ ${tile.x}, ${tile.y}`);
    return;
  }

  if (placementState.active) {
    if (placementState.mode === "prop") {
      worldState.placed_props.push({
        id:       crypto.randomUUID(),
        template: placementState.templateId,
        x:        tile.x,
        y:        tile.y,
        rotation: placementState.rotation
      });
      document.getElementById("editorSelection").innerHTML = `
        <b>Placed prop</b><br>
        ${placementState.templateId}<br>
        @ ${tile.x}, ${tile.y}
      `;
      setStatus(`Placed prop: ${placementState.templateId} @ ${tile.x}, ${tile.y}`);
      return;
    }

    worldState.floorplans.push({
      id:       crypto.randomUUID(),
      template: placementState.templateId,
      x:        tile.x,
      y:        tile.y,
      rotation: placementState.rotation
    });
    document.getElementById("editorSelection").innerHTML = `
      <b>Placed floorplan</b><br>
      ${placementState.templateId}<br>
      @ ${tile.x}, ${tile.y}
    `;
    setStatus(`Placed floorplan: ${placementState.templateId} @ ${tile.x}, ${tile.y}`);
    return;
  }
});

//
// ===================================
// STATUS BAR
// ===================================
//

function setStatus(msg) {
  const bar = document.getElementById("statusBar");
  if (bar) bar.textContent = msg;
}

//
// ===================================
// TOOL BUTTONS
// ===================================
//

function setActiveTool(tool) {
  currentTool = tool;
  placementState.active = false;
  placementState.mode   = null;

  document.querySelectorAll(".toolButton[data-tool]").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tool === tool);
  });
}

//
// ===================================
// MODALS
// ===================================
//

window.closeModal = function(id) {
  document.getElementById(id).classList.remove("open");
};

function openModal(id) {
  document.getElementById(id).classList.add("open");
}

// Close modal when clicking overlay background
document.querySelectorAll(".modal-overlay").forEach(overlay => {
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.classList.remove("open");
  });
});

function buildModalList(listEl, items, onSelect) {
  listEl.innerHTML = "";
  const keys = Object.keys(items || {});
  if (!keys.length) {
    listEl.innerHTML = '<div class="modal-empty">No templates found</div>';
    return;
  }
  for (const id of keys) {
    const tmpl = items[id];
    const div  = document.createElement("div");
    div.className = "modal-item";
    div.innerHTML = `
      <div>${tmpl.display_name || id}</div>
      <div class="modal-item-id">${id}</div>
    `;
    div.onclick = () => onSelect(id, tmpl);
    listEl.appendChild(div);
  }
}

//
// Paint Tile button
//

document.getElementById("btn-paint_tile").onclick = () => {
  buildModalList(
    document.getElementById("list-paint_tile"),
    definitions.tile_templates,
    (id, tmpl) => {
      // definitions.tile_templates uses nested structure:
      // { "Grass": { "grass": { name, material, ... } } }
      // The outer key is the display name; we need the inner key for paintTile.
      const innerKey = (Object.keys(tmpl).find(k => typeof tmpl[k] === "object") || id).toLowerCase();
      currentWorldTileType = innerKey;
      setActiveTool("paint_tile");
      closeModal("modal-paint_tile");
      setStatus(`Paint tile: ${innerKey}`);
    }
  );
  openModal("modal-paint_tile");
};

//
// Place Floorplan button
//

document.getElementById("btn-place_floorplan").onclick = () => {
  buildModalList(
    document.getElementById("list-place_floorplan"),
    definitions.floorplan_templates,
    (id) => {
      placementState.templateId = id;
      placementState.mode       = "floorplan";
      placementState.active     = true;
      setActiveTool("place_floorplan");
      closeModal("modal-place_floorplan");
      setStatus(`