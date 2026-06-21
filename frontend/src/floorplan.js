import { detectRooms }            from "./roomDetection.js";
import { generateRoomGraph }       from "./roomGraph.js";
import { generateNavigationGrid }  from "./navigation.js";

// =========================================================
// CONSTANTS
// =========================================================

const TILE_SIZE = 32;

const ROOM_TYPES = [
  "restroom", "kitchen", "living_room", "bedroom", "dining_room",
  "home_office", "corridor", "main_entrance", "secondary_exit",
  "storage", "garage", "laundry", "room",
];

const ROOM_COLORS = {
  restroom:       "rgba(0,255,255,0.18)",
  kitchen:        "rgba(255,165,0,0.18)",
  living_room:    "rgba(180,100,255,0.18)",
  bedroom:        "rgba(80,80,255,0.18)",
  dining_room:    "rgba(255,220,120,0.18)",
  home_office:    "rgba(120,220,255,0.18)",
  corridor:       "rgba(180,180,180,0.12)",
  main_entrance:  "rgba(255,255,255,0.18)",
  secondary_exit: "rgba(255,80,80,0.18)",
  storage:        "rgba(140,100,60,0.18)",
  garage:         "rgba(100,140,80,0.18)",
  laundry:        "rgba(60,180,220,0.18)",
};

const WALL_COLORS = { wall: "#ddd", door: "#b07030", window: "#55aaee" };

// =========================================================
// STATE
// =========================================================

const canvas = document.getElementById("floorCanvas");
const ctx    = canvas.getContext("2d");

let definitions        = {};
let currentTool        = "tile";
let currentTileTemplate= "grass";
let currentMaterial    = "wood_floor_01";
let currentPropTemplate= "";
let currentPropRotation= 0;
let roomMode           = false;
let isLeftDown         = false;
let isPanning          = false;
let panStartX          = 0;
let panStartY          = 0;

// Pan / zoom
let viewX    = 0;
let viewY    = 0;
let viewZoom = 1;

// Hover info (world coords & detected wall side)
let hoverInfo = null;  // { x, y, fx, fy, side }

const selectedTiles = new Set();

let floorplan = {
  id:         "starter_house",
  category:   "residential",
  tags:       ["small", "starter"],
  width:      20,
  height:     20,
  tiles:      {},
  rooms:      [],
  roomGraph:  {},
  navigation: {},
  prop_spawns: [],
};

const FLOORPLAN_CACHE = {
  roomsDirty: true,
  navDirty:   true,
  graphDirty: true,
};

// =========================================================
// COORDINATE HELPERS
// =========================================================

function screenToWorld(mx, my) {
  return {
    wx: (mx - viewX) / viewZoom,
    wy: (my - viewY) / viewZoom,
  };
}

function worldToTile(wx, wy) {
  const tx = Math.floor(wx / TILE_SIZE);
  const ty = Math.floor(wy / TILE_SIZE);
  const fx = ((wx % TILE_SIZE) + TILE_SIZE) % TILE_SIZE;
  const fy = ((wy % TILE_SIZE) + TILE_SIZE) % TILE_SIZE;
  return { x: tx, y: ty, fx, fy };
}

// Returns the nearest edge side given a fractional (fx, fy) position within a tile.
function getWallSide(fx, fy) {
  const dN = fy, dS = TILE_SIZE - fy, dW = fx, dE = TILE_SIZE - fx;
  const min = Math.min(dN, dS, dW, dE);
  if (min === dN) return "north";
  if (min === dS) return "south";
  if (min === dW) return "west";
  return "east";
}

const OPPOSITE = { north: "south", south: "north", east: "west", west: "east" };
const DELTA    = { north: [0,-1], south: [0,1], east: [1,0], west: [-1,0] };

// =========================================================
// CANVAS RESIZE
// =========================================================

function resizeCanvas() {
  canvas.width  = canvas.parentElement.clientWidth;
  canvas.height = canvas.parentElement.clientHeight;
  render();
}
window.addEventListener("resize", resizeCanvas);
resizeCanvas();

