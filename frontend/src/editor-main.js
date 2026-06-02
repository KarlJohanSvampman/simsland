
import * as THREE from "three";
import { OrbitControls }
from "three/examples/jsm/controls/OrbitControls.js";

const canvas =
  document.getElementById("c");

const scene =
  new THREE.Scene();

scene.background =
  new THREE.Color(0x20242a);

const camera =
  new THREE.PerspectiveCamera(
    60,
    window.innerWidth /
    window.innerHeight,
    0.1,
    1000
  );
let selectedTile = null;
let selectionHighlight = null;
camera.position.set(10,10,10);

const renderer =
  new THREE.WebGLRenderer({

    canvas,
    antialias: true
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
  new THREE.GridHelper(100,100)
);

const raycaster =
  new THREE.Raycaster();

const mouse =
  new THREE.Vector2();

const tiles = {};

let definitions = {  floorplan_templates: {}};

const worldState = {
  floorplans: []
};

const placementState = {

  active: false,

  templateId: null,

  rotation: 0,

  preview: null
};

// =========================================
// LOAD DEFINITIONS
// =========================================

async function loadDefinitions(){

  const res = await fetch(
    "/definitions?sim_id=default"
  );

  definitions = await res.json();

  populateFloorplanDropdown();
}

// =========================================
// DROPDOWN
// =========================================

function populateFloorplanDropdown(){

  const select =
    document.getElementById(
      "floorplanSelect"
    );

  if(!select) return;

  select.innerHTML = "";

  const defs =
    definitions
    ?.floorplan_templates
    || {};

  for(const id in defs){

    const opt =
      document.createElement("option");

    opt.value = id;
    opt.textContent = id;

    select.appendChild(opt);
  }
}
function createSelectionHighlight(){

  const geo =
    new THREE.EdgesGeometry(
      new THREE.PlaneGeometry(
        1.05,
        1.05
      )
    );

  const line =
    new THREE.LineSegments(

      geo,

      new THREE.LineBasicMaterial({

        color: 0xffff00

      })
    );

  line.rotation.x = -Math.PI / 2;

  line.position.y = 0.05;

  line.visible = false;

  scene.add(line);

  return line;
}
// =========================================
// TILES
// =========================================

function createTile(x,y){

  const mesh =
    new THREE.Mesh(

      new THREE.PlaneGeometry(1,1),

      new THREE.MeshBasicMaterial({

        color: 0x557799,

        side:
          THREE.DoubleSide
      })
    );

  mesh.rotation.x =
    -Math.PI / 2;

  mesh.position.set(x,0,y);

  mesh.userData = {

    type: "tile",

    x,
    y
  };

  scene.add(mesh);

  tiles[`${x},${y}`] = mesh;
}

for(let x=-40;x<40;x++){

  for(let y=-40;y<40;y++){

    createTile(x,y);
  }
}
selectionHighlight =
createSelectionHighlight();
// =========================================
// PREVIEW
// =========================================

function clearPlacementPreview(){

  if(!placementState.preview)
    return;

  scene.remove(
    placementState.preview
  );

  placementState.preview = null;
}

function buildFloorplanPreview(
  template,
  worldX,
  worldY
){

  const group =
    new THREE.Group();

  for(const key in template.tiles){

    const [tx,ty] = key
      .split(",")
      .map(Number);

    const geo =
      new THREE.PlaneGeometry(1,1);

    const mat =
      new THREE.MeshBasicMaterial({

        color: 0x00ff99,

        transparent: true,

        opacity: 0.45,

        side: THREE.DoubleSide
      });

    const mesh =
      new THREE.Mesh(geo, mat);

    mesh.rotation.x =
      -Math.PI / 2;

    mesh.position.set(
      worldX + tx,
      0.02,
      worldY + ty
    );

    group.add(mesh);
  }

  group.rotation.y =
    placementState.rotation;

  return group;
}

// =========================================
// TOOLBAR
// =========================================

document
  .getElementById(
    "placeFloorplanBtn"
  )
  .onclick = ()=>{

    placementState.active = true;

    placementState.templateId =
      document.getElementById(
        "floorplanSelect"
      ).value;
  };

document
  .getElementById(
    "rotateFloorplanBtn"
  )
  .onclick = ()=>{

    placementState.rotation +=
      Math.PI / 2;
  };

// =========================================
// MOUSE MOVE
// =========================================

renderer.domElement
.addEventListener(

  "pointermove",

  (event)=>{

    if(!placementState.active)
      return;

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
      raycaster.intersectObjects(
        Object.values(tiles)
      );

    if(!hits.length)
      return;

    const tile =
      hits[0].object;

    clearPlacementPreview();

    const template =
      definitions
      ?.floorplan_templates
      ?.[placementState.templateId];

    if(template){

      placementState.preview =
        buildFloorplanPreview(
          template,
          tile.userData.x,
          tile.userData.y
        );

      scene.add(
        placementState.preview
      );
    }
  }
);

// =========================================
// CLICK
// =========================================

renderer.domElement
.addEventListener(

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
      raycaster.intersectObjects(
        Object.values(tiles)
      );

    if(!hits.length){
      return;
    }

    const tile =
      hits[0].object;

    selectedTile = tile;

    selectionHighlight.visible = true;

    selectionHighlight.position.set(

    tile.userData.x,

    0.03,

    tile.userData.y

    );

    // =====================================
    // PLACE FLOORPLAN
    // =====================================

    if(placementState.active){

      worldState.floorplans ||= [];

      worldState.floorplans.push({

        id:
          crypto.randomUUID(),

        template:
          placementState.templateId,

        x: tile.userData.x,

        y: tile.userData.y,

        rotation:
          placementState.rotation
      });

      document
        .getElementById(
          "editorSelection"
        ).innerHTML = `

          <b>Placed</b><br>
          ${placementState.templateId}
        `;

      return;
    }

    // =====================================
    // NORMAL TILE SELECT
    // =====================================

    document
      .getElementById(
        "editorSelection"
      ).innerHTML = `

        <b>Tile</b><br>

        ${tile.userData.x},
        ${tile.userData.y}
      `;

    document
      .getElementById(
        "inspectorContent"
      ).innerHTML = `

        <h3>Tile</h3>

        X:
        ${tile.userData.x}

        <br>

        Y:
        ${tile.userData.y}
      `;
  }
);

// =========================================
// SAVE WORLD
// =========================================

window.saveWorld = async function(){

  await fetch(
    "/api/editor/world?sim_id=default",
    {
      method: "POST",

      headers: {
        "Content-Type": "application/json"
      },

      body: JSON.stringify(worldState)
    }
  );

  alert("World saved");
};

// =========================================
// RELOAD
// =========================================

window.reloadWorld = ()=>{
  location.reload();
};

// =========================================
// ANIMATE
// =========================================

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

loadDefinitions();
animate();