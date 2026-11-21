"""
CHISEL Pydantic Schemas
Request/response models for the FastAPI endpoints.
"""

from datetime import datetime
from pydantic import BaseModel, EmailStr


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


# ── Keys ──────────────────────────────────────────────────

class UploadKeysRequest(BaseModel):
    x25519_pub_hex: str    # 64 hex characters (32 bytes)
    ed25519_pub_hex: str   # 64 hex characters (32 bytes)
    x25519_sig_hex: str    # 128 hex characters: Ed25519 sig over the X25519 key


class PublicKeysResponse(BaseModel):
    user_id: str
    email: str
    x25519_pub_hex: str
    x25519_sig_hex: str
    ed25519_pub_hex: str
    fingerprint: str       # Safety number of the identity key, for out-of-band checks


# ── Messages ──────────────────────────────────────────────

class MessageMeta(BaseModel):
    id: str
    sender_email: str
    created_at: datetime
    expires_at: datetime

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


class HealthResponse(BaseModel):
    status: str
    service: str
