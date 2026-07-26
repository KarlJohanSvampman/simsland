
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// =====================================================================
// STATE
// =====================================================================
let definitions    = {};
// { id, sandboxId, serverChar /* trimmed view from stage/turn */, mesh, color,
//   _fullChar /* cached full character dict, fetched on demand -- see fetchFullChar() */ }
let sandboxChars   = [];
let currentSandboxId = null;      // all staged characters currently share one sandbox
let selectedChar   = null;
let showThoughts   = true;
let outfitMode     = false;       // true when Outfit tab is active
let detailItemKey  = null;        // item key currently shown in detail overlay
let detailIsEquipped = false;
window.speechInterval = 8;

// ── turn engine (Round 3) ──
let turnInFlight     = false;   // in-flight guard -- never overlap /turn calls
let autoAdvanceOn    = false;
let autoAdvanceTimer = null;

// ── absent relationships (Round 5) ──
// { name, relation_label, charIndex } -- charIndex is a position into
// sandboxChars, replayed as relationship_to_index on every /stage call
// (see stageSelectedTemplate() -- staged ids are re-minted every call, but
// sandboxChars' own ordering is stable since characters are only ever
// appended, never removed or reordered).
let pendingAbsent = [];

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
  const slots = char._fullChar?.worn || {};
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
};

window.unequipFromDetail = function() {
  if (!detailItemKey || !selectedChar) return;
  const char = selectedChar;
  const tmpl = definitions.item_templates?.[detailItemKey] || {};
  const slot = tmpl.slot || '?';
  if (char._fullChar?.worn?.[slot] !== detailItemKey) return;
  patchChar(char, { worn: { [slot]: null } })
    .then(() => {
      buildOutfitMeshes(char);
      closeItemDetail();
      renderOutfitTab();
    })
    .catch(e => addLog('system', char.id, 'unequip error: ' + e.message));
};

function equipItem(itemKey) {
  if (!selectedChar) return;
  const char = selectedChar;
  const tmpl = definitions.item_templates?.[itemKey] || {};
  const slot = tmpl.slot || '?';
  patchChar(char, { worn: { [slot]: itemKey } })
    .then(() => {
      buildOutfitMeshes(char);
      renderOutfitTab();
      addLog('system', char.id, char.serverChar.name + ' equipped: ' + (tmpl.name||itemKey) + ' [' + slot + ']');
    })
    .catch(e => addLog('system', char.id, 'equip error: ' + e.message));
}

// =====================================================================
// OUTFIT TAB RENDER
// =====================================================================
async function renderOutfitTab() {
  if (!selectedChar) return;
  const char = selectedChar;
  if (!char._fullChar) {
    document.getElementById('outfitSlots').innerHTML = '<span style="color:#3a4050;font-size:12px">Loading…</span>';
    document.getElementById('clothingList').innerHTML = '';
    await fetchFullChar(char);
    if (selectedChar !== char) return; // selection changed while awaiting
  }
  const slots = char._fullChar?.worn || {};

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

// Mirrors backend/brain/emotion.py::EMOTION_TEMP's key list -- the
// canonical set of c["emotion"] labels. Small acceptable duplication for
// a debug tool rather than adding a fetch just for this.
const EMOTION_TEMP = {
  ecstatic:95, euphoric:88, excited:78, cheerful:65, content:50, calm:35,
  neutral:20, bored:25, melancholy:40, anxious:55, annoyed:60, sad:45,
  angry:72, furious:88, fearful:70, smug:55, suspicious:50, awkward:45,
  curious:35, warm:28,
};

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

function showSpeechBubble(char, text, isThought=false) {
  if (!char || !char.mesh) return;
  if (char.mesh.userData.speechSprite) {
    char.mesh.remove(char.mesh.userData.speechSprite);
    char.mesh.userData.speechSprite = null;
  }
  clearTimeout(char.mesh.userData.speechTimer);
  const sprite = makeSpeechSprite(text, isThought);
  char.mesh.add(sprite);
  char.mesh.userData.speechSprite = sprite;
  char.mesh.userData.speechTimer = setTimeout(() => {
    if (char.mesh.userData.speechSprite === sprite) {
      char.mesh.remove(sprite);
      char.mesh.userData.speechSprite = null;
    }
  }, 6000);
}

function makeSpeechSprite(text, isThought) {
  const canvas = document.createElement('canvas');
  canvas.width = 512; canvas.height = 128;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = isThought ? 'rgba(30,20,50,0.85)' : 'rgba(10,20,35,0.9)';
  ctx.roundRect(4,4,504,120,16);
  ctx.fill();
  ctx.strokeStyle = isThought ? '#7986cb' : '#4caf80';
  ctx.lineWidth = 2;
  ctx.roundRect(4,4,504,120,16);
  ctx.stroke();
  ctx.fillStyle = '#eef';
  ctx.font = '22px Arial';
  ctx.textAlign = 'center';
  _wrapCanvasText(ctx, text, 256, 40, 470, 28);
  const tex = new THREE.CanvasTexture(canvas);
  const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(1.8, 0.45, 1);
  sprite.position.set(0, 2.55, 0);
  return sprite;
}

function _wrapCanvasText(ctx, text, x, y, maxWidth, lineHeight) {
  const words = String(text).split(' ');
  let line = '';
  let lines = [];
  for (const w of words) {
    const test = line ? line + ' ' + w : w;
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line);
      line = w;
    } else {
      line = test;
    }
  }
  if (line) lines.push(line);
  lines = lines.slice(0, 3);
  const startY = y - (lines.length - 1) * lineHeight / 2;
  lines.forEach((l, i) => ctx.fillText(l, x, startY + i * lineHeight));
}

