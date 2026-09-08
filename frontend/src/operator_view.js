// src/operator_view.js
//
// Wires the Director Panel (operator_view.html) to systems/director_mode.py's
// four REST primitives (api/director.py) -- the desktop-testable half of VR
// director-mode. main.js (loaded before this file, same page) owns the
// entire viewer/selection/Inspector/outliner setup unchanged; this module
// only reads its selection via the window.getSelectedCharacterId()/
// getSelectedCharacterName() hooks it exposes and adds the new panel's
// behavior on top -- it never touches main.js's own state directly.
//
// Backend calls use an absolute URL (matching main.js's own WebSocket
// connection, `ws://${location.hostname}:8000/ws`) rather than a relative
// path through nginx's /director proxy -- works identically whether this
// page is served by the built nginx container or a local `npm run dev`.

const DIRECTOR_BASE = `http://${location.hostname}:8000/director`;

const targetEl          = document.getElementById("directorTarget");
const interruptBtn      = document.getElementById("directorInterruptBtn");
const lineInput         = document.getElementById("directorLineInput");
const injectBtn         = document.getElementById("directorInjectBtn");
const fieldInput        = document.getElementById("directorFieldInput");
const valueInput        = document.getElementById("directorValueInput");
const stageBtn          = document.getElementById("directorStageBtn");
const pendingChangesEl  = document.getElementById("directorPendingChanges");
const endBtn            = document.getElementById("directorEndBtn");
const statusLineEl      = document.getElementById("directorStatusLine");

const CONTROLS = [interruptBtn, lineInput, injectBtn, fieldInput, valueInput, stageBtn, endBtn];

let _lastSelectedId = null;

function _setStatus(text, isError = false) {
  statusLineEl.textContent = text || "";
  statusLineEl.classList.toggle("directorError", !!isError);
}

