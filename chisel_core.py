import hashlib
import json
import math
import os
import struct
import time
import uuid
from PIL import Image
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


# ---------------------------------------------------------
# 1. USER KEY MANAGEMENT (Device-side only)
# ---------------------------------------------------------
class UserKeys:
    def __init__(self, user_id: str):
        self.user_id = user_id
        # Long-term signing identity key
        self.sign_priv = ed25519.Ed25519PrivateKey.generate()
        self.sign_pub = self.sign_priv.public_key()
        # Daily rotating encryption key (destroyed after 24h)
        self.enc_priv = x25519.X25519PrivateKey.generate()
        self.enc_pub = self.enc_priv.public_key()

    def rotate_daily_key(self):
        """Simulates 24h cryptographic erasure by destroying the old private key."""
        self.enc_priv = x25519.X25519PrivateKey.generate()
        self.enc_pub = self.enc_priv.public_key()

    # -- Public material to upload to the server's key directory --
    def x25519_pub_bytes(self) -> bytes:
        return _raw(self.enc_pub)

    def ed25519_pub_bytes(self) -> bytes:
        return _raw(self.sign_pub)

    def signed_prekey(self) -> bytes:
        """Ed25519 signature binding the current X25519 key to this identity."""
        return self.sign_priv.sign(PREKEY_CONTEXT + self.x25519_pub_bytes())

    def key_upload_payload(self) -> dict:
        """JSON body for PUT /api/keys."""
        return {
            "x25519_pub_hex": self.x25519_pub_bytes().hex(),
            "ed25519_pub_hex": self.ed25519_pub_bytes().hex(),
            "x25519_sig_hex": self.signed_prekey().hex(),
        }


# ---------------------------------------------------------
# 1b. KEY DIRECTORY VERIFICATION (client must not blindly trust the server)
# ---------------------------------------------------------
PREKEY_CONTEXT = b"CHISEL-v1-prekey"
FINGERPRINT_CONTEXT = b"CHISEL-v1-fingerprint"


def _raw(pub) -> bytes:
    return pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def fingerprint(ed25519_pub_bytes: bytes) -> str:
    """30-digit safety number users can compare in person (6 groups of 5 digits)."""
    digest = hashlib.sha256(FINGERPRINT_CONTEXT + ed25519_pub_bytes).digest()
    groups = [int.from_bytes(digest[i : i + 5], "big") % 100_000 for i in range(0, 30, 5)]
    return " ".join(f"{g:05d}" for g in groups)


class KeyPinStore:
    """
    Trust-on-first-use pinning of contacts' identity keys (lives on the device).
    The first identity key seen for an email is remembered; if the server later
    hands out a different one, the client refuses instead of silently trusting it.
    """

    def __init__(self):
        self._pins: dict[str, bytes] = {}

    def check(self, email: str, ed25519_pub_bytes: bytes) -> None:
        pinned = self._pins.setdefault(email.lower(), ed25519_pub_bytes)
        if pinned != ed25519_pub_bytes:
            raise ValueError(
                f"IDENTITY KEY CHANGED for {email}! Possible server-side key substitution. "
                "Verify the fingerprint in person before trusting the new key."
            )


def load_verified_contact(directory_entry: dict, pins: KeyPinStore | None = None):
    """
    Turn a /api/users/{email}/public-keys response into usable key objects,
    after checking (1) the TOFU pin and (2) the identity key's signature on the
    X25519 key. Returns (x25519_pub, ed25519_pub).
    """
    ed_bytes = bytes.fromhex(directory_entry["ed25519_pub_hex"])
    x_bytes = bytes.fromhex(directory_entry["x25519_pub_hex"])
    sig = bytes.fromhex(directory_entry["x25519_sig_hex"])

    if pins is not None:
        pins.check(directory_entry["email"], ed_bytes)

    ed_pub = ed25519.Ed25519PublicKey.from_public_bytes(ed_bytes)
    try:
        ed_pub.verify(sig, PREKEY_CONTEXT + x_bytes)
    except InvalidSignature as e:
        raise ValueError("KEY DIRECTORY TAMPERED: X25519 key is not signed by the identity key!") from e

    return x25519.X25519PublicKey.from_public_bytes(x_bytes), ed_pub


