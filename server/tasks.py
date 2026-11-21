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
from .pool import ensure_pool

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
    """
    Fill the cover buffer at startup, then re-check every few minutes as a
    safety net (e.g. if Pollinations was down during an earlier refill).
    The main trigger is immediate: every cover taken calls trigger_refill().
    """
    while True:
        try:
            await ensure_pool()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("[Pool] Refill error: %s", e)
        await asyncio.sleep(settings.POOL_CHECK_INTERVAL_SECONDS)
