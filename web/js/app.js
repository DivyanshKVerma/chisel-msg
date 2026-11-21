// Chisel — app screens and flows.
// All private work happens on this device: keys, encryption, hiding the message
// in the picture, finding and decrypting it. The server relays pictures and
// hands out AI-generated covers.
import * as C from "./chisel.js";
import * as store from "./store.js";
import * as D from "./data.js";
import { api, ApiError, setToken, setOnUnauthorized } from "./api.js";
import { h, icon, toast, modal, avatar, stamp, listTime, dayLabel, timeLeft } from "./ui.js";
import { APP_VERSION, API_BASE } from "./config.js";

const DAY = 24 * 3600 * 1000;
const MAX_CHARS = 2000;
const TABS = ["info", "chats", "settings"];
const root = document.getElementById("app");
const isTouch = matchMedia("(pointer: coarse)").matches;

const S = {
  me: null, name: null, keys: null,
  route: { name: "chats" },
  inbox: [], sent: [], pending: {}, contacts: new Map(), read: new Set(),
  images: new Map(), drafts: {}, signin: { step: "email" }, reveal: null, refs: {},
};

const friendly = (e) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));
const nameOf = (email) => S.contacts.get(email)?.name || email;

// ── theme ─────────────────────────────────────────────────
function themePref() { try { return localStorage.getItem("chisel-theme") || "system"; } catch { return "system"; } }
function applyTheme(pref = themePref()) {
  const el = document.documentElement;
  if (pref === "system") el.removeAttribute("data-theme"); else el.setAttribute("data-theme", pref);
  const dark = pref === "dark" || (pref === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", "#1d70b8");
  const bar = window.Capacitor?.Plugins?.StatusBar;
  if (bar) { bar.setBackgroundColor?.({ color: "#1d70b8" })?.catch?.(() => {}); bar.setStyle?.({ style: "DARK" })?.catch?.(() => {}); }
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme());
applyTheme();

// ── navigation (history-backed, so browser + Android back both work) ──
function nav(route, { replace = false } = {}) {
  S.route = route;
  S.reveal = null;
  (replace ? history.replaceState : history.pushState).call(history, route, "");
  render();
  window.scrollTo(0, 0);
}
window.addEventListener("popstate", (e) => {
  if (!S.me) return;
  S.route = e.state || { name: "chats" };
  S.reveal = null;
  render();
});
function goBack() {
  if (S.reveal) return closeReveal();
  if (!TABS.includes(S.route.name)) return history.length > 1 ? history.back() : nav({ name: "chats" }, { replace: true });
  if (S.route.name !== "chats") return nav({ name: "chats" }, { replace: true });
  window.Capacitor?.Plugins?.App?.exitApp?.();
}
window.Capacitor?.Plugins?.App?.addListener?.("backButton", () => { if (!S.me) return; goBack(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.reveal) closeReveal(); });

// ── session & keys ────────────────────────────────────────
async function signOut(message) {
  await store.del("session");
  setToken(null);
  for (const [k, url] of S.images) if (typeof url === "string" && !k.startsWith("bytes:")) URL.revokeObjectURL(url);
  Object.assign(S, { me: null, name: null, keys: null, inbox: [], sent: [], pending: {}, contacts: new Map(), read: new Set(), images: new Map(), drafts: {}, reveal: null, signin: { step: "email" } });
  history.replaceState(null, "");
  render();
  if (message) toast(message);
}
setOnUnauthorized(() => signOut("Your session ended. Sign in again with a new code."));

async function setupKeys(email) {
  let keys = await store.get(`keys:${email}`);
  let server = null;
  try { server = await api.publicKeys(email); } catch (e) { if (e.status !== 404) throw e; }
  if (keys && server && server.ed25519_pub_hex === C.toHex(keys.signPub)) return maybeRotate(keys);
  const fresh = keys || C.generateKeys(email);
  try {
    await api.uploadKeys(C.keyUploadPayload(fresh));
  } catch (e) {
    if (e.status !== 409) throw e;
    const ok = await modal({
      title: "Use this phone for your account?",
      body: h("div", {},
        h("p", { class: "body" }, "Your account's keys are on another phone, or were removed from this one."),
        h("div", { class: "warning-text" }, h("span", { class: "bang", "aria-hidden": "true" }, "!"),
          h("span", {}, "Pictures waiting for your old keys can't be opened, and your contacts will see that your safety number changed."))),
      actions: [{ label: "Reset keys on this phone", value: true }, { label: "Cancel", value: false, kind: "secondary-btn" }],
    });
    if (!ok) return null;
    await api.uploadKeys(C.keyUploadPayload(fresh, true));
    toast("New keys created. Your safety number changed.");
  }
  await store.set(`keys:${email}`, fresh);
  return fresh;
}

async function maybeRotate(keys, force = false) {
  if (!force && Date.now() - keys.encCreatedAt < DAY) return keys;
  const next = C.rotateDailyKey(keys);
  await api.uploadKeys(C.keyUploadPayload(next));
  await store.set(`keys:${keys.email}`, next);
  return next;
}

async function contactKeys(email) {
  const entry = await api.publicKeys(email);
  await D.rememberContact(S.me, email, entry.display_name);
  if (entry.display_name) S.contacts.set(email, { email, name: entry.display_name });
  const pins = store.pinsFor(S.me);
  try { return await C.loadVerifiedContact(entry, pins); }
  catch (e) {
    if (!(e instanceof C.IdentityChangedError)) throw e;
    const ok = await modal({
      title: "Safety number changed",
      body: h("div", {},
        h("p", { class: "body" }, `${nameOf(email)} has new keys. This happens with a new phone, or if someone is pretending to be them. Compare the new number with them in person before you trust it.`),
        h("span", { class: "caption" }, "Old number"), h("p", { class: "safety" }, C.fingerprint(e.oldPub)),
        h("span", { class: "caption" }, "New number"), h("p", { class: "safety" }, C.fingerprint(e.newPub))),
      actions: [{ label: "I've checked, trust it", value: true }, { label: "Cancel", value: false, kind: "secondary-btn" }],
    });
    if (!ok) throw new Error("Stopped: you didn't trust the new safety number.");
    await pins.set(email, e.newPub);
    return C.loadVerifiedContact(entry, pins);
  }
}

// ── data ──────────────────────────────────────────────────
async function loadLocal() {
  await D.purgeExpired(S.me);
  S.sent = await D.sentMessages(S.me);
  S.contacts = await D.contacts(S.me);
  S.read = await D.readSet(S.me);
}
let refreshing = null;
function refresh({ quiet = true } = {}) {
  if (!S.me) return null;
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      const { messages } = await api.inbox();
      S.inbox = messages.map((m) => ({ ...m, at: new Date(m.created_at), exp: new Date(m.expires_at) }));
      for (const m of S.inbox) {
        const known = S.contacts.get(m.sender_email);
        if (!known || (m.sender_display_name && known.name !== m.sender_display_name)) {
          S.contacts.set(m.sender_email, { email: m.sender_email, name: m.sender_display_name || known?.name || null });
          D.rememberContact(S.me, m.sender_email, m.sender_display_name);
        }
      }
      S.sent = await D.sentMessages(S.me);
      S.loadError = null;
    } catch (e) {
      S.loadError = friendly(e);
      if (!quiet) toast(S.loadError);
    } finally { refreshing = null; }
    if (S.route.name === "chat") markChatRead(S.route.email);
    update();
  })();
  return refreshing;
}

