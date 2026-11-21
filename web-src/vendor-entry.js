// Third-party code the app needs, bundled into web/vendor/libs.js so nothing
// loads from a CDN and the Android app works offline from its own files.
//   @noble/*  — audited crypto (Ed25519, X25519, AES-GCM, ChaCha20, HKDF, SHA-256)
//   fflate    — zlib inflate/deflate for exact PNG encoding (no CompressionStream needed)
export { ed25519, x25519 } from "@noble/curves/ed25519.js";
export { chacha20 } from "@noble/ciphers/chacha.js";
export { gcm } from "@noble/ciphers/aes.js";
export { hkdf } from "@noble/hashes/hkdf.js";
export { sha256 } from "@noble/hashes/sha2.js";
export { zlibSync, unzlibSync } from "fflate";
