
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// =====================================================================
// STATE
// =====================================================================
let definitions    = {};
let sandboxChars   = [];          // { id, name, sex, age, traits, hobbies, mood, mesh, position, template, instance }
let selectedChar   = null;
let scenarioState  = 'idle';      // idle | running | paused
let showThoughts   = true;
let outfitMode     = false;       // true when Outfit tab is active
let detailItemKey  = null;        // item key currently shown in detail overlay
let detailIsEquipped = false;
window.speechInterval = 8;

// ── log filters ──
const logFilters   = new Set(['speech','thought','event','system']);
let logAll         = [];

// =====================================================================
// DEFINITIONS LOAD
// =====================================================================
async function loadDefinitions() {
  try {
    const r = await fetch('/api/editor/definitions?sim_id=default');
    definitions = await r.json();
  } catch(e) {
    definitions = {};
  }
  buildSpawnerUI();
}

// =====================================================================
// SANDBOX THREE.JS
// =====================================================================
const sbScene    = new THREE.Scene();
sbScene.background = new THREE.Color(0x141820);
sbScene.add(new THREE.AmbientLight(0xffffff, 1.2));
const sbSun      = new THREE.DirectionalLight(0xffffff, 2);
sbSun.position.set(5,10,5); sbScene.add(sbSun);
sbScene.add(new THREE.GridHelper(20, 20, 0x2a3040, 0x232933));

const sbCamera   = new THREE.PerspectiveCamera(55, 1, 0.1, 500);
sbCamera.position.set(0, 8, 12);
const sbRenderer = new THREE.WebGLRenderer({ antialias:true });
sbRenderer.setPixelRatio(window.devicePixelRatio);

const sbMount    = document.getElementById('sandboxCanvas');
sbMount.appendChild(sbRenderer.domElement);

const sbControls = new OrbitControls(sbCamera, sbRenderer.domElement);
sbControls.enableDamping = true;
sbControls.screenSpacePanning = false;
sbControls.target.set(0,0,0);
sbControls.update();

// Click plane for placement
const placePlane  = new THREE.Plane(new THREE.Vector3(0,1,0), 0);
const sbRay       = new THREE.Raycaster();

// =====================================================================
// PREVIEW THREE.JS (right panel)
// =====================================================================
const pvScene    = new THREE.Scene();
pvScene.background = new THREE.Color(0x181c22);
pvScene.add(new THREE.AmbientLight(0xffffff, 1.5));
const pvSun      = new THREE.DirectionalLight(0xffffff, 2);
pvSun.position.set(3,6,4); pvScene.add(pvSun);
pvScene.add(new THREE.GridHelper(4,4,0x2a3040,0x1e242b));

const pvCamera   = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
pvCamera.position.set(0,1.4,3.5);
pvCamera.lookAt(0,1,0);
const pvRenderer = new THREE.WebGLRenderer({ antialias:true });
pvRenderer.setPixelRatio(window.devicePixelRatio);

const pvMount    = document.getElementById('pvCanvas');
pvMount.appendChild(pvRenderer.domElement);

let pvMesh = null;
let pvRotY = 0;

// =====================================================================
// PERSPECTIVE BUTTONS
// =====================================================================
const PERSPECTIVES = {
  front: { pos:[0, 1.4, 3.5], look:[0,1,0] },
  back:  { pos:[0, 1.4,-3.5], look:[0,1,0] },
  left:  { pos:[-3.5,1.4, 0], look:[0,1,0] },
  right: { pos:[ 3.5,1.4, 0], look:[0,1,0] },
  top:   { pos:[0, 5.5, 0.01],look:[0,1,0] },
};

window.setPerspective = function(view) {
  const p = PERSPECTIVES[view];
  if (!p) return;
  pvCamera.position.set(...p.pos);
  pvCamera.lookAt(...p.look);
  document.querySelectorAll('.perspBtn').forEach(b=>b.classList.remove('active'));
  const btn = document.getElementById('persp-' + view);
  if (btn) btn.classList.add('active');
};

// =====================================================================
// OUTFIT SLOT GEOMETRY
// =====================================================================
const SLOT_COLORS = {
  head:0xff8f00, hair:0x6d4c41, torso:0x1565c0, outerwear:0x00695c,
  undershirt:0x7986cb, legs:0x37474f, feet:0x5d4037, socks:0xbdbdbd,
  hands:0x6a1b9a, neck:0xe53935, underwear:0x78909c,
  wrist_l:0xf9a825, accessory:0x558b2f
};

function makeSlotMesh(slot) {
  const col = SLOT_COLORS[slot] || 0x8888aa;
  const mat = new THREE.MeshStandardMaterial({ color:col, roughness:0.5, opacity:0.82, transparent:true });
  let geo, mesh;
  switch (slot) {
    case 'head':
      geo = new THREE.CylinderGeometry(0.27,0.24,0.10,16);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,1.86,0);
      break;
    case 'hair':
      geo = new THREE.SphereGeometry(0.30,12,8,0,Math.PI*2,0,Math.PI*0.6);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,1.64,0);
      break;
    case 'torso':
      geo = new THREE.BoxGeometry(0.70,0.98,0.64);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,0.80,0);
      break;
    case 'outerwear':
      geo = new THREE.BoxGeometry(0.80,1.10,0.72);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,0.82,0);
      break;
    case 'undershirt':
      geo = new THREE.BoxGeometry(0.64,0.88,0.60);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,0.80,0);
      break;
    case 'legs':
      geo = new THREE.CylinderGeometry(0.32,0.32,0.58,12);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,0.44,0);
      break;
    case 'feet':
      geo = new THREE.BoxGeometry(0.35,0.13,0.24);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,0.065,0);
      break;
    case 'socks':
      geo = new THREE.CylinderGeometry(0.31,0.31,0.10,12);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,0.22,0);
      break;
    case 'hands': {
      const g2 = new THREE.Group();
      const sg  = new THREE.SphereGeometry(0.10,8,6);
      [-0.42, 0.42].forEach(x => {
        const m2 = new THREE.Mesh(sg, mat.clone());
        m2.position.set(x,0.82,0);
        m2.userData.outfitSlot = slot;
        g2.add(m2);
      });
      return g2;
    }
    case 'neck':
      geo = new THREE.CylinderGeometry(0.17,0.17,0.12,12);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,1.42,0);
      break;
    case 'wrist_l':
      geo = new THREE.TorusGeometry(0.09,0.025,8,16);
      mesh = new THREE.Mesh(geo, mat);
      mesh.rotation.z = Math.PI/2;
      mesh.position.set(-0.38,0.52,0);
      break;
    case 'accessory':
      geo = new THREE.BoxGeometry(0.22,0.30,0.14);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,0.90,-0.26);
      break;
    case 'underwear':
      geo = new THREE.CylinderGeometry(0.32,0.32,0.26,12);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,0.24,0);
      break;
    default:
      // unknown slot — small cube at mid-body
      geo = new THREE.BoxGeometry(0.18,0.18,0.18);
      mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0,1.0,0.3);
  }
  return mesh;
}

