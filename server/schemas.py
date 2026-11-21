"""
CHISEL Pydantic Schemas
Request/response models for the FastAPI endpoints.
"""

from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr, field_validator


# ── Auth ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    code: str


class VerifyOTPResponse(BaseModel):
    token: str
    user_id: str
    email: str
    display_name: str | None = None   # None → the app asks the new user for a name


# ── Profile ───────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    display_name: str

    @field_validator("display_name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())  # trim + collapse whitespace
        if not 1 <= len(v) <= 40:
            raise ValueError("Name must be 1 to 40 characters")
        if any(ord(ch) < 32 or 0x7F <= ord(ch) < 0xA0 for ch in v):
            raise ValueError("Name contains invalid characters")
        return v


class MeResponse(BaseModel):
    user_id: str
    email: str
    display_name: str | None


# ── Keys ──────────────────────────────────────────────────

class UploadKeysRequest(BaseModel):
    x25519_pub_hex: str    # 64 hex characters (32 bytes)
    ed25519_pub_hex: str   # 64 hex characters (32 bytes)
    x25519_sig_hex: str    # 128 hex characters: Ed25519 sig over the X25519 key
    # Replace a pinned identity key (new phone / cleared storage). Needs a
    # fresh email-code sign-in; contacts will see a safety-number change.
    reset_identity: bool = False


class PublicKeysResponse(BaseModel):
    user_id: str
    email: str
    x25519_pub_hex: str
    x25519_sig_hex: str
    ed25519_pub_hex: str
    fingerprint: str       # Safety number of the identity key, for out-of-band checks
    display_name: str | None = None


# ── Messages ──────────────────────────────────────────────

class MessageMeta(BaseModel):
    id: str
    sender_email: str
    sender_display_name: str | None = None
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def _as_utc(cls, v: datetime) -> datetime:
        # SQLite hands back naive datetimes; they are stored in UTC, so say so
        # explicitly — otherwise phones would read them in their local timezone.
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v

    model_config = {"from_attributes": True}


class InboxResponse(BaseModel):
    messages: list[MessageMeta]


class SendMessageResponse(BaseModel):
    message_id: str
    expires_at: datetime


# ── Pool / Health ─────────────────────────────────────────

class PoolStatusResponse(BaseModel):
    unused_covers: int
    total_covers: int      # Covers are deleted once handed out, so total == unused
    target_size: int       # Buffer size the server refills to
    refill_threshold: int  # Refill starts when this many (or fewer) are left
    refilling: bool        # A refill is running right now


class HealthResponse(BaseModel):
    status: str
    service: str
