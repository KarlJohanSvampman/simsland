import * as THREE from "three";

import { OrbitControls }
from "three/examples/jsm/controls/OrbitControls.js";

import { GLTFLoader }
from "three/examples/jsm/loaders/GLTFLoader.js";

const anchorMarkers = [];
const targetMarkers = [];
let pivotMarker = null;
let currentSkeletonHelper = null;
const canvas =
    document.getElementById(
        "canvas"
    );

const renderer =
    new THREE.WebGLRenderer({
        canvas,
        antialias:true
    });
renderer.autoClear = false;
renderer.setSize(
    window.innerWidth - 300,
    window.innerHeight
);

const centerSphere =
    new THREE.Mesh(

        new THREE.SphereGeometry(
            0.08,
            16,
            16
        ),

        new THREE.MeshBasicMaterial({

            color: 0x666666
        })
    );
// ======================================
// ORIENTATION GIZMO
// ======================================

const gizmoScene =
    new THREE.Scene();

const gizmoCamera =
    new THREE.PerspectiveCamera(
        50,
        1,
        0.1,
        10
    );

gizmoCamera.position.z = 3;

const gizmoRoot =
    new THREE.Group();
gizmoRoot.add(
    centerSphere
);
gizmoScene.add(
    gizmoRoot
);
const scene =
    new THREE.Scene();

scene.background =
    new THREE.Color(
        0x20242a
    );
buildOrientationGizmo();
const camera =
    new THREE.PerspectiveCamera(
        60,
        (window.innerWidth-300)
        / window.innerHeight,
        0.1,
        1000
    );

camera.position.set(
    5,
    5,
    5
);
const controls =
    new OrbitControls(
        camera,
        renderer.domElement
    );

controls.enablePan = true;
controls.enableZoom = true;
controls.enableRotate = true;

controls.screenSpacePanning = true;

controls.target.set(
    0,
    1,
    0
);

controls.update();

scene.add(
    new THREE.AmbientLight(
        0xffffff,
        2
    )
);

const sun =
    new THREE.DirectionalLight(
        0xffffff,
        2
    );

sun.position.set(
    5,
    10,
    5
);

scene.add(sun);

scene.add(
    new THREE.GridHelper(
        10,
        10
    )
);

const ground =
    new THREE.Mesh(

        new THREE.PlaneGeometry(
            200,
            200
        ),

        new THREE.MeshStandardMaterial({

            color: 0x444444

        })
    );

ground.rotation.x =
    -Math.PI / 2;

ground.position.y =
    -0.01;

scene.add(
    ground
);
let currentModel = null;
let meshbank = {};
let mixer = null;
let currentAssetId;
let currentAnimations = [];
let currentBoxHelper = null;

let anchorHelpers = [];

const loader =
    new GLTFLoader();

let assets = {};

async function loadAssets(){

    const res =
        await fetch(
            "/api/assets"
        );

    assets =
        await res.json();

    populateAssetList();
}
function updatePivotMarker(){

    if(
        !currentModel ||
        !currentAssetId
    ){
        return;
    }

    if(pivotMarker){

        scene.remove(
            pivotMarker
        );
    }

    const box =
        new THREE.Box3()
            .setFromObject(
                currentModel
            );

    const center =
        box.getCenter(
            new THREE.Vector3()
        );

const p =
    ensurePlacement(
        meshbank[
            currentAssetId
        ]
    );

    let pos =
        center.clone();

    switch(
        p?.pivot
    ){

        case "bottom_center":

            pos.y =
                box.min.y;

            break;

        case "top_center":

            pos.y =
                box.max.y;

            break;

        case "front_center":

            pos.z =
                box.max.z;

            break;

        case "rear_center":

            pos.z =
                box.min.z;

            break;
    }

    pivotMarker =
        new THREE.Mesh(

            new THREE.SphereGeometry(
                0.12,
                16,
                16
            ),

            new THREE.MeshBasicMaterial({

                color:
                    0xff0000
            })
        );

    pivotMarker.position.copy(
        pos
    );

    scene.add(
        pivotMarker
    );
}
function ensureTransform(asset){

    asset.transform ||= {

        position:{
            x:0,
            y:0,
            z:0
        },

        rotation:{
            x:0,
            y:0,
            z:0
        },

        scale:{
            x:1,
            y:1,
            z:1
        }
    };

    return asset.transform;
}
function ensureInteractions(asset){

    asset.interaction_points ||= {};

    return asset.interaction_points;
}
function populateSlotBones(){

    const select =
        document.getElementById(
            "slotBone"
        );

    select.innerHTML = "";

    const bones =
        meshbank[
            currentAssetId
        ]?.bones || {};

    for(
        const bone
        in bones
    ){

        const option =
            document.createElement(
                "option"
            );

        option.value =
            bone;

        option.textContent =
            bone;

        select.appendChild(
            option
        );
    }
}
function ensurePlacement(asset){

    asset.placement ||= {

        pivot:
            "bottom_center",

        snap_to_ground:
            true,

        snap_to_grid:
            true
    };

    return asset.placement;
}
function populateInteractionAnchors(){

    const select =
        document.getElementById(
            "interactionAnchor"
        );

    select.innerHTML = "";

    const anchors =
        meshbank[
            currentAssetId
        ]?.anchors || {};

    for(const name in anchors){

        const option =
            document.createElement(
                "option"
            );

        option.value =
            name;

        option.textContent =
            name;

        select.appendChild(
            option
        );
    }
}   
function populateInteractionTargets(){

    const select =
        document.getElementById(
            "interactionTarget"
        );

    select.innerHTML = "";

    const targets =
        meshbank[
            currentAssetId
        ]?.targets || {};

    for(const name in targets){

        const option =
            document.createElement(
                "option"
            );

        option.value =
            name;

        option.textContent =
            name;

        select.appendChild(
            option
        );
    }
}
function populateInteractions(){

    const select =
        document.getElementById(
            "interactionSelect"
        );

    select.innerHTML = "";

    const interactions =
        ensureInteractions(

            meshbank[
                currentAssetId
            ]
        );

    for(const id in interactions){

        const option =
            document.createElement(
                "option"
            );

        option.value =
            id;

        option.textContent =
            id;

        select.appendChild(
            option
        );
    }
}
function loadPlacementUI(){

    if(!currentAssetId)
        return;

    const asset =
        meshbank[
            currentAssetId
        ];

    const p =
        ensurePlacement(
            asset
        );

    document
    .getElementById(
        "pivot"
    )
    .value =
        p.pivot;

    document
    .getElementById(
        "snapGround"
    )
    .checked =
        p.snap_to_ground;

    document
    .getElementById(
        "snapGrid"
    )
    .checked =
        p.snap_to_grid;
}
function updatePlacementFromUI(){

    if(!currentAssetId)
        return;

    const asset =
        meshbank[
            currentAssetId
        ];

    const p =
        ensurePlacement(
            asset
        );

    p.pivot =

        document
        .getElementById(
            "pivot"
        )
        .value;

    p.snap_to_ground =

        document
        .getElementById(
            "snapGround"
        )
        .checked;

    p.snap_to_grid =

        document
        .getElementById(
            "snapGrid"
        )
        .checked;
}
function loadTransformUI(){

    if(!currentAssetId)
        return;

    const asset =
        meshbank[
            currentAssetId
        ];

    const t =
        ensureTransform(
            asset
        );

    posX.value =
        t.position.x;

    posY.value =
        t.position.y;

    posZ.value =
        t.position.z;

    rotX.value =
        t.rotation.x;

    rotY.value =
        t.rotation.y;

    rotZ.value =
        t.rotation.z;

    scaleX.value =
        t.scale.x;

    scaleY.value =
        t.scale.y;

    scaleZ.value =
        t.scale.z;
}
function extractAnchors(root){

    const anchors = {};

    root.traverse(node=>{

        if(
            node.name
                .toLowerCase()
                .startsWith(
                    "anchor_"
                )
        ){

            anchors[
                node.name
            ] = {

                name:
                    node.name
            };
        }
    });

    return anchors;
}
// Derive a stable asset ID from the full URL path.
// For backward compat: root-level files keep their bare name ("long_wavy"),
// subfoldered files use a path relative to category root ("hair/long_wavy").
function assetIdFromPath(assetPath, category) {
    const prefix = `/resources/${category}/`;
    return assetPath.replace(prefix, '').replace(/\.glb$/i, '');
}