function buildOutfitMeshes(char) {
  if (!pvMesh) return;
  // Remove old outfit pieces
  pvMesh.children.filter(c=>c.userData.outfitSlot).forEach(c=>pvMesh.remove(c));
  const slots = char.instance?.outfitSlots || {};
  for (const [slot, itemKey] of Object.entries(slots)) {
    if (!itemKey) continue;
    const m = makeSlotMesh(slot);
    if (!m) continue;
    m.userData.outfitSlot = slot;
    m.userData.itemKey    = itemKey;
    pvMesh.add(m);
  }
}

// =====================================================================
// OUTFIT RAYCASTER (pvCanvas click)
// =====================================================================
const pvRay = new THREE.Raycaster();
pvRenderer.domElement.addEventListener('click', e => {
  if (!outfitMode || !pvMesh || !selectedChar) return;
  const rect = pvRenderer.domElement.getBoundingClientRect();
  const ndc  = new THREE.Vector2(
    ((e.clientX - rect.left) / rect.width)  *  2 - 1,
    ((e.clientY - rect.top)  / rect.height) * -2 + 1
  );
  pvRay.setFromCamera(ndc, pvCamera);
  const outfitPieces = [];
  pvMesh.traverse(o => { if (o.userData.outfitSlot) outfitPieces.push(o); });
  const hits = pvRay.intersectObjects(outfitPieces, true);
  if (!hits.length) { closeItemDetail(); return; }
  let obj = hits[0].object;
  while (obj && !obj.userData.itemKey) obj = obj.parent;
  if (obj?.userData.itemKey) showItemDetail(obj.userData.itemKey, true);
});

// =====================================================================
// ITEM DETAIL OVERLAY
// =====================================================================
window.showItemDetail = function(itemKey, isEquipped=false) {
  detailItemKey    = itemKey;
  detailIsEquipped = isEquipped;
  const tmpl = definitions.item_templates?.[itemKey] || {};
  document.getElementById('detailItemName').textContent = tmpl.name || itemKey;
  const rows = [
    ['Slot',   tmpl.slot   || '—'],
    ['Price',  tmpl.base_price != null ? '$' + tmpl.base_price : null],
    ['Style',  tmpl.style  != null ? (tmpl.style*100).toFixed(0) + '%' : null],
    ['Warmth', tmpl.warmth != null ? (tmpl.warmth*100).toFixed(0) + '%' : null],
    ['Size',   tmpl.size   != null ? tmpl.size : null],
    ['Bone',   tmpl.bone   || null],
  ].filter(([,v])=>v!=null);
  document.getElementById('detailBody').innerHTML = rows.map(([k,v]) =>
    '<div class="detailRow"><span>' + k + '</span><span>' + v + '</span></div>'
  ).join('');
  document.getElementById('detailEquipBtn').style.display   = isEquipped ? 'none' : '';
  document.getElementById('detailUnequipBtn').style.display = isEquipped ? '' : 'none';
  document.getElementById('itemDetailOverlay').style.display = '';
};

window.closeItemDetail = function() {
  document.getElementById('itemDetailOverlay').style.display = 'none';
  detailItemKey = null;
};

window.equipFromDetail = function() {
  if (!detailItemKey || !selectedChar) return;
  equipItem(detailItemKey);
  showItemDetail(detailItemKey, true);
  renderOutfitTab();
};

window.unequipFromDetail = function() {
  if (!detailItemKey || !selectedChar) return;
  const tmpl = definitions.item_templates?.[detailItemKey] || {};
  const slot = tmpl.slot || '?';
  if (selectedChar.instance.outfitSlots[slot] === detailItemKey) {
    selectedChar.instance.outfitSlots[slot] = null;
    buildOutfitMeshes(selectedChar);
    closeItemDetail();
    renderOutfitTab();
  }
};

function equipItem(itemKey) {
  if (!selectedChar) return;
  const tmpl = definitions.item_templates?.[itemKey] || {};
  const slot = tmpl.slot || '?';
  selectedChar.instance.outfitSlots[slot] = itemKey;
  buildOutfitMeshes(selectedChar);
  addLog('system', selectedChar.id, selectedChar.name + ' equipped: ' + (tmpl.name||itemKey) + ' [' + slot + ']');
}

