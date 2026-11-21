// Exact PNG decode/encode for 8-bit RGB/RGBA, non-interlaced images.
// Steganography needs the raw pixel values untouched, so this avoids <canvas>
// (which can apply colour management / premultiplied alpha). zlib comes from
// the bundled fflate library, so it works on any WebView (no CompressionStream).
import { zlibSync, unzlibSync } from "../vendor/libs.js";

const SIG = [137, 80, 78, 71, 13, 10, 26, 10];

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const inflate = async (b) => unzlibSync(b);
const deflate = async (b) => zlibSync(b, { level: 6 });

function paeth(a, b, c) {
  const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

/** Decode a PNG. Returns { width, height, rgb } with rgb = Uint8Array(w*h*3). */
export async function decodePNG(bytes) {
  bytes = new Uint8Array(bytes);
  if (!SIG.every((v, i) => bytes[i] === v)) throw new Error("Not a PNG image.");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let pos = 8, width = 0, height = 0, colorType = -1, interlace = 0;
  const idat = [];
  while (pos < bytes.length) {
    const len = view.getUint32(pos);
    const type = String.fromCharCode(...bytes.subarray(pos + 4, pos + 8));
    const data = bytes.subarray(pos + 8, pos + 8 + len);
    if (type === "IHDR") {
      width = view.getUint32(pos + 8);
      height = view.getUint32(pos + 12);
      const depth = data[8];
      colorType = data[9];
      interlace = data[12];
      if (depth !== 8 || (colorType !== 2 && colorType !== 6) || interlace !== 0)
        throw new Error("Unsupported PNG (needs 8-bit RGB/RGBA, non-interlaced).");
    } else if (type === "IDAT") idat.push(data);
    else if (type === "IEND") break;
    pos += 12 + len;
  }
  const bpp = colorType === 6 ? 4 : 3;
  const stride = width * bpp;
  const raw = await inflate(concat(idat));
  if (raw.length < (stride + 1) * height) throw new Error("Truncated PNG data.");
  const px = new Uint8Array(stride * height);
  for (let y = 0; y < height; y++) {
    const f = raw[y * (stride + 1)];
    const src = y * (stride + 1) + 1, dst = y * stride, prev = dst - stride;
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? px[dst + x - bpp] : 0;
      const b = y ? px[prev + x] : 0;
      const c = y && x >= bpp ? px[prev + x - bpp] : 0;
      let v = raw[src + x];
      if (f === 1) v += a;
      else if (f === 2) v += b;
      else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) v += paeth(a, b, c);
      else if (f !== 0) throw new Error("Bad PNG filter.");
      px[dst + x] = v & 255;
    }
  }
  if (bpp === 3) return { width, height, rgb: px };
  const rgb = new Uint8Array(width * height * 3); // drop alpha, same as PIL .convert("RGB")
  for (let i = 0, j = 0; i < px.length; i += 4, j += 3) {
    rgb[j] = px[i]; rgb[j + 1] = px[i + 1]; rgb[j + 2] = px[i + 2];
  }
  return { width, height, rgb };
}

/** Encode RGB pixels as a lossless 8-bit RGB PNG (per-row adaptive filters). */
export async function encodePNG(width, height, rgb) {
  const stride = width * 3;
  const raw = new Uint8Array((stride + 1) * height);
  const cand = Array.from({ length: 5 }, () => new Uint8Array(stride));
  for (let y = 0; y < height; y++) {
    const row = y * stride, prev = row - stride;
    let best = 0, bestScore = Infinity;
    for (let f = 0; f < 5; f++) {
      const out = cand[f];
      let score = 0;
      for (let x = 0; x < stride; x++) {
        const a = x >= 3 ? rgb[row + x - 3] : 0;
        const b = y ? rgb[prev + x] : 0;
        const c = y && x >= 3 ? rgb[prev + x - 3] : 0;
        const v = rgb[row + x];
        const p = f === 0 ? 0 : f === 1 ? a : f === 2 ? b : f === 3 ? (a + b) >> 1 : paeth(a, b, c);
        const d = (v - p) & 255;
        out[x] = d;
        score += d < 128 ? d : 256 - d;
      }
      if (score < bestScore) { bestScore = score; best = f; }
    }
    raw[y * (stride + 1)] = best;
    raw.set(cand[best], y * (stride + 1) + 1);
  }
  const ihdr = new Uint8Array(13);
  const hv = new DataView(ihdr.buffer);
  hv.setUint32(0, width); hv.setUint32(4, height);
  ihdr.set([8, 2, 0, 0, 0], 8); // depth 8, colour type 2 (RGB), deflate, filter 0, no interlace
  return concat([new Uint8Array(SIG), chunk("IHDR", ihdr), chunk("IDAT", await deflate(raw)), chunk("IEND", new Uint8Array(0))]);
}

function chunk(type, data) {
  const out = new Uint8Array(12 + data.length);
  const v = new DataView(out.buffer);
  v.setUint32(0, data.length);
  for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
  out.set(data, 8);
  v.setUint32(8 + data.length, crc32(out.subarray(4, 8 + data.length)));
  return out;
}

function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
