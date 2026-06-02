import { detectRooms } from './roomDetection.js';
import { generateRoomGraph } from './roomGraph.js';
import { generateNavigationGrid } from './navigation.js';
import {

  resolveFloorplan

} from "./templates.js";
const FLOORPLAN_CACHE = {

  roomsDirty: true,

  navDirty: true,

  graphDirty: true,

  cachedRoomLookup: null,

  cachedGraph: null,

  cachedNavigation: null
};
const canvas = document.getElementById("floorCanvas");
const ctx = canvas.getContext("2d");

const TILE_SIZE = 32;

let definitions = {};
let currentTool = "tile";

let currentTileTemplate = "grass";

let currentMaterial = "wood_floor_01";
let roomMode = false;
let isMouseDown = false;

const selectedTiles = new Set();

const ROOM_TYPES = [
  "restroom",
  "kitchen",
  "living_room",
  "bedroom",
  "dining_room",
  "home_office",
  "main_entrance",
  "secondary_exit"
];


const ROOM_COLORS = {
  restroom: "rgba(0,255,255,0.2)",
  kitchen: "rgba(255,165,0,0.2)",
  living_room: "rgba(180,100,255,0.2)",
  bedroom: "rgba(100,100,255,0.2)",
  dining_room: "rgba(255,220,120,0.2)",
  home_office: "rgba(120,220,255,0.2)",
  main_entrance: "rgba(255,255,255,0.2)",
  secondary_exit: "rgba(255,100,100,0.2)"
};

let floorplan = {

  id: "starter_house",

  category: "residential",

  tags: [

    "small",

    "starter"
  ],

  width: 20,

  height: 20,

  tiles: {},

  rooms: [],

  roomGraph: {},

  navigation: {}
};
function invalidateNavigation(){

  FLOORPLAN_CACHE.navDirty = true;

  FLOORPLAN_CACHE.graphDirty = true;

  FLOORPLAN_CACHE.roomsDirty = true;
}
function tileKey(x, y) {
  return `${x},${y}`;
}

function resizeCanvas() {
  canvas.width = window.innerWidth - 580;
  canvas.height = window.innerHeight;
  render();
}

window.addEventListener("resize", resizeCanvas);
resizeCanvas();

function ensureTile(x, y) {

  const key = tileKey(x, y);

  if (!floorplan.tiles[key]) {

    floorplan.tiles[key] = {
      floor: null,

      walls: {
        north: null,
        south: null,
        east: null,
        west: null
      }
    };
  }

  return floorplan.tiles[key];
}

function setFloorTile(
  x,
  y,
  action
){

  invalidateNavigation();

  const tile =
    ensureTile(x,y);

  if(
    action === "erase"
  ){

    delete floorplan.tiles[
      tileKey(x,y)
    ];

    return;
  }

  tile.floor = {

    template:
      currentTileTemplate
  };
}

function setWallTile(x, y, side, type) {
  invalidateNavigation();
  const tile = ensureTile(x, y);

  tile.walls[side] = {
    type,
    material: currentMaterial
  };
}

function screenToTile(mx, my) {

  return {
    x: Math.floor(mx / TILE_SIZE),
    y: Math.floor(my / TILE_SIZE)
  };
}

function paintTile(x, y) {

  if (
    x < 0 ||
    y < 0 ||
    x >= floorplan.width ||
    y >= floorplan.height
  ) {
    return;
  }

  if (roomMode) {

    const key = tileKey(x, y);

    if (selectedTiles.has(key)) {
      selectedTiles.delete(key);
    } else {
      selectedTiles.add(key);
    }

    render();
    return;
  }

  if(
    currentTool === "tile"
  ){

    setFloorTile(
      x,
      y,
      "tile"
    );
  }

  else if(
    currentTool === "erase"
  ){

    setFloorTile(
      x,
      y,
      "erase"
    );
  }{
    setFloorTile(x, y, currentTool);
  }

  else if (currentTool === "wall") {
    setWallTile(x, y, "north", "wall");
    setWallTile(x, y, "west", "wall");
  }

  else if (currentTool === "door") {
    setWallTile(x, y, "north", "door");
  }

  else if (currentTool === "window") {
    setWallTile(x, y, "north", "window");
  }

  render();
}

canvas.addEventListener("mousedown", (e) => {

  isMouseDown = true;

  const rect = canvas.getBoundingClientRect();

  const tile = screenToTile(
    e.clientX - rect.left,
    e.clientY - rect.top
  );

  paintTile(tile.x, tile.y);
});

canvas.addEventListener("mousemove", (e) => {

  if (!isMouseDown) return;

  if (roomMode) return;

  const rect = canvas.getBoundingClientRect();

  const tile = screenToTile(
    e.clientX - rect.left,
    e.clientY - rect.top
  );

  paintTile(tile.x, tile.y);
});

window.addEventListener("mouseup", () => {
  isMouseDown = false;
});