// =====================================================================
// OUTFIT TAB RENDER
// =====================================================================
function renderOutfitTab() {
  if (!selectedChar) return;
  const slots = selectedChar.instance.outfitSlots || {};

  // Worn slots chips
  const slotsDiv = document.getElementById('outfitSlots');
  const worn = Object.entries(slots).filter(([,v])=>v);
  if (!worn.length) {
    slotsDiv.innerHTML = '<span style="color:#3a4050;font-size:12px">Nothing worn</span>';
  } else {
    slotsDiv.innerHTML = worn.map(([slot, key]) => {
      const t = definitions.item_templates?.[key] || {};
      return '<span class="slotChip worn" onclick="showItemDetail(\'' + key + '\',true)" title="Click to inspect / remove">' +
        slot + ': ' + escHtml(t.name||key) + '</span>';
    }).join('');
  }

  // Clothing catalog grouped by slot
  const listDiv = document.getElementById('clothingList');
  const items   = definitions.item_templates || {};
  const clothing = Object.entries(items)
    .filter(([,v])=>v.category==='clothing')
    .sort((a,b)=>(a[1].slot||'zzz').localeCompare(b[1].slot||'zzz') || (a[1].name||'').localeCompare(b[1].name||''));

  listDiv.innerHTML = '';
  let lastSlot = null;
  for (const [key, tmpl] of clothing) {
    const slot = tmpl.slot || '?';
    if (slot !== lastSlot) {
      lastSlot = slot;
      const lbl = document.createElement('div');
      lbl.className = 'slotGroupLabel';
      lbl.textContent = slot;
      listDiv.appendChild(lbl);
    }
    const isEquipped = slots[slot] === key;
    const row = document.createElement('div');
    row.className = 'clothingRow' + (isEquipped ? ' equipped' : '');
    row.innerHTML =
      '<div><div class="cName">' + escHtml(tmpl.name||key) + '</div>' +
      '<div class="cMeta">' + (tmpl.base_price?'$'+tmpl.base_price+' · ':'') + slot + '</div></div>' +
      '<div>' + (isEquipped ? '<span class="cEquipHint">✓ on</span>' : '<span class="cDblHint">dbl-click</span>') + '</div>';
    row.onclick    = () => showItemDetail(key, isEquipped);
    row.ondblclick = (e) => {
      e.preventDefault();
      equipItem(key);
      renderOutfitTab();
      showItemDetail(key, true);
    };
    listDiv.appendChild(row);
  }
}

// =====================================================================
// RESIZE OBSERVERS
// =====================================================================
new ResizeObserver(() => {
  const w = sbMount.clientWidth, h = sbMount.clientHeight;
  sbRenderer.setSize(w, h);
  sbCamera.aspect = w / (h||1);
  sbCamera.updateProjectionMatrix();
}).observe(sbMount);

new ResizeObserver(() => {
  const w = pvMount.clientWidth, h = pvMount.clientHeight;
  pvRenderer.setSize(w, h);
  pvCamera.aspect = w / (h||1);
  pvCamera.updateProjectionMatrix();
}).observe(pvMount);

// =====================================================================
// RENDER LOOP
// =====================================================================
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = clock.getDelta();
  sbControls.update();
  sbRenderer.render(sbScene, sbCamera);
  if (!outfitMode) {
    pvRotY += dt * 0.4;
    if (pvMesh) pvMesh.rotation.y = pvRotY;
  }
  pvRenderer.render(pvScene, pvCamera);
}
animate();

// =====================================================================
// MOOD COLORS
// =====================================================================
const MOOD_COLORS = {
  content:0x4caf50, cheerful:0x8bc34a, playful:0xffeb3b,
  focused:0x2196f3, romantic:0xe91e63, restless:0xff9800,
  lonely:0x9e9e9e, anxious:0xffc107, irritable:0xff5722,
  sad:0x607d8b, grieving:0x455a64, depressed:0x263238,
  furious:0xf44336, embarrassed:0xce93d8, energized:0x76ff03
};
function moodColor(mood) { return MOOD_COLORS[mood] || 0x7986cb; }

// =====================================================================
// CHARACTER CAPSULE MESH
// =====================================================================
function makeCapsule(color) {
  const g = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({ color, roughness:0.6 });
  // Body cylinder
  const body = new THREE.Mesh(new THREE.CylinderGeometry(0.3,0.3,1.0,16), mat);
  body.position.y = 0.8;
  g.add(body);
  // Head sphere
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.28,16,12), mat);
  head.position.y = 1.6;
  g.add(head);
  // Feet hemisphere
  const feet = new THREE.Mesh(new THREE.CylinderGeometry(0.28,0.3,0.3,12), mat);
  feet.position.y = 0.22;
  g.add(feet);
  return g;
}

function makeNameSprite(name, color) {
  const canvas = document.createElement('canvas');
  canvas.width = 256; canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.roundRect(4,8,248,48,12);
  ctx.fill();
  ctx.fillStyle = '#' + (color||0xaaddff).toString(16).padStart(6,'0');
  ctx.font = 'bold 28px Arial';
  ctx.textAlign = 'center';
  ctx.fillText(name, 128, 42);
  const tex = new THREE.CanvasTexture(canvas);
  const mat = new THREE.SpriteMaterial({ map:tex, depthTest:false });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(1.2, 0.3, 1);
  sprite.position.set(0, 2.1, 0);
  return sprite;
}