function populateAssetList(){

    const category =
        document.getElementById(
            "category"
        ).value;

    const container =
        document.getElementById(
            "assetList"
        );

    container.innerHTML = "";

    // Group by subfolder (first path component after category root)
    const groups = {};   // folderName → [{asset, assetId, filename}]
    const prefix = `/resources/${category}/`;

    for (const asset of assets[category] || []) {
        const rel = asset.replace(prefix, '').replace(/\.glb$/i, '');
        const parts = rel.split('/');
        const folder = parts.length > 1 ? parts.slice(0, -1).join('/') : '';
        const filename = parts[parts.length - 1];
        (groups[folder] ||= []).push({ asset, assetId: rel, filename });
    }

    // Sort: root first, then alphabetical folders
    const folderKeys = Object.keys(groups).sort((a, b) => {
        if (a === '') return -1;
        if (b === '') return 1;
        return a.localeCompare(b);
    });

    function makeAssetRow(item, indented) {
        const div = document.createElement('div');
        div.className = 'assetRow' + (indented ? ' indented' : '');
        div.textContent = item.filename;
        div.dataset.assetId = item.assetId;
        div.onclick = () => {
            container.querySelectorAll('.assetRow').forEach(r => r.classList.remove('active'));
            div.classList.add('active');

            currentAssetId = item.assetId;
            loadModel(item.asset);

            meshbank[currentAssetId] ||= { display_name: item.filename, anchors: {} };
            meshbank[currentAssetId].mesh = item.asset;

            const meta = meshbank[currentAssetId];
            document.getElementById('displayName').value = meta?.display_name || '';
            document.getElementById('tags').value = (meta?.tags || []).join(',');
            loadPlacementUI();
            loadTransformUI();
            loadHairAttachUI();
        };
        return div;
    }

    for (const folder of folderKeys) {
        const items = groups[folder];
        if (folder === '') {
            // Root items — no header
            for (const item of items) {
                container.appendChild(makeAssetRow(item, false));
            }
        } else {
            // Folder group with collapsible header
            const group = document.createElement('div');
            group.className = 'folderGroup';

            const header = document.createElement('div');
            header.className = 'folderHeader';
            header.textContent = '▾ 📁 ' + folder;
            header.onclick = () => {
                group.classList.toggle('collapsed');
                header.textContent = group.classList.contains('collapsed')
                    ? '▸ 📁 ' + folder
                    : '▾ 📁 ' + folder;
            };

            const itemsDiv = document.createElement('div');
            itemsDiv.className = 'folderItems';
            for (const item of items) {
                itemsDiv.appendChild(makeAssetRow(item, true));
            }

            group.appendChild(header);
            group.appendChild(itemsDiv);
            container.appendChild(group);
        }
    }
}

