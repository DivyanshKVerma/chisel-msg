"""
CHISEL FastAPI Server
=====================
REST API for the CHISEL encrypted steganographic messaging system.

Endpoints
---------
Auth:
    POST /api/register          — Send OTP to email (demo: returns OTP directly)
    POST /api/verify-otp        — Verify OTP → create user → return JWT
                                  (both rate-limited per IP; OTPs hashed, 5 tries max)

Keys:
    PUT  /api/keys              — Upload signed device public keys (requires auth)
    GET  /api/users/{email}/public-keys  — Look up a user's public keys (requires auth)

Cover Images:
    GET  /api/cover-image       — Pop a 512×512 PNG from the pool (requires auth)

Messages:
    POST /api/messages          — Upload stego PNG to a receiver (requires auth)
    GET  /api/messages/inbox    — List incoming messages (requires auth)
    GET  /api/messages/{id}/image  — Download a stego PNG (requires auth)
    DELETE /api/messages/{id}   — Delete a message (requires auth)

Admin / Debug:
    GET  /api/health            — Health check
    GET  /api/pool-status       — Cover pool stats (requires auth)
    POST /api/admin/seed-pool   — Manually trigger pool refill (requires admin)
"""

import asyncio
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .auth import (
    create_token,
    generate_otp,
    get_current_user,
    hash_otp,
    otp_matches,
    rate_limit_auth,
    require_admin,
)
from .config import DEFAULT_SECRET, settings
from .database import get_db, init_db
from .emailer import EmailDeliveryError, send_otp_email
from .keyutil import fingerprint, verify_prekey_signature
from .models import CoverImage, Message, OTP, User
from .pool import get_total_count, get_unused_count, pop_cover, refill_pool
from .schemas import (
    HealthResponse,
    InboxResponse,
    MessageMeta,
    PoolStatusResponse,
    PublicKeysResponse,
    RegisterRequest,
    SendMessageResponse,
    UploadKeysRequest,
    VerifyOTPRequest,
    VerifyOTPResponse,
)
from .tasks import periodic_cleanup, periodic_pool_refill

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)-18s  %(message)s")
log = logging.getLogger("chisel.api")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_email_adapter = TypeAdapter(EmailStr)


def _normalise_email(raw: str) -> str:
    """Validate and lowercase an email so lookups are case-insensitive."""
    try:
        return _email_adapter.validate_python(raw.strip()).lower()
    except ValidationError:
        raise HTTPException(status_code=422, detail="Invalid email address")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APP LIFESPAN (startup / shutdown)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────
    settings.check_production_safety()  # refuses to boot with demo settings in prod
    if settings.SECRET_KEY == DEFAULT_SECRET:
        log.warning("Using the default SECRET_KEY — fine for local dev, NEVER for deployment.")
    if settings.DEMO_RETURN_OTP:
        log.warning("DEMO_RETURN_OTP is on — OTPs are returned in API responses.")
    log.info("Initialising database...")
    await init_db()
    log.info("Starting background tasks...")

    bg_tasks = [
        asyncio.create_task(periodic_cleanup(), name="ttl-cleanup"),
        asyncio.create_task(periodic_pool_refill(), name="pool-refill"),
    ]

    yield

    # ── Shutdown ──────────────────────────────────────────
    log.info("Stopping background tasks...")
    for t in bg_tasks:
        t.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)
    log.info("CHISEL server stopped.")


