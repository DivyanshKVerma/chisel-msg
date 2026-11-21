"""
CHISEL Authentication
JWT token creation/verification, OTP generation/hashing, rate limiting,
and the get_current_user / require_admin dependencies.
"""

import hashlib
import hmac
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt  # PyJWT (python-jose is unmaintained and has open CVEs)
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db
from .models import User

security = HTTPBearer()


# ── JWT ───────────────────────────────────────────────────

def create_token(user_id: str, email: str) -> str:
    """Create a signed JWT. `sub` = user id, `jti` makes every token unique."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and verify a JWT. Pins the algorithm and requires exp/sub."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type")
    return payload


# ── OTP ───────────────────────────────────────────────────

def generate_otp() -> str:
    """6-digit OTP from the OS CSPRNG (the `random` module is predictable)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(email: str, code: str) -> str:
    """
    Keyed hash of the OTP so a database leak does not reveal live codes.
    HMAC-SHA256(SECRET_KEY, email || code).
    """
    msg = f"{email.lower()}|{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def otp_matches(stored_hash: str, email: str, code: str) -> bool:
    """Constant-time comparison."""
    return hmac.compare_digest(stored_hash, hash_otp(email, code))


# ── Rate limiting (in-memory, per client IP) ──────────────
# Good enough for a single-instance deployment. Multi-instance → use Redis.

_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit_auth(request: Request) -> None:
    """Sliding-window limit on auth endpoints (register / verify)."""
    key = f"auth:{_client_ip(request)}"
    now = time.monotonic()
    window = _hits[key]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.AUTH_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication requests. Try again in a minute.",
        )
    window.append(now)


# ── FastAPI Dependencies ──────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Verify the Bearer token and return the matching User."""
    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Malformed token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Only emails listed in ADMIN_EMAILS may use admin routes."""
    if user.email.lower() not in settings.admin_emails:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