// =========================================================
// TILE HELPERS
// =========================================================

function tileKey(x, y) { return `${x},${y}`; }

function ensureTile(x, y) {
  const key = tileKey(x, y);
  if (!floorplan.tiles[key]) {
    floorplan.tiles[key] = {
      floor: null,
      walls: { north: null, south: null, east: null, west: null },
    };
  }
  return floorplan.tiles[key];
}

function invalidateNavigation() {
  FLOORPLAN_CACHE.roomsDirty = true;
  FLOORPLAN_CACHE.navDirty   = true;
  FLOORPLAN_CACHE.graphDirty = true;
}

function inBounds(x, y) {
  return x >= 0 && y >= 0 && x < floorplan.width && y < floorplan.height;
}

// =========================================================
// PAINT ACTIONS
// =========================================================

function setFloorTile(x, y, erase = false) {
  invalidateNavigation();
  if (erase) {
    delete floorplan.tiles[tileKey(x, y)];
    return;
  }
  const tile = ensureTile(x, y);
  tile.floor = { template: currentTileTemplate };
}

// Paints a wall/door/window on the given side of (x,y).
// Also mirrors the opposite side on the adjacent tile so walls are bidirectional.
function setWallEdge(x, y, side, type) {
  if (!inBounds(x, y)) return;
  invalidateNavigation();

  const tile = ensureTile(x, y);
  tile.walls[side] = type ? { type, material: currentMaterial } : null;

  // Mirror on adjacent tile
  const [dx, dy] = DELTA[side];
  const nx = x + dx, ny = y + dy;
  if (inBounds(nx, ny)) {
    const nTile = ensureTile(nx, ny);
    nTile.walls[OPPOSITE[side]] = type ? { type, material: currentMaterial } : null;
  }
}

function eraseWallEdge(x, y, side) {
  setWallEdge(x, y, side, null);
}

function placeOrEraseProp(x, y, erase = false) {
  if (!inBounds(x, y)) return;
  if (erase) {
    floorplan.prop_spawns = floorplan.prop_spawns.filter(
      p => !(p.x === x && p.y === y)
    );
    return;
  }
  if (!currentPropTemplate) { setStatus("Select a prop template first"); return; }
  // Remove existing spawn at this tile before placing
  floorplan.prop_spawns = floorplan.prop_spawns.filter(
    p => !(p.x === x && p.y === y)
  );
  floorplan.prop_spawns.push({
    id:       crypto.randomUUID(),
    template: currentPropTemplate,
    x, y,
    rotation: currentPropRotation,
  });
  updatePropSpawnList();
}

// =========================================================
// PAINT DISPATCH
// =========================================================

function paintAt(mx, my, eraseOverride = false) {
  const rect = canvas.getBoundingClientRect();
  const { wx, wy } = screenToWorld(mx - rect.left, my - rect.top);
  const { x, y, fx, fy } = worldToTile(wx, wy);
  if (!inBounds(x, y) && currentTool !== "erase") return;

  const erase = eraseOverride || currentTool === "erase";

  if (roomMode) {
    const key = tileKey(x, y);
    if (inBounds(x, y)) {
      if (selectedTiles.has(key)) selectedTiles.delete(key);
      else selectedTiles.add(key);
      updateSelectionInfo();
      render();
    }
    return;
  }

  if (currentTool === "tile") {
    setFloorTile(x, y, erase);

  } else if (currentTool === "erase") {
    // Erase floor first; if already empty try erasing nearest wall edge
    const key  = tileKey(x, y);
    const tile = floorplan.tiles[key];
    if (tile?.floor) {
      setFloorTile(x, y, true);
    } else if (tile) {
      const side = getWallSide(fx, fy);
      eraseWallEdge(x, y, side);
    }

  } else if (currentTool === "wall") {
    const side = getWallSide(fx, fy);
    if (erase) eraseWallEdge(x, y, side);
    else setWallEdge(x, y, side, "wall");

  } else if (currentTool === "door") {
    const side = getWallSide(fx, fy);
    if (erase) eraseWallEdge(x, y, side);
    else setWallEdge(x, y, side, "door");

  } else if (currentTool === "window") {
    const side = getWallSide(fx, fy);
    if (erase) eraseWallEdge(x, y, side);
    else setWallEdge(x, y, side, "window");

  } else if (currentTool === "staircase") {
    setFloorTile(x, y, erase);
    if (!erase) {
      const tile = ensureTile(x, y);
      tile.floor.template = "staircase";
    }

  } else if (currentTool === "prop") {
    placeOrEraseProp(x, y, erase);
  }

  render();
}

