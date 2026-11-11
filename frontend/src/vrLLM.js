// src/vrLLM.js -- two context-menu views (src/vrDebug.js draws the panel from spec()/choose()):
//
//   LLM log          every prompt sent to the model for this character and the reply, newest first: which prompt
//                    (the decision, a diary entry, an opinion...), how long ago, how long it took, cached / failed.
//                    Open one to read the whole exchange -- system prompt, context, reply -- page by page.
//                    (backend: llm/llm_client.py's per-character log, /admin/llm/{id}/log)
//   Choices & tags   the short version: each decision -- what was chosen from how many options -- and which of the
//                    character's tags the model said decided it (the one most significant, up to 3), plus any it
//                    named that aren't theirs. (backend: systems/choice_tags.py, /admin/llm/{id}/choices)

const LIST_PAGE = 8;
const TEXT_LINES = 22;            // lines of text per page when reading a prompt
const CHARS_PER_LINE = 58;        // roughly what fits the panel's width
const CHOICES_PAGE = 5;

const ago = (s) => (s == null ? "?" : s < 60 ? `${Math.round(s)} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${(s / 3600).toFixed(1)} h ago`);
const PURPOSE = { "llm_brain.think": "decision", "llm_brain._fill_missing_speech": "words to say" };
const purposeName = (p) => PURPOSE[p] || String(p || "?").replace(/^(\w+\.)*?(\w+)\.(\w+)$/, "$2 · $3").replace(/_/g, " ");

// a long text -> display lines (hard-wrapped, so pages have a known length)
function toLines(text, color) {
  const out = [];
  for (const para of String(text ?? "").split("\n")) {
    if (!para.trim()) { out.push({ text: " ", color }); continue; }
    let rest = para;
    while (rest.length > CHARS_PER_LINE) {
      let cut = rest.lastIndexOf(" ", CHARS_PER_LINE);
      if (cut < CHARS_PER_LINE * 0.5) cut = CHARS_PER_LINE;
      out.push({ text: rest.slice(0, cut), color });
      rest = rest.slice(cut).trimStart();
    }
    out.push({ text: rest, color });
  }
  return out;
}