// =====================================================================
// SPAWNER UI
// =====================================================================
function buildSpawnerUI() {
  // Mood select
  const moodSel = document.getElementById('spMood');
  moodSel.innerHTML = '';
  for (const key of Object.keys(definitions.mood_templates||{})) {
    const o = document.createElement('option');
    o.value = key; o.textContent = key.replace(/_/g,' ');
    moodSel.appendChild(o);
  }
  if (!moodSel.value) { const o=document.createElement('option'); o.value='content'; o.textContent='content'; moodSel.appendChild(o); }

  // Trait chips
  const tc = document.getElementById('traitChips');
  tc.innerHTML = '';
  for (const [key, tmpl] of Object.entries(definitions.trait_templates||{})) {
    const chip = document.createElement('span');
    chip.className = 'chip trait-' + (tmpl.polarity==='negative'?'neg':'pos');
    chip.textContent = tmpl.name || key;
    chip.dataset.key = key;
    chip.onclick = () => {
      const selected = tc.querySelectorAll('.chip.on').length;
      if (!chip.classList.contains('on') && selected >= 5) return;
      chip.classList.toggle('on');
    };
    tc.appendChild(chip);
  }

  // Hobby chips
  const hc = document.getElementById('hobbyChips');
  hc.innerHTML = '';
  for (const [key] of Object.entries(definitions.hobby_templates||{})) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = key.replace(/_/g,' ');
    chip.dataset.key = key;
    chip.onclick = () => {
      const selected = hc.querySelectorAll('.chip.on').length;
      if (!chip.classList.contains('on') && selected >= 3) return;
      chip.classList.toggle('on');
    };
    hc.appendChild(chip);
  }
}

// =====================================================================
// SPAWNER DRAWER TOGGLE
// =====================================================================
let spawnerOpen = true;
window.toggleSpawner = function() {
  spawnerOpen = !spawnerOpen;
  const form = document.getElementById('spawnerForm');
  form.style.display = spawnerOpen ? 'flex' : 'none';
  document.getElementById('spawnerArrow').textContent = spawnerOpen ? '▲' : '▼';
};

// =====================================================================
// SPAWN CHARACTER
// =====================================================================
let charIdCounter = 0;
window.spawnCharacter = function() {
  const name    = document.getElementById('spName').value.trim() || ('Char_' + (++charIdCounter));
  const sex     = document.getElementById('spSex').value;
  const age     = parseInt(document.getElementById('spAge').value) || 28;
  const mood    = document.getElementById('spMood').value || 'content';
  const app     = document.getElementById('spAppearance').value.trim();
  const traits  = [...document.querySelectorAll('#traitChips .chip.on')].map(c=>c.dataset.key);
  const hobbies = [...document.querySelectorAll('#hobbyChips .chip.on')].map(c=>c.dataset.key);

  const id = 'char_' + Date.now().toString(36);
  const color = moodColor(mood);

  const template = {
    id, name, sex, age, appearance: app,
    traits, hobbies,
    model: 'adult_male',
    base_animations: { idle:'idle', walk:'walk' },
    inventory_slots: { left_hand:1, right_hand:1, back:1, belt:4, pockets:4 }
  };

  const instance = buildInstance(id, name, sex, age, mood, traits, hobbies);

  // Build mesh
  const mesh = makeCapsule(color);
  const sprite = makeNameSprite(name, color);
  mesh.add(sprite);
  mesh.userData = { charId:id };

  // Default position: cluster near center with jitter
  const angle = Math.random() * Math.PI * 2;
  const r     = sandboxChars.length === 0 ? 0 : 1.5 + sandboxChars.length * 0.4;
  const px    = Math.cos(angle) * r;
  const pz    = Math.sin(angle) * r;
  mesh.position.set(px, 0, pz);

  sbScene.add(mesh);

  const char = { id, name, sex, age, mood, traits, hobbies, appearance:app, color, mesh, template, instance };
  sandboxChars.push(char);

  updateCharCount();
  addLog('system', null, name + ' spawned (' + sex + ', ' + age + ', ' + mood + ')');
  selectChar(id);

  // Enable scenario if >= 2 chars
  if (sandboxChars.length >= 2) {
    document.getElementById('btnStart').disabled = false;
    document.getElementById('scenarioStatus').textContent = sandboxChars.length + ' characters ready';
  }
};

function buildInstance(id, name, sex, age, mood, traits, hobbies) {
  return {
    id, name, sex, age,
    posture:   'standing',
    location:  'sandbox',
    activity:  null,
    mood:      mood,
    mood_intensity: 0.6,
    traits,
    hobbies,
    needs: { hunger:0.6, energy:0.8, social:0.5, hygiene:0.9, fun:0.5, bladder:0.8 },
    emotions: { happiness:0.6, anger:0.0, fear:0.0, sadness:0.0, surprise:0.0 },
    relationships: {},
    memory:    [],
    inventory: {},
    outfitSlots: {
      hair:null, head:null, torso:null, outerwear:null, undershirt:null,
      legs:null, feet:null, socks:null, hands:null, neck:null,
      wrist_l:null, underwear:null, accessory:null
    },
    current_thought: null,
    last_speech: null,
  };
}

function updateCharCount() {
  document.getElementById('charCountBadge').textContent = sandboxChars.length + ' character' + (sandboxChars.length!==1?'s':'');
}

// =====================================================================
// SELECTION
// =====================================================================
function selectChar(id) {
  selectedChar = sandboxChars.find(c=>c.id===id) || null;
  // Highlight selected
  sandboxChars.forEach(c => {
    c.mesh.traverse(o => {
      if (o.isMesh) {
        o.material.emissive = new THREE.Color(c===selectedChar ? 0x223355 : 0x000000);
      }
    });
  });
  if (selectedChar) {
    document.getElementById('charHeaderName').textContent = selectedChar.name;
    document.getElementById('charHeaderName').style.color = '#' + selectedChar.color.toString(16).padStart(6,'0');
    document.getElementById('noCharMsg').style.display = 'none';
    buildPreviewChar(selectedChar);
    refreshAllTabs();
    document.getElementById('btnEscalate').disabled = false;
  }
}

