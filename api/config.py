"""
api/config.py — Application settings via pydantic-settings.

All values can be overridden via environment variables or a .env file.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Server ────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ── Paths ─────────────────────────────────────────────────────────────
    recordings_dir: Path = Path("data/recordings")
    artifacts_dir: Path = Path("artifacts")
    weights_dir: Path = Path("weights")
    log_dir: Path = Path("logs")
    alert_log_path: Path = Path("data/alert_log.jsonl")

    # ── Simulation ────────────────────────────────────────────────────────
    default_bed_count: int = 4          # beds started at lifespan startup
    default_replay_speed: float = 10.0  # initial playback speed (1–20×)
    max_beds: int = 16

    # ── God Mode ──────────────────────────────────────────────────────────
    god_mode_enabled: bool = False      # override: GOD_MODE_ENABLED=true

    # ── CORS ──────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Module-level singleton — import from here everywhere
settings = Settings()
