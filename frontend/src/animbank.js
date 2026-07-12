import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader }         from "three/examples/jsm/loaders/GLTFLoader.js";
import { TransformControls }   from "three/examples/jsm/controls/TransformControls.js";

// =========================================================
// CATEGORY REGISTRY
// =========================================================

const CATEGORIES = [
    "idle", "locomotion", "transition",
    "gesture", "action", "reaction",
    "converse", "touch", "phone", "clean",
    "intoxicated", "sex", "altercation",
    "uncategorized",
];

// Categories where a second character should always be shown
const PAIRED_PREVIEW_CATS = new Set(["touch", "sex", "altercation"]);

const CAT_COLOR = {
    idle:          "#5a7a9a",
    locomotion:    "#4aaa7a",
    transition:    "#7a6aaa",
    gesture:       "#6aaa6a",
    action:        "#7a8acc",
    reaction:      "#cc8a6a",
    converse:      "#cccc6a",
    touch:         "#cc8acc",
    phone:         "#5acccc",
    clean:         "#aaccaa",
    intoxicated:   "#cc6a6a",
    sex:           "#cc6a8a",
    altercation:   "#cc4444",
    uncategorized: "#555555",
};

function classifyClip(name) {
    const lower = name.toLowerCase();
    for (const cat of CATEGORIES) {
        if (cat === "uncategorized") continue;
        if (lower.startsWith(cat + "_")) return cat;
    }
    return "uncategorized";
}

// =========================================================
// BONE CLASSIFICATION FOR BLEND MODE
// =========================================================

function getBoneNameFromTrack(trackName) {
    // Handles "[BoneName].prop" and "BoneName.prop" formats
    const m = trackName.match(/\[(.+?)\]/);
    return m ? m[1] : trackName.split('.')[0];
}

function classifyBones(character) {
    const upper = new Set();
    const lower = new Set();
    character.traverse(node => {
        if (!node.isBone) return;
        const stripped = node.name.replace(/mixamorig/i, "");
        // Lower body: hips/pelvis, legs, knees, ankles, feet, toes
        if (/leg|upleg|foot|toe|ankle|knee|hip|pelvis/i.test(stripped)) {
            lower.add(node.name);
        } else {
            upper.add(node.name);
        }
    });
    return { upper, lower };
}

function filterClip(clip, boneNames, nameSuffix) {
    const tracks = clip.tracks.filter(t => boneNames.has(getBoneNameFromTrack(t.name)));
    return new THREE.AnimationClip(clip.name + nameSuffix, clip.duration, tracks);
}

// =========================================================
// IK — BONE DETECTION + TARGET MANAGEMENT
// =========================================================

function getBoneByPattern(character, patterns) {
    let found = null;
    character.traverse(n => {
        if (!n.isBone || found) return;
        const stripped = n.name.replace(/mixamorig/i, "").toLowerCase();
        if (patterns.some(p => stripped.includes(p))) found = n;
    });
    return found;
}

function initIKBones(character) {
    ikBones = {
        right_hand: {
            upper: getBoneByPattern(character, ["rightarm", "r_arm", "r_upperarm"]),
            lower: getBoneByPattern(character, ["rightforearm", "r_forearm", "r_lowerarm"]),
            hand:  getBoneByPattern(character, ["righthand", "r_hand"]),
        },
        left_hand: {
            upper: getBoneByPattern(character, ["leftarm", "l_arm", "l_upperarm"]),
            lower: getBoneByPattern(character, ["leftforearm", "l_forearm", "l_lowerarm"]),
            hand:  getBoneByPattern(character, ["lefthand", "l_hand"]),
        },
        head: {
            neck: getBoneByPattern(character, ["neck"]),
            head: getBoneByPattern(character, ["head"]),
        },
    };
}

function addIKTarget(type) {
    if (ikTargets[type]) return;          // already added
    if (!characterA) return;

    // Determine initial world position from the relevant bone
    const boneRef = {
        right_hand: ikBones.right_hand?.hand,
        left_hand:  ikBones.left_hand?.hand,
        look_at:    ikBones.head?.head,
    }[type] || (type === "both_hands" ? ikBones.right_hand?.hand : null);

    const initPos = new THREE.Vector3();
    if (boneRef) boneRef.getWorldPosition(initPos);
    else initPos.set(0, 1.5, 0.4);

    const color = { right_hand: 0xff4444, left_hand: 0x4444ff,
                    both_hands: 0xff44ff, look_at: 0x44ff88 }[type] || 0xffffff;

    const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.04, 10, 10),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 })
    );
    mesh.position.copy(initPos);
    scene.add(mesh);

    const tc = new TransformControls(camera, rendererInst.domElement);
    tc.setMode("translate");
    tc.setSize(0.6);
    tc.attach(mesh);
    tc.addEventListener("dragging-changed", e => { controls.enabled = !e.value; });
    scene.add(tc);

    ikTargets[type] = { mesh, tc, trackBone: null };
    updateIKTargetListUI();
    showStatus(`IK target added: ${type}`);
}

function removeIKTarget(type) {
    const t = ikTargets[type];
    if (!t) return;
    t.tc.detach();
    scene.remove(t.tc);
    scene.remove(t.mesh);
    t.tc.dispose();
    t.mesh.geometry.dispose();
    delete ikTargets[type];
    updateIKTargetListUI();
}

function setIKTrackBone(type, bone) {
    if (ikTargets[type]) ikTargets[type].trackBone = bone || null;
}

// 2-bone IK: point upper→lower chain at targetWorldPos
function applyReachIK(upper, lower, targetWorldPos) {
    if (!upper || !lower) return;

    // Upper arm: align bone's natural axis toward target
    const uFwd = upper.position.clone().normalize();
    const uWorldPos = new THREE.Vector3();
    upper.getWorldPosition(uWorldPos);
    const uDir = targetWorldPos.clone().sub(uWorldPos).normalize();
    const uPQ = new THREE.Quaternion();
    if (upper.parent) upper.parent.getWorldQuaternion(uPQ);
    const uLocalDir = uDir.clone().applyQuaternion(uPQ.clone().invert());
    upper.quaternion.copy(new THREE.Quaternion().setFromUnitVectors(uFwd, uLocalDir));
    upper.updateWorldMatrix(true, true);

    // Forearm: align toward target from current elbow position
    const lFwd = lower.position.clone().normalize();
    const lWorldPos = new THREE.Vector3();
    lower.getWorldPosition(lWorldPos);
    const lDir = targetWorldPos.clone().sub(lWorldPos).normalize();
    const lPQ = new THREE.Quaternion();
    if (lower.parent) lower.parent.getWorldQuaternion(lPQ);
    const lLocalDir = lDir.clone().applyQuaternion(lPQ.clone().invert());
    lower.quaternion.copy(new THREE.Quaternion().setFromUnitVectors(lFwd, lLocalDir));
    lower.updateWorldMatrix(true, true);
}

function applyLookAtIK(neck, head, targetWorldPos) {
    for (const bone of [neck, head].filter(Boolean)) {
        const fwd = bone.position.clone().normalize();
        if (fwd.lengthSq() < 0.001) continue;
        const wPos = new THREE.Vector3();
        bone.getWorldPosition(wPos);
        const dir = targetWorldPos.clone().sub(wPos).normalize();
        const pq = new THREE.Quaternion();
        if (bone.parent) bone.parent.getWorldQuaternion(pq);
        const localDir = dir.clone().applyQuaternion(pq.clone().invert());
        bone.quaternion.copy(new THREE.Quaternion().setFromUnitVectors(fwd, localDir));
        bone.updateWorldMatrix(true, true);
    }
}

function updateIK() {
    if (!characterA || !Object.keys(ikTargets).length) return;

    for (const [type, t] of Object.entries(ikTargets)) {
        // If tracking a CharB bone, copy its world pos to sphere
        if (t.trackBone) {
            const wp = new THREE.Vector3();
            t.trackBone.getWorldPosition(wp);
            t.mesh.position.copy(wp);
            t.tc.update();
        }

        const target = t.mesh.position.clone();

        if (type === "right_hand") {
            applyReachIK(ikBones.right_hand?.upper, ikBones.right_hand?.lower, target);
        } else if (type === "left_hand") {
            applyReachIK(ikBones.left_hand?.upper, ikBones.left_hand?.lower, target);
        } else if (type === "both_hands") {
            // Both hands share the same target sphere — mirror offset for L
            applyReachIK(ikBones.right_hand?.upper, ikBones.right_hand?.lower, target);
            applyReachIK(ikBones.left_hand?.upper,  ikBones.left_hand?.lower,  target);
        } else if (type === "look_at") {
            applyLookAtIK(ikBones.head?.neck, ikBones.head?.head, target);
        }
    }
}

