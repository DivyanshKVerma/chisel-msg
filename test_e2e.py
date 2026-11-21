"""
CHISEL End-to-End Integration Test
===================================
Simulates the complete flow:
  1. Alice and Bob register (email → OTP)
  2. Both verify OTP → get JWT tokens
  3. Both generate keys on-device and upload public keys
  4. Alice fetches Bob's public key
  5. Alice fetches a cover image from the pool
  6. Alice encrypts a message, embeds it via LSB, uploads the stego PNG
  7. Bob checks inbox, downloads the stego image
  8. Bob extracts, verifies signature, decrypts → sees the original message
"""

import io
import os
import sys
import time

import httpx
from PIL import Image

# Add project root so we can import chisel_core
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chisel_core

BASE = "http://127.0.0.1:8000"


def main():
    client = httpx.Client(base_url=BASE, timeout=30)

    print("=" * 60)
    print("  CHISEL — FULL END-TO-END INTEGRATION TEST")
    print("=" * 60)

    # ── 1. Register Alice & Bob ──────────────────────────
    print("\n[1] Registering Alice...")
    r = client.post("/api/register", json={"email": "alice@gbu.ac.in"})
    assert r.status_code == 200, f"Register failed: {r.text}"
    alice_otp = r.json()["otp_for_demo"]
    print(f"    OTP for Alice: {alice_otp}")

    print("[1] Registering Bob...")
    r = client.post("/api/register", json={"email": "bob@gbu.ac.in"})
    assert r.status_code == 200, f"Register failed: {r.text}"
    bob_otp = r.json()["otp_for_demo"]
    print(f"    OTP for Bob:   {bob_otp}")

    # ── 2. Verify OTP → get JWTs ────────────────────────
    print("\n[2] Verifying OTP for Alice...")
    r = client.post("/api/verify-otp", json={"email": "alice@gbu.ac.in", "code": alice_otp})
    assert r.status_code == 200, f"Verify failed: {r.text}"
    alice_data = r.json()
    alice_token = alice_data["token"]
    alice_id = alice_data["user_id"]
    print(f"    Alice JWT: {alice_token[:30]}...")

    print("[2] Verifying OTP for Bob...")
    r = client.post("/api/verify-otp", json={"email": "bob@gbu.ac.in", "code": bob_otp})
    assert r.status_code == 200, f"Verify failed: {r.text}"
    bob_data = r.json()
    bob_token = bob_data["token"]
    bob_id = bob_data["user_id"]
    print(f"    Bob JWT:   {bob_token[:30]}...")

    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # ── 3. Generate keys on-device & upload public keys ──
    print("\n[3] Generating device keys for Alice...")
    alice_keys = chisel_core.UserKeys("alice@gbu.ac.in")
    alice_payload = alice_keys.key_upload_payload()  # includes signed X25519 key
    alice_x25519_pub_hex = alice_payload["x25519_pub_hex"]
    alice_ed25519_pub_hex = alice_payload["ed25519_pub_hex"]

    r = client.put("/api/keys", json=alice_payload, headers=alice_headers)
    assert r.status_code == 200, f"Key upload failed: {r.text}"
    print(f"    Alice X25519 pub:  {alice_x25519_pub_hex[:16]}...")
    print(f"    Alice Ed25519 pub: {alice_ed25519_pub_hex[:16]}...")

    print("[3] Generating device keys for Bob...")
    bob_keys = chisel_core.UserKeys("bob@gbu.ac.in")
    bob_payload = bob_keys.key_upload_payload()
    bob_x25519_pub_hex = bob_payload["x25519_pub_hex"]
    bob_ed25519_pub_hex = bob_payload["ed25519_pub_hex"]

    r = client.put("/api/keys", json=bob_payload, headers=bob_headers)
    assert r.status_code == 200, f"Key upload failed: {r.text}"
    print(f"    Bob X25519 pub:    {bob_x25519_pub_hex[:16]}...")
    print(f"    Bob Ed25519 pub:   {bob_ed25519_pub_hex[:16]}...")

    # ── 4. Alice fetches Bob's public key ────────────────
    print("\n[4] Alice fetches Bob's public keys from server...")
    alice_pins = chisel_core.KeyPinStore()  # Alice's device-side TOFU pins
    r = client.get("/api/users/bob@gbu.ac.in/public-keys", headers=alice_headers)
    assert r.status_code == 200, f"Key lookup failed: {r.text}"
    bob_pub_data = r.json()
    print(f"    Got Bob's X25519:  {bob_pub_data['x25519_pub_hex'][:16]}...")
    print(f"    Bob's fingerprint: {bob_pub_data['fingerprint']}")
    # Verify signature on Bob's X25519 key + pin his identity before using it
    bob_enc_pub_from_server, _ = chisel_core.load_verified_contact(bob_pub_data, alice_pins)
    print("    Signed X25519 key verified against Bob's identity key ✔")

    # ── 5. Alice fetches a cover image ───────────────────
    print("\n[5] Alice fetches a cover image from pool...")
    r = client.get("/api/cover-image", headers=alice_headers)
    if r.status_code == 503:
        print("    Pool empty — waiting for refill (30s)...")
        time.sleep(30)
        r = client.get("/api/cover-image", headers=alice_headers)
    assert r.status_code == 200, f"Cover image fetch failed ({r.status_code}): {r.text}"
    cover_bytes = r.content
    print(f"    Got cover image: {len(cover_bytes)} bytes")

    # Save cover locally for the embed step
    cover_path = "test_cover_from_server.png"
    with open(cover_path, "wb") as f:
        f.write(cover_bytes)

    # ── 6. Alice encrypts + LSB embeds + uploads ─────────
    secret_msg = "CHISEL integration test: end-to-end encrypted stego message!"
    print(f"\n[6] Alice encrypts: \"{secret_msg}\"")

    bundle = chisel_core.encrypt_and_sign(
        secret_msg, alice_keys, bob_keys.user_id, bob_enc_pub_from_server
    )
    print(f"    Encrypted bundle: {len(bundle)} bytes")

    stego_path = "test_stego_upload.png"
    stats = chisel_core.embed_lsb(cover_path, bundle, stego_path)
    psnr = chisel_core.calculate_psnr(cover_path, stego_path)
    print(f"    LSB embedded:     {stats['utilization_pct']:.4f}% capacity used")
    print(f"    PSNR:             {psnr:.2f} dB")

    print("[6] Uploading stego PNG to server...")
    with open(stego_path, "rb") as f:
        r = client.post(
            "/api/messages",
            data={"receiver_email": "bob@gbu.ac.in"},
            files={"stego_image": ("stego.png", f, "image/png")},
            headers=alice_headers,
        )
    assert r.status_code == 201, f"Send failed: {r.text}"
    msg_id = r.json()["message_id"]
    expires = r.json()["expires_at"]
    print(f"    Message ID:  {msg_id}")
    print(f"    Expires at:  {expires}")

    # ── 7. Bob checks inbox ──────────────────────────────
    print("\n[7] Bob checks inbox...")
    r = client.get("/api/messages/inbox", headers=bob_headers)
    assert r.status_code == 200, f"Inbox failed: {r.text}"
    inbox = r.json()["messages"]
    print(f"    Messages in inbox: {len(inbox)}")
    assert len(inbox) >= 1, "No messages in inbox!"
    print(f"    Latest from: {inbox[0]['sender_email']}")
    latest_msg_id = inbox[0]["id"]

    # ── 8. Bob downloads the stego image ─────────────────
    print(f"\n[8] Bob downloads stego image (id={latest_msg_id[:8]}...)...")
    r = client.get(f"/api/messages/{latest_msg_id}/image", headers=bob_headers)
    assert r.status_code == 200, f"Download failed: {r.text}"
    downloaded_stego = r.content
    print(f"    Downloaded: {len(downloaded_stego)} bytes")

    # Save it locally for extraction
    dl_stego_path = "test_stego_downloaded.png"
    with open(dl_stego_path, "wb") as f:
        f.write(downloaded_stego)

    # ── 9. Bob extracts + verifies + decrypts ────────────
    print("\n[9] Bob extracts LSB payload...")
    extracted_bundle = chisel_core.extract_lsb(dl_stego_path)
    print(f"    Extracted bundle: {len(extracted_bundle)} bytes")

    # Reconstruct Alice's signing key from the server
    bob_pins = chisel_core.KeyPinStore()
    r = client.get("/api/users/alice@gbu.ac.in/public-keys", headers=bob_headers)
    alice_pub_data = r.json()
    _, alice_sign_pub_from_server = chisel_core.load_verified_contact(alice_pub_data, bob_pins)

    print("[9] Verifying Ed25519 signature + decrypting AES-256-GCM...")
    decrypted, meta = chisel_core.verify_and_decrypt(
        extracted_bundle, bob_keys, alice_sign_pub_from_server
    )

    print(f"\n    ┌─────────────────────────────────────────────────┐")
    print(f"    │  DECRYPTED MESSAGE: {decrypted}")
    print(f"    │  Sender:    {meta['sender']}")
    print(f"    │  Receiver:  {meta['receiver']}")
    print(f"    │  Message ID:{meta['msg_id']}")
    print(f"    └─────────────────────────────────────────────────┘")

    assert decrypted == secret_msg, f"MISMATCH! Got: {decrypted}"

    # ── 10. Health & Pool Status ─────────────────────────
    print("\n[10] Server health & pool status...")
    r = client.get("/api/health")
    print(f"    Health: {r.json()}")
    r = client.get("/api/pool-status", headers=alice_headers)
    print(f"    Pool:   {r.json()}")

    # ── Cleanup test files ───────────────────────────────
    for f in [cover_path, stego_path, dl_stego_path]:
        if os.path.exists(f):
            os.remove(f)

    print("\n" + "=" * 60)
    print("  ✅  ALL TESTS PASSED — CHISEL E2E PIPELINE WORKS!")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