// =====================================================================
// SANDBOX CLICK (select or place)
// =====================================================================
sbRenderer.domElement.addEventListener('click', e => {
  const rect = sbRenderer.domElement.getBoundingClientRect();
  const ndc  = new THREE.Vector2(
    ((e.clientX - rect.left) / rect.width)  *  2 - 1,
    ((e.clientY - rect.top)  / rect.height) * -2 + 1
  );
  sbRay.setFromCamera(ndc, sbCamera);

  // Check if clicking a character
  const meshes = sandboxChars.map(c=>c.mesh);
  const hits   = sbRay.intersectObjects(meshes, true);
  if (hits.length) {
    let obj = hits[0].object;
    while (obj && !obj.userData.charId) obj = obj.parent;
    if (obj?.userData.charId) { selectChar(obj.userData.charId); return; }
  }
});

// =====================================================================
// PREVIEW CHARACTER (right panel Three.js)
// =====================================================================
function buildPreviewChar(char) {
  if (pvMesh) { pvScene.remove(pvMesh); pvMesh = null; }
  pvMesh = makeCapsule(char.color);
  pvMesh.position.set(0,0,0);
  pvScene.add(pvMesh);
  pvRotY = 0;
  buildOutfitMeshes(char);
}

// =====================================================================
// INSPECTOR TABS
// =====================================================================
window.switchTab = function(el) {
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('#tabContent > div').forEach(d=>d.style.display='none');
  const panel = document.getElementById('tab-' + el.dataset.tab);
  if (panel) panel.style.display = '';
  outfitMode = (el.dataset.tab === 'outfit');
  if (!outfitMode) closeItemDetail();
  refreshTab(el.dataset.tab);
};

function refreshAllTabs() {
  const activeTab = document.querySelector('.tab.active')?.dataset.tab || 'appearance';
  refreshTab(activeTab);
}

function refreshTab(tab) {
  if (!selectedChar) return;
  if (tab==='outfit')     renderOutfitTab();
  if (tab==='appearance') renderAppearanceTab();
  if (tab==='state')      renderStateTab();
  if (tab==='runtime')    document.getElementById('runtimeJson').textContent = JSON.stringify(selectedChar.instance, null,2);
  if (tab==='template')   document.getElementById('templateJson').textContent = JSON.stringify(selectedChar.template, null,2);
  if (tab==='log')        renderLogTab();
  if (tab==='prompts')    renderPromptsTab();
  if (tab==='family')     window._refreshFamilyTab && window._refreshFamilyTab();
}

// =====================================================================
// PROMPTS TAB
// =====================================================================

let _promptLog = [];

async function renderPromptsTab() {
  if (!selectedChar) return;
  await refreshPromptLog(false);
}

window.refreshPromptLog = async function(scroll=true) {
  if (!selectedChar) return;
  const charId = selectedChar.id;
  const statusEl = document.getElementById('promptLogStatus');
  statusEl.textContent = 'Loading…';
  try {
    const res = await fetch(`/debug/prompt-log/${encodeURIComponent(charId)}`);
    const data = await res.json();
    _promptLog = data.entries || [];
    renderPromptEntries();
    statusEl.textContent = `${_promptLog.length} entries for ${charId}`;
  } catch(e) {
    statusEl.textContent = 'Error: ' + e.message;
  }
};

window.clearPromptLog = async function() {
  if (!selectedChar) return;
  await fetch(`/debug/prompt-log/${encodeURIComponent(selectedChar.id)}`, {method:'DELETE'});
  _promptLog = [];
  renderPromptEntries();
  document.getElementById('promptLogStatus').textContent = 'Cleared';
};

function renderPromptEntries() {
  const container = document.getElementById('promptLogEntries');
  if (!_promptLog.length) {
    container.innerHTML = '<div style="color:#445;font-size:12px;padding:10px 0">No LLM calls logged yet for this character.</div>';
    return;
  }
  container.innerHTML = _promptLog.map((e, idx) => {
    const ts = new Date(e.ts * 1000).toLocaleTimeString();
    const msgs = e.messages || [];
    const sysPart = msgs.find(m => m.role === 'system');
    const userPart = msgs.find(m => m.role === 'user');
    const sysPreview = sysPart ? sysPart.content.slice(0, 80) + (sysPart.content.length > 80 ? '…' : '') : '—';
    return `<div class="promptEntry">
      <div class="promptEntryHead" onclick="togglePromptEntry(${idx})">
        <span style="color:#aaa">#${_promptLog.length - idx}</span>
        <span style="color:#7af;font-size:10px">${e.elapsed_s}s</span>
        <span class="peBadge ${e.cached ? 'cached' : 'live'}">${e.cached ? 'cached' : 'live'}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#667">${escHtml(sysPreview)}</span>
        <button class="promptLoadBtn" onclick="event.stopPropagation();loadPromptIntoCompose(${idx})">Edit &amp; Send</button>
        <span class="peTime">${ts}</span>
      </div>
      <div id="promptEntry-${idx}" style="display:none">
        <div class="promptSection">
          <div class="psLabel">System Prompt</div>
          <pre>${escHtml(sysPart ? sysPart.content : '—')}</pre>
        </div>
        <div class="promptSection">
          <div class="psLabel">User Prompt</div>
          <pre>${escHtml(userPart ? userPart.content : '—')}</pre>
        </div>
        <div class="promptSection response">
          <div class="psLabel">Response</div>
          <pre>${escHtml(typeof e.response === 'string' ? e.response : JSON.stringify(e.response, null, 2))}</pre>
        </div>
      </div>
    </div>`;
  }).join('');
}

window.togglePromptEntry = function(idx) {
  const el = document.getElementById('promptEntry-' + idx);
  if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
};

window.loadPromptIntoCompose = function(idx) {
  const e = _promptLog[idx];
  if (!e) return;
  const msgs = e.messages || [];
  const sys  = msgs.find(m => m.role === 'system');
  const user = msgs.find(m => m.role === 'user');
  document.getElementById('promptSysInput').value  = sys  ? sys.content  : '';
  document.getElementById('promptUserInput').value = user ? user.content : '';
  document.getElementById('promptResponseBox').textContent = '—';
  document.getElementById('promptSendStatus').textContent = '';
};