function conversations() {
  const conv = new Map();
  const add = (email, item) => {
    const c = conv.get(email) || { email, items: [] };
    c.items.push(item);
    conv.set(email, c);
  };
  for (const m of S.inbox) add(m.sender_email, { dir: "in", at: m.at, id: m.id });
  for (const m of S.sent) add(m.to, { dir: "out", at: new Date(m.createdAt), id: m.id });
  for (const [email, list] of Object.entries(S.pending)) for (const p of list) add(email, { dir: "out", at: new Date(p.createdAt), id: p.tmpId });
  for (const c of conv.values()) {
    c.items.sort((a, b) => a.at - b.at);
    c.last = c.items[c.items.length - 1];
    c.unread = c.items.filter((i) => i.dir === "in" && !S.read.has(i.id)).length;
  }
  return [...conv.values()].sort((a, b) => b.last.at - a.last.at);
}

function thread(email) {
  const items = [
    ...S.inbox.filter((m) => m.sender_email === email).map((m) => ({ dir: "in", id: m.id, at: m.at, exp: m.exp })),
    ...S.sent.filter((m) => m.to === email).map((m) => ({ dir: "out", id: m.id, at: new Date(m.createdAt), exp: new Date(m.expiresAt), local: m })),
    ...(S.pending[email] || []).map((p) => ({ dir: "out", id: p.tmpId, at: new Date(p.createdAt), pending: p })),
  ];
  return items.sort((a, b) => a.at - b.at);
}

async function imageUrl(id, expires) {
  if (S.images.has(id)) return S.images.get(id);
  let bytes = await D.cachedImage(S.me, id);
  if (!bytes) {
    bytes = await api.image(id);
    D.cacheImage(S.me, id, bytes, +expires);
  }
  const url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
  S.images.set(id, url);
  S.images.set(`bytes:${id}`, bytes);
  return url;
}
function localUrl(id, png) {
  if (!S.images.has(id)) S.images.set(id, URL.createObjectURL(new Blob([png], { type: "image/png" })));
  return S.images.get(id);
}

// ── rendering ─────────────────────────────────────────────
function render() {
  S.refs = {};
  if (!S.me) return root.replaceChildren(signInView());
  const views = { chats: chatsView, chat: chatView, new: newChatView, info: infoView, settings: settingsView, name: nameView, "delete-account": deleteAccountView };
  root.replaceChildren((views[S.route.name] || chatsView)());
}
/** Light refresh that keeps focus and typed text. */
function update() {
  if (!S.me) return;
  if (S.route.name === "chats" && S.refs.list) fillChatList();
  else if (S.route.name === "chat" && S.refs.thread && !S.reveal) fillThread();
}

function header(title, { back, action } = {}) {
  return h("header", { class: "header" }, h("div", { class: "header-inner" },
    back ? h("button", { class: "icon-btn", type: "button", "aria-label": "Back", onclick: goBack }, icon("back")) : null,
    h("span", { class: "title" }, title), action || null));
}

function tabbar(active) {
  const tabs = [["info", "Info", "info"], ["chats", "Chats", "chats"], ["settings", "Settings", "settings"]];
  return h("nav", { class: "tabbar glass", "aria-label": "Main" }, tabs.map(([name, label, ic]) =>
    h("button", { class: "tab", type: "button", "aria-current": active === name ? "page" : null,
      onclick: () => { if (active !== name) nav({ name }, { replace: true }); if (name === "chats") refresh(); } },
      icon(ic), label)));
}

function errorSummary(items) {
  if (!items?.length) return null;
  return h("div", { class: "error-summary", role: "alert", tabindex: "-1" },
    h("h2", { class: "h-m" }, "There is a problem"),
    h("ul", {}, items.map(([msg, target]) => h("li", {}, h("a", { href: `#${target}`, onclick: (e) => { e.preventDefault(); document.getElementById(target)?.focus(); } }, msg)))));
}