function updateIKTargetListUI() {
    const el = document.getElementById("ikTargetList");
    if (!el) return;
    el.innerHTML = "";

    const typeLabels = {
        right_hand: "R.Hand", left_hand: "L.Hand",
        both_hands: "Both Hands", look_at: "Look At",
    };

    for (const [type, t] of Object.entries(ikTargets)) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:6px;margin-bottom:3px;font-size:11px";

        const lbl = document.createElement("span");
        lbl.textContent = typeLabels[type] || type;
        lbl.style.color = "#aaa";

        // Optional: track CharB bone
        if (characterB) {
            const sel = document.createElement("select");
            sel.style.cssText = "flex:1;padding:2px 4px;background:#141820;border:1px solid #333;color:#ccc;border-radius:3px;font-size:10px";
            const blank = document.createElement("option");
            blank.value = ""; blank.textContent = "— free —";
            sel.appendChild(blank);
            characterB.traverse(n => {
                if (!n.isBone) return;
                const opt = document.createElement("option");
                opt.value = n.name; opt.textContent = n.name;
                sel.appendChild(opt);
            });
            sel.value = t.trackBone?.name || "";
            sel.addEventListener("change", () => {
                let bone = null;
                if (sel.value) characterB.traverse(n => { if (n.name === sel.value) bone = n; });
                setIKTrackBone(type, bone);
            });
            row.appendChild(lbl);
            row.appendChild(sel);
        } else {
            row.appendChild(lbl);
        }

        const del = document.createElement("button");
        del.textContent = "✕"; del.className = "danger";
        del.style.cssText = "padding:1px 5px;font-size:10px";
        del.addEventListener("click", () => removeIKTarget(type));
        row.appendChild(del);
        el.appendChild(row);
    }
}

// =========================================================
// STATE
// =========================================================

let bank = {};                  // animbank.json
let currentSourceKey = null;    // key in bank
let currentClipMeta  = null;    // clip object from bank

// Three.js
let rendererInst = null;
let scene, camera, controls, clock;
let characterA = null;          // THREE.Group
let mixerA     = null;
let characterB = null;          // second character for paired anims
let mixerB     = null;
let rawClipsA  = [];            // AnimationClip[] from loaded GLB

// Playback state
let activeAction   = null;
let activeActionB  = null;
let isPlaying      = false;
let loopMode       = THREE.LoopRepeat;  // current loop mode
let playSpeed      = 1.0;
let clipFPS        = 30;

// Blend mode state
let blendEnabled      = false;
let boneSets          = { upper: new Set(), lower: new Set() };
let activeActionUpper = null;
let activeActionLower = null;

// Template state
let currentTemplate = null;   // template object being edited / playing
let chainTemplate   = null;   // template currently playing (chain)
let chainIndex      = 0;      // which step in the chain is active
let chainListener   = null;   // mixer 'finished' listener for chain advancement

// IK state
let ikBones   = {};   // { right_hand:{upper,lower,hand}, left_hand:{...}, head:{neck,head} }
let ikTargets = {};   // { right_hand:{mesh,tc,trackBone:null}, ... }

// Notify tracking (fires once per crossing)
let lastMixerTime  = 0;
let notifyFired    = new Set();  // ids fired this pass

const loader = new GLTFLoader();

// =========================================================
// THREE.JS SETUP
// =========================================================

function initThree() {
    const canvas = document.getElementById("canvas");
    const main   = document.getElementById("main");

    rendererInst = new THREE.WebGLRenderer({ canvas, antialias: true });
    rendererInst.shadowMap.enabled = true;
    rendererInst.setPixelRatio(window.devicePixelRatio);

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a2030);
    scene.fog = new THREE.Fog(0x1a2030, 20, 60);

    camera = new THREE.PerspectiveCamera(55, 1, 0.1, 200);
    camera.position.set(0, 1.5, 4);

    controls = new OrbitControls(camera, canvas);
    controls.enablePan = true;
    controls.target.set(0, 0.9, 0);
    controls.update();

    clock = new THREE.Clock();

    // Lights
    const amb = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(amb);
    const dir = new THREE.DirectionalLight(0xffffff, 1.2);
    dir.position.set(3, 6, 4);
    dir.castShadow = true;
    scene.add(dir);

    // Floor grid
    const grid = new THREE.GridHelper(10, 20, 0x333344, 0x2a2a3a);
    scene.add(grid);

    resize();
    window.addEventListener("resize", resize);
    render();
}

function resize() {
    const main   = document.getElementById("main");
    const editor = document.getElementById("editor");
    const transport = document.getElementById("transport");
    const header = document.getElementById("clipHeader");
    const blendPanel = document.getElementById("blendPanel");
    const blendH = blendPanel && !blendPanel.classList.contains("hidden") ? blendPanel.offsetHeight : 0;
    const ikPanel = document.getElementById("ikPanel");
    const ikH = ikPanel && !ikPanel.classList.contains("hidden") ? ikPanel.offsetHeight : 0;
    const teH = document.getElementById("templateEditor")?.classList.contains("hidden") ? 0
              : (document.getElementById("templateEditor")?.offsetHeight || 0);
    const edH = editor.classList.contains("hidden") ? 0 : editor.offsetHeight;
    const h = main.offsetHeight - transport.offsetHeight - header.offsetHeight - edH - blendH - ikH - teH;
    const w = main.offsetWidth;
    rendererInst.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
}

// =========================================================
// RENDER LOOP
// =========================================================

function render() {
    requestAnimationFrame(render);
    const delta = clock.getDelta();

    if (mixerA && isPlaying) {
        mixerA.update(delta * playSpeed);
        checkNotifies(mixerA.time);
    }
    if (mixerB && isPlaying) {
        mixerB.update(delta * playSpeed);
    }
    // IK runs every frame regardless of pause state (so you can drag while paused)
    if (characterA) updateIK();

    // Enforce start/end frame range
    if (activeAction && isPlaying) {
        const startT = startFrameToTime();
        const endT   = endFrameToTime();
        const t = activeAction.time;
        if (t >= endT) {
            if (loopMode === THREE.LoopOnce) {
                activeAction.paused = true;
                if (activeActionLower) activeActionLower.paused = true;
                isPlaying = false;
                document.getElementById("playBtn").textContent = "▶";
            } else {
                // jump back to start
                activeAction.time = startT;
                if (activeActionB) activeActionB.time = startT;
            }
        }
        if (t < startT) activeAction.time = startT;
    }

    controls.update();
    rendererInst.render(scene, camera);
    updateTransportUI();
}

// =========================================================
// NOTIFY FIRING
// =========================================================

function checkNotifies(currentTime) {
    if (!currentClipMeta) return;
    const notifies = currentClipMeta.notifies || [];
    const prevTime = lastMixerTime;

    for (const n of notifies) {
        const nTime = n.frame / (n.fps || clipFPS);
        const crossed = (prevTime <= nTime && currentTime > nTime) ||
                        (prevTime > currentTime && currentTime <= nTime); // loop wrap

        if (crossed && !notifyFired.has(n.id)) {
            notifyFired.add(n.id);
            flashNotifyRow(n.id);
            console.log("[AnimNotify]", n.event, "at frame", n.frame, "payload:", n.payload || {});

            // IK target add/remove via notifies
            if (n.event === "ik_add" && n.payload?.target)    addIKTarget(n.payload.target);
            if (n.event === "ik_remove" && n.payload?.target) removeIKTarget(n.payload.target);

            // Built-in reaction handler for altercation clips
            if (n.event === "start_reaction" && n.payload?.clip && mixerB) {
                const reactionRaw = rawClipsA.find(c => c.name === n.payload.clip);
                if (reactionRaw) {
                    mixerB.stopAllAction();
                    activeActionB = mixerB.clipAction(reactionRaw);
                    activeActionB.loop = THREE.LoopOnce;
                    activeActionB.clampWhenFinished = true;
                    activeActionB.reset().play();
                }
            }
        }
    }

    // Clear fire set on loop (when time resets)
    if (currentTime < prevTime) notifyFired.clear();
    lastMixerTime = currentTime;
}

function flashNotifyRow(id) {
    const row = document.querySelector(`.notifyRow[data-id="${id}"]`);
    if (!row) return;
    row.classList.remove("notifyFire");
    void row.offsetWidth;
    row.classList.add("notifyFire");
}

