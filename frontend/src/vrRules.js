// src/vrRules.js -- VR "Personal rules" (context menu; src/vrDebug.js draws the panel from spec()/choose()).
//
// Rules a character keeps, learned from your notes on their lines (Conversations timeline: like / dislike, why, a
// better line). The model writes them in the character's voice from the notes (backend/systems/personal_rules.py);
// none counts until you approve it:
//
//   proposed     ✔ approve (from now on it's in their prompt), ✘ reject (never proposed again), ✎ edit the wording
//   approved     open one to retire it or edit it
//   Propose from notes now   don't wait for enough notes to pile up
//   Write a rule…            your own rule (dictation or the pointer keyboard), approved straight away

const SHOW_PROPOSED = 3;
const short = (t, n = 46) => (String(t || "").length > n ? String(t).slice(0, n - 1) + "…" : String(t || ""));

function setup() {
  const st = new Map();             // charId -> {view: "main" | "approved" | "rule", data, loading, error, ruleId, polled}
  const redraw = () => window.vrDebugRedraw?.();
  const S = (id) => { if (!st.has(id)) st.set(id, { view: "main" }); return st.get(id); };
  const url = (id, tail = "") => `/admin/rules/${encodeURIComponent(id)}${tail}`;

  async function call(id, path, body) {
    const s = S(id);
    s.loading = !s.data; s.error = null; redraw();
    try {
      const r = await fetch(url(id, path), body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      s.data = j;
    } catch (err) { s.error = err.message; }
    s.loading = false; s.polled = performance.now(); redraw();
    if (s.data?.asking) setTimeout(() => { if (st.get(id) === s && s.data?.asking) call(id, ""); }, 3000);   // until the model answers
  }

  function open(id) { const s = S(id); s.view = "main"; call(id, ""); }

  function spec(id) {
    const s = S(id);
    const c = window.getWorldCharacter?.(id) || {};
    const title = c.name || id;
    const back = { id: "r:back", label: "Back" };
    if (s.loading) return { title, subtitle: "Personal rules", lines: ["Loading…"], buttons: [back] };
    const d = s.data || {};
    const err = s.error ? [{ text: s.error, color: "#ff8a7a" }] : [];
    if (s.view === "approved") {
      return { title, subtitle: `Personal rules — ${d.approved?.length || 0} approved (in their prompt)`,
               lines: [...err, ...(d.approved?.length ? ["Pick one to retire it or change its wording."] : ["None yet."])],
               buttons: [...(d.approved || []).map((r) => ({ id: `r:open:${r.id}`, label: `${r.source === "director" ? "✍ " : ""}${short(r.text)}` })),
                         { id: "r:main", label: "Back" }] };
    }
    if (s.view === "rule") {
      const r = [...(d.approved || []), ...(d.proposed || [])].find((x) => x.id === s.ruleId);
      if (!r) { s.view = "main"; return spec(id); }
      const lines = [...err, { text: `“${r.text}”`, color: "#ffffff" }, { text: r.source === "director" ? "written by you" : "from your notes on:", color: "#8b98ad" }];
      for (const n of r.notes || []) lines.push({ text: `  “${short(n.utterance, 60)}”${n.verdict ? ` — ${n.verdict}d` : ""}${n.comment ? ` — ${short(n.comment, 50)}` : ""}`, color: "#c9d1d9" });
      return { title, subtitle: `Personal rule — ${r.status}`, lines,
               buttons: [...(r.status === "proposed" ? [{ id: `r:approve:${r.id}`, label: "✔ Approve" }, { id: `r:reject:${r.id}`, label: "✘ Reject" }]
                                                      : [{ id: `r:retire:${r.id}`, label: "Retire (take it out of their prompt)" }]),
                         { id: `r:edit:${r.id}`, label: "✎ Edit the wording…" }, { id: r.status === "proposed" ? "r:main" : "r:approvedview", label: "Back" }] };
    }
    // main
    const lines = [...err];
    if (d.asking) lines.push({ text: "The model is writing rules from your notes…", color: "#7ee787" });
    else if (d.notes_waiting) lines.push({ text: `${d.notes_waiting} note${d.notes_waiting === 1 ? "" : "s"} waiting to become rules (proposed on their own at ${d.min_notes})`, color: "#c9d1d9" });
    else lines.push({ text: "No notes waiting — like / dislike lines in Conversations, say why or suggest a better one.", color: "#8b98ad" });
    if (d.last?.outcome) lines.push({ text: `Last: ${d.last.outcome}`, color: "#8b98ad" });
    const prop = (d.proposed || []).slice(0, SHOW_PROPOSED);
    if (prop.length) lines.push({ text: " " }, { text: `PROPOSED (${d.proposed.length}) — approve before they count:`, color: "#ffd33d" });
    const buttons = [];
    prop.forEach((r, i) => {
      lines.push({ text: `${i + 1}. “${r.text}”`, color: "#ffffff" });
      const from = (r.notes || [])[0];
      if (from) lines.push({ text: `    from: “${short(from.utterance, 50)}”${from.comment ? ` — ${short(from.comment, 40)}` : ""}${r.notes.length > 1 ? ` (+${r.notes.length - 1})` : ""}`, color: "#8b98ad" });
      buttons.push({ id: `r:approve:${r.id}`, label: `✔ Approve ${i + 1}` }, { id: `r:reject:${r.id}`, label: `✘ Reject ${i + 1}` },
                   { id: `r:open:${r.id}`, label: `✎ Edit / details ${i + 1}` });
    });
    lines.push({ text: " " }, { text: `APPROVED: ${d.approved?.length || 0} rule${d.approved?.length === 1 ? "" : "s"} in their prompt`, color: "#7ee787" });
    for (const r of (d.approved || []).slice(-3)) lines.push({ text: `• ${short(r.text, 70)}`, color: "#c9d1d9" });
    buttons.push({ id: "r:approvedview", label: `Approved rules (${d.approved?.length || 0})…` },
                 ...(d.notes_waiting && !d.asking ? [{ id: "r:ask", label: `Propose from notes now (${d.notes_waiting})` }] : []),
                 { id: "r:write", label: "✍ Write a rule…" }, { id: "r:refresh", label: "Refresh" }, back);
    return { title, subtitle: "Personal rules", lines, buttons };
  }

  function choose(id, button) {
    const s = S(id);
    const [, act, rid] = button.split(":");
    if (act === "back") { st.delete(id); return "menu"; }
    if (act === "main") { s.view = "main"; return; }
    if (act === "approvedview") { s.view = "approved"; return; }
    if (act === "refresh") return call(id, "");
    if (act === "ask") return call(id, "/ask", {});
    if (act === "open") { s.view = "rule"; s.ruleId = rid; return; }
    if (act === "approve" || act === "reject" || act === "retire") { if (s.view === "rule") s.view = act === "retire" ? "approved" : "main"; return call(id, `/${rid}`, { action: act }); }
    if (act === "edit") {
      const r = [...(s.data?.approved || []), ...(s.data?.proposed || [])].find((x) => x.id === rid);
      window.vrKeyboard?.open({ title: "Edit the rule", prompt: "In their voice: “I …”", text: r?.text || "",
                                onDone: (text) => text && call(id, `/${rid}`, { action: "edit", text }) });
      return;
    }
    if (act === "write") {
      const name = (window.getWorldCharacter?.(id) || {}).name || "them";
      window.vrKeyboard?.open({ title: `A rule for ${name}`, prompt: "In their voice, e.g. “I keep it casual with family.” It counts straight away.",
                                onDone: (text) => text && call(id, "/add", { text }) });
    }
  }

  window.vrRules = { open, spec, choose, state: (id) => st.get(id) && { view: st.get(id).view, data: st.get(id).data } };
}

setup();