const fieldError = (msg) => msg ? h("p", { class: "error-message" }, h("span", { class: "visually-hidden" }, "Error: "), msg) : null;
const validEmail = (e) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);

// ── sign in ───────────────────────────────────────────────
function signInView() {
  const st = S.signin;
  const wrap = (...kids) => h("div", { class: "app" }, header("Chisel"), h("main", { class: "container", id: "main" }, ...kids));

  if (st.step === "email") {
    const input = h("input", { class: `input${st.error ? " error" : ""}`, id: "email", name: "email", type: "email", autocomplete: "email", spellcheck: "false", inputmode: "email", value: st.email || "" });
    return wrap(
      errorSummary(st.error && [[st.error, "email"]]),
      h("h1", { class: "h-xl" }, "Sign in to Chisel"),
      h("p", { class: "body-l" }, "Send private messages hidden inside AI-painted pictures. Only the person you send them to can read them."),
      h("form", { novalidate: true, onsubmit: async (e) => {
        e.preventDefault();
        const email = input.value.trim().toLowerCase();
        if (!validEmail(email)) { Object.assign(st, { email, error: "Enter an email address in the correct format, like name@example.com" }); return render(); }
        Object.assign(st, { email, busy: true, error: null }); render();
        try {
          const r = await api.register(email);
          Object.assign(st, { step: "code", busy: false, devCode: r.otp_for_demo || null });
        } catch (err) { Object.assign(st, { busy: false, error: friendly(err) }); }
        render();
      } },
        h("div", { class: `form-group${st.error ? " error" : ""}` },
          h("label", { class: "label", for: "email" }, "Email address"),
          h("span", { class: "hint" }, "We'll email you a 6-digit code. No password needed."),
          fieldError(st.error), input),
        h("button", { class: "btn", type: "submit", disabled: st.busy || null }, st.busy ? "Sending code…" : "Continue")));
  }

  if (st.step === "code") {
    const code = h("input", { class: `input code${st.error ? " error" : ""}`, id: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6", spellcheck: "false", value: st.devCode || "" });
    return wrap(
      errorSummary(st.error && [[st.error, "code"]]),
      h("h1", { class: "h-xl" }, "Check your email"),
      h("div", { class: "inset" }, "We've sent a 6-digit code to ", h("b", {}, st.email), ". It expires in 5 minutes."),
      st.devCode ? h("div", { class: "banner", role: "region", "aria-labelledby": "demo-title" },
        h("p", { class: "banner-title", id: "demo-title" }, "Demo server"),
        h("div", { class: "banner-body" }, "Your code is ", h("b", {}, st.devCode), ". On the live server it only arrives by email.")) : null,
      h("form", { novalidate: true, onsubmit: async (e) => {
        e.preventDefault();
        Object.assign(st, { busy: "Checking code…", error: null }); render();
        try {
          const r = await api.verify(st.email, code.value.trim());
          setToken(r.token);
          st.busy = "Creating your keys on this phone…"; render();
          const keys = await setupKeys(r.email);
          if (!keys) { setToken(null); S.signin = { step: "email", email: st.email }; return render(); }
          Object.assign(st, { token: r.token, email: r.email, keys });
          if (!r.display_name) { Object.assign(st, { step: "name", busy: false }); return render(); }
          await enterApp(r.email, r.token, keys, r.display_name);
        } catch (err) { setToken(null); Object.assign(st, { busy: false, error: friendly(err) }); render(); }
      } },
        h("div", { class: `form-group${st.error ? " error" : ""}` },
          h("label", { class: "label", for: "code" }, "Code"), fieldError(st.error), code),
        h("button", { class: "btn", type: "submit", disabled: st.busy || null }, st.busy || "Continue")),
      h("p", { class: "body" }, h("button", { class: "link-btn", type: "button", onclick: async () => {
        try { const r = await api.register(st.email); Object.assign(st, { devCode: r.otp_for_demo || null, error: null }); toast("New code sent."); }
        catch (err) { st.error = friendly(err); }
        render();
      } }, "Not received it? Send a new code")),
      h("p", { class: "body" }, h("button", { class: "link-btn", type: "button", onclick: () => { S.signin = { step: "email", email: st.email }; render(); } }, "Change email address")));
  }

  // step "name": a new account picks the name others will see
  const input = h("input", { class: `input${st.error ? " error" : ""}`, id: "name", autocomplete: "nickname", maxlength: "40", value: st.nameDraft || "" });
  return wrap(
    errorSummary(st.error && [[st.error, "name"]]),
    h("h1", { class: "h-xl" }, "What should people call you?"),
    h("form", { novalidate: true, onsubmit: async (e) => {
      e.preventDefault();
      const name = input.value.trim();
      if (!name) { Object.assign(st, { nameDraft: name, error: "Enter a name" }); return render(); }
      try {
        setToken(st.token);
        const r = await api.setName(name);
        await enterApp(st.email, st.token, st.keys, r.display_name);
      } catch (err) { Object.assign(st, { nameDraft: name, error: friendly(err) }); render(); }
    } },
      h("div", { class: `form-group${st.error ? " error" : ""}` },
        h("label", { class: "label", for: "name" }, "Your name"),
        h("span", { class: "hint" }, "People you send pictures to will see this, with your email address. You can change it later in Settings."),
        fieldError(st.error), input),
      h("button", { class: "btn", type: "submit" }, "Save and continue")));
}

async function enterApp(email, token, keys, name) {
  await store.set("session", { email, token });
  setToken(token);
  Object.assign(S, { me: email, name, keys, signin: { step: "email" } });
  await loadLocal();
  nav({ name: "chats" }, { replace: true });
  refresh();
}

// ── chats (inbox) ─────────────────────────────────────────
function chatsView() {
  const search = h("input", { class: "input", id: "search", type: "search", placeholder: "Search chats", "aria-label": "Search chats", value: S.search || "",
    oninput: (e) => { S.search = e.target.value; fillChatList(); } });
  S.refs.list = h("ul", { class: "chat-list", "aria-label": "Chats" });
  const v = h("div", { class: "app" },
    header("Chisel", { action: h("button", { class: "icon-btn", type: "button", "aria-label": "Refresh", onclick: () => refresh({ quiet: false }) }, icon("refresh")) }),
    h("main", { class: "container page-pad", id: "main" },
      h("h1", { class: "visually-hidden" }, "Chats"),
      h("div", { class: "search" }, icon("search"), search),
      S.refs.list),
    h("button", { class: "fab", type: "button", "aria-label": "New chat", onclick: () => nav({ name: "new" }) }, icon("newchat")),
    tabbar("chats"));
  fillChatList();
  return v;
}

function fillChatList() {
  const list = S.refs.list;
  if (!list) return;
  const q = (S.search || "").trim().toLowerCase();
  const convs = conversations().filter((c) => !q || c.email.includes(q) || nameOf(c.email).toLowerCase().includes(q));
  if (!convs.length) {
    list.replaceChildren(h("li", { class: "empty" },
      S.loadError && !q ? h("div", { class: "error-summary", role: "alert" }, h("h2", { class: "h-m" }, "There is a problem"), h("p", { class: "body" }, S.loadError))
        : [icon("picture"), h("h2", { class: "h-m" }, q ? "No chats match your search" : "No chats yet"),
          h("p", { class: "body secondary" }, q ? "Try a name or email address." : "Tap the new chat button to send someone a picture with a hidden message. Pictures vanish after 24 hours.")]));
    return;
  }
  list.replaceChildren(...convs.map((c) => h("li", {},
    h("button", { class: `chat-row${c.unread ? " unread" : ""}`, type: "button", onclick: () => nav({ name: "chat", email: c.email }) },
      avatar(nameOf(c.email), c.email),
      h("span", { class: "meta" },
        h("span", { class: "name" }, nameOf(c.email)),
        h("span", { class: "last" }, icon("picture"), h("span", { class: "clip" }, c.last.dir === "out" ? "You: Picture" : c.unread ? `${c.unread === 1 ? "New picture" : `${c.unread} new pictures`}` : "Picture"))),
      h("span", { class: "side" },
        h("span", { class: "when" }, listTime(c.last.at)),
        c.unread ? h("span", { class: "badge", "aria-label": `${c.unread} unread` }, String(c.unread)) : null)))));
}

// ── chat ──────────────────────────────────────────────────
function chatView() {
  const email = S.route.email;
  S.refs.thread = h("div", { class: "thread", role: "log", "aria-live": "polite", "aria-label": `Messages with ${nameOf(email)}` });
  const send = h("button", { class: "send-btn", type: "submit", "aria-label": "Send" }, icon("send"));
  const box = h("textarea", { id: "compose", rows: "1", maxlength: String(MAX_CHARS), placeholder: "Type here…", "aria-label": `Message ${nameOf(email)}`,
    oninput: (e) => { S.drafts[email] = e.target.value; grow(e.target); send.disabled = !e.target.value.trim(); },
    onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey && !isTouch) { e.preventDefault(); submit(); } } });
  box.value = S.drafts[email] || "";
  send.disabled = !box.value.trim();
  const submit = () => {
    const text = box.value.trim();
    if (!text) return;
    box.value = ""; S.drafts[email] = ""; grow(box); send.disabled = true;
    sendMessage(email, text);
  };
  const v = h("div", { class: "chat", id: "chat" },
    h("header", { class: "chat-head glass" },
      h("button", { class: "icon-btn", type: "button", "aria-label": "Back to chats", onclick: goBack }, icon("back")),
      avatar(nameOf(email), email, true),
      h("div", { class: "who" }, h("div", { class: "n" }, nameOf(email)), h("div", { class: "e" }, email)),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Delete this chat", onclick: () => deleteChat(email) }, icon("trash"))),
    S.refs.thread,
    h("form", { class: "composer glass-light", onsubmit: (e) => { e.preventDefault(); submit(); } }, box, send));
  S.refs.chat = v;
  markChatRead(email);
  fillThread(true);
  requestAnimationFrame(() => grow(box));
  return v;
}
function grow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 136) + "px"; }