// =========================================================
// GLB LOADING
// =========================================================

async function loadSourceGLB(sourceKey) {
    const src = bank[sourceKey];
    if (!src) { console.warn("loadSourceGLB: no bank entry for", sourceKey); return; }
    currentSourceKey = sourceKey;
    showStatus("Loading " + (src.path || sourceKey) + "…");
    clearScene();
    try {
        const gltf = await loader.loadAsync(src.path);
        setupCharacter(gltf, 0);
        rawClipsA = gltf.animations || [];
        console.log("[animbank] GLB loaded:", src.path, "| animations:", rawClipsA.length);
        if (!rawClipsA.length) {
            showStatus("⚠ GLB loaded but contains NO animations — check the file");
        } else {
            showStatus("Loaded " + rawClipsA.length + " animations from " + (src.display_name || sourceKey));
        }
        frameAll();
        renderClipList();
    } catch (err) {
        console.error("[animbank] loadSourceGLB failed:", err);
        showStatus("❌ Failed to load GLB: " + (err.message || err));
    }
}

function setupCharacter(gltf, offsetX) {
    const model = gltf.scene;
    model.position.x = offsetX;
    model.traverse(o => {
        if (!o.isMesh) return;
        o.castShadow    = true;
        o.receiveShadow = true;
        // Disable frustum culling: prevents Three.js skipping bone-matrix uploads
        // when the bounding sphere misses the frustum, causing T-pose ghost overlay.
        o.frustumCulled = false;
        // DoubleSide prevents holes/see-through during extreme poses.
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach(m => {
            if (!m) return;
            m.side       = THREE.DoubleSide;
            m.depthWrite = true;
        });
    });
    // Flush skeleton to animated pose immediately so bind-pose ghost never renders.
    model.traverse(o => {
        if (o.isSkinnedMesh && o.skeleton) o.skeleton.pose();
    });
    scene.add(model);

    if (offsetX === 0) {
        characterA = model;
        mixerA     = new THREE.AnimationMixer(model);
        boneSets   = classifyBones(model);
        initIKBones(model);
        const info = document.getElementById("blendBoneInfo");
        if (info) info.textContent =
            `upper: ${boneSets.upper.size} bones · lower: ${boneSets.lower.size} bones`;
        const bp = document.getElementById("blendPanel");
        if (bp) bp.classList.remove("hidden");
        const ikp = document.getElementById("ikPanel");
        if (ikp) ikp.classList.remove("hidden");
        renderBlendDropdowns();
    } else {
        characterB = model;
        mixerB     = new THREE.AnimationMixer(model);
    }
}

function clearScene() {
    if (characterA) { scene.remove(characterA); characterA = null; mixerA = null; }
    if (characterB) { scene.remove(characterB); characterB = null; mixerB = null; }
    activeAction = null; activeActionB = null;
    activeActionUpper = null; activeActionLower = null;
    blendEnabled = false;
    chainTemplate = null; chainIndex = 0;
    // Remove all IK targets
    for (const type of Object.keys(ikTargets)) removeIKTarget(type);
    ikBones = {};
    rawClipsA = [];
    isPlaying = false;
    document.getElementById("playBtn").textContent = "▶";
    const bp = document.getElementById("blendPanel");
    if (bp) bp.classList.add("hidden");
    const ikp = document.getElementById("ikPanel");
    if (ikp) ikp.classList.add("hidden");
}

function frameAll() {
    if (!characterA) return;
    const box = new THREE.Box3().setFromObject(characterA);
    const center = box.getCenter(new THREE.Vector3());
    const size   = box.getSize(new THREE.Vector3());
    controls.target.copy(center);
    camera.position.set(center.x, center.y + size.y * 0.5, size.z * 2.5 + 2);
    controls.update();
}

// =========================================================
// PLAY A CLIP
// =========================================================

async function playClip(clipMeta) {
    // Exit blend mode; single-clip takes over
    blendEnabled      = false;
    activeActionUpper = null;
    activeActionLower = null;

    currentClipMeta = clipMeta;
    lastMixerTime   = 0;
    notifyFired.clear();

    // Auto-load second character for touch / sex / altercation
    if (PAIRED_PREVIEW_CATS.has(clipMeta.category) && !characterB && currentSourceKey) {
        const src = bank[currentSourceKey];
        if (src && src.path) {
            const gltf = await loader.loadAsync(src.path);
            setupCharacter(gltf, 1.2);
        }
    }

    if (!mixerA) return;

    // Find raw AnimationClip by original_name
    const originalName = clipMeta.original_name || clipMeta.name;
    let clip = rawClipsA.find(c => c.name === originalName)
            || rawClipsA.find(c => c.name === clipMeta.name);
    if (!clip) {
        console.warn("Clip not found in loaded GLB:", originalName);
        return;
    }

    // Stop all cached actions so no stale "T-pose ghost" action blends
    // on top of the new one. We skip AnimationUtils.subclip because it
    // creates a separate clip object that can leave the original clip's
    // cached action half-active. Instead we play the full clip and let
    // the render loop enforce startFrame / endFrame boundaries.
    mixerA.stopAllAction();
    activeAction = mixerA.clipAction(clip);
    activeAction
        .reset()
        .setEffectiveWeight(1)
        .setEffectiveTimeScale(1)
        .play();

    // Jump to the requested start frame; render loop clamps the end.
    activeAction.time = startFrameToTime();
    mixerA.update(0);   // force first frame immediately (kills T-pose flicker)

    // Paired side
    if (clipMeta.paired && clipMeta.pair_group && characterB) {
        const role = clipMeta.pair_role === "a" ? "b" : "a";
        const pairClipMeta = findPairClip(clipMeta.pair_group, role);
        if (pairClipMeta) {
            const pairOriginal = pairClipMeta.original_name || pairClipMeta.name;
            const pairRaw = rawClipsA.find(c => c.name === pairOriginal);
            if (pairRaw && mixerB) {
                mixerB.stopAllAction();
                activeActionB = mixerB.clipAction(pairRaw);
                activeActionB.loop = loopMode;
                activeActionB.play();
            }
        }
    }

    isPlaying = true;
    document.getElementById("playBtn").textContent = "⏸";
    updateEditorPanel(clipMeta);
    updateClipHeader(clipMeta, clip);
}

function findPairClip(pairGroup, role) {
    const src = bank[currentSourceKey];
    if (!src) return null;
    return (src.clips || []).find(c => c.pair_group === pairGroup && c.pair_role === role) || null;
}

// =========================================================
// BLEND PLAYBACK
// =========================================================

function renderBlendDropdowns() {
    const src = bank[currentSourceKey];
    const clips = src?.clips || [];
    ["blendUpperSel", "blendLowerSel"].forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const prev = sel.value;
        sel.innerHTML = '<option value="">— select clip —</option>';
        for (const c of clips) {
            const opt = document.createElement("option");
            opt.value = c.original_name || c.name;
            opt.textContent = `[${c.category}] ${c.name}`;
            if (opt.value === prev) opt.selected = true;
            sel.appendChild(opt);
        }
    });
}

function playBlended() {
    if (!mixerA) { showStatus("Load a character first."); return; }

    const upperName = document.getElementById("blendUpperSel").value;
    const lowerName = document.getElementById("blendLowerSel").value;
    if (!upperName || !lowerName) { showStatus("Select both clips."); return; }

    const upperRaw = rawClipsA.find(c => c.name === upperName);
    const lowerRaw = rawClipsA.find(c => c.name === lowerName);
    if (!upperRaw || !lowerRaw) { showStatus("Clip(s) not in loaded GLB."); return; }

    const upperFiltered = filterClip(upperRaw, boneSets.upper, "__upper");
    const lowerFiltered = filterClip(lowerRaw, boneSets.lower, "__lower");

    if (!upperFiltered.tracks.length) { showStatus("No upper-body tracks found in that clip."); return; }
    if (!lowerFiltered.tracks.length) { showStatus("No lower-body tracks found in that clip."); return; }

    mixerA.stopAllAction();

    activeActionUpper = mixerA.clipAction(upperFiltered);
    activeActionUpper.reset().setEffectiveWeight(1).setEffectiveTimeScale(1).play();
    activeActionUpper.loop = loopMode;

    activeActionLower = mixerA.clipAction(lowerFiltered);
    activeActionLower.reset().setEffectiveWeight(1).setEffectiveTimeScale(1).play();
    activeActionLower.loop = THREE.LoopRepeat;  // lower body always loops

    mixerA.update(0);  // force first frame immediately

    activeAction = activeActionUpper;  // timeline + transport track the upper clip
    blendEnabled  = true;
    isPlaying     = true;
    document.getElementById("playBtn").textContent = "⏸";
    showStatus(`Blending: ${upperRaw.name} ↑  +  ${lowerRaw.name} ↓`);
}