async function _post(path, body) {
  const res = await fetch(`${DIRECTOR_BASE}${path}?sim_id=default`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

function _renderPendingChanges(pending) {
  const entries = Object.entries(pending || {});
  if (!entries.length) {
    pendingChangesEl.textContent = "";
    return;
  }
  pendingChangesEl.innerHTML =
    "Pending: " + entries.map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join(", ");
}

function _syncTargetDisplay() {
  const id = window.getSelectedCharacterId?.();
  const changed = id !== _lastSelectedId;
  _lastSelectedId = id;

  const enabled = !!id;
  CONTROLS.forEach(el => { el.disabled = !enabled; });

  if (!enabled) {
    targetEl.textContent = "No character selected";
    if (changed) {
      _renderPendingChanges(null);
      _setStatus("");
    }
    return;
  }

  const name = window.getSelectedCharacterName?.() || id;
  targetEl.textContent = `Directing: ${name}`;
  if (changed) {
    _renderPendingChanges(null);
    _setStatus("");
  }
}

// Polls rather than hooking main.js's click handler directly -- main.js
// exposes no selection-changed event, only a plain getter, and polling a
// cheap getter a couple times a second is simpler than patching a second
// file's click-handling code to fire one.
setInterval(_syncTargetDisplay, 400);
_syncTargetDisplay();

interruptBtn.addEventListener("click", async () => {
  const id = window.getSelectedCharacterId?.();
  if (!id) return;
  try {
    await _post("/interrupt_attention", { char_id: id });
    _setStatus("Interrupted -- they'll notice you on their next thought.");
  } catch (err) {
    _setStatus(err.message, true);
  }
});

injectBtn.addEventListener("click", async () => {
  const id = window.getSelectedCharacterId?.();
  const text = lineInput.value.trim();
  if (!id || !text) return;
  try {
    await _post("/inject_line", { char_id: id, text });
    _setStatus("Line delivered.");
    lineInput.value = "";
  } catch (err) {
    _setStatus(err.message, true);
  }
});

stageBtn.addEventListener("click", async () => {
  const id = window.getSelectedCharacterId?.();
  const field = fieldInput.value.trim();
  const raw = valueInput.value.trim();
  if (!id || !field || !raw) return;

  // Values are entered as JSON so numbers/strings/bools/lists all round-trip
  // correctly through the backend's type check (director_mode.py's
  // _STAGEABLE_VALUE_TYPES) -- a bare unquoted word is treated as a plain
  // string for convenience, matching how someone would naturally type e.g.
  // a trait name without quotes.
  let value;
  try {
    value = JSON.parse(raw);
  } catch {
    value = raw;
  }

  try {
    const data = await _post("/set_preference", { char_id: id, field, value });
    _renderPendingChanges(data.pending_changes);
    _setStatus(`Staged ${field} (takes effect when you end the session).`);
    fieldInput.value = "";
    valueInput.value = "";
  } catch (err) {
    _setStatus(err.message, true);
  }
});

endBtn.addEventListener("click", async () => {
  const id = window.getSelectedCharacterId?.();
  if (!id) return;
  try {
    const data = await _post("/end_session", { char_id: id });
    const fields = Object.keys(data.changed_fields || {});
    _renderPendingChanges(null);
    _setStatus(fields.length
      ? `Session ended -- committed: ${fields.join(", ")}.`
      : "Session ended -- nothing was staged.");
  } catch (err) {
    _setStatus(err.message, true);
  }
});

// =========================================================
// VR CONTROLLER INPUT (Phase 2)
// =========================================================
// main.js owns the actual WebXR session/render/locomotion/raycasting
// plumbing (see window.getXRContext()) -- this is just the director-mode-
// specific reaction to controller button events, kept separate the same
// way the desktop Director Panel above is kept separate from main.js's
// viewer code.
//
// Matches the original ask's gesture shape: hold a controller button to
// ENTER director mode (calls every nearby character to attention); while
// active, trigger-tap selects+interrupts whoever you're pointing at, and
// holding the trigger on a selected character captures speech (Web Speech
// API) and injects it as their line -- "instruct the AI via free-text
// conversation," via real speech-to-text rather than an in-VR keyboard;
// holding the SAME button again EXITS director mode and commits
// (end_session) every character touched during the session, matching
// "save the changes you made" on release.
//
// Known gap this round: there's still no in-VR HUD/menu -- _setStatus()'s
// text only shows on the flat desktop mirror, not inside the headset.
// In-headset feedback is the laser ray's color (yellow idle, orange/red
// while director mode is active, green while hovering a character -- see
// main.js's updateXRFrame/window.setDirectorModeActive) plus the real,
// observable effect on the sim. A proper in-scene panel is future work.

const CALL_ATTENTION_RADIUS = 8;        // tiles
const MODE_TOGGLE_HOLD_MS   = 1200;     // squeeze-hold to enter/exit director mode
const SPEECH_CAPTURE_HOLD_MS = 350;     // trigger-hold longer than this starts speech capture

const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;

let directorModeActive = false;
const touchedCharacterIds = new Set();

function setupXRControllerInput() {
  const ctx = window.getXRContext?.();
  if (!ctx) return;   // main.js hasn't loaded (shouldn't happen on this page) -- retry below

  ctx.controllers.forEach((controller, i) => {
    let modeHoldTimer = null;
    let speechHoldTimer = null;
    let recognizer = null;
    let capturingSpeech = false;

    // ---- Squeeze: hold to toggle director mode on/off ----
    controller.addEventListener("squeezestart", () => {
      clearTimeout(modeHoldTimer);
      modeHoldTimer = setTimeout(() => _toggleDirectorMode(ctx), MODE_TOGGLE_HOLD_MS);
    });
    controller.addEventListener("squeezeend", () => {
      clearTimeout(modeHoldTimer);
      modeHoldTimer = null;
    });

    // ---- Trigger: tap to select+interrupt, hold to speak a line ----
    controller.addEventListener("selectstart", () => {
      if (!directorModeActive) return;
      capturingSpeech = false;
      clearTimeout(speechHoldTimer);
      speechHoldTimer = setTimeout(() => {
        const id = ctx.hover[i] || window.getSelectedCharacterId?.();
        if (!id || !SpeechRecognitionCtor) return;
        capturingSpeech = true;
        recognizer = _startSpeechCapture((text) => {
          if (text) _post("/inject_line", { char_id: id, text }).catch(() => {});
        });
      }, SPEECH_CAPTURE_HOLD_MS);
    });

    controller.addEventListener("selectend", async () => {
      clearTimeout(speechHoldTimer);
      if (capturingSpeech) {
        recognizer?.stop();
        capturingSpeech = false;
        recognizer = null;
        return;
      }
      if (!directorModeActive) return;
      const id = ctx.hover[i];
      if (!id) return;
      window.setSelectedCharacterId?.(id);
      touchedCharacterIds.add(id);
      try {
        await _post("/interrupt_attention", { char_id: id });
      } catch { /* best-effort in VR -- no HUD to report failure to yet */ }
    });
  });
}

function _startSpeechCapture(onResult) {
  const recognizer = new SpeechRecognitionCtor();
  recognizer.continuous = false;
  recognizer.interimResults = false;
  recognizer.lang = "en-US";
  let finalTranscript = "";
  recognizer.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) finalTranscript += event.results[i][0].transcript;
    }
  };
  recognizer.onend = () => onResult(finalTranscript.trim());
  recognizer.onerror = () => onResult("");
  recognizer.start();
  return recognizer;
}