app = FastAPI(
    title="CHISEL API",
    description="Cryptographic Hybrid Image-Steganographic Ephemeral Layer — Backend",
    version="1.1.0",
    lifespan=lifespan,
    # Hide the interactive docs in production
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Origins come from CORS_ORIGINS. Auth uses Bearer headers, not cookies, so
# credentials are not needed (and "*" + credentials is rejected by browsers).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. AUTH ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/api/register", tags=["Auth"], dependencies=[Depends(rate_limit_auth)])
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Generate a 6-digit OTP for the given email.
    - Codes come from the OS CSPRNG and only their HMAC is stored.
    - A new code invalidates any older unused code for the same email.
    - One code per email per OTP_RESEND_COOLDOWN_SECONDS.
    The OTP is emailed via Brevo; DEMO_RETURN_OTP also returns it for the viva.
    """
    email = req.email.lower()
    now = datetime.now(timezone.utc)

    recent = await db.scalar(
        select(OTP.id).where(
            OTP.email == email,
            OTP.created_at > now - timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS),
        )
    )
    if recent:
        raise HTTPException(
            status_code=429,
            detail=f"An OTP was sent recently. Wait {settings.OTP_RESEND_COOLDOWN_SECONDS}s before requesting another.",
        )

    # Burn any older live codes so only the newest one works
    await db.execute(
        update(OTP).where(OTP.email == email, OTP.used == False).values(used=True)
    )

    code = generate_otp()
    otp = OTP(
        email=email,
        code_hash=hash_otp(email, code),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.OTP_EXPIRE_SECONDS),
    )
    db.add(otp)
    await db.commit()

    try:
        await send_otp_email(email, code)
    except EmailDeliveryError as e:
        # Remove the undeliverable code so the user can retry without waiting
        # for the resend cooldown.
        await db.delete(otp)
        await db.commit()
        log.error("[Auth] OTP email to %s failed: %s", email, e)
        raise HTTPException(
            status_code=502,
            detail="Could not send the verification email. Please try again shortly.",
        )

    log.info("[Auth] OTP issued for %s", email)
    body = {"message": "OTP generated. Check your email."}
    if settings.DEMO_RETURN_OTP:
        body["otp_for_demo"] = code
        body["note"] = "Demo mode only — disabled in production; the OTP would be emailed."
    return body


@app.post(
    "/api/verify-otp",
    response_model=VerifyOTPResponse,
    tags=["Auth"],
    dependencies=[Depends(rate_limit_auth)],
)
async def verify_otp(req: VerifyOTPRequest, db: AsyncSession = Depends(get_db)):
    """
    Verify an OTP. If valid, create user (or find existing) and return a JWT.
    Each code allows OTP_MAX_ATTEMPTS wrong guesses, then it is burned.
    """
    email = req.email.lower()
    otp = (
        await db.execute(
            select(OTP)
            .where(
                OTP.email == email,
                OTP.used == False,
                OTP.expires_at > datetime.now(timezone.utc),
            )
            .order_by(OTP.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    if not otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    if not otp_matches(otp.code_hash, email, req.code.strip()):
        otp.attempts += 1
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            otp.used = True
            await db.commit()
            log.warning("[Auth] OTP for %s burned after %d wrong attempts", email, otp.attempts)
            raise HTTPException(
                status_code=429,
                detail="Too many wrong attempts. Request a new OTP.",
            )
        await db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    otp.used = True

    # Find or create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if not user:
        user = User(email=email)
        db.add(user)

    await db.commit()
    await db.refresh(user)

    token = create_token(user.id, user.email)
    log.info("[Auth] User verified: %s (id=%s)", user.email, user.id)
    return VerifyOTPResponse(token=token, user_id=user.id, email=user.email)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. KEY ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.put("/api/keys", tags=["Keys"])
async def upload_keys(
    req: UploadKeysRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload (or rotate) the user's public keys. Private keys NEVER leave the device.

    - The X25519 key must be signed by the Ed25519 identity key, so a client
      can check that the encryption key really belongs to that identity.
    - The Ed25519 identity key is pinned on first upload. Daily rotation only
      replaces the X25519 key; an attempt to change the identity key is refused.
    """
    try:
        x25519_bytes = bytes.fromhex(req.x25519_pub_hex)
        ed25519_bytes = bytes.fromhex(req.ed25519_pub_hex)
        sig_bytes = bytes.fromhex(req.x25519_sig_hex)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid hex encoding")

    if len(x25519_bytes) != 32 or len(ed25519_bytes) != 32:
        raise HTTPException(status_code=400, detail="Keys must be exactly 32 bytes each")
    if len(sig_bytes) != 64:
        raise HTTPException(status_code=400, detail="Signature must be exactly 64 bytes")

    if user.ed25519_pub and user.ed25519_pub != ed25519_bytes:
        raise HTTPException(
            status_code=409,
            detail="Identity key is pinned and cannot be replaced. Only the X25519 key rotates.",
        )

    if not verify_prekey_signature(ed25519_bytes, x25519_bytes, sig_bytes):
        raise HTTPException(
            status_code=400,
            detail="X25519 key signature does not verify under the Ed25519 identity key",
        )

    user.x25519_pub = x25519_bytes
    user.x25519_sig = sig_bytes
    user.ed25519_pub = ed25519_bytes
    user.key_uploaded_at = datetime.now(timezone.utc)
    await db.commit()

    log.info("[Keys] Public keys updated for %s", user.email)
    return {
        "message": "Public keys uploaded successfully",
        "fingerprint": fingerprint(ed25519_bytes),
    }


@app.get("/api/users/{email}/public-keys", response_model=PublicKeysResponse, tags=["Keys"])
async def get_public_keys(
    email: str,
    _caller: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Look up a user's public keys by email (signed-in users only).
    Clients must verify x25519_sig against ed25519_pub, and should pin
    ed25519_pub / compare the fingerprint in person (trust on first use).
    """
    email = _normalise_email(email)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()

    if not user or not user.x25519_pub or not user.ed25519_pub or not user.x25519_sig:
        # Same answer for "no such user" and "no keys yet" to limit enumeration
        raise HTTPException(status_code=404, detail="No keys available for this user")

    return PublicKeysResponse(
        user_id=user.id,
        email=user.email,
        x25519_pub_hex=user.x25519_pub.hex(),
        x25519_sig_hex=user.x25519_sig.hex(),
        ed25519_pub_hex=user.ed25519_pub.hex(),
        fingerprint=fingerprint(user.ed25519_pub),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. COVER IMAGE ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/api/cover-image", tags=["Cover Images"])
async def get_cover_image(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Pop one unused 512×512 PNG cover image from the pool.
    The phone uses this as the canvas for LSB embedding. The server deletes
    its copy, so it cannot later diff the cover against the stego image.
    """
    image_data = await pop_cover(db)
    if not image_data:
        raise HTTPException(
            status_code=503,
            detail="Cover image pool is empty. The server is generating more — try again in a minute.",
        )
    return Response(content=image_data, media_type="image/png")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. MESSAGE ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post(
    "/api/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Messages"],
)
async def send_message(
    receiver_email: str = Form(..., description="Recipient's email address"),
    stego_image: UploadFile = File(..., description="Stego PNG with embedded payload"),
    sender: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a stego-PNG addressed to a receiver.
    The server stores the blob as-is — it cannot read the hidden payload.
    The upload must be a genuine, lossless 512×512 PNG under MAX_UPLOAD_BYTES.
    """
    receiver_email = _normalise_email(receiver_email)

    # Validate receiver exists
    result = await db.execute(select(User).where(User.email == receiver_email))
    receiver = result.scalars().first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")
    if receiver.id == sender.id:
        raise HTTPException(status_code=400, detail="Cannot send a message to yourself")

    image_bytes = await stego_image.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(image_bytes) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file is too large")
    _validate_stego_png(image_bytes)

    expires = datetime.now(timezone.utc) + timedelta(hours=settings.MESSAGE_TTL_HOURS)
    msg = Message(
        sender_id=sender.id,
        receiver_id=receiver.id,
        stego_image=image_bytes,
        expires_at=expires,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    log.info("[Msg] %s → %s  (id=%s, expires=%s)", sender.email, receiver.email, msg.id, expires)
    return SendMessageResponse(message_id=msg.id, expires_at=expires)


@app.get("/api/messages/inbox", response_model=InboxResponse, tags=["Messages"])
async def inbox(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all non-expired messages addressed to the current user.
    Returns metadata only — the actual stego image is downloaded separately.
    """
    result = await db.execute(
        select(Message)
        .options(selectinload(Message.sender))
        .where(
            Message.receiver_id == user.id,
            Message.expires_at > datetime.now(timezone.utc),
        )
        .order_by(Message.created_at.desc())
    )
    messages = result.scalars().all()

    return InboxResponse(
        messages=[
            MessageMeta(
                id=msg.id,
                sender_email=msg.sender.email,
                created_at=msg.created_at,
                expires_at=msg.expires_at,
            )
            for msg in messages
        ]
    )


@app.get("/api/messages/{message_id}/image", tags=["Messages"])
async def download_message_image(
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download the stego PNG for a specific message.
    Only the intended receiver can download it.
    """
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.receiver_id == user.id,
            Message.expires_at > datetime.now(timezone.utc),
        )
    )
    msg = result.scalars().first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found or expired")

    return Response(content=msg.stego_image, media_type="image/png")


@app.delete("/api/messages/{message_id}", tags=["Messages"])
async def delete_message(
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a message (allowed for both sender and receiver)."""
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            (Message.sender_id == user.id) | (Message.receiver_id == user.id),
        )
    )
    msg = result.scalars().first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.delete(msg)
    await db.commit()
    log.info("[Msg] Deleted message %s by user %s", message_id, user.email)
    return {"message": "Deleted"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. ADMIN / DEBUG ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/api/health", response_model=HealthResponse, tags=["Admin"])
async def health():
    """Health check — no auth required."""
    return HealthResponse(status="ok", service="CHISEL")


@app.get("/api/pool-status", response_model=PoolStatusResponse, tags=["Admin"])
async def pool_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check how many cover images are available in the pool."""
    unused = await get_unused_count(db)
    total = await get_total_count(db)
    return PoolStatusResponse(unused_covers=unused, total_covers=total)


@app.post("/api/admin/seed-pool", tags=["Admin"])
async def seed_pool(
    count: int = Query(5, ge=1, le=settings.ADMIN_SEED_MAX),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger pool refill.  Useful for initial setup or demo prep.
    Runs synchronously (blocks until all images are fetched).
    """
    log.info("[Admin] %s seeding %d cover image(s)", admin.email, count)
    added = await refill_pool(db, count)
    return {"message": f"Added {added} cover images to the pool"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _validate_stego_png(data: bytes) -> None:
    """Reject anything that is not a well-formed, lossless 512×512 PNG."""
    if len(data) < 100 or not data.startswith(PNG_MAGIC):
        raise HTTPException(status_code=400, detail="Upload must be a PNG image")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()  # checks chunk CRCs / structure
        with Image.open(io.BytesIO(data)) as img:
            fmt, size, mode = img.format, img.size, img.mode
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise HTTPException(status_code=400, detail="Upload is not a valid PNG image")

    expected = (settings.STEGO_IMAGE_SIZE, settings.STEGO_IMAGE_SIZE)
    if fmt != "PNG" or size != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Stego image must be a {expected[0]}×{expected[1]} PNG",
        )
    if mode not in ("RGB", "RGBA"):
        raise HTTPException(status_code=400, detail="Stego image must be RGB")
