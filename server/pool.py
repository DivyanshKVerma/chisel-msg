"""
CHISEL Cover-Image Pool Manager
Fetches AI-generated 512×512 PNGs from Pollinations.ai and stores them in Postgres.
"""

import asyncio
import io
import logging
import random
import urllib.parse

import httpx
from PIL import Image
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import async_session
from .models import CoverImage

log = logging.getLogger("chisel.pool")

# Random, high-texture prompts completely unrelated to user messages.
# 100 subjects x 10 styles x a random seed, so chats rarely show repeats.
SUBJECTS = [
    "misty pine forest at dawn",
    "geometric brutalist concrete architecture",
    "aerial view of ocean waves hitting dark rocks",
    "vintage botanical illustration of ferns",
    "macro shot of colourful oil paint swirls",
    "quiet rain-soaked street in Tokyo at night",
    "sand dunes under twilight sky",
    "abstract stained glass mosaic pattern",
    "close up of weathered rusty metal texture",
    "colourful hot air balloons over green fields",
    "northern lights over a frozen lake",
    "old European cobblestone alley in golden hour",
    "underwater coral reef with tropical fish",
    "dense fog rolling through a mountain valley",
    "antique map with ink illustrations",
    "terraced rice fields after rain",
    "autumn maple leaves floating on a pond",
    "snow-covered alpine village at dusk",
    "lavender fields stretching to the horizon",
    "desert canyon with layered red rock walls",
    "bamboo grove with shafts of sunlight",
    "tidal pools full of starfish and anemones",
    "glacier ice cave with blue light",
    "volcanic black sand beach with sea stacks",
    "cherry blossom canopy over a stone path",
    "moss-covered boulders in a temperate rainforest",
    "wheat field swaying under storm clouds",
    "frozen waterfall in a winter forest",
    "mangrove roots in clear shallow water",
    "salt flats reflecting a pastel sky",
    "aerial view of winding river deltas",
    "cliffside lighthouse in crashing surf",
    "sunflower field under a bright summer sky",
    "moonlit pine trees over a still lake",
    "tropical waterfall in a jungle gorge",
    "rolling green hills with dry stone walls",
    "macro shot of frost crystals on a leaf",
    "macro shot of a peacock feather",
    "honeycomb with golden dripping honey",
    "close up of tree bark with lichen",
    "pile of polished river pebbles",
    "macro shot of soap bubble iridescence",
    "cracked dry earth in a drought",
    "wave patterns in wind-blown sand",
    "close up of woven indigo textile",
    "ripples on dark water with reflections",
    "marbled paper in swirling colours",
    "peeling layers of painted wood",
    "macro shot of a butterfly wing",
    "colourful spice market bowls from above",
    "heap of autumn leaves in warm tones",
    "pattern of terracotta roof tiles",
    "Moroccan zellige tile mosaic",
    "Art Deco building facade at sunset",
    "Gothic cathedral interior with rib vaults",
    "spiral staircase seen from above",
    "Venetian canal with gondolas at dawn",
    "Greek island village with white houses and blue domes",
    "Japanese zen garden with raked gravel",
    "abandoned greenhouse overgrown with plants",
    "old library with towering wooden shelves",
    "lantern-lit night market alley",
    "industrial harbour with stacked containers",
    "glass skyscrapers reflecting clouds",
    "wooden pier stretching into a calm sea",
    "cobbled courtyard with ivy-covered walls",
    "windmills on a Dutch canal",
    "red telephone box on a rainy street",
    "bustling train station under a glass roof",
    "desert oasis with palm trees",
    "Saturn rising over an alien landscape",
    "spiral galaxy in deep space",
    "nebula clouds in purple and teal",
    "starry night sky over a desert",
    "lightning storm over the open sea",
    "double rainbow over green moorland",
    "solar eclipse over mountain peaks",
    "meteor shower above snowy peaks",
    "aurora over a fjord village",
    "thunderhead clouds at sunset",
    "herd of wild horses on a misty plain",
    "flock of flamingos in a pink lagoon",
    "fox in a snowy birch forest",
    "jellyfish glowing in dark water",
    "koi fish in a lily pond",
    "owl perched in an autumn tree",
    "sea turtle gliding over a reef",
    "humpback whale breaching at sunrise",
    "mountain goats on a rocky ridge",
    "hummingbird beside tropical flowers",
    "still life of fruit on a wooden table",
    "watercolour painting of a seaside town",
    "ink wash painting of misty mountains",
    "pointillist painting of a summer garden",
    "woodblock print of ocean waves",
    "mosaic of a Mediterranean courtyard",
    "pastel sketch of a harbour at dawn",
    "impressionist painting of a water lily pond",
    "art nouveau floral poster pattern",
    "papercut layered landscape of hills",
]

