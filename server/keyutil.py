"""
CHISEL key helpers (server side).
Must match the client implementation in chisel_core.py.
"""

import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

PREKEY_CONTEXT = b"CHISEL-v1-prekey"
FINGERPRINT_CONTEXT = b"CHISEL-v1-fingerprint"


def verify_prekey_signature(ed25519_pub: bytes, x25519_pub: bytes, signature: bytes) -> bool:
    """True if `signature` is the identity key's signature over the X25519 key."""
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(ed25519_pub).verify(
            signature, PREKEY_CONTEXT + x25519_pub
        )
        return True
    except (InvalidSignature, ValueError):
        return False


def fingerprint(ed25519_pub: bytes) -> str:
    """30-digit safety number (6 groups of 5) for comparing identity keys in person."""
    digest = hashlib.sha256(FINGERPRINT_CONTEXT + ed25519_pub).digest()
    groups = [int.from_bytes(digest[i : i + 5], "big") % 100_000 for i in range(0, 30, 5)]
    return " ".join(f"{g:05d}" for g in groups)
