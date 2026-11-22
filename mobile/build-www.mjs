// Copies ../web into ./www for the Android app and points it at the API.
// Override the server for testing: CHISEL_API_BASE=http://localhost:8000 npm run www
import { cp, rm, readFile, writeFile } from "node:fs/promises";
import { build } from "esbuild";

const API_BASE = process.env.CHISEL_API_BASE || "https://chisel-api-1mkl.onrender.com";
await rm("www", { recursive: true, force: true });
await cp("../web", "www", {
  recursive: true,
  // The service worker and the icon/wordmark sources aren't needed inside the APK
  filter: (src) => !/(\/sw\.js|chisel-icon(-source)?\.(svg|png)|chisel-wordmark\.(svg|png)|android-foreground-1024\.png)$/.test(src),
});
// Background inbox check for notifications while the app is closed
await cp("runners", "www/runners", { recursive: true });
const cfg = "www/js/config.js";
const text = (await readFile(cfg, "utf8")).replace(/export const API_BASE = ".*?";/, `export const API_BASE = ${JSON.stringify(API_BASE)};`);
await writeFile(cfg, text);
// Compile the app (ES modules, modern syntax) into one classic script for
// older Android WebViews: Chrome 67+ is the floor (the crypto needs BigInt).
await build({
  entryPoints: ["www/js/app.js"], bundle: true, format: "iife", target: ["chrome67"],
  minify: true, legalComments: "inline", outfile: "www/js/app.bundle.js",
});
for (const f of ["app.js", "api.js", "chisel.js", "config.js", "data.js", "notify.js", "png.js", "store.js", "ui.js"]) await rm(`www/js/${f}`);
await rm("www/vendor", { recursive: true });
const html = "www/index.html";
await writeFile(html, (await readFile(html, "utf8")).replace('<script type="module" src="js/app.js"></script>', '<script src="js/app.bundle.js" defer></script>'));

if (API_BASE !== "https://chisel-api-1mkl.onrender.com") {
  // Test builds talking to a local server: allow that origin in the page CSP
  const idx = "www/index.html";
  await writeFile(idx, (await readFile(idx, "utf8")).replace("connect-src 'self'", `connect-src 'self' ${new URL(API_BASE).origin}`));
}
console.log(`www/ ready → API ${API_BASE}`);