STYLES = [
    "soft natural lighting, high detail",
    "film grain photography, muted tones",
    "minimalist oil painting texture",
    "crisp architectural photography",
    "cinematic widescreen, warm grading",
    "vivid colours, sharp focus",
    "dreamy pastel palette, soft focus",
    "dramatic chiaroscuro lighting",
    "golden hour glow, rich textures",
    "high contrast, deep shadows",
]


def _random_prompt() -> tuple[str, int]:
    prompt = f"{random.choice(SUBJECTS)}, {random.choice(STYLES)}"
    seed = random.randint(1, 999_999_999)
    return prompt, seed


async def fetch_cover_from_pollinations(api_key: str) -> bytes:
    """
    Call Pollinations.ai to generate a 512×512 image and return lossless PNG bytes.
    """
    prompt, seed = _random_prompt()
    encoded = urllib.parse.quote(prompt)
    url = (
        f"https://gen.pollinations.ai/image/{encoded}"
        f"?width=512&height=512&model=flux&seed={seed}&nologo=true"
    )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    log.info("Fetching cover: %s (seed=%d)", prompt, seed)

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()

    # Convert whatever the API returns to exact lossless 512×512 RGB PNG
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    if img.size != (512, 512):
        img = img.resize((512, 512), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def get_unused_count(db: AsyncSession) -> int:
    """Count unused cover images in the pool."""
    result = await db.scalar(
        select(func.count()).select_from(CoverImage).where(CoverImage.used == False)
    )
    return result or 0


async def get_total_count(db: AsyncSession) -> int:
    """Count all cover images (covers are deleted once handed out)."""
    result = await db.scalar(select(func.count()).select_from(CoverImage))
    return result or 0


async def refill_pool(db: AsyncSession, count: int) -> int:
    """
    Generate `count` new cover images from Pollinations and store them in the DB.
    Returns how many were successfully added.
    """
    api_key = settings.POLLINATIONS_API_KEY
    added = 0

    for i in range(count):
        try:
            png_bytes = await fetch_cover_from_pollinations(api_key)
            cover = CoverImage(image_data=png_bytes)
            db.add(cover)
            await db.commit()
            added += 1
            log.info("[Pool] Added cover image %d/%d (%d bytes)", i + 1, count, len(png_bytes))
        except Exception as e:
            log.warning("[Pool] Failed to generate image %d/%d: %s: %s", i + 1, count, type(e).__name__, e)
            continue

    return added


async def pop_cover(db: AsyncSession) -> bytes | None:
    """
    Atomically take one cover out of the pool and DELETE it from the server.

    Why delete: if the server kept the original cover, it could diff it against
    the stego PNG later and see exactly which LSBs carry a payload. Deleting it
    also guarantees no cover is ever handed to two senders.

    The DELETE ... WHERE id = ? RETURNING is atomic, so two concurrent requests
    can never receive the same image; the loser simply retries with another row.
    """
    for _ in range(5):
        cover_id = await db.scalar(
            select(CoverImage.id).where(CoverImage.used == False).limit(1)
        )
        if cover_id is None:
            return None
        data = await db.scalar(
            delete(CoverImage)
            .where(CoverImage.id == cover_id)
            .returning(CoverImage.image_data)
        )
        await db.commit()
        if data is not None:
            return data
    return None


# ── Buffer management ─────────────────────────────────────
# One refill at a time (single-flight); extra triggers while one runs are ignored.
_refill_lock = asyncio.Lock()
_background: set[asyncio.Task] = set()


def refill_in_progress() -> bool:
    return _refill_lock.locked()


async def ensure_pool() -> int:
    """
    If the buffer has POOL_REFILL_THRESHOLD or fewer covers left, generate
    enough new ones (on this server, via Pollinations) to get back to
    POOL_TARGET_SIZE. Returns how many were added.
    """
    if _refill_lock.locked():
        return 0
    async with _refill_lock:
        async with async_session() as db:
            unused = await get_unused_count(db)
            if unused > settings.POOL_REFILL_THRESHOLD:
                return 0
            need = settings.POOL_TARGET_SIZE - unused
            log.info(
                "[Pool] %d cover(s) left (refill at <= %d) - generating %d to refill to %d",
                unused, settings.POOL_REFILL_THRESHOLD, need, settings.POOL_TARGET_SIZE,
            )
            added = await refill_pool(db, need)
            log.info("[Pool] Refill done: +%d, buffer now %d", added, unused + added)
            return added


def trigger_refill() -> None:
    """Fire-and-forget refill check (called right after a cover is taken)."""
    task = asyncio.create_task(ensure_pool(), name="pool-refill-trigger")
    _background.add(task)          # keep a reference so it isn't garbage-collected
    task.add_done_callback(_background.discard)