function fillThread(scroll = false) {
  const el = S.refs.thread;
  if (!el) return;
  const email = S.route.email;
  const items = thread(email);
  const nearBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 160;
  const out = [];
  let lastDay = "";
  if (!items.length) out.push(h("p", { class: "body secondary" }, `Say something to ${nameOf(email)}. Your message is encrypted on this phone and hidden in a picture.`));
  for (const it of items) {
    const d = dayLabel(it.at);
    if (d !== lastDay) { out.push(h("div", { class: "day" }, d)); lastDay = d; }
    out.push(bubble(it));
  }
  el.replaceChildren(...out);
  if (scroll || nearBottom) requestAnimationFrame(() => window.scrollTo(0, document.body.scrollHeight));
}

function bubble(it) {
  const img = h("img", { alt: it.dir === "in" ? `Picture from ${nameOf(S.route.email)}` : "Picture you sent" });
  const btn = h("button", { class: "bubble-img", type: "button", "aria-label": it.dir === "in" ? "Show the hidden message" : "Show your message", onclick: () => onBubble(it) }, img);
  const wrap = h("div", { class: "bubble" }, btn);
  let status = null;
  if (it.pending) {
    const p = it.pending;
    if (p.png) img.src = localUrl(p.tmpId, p.png);
    if (p.status !== "failed") wrap.append(h("div", { class: "progress" }, h("span", {}, h("span", { class: "spinner", "aria-hidden": "true" }), p.step)));
    status = p.status === "failed" ? h("span", { class: "st err" }, "Not sent · tap to retry") : h("span", { class: "st" }, "Sending…");
  } else if (it.dir === "out") {
    img.src = localUrl(it.id, it.local.png);
    status = h("span", { class: "st" }, "Sent");
  } else {
    imageUrl(it.id, it.exp).then((u) => { img.src = u; }).catch(() => { img.alt = "Picture couldn't be loaded"; });
    if (S.fresh?.has(it.id)) wrap.append(h("span", { class: "chip" }, icon("eye"), "Tap to read"));
  }
  return h("div", { class: `msg ${it.dir}` }, wrap, h("div", { class: "stamp" }, `[${stamp(it.at)}]`, status));
}