function setup() {
  const st = new Map();             // charId -> {view: "log"|"entry"|"choices", page, list, entry, lines, choices, loading, error}
  const redraw = () => window.vrDebugRedraw?.();
  const S = (id) => { if (!st.has(id)) st.set(id, { page: 0 }); return st.get(id); };

  async function get(id, url, key) {
    const s = S(id);
    s.loading = true; s.error = null; redraw();
    try {
      const r = await fetch(url);
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      s[key] = j;
      if (key === "entry") s.lines = entryLines(j);
    } catch (err) { s.error = err.message; }
    s.loading = false; redraw();
  }

  function entryLines(e) {
    const lines = [];
    lines.push({ text: `${purposeName(e.purpose)} · ${ago(e.ago_s)} · ${e.elapsed_s ?? "?"} s${e.cached ? " · cached" : ""}`, color: "#8b98ad" });
    if (e.error) lines.push(...toLines(`FAILED: ${e.error}`, "#ff8a7a"));
    for (const m of e.messages || []) {
      lines.push({ text: " " }, { text: `── ${String(m.role || "?").toUpperCase()} ──`, color: m.role === "system" ? "#d2a8ff" : "#79c0ff" });
      lines.push(...toLines(m.content, "#c9d1d9"));
    }
    lines.push({ text: " " }, { text: "── REPLY ──", color: "#7ee787" });
    lines.push(...toLines(e.response || "(nothing)", "#e6ffe6"));
    return lines;
  }

  function open(id, view) {
    const s = S(id);
    s.view = view; s.page = 0;
    if (view === "log") get(id, `/admin/llm/${encodeURIComponent(id)}/log?limit=100`, "list");
    if (view === "choices") get(id, `/admin/llm/${encodeURIComponent(id)}/choices?limit=60`, "choices");
  }

  function spec(id) {
    const s = S(id);
    const c = window.getWorldCharacter?.(id) || {};
    const title = c.name || id;
    const back = { id: "l:back", label: "Back" };
    if (s.loading) return { title, subtitle: s.view === "choices" ? "Choices & tags" : "LLM log", lines: ["Loading…"], buttons: [back] };
    if (s.error) return { title, subtitle: "LLM", lines: [{ text: s.error, color: "#ff8a7a" }], buttons: [{ id: "l:refresh", label: "Try again" }, back] };

    if (s.view === "log") {
      const rows = s.list?.entries || [];
      const pages = Math.max(1, Math.ceil(rows.length / LIST_PAGE));
      const shown = rows.slice(s.page * LIST_PAGE, s.page * LIST_PAGE + LIST_PAGE);
      return {
        title, subtitle: `LLM log — ${rows.length} exchange${rows.length === 1 ? "" : "s"}, newest first`,
        lines: rows.length ? ["Pick one to read the prompt and the reply."] : ["Nothing sent to the model for them yet (this server's log starts at restart)."],
        buttons: [...shown.map((e) => ({ id: `l:e:${e.n}`,
                    label: `${e.error ? "✘ " : e.cached ? "♻ " : ""}${purposeName(e.purpose)} · ${ago(e.ago_s)} · ${e.elapsed_s ?? "?"} s` })),
                  ...(pages > 1 ? [{ id: "l:prev", label: "◀ Newer" }, { id: "l:next", label: `Older ▶  ${s.page + 1}/${pages}` }] : []),
                  { id: "l:refresh", label: "Refresh" }, back],
      };
    }
    if (s.view === "entry") {
      const lines = s.lines || [];
      const off = s.offset || 0;                     // first line shown (a page is TEXT_LINES from there)
      const reply = lines.findIndex((l) => l.text === "── REPLY ──");
      return {
        title, subtitle: `${purposeName(s.entry?.purpose)} — lines ${off + 1}–${Math.min(lines.length, off + TEXT_LINES)} of ${lines.length}`,
        lines: lines.slice(off, off + TEXT_LINES),
        buttons: [{ id: "l:tprev", label: "◀ Previous page" }, { id: "l:tnext", label: "Next page ▶" },
                  ...(reply >= 0 ? [{ id: "l:reply", label: "Jump to the reply" }] : []),
                  { id: "l:tolist", label: "Back to the list" }],
      };
    }
    // choices & tags
    const ch = s.choices || {};
    const rows = ch.choices || [];
    const pages = Math.max(1, Math.ceil(rows.length / CHOICES_PAGE));
    const lines = [{ text: `Tags now: ${(ch.tags_now || []).join(", ") || "(none)"}`, color: "#8b98ad" }, { text: " " }];
    for (const e of rows.slice(s.page * CHOICES_PAGE, s.page * CHOICES_PAGE + CHOICES_PAGE)) {
      const tgt = e.chosen?.target ? ` (${e.chosen.target})` : "";
      lines.push({ text: `${ago(e.ago_s)} — ${e.chosen?.type || "?"}${tgt}, from ${e.options?.length || "?"} options${e.fallback ? " [fallback]" : ""}`, color: "#e8eef8" });
      if (e.significant?.length) lines.push({ text: `   ★ ${e.significant.join(", ")}`, color: "#7ee787" });
      else lines.push({ text: e.said ? "   no trait mattered" : "   (the reply named no tags)", color: "#8b98ad" });
      if (e.not_theirs?.length) lines.push({ text: `   not theirs: ${e.not_theirs.join(", ")}`, color: "#ffa657" });
    }
    if (!rows.length) lines.push("No decisions recorded yet.");
    return {
      title, subtitle: `Choices & tags — ${rows.length} recent decision${rows.length === 1 ? "" : "s"}`, lines,
      buttons: [...(pages > 1 ? [{ id: "l:prev", label: "◀ Newer" }, { id: "l:next", label: `Older ▶  ${s.page + 1}/${pages}` }] : []),
                { id: "l:refresh", label: "Refresh" }, back],
    };
  }

  function choose(id, button) {
    const s = S(id);
    const b = button.slice(2);
    if (b === "back") { st.delete(id); return "menu"; }
    if (b === "refresh") return open(id, s.view === "entry" ? "log" : s.view);
    if (b === "prev") { s.page = Math.max(0, s.page - 1); return; }
    if (b === "next") {
      const n = s.view === "log" ? Math.ceil((s.list?.entries || []).length / LIST_PAGE) : Math.ceil((s.choices?.choices || []).length / CHOICES_PAGE);
      s.page = Math.min(Math.max(0, n - 1), s.page + 1); return;
    }
    if (b.startsWith("e:")) {
      s.listPage = s.page; s.view = "entry"; s.offset = 0;
      return get(id, `/admin/llm/${encodeURIComponent(id)}/log/${b.slice(2)}`, "entry");
    }
    if (b === "tprev") { s.offset = Math.max(0, (s.offset || 0) - TEXT_LINES); return; }
    if (b === "tnext") { s.offset = Math.min(Math.max(0, (s.lines || []).length - 1), (s.offset || 0) + TEXT_LINES); return; }
    if (b === "reply") { const i = (s.lines || []).findIndex((l) => l.text === "── REPLY ──"); if (i >= 0) s.offset = i; return; }
    if (b === "tolist") { s.view = "log"; s.page = s.listPage || 0; return; }
  }

  window.vrLLM = { open, spec, choose, state: (id) => st.get(id) && { view: st.get(id).view, page: st.get(id).page, offset: st.get(id).offset, lines: (st.get(id).lines || []).length } };
}

setup();