async function _toggleDirectorMode(ctx) {
  directorModeActive = !directorModeActive;
  window.setDirectorModeActive?.(directorModeActive);

  if (directorModeActive) {
    await _triggerCallAttention(ctx);
    _setStatus("Director mode ON.");
    return;
  }

  // Exiting -- commit (end_session) every character touched this session,
  // matching "save the changes you made" on release.
  const ids = [...touchedCharacterIds];
  touchedCharacterIds.clear();
  await Promise.all(ids.map(id => _post("/end_session", { char_id: id }).catch(() => {})));
  _setStatus(`Director mode OFF -- ${ids.length} character(s) committed.`);
}

async function _triggerCallAttention(ctx) {
  const pos = ctx.dolly.position;
  try {
    const data = await _post("/call_attention_radius", {
      x: pos.x + 10, y: pos.z + 7, radius: CALL_ATTENTION_RADIUS,
    });
    // Visual "turn to face the director" -- a courtesy render effect only
    // (see systems/director_mode.py::call_attention_radius's own docstring
    // on why this isn't backend state: character facing is a derived-from-
    // recent-movement render detail in main.js, nothing persists it).
    const sims = window.getXRContext?.().sims || {};
    for (const id of data.affected || []) {
      touchedCharacterIds.add(id);
      const model = sims[id];
      if (!model) continue;
      const dx = model.position.x - pos.x;
      const dz = model.position.z - pos.z;
      model.rotation.y = Math.atan2(-dx, -dz);
    }
    _setStatus(`Called ${(data.affected || []).length} nearby character(s) to attention.`);
  } catch (err) {
    _setStatus(err.message, true);
  }
}

// window.getXRContext only exists once main.js's module body has fully
// run (it's defined near the renderer setup, evaluated top-to-bottom at
// import time) -- both scripts load as type="module" in the same
// <head>/<body> order operator_view.html declares, so by the time this
// file's own top-level code runs, main.js is already done. Retry briefly
// regardless, in case that ordering assumption ever changes.
(function waitForXRContext(attempts = 20) {
  if (window.getXRContext) {
    setupXRControllerInput();
    return;
  }
  if (attempts <= 0) return;
  setTimeout(() => waitForXRContext(attempts - 1), 100);
})();
