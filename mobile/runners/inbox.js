// CHISEL background inbox check (Android, @capacitor/background-runner).
// Runs about every 15 minutes while the app is closed, in a small separate
// JavaScript engine. It only reads inbox metadata (who sent a picture, when);
// it has no keys and never decrypts anything. Notifications say who sent a
// picture, never what it says.
//
// Stored with CapacitorKV (app-private SharedPreferences, excluded from backups):
//   api, token, me   the signed-in session (sent by the app on sign-in)
//   cursor           newest picture time (ms) already notified or seen in the app
//   notify           "on" | "off" (Settings → Notifications)

function kv(key) {
  const v = CapacitorKV.get(key);
  if (typeof v === "string") return v || null;
  return v && v.value ? v.value : null;
}

// Same id scheme as web/js/notify.js, so the app and this runner update one
// notification per chat instead of stacking duplicates.
function notificationId(email) {
  let x = 0;
  for (let i = 0; i < email.length; i++) x = (x * 31 + email.charCodeAt(i)) | 0;
  return (Math.abs(x) % 2000000000) + 1;
}

addEventListener("sync", (resolve, reject, args) => {
  try {
    const keys = ["api", "token", "me", "cursor", "notify"];
    if (args && args.clear) {
      for (const k of keys) CapacitorKV.remove(k);
    } else if (args) {
      for (const k of keys) if (args[k] != null) CapacitorKV.set(k, String(args[k]));
    }
    resolve();
  } catch (err) {
    reject(err);
  }
});

addEventListener("checkInbox", async (resolve, reject) => {
  try {
    const api = kv("api");
    const token = kv("token");
    if (!api || !token || kv("notify") === "off") return resolve();

    const res = await fetch(api + "/api/messages/inbox", { method: "GET", headers: { Authorization: "Bearer " + token } });
    if (!res.ok) return resolve(); // signed out or token expired: the app will sign in again
    const data = await res.json();
    const cursor = Number(kv("cursor") || 0);
    let newest = cursor;
    const bySender = {};
    const names = {};
    for (const m of data.messages || []) {
      const at = Date.parse(m.created_at);
      if (at > newest) newest = at;
      if (at <= cursor) continue;
      bySender[m.sender_email] = (bySender[m.sender_email] || 0) + 1;
      names[m.sender_email] = m.sender_display_name || m.sender_email;
    }
    const list = Object.keys(bySender).map((email) => ({
      id: notificationId(email),
      title: names[email],
      body: bySender[email] === 1
        ? "Sent you a picture. Tap to read the hidden message."
        : "Sent you " + bySender[email] + " pictures. Tap to read the hidden messages.",
      scheduleAt: new Date(Date.now() + 1000),
      smallIcon: "ic_stat_chisel",
    }));
    if (list.length) CapacitorNotifications.schedule(list);
    if (newest > cursor) CapacitorKV.set("cursor", String(newest));
    resolve();
  } catch (err) {
    reject(err);
  }
});
