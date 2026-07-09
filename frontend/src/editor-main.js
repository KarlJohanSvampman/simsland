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

//
// ===================================
// TEXTURE LOADING
// ===================================
//

const textureLoader = new THREE.TextureLoader();
const textureCache   = new Map();

function getTexture(url) {
  if (textureCache.has(url)) return textureCache.get(url);
  const tex = textureLoader.load(url);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  if ("colorSpace" in tex) tex.colorSpace = THREE.SRGBColorSpace;
  textureCache.set(url, tex);
  return tex;
}

let definitions = {
  tile_templates:      {},
  floorplan_templates: {},
  prop_templates:      {},
  character_templates: {}
};

const worldState = {
  floorplans:    [],
  world_tiles:   [],
  placed_props:  [],
  wall_segments: []
};

let currentTool             = null;   // "paint_tile" | "place_floorplan" | "place_prop"
let currentWorldTileType    = "grass";
let currentWorldTileRotation = 0;
let lastClickedTile         = null;   // { x, y } — used for character spawn

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

const tileData      = new Map();
const tileRotations = new Map();
const tileIndexMap  = new Map();

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
// Base layer: a flat grey "unpainted ground" plane under every cell.
// Painted tiles get their own per-material textured InstancedMesh layered
// just above this, so each material can show its real texture instead of
// a flat color swatch.
//

const tileGeometry = new THREE.PlaneGeometry(1, 1);
tileGeometry.rotateX(-Math.PI / 2);

const TILE_COUNT = WORLD_SIZE * WORLD_SIZE;

const baseMaterial = new THREE.MeshBasicMaterial({ color: 0x557799 });
const baseMesh     = new THREE.InstancedMesh(tileGeometry, baseMaterial, TILE_COUNT);
scene.add(baseMesh);

const dummy = new THREE.Object3D();

let instance = 0;

for (let x = 0; x < WORLD_SIZE; x++) {
  for (let y = 0; y < WORLD_SIZE; y++) {
    dummy.position.set(
      x + 0.5 - WORLD_SIZE / 2,
      0,
      y + 0.5 - WORLD_SIZE / 2
    );
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    baseMesh.setMatrixAt(instance, dummy.matrix);
    tileIndexMap.set(key(x, y), instance);
    instance++;
  }
}

baseMesh.instanceMatrix.needsUpdate = true;

//
// ===================================
// PER-MATERIAL TILE TYPE MESHES
// ===================================
// One InstancedMesh per resolved material/color, all sharing the same
// TILE_COUNT-sized instance index scheme as tileIndexMap. Unused instances
// are scaled to 0 so they're invisible.
//

const tileTypeMeshes       = new Map(); // visualKey -> { mesh }
const tileVisualAssignment = new Map(); // "x,y" -> visualKey

function hideInstance(mesh, index) {
  dummy.position.set(0, 0, 0);
  dummy.rotation.set(0, 0, 0);
  dummy.scale.set(0, 0, 0);
  dummy.updateMatrix();
  mesh.setMatrixAt(index, dummy.matrix);
  dummy.scale.set(1, 1, 1);
}

function getOrCreateTileTypeMesh(visual) {
  let entry = tileTypeMeshes.get(visual.key);
  if (entry) return entry;

  const material = visual.textureUrl
    ? new THREE.MeshBasicMaterial({ map: getTexture(visual.textureUrl) })
    : new THREE.MeshBasicMaterial({ color: visual.color ?? 0x557799 });

  const mesh = new THREE.InstancedMesh(tileGeometry, material, TILE_COUNT);
  mesh.frustumCulled = false;

  for (let i = 0; i < TILE_COUNT; i++) {
    hideInstance(mesh, i);
  }
  mesh.instanceMatrix.needsUpdate = true;

  scene.add(mesh);
  entry = { mesh };
  tileTypeMeshes.set(visual.key, entry);
  return entry;
}

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
// PLACED PROP / FLOORPLAN MARKERS
// ===================================
// The editor doesn't load actual GLB models — these are simple placeholder
// markers so placed props/floorplans are actually visible in the scene.
//

const placedGroup = new THREE.Group();
scene.add(placedGroup);

