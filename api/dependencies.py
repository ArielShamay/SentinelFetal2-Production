"""
api/dependencies.py — FastAPI Depends() helpers.

Usage:
    from api.dependencies import get_manager, get_broadcaster, get_engine

    @router.get("/...")
    async def handler(mgr: PipelineManager = Depends(get_manager)): ...
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from api.services.pipeline_manager import PipelineManager
    from api.services.broadcaster import AsyncBroadcaster
    from generator.replay import ReplayEngine


def get_manager(request: Request) -> "PipelineManager":
    return request.app.state.manager


def get_broadcaster(request: Request) -> "AsyncBroadcaster":
    return request.app.state.broadcaster


def get_engine(request: Request) -> "ReplayEngine":
    return request.app.state.engine
