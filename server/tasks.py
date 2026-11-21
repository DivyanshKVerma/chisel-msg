"""
CHISEL Background Tasks
Async loops that run alongside the FastAPI server:
  1. Expired-message cleanup (hourly)
  2. Cover-image pool refill  (every 30 min)
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from .config import settings
from .database import async_session
from .models import OTP, CoverImage, Message
from .pool import refill_pool

log = logging.getLogger("chisel.tasks")


async def periodic_cleanup():
    """Delete expired messages and spent OTPs from the database every hour."""
    while True:
        try:
            async with async_session() as db:
                result = await db.execute(
                    delete(Message).where(Message.expires_at < datetime.now(timezone.utc))
                )
                count = result.rowcount
                # Expired or used OTP hashes have no further purpose — drop them
                otp_result = await db.execute(
                    delete(OTP).where(
                        (OTP.expires_at < datetime.now(timezone.utc)) | (OTP.used == True)
                    )
                )
                await db.commit()
                if count:
                    log.info("[Cleanup] Deleted %d expired message(s).", count)
                if otp_result.rowcount:
                    log.info("[Cleanup] Deleted %d spent OTP(s).", otp_result.rowcount)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("[Cleanup] Error: %s", e)

        await asyncio.sleep(settings.TTL_CLEANUP_INTERVAL_SECONDS)


async def periodic_pool_refill():
    """Check the cover-image pool and refill from Pollinations if it's low."""
    while True:
        try:
            async with async_session() as db:
                unused = await db.scalar(
                    select(func.count())
                    .select_from(CoverImage)
                    .where(CoverImage.used == False)
                )
                unused = unused or 0

                if unused < settings.POOL_MIN_SIZE:
                    need = settings.POOL_REFILL_COUNT
                    log.info(
                        "[Pool] Only %d unused covers (min=%d). Refilling %d...",
                        unused, settings.POOL_MIN_SIZE, need,
                    )
                    added = await refill_pool(db, need)
                    log.info("[Pool] Added %d new cover images.", added)
                else:
                    log.debug("[Pool] %d unused covers — no refill needed.", unused)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("[Pool] Refill error: %s", e)

        await asyncio.sleep(settings.POOL_REFILL_INTERVAL_SECONDS)
