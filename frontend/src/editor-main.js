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

camera.position.set(
  20,
  20,
  20
);

const renderer =
new THREE.WebGLRenderer({
  canvas:
    document.getElementById("c"),
  antialias:true
});

renderer.setSize(
  window.innerWidth,
  window.innerHeight
);

const controls =
new OrbitControls(
  camera,
  renderer.domElement
);

controls.enableDamping = true;

scene.add(
  new THREE.AmbientLight(
    0xffffff,
    1
  )
);

scene.add(
  new THREE.GridHelper(
    WORLD_SIZE,
    WORLD_SIZE
  )
);

const raycaster =
new THREE.Raycaster();

const mouse =
new THREE.Vector2();

let definitions = {
  floorplan_templates: {},
  prop_templates: {}
};

const worldState = {
  floorplans: [],
  world_tiles: [],
  placed_props: []
};

let currentTool = "select";
let currentWorldTileType = "grass";

const placementState = {
  active: false,
  mode: null,           // "floorplan" | "prop"
  templateId: null,
  rotation: 0,
  preview: null
};

//
// ===================================
// TILE STORAGE
// ===================================
//

const tileData = new Map();

function key(x,y){
  return `${x},${y}`;
}

//
// ===================================
// GROUND PICKING PLANE
// ===================================
//

const ground =
new THREE.Mesh(
  new THREE.PlaneGeometry(
    WORLD_SIZE,
    WORLD_SIZE
  ),
  new THREE.MeshBasicMaterial({
    visible:false
  })
);

ground.rotation.x =
  -Math.PI / 2;

scene.add(ground);

//
// ===================================
// INSTANCED TILE MESH
// ===================================
//

const tileGeometry =
new THREE.PlaneGeometry(
  1,
  1
);

tileGeometry.rotateX(
  -Math.PI / 2
);

const tileMaterial =
new THREE.MeshBasicMaterial({
  vertexColors:true
});

const TILE_COUNT =
WORLD_SIZE * WORLD_SIZE;

const tileMesh =
new THREE.InstancedMesh(
  tileGeometry,
  tileMaterial,
  TILE_COUNT
);

scene.add(tileMesh);

const dummy =
new THREE.Object3D();

const color =
new THREE.Color();

const tileIndexMap =
new Map();

let instance = 0;

for(
  let x = 0;
  x < WORLD_SIZE;
  x++
){

  for(
    let y = 0;
    y < WORLD_SIZE;
    y++
  ){

    dummy.position.set(
      x + 0.5 - WORLD_SIZE/2,
      0,
      y + 0.5 - WORLD_SIZE/2
    );

    dummy.updateMatrix();

    tileMesh.setMatrixAt(
      instance,
      dummy.matrix
    );

    color.setHex(
      0x557799
    );

    tileMesh.setColorAt(
      instance,
      color
    );

    tileIndexMap.set(
      key(x,y),
      instance
    );

    instance++;
  }
}

tileMesh.instanceMatrix.needsUpdate =
true;

tileMesh.instanceColor.needsUpdate =
true;

//
// ===================================
// SELECTION
// ===================================
//

const selection =
new THREE.Mesh(
  new THREE.PlaneGeometry(
    1.02,
    1.02
  ),
  new THREE.MeshBasicMaterial({
    color:0xffff00,
    wireframe:true
  })
);

selection.rotation.x =
  -Math.PI/2;

selection.visible = false;

scene.add(selection);

//
// ===================================
// COLORS
// ===================================
//

const TILE_COLORS = {

  grass:0x3f7a3f,

  road:0x333333,

  sidewalk:0xaaaaaa,

  park:0x55aa55,

  water:0x3377cc
};

//
// ===================================
// WORLD->GRID
// ===================================
//

function worldToGrid(point){

  const x =
  Math.floor(
    point.x + WORLD_SIZE/2
  );

  const y =
  Math.floor(
    point.z + WORLD_SIZE/2
  );

  return {x,y};
}

//
// ===================================
// GRID->WORLD
// ===================================
//

function gridToWorld(x,y){

  return {

    x:
      x + 0.5 -
      WORLD_SIZE/2,

    z:
      y + 0.5 -
      WORLD_SIZE/2
  };
}

//
// ===================================
// PAINT TILE
// ===================================
//

function paintTile(
  x,
  y,
  type
){

  const index =
  tileIndexMap.get(
    key(x,y)
  );

  if(index == null)
    return;

  color.setHex(

    TILE_COLORS[type]
    ||
    0x557799
  );

  tileMesh.setColorAt(
    index,
    color
  );

  tileMesh.instanceColor.needsUpdate =
    true;

  const existing =
  worldState.world_tiles.find(
    t =>
      t.x===x &&
      t.y===y
  );

  if(existing){

    existing.type = type;
  }
  else{

    worldState.world_tiles.push({

      x,
      y,
      type
    });
  }
}