/**
 * Opening a chat clears its unread badge (saved on this phone). Pictures that
 * were new when you opened it keep a "Tap to read" chip until you reveal them.
 */
function markChatRead(email) {
  S.fresh ??= new Set();
  for (const m of S.inbox) {
    if (m.sender_email !== email || S.read.has(m.id)) continue;
    S.fresh.add(m.id);
    S.read.add(m.id);
    D.markRead(S.me, m.id);
  }
}

async function sendMessage(email, text, retryOf = null) {
  const p = retryOf || { tmpId: `tmp-${C.uuid4()}`, text, createdAt: Date.now() };
  Object.assign(p, { status: "sending", step: "Checking keys…", png: null });
  if (!retryOf) (S.pending[email] ??= []).push(p);
  const step = (s) => { p.step = s; update(); };
  update();
  try {
    let them;
    try { them = await contactKeys(email); }
    catch (e) { if (e.status === 404) throw new Error(`${email} isn't on Chisel yet.`); throw e; }
    step("Getting a picture…");
    let cover;
    for (let tries = 0; ; tries++) {
      try { cover = await api.coverImage(); break; }
      catch (e) {
        if (e.status !== 503 || tries >= 6) throw e;
        step("Server is painting pictures…");
        await new Promise((r) => setTimeout(r, 10000));
      }
    }
    step("Hiding your message…");
    await new Promise((r) => setTimeout(r, 30));
    const { png } = await C.sealIntoImage(text, S.keys, email, them.encPub, cover);
    p.png = png;
    step("Sending…");
    const r = await api.send(email, png);
    const rec = { id: r.message_id, to: email, text, png, createdAt: p.createdAt, expiresAt: Date.parse(r.expires_at) };
    await D.saveSent(S.me, rec);
    S.sent.push(rec);
    if (S.images.has(p.tmpId)) { S.images.set(rec.id, S.images.get(p.tmpId)); S.images.delete(p.tmpId); }
    S.pending[email] = S.pending[email].filter((x) => x !== p);
  } catch (e) {
    Object.assign(p, { status: "failed", error: friendly(e) });
    toast(friendly(e), true);
  }
  update();
}

// ── reveal ────────────────────────────────────────────────
function onBubble(it) {
  if (it.pending) {
    if (it.pending.status === "failed") sendMessage(S.route.email, it.pending.text, it.pending);
    return;
  }
  openReveal(it);
}

function openReveal(it) {
  const email = S.route.email;
  S.reveal = { id: it.id };
  const card = h("div", { class: "reveal-card", role: "dialog", "aria-modal": "true", "aria-label": `Message ${it.dir === "in" ? "from" : "to"} ${nameOf(email)}`, tabindex: "-1", onclick: (e) => e.stopPropagation() },
    h("span", { class: "spinner", "aria-hidden": "true" }), "Finding the hidden message…");
  const layer = h("div", { class: "reveal", onclick: closeReveal }, card);
  S.refs.chat?.classList.add("revealing");
  S.refs.chat?.append(layer);
  S.refs.revealLayer = layer;
  card.focus();
  const show = (text, sub, err = false) => {
    if (S.reveal?.id !== it.id) return;
    card.className = `reveal-card${err ? " err" : ""}`;
    card.replaceChildren(text, h("span", { class: "sub" }, sub));
  };
  if (it.dir === "out") return show(it.local.text, `Sent ${stamp(it.at)} · ${timeLeft(+it.exp)} · tap outside to close`);
  (async () => {
    try {
      const sender = await contactKeys(email);
      await imageUrl(it.id, it.exp);
      const bytes = S.images.get(`bytes:${it.id}`) || (await D.cachedImage(S.me, it.id));
      const { text, meta } = await C.openFromImage(bytes, S.keys, sender.signPub);
      if (meta.sender !== email) throw new Error("The signed sender doesn't match who the server says sent it.");
      const seenKey = `seen:${S.me}:${meta.msg_id}`;
      const seen = await store.get(seenKey);
      if (seen && seen !== it.id) throw new Error("Replay detected: this exact message was already delivered to you.");
      await store.set(seenKey, it.id);
      S.fresh?.delete(it.id);
      show(text, `Signed by ${email} · decrypted on this phone · ${timeLeft(+it.exp)}`);
    } catch (e) { show(friendly(e), "Tap outside to close", true); }
  })();
}

function closeReveal() {
  S.reveal = null;
  S.refs.chat?.classList.remove("revealing");
  S.refs.revealLayer?.remove();
  fillThread();
}