function renderGrid() {

  ctx.strokeStyle = "#333";

  for (let x = 0; x < floorplan.width; x++) {

    for (let y = 0; y < floorplan.height; y++) {

      ctx.strokeRect(
        x * TILE_SIZE,
        y * TILE_SIZE,
        TILE_SIZE,
        TILE_SIZE
      );
    }
  }
}

function renderTiles(){

  for(
    const key
    in floorplan.tiles
  ){

    const [x,y] =
      key.split(",")
      .map(Number);

    const tile =
      floorplan.tiles[key];

    if(
      !tile.floor
    ){
      continue;
    }

    const templateId =

      tile.floor.template;

    const tpl =

      definitions
        ?.tile_templates
        ?.[templateId];

    let color =
      "#777";

    if(
      tpl?.editor_color
    ){

      color =
        tpl.editor_color;
    }

    else{

      switch(
        templateId
      ){

        case "grass":
          color="#3f7a3f";
          break;

        case "road":
          color="#444";
          break;

        case "sidewalk":
          color="#aaa";
          break;

        case "water":
          color="#4477cc";
          break;
      }
    }

    ctx.fillStyle =
      color;

    ctx.fillRect(

      x * TILE_SIZE,

      y * TILE_SIZE,

      TILE_SIZE,

      TILE_SIZE
    );
  }
}

function renderWalls() {

  ctx.lineWidth = 4;

  for (const key in floorplan.tiles) {

    const [x, y] = key
      .split(",")
      .map(Number);

    const tile = floorplan.tiles[key];

    const px = x * TILE_SIZE;
    const py = y * TILE_SIZE;

    const walls = tile.walls || {};

    for (const side in walls) {

      const wall = walls[side];

      if (!wall) continue;

      if (wall.type === "wall") {
        ctx.strokeStyle = "#dddddd";
      }

      else if (wall.type === "door") {
        ctx.strokeStyle = "#996633";
      }

      else if (wall.type === "window") {
        ctx.strokeStyle = "#66ccff";
      }

      ctx.beginPath();

      if (side === "north") {
        ctx.moveTo(px, py);
        ctx.lineTo(px + TILE_SIZE, py);
      }

      if (side === "south") {
        ctx.moveTo(px, py + TILE_SIZE);
        ctx.lineTo(px + TILE_SIZE, py + TILE_SIZE);
      }

      if (side === "west") {
        ctx.moveTo(px, py);
        ctx.lineTo(px, py + TILE_SIZE);
      }

      if (side === "east") {
        ctx.moveTo(px + TILE_SIZE, py);
        ctx.lineTo(px + TILE_SIZE, py + TILE_SIZE);
      }

      ctx.stroke();
    }
  }
}

function renderRooms(){

  for(const room of floorplan.rooms || []){

    ctx.fillStyle =

      ROOM_COLORS[
        room.type
      ]

      || "rgba(255,255,255,0.15)";

    for(const tile of room.tiles){

      ctx.fillRect(

        tile.x * TILE_SIZE,

        tile.y * TILE_SIZE,

        TILE_SIZE,

        TILE_SIZE
      );
    }
  }
}


function renderSelection() {

  ctx.fillStyle =
    "rgba(255,255,255,0.35)";

  for (const key of selectedTiles) {

    const parts = key.split(",");

    const x = parseInt(parts[0]);

    const y = parseInt(parts[1]);
    ctx.fillRect(
      x * TILE_SIZE,
      y * TILE_SIZE,
      TILE_SIZE,
      TILE_SIZE
    );
  }
}

function render(){

  ctx.clearRect(

    0,
    0,

    canvas.width,

    canvas.height
  );

  renderGrid();

  renderTiles();

  renderRooms();

  renderSelection();

  renderWalls();

  document.getElementById(
    "selectionInfo"
  ).innerHTML =

    `${selectedTiles.size} selected`;
}

function updateRoomList() {

  const el =
    document.getElementById(
      "roomList"
    );

  el.innerHTML = "";

  for (const room of floorplan.rooms) {

    const div =
      document.createElement("div");

    div.className = "roomRow";

    div.innerHTML = `
      <b>${room.id}</b><br>
      ${room.type}<br>
      ${room.tiles.length} tiles
    `;

    el.appendChild(div);
  }
}

function setStatus(text) {

  document.getElementById(
    "status"
  ).innerText = text;
}

async function loadDefinitions() {

  const res = await fetch(
    "/api/editor/definitions?sim_id=default"
  );

  definitions = await res.json();

  populateMaterials();

  populateTileTemplates();
}

function populateMaterials() {

  const select =
    document.getElementById(
      "materialSelect"
    );

  select.innerHTML = "";

  const mats =
    definitions.material_templates
    || {};

  for (const id in mats) {

    const opt =
      document.createElement("option");

    opt.value = id;
    opt.innerText =
      mats[id].name || id;

    select.appendChild(opt);
  }

  select.onchange = () => {
    currentMaterial = select.value;
  };
}

