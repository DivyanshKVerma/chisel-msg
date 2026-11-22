// New-message notifications (v1.1).
// A notification only says WHO sent a picture. The message itself stays locked
// inside the picture until you tap it in the app, so nothing secret reaches the
// notification shade.
//
//   Android app: @capacitor/local-notifications while CHISEL is open or in the
//                background, plus @capacitor/background-runner (runners/inbox.js),
//                which checks the inbox about every 15 minutes when it's closed.
//   Browser:     the Notification API while the tab is open in the background.
const Cap = window.Capacitor;
const native = !!Cap?.isNativePlatform?.();
const LN = () => Cap?.Plugins?.LocalNotifications;
const BR = () => Cap?.Plugins?.CapacitorBackgroundRunner; // native plugin name
const RUNNER = "com.chisel.messenger.inbox";
const PREF = "chisel-notify";

/** Same notification id for the same chat, so a new picture updates it instead of stacking. */
export function notificationId(email) {
  let x = 0;
  for (const c of email) x = (x * 31 + c.charCodeAt(0)) | 0;
  return (Math.abs(x) % 2000000000) + 1;
}

// Android's WebView keeps document.hidden false while the app is in the
// background, so track Capacitor's app state as well.
let appActive = true;
Cap?.Plugins?.App?.addListener?.("appStateChange", (st) => { appActive = !!st.isActive; });
/** True when nobody is looking at CHISEL (tab hidden, or the Android app in the background). */
export const inBackground = () => document.hidden || !appActive;

export const supported = () => (native ? !!LN() : "Notification" in window);
export const wanted = () => { try { return localStorage.getItem(PREF) !== "off"; } catch { return true; } };

/** "granted" | "denied" | "prompt" | "unsupported" */
export async function permission() {
  if (!supported()) return "unsupported";
  if (native) {
    try { const p = (await LN().checkPermissions()).display; return p === "granted" || p === "denied" ? p : "prompt"; }
    catch { return "prompt"; }
  }
  return Notification.permission === "default" ? "prompt" : Notification.permission;
}

export async function requestPermission() {
  if (!supported()) return "unsupported";
  try {
    if (native) await LN().requestPermissions();
    else await Notification.requestPermission();
  } catch {}
  return permission();
}

export async function setWanted(on) {
  try { localStorage.setItem(PREF, on ? "on" : "off"); } catch {}
  syncRunner({ notify: on ? "on" : "off" });
  if (on) return requestPermission();
  return permission();
}

let openChat = () => {};
/** Called with the sender's email when a notification is tapped. */
export function onOpen(fn) {
  openChat = fn;
  if (native && LN()) {
    LN().addListener?.("localNotificationActionPerformed", (a) => {
      const email = a?.notification?.extra?.email;
      if (email) openChat(email);
    });
  }
}

const cursorKey = (me) => `chisel-notify-cursor:${me}`;
const getCursor = (me) => { try { const v = localStorage.getItem(cursorKey(me)); return v ? Number(v) : null; } catch { return null; } };
const setCursor = (me, v) => { try { localStorage.setItem(cursorKey(me), String(v)); } catch {} };

/** Tell the background runner who is signed in and how far notifications have got. */
export function syncRunner(details) {
  if (!native || !BR()) return;
  BR().dispatchEvent({ label: RUNNER, event: "sync", details }).catch(() => {});
}

export function signedIn(me, token, apiBase) {
  syncRunner({ me, token, api: apiBase, notify: wanted() ? "on" : "off", cursor: String(getCursor(me) || Date.now()) });
}
export function signedOut() { syncRunner({ clear: true }); }

/**
 * After each inbox refresh: notify about pictures that arrived since the last
 * check, if the app is in the background. `nameOf(email)` gives display names.
 * Returns the list of new pictures (for an in-app hint when the app is open).
 */
export async function inboxChanged(me, inbox, { read, nameOf, hidden }) {
  const newest = inbox.reduce((t, m) => Math.max(t, +m.at), 0);
  const cursor = getCursor(me);
  if (cursor == null) { setCursor(me, newest || Date.now()); syncRunner({ cursor: String(newest || Date.now()) }); return []; }
  const fresh = inbox.filter((m) => +m.at > cursor && !read.has(m.id));
  if (newest > cursor) { setCursor(me, newest); syncRunner({ cursor: String(newest) }); }
  if (!fresh.length || !hidden || !wanted() || (await permission()) !== "granted") return fresh;

  const bySender = new Map();
  for (const m of fresh) bySender.set(m.sender_email, (bySender.get(m.sender_email) || 0) + 1);
  for (const [email, n] of bySender) {
    const title = nameOf(email);
    const body = n === 1 ? "Sent you a picture. Tap to read the hidden message." : `Sent you ${n} pictures. Tap to read the hidden messages.`;
    try {
      if (native) {
        await LN().schedule({ notifications: [{ id: notificationId(email), title, body, extra: { email }, smallIcon: "ic_stat_chisel", iconColor: "#1D70B8", group: "chisel-messages" }] });
      } else {
        const n2 = new Notification(title, { body, tag: email, icon: "icons/icon-192.png" });
        n2.onclick = () => { window.focus(); openChat(email); n2.close(); };
      }
    } catch {}
  }
  return fresh;
}

/** Clear a chat's notification once you open it. */
export function clearFor(email) {
  if (native && LN()) LN().cancel?.({ notifications: [{ id: notificationId(email) }] }).catch?.(() => {});
}