async function deleteChat(email) {
  const ok = await modal({ title: `Delete chat with ${nameOf(email)}?`, body: h("p", { class: "body" }, "Pictures they sent you are deleted from the server, and your sent pictures are removed from this phone. Pictures you already sent stay in their chat until they vanish."),
    actions: [{ label: "Delete chat", value: true, kind: "warning" }, { label: "Cancel", value: false, kind: "secondary-btn" }] });
  if (!ok) return;
  try {
    const ids = S.inbox.filter((m) => m.sender_email === email).map((m) => m.id);
    await api.clearChats(email);
    await D.clearLocalChats(S.me, email, ids);
    S.inbox = S.inbox.filter((m) => m.sender_email !== email);
    S.sent = S.sent.filter((m) => m.to !== email);
    delete S.pending[email];
    nav({ name: "chats" }, { replace: true });
    toast("Chat deleted.");
  } catch (e) { toast(friendly(e)); }
}

// ── new chat ──────────────────────────────────────────────
function newChatView() {
  const st = (S.newChat ??= {});
  const input = h("input", { class: `input${st.error ? " error" : ""}`, id: "to", type: "email", inputmode: "email", autocomplete: "off", spellcheck: "false", value: st.email || "" });
  const known = [...S.contacts.values()].sort((a, b) => (a.name || a.email).localeCompare(b.name || b.email));
  return h("div", { class: "app" }, header("New chat", { back: true }),
    h("main", { class: "container", id: "main" },
      errorSummary(st.error && [[st.error, "to"]]),
      h("form", { novalidate: true, onsubmit: async (e) => {
        e.preventDefault();
        const email = input.value.trim().toLowerCase();
        if (email === S.me) { Object.assign(st, { email, error: "You can't start a chat with yourself" }); return render(); }
        if (!validEmail(email)) { Object.assign(st, { email, error: "Enter an email address in the correct format, like name@example.com" }); return render(); }
        Object.assign(st, { email, busy: true, error: null }); render();
        try {
          await contactKeys(email);
          S.newChat = null;
          nav({ name: "chat", email }, { replace: true });
        } catch (err) {
          Object.assign(st, { busy: false, error: err.status === 404 ? `${email} isn't on Chisel yet. Ask them to sign up first.` : friendly(err) });
          render();
        }
      } },
        h("div", { class: `form-group${st.error ? " error" : ""}` },
          h("label", { class: "label", for: "to" }, "Their email address"),
          h("span", { class: "hint" }, "They need to have signed up to Chisel."),
          fieldError(st.error), input),
        h("button", { class: "btn", type: "submit", disabled: st.busy || null }, st.busy ? "Checking…" : "Start chat")),
      known.length ? [h("h2", { class: "h-m" }, "People you've talked to"),
        h("ul", { class: "chat-list" }, known.map((c) => h("li", {},
          h("button", { class: "chat-row", type: "button", onclick: () => { S.newChat = null; nav({ name: "chat", email: c.email }, { replace: true }); } },
            avatar(c.name || c.email, c.email), h("span", { class: "meta" }, h("span", { class: "name" }, c.name || c.email), h("span", { class: "last" }, c.email))))))] : null));
}

// ── info ──────────────────────────────────────────────────
function infoView() {
  const term = (t, d) => h("details", { class: "details" }, h("summary", {}, t), h("div", { class: "details-text" }, d));
  const dev = (name, user) => h("div", { class: "dev-card" }, avatar(name, user),
    h("div", {}, h("p", { class: "h-s" }, name), h("a", { href: `https://github.com/${user}`, target: "_blank", rel: "noopener noreferrer" }, `github.com/${user}`)));
  return h("div", { class: "app" }, header("About Chisel"),
    h("main", { class: "container page-pad", id: "main" },
      h("h1", { class: "h-xl" }, "Chisel", h("span", { class: "caption" }, "Secret messages, hidden in plain sight.")),
      h("p", { class: "body-l" }, "Chisel lets you send a private message that travels inside an ordinary-looking picture. Anyone who sees the picture just sees a painting. Only the person you sent it to can find and read the words inside."),

      h("h2", { class: "h-l" }, "How it works"),
      h("ol", { class: "steps" },
        h("li", {}, h("h3", {}, "You write a message"), h("p", { class: "body" }, "Type it like in any chat app.")),
        h("li", {}, h("h3", {}, "Your phone locks it"), h("p", { class: "body" }, "It's scrambled with a key that only your friend's phone can undo, and signed so they know it's really from you. This happens on your phone, so the server never sees your words.")),
        h("li", {}, h("h3", {}, "It's hidden in a picture"), h("p", { class: "body" }, "The server gives your phone a fresh AI-painted picture. Your phone tucks the locked message into tiny colour changes scattered across it, far too small to see.")),
        h("li", {}, h("h3", {}, "Your friend taps to read"), h("p", { class: "body" }, "Their phone finds the hidden bits with its own key, checks your signature and unlocks the message.")),
        h("li", {}, h("h3", {}, "It disappears"), h("p", { class: "body" }, "Pictures are deleted after 24 hours, and every phone replaces its key each day, so old messages can never be unlocked again."))),

      h("h2", { class: "h-l" }, "What keeps you safe"),
      h("ul", { class: "body" },
        h("li", {}, "Only your friend's phone can unlock your messages. Not us, not the server."),
        h("li", {}, "If anyone changes even one dot of the picture, the message is rejected."),
        h("li", {}, "If someone tries to swap a friend's keys, Chisel warns you and shows a safety number to check."),
        h("li", {}, "No passwords: you sign in with a code sent to your email.")),

      h("h2", { class: "h-l" }, "Words explained"),
      term("Encryption", "Scrambling a message so it looks like random noise to everyone except the person with the right key."),
      term("Steganography", "Hiding a message inside something innocent, here a picture, so nobody even knows a message is there."),
      term("Safety number", "A 30-digit number made from someone's key. If your screen and your friend's show the same number for each other, nobody is secretly in the middle."),
      term("End-to-end", "Only the two ends of the conversation, your phone and your friend's, can read the message. Everything in between just carries a locked box."),
      term("Cryptographic erasure", "Each phone throws away yesterday's key. Without it, yesterday's messages can never be unlocked, even by someone who copied them."),

      h("h2", { class: "h-l" }, "Under the hood"),
      h("div", { class: "inset" },
        h("p", { class: "body" }, "X25519 key agreement → HKDF-SHA256 → AES-256-GCM encryption, signed with Ed25519. The message is hidden by keyed, scattered ±1 changes to 512×512 PNG pixels, at positions only the receiver can compute."),
        h("p", { class: "body" }, "Pictures are generated on the server with Pollinations.ai. Server: FastAPI on Render, Postgres on Neon, email codes by Brevo.")),
      h("p", { class: "body" }, h("b", {}, "Chisel"), " stands for ", h("b", {}, "C"), "ryptographic ", h("b", {}, "H"), "ybrid ", h("b", {}, "I"), "mage-", h("b", {}, "S"), "teganographic ", h("b", {}, "E"), "phemeral ", h("b", {}, "L"), "ayer."),

      h("h2", { class: "h-l" }, "Made by"),
      h("div", { class: "dev-cards" }, dev("Divyansh K Verma", "DivyanshKVerma"), dev("Saatwika Saini", "SaatwikaSaini")),
      h("p", { class: "small secondary" }, `Version ${APP_VERSION}`)),
    tabbar("info"));
}

