"""
CHISEL ORM Models
Tables: users, otps, messages, cover_images
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=True)

    # Public keys only — private keys NEVER touch the server
    # Ed25519 identity key is pinned once set; X25519 rotates daily and must be
    # signed by the identity key (x25519_sig) so the server cannot swap it alone.
    x25519_pub = Column(LargeBinary, nullable=True)   # 32 bytes
    x25519_sig = Column(LargeBinary, nullable=True)   # 64-byte Ed25519 signature
    ed25519_pub = Column(LargeBinary, nullable=True)   # 32 bytes
    key_uploaded_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    sent_messages = relationship(
        "Message", foreign_keys="Message.sender_id", back_populates="sender"
    )
    received_messages = relationship(
        "Message", foreign_keys="Message.receiver_id", back_populates="receiver"
    )


class OTP(Base):
    __tablename__ = "otps"

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, nullable=False, index=True)
    # HMAC-SHA256 of (email, code) — the plain code is never stored
    code_hash = Column(String(64), nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=_uuid)
    sender_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    receiver_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    # The stego PNG blob — server cannot read the payload inside it
    stego_image = Column(LargeBinary, nullable=False)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Relationships
    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver = relationship("User", foreign_keys=[receiver_id], back_populates="received_messages")


class CoverImage(Base):
    __tablename__ = "cover_images"

    id = Column(String, primary_key=True, default=_uuid)
    image_data = Column(LargeBinary, nullable=False)   # Raw 512×512 PNG bytes
    used = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