// =========================================================
// CANVAS EVENTS
// =========================================================

canvas.addEventListener("contextmenu", e => e.preventDefault());

canvas.addEventListener("mousedown", e => {
  // Middle button or right button = start pan
  if (e.button === 1 || e.button === 2 && e.shiftKey) {
    isPanning  = true;
    panStartX  = e.clientX - viewX;
    panStartY  = e.clientY - viewY;
    canvas.style.cursor = "grab";
    e.preventDefault();
    return;
  }

  // Right button without shift = erase
  if (e.button === 2) {
    paintAt(e.clientX, e.clientY, true);
    return;
  }

  // Left button = paint
  if (e.button === 0) {
    isLeftDown = true;
    paintAt(e.clientX, e.clientY, false);
  }
});

canvas.addEventListener("mousemove", e => {
  // Pan
  if (isPanning) {
    viewX = e.clientX - panStartX;
    viewY = e.clientY - panStartY;
    render();
    return;
  }

  // Update hover info for wall edge preview
  const rect   = canvas.getBoundingClientRect();
  const { wx, wy } = screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
  const ti     = worldToTile(wx, wy);
  hoverInfo    = { ...ti, side: getWallSide(ti.fx, ti.fy) };

  // Paint while dragging (not in room mode — room mode is click-only)
  if (isLeftDown && !roomMode) {
    paintAt(e.clientX, e.clientY, false);
  } else {
    render(); // re-render for hover highlight
  }
});

canvas.addEventListener("mouseup", e => {
  if (isPanning) { isPanning = false; canvas.style.cursor = "crosshair"; }
  if (e.button === 0) isLeftDown = false;
});

canvas.addEventListener("mouseleave", () => {
  isLeftDown = false;
  isPanning  = false;
  hoverInfo  = null;
  render();
});

// Zoom toward cursor on scroll
canvas.addEventListener("wheel", e => {
  e.preventDefault();
  const rect      = canvas.getBoundingClientRect();
  const mx        = e.clientX - rect.left;
  const my        = e.clientY - rect.top;
  const factor    = e.deltaY < 0 ? 1.12 : 1 / 1.12;
  const newZoom   = Math.max(0.2, Math.min(6, viewZoom * factor));
  viewX           = mx - (mx - viewX) * (newZoom / viewZoom);
  viewY           = my - (my - viewY) * (newZoom / viewZoom);
  viewZoom        = newZoom;
  render();
}, { passive: false });

// =========================================================
// RENDER
// =========================================================

function render() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  ctx.save();
  ctx.setTransform(viewZoom, 0, 0, viewZoom, viewX, viewY);

  renderGrid();
  renderTiles();
  renderRooms();
  renderSelection();
  renderPropSpawns();
  renderWalls();
  renderHoverEdge();

  ctx.restore();
}