# ---------------------------------------------------------
# 2. CRYPTOGRAPHIC LAYER (X25519 + HKDF + AES-256-GCM + Ed25519)
# ---------------------------------------------------------
def derive_aes_key(shared_secret: bytes, salt: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,  # 256-bit key
        salt=salt,
        info=b"CHISEL-v1-AES256GCM",
    ).derive(shared_secret)


def encrypt_and_sign(
    plaintext: str,
    sender: UserKeys,
    receiver_id: str,
    receiver_enc_pub: x25519.X25519PublicKey,
    ttl_seconds: int = 86400,
) -> bytes:
    # 1. Per-message ephemeral X25519 key pair
    eph_priv = x25519.X25519PrivateKey.generate()
    eph_pub_bytes = eph_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    # 2. Compute shared secret & derive AES-256 key via HKDF
    nonce = os.urandom(12)  # Fresh 12-byte GCM nonce every time
    shared_secret = eph_priv.exchange(receiver_enc_pub)
    aes_key = derive_aes_key(shared_secret, salt=nonce)

    # 3. Build AAD (authenticated metadata to prevent rerouting/replay/expiry extension)
    aad_dict = {
        "sender": sender.user_id,
        "receiver": receiver_id,
        "msg_id": str(uuid.uuid4()),
        "expiry": int(time.time()) + ttl_seconds,
    }
    aad = json.dumps(aad_dict, separators=(",", ":")).encode("utf-8")

    # 4. Encrypt with AES-256-GCM
    ciphertext_and_tag = AESGCM(aes_key).encrypt(nonce, plaintext.encode("utf-8"), aad)

    # 5. Pack unsigned bundle: [32B eph_pub | 12B nonce | 2B aad_len | aad | 4B ct_len | ct+tag]
    unsigned_bundle = (
        eph_pub_bytes
        + nonce
        + struct.pack(">H", len(aad))
        + aad
        + struct.pack(">I", len(ciphertext_and_tag))
        + ciphertext_and_tag
    )

    # 6. Sign the entire bundle with sender's Ed25519 private key (64 bytes)
    signature = sender.sign_priv.sign(unsigned_bundle)
    return unsigned_bundle + signature


def verify_and_decrypt(
    bundle: bytes,
    receiver: UserKeys,
    sender_sign_pub: ed25519.Ed25519PublicKey,
    seen_msg_ids: set | None = None,
) -> tuple[str, dict]:
    if len(bundle) < 32 + 12 + 2 + 4 + 64:
        raise ValueError("Corrupted payload: bundle too short.")

    # 1. Split signature and verify authenticity first (fail fast on tamper)
    unsigned_bundle = bundle[:-64]
    signature = bundle[-64:]
    try:
        sender_sign_pub.verify(signature, unsigned_bundle)
    except InvalidSignature as e:
        raise ValueError("TAMPER DETECTED: Ed25519 signature verification failed!") from e

    # 2. Unpack fields
    offset = 0
    eph_pub_bytes = unsigned_bundle[offset : offset + 32]
    offset += 32
    nonce = unsigned_bundle[offset : offset + 12]
    offset += 12

    (aad_len,) = struct.unpack(">H", unsigned_bundle[offset : offset + 2])
    offset += 2
    aad = unsigned_bundle[offset : offset + aad_len]
    offset += aad_len

    (ct_len,) = struct.unpack(">I", unsigned_bundle[offset : offset + 4])
    offset += 4
    ciphertext_and_tag = unsigned_bundle[offset : offset + ct_len]

    # 3. Validate AAD metadata (receiver match & 24h expiry)
    aad_dict = json.loads(aad.decode("utf-8"))
    if aad_dict["receiver"] != receiver.user_id:
        raise ValueError("AAD mismatch: message was not addressed to this receiver.")
    if time.time() > aad_dict["expiry"]:
        raise ValueError("Message expired (past 24-hour TTL).")
    # Optional replay protection: the device remembers msg_ids it has opened
    if seen_msg_ids is not None and aad_dict["msg_id"] in seen_msg_ids:
        raise ValueError("REPLAY DETECTED: this message was already delivered.")

    # 4. Recompute shared secret & decrypt AES-256-GCM
    eph_pub = x25519.X25519PublicKey.from_public_bytes(eph_pub_bytes)
    shared_secret = receiver.enc_priv.exchange(eph_pub)
    aes_key = derive_aes_key(shared_secret, salt=nonce)

    try:
        plaintext_bytes = AESGCM(aes_key).decrypt(nonce, ciphertext_and_tag, aad)
    except InvalidTag as e:
        raise ValueError("DECRYPTION FAILED: Wrong/rotated key or corrupted ciphertext!") from e

    if seen_msg_ids is not None:
        seen_msg_ids.add(aad_dict["msg_id"])
    return plaintext_bytes.decode("utf-8"), aad_dict


