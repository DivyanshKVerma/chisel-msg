// JS half of test_interop.py. Usage: node interop.mjs <workdir>
// Reads keys + a Python-made stego PNG, opens it, and writes JS-made artefacts
// for Python to open. Prints one JSON line of results.
import { readFile, writeFile } from "node:fs/promises";
import * as C from "../web/js/chisel.js";
import { decodePNG } from "../web/js/png.js";

const dir = process.argv[2];
const j = JSON.parse(await readFile(`${dir}/keys.json`, "utf8"));
const keys = (k) => ({
  email: k.email,
  signPriv: C.fromHex(k.sign_priv), signPub: C.fromHex(k.sign_pub),
  encPriv: C.fromHex(k.enc_priv), encPub: C.fromHex(k.enc_pub),
});
const alice = keys(j.alice), bob = keys(j.bob);
const out = {};

// Fingerprints and signed prekeys agree with Python
out.fp_alice = C.fingerprint(alice.signPub);
out.fp_bob = C.fingerprint(bob.signPub);
const fakePins = { m: new Map(), get(e) { return this.m.get(e); }, set(e, v) { this.m.set(e, v); } };
await C.loadVerifiedContact({ email: alice.email, ...j.alice_payload_from_python }, fakePins);
out.python_prekey_verified_in_js = true;
out.js_payload_bob = C.keyUploadPayload(bob);

// Open the Python-sealed image as Bob
const py = await readFile(`${dir}/py_to_js.png`);
const t0 = performance.now();
const opened = await C.openFromImage(py, bob, alice.signPub);
out.open_ms = Math.round(performance.now() - t0);
out.js_opened_text = opened.text;
out.js_opened_meta = opened.meta;
out.js_positions_of_py_image = await C.payloadPositions(py, bob);

// Wrong receiver can't locate
try { await C.openFromImage(py, alice, alice.signPub); out.wrong_receiver = "OPENED"; }
catch (e) { out.wrong_receiver = e.message; }

// Seal a reply Bob → Alice on the same cover Python used
const cover = await readFile(`${dir}/cover.png`);
const t1 = performance.now();
const sealed = await C.sealIntoImage(j.reply_text, bob, alice.email, alice.encPub, cover);
out.seal_ms = Math.round(performance.now() - t1);
out.seal_stats = sealed.stats;
await writeFile(`${dir}/js_to_py.png`, sealed.png);
out.js_positions_of_js_image = await C.payloadPositions(sealed.png, alice);

// PNG codec: JS decode of the Python cover (for pixel comparison)
const dec = await decodePNG(cover);
out.cover_pixel_sha = Buffer.from(await crypto.subtle.digest("SHA-256", dec.rgb)).toString("hex");

// Plain bundle (no image) for Python's verify_and_decrypt
out.js_bundle_hex = C.toHex(C.encryptAndSign("bundle-level check", bob, alice.email, alice.encPub));

console.log(JSON.stringify(out));
