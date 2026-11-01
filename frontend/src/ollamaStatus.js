// =========================================================
// OLLAMA STATUS LIGHT (top-right corner of the view page)
//
// Polls GET /debug/ollama_status (backend/api/debug.py), which asks the
// Ollama server the simulation decides with whether it is up and has the
// configured model installed. Green = up, amber = answering but the model
// is missing, red = not answering (or the simulation core itself did not
// answer), grey pulsing = first check still in flight.
// Hover for details; click to check again right away.
// =========================================================

const POLL_MS = 10000;
const REQUEST_TIMEOUT_MS = 8000;

const el = document.getElementById("ollamaStatus");

let timer = null;
let inFlight = false;

function render(state, title) {
  el.classList.remove("checking", "up", "degraded", "down");
  el.classList.add(state);
  el.title = title;
}

function describe(s) {
  const lines = [`Ollama: ${s.state}`, s.base_url, `model: ${s.model}`];
  if (s.latency_ms != null) lines.push(`answered in ${s.latency_ms} ms`);
  if (Array.isArray(s.loaded)) lines.push(s.loaded.length ? `in memory: ${s.loaded.join(", ")}` : "no model in memory yet");
  if (s.error) lines.push(s.error);
  lines.push("click to check now");
  return lines.join("\n");
}

async function check() {
  if (inFlight) return;
  inFlight = true;
  const ctrl = new AbortController();
  const abort = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
  try {
    const r = await fetch("/debug/ollama_status", { signal: ctrl.signal, cache: "no-store" });
    if (!r.ok) throw new Error(`the simulation answered ${r.status}`);
    const s = await r.json();
    render(s.state === "up" || s.state === "degraded" ? s.state : "down", describe(s));
  } catch (err) {
    const why = err.name === "AbortError" ? "the status check timed out" : err.message;
    render("down", `Ollama: unknown — ${why}\nclick to check now`);
  } finally {
    clearTimeout(abort);
    inFlight = false;
  }
}

function schedule() {
  clearInterval(timer);
  timer = document.hidden ? null : setInterval(check, POLL_MS);
}

if (el) {
  el.addEventListener("click", check);
  // No polling from a background tab; check straight away on coming back.
  document.addEventListener("visibilitychange", () => {
    schedule();
    if (!document.hidden) check();
  });
  check();
  schedule();
}
