// src/vrDirector.js -- Director Mode's "STOP!" and Director's Cut in VR (backend/systems/directors_cut.py).
//
// STOP!     time stops for everyone; the characters within reach of you turn to look at you (and keep facing you as
//           you move) with an amber ring under them; a banner says time is stopped. "Action!" lets it run again --
//           nobody was interrupted, the world carries on from exactly where it stopped.
//             * context menu: "STOP!" / "Action!" (any time)
//             * in Director Mode (hold a grip still -- operator_view.js): click a thumbstick, or say "stop" / "freeze"
//               and "action" / "go on" (voice where the browser has speech recognition)
//
// Director's Cut   (context menu on a character -- src/vrDebug.js draws the panel from spec()/choose())
//           what they chose last; what they should do instead and why that's more like them (dictation or the pointer
//           keyboard, vrKeyboard.js); key -> value changes in any area -- traits, speech quirks, insecurities,
//           confidence sources (add / remove / replace), or a fact about them: opinions, values, principles,
//           preferences (food, products, people), hobbies, routines, intentions, expectations of relationships /
//           others / themselves, ideal partner, what they want out of life, parents' / society's expectations,
//           temperament, patience, manners, generosity...; optionally keep the "why" as a personal rule. Apply it --
//           and undo any past cut.

import * as THREE from "three";

const POLL_S = 1;
const RADIUS = 8;
const PAGE = 9;
const short = (t, n = 44) => (String(t ?? "").length > n ? String(t).slice(0, n - 1) + "…" : String(t ?? ""));

