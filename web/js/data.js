// What this phone remembers (IndexedDB), all scoped to the signed-in user:
//   contact:<me>:<email>  → { email, name } (names learned from the server)
//   sent:<me>:<id>        → your own sent picture + its text (deleted after 24 h)
//   img:<me>:<id>         → cached received picture bytes (deleted after 24 h)
//   read:<me>:<id>        → you've opened this chat since the picture arrived
// Pictures you receive stay readable only with your private key; the text you
// SENT is kept here so your side of the conversation can be shown.
import * as store from "./store.js";

const k = (me, kind, id = "") => `${kind}:${me}:${id}`;

export async function contacts(me) {
  return new Map((await store.entries(k(me, "contact"))).map(([email, c]) => [email, c]));
}
export async function rememberContact(me, email, name) {
  email = email.toLowerCase();
  const prev = await store.get(k(me, "contact", email));
  if (!prev || (name && prev.name !== name)) await store.set(k(me, "contact", email), { email, name: name || prev?.name || null });
}

export async function sentMessages(me) {
  const rows = await store.entries(k(me, "sent"));
  const out = [];
  for (const [id, m] of rows) {
    if (m.expiresAt < Date.now()) await store.del(k(me, "sent", id));
    else out.push(m);
  }
  return out;
}
export const saveSent = (me, m) => store.set(k(me, "sent", m.id), m);
export const deleteSent = (me, id) => store.del(k(me, "sent", id));

export async function cachedImage(me, id) {
  const v = await store.get(k(me, "img", id));
  return v?.bytes || null;
}
export const cacheImage = (me, id, bytes, expiresAt) => store.set(k(me, "img", id), { bytes, expiresAt });

export async function purgeExpired(me) {
  for (const [id, v] of await store.entries(k(me, "img"))) if (v.expiresAt < Date.now()) await store.del(k(me, "img", id));
  await sentMessages(me);
}

export async function readSet(me) { return new Set((await store.entries(k(me, "read"))).map(([id]) => id)); }
export const markRead = (me, id) => store.set(k(me, "read", id), 1);

/**
 * Remove what this phone stored for one chat (email + the ids of pictures
 * received in it), or for all chats when email is null.
 */
export async function clearLocalChats(me, email = null, receivedIds = []) {
  const ids = new Set(receivedIds);
  for (const [id, v] of await store.entries(k(me, "sent"))) if (!email || v.to === email) await store.del(k(me, "sent", id));
  for (const kind of ["img", "read"]) {
    for (const [id] of await store.entries(k(me, kind))) if (!email || ids.has(id)) await store.del(k(me, kind, id));
  }
}

/** Wipe every key and record for this user from the phone (sign-out keeps them; this doesn't). */
export async function wipeUser(me) {
  for (const kind of ["sent", "img", "read", "contact", "pin", "seen"]) {
    for (const [id] of await store.entries(k(me, kind))) await store.del(k(me, kind, id));
  }
  await store.del(`keys:${me}`);
}
