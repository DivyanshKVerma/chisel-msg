// Small UI toolkit: DOM builder (text is always inserted as text, never HTML),
// icons, toast, modal dialog, avatars and date formatting.

export function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (v === true) el.setAttribute(k, "");
    else if (v != null && v !== false) el.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

const ICONS = {
  info: '<circle cx="12" cy="12" r="9.5"/><path d="M12 11v6"/><circle cx="12" cy="7.5" r="1.2" fill="currentColor" stroke="none"/>',
  chats: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-5 4v-4.2A2.5 2.5 0 0 1 4 13.5z"/>',
  settings: '<circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V9c.26.6.86 1 1.51 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1z"/>',
  newchat: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-5 4v-4.2A2.5 2.5 0 0 1 4 13.5z"/><path d="M12 6.5v6M9 9.5h6"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  send: '<path d="M21 3L3 10.5l7.5 3L13.5 21z"/><path d="M21 3l-10.5 10.5"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  picture: '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="M3 17l5-5 4 4 3-3 6 6"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  arrowdown: '<path d="M12 5v14M6 13l6 6 6-6"/>',
};

export function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false" }))
    s.setAttribute(k, v);
  s.innerHTML = ICONS[name]; // static markup only
  return s;
}

export function toast(msg, high = false) {
  document.querySelector(".toast")?.remove();
  const t = h("div", { class: `toast${high ? " high" : ""}`, role: "status" }, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), 4200);
}

/** Bottom-sheet dialog. actions: [{ label, value, kind: "secondary-btn" | "warning" }] */
export function modal({ title, body, actions, onOpen }) {
  return new Promise((resolve) => {
    const prev = document.activeElement;
    const close = (v) => { back.remove(); document.removeEventListener("keydown", esc); prev?.focus?.(); resolve(v); };
    const esc = (e) => e.key === "Escape" && close(null);
    const back = h("div", { class: "modal-back", onclick: (e) => e.target === back && close(null) },
      h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "modal-title" },
        h("h2", { class: "h-l", id: "modal-title" }, title), body,
        h("div", { class: "btn-group" }, actions.map((a) =>
          h("button", { class: `btn ${a.kind || ""}`, type: "button", onclick: () => close(typeof a.value === "function" ? a.value() : a.value) }, a.label)))));
    document.body.append(back);
    document.addEventListener("keydown", esc);
    (back.querySelector("input") || back.querySelector("button"))?.focus();
    onOpen?.(back, close);
  });
}

export function avatar(name, key, small = false) {
  let hsh = 0;
  for (const c of key) hsh = (hsh * 31 + c.charCodeAt(0)) >>> 0;
  const initials = (name || key).trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("") || "?";
  return h("span", { class: `avatar av-${hsh % 8}${small ? " sm" : ""}`, "aria-hidden": "true" }, initials);
}

const pad = (n) => String(n).padStart(2, "0");
const clock = (d) => `${pad(d.getHours() % 12 || 12)}:${pad(d.getMinutes())} ${d.getHours() < 12 ? "am" : "pm"}`;
/** Mockup format: 13-12-26 | 08:58 pm */
export const stamp = (d) => `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${String(d.getFullYear()).slice(2)} | ${clock(d)}`;
export function listTime(d) {
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return clock(d);
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${String(d.getFullYear()).slice(2)}`;
}
export function dayLabel(d) {
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return "Today";
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
}
export function timeLeft(expires) {
  const s = (expires - Date.now()) / 1000;
  if (s <= 0) return "expired";
  if (s < 3600) return `vanishes in ${Math.ceil(s / 60)} min`;
  return `vanishes in ${Math.floor(s / 3600)} h`;
}