// =========================================================
// ANIMATION TEMPLATES
// =========================================================

function getTemplates() {
    return bank["_templates"] || (bank["_templates"] = {});
}

function createTemplate() {
    // Reuse an already-open, never-renamed-or-populated scaffold for this
    // source rather than creating another one — otherwise clicking
    // "+ New Template" again (e.g. after Save, unsure whether it "took")
    // silently piles up empty "new_template" entries that never get cleaned
    // up, since createTemplate() inserts into the bank immediately, before
    // the user has typed a name or saved anything.
    const templates = getTemplates();
    const existingScaffold = Object.values(templates).find(t =>
        t.source_key === (currentSourceKey || "") &&
        t.name === "new_template" &&
        (t.chain || []).length === 0
    );
    if (existingScaffold) {
        openTemplateEditor(existingScaffold);
        renderTemplateTab();
        return;
    }

    const id = crypto.randomUUID();
    const tmpl = {
        id,
        name: "new_template",
        source_key: currentSourceKey || "",
        chain: [],
        alternatives: [],
        notifies: [],
        ik_targets: [],
    };
    templates[id] = tmpl;
    // Set currentTemplate before rendering the list so the new row's
    // "active" highlight (currentTemplate?.id === tmpl.id, in
    // renderTemplateTab) is correct on the very first render instead of
    // lagging one click behind.
    openTemplateEditor(tmpl);
    renderTemplateTab();
}

function openTemplateEditor(tmpl) {
    currentTemplate = tmpl;

    // Show template editor, hide clip editor
    document.getElementById("editor").classList.add("hidden");
    const te = document.getElementById("templateEditor");
    te.classList.remove("hidden");

    document.getElementById("teName").value        = tmpl.name || "";
    document.getElementById("teAlternatives").value = (tmpl.alternatives || []).join(", ");

    // Source dropdown
    const srcSel = document.getElementById("teSource");
    srcSel.innerHTML = "";
    for (const key of Object.keys(bank)) {
        if (key.startsWith("_")) continue;
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = bank[key].display_name || key;
        if (key === tmpl.source_key) opt.selected = true;
        srcSel.appendChild(opt);
    }
    srcSel.addEventListener("change", () => {
        tmpl.source_key = srcSel.value;
        renderChainList(tmpl);
    });

    renderChainList(tmpl);
    renderTemplateNotifyList(tmpl);
    resize();
}

function renderChainList(tmpl) {
    const el = document.getElementById("chainList");
    el.innerHTML = "";

    const src = bank[tmpl.source_key];
    const clipOpts = (src?.clips || []).map(c => ({
        label: `[${c.category}] ${c.name}`,
        value: c.original_name || c.name,
    }));

    (tmpl.chain || []).forEach((entry, idx) => {
        const row = document.createElement("div");
        row.className = "chainRow";

        // Clip selector
        const sel = document.createElement("select");
        sel.style.cssText = "flex:2;padding:3px 5px;background:#141820;border:1px solid #3a4050;color:#ccc;border-radius:3px;font-size:11px";
        const blank = document.createElement("option");
        blank.value = ""; blank.textContent = "— clip —";
        sel.appendChild(blank);
        for (const o of clipOpts) {
            const opt = document.createElement("option");
            opt.value = o.value; opt.textContent = o.label;
            if (o.value === entry.clip) opt.selected = true;
            sel.appendChild(opt);
        }
        sel.addEventListener("change", () => { entry.clip = sel.value; });

        // Start frame
        const startF = document.createElement("input");
        startF.type = "number"; startF.min = 0; startF.value = entry.start_frame ?? 0;
        startF.title = "Start frame";
        startF.style.cssText = "width:44px;padding:3px;background:#141820;border:1px solid #333;color:#ccc;border-radius:3px;font-size:11px";
        startF.addEventListener("change", () => { entry.start_frame = parseInt(startF.value) || 0; });

        // End frame
        const endF = document.createElement("input");
        endF.type = "number"; endF.min = 0; endF.value = entry.end_frame ?? "";
        endF.placeholder = "end"; endF.title = "End frame (blank = full clip)";
        endF.style.cssText = "width:44px;padding:3px;background:#141820;border:1px solid #333;color:#ccc;border-radius:3px;font-size:11px";
        endF.addEventListener("change", () => {
            entry.end_frame = endF.value === "" ? null : parseInt(endF.value);
        });

        // Speed
        const spd = document.createElement("input");
        spd.type = "number"; spd.step = 0.05; spd.min = 0.05; spd.max = 4;
        spd.value = entry.speed ?? 1.0; spd.title = "Speed";
        spd.style.cssText = "width:44px;padding:3px;background:#141820;border:1px solid #333;color:#ccc;border-radius:3px;font-size:11px";
        spd.addEventListener("change", () => { entry.speed = parseFloat(spd.value) || 1.0; });

        // Loop mode
        const loopSel = document.createElement("select");
        loopSel.style.cssText = "padding:3px 5px;background:#141820;border:1px solid #3a4050;color:#ccc;border-radius:3px;font-size:11px";
        for (const [v, lbl] of [["repeat","↺ Loop"],["pingpong","⇄ Ping"],["once","→| Once"]]) {
            const o = document.createElement("option");
            o.value = v; o.textContent = lbl;
            if (v === (entry.loop || "repeat")) o.selected = true;
            loopSel.appendChild(o);
        }
        loopSel.addEventListener("change", () => { entry.loop = loopSel.value; });

        // Loop count
        const cnt = document.createElement("input");
        cnt.type = "number"; cnt.min = -1; cnt.value = entry.loop_count ?? -1;
        cnt.title = "Loop count (-1 = infinite)";
        cnt.style.cssText = "width:40px;padding:3px;background:#141820;border:1px solid #333;color:#ccc;border-radius:3px;font-size:11px";
        cnt.addEventListener("change", () => { entry.loop_count = parseInt(cnt.value); });

        // Delete
        const del = document.createElement("button");
        del.textContent = "✕"; del.className = "danger";
        del.style.cssText = "padding:2px 5px;font-size:10px;flex-shrink:0";
        del.addEventListener("click", () => {
            tmpl.chain.splice(idx, 1);
            renderChainList(tmpl);
        });

        row.appendChild(sel);
        row.appendChild(startF);
        row.appendChild(endF);
        row.appendChild(spd);
        row.appendChild(loopSel);
        row.appendChild(cnt);
        row.appendChild(del);
        el.appendChild(row);
    });
}

function renderTemplateNotifyList(tmpl) {
    const el = document.getElementById("templateNotifyList");
    if (!el) return;
    el.innerHTML = "";
    for (const n of (tmpl.notifies || [])) {
        const row = document.createElement("div");
        row.className = "notifyRow"; row.dataset.id = n.id;

        const frameInput = document.createElement("input");
        frameInput.className = "nFrame"; frameInput.type = "number"; frameInput.value = n.frame;
        frameInput.addEventListener("change", () => { n.frame = parseInt(frameInput.value) || 0; });

        const eventInput = document.createElement("input");
        eventInput.className = "nEvent";
        eventInput.setAttribute("list", "notifyEventOptions");
        eventInput.value = n.event || ""; eventInput.placeholder = "event_name";
        eventInput.addEventListener("change", () => { n.event = eventInput.value; });

        const delBtn = document.createElement("button");
        delBtn.className = "nDel danger"; delBtn.textContent = "✕";
        delBtn.addEventListener("click", () => {
            tmpl.notifies = (tmpl.notifies || []).filter(x => x.id !== n.id);
            renderTemplateNotifyList(tmpl);
        });

        row.appendChild(frameInput); row.appendChild(eventInput); row.appendChild(delBtn);
        el.appendChild(row);
    }
}

function saveCurrentTemplate() {
    if (!currentTemplate) return;
    currentTemplate.name        = document.getElementById("teName").value.trim() || currentTemplate.name;
    currentTemplate.alternatives = document.getElementById("teAlternatives").value
        .split(",").map(s => s.trim()).filter(Boolean);
    getTemplates()[currentTemplate.id] = currentTemplate;
    renderTemplateTab();
    showStatus("Template saved.");
}