document
.getElementById(
    "category"
)
.onchange =
populateAssetList;
function updateTransformFromUI(){

    if(
        !currentAssetId ||
        !currentModel
    ){
        return;
    }

    const asset =
        meshbank[
            currentAssetId
        ];

    const t =
        ensureTransform(
            asset
        );

    t.position.x =
        parseFloat(
            posX.value
        ) || 0;

    t.position.y =
        parseFloat(
            posY.value
        ) || 0;

    t.position.z =
        parseFloat(
            posZ.value
        ) || 0;

    t.rotation.x =
        parseFloat(
            rotX.value
        ) || 0;

    t.rotation.y =
        parseFloat(
            rotY.value
        ) || 0;

    t.rotation.z =
        parseFloat(
            rotZ.value
        ) || 0;

    t.scale.x =
        parseFloat(
            scaleX.value
        ) || 1;

    t.scale.y =
        parseFloat(
            scaleY.value
        ) || 1;

    t.scale.z =
        parseFloat(
            scaleZ.value
        ) || 1;

    applyTransform(
        currentModel,
        t
    );

    updateBoxHelper(
        currentModel
    );
updateStats(
    currentModel
);
    updatePivotMarker();


}   
function clearCurrentModel(){

    if(currentModel){

        scene.remove(
            currentModel
        );

        currentModel = null;
    }

    if(currentBoxHelper){

        scene.remove(
            currentBoxHelper
        );

        currentBoxHelper = null;
    }

    if(currentSkeletonHelper){

    scene.remove(
        currentSkeletonHelper
    );

    currentSkeletonHelper = null;
}

    for(const helper of anchorHelpers){

        scene.remove(
            helper
        );
    }

    anchorHelpers = [];

    _removeAnchorMarkers();
    _removeTargetMarkers();

    mixer = null;
}

async function loadMeshbank(){

    const res =
        await fetch(
            "/api/meshbank"
        );

    meshbank =
        await res.json();
}
async function saveMeshbank(){

    await fetch(

        "/api/meshbank",

        {
            method:"POST",

            headers:{
                "Content-Type":
                "application/json"
            },

            body: JSON.stringify(
                meshbank
            )
        }
    );
}

document
.getElementById(
    "uploadBtn"
)
.onclick = async ()=>{

    const file =
        document.getElementById("uploadFile").files[0];

    if(!file)
        return;

    const category =
        document.getElementById("category").value;

    const subfolder =
        document.getElementById("uploadSubfolder").value.trim().replace(/^\/|\/$/g, '');

    // Full category path including optional subfolder
    const categoryPath = subfolder ? `${category}/${subfolder}` : category;

    const form = new FormData();
    form.append("file", file);

    const res = await fetch(
        `/api/assets/upload?category=${encodeURIComponent(categoryPath)}`,
        { method:"POST", body:form }
    );

    const result = await res.json();

    await loadAssets();

    // ID is relative path within category: "subfolder/filename" or just "filename"
    const bareId = file.name.replace(/\.glb$/i, '');
    const assetId = subfolder ? `${subfolder}/${bareId}` : bareId;

    meshbank[assetId] = {
        display_name: bareId,
        category,
        subfolder: subfolder || null,
        mesh: result.path,
        tags: [],
        anchors: {}
    };

    await saveMeshbank();
    alert("Uploaded: " + assetId);
};


function clearMarkers(){

    for(
        const marker
        of anchorMarkers
    ){

        scene.remove(
            marker
        );
    }

    for(
        const marker
        of targetMarkers
    ){

        scene.remove(
            marker
        );
    }

    anchorMarkers.length = 0;
    targetMarkers.length = 0;
}
function addMarker(
    parent,
    position,
    label,
    color
){

    const sphere =
        new THREE.Mesh(

    new THREE.SphereGeometry(
        0.1,
        16,
        16
    ),

    new THREE.MeshBasicMaterial({

                color
            })
        );
    sphere.position.copy(
        position
    );

    parent.add(
        sphere
    );


    return sphere;
}

function populateAnimations(
    animations
){

    const container =
        document.getElementById(
            "animations"
        );

    container.innerHTML = "";

    if(
        !animations.length
    ){
        return;
    }

    for(const clip of animations){


        const btn =
            document.createElement(
                "button"
            );

        btn.textContent =
            clip.name;

        btn.onclick = ()=>{

            if (mixer != null && mixer != undefined) {
                mixer.stopAllAction();
                mixer.clipAction(
                        clip
                    )
                    .play();
            }

  
        };

        container.appendChild(
            btn
        );
    }
}
function normalizeModel(model){

    const box =
        new THREE.Box3()
            .setFromObject(model);

    const center =
        box.getCenter(
            new THREE.Vector3()
        );

    const minY =
        box.min.y;

    model.position.set(

        -center.x,

        -minY,

        -center.z
    );

    model.updateMatrixWorld(
        true
    );
}
function frameCamera(model){

    const box =
        new THREE.Box3()
            .setFromObject(model);

    const size =
        box.getSize(
            new THREE.Vector3()
        );

    const center =
        box.getCenter(
            new THREE.Vector3()
        );

    const maxDim =
        Math.max(

            size.x,

            size.y,

            size.z
        );

    camera.position.set(

        center.x + maxDim * 1.8,

        center.y + maxDim * 1.3,

        center.z + maxDim * 1.8
    );

    controls.target.copy(
        center
    );

    controls.update();
}
function updateStats(model){

    const box =
        new THREE.Box3()
            .setFromObject(model);

    const size =
        box.getSize(
            new THREE.Vector3()
        );

    const maxDim =
        Math.max(

            size.x,

            size.y,

            size.z
        );

    document
    .getElementById(
        "stats"
    )
    .innerHTML = `

        Size X:
        ${size.x.toFixed(2)}<br>

        Size Y:
        ${size.y.toFixed(2)}<br>

        Size Z:
        ${size.z.toFixed(2)}<br>

        Largest:
        ${maxDim.toFixed(2)}
    `;
}

// ── Placeholder mesh (shown when a GLB is missing/fails to load) ───────────────
function showPlaceholderMesh(err) {
    clearCurrentModel();
    // Orange semi-transparent box body + wireframe overlay + question-mark head
    const bodyGeo  = new THREE.BoxGeometry(0.8, 1.7, 0.5);
    const bodyMat  = new THREE.MeshStandardMaterial({ color:0xff6600, opacity:0.4, transparent:true });
    const body     = new THREE.Mesh(bodyGeo, bodyMat);
    body.add(new THREE.Mesh(bodyGeo, new THREE.MeshBasicMaterial({ color:0xff9900, wireframe:true })));
    body.position.y = 0.85;

    const headGeo  = new THREE.SphereGeometry(0.25, 10, 8);
    const headMat  = new THREE.MeshStandardMaterial({ color:0xff6600, opacity:0.4, transparent:true });
    const head     = new THREE.Mesh(headGeo, headMat);
    head.add(new THREE.Mesh(headGeo, new THREE.MeshBasicMaterial({ color:0xff9900, wireframe:true })));
    head.position.y = 1.95;

    const grp = new THREE.Group();
    grp.add(body);
    grp.add(head);
    currentModel = grp;
    scene.add(currentModel);
    frameCamera(currentModel);

    document.getElementById('stats').innerHTML =
        '<span style="color:#ff8844">⚠ Model file not found</span><br>' +
        '<span style="color:#664422;font-size:10px">' + (err?.message || err || 'GLB missing') + '</span>';
}

