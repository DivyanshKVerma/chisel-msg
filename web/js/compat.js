// Runs before the app (plain ES5, no modules). If this phone's WebView is too
// old for Chisel's cryptography, explain how to fix it instead of a blank screen.
(function () {
  var ok = typeof BigInt === "function" && window.crypto && crypto.getRandomValues &&
    window.indexedDB && window.Promise && window.fetch && window.TextEncoder && window.Uint8Array;
  if (ok) return;
  window.CHISEL_UNSUPPORTED = true;
  document.addEventListener("DOMContentLoaded", function () {
    var el = document.getElementById("app");
    if (!el) return;
    el.innerHTML = "";
    var box = document.createElement("div");
    box.style.cssText = "font:18px/1.4 Arial,sans-serif;padding:24px;color:#0b0c0c;background:#fff;min-height:100vh";
    var h = document.createElement("h1"); h.textContent = "Please update Android System WebView";
    h.style.cssText = "font-size:28px;margin:0 0 16px";
    var p = document.createElement("p");
    p.textContent = "Chisel needs a newer version of Android System WebView to encrypt your messages. Open the Play Store, search for “Android System WebView”, tap Update, then open Chisel again.";
    box.appendChild(h); box.appendChild(p); el.appendChild(box);
  });
})();