// ── settings ──────────────────────────────────────────────
function settingsView() {
  const pref = themePref();
  const radio = (value, label) => h("label", { class: "radio" },
    h("input", { type: "radio", name: "theme", value, checked: pref === value || null,
      onchange: () => { try { localStorage.setItem("chisel-theme", value); } catch {} applyTheme(value); } }),
    h("span", {}, label));
  const row = (k, v, action) => h("div", { class: "row" }, h("dt", {}, k), h("dd", {}, v), action ? h("dd", { class: "action" }, action) : null);
  const pinsSection = h("div", {});
  store.entries(`pin:${S.me}:`).then((rows) => {
    pinsSection.replaceChildren(rows.length
      ? h("details", { class: "details" }, h("summary", {}, `Verified contacts (${rows.length})`),
          h("div", { class: "details-text" }, rows.map(([email, pub]) => h("div", { class: "form-group" },
            h("p", { class: "h-s" }, nameOf(email)), h("span", { class: "caption" }, email), h("p", { class: "safety" }, C.fingerprint(pub))))))
      : h("p", { class: "body secondary" }, "Contacts you message will appear here with their safety numbers."));
  });
  const age = Date.now() - S.keys.encCreatedAt;
  return h("div", { class: "app" }, header("Settings"),
    h("main", { class: "container page-pad", id: "main" },
      h("h1", { class: "visually-hidden" }, "Settings"),
      h("h2", { class: "h-l" }, "Your account"),
      h("dl", { class: "summary" },
        row("Name", S.name || "Not set", h("a", { href: "#", onclick: (e) => { e.preventDefault(); nav({ name: "name" }); } }, "Change", h("span", { class: "visually-hidden" }, " name"))),
        row("Email", S.me),
        row("Daily key", `Made ${Math.max(0, Math.floor(age / 3600000))} h ago · renews in ${Math.max(0, Math.ceil((DAY - age) / 3600000))} h`)),
      h("h3", { class: "h-m" }, "Your safety number"),
      h("p", { class: "safety" }, C.fingerprint(S.keys.signPub)),
      h("p", { class: "body secondary" }, "Compare this with a friend's screen in person. If it matches, nobody is in the middle."),

      h("hr", { class: "section-break" }),
      h("h2", { class: "h-l" }, "Appearance"),
      h("fieldset", { class: "form-group radios" },
        h("legend", { class: "label" }, "Theme"),
        radio("system", "System default"), radio("light", "Light"), radio("dark", "Dark")),

      h("hr", { class: "section-break" }),
      h("h2", { class: "h-l" }, "Privacy and security"),
      pinsSection,
      h("button", { class: "btn secondary-btn", type: "button", onclick: async () => {
        const ok = await modal({ title: "Renew your daily key now?", body: h("p", { class: "body" }, "Pictures already sent to you that you haven't opened will become unreadable. That's how Chisel erases old messages."),
          actions: [{ label: "Renew key", value: true }, { label: "Cancel", value: false, kind: "secondary-btn" }] });
        if (!ok) return;
        try { S.keys = await maybeRotate(S.keys, true); toast("New daily key in place."); render(); } catch (e) { toast(friendly(e)); }
      } }, "Renew daily key now"),

      h("hr", { class: "section-break" }),
      h("h2", { class: "h-l" }, "Chats"),
      h("p", { class: "body" }, "Delete every picture sent to you from the server, and everything Chisel stored on this phone for your chats."),
      h("button", { class: "btn warning", type: "button", onclick: async () => {
        const ok = await modal({ title: "Delete all chats?", body: h("p", { class: "body" }, "This can't be undone. Pictures you've already sent stay with the people you sent them to until they vanish."),
          actions: [{ label: "Delete all chats", value: true, kind: "warning" }, { label: "Cancel", value: false, kind: "secondary-btn" }] });
        if (!ok) return;
        try { await api.clearChats(); await D.clearLocalChats(S.me); Object.assign(S, { inbox: [], sent: [], pending: {} }); toast("All chats deleted."); }
        catch (e) { toast(friendly(e)); }
      } }, "Delete all chats"),

      h("hr", { class: "section-break" }),
      h("h2", { class: "h-l" }, "Sign out"),
      h("div", { class: "btn-group" },
        h("button", { class: "btn secondary-btn", type: "button", onclick: () => signOut("Signed out. Your keys stay on this phone.") }, "Sign out"),
        h("button", { class: "btn warning", type: "button", onclick: async () => {
          const ok = await modal({ title: "Remove your keys from this phone?", body: h("p", { class: "body" }, "You won't be able to read any picture sent to you here. Signing in again creates new keys and changes your safety number."),
            actions: [{ label: "Remove keys", value: true, kind: "warning" }, { label: "Cancel", value: false, kind: "secondary-btn" }] });
          if (!ok) return;
          await D.wipeUser(S.me);
          signOut("Keys removed from this phone.");
        } }, "Remove keys from this phone")),
      h("p", { class: "body" }, h("a", { href: "#", onclick: (e) => { e.preventDefault(); startDeleteAccount(); } }, "Delete my account")),

      h("hr", { class: "section-break" }),
      h("p", { class: "small secondary" }, `Chisel ${APP_VERSION}${API_BASE ? ` · ${API_BASE.replace("https://", "")}` : ""}`)),
    tabbar("settings"));
}

