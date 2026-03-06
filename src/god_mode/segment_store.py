"""
src/god_mode/segment_store.py — Pathology segment catalog for God Mode
======================================================================

Loads the pre-built catalog (data/god_mode_catalog.json) at startup and
provides segment selection per event type.

When God Mode injects an event, SegmentStore picks a real recording that
contains that pathology, so the CTG graph shows authentic pathological data.

See docs/god_mode_signal_plan.md for full design.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)


class SegmentStore:
    """Loaded at startup. Provides recording selection per event type."""

    def __init__(self, catalog_path: Path | str = Path("data/god_mode_catalog.json")) -> None:
        catalog_path = Path(catalog_path)
        if not catalog_path.exists():
            logger.warning(
                "God Mode catalog not found at %s — signal swap will be unavailable. "
                "Run: python scripts/catalog_pathologies.py",
                catalog_path,
            )
            self._catalog: dict[str, list[dict]] = {}
            return

        with open(catalog_path, encoding="utf-8") as f:
            data = json.load(f)

        self._catalog = data.get("catalog", {})
        total = sum(len(v) for v in self._catalog.values())
        logger.info(
            "SegmentStore loaded: %d entries across %d event types from %s",
            total,
            len([k for k, v in self._catalog.items() if v]),
            catalog_path,
        )

    def get_segment(self, event_type: str) -> dict | None:
        """Return a suitable segment for the given event type, or None.

        Selects randomly from top 3 matches for variety.
        Returns dict with at least: {"recording_id": str, "best_start_sample": int}
        """
        entries = self._catalog.get(event_type, [])
        if not entries:
            return None
        top = entries[: min(3, len(entries))]
        return random.choice(top)

    def has_segments(self, event_type: str) -> bool:
        """Check if any segments are available for this event type."""
        return bool(self._catalog.get(event_type))

    def available_types(self) -> list[str]:
        """Return event types that have at least one catalog entry."""
        return [k for k, v in self._catalog.items() if v]