function updateBoxHelper(model){

    if(currentBoxHelper){

        scene.remove(
            currentBoxHelper
        );
    }

    currentBoxHelper =
        new THREE.Box3Helper(

            new THREE.Box3()
                .setFromObject(model),

            0xffff00
        );

    scene.add(
        currentBoxHelper
    );
}

function extractBones(root){

    const bones = {};

    root.traverse(node=>{

        if(node.isBone){

            bones[node.name] = {

                name: node.name
            };
        }
    });

    return bones;
}
function extractTargets(root){

    const targets = {};

    root.traverse(node=>{

        if(
            node.name
                .toLowerCase()
                .startsWith(
                    "target_"
                )
        ){

            targets[
                node.name
            ] = {

                name:
                    node.name
            };
        }
    });

    return targets;
}

function extractAnimations(
    gltf
){

    const result = {};

    for(
        const clip
        of gltf.animations
    ){

        result[
            clip.name
        ] = {

            duration:
                clip.duration
        };
    }

    return result;
}


function detectSkeleton(
    root
){

    let found = false;

    root.traverse(node=>{

        if(node.isBone){

            found = true;
        }
    });

    return found;
}

function extractBounds(
    root
){

    root.updateMatrixWorld(
        true
    );

    const box =
        new THREE.Box3()
            .setFromObject(
                root
            );

    const size =
        box.getSize(
            new THREE.Vector3()
        );

    return {

        width:
            size.x,

        height:
            size.y,

        depth:
            size.z
    };
}

function applyTransform(
    object,
    transform
){

    if(!transform)
        return;

    object.position.set(

        transform.position?.x ?? 0,

        transform.position?.y ?? 0,

        transform.position?.z ?? 0
    );

    object.rotation.set(

        THREE.MathUtils.degToRad(

            transform.rotation?.x ?? 0
        ),

        THREE.MathUtils.degToRad(

            transform.rotation?.y ?? 0
        ),

        THREE.MathUtils.degToRad(

            transform.rotation?.z ?? 0
        )
    );

    object.scale.set(

        transform.scale?.x ?? 1,

        transform.scale?.y ?? 1,

        transform.scale?.z ?? 1
    );
}

function loadModel(url){

    clearCurrentModel();
    clearMarkers();
    document
    .getElementById(
        "anchorList"
    )
    .innerHTML = "";

    loader.load(

        url,

        gltf=>{

            currentModel =
                gltf.scene;

                if(currentAssetId){

                    meshbank[
                        currentAssetId
                    ] ||= {};

console.log(
    gltf.scene
);

gltf.scene.traverse(node=>{

    if(node.isMesh){

        node.visible = true;

        node.frustumCulled = false;

    }
});

    meshbank[
        currentAssetId
    ].anchors =
        extractAnchors(
            gltf.scene
        );

        const bones =
    extractBones(
        gltf.scene
    );

meshbank[
    currentAssetId
].bones = bones;

meshbank[currentAssetId].hasSkeleton =
    detectSkeleton(
        gltf.scene
    );
}

meshbank[
    currentAssetId
].targets =
    extractTargets(
        gltf.scene
    );

populateAnchors();

populateTargets();

populateBones();
populateInteractionAnchors();

populateInteractionTargets();

populateInteractions();

scene.add(
    currentModel
);

normalizeModel(
    currentModel
);

const transform =
    meshbank[
        currentAssetId
    ]?.transform;

if(transform){

    applyTransform(
        currentModel,
        transform
    );
}

updateStats(
    currentModel
);

updateBoxHelper(
    currentModel
);

frameCamera(
    currentModel
);
loadTransformUI();

loadPlacementUI();

updatePivotMarker();
            buildHierarchy(
                currentModel
            );
if(currentSkeletonHelper){

    scene.remove(
        currentSkeletonHelper
    );
}

if(
    detectSkeleton(
        currentModel
    )
){

    currentSkeletonHelper =
        new THREE.SkeletonHelper(
            currentModel
        );

    scene.add(
        currentSkeletonHelper
    );
}

currentModel.traverse(node=>{

    const name =
        (
            node.name
            || ""
        )
        .toLowerCase();

    if(
        name.startsWith(
            "anchor_"
        )
    ){

       const marker =
    addMarker(

        node,

        new THREE.Vector3(),

        node.name,

        0x00ff00
    );

        anchorMarkers.push(
            marker
        );
    }
});
currentModel.traverse(node=>{

    const name =
        (
            node.name
            || ""
        )
        .toLowerCase();

    if(
        name.startsWith(
            "target_"
        )
    ){

const marker =
    addMarker(

        node,

        new THREE.Vector3(),

        node.name,

        0x0088ff
    );
        targetMarkers.push(
            marker
        );
    }
});



            currentAnimations =
                gltf.animations;

            if(
                currentAnimations.length
            ){

                mixer =
                    new THREE.AnimationMixer(
                        currentModel
                    );

                populateAnimations(
                    currentAnimations
                );
            }
        },

        undefined,

        err => {
            console.warn('GLB load failed:', url, err);
            showPlaceholderMesh(err);
        }
    );
}
function populateAnchors(){
    selectedAnchorKey = null;
    renderAnchorList();
    _rebuildAnchorMarkers();
}

