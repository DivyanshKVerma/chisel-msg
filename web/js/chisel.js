// CHISEL device-side crypto + steganography — JavaScript port of chisel_core.py.
// Byte-for-byte compatible with the Python reference (see test_interop.py):
// same bundle layout, HKDF labels, ChaCha20 position stream and PNG pixels.
import { ed25519, x25519, chacha20, gcm, hkdf, sha256 } from "../vendor/libs.js";
import { decodePNG, encodePNG } from "./png.js";

const te = new TextEncoder();
const td = new TextDecoder();
const PREKEY_CONTEXT = te.encode("CHISEL-v1-prekey");
const FINGERPRINT_CONTEXT = te.encode("CHISEL-v1-fingerprint");
const AES_INFO = te.encode("CHISEL-v1-AES256GCM");
const STEGO_HEADER_INFO = te.encode("CHISEL-v2-stego-header");
const STEGO_BODY_INFO = te.encode("CHISEL-v2-stego-body");
const STEGO_MAX_FILL = 0.25;
const ZERO_NONCE = new Uint8Array(12);

// ── small byte helpers ────────────────────────────────────
export const toHex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
export const fromHex = (h) => {
  if (!/^([0-9a-f]{2})*$/i.test(h)) throw new Error("bad hex");
  return Uint8Array.from(h.match(/../g) || [], (x) => parseInt(x, 16));
};
const cat = (...parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
};
const u16 = (n) => new Uint8Array([(n >> 8) & 255, n & 255]);
const u32 = (n) => new Uint8Array([(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]);
const readU32 = (b, o) => ((b[o] << 24) >>> 0) + (b[o + 1] << 16) + (b[o + 2] << 8) + b[o + 3];
const randomBytes = (n) => crypto.getRandomValues(new Uint8Array(n));
/** RFC 4122 v4 UUID; crypto.randomUUID only exists on newer WebViews. */
const uuid4 = () => {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = randomBytes(16);
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
  const x = toHex(b);
  return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
};
export { uuid4 };
const equal = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

// ── 1. keys ───────────────────────────────────────────────
/** New device keys: long-term Ed25519 identity + daily X25519 encryption key. */
export function generateKeys(email) {
  const signPriv = randomBytes(32);
  const encPriv = x25519.utils.randomSecretKey();
  return {
    email,
    signPriv, signPub: ed25519.getPublicKey(signPriv),
    encPriv, encPub: x25519.getPublicKey(encPriv),
    encCreatedAt: Date.now(),
  };
}

/** Daily rotation: the old X25519 private key is discarded (cryptographic erasure). */
export function rotateDailyKey(keys) {
  const encPriv = x25519.utils.randomSecretKey();
  return { ...keys, encPriv, encPub: x25519.getPublicKey(encPriv), encCreatedAt: Date.now() };
}

export function keyUploadPayload(keys, resetIdentity = false) {
  return {
    x25519_pub_hex: toHex(keys.encPub),
    ed25519_pub_hex: toHex(keys.signPub),
    x25519_sig_hex: toHex(ed25519.sign(cat(PREKEY_CONTEXT, keys.encPub), keys.signPriv)),
    reset_identity: resetIdentity,
  };
}

/** 30-digit safety number (6 groups of 5), same as the server and Python. */
export function fingerprint(ed25519Pub) {
  const d = sha256(cat(FINGERPRINT_CONTEXT, ed25519Pub));
  const groups = [];
  for (let i = 0; i < 30; i += 5) {
    let v = 0n;
    for (let j = 0; j < 5; j++) v = (v << 8n) | BigInt(d[i + j]);
    groups.push(String(v % 100000n).padStart(5, "0"));
  }
  return groups.join(" ");
}

export class IdentityChangedError extends Error {
  constructor(email, oldPub, newPub) {
    super(`The safety number for ${email} changed.`);
    this.email = email; this.oldPub = oldPub; this.newPub = newPub;
  }
}

/**
 * Check a key-directory entry before using it: (1) trust-on-first-use pin of
 * the identity key, (2) identity key's signature over the X25519 key.
 * `pins` is { get(email) -> Uint8Array|undefined, set(email, pub) }.
 */
export async function loadVerifiedContact(entry, pins) {
  const ed = fromHex(entry.ed25519_pub_hex);
  const x = fromHex(entry.x25519_pub_hex);
  const sig = fromHex(entry.x25519_sig_hex);
  if (pins) {
    const pinned = await pins.get(entry.email);
    if (pinned && !equal(pinned, ed)) throw new IdentityChangedError(entry.email, pinned, ed);
    if (!pinned) await pins.set(entry.email, ed);
  }
  if (!ed25519.verify(sig, cat(PREKEY_CONTEXT, x), ed))
    throw new Error("Key directory tampered: encryption key is not signed by the identity key.");
  return { encPub: x, signPub: ed };
}

// ── 2. encryption (X25519 → HKDF → AES-256-GCM, Ed25519) ──
const aesKey = (shared, nonce) => hkdf(sha256, shared, nonce, AES_INFO, 32);

export function encryptAndSign(plaintext, sender, receiverId, receiverEncPub, ttlSeconds = 86400, ephPriv) {
  ephPriv = ephPriv || x25519.utils.randomSecretKey();
  const ephPub = x25519.getPublicKey(ephPriv);
  const nonce = randomBytes(12);
  const shared = x25519.getSharedSecret(ephPriv, receiverEncPub);
  const aad = te.encode(JSON.stringify({
    sender: sender.email,
    receiver: receiverId,
    msg_id: uuid4(),
    expiry: Math.floor(Date.now() / 1000) + ttlSeconds,
  }));
  const ct = gcm(aesKey(shared, nonce), nonce, aad).encrypt(te.encode(plaintext));
  const unsigned = cat(ephPub, nonce, u16(aad.length), aad, u32(ct.length), ct);
  return cat(unsigned, ed25519.sign(unsigned, sender.signPriv));
}

export function verifyAndDecrypt(bundle, receiver, senderSignPub) {
  if (bundle.length < 32 + 12 + 2 + 4 + 64) throw new Error("Corrupted payload: bundle too short.");
  const unsigned = bundle.subarray(0, bundle.length - 64);
  const sig = bundle.subarray(bundle.length - 64);
  if (!ed25519.verify(sig, unsigned, senderSignPub))
    throw new Error("TAMPER DETECTED: signature check failed.");
  let o = 0;
  const ephPub = unsigned.subarray(o, (o += 32));
  const nonce = unsigned.subarray(o, (o += 12));
  const aadLen = (unsigned[o] << 8) | unsigned[o + 1]; o += 2;
  const aad = unsigned.subarray(o, (o += aadLen));
  const ctLen = readU32(unsigned, o); o += 4;
  const ct = unsigned.subarray(o, o + ctLen);
  const meta = JSON.parse(td.decode(aad));
  if (meta.receiver !== receiver.email) throw new Error("This message was not addressed to you.");
  if (Date.now() / 1000 > meta.expiry) throw new Error("Message expired (past its 24-hour life).");
  const shared = x25519.getSharedSecret(receiver.encPriv, ephPub);
  let pt;
  try { pt = gcm(aesKey(shared, nonce), nonce, aad).decrypt(ct); }
  catch { throw new Error("Decryption failed: wrong or rotated key, or corrupted data."); }
  return { text: td.decode(pt), meta };
}

// ── 3. keyed, scattered steganography (v2) ────────────────
function* positions(key, total, used) {
  const limit = 2 ** 32 - (2 ** 32 % total); // rejection sampling → no modulo bias
  const zeros = new Uint8Array(4096);
  for (let counter = 0; ; counter += 64) {   // 4096 bytes = 64 ChaCha20 blocks
    const block = chacha20(key, ZERO_NONCE, zeros, undefined, counter);
    for (let i = 0; i < 4096; i += 4) {
      const v = readU32(block, i);
      if (v >= limit) continue;
      const idx = v % total;
      if (!used.has(idx)) { used.add(idx); yield idx; }
    }
  }
}
const take = (gen, n) => { const out = new Array(n); for (let i = 0; i < n; i++) out[i] = gen.next().value; return out; };
const bitsOf = (bytes) => { const b = []; for (const x of bytes) for (let i = 7; i >= 0; i--) b.push((x >> i) & 1); return b; };
const bytesOf = (bits) => { const out = new Uint8Array(bits.length >> 3); for (let i = 0; i < out.length; i++) { let v = 0; for (let j = 0; j < 8; j++) v = (v << 1) | bits[i * 8 + j]; out[i] = v; } return out; };
const headerKey = (receiverXPub) => hkdf(sha256, receiverXPub, undefined, STEGO_HEADER_INFO, 32);
const bodyKey = (shared, ephPub) => hkdf(sha256, shared, ephPub, STEGO_BODY_INFO, 32);

function writeBits(ch, pos, bits) {
  const coin = randomBytes(pos.length);
  let changed = 0;
  for (let i = 0; i < pos.length; i++) {
    let v = ch[pos[i]];
    if ((v & 1) !== bits[i]) {
      v = v === 0 ? 1 : v === 255 ? 254 : v + ((coin[i] & 1) ? 1 : -1); // LSB matching
      ch[pos[i]] = v;
      changed++;
    }
  }
  return changed;
}

/** Encrypt + sign, then hide at keyed positions in a PNG cover. Returns { png, stats }. */
export async function sealIntoImage(plaintext, sender, receiverId, receiverEncPub, coverPng) {
  const ephPriv = x25519.utils.randomSecretKey();
  const bundle = encryptAndSign(plaintext, sender, receiverId, receiverEncPub, 86400, ephPriv);
  const ephPub = bundle.subarray(0, 32), rest = bundle.subarray(32);
  const shared = x25519.getSharedSecret(ephPriv, receiverEncPub);
  const { width, height, rgb } = await decodePNG(coverPng);
  const ch = rgb.slice();
  const total = ch.length;
  const body = cat(u32(rest.length), rest);
  if (256 + body.length * 8 > total * STEGO_MAX_FILL) throw new Error("Message too long for this image.");
  const header = ephPub.slice();
  header[31] |= (randomBytes(1)[0] & 1) << 7; // X25519 keys never set bit 255 — randomise it
  const used = new Set();
  const hdrPos = take(positions(headerKey(receiverEncPub), total, used), 256);
  const bodyPos = take(positions(bodyKey(shared, ephPub), total, used), body.length * 8);
  const changed = writeBits(ch, hdrPos, bitsOf(header)) + writeBits(ch, bodyPos, bitsOf(body));
  const bitsUsed = 256 + body.length * 8;
  return {
    png: await encodePNG(width, height, ch),
    stats: { payloadBytes: bundle.length, bitsUsed, capacityPct: (bitsUsed / total) * 100, channelsChanged: changed },
  };
}

const NOT_FOUND = "No CHISEL message for your key in this image (sent to someone else, or your daily key has rotated since).";

function locate(ch, receiver) {
  const total = ch.length, used = new Set();
  const hdrPos = take(positions(headerKey(receiver.encPub), total, used), 256);
  const eph = bytesOf(hdrPos.map((i) => ch[i] & 1));
  eph[31] &= 0x7f;
  let shared;
  try { shared = x25519.getSharedSecret(receiver.encPriv, eph); } catch { throw new Error(NOT_FOUND); }
  const gen = positions(bodyKey(shared, eph), total, used);
  const lenPos = take(gen, 32);
  const restLen = readU32(bytesOf(lenPos.map((i) => ch[i] & 1)), 0);
  if (restLen < 12 + 2 + 4 + 16 + 64 || restLen > (total * STEGO_MAX_FILL) / 8) throw new Error(NOT_FOUND);
  const restPos = take(gen, restLen * 8);
  return { eph, hdrPos, lenPos, restPos };
}

/** Find, verify and decrypt a message hidden with sealIntoImage. Returns { text, meta }. */
export async function openFromImage(stegoPng, receiver, senderSignPub) {
  const { rgb } = await decodePNG(stegoPng);
  const { eph, restPos } = locate(rgb, receiver);
  const rest = bytesOf(restPos.map((i) => rgb[i] & 1));
  return verifyAndDecrypt(cat(eph, rest), receiver, senderSignPub);
}

/** Receiver-only: channel indices that carry the message (for tests / visualisation). */
export async function payloadPositions(stegoPng, receiver) {
  const { rgb } = await decodePNG(stegoPng);
  const { hdrPos, lenPos, restPos } = locate(rgb, receiver);
  return { header: hdrPos, body: [...lenPos, ...restPos] }; // same order as Python
}
