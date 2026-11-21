// Thin client for the Chisel API (same origin, or API_BASE in the Android app).
import { API_BASE } from "./config.js";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed (${status})`);
    this.status = status;
  }
}

let token = null;
let onUnauthorized = () => {};
export const setToken = (t) => { token = t; };
export const setOnUnauthorized = (fn) => { onUnauthorized = fn; };

async function call(method, path, { json, form, raw } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let body;
  if (json) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  let res;
  try {
    res = await fetch(API_BASE + path, { method, headers, body, cache: "no-store" });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection (a sleeping server can take up to a minute to wake).");
  }
  if (res.status === 401 && token) onUnauthorized();
  if (!res.ok) {
    let detail = "";
    try {
      const d = await res.json();
      detail = typeof d.detail === "string" ? d.detail : Array.isArray(d.detail) ? d.detail[0]?.msg : "";
    } catch {}
    throw new ApiError(res.status, detail);
  }
  if (raw) return new Uint8Array(await res.arrayBuffer());
  return res.json();
}

export const api = {
  health: () => call("GET", "/api/health"),
  register: (email) => call("POST", "/api/register", { json: { email } }),
  verify: (email, code) => call("POST", "/api/verify-otp", { json: { email, code } }),
  uploadKeys: (payload) => call("PUT", "/api/keys", { json: payload }),
  publicKeys: (email) => call("GET", `/api/users/${encodeURIComponent(email)}/public-keys`),
  coverImage: () => call("GET", "/api/cover-image", { raw: true }),
  send: (receiverEmail, png) => {
    const form = new FormData();
    form.append("receiver_email", receiverEmail);
    form.append("stego_image", new Blob([png], { type: "image/png" }), "image.png");
    return call("POST", "/api/messages", { form });
  },
  inbox: () => call("GET", "/api/messages/inbox"),
  image: (id) => call("GET", `/api/messages/${encodeURIComponent(id)}/image`, { raw: true }),
  remove: (id) => call("DELETE", `/api/messages/${encodeURIComponent(id)}`),
  clearChats: (withEmail) => call("DELETE", `/api/chats${withEmail ? `?with=${encodeURIComponent(withEmail)}` : ""}`),
  me: () => call("GET", "/api/me"),
  setName: (display_name) => call("PUT", "/api/me", { json: { display_name } }),
  deleteAccount: () => call("DELETE", "/api/me"),
};