function populateTargets(){
    selectedTargetKey = null;
    renderTargetList();
    _rebuildTargetMarkers();
}

function populateBones(){

    const container =
        document.getElementById(
            "bones"
        );

    if(!container) return;

    container.innerHTML = "";

    const bones =
        meshbank[
            currentAssetId
        ]?.bones || {};

    for(
        const name
        in bones
    ){

        const row =
            document.createElement(
                "div"
            );

        row.className = "assetRow";

        row.textContent = name;

        container.appendChild(
            row
        );
    }
}
function makeAxisLabel(
    text
){

    const canvas =
        document.createElement(
            "canvas"
        );

    canvas.width = 128;
    canvas.height = 128;

    const ctx =
        canvas.getContext("2d");

    ctx.fillStyle =
        "white";

    ctx.font =
        "90px Arial";

    ctx.textAlign =
        "center";

    ctx.fillText(
        text,
        64,
        96
    );

    const texture =
        new THREE.CanvasTexture(
            canvas
        );

    const sprite =
        new THREE.Sprite(

            new THREE.SpriteMaterial({

                map:
                    texture
            })
        );

    sprite.scale.set(
        0.35,
        0.35,
        0.35
    );

    return sprite;
}
function buildOrientationGizmo(){

    const origin =
        new THREE.Vector3();

    const length = 1;

    const xArrow =
        new THREE.ArrowHelper(

            new THREE.Vector3(
                1,0,0
            ),

            origin,

            length,

            0xff0000
        );

    const yArrow =
        new THREE.ArrowHelper(

            new THREE.Vector3(
                0,1,0
            ),

            origin,

            length,

            0x00ff00
        );

    const zArrow =
        new THREE.ArrowHelper(

            new THREE.Vector3(
                0,0,1
            ),

            origin,

            length,

            0x0000ff
        );
const yLabel =
    makeAxisLabel("Y");

yLabel.position.set(
    0,
    1.25,
    0
);

const zLabel =
    makeAxisLabel("Z");

zLabel.position.set(
    0,
    0,
    1.25
);


const xLabel =
    makeAxisLabel("X");

xLabel.position.set(
    1.25,
    0,
    0
);
gizmoRoot.add(

    xArrow,
    yArrow,
    zArrow,

    xLabel,
    yLabel,
    zLabel
);
}
function buildHierarchy(
    root
){

    const hierarchy =
        document.getElementById(
            "hierarchy"
        );

    hierarchy.innerHTML = "";

    root.traverse(node=>{

        const row =
            document.createElement(
                "div"
            );

        row.textContent =
            node.name
            || "(unnamed)";

        hierarchy.appendChild(
            row
        );
    });
}
const clock =
    new THREE.Clock();

function animate(){

    requestAnimationFrame(
        animate
    );

    controls.update();

const size =
    renderer.getSize(
        new THREE.Vector2()
    );

renderer.setViewport(

    0,
    0,

    size.x,

    size.y
);

    renderer.render(
        scene,
        camera
    );

    // ==================================
    // GIZMO ROTATION
    // ==================================

    gizmoRoot.quaternion.copy(
        camera.quaternion
    );

    gizmoRoot.quaternion.invert();

    const viewportSize =
        renderer.getSize(
            new THREE.Vector2()
        );

    renderer.clearDepth();

const gizmoSize = 140;

renderer.setViewport(

    viewportSize.x - gizmoSize - 10,

    viewportSize.y - gizmoSize - 10,

    gizmoSize,

    gizmoSize
);

    renderer.render(

        gizmoScene,

        gizmoCamera
    );

    renderer.setViewport(

        0,
        0,

        viewportSize.x,

        viewportSize.y
    );
}

window.addEventListener(
    "resize",
    ()=>{

        const width =
            window.innerWidth - 300;

        const height =
            window.innerHeight;

        camera.aspect =
            width / height;

        camera.updateProjectionMatrix();

        renderer.setSize(
            width,
            height
        );
    }
);
animate();

await loadMeshbank();

await loadAssets();

// Default to props (most common category)
document.getElementById("category").value = "props";
populateAssetList();
pivot.onchange = ()=>{

    updatePlacementFromUI();

    updatePivotMarker();
};

snapGround.onchange = ()=>{

    updatePlacementFromUI();

    updatePivotMarker();
};

snapGrid.onchange = ()=>{

    updatePlacementFromUI();

    updatePivotMarker();
};
[
    posX,
    posY,
    posZ,

    rotX,
    rotY,
    rotZ,

    scaleX,
    scaleY,
    scaleZ
]
.forEach(input=>{

    input.addEventListener(

        "input",

        updateTransformFromUI
    );
});
document
.getElementById(
    "resetTransformBtn"
)
.onclick = ()=>{

    if(!currentAssetId)
        return;

    meshbank[
        currentAssetId
    ].transform = {

        position:{
            x:0,
            y:0,
            z:0
        },

        rotation:{
            x:0,
            y:0,
            z:0
        },

        scale:{
            x:1,
            y:1,
            z:1
        }
    };

    loadTransformUI();

    applyTransform(

        currentModel,

        meshbank[
            currentAssetId
        ].transform
    );
};
document
.getElementById(
    "frameBtn"
)
.onclick = ()=>{

    if(currentModel){

frameCamera(
    currentModel
);
    }
};


function ensureBoneSlots(asset) {
    asset.bone_slots ||= {};
    return asset.bone_slots;
}

function populateSlots() {
    const select = document.getElementById("slotSelect");
    select.innerHTML = "";
    if (!currentAssetId) return;
    const slots = ensureBoneSlots(meshbank[currentAssetId]);
    for (const name in slots) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    }
    populateSlotBones();
}