# ---------------------------------------------------------
# 3. STEGANOGRAPHY LAYER (Lossless 512x512 PNG LSB)
# ---------------------------------------------------------
def bytes_to_bits(data: bytes) -> list[int]:
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def bits_to_bytes(bits: list[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits[i : i + 8]:
            byte = (byte << 1) | bit
        out.append(byte)
    return bytes(out)


def embed_lsb(cover_path: str, payload: bytes, output_path: str) -> dict:
    img = Image.open(cover_path).convert("RGB")
    w, h = img.size
    max_bits = w * h * 3

    # Prefix payload with 4-byte big-endian length header
    framed = struct.pack(">I", len(payload)) + payload
    bits = bytes_to_bits(framed)

    if len(bits) > max_bits:
        raise ValueError(f"Payload too large ({len(bits)} bits) for image capacity ({max_bits} bits).")

    pixels = list(img.get_flattened_data())
    new_pixels = []
    bit_idx = 0
    total_bits = len(bits)

    for r, g, b in pixels:
        if bit_idx < total_bits:
            r = (r & ~1) | bits[bit_idx]
            bit_idx += 1
        if bit_idx < total_bits:
            g = (g & ~1) | bits[bit_idx]
            bit_idx += 1
        if bit_idx < total_bits:
            b = (b & ~1) | bits[bit_idx]
            bit_idx += 1
        new_pixels.append((r, g, b))

    stego_img = Image.new("RGB", (w, h))
    stego_img.putdata(new_pixels)
    stego_img.save(output_path, format="PNG")

    return {
        "payload_bytes": len(payload),
        "bits_used": total_bits,
        "capacity_bits": max_bits,
        "utilization_pct": (total_bits / max_bits) * 100,
    }


def extract_lsb(stego_path: str) -> bytes:
    img = Image.open(stego_path).convert("RGB")
    pixels = list(img.get_flattened_data())

    # Flatten LSBs lazily as needed
    def lsb_stream():
        for r, g, b in pixels:
            yield r & 1
            yield g & 1
            yield b & 1

    stream = lsb_stream()

    # Read 4-byte (32-bit) length header first
    header_bits = [next(stream) for _ in range(32)]
    (payload_len,) = struct.unpack(">I", bits_to_bytes(header_bits))

    max_bytes = (img.width * img.height * 3 // 8) - 4
    if payload_len <= 0 or payload_len > max_bytes:
        raise ValueError(f"Invalid extracted payload length ({payload_len} bytes). Image may be corrupted.")

    payload_bits = [next(stream) for _ in range(payload_len * 8)]
    return bits_to_bytes(payload_bits)


# ---------------------------------------------------------
# 4. METRICS & HELPER UTILITIES
# ---------------------------------------------------------
def calculate_psnr(cover_path: str, stego_path: str) -> float:
    img1 = list(Image.open(cover_path).convert("RGB").get_flattened_data())
    img2 = list(Image.open(stego_path).convert("RGB").get_flattened_data())

    sq_err = 0
    for (r1, g1, b1), (r2, g2, b2) in zip(img1, img2):
        sq_err += (r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2

    mse = sq_err / (len(img1) * 3)
    if mse == 0:
        return float("inf")
    return 10 * math.log10((255.0 ** 2) / mse)


def create_dummy_cover(path: str, size: int = 512):
    """Generates a clean 512x512 RGB PNG so the prototype runs immediately without an AI API."""
    img = Image.new("RGB", (size, size))
    pixels = [
        (int(x * 255 / size), int(y * 255 / size), 140)
        for y in range(size)
        for x in range(size)
    ]
    img.putdata(pixels)
    img.save(path, format="PNG")


# ---------------------------------------------------------
# 5. END-TO-END DEMO & SECURITY TESTS
# ---------------------------------------------------------
if __name__ == "__main__":
    cover_file = "cover_512.png"
    stego_file = "stego_512.png"
    tampered_file = "tampered_512.png"

    if not os.path.exists(cover_file):
        create_dummy_cover(cover_file)
        print(f"[+] Created fallback 512x512 cover image: {cover_file}")

    # Step A: Sign-up / Daily Key Generation
    alice = UserKeys("alice@gbu.ac.in")
    bob = UserKeys("bob@gbu.ac.in")
    secret_message = "Meet at the library at 5 PM. Project viva slides are finalized."

    # Step B: Encrypt, Sign & Embed
    bundle = encrypt_and_sign(secret_message, alice, bob.user_id, bob.enc_pub)
    stats = embed_lsb(cover_file, bundle, stego_file)
    psnr = calculate_psnr(cover_file, stego_file)

    print("\n--- EMBEDDING REPORT ---")
    print(f"Bundle Size : {stats['payload_bytes']} bytes ({stats['bits_used']} bits)")
    print(f"Capacity    : {stats['utilization_pct']:.4f}% of 512x512 RGB LSB space")
    print(f"Image PSNR  : {psnr:.2f} dB (values > 50 dB are visually indistinguishable)")

    # Step C: Receiver Tap-to-Decrypt
    extracted_bundle = extract_lsb(stego_file)
    decrypted_text, meta = verify_and_decrypt(extracted_bundle, bob, alice.sign_pub)

    print("\n--- RECEIVER DECRYPTION ---")
    print(f"Sender      : {meta['sender']}")
    print(f"Message ID  : {meta['msg_id']}")
    print(f"Plaintext   : {decrypted_text}")
    assert decrypted_text == secret_message, "Round-trip mismatch!"

    # Step D: Tamper Test (flip 1 LSB inside the payload region)
    t_img = Image.open(stego_file).convert("RGB")
    t_px = list(t_img.get_flattened_data())
    r, g, b = t_px[50]  # Pixel inside the embedded ciphertext region
    t_px[50] = (r ^ 1, g, b)
    t_img.putdata(t_px)
    t_img.save(tampered_file, format="PNG")

    print("\n--- TAMPER TEST (1-bit pixel flip) ---")
    try:
        bad_bundle = extract_lsb(tampered_file)
        verify_and_decrypt(bad_bundle, bob, alice.sign_pub)
        print("[!] FAIL: Tampered image was accepted!")
    except ValueError as err:
        print(f"[PASS] Rejected cleanly -> {err}")

    # Step E: 24h Cryptographic Erasure Test (Bob rotates & destroys old daily key)
    print("\n--- 24H KEY ROTATION (CRYPTOGRAPHIC ERASURE) TEST ---")
    bob.rotate_daily_key()
    try:
        verify_and_decrypt(extracted_bundle, bob, alice.sign_pub)
        print("[!] FAIL: Old message decrypted after key rotation!")
    except ValueError as err:
        print(f"[PASS] Old ciphertext permanently unreadable -> {err}")