function renderGrid() {
  const invZ = 1 / viewZoom;

  // Compute visible tile range
  const x0 = Math.max(0, Math.floor((-viewX * invZ) / TILE_SIZE));
  const y0 = Math.max(0, Math.floor((-viewY * invZ) / TILE_SIZE));
  const x1 = Math.min(floorplan.width,  Math.ceil(((-viewX + canvas.width)  * invZ) / TILE_SIZE));
  const y1 = Math.min(floorplan.height, Math.ceil(((-viewY + canvas.height) * invZ) / TILE_SIZE));

  ctx.strokeStyle = "#2a2f38";
  ctx.lineWidth   = 0.5;

  for (let x = x0; x <= x1; x++) {
    ctx.beginPath();
    ctx.moveTo(x * TILE_SIZE, y0 * TILE_SIZE);
    ctx.lineTo(x * TILE_SIZE, y1 * TILE_SIZE);
    ctx.stroke();
  }
  for (let y = y0; y <= y1; y++) {
    ctx.beginPath();
    ctx.moveTo(x0 * TILE_SIZE, y * TILE_SIZE);
    ctx.lineTo(x1 * TILE_SIZE, y * TILE_SIZE);
    ctx.stroke();
  }

  // Floorplan border
  ctx.strokeStyle = "#445";
  ctx.lineWidth   = 1;
  ctx.strokeRect(0, 0, floorplan.width * TILE_SIZE, floorplan.height * TILE_SIZE);
}

function renderTiles() {
  for (const key in floorplan.tiles) {
    const tile = floorplan.tiles[key];
    if (!tile.floor) continue;

    const [x, y] = key.split(",").map(Number);
    const tpl    = definitions?.tile_templates?.[tile.floor.template];

    let color = tpl?.editor_color ?? "#555";
    if (!tpl) {
      switch (tile.floor.template) {
        case "grass":     color = "#3a6e3a"; break;
        case "road":      color = "#3a3a3a"; break;
        case "sidewalk":  color = "#888";    break;
        case "water":     color = "#3a5e99"; break;
        case "staircase": color = "#667";    break;
        default:          color = "#4a4a55"; break;
      }
    }

    ctx.fillStyle = color;
    ctx.fillRect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE);
  }
}

function renderRooms() {
  for (const room of floorplan.rooms || []) {
    ctx.fillStyle = ROOM_COLORS[room.type] || "rgba(255,255,255,0.1)";
    for (const tile of room.tiles) {
      ctx.fillRect(tile.x * TILE_SIZE, tile.y * TILE_SIZE, TILE_SIZE, TILE_SIZE);
    }
    // Label first tile
    if (room.tiles.length > 0) {
      const t  = room.tiles[0];
      const cx = t.x * TILE_SIZE + 2;
      const cy = t.y * TILE_SIZE + 10;
      ctx.fillStyle   = "rgba(255,255,255,0.6)";
      ctx.font        = `${Math.max(8, Math.round(9 / viewZoom * viewZoom))}px sans-serif`;
      ctx.font        = "8px sans-serif";
      ctx.fillText(room.type, cx, cy);
    }
  }
}

function renderSelection() {
  if (selectedTiles.size === 0) return;
  ctx.fillStyle   = "rgba(120,180,255,0.3)";
  ctx.strokeStyle = "rgba(120,180,255,0.8)";
  ctx.lineWidth   = 1.5;
  for (const key of selectedTiles) {
    const [x, y] = key.split(",").map(Number);
    ctx.fillRect  (x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE);
    ctx.strokeRect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE);
  }
}

function renderPropSpawns() {
  for (const ps of floorplan.prop_spawns || []) {
    const cx = (ps.x + 0.5) * TILE_SIZE;
    const cy = (ps.y + 0.5) * TILE_SIZE;

    ctx.fillStyle = "rgba(255,200,50,0.55)";
    ctx.beginPath();
    ctx.arc(cx, cy, TILE_SIZE * 0.35, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "rgba(0,0,0,0.7)";
    ctx.font      = "7px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(ps.template.slice(0, 8), cx, cy);
    ctx.textAlign    = "left";
    ctx.textBaseline = "alphabetic";
  }
}

function renderWalls() {
  ctx.lineCap = "round";

  for (const key in floorplan.tiles) {
    const [x, y] = key.split(",").map(Number);
    const tile   = floorplan.tiles[key];
    const px     = x * TILE_SIZE;
    const py     = y * TILE_SIZE;

    for (const [side,