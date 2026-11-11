// src/panels/api.js -- the debug panels API (backend api/debug_panels.py), shared by the panel designer and VR.

async function j(method, url, body) {
  const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(out.detail || out.error || r.statusText);
  return out;
}

export const listTemplates = () => j("GET", "/admin/panels");
export const saveTemplate = (t) => j("PUT", `/admin/panels/templates/${encodeURIComponent(t.id)}`, t);
export const deleteTemplate = (id) => j("DELETE", `/admin/panels/templates/${encodeURIComponent(id)}`);
export const panelsFor = (kind, id) => j("GET", `/admin/panels/for/${kind}/${encodeURIComponent(id)}`);
export const saveLayouts = (kind, id, body) => j("PUT", `/admin/panels/for/${kind}/${encodeURIComponent(id)}`, body);
export const listEntities = (kind) => j("GET", `/admin/panels/entities?kind=${kind}`);
export const fieldsOf = (kind, id, path = "", depth = 2) =>
  j("GET", `/admin/panels/fields/${kind}/${encodeURIComponent(id)}?path=${encodeURIComponent(path)}&depth=${depth}`);
export const dataOf = (kind, id, path = "", limit = 500) =>
  j("GET", `/admin/panels/data/${kind}/${encodeURIComponent(id)}?path=${encodeURIComponent(path)}&limit=${limit}`);

// Keeps each (entity, template) panel's data fresh, at the template's own refresh rate.
export class PanelFeed {
  constructor() { this.cache = new Map(); }
  get(kind, id, template) {
    const key = `${kind}:${id}:${template.id}:${template.source?.path || ""}`;
    let e = this.cache.get(key);
    const every = Math.max(0.5, Number(template.source?.refresh_s) || 2) * 1000;
    if (!e) { e = { value: undefined, at: 0, busy: false, error: null }; this.cache.set(key, e); }
    if (!e.busy && Date.now() - e.at > every) {
      e.busy = true;
      dataOf(kind, id, template.source?.path || "", template.options?.limit || 500)
        .then((r) => { e.value = r.value; e.error = null; })
        .catch((err) => { e.error = err.message; })
        .finally(() => { e.at = Date.now(); e.busy = false; });
    }
    return e;
  }
}