window.loadLastPromptIntoCompose = function() {
  if (_promptLog.length) loadPromptIntoCompose(0);
};

window.sendCustomPrompt = async function() {
  if (!selectedChar) return;
  const sys  = document.getElementById('promptSysInput').value.trim();
  const user = document.getElementById('promptUserInput').value.trim();
  const statusEl = document.getElementById('promptSendStatus');
  const respBox  = document.getElementById('promptResponseBox');
  if (!sys && !user) { statusEl.textContent = 'Nothing to send'; return; }
  statusEl.textContent = 'Sending…';
  respBox.textContent = '…';
  try {
    const res = await fetch('/debug/prompt-send', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        char_id: selectedChar.id,
        system_prompt: sys,
        user_prompt: user,
        use_cache: false
      })
    });
    const data = await res.json();
    const raw = data.raw_response;
    respBox.textContent = typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2);
    statusEl.textContent = `${data.elapsed_s}s • valid=${data.valid}${data.parse_error ? ' ⚠ '+data.parse_error : ''}`;
    // Add to local log immediately
    _promptLog.unshift({
      ts: Date.now() / 1000,
      messages: [
        {role:'system', content: sys},
        {role:'user',   content: user}
      ],
      response: raw,
      elapsed_s: data.elapsed_s,
      cached: false
    });
    renderPromptEntries();
  } catch(e) {
    statusEl.textContent = 'Error: ' + e.message;
    respBox.textContent = '—';
  }
};

// ── Appearance tab ──
function renderAppearanceTab() {
  const c = selectedChar;
  const traits = (c.traits||[]).map(t=>{
    const tmpl = definitions.trait_templates?.[t] || {};
    const cls  = tmpl.polarity==='negative' ? 'traitBadge neg' : 'traitBadge';
    return '<span class="' + cls + '">' + (tmpl.name||t) + '</span>';
  }).join('');
  const hobbies = (c.hobbies||[]).map(h=>'<span class="traitBadge" style="background:#1a2040;border-color:#2e4da4;color:#adf">' + h.replace(/_/g,' ') + '</span>').join('');
  document.getElementById('tab-appearance').innerHTML = '<div class="fieldGrid">' +
    '<label>Name</label><input value="' + c.name + '" oninput="updateCharField(\'name\',this.value)">' +
    '<label>Sex</label><select onchange="updateCharField(\'sex\',this.value)">' +
    ['male','female','other'].map(s=>'<option'+(c.sex===s?' selected':'')+'>'+s+'</option>').join('') + '</select>' +
    '<label>Age</label><input type="number" value="' + c.age + '" style="width:70px" oninput="updateCharField(\'age\',+this.value)">' +
    '<label>Appearance</label><input value="' + (c.appearance||'') + '" oninput="updateCharField(\'appearance\',this.value)">' +
    '</div>' +
    '<div class="sectionHead">Traits</div><div>' + (traits||'<span style="color:#445">None selected</span>') + '</div>' +
    '<div class="sectionHead">Hobbies</div><div>' + (hobbies||'<span style="color:#445">None selected</span>') + '</div>';
}

window.updateCharField = function(field, val) {
  if (!selectedChar) return;
  selectedChar[field] = val;
  selectedChar.template[field] = val;
  selectedChar.instance[field] = val;
  if (field==='name') {
    document.getElementById('charHeaderName').textContent = val;
  }
};

// ── State tab ──
const NEED_COLORS = { hunger:'#ef6c00', energy:'#fdd835', social:'#42a5f5', hygiene:'#66bb6a', fun:'#ab47bc', bladder:'#26c6da' };
const EMO_COLORS  = { happiness:'#4caf50', anger:'#f44336', fear:'#ff9800', sadness:'#607d8b', surprise:'#ce93d8' };

function renderStateTab() {
  const c = selectedChar;
  const inst = c.instance;
  const moodCol = moodColor(inst.mood);
  let html = '<div class="moodPill" style="background:#' + moodCol.toString(16).padStart(6,'0') + '22;border:1px solid #' + moodCol.toString(16).padStart(6,'0') + ';color:#fff">' +
    '\u{1F636} Mood: <b>' + (inst.mood||'unknown') + '</b> ' +
    '<input class="editableVal" type="number" min="0" max="1" step="0.05" value="' + (inst.mood_intensity||0.5).toFixed(2) + '" oninput="setInstField(\'mood_intensity\',+this.value)" style="width:55px"></div>';

  html += '<div class="sectionHead">Needs</div>';
  for (const [k,v] of Object.entries(inst.needs||{})) {
    const col = NEED_COLORS[k]||'#aaa';
    const pct  = Math.round((v||0)*100);
    html += '<div class="meterRow"><span class="meterLabel">' + k + '</span>' +
      '<div class="meterBar"><div class="meterFill" style="width:' + pct + '%;background:' + col + '"></div></div>' +
      '<input class="editableVal" type="number" min="0" max="1" step="0.05" value="' + (v||0).toFixed(2) + '" oninput="setNeed(\'' + k + '\',+this.value)">' +
      '</div>';
  }

  html += '<div class="sectionHead">Emotions</div>';
  for (const [k,v] of Object.entries(inst.emotions||{})) {
    const col = EMO_COLORS[k]||'#aaa';
    const pct  = Math.round((v||0)*100);
    html += '<div class="meterRow"><span class="meterLabel">' + k + '</span>' +
      '<div class="meterBar"><div class="meterFill" style="width:' + pct + '%;background:' + col + '"></div></div>' +
      '<input class="editableVal" type="number" min="0" max="1" step="0.05" value="' + (v||0).toFixed(2) + '" oninput="setEmotion(\'' + k + '\',+this.value)">' +
      '</div>';
  }

  html += '<div class="sectionHead">Mood override</div>';
  html += '<select onchange="setInstField(\'mood\',this.value)" style="background:#1a1e24;border:1px solid #3a3f48;color:#ccc;padding:4px 8px;border-radius:4px;width:100%;font-size:12px">';
  for (const key of Object.keys(definitions.mood_templates||{content:{}})) {
    html += '<option' + (inst.mood===key?' selected':'') + ' value="' + key + '">' + key + '</option>';
  }
  html += '</select>';

  document.getElementById('tab-state').innerHTML = html;
}