function deleteCurrentTemplate() {
    if (!currentTemplate) return;
    delete getTemplates()[currentTemplate.id];
    currentTemplate = null;
    document.getElementById("templateEditor").classList.add("hidden");
    renderTemplateTab();
    showStatus("Template deleted.");
}

// Play entire chain sequence
function playTemplate(tmpl) {
    if (!rawClipsA.length) {
        // Auto-load the source GLB if not already loaded
        if (tmpl.source_key && bank[tmpl.source_key]) {
            loadSourceGLB(tmpl.source_key).then(() => playTemplate(tmpl));
        }
        return;
    }
    chainTemplate = tmpl;
    chainIndex = 0;
    playChainStep(0);
}

function playChainStep(idx) {
    if (!chainTemplate) return;
    const entry = (chainTemplate.chain || [])[idx];
    if (!entry) return;

    const raw = rawClipsA.find(c => c.name === entry.clip);
    if (!raw) {
        console.warn("Chain: clip not found in GLB:", entry.clip);
        // Advance anyway
        if (idx + 1 < chainTemplate.chain.length) playChainStep(idx + 1);
        return;
    }

    blendEnabled = false; activeActionUpper = null; activeActionLower = null;
    mixerA.stopAllAction();

    // Remove previous chain listener
    if (chainListener) { mixerA.removeEventListener("finished", chainListener); chainListener = null; }

    const loopMap = { repeat: THREE.LoopRepeat, pingpong: THREE.LoopPingPong, once: THREE.LoopOnce };
    const loop = loopMap[entry.loop || "repeat"] || THREE.LoopRepeat;

    const action = mixerA.clipAction(raw);
    action.reset().setEffectiveWeight(1).setEffectiveTimeScale(entry.speed || 1.0).play();
    action.loop = loop;
    action.clampWhenFinished = loop === THREE.LoopOnce;
    if (entry.loop_count > 0) action.repetitions = entry.loop_count;

    const startT = (entry.start_frame || 0) / clipFPS;
    action.time = startT;
    mixerA.update(0);

    activeAction = action;
    chainIndex   = idx;
    isPlaying    = true;
    document.getElementById("playBtn").textContent = "⏸";

    // Advance to next step when this one finishes (only for once / finite loops)
    if (idx + 1 < chainTemplate.chain.length && loop !== THREE.LoopRepeat) {
        chainListener = (e) => {
            if (e.action === action) {
                mixerA.removeEventListener("finished", chainListener);
                chainListener = null;
                playChainStep(idx + 1);
            }
        };
        mixerA.addEventListener("finished", chainListener);
    }
}

function renderTemplateTab() {
    renderStancesPanel();
    renderTransitionsPanel();

    const el = document.getElementById("templateList");
    if (!el) return;
    el.innerHTML = "";
    // Filtered to the currently selected character/source — without this,
    // every template from every character shows in one flat list, and it's
    // easy to accidentally open/edit e.g. adult_male's walk cycle while
    // adult_female is selected. Falls back to unfiltered if no source is
    // selected yet, matching the tool's state before a source is picked.
    const allTemplates = Object.values(getTemplates());
    const templates = currentSourceKey
        ? allTemplates.filter(t => t.source_key === currentSourceKey)
        : allTemplates;
    for (const tmpl of templates) {
        const row = document.createElement("div");
        row.className = "sourceRow" + (currentTemplate?.id === tmpl.id ? " active" : "");
        row.style.cursor = "pointer";

        const name = document.createElement("div");
        name.className = "srcName"; name.textContent = tmpl.name;

        const count = document.createElement("div");
        count.className = "srcCount";
        count.textContent = (tmpl.chain || []).length + " clips";

        row.appendChild(name); row.appendChild(count);
        row.addEventListener("click", () => {
            // openTemplateEditor() must run first — it sets currentTemplate,
            // which renderTemplateTab()'s active-row highlight reads. Doing
            // it in the other order re-renders the list against the
            // previous selection, so the highlight lags one click behind.
            openTemplateEditor(tmpl);
            renderTemplateTab();
        });
        el.appendChild(row);
    }
}

// =========================================================
// EXTRACT CLIPS FROM LOADED GLB
// =========================================================

function extractClips() {
    if (!rawClipsA.length) {
        alert("Load a GLB source first.");
        return;
    }
    const src = bank[currentSourceKey];
    if (!src) return;

    const existing = new Set((src.clips || []).map(c => c.original_name));

    let added = 0;
    for (const clip of rawClipsA) {
        if (existing.has(clip.name)) continue;
        const cat = classifyClip(clip.name);
        src.clips = src.clips || [];
        src.clips.push({
            id:            crypto.randomUUID(),
            name:          clip.name,
            original_name: clip.name,
            category:      cat,
            duration:      parseFloat(clip.duration.toFixed(3)),
            loop:          cat === "idle" || cat === "locomotion",
            paired:        false,
            pair_role:     null,
            pair_group:    null,
            tags:          [],
            notifies:      [],
        });
        added++;
    }

    renderClipList();
    showStatus(`Extracted ${added} new clip${added !== 1 ? "s" : ""}.`);
}

// =========================================================
// TRANSPORT CONTROLS
// =========================================================

function startFrameToTime() {
    const f = parseInt(document.getElementById("startFrame").value) || 0;
    return f / clipFPS;
}
function endFrameToTime() {
    const f = parseInt(document.getElementById("endFrame").value);
    if (isNaN(f)) return activeAction ? activeAction.getClip().duration : 999;
    return f / clipFPS;
}

function updateTransportUI() {
    if (!activeAction) return;
    const clip = activeAction.getClip();
    const t    = activeAction.time;
    const dur  = clip.duration;
    const startT = startFrameToTime();
    const endT   = endFrameToTime();
    const range  = endT - startT;

    // Timeline position relative to range
    const pct = range > 0 ? Math.max(0, Math.min(1, (t - startT) / range)) : 0;
    const tl = document.getElementById("timeline");
    if (!tl._dragging) tl.value = pct;

    const frame = Math.round(t * clipFPS);
    const endFrame = Math.round(Math.min(endT, dur) * clipFPS);
    document.getElementById("timeDisplay").textContent =
        `f${frame} / f${endFrame}  (${t.toFixed(2)}s)`;
}

// =========================================================
// STANCE / TRANSITION MIGRATION
// =========================================================
// Replaces the old flat 5-state `locomotion` map with the richer `stances`
// (per-stance idle/move template slots) + `transitions` (from->to template
// graph) shape. `locomotion` is left in place on disk, untouched — nothing
// reads it after this, but there's no reason to destroy it.

function migrateLocomotionToStances(src) {
    if (!src || src.stances) return;   // already migrated (or nothing to migrate)

    const loco = src.locomotion || {};
    src.stances = {
        standing:      { idle: loco.idle, walk: loco.walk, run: loco.run },
        sitting_seat:  {},
        sitting_floor: {},
        lying:         {},
        crouching:     { idle: loco.crouch_idle, move: loco.crouch_walk },
        crawling:      {},
        fallen_front:  {},
        fallen_back:   {},
        leaning_wall:  {},
    };
    // Drop undefined slots rather than storing them — matches the existing
    // "absent key means unset" convention used by the old locomotion map.
    for (const slots of Object.values(src.stances)) {
        for (const [slot, val] of Object.entries(slots)) {
            if (val === undefined) delete slots[slot];
        }
    }
    src.transitions = src.transitions || [];
}

// =========================================================
// BANK API
// =========================================================

async function loadBank() {
    const r = await fetch("/api/animbank");
    bank = await r.json();
    for (const [key, src] of Object.entries(bank)) {
        // "_templates" holds the template dict itself, not a character
        // source — skip it, migrateLocomotionToStances() is only meaningful
        // for per-character source entries.
        if (key === "_templates") continue;
        if (src && typeof src === "object") migrateLocomotionToStances(src);
    }
    renderSidebar();
    renderCategoryFilter();
    renderClipList();
    renderTemplateTab();
}

async function saveBank() {
    await fetch("/api/animbank", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bank),
    });
    showStatus("Bank saved.");
}

// =========================================================
// RENDER SIDEBAR (sources)
// =========================================================