function nameView() {
  const st = (S.nameEdit ??= { value: S.name || "" });
  const input = h("input", { class: `input${st.error ? " error" : ""}`, id: "name", maxlength: "40", autocomplete: "nickname", value: st.value });
  return h("div", { class: "app" }, header("Your name", { back: true }),
    h("main", { class: "container", id: "main" },
      errorSummary(st.error && [[st.error, "name"]]),
      h("form", { novalidate: true, onsubmit: async (e) => {
        e.preventDefault();
        st.value = input.value.trim();
        if (!st.value) { st.error = "Enter a name"; return render(); }
        try { const r = await api.setName(st.value); S.name = r.display_name; S.nameEdit = null; toast("Name updated."); goBack(); }
        catch (err) { st.error = friendly(err); render(); }
      } },
        h("div", { class: `form-group${st.error ? " error" : ""}` },
          h("label", { class: "label", for: "name" }, "What should people call you?"),
          h("span", { class: "hint" }, "Shown to people you send pictures to, with your email address."),
          fieldError(st.error), input),
        h("button", { class: "btn", type: "submit" }, "Save"))));
}

async function startDeleteAccount() {
  const ok = await modal({ title: "Delete your account?", body: h("div", {},
      h("div", { class: "warning-text" }, h("span", { class: "bang", "aria-hidden": "true" }, "!"), h("span", {}, "This deletes your name, keys and every picture you've sent or received. It can't be undone.")),
      h("p", { class: "body" }, "To confirm it's you, we'll email you a code.")),
    actions: [{ label: "Email me a code", value: true, kind: "warning" }, { label: "Cancel", value: false, kind: "secondary-btn" }] });
  if (!ok) return;
  try { const r = await api.register(S.me); S.deleteAcct = { devCode: r.otp_for_demo || null }; nav({ name: "delete-account" }); }
  catch (e) { toast(friendly(e)); }
}

function deleteAccountView() {
  const st = (S.deleteAcct ??= {});
  const code = h("input", { class: `input code${st.error ? " error" : ""}`, id: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6", value: st.devCode || "" });
  return h("div", { class: "app" }, header("Delete account", { back: true }),
    h("main", { class: "container", id: "main" },
      errorSummary(st.error && [[st.error, "code"]]),
      h("h1", { class: "h-xl" }, "Confirm with your code"),
      h("div", { class: "inset" }, "We've sent a code to ", h("b", {}, S.me), "."),
      st.devCode ? h("div", { class: "banner" }, h("p", { class: "banner-title" }, "Demo server"), h("div", { class: "banner-body" }, "Your code is ", h("b", {}, st.devCode), ".")) : null,
      h("form", { novalidate: true, onsubmit: async (e) => {
        e.preventDefault();
        try {
          const r = await api.verify(S.me, code.value.trim());
          setToken(r.token);
          await api.deleteAccount();
          await D.wipeUser(S.me);
          S.deleteAcct = null;
          signOut("Your account has been deleted.");
        } catch (err) { st.error = friendly(err); render(); }
      } },
        h("div", { class: `form-group${st.error ? " error" : ""}` },
          h("label", { class: "label", for: "code" }, "Code"), fieldError(st.error), code),
        h("button", { class: "btn warning", type: "submit" }, "Delete my account"))));
}

// ── start ─────────────────────────────────────────────────
async function start() {
  const sess = await store.get("session");
  const keys = sess && (await store.get(`keys:${sess.email}`));
  if (!sess || !keys) return render();
  setToken(sess.token);
  Object.assign(S, { me: sess.email, keys });
  await loadLocal();
  S.route = history.state?.name ? history.state : { name: "chats" };
  history.replaceState(S.route, "");
  render();
  try {
    const me = await api.me();
    S.name = me.display_name;
    S.keys = await maybeRotate(keys);
  } catch (e) { if (e.status !== 401) toast(friendly(e)); }
  refresh();
}

document.addEventListener("visibilitychange", () => { if (!document.hidden && S.me) refresh(); });
setInterval(() => { if (!document.hidden && S.me && (S.route.name === "chats" || S.route.name === "chat")) refresh(); }, 15000);
if (!window.CHISEL_UNSUPPORTED) {
  if ("serviceWorker" in navigator && !window.Capacitor) navigator.serviceWorker.register("sw.js").catch(() => {});
  start();
}
