"""
Campus Ballot — Configuration Module
Loads all settings from environment variables with sensible defaults.
"""

import os
import secrets
from pathlib import Path

# Load .env file if available (from backend or project root)
try:
    from dotenv import load_dotenv
    _env_paths = [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
    ]
    for _p in _env_paths:
        if _p.exists():
            load_dotenv(_p)
            break
    else:
        load_dotenv()
except ImportError:
    pass


class Settings:
    """Application settings loaded from environment variables."""

    # --- Security ---
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    SESSION_HOURS: int = int(os.getenv("SESSION_HOURS", "8"))
    PBKDF2_ITERATIONS: int = int(os.getenv("PBKDF2_ITERATIONS", "600000"))

    # --- Database (PostgreSQL or SQLite) ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    DATABASE_PATH: str = os.getenv(
        "DATABASE_PATH",
        "/data/campus_ballot.db"
        if os.path.exists("/data")
        else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "campus_ballot.db")),
    )

    # --- Admin bootstrap ---
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "Admin@Campus2026!")

    # --- Timezone ---
    APP_TIMEZONE: str = os.getenv("APP_TIMEZONE", "Asia/Kolkata")

    # --- Runtime ---
    PORT: int = int(os.getenv("PORT", "10000"))

    def __init__(self) -> None:
        # In production (COOKIE_SECURE=true), SECRET_KEY must be set explicitly.
        if self.COOKIE_SECURE and not self.SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY environment variable is required in production "
                "(COOKIE_SECURE=true). Set it to a long random string."
            )
        # For local development, generate an ephemeral key so devs can start fast.
        if not self.SECRET_KEY:
            self.SECRET_KEY = secrets.token_hex(32)


settings = Settings()