// Schematic markers drawn over "corner"-kind tiles (e.g. sidewalk_corner) so
// their rotation is visible in the editor even though the underlying tile
// texture is the same flat material as the straight variant — see
// updateTileCornerMarker() near paintTile().
const tileCornerMarkerGroup = new THREE.Group();
scene.add(tileCornerMarkerGroup);
const tileCornerMarkers = new Map(); // "x,y" -> THREE.Group

function addPropMarker(entry) {
  const world = gridToWorld(entry.x, entry.y);
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(0.3, 0.35, 0.9, 12),
    new THREE.MeshBasicMaterial({ color: 0xe0a030 })
  );
  mesh.position.set(world.x, 0.45, world.z);
  mesh.userData = { type: "prop", id: entry.id, template: entry.template };
  placedGroup.add(mesh);
  return mesh;
}

function addFloorplanMarker(entry) {
  const world = gridToWorld(entry.x, entry.y);
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(0.96, 0.96),
    new THREE.MeshBasicMaterial({
      color:       0x4090e0,
      transparent: true,
      opacity:     0.55,
      side:        THREE.DoubleSide
    })
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set(world.x, 0.04, world.z);
  mesh.userData = { type: "floorplan", id: entry.id, template: entry.template };
  placedGroup.add(mesh);
  return mesh;
}

//
// ===================================
// WALL SEGMENTS
// ===================================
// A wall segment is more like a prop than a ground tile: a rectangular
// model (half a tile wide) snapped to the outer edge of the tile it's
// built on (north/east/south/west, cycled via rotation), textured from a
// wallpaper/paint material. "window" and "door" kinds reuse the same box
// with a small decal so they're distinguishable here.
//

// Sized to match main.js's real in-game walls (WALL_HEIGHT / WALL_THICKNESS):
// width spans the full tile edge (1 unit) so adjacent segments butt together
// with no gap, instead of floating as isolated half-width posts.
const WALL_SEGMENT_WIDTH     = 1;
const WALL_SEGMENT_HEIGHT    = 1.2;
const WALL_SEGMENT_THICKNESS = 0.1;

// Rotation snaps to one of the tile's 4 outer edges rather than free rotation —
// each 90° step picks the next side, and the wall is offset to sit right on
// that edge (like main.js's real floorplan walls), not floating in the middle.
const WALL_SIDES = ["north", "east", "south", "west"];

function wallSideFromRotation(rotation) {
  const steps = Math.round((((rotation % 360) + 360) % 360) / 90) % 4;
  return WALL_SIDES[steps];
}

// Corner pieces cover two adjacent sides at once (e.g. north+east), forming
// an L that meets exactly at the tile's corner since each arm already spans
// the full edge. Rotation cycles which corner of the tile it occupies.
const CORNER_SIDE_PAIRS = [
  ["north", "east"],
  ["east", "south"],
  ["south", "west"],
  ["west", "north"]
];

function cornerSidesFromRotation(rotation) {
  const steps = Math.round((((rotation % 360) + 360) % 360) / 90) % 4;
  return CORNER_SIDE_PAIRS[steps];
}

// Label used in status text — a single side for straight/window/door kinds,
// or the joined pair (e.g. "north-east") for corner kind.
function wallSideLabel(templateId, rotation) {
  const tmpl = (definitions.wall_segment_templates || {})[templateId] || {};
  if (tmpl.kind === "corner") return cornerSidesFromRotation(rotation).join("-");
  return wallSideFromRotation(rotation);
}

// Resolve a material id (from any template, not just tiles) to a texture
// or flat color — shared by wall segments here and reusable elsewhere.
function resolveMaterialVisual(materialId) {
  const material = materialId ? (definitions.material_templates || {})[materialId] : null;
  if (material && material.texture) return { textureUrl: material.texture, color: null };
  if (material && material.color)   return { textureUrl: null, color: parseInt(material.color.replace("#", ""), 16) };
  return { textureUrl: null, color: 0xdddddd };
}

// Shared positioning: offsets an object (mesh or group) from the tile
// center out to the given edge, matching gridToWorld's tile-center origin.
function positionOnWallSide(obj, side) {
  let px = 0;
  let pz = 0;
  if (side === "north") pz -= 0.5;
  if (side === "south") pz += 0.5;
  if (side === "west")  px -= 0.5;
  if (side === "east")  px += 0.5;
  obj.position.set(px, 0, pz);
}