window.setNeed      = function(k,v) { if(selectedChar) { selectedChar.instance.needs[k]=v; refreshTab('state'); } };
window.setEmotion   = function(k,v) { if(selectedChar) { selectedChar.instance.emotions[k]=v; refreshTab('state'); } };
window.setInstField = function(k,v) {
  if (!selectedChar) return;
  selectedChar.instance[k] = v;
  if (k==='mood') {
    selectedChar.mood = v;
    const col = moodColor(v);
    selectedChar.color = col;
    selectedChar.mesh.traverse(o => { if(o.isMesh) o.material.color.set(col); });
    // Only recolor base capsule, not outfit pieces
    if (pvMesh) pvMesh.traverse(o => { if(o.isMesh && !o.userData.outfitSlot) o.material.color.set(col); });
    refreshTab('state');
  }
};

// =====================================================================
// LOG
// =====================================================================
function addLog(type, charId, text) {
  const entry = { ts: new Date(), type, charId, text };
  logAll.push(entry);
  if (logAll.length > 500) logAll.splice(0, logAll.length-500);
  if (document.querySelector('.tab.active')?.dataset.tab === 'log') renderLogTab();
}
window.addLog = addLog;

function renderLogTab() {
  const container = document.getElementById('logEntries');
  container.innerHTML = '';
  const filtered = [...logAll].reverse().filter(e=>logFilters.has(e.type));
  for (const e of filtered.slice(0,100)) {
    const div = document.createElement('div');
    div.className = 'logEntry ' + e.type;
    const ts = e.ts.toTimeString().slice(0,8);
    const charName = sandboxChars.find(c=>c.id===e.charId)?.name || '';
    div.innerHTML = '<div class="logMeta"><span class="logCharName">' + (charName||'System') + '</span> ' +
      '<span class="logType ' + e.type + '">' + e.type + '</span> <span style="color:#445">' + ts + '</span></div>' +
      '<div style="color:#ccd">' + escHtml(e.text) + '</div>';
    container.appendChild(div);
  }
}

window.toggleLogFilter = function(btn) {
  btn.classList.toggle('on');
  const f = btn.dataset.filter;
  if (logFilters.has(f)) logFilters.delete(f); else logFilters.add(f);
  renderLogTab();
};
window.clearLog = function() { logAll = []; renderLogTab(); };

function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// =====================================================================
// SCENARIO CONTROLS
// =====================================================================
let scenarioTimer = null;

window.startScenario = function() {
  if (sandboxChars.length < 2) { addLog('system',null,'Need at least 2 characters'); return; }
  scenarioState = 'running';
  document.getElementById('btnStart').disabled  = true;
  document.getElementById('btnPause').disabled  = false;
  document.getElementById('btnStop').disabled   = false;
  document.getElementById('scenarioStatus').textContent = 'Running — ' + document.getElementById('scenarioSelect').value;
  addLog('system', null, 'Scenario started: ' + document.getElementById('scenarioSelect').value);
  scheduleNextTurn();
};

window.pauseScenario = function() {
  if (scenarioState === 'running') {
    scenarioState = 'paused';
    clearTimeout(scenarioTimer);
    document.getElementById('btnStart').textContent = '▶ Resume';
    document.getElementById('btnStart').disabled    = false;
    document.getElementById('btnPause').disabled    = true;
    document.getElementById('scenarioStatus').textContent = 'Paused';
    addLog('system', null, 'Scenario paused');
  } else if (scenarioState === 'paused') {
    scenarioState = 'running';
    document.getElementById('btnStart').textContent = '▶ Start';
    document.getElementById('btnStart').disabled    = true;
    document.getElementById('btnPause').disabled    = false;
    document.getElementById('scenarioStatus').textContent = 'Resumed';
    scheduleNextTurn();
  }
};

window.stopScenario = function() {
  scenarioState = 'idle';
  clearTimeout(scenarioTimer);
  document.getElementById('btnStart').textContent = '▶ Start';
  document.getElementById('btnStart').disabled    = sandboxChars.length < 2;
  document.getElementById('btnPause').disabled    = true;
  document.getElementById('btnStop').disabled     = true;
  document.getElementById('scenarioStatus').textContent = 'Stopped';
  addLog('system', null, 'Scenario stopped');
};

window.triggerEscalation = function() {
  if (!selectedChar) return;
  selectedChar.instance.emotions.anger = Math.min(1, (selectedChar.instance.emotions.anger||0) + 0.4);
  selectedChar.instance.mood = 'furious';
  setInstField('mood', 'furious');
  addLog('event', selectedChar.id, selectedChar.name + ' mood escalated to FURIOUS');
  refreshTab('state');
};

function scheduleNextTurn() {
  if (scenarioState !== 'running') return;
  const jitter = (Math.random() * 0.4 + 0.8);
  scenarioTimer = setTimeout(() => {
    runConversationTurn();
    scheduleNextTurn();
  }, window.speechInterval * 1000 * jitter);
}

