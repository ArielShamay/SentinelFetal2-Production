"""
api/logging_config.py — Centralised logging setup.

Call setup_logging() once at application startup (in lifespan).
Creates two log files:
  logs/sentinel.log  — rotating, all levels
  logs/audit.log     — append-only, God Mode + alert transitions
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path = Path("logs")) -> None:
    """Configure root logger + dedicated audit logger."""
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Rotating file: 10 MB × 5 backups ─────────────────────────────────
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "sentinel.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)

    # ── Console (dev / docker stdout) ─────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Avoid double handlers if setup_logging is called again
    if not root.handlers:
        root.addHandler(fh)
        root.addHandler(ch)

    # ── Audit logger: append-only, separate file ──────────────────────────
    # Logs: alert on/off transitions, God Mode inject/end/clear, bed config changes
    audit = logging.getLogger("sentinel.audit")
    if not audit.handlers:
        ah = logging.FileHandler(log_dir / "audit.log", encoding="utf-8")
        ah.setFormatter(fmt)
        audit.addHandler(ah)
    audit.propagate = False   # don't double-log to root