// Proportions (fractions of the wall segment's own width/height) for the
// hollowed-out door and window openings — mirrors main.js's createDoorSegment
// / createWindowSegment, which use the same fractions in absolute units at
// the real in-game wall scale.
const DOOR_WIDTH_FRACTION         = 0.55;
const DOOR_TOP_HEIGHT_FRACTION    = 0.16;
const WINDOW_LOWER_FRACTION       = 0.32;
const WINDOW_UPPER_FRACTION       = 0.25;
const WINDOW_GLASS_WIDTH_FRACTION = 0.85;

// Door: an actual gap in the wall — left/right jambs plus a header above the
// opening, with nothing spanning the doorway itself.
function buildDoorSideMesh(side, horizontal, material) {
  const group = new THREE.Group();

  const doorWidth  = WALL_SEGMENT_WIDTH * DOOR_WIDTH_FRACTION;
  const jambWidth  = (WALL_SEGMENT_WIDTH - doorWidth) / 2;
  const topHeight  = WALL_SEGMENT_HEIGHT * DOOR_TOP_HEIGHT_FRACTION;

  const jambGeo = horizontal
    ? new THREE.BoxGeometry(jambWidth, WALL_SEGMENT_HEIGHT, WALL_SEGMENT_THICKNESS)
    : new THREE.BoxGeometry(WALL_SEGMENT_THICKNESS, WALL_SEGMENT_HEIGHT, jambWidth);

  const topGeo = horizontal
    ? new THREE.BoxGeometry(doorWidth, topHeight, WALL_SEGMENT_THICKNESS)
    : new THREE.BoxGeometry(WALL_SEGMENT_THICKNESS, topHeight, doorWidth);

  const left  = new THREE.Mesh(jambGeo, material);
  const right = new THREE.Mesh(jambGeo, material);
  const top   = new THREE.Mesh(topGeo, material);

  const jambOffset = WALL_SEGMENT_WIDTH / 2 - jambWidth / 2;
  if (horizontal) {
    left.position.x  = -jambOffset;
    right.position.x =  jambOffset;
  } else {
    left.position.z  = -jambOffset;
    right.position.z =  jambOffset;
  }
  top.position.y = WALL_SEGMENT_HEIGHT / 2 - topHeight / 2;

  group.add(left, right, top);
  positionOnWallSide(group, side);
  return group;
}

// Window: solid sill and header around a hollow band filled only with a
// translucent "glass" pane, instead of an opaque box with a decal on top.
function buildWindowSideMesh(side, horizontal, material) {
  const group = new THREE.Group();

  const lowerHeight = WALL_SEGMENT_HEIGHT * WINDOW_LOWER_FRACTION;
  const upperHeight = WALL_SEGMENT_HEIGHT * WINDOW_UPPER_FRACTION;
  const glassHeight = WALL_SEGMENT_HEIGHT - lowerHeight - upperHeight;
  const glassWidth  = WALL_SEGMENT_WIDTH * WINDOW_GLASS_WIDTH_FRACTION;

  const lowerGeo = horizontal
    ? new THREE.BoxGeometry(WALL_SEGMENT_WIDTH, lowerHeight, WALL_SEGMENT_THICKNESS)
    : new THREE.BoxGeometry(WALL_SEGMENT_THICKNESS, lowerHeight, WALL_SEGMENT_WIDTH);

  const upperGeo = horizontal
    ? new THREE.BoxGeometry(WALL_SEGMENT_WIDTH, upperHeight, WALL_SEGMENT_THICKNESS)
    : new THREE.BoxGeometry(WALL_SEGMENT_THICKNESS, upperHeight, WALL_SEGMENT_WIDTH);

  const glassGeo = horizontal
    ? new THREE.BoxGeometry(glassWidth, glassHeight, WALL_SEGMENT_THICKNESS / 2)
    : new THREE.BoxGeometry(WALL_SEGMENT_THICKNESS / 2, glassHeight, glassWidth);

  const glassMaterial = new THREE.MeshBasicMaterial({
    color:       0x88ccff,
    transparent: true,
    opacity:     0.35,
    side:        THREE.DoubleSide
  });

  const lower = new THREE.Mesh(lowerGeo, material);
  const upper = new THREE.Mesh(upperGeo, material);
  const glass = new THREE.Mesh(glassGeo, glassMaterial);

  lower.position.y = -WALL_SEGMENT_HEIGHT / 2 + lowerHeight / 2;
  upper.position.y =  WALL_SEGMENT_HEIGHT / 2 - upperHeight / 2;
  glass.position.y = (lowerHeight - upperHeight) / 2;

  group.add(lower, upper, glass);
  positionOnWallSide(group, side);
  return group;
}

