"""
CHISEL — Python ↔ JavaScript compatibility test
================================================
The phone app (web/js/chisel.js) must be byte-compatible with chisel_core.py.
Python seals a message that JS must open; JS seals one that Python must open;
both sides must agree on fingerprints, signatures, pixel positions and PNG
pixels. Needs Node.js (run `npm install` in web-src/ once).
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from cryptography.hazmat.primitives import serialization
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chisel_core as cc

HERE = os.path.dirname(os.path.abspath(__file__))
results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(f"  {'✅ PASS' if ok else '❌ FAIL'}  {label}" + (f"  — {detail}" if detail and not ok else ""))


def priv_hex(k):
    return k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                           serialization.NoEncryption()).hex()


def export(u: cc.UserKeys):
    return {"email": u.user_id, "sign_priv": priv_hex(u.sign_priv), "sign_pub": u.ed25519_pub_bytes().hex(),
            "enc_priv": priv_hex(u.enc_priv), "enc_pub": u.x25519_pub_bytes().hex()}


def main():
    t0 = time.perf_counter()
    if not shutil.which("node"):
        print("Node.js not found — install it to run this test.")
        return False
    d = tempfile.mkdtemp(prefix="chisel_interop_")
    alice, bob = cc.UserKeys("alice@example.com"), cc.UserKeys("bob@example.com")
    # A real AI cover if available, else the generated gradient
    cover = next((p for p in ("docs/images/cover.png", "cover_512.png") if os.path.exists(p)), None)
    shutil.copy(cover, f"{d}/cover.png")

    msg = "Hi Bob — sent from Python, opened in the phone app. ✓ ünïcödé"
    reply = "Hi Alice — sealed in JavaScript, opened in Python. ✓ ünïcödé"
    py_stats = cc.seal_into_image(msg, alice, bob.user_id, bob.enc_pub, f"{d}/cover.png", f"{d}/py_to_js.png")
    json.dump({"alice": export(alice), "bob": export(bob), "reply_text": reply,
               "alice_payload_from_python": alice.key_upload_payload()}, open(f"{d}/keys.json", "w"))

    r = subprocess.run(["node", os.path.join(HERE, "web-src", "interop.mjs"), d], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr)
        check("JS side ran", False, r.stderr.strip().splitlines()[-1] if r.stderr else "")
        return False
    js = json.loads(r.stdout.strip().splitlines()[-1])

    print("\n── Keys ─────────────────────────────────────────────────")
    check("fingerprints identical (Alice)", js["fp_alice"] == cc.fingerprint(alice.ed25519_pub_bytes()))
    check("fingerprints identical (Bob)", js["fp_bob"] == cc.fingerprint(bob.ed25519_pub_bytes()))
    check("Python-signed key verifies in JS", js["python_prekey_verified_in_js"])
    entry = {"email": bob.user_id, **js["js_payload_bob"]}
    try:
        x_pub, ed_pub = cc.load_verified_contact(entry, cc.KeyPinStore())
        check("JS-signed key verifies in Python", cc._raw(x_pub) == bob.x25519_pub_bytes())
    except ValueError as e:
        check("JS-signed key verifies in Python", False, str(e))

    print("\n── Python → JS ──────────────────────────────────────────")
    check("JS opens the Python-sealed image", js["js_opened_text"] == msg, js.get("js_opened_text"))
    check("signed metadata matches", js["js_opened_meta"]["sender"] == alice.user_id
          and js["js_opened_meta"]["receiver"] == bob.user_id)
    py_pos = cc.payload_positions(f"{d}/py_to_js.png", bob)
    jp = js["js_positions_of_py_image"]
    check("JS computes exactly the same pixel positions", py_pos == jp["header"] + jp["body"],
          f"{len(py_pos)} vs {len(jp['header']) + len(jp['body'])}")
    check("wrong receiver can't locate it in JS either", "No CHISEL message" in js["wrong_receiver"], js["wrong_receiver"])

    print("\n── JS → Python ──────────────────────────────────────────")
    text, meta = cc.open_from_image(f"{d}/js_to_py.png", alice, bob.sign_pub)
    check("Python opens the JS-sealed image", text == reply, text)
    check("JS-made PNG is a valid 512×512 RGB PNG for the server",
          Image.open(f"{d}/js_to_py.png").format == "PNG" and Image.open(f"{d}/js_to_py.png").size == (512, 512))
    check("Python finds the same positions JS used",
          cc.payload_positions(f"{d}/js_to_py.png", alice) == js["js_positions_of_js_image"]["header"] + js["js_positions_of_js_image"]["body"])
    cov = Image.open(f"{d}/cover.png").convert("RGB").tobytes()
    out = Image.open(f"{d}/js_to_py.png").convert("RGB").tobytes()
    deltas = {out[i] - cov[i] for i in range(len(cov)) if out[i] != cov[i]}
    rows = {i // (512 * 3) for i in range(len(cov)) if out[i] != cov[i]}
    check("JS changes are ±1 only and spread out (≥300 rows)", deltas <= {1, -1} and len(rows) >= 300,
          f"deltas={deltas}, rows={len(rows)}")
    text2, _ = cc.verify_and_decrypt(bytes.fromhex(js["js_bundle_hex"]), alice, bob.sign_pub)
    check("JS bundle decrypts in Python (no image)", text2 == "bundle-level check")

    print("\n── PNG codec ────────────────────────────────────────────")
    check("JS decodes the PIL-made cover to identical pixels",
          js["cover_pixel_sha"] == hashlib.sha256(cov).hexdigest())

    passed = sum(results)
    print(f"\n  JS seal {js['seal_ms']} ms, JS open {js['open_ms']} ms (Node); Python seal payload {py_stats['payload_bytes']} B")
    print(f"  {passed}/{len(results)} passed in {(time.perf_counter() - t0) * 1000:.0f} ms")
    shutil.rmtree(d, ignore_errors=True)
    return passed == len(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