function renderSidebar() {
    const el = document.getElementById("sourceList");
    el.innerHTML = "";
    for (const [key, src] of Object.entries(bank)) {
        // "_templates" holds the template dict itself, not a character
        // source — same exclusion as loadBank()'s migration loop above.
        if (key === "_templates") continue;
        const row = document.createElement("div");
        row.className = "sourceRow" + (key === currentSourceKey ? " active" : "");
        const dot = document.createElement("div");
        dot.className = "srcDot";
        dot.style.background = "#4a90d9";
        const name = document.createElement("div");
        name.className = "srcName";
        name.textContent = src.display_name || key;
        const count = document.createElement("div");
        count.className = "srcCount";
        count.textContent = (src.clips || []).length;
        row.appendChild(dot);
        row.appendChild(name);
        row.appendChild(count);
        row.addEventListener("click", () => {
            currentSourceKey = key;
            renderSidebar();
            renderClipList();
            renderTemplateTab();
            loadSourceGLB(key);
        });
        el.appendChild(row);
    }
}

// =========================================================
// RENDER CATEGORY FILTER
// =========================================================

let activeCategory = "all";

function renderCategoryFilter() {
    const el = document.getElementById("catFilter");
    el.innerHTML = "";
    const allBtn = makeCatBtn("All", "all");
    el.appendChild(allBtn);
    for (const cat of CATEGORIES) {
        el.appendChild(makeCatBtn(cat, cat));
    }
}

function makeCatBtn(label, value) {
    const btn = document.createElement("button");
    btn.className = "catBtn" + (activeCategory === value ? " active" : "");
    btn.textContent = label;
    btn.style.borderColor = CAT_COLOR[value] || "#444";
    if (activeCategory === value) btn.style.background = CAT_COLOR[value] || "#333";
    btn.addEventListener("click", () => {
        activeCategory = value;
        renderCategoryFilter();
        renderClipList();
    });
    return btn;
}

// =========================================================
// RENDER CLIP LIST
// =========================================================

// =========================================================
// STANCES + TRANSITIONS (per source/character)
// =========================================================
// Which TEMPLATE fills each stance's idle/movement animation, and which
// TEMPLATE (if any) plays as a one-shot transition when moving between two
// stances — read by the live game (main.js) instead of its hardcoded
// clip-name convention. Mapped to templates (not raw clips) so this reuses
// the same reusable-chain/variant-pool abstraction as every other
// animation in the bank, rather than being a one-off special case.
//
// Idle/move slots resolve a mapped template down to its first chain step's
// clip (the loopable clip) at character-load time; transitions do too, but
// since a transition is a one-shot rather than a loop, authoring a
// multi-step chain (e.g. "slip" then "fall") on the template lets the
// live game play the full sequence — see resolveLocomotionMap() in main.js.

const STANCES = [
    { key: "standing",      label: "Standing",
      moves: [{ slot: "idle", label: "Idle" }, { slot: "walk", label: "Walk" }, { slot: "run", label: "Run" }] },
    { key: "sitting_seat",  label: "Sitting (Seat)",  moves: [{ slot: "idle", label: "Idle" }] },
    { key: "sitting_floor", label: "Sitting (Floor)", moves: [{ slot: "idle", label: "Idle" }] },
    { key: "lying",         label: "Lying",           moves: [{ slot: "idle", label: "Idle" }] },
    { key: "crouching",     label: "Crouching",
      moves: [{ slot: "idle", label: "Idle" }, { slot: "move", label: "Move" }] },
    { key: "crawling",      label: "Crawling",
      moves: [{ slot: "idle", label: "Idle" }, { slot: "move", label: "Move" }] },
    // Split by fall direction (not one generic "Fallen") so fall_forward/
    // get_up_front and fall_backward/get_up_back are just ordinary
    // standing<->stance transitions with no new from/to concept needed —
    // each pair is already unique in the Transitions panel below.
    { key: "fallen_front",  label: "Fallen (Front)",  moves: [{ slot: "idle", label: "Idle" }] },
    { key: "fallen_back",   label: "Fallen (Back)",   moves: [{ slot: "idle", label: "Idle" }] },
    { key: "leaning_wall",  label: "Leaning (Wall)",  moves: [{ slot: "idle", label: "Idle" }] },
    { key: "unconscious",   label: "Unconscious",     moves: [{ slot: "idle", label: "Idle" }] },
    { key: "dead",          label: "Dead",            moves: [{ slot: "idle", label: "Idle" }] },
    { key: "intoxicated",   label: "Intoxicated",
      moves: [{ slot: "idle", label: "Idle" }, { slot: "walk", label: "Walk" }, { slot: "run", label: "Run" }] },
    // Carry is an upper-body overlay (legs keep walking/idling normally
    // while carrying), not an exclusive full-body pose like the others —
    // main.js already has working carry_idle/carry_walk ANIM_LAYERS
    // entries for this, so leaving these unset here keeps that fallback;
    // authoring a template here overrides both layers with the same clip.
    { key: "carry",         label: "Carry",
      moves: [{ slot: "idle", label: "Idle" }, { slot: "move", label: "Move" }] },
    // Dragging/pushing: same "optional override of an existing ANIM_LAYERS
    // fallback" pattern as carry, not real c["posture"] values — see the
    // comment on _STANCE_IDLE_KEY in main.js.
    { key: "dragging",      label: "Dragging",
      moves: [{ slot: "idle", label: "Idle" }, { slot: "move", label: "Move" }] },
    { key: "pushing",       label: "Pushing",         moves: [{ slot: "idle", label: "Idle" }] },
];

function _templateOptionsHTML(templates, current) {
    return `<option value="">— none —</option>` +
        templates.map(t => `<option value="${t.id}"${t.id === current ? " selected" : ""}>${t.name}</option>`).join("");
}

function renderStancesPanel() {
    const panel = document.getElementById("stancesPanel");
    const src = bank[currentSourceKey];

    if (!src) {
        panel.classList.add("hidden");
        return;
    }
    panel.classList.remove("hidden");

    migrateLocomotionToStances(src);   // defensive — matches old src.locomotion=src.locomotion||{} guard

    const templates = Object.values(getTemplates())
        .filter(t => t.source_key === currentSourceKey);
    const title = templates.length === 0
        ? "No templates for this character yet — create one in the Templates tab first." : "";

    const listEl = document.getElementById("stanceList");
    listEl.innerHTML = "";

    for (const stance of STANCES) {
        src.stances[stance.key] = src.stances[stance.key] || {};
        const slots = src.stances[stance.key];

        const group = document.createElement("div");
        group.className = "stanceGroup";
        const groupLabel = document.createElement("div");
        groupLabel.className = "stanceGroupLabel";
        groupLabel.textContent = stance.label;
        group.appendChild(groupLabel);

        for (const { slot, label } of stance.moves) {
            const row = document.createElement("div");
            row.className = "locoRow";
            const lbl = document.createElement("label");
            lbl.textContent = label;
            const select = document.createElement("select");
            select.title = title;
            select.innerHTML = _templateOptionsHTML(templates, slots[slot] || "");
            select.onchange = () => {
                if (select.value) slots[slot] = select.value;
                else delete slots[slot];
            };
            row.appendChild(lbl);
            row.appendChild(select);
            group.appendChild(row);
        }
        listEl.appendChild(group);
    }
}

function renderTransitionsPanel() {
    const panel = document.getElementById("transitionsPanel");
    const src = bank[currentSourceKey];

    if (!src) {
        panel.classList.add("hidden");
        return;
    }
    panel.classList.remove("hidden");

    migrateLocomotionToStances(src);
    src.transitions = src.transitions || [];

    const templates = Object.values(getTemplates())
        .filter(t => t.source_key === currentSourceKey);

    const listEl = document.getElementById("transitionList");
    listEl.innerHTML = "";

    for (const t of src.transitions) {
        const row = document.createElement("div");
        row.className = "transRow";

        const fromSel = document.createElement("select");
        for (const s of STANCES) {
            const o = document.createElement("option");
            o.value = s.key; o.textContent = s.label;
            if (s.key === t.from) o.selected = true;
            fromSel.appendChild(o);
        }
        fromSel.addEventListener("change", () => { t.from = fromSel.value; });

        const arrow = document.createElement("span");
        arrow.textContent = "→";
        arrow.style.cssText = "color:#666;flex:none";

        const toSel = document.createElement("select");
        for (const s of STANCES) {
            const o = document.createElement("option");
            o.value = s.key; o.textContent = s.label;
            if (s.key === t.to) o.selected = true;
            toSel.appendChild(o);
        }
        toSel.addEventListener("change", () => { t.to = toSel.value; });

        const tmplSel = document.createElement("select");
        tmplSel.innerHTML = _templateOptionsHTML(templates, t.template || "");
        tmplSel.addEventListener("change", () => { t.template = tmplSel.value || null; });

        const del = document.createElement("button");
        del.textContent = "✕"; del.className = "danger transDel";
        del.addEventListener("click", () => {
            src.transitions = src.transitions.filter(x => x.id !== t.id);
            renderTransitionsPanel();
        });

        row.appendChild(fromSel);
        row.appendChild(arrow);
        row.appendChild(toSel);
        row.appendChild(tmplSel);
        row.appendChild(del);
        listEl.appendChild(row);
    }
}

