import io
import os
import random
import time
import urllib.parse
from datetime import datetime
import requests
from PIL import Image

import chisel_core  # Uses your Phase 1 module
from dotenv import load_dotenv
load_dotenv()

POOL_DIR = "cover_pool"
POOL_SIZE = 5  # Increase to 50-100 when populating your demo pool

# Random, high-texture prompts completely unrelated to user messages
SUBJECTS = [
    "misty pine forest at dawn",
    "geometric brutalist concrete architecture",
    "aerial view of ocean waves hitting dark rocks",
    "vintage botanical illustration of ferns",
    "macro shot of colourful oil paint swirls",
    "quiet rain-soaked street in Tokyo at night",
    "sand dunes under twilight sky",
    "abstract stained glass mosaic pattern",
]
STYLES = [
    "soft natural lighting, high detail",
    "film grain photography, muted tones",
    "minimalist oil painting texture",
    "crisp architectural photography",
]


def build_random_prompt() -> tuple[str, int]:
    prompt = f"{random.choice(SUBJECTS)}, {random.choice(STYLES)}"
    seed = random.randint(1, 999_999_999)
    return prompt, seed


def fetch_and_save_cover(index: int, api_key: str | None = None) -> str:
    os.makedirs(POOL_DIR, exist_ok=True)
    prompt, seed = build_random_prompt()
    encoded_prompt = urllib.parse.quote(prompt)

    url = (
    f"https://gen.pollinations.ai/image/{encoded_prompt}"
    f"?width=512&height=512&model=flux&seed={seed}&nologo=true"
    )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    print(f"[{index}] Fetching: {prompt} (seed={seed})...")
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()

    # Convert whatever format the API returns (JPEG/WebP/PNG) to exact lossless 512x512 RGB PNG
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    if img.size != (512, 512):
        img = img.resize((512, 512), Image.Resampling.LANCZOS)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(POOL_DIR, f"cover_{timestamp}_{seed}.png")
    img.save(filepath, format="PNG")
    return filepath


def populate_pool(count: int = POOL_SIZE) -> list[str]:
    api_key = os.getenv("POLLINATIONS_API_KEY", "").strip()
    if not api_key or not api_key.startswith("sk_"):
        raise SystemExit("[!] Missing or invalid key. Set a valid 'sk_...' key in .env")
    saved_files = []

    for i in range(1, count + 1):
        try:
            path = fetch_and_save_cover(i, api_key=api_key)
            saved_files.append(path)
            print(f"    -> Saved lossless 512x512 PNG: {path}")
            time.sleep(1.5)  # Polite delay to avoid rate limits
        except Exception as e:
            print(f"    [!] Skipped image {i} due to error: {e}")

    return saved_files


def pop_cover_image() -> str:
    """Helper your backend will call to grab an unused cover image from the pool."""
    if not os.path.isdir(POOL_DIR):
        raise FileNotFoundError(f"Pool directory '{POOL_DIR}' not found. Run populate_pool() first.")
    pngs = [f for f in os.listdir(POOL_DIR) if f.lower().endswith(".png")]
    if not pngs:
        raise RuntimeError("Cover image pool is empty. Refill it before sending messages.")
    return os.path.join(POOL_DIR, random.choice(pngs))


if __name__ == "__main__":
    print(f"=== PHASE 2: GENERATING {POOL_SIZE} AI COVER IMAGES ===")
    files = populate_pool(POOL_SIZE)

    if not files:
        raise SystemExit("[!] No images were downloaded. Check internet/API availability.")

    # Integration test: run Phase 1 CHISEL pipeline on a real AI-generated cover PNG
    test_cover = files[0]
    test_stego = "ai_stego_test.png"

    alice = chisel_core.UserKeys("alice@example.com")
    bob = chisel_core.UserKeys("bob@example.com")
    msg = "Phase 2 integration check: real AI cover image carrying AES-256-GCM + Ed25519 payload."

    stats = chisel_core.seal_into_image(msg, alice, bob.user_id, bob.enc_pub, test_cover, test_stego)
    psnr = chisel_core.calculate_psnr(test_cover, test_stego)

    recovered, meta = chisel_core.open_from_image(test_stego, bob, alice.sign_pub)

    print("\n=== PHASE 1 + PHASE 2 INTEGRATION CHECK ===")
    print(f"Cover Image : {test_cover}")
    print(f"Stego Output: {test_stego}")
    print(f"Payload     : {stats['payload_bytes']} bytes ({stats['utilization_pct']:.4f}% capacity)")
    print(f"Real PSNR   : {psnr:.2f} dB")
    print(f"Decrypted   : {recovered}")
    assert recovered == msg, "Integration round-trip failed!"
    print("[PASS] Real AI PNG carried and returned the encrypted payload intact.")