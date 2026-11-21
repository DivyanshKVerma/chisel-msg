// On-device storage (IndexedDB). Private keys live ONLY here — never sent anywhere.
//   keys:<email>              → device keys (Uint8Arrays)
//   pin:<me>:<contact>        → contact's pinned identity key (trust on first use)
//   seen:<me>:<aad msg_id>    → server message id it was opened from (replay check)
//   session                   → { email, token }
const DB = "chisel";
const STORE = "kv";

let dbp;
function db() {
  dbp ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbp;
}

async function tx(mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const t = d.transaction(STORE, mode);
    const req = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(req?.result);
    t.onerror = () => reject(t.error);
  });
}

export const get = (k) => tx("readonly", (s) => s.get(k));
export const set = (k, v) => tx("readwrite", (s) => s.put(v, k));
export const del = (k) => tx("readwrite", (s) => s.delete(k));

export async function entries(prefix) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const out = [];
    const range = IDBKeyRange.bound(prefix, prefix + "￿");
    const req = d.transaction(STORE).objectStore(STORE).openCursor(range);
    req.onsuccess = () => {
      const c = req.result;
      if (!c) return resolve(out);
      out.push([c.key.slice(prefix.length), c.value]);
      c.continue();
    };
    req.onerror = () => reject(req.error);
  });
}

/** Pin store for loadVerifiedContact, scoped to the signed-in user. */
export const pinsFor = (me) => ({
  get: (contact) => get(`pin:${me}:${contact.toLowerCase()}`),
  set: (contact, pub) => set(`pin:${me}:${contact.toLowerCase()}`, pub),
});