function setup(ctx) {
  const { renderer, scene, camera, controllers, sims } = ctx;
  let stop = { active: false };
  let clock = 0, lastT = performance.now(), polled = -1e9, busy = false;
  const rings = new Map();

  // ---- the banner, fixed in view ----
  const bCanvas = document.createElement("canvas"); bCanvas.width = 1024; bCanvas.height = 140;
  const bTex = new THREE.CanvasTexture(bCanvas); bTex.colorSpace = THREE.SRGBColorSpace;
  const banner = new THREE.Mesh(new THREE.PlaneGeometry(0.62, 0.085), new THREE.MeshBasicMaterial({ map: bTex, transparent: true, depthTest: false }));
  banner.renderOrder = 1002; banner.position.set(0, 0.22, -0.8); banner.visible = false; banner.userData.ignoreRaycast = true;
  camera.add(banner);
  if (!camera.parent) scene.add(camera);
  function drawBanner() {
    const c = bCanvas.getContext("2d");
    c.clearRect(0, 0, 1024, 140);
    c.fillStyle = "rgba(160,90,0,0.88)"; c.beginPath(); c.roundRect(4, 4, 1016, 132, 26); c.fill();
    c.fillStyle = "#fff"; c.font = "bold 54px system-ui, sans-serif"; c.textBaseline = "middle"; c.textAlign = "center";
    c.fillText(`⏸ TIME STOPPED · ${stop.char_ids?.length || 0} looking at you`, 512, 50);
    c.font = "30px system-ui, sans-serif"; c.fillText("“Action!” (menu, thumbstick click or say it) to let it run", 512, 104);
    bTex.needsUpdate = true;
  }

  const here = () => { const p = camera.getWorldPosition(new THREE.Vector3()); return { x: p.x + 10, y: p.z + 7 }; };
  async function post(path, body) {
    const r = await fetch(`/director${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.statusText);
    return j;
  }
  async function poll() {
    if (busy) return;
    try { const r = await fetch("/director/stop"); if (r.ok) setStop(await r.json()); } catch (_) { /* next time */ }
  }
  function setStop(s) {
    const was = stop.active;
    stop = s || { active: false };
    if (stop.active) drawBanner();
    banner.visible = !!stop.active;
    if (was !== !!stop.active) window.vrDebugRedraw?.();
  }
  async function doStop() {
    busy = true;
    try { const p = here(); setStop(await post("/stop", { x: p.x, y: p.y, radius: RADIUS })); } catch (err) { console.warn("STOP failed", err); }
    busy = false;
  }
  async function doResume() {
    busy = true;
    try { setStop(await post("/resume")); } catch (err) { console.warn("resume failed", err); }
    busy = false;
  }
  const toggle = () => (stop.active ? doResume() : doStop());

  // ---- while stopped: they look at you, with a ring under them ----
  function lookAtMe() {
    const want = new Set(stop.active ? stop.char_ids || [] : []);
    const me = camera.getWorldPosition(new THREE.Vector3());
    for (const id of want) {
      const m = sims[id];
      if (!m) continue;
      const p = m.getWorldPosition(new THREE.Vector3());
      m.rotation.y = Math.atan2(me.x - p.x, me.z - p.z);
      let r = rings.get(id);
      if (!r) {
        r = new THREE.Mesh(new THREE.RingGeometry(0.42, 0.5, 48), new THREE.MeshBasicMaterial({ color: 0xffa000, transparent: true, opacity: 0.85, depthTest: false, side: THREE.DoubleSide }));
        r.rotation.x = -Math.PI / 2; r.renderOrder = 995; r.userData.ignoreRaycast = true; scene.add(r); rings.set(id, r);
      }
      r.position.set(p.x, p.y + 0.04, p.z);
      r.material.opacity = 0.6 + 0.3 * Math.sin(clock * 3);
    }
    for (const [id, r] of rings) if (!want.has(id)) { scene.remove(r); r.geometry.dispose(); r.material.dispose(); rings.delete(id); }
  }

  // ---- Director Mode: thumbstick click and voice ----
  const stickWas = [false, false];
  function sticks() {
    if (!window.getDirectorModeActive?.()) return;
    controllers.forEach((c, i) => {
      const g = c.userData.inputSource?.gamepad;
      const pressed = !!g?.buttons?.[3]?.pressed;       // xr-standard: 3 = thumbstick press
      if (pressed && !stickWas[i]) toggle();
      stickWas[i] = pressed;
    });
  }
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, wantVoice = false;
  function voice() {
    const should = !!window.getDirectorModeActive?.() && renderer.xr.isPresenting && !!Speech && !window.vrKeyboard?.isOpen();
    if (should === wantVoice) return;
    wantVoice = should;
    if (should) startVoice(); else { try { rec?.abort(); } catch (_) { /* fine */ } rec = null; }
  }
  function startVoice() {
    try {
      rec = new Speech(); rec.continuous = true; rec.interimResults = true; rec.lang = navigator.language || "en-US";
      rec.onresult = (ev) => {
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const t = ev.results[i][0].transcript.toLowerCase();
          if (/\b(stop|freeze|cut)\b/.test(t) && !stop.active) { doStop(); break; }
          if (/\b(action|go on|carry on|resume)\b/.test(t) && stop.active) { doResume(); break; }
        }
      };
      rec.onend = () => { if (wantVoice) setTimeout(() => { if (wantVoice) startVoice(); }, 300); };
      rec.onerror = () => {};
      rec.start();
    } catch (_) { rec = null; }
  }

  window.xrFrameHooks.push(() => {
    const t = performance.now(); clock += (t - lastT) / 1000; lastT = t;
    if (clock - polled > POLL_S) { polled = clock; poll(); }
    lookAtMe(); sticks(); voice();
  });

  // ---- Director's Cut (the context menu panel) ----
  const cuts = new Map();     // charId -> {screen, data, draft: {instead, why, changes, keep}, area, page, error, saving, msg}
  const redraw = () => window.vrDebugRedraw?.();
  const S = (id) => { if (!cuts.has(id)) cuts.set(id, { screen: "main", draft: { instead: "", why: "", changes: [], keep: false }, page: 0 }); return cuts.get(id); };
  async function load(id) {
    const s = S(id);
    s.loading = !s.data; redraw();
    try { const r = await fetch(`/director/cut/${encodeURIComponent(id)}`); const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.statusText); s.data = j; s.error = null; }
    catch (err) { s.error = err.message; }
    s.loading = false; redraw();
  }
  function openCut(id) { const s = S(id); s.screen = "main"; s.msg = null; load(id); }
  const areaOf = (s, id) => (s.data?.areas || []).find((a) => a.id === id) || { id, label: id };
  const describe = (s, ch) => {
    const a = areaOf(s, ch.area);
    if (a.kind === "list") return ch.action === "replace" ? `${a.label}: “${ch.old}” → “${ch.value}”` : `${a.label}: ${ch.action} “${ch.value}”`;
    return `${a.label}${ch.key ? ` (${ch.key})` : ""}: ${ch.action === "remove" ? "forget it" : `“${ch.value}”`}`;
  };

  function spec(id) {
    const s = S(id);
    const c = window.getWorldCharacter?.(id) || {};
    const title = c.name || id;
    const back = { id: "c:back", label: "Back" };
    if (s.loading) return { title, subtitle: "Director's Cut", lines: ["Loading…"], buttons: [back] };
    const d = s.data || {};
    const err = s.error ? [{ text: s.error, color: "#ff8a7a" }] : [];
    if (s.screen === "areas") {
      const list = d.areas || [];
      const pages = Math.max(1, Math.ceil(list.length / PAGE));
      return { title, subtitle: "Director's Cut — what to change", lines: ["Pick an area."],
               buttons: [...list.slice(s.page * PAGE, s.page * PAGE + PAGE).map((a) => ({ id: `c:area:${a.id}`, label: a.label })),
                         ...(pages > 1 ? [{ id: "c:prev", label: "◀ More" }, { id: "c:next", label: `More ▶  ${s.page + 1}/${pages}` }] : []),
                         { id: "c:main", label: "Back" }] };
    }
    if (s.screen === "area") {
      const a = areaOf(s, s.area);
      if (a.kind === "list") {
        const items = d.lists?.[a.id] || [];
        return { title, subtitle: `Director's Cut — ${a.label}`, lines: [items.length ? `Now: ${items.join(", ")}` : "None yet.", "Add one, or pick one to remove or replace."],
                 buttons: [{ id: "c:listadd", label: `+ Add a ${a.label.toLowerCase()}…` },
                           ...items.slice(0, 8).map((t) => ({ id: `c:item:${t}`, label: `“${short(t, 30)}” — remove / replace` })),
                           { id: "c:areas", label: "Back" }] };
      }
      const facts = d.facts?.[a.id] || {};
      return { title, subtitle: `Director's Cut — ${a.label}`, lines: [Object.keys(facts).length ? "Now:" : "Nothing set yet.",
               ...Object.entries(facts).map(([k, v]) => `• ${k === "general" ? "" : k + ": "}${short(v, 70)}`)],
               buttons: [{ id: "c:factnew", label: "+ Set one… (what about, then what)" },
                         ...Object.keys(facts).slice(0, 6).map((k) => ({ id: `c:fact:${k}`, label: `✎ ${k === "general" ? a.label : k}` })),
                         { id: "c:areas", label: "Back" }] };
    }
    if (s.screen === "item") {
      const a = areaOf(s, s.area);
      return { title, subtitle: `Director's Cut — ${a.label} “${short(s.item, 30)}”`, lines: ["Remove it, or replace it with another."],
               buttons: [{ id: "c:itemremove", label: "Remove it" }, { id: "c:itemreplace", label: "Replace it with…" }, { id: "c:area:" + s.area, label: "Back" }] };
    }
    if (s.screen === "fact") {
      const a = areaOf(s, s.area);
      return { title, subtitle: `Director's Cut — ${a.label}${s.key && s.key !== "general" ? ` (${s.key})` : ""}`, lines: [`Now: ${short(d.facts?.[a.id]?.[s.key], 80) || "—"}`],
               buttons: [{ id: "c:factedit", label: "✎ Change it…" }, { id: "c:factforget", label: "Forget it" }, { id: "c:area:" + s.area, label: "Back" }] };
    }
    if (s.screen === "history") {
      const list = (d.cuts || []).slice(0, 8);
      return { title, subtitle: "Director's Cut — past cuts", lines: list.length ? list.map((x) => ({ text: `${x.undone ? "↶ " : ""}${x.instead ? `instead: ${short(x.instead, 40)}` : ""}${x.changes.length ? ` · ${x.changes.length} change${x.changes.length === 1 ? "" : "s"}` : ""}${x.why ? ` · why: ${short(x.why, 30)}` : ""}`, color: x.undone ? "#8b98ad" : "#c9d1d9" })) : ["None yet."],
               buttons: [...list.filter((x) => !x.undone).map((x) => ({ id: `c:undo:${x.id}`, label: `↶ Undo: ${short(x.instead || describe(s, x.changes[0] || {}), 34)}` })), { id: "c:main", label: "Back" }] };
    }
    // main
    const lc = d.last_choice || {};
    const dr = s.draft;
    const lines = [...err];
    if (s.msg) lines.push({ text: s.msg, color: "#7ee787" });
    if (d.stopped) lines.push({ text: "⏸ Time is stopped.", color: "#ffb340" });
    lines.push({ text: `Chose last: ${lc.chosen ? `${lc.chosen.type || "?"}${lc.chosen.target ? ` (${short(lc.chosen.target, 30)})` : ""}` : "—"}${lc.doing_now ? ` · doing now: ${lc.doing_now}` : ""}`, color: "#c9d1d9" });
    if (lc.tags?.length) lines.push({ text: `   because of: ${lc.tags.join(", ")}`, color: "#8b98ad" });
    lines.push({ text: " " });
    lines.push({ text: `Instead: ${dr.instead || "—"}`, color: dr.instead ? "#ffffff" : "#8b98ad" });
    lines.push({ text: `Why it's more like them: ${dr.why || "—"}`, color: dr.why ? "#ffffff" : "#8b98ad" });
    if (dr.changes.length) { lines.push({ text: "Changes:", color: "#ffd33d" }); dr.changes.forEach((ch, i) => lines.push({ text: `  ${i + 1}. ${describe(s, ch)}`, color: "#e6edf3" })); }
    const ready = dr.instead || dr.changes.length || (dr.keep && dr.why);
    return { title, subtitle: "Director's Cut", lines,
             buttons: [{ id: "c:instead", label: dr.instead ? "✎ What they do instead" : "✎ What should they do instead…" },
                       { id: "c:why", label: dr.why ? "✎ Why" : "✎ Why is that more like them…" },
                       { id: "c:areas", label: "+ Add a change (trait, opinion, preference…)" },
                       ...dr.changes.map((ch, i) => ({ id: `c:drop:${i}`, label: `✕ Drop change ${i + 1}` })),
                       { id: "c:keep", label: `${dr.keep ? "☑" : "☐"} Keep the “why” as a personal rule` },
                       ...(ready ? [{ id: "c:apply", label: s.saving ? "Applying…" : "✔ Apply the cut" }] : []),
                       { id: "c:history", label: `Past cuts (${(d.cuts || []).length})…` },
                       { id: "c:stop", label: stop.active ? "▶ Action! (time runs)" : "⏸ STOP! (time stops)" }, back] };
  }

  function kb(title, prompt, text, done) { window.vrKeyboard?.open({ title, prompt, text: text || "", onDone: (t) => { done(t); redraw(); } }); }

  function choose(id, button) {
    const s = S(id);
    const parts = button.split(":");
    const act = parts[1], arg = parts.slice(2).join(":");
    const dr = s.draft;
    const who = (window.getWorldCharacter?.(id) || {}).name || "them";
    if (act === "back") { cuts.delete(id); return "menu"; }
    if (act === "main") { s.screen = "main"; return; }
    if (act === "stop") { toggle(); return; }
    if (act === "areas") { s.screen = "areas"; s.page = 0; return; }
    if (act === "prev") { s.page = Math.max(0, s.page - 1); return; }
    if (act === "next") { s.page = Math.min(Math.ceil((s.data?.areas || []).length / PAGE) - 1, s.page + 1); return; }
    if (act === "history") { s.screen = "history"; return; }
    if (act === "instead") return kb("What should they do instead?", `e.g. “go and apologise to Kathleen”`, dr.instead, (t) => { dr.instead = t; });
    if (act === "why") return kb(`Why is that more like ${who}?`, "In plain words -- it can also become one of their personal rules.", dr.why, (t) => { dr.why = t; });
    if (act === "keep") { dr.keep = !dr.keep; return; }
    if (act === "drop") { dr.changes.splice(Number(arg), 1); return; }
    if (act === "area") { s.area = arg; s.screen = "area"; return; }
    if (act === "listadd") { const a = areaOf(s, s.area); return kb(`Add a ${a.label.toLowerCase()}`, `for ${who}`, "", (t) => { if (t) { dr.changes.push({ area: s.area, action: "add", value: t }); s.screen = "main"; } }); }
    if (act === "item") { s.item = arg; s.screen = "item"; return; }
    if (act === "itemremove") { dr.changes.push({ area: s.area, action: "remove", value: s.item }); s.screen = "main"; return; }
    if (act === "itemreplace") { const a = areaOf(s, s.area); return kb(`Replace “${s.item}”`, `with which ${a.label.toLowerCase()}?`, "", (t) => { if (t) { dr.changes.push({ area: s.area, action: "replace", old: s.item, value: t }); s.screen = "main"; } }); }
    if (act === "factnew") {
      const a = areaOf(s, s.area);
      return kb(`${a.label} — what about?`, "e.g. food, music, money, family… (leave empty for in general)", "", (key) => {
        setTimeout(() => kb(`${a.label}${key ? ` (${key})` : ""}`, `What is it for ${who}?`, "", (t) => { if (t) { dr.changes.push({ area: s.area, key: key || "", action: "set", value: t }); s.screen = "main"; } }), 50);
      });
    }
    if (act === "fact") { s.key = arg; s.screen = "fact"; return; }
    if (act === "factedit") { const a = areaOf(s, s.area); return kb(`${a.label}${s.key !== "general" ? ` (${s.key})` : ""}`, `What is it for ${who}?`, s.data?.facts?.[s.area]?.[s.key], (t) => { if (t) { dr.changes.push({ area: s.area, key: s.key === "general" ? "" : s.key, action: "set", value: t }); s.screen = "main"; } }); }
    if (act === "factforget") { dr.changes.push({ area: s.area, key: s.key === "general" ? "" : s.key, action: "remove" }); s.screen = "main"; return; }
    if (act === "apply") {
      if (s.saving) return;
      s.saving = true;
      fetch(`/director/cut/${encodeURIComponent(id)}`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instead: dr.instead, why: dr.why, changes: dr.changes, keep_as_rule: dr.keep }) })
        .then(async (r) => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.statusText); s.data = j; s.error = null;
          s.msg = `Cut applied${dr.instead ? ` -- ${who} will ${dr.instead}` : ""}.`; s.draft = { instead: "", why: "", changes: [], keep: false }; })
        .catch((err) => { s.error = `couldn't apply: ${err.message}`; })
        .finally(() => { s.saving = false; redraw(); });
      return;
    }
    if (act === "undo") {
      fetch(`/director/cut/${encodeURIComponent(id)}/${arg}/undo`, { method: "POST" })
        .then(async (r) => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.statusText); s.data = j; s.msg = "Cut undone."; s.error = null; })
        .catch((err) => { s.error = `couldn't undo: ${err.message}`; }).finally(redraw);
    }
  }

  window.vrDirector = { toggle, stopped: () => !!stop.active, openCut, spec, choose,
    state: (id) => ({ stop, rings: [...rings.keys()], banner: banner.visible, cut: id && cuts.get(id) && { screen: cuts.get(id).screen, draft: cuts.get(id).draft, msg: cuts.get(id).msg, error: cuts.get(id).error } }) };
}

(function waitForXR(attempts = 50) {
  const ctx = window.getXRContext?.();
  if (ctx && window.xrFrameHooks) return setup(ctx);
  if (attempts > 0) setTimeout(() => waitForXR(attempts - 1), 100);
})();
