"""
CHISEL — Comprehensive Implementation Audit
=============================================
Tests EVERY endpoint, edge case, security boundary, and crypto guarantee.
Reports wall-clock time for each operation.
"""

import io
import os
import sqlite3
import sys
import time

import httpx
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chisel_core
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519 as ed25519_mod
from cryptography.hazmat.primitives.asymmetric import x25519 as x25519_mod

BASE = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@example.com"   # server must be started with ADMIN_EMAILS=admin@example.com
# Same DATABASE_URL the server uses (SQLite locally, Postgres when testing Neon-style)
DB_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./chisel.db")


def db_query(sql: str, params: tuple = ()) -> list:
    """Run a read-only check directly against the server's database."""
    if DB_URL.startswith("sqlite"):
        con = sqlite3.connect(DB_URL.split("///", 1)[1])
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()
    import asyncio
    import asyncpg
    from urllib.parse import parse_qsl, urlsplit
    parts = urlsplit(DB_URL.replace("+asyncpg", ""))
    q = dict(parse_qsl(parts.query))
    dsn = parts._replace(query="").geturl()
    pg_sql = sql
    for i in range(1, sql.count("?") + 1):
        pg_sql = pg_sql.replace("?", f"${i}", 1)

    async def run():
        con = await asyncpg.connect(dsn, ssl=q.get("sslmode") or q.get("ssl"))
        try:
            return [tuple(r) for r in await con.fetch(pg_sql, *params)]
        finally:
            await con.close()
    return asyncio.run(run())
PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []


def timed(label, fn):
    """Run fn(), time it, record pass/fail."""
    t0 = time.perf_counter()
    try:
        result = fn()
        elapsed = (time.perf_counter() - t0) * 1000
        results.append((label, PASS, elapsed, ""))
        print(f"  {PASS}  {elapsed:8.1f} ms  │  {label}")
        return result
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        results.append((label, FAIL, elapsed, str(e)))
        print(f"  {FAIL}  {elapsed:8.1f} ms  │  {label}")
        print(f"              ERROR: {e}")
        return None


def expect_fail(label, fn, expected_status=None):
    """Run fn(), expect it to raise or return an error status. PASS if it fails correctly."""
    t0 = time.perf_counter()
    try:
        result = fn()
        elapsed = (time.perf_counter() - t0) * 1000
        allowed = expected_status if isinstance(expected_status, tuple) else (expected_status,)
        if expected_status and hasattr(result, "status_code") and result.status_code in allowed:
            results.append((label, PASS, elapsed, f"Correctly returned {expected_status}"))
            print(f"  {PASS}  {elapsed:8.1f} ms  │  {label}")
            return result
        else:
            got = getattr(result, "status_code", result)
            results.append((label, FAIL, elapsed, f"Should have been rejected (got {got})"))
            print(f"  {FAIL}  {elapsed:8.1f} ms  │  {label} — Should have been rejected! (got {got})")
            return result
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        results.append((label, PASS, elapsed, f"Correctly rejected: {e}"))
        print(f"  {PASS}  {elapsed:8.1f} ms  │  {label}")
        return None