// Builds one full-edge wall piece for a given side, positioned relative to
// the tile center (parent group is what gets moved to the tile's world
// position). Straight/corner kinds get a plain solid box; door/window kinds
// get an actual hollowed-out opening instead of a decal on a solid box.
function buildWallSideMesh(side, material, kind) {
  const horizontal = side === "north" || side === "south";

  if (kind === "door")   return buildDoorSideMesh(side, horizontal, material);
  if (kind === "window") return buildWindowSideMesh(side, horizontal, material);

  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(
      horizontal ? WALL_SEGMENT_WIDTH     : WALL_SEGMENT_THICKNESS,
      WALL_SEGMENT_HEIGHT,
      horizontal ? WALL_SEGMENT_THICKNESS : WALL_SEGMENT_WIDTH
    ),
    material
  );
  positionOnWallSide(mesh, side);

  return mesh;
}

function addWallSegmentMarker(entry) {
  const tmpl   = (definitions.wall_segment_templates || {})[entry.template] || {};
  const visual = resolveMaterialVisual(tmpl.material);

  const material = visual.textureUrl
    ? new THREE.MeshBasicMaterial({ map: getTexture(visual.textureUrl) })
    : new THREE.MeshBasicMaterial({ color: visual.color ?? 0xdddddd });

  const world = gridToWorld(entry.x, entry.y);
  const group = new THREE.Group();
  group.position.set(world.x, WALL_SEGMENT_HEIGHT / 2, world.z);

  let side;
  if (tmpl.kind === "corner") {
    const sides = cornerSidesFromRotation(entry.rotation || 0);
    for (const s of sides) group.add(buildWallSideMesh(s, material, "corner"));
    side = sides.join("-");
  } else {
    side = wallSideFromRotation(entry.rotation || 0);
    group.add(buildWallSideMesh(side, material, tmpl.kind));
  }

  group.userData = { type: "wall_segment", id: entry.id, template: entry.template, side };

  placedGroup.add(group);
  return group;
}

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
  water:    0x3377cc,
  wall:     0x552222
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

// Resolve a tile type to its visual: a real texture (via tile_templates[type].material
// -> material_templates[materialId].texture) when available, otherwise a flat color.
function resolveTileVisual(type) {
  const t = (type || "").toLowerCase();

  const tileTpl    = (definitions.tile_templates || {})[t];
  const materialId = tileTpl && tileTpl.material;
  const material    = materialId ? (definitions.material_templates || {})[materialId] : null;

  if (material && material.texture) {
    return { key: materialId, textureUrl: material.texture, color: null };
  }
  if (material && material.color) {
    return { key: materialId, textureUrl: null, color: parseInt(material.color.replace("#", ""), 16) };
  }
  return { key: `flat:${t}`, textureUrl: null, color: TILE_COLORS[t] || 0x557799 };
}

