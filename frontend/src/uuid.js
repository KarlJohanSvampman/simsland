// A random v4 UUID that works everywhere. crypto.randomUUID() exists only in a "secure context" (https, or localhost):
// opened over plain http from another machine (http://192.168.x.x:5173) it is undefined, and every "New template" /
// "Add" button that made an id threw "crypto.randomUUID is not a function" and did nothing. crypto.getRandomValues()
// is available in every context.
export function uuid() {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  const b = new Uint8Array(16);
  if (c && typeof c.getRandomValues === "function") c.getRandomValues(b);
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6] & 0x0f) | 0x40;          // version 4
  b[8] = (b[8] & 0x3f) | 0x80;          // RFC 4122 variant
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