def main():
    client = httpx.Client(base_url=BASE, timeout=30)

    print("=" * 76)
    print("  CHISEL — COMPREHENSIVE IMPLEMENTATION AUDIT")
    print("  " + time.strftime("%Y-%m-%d %H:%M:%S %Z"))
    print("=" * 76)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION A: HEALTH & SERVER STATUS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── A. SERVER HEALTH ─────────────────────────────────────")

    def a1():
        r = client.get("/api/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok" and d["service"] == "CHISEL"
        return d
    timed("GET /api/health returns 200 + correct payload", a1)

    def a2():
        r = client.get("/api/nonexistent")
        assert r.status_code == 404
    timed("GET /api/nonexistent returns 404", a2)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION B: AUTHENTICATION FLOW
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── B. AUTHENTICATION ────────────────────────────────────")

    # B1: Register Alice
    alice_otp = None
    def b1():
        nonlocal alice_otp
        r = client.post("/api/register", json={"email": "alice@example.com"})
        assert r.status_code == 200
        alice_otp = r.json()["otp_for_demo"]
        assert len(alice_otp) == 6 and alice_otp.isdigit()
    timed("POST /api/register — valid email → 6-digit OTP", b1)

    # B2: Register Bob
    bob_otp = None
    def b2():
        nonlocal bob_otp
        r = client.post("/api/register", json={"email": "bob@example.com"})
        assert r.status_code == 200
        bob_otp = r.json()["otp_for_demo"]
    timed("POST /api/register — second user", b2)

    # B3: Register with invalid email
    def b3():
        r = client.post("/api/register", json={"email": "not-an-email"})
        return r
    expect_fail("POST /api/register — invalid email rejected", b3, expected_status=422)

    # B4: Verify with wrong OTP
    def b4():
        r = client.post("/api/verify-otp", json={"email": "alice@example.com", "code": "000000"})
        return r
    expect_fail("POST /api/verify-otp — wrong OTP rejected", b4, expected_status=400)

    # B5: Verify Alice
    alice_token = None
    alice_uid = None
    def b5():
        nonlocal alice_token, alice_uid
        r = client.post("/api/verify-otp", json={"email": "alice@example.com", "code": alice_otp})
        assert r.status_code == 200
        d = r.json()
        alice_token = d["token"]
        alice_uid = d["user_id"]
        assert len(alice_token) > 50
    timed("POST /api/verify-otp — correct OTP → JWT issued", b5)

    # B6: Reuse same OTP (should fail)
    def b6():
        r = client.post("/api/verify-otp", json={"email": "alice@example.com", "code": alice_otp})
        return r
    expect_fail("POST /api/verify-otp — OTP reuse rejected", b6, expected_status=400)

    # B7: Verify Bob
    bob_token = None
    bob_uid = None
    def b7():
        nonlocal bob_token, bob_uid
        r = client.post("/api/verify-otp", json={"email": "bob@example.com", "code": bob_otp})
        assert r.status_code == 200
        d = r.json()
        bob_token = d["token"]
        bob_uid = d["user_id"]
    timed("POST /api/verify-otp — Bob verified", b7)

    alice_h = {"Authorization": f"Bearer {alice_token}"}
    bob_h = {"Authorization": f"Bearer {bob_token}"}

    # B8: Access protected endpoint without token
    def b8():
        r = client.get("/api/messages/inbox")
        return r
    expect_fail("GET /api/messages/inbox — no token → 401/403", b8, expected_status=(401, 403))

    # B9: Access protected endpoint with garbage token
    def b9():
        r = client.get("/api/messages/inbox", headers={"Authorization": "Bearer garbage.token.here"})
        return r
    expect_fail("GET /api/messages/inbox — garbage token → 401", b9, expected_status=401)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION C: KEY MANAGEMENT
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── C. KEY MANAGEMENT ────────────────────────────────────")

    # Generate device keys
    alice_keys = chisel_core.UserKeys("alice@example.com")
    bob_keys = chisel_core.UserKeys("bob@example.com")

    def _pub_hex(key_obj, is_ed=False):
        return key_obj.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()

    alice_x_hex = _pub_hex(alice_keys.enc_pub)
    alice_e_hex = _pub_hex(alice_keys.sign_pub)
    bob_x_hex = _pub_hex(bob_keys.enc_pub)
    bob_e_hex = _pub_hex(bob_keys.sign_pub)

    alice_pins = chisel_core.KeyPinStore()   # Alice's device-side TOFU store
    bob_pins = chisel_core.KeyPinStore()

    # C1: Upload Alice's keys
    def c1():
        r = client.put("/api/keys", json=alice_keys.key_upload_payload(), headers=alice_h)
        assert r.status_code == 200, r.text
        assert r.json()["fingerprint"] == chisel_core.fingerprint(alice_keys.ed25519_pub_bytes())
    timed("PUT /api/keys — Alice uploads signed public keys", c1)

    # C2: Upload Bob's keys
    def c2():
        r = client.put("/api/keys", json=bob_keys.key_upload_payload(), headers=bob_h)
        assert r.status_code == 200, r.text
    timed("PUT /api/keys — Bob uploads signed public keys", c2)

    # C3: Upload invalid hex
    def c3():
        bad = bob_keys.key_upload_payload() | {"x25519_pub_hex": "ZZZZ"}
        return client.put("/api/keys", json=bad, headers=bob_h)
    expect_fail("PUT /api/keys — invalid hex rejected", c3, expected_status=400)

    # C4: Upload wrong-length key
    def c4():
        bad = bob_keys.key_upload_payload() | {"x25519_pub_hex": "aabb", "ed25519_pub_hex": "ccdd"}
        return client.put("/api/keys", json=bad, headers=bob_h)
    expect_fail("PUT /api/keys — wrong key length rejected", c4, expected_status=400)

    # C4b: Missing signature field
    def c4b():
        return client.put("/api/keys", json={"x25519_pub_hex": bob_x_hex, "ed25519_pub_hex": bob_e_hex}, headers=bob_h)
    expect_fail("PUT /api/keys — unsigned X25519 key rejected (422)", c4b, expected_status=422)

    # C4c: Signature by a different identity key
    def c4c():
        mallory = chisel_core.UserKeys("mallory@example.com")
        forged = bob_keys.key_upload_payload() | {"x25519_sig_hex": mallory.signed_prekey().hex()}
        return client.put("/api/keys", json=forged, headers=bob_h)
    expect_fail("PUT /api/keys — X25519 signed by wrong identity → 400", c4c, expected_status=400)

    # C4d: Identity key swap after pinning
    def c4d():
        impostor = chisel_core.UserKeys("bob@example.com")
        return client.put("/api/keys", json=impostor.key_upload_payload(), headers=bob_h)
    expect_fail("PUT /api/keys — identity key replacement refused → 409", c4d, expected_status=409)

    # C5: Fetch Bob's public keys (authenticated) + client-side verification
    def c5():
        r = client.get("/api/users/bob@example.com/public-keys", headers=alice_h)
        assert r.status_code == 200
        d = r.json()
        assert d["x25519_pub_hex"] == bob_x_hex
        assert d["ed25519_pub_hex"] == bob_e_hex
        assert d["fingerprint"] == chisel_core.fingerprint(bob_keys.ed25519_pub_bytes())
        chisel_core.load_verified_contact(d, alice_pins)
    timed("GET public-keys — correct keys, signature + fingerprint verified", c5)

    # C5b: Lookup without auth
    def c5b():
        return client.get("/api/users/bob@example.com/public-keys")
    expect_fail("GET public-keys — unauthenticated lookup → 401/403", c5b, expected_status=(401, 403))

    # C5c: Uppercase email resolves to the same user
    def c5c():
        r = client.get("/api/users/BOB@EXAMPLE.COM/public-keys", headers=alice_h)
        assert r.status_code == 200 and r.json()["ed25519_pub_hex"] == bob_e_hex
    timed("GET public-keys — email lookup is case-insensitive", c5c)

    # C6: Fetch non-existent user's keys
    def c6():
        return client.get("/api/users/nobody@example.com/public-keys", headers=alice_h)
    expect_fail("GET public-keys — unknown user → 404", c6, expected_status=404)

    # C6b: Client detects a tampered directory entry
    def c6b():
        d = client.get("/api/users/bob@example.com/public-keys", headers=alice_h).json()
        evil = chisel_core.UserKeys("eve@example.com")
        d["x25519_pub_hex"] = evil.x25519_pub_bytes().hex()   # server swaps X25519 only
        try:
            chisel_core.load_verified_contact(d, chisel_core.KeyPinStore())
            raise AssertionError("Swapped X25519 key was accepted!")
        except ValueError as e:
            assert "TAMPERED" in str(e)
    timed("Client: swapped X25519 key in directory → rejected", c6b)

    # C6c: Client detects an identity-key swap via TOFU pin
    def c6c():
        d = client.get("/api/users/bob@example.com/public-keys", headers=alice_h).json()
        evil = chisel_core.UserKeys("bob@example.com")
        d.update(evil.key_upload_payload())                  # whole identity replaced
        try:
            chisel_core.load_verified_contact(d, alice_pins)  # Alice pinned Bob in C5
            raise AssertionError("Swapped identity key was accepted!")
        except ValueError as e:
            assert "IDENTITY KEY CHANGED" in str(e)
    timed("Client: swapped identity key → TOFU pin mismatch rejected", c6c)

    # C7: Daily rotation (same identity, new X25519)
    def c7():
        alice_keys.rotate_daily_key()
        new_x = alice_keys.x25519_pub_bytes().hex()
        r = client.put("/api/keys", json=alice_keys.key_upload_payload(), headers=alice_h)
        assert r.status_code == 200, r.text
        d = client.get("/api/users/alice@example.com/public-keys", headers=bob_h).json()
        assert d["x25519_pub_hex"] == new_x, "Key rotation did not update"
        chisel_core.load_verified_contact(d, bob_pins)
    timed("PUT /api/keys — daily X25519 rotation under pinned identity", c7)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION D: COVER IMAGE POOL
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── D. COVER IMAGE POOL ──────────────────────────────────")

    # D1: Pool status
    def d1():
        r = client.get("/api/pool-status", headers=alice_h)
        assert r.status_code == 200
        d = r.json()
        assert "unused_covers" in d and "total_covers" in d
        return d
    pool_info = timed("GET /api/pool-status — returns counts", d1)

    # D2: Wait for pool to have at least 1 image
    def d2():
        for _ in range(60):
            r = client.get("/api/pool-status", headers=alice_h)
            if r.json()["unused_covers"] > 0:
                return
            time.sleep(1)
        raise TimeoutError("Pool did not populate in 60s")
    timed("Wait for pool to have ≥ 1 cover image", d2)

    pool_before = client.get("/api/pool-status", headers=alice_h).json()

    # D3: Fetch a cover image
    cover_bytes = None
    def d3():
        nonlocal cover_bytes
        r = client.get("/api/cover-image", headers=alice_h)
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        cover_bytes = r.content
        assert len(cover_bytes) > 10000, "Cover image too small"
        # Verify it's a valid 512×512 PNG
        img = Image.open(io.BytesIO(cover_bytes))
        assert img.size == (512, 512), f"Expected 512×512 but got {img.size}"
        assert img.mode == "RGB"
    timed("GET /api/cover-image — valid 512×512 RGB PNG", d3)

    # D4: Cover is deleted from the server once handed out
    def d4():
        d = client.get("/api/pool-status", headers=alice_h).json()
        assert d["total_covers"] == pool_before["total_covers"] - 1, (pool_before, d)
        n = db_query("SELECT COUNT(*) FROM cover_images WHERE image_data = ?", (cover_bytes,))[0][0]
        assert n == 0, "Server still holds a copy of the issued cover"
    timed("Cover deleted server-side after pop (no cover/stego diffing)", d4)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION E: FULL MESSAGE FLOW (encrypt → embed → send → inbox → download → decrypt)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── E. FULL MESSAGE PIPELINE ─────────────────────────────")

    secret_msg = "Top secret: viva at 3 PM tomorrow. Bring the architecture slides."

    # Save cover locally
    cover_path = "_audit_cover.png"
    with open(cover_path, "wb") as f:
        f.write(cover_bytes)

    # E1: Fetch receiver public key from server
    bob_enc_pub_from_server = None
    def e1():
        nonlocal bob_enc_pub_from_server
        d = client.get("/api/users/bob@example.com/public-keys", headers=alice_h).json()
        bob_enc_pub_from_server, _ = chisel_core.load_verified_contact(d, alice_pins)
    timed("Fetch + verify receiver's signed X25519 key", e1)

    # E2: On-device encryption + signing
    bundle = None
    def e2():
        nonlocal bundle
        bundle = chisel_core.encrypt_and_sign(
            secret_msg, alice_keys, bob_keys.user_id, bob_enc_pub_from_server
        )
        assert len(bundle) > 100
    timed("On-device: X25519 ECDH → HKDF → AES-256-GCM → Ed25519 sign", e2)

    # E3: On-device encrypt + hide at keyed, scattered positions (v2)
    stego_path = "_audit_stego.png"
    stats = None
    def e3():
        nonlocal stats
        stats = chisel_core.seal_into_image(
            secret_msg, alice_keys, bob_keys.user_id, bob_enc_pub_from_server, cover_path, stego_path
        )
        assert stats["utilization_pct"] < 5, "Payload uses too much capacity"
    timed("On-device: encrypt + hide at keyed scattered positions (512×512 PNG)", e3)

    # E4: PSNR check
    psnr_val = None
    def e4():
        nonlocal psnr_val
        psnr_val = chisel_core.calculate_psnr(cover_path, stego_path)
        assert psnr_val > 50, f"PSNR {psnr_val} dB too low — image visibly changed"
    timed(f"PSNR check (cover vs stego)", e4)
    print(f"              PSNR = {psnr_val:.2f} dB  |  Payload = {stats['payload_bytes']} bytes  |  Capacity used = {stats['utilization_pct']:.4f}%")

    # E5: Upload stego image
    msg_id = None
    def e5():
        nonlocal msg_id
        with open(stego_path, "rb") as f:
            r = client.post(
                "/api/messages",
                data={"receiver_email": "bob@example.com"},
                files={"stego_image": ("stego.png", f, "image/png")},
                headers=alice_h,
            )
        assert r.status_code == 201
        msg_id = r.json()["message_id"]
    timed("POST /api/messages — upload stego PNG", e5)

    # E6: Bob checks inbox
    def e6():
        r = client.get("/api/messages/inbox", headers=bob_h)
        assert r.status_code == 200
        msgs = r.json()["messages"]
        assert len(msgs) >= 1
        assert msgs[0]["sender_email"] == "alice@example.com"
    timed("GET /api/messages/inbox — Bob sees Alice's message", e6)

    # E7: Alice's inbox should NOT have this message
    def e7():
        r = client.get("/api/messages/inbox", headers=alice_h)
        assert r.status_code == 200
        msgs = r.json()["messages"]
        assert len(msgs) == 0, "Alice should not see her own sent message in inbox"
    timed("GET /api/messages/inbox — Alice's inbox empty (no self-delivery)", e7)

    # E8: Bob downloads the stego image
    dl_bytes = None
    def e8():
        nonlocal dl_bytes
        r = client.get(f"/api/messages/{msg_id}/image", headers=bob_h)
        assert r.status_code == 200
        dl_bytes = r.content
        assert len(dl_bytes) > 10000
    timed("GET /api/messages/{id}/image — download stego PNG", e8)

    # E9: Verify downloaded image is byte-identical to uploaded
    def e9():
        with open(stego_path, "rb") as f:
            original = f.read()
        assert dl_bytes == original, "Downloaded image differs from uploaded — data corruption!"
    timed("Byte-identity check: uploaded == downloaded (no re-encoding)", e9)

    # E10: On-device LSB extraction
    dl_path = "_audit_downloaded.png"
    with open(dl_path, "wb") as f:
        f.write(dl_bytes)
    payload_pos = None
    def e10():
        nonlocal payload_pos
        payload_pos = chisel_core.payload_positions(dl_path, bob_keys)
        assert len(payload_pos) == stats["bits_used"], (len(payload_pos), stats["bits_used"])
    timed("On-device: Bob locates the hidden bits with his private key", e10)

    # E11: Fetch sender's signing key + verify + decrypt
    decrypted = None
    bob_seen = set()   # Bob's device remembers opened msg_ids (replay protection)
    def e11():
        nonlocal decrypted
        d = client.get("/api/users/alice@example.com/public-keys", headers=bob_h).json()
        _, alice_sign_pub = chisel_core.load_verified_contact(d, bob_pins)
        decrypted, meta = chisel_core.open_from_image(
            dl_path, bob_keys, alice_sign_pub, seen_msg_ids=bob_seen
        )
        assert decrypted == secret_msg
        assert meta["sender"] == "alice@example.com"
        assert meta["receiver"] == "bob@example.com"
    timed("On-device: Ed25519 verify + AES-256-GCM decrypt → plaintext", e11)

    print(f"\n              DECRYPTED: \"{decrypted}\"")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION F: SECURITY BOUNDARY TESTS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── F. SECURITY BOUNDARIES ───────────────────────────────")

    # F1: Alice cannot download Bob's message
    def f1():
        r = client.get(f"/api/messages/{msg_id}/image", headers=alice_h)
        return r
    expect_fail("Alice cannot download Bob's message → 404", f1, expected_status=404)

    # F2: Unauthenticated cannot download
    def f2():
        r = client.get(f"/api/messages/{msg_id}/image")
        return r
    expect_fail("Unauthenticated cannot download → 401/403", f2, expected_status=(401, 403))

    # F3: Cannot send to self
    def f3():
        with open(stego_path, "rb") as f:
            r = client.post(
                "/api/messages",
                data={"receiver_email": "alice@example.com"},
                files={"stego_image": ("s.png", f, "image/png")},
                headers=alice_h,
            )
        return r
    expect_fail("POST /api/messages — send to self rejected → 400", f3, expected_status=400)

    # F4: Cannot send to non-existent user
    def f4():
        with open(stego_path, "rb") as f:
            r = client.post(
                "/api/messages",
                data={"receiver_email": "nobody@example.com"},
                files={"stego_image": ("s.png", f, "image/png")},
                headers=alice_h,
            )
        return r
    expect_fail("POST /api/messages — unknown receiver → 404", f4, expected_status=404)

    def _send(raw: bytes, name="x.png"):
        return client.post(
            "/api/messages",
            data={"receiver_email": "bob@example.com"},
            files={"stego_image": (name, raw, "image/png")},
            headers=alice_h,
        )

    # F5: Not a PNG at all
    expect_fail("POST /api/messages — non-PNG bytes rejected → 400",
                lambda: _send(b"this is not an image" * 20), expected_status=400)

    # F6: JPEG disguised with .png name (lossy — would destroy LSBs)
    def f6():
        buf = io.BytesIO()
        Image.new("RGB", (512, 512), (10, 20, 30)).save(buf, format="JPEG")
        return _send(buf.getvalue())
    expect_fail("POST /api/messages — JPEG upload rejected → 400", f6, expected_status=400)

    # F7: Wrong dimensions
    def f7():
        buf = io.BytesIO()
        Image.new("RGB", (256, 256), (10, 20, 30)).save(buf, format="PNG")
        return _send(buf.getvalue())
    expect_fail("POST /api/messages — 256×256 PNG rejected → 400", f7, expected_status=400)

    # F8: Oversized upload
    expect_fail("POST /api/messages — >2 MiB upload rejected → 413",
                lambda: _send(b"\x89PNG\r\n\x1a\n" + os.urandom(2 * 1024 * 1024 + 10)),
                expected_status=413)

    # F9: Corrupted PNG (valid header, broken body)
    def f9():
        with open(stego_path, "rb") as f:
            raw = bytearray(f.read())
        raw[200:260] = os.urandom(60)
        return _send(bytes(raw))
    expect_fail("POST /api/messages — corrupted PNG rejected → 400", f9, expected_status=400)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION G: CRYPTO INTEGRITY TESTS (on-device)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── G. CRYPTO INTEGRITY (on-device) ──────────────────────")

    # G1: Tamper detection (flip 1 bit in stego image)
    def _flip(src, channel_idx, dst):
        img = Image.open(src).convert("RGB")
        ch = bytearray(img.tobytes())
        ch[channel_idx] ^= 1
        Image.frombytes("RGB", img.size, bytes(ch)).save(dst, format="PNG")

    def g1():
        tampered_path = "_audit_tampered.png"
        # A body bit near the end of the payload (inside the signed bundle)
        _flip(dl_path, payload_pos[-200], tampered_path)
        try:
            chisel_core.open_from_image(tampered_path, bob_keys, alice_keys.sign_pub)
            raise AssertionError("Tampered image was accepted!")
        except ValueError as e:
            assert "TAMPER" in str(e) or "DECRYPTION FAILED" in str(e) or "No CHISEL message" in str(e), e
        finally:
            os.remove(tampered_path)
    timed("Tamper test: 1 flipped payload bit → rejected", g1)

    # G2: Wrong receiver cannot decrypt
    def g2():
        eve_keys = chisel_core.UserKeys("eve@example.com")
        alice_sign_pub = alice_keys.sign_pub   # already verified + pinned in E11
        try:
            chisel_core.open_from_image(dl_path, eve_keys, alice_sign_pub)
            raise AssertionError("Eve decrypted Bob's message!")
        except ValueError as e:
            assert "No CHISEL message" in str(e), e  # Eve can't even locate it
    timed("Wrong receiver (Eve) can't even locate Bob's hidden bits", g2)

    # G3: Cryptographic erasure (key rotation)
    def g3():
        old_priv = bob_keys.enc_priv  # save ref for assertion
        bob_keys.rotate_daily_key()
        alice_sign_pub = alice_keys.sign_pub   # already verified + pinned in E11
        try:
            chisel_core.open_from_image(dl_path, bob_keys, alice_sign_pub)
            raise AssertionError("Old ciphertext decrypted after key rotation!")
        except ValueError:
            pass  # Expected — cryptographic erasure works
    timed("Cryptographic erasure: old ciphertext unreadable after key rotation", g3)

    # G4: AAD prevents receiver mismatch
    def g4():
        # Create a fresh bundle for alice→bob, but try decrypting as a different "receiver"
        fresh_bob = chisel_core.UserKeys("bob@example.com")
        fresh_bundle = chisel_core.encrypt_and_sign(
            "test", alice_keys, "bob@example.com", fresh_bob.enc_pub
        )
        # Modify bob's user_id so AAD check fails
        fake_bob = chisel_core.UserKeys("mallory@example.com")
        fake_bob.enc_priv = fresh_bob.enc_priv  # give Mallory Bob's key (hypothetically)
        fake_bob.enc_pub = fresh_bob.enc_pub
        try:
            chisel_core.verify_and_decrypt(fresh_bundle, fake_bob, alice_keys.sign_pub)
            raise AssertionError("AAD check bypassed!")
        except ValueError as e:
            assert "AAD mismatch" in str(e)
    timed("AAD enforcement: receiver ID mismatch → rejected", g4)

    # G5: Replay detection
    def g5():
        carol = chisel_core.UserKeys("carol@example.com")
        b = chisel_core.encrypt_and_sign("once only", alice_keys, carol.user_id, carol.enc_pub)
        seen = set()
        chisel_core.verify_and_decrypt(b, carol, alice_keys.sign_pub, seen_msg_ids=seen)
        try:
            chisel_core.verify_and_decrypt(b, carol, alice_keys.sign_pub, seen_msg_ids=seen)
            raise AssertionError("Replayed message accepted!")
        except ValueError as e:
            assert "REPLAY" in str(e)
    timed("Replay protection: same bundle delivered twice → rejected", g5)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION J: STEGANOGRAPHY — keyed scattering vs. old sequential LSB
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── J. STEGANOGRAPHY (keyed scatter) ─────────────────────")

    def _diff(a_path, b_path):
        a = Image.open(a_path).convert("RGB").tobytes()
        b = Image.open(b_path).convert("RGB").tobytes()
        idx = [i for i in range(len(a)) if a[i] != b[i]]
        deltas = {b[i] - a[i] for i in idx}
        rows = {i // (512 * 3) for i in idx}
        return idx, deltas, rows

    sx, sy = chisel_core.UserKeys("sx@example.com"), chisel_core.UserKeys("sy@example.com")
    v1_path, v2_path = "_audit_v1.png", "_audit_v2.png"
    demo = "Steganography check: where do the bits go?"
    chisel_core.embed_lsb(cover_path, chisel_core.encrypt_and_sign(demo, sx, sy.user_id, sy.enc_pub), v1_path)
    chisel_core.seal_into_image(demo, sx, sy.user_id, sy.enc_pub, cover_path, v2_path)

    def j1():
        _, _, rows_v1 = _diff(cover_path, v1_path)
        _, _, rows_v2 = _diff(cover_path, v2_path)
        print(f"              rows touched: old sequential = {len(rows_v1)}, keyed scatter = {len(rows_v2)} of 512")
        assert len(rows_v1) <= 3 and len(rows_v2) >= 300, (len(rows_v1), len(rows_v2))
    timed("Changes spread over the whole image (≥300 of 512 rows), not the top 2", j1)

    def j2():
        _, deltas, _ = _diff(cover_path, v2_path)
        assert deltas == {1, -1} or deltas <= {1, -1} and len(deltas) == 2, deltas
    timed("LSB matching: values move by +1 and -1 (no LSB-replacement fingerprint)", j2)

    def j3():
        def seq_lsb_bytes(path, n=4000):
            ch = Image.open(path).convert("RGB").tobytes()
            bits = [c & 1 for c in ch[: n * 8]]
            return chisel_core.bits_to_bytes(bits)
        assert b'"sender"' in seq_lsb_bytes(v1_path), "v1 should leak (sanity)"
        assert b'"sender"' not in seq_lsb_bytes(v2_path), "metadata readable without keys!"
    timed("Outsider reading LSBs in order: old format leaks sender JSON, new doesn't", j3)

    def j4():
        try:
            chisel_core.extract_lsb(v2_path)
            raise AssertionError("old extractor found a payload")
        except (ValueError, struct_error):
            pass
    struct_error = __import__("struct").error
    timed("Old sequential extractor finds nothing in a new image", j4)

    def j5():
        p1 = chisel_core.payload_positions(v2_path, sy)
        v2b = "_audit_v2b.png"
        chisel_core.seal_into_image(demo, sx, sy.user_id, sy.enc_pub, cover_path, v2b)
        p2 = chisel_core.payload_positions(v2b, sy)
        os.remove(v2b)
        same_header = p1[:256] == p2[:256]
        overlap = len(set(p1[256:]) & set(p2[256:])) / len(p1[256:])
        print(f"              header positions shared per receiver: {same_header} | body overlap between 2 messages: {overlap:.1%}")
        assert same_header and overlap < 0.05
    timed("Body positions change with every message (keyed by its one-time secret)", j5)

    def j6():
        pos = set(chisel_core.payload_positions(v2_path, sy))
        free = next(i for i in range(10_000, 700_000) if i not in pos)
        _flip(v2_path, free, "_audit_v2c.png")
        text, _ = chisel_core.open_from_image("_audit_v2c.png", sy, sx.sign_pub)
        os.remove("_audit_v2c.png")
        assert text == demo
    timed("Editing a pixel outside the payload doesn't break the message", j6)

    for f in (v1_path, v2_path):
        os.remove(f)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION H: MESSAGE LIFECYCLE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── H. MESSAGE LIFECYCLE ─────────────────────────────────")

    # H1: Delete message
    def h1():
        # Send a deletable message
        # Bob already rotated in G3 — upload the new signed X25519 key
        r = client.put("/api/keys", json=bob_keys.key_upload_payload(), headers=bob_h)
        assert r.status_code == 200, r.text
        new_bob_enc_pub = bob_keys.enc_pub
        chisel_core.seal_into_image("delete me", alice_keys, "bob@example.com", new_bob_enc_pub,
                                    cover_path, "_audit_del.png")
        with open("_audit_del.png", "rb") as f:
            r = client.post(
                "/api/messages",
                data={"receiver_email": "bob@example.com"},
                files={"stego_image": ("d.png", f, "image/png")},
                headers=alice_h,
            )
        del_id = r.json()["message_id"]
        # Bob deletes it
        r = client.delete(f"/api/messages/{del_id}", headers=bob_h)
        assert r.status_code == 200
        # Verify it's gone
        r = client.get(f"/api/messages/{del_id}/image", headers=bob_h)
        assert r.status_code == 404
        os.remove("_audit_del.png")
    timed("DELETE /api/messages/{id} — message removed + verified gone", h1)

    # H2: Non-admin cannot seed
    expect_fail("POST /api/admin/seed-pool — non-admin → 403",
                lambda: client.post("/api/admin/seed-pool?count=1", headers=alice_h),
                expected_status=403)

    # Sign in the admin account
    admin_h = None
    def h3():
        nonlocal admin_h
        otp = client.post("/api/register", json={"email": ADMIN_EMAIL}).json()["otp_for_demo"]
        tok = client.post("/api/verify-otp", json={"email": ADMIN_EMAIL, "code": otp}).json()["token"]
        admin_h = {"Authorization": f"Bearer {tok}"}
    timed("Admin account signs in", h3)

    # H4: Admin count is bounded
    expect_fail("POST /api/admin/seed-pool — count=999 rejected → 422",
                lambda: client.post("/api/admin/seed-pool?count=999", headers=admin_h),
                expected_status=422)

    # H5: Admin seeds 1 image (calls Pollinations)
    def h5():
        r = client.post("/api/admin/seed-pool?count=1", headers=admin_h, timeout=120)
        assert r.status_code == 200, r.text
        assert "Added 1" in r.json()["message"], r.json()
    timed("POST /api/admin/seed-pool — admin generates 1 image", h5)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECTION I: AUTH HARDENING
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n── I. AUTH HARDENING ────────────────────────────────────")

    carol_otp = None
    def i1():
        nonlocal carol_otp
        r = client.post("/api/register", json={"email": "carol@example.com"})
        assert r.status_code == 200
        carol_otp = r.json()["otp_for_demo"]
        rows = db_query("SELECT code_hash FROM otps WHERE email = ?", ("carol@example.com",))
        assert rows and all(len(h) == 64 and carol_otp not in h for (h,) in rows)
    timed("OTP stored only as HMAC-SHA256 hash (no plaintext in DB)", i1)

    expect_fail("POST /api/register — resend within cooldown → 429",
                lambda: client.post("/api/register", json={"email": "carol@example.com"}),
                expected_status=429)

    def i3():
        wrong = "000000" if carol_otp != "000000" else "111111"
        codes = []
        for _ in range(5):
            codes.append(client.post("/api/verify-otp", json={"email": "carol@example.com", "code": wrong}).status_code)
        assert codes[:4] == [400] * 4 and codes[4] == 429, codes
        # The real code is now burned too
        r = client.post("/api/verify-otp", json={"email": "carol@example.com", "code": carol_otp})
        assert r.status_code == 400, r.status_code
    timed("OTP brute force: 5 wrong guesses burn the code (even correct one fails)", i3)

    def i4():
        import base64, json as _json
        def b64(o): return base64.urlsafe_b64encode(_json.dumps(o).encode()).rstrip(b"=").decode()
        forged = b64({"alg": "none", "typ": "JWT"}) + "." + b64({"sub": alice_uid, "exp": 9999999999, "iat": 0, "typ": "access"}) + "."
        return client.get("/api/messages/inbox", headers={"Authorization": f"Bearer {forged}"})
    expect_fail("JWT with alg=none rejected → 401", i4, expected_status=401)

    def i5():
        from server.config import Settings
        bad = Settings(_env_file=None, ENVIRONMENT="production")
        try:
            bad.check_production_safety()
            raise AssertionError("Production booted with default secret!")
        except RuntimeError as e:
            assert "SECRET_KEY" in str(e) and "DEMO_RETURN_OTP" in str(e)
    timed("Production config refuses default secret / demo OTP / CORS *", i5)

    def i6():
        r = client.get("/api/health")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("cache-control") == "no-store"
    timed("Security headers present (nosniff, no-store)", i6)

    # ── Identity reset (new phone / cleared browser) ────────
    dave_h, dave_keys = None, None
    def i8():
        nonlocal dave_h, dave_keys
        otp = client.post("/api/register", json={"email": "dave@example.com"}).json()["otp_for_demo"]
        tok = client.post("/api/verify-otp", json={"email": "dave@example.com", "code": otp}).json()["token"]
        dave_h = {"Authorization": f"Bearer {tok}"}
        dave_keys = chisel_core.UserKeys("dave@example.com")
        assert client.put("/api/keys", json=dave_keys.key_upload_payload(), headers=dave_h).status_code == 200
        new_phone = chisel_core.UserKeys("dave@example.com")
        r = client.put("/api/keys", json=new_phone.key_upload_payload(), headers=dave_h)
        assert r.status_code == 409, r.status_code
        r = client.put("/api/keys", json=new_phone.key_upload_payload() | {"reset_identity": True}, headers=dave_h)
        assert r.status_code == 200 and r.json()["identity_reset"] is True, r.text
        d = client.get("/api/users/dave@example.com/public-keys", headers=alice_h).json()
        assert d["ed25519_pub_hex"] == new_phone.ed25519_pub_bytes().hex()
        dave_keys = new_phone
    timed("Identity reset works only with reset_identity + fresh sign-in", i8)

    def i9():
        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone
        from server.config import settings as srv
        old = datetime.now(timezone.utc) - timedelta(minutes=30)
        claims = pyjwt.decode(dave_h["Authorization"].split()[1], options={"verify_signature": False})
        stale = pyjwt.encode(claims | {"iat": old, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                             srv.SECRET_KEY, algorithm=srv.JWT_ALGORITHM)
        third = chisel_core.UserKeys("dave@example.com")
        return client.put("/api/keys", json=third.key_upload_payload() | {"reset_identity": True},
                          headers={"Authorization": f"Bearer {stale}"})
    expect_fail("Identity reset with a 30-min-old token → 403 (stolen token can't swap keys)", i9, expected_status=403)

    def i10():
        r = client.get("/")
        assert r.status_code == 200 and "<title>Chisel</title>" in r.text, r.status_code
        csp = r.headers.get("content-security-policy", "")
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp, csp
        for path in ("/js/chisel.js", "/js/app.js", "/js/ui.js", "/js/data.js", "/vendor/libs.js", "/js/compat.js", "/manifest.webmanifest",
                     "/sw.js", "/icons/icon-192.png", "/fonts/arimo-latin-400-normal.woff2", "/favicon.ico"):
            assert client.get(path).status_code == 200, path
        assert client.get("/api/does-not-exist").status_code == 404
    timed("Phone app served from / with a strict CSP; API routes unaffected", i10)

    # ── Display names ───────────────────────────────────────
    def i11():
        r = client.put("/api/me", json={"display_name": "  Alice   Sharma "}, headers=alice_h)
        assert r.status_code == 200 and r.json()["display_name"] == "Alice Sharma", r.text
        assert client.get("/api/me", headers=alice_h).json()["display_name"] == "Alice Sharma"
        d = client.get("/api/users/alice@example.com/public-keys", headers=bob_h).json()
        assert d["display_name"] == "Alice Sharma", d
    timed("Display name: set (whitespace tidied), read back, shown to contacts", i11)

    def i12():
        bad = ["", "   ", "x" * 41, "Bad\x00name", "Bell\x07name"]
        codes = [client.put("/api/me", json={"display_name": b}, headers=alice_h).status_code for b in bad]
        assert codes == [422] * len(bad), codes
        # Tabs/newlines are whitespace: tidied into single spaces, not rejected
        r = client.put("/api/me", json={"display_name": "Tab\tand\nnewline"}, headers=alice_h)
        assert r.status_code == 200 and r.json()["display_name"] == "Tab and newline", r.text
        assert client.put("/api/me", json={"display_name": "Alice Sharma"}, headers=alice_h).status_code == 200
    timed("Display name: empty, too long or control characters → 422", i12)

    # ── Clearing chats ──────────────────────────────────────
    def i13():
        def send_one():
            d = client.get("/api/users/bob@example.com/public-keys", headers=alice_h).json()
            x, _ = chisel_core.load_verified_contact(d, chisel_core.KeyPinStore())
            chisel_core.seal_into_image("clear me", alice_keys, "bob@example.com", x, cover_path, "_audit_clear.png")
            with open("_audit_clear.png", "rb") as f:
                assert client.post("/api/messages", data={"receiver_email": "bob@example.com"},
                                   files={"stego_image": ("c.png", f, "image/png")}, headers=alice_h).status_code == 201
        send_one(); send_one()
        inbox = client.get("/api/messages/inbox", headers=bob_h).json()["messages"]
        assert inbox and inbox[0]["sender_display_name"] == "Alice Sharma", inbox[:1]
        r = client.delete("/api/chats?with=alice@example.com", headers=bob_h)
        assert r.status_code == 200 and r.json()["deleted"] >= 2, r.text
        assert not [m for m in client.get("/api/messages/inbox", headers=bob_h).json()["messages"] if m["sender_email"] == "alice@example.com"]
        assert client.delete("/api/chats", headers=bob_h).json()["deleted"] >= 0
        os.remove("_audit_clear.png")
    timed("Clear chat with one contact, then all chats (receiver's copies only)", i13)

    # ── Deleting an account ─────────────────────────────────
    def i14():
        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone
        from server.config import settings as srv
        claims = pyjwt.decode(dave_h["Authorization"].split()[1], options={"verify_signature": False})
        stale = pyjwt.encode(claims | {"iat": datetime.now(timezone.utc) - timedelta(minutes=30),
                                       "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                             srv.SECRET_KEY, algorithm=srv.JWT_ALGORITHM)
        r = client.delete("/api/me", headers={"Authorization": f"Bearer {stale}"})
        assert r.status_code == 403, r.status_code
        r = client.delete("/api/me", headers=dave_h)            # fresh sign-in from i8
        assert r.status_code == 200, r.text
        assert client.get("/api/me", headers=dave_h).status_code == 401
        assert client.get("/api/users/dave@example.com/public-keys", headers=alice_h).status_code == 404
    timed("Delete account: refused with old token (403), works after fresh sign-in", i14)

    # Must be last: exhausts this IP's auth budget for a minute
    def i7():
        statuses = []
        for n in range(60):
            sc = client.post("/api/register", json={"email": f"spam{n}@example.com"}).status_code
            statuses.append(sc)
            if sc == 429:
                return
        raise AssertionError(f"No 429 after 60 requests: {statuses[-5:]}")
    timed("Per-IP auth rate limit kicks in (429)", i7)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # RESULTS SUMMARY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 76)
    print("  AUDIT RESULTS SUMMARY")
    print("=" * 76)

    total = len(results)
    passed = sum(1 for _, s, _, _ in results if s == PASS)
    failed = sum(1 for _, s, _, _ in results if s == FAIL)

    print(f"\n  {'Test':<70} {'Time':>9}  Result")
    print(f"  {'─'*70} {'─'*9}  {'─'*6}")
    total_time = 0
    for label, status, ms, detail in results:
        total_time += ms
        print(f"  {label:<70} {ms:>7.1f}ms  {status}")

    print(f"\n  {'─'*76}")
    print(f"  Total tests:  {total}")
    print(f"  Passed:       {passed}  {PASS}")
    print(f"  Failed:       {failed}  {'❌' if failed else ''}")
    print(f"  Total time:   {total_time:.0f} ms ({total_time/1000:.2f} s)")
    print(f"  {'─'*76}")

    if failed:
        print("\n  FAILED TESTS:")
        for label, status, ms, detail in results:
            if status == FAIL:
                print(f"    ❌  {label}: {detail}")

    # Cleanup
    for f in [cover_path, stego_path, dl_path]:
        if os.path.exists(f):
            os.remove(f)

    client.close()

    print("\n" + ("  ✅  ALL TESTS PASSED!" if failed == 0 else f"  ❌  {failed} TEST(S) FAILED!"))
    print("=" * 76)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