function renderClipList() {
    renderStancesPanel();
    renderTransitionsPanel();

    const el = document.getElementById("clipList");
    el.innerHTML = "";
    const src = bank[currentSourceKey];
    if (!src) return;

    const clips = (src.clips || []).filter(c =>
        activeCategory === "all" || c.category === activeCategory
    );

    // Group by category
    const groups = {};
    for (const clip of clips) {
        const cat = clip.category || "uncategorized";
        if (!groups[cat]) groups[cat] = [];
        groups[cat].push(clip);
    }

    for (const [cat, catClips] of Object.entries(groups)) {
        const group = document.createElement("div");
        group.className = "catGroup";
        group.dataset.cat = cat;

        const header = document.createElement("div");
        header.className = "catHeader";
        header.style.background = CAT_COLOR[cat] || "#333";
        header.innerHTML = `
            <span>${cat}</span>
            <span class="catCount">${catClips.length}</span>
            <span class="arrow">▾</span>
        `;
        header.addEventListener("click", () => {
            group.classList.toggle("collapsed");
        });

        const items = document.createElement("div");
        items.className = "catItems";

        for (const clip of catClips) {
            const row = document.createElement("div");
            row.className = "clipRow" + (currentClipMeta?.id === clip.id ? " active" : "");
            row.dataset.clipId = clip.id;

            const nameEl = document.createElement("div");
            nameEl.className = "clipName";
            nameEl.textContent = clip.name;

            const durEl = document.createElement("div");
            durEl.className = "clipDur";
            durEl.textContent = clip.duration ? clip.duration.toFixed(2) + "s" : "—";

            row.appendChild(nameEl);
            row.appendChild(durEl);

            if (clip.paired) {
                const badge = document.createElement("div");
                badge.className = "pairedBadge";
                badge.textContent = clip.pair_role ? clip.pair_role.toUpperCase() : "⇄";
                row.appendChild(badge);
            }

            row.addEventListener("click", () => {
                document.querySelectorAll(".clipRow").forEach(r => r.classList.remove("active"));
                row.classList.add("active");
                playClip(clip);
            });

            items.appendChild(row);
        }

        group.appendChild(header);
        group.appendChild(items);
        el.appendChild(group);
    }
    // Keep blend dropdowns in sync with current clip list
    renderBlendDropdowns();
}

// =========================================================
// CLIP HEADER + EDITOR PANEL
// =========================================================

function updateClipHeader(clipMeta, rawClip) {
    document.getElementById("clipTitle").textContent = clipMeta.name;
    document.getElementById("clipTitle").style.color = "#ccc";

    const pill = document.getElementById("clipCatPill");
    pill.textContent = clipMeta.category || "uncategorized";
    pill.style.background = CAT_COLOR[clipMeta.category] || "#555";
    pill.style.color = "#fff";

    const paired = document.getElementById("pairedBadge");
    paired.style.display = clipMeta.paired ? "inline-block" : "none";

    const dur = rawClip ? rawClip.duration : (clipMeta.duration || 0);
    document.getElementById("clipDurLabel").textContent =
        `${dur.toFixed(3)}s  ·  ${Math.round(dur * clipFPS)} frames`;

    // Set default end frame to clip length
    const endInput = document.getElementById("endFrame");
    if (parseInt(endInput.value) > Math.round(dur * clipFPS) || endInput.value === "999") {
        endInput.value = Math.round(dur * clipFPS);
    }
    document.getElementById("fpsHint").textContent = `${clipFPS} fps`;
}

function updateEditorPanel(clipMeta) {
    const editor = document.getElementById("editor");
    editor.classList.remove("hidden");
    // Mirror openTemplateEditor()'s hide of #editor — selecting a clip must
    // also close out any open template editor, or the two panels stack.
    document.getElementById("templateEditor").classList.add("hidden");

    document.getElementById("eName").value      = clipMeta.name || "";
    document.getElementById("eLoop").checked    = !!clipMeta.loop;
    document.getElementById("ePaired").checked  = !!clipMeta.paired;
    document.getElementById("ePairGroup").value = clipMeta.pair_group || "";
    document.getElementById("ePairRole").value  = clipMeta.pair_role  || "";
    document.getElementById("eTags").value      = (clipMeta.tags || []).join(", ");

    // Fill category select
    const eCat = document.getElementById("eCat");
    eCat.innerHTML = "";
    for (const cat of CATEGORIES) {
        const opt = document.createElement("option");
        opt.value = cat;
        opt.textContent = cat;
        if (cat === clipMeta.category) opt.selected = true;
        eCat.appendChild(opt);
    }

    // Notifies
    renderNotifyList(clipMeta);

    resize();
}

function renderNotifyList(clipMeta) {
    const el = document.getElementById("notifyList");
    el.innerHTML = "";
    for (const n of (clipMeta.notifies || [])) {
        const row = document.createElement("div");
        row.className = "notifyRow";
        row.dataset.id = n.id;

        const frameInput = document.createElement("input");
        frameInput.className = "nFrame";
        frameInput.type  = "number";
        frameInput.value = n.frame;
        frameInput.title = "Frame number";
        frameInput.addEventListener("change", () => {
            n.frame = parseInt(frameInput.value) || 0;
        });

        // Event input (text, with common suggestions)
        const eventInput = document.createElement("input");
        eventInput.className = "nEvent";
        eventInput.setAttribute("list", "notifyEventOptions");
        eventInput.value       = n.event || "";
        eventInput.placeholder = "event_name";

        // Reaction clip selector (shown when event is start_reaction)
        const reactionWrap = document.createElement("div");
        reactionWrap.style.cssText = "display:flex;gap:4px;align-items:center;";

        function refreshReactionUI() {
            reactionWrap.innerHTML = "";
            if (eventInput.value === "start_reaction") {
                const sel = document.createElement("select");
                sel.style.cssText = "flex:1;padding:3px 5px;background:#141820;border:1px solid #333;color:#ccc;border-radius:3px;font-size:11px";
                const blank = document.createElement("option");
                blank.value = ""; blank.textContent = "— reaction clip —";
                sel.appendChild(blank);
                const src = bank[currentSourceKey];
                for (const c of (src?.clips || [])) {
                    if (c.category !== "reaction") continue;
                    const opt = document.createElement("option");
                    opt.value = c.original_name || c.name;
                    opt.textContent = c.name;
                    if (opt.value === n.payload?.clip) opt.selected = true;
                    sel.appendChild(opt);
                }
                sel.addEventListener("change", () => {
                    n.payload = n.payload || {};
                    n.payload.clip = sel.value;
                });
                reactionWrap.appendChild(sel);
            }
        }

        eventInput.addEventListener("change", () => {
            n.event = eventInput.value;
            refreshReactionUI();
        });
        refreshReactionUI();

        const delBtn = document.createElement("button");
        delBtn.className   = "nDel danger";
        delBtn.textContent = "✕";
        delBtn.addEventListener("click", () => {
            clipMeta.notifies = (clipMeta.notifies || []).filter(x => x.id !== n.id);
            renderNotifyList(clipMeta);
        });

        row.appendChild(frameInput);
        row.appendChild(eventInput);
        row.appendChild(reactionWrap);
        row.appendChild(delBtn);
        el.appendChild(row);
    }
}

// =========================================================
// STATUS BAR
// =========================================================

function showStatus(msg) {
    const el = document.getElementById("clipDurLabel");
    const orig = el.textContent;
    el.textContent = "✓ " + msg;
    el.style.color = "#4acc88";
    setTimeout(() => { el.textContent = orig; el.style.color = "#666"; }, 2000);
}

// =========================================================
// EVENT WIRING
// =========================================================

