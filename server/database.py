"""
CHISEL Database Layer
Async SQLAlchemy engine, session factory, and ORM base class.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

_engine_kwargs: dict = {"echo": False}
if settings.async_database_url.startswith("postgresql"):
    # Free-tier Postgres (Neon) suspends idle compute and drops connections:
    # pre-ping replaces dead pooled connections instead of failing a request.
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 300
    if settings.uses_pgbouncer:
        # PgBouncer in transaction mode can't keep prepared statements
        _engine_kwargs["connect_args"] = {"statement_cache_size": 0}

engine = create_async_engine(settings.async_database_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db():
    """FastAPI dependency — yields one DB session per request."""
    async with async_session() as session:
        yield session


async def init_db():
    """Create all tables on first startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