function populateTileTemplates(){

  const select =
    document.getElementById(
      "tileTemplateSelect"
    );

  if(!select){
    return;
  }

  select.innerHTML = "";

  const templates =

    definitions
      .tile_templates
    || {};

  for(
    const id
    in templates
  ){

    const opt =
      document.createElement(
        "option"
      );

    opt.value = id;

    opt.textContent =
      templates[id].name
      || id;

    select.appendChild(opt);
  }

  if(
    select.options.length
  ){

    currentTileTemplate =
      select.options[0].value;
  }

  select.onchange = ()=>{

    currentTileTemplate =
      select.value;
  };
} 
async function saveDefinitions(defs) {

  await fetch(
    "/api/editor/definitions?sim_id=default",
    {
      method: "POST",

      headers: {
        "Content-Type": "application/json"
      },

      body: JSON.stringify(defs)
    }
  );
}
function rebuildFloorplanCaches(){

  // =========================
  // ROOM DETECTION
  // =========================

  if(FLOORPLAN_CACHE.roomsDirty){

    detectRooms(floorplan);

    FLOORPLAN_CACHE.roomsDirty = false;
  }

  // =========================
  // ROOM GRAPH
  // =========================

  if(FLOORPLAN_CACHE.graphDirty){

    generateRoomGraph(floorplan);

    FLOORPLAN_CACHE.cachedGraph =
      floorplan.roomGraph;

    FLOORPLAN_CACHE.graphDirty = false;
  }
  buildRoomLookup();
  // =========================
  // NAVIGATION
  // =========================

  if(FLOORPLAN_CACHE.navDirty){

    generateNavigationGrid(
      floorplan
    );

    FLOORPLAN_CACHE.cachedNavigation =
      floorplan.navigation;

    FLOORPLAN_CACHE.navDirty = false;
  }
}
function buildRoomLookup(){

  const lookup = {};

  for(const room of floorplan.rooms){

    for(const tile of room.tiles){

      lookup[
        `${tile.x},${tile.y}`
      ] = room.id;
    }
  }

  FLOORPLAN_CACHE.cachedRoomLookup =
    lookup;
}
async function saveFloorplan(){

  rebuildFloorplanCaches();

  const defs = definitions;

  defs.floorplan_templates =
    defs.floorplan_templates || {};

  defs.floorplan_templates[
    floorplan.id
  ] = floorplan;

  await saveDefinitions(defs);

  setStatus(
    `Saved ${floorplan.id}`
  );
}

async function loadFloorplan(){

  const id = prompt(
    "Floorplan ID"
  );

  if(!id) return;

  const fp =
    definitions
    ?.floorplan_templates
    ?.[id];

  if(!fp){

    alert("Not found");

    return;
  }

  floorplan = structuredClone(fp);

  rebuildFloorplanCaches();

  updateRoomList();

  render();

  setStatus(
    `Loaded ${id}`
  );
}

// TOOL BUTTONS

document
  .querySelectorAll(".toolBtn")
  .forEach(btn => {

    btn.onclick = () => {

      document
        .querySelectorAll(".toolBtn")
        .forEach(b =>
          b.classList.remove("active")
        );

      btn.classList.add("active");

      currentTool =
        btn.dataset.tool;

      roomMode = false;
    };
  });

// ROOM MODE

document.getElementById(
  "roomModeBtn"
).onclick = () => {

  roomMode = !roomMode;
};

// CREATE ROOM

document.getElementById(
  "createRoomBtn"
).onclick = () => {

  if(selectedTiles.size === 0){
    return;
  }

  invalidateNavigation();

  const type = prompt(

    "Room Type:\n"

    + ROOM_TYPES.join(", ")
  );

  if(!type) return;

  const tags = (

    prompt(
      "Tags (comma separated)"
    )

    || ""
  );

  const id =

    `${type}_${
      floorplan.rooms.length
    }`;

  const tiles = [];

  for(const key of selectedTiles){

    const [x, y] = key
      .split(",")
      .map(Number);

    tiles.push({
      x,
      y
    });
  }

  floorplan.rooms.push({

    id,

    type,

    tags: tags
      .split(",")
      .map(t => t.trim())
      .filter(Boolean),

    tiles
  });

  selectedTiles.clear();

  rebuildFloorplanCaches();

  updateRoomList();

  render();
};


// NEW FLOORPLAN
document.getElementById(
  "newFloorplanBtn"
).onclick = () => {

  floorplan = {

    id:

      document.getElementById(
        "floorplanId"
      ).value

      || "new_floorplan",

    category: "residential",

    tags: [],

    width: parseInt(

      document.getElementById(
        "floorplanWidth"
      ).value
    ),

    height: parseInt(

      document.getElementById(
        "floorplanHeight"
      ).value
    ),

    tiles: {},

    rooms: [],

    roomGraph: {},

    navigation: {}
  };

  invalidateNavigation();

  updateRoomList();

  render();
};
// SAVE / LOAD

document.getElementById(
  "saveFloorplanBtn"
).onclick = saveFloorplan;

document.getElementById(
  "loadFloorplanBtn"
).onclick = loadFloorplan;

loadDefinitions().then(() => {
  render();
});
