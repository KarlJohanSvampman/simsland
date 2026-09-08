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