//
// ===================================
// PICK TILE
// ===================================
//

function pickTile(event){

  mouse.x =
    (event.clientX /
    window.innerWidth)
    *2-1;

  mouse.y =
    -(event.clientY /
    window.innerHeight)
    *2+1;

  raycaster.setFromCamera(
    mouse,
    camera
  );

  const hit =
  raycaster.intersectObject(
    ground
  )[0];

  if(!hit)
    return null;

  return worldToGrid(
    hit.point
  );
}

//
// ===================================
// POINTER DOWN
// ===================================
//

renderer.domElement
.addEventListener(
"pointerdown",
(event)=>{

  const tile =
    pickTile(event);

  if(!tile)
    return;

  const world =
    gridToWorld(
      tile.x,
      tile.y
    );

  selection.visible = true;

  selection.position.set(
    world.x,
    0.03,
    world.z
  );

  if(
    currentTool ===
    "paint_tile"
  ){

    paintTile(

      tile.x,

      tile.y,

      currentWorldTileType
    );

    return;
  }

  if(
    placementState.active
  ){

    if (placementState.mode === 'prop') {

      worldState.placed_props.push({
        id:       crypto.randomUUID(),
        template: placementState.templateId,
        x:        tile.x,
        y:        tile.y,
        rotation: placementState.rotation
      });

      document
      .getElementById('editorSelection')
      .innerHTML = `
        <b>Placed prop</b><br>
        ${placementState.templateId}<br>
        @ ${tile.x}, ${tile.y}
      `;

      return;
    }

    worldState.floorplans.push({

      id:
      crypto.randomUUID(),

      template:
      placementState.templateId,

      x:
      tile.x,

      y:
      tile.y,

      rotation:
      placementState.rotation
    });

    return;
  }

  document
  .getElementById(
    "editorSelection"
  ).innerHTML = `

    <b>Tile</b><br>

    ${tile.x},
    ${tile.y}
  `;
});

//
// ===================================
// DEFINITIONS
// ===================================
//

async function loadDefinitions(){

  const res =
  await fetch(
    "/api/editor/definitions?sim_id=default"
  );

  definitions =
  await res.json();

  // Populate floorplan selector
  const fpSelect =
  document.getElementById(
    "floorplanSelect"
  );

  if(fpSelect){

    fpSelect.innerHTML="";

    for(
      const id
      in definitions.floorplan_templates
    ){

      const opt =
      document.createElement(
        "option"
      );

      opt.value=id;
      opt.textContent=id;

      fpSelect.appendChild(opt);
    }
  }

  // Populate prop selector
  const propSelect =
  document.getElementById(
    "propSelect"
  );

  if(propSelect){

    propSelect.innerHTML = '<option value="">— pick prop —</option>';

    for(
      const id
      in definitions.prop_templates
    ){

      const opt =
      document.createElement("option");

      opt.value = id;
      opt.textContent = id;

      propSelect.appendChild(opt);
    }
  }
}

//
// ===================================
// LOAD WORLD
// ===================================
//

async function loadWorld(){

  const res =
  await fetch(
    "/api/editor/world?sim_id=default"
  );

  const world =
  await res.json();

  Object.assign(
    worldState,
    world
  );

  for(
    const tile
    of
    worldState.world_tiles
    || []
  ){

    paintTile(
      tile.x,
      tile.y,
      tile.type
    );
  }
}

//
// ===================================
// SAVE
// ===================================
//

window.saveWorld =
async ()=>{

  await fetch(
    "/api/editor/world?sim_id=default",
    {
      method:"POST",
      headers:{
        "Content-Type":
        "application/json"
      },
      body:
      JSON.stringify(
        worldState
      )
    }
  );

  alert(
    "World saved"
  );
};

window.reloadWorld =
()=> location.reload();

//
// ===================================
// TOOLS
// ===================================
//

document
.querySelectorAll(
  ".toolButton"
)
.forEach(btn=>{

  btn.onclick = ()=>{

    currentTool =
      btn.dataset.tool
      ||
      "select";

    placementState.active =
      currentTool ===
      "place_floorplan";
  };
});

const tileSelect =
document.getElementById(
  "worldTileSelect"
);

if(tileSelect){

  tileSelect.onchange =
  ()=>{

    currentWorldTileType =
      tileSelect.value;
  };
}

const rotateBtn =
document.getElementById(
  "rotateFloorplanBtn"
);

if(rotateBtn){

  rotateBtn.onclick =
  ()=>{

    placementState.rotation +=
      Math.PI/2;
  };
}

//
// ===================================
// RENDER LOOP
// ===================================
//

function animate(){

  requestAnimationFrame(
    animate
  );

  controls.update();

  renderer.render(
    scene,
    camera
  );
}

await loadDefinitions();
await loadWorld();

animate();