// Stub — Phase 2 will call backend LLM
function runConversationTurn() {
  if (!sandboxChars.length) return;
  const speaker  = sandboxChars[Math.floor(Math.random()*sandboxChars.length)];
  const listener = sandboxChars.find(c=>c.id!==speaker.id);
  const placeholders = [
    'Interesting weather today, right?',
    'I was just thinking about that earlier.',
    'Do you come here often?',
    'That reminds me of something.',
    'I completely agree with that.',
    'Hmm, not sure about that one.',
    'Have you heard about the news?',
    'Tell me more.',
    '... (silence)',
  ];
  const thought_phs = [
    'This conversation is going well.',
    'I wonder if they trust me.',
    'Should I bring up the topic?',
    'I feel a bit nervous.',
    'This person seems interesting.',
  ];
  const said = placeholders[Math.floor(Math.random()*placeholders.length)];
  addLog('speech', speaker.id, said);
  speaker.instance.last_speech = said;
  if (showThoughts && Math.random() > 0.5) {
    const thought = thought_phs[Math.floor(Math.random()*thought_phs.length)];
    addLog('thought', speaker.id, thought);
    speaker.instance.current_thought = thought;
  }
  if (speaker.instance.needs.social < 1)
    speaker.instance.needs.social = Math.min(1,(speaker.instance.needs.social||0.5)+0.05);
  if (listener && listener.instance.needs.social < 1)
    listener.instance.needs.social = Math.min(1,(listener.instance.needs.social||0.5)+0.03);
  if (document.querySelector('.tab.active')?.dataset.tab==='log') renderLogTab();
  if (selectedChar && (selectedChar.id===speaker.id || selectedChar.id===listener?.id)) {
    if (document.querySelector('.tab.active')?.dataset.tab==='state') renderStateTab();
  }
}

// =====================================================================
// THOUGHTS TOGGLE
// =====================================================================
window.toggleThoughts = function(val) { showThoughts = val; };

// =====================================================================
// INIT
// =====================================================================
await loadDefinitions();

// =====================================================================
// FAMILY TAB
// =====================================================================

window.generateFamilyTree = async function(replace=false) {
  if (!selectedChar) { alert('Select a character first.'); return; }
  const charId  = selectedChar.id;
  const depth   = document.getElementById('familyDepth2')?.checked ? 2 : 1;
  const statusEl = document.getElementById('familyStatus');
  const treeEl   = document.getElementById('familyTree');

  statusEl.textContent = 'Generating…';
  treeEl.innerHTML = '';

  try {
    const res = await fetch(`/api/editor/characters/${charId}/generate_family`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ sim_id: 'default', depth, replace }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);

    const fam = data.family;
    statusEl.textContent = data.already_existed
      ? `Existing family loaded — ${fam.size} members`
      : `Generated — ${fam.size} members (depth ${depth})`;

    // Render the tree
    treeEl.innerHTML = _renderFamilyHTML(fam, charId);

    // Refresh instance data (family_id is now set)
    const worldRes = await fetch('/api/editor/world?sim_id=default');
    const world    = await worldRes.json();
    const updated  = world?.characters?.[charId];
    if (updated) selectedChar.instance = updated;

  } catch(e) {
    statusEl.textContent = '⚠ ' + e.message;
    console.error('[family]', e);
  }
};

function _renderFamilyHTML(fam, focusId) {
  // Group members by role order
  const roleOrder = ['grandparent','parent','spouse','head','sibling','in_law','child','aunt_uncle','cousin','ex_spouse','other'];
  const members = [...fam.members].sort((a,b) => {
    return (roleOrder.indexOf(a.role ?? 'other') - roleOrder.indexOf(b.role ?? 'other'));
  });

  const roleColors = {
    grandparent: '#8a7',  parent: '#7ab',  spouse: '#da8',
    sibling:     '#a9c',  child:  '#7c9',  in_law: '#98a',
    aunt_uncle:  '#b97',  cousin: '#8ba',  ex_spouse: '#a77',
    head:        '#adf',  other:  '#778',
  };

  let html = `<div style="font-size:10px;color:#445;margin-bottom:6px;text-transform:uppercase;letter-spacing:.07em">
    ${fam.surname} Family — ${fam.size} members
  </div>`;

  for (const m of members) {
    const isFocus  = m.id === focusId;
    const col      = roleColors[m.role] || '#778';
    const roleTag  = m.role ? `<span style="color:${col};font-size:10px">[${m.role}]</span>` : '';
    const offTag   = m.offscreen ? ' <span style="color:#333;font-size:9px">(off-screen)</span>' : '';
    const focusMark= isFocus ? ' ★' : '';
    const rels     = Object.entries(m.relations_to_others || {});

    html += `<div style="border-left:2px solid ${isFocus ? '#2e86c1' : '#2a3040'};
      padding:5px 8px;margin-bottom:4px;background:${isFocus ? '#111d2a' : '#13171d'}">
      <div style="color:${isFocus ? '#adf' : '#ccd'};font-size:12px">${m.name}${focusMark} ${offTag}</div>
      <div style="font-size:10px;color:#445">age ${m.age} · ${m.sex} ${roleTag}</div>`;

    if (rels.length) {
      const relStr = rels.map(([name, rel]) =>
        `<span style="color:#445">${name}</span> <span style="color:#667">(${rel})</span>`
      ).join(' · ');
      html += `<div style="font-size:10px;margin-top:2px">${relStr}</div>`;
    }
    html += '</div>';
  }
  return html;
}

// Hook into refreshTab
const _origRefreshTab = refreshTab;
// Patch refreshTab by re-declaring (module scope safe via closure)
window._refreshFamilyTab = function() {
  if (!selectedChar) return;
  const fam_id = selectedChar.instance?.family_id;
  const statusEl = document.getElementById('familyStatus');
  const treeEl   = document.getElementById('familyTree');
  if (!fam_id) {
    if (statusEl) statusEl.textContent = 'No family tree yet — click Generate.';
    if (treeEl)   treeEl.innerHTML = '';
  }
};
