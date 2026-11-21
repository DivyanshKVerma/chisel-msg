"""
CHISEL Server Configuration
Reads from environment variables / .env file.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings

DEFAULT_SECRET = "chisel-dev-secret-change-in-production"


class Settings(BaseSettings):
    # --- Environment ---
    # "development" (local / viva demo) or "production" (Railway)
    ENVIRONMENT: str = "development"

    # --- Database ---
    # Local dev  : sqlite+aiosqlite:///./chisel.db
    # Railway    : postgresql+asyncpg://user:pass@host/db  (auto-set by Railway)
    DATABASE_URL: str = "sqlite+aiosqlite:///./chisel.db"

    # --- Auth ---
    SECRET_KEY: str = DEFAULT_SECRET
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440          # 24 hours

    # --- OTP ---
    OTP_EXPIRE_SECONDS: int = 300           # 5 minutes
    OTP_MAX_ATTEMPTS: int = 5               # Wrong guesses before the code is burned
    OTP_RESEND_COOLDOWN_SECONDS: int = 30   # Min gap between two codes for one email
    # Return the OTP in the /api/register response (demo only — never in production)
    DEMO_RETURN_OTP: bool = True

    # --- Email (Brevo HTTPS API; free tier = 300 emails/day) ---
    # Leave BREVO_API_KEY empty locally: the OTP is then printed to the server log.
    BREVO_API_KEY: str = ""
    EMAIL_SENDER_ADDRESS: str = ""          # Must be a sender verified in Brevo
    EMAIL_SENDER_NAME: str = "CHISEL"

    # --- Rate limiting (per client IP, in-memory) ---
    AUTH_RATE_LIMIT_PER_MINUTE: int = 20

    # --- Identity reset ---
    # Replacing a pinned identity key (lost phone / cleared browser) needs a
    # token from an email-code sign-in no older than this.
    IDENTITY_RESET_MAX_TOKEN_AGE_SECONDS: int = 600

    # --- Admin ---
    # Comma-separated list of emails allowed to call /api/admin/*
    ADMIN_EMAILS: str = ""

    # --- CORS ---
    # Browser origins allowed to call the API, comma-separated. Empty = none,
    # which is right for a mobile-only (Flutter) client. "*" is for local dev only.
    CORS_ORIGINS: str = ""

    # --- Uploads ---
    MAX_UPLOAD_BYTES: int = 2 * 1024 * 1024  # 2 MiB; a 512×512 RGB PNG is < 800 KB
    STEGO_IMAGE_SIZE: int = 512

    # --- Cover Image Pool ---
    POLLINATIONS_API_KEY: str = ""
    # Keep a buffer of POOL_TARGET_SIZE covers. As soon as a sender takes one and
    # only POOL_REFILL_THRESHOLD remain, the server generates enough to refill.
    POOL_TARGET_SIZE: int = 5
    POOL_REFILL_THRESHOLD: int = 2
    POOL_CHECK_INTERVAL_SECONDS: int = 300  # safety net: re-check every 5 min
    ADMIN_SEED_MAX: int = 20                # Max images per manual seed call

    # --- Message TTL ---
    MESSAGE_TTL_HOURS: int = 24
    TTL_CLEANUP_INTERVAL_SECONDS: int = 3600  # 1 hour

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def admin_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def async_database_url(self) -> str:
        """
        Convert DATABASE_URL to the async driver format.

        Hosted Postgres URLs (Neon, Render, Supabase) are written for libpq,
        e.g. postgresql://u:p@host/db?sslmode=require&channel_binding=require.
        asyncpg does not understand `sslmode` or `channel_binding`, so:
          sslmode=require   → ssl=require
          channel_binding   → dropped (asyncpg negotiates SCRAM itself)
        """
        url = self.DATABASE_URL.strip()
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+asyncpg://" + url[len(prefix):]
                break
        if not url.startswith("postgresql+asyncpg://"):
            return url  # e.g. sqlite+aiosqlite:///./chisel.db

        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)
        if sslmode and "ssl" not in query:
            query["ssl"] = sslmode
        return urlunsplit(parts._replace(query=urlencode(query)))

    @property
    def uses_pgbouncer(self) -> bool:
        """Neon's pooled hostnames contain '-pooler' (PgBouncer, transaction mode)."""
        return "-pooler." in self.DATABASE_URL

    def check_production_safety(self) -> None:
        """Refuse to boot in production with demo-only settings."""
        if not self.is_production:
            return
        problems = []
        if self.SECRET_KEY == DEFAULT_SECRET or len(self.SECRET_KEY) < 32:
            problems.append("SECRET_KEY must be a random string of at least 32 characters")
        if self.DEMO_RETURN_OTP:
            problems.append("DEMO_RETURN_OTP must be false (OTPs must be emailed, not returned)")
        if not self.BREVO_API_KEY or not self.EMAIL_SENDER_ADDRESS:
            problems.append("BREVO_API_KEY and EMAIL_SENDER_ADDRESS are required to email OTPs")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must list real origins, not '*'")
        if problems:
            raise RuntimeError("Unsafe production config:\n  - " + "\n  - ".join(problems))

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
