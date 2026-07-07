import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader }    from "three/examples/jsm/loaders/GLTFLoader.js";

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
    const edH = editor.classList.contains("hidden") ? 0 : editor.offsetHeight;
    const h = main.offsetHeight - transport.offsetHeight - header.offsetHeight - edH;
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

    // Enforce start/end frame range
    if (activeAction && isPlaying) {
        const startT = startFrameToTime();
        const endT   = endFrameToTime();
        const t = activeAction.time;
        if (t >= endT) {
            if (loopMode === THREE.LoopOnce) {
                activeAction.paused = true;
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
    if (!src) return;
    currentSourceKey = sourceKey;
    clearScene();
    const gltf = await loader.loadAsync(src.path);
    setupCharacter(gltf, 0);
    rawClipsA = gltf.animations || [];
    frameAll();
    renderClipList();
}

function setupCharacter(gltf, offsetX) {
    const model = gltf.scene;
    model.position.x = offsetX;
    model.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    scene.add(model);

    if (offsetX === 0) {
        characterA = model;
        mixerA     = new THREE.AnimationMixer(model);
    } else {
        characterB = model;
        mixerB     = new THREE.AnimationMixer(model);
    }
}

function clearScene() {
    if (characterA) { scene.remove(characterA); characterA = null; mixerA = null; }
    if (characterB) { scene.remove(characterB); characterB = null; mixerB = null; }
    activeAction = null; activeActionB = null;
    rawClipsA = [];
    isPlaying = false;
    document.getElementById("playBtn").textContent = "▶";
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

    // Apply start/end frame subclip
    const startF = parseInt(document.getElementById("startFrame").value) || 0;
    const endF   = parseInt(document.getElementById("endFrame").value);
    const totalFrames = Math.round(clip.duration * clipFPS);
    const clampEnd = Math.min(endF, totalFrames);

    let playClipObj = clip;
    if (startF > 0 || clampEnd < totalFrames) {
        playClipObj = THREE.AnimationUtils.subclip(clip, clip.name + "_sub", startF, clampEnd, clipFPS);
    }

    mixerA.stopAllAction();
    activeAction = mixerA.clipAction(playClipObj);
    activeAction.loop      = loopMode;
    activeAction.clampWhenFinished = true;
    activeAction.timeScale = 1;  // speed applied in render loop via delta scaling
    activeAction.play();

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
// BANK API
// =========================================================

async function loadBank() {
    const r = await fetch("/api/animbank");
    bank = await r.json();
    renderSidebar();
    renderCategoryFilter();
    renderClipList();
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

function renderClipList() {
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
        activeAction.paused = !isPlaying;
        if (activeActionB) activeActionB.paused = !isPlaying;
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