function wireEvents() {

    // Play / pause
    document.getElementById("playBtn").addEventListener("click", () => {
        if (!activeAction) return;
        isPlaying = !isPlaying;
        activeAction.paused   = !isPlaying;
        if (activeActionB)     activeActionB.paused     = !isPlaying;
        if (activeActionLower) activeActionLower.paused  = !isPlaying;
        document.getElementById("playBtn").textContent = isPlaying ? "⏸" : "▶";
        if (isPlaying) notifyFired.clear();
    });

    // Timeline scrub
    const tl = document.getElementById("timeline");
    tl.addEventListener("mousedown", () => { tl._dragging = true; });
    tl.addEventListener("mouseup",   () => { tl._dragging = false; });
    tl.addEventListener("input", () => {
        if (!activeAction) return;
        const clip   = activeAction.getClip();
        const startT = startFrameToTime();
        const endT   = endFrameToTime();
        const t = startT + parseFloat(tl.value) * (endT - startT);
        activeAction.time = Math.max(0, Math.min(clip.duration, t));
        if (activeActionB) activeActionB.time = activeAction.time;
        notifyFired.clear();
        lastMixerTime = activeAction.time;
    });

    // Speed
    const speedSlider = document.getElementById("speedSlider");
    speedSlider.addEventListener("input", () => {
        playSpeed = parseFloat(speedSlider.value);
        document.getElementById("speedLabel").textContent = playSpeed.toFixed(2) + "×";
    });

    // Loop mode buttons
    document.getElementById("loopRepeat").addEventListener("click", () => setLoopMode(THREE.LoopRepeat, "loopRepeat"));
    document.getElementById("loopPingPong").addEventListener("click", () => setLoopMode(THREE.LoopPingPong, "loopPingPong"));
    document.getElementById("loopOnce").addEventListener("click",    () => setLoopMode(THREE.LoopOnce,    "loopOnce"));

    // Start / end frame — trigger replay if clip is active
    document.getElementById("startFrame").addEventListener("change", () => {
        if (currentClipMeta && isPlaying) playClip(currentClipMeta);
    });
    document.getElementById("endFrame").addEventListener("change", () => {
        if (currentClipMeta && isPlaying) playClip(currentClipMeta);
    });

    // Add source
    document.getElementById("addSourceBtn").addEventListener("click", () => {
        const path = document.getElementById("addSourcePath").value.trim();
        if (!path) return;
        const key = path.split("/").pop().replace(".glb", "").replace(/\W+/g, "_");
        if (!bank[key]) {
            bank[key] = { display_name: key, path, clips: [] };
        }
        renderSidebar();
        currentSourceKey = key;
        loadSourceGLB(key);
        document.getElementById("addSourcePath").value = "";
    });

    // Upload GLB
    document.getElementById("uploadGlb").addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append("file", file);
        fd.append("category", "characters");
        const r = await fetch("/api/assets/upload", { method: "POST", body: fd });
        if (!r.ok) {
            alert(`Upload failed: ${r.status} ${r.statusText}${r.status === 413 ? " — file too large (nginx limit)" : ""}`);
            return;
        }
        const data = await r.json();
        if (!data.ok) { alert("Upload failed"); return; }
        const key = file.name.replace(".glb", "").replace(/\W+/g, "_");
        bank[key] = bank[key] || { display_name: key, path: data.path, clips: [] };
        currentSourceKey = key;
        renderSidebar();
        loadSourceGLB(key);
    });

    // Extract clips
    document.getElementById("extractBtn").addEventListener("click", extractClips);

    // Save bank
    document.getElementById("saveBankBtn").addEventListener("click", saveBank);

    // Save clip metadata
    document.getElementById("saveClipBtn").addEventListener("click", () => {
        if (!currentClipMeta) return;
        currentClipMeta.name       = document.getElementById("eName").value.trim() || currentClipMeta.name;
        currentClipMeta.category   = document.getElementById("eCat").value;
        currentClipMeta.loop       = document.getElementById("eLoop").checked;
        currentClipMeta.paired     = document.getElementById("ePaired").checked;
        currentClipMeta.pair_group = document.getElementById("ePairGroup").value.trim() || null;
        currentClipMeta.pair_role  = document.getElementById("ePairRole").value || null;
        currentClipMeta.tags       = document.getElementById("eTags").value
            .split(",").map(t => t.trim()).filter(Boolean);

        renderClipList();
        renderSidebar();
        updateClipHeader(currentClipMeta, activeAction?.getClip() || null);
        showStatus("Clip saved.");
    });

    // Delete clip from bank
    document.getElementById("deleteClipBtn").addEventListener("click", () => {
        if (!currentClipMeta || !currentSourceKey) return;
        const src = bank[currentSourceKey];
        src.clips = (src.clips || []).filter(c => c.id !== currentClipMeta.id);
        currentClipMeta = null;
        document.getElementById("editor").classList.add("hidden");
        renderClipList();
        renderSidebar();
        resize();
    });

    // Add notify
    document.getElementById("addNotifyBtn").addEventListener("click", () => {
        if (!currentClipMeta) return;
        currentClipMeta.notifies = currentClipMeta.notifies || [];
        currentClipMeta.notifies.push({
            id:      crypto.randomUUID(),
            frame:   0,
            fps:     clipFPS,
            event:   "footstep",
            payload: {},
        });
        renderNotifyList(currentClipMeta);
    });

    // IK panel buttons
    document.getElementById("ikAddRH").addEventListener("click",    () => addIKTarget("right_hand"));
    document.getElementById("ikAddLH").addEventListener("click",    () => addIKTarget("left_hand"));
    document.getElementById("ikAddBoth").addEventListener("click",  () => addIKTarget("both_hands"));
    document.getElementById("ikAddLookAt").addEventListener("click",() => addIKTarget("look_at"));

    // Transitions
    document.getElementById("addTransitionBtn").addEventListener("click", () => {
        const src = bank[currentSourceKey];
        if (!src) return;
        migrateLocomotionToStances(src);
        src.transitions = src.transitions || [];
        src.transitions.push({ id: crypto.randomUUID(), from: "standing", to: "standing", template: "" });
        renderTransitionsPanel();
    });

    // Template buttons (inside templateEditor)
    document.getElementById("saveTemplateBtn").addEventListener("click", saveCurrentTemplate);
    document.getElementById("deleteTemplateBtn").addEventListener("click", deleteCurrentTemplate);
    document.getElementById("newTemplateBtn").addEventListener("click", createTemplate);
    document.getElementById("addChainClipBtn").addEventListener("click", () => {
        if (!currentTemplate) return;
        currentTemplate.chain = currentTemplate.chain || [];
        currentTemplate.chain.push({
            id: crypto.randomUUID(), clip: "", start_frame: 0,
            end_frame: null, speed: 1.0, loop: "repeat", loop_count: -1,
        });
        renderChainList(currentTemplate);
    });
    document.getElementById("playTemplateBtn").addEventListener("click", () => {
        if (currentTemplate) playTemplate(currentTemplate);
    });
    document.getElementById("addTemplateNotifyBtn").addEventListener("click", () => {
        if (!currentTemplate) return;
        currentTemplate.notifies = currentTemplate.notifies || [];
        currentTemplate.notifies.push({ id: crypto.randomUUID(), frame: 0, fps: clipFPS, event: "", payload: {} });
        renderTemplateNotifyList(currentTemplate);
    });

    // Sidebar tabs
    document.querySelectorAll(".sideTab").forEach(btn => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll(".sideTab").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById("tab-sources").classList.toggle("hidden", tab !== "sources");
            document.getElementById("tab-templates").classList.toggle("hidden", tab !== "templates");
            if (tab === "templates") renderTemplateTab();
        });
    });

    // Blend panel
    document.getElementById("blendPlayBtn").addEventListener("click", playBlended);

    // Paired load (when paired checkbox toggled)
    document.getElementById("ePaired").addEventListener("change", async (e) => {
        if (e.target.checked && currentSourceKey) {
            const src = bank[currentSourceKey];
            if (!characterB) {
                const gltf = await loader.loadAsync(src.path);
                setupCharacter(gltf, 1.2);
            }
        } else {
            if (characterB) { scene.remove(characterB); characterB = null; mixerB = null; }
        }
    });
}

function setLoopMode(mode, btnId) {
    loopMode = mode;
    document.querySelectorAll(".loopBtn").forEach(b => b.classList.remove("active"));
     document.getElementById(btnId).classList.add("active");
    if (activeAction) {
        activeAction.loop = mode;
        if (mode === THREE.LoopOnce) {
            activeAction.clampWhenFinished = true;
            activeAction.reset().play();
        }
    }

    if (activeActionB) {
        activeActionB.loop = mode;
        if (mode === THREE.LoopOnce) activeActionB.reset().play();
    }
}

// =========================================================
// BOOT
// =========================================================

initThree();
wireEvents();
loadBank();

// Set default loop button active
document.getElementById("loopRepeat").classList.add("active");