addSlotBtn.onclick =
()=>{

    const name =
        prompt(
            "Slot Name"
        );

    if(!name)
        return;

    const slots =
        ensureBoneSlots(

            meshbank[
                currentAssetId
            ]
        );

    slots[name] = "";

    populateSlots();
};
document
.getElementById(
    "saveMetaBtn"
)
.onclick = async ()=>{

    if(!currentAssetId)
        return;

    meshbank[
        currentAssetId
    ].display_name =

        document
        .getElementById(
            "displayName"
        )
        .value;

    meshbank[
        currentAssetId
    ].tags =

        document
        .getElementById(
            "tags"
        )
        .value

        .split(",")

        .map(
            s => s.trim()
        )

        .filter(Boolean);
    meshbank[
        currentAssetId
    ].anchors ||= {};
    await saveMeshbank();
    
await loadMeshbank();
};
document
.getElementById(
    "addInteractionBtn"
)
.onclick = ()=>{

    const name =
        prompt(
            "Interaction Name"
        );

    if(!name)
        return;

    const interactions =
        ensureInteractions(

            meshbank[
                currentAssetId
            ]
        );

    interactions[name] = {

        anchor: "",

        target: "",

        max_distance: 1,

        required_item: ""
    };

    populateInteractions();
};
document
.getElementById(
    "interactionSelect"
)
.onchange = ()=>{

    const id =
        interactionSelect.value;

    const data =

        ensureInteractions(
            meshbank[
                currentAssetId
            ]
        )[id];

    interactionName.value =
        id;

    interactionAnchor.value =
        data.anchor || "";

    interactionTarget.value =
        data.target || "";

    interactionDistance.value =
        data.max_distance || 1;

    interactionItem.value =
        data.required_item || "";
};
function updateInteraction(){

    const id =
        interactionSelect.value;

    if(!id)
        return;

    const interaction =

        ensureInteractions(
            meshbank[
                currentAssetId
            ]
        )[id];

    interaction.anchor =
        interactionAnchor.value;

    interaction.target =
        interactionTarget.value;

    interaction.max_distance =
        parseFloat(
            interactionDistance.value
        ) || 1;

    interaction.required_item =
        interactionItem.value;
}
interactionAnchor.onchange =
    updateInteraction;

interactionTarget.onchange =
    updateInteraction;

interactionDistance.oninput =
    updateInteraction;

interactionItem.oninput =
    updateInteraction;
    document
.getElementById(
    "deleteInteractionBtn"
)
.onclick = ()=>{

    const id =
        interactionSelect.value;

    if(!id)
        return;

    delete ensureInteractions(

        meshbank[
            currentAssetId
        ]
    )[id];

    populateInteractions();
};
document
.getElementById(
    "generateMetaBtn"
)
.onclick = async ()=>{

    if(
        !currentAssetId ||
        !currentModel
    ){
        return;
    }

    meshbank[
        currentAssetId
    ] ||= {};

    meshbank[
        currentAssetId
    ].anchors =
        extractAnchors(
            currentModel
        );

    meshbank[
        currentAssetId
    ].bones =
        extractBones(
            currentModel
        );

    meshbank[
        currentAssetId
    ].targets =
        extractTargets(
            currentModel
        );

    meshbank[
        currentAssetId
    ].animations =
        extractAnimations({

            animations:
                currentAnimations
        });

    meshbank[
        currentAssetId
    ].bounds =
        extractBounds(
            currentModel
        );

    meshbank[
        currentAssetId
    ].hasSkeleton =
        detectSkeleton(
            currentModel
        );

    await saveMeshbank();
    populateAnchors();
    populateTargets();
    populateBones();
    alert(
        "Metadata generated"
    );
};
// =====================================================
// ANCHOR / TARGET CRUD
// =====================================================

let selectedAnchorKey = null;
let selectedTargetKey = null;
let placingMode = null; // 'anchor' | 'target' | null
const placeRaycaster = new THREE.Raycaster();

// ── Shared helpers ────────────────────────────────────────────────────────────
function ensureAnchors(asset) { asset.anchors ||= {}; return asset.anchors; }
function ensureTargets(asset) { asset.targets ||= {}; return asset.targets; }

function getCanvasNDC(e) {
  const r = canvas.getBoundingClientRect();
  return new THREE.Vector2(
    ((e.clientX - r.left) / r.width)  *  2 - 1,
    ((e.clientY - r.top)  / r.height) * -2 + 1
  );
}

// ── 3D markers ────────────────────────────────────────────────────────────────
let _anchorMarker3D = {};  // key -> {sphere, arrow}
let _targetMarker3D = {};  // key -> sphere

function _removeAnchorMarkers() {
  Object.values(_anchorMarker3D).forEach(g => scene.remove(g));
  _anchorMarker3D = {};
}
function _removeTargetMarkers() {
  Object.values(_targetMarker3D).forEach(g => scene.remove(g));
  _targetMarker3D = {};
}

function _rebuildAnchorMarkers() {
  _removeAnchorMarkers();
  if (!currentAssetId) return;
  const anchors = ensureAnchors(meshbank[currentAssetId]);
  const geoS = new THREE.SphereGeometry(0.08, 12, 12);
  for (const [key, a] of Object.entries(anchors)) {
    const pos = a.position || { x: 0, y: 0, z: 0 };
    const isSelected = key === selectedAnchorKey;
    const mat = new THREE.MeshBasicMaterial({ color: isSelected ? 0x00ff88 : 0x00cc44 });
    const sphere = new THREE.Mesh(geoS, mat);
    sphere.position.set(pos.x, pos.y, pos.z);
    // Arrow showing facing direction
    const ry = THREE.MathUtils.degToRad(a.rotation_y || 0);
    const dir = new THREE.Vector3(Math.sin(ry), 0, Math.cos(ry)).normalize();
    const arrow = new THREE.ArrowHelper(dir, sphere.position, a.distance || 1.0, isSelected ? 0x00ff88 : 0x00cc44, 0.15, 0.1);
    const group = new THREE.Group();
    group.add(sphere, arrow);
    scene.add(group);
    _anchorMarker3D[key] = group;
  }
}

