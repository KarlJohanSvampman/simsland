import * as THREE from "three";

import { OrbitControls }
from "three/examples/jsm/controls/OrbitControls.js";

import { GLTFLoader }
from "three/examples/jsm/loaders/GLTFLoader.js";

const anchorMarkers = [];
const targetMarkers = [];
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

renderer.setSize(
    window.innerWidth - 300,
    window.innerHeight
);

const scene =
    new THREE.Scene();

scene.background =
    new THREE.Color(
        0x20242a
    );

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

    for(const asset of assets[category] || []){

        const div =
            document.createElement(
                "div"
            );

        div.className =
            "assetRow";

        div.textContent =
            asset.split("/")
            .pop();

        div.onclick = ()=>{

    currentAssetId =
        asset
            .split("/")
            .pop()
            .replace(".glb","");

            loadModel(asset);

            const meta =
                meshbank[currentAssetId];

            document
            .getElementById(
                "displayName"
            )
            .value =
                meta?.display_name || "";

            document
            .getElementById(
                "tags"
            )
            .value =
                (
                    meta?.tags || []
                ).join(",");
        };

        container.appendChild(
            div
        );
    }
}

document
.getElementById(
    "category"
)
.onchange =
populateAssetList;

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

        document
        .getElementById(
            "uploadFile"
        )
        .files[0];

    if(!file)
        return;

    const category =
        document
        .getElementById(
            "category"
        )
        .value;

    const form =
        new FormData();

    form.append(
        "file",
        file
    );

    const res =
        await fetch(

            `/api/assets/upload?category=${category}`,

            {
                method:"POST",
                body:form
            }
        );

    const result =
        await res.json();

    alert(
        "Uploaded"
    );

    await loadAssets();

    const assetId = file.name.replace(".glb","");
    const meta = meshbank[assetId];
    const tags = [];

    meshbank[assetId] = {

        display_name:
            assetId,

        category,

        mesh:
            result.path,

        tags,

        anchors: {}
    };
meshbank[
    assetId
].anchors ||= {};
    await saveMeshbank();

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
    position,
    label,
    color = 0x00ff00
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

    scene.add(
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
        "anchors"
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
    const transform =
    meshbank[
        currentAssetId
    ]?.transform;

    if(transform){
        applyTransform(
            currentModel,
            meshbank[
                currentAssetId
            ].transform
        );
}

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

scene.add(
    currentModel
);

normalizeModel(
    currentModel
);

updateStats(
    currentModel
);

updateBoxHelper(
    currentModel
);

frameCamera(
    currentModel
);

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

        const pos =
            new THREE.Vector3();

        node.getWorldPosition(
            pos
        );

        const marker =
            addMarker(

                pos,

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

        const pos =
            new THREE.Vector3();

        node.getWorldPosition(
            pos
        );

        const marker =
            addMarker(

                pos,

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
        }
    );
}
function populateAnchors(){

    const container =
        document.getElementById(
            "anchors"
        );

    container.innerHTML = "";

    const anchors =
        meshbank[
            currentAssetId
        ]?.anchors || {};

    for(
        const name
        in anchors
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

function populateTargets(){

    const container =
        document.getElementById(
            "targets"
        );

    if(!container) return;

    container.innerHTML = "";

    const targets =
        meshbank[
            currentAssetId
        ]?.targets || {};

    for(
        const name
        in targets
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

    const dt =
        clock.getDelta();

    if(mixer){

        mixer.update(
            dt
        );
    }

    controls.update();

    renderer.render(
        scene,
        camera
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