// =====================================================================
// TEMPLATE PICKER
// =====================================================================
function buildSpawnerUI() {
  const sel = document.getElementById('spTemplate');
  sel.innerHTML = '';
  const templates = definitions.character_templates || {};
  const ids = Object.keys(templates);
  if (!ids.length) {
    const o = document.createElement('option');
    o.textContent = '(no character_templates found)';
    sel.appendChild(o);
    return;
  }
  for (const id of ids) {
    const tmpl = templates[id];
    const o = document.createElement('option');
    o.value = id;
    o.textContent = (tmpl.name || id) + ` (${id})`;
    sel.appendChild(o);
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
// STAGE CHARACTER (real backend call -- POST /debug/sandbox/stage)
// =====================================================================
// Each call stages ONE additional character. If a sandbox already exists
// (currentSandboxId set), the new character is staged into a FRESH
// sandbox alongside every character already in sandboxChars, re-using
// each one's own template id + position -- /stage has no "add to existing
// sandbox" endpoint (by design, see the Round 1 plan), so growing the
// scene means restaging everyone together every time.
window.stageSelectedTemplate = async function() {
  const sel = document.getElementById('spTemplate');
  const templateId = sel.value;
  const statusEl = document.getElementById('stageStatus');
  if (!templateId) { statusEl.textContent = 'No template selected'; return; }

  statusEl.textContent = 'Staging…';

  const angle = Math.random() * Math.PI * 2;
  const r     = sandboxChars.length === 0 ? 0 : 1.5 + sandboxChars.length * 0.4;
  const newSpec = {
    template_id: templateId,
    x: Math.cos(angle) * r,
    y: Math.sin(angle) * r,
  };

  // Re-stage every existing character (by their own template + position)
  // plus the new one, in one combined /stage call.
  const specs = sandboxChars.map(c => ({
    template_id: c.serverChar.template,
    x: c.serverChar.x, y: c.serverChar.y,
  }));
  specs.push(newSpec);

  const absent = pendingAbsent.map(a => ({
    name: a.name, relationship_to_index: a.charIndex, relation_label: a.relation_label,
  }));

  try {
    const res = await fetch('/debug/sandbox/stage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sim_id: 'default', characters: specs, absent }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);

    // Rebuild sandboxChars from scratch against the new sandbox_id --
    // old meshes are removed and re-added so ids stay in sync with the
    // freshly-staged world (staging always mints new sandbox character
    // ids, even for characters that were already present).
    for (const old of sandboxChars) sbScene.remove(old.mesh);
    sandboxChars = [];
    currentSandboxId = data.sandbox_id;

    for (const serverChar of data.characters) {
      const color = moodColor(serverChar.emotion);
      const mesh = makeCapsule(color);
      const sprite = makeNameSprite(serverChar.name, color);
      mesh.add(sprite);
      mesh.userData = { charId: serverChar.id };
      mesh.position.set(serverChar.x || 0, 0, serverChar.y || 0);
      sbScene.add(mesh);

      sandboxChars.push({
        id: serverChar.id, sandboxId: currentSandboxId,
        serverChar, mesh, color, _fullChar: null,
      });
    }

    updateCharCount();
    populateTurnCharSelect();
    addLog('system', null, `Staged ${data.characters.length} character(s) -- sandbox ${currentSandboxId}`);
    statusEl.textContent = `${data.characters.length} staged`;
    selectChar(sandboxChars[sandboxChars.length - 1].id);

    if (sandboxChars.length >= 2) {
      document.getElementById('btnStart').disabled = false;
      document.getElementById('scenarioStatus').textContent = sandboxChars.length + ' characters ready';
    }
  } catch (e) {
    statusEl.textContent = 'Error: ' + e.message;
    console.error('[stage]', e);
  }
};

function updateCharCount() {
  document.getElementById('charCountBadge').textContent = sandboxChars.length + ' character' + (sandboxChars.length!==1?'s':'');
}

// Whose turn is next -- the turn engine defaults to whatever's selected
// here, but a completed turn that touched a conversation snaps the select
// forward to the real turn_owner (see takeNextTurn()).
function populateTurnCharSelect() {
  const sel = document.getElementById('turnCharSelect');
  const prev = sel.value;
  sel.innerHTML = '';
  for (const c of sandboxChars) {
    const o = document.createElement('option');
    o.value = c.id;
    o.textContent = c.serverChar.name;
    sel.appendChild(o);
  }
  if (sandboxChars.some(c => c.id === prev)) sel.value = prev;
  populateAbsentRelToSelect();
}

// =====================================================================
// ABSENT RELATIONSHIPS (mocked people not physically staged) --
// replayed into every /stage call's "absent" list, see stageSelectedTemplate().
// =====================================================================
function populateAbsentRelToSelect() {
  const sel = document.getElementById('absentRelTo');
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = '';
  sandboxChars.forEach((c, i) => {
    const o = document.createElement('option');
    o.value = String(i);
    o.textContent = c.serverChar.name;
    sel.appendChild(o);
  });
  if (prev && +prev < sandboxChars.length) sel.value = prev;
}

window.addAbsentRelationship = function() {
  const relSel  = document.getElementById('absentRelTo');
  const nameInp = document.getElementById('absentName');
  const lblInp  = document.getElementById('absentLabel');
  if (!sandboxChars.length) { addLog('system', null, 'Stage a character first.'); return; }
  const name = nameInp.value.trim();
  if (!name) { addLog('system', null, 'Absent relationship needs a name.'); return; }

  pendingAbsent.push({
    name,
    charIndex: +relSel.value || 0,
    relation_label: lblInp.value.trim(),
  });
  nameInp.value = '';
  lblInp.value = '';
  renderAbsentList();
};

window.removeAbsentRelationship = function(idx) {
  pendingAbsent.splice(idx, 1);
  renderAbsentList();
};

function renderAbsentList() {
  const el = document.getElementById('absentList');
  if (!el) return;
  if (!pendingAbsent.length) {
    el.innerHTML = '<span style="color:#3a4050;font-size:11px">None</span>';
    return;
  }
  el.innerHTML = pendingAbsent.map((a, i) => {
    const relTo = sandboxChars[a.charIndex]?.serverChar.name || '?';
    return '<span class="traitBadge" style="background:#241a1a;border-color:#7a4d2e;color:#f8c8ad">' +
      escHtml(a.name) + (a.relation_label ? ' (' + escHtml(a.relation_label) + ')' : '') +
      ' → ' + escHtml(relTo) +
      ' <a onclick="removeAbsentRelationship(' + i + ')" style="cursor:pointer;color:#f66;margin-left:4px">✕</a></span>';
  }).join(' ');
}

// =====================================================================
// FULL CHARACTER FETCH (real backend schema -- trimmed serverChar doesn't
// carry everything the Runtime/Template/Outfit tabs need, e.g. "worn")
// =====================================================================
async function fetchFullChar(char) {
  if (!char.sandboxId) return null;
  try {
    const res = await fetch(`/debug/sandbox/${char.sandboxId}/characters/${char.id}`);
    if (!res.ok) throw new Error(res.statusText);
    char._fullChar = await res.json();
  } catch (e) {
    console.error('[fetchFullChar]', e);
    char._fullChar = null;
  }
  return char._fullChar;
}

// =====================================================================
// SELECTION
// =====================================================================
async function selectChar(id) {
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
    const char = selectedChar;
    document.getElementById('charHeaderName').textContent = char.serverChar.name;
    document.getElementById('charHeaderName').style.color = '#' + char.color.toString(16).padStart(6,'0');
    document.getElementById('noCharMsg').style.display = 'none';
    document.getElementById('btnEscalate').disabled = false;
    await fetchFullChar(char);
    if (selectedChar !== char) return; // selection changed while awaiting
    buildPreviewChar(char);
    refreshAllTabs();
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
  if (tab==='runtime')    renderRuntimeTab();
  if (tab==='template')   renderTemplateTab();
  if (tab==='log')        renderLogTab();
  if (tab==='prompts')    renderPromptsTab();
  if (tab==='family')     window._refreshFamilyTab && window._refreshFamilyTab();
}

async function renderRuntimeTab() {
  const char = selectedChar;
  const el = document.getElementById('runtimeJson');
  el.textContent = 'Loading…';
  const full = await fetchFullChar(char);
  if (char !== selectedChar) return; // selection changed while awaiting
  el.textContent = full ? JSON.stringify(full, null, 2) : 'Error loading character';
}

function renderTemplateTab() {
  const el = document.getElementById('templateJson');
  const templateId = selectedChar.serverChar.template;
  const tmpl = (definitions.character_templates || {})[templateId];
  el.textContent = tmpl ? JSON.stringify(tmpl, null, 2) : `(template '${templateId}' not found)`;
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

// =====================================================================
// OFFGRID TAB
// =====================================================================
window.sendOffgrid = async function() {
  if (!selectedChar) return;
  const catSel   = document.getElementById('offgridCategory');
  const category = catSel.value === 'event'
    ? 'event:' + (document.getElementById('offgridEventId').value.trim() || 'evt_unknown')
    : catSel.value;
  const duration = +document.getElementById('offgridDuration').value || 20;
  const statusEl = document.getElementById('offgridStatus');
  const narrEl   = document.getElementById('offgridNarration');
  const jsonEl   = document.getElementById('offgridCharJson');
  const charId   = selectedChar.id;

  statusEl.textContent = 'Sending off-grid…';
  try {
    const res = await fetch(`/debug/sandbox/${currentSandboxId}/offgrid`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ char_id: charId, category, duration }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);

    if (!data.ok) {
      statusEl.textContent = 'Not sent: ' + data.reason;
      return;
    }

    statusEl.textContent = 'Returned';
    narrEl.textContent = data.narration;
    jsonEl.textContent = JSON.stringify(data.character, null, 2);
    addLog('event', charId, data.narration);

    const char = sandboxChars.find(c => c.id === charId);
    if (char) {
      Object.assign(char.serverChar, data.character);
      char._fullChar = null;
      if (selectedChar.id === charId) refreshAllTabs();
    }
  } catch (e) {
    statusEl.textContent = 'Error: ' + e.message;
    console.error('[offgrid]', e);
  }
};

// =====================================================================
// PATCH -- generic setter, all State/Appearance edits collapse into this.
// PATCH /debug/sandbox/{sandboxId}/characters/{id} does a shallow +
// one-level-nested merge server-side and returns the full updated
// character, which we use to refresh both the trimmed serverChar (so
// Log/Runtime/etc. stay in sync) and the mesh color (mirrors the old
// setInstField's mood-recolor behavior, now against a real field).
// =====================================================================
async function patchChar(char, patch) {
  const res = await fetch(`/debug/sandbox/${char.sandboxId}/characters/${char.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || res.statusText);

  char._fullChar = data;
  char.serverChar.name = data.name;
  char.serverChar.sex = data.sex;
  char.serverChar.age = data.age;
  char.serverChar.health = data.health;
  char.serverChar.emotion = data.emotion;
  char.serverChar.mood = data.mood;

  const newColor = moodColor(data.emotion);
  char.color = newColor;
  char.mesh.traverse(o => { if (o.isMesh) o.material.color.set(newColor); });
  if (char === selectedChar) {
    document.getElementById('charHeaderName').textContent = data.name;
    document.getElementById('charHeaderName').style.color = '#' + newColor.toString(16).padStart(6,'0');
  }
  populateTurnCharSelect();
  return data;
}

async function patchSelectedChar(patch, refreshTabName) {
  if (!selectedChar) return;
  try {
    await patchChar(selectedChar, patch);
    if (refreshTabName) refreshTab(refreshTabName);
  } catch (e) {
    addLog('system', selectedChar.id, 'patch error: ' + e.message);
  }
}

window.setNameField  = v => patchSelectedChar({ name: v }, 'appearance');
window.setSexField   = v => patchSelectedChar({ sex: v }, 'appearance');
window.setAgeField   = v => patchSelectedChar({ age: v }, 'appearance');
window.setEmotionField = v => patchSelectedChar({ emotion: v }, 'state');
window.setEmotionalTemp = v => patchSelectedChar({ emotional_temperature: v });
window.setHealthField = (k, v) => patchSelectedChar({ health: { [k]: v } }, 'state');

// ── Appearance tab ──
async function renderAppearanceTab() {
  const char = selectedChar;
  if (!char._fullChar) await fetchFullChar(char);
  if (selectedChar !== char) return; // selection changed while awaiting

  const c = char.serverChar;
  const full = char._fullChar;
  const traits = (c.traits||[]).map(t=>{
    const tmpl = definitions.trait_templates?.[t] || {};
    const cls  = tmpl.polarity==='negative' ? 'traitBadge neg' : 'traitBadge';
    return '<span class="' + cls + '">' + (tmpl.name||t) + '</span>';
  }).join('');
  const hobbies = (c.hobbies||[]).map(h=>'<span class="traitBadge" style="background:#1a2040;border-color:#2e4da4;color:#adf">' + h.replace(/_/g,' ') + '</span>').join('');
  const physTraits = (full?.physical_traits||[]).map(t=>{
    const tmpl = definitions.physical_trait_templates?.[t] || {};
    return '<span class="traitBadge" style="background:#20261a;border-color:#4d7a2e;color:#adf8ad">' + (tmpl.name||t) + '</span>';
  }).join('');
  const appearance = full?.appearance || {};
  const appearanceBits = ['height','build','hair_color','hair_style','eye_color','clothing_style']
    .filter(k => appearance[k]).map(k => k.replace(/_/g,' ') + ': ' + appearance[k]).join(', ');

  document.getElementById('tab-appearance').innerHTML = '<div class="fieldGrid">' +
    '<label>Name</label><input value="' + escHtml(c.name||'') + '" onchange="setNameField(this.value)">' +
    '<label>Sex</label><select onchange="setSexField(this.value)">' +
    ['male','female','other'].map(s=>'<option'+(c.sex===s?' selected':'')+'>'+s+'</option>').join('') + '</select>' +
    '<label>Age</label><input type="number" value="' + (c.age ?? '') + '" style="width:70px" onchange="setAgeField(+this.value)">' +
    '</div>' +
    '<div class="sectionHead">Traits</div><div>' + (traits||'<span style="color:#445">None selected</span>') + '</div>' +
    '<div class="sectionHead">Physical Traits</div><div>' + (physTraits||'<span style="color:#445">None</span>') + '</div>' +
    '<div class="sectionHead">Hobbies</div><div>' + (hobbies||'<span style="color:#445">None selected</span>') + '</div>' +
    '<div class="sectionHead">Physical Appearance</div><div style="color:#778;font-size:12px">' +
    (appearanceBits || '<span style="color:#445">Not generated — these fields are unpopulated by character_gen.py today</span>') + '</div>';
}

// ── State tab ──
const HEALTH_FIELDS = ['hunger','energy','hydration','hygiene','bladder','fatigue','stress','pain'];

async function renderStateTab() {
  const char = selectedChar;
  if (!char._fullChar) await fetchFullChar(char);
  if (selectedChar !== char) return; // selection changed while awaiting

  const c = char.serverChar;
  const health = c.health || {};
  const mood = c.mood;
  const temp = c.emotional_temperature ?? char._fullChar?.emotional_temperature ?? 20;

  let html = '<div class="sectionHead">Emotion</div>';
  html += '<select onchange="setEmotionField(this.value)" style="background:#1a1e24;border:1px solid #3a3f48;color:#ccc;padding:4px 8px;border-radius:4px;font-size:12px">';
  for (const label of Object.keys(EMOTION_TEMP)) {
    html += '<option' + (c.emotion===label?' selected':'') + '>' + label + '</option>';
  }
  html += '</select>';

  html += '<div class="sectionHead">Emotional Temperature</div>';
  html += '<div style="display:flex;align-items:center;gap:8px">' +
    '<input type="range" min="0" max="100" value="' + temp + '" style="flex:1" ' +
    'oninput="document.getElementById(\'etVal\').textContent=this.value" onchange="setEmotionalTemp(+this.value)">' +
    '<span id="etVal" style="color:#ccd;width:28px">' + temp + '</span></div>';

  html += '<div class="sectionHead">Mood</div>' +
    '<div style="padding:4px 0 12px;color:#ccd">' +
    (mood ? escHtml(mood.name || mood.id) + ' <span style="color:#556;font-size:11px">(data-driven, read-only)</span>' : '<span style="color:#445">none</span>') + '</div>';

  html += '<div class="sectionHead">Health</div>';
  for (const k of HEALTH_FIELDS) {
    if (!(k in health)) continue;
    const v = health[k];
    html += '<div class="meterRow"><span class="meterLabel">' + k + '</span>' +
      '<input class="editableVal" type="number" step="0.05" value="' + (typeof v==='number'?v.toFixed(2):v) + '" onchange="setHealthField(\'' + k + '\',+this.value)"></div>';
  }
  if ('sick' in health) {
    html += '<div class="meterRow"><span class="meterLabel">sick</span>' +
      '<input type="checkbox" ' + (health.sick?'checked':'') + ' onchange="setHealthField(\'sick\',this.checked)"></div>';
  }
  if (health.conditions?.length) {
    html += '<div style="color:#f44336;padding:6px 0">Conditions: ' + escHtml(JSON.stringify(health.conditions)) + '</div>';
  }

  document.getElementById('tab-state').innerHTML = html;
}

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
    const charName = sandboxChars.find(c=>c.id===e.charId)?.serverChar.name || '';
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
// TURN ENGINE -- click-driven by default; "Auto" is an off-by-default
// interval loop (never overlaps calls, guarded by turnInFlight) rather
// than a blind setTimeout loop, since each turn is a real Ollama
// round-trip that can take tens of seconds.
// =====================================================================

window.startScenario = function() {
  takeNextTurn();
};

window.pauseScenario = function() {
  autoAdvanceOn = !autoAdvanceOn;
  const btn = document.getElementById('btnPause');
  const stopBtn = document.getElementById('btnStop');
  if (autoAdvanceOn) {
    btn.textContent = '🔁 Auto: On';
    stopBtn.disabled = false;
    document.getElementById('scenarioStatus').textContent = 'Auto-advancing every ' + window.speechInterval + 's';
    scheduleAutoAdvance();
  } else {
    btn.textContent = '🔁 Auto: Off';
    stopBtn.disabled = true;
    clearTimeout(autoAdvanceTimer);
    document.getElementById('scenarioStatus').textContent = 'Auto-advance stopped';
  }
};

window.stopScenario = function() {
  autoAdvanceOn = false;
  clearTimeout(autoAdvanceTimer);
  document.getElementById('btnPause').textContent = '🔁 Auto: Off';
  document.getElementById('btnStop').disabled = true;
  document.getElementById('scenarioStatus').textContent = 'Auto-advance stopped';
};

function scheduleAutoAdvance() {
  if (!autoAdvanceOn) return;
  autoAdvanceTimer = setTimeout(async () => {
    if (!turnInFlight) await takeNextTurn();
    scheduleAutoAdvance();
  }, window.speechInterval * 1000);
}

async function takeNextTurn() {
  if (turnInFlight) return;
  const sel = document.getElementById('turnCharSelect');
  const charId = sel.value;
  const statusEl = document.getElementById('scenarioStatus');
  if (!currentSandboxId || !charId) {
    statusEl.textContent = 'Stage at least 2 characters first';
    return;
  }

  turnInFlight = true;
  document.getElementById('btnStart').disabled = true;
  statusEl.textContent = 'Thinking…';

  try {
    const res = await fetch(`/debug/sandbox/${currentSandboxId}/turn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ char_id: charId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);

    const char = sandboxChars.find(c => c.id === charId);
    if (char) {
      Object.assign(char.serverChar, data.character);
      char._fullChar = null; // health/emotion may have changed -- refetch on next tab view
    }

    const thought = data.decision?.thought;
    if (thought) {
      addLog('thought', charId, thought);
      if (showThoughts) showSpeechBubble(char, '💭 ' + thought, true);
    }
    const speech = data.character?.current_speech;
    if (speech?.utterance) {
      addLog('speech', charId, speech.utterance);
      showSpeechBubble(char, speech.utterance, false);
    } else if (!thought) {
      addLog('system', charId, `did: ${data.decision?.action?.type || 'nothing'}`);
    }
    if (data.action_error) {
      addLog('system', charId, 'action error: ' + data.action_error);
    }

    if (data.conversation) {
      populateTurnCharSelect();
      sel.value = data.conversation.turn_owner;
      const nextName = sandboxChars.find(c => c.id === data.conversation.turn_owner)?.serverChar.name
        || data.conversation.turn_owner;
      statusEl.textContent = `Conversation ongoing — next: ${nextName}`;
    } else {
      statusEl.textContent = 'Turn complete';
    }

    if (selectedChar && selectedChar.id === charId) {
      refreshAllTabs();
    }
  } catch (e) {
    statusEl.textContent = 'Error: ' + e.message;
    console.error('[turn]', e);
  } finally {
    turnInFlight = false;
    document.getElementById('btnStart').disabled = false;
  }
}

window.triggerEscalation = async function() {
  if (!selectedChar) return;
  const char = selectedChar;
  try {
    await patchChar(char, { emotion: 'furious', emotional_temperature: 90 });
    addLog('event', char.id, char.serverChar.name + ' mood escalated to FURIOUS');
    if (selectedChar === char) refreshTab('state');
  } catch (e) {
    addLog('system', char.id, 'escalate error: ' + e.message);
  }
};

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

window.generateFamilyTree = async function() {
  if (!selectedChar) { alert('Select a character first.'); return; }
  const char    = selectedChar;
  const charId  = char.id;
  const depth   = document.getElementById('familyDepth2')?.checked ? 2 : 1;
  const statusEl = document.getElementById('familyStatus');
  const treeEl   = document.getElementById('familyTree');

  statusEl.textContent = 'Generating…';
  treeEl.innerHTML = '';

  try {
    const res = await fetch(`/debug/sandbox/${char.sandboxId}/characters/${charId}/generate_family?depth=${depth}`, {
      method: 'POST',
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);

    const fam = data.family;
    statusEl.textContent = data.already_existed
      ? `Existing family loaded — ${fam.size} members`
      : `Generated — ${fam.size} members (depth ${depth})`;

    // Render the tree
    treeEl.innerHTML = _renderFamilyHTML(fam, charId);

    char._fullChar = null; // family_id changed on the character -- refetch on next full-char need

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

window._refreshFamilyTab = async function() {
  if (!selectedChar) return;
  const char = selectedChar;
  if (!char._fullChar) await fetchFullChar(char);
  if (selectedChar !== char) return; // selection changed while awaiting

  const statusEl = document.getElementById('familyStatus');
  const treeEl   = document.getElementById('familyTree');
  if (!char._fullChar?.family_id) {
    if (statusEl) statusEl.textContent = 'No family tree yet — click Generate.';
    if (treeEl)   treeEl.innerHTML = '';
  }
  // If a family_id exists, leave whatever generateFamilyTree() last wrote
  // to #familyTree in place -- there's no GET-family-by-id endpoint to
  // re-render from on a tab switch alone.
};