function _rebuildTargetMarkers() {
  _removeTargetMarkers();
  if (!currentAssetId) return;
  const targets = ensureTargets(meshbank[currentAssetId]);
  const geoS = new THREE.SphereGeometry(0.08, 12, 12);
  for (const [key, t] of Object.entries(targets)) {
    const pos = t.position || { x: 0, y: 0, z: 0 };
    const isSelected = key === selectedTargetKey;
    const mat = new THREE.MeshBasicMaterial({ color: isSelected ? 0x44aaff : 0x0066cc });
    const sphere = new THREE.Mesh(geoS, mat);
    sphere.position.set(pos.x, pos.y, pos.z);
    scene.add(sphere);
    _targetMarker3D[key] = sphere;
  }
}

// ── Anchor list + editor ──────────────────────────────────────────────────────
function renderAnchorList() {
  const list = document.getElementById('anchorList');
  if (!list) return;
  const anchors = currentAssetId ? ensureAnchors(meshbank[currentAssetId]) : {};
  list.innerHTML = '';
  for (const key of Object.keys(anchors)) {
    const row = document.createElement('div');
    row.className = 'assetRow' + (key === selectedAnchorKey ? ' active' : '');
    row.textContent = key;
    row.onclick = () => { selectedAnchorKey = key; renderAnchorList(); loadAnchorEditor(); _rebuildAnchorMarkers(); };
    list.appendChild(row);
  }
  const ed = document.getElementById('anchorEditor');
  if (ed) ed.style.display = selectedAnchorKey ? '' : 'none';
}

function loadAnchorEditor() {
  if (!currentAssetId || !selectedAnchorKey) return;
  const a = ensureAnchors(meshbank[currentAssetId])[selectedAnchorKey] || {};
  const pos = a.position || { x: 0, y: 0, z: 0 };
  document.getElementById('anchorName').value      = a.name || selectedAnchorKey;
  document.getElementById('anchorPosX').value      = pos.x ?? 0;
  document.getElementById('anchorPosY').value      = pos.y ?? 0;
  document.getElementById('anchorPosZ').value      = pos.z ?? 0;
  document.getElementById('anchorRotY').value      = a.rotation_y ?? 0;
  document.getElementById('anchorDist').value      = a.distance  ?? 1.2;
  document.getElementById('anchorInteraction').value = a.interaction || '';
}

function saveAnchorEdits() {
  if (!currentAssetId || !selectedAnchorKey) return;
  const anchors = ensureAnchors(meshbank[currentAssetId]);
  const newName = document.getElementById('anchorName').value.trim() || selectedAnchorKey;
  const data = {
    name:        newName,
    position: {
      x: parseFloat(document.getElementById('anchorPosX').value) || 0,
      y: parseFloat(document.getElementById('anchorPosY').value) || 0,
      z: parseFloat(document.getElementById('anchorPosZ').value) || 0,
    },
    rotation_y:  parseFloat(document.getElementById('anchorRotY').value) || 0,
    distance:    parseFloat(document.getElementById('anchorDist').value)  || 1.2,
    interaction: document.getElementById('anchorInteraction').value.trim(),
  };
  // Handle rename
  if (newName !== selectedAnchorKey) {
    delete anchors[selectedAnchorKey];
    selectedAnchorKey = newName;
  }
  anchors[selectedAnchorKey] = data;
  renderAnchorList();
  _rebuildAnchorMarkers();
}

// ── Target list + editor ──────────────────────────────────────────────────────
function renderTargetList() {
  const list = document.getElementById('targetList');
  if (!list) return;
  const targets = currentAssetId ? ensureTargets(meshbank[currentAssetId]) : {};
  list.innerHTML = '';
  for (const key of Object.keys(targets)) {
    const row = document.createElement('div');
    row.className = 'assetRow' + (key === selectedTargetKey ? ' active' : '');
    row.textContent = key;
    row.onclick = () => { selectedTargetKey = key; renderTargetList(); loadTargetEditor(); _rebuildTargetMarkers(); };
    list.appendChild(row);
  }
  const ed = document.getElementById('targetEditor');
  if (ed) ed.style.display = selectedTargetKey ? '' : 'none';
}

function loadTargetEditor() {
  if (!currentAssetId || !selectedTargetKey) return;
  const t = ensureTargets(meshbank[currentAssetId])[selectedTargetKey] || {};
  const pos = t.position || { x: 0, y: 0, z: 0 };
  document.getElementById('targetName').value    = t.name || selectedTargetKey;
  document.getElementById('targetPosX').value    = pos.x ?? 0;
  document.getElementById('targetPosY').value    = pos.y ?? 0;
  document.getElementById('targetPosZ').value    = pos.z ?? 0;
  document.getElementById('targetType').value    = t.type || '';
}

function saveTargetEdits() {
  if (!currentAssetId || !selectedTargetKey) return;
  const targets = ensureTargets(meshbank[currentAssetId]);
  const newName = document.getElementById('targetName').value.trim() || selectedTargetKey;
  const data = {
    name: newName,
    position: {
      x: parseFloat(document.getElementById('targetPosX').value) || 0,
      y: parseFloat(document.getElementById('targetPosY').value) || 0,
      z: parseFloat(document.getElementById('targetPosZ').value) || 0,
    },
    type: document.getElementById('targetType').value.trim(),
  };
  if (newName !== selectedTargetKey) {
    delete targets[selectedTargetKey];
    selectedTargetKey = newName;
  }
  targets[selectedTargetKey] = data;
  renderTargetList();
  _rebuildTargetMarkers();
}

// ── Place-at-click ────────────────────────────────────────────────────────────
canvas.addEventListener('click', e => {
  if (!placingMode || !currentModel) return;
  placeRaycaster.setFromCamera(getCanvasNDC(e), camera);
  const hits = placeRaycaster.intersectObject(currentModel, true);
  if (!hits.length) return;
  const p = hits[0].point;
  if (placingMode === 'anchor') {
    document.getElementById('anchorPosX').value = p.x.toFixed(3);
    document.getElementById('anchorPosY').value = p.y.toFixed(3);
    document.getElementById('anchorPosZ').value = p.z.toFixed(3);
    saveAnchorEdits();
  } else {
    document.getElementById('targetPosX').value = p.x.toFixed(3);
    document.getElementById('targetPosY').value = p.y.toFixed(3);
    document.getElementById('targetPosZ').value = p.z.toFixed(3);
    saveTargetEdits();
  }
  placingMode = null;
  canvas.style.cursor = '';
  document.getElementById('placeAnchorBtn') && (document.getElementById('placeAnchorBtn').textContent = 'Place at click');
  document.getElementById('placeTargetBtn') && (document.getElementById('placeTargetBtn').textContent = 'Place at click');
});