function paintTile(x, y, type, rotation = 0) {
  const t = (type || "").toLowerCase();
  const r = ((rotation % 360) + 360) % 360;
  const gridKey = key(x, y);
  const index   = tileIndexMap.get(gridKey);
  if (index == null) return;

  const visual = resolveTileVisual(t);
  const { mesh } = getOrCreateTileTypeMesh(visual);

  // If this cell previously showed a different material/color, hide it there.
  const prevKey = tileVisualAssignment.get(gridKey);
  if (prevKey && prevKey !== visual.key) {
    const prevEntry = tileTypeMeshes.get(prevKey);
    if (prevEntry) {
      hideInstance(prevEntry.mesh, index);
      prevEntry.mesh.instanceMatrix.needsUpdate = true;
    }
  }

  const world = gridToWorld(x, y);
  dummy.position.set(world.x, 0.02, world.z);
  dummy.rotation.set(0, THREE.MathUtils.degToRad(r), 0);
  dummy.scale.set(1, 1, 1);
  dummy.updateMatrix();
  mesh.setMatrixAt(index, dummy.matrix);
  mesh.instanceMatrix.needsUpdate = true;
  dummy.rotation.set(0, 0, 0); // dummy is shared — leave it neutral for other callers

  tileVisualAssignment.set(gridKey, visual.key);
  tileData.set(gridKey, t);
  tileRotations.set(gridKey, r);

  const existing = worldState.world_tiles.find(wt => wt.x === x && wt.y === y);
  if (existing) {
    existing.type     = t;
    existing.rotation = r;
  } else {
    worldState.world_tiles.push({ x, y, type: t, rotation: r });
  }

  updateTileCornerMarker(x, y, t, r);
}

// Draws (or clears) the schematic corner marker for a tile. Only tile
// templates with kind "corner" (e.g. sidewalk_corner) get one — it's the
// only visual sign of orientation, since the tile texture itself doesn't
// change per rotation. Reuses cornerSidesFromRotation()/WALL_SIDES logic
// defined below in the WALL SEGMENTS section (hoisted, safe to call here).
function updateTileCornerMarker(x, y, type, rotation) {
  const gridKey  = key(x, y);
  const existing = tileCornerMarkers.get(gridKey);
  if (existing) {
    tileCornerMarkerGroup.remove(existing);
    tileCornerMarkers.delete(gridKey);
  }

  const tmpl = (definitions.tile_templates || {})[type] || {};
  if (tmpl.kind !== "corner") return;

  const world = gridToWorld(x, y);
  const group = new THREE.Group();
  group.position.set(world.x, 0.03, world.z);

  const material = new THREE.MeshBasicMaterial({ color: 0xffe066 });
  for (const side of cornerSidesFromRotation(rotation)) {
    const horizontal = side === "north" || side === "south";
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(
        horizontal ? 0.9  : 0.06,
        0.02,
        horizontal ? 0.06 : 0.9
      ),
      material
    );
    let px = 0;
    let pz = 0;
    if (side === "north") pz = -0.47;
    if (side === "south") pz =  0.47;
    if (side === "west")  px = -0.47;
    if (side === "east")  px =  0.47;
    mesh.position.set(px, 0, pz);
    group.add(mesh);
  }

  tileCornerMarkerGroup.add(group);
  tileCornerMarkers.set(gridKey, group);
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

  const tileType = tileData.get(key(tile.x, tile.y)) || "(unpainted)";
  const tileRot  = tileRotations.get(key(tile.x, tile.y)) || 0;

  document.getElementById("editorSelection").innerHTML = `
    <b>Tile</b><hr>
    Grid: ${tile.x}, ${tile.y}<br>
    Type: ${tileType}<br>
    Rotation: ${tileRot}°
  `;
});

//
// Commit a prop/floorplan placement at a given tile — shared by the
// double-click handler and the explicit "Place Here" button.
//
function commitPlacement(tile) {
  if (!placementState.active || !tile) return;

  if (placementState.mode === "prop") {
    const entry = {
      id:       crypto.randomUUID(),
      template: placementState.templateId,
      x:        tile.x,
      y:        tile.y,
      rotation: placementState.rotation
    };
    worldState.placed_props.push(entry);
    addPropMarker(entry);
    document.getElementById("editorSelection").innerHTML = `
      <b>Placed prop</b><br>
      ${entry.template}<br>
      @ ${entry.x}, ${entry.y}
    `;
    setStatus(`Placed prop: ${entry.template} @ ${entry.x}, ${entry.y}`);
    return;
  }

  if (placementState.mode === "floorplan") {
    const entry = {
      id:       crypto.randomUUID(),
      template: placementState.templateId,
      x:        tile.x,
      y:        tile.y,
      rotation: placementState.rotation
    };
    worldState.floorplans.push(entry);
    addFloorplanMarker(entry);
    document.getElementById("editorSelection").innerHTML = `
      <b>Placed floorplan</b><br>
      ${entry.template}<br>
      @ ${entry.x}, ${entry.y}
    `;
    setStatus(`Placed floorplan: ${entry.template} @ ${entry.x}, ${entry.y}`);
    return;
  }

  if (placementState.mode === "wall_segment") {
    const entry = {
      id:       crypto.randomUUID(),
      template: placementState.templateId,
      x:        tile.x,
      y:        tile.y,
      rotation: placementState.rotation
    };
    worldState.wall_segments.push(entry);
    addWallSegmentMarker(entry);
    const side = wallSideLabel(entry.template, entry.rotation);
    document.getElementById("editorSelection").innerHTML = `
      <b>Placed wall segment</b><br>
      ${entry.template}<br>
      @ ${entry.x}, ${entry.y} (${side} side)
    `;
    setStatus(`Placed wall segment: ${entry.template} @ ${entry.x}, ${entry.y} (${side} side)`);
    return;
  }
}

