"""
api/middleware/god_mode_guard.py — PIN authentication for God Mode endpoints
============================================================================

Protects /api/god-mode/* endpoints with a PIN header (X-God-Mode-Pin).
Non-God-Mode endpoints pass through untouched.

PLAN.md reference: §11.6
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("sentinel.audit")


class GodModeGuard(BaseHTTPMiddleware):
    """Middleware that requires X-God-Mode-Pin header for /api/god-mode/* routes."""

    def __init__(self, app, pin: str) -> None:
        super().__init__(app)
        # Store hash — never keep plaintext PIN in memory longer than needed
        self._pin_hash = hashlib.sha256(pin.encode()).digest()

    async def dispatch(self, request: Request, call_next):
        # Only guard /api/god-mode paths
        if not request.url.path.startswith("/api/god-mode"):
            return await call_next(request)

        # Check PIN header
        provided_pin = request.headers.get("X-God-Mode-Pin", "")
        provided_hash = hashlib.sha256(provided_pin.encode()).digest()

        if not hmac.compare_digest(provided_hash, self._pin_hash):
            client_ip = request.client.host if request.client else "unknown"
            audit_logger.warning(
                "GOD_MODE_AUTH_FAIL | ip=%s path=%s", client_ip, request.url.path,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid or missing God Mode PIN"},
            )

        return await call_next(request)
