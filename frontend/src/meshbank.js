import * as THREE from "three";

import { OrbitControls }
from "three/examples/jsm/controls/OrbitControls.js";

import { GLTFLoader }
from "three/examples/jsm/loaders/GLTFLoader.js";

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

let mixer = null;

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

            loadModel(asset);
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

    for(const helper of anchorHelpers){

        scene.remove(
            helper
        );
    }

    anchorHelpers = [];

    mixer = null;
}

function addAnchorMarker(
    position,
    name
){

    const sphere =
        new THREE.Mesh(

            new THREE.SphereGeometry(
                0.05
            ),

            new THREE.MeshBasicMaterial({

                color:0xff0000
            })
        );

    sphere.position.copy(
        position
    );

    scene.add(
        sphere
    );

    anchorHelpers.push(
        sphere
    );

    const axes =
        new THREE.AxesHelper(
            0.25
        );

    axes.position.copy(
        position
    );

    scene.add(
        axes
    );

    anchorHelpers.push(
        axes
    );

    const row =
        document.createElement(
            "button"
        );

    row.textContent =
        name;

    row.onclick = ()=>{

        camera.position.copy(

            position.clone().add(

                new THREE.Vector3(
                    0.5,
                    0.5,
                    0.5
                )
            )
        );

        controls.target.copy(
            position
        );

        controls.update();
    };

    document
    .getElementById(
        "anchors"
    )
    .appendChild(
        row
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

            mixer.stopAllAction();

            mixer
            .clipAction(
                clip
            )
            .play();
        };

        container.appendChild(
            btn
        );
    }
}

function frameModel(model){

    const box =
        new THREE.Box3()
        .setFromObject(
            model
        );

    const center =
        box.getCenter(
            new THREE.Vector3()
        );

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

    model.position.sub(
        center
    );

    camera.position.set(

        maxDim * 1.8,

        maxDim * 1.3,

        maxDim * 1.8
    );

    controls.target.set(

        0,

        maxDim * 0.25,

        0
    );

    controls.update();

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

function loadModel(url){

    clearCurrentModel();

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

            scene.add(
                currentModel
            );

            frameModel(
            currentModel
            );

            buildHierarchy(
                currentModel
            );

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

                    addAnchorMarker(
                        pos,
                        node.name
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

loadAssets();

document
.getElementById(
    "frameBtn"
)
.onclick = ()=>{

    if(currentModel){

        frameModel(
            currentModel
        );
    }
};