// Double click — place / paint
renderer.domElement.addEventListener("dblclick", (event) => {
  const tile = pickTile(event);
  if (!tile) return;

  if (currentTool === "paint_tile") {
    paintTile(tile.x, tile.y, currentWorldTileType, currentWorldTileRotation);
    setStatus(`Painted ${currentWorldTileType} @ ${tile.x}, ${tile.y} (${currentWorldTileRotation}°)`);
    return;
  }

  if (placementState.active) {
    commitPlacement(tile);
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

  updatePlaceButton();
  updatePlaceTileButton();
}

//
// "Place Tile" button — shows while the paint_tile tool is active, lets you
// paint the last-selected tile immediately without needing a double-click.
//
function updatePlaceTileButton() {
  const btn = document.getElementById("btn-place_tile");
  if (!btn) return;
  btn.style.display = currentTool === "paint_tile" ? "block" : "none";
}

document.getElementById("btn-place_tile").onclick = () => {
  if (currentTool !== "paint_tile") return;
  if (!lastClickedTile) {
    setStatus("Click a tile first, then press Place Tile");
    return;
  }
  paintTile(lastClickedTile.x, lastClickedTile.y, currentWorldTileType, currentWorldTileRotation);
  setStatus(`Painted ${currentWorldTileType} @ ${lastClickedTile.x}, ${lastClickedTile.y} (${currentWorldTileRotation}°)`);
};

//
// "Place Here" button — shows whenever a floorplan/prop placement is armed,
// lets you commit the placement on the last-selected tile without needing
// a double-click.
//
function updatePlaceButton() {
  const btn = document.getElementById("btn-place_here");
  if (!btn) return;
  btn.style.display = placementState.active ? "block" : "none";
  updateRotateButton();
}

//
// Rotate control — rotates the currently-armed placement (floorplan, prop,
// or wall segment) in 90° steps before it's committed. Visually meaningful
// for wall segments right now, since props/floorplans are placeholder
// markers with no directional shape yet.
//

function updateRotateButton() {
  const btn = document.getElementById("btn-rotate");
  if (!btn) return;
  btn.style.display = (placementState.active || currentTool === "paint_tile") ? "block" : "none";
}

function rotatePlacement() {
  if (currentTool === "paint_tile") {
    currentWorldTileRotation = (currentWorldTileRotation + 90) % 360;
    setStatus(`Tile rotation: ${currentWorldTileRotation}°`);
    return;
  }
  if (!placementState.active) return;
  placementState.rotation = (placementState.rotation + 90) % 360;
  if (placementState.mode === "wall_segment") {
    setStatus(`Wall side: ${wallSideLabel(placementState.templateId, placementState.rotation)}`);
  } else {
    setStatus(`Rotation: ${placementState.rotation}°`);
  }
}

document.getElementById("btn-rotate").onclick = rotatePlacement;

window.addEventListener("keydown", (e) => {
  if ((e.key === "r" || e.key === "R") && (placementState.active || currentTool === "paint_tile")) {
    rotatePlacement();
  }
});

document.getElementById("btn-place_here").onclick = () => {
  if (!placementState.active) return;
  if (!lastClickedTile) {
    setStatus("Click a tile first, then press Place Here");
    return;
  }
  commitPlacement(lastClickedTile);
};

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
      currentWorldTileType     = innerKey;
      currentWorldTileRotation = 0;
      setActiveTool("paint_tile");
      closeModal("modal-paint_tile");
      setStatus(`Paint tile: ${innerKey} — double-click a tile, or click a tile then press Place Tile. Press R to rotate.`);
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
      setActiveTool("place_floorplan");
      placementState.templateId = id;
      placementState.mode       = "floorplan";
      placementState.active     = true;
      placementState.rotation   = 0;
      updatePlaceButton();
      closeModal("modal-place_floorplan");
      setStatus(`Place floorplan: ${id} — double-click a tile, or click a tile then press Place Here`);
    }
  );
  openModal("modal-place_floorplan");
};