// ── Wire up buttons ───────────────────────────────────────────────────────────
document.getElementById('addAnchorBtn').onclick = () => {
  if (!currentAssetId) return;
  let n = 'anchor_' + Date.now().toString(36);
  ensureAnchors(meshbank[currentAssetId])[n] = { name: n, position: { x:0,y:0,z:0 }, rotation_y:0, distance:1.2, interaction:'' };
  selectedAnchorKey = n;
  renderAnchorList();
  loadAnchorEditor();
  _rebuildAnchorMarkers();
};
document.getElementById('removeAnchorBtn').onclick = () => {
  if (!currentAssetId || !selectedAnchorKey) return;
  delete ensureAnchors(meshbank[currentAssetId])[selectedAnchorKey];
  selectedAnchorKey = null;
  renderAnchorList();
  _rebuildAnchorMarkers();
};
document.getElementById('addTargetBtn').onclick = () => {
  if (!currentAssetId) return;
  let n = 'target_' + Date.now().toString(36);
  ensureTargets(meshbank[currentAssetId])[n] = { name: n, position: { x:0,y:1,z:0 }, type:'' };
  selectedTargetKey = n;
  renderTargetList();
  loadTargetEditor();
  _rebuildTargetMarkers();
};
document.getElementById('removeTargetBtn').onclick = () => {
  if (!currentAssetId || !selectedTargetKey) return;
  delete ensureTargets(meshbank[currentAssetId])[selectedTargetKey];
  selectedTargetKey = null;
  renderTargetList();
  _rebuildTargetMarkers();
};
document.getElementById('placeAnchorBtn').onclick = () => {
  if (!selectedAnchorKey) return;
  placingMode = placingMode === 'anchor' ? null : 'anchor';
  canvas.style.cursor = placingMode ? 'crosshair' : '';
  document.getElementById('placeAnchorBtn').textContent = placingMode ? 'Click model to place...' : 'Place at click';
};
document.getElementById('placeTargetBtn').onclick = () => {
  if (!selectedTargetKey) return;
  placingMode = placingMode === 'target' ? null : 'target';
  canvas.style.cursor = placingMode ? 'crosshair' : '';
  document.getElementById('placeTargetBtn').textContent = placingMode ? 'Click model to place...' : 'Place at click';
};

// Live-update on input
['anchorName','anchorPosX','anchorPosY','anchorPosZ','anchorRotY','anchorDist','anchorInteraction']
  .forEach(id => { const el = document.getElementById(id); if (el) el.addEventListener('input', saveAnchorEdits); });
['targetName','targetPosX','targetPosY','targetPosZ','targetType']
  .forEach(id => { const el = document.getElementById(id); if (el) el.addEventListener('input', saveTargetEdits); });

// ══════════════════════════════════════════════════════════════════════════════
// HAIR ATTACH POINT
// ══════════════════════════════════════════════════════════════════════════════

function ensureHairAttach(asset) {
    asset.hair_attach ||= {
        bone: '',
        offset: { x: 0, y: 0, z: 0 },
        rotation: { x: 0, y: 0, z: 0 },
    };
    return asset.hair_attach;
}

function loadHairAttachUI() {
    if (!currentAssetId) return;
    const asset = meshbank[currentAssetId];
    if (!asset) return;
    const ha = asset.hair_attach || {};

    // Populate bone selector with bones extracted from the loaded model
    const boneSelect = document.getElementById('hairAttachBone');
    boneSelect.innerHTML = '<option value="">-- none --</option>';
    const bones = asset.bones || {};
    for (const boneName in bones) {
        const opt = document.createElement('option');
        opt.value = boneName;
        opt.textContent = boneName;
        if (boneName === ha.bone) opt.selected = true;
        boneSelect.appendChild(opt);
    }
    if (ha.bone) boneSelect.value = ha.bone;

    const off = ha.offset || {};
    const rot = ha.rotation || {};
    document.getElementById('hairAttachOffX').value = off.x ?? 0;
    document.getElementById('hairAttachOffY').value = off.y ?? 0;
    document.getElementById('hairAttachOffZ').value = off.z ?? 0;
    document.getElementById('hairAttachRotX').value = rot.x ?? 0;
    document.getElementById('hairAttachRotY').value = rot.y ?? 0;
    document.getElementById('hairAttachRotZ').value = rot.z ?? 0;
}

function saveHairAttach() {
    if (!currentAssetId) return;
    const asset = meshbank[currentAssetId] ||= {};
    const ha = ensureHairAttach(asset);
    ha.bone     = document.getElementById('hairAttachBone').value;
    ha.offset   = {
        x: parseFloat(document.getElementById('hairAttachOffX').value) || 0,
        y: parseFloat(document.getElementById('hairAttachOffY').value) || 0,
        z: parseFloat(document.getElementById('hairAttachOffZ').value) || 0,
    };
    ha.rotation = {
        x: parseFloat(document.getElementById('hairAttachRotX').value) || 0,
        y: parseFloat(document.getElementById('hairAttachRotY').value) || 0,
        z: parseFloat(document.getElementById('hairAttachRotZ').value) || 0,
    };
}

document.getElementById('saveHairAttachBtn').onclick = async () => {
    saveHairAttach();
    await saveMeshbank();
    document.getElementById('saveHairAttachBtn').textContent = 'Saved ✓';
    setTimeout(() => { document.getElementById('saveHairAttachBtn').textContent = 'Save Hair Attach'; }, 1500);
};