//
// Place Prop button
//

document.getElementById("btn-place_prop").onclick = () => {
  buildModalList(
    document.getElementById("list-place_prop"),
    definitions.prop_templates,
    (id) => {
      setActiveTool("place_prop");
      placementState.templateId = id;
      placementState.mode       = "prop";
      placementState.active     = true;
      placementState.rotation   = 0;
      updatePlaceButton();
      closeModal("modal-place_prop");
      setStatus(`Place prop: ${id} — double-click a tile, or click a tile then press Place Here`);
    }
  );
  openModal("modal-place_prop");
};

//
// Place Wall button
//

document.getElementById("btn-place_wall").onclick = () => {
  buildModalList(
    document.getElementById("list-place_wall"),
    definitions.wall_segment_templates,
    (id) => {
      setActiveTool("place_wall");
      placementState.templateId = id;
      placementState.mode       = "wall_segment";
      placementState.active     = true;
      placementState.rotation   = 0;
      updatePlaceButton();
      closeModal("modal-place_wall");
      setStatus(`Place wall: ${id} — snaps to the tile's north edge by default, press R to cycle sides, then double-click or Place Here`);
    }
  );
  openModal("modal-place_wall");
};

//
// Spawn Character button
//

document.getElementById("btn-spawn_character").onclick = () => {
  buildModalList(
    document.getElementById("list-spawn_character"),
    definitions.character_templates,
    async (id) => {
      closeModal("modal-spawn_character");

      if (!lastClickedTile) {
        setStatus("Click a tile first, then spawn character");
        return;
      }

      setStatus(`Spawning ${id} at ${lastClickedTile.x}, ${lastClickedTile.y}…`);

      try {
        const res = await fetch("/api/editor/spawn_character", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({
            sim_id:   "default",
            template: id,
            x:        lastClickedTile.x,
            y:        lastClickedTile.y
          })
        });

        if (res.ok) {
          setStatus(`Spawned ${id} at ${lastClickedTile.x}, ${lastClickedTile.y}`);
        } else {
          const err = await res.text();
          setStatus(`Spawn failed: ${err}`);
        }
      } catch (e) {
        setStatus(`Spawn error: ${e.message}`);
      }
    }
  );
  openModal("modal-spawn_character");
};

//
// ===================================
// DEFINITIONS
// ===================================
//

async function loadDefinitions() {
  const res = await fetch("/api/editor/definitions?sim_id=default");
  definitions = await res.json();
}

//
// ===================================
// LOAD WORLD
// ===================================
//

async function loadWorld() {
  const res   = await fetch("/api/editor/world?sim_id=default");
  const world = await res.json();

  Object.assign(worldState, world);

  for (const tile of worldState.world_tiles || []) {
    paintTile(tile.x, tile.y, tile.type, tile.rotation || 0);
  }

  for (const prop of worldState.placed_props || []) {
    addPropMarker(prop);
  }

  for (const fp of worldState.floorplans || []) {
    addFloorplanMarker(fp);
  }

  for (const wallSeg of worldState.wall_segments || []) {
    addWallSegmentMarker(wallSeg);
  }
}

//
// ===================================
// SAVE
// ===================================
//

window.saveWorld = async () => {
  await fetch("/api/editor/world?sim_id=default", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(worldState)
  });
  alert("World saved");
};

window.reloadWorld = () => location.reload();

//
// ===================================
// RENDER LOOP
// ===================================
//

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}

await loadDefinitions();
await loadWorld();
animate();
